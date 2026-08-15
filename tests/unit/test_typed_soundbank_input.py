from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import pytest

from tests.semantic.support.codex_eval_protocol_v3 import build_transaction_protocol
from tests.semantic.support.codex_gateway_broker import ResponseBinding
from wwise_waapi.operation_composer import (
    OPERATION_COMPOSITION_CONTRACT,
    materialize_operation_request,
)
from wwise_waapi.operation_registry import parse_operation_request
from wwise_waapi.typed_operations import (
    draft_operation_request_contract,
    inline_operation_contract,
)
from wwise_waapi.typed_requests import (
    MAX_TYPED_ARRAY_ITEMS,
    TypedRequestFact,
    dynamic_array_item_handle,
    dynamic_branch_choices,
    dynamic_container_disclosure,
    dynamic_map_entry_handle,
    materialize_typed_request,
    typed_request_construction_for_values,
)
from wwise_waapi.transactions import TransactionStore


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_typed_soundbank_gateway", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)

ALL_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
FOUR_VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")
OPERATIONS = {
    "soundbank.generate": ALL_VERSIONS,
    "soundbank.setInclusions": ALL_VERSIONS,
    "soundbank.convertExternalSources": FOUR_VERSIONS,
    "soundbank.processDefinitionFiles": FOUR_VERSIONS,
}
BANK_ID = "{11111111-1111-1111-1111-111111111111}"
EVENT_ID = "{22222222-2222-2222-2222-222222222222}"


class _InclusionClient:
    def __init__(self, tmp_path: Path) -> None:
        project = tmp_path.parent / f"{tmp_path.name}-project" / "SampleProject.wproj"
        project.parent.mkdir(exist_ok=True)
        if not project.exists():
            project.write_text("<Project/>", encoding="utf-8")
        self.project = project
        self.calls: list[str] = []

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append(uri)
        if uri == "ak.wwise.core.getInfo":
            return {
                "displayName": "Wwise",
                "isCommandLine": True,
                "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "processId": 42,
                "processPath": "/Applications/Wwise.app/Contents/MacOS/Wwise",
                "apiVersion": 1,
                "platform": "macosx",
                "configuration": "release",
                "version": {"year": 2025, "major": 1, "minor": 0, "build": 1},
            }
        if uri == "ak.wwise.core.getProjectInfo":
            return {
                "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "name": "SampleProject",
                "path": str(self.project),
            }
        if uri == "ak.wwise.core.object.get":
            return {
                "return": [
                    {
                        "id": BANK_ID,
                        "name": "Harbor",
                        "type": "SoundBank",
                        "path": r"\SoundBanks\Default Work Unit\Harbor",
                        "parent": {"id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"},
                        "notes": "",
                    }
                ]
            }
        if uri == "ak.wwise.core.soundbank.getInclusions":
            return {
                "inclusions": [
                    {"object": {"id": EVENT_ID}, "filter": ["events"]}
                ]
            }
        raise AssertionError((uri, args, options))

    def disconnect(self) -> None:
        pass


