"""Closed business contracts for reviewed media/build Core reads."""

from __future__ import annotations

from typing import Any


MEDIA_BUILD_BUSINESS_CONTRACT = "waapi-skill.media-build-business/v1"

PEAKS_REGION_URI = "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInRegion"
PEAKS_TRIMMED_URI = (
    "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInTrimmedRegion"
)
MEDIA_POOL_GET_URI = "ak.wwise.core.mediaPool.get"
SOUNDBANK_GET_INCLUSIONS_URI = "ak.wwise.core.soundbank.getInclusions"

_ALL_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")

_CONTRACTS: dict[str, dict[str, Any]] = {
    PEAKS_REGION_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": (
            "audio_source_id",
            "start_seconds",
            "end_seconds",
            "peak_pair_count",
        ),
        "optional_fields": ("channel_mode",),
        "field_types": {
            "audio_source_id": "gateway_evidence_audio_source_id",
            "start_seconds": "nonnegative_finite_seconds",
            "end_seconds": "finite_seconds_after_start",
            "peak_pair_count": "bounded_peak_pair_count",
            "channel_mode": "per_channel_or_cross_channel",
        },
        "input_forms": {
            "audio_source_id": {"flag": "--audio-source-id", "repeatable": False},
            "start_seconds": {"flag": "--start-seconds", "repeatable": False},
            "end_seconds": {"flag": "--end-seconds", "repeatable": False},
            "peak_pair_count": {"flag": "--peak-pair-count", "repeatable": False},
            "channel_mode": {"flag": "--channel-mode", "repeatable": False},
        },
        "result_shape": "decoded_min_max_pairs_by_channel",
    },
    PEAKS_TRIMMED_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("audio_source_id", "peak_pair_count"),
        "optional_fields": ("channel_mode",),
        "field_types": {
            "audio_source_id": "gateway_evidence_audio_source_id",
            "peak_pair_count": "bounded_peak_pair_count",
            "channel_mode": "per_channel_or_cross_channel",
        },
        "input_forms": {
            "audio_source_id": {"flag": "--audio-source-id", "repeatable": False},
            "peak_pair_count": {"flag": "--peak-pair-count", "repeatable": False},
            "channel_mode": {"flag": "--channel-mode", "repeatable": False},
        },
        "result_shape": "decoded_min_max_pairs_by_channel",
    },
    SOUNDBANK_GET_INCLUSIONS_URI: {
        "versions": _ALL_VERSIONS,
        "required_fields": ("soundbank_id",),
        "optional_fields": (),
        "field_types": {
            "soundbank_id": "gateway_evidence_soundbank_id",
        },
        "input_forms": {
            "soundbank_id": {"flag": "--soundbank-id", "repeatable": False},
        },
        "result_shape": "bounded_inclusions_with_object_identity",
    },
    MEDIA_POOL_GET_URI: {
        "versions": ("2025.1",),
        "required_fields": ("max_results",),
        "optional_fields": (
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
        ),
        "field_types": {
            "max_results": "bounded_candidate_limit",
            "database_scopes": "reviewed_media_database_scope_list",
            "database_ids": "gateway_evidence_database_id_list",
            "search_text": "bounded_fuzzy_search_text",
            "text_filters": "media_field_text_filter_list",
            "number_filters": "media_field_number_filter_list",
            "audio_descriptions": "audio_description_list",
            "weighted_audio_descriptions": "weighted_audio_description_list",
            "audio_similarity_files": "exact_audio_file_list",
            "weighted_audio_similarity_files": "weighted_exact_audio_file_list",
            "return_field_meanings": "media_field_meaning_list",
            "exact_name_contains": "exact_case_filename_substring",
            "final_limit": "bounded_final_limit",
            "sort_rules": "media_field_sort_rule_list",
        },
        "input_forms": {
            "max_results": {"flag": "--max-results", "repeatable": False},
            "database_scopes": {"flag": "--database-scope", "repeatable": True},
            "database_ids": {"flag": "--database-id", "repeatable": True},
            "search_text": {"flag": "--search-text", "repeatable": False},
            "text_filters": {
                "flag": "--text-filter",
                "repeatable": True,
                "arguments": ["FIELD_MEANING", "OPERATOR", "VALUE"],
            },
            "number_filters": {
                "flag": "--number-filter",
                "repeatable": True,
                "arguments": ["FIELD_MEANING", "OPERATOR", "VALUE"],
            },
            "audio_descriptions": {
                "flag": "--audio-description",
                "repeatable": True,
            },
            "weighted_audio_descriptions": {
                "flag": "--weighted-audio-description",
                "repeatable": True,
                "arguments": ["DESCRIPTION", "WEIGHT_0_TO_1"],
            },
            "audio_similarity_files": {
                "flag": "--audio-similarity-file",
                "repeatable": True,
            },
            "weighted_audio_similarity_files": {
                "flag": "--weighted-audio-similarity-file",
                "repeatable": True,
                "arguments": ["ABSOLUTE_AUDIO_FILE", "WEIGHT_0_TO_1"],
            },
            "return_field_meanings": {
                "flag": "--include-field",
                "repeatable": True,
            },
            "exact_name_contains": {
                "flag": "--exact-name-contains",
                "repeatable": False,
            },
            "final_limit": {"flag": "--final-limit", "repeatable": False},
            "sort_rules": {
                "flag": "--sort-by",
                "repeatable": True,
                "arguments": ["FIELD_MEANING", "ascending|descending"],
            },
        },
        "result_shape": "bounded_business_media_rows",
    },
}

