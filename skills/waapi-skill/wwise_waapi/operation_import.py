"""Pure, closed contracts for the packaged audio-import operations.

The public operation registry deliberately owns live identity resolution and
dispatch.  This module owns the parts that can be proved without a Wwise
connection: a small JSON DSL, import-operation policy, source-file provenance,
and deterministic parsing of tab-delimited import files.  It never writes a
file and never calls WAAPI.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import os
import re
import stat
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Sequence


AUDIO_IMPORT_PLAN_CONTRACT = "waapi-skill.audio-import-plan/v1"
TAB_IMPORT_PLAN_CONTRACT = "waapi-skill.tab-import-plan/v1"
SUPPORTED_WWISE_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
SUPPORTED_IMPORT_OPERATIONS = ("createNew", "useExisting", "replaceExisting")
AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS = ("2023.1", "2024.1", "2025.1")

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
MAX_TAB_COLUMNS = 64
MAX_TAB_CELL_CHARS = 16 * 1024
MAX_TEXT_CHARS = 16 * 1024
MAX_INLINE_AUDIO_BYTES = 180 * 1024
MAX_AUDIO_IMPORT_BASE64_ENCODED_CHARS = 256 * 1024
MAX_IMPORT_FIELDS_PER_ROW = 64

_AUDIO_IMPORT_REQUIRED_FIELDS = frozenset()
_AUDIO_IMPORT_OPTIONAL_FIELDS = frozenset(
    {
        "object_path",
        "object_type",
        "audio_file",
        "audio_file_base64",
        "import_language",
        "import_location",
        "originals_subfolder",
        "notes",
        "audio_source_notes",
        "event",
        "dialogue_event",
        "switch_assignment",
        "properties",
        "references",
    }
)
_AUDIO_IMPORT_DEFAULT_FIELDS = _AUDIO_IMPORT_OPTIONAL_FIELDS
_EVENT_ACTIONS = frozenset({"Play", "Stop", "Pause", "Resume", "Break", "Seek"})
_TYPED_PATH_SEGMENT = re.compile(r"^<([^<>]+)>([^<>]+)$")
_DYNAMIC_FIELD_NAME = re.compile(r"^[:_a-zA-Z0-9]+$")
_PROPERTY_HEADER = re.compile(r"^Property\[([:_a-zA-Z0-9]+)\]$")
_REFERENCE_HEADER = re.compile(r"^Reference\[([:_a-zA-Z0-9]+)\]$")
_AT_HEADER = re.compile(r"^@([:_a-zA-Z0-9]+)$")
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
        "Audio File Base64",
        "Object Path",
        "Object Type",
        "OriginalsSubFolder",
        "Notes",
        "Audio Source Notes",
        "Event",
        "Dialogue Event",
        "Switch Assignation",
    }
)
TAB_HEADERS_BY_VERSION: Mapping[str, frozenset[str]] = {
    version: _TAB_HEADERS for version in SUPPORTED_WWISE_VERSIONS
}
REQUIRED_TAB_HEADERS = frozenset({"Object Path"})

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


def normalize_auto_check_out_to_source_control(
    value: Any,
    *,
    version: str,
    supplied: bool,
) -> bool | None:
    """Close the versioned import source-control option before dispatch."""

    lane = _require_version(version)
    if not supplied:
        return False if lane in AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS else None
    if type(value) is not bool:
        raise ImportContractError(
            "INVALID_ARGUMENT",
            "auto_check_out_to_source_control must be a JSON boolean.",
            details={"field": "auto_check_out_to_source_control", "value": value},
        )
    if lane not in AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS:
        raise ImportContractError(
            "VERSION_BEHAVIOR_BOUNDARY",
            "auto_check_out_to_source_control is available only in Wwise 2023.1-2025.1.",
            details={
                "field": "auto_check_out_to_source_control",
                "version": lane,
                "supported_versions": list(AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS),
            },
        )
    return value


def import_operation_policy(import_operation: str) -> dict[str, Any]:
    """Return the immutable collision, identity, and cleanup policy."""

    operation = _require_import_operation(import_operation)
    common: dict[str, Any] = {
        "import_operation": operation,
        "one_global_operation_per_call": True,
        "pre_state_required": True,
        "pre_execution_drift_check_required": True,
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


def normalize_inline_audio_file(
    value: Any,
    *,
    field: str,
) -> tuple[str, dict[str, Any]]:
    """Return canonical bounded ``relative.wav|base64`` data and its proof."""

    return _normalize_audio_file_base64(value, field=field)


def normalize_originals_subfolder(value: Any, *, field: str) -> str:
    """Normalize one path segment below Wwise's managed Originals root."""

    return _require_originals_subfolder(value, field=field)