def _env(tmp_path: Path, version: str) -> dict[str, str]:
    config = tmp_path / f"config-{version}.json"
    config.write_text(
        json.dumps({"wwise_version": version, "project_modification_policy": "ask_before_changes"}),
        encoding="utf-8",
    )
    return {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_WAAPI_PORT": "8080"}


def _field(contract, path: tuple[str, ...], *, shape: str | None = None):
    return next(
        field
        for field in contract.fields
        if field.path == path
        and field.parent_handle is None
        and (shape is None or field.shape == shape)
    )


def _identity_facts(contract, path: tuple[str, ...], value: str) -> list[TypedRequestFact]:
    branch = _field(contract, path, shape="branch")
    object_branch = next(
        field
        for field in contract.fields
        if field.parent_handle == branch.handle and field.name == "object:0"
    )
    kind = next(field for field in contract.fields if field.parent_handle == object_branch.handle and field.name == "kind")
    selector_value = next(field for field in contract.fields if field.parent_handle == object_branch.handle and field.name == "value")
    return [
        TypedRequestFact("choose", branch.handle, "branch", object_branch.handle),
        TypedRequestFact("set", kind.handle, "string", "id"),
        TypedRequestFact("set", selector_value.handle, "string", value),
    ]


def _composition(contract, facts: list[TypedRequestFact]) -> dict[str, object]:
    return {
        "contract": OPERATION_COMPOSITION_CONTRACT,
        "typed_request_schema_digest": contract.schema_digest,
        "facts": [
            {
                "handle": f"tdh1-{index:024x}",
                "fact_action": fact.action,
                "field_handle": fact.handle,
                "value_type": fact.value_type,
                "value": fact.value,
                **({"key": fact.key} if fact.key is not None else {}),
            }
            for index, fact in enumerate(facts)
        ],
    }


def _dynamic_identity_facts(
    contract,
    *,
    parent_handle: str,
    parent_schema: Mapping[str, Any],
    key: str,
    selector: Mapping[str, Any],
) -> list[TypedRequestFact]:
    """Build one identity only from the Core's disclosed dynamic contract."""

    value_schema = parent_schema["properties"][key]
    choices = dynamic_branch_choices(
        contract,
        object_handle=parent_handle,
        key=key,
        value_schema=value_schema,
    )
    choice_handle = next(
        handle
        for handle, variant in choices
        if variant["properties"]["kind"].get("const") == selector["kind"]
    )
    identity_handle = dynamic_map_entry_handle(
        contract,
        map_handle=parent_handle,
        key=key,
        shape="object",
        choice_handle=choice_handle,
        parent_schema=parent_schema,
    )
    identity_disclosure = dynamic_container_disclosure(
        contract,
        parent_handle=parent_handle,
        key=key,
        shape="object",
        child_handle=identity_handle,
        parent_schema=parent_schema,
        choice_handle=choice_handle,
    )
    identity_schema = identity_disclosure["schema_lineage"]
    facts = [
        TypedRequestFact("choose-dynamic", parent_handle, "choice", choice_handle, key=key),
        TypedRequestFact("map-put", parent_handle, "object", identity_handle, key=key),
    ]
    for property_name, property_schema in identity_schema["properties"].items():
        if property_name == "parent":
            facts.extend(
                _dynamic_identity_facts(
                    contract,
                    parent_handle=identity_handle,
                    parent_schema=identity_schema,
                    key="parent",
                    selector=selector["parent"],
                )
            )
            continue
        value = selector.get(property_name, property_schema.get("const"))
        assert value is not None
        value_type = (
            "boolean"
            if isinstance(value, bool)
            else "integer"
            if isinstance(value, int)
            else "string"
        )
        if isinstance(property_schema.get("type"), list) or isinstance(
            property_schema.get("oneOf"), list
        ):
            branch_choices = next(
                item["choices"]
                for item in identity_disclosure["branch_choices"]
                if item["key"] == property_name
            )
            scalar_choice = next(
                choice["handle"]
                for choice in branch_choices
                if value_type in choice["accepted_types"]
            )
            facts.append(
                TypedRequestFact(
                    "choose-dynamic",
                    identity_handle,
                    "choice",
                    scalar_choice,
                    key=property_name,
                )
            )
        facts.append(
            TypedRequestFact(
                "map-put",
                identity_handle,
                value_type,
                str(value).lower() if isinstance(value, bool) else str(value),
                key=property_name,
            )
        )
    return facts


def _inclusion_row_facts(
    contract,
    *,
    index: int,
    selector: Mapping[str, Any],
    filters: tuple[str, ...] = ("events",),
) -> list[TypedRequestFact]:
    inclusions = _field(contract, ("inclusions",), shape="array")
    row_handle = dynamic_array_item_handle(
        contract,
        array_handle=inclusions.handle,
        index=index,
        shape="object",
    )
    row_disclosure = dynamic_container_disclosure(
        contract,
        parent_handle=inclusions.handle,
        key=str(index),
        shape="object",
        child_handle=row_handle,
    )
    row_schema = row_disclosure["schema_lineage"]
    filters_handle = dynamic_map_entry_handle(
        contract,
        map_handle=row_handle,
        key="filters",
        shape="array",
        parent_schema=row_schema,
    )
    return [
        TypedRequestFact("append", inclusions.handle, "object", row_handle),
        *_dynamic_identity_facts(
            contract,
            parent_handle=row_handle,
            parent_schema=row_schema,
            key="object",
            selector=selector,
        ),
        TypedRequestFact("map-put", row_handle, "array", filters_handle, key="filters"),
        *(
            TypedRequestFact("append", filters_handle, "string", value)
            for value in filters
        ),
    ]


def _apply_facts(
    tmp_path: Path,
    *,
    state_dir: Path,
    started: Mapping[str, Any],
    facts: list[TypedRequestFact],
) -> int:
    revision = 1
    for fact in facts:
        argv = [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-apply", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(revision), "--facts",
            "--action", "add_typed_fact", "--fact-action", fact.action,
            "--field-handle", fact.handle,
        ]
        if fact.action == "choose":
            argv += ["--fact-value", fact.value]
        elif fact.action == "present":
            pass
        else:
            argv += ["--value-type", fact.value_type, "--fact-value", fact.value]
        code, payload = gateway.execute_gateway(
            argv,
            env=_env(tmp_path, "2025.1"),
            client_factory=lambda url: pytest.fail(f"draft-apply connected to {url}"),
        )
        assert code == 0, payload
        revision = payload["draft"]["revision"]
    return revision


@pytest.mark.parametrize(
    ("operation", "version"),
    [(operation, version) for operation, versions in OPERATIONS.items() for version in versions],
)
def test_every_soundbank_lane_is_one_public_typed_draft(
    tmp_path: Path, operation: str, version: str
) -> None:
    expected_shape = (
        "inline" if operation == "soundbank.processDefinitionFiles" else "draft"
    )
    if expected_shape == "inline":
        contract = inline_operation_contract(operation, version)
        assert contract["operation"] == operation
        assert contract["input_shape"] == "inline"
    else:
        contract = draft_operation_request_contract(operation, version)
        assert contract.uri == operation
        assert contract.as_gateway_payload()["input_shape"] == "draft"

    code, schema = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )
    assert code == 0, schema
    assert schema["operation"]["input_mode"] == (
        "inline_typed" if expected_shape == "inline" else "composer"
    )
    if expected_shape == "inline":
        continuation = schema["typed_operation"]["continuation"]
        assert continuation["subcommand"] == "typed-operation"
        assert continuation["schema_digest"] == schema["typed_operation"]["schema_digest"]
        assert continuation["gateway_argv_prefix"] == [
            "typed-operation",
            operation,
            "--schema-digest",
            schema["typed_operation"]["schema_digest"],
            "--apply",
        ]
        return
    assert schema["composer"]["start"]["subcommand"] == "draft-start"

    code, started = gateway.execute_gateway(
        ["--version", version, "--state-dir", str(tmp_path / f"state-{operation}-{version}"), "draft-start", operation],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    assert code == 0, started
    assert started["draft"]["binding"]["operation"] == operation


def test_set_inclusions_discloses_selector_branch_constants(tmp_path: Path) -> None:
    code, schema = gateway.execute_gateway(
        ["--version", "2025.1", "operation-schema", "soundbank.setInclusions"],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"operation-schema connected to {url}"),
    )
    assert code == 0, schema
    payload = {"fields": schema["composer"]["typed_request_fields"]}
    soundbank = next(
        field
        for field in payload["fields"]
        if field["path"] == ["args", "soundbank"] and field["shape"] == "branch"
    )
    choices = [
        field
        for field in payload["fields"]
        if field.get("parent_handle") == soundbank["handle"]
    ]
    assert [choice["branch_choice_constants"] for choice in choices] == [
        {"kind": "id"},
        {"kind": "path"},
        {"kind": "exact-type-name"},
        {"kind": "direct-child"},
        {"kind": "scoped-name"},
    ]

    inclusions = next(
        field
        for field in schema["composer"]["typed_request_fields"]
        if field["path"] == ["args", "inclusions"]
    )
    digest = schema["composer"]["typed_request_schema_digest"]
    item_code, item = gateway.execute_gateway(
        [
            "--version", "2025.1", "request-array-item", "soundbank.setInclusions",
            "--schema-digest", digest,
            "--array-handle", inclusions["handle"],
            "--index", "0", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"array disclosure connected to {url}"),
    )
    assert item_code == 0, item
    construction = typed_request_construction_for_values(
        draft_operation_request_contract("soundbank.setInclusions", "2025.1"),
        args={
            "soundbank": {"kind": "id", "value": BANK_ID},
            "mode": "add",
            "inclusions": [
                {
                    "object": {"kind": "id", "value": EVENT_ID},
                    "filters": ["events"],
                }
            ],
        },
        options={},
    )
    assert [
        (disclosure.command, disclosure.key, disclosure.shape)
        for disclosure in construction.disclosures
    ] == [
        ("request-array-item", "0", "object"),
        ("request-map-container", "object", "object"),
        ("request-map-container", "filters", "array"),
    ]
    nested = item["continuation"]["nested_container_disclosures"]
    assert [(row["key"], row["shape"]) for row in nested] == [
        ("filters", "array"),
    ]
    assert item["continuation"]["nested_container_order"] == (
        "for the current array item, follow branch_disclosure first, then "
        "disclose every business-present member and its descendants in this "
        "order before the next sibling; after the current root disclosures, "
        "drain its deferred facts"
    )
    assert item["continuation"]["request_wide_order"] == {
        "phase": "dynamic_disclosure",
        "finish_current_root_disclosure_chain_first": True,
        "disclosure_chain_definition": (
            "only branch_disclosure and nested_container_disclosures; "
            "child_contract branch choices are typed facts"
        ),
        "array_item_order": "ascending_business_present_index",
        "array_item_traversal": (
            "response_tree_preorder_finish_item_descendants_before_next_sibling"
        ),
        "absent_array_item_disclosure_forbidden": True,
        "nested_member_order": "schema_property_order",
        "child_fact_order": "child_contract_schema_order",
        "facts_using_returned_handles": (
            "after_current_root_dynamic_disclosures_in_deferred_fact_queue_order"
        ),
        "deferred_fact_queue": {
            "scope": "current_disclosed_root",
            "root_boundary": (
                "current_root_disclosures_then_current_root_facts_before_next_root"
            ),
            "drain_after": "root_dynamic_disclosures",
            "traversal": "response_tree_preorder",
            "node_steps": [
                "deferred_parent_fact",
                "child_contract_facts",
                "descendant_response_nodes",
            ],
            "parent_dependency": (
                "deferred_parent_fact_before_every_fact_using_response_handle"
            ),
            "array_traversal": "response_tree_preorder_within_current_root",
            "sibling_order": "ascending_business_present_index",
        },
        "this_handle_is_not_a_complete_request": True,
    }
    assert item["continuation"]["deferred_fact"]["argv"] == [
        "--action", "add_typed_fact", "--fact-action", "append",
        "--field-handle", inclusions["handle"], "--value-type", "object",
        "--fact-value", item["handle"],
    ]
    assert item["continuation"]["deferred_fact"]["must_precede"] == {
        "all_facts_with_field_handle": item["handle"],
        "reason": "attach_returned_handle_to_its_parent_first",
    }
    assert "action_argv" not in item["continuation"]
    branch_argv = [
        "object" if token == "<exact-key>" else token
        for token in item["continuation"]["branch_disclosure"]
    ]
    assert "--member-key" not in branch_argv
    item_choices = item["child_contract"]["branch_choices"][0]["choices"]
    id_choice = item_choices[0]["handle"]
    choice_argv = [
        id_choice
        if token == "<selected-choice-handle-from-child_contract>"
        else token
        for token in branch_argv
    ]
    protocol = build_transaction_protocol(
        (
            {
                "contract": "waapi-skill.operation-request/v1",
                "version": "2025.1",
                "operation": "soundbank.setInclusions",
                "arguments": {
                    "soundbank": {"kind": "id", "value": BANK_ID},
                    "mode": "add",
                    "inclusions": [
                        {
                            "object": {"kind": "id", "value": EVENT_ID},
                            "filters": ["events"],
                        }
                    ],
                },
            },
        )
    )
    protocol_disclosure = next(
        step for step in protocol.steps if step.name == "tx01.disclose.002"
    )

    def resolve_item_binding(value: object) -> object:
        if not isinstance(value, ResponseBinding):
            return value
        assert value.step == "tx01.disclose.001"
        current: object = item
        for token in value.pointer.removeprefix("/").split("/"):
            assert isinstance(current, (dict, list))
            current = (
                current[int(token)] if isinstance(current, list) else current[token]
            )
        return current

    assert tuple(choice_argv[1:]) == tuple(
        resolve_item_binding(value) for value in protocol_disclosure.arguments
    )
    assert choice_argv.index("--parent-schema-token") < choice_argv.index(
        "--choice-handle"
    )
    identity_code, identity = gateway.execute_gateway(
        ["--version", "2025.1", *choice_argv],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"identity disclosure connected to {url}"),
    )
    assert identity_code == 0, identity
    assert identity["parent_handle"] == item["handle"]
    assert identity["handle"] != item["handle"]
    assert identity["child_contract"]["required_keys"] == ["kind", "value"]
    assert identity["child_contract"]["constant_fields"] == {"kind": "id"}
    assert identity["child_contract"]["constant_field_facts"] == [
        {
            "typed_fact": {
                "action": "map-put",
                "handle": identity["handle"],
                "key": "kind",
                "value_type": "string",
                "value": "id",
            },
            "deferred_fact": {
                "argv": [
                    "--action", "add_typed_fact", "--fact-action", "map-put",
                    "--field-handle", identity["handle"], "--value-type", "string",
                    "--fact-value", "id", "--key", "kind",
                ],
                "execute_after": "deferred_parent_fact",
                "queue_phase": "child_contract",
                    "queue_order_ref": (
                        "/continuation/request_wide_order/deferred_fact_queue"
                    ),
                    "is_next_command": False,
                    "consume_once": True,
                    "replay_allowed": False,
                },
        }
    ]
    assert "branch_disclosure" not in identity["continuation"]
    assert "action_argv" not in identity["continuation"]
    assert identity["continuation"]["deferred_fact"]["argv"] == [
        "--action", "add_typed_fact", "--fact-action", "map-put",
        "--field-handle", item["handle"], "--value-type", "object",
        "--fact-value", identity["handle"], "--key", "object",
    ]
    assert identity["continuation"]["deferred_fact"]["must_precede"] == {
        "all_facts_with_field_handle": identity["handle"],
        "reason": "attach_returned_handle_to_its_parent_first",
    }

    for contradiction in (
        ["--shape", "array"],
        ["--shape", "object", "--choice-handle", "trc1-000000000000000000000000"],
    ):
        rejected_code, rejected = gateway.execute_gateway(
            [
                "--version", "2025.1", "request-map-container",
                "soundbank.setInclusions", "--schema-digest", digest,
                "--map-handle", item["handle"], "--key", "object",
                *contradiction,
                "--parent-schema-token", item["schema_lineage_token"],
            ],
            env=_env(tmp_path, "2025.1"),
            client_factory=lambda url: pytest.fail(
                f"invalid member disclosure connected to {url}"
            ),
        )
        assert rejected_code == 2, rejected


