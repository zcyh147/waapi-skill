"""Compile closed schema, test-tone, and UI-project business plans."""

from __future__ import annotations

import math
import ntpath
import posixpath
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .canonical import canonical_json_bytes
from .host_ui_debug_business_contracts import (
    BASE_PLATFORM_CHOICES,
    BIT_DEPTH_CHOICES,
    CHANNEL_LAYOUT_CHOICES,
    HOST_UI_DEBUG_BUSINESS_OPERATIONS,
    PROJECT_POLICY_CHOICES,
    WAVEFORM_CHOICES,
    host_ui_debug_business_contract_data,
)
from .operation_registry import parse_operation_request


MAX_HOST_PLAN_BYTES = 128 * 1024
MAX_COLLECTION_ITEMS = 128
MAX_PATH_BYTES = 4096
MAX_TEXT_BYTES = 8192
_WAAPI_URI = re.compile(r"^ak\.[A-Za-z0-9_.]+$")
_WAVEFORMS = {
    "silence": "silence",
    "sine": "sine",
    "triangle": "triangle",
    "square": "square",
    "white_noise": "whiteNoise",
}


def materialize_host_ui_debug_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    if operation not in HOST_UI_DEBUG_BUSINESS_OPERATIONS:
        raise ValueError("unsupported host/UI/Debug business operation")
    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    if set(session.settings) != {"host_ui_debug_plan"}:
        raise _repair(
            session,
            "BUSINESS_DECLARATION_INCOMPLETE",
            field="host_ui_debug_plan",
            action="submit one complete disclosed host/UI/Debug plan",
        )
    raw = session.settings["host_ui_debug_plan"]
    if not isinstance(raw, Mapping):
        raise _invalid(session, "host_ui_debug_plan", "submit one structured plan")
    plan = dict(raw)
    try:
        size = len(canonical_json_bytes(plan))
    except (TypeError, ValueError) as exc:
        raise _invalid(
            session,
            "host_ui_debug_plan",
            "use strict JSON business values",
        ) from exc
    if size > MAX_HOST_PLAN_BYTES:
        raise _invalid(
            session,
            "host_ui_debug_plan",
            "split the work into separately previewed bounded operations",
            limit_bytes=MAX_HOST_PLAN_BYTES,
        )
    try:
        contract = host_ui_debug_business_contract_data(
            operation,
            session.context.wwise_version,
        )
    except ValueError as exc:
        raise _repair(
            session,
            "VERSION_BEHAVIOR_BOUNDARY",
            field="host_ui_debug_plan",
            action="select an operation available in the connected Wwise version",
        ) from exc
    declaration = contract["declaration"]
    missing = sorted(set(declaration["required_fields"]) - set(plan))
    unexpected = sorted(set(plan) - set(declaration["public_fields"]))
    if missing or unexpected:
        raise _invalid(
            session,
            unexpected[0] if unexpected else missing[0],
            "use exactly the fields disclosed for this operation and version",
            missing_fields=missing,
            unexpected_fields=unexpected,
        )
    normalized = _normalize(
        session,
        plan,
        declaration["field_types"],
    )
    native_args = _native_args(operation, normalized)
    arguments: dict[str, Any] = {
        "api": operation,
        "args": native_args,
        "options": {},
    }
    io_root = _io_root(operation, normalized)
    if io_root is not None:
        arguments["io_root"] = io_root
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": session.context.wwise_version,
        "operation": "waapi.call",
        "arguments": arguments,
    }
    parse_operation_request(request, expected_version=session.context.wwise_version)
    return request


def materialize_waapi_schema_read_args(
    version: str,
    *,
    target_uri: str,
    include_examples: bool | None,
) -> dict[str, Any]:
    """Build the bounded direct-read args without exposing native field names."""

    if version not in {"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"}:
        raise ValueError("unsupported Wwise version")
    if not isinstance(target_uri, str) or not _WAAPI_URI.fullmatch(target_uri):
        raise ValueError("target_uri must be one exact WAAPI URI")
    if include_examples is not None and type(include_examples) is not bool:
        raise ValueError("include_examples must be a boolean when supplied")
    if include_examples is not None and version not in {"2024.1", "2025.1"}:
        raise ValueError("include_examples is unavailable before Wwise 2024.1")
    return {
        "uri": target_uri,
        **(
            {"includeExamples": include_examples}
            if include_examples is not None
            else {}
        ),
    }


