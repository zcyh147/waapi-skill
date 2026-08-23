from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.semantic.support.codex_integration_workflows_v1 import (
    CASE_FILE_CONTRACT,
    DATA_FILE_NAMES,
    EXPECTED_ADAPTERS,
    EXPECTED_PRIMARY_API,
    EXPECTED_TRANSACTION_SPECS,
    EXPECTED_TURN_KINDS,
    EXPECTED_VISIBLE_INPUTS,
    LOGICAL_WORKFLOW_COUNT,
    PROFILE_CONTRACT,
    PROFILE_ID,
    TASK_COUNT,
    TRANSACTION_COUNT,
    USER_TURN_COUNT,
    VERSIONS,
    WORKFLOW_IDS,
    IntegrationWorkflowProfileError,
    load_integration_workflows_profile,
)


COMMITTED_DATA_ROOT = (
    Path(__file__).resolve().parent
    / "data"
    / "integration-workflows-v1"
)
COMMITTED_PROFILE_PATH = COMMITTED_DATA_ROOT / "profile.json"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _copy_profile(tmp_path: Path) -> Path:
    root = tmp_path / "integration-workflows-v1"
    shutil.copytree(COMMITTED_DATA_ROOT, root)
    return root / "profile.json"


def _rewrite_json(
    path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    _write_json(path, value)


def _workflow_data_path(profile_path: Path) -> Path:
    return profile_path.parent / DATA_FILE_NAMES[0]


def test_committed_profile_declares_the_closed_standalone_data_shape() -> None:
    root = json.loads(COMMITTED_PROFILE_PATH.read_text(encoding="utf-8"))

    assert root == {
        "contract": PROFILE_CONTRACT,
        "profile_id": PROFILE_ID,
        "data_files": list(DATA_FILE_NAMES),
        "versions": list(VERSIONS),
        "totals": {
            "logical_workflow_count": LOGICAL_WORKFLOW_COUNT,
            "task_count": TASK_COUNT,
            "transaction_count": TRANSACTION_COUNT,
            "user_turn_count": USER_TURN_COUNT,
        },
    }
    assert all(Path(name).parts == (name,) for name in root["data_files"])

    data = json.loads(
        (COMMITTED_DATA_ROOT / DATA_FILE_NAMES[0]).read_text(encoding="utf-8")
    )
    assert data["contract"] == CASE_FILE_CONTRACT
    assert [row["id"] for row in data["workflows"]] == list(WORKFLOW_IDS)


def test_loader_expands_three_workflows_into_six_version_pinned_units() -> None:
    profile = load_integration_workflows_profile(COMMITTED_PROFILE_PATH)

    assert len(profile.workflows) == LOGICAL_WORKFLOW_COUNT == 3
    assert len(profile.units) == TASK_COUNT == 6
    assert sum(unit.transaction_count for unit in profile.units) == (
        TRANSACTION_COUNT
    ) == 12
    assert sum(unit.user_turn_count for unit in profile.units) == (
        USER_TURN_COUNT
    ) == 20
    assert [unit.version for unit in profile.units[:3]] == ["2022.1"] * 3
    assert [unit.version for unit in profile.units[3:]] == ["2025.1"] * 3
    assert [unit.unit_id for unit in profile.units] == [
        "INT22-INTERACTIVE-WEATHER-BUILD",
        "INT22-ALARM-DIAGNOSE-AND-REPAIR",
        "INT22-HARBOR-SOUNDBANK-RELEASE",
        "INT25-INTERACTIVE-WEATHER-BUILD",
        "INT25-ALARM-DIAGNOSE-AND-REPAIR",
        "INT25-HARBOR-SOUNDBANK-RELEASE",
    ]


def test_workflows_keep_the_reviewed_turn_and_transaction_topology() -> None:
    profile = load_integration_workflows_profile(COMMITTED_PROFILE_PATH)

    for workflow in profile.workflows:
        assert tuple(turn.kind for turn in workflow.turns) == (
            EXPECTED_TURN_KINDS[workflow.id]
        )
        assert tuple(
            (
                transaction.operation,
                transaction.api,
                transaction.preview_turn,
                transaction.confirmation_turn,
            )
            for transaction in workflow.transactions
        ) == EXPECTED_TRANSACTION_SPECS[workflow.id]
        assert tuple(item.name for item in workflow.visible_inputs) == (
            EXPECTED_VISIBLE_INPUTS[workflow.id]
        )

    alarm = profile.workflows[1]
    assert alarm.turns[0].kind == "diagnosis_request"
    assert alarm.turns[0].confirms_transaction is None
    assert alarm.turns[0].expects_preview_transaction is None
    assert alarm.transactions[0].preview_turn == 2
    assert "只读" in alarm.turns[0].prompt
    assert "不要修改" in alarm.turns[0].prompt


def test_weather_and_harbor_prompts_express_only_the_exact_business_facts() -> None:
    weather, _alarm, harbor = load_integration_workflows_profile(
        COMMITTED_PROFILE_PATH
    ).workflows

    assert "都启用循环，并把循环模式设为无限循环" in weather.turns[0].prompt
    assert "Harbor_Release 这一行的 rebuild 明确设为 false" in harbor.turns[0].prompt
    assert (
        "Harbor_Release rebuild=false、写入磁盘、跳过语言变体、"
        "不重建全部 SoundBank、不清空音频缓存、不重建 Init Bank"
        in harbor.turns[1].prompt
    )
    assert "可信 io_root" in harbor.turns[1].prompt
    assert "Event 或 Aux Bus" not in harbor.turns[0].prompt
    assert "清单明确为空" not in harbor.turns[0].prompt


def test_units_expose_the_existing_runner_scenario_read_seam() -> None:
    profile = load_integration_workflows_profile(COMMITTED_PROFILE_PATH)

    for unit in profile.units:
        scenario = unit.scenario
        assert scenario.id == unit.unit_id
        assert scenario.api == EXPECTED_PRIMARY_API[unit.workflow_id]
        assert scenario.item_type == "function"
        assert scenario.versions == (unit.version,)
        assert scenario.lane == "online_authoring"
        assert scenario.primary_dispatch.api == scenario.api
        assert scenario.primary_dispatch.count == 1
        assert scenario.confirmation_turn_count == unit.transaction_count
        assert scenario.follow_up_prompts == tuple(
            turn.prompt for turn in unit.turns[1:]
        )
        assert scenario.confirmation_prompt in scenario.follow_up_prompts
        values = {
            item.name: (
                ["\\Events\\One", "\\Events\\Two", "\\Events\\Three"]
                if item.kind == "structured_array"
                else f"/visible/{item.name}"
            )
            for item in scenario.visible_inputs
        }
        rendered = scenario.render_prompt(values)
        assert "{" not in rendered
        assert all(str(value) in rendered or isinstance(value, list) for value in values.values())

    with pytest.raises(IntegrationWorkflowProfileError, match="input mismatch"):
        profile.units[0].scenario.render_prompt({})


def test_rendered_prompt_accepts_provenance_owned_sandbox_path_values() -> None:
    scenario = load_integration_workflows_profile(
        COMMITTED_PROFILE_PATH
    ).units[0].scenario

    rendered = scenario.render_prompt(
        {
            "weather_source_directory": (
                "/private/tmp/runner/sandbox-root/owned/weather/sources"
            ),
            "weather_root_path": (
                r"\Actor-Mixer Hierarchy\Default Work Unit\IntegrationLab"
            ),
            "weather_event_root_path": (
                r"\Events\Default Work Unit\Integration_Weather"
            ),
            "weather_game_parameter_path": (
                r"\Game Parameters\Ambience\Rain_Intensity"
            ),
            "weather_bus_path": (
                r"\Master-Mixer Hierarchy\Default Work Unit\Weather_Bus"
            ),
        }
    )

    assert "/sandbox-root/owned/weather/sources" in rendered


def test_prompts_read_as_user_requests_and_close_visible_inputs() -> None:
    profile = load_integration_workflows_profile(COMMITTED_PROFILE_PATH)
    forbidden = (
        "skill",
        "gateway",
        "harness",
        "fixture",
        "sandbox",
        "oracle",
        "test case",
        "run.py",
        "测试",
        "沙箱",
        "边界",
    )

    for workflow in profile.workflows:
        declared = {item.name for item in workflow.visible_inputs}
        first_prompt = workflow.turns[0].prompt
        assert all(f"{{{name}}}" in first_prompt for name in declared)
        for turn in workflow.turns:
            assert len(turn.prompt.strip()) >= 12
            assert not any(word.lower() in turn.prompt.lower() for word in forbidden)

    weather_prompt = profile.workflows[0].turns[0].prompt
    assert "-4 dB/2" not in weather_prompt
    assert "0.25/0 秒" not in weather_prompt
    assert "Rain_Bed 的音量设为 -4 dB，最大实例数设为 2" in weather_prompt
    assert "一个名为 Thunder 的 Random Container" in weather_prompt
    assert "每一步都直接生成并展示预览，预览前不要询问" in weather_prompt
    assert (
        "Play_Thunder_Near 的 FadeTime 设为 0.05 秒，"
        "Delay 设为 0 秒"
    ) in weather_prompt

    harbor_prompts = tuple(
        turn.prompt for turn in profile.workflows[2].turns
    )
    assert all("正式事件" not in prompt for prompt in harbor_prompts)
    assert (
        "为下面三个 Event 分别增加 Event、Structure 和 Media 三类包含内容"
        in harbor_prompts[0]
    )
    assert "同时移除已有的 Debug 包含项；不要修改 Harbor_Control" in harbor_prompts[0]


def test_fixtures_supply_only_visible_inputs_and_owned_cleanup_contracts() -> None:
    profile = load_integration_workflows_profile(COMMITTED_PROFILE_PATH)

    for workflow in profile.workflows:
        assert workflow.fixture.adapter == EXPECTED_ADAPTERS[workflow.id]
        assert set(workflow.fixture.visible_bindings) == {
            item.name for item in workflow.visible_inputs
        }
        assert workflow.fixture.cleanup == {
            "success": "remove_scenario_owned_project_assets_and_outputs",
            "failure": "seal_owned_state_never_reuse",
            "source_project": "must_remain_unchanged",
        }

    weather, alarm, harbor = profile.workflows
    assert len(weather.fixture.parameters["source_files"]) == 5
    assert len(weather.fixture.parameters["import_rows"]) == 5
    assert len(weather.fixture.parameters["action_updates"]) == 5
    assert len(weather.fixture.parameters["rtpc"]["points"]) == 3
    assert {
        row["event_name"] for row in weather.fixture.parameters["import_rows"]
    } == {
        "Play_Rain_Bed",
        "Play_Wind_Bed",
        "Play_Thunder_Near",
        "Play_Thunder_Mid",
        "Play_Thunder_Far",
    }
    assert all(
        row["references"]["OutputBus"]
        == "{weather_bus_path}"
        for row in weather.fixture.parameters["import_rows"]
    )
    assert [
        row["object"]
        for row in weather.fixture.parameters["action_updates"]
    ] == [
        {
            "kind": "direct-child",
            "parent": {
                "kind": "path",
                "value": (
                    r"\Events\Default Work Unit\Integration_Weather"
                    f"\\{event_name}"
                ),
            },
            "type": "Action",
        }
        for event_name in (
            "Play_Rain_Bed",
            "Play_Wind_Bed",
            "Play_Thunder_Near",
            "Play_Thunder_Mid",
            "Play_Thunder_Far",
        )
    ]
    assert alarm.fixture.parameters["reference_name"] == "OutputBus"
    assert [
        row["stage"] for row in alarm.fixture.parameters["diagnostic_plan"]
    ] == ["event", "action", "sound", "audio_source", "bus"]
    assert harbor.fixture.parameters["inclusion_filter"] == [
        "events",
        "structures",
        "media",
    ]
    assert harbor.fixture.parameters["remove_event_path"].endswith("\\Debug")
    assert harbor.fixture.parameters["control_bank_name"] == "Harbor_Control"
    assert harbor.fixture.parameters["platforms"] == ["Windows", "Mac"]
    assert harbor.fixture.parameters["languages"] == ["SFX"]


def test_loader_filters_only_after_validating_the_complete_profile(
    tmp_path: Path,
) -> None:
    profile_path = _copy_profile(tmp_path)
    selected = load_integration_workflows_profile(
        profile_path,
        unit_ids=("INT25-ALARM-DIAGNOSE-AND-REPAIR",),
        versions=("2025.1",),
    )

    assert [unit.unit_id for unit in selected.units] == [
        "INT25-ALARM-DIAGNOSE-AND-REPAIR"
    ]
    assert len(selected.workflows) == LOGICAL_WORKFLOW_COUNT

    with pytest.raises(IntegrationWorkflowProfileError, match="unknown"):
        load_integration_workflows_profile(profile_path, unit_ids=("UNKNOWN",))
    with pytest.raises(IntegrationWorkflowProfileError, match="no units for versions"):
        load_integration_workflows_profile(profile_path, versions=("2024.1",))
    with pytest.raises(IntegrationWorkflowProfileError, match="duplicate"):
        load_integration_workflows_profile(
            profile_path,
            versions=("2025.1", "2025.1"),
        )
    with pytest.raises(
        IntegrationWorkflowProfileError,
        match="no integration units",
    ):
        load_integration_workflows_profile(
            profile_path,
            unit_ids=("INT22-INTERACTIVE-WEATHER-BUILD",),
            versions=("2025.1",),
        )

    _rewrite_json(
        _workflow_data_path(profile_path),
        lambda root: root["workflows"][0]["transactions"][0].__setitem__(
            "api",
            "ak.wwise.core.object.create",
        ),
    )
    with pytest.raises(IntegrationWorkflowProfileError, match="sequence drifted"):
        load_integration_workflows_profile(
            profile_path,
            unit_ids=("INT25-ALARM-DIAGNOSE-AND-REPAIR",),
        )


def test_definition_digest_covers_profile_and_workflow_data(
    tmp_path: Path,
) -> None:
    profile_path = _copy_profile(tmp_path)
    first = load_integration_workflows_profile(profile_path)
    data_path = _workflow_data_path(profile_path)
    data_path.write_text(
        data_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    second = load_integration_workflows_profile(profile_path)

    assert [name for name, _ in first.source_digests] == [
        "profile.json",
        "workflows.json",
    ]
    assert len(first.definition_sha256) == 64
    assert first.definition_sha256 != second.definition_sha256


@pytest.mark.parametrize(
    ("target", "mutate", "message"),
    [
        (
            "profile",
            lambda root: root.__setitem__("unexpected", True),
            "schema is not closed",
        ),
        (
            "profile",
            lambda root: root["totals"].__setitem__("task_count", 7),
            "totals drifted",
        ),
        (
            "data",
            lambda root: root["workflows"][0]["turns"][1].__setitem__(
                "expects_preview_transaction",
                3,
            ),
            "link drifted",
        ),
        (
            "data",
            lambda root: root["workflows"][0]["turns"][0].__setitem__(
                "prompt",
                "请按 skill 边界执行这个测试案例并先给我预览。",
            ),
            "test-harness coaching",
        ),
        (
            "data",
            lambda root: root["workflows"][1]["fixture"][
                "visible_bindings"
            ].pop("alarm_target_bus_path"),
            "exactly cover visible inputs",
        ),
        (
            "data",
            lambda root: root["workflows"][2]["fixture"]["visible_bindings"][
                "soundbank_output_directory"
            ].__setitem__("relative_path", "../escaped"),
            "owned root",
        ),
        (
            "data",
            lambda root: root["workflows"][2]["fixture"]["visible_bindings"][
                "soundbank_io_root"
            ].__setitem__("unexpected", True),
            "owned-root schema is not closed",
        ),
        (
            "data",
            lambda root: root["workflows"][2]["fixture"]["parameters"][
                "artifact_scope"
            ].append("metadata"),
            "stable Bank and media outputs",
        ),
        (
            "data",
            lambda root: root["workflows"][0]["fixture"]["parameters"][
                "action_updates"
            ][0].__setitem__(
                "object",
                {
                    "kind": "waql",
                    "value": (
                        'from object "\\Events\\Default Work Unit'
                        '\\Integration_Weather\\Play_Rain_Bed" '
                        'select children where type = "Action" take 2'
                    ),
                },
            ),
            "exact direct Action child",
        ),
        (
            "data",
            lambda root: root["workflows"][0]["fixture"]["parameters"][
                "action_updates"
            ][0]["object"].__setitem__("type", "Event"),
            "exact direct Action child",
        ),
    ],
)
def test_loader_rejects_schema_and_contract_tampering(
    tmp_path: Path,
    target: str,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    profile_path = _copy_profile(tmp_path)
    path = (
        profile_path
        if target == "profile"
        else _workflow_data_path(profile_path)
    )
    _rewrite_json(path, mutate)

    with pytest.raises(IntegrationWorkflowProfileError, match=message):
        load_integration_workflows_profile(profile_path)


def test_loader_rejects_duplicate_json_object_keys(tmp_path: Path) -> None:
    profile_path = _copy_profile(tmp_path)
    profile_path.write_text(
        '{"contract":"first","contract":"second"}\n',
        encoding="utf-8",
    )

    with pytest.raises(IntegrationWorkflowProfileError, match="duplicate"):
        load_integration_workflows_profile(profile_path)