def test_file_operations_materialize_exact_paths_without_rewriting_sources(tmp_path: Path) -> None:
    io_root = tmp_path / "I O 根"
    io_root.mkdir()
    source = io_root / "External Sources.wsources"
    source.write_text("<ExternalSourcesList/>", encoding="utf-8")
    definition = io_root / "Definition File.tsv"
    definition.write_text("SoundBank\tObject\n", encoding="utf-8")

    convert = draft_operation_request_contract("soundbank.convertExternalSources", "2025.1")
    sources = _field(convert, ("sources",), shape="array")
    row = dynamic_array_item_handle(convert, array_handle=sources.handle, index=0, shape="object")
    convert_facts = [
        TypedRequestFact("append", sources.handle, "object", row),
        TypedRequestFact("map-put", row, "string", str(source), key="input"),
        TypedRequestFact("map-put", row, "string", "Windows", key="platform"),
        TypedRequestFact("map-put", row, "string", str(io_root / "Output Files"), key="output"),
        TypedRequestFact("set", _field(convert, ("io_root",)).handle, "string", str(io_root)),
    ]
    converted = materialize_operation_request(
        "soundbank.convertExternalSources", "2025.1", _composition(convert, convert_facts)
    )
    assert converted["arguments"]["sources"][0]["input"] == str(source)
    assert source.read_text(encoding="utf-8") == "<ExternalSourcesList/>"
    parse_operation_request(converted, expected_version="2025.1")

    processed = gateway.materialize_inline_operation_request(
        "soundbank.processDefinitionFiles",
        "2025.1",
        {"files": (str(definition),), "io_root": str(io_root)},
    )
    assert processed["arguments"] == {"files": [str(definition)], "io_root": str(io_root)}
    assert definition.read_text(encoding="utf-8") == "SoundBank\tObject\n"
    parse_operation_request(processed, expected_version="2025.1")


