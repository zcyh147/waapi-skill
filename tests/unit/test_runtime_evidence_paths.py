from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.runtime_evidence_paths import (  # pyright: ignore[reportMissingImports]
    RuntimeEvidencePathError,
    localize_runtime_evidence_path,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
WAQL_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "resource-evidence" / "waql"
CAPABILITY_RESOURCE_ROOT = (
    REPO_ROOT / "tests" / "destructive" / "support" / "resources" / "capabilities"
)
VERSIONED_EVIDENCE_ROOTS = {
    "2021.1": "wwise-2021-waapi-integration-coverage",
    "2022.1": "wwise-2022-test-parity",
    "2023.1": "wwise-2023-test-parity",
    "2024.1": "wwise-2024-waapi-integration-coverage",
    "2025.1": "wwise-2025-waapi-integration-coverage",
}


@pytest.mark.parametrize("version", tuple(VERSIONED_EVIDENCE_ROOTS))
def test_versioned_waql_provenance_localizes_to_current_runtime_root(
    tmp_path: Path,
    version: str,
) -> None:
    matrix = json.loads(
        (WAQL_FIXTURE_ROOT / version / "object-get-live-matrix.json").read_text(
            encoding="utf-8"
        )
    )
    runtime_root = (
        tmp_path
        / ".waapi-skill-state"
        / "evidence"
        / VERSIONED_EVIDENCE_ROOTS[version]
        / "live-read-only"
    )

    for case in matrix["live_cases"]:
        provenance = case["evidence_path"]
        assert provenance.startswith(".sisyphus/evidence/")
        target = localize_runtime_evidence_path(
            runtime_root,
            provenance,
            expected_filename=f"{case['id']}.json",
        )
        assert target == (runtime_root / f"{case['id']}.json").resolve()
        assert ".sisyphus" not in target.parts


@pytest.mark.parametrize(
    "provenance",
    (
        "relative/evidence.json",
        "/absolute/evidence.json",
        ".sisyphus/evidence/../escape.json",
        "./.sisyphus/evidence/normalized.json",
        ".sisyphus/evidence/repeated//separator.json",
        ".sisyphus/evidence/dot/./segment.json",
        "C:/temp/evidence.json",
        r"C:\temp\evidence.json",
        r"\\server\share\evidence.json",
        ".sisyphus/evidence/mixed\\evidence.json",
    ),
)
def test_runtime_evidence_localization_rejects_untrusted_path_spellings(
    tmp_path: Path,
    provenance: str,
) -> None:
    with pytest.raises(RuntimeEvidencePathError):
        localize_runtime_evidence_path(tmp_path / "evidence", provenance)


def test_runtime_evidence_localization_binds_provenance_to_case_filename(
    tmp_path: Path,
) -> None:
    provenance = ".sisyphus/evidence/history/actual.json"

    with pytest.raises(RuntimeEvidencePathError, match="does not match"):
        localize_runtime_evidence_path(
            tmp_path / "evidence",
            provenance,
            expected_filename="different.json",
        )
    with pytest.raises(RuntimeEvidencePathError, match="unsafe"):
        localize_runtime_evidence_path(
            tmp_path / "evidence",
            provenance,
            expected_filename="../actual.json",
        )


def test_current_state_provenance_is_accepted_without_becoming_the_output_root(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "owned" / "evidence"
    target = localize_runtime_evidence_path(
        runtime_root,
        ".waapi-skill-state/evidence/previous/run.json",
    )

    assert target == (runtime_root / "run.json").resolve()


def test_runtime_evidence_root_must_be_caller_owned_absolute_path() -> None:
    with pytest.raises(RuntimeEvidencePathError, match="root must be absolute"):
        localize_runtime_evidence_path(
            Path("relative-evidence"),
            ".sisyphus/evidence/history/run.json",
        )


def test_all_committed_historical_evidence_paths_are_portable_provenance(
    tmp_path: Path,
) -> None:
    provenance_rows: list[tuple[Path, str]] = []
    for root in (WAQL_FIXTURE_ROOT, CAPABILITY_RESOURCE_ROOT):
        for resource_path in sorted(root.rglob("*.json")):
            document = json.loads(resource_path.read_text(encoding="utf-8"))
            provenance_rows.extend(
                (resource_path, value)
                for value in _iter_evidence_paths(document)
                if value.startswith(".sisyphus/evidence/")
            )

    assert provenance_rows
    runtime_root = tmp_path / ".waapi-skill-state" / "evidence" / "localized"
    for resource_path, provenance in provenance_rows:
        target = localize_runtime_evidence_path(runtime_root, provenance)
        assert target.parent == runtime_root.resolve(), resource_path
        assert target.name == PurePosixPath(provenance).name, resource_path
        assert ".sisyphus" not in target.parts, resource_path


def _iter_evidence_paths(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "evidence_path" and isinstance(child, str):
                yield child
            else:
                yield from _iter_evidence_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_evidence_paths(child)
