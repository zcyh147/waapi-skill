from __future__ import annotations

from copy import deepcopy
import json
from collections import Counter
from pathlib import Path

import pytest

from tests.semantic.support.codex_audio_conversion_runtime_v3 import (
    ConversionPreset,
    derive_conversion_profiles,
)
from tests.semantic.support.codex_eval_bundle_v3 import (
    EvalBundleV3Error,
    SEQUENTIAL_CONFIRMATION_PROMPT,
    WEAK_ASSERTION_ADAPTERS,
    _archive_relative,
    _canonical_archive_relative,
    _parse_online_case,
    _safe_child,
    load_eval_bundle_v3,
)
from tests.semantic.render_v3_review import render_review
from wwise_waapi.builders.schema import validate_semantic_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_V3 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"
CORE_OBJECT_V3 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "online" / "2022.1" / "core_object.json"
OTHER_V3 = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "online" / "2022.1" / "other.json"
REQUEST_MAPPING_V3 = (
    REPO_ROOT / "skills" / "waapi-skill" / "evals" / "request_mapping_registry.json"
)
VERSION_SPECIFIC_AUTHORING_V3 = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "evals"
    / "online"
    / "version_specific"
    / "authoring.json"
)
DEBUG_LUA_V3 = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "evals"
    / "online"
    / "debug_lua.json"
)


def test_eval_bundle_relative_fields_share_portable_archive_parsing() -> None:
    parsed = _archive_relative(
        r"nested\素材.wav",
        "test.path",
        error="must be portable",
    )
    assert parsed.canonical == "nested/素材.wav"

    for relative in (
        r"nested\mixed/file.wav",
        "nested//file.wav",
        "nested/../file.wav",
        "nested/LPT1.wav",
    ):
        with pytest.raises(EvalBundleV3Error, match="must be portable"):
            _archive_relative(relative, "test.path", error="must be portable")

    assert _canonical_archive_relative(
        "nested/素材.wav",
        "test.path",
        error="must be canonical",
    ) == "nested/素材.wav"
    with pytest.raises(EvalBundleV3Error, match="must be canonical"):
        _canonical_archive_relative(
            r"nested\素材.wav",
            "test.path",
            error="must be canonical",
        )


@pytest.mark.parametrize(
    "relative",
    (
        "nested//case.json",
        "nested/./case.json",
        "nested/../case.json",
        r"nested\case.json",
        "nested/bad:name.json",
        "nested/CON.json",
    ),
)
def test_eval_bundle_child_path_reuses_portable_archive_boundary(
    tmp_path: Path,
    relative: str,
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "case.json").write_text("{}", encoding="utf-8")

    with pytest.raises(EvalBundleV3Error, match="contained relative path"):
        _safe_child(tmp_path, relative, "test.path")


def test_eval_bundle_child_path_accepts_canonical_posix_spelling(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    expected = nested / "case.json"
    expected.write_text("{}", encoding="utf-8")

    assert _safe_child(tmp_path, "nested/case.json", "test.path") == expected


def test_v3_bundle_covers_every_unique_five_version_api_with_reviewed_heavy_extensions() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)

    assert len(bundle.coverage) == 198
    assert len(bundle.scenarios) == 444
    assert Counter(row.item_type for row in bundle.coverage) == {
        "function": 165,
        "topic": 33,
    }
    assert Counter(row.scenario_count for row in bundle.coverage) == {2: 182, 5: 16}
    assert all(len(set(row.scenario_families)) == row.scenario_count for row in bundle.coverage)
    assert all(len(set(row.prompt_sha256)) == row.scenario_count for row in bundle.coverage)
    assert Counter(version for case in bundle.scenarios for version in case.versions) == {
        "2022.1": 326,
        "2023.1": 74,
        "2024.1": 27,
        "2025.1": 17,
    }

    cases_2022 = [case for case in bundle.scenarios if "2022.1" in case.versions]
    assert len(cases_2022) == 326
    assert len({case.api for case in cases_2022}) == 142
    assert Counter(case.protocol for case in cases_2022) == {
        "preview_confirm": 208,
        "single": 118,
    }
    assert sum(case.confirmation_turn_count for case in cases_2022) == 227
    assert len(cases_2022) + sum(
        case.confirmation_turn_count for case in cases_2022
    ) == 553


def test_v3_debug_and_lua_cases_close_protocol_acknowledgement_and_oracle_boundaries() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    payload = json.loads(DEBUG_LUA_V3.read_text(encoding="utf-8"))
    case_ids = {row["id"] for row in payload["cases"]}
    cases = [bundle.scenario(case_id) for case_id in case_ids]

    assert len(cases) == 20
    expected = {
        "ak.wwise.cli.executeLuaScript": ("2023.1", "preview_confirm"),
        "ak.wwise.core.executeLuaScript": ("2023.1", "preview_confirm"),
        "ak.wwise.debug.assertFailed": ("2022.1", "single"),
        "ak.wwise.debug.enableAsserts": ("2022.1", "preview_confirm"),
        "ak.wwise.debug.enableAutomationMode": ("2022.1", "preview_confirm"),
        "ak.wwise.debug.getWalTree": ("2023.1", "single"),
        "ak.wwise.debug.restartWaapiServers": ("2023.1", "preview_confirm"),
        "ak.wwise.debug.testAssert": ("2022.1", "preview_confirm"),
        "ak.wwise.debug.testCrash": ("2022.1", "preview_confirm"),
        "ak.wwise.debug.validateCall": ("2024.1", "single"),
    }
    for api, (version, protocol) in expected.items():
        selected = [case for case in cases if case.api == api]
        assert len(selected) == 2
        assert {case.scenario_index for case in selected} == {1, 2}
        assert len({case.scenario_family for case in selected}) == 2
        assert all(case.versions == (version,) for case in selected)
        assert all(case.protocol == protocol for case in selected)
        assert all(case.primary_dispatch.count == 1 for case in selected)
        assert all(not bundle.scenario_mapping_blockers(case.id) for case in selected)

    acknowledgement_by_api = {
        "ak.wwise.debug.restartWaapiServers": "restart_waapi_servers",
        "ak.wwise.debug.testAssert": "trigger_debug_assert",
        "ak.wwise.debug.testCrash": "crash_wwise_process",
    }
    for api, acknowledgement in acknowledgement_by_api.items():
        for case in (case for case in cases if case.api == api):
            assert acknowledgement in case.prompt
            assert case.confirmation_prompt
            assert any(
                assertion.phase == "preview" and assertion.subject_api == api
                for assertion in case.oracle_assertions
            )
            assert any(
                assertion.phase == "after"
                and assertion.adapter
                in {
                    "debug_assert_event_oracle",
                    "waapi_restart_oracle",
                    "wwise_process_termination_oracle",
                }
                for assertion in case.oracle_assertions
            )

    lua_cases = [
        case
        for case in cases
        if case.api
        in {"ak.wwise.cli.executeLuaScript", "ak.wwise.core.executeLuaScript"}
    ]
    assert all(
        {item.name for item in case.visible_inputs} == {"script_file", "io_root"}
        for case in lua_cases
    )
    assert all(
        any(
            phrase in case.prompt
            for phrase in ("不要改写", "保持源码不变", "保持原样", "源码不要改")
        )
        for case in lua_cases
    )
    assert all(
        any(
            assertion.phase == "after"
            and assertion.adapter == "lua_execution_oracle"
            for assertion in case.oracle_assertions
        )
        for case in lua_cases
    )

    mode_cases = [
        case
        for case in cases
        if case.api
        in {
            "ak.wwise.debug.enableAsserts",
            "ak.wwise.debug.enableAutomationMode",
        }
    ]
    assert "debug_mode_result_schema_boundary" in WEAK_ASSERTION_ADAPTERS
    assert all(
        any(
            assertion.phase == "after"
            and assertion.adapter == "debug_mode_result_schema_boundary"
            and (
                "不能" in assertion.expectation
                or "不得" in assertion.expectation
                or "无法" in assertion.expectation
                or "不把" in assertion.expectation
            )
            for assertion in case.oracle_assertions
        )
        for case in mode_cases
    )


