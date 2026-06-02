from __future__ import annotations

import json
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

import tests.destructive.support.live_environment as live_env  # pyright: ignore[reportMissingImports]
from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    INSTALLED_SAMPLE_PROJECT_2023_1_ROOT,
    LiveEnvironmentError,
    parse_live_environment,
    path_is_under,
    path_is_under_immutable_sample_source,
    require_destructive_environment,
    require_live_environment,
    resolve_sample_project_source,
)


def make_project(root: Path, name: str = "SampleProject.wproj") -> Path:
    project = root / name
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("<WwiseDocument />", encoding="utf-8")
    return project


def make_console(tmp_path: Path) -> Path:
    console = tmp_path / "WwiseConsole.sh"
    console.parent.mkdir(parents=True, exist_ok=True)
    console.write_text("#!/bin/sh\n", encoding="utf-8")
    console.chmod(0o755)
    return console


def test_live_and_destructive_flags_are_canonicalized() -> None:
    disabled = parse_live_environment({"WWISE_DESTRUCTIVE": "1"})
    assert disabled.live_enabled is False
    assert disabled.destructive_enabled is False

    enabled = parse_live_environment({"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1"})
    assert enabled.live_enabled is True
    assert enabled.destructive_enabled is True


def test_sample_project_path_is_immutable_source_and_defaults_only_when_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    default_root = tmp_path / "DefaultSample"
    explicit_root = tmp_path / "ConfiguredSample"
    default_project = make_project(default_root, "Default.wproj")
    explicit_project = make_project(explicit_root, "Configured.wproj")
    monkeypatch.setattr(live_env, "DEFAULT_SAMPLE_PROJECT_ROOT", default_root)

    assert resolve_sample_project_source({}) == default_project
    assert resolve_sample_project_source({"WWISE_SAMPLE_PROJECT_PATH": str(explicit_root)}) == explicit_project

    monkeypatch.setattr(live_env, "DEFAULT_SAMPLE_PROJECT_ROOT", tmp_path / "MissingDefault")
    assert resolve_sample_project_source({}) is None


