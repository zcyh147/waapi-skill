"""Pure, closed contracts for the packaged audio-import operations.

The public operation registry deliberately owns live identity resolution and
dispatch.  This module owns the parts that can be proved without a Wwise
connection: a small JSON DSL, import-operation policy, source-file provenance,
and deterministic parsing of tab-delimited import files.  It never writes a
file and never calls WAAPI.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence


AUDIO_IMPORT_PLAN_CONTRACT = "waapi-skill.audio-import-plan/v1"
TAB_IMPORT_PLAN_CONTRACT = "waapi-skill.tab-import-plan/v1"
SUPPORTED_WWISE_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
SUPPORTED_IMPORT_OPERATIONS = ("createNew", "useExisting", "replaceExisting")

# Wwise 2022 evidence establishes only audioFile/objectPath/importLanguage for
# a useExisting row that resolves to a localized object.  The fields below are
# therefore creation- or placement-sensitive at that boundary; they must not
# be silently removed from a caller's request.
# A useExisting request may legitimately mix live and absent target paths, so
# the registry applies this row policy only after it has captured each path's
# actual pre-state.
LOCALIZED_EXISTING_UNSUPPORTED_FIELDS = (
    "originals_subfolder",
    "notes",
    "audio_source_notes",
    "event",
)

MAX_IMPORT_ITEMS = 128
MAX_TAB_BYTES = 256 * 1024
MAX_TAB_ROWS = 128
MAX_TAB_COLUMNS = 16
MAX_TAB_CELL_CHARS = 16 * 1024
MAX_TEXT_CHARS = 16 * 1024

_AUDIO_IMPORT_REQUIRED_FIELDS = frozenset({"object_path", "audio_file"})
_AUDIO_IMPORT_OPTIONAL_FIELDS = frozenset(
    {
        "object_type",
        "import_language",
        "originals_subfolder",
        "notes",
        "audio_source_notes",
        "event",
    }
)
_EVENT_ACTIONS = frozenset({"Play", "Stop", "Pause", "Resume", "Break", "Seek"})
_TYPED_PATH_SEGMENT = re.compile(r"^<([^<>]+)>([^<>]+)$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")

IMPORT_ROOTS_BY_VERSION: Mapping[str, frozenset[str]] = {
    "2021.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2022.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2023.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2024.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2025.1": frozenset({"Containers", "Interactive Music Hierarchy"}),
}

# Keep the map versioned even while the reviewed subset is identical.  A future
# Wwise lane can then change without silently widening the other four lanes.
_TAB_HEADERS = frozenset(
    {
        "Audio File",
        "Object Path",
        "Object Type",
        "OriginalsSubFolder",
        "Notes",
        "Audio Source Notes",
        "Event",
    }
)
TAB_HEADERS_BY_VERSION: Mapping[str, frozenset[str]] = {
    version: _TAB_HEADERS for version in SUPPORTED_WWISE_VERSIONS
}
REQUIRED_TAB_HEADERS = frozenset({"Audio File", "Object Path"})

# Both WAAPI/internal names and the reviewed tab-import display names are
# accepted.  Unknown strings are rejected rather than passed through.
_IMPORT_OBJECT_TYPES = frozenset(
    {
        "Actor-Mixer",
        "ActorMixer",
        "Blend Container",
        "BlendContainer",
        "Folder",
        "Music Playlist Container",
        "Music Segment",
        "Music Switch Container",
        "Music Track",
        "MusicRanSeqCntr",
        "MusicSegment",
        "MusicSwitchContainer",
        "MusicTrack",
        "Property Container",
        "Random Container",
        "RandomSequenceContainer",
        "Sequence Container",
        "Sound",
        "Sound SFX",
        "Sound Voice",
        "Switch Container",
        "SwitchContainer",
        "Virtual Folder",
    }
)


class ImportContractError(ValueError):
    """A closed import request or source artifact failed validation."""

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


def import_operation_policy(import_operation: str) -> dict[str, Any]:
    """Return the immutable collision, identity, and cleanup policy."""

    operation = _require_import_operation(import_operation)
    common: dict[str, Any] = {
        "import_operation": operation,
        "one_global_operation_per_call": True,
        "pre_state_required": True,
        "confirmation_time_drift_check_required": True,
        "verify_every_derived_target": True,
        "partial_success_is_failure": True,
        "automatic_retry": False,
    }
    if operation == "createNew":
        return common | {
            "collision_policy": "exact_target_must_be_absent",
            "existing_target_postcondition": "not_applicable",
            "absent_target_postcondition": "new_unique_guid_at_exact_path",
            "cleanup_policy": "delete_created_guids_then_discard_owned_project_copy_for_media",
            "disposable_project_required": False,
            "owned_project_copy_required_for_clean_test": True,
            "in_place_restore_supported": False,
        }
    if operation == "useExisting":
        return common | {
            "collision_policy": "reuse_exact_existing_target_else_create",
            "existing_target_postcondition": "guid_preserved_and_media_source_updated",
            "notes_destination_policy": (
                "preexisting_target_routes_notes_to_new_audio_file_source;"
                "absent_target_routes_notes_to_created_target"
            ),
            "absent_target_postcondition": "new_unique_guid_at_exact_path",
            "cleanup_policy": "discard_owned_project_copy_when_existing_media_was_updated",
            "disposable_project_required": False,
            "owned_project_copy_required_for_clean_test": True,
            "in_place_restore_supported": False,
        }
    return common | {
        "collision_policy": "destroy_exact_existing_target_then_create_replacement",
        "existing_target_postcondition": "old_guid_absent_and_new_guid_distinct",
        "absent_target_postcondition": "new_unique_guid_at_exact_path",
        "cleanup_policy": "discard_owned_project_copy; in_place_restore_is_not_claimed",
        "disposable_project_required": True,
        "owned_project_copy_required_for_clean_test": True,
        "in_place_restore_supported": False,
    }


def unsupported_localized_existing_fields(
    *,
    import_language: Any,
    originals_subfolder_supplied: bool,
    notes_supplied: bool,
    audio_source_notes_supplied: bool,
    event_supplied: bool,
) -> tuple[str, ...]:
    """Return fields unsafe on an existing localized useExisting target.

    Wwise's import operation is call-wide, but localization state is row-wide:
    some useExisting rows can resolve to live Sound Voice objects while other
    rows in the same call are still absent.  The caller must therefore invoke
    this only for a row already proven to exist.  ``SFX`` and rows without an
    explicit language are outside this narrow localized boundary.
    """

    if not isinstance(import_language, str) or import_language.casefold() == "sfx":
        return ()
    requested: list[str] = []
    if originals_subfolder_supplied:
        requested.append("originals_subfolder")
    if notes_supplied:
        requested.append("notes")
    if audio_source_notes_supplied:
        requested.append("audio_source_notes")
    if event_supplied:
        requested.append("event")
    return tuple(requested)


def regular_file_proof(value: str | os.PathLike[str], *, field: str) -> dict[str, Any]:
    """Hash one absolute, non-symlink regular file without following the leaf."""

    path, opened = _open_regular_file(value, field=field)
    digest = hashlib.sha256()
    try:
        with opened:
            before = os.fstat(opened.fileno())
            for chunk in iter(lambda: opened.read(1024 * 1024), b""):
                digest.update(chunk)
            after = os.fstat(opened.fileno())
    except OSError as exc:
        raise ImportContractError(
            "INVALID_FILE",
            f"{field} could not be hashed.",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    _require_unchanged_stat(before, after, field=field, path=path)
    return _file_proof(path, after, digest.hexdigest())


def verify_regular_file_proof(proof: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    """Recompute a proof and fail if the immutable preview input drifted."""

    if not isinstance(proof, Mapping):
        raise ImportContractError("INVALID_FILE_PROOF", f"{field} proof must be a JSON object.")
    expected_path = proof.get("path")
    if not isinstance(expected_path, str):
        raise ImportContractError("INVALID_FILE_PROOF", f"{field} proof requires path.")
    actual = regular_file_proof(expected_path, field=field)
    compared = ("path", "size", "sha256", "mtime_ns", "device", "inode")
    if any(actual.get(key) != proof.get(key) for key in compared):
        raise ImportContractError(
            "FILE_CHANGED",
            f"{field} changed after preview.",
            details={"expected": dict(proof), "actual": actual},
        )
    return actual


def build_audio_import_plan(
    imports: Sequence[Mapping[str, Any]],
    *,
    version: str,
    import_operation: str,
) -> dict[str, Any]:
    """Normalize the closed ``audio.import`` item DSL into a JSON plan."""

    lane = _require_version(version)
    policy = import_operation_policy(import_operation)
    if isinstance(imports, (str, bytes)) or not isinstance(imports, Sequence):
        raise ImportContractError("INVALID_ARGUMENT", "imports must be a JSON array.")
    if not imports:
        raise ImportContractError("INVALID_ARGUMENT", "audio.import requires at least one item.")
    if len(imports) > MAX_IMPORT_ITEMS:
        raise ImportContractError(
            "LIMIT_EXCEEDED",
            "audio.import exceeds the closed item limit.",
            details={"count": len(imports), "limit": MAX_IMPORT_ITEMS},
        )

    dispatch_rows: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    file_proofs: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for index, raw in enumerate(imports):
        if not isinstance(raw, Mapping):
            raise ImportContractError(
                "INVALID_ARGUMENT",
                "Every audio.import item must be a JSON object.",
                details={"index": index},
            )
        _require_exact_keys(
            raw,
            required=_AUDIO_IMPORT_REQUIRED_FIELDS,
            optional=_AUDIO_IMPORT_OPTIONAL_FIELDS,
            context=f"imports[{index}]",
        )
        object_path = _require_text(raw.get("object_path"), field=f"imports[{index}].object_path")
        target = canonical_import_target(object_path, version=lane)
        target_key = target["canonical_target_path"].casefold()
        if target_key in seen_targets:
            raise ImportContractError(
                "DUPLICATE_TARGET",
                "audio.import target paths must be unique.",
                details={"index": index, "target_path": target["canonical_target_path"]},
            )
        seen_targets.add(target_key)

        proof = regular_file_proof(raw.get("audio_file"), field=f"imports[{index}].audio_file")
        _require_media_extension(proof["path"], field=f"imports[{index}].audio_file")
        dispatch: dict[str, Any] = {"objectPath": object_path, "audioFile": proof["path"]}
        oracle_row: dict[str, Any] = {
            "index": index,
            **target,
            "source_file": dict(proof),
            "pre_state_required": True,
        }
        expected_source_path = expected_audio_file_source_result_path(
            target["canonical_target_path"],
            proof["path"],
        )
        if expected_source_path is not None:
            oracle_row["expected_audio_file_source_result_path"] = expected_source_path

        if "object_type" in raw:
            object_type = _require_object_type(raw.get("object_type"), field=f"imports[{index}].object_type")
            dispatch["objectType"] = object_type
            oracle_row["requested_object_type"] = object_type
        if "import_language" in raw:
            language = _require_language(raw.get("import_language"), field=f"imports[{index}].import_language")
            dispatch["importLanguage"] = language
            oracle_row["requested_language"] = language
        if "originals_subfolder" in raw:
            subfolder = _require_originals_subfolder(
                raw.get("originals_subfolder"),
                field=f"imports[{index}].originals_subfolder",
            )
            dispatch["originalsSubFolder"] = subfolder
            oracle_row["requested_originals_subfolder"] = subfolder
        for public_name, waapi_name in (("notes", "notes"), ("audio_source_notes", "audioSourceNotes")):
            if public_name in raw:
                value = _require_bounded_text(raw.get(public_name), field=f"imports[{index}].{public_name}")
                dispatch[waapi_name] = value
                oracle_row[f"requested_{public_name}"] = value
        if "event" in raw:
            event = _normalize_structured_event(raw.get("event"), field=f"imports[{index}].event")
            dispatch["event"] = event["waapi_value"]
            oracle_row["requested_event"] = {key: value for key, value in event.items() if key != "waapi_value"}

        dispatch_rows.append(dispatch)
        file_proofs.append({"index": index, **proof})
        targets.append(oracle_row)

    dispatch_args: dict[str, Any] = {
        "imports": dispatch_rows,
        "importOperation": policy["import_operation"],
        "autoAddToSourceControl": False,
    }
    if lane in {"2023.1", "2024.1", "2025.1"}:
        dispatch_args["autoCheckOutToSourceControl"] = False
    return {
        "contract": AUDIO_IMPORT_PLAN_CONTRACT,
        "version": lane,
        "dispatch_args": dispatch_args,
        "file_proofs": file_proofs,
        "operation_policy": policy,
        "oracle": {
            "derived_from": "closed_request_and_hashed_source_files",
            "targets": targets,
            "result_contract": "objects_only" if lane in {"2021.1", "2022.1"} else "required_log_files_objects",
            "language_requires_live_project_validation": any(
                language_requires_live_project_validation(row.get("requested_language"))
                for row in targets
            ),
            "event_side_effects_present": any("requested_event" in row for row in targets),
            "media_hash_readback_required": True,
            "no_retry_after_dispatch": True,
        },
    }


def parse_tab_delimited_import_file(
    import_file: str | os.PathLike[str],
    *,
    version: str,
    import_location: str,
    import_language: str,
    import_operation: str,
) -> dict[str, Any]:
    """Parse and prove a reviewed UTF-8 TSV subset without trusting caller rows."""

    lane = _require_version(version)
    policy = import_operation_policy(import_operation)
    location = canonical_import_location(import_location, version=lane)
    language = _require_language(import_language, field="import_language")
    path, data, import_file_proof = _read_proven_bytes(
        import_file,
        field="import_file",
        max_bytes=MAX_TAB_BYTES,
    )
    if data.startswith(b"\xef\xbb\xbf"):
        raise ImportContractError("INVALID_ENCODING", "import_file must be UTF-8 without a byte-order mark.")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ImportContractError(
            "INVALID_ENCODING",
            "import_file must be strict UTF-8.",
            details={"path": str(path), "start": exc.start},
        ) from exc
    if "\x00" in text:
        raise ImportContractError("INVALID_TAB_FILE", "import_file must not contain NUL characters.")
    if re.search(r"\r(?!\n)", text):
        raise ImportContractError("INVALID_TAB_FILE", "import_file must use LF or CRLF line endings, not bare CR.")

    try:
        parsed = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t", strict=True))
    except csv.Error as exc:
        raise ImportContractError(
            "INVALID_TAB_FILE",
            "import_file is not valid tab-delimited data.",
            details={"error": str(exc)},
        ) from exc
    if not parsed or not parsed[0]:
        raise ImportContractError("INVALID_TAB_FILE", "import_file requires a header row.")
    headers = parsed[0]
    _validate_tab_headers(headers, version=lane)
    _validate_wwise_physical_tab_records(
        text,
        column_count=len(headers),
        parsed_record_count=len(parsed),
    )
    raw_rows = parsed[1:]
    if not raw_rows:
        raise ImportContractError("INVALID_TAB_FILE", "import_file requires at least one data row.")
    if len(raw_rows) > MAX_TAB_ROWS:
        raise ImportContractError(
            "LIMIT_EXCEEDED",
            "import_file exceeds the closed row limit.",
            details={"rows": len(raw_rows), "limit": MAX_TAB_ROWS},
        )

    rows: list[dict[str, Any]] = []
    target_oracle: list[dict[str, Any]] = []
    source_proofs: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for offset, cells in enumerate(raw_rows, start=2):
        if not cells or all(cell == "" for cell in cells):
            raise ImportContractError(
                "INVALID_TAB_FILE",
                "import_file contains an empty data row.",
                details={"row": offset},
            )
        if len(cells) != len(headers):
            raise ImportContractError(
                "INVALID_TAB_FILE",
                "Every tab-delimited row must have exactly the header column count.",
                details={"row": offset, "expected": len(headers), "actual": len(cells)},
            )
        for column, cell in zip(headers, cells, strict=True):
            if len(cell) > MAX_TAB_CELL_CHARS:
                raise ImportContractError(
                    "LIMIT_EXCEEDED",
                    "A tab-delimited cell exceeds the closed character limit.",
                    details={"row": offset, "column": column, "limit": MAX_TAB_CELL_CHARS},
                )
        fields = dict(zip(headers, cells, strict=True))
        audio_file = _require_text(fields["Audio File"], field=f"row[{offset}].Audio File")
        proof = regular_file_proof(audio_file, field=f"row[{offset}].Audio File")
        _require_media_extension(proof["path"], field=f"row[{offset}].Audio File")
        object_path = _require_text(fields["Object Path"], field=f"row[{offset}].Object Path")
        target = derive_tab_target(object_path, import_location=location, version=lane)
        target_key = target["canonical_target_path"].casefold()
        if target_key in seen_targets:
            raise ImportContractError(
                "DUPLICATE_TARGET",
                "import_file target paths must be unique.",
                details={"row": offset, "target_path": target["canonical_target_path"]},
            )
        seen_targets.add(target_key)

        row_plan: dict[str, Any] = {
            "row_number": offset,
            "audio_file": proof["path"],
            "object_path": object_path,
            **target,
        }
        oracle_row: dict[str, Any] = {
            "row_number": offset,
            **target,
            "source_file": dict(proof),
            "requested_language": language,
            "pre_state_required": True,
        }
        expected_source_path = expected_audio_file_source_result_path(
            target["canonical_target_path"],
            proof["path"],
        )
        if expected_source_path is not None:
            oracle_row["expected_audio_file_source_result_path"] = expected_source_path
        if fields.get("Object Type"):
            object_type = _require_object_type(fields["Object Type"], field=f"row[{offset}].Object Type")
            row_plan["object_type"] = object_type
            oracle_row["requested_object_type"] = object_type
        if fields.get("OriginalsSubFolder"):
            subfolder = _require_originals_subfolder(
                fields["OriginalsSubFolder"],
                field=f"row[{offset}].OriginalsSubFolder",
            )
            row_plan["originals_subfolder"] = subfolder
            oracle_row["requested_originals_subfolder"] = subfolder
        for header, key in (("Notes", "notes"), ("Audio Source Notes", "audio_source_notes")):
            if fields.get(header):
                value = _require_bounded_text(fields[header], field=f"row[{offset}].{header}")
                row_plan[key] = value
                oracle_row[f"requested_{key}"] = value
        if fields.get("Event"):
            event = _parse_tab_event(fields["Event"], field=f"row[{offset}].Event")
            row_plan["event"] = {key: value for key, value in event.items() if key != "waapi_value"}
            oracle_row["requested_event"] = dict(row_plan["event"])

        rows.append(row_plan)
        source_proofs.append({"row_number": offset, **proof})
        target_oracle.append(oracle_row)

    dispatch_args: dict[str, Any] = {
        "importFile": str(path),
        "importLocation": location,
        "importLanguage": language,
        "importOperation": policy["import_operation"],
        "autoAddToSourceControl": False,
    }
    if lane in {"2023.1", "2024.1", "2025.1"}:
        dispatch_args["autoCheckOutToSourceControl"] = False
    return {
        "contract": TAB_IMPORT_PLAN_CONTRACT,
        "version": lane,
        "dispatch_args": dispatch_args,
        "headers": list(headers),
        "rows": rows,
        "import_file_proof": import_file_proof,
        "source_file_proofs": source_proofs,
        "operation_policy": policy,
        "oracle": {
            "derived_from": {
                "import_file_path": str(path),
                "import_file_sha256": import_file_proof["sha256"],
                "caller_expected_rows_accepted": False,
            },
            "targets": target_oracle,
            "result_contract": "objects_only",
            "language_requires_live_project_validation": (
                language_requires_live_project_validation(language)
            ),
            "event_side_effects_present": any("requested_event" in row for row in target_oracle),
            "all_sources_validated_before_dispatch": True,
            "missing_or_unreadable_source_policy": "reject_before_preview_and_dispatch",
            "media_hash_readback_required": True,
            "no_retry_after_dispatch": True,
        },
    }


def canonical_import_target(object_path: str, *, version: str) -> dict[str, str]:
    """Derive the exact untyped target and parent paths for one absolute row."""

    lane = _require_version(version)
    segments = _canonical_wwise_segments(object_path, field="object_path", absolute=True)
    if len(segments) < 3:
        raise ImportContractError(
            "INVALID_TARGET",
            "object_path must name an object below a top-level Work Unit.",
            details={"object_path": object_path},
        )
    _require_import_root(segments[0], version=lane, field="object_path")
    return {
        "canonical_target_path": "\\" + "\\".join(segments),
        "canonical_parent_path": "\\" + "\\".join(segments[:-1]),
    }


def expected_audio_file_source_result_path(
    canonical_target_path: str,
    source_file_path: str,
) -> str | None:
    """Seal the exact AudioFileSource result path for reviewed audio media.

    Wwise names the AudioFileSource child from the imported audio filename,
    without its extension.  MIDI imports have a different object topology and
    therefore deliberately do not claim this AudioFileSource result contract.
    """

    target_segments = _canonical_wwise_segments(
        canonical_target_path,
        field="canonical_target_path",
        absolute=True,
    )
    source_path = Path(source_file_path)
    extension = source_path.suffix.casefold()
    if extension in {".mid", ".midi"}:
        return None
    if extension not in {".wav", ".amb"}:
        raise ImportContractError(
            "INVALID_FILE",
            "source_file_path does not use a reviewed AudioFileSource extension.",
            details={"path": source_file_path, "supported_extensions": [".amb", ".wav"]},
        )
    source_name = source_path.stem
    if (
        not source_name
        or source_name != source_name.strip()
        or source_name in {".", ".."}
        or any(character in source_name for character in '<>:"/\\|?*\x00\r\n\t')
    ):
        raise ImportContractError(
            "INVALID_FILE",
            "The imported audio filename cannot be sealed to one exact Wwise AudioFileSource child.",
            details={"path": source_file_path, "stem": source_name},
        )
    return "\\" + "\\".join((*target_segments, source_name))


def canonical_import_location(import_location: str, *, version: str) -> str:
    """Normalize one already live-resolved absolute import-location path."""

    lane = _require_version(version)
    segments = _canonical_wwise_segments(import_location, field="import_location", absolute=True)
    if len(segments) < 2:
        raise ImportContractError(
            "INVALID_TARGET",
            "import_location must name a top-level Work Unit or a descendant.",
            details={"import_location": import_location},
        )
    _require_import_root(segments[0], version=lane, field="import_location")
    return "\\" + "\\".join(segments)


def derive_tab_target(object_path: str, *, import_location: str, version: str) -> dict[str, str]:
    """Resolve a tab row's absolute or relative object path deterministically."""

    lane = _require_version(version)
    location = canonical_import_location(import_location, version=lane)
    if object_path.startswith("\\"):
        return canonical_import_target(object_path, version=lane)
    relative = _canonical_wwise_segments(object_path, field="Object Path", absolute=False)
    location_segments = location[1:].split("\\")
    combined = "\\" + "\\".join([*location_segments, *relative])
    return canonical_import_target(combined, version=lane)


