"""Closed cross-version requests and projections for stable fixed reads.

These adapters keep the small set of known WAAPI compatibility deltas out of
agent-authored payloads.  They build only reviewed args/options and normalize
only fields whose names or availability differ between supported Wwise lanes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


GET_PROJECT_INFO_URI = "ak.wwise.core.getProjectInfo"
GET_GAME_OBJECTS_URI = "ak.wwise.core.profiler.getGameObjects"
GET_VOICE_CONTRIBUTIONS_URI = (
    "ak.wwise.core.profiler.getVoiceContributions"
)

STABLE_READ_REQUEST_CONTRACT = "waapi-skill.stable-read-request/v1"
STABLE_READ_RESULT_LIMIT_BYTES = 256 * 1024
PROFILER_TIME_CURSORS = frozenset({"user", "capture"})
MAX_PROFILER_TIME_MILLISECONDS = (1 << 53) - 1
MAX_PIPELINE_ID = (1 << 32) - 1
MAX_BUS_PIPELINE_IDS = 64
MAX_GAME_OBJECT_ROWS = 4096
MAX_STABLE_STRING_BYTES = 4096
MAX_CONTRIBUTION_DEPTH = 32
MAX_CONTRIBUTION_NODES = 8192

_ASCII_UNSIGNED_INTEGER = re.compile(r"[0-9]+")
_GAME_OBJECT_VERSIONS = frozenset(
    {"2022.1", "2023.1", "2024.1", "2025.1"}
)
_PROJECT_INFO_VERSIONS = frozenset(
    {"2022.1", "2023.1", "2024.1", "2025.1"}
)
_DEFAULT_WORK_UNIT_VERSION = "2025.1"
_DEFAULT_WORK_UNIT_CATEGORIES = (
    "Busses",
    "Containers",
    "Events",
    "Switches",
    "States",
    "SoundBanks",
    "GameParameters",
    "Effects",
    "Devices",
    "Presets",
    "SoundcasterSessions",
    "MixingSessions",
    "Queries",
    "Triggers",
    "Attenuations",
    "DynamicDialogue",
    "Conversions",
    "Modulators",
    "ControlSurfaceSessions",
    "VirtualAcoustics",
    "Metadatas",
    "SidechainMixes",
)


class StableReadContractError(ValueError):
    """Machine-readable input/version/result failure for one fixed read."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": dict(self.details),
        }


@dataclass(slots=True, frozen=True)
class StableReadRequest:
    """One immutable fixed-read request ready for dispatcher validation."""

    version: str
    uri: str
    args: Mapping[str, Any]
    options: Mapping[str, Any]

    def dispatch_payload(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "args": dict(self.args),
            "options": dict(self.options),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": STABLE_READ_REQUEST_CONTRACT,
            "version": self.version,
            **self.dispatch_payload(),
        }


def normalize_profiler_time(value: Any) -> int | str:
    """Normalize a non-negative millisecond time or a reviewed cursor token."""

    if isinstance(value, bool):
        raise _input_error(
            "Profiler time must be a non-negative integer or one of: user, capture.",
            field="time",
            actual_type="bool",
        )
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, str):
        if value in PROFILER_TIME_CURSORS:
            return value
        if _ASCII_UNSIGNED_INTEGER.fullmatch(value) is None:
            raise _input_error(
                "Profiler time must be a non-negative integer or one of: user, capture.",
                field="time",
                string_length=len(value),
            )
        if len(value) > 16:
            raise _input_error(
                "Profiler time is outside the reviewed exact JSON integer range.",
                field="time",
                maximum=MAX_PROFILER_TIME_MILLISECONDS,
                digit_count=len(value),
            )
        normalized = int(value)
    else:
        raise _input_error(
            "Profiler time must be a non-negative integer or one of: user, capture.",
            field="time",
            actual_type=type(value).__name__,
        )
    if not 0 <= normalized <= MAX_PROFILER_TIME_MILLISECONDS:
        raise _input_error(
            "Profiler time is outside the reviewed exact JSON integer range.",
            field="time",
            minimum=0,
            maximum=MAX_PROFILER_TIME_MILLISECONDS,
            value=normalized,
        )
    return normalized


