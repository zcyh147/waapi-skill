"""Compile and normalize closed media/build business reads."""

from __future__ import annotations

import base64
import binascii
import math
import re
import stat
import struct
from pathlib import Path
from typing import Any, Mapping, Sequence

from .filesystem_security import metadata_is_link_or_reparse
from .host_paths import HostPathError, localize_waapi_host_path
from .business_declarations import normalize_live_object_identity
from .media_build_business_contracts import (
    MEDIA_POOL_GET_URI,
    MEDIA_POOL_NUMBER_OPERATOR_TOKENS,
    MEDIA_POOL_SORT_DIRECTIONS,
    MEDIA_POOL_TEXT_OPERATOR_TOKENS,
    PEAKS_REGION_URI,
    PEAKS_TRIMMED_URI,
    SOUNDBANK_GET_INCLUSIONS_URI,
    media_build_business_contract_data,
)


MEDIA_BUILD_CALL_CONTRACT = "waapi-skill.media-build-call/v1"
MEDIA_BUILD_RESULT_CONTRACT = "waapi-skill.media-build-result/v1"
MAX_PEAK_PAIR_COUNT = 512
MAX_MEDIA_POOL_RESULTS = 200
MAX_MEDIA_POOL_FILTERS = 16
MAX_MEDIA_POOL_DATABASES = 8
MAX_MEDIA_POOL_RETURN_FIELDS = 32
MAX_MEDIA_POOL_TEXT_CHARS = 4096
MAX_MEDIA_POOL_SEARCH_TEXT_CHARS = 1024
MAX_MEDIA_POOL_FIELD_TOKEN_CHARS = 256
MAX_SOUNDBANK_INCLUSIONS = 500

_GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
_TEXT_OPERATORS = frozenset(MEDIA_POOL_TEXT_OPERATOR_TOKENS)
_NUMBER_OPERATORS = frozenset(MEDIA_POOL_NUMBER_OPERATOR_TOKENS)
_DATABASE_SCOPES = {
    "project-originals": r"\Databases\Project Originals",
    "project originals": r"\Databases\Project Originals",
    r"\databases\project originals": r"\Databases\Project Originals",
}
_FIELD_ALIASES = {
    "filename": "Filename",
    "name": "Filename",
    "name/file": "Filename",
    "path": "Path",
    "fileid": "FileId",
    "file-id": "FileId",
    "database": "Db",
    "database-id": "Db",
    "duration": "WAV/Duration",
    "duration-seconds": "WAV/Duration",
    "sample-rate": "WAV/Sample Rate",
    "sample-rate-hz": "WAV/Sample Rate",
    "bit-depth": "WAV/Bit Depth",
    "channels": "WAV/Channels",
    "channel-count": "WAV/Channels",
    "ixml-scene": "IXML/Scene",
    "scene": "IXML/Scene",
    "ixml-take": "IXML/Take",
    "take": "IXML/Take",
}
_FIXED_MEDIA_FIELDS = ("Path", "FileId", "Db")


class MediaBuildBusinessError(ValueError):
    """One high-level media/build declaration cannot be closed safely."""

    def __init__(self, message: str, *, code: str = "MEDIA_BUILD_INPUT_INVALID") -> None:
        super().__init__(message)
        self.code = code