def _validate_tab_headers(headers: Sequence[str], *, version: str) -> None:
    if len(headers) > MAX_TAB_COLUMNS:
        raise ImportContractError(
            "LIMIT_EXCEEDED",
            "import_file exceeds the closed column limit.",
            details={"columns": len(headers), "limit": MAX_TAB_COLUMNS},
        )
    if any(not header for header in headers):
        raise ImportContractError("INVALID_TAB_FILE", "import_file header names must not be empty.")
    if len(set(headers)) != len(headers):
        raise ImportContractError(
            "INVALID_TAB_FILE",
            "Duplicate tab-delimited headers are not supported by the closed parser.",
            details={"headers": list(headers)},
        )
    allowed = TAB_HEADERS_BY_VERSION[version]
    unsupported = sorted(set(headers) - allowed)
    if unsupported:
        raise ImportContractError(
            "UNSUPPORTED_COLUMN",
            "import_file contains columns outside the reviewed closed subset.",
            details={"version": version, "unsupported": unsupported, "allowed": sorted(allowed)},
        )
    missing = sorted(REQUIRED_TAB_HEADERS - set(headers))
    if missing:
        raise ImportContractError(
            "INVALID_TAB_FILE",
            "import_file is missing required columns.",
            details={"missing": missing},
        )


