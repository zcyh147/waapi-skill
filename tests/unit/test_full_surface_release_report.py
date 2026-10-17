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
        "construction_covered_lanes": 863,
        "function_lanes": 703,
        "topic_lanes": 160,
        "total_lanes": 863,
        "unique_function_uris": 175,
        "unique_topic_uris": 35,
    }
    assert report["construction_shapes"] == {
        "closed_read": 14,
        "draft": 116,
        "inline": 471,
        "topic": 160,
        "zero": 102,
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
        862 if expected_audit == "missing_continuations" else 863
    )


def test_release_report_reaches_closed_layout_reads_without_typed_codec_fallback(tmp_path):
    import shutil
    from wwise_waapi.schema_inventory import build_typed_request_surface
    skill = REPO_ROOT / 'skills/waapi-skill'
    target = tmp_path / 'skills/waapi-skill'
    for directory in ('scripts', 'wwise_waapi', 'resources'):
        shutil.copytree(skill / directory, target / directory,
                        ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))
    manifest = target / 'resources/manifest'
    surface = build_typed_request_surface(root=manifest)
    (manifest / 'typed-request-surface.json').write_text(DeterministicJsonWriter().dumps(surface), encoding='utf-8')
    report = build_full_surface_release_report(repo_root=tmp_path)
    assert report['audit']['missing_continuations'] == []
    assert report['audit']['missing_host_overlays'] == []
    assert report['construction_shapes']['closed_read'] == 14
