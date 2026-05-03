from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "skills"
    / "wwise-waapi"
    / "resources"
    / "capabilities"
    / "2022.1"
    / "task-7-project-mutation-sandbox-plan.json"
)
REQUIRED_URIS = {
    "ak.wwise.core.object.create",
    "ak.wwise.core.object.set",
    "ak.wwise.core.object.delete",
    "ak.wwise.core.switchContainer.addAssignment",
    "ak.wwise.core.switchContainer.getAssignments",
    "ak.wwise.core.switchContainer.removeAssignment",
    "ak.wwise.core.undo.beginGroup",
    "ak.wwise.core.undo.endGroup",
    "ak.wwise.core.undo.cancelGroup",
    "ak.wwise.core.undo.undo",
}


def test_task_7_plan_covers_project_mutation_groups() -> None:
    plan = _plan()
    cases = plan["mutation_cases"]

    assert {case["group"] for case in cases} == {"core.object", "core.switchContainer", "core.undo"}
    covered = {uri for case in cases for uri in case["uris"]}
    assert REQUIRED_URIS <= covered


def test_every_mutation_case_has_allowlist_and_cleanup_contract() -> None:
    for case in _plan()["mutation_cases"]:
        assert case["temporary_name_prefix"].startswith("WAAPI_TASK7_SANDBOX_"), case["id"]
        assert case["setup"], case["id"]
        assert case["action"], case["id"]
        assert case["assertions"], case["id"]
        assert case["cleanup"], case["id"]
        assert case["gate"] == {
            "env": {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1"},
            "allow_source_mutation": False,
        }
        allowlist = case["allowlist"]
        assert allowlist["expected_mutations"], case["id"]
        assert allowlist["cleanup_expectations"], case["id"]
        assert any("sandbox" in item for item in allowlist["cleanup_expectations"]), case["id"]
        assert case["evidence_path"].startswith(
            ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-7-"
        ), case["id"]


def test_postconditions_require_readbacks_not_no_exception_claims() -> None:
    for case in _plan()["mutation_cases"]:
        assertion_text = "\n".join(case["assertions"]).lower()
        assert "readback" in assertion_text or "getassignments" in assertion_text, case["id"]
        assert "no-exception" not in assertion_text
        assert "no exception" not in assertion_text


def test_undo_redo_limitation_is_explicitly_recorded() -> None:
    undo_case = _case("undo_group_create_then_undo_and_cancel")

    assert "ak.wwise.core.undo.undo" in undo_case["uris"]
    blockers = undo_case["blockers"]
    blocker_by_uri = {blocker["uri"]: blocker for blocker in blockers}
    assert blocker_by_uri["ak.wwise.core.undo.redo"] == {
        "uri": "ak.wwise.core.undo.redo",
        "reason": "No redo URI is reflected in the local Wwise 2022.1 functions manifest, so redo behavior cannot be asserted without inventing an API.",
    }
    assert "ak.wwise.core.undo.cancelGroup" in blocker_by_uri
    assert "deletes the disposable object explicitly" in blocker_by_uri["ak.wwise.core.undo.cancelGroup"]["reason"]


def test_switch_container_case_is_fail_closed_when_fixture_shape_is_rejected() -> None:
    switch_case = _case("switch_container_assignment_add_get_remove")

    assert switch_case["status"] == "sandbox-mutating-tested-or-blocked"
    assert switch_case["blockers"]
    assert "without claiming coverage" in " ".join(switch_case["assertions"])


def _case(case_id: str) -> Mapping[str, Any]:
    for case in _plan()["mutation_cases"]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing Task 7 mutation case {case_id}")


def _plan() -> Mapping[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
