from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.phase21_uri_policy import REOPENED_CORE_OBJECT_URIS  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "skills" / "wwise-waapi" / "resources" / "coverage" / "2022.1" / "task-4-core-object-deferred-plan.json"
SOURCE_FIXTURE = "tests/_org/2022.1/SampleProject.wproj"
FUNCTION_URIS = {
    "ak.wwise.core.object.copy",
    "ak.wwise.core.object.diff",
    "ak.wwise.core.object.move",
    "ak.wwise.core.object.pasteProperties",
    "ak.wwise.core.object.setAttenuationCurve",
    "ak.wwise.core.object.setName",
    "ak.wwise.core.object.setNotes",
    "ak.wwise.core.object.setProperty",
    "ak.wwise.core.object.setRandomizer",
    "ak.wwise.core.object.setReference",
}
TOPIC_URIS = {
    "ak.wwise.core.object.attenuationCurveChanged",
    "ak.wwise.core.object.attenuationCurveLinkChanged",
    "ak.wwise.core.object.childAdded",
    "ak.wwise.core.object.childRemoved",
    "ak.wwise.core.object.created",
    "ak.wwise.core.object.curveChanged",
    "ak.wwise.core.object.nameChanged",
    "ak.wwise.core.object.notesChanged",
    "ak.wwise.core.object.postDeleted",
    "ak.wwise.core.object.preDeleted",
    "ak.wwise.core.object.propertyChanged",
    "ak.wwise.core.object.referenceChanged",
}


def test_task_4_plan_locks_exact_reopened_core_object_uris() -> None:
    plan = _plan()
    function_uris = {case["uri"] for case in plan["function_cases"]}
    topic_uris = {case["uri"] for case in plan["topic_cases"]}

    assert function_uris == FUNCTION_URIS
    assert topic_uris == TOPIC_URIS
    assert function_uris | topic_uris == REOPENED_CORE_OBJECT_URIS
    assert plan["metadata"]["source_policy"].startswith(f"Use {SOURCE_FIXTURE}")
    assert SOURCE_FIXTURE in plan["metadata"]["destructive_command"]


def test_function_cases_require_precondition_after_read_cleanup_and_source_proof_or_blocker() -> None:
    for case in _plan()["function_cases"]:
        assert case["uri"].startswith("ak.wwise.core.object."), case["id"]
        assert case["precondition"], case["id"]
        assert case["mutation"], case["id"]
        after_read = case["after_read"].lower()
        assert "read" in after_read or "object.get" in after_read or case["status"] == "still-deferred-with-evidence", case["id"]
        assert case["cleanup"], case["id"]
        assert "source" in case["source_immutability_proof"].lower(), case["id"]
        assert case["evidence_path"] == ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/task-4-core-object.md"

        if case["status"] == "still-deferred-with-evidence":
            assert case.get("blocker"), case["id"]
            assert "no exception" not in case["blocker"].lower(), case["id"]
        else:
            assert case["status"] == "sandbox-mutating-tested-or-blocked", case["id"]
            text = "\n".join([case["precondition"], case["after_read"], *case["cleanup"], case["source_immutability_proof"]]).lower()
            assert "object.get" in text or "read" in text, case["id"]
            assert "delete" in text and "empty array" in text, case["id"]
            assert "hash unchanged" in text, case["id"]


def test_topic_cases_require_subscribe_first_identity_payload_unsubscribe_and_cleanup_contract() -> None:
    old_new_topics = {
        "ak.wwise.core.object.nameChanged",
        "ak.wwise.core.object.notesChanged",
        "ak.wwise.core.object.propertyChanged",
        "ak.wwise.core.object.referenceChanged",
        "ak.wwise.core.object.attenuationCurveChanged",
        "ak.wwise.core.object.attenuationCurveLinkChanged",
        "ak.wwise.core.object.curveChanged",
    }
    for case in _plan()["topic_cases"]:
        assert case["subscribe_before_mutation"] is True, case["id"]
        assert case["bounded_wait_seconds"] <= 5.0, case["id"]
        assert case["publisher"], case["id"]
        requirements = case["payload_identity_requirements"]
        assert requirements["match_object_id_or_path"] is True, case["id"]
        assert {"id", "name", "type", "path"} <= set(requirements["required_return_fields"]), case["id"]
        assert requirements["topic_specific_fields"], case["id"]
        assert requirements["old_new_required_when_applicable"] is (case["uri"] in old_new_topics), case["id"]
        assert "unsubscribed" in case["unsubscribe_assertion"], case["id"]
        assert any("object.get" in item for item in case["cleanup"]), case["id"]
        assert "hash unchanged" in case["source_immutability_proof"], case["id"]
        assert case["evidence_path"] == ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/task-4-core-object-topics.md"
        if case["status"] == "still-deferred-with-evidence":
            assert case.get("blocker"), case["id"]


def test_plan_does_not_promote_from_timed_waits_or_modify_broad_summary_counts() -> None:
    plan = _plan()
    assert "Do not promote" in plan["metadata"]["promotion_policy"]
    assert "timed waits" in plan["metadata"]["promotion_policy"]
    assert "phase2-coverage-summary.json" not in json.dumps(plan)
    for case in [*plan["function_cases"], *plan["topic_cases"]]:
        assert case["status"] in {
            "sandbox-mutating-tested-or-blocked",
            "sandbox-topic-tested-or-blocked",
            "still-deferred-with-evidence",
        }
        assert case["status"] not in {"live-sandbox-tested", "sandbox-mutating-tested"}


def _plan() -> Mapping[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
