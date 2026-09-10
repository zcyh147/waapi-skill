from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from wwise_waapi.capabilities import CapabilityCatalog
from wwise_waapi.execution_contracts import AUTHORING_UI_EXECUTION_PROFILE
from wwise_waapi.typed_topics import (
    materialize_typed_topic_inputs,
    topic_match_contract,
    topic_options_contract,
)
from wwise_waapi.typed_requests import TypedRequestFact
from wwise_waapi.typed_requests import dynamic_array_item_choices
from wwise_waapi.topic_business import (
    TopicBusinessEntryObjectFact,
    materialize_topic_business_inputs,
    resolve_topic_business_value_choice,
    topic_business_contract,
    topic_business_value_choices,
)
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


def _contract_binding(topic: str, version: str = "2025.1") -> list[str]:
    return [
        "--topic-contract-digest",
        topic_business_contract(version, topic).contract_digest,
    ]


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


def _business_field_names(table: dict[str, object]) -> set[str]:
    field_column = list(table["columns"]).index("field")
    return {str(row[field_column]) for row in table["rows"]}


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




def test_public_nested_topic_handle_disclosure_is_removed(tmp_path: Path) -> None:
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

    assert code == 2
    assert "business topic-schema" in payload["message"].lower()


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
    assert "handle-free business topic-schema" in payload["message"]


def test_public_wait_topic_uses_business_options_and_match_then_unsubscribes(
    tmp_path: Path,
) -> None:
    version = "2025.1"
    topic = "ak.wwise.core.object.nameChanged"
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
            *_contract_binding(topic, version),
            "--topic-option", "platform", "{11111111-1111-1111-1111-111111111111}",
            "--event-match", "object-id", wanted,
        ],
        env=_env(tmp_path, version),
        client_factory=lambda url: client,
    )

    assert code == 0
    assert payload["event"]["newName"] == "UI_Click"
    assert client.options == {"platform": "{11111111-1111-1111-1111-111111111111}"}
    assert client.handler.unsubscribe_calls == 1


def test_topic_schema_leads_with_handle_free_business_input(tmp_path: Path) -> None:
    topic = "ak.wwise.core.object.created"

    code, payload = gateway.execute_gateway(
        ["topic-schema", topic, "--match-group", "object"],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"topic-schema connected to {url}"),
    )

    assert code == 0
    business = payload["business_input"]
    assert business["contract"] == "waapi-skill.topic-business/v1"
    assert business["topic"] == topic
    assert _business_field_names(business["options"]) >= {
        "platform",
        "include",
    }
    assert _business_field_names(business["event_match"]) >= {
        "object-name",
        "object-type",
    }
    serialized = json.dumps(business, sort_keys=True)
    assert "trh1-" not in serialized
    assert "schema_digest" not in serialized
    assert "wire_type" not in serialized
    assert "accepted_value_kinds" not in serialized
    assert "value_kind_sets" not in serialized
    assert payload["continuation"]["default_input"] == "business"
    digest = business["contract_digest"]
    assert payload["continuation"]["contract_binding"] == {
        "flag": "--topic-contract-digest",
        "value": digest,
        "copy_exactly": True,
    }
    assert payload["continuation"]["wait_argv_prefix"][-2:] == [
        "--topic-contract-digest",
        digest,
    ]
    assert payload["continuation"]["business_fact_argv"] == {
        "topic_option": "--topic-option <field> <value>",
        "empty_topic_option": "--topic-option-empty <field>",
        "typed_topic_option": "--topic-option-as <field> <value-choice-handle> <value>",
        "event_match": "--event-match <field> <value>",
        "empty_event_field": "--event-empty <field>",
        "typed_event_match": "--event-match-as <field> <value-choice-handle> <value>",
        "event_row": "--event-row <collection> <comma-separated-indices> <field> <value>",
        "typed_event_row": "--event-row-as <collection> <comma-separated-indices> <field> <value-choice-handle> <value>",
        "empty_event_row": "--event-row-empty <collection> <comma-separated-parent-indices-or-dash>",
        "exact_entry": "--event-entry <scope> <indices-or-dash> <exact-key> <value>",
        "typed_exact_entry": "--event-entry-as <scope> <indices-or-dash> <exact-key> <value-choice-handle> <value>",
        "empty_exact_entry": "--event-entry-empty <scope> <indices-or-dash> <exact-key> <object|list>",
        "exact_entry_object": "--event-entry-object <scope> <indices-or-dash> <exact-key> <field> <value>",
        "typed_exact_entry_object": "--event-entry-object-as <scope> <indices-or-dash> <exact-key> <field> <value-choice-handle> <value>",
        "exact_entry_row": "--event-entry-row <scope> <indices-or-dash> <exact-key> <item-index> <field> <value>",
        "typed_exact_entry_row": "--event-entry-row-as <scope> <indices-or-dash> <exact-key> <item-index> <field> <value-choice-handle> <value>",
    }
    assert payload["continuation"]["value_choice_policy"] == {
        "choice_on_disclosure": {
            "disclose_first": True,
            "field_disclosure_source": "business_input",
            "untyped_fact_forms_allowed": False,
            "typed_fact_suffix": "-as",
            "value_choice_handle": "copy_exactly_from_disclosure",
        }
    }


