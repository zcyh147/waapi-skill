from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.semantic.support.codex_eval_protocol_v3 import wait_topic_step
from tests.semantic.support.codex_gateway_broker import ResponseBinding
from wwise_waapi.capabilities import CapabilityCatalog
from wwise_waapi.execution_contracts import AUTHORING_UI_EXECUTION_PROFILE
from wwise_waapi.typed_topics import (
    materialize_typed_topic_inputs,
    topic_match_contract,
    topic_options_contract,
)
from wwise_waapi.typed_requests import TypedRequestFact
from wwise_waapi.typed_requests import dynamic_array_item_choices
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location("waapi_typed_topic_gateway_script", SCRIPT_PATH)
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
    return {"WAAPI_SKILL_CONFIG_PATH": str(config)}


class _Handler:
    def __init__(self) -> None:
        self.unsubscribe_calls = 0

    def unsubscribe(self) -> bool:
        self.unsubscribe_calls += 1
        return True


def _expand_compact_field_table(table: dict[str, object]) -> list[dict[str, object]]:
    columns = list(table["columns"])
    shapes = list(table["shape_codes"])
    accepted_type_sets = list(table["accepted_type_sets"])
    fact_action_definitions = list(table["fact_action_definitions"])
    constraint_sets = list(table["constraint_sets"])
    defaults = dict(table["constraint_defaults"])
    rows = list(table["rows"])
    handle_prefix = str(table.get("handle_prefix", ""))
    handles = [handle_prefix + str(row[0]) for row in rows]
    expanded_fields: list[dict[str, object]] = []
    assert columns[:5] == [
        "handle_suffix" if handle_prefix else "handle",
        "parent_row",
        "name",
        "shape_code",
        "accepted_type_set",
    ]
    assert columns[5] in {"fact_action", "fact_action_code"}
    assert columns[6] == "constraint_set"
    for handle, row in zip(handles, rows, strict=True):
        parent_row = row[1]
        shape = shapes[row[3]]
        constraints = dict(constraint_sets[row[6]])
        fact_action = row[5]
        fact_action_index = (
            int(fact_action)
            if columns[5] == "fact_action_code"
            else list(table["fact_action_codes"]).index(fact_action)
        )
        field: dict[str, object] = {
            "handle": handle,
            "section": table["section"],
            "name": row[2],
            "required": constraints.pop("required", defaults["required"]),
            "shape": shape,
            "accepted_types": accepted_type_sets[row[4]],
            "fact_construction": dict(fact_action_definitions[fact_action_index]),
            **constraints,
        }
        if parent_row is not None:
            field["parent_handle"] = handles[parent_row]
        if shape == "array":
            field.setdefault("minimum_items", None)
            field.setdefault("maximum_items", None)
            field.setdefault("unique_items", defaults["array_unique_items"])
        if shape == "map":
            field.setdefault("maximum_properties", None)
            field.setdefault("maximum_bytes", None)
            field.setdefault("maximum_key_bytes", None)
            map_payload = dict(field["map"])
            for key, value in dict(defaults["map"]).items():
                map_payload.setdefault(key, value)
            field["map"] = map_payload
        expanded_fields.append(field)
    return expanded_fields


@pytest.mark.parametrize("version", ("2021.1", "2023.1", "2024.1"))
def test_profile_soundbank_topic_rows_expose_copy_ready_handles(version: str) -> None:
    table = topic_match_contract(
        version,
        "ak.wwise.core.soundbank.generated",
    ).gateway_field_table()

    assert "handle_prefix" not in table
    assert table["columns"][0] == "handle"
    assert table["columns"][5] == "fact_action"
    assert all(str(row[0]).startswith("trh1-") for row in table["rows"])
    assert all(isinstance(row[5], str) for row in table["rows"])


@pytest.mark.parametrize(
    ("version", "field_name", "expected_action"),
    (
        (
            "2021.1",
            "platform",
            "--match-map-put(nonempty)|--match-present(empty)",
        ),
        ("2023.1", "name", "--match-set"),
        ("2024.1", "name", "--match-set"),
    ),
)
def test_compact_topic_rows_disclose_the_direct_fact_action(
    version: str,
    field_name: str,
    expected_action: str,
) -> None:
    table = topic_match_contract(
        version,
        "ak.wwise.core.soundbank.generated",
    ).gateway_field_table()
    columns = list(table["columns"])
    action_name = "fact_action" if "fact_action" in columns else "fact_action_code"
    action_index = columns.index(action_name)
    name_index = columns.index("name")
    actions = list(table["fact_action_codes"])
    rows = [row for row in table["rows"] if row[name_index] == field_name]

    assert expected_action in {
        row[action_index]
        if action_name == "fact_action"
        else actions[row[action_index]]
        for row in rows
    }


