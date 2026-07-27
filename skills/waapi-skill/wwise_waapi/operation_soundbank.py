"""Closed, filesystem-backed contracts for SoundBank operations.

The operation registry owns live WAAPI resolution and dispatch.  This module
owns the parts that can be proved before a call is made: explicit generation
scope, project/output containment, immutable input-file evidence, strict
External Sources and SoundBank Definition parsing, and bounded artifact-tree
deltas.  It never calls WAAPI and never writes project or output files.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .canonical import canonical_sha256


GENERATE_PLAN_CONTRACT = "waapi-skill.soundbank-generate-plan/v1"
WWISE_2021_PROJECT_FILE_CONTRACT = "waapi-skill.wwise-2021-project-file/v1"
EXTERNAL_SOURCES_PLAN_CONTRACT = "waapi-skill.soundbank-external-sources-plan/v1"
EXTERNAL_SOURCES_FILE_CONTRACT = "waapi-skill.external-sources-file/v1"
DEFINITION_PLAN_CONTRACT = "waapi-skill.soundbank-definition-plan/v1"
DEFINITION_FILE_CONTRACT = "waapi-skill.soundbank-definition-file/v1"
FILE_PROOF_CONTRACT = "waapi-skill.regular-file-proof/v1"
ARTIFACT_PATH_PROOF_CONTRACT = "waapi-skill.artifact-path-proof/v1"
ARTIFACT_TREE_CONTRACT = "waapi-skill.artifact-tree/v1"
ARTIFACT_DELTA_CONTRACT = "waapi-skill.artifact-tree-delta/v1"
WWISE_2021_LANGUAGE_INVENTORY_CONTRACT = "waapi-skill.wwise-2021-language-inventory/v1"

SUPPORTED_WWISE_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
POST_2021_WWISE_VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")

MAX_GENERATE_BANKS = 64
MAX_GENERATE_IDENTITIES_PER_BANK = 256
MAX_PLATFORMS = 16
MAX_LANGUAGES = 64
MAX_EXTERNAL_SOURCE_REQUESTS = 32
MAX_EXTERNAL_SOURCES_BYTES = 1024 * 1024
MAX_EXTERNAL_SOURCE_ENTRIES = 1024
MAX_SOURCE_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_DEFINITION_FILES = 32
MAX_DEFINITION_BYTES = 2 * 1024 * 1024
MAX_DEFINITION_ROWS = 4096
MAX_DEFINITION_COLUMNS = 8
MAX_DEFINITION_CELL_CHARS = 4096
MAX_PROJECT_FILE_BYTES = 64 * 1024 * 1024
MAX_TREE_FILES = 8192
MAX_TREE_ENTRIES = 16384
MAX_TREE_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_TREE_FILE_BYTES = 512 * 1024 * 1024
MAX_TREE_DEPTH = 32

_GENERATE_REQUIRED_KEYS = frozenset({"soundbanks", "platforms", "skipLanguages", "writeToDisk"})
_GENERATE_OPTIONAL_KEYS = frozenset(
    {"languages", "rebuildSoundBanks", "clearAudioFileCache", "rebuildInitBank"}
)
_GENERATE_BANK_REQUIRED_KEYS = frozenset({"name", "artifactExpectation"})
_GENERATE_BANK_OPTIONAL_KEYS = frozenset({"events", "auxBusses", "inclusions", "rebuild"})
_GENERATE_INCLUSIONS = ("event", "structure", "media")
_BANK_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GUID = re.compile(
    r"^\{([0-9A-Fa-f]{8})-([0-9A-Fa-f]{4})-([0-9A-Fa-f]{4})-"
    r"([0-9A-Fa-f]{4})-([0-9A-Fa-f]{12})\}$"
)
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_UNC = re.compile(r"^[\\/]{2}[^\\/]+[\\/][^\\/]+")
_UNSAFE_DESTINATION_CHARS = frozenset('<>:"|?*')
_WWISE_2021_PROJECT_SCHEMA = "103"
_WWISE_2021_VERSION = re.compile(r"^v2021\.1(?:\.\d+)?$")
_DEFAULT_COPY_STREAMED_FILES_COMMAND = (
    '"$(WwiseExePath)\\CopyStreamedFiles.exe" -info "$(InfoFilePath)" '
    '-outputpath "$(SoundBankPath)" -banks "$(SoundBankList)" '
    '-languages "$(LanguageList)"'
)

_EXTERNAL_ROW_KEYS = frozenset({"input", "platform", "output"})
_EXTERNAL_ROOT_ATTRIBUTES = frozenset({"SchemaVersion", "Root"})
_EXTERNAL_SOURCE_ATTRIBUTES = frozenset({"Path", "Conversion", "Destination", "AnalysisTypes"})
_ANALYSIS_TYPES = frozenset({"0", "2", "4", "6"})

_DEFINITION_DIRECTIVES: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "-AuxBus": ("AuxBus", ("Structure", "Media")),
    "-DialogueEvent": ("DialogueEvent", ("Event", "Structure", "Media")),
    "-EffectShareset": ("Effect", ("Structure", "Media")),
}
_DEFINITION_FILTERS: Mapping[str, str] = {
    "Event": "events",
    "Structure": "structures",
    "Media": "media",
}
_DEFINITION_EXTENSIONS = frozenset({".txt", ".tsv"})


class SoundBankContractError(ValueError):
    """A SoundBank request or evidence artifact failed closed validation."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": dict(self.details),
        }


