from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_integration_workflows_v2 import (
    PROFILE_ID,
    TASK_COUNT,
    TRANSACTION_COUNT,
    USER_TURN_COUNT,
    VERSIONS,
    WORKFLOW_IDS,
    load_integration_workflows_v2_profile,
)


PROFILE_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "integration-workflows-v2"
    / "profile.json"
)


def _dependency_args(tmp_path: Path) -> list[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    codex = tmp_path / "codex.exe"
    auth = tmp_path / "auth.json"
    live = tmp_path / "live-environment.json"
    codex.write_text("not invoked\n", encoding="utf-8")
    codex.chmod(0o755)
    auth.write_text("{}\n", encoding="utf-8")
    live.write_text("{}\n", encoding="utf-8")
    return [
        "--codex-binary",
        str(codex),
        "--auth-json",
        str(auth),
        "--live-config",
        str(live),
    ]


def _matrix_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--profile",
        PROFILE_ID,
        *_dependency_args(tmp_path),
        *extra,
    ]


def _campaign_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--campaign-root",
        str(tmp_path / "campaign"),
        "--profile",
        PROFILE_ID,
        *_dependency_args(tmp_path),
        *extra,
    ]


def _units() -> tuple[Any, ...]:
    return load_integration_workflows_v2_profile(PROFILE_PATH).units


def test_matrix_v2_integration_defaults_and_explicit_terra_lock(
    tmp_path: Path,
) -> None:
    defaults = matrix.parse_args(_matrix_args(tmp_path))
    explicit = matrix.parse_args(
        _matrix_args(
            tmp_path / "explicit",
            "--model",
            "gpt-5.6-terra",
            "--reasoning-effort",
            "medium",
            "--service-tier",
            "default",
            "--version",
            "2022.1",
            "--version",
            "2025.1",
        )
    )

    assert defaults.profile == PROFILE_ID
    assert defaults.model == explicit.model == "gpt-5.6-terra"
    assert defaults.reasoning_effort == explicit.reasoning_effort == "medium"
    assert defaults.service_tier == explicit.service_tier == "default"
    assert defaults.suite_path == matrix.DEFAULT_INTEGRATION_WORKFLOWS_V2_SUITE.resolve()
    assert defaults.iteration_root == (
        matrix.DEFAULT_INTEGRATION_WORKFLOWS_V2_ITERATION_ROOT.resolve()
    )
    assert defaults.versions == ()
    assert explicit.versions == VERSIONS


def test_campaign_v2_integration_defaults_and_explicit_terra_lock(
    tmp_path: Path,
) -> None:
    defaults = campaign.parse_args(_campaign_args(tmp_path))
    explicit = campaign.parse_args(
        _campaign_args(
            tmp_path / "explicit",
            "--model",
            "gpt-5.6-terra",
            "--reasoning-effort",
            "medium",
            "--service-tier",
            "default",
            "--version",
            "2022.1",
            "--version",
            "2025.1",
        )
    )

    assert defaults.profile == PROFILE_ID
    assert defaults.model == explicit.model == "gpt-5.6-terra"
    assert defaults.reasoning_effort == explicit.reasoning_effort == "medium"
    assert defaults.service_tier == explicit.service_tier == "default"
    assert defaults.suite_path == matrix.DEFAULT_INTEGRATION_WORKFLOWS_V2_SUITE.resolve()
    assert defaults.campaign_root == (tmp_path / "campaign").resolve()
    assert defaults.versions == ()
    assert explicit.versions == VERSIONS


@pytest.mark.parametrize(
    "override",
    (
        ("--model", "gpt-5.6-sol"),
        ("--reasoning-effort", "high"),
        ("--service-tier", "priority"),
    ),
)
@pytest.mark.parametrize("surface", ("matrix", "campaign"))
def test_v2_integration_profile_rejects_terra_lock_overrides(
    tmp_path: Path,
    surface: str,
    override: tuple[str, str],
) -> None:
    argv = (
        _matrix_args(tmp_path, *override)
        if surface == "matrix"
        else _campaign_args(tmp_path, *override)
    )
    parser = matrix.parse_args if surface == "matrix" else campaign.parse_args

    with pytest.raises(SystemExit):
        parser(argv)