def test_v3_heavy_object_create_and_set_have_five_closed_scenarios_each() -> None:
    payload = json.loads(CORE_OBJECT_V3.read_text(encoding="utf-8"))
    parsed = [
        _parse_online_case(row, f"core_object.cases[{index}]")
        for index, row in enumerate(payload["cases"])
    ]

    for api, prefix in (
        ("ak.wwise.core.object.create", "OBJ22-F-CREATE-"),
        ("ak.wwise.core.object.set", "OBJ22-F-SET-"),
    ):
        cases = [case for case in parsed if case.api == api]
        assert [case.id for case in cases] == [f"{prefix}{index:02d}" for index in range(1, 6)]
        assert [case.scenario_index for case in cases] == [1, 2, 3, 4, 5]
        assert len({case.scenario_family for case in cases}) == 5
        assert len({case.prompt for case in cases}) == 5
        assert all(case.primary_dispatch.count == 1 for case in cases)
        assert all(case.protocol == "preview_confirm" for case in cases)
        assert all(case.fixture["sandbox"] == "scenario_project_copy" for case in cases)
        assert len({tuple(case.fixture["prerequisites"]) for case in cases}) == 5
        assert all(
            "successful_case_project_copy_removed" in case.cleanup["postconditions"]
            and "failed_or_indeterminate_case_sandbox_sealed_and_never_reused"
            in case.cleanup["postconditions"]
            for case in cases
        )
        assert all(
            {assertion.phase for assertion in case.oracle_assertions}
            >= {"before", "preview", "after", "cleanup"}
            for case in cases
        )
        assert all(
            all(
                forbidden not in case.prompt.casefold()
                for forbidden in ("rtpc", "listmode", "replaceall", "平台联动", "插件")
            )
            for case in cases
        )
        assert all(
            any(
                assertion.phase == "cleanup"
                and "never reused" in assertion.expectation
                for assertion in case.oracle_assertions
            )
            for case in cases
        )