def capture_file_proof(
    value: str | os.PathLike[str],
    *,
    field: str,
    max_bytes: int = MAX_SOURCE_FILE_BYTES,
) -> dict[str, Any]:
    """Capture a digest-bound proof for one absolute, non-symlink file."""

    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise SoundBankContractError("INVALID_LIMIT", "max_bytes must be a positive integer.")
    path, descriptor, before = _open_regular_file(value, field=field)
    if before.st_size > max_bytes:
        os.close(descriptor)
        raise SoundBankContractError(
            "LIMIT_EXCEEDED",
            f"{field} exceeds the closed byte limit.",
            details={"path": str(path), "size": before.st_size, "limit": max_bytes},
        )
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "rb") as opened:
            for chunk in iter(lambda: opened.read(1024 * 1024), b""):
                digest.update(chunk)
            after = os.fstat(opened.fileno())
    except OSError as exc:
        raise SoundBankContractError(
            "INVALID_FILE",
            f"{field} could not be hashed.",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    _require_unchanged_file_stat(before, after, field=field, path=path)
    body = {
        "contract": FILE_PROOF_CONTRACT,
        "path": str(path),
        "size": after.st_size,
        "sha256": digest.hexdigest(),
        "mtime_ns": after.st_mtime_ns,
        "device": after.st_dev,
        "inode": after.st_ino,
    }
    return _seal(body, "proof_sha256")


def verify_file_proof(proof: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    """Recompute a file proof and reject any preview-time input drift."""

    _require_sealed(proof, contract=FILE_PROOF_CONTRACT, seal_field="proof_sha256", field=field)
    path = proof.get("path")
    if not isinstance(path, str):
        raise SoundBankContractError("INVALID_FILE_PROOF", f"{field} proof requires path.")
    expected_size = proof.get("size")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        raise SoundBankContractError("INVALID_FILE_PROOF", f"{field} proof requires a non-negative size.")
    actual = capture_file_proof(path, field=field, max_bytes=max(expected_size, 1))
    compared = ("path", "size", "sha256", "mtime_ns", "device", "inode")
    changed = [key for key in compared if actual.get(key) != proof.get(key)]
    if changed:
        raise SoundBankContractError(
            "FILE_CHANGED",
            f"{field} changed after preview.",
            details={"changed_fields": changed, "expected": dict(proof), "actual": actual},
        )
    return actual


def prove_artifact_path(
    value: str | os.PathLike[str],
    *,
    io_root: str | os.PathLike[str],
    field: str,
    must_exist: bool = False,
    expect_directory: bool = True,
) -> dict[str, Any]:
    """Prove that an explicit artifact path resolves inside one trusted root."""

    root = _require_io_root(io_root)
    supplied = _absolute_path(value, field=field)
    try:
        resolved = supplied.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise SoundBankContractError(
            "INVALID_PATH",
            f"{field} could not be resolved.",
            details={"path": str(supplied), "error": str(exc)},
        ) from exc
    if not _is_within(resolved, root):
        raise SoundBankContractError(
            "PATH_OUTSIDE_IO_ROOT",
            f"{field} resolves outside the trusted I/O root.",
            details={"path": str(supplied), "resolved_path": str(resolved), "io_root": str(root)},
        )
    exists = supplied.exists() or supplied.is_symlink()
    kind = "missing"
    if exists:
        try:
            leaf_stat = supplied.lstat()
        except OSError as exc:
            raise SoundBankContractError(
                "INVALID_PATH",
                f"{field} could not be inspected.",
                details={"path": str(supplied), "error": str(exc)},
            ) from exc
        if stat.S_ISLNK(leaf_stat.st_mode):
            raise SoundBankContractError(
                "SYMLINK_NOT_ALLOWED",
                f"{field} must not be a symbolic link.",
                details={"path": str(supplied)},
            )
        if stat.S_ISDIR(leaf_stat.st_mode):
            kind = "directory"
        elif stat.S_ISREG(leaf_stat.st_mode):
            kind = "file"
        else:
            kind = "special"
        expected_kind = "directory" if expect_directory else "file"
        if kind != expected_kind:
            raise SoundBankContractError(
                "INVALID_PATH_KIND",
                f"{field} must identify a {expected_kind}.",
                details={"path": str(supplied), "actual_kind": kind},
            )
    elif must_exist:
        raise SoundBankContractError(
            "MISSING_PATH",
            f"{field} must already exist.",
            details={"path": str(supplied)},
        )
    body = {
        "contract": ARTIFACT_PATH_PROOF_CONTRACT,
        "field": field,
        "declared_path": str(supplied),
        "resolved_path": str(resolved),
        "io_root": str(root),
        "within_io_root": True,
        "exists": exists,
        "kind": kind,
    }
    return _seal(body, "proof_sha256")


def capture_artifact_tree(
    root: str | os.PathLike[str],
    *,
    io_root: str | os.PathLike[str],
    max_files: int = MAX_TREE_FILES,
    max_entries: int = MAX_TREE_ENTRIES,
    max_total_bytes: int = MAX_TREE_TOTAL_BYTES,
    max_file_bytes: int = MAX_TREE_FILE_BYTES,
    max_depth: int = MAX_TREE_DEPTH,
) -> dict[str, Any]:
    """Return a bounded, deterministic snapshot of one output tree."""

    for name, value in (
        ("max_files", max_files),
        ("max_entries", max_entries),
        ("max_total_bytes", max_total_bytes),
        ("max_file_bytes", max_file_bytes),
        ("max_depth", max_depth),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise SoundBankContractError("INVALID_LIMIT", f"{name} must be a positive integer.")
    path_proof = prove_artifact_path(
        root,
        io_root=io_root,
        field="artifact_root",
        must_exist=False,
        expect_directory=True,
    )
    resolved_root = Path(path_proof["resolved_path"])
    files: list[dict[str, Any]] = []
    entry_count = 0
    total_bytes = 0
    if path_proof["exists"]:
        stack: list[tuple[Path, PurePosixPath, int]] = [(resolved_root, PurePosixPath(), 0)]
        while stack:
            directory, relative_directory, depth = stack.pop()
            if depth > max_depth:
                raise SoundBankContractError(
                    "LIMIT_EXCEEDED",
                    "Artifact tree exceeds the closed depth limit.",
                    details={"path": str(directory), "depth": depth, "limit": max_depth},
                )
            try:
                with os.scandir(directory) as iterator:
                    entries = sorted(iterator, key=lambda entry: entry.name)
            except OSError as exc:
                raise SoundBankContractError(
                    "ARTIFACT_SNAPSHOT_FAILED",
                    "Artifact tree could not be enumerated.",
                    details={"path": str(directory), "error": str(exc)},
                ) from exc
            directories: list[tuple[Path, PurePosixPath, int]] = []
            for entry in entries:
                entry_count += 1
                if entry_count > max_entries:
                    raise SoundBankContractError(
                        "LIMIT_EXCEEDED",
                        "Artifact tree exceeds the closed entry limit.",
                        details={"entries": entry_count, "limit": max_entries},
                    )
                relative = relative_directory / entry.name
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise SoundBankContractError(
                        "ARTIFACT_SNAPSHOT_FAILED",
                        "An artifact entry could not be inspected.",
                        details={"path": entry.path, "error": str(exc)},
                    ) from exc
                if stat.S_ISLNK(entry_stat.st_mode):
                    raise SoundBankContractError(
                        "SYMLINK_NOT_ALLOWED",
                        "Artifact trees must not contain symbolic links.",
                        details={"path": entry.path},
                    )
                if stat.S_ISDIR(entry_stat.st_mode):
                    directories.append((Path(entry.path), relative, depth + 1))
                    continue
                if not stat.S_ISREG(entry_stat.st_mode):
                    raise SoundBankContractError(
                        "SPECIAL_FILE_NOT_ALLOWED",
                        "Artifact trees must contain only regular files and directories.",
                        details={"path": entry.path},
                    )
                if len(files) + 1 > max_files:
                    raise SoundBankContractError(
                        "LIMIT_EXCEEDED",
                        "Artifact tree exceeds the closed file limit.",
                        details={"files": len(files) + 1, "limit": max_files},
                    )
                if entry_stat.st_size > max_file_bytes:
                    raise SoundBankContractError(
                        "LIMIT_EXCEEDED",
                        "An artifact file exceeds the closed per-file limit.",
                        details={"path": entry.path, "size": entry_stat.st_size, "limit": max_file_bytes},
                    )
                total_bytes += entry_stat.st_size
                if total_bytes > max_total_bytes:
                    raise SoundBankContractError(
                        "LIMIT_EXCEEDED",
                        "Artifact tree exceeds the closed total byte limit.",
                        details={"total_bytes": total_bytes, "limit": max_total_bytes},
                    )
                proof = capture_file_proof(entry.path, field="artifact_file", max_bytes=max_file_bytes)
                if (entry_stat.st_dev, entry_stat.st_ino) != (proof["device"], proof["inode"]):
                    raise SoundBankContractError(
                        "FILE_CHANGED",
                        "An artifact entry changed while the tree snapshot was captured.",
                        details={"path": entry.path},
                    )
                files.append(
                    {
                        "path": relative.as_posix(),
                        "size": proof["size"],
                        "sha256": proof["sha256"],
                        "mtime_ns": proof["mtime_ns"],
                    }
                )
            stack.extend(reversed(directories))
    files.sort(key=lambda item: item["path"])
    body = {
        "contract": ARTIFACT_TREE_CONTRACT,
        "root": path_proof["declared_path"],
        "resolved_root": path_proof["resolved_path"],
        "io_root": path_proof["io_root"],
        "exists": path_proof["exists"],
        "file_count": len(files),
        "entry_count": entry_count,
        "total_bytes": total_bytes,
        "files": files,
        "limits": {
            "max_files": max_files,
            "max_entries": max_entries,
            "max_total_bytes": max_total_bytes,
            "max_file_bytes": max_file_bytes,
            "max_depth": max_depth,
        },
    }
    return _seal(body, "snapshot_sha256")


def compare_artifact_trees(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    expected_relative_paths: Sequence[str] = (),
    allowed_relative_paths: Sequence[str] | None = None,
    require_expected_change: bool = True,
    enforce_no_unexpected_changes: bool = False,
) -> dict[str, Any]:
    """Compare two sealed snapshots and evaluate exact expected artifacts."""

    _require_sealed(before, contract=ARTIFACT_TREE_CONTRACT, seal_field="snapshot_sha256", field="before")
    _require_sealed(after, contract=ARTIFACT_TREE_CONTRACT, seal_field="snapshot_sha256", field="after")
    for key in ("root", "resolved_root", "io_root"):
        if before.get(key) != after.get(key):
            raise SoundBankContractError(
                "SNAPSHOT_ROOT_CHANGED",
                "Artifact snapshots do not describe the same trusted root.",
                details={"field": key, "before": before.get(key), "after": after.get(key)},
            )
    before_rows = _snapshot_rows(before, field="before")
    after_rows = _snapshot_rows(after, field="after")
    created = sorted(set(after_rows) - set(before_rows))
    deleted = sorted(set(before_rows) - set(after_rows))
    modified = sorted(
        path
        for path in set(before_rows) & set(after_rows)
        if any(before_rows[path].get(key) != after_rows[path].get(key) for key in ("size", "sha256"))
    )
    unchanged = sorted(set(before_rows) & set(after_rows) - set(modified))
    changed = sorted({*created, *deleted, *modified})

    expected = _relative_path_set(expected_relative_paths, field="expected_relative_paths")
    allowed = (
        None
        if allowed_relative_paths is None
        else _relative_path_set(allowed_relative_paths, field="allowed_relative_paths")
    )
    expected_results: list[dict[str, Any]] = []
    for path in sorted(expected):
        if path in created:
            status = "created"
        elif path in modified:
            status = "modified"
        elif path in unchanged:
            status = "unchanged"
        elif path in deleted:
            status = "deleted"
        else:
            status = "missing"
        row = after_rows.get(path)
        nonempty = bool(row and isinstance(row.get("size"), int) and row["size"] > 0)
        changed_as_required = status in {"created", "modified"} or not require_expected_change
        expected_results.append(
            {
                "path": path,
                "status": status,
                "nonempty": nonempty,
                "satisfied": status not in {"missing", "deleted"} and nonempty and changed_as_required,
            }
        )
    unexpected = [] if allowed is None else sorted(set(changed) - allowed)
    expectations_satisfied = all(row["satisfied"] for row in expected_results)
    no_unexpected_changes = not unexpected
    body = {
        "contract": ARTIFACT_DELTA_CONTRACT,
        "root": before["root"],
        "before_snapshot_sha256": before["snapshot_sha256"],
        "after_snapshot_sha256": after["snapshot_sha256"],
        "created": created,
        "modified": modified,
        "deleted": deleted,
        "unchanged_count": len(unchanged),
        "expected": expected_results,
        "unexpected_changes": unexpected,
        "expectations_satisfied": expectations_satisfied,
        "no_unexpected_changes": no_unexpected_changes,
        "verified": expectations_satisfied and (
            no_unexpected_changes if enforce_no_unexpected_changes else True
        ),
    }
    return _seal(body, "delta_sha256")


def _load_wwise_2021_project_identity_and_languages(
    value: str | os.PathLike[str],
    *,
    live_project_id: str,
    live_project_name: str,
    workunit_is_dirty: bool,
) -> tuple[Path, ET.Element, ET.Element, list[dict[str, str]], dict[str, Any]]:
    """Strictly load the live 2021.1 WPROJ identity and LanguageList."""

    if workunit_is_dirty is not False:
        raise SoundBankContractError(
            "PROJECT_DIRTY",
            "The on-disk Wwise 2021.1 LanguageList is authoritative only when workunitIsDirty is explicitly false.",
            details={"workunitIsDirty": workunit_is_dirty},
        )
    project_id = _canonical_wwise_guid(live_project_id, field="live_project.id")
    project_name = _require_text(live_project_name, field="live_project.name")
    project_path, data, file_proof = _read_proven_bytes(
        value,
        field="live_project.filePath",
        max_bytes=MAX_PROJECT_FILE_BYTES,
    )
    if project_path.suffix.casefold() != ".wproj":
        raise SoundBankContractError(
            "INVALID_PROJECT_FILE",
            "The live Wwise 2021.1 Project file must use the .wproj extension.",
            details={"path": str(project_path)},
        )
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise SoundBankContractError(
            "INVALID_PROJECT_FILE",
            "The Wwise 2021.1 Project file must be UTF-8.",
            details={"path": str(project_path), "start": exc.start},
        ) from exc
    upper = text.upper()
    if "\x00" in text or "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise SoundBankContractError(
            "UNSAFE_XML",
            "The Wwise Project file cannot contain NUL, DTD, or entity declarations.",
            details={"path": str(project_path)},
        )
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SoundBankContractError(
            "INVALID_PROJECT_FILE",
            "The Wwise 2021.1 Project file is not well-formed XML.",
            details={"path": str(project_path), "error": str(exc)},
        ) from exc
    if root.tag != "WwiseDocument":
        raise SoundBankContractError(
            "INVALID_PROJECT_FILE",
            "The Wwise Project root must be WwiseDocument without a namespace.",
            details={"root_tag": str(root.tag)},
        )
    _require_xml_attributes(
        root.attrib,
        frozenset({"Type", "SchemaVersion", "WwiseVersion", "WwiseBuild"}),
        field="WwiseDocument",
    )
    if (
        root.attrib.get("Type") != "Project"
        or root.attrib.get("SchemaVersion") != _WWISE_2021_PROJECT_SCHEMA
        or _WWISE_2021_VERSION.fullmatch(root.attrib.get("WwiseVersion", "")) is None
        or not root.attrib.get("WwiseBuild", "").isdecimal()
    ):
        raise SoundBankContractError(
            "UNSUPPORTED_PROJECT_SCHEMA",
            "The Project file does not match the reviewed Wwise 2021.1 schema.",
            details={"attributes": dict(root.attrib)},
        )
    project_info_elements = [child for child in root if child.tag == "ProjectInfo"]
    if len(project_info_elements) != 1:
        raise SoundBankContractError(
            "INVALID_PROJECT_FILE",
            "WwiseDocument must contain exactly one direct ProjectInfo element.",
            details={"count": len(project_info_elements)},
        )
    project_elements = [child for child in project_info_elements[0] if child.tag == "Project"]
    if len(project_elements) != 1:
        raise SoundBankContractError(
            "INVALID_PROJECT_FILE",
            "ProjectInfo must contain exactly one direct Project element.",
            details={"count": len(project_elements)},
        )
    project = project_elements[0]
    _require_xml_attributes(project.attrib, frozenset({"Name", "ID"}), field="Project")
    xml_name = _require_text(project.attrib.get("Name"), field="Project.Name")
    xml_id = _canonical_wwise_guid(project.attrib.get("ID"), field="Project.ID")
    if xml_name != project_name or xml_id.casefold() != project_id.casefold():
        raise SoundBankContractError(
            "PROJECT_IDENTITY_MISMATCH",
            "The live Project identity does not match the hashed WPROJ identity.",
            details={
                "live": {"id": project_id, "name": project_name},
                "wproj": {"id": xml_id, "name": xml_name},
            },
        )

    language_parent = _single_direct_xml_child(project, "LanguageList", field="Project")
    language_elements = [child for child in language_parent if child.tag == "Language"]
    if len(language_elements) != len(language_parent):
        raise SoundBankContractError(
            "INVALID_PROJECT_FILE",
            "Project.LanguageList may contain only direct Language elements.",
        )
    if len(language_elements) > MAX_LANGUAGES:
        raise SoundBankContractError(
            "INVALID_PROJECT_CONTEXT",
            "The Wwise 2021.1 Project language list exceeds the closed limit.",
            details={"count": len(language_elements), "limit": MAX_LANGUAGES},
        )
    languages: list[dict[str, str]] = []
    seen_language_names: set[str] = set()
    seen_language_ids: set[str] = set()
    for index, element in enumerate(language_elements):
        _require_xml_attributes(
            element.attrib,
            frozenset({"Name", "ID"}),
            field=f"LanguageList.Language[{index}]",
        )
        name = _require_text(element.attrib.get("Name"), field=f"LanguageList.Language[{index}].Name")
        language_id = _canonical_wwise_guid(
            element.attrib.get("ID"),
            field=f"LanguageList.Language[{index}].ID",
        )
        if name.casefold() in seen_language_names or language_id.casefold() in seen_language_ids:
            raise SoundBankContractError(
                "INVALID_PROJECT_CONTEXT",
                "Language names and IDs must be unique in the Wwise Project file.",
                details={"index": index, "name": name, "id": language_id},
            )
        seen_language_names.add(name.casefold())
        seen_language_ids.add(language_id.casefold())
        languages.append({"id": language_id, "name": name})
    return project_path, root, project, languages, file_proof


def parse_wwise_2021_language_inventory(
    value: str | os.PathLike[str],
    *,
    live_project_id: str,
    live_project_name: str,
    workunit_is_dirty: bool,
) -> dict[str, Any]:
    """Return hash-bound 2021.1 live Project LanguageList evidence."""

    project_id = _canonical_wwise_guid(live_project_id, field="live_project.id")
    project_name = _require_text(live_project_name, field="live_project.name")
    _, _, _, languages, file_proof = _load_wwise_2021_project_identity_and_languages(
        value,
        live_project_id=project_id,
        live_project_name=project_name,
        workunit_is_dirty=workunit_is_dirty,
    )
    return _seal(
        {
            "contract": WWISE_2021_LANGUAGE_INVENTORY_CONTRACT,
            "project": {"id": project_id, "name": project_name},
            "languages": languages,
            "file_proof": file_proof,
        },
        "inventory_sha256",
    )


def parse_wwise_2021_project_file(
    value: str | os.PathLike[str],
    *,
    io_root: str | os.PathLike[str],
    live_project_id: str,
    live_project_name: str,
    workunit_is_dirty: bool,
) -> dict[str, Any]:
    """Derive the 2021.1 generation context from one live Project WPROJ.

    The filesystem path and dirty flag must come from the live Project object's
    ``filePath`` and ``workunitIsDirty`` accessors.  The caller cannot provide
    any project-layout fields to the named operation.
    """

    project_id = _canonical_wwise_guid(live_project_id, field="live_project.id")
    project_name = _require_text(live_project_name, field="live_project.name")
    path_proof = prove_artifact_path(
        value,
        io_root=io_root,
        field="live_project.filePath",
        must_exist=True,
        expect_directory=False,
    )
    project_path, root, project, all_languages, file_proof = _load_wwise_2021_project_identity_and_languages(
        path_proof["resolved_path"],
        live_project_id=project_id,
        live_project_name=project_name,
        workunit_is_dirty=workunit_is_dirty,
    )

    platform_parent = _single_direct_xml_child(project, "Platforms", field="Project")
    platform_elements = [child for child in platform_parent if child.tag == "Platform"]
    if len(platform_elements) != len(platform_parent):
        raise SoundBankContractError(
            "INVALID_PROJECT_FILE",
            "Project.Platforms may contain only direct Platform elements.",
        )
    if not platform_elements or len(platform_elements) > MAX_PLATFORMS:
        raise SoundBankContractError(
            "INVALID_PROJECT_CONTEXT",
            "The Wwise 2021.1 Project must declare a non-empty bounded platform list.",
            details={"count": len(platform_elements), "limit": MAX_PLATFORMS},
        )
    platforms: list[dict[str, Any]] = []
    seen_platform_names: set[str] = set()
    seen_platform_ids: set[str] = set()
    for index, element in enumerate(platform_elements):
        _require_xml_attributes(
            element.attrib,
            frozenset({"Name", "ReferencePlatform", "ID"}),
            field=f"Platforms.Platform[{index}]",
        )
        name = _require_text(element.attrib.get("Name"), field=f"Platforms.Platform[{index}].Name")
        base_name = _require_text(
            element.attrib.get("ReferencePlatform"),
            field=f"Platforms.Platform[{index}].ReferencePlatform",
        )
        platform_id = _canonical_wwise_guid(
            element.attrib.get("ID"),
            field=f"Platforms.Platform[{index}].ID",
        )
        if name.casefold() in seen_platform_names or platform_id.casefold() in seen_platform_ids:
            raise SoundBankContractError(
                "INVALID_PROJECT_CONTEXT",
                "Platform names and IDs must be unique in the Wwise Project file.",
                details={"index": index, "name": name, "id": platform_id},
            )
        seen_platform_names.add(name.casefold())
        seen_platform_ids.add(platform_id.casefold())
        platforms.append({"id": platform_id, "name": name, "baseName": base_name})

    languages = [
        dict(language)
        for language in all_languages
        if language["name"].casefold() not in {"external", "mixed", "sfx"}
    ]

    property_list = _single_direct_xml_child(project, "PropertyList", field="Project")
    property_elements = [child for child in property_list if child.tag == "Property"]
    if len(property_elements) != len(property_list):
        raise SoundBankContractError(
            "INVALID_PROJECT_FILE",
            "Project.PropertyList may contain only direct Property elements.",
        )
    reviewed_hook_names = {
        "SoundBankPreGenerateCustomCmdLines",
        "SoundBankPostGenerateCustomCmdLines",
    }
    unknown_hooks = sorted(
        element.attrib.get("Name", "")
        for element in property_elements
        if "SoundBank" in element.attrib.get("Name", "")
        and "Custom" in element.attrib.get("Name", "")
        and element.attrib.get("Name", "").endswith("CmdLines")
        and element.attrib.get("Name") not in reviewed_hook_names
    )
    if unknown_hooks:
        raise SoundBankContractError(
            "UNSAFE_PROJECT_HOOK",
            "The Wwise Project declares an unreviewed SoundBank command hook.",
            details={"hooks": unknown_hooks},
        )
    soundbank_paths = _project_platform_property_values(
        property_elements,
        "SoundBankPaths",
        platforms=platforms,
    )
    pre_hooks = _project_platform_property_values(
        property_elements,
        "SoundBankPreGenerateCustomCmdLines",
        platforms=platforms,
        allow_empty=True,
    )
    post_hooks = _project_platform_property_values(
        property_elements,
        "SoundBankPostGenerateCustomCmdLines",
        platforms=platforms,
        allow_empty=True,
    )
    for platform in platforms:
        platform_name = platform["name"]
        if pre_hooks[platform_name]:
            raise SoundBankContractError(
                "UNSAFE_PROJECT_HOOK",
                "The Wwise 2021.1 named route rejects non-empty pre-generation hooks.",
                details={"platform": platform_name},
            )
        if post_hooks[platform_name] not in {"", _DEFAULT_COPY_STREAMED_FILES_COMMAND}:
            raise SoundBankContractError(
                "UNSAFE_PROJECT_HOOK",
                "The Wwise 2021.1 named route accepts only the default CopyStreamedFiles post-generation hook.",
                details={"platform": platform_name},
            )

    header_property = _single_project_property(property_elements, "SoundBankHeaderFilePath")
    _require_xml_attributes(
        header_property.attrib,
        frozenset({"Name", "Type", "Value"}),
        field="Property[SoundBankHeaderFilePath]",
    )
    if header_property.attrib.get("Type") != "string":
        raise SoundBankContractError(
            "INVALID_PROJECT_CONTEXT",
            "SoundBankHeaderFilePath must be a string property.",
        )
    project_root = project_path.parent.resolve(strict=True)
    metadata_root = _resolve_wwise_project_setting_path(
        header_property.attrib.get("Value"),
        project_root=project_root,
        io_root=io_root,
        field="SoundBankHeaderFilePath",
    )
    for platform in platforms:
        platform_name = platform["name"]
        bank_path = _resolve_wwise_project_setting_path(
            soundbank_paths[platform_name],
            project_root=project_root,
            io_root=io_root,
            field=f"SoundBankPaths[{platform_name}]",
        )
        platform["soundBankPath"] = bank_path
        # 2021.1 has no independent copied-media field.  This equality is
        # valid only because the hook check above accepts either no post hook
        # or the default CopyStreamedFiles output to $(SoundBankPath).
        platform["copiedMediaPath"] = bank_path

    misc_settings = _single_direct_xml_child(project, "MiscSettings", field="Project")
    cache_elements = [
        child
        for child in misc_settings
        if child.tag == "MiscSettingEntry" and child.attrib.get("Name") == "Cache"
    ]
    if len(cache_elements) != 1:
        raise SoundBankContractError(
            "INVALID_PROJECT_CONTEXT",
            "The Wwise 2021.1 Project must declare exactly one Cache setting.",
            details={"count": len(cache_elements)},
        )
    _require_xml_attributes(cache_elements[0].attrib, frozenset({"Name"}), field="MiscSettingEntry[Cache]")
    cache_path = _resolve_wwise_project_setting_path(
        cache_elements[0].text,
        project_root=project_root,
        io_root=io_root,
        field="MiscSettings.Cache",
    )

    default_conversion = _single_direct_xml_child(project, "DefaultConversion", field="Project")
    _require_xml_attributes(
        default_conversion.attrib,
        frozenset({"Name", "ID"}),
        field="DefaultConversion",
    )
    conversion_name = _require_text(default_conversion.attrib.get("Name"), field="DefaultConversion.Name")
    conversion_id = _canonical_wwise_guid(default_conversion.attrib.get("ID"), field="DefaultConversion.ID")
    source = _seal(
        {
            "contract": WWISE_2021_PROJECT_FILE_CONTRACT,
            "schema_version": root.attrib["SchemaVersion"],
            "wwise_version": root.attrib["WwiseVersion"],
            "wwise_build": root.attrib["WwiseBuild"],
            "file_proof": file_proof,
            "path_proof": path_proof,
            "hook_policy": "empty_pre_and_empty_or_default_copy_streamed_files_post_only",
        },
        "context_sha256",
    )
    return {
        "id": project_id,
        "name": project_name,
        "path": str(project_path),
        "isDirty": False,
        "directories": {
            "root": str(project_root),
            "cache": cache_path,
            "soundBankOutputRoot": metadata_root,
        },
        "platforms": platforms,
        "languages": languages,
        "defaultConversion": {"id": conversion_id, "name": conversion_name},
        "wwiseProjectFile": source,
    }


def build_generate_operation_plan(
    arguments: Mapping[str, Any],
    *,
    version: str,
    project_info: Mapping[str, Any],
    io_root: str | os.PathLike[str],
    project_context_authority: str | None = None,
) -> dict[str, Any]:
    """Build a closed ``soundbank.generate`` request and artifact oracle."""

    lane = _require_version(version, supported=SUPPORTED_WWISE_VERSIONS)
    _require_mapping(arguments, field="arguments")
    _require_exact_keys(
        arguments,
        required=_GENERATE_REQUIRED_KEYS,
        optional=_GENERATE_OPTIONAL_KEYS,
        context="soundbank.generate arguments",
    )
    project = _project_context(
        project_info,
        version=lane,
        io_root=io_root,
        authority=project_context_authority,
    )

    soundbanks = _require_sequence(arguments.get("soundbanks"), field="soundbanks")
    if not soundbanks or len(soundbanks) > MAX_GENERATE_BANKS:
        raise SoundBankContractError(
            "INVALID_SCOPE",
            "soundbank.generate requires an explicit non-empty bounded SoundBank list.",
            details={"count": len(soundbanks), "limit": MAX_GENERATE_BANKS},
        )
    normalized_banks: list[dict[str, Any]] = []
    seen_banks: set[str] = set()
    for index, raw in enumerate(soundbanks):
        if not isinstance(raw, Mapping):
            raise SoundBankContractError(
                "INVALID_ARGUMENT",
                "Every soundbanks item must be a JSON object.",
                details={"index": index},
            )
        _require_exact_keys(
            raw,
            required=_GENERATE_BANK_REQUIRED_KEYS,
            optional=_GENERATE_BANK_OPTIONAL_KEYS,
            context=f"soundbanks[{index}]",
        )
        name = _require_bank_name(raw.get("name"), field=f"soundbanks[{index}].name")
        if name.casefold() == "init":
            raise SoundBankContractError(
                "INVALID_SCOPE",
                "Init is an automatic generation by-product and cannot be requested as a user SoundBank.",
                details={"index": index, "name": name},
            )
        key = name.casefold()
        if key in seen_banks:
            raise SoundBankContractError(
                "DUPLICATE_TARGET",
                "SoundBank names must be unique within one generation request.",
                details={"index": index, "name": name},
            )
        seen_banks.add(key)
        artifact_expectation = _require_text(
            raw.get("artifactExpectation"),
            field=f"soundbanks[{index}].artifactExpectation",
        )
        if artifact_expectation not in {"nonlocalized", "localized", "mixed"}:
            raise SoundBankContractError(
                "INVALID_ARGUMENT",
                "SoundBank artifactExpectation must be nonlocalized, localized, or mixed.",
                details={"index": index, "actual": artifact_expectation},
            )
        bank: dict[str, Any] = {
            "name": name,
            "artifactExpectation": artifact_expectation,
        }
        for public_name in ("events", "auxBusses"):
            if public_name in raw:
                identities = _normalize_identities(
                    raw.get(public_name),
                    field=f"soundbanks[{index}].{public_name}",
                )
                if not identities:
                    raise SoundBankContractError(
                        "INVALID_ARGUMENT",
                        f"soundbanks[{index}].{public_name} must not be an empty explicit list.",
                    )
                bank[public_name] = identities
        definitions_present = "events" in bank or "auxBusses" in bank
        if "inclusions" in raw:
            if not definitions_present:
                raise SoundBankContractError(
                    "INVALID_ARGUMENT",
                    "SoundBank inclusions are accepted only with explicit Event or AuxBus definitions.",
                    details={"index": index},
                )
            bank["inclusions"] = _normalize_generate_inclusions(
                raw.get("inclusions"),
                field=f"soundbanks[{index}].inclusions",
            )
        elif definitions_present:
            bank["inclusions"] = list(_GENERATE_INCLUSIONS)
        bank["rebuild"] = _optional_bool(raw, "rebuild", default=False, field=f"soundbanks[{index}].rebuild")
        normalized_banks.append(bank)

    requested_platforms = _require_nonempty_strings(
        arguments.get("platforms"),
        field="platforms",
        limit=MAX_PLATFORMS,
    )
    selected_platforms = _resolve_project_rows(
        requested_platforms,
        project_info.get("platforms"),
        field="platforms",
        aliases=("id", "name", "baseName"),
        required_fields=("id", "name", "baseName", "soundBankPath", "copiedMediaPath"),
    )
    skip_languages = _require_bool(arguments.get("skipLanguages"), field="skipLanguages")
    if skip_languages:
        if "languages" in arguments:
            raise SoundBankContractError(
                "INVALID_SCOPE",
                "languages must be omitted when skipLanguages is true.",
            )
        selected_languages: list[dict[str, Any]] = []
    else:
        requested_languages = _require_nonempty_strings(
            arguments.get("languages"),
            field="languages",
            limit=MAX_LANGUAGES,
        )
        selected_languages = _resolve_project_rows(
            requested_languages,
            project_info.get("languages"),
            field="languages",
            aliases=("id", "name"),
            required_fields=("id", "name"),
        )
    language_dependent_banks = [
        bank["name"]
        for bank in normalized_banks
        if bank["artifactExpectation"] in {"localized", "mixed"}
    ]
    if language_dependent_banks and not selected_languages:
        raise SoundBankContractError(
            "INVALID_SCOPE",
            "Localized or mixed SoundBank artifact expectations require explicit languages and skipLanguages=false.",
            details={"soundbanks": language_dependent_banks, "skipLanguages": skip_languages},
        )
    if _require_bool(arguments.get("writeToDisk"), field="writeToDisk") is not True:
        raise SoundBankContractError(
            "UNSUPPORTED_BOUNDARY",
            "The closed generation route currently requires writeToDisk=true for artifact verification.",
        )

    directories = _require_mapping(project_info.get("directories"), field="project_info.directories")
    cache_path = _require_text(directories.get("cache"), field="project_info.directories.cache")
    metadata_root = _require_text(
        directories.get("soundBankOutputRoot"),
        field="project_info.directories.soundBankOutputRoot",
    )
    path_proofs: list[dict[str, Any]] = [
        prove_artifact_path(cache_path, io_root=io_root, field="project_info.directories.cache"),
        prove_artifact_path(
            metadata_root,
            io_root=io_root,
            field="project_info.directories.soundBankOutputRoot",
        ),
    ]
    platform_oracle: list[dict[str, Any]] = []
    for index, platform in enumerate(selected_platforms):
        bank_path = _require_text(platform.get("soundBankPath"), field=f"platforms[{index}].soundBankPath")
        media_path = _require_text(platform.get("copiedMediaPath"), field=f"platforms[{index}].copiedMediaPath")
        bank_proof = prove_artifact_path(
            bank_path,
            io_root=io_root,
            field=f"platforms[{index}].soundBankPath",
        )
        media_proof = prove_artifact_path(
            media_path,
            io_root=io_root,
            field=f"platforms[{index}].copiedMediaPath",
        )
        path_proofs.extend((bank_proof, media_proof))
        expected_banks: list[dict[str, Any]] = []
        for bank in normalized_banks:
            expectation = bank["artifactExpectation"]
            expected_artifacts: list[dict[str, Any]] = []
            if expectation in {"nonlocalized", "mixed"}:
                expected_artifacts.append(
                    {
                        "kind": "nonlocalized",
                        "language": None,
                        "path": str(Path(bank_proof["resolved_path"]) / f"{bank['name']}.bnk"),
                    }
                )
            if expectation in {"localized", "mixed"}:
                expected_artifacts.extend(
                    {
                        "kind": "localized",
                        "language": language["name"],
                        "path": str(
                            Path(bank_proof["resolved_path"])
                            / _safe_artifact_segment(language["name"], field="project_info.languages[].name")
                            / f"{bank['name']}.bnk"
                        ),
                    }
                    for language in selected_languages
                )
            expected_banks.append(
                {
                    "name": bank["name"],
                    "filename": f"{bank['name']}.bnk",
                    "artifact_expectation": expectation,
                    "expected_artifacts": expected_artifacts,
                    "verification": "every_expected_artifact_created_or_modified_and_nonempty",
                }
            )
        platform_oracle.append(
            {
                "id": platform["id"],
                "name": platform["name"],
                "baseName": platform["baseName"],
                "soundBankPath": bank_proof["resolved_path"],
                "copiedMediaPath": media_proof["resolved_path"],
                "expected_user_soundbanks": expected_banks,
            }
        )

    dispatch_args = {
        "soundbanks": [
            {key: value for key, value in bank.items() if key != "artifactExpectation"}
            for bank in normalized_banks
        ],
        "platforms": [platform["id"] for platform in selected_platforms],
        "skipLanguages": skip_languages,
        "rebuildSoundBanks": _optional_bool(arguments, "rebuildSoundBanks", default=False),
        "clearAudioFileCache": _optional_bool(arguments, "clearAudioFileCache", default=False),
        "writeToDisk": True,
        "rebuildInitBank": _optional_bool(arguments, "rebuildInitBank", default=False),
    }
    if selected_languages:
        dispatch_args["languages"] = [language["id"] for language in selected_languages]

    body = {
        "contract": GENERATE_PLAN_CONTRACT,
        "version": lane,
        "dispatch_args": dispatch_args,
        "project_context": project,
        "scope": {
            "user_soundbanks": [bank["name"] for bank in normalized_banks],
            "artifact_expectations": [
                {"name": bank["name"], "mode": bank["artifactExpectation"]}
                for bank in normalized_banks
            ],
            "platforms": [
                {key: platform[key] for key in ("id", "name", "baseName")}
                for platform in selected_platforms
            ],
            "languages": [
                {key: language[key] for key in ("id", "name")}
                for language in selected_languages
            ],
            "skip_languages": skip_languages,
            "empty_soundbank_list_allowed": False,
            "implicit_all_platforms_allowed": False,
            "implicit_all_languages_allowed": False,
            "auto_defined_soundbanks": (
                "generated_by_wwise_if_project_feature_enabled_and_not_selectable_by_this_api"
                if lane in {"2023.1", "2024.1", "2025.1"}
                else "not_declared_by_versioned_generate_schema"
            ),
        },
        "artifact_plan": {
            "path_proofs": _dedupe_path_proofs(path_proofs),
            "snapshot_roots": _dedupe_strings(
                [proof["resolved_path"] for proof in path_proofs]
            ),
            "platforms": platform_oracle,
            "metadata_root": str(Path(metadata_root).resolve(strict=False)),
            "cache_root": str(Path(cache_path).resolve(strict=False)),
            "automatic_byproducts": ["Init.bnk"],
            "required_verification": "bounded_pre_post_tree_delta_plus_nonempty_requested_bank_artifacts",
        },
        "oracle": {
            "result_schema_required": True,
            "logs_are_diagnostic_only": lane != "2021.1",
            "error_field_must_be_empty": lane == "2025.1",
            "business_state_requires_artifacts": True,
            "no_retry_after_dispatch": True,
        },
    }
    return _seal(body, "plan_sha256")


def parse_external_sources_file(
    source_list: str | os.PathLike[str],
    *,
    project_root: str | os.PathLike[str],
) -> dict[str, Any]:
    """Parse a strict, proven ``.wsources`` file and derive WEM names."""

    path, data, proof = _read_proven_bytes(
        source_list,
        field="source_list",
        max_bytes=MAX_EXTERNAL_SOURCES_BYTES,
    )
    if path.suffix.casefold() != ".wsources":
        raise SoundBankContractError(
            "INVALID_EXTERNAL_SOURCES_FILE",
            "External Sources input must use the .wsources extension.",
            details={"path": str(path)},
        )
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise SoundBankContractError(
            "INVALID_ENCODING",
            "External Sources input must be UTF-8.",
            details={"path": str(path), "start": exc.start},
        ) from exc
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise SoundBankContractError(
            "UNSAFE_XML",
            "External Sources XML must not contain NUL, DTD, or entity declarations.",
            details={"path": str(path)},
        )
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SoundBankContractError(
            "INVALID_EXTERNAL_SOURCES_FILE",
            "External Sources input is not well-formed XML.",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if root.tag != "ExternalSourcesList":
        raise SoundBankContractError(
            "INVALID_EXTERNAL_SOURCES_FILE",
            "External Sources XML root must be ExternalSourcesList without a namespace.",
            details={"root_tag": str(root.tag)},
        )
    _require_xml_attributes(root.attrib, _EXTERNAL_ROOT_ATTRIBUTES, field="ExternalSourcesList")
    if root.attrib.get("SchemaVersion") != "1":
        raise SoundBankContractError(
            "UNSUPPORTED_EXTERNAL_SOURCES_SCHEMA",
            "External Sources SchemaVersion must be exactly 1.",
            details={"schema_version": root.attrib.get("SchemaVersion")},
        )
    if root.text and root.text.strip():
        raise SoundBankContractError(
            "INVALID_EXTERNAL_SOURCES_FILE",
            "ExternalSourcesList must contain only Source elements.",
        )
    try:
        project_path = _absolute_path(project_root, field="project_root").resolve(strict=True)
    except OSError as exc:
        raise SoundBankContractError(
            "INVALID_PATH",
            "project_root must be an existing directory.",
            details={"path": os.fspath(project_root), "error": str(exc)},
        ) from exc
    if not project_path.is_dir():
        raise SoundBankContractError("INVALID_PATH_KIND", "project_root must identify a directory.")
    root_value = root.attrib.get("Root")
    source_root = (
        project_path
        if root_value is None
        else _resolve_xml_path(root_value, base=project_path, field="ExternalSourcesList.Root")
    )
    if not source_root.is_dir():
        raise SoundBankContractError(
            "INVALID_EXTERNAL_SOURCE_ROOT",
            "External Sources Root must resolve to an existing directory.",
            details={"root": str(source_root)},
        )

    children = list(root)
    if not children or len(children) > MAX_EXTERNAL_SOURCE_ENTRIES:
        raise SoundBankContractError(
            "LIMIT_EXCEEDED" if children else "INVALID_EXTERNAL_SOURCES_FILE",
            "External Sources input requires a non-empty bounded Source list.",
            details={"count": len(children), "limit": MAX_EXTERNAL_SOURCE_ENTRIES},
        )
    entries: list[dict[str, Any]] = []
    seen_destinations: set[str] = set()
    for index, element in enumerate(children):
        if element.tag != "Source" or list(element):
            raise SoundBankContractError(
                "INVALID_EXTERNAL_SOURCES_FILE",
                "ExternalSourcesList children must be leaf Source elements.",
                details={"index": index, "tag": str(element.tag)},
            )
        if (element.text and element.text.strip()) or (element.tail and element.tail.strip()):
            raise SoundBankContractError(
                "INVALID_EXTERNAL_SOURCES_FILE",
                "Source elements must not contain text.",
                details={"index": index},
            )
        _require_xml_attributes(element.attrib, _EXTERNAL_SOURCE_ATTRIBUTES, field=f"Source[{index}]")
        raw_source = _require_text(element.attrib.get("Path"), field=f"Source[{index}].Path")
        source_path = _resolve_xml_path(raw_source, base=source_root, field=f"Source[{index}].Path")
        source_proof = capture_file_proof(
            source_path,
            field=f"Source[{index}].Path",
            max_bytes=MAX_SOURCE_FILE_BYTES,
        )
        if source_path.suffix.casefold() != ".wav":
            raise SoundBankContractError(
                "UNSUPPORTED_SOURCE_FORMAT",
                "The closed External Sources route currently supports WAV inputs only.",
                details={"index": index, "path": str(source_path), "supported": [".wav"]},
            )
        conversion = element.attrib.get("Conversion")
        if conversion is not None:
            conversion = _require_text(conversion, field=f"Source[{index}].Conversion")
        analysis_types = element.attrib.get("AnalysisTypes")
        if analysis_types is not None and analysis_types not in _ANALYSIS_TYPES:
            raise SoundBankContractError(
                "INVALID_EXTERNAL_SOURCES_FILE",
                "Source AnalysisTypes is outside the reviewed 0/2/4/6 set.",
                details={"index": index, "value": analysis_types},
            )
        destination_value = element.attrib.get("Destination")
        if destination_value is None:
            if _is_absolute_path_text(raw_source) or ".." in _portable_path_parts(raw_source):
                raise SoundBankContractError(
                    "EXPLICIT_DESTINATION_REQUIRED",
                    "An absolute or parent-traversing Source Path requires an explicit Destination.",
                    details={"index": index, "path": raw_source},
                )
            destination = _normalized_destination(raw_source, field=f"Source[{index}].Path")
            destination_source = "source_relative_path"
        else:
            destination = _normalized_destination(
                _require_text(destination_value, field=f"Source[{index}].Destination"),
                field=f"Source[{index}].Destination",
            )
            destination_source = "Destination"
        destination_key = destination.casefold()
        if destination_key in seen_destinations:
            raise SoundBankContractError(
                "DUPLICATE_DESTINATION",
                "External Sources destinations must be unique within one list.",
                details={"index": index, "destination": destination},
            )
        seen_destinations.add(destination_key)
        entries.append(
            {
                "index": index,
                "source": source_proof,
                "conversion": conversion,
                "uses_project_default_conversion": conversion is None,
                "analysis_types": None if analysis_types is None else int(analysis_types),
                "expected_destination": destination,
                "destination_source": destination_source,
            }
        )
    body = {
        "contract": EXTERNAL_SOURCES_FILE_CONTRACT,
        "path": str(path),
        "file_proof": proof,
        "schema_version": 1,
        "source_root": str(source_root),
        "entries": entries,
        "entry_count": len(entries),
    }
    return _seal(body, "document_sha256")


def build_external_sources_operation_plan(
    arguments: Mapping[str, Any],
    *,
    version: str,
    project_info: Mapping[str, Any],
    io_root: str | os.PathLike[str],
    project_context_authority: str | None = None,
) -> dict[str, Any]:
    """Build a closed ``convertExternalSources`` request and output oracle."""

    lane = _require_version(version, supported=POST_2021_WWISE_VERSIONS)
    _require_mapping(arguments, field="arguments")
    _require_exact_keys(
        arguments,
        required=frozenset({"sources"}),
        optional=frozenset(),
        context="soundbank.convertExternalSources arguments",
    )
    project = _project_context(
        project_info,
        version=lane,
        io_root=io_root,
        authority=project_context_authority,
    )
    source_rows = _require_sequence(arguments.get("sources"), field="sources")
    if not source_rows or len(source_rows) > MAX_EXTERNAL_SOURCE_REQUESTS:
        raise SoundBankContractError(
            "INVALID_SCOPE",
            "convertExternalSources requires a non-empty bounded sources list.",
            details={"count": len(source_rows), "limit": MAX_EXTERNAL_SOURCE_REQUESTS},
        )
    requested_platforms: list[str] = []
    for index, row in enumerate(source_rows):
        if not isinstance(row, Mapping):
            raise SoundBankContractError(
                "INVALID_ARGUMENT",
                "Every external-source request must be a JSON object.",
                details={"index": index},
            )
        _require_exact_keys(
            row,
            required=_EXTERNAL_ROW_KEYS,
            optional=frozenset(),
            context=f"sources[{index}]",
        )
        requested_platforms.append(_require_text(row.get("platform"), field=f"sources[{index}].platform"))
    selected_platforms = _resolve_project_rows(
        requested_platforms,
        project_info.get("platforms"),
        field="platforms",
        aliases=("id", "name", "baseName"),
        required_fields=("id", "name", "baseName"),
        allow_duplicate_requests=True,
    )

    dispatch_rows: list[dict[str, str]] = []
    request_plans: list[dict[str, Any]] = []
    snapshot_roots: list[str] = []
    seen_requests: set[tuple[str, str, str]] = set()
    seen_platform_roots: dict[str, str] = {}
    seen_outputs: set[tuple[str, str]] = set()
    requested_conversions: set[str] = set()
    uses_project_default_conversion = False
    project_root = project["directories"]["root"]
    for index, (raw, platform) in enumerate(zip(source_rows, selected_platforms, strict=True)):
        input_path = _require_text(raw.get("input"), field=f"sources[{index}].input")
        output_path = _require_text(raw.get("output"), field=f"sources[{index}].output")
        output_proof = prove_artifact_path(
            output_path,
            io_root=io_root,
            field=f"sources[{index}].output",
            must_exist=False,
            expect_directory=True,
        )
        output_root = output_proof["resolved_path"]
        platform_root_key = output_root.casefold()
        previous_platform = seen_platform_roots.get(platform_root_key)
        if previous_platform is not None and previous_platform != platform["id"]:
            raise SoundBankContractError(
                "CROSS_PLATFORM_OUTPUT_COLLISION",
                "Different platforms must not share one External Sources output root.",
                details={"output": output_root, "platforms": [previous_platform, platform["id"]]},
            )
        seen_platform_roots[platform_root_key] = platform["id"]
        parsed = parse_external_sources_file(input_path, project_root=project_root)
        request_key = (parsed["path"].casefold(), platform["id"].casefold(), output_root.casefold())
        if request_key in seen_requests:
            raise SoundBankContractError(
                "DUPLICATE_REQUEST",
                "Duplicate External Sources request rows are not allowed.",
                details={"index": index},
            )
        seen_requests.add(request_key)
        expected_outputs: list[dict[str, Any]] = []
        for entry in parsed["entries"]:
            if entry["conversion"] is None:
                uses_project_default_conversion = True
            else:
                requested_conversions.add(entry["conversion"])
            relative = entry["expected_destination"]
            output_key = (output_root.casefold(), relative.casefold())
            if output_key in seen_outputs:
                raise SoundBankContractError(
                    "DUPLICATE_DESTINATION",
                    "External Sources requests resolve to the same output artifact.",
                    details={"index": index, "output_root": output_root, "destination": relative},
                )
            seen_outputs.add(output_key)
            absolute = Path(output_root, *PurePosixPath(relative).parts)
            artifact_proof = prove_artifact_path(
                absolute,
                io_root=io_root,
                field=f"sources[{index}].expected_destination",
                must_exist=False,
                expect_directory=False,
            )
            expected_outputs.append(
                {
                    "relative_path": relative,
                    "absolute_path": artifact_proof["resolved_path"],
                    "source_sha256": entry["source"]["sha256"],
                    "verification": "created_or_modified_and_nonempty_wem",
                }
            )
        dispatch_rows.append(
            {"input": parsed["path"], "platform": platform["id"], "output": output_root}
        )
        snapshot_roots.append(output_root)
        request_plans.append(
            {
                "index": index,
                "platform": {key: platform[key] for key in ("id", "name", "baseName")},
                "output_root": output_root,
                "output_path_proof": output_proof,
                "source_list": parsed,
                "expected_outputs": expected_outputs,
                "managed_side_effects": ["Wwise.dat"],
            }
        )

    default_conversion: dict[str, str] | None = None
    if uses_project_default_conversion:
        raw_default = _require_mapping(
            project_info.get("defaultConversion"),
            field="project_info.defaultConversion",
        )
        default_conversion = {
            "id": _require_text(raw_default.get("id"), field="project_info.defaultConversion.id"),
            "name": _require_text(raw_default.get("name"), field="project_info.defaultConversion.name"),
        }
    body = {
        "contract": EXTERNAL_SOURCES_PLAN_CONTRACT,
        "version": lane,
        "dispatch_args": {"sources": dispatch_rows},
        "project_context": project,
        "requests": request_plans,
        "artifact_plan": {
            "snapshot_roots": _dedupe_strings(snapshot_roots),
            "expected_output_count": sum(len(request["expected_outputs"]) for request in request_plans),
            "all_outputs_explicit": True,
            "cross_platform_output_roots_are_distinct": True,
            "required_verification": "bounded_pre_post_tree_delta_plus_exact_nonempty_wem_outputs",
        },
        "oracle": {
            "result_schema_required": True,
            "result_schema_is_business_state_proof": False,
            "all_source_files_hashed_before_dispatch": True,
            "source_files_must_be_reverified_before_execution": True,
            "explicit_conversion_names_require_live_resolution": sorted(requested_conversions),
            "project_default_conversion": default_conversion,
            "no_retry_after_dispatch": True,
        },
    }
    return _seal(body, "plan_sha256")


def parse_soundbank_definition_file(
    definition_file: str | os.PathLike[str],
) -> dict[str, Any]:
    """Parse the strongly verifiable subset of a SoundBank Definition TSV."""

    path, data, proof = _read_proven_bytes(
        definition_file,
        field="definition_file",
        max_bytes=MAX_DEFINITION_BYTES,
    )
    if path.suffix.casefold() not in _DEFINITION_EXTENSIONS:
        raise SoundBankContractError(
            "INVALID_DEFINITION_FILE",
            "SoundBank Definition files must use .txt or .tsv.",
            details={"path": str(path), "supported": sorted(_DEFINITION_EXTENSIONS)},
        )
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise SoundBankContractError(
            "INVALID_ENCODING",
            "SoundBank Definition files must be UTF-8.",
            details={"path": str(path), "start": exc.start},
        ) from exc
    if "\x00" in text:
        raise SoundBankContractError("INVALID_DEFINITION_FILE", "Definition files must not contain NUL.")
    if re.search(r"\r(?!\n)", text):
        raise SoundBankContractError(
            "INVALID_DEFINITION_FILE",
            "Definition files must use LF or CRLF line endings, not bare CR.",
        )
    if text.lstrip().startswith("<"):
        raise SoundBankContractError(
            "INVALID_DEFINITION_FORMAT",
            "SoundBank Definition input is tab-delimited text, not SoundBanksInfo XML.",
        )
    try:
        parsed_rows = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t", strict=True))
    except csv.Error as exc:
        raise SoundBankContractError(
            "INVALID_DEFINITION_FILE",
            "Definition input is not valid tab-delimited data.",
            details={"error": str(exc)},
        ) from exc
    quoted_rows = _definition_quoted_columns(text, parsed_rows)
    if not parsed_rows or len(parsed_rows) > MAX_DEFINITION_ROWS:
        raise SoundBankContractError(
            "LIMIT_EXCEEDED" if parsed_rows else "INVALID_DEFINITION_FILE",
            "Definition input requires a non-empty bounded row list.",
            details={"rows": len(parsed_rows), "limit": MAX_DEFINITION_ROWS},
        )

    banks: dict[str, dict[str, Any]] = {}
    bank_order: list[str] = []
    normalized_rows: list[dict[str, Any]] = []
    seen_inclusions: set[tuple[str, str, str]] = set()
    for row_number, (cells, quoted_columns) in enumerate(
        zip(parsed_rows, quoted_rows, strict=True),
        start=1,
    ):
        if not cells or all(cell == "" for cell in cells):
            raise SoundBankContractError(
                "INVALID_DEFINITION_FILE",
                "Definition input must not contain empty rows.",
                details={"row": row_number},
            )
        if len(cells) < 2 or len(cells) > MAX_DEFINITION_COLUMNS:
            raise SoundBankContractError(
                "INVALID_DEFINITION_ROW",
                "Definition rows require 2-8 tab-delimited columns.",
                details={"row": row_number, "columns": len(cells)},
            )
        for column, cell in enumerate(cells, start=1):
            if len(cell) > MAX_DEFINITION_CELL_CHARS:
                raise SoundBankContractError(
                    "LIMIT_EXCEEDED",
                    "A Definition cell exceeds the closed character limit.",
                    details={"row": row_number, "column": column, "limit": MAX_DEFINITION_CELL_CHARS},
                )
            if not cell or cell != cell.strip() or any(
                character in cell for character in ("\x00", "\t", "\r", "\n")
            ):
                raise SoundBankContractError(
                    "INVALID_DEFINITION_ROW",
                    "Definition cells must be non-empty and have no outer whitespace or controls.",
                    details={"row": row_number, "column": column},
                )
        bank_name = _require_bank_name(cells[0], field=f"row[{row_number}].soundbank")
        token = cells[1]
        if token == "-GameSyncExclusion":
            raise SoundBankContractError(
                "UNSUPPORTED_DEFINITION_DIRECTIVE",
                "-GameSyncExclusion is not strongly verifiable through getInclusions and is rejected.",
                details={"row": row_number, "directive": token},
            )
        if token.startswith("-"):
            directive = _DEFINITION_DIRECTIVES.get(token)
            if directive is None:
                raise SoundBankContractError(
                    "UNSUPPORTED_DEFINITION_DIRECTIVE",
                    "Definition input contains an unsupported special directive.",
                    details={"row": row_number, "directive": token, "supported": sorted(_DEFINITION_DIRECTIVES)},
                )
            if len(cells) < 3:
                raise SoundBankContractError(
                    "INVALID_DEFINITION_ROW",
                    "A special Definition directive requires an object identity.",
                    details={"row": row_number, "directive": token},
                )
            object_type, allowed_filters = directive
            identity_cell = cells[2]
            identity_column = 2
            raw_filters = cells[3:]
            keyword = token
        else:
            object_type = "Event"
            allowed_filters = ("Event", "Structure", "Media")
            identity_cell = token
            identity_column = 1
            raw_filters = cells[2:]
            keyword = "Event"
        identity = _definition_identity(identity_cell, row_number=row_number)
        if any(
            quoted
            for column, quoted in enumerate(quoted_columns)
            if column != identity_column
        ):
            raise SoundBankContractError(
                "INVALID_DEFINITION_ROW",
                "Only a string object-name identity may be double-quoted in a Definition row.",
                details={"row": row_number},
            )
        if identity["kind"] == "name" and not quoted_columns[identity_column]:
            raise SoundBankContractError(
                "INVALID_DEFINITION_IDENTITY",
                "Definition object names must use the official double-quoted string form.",
                details={"row": row_number, "value": identity_cell},
            )
        if identity["kind"] != "name" and quoted_columns[identity_column]:
            raise SoundBankContractError(
                "INVALID_DEFINITION_IDENTITY",
                "Definition GUID and uint32 identities must remain unquoted.",
                details={"row": row_number, "value": identity_cell},
            )
        filters = _definition_filters(
            raw_filters,
            allowed=allowed_filters,
            row_number=row_number,
        )
        duplicate_key = (bank_name.casefold(), object_type, _identity_key(identity))
        if duplicate_key in seen_inclusions:
            raise SoundBankContractError(
                "DUPLICATE_DEFINITION_INCLUSION",
                "A SoundBank Definition must not repeat one object inclusion.",
                details={"row": row_number, "soundbank": bank_name, "identity": identity},
            )
        seen_inclusions.add(duplicate_key)
        inclusion = {
            "row_number": row_number,
            "definition_keyword": keyword,
            "object_type": object_type,
            "identity": identity,
            "filters": filters,
        }
        bank_key = bank_name.casefold()
        if bank_key not in banks:
            banks[bank_key] = {"name": bank_name, "inclusions": []}
            bank_order.append(bank_key)
        banks[bank_key]["inclusions"].append(inclusion)
        normalized_rows.append({"soundbank": bank_name, **inclusion})

    body = {
        "contract": DEFINITION_FILE_CONTRACT,
        "path": str(path),
        "file_proof": proof,
        "row_count": len(normalized_rows),
        "rows": normalized_rows,
        "soundbanks": [banks[key] for key in bank_order],
        "unsupported_boundary": {
            "GameSyncExclusion": "rejected because getInclusions cannot prove exclusion state",
            "identity_quoting": "string names require double quotes; GUID and uint32 identities must be unquoted",
            "unknown_directives": "rejected",
            "unknown_filters": "rejected",
        },
    }
    return _seal(body, "document_sha256")


def build_process_definition_operation_plan(
    arguments: Mapping[str, Any],
    *,
    version: str,
    project_info: Mapping[str, Any],
    io_root: str | os.PathLike[str],
    project_context_authority: str | None = None,
) -> dict[str, Any]:
    """Build a trusted ``processDefinitionFiles`` mutation/readback plan."""

    lane = _require_version(version, supported=POST_2021_WWISE_VERSIONS)
    _require_mapping(arguments, field="arguments")
    _require_exact_keys(
        arguments,
        required=frozenset({"files"}),
        optional=frozenset(),
        context="soundbank.processDefinitionFiles arguments",
    )
    project = _project_context(
        project_info,
        version=lane,
        io_root=io_root,
        authority=project_context_authority,
    )
    raw_files = _require_sequence(arguments.get("files"), field="files")
    if not raw_files or len(raw_files) > MAX_DEFINITION_FILES:
        raise SoundBankContractError(
            "INVALID_SCOPE",
            "processDefinitionFiles requires a non-empty bounded file list.",
            details={"count": len(raw_files), "limit": MAX_DEFINITION_FILES},
        )
    documents: list[dict[str, Any]] = []
    dispatch_files: list[str] = []
    soundbanks: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    bank_sources: dict[str, str] = {}
    for index, value in enumerate(raw_files):
        if not isinstance(value, (str, os.PathLike)):
            raise SoundBankContractError(
                "INVALID_ARGUMENT",
                "Definition file paths must be strings.",
                details={"index": index},
            )
        document = parse_soundbank_definition_file(value)
        file_key = document["path"].casefold()
        if file_key in seen_files:
            raise SoundBankContractError(
                "DUPLICATE_REQUEST",
                "Duplicate Definition file paths are not allowed.",
                details={"index": index, "path": document["path"]},
            )
        seen_files.add(file_key)
        for bank in document["soundbanks"]:
            bank_key = bank["name"].casefold()
            previous = bank_sources.get(bank_key)
            if previous is not None:
                raise SoundBankContractError(
                    "CROSS_FILE_SOUNDBANK_COLLISION",
                    "One SoundBank may be defined by only one file in the closed route.",
                    details={"soundbank": bank["name"], "files": [previous, document["path"]]},
                )
            bank_sources[bank_key] = document["path"]
            soundbanks.append(
                {
                    "name": bank["name"],
                    "source_file": document["path"],
                    "expected_inclusions": list(bank["inclusions"]),
                    "pre_state_required": True,
                    "post_state": "exact_additive_getInclusions_match_after_live_identity_resolution",
                }
            )
        documents.append(document)
        dispatch_files.append(document["path"])
    body = {
        "contract": DEFINITION_PLAN_CONTRACT,
        "version": lane,
        "dispatch_args": {"files": dispatch_files},
        "project_context": project,
        "documents": documents,
        "soundbanks": soundbanks,
        "oracle": {
            "caller_expected_soundbank_names_accepted": False,
            "soundbank_names_and_inclusions_derived_from_hashed_files": True,
            "resolve_every_identity_before_dispatch": True,
            "unknown_or_ambiguous_identity_policy": "reject_before_dispatch",
            "capture_existing_soundbank_guid_and_inclusions": True,
            "verify_new_or_preserved_guid_and_exact_additive_inclusions": True,
            "verify_unrelated_control_soundbank_unchanged": True,
            "result_schema_is_business_state_proof": False,
            "no_retry_after_dispatch": True,
        },
        "cleanup": {
            "automatic_cleanup": False,
            "sandbox_teardown_preferred": True,
            "manual_rollback_plan": "delete newly created SoundBanks and restore captured inclusions",
            "cleanup_failure_is_distinct": True,
        },
    }
    return _seal(body, "plan_sha256")


def _project_context(
    project_info: Mapping[str, Any],
    *,
    version: str,
    io_root: str | os.PathLike[str],
    authority: str | None,
) -> dict[str, Any]:
    _require_mapping(project_info, field="project_info")
    expected_authority = (
        "waapi_object_get_filePath_plus_hashed_wproj"
        if version == "2021.1"
        else "waapi_getProjectInfo"
    )
    selected_authority = expected_authority if authority is None else authority
    if selected_authority != expected_authority:
        raise SoundBankContractError(
            "INVALID_PROJECT_CONTEXT_AUTHORITY",
            "Project path authority does not match the selected Wwise version.",
            details={"version": version, "expected": expected_authority, "actual": selected_authority},
        )
    if project_info.get("isDirty") is not False:
        raise SoundBankContractError(
            "PROJECT_DIRTY",
            "The closed SoundBank route requires a saved, non-dirty sandbox project.",
            details={"isDirty": project_info.get("isDirty")},
        )
    project_id = _require_text(project_info.get("id"), field="project_info.id")
    project_name = _require_text(project_info.get("name"), field="project_info.name")
    project_file = _require_text(project_info.get("path"), field="project_info.path")
    directories = _require_mapping(project_info.get("directories"), field="project_info.directories")
    project_root = _require_text(directories.get("root"), field="project_info.directories.root")
    root_proof = prove_artifact_path(
        project_root,
        io_root=io_root,
        field="project_info.directories.root",
        must_exist=True,
        expect_directory=True,
    )
    project_path = _absolute_path(project_file, field="project_info.path")
    if not _is_within(project_path.resolve(strict=False), Path(root_proof["resolved_path"])):
        raise SoundBankContractError(
            "PROJECT_PATH_MISMATCH",
            "The active project file does not resolve below project_info.directories.root.",
            details={"project_path": str(project_path), "project_root": root_proof["resolved_path"]},
        )
    project_path_proof = prove_artifact_path(
        project_path,
        io_root=io_root,
        field="project_info.path",
        must_exist=True,
        expect_directory=False,
    )
    project_file_proof = capture_file_proof(
        project_path,
        field="project_info.path",
        max_bytes=MAX_PROJECT_FILE_BYTES,
    )
    source_evidence: dict[str, Any] | None = None
    if version == "2021.1":
        raw_source = project_info.get("wwiseProjectFile")
        if not isinstance(raw_source, Mapping):
            raise SoundBankContractError(
                "INVALID_PROJECT_CONTEXT_AUTHORITY",
                "Wwise 2021.1 generation requires parser-owned WPROJ evidence.",
            )
        _require_sealed(
            raw_source,
            contract=WWISE_2021_PROJECT_FILE_CONTRACT,
            seal_field="context_sha256",
            field="project_info.wwiseProjectFile",
        )
        raw_proof = raw_source.get("file_proof")
        if not isinstance(raw_proof, Mapping):
            raise SoundBankContractError(
                "INVALID_PROJECT_CONTEXT_AUTHORITY",
                "Wwise 2021.1 WPROJ evidence lacks a file proof.",
            )
        proof_fields = ("path", "size", "sha256", "mtime_ns", "device", "inode", "proof_sha256")
        if any(project_file_proof.get(key) != raw_proof.get(key) for key in proof_fields):
            raise SoundBankContractError(
                "FILE_CHANGED",
                "The Wwise 2021.1 Project file changed after strict parsing.",
                details={"expected": dict(raw_proof), "actual": project_file_proof},
            )
        source_evidence = {
            "contract": raw_source.get("contract"),
            "context_sha256": raw_source.get("context_sha256"),
            "schema_version": raw_source.get("schema_version"),
            "wwise_version": raw_source.get("wwise_version"),
            "wwise_build": raw_source.get("wwise_build"),
            "hook_policy": raw_source.get("hook_policy"),
        }
    body = {
        "version": version,
        "authority": selected_authority,
        "id": project_id,
        "name": project_name,
        "path": project_path_proof["resolved_path"],
        "isDirty": False,
        "directories": {"root": root_proof["resolved_path"]},
        "project_file_proof": project_file_proof,
        "io_root": root_proof["io_root"],
    }
    if source_evidence is not None:
        body["wproj_source"] = source_evidence
    return {**body, "context_sha256": canonical_sha256(body)}


def _resolve_project_rows(
    requested: Sequence[str],
    available: Any,
    *,
    field: str,
    aliases: Sequence[str],
    required_fields: Sequence[str],
    allow_duplicate_requests: bool = False,
) -> list[dict[str, Any]]:
    rows = _require_sequence(available, field=f"project_info.{field}")
    normalized_available: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise SoundBankContractError(
                "INVALID_PROJECT_CONTEXT",
                f"project_info.{field} entries must be JSON objects.",
                details={"index": index},
            )
        row: dict[str, Any] = {}
        for key in required_fields:
            row[key] = _require_text(raw.get(key), field=f"project_info.{field}[{index}].{key}")
        normalized_available.append(row)
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(requested):
        matches = [row for row in normalized_available if any(row.get(alias) == value for alias in aliases)]
        if len(matches) != 1:
            raise SoundBankContractError(
                "PROJECT_VALUE_NOT_UNIQUE",
                f"{field}[{index}] must resolve to exactly one live project row.",
                details={"value": value, "matches": len(matches), "aliases": list(aliases)},
            )
        key = matches[0]["id"].casefold()
        if key in seen and not allow_duplicate_requests:
            raise SoundBankContractError(
                "DUPLICATE_SCOPE",
                f"{field} must not resolve the same project row twice.",
                details={"value": value, "id": matches[0]["id"]},
            )
        seen.add(key)
        resolved.append(matches[0])
    return resolved


def _normalize_identities(value: Any, *, field: str) -> list[str | int]:
    rows = _require_sequence(value, field=field)
    if len(rows) > MAX_GENERATE_IDENTITIES_PER_BANK:
        raise SoundBankContractError(
            "LIMIT_EXCEEDED",
            f"{field} exceeds the closed identity limit.",
            details={"count": len(rows), "limit": MAX_GENERATE_IDENTITIES_PER_BANK},
        )
    result: list[str | int] = []
    seen: set[str] = set()
    for index, identity in enumerate(rows):
        if isinstance(identity, bool) or not isinstance(identity, (str, int)):
            raise SoundBankContractError(
                "INVALID_ARGUMENT",
                f"{field}[{index}] must be a name, path, GUID, or uint32 identity.",
            )
        if isinstance(identity, int):
            if identity < 0 or identity > 0xFFFFFFFF:
                raise SoundBankContractError("INVALID_ARGUMENT", f"{field}[{index}] is outside uint32.")
            key = f"uint32:{identity}"
        else:
            identity = _require_text(identity, field=f"{field}[{index}]")
            if len(identity) > 512 or any(character in identity for character in ("\r", "\n", "\t")):
                raise SoundBankContractError("INVALID_ARGUMENT", f"{field}[{index}] is not a bounded identity.")
            key = f"string:{identity.casefold()}"
        if key in seen:
            raise SoundBankContractError(
                "DUPLICATE_IDENTITY",
                f"{field} must not contain duplicate identities.",
                details={"index": index, "identity": identity},
            )
        seen.add(key)
        result.append(identity)
    return result


def _normalize_generate_inclusions(value: Any, *, field: str) -> list[str]:
    rows = _require_sequence(value, field=field)
    if not rows:
        raise SoundBankContractError("INVALID_ARGUMENT", f"{field} must not be empty.")
    result: list[str] = []
    for index, inclusion in enumerate(rows):
        if not isinstance(inclusion, str) or inclusion not in _GENERATE_INCLUSIONS:
            raise SoundBankContractError(
                "INVALID_ARGUMENT",
                f"{field}[{index}] is outside the reviewed generate inclusion set.",
                details={"value": inclusion, "supported": list(_GENERATE_INCLUSIONS)},
            )
        if inclusion in result:
            raise SoundBankContractError("DUPLICATE_FILTER", f"{field} must not contain duplicates.")
        result.append(inclusion)
    return [value for value in _GENERATE_INCLUSIONS if value in result]


def _definition_filters(raw: Sequence[str], *, allowed: Sequence[str], row_number: int) -> list[str]:
    if not raw:
        selected = list(allowed)
    else:
        selected = []
        for value in raw:
            if value not in allowed:
                raise SoundBankContractError(
                    "UNSUPPORTED_DEFINITION_FILTER",
                    "Definition row contains a filter unsupported for its object type.",
                    details={"row": row_number, "filter": value, "allowed": list(allowed)},
                )
            if value in selected:
                raise SoundBankContractError(
                    "DUPLICATE_FILTER",
                    "Definition filters must not repeat.",
                    details={"row": row_number, "filter": value},
                )
            selected.append(value)
    return [_DEFINITION_FILTERS[value] for value in allowed if value in selected]


def _definition_quoted_columns(
    text: str,
    parsed_rows: Sequence[Sequence[str]],
) -> tuple[tuple[bool, ...], ...]:
    """Bind decoded TSV cells to the exact, deliberately narrow quote form."""

    physical_rows = text.splitlines()
    if len(physical_rows) != len(parsed_rows):
        raise SoundBankContractError(
            "INVALID_DEFINITION_FILE",
            "Definition quoted fields must not span physical lines.",
        )
    result: list[tuple[bool, ...]] = []
    for row_number, (physical_row, parsed_row) in enumerate(
        zip(physical_rows, parsed_rows, strict=True),
        start=1,
    ):
        raw_cells = physical_row.split("\t")
        if len(raw_cells) != len(parsed_row):
            raise SoundBankContractError(
                "INVALID_DEFINITION_ROW",
                "Definition quoted fields must not contain tabs.",
                details={"row": row_number},
            )
        flags: list[bool] = []
        for column, (raw_cell, parsed_cell) in enumerate(
            zip(raw_cells, parsed_row, strict=True),
            start=1,
        ):
            contains_quote = '"' in raw_cell
            if contains_quote:
                if '"' in parsed_cell or raw_cell != f'"{parsed_cell}"':
                    raise SoundBankContractError(
                        "INVALID_DEFINITION_ROW",
                        "Definition quoting must be exactly one pair of double quotes around an object name.",
                        details={"row": row_number, "column": column},
                    )
                flags.append(True)
            else:
                if raw_cell != parsed_cell:
                    raise SoundBankContractError(
                        "INVALID_DEFINITION_ROW",
                        "Definition field serialization is ambiguous.",
                        details={"row": row_number, "column": column},
                    )
                flags.append(False)
        result.append(tuple(flags))
    return tuple(result)


def _definition_identity(value: str, *, row_number: int) -> dict[str, Any]:
    text = _require_text(value, field=f"row[{row_number}].identity")
    guid_match = _GUID.fullmatch(text)
    if guid_match is not None:
        canonical = "{" + "-".join(group.upper() for group in guid_match.groups()) + "}"
        return {"kind": "guid", "value": canonical}
    if text.startswith(("0x", "0X")):
        try:
            numeric = int(text[2:], 16)
        except ValueError as exc:
            raise SoundBankContractError(
                "INVALID_DEFINITION_IDENTITY",
                "Definition hexadecimal IDs must contain hexadecimal digits.",
                details={"row": row_number, "value": text},
            ) from exc
        if not text[2:] or numeric > 0xFFFFFFFF:
            raise SoundBankContractError(
                "INVALID_DEFINITION_IDENTITY",
                "Definition hexadecimal IDs must fit uint32.",
                details={"row": row_number, "value": text},
            )
        return {"kind": "short_id", "value": numeric, "source_format": "hexadecimal"}
    if text.isdecimal():
        numeric = int(text, 10)
        if numeric > 0xFFFFFFFF:
            raise SoundBankContractError(
                "INVALID_DEFINITION_IDENTITY",
                "Definition decimal IDs must fit uint32.",
                details={"row": row_number, "value": text},
            )
        return {"kind": "short_id", "value": numeric, "source_format": "decimal"}
    if len(text) > 512 or any(character in text for character in ("\\", "/", "\t", "\r", "\n")):
        raise SoundBankContractError(
            "INVALID_DEFINITION_IDENTITY",
            "Definition names must be bounded object names, not paths.",
            details={"row": row_number, "value": text},
        )
    return {"kind": "name", "value": text}


def _identity_key(identity: Mapping[str, Any]) -> str:
    value = identity.get("value")
    return f"{identity.get('kind')}:{value.casefold() if isinstance(value, str) else value}"


def _canonical_wwise_guid(value: Any, *, field: str) -> str:
    text = _require_text(value, field=field)
    match = _GUID.fullmatch(text)
    if match is None:
        raise SoundBankContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{field} must be a canonical braced GUID.",
            details={"value": text},
        )
    return "{" + "-".join(group.upper() for group in match.groups()) + "}"


def _single_direct_xml_child(parent: ET.Element, tag: str, *, field: str) -> ET.Element:
    matches = [child for child in parent if child.tag == tag]
    if len(matches) != 1:
        raise SoundBankContractError(
            "INVALID_PROJECT_FILE",
            f"{field} must contain exactly one direct {tag} element.",
            details={"tag": tag, "count": len(matches)},
        )
    return matches[0]


def _single_project_property(elements: Sequence[ET.Element], name: str) -> ET.Element:
    matches = [element for element in elements if element.attrib.get("Name") == name]
    if len(matches) != 1:
        raise SoundBankContractError(
            "INVALID_PROJECT_CONTEXT",
            f"The Wwise Project must declare exactly one {name} property.",
            details={"property": name, "count": len(matches)},
        )
    return matches[0]


def _project_platform_property_values(
    elements: Sequence[ET.Element],
    name: str,
    *,
    platforms: Sequence[Mapping[str, Any]],
    allow_empty: bool = False,
) -> dict[str, str]:
    property_element = _single_project_property(elements, name)
    _require_xml_attributes(
        property_element.attrib,
        frozenset({"Name", "Type"}),
        field=f"Property[{name}]",
    )
    if property_element.attrib.get("Type") != "string":
        raise SoundBankContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{name} must be a string property.",
        )
    value_list = _single_direct_xml_child(property_element, "ValueList", field=f"Property[{name}]")
    values: dict[str, str] = {}
    known_platforms = {str(platform["name"]) for platform in platforms}
    for index, element in enumerate(value_list):
        if element.tag != "Value":
            raise SoundBankContractError(
                "INVALID_PROJECT_FILE",
                f"Property[{name}].ValueList contains an unsupported child.",
                details={"index": index, "tag": str(element.tag)},
            )
        _require_xml_attributes(
            element.attrib,
            frozenset({"Platform"}),
            field=f"Property[{name}].Value[{index}]",
        )
        platform = _require_text(
            element.attrib.get("Platform"),
            field=f"Property[{name}].Value[{index}].Platform",
        )
        if platform not in known_platforms or platform in values:
            raise SoundBankContractError(
                "INVALID_PROJECT_CONTEXT",
                f"{name} must contain exactly one value for every declared platform.",
                details={"platform": platform, "known": sorted(known_platforms)},
            )
        value = element.text or ""
        if value != value.strip() or "\x00" in value:
            raise SoundBankContractError(
                "INVALID_PROJECT_CONTEXT",
                f"{name}[{platform}] contains outer whitespace or NUL.",
            )
        if not value and not allow_empty:
            raise SoundBankContractError(
                "INVALID_PROJECT_CONTEXT",
                f"{name}[{platform}] must not be empty.",
            )
        values[platform] = value
    if set(values) != known_platforms:
        raise SoundBankContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{name} must contain exactly one value for every declared platform.",
            details={"missing": sorted(known_platforms - set(values))},
        )
    return values


