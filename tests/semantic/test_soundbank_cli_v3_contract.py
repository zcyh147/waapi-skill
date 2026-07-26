from __future__ import annotations

import copy
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from tests.semantic.support.codex_eval_bundle_v3 import (
    EvalBundleV3Error,
    OnlineScenario,
    _parse_online_case,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
OTHER_CASES = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "evals"
    / "online"
    / "2022.1"
    / "other.json"
)

SOUNDBANK_OPERATIONS = {
    "ak.wwise.core.soundbank.convertExternalSources": "convertExternalSources",
    "ak.wwise.core.soundbank.generate": "generate",
    "ak.wwise.core.soundbank.generated": "observeGenerated",
    "ak.wwise.core.soundbank.processDefinitionFiles": "processDefinitionFiles",
    "ak.wwise.core.soundbank.setInclusions": "setInclusions",
}
CLI_OPERATIONS = {
    "ak.wwise.cli.convertExternalSource": "convertExternalSource",
    "ak.wwise.cli.generateSoundbank": "generateSoundbank",
    "ak.wwise.cli.migrate": "migrate",
    "ak.wwise.cli.tabDelimitedImport": "tabDelimitedImport",
}
REVIEWED_APIS = frozenset(SOUNDBANK_OPERATIONS | CLI_OPERATIONS)

CLI_ASSET_CONTRACT = "waapi-skill.cli-heavy-fixture/v1"
CLI_SANDBOX_POLICY = "fresh_project_process_asset_and_output_roots_per_case"
CLI_CUSTOM_COMMAND_POLICY = "forbid_all_custom_command_fields_and_project_hooks"
CLI_CLEANUP_POLICY = (
    "success_remove_all_case_owned_project_process_asset_output_"
    "failure_or_indeterminate_seal_never_reuse"
)
FAILURE_CLEANUP_POSTCONDITION = (
    "failed_or_indeterminate_case_sandbox_sealed_and_never_reused"
)
SOUNDBANK_FIXTURE_POLICY = (
    "fresh_case_project_materializes_events_media_dependencies_controls_and_"
    "preexisting_artifacts_then_existing_soundbank_objects_or_proves_"
    "temporary_request_only_bank_objects_absent_before_snapshot"
)
SOUNDBANK_DEFINITION_SERIALIZATION = {
    "line_endings": "lf",
    "field_separator": "tab",
    "ordinary_event_layout": ["soundbank", "resolved_identity", "filter_columns"],
    "special_directive_layout": [
        "soundbank",
        "directive",
        "resolved_identity",
        "filter_columns",
    ],
    "quoting_policy": "name_identity_double_quoted_guid_and_uint32_unquoted",
}
SOUNDBANK_TOPIC_INIT_PRECONDITION = {
    "materialization": (
        "runner_generates_init_before_subscription_in_case_owned_output_and_cache"
    ),
    "proof": [
        "init_artifact_nonzero_sha256",
        "init_artifact_mtime_ns",
        "cache_tree_sha256",
    ],
    "publisher_requirement": (
        "subscription_ack_then_all_publisher_requests_rebuildInitBank_false"
    ),
    "unexpected_notification_policy": "any_init_generated_notification_fails_scope",
}


def _raw_cases() -> list[dict[str, Any]]:
    document = json.loads(OTHER_CASES.read_text(encoding="utf-8"))
    return [
        row
        for row in document["cases"]
        if isinstance(row, dict) and row.get("api") in REVIEWED_APIS
    ]


def _parsed_cases() -> list[OnlineScenario]:
    return [
        _parse_online_case(row, f"soundbank_cli.cases[{index}]")
        for index, row in enumerate(_raw_cases())
    ]


def _raw_case(case_id: str) -> dict[str, Any]:
    return copy.deepcopy(next(row for row in _raw_cases() if row["id"] == case_id))


def _asset_spec(row: Mapping[str, Any]) -> dict[str, Any]:
    fixture = row["fixture"]
    assert isinstance(fixture, Mapping)
    asset_spec = fixture["asset_spec"]
    assert isinstance(asset_spec, dict)
    return asset_spec