def _validate_wwise_physical_tab_records(
    text: str,
    *,
    column_count: int,
    parsed_record_count: int,
) -> None:
    """Reject CSV-style embedded row/column separators before Wwise dispatch.

    Python's CSV reader accepts a quoted tab or line break as cell content, but
    Wwise's tab-delimited importer treats those bytes as physical separators.
    A file accepted under the broader CSV grammar can therefore create parent
    containers and still omit every leaf Sound.  Keep the packaged contract on
    the narrower grammar proven by Wwise: one physical line per row and exactly
    ``column_count - 1`` literal tab separators on every line.
    """

    physical_rows = text.splitlines()
    expected_separators = column_count - 1
    mismatches = [
        {
            "physical_row": index,
            "actual_tab_separators": row.count("\t"),
            "expected_tab_separators": expected_separators,
        }
        for index, row in enumerate(physical_rows, start=1)
        if row.count("\t") != expected_separators
    ]
    if len(physical_rows) != parsed_record_count or mismatches:
        raise ImportContractError(
            "INVALID_TAB_FILE",
            (
                "Wwise tab-delimited cells must not contain tab or line "
                "separators, including CSV-style quoted separators."
            ),
            details={
                "physical_record_count": len(physical_rows),
                "parsed_record_count": parsed_record_count,
                "mismatches": mismatches[:8],
            },
        )


