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
    # Output may describe lossless JSON entries. The input continuation must
    # still expose only the closed business flags, never caller-authored JSON.
    assert "json" not in json.dumps(payload["continuation"]).casefold()
    assert "lossless JSON entries" in payload["result_presence"]["delivery"]["large_observation"]
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
            "sound": "alias of all-sounds; every Wwise Sound, including SFX and Voice",
            "sound-sfx": "only Sound objects whose source language is SFX",
            "sound-voice": "only Sound objects whose source language is not SFX",
        }
        assert payload["sources"]["short_id_candidates"] == "--short-id <uint32> --short-id-kind <business-kind> --max-results <1..1000>"
        assert payload["source_rules"]["short_id"]["mutation_authority"] is False
        assert payload["sources"]["selected_native_kind"] == "--type-selection <Gateway-issued live type selection>"
        selected_kind = payload["source_rules"]["selected_native_kind"]
        assert selected_kind["mutation_authority"] is False
        assert "900-second expiry" in selected_kind["binding"]
        assert "without alias inference or retry" in selected_kind["native_queryability"]
        assert {key: value for key, value in payload["source_rules"].items() if key not in {"short_id", "selected_native_kind"}} == {
            "exactly_one_source": True,
            "common_kind_is_a_source": (
                "--kind is valid only when no path, id, search, or Query Editor "
                "source is present"
            ),
            "kind_filter_after_another_source": "--predicate kind-is <business-kind>",
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


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_query_schema_discloses_diagnostic_view_exclusions_before_transport(tmp_path: Path, version: str) -> None:
    env = _env(tmp_path, version)
    code, schema = gateway.execute_gateway(["query-schema"], env=env,
        client_factory=lambda _url: pytest.fail("query-schema must stay offline"))
    assert code == 0
    view = schema["views"]["sound-routing-diagnostics"]
    assert view["exact_object_bound"] == 1
    assert "--exact-id" in view["source"] and "--path-segment" in view["source"]
    assert "literal" in view["source"] and "one exact" in view["source"]
    forbidden = {
        "--include": ["volume-db"], "--include-field": ["attenuation"],
        "--relationship": ["children"], "--predicate": ["name-is", "Sound"], "--max-results": ["1"],
    }
    assert set(view["cannot_combine_with"]) == set(forbidden)
    assert view["additional_fields"]["omit_options"] == ["--view"]
    assert view["additional_fields"]["field_options"] == ["--include", "--include-field"]
    identity = ["--exact-id", "{33333333-3333-3333-3333-333333333333}"]
    for option in view["cannot_combine_with"]:
        code, payload = gateway.execute_gateway(["query-object", *identity,
            "--view", "sound-routing-diagnostics", option, *forbidden[option]], env=env,
            client_factory=lambda _url: pytest.fail("view conflict must reject before transport"))
        assert code == 2, (option, payload)
        assert payload["error_code"] == "GatewayInputError"
        assert "owns its complete projection" in payload["message"]
    # The actual failed Agent combination must remain invalid after disclosure.
    code, _ = gateway.execute_gateway(["query-object", *identity, "--view", "sound-routing-diagnostics",
        "--include", "volume-db", "--include-field", "attenuation"], env=env,
        client_factory=lambda _url: pytest.fail("combined view projection must reject before transport"))
    assert code == 2


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("source", [
    ["--exact-id", "{33333333-3333-3333-3333-333333333333}"],
    ["--path-segment", "Actor-Mixer Hierarchy", "--path-segment", "Default Work Unit", "--path-segment", "Sound"],
])
def test_diagnostic_view_and_separate_extra_field_query_keep_existing_input_boundaries(tmp_path: Path, version: str, source: list[str]) -> None:
    env = _env(tmp_path, version)
    parser = gateway.build_parser()
    view = parser.parse_args(["query-object", *source, "--view", "sound-routing-diagnostics", "--detail"])
    if version == "2021.1":
        # The generic active-source implementation gap remains #181 / #174;
        # this diagnostic view cannot turn that missing mapping into support.
        with pytest.raises(gateway.GatewayInputError, match="active-source.*2021.1"):
            gateway.preflight_query_object_input(view, env=env)
    else:
        gateway.preflight_query_object_input(view, env=env)
    ordinary = parser.parse_args(["query-object", *source, "--include", "volume-db",
        "--include-field", "attenuation", "--max-results", "1"])
    gateway.preflight_query_object_input(ordinary, env=env)
    assert view.detail and view.business_view == "sound-routing-diagnostics"
    assert ordinary.business_view is None and ordinary.max_results == 1


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


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_exact_query_missing_guid_retains_native_identity_failure(tmp_path: Path, version: str) -> None:
    native_row = {"name": "Context", "owner": None}
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return super().call(uri, args, options)
            self.calls.append((uri, dict(args or {}), dict(options or {})))
            return {"return": [native_row]}
    client = Client(version)
    code, payload = gateway.execute_gateway(["query-object", "--exact-id", "{22222222-2222-2222-2222-222222222222}", "--include", "owner"],
        env=_env(tmp_path, version), client_factory=lambda _: client)
    assert code == 2, payload
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert payload["details"]["call"]["ok"] is True
    assert payload["details"]["native_observation"] == {"return": [native_row]}
    assert len(client.calls) == 1


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


def test_all_sound_business_alias_compiles_to_the_same_closed_type_filter(
    tmp_path: Path,
) -> None:
    client = _AdvancedQueryClient("2025.1")
    code, payload = gateway.execute_gateway(
        [
            "query-object",
            "--path-segment",
            "Actor-Mixer Hierarchy",
            "--relationship",
            "descendants",
            "--predicate",
            "kind-is",
            "sound",
            "--max-results",
            "10",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert client.calls == [
        (
            "ak.wwise.core.object.get",
            {
                "waql": (
                    r'from object "\Actor-Mixer Hierarchy" '
                    'select descendants where type = "Sound" take 10'
                )
            },
            {"return": ["id", "name", "type", "path"]},
        )
    ]


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_public_query_reads_switch_child_context_then_exact_context_identity(tmp_path: Path, version: str) -> None:
    child_id = "{11111111-1111-1111-1111-111111111111}"
    context_id = "{22222222-2222-2222-2222-222222222222}"
    parent_id = "{33333333-3333-3333-3333-333333333333}"
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return super().call(uri, args, options)
            self.calls.append((uri, dict(args or {}), dict(options or {})))
            if len(self.calls) == 1:
                return {"return": [{"id": child_id, "name": "Footstep", "type": "Sound", "path": r"\Containers\Footsteps\Footstep", "switchContainerChildContext": {"id": context_id}}]}
            return {"return": [{"id": context_id, "name": "Context", "type": "ObjectSettingAssoc", "path": r"\Containers\Footsteps\Context", "parent": {"id": parent_id}, "owner": {"id": child_id}}]}
    env = _env(tmp_path, version)
    code, schema = gateway.execute_gateway(["query-schema"], env=env)
    assert code == 0, schema
    assert "switch-container-child-context" in schema["business_outputs"]
    client = Client(version)
    code, child = gateway.execute_gateway(["query-object", "--exact-id", child_id, "--include", "switch-container-child-context"], env=env, client_factory=lambda _: client)
    assert code == 0, child
    assert child["agent_result"][0]["switch_container_child_context"] == {"id": context_id}
    code, context = gateway.execute_gateway(["query-object", "--exact-id", child["agent_result"][0]["switch_container_child_context"]["id"], "--include", "parent", "--include", "owner"], env=env, client_factory=lambda _: client)
    assert code == 0, context
    assert context["agent_result"][0]["id"] == context_id
    assert context["agent_result"][0]["parent"] == {"id": parent_id}
    assert context["agent_result"][0]["owner"] == {"id": child_id}
    assert client.calls[0] == ("ak.wwise.core.object.get", {"waql": 'from object "{11111111-1111-1111-1111-111111111111}"'}, {"return": ["id", "name", "type", "path", "switchContainerChildContext"]})
    assert client.calls[1] == ("ak.wwise.core.object.get", {"waql": 'from object "{22222222-2222-2222-2222-222222222222}"'}, {"return": ["id", "name", "type", "path", "parent", "owner"]})
    assert list(context)[-1] == "agent_result"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_switch_context_output_does_not_expose_a_native_accessor_input(tmp_path: Path, version: str, capsys) -> None:
    with pytest.raises(SystemExit) as rejected:
        gateway.execute_gateway(["query-object", "--exact-id", "{11111111-1111-1111-1111-111111111111}", "--include", "switchContainerChildContext"],
            env=_env(tmp_path, version), client_factory=lambda _: pytest.fail("invalid business output connected"))
    assert rejected.value.code == 2
    assert "switch-container-child-context" in capsys.readouterr().err


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("advanced", [False, True])
def test_query_preserves_optional_identity_and_output_absence(tmp_path: Path, version: str, advanced: bool) -> None:
    context_id = "{22222222-2222-2222-2222-222222222222}"
    native_row = {"id": context_id, "name": "", "path": "", "owner": None}
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return super().call(uri, args, options)
            self.calls.append((uri, dict(args or {}), dict(options or {})))
            return {"return": [dict(native_row)]}
    source = ["--advanced-waql", 'from object "' + context_id + '"', "--max-results", "1"] if advanced else ["--exact-id", context_id]
    client = Client(version)
    code, payload = gateway.execute_gateway(["query-object", *source, "--include", "parent", "--include", "owner"],
        env=_env(tmp_path, version), client_factory=lambda _: client)
    assert code == 0, payload
    row = payload["agent_result"][0]
    assert {key: row[key] for key in native_row} == native_row
    assert "type" not in row and "parent" not in row
    assert row["unavailable_fields"] == ["type", "parent"]
    assert row["identity_completeness"] == {"complete": False, "unavailable_fields": ["type"], "mutation_authority": False}
    assert "mutation_selection" not in payload
    assert payload["call"]["ok"] is True
    assert payload["native_observation"] == {"return": [native_row]}
    assert len(client.calls) == 1
    assert list(payload)[-1] == "agent_result"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_exact_context_custom_fields_do_not_require_optional_native_type(tmp_path: Path, version: str) -> None:
    context_id = "{22222222-2222-2222-2222-222222222222}"
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return super().call(uri, args, options)
            self.calls.append((uri, dict(args or {}), dict(options or {})))
            if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
                assert args == {"object": context_id}
                return {"return": ["ContinuePlay", "FadeInTime"]}
            if uri == "ak.wwise.core.object.getPropertyInfo":
                assert args["object"] == context_id
                return {"name": args["property"], "type": "bool" if args["property"] == "ContinuePlay" else "Real32"}
            assert uri == "ak.wwise.core.object.get"
            assert options["return"] == ["id", "name", "type", "path", "@ContinuePlay", "@FadeInTime"]
            return {"return": [{"id": context_id, "name": "", "path": "", "@ContinuePlay": False, "@FadeInTime": 0}]}
    client = Client(version)
    code, payload = gateway.execute_gateway(["query-object", "--exact-id", context_id,
        "--include-field", "ContinuePlay", "--include-field", "FadeInTime"], env=_env(tmp_path, version), client_factory=lambda _: client)
    assert code == 0, payload
    row = payload["agent_result"][0]
    assert row["properties"] == {"ContinuePlay": False, "FadeInTime": 0}
    assert "type" not in row
    assert row["identity_completeness"]["complete"] is False
    assert payload["native_observation"]["return"][0]["@ContinuePlay"] is False
    assert sum(uri == "ak.wwise.core.object.get" for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_query_schema_covers_every_named_native_return_through_closed_outputs(tmp_path: Path, version: str) -> None:
    definitions = json.loads((SCRIPT_PATH.parents[1] / "resources/manifest" / version / "definitions.json").read_text())
    native = definitions["documents"]["waapi_definitions.json"]["definitions"]["objectReturn"]["properties"]
    env = _env(tmp_path, version)
    code, schema = gateway.execute_gateway(["query-schema"], env=env, client_factory=lambda _: pytest.fail("schema connected"))
    assert code == 0, schema
    covered = set(schema["identity_projection"])
    for output in schema["business_outputs"]:
        code, detail = gateway.execute_gateway(["query-schema", "--output", output], env=env,
            client_factory=lambda _: pytest.fail("output disclosure connected"))
        assert code == 0, detail
        selected = detail["business_output"]
        assert selected["available"] is True
        if selected["native_definition"] is None:
            continue
        field = selected["native_definition"]["pointer"].rsplit("/", 1)[1]
        covered.add(field)
        assert selected["native_definition"]["pointer"] == "/definitions/objectReturn/properties/" + field
        assert selected["result_schema"] == native[field]
        assert selected["output_field"]
    assert covered == set(native)


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
def test_query_output_detail_resolves_nested_result_shape(tmp_path: Path, version: str) -> None:
    code, detail = gateway.execute_gateway(["query-schema", "--output", "curve-points"], env=_env(tmp_path, version))
    assert code == 0, detail
    shape = detail["business_output"]["result_shape"]
    assert shape["type"] == "array"
    assert shape["items"]["required"] == ["x", "y", "shape"]
    assert shape["items"]["properties"]["x"]["type"] == "number"
    assert "Linear" in shape["items"]["properties"]["shape"]["enum"]


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_new_query_output_version_boundary_rejects_before_transport(tmp_path: Path, version: str) -> None:
    env = _env(tmp_path, version)
    code, detail = gateway.execute_gateway(["query-schema", "--output", "conversion-format"], env=env)
    assert code == 0, detail
    assert detail["business_output"]["available"] is (version == "2025.1")
    assert detail["business_output"]["supported_versions"] == ["2025.1"]
    if version != "2025.1":
        code, result = gateway.execute_gateway(["query-object", "--exact-id", "{22222222-2222-2222-2222-222222222222}", "--include", "conversion-format"],
            env=env, client_factory=lambda _: pytest.fail("unavailable output connected"))
        assert code == 2, result
        assert result["error_code"] == "GatewayInputError"
        assert "2025.1" in result["message"]


@pytest.mark.parametrize("version,field,native,output,value", [
    ("2021.1", "audio-source-trim-values", "audioSourceTrimValues", "audio_source_trim_values", {"trimBegin": 0.5, "trimEnd": 2.5}),
    ("2022.1", "implicitly-muted", "isImplicitMute", "implicitly_muted", False),
    ("2023.1", "state-groups", "stateGroups", "state_groups", [{"id": "{33333333-3333-3333-3333-333333333333}", "name": "Weather"}]),
    ("2024.1", "original-sample-rate", "originalSampleRate", "original_sample_rate", 48000),
    ("2025.1", "conversion-format", "conversionFormat", "conversion_format", "Vorbis"),
    ("2025.1", "extracted-media", "extractMedia", "extracted_media", ["Audio/source.wem"]),
])
def test_public_versioned_query_outputs_preserve_native_values(tmp_path: Path, version: str, field: str, native: str, output: str, value) -> None:
    object_id = "{22222222-2222-2222-2222-222222222222}"
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return super().call(uri, args, options)
            self.calls.append((uri, dict(args or {}), dict(options or {})))
            return {"return": [{"id": object_id, "name": "Object", "type": "Sound", "path": r"\Containers\Object", native: value}]}
    client = Client(version)
    code, result = gateway.execute_gateway(["query-object", "--exact-id", object_id, "--include", field],
        env=_env(tmp_path, version), client_factory=lambda _: client)
    assert code == 0, result
    assert client.calls == [("ak.wwise.core.object.get", {"waql": 'from object "' + object_id + '"'}, {"return": ["id", "name", "type", "path", native]})]
    assert result["agent_result"][0][output] == value


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("advanced", [False, True])
@pytest.mark.parametrize("platform,language", [("Windows", "English(US)"),
    ("{33333333-3333-3333-3333-333333333333}", "{44444444-4444-4444-4444-444444444444}")])
def test_public_queries_compile_closed_platform_and_language_scopes(tmp_path: Path, version: str, advanced: bool, platform: str, language: str) -> None:
    source = ["--advanced-waql", "from project", "--max-results", "3"] if advanced else ["--kind", "project", "--max-results", "3"]
    client = _AdvancedQueryClient(version)
    code, result = gateway.execute_gateway(["query-object", *source, "--platform", platform, "--language", language],
        env=_env(tmp_path, version), client_factory=lambda _: client)
    assert code == 0, result
    assert client.calls[0][2] == {"return": ["id", "name", "type", "path"], "platform": platform, "language": language}
    code, schema = gateway.execute_gateway(["query-schema", *( ["--advanced"] if advanced else [])], env=_env(tmp_path, version),
        client_factory=lambda _: pytest.fail("query scope schema connected"))
    assert code == 0, schema
    assert schema["return_scope"]["platform"]["cli"] == "--platform <exact name or GUID>"
    assert schema["return_scope"]["platform"]["omitted"] == "current Wwise platform"
    assert schema["return_scope"]["language"]["cli"] == "--language <exact name or GUID>"


@pytest.mark.parametrize("argv", [
    ["--platform", ""], ["--language", " "], ["--platform", "name\nother"],
    ["--language", "声" * 200], ["--platform", "Windows", "--platform", "Mac"],
    ["--language", "SFX", "--language", "English(US)"],
])
def test_query_return_scope_rejects_unusable_or_repeated_selection_before_transport(tmp_path: Path, argv: list[str]) -> None:
    code, result = gateway.execute_gateway(["query-object", "--kind", "project", "--max-results", "1", *argv],
        env=_env(tmp_path, "2025.1"), client_factory=lambda _: pytest.fail("invalid return scope connected"))
    assert code == 2, result
    assert result["error_code"] == "GatewayInputError"


def test_query_generated_event_hop_preserves_return_scope(tmp_path: Path) -> None:
    event_id = "{22222222-2222-2222-2222-222222222222}"
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return super().call(uri, args, options)
            self.calls.append((uri, dict(args or {}), dict(options or {})))
            return {"return": [{"id": event_id, "name": "Play", "type": "Event", "path": r"\Events\Play"}]}
    client = Client("2025.1")
    code, result = gateway.execute_gateway(["query-object", "--exact-id", event_id, "--platform", "Windows", "--language", "SFX"],
        env=_env(tmp_path, "2025.1"), client_factory=lambda _: client)
    assert code == 0, result
    assert result["continuations"][0]["next_command"]["gateway_argv"] == ["query-object", "--platform", "Windows", "--language", "SFX", "--exact-id", event_id, "--relationship", "event-actions"]


def test_original_file_reference_scan_compiles_requested_return_scope(tmp_path: Path) -> None:
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return super().call(uri, args, options)
            self.calls.append((uri, dict(args or {}), dict(options or {})))
            return {"return": []}
    client = Client("2025.1")
    code, result = gateway.execute_gateway(["query-object", "--match-original-file-path", "/owned/source.wav", "--max-results", "1000", "--platform", "Windows", "--language", "SFX"],
        env=_env(tmp_path, "2025.1"), client_factory=lambda _: client)
    assert code == 0, result
    assert client.calls[0][2] == {"return": ["id", "path", "originalFilePath"], "platform": "Windows", "language": "SFX"}


@pytest.fixture
def short_id_product_capture(request, version):
    import os
    context = os.environ.get("WAAPI_SHORT_ID_BRANCH_CAPTURE_CONTEXT")
    observed = {}
    # This historical capture owns the native from.id branch. The 2021
    # alternative now uses WAQL and must not receive that branch's credit.
    if context and version != "2021.1":
        from tests.support.short_id_query_branch_evidence import load_short_id_capture, finish_short_id_capture
        from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
        capture = load_short_id_capture(Path(context), request.node.nodeid, version)
        register_exact_evidence_finalizer(request.node, lambda reports: finish_short_id_capture(capture, reports, observed))
    return observed


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_short_id_source_resolves_native_candidates_then_applies_business_read_semantics(tmp_path: Path, version: str, short_id_product_capture: dict) -> None:
    object_id = "{11111111-1111-1111-1111-111111111111}"
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get":
                self.calls.append((uri, args, options))
                return {"return": [{"id": object_id, "name": "Rain", "type": "Event", "path": r"\Events\Rain", "notes": "Exterior"}]}
            return super().call(uri, args, options)
    client = Client(version)
    code, payload = gateway.execute_gateway(
        ["query-object", "--short-id", "123456", "--short-id-kind", "event", "--max-results", "5", "--predicate", "name-is", "Rain",
         "--include", "notes", "--platform", "Windows", "--language", "English(US)", "--detail"],
        env=_env(tmp_path, version), client_factory=lambda _: client)
    assert code == 0, json.dumps(payload,ensure_ascii=False)
    queries = [call for call in client.calls if call[0] == "ak.wwise.core.object.get"]
    assert queries[0][1] == ({"waql": "from type Event where shortId = 123456.0 take 65"} if version == "2021.1" else
                             {"from": {"id": [{"shortId": 123456, "type": 10}]}, "transform": [{"range": [0, 65]}]})
    assert queries[0][2] == {"return": ["id", "name", "type", "path"]}
    assert queries[1][1] == {"waql": 'from object "{11111111-1111-1111-1111-111111111111}" where name = "Rain" take 5'}
    assert queries[1][2] == {"return": ["id", "name", "type", "path", "notes"], "platform": "Windows", "language": "English(US)"}
    assert payload["agent_result"][0]["notes"] == "Exterior"
    assert payload["source_resolution"]["candidate_count"] == 1
    assert payload["source_resolution"]["mutation_authority"] is False
    assert payload["mutation_selection"]["candidates"][0]["id"] == object_id
    short_id_product_capture.update({"gateway": {"argv": ["query-object", "--short-id", "123456", "--short-id-kind", "event", "--max-results", "5",
        "--predicate", "name-is", "Rain", "--include", "notes", "--platform", "Windows", "--language", "English(US)", "--detail"],
        "exit_code": code, "payload": payload},
        "native_call": {"uri": queries[0][0], "args": queries[0][1], "options": queries[0][2]},
        "final_call": {"uri": queries[1][0], "args": queries[1][1], "options": queries[1][2]}})


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_short_id_collision_preserves_all_candidates_for_relationship_reads(tmp_path: Path, version: str) -> None:
    ids = ["{11111111-1111-1111-1111-111111111111}", "{22222222-2222-2222-2222-222222222222}"]
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get":
                self.calls.append((uri, args, options))
                return {"return": [{"id": value, "name": "Rain", "type": "Event", "path": r"\Events\Rain"} for value in ids]}
            return super().call(uri, args, options)
    client = Client(version)
    code, payload = gateway.execute_gateway(["query-object", "--short-id", "0", "--short-id-kind", "event", "--max-results", "4", "--relationship", "parent"],
        env=_env(tmp_path, version), client_factory=lambda _: client)
    assert code == 0, payload
    assert client.calls[-1][1] == {"waql": 'from object "{11111111-1111-1111-1111-111111111111}", "{22222222-2222-2222-2222-222222222222}" select parent take 4'}
    assert payload["source_resolution"]["candidate_count"] == 2
    assert [row["id"] for row in payload["agent_result"]] == ids
    assert len(payload["mutation_selection"]["candidates"]) == 2


@pytest.mark.parametrize("count,custom_field,reason", [(0, False, None), (2, True, "custom_fields_require_one_exact_guid"),
                                                       (65, False, "short_id_source_limit_reached")])
@pytest.mark.parametrize("version", ["2021.1", "2023.1", "2025.1"])
def test_short_id_empty_and_unresolved_sources_do_not_run_a_partial_final_query(
    tmp_path: Path, count: int, custom_field: bool, reason: str | None, version: str,
) -> None:
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get":
                self.calls.append((uri, args, options))
                literal = "4294967295.0" if version in {"2021.1", "2023.1"} else "4294967295"
                assert args == {"waql": f"from type DialogueEvent where shortId = {literal} take 65"}, args
                return {"return": [{"id": "{%08X-1111-1111-1111-111111111111}" % n} for n in range(count)]}
            return super().call(uri, args, options)
    client = Client(version)
    command = ["query-object", "--short-id", "4294967295", "--short-id-kind", "dialogue-event", "--max-results", "3"]
    if custom_field:
        command.extend(["--include-field", "Volume"])
    code, payload = gateway.execute_gateway(command, env=_env(tmp_path, version), client_factory=lambda _: client)
    assert code == 0, payload
    assert len([call for call in client.calls if call[0] == "ak.wwise.core.object.get"]) == 1
    if reason is None:
        assert payload["agent_result"] == [] and payload["source_resolution"]["complete"] is True
    else:
        assert payload["status"] == "needs_clarification" and payload["agent_result"]["reason"] == reason
        assert payload["agent_result"]["mutation_authority"] is False


@pytest.mark.parametrize("extra", [["--short-id", "-1", "--max-results", "2"], ["--short-id", "4294967296", "--max-results", "2"],
                                  ["--short-id", "1"], ["--short-id", "1", "--max-results", "1001"]])
def test_short_id_source_requires_a_valid_uint32_and_result_bound_before_connecting(tmp_path: Path, extra: list[str]) -> None:
    code, payload = gateway.execute_gateway(["query-object", *extra], env=_env(tmp_path, "2025.1"),
        client_factory=lambda _: pytest.fail("invalid Short ID source connected"))
    assert code == 2, payload


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("selector", [123456, {"shortId": 123456}, {"shortId": 123456, "type": "Event"}])
def test_native_short_id_recursive_schema_rejects_bare_missing_and_invalid_type_before_dispatch(
    tmp_path: Path, version: str, selector: object,
) -> None:
    from wwise_waapi.builders.common import SemanticValidationError
    from wwise_waapi.builders.schema import validate_resolved_semantic_payload
    # This is the same recursive schema boundary called by query preflight;
    # root explicitly requested these malformed referenced-shape controls.
    with pytest.raises(SemanticValidationError):
        validate_resolved_semantic_payload("ak.wwise.core.object.get",
            {"from": {"id": [selector]}, "transform": [{"range": [0, 65]}]},
            {"return": ["id", "name", "type", "path"]}, version=version)


@pytest.mark.parametrize("kind,object_type", [("event", "Event"), ("switch-group", "SwitchGroup"),
    ("state-group", "StateGroup"), ("effect", "Effect"), ("soundbank", "SoundBank"),
    ("bus", "Bus"), ("aux-bus", "AuxBus"), ("game-parameter", "GameParameter"),
    ("trigger", "Trigger"), ("audio-device", "AudioDevice")])
def test_short_id_2021_business_kinds_use_documented_typed_predicate(tmp_path: Path, kind: str, object_type: str) -> None:
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get":
                self.calls.append((uri, args, options))
                return {"return": []}
            return super().call(uri, args, options)
    client = Client("2021.1")
    code, payload = gateway.execute_gateway(["query-object", "--short-id", "123456", "--short-id-kind", kind, "--max-results", "3"],
        env=_env(tmp_path, "2021.1"), client_factory=lambda _: client)
    assert code == 0, payload
    assert client.calls[-1][1] == {"waql": f"from type {object_type} where shortId = 123456.0 take 65"}


@pytest.mark.parametrize("version", ["2021.1", "2023.1", "2025.1"])
def test_short_id_collision_final_query_rejects_an_unrelated_native_guid(tmp_path: Path, version: str) -> None:
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get":
                self.calls.append((uri, args, options))
                ids = ["{11111111-1111-1111-1111-111111111111}", "{22222222-2222-2222-2222-222222222222}"] if args.get("waql", "").startswith("from type") else ["{33333333-3333-3333-3333-333333333333}"]
                return {"return": [{"id": value} for value in ids]}
            return super().call(uri, args, options)
    client = Client(version)
    code, payload = gateway.execute_gateway(["query-object", "--short-id", "123456", "--short-id-kind", "dialogue-event", "--max-results", "3"],
        env=_env(tmp_path, version), client_factory=lambda _: client)
    assert code == 2, payload
    assert payload["error_code"] == "SHORT_ID_CANDIDATE_DRIFT"


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("kind,code", [("event", 10), ("switch-group", 12), ("state-group", 14), ("effect", 17),
    ("soundbank", 18), ("bus", 19), ("aux-bus", 20), ("game-parameter", 22), ("trigger", 41), ("audio-device", 68)])
def test_short_id_business_kinds_compile_only_the_exact_version_documented_type_codes(tmp_path: Path, version: str, kind: str, code: int) -> None:
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get":
                self.calls.append((uri, args, options))
                return {"return": []}
            return super().call(uri, args, options)
    client = Client(version)
    exit_code, payload = gateway.execute_gateway(["query-object", "--short-id", "1", "--short-id-kind", kind, "--max-results", "3"],
        env=_env(tmp_path, version), client_factory=lambda _: client)
    assert exit_code == 0, payload
    assert client.calls[-1][1] == {"from": {"id": [{"shortId": 1, "type": code}]}, "transform": [{"range": [0, 65]}]}


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("policy", ["read_only", "ask_before_changes", "allow_changes"])
def test_short_id_dialogue_query_and_schema_agree_on_typed_source(tmp_path: Path, version: str, policy: str) -> None:
    from tests.support.gateway_config import set_gateway_config
    env = set_gateway_config(_env(tmp_path, version), project_modification_policy=policy)
    code, schema = gateway.execute_gateway(["query-schema"], env=env,
        client_factory=lambda _: pytest.fail("schema must stay offline"))
    assert code == 0, schema
    assert schema["source_rules"]["short_id"]["mapped_versions"] == list(SUPPORTED_WWISE_VERSION_KEYS)
    assert "dialogue-event" in schema["source_rules"]["short_id"]["kind_choices"]
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get":
                self.calls.append((uri, args, options))
                return {"return": []}
            return super().call(uri, args, options)
    client = Client(version)
    code, result = gateway.execute_gateway(["query-object", "--short-id", "4294967295", "--short-id-kind", "dialogue-event", "--max-results", "2"],
        env=env, client_factory=lambda _: client)
    assert code == 0, result
    literal = "4294967295.0" if version in {"2021.1", "2022.1", "2023.1"} else "4294967295"
    assert client.calls[-1][1:] == ({"waql": f"from type DialogueEvent where shortId = {literal} take 65"}, {"return": ["id", "name", "type", "path"]})


@pytest.mark.parametrize("version,kind,object_type,number", [
    (version, "dialogue-event", "DialogueEvent", number)
    for version in SUPPORTED_WWISE_VERSION_KEYS
    for number in [0, 2147483647, 2147483648, 3970659059, 4294967295]
] + [(version, "event", "Event", 72162316) for version in SUPPORTED_WWISE_VERSION_KEYS])
def test_short_id_exact_uint32_native_expression_and_final_integer(tmp_path: Path, version: str, kind: str, object_type: str, number: int) -> None:
    object_id = "{3C874205-5335-4290-830F-A8BFF3AE8A6B}"
    row = {"id": object_id, "name": "Known", "type": object_type, "path": r"\Objects\Known", "shortId": number}
    native = kind == "event" and version != "2021.1"
    literal = f"{number}.0" if version in {"2021.1", "2022.1", "2023.1"} else str(number)
    expected = ({"from": {"id": [{"shortId": number, "type": 10}]}, "transform": [{"range": [0, 65]}]} if native else
                {"waql": f"from type {object_type} where shortId = {literal} take 65"})
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri != "ak.wwise.core.object.get":
                return super().call(uri, args, options)
            self.calls.append((uri, args, options))
            if len(self.calls) == 1:
                assert args == expected and options == {"return": ["id", "name", "type", "path"]}, (args, options)
                return {"return": [{key: row[key] for key in options["return"]}]}
            assert args == {"waql": f'from object "{object_id}" take 2'}, args
            assert options == {"return": ["id", "name", "type", "path", "shortId"]}, options
            return {"return": [row]}
    client = Client(version)
    code, result = gateway.execute_gateway(["query-object", "--short-id", str(number), "--short-id-kind", kind,
        "--max-results", "2", "--include", "short-id"], env=_env(tmp_path, version), client_factory=lambda _: client)
    assert code == 0, result
    assert result["agent_result"] == [{**{key: value for key, value in row.items() if key != "shortId"}, "short_id": number}]
    assert type(result["agent_result"][0]["short_id"]) is int
    assert result["source_resolution"]["short_id"] == number and type(result["source_resolution"]["short_id"]) is int
    assert result["source_resolution"]["complete"] is True and len(client.calls) == 2


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("rows", [[{"id": "malformed"}], [{"id": 123}], [{}],
    [{"id": "{11111111-1111-1111-1111-111111111111}"}] * 2])
def test_short_id_query_rejects_unbound_or_duplicate_native_candidates(tmp_path: Path, version: str, rows: list) -> None:
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get":
                self.calls.append((uri, args, options))
                return {"return": rows}
            return super().call(uri, args, options)
    client = Client(version)
    code, result = gateway.execute_gateway(["query-object", "--short-id", "1", "--short-id-kind", "event", "--max-results", "2"],
        env=_env(tmp_path, version), client_factory=lambda _: client)
    assert code == 2 and result["error_code"] == "INVALID_QUERY_RESULT", result
    assert len([call for call in client.calls if call[0] == "ak.wwise.core.object.get"]) == 1


def _legacy_active_source_client(tmp_path, *, fault=None, language_name="SFX"):
    sound = "{11111111-1111-1111-1111-111111111111}"
    inactive = "{22222222-2222-2222-2222-222222222222}"
    active = "{33333333-3333-3333-3333-333333333333}"
    platform = "{44444444-4444-4444-4444-444444444444}"
    language = "{55555555-5555-5555-5555-555555555555}"
    project = "{66666666-6666-6666-6666-666666666666}"
    project_file = tmp_path / "Fixture.wproj"
    project_file.write_text("<Project />")
    class Client(_AdvancedQueryClient):
        child_reads = 0
        sound_reads = 0

        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return {**super().call(uri, args, options), "sessionId": project, "processId": 42}
            self.calls.append((uri, dict(args or {}), dict(options or {})))
            if uri == "ak.wwise.core.object.getTypes":
                return {"return": [{"classId": 65552, "name": "Sound", "type": "WObject"},
                    {"classId": 16, "name": "AudioSource", "type": "WObject"}]}
            assert uri == "ak.wwise.core.object.get", uri
            query = args["waql"]
            if query.startswith("from type Project"):
                rows = [{"id": project, "name": "Fixture", "type": "Project", "path": "\\", "filePath": str(project_file)}]
            elif query.startswith("from type Platform"):
                rows = [{"id": platform, "name": "Mac", "type": "Platform", "path": r"\Platforms\Mac"}]
            elif query.startswith("from type Language"):
                rows = [{"id": language, "name": language_name, "type": "Language", "path": "\\Languages\\" + language_name}]
            elif "select children" in query:
                self.child_reads += 1
                rows = [{"id": identity, "name": name, "type": "AudioFileSource", "classId": 16,
                    "path": r"\Sounds\Rain" + "\\" + name, "parent": {"id": sound},
                    "audioSource:language": {"id": language, "name": language_name},
                    "originalWavFilePath": "/owned/Originals/SFX/" + name + ".wav"}
                    for identity, name in ((inactive, "Alpha"), (active, "Beta"))]
                if language_name != "SFX":
                    rows[0]["audioSource:language"] = {"id": project, "name": "French(France)"}
                if fault == "duplicate-path":
                    rows[0]["originalWavFilePath"] = rows[1]["originalWavFilePath"]
                elif fault == "wrong-parent":
                    rows[1]["parent"] = {"id": project}
                elif fault == "missing-class":
                    del rows[1]["classId"]
                elif fault == "plugin":
                    rows[1]["type"] = "SourcePlugin"
                elif fault == "membership-drift" and self.child_reads == 2:
                    rows.pop(0)
                elif fault == "fence":
                    rows = [{**rows[0], "id": "{%08X-0000-0000-0000-000000000000}" % index} for index in range(1, 1001)]
            else:
                assert sound in query, query
                self.sound_reads += 1
                rows = [{"id": sound, "name": "Rain", "type": "Sound", "classId": 65552,
                    "path": r"\Sounds\Rain", "parent": {"id": project},
                    "originalWavFilePath": "/owned/Originals/SFX/Beta.wav",
                    "audioSource:language": {"id": language, "name": language_name}}]
                if fault in {"wrong-path", "sound-drift"} and (fault == "wrong-path" or self.sound_reads == 2):
                    rows[0]["originalWavFilePath"] = "/owned/Originals/SFX/Other.wav"
                elif fault == "null-path":
                    rows[0]["originalWavFilePath"] = None
                elif fault == "missing-path":
                    del rows[0]["originalWavFilePath"]
                elif fault == "parent-representation" and self.sound_reads == 2:
                    rows[0]["parent"] = project
            return {"return": [{key: row[key] for key in options["return"] if key in row} for row in rows]}
    return Client("2021.1"), {"sound": sound, "active": active, "platform": platform, "language": language}


@pytest.mark.parametrize("language_name", ["SFX", "English(US)"])
def test_2021_active_source_joins_complete_same_view_paths_independent_of_child_order(tmp_path, language_name):
    client, ids = _legacy_active_source_client(tmp_path, language_name=language_name)
    sound, active, platform, language = (ids[name] for name in ("sound", "active", "platform", "language"))
    code, result = gateway.execute_gateway(["query-object", "--exact-id", sound, "--platform", "Mac",
        "--language", language_name, "--include", "active-source"], env=_env(tmp_path, "2021.1"), client_factory=lambda _: client)
    assert code == 0, result
    assert result["agent_result"] == [{"id": sound, "name": "Rain", "type": "Sound", "path": r"\Sounds\Rain",
        "active_source": {"id": active, "name": "Beta"}}]
    assert list(result)[-1] == "agent_result"
    observations = [(args, options) for uri, args, options in client.calls if uri.endswith("object.get") and sound in args.get("waql", "")]
    assert len(observations) == 4
    assert all(options["platform"] == platform and options["language"] == language for _, options in observations)
    assert all("activeSource" not in options["return"] for _, options in observations)
    assert len(client.calls) <= 10


def test_2021_active_source_preserves_parent_identity_across_native_reference_representations(tmp_path):
    client, ids = _legacy_active_source_client(tmp_path, fault="parent-representation")
    code, result = gateway.execute_gateway(["query-object", "--exact-id", ids["sound"], "--platform", "Mac",
        "--language", "SFX", "--include", "active-source"], env=_env(tmp_path, "2021.1"), client_factory=lambda _: client)
    assert code == 0, result
    assert result["agent_result"][0]["active_source"]["id"] == ids["active"]


@pytest.mark.parametrize("fault,expected", [
    ("duplicate-path", "ACTIVE_SOURCE_SELECTION_UNRESOLVED"),
    ("wrong-path", "ACTIVE_SOURCE_SELECTION_UNRESOLVED"),
    ("missing-path", "ACTIVE_SOURCE_SELECTION_UNRESOLVED"),
    ("null-path", "ACTIVE_SOURCE_SELECTION_UNRESOLVED"),
    ("plugin", "ACTIVE_SOURCE_SELECTION_UNRESOLVED"),
    ("wrong-parent", "ACTIVE_SOURCE_INVALID_OBSERVATION"),
    ("missing-class", "ACTIVE_SOURCE_INVALID_OBSERVATION"),
    ("membership-drift", "ACTIVE_SOURCE_OBSERVATION_CHANGED"),
    ("sound-drift", "ACTIVE_SOURCE_OBSERVATION_CHANGED"),
    ("fence", "ACTIVE_SOURCE_OBSERVATION_INCOMPLETE"),
])
def test_2021_active_source_rejects_unproved_or_changed_selection_without_fallback(tmp_path, fault, expected):
    client, ids = _legacy_active_source_client(tmp_path, fault=fault)
    code, result = gateway.execute_gateway(["query-object", "--exact-id", ids["sound"], "--platform", "Mac",
        "--language", "SFX", "--include", "active-source"], env=_env(tmp_path, "2021.1"), client_factory=lambda _: client)
    assert code == 2 and result["error_code"] == expected, result
    assert not result.get("agent_result") and not result.get("continuations")
    assert result["details"]["native_absence_proven"] is False
    if fault in {"missing-path", "null-path"}:
        assert result["details"]["presence"] == ("absent" if fault == "missing-path" else "null")
    assert len(client.calls) <= 10
    assert all("activeSource" not in options.get("return", ()) for _, _, options in client.calls)


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_public_source_query_uses_exact_versioned_file_and_active_bindings(tmp_path, version):
    sound = "{11111111-1111-1111-1111-111111111111}"
    source = "{22222222-2222-2222-2222-222222222222}"
    class Client(_AdvancedQueryClient):
        def call(self, uri, args=None, options=None):
            if uri != "ak.wwise.core.object.get":
                return super().call(uri, args, options)
            self.calls.append((uri, dict(args), dict(options)))
            expected = "originalWavFilePath" if version == "2021.1" else "originalFilePath"
            assert expected in options["return"]
            if version == "2021.1":
                assert not {"originalFilePath", "activeSource"} & set(options["return"])
                assert args["waql"] == f'from object "{sound}" select children take 100'
                row = {"id": source, "name": "Audio", "type": "AudioFileSource", "path": r"\Sound\Audio"}
            else:
                assert args["waql"] == f'from object "{sound}"'
                row = {"id": sound, "name": "Sound", "type": "Sound", "path": r"\Sound", "activeSource": {"id": source}}
            row[expected] = "/owned/Originals/SFX/Audio.wav"
            return {"return": [row]}
    env, client = _env(tmp_path, version), Client(version)
    argv = ["query-object", "--exact-id", sound, "--language", "SFX", "--include", "original-file-path"]
    argv += ["--relationship", "children", "--max-results", "100"] if version == "2021.1" else ["--include", "active-source"]
    code, result = gateway.execute_gateway(argv, env=env, client_factory=lambda _: client)
    assert code == 0, result
    assert result["objects"][0]["original_file_path"] == "/owned/Originals/SFX/Audio.wav"
    assert result["objects"][0]["id"] == (source if version == "2021.1" else sound)
    assert client.calls[-1][2]["language"] == "SFX"
    if version == "2021.1":
        code, schema = gateway.execute_gateway(["query-schema", "--output", "active-source"], env=env)
        detail = schema["business_output"]
        assert code == 0 and detail["available"] is True
        assert detail["native_definition"] is None
        assert detail["derivation"]["runtime_xml"] is False
        before = len(client.calls)
        code, error = gateway.execute_gateway(["query-object", "--exact-id", sound, "--include", "active-source"],
            env=env, client_factory=lambda _: client)
        assert code != 0 and "explicit platform and language" in error["message"]
        assert len(client.calls) == before
        code, detail = gateway.execute_gateway(["query-schema", "--output", "original-file-path"], env=env)
        assert code == 0 and detail["business_output"]["native_definition"]["pointer"].endswith("/originalWavFilePath")
        code, schema = gateway.execute_gateway(["query-schema"], env=env)
        assert code == 0 and "active-source" not in schema["relationships"]
        with pytest.raises(SystemExit):
            gateway.build_parser().parse_args(["query-object", "--exact-id", sound, "--relationship", "active-source"])
        assert len(client.calls) == before
    else:
        code, schema = gateway.execute_gateway(["query-schema"], env=env)
        assert code == 0 and "active-source" not in schema["relationships"]
