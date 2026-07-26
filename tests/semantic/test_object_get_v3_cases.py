from __future__ import annotations

import json
from pathlib import Path

from tests.semantic.support.codex_eval_bundle_v3 import (
    _parse_online_case,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_OBJECT_V3 = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "evals"
    / "online"
    / "2022.1"
    / "core_object.json"
)
OBJECT_GET_URI = "ak.wwise.core.object.get"


def _object_get_cases():
    payload = json.loads(CORE_OBJECT_V3.read_text(encoding="utf-8"))
    return [
        _parse_online_case(row, f"core_object.cases[{index}]")
        for index, row in enumerate(payload["cases"])
        if row["api"] == OBJECT_GET_URI
    ]


def test_v3_heavy_object_get_has_five_distinct_natural_scenarios() -> None:
    cases = _object_get_cases()

    assert [case.id for case in cases] == [
        f"OBJ22-F-GET-{index:02d}" for index in range(1, 6)
    ]
    assert [case.scenario_index for case in cases] == [1, 2, 3, 4, 5]
    assert len({case.scenario_family for case in cases}) == 5
    assert len({case.prompt for case in cases}) == 5
    assert all(case.protocol == "single" for case in cases)
    assert all(case.confirmation_prompt is None for case in cases)
    assert all(case.primary_dispatch.count == 1 for case in cases)
    assert all(case.fixture["adapter"] == "core_object_query_fixture" for case in cases)
    assert all(case.fixture["sandbox"] == "scenario_project_copy" for case in cases)
    assert all(
        forbidden not in case.prompt.casefold()
        for case in cases
        for forbidden in (
            "gateway",
            "runner",
            "fixture",
            "sandbox",
            "oracle",
            "skill 边界",
            "必须遵守",
        )
    )


def test_v3_object_get_depth_bound_has_a_true_match_decoy() -> None:
    case = {case.id: case for case in _object_get_cases()}["OBJ22-F-GET-01"]
    prerequisites = " ".join(case.fixture["prerequisites"])
    assertions = " ".join(item.expectation for item in case.oracle_assertions)

    assert "depth-four Sound" in prerequisites
    assert "depth-four decoy GUID" in prerequisites
    assert "depth-four true-match decoy GUID" in assertions
    assert "depth-four decoy GUID is absent" in assertions


def test_v3_bounded_superset_prompts_expose_their_24_row_limit() -> None:
    cases = {case.id: case for case in _object_get_cases()}

    for case_id in ("OBJ22-F-GET-01", "OBJ22-F-GET-02"):
        prompt = cases[case_id].prompt
        assert "最多返回 24 条候选记录" in prompt
        assert "达到上限" in prompt
        assert "结果可能不完整" in prompt


def test_v3_object_set_semitones_bind_to_exact_2022_pitch_cents() -> None:
    payload = json.loads(CORE_OBJECT_V3.read_text(encoding="utf-8"))
    row = next(item for item in payload["cases"] if item["id"] == "OBJ22-F-SET-03")
    case = _parse_online_case(row, "core_object.OBJ22-F-SET-03")
    prerequisites = " ".join(case.fixture["prerequisites"])
    after = " ".join(
        item.expectation for item in case.oracle_assertions if item.phase == "after"
    )

    assert "Pitch property metadata" in prerequisites
    assert "Day=100, Night=-100, Storm=-200" in prerequisites
    assert "100/-100/-200 cents" in case.primary_dispatch.effect
    assert "raw Pitch equals exactly 100/-100/-200 cents" in after


def test_v3_new_object_get_cases_close_bounds_fixtures_oracles_and_cleanup() -> None:
    cases = {case.id: case for case in _object_get_cases()}
    expected = {
        "OBJ22-F-GET-03": {
            "prompt_fragments": ("全部后代", "同时满足", "最多取 12 条", "按 Output Bus 汇总"),
            "effect_fragments": ("select descendants", "type/Volume/notes/isIncluded", "12"),
            "relation_fragment": "OutputBus GUID count buckets",
            "answer_fragment": "5-to-3",
        },
        "OBJ22-F-GET-04": {
            "prompt_fragments": ("反查直接父级", "至少有 3 个", "最多返回 10 个", "结果要去重"),
            "effect_fragments": ("select each direct parent", "path/type/childrenCount/notes", "10"),
            "relation_fragment": "Sound-to-parent GUID edges",
            "answer_fragment": "three unique parents and twelve direct Sound children",
        },
        "OBJ22-F-GET-05": {
            "prompt_fragments": ("归属链", "排除 Project", "最多查 8 层", "按类型汇总"),
            "effect_fragments": ("select ancestors", "exclude Project", "8"),
            "relation_fragment": "direct-parent edges",
            "answer_fragment": "RandomSequenceContainer/ActorMixer/WorkUnit",
        },
    }

    for case_id, specification in expected.items():
        case = cases[case_id]
        assert all(fragment in case.prompt for fragment in specification["prompt_fragments"])
        assert all(
            fragment in case.primary_dispatch.effect
            for fragment in specification["effect_fragments"]
        )

        prerequisites = tuple(case.fixture["prerequisites"])
        assert len(prerequisites) == 3
        joined_prerequisites = " ".join(prerequisites)
        assert "decoy" in joined_prerequisites
        assert "path-to-GUID" in joined_prerequisites
        assert specification["relation_fragment"] in joined_prerequisites
        assert "source-project hashes" in joined_prerequisites

        assertions_by_phase = {
            phase: [
                assertion.expectation
                for assertion in case.oracle_assertions
                if assertion.phase == phase
            ]
            for phase in ("before", "after", "cleanup")
        }
        assert assertions_by_phase["before"]
        assert len(assertions_by_phase["after"]) == 2
        assert assertions_by_phase["cleanup"]
        before = " ".join(assertions_by_phase["before"])
        readback = next(
            assertion.expectation
            for assertion in case.oracle_assertions
            if assertion.adapter == "waapi_object_query_readback"
        )
        answer = next(
            assertion.expectation
            for assertion in case.oracle_assertions
            if assertion.adapter == "semantic_answer_assertion"
        )
        cleanup = " ".join(assertions_by_phase["cleanup"])
        assert "GUID" in before and "path" in before
        assert "exact" in readback and "GUID" in readback and "path" in readback
        assert specification["answer_fragment"] in answer
        assert "on success" in cleanup and "on failure or an indeterminate result" in cleanup
        assert "never reused" in cleanup
        assert case.cleanup == {
            "adapter": "scenario_project_cleanup",
            "postconditions": [
                "owned_state_removed_or_restored",
                "project_source_unchanged",
                "successful_case_project_copy_removed",
                "failed_or_indeterminate_case_sandbox_sealed_and_never_reused",
            ],
        }