def _resolve_wwise_project_setting_path(
    value: Any,
    *,
    project_root: Path,
    io_root: str | os.PathLike[str],
    field: str,
) -> str:
    text = _require_text(value, field=field)
    if any(token in text for token in ("$", "%")) or text.startswith("~") or _is_absolute_path_text(text):
        raise SoundBankContractError(
            "UNSAFE_PROJECT_PATH",
            f"{field} must be a literal path relative to the Project root.",
            details={"value": text},
        )
    parts = list(_portable_path_parts(text))
    while parts and parts[-1] == "":
        parts.pop()
    if not parts or any(
        part in {"", "."}
        or part != part.strip()
        or any(ord(character) < 32 or character in _UNSAFE_DESTINATION_CHARS for character in part)
        for part in parts
    ):
        raise SoundBankContractError(
            "UNSAFE_PROJECT_PATH",
            f"{field} contains an unsafe path segment.",
            details={"value": text},
        )
    candidate = project_root.joinpath(*parts)
    proof = prove_artifact_path(
        candidate,
        io_root=io_root,
        field=field,
        must_exist=False,
        expect_directory=True,
    )
    return str(proof["resolved_path"])


def _read_proven_bytes(
    value: str | os.PathLike[str],
    *,
    field: str,
    max_bytes: int,
) -> tuple[Path, bytes, dict[str, Any]]:
    proof = capture_file_proof(value, field=field, max_bytes=max_bytes)
    path = Path(proof["path"])
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SoundBankContractError(
            "INVALID_FILE",
            f"{field} could not be read.",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if hashlib.sha256(data).hexdigest() != proof["sha256"] or len(data) != proof["size"]:
        raise SoundBankContractError(
            "FILE_CHANGED",
            f"{field} changed while it was parsed.",
            details={"path": str(path)},
        )
    return path, data, proof


def _open_regular_file(
    value: str | os.PathLike[str],
    *,
    field: str,
) -> tuple[Path, int, os.stat_result]:
    supplied = _absolute_path(value, field=field)
    try:
        leaf_stat = supplied.lstat()
    except OSError as exc:
        raise SoundBankContractError(
            "INVALID_FILE",
            f"{field} is not accessible.",
            details={"path": str(supplied), "error": str(exc)},
        ) from exc
    if stat.S_ISLNK(leaf_stat.st_mode):
        raise SoundBankContractError(
            "SYMLINK_NOT_ALLOWED",
            f"{field} must not be a symbolic link.",
            details={"path": str(supplied)},
        )
    if not stat.S_ISREG(leaf_stat.st_mode):
        raise SoundBankContractError(
            "INVALID_FILE",
            f"{field} must identify a regular file, not a directory or device.",
            details={"path": str(supplied)},
        )
    descriptor: int | None = None
    try:
        path = supplied.resolve(strict=True)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened_stat = os.fstat(descriptor)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise SoundBankContractError(
            "INVALID_FILE",
            f"{field} could not be opened.",
            details={"path": str(supplied), "error": str(exc)},
        ) from exc
    if not stat.S_ISREG(opened_stat.st_mode) or (
        leaf_stat.st_dev,
        leaf_stat.st_ino,
    ) != (
        opened_stat.st_dev,
        opened_stat.st_ino,
    ):
        os.close(descriptor)
        raise SoundBankContractError(
            "FILE_CHANGED",
            f"{field} changed while it was opened.",
            details={"path": str(path)},
        )
    return path, descriptor, opened_stat


def _require_unchanged_file_stat(
    before: os.stat_result,
    after: os.stat_result,
    *,
    field: str,
    path: Path,
) -> None:
    identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, name) != getattr(after, name) for name in identity):
        raise SoundBankContractError(
            "FILE_CHANGED",
            f"{field} changed while its proof was captured.",
            details={"path": str(path)},
        )


