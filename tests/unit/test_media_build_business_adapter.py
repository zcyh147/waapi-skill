from __future__ import annotations

import base64
import struct
from pathlib import Path

import pytest
from wwise_waapi.media_build_business import (
    MediaBuildBusinessError,
    materialize_media_build_business_request,
    normalize_media_build_result,
    validate_media_pool_business_plan,
)
from wwise_waapi.media_build_business_contracts import (
    MEDIA_POOL_GET_URI,
    PEAKS_REGION_URI,
    PEAKS_TRIMMED_URI,
    SOUNDBANK_GET_INCLUSIONS_URI,
    media_build_business_contract_data,
    media_build_business_operations,
    media_build_business_versions,
)


SOURCE_ID = "{11111111-1111-1111-1111-111111111111}"
SOUNDBANK_ID = "{22222222-2222-2222-2222-222222222222}"
INCLUDED_ID = "{33333333-3333-3333-3333-333333333333}"


def test_issue_85_contract_seals_all_sixteen_version_api_rows() -> None:
    rows = [
        (operation, version)
        for operation in sorted(media_build_business_operations())
        for version in media_build_business_versions(operation)
    ]

    assert len(rows) == 16
    assert rows.count((MEDIA_POOL_GET_URI, "2025.1")) == 1
    for operation, version in rows:
        contract = media_build_business_contract_data(operation, version)
        assert contract["input_mode"] == "business_declaration"
        assert contract["execution_shape"] == "bounded_read"
        assert contract["legacy_typed_call_public"] is False
        assert contract["start"]["gateway_argv_prefix"] == [
            "core-call",
            operation,
        ]


def test_peak_region_business_read_compiles_and_decodes_known_pcm_pairs() -> None:
    prepared = materialize_media_build_business_request(
        PEAKS_REGION_URI,
        "2025.1",
        {
            "audio_source_id": SOURCE_ID,
            "start_seconds": 0.25,
            "end_seconds": 0.75,
            "peak_pair_count": 2,
            "channel_mode": "cross-channel",
        },
    )

    assert prepared["args"] == {
        "object": SOURCE_ID,
        "timeFrom": 0.25,
        "timeTo": 0.75,
        "numPeaks": 2,
        "getCrossChannelPeaks": True,
    }
    encoded = base64.b64encode(struct.pack("<4h", -32768, 16384, -8192, 32767)).decode()

    assert normalize_media_build_result(
        prepared,
        {
            "numChannels": 1,
            "peaksArrayLength": 2,
            "peaksBinaryStrings": [encoded],
            "peaksDataSize": 8,
            "maxAbsValue": 32768,
            "channelConfig": "1.0",
        },
    ) == {
        "contract": "waapi-skill.media-build-result/v1",
        "kind": "decoded_peaks",
        "channel_mode": "cross-channel",
        "channel_count": 1,
        "peak_pair_count": 2,
        "requested_peak_pair_count": 2,
        "complete_requested_count": True,
        "normalization_divisor": 32768.0,
        "channels": [
            {
                "channel_index": 0,
                "pairs_normalized": [[-1.0, 0.5], [-0.25, 32767 / 32768]],
            }
        ],
        "channel_config": "1.0",
    }


