from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_TEST_SH = REPO_ROOT / "ci" / "test.sh"
CI_TEST_BAT = REPO_ROOT / "ci" / "test.bat"


def _write_fake_python(bin_dir: Path, fail_on_nonlive: bool = False) -> Path:
    script = bin_dir / "fake_python.py"
    script.write_text(
        "from __future__ import annotations\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"log_path = Path(os.environ['CI_TEST_LOG'])\n"
        "argv = sys.argv[1:]\n"
        "effective_argv = argv[2:] if argv[:2] == ['run', 'python'] else argv\n"
        "with log_path.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(argv) + '\\n')\n"
        f"if {str(fail_on_nonlive)} and effective_argv[:3] == ['-m', 'pytest', '-m'] and 'not live and not destructive' in effective_argv:\n"
        "    sys.exit(7)\n"
        "sys.exit(0)\n"
    )
    if os.name == "nt":
        launcher = bin_dir / "python.bat"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "%~dp0fake_python.py" %*\r\nexit /b %%%%ERRORLEVEL%%%%\r\n',
            encoding="utf-8",
        )
        poetry = bin_dir / "poetry.bat"
        poetry.write_text(
            '@echo off\r\n'
            'if /I "%~1"=="run" shift\r\n'
            'if /I "%~1"=="python" shift\r\n'
            f'"{sys.executable}" "{script}" %1 %2 %3 %4 %5 %6 %7 %8 %9\r\nexit /b %%%%ERRORLEVEL%%%%\r\n',
            encoding="utf-8",
        )
    else:
        launcher = bin_dir / "python"
        launcher.write_text(
            f"#!/usr/bin/env bash\n\"{sys.executable}\" \"{script}\" \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    return script


def _run_ci_test(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    command = ["cmd.exe", "/d", "/c", str(CI_TEST_BAT), *args] if os.name == "nt" else ["bash", str(CI_TEST_SH), *args]
    return subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)


def _pytest_argv(argv: list[str]) -> list[str]:
    if argv[:2] == ["run", "python"]:
        return argv[2:]
    return argv


def test_ci_test_help_mentions_all_mode() -> None:
    result = _run_ci_test(os.environ.copy(), "--help")

    assert result.returncode == 0
    assert "all          Run non-live suite first, then strict real matrix" in result.stdout
    expected_example = "ci\\test.bat --version all --mode all -- -q -ra" if os.name == "nt" else "ci/test.sh --version all --mode all -- -q -ra"
    assert expected_example in result.stdout


def test_ci_test_all_runs_nonlive_before_matrix(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "python.log"
    _write_fake_python(bin_dir)

    console_path = tmp_path / ("WwiseConsole.exe" if os.name == "nt" else "WwiseConsole.sh")
    console_path.write_text("console\n", encoding="utf-8")
    if os.name != "nt":
        console_path.chmod(0o755)

    project_path = tmp_path / "SampleProject.wproj"
    project_path.write_text("<Project />\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "CI_TEST_LOG": str(log_path),
            "WWISE_CONSOLE": str(console_path),
            "WWISE_SAMPLE_PROJECT_PATH": str(project_path),
            "WWISE_SANDBOX_ROOT": str(tmp_path / "sandbox"),
        }
    )

    result = _run_ci_test(env, "--version", "all", "--mode", "all", "--", "-q", "-ra")

    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 11
    assert _pytest_argv(calls[0]) == ["-m", "pytest", "-m", "not live and not destructive", "-q", "-ra"]
    assert _pytest_argv(calls[1])[0:4] == ["-m", "pytest", "tests/live/test_2021_1_live_prerequisites.py::test_2021_1_live_read_only_prerequisites_validate_exact_get_info_before_matrix", "tests/live/test_2021_1_reflection_prerequisites.py::test_2021_1_live_reflection_prerequisites_and_resource_generation"]
    assert _pytest_argv(calls[3])[0:4] == ["-m", "pytest", "tests/live/test_2022_live_prerequisites.py::test_2022_live_environment_prerequisites_fail_fast", "tests/live/test_2022_reflection_inventory.py::test_2022_live_reflection_inventory_runs_against_sandbox"]


def test_ci_test_all_stops_when_nonlive_fails(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "python.log"
    _write_fake_python(bin_dir, fail_on_nonlive=True)

    console_path = tmp_path / ("WwiseConsole.exe" if os.name == "nt" else "WwiseConsole.sh")
    console_path.write_text("console\n", encoding="utf-8")
    if os.name != "nt":
        console_path.chmod(0o755)

    project_path = tmp_path / "SampleProject.wproj"
    project_path.write_text("<Project />\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "CI_TEST_LOG": str(log_path),
            "WWISE_CONSOLE": str(console_path),
            "WWISE_SAMPLE_PROJECT_PATH": str(project_path),
            "WWISE_SANDBOX_ROOT": str(tmp_path / "sandbox"),
        }
    )

    result = _run_ci_test(env, "--version", "all", "--mode", "all", "--", "-q", "-ra")

    assert result.returncode != 0
    calls = log_path.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1

def test_ci_test_sh_reads_versioned_live_environment_config(tmp_path: Path) -> None:
    if os.name == "nt":
        import pytest  # pyright: ignore[reportMissingImports]

        pytest.skip("ci/test.sh JSON config test is for the POSIX shell runner")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "python.log"
    _write_fake_python(bin_dir)

    console_path = tmp_path / "configured" / "WwiseConsole.sh"
    console_path.parent.mkdir(parents=True)
    console_path.write_text("#!/bin/sh\n", encoding="utf-8")
    console_path.chmod(0o755)
    project_path = tmp_path / "configured" / "SampleProject.wproj"
    project_path.write_text("<Project />\n", encoding="utf-8")
    sandbox_root = tmp_path / "configured" / "sandbox"
    config_path = tmp_path / "live-environment.json"
    config_path.write_text(
        json.dumps(
            {
                "versions": {
                    "2024.1": {
                        "wwise_console": str(console_path),
                        "sample_project": str(project_path),
                        "sandbox_root": str(sandbox_root),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "CI_TEST_LOG": str(log_path),
            "WWISE_TEST_CONFIG": str(config_path),
        }
    )
    env.pop("WWISE_CONSOLE", None)
    env.pop("WWISE_SAMPLE_PROJECT_PATH", None)
    env.pop("WWISE_SANDBOX_ROOT", None)

    result = _run_ci_test(env, "--version", "2024.1", "--mode", "live", "--", "--collect-only", "-q")

    assert result.returncode == 0, result.stderr
    assert f"console:      {console_path}" in result.stdout
    assert f"project:      {project_path}" in result.stdout
    assert f"sandbox_root: {sandbox_root}" in result.stdout
    calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 1
    assert "--collect-only" in _pytest_argv(calls[0])


def test_ci_test_sh_env_overrides_versioned_live_environment_config(tmp_path: Path) -> None:
    if os.name == "nt":
        import pytest  # pyright: ignore[reportMissingImports]

        pytest.skip("ci/test.sh JSON config test is for the POSIX shell runner")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "python.log"
    _write_fake_python(bin_dir)

    configured_root = tmp_path / "configured"
    configured_console = configured_root / "WwiseConsole.sh"
    configured_console.parent.mkdir(parents=True)
    configured_console.write_text("#!/bin/sh\n", encoding="utf-8")
    configured_console.chmod(0o755)
    configured_project = configured_root / "SampleProject.wproj"
    configured_project.write_text("<Project />\n", encoding="utf-8")
    configured_sandbox = configured_root / "sandbox"

    override_root = tmp_path / "override"
    override_console = override_root / "WwiseConsole.sh"
    override_console.parent.mkdir(parents=True)
    override_console.write_text("#!/bin/sh\n", encoding="utf-8")
    override_console.chmod(0o755)
    override_project = override_root / "SampleProject.wproj"
    override_project.write_text("<Project />\n", encoding="utf-8")
    override_sandbox = override_root / "sandbox"

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

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "CI_TEST_LOG": str(log_path),
            "WWISE_TEST_CONFIG": str(config_path),
            "WWISE_CONSOLE": str(override_console),
            "WWISE_SAMPLE_PROJECT_PATH": str(override_project),
            "WWISE_SANDBOX_ROOT": str(override_sandbox),
        }
    )

    result = _run_ci_test(env, "--version", "2024.1", "--mode", "live", "--", "--collect-only", "-q")

    assert result.returncode == 0, result.stderr
    assert f"console:      {override_console}" in result.stdout
    assert f"project:      {override_project}" in result.stdout
    assert f"sandbox_root: {override_sandbox}" in result.stdout
    assert str(configured_console) not in result.stdout
    assert str(configured_project) not in result.stdout
    calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 1
    assert "--collect-only" in _pytest_argv(calls[0])