class _TopicClient:
    def __init__(self, topic: str, events: list[dict[str, object]]) -> None:
        self.topic = topic
        self.events = events
        self.options: dict[str, object] | None = None
        self.handler = _Handler()

    def call(self, uri: str, args=None, options=None):
        assert uri == "ak.wwise.core.getInfo"
        return {
            "displayName": "Wwise",
            "isCommandLine": True,
            "version": {"year": 2025, "major": 1, "minor": 7, "build": 9143},
        }

    def subscribe(self, uri: str, callback, options=None):
        assert uri == self.topic
        self.options = options
        for event in self.events:
            callback(event)
        return self.handler

    def disconnect(self) -> None:
        return None


def test_all_maximum_profile_topic_lanes_compile_exact_typed_contracts() -> None:
    catalog = CapabilityCatalog()
    lane_count = 0

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        topics = [
            row
            for row in catalog.entries_for_profile(
                version,
                profile=AUTHORING_UI_EXECUTION_PROFILE,
            )
            if row.item_type == "topic"
        ]
        for topic in topics:
            options = topic_options_contract(version, topic.uri)
            match = topic_match_contract(version, topic.uri)
            assert options.version == version
            assert match.version == version
            assert options.uri != match.uri
            assert options.schema_digest != match.schema_digest
            lane_count += 1

    assert lane_count == 154


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_all_public_topic_schema_lanes_fit_the_final_visible_ceiling(
    tmp_path: Path,
    version: str,
) -> None:
    topics = [
        row
        for row in CapabilityCatalog().entries_for_profile(
            version,
            profile=AUTHORING_UI_EXECUTION_PROFILE,
        )
        if row.item_type == "topic"
    ]

    for topic in topics:
        code, payload = gateway.execute_gateway(
            ["topic-schema", topic.uri],
            env=_env(tmp_path, version),
            client_factory=lambda url: pytest.fail(
                f"topic-schema connected to {url}"
            ),
        )

        assert code == 0, (version, topic.uri, payload)
        assert payload["topic"] == topic.uri
        assert payload["bounds"]["stdout_utf8_bytes"] == 32 * 1024
        assert gateway.gateway_json_document_size(payload) <= 32 * 1024
        encoded = gateway.gateway_stdout_json_encoder(payload).encode(payload)
        assert json.loads(encoded) == payload
        assert encoded.index('"continuation"') < 4096


def test_zero_topic_inputs_materialize_without_caller_authored_json() -> None:
    version = "2025.1"
    topic = "ak.wwise.core.audio.imported"
    options = topic_options_contract(version, topic)
    match = topic_match_contract(version, topic)

    materialized = materialize_typed_topic_inputs(
        version=version,
        topic=topic,
        options_schema_digest=options.schema_digest,
        option_facts=(),
        match_schema_digest=match.schema_digest,
        match_facts=(),
    )

    assert materialized.options == {}
    assert materialized.match == {}


def test_name_changed_options_and_nested_match_materialize_exactly() -> None:
    version = "2025.1"
    topic = "ak.wwise.core.object.nameChanged"
    options = topic_options_contract(version, topic)
    match = topic_match_contract(version, topic)
    platform = next(field for field in options.fields if field.name == "platform")
    object_field = next(field for field in match.fields if field.name == "object")
    object_id = next(
        field
        for field in match.fields
        if field.parent_handle == object_field.handle and field.name == "id"
    )
    new_name = next(field for field in match.fields if field.name == "newName")

    materialized = materialize_typed_topic_inputs(
        version=version,
        topic=topic,
        options_schema_digest=options.schema_digest,
        option_facts=(
            TypedRequestFact(
                "set",
                platform.handle,
                "string",
                "{11111111-1111-1111-1111-111111111111}",
            ),
        ),
        match_schema_digest=match.schema_digest,
        match_facts=(
            TypedRequestFact(
                "set",
                object_id.handle,
                "string",
                "{22222222-2222-2222-2222-222222222222}",
            ),
            TypedRequestFact("set", new_name.handle, "string", "UI_Click"),
        ),
    )

    assert materialized.options == {
        "platform": "{11111111-1111-1111-1111-111111111111}"
    }
    assert materialized.match == {
        "object": {"id": "{22222222-2222-2222-2222-222222222222}"},
        "newName": "UI_Click",
    }


