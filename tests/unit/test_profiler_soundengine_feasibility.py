from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.profiler_capability import (  # pyright: ignore[reportMissingImports]
    ProfilerCapabilitySchemaError,
    REQUIRED_EVIDENCE_ROW_FIELDS,
    validate_profiler_capability_resource,
    validate_profiler_evidence_row,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK3_RESOURCE_PATH = (
    REPO_ROOT
    / "resources"
    / "coverage"
    / "2022.1"
    / "task-3-profiler-capability.json"
)
TASK5_RESOURCE_PATH = (
    REPO_ROOT
    / "resources"
    / "coverage"
    / "2022.1"
    / "task-5-profiler-soundengine-evidence.json"
)
EVIDENCE_ROOT = ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/"
TASK5_EVIDENCE_PATHS = {
    ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/task-5-soundengine-profiler.md",
    ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/task-5-no-overclaim.md",
}
PROFILER_BOUNDARY_URIS = {
    "ak.wwise.core.profiler.startCapture",
    "ak.wwise.core.profiler.stopCapture",
}
TRANSPORT_URIS = {
    "ak.wwise.core.transport.create",
    "ak.wwise.core.transport.getList",
    "ak.wwise.core.transport.getState",
    "ak.wwise.core.transport.executeAction",
    "ak.wwise.core.transport.destroy",
    "ak.wwise.core.transport.stateChanged",
}
TASK3_SOUNDENGINE_SMOKE_URIS = {
    "ak.soundengine.postMsgMonitor",
    "ak.soundengine.registerGameObj",
    "ak.soundengine.unregisterGameObj",
}
ALL_SOUNDENGINE_URIS = {
    "ak.soundengine.executeActionOnEvent",
    "ak.soundengine.getState",
    "ak.soundengine.getSwitch",
    "ak.soundengine.postEvent",
    "ak.soundengine.postMsgMonitor",
    "ak.soundengine.postTrigger",
    "ak.soundengine.registerGameObj",
    "ak.soundengine.resetRTPCValue",
    "ak.soundengine.seekOnEvent",
    "ak.soundengine.setDefaultListeners",
    "ak.soundengine.setGameObjectAuxSendValues",
    "ak.soundengine.setGameObjectOutputBusVolume",
    "ak.soundengine.setListenerSpatialization",
    "ak.soundengine.setListeners",
    "ak.soundengine.setMultiplePositions",
    "ak.soundengine.setObjectObstructionAndOcclusion",
    "ak.soundengine.setPosition",
    "ak.soundengine.setRTPCValue",
    "ak.soundengine.setScalingFactor",
    "ak.soundengine.setState",
    "ak.soundengine.setSwitch",
    "ak.soundengine.stopAll",
    "ak.soundengine.stopPlayingID",
    "ak.soundengine.unregisterGameObj",
}
INSUFFICIENT_PROOF_PHRASES = (
    "accepted call is not proof",
    "accepted calls would be insufficient",
    "context only",
    "empty return/no exception would be insufficient",
    "no exception would be insufficient",
)


def test_task_3_plan_covers_profiler_transport_and_soundengine_candidates() -> None:
    resource = _task3_resource()
    profiler_transport_uris = _covered_uris(resource["profiler_transport_cases"])
    soundengine_uris = _covered_uris(resource["soundengine_cases"])

    assert PROFILER_BOUNDARY_URIS <= profiler_transport_uris | soundengine_uris
    assert TRANSPORT_URIS <= profiler_transport_uris
    assert TASK3_SOUNDENGINE_SMOKE_URIS <= soundengine_uris
    assert any(uri.startswith("ak.soundengine.") for uri in soundengine_uris)


def test_task_3_capability_resource_matches_schema_and_does_not_promote() -> None:
    resource = _task3_resource()

    validate_profiler_capability_resource(resource)
    assert resource["metadata"]["promotes_coverage"] is False
    for case in _task3_cases():
        assert case["status"] in {"capability-observed", "capability-blocked", "prerequisite-blocked"}
        assert case["status"] not in {"profiler-backed-tested", "soundengine-backed-tested"}
        assert case["evidence_path"].startswith(EVIDENCE_ROOT)
        for row in case["evidence_rows"]:
            assert REQUIRED_EVIDENCE_ROW_FIELDS <= set(row), case["id"]
            validate_profiler_evidence_row(row)


def test_task_3_blocked_live_outcomes_are_not_observed_or_placeholder_payloads() -> None:
    for case in _task3_cases():
        assert case["status"] == "capability-blocked", case["id"]
        for row in case["evidence_rows"]:
            assert row["observed_payload_fields"] == [], row["api_uri"]
            blocker = row["missing_payload_blocker"].lower()
            assert "live probe replaces this" not in blocker, row["api_uri"]
            assert "payload" in blocker or "statechanged" in blocker or "getstate transition" in blocker, row["api_uri"]


def test_task_3_observed_status_rejects_placeholder_or_missing_payload_blockers() -> None:
    observed_resource = json.loads(json.dumps(_task3_resource()))
    case = observed_resource["soundengine_cases"][0]
    case["status"] = "capability-observed"
    case["evidence_rows"][0]["observed_payload_fields"] = ["description"]
    case["evidence_rows"][0]["missing_payload_blocker"] = "live probe replaces this with the exact missing payload/topic blocker"

    with pytest.raises(ProfilerCapabilitySchemaError, match="placeholder text"):
        validate_profiler_capability_resource(observed_resource)

    case["evidence_rows"][0]["missing_payload_blocker"] = "no matching profiler topic payload within 5.0s; seen=[]"
    with pytest.raises(ProfilerCapabilitySchemaError, match="cannot carry a missing-payload blocker"):
        validate_profiler_capability_resource(observed_resource)


def test_task_3_cases_use_capture_action_bounded_observation_stop_capture_cleanup() -> None:
    for case in _task3_cases():
        sequence = "\n".join(case["capture_sequence"]).lower()
        assert "start" in sequence and "capture" in sequence, case["id"]
        assert "bounded" in sequence, case["id"]
        assert "stop" in sequence and "capture" in sequence, case["id"]
        trigger = case["trigger"]
        assert trigger["bounded_wait_seconds"] > 0, case["id"]
        assert trigger["predicate"], case["id"]
        cleanup_text = "\n".join(case["cleanup"]).lower()
        assert "stop capture" in cleanup_text, case["id"]
        assert "disconnect waapi" in cleanup_text, case["id"]
        assert "shutdown wwiseconsole" in cleanup_text, case["id"]


def test_task_3_profiler_evidence_rows_require_per_uri_payload_or_exact_blocker() -> None:
    valid = dict(_task3_case("soundengine_cases", "soundengine_monitor_message_capture_log_capability_probe")["evidence_rows"][0])

    missing_payload = dict(valid)
    missing_payload["observed_payload_fields"] = []
    missing_payload["missing_payload_blocker"] = ""
    with pytest.raises(ProfilerCapabilitySchemaError, match="observed payload fields or an exact missing-payload blocker"):
        validate_profiler_evidence_row(missing_payload)

    vague_blocker = dict(valid)
    vague_blocker["observed_payload_fields"] = []
    vague_blocker["missing_payload_blocker"] = "call returned without exception"
    with pytest.raises(ProfilerCapabilitySchemaError, match="missing payload/topic prerequisite"):
        validate_profiler_evidence_row(vague_blocker)

    no_cleanup = dict(valid)
    no_cleanup["cleanup_proof"] = {"capture_stopped": False, "subscriptions_cleared": True}
    with pytest.raises(ProfilerCapabilitySchemaError, match="capture cleanup"):
        validate_profiler_evidence_row(no_cleanup)


def test_task_3_transport_case_asserts_state_transitions_not_just_ids() -> None:
    case = _task3_case("profiler_transport_cases", "profiler_transport_state_capability_probe")
    assertions = "\n".join(case["assertions"]).lower()
    trigger = json.dumps(case["trigger"]).lower()

    assert "getstate" in assertions
    assert "state transition" in assertions
    assert "getlist contains" in assertions
    assert "destroy" in assertions
    assert "returned ids alone" not in assertions
    assert "statechanged" in trigger or "state transition" in trigger


def test_task_3_soundengine_cases_require_profiler_or_topic_side_effects() -> None:
    for case in _task3_resource()["soundengine_cases"]:
        assertions = "\n".join(case["assertions"]).lower()
        trigger = json.dumps(case["trigger"]).lower()
        assert "not claimed from" in assertions, case["id"]
        assert "payload" in assertions, case["id"]
        assert "profiler" in assertions or "capture-log" in assertions, case["id"]
        assert "predicate" in trigger and "payload" in trigger, case["id"]


def test_task_3_infeasible_indirect_cases_remain_blocked_with_exact_blockers() -> None:
    for case in _task3_cases():
        assert case["status"] != "profiler-backed-tested", case["id"]
        assert case["status"] != "soundengine-backed-tested", case["id"]
        assert case["blockers"], case["id"]
        blockers = json.dumps(case["blockers"]).lower()
        assert "payload" in blockers or "topic" in blockers or "wwiseconsole" in blockers, case["id"]
        assert case["evidence_path"].startswith(EVIDENCE_ROOT), case["id"]


def test_task_3_evidence_contract_names_required_files_and_commands() -> None:
    metadata = _task3_resource()["metadata"]

    assert metadata["unit_command"] == "python -m pytest tests/unit/test_profiler_soundengine_feasibility.py -q"
    assert metadata["live_command"].endswith("python -m pytest tests/live/test_profiler_transport_soundengine.py -q")
    assert "WWISE_LIVE=1" in metadata["live_command"]
    assert "startCapture -> subscribe -> trigger/action -> bounded wait -> stopCapture -> cleanup proof" in metadata["capture_policy"]
    assert {Path(case["evidence_path"]).name for case in _task3_cases()} == {
        "task-3-profiler-capability.md",
    }
    for case in _task3_cases():
        assert "tests/live/test_profiler_transport_soundengine.py" in case["evidence_command"], case["id"]


def test_task_3_cleanup_contract_prevents_orphan_capture_transport_and_subscriptions() -> None:
    for case in _task3_cases():
        cleanup_text = "\n".join(case["cleanup"]).lower()
        if any(uri.startswith("ak.wwise.core.transport.") for uri in case["uris"]):
            assert "destroy transport" in cleanup_text, case["id"]
            assert "execute stop" in cleanup_text, case["id"]
        if any("." in uri and uri.endswith(("itemAdded", "Registered", "Unregistered", "stateChanged")) for uri in case["uris"]):
            assert "unsubscribe" in cleanup_text or "cancel background subscriptions" in cleanup_text, case["id"]
        assert "delete sandbox" in cleanup_text, case["id"]


def test_task_5_resource_covers_every_soundengine_uri_once() -> None:
    resource = _task5_resource()
    rows = _task5_rows_by_uri(resource)

    assert set(rows) == ALL_SOUNDENGINE_URIS
    assert _covered_uris(resource["soundengine_cases"]) == ALL_SOUNDENGINE_URIS
    assert resource["metadata"]["promotes_coverage"] is False
    assert set(resource["metadata"]["evidence_paths"]) == TASK5_EVIDENCE_PATHS


def test_task_5_per_uri_rows_match_profiler_evidence_contract() -> None:
    for case in _task5_resource()["soundengine_cases"]:
        assert case["status"] == "still-deferred-with-evidence", case["id"]
        assert case["evidence_path"].startswith(EVIDENCE_ROOT), case["id"]
        assert case["trigger"]["bounded_wait_seconds"] == 5, case["id"]
        assert "payload" in case["trigger"]["predicate"].lower(), case["id"]
        for row in case["evidence_rows"]:
            assert REQUIRED_EVIDENCE_ROW_FIELDS <= set(row), row["api_uri"]
            validate_profiler_evidence_row(row)
            assert row["api_uri"] == row["trigger_call"], row["api_uri"]
            assert row["artifact_path"] == case["evidence_path"], row["api_uri"]
            assert row["bounded_wait_seconds"] == case["trigger"]["bounded_wait_seconds"], row["api_uri"]
            assert row["observed_payload_fields"] == [], row["api_uri"]
            assert row["missing_payload_blocker"], row["api_uri"]
            assert "payload" in row["missing_payload_blocker"].lower() or "topic" in row["missing_payload_blocker"].lower(), row["api_uri"]
            assert "cursor/time" in row["timestamp_window_mapping"], row["api_uri"]
            cleanup = row["cleanup_proof"]
            assert cleanup["capture_stopped"] is True, row["api_uri"]
            assert cleanup["subscriptions_cleared"] is True, row["api_uri"]
            assert cleanup["source_fixture_unchanged"] is True, row["api_uri"]


def test_task_5_inherits_task_3_profiler_blockers_for_accepted_smoke_calls() -> None:
    task3_rows = {row["api_uri"]: row for case in _task3_resource()["soundengine_cases"] for row in case["evidence_rows"]}
    task5_rows = _task5_rows_by_uri(_task5_resource())

    for uri in ("ak.soundengine.postMsgMonitor", "ak.soundengine.registerGameObj", "ak.soundengine.unregisterGameObj"):
        assert uri in task3_rows
        assert task3_rows[uri]["observed_payload_fields"] == []
        assert "no matching profiler topic payload" in task3_rows[uri]["missing_payload_blocker"]
        blocker = task5_rows[uri]["missing_payload_blocker"].lower()
        assert "task 3" in blocker
        assert "accepted" in blocker
        assert "no matching" in blocker
        assert "payload" in blocker


def test_task_5_does_not_promote_soundengine_or_transport_side_effects() -> None:
    resource = _task5_resource()

    assert resource["metadata"]["promotes_coverage"] is False
    assert not resource.get("profiler_transport_cases")
    for case in resource["soundengine_cases"]:
        assert case["status"] not in {"profiler-backed-tested", "soundengine-backed-tested"}
        assert not any(uri.startswith("ak.wwise.core.transport.") for uri in case["uris"]), case["id"]
        for row in case["evidence_rows"]:
            assert row["api_uri"].startswith("ak.soundengine."), row["api_uri"]
            proof_text = json.dumps(row).lower()
            assert any(phrase in proof_text for phrase in INSUFFICIENT_PROOF_PHRASES), row["api_uri"]


def test_task_5_fixture_plan_requires_copied_sandbox_and_deterministic_prerequisites() -> None:
    case = _task5_resource()["soundengine_cases"][0]
    setup = json.dumps(case["setup"]).lower()
    sequence = "\n".join(case["capture_sequence"]).lower()
    cleanup = "\n".join(case["cleanup"]).lower()

    assert "copied sampleproject sandbox" in setup
    assert "tests/_org/2022.1/sampleproject.wproj" in setup
    for prerequisite in ("event", "state", "switch", "rtpc", "listener", "game-object"):
        assert prerequisite in setup or prerequisite in sequence
    assert "startcapture" in sequence
    assert "bounded-wait per uri" in sequence
    assert "stopcapture" in sequence
    assert "unregister game objects" in cleanup
    assert "source fixture mtime" in cleanup


def test_task_5_profiler_evidence_rows_reject_missing_or_vague_blockers() -> None:
    valid = dict(_task5_resource()["soundengine_cases"][0]["evidence_rows"][0])

    missing_payload = dict(valid)
    missing_payload["observed_payload_fields"] = []
    missing_payload["missing_payload_blocker"] = ""
    with pytest.raises(ProfilerCapabilitySchemaError, match="observed payload fields or an exact missing-payload blocker"):
        validate_profiler_evidence_row(missing_payload)

    vague_blocker = dict(valid)
    vague_blocker["observed_payload_fields"] = []
    vague_blocker["missing_payload_blocker"] = "call returned without exception"
    with pytest.raises(ProfilerCapabilitySchemaError, match="missing payload/topic prerequisite"):
        validate_profiler_evidence_row(vague_blocker)

    no_cleanup = dict(valid)
    no_cleanup["cleanup_proof"] = {"capture_stopped": False, "subscriptions_cleared": True}
    with pytest.raises(ProfilerCapabilitySchemaError, match="capture cleanup"):
        validate_profiler_evidence_row(no_cleanup)


def test_task_5_evidence_contract_names_required_files_and_commands() -> None:
    metadata = _task5_resource()["metadata"]

    assert metadata["unit_command"] == "python -m pytest tests/unit/test_profiler_soundengine_feasibility.py -q"
    assert metadata["live_command"] == "WWISE_LIVE=1 python -m pytest tests/live/test_profiler_transport_soundengine.py -q"
    assert metadata["source_fixture"] == "tests/_org/2022.1/SampleProject.wproj"
    assert metadata["evidence_root"] == EVIDENCE_ROOT
    assert "accepted calls" in metadata["capture_policy"]
    assert "never proof" in metadata["capture_policy"]
    for case in _task5_resource()["soundengine_cases"]:
        assert "tests/live/test_profiler_transport_soundengine.py" in case["evidence_command"], case["id"]


def _task3_cases() -> list[Mapping[str, Any]]:
    resource = _task3_resource()
    return list(resource["profiler_transport_cases"]) + list(resource["soundengine_cases"])


def _task3_case(group: str, case_id: str) -> Mapping[str, Any]:
    for case in _task3_resource()[group]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing Task 3 case {case_id}")


def _task5_rows_by_uri(resource: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = [row for case in resource["soundengine_cases"] for row in case["evidence_rows"]]
    by_uri = {row["api_uri"]: row for row in rows}
    assert len(by_uri) == len(rows)
    return by_uri


def _covered_uris(cases: list[Mapping[str, Any]]) -> set[str]:
    return {uri for case in cases for uri in case["uris"]}


def _task3_resource() -> Mapping[str, Any]:
    return json.loads(TASK3_RESOURCE_PATH.read_text(encoding="utf-8"))


def _task5_resource() -> Mapping[str, Any]:
    return json.loads(TASK5_RESOURCE_PATH.read_text(encoding="utf-8"))
