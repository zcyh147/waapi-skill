from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from wwise_waapi.schema_inventory import load_definition_graph
from wwise_waapi.typed_requests import (
    compile_typed_request_contract,
    request_contract,
)


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills/waapi-skill/scripts/gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_gateway_complex_typed_tests", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)

VALIDATE_URI = "ak.wwise.debug.validateCall"
AUDIO_CONVERT_URI = "ak.wwise.core.audio.convert"
MEDIA_POOL_URI = "ak.wwise.core.mediaPool.get"


class FakeClient:
    def __init__(self, version: str) -> None:
        self.version = version
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []

    def call(self, uri: str, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            year, major = (int(item) for item in self.version.split("."))
            return {"isCommandLine": False, "version": {"year": year, "major": major}}
        return {}

    def disconnect(self) -> None:
        pass


def _env(tmp_path: Path, version: str) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"wwise_version": version, "waapi_host": "127.0.0.1", "waapi_port": 31337}), encoding="utf-8")
    return {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_VERSION": version}


def test_media_pool_schema_marks_scalar_array_items_as_append_facts(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", MEDIA_POOL_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )

    assert exit_code == 0, schema
    databases = next(
        field for field in schema["fields"] if field["path"] == ["args", "databases"]
    )
    assert databases["fact_construction"] == {
        "nonempty_scalar_items": {
            "phase": "before_dynamic_disclosure",
            "fact_action": "append",
            "repeat_for_each_item": True,
        },
        "empty_array_only": {
            "phase": "before_dynamic_disclosure",
            "fact_action": "present",
            "must_not_accompany": ["append"],
        },
    }


def test_media_pool_dynamic_child_defers_parent_append_until_disclosure_finishes(
    tmp_path: Path,
) -> None:
    contract = request_contract("2025.1", MEDIA_POOL_URI)
    filters = next(field for field in contract.fields if field.name == "filters")

    exit_code, item = gateway.execute_gateway(
        [
            "--version", "2025.1", "request-array-item", MEDIA_POOL_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", filters.handle,
            "--index", "0", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )

    assert exit_code == 0, item
    assert item["continuation"]["request_wide_order"] == {
        "phase": "dynamic_disclosure",
        "finish_current_root_disclosure_chain_first": True,
        "disclosure_chain_definition": (
            "only branch_disclosure and nested_container_disclosures; "
            "child_contract branch choices are typed facts"
        ),
        "array_item_order": "ascending_index",
        "nested_member_order": "schema_property_order",
        "child_fact_order": "child_contract_schema_order",
        "facts_using_returned_handles": (
            "after_all_dynamic_disclosures_in_deferred_fact_queue_order"
        ),
        "deferred_fact_queue": {
            "scope": "current_disclosed_root",
            "root_boundary": "before_next_parent_array_sibling",
            "drain_after": "root_dynamic_disclosures",
            "response_order": "parent_fact_then_child_contract_then_descendants",
            "array_traversal": (
                "business_present_sibling_indices_then_nested_members"
            ),
            "member_traversal": "schema_property_order",
        },
        "this_handle_is_not_a_complete_request": True,
    }
    assert item["continuation"]["deferred_fact"]["argv"] == [
        "--action", "add_typed_fact", "--fact-action", "append",
        "--field-handle", filters.handle, "--value-type", "object",
        "--fact-value", item["handle"],
    ]
    assert "branch_disclosure" not in item["continuation"]
    branch_choices = item["child_contract"]["branch_choices"]
    assert branch_choices
    type_branch = next(row for row in branch_choices if row["key"] == "type")
    field_choice = next(
        choice
        for choice in type_branch["choices"]
        if choice.get("enum") == ["field"]
    )
    assert field_choice["deferred_fact"]["argv"] == [
        "--action", "add_typed_fact", "--fact-action", "choose-dynamic",
        "--field-handle", item["handle"], "--fact-value",
        field_choice["handle"], "--key", "type",
    ]
    assert field_choice["deferred_fact"]["is_next_command"] is False
    assert field_choice["deferred_fact"]["queue_phase"] == "child_contract"
    assert field_choice["deferred_fact"]["queue_order"] == item["continuation"][
        "request_wide_order"
    ]["deferred_fact_queue"]
    assert field_choice["typed_fact"] == {
        "action": "choose-dynamic",
        "handle": item["handle"],
        "value_type": "choice",
        "value": field_choice["handle"],
        "key": "type",
    }
    assert item["continuation"]["deferred_fact"]["execute_after"] == (
        "all_dynamic_disclosures_for_current_root"
    )
    assert item["continuation"]["deferred_fact"]["queue_phase"] == (
        "parent_response"
    )
    assert item["continuation"]["deferred_fact"]["queue_order"] == item[
        "continuation"
    ]["request_wide_order"]["deferred_fact_queue"]
    assert item["continuation"]["deferred_fact"]["is_next_command"] is False
    assert "deferred_action_argv" not in item["continuation"]


def test_audio_convert_schema_forbids_present_with_nonempty_languages(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", AUDIO_CONVERT_URI],
        env=_env(tmp_path, "2024.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )

    assert exit_code == 0, schema
    languages = next(
        field for field in schema["fields"] if field["path"] == ["args", "languages"]
    )
    assert languages["fact_construction"]["nonempty_scalar_items"] == {
        "phase": "before_dynamic_disclosure",
        "fact_action": "append",
        "repeat_for_each_item": True,
    }
    assert languages["fact_construction"]["empty_array_only"] == {
        "phase": "before_dynamic_disclosure",
        "fact_action": "present",
        "must_not_accompany": ["append"],
    }


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
def test_complex_tracer_uses_open_map_facts_and_existing_debug_dispatch(
    tmp_path: Path, version: str
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    handles = {
        field["name"]: field["handle"]
        for field in schema["fields"]
        if "parent_handle" not in field
    }
    client = FakeClient(version)
    exit_code, payload = gateway.execute_gateway(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--set", handles["id"], "string", "ak.wwise.core.getInfo",
            "--map-put", handles["args"], "sentinel", "integer", "42",
            "--map-correct", handles["args"], "sentinel", "integer", "43",
            "--map-put", handles["args"], "removed", "null", "null",
            "--map-remove", handles["args"], "removed",
        ],
        env=_env(tmp_path, version),
        client_factory=lambda _url: client,
    )
    assert exit_code == 0
    assert payload["agent_result"] == {
        "validated_api": "ak.wwise.core.getInfo",
        "supplied_sections": ["args"],
        "accepted_by_wwise": True,
    }
    assert list(payload)[-1] == "agent_result"
    assert client.calls[-1] == (
        VALIDATE_URI,
        {"id": "ak.wwise.core.getInfo", "args": {"sentinel": 43}},
        {},
    )


def test_complex_tracer_is_unavailable_before_2024_without_connection(tmp_path: Path) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2023.1"),
        client_factory=lambda _url: pytest.fail("unsupported discovery must be offline"),
    )
    assert exit_code == 2
    assert payload["ok"] is False


def test_open_map_container_handle_is_gateway_issued_and_version_bound(tmp_path: Path) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    args_handle = next(
        field["handle"] for field in schema["fields"] if field["name"] == "args"
    )

    exit_code, payload = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", args_handle,
            "--key", "nested",
            "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("handle issuance must be offline"),
    )
    assert exit_code == 0
    assert payload["handle"].startswith("trm1-")
    assert payload["continuation"]["deferred_fact"]["argv"] == [
        "--map-put", args_handle, "nested", "object", payload["handle"]
    ]

    stale_code, stale = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", args_handle,
            "--key", "nested",
            "--shape", "object",
        ],
        env=_env(tmp_path, "2024.1"),
        client_factory=lambda _url: pytest.fail("stale handle must fail offline"),
    )
    assert stale_code == 2
    assert stale["ok"] is False

    nested_code, nested = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", payload["handle"],
            "--key", "items",
            "--shape", "array",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("nested handle issuance must be offline"),
    )
    assert nested_code == 0
    assert nested["parent_handle"] == payload["handle"]
    assert nested["handle"].startswith("trm1-")