def _resolve_xml_path(value: str, *, base: Path, field: str) -> Path:
    if _is_windows_absolute(value) and os.name != "nt":
        raise SoundBankContractError(
            "PATH_FLAVOR_MISMATCH",
            f"{field} uses a Windows absolute path on a non-Windows host.",
            details={"value": value},
        )
    normalized = value if os.name == "nt" else value.replace("\\", "/")
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:
        raise SoundBankContractError(
            "INVALID_FILE",
            f"{field} could not be resolved.",
            details={"value": value, "base": str(base), "error": str(exc)},
        ) from exc


def _normalized_destination(value: str, *, field: str) -> str:
    if _is_absolute_path_text(value):
        raise SoundBankContractError("INVALID_DESTINATION", f"{field} destination must be relative.")
    parts = _portable_path_parts(value)
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SoundBankContractError(
            "INVALID_DESTINATION",
            f"{field} contains an empty, dot, or dot-dot destination segment.",
            details={"value": value},
        )
    for part in parts:
        if part != part.strip() or part.endswith((".", " ")) or any(
            ord(character) < 32 or character in _UNSAFE_DESTINATION_CHARS for character in part
        ):
            raise SoundBankContractError(
                "INVALID_DESTINATION",
                f"{field} contains an unsafe destination segment.",
                details={"segment": part},
            )
    relative = PurePosixPath(*parts)
    filename = relative.name
    if filename in {"", ".", ".."}:
        raise SoundBankContractError("INVALID_DESTINATION", f"{field} must include a destination filename.")
    return relative.with_suffix(".wem").as_posix()