def validate_import_media_extension(path: str, *, field: str) -> None:
    """Require one of the version-independent reviewed import media suffixes."""

    _require_media_extension(path, field=field)


def build_audio_import_plan(
    imports: Sequence[Mapping[str, Any]],
    *,
    version: str,
    import_operation: str,
    defaults: Mapping[str, Any] | None = None,
    auto_add_to_source_control: bool = False,
    auto_check_out_to_source_control: bool | None = None,
) -> dict[str, Any]:
    """Normalize the closed ``audio.import`` item DSL into a JSON plan."""

    lane = _require_version(version)
    policy = import_operation_policy(import_operation)
    auto_add = _require_boolean(
        auto_add_to_source_control,
        field="auto_add_to_source_control",
    )
    auto_check_out = normalize_auto_check_out_to_source_control(
        auto_check_out_to_source_control,
        version=lane,
        supplied=auto_check_out_to_source_control is not None,
    )
    normalized_defaults = _normalize_import_defaults(defaults)
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
    total_audio_file_base64_encoded_chars = 0
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
        effective = _merge_import_defaults(
            normalized_defaults,
            raw,
            field=f"imports[{index}]",
        )
        object_path = _require_text(
            effective.get("object_path"),
            field=f"imports[{index}].object_path",
        )
        import_location = (
            canonical_import_location(
                effective.get("import_location"),
                version=lane,
            )
            if "import_location" in effective
            else None
        )
        if object_path.startswith("\\"):
            target = canonical_import_target(object_path, version=lane)
        elif import_location is not None:
            target = derive_tab_target(
                object_path,
                import_location=import_location,
                version=lane,
            )
        else:
            raise ImportContractError(
                "INVALID_TARGET",
                "A relative object_path requires import_location.",
                details={"index": index, "object_path": object_path},
            )
        target_key = target["canonical_target_path"].casefold()
        if target_key in seen_targets:
            raise ImportContractError(
                "DUPLICATE_TARGET",
                "audio.import target paths must be unique.",
                details={"index": index, "target_path": target["canonical_target_path"]},
            )
        seen_targets.add(target_key)

        has_audio_file = "audio_file" in effective
        has_audio_base64 = "audio_file_base64" in effective
        if has_audio_file and has_audio_base64:
            raise ImportContractError(
                "INVALID_ARGUMENT",
                "An import row must not provide both audio_file and audio_file_base64.",
                details={"index": index},
            )

        dispatch: dict[str, Any] = {"objectPath": object_path}
        oracle_row: dict[str, Any] = {
            "index": index,
            **target,
            "pre_state_required": True,
            "media_expected": has_audio_file or has_audio_base64,
        }
        if import_location is not None:
            dispatch["importLocation"] = import_location
            oracle_row["requested_import_location"] = import_location

        source_name_path: str | None = None
        if has_audio_file:
            proof = regular_file_proof(
                effective.get("audio_file"),
                field=f"imports[{index}].audio_file",
            )
            _require_media_extension(
                proof["path"],
                field=f"imports[{index}].audio_file",
            )
            source_proof = {"kind": "regular_file", **proof}
            dispatch["audioFile"] = proof["path"]
            source_name_path = proof["path"]
            file_proofs.append({"index": index, **proof})
            oracle_row["source_file"] = source_proof
        elif has_audio_base64:
            encoded, source_proof = _normalize_audio_file_base64(
                effective.get("audio_file_base64"),
                field=f"imports[{index}].audio_file_base64",
            )
            total_audio_file_base64_encoded_chars += len(encoded)
            if (
                total_audio_file_base64_encoded_chars
                > MAX_AUDIO_IMPORT_BASE64_ENCODED_CHARS
            ):
                raise ImportContractError(
                    "LIMIT_EXCEEDED",
                    "audio.import exceeds the request-wide encoded Base64 limit "
                    "after defaults expansion.",
                    details={
                        "field": "audio_file_base64",
                        "counted_through_index": index,
                        "encoded_characters": total_audio_file_base64_encoded_chars,
                        "limit": MAX_AUDIO_IMPORT_BASE64_ENCODED_CHARS,
                        "aggregation": "effective_rows_after_defaults",
                    },
                )
            dispatch["audioFileBase64"] = encoded
            source_name_path = str(source_proof["relative_path"])
            oracle_row["source_file"] = source_proof

        if source_name_path is not None:
            expected_source_path = expected_audio_file_source_result_path(
                target["canonical_target_path"],
                source_name_path,
            )
            if expected_source_path is not None:
                oracle_row["expected_audio_file_source_result_path"] = expected_source_path

        requested_type = effective.get("object_type")
        if requested_type is None:
            requested_type = _typed_leaf_object_type(object_path)
        if requested_type is not None:
            object_type = _require_object_type(
                requested_type,
                field=f"imports[{index}].object_type",
            )
            dispatch["objectType"] = object_type
            oracle_row["requested_object_type"] = object_type
        elif not oracle_row["media_expected"]:
            raise ImportContractError(
                "INVALID_ARGUMENT",
                "A structure-only import row requires object_type or a typed final object_path segment.",
                details={"index": index, "object_path": object_path},
            )
        if "import_language" in effective:
            if not oracle_row["media_expected"]:
                raise ImportContractError(
                    "INVALID_ARGUMENT",
                    "import_language requires an audio source in the same effective row.",
                    details={"index": index},
                )
            language = _require_language(
                effective.get("import_language"),
                field=f"imports[{index}].import_language",
            )
            dispatch["importLanguage"] = language
            oracle_row["requested_language"] = language
        if "originals_subfolder" in effective:
            if not oracle_row["media_expected"]:
                raise ImportContractError(
                    "INVALID_ARGUMENT",
                    "originals_subfolder requires an audio source in the same effective row.",
                    details={"index": index},
                )
            subfolder = _require_originals_subfolder(
                effective.get("originals_subfolder"),
                field=f"imports[{index}].originals_subfolder",
            )
            dispatch["originalsSubFolder"] = subfolder
            oracle_row["requested_originals_subfolder"] = subfolder
        for public_name, waapi_name in (("notes", "notes"), ("audio_source_notes", "audioSourceNotes")):
            if public_name in effective:
                if public_name == "audio_source_notes" and not oracle_row["media_expected"]:
                    raise ImportContractError(
                        "INVALID_ARGUMENT",
                        "audio_source_notes requires an audio source in the same effective row.",
                        details={"index": index},
                    )
                value = _require_bounded_text(
                    effective.get(public_name),
                    field=f"imports[{index}].{public_name}",
                )
                dispatch[waapi_name] = value
                oracle_row[f"requested_{public_name}"] = value
        if "event" in effective:
            event = _normalize_structured_event(
                effective.get("event"),
                field=f"imports[{index}].event",
            )
            dispatch["event"] = event["waapi_value"]
            oracle_row["requested_event"] = {key: value for key, value in event.items() if key != "waapi_value"}
        if "dialogue_event" in effective:
            dialogue_event = _require_native_import_directive(
                effective.get("dialogue_event"),
                field=f"imports[{index}].dialogue_event",
            )
            dispatch["dialogueEvent"] = dialogue_event
            oracle_row["requested_dialogue_event"] = dialogue_event
        if "switch_assignment" in effective:
            switch_assignment = _require_native_import_directive(
                effective.get("switch_assignment"),
                field=f"imports[{index}].switch_assignment",
            )
            dispatch["switchAssignation"] = switch_assignment
            oracle_row["requested_switch_assignment"] = switch_assignment

        properties = _normalize_named_value_rows(
            effective.get("properties", ()),
            field=f"imports[{index}].properties",
        )
        references = _normalize_reference_rows(
            effective.get("references", ()),
            field=f"imports[{index}].references",
        )
        _reject_property_reference_name_collisions(
            properties,
            references,
            field=f"imports[{index}]",
        )
        if properties:
            oracle_row["requested_properties"] = properties
        if references:
            oracle_row["requested_references"] = references

        dispatch_rows.append(dispatch)
        targets.append(oracle_row)

    dispatch_args: dict[str, Any] = {
        "imports": dispatch_rows,
        "importOperation": policy["import_operation"],
        "autoAddToSourceControl": auto_add,
    }
    if auto_check_out is not None:
        dispatch_args["autoCheckOutToSourceControl"] = auto_check_out
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
            "dialogue_event_side_effects_present": any(
                "requested_dialogue_event" in row for row in targets
            ),
            "switch_assignment_side_effects_present": any(
                "requested_switch_assignment" in row for row in targets
            ),
            "media_hash_readback_required": any(
                row.get("media_expected") is True for row in targets
            ),
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
    auto_add_to_source_control: bool = False,
    auto_check_out_to_source_control: bool | None = None,
) -> dict[str, Any]:
    """Parse and prove a reviewed UTF-8 TSV subset without trusting caller rows."""

    lane = _require_version(version)
    policy = import_operation_policy(import_operation)
    auto_add = _require_boolean(
        auto_add_to_source_control,
        field="auto_add_to_source_control",
    )
    auto_check_out = normalize_auto_check_out_to_source_control(
        auto_check_out_to_source_control,
        version=lane,
        supplied=auto_check_out_to_source_control is not None,
    )
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
            cell_limit = (
                MAX_TAB_BYTES
                if column == "Audio File Base64"
                else MAX_TAB_CELL_CHARS
            )
            if len(cell) > cell_limit:
                raise ImportContractError(
                    "LIMIT_EXCEEDED",
                    "A tab-delimited cell exceeds the closed character limit.",
                    details={"row": offset, "column": column, "limit": cell_limit},
                )
        pairs = list(zip(headers, cells, strict=True))

        def single_value(header: str) -> str:
            values = [cell for column, cell in pairs if column == header]
            return values[0] if values else ""

        audio_file = single_value("Audio File")
        audio_file_base64 = single_value("Audio File Base64")
        if audio_file and audio_file_base64:
            raise ImportContractError(
                "INVALID_TAB_FILE",
                "A tab-delimited row must not provide both Audio File and Audio File Base64.",
                details={"row": offset},
            )
        object_path = _require_text(
            single_value("Object Path"),
            field=f"row[{offset}].Object Path",
        )
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
            "object_path": object_path,
            **target,
        }
        oracle_row: dict[str, Any] = {
            "row_number": offset,
            **target,
            "pre_state_required": True,
            "media_expected": bool(audio_file or audio_file_base64),
        }
        if oracle_row["media_expected"]:
            oracle_row["requested_language"] = language
        source_name_path: str | None = None
        if audio_file:
            proof = regular_file_proof(
                audio_file,
                field=f"row[{offset}].Audio File",
            )
            _require_media_extension(
                proof["path"],
                field=f"row[{offset}].Audio File",
            )
            source_proof = {"kind": "regular_file", **proof}
            row_plan["audio_file"] = proof["path"]
            oracle_row["source_file"] = source_proof
            source_proofs.append({"row_number": offset, **proof})
            source_name_path = proof["path"]
        elif audio_file_base64:
            _, source_proof = _normalize_audio_file_base64(
                audio_file_base64,
                field=f"row[{offset}].Audio File Base64",
            )
            row_plan["audio_file_base64"] = source_proof["relative_path"]
            oracle_row["source_file"] = source_proof
            source_name_path = str(source_proof["relative_path"])

        if source_name_path is not None:
            expected_source_path = expected_audio_file_source_result_path(
                target["canonical_target_path"],
                source_name_path,
            )
            if expected_source_path is not None:
                oracle_row["expected_audio_file_source_result_path"] = expected_source_path

        object_type_value = single_value("Object Type")
        inferred_type = _typed_leaf_object_type(object_path)
        if object_type_value:
            object_type = _require_object_type(
                object_type_value,
                field=f"row[{offset}].Object Type",
            )
            row_plan["object_type"] = object_type
            oracle_row["requested_object_type"] = object_type
        elif inferred_type is not None:
            oracle_row["requested_object_type"] = _require_object_type(
                inferred_type,
                field=f"row[{offset}].Object Path",
            )
        elif not oracle_row["media_expected"]:
            raise ImportContractError(
                "INVALID_TAB_FILE",
                "A structure-only tab row requires Object Type or a typed final Object Path segment.",
                details={"row": offset},
            )

        originals_subfolder = single_value("OriginalsSubFolder")
        if originals_subfolder:
            if not oracle_row["media_expected"]:
                raise ImportContractError(
                    "INVALID_TAB_FILE",
                    "OriginalsSubFolder requires Audio File or Audio File Base64.",
                    details={"row": offset},
                )
            subfolder = _require_originals_subfolder(
                originals_subfolder,
                field=f"row[{offset}].OriginalsSubFolder",
            )
            row_plan["originals_subfolder"] = subfolder
            oracle_row["requested_originals_subfolder"] = subfolder
        for header, key in (("Notes", "notes"), ("Audio Source Notes", "audio_source_notes")):
            field_value = single_value(header)
            if field_value:
                if header == "Audio Source Notes" and not oracle_row["media_expected"]:
                    raise ImportContractError(
                        "INVALID_TAB_FILE",
                        "Audio Source Notes requires Audio File or Audio File Base64.",
                        details={"row": offset},
                    )
                value = _require_bounded_text(
                    field_value,
                    field=f"row[{offset}].{header}",
                )
                row_plan[key] = value
                oracle_row[f"requested_{key}"] = value

        requested_events = [
            {
                key: value
                for key, value in _parse_tab_event(
                    cell,
                    field=f"row[{offset}].Event",
                ).items()
                if key != "waapi_value"
            }
            for header, cell in pairs
            if header == "Event" and cell
        ]
        if requested_events:
            row_plan["events"] = requested_events
            oracle_row["requested_events"] = requested_events
            if len(requested_events) == 1:
                # Compatibility with the original one-Event verifier.
                row_plan["event"] = requested_events[0]
                oracle_row["requested_event"] = requested_events[0]

        dialogue_events = [
            _require_native_import_directive(
                cell,
                field=f"row[{offset}].Dialogue Event",
            )
            for header, cell in pairs
            if header == "Dialogue Event" and cell
        ]
        if dialogue_events:
            row_plan["dialogue_events"] = dialogue_events
            oracle_row["requested_dialogue_events"] = dialogue_events

        switch_assignments = [
            _require_native_import_directive(
                cell,
                field=f"row[{offset}].Switch Assignation",
            )
            for header, cell in pairs
            if header == "Switch Assignation" and cell
        ]
        if switch_assignments:
            row_plan["switch_assignments"] = switch_assignments
            oracle_row["requested_switch_assignments"] = switch_assignments

        dynamic_fields: list[dict[str, Any]] = []
        for header, cell in pairs:
            dynamic = _parse_dynamic_tab_header(header)
            if dynamic is None or not cell:
                continue
            dynamic_fields.append(
                {
                    "kind": dynamic["kind"],
                    "name": dynamic["name"],
                    "value": _require_bounded_text(
                        cell,
                        field=f"row[{offset}].{header}",
                    ),
                    "header": header,
                }
            )
        _reject_duplicate_dynamic_fields(
            dynamic_fields,
            field=f"row[{offset}]",
        )
        if dynamic_fields:
            oracle_row["requested_dynamic_fields"] = dynamic_fields

        rows.append(row_plan)
        target_oracle.append(oracle_row)

    dispatch_args: dict[str, Any] = {
        "importFile": str(path),
        "importLocation": location,
        "importLanguage": language,
        "importOperation": policy["import_operation"],
        "autoAddToSourceControl": auto_add,
    }
    if auto_check_out is not None:
        dispatch_args["autoCheckOutToSourceControl"] = auto_check_out
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
            "event_side_effects_present": any(
                "requested_events" in row for row in target_oracle
            ),
            "dialogue_event_side_effects_present": any(
                "requested_dialogue_events" in row for row in target_oracle
            ),
            "switch_assignment_side_effects_present": any(
                "requested_switch_assignments" in row for row in target_oracle
            ),
            "all_sources_validated_before_dispatch": True,
            "missing_or_unreadable_source_policy": "reject_before_preview_and_dispatch",
            "media_hash_readback_required": any(
                row.get("media_expected") is True for row in target_oracle
            ),
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
    # Inline Base64 paths are normalized to Wwise/Windows separators even when
    # the gateway runs on macOS or Linux.  PureWindowsPath also handles the
    # ordinary POSIX absolute paths accepted for file-backed imports.
    source_path = PureWindowsPath(source_file_path)
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


