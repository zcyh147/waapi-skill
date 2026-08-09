from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from tests.semantic.support import codex_integration_workflows as integration
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
    canonicalize_integration_unit_ids,
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


def _copy_definition(
    tmp_path: Path,
    *,
    include_projects: bool = False,
) -> Path:
    repository = tmp_path / "repo"
    target = repository / "tests" / "semantic" / "data"
    for name in (
        "integration",
        "integration-workflows-v1",
        "integration-workflows-v2",
    ):
        shutil.copytree(DATA_ROOT / name, target / name)
    if include_projects:
        for version in VERSIONS:
            shutil.copytree(
                REPO_ROOT / "tests" / "_org" / version,
                repository / "tests" / "_org" / version,
            )
    return target / "integration" / "profile.json"


def _copied_repo_root(profile_path: Path) -> Path:
    return profile_path.parents[4]


def _replace_with_symlink(path: Path, target: Path) -> None:
    path.unlink()
    try:
        path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")


def _simulate_reparse_before_resolve(
    monkeypatch: pytest.MonkeyPatch,
    target: Path,
) -> None:
    real_lstat = Path.lstat
    real_resolve = Path.resolve
    target_stat = real_lstat(target)
    reparse_stat = SimpleNamespace(
        st_mode=target_stat.st_mode,
        st_file_attributes=0x400,
    )

    def simulated_lstat(path: Path):
        if path == target:
            return reparse_stat
        return real_lstat(path)

    def guarded_resolve(path: Path, strict: bool = False) -> Path:
        if path == target:
            pytest.fail("reparse target was resolved before rejection")
        return real_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "lstat", simulated_lstat)
    monkeypatch.setattr(Path, "resolve", guarded_resolve)


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
    copied = _copy_definition(tmp_path, include_projects=True)
    repository = _copied_repo_root(copied)
    first = load_integration_profile(copied, repo_root=repository)
    workflows = copied.parent.parent / "integration-workflows-v1" / "workflows.json"
    workflows.write_bytes(workflows.read_bytes() + b"\n")
    second = load_integration_profile(copied, repo_root=repository)

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
            lambda root: root["component_profiles"].__setitem__(
                0,
                "../integration-workflows-v1-near/profile.json",
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
        load_integration_profile(
            copied,
            repo_root=_copied_repo_root(copied),
        )


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
        load_integration_profile(
            copied,
            repo_root=_copied_repo_root(copied),
        )


def test_preflight_rejects_workflows_symlink_escape_before_legacy_loaders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = _copy_definition(tmp_path)
    workflows = (
        copied.parent.parent
        / "integration-workflows-v1"
        / "workflows.json"
    )
    outside = tmp_path / "outside-workflows.json"
    shutil.copy2(workflows, outside)
    _replace_with_symlink(workflows, outside)

    def forbidden_loader(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("legacy loader ran before component source preflight")

    monkeypatch.setattr(
        integration,
        "load_integration_workflows_profile",
        forbidden_loader,
    )
    monkeypatch.setattr(
        integration,
        "load_integration_workflows_v2_profile",
        forbidden_loader,
    )
    with pytest.raises(
        IntegrationProfileError,
        match="component-01/workflows.json may not be a link",
    ):
        load_integration_profile(
            copied,
            repo_root=_copied_repo_root(copied),
        )


def test_preflight_rejects_near_baseline_symlink_before_legacy_loaders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = _copy_definition(tmp_path)
    baseline = (
        copied.parent.parent
        / "integration-workflows-v2"
        / "baseline-2022.1.json"
    )
    near = baseline.with_name("baseline-2022.1-near.json")
    shutil.copy2(baseline, near)
    _replace_with_symlink(baseline, near)

    def forbidden_loader(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("legacy loader ran before component source preflight")

    monkeypatch.setattr(
        integration,
        "load_integration_workflows_profile",
        forbidden_loader,
    )
    monkeypatch.setattr(
        integration,
        "load_integration_workflows_v2_profile",
        forbidden_loader,
    )
    with pytest.raises(
        IntegrationProfileError,
        match="component-02/baseline-2022.1.json may not be a link",
    ):
        load_integration_profile(
            copied,
            repo_root=_copied_repo_root(copied),
        )


def test_preflight_requires_fixed_sources_to_be_regular_files(
    tmp_path: Path,
) -> None:
    copied = _copy_definition(tmp_path)
    workflows = (
        copied.parent.parent
        / "integration-workflows-v2"
        / "workflows.json"
    )
    workflows.unlink()
    workflows.mkdir()

    with pytest.raises(
        IntegrationProfileError,
        match="component-02/workflows.json must be a regular file",
    ):
        load_integration_profile(
            copied,
            repo_root=_copied_repo_root(copied),
        )


def test_meta_profile_reparse_is_rejected_before_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = _copy_definition(tmp_path)
    _simulate_reparse_before_resolve(monkeypatch, copied)

    with pytest.raises(
        IntegrationProfileError,
        match="integration profile may not be a symlink or reparse point",
    ):
        load_integration_profile(
            copied,
            repo_root=_copied_repo_root(copied),
        )


def test_component_profile_reparse_is_rejected_before_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = _copy_definition(tmp_path)
    component_profile = (
        copied.parent.parent
        / "integration-workflows-v1"
        / "profile.json"
    )
    _simulate_reparse_before_resolve(monkeypatch, component_profile)

    with pytest.raises(
        IntegrationProfileError,
        match="component-01 may not be a symlink or reparse point",
    ):
        load_integration_profile(
            copied,
            repo_root=_copied_repo_root(copied),
        )


def test_component_directory_reparse_is_rejected_before_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = _copy_definition(tmp_path)
    component_root = (
        copied.parent.parent / "integration-workflows-v2"
    )
    _simulate_reparse_before_resolve(monkeypatch, component_root)

    with pytest.raises(
        IntegrationProfileError,
        match="component-02 may not be a symlink or reparse point",
    ):
        load_integration_profile(
            copied,
            repo_root=_copied_repo_root(copied),
        )


def test_baseline_root_reparse_is_rejected_before_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = _copy_definition(tmp_path)
    baseline_root = (
        REPO_ROOT
        / "tests"
        / "semantic"
        / "data"
        / "integration-workflows-v2"
    )
    _simulate_reparse_before_resolve(monkeypatch, baseline_root)

    with pytest.raises(
        IntegrationProfileError,
        match="component-02 repository root may not be a link",
    ):
        load_integration_profile(copied, repo_root=REPO_ROOT)


def test_baseline_source_reparse_is_rejected_before_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = _copy_definition(tmp_path)
    baseline = (
        REPO_ROOT
        / "tests"
        / "semantic"
        / "data"
        / "integration-workflows-v2"
        / "baseline-2025.1.json"
    )
    _simulate_reparse_before_resolve(monkeypatch, baseline)

    with pytest.raises(
        IntegrationProfileError,
        match="component-02/baseline-2025.1.json may not be a link",
    ):
        load_integration_profile(copied, repo_root=REPO_ROOT)


def test_public_unit_id_canonicalizer_is_closed() -> None:
    assert canonicalize_integration_unit_ids(
        (
            "INT22-WEATHER",
            "INT25-V2-RIFLE-SAFE-REIMPORT",
        )
    ) == ("INT22-WEATHER", "INT25-RIFLE")
    assert canonicalize_integration_unit_ids(()) == ()
    with pytest.raises(IntegrationProfileError, match="unknown integration"):
        canonicalize_integration_unit_ids(("INT22-NEAR-WEATHER",))
    with pytest.raises(IntegrationProfileError, match="same integration unit"):
        canonicalize_integration_unit_ids(
            (
                "INT22-WEATHER",
                "INT22-INTERACTIVE-WEATHER-BUILD",
            )
        )


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
