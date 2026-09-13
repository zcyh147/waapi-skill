from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ci.run_program_tests import (
    PROGRAM_PYTEST_ARGS,
    ProgramManifestError,
    ProgramPytestArgsError,
    load_program_nodes,
    validate_program_pytest_args,
)
from ci.test_driver import (
    DESTRUCTIVE_TEST_NODES,
    LIVE_TEST_NODES,
    SUPPORTED_VERSIONS,
    TestDriverError as DriverError,
    TestEnvironmentError as DriverEnvironmentError,
    default_live_paths,
    parse_request,
    validate_test_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_TEST_BAT = REPO_ROOT / "ci" / "test.bat"
CI_TEST_SH = REPO_ROOT / "ci" / "test.sh"
CI_TEST_DRIVER = REPO_ROOT / "ci" / "test_driver.py"
PROGRAM_TEST_MANIFEST = REPO_ROOT / "ci" / "program-test-nodes.txt"


def _write_fake_python(bin_dir: Path, fail_on: str | None = None) -> None:
    runner = bin_dir / "fake_python.py"
    runner.write_text(
        "from __future__ import annotations\n"
        "import json, os, subprocess, sys\n"
        "from pathlib import Path\n"
        "log_path = Path(os.environ['CI_TEST_LOG'])\n"
        f"fail_on = {fail_on!r}\n"
        "def append_entry(payload_argv, environment, program_manifest_nodes=None, options=None):\n"
        "    entry = {\n"
        "        'argv': list(payload_argv),\n"
        "        'program_manifest_nodes': program_manifest_nodes,\n"
        "        'WWISE_VERSION': environment.get('WWISE_VERSION'),\n"
        "        'WWISE_LIVE': environment.get('WWISE_LIVE'),\n"
        "        'WWISE_DESTRUCTIVE': environment.get('WWISE_DESTRUCTIVE'),\n"
        "        'WWISE_STRICT_REAL': environment.get('WWISE_STRICT_REAL'),\n"
        "        'WWISE_CONSOLE': environment.get('WWISE_CONSOLE'),\n"
        "        'WWISE_SAMPLE_PROJECT_PATH': environment.get('WWISE_SAMPLE_PROJECT_PATH'),\n"
        "        'WWISE_SANDBOX_ROOT': environment.get('WWISE_SANDBOX_ROOT'),\n"
        "        'WWISE_TEST_CONFIG': environment.get('WWISE_TEST_CONFIG'),\n"
        "        'PYTEST_ADDOPTS': environment.get('PYTEST_ADDOPTS'),\n"
        "        'PYTEST_PLUGINS': environment.get('PYTEST_PLUGINS'),\n"
        "    }\n"
        "    if options is not None:\n"
        "        entry.update({\n"
        "            'cwd': str(options.get('cwd')),\n"
        "            'shell': options.get('shell'),\n"
        "            'check': options.get('check'),\n"
        "        })\n"
        "    with log_path.open('a', encoding='utf-8') as handle:\n"
        "        handle.write(json.dumps(entry) + '\\n')\n"
        "def selected_returncode(effective):\n"
        "    if fail_on == 'nonlive' and effective[:4] == ['-m', 'pytest', '-m', 'not live and not destructive']:\n"
        "        return 7\n"
        "    if fail_on == 'smoke' and effective and effective[0].endswith('wwise_smoke.py'):\n"
        "        return 8\n"
        "    if fail_on == 'live' and 'tests/live/' in ' '.join(effective):\n"
        "        return 9\n"
        "    if fail_on == 'destructive' and 'tests/destructive/' in ' '.join(effective):\n"
        "        return 10\n"
        "    return 0\n"
        "def record_live_child(command, **options):\n"
        "    child_argv = list(command)\n"
        "    if not child_argv or os.path.normcase(child_argv[0]) != os.path.normcase(sys.executable):\n"
        "        raise AssertionError('live child did not reuse the active Python interpreter')\n"
        "    child_environment = options['env']\n"
        "    program_manifest_nodes = None\n"
        "    if len(child_argv) >= 3 and Path(child_argv[1]).name == 'run_program_tests.py':\n"
        "        manifest_path = Path(child_argv[2])\n"
        "        if manifest_path.name == 'program-test-nodes.txt':\n"
        "            program_manifest_nodes = [line for line in manifest_path.read_text(encoding='utf-8-sig').splitlines() if line and not line.startswith('#')]\n"
        "        sys.path.insert(0, str(Path(child_argv[1]).resolve().parents[1]))\n"
        "        from ci.run_program_tests import ProgramPytestArgsError, validate_program_pytest_args\n"
        "        try:\n"
        "            validate_program_pytest_args(child_argv[3:])\n"
        "        except ProgramPytestArgsError as exc:\n"
        "            print(str(exc), file=sys.stderr)\n"
        "            return subprocess.CompletedProcess(command, 1)\n"
        "    append_entry(child_argv, child_environment, program_manifest_nodes, options=options)\n"
        "    is_smoke = bool(child_argv[1:]) and child_argv[1].endswith('wwise_smoke.py')\n"
        "    builds = {'2021.1': '2021.1.14.8108', '2022.1': '2022.1.19.8584', '2023.1': '2023.1.19.8928', '2024.1': '2024.1.13.9056', '2025.1': '2025.1.7.9143'}\n"
        "    version = child_environment.get('WWISE_VERSION')\n"
        "    if not is_smoke:\n"
        "        return subprocess.CompletedProcess(command, selected_returncode(child_argv[1:]))\n"
        "    sandbox_root = child_environment.get('WWISE_SANDBOX_ROOT')\n"
        "    if sandbox_root is None:\n"
        "        raise AssertionError('smoke child did not receive WWISE_SANDBOX_ROOT')\n"
        "    sandbox_project = Path(sandbox_root).resolve() / 'deleted' / 'SampleProject.wproj'\n"
        "    smoke_command = [child_environment['WWISE_CONSOLE'], 'waapi-server', str(sandbox_project), '--wamp-port', '31337', '--http-port', '0']\n"
        "    smoke_payload = {'argv': smoke_command, 'build': builds.get(version), 'cleanup': 'cleaned', 'contract': 'waapi-skill.real-smoke/v1', 'display_name': 'fake WwiseConsole', 'isCommandLine': True, 'pid': 4242, 'port': 31337, 'ready_duration_seconds': 0.25, 'sandbox_deleted': True, 'sandbox_project': str(sandbox_project), 'source_mtime_ns': 123456789, 'source_sha256': '0' * 64, 'version': version}\n"
        "    smoke_stdout = 'smoke ok:' + json.dumps(smoke_payload, sort_keys=True) + '\\n' if is_smoke else None\n"
        "    smoke_stderr = '' if is_smoke else None\n"
        "    return subprocess.CompletedProcess(command, selected_returncode(child_argv[1:]), stdout=smoke_stdout, stderr=smoke_stderr)\n"
        "argv = sys.argv[1:]\n"
        "if len(argv) >= 2 and argv[0] == '--directory':\n"
        "    argv = argv[2:]\n"
        "if argv[:2] == ['run', 'python'] and '--version' in argv:\n"
        "    print('Poetry (version 2.2.1)')\n"
        "    sys.exit(0)\n"
        "effective_argv = argv[3:] if argv[:3] == ['run', '--', 'python'] else (argv[2:] if argv[:2] == ['run', 'python'] else argv)\n"
        "if effective_argv and Path(effective_argv[0]).name == 'test_driver.py':\n"
        "    sys.path.insert(0, str(Path(effective_argv[0]).resolve().parent))\n"
        "    from test_driver import main\n"
        "    sys.exit(main(effective_argv[1:], environment=os.environ, python_executable=sys.executable, command_runner=record_live_child, windows=True))\n"
        "if effective_argv and Path(effective_argv[0]).name == 'run_live_test_command.py':\n"
        "    sys.path.insert(0, str(Path(effective_argv[0]).resolve().parent))\n"
        "    from run_live_test_command import main\n"
        "    sys.exit(main(effective_argv[1:], command_runner=record_live_child, python_executable=sys.executable))\n"
        "if effective_argv and Path(effective_argv[0]).name == 'resolve_live_test_config.py':\n"
        "    import runpy\n"
        "    sys.path.insert(0, str(Path(effective_argv[0]).resolve().parent))\n"
        "    sys.argv = effective_argv\n"
        "    runpy.run_path(effective_argv[0], run_name='__main__')\n"
        "program_manifest_nodes = None\n"
        "if len(effective_argv) >= 2 and Path(effective_argv[0]).name == 'run_program_tests.py':\n"
        "    manifest_path = Path(effective_argv[1])\n"
        "    if manifest_path.name == 'program-test-nodes.txt':\n"
        "        program_manifest_nodes = [\n"
        "            line for line in manifest_path.read_text(encoding='utf-8-sig').splitlines()\n"
        "            if line and not line.startswith('#')\n"
        "        ]\n"
        "    sys.path.insert(0, str(Path(effective_argv[0]).resolve().parents[1]))\n"
        "    from ci.run_program_tests import ProgramPytestArgsError, validate_program_pytest_args\n"
        "    try:\n"
        "        validate_program_pytest_args(effective_argv[2:])\n"
        "    except ProgramPytestArgsError as exc:\n"
        "        print(str(exc), file=sys.stderr)\n"
        "        sys.exit(1)\n"
        "append_entry(argv, os.environ, program_manifest_nodes)\n"
        "sys.exit(selected_returncode(effective_argv))\n",
        encoding="utf-8",
    )

    python_bat = bin_dir / "python.bat"
    python_bat.write_text(
        f'@echo off\r\n"{sys.executable}" "%~dp0fake_python.py" %*\r\n'
        'exit /b %ERRORLEVEL%\r\n',
        encoding="utf-8",
        newline="",
    )

    poetry_bat = bin_dir / "poetry.bat"
    poetry_bat.write_text(
        f'@echo off\r\n"{sys.executable}" "{runner}" %*\r\n'
        'exit /b %ERRORLEVEL%\r\n',
        encoding="utf-8",
        newline="",
    )


def _run_ci_test(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    if os.name != "nt":
        import pytest  # pyright: ignore[reportMissingImports]

        pytest.skip("ci/test.bat parity tests require a Windows cmd.exe executor")
    if shutil.which("cmd.exe") is None:
        import pytest  # pyright: ignore[reportMissingImports]

        pytest.skip("cmd.exe is unavailable on this Windows host")
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
    source_root = tmp_path / "source"
    source_root.mkdir()
    project_path = source_root / "SampleProject.wproj"
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
    if argv[:3] == ["run", "--", "python"]:
        return argv[3:]
    if argv[:2] == ["run", "python"]:
        return argv[2:]
    if argv and os.path.normcase(argv[0]) == os.path.normcase(sys.executable):
        return argv[1:]
    return argv


def _smoke_argv(call: dict[str, object]) -> list[str]:
    argv = _payload_argv(call)
    if argv[:3] == ["run", "--", "python"]:
        return argv[3:]
    if argv[:2] == ["run", "python"]:
        return argv[2:]
    if argv and os.path.normcase(argv[0]) == os.path.normcase(sys.executable):
        return argv[1:]
    return argv


def _program_manifest_nodes() -> list[str]:
    return [
        line
        for line in PROGRAM_TEST_MANIFEST.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    (
        (("--mode", "program"), ("none", "program", ())),
        (("--mode", "all", "--", "-q", "-ra"), ("all", "all", ("-q", "-ra"))),
        (("all", "focused", "--", "-k", "gateway or lock"), ("all", "focused", ("-k", "gateway or lock"))),
        (("2024.1", "live"), ("2024.1", "live", ())),
    ),
)
def test_python_driver_owns_cli_defaults_and_exact_pytest_passthrough(
    arguments: tuple[str, ...],
    expected: tuple[str, str, tuple[str, ...]],
) -> None:
    request = parse_request(arguments)

    assert request is not None
    assert (request.version, request.mode, request.pytest_args) == expected


@pytest.mark.parametrize(
    "arguments",
    (
        ("--mode", "live"),
        ("--version", "2024.1", "--mode", "all"),
        ("--version", "2024.1", "--mode", "matrix"),
        ("--version", "none", "--mode", "smoke"),
        ("--version", "2099.1", "--mode", "live"),
    ),
)
def test_python_driver_rejects_unsafe_mode_version_combinations(
    arguments: tuple[str, ...],
) -> None:
    with pytest.raises(DriverError):
        parse_request(arguments)


def test_test_environment_preflight_requires_locked_runtime_and_pytest() -> None:
    expected = {"pytest": "8.4.2", "waapi-client": "0.8.1"}

    validate_test_environment(
        repo_root=REPO_ROOT,
        python_version=(3, 13),
        distribution_version=expected.__getitem__,
    )
    with pytest.raises(DriverEnvironmentError, match="pytest is unavailable"):
        validate_test_environment(
            repo_root=REPO_ROOT,
            python_version=(3, 13),
            distribution_version=lambda name: (
                (_ for _ in ()).throw(LookupError(name))
                if name == "pytest"
                else expected[name]
            ),
        )
    with pytest.raises(DriverEnvironmentError, match="waapi-client version"):
        validate_test_environment(
            repo_root=REPO_ROOT,
            python_version=(3, 13),
            distribution_version=lambda name: (
                "0.0.0" if name == "waapi-client" else expected[name]
            ),
        )
    with pytest.raises(DriverEnvironmentError, match="Python 3.11 through 3.13"):
        validate_test_environment(
            repo_root=REPO_ROOT,
            python_version=(3, 14),
            distribution_version=expected.__getitem__,
        )


def test_python_driver_owns_all_platform_defaults_and_pytest_nodes() -> None:
    for version in SUPPORTED_VERSIONS:
        windows = default_live_paths(version, "live", windows=True)
        posix = default_live_paths(version, "live", windows=False)

        assert str(windows.console).startswith(r"C:\Audiokinetic\Wwise")
        assert windows.project == (
            REPO_ROOT / "tests" / "_org" / version / "SampleProject.wproj"
        )
        assert posix.console.as_posix().startswith("/Applications/Audiokinetic/Wwise")
        for node in (*LIVE_TEST_NODES[version], *DESTRUCTIVE_TEST_NODES[version]):
            assert (REPO_ROOT / node.split("::", 1)[0]).is_file()


def test_program_manifest_is_the_single_ordered_cross_platform_node_source() -> None:
    lines = PROGRAM_TEST_MANIFEST.read_text(encoding="utf-8").splitlines()
    nodes = load_program_nodes(PROGRAM_TEST_MANIFEST)

    assert len(nodes) == 187
    assert nodes[0] == "tests/unit/test_gateway_session_context.py"
    assert nodes[-1] == "tests/unit/test_single_typed_input_cutover.py"
    assert len(nodes) == len(set(nodes))
    assert "tests/unit/test_typed_gateway_input.py" in nodes
    assert {
        "tests/unit/test_script_helpers.py::test_environment_ready_marker_binds_requirements_and_rejects_symlink",
        "tests/unit/test_script_helpers.py::test_run_bootstrap_repairs_existing_venv_without_ready_marker",
        "tests/unit/test_script_helpers.py::test_setup_environment_ensure_creates_venv_and_installs",
        "tests/unit/test_script_helpers.py::test_setup_environment_check_rejects_partial_existing_venv",
        "tests/unit/test_waapi_gateway.py::test_stream_topic_idle_timeout_stops_incomplete_and_unsubscribes",
        "tests/unit/test_waapi_gateway.py::test_selection_monitor_uses_authoring_schema_and_rejects_console",
        "tests/unit/test_waapi_gateway.py::test_stream_topic_discloses_effective_idle_policy_without_shortening_user_duration",
        "tests/unit/test_waapi_gateway.py::test_stream_topic_invalid_idle_timeout_rejected_before_connection",
        "tests/unit/test_waapi_gateway.py::test_stream_topic_matching_events_restart_idle_clock",
    } <= set(nodes)
    for line in lines:
        if not line or line.startswith("#"):
            continue
        assert line == line.strip()
        assert not any(character.isspace() for character in line)
        assert line.startswith("tests/unit/")
        test_path = line.split("::", 1)[0]
        assert "." not in Path(test_path).parts
        assert ".." not in Path(test_path).parts
        assert (REPO_ROOT / test_path).is_file()

    shell_source = CI_TEST_SH.read_text(encoding="utf-8")
    batch_source = CI_TEST_BAT.read_text(encoding="utf-8")
    driver_source = CI_TEST_DRIVER.read_text(encoding="utf-8")
    assert '"program-test-nodes.txt"' in driver_source
    assert '"run_program_tests.py"' in driver_source
    assert "program-test-nodes.txt" not in shell_source
    assert "program-test-nodes.txt" not in batch_source
    assert driver_source.count("program-test-nodes.txt") == 1
    assert "test_gateway_session_context.py" not in shell_source
    assert "test_gateway_session_context.py" not in batch_source
    assert "--mode" not in shell_source
    assert "--mode" not in batch_source


def test_program_manifest_loader_allows_comments_and_blank_lines(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    test_file = repo_root / "tests" / "unit" / "test_example.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_example(): pass\n", encoding="utf-8")
    manifest = tmp_path / "program-test-nodes.txt"
    manifest.write_text(
        "# ordered program nodes\n\n"
        "tests/unit/test_example.py\n"
        "tests/unit/test_example.py::test_example\n",
        encoding="utf-8",
    )

    assert load_program_nodes(manifest, repo_root=repo_root) == [
        "tests/unit/test_example.py",
        "tests/unit/test_example.py::test_example",
    ]


@pytest.mark.parametrize(
    "contents",
    [
        "   \n",
        " # indented comment\n",
        " tests/unit/test_example.py\n",
        "tests/unit/test example.py\n",
        "tests/live/test_example.py\n",
        "tests/unit/../live/test_example.py\n",
        "tests\\unit\\test_example.py\n",
        "tests/unit/test_example.py\ntests/unit/test_example.py\n",
    ],
)
def test_program_manifest_loader_rejects_whitespace_escape_and_duplicates(
    tmp_path: Path,
    contents: str,
) -> None:
    repo_root = tmp_path / "repo"
    test_file = repo_root / "tests" / "unit" / "test_example.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_example(): pass\n", encoding="utf-8")
    manifest = tmp_path / "program-test-nodes.txt"
    manifest.write_text(contents, encoding="utf-8")

    with pytest.raises(ProgramManifestError):
        load_program_nodes(manifest, repo_root=repo_root)


def test_program_pytest_argument_validator_preserves_complex_filters() -> None:
    arguments = [
        "--collect-only",
        "-k",
        "transaction and (gateway or lock)",
        "--maxfail",
        "1",
        "-q",
        "-ra",
        "-rN",
        "-rE",
        "--tb=short",
        "--durations-min",
        "0.5",
    ]

    assert validate_program_pytest_args(arguments) == arguments
    assert PROGRAM_PYTEST_ARGS == (
        "-m",
        "not live and not destructive",
        "--ignore=tests/semantic",
        "--ignore=tests/live",
        "--ignore=tests/destructive",
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["tests/unit/test_ci_test_bat.py"],
        ["tests/unit/test_ci_test_bat.py::test_program_manifest_loader_allows_comments_and_blank_lines"],
        ["--pyargs", "tests.unit.test_ci_test_bat"],
        ["--pyargs=tests.unit.test_ci_test_bat"],
        ["--override-ini=addopts=tests/semantic"],
        ["--override-ini", "addopts=tests/live"],
        ["-o=addopts=tests/destructive"],
        ["-oaddopts=tests/semantic"],
        ["-c", "pytest.ini"],
        ["--rootdir", "tests/live"],
        ["-p", "unsafe_plugin"],
        ["-m", "live"],
        ["@pytest-args.txt"],
        ["--unknown-plugin-option"],
        ["-k"],
        ["-k", ""],
        ["--tb="],
    ],
)
def test_program_pytest_argument_validator_rejects_collection_widening_and_missing_values(
    arguments: list[str],
) -> None:
    with pytest.raises(ProgramPytestArgsError):
        validate_program_pytest_args(arguments)