def test_cross_channel_peak_result_requires_one_returned_channel() -> None:
    prepared = materialize_media_build_business_request(
        PEAKS_REGION_URI,
        "2025.1",
        {
            "audio_source_id": SOURCE_ID,
            "start_seconds": 0,
            "end_seconds": 1,
            "peak_pair_count": 1,
            "channel_mode": "cross-channel",
        },
    )
    encoded = base64.b64encode(struct.pack("<2h", -1, 1)).decode()

    with pytest.raises(MediaBuildBusinessError, match="cross-channel"):
        normalize_media_build_result(
            prepared,
            {
                "numChannels": 2,
                "peaksArrayLength": 1,
                "peaksBinaryStrings": [encoded, encoded],
                "peaksDataSize": 4,
                "maxAbsValue": 32768,
            },
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"audio_source_id": "not-a-guid"},
        {"start_seconds": float("nan")},
        {"end_seconds": float("inf")},
        {"start_seconds": -0.01},
        {"start_seconds": 1.0, "end_seconds": 1.0},
        {"peak_pair_count": True},
        {"peak_pair_count": 0},
        {"peak_pair_count": 513},
        {"channel_mode": "invented"},
        {"native_args": {}},
    ],
)
def test_peak_business_input_rejects_hostile_or_native_values(
    changes: dict[str, object],
) -> None:
    plan: dict[str, object] = {
        "audio_source_id": SOURCE_ID,
        "start_seconds": 0,
        "end_seconds": 1,
        "peak_pair_count": 4,
    }
    plan.update(changes)

    with pytest.raises(MediaBuildBusinessError):
        materialize_media_build_business_request(
            PEAKS_REGION_URI,
            "2025.1",
            plan,
        )


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_trimmed_peak_business_read_owns_native_defaults(version: str) -> None:
    prepared = materialize_media_build_business_request(
        PEAKS_TRIMMED_URI,
        version,
        {"audio_source_id": SOURCE_ID, "peak_pair_count": 8},
    )

    assert prepared["args"] == {
        "object": SOURCE_ID,
        "numPeaks": 8,
        "getCrossChannelPeaks": False,
    }
    assert prepared["options"] == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"peaksArrayLength": 3},
        {"numChannels": 2},
        {"peaksBinaryStrings": ["not-base64"]},
        {"peaksDataSize": 2},
        {"maxAbsValue": 0},
        {"channelConfig": 7},
    ],
)
def test_peak_result_rejects_inconsistent_or_malformed_binary(
    changes: dict[str, object],
) -> None:
    prepared = materialize_media_build_business_request(
        PEAKS_REGION_URI,
        "2025.1",
        {
            "audio_source_id": SOURCE_ID,
            "start_seconds": 0,
            "end_seconds": 1,
            "peak_pair_count": 2,
        },
    )
    encoded = base64.b64encode(struct.pack("<4h", -2, 2, -1, 1)).decode()
    result: dict[str, object] = {
        "numChannels": 1,
        "peaksArrayLength": 2,
        "peaksBinaryStrings": [encoded],
        "peaksDataSize": 8,
        "maxAbsValue": 32768,
        "channelConfig": "1.0",
    }
    result.update(changes)

    with pytest.raises(MediaBuildBusinessError):
        normalize_media_build_result(prepared, result)


def test_soundbank_inclusions_normalize_exact_identity_and_empty_results() -> None:
    prepared = materialize_media_build_business_request(
        SOUNDBANK_GET_INCLUSIONS_URI,
        "2022.1",
        {"soundbank_id": SOUNDBANK_ID},
    )

    assert prepared["args"] == {"soundbank": SOUNDBANK_ID}
    assert normalize_media_build_result(prepared, {"inclusions": []})["inclusions"] == []
    normalized = normalize_media_build_result(
        prepared,
        {"inclusions": [{"object": INCLUDED_ID, "filter": ["media", "events"]}]},
        identity_rows=[
            {
                "id": INCLUDED_ID,
                "name": "Play_Alarm",
                "type": "Event",
                "path": r"\Events\Default Work Unit\Play_Alarm",
            }
        ],
    )
    assert normalized["inclusions"][0]["includes"] == ["events", "media"]


@pytest.mark.parametrize(
    ("raw_result", "identity_rows"),
    [
        ({"inclusions": [{"object": INCLUDED_ID, "filter": []}]}, []),
        (
            {"inclusions": [{"object": INCLUDED_ID, "filter": ["invented"]}]},
            [],
        ),
        (
            {"inclusions": [{"object": INCLUDED_ID, "filter": ["events"]}]},
            [],
        ),
        (
            {"inclusions": []},
            [
                {
                    "id": INCLUDED_ID,
                    "name": "Extra",
                    "type": "Event",
                    "path": r"\Events\Extra",
                }
            ],
        ),
    ],
)
def test_soundbank_inclusions_fail_closed_on_unusable_identity_evidence(
    raw_result: dict[str, object],
    identity_rows: list[dict[str, object]],
) -> None:
    prepared = materialize_media_build_business_request(
        SOUNDBANK_GET_INCLUSIONS_URI,
        "2025.1",
        {"soundbank_id": SOUNDBANK_ID},
    )

    with pytest.raises(MediaBuildBusinessError):
        normalize_media_build_result(
            prepared,
            raw_result,
            identity_rows=identity_rows,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"max_results": 0},
        {"max_results": 201},
        {"search_text": "x" * 1025},
        {"text_filters": [["x" * 257, "contains", "rain"]]},
        {"text_filters": [["filename", "invented", "rain"]]},
        {"number_filters": [["duration", "greaterThan", float("nan")]]},
        {"text_filters": [["filename", "contains", "x"]] * 17},
        {"database_scopes": ["project-originals"] * 2},
        {"return_field_meanings": [f"custom-{index}" for index in range(33)]},
        {"weighted_audio_descriptions": [["rain", 1.01]]},
        {"sort_rules": [["duration", "sideways"]]},
        {"exact_name_contains": "Rain"},
        {"final_limit": 1},
        {"native_options": {}},
    ],
)
def test_media_pool_business_plan_rejects_hostile_or_native_values(
    changes: dict[str, object],
) -> None:
    plan: dict[str, object] = {"max_results": 10}
    plan.update(changes)

    with pytest.raises(MediaBuildBusinessError):
        validate_media_pool_business_plan(plan)