@pytest.mark.parametrize("version", ("2021.1", "2023.1", "2024.1"))
@pytest.mark.parametrize("surface", ("matrix", "campaign"))
def test_v2_integration_profile_rejects_versions_outside_2022_and_2025(
    tmp_path: Path,
    surface: str,
    version: str,
) -> None:
    argv = (
        _matrix_args(tmp_path, "--version", version)
        if surface == "matrix"
        else _campaign_args(tmp_path, "--version", version)
    )
    parser = matrix.parse_args if surface == "matrix" else campaign.parse_args

    with pytest.raises(SystemExit):
        parser(argv)


def test_matrix_dispatches_to_v2_loader_and_requires_committed_baselines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = SimpleNamespace(unit_id="INT25-V2-RIFLE-SAFE-REIMPORT")
    calls: list[tuple[Path, dict[str, Any]]] = []

    def load(path: Path, **kwargs: Any) -> Any:
        calls.append((path, kwargs))
        return SimpleNamespace(units=(selected,))

    module = SimpleNamespace(load_integration_workflows_v2_profile=load)
    real_import = matrix.importlib.import_module

    def import_module(name: str) -> Any:
        if name == "tests.semantic.support.codex_integration_workflows_v2":
            return module
        return real_import(name)

    monkeypatch.setattr(matrix.importlib, "import_module", import_module)
    options = matrix.parse_args(
        _matrix_args(
            tmp_path,
            "--case-id",
            selected.unit_id,
            "--version",
            "2025.1",
        )
    )

    assert matrix.load_heavy_v3_units(options) == (selected,)
    assert calls == [
        (
            options.suite_path,
            {
                "unit_ids": (selected.unit_id,),
                "versions": ("2025.1",),
                "require_committed_baselines": True,
                "repo_root": matrix.REPO_ROOT,
            },
        )
    ]


def test_campaign_child_selection_preserves_v2_profile_and_reviewed_totals(
    tmp_path: Path,
) -> None:
    options = campaign.parse_args(_campaign_args(tmp_path))
    units = _units()

    argv = campaign.build_heavy_v3_child_argv(
        options,
        units=units,
        matrix_root=tmp_path / "matrix",
    )
    request = campaign.heavy_v3_child_request(
        options,
        units=units,
        argv=argv,
    )

    assert len(units) == TASK_COUNT
    assert sum(unit.transaction_count for unit in units) == TRANSACTION_COUNT
    assert sum(unit.user_turn_count for unit in units) == USER_TURN_COUNT
    assert {unit.workflow_id for unit in units} == set(WORKFLOW_IDS)
    assert argv[argv.index("--profile") + 1] == PROFILE_ID
    assert [
        argv[index + 1]
        for index, value in enumerate(argv)
        if value == "--case-id"
    ] == [unit.unit_id for unit in units]
    assert request["request"]["profile"] == PROFILE_ID
    assert request["request"]["approval_policy"] == "never"
    assert request["request"]["sequential"] is True
    assert request["scenario_ids"] == [unit.unit_id for unit in units]


def test_campaign_resume_child_can_select_only_the_pending_v2_unit(
    tmp_path: Path,
) -> None:
    options = campaign.parse_args(_campaign_args(tmp_path))
    pending = _units()[-1:]

    argv = campaign.build_heavy_v3_child_argv(
        options,
        units=pending,
        matrix_root=tmp_path / "matrix-resume",
    )

    assert [
        argv[index + 1]
        for index, value in enumerate(argv)
        if value == "--case-id"
    ] == [pending[0].unit_id]
    assert argv[argv.index("--profile") + 1] == PROFILE_ID
    assert argv[argv.index("--model") + 1] == "gpt-5.6-terra"
    assert argv[argv.index("--reasoning-effort") + 1] == "medium"
    assert argv[argv.index("--service-tier") + 1] == "default"
