from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from wwise_waapi.versions import WWISE_VERSION_CONTRACTS

if __package__:
    from .resolve_live_test_config import LiveTestConfigError, load_version_config
else:  # Executed directly by ci/test.bat.
    from resolve_live_test_config import LiveTestConfigError, load_version_config


LIVE_MODES = frozenset({"smoke", "live", "destructive"})
_POETRY_PYTHON_PREFIX = ("poetry", "run", "python")
_SMOKE_SUCCESS_PREFIX = "smoke ok:"
_SMOKE_CONTRACT = "waapi-skill.real-smoke/v1"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def resolve_live_python_command(
    command: Sequence[str],
    *,
    python_executable: str | None = None,
) -> tuple[str, ...]:
    """Replace the already-active Poetry prefix with this interpreter.

    The accepted prefix is the legacy child-command schema used by this
    helper's standalone CLI.  ``ci/test_driver.py`` also calls the helper
    in-process.  In both cases starting another bare ``poetry`` child is
    unnecessary and unreliable on Windows, where the Poetry shim may be a
    batch file that CreateProcess cannot execute directly.  The remaining argv
    stays data without a shell or quoting round-trip.
    """

    if isinstance(command, (str, bytes)):
        raise LiveTestConfigError("child command must be an argv sequence")
    normalized = tuple(command)
    if any(type(argument) is not str for argument in normalized):
        raise LiveTestConfigError("child command argv must contain only strings")
    if any("\x00" in argument for argument in normalized):
        raise LiveTestConfigError("child command argv contains a NUL character")
    if normalized[:3] != _POETRY_PYTHON_PREFIX:
        raise LiveTestConfigError(
            "child command must begin with the fixed 'poetry run python' prefix"
        )
    if len(normalized) == len(_POETRY_PYTHON_PREFIX):
        raise LiveTestConfigError("child Python command is missing")

    executable = sys.executable if python_executable is None else python_executable
    if (
        not isinstance(executable, str)
        or not executable
        or "\x00" in executable
        or not Path(executable).is_absolute()
    ):
        raise LiveTestConfigError(
            "the active Python interpreter must be one absolute native path"
        )
    return (executable, *normalized[len(_POETRY_PYTHON_PREFIX) :])


def build_live_test_environment(
    environment: Mapping[str, str],
    *,
    version: str,
    mode: str,
    repo_root: Path,
    default_config: Path,
    default_console: Path,
    default_project: Path,
    default_sandbox: Path,
) -> dict[str, str]:
    """Resolve one real-test process environment without a shell path round-trip."""

    if mode not in LIVE_MODES:
        raise LiveTestConfigError(f"unsupported live-test mode: {mode}")
    root = repo_root.expanduser().resolve(strict=False)
    explicit_config = "WWISE_TEST_CONFIG" in environment
    raw_config = environment.get("WWISE_TEST_CONFIG")
    if explicit_config and not raw_config:
        raise LiveTestConfigError("WWISE_TEST_CONFIG must not be empty")
    config_path = (
        Path(str(raw_config)).expanduser()
        if explicit_config
        else default_config.expanduser()
    )
    if not config_path.is_absolute():
        config_path = root / config_path
    config_path = config_path.resolve(strict=False)
    if explicit_config and not config_path.is_file():
        raise LiveTestConfigError(
            f"explicit WWISE_TEST_CONFIG does not exist: {config_path}"
        )

    configured: dict[str, str] = {}
    if config_path.is_file():
        configured = load_version_config(
            config_path,
            version=version,
            repo_root=root,
        )

    resolved = dict(environment)
    defaults = {
        "WWISE_CONSOLE": str(default_console.expanduser().resolve(strict=False)),
        "WWISE_SAMPLE_PROJECT_PATH": str(
            default_project.expanduser().resolve(strict=False)
        ),
        "WWISE_SANDBOX_ROOT": str(default_sandbox.expanduser().resolve(strict=False)),
    }
    for name, default_value in defaults.items():
        if name in environment:
            if not environment[name]:
                raise LiveTestConfigError(f"{name} must not be empty")
            resolved[name] = environment[name]
        else:
            resolved[name] = configured.get(name, default_value)

    resolved["WWISE_VERSION"] = version
    resolved["WWISE_LIVE"] = "1"
    resolved["WWISE_DESTRUCTIVE"] = "1" if mode == "destructive" else "0"
    resolved["WWISE_STRICT_REAL"] = "1"
    if config_path.is_file():
        resolved["WWISE_TEST_CONFIG"] = str(config_path)
    else:
        resolved.pop("WWISE_TEST_CONFIG", None)
    return resolved


