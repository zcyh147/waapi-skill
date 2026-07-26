from __future__ import annotations

import json
from pathlib import Path

from tests.semantic.support.codex_eval_bundle_v3 import _parse_online_case


REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHORING_V3 = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "evals"
    / "online"
    / "version_specific"
    / "authoring.json"
)


def _rows_by_id() -> dict[str, dict]:
    payload = json.loads(AUTHORING_V3.read_text(encoding="utf-8"))
    return {row["id"]: row for row in payload["cases"]}


def test_conversion_rebuild_cases_have_executable_baselines_and_deltas() -> None:
    rows = _rows_by_id()
    baseline = rows["VS24-F-AUDIO-CONVERT-01"]["fixture"]["asset_spec"]
    stale = rows["VS24-F-AUDIO-CONVERT-04"]["fixture"]["asset_spec"]

    assert baseline["baseline_recipe"]["preconvert_objects"] == baseline["request"]["objects"]
    assert "delete exactly those six" in baseline["baseline_recipe"]["freshness_predicate"]
    assert "mtime_ns greater" in baseline["baseline_recipe"]["freshness_predicate"]

    assert stale["wav"]["count"] == 5
    assert [row["path"] for row in stale["control_bindings"]] == stale["control_objects"]
    assert {row["source_key"] for row in stale["control_bindings"]} == {
        "current_control",
        "untouched_decoy",
    }
    assert [row["kind"] for row in stale["delta_plan"]] == [
        "replace_source_bytes",
        "replace_effective_settings",
        "delete_converted_artifacts",
    ]
    assert {row["path"] for row in stale["delta_plan"]} == set(stale["request"]["objects"])
    assert stale["delta_plan"][0]["before"]["signal_seed"] != stale["delta_plan"][0]["after"]["signal_seed"]
    assert stale["delta_plan"][1]["before"]["Windows"] != stale["delta_plan"][1]["after"]["Windows"]
    assert stale["delta_plan"][2]["after"] == {
        "Windows": "exact_artifact_path_absent",
        "Mac": "exact_artifact_path_absent",
    }


def test_audio_convert_wording_uses_global_composite_conversion_sharesets() -> None:
    rows = _rows_by_id()
    cases = [rows[f"VS24-F-AUDIO-CONVERT-{index:02d}"] for index in range(1, 6)]
    expected_internal_component_names = {
        "VS24-F-AUDIO-CONVERT-01": {
            "SemanticLab_Weapons_Windows_PCM_48k",
            "SemanticLab_Weapons_Mac_Vorbis_48k",
        },
        "VS24-F-AUDIO-CONVERT-02": {"SemanticLab_Dialogue_Windows_Vorbis_48k"},
        "VS24-F-AUDIO-CONVERT-03": {
            "SemanticLab_Desktop_PCM_48k",
            "SemanticLab_Desktop_Vorbis_48k",
            "SemanticLab_Mobile_Vorbis_24k",
        },
        "VS24-F-AUDIO-CONVERT-04": {
            "SemanticLab_Windows_PCM_48k",
            "SemanticLab_Mac_Vorbis_48k",
            "SemanticLab_Windows_Vorbis_24k_Baseline",
            "SemanticLab_Mac_PCM_44k_Baseline",
        },
        "VS24-F-AUDIO-CONVERT-05": {
            "SemanticLab_Windows_PCM_48k",
            "SemanticLab_Mac_Vorbis_48k",
            "SemanticLab_Mac_ADPCM_48k",
        },
    }

    for case in cases:
        prerequisites = "\n".join(case["fixture"]["prerequisites"])
        oracle_text = "\n".join(
            assertion["expectation"] for assertion in case["oracle_assertions"]
        )
        dispatch_text = "\n".join(
            dispatch["effect"] for dispatch in case["expected_dispatches"]
        )
        public_text = "\n".join(
            (
                case["prompt"],
                case["confirmation_prompt"],
                prerequisites,
                dispatch_text,
                oracle_text,
            )
        )
        component_names = {
            row["name"] for row in case["fixture"]["asset_spec"]["conversion_settings"]
        }

        assert "Conversion ShareSet" in case["prompt"]
        assert "Conversion ShareSet" in case["confirmation_prompt"]
        assert "composite Conversion ShareSet" in prerequisites
        assert "Conversion ShareSet" in oracle_text
        assert component_names == expected_internal_component_names[case["id"]]
        assert all(name not in public_text for name in component_names)

    public_text = "\n".join(
        json.dumps(case, ensure_ascii=False) for case in cases
    )
    for misleading_phrase in (
        "现有三套平台设置",
        "独立 ADPCM 设置",
        "three declared conversion settings",
        "existing per-platform conversion settings",
        "Metal/Mac ADPCM override",
    ):
        assert misleading_phrase not in public_text

    weather = cases[2]
    assert "共同全局引用同一套 Conversion ShareSet" in weather["prompt"]
    assert "one composite Conversion ShareSet" in "\n".join(
        weather["fixture"]["prerequisites"]
    )

    stale = cases[3]
    assert "刚从旧复合 Conversion ShareSet" in stale["prompt"]
    assert "切换到当前 ShareSet" in stale["prompt"]
    assert "switch Changed_Setting exactly once" in "\n".join(
        stale["fixture"]["prerequisites"]
    )
    assert "through one global reference" in "\n".join(
        stale["fixture"]["prerequisites"]
    )

    collisions = cases[4]
    assert "全局引用同一套复合 Conversion ShareSet" in collisions["prompt"]
    assert "`Metal` 全局引用另一套复合 Conversion ShareSet" in collisions["prompt"]
    assert "second composite Conversion ShareSet" in "\n".join(
        collisions["fixture"]["prerequisites"]
    )


