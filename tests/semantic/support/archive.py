"""Archive records for OpenCode semantic WAAPI batch scenarios."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_ARCHIVE_ROOT = Path(".sisyphus") / "evidence" / "waapi-opencode-semantic-runs"
ALLOWED_VERDICTS = frozenset({"pass", "fail", "skip", "blocked"})
ARCHIVE_SCHEMA_VERSION = 1
EXCLUDED_ARTIFACT_CLASSES = (
    "sandbox_project_contents",
    ".venv",
    "__pycache__",
    "caches",
    "full_opencode_databases",
    "wholesale_logs",
)


class SemanticArchiveError(ValueError):
    """Raised when a semantic archive record would be invalid."""


def build_semantic_archive_record(
    *,
    scenario_id: str,
    prompt: str,
    expected_assertions: Sequence[str],
    assistant_output: str,
    verdict: str,
    bug_classes: Sequence[str] = (),
    wwise_version: str,
    waapi_host: str,
    waapi_port: int,
    opencode_session_id: str,
    sandbox_metadata_path: str | Path | None,
    dispatcher_evidence_paths: Sequence[str | Path] = (),
    evidence_references: Sequence[str | Path] = (),
    command_line: Sequence[str] = (),
    command_exit_status: int | None = None,
    timestamps: Mapping[str, str | None] | None = None,
    failure_notes: Sequence[str] = (),
    run_id: str | None = None,
    archive_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a stable machine-readable semantic scenario archive record."""

    normalized_verdict = _require_verdict(verdict)
    safe_scenario_id = _require_non_empty("scenario_id", scenario_id)
    selected_run_id = _require_non_empty("run_id", run_id or opencode_session_id or "manual")
    return {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "run_id": selected_run_id,
        "scenario_id": safe_scenario_id,
        "prompt": str(prompt),
        "expected_assertions": [str(assertion) for assertion in expected_assertions],
        "assistant_output": str(assistant_output),
        "verdict": normalized_verdict,
        "bug_classes": [str(bug_class) for bug_class in bug_classes],
        "wwise_version": str(wwise_version),
        "waapi_host": str(waapi_host),
        "waapi_port": int(waapi_port),
        "opencode_session_id": str(opencode_session_id),
        "sandbox_metadata_path": _path_string(sandbox_metadata_path),
        "dispatcher_evidence_paths": [_path_string(path) for path in dispatcher_evidence_paths],
        "evidence_references": [_path_string(path) for path in evidence_references],
        "command_line": [str(part) for part in command_line],
        "command_exit_status": command_exit_status,
        "timestamps": _timestamps(timestamps),
        "failure_notes": [str(note) for note in failure_notes],
        "archive_path": _path_string(archive_path),
        "archive_policy": {
            "copies_artifacts": False,
            "references_only": True,
            "excluded_artifact_classes": list(EXCLUDED_ARTIFACT_CLASSES),
        },
    }


def write_semantic_archive_record(
    *,
    archive_root: str | Path | None = None,
    **record_kwargs: Any,
) -> Path:
    """Write one semantic scenario archive record and return its JSON path."""

    root = _archive_root(archive_root)
    scenario_id = _require_non_empty("scenario_id", str(record_kwargs.get("scenario_id", "")))
    run_id = _require_non_empty(
        "run_id",
        str(record_kwargs.get("run_id") or record_kwargs.get("opencode_session_id") or "manual"),
    )
    record_path = root / _safe_path_part(run_id) / _safe_path_part(scenario_id) / "record.json"
    payload_kwargs = dict(record_kwargs)
    payload_kwargs["run_id"] = run_id
    payload_kwargs["archive_path"] = record_path
    record = build_semantic_archive_record(**payload_kwargs)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record_path


def _archive_root(archive_root: str | Path | None) -> Path:
    root = Path(archive_root) if archive_root is not None else DEFAULT_ARCHIVE_ROOT
    if root.is_absolute():
        return root.resolve(strict=False)
    return (Path.cwd() / root).resolve(strict=False)


def _require_verdict(verdict: str) -> str:
    normalized = str(verdict).strip().lower()
    if normalized not in ALLOWED_VERDICTS:
        allowed = ", ".join(sorted(ALLOWED_VERDICTS))
        raise SemanticArchiveError(f"verdict must be one of: {allowed}")
    return normalized


def _require_non_empty(name: str, value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise SemanticArchiveError(f"{name} must be a non-empty string")
    return normalized


def _path_string(path: str | Path | None) -> str:
    if path is None:
        return ""
    return str(path)


def _safe_path_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    return safe or "unknown"


def _timestamps(timestamps: Mapping[str, str | None] | None) -> dict[str, str | None]:
    payload = {
        "started_at": None,
        "completed_at": None,
        "archived_at": _utc_now(),
    }
    if timestamps:
        payload.update({str(key): value for key, value in timestamps.items()})
    return payload


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "ALLOWED_VERDICTS",
    "ARCHIVE_SCHEMA_VERSION",
    "DEFAULT_ARCHIVE_ROOT",
    "EXCLUDED_ARTIFACT_CLASSES",
    "SemanticArchiveError",
    "build_semantic_archive_record",
    "write_semantic_archive_record",
]
