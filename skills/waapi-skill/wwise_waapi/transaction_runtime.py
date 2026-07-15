"""Runtime guards and immutable artifacts for closed WAAPI transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_sha256, sha256_hex
from .operation_registry import (
    OperationRequest,
    PreparedOperation,
    ReadCall,
    parse_operation_request,
    prepare_operation,
)


TRANSACTION_PREVIEW_CONTRACT = "waapi-skill.transaction-preview/v1"
PROJECT_GUARD_CONTRACT = "waapi-skill.project-guard/v1"
RUNTIME_GUARD_CONTRACT = "waapi-skill.runtime-guard/v1"
DEFAULT_PREVIEW_TTL_SECONDS = 30 * 60


class TransactionGuardError(RuntimeError):
    """The live project, packaged runtime, or preview lifetime no longer matches."""

    def __init__(self, error_code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), "details": dict(self.details)}


@dataclass(frozen=True, slots=True)
class TransactionArtifact:
    request: OperationRequest
    prepared_operation: PreparedOperation
    project_guard: Mapping[str, Any]
    runtime_guard: Mapping[str, Any]
    created_at: str
    expires_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": TRANSACTION_PREVIEW_CONTRACT,
            "request": self.request.as_dict(),
            "prepared_operation": self.prepared_operation.as_dict(),
            "project_guard": dict(self.project_guard),
            "runtime_guard": dict(self.runtime_guard),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "execution_policy": {
                "confirmation_required": True,
                "automatic_retry_allowed": False,
                "revalidate_project_guard": True,
                "revalidate_runtime_guard": True,
                "revalidate_resolved_roles": True,
                "post_execution_verification_required": True,
            },
        }


def build_project_guard(
    *,
    endpoint: Mapping[str, Any],
    version: str,
    live_info: Mapping[str, Any],
    project: Mapping[str, Any],
) -> dict[str, Any]:
    body = {
        "endpoint": {
            key: endpoint.get(key)
            for key in ("host", "port", "url")
            if endpoint.get(key) is not None
        },
        "version": version,
        "wwise": {
            "displayName": live_info.get("displayName"),
            "isCommandLine": live_info.get("isCommandLine"),
            "version": live_info.get("version"),
        },
        "project": {
            key: project.get(key)
            for key in ("id", "name", "path", "projectPath", "filePath")
            if project.get(key) is not None
        },
    }
    return {"contract": PROJECT_GUARD_CONTRACT, **body, "fingerprint": canonical_sha256(body)}


def build_runtime_guard(skill_root: Path, version: str) -> dict[str, Any]:
    root = skill_root.resolve()
    files: dict[str, str] = {}
    for relative in _runtime_files(root, version):
        path = root / relative
        if not path.is_file():
            raise TransactionGuardError(
                "RUNTIME_FILE_MISSING",
                f"Required packaged runtime file is missing: {relative}",
                details={"relative_path": relative, "skill_root": str(root)},
            )
        files[relative] = sha256_hex(path.read_bytes())
    body = {"version": version, "files": files}
    return {"contract": RUNTIME_GUARD_CONTRACT, **body, "fingerprint": canonical_sha256(body)}


def build_transaction_artifact(
    request_payload: Mapping[str, Any],
    *,
    live_version: str,
    read_call: ReadCall,
    project_guard: Mapping[str, Any],
    skill_root: Path,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_PREVIEW_TTL_SECONDS,
) -> TransactionArtifact:
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be greater than zero")
    request = parse_operation_request(request_payload, expected_version=live_version)
    prepared = prepare_operation(request, read_call=read_call)
    created = _utc(now)
    expires = created + timedelta(seconds=ttl_seconds)
    return TransactionArtifact(
        request=request,
        prepared_operation=prepared,
        project_guard=dict(project_guard),
        runtime_guard=build_runtime_guard(skill_root, request.version),
        created_at=_timestamp(created),
        expires_at=_timestamp(expires),
    )


def validate_transaction_guards(
    artifact: Mapping[str, Any],
    *,
    current_project_guard: Mapping[str, Any],
    skill_root: Path,
    now: datetime | None = None,
    check_expiry: bool = True,
) -> Mapping[str, Any]:
    if artifact.get("contract") != TRANSACTION_PREVIEW_CONTRACT:
        raise TransactionGuardError("INVALID_PREVIEW", "Transaction preview contract is missing or unsupported.")
    request = artifact.get("request")
    if not isinstance(request, Mapping) or not isinstance(request.get("version"), str):
        raise TransactionGuardError("INVALID_PREVIEW", "Transaction preview lacks a versioned request.")
    stored_project = artifact.get("project_guard")
    stored_runtime = artifact.get("runtime_guard")
    if not isinstance(stored_project, Mapping) or not isinstance(stored_runtime, Mapping):
        raise TransactionGuardError("INVALID_PREVIEW", "Transaction preview lacks project/runtime guards.")
    expires_at = artifact.get("expires_at")
    if not isinstance(expires_at, str):
        raise TransactionGuardError("INVALID_PREVIEW", "Transaction preview lacks expires_at.")
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransactionGuardError("INVALID_PREVIEW", "Transaction preview expires_at is invalid.") from exc
    current_time = _utc(now)
    if check_expiry and current_time > expires:
        raise TransactionGuardError(
            "PREVIEW_EXPIRED",
            "Confirmed preview has expired; create and review a fresh preview.",
            details={"expires_at": expires_at, "current_time": _timestamp(current_time)},
        )

    stored_project_fingerprint = stored_project.get("fingerprint")
    current_project_fingerprint = current_project_guard.get("fingerprint")
    if stored_project_fingerprint != current_project_fingerprint:
        raise TransactionGuardError(
            "PROJECT_GUARD_MISMATCH",
            "Live endpoint/project no longer matches the confirmed preview.",
            details={
                "expected_fingerprint": stored_project_fingerprint,
                "actual_fingerprint": current_project_fingerprint,
                "expected": dict(stored_project),
                "actual": dict(current_project_guard),
            },
        )

    current_runtime = build_runtime_guard(skill_root, str(request["version"]))
    if stored_runtime.get("fingerprint") != current_runtime.get("fingerprint"):
        raise TransactionGuardError(
            "RUNTIME_GUARD_MISMATCH",
            "Packaged builders, schemas, or transaction runtime changed after preview.",
            details={
                "expected_fingerprint": stored_runtime.get("fingerprint"),
                "actual_fingerprint": current_runtime.get("fingerprint"),
            },
        )
    return {
        "ok": True,
        "status": "valid",
        "project_guard_fingerprint": current_project_fingerprint,
        "runtime_guard_fingerprint": current_runtime["fingerprint"],
        "expires_at": expires_at,
    }


def _runtime_files(root: Path, version: str) -> tuple[str, ...]:
    package_root = root / "wwise_waapi"
    if not package_root.is_dir():
        raise TransactionGuardError(
            "RUNTIME_FILE_MISSING",
            "Required packaged runtime directory is missing: wwise_waapi",
            details={"relative_path": "wwise_waapi", "skill_root": str(root)},
        )
    # Bind the complete packaged Python implementation, not a hand-maintained
    # subset. New operation builders or helper modules must never become an
    # un-fingerprinted execution dependency after a preview was confirmed.
    scripts_root = root / "scripts"
    common = tuple(
        sorted(path.relative_to(root).as_posix() for path in package_root.rglob("*.py") if path.is_file())
    ) + tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in scripts_root.glob("*.py")
            if path.is_file() and path.name in {"gateway.py", "run.py"}
        )
    )
    versioned = (
        f"resources/manifest/{version}/manifest.json",
        f"resources/manifest/{version}/functions.json",
        f"resources/manifest/{version}/schemas.json",
        f"resources/manifest/{version}/topics.json",
        f"resources/semantic/{version}/source_notes.json",
    )
    return common + versioned


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return current.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = [
    "DEFAULT_PREVIEW_TTL_SECONDS",
    "PROJECT_GUARD_CONTRACT",
    "RUNTIME_GUARD_CONTRACT",
    "TRANSACTION_PREVIEW_CONTRACT",
    "TransactionArtifact",
    "TransactionGuardError",
    "build_project_guard",
    "build_runtime_guard",
    "build_transaction_artifact",
    "validate_transaction_guards",
]