def test_soundbank_and_cli_review_set_is_exactly_five_parseable_cases_per_api() -> None:
    cases = _parsed_cases()

    assert len(REVIEWED_APIS) == 9
    assert len(cases) == 45
    assert Counter(case.api for case in cases) == {
        api: 5 for api in REVIEWED_APIS
    }
    for api in REVIEWED_APIS:
        api_cases = [case for case in cases if case.api == api]
        assert [case.scenario_index for case in api_cases] == [1, 2, 3, 4, 5]
        assert len({case.scenario_family for case in api_cases}) == 5
        assert len({case.prompt_sha256 for case in api_cases}) == 5

        prompts = "\n".join(case.prompt.casefold() for case in api_cases)
        for coaching_phrase in (
            "必须遵守",
            "skill 的边界",
            "skill边界",
            "runner",
            "harness",
            "memory",
            "oracle",
            "fixture",
        ):
            assert coaching_phrase.casefold() not in prompts


def test_soundbank_and_cli_cases_have_full_oracle_and_cleanup_lifecycles() -> None:
    for case in _parsed_cases():
        expected_sandbox = (
            "isolated_io_root" if case.api in CLI_OPERATIONS else "scenario_project_copy"
        )
        assert case.fixture["sandbox"] == expected_sandbox

        phases = {assertion.phase for assertion in case.oracle_assertions}
        assert {"before", "after", "cleanup"}.issubset(phases)
        if case.item_type == "topic":
            assert case.api == "ak.wwise.core.soundbank.generated"
            assert {"event", "preview"}.issubset(phases)
        else:
            assert "preview" in phases

        postconditions = set(case.cleanup["postconditions"])
        assert "project_source_unchanged" in postconditions
        assert FAILURE_CLEANUP_POSTCONDITION in postconditions
        assert any(
            value.startswith("successful_case_") and value.endswith("removed")
            for value in postconditions
        )
        assert any(
            assertion.phase == "cleanup" and assertion.subject_api == case.api
            for assertion in case.oracle_assertions
        )


@pytest.mark.parametrize(
    "case_id",
    ("O22-SB-GENERATE-02", "O22-SB-GENERATED-02"),
)
def test_localized_soundbank_contract_declares_one_logical_sound_per_semantic_line(
    case_id: str,
) -> None:
    spec = _asset_spec(_raw_case(case_id))
    manifest = spec["fixture_manifest"]
    bank = manifest["soundbanks"][0]
    logical_paths: set[str] = set()

    for event in bank["events"]:
        rows = [row for row in bank["media"] if row["event"] == event["name"]]
        assert [
            (row["language"], row["import_operation"], row["create_event"])
            for row in rows
        ] == [
            ("Chinese", "createNew", True),
            ("English", "useExisting", False),
            ("Japanese", "useExisting", False),
        ]
        assert len({row["object_path"] for row in rows}) == 1
        logical_path = rows[0]["object_path"]
        assert logical_path.startswith(
            r"\Actor-Mixer Hierarchy\Default Work Unit" + "\\" + manifest["profile"] + "\\"
        )
        logical_paths.add(logical_path)

    assert len(logical_paths) == 2


def test_soundbank_assets_are_closed_and_case_owned() -> None:
    for row in _raw_cases():
        api = row["api"]
        if api not in SOUNDBANK_OPERATIONS:
            continue
        asset_spec = _asset_spec(row)

        assert asset_spec["operation"] == SOUNDBANK_OPERATIONS[api]
        assert "case_owned" in asset_spec["cleanup_policy"]