def test_complex_schema_discloses_one_complete_non_json_continuation(tmp_path: Path) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    continuation = schema["continuation"]
    dynamic = continuation["dynamic_container_commands"]
    assert dynamic["map_value"] == "request-map-container"
    assert dynamic["array_item"] == "request-array-item"
    assert dynamic["draft_binding"] is False
    assert dynamic["map_value_argv"][:5] == [
        "request-map-container",
        VALIDATE_URI,
        "--schema-digest",
        schema["schema_digest"],
        "--map-handle",
    ]
    assert dynamic["array_item_argv"][:5] == [
        "request-array-item",
        VALIDATE_URI,
        "--schema-digest",
        schema["schema_digest"],
        "--array-handle",
    ]
    assert continuation["gateway_argv_prefix"] == [
        "typed-call",
        VALIDATE_URI,
        "--schema-digest",
        schema["schema_digest"],
    ]
    assert set(continuation["fact_flags"]) == {
        "scalar", "array_item", "container", "branch", "dynamic_branch", "map_put",
        "map_correct", "map_remove",
    }
    encoded = json.dumps(schema)
    assert "args-json" not in encoded
    assert "options-json" not in encoded
    assert "action-json" not in encoded


def test_isolated_typed_call_prefix_places_io_authority_before_every_fact(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", AUDIO_CONVERT_URI],
        env=_env(tmp_path, "2024.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    continuation = schema["continuation"]
    assert continuation["gateway_argv_prefix"] == [
        "typed-call",
        AUDIO_CONVERT_URI,
        "--schema-digest",
        schema["schema_digest"],
        "--apply",
        "--io-root",
        "<absolute-allowed-root>",
    ]
    assert continuation["apply"] is True
    assert "io_root_flag" not in continuation


def test_nested_container_handles_can_be_issued_before_one_atomic_typed_call(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    handles = {
        field["name"]: field["handle"]
        for field in schema["fields"]
        if "parent_handle" not in field
    }
    _, object_handle = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", handles["args"],
            "--key", "nested", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("handle issuance must be offline"),
    )
    _, array_handle = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", object_handle["handle"],
            "--key", "items", "--shape", "array",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("handle issuance must be offline"),
    )
    client = FakeClient("2025.1")
    exit_code, _payload = gateway.execute_gateway(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--set", handles["id"], "string", "ak.wwise.core.getInfo",
            # Child facts may arrive before their parents; the Gateway validates
            # the complete signed chain atomically before opening the transport.
            "--append", array_handle["handle"], "integer", "42",
            "--map-put", object_handle["handle"], "items", "array", array_handle["handle"],
            "--map-put", handles["args"], "nested", "object", object_handle["handle"],
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: client,
    )
    assert exit_code == 0
    assert client.calls[-1] == (
        VALIDATE_URI,
        {
            "id": "ak.wwise.core.getInfo",
            "args": {"nested": {"items": [42]}},
        },
        {},
    )


def test_array_item_handle_is_gateway_issued_and_schema_bound(tmp_path: Path) -> None:
    # The public command rejects an array handle from another exact schema
    # before any transport is opened.
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", "ak.wwise.core.profiler.getVoiceContributions"],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    scalar_array = next(
        field["handle"] for field in schema["fields"] if field["name"] == "bussesPipelineID"
    )
    exit_code, payload = gateway.execute_gateway(
        [
            "request-array-item", "ak.wwise.core.profiler.getVoiceContributions",
            "--schema-digest", schema["schema_digest"],
            "--array-handle", scalar_array,
            "--index", "0",
            "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("invalid handle request must be offline"),
    )
    assert exit_code == 2
    assert payload["ok"] is False


def test_dynamic_open_array_can_issue_and_materialize_nonempty_object_item(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    handles = {field["name"]: field["handle"] for field in schema["fields"] if "parent_handle" not in field}
    _, array_payload = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", handles["args"],
            "--key", "items", "--shape", "array",
        ], env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline")
    )
    _, object_payload = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--array-handle", array_payload["handle"],
            "--index", "0", "--shape", "object",
        ], env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline")
    )
    client = FakeClient("2025.1")
    exit_code, _ = gateway.execute_gateway(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--set", handles["id"], "string", "ak.wwise.core.getInfo",
            "--map-put", object_payload["handle"], "x", "integer", "1",
            "--append", array_payload["handle"], "object", object_payload["handle"],
            "--map-put", handles["args"], "items", "array", array_payload["handle"],
        ], env=_env(tmp_path, "2025.1"), client_factory=lambda _url: client,
    )
    assert exit_code == 0
    assert client.calls[-1][1] == {
        "id": "ak.wwise.core.getInfo",
        "args": {"items": [{"x": 1}]},
    }


