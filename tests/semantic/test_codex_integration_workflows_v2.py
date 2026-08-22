from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.semantic.support.codex_campaign import canonical_json_bytes
from tests.semantic.support.codex_integration_fixture_tree_v2 import (
    wwise_fixture_tree_sha256,
)
from tests.semantic.support.codex_integration_workflows_v2 import (
    BASELINE_MANIFEST_CONTRACT,
    CASE_FILE_CONTRACT,
    DATA_FILE_NAMES,
    EXPECTED_ASSERTION_IDS,
    EXPECTED_SOURCE_KEYS,
    EXPECTED_STORAGE_FILES,
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
    IntegrationWorkflowV2Error,
    load_integration_workflows_v2_profile,
)


DATA_ROOT = Path(__file__).resolve().parent / "data" / "integration-workflows-v2"
PROFILE_PATH = DATA_ROOT / "profile.json"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_definition(repo: Path) -> Path:
    target = repo / "tests" / "semantic" / "data" / "integration-workflows-v2"
    shutil.copytree(DATA_ROOT, target)
    return target / "profile.json"


def _rewrite(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    _write_json(path, value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seal_fake_baselines(repo: Path, profile_path: Path) -> None:
    definition = load_integration_workflows_v2_profile(profile_path)
    specs = {}
    for workflow in definition.workflows:
        for spec in workflow.fixture.object_graph:
            if spec.baseline_state == "present":
                previous = specs.setdefault(spec.role, spec)
                assert previous == spec

    for version_index, version in enumerate(VERSIONS, start=1):
        layout = definition.baseline_layouts[version]
        project = repo / layout.source_project
        project.parent.mkdir(parents=True, exist_ok=True)
        project.write_text(f"fake {version} project\n", encoding="utf-8")

        storage_rows = []
        for index, relative in enumerate(layout.storage_files, start=1):
            path = project.parent / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{version} storage {index}\n", encoding="utf-8")
            storage_rows.append({"relative_path": relative, "sha256": _sha256(path)})

        object_rows = []
        media_rows = []
        for index, (role, spec) in enumerate(sorted(specs.items()), start=1):
            state = {
                "captured_fields": ["id", "path", "type"],
                "role": role,
            }
            object_rows.append(
                {
                    "role": role,
                    "id": f"{{00000000-0000-0000-{version_index:04d}-{index:012X}}}",
                    "path": spec.path_for(version),
                    "type": spec.type,
                    "state": state,
                    "state_sha256": hashlib.sha256(
                        canonical_json_bytes(state)
                    ).hexdigest(),
                }
            )
            if spec.type == "Sound":
                media_path = project.parent / "Originals" / "SFX" / f"{role}.wav"
                media_path.parent.mkdir(parents=True, exist_ok=True)
                media_path.write_bytes(f"RIFF:{version}:{role}".encode())
                media_rows.append(
                    {
                        "role": role,
                        "active_source_id": f"{{10000000-0000-0000-{version_index:04d}-{index:012X}}}",
                        "relative_path": media_path.relative_to(project.parent).as_posix(),
                        "sha256": _sha256(media_path),
                    }
                )

        manifest = {
            "contract": BASELINE_MANIFEST_CONTRACT,
            "version": version,
            "source_project": {
                "relative_path": layout.source_project,
                "project_file_sha256": _sha256(project),
                "full_tree_sha256": wwise_fixture_tree_sha256(project.parent),
            },
            "storage_files": storage_rows,
            "objects": object_rows,
            "media": media_rows,
        }
        _write_json(repo / layout.manifest, manifest)


def test_committed_profile_has_a_distinct_fixed_baseline_contract() -> None:
    root = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    assert root["contract"] == PROFILE_CONTRACT
    assert root["profile_id"] == PROFILE_ID
    assert root["profile_id"] != "integration_workflows_cross_version_6"
    assert root["data_files"] == list(DATA_FILE_NAMES)
    assert root["versions"] == list(VERSIONS)
    assert root["baseline_kind"] == "committed_sample_project"
    assert root["totals"] == {
        "logical_workflow_count": LOGICAL_WORKFLOW_COUNT,
        "task_count": TASK_COUNT,
        "transaction_count": TRANSACTION_COUNT,
        "user_turn_count": USER_TURN_COUNT,
    }

    data = json.loads((DATA_ROOT / DATA_FILE_NAMES[0]).read_text(encoding="utf-8"))
    assert data["contract"] == CASE_FILE_CONTRACT
    assert [row["id"] for row in data["workflows"]] == list(WORKFLOW_IDS)


def test_loader_expands_three_workflows_to_six_units_with_reviewed_topology() -> None:
    profile = load_integration_workflows_v2_profile(PROFILE_PATH)

    assert not profile.committed_baselines_ready
    assert len(profile.workflows) == LOGICAL_WORKFLOW_COUNT == 3
    assert len(profile.units) == TASK_COUNT == 6
    assert sum(row.transaction_count for row in profile.units) == TRANSACTION_COUNT == 8
    assert sum(row.user_turn_count for row in profile.units) == USER_TURN_COUNT == 16
    assert [row.unit_id for row in profile.units] == [
        "INT22-V2-RIFLE-SAFE-REIMPORT",
        "INT22-V2-FOOTSTEPS-SNOW-ASSIGNMENT-MAINTENANCE",
        "INT22-V2-WEAPONS-QUERY-GUIDED-BATCH-CLEANUP",
        "INT25-V2-RIFLE-SAFE-REIMPORT",
        "INT25-V2-FOOTSTEPS-SNOW-ASSIGNMENT-MAINTENANCE",
        "INT25-V2-WEAPONS-QUERY-GUIDED-BATCH-CLEANUP",
    ]

    for workflow in profile.workflows:
        assert tuple(row.kind for row in workflow.turns) == EXPECTED_TURN_KINDS[workflow.id]
        assert tuple(
            (row.operation, row.api, row.preview_turn, row.confirmation_turn)
            for row in workflow.transactions
        ) == EXPECTED_TRANSACTION_SPECS[workflow.id]
        assert tuple(row.name for row in workflow.visible_inputs) == EXPECTED_VISIBLE_INPUTS[workflow.id]
        assert tuple(row.id for row in workflow.fixture.business_assertions) == EXPECTED_ASSERTION_IDS[workflow.id]


def test_workflows_use_fixed_default_work_unit_subtrees_and_versioned_disk_layouts() -> None:
    profile = load_integration_workflows_v2_profile(PROFILE_PATH)
    actor_prefixes = {
        "2022.1": r"\Actor-Mixer Hierarchy\Default Work Unit\WAAPI Skill Integration V2",
        "2025.1": r"\Containers\Default Work Unit\WAAPI Skill Integration V2",
    }
    event_prefix = r"\Events\Default Work Unit\WAAPI_Skill_Integration_V2"

    assert profile.baseline_layouts["2022.1"].storage_files == EXPECTED_STORAGE_FILES["2022.1"]
    assert profile.baseline_layouts["2025.1"].storage_files == EXPECTED_STORAGE_FILES["2025.1"]
    assert profile.baseline_layouts["2022.1"].storage_files[0].startswith("Actor-Mixer Hierarchy/")
    assert profile.baseline_layouts["2025.1"].storage_files[0].startswith("Containers/")
    assert profile.baseline_layouts["2022.1"].storage_files[3].startswith("Master-Mixer Hierarchy/")
    assert profile.baseline_layouts["2025.1"].storage_files[3].startswith("Busses/")

    event_roles = []
    for workflow in profile.workflows:
        for spec in workflow.fixture.object_graph:
            if spec.type in {"Sound", "ActorMixer", "RandomSequenceContainer", "SwitchContainer"}:
                assert all(
                    spec.path_for(version).startswith(actor_prefixes[version] + "\\")
                    for version in VERSIONS
                )
            if spec.type == "Event":
                assert all(path.startswith(event_prefix + "\\") for path in spec.paths.values())
                event_roles.append(spec.role)
    assert event_roles == ["play_rifle_event", "play_footsteps_event", "audit_close_event"]
    rifle_graph = {row.role: row for row in profile.workflows[0].fixture.object_graph}
    assert rifle_graph["play_rifle_event"].paths == {
        "2022.1": r"\Events\Default Work Unit\WAAPI_Skill_Integration_V2\RifleRevision\Play_Rifle",
        "2025.1": r"\Events\Default Work Unit\WAAPI_Skill_Integration_V2\Play_Rifle",
    }

    footstep_graph = {row.role: row for row in profile.workflows[1].fixture.object_graph}
    assert set(footstep_graph["surface_group"].paths.values()) == {
        r"\Switches\Default Work Unit\WAAPI_V2_Surface"
    }
    assert {role for role, row in footstep_graph.items() if row.baseline_state == "absent"} == {
        "snow_container", "snow_step_01", "snow_step_02", "snow_step_03", "snow_step_04"
    }
    assert "metal_sound" in footstep_graph and "mud_sound" in footstep_graph
    assert footstep_graph["play_footsteps_event"].paths == {
        "2022.1": r"\Events\Default Work Unit\WAAPI_Skill_Integration_V2\PlayerFootstepsMaintenance\Play_Footsteps",
        "2025.1": r"\Events\Default Work Unit\WAAPI_Skill_Integration_V2\Play_Player_Footsteps",
    }

    weapons_graph = {row.role: row for row in profile.workflows[2].fixture.object_graph}
    assert weapons_graph["audit_close_event"].paths == {
        "2022.1": r"\Events\Default Work Unit\WAAPI_Skill_Integration_V2\WeaponsAudit\Play_Rifle_Close",
        "2025.1": r"\Events\Default Work Unit\WAAPI_Skill_Integration_V2\Play_Rifle_Close",
    }


def test_prompts_are_natural_and_encode_the_three_business_acceptance_cases() -> None:
    rifle, footsteps, audit = load_integration_workflows_v2_profile(PROFILE_PATH).workflows
    all_prompts = [turn.prompt for row in (rifle, footsteps, audit) for turn in row.turns]
    forbidden = ("skill", "gateway", "harness", "fixture", "sandbox", "oracle", "测试", "沙箱", "边界")
    assert all(not any(word.lower() in prompt.lower() for word in forbidden) for prompt in all_prompts)

    assert "沿用这三个 Sound，不要替换或重建对象" in rifle.turns[0].prompt
    assert "合成一次变更" in rifle.turns[0].prompt
    assert "{rifle_source_files}" in rifle.turns[0].prompt
    assert rifle.fixture.parameters["import_operation"] == "useExisting"
    assert [row.key for row in rifle.fixture.source_files] == list(EXPECTED_SOURCE_KEYS["rifle_safe_reimport"])

    assert "保留 Mud 容器、里面的声音、素材和 Mud Switch 值" in footsteps.turns[0].prompt
    assert "完成后再单独预览解除 Mud 分配" in footsteps.turns[0].prompt
    assert "名为 Snow 的 Random Container" in footsteps.turns[0].prompt
    assert all(
        f"Snow_Step_{index:02d}" in footsteps.turns[0].prompt
        for index in range(1, 5)
    )
    assert "名为 Snow 的 Random Container" in footsteps.turns[1].prompt
    assert footsteps.fixture.parameters["structure_row"]["switch_assignment"] == "Snow"

    assert "这一轮不要修改工程" in audit.turns[0].prompt
    assert "Legacy_Rifle_Reference 和 RFL_Intentional_Hot 是有意保留的例外" in audit.turns[1].prompt
    assert audit.fixture.parameters["identity_readback"] == "exact_id_before_preview"
    assert len(audit.fixture.parameters["selected_corrections"]) == 3


def test_scenario_proxy_renders_only_declared_runner_owned_values() -> None:
    scenario = load_integration_workflows_v2_profile(PROFILE_PATH).units[0].scenario
    rendered = scenario.render_prompt(
        {
            "rifle_source_directory": "/tmp/owned/rifle/incoming",
            "rifle_source_files": (
                '["/tmp/owned/rifle/incoming/rifle_close_v2.wav",'
                '"/tmp/owned/rifle/incoming/rifle_tail_v2.wav",'
                '"/tmp/owned/rifle/incoming/rifle_mechanical_v2.wav",'
                '"/tmp/owned/rifle/incoming/rifle_distant.wav"]'
            ),
            "rifle_container_path": r"\Actor-Mixer Hierarchy\Default Work Unit\WAAPI Skill Integration V2\RifleRevision\Rifle",
            "rifle_event_path": r"\Events\Default Work Unit\WAAPI_Skill_Integration_V2\RifleRevision\Play_Rifle",
            "rifle_bus_path": r"\Master-Mixer Hierarchy\Default Work Unit\WAAPI_V2_Weapons",
        }
    )
    assert "{" not in rendered
    assert "/tmp/owned/rifle/incoming" in rendered
    assert "/tmp/owned/rifle/incoming/rifle_mechanical_v2.wav" in rendered
    with pytest.raises(IntegrationWorkflowV2Error, match="input mismatch"):
        scenario.render_prompt({})


def test_filtering_happens_after_complete_definition_validation(tmp_path: Path) -> None:
    profile_path = _copy_definition(tmp_path)
    selected = load_integration_workflows_v2_profile(
        profile_path,
        unit_ids=("INT25-V2-WEAPONS-QUERY-GUIDED-BATCH-CLEANUP",),
        versions=("2025.1",),
    )
    assert [row.unit_id for row in selected.units] == [
        "INT25-V2-WEAPONS-QUERY-GUIDED-BATCH-CLEANUP"
    ]

    workflows_path = profile_path.parent / "workflows.json"
    _rewrite(
        workflows_path,
        lambda root: root["workflows"][0]["transactions"][0].__setitem__(
            "api", "ak.wwise.core.object.create"
        ),
    )
    with pytest.raises(IntegrationWorkflowV2Error, match="transaction sequence drifted"):
        load_integration_workflows_v2_profile(
            profile_path,
            unit_ids=("INT25-V2-WEAPONS-QUERY-GUIDED-BATCH-CLEANUP",),
        )


@pytest.mark.parametrize(
    ("target", "mutate", "message"),
    [
        ("profile", lambda root: root.__setitem__("extra", True), "schema is not closed"),
        (
            "profile",
            lambda root: root["totals"].__setitem__("task_count", 7),
            "totals drifted",
        ),
        (
            "workflows",
            lambda root: root["workflows"][0]["turns"][0].__setitem__(
                "prompt", "请按 skill 的测试边界执行这个测试案例。"
            ),
            "test-harness coaching",
        ),
        (
            "workflows",
            lambda root: root["workflows"][1]["fixture"]["object_graph"][0][
                "paths"
            ].__setitem__(
                "2022.1",
                r"\Actor-Mixer Hierarchy\Default Work Unit\Elsewhere\Player_Footsteps",
            ),
            "escaped the fixed Actor subtree",
        ),
        (
            "workflows",
            lambda root: root["workflows"][2]["fixture"]["business_assertions"].pop(),
            "business assertion identity drifted",
        ),
    ],
)
def test_loader_rejects_definition_tampering(
    tmp_path: Path,
    target: str,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    profile_path = _copy_definition(tmp_path)
    path = profile_path if target == "profile" else profile_path.parent / "workflows.json"
    _rewrite(path, mutate)
    with pytest.raises(IntegrationWorkflowV2Error, match=message):
        load_integration_workflows_v2_profile(profile_path)


def test_real_execution_preflight_loads_sealed_committed_baselines() -> None:
    loaded = load_integration_workflows_v2_profile(
        PROFILE_PATH,
        require_committed_baselines=True,
    )

    assert loaded.committed_baselines_ready
    assert set(loaded.baseline_manifests) == set(VERSIONS)
    assert len(loaded.source_digests) == 4
    assert all(len(manifest.objects) == 35 for manifest in loaded.baseline_manifests.values())
    assert all(len(manifest.media) == 15 for manifest in loaded.baseline_manifests.values())


def test_sealed_baseline_manifests_bind_guids_media_and_tree_hashes(tmp_path: Path) -> None:
    profile_path = _copy_definition(tmp_path)
    _seal_fake_baselines(tmp_path, profile_path)

    loaded = load_integration_workflows_v2_profile(
        profile_path,
        require_committed_baselines=True,
        repo_root=tmp_path,
    )
    assert loaded.committed_baselines_ready
    assert set(loaded.baseline_manifests) == set(VERSIONS)
    assert len(loaded.source_digests) == 4
    for manifest in loaded.baseline_manifests.values():
        assert manifest.objects
        assert manifest.media
        assert all(row["id"].startswith("{") for row in manifest.objects)
        assert all(len(row["sha256"]) == 64 for row in manifest.media)

    source = tmp_path / loaded.baseline_layouts["2022.1"].source_project
    source.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(IntegrationWorkflowV2Error, match="project hash drifted"):
        load_integration_workflows_v2_profile(
            profile_path,
            require_committed_baselines=True,
            repo_root=tmp_path,
        )


def test_definition_digest_covers_profile_and_workflow_bytes(tmp_path: Path) -> None:
    profile_path = _copy_definition(tmp_path)
    first = load_integration_workflows_v2_profile(profile_path)
    workflow_path = profile_path.parent / "workflows.json"
    workflow_path.write_text(workflow_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    second = load_integration_workflows_v2_profile(profile_path)

    assert len(first.definition_sha256) == 64
    assert first.definition_sha256 != second.definition_sha256
