from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.semantic.support.codex_integration_workflows import (
    COMPONENT_PROFILE_PATHS,
    LEGACY_UNIT_ID_BY_PUBLIC_ID,
    LOGICAL_WORKFLOW_COUNT,
    PROFILE_CONTRACT,
    PROFILE_ID,
    TASK_COUNT,
    TRANSACTION_COUNT,
    USER_TURN_COUNT,
    VERSIONS,
    WORKFLOW_ORDER,
    IntegrationProfileError,
    load_integration_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(__file__).resolve().parent / "data"
PROFILE_PATH = DATA_ROOT / "integration" / "profile.json"


@pytest.fixture(scope="module")
def profile():
    return load_integration_profile(PROFILE_PATH)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _copy_definition(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    for name in (
        "integration",
        "integration-workflows-v1",
        "integration-workflows-v2",
    ):
        shutil.copytree(DATA_ROOT / name, target / name)
    return target / "integration" / "profile.json"


def _rewrite(
    path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    _write_json(path, value)


def test_committed_meta_profile_is_closed_and_does_not_duplicate_workflows() -> None:
    root = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))

    assert root == {
        "contract": PROFILE_CONTRACT,
        "profile_id": PROFILE_ID,
        "component_profiles": list(COMPONENT_PROFILE_PATHS),
        "versions": list(VERSIONS),
        "workflow_order": list(WORKFLOW_ORDER),
        "totals": {
            "logical_workflow_count": LOGICAL_WORKFLOW_COUNT,
            "task_count": TASK_COUNT,
            "transaction_count": TRANSACTION_COUNT,
            "user_turn_count": USER_TURN_COUNT,
        },
    }
    assert not (PROFILE_PATH.parent / "workflows.json").exists()
    assert not tuple(PROFILE_PATH.parent.glob("baseline-*.json"))


def test_loader_composes_twelve_public_units_in_version_major_order(profile) -> None:
    assert len(profile.workflows) == LOGICAL_WORKFLOW_COUNT == 6
    assert len(profile.units) == TASK_COUNT == 12
    assert profile.committed_baselines_ready
    assert set(profile.baseline_manifests) == set(VERSIONS)
    assert sum(unit.transaction_count for unit in profile.units) == (
        TRANSACTION_COUNT
    ) == 20
    assert sum(unit.user_turn_count for unit in profile.units) == (
        USER_TURN_COUNT
    ) == 36
    assert [unit.unit_id for unit in profile.units] == [
        "INT22-WEATHER",
        "INT22-ALARM",
        "INT22-HARBOR",
        "INT22-RIFLE",
        "INT22-FOOTSTEPS",
        "INT22-WEAPONS",
        "INT25-WEATHER",
        "INT25-ALARM",
        "INT25-HARBOR",
        "INT25-RIFLE",
        "INT25-FOOTSTEPS",
        "INT25-WEAPONS",
    ]
    assert [unit.workflow_name for unit in profile.units[:6]] == list(
        WORKFLOW_ORDER
    )
    assert [unit.workflow_name for unit in profile.units[6:]] == list(
        WORKFLOW_ORDER
    )
    assert [unit.scenario.scenario_index for unit in profile.units] == [
        *range(1, 7),
        *range(1, 7),
    ]
    assert [unit.version for unit in profile.units] == [
        *("2022.1" for _ in WORKFLOW_ORDER),
        *("2025.1" for _ in WORKFLOW_ORDER),
    ]


def test_public_units_retain_component_runtime_and_closed_legacy_ids(profile) -> None:
    assert dict(profile.legacy_unit_ids) == dict(LEGACY_UNIT_ID_BY_PUBLIC_ID)
    assert [unit.legacy_unit_id for unit in profile.units] == list(
        LEGACY_UNIT_ID_BY_PUBLIC_ID.values()
    )
    for unit in profile.units:
        assert unit.scenario.id == unit.unit_id
        assert unit.scenario.versions == (unit.version,)
        assert unit.scenario.scenario_family == unit.workflow_id
        assert unit.scenario.follow_up_prompts == tuple(
            turn.prompt for turn in unit.turns[1:]
        )
        assert unit.scenario.confirmation_turn_count == unit.transaction_count
        if unit.workflow_name in {"rifle", "footsteps", "weapons"}:
            assert unit.baseline_manifest is profile.baseline_manifests[unit.version]
        else:
            assert unit.baseline_manifest is None
    with pytest.raises(TypeError):
        profile.legacy_unit_ids["INT22-WEATHER"] = "not-a-legacy-id"


@pytest.mark.parametrize(
    ("case_id", "expected"),
    [
        ("INT22-WEATHER", "INT22-WEATHER"),
        ("INT22-INTERACTIVE-WEATHER-BUILD", "INT22-WEATHER"),
        ("INT25-RIFLE", "INT25-RIFLE"),
        ("INT25-V2-RIFLE-SAFE-REIMPORT", "INT25-RIFLE"),
    ],
)
def test_case_selection_accepts_public_ids_and_legacy_aliases(
    case_id: str,
    expected: str,
) -> None:
    selected = load_integration_profile(
        PROFILE_PATH,
        unit_ids=(case_id,),
        repo_root=REPO_ROOT,
    )

    assert [unit.unit_id for unit in selected.units] == [expected]


def test_filters_keep_public_version_major_order(profile) -> None:
    selected = load_integration_profile(
        PROFILE_PATH,
        unit_ids=(
            "INT25-V2-WEAPONS-QUERY-GUIDED-BATCH-CLEANUP",
            "INT22-HARBOR",
        ),
        repo_root=REPO_ROOT,
    )
    version_only = load_integration_profile(
        PROFILE_PATH,
        versions=("2025.1",),
        repo_root=REPO_ROOT,
    )

    assert [unit.unit_id for unit in selected.units] == [
        "INT22-HARBOR",
        "INT25-WEAPONS",
    ]
    assert [unit.unit_id for unit in version_only.units] == [
        unit.unit_id for unit in profile.units[6:]
    ]
    assert selected.definition_sha256 == profile.definition_sha256
    assert version_only.source_digests == profile.source_digests


def test_component_source_digests_are_namespaced_and_include_baselines(
    profile,
) -> None:
    names = [name for name, _ in profile.source_digests]

    assert names == [
        "integration/profile.json",
        "component-01/profile.json",
        "component-01/workflows.json",
        "component-02/profile.json",
        "component-02/workflows.json",
        "component-02/baseline-2022.1.json",
        "component-02/baseline-2025.1.json",
    ]
    assert len(names) == len(set(names))
    assert len(profile.definition_sha256) == 64


def test_component_bytes_participate_in_the_unified_definition_digest(
    tmp_path: Path,
) -> None:
    copied = _copy_definition(tmp_path)
    first = load_integration_profile(copied, repo_root=REPO_ROOT)
    workflows = copied.parent.parent / "integration-workflows-v1" / "workflows.json"
    workflows.write_bytes(workflows.read_bytes() + b"\n")
    second = load_integration_profile(copied, repo_root=REPO_ROOT)

    assert first.definition_sha256 != second.definition_sha256
    assert first.units[0].unit_id == second.units[0].unit_id


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda root: root.__setitem__("unexpected", True), "not closed"),
        (
            lambda root: root["component_profiles"].__setitem__(
                0,
                "../../outside/profile.json",
            ),
            "component profile order or identity drifted",
        ),
        (
            lambda root: root["totals"].__setitem__("task_count", True),
            "values must be integers",
        ),
    ],
)
def test_profile_rejects_schema_path_and_numeric_drift_before_loading_components(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    match: str,
) -> None:
    copied = _copy_definition(tmp_path)
    _rewrite(copied, mutate)

    with pytest.raises(IntegrationProfileError, match=match):
        load_integration_profile(copied, repo_root=REPO_ROOT)


def test_profile_rejects_a_component_directory_symlink_escape(
    tmp_path: Path,
) -> None:
    copied = _copy_definition(tmp_path)
    component = copied.parent.parent / "integration-workflows-v1"
    outside = tmp_path / "outside-component"
    shutil.copytree(component, outside)
    shutil.rmtree(component)
    try:
        component.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(IntegrationProfileError, match="may not be a symlink"):
        load_integration_profile(copied, repo_root=REPO_ROOT)


def test_case_selection_rejects_unknown_and_duplicate_aliases() -> None:
    with pytest.raises(IntegrationProfileError, match="unknown integration"):
        load_integration_profile(
            PROFILE_PATH,
            unit_ids=("INT22-NOT-A-WORKFLOW",),
            repo_root=REPO_ROOT,
        )
    with pytest.raises(IntegrationProfileError, match="same integration unit"):
        load_integration_profile(
            PROFILE_PATH,
            unit_ids=(
                "INT22-WEATHER",
                "INT22-INTERACTIVE-WEATHER-BUILD",
            ),
            repo_root=REPO_ROOT,
        )