def test_generate_and_replace_empty_inclusions_materialize_exact_operation_contracts(tmp_path: Path) -> None:
    generate = draft_operation_request_contract("soundbank.generate", "2025.1")
    banks = _field(generate, ("soundbanks",), shape="array")
    bank = dynamic_array_item_handle(generate, array_handle=banks.handle, index=0, shape="object")
    facts = [
        TypedRequestFact("append", banks.handle, "object", bank),
        TypedRequestFact("map-put", bank, "string", "Harbor", key="name"),
        TypedRequestFact("map-put", bank, "string", "nonlocalized", key="artifact_expectation"),
        TypedRequestFact("append", _field(generate, ("platforms",)).handle, "string", "Windows"),
        TypedRequestFact("set", _field(generate, ("skip_languages",)).handle, "boolean", "true"),
        TypedRequestFact("set", _field(generate, ("write_to_disk",)).handle, "boolean", "true"),
        TypedRequestFact("set", _field(generate, ("io_root",)).handle, "string", str(tmp_path)),
    ]
    request = materialize_operation_request(
        "soundbank.generate", "2025.1", _composition(generate, facts)
    )
    assert request["arguments"]["soundbanks"] == [
        {"name": "Harbor", "artifact_expectation": "nonlocalized"}
    ]
    parse_operation_request(request, expected_version="2025.1")

    inclusions = draft_operation_request_contract("soundbank.setInclusions", "2025.1")
    inclusion_facts = [
        *_identity_facts(inclusions, ("soundbank",), BANK_ID),
        TypedRequestFact("set", _field(inclusions, ("mode",)).handle, "string", "replace"),
        TypedRequestFact("present", _field(inclusions, ("inclusions",)).handle, "null", "null"),
    ]
    replaced = materialize_operation_request(
        "soundbank.setInclusions", "2025.1", _composition(inclusions, inclusion_facts)
    )
    assert replaced["arguments"]["inclusions"] == []
    parse_operation_request(replaced, expected_version="2025.1")