def _normalize_import_defaults(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ImportContractError(
            "INVALID_ARGUMENT",
            "defaults must be a JSON object.",
        )
    _require_exact_keys(
        value,
        required=frozenset(),
        optional=_AUDIO_IMPORT_DEFAULT_FIELDS,
        context="defaults",
    )
    return dict(value)


def _merge_import_defaults(
    defaults: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    field: str,
) -> dict[str, Any]:
    merged = dict(defaults)
    merged.update(row)
    for collection_name, normalizer in (
        ("properties", _normalize_named_value_rows),
        ("references", _normalize_reference_rows),
    ):
        default_rows = normalizer(
            defaults.get(collection_name, ()),
            field=f"defaults.{collection_name}",
        )
        item_rows = normalizer(
            row.get(collection_name, ()),
            field=f"{field}.{collection_name}",
        )
        by_name = {str(item["name"]).casefold(): dict(item) for item in default_rows}
        for item in item_rows:
            by_name[str(item["name"]).casefold()] = dict(item)
        if by_name:
            merged[collection_name] = list(by_name.values())
        else:
            merged.pop(collection_name, None)
    requested_field_count = len(merged)
    requested_field_count += len(merged.get("properties", ()))
    requested_field_count += len(merged.get("references", ()))
    if requested_field_count > MAX_IMPORT_FIELDS_PER_ROW:
        raise ImportContractError(
            "LIMIT_EXCEEDED",
            "An effective import row exceeds the closed field limit.",
            details={
                "field": field,
                "count": requested_field_count,
                "limit": MAX_IMPORT_FIELDS_PER_ROW,
            },
        )
    return merged


def _normalize_named_value_rows(value: Any, *, field: str) -> list[dict[str, Any]]:
    if value in (None, ()):
        return []
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ImportContractError("INVALID_ARGUMENT", f"{field} must be a JSON array.")
    if len(value) > MAX_IMPORT_FIELDS_PER_ROW:
        raise ImportContractError(
            "LIMIT_EXCEEDED",
            f"{field} exceeds the closed field limit.",
            details={"count": len(value), "limit": MAX_IMPORT_FIELDS_PER_ROW},
        )
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise ImportContractError(
                "INVALID_ARGUMENT",
                f"{field}[{index}] must be a JSON object.",
            )
        _require_exact_keys(
            raw,
            required=frozenset({"name", "value"}),
            optional=frozenset(),
            context=f"{field}[{index}]",
        )
        name = _require_dynamic_field_name(
            raw.get("name"),
            field=f"{field}[{index}].name",
        )
        key = name.casefold()
        if key in names:
            raise ImportContractError(
                "DUPLICATE_FIELD",
                f"{field} contains the same name more than once.",
                details={"name": name},
            )
        names.add(key)
        item_value = raw.get("value")
        if (
            item_value is None
            or isinstance(item_value, (list, Mapping))
            or isinstance(item_value, float)
            and not _is_finite_number(item_value)
            or isinstance(item_value, str)
            and (len(item_value) > MAX_TEXT_CHARS or "\x00" in item_value)
        ):
            raise ImportContractError(
                "INVALID_ARGUMENT",
                f"{field}[{index}].value must be a bounded finite JSON scalar.",
                details={"name": name},
            )
        result.append({"name": name, "value": item_value})
    return result


def _normalize_reference_rows(value: Any, *, field: str) -> list[dict[str, Any]]:
    if value in (None, ()):
        return []
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ImportContractError("INVALID_ARGUMENT", f"{field} must be a JSON array.")
    if len(value) > MAX_IMPORT_FIELDS_PER_ROW:
        raise ImportContractError(
            "LIMIT_EXCEEDED",
            f"{field} exceeds the closed field limit.",
            details={"count": len(value), "limit": MAX_IMPORT_FIELDS_PER_ROW},
        )
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise ImportContractError(
                "INVALID_ARGUMENT",
                f"{field}[{index}] must be a JSON object.",
            )
        _require_exact_keys(
            raw,
            required=frozenset({"name", "target"}),
            optional=frozenset(),
            context=f"{field}[{index}]",
        )
        name = _require_dynamic_field_name(
            raw.get("name"),
            field=f"{field}[{index}].name",
        )
        key = name.casefold()
        if key in names:
            raise ImportContractError(
                "DUPLICATE_FIELD",
                f"{field} contains the same name more than once.",
                details={"name": name},
            )
        target = raw.get("target")
        if not isinstance(target, Mapping):
            raise ImportContractError(
                "INVALID_ARGUMENT",
                f"{field}[{index}].target must be a closed object identity.",
            )
        names.add(key)
        result.append({"name": name, "target": dict(target)})
    return result


def _reject_property_reference_name_collisions(
    properties: Sequence[Mapping[str, Any]],
    references: Sequence[Mapping[str, Any]],
    *,
    field: str,
) -> None:
    property_names = {
        str(item.get("name")).casefold()
        for item in properties
        if isinstance(item.get("name"), str)
    }
    reference_names = {
        str(item.get("name")).casefold()
        for item in references
        if isinstance(item.get("name"), str)
    }
    collisions = sorted(property_names & reference_names)
    if collisions:
        raise ImportContractError(
            "DUPLICATE_FIELD",
            "An import field cannot be both a property and a reference.",
            details={"field": field, "names": collisions},
        )


def _normalize_audio_file_base64(value: Any, *, field: str) -> tuple[str, dict[str, Any]]:
    encoded = _require_text(value, field=field)
    relative_path, separator, payload = encoded.partition("|")
    if not separator or not relative_path or not payload:
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} must use '<relative .wav path>|<base64 WAV data>'.",
        )
    normalized_path = _require_inline_relative_wav_path(
        relative_path,
        field=f"{field}.relative_path",
    )
    try:
        decoded = base64.b64decode(payload.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} contains invalid canonical base64.",
        ) from exc
    if not decoded or len(decoded) > MAX_INLINE_AUDIO_BYTES:
        raise ImportContractError(
            "LIMIT_EXCEEDED",
            f"{field} exceeds the bounded inline-audio limit or is empty.",
            details={"size": len(decoded), "limit": MAX_INLINE_AUDIO_BYTES},
        )
    if len(decoded) < 12 or decoded[:4] != b"RIFF" or decoded[8:12] != b"WAVE":
        raise ImportContractError(
            "INVALID_FILE",
            f"{field} must contain a RIFF/WAVE payload.",
        )
    canonical_payload = base64.b64encode(decoded).decode("ascii")
    canonical = f"{normalized_path}|{canonical_payload}"
    return canonical, {
        "kind": "inline_base64",
        "relative_path": normalized_path,
        "size": len(decoded),
        "sha256": hashlib.sha256(decoded).hexdigest(),
    }


