"""Bounded projections of one exact peak observation, verified on each reread.

The native APIs have no offset. A page repeats the same bounded native request
and verifies the entire observation before exposing the next channel fragment.
These locators carry no mutation authority or native request fields.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
import time
from typing import Any, Callable, Mapping

from .canonical import canonical_sha256


class PeakContinuationError(ValueError):
    code = "PEAK_CONTINUATION_CHANGED"


class PeakProjectionLimitError(PeakContinuationError):
    code = "PEAK_PROJECTION_LIMIT_EXCEEDED"


@dataclass(frozen=True, slots=True)
class PeakPage:
    issued: int
    offset: int
    query_hash: str
    context_hash: str
    result_hash: str


def parse_peak_page(token: str) -> PeakPage:
    try:
        if not isinstance(token, str) or len(token) > 512:
            raise ValueError("token bound")
        kind, stamp, position, query, context, result, digest = token.split(".")
        issued, offset = int(stamp), int(position)
        valid = (kind == "pk1" and str(issued) == stamp and str(offset) == position
            and 0 < offset < 256 * 1024 and issued <= time.time() <= issued + 900
            and all(len(value) == 64 and all(char in "0123456789abcdef" for char in value)
                for value in (query, context, result, digest))
            and hmac.compare_digest(canonical_sha256(token.rsplit(".", 1)[0]), digest))
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise PeakContinuationError("Peak page is malformed or expired; start the bounded read again")
    return PeakPage(issued, offset, query, context, result)


def prepare_peak_page(request: Mapping[str, Any], *, token: str | None,
                      context: Mapping[str, Any]) -> PeakPage:
    query_hash = canonical_sha256({key: request[key] for key in ("api", "version", "args", "options", "result_plan")})
    context_hash = canonical_sha256(context)
    if token is None:
        return PeakPage(int(time.time()), 0, query_hash, context_hash, "")
    page = parse_peak_page(token)
    if not hmac.compare_digest(page.query_hash, query_hash) or not hmac.compare_digest(page.context_hash, context_hash):
        raise PeakContinuationError("Peak query, configuration, project or host session changed; start the read again")
    return page


def peak_page_argv(request: Mapping[str, Any], token: str) -> list[str]:
    business = request["business_request"]
    argv = ["core-call", request["api"], "--audio-source-id", business["audio_source_id"],
        "--peak-pair-count", str(business["peak_pair_count"]), "--channel-mode", business["channel_mode"]]
    if "start_seconds" in business:
        argv += ["--start-seconds", str(business["start_seconds"]), "--end-seconds", str(business["end_seconds"])]
    return [*argv, "--peak-page", token]


def _encoded_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))


def _raw_observation_page(page: PeakPage, *, raw: Mapping[str, Any], normalized: Mapping[str, Any],
                          result_hash: str, context_available: bool,
                          next_command: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    from .metadata_detail import detail_entries
    entries = detail_entries(raw)
    if page.offset >= len(entries):
        raise PeakContinuationError("Peak page position is outside this native observation")
    header = {key: raw[key] for key in ("numChannels", "peaksArrayLength", "peaksDataSize", "maxAbsValue") if key in raw}
    if isinstance(raw.get("channelConfig"), str) and len(raw["channelConfig"]) <= 1024:
        header["channelConfig"] = raw["channelConfig"]
    end = min(len(entries), page.offset + 64)
    while True:
        complete = end == len(entries)
        result = {**{key: value for key, value in normalized.items() if key != "native_result"},
            "native_header": header, "native_result_fragments": entries[page.offset:end],
            "observation_complete": complete,
            "page": {"offset": page.offset, "next_offset": end, "total_positions": len(entries),
                "position_unit": "lossless native JSON entries with exact pointer/string offsets",
                "native_read": "repeat_same_bounded_read_and_verify_entire_result",
                "native_result_sha256": result_hash, "expires_at": page.issued + 900,
                "mutation_authority": False}}
        if not complete:
            if context_available:
                unsigned = f"pk1.{page.issued}.{end}.{page.query_hash}.{page.context_hash}.{result_hash}"
                result["next_command"] = dict(next_command(unsigned + "." + canonical_sha256(unsigned)))
            else:
                result["page"]["continuation_unavailable_reason"] = "host_session_identity_unavailable"
        if _encoded_size(result) <= 20 * 1024:
            return result
        if end <= page.offset + 1:
            raise PeakProjectionLimitError("One raw peak entry exceeds the bounded projection; retain native evidence and refine the read")
        end = page.offset + max(1, (end - page.offset) // 2)


def finish_peak_page(page: PeakPage, *, raw: Mapping[str, Any], normalized: dict[str, Any],
                     context_available: bool, next_command: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    result_hash = canonical_sha256(raw)
    if page.offset and not hmac.compare_digest(page.result_hash, result_hash):
        raise PeakContinuationError("The complete native peak observation changed; discard the previous projection and start again")
    if not page.offset and _encoded_size(normalized) <= 12 * 1024:
        return normalized
    if normalized.get("kind") != "decoded_peaks":
        return _raw_observation_page(page, raw=raw, normalized=normalized, result_hash=result_hash,
            context_available=context_available, next_command=next_command)
    count, channels = normalized["peak_pair_count"], normalized["channel_count"]
    stride = max(count, 1)  # Empty channels remain explicit rows, not lost positions.
    total = stride * channels
    if not total:
        raise PeakProjectionLimitError("Peak header exceeds the bounded projection; retain native evidence and refine the read")
    if page.offset >= total:
        raise PeakContinuationError("Peak page position is outside this native observation")
    end = min(total, page.offset + 256)
    while True:
        fragments = []
        position = page.offset
        while position < end:
            channel_index, pair_offset = divmod(position, stride)
            stop = min(end, (channel_index + 1) * stride)
            pairs = normalized["channels"][channel_index]["pairs_normalized"]
            fragments.append({"channel_index": channel_index, "pair_offset": pair_offset if count else 0,
                "pairs_normalized": pairs[pair_offset:pair_offset + stop - position] if count else []})
            position = stop
        complete = end == total
        result = {**{key: value for key, value in normalized.items() if key != "channels"},
            "channels": fragments, "projection_complete": complete,
            "page": {"offset": page.offset, "next_offset": end, "total_positions": total,
                "position_unit": "channel-major peak pairs; empty channel occupies one position",
                "native_read": "repeat_same_bounded_read_and_verify_entire_result",
                "native_result_sha256": result_hash, "expires_at": page.issued + 900,
                "mutation_authority": False}}
        if not complete:
            if context_available:
                unsigned = f"pk1.{page.issued}.{end}.{page.query_hash}.{page.context_hash}.{result_hash}"
                result["next_command"] = dict(next_command(unsigned + "." + canonical_sha256(unsigned)))
            else:
                result["page"]["continuation_unavailable_reason"] = "host_session_identity_unavailable"
        if _encoded_size(result) <= 20 * 1024:
            return result
        if end <= page.offset + 1:
            raise PeakProjectionLimitError("Peak header exceeds the bounded projection; retain native evidence and refine the read")
        end = page.offset + max(1, (end - page.offset) // 2)