@pytest.mark.parametrize(
    "selector",
    [
        {"kind": "id", "value": EVENT_ID},
        {"kind": "id", "value": 42},
        {"kind": "path", "value": r"\Events\Default Work Unit\Play_Harbor"},
        {"kind": "exact-type-name", "type": "Event", "name": "Play_Harbor"},
        {
            "kind": "direct-child",
            "parent": {"kind": "path", "value": r"\Events\Default Work Unit"},
            "type": "Event",
        },
        {
            "kind": "scoped-name",
            "parent": {"kind": "id", "value": BANK_ID},
            "type": "Event",
            "name": "Play_Harbor",
        },
    ],
)
def test_nonempty_inclusion_rows_materialize_every_closed_selector_shape(
    selector: Mapping[str, Any],
) -> None:
    contract = draft_operation_request_contract("soundbank.setInclusions", "2025.1")
    facts = [
        *_identity_facts(contract, ("soundbank",), BANK_ID),
        TypedRequestFact("set", _field(contract, ("mode",)).handle, "string", "add"),
        *_inclusion_row_facts(contract, index=0, selector=selector),
    ]
    request = materialize_operation_request(
        "soundbank.setInclusions", "2025.1", _composition(contract, facts)
    )
    assert request["arguments"]["inclusions"] == [
        {"object": selector, "filters": ["events"]}
    ]
    parse_operation_request(request, expected_version="2025.1")


