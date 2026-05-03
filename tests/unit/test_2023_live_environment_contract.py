from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

import tests.destructive.support.live_environment as live_env  # pyright: ignore[reportMissingImports]
from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    LiveEnvironmentError,
    parse_live_environment,
    require_destructive_environment,
    require_live_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ORG_FIXTURE_2023_ROOT = REPO_ROOT / "tests" / "_org" / "2023.1"


def make_console(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def make_project(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<WwiseDocument />\n", encoding="utf-8")
    return path


def configure_2023_contract(
    monkeypatch: pytest.MonkeyPatch,
    *,
    console_path: Path,
    sample_project_path: Path,
) -> None:
    monkeypatch.setattr(live_env, "WWISE_2023_1_CONSOLE_PATH", console_path)
    monkeypatch.setattr(live_env, "WWISE_2023_1_SAMPLE_PROJECT_PATH", sample_project_path)
    monkeypatch.setattr(live_env, "INSTALLED_SAMPLE_PROJECT_2023_1_ROOT", sample_project_path.parent)
    monkeypatch.setattr(
        live_env,
        "LIVE_VERSION_PATHS",
        {
            live_env.SUPPORTED_WWISE_VERSION: live_env.LIVE_VERSION_PATHS[live_env.SUPPORTED_WWISE_VERSION],
            "2023.1": live_env._LiveVersionPaths(
                version="2023.1",
                console_path=console_path,
                sample_project_path=sample_project_path,
                require_exact_paths=True,
            ),
        },
    )


def test_2023_live_environment_uses_exact_console_and_sample_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = make_console(
        tmp_path / "Applications" / "Audiokinetic" / "Wwise2023.1.19.8928" / "Wwise.app" / "Contents" / "Tools" / "WwiseConsole.sh"
    )
    sample_project = make_project(
        tmp_path
        / "Applications"
        / "Audiokinetic"
        / "SampleProject2023.1.19.8928"
        / "SampleProject"
        / "SampleProject.wproj"
    )
    configure_2023_contract(monkeypatch, console_path=console, sample_project_path=sample_project)

    parsed = parse_live_environment({"WWISE_VERSION": "2023.1"})
    assert parsed.live_enabled is False
    assert parsed.console_path == console
    assert parsed.sample_project_source == sample_project

    contract = require_live_environment({"WWISE_LIVE": "1", "WWISE_VERSION": "2023.1"})
    assert contract.version == "2023.1"
    assert contract.console_path == console
    assert contract.sample_project_source == sample_project


def test_2023_live_environment_rejects_wrong_console_or_sample_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = make_console(tmp_path / "exact" / "WwiseConsole.sh")
    sample_project = make_project(tmp_path / "exact" / "SampleProject.wproj")
    wrong_console = make_console(tmp_path / "wrong" / "WwiseConsole.sh")
    wrong_project = make_project(tmp_path / "wrong" / "SampleProject.wproj")
    configure_2023_contract(monkeypatch, console_path=console, sample_project_path=sample_project)

    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_live_environment(
            {
                "WWISE_LIVE": "1",
                "WWISE_VERSION": "2023.1",
                "WWISE_CONSOLE": str(wrong_console),
                "WWISE_SAMPLE_PROJECT_PATH": str(wrong_project),
            }
        )

    message = str(exc_info.value)
    assert "exact 2023.1 WwiseConsole path" in message
    assert "exact 2023.1 SampleProject path" in message


def test_2023_live_environment_does_not_fall_back_to_2022_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console_2022 = make_console(tmp_path / "Wwise2022.1.19.8584" / "WwiseConsole.sh")
    sample_2022 = make_project(tmp_path / "Wwise2022.1.19.8584" / "SampleProject" / "SampleProject.wproj")
    missing_console_2023 = tmp_path / "Wwise2023.1.19.8928" / "WwiseConsole.sh"
    missing_sample_2023 = tmp_path / "SampleProject2023.1.19.8928" / "SampleProject" / "SampleProject.wproj"
    monkeypatch.setattr(
        live_env,
        "LIVE_VERSION_PATHS",
        {
            live_env.SUPPORTED_WWISE_VERSION: live_env._LiveVersionPaths(
                version=live_env.SUPPORTED_WWISE_VERSION,
                console_path=console_2022,
                sample_project_path=sample_2022.parent,
            ),
            "2023.1": live_env._LiveVersionPaths(
                version="2023.1",
                console_path=missing_console_2023,
                sample_project_path=missing_sample_2023,
                require_exact_paths=True,
            ),
        },
    )

    parsed = parse_live_environment({"WWISE_VERSION": "2023.1"})
    assert parsed.console_path == missing_console_2023
    assert parsed.sample_project_source == missing_sample_2023
    assert parsed.console_path != console_2022
    assert parsed.sample_project_source != sample_2022

    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_live_environment({"WWISE_LIVE": "1", "WWISE_VERSION": "2023.1"})
    message = str(exc_info.value)
    assert str(missing_console_2023) in message
    assert str(missing_sample_2023) in message
    assert str(console_2022) not in message
    assert str(sample_2022) not in message


def test_2023_destructive_environment_requires_sandbox_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = make_console(tmp_path / "exact" / "WwiseConsole.sh")
    installed_project = make_project(tmp_path / "installed" / "SampleProject" / "SampleProject.wproj")
    sandbox_root = tmp_path / "sandbox"
    sandbox_project = make_project(sandbox_root / "copy" / "SampleProject.wproj")
    configure_2023_contract(monkeypatch, console_path=console, sample_project_path=installed_project)

    valid = require_destructive_environment(
        {
            "WWISE_LIVE": "1",
            "WWISE_DESTRUCTIVE": "1",
            "WWISE_VERSION": "2023.1",
            "WWISE_FIXTURE_PROJECT": str(sandbox_project),
            "WWISE_SANDBOX_ROOT": str(sandbox_root),
        }
    )
    assert valid.active_destructive_project == sandbox_project.resolve(strict=False)

    installed_env = {
        "WWISE_LIVE": "1",
        "WWISE_DESTRUCTIVE": "1",
        "WWISE_VERSION": "2023.1",
        "WWISE_FIXTURE_PROJECT": str(installed_project),
        "WWISE_SANDBOX_ROOT": str(installed_project.parent),
    }
    org_fixture_env = {
        "WWISE_LIVE": "1",
        "WWISE_DESTRUCTIVE": "1",
        "WWISE_VERSION": "2023.1",
        "WWISE_FIXTURE_PROJECT": str(ORG_FIXTURE_2023_ROOT / "SampleProject.wproj"),
        "WWISE_SANDBOX_ROOT": str(ORG_FIXTURE_2023_ROOT),
    }

    with pytest.raises(LiveEnvironmentError, match="immutable installed SampleProject"):
        require_destructive_environment(installed_env)
    with pytest.raises(LiveEnvironmentError, match="tests/_org"):
        require_destructive_environment(org_fixture_env)
