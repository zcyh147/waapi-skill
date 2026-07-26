#!/usr/bin/env python3
"""Thin wrapper for running Wwise WAAPI skill scripts inside the local venv."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

try:  # pragma: no cover - import path differs between CLI and tests
    from config import (
        PackagedScriptError,
        SKILL_DIR,
        VENV_DIR,
        resolve_packaged_script,
    )
except ImportError:  # pragma: no cover
    from .config import (
        PackagedScriptError,
        SKILL_DIR,
        VENV_DIR,
        resolve_packaged_script,
    )


CODEX_GATEWAY_REQUIRED_ENV = "WAAPI_CODEX_GATEWAY_REQUIRED"
CODEX_GATEWAY_REQUIRED_EXIT_CODE = 125
INTERRUPTED_CHILD_CLEANUP_GRACE_SECONDS = 2.0
INTERRUPTED_CHILD_SIGNAL_GRACE_SECONDS = 1.0
INTERRUPTED_CHILD_TERMINATE_GRACE_SECONDS = 1.0
SUPPORTED_WWISE_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
_GATEWAY_VERSION_OPTIONS = frozenset({"--version", "--wwise-version"})
_GATEWAY_GLOBAL_OPTIONS_WITH_VALUES = frozenset(
    {
        "--host",
        "--port",
        "--version",
        "--wwise-version",
        "--timeout",
        "--evidence-dir",
        "--state-dir",
    }
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Run Wwise WAAPI skill scripts through the skill-local environment",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version",
        "--wwise-version",
        dest="gateway_versions",
        action="append",
        choices=SUPPORTED_WWISE_VERSIONS,
        default=[],
        help=(
            "Compatibility spelling for one gateway Wwise version selector before "
            "gateway.py; normalized to gateway.py --version VERSION"
        ),
    )
    parser.add_argument("script", nargs="?", help="Script to run (for example: gateway.py)")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to the script")
    return parser


def _has_gateway_version_selector_before_subcommand(arguments: list[str]) -> bool:
    """Return whether gateway global arguments already contain a version selector."""

    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value in _GATEWAY_VERSION_OPTIONS or any(
            value.startswith(f"{option}=") for option in _GATEWAY_VERSION_OPTIONS
        ):
            return True
        if value in _GATEWAY_GLOBAL_OPTIONS_WITH_VALUES:
            if index + 1 >= len(arguments):
                return False
            index += 2
            continue
        if any(
            value.startswith(f"{option}=")
            for option in _GATEWAY_GLOBAL_OPTIONS_WITH_VALUES
        ):
            index += 1
            continue
        return False
    return False


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def bootstrap_if_needed() -> None:
    if VENV_DIR.exists():
        return
    setup_script = resolve_packaged_script(SKILL_DIR, "setup_environment.py")
    subprocess.run([sys.executable, str(setup_script)], check=True)


def _wait_for_interrupted_child(
    process: subprocess.Popen[bytes],
    *,
    timeout: float,
) -> bool:
    """Wait a bounded interval while suppressing repeated wrapper interrupts."""

    deadline = time.monotonic() + timeout
    while True:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            return process.poll() is not None
        try:
            process.wait(timeout=remaining)
            return True
        except subprocess.TimeoutExpired:
            return process.poll() is not None
        except KeyboardInterrupt:
            # A repeated terminal interrupt must not abandon the child between
            # cleanup stages. Continue toward the bounded escalation below.
            continue


def _signal_running_child(
    process: subprocess.Popen[bytes],
    action: str,
) -> None:
    """Apply one escalation action without racing a just-exited child."""

    if process.poll() is not None:
        return
    try:
        if action == "interrupt":
            process.send_signal(signal.SIGINT)
        elif action == "terminate":
            process.terminate()
        elif action == "kill":
            process.kill()
        else:  # pragma: no cover - internal closed call surface
            raise ValueError(f"Unsupported child action: {action}")
    except ProcessLookupError:
        return
    except (OSError, ValueError):
        if action == "interrupt":
            # Windows cannot deliver SIGINT to every child configuration.
            # Continue through the bounded terminate/kill fallback instead of
            # adding a wrapper traceback to an already-cancelled command.
            return
        raise


def _reap_interrupted_child(process: subprocess.Popen[bytes]) -> None:
    """Reap a force-killed child even if the wrapper receives another Ctrl-C."""

    while process.poll() is None:
        try:
            process.wait()
        except KeyboardInterrupt:
            continue


def _cleanup_interrupted_child(process: subprocess.Popen[bytes]) -> None:
    """Give the gateway cleanup time, then escalate without orphaning it.

    A terminal Ctrl-C normally reaches the wrapper and child gateway
    synchronously because they share a process group. The first grace period
    therefore deliberately sends no second signal: it lets the gateway emit its
    structured cancellation result and close active WAAPI subscriptions. Only a
    child that remains alive is interrupted again, then terminated, then killed.
    """

    if _wait_for_interrupted_child(
        process,
        timeout=INTERRUPTED_CHILD_CLEANUP_GRACE_SECONDS,
    ):
        return
    _signal_running_child(process, "interrupt")
    if _wait_for_interrupted_child(
        process,
        timeout=INTERRUPTED_CHILD_SIGNAL_GRACE_SECONDS,
    ):
        return
    _signal_running_child(process, "terminate")
    if _wait_for_interrupted_child(
        process,
        timeout=INTERRUPTED_CHILD_TERMINATE_GRACE_SECONDS,
    ):
        return
    _signal_running_child(process, "kill")
    _reap_interrupted_child(process)


def main(argv: list[str] | None = None) -> int:
    if CODEX_GATEWAY_REQUIRED_ENV in os.environ:
        print(
            "Direct run.py execution is disabled for this Codex evaluation; "
            "use the authorized WAAPI gateway broker.",
            file=sys.stderr,
        )
        return CODEX_GATEWAY_REQUIRED_EXIT_CODE

    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.script:
        if args.gateway_versions:
            parser.error("a runner-level version selector requires the exact target gateway.py")
        parser.print_help()
        return 0

    script_arguments = list(args.args)
    if args.gateway_versions:
        if len(args.gateway_versions) != 1:
            parser.error("at most one runner-level version selector is allowed")
        if args.script != "gateway.py":
            parser.error("a runner-level version selector is allowed only before the exact target gateway.py")
        if _has_gateway_version_selector_before_subcommand(script_arguments):
            parser.error("do not combine runner-level and gateway-level version selectors")
        script_arguments = ["--version", args.gateway_versions[0], *script_arguments]

    try:
        script_path = resolve_packaged_script(SKILL_DIR, args.script)
    except PackagedScriptError as exc:
        parser.error(str(exc))

    try:
        bootstrap_if_needed()
    except PackagedScriptError as exc:
        parser.error(str(exc))
    process = subprocess.Popen(
        [str(venv_python()), str(script_path), *script_arguments]
    )
    try:
        return process.wait()
    except KeyboardInterrupt:
        _cleanup_interrupted_child(process)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
