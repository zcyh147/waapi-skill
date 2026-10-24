"""Reject malformed native runtime results at the public Gateway boundary."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient

VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
PREFIX = "ak.wwise.core.profiler."
GUID = "{11111111-1111-1111-1111-111111111111}"
LABEL = 'MIDI: Note On (C#4), Channel 1 / 界'


def task(tmp_path, version, operation, result):
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    calls = []
    def call(uri, args=None, options=None):
        calls.append((uri, deepcopy(args), deepcopy(options)))
        if operation.endswith("getVoiceContributions") and uri == PREFIX + "getVoices":
            return {"return": [{"pipelineID": 42, "gameObjectID": 1, "objectGUID": GUID,
                                 "objectName": LABEL, "gameObjectName": LABEL}]}
        return deepcopy(result) if uri == operation else original(uri, args, options)
    client.call = call
    env = _env(tmp_path, version=version)
    state = tmp_path / "state"
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(state), *argv], env=env,
            client_factory=lambda _url: client)
    return run, state, calls


def assert_rejected(code, payload, state):
    assert code == 2, payload
    assert payload["ok"] is False
    assert "agent_result" not in payload
    assert not list((state / "runtime-inspection-observations-v1").glob("**/*.json"))


def profiler_row(operation, version):
    row = {"gameObjectID": -(1 << 63) if version in ("2024.1", "2025.1") else 0,
           "gameObjectName": LABEL}
    if operation == "getAudioObjects":
        row.update(busPipelineID=42, busGUID=GUID, busID=17, audioObjectID=(1 << 64) - 1,
            audioObjectName=LABEL, metadata=[{"metadataClassID": 0, "sourceShortID": 0, "sourceName": LABEL}])
    else:
        row.update(pipelineID=42, objectGUID=GUID, objectName=LABEL)
        row.update({"priority": -128, "playingID": (1 << 32) - 1} if operation == "getVoices"
                   else {"voiceCount": (1 << 32) - 1, "mixBusID": (1 << 64) - 1})
    return row


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation,field,bad", [
    ("getVoices", "objectGUID", 7), ("getVoices", "priority", 128),
    ("getBusses", "voiceCount", -1), ("getAudioObjects", "busGUID", "bad"),
    ("getAudioObjects", "metadata", [{"metadataClassID": 0, "sourceShortID": -1}]),
])
def test_profiler_rejects_malformed_off_page_rows_before_retaining_handles(tmp_path, version, operation, field, bad):
    row = profiler_row(operation, version)
    invalid = {**deepcopy(row), field: bad}
    invalid["busPipelineID" if operation == "getAudioObjects" else "pipelineID"] = 43
    run, state, _calls = task(tmp_path, version, PREFIX + operation, {"return": [invalid, row]})
    code, payload = run("core-call", PREFIX + operation, "--profiler-position", "123", "--max-results", "1")
    assert_rejected(code, payload, state)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ["getVoices", "getBusses", "getAudioObjects"])
def test_profiler_preserves_native_labels_optional_fields_and_versioned_ids(tmp_path, version, operation):
    row = profiler_row(operation, version)
    run, _state, _calls = task(tmp_path, version, PREFIX + operation, {"return": [row]})
    code, payload = run("core-call", PREFIX + operation, "--profiler-position", "123")
    assert code == 0, payload
    observed = payload["agent_result"]["return"][0]
    assert all(observed[key] == value for key, value in row.items() if key not in ("pipelineID", "busPipelineID"))
    assert observed["bus_instance_handle" if operation != "getVoices" else "voice_instance_handle"].startswith("rph1-")


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("bad", [False, True], ids=["valid", "invalid-off-page"])
def test_performance_counter_validates_local_result_references(tmp_path, version, bad):
    rows = [{"id": "cpu", "name": LABEL, "value": 1.25}, {"id": "memory", "name": "Memory", "value": 2048.0}]
    if bad:
        rows[0]["value"] = "bad"
    run, state, _calls = task(tmp_path, version, PREFIX + "getPerformanceMonitor", {"return": rows})
    code, payload = run("core-call", PREFIX + "getPerformanceMonitor", "--profiler-position", "123", "--max-results", "1")
    if bad:
        assert_rejected(code, payload, state)
    else:
        assert code == 0, payload
        assert payload["agent_result"]["return"] == [rows[1]]


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize("bad_field,bad_value", [(None, None), ("id", 7), ("classId", -1)])
def test_default_meter_object_projection_validates_off_page_identity(tmp_path, version, bad_field, bad_value):
    row = {"object": {"id": GUID, "name": LABEL, "classId": 553}, "source": "Bus",
           "configurationName": "Stereo", "configurationMask": 3, "configurationType": "Standard",
           "channels": [{"name": "L", "value": -12.0}]}
    other = deepcopy(row)
    if bad_field:
        other["object"][bad_field] = bad_value
    run, state, _calls = task(tmp_path, version, PREFIX + "getMeters", {"meters": [other, row]})
    code, payload = run("core-call", PREFIX + "getMeters", "--profiler-position", "123", "--max-results", "1")
    if bad_field:
        assert_rejected(code, payload, state)
    else:
        assert code == 0, payload
        assert payload["agent_result"]["meters"] == [row]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("bad_field,bad_value", [(None, None), ("severity", "Invalid"), ("platform", {"id": 7})])
def test_log_validates_whole_entries_and_nested_platforms_before_retention(tmp_path, version, bad_field, bad_value):
    operation = "ak.wwise.core.log.get"
    row = {"severity": "Message", "time": 123, "messageId": "test", "message": LABEL,
           "platform": {"id": GUID, "name": LABEL}}
    other = deepcopy(row)
    if bad_field:
        other[bad_field] = bad_value
    run, state, _calls = task(tmp_path, version, operation, {"items": [other, row]})
    code, payload = run("core-call", operation, "--log-channel", "general", "--max-results", "1")
    if bad_field:
        assert_rejected(code, payload, state)
    else:
        assert code == 0, payload
        assert payload["agent_result"]["items"] == [row]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("driver_value", [False, 1.5, GUID])
def test_contribution_tree_validates_recursive_driver_values_with_real_input_handles(tmp_path, version, driver_value):
    operation = PREFIX + "getVoiceContributions"
    tree = [{"name": LABEL, "children": [{"name": LABEL, "parameters": [
        {"driver": "Distance from listener (no object)", "driverValue": driver_value, "value": -3.0},
        {"driver": GUID, "driverValue": GUID}]}]}]
    result = {"return": {"volume": -3.0, "LPF": 2.0, "HPF": 1.0, "objects": tree}}
    if version == "2025.1":
        result["return"]["DSF"] = 0.0
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    def call(uri, args=None, options=None):
        if uri == operation:
            return deepcopy(result)
        if uri == PREFIX + "getVoices":
            return {"return": [{"pipelineID": 42, "gameObjectID": 1, "objectGUID": GUID,
                                 "objectName": LABEL, "gameObjectName": LABEL}]}
        return original(uri, args, options)
    client.call = call
    env = _env(tmp_path, version=version)
    state = tmp_path / "state"
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(state), *argv], env=env, client_factory=lambda _url: client)
    code, observed = run("core-call", PREFIX + "getVoices", "--profiler-position", "123")
    assert code == 0, observed
    handle = observed["agent_result"]["return"][0]["voice_instance_handle"]
    code, payload = run("profiler-voice-contributions", "--capture-ms", "123", "--voice-instance-handle", handle)
    if driver_value is False:
        assert code == 2, payload
        assert "agent_result" not in payload
    else:
        assert code == 0, payload
        assert payload["agent_result"]["objects"] == tree
        if version in ("2021.1", "2022.1", "2023.1"):
            rules = payload["schema_validation"]["result"]["compatibility_rules"]
            assert [rule["rule_id"] for rule in rules] == ["profiler-contribution-driver-reason-or-guid/v1"]


_NATIVE_CASES = json.loads((Path(__file__).parents[1] /
    "fixtures/runtime/referenced-runtime-native-results.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _NATIVE_CASES, ids=lambda case: case["version"] + "-" + case["operation"].split(".")[-1])
def test_retained_native_runtime_results_remain_compatible_at_public_gateway(tmp_path, case):
    version, operation = case["version"], case["operation"]
    run, _state, _calls = task(tmp_path, version, operation, case["result"])
    if operation.endswith("getVoiceContributions"):
        code, payload = run("profiler-voice-contributions", "--capture-ms", "123", "--voice-object-id", GUID)
    else:
        code, payload = run("core-call", operation, "--profiler-position", "123", "--max-results", "1000")
    assert code == 0, payload


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize("game_object_id", [-1, -(1 << 63)])
def test_signed_game_object_voice_and_bus_handles_continue_to_contributions(tmp_path, version, game_object_id):
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    calls = []
    def call(uri, args=None, options=None):
        calls.append(uri)
        if uri in {PREFIX + "getVoices", PREFIX + "getBusses"}:
            return {"return": [{"pipelineID": 42 if uri.endswith("getVoices") else 43,
                "gameObjectID": game_object_id, "objectGUID": GUID, "objectName": LABEL,
                "gameObjectName": LABEL}]}
        if uri == PREFIX + "getVoiceContributions":
            return {"return": {"volume": -3.0, "LPF": 2.0, "HPF": 1.0, "objects": [],
                **({"DSF": 0.0} if version == "2025.1" else {})}}
        return original(uri, args, options)
    client.call = call
    env = _env(tmp_path, version=version)
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), *argv], env=env,
            client_factory=lambda _url: client)
    handles = []
    for operation, field in [("getVoices", "voice_instance_handle"), ("getBusses", "bus_instance_handle")]:
        code, payload = run("core-call", PREFIX + operation, "--profiler-position", "123")
        assert code == 0, payload
        handles.append(payload["agent_result"]["return"][0][field])
    code, payload = run("profiler-voice-contributions", "--capture-ms", "123",
        "--voice-instance-handle", handles[0], "--bus-instance-handle", handles[1])
    assert code == 0, payload
    assert payload["agent_result"]["volume"] == -3.0
    assert calls[-1] == PREFIX + "getVoiceContributions"


@pytest.mark.parametrize("version,invalid", [
    *((version, value) for version in VERSIONS for value in (False, -(1 << 63) - 1, 1 << 64)),
    *((version, -1) for version in VERSIONS[:3]),
])
def test_contribution_handle_revalidation_rejects_invalid_versioned_game_object_ids(tmp_path, version, invalid):
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    game_object_id = 1
    calls = []
    def call(uri, args=None, options=None):
        calls.append(uri)
        if uri == PREFIX + "getVoices":
            return {"return": [{"pipelineID": 42, "gameObjectID": game_object_id, "objectGUID": GUID,
                                 "objectName": LABEL, "gameObjectName": LABEL}]}
        return original(uri, args, options)
    client.call = call
    env = _env(tmp_path, version=version)
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), *argv], env=env,
            client_factory=lambda _url: client)
    code, observed = run("core-call", PREFIX + "getVoices", "--profiler-position", "123")
    assert code == 0, observed
    handle = observed["agent_result"]["return"][0]["voice_instance_handle"]
    game_object_id = invalid
    code, payload = run("profiler-voice-contributions", "--capture-ms", "123", "--voice-instance-handle", handle)
    assert code == 2, payload
    assert payload["error_code"] == "INVALID_STABLE_READ_RESULT"
    assert "agent_result" not in payload
    assert PREFIX + "getVoiceContributions" not in calls