def normalize_pipeline_id(value: Any, *, field: str) -> int:
    """Normalize one exact unsigned 32-bit profiler pipeline identifier."""

    if isinstance(value, bool):
        raise _input_error(
            f"{field} must be an unsigned 32-bit integer.",
            field=field,
            actual_type="bool",
        )
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, str) and _ASCII_UNSIGNED_INTEGER.fullmatch(value):
        if len(value) > 10:
            raise _input_error(
                f"{field} must be an unsigned 32-bit integer.",
                field=field,
                minimum=0,
                maximum=MAX_PIPELINE_ID,
                digit_count=len(value),
            )
        normalized = int(value)
    else:
        raise _input_error(
            f"{field} must be an unsigned 32-bit integer.",
            field=field,
            actual_type=type(value).__name__,
            string_length=len(value) if isinstance(value, str) else None,
        )
    if not 0 <= normalized <= MAX_PIPELINE_ID:
        raise _input_error(
            f"{field} must be an unsigned 32-bit integer.",
            field=field,
            minimum=0,
            maximum=MAX_PIPELINE_ID,
            value=normalized,
        )
    return normalized


def build_profiler_game_objects_request(
    *,
    version: str,
    time: Any,
) -> StableReadRequest:
    """Build the fixed ``getGameObjects`` request for Wwise 2022.1+."""

    _require_version(version, _GAME_OBJECT_VERSIONS, GET_GAME_OBJECTS_URI)
    return StableReadRequest(
        version=version,
        uri=GET_GAME_OBJECTS_URI,
        args={"time": normalize_profiler_time(time)},
        options={},
    )


def build_profiler_voice_contributions_request(
    *,
    version: str,
    time: Any,
    voice_pipeline_id: Any,
    bus_pipeline_ids: Sequence[Any] = (),
) -> StableReadRequest:
    """Build a closed voice-path contribution query for all five versions."""

    _require_version(
        version,
        frozenset(SUPPORTED_WWISE_VERSION_KEYS),
        GET_VOICE_CONTRIBUTIONS_URI,
    )
    if isinstance(bus_pipeline_ids, (str, bytes)) or not isinstance(
        bus_pipeline_ids, Sequence
    ):
        raise _input_error(
            "bus_pipeline_ids must be an ordered array of pipeline identifiers.",
            field="bus_pipeline_ids",
            actual_type=type(bus_pipeline_ids).__name__,
        )
    if len(bus_pipeline_ids) > MAX_BUS_PIPELINE_IDS:
        raise _input_error(
            "Too many bus pipeline identifiers were supplied.",
            field="bus_pipeline_ids",
            maximum=MAX_BUS_PIPELINE_IDS,
            actual_count=len(bus_pipeline_ids),
        )
    buses = [
        normalize_pipeline_id(value, field=f"bus_pipeline_ids[{index}]")
        for index, value in enumerate(bus_pipeline_ids)
    ]
    if len(set(buses)) != len(buses):
        raise _input_error(
            "bus_pipeline_ids must not contain duplicates.",
            field="bus_pipeline_ids",
        )
    args: dict[str, Any] = {
        "voicePipelineID": normalize_pipeline_id(
            voice_pipeline_id,
            field="voice_pipeline_id",
        ),
        "bussesPipelineID": buses,
        "time": normalize_profiler_time(time),
    }
    return StableReadRequest(
        version=version,
        uri=GET_VOICE_CONTRIBUTIONS_URI,
        args=args,
        options={},
    )


def build_project_default_work_units_request(
    *,
    version: str,
) -> StableReadRequest:
    """Build the project-info request used to inspect default Work Units."""

    _require_version(version, _PROJECT_INFO_VERSIONS, GET_PROJECT_INFO_URI)
    return StableReadRequest(
        version=version,
        uri=GET_PROJECT_INFO_URI,
        args={},
        options={},
    )