@pytest.mark.parametrize(
    "member_schema,member_key",
    (
        (
            {
                "type": "object",
                "additionalProperties": False,
                "patternProperties": {
                    "^x-": {"oneOf": [{"type": "integer"}, {"type": "string"}]}
                },
            },
            "x-value",
        ),
        (
            {
                "type": "object",
                "additionalProperties": {
                    "oneOf": [{"type": "integer"}, {"type": "string"}]
                },
            },
            "custom",
        ),
    ),
)
def test_gateway_discloses_opaque_choice_for_exact_dynamic_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member_schema: dict[str, Any],
    member_key: str,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=VALIDATE_URI,
        schema={
            "argsSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "rows"],
                "properties": {
                    "id": {"type": "string"},
                    "rows": {
                        "type": "array",
                        "items": member_schema,
                    },
                },
            },
            "optionsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
        graph=load_definition_graph("2025.1"),
    )
    monkeypatch.setattr(gateway, "request_contract", lambda _version, _api: contract)
    rows = next(field for field in contract.fields if field.name == "rows")

    code, initial = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", rows.handle,
            "--index", "0",
            "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0, initial
    assert initial["child_contract"]["member_key_disclosure_required"] is True
    row_handle = initial["handle"]

    disclosed_command = [
        member_key if token == "<exact-key>" else token
        for token in initial["continuation"]["branch_disclosure"]
    ]
    code, disclosed = gateway.execute_gateway(
        disclosed_command,
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0
    choices = disclosed["child_contract"]["branch_choices"][0]
    assert choices["key"] == member_key
    integer_choice = next(
        choice["handle"]
        for choice in choices["choices"]
        if choice["accepted_types"] == ["integer"]
    )
    assert integer_choice.startswith("trc1-")

    id_handle = next(field for field in contract.fields if field.name == "id").handle
    parser = gateway.build_parser()
    accepted = parser.parse_args(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--set", id_handle, "string", "ak.wwise.core.getInfo",
            "--append", rows.handle, "object", row_handle,
            "--choose-dynamic", row_handle, member_key, integer_choice,
            "--map-put", row_handle, member_key, "integer", "7",
        ]
    )
    gateway.preflight_typed_request_input(
        accepted,
        env=_env(tmp_path, "2025.1"),
    )
    assert accepted.typed_request.args == {
        "id": "ak.wwise.core.getInfo",
        "rows": [{member_key: 7}],
    }

    rejected_code, rejected = gateway.execute_gateway(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--set", id_handle, "string", "ak.wwise.core.getInfo",
            "--append", rows.handle, "object", row_handle,
            "--choose-dynamic", row_handle, member_key, "0",
            "--map-put", row_handle, member_key, "integer", "7",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("numeric choice must fail before transport"),
    )
    assert rejected_code == 2
    assert rejected["ok"] is False


