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


def test_bounded_query_prompt_keeps_boolean_filtering_in_the_returned_inventory() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    unit = next(
        unit
        for unit in profile.units
        if unit.unit_id == "TYP21-QUERY-OBJECT-GET"
    )

    assert "候选可以包含更深层" in unit.scenario.prompt
    assert "从这份有界候选清单中只保留相对该根三层以内" in unit.scenario.prompt
    assert "Volume 低于 -6 dB 或备注含 `needs-review`" in unit.scenario.prompt
    assert "筛选结果可能不完整" in unit.scenario.prompt
    assert all(
        command not in unit.scenario.prompt
        for command in ("query-schema", "query-object", "--where")
    )


def test_parent_child_query_prompt_keeps_join_logic_after_one_bounded_inventory() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    unit = next(
        unit
        for unit in profile.units
        if unit.unit_id == "TYP23-QUERY-OBJECT-GET"
    )

    assert "最多返回 24 条候选记录" in unit.scenario.prompt
    assert "从这份返回的候选清单中" in unit.scenario.prompt
    assert "名字以 `VO_` 开头" in unit.scenario.prompt
    assert "直接子级" in unit.scenario.prompt
    assert "父容器只作为匹配子 Sound 行中的一列" in unit.scenario.prompt
    assert "不要列出或提及被排除候选的路径" in unit.scenario.prompt
    assert all(
        command not in unit.scenario.prompt
        for command in ("query-schema", "query-object", "--select")
    )


def test_topic_prompts_name_the_exact_business_projection_without_gateway_syntax() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    units = [
        unit
        for unit in profile.units
        if unit.unit_id
        in {
            "TYP23-TOPIC-SOUNDBANK-GENERATED",
            "TYP24-TOPIC-SOUNDBANK-GENERATED",
        }
    ]

    assert len(units) == 2
    assert all("SoundBank 的 id、name、type" in unit.scenario.prompt for unit in units)
    assert all("完整 path" in unit.scenario.prompt for unit in units)
    assert all(
        command not in unit.scenario.prompt
        for unit in units
        for command in ("topic-schema", "wait-topic", "--option-append")
    )


def test_create_merge_prompt_keeps_the_existing_node_out_of_the_parent_role() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    unit = next(
        unit
        for unit in profile.units
        if unit.unit_id == "TYP21-DEDICATED-OBJECT-CREATE"
    )

    assert "在它当前的直接父级下按原名合并" in unit.scenario.prompt
    assert "GUID 只证明现有节点身份，不能替代这条父级路径" in unit.scenario.prompt
    assert "不要把 `Robot_VO` 自己当作新建父级" in unit.scenario.prompt
    assert "`Idle_A` Sound 也是叶节点" in unit.scenario.prompt
    assert "仅是保持不变的验收条件，不属于本次新增 children" in (
        unit.scenario.prompt
    )
    assert "不要为 `Idle` 或 `Idle_A` 生成任何新增事实" in (
        unit.scenario.prompt
    )
    assert "本次新增 children 只有 `Alert`" in (
        unit.scenario.prompt
    )
    assert "`Combat`、`Damage` 不属于本单元范围" in unit.scenario.prompt
    assert "警戒对白" not in unit.scenario.prompt
    assert unit.scenario.confirmation_prompt == (
        "可以，只在现有 Robot_VO 下合并新增 Alert 这一组并核对结果。"
    )
    assert "`Alert_A`、`Alert_B` 都是叶节点" in unit.scenario.prompt
    assert "不再添加子对象、属性或引用" in unit.scenario.prompt
    assert all(
        command not in unit.scenario.prompt
        for command in ("operation-schema", "draft-start", "--fact-action")
    )


def test_metadata_set_prompt_names_each_exact_target_path() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    unit = next(
        unit
        for unit in profile.units
        if unit.unit_id == "TYP22-METADATA-OBJECT-SET"
    )

    root = r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Ambience"
    assert all(
        f"`{root}\\{name}`" in unit.scenario.prompt
        for name in ("Day", "Night", "Storm")
    )
    assert all(
        command not in unit.scenario.prompt
        for command in ("operation-schema", "draft-start", "--target")
    )