def _require_inline_relative_wav_path(value: Any, *, field: str) -> str:
    path = _require_text(value, field=field)
    if (
        path.startswith(("/", "\\"))
        or _WINDOWS_DRIVE.match(path)
        or len(path) > 1024
    ):
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} must be relative to the Project Originals folder.",
        )
    segments = re.split(r"[\\/]", path)
    if any(
        not segment
        or segment in {".", ".."}
        or segment != segment.strip()
        or any(character in segment for character in ("\x00", ":", "\r", "\n", "\t"))
        for segment in segments
    ):
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} contains an unsafe path segment.",
        )
    normalized = "\\".join(segments)
    if Path(normalized).suffix.casefold() != ".wav":
        raise ImportContractError(
            "INVALID_FILE",
            f"{field} must end in .wav.",
        )
    return normalized


def _typed_leaf_object_type(object_path: str) -> str | None:
    leaf = object_path.rsplit("\\", 1)[-1]
    match = _TYPED_PATH_SEGMENT.fullmatch(leaf)
    return match.group(1).strip() if match is not None else None


def _parse_dynamic_tab_header(header: str) -> dict[str, str] | None:
    for kind, pattern in (
        ("property", _PROPERTY_HEADER),
        ("reference", _REFERENCE_HEADER),
        ("auto", _AT_HEADER),
    ):
        match = pattern.fullmatch(header)
        if match is not None:
            return {"kind": kind, "name": match.group(1)}
    return None