def test_nested_dynamic_lineage_discloses_deep_opaque_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=VALIDATE_URI,
        schema={
            "argsSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "matrix"],
                "properties": {
                    "id": {"type": "string"},
                    "matrix": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["v"],
                                "properties": {
                                    "v": {
                                        "oneOf": [
                                            {"type": "integer"},
                                            {"type": "string"},
                                        ]
                                    }
                                },
                            },
                        },
                    },
                },
            },
            "optionsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
        graph=load_definition_graph("2025.1"),
    )
    monkeypatch.setattr(gateway, "request_contract", lambda _version, _api: contract)
    matrix = next(field for field in contract.fields if field.name == "matrix")

    code, inner = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", matrix.handle,
            "--index", "0", "--shape", "array",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    code, row = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", inner["handle"],
            "--index", "0", "--shape", "object",
            "--member-key", "v",
            "--parent-schema-token", inner["schema_lineage_token"],
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    choices = row["child_contract"]["branch_choices"][0]["choices"]
    integer_choice = next(
        choice["handle"]
        for choice in choices
        if choice["accepted_types"] == ["integer"]
    )
    assert integer_choice.startswith("trc1-")

    id_handle = next(field for field in contract.fields if field.name == "id").handle
    parsed = gateway.build_parser().parse_args(
        [
            "typed-call", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--set", id_handle, "string", "ak.wwise.core.getInfo",
            "--append", matrix.handle, "array", inner["handle"],
            "--append", inner["handle"], "object", row["handle"],
            "--choose-dynamic", row["handle"], "v", integer_choice,
            "--map-put", row["handle"], "v", "integer", "1",
        ]
    )
    gateway.preflight_typed_request_input(parsed, env=_env(tmp_path, "2025.1"))
    assert parsed.typed_request.args == {
        "id": "ak.wwise.core.getInfo",
        "matrix": [[{"v": 1}]],
    }