def test_ci_test_bat_program_loads_every_shared_node_and_forwards_all_flags(tmp_path: Path) -> None:
    env, log_path = _base_env(tmp_path)
    env["PYTEST_ADDOPTS"] = "tests/live"
    env["PYTEST_PLUGINS"] = "unsafe_plugin"
    expression = "transaction and (gateway or lock)"

    result = _run_ci_test(
        env,
        "--mode",
        "program",
        "--",
        "--collect-only",
        "-k",
        expression,
        "-q",
        "-ra",
    )

    assert result.returncode == 0, result.stderr
    calls = _load_calls(log_path)
    assert len(calls) == 1
    call = calls[0]
    argv = _pytest_argv(call)
    assert Path(argv[0]).name == "run_program_tests.py"
    assert Path(argv[1]).resolve() == PROGRAM_TEST_MANIFEST.resolve()
    assert argv[2:] == [
        "--collect-only",
        "-k",
        expression,
        "-q",
        "-ra",
    ]
    assert call["program_manifest_nodes"] == _program_manifest_nodes()
    assert call["WWISE_VERSION"] is None
    assert call["WWISE_CONSOLE"] is None
    assert call["WWISE_SAMPLE_PROJECT_PATH"] is None
    assert call["WWISE_SANDBOX_ROOT"] is None
    assert call["PYTEST_ADDOPTS"] is None
    assert call["PYTEST_PLUGINS"] is None


