"""Public monitoring behavior against independently selected reflected facts."""

from __future__ import annotations

from copy import deepcopy
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
    def __init__(self, version, events, *, pinned_build=None, is_command_line=True):
        self.version = version
        self.pinned_build = pinned_build
        self.is_command_line = is_command_line
        self.calls = []
        self.subscriptions = []
        self.callbacks = []
        self.argv = []
        self.events = events
        self.unsubscribed = 0
        self.options = None
        self.disconnected = False

    def call(self, uri, args=None, options=None):
        assert uri == "ak.wwise.core.getInfo"
        parts = [int(part) for part in self.pinned_build.split(".")] if self.pinned_build else [int(self.version[:4]), 1, 0, 1]
        result = {"displayName": "Wwise", "isCommandLine": self.is_command_line,
                  "version": dict(zip(("year", "major", "minor", "build"), parts))}
        self.calls.append({"uri": uri, "args": deepcopy(args), "options": deepcopy(options), "result": deepcopy(result)})
        return result

    def subscribe(self, uri, callback, options=None):
        self.options = deepcopy(options)
        self.subscriptions.append({"uri": uri, "options": deepcopy(options)})
        for event in self.events:
            self.callbacks.append({"uri": uri, "options": deepcopy(options), "event": deepcopy(event)})
            callback(event)
        return self

    def unsubscribe(self):
        self.unsubscribed += 1
        return True

    def disconnect(self):
        self.disconnected = True