def _normalize_structured_event(value: Any, *, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} must be a structured object, not a raw WAAPI string.",
        )
    _require_exact_keys(value, required=frozenset({"path"}), optional=frozenset({"action"}), context=field)
    path = _require_event_path(value.get("path"), field=f"{field}.path")
    action = value.get("action", "Play")
    if not isinstance(action, str) or action not in _EVENT_ACTIONS:
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field}.action is not supported.",
            details={"action": action, "supported": sorted(_EVENT_ACTIONS)},
        )
    return {"path": path, "action": action, "waapi_value": f"{path}@{action}"}


def _parse_tab_event(value: Any, *, field: str) -> dict[str, str]:
    text = _require_text(value, field=field)
    path, marker, action = text.rpartition("@")
    if not marker:
        path = text
        action = "Play"
    return _normalize_structured_event({"path": path, "action": action}, field=field)


def _require_event_path(value: Any, *, field: str) -> str:
    path = _require_text(value, field=field)
    if "@" in path:
        raise ImportContractError("INVALID_ARGUMENT", f"{field} must not embed an action suffix.")
    segments = _canonical_wwise_segments(path, field=field, absolute=True)
    if len(segments) < 3 or segments[0] != "Events":
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} must be an absolute path below an Events Work Unit.",
            details={"path": path},
        )
    return "\\" + "\\".join(segments)


