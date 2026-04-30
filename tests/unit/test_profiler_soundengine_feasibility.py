from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "resources"
    / "coverage"
    / "2022.1"
    / "task-9-profiler-soundengine-feasibility.json"
)
EVIDENCE_ROOT = ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/"
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


def test_task_9_plan_covers_profiler_transport_and_soundengine_candidates() -> None:
    plan = _plan()
    profiler_transport_uris = _covered_uris(plan["profiler_transport_cases"])
    soundengine_uris = _covered_uris(plan["soundengine_cases"])

    assert PROFILER_BOUNDARY_URIS <= profiler_transport_uris | soundengine_uris
    assert TRANSPORT_URIS <= profiler_transport_uris
    assert SOUNDENGINE_SMOKE_URIS <= soundengine_uris
    assert any(uri.startswith("ak.soundengine.") for uri in _covered_uris(plan["deferred_cases"]))


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


def test_transport_case_asserts_state_transitions_not_just_ids() -> None:
    case = _case("profiler_transport_cases", "profiler_transport_event_state_capture")
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
    deferred = _plan()["deferred_cases"]
    assert deferred
    for case in deferred:
        assert case["status"] == "still-deferred-with-evidence", case["id"]
        assert case["blocker"], case["id"]
        assert "insufficient" in case["blocker"].lower() or "empty arrays" in case["blocker"].lower(), case["id"]
        assert case["missing_requirements"], case["id"]
        assert case["future_review_trigger"], case["id"]
        assert case["evidence_path"].startswith(EVIDENCE_ROOT), case["id"]


def test_evidence_contract_names_required_task_files_and_commands() -> None:
    metadata = _plan()["metadata"]

    assert metadata["unit_command"] == "python -m pytest tests/unit/test_profiler_soundengine_feasibility.py -q"
    assert metadata["live_command"].endswith("python -m pytest tests/live/test_profiler_transport_soundengine.py -q")
    assert "WWISE_LIVE=1" in metadata["live_command"]
    assert "startCapture -> trigger/action -> bounded observation -> stopCapture -> cleanup" in metadata["capture_policy"]
    assert {Path(case["evidence_path"]).name for case in _feasible_cases()} == {
        "task-9-profiler-transport.md",
        "task-9-soundengine.md",
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