def test_soundbank_topic_schema_exposes_closed_business_shortcuts(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.soundbank.generated"

    code, payload = gateway.execute_gateway(
        ["topic-schema", topic],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"topic-schema connected to {url}"),
    )

    assert code == 0
    assert payload["continuation"]["business_shortcuts"] == {
        "include_object_identity": "--include-object-identity",
        "match_platform_name": "--match-platform-name <exact-name>",
        "match_soundbank_name": "--match-soundbank-name <exact-name>",
    }
    encoded = gateway.gateway_stdout_json_encoder(payload).encode(payload)
    assert len(encoded.encode("utf-8")) <= 8 * 1024
    assert payload["business_input"]["event_rows"]["rows"] == []
    assert payload["business_input"]["event_rows"]["catalog_count"] > 0
    assert payload["business_input"]["exact_entries"]["rows"] == []
    assert payload["business_input"]["exact_entries"]["catalog_count"] > 0
    assert payload["continuation"]["advanced_field_catalog"] == (
        "topic-schema <topic-uri> --catalog"
    )


def test_soundbank_topic_schema_discloses_long_tail_catalog_only_on_request(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        ["topic-schema", "ak.wwise.core.soundbank.generated", "--catalog"],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"topic-schema connected to {url}"),
    )

    assert code == 0, payload
    business = payload["business_input"]
    assert len(business["event_rows"]["rows"]) == business["event_rows"][
        "catalog_count"
    ]
    assert len(business["exact_entries"]["rows"]) == business["exact_entries"][
        "catalog_count"
    ]


