from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest

from tests.semantic.support.codex_typed_input_profile import (
    PROFILE_CONTRACT,
    PROFILE_ID,
    PROFILE_TASK_COUNT,
    REQUIRED_CATEGORIES,
    SUPPORTED_VERSIONS,
    TypedInputProfileError,
    load_typed_input_profile,
)
from tests.semantic.support.codex_heavy_project_runner_v3 import PROJECT_RUNNER_APIS
from tests.semantic.support.codex_import_runtime_v3 import (
    COMPOUND_SUPPORTED_VERSIONS as IMPORT_COMPOUND_VERSIONS,
    PROFILE_CROSS_VERSION_SCENARIOS as IMPORT_PROFILE_VERSIONS,
    SUPPORTED_VERSION as IMPORT_BASE_VERSION,
)
from tests.semantic.support.codex_object_heavy_v3 import (
    OBJECT_COMPOUND_CROSS_VERSION_CASE_VERSIONS,
)
from tests.semantic.support.codex_soundbank_runtime_v3 import (
    PROFILE_CROSS_VERSION_SCENARIOS as SOUNDBANK_PROFILE_VERSIONS,
    SUPPORTED_VERSIONS as SOUNDBANK_BASE_VERSIONS,
)


PROFILE_PATH = (
    Path(__file__).resolve().parent / "data" / "typed-input-v1" / "profile.json"
)


def test_typed_input_profile_is_a_fixed_five_version_25_task_contract() -> None:
    root = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profile = load_typed_input_profile(PROFILE_PATH)

    assert root["contract"] == PROFILE_CONTRACT
    assert root["profile_id"] == PROFILE_ID
    assert len(profile.units) == PROFILE_TASK_COUNT == 25
    assert Counter(unit.version for unit in profile.units) == {
        version: 5 for version in SUPPORTED_VERSIONS
    }
    assert {
        category for unit in profile.units for category in unit.categories
    } == set(REQUIRED_CATEGORIES)
    assert len({unit.unit_id for unit in profile.units}) == PROFILE_TASK_COUNT
    assert all(unit.scenario.versions == (unit.version,) for unit in profile.units)
    assert all(unit.user_turn_count in {1, 2} for unit in profile.units)
    assert all(unit.transaction_count in {0, 1} for unit in profile.units)
    assert all(
        "2022.1" not in unit.scenario.prompt
        for unit in profile.units
        if unit.scenario.api == "ak.wwise.core.getInfo"
    )
    assert all(
        "验证仅限返回结果结构" in unit.scenario.prompt
        for unit in profile.units
        if unit.scenario.api == "ak.wwise.core.executeLuaScript"
    )
    assert all(
        unit.scenario.confirmation_prompt
        == "确认，按刚才唯一的 immutable Preview 执行这份文件，并按弱验证边界报告结果。"
        for unit in profile.units
        if unit.scenario.api == "ak.wwise.core.executeLuaScript"
    )


def test_typed_input_profile_filters_only_after_validating_the_complete_contract() -> None:
    profile = load_typed_input_profile(
        PROFILE_PATH,
        unit_ids=("TYP21-ZERO-GET-INFO", "TYP25-GENERIC-MEDIA-POOL"),
        versions=("2021.1", "2025.1"),
    )

    assert [unit.unit_id for unit in profile.units] == [
        "TYP21-ZERO-GET-INFO",
        "TYP25-GENERIC-MEDIA-POOL",
    ]

    with pytest.raises(TypedInputProfileError, match="unknown typed-input unit ids"):
        load_typed_input_profile(PROFILE_PATH, unit_ids=("TYP25-INVENTED",))


def test_get_info_tasks_describe_the_business_result_without_gateway_commands() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)

    prompts = {
        unit.version: unit.scenario.prompt
        for unit in profile.units
        if unit.scenario.api == "ak.wwise.core.getInfo"
    }

    assert set(prompts) == {"2021.1", "2023.1", "2024.1", "2025.1"}
    assert all("getInfo 的实时结果" in prompt for prompt in prompts.values())
    assert all(
        command not in prompt
        for prompt in prompts.values()
        for command in ("status", "request-schema", "typed-zero-call")
    )


def test_typed_input_profile_rejects_definition_drift_before_filtering(
    tmp_path: Path,
) -> None:
    root = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    for task in root["tasks"]:
        task["categories"] = [
            category for category in task["categories"] if category != "zero"
        ]
    drifted = tmp_path / "profile.json"
    drifted.write_text(json.dumps(root), encoding="utf-8")

    with pytest.raises(TypedInputProfileError, match="category coverage drifted"):
        load_typed_input_profile(drifted)


def test_every_typed_input_task_has_an_existing_closed_runner_adapter() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)

    assert {
        unit.scenario.api
        for unit in profile.units
        if not unit.scenario.api.startswith("ak.wwise.cli.")
    }.issubset(PROJECT_RUNNER_APIS)


def test_every_typed_input_task_uses_a_reviewed_runtime_version_lane() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)

    for unit in profile.units:
        api = unit.scenario.api
        if api.startswith("ak.wwise.core.object."):
            assert unit.version == "2022.1" or unit.version in (
                OBJECT_COMPOUND_CROSS_VERSION_CASE_VERSIONS.get(
                    unit.base_scenario_id,
                    (),
                )
            ), unit.unit_id
        elif api.startswith("ak.wwise.core.audio.import"):
            assert (
                unit.version == IMPORT_BASE_VERSION
                or unit.version in IMPORT_COMPOUND_VERSIONS
                or unit.version
                in IMPORT_PROFILE_VERSIONS.get(unit.base_scenario_id, ())
            ), unit.unit_id
        elif api.startswith("ak.wwise.core.soundbank."):
            assert (
                unit.version in SOUNDBANK_BASE_VERSIONS
                or unit.version
                in SOUNDBANK_PROFILE_VERSIONS.get(unit.base_scenario_id, ())
            ), unit.unit_id