def test_ci_test_bat_program_rejects_extra_paths_and_incomplete_filter_flags(tmp_path: Path) -> None:
    env, log_path = _base_env(tmp_path)

    extra_path = _run_ci_test(env, "--mode", "program", "--", "tests/unit/test_ci_test_bat.py")
    missing_filter = _run_ci_test(env, "--mode", "program", "--", "-k")

    assert extra_path.returncode == 1
    assert (
        "accepts allowlisted pytest flags and filter values, not additional test paths"
        in extra_path.stderr
    )
    assert missing_filter.returncode == 1
    assert "pytest option without its required value" in missing_filter.stderr
    assert not log_path.exists()


def test_ci_test_bat_help_matches_shell_parity_surface() -> None:
    result = _run_ci_test(os.environ.copy(), "--help")

    assert result.returncode == 0
    assert "2021.1 | 2022.1 | 2023.1 | 2024.1 | 2025.1 | all | none" in result.stdout
    assert "nonlive      Run default non-live test suite" in result.stdout
    assert "all          Run non-live suite first, then strict real matrix" in result.stdout
    assert "smoke        Run focused WAAPI getInfo smoke via HeadlessLifecycle" in result.stdout
    assert "ci\\test.bat all matrix" in result.stdout
    assert "WWISE_TEST_CONFIG" in result.stdout


