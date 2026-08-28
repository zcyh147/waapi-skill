import importlib.util
import json
import sys
from pathlib import Path

import pytest

import wwise_waapi.dispatcher as dispatcher_module
from wwise_waapi.builders.query import ADVANCED_QUERY_CONTRACT, MAX_ADVANCED_WAQL_BYTES
from wwise_waapi.builders.query import STRUCTURED_QUERY_CONTRACT
from wwise_waapi.typed_queries import (
    ADVANCED_TYPED_QUERY_OPERATION,
    STRUCTURED_TYPED_QUERY_OPERATION,
    materialize_typed_query,
    typed_query_contract,
)
from wwise_waapi.typed_requests import (
    TypedRequestError,
    TypedRequestFact,
    dynamic_array_item_choices,
    dynamic_array_item_handle,
    dynamic_map_container_choices,
    dynamic_map_entry_handle,
    parse_typed_schema_lineage_token,
    typed_schema_lineage_token,
)
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location("waapi_typed_query_gateway_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


def _env(tmp_path: Path, version: str) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": version,
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WAAPI_SKILL_STATE_DIR": str(tmp_path / "state"),
        "WWISE_VERSION": version,
    }


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_advanced_query_typed_facts_materialize_the_existing_builder_document(
    version: str,
) -> None:
    contract = typed_query_contract(version, advanced=True)
    fields = {field.name: field for field in contract.fields}

    materialized = materialize_typed_query(
        ADVANCED_TYPED_QUERY_OPERATION,
        version,
        contract.schema_digest,
        (
            TypedRequestFact("set", fields["waql"].handle, "string", "from project"),
            TypedRequestFact("append", fields["return"].handle, "string", "id"),
            TypedRequestFact("append", fields["return"].handle, "string", "name"),
            TypedRequestFact("set", fields["max_results"].handle, "integer", "7"),
        ),
    )

    assert materialized.document == {
        "contract": ADVANCED_QUERY_CONTRACT,
        "waql": "from project",
        "return": ["id", "name"],
        "max_results": 7,
    }
    assert materialized.preview.envelope.uri == "ak.wwise.core.object.get"
    assert materialized.preview.envelope.args == {"waql": "from project take 7"}
    assert materialized.preview.envelope.options == {"return": ["id", "name"]}


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_structured_query_typed_facts_materialize_the_existing_builder_document(
    version: str,
) -> None:
    contract = typed_query_contract(version)
    source = next(field for field in contract.fields if field.name == "source")
    source_type = next(
        field
        for field in contract.fields
        if field.parent_handle == source.handle
        and field.shape == "object"
        and any(
            child.parent_handle == field.handle
            and child.name == "kind"
            and any(variant.get("const") == "type" for variant in child.variants)
            for child in contract.fields
        )
    )
    kind = next(
        field for field in contract.fields
        if field.parent_handle == source_type.handle and field.name == "kind"
    )
    types = next(
        field for field in contract.fields
        if field.parent_handle == source_type.handle and field.name == "types"
    )
    transforms = next(field for field in contract.fields if field.name == "transforms")
    returns = next(field for field in contract.fields if field.name == "return")
    take_choice = next(
        handle
        for handle, _index, variant in dynamic_array_item_choices(
            contract,
            array_handle=transforms.handle,
            index=0,
            shape="object",
        )
        if variant.get("required") == ["kind", "value"]
    )
    take_handle = dynamic_array_item_handle(
        contract,
        array_handle=transforms.handle,
        index=0,
        shape="object",
        choice_handle=take_choice,
    )

    materialized = materialize_typed_query(
        STRUCTURED_TYPED_QUERY_OPERATION,
        version,
        contract.schema_digest,
        (
            TypedRequestFact("choose", source.handle, "branch", source_type.handle),
            TypedRequestFact("set", kind.handle, "string", "type"),
            TypedRequestFact("append", types.handle, "string", "Sound"),
            TypedRequestFact("append", transforms.handle, "object", take_handle),
            TypedRequestFact("map-put", take_handle, "string", "take", key="kind"),
            TypedRequestFact("map-put", take_handle, "integer", "12", key="value"),
            TypedRequestFact("append", returns.handle, "string", "id"),
            TypedRequestFact("append", returns.handle, "string", "name"),
        ),
    )

    assert materialized.document == {
        "contract": STRUCTURED_QUERY_CONTRACT,
        "source": {"kind": "type", "types": ["Sound"]},
        "transforms": [{"kind": "take", "value": 12}],
        "return": ["id", "name"],
    }
    assert materialized.preview.envelope.args == {"waql": "from type Sound take 12"}


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_structured_query_predicate_accessor_operator_and_literal_are_typed(
    version: str,
) -> None:
    contract = typed_query_contract(version)
    fields = {field.name: field for field in contract.fields if field.parent_handle is None}
    source = fields["source"]
    project = next(
        field
        for field in contract.fields
        if field.parent_handle == source.handle
        and any(
            child.parent_handle == field.handle
            and any(variant.get("const") == "project" for variant in child.variants)
            for child in contract.fields
        )
    )
    project_kind = next(
        field for field in contract.fields
        if field.parent_handle == project.handle and field.name == "kind"
    )
    transforms = fields["transforms"]
    where_choice = next(
        handle
        for handle, _index, variant in dynamic_array_item_choices(
            contract, array_handle=transforms.handle, index=0, shape="object"
        )
        if variant.get("required") == ["kind", "predicate"]
    )
    where_handle = dynamic_array_item_handle(
        contract,
        array_handle=transforms.handle,
        index=0,
        shape="object",
        choice_handle=where_choice,
    )
    where_schema = next(
        variant
        for _handle, _index, variant in dynamic_array_item_choices(
            contract, array_handle=transforms.handle, index=0, shape="object"
        )
        if variant.get("required") == ["kind", "predicate"]
    )
    compare_choice, _compare_index, predicate_schema = next(
        item
        for item in dynamic_map_container_choices(
            contract,
            map_handle=where_handle,
            key="predicate",
            shape="object",
            parent_schema=where_schema,
            parent_section="args",
        )
        if item[2].get("properties", {}).get("operator", {}).get("const") == ":"
    )
    predicate_handle = dynamic_map_entry_handle(
        contract,
        map_handle=where_handle,
        key="predicate",
        shape="object",
        choice_handle=compare_choice,
        parent_schema=where_schema,
        parent_section="args",
    )
    predicate_choice = compare_choice
    path_handle = dynamic_map_entry_handle(
        contract,
        map_handle=predicate_handle,
        key="path",
        shape="array",
        parent_schema=predicate_schema,
        parent_section="args",
    )
    take_choice = next(
        handle
        for handle, _index, variant in dynamic_array_item_choices(
            contract, array_handle=transforms.handle, index=1, shape="object"
        )
        if variant.get("required") == ["kind", "value"]
    )
    take_handle = dynamic_array_item_handle(
        contract,
        array_handle=transforms.handle,
        index=1,
        shape="object",
        choice_handle=take_choice,
    )

    materialized = materialize_typed_query(
        STRUCTURED_TYPED_QUERY_OPERATION,
        version,
        contract.schema_digest,
        (
            TypedRequestFact("choose", source.handle, "branch", project.handle),
            TypedRequestFact("set", project_kind.handle, "string", "project"),
            TypedRequestFact("append", transforms.handle, "object", where_handle),
            TypedRequestFact("map-put", where_handle, "string", "where", key="kind"),
            TypedRequestFact(
                "choose-dynamic", where_handle, "choice", predicate_choice,
                key="predicate",
            ),
            TypedRequestFact(
                "map-put", where_handle, "object", predicate_handle, key="predicate"
            ),
            TypedRequestFact("map-put", predicate_handle, "string", "compare", key="kind"),
            TypedRequestFact("map-put", predicate_handle, "array", path_handle, key="path"),
            TypedRequestFact("append", path_handle, "string", "name"),
            TypedRequestFact("map-put", predicate_handle, "string", ":", key="operator"),
            TypedRequestFact("map-put", predicate_handle, "string", "UI", key="value"),
            TypedRequestFact("append", transforms.handle, "object", take_handle),
            TypedRequestFact("map-put", take_handle, "string", "take", key="kind"),
            TypedRequestFact("map-put", take_handle, "integer", "10", key="value"),
            TypedRequestFact("append", fields["return"].handle, "string", "id"),
        ),
    )

    assert materialized.preview.envelope.args == {
        "waql": 'from project where name : "UI" take 10'
    }


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_recursive_all_not_predicate_uses_only_gateway_disclosed_lineage(
    version: str,
) -> None:
    contract = typed_query_contract(version)
    transforms = next(field for field in contract.fields if field.name == "transforms")
    where_choice, _index, where_schema = next(
        item for item in dynamic_array_item_choices(
            contract, array_handle=transforms.handle, index=0, shape="object"
        ) if item[2].get("required") == ["kind", "predicate"]
    )
    where_handle = dynamic_array_item_handle(
        contract, array_handle=transforms.handle, index=0, shape="object",
        choice_handle=where_choice,
    )
    where_token = typed_schema_lineage_token(
        contract, child_handle=where_handle, parent_handle=transforms.handle,
        key="0", shape="object", choice_handle=where_choice,
    )
    parent_schema, parent_section = parse_typed_schema_lineage_token(
        contract, parent_handle=where_handle, token=where_token,
    ) or ({}, "")
    all_choice, _all_index, all_schema = next(
        item for item in dynamic_map_container_choices(
            contract, map_handle=where_handle, key="predicate", shape="object",
            parent_schema=parent_schema, parent_section=parent_section,
        ) if item[2].get("properties", {}).get("kind", {}).get("enum") == ["all", "any"]
    )
    all_handle = dynamic_map_entry_handle(
        contract, map_handle=where_handle, key="predicate", shape="object",
        choice_handle=all_choice, parent_schema=parent_schema,
        parent_section=parent_section,
    )
    all_token = typed_schema_lineage_token(
        contract, child_handle=all_handle, parent_token=where_token,
        parent_handle=where_handle, key="predicate", shape="object",
        choice_handle=all_choice,
    )
    all_parent, all_section = parse_typed_schema_lineage_token(
        contract, parent_handle=all_handle, token=all_token,
    ) or ({}, "")
    operands_handle = dynamic_map_entry_handle(
        contract, map_handle=all_handle, key="operands", shape="array",
        parent_schema=all_parent, parent_section=all_section,
    )
    operands_token = typed_schema_lineage_token(
        contract, child_handle=operands_handle, parent_token=all_token,
        parent_handle=all_handle, key="operands", shape="array",
    )
    operands_schema, operands_section = parse_typed_schema_lineage_token(
        contract, parent_handle=operands_handle, token=operands_token,
    ) or ({}, "")
    operand_choices = dynamic_array_item_choices(
        contract, array_handle=operands_handle, index=0, shape="object",
        parent_schema=operands_schema, parent_section=operands_section,
    )
    truthy_choice, _truthy_index, truthy_schema = next(
        item for item in operand_choices
        if item[2].get("properties", {}).get("kind", {}).get("const") == "truthy"
    )
    truthy_handle = dynamic_array_item_handle(
        contract, array_handle=operands_handle, index=0, shape="object",
        choice_handle=truthy_choice, parent_schema=operands_schema,
        parent_section=operands_section,
    )
    truthy_path = dynamic_map_entry_handle(
        contract, map_handle=truthy_handle, key="path", shape="array",
        parent_schema=truthy_schema, parent_section=operands_section,
    )
    not_choice, _not_index, _not_schema = next(
        item for item in operand_choices
        if item[2].get("properties", {}).get("kind", {}).get("const") == "not"
    )
    not_handle = dynamic_array_item_handle(
        contract, array_handle=operands_handle, index=0, shape="object",
        choice_handle=not_choice, parent_schema=operands_schema,
        parent_section=operands_section,
    )
    not_contract = gateway.dynamic_container_disclosure(
        contract,
        parent_handle=operands_handle,
        key="0",
        shape="object",
        child_handle=not_handle,
        parent_schema=operands_schema,
        parent_section=operands_section,
        choice_handle=not_choice,
    )
    source = next(field for field in contract.fields if field.name == "source")
    project = next(
        field for field in contract.fields
        if field.parent_handle == source.handle
        and any(
            child.parent_handle == field.handle
            and any(variant.get("const") == "project" for variant in child.variants)
            for child in contract.fields
        )
    )
    project_kind = next(
        field for field in contract.fields
        if field.parent_handle == project.handle and field.name == "kind"
    )
    returns = next(field for field in contract.fields if field.name == "return")
    take_choice = next(
        handle for handle, _variant_index, variant in dynamic_array_item_choices(
            contract, array_handle=transforms.handle, index=1, shape="object"
        ) if variant.get("required") == ["kind", "value"]
    )
    take_handle = dynamic_array_item_handle(
        contract, array_handle=transforms.handle, index=1, shape="object",
        choice_handle=take_choice,
    )
    materialized = materialize_typed_query(
        STRUCTURED_TYPED_QUERY_OPERATION,
        version,
        contract.schema_digest,
        (
            TypedRequestFact("choose", source.handle, "branch", project.handle),
            TypedRequestFact("set", project_kind.handle, "string", "project"),
            TypedRequestFact("append", transforms.handle, "object", where_handle),
            TypedRequestFact("map-put", where_handle, "string", "where", key="kind"),
            TypedRequestFact(
                "choose-dynamic", where_handle, "choice", all_choice, key="predicate"
            ),
            TypedRequestFact(
                "map-put", where_handle, "object", all_handle, key="predicate"
            ),
            TypedRequestFact("map-put", all_handle, "string", "all", key="kind"),
            TypedRequestFact(
                "map-put", all_handle, "array", operands_handle, key="operands"
            ),
            TypedRequestFact(
                "append", operands_handle, "object", truthy_handle
            ),
            TypedRequestFact(
                "map-put", truthy_handle, "string", "truthy", key="kind"
            ),
            TypedRequestFact(
                "map-put", truthy_handle, "array", truthy_path, key="path"
            ),
            TypedRequestFact("append", truthy_path, "string", "name"),
            TypedRequestFact("append", transforms.handle, "object", take_handle),
            TypedRequestFact("map-put", take_handle, "string", "take", key="kind"),
            TypedRequestFact("map-put", take_handle, "integer", "10", key="value"),
            TypedRequestFact("append", returns.handle, "string", "id"),
        ),
    )

    assert all_schema["required"] == ["kind", "operands"]
    assert not_handle.startswith("trm1-")
    assert not_contract["required_keys"] == ["kind", "operand"]
    assert materialized.preview.envelope.args == {
        "waql": "from project where name take 10"
    }