def test_object_create_prompts_declare_the_requested_sound_leaves() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    units = [
        unit
        for unit in profile.units
        if unit.unit_id
        in {
            "TYP21-DEDICATED-OBJECT-CREATE",
            "TYP23-DEDICATED-OBJECT-CREATE",
        }
    ]

    assert len(units) == 2
    assert all("都是叶节点" in unit.scenario.prompt for unit in units)
    assert all(
        "不再添加子对象、属性或引用" in unit.scenario.prompt for unit in units
    )
    assert all("严格按这棵业务树" in unit.scenario.prompt for unit in units)
    assert all(
        "处理完一个叶节点后直接处理同组的下一个叶节点" in unit.scenario.prompt
        for unit in units
    )
    assert all(
        "预览返回后再请我确认执行" in unit.scenario.prompt for unit in units
    )
    assert all(
        command not in unit.scenario.prompt
        for unit in units
        for command in ("request-map-container", "--parent-schema-token")
    )


def test_2025_metadata_prompt_uses_the_exact_version_owned_container_path() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    unit = next(
        unit
        for unit in profile.units
        if unit.unit_id == "TYP25-METADATA-OBJECT-SET"
    )

    assert all(
        rf"\Containers\Default Work Unit\SemanticLab\UI\{name}"
        in unit.scenario.prompt
        for name in ("Confirm", "Cancel", "Error")
    )
    assert r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\UI" not in (
        unit.scenario.prompt
    )
    assert all(
        command not in unit.scenario.prompt
        for command in ("operation-schema", "draft-start", "--fact-action")
    )


def test_media_pool_prompt_separates_the_bounded_candidate_inventory_from_the_final_limit() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    unit = next(
        unit
        for unit in profile.units
        if unit.unit_id == "TYP25-GENERIC-MEDIA-POOL"
    )
    assert "最多 200 条候选" in unit.scenario.prompt
    assert "从这份候选清单" in unit.scenario.prompt
    assert "最终最多返回 20 条" in unit.scenario.prompt
    assert all(
        command not in unit.scenario.prompt
        for command in (
            "request-schema",
            "typed-call",
            "draft-start",
            "maxResults",
        )
    )


def test_topic_prompts_separate_subscription_scope_from_returned_event_checks() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    prompts = {
        unit.unit_id: unit.scenario.prompt
        for unit in profile.units
        if "TOPIC-SOUNDBANK-GENERATED" in unit.unit_id
    }

    assert "订阅时只按平台名称 `Windows` 限定" in prompts[
        "TYP21-TOPIC-SOUNDBANK-GENERATED"
    ]
    assert "三个 SoundBank 名称在通知返回后核对" in prompts[
        "TYP21-TOPIC-SOUNDBANK-GENERATED"
    ]
    assert "SoundBank 对象本身的名称 `Dialogue_Chapter14`" in prompts[
        "TYP23-TOPIC-SOUNDBANK-GENERATED"
    ]
    assert "平台记录的名称 `Windows`" in prompts[
        "TYP23-TOPIC-SOUNDBANK-GENERATED"
    ]
    assert "只按 SoundBank 对象本身的名称 `Weapons_Core` 限定" in prompts[
        "TYP24-TOPIC-SOUNDBANK-GENERATED"
    ]
    assert "平台不限定为单值" in prompts[
        "TYP24-TOPIC-SOUNDBANK-GENERATED"
    ]
    assert all(
        command not in prompt
        for prompt in prompts.values()
        for command in ("topic-schema", "wait-topic", "--match-set")
    )


def test_query_prompt_treats_the_exact_object_path_as_business_input() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    unit = next(
        unit
        for unit in profile.units
        if unit.unit_id == "TYP23-QUERY-OBJECT-GET"
    )

    assert r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab" in (
        unit.scenario.prompt
    )
    assert "无需查找任何本地文件或目录" in unit.scenario.prompt
    assert all(
        command not in unit.scenario.prompt
        for command in ("query-object", "Get-ChildItem", "SKILL.md")
    )


def test_object_create_prompt_does_not_invite_a_redundant_parent_query() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    unit = next(
        unit
        for unit in profile.units
        if unit.unit_id == "TYP21-DEDICATED-OBJECT-CREATE"
    )

    assert "父级路径已经明确" in unit.scenario.prompt
    assert "无需另行核对父级" in unit.scenario.prompt


def test_rename_object_create_prompt_seals_the_existing_collision_identity() -> None:
    profile = load_typed_input_profile(PROFILE_PATH)
    unit = next(
        unit
        for unit in profile.units
        if unit.unit_id == "TYP23-DEDICATED-OBJECT-CREATE"
    )

    assert (
        r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Weapons"
        r"\Impact_Library"
    ) in unit.scenario.prompt
    assert "已证明是 Actor Mixer" in unit.scenario.prompt
    assert "创建前无需重复读取" in unit.scenario.prompt
    assert all(
        command not in unit.scenario.prompt
        for command in ("query-object", "operation-schema", "draft-start")
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
