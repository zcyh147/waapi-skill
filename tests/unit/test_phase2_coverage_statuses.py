from __future__ import annotations

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.api_coverage_audit import (  # pyright: ignore[reportMissingImports]
    ApiCoverageAuditor,
    Phase2CoverageStatusRecord,
)
from wwise_waapi.deferred_registry import DeferredRegistry  # pyright: ignore[reportMissingImports]


@pytest.mark.parametrize(
    ("status", "uri", "expected_behavioral", "expected_live_behavioral"),
    [
        ("fake-route-tested", "ak.wwise.core.getInfo", 1, 0),
        ("live-smoke-tested", "ak.wwise.core.getInfo", 1, 1),
        ("live-sandbox-tested", "ak.wwise.core.object.get", 1, 1),
        ("sandbox-mutating-tested", "ak.wwise.core.object.create", 1, 1),
        ("profiler-backed-tested", "ak.wwise.core.profiler.getCursorTime", 0, 0),
        ("soundengine-backed-tested", "ak.soundengine.getState", 1, 1),
        ("wrapper-only", "ak.wwise.ui.getSelectedObjects", 0, 0),
        ("skipped-approved", "ak.wwise.cli.verify", 0, 0),
        ("conformance-only-skip", "ak.wwise.core.transport.create", 0, 0),
        ("still-deferred-with-evidence", "ak.wwise.core.getProjectInfo", 0, 0),
    ],
)
def test_valid_phase2_statuses_are_auditable(
    status: str, uri: str, expected_behavioral: int, expected_live_behavioral: int
) -> None:
    record = _phase2_record(uri, status)

    result = ApiCoverageAuditor().audit(_manifest_for(uri), DeferredRegistry(), version="2022.1", phase2_status_records=[record])

    assert result.passed is True
    assert result.inventory_covered_count == 1
    assert result.phase2_status_covered_count == 1
    assert result.behavioral_covered_count == expected_behavioral
    assert result.live_behavioral_covered_count == expected_live_behavioral
    assert result.status_counts == {status: 1}


def test_invalid_phase2_status_is_rejected() -> None:
    result = _audit_status(_phase2_record("ak.wwise.core.getInfo", "live-tested"))

    assert result.passed is False
    assert result.invalid == ("Phase 2 coverage record ak.wwise.core.getInfo has invalid achieved status 'live-tested'",)


def test_multiple_phase2_achieved_statuses_are_rejected() -> None:
    record = _phase2_record("ak.wwise.core.getInfo", "fake-route-tested")
    record = Phase2CoverageStatusRecord(
        uri=record.uri,
        version=record.version,
        category=record.category,
        inventory_coverage=record.inventory_coverage,
        achieved_statuses=("fake-route-tested", "live-smoke-tested"),
        evidence_path=record.evidence_path,
        evidence_command=record.evidence_command,
    )

    result = _audit_status(record)

    assert result.passed is False
    assert result.invalid == ("Phase 2 coverage record ak.wwise.core.getInfo must declare exactly one achieved status",)


def test_live_phase2_status_requires_evidence_path_and_command() -> None:
    result = _audit_status(_phase2_record("ak.wwise.core.getInfo", "live-smoke-tested", evidence_path="", evidence_command=""))

    assert result.passed is False
    assert result.invalid == (
        "Phase 2 coverage record ak.wwise.core.getInfo status 'live-smoke-tested' missing: evidence_path, evidence_command",
    )


def test_live_phase2_status_cannot_overlap_with_still_deferred() -> None:
    record = Phase2CoverageStatusRecord(
        uri="ak.wwise.core.getInfo",
        version="2022.1",
        category="core",
        inventory_coverage="reflected-schema-ok",
        achieved_statuses=("live-sandbox-tested", "still-deferred-with-evidence"),
        evidence_path=".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/live.md",
        evidence_command="python -m pytest tests/live/test_example.py -q",
        future_review_trigger="Review when live sandbox fixture changes.",
    )

    result = _audit_status(record)

    assert result.passed is False
    assert result.invalid == (
        "Phase 2 coverage record ak.wwise.core.getInfo live status cannot overlap with still-deferred",
    )