def test_v3_heavy_audio_imports_have_five_closed_scenarios_and_asset_oracles_each() -> None:
    other_payload = json.loads(OTHER_V3.read_text(encoding="utf-8"))
    raw_by_id = {row["id"]: row for row in other_payload["cases"]}
    import_rows = [
        row
        for row in other_payload["cases"]
        if row["id"].startswith(("O22-AUDIO-IMPORT-", "O22-AUDIO-TAB-"))
    ]
    parsed = [
        _parse_online_case(row, f"other.import.cases[{index}]")
        for index, row in enumerate(import_rows)
    ]
    parsed_by_id = {case.id: case for case in parsed}
    expected = {
        "ak.wwise.core.audio.import": {
            "prefix": "O22-AUDIO-IMPORT-",
            "operations": ["useExisting", "useExisting", "createNew", "replaceExisting", "createNew"],
            "dispatch_counts": [1, 1, 1, 1, 1],
            "tsv_counts": [0, 0, 0, 0, 0],
        },
        "ak.wwise.core.audio.importTabDelimited": {
            "prefix": "O22-AUDIO-TAB-",
            "operations": ["useExisting", "useExisting", "createNew", "useExisting", "replaceExisting"],
            "dispatch_counts": [0, 3, 1, 1, 1],
            "tsv_counts": [1, 3, 1, 1, 1],
        },
    }

    for api, specification in expected.items():
        cases = [case for case in parsed if case.api == api]
        assert [case.id for case in cases] == [
            f"{specification['prefix']}{index:02d}" for index in range(1, 6)
        ]
        assert [case.scenario_index for case in cases] == [1, 2, 3, 4, 5]
        assert len({case.scenario_family for case in cases}) == 5
        assert len({case.prompt for case in cases}) == 5
        assert [case.primary_dispatch.count for case in cases] == specification["dispatch_counts"]
        assert all(case.fixture["sandbox"] == "scenario_project_copy" for case in cases)
        assert all(
            {assertion.phase for assertion in case.oracle_assertions}
            >= {"before", "preview", "after", "cleanup"}
            for case in cases
        )
        assert all(
            "successful_case_project_copy_removed" in case.cleanup["postconditions"]
            and "failed_or_indeterminate_case_sandbox_sealed_and_never_reused"
            in case.cleanup["postconditions"]
            for case in cases
        )
        for case, operation, tsv_count in zip(
            cases,
            specification["operations"],
            specification["tsv_counts"],
            strict=True,
        ):
            asset_spec = case.fixture["asset_spec"]
            assert asset_spec["contract"] == "waapi-skill.import-eval-assets/v2"
            assert asset_spec["materialization_policy"] == (
                "generate_sources_then_seal_sha256_render_visible_rows_or_tsv_"
                "exactly_from_declared_order"
            )
            assert asset_spec["source_policy"] == "absolute_regular_non_symlink_size_sha256"
            assert asset_spec["cleanup_policy"] == (
                "success_delete_case_owned_project_and_assets_"
                "failure_or_indeterminate_seal_never_reuse"
            )
            assert asset_spec["wav"]["format"] == "pcm_s16le_mono_48000hz"
            assert asset_spec["wav"]["generator_policy"] == (
                "riff_wave_pcm_s16le_sine_phase0_peak8191_int_truncate_"
                "samples_floor_48000xms_div1000"
            )
            sources = asset_spec["sources"]
            pre_state_sources = asset_spec["pre_state_sources"]
            rows = asset_spec["rows"]
            assert sources and rows
            assert len(sources) == len(rows)
            assert asset_spec["wav"]["count"] == sum(
                source["presence"] == "present" for source in sources
            )
            assert len({source["source_key"] for source in sources}) == len(sources)
            assert len({source["relative_path"].casefold() for source in sources}) == len(sources)
            assert {source["source_key"] for source in sources} == {
                row["source_key"] for row in rows
            }
            assert {
                source["media_sha256_key"] for source in pre_state_sources
            } == {
                row["pre_state"]["media_sha256_key"]
                for row in rows
                if row["pre_state"]["existence"] == "existing"
            }
            assert len(
                {
                    source["relative_path"].casefold()
                    for source in [*sources, *pre_state_sources]
                }
            ) == len(sources) + len(pre_state_sources)
            assert len(
                {
                    (source["duration_ms"], source["frequency_hz"])
                    for source in [
                        *[source for source in sources if source["presence"] == "present"],
                        *pre_state_sources,
                    ]
                }
            ) == asset_spec["wav"]["count"] + len(pre_state_sources)
            assert all(
                set(source)
                == {
                    "source_key",
                    "relative_path",
                    "presence",
                    "duration_ms",
                    "frequency_hz",
                    "sha256_key",
                }
                for source in sources
            )
            assert all(
                set(source)
                == {"media_sha256_key", "relative_path", "duration_ms", "frequency_hz"}
                for source in pre_state_sources
            )
            assert all(
                set(row)
                == {
                    "row_key",
                    "tsv_name",
                    "tsv_row",
                    "source_key",
                    "object_key",
                    "object_path",
                    "target_path",
                    "object_type",
                    "language",
                    "originals_subfolder",
                    "notes",
                    "audio_source_notes",
                    "event",
                    "pre_state",
                    "guid_policy",
                    "oracle",
                }
                for row in rows
            )
            assert all(
                set(row["pre_state"])
                == {"existence", "guid_key", "media_sha256_key", "notes"}
                for row in rows
            )
            assert all(
                set(row["oracle"])
                == {
                    "target_cardinality",
                    "media_policy",
                    "language_policy",
                    "event_policy",
                }
                for row in rows
            )
            assert all(
                row["source_key"]
                and row["object_path"]
                and row["target_path"].startswith("\\Actor-Mixer Hierarchy\\")
                and row["object_type"]
                and row["language"]
                and "event" in row
                and row["guid_policy"]
                for row in rows
            )
            assert len(asset_spec["tsv"]) == tsv_count
            if api == "ak.wwise.core.audio.import":
                assert asset_spec["audio_import_operation"] == operation
                assert asset_spec["import_location"] is None
                assert all(row["tsv_name"] is None and row["tsv_row"] is None for row in rows)
            else:
                assert asset_spec["audio_import_operation"] is None
                assert asset_spec["import_location"].startswith("\\Actor-Mixer Hierarchy\\")
                assert {row["import_operation"] for row in asset_spec["tsv"]} == {operation}
                for template in asset_spec["tsv"]:
                    assert template["render_policy"] == "csv_tab_quote_minimal_doublequote_lf"
                    assert "Import Language" not in template["headers"]
                    assert "Originals Sub Folder" not in template["headers"]
                    assert set(template["headers"]).isdisjoint(
                        {"Event", "Switch Assignation", "Dialogue Event", "@Volume"}
                    )
                    table_rows = [row for row in rows if row["tsv_name"] == template["name"]]
                    assert [row["tsv_row"] for row in table_rows] == list(
                        range(2, template["row_count"] + 2)
                    )
            prompt = case.prompt.casefold()
            assert "cookie" not in prompt
            assert "switchassignation" not in prompt
            assert "dialogueevent" not in prompt
            assert "@" not in prompt
            assert raw_by_id[case.id]["fixture"]["asset_spec"] == asset_spec

    refusal = parsed_by_id["O22-AUDIO-TAB-01"]
    assert refusal.primary_dispatch.count == 0
    assert refusal.confirmation_prompt is None
    assert refusal.confirmation_turn_count == 0
    assert refusal.fixture["asset_spec"]["tsv"][0]["missing_audio_rows"] == [7]
    assert any("零" in assertion.expectation for assertion in refusal.oracle_assertions)

    multilingual = parsed_by_id["O22-AUDIO-TAB-02"]
    assert multilingual.primary_dispatch.count == 3
    assert multilingual.confirmation_prompt == SEQUENTIAL_CONFIRMATION_PROMPT
    assert [
        template["language"] for template in multilingual.fixture["asset_spec"]["tsv"]
    ] == ["Chinese", "English", "Japanese"]
    multilingual_spec = multilingual.fixture["asset_spec"]
    multilingual_rows = multilingual_spec["rows"]
    grouped_rows = {
        object_key: [row for row in multilingual_rows if row["object_key"] == object_key]
        for object_key in {row["object_key"] for row in multilingual_rows}
    }
    assert len(multilingual_rows) == 12
    assert len(multilingual_spec["sources"]) == 12
    assert set(grouped_rows) == {
        "m07_alpha_voice",
        "m07_bravo_voice",
        "m07_charlie_voice",
        "m07_delta_voice",
    }
    assert all(len(rows) == 3 for rows in grouped_rows.values())
    assert all(
        {row["language"] for row in rows} == {"Chinese", "English", "Japanese"}
        and len({row["target_path"] for row in rows}) == 1
        and {row["object_type"] for row in rows} == {"Sound Voice"}
        for rows in grouped_rows.values()
    )
    existing_groups = [
        rows
        for rows in grouped_rows.values()
        if rows[0]["pre_state"]["existence"] == "existing"
    ]
    absent_groups = [
        rows
        for rows in grouped_rows.values()
        if rows[0]["pre_state"]["existence"] == "absent"
    ]
    assert len(existing_groups) == 2
    assert len(absent_groups) == 2
    assert len(
        {rows[0]["pre_state"]["guid_key"] for rows in existing_groups}
    ) == 2
    assert all(
        {row["guid_policy"] for row in rows} == {"preserve_shared_existing_guid"}
        and len({row["pre_state"]["guid_key"] for row in rows}) == 1
        and len({row["pre_state"]["media_sha256_key"] for row in rows}) == 3
        for rows in existing_groups
    )
    assert all(
        {row["guid_policy"] for row in rows}
        == {"create_once_then_preserve_shared_guid"}
        and all(row["pre_state"]["guid_key"] is None for row in rows)
        for rows in absent_groups
    )
    assert all(
        row["oracle"]["media_policy"]
        == "copied_original_sha256_equals_source_sha256"
        and row["oracle"]["language_policy"]
        == "audio_file_source_language_equals_row_language"
        for row in multilingual_rows
    )

    unicode_case = parsed_by_id["O22-AUDIO-TAB-03"]
    unicode_rows = unicode_case.fixture["asset_spec"]["rows"]
    assert len(unicode_rows) == 8
    assert all(
        not any(separator in row["notes"] for separator in ("\t", "\r", "\n"))
        for row in unicode_rows
    )
    assert unicode_case.fixture["asset_spec"]["tsv"][0]["name"] == (
        "city_unicode_recursive.tsv"
    )
    assert unicode_case.fixture["asset_spec"]["tsv"][0]["render_policy"] == (
        "csv_tab_quote_minimal_doublequote_lf"
    )
    request_mapping = json.loads(REQUEST_MAPPING_V3.read_text(encoding="utf-8"))
    blocked_case_ids = {
        case_id
        for requirement in request_mapping["requirements"]
        if requirement["status"] != "closed"
        for case_id in requirement["case_ids"]
    }
    assert not blocked_case_ids.intersection(parsed_by_id)


def test_v3_import_asset_loader_rejects_unbound_rows_and_inferred_targets() -> None:
    payload = json.loads(OTHER_V3.read_text(encoding="utf-8"))
    original = next(row for row in payload["cases"] if row["id"] == "O22-AUDIO-IMPORT-01")

    unknown_source = deepcopy(original)
    unknown_source["fixture"]["asset_spec"]["rows"][0]["source_key"] = "undeclared_source"
    with pytest.raises(EvalBundleV3Error, match="unknown source"):
        _parse_online_case(unknown_source, "other.import.unknown_source")

    inferred_target = deepcopy(original)
    inferred_target["fixture"]["asset_spec"]["rows"][0]["target_path"] += "_guessed"
    with pytest.raises(EvalBundleV3Error, match="does not match the declared object path"):
        _parse_online_case(inferred_target, "other.import.inferred_target")

    unknown_pre_state_source = deepcopy(original)
    unknown_pre_state_source["fixture"]["asset_spec"]["rows"][0]["pre_state"][
        "media_sha256_key"
    ] = "undeclared_before_media_sha256"
    with pytest.raises(EvalBundleV3Error, match="unknown pre-state source"):
        _parse_online_case(
            unknown_pre_state_source,
            "other.import.unknown_pre_state_source",
        )

    incomplete_pre_state = deepcopy(original)
    del incomplete_pre_state["fixture"]["asset_spec"]["rows"][0]["pre_state"]["guid_key"]
    with pytest.raises(EvalBundleV3Error, match="pre_state fields mismatch"):
        _parse_online_case(incomplete_pre_state, "other.import.incomplete_pre_state")

    tab_original = next(
        row for row in payload["cases"] if row["id"] == "O22-AUDIO-TAB-03"
    )
    embedded_separator = deepcopy(tab_original)
    embedded_separator["fixture"]["asset_spec"]["rows"][0]["notes"] += "\t远景"
    with pytest.raises(EvalBundleV3Error, match="physical TSV separator"):
        _parse_online_case(
            embedded_separator,
            "other.import.embedded_tab_separator",
        )