def test_ci_test_bat_and_shell_share_pathlib_config_resolver() -> None:
    shell_source = CI_TEST_SH.read_text(encoding="utf-8")
    batch_source = CI_TEST_BAT.read_text(encoding="utf-8")
    driver_source = CI_TEST_DRIVER.read_text(encoding="utf-8")
    live_runner_source = (
        REPO_ROOT / "ci" / "run_live_test_command.py"
    ).read_text(encoding="utf-8")

    assert "WAAPI_TEST_PYTHON" in shell_source
    assert "WAAPI_TEST_PYTHON" in batch_source
    assert 'exec "$WAAPI_TEST_PYTHON" "$SCRIPT_DIR/test_driver.py" "$@"' in shell_source
    assert '"%WAAPI_TEST_PYTHON%" "%~dp0test_driver.py" %*' in batch_source
    assert 'poetry --directory "$SCRIPT_DIR/.." run -- python ' in shell_source
    assert 'call poetry --directory "%~dp0.." run -- python ' in batch_source
    assert "run_live_test_command" in driver_source
    assert "resolve_live_test_config" in live_runner_source
    assert batch_source.count('"%~dp0test_driver.py" %*') == 2
    assert "from wwise_waapi.headless import" not in shell_source


def test_python_driver_includes_shared_gateway_nodes_for_every_matrix_version() -> None:
    shared_live = (
        "tests/live/test_gateway_live_matrix.py::"
        "test_gateway_read_only_matrix_runs_once_against_copied_sandbox"
    )
    for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"):
        assert shared_live in LIVE_TEST_NODES[version]
        assert (
            "tests/destructive/test_gateway_transaction_matrix.py"
            in DESTRUCTIVE_TEST_NODES[version]
        )
        assert (
            "tests/destructive/test_gateway_workflow_transaction_matrix.py"
            in DESTRUCTIVE_TEST_NODES[version]
        )


