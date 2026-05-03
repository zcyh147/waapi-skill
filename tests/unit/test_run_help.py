from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_run_help_exits_zero() -> None:
    skill_root = Path(__file__).resolve().parents[2] / "skills" / "wwise-waapi"
    result = subprocess.run(
        [sys.executable, str(skill_root / "scripts" / "run.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Run Wwise WAAPI skill scripts" in result.stdout
