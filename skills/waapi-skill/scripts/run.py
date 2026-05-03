#!/usr/bin/env python3
"""Thin wrapper for running Wwise WAAPI skill scripts inside the local venv."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

try:  # pragma: no cover - import path differs between CLI and tests
    from config import SKILL_DIR, VENV_DIR
except ImportError:  # pragma: no cover
    from .config import SKILL_DIR, VENV_DIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Run Wwise WAAPI skill scripts through the skill-local environment",
    )
    parser.add_argument("script", nargs="?", help="Script to run (for example: setup_environment.py)")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to the script")
    return parser


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def bootstrap_if_needed() -> None:
    if VENV_DIR.exists():
        return
    setup_script = SKILL_DIR / "scripts" / "setup_environment.py"
    subprocess.run([sys.executable, str(setup_script)], check=True)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.script:
        parser.print_help()
        return 0

    script_name = args.script.removeprefix("scripts/")
    if not script_name.endswith(".py"):
        script_name = f"{script_name}.py"

    script_path = SKILL_DIR / "scripts" / script_name
    if not script_path.exists():
        parser.error(f"unknown script: {args.script}")

    bootstrap_if_needed()
    result = subprocess.run([str(venv_python()), str(script_path), *args.args])
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
