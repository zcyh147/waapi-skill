"""Public monitoring behavior against independently selected reflected facts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from wwise_waapi.topic_business import topic_business_contract, topic_business_value_choices


SCRIPT = Path(__file__).resolve().parents[2] / "skills/waapi-skill/scripts/gateway.py"
SPEC = importlib.util.spec_from_file_location("topic_monitoring_gateway", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)
GUID = "{11111111-1111-1111-1111-111111111111}"
VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")


class Client:
    def __init__(self, version, events):
        self.version = version
        self.events = events
        self.unsubscribed = 0
        self.options = None
        self.disconnected = False

    def call(self, uri, args=None, options=None):
        assert uri == "ak.wwise.core.getInfo"
        return {"displayName": "Wwise", "isCommandLine": True,
                "version": {"year": int(self.version[:4]), "major": 1, "minor": 0, "build": 1}}

    def subscribe(self, uri, callback, options=None):
        self.options = options
        for event in self.events:
            callback(event)
        return self

    def unsubscribe(self):
        self.unsubscribed += 1
        return True

    def disconnect(self):
        self.disconnected = True


def run(tmp_path, version, mode, topic, events, *facts, timeout_seconds=0.03):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"wwise_version": version, "waapi_host": "127.0.0.1",
                                 "waapi_port": 31337, "project_modification_policy": "read_only"}))
    client = Client(version, events)
    records = []
    code, payload = gateway.execute_gateway(
        ["--timeout", str(timeout_seconds), mode, topic,
         "--topic-contract-digest", topic_business_contract(version, topic).contract_digest,
         *(["--event-count", "1"] if mode == "stream-topic" else []), *facts],
        env={"WAAPI_SKILL_CONFIG_PATH": str(config)},
        client_factory=lambda _url: client, stream_sink=records.append,
    )
    return code, payload, client, records


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("mode", ("wait-topic", "stream-topic"))
def test_monitor_rejects_out_of_range_referenced_transport_id_and_cleans_up(tmp_path, version, mode):
    # Schema/matching and cleanup control, not a 30ms scheduler benchmark.
    code, result, client, records = run(
        tmp_path, version, mode, "ak.wwise.core.transport.stateChanged",
        [{"transport": -1, "state": "playing", "object": GUID}],
        "--topic-option", "transport", "1",
        timeout_seconds=1.0,
    )
    assert code != 0, result
    assert client.unsubscribed == 1
    assert client.disconnected
    assert not any(record.get("record_type") == "event" for record in records)


@pytest.mark.parametrize("mode", ("wait-topic", "stream-topic"))
def test_nonmatching_malformed_event_cannot_hide_behind_filter(tmp_path, mode):
    code, result, client, records = run(
        tmp_path, "2025.1", mode, "ak.wwise.core.transport.stateChanged",
        [{"transport": -1, "state": "playing", "object": GUID}],
        "--topic-option", "transport", "1", "--event-match", "state", "paused",
    )
    assert code != 0, result
    assert result["cleanup"] == "unsubscribed"
    failure = result.get("call", result)
    assert failure["error_code"] not in {"TIMEOUT", "SubscriptionTimeout"}
    assert client.unsubscribed == 1


def test_wait_does_not_silently_drop_a_burst_before_counting(tmp_path):
    code, result, client, _ = run(
        tmp_path, "2025.1", "wait-topic", "ak.wwise.core.transport.stateChanged",
        [{"transport": 1, "state": "playing", "object": GUID}] * 65,
        "--topic-option", "transport", "1",
    )
    assert code != 0, result
    assert result["call"]["error_code"] == "SUBSCRIPTION_STREAM_OVERFLOW"
    assert result["cleanup"] == "unsubscribed"
    assert client.unsubscribed == 1


@pytest.mark.parametrize("mode", ("wait-topic", "stream-topic"))
def test_numeric_match_does_not_count_boolean_property_event(tmp_path, mode):
    topic = "ak.wwise.core.object.propertyChanged"
    choice = next(item.handle for item in topic_business_value_choices(
        topic_business_contract("2025.1", topic), channel="event-match", owner=("new",),
    ) if item.meaning == "decimal_number")
    base = {"object": {"id": GUID}, "property": "Volume", "old": None, "platform": GUID}
    code, result, client, records = run(
        tmp_path, "2025.1", mode, topic, [{**base, "new": True}, {**base, "new": 1}],
        "--topic-option", "object", GUID, "--topic-option", "property", "Volume",
        "--event-match-as", "new", choice, "1",
    )
    assert code == 0, result
    event = result["event"] if mode == "wait-topic" else records[1]["event"]
    assert type(event["new"]) is int
    assert client.unsubscribed == 1


def test_stream_duration_with_partial_count_reports_stopped(tmp_path):
    code, result, client, _ = run(
        tmp_path, "2025.1", "stream-topic", "ak.wwise.core.transport.stateChanged",
        [{"transport": 1, "state": "playing", "object": GUID}],
        "--event-count", "2", "--topic-option", "transport", "1",
    )
    assert code == 0, result
    assert result["status"] == "stopped"
    assert result["completion_reason"] == "duration_elapsed"
    assert result["monitoring_outcome"] == {
        "subscription_established": True, "requested_event_count": 2,
        "event_count": 1, "target_completed": False, "termination": "duration_elapsed",
    }
    assert client.unsubscribed == 1


def test_wait_partial_timeout_preserves_matching_count(tmp_path):
    code, result, client, _ = run(
        tmp_path, "2025.1", "wait-topic", "ak.wwise.core.transport.stateChanged",
        [{"transport": 1, "state": "playing", "object": GUID}],
        "--event-count", "2", "--topic-option", "transport", "1",
    )
    assert code != 0
    assert result["monitoring_outcome"] == {
        "subscription_established": True, "requested_event_count": 2,
        "event_count": 1, "target_completed": False, "termination": "timeout",
    }
    assert result["cleanup"] == "unsubscribed"
    assert client.unsubscribed == 1


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("value", (None, "native text", -1.5, True))
def test_monitor_accepts_all_native_property_value_alternatives(tmp_path, version, value):
    event = {"object": {"id": GUID, "Children": [{"id": GUID, "name": "Child"}]},
             "property": "Volume", "old": None, "new": value, "platform": GUID}
    # Schema/matching and cleanup control, not a 30ms scheduler benchmark.
    code, result, client, _ = run(
        tmp_path, version, "wait-topic", "ak.wwise.core.object.propertyChanged", [event],
        "--topic-option", "object", GUID, "--topic-option", "property", "Volume",
        timeout_seconds=1.0,
    )
    assert code == 0, result
    assert result["event"] == event
    assert result["event_validation"]["unresolved_refs"] == []
    assert result["monitoring_outcome"]["target_completed"] is True
    assert client.options == {"object": GUID, "property": "Volume"}
    assert client.unsubscribed == 1


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("severity", ("Message", "Fatal Error"))
def test_nested_log_definitions_preserve_native_required_and_enum_fields(tmp_path, version, severity):
    event = {"channel": "general", "item": {"severity": severity, "time": 0,
             "messageId": "test", "message": "Test", "platform": {"id": GUID}, "parameters": []}}
    # This checks reflected enum/required fields, not a 30ms scheduler deadline.
    code, result, client, _ = run(tmp_path, version, "wait-topic", "ak.wwise.core.log.itemAdded", [event], timeout_seconds=1.0)
    assert code == 0, result
    assert result["event"] == event
    assert result["event_validation"]["unresolved_refs"] == []
    assert client.unsubscribed == 1


def test_2021_soundbank_implicit_rows_are_reachable_business_matches(tmp_path):
    event = {"soundbank": {"id": GUID}, "platform": {"id": GUID},
             "bankInfo": [{"GameParameters": [{"Name": "Intensity", "GUID": GUID}]}]}
    code, result, client, _ = run(
        tmp_path, "2021.1", "wait-topic", "ak.wwise.core.soundbank.generated", [event],
        "--event-row", "bank-info-game-parameters", "0,0", "name", "Intensity",
    )
    assert code == 0, result
    assert result["event"] == event
    assert result["match"] == {"bankInfo": [{"GameParameters": [{"Name": "Intensity"}]}]}
    assert client.unsubscribed == 1


@pytest.mark.parametrize("collection,children,native_field,field,value", [
    ("excluded-memory-files", ("ExcludedMemoryFiles",), "ShortName", "short-name", "Media"),
    ("included-aux-busses", ("IncludedAuxBusses",), "Name", "name", "Aux"),
    ("included-memory-files", ("IncludedMemoryFiles",), "ShortName", "short-name", "Media"),
    ("referenced-streamed-files", ("ReferencedStreamedFiles",), "ShortName", "short-name", "Stream"),
    ("state-groups", ("StateGroups",), "Name", "name", "StateGroup"),
    ("state-groups-states", ("StateGroups", "States"), "Name", "name", "State"),
    ("switch-groups", ("SwitchGroups",), "Name", "name", "SwitchGroup"),
    ("switch-groups-switches", ("SwitchGroups", "Switches"), "Name", "name", "Switch"),
    ("triggers", ("Triggers",), "Name", "name", "Trigger"),
    ("included-events-included-memory-files", ("IncludedEvents", "IncludedMemoryFiles"), "ShortName", "short-name", "Media"),
    ("included-events-switch-containers", ("IncludedEvents", "SwitchContainers"), "SwitchValue", "switch-value", GUID),
    ("included-events-switch-containers-media", ("IncludedEvents", "SwitchContainers", "Media"), "Id", "id", "17"),
])
def test_2021_implicit_collection_descendants_remain_matchable(tmp_path, collection, children, native_field, field, value):
    expected = {native_field: value}
    for child in reversed(children):
        expected = {child: [expected]}
    event = {"bankInfo": [expected]}
    # Schema/matching and cleanup control, not a 30ms scheduler benchmark.
    code, result, _, _ = run(
        tmp_path, "2021.1", "wait-topic", "ak.wwise.core.soundbank.generated", [event],
        "--event-row", f"bank-info-{collection}", ",".join(["0"] * (1 + len(children))), field, value,
        timeout_seconds=1.0,
    )
    assert code == 0, result
    assert result["event"] == event
    assert result["match"] == event


@pytest.mark.parametrize("mode", ("wait-topic", "stream-topic"))
def test_native_shape_mismatch_retains_small_exact_event_for_diagnosis(tmp_path, mode):
    event = {"transport": -1, "state": "playing", "object": GUID}
    code, result, client, _ = run(
        tmp_path, "2025.1", mode, "ak.wwise.core.transport.stateChanged", [event],
        "--topic-option", "transport", "1",
    )
    failure = result.get("call", result)
    assert code != 0
    assert failure["error_code"] == "TOPIC_EVENT_SCHEMA_MISMATCH"
    diagnostic = failure["details"]["event_diagnostic"]
    assert diagnostic["complete"] is True
    assert json.loads(diagnostic["json"]) == event
    assert client.unsubscribed == 1


def test_stream_count_reached_with_failed_cleanup_is_not_completed(tmp_path, monkeypatch):
    def failed_unsubscribe(self):
        self.unsubscribed += 1
        return False
    monkeypatch.setattr(Client, "unsubscribe", failed_unsubscribe)
    code, result, client, _ = run(
        tmp_path, "2025.1", "stream-topic", "ak.wwise.core.transport.stateChanged",
        [{"transport": 1, "state": "playing", "object": GUID}],
        "--topic-option", "transport", "1",
    )
    assert code != 0
    assert result["event_count_reached"] is True
    assert result["monitoring_outcome"]["target_completed"] is False
    assert result["monitoring_outcome"]["termination"] == "error"
    assert result["error_code"] == "SUBSCRIPTION_CLEANUP_FAILED"


@pytest.mark.parametrize("version", VERSIONS)
def test_independent_native_topic_catalog_has_a_public_business_route(tmp_path, version):
    from wwise_waapi.capabilities import CapabilityCatalog
    from wwise_waapi.execution_contracts import AUTHORING_UI_EXECUTION_PROFILE

    root = SCRIPT.parents[1] / "resources/native-catalog" / version
    native = set()
    for host in ("wwise-console", "wwise-authoring"):
        native.update(json.loads((root / f"{host}.json").read_text())["topics"])
    public = {entry.uri for entry in CapabilityCatalog().entries_for_profile(
        version, profile=AUTHORING_UI_EXECUTION_PROFILE,
    ) if entry.item_type == "topic"}
    assert public == native
    for topic in native:
        code, payload = gateway.execute_gateway(
            ["--version", version, "topic-schema", topic],
            env={"WAAPI_SKILL_CONFIG_PATH": str(tmp_path / "absent.json")},
            client_factory=lambda _url: pytest.fail("offline schema connected"),
        )
        assert code == 0, payload
        assert payload["continuation"]["subcommands"] == ["wait-topic", "stream-topic"]


def test_unknown_event_definition_is_rejected_before_subscription(tmp_path, monkeypatch):
    original = Path.read_text
    schema_path = SCRIPT.parents[1] / "resources/manifest/2025.1/schemas.json"
    def corrupted_schema(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        if path == schema_path:
            payload = json.loads(text)
            topic = next(row for row in payload["schemas"] if row["uri"] == "ak.wwise.core.transport.stateChanged")
            topic["schema"]["publishSchema"]["properties"]["transport"] = {"$ref": "missing.json#/definitions/id"}
            return json.dumps(payload)
        return text
    monkeypatch.setattr(Path, "read_text", corrupted_schema)
    code, payload = gateway.execute_gateway(
        ["--version", "2025.1", "topic-schema", "ak.wwise.core.transport.stateChanged"],
        env={"WAAPI_SKILL_CONFIG_PATH": str(tmp_path / "absent.json")},
        client_factory=lambda _url: pytest.fail("unknown definition connected"),
    )
    assert code != 0
    assert "Unpackaged same-version definition document" in payload["message"]


def test_native_subscription_setup_exception_does_not_claim_unsubscribe(tmp_path, monkeypatch):
    def failed_subscribe(self, uri, callback, options=None):
        raise RuntimeError("native subscription setup failed")
    monkeypatch.setattr(Client, "subscribe", failed_subscribe)
    code, result, client, _ = run(
        tmp_path, "2025.1", "wait-topic", "ak.wwise.core.transport.stateChanged", [],
        "--topic-option", "transport", "1",
    )
    assert code != 0
    assert result["cleanup"] == "unknown"
    assert result["monitoring_outcome"]["subscription_established"] is None
    assert client.unsubscribed == 0
