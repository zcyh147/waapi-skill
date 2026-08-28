"""CLI boundary for closed media/build business reads."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from .media_build_business import (
    MediaBuildBusinessError,
    materialize_media_build_business_request,
    validate_media_pool_business_plan,
)
from .media_build_business_contracts import (
    MEDIA_POOL_GET_URI,
    PEAKS_REGION_URI,
    PEAKS_TRIMMED_URI,
    SOUNDBANK_GET_INCLUSIONS_URI,
    media_build_business_contract_data,
)


class MediaBuildBusinessCliError(ValueError):
    """One CLI declaration does not match its disclosed business shape."""


@dataclass(frozen=True, slots=True)
class MediaBuildCliInput:
    materialized_request: dict[str, Any] | None = None
    deferred_media_pool_plan: dict[str, Any] | None = None


def add_media_build_read_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--audio-source-id")
    parser.add_argument("--start-seconds", type=float)
    parser.add_argument("--end-seconds", type=float)
    parser.add_argument("--peak-pair-count", type=int)
    parser.add_argument(
        "--channel-mode",
        choices=("per-channel", "cross-channel"),
    )
    parser.add_argument("--soundbank-id")
    parser.add_argument("--max-results", type=int)
    parser.add_argument("--database-scope", action="append", default=[])
    parser.add_argument("--database-id", action="append", default=[])
    parser.add_argument("--search-text")
    parser.add_argument("--text-filter", nargs=3, action="append", default=[])
    parser.add_argument("--number-filter", nargs=3, action="append", default=[])
    parser.add_argument("--audio-description", action="append", default=[])
    parser.add_argument(
        "--weighted-audio-description",
        nargs=2,
        action="append",
        default=[],
    )
    parser.add_argument("--audio-similarity-file", action="append", default=[])
    parser.add_argument(
        "--weighted-audio-similarity-file",
        nargs=2,
        action="append",
        default=[],
    )
    parser.add_argument("--include-field", action="append", default=[])
    parser.add_argument("--exact-name-contains")
    parser.add_argument("--final-limit", type=int)
    parser.add_argument("--sort-by", nargs=2, action="append", default=[])


def media_build_fields_supplied(args: argparse.Namespace) -> bool:
    return any(
        getattr(args, name, None) is not None
        for name in (
            "audio_source_id",
            "start_seconds",
            "end_seconds",
            "peak_pair_count",
            "channel_mode",
            "soundbank_id",
            "max_results",
            "search_text",
            "exact_name_contains",
            "final_limit",
        )
    ) or any(
        bool(getattr(args, name, ()))
        for name in (
            "database_scope",
            "database_id",
            "text_filter",
            "number_filter",
            "audio_description",
            "weighted_audio_description",
            "audio_similarity_file",
            "weighted_audio_similarity_file",
            "include_field",
            "sort_by",
        )
    )


def media_build_input_from_namespace(
    args: argparse.Namespace,
    *,
    operation: str,
    version: str,
) -> MediaBuildCliInput:
    media_build_business_contract_data(operation, version)
    foreign_core_values = (
        args.source_id,
        args.target_id,
        args.object_id,
        args.field_meaning,
        args.platform_name,
    )
    try:
        if operation in {PEAKS_REGION_URI, PEAKS_TRIMMED_URI}:
            if any(value is not None for value in foreign_core_values):
                raise MediaBuildBusinessCliError(
                    "Audio peak reads accept only their disclosed media business fields"
                )
            if args.soundbank_id is not None or _media_pool_fields_supplied(args):
                raise MediaBuildBusinessCliError(
                    "Audio peak reads accept only their disclosed media business fields"
                )
            plan = {
                "audio_source_id": args.audio_source_id,
                "peak_pair_count": args.peak_pair_count,
                **(
                    {
                        "start_seconds": args.start_seconds,
                        "end_seconds": args.end_seconds,
                    }
                    if operation == PEAKS_REGION_URI
                    else {}
                ),
                **(
                    {"channel_mode": args.channel_mode}
                    if args.channel_mode is not None
                    else {}
                ),
            }
            return MediaBuildCliInput(
                materialized_request=materialize_media_build_business_request(
                    operation,
                    version,
                    plan,
                )
            )
        if operation == SOUNDBANK_GET_INCLUSIONS_URI:
            if any(value is not None for value in foreign_core_values) or any(
                value is not None
                for value in (
                    args.audio_source_id,
                    args.start_seconds,
                    args.end_seconds,
                    args.peak_pair_count,
                    args.channel_mode,
                )
            ) or _media_pool_fields_supplied(args):
                raise MediaBuildBusinessCliError(
                    "SoundBank inclusion reads accept only --soundbank-id"
                )
            return MediaBuildCliInput(
                materialized_request=materialize_media_build_business_request(
                    operation,
                    version,
                    {"soundbank_id": args.soundbank_id},
                )
            )
        if operation == MEDIA_POOL_GET_URI:
            if any(value is not None for value in foreign_core_values) or any(
                value is not None
                for value in (
                    args.audio_source_id,
                    args.start_seconds,
                    args.end_seconds,
                    args.peak_pair_count,
                    args.channel_mode,
                    args.soundbank_id,
                )
            ):
                raise MediaBuildBusinessCliError(
                    "Media Pool reads accept only their disclosed media business fields"
                )
            plan = _media_pool_plan(args)
            validate_media_pool_business_plan(plan)
            return MediaBuildCliInput(deferred_media_pool_plan=plan)
    except MediaBuildBusinessError as exc:
        raise MediaBuildBusinessCliError(str(exc)) from exc
    raise MediaBuildBusinessCliError("Unsupported media/build business read")


def _media_pool_fields_supplied(args: argparse.Namespace) -> bool:
    return any(
        getattr(args, name, None) is not None
        for name in (
            "max_results",
            "search_text",
            "exact_name_contains",
            "final_limit",
        )
    ) or any(
        bool(getattr(args, name, ()))
        for name in (
            "database_scope",
            "database_id",
            "text_filter",
            "number_filter",
            "audio_description",
            "weighted_audio_description",
            "audio_similarity_file",
            "weighted_audio_similarity_file",
            "include_field",
            "sort_by",
        )
    )


def _media_pool_plan(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "max_results": args.max_results,
        **({"database_scopes": args.database_scope} if args.database_scope else {}),
        **({"database_ids": args.database_id} if args.database_id else {}),
        **({"search_text": args.search_text} if args.search_text is not None else {}),
        **({"text_filters": args.text_filter} if args.text_filter else {}),
        **({"number_filters": args.number_filter} if args.number_filter else {}),
        **(
            {"audio_descriptions": args.audio_description}
            if args.audio_description
            else {}
        ),
        **(
            {"weighted_audio_descriptions": args.weighted_audio_description}
            if args.weighted_audio_description
            else {}
        ),
        **(
            {"audio_similarity_files": args.audio_similarity_file}
            if args.audio_similarity_file
            else {}
        ),
        **(
            {"weighted_audio_similarity_files": args.weighted_audio_similarity_file}
            if args.weighted_audio_similarity_file
            else {}
        ),
        **(
            {"return_field_meanings": args.include_field}
            if args.include_field
            else {}
        ),
        **(
            {"exact_name_contains": args.exact_name_contains}
            if args.exact_name_contains is not None
            else {}
        ),
        **({"final_limit": args.final_limit} if args.final_limit is not None else {}),
        **({"sort_rules": args.sort_by} if args.sort_by else {}),
    }


__all__ = [
    "MediaBuildBusinessCliError",
    "MediaBuildCliInput",
    "add_media_build_read_arguments",
    "media_build_fields_supplied",
    "media_build_input_from_namespace",
]