def test_generate_and_generated_fixtures_materialize_exact_business_content() -> None:
    rows = {
        row["id"]: _asset_spec(row)
        for row in _raw_cases()
        if row["api"]
        in {
            "ak.wwise.core.soundbank.generate",
            "ak.wwise.core.soundbank.generated",
        }
    }
    assert len(rows) == 10
    assert len(
        {row["fixture_manifest"]["profile"] for row in rows.values()}
    ) == 10

    for row in rows.values():
        fixture = row["fixture_manifest"]
        assert fixture["materialization_policy"] == SOUNDBANK_FIXTURE_POLICY
        assert fixture["control_soundbanks"]
        assert fixture["soundbanks"]
        for bank in fixture["soundbanks"]:
            assert bank["artifact_expectation"] in {
                "nonlocalized",
                "localized",
                "mixed",
            }
            assert bank["project_object_mode"] in {
                "existing_soundbank",
                "temporary_request_only",
            }
            assert len(bank["events"]) >= 2
            event_names = {event["name"] for event in bank["events"]}
            assert event_names == {media["event"] for media in bank["media"]}
            assert all(media["relative_wav"].endswith(".wav") for media in bank["media"])
            assert bank["dependencies"]

    generation_rows = [
        rows[f"O22-SB-GENERATE-{index:02d}"] for index in range(1, 6)
    ]
    for row in generation_rows:
        requested = {
            bank["name"]: bank["artifact_expectation"]
            for bank in row["request"]["soundbanks"]
        }
        materialized = {
            bank["name"]: bank["artifact_expectation"]
            for bank in row["fixture_manifest"]["soundbanks"]
        }
        assert materialized == requested
    assert {
        media["language"]
        for media in generation_rows[1]["fixture_manifest"]["soundbanks"][0]["media"]
    } == {"Chinese", "English", "Japanese"}
    assert generation_rows[3]["fixture_manifest"]["preexisting_artifacts"] == [
        {
            "soundbank": "Cinematics_Intro",
            "platform": "Windows",
            "language": None,
            "marker": "deterministic_stale_nonzero_sha256",
        }
    ]
    assert [
        event["name"]
        for event in generation_rows[4]["fixture_manifest"]["soundbanks"][0]["events"]
    ] == generation_rows[4]["request"]["soundbanks"][0]["events"]
    assert [
        bank["project_object_mode"]
        for row in generation_rows[:4]
        for bank in row["fixture_manifest"]["soundbanks"]
    ] == ["existing_soundbank"] * 6
    assert generation_rows[4]["fixture_manifest"]["soundbanks"][0][
        "project_object_mode"
    ] == "temporary_request_only"
    assert generation_rows[4]["fixture_manifest"]["preexisting_artifacts"] == []

    topic_rows = [
        rows[f"O22-SB-GENERATED-{index:02d}"] for index in range(1, 6)
    ]
    assert topic_rows[4]["fixture_manifest"]["preexisting_artifacts"][0][
        "marker"
    ] == "deterministic_stale_nonzero_sha256"
    for row in topic_rows:
        assert {
            bank["project_object_mode"]
            for bank in row["fixture_manifest"]["soundbanks"]
        } == {"existing_soundbank"}
        assert row["fixture_manifest"]["init_precondition"] == (
            SOUNDBANK_TOPIC_INIT_PRECONDITION
        )
        assert all(
            request["rebuildInitBank"] is False
            for request in row["publisher_requests"]
        )
        assert all(
            request["rebuildSoundBanks"] is False
            for request in row["publisher_requests"]
        )


def test_soundbank_definition_files_declare_exact_tsv_serialization() -> None:
    rows = [
        _asset_spec(row)
        for row in _raw_cases()
        if row["api"] == "ak.wwise.core.soundbank.processDefinitionFiles"
    ]
    assert len(rows) == 5
    for row in rows:
        for definition in row["files"]:
            assert definition["encoding"] == "utf-8_no_bom"
            assert definition["serialization"] == SOUNDBANK_DEFINITION_SERIALIZATION
            assert definition["serialization"]["ordinary_event_layout"] == [
                "soundbank",
                "resolved_identity",
                "filter_columns",
            ]
            assert definition["serialization"]["special_directive_layout"][1] == (
                "directive"
            )


def test_cli_assets_are_closed_isolated_and_fail_closed() -> None:
    for row in _raw_cases():
        api = row["api"]
        if api not in CLI_OPERATIONS:
            continue
        asset_spec = _asset_spec(row)

        assert asset_spec["contract"] == CLI_ASSET_CONTRACT
        assert asset_spec["operation"] == CLI_OPERATIONS[api]
        assert asset_spec["sandbox_policy"] == CLI_SANDBOX_POLICY
        assert asset_spec["custom_command_policy"] == CLI_CUSTOM_COMMAND_POLICY
        assert asset_spec["cleanup_policy"] == CLI_CLEANUP_POLICY


