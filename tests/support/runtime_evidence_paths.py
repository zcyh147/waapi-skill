"""Localize historical evidence provenance into a current runtime root.

Committed test resources retain the path that identified their original
evidence.  Those portable POSIX strings are provenance, not writable host
paths.  Runtime tests choose their own ignored evidence root and reuse only the
declared filename after validating the provenance spelling.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


_PROVENANCE_PREFIXES = {
    (".sisyphus", "evidence"),
    (".waapi-skill-state", "evidence"),
}


class RuntimeEvidencePathError(ValueError):
    """Raised when a declared evidence provenance cannot be localized safely."""


def localize_runtime_evidence_path(
    evidence_root: Path,
    provenance_path: str,
    *,
    expected_filename: str | None = None,
) -> Path:
    """Return one file below ``evidence_root`` for a portable provenance path.

    Directory components from ``provenance_path`` are deliberately not reused:
    the caller owns the current output root.  This prevents a historical
    ``.sisyphus/evidence`` record from becoming an active write destination.
    """

    if not isinstance(provenance_path, str) or not provenance_path:
        raise RuntimeEvidencePathError("evidence provenance must be a non-empty string")
    if "\\" in provenance_path:
        raise RuntimeEvidencePathError(
            "evidence provenance must use portable POSIX separators"
        )

    logical = PurePosixPath(provenance_path)
    if (
        logical.as_posix() != provenance_path
        or logical.is_absolute()
        or ".." in logical.parts
        or len(logical.parts) < 3
        or tuple(logical.parts[:2]) not in _PROVENANCE_PREFIXES
        or logical.name in {"", ".", ".."}
    ):
        raise RuntimeEvidencePathError(
            f"evidence provenance is not a supported bounded path: {provenance_path!r}"
        )

    filename = logical.name
    if expected_filename is not None:
        expected = PurePosixPath(expected_filename)
        if (
            not expected_filename
            or "\\" in expected_filename
            or expected.is_absolute()
            or len(expected.parts) != 1
            or expected.name != expected_filename
        ):
            raise RuntimeEvidencePathError(
                f"expected evidence filename is unsafe: {expected_filename!r}"
            )
        if filename != expected_filename:
            raise RuntimeEvidencePathError(
                "evidence provenance filename does not match the case identity: "
                f"expected {expected_filename!r}, got {filename!r}"
            )

    expanded_root = evidence_root.expanduser()
    if not expanded_root.is_absolute():
        raise RuntimeEvidencePathError(
            f"runtime evidence root must be absolute: {evidence_root}"
        )
    root = expanded_root.resolve(strict=False)
    target = (root / filename).resolve(strict=False)
    if target == root or root not in target.parents:
        raise RuntimeEvidencePathError(
            f"localized evidence path escaped its runtime root: {target}"
        )
    return target


__all__ = [
    "RuntimeEvidencePathError",
    "localize_runtime_evidence_path",
]