def _canonical_wwise_segments(value: Any, *, field: str, absolute: bool) -> list[str]:
    text = _require_text(value, field=field)
    if "/" in text:
        raise ImportContractError("INVALID_ARGUMENT", f"{field} must use Wwise backslash separators.")
    if absolute and (not text.startswith("\\") or text.endswith("\\")):
        raise ImportContractError("INVALID_ARGUMENT", f"{field} must be an absolute Wwise object path.")
    if not absolute and (text.startswith("\\") or text.endswith("\\")):
        raise ImportContractError("INVALID_ARGUMENT", f"{field} must be a relative Wwise object path.")
    raw_segments = text[1:].split("\\") if absolute else text.split("\\")
    canonical: list[str] = []
    for segment in raw_segments:
        if not segment or segment in {".", ".."}:
            raise ImportContractError(
                "INVALID_ARGUMENT",
                f"{field} contains an empty, dot, or dot-dot path segment.",
                details={"segment": segment},
            )
        if segment.startswith("<"):
            match = _TYPED_PATH_SEGMENT.fullmatch(segment)
            if match is None or not match.group(1).strip() or not match.group(2).strip():
                raise ImportContractError("INVALID_ARGUMENT", f"{field} contains a malformed typed path segment.")
            segment = match.group(2)
        elif "<" in segment or ">" in segment:
            raise ImportContractError("INVALID_ARGUMENT", f"{field} contains a malformed typed path segment.")
        if segment != segment.strip():
            raise ImportContractError("INVALID_ARGUMENT", f"{field} path segments must not have outer whitespace.")
        canonical.append(segment)
    return canonical


