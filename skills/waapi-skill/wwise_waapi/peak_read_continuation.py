"""Bounded projections of one retained peak observation."""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from .canonical import canonical_json_bytes
from .media_pool_continuation import MediaPoolContinuationError
from .wal_peak_observations import NativePageLocator, parse_native_page


class PeakContinuationError(ValueError):
    code = "PEAK_CONTINUATION_CHANGED"


class PeakProjectionLimitError(PeakContinuationError):
    code = "PEAK_PROJECTION_LIMIT_EXCEEDED"


def parse_peak_page(token: str) -> NativePageLocator:
    try:
        return parse_native_page(token, kind="pk2", maximum_offset=256 * 1024)
    except MediaPoolContinuationError as exc:
        raise PeakContinuationError(str(exc)) from exc


def peak_page_argv(request: Mapping[str, Any], token: str) -> list[str]:
    business = request["business_request"]
    argv = ["core-call", request["api"], "--audio-source-id", business["audio_source_id"],
        "--peak-pair-count", str(business["peak_pair_count"]), "--channel-mode", business["channel_mode"]]
    if "start_seconds" in business:
        argv += ["--start-seconds", str(business["start_seconds"]), "--end-seconds", str(business["end_seconds"])]
    return [*argv, "--peak-page", token]


def _encoded_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))


def _raw_observation_page(normalized: Mapping[str, Any], *, offset: int, observed_at: int,
                          result_hash: str, next_command: Callable[[int], Mapping[str, Any]] | None) -> dict[str, Any]:
    from .metadata_detail import detail_entries
    raw = normalized["native_result"]
    # The store uses canonical JSON ordering. Match that order on the first page.
    entries = detail_entries(raw if offset else json.loads(canonical_json_bytes(raw)))
    if offset >= len(entries):
        raise PeakContinuationError("Peak page position is outside this native observation")
    header = {key: raw[key] for key in ("numChannels", "peaksArrayLength", "peaksDataSize", "maxAbsValue") if key in raw}
    if isinstance(raw.get("channelConfig"), str) and len(raw["channelConfig"]) <= 1024:
        header["channelConfig"] = raw["channelConfig"]
    end = min(len(entries), offset + 64)
    while True:
        complete = end == len(entries)
        result = {**{key: value for key, value in normalized.items() if key != "native_result"},
            "native_header": header, "native_result_fragments": entries[offset:end],
            "observation_complete": complete,
            "page": {"offset": offset, "next_offset": end, "total_positions": len(entries),
                "position_unit": "lossless native JSON entries with exact pointer/string offsets",
                "native_read": "retained_historical_observation",
                "observed_at_unix_seconds": observed_at,
                "native_result_sha256": result_hash, "expires_at": observed_at + 900,
                "mutation_authority": False}}
        if not complete:
            if next_command is not None:
                result["next_command"] = dict(next_command(end))
            else:
                result["page"]["continuation_unavailable_reason"] = "host_session_identity_unavailable"
        if _encoded_size(result) <= 20 * 1024:
            return result
        if end <= offset + 1:
            raise PeakProjectionLimitError("One raw peak entry exceeds the bounded projection; retain native evidence and refine the read")
        end = offset + max(1, (end - offset) // 2)


def finish_peak_page(normalized: dict[str, Any], *, offset: int, observed_at: int, result_hash: str,
                     next_command: Callable[[int], Mapping[str, Any]] | None) -> dict[str, Any]:
    if not offset and _encoded_size(normalized) <= 12 * 1024:
        return normalized
    if normalized.get("kind") != "decoded_peaks":
        return _raw_observation_page(normalized, offset=offset, observed_at=observed_at,
            result_hash=result_hash, next_command=next_command)
    count, channels = normalized["peak_pair_count"], normalized["channel_count"]
    stride = max(count, 1)  # Empty channels remain explicit rows, not lost positions.
    pair_positions = stride * channels
    header = {key: value for key, value in normalized.items() if key != "channels"}
    header_entries = []
    channel_config = header.get("channel_config")
    if isinstance(channel_config, str) and len(channel_config.encode("utf-8")) > 4096:
        from .metadata_detail import detail_entries
        header_entries = detail_entries({"channel_config": header.pop("channel_config")})
        header["header_projection"] = {"channel_config": {"total_characters": len(channel_config),
            "preview": channel_config[:128], "complete": False, "fragment_pointer": "/channel_config"}}
    total = pair_positions + len(header_entries)
    if not total:
        raise PeakProjectionLimitError("Peak header exceeds the bounded projection; retain native evidence and refine the read")
    if offset >= total:
        raise PeakContinuationError("Peak page position is outside this native observation")
    end = min(total, offset + 256)
    while True:
        fragments = []
        position = offset
        while position < min(end, pair_positions):
            channel_index, pair_offset = divmod(position, stride)
            stop = min(end, (channel_index + 1) * stride)
            pairs = normalized["channels"][channel_index]["pairs_normalized"]
            fragments.append({"channel_index": channel_index, "pair_offset": pair_offset if count else 0,
                "pairs_normalized": pairs[pair_offset:pair_offset + stop - position] if count else []})
            position = stop
        complete = end == total
        result = {**header, "channels": fragments, "projection_complete": complete,
            **({"header_fragments": header_entries[max(0, offset - pair_positions):max(0, end - pair_positions)]}
               if header_entries else {}),
            "page": {"offset": offset, "next_offset": end, "total_positions": total,
                "position_unit": "channel-major peak pairs; empty channel occupies one position; then lossless header entries",
                "native_read": "retained_historical_observation",
                "observed_at_unix_seconds": observed_at,
                "native_result_sha256": result_hash, "expires_at": observed_at + 900,
                "mutation_authority": False}}
        if not complete:
            if next_command is not None:
                result["next_command"] = dict(next_command(end))
            else:
                result["page"]["continuation_unavailable_reason"] = "host_session_identity_unavailable"
        if _encoded_size(result) <= 20 * 1024:
            return result
        if end <= offset + 1:
            raise PeakProjectionLimitError("Peak header exceeds the bounded projection; retain native evidence and refine the read")
        end = offset + max(1, (end - offset) // 2)