def normalize_profiler_game_objects_result(
    *,
    version: str,
    result: Any,
) -> dict[str, Any]:
    """Project 2022 and 2023+ registration-field spellings to one shape."""

    _require_version(version, _GAME_OBJECT_VERSIONS, GET_GAME_OBJECTS_URI)
    payload = _require_result_mapping(GET_GAME_OBJECTS_URI, result)
    rows = payload.get("return")
    if not isinstance(rows, list):
        raise _result_error(
            GET_GAME_OBJECTS_URI,
            "The successful result must contain a return array.",
            expected={"return": "array<object>"},
            actual_type=type(rows).__name__,
        )
    if len(rows) > MAX_GAME_OBJECT_ROWS:
        raise _result_error(
            GET_GAME_OBJECTS_URI,
            "The game-object result exceeded the fixed row ceiling.",
            maximum_rows=MAX_GAME_OBJECT_ROWS,
            actual_count=len(rows),
        )
    register_field, unregister_field = (
        ("registrationTime", "unregistrationTime")
        if version == "2022.1"
        else ("registerTime", "unregisterTime")
    )
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise _result_error(
                GET_GAME_OBJECTS_URI,
                "Every game-object row must be an object.",
                row_index=index,
                actual_type=type(row).__name__,
            )
        for field in ("id", "name", register_field, unregister_field):
            if field not in row:
                raise _result_error(
                    GET_GAME_OBJECTS_URI,
                    "A game-object row omitted a required stable field.",
                    row_index=index,
                    missing_field=field,
                )
        object_id = row["id"]
        if (
            not isinstance(object_id, int)
            or isinstance(object_id, bool)
            or not -(1 << 63) <= object_id <= (1 << 64) - 1
        ):
            raise _result_error(
                GET_GAME_OBJECTS_URI,
                "A game-object id was not a supported 64-bit integer.",
                row_index=index,
                field="id",
                actual_type=type(object_id).__name__,
            )
        name = _bounded_result_string(
            GET_GAME_OBJECTS_URI,
            row["name"],
            field="name",
            row_index=index,
        )
        register_time = _int32_result(
            GET_GAME_OBJECTS_URI,
            row[register_field],
            field=register_field,
            row_index=index,
        )
        unregister_time = _int32_result(
            GET_GAME_OBJECTS_URI,
            row[unregister_field],
            field=unregister_field,
            row_index=index,
        )
        normalized.append(
            {
                "id": object_id,
                "name": name,
                "register_time": register_time,
                "unregister_time": unregister_time,
            }
        )
    return {
        "count": len(normalized),
        "game_objects": normalized,
    }


def normalize_profiler_voice_contributions_result(
    *,
    version: str,
    result: Any,
) -> dict[str, Any]:
    """Normalize the 2025-only DSF field without inventing an older value."""

    _require_version(
        version,
        frozenset(SUPPORTED_WWISE_VERSION_KEYS),
        GET_VOICE_CONTRIBUTIONS_URI,
    )
    payload = _require_result_mapping(GET_VOICE_CONTRIBUTIONS_URI, result)
    contribution = payload.get("return")
    dsf_available = version == "2025.1"
    if contribution is None:
        return {
            "contribution_reported": False,
            "volume": None,
            "lpf": None,
            "hpf": None,
            "dsf": {
                "feature_available": dsf_available,
                "reported": False,
                "value": None,
            },
            "objects": None,
        }
    if not isinstance(contribution, Mapping):
        raise _result_error(
            GET_VOICE_CONTRIBUTIONS_URI,
            "The successful result.return value must be an object when reported.",
            actual_type=type(contribution).__name__,
        )
    for field in ("volume", "LPF", "HPF", "objects"):
        if field not in contribution:
            raise _result_error(
                GET_VOICE_CONTRIBUTIONS_URI,
                "The reported voice contribution omitted a required stable field.",
                missing_field=field,
            )
    volume = _finite_result_number(
        GET_VOICE_CONTRIBUTIONS_URI,
        contribution["volume"],
        field="volume",
    )
    lpf = _finite_result_number(
        GET_VOICE_CONTRIBUTIONS_URI,
        contribution["LPF"],
        field="LPF",
    )
    hpf = _finite_result_number(
        GET_VOICE_CONTRIBUTIONS_URI,
        contribution["HPF"],
        field="HPF",
    )
    objects = contribution["objects"]
    if not isinstance(objects, list):
        raise _result_error(
            GET_VOICE_CONTRIBUTIONS_URI,
            "The reported voice contribution objects field must be an array.",
            field="objects",
            actual_type=type(objects).__name__,
        )
    normalized_objects = _bounded_json_copy(
        GET_VOICE_CONTRIBUTIONS_URI,
        objects,
    )
    dsf_reported = "DSF" in contribution
    if dsf_reported and not dsf_available:
        raise _result_error(
            GET_VOICE_CONTRIBUTIONS_URI,
            "Wwise reported the 2025-only DSF field for an older version lane.",
            version=version,
            field="DSF",
        )
    dsf_value = (
        _finite_result_number(
            GET_VOICE_CONTRIBUTIONS_URI,
            contribution["DSF"],
            field="DSF",
        )
        if dsf_reported
        else None
    )
    return {
        "contribution_reported": True,
        "volume": volume,
        "lpf": lpf,
        "hpf": hpf,
        "dsf": {
            "feature_available": dsf_available,
            "reported": dsf_reported,
            "value": dsf_value,
        },
        "objects": normalized_objects,
    }