def _require_import_root(root: str, *, version: str, field: str) -> None:
    allowed = IMPORT_ROOTS_BY_VERSION[version]
    if root not in allowed:
        raise ImportContractError(
            "INVALID_TARGET",
            f"{field} uses an unsupported hierarchy root for Wwise {version}.",
            details={"root": root, "allowed": sorted(allowed)},
        )


def _require_import_operation(value: Any) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_IMPORT_OPERATIONS:
        raise ImportContractError(
            "INVALID_ARGUMENT",
            "import_operation is not supported.",
            details={"value": value, "supported": list(SUPPORTED_IMPORT_OPERATIONS)},
        )
    return value


def _require_version(value: Any) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_WWISE_VERSIONS:
        raise ImportContractError(
            "UNSUPPORTED_VERSION",
            "The import contract is not available for this Wwise version.",
            details={"version": value, "supported": list(SUPPORTED_WWISE_VERSIONS)},
        )
    return value


def _require_language(value: Any, *, field: str) -> str:
    language = _require_text(value, field=field)
    if len(language) > 128 or any(character in language for character in ("\x00", "\r", "\n", "\t")):
        raise ImportContractError("INVALID_ARGUMENT", f"{field} is not a valid project language label.")
    return "SFX" if language.casefold() == "sfx" else language