def _portable_path_parts(value: str) -> tuple[str, ...]:
    return tuple(part for part in re.split(r"[\\/]", value))


def _is_absolute_path_text(value: str) -> bool:
    return value.startswith(("/", "\\")) or _is_windows_absolute(value)


def _is_windows_absolute(value: str) -> bool:
    return _WINDOWS_DRIVE.match(value) is not None or _WINDOWS_UNC.match(value) is not None


def _require_xml_attributes(attributes: Mapping[str, str], allowed: frozenset[str], *, field: str) -> None:
    extras = sorted(set(attributes) - allowed)
    if extras:
        raise SoundBankContractError(
            "UNSUPPORTED_XML_ATTRIBUTE",
            f"{field} contains attributes outside the reviewed schema.",
            details={"unsupported": extras, "allowed": sorted(allowed)},
        )


def _snapshot_rows(snapshot: Mapping[str, Any], *, field: str) -> dict[str, Mapping[str, Any]]:
    rows = snapshot.get("files")
    if not isinstance(rows, list):
        raise SoundBankContractError("INVALID_SNAPSHOT", f"{field}.files must be a JSON array.")
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str):
            raise SoundBankContractError(
                "INVALID_SNAPSHOT",
                f"{field}.files entries must be objects with paths.",
                details={"index": index},
            )
        path = _relative_path(row["path"], field=f"{field}.files[{index}].path")
        if path in result:
            raise SoundBankContractError("INVALID_SNAPSHOT", f"{field}.files contains duplicate paths.")
        result[path] = row
    return result