def test_media_pool_audio_similarity_requires_an_exact_regular_file(
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "reference.wav"
    audio_file.write_bytes(b"RIFF")
    validate_media_pool_business_plan(
        {
            "max_results": 10,
            "audio_similarity_files": [str(audio_file)],
            "weighted_audio_similarity_files": [[str(audio_file), 0.75]],
        }
    )

    link = tmp_path / "link.wav"
    link.symlink_to(audio_file)
    with pytest.raises(MediaBuildBusinessError, match="non-symlink"):
        validate_media_pool_business_plan(
            {"max_results": 10, "audio_similarity_files": [str(link)]}
        )
    with pytest.raises(MediaBuildBusinessError, match="existing audio file"):
        validate_media_pool_business_plan(
            {
                "max_results": 10,
                "audio_similarity_files": [str(tmp_path / "missing.wav")],
            }
        )


@pytest.mark.parametrize(
    "available_fields",
    [
        ["Path", "FileId", "Db"],
        ["Path", "FileId", "Db", "IXML/Mood", "Custom/Mood"],
        ["Path", "FileId", "Db", "Mood", "Mood"],
    ],
)
def test_media_pool_live_field_binding_requires_one_exact_case_candidate(
    available_fields: list[str],
) -> None:
    with pytest.raises(MediaBuildBusinessError):
        materialize_media_build_business_request(
            MEDIA_POOL_GET_URI,
            "2025.1",
            {"max_results": 5, "return_field_meanings": ["mood"]},
            available_media_fields=available_fields,
        )


def test_media_pool_result_rejects_missing_or_excess_projection_rows() -> None:
    prepared = materialize_media_build_business_request(
        MEDIA_POOL_GET_URI,
        "2025.1",
        {"max_results": 2, "return_field_meanings": ["filename"]},
        available_media_fields=["Path", "FileId", "Db", "Filename"],
    )
    valid = {
        "Path": "/Audio/Rain.wav",
        "FileId": "rain-id",
        "Db": "db-id",
        "Filename": "Rain.wav",
    }

    with pytest.raises(MediaBuildBusinessError):
        normalize_media_build_result(prepared, {"return": [valid] * 3})
    with pytest.raises(MediaBuildBusinessError):
        normalize_media_build_result(
            prepared,
            {"return": [{key: value for key, value in valid.items() if key != "Path"}]},
        )
    with pytest.raises(MediaBuildBusinessError):
        normalize_media_build_result(
            prepared,
            {
                "return": [
                    {
                        key: value
                        for key, value in valid.items()
                        if key != "Filename"
                    }
                ]
            },
        )


def test_media_pool_descending_sort_keeps_missing_values_last() -> None:
    prepared = materialize_media_build_business_request(
        MEDIA_POOL_GET_URI,
        "2025.1",
        {
            "max_results": 5,
            "return_field_meanings": ["filename", "duration-seconds"],
            "sort_rules": [["duration-seconds", "descending"]],
        },
        available_media_fields=[
            "Path",
            "FileId",
            "Db",
            "Filename",
            "WAV/Duration",
        ],
    )

    result = normalize_media_build_result(
        prepared,
        {
            "return": [
                {
                    "Path": "/Audio/unknown.wav",
                    "FileId": "unknown",
                    "Db": "db",
                    "Filename": "unknown.wav",
                    "WAV/Duration": None,
                },
                {
                    "Path": "/Audio/long.wav",
                    "FileId": "long",
                    "Db": "db",
                    "Filename": "long.wav",
                    "WAV/Duration": 4.0,
                },
            ]
        },
    )

    assert [row["file_id"] for row in result["items"]] == ["long", "unknown"]