def test_set_inclusions_exact_reviewed_row_limit_materializes() -> None:
    contract = draft_operation_request_contract("soundbank.setInclusions", "2025.1")
    facts = [
        *_identity_facts(contract, ("soundbank",), BANK_ID),
        TypedRequestFact("set", _field(contract, ("mode",)).handle, "string", "replace"),
    ]
    for index in range(128):
        facts.extend(
            _inclusion_row_facts(
                contract,
                index=index,
                selector={
                    "kind": "id",
                    "value": f"{{{index:08X}-2222-2222-2222-222222222222}}",
                },
            )
        )
    request = materialize_operation_request(
        "soundbank.setInclusions", "2025.1", _composition(contract, facts)
    )
    assert len(request["arguments"]["inclusions"]) == 128

    overflow_facts = [
        *facts,
        *_inclusion_row_facts(
            contract,
            index=128,
            selector={"kind": "id", "value": EVENT_ID},
        ),
    ]
    with pytest.raises(Exception, match="at most 128 items"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=overflow_facts,
        )


def test_public_draft_apply_rejects_inclusion_row_129_atomically(
    tmp_path: Path,
) -> None:
    operation = "soundbank.setInclusions"
    state_dir = tmp_path / "state-inclusion-limit"
    contract = draft_operation_request_contract(operation, "2025.1")
    inclusions = _field(contract, ("inclusions",), shape="array")
    code, started = gateway.execute_gateway(
        ["--version", "2025.1", "--state-dir", str(state_dir), "draft-start", operation],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    assert code == 0, started
    accepted = [
        TypedRequestFact(
            "append",
            inclusions.handle,
            "object",
            dynamic_array_item_handle(
                contract,
                array_handle=inclusions.handle,
                index=index,
                shape="object",
            ),
        )
        for index in range(128)
    ]
    revision = _apply_facts(
        tmp_path,
        state_dir=state_dir,
        started=started,
        facts=accepted,
    )
    record_before = gateway.OperationDraftStore(state_dir).inspect(
        started["draft"]["draft_id"], task_authority=started["task_authority"]
    )
    overflow = TypedRequestFact(
        "append",
        inclusions.handle,
        "object",
        dynamic_array_item_handle(
            contract,
            array_handle=inclusions.handle,
            index=128,
            shape="object",
        ),
    )
    failure_code, failure = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-apply", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(revision), "--facts",
            "--action", "add_typed_fact", "--fact-action", "append",
            "--field-handle", overflow.handle,
            "--value-type", overflow.value_type,
            "--fact-value", overflow.value,
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"draft-apply connected to {url}"),
    )
    assert failure_code == 2
    assert failure["error_code"] == "OPERATION_DRAFT_ACTION_INVALID"
    record_after = gateway.OperationDraftStore(state_dir).inspect(
        started["draft"]["draft_id"], task_authority=started["task_authority"]
    )
    assert record_after.revision == record_before.revision == 129
    assert record_after.composition == record_before.composition