def test_v3_heavy_soundbank_operations_have_five_closed_scenarios_and_asset_oracles_each() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    other_payload = json.loads(OTHER_V3.read_text(encoding="utf-8"))
    raw_by_id = {row["id"]: row for row in other_payload["cases"]}
    expected = {
        "ak.wwise.core.soundbank.generate": {
            "prefix": "O22-SB-GENERATE-",
            "operation": "generate",
            "dispatch_counts": [1, 1, 1, 1, 1],
        },
        "ak.wwise.core.soundbank.convertExternalSources": {
            "prefix": "O22-SB-CONVERT-EXT-",
            "operation": "convertExternalSources",
            "dispatch_counts": [1, 1, 1, 1, 1],
        },
        "ak.wwise.core.soundbank.processDefinitionFiles": {
            "prefix": "O22-SB-PROCESS-DEF-",
            "operation": "processDefinitionFiles",
            "dispatch_counts": [1, 1, 1, 1, 0],
        },
    }

    for api, specification in expected.items():
        cases = [case for case in bundle.scenarios if case.api == api]
        assert [case.id for case in cases] == [
            f"{specification['prefix']}{index:02d}" for index in range(1, 6)
        ]
        assert [case.scenario_index for case in cases] == [1, 2, 3, 4, 5]
        assert len({case.scenario_family for case in cases}) == 5
        assert len({case.prompt for case in cases}) == 5
        assert [case.primary_dispatch.count for case in cases] == specification["dispatch_counts"]
        assert all(case.protocol == "preview_confirm" for case in cases)
        assert all(case.fixture["sandbox"] == "scenario_project_copy" for case in cases)
        assert all(
            {assertion.phase for assertion in case.oracle_assertions}
            >= {"before", "preview", "after", "cleanup"}
            for case in cases
        )
        assert all(
            "failed_or_indeterminate_case_sandbox_sealed_and_never_reused"
            in case.cleanup["postconditions"]
            for case in cases
        )
        assert all(
            case.fixture["asset_spec"]["operation"] == specification["operation"]
            for case in cases
        )
        assert all(
            case.fixture["asset_spec"]["cleanup_policy"]
            == "case_owned_project_copy_discard"
            for case in cases
        )
        assert all(
            raw_by_id[case.id]["fixture"]["asset_spec"] == case.fixture["asset_spec"]
            for case in cases
        )

    generate_cases = [
        bundle.scenario(f"O22-SB-GENERATE-{index:02d}") for index in range(1, 6)
    ]
    for case in generate_cases:
        asset_spec = case.fixture["asset_spec"]
        request = asset_spec["request"]
        assert request["soundbanks"]
        assert request["platforms"]
        assert request["writeToDisk"] is True
        assert all(row["name"].casefold() != "init" for row in request["soundbanks"])
        assert asset_spec["expected_user_soundbanks"] == [
            row["name"] for row in request["soundbanks"]
        ]
        assert asset_spec["automatic_byproducts"] == ["Init.bnk"]
        if request["skipLanguages"]:
            assert "languages" not in request
        else:
            assert request["languages"]
        assert any(
            assertion.adapter == "filesystem_tree_oracle"
            and assertion.phase == "after"
            for assertion in case.oracle_assertions
        ) or case.id == "O22-SB-GENERATE-05"

    external_cases = [
        bundle.scenario(f"O22-SB-CONVERT-EXT-{index:02d}") for index in range(1, 6)
    ]
    for case in external_cases:
        asset_spec = case.fixture["asset_spec"]
        serialized = json.dumps(raw_by_id[case.id], ensure_ascii=False).casefold()
        assert "cookie" not in serialized
        assert asset_spec["documents"]
        assert asset_spec["jobs"]
        assert len({job["output_key"] for job in asset_spec["jobs"]}) == len(
            asset_spec["jobs"]
        )
        entries = [
            entry
            for document in asset_spec["documents"]
            for entry in document["entries"]
        ]
        assert len(entries) == asset_spec["wav"]["count"]
        assert all(entry["path"].casefold().endswith(".wav") for entry in entries)
        assert all(
            entry["destination"] is None
            or entry["destination"].casefold().endswith(".wem")
            for entry in entries
        )
        assert any(
            assertion.adapter == "external_source_output_oracle"
            and assertion.phase == "after"
            for assertion in case.oracle_assertions
        )

    definition_cases = [
        bundle.scenario(f"O22-SB-PROCESS-DEF-{index:02d}") for index in range(1, 6)
    ]
    identity_materialization = {
        "name": "runner_writes_double_quoted_literal_name",
        "guid": "runner_queries_guid",
        "decimal_short_id": "runner_queries_decimal_short_id",
        "hexadecimal_short_id": "runner_queries_hexadecimal_short_id",
    }
    for case in definition_cases:
        asset_spec = case.fixture["asset_spec"]
        assert all(file["name"].endswith(".tsv") for file in asset_spec["files"])
        assert asset_spec["expected_primary_dispatch_count"] == case.primary_dispatch.count
        rows = [row for file in asset_spec["files"] for row in file["rows"]]
        assert all(
            row["identity_materialization"]
            == identity_materialization[row["identity_format"]]
            for row in rows
        )
        resolutions = {
            row["resolution"]
            for row in rows
        }
        assert resolutions == ({"unknown"} if case.primary_dispatch.count == 0 else {"unique"})
        assert "soundbanksinfo" not in case.prompt.casefold()
        assert "xml" not in case.prompt.casefold()

    refusal = bundle.scenario("O22-SB-PROCESS-DEF-05")
    assert refusal.confirmation_prompt is None
    assert refusal.confirmation_turn_count == 0
    assert len(refusal.fixture["asset_spec"]["files"][0]["rows"]) == 1
    assert any(
        assertion.phase == "preview" and "零" in assertion.expectation
        for assertion in refusal.oracle_assertions
    )

    bad_generate = json.loads(json.dumps(raw_by_id["O22-SB-GENERATE-01"]))
    bad_generate["fixture"]["asset_spec"]["request"]["writeToDisk"] = False
    with pytest.raises(EvalBundleV3Error, match="writeToDisk must be true"):
        _parse_online_case(bad_generate, "bad_generate")

    bad_external = json.loads(json.dumps(raw_by_id["O22-SB-CONVERT-EXT-01"]))
    bad_external["fixture"]["asset_spec"]["documents"][0]["entries"][0]["cookie"] = 7
    with pytest.raises(EvalBundleV3Error, match="unknown=\\['cookie'\\]"):
        _parse_online_case(bad_external, "bad_external")

    bad_refusal = json.loads(json.dumps(raw_by_id["O22-SB-PROCESS-DEF-05"]))
    bad_refusal["fixture"]["asset_spec"]["files"][0]["rows"][0]["resolution"] = "unique"
    with pytest.raises(EvalBundleV3Error, match="only an independent unknown identity"):
        _parse_online_case(bad_refusal, "bad_refusal")