def test_live_environment_reads_versioned_local_json_config(tmp_path: Path) -> None:
    console = make_console(tmp_path / "configured")
    sample_project = make_project(tmp_path / "configured")
    sandbox_root = tmp_path / "configured-sandbox"
    config_path = tmp_path / "live-environment.json"
    config_path.write_text(
        json.dumps(
            {
                "versions": {
                    "2024.1": {
                        "wwise_console": str(console),
                        "sample_project": str(sample_project),
                        "sandbox_root": str(sandbox_root),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    contract = require_live_environment(
        {
            "WWISE_LIVE": "1",
            "WWISE_VERSION": "2024.1",
            "WWISE_TEST_CONFIG": str(config_path),
        }
    )

    assert contract.console_path == console.resolve(strict=False)
    assert contract.sample_project_source == sample_project.resolve(strict=False)
    assert contract.sandbox_root == sandbox_root.resolve(strict=False)


def test_live_environment_env_overrides_versioned_json_config_for_exact_versions(tmp_path: Path) -> None:
    configured_console = make_console(tmp_path / "configured" / "WwiseConsole.sh")
    configured_project = make_project(tmp_path / "configured" / "SampleProject.wproj")
    configured_sandbox = tmp_path / "configured-sandbox"
    override_console = make_console(tmp_path / "override" / "WwiseConsole.sh")
    override_project = make_project(tmp_path / "override" / "SampleProject.wproj")
    override_sandbox = tmp_path / "override-sandbox"
    config_path = tmp_path / "live-environment.json"
    config_path.write_text(
        json.dumps(
            {
                "versions": {
                    "2024.1": {
                        "wwise_console": str(configured_console),
                        "sample_project": str(configured_project),
                        "sandbox_root": str(configured_sandbox),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    contract = require_live_environment(
        {
            "WWISE_LIVE": "1",
            "WWISE_VERSION": "2024.1",
            "WWISE_TEST_CONFIG": str(config_path),
            "WWISE_CONSOLE": str(override_console),
            "WWISE_SAMPLE_PROJECT_PATH": str(override_project),
            "WWISE_SANDBOX_ROOT": str(override_sandbox),
        }
    )

    assert contract.console_path == override_console.resolve(strict=False)
    assert contract.sample_project_source == override_project.resolve(strict=False)
    assert contract.sandbox_root == override_sandbox.resolve(strict=False)


def test_fixture_project_is_read_only_live_project_not_destructive_without_sandbox(tmp_path: Path) -> None:
    console = make_console(tmp_path)
    fixture = make_project(tmp_path / "fixture", "fixture.wproj")

    contract = require_live_environment(
        {
            "WWISE_LIVE": "1",
            "WWISE_CONSOLE": str(console),
            "WWISE_FIXTURE_PROJECT": str(fixture),
        }
    )

    assert contract.active_live_project == fixture
    assert contract.active_destructive_project is None

    with pytest.raises(LiveEnvironmentError, match="WWISE_SANDBOX_ROOT is required"):
        require_destructive_environment(
            {
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_CONSOLE": str(console),
                "WWISE_FIXTURE_PROJECT": str(fixture),
            }
        )


def test_destructive_project_must_be_under_active_sandbox_root(tmp_path: Path) -> None:
    console = make_console(tmp_path)
    sandbox = tmp_path / "sandbox"
    sandbox_project = make_project(sandbox / "copy", "copy.wproj")
    outside_project = make_project(tmp_path / "outside", "outside.wproj")

    contract = require_destructive_environment(
        {
            "WWISE_LIVE": "1",
            "WWISE_DESTRUCTIVE": "1",
            "WWISE_CONSOLE": str(console),
            "WWISE_FIXTURE_PROJECT": str(sandbox_project),
            "WWISE_SANDBOX_ROOT": str(sandbox),
        }
    )
    assert contract.active_destructive_project == sandbox_project.resolve(strict=False)

    with pytest.raises(LiveEnvironmentError, match="must be under active WWISE_SANDBOX_ROOT"):
        require_destructive_environment(
            {
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_CONSOLE": str(console),
                "WWISE_FIXTURE_PROJECT": str(outside_project),
                "WWISE_SANDBOX_ROOT": str(sandbox),
            }
        )


def test_destructive_guard_rejects_sample_source_as_active_project(tmp_path: Path) -> None:
    console = make_console(tmp_path)
    sandbox = tmp_path / "sandbox"
    sample_project = make_project(sandbox / "SampleProject", "SampleProject.wproj")

    with pytest.raises(LiveEnvironmentError, match="must not launch the immutable SampleProject source"):
        require_destructive_environment(
            {
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_CONSOLE": str(console),
                "WWISE_FIXTURE_PROJECT": str(sample_project),
                "WWISE_SAMPLE_PROJECT_PATH": str(sample_project),
                "WWISE_SANDBOX_ROOT": str(sandbox),
            }
        )


def test_destructive_guard_rejects_installed_2023_sample_project_targets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = make_console(tmp_path)
    installed_root = tmp_path / "Applications" / "Audiokinetic" / "SampleProject2023.1.19.8928" / "SampleProject"
    installed_project = make_project(installed_root, "SampleProject.wproj")
    monkeypatch.setattr(live_env, "INSTALLED_SAMPLE_PROJECT_2023_1_ROOT", installed_root)

    with pytest.raises(LiveEnvironmentError, match="immutable installed SampleProject"):
        require_destructive_environment(
            {
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_CONSOLE": str(console),
                "WWISE_FIXTURE_PROJECT": str(installed_project),
                "WWISE_SANDBOX_ROOT": str(installed_root),
            }
        )


def test_installed_2023_sample_project_source_path_is_guarded() -> None:
    expected = live_env.INSTALLED_SAMPLE_PROJECT_2023_1_ROOT

    assert INSTALLED_SAMPLE_PROJECT_2023_1_ROOT == expected
    assert path_is_under_immutable_sample_source(expected / "SampleProject.wproj")


def test_live_prerequisites_fail_fast_without_fake_fallbacks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(live_env, "DEFAULT_SAMPLE_PROJECT_ROOT", tmp_path / "missing-default")
    monkeypatch.setattr(
        live_env,
        "LIVE_VERSION_PATHS",
        {
            live_env.SUPPORTED_WWISE_VERSION: live_env._LiveVersionPaths(
                version=live_env.SUPPORTED_WWISE_VERSION,
                console_path=live_env.WWISE_2022_1_CONSOLE_PATH,
                sample_project_path=tmp_path / "missing-default",
            )
        },
    )
    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_live_environment({"WWISE_LIVE": "1", "WWISE_CONSOLE": str(tmp_path / "missing-console")})

    message = str(exc_info.value)
    assert "missing immutable SampleProject source" in message
    assert "WwiseConsole is unavailable" in message


def test_path_is_under_accepts_root_and_descendants_only(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    assert path_is_under(root, root)
    assert path_is_under(root / "copy" / "project.wproj", root)
    assert not path_is_under(tmp_path / "other" / "project.wproj", root)
