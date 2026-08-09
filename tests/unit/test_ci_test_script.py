from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ci.resolve_live_test_config import LiveTestConfigError, resolve_version_config
from ci.run_live_test_command import (
    _validate_smoke_child_command,
    build_live_test_environment,
    main as run_live_test_command,
    resolve_live_python_command,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_TEST_SH = REPO_ROOT / "ci" / "test.sh"
CI_TEST_BAT = REPO_ROOT / "ci" / "test.bat"


def test_live_config_resolver_uses_host_native_pathlib_and_aliases(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo root"
    resolved = resolve_version_config(
        {
            "versions": {
                "2025.1": {
                    "console_path": "tooling/WwiseConsole",
                    "sample_project_path": "fixtures/SampleProject.wproj",
                    "sandbox_root": "runtime/sandboxes",
                }
            }
        },
        version="2025.1",
        repo_root=repo_root,
    )

    assert resolved == {
        "WWISE_CONSOLE": str((repo_root / "tooling" / "WwiseConsole").resolve()),
        "WWISE_SAMPLE_PROJECT_PATH": str(
            (repo_root / "fixtures" / "SampleProject.wproj").resolve()
        ),
        "WWISE_SANDBOX_ROOT": str(
            (repo_root / "runtime" / "sandboxes").resolve()
        ),
    }
    if os.name == "nt":
        assert all("/" not in value for value in resolved.values())


def test_live_config_resolver_rejects_invalid_path_fields(tmp_path: Path) -> None:
    with pytest.raises(LiveTestConfigError, match="must be a non-empty string"):
        resolve_version_config(
            {"versions": {"2025.1": {"wwise_console": ["not", "a", "path"]}}},
            version="2025.1",
            repo_root=tmp_path,
        )


def test_live_command_environment_uses_config_then_explicit_overrides(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    configured = tmp_path / "configured"
    overridden_console = tmp_path / "override" / "WwiseConsole"
    config_path = tmp_path / "live-environment.json"
    config_path.write_text(
        json.dumps(
            {
                "versions": {
                    "2025.1": {
                        "wwise_console": str(configured / "WwiseConsole"),
                        "sample_project": str(configured / "SampleProject.wproj"),
                        "sandbox_root": str(configured / "sandbox"),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    environment = build_live_test_environment(
        {
            "WWISE_TEST_CONFIG": str(config_path),
            "WWISE_CONSOLE": str(overridden_console),
        },
        version="2025.1",
        mode="destructive",
        repo_root=repo_root,
        default_config=repo_root / "default.json",
        default_console=repo_root / "default-console",
        default_project=repo_root / "default-project.wproj",
        default_sandbox=repo_root / "default-sandbox",
    )

    assert environment["WWISE_CONSOLE"] == str(overridden_console)
    assert environment["WWISE_SAMPLE_PROJECT_PATH"] == str(
        (configured / "SampleProject.wproj").resolve()
    )
    assert environment["WWISE_SANDBOX_ROOT"] == str(
        (configured / "sandbox").resolve()
    )
    assert environment["WWISE_TEST_CONFIG"] == str(config_path.resolve())
    assert environment["WWISE_LIVE"] == "1"
    assert environment["WWISE_DESTRUCTIVE"] == "1"
    assert environment["WWISE_STRICT_REAL"] == "1"


def test_live_command_environment_rejects_missing_explicit_config(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-live-environment.json"
    with pytest.raises(LiveTestConfigError, match="explicit WWISE_TEST_CONFIG"):
        build_live_test_environment(
            {"WWISE_TEST_CONFIG": str(missing)},
            version="2025.1",
            mode="live",
            repo_root=tmp_path,
            default_config=tmp_path / "default.json",
            default_console=tmp_path / "WwiseConsole",
            default_project=tmp_path / "SampleProject.wproj",
            default_sandbox=tmp_path / "sandbox",
        )


def test_live_python_command_reuses_active_interpreter_and_preserves_exact_argv(
    tmp_path: Path,
) -> None:
    interpreter = str(tmp_path / "venv with spaces" / "python")
    child = (
        "poetry",
        "run",
        "python",
        "-m",
        "pytest",
        "-k",
        "transaction and (gateway or lock)",
        "",
        "中文 & | < > ^ ! %",
    )

    assert resolve_live_python_command(
        child,
        python_executable=interpreter,
    ) == (interpreter, *child[3:])


@pytest.mark.parametrize(
    "command,python_executable",
    (
        ("poetry run python -m pytest", None),
        (("python", "-m", "pytest"), None),
        (("poetry", "run", "python"), None),
        (("poetry", "run", "python", "-m", 7), None),
        (("poetry", "run", "python", "-m", "pytest"), "python"),
        (("poetry", "run", "python", "-m", "py\x00test"), None),
    ),
)
def test_live_python_command_rejects_noncanonical_or_unsafe_argv(
    command: object,
    python_executable: str | None,
) -> None:
    with pytest.raises(LiveTestConfigError):
        resolve_live_python_command(  # type: ignore[arg-type]
            command,
            python_executable=python_executable,
        )


def test_live_command_main_runs_exact_argv_without_a_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = tmp_path / "WwiseConsole"
    console.write_text("console\n", encoding="utf-8")
    console.chmod(0o755)
    project = tmp_path / "SampleProject.wproj"
    project.write_text("<Project />\n", encoding="utf-8")
    sandbox = tmp_path / "sandbox"
    interpreter = str(tmp_path / "venv" / "python")
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    for name in (
        "WWISE_TEST_CONFIG",
        "WWISE_CONSOLE",
        "WWISE_SAMPLE_PROJECT_PATH",
        "WWISE_SANDBOX_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)

    def record_child(
        command: tuple[str, ...],
        **options: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((tuple(command), dict(options)))
        return subprocess.CompletedProcess(command, 7)

    code = run_live_test_command(
        (
            "--version",
            "2025.1",
            "--mode",
            "live",
            "--repo-root",
            str(tmp_path),
            "--default-config",
            str(tmp_path / "missing.json"),
            "--default-console",
            str(console),
            "--default-project",
            str(project),
            "--default-sandbox",
            str(sandbox),
            "--",
            "poetry",
            "run",
            "python",
            "-m",
            "pytest",
            "-k",
            "transaction and (gateway or lock)",
        ),
        command_runner=record_child,
        python_executable=interpreter,
    )

    assert code == 7
    assert len(calls) == 1
    command, options = calls[0]
    assert command == (
        interpreter,
        "-m",
        "pytest",
        "-k",
        "transaction and (gateway or lock)",
    )
    assert options["cwd"] == tmp_path.resolve()
    assert options["shell"] is False
    assert options["check"] is False
    environment = options["env"]
    assert isinstance(environment, dict)
    assert environment["WWISE_VERSION"] == "2025.1"
    assert environment["WWISE_LIVE"] == "1"
    assert environment["WWISE_DESTRUCTIVE"] == "0"
    assert environment["WWISE_STRICT_REAL"] == "1"


def _strong_smoke_output(
    *,
    console: Path,
    sandbox_project: Path,
    build: str = "2022.1.19.8584",
) -> str:
    payload = {
        "argv": [
            str(console),
            "waapi-server",
            str(sandbox_project),
            "--wamp-port",
            "31337",
            "--http-port",
            "0",
        ],
        "build": build,
        "cleanup": "cleaned",
        "contract": "waapi-skill.real-smoke/v1",
        "display_name": "fake WwiseConsole",
        "isCommandLine": True,
        "pid": 4242,
        "port": 31337,
        "ready_duration_seconds": 0.25,
        "sandbox_deleted": True,
        "sandbox_project": str(sandbox_project),
        "source_mtime_ns": 123456789,
        "source_sha256": "0" * 64,
        "version": "2022.1",
    }
    return "smoke ok:" + json.dumps(payload, sort_keys=True) + "\n"


@pytest.mark.parametrize(
    ("proof_kind", "expected_code"),
    (
        ("poetry-version", 2),
        ("valid", 0),
        ("wrong-build", 2),
    ),
)
def test_live_smoke_requires_get_info_marker_in_addition_to_zero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    proof_kind: str,
    expected_code: int,
) -> None:
    console = tmp_path / "WwiseConsole"
    console.write_text("console\n", encoding="utf-8")
    console.chmod(0o755)
    project = tmp_path / "source" / "SampleProject.wproj"
    project.parent.mkdir()
    project.write_text("<Project />\n", encoding="utf-8")
    sandbox_root = tmp_path / "sandbox"
    sandbox_project = sandbox_root / "deleted" / "SampleProject.wproj"
    smoke_script = tmp_path / "ci" / "wwise_smoke.py"
    smoke_script.parent.mkdir()
    smoke_script.write_text("# packaged smoke fixture\n", encoding="utf-8")
    if proof_kind == "poetry-version":
        child_stdout = "Poetry (version 2.2.1)\n"
    else:
        child_stdout = _strong_smoke_output(
            console=console,
            sandbox_project=sandbox_project,
            build=(
                "2022.1.18.9999"
                if proof_kind == "wrong-build"
                else "2022.1.19.8584"
            ),
        )

    for name in (
        "WWISE_TEST_CONFIG",
        "WWISE_CONSOLE",
        "WWISE_SAMPLE_PROJECT_PATH",
        "WWISE_SANDBOX_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)

    def complete_smoke(
        command: tuple[str, ...],
        **options: object,
    ) -> subprocess.CompletedProcess[str]:
        assert options["stdout"] is subprocess.PIPE
        assert options["stderr"] is subprocess.PIPE
        assert options["text"] is True
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=child_stdout,
            stderr="",
        )

    code = run_live_test_command(
        (
            "--version",
            "2022.1",
            "--mode",
            "smoke",
            "--repo-root",
            str(tmp_path),
            "--default-config",
            str(tmp_path / "missing-config.json"),
            "--default-console",
            str(console),
            "--default-project",
            str(project),
            "--default-sandbox",
            str(sandbox_root),
            "--",
            "poetry",
            "run",
            "python",
            str(smoke_script),
        ),
        command_runner=complete_smoke,
        python_executable=sys.executable,
    )

    captured = capsys.readouterr()
    assert code == expected_code, captured.err
    assert child_stdout in captured.out
    if expected_code == 0:
        assert "smoke proof error" not in captured.err
    else:
        assert "smoke proof error" in captured.err


def test_live_smoke_rejects_any_child_other_than_the_packaged_script(
    tmp_path: Path,
) -> None:
    packaged = tmp_path / "ci" / "wwise_smoke.py"
    packaged.parent.mkdir()
    packaged.write_text("# packaged\n", encoding="utf-8")
    other = tmp_path / "other.py"
    other.write_text("# other\n", encoding="utf-8")

    with pytest.raises(LiveTestConfigError, match="this checkout"):
        _validate_smoke_child_command(
            ("poetry", "run", "python", str(other)),
            repo_root=tmp_path,
        )


def test_live_command_main_reports_missing_real_prerequisite_as_test_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = tmp_path / "WwiseConsole"
    console.write_text("console\n", encoding="utf-8")
    console.chmod(0o755)
    missing_project = tmp_path / "missing.wproj"
    child_started = False

    for name in (
        "WWISE_TEST_CONFIG",
        "WWISE_CONSOLE",
        "WWISE_SAMPLE_PROJECT_PATH",
        "WWISE_SANDBOX_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)

    def reject_child(
        *_args: object,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal child_started
        child_started = True
        return subprocess.CompletedProcess((), 0)

    code = run_live_test_command(
        (
            "--version",
            "2025.1",
            "--mode",
            "live",
            "--repo-root",
            str(tmp_path),
            "--default-config",
            str(tmp_path / "missing-config.json"),
            "--default-console",
            str(console),
            "--default-project",
            str(missing_project),
            "--default-sandbox",
            str(tmp_path / "sandbox"),
            "--",
            "poetry",
            "run",
            "python",
            "-m",
            "pytest",
        ),
        command_runner=reject_child,
        python_executable=sys.executable,
    )

    assert code == 1
    assert child_started is False


def _write_fake_python(bin_dir: Path, fail_on_nonlive: bool = False) -> Path:
    script = bin_dir / "fake_python.py"
    script.write_text(
        "from __future__ import annotations\n"
        "import json, os, subprocess, sys\n"
        "from pathlib import Path\n"
        f"log_path = Path(os.environ['CI_TEST_LOG'])\n"
        "def record_live_child(command, **options):\n"
        "    child_argv = list(command)\n"
        "    if not child_argv or os.path.normcase(child_argv[0]) != os.path.normcase(sys.executable):\n"
        "        raise AssertionError('live child did not reuse the active Python interpreter')\n"
        "    with log_path.open('a', encoding='utf-8') as handle:\n"
        "        handle.write(json.dumps(child_argv) + '\\n')\n"
        f"    if {str(fail_on_nonlive)} and child_argv[1:5] == ['-m', 'pytest', '-m', 'not live and not destructive']:\n"
        "        return subprocess.CompletedProcess(command, 7)\n"
        "    return subprocess.CompletedProcess(command, 0)\n"
        "argv = sys.argv[1:]\n"
        "if len(argv) >= 2 and argv[0] == '--directory':\n"
        "    argv = argv[2:]\n"
        "effective_argv = argv[3:] if argv[:3] == ['run', '--', 'python'] else (argv[2:] if argv[:2] == ['run', 'python'] else argv)\n"
        "if effective_argv and Path(effective_argv[0]).name == 'test_driver.py':\n"
        "    sys.path.insert(0, str(Path(effective_argv[0]).resolve().parent))\n"
        "    from test_driver import main\n"
        "    sys.exit(main(effective_argv[1:], environment=os.environ, python_executable=sys.executable, command_runner=record_live_child))\n"
        "if effective_argv and Path(effective_argv[0]).name == 'run_live_test_command.py':\n"
        "    sys.path.insert(0, str(Path(effective_argv[0]).resolve().parent))\n"
        "    from run_live_test_command import main\n"
        "    sys.exit(main(effective_argv[1:], command_runner=record_live_child, python_executable=sys.executable))\n"
        "with log_path.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(argv) + '\\n')\n"
        f"if {str(fail_on_nonlive)} and effective_argv[:3] == ['-m', 'pytest', '-m'] and 'not live and not destructive' in effective_argv:\n"
        "    sys.exit(7)\n"
        "sys.exit(0)\n"
    )
    if os.name == "nt":
        launcher = bin_dir / "python.bat"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "%~dp0fake_python.py" %*\r\n'
            'exit /b %ERRORLEVEL%\r\n',
            encoding="utf-8",
            newline="",
        )
        poetry = bin_dir / "poetry.bat"
        poetry.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n'
            'exit /b %ERRORLEVEL%\r\n',
            encoding="utf-8",
            newline="",
        )
    else:
        launcher = bin_dir / "python"
        launcher.write_text(
            f"#!/usr/bin/env bash\n\"{sys.executable}\" \"{script}\" \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        poetry = bin_dir / "poetry"
        poetry.write_text(
            f"#!/usr/bin/env bash\n\"{sys.executable}\" \"{script}\" \"$@\"\n",
            encoding="utf-8",
        )
        poetry.chmod(0o755)
    return script


def _run_ci_test(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    command = ["cmd.exe", "/d", "/c", str(CI_TEST_BAT), *args] if os.name == "nt" else ["bash", str(CI_TEST_SH), *args]
    return subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)


def _pytest_argv(argv: list[str]) -> list[str]:
    if argv[:3] == ["run", "--", "python"]:
        return argv[3:]
    if argv[:2] == ["run", "python"]:
        return argv[2:]
    if argv and os.path.normcase(argv[0]) == os.path.normcase(sys.executable):
        return argv[1:]
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
    assert "tests/destructive/test_gateway_transaction_matrix.py" in _pytest_argv(calls[2])
    assert "tests/destructive/test_gateway_workflow_transaction_matrix.py" in _pytest_argv(calls[2])
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


def test_ci_test_sh_rejects_missing_explicit_live_environment_config(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("ci/test.sh missing-config test is for the POSIX shell runner")

    env = os.environ.copy()
    env["WWISE_TEST_CONFIG"] = str(tmp_path / "missing-live-environment.json")
    env.pop("WWISE_CONSOLE", None)
    env.pop("WWISE_SAMPLE_PROJECT_PATH", None)
    env.pop("WWISE_SANDBOX_ROOT", None)

    result = _run_ci_test(env, "--version", "2024.1", "--mode", "live")

    assert result.returncode != 0
    assert "explicit WWISE_TEST_CONFIG does not exist" in result.stderr