def test_cli_heavy_cases_cover_the_reviewed_request_shapes() -> None:
    rows = {row["id"]: _asset_spec(row) for row in _raw_cases() if row["api"] in CLI_OPERATIONS}

    convert_rows = [rows[f"O22-CLI-CONVERT-EXTERNAL-{index:02d}"] for index in range(1, 6)]
    assert [row["request"]["output_mode"] for row in convert_rows] == [
        "platform_pair",
        "platform_pair_array",
        "platform_pair_array",
        "platform_pair_array",
        "platform_pair",
    ]
    assert [row["request"]["source_mode"] for row in convert_rows] == [
        "source_file",
        "source_file",
        "source_by_platform",
        "source_file",
        "source_file",
    ]
    assert [len(row["expected"]["outputs"]) for row in convert_rows] == [3, 8, 4, 12, 3]
    for row in convert_rows:
        wav_names = {item["name"] for item in row["assets"]["wav"]["files"]}
        document_entries: dict[str, list[dict[str, Any]]] = {}
        for document in row["assets"]["wsources"]:
            assert set(document) == {"name", "schema_version", "root_mode", "entries"}
            assert document["schema_version"] == 1
            assert document["root_mode"] == "case_asset_root"
            document_entries[document["name"]] = document["entries"]
            for entry in document["entries"]:
                assert set(entry) == {
                    "path",
                    "conversion",
                    "destination",
                    "analysis_types",
                }
                assert entry["path"] in wav_names
                assert entry["destination"].casefold().endswith(".wav")
                assert not {"cookie", "language", "wav_key"}.intersection(entry)

        expected_outputs = {
            (
                binding["platform"],
                document_name,
                entry["path"],
                f"{entry['destination'][:-4]}.wem",
            )
            for binding in row["request"]["bindings"]
            for document_name in binding["manifests"]
            for entry in document_entries[document_name]
        }
        assert expected_outputs == {
            (
                item["platform"],
                item["document"],
                item["source_path"],
                item["relative_path"],
            )
            for item in row["expected"]["outputs"]
        }
    assert [
        item["root_key"] for item in convert_rows[3]["request"]["outputs"]
    ] == ["windows_output", "mac_output"]

    generate_rows = [rows[f"O22-CLI-GENERATE-BANK-{index:02d}"] for index in range(1, 6)]
    assert [row["request"]["bank_selector"] for row in generate_rows] == [
        "names",
        "names",
        "absolute_utf8_list_file",
        "names",
        "names",
    ]
    assert generate_rows[2]["assets"]["bank_list"] is not None
    assert generate_rows[3]["request"]["clear_audio_file_cache"] is True
    assert generate_rows[3]["request"]["header_file"] is True
    assert len(generate_rows[4]["request"]["import_definition_files"]) == 2
    assert all(row["request"]["save"] is False for row in generate_rows)
    localized = generate_rows[1]
    assert localized["request"]["languages"] == [
        "English(US)",
        "Japanese",
        "Chinese(PRC)",
    ]
    assert "Chinese(PRC)" in _raw_case("O22-CLI-GENERATE-BANK-02")["prompt"]
    assert {
        row["language"] for row in localized["expected"]["bank_artifacts"]
    } == {"English(US)", "Japanese", "Chinese(PRC)"}
    localized_media = localized["fixture_manifest"]["soundbanks"][0]["media"]
    logical_paths: set[str] = set()
    for event in localized["fixture_manifest"]["soundbanks"][0]["events"]:
        event_rows = [
            row for row in localized_media if row["event"] == event["name"]
        ]
        assert {row["language"] for row in event_rows} == {
            "English(US)",
            "Japanese",
            "Chinese(PRC)",
        }
        assert len({row["object_path"] for row in event_rows}) == 1
        logical_paths.add(event_rows[0]["object_path"])
        assert [
            (row["language"], row["import_operation"], row["create_event"])
            for row in event_rows
        ] == [
            ("English(US)", "createNew", True),
            ("Japanese", "useExisting", False),
            ("Chinese(PRC)", "useExisting", False),
        ]
    assert len(logical_paths) == 2
    assert len(
        {row["fixture_manifest"]["profile"] for row in generate_rows}
    ) == 5
    for row in generate_rows:
        fixture = row["fixture_manifest"]
        assert fixture["materialization_policy"] == SOUNDBANK_FIXTURE_POLICY
        assert [bank["name"] for bank in fixture["soundbanks"]] == row["request"][
            "banks"
        ]
        expected_artifact_expectation = (
            "nonlocalized" if row["request"]["skip_languages"] else "localized"
        )
        assert {
            bank["artifact_expectation"] for bank in fixture["soundbanks"]
        } == {expected_artifact_expectation}
        assert fixture["control_soundbanks"]
        for bank in fixture["soundbanks"]:
            assert len(bank["events"]) >= 2
            assert {event["name"] for event in bank["events"]} == {
                media["event"] for media in bank["media"]
            }
            assert bank["dependencies"]
        bindings = row["request"]["path_bindings"]
        assert bindings["resolution_policy"] == (
            "resolve_declared_case_root_keys_to_absolute_paths_then_append_"
            "contained_relative_path"
        )
        assert [item["platform"] for item in bindings["soundbank_paths"]] == row[
            "request"
        ]["platforms"]
        assert all(
            item["root_key"] == "output_directory"
            for item in bindings["soundbank_paths"]
        )
        physical_paths = {
            (item["root_key"], item["relative_path"])
            for item in bindings["soundbank_paths"]
        }
        assert len(physical_paths) == len(row["request"]["platforms"])
        assert bindings["cache"]["root_key"] != bindings["root_output_path"]["root_key"]
    assert generate_rows[2]["request"]["output_mode"] == "per_platform"
    assert generate_rows[3]["request"]["path_bindings"]["fixture_owned_root_keys"] == []
    assert generate_rows[3]["request"]["path_bindings"]["cache"]["root_key"] == (
        "cache_directory"
    )
    assert generate_rows[3]["request"]["path_bindings"]["root_output_path"][
        "root_key"
    ] == "root_output_directory"
    assert [
        item for item in generate_rows[3]["expected"]["automatic_artifacts"]
        if item["name"] == "Wwise_IDs.h"
    ] == [{"name": "Wwise_IDs.h", "platform": None, "location": "root_output"}]
    assert all(
        bank["project_object_mode"] == "existing_soundbank"
        for row in generate_rows[:4]
        for bank in row["fixture_manifest"]["soundbanks"]
    )
    assert {
        bank["project_object_mode"]
        for bank in generate_rows[4]["fixture_manifest"]["soundbanks"]
    } == {"temporary_request_only"}
    assert len(generate_rows[3]["fixture_manifest"]["preexisting_artifacts"]) == 4
    assert generate_rows[3]["fixture_manifest"]["rebuild_seeds"] == {
        "cache": {
            "relative_path": "Windows/SFX/stale-audio-cache.wem",
            "marker": "deterministic_stale_cache_v1",
        },
        "header": {
            "relative_path": "Wwise_IDs.h",
            "marker": "deterministic_stale_header_v1",
        },
    }
    assert generate_rows[4]["fixture_manifest"]["preexisting_artifacts"] == []
    generate01 = _raw_case("O22-CLI-GENERATE-BANK-01")
    assert "Init 依赖齐全" not in generate01["prompt"]
    assert all(
        "依赖正确" not in assertion["expectation"]
        for assertion in generate01["oracle_assertions"]
    )
    for definition in generate_rows[4]["assets"]["definition_files"]:
        assert definition["serialization"] == SOUNDBANK_DEFINITION_SERIALIZATION
        assert definition["materialization_policy"] == (
            "runner_resolves_declared_object_paths_then_writes_sealed_guid_identity_rows"
        )
        for definition_row in definition["rows"]:
            assert definition_row["directive"] == "Event"
            assert definition_row["identity_format"] == "guid"
            assert definition_row["identity_materialization"] == "runner_queries_guid"
            assert definition_row["identity"].startswith("\\")
            assert definition_row["filters"] == ["Event", "Structure", "Media"]

    tab_rows = [rows[f"O22-CLI-TAB-IMPORT-{index:02d}"] for index in range(1, 6)]
    assert [row["request"]["import_operation"] for row in tab_rows] == [
        "useExisting",
        "useExisting",
        "createNew",
        "replaceExisting",
        "useExisting",
    ]
    assert [len(row["assets"]["tsv"]["rows"]) for row in tab_rows] == [6, 6, 5, 4, 5]
    assert [row["assets"]["existing_top_level_work_unit"] for row in tab_rows] == [
        "Voices",
        "SFX",
        "Review",
        "SFX",
        "SFX",
    ]
    assert "Event" in tab_rows[4]["assets"]["tsv"]["headers"]
    assert all(item["event"] for item in tab_rows[4]["expected"]["objects"])
    assert tab_rows[0]["expected"]["hierarchy_materialization"] == (
        "preexisting_actor_mixers"
    )
    assert Counter(item["level"] for item in tab_rows[0]["expected"]["hierarchy"]) == {
        "chapter": 3,
        "scene": 6,
        "character": 6,
    }
    assert {item["type"] for item in tab_rows[0]["expected"]["hierarchy"]} == {
        "ActorMixer"
    }

    migrate_rows = [rows[f"O22-CLI-MIGRATE-{index:02d}"] for index in range(1, 6)]
    assert {row["project"]["source_version"] for row in migrate_rows} == {"2021.1"}
    assert {row["project"]["target_version"] for row in migrate_rows} == {"2022.1"}
    assert len({row["assets"]["profile"] for row in migrate_rows}) == 5
    assert [len(row["assets"]["anchors"]) for row in migrate_rows] == [2, 1, 2, 2, 4]
    assert all(row["request"]["abort_on_load_issues"] is False for row in migrate_rows)
    assert all(
        row["expected"]["log_policy"]
        == "zero_fatal_zero_unresolved_selected_anchor_verification_and_all_load_issues_classified"
        for row in migrate_rows
    )
    sealed_fixtures = [row["assets"]["fixture"] for row in migrate_rows]
    assert {fixture["root"] for fixture in sealed_fixtures} == {"tests/_org/2021.1"}
    assert {fixture["project"] for fixture in sealed_fixtures} == {"SampleProject.wproj"}
    assert {fixture["file_count"] for fixture in sealed_fixtures} == {66}
    assert {fixture["manifest_digest"] for fixture in sealed_fixtures} == {
        "51b1d8abfee6c296e184446a89069c011db56e50c50463f5f9036c37766fde4d"
    }
    scoped = migrate_rows[4]["expected"]["comparison_scope"]
    assert scoped["project_descendant_tags"] == ["Platform", "Language"]
    assert scoped["project_property_names"] == [
        "DefaultLanguage",
        "ExternalSourcesInputPath",
        "ExternalSourcesOutputPath",
        "SoundBankHeaderFilePath",
        "SoundBankPaths",
    ]
    assert scoped["conversion_property_names"] == [
        "Channels",
        "LRMix",
        "MaxSampleRate",
        "MinSampleRate",
        "SampleRate",
    ]