def test_topic_schema_discloses_one_typed_continuation_offline(tmp_path: Path) -> None:
    topic = "ak.wwise.core.object.nameChanged"
    called = False

    def client_factory(url: str):
        nonlocal called
        called = True
        raise AssertionError(url)

    code, payload = gateway.execute_gateway(
        ["topic-schema", topic],
        env=_env(tmp_path, "2025.1"),
        client_factory=client_factory,
    )

    assert code == 0
    assert called is False
    assert payload["contract"] == "waapi-skill.typed-topic-input/v1"
    assert payload["topic"] == topic
    assert payload["options"]["schema_digest"]
    assert payload["event_match"]["schema_digest"]
    assert "construction_order" not in payload["options"]
    assert "top_level_fact_plan" not in payload["options"]
    assert "construction_order" not in payload["event_match"]
    assert "top_level_fact_plan" not in payload["event_match"]
    assert payload["bounds"]["stdout_utf8_bytes"] == 32 * 1024
    assert payload["continuation"]["subcommands"] == ["wait-topic", "stream-topic"]
    assert payload["continuation"]["fact_selection"] == (
        "row action; present only when empty; disclose-* rows only"
    )
    assert payload["continuation"]["fact_order"] == (
        "options ordered; match facts commute"
    )
    prefix = payload["continuation"]["wait_argv_prefix"]
    assert prefix[:6] == [
        "--timeout",
        "<positive-seconds>",
        "wait-topic",
        topic,
        "--event-count",
        "<exact-count:1..64>",
    ]
    assert prefix[6:] == [
        "--options-schema-digest",
        payload["options"]["schema_digest"],
        "--match-schema-digest",
        payload["event_match"]["schema_digest"],
    ]
    assert payload["event_match"]["continuation"]["dynamic_container_commands"] == {
        "array_item": "request-array-item",
    }
    serialized = json.dumps(payload, sort_keys=True)
    assert "options-json" not in serialized
    assert "match-json" not in serialized


