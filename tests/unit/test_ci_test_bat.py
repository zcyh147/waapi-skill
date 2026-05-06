from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_TEST_BAT = REPO_ROOT / "ci" / "test.bat"


def _write_fake_python(bin_dir: Path, fail_on: str | None = None) -> None:
    runner = bin_dir / "fake_python.py"
    runner.write_text(
        "from __future__ import annotations\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "log_path = Path(os.environ['CI_TEST_LOG'])\n"
        "argv = sys.argv[1:]\n"
        "entry = {\n"
        "    'argv': argv,\n"
        "    'WWISE_VERSION': os.environ.get('WWISE_VERSION'),\n"
        "    'WWISE_LIVE': os.environ.get('WWISE_LIVE'),\n"
        "    'WWISE_DESTRUCTIVE': os.environ.get('WWISE_DESTRUCTIVE'),\n"
        "    'WWISE_STRICT_REAL': os.environ.get('WWISE_STRICT_REAL'),\n"
        "    'WWISE_CONSOLE': os.environ.get('WWISE_CONSOLE'),\n"
        "    'WWISE_SAMPLE_PROJECT_PATH': os.environ.get('WWISE_SAMPLE_PROJECT_PATH'),\n"
        "    'WWISE_SANDBOX_ROOT': os.environ.get('WWISE_SANDBOX_ROOT'),\n"
        "}\n"
        "with log_path.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(entry) + '\\n')\n"
        f"fail_on = {fail_on!r}\n"
        "effective_argv = argv[2:] if argv[:2] == ['run', 'python'] else argv\n"
        "joined = ' '.join(argv)\n"
        "if fail_on == 'nonlive' and effective_argv[:4] == ['-m', 'pytest', '-m', 'not live and not destructive']:\n"
        "    sys.exit(7)\n"
        "if fail_on == 'smoke' and effective_argv and effective_argv[0].endswith('wwise_smoke.py'):\n"
        "    sys.exit(8)\n"
        "if fail_on == 'live' and 'tests/live/' in ' '.join(effective_argv):\n"
        "    sys.exit(9)\n"
        "if fail_on == 'destructive' and 'tests/destructive/' in ' '.join(effective_argv):\n"
        "    sys.exit(10)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )

    python_bat = bin_dir / "python.bat"
    python_bat.write_text(
        f'@echo off\r\n"{sys.executable}" "%~dp0fake_python.py" %*\r\nexit /b %%%%ERRORLEVEL%%%%\r\n',
        encoding="utf-8",
    )

    poetry_bat = bin_dir / "poetry.bat"
    poetry_bat.write_text(
        '@echo off\r\n'
        'if /I "%~1"=="run" shift\r\n'
        'if /I "%~1"=="python" shift\r\n'
        f'"{sys.executable}" "{runner}" %1 %2 %3 %4 %5 %6 %7 %8 %9\r\nexit /b %%%%ERRORLEVEL%%%%\r\n',
        encoding="utf-8",
    )


def _run_ci_test(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cmd.exe", "/d", "/c", str(CI_TEST_BAT), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _base_env(tmp_path: Path, *, fail_on: str | None = None) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "python.log"
    _write_fake_python(bin_dir, fail_on=fail_on)

    console_path = tmp_path / "WwiseConsole.exe"
    console_path.write_text("console\n", encoding="utf-8")
    project_path = tmp_path / "SampleProject.wproj"
    project_path.write_text("<Project />\n", encoding="utf-8")
    sandbox_root = tmp_path / "sandbox"

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "CI_TEST_LOG": str(log_path),
            "WWISE_CONSOLE": str(console_path),
            "WWISE_SAMPLE_PROJECT_PATH": str(project_path),
            "WWISE_SANDBOX_ROOT": str(sandbox_root),
        }
    )
    return env, log_path