@pytest.mark.parametrize("advanced", (False, True))
def test_query_schema_discloses_one_business_continuation_without_typed_facts(
    tmp_path: Path,
    advanced: bool,
) -> None:
    argv = ["query-schema", *(["--advanced"] if advanced else [])]
    code, payload = gateway.execute_gateway(
        argv,
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("query-schema must remain offline"),
    )

    assert code == 0, json.dumps(take, sort_keys=True)
    assert payload["input_shape"] == "business_declaration"
    assert payload["continuation"]["subcommand"] == "query-object"
    assert "json" not in json.dumps(payload).casefold()
    if advanced:
        assert {
            key: value
            for key, value in payload["continuation"].items()
            if key != "exact_expression_limits"
        } == {
            "subcommand": "query-object",
            "query_layer": "advanced-native-waql",
            "exact_expression": "--advanced-waql <one bounded exact WAQL expression>",
            "result_bound": "--max-results <1..1000>",
            "business_output": "--include <business-field> (repeat)",
        }
        assert payload["continuation"]["exact_expression_limits"][
            "max_utf8_bytes"
        ] == MAX_ADVANCED_WAQL_BYTES
    else:
        assert payload["query_contract"] == "waapi-skill.object-query-business/v1"
        assert payload["identity_projection"] == ["id", "name", "type", "path"]
        assert "volume-db" in payload["business_outputs"]
        assert payload["kind_semantics"] == {
            "all-sounds": "every Wwise Sound, including SFX and Voice",
            "sound-sfx": "only Sound objects whose source language is SFX",
            "sound-voice": "only Sound objects whose source language is not SFX",
        }
        assert payload["presentation_boundary"] == {
            "sort_or_group_complete_result": "agent-owned presentation",
            "advanced_required_only_when": (
                "server-side ordering, skip, distinct, regex, or another native "
                "construct changes which rows enter the bounded result"
            ),
        }
        assert payload["advanced_fallback"]["use_only_when"].startswith(
            "server-side query semantics"
        )
        assert payload["continuation"]["predicate"] == (
            "--predicate <business-condition> <value>"
        )
        assert "schema_digest" not in payload


