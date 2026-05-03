from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from tests.destructive.support.api_coverage_audit import (  # pyright: ignore[reportMissingImports]
    ApiCoverageAuditor,
    BehavioralCoverageRecord,
    Phase2CoverageStatusRecord,
)
from wwise_waapi.deferred_registry import ApiClassifier, DeferredRegistry  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_ROOT = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "manifest"


def test_default_manifest_audit_passes_with_complete_deferred_registry() -> None:
    manifest = ManifestStore(root=MANIFEST_ROOT).load("2022.1")
    registry = DeferredRegistry.load_default("2022.1")

    result = ApiCoverageAuditor().audit(manifest, registry, version="2022.1")

    assert result.passed is True
    assert result.reflected_count == 144
    assert result.inventory_covered_count == 144
    assert result.behavioral_covered_count == 0
    assert result.deferred_count == 144
    assert result.categories["core.object"] > 0


def test_audit_fails_when_reflected_topic_is_neither_behavioral_nor_deferred() -> None:
    manifest = {
        "functions": [{"uri": "ak.wwise.core.getInfo"}],
        "topics": [{"uri": "ak.wwise.ui.selectionChanged"}],
    }
    registry = DeferredRegistry.from_mappings([_valid_deferred_payload("ak.wwise.core.getInfo")])

    result = ApiCoverageAuditor().audit(manifest, registry, version="2022.1")

    assert result.passed is False
    assert result.inventory_covered_count == 2
    assert result.behavioral_covered_count == 0
    assert result.deferred_count == 1
    assert result.missing == ("ak.wwise.ui.selectionChanged",)
    with pytest.raises(RuntimeError, match="Missing coverage for ak.wwise.ui.selectionChanged"):
        result.raise_for_failures()


def test_behavioral_record_counts_separately_from_inventory_coverage() -> None:
    manifest = {"functions": [{"uri": "ak.wwise.core.getInfo"}], "topics": []}
    behavior = BehavioralCoverageRecord(
        uri="ak.wwise.core.getInfo",
        version="2022.1",
        category="core",
        evidence_source="tests/unit/test_api_coverage_audit.py::fixture",
        test_name="test_get_info_behavior",
    )

    result = ApiCoverageAuditor().audit(manifest, DeferredRegistry(), [behavior], version="2022.1")

    assert result.passed is True
    assert result.inventory_covered_count == 1
    assert result.behavioral_covered_count == 1
    assert result.deferred_count == 0


def test_deferred_entry_with_wrong_category_fails_usefully() -> None:
    manifest = {"functions": [{"uri": "ak.wwise.core.getInfo"}], "topics": []}
    payload = _valid_deferred_payload("ak.wwise.core.getInfo")
    payload["category"] = "freeform-wrong-category"
    registry = DeferredRegistry.from_mappings([payload])

    result = ApiCoverageAuditor().audit(manifest, registry, version="2022.1")

    assert result.passed is False
    assert result.invalid == (
        "Deferred entry ak.wwise.core.getInfo category 'freeform-wrong-category' != deterministic 'core'",
    )


def test_audit_rejects_unknown_deferred_entries() -> None:
    manifest = {"functions": [{"uri": "ak.wwise.core.getInfo"}], "topics": []}
    registry = DeferredRegistry.from_mappings(
        [
            _valid_deferred_payload("ak.wwise.core.getInfo"),
            _valid_deferred_payload("ak.wwise.core.getProjectInfo"),
        ]
    )

    result = ApiCoverageAuditor().audit(manifest, registry, version="2022.1")

    assert result.passed is False
    assert result.invalid == (
        "Deferred entry ak.wwise.core.getProjectInfo is not present in reflected manifest inventory",
    )


def test_manifest_shape_errors_fail_before_any_uri_can_be_silently_skipped() -> None:
    with pytest.raises(ValueError, match="missing required sections: functions, topics"):
        ApiCoverageAuditor().audit({}, DeferredRegistry())
    with pytest.raises(ValueError, match="missing required sections: topics"):
        ApiCoverageAuditor().audit({"functions": []}, DeferredRegistry())
    with pytest.raises(ValueError, match="at least one reflected"):
        ApiCoverageAuditor().audit({"functions": [], "topics": []}, DeferredRegistry())
    with pytest.raises(ValueError, match="function section must be a list"):
        ApiCoverageAuditor().audit({"functions": {}, "topics": []}, DeferredRegistry())
    with pytest.raises(ValueError, match="missing uri"):
        ApiCoverageAuditor().audit({"functions": [{"name": "missing"}], "topics": []}, DeferredRegistry())


