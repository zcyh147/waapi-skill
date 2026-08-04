"""Business evidence oracles for the closed destructive Gateway workflows.

These helpers validate structured execution results and readbacks.  Assertion
display names are intentionally not part of the contract: verifier wording may
change without weakening the business evidence recorded in the transaction
journal.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.host_paths import HostPathError, parse_absolute_host_path


OBJECT_GET_URI = "ak.wwise.core.object.get"
SOUNDBANK_GET_INCLUSIONS_URI = "ak.wwise.core.soundbank.getInclusions"
SWITCHCONTAINER_GET_ASSIGNMENTS_URI = (
    "ak.wwise.core.switchContainer.getAssignments"
)
INCLUSION_FILTERS = frozenset({"events", "media", "structures"})
IMPORT_LOG_SEVERITIES = frozenset(
    {"normal", "message", "warning", "error", "fatal", "fatal error"}
)
_GUID = re.compile(
    r"^\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}$"
)


class WorkflowEvidenceError(AssertionError):
    """Raised when durable workflow evidence does not prove the business state."""


def validate_audio_import_business_evidence(
    *,
    execution: Mapping[str, Any],
    verification: Mapping[str, Any],
    version: str,
    expected_target_path: str,
    expected_target_id: str,
    expected_notes: str,
    source_file: str | Path,
) -> None:
    """Prove one imported Sound and its active AudioFileSource structurally."""

    readbacks = _verification_readbacks(verification, operation="audio.import")
    expected_target_id = _require_guid(expected_target_id, field="expected target GUID")
    expected_target_path = _require_wwise_path(
        expected_target_path,
        field="expected target path",
    )
    try:
        source_name = parse_absolute_host_path(str(source_file)).pure_path.stem
    except HostPathError as exc:
        raise WorkflowEvidenceError(
            f"audio.import source file path is invalid: {exc}"
        ) from exc
    if not source_name:
        raise WorkflowEvidenceError("audio.import source file has no filename stem")
    expected_source_path = f"{expected_target_path}\\{source_name}"

    dispatch_result = execution.get("dispatch_result")
    if not isinstance(dispatch_result, Mapping):
        raise WorkflowEvidenceError("audio.import execution lacks dispatch_result")
    result = dispatch_result.get("result")
    if not isinstance(result, Mapping):
        raise WorkflowEvidenceError("audio.import execution lacks a result object")
    expected_result_keys = (
        {"log", "files", "objects"}
        if version in {"2023.1", "2024.1", "2025.1"}
        else {"objects"}
    )
    if set(result) != expected_result_keys:
        raise WorkflowEvidenceError(
            "audio.import result shape does not match the version: "
            f"expected {sorted(expected_result_keys)!r}, got {sorted(result)!r}"
        )
    objects = _mapping_rows(result.get("objects"), field="audio.import result objects")
    result_targets = [row for row in objects if row.get("path") == expected_target_path]
    if len(result_targets) != 1:
        raise WorkflowEvidenceError(
            "audio.import result path does not identify exactly one target: "
            f"{expected_target_path!r}"
        )
    result_id = _reference_id(result_targets[0].get("id"))
    if not _same_id(result_id, expected_target_id):
        raise WorkflowEvidenceError(
            "audio.import result GUID does not match the expected target GUID"
        )

    if version in {"2023.1", "2024.1", "2025.1"}:
        logs = _mapping_rows(result.get("log"), field="audio.import result log")
        files = result.get("files")
        if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
            raise WorkflowEvidenceError("audio.import result files must be strings")
        for index, row in enumerate(logs):
            severity = row.get("severity")
            message = row.get("message")
            row_index = row.get("index")
            if (
                not isinstance(severity, str)
                or severity.casefold() not in IMPORT_LOG_SEVERITIES
                or not isinstance(message, str)
                or (
                    row_index is not None
                    and (
                        isinstance(row_index, bool)
                        or not isinstance(row_index, (int, float))
                    )
                )
            ):
                raise WorkflowEvidenceError(
                    f"audio.import log row {index} is malformed"
                )
            if "error" in severity.casefold() or "fatal" in severity.casefold():
                raise WorkflowEvidenceError(
                    f"audio.import log contains a failure: {row!r}"
                )

    object_rows = _object_readback_rows(readbacks)
    target_rows = [
        row
        for row in object_rows
        if row.get("path") == expected_target_path
        and _same_id(_reference_id(row.get("id")), expected_target_id)
    ]
    if len(target_rows) != 1:
        raise WorkflowEvidenceError(
            "audio.import target path/GUID readback is not exact"
        )
    target = target_rows[0]
    if _type_token(target.get("type")) != "sound":
        raise WorkflowEvidenceError("audio.import target type is not Sound")
    if target.get("notes") != expected_notes:
        raise WorkflowEvidenceError("audio.import target notes do not match")
    active_source_id = _reference_id(
        _first_present(target, "activeSource", "@activeSource")
    )
    if not _is_guid(active_source_id):
        raise WorkflowEvidenceError(
            "audio.import target activeSource is not a canonical GUID"
        )
    source_rows = [
        row
        for row in object_rows
        if _same_id(_reference_id(row.get("id")), active_source_id)
    ]
    if len(source_rows) != 1:
        raise WorkflowEvidenceError(
            "audio.import activeSource GUID does not resolve exactly once"
        )
    source = source_rows[0]
    if _type_token(source.get("type")) != "audiofilesource":
        raise WorkflowEvidenceError("audio.import activeSource type is not AudioFileSource")
    if source.get("path") != expected_source_path:
        raise WorkflowEvidenceError(
            "audio.import activeSource path does not match the imported media"
        )


def validate_soundbank_inclusions_business_evidence(
    verification: Mapping[str, Any],
    *,
    soundbank_id: str,
    expected: Sequence[Mapping[str, Any]],
) -> None:
    """Prove the complete normalized SoundBank inclusion state."""

    readbacks = _verification_readbacks(
        verification,
        operation="soundbank.setInclusions",
    )
    soundbank_id = _require_guid(soundbank_id, field="SoundBank GUID")
    matches = [
        row
        for row in readbacks
        if row.get("uri") == SOUNDBANK_GET_INCLUSIONS_URI
        and isinstance(row.get("args"), Mapping)
        and _same_id(_reference_id(row["args"].get("soundbank")), soundbank_id)
    ]
    if len(matches) != 1:
        raise WorkflowEvidenceError(
            "SoundBank inclusion evidence must contain one exact getInclusions readback"
        )
    result = matches[0].get("result")
    if not isinstance(result, Mapping):
        raise WorkflowEvidenceError("SoundBank getInclusions readback is not an object")
    actual = _normalize_inclusions(result.get("inclusions"), field="live inclusions")
    normalized_expected = _normalize_expected_inclusions(expected)
    if actual != normalized_expected:
        raise WorkflowEvidenceError(
            "SoundBank inclusion object/filter state does not match: "
            f"expected {normalized_expected!r}, got {actual!r}"
        )


def validate_switch_assignment_business_evidence(
    verification: Mapping[str, Any],
    *,
    switch_container_id: str,
    switch_group_id: str,
    child_id: str,
    state_or_switch_id: str,
    should_exist: bool,
) -> None:
    """Prove the complete assignment pair and its object relationships."""

    readbacks = _verification_readbacks(
        verification,
        operation=(
            "switchContainer.addAssignment"
            if should_exist
            else "switchContainer.removeAssignment"
        ),
    )
    switch_container_id = _require_guid(
        switch_container_id,
        field="Switch Container GUID",
    )
    switch_group_id = _require_guid(switch_group_id, field="Switch Group GUID")
    child_id = _require_guid(child_id, field="assignment child GUID")
    state_or_switch_id = _require_guid(
        state_or_switch_id,
        field="state-or-switch GUID",
    )
    matches = [
        row
        for row in readbacks
        if row.get("uri") == SWITCHCONTAINER_GET_ASSIGNMENTS_URI
        and isinstance(row.get("args"), Mapping)
        and _same_id(_reference_id(row["args"].get("id")), switch_container_id)
    ]
    if len(matches) != 1:
        raise WorkflowEvidenceError(
            "Switch assignment evidence must contain one exact getAssignments readback"
        )
    result = matches[0].get("result")
    if not isinstance(result, Mapping):
        raise WorkflowEvidenceError("Switch getAssignments readback is not an object")
    pairs = _normalize_assignment_pairs(result.get("return"))
    expected_pair = (child_id.casefold(), state_or_switch_id.casefold())
    expected_pairs = {expected_pair} if should_exist else set()
    if pairs != expected_pairs:
        raise WorkflowEvidenceError(
            "Switch assignment pair state does not match: "
            f"expected {sorted(expected_pairs)!r}, got {sorted(pairs)!r}"
        )

    object_rows = _object_readback_rows(readbacks)
    container = _one_object_by_id(
        object_rows,
        switch_container_id,
        field="Switch Container",
    )
    if _type_token(container.get("type")) != "switchcontainer":
        raise WorkflowEvidenceError("Switch Container readback type is invalid")
    reference_id = _reference_id(
        _first_present(
            container,
            "SwitchGroupOrStateGroup",
            "@SwitchGroupOrStateGroup",
        )
    )
    if not _same_id(reference_id, switch_group_id):
        raise WorkflowEvidenceError("Switch Container group reference GUID changed")

    child = _one_object_by_id(object_rows, child_id, field="assignment child")
    if not _same_id(_reference_id(child.get("parent")), switch_container_id):
        raise WorkflowEvidenceError(
            "assignment child parent relationship GUID changed"
        )
    group = _one_object_by_id(object_rows, switch_group_id, field="Switch Group")
    if _type_token(group.get("type")) not in {"switchgroup", "stategroup"}:
        raise WorkflowEvidenceError("Switch Group readback type is invalid")
    state = _one_object_by_id(
        object_rows,
        state_or_switch_id,
        field="state-or-switch",
    )
    if not _same_id(_reference_id(state.get("parent")), switch_group_id):
        raise WorkflowEvidenceError(
            "state-or-switch parent relationship GUID changed"
        )


def _verification_readbacks(
    verification: Mapping[str, Any],
    *,
    operation: str,
) -> list[Mapping[str, Any]]:
    if verification.get("operation") != operation:
        raise WorkflowEvidenceError(
            f"verification operation mismatch: expected {operation!r}"
        )
    if (
        verification.get("ok") is not True
        or verification.get("status") != "verified"
        or verification.get("business_state_verified") is not True
    ):
        raise WorkflowEvidenceError("verification is not a strong business-state success")
    assertions = verification.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        raise WorkflowEvidenceError("verification assertions are missing")
    if any(
        not isinstance(row, Mapping) or row.get("passed") is not True
        for row in assertions
    ):
        raise WorkflowEvidenceError("verification contains a failed assertion")
    readbacks = verification.get("readbacks")
    if not isinstance(readbacks, list) or not all(
        isinstance(row, Mapping) for row in readbacks
    ):
        raise WorkflowEvidenceError("verification readbacks are malformed")
    return list(readbacks)


def _object_readback_rows(
    readbacks: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for readback in readbacks:
        if readback.get("uri") != OBJECT_GET_URI:
            continue
        result = readback.get("result")
        if not isinstance(result, Mapping):
            raise WorkflowEvidenceError("object.get readback result is malformed")
        rows.extend(_mapping_rows(result.get("return"), field="object.get return"))
    return rows


def _normalize_inclusions(value: Any, *, field: str) -> list[dict[str, Any]]:
    rows = _mapping_rows(value, field=field)
    normalized: dict[str, set[str]] = {}
    for index, row in enumerate(rows):
        object_id = _reference_id(row.get("object"))
        object_id = _require_guid(object_id, field=f"{field}[{index}] object GUID")
        filters = row.get("filter")
        if not isinstance(filters, list) or not filters or not all(
            isinstance(item, str) and item in INCLUSION_FILTERS for item in filters
        ):
            raise WorkflowEvidenceError(f"{field}[{index}] filter is invalid")
        if len(filters) != len(set(filters)):
            raise WorkflowEvidenceError(f"{field}[{index}] filter contains duplicates")
        normalized.setdefault(object_id.casefold(), set()).update(filters)
    return [
        {"object": object_id, "filters": sorted(filters)}
        for object_id, filters in sorted(normalized.items())
    ]


def _normalize_expected_inclusions(
    value: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in value]
    wire_rows = [
        {"object": row.get("object"), "filter": row.get("filters")}
        for row in rows
    ]
    return _normalize_inclusions(wire_rows, field="expected inclusions")


def _normalize_assignment_pairs(value: Any) -> set[tuple[str, str]]:
    rows = _mapping_rows(value, field="assignment return")
    pairs: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        child = _require_guid(
            _reference_id(row.get("child")),
            field=f"assignment return[{index}] child GUID",
        )
        state = _require_guid(
            _reference_id(row.get("stateOrSwitch")),
            field=f"assignment return[{index}] state-or-switch GUID",
        )
        pair = (child.casefold(), state.casefold())
        if pair in pairs:
            raise WorkflowEvidenceError("Switch assignment pair is duplicated")
        pairs.add(pair)
    return pairs


def _one_object_by_id(
    rows: Sequence[Mapping[str, Any]],
    object_id: str,
    *,
    field: str,
) -> Mapping[str, Any]:
    matches = [
        row
        for row in rows
        if _same_id(_reference_id(row.get("id")), object_id)
    ]
    if len(matches) != 1:
        raise WorkflowEvidenceError(f"{field} GUID does not resolve exactly once")
    return matches[0]


def _mapping_rows(value: Any, *, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        raise WorkflowEvidenceError(f"{field} must be an array of objects")
    return list(value)


def _first_present(row: Mapping[str, Any], *fields: str) -> Any:
    for field in fields:
        if field in row:
            return row[field]
    return None


def _reference_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        nested = value.get("id")
        return nested if isinstance(nested, str) else None
    return None


def _same_id(left: Any, right: Any) -> bool:
    return isinstance(left, str) and isinstance(right, str) and left.casefold() == right.casefold()


def _is_guid(value: Any) -> bool:
    return isinstance(value, str) and _GUID.fullmatch(value) is not None


def _require_guid(value: Any, *, field: str) -> str:
    if not _is_guid(value):
        raise WorkflowEvidenceError(f"{field} is not canonical")
    return str(value)


def _require_wwise_path(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("\\")
        or value.startswith("\\\\")
        or value.endswith("\\")
        or "\\\\" in value
        or "/" in value
    ):
        raise WorkflowEvidenceError(f"{field} is not canonical")
    return value


def _type_token(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("name", value.get("type"))
    return str(value or "").replace(" ", "").casefold()


__all__ = [
    "WorkflowEvidenceError",
    "validate_audio_import_business_evidence",
    "validate_soundbank_inclusions_business_evidence",
    "validate_switch_assignment_business_evidence",
]