def _normalize(
    session: BusinessDeclarationSession,
    plan: Mapping[str, Any],
    field_types: Mapping[str, str],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field, raw in plan.items():
        field_type = field_types[field]
        if field_type == "boolean":
            if type(raw) is not bool:
                raise _invalid(session, field, "provide a JSON boolean")
            result[field] = raw
        elif field_type in {
            "frequency_hz",
            "sample_rate_hz",
            "nonnegative_seconds",
            "sustain_db",
        }:
            result[field] = _number(session, field, field_type, raw)
        elif field_type == "channel_index_list":
            result[field] = _channel_indexes(session, field, raw)
        elif field_type == "tone_marker_list":
            result[field] = _markers(session, field, raw)
        elif field_type == "language_name_list":
            result[field] = _string_list(session, field, raw)
        elif field_type == "platform_creation_mappings":
            result[field] = _platforms(session, field, raw)
        else:
            value = _string(session, field, raw)
            limit = MAX_PATH_BYTES if "file" in field_type else MAX_TEXT_BYTES
            if len(value.encode("utf-8")) > limit:
                raise _invalid(
                    session,
                    field,
                    "shorten the value to its disclosed byte limit",
                )
            if field_type in {"exact_wav_file", "exact_project_file"}:
                _absolute_path(session, field, value)
                suffix = ".wav" if field_type == "exact_wav_file" else ".wproj"
                if not value.casefold().endswith(suffix):
                    raise _invalid(session, field, f"provide one exact {suffix} file")
            if field_type == "exact_waapi_uri" and not _WAAPI_URI.fullmatch(value):
                raise _invalid(session, field, "provide one exact WAAPI URI")
            choices = {
                "waveform": WAVEFORM_CHOICES,
                "channel_layout": CHANNEL_LAYOUT_CHOICES,
                "bit_depth": BIT_DEPTH_CHOICES,
                "project_policy": PROJECT_POLICY_CHOICES,
            }.get(field_type)
            if choices is not None and value not in choices:
                raise _invalid(
                    session,
                    field,
                    "choose one disclosed business value",
                    choices=list(choices),
                )
            result[field] = value
    if "waveform_channels" in result:
        layout = str(result.get("channel_layout", "1.0"))
        channel_count = _channel_count(layout)
        invalid = [
            index
            for index in result["waveform_channels"]
            if index >= channel_count
        ]
        if invalid:
            raise _invalid(
                session,
                "waveform_channels",
                "choose only channel indexes present in the selected layout",
                channel_layout=layout,
                channel_count=channel_count,
                invalid_indexes=invalid,
            )
    if (
        str(result.get("channel_layout", "")).startswith("Ambisonics ")
        and result.get("waveform", "silence") != "silence"
    ):
        raise _invalid(
            session,
            "waveform",
            "use silence for an Ambisonics channel layout",
        )
    return result


def _native_args(operation: str, plan: Mapping[str, Any]) -> dict[str, Any]:
    if operation == "ak.wwise.waapi.getSchema":
        result = {"uri": plan["target_uri"]}
        if "include_examples" in plan:
            result["includeExamples"] = plan["include_examples"]
        return result
    if operation == "ak.wwise.debug.generateToneWAV":
        result = {"path": plan["output_file"]}
        mappings = {
            "frequency_hz": "frequency",
            "channel_layout": "channelConfig",
            "bit_depth": "bitDepth",
            "sample_rate_hz": "sampleRate",
            "attack_seconds": "attackTime",
            "sustain_seconds": "sustainTime",
            "release_seconds": "releaseTime",
            "sustain_db": "sustainLevel",
            "anonymous_channels": "setAnonymous",
        }
        if "waveform" in plan:
            result["waveform"] = _WAVEFORMS[str(plan["waveform"])]
        for public, native in mappings.items():
            if public in plan:
                result[native] = plan[public]
        if "waveform_channels" in plan:
            result["waveformChannelMask"] = sum(
                1 << index for index in plan["waveform_channels"]
            )
        if "markers" in plan:
            result["markers"] = [
                {
                    "position": marker["position_seconds"],
                    **(
                        {"label": marker["label"]}
                        if "label" in marker
                        else {}
                    ),
                }
                for marker in plan["markers"]
            ]
        return result
    if operation == "ak.wwise.ui.project.close":
        return (
            {"bypassSave": plan["discard_unsaved_changes"]}
            if "discard_unsaved_changes" in plan
            else {}
        )
    result = {"path": plan["project_file"]}
    if operation == "ak.wwise.ui.project.create":
        if "languages" in plan:
            result["languages"] = plan["languages"]
        if "platforms" in plan:
            result["platforms"] = [
                {"basePlatform": base, "name": name}
                for base, name in plan["platforms"]
            ]
        return result
    mappings = {
        "discard_unsaved_current_project": "bypassSave",
        "upgrade_policy": "onUpgrade",
        "migration_policy": "onMigrationRequired",
        "auto_checkout": "autoCheckOutToSourceControl",
    }
    for public, native in mappings.items():
        if public in plan:
            result[native] = plan[public]
    return result


def _io_root(operation: str, plan: Mapping[str, Any]) -> str | None:
    field = (
        "output_file"
        if operation == "ak.wwise.debug.generateToneWAV"
        else "project_file"
        if operation in {"ak.wwise.ui.project.create", "ak.wwise.ui.project.open"}
        else None
    )
    return _parent(str(plan[field])) if field is not None else None


def _number(
    session: BusinessDeclarationSession,
    field: str,
    field_type: str,
    raw: object,
) -> int | float:
    if (
        isinstance(raw, bool)
        or not isinstance(raw, (int, float))
        or not math.isfinite(raw)
    ):
        raise _invalid(session, field, "provide one finite number")
    lower, upper = {
        "frequency_hz": (1, 22000),
        "sample_rate_hz": (300, 192000),
        "nonnegative_seconds": (0, None),
        "sustain_db": (-100, 0),
    }[field_type]
    if raw < lower or upper is not None and raw > upper:
        raise _invalid(session, field, "provide a number inside the disclosed range")
    return raw


def _channel_indexes(
    session: BusinessDeclarationSession,
    field: str,
    raw: object,
) -> list[int]:
    if not isinstance(raw, list) or not raw or len(raw) > 64:
        raise _invalid(session, field, "provide one or more channel indexes")
    values: list[int] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 63:
            raise _invalid(session, field, "provide channel indexes from 0 through 63")
        values.append(value)
    if len(set(values)) != len(values):
        raise _invalid(session, field, "provide each channel index once")
    return values


def _channel_count(layout: str) -> int:
    fixed = {
        "0.1": 1,
        "1.0": 1,
        "2.0": 2,
        "2.1": 3,
        "3.0": 3,
        "4.0": 4,
        "5.1": 6,
        "7.1": 8,
        "5.1.2": 8,
        "7.1.2": 10,
        "7.1.4": 12,
    }
    if layout in fixed:
        return fixed[layout]
    match = re.fullmatch(r"Ambisonics ([1-5])(st|nd|rd|th) order", layout)
    if match is None:  # pragma: no cover - closed contract validates first.
        raise ValueError("unsupported channel layout")
    order = int(match.group(1))
    return (order + 1) ** 2


def _markers(
    session: BusinessDeclarationSession,
    field: str,
    raw: object,
) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > MAX_COLLECTION_ITEMS:
        raise _invalid(session, field, "provide a bounded marker list")
    result: list[dict[str, Any]] = []
    for marker in raw:
        if not isinstance(marker, Mapping) or set(marker) - {
            "position_seconds",
            "label",
        }:
            raise _invalid(
                session,
                field,
                "provide markers with position_seconds and optional label",
            )
        if "position_seconds" not in marker:
            raise _invalid(session, field, "provide every marker position_seconds")
        position = _number(
            session,
            field,
            "nonnegative_seconds",
            marker["position_seconds"],
        )
        row: dict[str, Any] = {"position_seconds": position}
        if "label" in marker:
            label = marker["label"]
            if (
                not isinstance(label, str)
                or "\x00" in label
                or len(label.encode("utf-8")) > MAX_TEXT_BYTES
            ):
                raise _invalid(session, field, "provide one bounded exact marker label")
            row["label"] = label
        result.append(row)
    return result


def _string_list(
    session: BusinessDeclarationSession,
    field: str,
    raw: object,
) -> list[str]:
    if not isinstance(raw, list) or not raw or len(raw) > MAX_COLLECTION_ITEMS:
        raise _invalid(session, field, "provide one or more bounded exact values")
    values = [_string(session, field, value) for value in raw]
    if len(set(values)) != len(values):
        raise _invalid(session, field, "provide each value once")
    return values


def _platforms(
    session: BusinessDeclarationSession,
    field: str,
    raw: object,
) -> list[list[str]]:
    if not isinstance(raw, list) or not raw or len(raw) > MAX_COLLECTION_ITEMS:
        raise _invalid(session, field, "provide one or more platform mappings")
    result: list[list[str]] = []
    names: set[str] = set()
    for row in raw:
        if not isinstance(row, list) or len(row) != 2:
            raise _invalid(session, field, "provide each platform as [base, name]")
        base = _string(session, field, row[0])
        name = _string(session, field, row[1])
        if base not in BASE_PLATFORM_CHOICES:
            raise _invalid(session, field, "choose one disclosed base platform")
        if name.casefold() in names:
            raise _invalid(session, field, "provide each project platform name once")
        names.add(name.casefold())
        result.append([base, name])
    return result
def _string(session: BusinessDeclarationSession, field: str, raw: object) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise _invalid(session, field, "provide one nonempty exact string")
    return raw


def _absolute_path(session: BusinessDeclarationSession, field: str, value: str) -> None:
    if not (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()):
        raise _invalid(session, field, "provide one exact absolute filesystem path")


def _parent(value: str) -> str:
    windows = PureWindowsPath(value).is_absolute() and not PurePosixPath(value).is_absolute()
    module = ntpath if windows else posixpath
    return module.dirname(module.normpath(value))


def _invalid(
    session: BusinessDeclarationSession,
    field: str,
    action: str,
    **details: Any,
):
    return _repair(session, "INVALID_ARGUMENT", field=field, action=action, **details)


def _repair(
    session: BusinessDeclarationSession,
    error_code: str,
    *,
    field: str,
    action: str,
    **details: Any,
):
    return business_repair(
        error_code,
        field=field,
        action=action,
        draft_revision=session.revision,
        **details,
    )


__all__ = [
    "MAX_COLLECTION_ITEMS",
    "MAX_HOST_PLAN_BYTES",
    "materialize_host_ui_debug_business_request",
    "materialize_waapi_schema_read_args",
]