def test_query_object_parser_has_no_typed_fact_or_projection_escape() -> None:
    parser = gateway.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if "query-object" in (getattr(action, "choices", None) or {})
    )
    query_parser = subparsers.choices["query-object"]
    options = {
        option
        for action in query_parser._actions
        for option in action.option_strings
    }

    assert "--advanced-waql" in options
    assert not {
        "--typed-structured",
        "--typed-advanced",
        "--typed-schema-digest",
        "--typed-set",
        "--typed-append",
        "--typed-present",
        "--typed-choose",
        "--typed-choose-dynamic",
        "--typed-map-put",
        "--typed-map-correct",
        "--typed-map-remove",
        "--schema-digest",
        "--waql",
        "--advanced-return",
        "--return-field",
    } & options


def test_request_schema_rejects_query_pseudo_operations_in_favor_of_query_schema(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        ["request-schema", STRUCTURED_TYPED_QUERY_OPERATION],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("rejection must be offline"),
    )

    assert code == 2
    assert "query-schema" in payload["message"]


def test_generic_typed_container_routes_reject_archived_query_pseudo_operations(
    tmp_path: Path,
) -> None:
    contract = typed_query_contract("2025.1")
    transforms = next(field for field in contract.fields if field.name == "transforms")

    code, payload = gateway.execute_gateway(
        [
            "request-array-item",
            STRUCTURED_TYPED_QUERY_OPERATION,
            "--schema-digest",
            contract.schema_digest,
            "--array-handle",
            transforms.handle,
            "--index",
            "0",
            "--shape",
            "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("rejection must remain offline"),
    )

    assert code == 2
    assert "query-schema" in payload["message"]


def test_typed_query_arrays_reject_duplicate_schema_unique_items() -> None:
    contract = typed_query_contract("2025.1", advanced=True)
    returns = next(field for field in contract.fields if field.name == "return")
    with pytest.raises(TypedRequestError, match="unique"):
        materialize_typed_query(
            ADVANCED_TYPED_QUERY_OPERATION,
            "2025.1",
            contract.schema_digest,
            (
                TypedRequestFact("set", next(
                    field.handle for field in contract.fields if field.name == "waql"
                ), "string", "from project"),
                TypedRequestFact("append", returns.handle, "string", "id"),
                TypedRequestFact("append", returns.handle, "string", "id"),
                TypedRequestFact("set", next(
                    field.handle for field in contract.fields if field.name == "max_results"
                ), "integer", "2"),
            ),
        )


class _AdvancedQueryClient:
    def __init__(self, version: str) -> None:
        self.version = version
        self.calls: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def call(self, uri: str, args=None, options=None):  # type: ignore[no-untyped-def]
        if uri == "ak.wwise.core.getInfo":
            year, major = self.version.split(".")
            return {
                "displayName": "Wwise",
                "platform": "macOS",
                "version": {
                    "year": int(year),
                    "major": int(major),
                    "minor": 0,
                    "build": 1,
                    "displayName": f"v{self.version}",
                },
                "isCommandLine": True,
            }
        self.calls.append((uri, dict(args or {}), dict(options or {})))
        return {
            "return": [
                {
                    "id": "{11111111-1111-1111-1111-111111111111}",
                    "name": "Project",
                    "type": "Project",
                    "path": r"\Project",
                }
            ]
        }

    def disconnect(self) -> None:
        return None


def test_public_advanced_query_exact_expression_dispatches_gateway_owned_request(
    tmp_path: Path,
) -> None:
    code, _schema = gateway.execute_gateway(
        ["query-schema", "--advanced"],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("query-schema must be offline"),
    )
    assert code == 0
    client = _AdvancedQueryClient("2025.1")

    code, payload = gateway.execute_gateway(
        [
            "query-object",
            "--advanced-waql",
            "from project",
            "--max-results",
            "3",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert client.calls == [
        (
            "ak.wwise.core.object.get",
            {"waql": "from project take 3"},
            {"return": ["id", "name", "type", "path"]},
        )
    ]
    assert payload["agent_result"] == [
        {
            "id": "{11111111-1111-1111-1111-111111111111}",
            "name": "Project",
            "type": "Project",
            "path": r"\Project",
        }
    ]
    assert list(payload)[-1] == "agent_result"


def test_public_typed_advanced_query_dispatches_invalid_waql_once(
    tmp_path: Path,
) -> None:
    class InvalidQueryClient(_AdvancedQueryClient):
        def call(self, uri: str, args=None, options=None):  # type: ignore[no-untyped-def]
            if uri == "ak.wwise.core.getInfo":
                return super().call(uri, args, options)
            self.calls.append((uri, dict(args or {}), dict(options or {})))
            raise RuntimeError("invalid WAQL")

    env = _env(tmp_path, "2025.1")
    code, _schema = gateway.execute_gateway(["query-schema", "--advanced"], env=env)
    assert code == 0
    client = InvalidQueryClient("2025.1")

    code, payload = gateway.execute_gateway(
        [
            "query-object",
            "--advanced-waql",
            "from project",
            "--max-results",
            "3",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert payload["call"]["error_code"] == "RuntimeError"
    assert [call[0] for call in client.calls] == ["ak.wwise.core.object.get"]


def test_public_typed_advanced_query_keeps_result_byte_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OversizedQueryClient(_AdvancedQueryClient):
        def call(self, uri: str, args=None, options=None):  # type: ignore[no-untyped-def]
            if uri == "ak.wwise.core.getInfo":
                return super().call(uri, args, options)
            self.calls.append((uri, dict(args or {}), dict(options or {})))
            return {"return": [{"id": "x", "name": "X" * 4096}]}

    env = _env(tmp_path, "2025.1")
    code, _schema = gateway.execute_gateway(["query-schema", "--advanced"], env=env)
    assert code == 0
    client = OversizedQueryClient("2025.1")
    monkeypatch.setattr(dispatcher_module, "MAX_LIVE_RESULT_JSON_BYTES", 2048)

    code, payload = gateway.execute_gateway(
        [
            "query-object",
            "--advanced-waql",
            "from project",
            "--max-results",
            "3",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert payload["call"]["error_code"] == "RESULT_TOO_LARGE"
    assert "X" * 512 not in json.dumps(payload)



def test_simple_query_business_predicate_preserves_short_gateway_route(
    tmp_path: Path,
) -> None:
    client = _AdvancedQueryClient("2025.1")
    code, payload = gateway.execute_gateway(
        [
            "query-object", "--kind", "all-sounds",
            "--predicate", "name-contains", "UI",
            "--max-results", "10",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert client.calls == [
        (
            "ak.wwise.core.object.get",
            {"waql": 'from type Sound where name : "UI" take 10'},
            {"return": ["id", "name", "type", "path"]},
        )
    ]
