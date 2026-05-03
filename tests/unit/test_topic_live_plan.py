from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC_OBJECT_ID_MARKER = "$disposable_object_id"
PLAN_PATH = (
    REPO_ROOT
    / "skills"
    / "wwise-waapi"
    / "resources"
    / "capabilities"
    / "2022.1"
    / "task-6-object-topic-live-plan.json"
)
TASK_8_PLAN_PATHS = {
    "2021.1": REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "capabilities" / "2021.1" / "task-8-object-topic-live-plan.json",
    "2024.1": REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "capabilities" / "2024.1" / "task-8-object-topic-live-plan.json",
    "2025.1": REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "capabilities" / "2025.1" / "task-8-object-topic-live-plan.json",
}
SAFE_TASK_8_TOPIC_URIS = {
    "ak.wwise.core.object.childAdded",
    "ak.wwise.core.object.childRemoved",
    "ak.wwise.core.object.created",
    "ak.wwise.core.object.nameChanged",
    "ak.wwise.core.object.notesChanged",
    "ak.wwise.core.object.postDeleted",
    "ak.wwise.core.object.preDeleted",
    "ak.wwise.core.object.propertyChanged",
    "ak.wwise.core.log.itemAdded",
}
FORBIDDEN_TASK_8_TOPIC_URIS = {
    "ak.wwise.core.object.attenuationCurveChanged",
    "ak.wwise.core.object.attenuationCurveLinkChanged",
    "ak.wwise.core.object.curveChanged",
    "ak.wwise.core.object.referenceChanged",
    "ak.wwise.core.object.structureChanged",
    "ak.wwise.core.profiler.captureLog.itemAdded",
    "ak.wwise.core.project.saved",
    "ak.wwise.ui.selectionChanged",
}


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


def test_task_8_versioned_safe_topic_plans_match_manifest_inventory_without_route_only_topics() -> None:
    for version, path in TASK_8_PLAN_PATHS.items():
        plan = _task8_plan(path)
        manifest_topics = _manifest_topics(version)
        cases = plan["topic_cases"]
        case_uris = {case["uri"] for case in cases}

        assert plan["metadata"]["version"] == version
        assert plan["metadata"]["source_manifest"] == f"resources/manifest/{version}/topics.json"
        assert plan["metadata"]["active_live_smoke_status"] == "blocked-by-no-Wwise-launch-instruction"
        assert plan["coverage_policy"]["counts_as_behavioral"] is False
        assert plan["coverage_policy"]["counts_as_live_behavioral"] is False
        assert case_uris == SAFE_TASK_8_TOPIC_URIS & manifest_topics
        assert not (case_uris & FORBIDDEN_TASK_8_TOPIC_URIS)
        assert "ak.wwise.core.object.deleted" not in case_uris

        for case in cases:
            assert case["uri"] in manifest_topics, case["uri"]
            assert case["bounded_wait_seconds"] > 0, case["id"]
            assert case["subscribe_before_mutation"] is True, case["id"]
            assert "active topic set is empty" in case["unsubscribe_assertion"], case["id"]
            assert case["payload_identity_requirements"], case["id"]
            assert case["readback"], case["id"]
            assert case["cleanup"], case["id"]
            assert case["counts_as_behavioral"] is False, case["id"]
            assert case["counts_as_live_behavioral"] is False, case["id"]
            assert case["evidence_path"].startswith(
                f".sisyphus/evidence/waapi-test-remediation/topic-behavior/{version}/"
            ), case["id"]


def test_task_8_planned_publishers_are_deterministic_and_unbounded_log_topics_stay_deferred() -> None:
    for version, path in TASK_8_PLAN_PATHS.items():
        for case in _task8_plan(path)["topic_cases"]:
            if case["status"] == "still-deferred-with-evidence":
                assert version in {"2021.1", "2024.1"}
                assert case["uri"] == "ak.wwise.core.log.itemAdded"
                assert "publisher" not in case
                if version == "2021.1":
                    assert "no ak.wwise.core.log.addItem publisher" in case["blocker"]
                else:
                    assert case["attempted_publisher"]["uri"] == "ak.wwise.core.log.addItem"
                    assert "did not publish a bounded" in case["blocker"]
                    assert case["future_review_trigger"]
                continue

            assert case["status"] == "planned-active-live-smoke", case["id"]
            publisher = case["publisher"]
            assert isinstance(publisher, Mapping), case["id"]
            assert publisher["deterministic"] is True, case["id"]
            assert publisher["uri"].startswith("ak.wwise.core."), case["id"]
            assert isinstance(publisher["options"], Mapping), case["id"]
            if case["uri"] == "ak.wwise.core.log.itemAdded":
                assert version in {"2024.1", "2025.1"}
                assert publisher["uri"] == "ak.wwise.core.log.addItem"
            else:
                assert publisher["uri"] in {
                    "ak.wwise.core.object.create",
                    "ak.wwise.core.object.delete",
                    "ak.wwise.core.object.setName",
                    "ak.wwise.core.object.setNotes",
                    "ak.wwise.core.object.setProperty",
                }


def test_task_8_property_changed_documents_dynamic_subscription_options() -> None:
    for path in TASK_8_PLAN_PATHS.values():
        case = _task8_topic_case(path, "ak.wwise.core.object.propertyChanged")

        assert case["subscription_options"] == {"return": ["id", "name", "type", "path", "notes", "Volume"]}
        assert case["dynamic_subscription_options"] == {"object": DYNAMIC_OBJECT_ID_MARKER, "property": "Volume"}
        assert "object" not in case["subscription_options"]
        assert "property" not in case["subscription_options"]
        assert case["publisher"]["uri"] == "ak.wwise.core.object.setProperty"


def test_property_changed_subscription_options_render_disposable_object_id() -> None:
    case = _task8_topic_case(TASK_8_PLAN_PATHS["2021.1"], "ak.wwise.core.object.propertyChanged")
    subscription_options = getattr(import_module("tests.live.versioned_object_topics_sandbox"), "_subscription_options")

    rendered = subscription_options(case, {"object": "{12345678-1234-1234-1234-123456789abc}"})

    assert rendered == {
        "return": ["id", "name", "type", "path", "notes", "Volume"],
        "object": "{12345678-1234-1234-1234-123456789abc}",
        "property": "Volume",
    }
    assert "object" not in case["subscription_options"]


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


def _task8_plan(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _task8_topic_case(path: Path, uri: str) -> Mapping[str, Any]:
    for case in _task8_plan(path)["topic_cases"]:
        if case["uri"] == uri:
            return case
    raise AssertionError(f"missing Task 8 topic case {uri} in {path}")


def _manifest_topics(version: str) -> set[str]:
    path = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "manifest" / version / "topics.json"
    return {entry["uri"] for entry in json.loads(path.read_text(encoding="utf-8"))["topics"]}