def validate_live_test_environment(environment: Mapping[str, str], *, mode: str) -> None:
    console = Path(environment["WWISE_CONSOLE"])
    project = Path(environment["WWISE_SAMPLE_PROJECT_PATH"])
    if not console.is_file():
        raise LiveTestConfigError(
            f"strict real {mode} requires executable WWISE_CONSOLE: {console}"
        )
    if os.name == "posix" and not os.access(console, os.X_OK):
        raise LiveTestConfigError(
            f"strict real {mode} requires executable WWISE_CONSOLE: {console}"
        )
    if not project.is_file() or project.suffix.casefold() != ".wproj":
        raise LiveTestConfigError(
            "strict real "
            f"{mode} requires an existing .wproj WWISE_SAMPLE_PROJECT_PATH: {project}"
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve a real Wwise test environment and run one bounded command."
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--mode", choices=sorted(LIVE_MODES), required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--default-config", type=Path, required=True)
    parser.add_argument("--default-console", type=Path, required=True)
    parser.add_argument("--default-project", type=Path, required=True)
    parser.add_argument("--default-sandbox", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def _print_context(environment: Mapping[str, str], *, version: str, mode: str) -> None:
    print("== Test Context ==")
    print(f"version:      {version}")
    print(f"mode:         {mode}")
    print(f"console:      {environment['WWISE_CONSOLE']}")
    print(f"project:      {environment['WWISE_SAMPLE_PROJECT_PATH']}")
    print(f"sandbox_root: {environment['WWISE_SANDBOX_ROOT']}")
    print(f"test_config:  {environment.get('WWISE_TEST_CONFIG', '<unset>')}")
    print(flush=True)


def _replay_text(value: object, *, stream: Any) -> str:
    """Replay captured smoke output while keeping its proof available to validate."""

    if value is None:
        return ""
    if not isinstance(value, str):
        raise LiveTestConfigError("captured smoke output is not text")
    stream.write(value)
    stream.flush()
    return value


def _validate_smoke_child_command(
    command: Sequence[str],
    *,
    repo_root: Path,
) -> None:
    if len(command) != 4 or tuple(command[:3]) != _POETRY_PYTHON_PREFIX:
        raise LiveTestConfigError(
            "smoke child must be exactly the packaged ci/wwise_smoke.py command"
        )
    candidate = Path(command[3])
    if not candidate.is_absolute():
        raise LiveTestConfigError("smoke child path must be absolute")
    expected = (repo_root.expanduser().resolve(strict=True) / "ci" / "wwise_smoke.py").resolve(
        strict=True
    )
    if candidate.expanduser().resolve(strict=True) != expected:
        raise LiveTestConfigError(
            "smoke child must be this checkout's ci/wwise_smoke.py"
        )


def _path_is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_smoke_success_proof(
    stdout: str,
    *,
    expected_version: str,
    environment: Mapping[str, str],
) -> Mapping[str, Any]:
    markers = [
        line[len(_SMOKE_SUCCESS_PREFIX) :].strip()
        for line in stdout.splitlines()
        if line.startswith(_SMOKE_SUCCESS_PREFIX)
    ]
    if len(markers) != 1 or not markers[0]:
        raise LiveTestConfigError(
            "child exited 0 without exactly one strong 'smoke ok:' getInfo marker"
        )
    try:
        payload = json.loads(
            markers[0],
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LiveTestConfigError(f"smoke marker is not strict JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise LiveTestConfigError("smoke marker payload must be an object")
    required = {
        "argv",
        "build",
        "cleanup",
        "contract",
        "display_name",
        "isCommandLine",
        "pid",
        "port",
        "ready_duration_seconds",
        "sandbox_deleted",
        "sandbox_project",
        "source_mtime_ns",
        "source_sha256",
        "version",
    }
    if set(payload) != required:
        raise LiveTestConfigError("smoke marker payload has an invalid shape")
    version_contract = WWISE_VERSION_CONTRACTS.get(expected_version)
    if version_contract is None:
        raise LiveTestConfigError(
            f"smoke proof requested unsupported version: {expected_version}"
        )
    expected_build = version_contract.build
    command = payload.get("argv")
    ready_duration = payload.get("ready_duration_seconds")
    sandbox_project = payload.get("sandbox_project")
    source_sha256 = payload.get("source_sha256")
    if (
        payload.get("contract") != _SMOKE_CONTRACT
        or payload.get("version") != expected_version
        or payload.get("build") != expected_build
        or not isinstance(payload.get("display_name"), str)
        or not payload["display_name"]
        or payload.get("isCommandLine") is not True
        or payload.get("cleanup") != "cleaned"
        or payload.get("sandbox_deleted") is not True
        or not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item for item in command)
        or type(payload.get("pid")) is not int
        or payload["pid"] <= 0
        or type(payload.get("port")) is not int
        or not 1 <= payload["port"] <= 65535
        or type(ready_duration) not in {int, float}
        or not math.isfinite(ready_duration)
        or ready_duration < 0
        or not isinstance(sandbox_project, str)
        or not sandbox_project
        or not Path(sandbox_project).is_absolute()
        or type(payload.get("source_mtime_ns")) is not int
        or payload["source_mtime_ns"] < 0
        or not isinstance(source_sha256, str)
        or _SHA256_PATTERN.fullmatch(source_sha256) is None
    ):
        raise LiveTestConfigError("smoke marker payload failed its proof contract")

    assert isinstance(command, list)
    assert isinstance(sandbox_project, str)
    if len(command) < 3:
        raise LiveTestConfigError("smoke marker launch command is incomplete")
    try:
        configured_console = Path(environment["WWISE_CONSOLE"]).expanduser().resolve(
            strict=True
        )
        configured_source = Path(
            environment["WWISE_SAMPLE_PROJECT_PATH"]
        ).expanduser().resolve(strict=True)
        configured_root = Path(environment["WWISE_SANDBOX_ROOT"]).expanduser().resolve(
            strict=False
        )
        proven_sandbox = Path(sandbox_project).expanduser().resolve(strict=False)
        launched_console = Path(command[0]).expanduser().resolve(strict=True)
        launched_project = Path(command[2]).expanduser().resolve(strict=False)
    except (KeyError, OSError) as exc:
        raise LiveTestConfigError(
            f"smoke marker path proof could not be resolved: {exc}"
        ) from exc
    source_root = configured_source.parent
    port = payload["port"]
    try:
        port_index = command.index("--wamp-port")
        command_port = command[port_index + 1]
    except (ValueError, IndexError) as exc:
        raise LiveTestConfigError("smoke marker command is missing its WAAPI port") from exc
    if (
        command[1] != "waapi-server"
        or launched_console != configured_console
        or launched_project != proven_sandbox
        or not _path_is_under(proven_sandbox, configured_root)
        or _path_is_under(proven_sandbox, source_root)
        or _path_is_under(configured_root, source_root)
        or _path_is_under(source_root, configured_root)
        or os.path.lexists(proven_sandbox)
        or command_port != str(port)
    ):
        raise LiveTestConfigError(
            "smoke marker is not bound to the configured Console and deleted sandbox"
        )
    return payload


def main(
    argv: Sequence[str] | None = None,
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[Any]] | None = None,
    python_executable: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("live-test config error: child command is required", file=sys.stderr)
        return 2
    try:
        if args.mode == "smoke":
            _validate_smoke_child_command(command, repo_root=args.repo_root)
        resolved_command = resolve_live_python_command(
            command,
            python_executable=python_executable,
        )
        environment = build_live_test_environment(
            os.environ if environment is None else environment,
            version=args.version,
            mode=args.mode,
            repo_root=args.repo_root,
            default_config=args.default_config,
            default_console=args.default_console,
            default_project=args.default_project,
            default_sandbox=args.default_sandbox,
        )
    except (LiveTestConfigError, OSError) as exc:
        print(f"live-test config error: {exc}", file=sys.stderr)
        return 2
    try:
        validate_live_test_environment(environment, mode=args.mode)
    except (LiveTestConfigError, OSError) as exc:
        print(f"live-test prerequisite error: {exc}", file=sys.stderr)
        return 1

    _print_context(environment, version=args.version, mode=args.mode)
    runner = subprocess.run if command_runner is None else command_runner
    options: dict[str, Any] = {
        "cwd": args.repo_root.expanduser().resolve(strict=False),
        "env": environment,
        "shell": False,
        "check": False,
    }
    if args.mode == "smoke":
        options.update(
            {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "errors": "replace",
            }
        )
    try:
        completed = runner(resolved_command, **options)
    except OSError as exc:
        print(f"live-test command failed to start: {exc}", file=sys.stderr)
        return 2
    if args.mode == "smoke":
        try:
            smoke_stdout = _replay_text(completed.stdout, stream=sys.stdout)
            _replay_text(completed.stderr, stream=sys.stderr)
        except LiveTestConfigError as exc:
            print(f"live-test smoke proof error: {exc}", file=sys.stderr)
            return 2
        if completed.returncode == 0:
            try:
                _validate_smoke_success_proof(
                    smoke_stdout,
                    expected_version=args.version,
                    environment=environment,
                )
            except LiveTestConfigError as exc:
                print(f"live-test smoke proof error: {exc}", file=sys.stderr)
                return 2
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