def test_v3_heavy_convert_and_media_pool_cases_have_closed_assets_and_terminal_cleanup() -> None:
    payload = json.loads(VERSION_SPECIFIC_AUTHORING_V3.read_text(encoding="utf-8"))
    raw_by_id = {row["id"]: row for row in payload["cases"]}
    parsed = [
        _parse_online_case(row, f"version_specific.authoring.cases[{index}]")
        for index, row in enumerate(payload["cases"])
    ]
    parsed_by_id = {case.id: case for case in parsed}
    lifecycle = {
        "ownership": "case_owned_project_and_asset_sandbox",
        "reuse_policy": "unique_per_scenario_execution",
        "success_policy": "delete_project_copy_and_all_owned_assets",
        "failure_policy": "seal_failed_or_indeterminate_sandbox_and_never_reuse",
    }
    terminal_postconditions = {
        "successful_case_project_copy_and_all_owned_assets_removed",
        "failed_or_indeterminate_case_sandbox_sealed_and_never_reused",
    }

    specifications = (
        (
            "ak.wwise.core.audio.convert",
            "VS24-F-AUDIO-CONVERT-",
            "2024.1",
            "isolated_io_root",
            "preview_confirm",
            [1, 1, 1, 1, 1],
            {"before", "preview", "after", "cleanup"},
        ),
        (
            "ak.wwise.core.mediaPool.get",
            "VS25-F-MEDIAPOOL-GET-",
            "2025.1",
            "scenario_project_copy",
            "single",
            [2, 2, 2, 3, 2],
            {"before", "after", "cleanup"},
        ),
    )
    for api, prefix, version, sandbox, protocol, dispatch_counts, required_phases in specifications:
        cases = [case for case in parsed if case.api == api]
        assert [case.id for case in cases] == [f"{prefix}{index:02d}" for index in range(1, 6)]
        assert [case.scenario_index for case in cases] == [1, 2, 3, 4, 5]
        assert len({case.scenario_family for case in cases}) == 5
        assert len({case.prompt for case in cases}) == 5
        assert all(case.versions == (version,) for case in cases)
        assert all(case.protocol == protocol for case in cases)
        assert all(case.primary_dispatch.count == 1 for case in cases)
        assert [len(case.expected_dispatches) for case in cases] == dispatch_counts
        assert all(case.fixture["sandbox"] == sandbox for case in cases)
        assert all(case.fixture["lifecycle"] == lifecycle for case in cases)
        assert all("asset_spec" in case.fixture for case in cases)
        assert all(
            {assertion.phase for assertion in case.oracle_assertions} >= required_phases
            for case in cases
        )
        assert all(
            terminal_postconditions <= set(case.cleanup["postconditions"])
            for case in cases
        )
        assert all(
            any(
                assertion.phase == "cleanup"
                and "on success" in assertion.expectation
                and "failure or indeterminate" in assertion.expectation
                and "never reused" in assertion.expectation
                for assertion in case.oracle_assertions
            )
            for case in cases
        )
        assert all(raw_by_id[case.id]["fixture"] == case.fixture for case in cases)

    convert_cases = [
        parsed_by_id[f"VS24-F-AUDIO-CONVERT-{index:02d}"]
        for index in range(1, 6)
    ]
    profile_counts: list[int] = []
    for case in convert_cases:
        asset_spec = case.fixture["asset_spec"]
        request = asset_spec["request"]
        validation = validate_semantic_payload(
            case.api,
            request,
            {},
            version="2024.1",
        )
        assert validation.section == "request"
        assert asset_spec["contract"] == "waapi-skill.audio-conversion-fixture/v1"
        assert asset_spec["expected_outputs"]["count"] == (
            len(request["objects"])
            * len(request["platforms"])
            * len(request["languages"])
        )
        assert set(request["objects"]).isdisjoint(asset_spec["control_objects"])
        assert asset_spec["output_policy"] == "case_owned_conversion_cache_tree"
        assert (
            asset_spec["cleanup_policy"]
            == "case_owned_project_copy_and_output_root_discard"
        )
        components = tuple(
            ConversionPreset(
                row["key"],
                row["name"],
                row["codec"],
                row["sample_rate"],
                row["channels"],
            )
            for row in asset_spec["conversion_settings"]
        )
        settings_maps = [
            tuple(
                (platform, binding["effective_settings"][platform])
                for platform in request["platforms"]
            )
            for binding in (
                asset_spec["object_bindings"]
                + asset_spec.get("control_bindings", [])
            )
        ]
        if case.id == "VS24-F-AUDIO-CONVERT-04":
            baseline = next(
                row
                for row in asset_spec["delta_plan"]
                if row["kind"] == "replace_effective_settings"
            )["before"]
            settings_maps.append(
                tuple(
                    (platform, baseline[platform])
                    for platform in request["platforms"]
                )
            )
        profiles = derive_conversion_profiles(
            scenario_id=case.id,
            platforms=tuple(request["platforms"]),
            presets=components,
            settings_maps=tuple(settings_maps),
        )
        profile_counts.append(len(profiles))
        component_by_key = {item.key: item for item in components}
        assert all(
            len(
                {
                    (
                        component_by_key[key].codec,
                        component_by_key[key].sample_rate,
                        component_by_key[key].channels,
                    )
                    for _platform, key in profile.components_by_platform
                }
            )
            == len(profile.components_by_platform)
            for profile in profiles
        )

    assert profile_counts == [1, 1, 1, 2, 2]

    media_cases = [
        parsed_by_id[f"VS25-F-MEDIAPOOL-GET-{index:02d}"]
        for index in range(1, 6)
    ]
    reflected_operators = {
        "equals",
        "notEquals",
        "contains",
        "startsWith",
        "endsWith",
        "matchesRegex",
        "lessThan",
        "greaterThan",
        "lessThanOrEqual",
        "greaterThanOrEqual",
    }
    for case in media_cases:
        asset_spec = case.fixture["asset_spec"]
        request = asset_spec["request_template"]
        validation = validate_semantic_payload(
            case.api,
            request["args"],
            request["options"],
            version="2025.1",
        )
        assert validation.section == "request"
        assert asset_spec["contract"] == "waapi-skill.media-pool-fixture/v1"
        assert set(request["args"]).isdisjoint({"offset", "page", "pageSize", "sort"})
        assert all(row["type"] == "field" for row in request["args"].get("filters", []))
        assert all(
            row["operator"] in reflected_operators
            for row in request["args"].get("filters", [])
        )
        assert request["args"]["maxResults"] >= len(asset_spec["expected_file_keys"])
        assert asset_spec["wav"]["count"] == len(asset_spec["rows"])
        assert (
            asset_spec["cleanup_policy"]
            == "case_owned_project_copy_and_media_databases_discard"
        )

    association = media_cases[3].fixture["asset_spec"]["association_expectations"]
    assert set(association["referenced"]) == {"used_dialogue", "used_foley"}
    assert set(association["unreferenced"]) == {"unused_roomtone", "unused_alt"}

    case01_spec = media_cases[0].fixture["asset_spec"]
    assert case01_spec["request_template"]["post_filter"] == {
        "field": "{media_pool_fields.name}",
        "operator": "containsCaseSensitive",
        "value": "footstep",
        "limit": 20,
    }
    assert case01_spec["expected_candidate_file_keys"] == [
        "footstep_gravel_short",
        "footstep_wood_short",
        "uppercase_name_decoy",
    ]
    assert case01_spec["expected_file_keys"] == [
        "footstep_gravel_short",
        "footstep_wood_short",
    ]
    assert all(
        case.fixture["asset_spec"].get("expected_candidate_file_keys") is None
        for case in media_cases[1:]
    )

    missing_candidates = deepcopy(raw_by_id["VS25-F-MEDIAPOOL-GET-01"])
    del missing_candidates["fixture"]["asset_spec"][
        "expected_candidate_file_keys"
    ]
    with pytest.raises(EvalBundleV3Error, match="required with post_filter"):
        _parse_online_case(missing_candidates, "missing_candidates")

    detached_post_filter = deepcopy(raw_by_id["VS25-F-MEDIAPOOL-GET-01"])
    detached_post_filter["fixture"]["asset_spec"]["request_template"][
        "post_filter"
    ]["value"] = "different"
    with pytest.raises(EvalBundleV3Error, match="complete server candidate request"):
        _parse_online_case(detached_post_filter, "detached_post_filter")

    candidates_without_filter = deepcopy(raw_by_id["VS25-F-MEDIAPOOL-GET-02"])
    candidates_without_filter["fixture"]["asset_spec"][
        "expected_candidate_file_keys"
    ] = ["vo_menu_48k_mono", "vo_quest_48k_mono", "vo_rate_decoy"]
    with pytest.raises(EvalBundleV3Error, match="must equal expected_file_keys"):
        _parse_online_case(candidates_without_filter, "candidates_without_filter")

    bad_lifecycle = json.loads(json.dumps(raw_by_id["VS24-F-AUDIO-CONVERT-01"]))
    del bad_lifecycle["fixture"]["lifecycle"]["failure_policy"]
    with pytest.raises(EvalBundleV3Error, match="lifecycle"):
        _parse_online_case(bad_lifecycle, "bad_lifecycle")