def test_soundbank_topic_business_shortcuts_compile_without_handles(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.soundbank.generated"
    contract = topic_business_contract("2025.1", topic)
    client = _TopicClient(
        topic,
        [
            {
                "soundbank": {
                    "id": "{22222222-2222-2222-2222-222222222222}",
                    "name": "Main",
                    "type": "SoundBank",
                    "path": r"\SoundBanks\Main",
                },
                "platform": {"name": "Windows"},
            }
        ],
    )

    code, payload = gateway.execute_gateway(
        [
            "--timeout",
            "0.5",
            "wait-topic",
            topic,
            "--event-count",
            "1",
            "--topic-contract-digest",
            contract.contract_digest,
            "--include-object-identity",
            "--match-platform-name",
            "Windows",
            "--match-soundbank-name",
            "Main",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )

    assert code == 0, payload.get("message", payload)
    assert payload["event"]["soundbank"] == {
        "id": "{22222222-2222-2222-2222-222222222222}",
        "name": "Main",
        "type": "SoundBank",
        "path": r"\SoundBanks\Main",
    }
    assert payload["event"]["platform"]["name"] == "Windows"


def test_soundbank_topic_business_shortcuts_reject_other_topics_before_connecting(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.object.created"
    contract = topic_business_contract("2025.1", topic)

    code, payload = gateway.execute_gateway(
        [
            "wait-topic",
            topic,
            "--event-count",
            "1",
            "--topic-contract-digest",
            contract.contract_digest,
            "--include-object-identity",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"invalid shortcut connected to {url}"),
    )

    assert code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "soundbank.generated" in payload["message"]


def test_ambiguous_topic_scalar_uses_a_digest_bound_value_choice_handle(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.soundbank.generated"
    schema_code, schema = gateway.execute_gateway(
        ["topic-schema", topic, "--entry", "platform"],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"topic-schema connected to {url}"),
    )

    assert schema_code == 0
    selected = schema["business_input"]["exact_entries"]["selected"]
    assert selected["scope"] == "platform"
    assert selected["scalar_value_mode"] == "choice_required"
    choices = {
        meaning: handle
        for handle, meaning in selected["value_choices"]["rows"]
    }
    assert set(choices) == {
        "literal_text",
        "whole_number",
        "decimal_number",
        "on_or_off",
        "explicit_empty",
    }
    assert all(handle.startswith("tvc1-") for handle in choices.values())
    client = _TopicClient(
        topic,
        [
            {
                "soundbank": {
                    "id": "{22222222-2222-2222-2222-222222222222}",
                    "name": "Main",
                    "type": "SoundBank",
                    "path": r"\SoundBanks\Main",
                },
                "platform": {"name": "Windows"},
            }
        ],
    )

    code, payload = gateway.execute_gateway(
        [
            "--timeout",
            "0.5",
            "wait-topic",
            topic,
            "--event-count",
            "1",
            "--topic-contract-digest",
            schema["business_input"]["contract_digest"],
            "--event-entry-as",
            "platform",
            "-",
            "name",
            choices["literal_text"],
            "Windows",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )

    assert code == 0, payload.get("message", payload)
    assert payload["event"]["platform"]["name"] == "Windows"
    assert client.handler.unsubscribe_calls == 1


def test_open_exact_entry_member_uses_one_scope_bound_value_choice(
    tmp_path: Path,
) -> None:
    version = "2021.1"
    topic = "ak.wwise.core.audio.imported"
    scope = "objects-audio-source-language"
    schema_code, schema = gateway.execute_gateway(
        ["--version", version, "topic-schema", topic, "--entry", scope],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"topic-schema connected to {url}"),
    )

    assert schema_code == 0
    open_member = schema["business_input"]["exact_entries"]["selected"][
        "object_fields"
    ]["open_member"]
    assert open_member["field_ownership"] == "exact_user_key"
    choices = {
        meaning: handle
        for handle, meaning in open_member["value_choices"]["rows"]
    }
    assert set(choices) == {
        "literal_text",
        "whole_number",
        "decimal_number",
        "on_or_off",
        "explicit_empty",
    }

    contract = topic_business_contract(version, topic)
    kind = resolve_topic_business_value_choice(
        contract,
        channel="event-entry-object",
        owner=(scope, "customLanguageTag"),
        handle=choices["literal_text"],
    )
    compiled = materialize_topic_business_inputs(
        version=version,
        topic=topic,
        option_facts=(),
        match_facts=(),
        entry_object_facts=(
            TopicBusinessEntryObjectFact(
                scope=scope,
                indices=(0,),
                key="metadata",
                field="customLanguageTag",
                value="Gameplay",
                kind=kind,
            ),
        ),
    )

    assert compiled.match["objects"][0]["audioSourceLanguage"] == {
        "metadata": {"customLanguageTag": "Gameplay"}
    }


def test_raw_topic_scalar_kind_is_rejected_before_connecting(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.soundbank.generated"
    connected = False

    def client_factory(url: str) -> _TopicClient:
        nonlocal connected
        connected = True
        raise AssertionError(url)

    code, payload = gateway.execute_gateway(
        [
            "wait-topic",
            topic,
            "--event-count",
            "1",
            *_contract_binding(topic),
            "--event-entry-as",
            "platform",
            "-",
            "name",
            "text",
            "Windows",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=client_factory,
    )

    assert code == 2
    assert "value-choice" in payload["message"]
    assert connected is False


def test_wait_topic_requires_contract_digest_before_connection(tmp_path: Path) -> None:
    topic = "ak.wwise.core.object.created"

    code, payload = gateway.execute_gateway(
        ["wait-topic", topic],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"wait-topic connected to {url}"),
    )

    assert code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "topic-schema" in payload["message"]


def test_wait_topic_rejects_stale_contract_digest_before_connection(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.object.created"

    code, payload = gateway.execute_gateway(
        ["wait-topic", topic, "--topic-contract-digest", "0" * 64],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"wait-topic connected to {url}"),
    )

    assert code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "stale" in payload["message"].lower()


def test_largest_progressive_topic_row_disclosure_stays_bounded(tmp_path: Path) -> None:
    code, payload = gateway.execute_gateway(
        [
            "topic-schema",
            "ak.wwise.core.object.structureChanged",
            "--row",
            "objects",
            "--row-field-group",
            "object-playback-duration",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"topic-schema connected to {url}"),
    )

    assert code == 0, payload
    encoded = gateway.gateway_stdout_json_encoder(payload).encode(payload)
    assert len(encoded.encode("utf-8")) <= 32 * 1024
    assert "trh1-" not in encoded
    selected = payload["business_input"]["event_rows"]["selected"]
    assert selected["collection"] == "objects"
    assert selected["fields"]["rows"]


def test_public_wait_topic_compiles_business_event_rows(tmp_path: Path) -> None:
    topic = "ak.wwise.core.audio.imported"
    contract = topic_business_contract("2025.1", topic)
    volume_choice = next(
        choice.handle
        for choice in topic_business_value_choices(
            contract,
            channel="event-entry",
            owner=("objects",),
        )
        if choice.meaning == "decimal_number"
    )
    client = _TopicClient(
        topic,
        [
            {
                "files": ["/tmp/Footstep_Run.wav"],
                "objects": [
                    {"name": "Footstep_Run", "type": "Sound", "@Volume": -4}
                ],
                "operation": "CreateNewObject",
            }
        ],
    )

    code, payload = gateway.execute_gateway(
        [
            "--timeout",
            "0.5",
            "wait-topic",
            topic,
            *_contract_binding(topic),
            "--event-row",
            "objects",
            "0",
            "name",
            "Footstep_Run",
            "--event-row",
            "objects",
            "0",
            "type",
            "Sound",
            "--event-entry-as",
            "objects",
            "0",
            "@Volume",
            volume_choice,
            "-4",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )

    assert code == 0, payload
    assert payload["event"]["objects"][0]["name"] == "Footstep_Run"
    assert client.handler.unsubscribe_calls == 1


def test_public_wait_topic_defaults_to_business_input_without_schema_digests(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.object.created"
    wanted = "Footstep_Run"
    client = _TopicClient(
        topic,
        [
            {"object": {"name": "Skip", "type": "Sound"}},
            {"object": {"name": wanted, "type": "Sound"}},
        ],
    )

    code, payload = gateway.execute_gateway(
        [
            "--timeout",
            "0.5",
            "wait-topic",
            topic,
            *_contract_binding(topic),
            "--topic-option",
            "include",
            "name",
            "--event-match",
            "object-name",
            wanted,
            "--event-match",
            "object-type",
            "Sound",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )

    assert code == 0, payload
    assert payload["event"]["object"]["name"] == wanted
    assert client.options == {"return": ["name"]}
    assert client.handler.unsubscribe_calls == 1


@pytest.mark.parametrize(
    "removed_flag",
    ["--options-schema-digest", "--match-set", "--legacy-typed"],
)
def test_model_authored_topic_handles_and_fragments_are_not_in_the_parser(
    removed_flag: str,
) -> None:
    argv = ["wait-topic", "ak.wwise.core.object.nameChanged", removed_flag, "x"]
    if removed_flag == "--legacy-typed":
        argv = ["topic-schema", "ak.wwise.core.object.nameChanged", removed_flag]

    with pytest.raises(SystemExit) as exc_info:
        gateway.build_parser().parse_args(argv)

    assert exc_info.value.code == 2