@pytest.mark.parametrize("status", ["wrapper-only", "skipped-approved", "conformance-only-skip"])
def test_policy_approved_phase2_status_requires_rationale_and_review_trigger(status: str) -> None:
    uri_by_status = {
        "wrapper-only": "ak.wwise.ui.getSelectedObjects",
        "skipped-approved": "ak.wwise.cli.verify",
        "conformance-only-skip": "ak.wwise.core.transport.create",
    }
    uri = uri_by_status[status]
    result = _audit_status(_phase2_record(uri, status, user_approved_rationale="", future_review_trigger=""))

    assert result.passed is False
    assert result.invalid == (
        f"Phase 2 coverage record {uri} status {status!r} missing: user_approved_rationale, future_review_trigger",
    )


def test_wrapper_only_is_not_counted_as_behavioral_live_coverage() -> None:
    result = _audit_status(_phase2_record("ak.wwise.ui.getSelectedObjects", "wrapper-only"))

    assert result.passed is True
    assert result.behavioral_covered_count == 0
    assert result.live_behavioral_covered_count == 0
    assert result.phase2_status_covered_count == 1


def test_conformance_only_skip_is_not_counted_as_behavioral_or_live_behavioral() -> None:
    result = _audit_status(
        _phase2_record(
            "ak.wwise.core.transport.create",
            "conformance-only-skip",
            evidence_class="conformance_only_skip",
        )
    )

    assert result.passed is True
    assert result.behavioral_covered_count == 0
    assert result.live_behavioral_covered_count == 0
    assert result.status_counts == {"conformance-only-skip": 1}


@pytest.mark.parametrize(
    ("status", "evidence_class"),
    [
        ("live-sandbox-tested", "live_behavioral_waapi"),
        ("profiler-backed-tested", "live_behavioral_profiler"),
        ("conformance-only-skip", "conformance_only_skip"),
        ("still-deferred-with-evidence", "still_deferred_with_evidence"),
    ],
)
def test_phase21_evidence_classes_are_accepted_for_matching_statuses(status: str, evidence_class: str) -> None:
    record = _phase2_record("ak.wwise.core.transport.create", status, evidence_class=evidence_class)

    result = _audit_status(record)

    assert result.passed is True


def test_phase21_evidence_class_must_match_status() -> None:
    result = _audit_status(
        _phase2_record(
            "ak.wwise.core.transport.create",
            "conformance-only-skip",
            evidence_class="live_behavioral_waapi",
        )
    )

    assert result.passed is False
    assert result.invalid == (
        "Phase 2 coverage record ak.wwise.core.transport.create status 'conformance-only-skip' "
        "requires evidence class 'conformance_only_skip'",
    )


def _audit_status(record: Phase2CoverageStatusRecord):
    return ApiCoverageAuditor().audit(
        _manifest_for(record.uri), DeferredRegistry(), version="2022.1", phase2_status_records=[record]
    )


def _manifest_for(uri: str) -> dict[str, list[dict[str, str]]]:
    return {"functions": [{"uri": uri}], "topics": []}


def _phase2_record(
    uri: str,
    status: str,
    *,
    evidence_path: str = ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/status.md",
    evidence_command: str = "python -m pytest tests/unit/test_phase2_coverage_statuses.py -q",
    user_approved_rationale: str = "User approved non-live Phase 2 coverage for this category.",
    future_review_trigger: str = "Review when Phase 2 coverage policy or reflected inventory changes.",
    evidence_class: str = "",
) -> Phase2CoverageStatusRecord:
    return Phase2CoverageStatusRecord(
        uri=uri,
        version="2022.1",
        category=_category_for(uri),
        inventory_coverage="reflected-schema-ok",
        achieved_status=status,
        evidence_path=evidence_path if status_requires_evidence(status) else "",
        evidence_command=evidence_command if status_requires_evidence(status) else "",
        evidence_class=evidence_class,
        user_approved_rationale=user_approved_rationale
        if status in {"wrapper-only", "skipped-approved", "conformance-only-skip"}
        else "",
        future_review_trigger=future_review_trigger
        if status in {"wrapper-only", "skipped-approved", "conformance-only-skip", "still-deferred-with-evidence"}
        else "",
    )


def status_requires_evidence(status: str) -> bool:
    return status in {
        "live-smoke-tested",
        "live-sandbox-tested",
        "sandbox-mutating-tested",
        "profiler-backed-tested",
        "soundengine-backed-tested",
    }


def _category_for(uri: str) -> str:
    if uri.startswith("ak.soundengine."):
        return "soundengine"
    parts = uri.split(".")
    return ".".join(parts[2:-1]) or "wwise"
