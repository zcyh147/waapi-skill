from __future__ import annotations

import importlib.util
import json
from collections import deque
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import pytest

from wwise_waapi.operation_composer import (
    OPERATION_COMPOSITION_CONTRACT,
    materialize_operation_request,
)
from wwise_waapi.operation_registry import parse_operation_request
from wwise_waapi.typed_operations import draft_operation_request_contract
from wwise_waapi.typed_requests import (
    MAX_TYPED_ARRAY_ITEMS,
    MAX_TYPED_REQUEST_FACTS,
    MAX_TYPED_REQUEST_BYTES,
    MAX_TYPED_STRING_BYTES,
    TypedRequestFact,
    dynamic_array_item_handle,
    dynamic_container_disclosure,
    materialize_typed_request,
)
from wwise_waapi.transactions import TransactionStore


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_typed_plugin_rtpc_gateway", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)

VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")
TARGET_ID = "{11111111-1111-1111-1111-111111111111}"
CONTROL_ID = "{22222222-2222-2222-2222-222222222222}"


class _Client:
    def __init__(self, responses: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
        self.responses = {uri: deque(rows) for uri, rows in responses.items()}
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append((uri, dict(args or {}), dict(options or {})))
        if uri not in self.responses or not self.responses[uri]:
            raise AssertionError(f"Unexpected or exhausted WAAPI call: {uri}")
        return self.responses[uri].popleft()

    def disconnect(self) -> None:
        pass


def _env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"wwise_version": "2025.1", "project_modification_policy": "ask_before_changes"}),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_WAAPI_PORT": "8080",
    }


