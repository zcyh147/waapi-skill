from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.destructive.support.phase21_uri_policy import (  # pyright: ignore[reportMissingImports]
    ACCEPTED_FAKE_ROUTE_PROFILER_READ_URIS,
    CONFORMANCE_ONLY_URIS,
    PROFILER_PROBED_URIS,
    REOPENED_CORE_OBJECT_URIS,
    REOPENED_CORE_SOUNDBANK_URIS,
    REOPENED_CORE_SWITCH_CONTAINER_URIS,
    REOPENED_SOUNDENGINE_URIS,
    load_phase21_uri_policy,
    reopened_uris,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_RESOURCE = REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities" / "2022.1" / "phase2-coverage-summary.json"


def test_phase21_policy_resource_pins_exact_reopened_and_probe_uri_sets() -> None:
    policy = load_phase21_uri_policy()

    assert set(policy["reopened_apis"]) == reopened_uris()
    assert set(policy["profiler_probed_apis"]) == PROFILER_PROBED_URIS
    assert {entry["uri"] for entry in policy["conformance_only_apis"]} == CONFORMANCE_ONLY_URIS
    assert set(policy["accepted_fake_route_profiler_reads"]) == ACCEPTED_FAKE_ROUTE_PROFILER_READ_URIS
    assert policy["summary"] == {
        "accepted_fake_route_profiler_read_count": 2,
        "conformance_only_count": 11,
        "profiler_probed_count": 9,
        "reopened_count": 51,
    }


def test_phase21_policy_resource_contains_requested_exact_subsets() -> None:
    assert REOPENED_CORE_OBJECT_URIS == {
        "ak.wwise.core.object.attenuationCurveChanged",
        "ak.wwise.core.object.attenuationCurveLinkChanged",
        "ak.wwise.core.object.childAdded",
        "ak.wwise.core.object.childRemoved",
        "ak.wwise.core.object.copy",
        "ak.wwise.core.object.created",
        "ak.wwise.core.object.curveChanged",
        "ak.wwise.core.object.diff",
        "ak.wwise.core.object.move",
        "ak.wwise.core.object.nameChanged",
        "ak.wwise.core.object.notesChanged",
        "ak.wwise.core.object.pasteProperties",
        "ak.wwise.core.object.postDeleted",
        "ak.wwise.core.object.preDeleted",
        "ak.wwise.core.object.propertyChanged",
        "ak.wwise.core.object.referenceChanged",
        "ak.wwise.core.object.setAttenuationCurve",
        "ak.wwise.core.object.setName",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.object.setProperty",
        "ak.wwise.core.object.setRandomizer",
        "ak.wwise.core.object.setReference",
    }
    assert REOPENED_CORE_SOUNDBANK_URIS == {"ak.wwise.core.soundbank.processDefinitionFiles"}
    assert REOPENED_CORE_SWITCH_CONTAINER_URIS == {
        "ak.wwise.core.switchContainer.addAssignment",
        "ak.wwise.core.switchContainer.assignmentAdded",
        "ak.wwise.core.switchContainer.assignmentRemoved",
        "ak.wwise.core.switchContainer.removeAssignment",
    }
    assert PROFILER_PROBED_URIS == {
        "ak.wwise.core.profiler.captureLog.itemAdded",
        "ak.wwise.core.profiler.enableProfilerData",
        "ak.wwise.core.profiler.gameObjectRegistered",
        "ak.wwise.core.profiler.gameObjectReset",
        "ak.wwise.core.profiler.gameObjectUnregistered",
        "ak.wwise.core.profiler.startCapture",
        "ak.wwise.core.profiler.stateChanged",
        "ak.wwise.core.profiler.stopCapture",
        "ak.wwise.core.profiler.switchChanged",
    }
    assert CONFORMANCE_ONLY_URIS == {
        "ak.wwise.core.project.loaded",
        "ak.wwise.core.project.postClosed",
        "ak.wwise.core.project.preClosed",
        "ak.wwise.core.project.save",
        "ak.wwise.core.project.saved",
        "ak.wwise.core.transport.create",
        "ak.wwise.core.transport.destroy",
        "ak.wwise.core.transport.executeAction",
        "ak.wwise.core.transport.prepare",
        "ak.wwise.core.transport.stateChanged",
        "ak.wwise.core.undo.cancelGroup",
    }


def test_phase21_reopened_soundengine_list_is_derived_from_current_still_deferred_summary() -> None:
    summary = _summary_payload()
    currently_still_deferred_soundengine = {
        entry["uri"]
        for entry in summary["entries"]
        if entry["uri"].startswith("ak.soundengine.")
        and entry["achieved_status"] == "still-deferred-with-evidence"
    }

    assert REOPENED_SOUNDENGINE_URIS == currently_still_deferred_soundengine
    assert len(REOPENED_SOUNDENGINE_URIS) == 24


def test_conformance_only_policy_requires_rationale_and_never_counts_behavioral() -> None:
    policy = load_phase21_uri_policy()

    for entry in policy["conformance_only_apis"]:
        assert entry["evidence_class"] == "conformance_only_skip", entry["uri"]
        assert entry["user_approved_rationale"], entry["uri"]
        assert entry["future_review_trigger"], entry["uri"]
        assert "do not claim behavioral or live behavioral coverage" in entry["user_approved_rationale"]

    assert policy["metadata"]["no_promotion_in_task_1"] is True
    assert policy["metadata"]["windows_validation"] == "pending"


def test_fake_route_profiler_reads_remain_accepted_fake_route_not_conformance_only() -> None:
    summary_entries = {entry["uri"]: entry for entry in _summary_payload()["entries"]}

    for uri in ACCEPTED_FAKE_ROUTE_PROFILER_READ_URIS:
        assert uri not in CONFORMANCE_ONLY_URIS
        assert summary_entries[uri]["achieved_status"] == "fake-route-tested"
        assert summary_entries[uri]["counts_as_behavioral"] is False
        assert summary_entries[uri]["counts_as_live_behavioral"] is False
        assert summary_entries[uri]["attempted_live_blocker"]


def _summary_payload() -> dict[str, Any]:
    return json.loads(SUMMARY_RESOURCE.read_text(encoding="utf-8"))