def test_audit_rejects_behavioral_and_deferred_overlap() -> None:
    manifest = {"functions": [{"uri": "ak.wwise.core.getInfo"}], "topics": []}
    registry = DeferredRegistry.from_mappings([_valid_deferred_payload("ak.wwise.core.getInfo")])
    behavior = BehavioralCoverageRecord(
        uri="ak.wwise.core.getInfo",
        version="2022.1",
        category="core",
        evidence_source="tests/unit/test_api_coverage_audit.py::fixture",
        test_name="test_get_info_behavior",
    )

    result = ApiCoverageAuditor().audit(manifest, registry, [behavior], version="2022.1")

    assert result.passed is False
    assert result.invalid == ("URI ak.wwise.core.getInfo has both behavioral coverage and a deferred entry",)


def test_phase2_statuses_are_exclusive() -> None:
    manifest = {"functions": [{"uri": "ak.wwise.core.getInfo"}], "topics": []}
    status = Phase2CoverageStatusRecord(
        uri="ak.wwise.core.getInfo",
        version="2022.1",
        category="core",
        inventory_coverage="reflected-schema-ok",
        achieved_statuses=("live-smoke-tested", "still-deferred-with-evidence"),
        evidence_class="live_behavioral_waapi",
        future_review_trigger="Review when live smoke evidence changes.",
    )

    result = ApiCoverageAuditor().audit(manifest, DeferredRegistry(), version="2022.1", phase2_status_records=[status])

    assert result.passed is False
    assert result.invalid == (
        "Phase 2 coverage record ak.wwise.core.getInfo live status cannot overlap with still-deferred",
    )


def test_conformance_only_phase2_status_requires_policy_and_never_counts_as_behavior() -> None:
    manifest = {"functions": [{"uri": "ak.wwise.core.transport.create"}], "topics": []}
    status = Phase2CoverageStatusRecord(
        uri="ak.wwise.core.transport.create",
        version="2022.1",
        category="core.transport",
        inventory_coverage="reflected-schema-ok",
        achieved_status="conformance-only-skip",
        evidence_class="conformance_only_skip",
        user_approved_rationale="User approved conformance-only route/schema coverage without behavior claim.",
        future_review_trigger="Review when a deterministic transport playback fixture can prove behavior.",
    )

    result = ApiCoverageAuditor().audit(manifest, DeferredRegistry(), version="2022.1", phase2_status_records=[status])

    assert result.passed is True
    assert result.behavioral_covered_count == 0
    assert result.live_behavioral_covered_count == 0
    assert result.status_counts == {"conformance-only-skip": 1}


def test_conformance_only_phase2_status_rejects_missing_user_policy() -> None:
    manifest = {"functions": [{"uri": "ak.wwise.core.transport.create"}], "topics": []}
    status = Phase2CoverageStatusRecord(
        uri="ak.wwise.core.transport.create",
        version="2022.1",
        category="core.transport",
        inventory_coverage="reflected-schema-ok",
        achieved_status="conformance-only-skip",
        evidence_class="conformance_only_skip",
    )

    result = ApiCoverageAuditor().audit(manifest, DeferredRegistry(), version="2022.1", phase2_status_records=[status])

    assert result.passed is False
    assert result.invalid == (
        "Phase 2 coverage record ak.wwise.core.transport.create status 'conformance-only-skip' missing: "
        "user_approved_rationale, future_review_trigger",
    )


def test_live_phase2_status_requires_evidence_class() -> None:
    manifest = {"functions": [{"uri": "ak.wwise.core.object.create"}], "topics": []}
    status = Phase2CoverageStatusRecord(
        uri="ak.wwise.core.object.create",
        version="2022.1",
        category="core.object",
        inventory_coverage="reflected-schema-ok",
        achieved_status="sandbox-mutating-tested",
        evidence_path=".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-7-object-mutation.md",
        evidence_command="python -m pytest tests/destructive/test_project_mutation_sandbox.py -q",
    )

    result = ApiCoverageAuditor().audit(manifest, DeferredRegistry(), version="2022.1", phase2_status_records=[status])

    assert result.passed is False
    assert result.invalid == (
        "Phase 2 coverage record ak.wwise.core.object.create status 'sandbox-mutating-tested' missing: evidence_class",
    )


