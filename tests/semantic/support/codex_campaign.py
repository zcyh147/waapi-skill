"""Immutable evidence primitives for resumable Codex semantic campaigns.

This module deliberately does not execute Codex or Wwise.  It supplies the
small trust core used by the campaign orchestrator: stable content hashing,
atomic JSON+digest files, immutable campaign configuration, append-only
attempt directories, sealed attempt manifests, and fail-closed unit
consolidation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence


CAMPAIGN_CONFIG_CONTRACT = "waapi-skill.codex-semantic-campaign-config/v1"
ATTEMPT_DESCRIPTOR_CONTRACT = "waapi-skill.codex-semantic-campaign-attempt/v1"
ATTEMPT_MANIFEST_CONTRACT = "waapi-skill.codex-semantic-attempt-manifest/v1"
ATTEMPT_LEDGER_CONTRACT = "waapi-skill.codex-semantic-attempt-ledger/v1"
CONSOLIDATED_CONTRACT = "waapi-skill.codex-semantic-consolidated-units/v1"

CAMPAIGN_CONFIG_FILE = "campaign-config.json"
ATTEMPT_DESCRIPTOR_FILE = "attempt.json"
ATTEMPT_MANIFEST_FILE = "attempt-manifest.json"
ATTEMPT_LEDGER_FILE = "attempt-ledger.json"
DIGEST_SUFFIX = ".sha256"

UNIT_STATUSES = ("PASS", "PENDING", "RETRYABLE", "FAIL", "BLOCKED")
OBSERVATION_STATUSES = frozenset({"PASS", "RETRYABLE", "FAIL", "BLOCKED"})
PHASE_STATUSES = frozenset({"PASS", "RETRYABLE", "FAIL", "BLOCKED"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_RE = re.compile(r"^attempt-(\d{6})$")


class CampaignEvidenceError(RuntimeError):
    """Campaign evidence is missing, mutable, malformed, or contradictory."""


def _is_windows_junction(path: Path) -> bool:
    if _path_reports_windows_junction(path):
        return True
    try:
        info = path.lstat()
    except OSError:
        return False
    return _stat_is_windows_reparse_point(info)


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic strict-JSON bytes without a trailing newline."""

    _require_string_json_keys(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CampaignEvidenceError(f"value is not strict JSON: {exc}") from exc
    return encoded.encode("utf-8")


def sha256_file(path: Path) -> str:
    """Hash one real regular file without following a symlink."""

    candidate = Path(path)
    digest = hashlib.sha256()
    _consume_real_regular_file(candidate, label="file", consume=digest.update)
    return digest.hexdigest()


def stable_tree_manifest(
    root: Path,
    *,
    exclude_names: Sequence[str] = (),
) -> tuple[dict[str, Any], ...]:
    """Describe a tree from content and semantic metadata, never mtime/ctime.

    Symlinks are recorded by their link target and are never followed.  The
    stricter attempt sealer below rejects symlinks entirely.
    """

    tree = _require_real_directory(root, label="tree root")
    excluded = frozenset(str(name) for name in exclude_names)
    rows: list[dict[str, Any]] = []

    def walk(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise CampaignEvidenceError(f"cannot scan tree directory {directory}: {exc}") from exc
        for entry in entries:
            if entry.name in excluded:
                continue
            path = Path(entry.path)
            relative = path.relative_to(tree).as_posix()
            _validate_relative_path(relative)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise CampaignEvidenceError(f"cannot stat tree entry {path}: {exc}") from exc
            if stat.S_ISLNK(info.st_mode):
                try:
                    target = os.readlink(path)
                except OSError as exc:
                    raise CampaignEvidenceError(f"cannot read symlink {path}: {exc}") from exc
                rows.append({"path": relative, "type": "symlink", "target": target})
            elif _is_windows_junction(path):
                raise CampaignEvidenceError(f"tree contains a Windows junction: {path}")
            elif stat.S_ISDIR(info.st_mode):
                rows.append(
                    {
                        "path": relative,
                        "type": "directory",
                        "executable": bool(info.st_mode & 0o111),
                    }
                )
                walk(path)
            elif stat.S_ISREG(info.st_mode):
                rows.append(
                    {
                        "path": relative,
                        "type": "file",
                        "executable": bool(info.st_mode & 0o111),
                        "size": info.st_size,
                        "sha256": sha256_file(path),
                    }
                )
            else:
                raise CampaignEvidenceError(f"unsupported tree entry type: {path}")

    walk(tree)
    return tuple(rows)


def stable_tree_sha256(root: Path, *, exclude_names: Sequence[str] = ()) -> str:
    return hashlib.sha256(
        canonical_json_bytes(stable_tree_manifest(root, exclude_names=exclude_names))
    ).hexdigest()


def atomic_write_json_with_digest(path: Path, payload: Any) -> str:
    """Atomically write strict JSON and a sibling SHA-256 attestation."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.is_symlink():
        raise CampaignEvidenceError(f"refusing to replace symlink: {destination}")
    digest_path = _digest_path(destination)
    if digest_path.exists() and digest_path.is_symlink():
        raise CampaignEvidenceError(f"refusing to replace digest symlink: {digest_path}")

    data = canonical_json_bytes(payload) + b"\n"
    digest = hashlib.sha256(data).hexdigest()
    _atomic_write_bytes(destination, data)
    _atomic_write_bytes(digest_path, (digest + "\n").encode("ascii"))
    return digest


def load_verified_json(path: Path) -> Any:
    """Load verified JSON from one no-follow read of each attested file.

    The exact source bytes used for the SHA-256 comparison are also the bytes
    parsed as JSON.  This avoids the prior hash-then-reopen TOCTOU window.
    """

    payload, _digest = _load_verified_json_and_digest(Path(path))
    return payload


def create_immutable_campaign_config(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    campaign_root = Path(root)
    campaign_root.mkdir(parents=True, exist_ok=True)
    if campaign_root.is_symlink() or _is_windows_junction(campaign_root) or not campaign_root.is_dir():
        raise CampaignEvidenceError(f"campaign root must be a real directory: {campaign_root}")
    config_path = campaign_root / CAMPAIGN_CONFIG_FILE
    ledger_path = campaign_root / ATTEMPT_LEDGER_FILE
    if (
        config_path.exists()
        or _digest_path(config_path).exists()
        or ledger_path.exists()
        or _digest_path(ledger_path).exists()
    ):
        raise CampaignEvidenceError(
            f"campaign config already exists and is immutable: {config_path}"
        )
    _require_string_json_keys(payload)
    if set(payload).intersection(
        {"contract", "campaign_id", "campaign_config_sha256"}
    ):
        raise CampaignEvidenceError(
            "campaign config payload may not override contract or campaign binding fields"
        )
    campaign_id = str(uuid.uuid4())
    document = {
        "contract": CAMPAIGN_CONFIG_CONTRACT,
        "campaign_id": campaign_id,
        **deepcopy(dict(payload)),
    }
    config_digest = atomic_write_json_with_digest(config_path, document)
    attempts_root = campaign_root / "attempts"
    try:
        attempts_root.mkdir()
    except FileExistsError:
        _require_real_directory(attempts_root, label="attempts root")
        if any(attempts_root.iterdir()):
            raise CampaignEvidenceError(
                f"cannot initialize campaign over non-empty attempts root: {attempts_root}"
            )
    atomic_write_json_with_digest(
        ledger_path,
        {
            "contract": ATTEMPT_LEDGER_CONTRACT,
            "campaign_id": campaign_id,
            "campaign_config_sha256": config_digest,
            "last_attempt_number": 0,
            "attempts": [],
        },
    )
    return document


def load_immutable_campaign_config(root: Path) -> dict[str, Any]:
    payload, _binding = _load_campaign_config_binding(Path(root))
    return payload


def create_attempt(campaign_root: Path) -> tuple[str, Path]:
    """Create the next append-only attempt directory.

    The attested campaign ledger must exactly match the directory inventory
    before allocation.  A deleted or unledgered attempt therefore blocks the
    campaign instead of allowing a number to be reused or skipped.
    """

    root = Path(campaign_root)
    _config, binding = _load_campaign_config_binding(root)
    ledger, attempt_roots = _verify_attempt_inventory(root, binding=binding)
    candidate = ledger["last_attempt_number"] + 1
    if candidate > 999_999:
        raise CampaignEvidenceError("campaign exhausted the six-digit attempt id space")
    attempt_id = f"attempt-{candidate:06d}"
    attempts_root = root / "attempts"
    attempt_root = attempts_root / attempt_id
    try:
        attempt_root.mkdir()
    except FileExistsError as exc:
        raise CampaignEvidenceError(
            f"next attempt number already exists outside the attested ledger: {attempt_root}"
        ) from exc
    descriptor_digest = atomic_write_json_with_digest(
        attempt_root / ATTEMPT_DESCRIPTOR_FILE,
        {
            "contract": ATTEMPT_DESCRIPTOR_CONTRACT,
            "campaign_id": binding["campaign_id"],
            "campaign_config_sha256": binding["campaign_config_sha256"],
            "attempt_id": attempt_id,
        },
    )
    updated_ledger = deepcopy(ledger)
    updated_ledger["last_attempt_number"] = candidate
    updated_ledger["attempts"].append(
        {"attempt_id": attempt_id, "descriptor_sha256": descriptor_digest}
    )
    atomic_write_json_with_digest(root / ATTEMPT_LEDGER_FILE, updated_ledger)
    if len(attempt_roots) + 1 != candidate:
        raise CampaignEvidenceError("internal attempt ledger sequence error")
    return attempt_id, attempt_root


def list_campaign_attempts(campaign_root: Path) -> tuple[Path, ...]:
    """Return the complete, ledger-verified append-only attempt inventory."""

    root = Path(campaign_root)
    _config, binding = _load_campaign_config_binding(root)
    _ledger, attempt_roots = _verify_attempt_inventory(root, binding=binding)
    return attempt_roots


def seal_attempt(
    attempt_root: Path,
    unit_observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    root = _require_real_directory(attempt_root, label="attempt root")
    if _ATTEMPT_RE.fullmatch(root.name) is None:
        raise CampaignEvidenceError(f"invalid attempt directory name: {root.name}")
    campaign_root = _campaign_root_for_attempt(root)
    _config, binding = _load_campaign_config_binding(campaign_root)
    _ledger, attempt_roots = _verify_attempt_inventory(campaign_root, binding=binding)
    if root not in attempt_roots:
        raise CampaignEvidenceError(f"attempt is not present in the attested ledger: {root}")
    descriptor, _descriptor_digest = _verify_attempt_descriptor(root, binding=binding)
    seal_path = root / ATTEMPT_MANIFEST_FILE
    if seal_path.exists() or _digest_path(seal_path).exists():
        raise CampaignEvidenceError(f"attempt is already sealed: {root}")
    observations = _normalize_unit_observations(unit_observations)
    manifest = {
        "contract": ATTEMPT_MANIFEST_CONTRACT,
        "campaign_id": descriptor["campaign_id"],
        "campaign_config_sha256": descriptor["campaign_config_sha256"],
        "attempt_id": root.name,
        "artifacts": list(_strict_artifact_manifest(root)),
        "unit_observations": observations,
    }
    atomic_write_json_with_digest(seal_path, manifest)
    return manifest


def verify_attempt_seal(attempt_root: Path) -> dict[str, Any]:
    root = _require_real_directory(attempt_root, label="attempt root")
    campaign_root = _campaign_root_for_attempt(root)
    _config, binding = _load_campaign_config_binding(campaign_root)
    _ledger, attempt_roots = _verify_attempt_inventory(campaign_root, binding=binding)
    if root not in attempt_roots:
        raise CampaignEvidenceError(f"attempt is not present in the attested ledger: {root}")
    descriptor, _descriptor_digest = _verify_attempt_descriptor(root, binding=binding)
    seal_path = root / ATTEMPT_MANIFEST_FILE
    payload = load_verified_json(seal_path)
    if not isinstance(payload, dict):
        raise CampaignEvidenceError("attempt manifest must be a JSON object")
    if set(payload) != {
        "contract",
        "campaign_id",
        "campaign_config_sha256",
        "attempt_id",
        "artifacts",
        "unit_observations",
    } or payload.get("contract") != ATTEMPT_MANIFEST_CONTRACT:
        raise CampaignEvidenceError("invalid attempt manifest contract")
    if payload.get("attempt_id") != root.name or _ATTEMPT_RE.fullmatch(root.name) is None:
        raise CampaignEvidenceError("attempt manifest is bound to the wrong directory")
    if (
        payload.get("campaign_id") != descriptor["campaign_id"]
        or payload.get("campaign_config_sha256")
        != descriptor["campaign_config_sha256"]
    ):
        raise CampaignEvidenceError("attempt manifest is bound to the wrong campaign config")
    expected_rows = _validate_artifact_rows(payload.get("artifacts"))
    actual_rows = _strict_artifact_manifest(root)
    if expected_rows != actual_rows:
        raise CampaignEvidenceError("attempt artifacts are missing, extra, or modified")
    _normalize_unit_observations(payload.get("unit_observations"))
    return payload


def consolidate_units(
    required_units: Mapping[str, Sequence[str]],
    attempt_manifests: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Consolidate sealed observations without cross-attempt phase splicing."""

    if not isinstance(required_units, Mapping):
        raise CampaignEvidenceError("required_units must be an object")
    if not isinstance(attempt_manifests, Sequence) or isinstance(
        attempt_manifests, (str, bytes)
    ):
        raise CampaignEvidenceError("attempt_manifests must be an array")
    required = _normalize_required_units(required_units)
    observations_by_unit: dict[str, list[dict[str, Any]]] = {
        unit_id: [] for unit_id in required
    }
    seen_attempts: set[str] = set()
    campaign_binding: tuple[str, str] | None = None

    for manifest_value in attempt_manifests:
        if not isinstance(manifest_value, Mapping):
            raise CampaignEvidenceError("attempt manifest must be an object")
        _require_string_json_keys(manifest_value)
        manifest = dict(manifest_value)
        if set(manifest) != {
            "contract",
            "campaign_id",
            "campaign_config_sha256",
            "attempt_id",
            "artifacts",
            "unit_observations",
        } or manifest.get("contract") != ATTEMPT_MANIFEST_CONTRACT:
            raise CampaignEvidenceError("cannot consolidate a non-attempt manifest")
        _validate_artifact_rows(manifest.get("artifacts"))
        manifest_binding = _normalize_campaign_binding(manifest)
        if campaign_binding is None:
            campaign_binding = manifest_binding
        elif manifest_binding != campaign_binding:
            raise CampaignEvidenceError("cannot consolidate manifests from different campaigns")
        attempt_id = manifest.get("attempt_id")
        if not isinstance(attempt_id, str) or _ATTEMPT_RE.fullmatch(attempt_id) is None:
            raise CampaignEvidenceError("attempt manifest has an invalid attempt_id")
        if attempt_id in seen_attempts:
            raise CampaignEvidenceError(f"duplicate attempt manifest: {attempt_id}")
        seen_attempts.add(attempt_id)
        normalized = _normalize_unit_observations(manifest.get("unit_observations"))
        seen_units: set[str] = set()
        for observation in normalized:
            unit_id = observation["unit_id"]
            if unit_id not in required:
                raise CampaignEvidenceError(f"attempt observes unknown unit: {unit_id}")
            if unit_id in seen_units:
                raise CampaignEvidenceError(
                    f"attempt {attempt_id} contains duplicate unit observation: {unit_id}"
                )
            seen_units.add(unit_id)
            effective = _effective_observation_status(
                observation,
                required_phases=required[unit_id],
            )
            observations_by_unit[unit_id].append(
                {
                    **deepcopy(observation),
                    "attempt_id": attempt_id,
                    "effective_status": effective,
                }
            )

    attempt_numbers = sorted(
        int(attempt_id.removeprefix("attempt-")) for attempt_id in seen_attempts
    )
    if attempt_numbers and attempt_numbers != list(range(1, attempt_numbers[-1] + 1)):
        raise CampaignEvidenceError(
            "attempt manifests are not a continuous prefix from attempt-000001"
        )

    units: dict[str, dict[str, Any]] = {}
    by_status: dict[str, list[str]] = {status: [] for status in UNIT_STATUSES}
    for unit_id, phases in required.items():
        observations = observations_by_unit[unit_id]
        effective_statuses = [item["effective_status"] for item in observations]
        if "BLOCKED" in effective_statuses:
            status = "BLOCKED"
        elif "FAIL" in effective_statuses:
            status = "FAIL"
        elif "PASS" in effective_statuses:
            status = "PASS"
        elif "RETRYABLE" in effective_statuses:
            status = "RETRYABLE"
        else:
            status = "PENDING"
        units[unit_id] = {
            "status": status,
            "required_phases": list(phases),
            "observations": observations,
        }
        by_status[status].append(unit_id)

    return {
        "contract": CONSOLIDATED_CONTRACT,
        "selected_unit_count": len(required),
        "units": units,
        "passed_unit_ids": by_status["PASS"],
        "pending_unit_ids": by_status["PENDING"],
        "retryable_unit_ids": by_status["RETRYABLE"],
        "failed_unit_ids": by_status["FAIL"],
        "blocked_unit_ids": by_status["BLOCKED"],
        "attempt_ids": sorted(seen_attempts),
        "all_selected_passed": bool(required) and len(by_status["PASS"]) == len(required),
    }


def _effective_observation_status(
    observation: Mapping[str, Any],
    *,
    required_phases: tuple[str, ...],
) -> str:
    status_value = observation["status"]
    phase_rows = observation["phases"]
    phase_names = tuple(row["phase"] for row in phase_rows)
    phase_statuses = tuple(row["status"] for row in phase_rows)
    if status_value == "PASS":
        if phase_names != required_phases or any(value != "PASS" for value in phase_statuses):
            return "BLOCKED"
        return "PASS"
    if status_value == "RETRYABLE":
        if not phase_rows:
            return "BLOCKED"
        if phase_names != required_phases[: len(phase_names)]:
            return "BLOCKED"
        if (
            phase_statuses[-1] != "RETRYABLE"
            or any(value != "PASS" for value in phase_statuses[:-1])
        ):
            return "BLOCKED"
        return "RETRYABLE"
    if status_value == "FAIL":
        if not phase_rows or phase_names != required_phases[: len(phase_names)]:
            return "BLOCKED"
        if phase_statuses[-1] != "FAIL" or any(
            value != "PASS" for value in phase_statuses[:-1]
        ):
            return "BLOCKED"
        return "FAIL"
    return "BLOCKED"


def _normalize_required_units(
    value: Mapping[str, Sequence[str]],
) -> dict[str, tuple[str, ...]]:
    _require_string_json_keys(value)
    normalized: dict[str, tuple[str, ...]] = {}
    for raw_unit_id, raw_phases in value.items():
        if not isinstance(raw_unit_id, str) or not raw_unit_id:
            raise CampaignEvidenceError("unit ids must be non-empty strings")
        unit_id = raw_unit_id
        if isinstance(raw_phases, (str, bytes)):
            raise CampaignEvidenceError(f"required phases must be a sequence for {unit_id}")
        phases = tuple(raw_phases)
        if (
            not phases
            or any(not isinstance(phase, str) or not phase for phase in phases)
            or len(set(phases)) != len(phases)
        ):
            raise CampaignEvidenceError(f"required phases are empty or duplicated for {unit_id}")
        normalized[unit_id] = phases
    if not normalized:
        raise CampaignEvidenceError("campaign must select at least one unit")
    return normalized


def _normalize_unit_observations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CampaignEvidenceError("unit_observations must be a JSON array")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise CampaignEvidenceError(f"unit observation {index} must be an object")
        _require_string_json_keys(raw)
        if set(raw) != {"unit_id", "status", "phases"}:
            raise CampaignEvidenceError(
                f"unit observation {index} requires exactly unit_id/status/phases"
            )
        row = deepcopy(dict(raw))
        unit_id = row.get("unit_id")
        status_value = row.get("status")
        phases_value = row.get("phases")
        if not isinstance(unit_id, str) or not unit_id:
            raise CampaignEvidenceError(f"unit observation {index} has invalid unit_id")
        if not isinstance(status_value, str) or status_value not in OBSERVATION_STATUSES:
            raise CampaignEvidenceError(f"unit observation {unit_id} has invalid status")
        if not isinstance(phases_value, Sequence) or isinstance(phases_value, (str, bytes)):
            raise CampaignEvidenceError(f"unit observation {unit_id} phases must be an array")
        phases: list[dict[str, str]] = []
        seen: set[str] = set()
        for phase_index, raw_phase in enumerate(phases_value):
            if not isinstance(raw_phase, Mapping):
                raise CampaignEvidenceError(
                    f"unit observation {unit_id} phase {phase_index} must be an object"
                )
            _require_string_json_keys(raw_phase)
            if set(raw_phase) != {"phase", "status"}:
                raise CampaignEvidenceError(
                    f"unit observation {unit_id} phase rows require exactly phase/status"
                )
            phase = raw_phase.get("phase")
            phase_status = raw_phase.get("status")
            if not isinstance(phase, str) or not phase or phase in seen:
                raise CampaignEvidenceError(f"unit observation {unit_id} has invalid phases")
            if not isinstance(phase_status, str) or phase_status not in PHASE_STATUSES:
                raise CampaignEvidenceError(
                    f"unit observation {unit_id} phase {phase} has invalid status"
                )
            seen.add(phase)
            phases.append({"phase": phase, "status": str(phase_status)})
        row["phases"] = phases
        normalized.append(row)
    canonical_json_bytes(normalized)
    return normalized


def _strict_artifact_manifest(root: Path) -> tuple[dict[str, Any], ...]:
    excluded = {ATTEMPT_MANIFEST_FILE, ATTEMPT_MANIFEST_FILE + DIGEST_SUFFIX}
    rows: list[dict[str, Any]] = []

    def fail_walk(error: OSError) -> None:
        raise CampaignEvidenceError(
            f"cannot walk attempt evidence under {root}: {error}"
        ) from error

    for directory, names, files in os.walk(
        root,
        topdown=True,
        onerror=fail_walk,
        followlinks=False,
    ):
        directory_path = Path(directory)
        for name in list(names):
            path = directory_path / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise CampaignEvidenceError(f"attempt evidence may not contain symlinks: {path}")
            if not stat.S_ISDIR(info.st_mode):
                raise CampaignEvidenceError(f"attempt evidence has non-directory entry: {path}")
        for name in files:
            path = directory_path / name
            relative = path.relative_to(root).as_posix()
            if relative in excluded:
                continue
            _validate_relative_path(relative)
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise CampaignEvidenceError(f"attempt evidence may not contain symlinks: {path}")
            if not stat.S_ISREG(info.st_mode):
                raise CampaignEvidenceError(
                    f"attempt artifact must be a real regular file: {path}"
                )
            rows.append(
                {
                    "path": relative,
                    "size": info.st_size,
                    "executable": bool(info.st_mode & 0o111),
                    "sha256": sha256_file(path),
                }
            )
    rows.sort(key=lambda row: row["path"])
    return tuple(rows)


def _validate_artifact_rows(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise CampaignEvidenceError("attempt artifacts must be an array")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {"path", "size", "executable", "sha256"}:
            raise CampaignEvidenceError("attempt artifact rows have an invalid shape")
        path = raw.get("path")
        size = raw.get("size")
        executable = raw.get("executable")
        digest = raw.get("sha256")
        if not isinstance(path, str):
            raise CampaignEvidenceError("attempt artifact path must be a string")
        _validate_relative_path(path)
        if path in seen or path in {ATTEMPT_MANIFEST_FILE, ATTEMPT_MANIFEST_FILE + DIGEST_SUFFIX}:
            raise CampaignEvidenceError(f"duplicate or reserved attempt artifact path: {path}")
        if type(size) is not int or size < 0 or type(executable) is not bool:
            raise CampaignEvidenceError(f"invalid attempt artifact metadata: {path}")
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise CampaignEvidenceError(f"invalid attempt artifact digest: {path}")
        seen.add(path)
        rows.append(
            {"path": path, "size": size, "executable": executable, "sha256": digest}
        )
    if [row["path"] for row in rows] != sorted(row["path"] for row in rows):
        raise CampaignEvidenceError("attempt artifact rows must be sorted")
    return tuple(rows)


def _validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise CampaignEvidenceError(f"unsafe relative path in evidence manifest: {value!r}")


def _load_campaign_config_binding(root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    campaign_root = _require_real_directory(root, label="campaign root")
    payload, config_digest = _load_verified_json_and_digest(
        campaign_root / CAMPAIGN_CONFIG_FILE
    )
    if not isinstance(payload, dict) or payload.get("contract") != CAMPAIGN_CONFIG_CONTRACT:
        raise CampaignEvidenceError("invalid campaign config contract")
    campaign_id = payload.get("campaign_id")
    _validate_campaign_id(campaign_id)
    return payload, {
        "campaign_id": campaign_id,
        "campaign_config_sha256": config_digest,
    }


def _campaign_root_for_attempt(attempt_root: Path) -> Path:
    attempts_root = _require_real_directory(attempt_root.parent, label="attempts root")
    if attempts_root.name != "attempts":
        raise CampaignEvidenceError(
            "attempt must be directly contained by the campaign attempts directory: "
            f"{attempt_root}"
        )
    return _require_real_directory(attempts_root.parent, label="campaign root")


def _verify_attempt_inventory(
    campaign_root: Path,
    *,
    binding: Mapping[str, str],
) -> tuple[dict[str, Any], tuple[Path, ...]]:
    ledger = _load_attempt_ledger(campaign_root, binding=binding)
    attempts_root = _require_real_directory(
        Path(campaign_root) / "attempts",
        label="attempts root",
    )
    observed: dict[str, Path] = {}
    try:
        with os.scandir(attempts_root) as entries:
            for entry in entries:
                path = Path(entry.path)
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise CampaignEvidenceError(
                        f"cannot stat attempt inventory entry {path}: {exc}"
                    ) from exc
                if (
                    _ATTEMPT_RE.fullmatch(entry.name) is None
                    or stat.S_ISLNK(info.st_mode)
                    or not stat.S_ISDIR(info.st_mode)
                ):
                    raise CampaignEvidenceError(f"unexpected entry in attempts root: {path}")
                observed[entry.name] = path
    except OSError as exc:
        raise CampaignEvidenceError(
            f"cannot scan attempts root {attempts_root}: {exc}"
        ) from exc

    ledger_ids = [row["attempt_id"] for row in ledger["attempts"]]
    if sorted(observed) != ledger_ids:
        raise CampaignEvidenceError(
            "attempt inventory differs from the attested ledger; "
            "an attempt is missing or unledgered"
        )
    roots: list[Path] = []
    for row in ledger["attempts"]:
        attempt_root = observed[row["attempt_id"]]
        _descriptor, descriptor_digest = _verify_attempt_descriptor(
            attempt_root,
            binding=binding,
        )
        if descriptor_digest != row["descriptor_sha256"]:
            raise CampaignEvidenceError(
                f"attempt descriptor differs from the attested ledger: {attempt_root}"
            )
        roots.append(attempt_root)
    return ledger, tuple(roots)


def _load_attempt_ledger(
    campaign_root: Path,
    *,
    binding: Mapping[str, str],
) -> dict[str, Any]:
    payload = load_verified_json(Path(campaign_root) / ATTEMPT_LEDGER_FILE)
    if not isinstance(payload, dict) or set(payload) != {
        "contract",
        "campaign_id",
        "campaign_config_sha256",
        "last_attempt_number",
        "attempts",
    }:
        raise CampaignEvidenceError("invalid campaign attempt ledger shape")
    if payload.get("contract") != ATTEMPT_LEDGER_CONTRACT:
        raise CampaignEvidenceError("invalid campaign attempt ledger contract")
    if _normalize_campaign_binding(payload) != _normalize_campaign_binding(binding):
        raise CampaignEvidenceError("campaign attempt ledger is bound to the wrong config")
    last_attempt_number = payload.get("last_attempt_number")
    attempts = payload.get("attempts")
    if type(last_attempt_number) is not int or last_attempt_number < 0:
        raise CampaignEvidenceError("campaign attempt ledger has invalid head")
    if not isinstance(attempts, list):
        raise CampaignEvidenceError("campaign attempt ledger attempts must be an array")
    normalized_rows: list[dict[str, str]] = []
    for index, raw in enumerate(attempts, start=1):
        if not isinstance(raw, Mapping):
            raise CampaignEvidenceError("campaign attempt ledger row must be an object")
        _require_string_json_keys(raw)
        if set(raw) != {"attempt_id", "descriptor_sha256"}:
            raise CampaignEvidenceError("campaign attempt ledger row has invalid shape")
        expected_id = f"attempt-{index:06d}"
        attempt_id = raw.get("attempt_id")
        descriptor_digest = raw.get("descriptor_sha256")
        if attempt_id != expected_id:
            raise CampaignEvidenceError("campaign attempt ledger is not continuous")
        if not isinstance(descriptor_digest, str) or _SHA256_RE.fullmatch(
            descriptor_digest
        ) is None:
            raise CampaignEvidenceError("campaign attempt ledger has invalid descriptor digest")
        normalized_rows.append(
            {"attempt_id": attempt_id, "descriptor_sha256": descriptor_digest}
        )
    if last_attempt_number != len(normalized_rows):
        raise CampaignEvidenceError("campaign attempt ledger head does not match its history")
    payload["attempts"] = normalized_rows
    return payload


def _verify_attempt_descriptor(
    root: Path,
    *,
    binding: Mapping[str, str],
) -> tuple[dict[str, Any], str]:
    descriptor, descriptor_digest = _load_verified_json_and_digest(
        root / ATTEMPT_DESCRIPTOR_FILE
    )
    if (
        not isinstance(descriptor, dict)
        or descriptor.get("contract") != ATTEMPT_DESCRIPTOR_CONTRACT
        or descriptor.get("attempt_id") != root.name
        or set(descriptor)
        != {
            "contract",
            "campaign_id",
            "campaign_config_sha256",
            "attempt_id",
        }
        or _normalize_campaign_binding(descriptor)
        != _normalize_campaign_binding(binding)
    ):
        raise CampaignEvidenceError("invalid or misbound attempt descriptor")
    return descriptor, descriptor_digest


def _normalize_campaign_binding(value: Mapping[str, Any]) -> tuple[str, str]:
    campaign_id = value.get("campaign_id")
    config_digest = value.get("campaign_config_sha256")
    _validate_campaign_id(campaign_id)
    if not isinstance(config_digest, str) or _SHA256_RE.fullmatch(config_digest) is None:
        raise CampaignEvidenceError("invalid campaign config digest binding")
    return campaign_id, config_digest


def _validate_campaign_id(value: Any) -> None:
    if not isinstance(value, str):
        raise CampaignEvidenceError("campaign_id must be a canonical UUID string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise CampaignEvidenceError("campaign_id must be a canonical UUID string") from exc
    if str(parsed) != value:
        raise CampaignEvidenceError("campaign_id must be a canonical UUID string")


def _require_real_directory(path: Path, *, label: str) -> Path:
    candidate = Path(path)
    try:
        info = candidate.lstat()
    except OSError as exc:
        raise CampaignEvidenceError(f"cannot stat {label} {candidate}: {exc}") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or _is_windows_junction(candidate)
        or not stat.S_ISDIR(info.st_mode)
    ):
        raise CampaignEvidenceError(f"{label} must be a real directory: {candidate}")
    return candidate


def _load_verified_json_and_digest(path: Path) -> tuple[Any, str]:
    source = Path(path)
    digest_path = _digest_path(source)
    source_bytes = _read_real_regular_file(source, label="JSON")
    digest_bytes = _read_real_regular_file(digest_path, label="digest")
    try:
        digest_text = digest_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise CampaignEvidenceError(f"malformed SHA-256 digest file: {digest_path}") from exc
    expected = digest_text.rstrip("\n")
    if not _SHA256_RE.fullmatch(expected) or digest_text != expected + "\n":
        raise CampaignEvidenceError(f"malformed SHA-256 digest file: {digest_path}")
    actual = hashlib.sha256(source_bytes).hexdigest()
    if actual != expected:
        raise CampaignEvidenceError(
            f"SHA-256 mismatch for {source}: expected {expected}, got {actual}"
        )
    try:
        text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CampaignEvidenceError(f"JSON is not valid UTF-8: {source}") from exc
    return _strict_json_loads(text), actual


def _read_real_regular_file(path: Path, *, label: str) -> bytes:
    chunks: list[bytes] = []
    _consume_real_regular_file(path, label=label, consume=chunks.append)
    return b"".join(chunks)


def _consume_real_regular_file(
    path: Path,
    *,
    label: str,
    consume: Callable[[bytes], None],
) -> None:
    """Consume one stable regular-file snapshot through its open descriptor."""

    source = Path(path)
    fd = _open_real_regular_file(source, label=label)
    bytes_read = 0
    try:
        before = os.fstat(fd)
        _require_real_regular_stat(before, path=source, label=label)
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            bytes_read += len(chunk)
            consume(chunk)
        after = os.fstat(fd)
    except OSError as exc:
        raise CampaignEvidenceError(f"cannot read {label} {source}: {exc}") from exc
    finally:
        os.close(fd)

    if not _same_regular_file_snapshot(before, after) or bytes_read != before.st_size:
        raise CampaignEvidenceError(f"{label} changed while it was being read: {source}")
    try:
        final = source.lstat()
    except OSError as exc:
        raise CampaignEvidenceError(
            f"{label} path disappeared after it was read: {source}: {exc}"
        ) from exc
    _require_real_regular_stat(final, path=source, label=label)
    if not _same_regular_file_snapshot(after, final):
        raise CampaignEvidenceError(f"{label} path changed while it was being read: {source}")


def _open_real_regular_file(path: Path, *, label: str) -> int:
    """Open a real regular file safely on POSIX and native Windows.

    POSIX keeps the kernel-level ``O_NOFOLLOW`` guarantee.  Native Windows has
    no equivalent flag, so the path is inspected before and immediately after
    ``open`` and bound to the descriptor through ``samestat``.  The caller
    performs the corresponding post-read descriptor/path checks.
    """

    source = Path(path)
    try:
        before = source.lstat()
    except OSError as exc:
        raise CampaignEvidenceError(f"cannot inspect {label} {source}: {exc}") from exc
    _require_real_regular_stat(before, path=source, label=label)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(source, flags)
    except OSError as exc:
        raise CampaignEvidenceError(
            f"cannot open {label} {source} without following links: {exc}"
        ) from exc
    try:
        opened = os.fstat(fd)
        _require_real_regular_stat(opened, path=source, label=label)
        try:
            after_open = source.lstat()
        except OSError as exc:
            raise CampaignEvidenceError(
                f"{label} path disappeared while it was being opened: {source}: {exc}"
            ) from exc
        _require_real_regular_stat(after_open, path=source, label=label)
        if (
            not _same_regular_file_snapshot(before, opened)
            or not _same_regular_file_snapshot(opened, after_open)
        ):
            raise CampaignEvidenceError(
                f"{label} path changed while it was being opened: {source}"
            )
        return fd
    except BaseException:
        os.close(fd)
        raise


def _require_real_regular_stat(
    value: os.stat_result,
    *,
    path: Path,
    label: str,
) -> None:
    if (
        stat.S_ISLNK(value.st_mode)
        or _stat_is_windows_reparse_point(value)
        or _path_reports_windows_junction(path)
        or not stat.S_ISREG(value.st_mode)
    ):
        raise CampaignEvidenceError(
            f"cannot open {label} {path} without following links: "
            "path must be a real regular file, not a symlink, junction, or reparse point"
        )


def _same_regular_file_snapshot(
    left: os.stat_result,
    right: os.stat_result,
) -> bool:
    return (
        os.path.samestat(left, right)
        and stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
        and left.st_ctime_ns == right.st_ctime_ns
        and left.st_nlink == right.st_nlink
    )


def _path_reports_windows_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _stat_is_windows_reparse_point(value: os.stat_result) -> bool:
    attributes = int(getattr(value, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse_flag)


def _require_string_json_keys(value: Any) -> None:
    active: set[int] = set()

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            identity = id(node)
            if identity in active:
                return
            active.add(identity)
            try:
                for key, child in node.items():
                    if type(key) is not str:
                        raise CampaignEvidenceError(
                            f"strict JSON object keys must be strings, got {type(key).__name__}"
                        )
                    visit(child)
            finally:
                active.remove(identity)
        elif isinstance(node, (list, tuple)):
            identity = id(node)
            if identity in active:
                return
            active.add(identity)
            try:
                for child in node:
                    visit(child)
            finally:
                active.remove(identity)

    visit(value)


def _digest_path(path: Path) -> Path:
    return path.with_name(path.name + DIGEST_SUFFIX)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = -1
        if directory_fd >= 0:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _strict_json_loads(text: str) -> Any:
    def reject_constant(value: str) -> Any:
        raise CampaignEvidenceError(f"non-finite JSON constant: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CampaignEvidenceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except json.JSONDecodeError as exc:
        raise CampaignEvidenceError(f"invalid JSON: {exc}") from exc
    _require_string_json_keys(payload)
    return payload


__all__ = [
    "ATTEMPT_LEDGER_CONTRACT",
    "ATTEMPT_LEDGER_FILE",
    "ATTEMPT_MANIFEST_CONTRACT",
    "ATTEMPT_MANIFEST_FILE",
    "CAMPAIGN_CONFIG_CONTRACT",
    "CAMPAIGN_CONFIG_FILE",
    "CONSOLIDATED_CONTRACT",
    "CampaignEvidenceError",
    "atomic_write_json_with_digest",
    "canonical_json_bytes",
    "consolidate_units",
    "create_attempt",
    "create_immutable_campaign_config",
    "load_immutable_campaign_config",
    "load_verified_json",
    "list_campaign_attempts",
    "seal_attempt",
    "sha256_file",
    "stable_tree_manifest",
    "stable_tree_sha256",
    "verify_attempt_seal",
]
