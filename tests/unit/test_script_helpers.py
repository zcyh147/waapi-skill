from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from scripts import config as script_config  # pyright: ignore[reportMissingImports]
from scripts import run as run_script  # pyright: ignore[reportMissingImports]
from scripts import setup_environment as setup_script  # pyright: ignore[reportMissingImports]


def test_script_config_exports_expected_paths_and_targets() -> None:
    assert script_config.SKILL_DIR.name == "wwise-waapi"
    assert script_config.VENV_DIR == script_config.SKILL_DIR / ".venv"
    assert script_config.COVERAGE_MINIMUM == 85
    assert script_config.CORE_COVERAGE_TARGETS["manifest"] == 95


def test_run_main_without_script_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_script.main([]) == 0
    captured = capsys.readouterr()
    assert "Run Wwise WAAPI skill scripts" in captured.out


def test_run_main_executes_existing_script_when_bootstrap_is_stubbed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    run_script.VENV_DIR.mkdir(parents=True)
    monkeypatch.setattr(run_script, "bootstrap_if_needed", lambda: None)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append([str(part) for part in cmd])

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(run_script.subprocess, "run", fake_run)
    assert run_script.main(["setup_environment.py", "--check"]) == 0
    assert calls and calls[0][0].endswith("python")


def test_run_bootstrap_if_needed_invokes_setup_when_venv_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    invoked: list[list[str]] = []

    def fake_run(cmd, check=True):
        invoked.append([str(part) for part in cmd])

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(run_script.subprocess, "run", fake_run)
    run_script.bootstrap_if_needed()
    assert invoked and invoked[0][0] == str(run_script.sys.executable)


def test_run_main_unknown_script_exits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(run_script, "VENV_DIR", tmp_path / ".venv")
    run_script.VENV_DIR.mkdir(parents=True)
    with pytest.raises(SystemExit):
        run_script.main(["does-not-exist.py"])


def test_setup_environment_ensure_creates_venv_and_installs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    monkeypatch.setattr(setup_script, "SKILL_DIR", Path("/Users/xiye/Documents/Git/waapi-skills/.agents/skills/wwise-waapi"))

    created: list[Path] = []

    def fake_venv_create(path, with_pip=True):
        created.append(Path(path))
        (Path(path) / "bin").mkdir(parents=True, exist_ok=True)
        (Path(path) / "bin" / "python").write_text("#!/usr/bin/env python3\n")
        (Path(path) / "bin" / "pip").write_text("#!/usr/bin/env python3\n")

    installs: list[list[str]] = []

    def fake_run(cmd, check=True, capture_output=False, text=False):
        installs.append([str(part) for part in cmd])

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(setup_script.venv, "create", fake_venv_create)
    monkeypatch.setattr(setup_script.subprocess, "run", fake_run)

    env = setup_script.SkillEnvironment()
    assert env.ensure() is True
    assert created and created[0] == tmp_path / ".venv"
    assert installs and "install" in installs[0]


def test_setup_environment_ensure_without_requirements_skips_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    skill_root = tmp_path / "skill"
    skill_root.mkdir()
    monkeypatch.setattr(setup_script, "SKILL_DIR", skill_root)
    monkeypatch.setattr(setup_script, "VENV_DIR", skill_root / ".venv")

    def fake_venv_create(path, with_pip=True):
        (Path(path) / "bin").mkdir(parents=True, exist_ok=True)
        (Path(path) / "bin" / "python").write_text("#!/usr/bin/env python3\n")
        (Path(path) / "bin" / "pip").write_text("#!/usr/bin/env python3\n")

    monkeypatch.setattr(setup_script.venv, "create", fake_venv_create)
    monkeypatch.setattr(setup_script.subprocess, "run", lambda *args, **kwargs: pytest.fail("install should be skipped"))

    env = setup_script.SkillEnvironment(skill_dir=skill_root)
    assert env.ensure() is True


def test_setup_environment_run_executes_script(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    env = setup_script.SkillEnvironment()
    monkeypatch.setattr(setup_script.SkillEnvironment, "ensure", lambda self: True)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append([str(part) for part in cmd])

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(setup_script.subprocess, "run", fake_run)
    assert env.run("setup_environment.py", ["--check"]) == 0
    assert calls and calls[0][1].endswith("setup_environment.py")


def test_setup_environment_run_missing_script_returns_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    env = setup_script.SkillEnvironment()
    assert env.run("missing.py", []) == 1


def test_setup_environment_main_check_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    setup_script.VENV_DIR.mkdir(parents=True)
    assert setup_script.main(["--check"]) == 0


def test_setup_environment_parser_exists() -> None:
    parser = setup_script.build_parser()
    assert parser.description == "Prepare the Wwise WAAPI skill environment"


def test_setup_environment_main_run_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(setup_script, "VENV_DIR", tmp_path / ".venv")
    setup_script.VENV_DIR.mkdir(parents=True)
    env = setup_script.SkillEnvironment()
    original_class = setup_script.SkillEnvironment
    monkeypatch.setattr(original_class, "run", lambda self, script_name, args: 0)
    monkeypatch.setattr(setup_script, "SkillEnvironment", lambda: env)
    assert setup_script.main(["--run", "setup_environment.py", "--check"]) == 0