def test_soundbank_draft_rejects_cross_operation_schema_digest() -> None:
    generate = draft_operation_request_contract("soundbank.generate", "2025.1")
    process = draft_operation_request_contract("soundbank.convertExternalSources", "2025.1")
    with pytest.raises(Exception, match="digest"):
        materialize_operation_request(
            "soundbank.generate", "2025.1", _composition(process, [])
        )
    assert generate.schema_digest != process.schema_digest


@pytest.mark.parametrize(
    ("operation", "path", "limit"),
    [
        ("soundbank.generate", ("platforms",), 16),
        ("soundbank.generate", ("languages",), 64),
        ("soundbank.setInclusions", ("inclusions",), 128),
    ],
)
def test_soundbank_collection_limits_are_registry_owned_and_disclosed(
    operation: str, path: tuple[str, ...], limit: int
) -> None:
    contract = draft_operation_request_contract(operation, "2025.1")
    assert _field(contract, path, shape="array").maximum_items == limit


def test_generate_identity_collection_limit_is_registry_owned() -> None:
    contract = draft_operation_request_contract("soundbank.generate", "2025.1")
    banks = _field(contract, ("soundbanks",), shape="array")
    row = dynamic_array_item_handle(
        contract, array_handle=banks.handle, index=0, shape="object"
    )
    disclosure = gateway.dynamic_container_disclosure(
        contract,
        parent_handle=banks.handle,
        key="0",
        shape="object",
        child_handle=row,
        member_key="events",
    )
    assert disclosure["schema_lineage"]["properties"]["events"]["maxItems"] == (
        MAX_TYPED_ARRAY_ITEMS
    )