def test_v3_heavy_soundbank_inclusions_and_generated_topic_have_five_closed_scenarios_each() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    other_payload = json.loads(OTHER_V3.read_text(encoding="utf-8"))
    raw_by_id = {row["id"]: row for row in other_payload["cases"]}

    inclusion_cases = [
        bundle.scenario(f"O22-SB-SET-INCLUSIONS-{index:02d}")
        for index in range(1, 6)
    ]
    assert [case.scenario_index for case in inclusion_cases] == [1, 2, 3, 4, 5]
    assert len({case.scenario_family for case in inclusion_cases}) == 5
    assert len({case.prompt for case in inclusion_cases}) == 5
    assert [case.fixture["asset_spec"]["mode"] for case in inclusion_cases] == [
        "replace",
        "add",
        "remove",
        "replace",
        "add",
    ]
    assert all(case.primary_dispatch.count == 1 for case in inclusion_cases)
    assert all(case.protocol == "preview_confirm" for case in inclusion_cases)
    assert all(case.fixture["sandbox"] == "scenario_project_copy" for case in inclusion_cases)
    assert all(
        {assertion.phase for assertion in case.oracle_assertions}
        >= {"before", "preview", "after", "cleanup"}
        for case in inclusion_cases
    )
    assert all(
        any(
            assertion.phase == "after"
            and assertion.adapter == "waapi_soundbank_inclusion_oracle"
            for assertion in case.oracle_assertions
        )
        for case in inclusion_cases
    )
    assert all(
        "failed_or_indeterminate_case_sandbox_sealed_and_never_reused"
        in case.cleanup["postconditions"]
        for case in inclusion_cases
    )
    assert inclusion_cases[3].fixture["asset_spec"]["requested"] == []
    assert inclusion_cases[3].fixture["asset_spec"]["expected_after"] == []
    assert inclusion_cases[1].fixture["asset_spec"]["before"][0]["filters"] == ["events"]
    assert inclusion_cases[1].fixture["asset_spec"]["expected_after"][0]["filters"] == [
        "events",
        "structures",
        "media",
    ]

    topic_cases = [
        bundle.scenario(f"O22-SB-GENERATED-{index:02d}")
        for index in range(1, 6)
    ]
    assert [case.scenario_index for case in topic_cases] == [1, 2, 3, 4, 5]
    assert len({case.scenario_family for case in topic_cases}) == 5
    assert len({case.prompt for case in topic_cases}) == 5
    assert [case.primary_dispatch.count for case in topic_cases] == [3, 3, 2, 4, 1]
    assert all(case.protocol == "single" for case in topic_cases)
    assert all(case.confirmation_prompt is None for case in topic_cases)
    assert all(case.fixture["sandbox"] == "scenario_project_copy" for case in topic_cases)
    assert all(
        {assertion.phase for assertion in case.oracle_assertions}
        >= {"before", "preview", "event", "after", "cleanup"}
        for case in topic_cases
    )
    assert all(
        case.trigger is not None
        and case.trigger["publisher_api"] == "ak.wwise.core.soundbank.generate"
        and "fresh" in case.trigger["ownership_assertion"].casefold()
        and "wait" in case.trigger["ownership_assertion"].casefold()
        for case in topic_cases
    )
    assert all(
        "memory" not in case.prompt.casefold()
        and "runner" not in case.prompt.casefold()
        for case in topic_cases
    )
    assert all(
        "subscription_removed" in case.cleanup["postconditions"]
        and "failed_or_indeterminate_case_sandbox_sealed_and_never_reused"
        in case.cleanup["postconditions"]
        for case in topic_cases
    )
    for case in topic_cases:
        asset_spec = case.fixture["asset_spec"]
        expected_events = [
            event
            for request in asset_spec["publisher_requests"]
            for event in request["expected_events"]
        ]
        assert asset_spec["expected_topic_event_count"] == len(expected_events)
        assert asset_spec["expected_topic_event_count"] == case.primary_dispatch.count
        assert all(request["writeToDisk"] is True for request in asset_spec["publisher_requests"])
        assert all(
            bank["name"].casefold() != "init"
            for request in asset_spec["publisher_requests"]
            for bank in request["soundbanks"]
        )
        assert raw_by_id[case.id]["fixture"]["asset_spec"] == asset_spec

    localized = topic_cases[1].fixture["asset_spec"]["publisher_requests"][0]
    assert localized["languages"] == ["Chinese", "English", "Japanese"]
    assert {event["language"] for event in localized["expected_events"]} == {
        "Chinese",
        "English",
        "Japanese",
    }
    for case_id in ("O22-SB-GENERATE-02", "O22-SB-GENERATED-02"):
        fixture = bundle.scenario(case_id).fixture["asset_spec"]["fixture_manifest"]
        bank = fixture["soundbanks"][0]
        for event in bank["events"]:
            rows = [row for row in bank["media"] if row["event"] == event["name"]]
            assert len({row["object_path"] for row in rows}) == 1
            assert [
                (row["language"], row["import_operation"], row["create_event"])
                for row in rows
            ] == [
                ("Chinese", "createNew", True),
                ("English", "useExisting", False),
                ("Japanese", "useExisting", False),
            ]
    matrix = topic_cases[3].fixture["asset_spec"]["publisher_requests"][0]
    assert len(matrix["soundbanks"]) == 2
    assert matrix["platforms"] == ["Windows", "Mac"]
    assert len(matrix["expected_events"]) == 4

    bad_remove = json.loads(json.dumps(raw_by_id["O22-SB-SET-INCLUSIONS-03"]))
    bad_remove["fixture"]["asset_spec"]["requested"][0]["filters"] = ["events"]
    with pytest.raises(EvalBundleV3Error, match="must exactly match the before filter row"):
        _parse_online_case(bad_remove, "bad_remove")

    bad_topic_matrix = json.loads(json.dumps(raw_by_id["O22-SB-GENERATED-04"]))
    bad_topic_matrix["fixture"]["asset_spec"]["publisher_requests"][0][
        "expected_events"
    ].pop()
    bad_topic_matrix["fixture"]["asset_spec"]["expected_topic_event_count"] = 3
    with pytest.raises(EvalBundleV3Error, match="must equal the explicit bank/platform/language scope"):
        _parse_online_case(bad_topic_matrix, "bad_topic_matrix")

    bad_logical_path = deepcopy(raw_by_id["O22-SB-GENERATE-02"])
    bad_logical_path["fixture"]["asset_spec"]["fixture_manifest"]["soundbanks"][0][
        "media"
    ][2]["object_path"] = (
        r"\Actor-Mixer Hierarchy\Default Work Unit\generate_dialogue_chapter11_localized\Different_Greeting"
    )
    with pytest.raises(
        EvalBundleV3Error,
        match="must map one logical Sound across every requested language",
    ):
        _parse_online_case(bad_logical_path, "bad_logical_path")

    bad_reuse = deepcopy(raw_by_id["O22-SB-GENERATED-02"])
    bad_reuse["fixture"]["asset_spec"]["fixture_manifest"]["soundbanks"][0][
        "media"
    ][4]["import_operation"] = "createNew"
    with pytest.raises(
        EvalBundleV3Error,
        match="must create its first-language Sound/Event once",
    ):
        _parse_online_case(bad_reuse, "bad_reuse")