@pytest.mark.parametrize(
    ("case_id", "mutate", "message"),
    [
        (
            "O22-CLI-GENERATE-BANK-01",
            lambda row: _asset_spec(row)["request"].__setitem__(
                "custom-pre-gen-cmd", "echo forbidden"
            ),
            "fields mismatch",
        ),
        (
            "O22-CLI-GENERATE-BANK-01",
            lambda row: _asset_spec(row).pop("fixture_manifest"),
            "fixture_manifest is required",
        ),
        (
            "O22-CLI-GENERATE-BANK-02",
            lambda row: _asset_spec(row)["fixture_manifest"]["soundbanks"][0][
                "media"
            ].__setitem__(
                slice(None),
                [
                    media
                    for media in _asset_spec(row)["fixture_manifest"]["soundbanks"][0][
                        "media"
                    ]
                    if media["language"] != "Chinese(PRC)"
                ],
            ),
            "languages must exactly prove artifact_expectation",
        ),
        (
            "O22-CLI-GENERATE-BANK-02",
            lambda row: _asset_spec(row)["fixture_manifest"]["soundbanks"][0][
                "media"
            ][0].pop("create_event"),
            "must declare object_path, import_operation, and create_event together",
        ),
        (
            "O22-SB-GENERATE-02",
            lambda row: _asset_spec(row)["fixture_manifest"]["soundbanks"][0][
                "media"
            ][0].pop("object_path"),
            "must declare object_path, import_operation, and create_event together",
        ),
        (
            "O22-SB-GENERATED-02",
            lambda row: _asset_spec(row)["fixture_manifest"]["soundbanks"][0][
                "media"
            ][2].__setitem__("create_event", True),
            "must create its first-language Sound/Event once",
        ),
        (
            "O22-CLI-CONVERT-EXTERNAL-01",
            lambda row: _asset_spec(row)["expected"]["outputs"].pop(),
            "must exactly match all bound manifests",
        ),
        (
            "O22-CLI-CONVERT-EXTERNAL-01",
            lambda row: _asset_spec(row)["assets"]["wsources"][0]["entries"][
                0
            ].__setitem__("cookie", "invented"),
            "fields mismatch",
        ),
        (
            "O22-CLI-CONVERT-EXTERNAL-04",
            lambda row: _asset_spec(row)["request"]["outputs"][1].__setitem__(
                "root_key", "windows_output"
            ),
            "disjoint platform roots",
        ),
        (
            "O22-CLI-CONVERT-EXTERNAL-01",
            lambda row: _asset_spec(row)["request"].__setitem__(
                "output_mode", "platform_pair_array"
            ),
            "requires multiple disjoint platform roots",
        ),
        (
            "O22-CLI-CONVERT-EXTERNAL-02",
            lambda row: _asset_spec(row)["request"].__setitem__(
                "output_mode", "platform_pair"
            ),
            "requires exactly one platform root",
        ),
        (
            "O22-CLI-GENERATE-BANK-01",
            lambda row: _asset_spec(row)["request"]["path_bindings"][
                "soundbank_paths"
            ][1].__setitem__("relative_path", "Windows"),
            "physical paths",
        ),
        (
            "O22-CLI-GENERATE-BANK-04",
            lambda row: _asset_spec(row)["expected"]["automatic_artifacts"][
                2
            ].__setitem__("platform", "Windows"),
            "Wwise_IDs.h",
        ),
        (
            "O22-CLI-GENERATE-BANK-04",
            lambda row: _asset_spec(row)["fixture_manifest"]["rebuild_seeds"][
                "cache"
            ].__setitem__("marker", "guessed_stale_cache"),
            "rebuild_seeds must exactly seal",
        ),
        (
            "O22-CLI-GENERATE-BANK-05",
            lambda row: _asset_spec(row)["assets"]["definition_files"][0][
                "rows"
            ][0].__setitem__("filters", ["event", "Structure", "Media"]),
            "case-sensitive directive filter set",
        ),
        (
            "O22-CLI-GENERATE-BANK-05",
            lambda row: _asset_spec(row)["assets"]["definition_files"][0][
                "serialization"
            ].__setitem__(
                "ordinary_event_layout",
                ["soundbank", "directive", "resolved_identity", "filter_columns"],
            ),
            "reviewed SoundBank Definition TSV layout",
        ),
        (
            "O22-CLI-TAB-IMPORT-05",
            lambda row: _asset_spec(row)["expected"]["objects"][0].__setitem__(
                "event", "Play_Wrong_Event"
            ),
            "events must match the TSV rows",
        ),
        (
            "O22-CLI-TAB-IMPORT-01",
            lambda row: _asset_spec(row)["expected"].__setitem__(
                "hierarchy_materialization", "implicit"
            ),
            "must precreate the typed hierarchy",
        ),
        (
            "O22-CLI-TAB-IMPORT-02",
            lambda row: _asset_spec(row)["assets"].__setitem__(
                "existing_top_level_work_unit", "Voices"
            ),
            "declared existing top-level Work Unit",
        ),
        (
            "O22-CLI-MIGRATE-01",
            lambda row: _asset_spec(row)["expected"]["allowed_changes"].pop(),
            "reviewed migration delta",
        ),
        (
            "O22-CLI-MIGRATE-01",
            lambda row: _asset_spec(row)["request"].__setitem__(
                "abort_on_load_issues", True
            ),
            "must be false",
        ),
        (
            "O22-CLI-MIGRATE-01",
            lambda row: _asset_spec(row)["assets"]["fixture"].__setitem__(
                "manifest_digest", "0" * 64
            ),
            "sealed 2021.1 SampleProject",
        ),
        (
            "O22-CLI-MIGRATE-05",
            lambda row: _asset_spec(row)["expected"]["comparison_scope"][
                "project_property_names"
            ].append("EveryProjectProperty"),
            "reviewed migration intent",
        ),
    ],
)
def test_cli_heavy_parser_rejects_unreviewed_or_incomplete_contracts(
    case_id: str,
    mutate: Any,
    message: str,
) -> None:
    row = _raw_case(case_id)
    mutate(row)

    with pytest.raises(EvalBundleV3Error, match=message):
        _parse_online_case(row, f"negative.{case_id}")