def _live_rows(tmp_path: Path, operation: str) -> dict[str, Sequence[Mapping[str, Any]]]:
    project_path = tmp_path / "project" / "SampleProject.wproj"
    project_path.parent.mkdir(exist_ok=True)
    project_path.write_text("<Project/>", encoding="utf-8")
    target = {
        "id": TARGET_ID,
        "name": "Parent",
        "type": "Sound" if operation == "object.createPlugin" else "ActorMixer",
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Parent",
        "parent": {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"},
        "notes": "",
    }
    responses: dict[str, Sequence[Mapping[str, Any]]] = {
        "ak.wwise.core.getInfo": [
            {
                "displayName": "Wwise",
                "isCommandLine": True,
                "sessionId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "processId": 42,
                "processPath": "/Applications/Wwise.app/Contents/MacOS/Wwise",
                "apiVersion": 1,
                "platform": "macosx",
                "configuration": "release",
                "version": {"year": 2025, "major": 1, "minor": 0, "build": 1},
            }
        ],
        "ak.wwise.core.getProjectInfo": [
            {"id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}", "name": "SampleProject", "path": str(project_path)}
        ],
    }
    if operation == "object.createPlugin":
        responses["ak.wwise.core.object.get"] = [
            {"return": [target]},
            {"return": []},
        ]
    else:
        control = {
            **target,
            "id": CONTROL_ID,
            "name": "Distance",
            "type": "GameParameter",
            "path": r"\Game Parameters\Default Work Unit\Distance",
        }
        responses["ak.wwise.core.object.get"] = [
            {"return": [target]},
            {"return": [control]},
            {"return": [{"id": TARGET_ID, "@RTPC": []}]},
        ]
        responses["ak.wwise.core.object.getPropertyInfo"] = [
            {
                "name": "Volume",
                "type": "Real32",
                "supports": {"randomizer": True, "rtpc": "Additive", "unlink": True},
            }
        ]
    return responses


def _apply_facts(
    tmp_path: Path,
    *,
    state_dir: Path,
    started: Mapping[str, Any],
    facts: Sequence[TypedRequestFact],
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
        if fact.action in {"choose", "choose-dynamic"}:
            argv += ["--fact-value", fact.value]
        elif fact.action != "present":
            argv += ["--value-type", fact.value_type, "--fact-value", fact.value]
        if fact.key is not None:
            argv += ["--key", fact.key]
        code, payload = gateway.execute_gateway(
            argv,
            env=_env(tmp_path),
            client_factory=lambda url: pytest.fail(f"draft-apply connected to {url}"),
        )
        assert code == 0, payload
        revision = payload["draft"]["revision"]
    return revision


def _identity_facts(contract, path: tuple[str, ...], value: str) -> list[TypedRequestFact]:
    branch = next(
        field
        for field in contract.fields
        if field.path == path and field.shape == "branch" and field.parent_handle is None
    )
    object_branch = next(
        field
        for field in contract.fields
        if field.parent_handle == branch.handle and field.name == "object:0"
    )
    kind = next(
        field
        for field in contract.fields
        if field.parent_handle == object_branch.handle and field.name == "kind"
    )
    selector_value = next(
        field
        for field in contract.fields
        if field.parent_handle == object_branch.handle and field.name == "value"
    )
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


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.createPlugin", "object.setRTPC"))
def test_plugin_and_rtpc_compile_as_exact_named_typed_drafts(
    version: str, operation: str
) -> None:
    contract = draft_operation_request_contract(operation, version)
    assert contract.uri == operation
    assert contract.as_gateway_payload()["input_shape"] == "draft"


def test_plugin_property_and_topology_materialize_without_json() -> None:
    contract = draft_operation_request_contract("object.createPlugin", "2025.1")
    facts = _identity_facts(contract, ("target",), TARGET_ID)
    for name, value_type, value in (
        ("kind", "string", "source"),
        ("name", "string", "Synth"),
        ("class_id", "integer", "1234"),
    ):
        field = next(field for field in contract.fields if field.path == ("plugin", name))
        facts.append(TypedRequestFact("set", field.handle, value_type, value))
    properties = next(field for field in contract.fields if field.path == ("plugin", "properties"))
    row = dynamic_array_item_handle(
        contract, array_handle=properties.handle, index=0, shape="object"
    )
    disclosure = dynamic_container_disclosure(
        contract,
        parent_handle=properties.handle,
        key="0",
        shape="object",
        child_handle=row,
        member_key="value",
    )
    number_choice = next(
        choice["handle"]
        for member in disclosure["branch_choices"]
        if member["key"] == "value"
        for choice in member["choices"]
        if choice["accepted_types"] == ["number"]
    )
    facts.extend(
        [
            TypedRequestFact("append", properties.handle, "object", row),
            TypedRequestFact("map-put", row, "string", "Gain", key="name"),
            TypedRequestFact("choose-dynamic", row, "choice", number_choice, key="value"),
            TypedRequestFact("map-put", row, "number", "-3.0", key="value"),
        ]
    )

    request = materialize_operation_request(
        "object.createPlugin", "2025.1", _composition(contract, facts)
    )
    assert request["arguments"]["plugin"] == {
        "kind": "source",
        "name": "Synth",
        "class_id": 1234,
        "properties": [{"name": "Gain", "value": -3.0}],
    }
    parse_operation_request(request, expected_version="2025.1")


def test_rtpc_ordered_points_materialize_and_reparse() -> None:
    contract = draft_operation_request_contract("object.setRTPC", "2025.1")
    facts = [
        *_identity_facts(contract, ("object",), TARGET_ID),
        *_identity_facts(contract, ("control_input",), CONTROL_ID),
    ]
    property_field = next(field for field in contract.fields if field.path == ("property",))
    facts.append(TypedRequestFact("set", property_field.handle, "string", "Volume"))
    points = next(field for field in contract.fields if field.path == ("points",))
    for index, (x, y, shape) in enumerate((("0", "-12", "Linear"), ("100", "0", "SCurve"))):
        row = dynamic_array_item_handle(
            contract, array_handle=points.handle, index=index, shape="object"
        )
        facts.extend(
            [
                TypedRequestFact("append", points.handle, "object", row),
                TypedRequestFact("map-put", row, "number", x, key="x"),
                TypedRequestFact("map-put", row, "number", y, key="y"),
                TypedRequestFact("map-put", row, "string", shape, key="shape"),
            ]
        )

    request = materialize_operation_request(
        "object.setRTPC", "2025.1", _composition(contract, facts)
    )
    assert request["arguments"]["points"] == [
        {"x": 0.0, "y": -12.0, "shape": "Linear"},
        {"x": 100.0, "y": 0.0, "shape": "SCurve"},
    ]
    parse_operation_request(request, expected_version="2025.1")


def test_rtpc_complete_256_point_contract_materializes_within_disclosed_limits() -> None:
    contract = draft_operation_request_contract("object.setRTPC", "2025.1")
    facts = [
        *_identity_facts(contract, ("object",), TARGET_ID),
        *_identity_facts(contract, ("control_input",), CONTROL_ID),
    ]
    property_field = next(field for field in contract.fields if field.path == ("property",))
    facts.append(TypedRequestFact("set", property_field.handle, "string", "Volume"))
    points = next(field for field in contract.fields if field.path == ("points",))
    for index in range(256):
        row = dynamic_array_item_handle(
            contract, array_handle=points.handle, index=index, shape="object"
        )
        facts.extend(
            (
                TypedRequestFact("append", points.handle, "object", row),
                TypedRequestFact("map-put", row, "number", str(index), key="x"),
                TypedRequestFact("map-put", row, "number", "0", key="y"),
                TypedRequestFact("map-put", row, "string", "Linear", key="shape"),
            )
        )

    assert len(facts) <= MAX_TYPED_REQUEST_FACTS
    request = materialize_operation_request(
        "object.setRTPC", "2025.1", _composition(contract, facts)
    )
    assert len(request["arguments"]["points"]) == MAX_TYPED_ARRAY_ITEMS == 256
    assert request["arguments"]["points"][-1]["x"] == 255.0


def test_plugin_notes_use_the_registry_owned_utf8_limit() -> None:
    contract = draft_operation_request_contract("object.createPlugin", "2025.1")
    facts = _identity_facts(contract, ("target",), TARGET_ID)
    for name, value_type, value in (
        ("kind", "string", "source"),
        ("name", "string", "Synth"),
        ("class_id", "integer", "1234"),
        ("notes", "string", "x" * MAX_TYPED_STRING_BYTES),
    ):
        field = next(field for field in contract.fields if field.path == ("plugin", name))
        facts.append(TypedRequestFact("set", field.handle, value_type, value))
    request = materialize_operation_request(
        "object.createPlugin", "2025.1", _composition(contract, facts)
    )
    assert len(request["arguments"]["plugin"]["notes"].encode("utf-8")) == 64 * 1024
    assert len(json.dumps(request).encode("utf-8")) < MAX_TYPED_REQUEST_BYTES

    facts[-1] = TypedRequestFact(
        "set", facts[-1].handle, "string", "x" * (MAX_TYPED_STRING_BYTES + 1)
    )
    with pytest.raises(Exception, match="schema"):
        materialize_operation_request(
            "object.createPlugin", "2025.1", _composition(contract, facts)
        )


def test_public_plugin_notes_accept_exact_registry_limit_and_reject_next_byte(
    tmp_path: Path,
) -> None:
    operation = "object.createPlugin"
    state_dir = tmp_path / "plugin-notes-boundary"
    contract = draft_operation_request_contract(operation, "2025.1")
    notes = next(field for field in contract.fields if field.path == ("plugin", "notes"))
    start_code, started = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-start", operation,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    assert start_code == 0, started

    code, applied = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-apply", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", "1", "--facts",
            "--action", "add_typed_fact", "--fact-action", "set",
            "--field-handle", notes.handle, "--value-type", "string",
            "--fact-value", "x" * MAX_TYPED_STRING_BYTES,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"draft-apply connected to {url}"),
    )
    assert code == 0, applied
    assert applied["draft"]["revision"] == 2

    second_dir = tmp_path / "plugin-notes-overflow"
    _, second = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(second_dir),
            "draft-start", operation,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    rejected_code, rejected = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(second_dir),
            "draft-apply", second["draft"]["draft_id"],
            "--task-authority", second["task_authority"],
            "--expected-revision", "1", "--facts",
            "--action", "add_typed_fact", "--fact-action", "set",
            "--field-handle", notes.handle, "--value-type", "string",
            "--fact-value", "x" * (MAX_TYPED_STRING_BYTES + 1),
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"draft-apply connected to {url}"),
    )
    assert rejected_code == 2, rejected
    assert rejected["error_code"] == "OPERATION_DRAFT_ACTION_INVALID"
    inspected = gateway.OperationDraftStore(second_dir).inspect(
        second["draft"]["draft_id"], task_authority=second["task_authority"]
    )
    assert inspected.revision == 1
    assert inspected.composition["facts"] == []


