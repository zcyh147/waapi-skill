#!/usr/bin/env python3
"""Create and prepare the skill-local virtual environment."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from dataclasses import dataclass
from pathlib import Path

try:  # pragma: no cover - import path differs between CLI and tests
    from config import SKILL_DIR, VENV_DIR
except ImportError:  # pragma: no cover
    from .config import SKILL_DIR, VENV_DIR


@dataclass(slots=True)
class SkillEnvironment:
    """Manage the local venv used by the Wwise WAAPI skill."""

    skill_dir: Path = SKILL_DIR

    @property
    def venv_dir(self) -> Path:
        return VENV_DIR

    @property
    def requirements_file(self) -> Path:
        return self.skill_dir / "requirements.txt"

    @property
    def python_executable(self) -> Path:
        if os.name == "nt":
            return self.venv_dir / "Scripts" / "python.exe"
        return self.venv_dir / "bin" / "python"

    @property
    def pip_executable(self) -> Path:
        if os.name == "nt":
            return self.venv_dir / "Scripts" / "pip.exe"
        return self.venv_dir / "bin" / "pip"

    def ensure(self) -> bool:
        """Create the venv and install dependencies when missing."""

        if not self.venv_dir.exists():
            venv.create(self.venv_dir, with_pip=True)

        if not self.requirements_file.exists():
            return True

        subprocess.run(
            [str(self.pip_executable), "install", "-r", str(self.requirements_file)],
            check=True,
        )
        return True

    def run(self, script_name: str, args: list[str]) -> int:
        script_path = self.skill_dir / "scripts" / script_name
        if not script_path.exists():
            print(f"Script not found: {script_name}")
            return 1

        self.ensure()
        result = subprocess.run([str(self.python_executable), str(script_path), *args])
        return result.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the Wwise WAAPI skill environment")
    parser.add_argument("--check", action="store_true", help="Check whether the venv exists")
    parser.add_argument("--run", help="Run a script through the skill venv")
    parser.add_argument("args", nargs="*", help="Arguments passed through to the script")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = SkillEnvironment()

    if args.check:
        print(env.venv_dir)
        return 0 if env.venv_dir.exists() else 1

    if args.run:
        return env.run(args.run, args.args)

    env.ensure()
    print(env.venv_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