def _reject_duplicate_dynamic_fields(
    fields: Sequence[Mapping[str, Any]],
    *,
    field: str,
) -> None:
    seen: dict[str, str] = {}
    for item in fields:
        name = item.get("name")
        kind = item.get("kind")
        if not isinstance(name, str) or not isinstance(kind, str):
            raise ImportContractError(
                "INVALID_TAB_FILE",
                f"{field} contains a malformed dynamic field.",
            )
        key = name.casefold()
        if key in seen:
            raise ImportContractError(
                "DUPLICATE_FIELD",
                f"{field} assigns one dynamic field more than once.",
                details={"name": name, "kinds": [seen[key], kind]},
            )
        seen[key] = kind


def _require_dynamic_field_name(value: Any, *, field: str) -> str:
    name = _require_text(value, field=field)
    if len(name) > 128 or _DYNAMIC_FIELD_NAME.fullmatch(name) is None:
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} is not a valid Wwise property/reference token.",
        )
    return name


def _require_native_import_directive(value: Any, *, field: str) -> str:
    text = _require_text(value, field=field)
    if len(text) > MAX_TEXT_CHARS or any(
        character in text for character in ("\r", "\n", "\t")
    ):
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} must be one bounded single-line Wwise import directive.",
        )
    return text


def _require_boolean(value: Any, *, field: str) -> bool:
    if type(value) is not bool:
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} must be a JSON boolean.",
        )
    return value