def normalize_project_default_work_units_result(
    *,
    version: str,
    result: Any | None,
) -> dict[str, Any]:
    """Expose 2025 project defaults with explicit availability/reporting facts."""

    _require_supported_version(version)
    feature_available = version == _DEFAULT_WORK_UNIT_VERSION
    if version == "2021.1":
        if result is not None:
            raise _result_error(
                GET_PROJECT_INFO_URI,
                "Wwise 2021.1 has no reflected getProjectInfo result.",
                version=version,
            )
        payload: Mapping[str, Any] = {}
    else:
        payload = _require_result_mapping(GET_PROJECT_INFO_URI, result)
    if not feature_available and (
        "defaultWorkUnits" in payload or "defaultImportWorkUnit" in payload
    ):
        raise _result_error(
            GET_PROJECT_INFO_URI,
            "Wwise reported 2025-only default Work Unit fields for an older version lane.",
            version=version,
        )

    work_units_reported = "defaultWorkUnits" in payload
    import_work_unit_reported = "defaultImportWorkUnit" in payload
    work_units = (
        _normalize_default_work_units(payload["defaultWorkUnits"])
        if work_units_reported
        else None
    )
    import_work_unit = (
        _normalize_work_unit(
            payload["defaultImportWorkUnit"],
            field="defaultImportWorkUnit",
        )
        if import_work_unit_reported
        else None
    )
    return {
        "default_work_units": {
            "feature_available": feature_available,
            "reported": work_units_reported,
            "value": work_units,
        },
        "default_import_work_unit": {
            "feature_available": feature_available,
            "reported": import_work_unit_reported,
            "value": import_work_unit,
        },
    }


def _normalize_default_work_units(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, Mapping):
        raise _result_error(
            GET_PROJECT_INFO_URI,
            "defaultWorkUnits must be an object when reported.",
            field="defaultWorkUnits",
            actual_type=type(value).__name__,
        )
    if not all(isinstance(key, str) for key in value):
        raise _result_error(
            GET_PROJECT_INFO_URI,
            "defaultWorkUnits contained a non-string category key.",
            field="defaultWorkUnits",
        )
    actual = set(value)
    expected = set(_DEFAULT_WORK_UNIT_CATEGORIES)
    if actual != expected:
        raise _result_error(
            GET_PROJECT_INFO_URI,
            "defaultWorkUnits did not match the pinned 2025.1 category set.",
            field="defaultWorkUnits",
            missing_categories=sorted(expected - actual),
            unexpected_categories=sorted(actual - expected),
        )
    return {
        category: _normalize_work_unit(
            value[category],
            field=f"defaultWorkUnits.{category}",
        )
        for category in _DEFAULT_WORK_UNIT_CATEGORIES
    }


