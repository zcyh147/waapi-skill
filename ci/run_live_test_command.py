from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

if __package__:
    from .resolve_live_test_config import LiveTestConfigError, load_version_config
else:  # Executed directly by ci/test.bat.
    from resolve_live_test_config import LiveTestConfigError, load_version_config


LIVE_MODES = frozenset({"smoke", "live", "destructive"})


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


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("live-test config error: child command is required", file=sys.stderr)
        return 2
    try:
        environment = build_live_test_environment(
            os.environ,
            version=args.version,
            mode=args.mode,
            repo_root=args.repo_root,
            default_config=args.default_config,
            default_console=args.default_console,
            default_project=args.default_project,
            default_sandbox=args.default_sandbox,
        )
        validate_live_test_environment(environment, mode=args.mode)
    except (LiveTestConfigError, OSError) as exc:
        print(f"live-test config error: {exc}", file=sys.stderr)
        return 2

    _print_context(environment, version=args.version, mode=args.mode)
    try:
        completed = subprocess.run(
            command,
            cwd=args.repo_root.expanduser().resolve(strict=False),
            env=environment,
            check=False,
        )
    except OSError as exc:
        print(f"live-test command failed to start: {exc}", file=sys.stderr)
        return 2
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