def _is_finite_number(value: float) -> bool:
    return value == value and value not in {float("inf"), float("-inf")}


def _validate_tab_headers(headers: Sequence[str], *, version: str) -> None:
    if len(headers) > MAX_TAB_COLUMNS:
        raise ImportContractError(
            "LIMIT_EXCEEDED",
            "import_file exceeds the closed column limit.",
            details={"columns": len(headers), "limit": MAX_TAB_COLUMNS},
        )
    if any(not header for header in headers):
        raise ImportContractError("INVALID_TAB_FILE", "import_file header names must not be empty.")
    repeatable = {"Event", "Dialogue Event", "Switch Assignation"}
    duplicate_singletons = sorted(
        {
            header
            for header in headers
            if headers.count(header) > 1 and header not in repeatable
        }
    )
    if duplicate_singletons:
        raise ImportContractError(
            "INVALID_TAB_FILE",
            "Only Event, Dialogue Event, and Switch Assignation columns may repeat.",
            details={"duplicate_headers": duplicate_singletons},
        )
    allowed = TAB_HEADERS_BY_VERSION[version]
    unsupported = sorted(
        {
            header
            for header in headers
            if header not in allowed and _parse_dynamic_tab_header(header) is None
        }
    )
    if unsupported:
        raise ImportContractError(
            "UNSUPPORTED_COLUMN",
            "import_file contains columns outside the closed native header grammar.",
            details={
                "version": version,
                "unsupported": unsupported,
                "fixed_headers": sorted(allowed),
                "dynamic_headers": [
                    "@PropertyOrReference",
                    "Property[Name]",
                    "Reference[Name]",
                ],
            },
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
    if (
        len(object_type) > 128
        or any(character in object_type for character in ("\\", "/", "<", ">", "\r", "\n", "\t"))
    ):
        raise ImportContractError(
            "INVALID_ARGUMENT",
            f"{field} is not a bounded Wwise object type token.",
            details={"object_type": object_type},
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
    "AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS",
    "IMPORT_ROOTS_BY_VERSION",
    "ImportContractError",
    "MAX_AUDIO_IMPORT_BASE64_ENCODED_CHARS",
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
    "language_requires_live_project_validation",
    "normalize_auto_check_out_to_source_control",
    "normalize_inline_audio_file",
    "normalize_originals_subfolder",
    "parse_tab_delimited_import_file",
    "regular_file_proof",
    "validate_import_media_extension",
    "verify_regular_file_proof",
]