def test_v3_mutations_have_natural_confirmation_and_strong_state_oracle() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)

    mutation_cases = [case for case in bundle.scenarios if case.protocol == "preview_confirm"]
    assert mutation_cases
    for case in mutation_cases:
        if case.primary_dispatch.count == 0:
            assert case.confirmation_prompt is None
            assert case.confirmation_turn_count == 0
        else:
            assert case.confirmation_prompt
            assert "transaction" not in case.confirmation_prompt.lower()
            assert "hash" not in case.confirmation_prompt.lower()
        assert any(
            assertion.subject_api == case.api and assertion.phase in {"before", "preview"}
            for assertion in case.oracle_assertions
        )
        assert any(
            assertion.subject_api == case.api and assertion.phase == "after"
            for assertion in case.oracle_assertions
        )


def test_v3_multi_call_mutations_confirm_each_current_preview_separately() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    multi_call = [
        case
        for case in bundle.scenarios
        if case.protocol == "preview_confirm" and case.primary_dispatch.count > 1
    ]

    assert len(multi_call) == 30
    assert sum(case.primary_dispatch.count - 1 for case in multi_call) == 37
    assert len([case for case in multi_call if "2022.1" in case.versions]) == 16
    assert all(
        case.confirmation_prompt == SEQUENTIAL_CONFIRMATION_PROMPT
        for case in multi_call
    )
    assert all(
        case.confirmation_turn_count == case.primary_dispatch.count
        for case in multi_call
    )


def test_v3_batch_capable_complex_requests_use_one_primary_dispatch() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)

    for case_id in (
        "RT-PROF-CONTRIB-02",
        "O22-CLI-CONVERT-EXTERNAL-02",
        "O22-SB-CONVERT-EXT-02",
        "O22-UI-COMMANDS-UNREGISTER-01",
    ):
        assert bundle.scenario(case_id).primary_dispatch.count == 1


def test_v3_2022_cli_external_source_cases_bind_one_manifest_per_platform() -> None:
    payload = json.loads(OTHER_V3.read_text(encoding="utf-8"))
    raw_by_id = {row["id"]: row for row in payload["cases"]}
    case = _parse_online_case(
        raw_by_id["O22-CLI-CONVERT-EXTERNAL-04"],
        "bulk_union",
    )

    request = case.fixture["asset_spec"]["request"]
    assert request["source_mode"] == "source_file"
    assert request["bindings"] == [
        {"platform": "Windows", "manifests": ["bulk_union.wsources"]},
        {"platform": "Mac", "manifests": ["bulk_union.wsources"]},
    ]

    unsupported = deepcopy(raw_by_id["O22-CLI-CONVERT-EXTERNAL-04"])
    second_manifest = deepcopy(
        unsupported["fixture"]["asset_spec"]["assets"]["wsources"][0]
    )
    second_manifest["name"] = "second.wsources"
    second_manifest["entries"] = [
        {
            "path": "second.wav",
            "conversion": None,
            "destination": "4999.wav",
            "analysis_types": 4,
        }
    ]
    unsupported["fixture"]["asset_spec"]["assets"]["wsources"].append(
        second_manifest
    )
    unsupported["fixture"]["asset_spec"]["assets"]["wav"]["files"].append(
        {
            "key": "second",
            "name": "second.wav",
            "duration_ms": 480,
            "frequency_hz": 251,
        }
    )
    unsupported["fixture"]["asset_spec"]["request"]["bindings"][0][
        "manifests"
    ].append("second.wsources")
    with pytest.raises(EvalBundleV3Error, match="exactly one .wsources"):
        _parse_online_case(unsupported, "unsupported_multi_manifest")


def test_v3_topics_have_runner_owned_triggers_and_event_oracles() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    topic_cases = [case for case in bundle.scenarios if case.item_type == "topic"]

    assert len(topic_cases) == 69
    for case in topic_cases:
        assert case.trigger is not None
        assert case.trigger["ownership_assertion"]
        assert any(
            assertion.subject_api == case.api and assertion.phase == "event"
            for assertion in case.oracle_assertions
        )

    repeated_waits = {
        case.id: next(
            dispatch.count
            for dispatch in case.expected_dispatches
            if dispatch.api == case.api
        )
        for case in topic_cases
        if next(
            dispatch.count
            for dispatch in case.expected_dispatches
            if dispatch.api == case.api
        )
        > 1
    }
    assert repeated_waits == {
        "O22-SB-GENERATED-01": 3,
        "O22-SB-GENERATED-02": 3,
        "O22-SB-GENERATED-03": 2,
        "O22-SB-GENERATED-04": 4,
        "O22-SW-ADDED-TOPIC-01": 2,
        "O22-SW-ADDED-TOPIC-02": 2,
        "O22-SW-REMOVED-TOPIC-01": 2,
        "RT-TOPIC-CAPTURE-LOG-01": 2,
        "RT-TOPIC-GAMEOBJ-REGISTERED-01": 3,
        "RT-TOPIC-GAMEOBJ-REGISTERED-02": 2,
        "RT-TOPIC-STATE-CHANGED-02": 2,
        "RT-TOPIC-SWITCH-CHANGED-02": 2,
        "RT-TOPIC-TRANSPORT-STATE-01": 3,
        "RT-TOPIC-TRANSPORT-STATE-02": 2,
    }
    for case in topic_cases:
        if case.id in repeated_waits:
            assert "wait" in case.trigger["ownership_assertion"].lower()


def test_v3_visible_prompt_inputs_render_without_hidden_template_fields() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    cases_with_inputs = [case for case in bundle.scenarios if case.visible_inputs]

    assert len(cases_with_inputs) == 218
    assert sum(len(case.visible_inputs) for case in cases_with_inputs) == 328

    for case in bundle.scenarios:
        values = {item.name: f"VISIBLE_{item.name}" for item in case.visible_inputs}
        rendered = case.render_prompt(values)
        assert "{" not in rendered
        assert "}" not in rendered