def _relative_path_set(values: Sequence[str], *, field: str) -> set[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise SoundBankContractError("INVALID_ARGUMENT", f"{field} must be a JSON array.")
    result: set[str] = set()
    for index, value in enumerate(values):
        path = _relative_path(value, field=f"{field}[{index}]")
        if path in result:
            raise SoundBankContractError("DUPLICATE_TARGET", f"{field} must not contain duplicates.")
        result.add(path)
    return result


def _relative_path(value: Any, *, field: str) -> str:
    text = _require_text(value, field=field).replace("\\", "/")
    if _is_absolute_path_text(text):
        raise SoundBankContractError("INVALID_ARGUMENT", f"{field} must be relative.")
    raw_parts = text.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise SoundBankContractError("INVALID_ARGUMENT", f"{field} contains an unsafe path segment.")
    path = PurePosixPath(text)
    return path.as_posix()


def _require_io_root(value: str | os.PathLike[str]) -> Path:
    supplied = _absolute_path(value, field="io_root")
    try:
        root_stat = supplied.lstat()
    except OSError as exc:
        raise SoundBankContractError(
            "INVALID_IO_ROOT",
            "io_root must be an existing directory.",
            details={"path": str(supplied), "error": str(exc)},
        ) from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise SoundBankContractError(
            "INVALID_IO_ROOT",
            "io_root must be a real directory, not a file or symbolic link.",
            details={"path": str(supplied)},
        )
    return supplied.resolve(strict=True)


def _absolute_path(value: str | os.PathLike[str] | Any, *, field: str) -> Path:
    path_text = os.fspath(value) if isinstance(value, os.PathLike) else value
    if not isinstance(path_text, str) or not path_text or "\x00" in path_text:
        raise SoundBankContractError("INVALID_PATH", f"{field} must be an absolute path string.")
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        raise SoundBankContractError(
            "INVALID_PATH",
            f"{field} must be absolute.",
            details={"path": path_text},
        )
    return path


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _require_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SoundBankContractError("INVALID_ARGUMENT", f"{field} must be a JSON object.")
    return value


def _require_sequence(value: Any, *, field: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SoundBankContractError("INVALID_ARGUMENT", f"{field} must be a JSON array.")
    return list(value)


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str],
    context: str,
) -> None:
    keys = set(value)
    missing = sorted(required - keys)
    unsupported = sorted(keys - required - optional)
    if missing or unsupported:
        raise SoundBankContractError(
            "INVALID_ARGUMENT",
            f"{context} does not match the closed schema.",
            details={"missing": missing, "unsupported": unsupported},
        )