def test_anchored_regex_requires_exact_member_key_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=VALIDATE_URI,
        schema={
            "argsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "rows": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "patternProperties": {
                                "^x-[a-z]+$": {
                                    "oneOf": [
                                        {"type": "integer"},
                                        {"type": "string"},
                                    ]
                                }
                            },
                        },
                    }
                },
            },
            "optionsSchema": {
                "type": "object", "additionalProperties": False, "properties": {}
            },
        },
        graph=load_definition_graph("2025.1"),
    )
    monkeypatch.setattr(gateway, "request_contract", lambda _version, _api: contract)
    rows = next(field for field in contract.fields if field.name == "rows")
    code, payload = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", rows.handle,
            "--index", "0", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    assert payload["child_contract"]["branch_choices"] == []
    assert payload["child_contract"]["member_key_disclosure_required"] is True


def test_schema_lineage_token_cannot_invent_a_child_schema(
    tmp_path: Path,
) -> None:
    code, schema = gateway.execute_gateway(
        ["request-schema", VALIDATE_URI],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    args_handle = next(
        field["handle"] for field in schema["fields"] if field["name"] == "args"
    )
    code, parent = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", args_handle,
            "--key", "nested", "--shape", "object",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    token = parent["schema_lineage_token"]
    from base64 import urlsafe_b64decode, urlsafe_b64encode
    raw = token.removeprefix("trl1-")
    decoded = json.loads(
        urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    )
    decoded["steps"][0]["key"] = "invented"
    forged = "trl1-" + urlsafe_b64encode(
        json.dumps(decoded, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    rejected_code, rejected = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", parent["handle"],
            "--key", "child", "--shape", "object",
            "--parent-schema-token", forged,
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("forgery must fail offline"),
    )
    assert rejected_code == 2
    assert rejected["ok"] is False

    oversized_code, oversized = gateway.execute_gateway(
        [
            "request-map-container", VALIDATE_URI,
            "--schema-digest", schema["schema_digest"],
            "--map-handle", parent["handle"],
            "--key", "child", "--shape", "object",
            "--parent-schema-token", "trl1-" + "A" * (64 * 1024 * 2 + 1),
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("oversized token must fail offline"),
    )
    assert oversized_code == 2
    assert oversized["ok"] is False


def test_nested_options_local_reference_keeps_its_origin_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=VALIDATE_URI,
        schema={
            "argsSchema": {
                "type": "object", "additionalProperties": False, "properties": {}
            },
            "optionsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "matrix": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"$ref": "#/definitions/row"},
                        },
                    }
                },
                "definitions": {
                    "row": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "v": {
                                "oneOf": [
                                    {"type": "integer"}, {"type": "string"}
                                ]
                            }
                        },
                    }
                },
            },
        },
        graph=load_definition_graph("2025.1"),
    )
    monkeypatch.setattr(gateway, "request_contract", lambda _version, _api: contract)
    matrix = next(field for field in contract.fields if field.name == "matrix")
    assert matrix.section == "options"
    code, inner = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", matrix.handle,
            "--index", "0", "--shape", "array",
        ],
        env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    code, row = gateway.execute_gateway(
        [
            "request-array-item", VALIDATE_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", inner["handle"],
            "--index", "0", "--shape", "object", "--member-key", "v",
            "--parent-schema-token", inner["schema_lineage_token"],
        ],
        env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    assert row["child_contract"]["branch_choices"][0]["key"] == "v"