def language_requires_live_project_validation(value: Any) -> bool:
    """Whether an import language must exist in the live Project inventory.

    ``SFX`` is Wwise's built-in non-localized import token.  It is accepted by
    the import API but is not a Project language row, so only other explicit
    language labels require a live inventory lookup.
    """

    return isinstance(value, str) and value.casefold() != "sfx"


def _require_originals_subfolder(value: Any, *, field: str) -> str:
    subfolder = _require_text(value, field=field)
    if len(subfolder) > 512 or subfolder.startswith(("/", "\\")) or _WINDOWS_DRIVE.match(subfolder):
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} must be relative to Wwise's normal import destination.",
        )
    segments = re.split(r"[\\/]", subfolder)
    if any(not segment or segment in {".", ".."} or segment != segment.strip() for segment in segments):
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} contains an unsafe path segment.",
            details={"value": subfolder},
        )
    if any(any(character in segment for character in ("\x00", ":", "\r", "\n", "\t")) for segment in segments):
        raise ImportContractError("INVALID_ARGUMENT", f"{field} contains unsupported characters.")
    return "\\".join(segments)


def _require_object_type(value: Any, *, field: str) -> str:
    object_type = _require_text(value, field=field)
    if object_type not in _IMPORT_OBJECT_TYPES:
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} is outside the reviewed import type set.",
            details={"object_type": object_type, "supported": sorted(_IMPORT_OBJECT_TYPES)},
        )
    return object_type


def _require_bounded_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise ImportContractError("INVALID_ARGUMENT", f"{field} must be a string.")
    if len(value) > MAX_TEXT_CHARS or "\x00" in value:
        raise ImportContractError(
            "LIMIT_EXCEEDED",
            f"{field} exceeds the closed text limit or contains NUL.",
            details={"limit": MAX_TEXT_CHARS},
        )
    return value


def _require_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ImportContractError("INVALID_ARGUMENT", f"{field} must be a non-empty string without outer whitespace or NUL.")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str],
    context: str,
) -> None:
    keys = set(value)
    missing = sorted(required - keys)
    extras = sorted(keys - required - optional)
    if missing or extras:
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{context} does not match the closed schema.",
            details={"missing": missing, "unsupported": extras},
        )