def test_public_set_inclusions_draft_checks_and_seals_one_immutable_preview(
    tmp_path: Path,
) -> None:
    operation = "soundbank.setInclusions"
    state_dir = tmp_path / "state-inclusions"
    contract = draft_operation_request_contract(operation, "2025.1")
    start_code, started = gateway.execute_gateway(
        ["--version", "2025.1", "--state-dir", str(state_dir), "draft-start", operation],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    assert start_code == 0, started
    facts = [
        *_identity_facts(contract, ("soundbank",), BANK_ID),
        TypedRequestFact("set", _field(contract, ("mode",)).handle, "string", "replace"),
        TypedRequestFact("present", _field(contract, ("inclusions",)).handle, "null", "null"),
    ]
    revision = _apply_facts(
        tmp_path, state_dir=state_dir, started=started, facts=facts
    )
    expected = materialize_operation_request(
        operation,
        "2025.1",
        gateway.OperationDraftStore(state_dir).inspect(
            started["draft"]["draft_id"], task_authority=started["task_authority"]
        ).composition,
    )
    check_code, checked = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-check", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(revision),
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: _InclusionClient(tmp_path),
    )
    assert check_code == 0, json.dumps(checked, indent=2)
    checked_revision = checked["draft"]["revision"]
    preview_code, previewed = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "preview-from-draft", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(checked_revision), "--apply",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: _InclusionClient(tmp_path),
    )
    assert preview_code == 0, previewed
    assert previewed["agent_result"]["request"] == expected
    stored = TransactionStore(state_dir).load_preview(previewed["transaction_id"])
    assert stored.artifact["request"] == expected
