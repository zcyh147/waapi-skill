from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

import tests.destructive.support.live_environment as live_env  # pyright: ignore[reportMissingImports]
from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    LiveEnvironmentError,
    parse_live_environment,
    require_live_environment,
)


def make_console(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def make_project(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<WwiseDocument />\n", encoding="utf-8")
    return path


def configure_2021_contract(
    monkeypatch: pytest.MonkeyPatch,
    *,
    console_path: Path,
    sample_project_path: Path,
) -> None:
    monkeypatch.setattr(live_env, "WWISE_2021_1_CONSOLE_PATH", console_path)
    monkeypatch.setattr(live_env, "WWISE_2021_1_SAMPLE_PROJECT_PATH", sample_project_path)
    monkeypatch.setattr(live_env, "INSTALLED_SAMPLE_PROJECT_2021_1_ROOT", sample_project_path.parent)
    monkeypatch.setattr(
        live_env,
        "LIVE_VERSION_PATHS",
        {
            live_env.SUPPORTED_WWISE_VERSION: live_env.LIVE_VERSION_PATHS[live_env.SUPPORTED_WWISE_VERSION],
            "2021.1": live_env._LiveVersionPaths(
                version="2021.1",
                console_path=console_path,
                sample_project_path=sample_project_path,
                require_exact_paths=True,
            ),
            "2023.1": live_env.LIVE_VERSION_PATHS["2023.1"],
            "2024.1": live_env.LIVE_VERSION_PATHS["2024.1"],
            "2025.1": live_env.LIVE_VERSION_PATHS["2025.1"],
        },
    )


def test_2021_1_live_environment_uses_exact_console_and_sample_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = make_console(
        tmp_path / "Applications" / "Audiokinetic" / "Wwise2021.1.14.8108" / "Wwise.app" / "Contents" / "Tools" / "WwiseConsole.sh"
    )
    sample_project = make_project(
        tmp_path
        / "Applications"
        / "Audiokinetic"
        / "SampleProject2021.1.14.8108"
        / "SampleProject"
        / "SampleProject.wproj"
    )
    configure_2021_contract(monkeypatch, console_path=console, sample_project_path=sample_project)

    parsed = parse_live_environment({"WWISE_VERSION": "2021.1"})
    assert parsed.live_enabled is False
    assert parsed.console_path == console
    assert parsed.sample_project_source == sample_project

    contract = require_live_environment({"WWISE_LIVE": "1", "WWISE_VERSION": "2021.1"})
    assert contract.version == "2021.1"
    assert contract.console_path == console
    assert contract.sample_project_source == sample_project


def test_2021_1_live_environment_rejects_wrong_console_or_sample_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = make_console(tmp_path / "exact" / "WwiseConsole.sh")
    sample_project = make_project(tmp_path / "exact" / "SampleProject.wproj")
    wrong_console = make_console(tmp_path / "wrong" / "WwiseConsole.sh")
    wrong_project = make_project(tmp_path / "wrong" / "SampleProject.wproj")
    configure_2021_contract(monkeypatch, console_path=console, sample_project_path=sample_project)

    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_live_environment(
            {
                "WWISE_LIVE": "1",
                "WWISE_VERSION": "2021.1",
                "WWISE_CONSOLE": str(wrong_console),
                "WWISE_SAMPLE_PROJECT_PATH": str(wrong_project),
            }
        )

    message = str(exc_info.value)
    assert "exact 2021.1 WwiseConsole path" in message
    assert "exact 2021.1 SampleProject path" in message


def test_2021_1_live_environment_does_not_fall_back_to_2022_2023_2024_2025_or_generic_2021(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console_2022 = make_console(tmp_path / "Wwise2022.1.19.8584" / "WwiseConsole.sh")
    sample_2022 = make_project(tmp_path / "Wwise2022.1.19.8584" / "SampleProject" / "SampleProject.wproj")
    console_2023 = make_console(tmp_path / "Wwise2023.1.19.8928" / "WwiseConsole.sh")
    sample_2023 = make_project(tmp_path / "SampleProject2023.1.19.8928" / "SampleProject" / "SampleProject.wproj")
    console_2024 = make_console(tmp_path / "Wwise2024.1.13.9056" / "WwiseConsole.sh")
    sample_2024 = make_project(tmp_path / "SampleProject2024.1.13.9056" / "SampleProject" / "SampleProject.wproj")
    console_2025 = make_console(tmp_path / "Wwise2025.1.7.9143" / "WwiseConsole.sh")
    sample_2025 = make_project(tmp_path / "SampleProject2025.1.7.9143" / "SampleProject" / "SampleProject.wproj")
    missing_console_2021_1 = tmp_path / "Wwise2021.1.14.8108" / "WwiseConsole.sh"
    missing_sample_2021_1 = tmp_path / "SampleProject2021.1.14.8108" / "SampleProject" / "SampleProject.wproj"
    monkeypatch.setattr(
        live_env,
        "LIVE_VERSION_PATHS",
        {
            live_env.SUPPORTED_WWISE_VERSION: live_env._LiveVersionPaths(
                version=live_env.SUPPORTED_WWISE_VERSION,
                console_path=console_2022,
                sample_project_path=sample_2022.parent,
            ),
            "2021": live_env._LiveVersionPaths(
                version="2021",
                console_path=console_2022,
                sample_project_path=sample_2022.parent,
                require_exact_paths=True,
            ),
            "2021.1": live_env._LiveVersionPaths(
                version="2021.1",
                console_path=missing_console_2021_1,
                sample_project_path=missing_sample_2021_1,
                require_exact_paths=True,
            ),
            "2023.1": live_env._LiveVersionPaths(
                version="2023.1",
                console_path=console_2023,
                sample_project_path=sample_2023,
                require_exact_paths=True,
            ),
            "2024.1": live_env._LiveVersionPaths(
                version="2024.1",
                console_path=console_2024,
                sample_project_path=sample_2024,
                require_exact_paths=True,
            ),
            "2025.1": live_env._LiveVersionPaths(
                version="2025.1",
                console_path=console_2025,
                sample_project_path=sample_2025,
                require_exact_paths=True,
            ),
        },
    )

    parsed = parse_live_environment({"WWISE_VERSION": "2021.1"})
    assert parsed.console_path == missing_console_2021_1
    assert parsed.sample_project_source == missing_sample_2021_1
    assert parsed.console_path not in {console_2022, console_2023, console_2024, console_2025}
    assert parsed.sample_project_source not in {sample_2022, sample_2023, sample_2024, sample_2025}

    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_live_environment({"WWISE_LIVE": "1", "WWISE_VERSION": "2021.1"})
    message = str(exc_info.value)
    assert str(missing_console_2021_1) in message
    assert str(missing_sample_2021_1) in message
    assert str(console_2022) not in message
    assert str(sample_2022) not in message
    assert str(console_2023) not in message
    assert str(sample_2023) not in message
    assert str(console_2024) not in message
    assert str(sample_2024) not in message
    assert str(console_2025) not in message
    assert str(sample_2025) not in message


def test_2021_version_alias_is_rejected_without_falling_back_to_2021_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = make_console(tmp_path / "exact" / "WwiseConsole.sh")
    sample_project = make_project(tmp_path / "exact" / "SampleProject.wproj")
    configure_2021_contract(monkeypatch, console_path=console, sample_project_path=sample_project)

    parsed = parse_live_environment({"WWISE_VERSION": "2021"})
    assert parsed.console_path is None
    assert parsed.sample_project_source is None

    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_live_environment({"WWISE_LIVE": "1", "WWISE_VERSION": "2021"})
    assert "WWISE_VERSION must be one of" in str(exc_info.value)
    assert "got '2021'" in str(exc_info.value)