def _require_media_extension(path: str, *, field: str) -> None:
    extension = Path(path).suffix.casefold()
    if extension not in {".wav", ".amb", ".mid", ".midi"}:
        raise ImportContractError(
            "INVALID_FILE",
            f"{field} does not use a reviewed Wwise import extension.",
            details={"path": path, "supported_extensions": [".amb", ".mid", ".midi", ".wav"]},
        )


def _open_regular_file(
    value: str | os.PathLike[str] | Any,
    *,
    field: str,
) -> tuple[Path, Any]:
    if isinstance(value, os.PathLike):
        path_text = os.fspath(value)
    else:
        path_text = value
    if not isinstance(path_text, str) or not path_text:
        raise ImportContractError("INVALID_FILE", f"{field} must be an absolute file path.")
    supplied = Path(path_text)
    if not supplied.is_absolute():
        raise ImportContractError(
            "INVALID_FILE",
            f"{field} must be an absolute file path.",
            details={"path": path_text},
        )
    try:
        leaf_stat = supplied.lstat()
    except FileNotFoundError as exc:
        raise ImportContractError(
            "INPUT_FILE_NOT_FOUND",
            f"{field} does not exist.",
            details={"path": path_text},
        ) from exc
    except OSError as exc:
        raise ImportContractError(
            "INVALID_FILE",
            f"{field} is not accessible.",
            details={"path": path_text, "error": str(exc)},
        ) from exc
    if not stat.S_ISREG(leaf_stat.st_mode):
        raise ImportContractError(
            "INVALID_FILE",
            f"{field} must identify a regular file, not a directory, device, or symbolic link.",
            details={"path": path_text},
        )
    try:
        canonical = supplied.resolve(strict=True)
        opened = canonical.open("rb")
    except FileNotFoundError as exc:
        raise ImportContractError(
            "INPUT_FILE_NOT_FOUND",
            f"{field} disappeared before it could be opened.",
            details={"path": path_text},
        ) from exc
    except OSError as exc:
        raise ImportContractError(
            "INVALID_FILE",
            f"{field} could not be opened.",
            details={"path": path_text, "error": str(exc)},
        ) from exc
    return canonical, opened


def _read_proven_bytes(
    value: str | os.PathLike[str],
    *,
    field: str,
    max_bytes: int,
) -> tuple[Path, bytes, dict[str, Any]]:
    path, opened = _open_regular_file(value, field=field)
    try:
        with opened:
            before = os.fstat(opened.fileno())
            if before.st_size > max_bytes:
                raise ImportContractError(
                    "LIMIT_EXCEEDED",
                    f"{field} exceeds the closed byte limit.",
                    details={"size": before.st_size, "limit": max_bytes},
                )
            data = opened.read(max_bytes + 1)
            after = os.fstat(opened.fileno())
    except ImportContractError:
        raise
    except OSError as exc:
        raise ImportContractError(
            "INVALID_FILE",
            f"{field} could not be read.",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if len(data) > max_bytes:
        raise ImportContractError(
            "LIMIT_EXCEEDED",
            f"{field} exceeds the closed byte limit.",
            details={"limit": max_bytes},
        )
    _require_unchanged_stat(before, after, field=field, path=path)
    return path, data, _file_proof(path, after, hashlib.sha256(data).hexdigest())


def _require_unchanged_stat(before: os.stat_result, after: os.stat_result, *, field: str, path: Path) -> None:
    identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, name) != getattr(after, name) for name in identity):
        raise ImportContractError(
            "FILE_CHANGED",
            f"{field} changed while its proof was being captured.",
            details={"path": str(path)},
        )


def _file_proof(path: Path, file_stat: os.stat_result, sha256: str) -> dict[str, Any]:
    return {
        "path": str(path),
        "size": file_stat.st_size,
        "sha256": sha256,
        "mtime_ns": file_stat.st_mtime_ns,
        "device": file_stat.st_dev,
        "inode": file_stat.st_ino,
    }


__all__ = [
    "AUDIO_IMPORT_PLAN_CONTRACT",
    "IMPORT_ROOTS_BY_VERSION",
    "ImportContractError",
    "MAX_IMPORT_ITEMS",
    "MAX_TAB_BYTES",
    "MAX_TAB_COLUMNS",
    "MAX_TAB_ROWS",
    "REQUIRED_TAB_HEADERS",
    "SUPPORTED_IMPORT_OPERATIONS",
    "SUPPORTED_WWISE_VERSIONS",
    "TAB_HEADERS_BY_VERSION",
    "TAB_IMPORT_PLAN_CONTRACT",
    "build_audio_import_plan",
    "canonical_import_location",
    "canonical_import_target",
    "derive_tab_target",
    "import_operation_policy",
    "parse_tab_delimited_import_file",
    "regular_file_proof",
    "verify_regular_file_proof",
]