def _load_calls(log_path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def _payload_argv(call: dict[str, object]) -> list[str]:
    argv = call["argv"]
    assert isinstance(argv, list)
    return argv


def _pytest_argv(call: dict[str, object]) -> list[str]:
    argv = _payload_argv(call)
    if argv[:2] == ["run", "python"]:
        return argv[2:]
    return argv


def _smoke_argv(call: dict[str, object]) -> list[str]:
    argv = _payload_argv(call)
    if argv[:2] == ["run", "python"]:
        return argv[2:]
    return argv


def test_ci_test_bat_help_matches_shell_parity_surface() -> None:
    result = _run_ci_test(os.environ.copy(), "--help")

    assert result.returncode == 0
    assert "2021.1 | 2022.1 | 2023.1 | 2024.1 | 2025.1 | all | none" in result.stdout
    assert "nonlive      Run default non-live test suite" in result.stdout
    assert "all          Run non-live suite first, then strict real matrix" in result.stdout
    assert "smoke        Run focused WAAPI getInfo smoke via HeadlessLifecycle" in result.stdout
    assert "ci\\test.bat all matrix" in result.stdout
    assert "poetry run python ..." in result.stdout


def test_ci_test_bat_all_mode_defaults_to_all_and_runs_full_matrix(tmp_path: Path) -> None:
    env, log_path = _base_env(tmp_path)

    result = _run_ci_test(env, "--mode", "all", "--", "-q", "-ra")

    assert result.returncode == 0, result.stderr
    calls = _load_calls(log_path)
    assert len(calls) == 11
    assert _pytest_argv(calls[0]) == ["-m", "pytest", "-m", "not live and not destructive", "-q", "-ra"]
    version_mode_pairs = [
        (call["WWISE_VERSION"], call["WWISE_LIVE"], call["WWISE_DESTRUCTIVE"])
        for call in calls[1:]
    ]
    assert version_mode_pairs == [
        ("2021.1", "1", "0"),
        ("2021.1", "1", "1"),
        ("2022.1", "1", "0"),
        ("2022.1", "1", "1"),
        ("2023.1", "1", "0"),
        ("2023.1", "1", "1"),
        ("2024.1", "1", "0"),
        ("2024.1", "1", "1"),
        ("2025.1", "1", "0"),
        ("2025.1", "1", "1"),
    ]
    assert all(_pytest_argv(call)[-2:] == ["-q", "-ra"] for call in calls if _pytest_argv(call) and _pytest_argv(call)[0] == "-m")


def test_ci_test_bat_smoke_all_runs_all_five_versions(tmp_path: Path) -> None:
    env, log_path = _base_env(tmp_path)

    result = _run_ci_test(env, "all", "smoke")

    assert result.returncode == 0, result.stderr
    calls = _load_calls(log_path)
    assert [call["WWISE_VERSION"] for call in calls] == ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"]
    assert all(call["WWISE_LIVE"] == "1" for call in calls)
    assert all(call["WWISE_DESTRUCTIVE"] == "0" for call in calls)
    assert all(call["WWISE_STRICT_REAL"] == "1" for call in calls)
    assert all(_smoke_argv(call) and str(_smoke_argv(call)[0]).endswith("ci\\wwise_smoke.py") for call in calls)


def test_ci_test_bat_nonlive_defaults_to_none_and_stops_before_live_on_failure(tmp_path: Path) -> None:
    env, log_path = _base_env(tmp_path, fail_on="nonlive")

    result = _run_ci_test(env, "--mode", "all")

    assert result.returncode == 7
    calls = _load_calls(log_path)
    assert len(calls) == 1
    assert calls[0]["WWISE_VERSION"] is None
    assert _pytest_argv(calls[0])[:4] == ["-m", "pytest", "-m", "not live and not destructive"]


def test_ci_test_bat_supports_positional_matrix_alias(tmp_path: Path) -> None:
    env, log_path = _base_env(tmp_path)

    result = _run_ci_test(env, "all", "focused", "--", "-q")

    assert result.returncode == 0, result.stderr
    calls = _load_calls(log_path)
    assert len(calls) == 10
    assert calls[0]["WWISE_VERSION"] == "2021.1"
    assert _pytest_argv(calls[0])[2].startswith("tests/live/test_2021_1_live_prerequisites.py")
    assert calls[2]["WWISE_VERSION"] == "2022.1"
    assert _pytest_argv(calls[2])[2].startswith("tests/live/test_2022_live_prerequisites.py")
    assert calls[-1]["WWISE_VERSION"] == "2025.1"
    assert _pytest_argv(calls[-1])[2] == "tests/destructive/test_2025_1_project_mutation_sandbox.py"
    assert all(_pytest_argv(call)[-1:] == ["-q"] for call in calls)


def test_ci_test_bat_rejects_invalid_mode_version_combinations_and_missing_real_prereqs(tmp_path: Path) -> None:
    env, _ = _base_env(tmp_path)

    wrong_all = _run_ci_test(env, "--version", "2024.1", "--mode", "all")
    assert wrong_all.returncode == 1
    assert "all mode requires version 'all'" in wrong_all.stderr

    wrong_matrix = _run_ci_test(env, "--version", "2024.1", "--mode", "matrix")
    assert wrong_matrix.returncode == 1
    assert "matrix/focused mode requires version 'all'" in wrong_matrix.stderr

    supported_2022_live = _run_ci_test(env, "--version", "2022.1", "--mode", "live")
    assert supported_2022_live.returncode == 0, supported_2022_live.stderr

    bad_env = env.copy()
    bad_env["WWISE_SAMPLE_PROJECT_PATH"] = str(tmp_path / "not-a-project.txt")
    prereq_fail = _run_ci_test(bad_env, "--version", "2024.1", "--mode", "smoke")
    assert prereq_fail.returncode == 1
    assert "requires an existing .wproj WWISE_SAMPLE_PROJECT_PATH" in prereq_fail.stderr
