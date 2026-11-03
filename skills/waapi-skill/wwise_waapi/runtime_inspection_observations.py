"""Immutable bounded runtime observations; never instantaneous resource authority.

The existing read-plan store owns secure files, digest validation, expiry and
capacity. A retained observation makes pages lossless without querying a later
capture. Pipeline selectors bind to this observation, not a bare native ID.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .canonical import canonical_json_bytes, canonical_sha256
from .media_pool_continuation import MediaPoolQueryStore, MediaPoolContinuationError


def validate_observation(plan: Mapping[str, Any]) -> None:
    if (set(plan) != {"operation", "request", "result", "page_size", "pipeline_bindings"}
            or not isinstance(plan["operation"], str)
            or not isinstance(plan["request"], dict) or not isinstance(plan["result"], dict)
            or type(plan["page_size"]) is not int or not 1 <= plan["page_size"] <= 1000
            or not isinstance(plan["pipeline_bindings"], dict)):
        raise MediaPoolContinuationError("Runtime observation has an invalid closed shape")


class RuntimeInspectionObservationStore(MediaPoolQueryStore):
    DIRECTORY = "runtime-inspection-observations-v1"
    CONTRACT = "waapi-skill.runtime-inspection-observation/v1"
    PREFIX = "rto1-"
    _HANDLE = re.compile(r"^rto1-[0-9a-f]{32}$")
    MAX_RECORD_BYTES = 2 * 1024 * 1024
    validate_plan = staticmethod(validate_observation)


_PIPELINE_HANDLE = re.compile(r"^rph1-([0-9a-f]{32})-([0-9a-f]{16})$")


def validate_pipeline_handle(handle: str) -> None:
    if not isinstance(handle, str) or _PIPELINE_HANDLE.fullmatch(handle) is None:
        raise MediaPoolContinuationError("Profiler instance handle must be copied exactly from a Gateway Profiler result")


def pipeline_key(kind: str, native_id: int) -> str:
    return canonical_sha256([kind, native_id])[:16]


def observation_pipeline_handle(handle: str, *, kind: str, native_id: int) -> str:
    return f"rph1-{handle[5:]}-{pipeline_key(kind, native_id)}"


def resolve_pipeline(store: RuntimeInspectionObservationStore, handle: str, *, kind: str,
                     configuration: Mapping[str, Any]) -> dict[str, Any]:
    validate_pipeline_handle(handle)
    match = _PIPELINE_HANDLE.fullmatch(handle)
    if match is None:
        raise MediaPoolContinuationError(f"{kind}_instance_handle must be copied exactly from a Gateway Profiler result")
    record = store.resolve("rto1-" + match[1])
    if record["context"].get("configuration") != configuration:
        raise MediaPoolContinuationError("Profiler observation configuration changed; refresh the original read")
    binding = record["plan"]["pipeline_bindings"].get(match[2])
    if not isinstance(binding, dict) or binding.get("kind") != kind:
        raise MediaPoolContinuationError("Profiler handle was not issued for this instance kind")
    return {**binding, "context": record["context"], "handle": handle}


def observation_page(record: Mapping[str, Any], *, token: str | None = None) -> dict[str, Any]:
    """Rows preserve native order within pages, delivered newest range first."""
    plan = record["plan"]
    result = plan["result"]
    field = next(field for field in ("return", "items", "meters") if field in result)
    rows = result[field]
    digest = canonical_sha256([record["handle"], result])
    offset = 0
    fragment_offset = None
    if token is not None:
        try:
            prefix, raw_offset, raw_fragment, expected = token.split(".")
            offset = int(raw_offset)
            fragment_offset = None if raw_fragment == "rows" else int(raw_fragment)
            valid = (prefix == "rtp1" and str(offset) == raw_offset and 0 <= offset < len(rows)
                     and expected == digest and (fragment_offset is None or 0 <= fragment_offset < 2 * 1024 * 1024))
        except (AttributeError, ValueError):
            valid = False
        if not valid:
            raise MediaPoolContinuationError("Runtime observation page is malformed or does not match this exact observation")
    end = min(len(rows), offset + plan["page_size"])
    # Decorate before byte selection/fragmentation so a large retained row has
    # the same exact public value through every delivery representation.
    rows = [dict(row) for row in rows]
    for binding in plan["pipeline_bindings"].values():
        for index in binding["row_indexes"]:
            rows[index][binding["kind"] + "_instance_handle"] = observation_pipeline_handle(
                record["handle"], kind=binding["kind"], native_id=binding["native_id"])
    selected = rows[len(rows) - end:len(rows) - offset]
    while len(selected) > 1 and len(canonical_json_bytes(selected)) > 4096:
        selected = selected[1:]
        end -= 1
    fragment = None
    if selected and (fragment_offset is not None or len(canonical_json_bytes(selected)) > 4096):
        # Document fragments also handle enormous keys and deeply nested rows;
        # pointer paths cannot expand or become ambiguous.
        document = canonical_json_bytes(rows[len(rows) - offset - 1]).decode("utf-8")
        start = fragment_offset or 0
        if start >= len(document):
            raise MediaPoolContinuationError("Runtime observation fragment is outside the retained row")
        stop = min(len(document), start + 1024)
        fragment = {"row_index": len(rows) - offset - 1, "offset_characters": start,
                    "total_characters": len(document), "value": document[start:stop],
                    "reconstruction": "Concatenate value strings in character-offset order, then parse the single JSON row"}
        selected = []
        end = offset + 1 if stop == len(document) else offset
        next_fragment = "rows" if stop == len(document) else str(stop)
    else:
        next_fragment = "rows"
    complete = end == len(rows)
    return {**{key: value for key, value in result.items() if key not in {field, "returned_count", "truncated"}},
        field: selected, **({"row_fragment": fragment} if fragment is not None else {}),
        "returned_count": len(selected), "total_count": len(rows), "truncated": not complete,
        "complete": complete, "observation": "retained_profiler_capture_snapshot" if plan["operation"].startswith("ak.wwise.core.profiler.") else "retained_log_snapshot",
        "instantaneous_native_resource_authority": False,
        "snapshot_sha256": canonical_sha256(result), "expires_at": record["expires_at"],
        "page": {"offset_from_end": offset, "next_offset_from_end": end, "order": "newest_range_first_native_order_within_range"},
        "next_page": None if complete else f"rtp1.{end}.{next_fragment}.{digest}"}