def test_python_driver_includes_task_91_topic_business_live_node() -> None:
    assert (
        "tests/live/test_2022_1_topic_business_sandbox.py::"
        "test_2022_1_topic_business_inputs_against_sandbox"
    ) in LIVE_TEST_NODES["2022.1"]


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
    assert result.stdout.count("smoke ok:") == 5


def test_ci_test_bat_reads_versioned_live_environment_config(tmp_path: Path) -> None:
    env, log_path = _base_env(tmp_path)
    configured_root = tmp_path / "配置 !percent% & equals= paths"
    console_path = configured_root / "WwiseConsole.exe"
    console_path.parent.mkdir(parents=True)
    console_path.write_text("console\n", encoding="utf-8")
    project_path = configured_root / "SampleProject.wproj"
    project_path.write_text("<Project />\n", encoding="utf-8")
    sandbox_root = configured_root / "sandbox"
    config_path = tmp_path / "配置 !percent% & equals= environment.json"
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
    env["WWISE_TEST_CONFIG"] = str(config_path)
    env.pop("WWISE_CONSOLE", None)
    env.pop("WWISE_SAMPLE_PROJECT_PATH", None)
    env.pop("WWISE_SANDBOX_ROOT", None)

    result = _run_ci_test(
        env,
        "--version",
        "2024.1",
        "--mode",
        "live",
        "--",
        "--collect-only",
        "-q",
    )

    assert result.returncode == 0, result.stderr
    calls = _load_calls(log_path)
    assert len(calls) == 1
    assert calls[0]["WWISE_CONSOLE"] == str(console_path.resolve())
    assert calls[0]["WWISE_SAMPLE_PROJECT_PATH"] == str(project_path.resolve())
    assert calls[0]["WWISE_SANDBOX_ROOT"] == str(sandbox_root.resolve())
    assert calls[0]["WWISE_TEST_CONFIG"] == str(config_path.resolve())