def _normalize_work_unit(value: Any, *, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise _result_error(
            GET_PROJECT_INFO_URI,
            "A default Work Unit value must be an object.",
            field=field,
            actual_type=type(value).__name__,
        )
    required = ("id", "name", "path", "filePath")
    missing = [name for name in required if name not in value]
    if missing:
        raise _result_error(
            GET_PROJECT_INFO_URI,
            "A default Work Unit value omitted required fields.",
            field=field,
            missing_fields=missing,
        )
    return {
        name: _bounded_result_string(
            GET_PROJECT_INFO_URI,
            value[name],
            field=f"{field}.{name}",
        )
        for name in required
    }


def _bounded_json_copy(api: str, value: Any) -> Any:
    nodes = 0

    def copy(item: Any, *, depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_CONTRIBUTION_NODES:
            raise _result_error(
                api,
                "The contribution tree exceeded the fixed node ceiling.",
                maximum_nodes=MAX_CONTRIBUTION_NODES,
            )
        if depth > MAX_CONTRIBUTION_DEPTH:
            raise _result_error(
                api,
                "The contribution tree exceeded the fixed depth ceiling.",
                maximum_depth=MAX_CONTRIBUTION_DEPTH,
            )
        if item is None or isinstance(item, (bool, int)):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise _result_error(
                    api,
                    "The contribution tree contained a non-finite number.",
                )
            return item
        if isinstance(item, str):
            _require_bounded_string_bytes(api, item, field="contribution_tree")
            return item
        if isinstance(item, list):
            return [copy(child, depth=depth + 1) for child in item]
        if isinstance(item, Mapping):
            copied: dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise _result_error(
                        api,
                        "The contribution tree contained a non-string object key.",
                        actual_type=type(key).__name__,
                    )
                _require_bounded_string_bytes(api, key, field="contribution_tree_key")
                copied[key] = copy(child, depth=depth + 1)
            return copied
        raise _result_error(
            api,
            "The contribution tree contained a non-JSON value.",
            actual_type=type(item).__name__,
        )

    return copy(value, depth=0)


def _require_version(
    version: str,
    supported: frozenset[str],
    api: str,
) -> None:
    _require_supported_version(version)
    if version not in supported:
        raise StableReadContractError(
            "UNSUPPORTED_STABLE_READ_VERSION",
            f"{api} is not reflected in the Wwise {version} fixed-read lane.",
            details={
                "api": api,
                "version": version,
                "supported_versions": sorted(supported),
            },
        )


def _require_supported_version(version: str) -> None:
    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise StableReadContractError(
            "UNSUPPORTED_STABLE_READ_VERSION",
            f"Unsupported Wwise version {version!r}.",
            details={
                "version": version,
                "supported_versions": list(SUPPORTED_WWISE_VERSION_KEYS),
            },
        )


def _require_result_mapping(api: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _result_error(
            api,
            "The successful WAAPI result must be an object.",
            actual_type=type(value).__name__,
        )
    return value


def _finite_result_number(api: str, value: Any, *, field: str) -> int | float:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, float) or not math.isfinite(value):
        raise _result_error(
            api,
            "A voice contribution measurement must be a finite number.",
            field=field,
            actual_type=type(value).__name__,
        )
    return value


def _int32_result(
    api: str,
    value: Any,
    *,
    field: str,
    row_index: int,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not -(1 << 31) <= value <= (1 << 31) - 1
    ):
        raise _result_error(
            api,
            "A game-object registration time must be a signed 32-bit integer.",
            field=field,
            row_index=row_index,
            actual_type=type(value).__name__,
        )
    return value


def _bounded_result_string(
    api: str,
    value: Any,
    *,
    field: str,
    row_index: int | None = None,
) -> str:
    if not isinstance(value, str):
        details: dict[str, Any] = {
            "field": field,
            "actual_type": type(value).__name__,
        }
        if row_index is not None:
            details["row_index"] = row_index
        raise _result_error(
            api,
            "A stable read string field had the wrong type.",
            **details,
        )
    _require_bounded_string_bytes(api, value, field=field)
    return value


def _require_bounded_string_bytes(api: str, value: str, *, field: str) -> None:
    try:
        observed = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise _result_error(
            api,
            "A stable read string field was not valid Unicode.",
            field=field,
        ) from exc
    if observed > MAX_STABLE_STRING_BYTES:
        raise _result_error(
            api,
            "A stable read string field exceeded the fixed byte ceiling.",
            field=field,
            maximum_bytes=MAX_STABLE_STRING_BYTES,
            observed_bytes=observed,
        )


def _input_error(message: str, **details: Any) -> StableReadContractError:
    return StableReadContractError(
        "INVALID_STABLE_READ_INPUT",
        message,
        details=details,
    )


def _result_error(
    api: str,
    message: str,
    **details: Any,
) -> StableReadContractError:
    return StableReadContractError(
        "INVALID_STABLE_READ_RESULT",
        message,
        details={"api": api, **details},
    )


__all__ = [
    "GET_GAME_OBJECTS_URI",
    "GET_PROJECT_INFO_URI",
    "GET_VOICE_CONTRIBUTIONS_URI",
    "MAX_BUS_PIPELINE_IDS",
    "MAX_PIPELINE_ID",
    "MAX_PROFILER_TIME_MILLISECONDS",
    "PROFILER_TIME_CURSORS",
    "STABLE_READ_REQUEST_CONTRACT",
    "STABLE_READ_RESULT_LIMIT_BYTES",
    "StableReadContractError",
    "StableReadRequest",
    "build_profiler_game_objects_request",
    "build_profiler_voice_contributions_request",
    "build_project_default_work_units_request",
    "normalize_pipeline_id",
    "normalize_profiler_game_objects_result",
    "normalize_profiler_time",
    "normalize_profiler_voice_contributions_result",
    "normalize_project_default_work_units_result",
]