def test_scalar_topic_array_does_not_advertise_container_disclosure(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.soundbank.generated"
    code, payload = gateway.execute_gateway(
        ["topic-schema", topic],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda url: pytest.fail(f"topic-schema connected to {url}"),
    )

    assert code == 0
    return_field = next(
        field
        for field in _expand_compact_field_table(payload["options"]["fields"])
        if field["name"] == "return"
    )
    assert return_field["accepted_types"] == ["string"]
    assert return_field["fact_construction"] == {
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
    assert "dynamic_container_commands" not in payload["options"]["continuation"]
    platform = next(
        field
        for field in _expand_compact_field_table(payload["event_match"]["fields"])
        if field["name"] == "platform" and field.get("parent_handle") is None
    )
    fact_tables = payload["continuation"]["fact_argv"]["top_level_fact_tables"]
    assert fact_tables["options"] == {
        "columns": [
            "business_pointer", "nonempty_fact_argv", "empty_argv",
            "object_identity_match_argv",
        ],
        "rows": [
            [
                "/options/bankData",
                ["--option-set", "trh1-1a15d3daa1ee65ce7a4d8dc9", "boolean", "<business-value>"],
                None,
                None,
            ],
            [
                "/options/infoFile",
                ["--option-set", "trh1-a420199e36fa199a064d9b1a", "boolean", "<business-value>"],
                None,
                None,
            ],
            [
                "/options/pluginInfo",
                ["--option-set", "trh1-608f352938a2e4324477c1a4", "boolean", "<business-value>"],
                None,
                None,
            ],
            [
                "/options/return",
                ["--option-append", return_field["handle"], "string", "<business-value>"],
                ["--option-present", return_field["handle"]],
                None,
            ],
        ],
    }
    assert fact_tables["match"]["columns"] == [
        "business_pointer", "nonempty_fact_argv", "empty_argv",
        "object_identity_match_argv",
    ]
    platform_row = next(
        row
        for row in fact_tables["match"]["rows"]
        if row[0] == "/args/platform"
    )
    assert platform_row == [
        "/args/platform",
        [
            "--match-map-put", platform["handle"], "<business-map-member-key>",
            "<type-of-business-map-member-value>",
            "<business-map-member-value>",
        ],
        ["--match-present", platform["handle"]],
        {
            "id": [
                "--match-map-put", platform["handle"], "id", "string",
                "<exact-guid>",
            ],
            "name": [
                "--match-map-put", platform["handle"], "name", "string",
                "<exact-name>",
            ],
        },
    ]
    encoded = gateway.gateway_stdout_json_encoder(payload).encode(payload)
    assert encoded.index(platform["handle"]) < 4096


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_wait_topic_digests_bind_to_the_real_topic_schema_envelope(
    tmp_path: Path,
    version: str,
) -> None:
    topic = "ak.wwise.core.soundbank.generated"
    code, payload = gateway.execute_gateway(
        ["topic-schema", topic],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"topic-schema connected to {url}"),
    )
    assert code == 0, payload
    step = wait_topic_step(
        "soundbank.generated.wait",
        topic,
        version=version,
        event_count=1,
        schema_step_name="soundbank.generated.schema",
    )
    options_binding = step.arguments[
        step.arguments.index("--options-schema-digest") + 1
    ]
    match_binding = step.arguments[
        step.arguments.index("--match-schema-digest") + 1
    ]

    assert options_binding == ResponseBinding(
        "soundbank.generated.schema", "/options/schema_digest"
    )
    assert match_binding == ResponseBinding(
        "soundbank.generated.schema", "/event_match/schema_digest"
    )
    assert payload["options"]["schema_digest"]
    assert payload["event_match"]["schema_digest"]
    assert payload["options"]["fields"]["section"] == "options"
    assert payload["event_match"]["fields"]["section"] == "args"
    assert payload["options"]["continuation"]["request_key"] == (
        f"topic.options:{topic}"
    )
    assert payload["event_match"]["continuation"]["request_key"] == (
        f"topic.match:{topic}"
    )
    for contract, public_key in (
        (topic_options_contract(version, topic), "options"),
        (topic_match_contract(version, topic), "event_match"),
    ):
        full_fields = contract.gateway_field_payloads()
        compact_fields = _expand_compact_field_table(payload[public_key]["fields"])
        assert len(compact_fields) == len(full_fields)
        for full, compact in zip(full_fields, compact_fields, strict=True):
            expected = dict(full)
            expected.pop("path")
            assert compact == expected
    platform = next(
        field
        for field in _expand_compact_field_table(payload["event_match"]["fields"])
        if field["name"] == "platform" and field.get("parent_handle") is None
    )
    assert platform["fact_construction"] == {
        "nonempty_scalar_members": {
            "phase": "before_dynamic_disclosure",
            "fact_action": "map-put",
            "repeat_for_each_member": True,
        },
        "empty_map_only": {
            "phase": "before_dynamic_disclosure",
            "fact_action": "present",
            "must_not_accompany": ["map-put"],
        },
    }
    assert payload["continuation"]["fact_selection"] == (
        "row action; present only when empty; disclose-* rows only"
    )
    soundbank_map = next(
        field
        for field in _expand_compact_field_table(payload["event_match"]["fields"])
        if field["name"] == "soundbank:map"
    )
    assert any(
        field["name"] == "name"
        and field.get("parent_handle") == soundbank_map["parent_handle"]
        for field in _expand_compact_field_table(payload["event_match"]["fields"])
    )
    duplicate_paths = {
        int(row): path
        for row, path in payload["event_match"]["fields"][
            "duplicate_name_paths"
        ]
    }
    assert payload["event_match"]["fields"]["path"] == (
        "omitted; use duplicate_name_paths exact row; "
        "parent map substitution forbidden"
    )
    compact_rows = payload["event_match"]["fields"]["rows"]
    top_level_name_row = next(
        index
        for index, row in enumerate(compact_rows)
        if row[2] == "name" and row[1] is not None
        and compact_rows[row[1]][2] == "soundbank"
    )
    assert duplicate_paths[top_level_name_row] == "soundbank.name"
    nested_name_rows = [
        index
        for index, row in enumerate(compact_rows)
        if row[2] == "name" and row[1] is not None
        and compact_rows[row[1]][2] == "activeSource"
    ]
    if nested_name_rows:
        assert duplicate_paths[nested_name_rows[0]] == (
            "soundbank.activeSource.name"
        )
    encoded = gateway.gateway_stdout_json_encoder(payload).encode(payload)
    assert len(encoded.encode("utf-8")) < 32 * 1024
    assert "\n" not in encoded
    assert encoded.index('"continuation"') < 4096


def test_public_nested_topic_match_handle_is_lifecycle_neutral(tmp_path: Path) -> None:
    version = "2025.1"
    topic = "ak.wwise.core.soundbank.generated"
    contract = topic_match_contract(version, topic)
    bank_info = next(field for field in contract.fields if field.name == "bankInfo")
    choice, _index, _variant = dynamic_array_item_choices(
        contract,
        array_handle=bank_info.handle,
        index=0,
        shape="object",
    )[0]

    code, payload = gateway.execute_gateway(
        [
            "request-array-item",
            f"topic.match:{topic}",
            "--schema-digest", contract.schema_digest,
            "--array-handle", bank_info.handle,
            "--index", "0",
            "--shape", "object",
            "--choice-handle", choice,
        ],
        env=_env(tmp_path, version),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert code == 0
    assert payload["continuation"]["subcommand"] == "topic-input-fact"
    assert payload["continuation"]["valid_subscription_subcommands"] == [
        "wait-topic",
        "stream-topic",
    ]
    assert payload["continuation"]["deferred_fact"]["argv"][:2] == [
        "--match-append",
        bank_info.handle,
    ]


@pytest.mark.parametrize(
    "operation_prefix",
    ["topic.options:", "topic.match:"],
)
def test_generic_request_schema_rejects_topic_pseudo_operations(
    tmp_path: Path,
    operation_prefix: str,
) -> None:
    code, payload = gateway.execute_gateway(
        [
            "request-schema",
            operation_prefix + "ak.wwise.core.object.nameChanged",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert code == 2
    assert "single schema entry" in payload["message"]
    assert "topic-schema" in payload["message"]


def test_public_wait_topic_uses_typed_options_and_match_then_unsubscribes(
    tmp_path: Path,
) -> None:
    version = "2025.1"
    topic = "ak.wwise.core.object.nameChanged"
    options = topic_options_contract(version, topic)
    match = topic_match_contract(version, topic)
    platform = next(field for field in options.fields if field.name == "platform")
    object_field = next(field for field in match.fields if field.name == "object")
    object_id = next(
        field
        for field in match.fields
        if field.parent_handle == object_field.handle and field.name == "id"
    )
    wanted = "{22222222-2222-2222-2222-222222222222}"
    client = _TopicClient(
        topic,
        [
            {"object": {"id": "{33333333-3333-3333-3333-333333333333}"}, "newName": "Skip", "oldName": "Old"},
            {"object": {"id": wanted}, "newName": "UI_Click", "oldName": "UI_Old"},
        ],
    )

    code, payload = gateway.execute_gateway(
        [
            "--timeout", "0.5", "wait-topic", topic,
            "--options-schema-digest", options.schema_digest,
            "--match-schema-digest", match.schema_digest,
            "--option-set", platform.handle, "string", "{11111111-1111-1111-1111-111111111111}",
            "--match-set", object_id.handle, "string", wanted,
        ],
        env=_env(tmp_path, version),
        client_factory=lambda url: client,
    )

    assert code == 0
    assert payload["event"]["newName"] == "UI_Click"
    assert client.options == {"platform": "{11111111-1111-1111-1111-111111111111}"}
    assert client.handler.unsubscribe_calls == 1


def test_typed_topic_rejects_stale_digest_before_connecting(tmp_path: Path) -> None:
    called = False

    def client_factory(url: str):
        nonlocal called
        called = True
        raise AssertionError(url)

    code, payload = gateway.execute_gateway(
        [
            "wait-topic", "ak.wwise.core.object.nameChanged",
            "--options-schema-digest", "stale",
            "--match-schema-digest", "stale",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=client_factory,
    )

    assert code == 2
    assert called is False
    assert "digest" in payload["message"].lower()
