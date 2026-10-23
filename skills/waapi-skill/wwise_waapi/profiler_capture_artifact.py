"""Bounded file outcome proof for the existing closed Profiler save route."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .builders.schema import SemanticSchemaValidator
from .canonical import canonical_sha256
from .filesystem_security import metadata_is_link_or_reparse
from .operation_soundbank import (
    MAX_TREE_FILE_BYTES, SoundBankContractError, capture_artifact_tree,
    capture_file_proof, prove_artifact_path,
)

SAVE_CAPTURE_URI = "ak.wwise.core.profiler.saveCapture"
SCOPE = {
    "outcome": "exact_destination_created_or_content_changed_and_nonempty",
    "preservation": "bounded_output_directory_regular_file_contents",
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


def _snapshot(path: str, root: str, anchor: str) -> dict[str, Any]:
    root_path = Path(root)
    try:
        if root_path.is_symlink() or (root_path.exists() and metadata_is_link_or_reparse(root_path.lstat())):
            raise SoundBankContractError("SYMLINK_NOT_ALLOWED", "Capture output directory must not be a link or reparse point.")
    except OSError as exc:
        raise SoundBankContractError("FILE_CHANGED", "Capture output directory changed while it was inspected.",
            details={"path": root, "reason": str(exc)}) from exc
    tree = capture_artifact_tree(root, io_root=anchor)
    proof = prove_artifact_path(path, io_root=anchor, field="capture output", expect_directory=False)
    if Path(proof["resolved_path"]).parent != Path(tree["resolved_root"]):
        raise SoundBankContractError("INVALID_PATH", "Capture destination must remain in its exact authorized directory.")
    file = (capture_file_proof(path, field="capture output", io_root=anchor,
        max_bytes=MAX_TREE_FILE_BYTES) if proof["exists"] else None)
    # The separate descriptor-backed proof must describe the same file as the
    # bounded directory snapshot, including when the directory changes mid-read.
    relative = Path(proof["resolved_path"]).name
    rows = [row for row in tree["files"] if row["path"] == relative]
    if (file is None and rows) or (file is not None and (len(rows) != 1 or any(
            rows[0][key] != file[key] for key in ("size", "sha256", "mtime_ns")))):
        raise SoundBankContractError("FILE_CHANGED", "Capture destination changed during its artifact snapshot.")
    return {"path": proof, "file": file, "tree": tree}


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
    before = _snapshot(path, root, anchor)
    if before["path"]["resolved_path"] != paths[0]["resolved_path"] or before["tree"]["resolved_root"] != audit["io_root"]:
        raise SoundBankContractError("INVALID_PATH", "Capture destination differs from its authorized I/O audit.")
    return {"kind": "profiler-capture-artifact", "uri": SAVE_CAPTURE_URI, "version": version,
        "args": dict(args), "path": path, "io_root": root, "anchor": anchor,
        "directory_identities": identities, "before": before,
        "schema_sha256": canonical_sha256(SemanticSchemaValidator(version=version).schema_for(SAVE_CAPTURE_URI)),
        "verification_scope": dict(SCOPE)}


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
            or plan.get("before", {}).get("tree", {}).get("resolved_root") != audit.get("io_root")
            or [row["resolved_path"] for row in audit["paths"] if row["json_path"] == "$.args.file"]
                != [plan.get("before", {}).get("path", {}).get("resolved_path")]):
        raise SoundBankContractError("INVALID_PREVIEW", "Capture artifact proof does not match its versioned request and I/O authorization.")
    _validate_directories(plan)
    if _snapshot(plan["path"], plan["io_root"], plan["anchor"]) != plan["before"]:
        raise SoundBankContractError("FILE_CHANGED", "Capture destination or output files changed after Preview; prepare again.")


def verify_capture_artifact(plan: Mapping[str, Any]) -> dict[str, Any]:
    _validate_directories(plan)
    after = _snapshot(plan["path"], plan["io_root"], plan["anchor"])
    _validate_directories(plan)
    before = plan["before"]
    relative = Path(after["path"]["resolved_path"]).name
    # Tree rows are exact logical POSIX paths. Do not pass these through the
    # portable SoundBank target parser, which rejects legal POSIX file names.
    def contents(snapshot):
        return {row["path"]: {key: row[key] for key in ("size", "sha256")}
            for row in snapshot["tree"]["files"] if row["path"] != relative}
    previous, current = before["file"], after["file"]
    changed = current is not None and (previous is None or any(
        previous[key] != current[key] for key in ("size", "sha256")))
    preserved = contents(before) == contents(after)
    return {"kind": "profiler-capture-artifact-observation", "path": plan["path"],
        "created": previous is None and current is not None, "changed": changed,
        "nonempty": current is not None and current["size"] > 0,
        "unrelated_files_preserved": preserved,
        "before_file": previous, "after_file": current,
        "before_snapshot_sha256": before["tree"]["snapshot_sha256"],
        "after_snapshot_sha256": after["tree"]["snapshot_sha256"],
        "limits": after["tree"]["limits"], "verification_scope": dict(SCOPE)}