_INTENTS = {
    PEAKS_REGION_URI: (
        "read and decode bounded min/max peak pairs from an explicit time region "
        "of one exact AudioFileSource"
    ),
    PEAKS_TRIMMED_URI: (
        "read and decode bounded min/max peak pairs from the retained trimmed "
        "region of one exact AudioFileSource"
    ),
    SOUNDBANK_GET_INCLUSIONS_URI: (
        "list one exact SoundBank's bounded inclusions with resolved object identities"
    ),
    MEDIA_POOL_GET_URI: (
        "query Media Pool with business field meanings, bounded candidates, exact-case "
        "post-filtering, and Gateway-owned projection"
    ),
}


def media_build_business_operations() -> frozenset[str]:
    return frozenset(_CONTRACTS)


def media_build_business_versions(operation: str) -> tuple[str, ...]:
    try:
        return tuple(_CONTRACTS[operation]["versions"])
    except KeyError as exc:
        raise ValueError("unsupported media/build business operation") from exc


def media_build_business_catalog_rows() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "api": operation,
            "intent": _INTENTS[operation],
            "supported_versions": list(_CONTRACTS[operation]["versions"]),
        }
        for operation in sorted(_CONTRACTS)
    )


def media_build_business_contract_data(
    operation: str,
    version: str,
) -> dict[str, Any]:
    try:
        row = _CONTRACTS[operation]
    except KeyError as exc:
        raise ValueError("unsupported media/build business operation") from exc
    if version not in row["versions"]:
        raise ValueError("media/build business operation is unavailable in this version")
    return {
        "contract": MEDIA_BUILD_BUSINESS_CONTRACT,
        "operation": operation,
        "version": version,
        "input_mode": "business_declaration",
        "execution_shape": "bounded_read",
        "start": {
            "subcommand": "core-call",
            "gateway_argv_prefix": ["core-call", operation],
            "copy_exactly": True,
            "append_arguments": "disclosed_business_fields_only",
        },
        "declaration": {
            "subcommand": "core-call",
            "required_fields": list(row["required_fields"]),
            "optional_fields": list(row["optional_fields"]),
            "field_types": dict(row["field_types"]),
            "input_forms": dict(row["input_forms"]),
        },
        "gateway_derivations": [
            "exact_object_selector",
            "live_media_field_binding",
            "native_request",
            "bounded_result_projection",
            "continuation",
        ],
        "legacy_typed_call_public": False,
        "safety": {
            "object_revalidation": "exact_guid_name_type_path",
            "max_peak_pair_count": 512,
            "max_media_pool_candidates": 200,
            "max_soundbank_inclusions": 500,
            "native_request_input": "forbidden",
            "result_bound": True,
        },
        "result_shape": row["result_shape"],
    }


__all__ = [
    "MEDIA_BUILD_BUSINESS_CONTRACT",
    "MEDIA_POOL_GET_URI",
    "PEAKS_REGION_URI",
    "PEAKS_TRIMMED_URI",
    "SOUNDBANK_GET_INCLUSIONS_URI",
    "media_build_business_catalog_rows",
    "media_build_business_contract_data",
    "media_build_business_operations",
    "media_build_business_versions",
]