def test_still_deferred_phase2_status_requires_evidence() -> None:
    manifest = {"functions": [{"uri": "ak.wwise.core.soundbank.processDefinitionFiles"}], "topics": []}
    status = Phase2CoverageStatusRecord(
        uri="ak.wwise.core.soundbank.processDefinitionFiles",
        version="2022.1",
        category="core.soundbank",
        inventory_coverage="reflected-schema-ok",
        achieved_status="still-deferred-with-evidence",
    )

    result = ApiCoverageAuditor().audit(manifest, DeferredRegistry(), version="2022.1", phase2_status_records=[status])

    assert result.passed is False
    assert result.invalid == (
        "Phase 2 coverage record ak.wwise.core.soundbank.processDefinitionFiles status "
        "'still-deferred-with-evidence' missing: evidence_path, evidence_command, evidence_class",
    )


def test_still_deferred_phase2_status_requires_review_trigger() -> None:
    manifest = {"functions": [{"uri": "ak.wwise.core.soundbank.processDefinitionFiles"}], "topics": []}
    status = Phase2CoverageStatusRecord(
        uri="ak.wwise.core.soundbank.processDefinitionFiles",
        version="2022.1",
        category="core.soundbank",
        inventory_coverage="reflected-schema-ok",
        achieved_status="still-deferred-with-evidence",
        evidence_path=".sisyphus/evidence/wwise-waapi-deferred-reevaluation/task-6-process-definition-files.md",
        evidence_command="python -m pytest tests/destructive/test_soundbank_audio_sandbox.py -q",
        evidence_class="still_deferred_with_evidence",
    )

    result = ApiCoverageAuditor().audit(manifest, DeferredRegistry(), version="2022.1", phase2_status_records=[status])

    assert result.passed is False
    assert result.invalid == (
        "Phase 2 coverage record ak.wwise.core.soundbank.processDefinitionFiles status "
        "'still-deferred-with-evidence' missing: future_review_trigger",
    )


def test_deferred_entry_with_wrong_risk_level_fails_usefully() -> None:
    manifest = {"functions": [{"uri": "ak.wwise.debug.testCrash"}], "topics": []}
    payload = _valid_deferred_payload("ak.wwise.debug.testCrash")
    payload["risk_level"] = "low"
    registry = DeferredRegistry.from_mappings([payload])

    result = ApiCoverageAuditor().audit(manifest, registry, version="2022.1")

    assert result.passed is False
    assert result.invalid == ("Deferred entry ak.wwise.debug.testCrash risk_level 'low' != deterministic 'high'",)


def test_behavioral_record_reports_non_string_fields_as_missing() -> None:
    record = BehavioralCoverageRecord(
        uri="ak.wwise.core.getInfo",
        version="2022.1",
        category="core",
        evidence_source="tests/unit/test_api_coverage_audit.py::fixture",
        test_name="test_get_info_behavior",
    )
    object.__setattr__(record, "test_name", None)

    with pytest.raises(ValueError, match="missing: test_name"):
        record.validate()


def _valid_deferred_payload(uri: str, item_type: str = "function") -> dict[str, str]:
    classification = ApiClassifier().classify(uri, item_type)
    return {
        "behavioral_coverage": "deferred",
        "blocking_condition": "Requires live fixture before behavioral execution can be asserted.",
        "category": classification.category,
        "date": "2026-04-30",
        "evidence_source": "resources/manifest/2022.1/functions.json + resources/manifest/2022.1/schemas.json",
        "inventory_coverage": "reflected-schema-ok",
        "item_type": item_type,
        "owner_follow_up": "Task 7 behavioral coverage implementation.",
        "reason": "Inventory/schema evidence exists but behavioral coverage is deferred.",
        "review_trigger": "When behavioral tests or manifest inventory change.",
        "risk_level": classification.risk_level,
        "substitute_test": "Inventory/schema validation only; not behavioral coverage.",
        "uri": uri,
        "version": "2022.1",
    }