def run(tmp_path, version, mode, topic, events, *facts, timeout_seconds=0.03, event_count=1, pinned_build=None, is_command_line=True):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"wwise_version": version, "waapi_host": "127.0.0.1",
                                 "waapi_port": 31337, "project_modification_policy": "read_only"}))
    client = Client(version, events, pinned_build=pinned_build, is_command_line=is_command_line)
    records = []
    client.argv = ["--timeout", str(timeout_seconds), mode, topic,
                   "--topic-contract-digest", topic_business_contract(version, topic).contract_digest,
                   *(["--event-count", str(event_count)] if mode == "stream-topic" else []), *facts]
    code, payload = gateway.execute_gateway(
        client.argv,
        env={"WAAPI_SKILL_CONFIG_PATH": str(config)},
        client_factory=lambda _url: client, stream_sink=lambda record: records.append(deepcopy(record)),
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


@pytest.mark.parametrize("version", VERSIONS)
def test_created_fixed_scalar_packets_preserve_ordered_public_stream(tmp_path, request, version):
    """Injected/schema-valid packets; native co-occurrence is deliberately unproved."""
    import os
    from tests.support.created_topic_cases import URI, BUILDS, created_packets, created_fields
    from tests.support.created_topic_branch_evidence import validate_packets, stream_observation
    packets = created_packets(version)
    validate_packets(version, packets)  # Independent pinned reflection, not the compiler.
    observed = {}
    context_path = os.environ.get("WAAPI_CREATED_TOPIC_BRANCH_CAPTURE_CONTEXT")
    if context_path:
        from tests.support.created_topic_branch_evidence import load_capture, finish_capture
        from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
        capture = load_capture(Path(context_path), request.node.nodeid, version)
        register_exact_evidence_finalizer(request.node, lambda reports: finish_capture(capture, reports, observed))
    facts = [token for field in created_fields(version) for token in ("--topic-option", "include", field)]
    code, terminal, client, records = run(tmp_path, version, "stream-topic", URI, packets, *facts,
        timeout_seconds=1.0, event_count=4, pinned_build=BUILDS[version])
    observed.update(stream_observation(code, terminal, client, records))
    assert code == 0, terminal
    assert "agent_result" not in terminal
    assert client.subscriptions == [{"uri": URI, "options": {"return": created_fields(version)}}]
    assert [record["record_type"] for record in records] == ["started", "event", "event", "event", "event"]
    assert [record["event"] for record in records[1:]] == packets
    assert [record["sequence"] for record in records[1:]] == [1, 2, 3, 4]
    assert all(record["event_validation"]["unresolved_refs"] == [] for record in records[1:])
    assert terminal["status"] == "completed"
    assert terminal["event_count"] == 4 and terminal["event_count_reached"] is True
    assert terminal["monitoring_outcome"]["target_completed"] is True
    assert terminal["cleanup"] == "unsubscribed" and client.unsubscribed == 1 and client.disconnected


def test_created_stream_sink_freezes_received_records_before_later_mutation(tmp_path, monkeypatch):
    """Run the public flow, then mutate the raw records retained by its consumer."""
    from tests.support.created_topic_cases import URI, BUILDS, created_packets, created_fields
    original_execute = gateway.execute_gateway
    received, before_mutation = [], []

    def execute_with_mutating_consumer(*args, **kwargs):
        sink = kwargs['stream_sink']

        def observe(record):
            received.append(record)
            before_mutation.append(deepcopy(record))
            sink(record)

        kwargs['stream_sink'] = observe
        result = original_execute(*args, **kwargs)
        # Gateway completed normally. A consumer retaining the original object
        # must not be able to rewrite the independently recorded sink snapshot.
        for record in received:
            if record['record_type'] == 'event':
                record['event']['object']['notes'] = 'changed after receipt'
        return result

    monkeypatch.setattr(gateway, 'execute_gateway', execute_with_mutating_consumer)
    packets = created_packets('2025.1')
    expected_packets = deepcopy(packets)
    facts = [token for field in created_fields('2025.1') for token in ('--topic-option', 'include', field)]
    code, terminal, client, records = run(tmp_path, '2025.1', 'stream-topic', URI, packets, *facts,
        timeout_seconds=1.0, event_count=4, pinned_build=BUILDS['2025.1'])
    assert code == 0 and terminal['cleanup'] == 'unsubscribed'
    assert terminal['monitoring_outcome']['target_completed'] is True
    assert client.unsubscribed == 1 and client.disconnected
    assert len(received) == 5 and received != before_mutation
    assert records == before_mutation
    assert [record['event'] for record in records[1:]] == expected_packets
    assert [callback['event'] for callback in client.callbacks] == expected_packets


@pytest.mark.parametrize('mode', ('wait-topic', 'stream-topic'))
@pytest.mark.parametrize('is_command_line', (True, False), ids=('console', 'authoring-structural'))
def test_structure_notes_rows_match_the_observed_old_notes_fields(tmp_path, mode, is_command_line):
    topic = 'ak.wwise.core.object.structureChanged'
    # Literal shape observed by the clean 796f16ca Console diagnostic.
    event = {'summary': 'Edit Notes', 'objects': [{'object': {'id': GUID},
        'changes': [{'type': 'notesChange', 'notesChange': {
            'oldNotes': 'topic-notes-before', 'newNotes': 'topic-notes-after'}}]}]}
    other = deepcopy(event)
    other['objects'][0]['changes'][0]['notesChange']['oldNotes'] = 'unrelated'
    code, terminal, client, records = run(tmp_path, '2025.1', mode, topic, [other, event],
        '--event-row', 'objects-changes', '0,0', 'notes-change-old-notes', 'topic-notes-before',
        '--event-row', 'objects-changes', '0,0', 'notes-change-new-notes', 'topic-notes-after',
        timeout_seconds=1.0, pinned_build='2025.1.7.9143', is_command_line=is_command_line)
    assert code == 0, terminal
    assert terminal['match'] == {'objects': [{'changes': [{'notesChange': {
        'oldNotes': 'topic-notes-before', 'newNotes': 'topic-notes-after'}}]}]}
    if mode == 'stream-topic':
        assert [row['event'] for row in records if row['record_type'] == 'event'] == [event]
        validation = records[1]['event_validation']
    else:
        assert terminal['event'] == event
        validation = terminal['event_validation']
    rule, = validation['compatibility_rules']
    assert rule['fields'] == ['oldNotes', 'newNotes']
    assert rule['host'] == ('wwise-console' if is_command_line else 'wwise-authoring')
    assert rule['native_delivery_credit'] is False
    assert terminal['monitoring_outcome']['target_completed'] is True
    assert client.unsubscribed == 1 and client.disconnected


@pytest.mark.parametrize('field,value', [('oldNotes', 1), ('newNotes', False)])
@pytest.mark.parametrize('is_command_line', (True, False), ids=('console', 'authoring-structural'))
def test_structure_notes_string_validation_precedes_filtering(tmp_path, field, value, is_command_line):
    event = {'summary': 'Edit Notes', 'objects': [{'object': {'id': GUID},
        'changes': [{'type': 'notesChange', 'notesChange': {'oldNotes': 'unrelated', 'newNotes': 'after', field: value}}]}]}
    code, result, client, records = run(tmp_path, '2025.1', 'stream-topic',
        'ak.wwise.core.object.structureChanged', [event],
        '--event-row', 'objects-changes', '0,0', 'notes-change-old-notes', 'before',
        timeout_seconds=1.0, is_command_line=is_command_line)
    assert code != 0 and result['error_code'] == 'TOPIC_EVENT_SCHEMA_MISMATCH', result
    assert not any(row.get('record_type') == 'event' for row in records)
    assert result['cleanup'] == 'unsubscribed' and client.unsubscribed == 1 and client.disconnected


@pytest.mark.parametrize('version', VERSIONS[:-1])
def test_classic_notes_changed_predicates_remain_unchanged(tmp_path, version):
    event = {'object': {'id': GUID}, 'oldNotes': 'before', 'newNotes': 'after'}
    code, result, client, _ = run(tmp_path, version, 'wait-topic', 'ak.wwise.core.object.notesChanged', [event],
        '--event-match', 'old-notes', 'before', '--event-match', 'new-notes', 'after', timeout_seconds=1.0)
    assert code == 0 and result['event'] == event, result
    assert result['match'] == {'oldNotes': 'before', 'newNotes': 'after'}
    assert 'compatibility_rules' not in result['event_validation']
    assert client.unsubscribed == 1 and client.disconnected
