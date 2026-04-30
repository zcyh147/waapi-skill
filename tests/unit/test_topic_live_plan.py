from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / ".agents"
    / "skills"
    / "wwise-waapi"
    / "resources"
    / "coverage"
    / "2022.1"
    / "task-6-object-topic-live-plan.json"
)


def test_task_6_plan_declares_object_read_cases_with_behavioral_assertions() -> None:
    plan = _plan()
    cases = plan["object_read_cases"]

    assert {case["uri"] for case in cases} >= {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.getTypes",
        "ak.wwise.core.object.getPropertyAndReferenceNames",
        "ak.wwise.core.object.getPropertyInfo",
        "ak.wwise.core.object.getAttenuationCurve",
    }
    for case in cases:
        assert case["no_mutation"] is True, case["id"]
        assert case["assertions"], case["id"]
        assert case["expected"], case["id"]
        assert case["evidence_path"].startswith(".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/object-read/"), case["id"]


def test_topic_cases_with_attempted_publishers_record_payload_wait_unsubscribe_and_cleanup() -> None:
    candidate_cases = [case for case in _plan()["topic_cases"] if case.get("publisher") or case.get("attempted_publisher")]

    assert candidate_cases, "topic candidates should document deterministic publisher attempts"
    for case in candidate_cases:
        publisher = case.get("publisher") or case.get("attempted_publisher")
        assert isinstance(publisher, Mapping), case["id"]
        assert publisher["deterministic"] is True, case["id"]
        assert publisher["uri"], case["id"]
        assert case["bounded_wait_seconds"] > 0, case["id"]
        assert isinstance(case["subscription_options"], Mapping), case["id"]
        payload = case.get("payload_assertions")
        assert isinstance(payload, Mapping), case["id"]
        assert payload["required_fields"], case["id"]
        assert payload["field_evidence"], case["id"]
        assert "active_topics is empty" in case["unsubscribe_assertion"], case["id"]
        assert case["cleanup"], case["id"]
        assert case["evidence_path"].startswith(".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/topics/"), case["id"]
        assert "tests/live/test_object_topics_sandbox.py" in case["evidence_command"], case["id"]


def test_still_deferred_topics_keep_blocker_evidence_instead_of_live_claims() -> None:
    deferred = [case for case in _plan()["topic_cases"] if case["status"] == "still-deferred-with-evidence"]

    assert deferred, "topics without deterministic publishers should remain evidence-backed deferrals"
    for case in deferred:
        assert "publisher" not in case, case["id"]
        assert case["blocker"], case["id"]
        assert case["missing_requirements"], case["id"]
        assert case["future_review_trigger"], case["id"]


def test_project_saved_topic_has_specific_payload_evidence() -> None:
    topic = _topic_case("ak.wwise.core.project.saved")

    assert topic["status"] == "still-deferred-with-evidence"
    assert topic["attempted_publisher"]["uri"] == "ak.wwise.core.project.save"
    assert topic["payload_assertions"]["required_fields"] == ["modifiedPaths"]
    assert "publishSchema" in topic["payload_assertions"]["field_evidence"]["modifiedPaths"]
    assert "Topic not available" in topic["blocker"]


def test_object_get_types_uses_wwise_type_name_not_broad_category() -> None:
    case = _object_case("object_get_types_contains_project_and_sound")

    assert case["expected"]["contains_type_names"] == ["Project", "Sound"]
    assert "contains_types" not in case["expected"]


def _topic_case(uri: str) -> Mapping[str, Any]:
    for case in _plan()["topic_cases"]:
        if case["uri"] == uri:
            return case
    raise AssertionError(f"missing topic case {uri}")


def _object_case(case_id: str) -> Mapping[str, Any]:
    for case in _plan()["object_read_cases"]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing object case {case_id}")


def _plan() -> Mapping[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