def _require_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise SoundBankContractError(
            "INVALID_ARGUMENT",
            f"{field} must be a non-empty string without outer whitespace or NUL.",
        )
    return value


def _require_bank_name(value: Any, *, field: str) -> str:
    name = _require_text(value, field=field)
    if len(name) > 128 or _BANK_NAME.fullmatch(name) is None:
        raise SoundBankContractError(
            "INVALID_SOUNDBANK_NAME",
            f"{field} must use the closed portable SoundBank naming subset.",
            details={"value": name, "pattern": _BANK_NAME.pattern, "max_length": 128},
        )
    return name


def _safe_artifact_segment(value: Any, *, field: str) -> str:
    segment = _require_text(value, field=field)
    if segment in {".", ".."} or any(
        ord(character) < 32 or character in {"/", "\\"} for character in segment
    ):
        raise SoundBankContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{field} cannot be represented as one artifact path segment.",
            details={"value": segment},
        )
    return segment


def _require_bool(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise SoundBankContractError("INVALID_ARGUMENT", f"{field} must be a boolean.")
    return value


def _optional_bool(
    value: Mapping[str, Any],
    key: str,
    *,
    default: bool,
    field: str | None = None,
) -> bool:
    return default if key not in value else _require_bool(value.get(key), field=field or key)


def _require_nonempty_strings(value: Any, *, field: str, limit: int) -> list[str]:
    rows = _require_sequence(value, field=field)
    if not rows or len(rows) > limit:
        raise SoundBankContractError(
            "INVALID_SCOPE",
            f"{field} must be a non-empty bounded array.",
            details={"count": len(rows), "limit": limit},
        )
    result = [_require_text(item, field=f"{field}[{index}]") for index, item in enumerate(rows)]
    if len({item.casefold() for item in result}) != len(result):
        raise SoundBankContractError("DUPLICATE_SCOPE", f"{field} must not contain duplicate labels.")
    return result


def _require_version(value: Any, *, supported: Sequence[str]) -> str:
    if not isinstance(value, str) or value not in supported:
        raise SoundBankContractError(
            "UNSUPPORTED_VERSION",
            "The SoundBank contract is unavailable for this Wwise version.",
            details={"version": value, "supported": list(supported)},
        )
    return value


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _dedupe_path_proofs(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = str(value["resolved_path"]).casefold()
        if key not in seen:
            seen.add(key)
            result.append(dict(value))
    return result


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    payload = dict(value)
    payload[field] = canonical_sha256(payload)
    return payload


def _require_sealed(
    value: Mapping[str, Any],
    *,
    contract: str,
    seal_field: str,
    field: str,
) -> None:
    if not isinstance(value, Mapping) or value.get("contract") != contract:
        raise SoundBankContractError(
            "INVALID_EVIDENCE",
            f"{field} does not use the expected contract.",
            details={"expected_contract": contract},
        )
    expected = value.get(seal_field)
    if not isinstance(expected, str) or len(expected) != 64:
        raise SoundBankContractError("INVALID_EVIDENCE", f"{field} lacks a valid SHA-256 seal.")
    body = {key: item for key, item in value.items() if key != seal_field}
    actual = canonical_sha256(body)
    if actual != expected:
        raise SoundBankContractError(
            "EVIDENCE_TAMPERED",
            f"{field} SHA-256 seal does not match its contents.",
            details={"expected": expected, "actual": actual},
        )


__all__ = [
    "ARTIFACT_DELTA_CONTRACT",
    "ARTIFACT_PATH_PROOF_CONTRACT",
    "ARTIFACT_TREE_CONTRACT",
    "DEFINITION_FILE_CONTRACT",
    "DEFINITION_PLAN_CONTRACT",
    "EXTERNAL_SOURCES_FILE_CONTRACT",
    "EXTERNAL_SOURCES_PLAN_CONTRACT",
    "FILE_PROOF_CONTRACT",
    "GENERATE_PLAN_CONTRACT",
    "POST_2021_WWISE_VERSIONS",
    "SUPPORTED_WWISE_VERSIONS",
    "WWISE_2021_PROJECT_FILE_CONTRACT",
    "WWISE_2021_LANGUAGE_INVENTORY_CONTRACT",
    "SoundBankContractError",
    "build_external_sources_operation_plan",
    "build_generate_operation_plan",
    "build_process_definition_operation_plan",
    "capture_artifact_tree",
    "capture_file_proof",
    "compare_artifact_trees",
    "parse_external_sources_file",
    "parse_soundbank_definition_file",
    "parse_wwise_2021_project_file",
    "parse_wwise_2021_language_inventory",
    "prove_artifact_path",
    "verify_file_proof",
]