def test_v3_empty_payload_topics_do_not_ask_the_event_for_missing_fields() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)

    for case_id in ("RT-TOPIC-GAMEOBJ-RESET-01", "RT-TOPIC-GAMEOBJ-RESET-02"):
        case = bundle.scenario(case_id)
        assert [item.api for item in case.expected_dispatches] == [case.api]
        assert any(
            assertion.adapter == "waapi_profiler_readback"
            and assertion.phase == "after"
            for assertion in case.oracle_assertions
        )

    for case_id in ("O22-PROJECT-LOADED-01", "O22-PROJECT-LOADED-02"):
        case = bundle.scenario(case_id)
        assert "ak.wwise.core.getProjectInfo" in {
            item.api for item in case.expected_dispatches
        }

    for case_id in ("O22-PROJECT-POST-CLOSED-01", "O22-PROJECT-POST-CLOSED-02"):
        case = bundle.scenario(case_id)
        assert "ak.wwise.core.getProjectInfo" in {
            item.api for item in case.expected_dispatches
        }

    for case_id in ("O22-PROJECT-PRE-CLOSED-01", "O22-PROJECT-PRE-CLOSED-02"):
        prompt = bundle.scenario(case_id).prompt
        assert "未保存对象数量" not in prompt
        assert "通知里的工程路径" not in prompt


def test_v3_object_created_wait_does_not_publish_an_unfilterable_decoy_first() -> None:
    case = load_eval_bundle_v3(SUITE_V3).scenario("OBJ22-T-CREATED-02")

    assert case.trigger is not None
    assert "decoy" not in case.trigger["ownership_assertion"].lower()
    assert "exactly one" in case.trigger["ownership_assertion"].lower()


def test_v3_source_control_array_requests_are_one_batch_dispatch() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    batch_apis = {
        "ak.wwise.core.sourceControl.add",
        "ak.wwise.core.sourceControl.checkOut",
        "ak.wwise.core.sourceControl.commit",
        "ak.wwise.core.sourceControl.delete",
        "ak.wwise.core.sourceControl.getStatus",
        "ak.wwise.core.sourceControl.move",
        "ak.wwise.core.sourceControl.revert",
    }
    source_control_cases = [
        case
        for case in bundle.scenarios
        if case.api in batch_apis
    ]

    assert source_control_cases
    for case in source_control_cases:
        primary = next(
            item for item in case.expected_dispatches if item.api == case.api
        )
        assert primary.count == 1


def test_v3_capture_screen_cases_validate_returned_image_instead_of_a_fake_save() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)

    for case_id in ("O22-UI-CAPTURE-01", "O22-UI-CAPTURE-02"):
        case = bundle.scenario(case_id)
        assert "不需要保存文件" in case.prompt
        expectations = " ".join(
            assertion.expectation for assertion in case.oracle_assertions
        )
        assert "contentType" in expectations
        assert "contentBase64" in expectations


def test_v3_project_save_prompts_only_claim_model_observable_work() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)

    for case_id in ("O22-PROJECT-SAVE-01", "O22-PROJECT-SAVE-02"):
        prompt = bundle.scenario(case_id).prompt
        assert "不需要关闭或重新打开工程" in prompt or "不要关闭或重新打开工程" in prompt

    for case_id in ("O22-PROJECT-SAVED-01", "O22-PROJECT-SAVED-02"):
        case = bundle.scenario(case_id)
        assert "已修改文件路径" in case.prompt
        assert any(
            "modifiedPaths" in assertion.expectation
            for assertion in case.oracle_assertions
        )


def test_v3_repaired_file_and_audio_oracles_claim_only_independent_evidence() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)

    for case_id in ("VS23-PROF-SAVE-CAPTURE-01", "VS23-PROF-SAVE-CAPTURE-02"):
        expectations = " ".join(
            assertion.expectation for assertion in bundle.scenario(case_id).oracle_assertions
        )
        assert "Capture Log" not in expectations
        assert "重新加载" in expectations
        assert "RTPC" in expectations

    for case_id in ("VS23-TRANSPORT-ORIGINALS-01", "VS23-TRANSPORT-ORIGINALS-02"):
        expectations = " ".join(
            assertion.expectation for assertion in bundle.scenario(case_id).oracle_assertions
        )
        assert "WAV" not in expectations
        assert "WEM" not in expectations
        assert "loopback PCM" in expectations

    dump_expectations = " ".join(
        assertion.expectation
        for assertion in bundle.scenario("O22-CLI-DUMP-OBJECTS-02").oracle_assertions
    )
    assert "duplicate 集合为空" in dump_expectations
    assert "type-mismatch 集合为空" in dump_expectations


def test_v3_offline_cases_are_named_separately_and_receive_no_coverage_credit() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)

    assert bundle.offline_path.name == "offline_tests.json"
    assert bundle.online_path.name == "online_tests.json"
    assert bundle.adapter_registry_path.name == "adapter_registry.json"
    assert bundle.request_mapping_registry_path.name == "request_mapping_registry.json"
    assert bundle.adapter_implementation_status == "specification_only_pending_user_review"
    assert len(bundle.offline_cases) == 12
    assert all("no_live_wwise_connection" in case.assertions for case in bundle.offline_cases)


def test_v3_unresolved_request_mappings_fail_closed_before_real_execution() -> None:
    bundle = load_eval_bundle_v3(SUITE_V3)
    blocked = {
        case.id
        for case in bundle.scenarios
        if bundle.scenario_mapping_blockers(case.id)
    }

    assert bundle.request_mapping_implementation_status == "specification_only_unresolved"
    assert len(bundle.request_mapping_requirements) == 14
    assert len(blocked) == 35
    assert len({bundle.scenario(case_id).api for case_id in blocked}) == 21
    assert {
        requirement.id
        for requirement in bundle.scenario_mapping_blockers("RT-SE-EXECUTE-ACTION-01")
    } == {
        "soundengine.action_on_event_type",
        "soundengine.fade_curve",
    }
    assert {
        requirement.id
        for requirement in bundle.scenario_mapping_blockers("RT-SE-MULTI-POSITIONS-01")
    } == {
        "soundengine.multi_position_type",
        "soundengine.position_array",
    }


def test_v3_loader_fails_closed_when_a_case_file_is_missing(tmp_path: Path) -> None:
    manifest = tmp_path / "suite-v3.json"
    manifest.write_text(SUITE_V3.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "online_tests.json").write_text(
        (SUITE_V3.parent / "online_tests.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "offline_tests.json").write_text(
        (SUITE_V3.parent / "offline_tests.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "adapter_registry.json").write_text(
        (SUITE_V3.parent / "adapter_registry.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "request_mapping_registry.json").write_text(
        (SUITE_V3.parent / "request_mapping_registry.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvalBundleV3Error, match="online/2022.1/core_object.json"):
        load_eval_bundle_v3(manifest)


def test_v3_review_renderer_can_select_one_case_without_live_execution() -> None:
    rendered = render_review(SUITE_V3, case_id="OBJ22-F-COPY-01")

    assert "Online scenarios: 1" in rendered
    assert "OBJ22-F-COPY-01" in rendered
    assert "Expected model dispatches:" in rendered
    assert "Cleanup postconditions:" in rendered
    assert "OBJ22-F-COPY-02" not in rendered

    summary = render_review(SUITE_V3, case_id="OBJ22-F-COPY-01", summary_only=True)
    assert "| 1 |" in summary


def test_v3_review_renderer_rejects_unknown_filters() -> None:
    with pytest.raises(EvalBundleV3Error, match="no v3 online scenarios"):
        render_review(SUITE_V3, case_id="DOES-NOT-EXIST")