@pytest.mark.parametrize(
    ("case_id", "mutate", "message"),
    [
        (
            "O22-SB-GENERATE-01",
            lambda row: _asset_spec(row)["request"]["soundbanks"][0].__setitem__(
                "artifact_expectation", "localized"
            ),
            "disagrees with skipLanguages",
        ),
        (
            "O22-SB-GENERATE-02",
            lambda row: _asset_spec(row)["fixture_manifest"]["soundbanks"][0][
                "media"
            ].__setitem__(
                slice(None),
                [
                    media
                    for media in _asset_spec(row)["fixture_manifest"]["soundbanks"][0][
                        "media"
                    ]
                    if media["language"] != "Japanese"
                ],
            ),
            "languages must exactly prove artifact_expectation",
        ),
        (
            "O22-SB-GENERATE-05",
            lambda row: _asset_spec(row)["fixture_manifest"]["soundbanks"][0][
                "events"
            ].pop(),
            "not declared by this Bank",
        ),
        (
            "O22-SB-GENERATE-05",
            lambda row: _asset_spec(row)["fixture_manifest"]["soundbanks"][0].__setitem__(
                "project_object_mode", "existing_soundbank"
            ),
            "does not match the generate request shape",
        ),
        (
            "O22-SB-GENERATED-01",
            lambda row: _asset_spec(row)["fixture_manifest"]["soundbanks"][0].__setitem__(
                "project_object_mode", "temporary_request_only"
            ),
            "must be existing_soundbank",
        ),
        (
            "O22-SB-GENERATED-02",
            lambda row: _asset_spec(row)["fixture_manifest"]["init_precondition"][
                "proof"
            ].pop(),
            "reviewed Init proof",
        ),
        (
            "O22-SB-GENERATED-03",
            lambda row: _asset_spec(row)["publisher_requests"][0].__setitem__(
                "rebuildInitBank", True
            ),
            "sealed Init precondition",
        ),
        (
            "O22-SB-GENERATED-04",
            lambda row: _asset_spec(row)["publisher_requests"][0]["soundbanks"][
                0
            ].__setitem__("rebuild", False),
            "forces one observable target generation",
        ),
        (
            "O22-SB-GENERATED-05",
            lambda row: _asset_spec(row)["publisher_requests"][0].__setitem__(
                "rebuildSoundBanks", True
            ),
            "explicitly scoped topic publisher",
        ),
        (
            "O22-SB-GENERATED-05",
            lambda row: _asset_spec(row)["fixture_manifest"][
                "preexisting_artifacts"
            ][0].__setitem__("marker", "unknown_old_file"),
            "marker is not closed",
        ),
        (
            "O22-SB-PROCESS-DEF-01",
            lambda row: _asset_spec(row)["files"][0]["serialization"].__setitem__(
                "ordinary_event_layout",
                ["soundbank", "directive", "resolved_identity", "filter_columns"],
            ),
            "reviewed SoundBank Definition TSV layout",
        ),
    ],
)
def test_core_soundbank_parser_rejects_guessed_fixture_or_file_layout(
    case_id: str,
    mutate: Any,
    message: str,
) -> None:
    row = _raw_case(case_id)
    mutate(row)

    with pytest.raises(EvalBundleV3Error, match=message):
        _parse_online_case(row, f"negative.{case_id}")
