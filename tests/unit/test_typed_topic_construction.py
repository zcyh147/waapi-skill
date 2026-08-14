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
    constraint_sets = list(table["constraint_sets"])
    defaults = dict(table["constraint_defaults"])
    rows = list(table["rows"])
    handles = [str(table["handle_prefix"]) + str(row[0]) for row in rows]
    expanded_fields: list[dict[str, object]] = []
    assert columns == [
        "handle_suffix",
        "parent_row",
        "name",
        "shape_code",
        "accepted_type_set",
        "constraint_set",
    ]
    for handle, row in zip(handles, rows, strict=True):
        parent_row = row[1]
        shape = shapes[row[3]]
        constraints = dict(constraint_sets[row[5]])
        field: dict[str, object] = {
            "handle": handle,
            "section": table["section"],
            "name": row[2],
            "required": constraints.pop("required", defaults["required"]),
            "shape": shape,
            "accepted_types": accepted_type_sets[row[4]],
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
    assert payload["bounds"]["stdout_utf8_bytes"] == 32 * 1024
    assert payload["continuation"]["subcommands"] == ["wait-topic", "stream-topic"]
    prefix = payload["continuation"]["wait_argv_prefix"]
    assert prefix[:6] == [
        "--timeout",
        "<positive-seconds>",
        "wait-topic",
        topic,
        "--event-count",
        "<1..64>",
    ]
    assert prefix[6:] == [
        "--options-schema-digest",
        payload["options"]["schema_digest"],
        "--match-schema-digest",
        payload["event_match"]["schema_digest"],
    ]
    assert payload["event_match"]["continuation"]["dynamic_container_commands"] == {
        "map_value": "request-map-container",
        "array_item": "request-array-item",
    }
    serialized = json.dumps(payload, sort_keys=True)
    assert "options-json" not in serialized
    assert "match-json" not in serialized


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
    assert payload["continuation"]["fact"][:2] == [
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
