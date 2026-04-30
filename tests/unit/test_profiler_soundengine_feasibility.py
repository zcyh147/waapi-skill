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
PLAN_PATH = (
    REPO_ROOT
    / "resources"
    / "coverage"
    / "2022.1"
    / "task-3-profiler-capability.json"
)
EVIDENCE_ROOT = ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/"
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
SOUNDENGINE_SMOKE_URIS = {
    "ak.soundengine.postMsgMonitor",
    "ak.soundengine.registerGameObj",
    "ak.soundengine.unregisterGameObj",
}


def test_task_3_plan_covers_profiler_transport_and_soundengine_candidates() -> None:
    plan = _plan()
    profiler_transport_uris = _covered_uris(plan["profiler_transport_cases"])
    soundengine_uris = _covered_uris(plan["soundengine_cases"])

    assert PROFILER_BOUNDARY_URIS <= profiler_transport_uris | soundengine_uris
    assert TRANSPORT_URIS <= profiler_transport_uris
    assert SOUNDENGINE_SMOKE_URIS <= soundengine_uris
    assert any(uri.startswith("ak.soundengine.") for uri in soundengine_uris)


def test_task_3_capability_resource_matches_schema_and_does_not_promote() -> None:
    plan = _plan()

    validate_profiler_capability_resource(plan)
    assert plan["metadata"]["promotes_coverage"] is False
    for case in _feasible_cases():
        assert case["status"] in {"capability-observed", "capability-blocked", "prerequisite-blocked"}
        assert case["status"] not in {"profiler-backed-tested", "soundengine-backed-tested"}
        assert case["evidence_path"].startswith(EVIDENCE_ROOT)
        for row in case["evidence_rows"]:
            assert REQUIRED_EVIDENCE_ROW_FIELDS <= set(row), case["id"]
            validate_profiler_evidence_row(row)


def test_blocked_live_outcomes_are_not_marked_observed_or_placeholder_payloads() -> None:
    for case in _feasible_cases():
        assert case["status"] == "capability-blocked", case["id"]
        for row in case["evidence_rows"]:
            assert row["observed_payload_fields"] == [], row["api_uri"]
            blocker = row["missing_payload_blocker"].lower()
            assert "live probe replaces this" not in blocker, row["api_uri"]
            assert "payload" in blocker or "statechanged" in blocker or "getstate transition" in blocker, row["api_uri"]


def test_observed_status_rejects_placeholder_or_missing_payload_blockers() -> None:
    observed_plan = json.loads(json.dumps(_plan()))
    case = observed_plan["soundengine_cases"][0]
    case["status"] = "capability-observed"
    case["evidence_rows"][0]["observed_payload_fields"] = ["description"]
    case["evidence_rows"][0]["missing_payload_blocker"] = "live probe replaces this with the exact missing payload/topic blocker"

    with pytest.raises(ProfilerCapabilitySchemaError, match="placeholder text"):
        validate_profiler_capability_resource(observed_plan)

    case["evidence_rows"][0]["missing_payload_blocker"] = "no matching profiler topic payload within 5.0s; seen=[]"
    with pytest.raises(ProfilerCapabilitySchemaError, match="cannot carry a missing-payload blocker"):
        validate_profiler_capability_resource(observed_plan)


def test_feasible_cases_use_capture_action_bounded_observation_stop_capture_cleanup() -> None:
    for case in _feasible_cases():
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


def test_profiler_evidence_rows_require_per_uri_payload_or_exact_blocker() -> None:
    valid = dict(_case("soundengine_cases", "soundengine_monitor_message_capture_log_capability_probe")["evidence_rows"][0])

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


def test_transport_case_asserts_state_transitions_not_just_ids() -> None:
    case = _case("profiler_transport_cases", "profiler_transport_state_capability_probe")
    assertions = "\n".join(case["assertions"]).lower()
    trigger = json.dumps(case["trigger"]).lower()

    assert "getstate" in assertions
    assert "state transition" in assertions
    assert "getlist contains" in assertions
    assert "destroy" in assertions
    assert "returned ids alone" not in assertions
    assert "statechanged" in trigger or "state transition" in trigger


def test_soundengine_cases_require_profiler_or_topic_side_effects() -> None:
    for case in _plan()["soundengine_cases"]:
        assertions = "\n".join(case["assertions"]).lower()
        trigger = json.dumps(case["trigger"]).lower()
        assert "not claimed from" in assertions, case["id"]
        assert "payload" in assertions, case["id"]
        assert "profiler" in assertions or "capture-log" in assertions, case["id"]
        assert "predicate" in trigger and "payload" in trigger, case["id"]


def test_infeasible_indirect_cases_remain_deferred_with_exact_blockers() -> None:
    for case in _feasible_cases():
        assert case["status"] != "profiler-backed-tested", case["id"]
        assert case["status"] != "soundengine-backed-tested", case["id"]
        assert case["blockers"], case["id"]
        blockers = json.dumps(case["blockers"]).lower()
        assert "payload" in blockers or "topic" in blockers or "wwiseconsole" in blockers, case["id"]
        assert case["evidence_path"].startswith(EVIDENCE_ROOT), case["id"]


def test_evidence_contract_names_required_task_files_and_commands() -> None:
    metadata = _plan()["metadata"]

    assert metadata["unit_command"] == "python -m pytest tests/unit/test_profiler_soundengine_feasibility.py -q"
    assert metadata["live_command"].endswith("python -m pytest tests/live/test_profiler_transport_soundengine.py -q")
    assert "WWISE_LIVE=1" in metadata["live_command"]
    assert "startCapture -> subscribe -> trigger/action -> bounded wait -> stopCapture -> cleanup proof" in metadata["capture_policy"]
    assert {Path(case["evidence_path"]).name for case in _feasible_cases()} == {
        "task-3-profiler-capability.md",
    }
    for case in _feasible_cases():
        assert "tests/live/test_profiler_transport_soundengine.py" in case["evidence_command"], case["id"]


def test_cleanup_contract_prevents_orphan_capture_transport_and_subscriptions() -> None:
    for case in _feasible_cases():
        cleanup_text = "\n".join(case["cleanup"]).lower()
        if any(uri.startswith("ak.wwise.core.transport.") for uri in case["uris"]):
            assert "destroy transport" in cleanup_text, case["id"]
            assert "execute stop" in cleanup_text, case["id"]
        if any("." in uri and uri.endswith(("itemAdded", "Registered", "Unregistered", "stateChanged")) for uri in case["uris"]):
            assert "unsubscribe" in cleanup_text or "cancel background subscriptions" in cleanup_text, case["id"]
        assert "delete sandbox" in cleanup_text, case["id"]


def _feasible_cases() -> list[Mapping[str, Any]]:
    plan = _plan()
    return list(plan["profiler_transport_cases"]) + list(plan["soundengine_cases"])


def _case(group: str, case_id: str) -> Mapping[str, Any]:
    for case in _plan()[group]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing Task 9 case {case_id}")


def _covered_uris(cases: list[Mapping[str, Any]]) -> set[str]:
    return {uri for case in cases for uri in case["uris"]}


def _plan() -> Mapping[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