def _canonical_guid(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _GUID_RE.fullmatch(value):
        raise MediaBuildBusinessError(
            f"{field} requires one exact GUID copied from Gateway evidence"
        )
    return value.upper()


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise MediaBuildBusinessError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MediaBuildBusinessError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise MediaBuildBusinessError(f"{field} must be a finite number")
    return number


def _bounded_text(value: Any, *, field: str, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise MediaBuildBusinessError(f"{field} must be a bounded string")
    if len(value) > MAX_MEDIA_POOL_TEXT_CHARS:
        raise MediaBuildBusinessError(
            f"{field} exceeds {MAX_MEDIA_POOL_TEXT_CHARS} characters"
        )
    return value


def _normalize_token(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _business_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    if not key:
        raise MediaBuildBusinessError("Media Pool field meaning has no stable key")
    return key


def _resolve_media_field(meaning: str, available_fields: Sequence[str]) -> str:
    meaning = _bounded_text(meaning, field="field meaning")
    if len(meaning) > MAX_MEDIA_POOL_FIELD_TOKEN_CHARS:
        raise MediaBuildBusinessError(
            f"field meaning exceeds {MAX_MEDIA_POOL_FIELD_TOKEN_CHARS} characters"
        )
    alias = _FIELD_ALIASES.get(meaning.casefold())
    if alias in _FIXED_MEDIA_FIELDS:
        return alias
    available = tuple(available_fields)
    if not available or not all(isinstance(item, str) and item for item in available):
        raise MediaBuildBusinessError(
            "Media Pool field discovery returned no usable exact-case fields",
            code="MEDIA_BUILD_FIELD_DISCOVERY_INVALID",
        )
    if len(set(available)) != len(available):
        raise MediaBuildBusinessError(
            "Media Pool field discovery returned duplicate fields",
            code="MEDIA_BUILD_FIELD_DISCOVERY_INVALID",
        )
    if alias is not None and alias in available:
        return alias
    casefold_matches = [item for item in available if item.casefold() == meaning.casefold()]
    if len(casefold_matches) == 1:
        return casefold_matches[0]
    normalized = _normalize_token(meaning)
    normalized_matches = [item for item in available if _normalize_token(item) == normalized]
    if len(normalized_matches) == 1:
        return normalized_matches[0]
    suffix_matches = [
        item
        for item in available
        if _normalize_token(item.rsplit("/", 1)[-1]) == normalized
    ]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    candidates = casefold_matches or normalized_matches or suffix_matches
    raise MediaBuildBusinessError(
        "Media Pool field meaning must resolve to one live exact-case field; "
        f"meaning={meaning!r}, candidate_count={len(candidates)}",
        code="MEDIA_BUILD_FIELD_AMBIGUOUS",
    )


def _validate_exact_audio_file(value: Any, *, field: str) -> str:
    raw = _bounded_text(value, field=field)
    try:
        localized = localize_waapi_host_path(raw)
    except HostPathError as exc:
        if exc.error_code == "INVALID_HOST_PATH":
            message = f"{field} must be a safe absolute host path"
        else:
            message = f"{field} cannot be localized on this host"
        raise MediaBuildBusinessError(message) from exc
    path = Path(localized)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise MediaBuildBusinessError(f"{field} must name an existing audio file") from exc
    if metadata_is_link_or_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise MediaBuildBusinessError(
            f"{field} must name a non-symlink regular audio file"
        )
    return str(path)


def _weight(value: Any, *, field: str) -> float:
    result = _finite_number(value, field=field)
    if not 0 <= result <= 1:
        raise MediaBuildBusinessError(f"{field} must be from 0 through 1")
    return result


def media_pool_requested_field_meanings(plan: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the deduplicated live-field concepts needed by one business plan."""

    meanings: list[str] = []
    for collection in ("text_filters", "number_filters"):
        for row in plan.get(collection, ()):
            if isinstance(row, Sequence) and not isinstance(row, (str, bytes)) and row:
                meanings.append(str(row[0]))
    meanings.extend(str(value) for value in plan.get("return_field_meanings", ()))
    for row in plan.get("sort_rules", ()):
        if isinstance(row, Sequence) and not isinstance(row, (str, bytes)) and row:
            meanings.append(str(row[0]))
    if plan.get("exact_name_contains") is not None:
        meanings.append("filename")
    return tuple(dict.fromkeys(meanings))


def validate_media_pool_business_plan(plan: Mapping[str, Any]) -> None:
    """Reject every host-independent Media Pool input defect before connection."""

    requested = media_pool_requested_field_meanings(plan)
    synthetic_fields = tuple(
        dict.fromkeys(
            (
                *_FIXED_MEDIA_FIELDS,
                *_FIELD_ALIASES.values(),
                *requested,
            )
        )
    )
    _materialize_media_pool("2025.1", plan, synthetic_fields)


def materialize_media_build_business_request(
    operation: str,
    version: str,
    plan: Mapping[str, Any],
    *,
    available_media_fields: Sequence[str] = (),
) -> dict[str, Any]:
    """Compile one high-level media/build read into one exact native request."""

    media_build_business_contract_data(operation, version)
    if operation in {PEAKS_REGION_URI, PEAKS_TRIMMED_URI}:
        return _materialize_peaks(operation, version, plan)
    if operation == SOUNDBANK_GET_INCLUSIONS_URI:
        if set(plan) != {"soundbank_id"}:
            raise MediaBuildBusinessError(
                "SoundBank inclusion read accepts only soundbank_id"
            )
        soundbank_id = _canonical_guid(plan.get("soundbank_id"), field="soundbank_id")
        return {
            "contract": MEDIA_BUILD_CALL_CONTRACT,
            "version": version,
            "api": operation,
            "args": {"soundbank": soundbank_id},
            "options": {},
            "business_request": {"soundbank_id": soundbank_id},
            "result_plan": {"kind": "soundbank_inclusions"},
        }
    if operation == MEDIA_POOL_GET_URI:
        return _materialize_media_pool(version, plan, available_media_fields)
    raise MediaBuildBusinessError("unsupported media/build business operation")


def _materialize_peaks(
    operation: str,
    version: str,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    required = {"audio_source_id", "peak_pair_count"}
    allowed = required | {"channel_mode"}
    if operation == PEAKS_REGION_URI:
        required |= {"start_seconds", "end_seconds"}
        allowed |= {"start_seconds", "end_seconds"}
    if not required <= set(plan):
        raise MediaBuildBusinessError(
            f"peak read fields do not match the closed shape; required={sorted(required)}"
        )
    unknown = set(plan) - allowed
    if unknown:
        raise MediaBuildBusinessError(f"peak read contains unknown fields: {sorted(unknown)}")
    source_id = _canonical_guid(plan.get("audio_source_id"), field="audio_source_id")
    count = plan.get("peak_pair_count")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not 1 <= count <= MAX_PEAK_PAIR_COUNT
    ):
        raise MediaBuildBusinessError(
            f"peak_pair_count must be an integer from 1 through {MAX_PEAK_PAIR_COUNT}"
        )
    channel_mode = plan.get("channel_mode", "per-channel")
    if channel_mode not in {"per-channel", "cross-channel"}:
        raise MediaBuildBusinessError(
            "channel_mode must be per-channel or cross-channel"
        )
    args: dict[str, Any] = {
        "object": source_id,
        "numPeaks": count,
        "getCrossChannelPeaks": channel_mode == "cross-channel",
    }
    business_request: dict[str, Any] = {
        "audio_source_id": source_id,
        "peak_pair_count": count,
        "channel_mode": channel_mode,
    }
    if operation == PEAKS_REGION_URI:
        start = _finite_number(plan.get("start_seconds"), field="start_seconds")
        end = _finite_number(plan.get("end_seconds"), field="end_seconds")
        if start < 0 or end <= start:
            raise MediaBuildBusinessError(
                "peak region requires 0 <= start_seconds < end_seconds"
            )
        args.update({"timeFrom": start, "timeTo": end})
        business_request.update({"start_seconds": start, "end_seconds": end})
    return {
        "contract": MEDIA_BUILD_CALL_CONTRACT,
        "version": version,
        "api": operation,
        "args": args,
        "options": {},
        "business_request": business_request,
        "result_plan": {
            "kind": "decoded_peaks",
            "requested_peak_pair_count": count,
            "channel_mode": channel_mode,
        },
    }


def _triples(value: Any, *, field: str) -> list[tuple[Any, Any, Any]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MediaBuildBusinessError(f"{field} must be a repeated three-value list")
    result: list[tuple[Any, Any, Any]] = []
    for index, row in enumerate(value):
        if (
            not isinstance(row, Sequence)
            or isinstance(row, (str, bytes))
            or len(row) != 3
        ):
            raise MediaBuildBusinessError(f"{field}[{index}] must have three values")
        result.append((row[0], row[1], row[2]))
    return result


def _pairs(value: Any, *, field: str) -> list[tuple[Any, Any]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MediaBuildBusinessError(f"{field} must be a repeated two-value list")
    result: list[tuple[Any, Any]] = []
    for index, row in enumerate(value):
        if (
            not isinstance(row, Sequence)
            or isinstance(row, (str, bytes))
            or len(row) != 2
        ):
            raise MediaBuildBusinessError(f"{field}[{index}] must have two values")
        result.append((row[0], row[1]))
    return result


def _materialize_media_pool(
    version: str,
    plan: Mapping[str, Any],
    available_fields: Sequence[str],
) -> dict[str, Any]:
    allowed = {
        "max_results",
        "database_scopes",
        "database_ids",
        "search_text",
        "text_filters",
        "number_filters",
        "audio_descriptions",
        "weighted_audio_descriptions",
        "audio_similarity_files",
        "weighted_audio_similarity_files",
        "return_field_meanings",
        "exact_name_contains",
        "final_limit",
        "sort_rules",
    }
    unknown = set(plan) - allowed
    if unknown:
        raise MediaBuildBusinessError(
            f"Media Pool plan contains unknown fields: {sorted(unknown)}"
        )
    max_results = plan.get("max_results")
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= MAX_MEDIA_POOL_RESULTS
    ):
        raise MediaBuildBusinessError(
            f"max_results must be an integer from 1 through {MAX_MEDIA_POOL_RESULTS}"
        )
    scopes = tuple(plan.get("database_scopes", ()))
    databases: list[str] = []
    for scope in scopes:
        try:
            databases.append(_DATABASE_SCOPES[str(scope).casefold()])
        except KeyError as exc:
            raise MediaBuildBusinessError(
                "database_scope must identify Project Originals"
            ) from exc
    databases.extend(
        _canonical_guid(value, field="database_id")
        for value in plan.get("database_ids", ())
    )
    if len(databases) > MAX_MEDIA_POOL_DATABASES or len(set(databases)) != len(databases):
        raise MediaBuildBusinessError(
            "Media Pool databases must be unique and within the eight-database limit"
        )
    field_bindings: dict[str, str] = {}

    def bind(meaning: Any) -> str:
        text = _bounded_text(meaning, field="field meaning")
        exact = field_bindings.get(text)
        if exact is None:
            exact = _resolve_media_field(text, available_fields)
            field_bindings[text] = exact
        return exact

    filters: list[dict[str, Any]] = []
    for meaning, operator, value in _triples(
        plan.get("text_filters"), field="text_filters"
    ):
        operator = str(operator)
        if operator not in _TEXT_OPERATORS:
            raise MediaBuildBusinessError(
                f"text filter operator must be one of {sorted(_TEXT_OPERATORS)}"
            )
        filters.append(
            {
                "type": "field",
                "field": bind(meaning),
                "operator": operator,
                "value": _bounded_text(value, field="text filter value"),
            }
        )
    for meaning, operator, value in _triples(
        plan.get("number_filters"), field="number_filters"
    ):
        operator = str(operator)
        if operator not in _NUMBER_OPERATORS:
            raise MediaBuildBusinessError(
                f"number filter operator must be one of {sorted(_NUMBER_OPERATORS)}"
            )
        filters.append(
            {
                "type": "field",
                "field": bind(meaning),
                "operator": operator,
                "value": _finite_number(value, field="number filter value"),
            }
        )
    for value in plan.get("audio_descriptions", ()):
        filters.append(
            {
                "type": "audioDescription",
                "value": _bounded_text(value, field="audio description"),
            }
        )
    for value, raw_weight in _pairs(
        plan.get("weighted_audio_descriptions"),
        field="weighted_audio_descriptions",
    ):
        filters.append(
            {
                "type": "audioDescription",
                "value": _bounded_text(value, field="audio description"),
                "weight": _weight(raw_weight, field="audio description weight"),
            }
        )
    for value in plan.get("audio_similarity_files", ()):
        filters.append(
            {
                "type": "audioSimilarity",
                "value": _validate_exact_audio_file(
                    value,
                    field="audio similarity file",
                ),
            }
        )
    for value, raw_weight in _pairs(
        plan.get("weighted_audio_similarity_files"),
        field="weighted_audio_similarity_files",
    ):
        filters.append(
            {
                "type": "audioSimilarity",
                "value": _validate_exact_audio_file(value, field="audio similarity file"),
                "weight": _weight(raw_weight, field="audio similarity weight"),
            }
        )
    exact_name = plan.get("exact_name_contains")
    final_limit = plan.get("final_limit")
    if exact_name is not None:
        exact_name = _bounded_text(exact_name, field="exact_name_contains")
        if len(exact_name) > MAX_MEDIA_POOL_SEARCH_TEXT_CHARS:
            raise MediaBuildBusinessError(
                "exact_name_contains exceeds 1024 characters"
            )
        filename = bind("filename")
        filename_contains = [
            row
            for row in filters
            if row.get("type") == "field"
            and row.get("field") == filename
            and row.get("operator") == "contains"
        ]
        if len(filename_contains) > 1 or (
            filename_contains
            and filename_contains[0].get("value") != exact_name
        ):
            raise MediaBuildBusinessError(
                "exact_name_contains conflicts with the server Filename candidate filter"
            )
        if not filename_contains:
            filters.append(
                {
                    "type": "field",
                    "field": filename,
                    "operator": "contains",
                    "value": exact_name,
                }
            )
        if (
            isinstance(final_limit, bool)
            or not isinstance(final_limit, int)
            or not 1 <= final_limit <= max_results
        ):
            raise MediaBuildBusinessError(
                "exact_name_contains requires final_limit from 1 through max_results"
            )
    elif final_limit is not None:
        raise MediaBuildBusinessError(
            "final_limit is accepted only with exact_name_contains"
        )
    if len(filters) > MAX_MEDIA_POOL_FILTERS:
        raise MediaBuildBusinessError(
            f"Media Pool accepts at most {MAX_MEDIA_POOL_FILTERS} business filters"
        )
    requested_meanings = tuple(
        dict.fromkeys(str(value) for value in plan.get("return_field_meanings", ()))
    )
    sort_rows = _pairs(plan.get("sort_rules"), field="sort_rules")
    sort_bindings: list[dict[str, str]] = []
    for meaning, direction in sort_rows:
        direction = str(direction)
        if direction not in MEDIA_POOL_SORT_DIRECTIONS:
            raise MediaBuildBusinessError(
                "sort direction must be ascending or descending"
            )
        sort_bindings.append(
            {
                "meaning": str(meaning),
                "field": bind(meaning),
                "direction": direction,
            }
        )
    return_meanings = tuple(
        dict.fromkeys((*requested_meanings, *(row["meaning"] for row in sort_bindings)))
    )
    output_bindings: list[dict[str, str]] = []
    output_keys: set[str] = set()
    for meaning in return_meanings:
        key = _business_key(meaning)
        if key in output_keys:
            raise MediaBuildBusinessError(
                "Media Pool return field meanings collapse to the same business key"
            )
        output_keys.add(key)
        output_bindings.append(
            {"meaning": meaning, "field": bind(meaning), "key": key}
        )
    return_fields = list(
        dict.fromkeys(
            (
                *_FIXED_MEDIA_FIELDS,
                *(row["field"] for row in output_bindings),
                *(row["field"] for row in sort_bindings),
                *(row["field"] for row in filters if row.get("type") == "field"),
            )
        )
    )
    if len(return_fields) > MAX_MEDIA_POOL_RETURN_FIELDS:
        raise MediaBuildBusinessError(
            f"Media Pool projection exceeds {MAX_MEDIA_POOL_RETURN_FIELDS} fields"
        )
    args: dict[str, Any] = {"maxResults": max_results}
    if databases:
        args["databases"] = databases
    if filters:
        args["filters"] = filters
    search_text = plan.get("search_text")
    if search_text is not None:
        search_text = _bounded_text(search_text, field="search_text")
        if len(search_text) > MAX_MEDIA_POOL_SEARCH_TEXT_CHARS:
            raise MediaBuildBusinessError("search_text exceeds 1024 characters")
        args["searchText"] = search_text
    return {
        "contract": MEDIA_BUILD_CALL_CONTRACT,
        "version": version,
        "api": MEDIA_POOL_GET_URI,
        "args": args,
        "options": {"return": return_fields},
        "business_request": {
            "database_scopes": list(scopes),
            "database_ids": [value for value in databases if _GUID_RE.fullmatch(value)],
            "search_text": search_text,
            "filter_count": len(filters),
            "max_results": max_results,
            "return_field_meanings": list(requested_meanings),
            "exact_name_contains": exact_name,
            "final_limit": final_limit,
            "sort_rules": [
                {"field_meaning": row["meaning"], "direction": row["direction"]}
                for row in sort_bindings
            ],
        },
        "result_plan": {
            "kind": "media_pool_rows",
            "candidate_limit": max_results,
            "output_bindings": output_bindings,
            "exact_name_field": field_bindings.get("filename"),
            "exact_name_contains": exact_name,
            "final_limit": final_limit,
            "sort_bindings": sort_bindings,
        },
    }


def normalize_media_build_result(
    prepared: Mapping[str, Any],
    raw_result: Any,
    *,
    identity_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Normalize one reflected result into its bounded business projection."""

    result_plan = prepared.get("result_plan")
    if not isinstance(result_plan, Mapping):
        raise MediaBuildBusinessError(
            "prepared media/build request lacks its result plan",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    kind = result_plan.get("kind")
    if kind == "decoded_peaks":
        return _normalize_peaks_result(raw_result, result_plan)
    if kind == "soundbank_inclusions":
        return _normalize_inclusions_result(raw_result, identity_rows)
    if kind == "media_pool_rows":
        return _normalize_media_pool_result(raw_result, result_plan)
    raise MediaBuildBusinessError(
        "unknown media/build result plan",
        code="MEDIA_BUILD_RESULT_INVALID",
    )


def _whole_number(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MediaBuildBusinessError(
            f"{field} must be an integer result",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    number = int(value)
    if float(value) != number or number < 0:
        raise MediaBuildBusinessError(
            f"{field} must be a nonnegative integer result",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    return number


def _normalize_peaks_result(raw_result: Any, plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_result, Mapping):
        raise MediaBuildBusinessError(
            "peak result must be an object",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    count = _whole_number(raw_result.get("peaksArrayLength"), field="peaksArrayLength")
    requested = int(plan["requested_peak_pair_count"])
    if count > requested:
        raise MediaBuildBusinessError(
            "peak result exceeds the requested pair count",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    channels = _whole_number(raw_result.get("numChannels"), field="numChannels")
    if plan.get("channel_mode") == "cross-channel" and channels != 1:
        raise MediaBuildBusinessError(
            "cross-channel peak result must contain exactly one channel",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    encoded = raw_result.get("peaksBinaryStrings")
    if not isinstance(encoded, list) or len(encoded) != channels:
        raise MediaBuildBusinessError(
            "peak result channel count does not match its binary strings",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    data_size = _whole_number(raw_result.get("peaksDataSize"), field="peaksDataSize")
    maximum = _finite_number(raw_result.get("maxAbsValue"), field="maxAbsValue")
    if maximum <= 0:
        raise MediaBuildBusinessError(
            "peak result maxAbsValue must be positive",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    channel_rows: list[dict[str, Any]] = []
    for index, value in enumerate(encoded):
        if not isinstance(value, str):
            raise MediaBuildBusinessError(
                "peak binary strings must be base64 text",
                code="MEDIA_BUILD_RESULT_INVALID",
            )
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise MediaBuildBusinessError(
                "peak binary string is not strict base64",
                code="MEDIA_BUILD_RESULT_INVALID",
            ) from exc
        expected_bytes = count * 2 * 2
        if data_size != expected_bytes or len(decoded) != expected_bytes:
            raise MediaBuildBusinessError(
                "peak binary byte count does not match peaksDataSize and peaksArrayLength",
                code="MEDIA_BUILD_RESULT_INVALID",
            )
        values = struct.unpack(f"<{count * 2}h", decoded)
        pairs = [
            [values[offset] / maximum, values[offset + 1] / maximum]
            for offset in range(0, len(values), 2)
        ]
        channel_rows.append({"channel_index": index, "pairs_normalized": pairs})
    result: dict[str, Any] = {
        "contract": MEDIA_BUILD_RESULT_CONTRACT,
        "kind": "decoded_peaks",
        "channel_mode": plan["channel_mode"],
        "channel_count": channels,
        "peak_pair_count": count,
        "requested_peak_pair_count": requested,
        "complete_requested_count": count == requested,
        "normalization_divisor": maximum,
        "channels": channel_rows,
    }
    channel_config = raw_result.get("channelConfig")
    if channel_config is not None:
        if not isinstance(channel_config, str):
            raise MediaBuildBusinessError(
                "peak channelConfig must be text",
                code="MEDIA_BUILD_RESULT_INVALID",
            )
        result["channel_config"] = channel_config
    return result


def _normalize_inclusions_result(
    raw_result: Any,
    identity_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(raw_result, Mapping) or not isinstance(raw_result.get("inclusions"), list):
        raise MediaBuildBusinessError(
            "SoundBank inclusion result must contain an inclusions array",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    inclusions = raw_result["inclusions"]
    if len(inclusions) > MAX_SOUNDBANK_INCLUSIONS:
        raise MediaBuildBusinessError(
            f"SoundBank inclusion result exceeds {MAX_SOUNDBANK_INCLUSIONS} rows",
            code="MEDIA_BUILD_RESULT_LIMIT_EXCEEDED",
        )
    identities: dict[str, Mapping[str, Any]] = {}
    for row in identity_rows:
        try:
            identity = normalize_live_object_identity(row)
        except ValueError as exc:
            raise MediaBuildBusinessError(
                "SoundBank inclusion identity row is malformed",
                code="MEDIA_BUILD_RESULT_INVALID",
            ) from exc
        object_id = identity.object_id
        if object_id in identities:
            raise MediaBuildBusinessError(
                "SoundBank inclusion identity read returned a duplicate",
                code="MEDIA_BUILD_RESULT_INVALID",
            )
        identities[object_id] = {
            **row,
            "id": identity.object_id,
            "name": identity.name,
            "type": identity.object_type,
            "path": identity.path,
        }
    normalized: list[dict[str, Any]] = []
    expected_ids: set[str] = set()
    for index, row in enumerate(inclusions):
        if not isinstance(row, Mapping):
            raise MediaBuildBusinessError(
                f"SoundBank inclusion row {index} is malformed",
                code="MEDIA_BUILD_RESULT_INVALID",
            )
        object_id = _canonical_guid(row.get("object"), field="inclusion object")
        filters = row.get("filter")
        if (
            not isinstance(filters, list)
            or not filters
            or not all(item in {"events", "structures", "media"} for item in filters)
            or len(set(filters)) != len(filters)
        ):
            raise MediaBuildBusinessError(
                f"SoundBank inclusion row {index} has invalid filters",
                code="MEDIA_BUILD_RESULT_INVALID",
            )
        expected_ids.add(object_id)
        identity = identities.get(object_id)
        if identity is None:
            raise MediaBuildBusinessError(
                "SoundBank inclusion identity read is incomplete",
                code="MEDIA_BUILD_RESULT_INVALID",
            )
        normalized.append(
            {
                "object_id": object_id,
                "name": identity["name"],
                "type": identity["type"],
                "path": identity["path"],
                "includes": sorted(filters),
            }
        )
    if set(identities) != expected_ids:
        raise MediaBuildBusinessError(
            "SoundBank inclusion identity read returned extra objects",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    normalized.sort(key=lambda row: (str(row["path"]).casefold(), row["object_id"]))
    return {
        "contract": MEDIA_BUILD_RESULT_CONTRACT,
        "kind": "soundbank_inclusions",
        "count": len(normalized),
        "inclusions": normalized,
    }


def _sort_value(value: Any) -> tuple[int, Any]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, float(value))
    if isinstance(value, str):
        return (1, value.casefold())
    return (2, repr(value))


def _normalize_media_pool_result(raw_result: Any, plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_result, Mapping) or set(raw_result) != {"return"}:
        raise MediaBuildBusinessError(
            "Media Pool result must contain exactly one return array",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    rows = raw_result.get("return")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise MediaBuildBusinessError(
            "Media Pool return rows must be objects",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    candidate_limit = int(plan["candidate_limit"])
    if len(rows) > candidate_limit:
        raise MediaBuildBusinessError(
            "Media Pool returned more rows than max_results",
            code="MEDIA_BUILD_RESULT_INVALID",
        )
    exact_name = plan.get("exact_name_contains")
    complete = True
    filtered = list(rows)
    if exact_name is not None:
        if len(rows) >= candidate_limit:
            complete = False
            filtered = []
        else:
            field = plan.get("exact_name_field")
            if not isinstance(field, str):
                raise MediaBuildBusinessError(
                    "Media Pool exact-name result plan lacks Filename binding",
                    code="MEDIA_BUILD_RESULT_INVALID",
                )
            for row in rows:
                if not isinstance(row.get(field), str):
                    raise MediaBuildBusinessError(
                        "Media Pool exact-name candidate lacks Filename text",
                        code="MEDIA_BUILD_RESULT_INVALID",
                    )
            filtered = [row for row in rows if exact_name in row[field]]
    for rule in reversed(tuple(plan.get("sort_bindings", ()))):
        field = rule["field"]
        reverse = rule["direction"] == "descending"
        present = [row for row in filtered if row.get(field) is not None]
        missing = [row for row in filtered if row.get(field) is None]
        present.sort(key=lambda row: _sort_value(row.get(field)), reverse=reverse)
        filtered = [*present, *missing]
    final_limit = plan.get("final_limit")
    if isinstance(final_limit, int):
        filtered = filtered[:final_limit]
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(filtered):
        fixed: dict[str, Any] = {}
        for native, business in (("Path", "path"), ("FileId", "file_id")):
            value = row.get(native)
            if not isinstance(value, str) or not value:
                raise MediaBuildBusinessError(
                    f"Media Pool row {index} lacks {native}",
                    code="MEDIA_BUILD_RESULT_INVALID",
                )
            fixed[business] = value
        if "Db" in row:
            database = row.get("Db")
            if (
                not isinstance(database, Mapping)
                or set(database) != {"id", "name"}
                or not isinstance(database.get("id"), str)
                or not _GUID_RE.fullmatch(database["id"])
                or not isinstance(database.get("name"), str)
                or not database["name"]
            ):
                raise MediaBuildBusinessError(
                    f"Media Pool row {index} has an invalid Db value",
                    code="MEDIA_BUILD_RESULT_INVALID",
                )
            fixed["database_id"] = database["id"].upper()
            fixed["database_name"] = database["name"]
        values: dict[str, Any] = {}
        for binding in plan.get("output_bindings", ()):
            if binding["field"] not in row:
                raise MediaBuildBusinessError(
                    f"Media Pool row {index} lacks requested field {binding['meaning']!r}",
                    code="MEDIA_BUILD_RESULT_INVALID",
                )
            values[binding["key"]] = row[binding["field"]]
        projected.append({**fixed, "values": values})
    return {
        "contract": MEDIA_BUILD_RESULT_CONTRACT,
        "kind": "media_pool_rows",
        "complete": complete,
        "candidate_count": len(rows),
        "returned_count": len(projected),
        "candidate_limit": candidate_limit,
        "incomplete_reason": (
            "candidate_limit_reached_before_exact_case_post_filter"
            if not complete
            else None
        ),
        "items": projected,
    }


__all__ = [
    "MAX_MEDIA_POOL_RESULTS",
    "MAX_PEAK_PAIR_COUNT",
    "MAX_SOUNDBANK_INCLUSIONS",
    "MEDIA_BUILD_CALL_CONTRACT",
    "MEDIA_BUILD_RESULT_CONTRACT",
    "MediaBuildBusinessError",
    "materialize_media_build_business_request",
    "media_pool_requested_field_meanings",
    "normalize_media_build_result",
    "validate_media_pool_business_plan",
]
