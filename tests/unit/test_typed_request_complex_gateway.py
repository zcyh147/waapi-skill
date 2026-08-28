from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from wwise_waapi.schema_inventory import load_definition_graph
from wwise_waapi.operation_composer import draft_operation_request_contract
from wwise_waapi.typed_operations import TypedOperationInputError
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

AUDIO_CONVERT_URI = "ak.wwise.core.audio.convert"
MEDIA_POOL_URI = "ak.wwise.core.mediaPool.get"
SYNTHETIC_URI = "waapi-skill.synthetic.typed-request"


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
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WAAPI_SKILL_STATE_DIR": str(tmp_path / "state"),
        "WWISE_VERSION": version,
    }














def test_audio_convert_business_schema_requires_complete_language_collection(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", AUDIO_CONVERT_URI],
        env=_env(tmp_path, "2024.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )

    assert exit_code == 0, schema
    declaration = schema["business_adapter"]["declaration"]
    assert "languages" in declaration["required_fields"]
    assert declaration["field_types"]["languages"] == "language_name_list"
    assert "fields" not in schema
    assert "schema_digest" not in schema


def test_audio_convert_business_draft_keeps_exact_io_authority_in_one_plan(
    tmp_path: Path,
) -> None:
    exit_code, schema = gateway.execute_gateway(
        ["request-schema", AUDIO_CONVERT_URI],
        env=_env(tmp_path, "2024.1"),
        client_factory=lambda _url: pytest.fail("schema must be offline"),
    )
    assert exit_code == 0
    continuation = schema["continuation"]
    assert continuation["gateway_argv"] == ["draft-start", AUDIO_CONVERT_URI]
    assert continuation["copy_exactly"] is True
    assert continuation["append_arguments"] == "forbidden"
    declaration = schema["business_adapter"]["declaration"]
    assert declaration["field_types"]["io_root"] == "exact_user_io_root"
    assert "typed-call" not in str(schema)


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
        uri=SYNTHETIC_URI,
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
            "request-array-item", SYNTHETIC_URI,
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


def test_nested_dynamic_lineage_discloses_deep_opaque_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=SYNTHETIC_URI,
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
            "request-array-item", SYNTHETIC_URI,
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
            "request-array-item", SYNTHETIC_URI,
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


def test_anchored_regex_requires_exact_member_key_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=SYNTHETIC_URI,
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
            "request-array-item", SYNTHETIC_URI,
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


def test_nested_options_local_reference_keeps_its_origin_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri=SYNTHETIC_URI,
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
            "request-array-item", SYNTHETIC_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", matrix.handle,
            "--index", "0", "--shape", "array",
        ],
        env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    code, row = gateway.execute_gateway(
        [
            "request-array-item", SYNTHETIC_URI,
            "--schema-digest", contract.schema_digest,
            "--array-handle", inner["handle"],
            "--index", "0", "--shape", "object", "--member-key", "v",
            "--parent-schema-token", inner["schema_lineage_token"],
        ],
        env=_env(tmp_path, "2025.1"), client_factory=lambda _url: pytest.fail("offline"),
    )
    assert code == 0
    assert row["child_contract"]["branch_choices"][0]["key"] == "v"


def test_object_create_archive_typed_disclosure_is_not_public(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypedOperationInputError):
        draft_operation_request_contract("object.create", "2021.1")

    code, root = gateway.execute_gateway(
        [
            "--version",
            "2021.1",
            "operation-schema",
            "object.create",
        ],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0, root
    assert root["operation"]["input_mode"] == "business_declaration"
    assert "business_adapter" in root
    assert "composer" not in root
    return
    root_projected = gateway.gateway_stdout_payload(root)
    root_encoded = gateway.gateway_stdout_json_encoder(root_projected).encode(
        root_projected
    )
    assert len((root_encoded + "\n").encode("utf-8")) < 7 * 1024
    assert "session_context" not in root_projected
    assert root_projected["response_integrity"] == {
        "complete": True,
        "truncated": False,
    }
    assert root_projected["response_end"] == {
        "contract": "waapi-skill.gateway-response-end/v1",
        "marker": "WAAPI_TYPED_CONTAINER_RESPONSE_END",
        "complete": True,
        "truncated": False,
        "agent_action": "continue_same_turn",
    }
    assert list(root_projected)[-1] == "response_end"
    assert root_encoded.endswith(
        '"response_end":{"contract":"waapi-skill.gateway-response-end/v1",'
        '"marker":"WAAPI_TYPED_CONTAINER_RESPONSE_END","complete":true,'
        '"truncated":false,"agent_action":"continue_same_turn"}}'
    )
    assert root_encoded.index('"response_integrity":{') < root_encoded.index(
        '"continuation":{'
    ) < root_encoded.index('"child_contract":{')
    assert list(root_projected["continuation"])[:4] == [
        "next_command_decision",
        "root_fact_queue_anchor",
        "deferred_fact",
        "nested_container_disclosures",
    ]
    assert root_projected["continuation"]["root_fact_queue_anchor"] == root[
        "continuation"
    ]["root_fact_queue_anchor"]
    assert "request_wide_order" not in root_projected["continuation"]
    assert root_projected["continuation"]["next_command_decision"][
        "evaluate_in_order"
    ][0]["candidate"] == "deferred_fact_queue"
    child_array_argv = next(
        row["argv"]
        for row in root["continuation"]["nested_container_disclosures"]
        if row["key"] == "children"
    )
    code, child_array = gateway.execute_gateway(
        ["--version", "2021.1", *child_array_argv],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0, child_array
    child_array_projected = gateway.gateway_stdout_payload(child_array)
    assert "root_fact_queue_anchor" not in child_array_projected["continuation"]
    assert child_array_projected["continuation"]["next_command_decision"][
        "evaluate_in_order"
    ][0]["command_key"] == "deferred_fact"
    assert child_array_projected["continuation"]["deferred_fact"][
        "complete_command_assembly"
    ] == {
        "fixed_argv_prefix_source": (
            "latest_draft_response.next_action_binding.fixed_argv_prefix"
        ),
        "append_this_fact_argv_exactly": True,
    }
    leaf_argv = [
        "0" if token == "<zero_based_business_present_index>" else token
        for token in child_array["continuation"]["next_item_disclosure"][
            "argv_by_shape"
        ]["object"]
    ]
    code, leaf = gateway.execute_gateway(
        ["--version", "2021.1", *leaf_argv],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0, leaf

    projected = gateway.gateway_stdout_payload(leaf)
    encoded = gateway.gateway_stdout_json_encoder(projected).encode(projected)
    assert len((encoded + "\n").encode("utf-8")) < 4 * 1024
    assert projected["handle"] == leaf["handle"]
    assert projected["schema_lineage_token"] == leaf["schema_lineage_token"]
    assert projected["response_integrity"] == root_projected["response_integrity"]
    assert projected["response_end"] == root_projected["response_end"]
    assert list(projected)[-1] == "response_end"
    assert encoded.index('"response_integrity":{') < encoded.index(
        '"continuation":{'
    ) < encoded.index('"child_contract":{')
    projected_scalar_table = projected["child_contract"][
        "fixed_scalar_member_fact_table"
    ]
    assert projected_scalar_table["columns"] == [
        "key",
        "required",
        "accepted_types",
    ]
    raw_scalar_table = leaf["child_contract"][
        "fixed_scalar_member_fact_table"
    ]
    business_pointers = [row[3] for row in raw_scalar_table["rows"]]
    assert len({pointer.rsplit("/", 1)[0] for pointer in business_pointers}) == 1
    assert projected_scalar_table["business_object_pointer"] == (
        business_pointers[0].rsplit("/", 1)[0]
    )
    assert projected_scalar_table["rows"] == [
        row[:3] for row in raw_scalar_table["rows"]
    ]
    assert projected_scalar_table["exact_type_tokens"] == {
        "Actor Mixer": "ActorMixer",
        "Random Container": "RandomSequenceContainer",
        "随机容器": "RandomSequenceContainer",
        "Blend Container": "BlendContainer",
        "混合容器": "BlendContainer",
        "Sound": "Sound",
        "forbidden": ["RandomContainer"],
    }
    assert projected_scalar_table["row_policy"] == (
        "all_present_rows_in_order_skip_absent_optional"
    )
    assert projected_scalar_table["fact_command_assembly"] == {
        "fixed_argv_prefix": [
            "--action",
            "add_typed_fact",
            "--fact-action",
            "map-put",
            "--field-handle",
            leaf["handle"],
        ],
        "append_for_each_business_present_row": [
            "--value-type",
            "<selected-accepted-type>",
            "--fact-value",
            "<business-value>",
            "--key",
            "<row-key>",
        ],
    }
    fact_prefix = projected_scalar_table["fact_command_assembly"][
        "fixed_argv_prefix"
    ]
    for projected_row, raw_row in zip(
        projected_scalar_table["rows"], raw_scalar_table["rows"], strict=True
    ):
        key, _required, accepted_types = projected_row
        assert len(accepted_types) == 1
        assert [
            *fact_prefix,
            "--value-type",
            accepted_types[0],
            "--fact-value",
            "<business-value>",
            "--key",
            key,
        ] == raw_row[4][accepted_types[0]]
    assert "shared_policy" not in projected_scalar_table
    raw_nested_rows = leaf["continuation"]["nested_container_disclosures"]
    nested_table = projected["continuation"]["nested_container_disclosures"]
    nested_business_pointers = [
        row["business_value_pointer"] for row in raw_nested_rows
    ]
    assert len(
        {pointer.rsplit("/", 1)[0] for pointer in nested_business_pointers}
    ) == 1
    assert nested_table["business_object_pointer"] == (
        nested_business_pointers[0].rsplit("/", 1)[0]
    )
    assert nested_table["selection"] == (
        "first_row_with_present_business_value_pointer_in_queue_order"
    )
    assert nested_table["absent_business_values"] == (
        "skip_without_gateway_command"
    )
    assert nested_table["allowed_members"] == [
        row["key"] for row in raw_nested_rows
    ]
    assert nested_table["shape"] == "array"
    assert nested_table["replace_only"] == ["<selected-business-member>"]
    for raw_row in raw_nested_rows:
        assert [
            raw_row["key"]
            if token == "<selected-business-member>"
            else token
            for token in nested_table["argv_template"]
        ] == raw_row["argv"]
    assert projected["continuation"]["next_command_decision"][
        "evaluate_in_order"
    ][0]["command_key"] == "deferred_fact"
    assert "root_fact_queue_anchor" not in projected["continuation"]
    assert projected["continuation"]["next_command_decision"][
        "evaluate_in_order"
    ][0]["candidate"] == "deferred_fact_queue"
    nested_candidate = next(
        row
        for row in projected["continuation"]["next_command_decision"][
            "evaluate_in_order"
        ]
        if row["candidate"] == "nested_container_disclosures"
    )
    assert nested_candidate["command_key"] == "nested_container_disclosures"
    assert list(projected["continuation"])[:5] == [
        "next_command_decision",
        "deferred_fact",
        "nested_container_disclosures",
        "business_sibling_transition",
        "subcommand",
    ]
    assert "--no-dynamic-descendants" not in encoded

    sibling = leaf["continuation"]["business_sibling_transition"]
    sibling_argv = sibling["argv_by_shape"]["object"]
    assert sibling["copy_command_by_shape"]["object"] == (
        gateway.operation_draft_copy_command(
            [
                "python",
                str(gateway.GATEWAY_RUNNER_PATH),
                "gateway.py",
                *sibling_argv,
            ]
        )
    )
    last_leaf_argv = [
        "1" if token == "<zero_based_business_present_index>" else token
        for token in child_array["continuation"]["next_item_disclosure"][
            "argv_by_shape"
        ]["object"]
    ]
    code, last_leaf = gateway.execute_gateway(
        ["--version", "2021.1", *last_leaf_argv],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )
    assert code == 0, last_leaf
    last_projected = gateway.gateway_stdout_payload(last_leaf)
    last_decision = last_projected["continuation"]["next_command_decision"]
    assert last_decision["evaluate_in_order"][0]["command_key"] == (
        "deferred_fact"
    )
    assert "root_fact_queue_anchor" not in last_projected["continuation"]
    assert last_projected["continuation"]["business_sibling_transition"][
        "when_absent"
    ] == "nearest_ancestor_business_sibling"
    last_encoded = gateway.gateway_stdout_json_encoder(last_projected).encode(
        last_projected
    )
    assert '"root_fact_queue_anchor":{' not in last_encoded


def _archive_test_dynamic_container_schema_exposes_one_standard_argv_per_shape(
    tmp_path: Path,
) -> None:
    contract = draft_operation_request_contract("object.create", "2021.1")
    children = next(
        field
        for field in contract.fields
        if field.path == ("children",) and field.shape == "array"
    )

    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2021.1",
            "request-array-item",
            "object.create",
            "--schema-digest",
            contract.schema_digest,
            "--array-handle",
            children.handle,
            "--index",
            "0",
            "--shape",
            "object",
        ],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("disclosure must be offline"),
    )

    assert code == 0, payload
    encoded = gateway.gateway_stdout_json_encoder(payload).encode(payload)
    assert "no_dynamic_descendants" not in encoded
    assert "--no-dynamic-descendants" not in encoded