def test_ci_test_bat_explicit_paths_override_versioned_config(tmp_path: Path) -> None:
    env, log_path = _base_env(tmp_path)
    configured_root = tmp_path / "configured"
    configured_console = configured_root / "WwiseConsole.exe"
    configured_console.parent.mkdir(parents=True)
    configured_console.write_text("console\n", encoding="utf-8")
    configured_project = configured_root / "SampleProject.wproj"
    configured_project.write_text("<Project />\n", encoding="utf-8")
    config_path = tmp_path / "live-environment.json"
    config_path.write_text(
        json.dumps(
            {
                "versions": {
                    "2024.1": {
                        "wwise_console": str(configured_console),
                        "sample_project": str(configured_project),
                        "sandbox_root": str(configured_root / "sandbox"),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    env["WWISE_TEST_CONFIG"] = str(config_path)

    result = _run_ci_test(
        env,
        "--version",
        "2024.1",
        "--mode",
        "live",
        "--",
        "--collect-only",
        "-q",
    )

    assert result.returncode == 0, result.stderr
    calls = _load_calls(log_path)
    assert len(calls) == 1
    assert calls[0]["WWISE_CONSOLE"] == env["WWISE_CONSOLE"]
    assert calls[0]["WWISE_SAMPLE_PROJECT_PATH"] == env["WWISE_SAMPLE_PROJECT_PATH"]
    assert calls[0]["WWISE_SANDBOX_ROOT"] == env["WWISE_SANDBOX_ROOT"]


def test_ci_test_bat_rejects_missing_explicit_live_config(tmp_path: Path) -> None:
    env, log_path = _base_env(tmp_path)
    env["WWISE_TEST_CONFIG"] = str(tmp_path / "missing-live-environment.json")

    result = _run_ci_test(env, "--version", "2024.1", "--mode", "live")

    assert result.returncode == 2
    assert "explicit WWISE_TEST_CONFIG does not exist" in result.stderr
    assert not log_path.exists()


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
