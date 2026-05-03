from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "capabilities" / "2022.1" / "task-7-switchcontainer-assignment-plan.json"
SOURCE_FIXTURE = "tests/_org/2022.1/SampleProject.wproj"
ASSIGNMENT_EVIDENCE_PATH = ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/task-7-switch-assignments.md"
TOPIC_EVIDENCE_PATH = ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/task-7-switch-topics.md"
ASSIGNMENT_URIS = {
    "ak.wwise.core.switchContainer.addAssignment",
    "ak.wwise.core.switchContainer.getAssignments",
    "ak.wwise.core.switchContainer.removeAssignment",
}
TOPIC_URIS = {
    "ak.wwise.core.switchContainer.assignmentAdded",
    "ak.wwise.core.switchContainer.assignmentRemoved",
}


class SwitchAssignmentEvidenceError(AssertionError):
    pass


def test_task_7_plan_locks_switchcontainer_assignment_fixture_and_commands() -> None:
    plan = _plan()
    fixture = plan["fixture"]

    assert plan["metadata"]["source_fixture"] == SOURCE_FIXTURE
    assert SOURCE_FIXTURE in plan["metadata"]["destructive_command"]
    assert plan["metadata"]["unit_command"] == "python -m pytest tests/unit/test_switchcontainer_assignment_plan.py -q"
    assert set(plan["metadata"]["evidence_paths"]) == {ASSIGNMENT_EVIDENCE_PATH, TOPIC_EVIDENCE_PATH}
    assert fixture["accepted_switch_container"]["id"] == "{B5DB3AFA-044F-441E-BC4A-1397D20E2692}"
    assert fixture["accepted_switch_container"]["required_reference"]["target_id"] == fixture["accepted_switch_group"]["id"]
    assert fixture["switch_child"]["id"]
    assert fixture["target_object"]["create_under"] == fixture["accepted_switch_container"]["id"]
    assert fixture["target_object"]["type"] == "Sound"


