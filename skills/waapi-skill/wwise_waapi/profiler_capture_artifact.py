"""Bounded file outcome proof for the existing closed Profiler save route."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .builders.schema import SemanticSchemaValidator
from .canonical import canonical_sha256
from .operation_soundbank import (
    MAX_TREE_FILE_BYTES, SoundBankContractError,
    capture_file_proof, prove_artifact_path,
)

SAVE_CAPTURE_URI = "ak.wwise.core.profiler.saveCapture"
SCOPE = {
    "outcome": "exact_destination_created_or_content_changed_and_nonempty",
    "unrelated_files_preservation_verified": False,
    "capture_format_validity_verified": False,
    "capture_content_completeness_verified": False,
    "writes_outside_output_directory_observed": False,
}


def _directory_identity(path: Path) -> dict[str, Any]:
    try:
        lexical = path.lstat()
        resolved = path.resolve(strict=True)
        actual = resolved.stat()
        if not resolved.is_dir():
            raise SoundBankContractError("INVALID_IO_ROOT", "Capture output ancestor must be a directory.")
    except (OSError, RuntimeError) as exc:
        raise SoundBankContractError("FILE_CHANGED", "Capture output directory is inaccessible or changed.",
            details={"path": str(path), "reason": str(exc)}) from exc
    return {"path": str(path), "resolved_path": str(resolved),
        "device": lexical.st_dev, "inode": lexical.st_ino,
        "resolved_device": actual.st_dev, "resolved_inode": actual.st_ino}


def _snapshot(path: str, root: str, anchor: str, *, expected_root: str,
        expected_path: str) -> dict[str, Any]:
    # Missing ancestors may materialize during save. Re-resolve the original
    # spellings against the sealed authorization before opening the file.
    root_proof = prove_artifact_path(root, io_root=anchor, field="capture output directory")
    proof = prove_artifact_path(path, io_root=anchor, field="capture output", expect_directory=False)
    if root_proof["resolved_path"] != expected_root or proof["resolved_path"] != expected_path:
        raise SoundBankContractError("FILE_CHANGED", "Capture output resolution changed from its exact authorized destination.",
            details={"expected_root": expected_root, "actual_root": root_proof["resolved_path"],
                "expected_path": expected_path, "actual_path": proof["resolved_path"]})
    if Path(expected_path).parent != Path(expected_root):
        raise SoundBankContractError("INVALID_PATH", "Capture destination must remain in its exact authorized directory.")
    identity = _directory_identity(Path(root)) if root_proof["exists"] else None
    if identity is not None and identity["resolved_path"] != expected_root:
        raise SoundBankContractError("FILE_CHANGED", "Capture output directory changed during its observation.")
    file = (capture_file_proof(path, field="capture output", io_root=anchor,
        max_bytes=MAX_TREE_FILE_BYTES) if proof["exists"] else None)
    if (file is not None and file["path"] != expected_path
            or prove_artifact_path(path, io_root=anchor, field="capture output", expect_directory=False) != proof
            or prove_artifact_path(root, io_root=anchor, field="capture output directory") != root_proof
            or identity is not None and _directory_identity(Path(root)) != identity):
        raise SoundBankContractError("FILE_CHANGED", "Capture destination or directory changed during its observation.")
    return {"path": proof, "file": file, "root": root_proof, "root_identity": identity}


def prepare_capture_artifact(args: Mapping[str, Any], root: str,
        audit: Mapping[str, Any], version: str) -> dict[str, Any]:
    # io_policy already establishes the local host namespace and confinement.
    # Keep the original spelling too: resolving it first would hide leaf links.
    path = args["file"]
    paths = [row for row in audit["paths"] if row["json_path"] == "$.args.file"]
    if len(paths) != 1:
        raise SoundBankContractError("INVALID_PATH", "Capture save requires its exact destination I/O audit.")
    identities = []
    for directory in (Path(root), *Path(root).parents):
        if directory.exists() or directory.is_symlink():
            identities.append(_directory_identity(directory))
    anchor = identities[0]["resolved_path"]
    before = _snapshot(path, root, anchor, expected_root=audit["io_root"],
        expected_path=paths[0]["resolved_path"])
    plan = {"kind": "profiler-capture-artifact", "uri": SAVE_CAPTURE_URI, "version": version,
        "args": dict(args), "path": path, "io_root": root, "anchor": anchor,
        "directory_identities": identities, "before": before,
        "schema_sha256": canonical_sha256(SemanticSchemaValidator(version=version).schema_for(SAVE_CAPTURE_URI)),
        "verification_scope": dict(SCOPE)}
    _validate_directories(plan)
    return plan


def _validate_directories(plan: Mapping[str, Any]) -> None:
    for expected in plan["directory_identities"]:
        if _directory_identity(Path(expected["path"])) != expected:
            raise SoundBankContractError("FILE_CHANGED", "Capture output directory identity changed after Preview.")


def validate_capture_artifact(plan, args, root, audit, version):
    if (plan.get("kind") != "profiler-capture-artifact" or plan.get("uri") != SAVE_CAPTURE_URI
            or plan.get("version") != version or plan.get("args") != dict(args)
            or plan.get("path") != args["file"] or plan.get("io_root") != root
            or plan.get("verification_scope") != SCOPE
            or plan.get("schema_sha256") != canonical_sha256(SemanticSchemaValidator(version=version).schema_for(SAVE_CAPTURE_URI))
            or plan.get("before", {}).get("root", {}).get("resolved_path") != audit.get("io_root")
            or [row["resolved_path"] for row in audit["paths"] if row["json_path"] == "$.args.file"]
                != [plan.get("before", {}).get("path", {}).get("resolved_path")]):
        raise SoundBankContractError("INVALID_PREVIEW", "Capture artifact proof does not match its versioned request and I/O authorization.")
    _validate_directories(plan)
    if _snapshot(plan["path"], plan["io_root"], plan["anchor"],
            expected_root=plan["before"]["root"]["resolved_path"],
            expected_path=plan["before"]["path"]["resolved_path"]) != plan["before"]:
        raise SoundBankContractError("FILE_CHANGED", "Capture destination or output directory identity changed after Preview; prepare again.")

    _validate_directories(plan)


def verify_capture_artifact(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("verification_scope") != SCOPE:
        raise SoundBankContractError("INVALID_PREVIEW", "Capture proof uses an incompatible verification scope.")
    _validate_directories(plan)
    after = _snapshot(plan["path"], plan["io_root"], plan["anchor"],
        expected_root=plan["before"]["root"]["resolved_path"],
        expected_path=plan["before"]["path"]["resolved_path"])
    _validate_directories(plan)
    before = plan["before"]
    previous, current = before["file"], after["file"]
    changed = current is not None and (previous is None or any(
        previous[key] != current[key] for key in ("size", "sha256")))
    return {"kind": "profiler-capture-artifact-observation", "path": plan["path"],
        "created": previous is None and current is not None, "changed": changed,
        "nonempty": current is not None and current["size"] > 0,
        "before_file": previous, "after_file": current,
        "limits": {"max_file_bytes": MAX_TREE_FILE_BYTES}, "verification_scope": dict(SCOPE)}