def test_audio_convert_confirmations_acknowledge_preview_limits_without_switching_project() -> None:
    rows = _rows_by_id()
    for scenario_id, current_project_label in (
        ("VS24-F-AUDIO-CONVERT-01", "当前打开的就是隔离工程"),
        ("VS24-F-AUDIO-CONVERT-02", "当前打开的就是工程副本"),
    ):
        confirmation = rows[scenario_id]["confirmation_prompt"]
        assert confirmation.startswith("明白这些核验限制。")
        assert current_project_label in confirmation
        assert "不需要切换项目" in confirmation
        assert "确认按现有预览" in confirmation


def test_media_pool_heavy_prompts_are_direct_and_discover_fields_internally() -> None:
    rows = _rows_by_id()
    cases = []
    for index in range(1, 6):
        row = rows[f"VS25-F-MEDIAPOOL-GET-{index:02d}"]
        cases.append(_parse_online_case(row, f"mediaPool.get[{index}]"))

    assert all(case.protocol == "single" for case in cases)
    assert all(case.confirmation_prompt is None for case in cases)
    assert all(not case.visible_inputs for case in cases)
    assert all("media_pool_fields" not in case.prompt for case in cases)
    assert all(
        any(
            dispatch.api == "ak.wwise.core.mediaPool.getFields" and dispatch.count == 1
            for dispatch in case.expected_dispatches
        )
        for case in cases
    )
    assert all(
        any(assertion.adapter == "semantic_answer_assertion" for assertion in case.oracle_assertions)
        for case in cases
    )
    assert all(
        not any(assertion.phase == "preview" for assertion in case.oracle_assertions)
        for case in cases
    )

    association = cases[3]
    assert any(
        dispatch.api == "ak.wwise.core.object.get"
        for dispatch in association.expected_dispatches
    )
    assert "searchText" not in rows[association.id]["fixture"]["asset_spec"]["request_template"]["args"]


def test_media_pool_get_fields_cases_are_also_direct_reads() -> None:
    rows = _rows_by_id()
    for index in range(1, 3):
        row = rows[f"VS25-F-MEDIAPOOL-GETFIELDS-{index:02d}"]
        case = _parse_online_case(row, f"mediaPool.getFields[{index}]")
        assert case.protocol == "single"
        assert case.confirmation_prompt is None
        assert not any(assertion.phase == "preview" for assertion in case.oracle_assertions)
        assert any(
            assertion.phase == "after" and assertion.adapter == "sandbox_unchanged_oracle"
            for assertion in case.oracle_assertions
        )
