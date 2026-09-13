from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from tests.maintenance.generate_full_surface_release_report import (
    build_full_surface_release_report,
)
from wwise_waapi.manifest import DeterministicJsonWriter


REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs" / "full-surface-release-report.json"


def test_committed_full_surface_release_report_matches_packaged_truth() -> None:
    report = build_full_surface_release_report(repo_root=REPO_ROOT)

    assert report["contract"] == "waapi-skill.full-surface-release-report/v1"
    assert report["coverage"] == {
        "construction_covered_lanes": 830,
        "function_lanes": 670,
        "topic_lanes": 160,
        "total_lanes": 830,
        "unique_function_uris": 167,
        "unique_topic_uris": 35,
    }
    assert report["construction_shapes"] == {
        "draft": 114,
        "inline": 463,
        "topic": 160,
        "zero": 93,
    }
    assert report["audit"] == {
        "duplicate_lanes": [],
        "missing_continuations": [],
        "missing_host_overlays": [],
        "missing_lanes": [],
        "missing_semantic_overlays": [],
        "unexpected_lanes": [],
        "unknown_schema_keywords": [],
        "unresolved_references": [],
    }
    assert report["intentionally_blocked_field_occurrences"] == 79
    assert REPORT_PATH.read_text(encoding="utf-8") == DeterministicJsonWriter().dumps(
        report
    )


@pytest.mark.parametrize(
    ("policy_change", "expected_audit"),
    (
        (
            {"gateway_commands": ["request-schema --invented-bypass"]},
            "missing_continuations",
        ),
        (
            {"program_case": "not-a-real-program-case"},
            "missing_semantic_overlays",
        ),
    ),
)
def test_release_report_rejects_invented_continuation_or_semantic_binding(
    monkeypatch: pytest.MonkeyPatch,
    policy_change: dict[str, object],
    expected_audit: str,
) -> None:
    from tests.maintenance import generate_full_surface_release_report as generator

    original = generator.validate_packaged_typed_request_surface

    def tampered_surface(*, root: Path) -> dict[str, object]:
        payload = original(root=root)
        lanes = [dict(row) for row in payload["lanes"]]
        lane = dict(lanes[0])
        policy = dict(lane["execution_policy"])
        policy.update(policy_change)
        lane["execution_policy"] = MappingProxyType(policy)
        lanes[0] = lane
        return {**payload, "lanes": lanes}

    monkeypatch.setattr(
        generator,
        "validate_packaged_typed_request_surface",
        tampered_surface,
    )

    report = build_full_surface_release_report(repo_root=REPO_ROOT)

    assert len(report["audit"][expected_audit]) == 1
    assert report["coverage"]["construction_covered_lanes"] == (
        829 if expected_audit == "missing_continuations" else 830
    )
