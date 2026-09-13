"""Collect the approved Authoring core delta through the public Gateway only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


COMMON_URIS = (
    "ak.wwise.core.remote.connect",
    "ak.wwise.core.remote.disconnect",
    "ak.wwise.core.remote.getAvailableConsoles",
    "ak.wwise.core.remote.getConnectionStatus",
    "ak.wwise.ui.bringToForeground",
    "ak.wwise.ui.getSelectedObjects",
    "ak.wwise.ui.project.close",
    "ak.wwise.ui.project.create",
    "ak.wwise.ui.project.open",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("2024.1", "2025.1"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    runner = root / "skills/waapi-skill/scripts/run.py"

    def call(label: str, *command: str) -> dict:
        result = subprocess.run(
            [sys.executable, str(runner), "gateway.py", "--version", args.version, *command],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        (args.output / f"{label}.json").write_text(result.stdout, encoding="utf-8")
        (args.output / f"{label}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        payload = json.loads(result.stdout)
        if result.returncode or not payload.get("ok"):
            raise RuntimeError(f"{label} failed; preserved evidence in {args.output}")
        return payload

    status = call("status", "status")
    if status.get("is_command_line") is not False:
        raise RuntimeError("Matching Authoring required; no schemas collected")
    uris = (*COMMON_URIS, "ak.wwise.ui.getSelectedFiles") if args.version == "2025.1" else COMMON_URIS
    for uri in uris:
        call(uri, "waapi-schema", uri, "--exclude-examples")
        print(f"Collected {uri}", flush=True)


if __name__ == "__main__":
    main()