@pytest.mark.parametrize("operation", ("object.createPlugin", "object.setRTPC"))
def test_typed_plugin_and_rtpc_drafts_check_and_seal_one_immutable_preview(
    tmp_path: Path, operation: str
) -> None:
    state_dir = tmp_path / f"state-{operation}"
    contract = draft_operation_request_contract(operation, "2025.1")
    start_code, started = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-start", operation,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    assert start_code == 0, started

    if operation == "object.createPlugin":
        facts = _identity_facts(contract, ("target",), TARGET_ID)
        for name, value_type, value in (
            ("kind", "string", "source"),
            ("name", "string", "Synth"),
            ("class_id", "integer", "1234"),
        ):
            field = next(field for field in contract.fields if field.path == ("plugin", name))
            facts.append(TypedRequestFact("set", field.handle, value_type, value))
    else:
        facts = [
            *_identity_facts(contract, ("object",), TARGET_ID),
            *_identity_facts(contract, ("control_input",), CONTROL_ID),
        ]
        property_field = next(field for field in contract.fields if field.path == ("property",))
        facts.append(TypedRequestFact("set", property_field.handle, "string", "Volume"))
        points = next(field for field in contract.fields if field.path == ("points",))
        row = dynamic_array_item_handle(
            contract, array_handle=points.handle, index=0, shape="object"
        )
        facts.extend(
            (
                TypedRequestFact("append", points.handle, "object", row),
                TypedRequestFact("map-put", row, "number", "0", key="x"),
                TypedRequestFact("map-put", row, "number", "-6", key="y"),
                TypedRequestFact("map-put", row, "string", "Linear", key="shape"),
            )
        )
    revision = _apply_facts(
        tmp_path, state_dir=state_dir, started=started, facts=facts
    )
    expected_request = materialize_operation_request(
        operation,
        "2025.1",
        gateway.OperationDraftStore(state_dir).inspect(
            started["draft"]["draft_id"],
            task_authority=started["task_authority"],
        ).composition,
    )

    check_client = _Client(_live_rows(tmp_path, operation))
    check_code, checked = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-check", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(revision),
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: check_client,
    )
    assert check_code == 0, json.dumps(checked, indent=2)
    checked_revision = checked["draft"]["revision"]
    assert checked["draft"]["check"]["status"] == "passed"

    preview_client = _Client(_live_rows(tmp_path, operation))
    preview_code, previewed = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "preview-from-draft", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(checked_revision), "--apply", "--ttl", "300",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: preview_client,
    )
    assert preview_code == 0, previewed
    assert previewed["state"] == "awaiting_confirmation"
    assert previewed["agent_result"]["request"] == expected_request
    stored = TransactionStore(state_dir).load_preview(previewed["transaction_id"])
    assert stored.artifact["request"] == expected_request
    events = TransactionStore(state_dir).read_events(previewed["transaction_id"])

    replay_code, replayed = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "preview-from-draft", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(checked_revision), "--apply", "--ttl", "300",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: _Client(_live_rows(tmp_path, operation)),
    )
    assert replay_code == 0, replayed
    assert replayed["transaction_id"] == previewed["transaction_id"]
    assert TransactionStore(state_dir).read_events(previewed["transaction_id"]) == events


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.createPlugin", "object.setRTPC"))
def test_public_schema_and_draft_start_share_one_exact_operation(
    tmp_path: Path, operation: str, version: str
) -> None:
    code, schema = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline command connected to {url}"),
    )
    assert code == 0, schema
    assert schema["operation"]["input_mode"] == "composer"
    start = schema["composer"]["start"]
    assert start["gateway_argv"] == ["draft-start", operation]
    assert start["copy_instruction"]["source_field"] == "gateway_argv"
    assert start["copy_instruction"]["action"] == (
        "append_to_packaged_gateway_prefix_and_execute_verbatim"
    )
    assert start["precondition_discipline"] == {
        "metadata_discover_allowed_only_when": (
            "preconditions is present and selects metadata"
        ),
        "when_preconditions_absent": "execute_gateway_argv_now",
        "infer_metadata_from_operation_constraints": False,
    }
    if operation == "object.setRTPC":
        assert "preconditions" not in start
    start_code, started = gateway.execute_gateway(
        [
            "--version", version, "--state-dir",
            str(tmp_path / f"{operation}-{version}"), "draft-start", operation,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline command connected to {url}"),
    )
    assert start_code == 0, started
    assert started["draft"]["binding"]["operation"] == operation
    draft_keys = list(started["draft"])
    assert draft_keys.index("agent_control") < draft_keys.index("current_facts")
    assert draft_keys.index("next_action_binding") < draft_keys.index(
        "current_facts"
    )
    binding_keys = list(started["draft"]["next_action_binding"])
    for later_key in (
        "typed_fact_batch_discipline",
        "root_dynamic_disclosure_commands",
    ):
        if later_key not in binding_keys:
            continue
        assert binding_keys.index("required_next_phase") < binding_keys.index(
            later_key
        )
        assert binding_keys.index("fixed_argv_prefix_copy") < binding_keys.index(
            later_key
        )
        assert binding_keys.index(
            "fixed_argv_prefix_copy_instruction"
        ) < binding_keys.index(later_key)


def test_rtpc_point_shape_fails_before_any_preview() -> None:
    contract = draft_operation_request_contract("object.setRTPC", "2025.1")
    points = next(field for field in contract.fields if field.path == ("points",))
    row = dynamic_array_item_handle(
        contract, array_handle=points.handle, index=0, shape="object"
    )
    with pytest.raises(Exception, match="shape"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(
                TypedRequestFact("append", points.handle, "object", row),
                TypedRequestFact("map-put", row, "number", "0", key="x"),
                TypedRequestFact("map-put", row, "number", "0", key="y"),
                TypedRequestFact("map-put", row, "string", "Invented", key="shape"),
            ),
        )