def test_assignment_case_requires_getassignments_add_remove_and_cleanup_proof() -> None:
    case = _plan()["assignment_case"]
    assertions = "\n".join(case["assertions"]).lower()
    cleanup = "\n".join(case["cleanup"]).lower()
    allowlist_cleanup = "\n".join(case["allowlist"]["cleanup_expectations"]).lower()

    assert set(case["uris"]) == ASSIGNMENT_URIS
    assert case["status"] == "sandbox-mutating-tested-or-blocked"
    assert case["evidence_path"] == ASSIGNMENT_EVIDENCE_PATH
    assert case["gate"] == {"env": {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1"}, "allow_source_mutation": False}
    assert "getassignments" in assertions
    assert "after addassignment" in assertions
    assert "after removeassignment" in assertions
    assert "without claiming coverage" in assertions
    assert "empty object.get" in assertions or "empty array" in assertions
    assert "remove assignment" in cleanup
    assert "delete disposable" in cleanup
    assert "source .wproj/.wwu hash" in allowlist_cleanup
    assert "source .wproj mtime" in allowlist_cleanup


def test_topic_cases_require_payload_identity_readback_unsubscribe_cleanup_and_source_proof() -> None:
    cases = _plan()["topic_cases"]

    assert {case["uri"] for case in cases} == TOPIC_URIS
    for case in cases:
        requirements = case["payload_identity_requirements"]
        assert case["status"] == "sandbox-topic-tested-or-blocked"
        assert case["subscribe_before_mutation"] is True
        assert case["bounded_wait_seconds"] <= 5.0
        assert case["evidence_path"] == TOPIC_EVIDENCE_PATH
        assert set(requirements["required_payload_fields"]) == {"switchContainer", "child", "stateOrSwitch"}
        assert requirements["match_container_id"] is True
        assert requirements["match_child_object_id"] is True
        assert requirements["match_state_or_switch_id"] is True
        assert requirements["assignment_id_required_when_available"] is True
        assert "getAssignments" in case["readback_requirement"]
        assert any("delete disposable" in item for item in case["cleanup"])
        assert "hash unchanged" in case["source_immutability_proof"]


def test_plan_does_not_modify_broad_phase21_summary_counts() -> None:
    plan_text = json.dumps(_plan())

    assert "phase2-coverage-summary.json" not in plan_text
    assert "Do not promote" in _plan()["metadata"]["promotion_policy"]
    assert "timed waits" in _plan()["metadata"]["promotion_policy"]


def test_assignment_evidence_validator_requires_getassignments_pair_for_add_remove_cleanup() -> None:
    valid = _valid_assignment_evidence()
    validate_assignment_evidence(valid)

    missing_after_add = dict(valid, assignments_after_add=[])
    with pytest.raises(SwitchAssignmentEvidenceError, match="after addAssignment"):
        validate_assignment_evidence(missing_after_add)

    stale_after_remove = dict(valid, assignments_after_remove=valid["assignments_after_add"])
    with pytest.raises(SwitchAssignmentEvidenceError, match="after removeAssignment"):
        validate_assignment_evidence(stale_after_remove)

    no_cleanup = dict(valid, cleanup_proof={"deleted_target_id": valid["target_id"], "read_after_delete": [{"id": valid["target_id"]}]})
    with pytest.raises(SwitchAssignmentEvidenceError, match="cleanup"):
        validate_assignment_evidence(no_cleanup)

    source_changed = dict(valid, source_hash_proof={"before": ["a", 1, 2], "after": ["b", 1, 2]})
    with pytest.raises(SwitchAssignmentEvidenceError, match="source hash"):
        validate_assignment_evidence(source_changed)


def test_topic_evidence_validator_rejects_missing_container_switch_or_available_assignment_id() -> None:
    valid = _valid_topic_evidence()
    validate_topic_evidence(valid)

    missing_container = json.loads(json.dumps(valid))
    missing_container["payload"]["switchContainer"]["id"] = "{00000000-0000-0000-0000-000000000000}"
    with pytest.raises(SwitchAssignmentEvidenceError, match="container"):
        validate_topic_evidence(missing_container)

    missing_switch = json.loads(json.dumps(valid))
    missing_switch["payload"]["stateOrSwitch"]["id"] = "{00000000-0000-0000-0000-000000000000}"
    with pytest.raises(SwitchAssignmentEvidenceError, match="stateOrSwitch"):
        validate_topic_evidence(missing_switch)

    missing_child = json.loads(json.dumps(valid))
    missing_child["payload"]["child"]["id"] = "{00000000-0000-0000-0000-000000000000}"
    with pytest.raises(SwitchAssignmentEvidenceError, match="child"):
        validate_topic_evidence(missing_child)

    missing_available_assignment = json.loads(json.dumps(valid))
    missing_available_assignment["assignment_id"] = "assignment-123"
    missing_available_assignment["payload"].pop("assignment", None)
    with pytest.raises(SwitchAssignmentEvidenceError, match="assignment id"):
        validate_topic_evidence(missing_available_assignment)

    missing_cleanup = json.loads(json.dumps(valid))
    missing_cleanup.pop("cleanup_proof")
    with pytest.raises(SwitchAssignmentEvidenceError, match="cleanup"):
        validate_topic_evidence(missing_cleanup)

    stale_cleanup = json.loads(json.dumps(valid))
    stale_cleanup["cleanup_proof"]["read_after_delete"] = [{"id": valid["target_id"]}]
    with pytest.raises(SwitchAssignmentEvidenceError, match="cleanup"):
        validate_topic_evidence(stale_cleanup)

    source_changed = json.loads(json.dumps(valid))
    source_changed["source_hash_proof"]["after"] = ["changed", 7, 100]
    with pytest.raises(SwitchAssignmentEvidenceError, match="source hash"):
        validate_topic_evidence(source_changed)


def validate_assignment_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("status") != "passed":
        raise SwitchAssignmentEvidenceError("only passed assignment evidence is promotable")
    if set(evidence.get("uris", [])) != ASSIGNMENT_URIS:
        raise SwitchAssignmentEvidenceError("assignment evidence URI set does not match Task 7 assignment APIs")
    target_id = _required_string(evidence, "target_id")
    switch_id = _required_string(evidence, "state_or_switch_id")
    container_id = _required_string(evidence, "switch_container_id")
    if container_id != _plan()["fixture"]["accepted_switch_container"]["id"]:
        raise SwitchAssignmentEvidenceError("assignment evidence must use the accepted SwitchContainer fixture")
    expected_pair = {"child": target_id, "stateOrSwitch": switch_id}
    if not _contains_pair(evidence.get("assignments_after_add"), expected_pair):
        raise SwitchAssignmentEvidenceError("getAssignments after addAssignment must contain the target/switch pair")
    if _contains_pair(evidence.get("assignments_after_remove"), expected_pair):
        raise SwitchAssignmentEvidenceError("getAssignments after removeAssignment must not contain the target/switch pair")
    cleanup = evidence.get("cleanup_proof")
    if not isinstance(cleanup, Mapping) or cleanup.get("deleted_target_id") != target_id or cleanup.get("read_after_delete") != []:
        raise SwitchAssignmentEvidenceError("cleanup proof must show deleted target and empty object.get readback")
    source_hash = evidence.get("source_hash_proof")
    if not isinstance(source_hash, Mapping) or source_hash.get("before") != source_hash.get("after"):
        raise SwitchAssignmentEvidenceError("source hash proof must show before/after equality")


def validate_topic_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("status") != "passed":
        raise SwitchAssignmentEvidenceError("only passed topic evidence is promotable")
    if evidence.get("uri") not in TOPIC_URIS:
        raise SwitchAssignmentEvidenceError("topic evidence URI does not match reopened switchContainer topics")
    payload = evidence.get("payload")
    if not isinstance(payload, Mapping):
        raise SwitchAssignmentEvidenceError("topic payload must be a mapping")
    payload_json = json.dumps(payload, sort_keys=True)
    container_id = _required_string(evidence, "switch_container_id")
    target_id = _required_string(evidence, "target_id")
    switch_id = _required_string(evidence, "state_or_switch_id")
    if container_id not in payload_json:
        raise SwitchAssignmentEvidenceError("topic payload must identify the SwitchContainer container")
    if target_id not in payload_json:
        raise SwitchAssignmentEvidenceError("topic payload must identify the assigned child target")
    if switch_id not in payload_json:
        raise SwitchAssignmentEvidenceError("topic payload must identify the stateOrSwitch")
    assignment_id = evidence.get("assignment_id")
    if isinstance(assignment_id, str) and assignment_id and assignment_id not in payload_json:
        raise SwitchAssignmentEvidenceError("topic payload must include assignment id when available")
    if evidence.get("readback_pair_verified") is not True:
        raise SwitchAssignmentEvidenceError("topic evidence must be paired with getAssignments readback")
    cleanup = evidence.get("cleanup_proof")
    if not isinstance(cleanup, Mapping) or cleanup.get("deleted_target_id") != target_id or cleanup.get("read_after_delete") != []:
        raise SwitchAssignmentEvidenceError("topic cleanup proof must show deleted target and empty object.get readback")
    source_hash = evidence.get("source_hash_proof")
    if not isinstance(source_hash, Mapping) or source_hash.get("before") != source_hash.get("after"):
        raise SwitchAssignmentEvidenceError("topic source hash proof must show before/after equality")


def _contains_pair(rows: Any, expected_pair: Mapping[str, str]) -> bool:
    if not isinstance(rows, list):
        return False
    for row in rows:
        if isinstance(row, Mapping) and row.get("child") == expected_pair["child"] and row.get("stateOrSwitch") == expected_pair["stateOrSwitch"]:
            return True
    return False


def _required_string(evidence: Mapping[str, Any], key: str) -> str:
    value = evidence.get(key)
    if not isinstance(value, str) or not value:
        raise SwitchAssignmentEvidenceError(f"{key} is required")
    return value


def _valid_assignment_evidence() -> dict[str, Any]:
    container_id = _plan()["fixture"]["accepted_switch_container"]["id"]
    target_id = "{11111111-1111-1111-1111-111111111111}"
    switch_id = _plan()["fixture"]["switch_child"]["id"]
    return {
        "status": "passed",
        "uris": sorted(ASSIGNMENT_URIS),
        "switch_container_id": container_id,
        "target_id": target_id,
        "state_or_switch_id": switch_id,
        "assignments_after_add": [{"child": target_id, "stateOrSwitch": switch_id}],
        "assignments_after_remove": [],
        "cleanup_proof": {"deleted_target_id": target_id, "read_after_delete": []},
        "source_hash_proof": {"before": ["hash", 7, 100], "after": ["hash", 7, 100]},
    }


def _valid_topic_evidence() -> dict[str, Any]:
    container_id = _plan()["fixture"]["accepted_switch_container"]["id"]
    target_id = "{11111111-1111-1111-1111-111111111111}"
    switch_id = _plan()["fixture"]["switch_child"]["id"]
    return {
        "status": "passed",
        "uri": "ak.wwise.core.switchContainer.assignmentAdded",
        "switch_container_id": container_id,
        "target_id": target_id,
        "state_or_switch_id": switch_id,
        "payload": {
            "switchContainer": {"id": container_id, "name": "Footstep_Types"},
            "child": {"id": target_id},
            "stateOrSwitch": {"id": switch_id, "name": "Running"},
            "assignment": {"id": "assignment-123"},
        },
        "assignment_id": "assignment-123",
        "readback_pair_verified": True,
        "cleanup_proof": {"deleted_target_id": target_id, "read_after_delete": []},
        "source_hash_proof": {"before": ["hash", 7, 100], "after": ["hash", 7, 100]},
    }


def _plan() -> Mapping[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
