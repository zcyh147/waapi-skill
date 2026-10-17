"""Capture a complete native catalog through config-bound public Gateway reads.

The historical filename is retained. This collector never starts Wwise, edits
configuration, calls a native client, or installs captured routes for execution.
An already-running owned project and explicit isolated config are required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills/waapi-skill"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))
from wwise_waapi.native_catalog import validate_native_catalog

VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def main(argv=None, *, run=subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=VERSIONS, required=True, help="Expected version; never forwarded as a live override")
    parser.add_argument("--build", required=True, help="Exact expected year.major.minor.build")
    parser.add_argument("--host", choices=("wwise-console", "wwise-authoring"), required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.config.is_absolute() or not args.config.is_file():
        parser.error("--config must identify an existing absolute isolated config")
    args.output.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, "WAAPI_SKILL_CONFIG_PATH": str(args.config)}
    config_digest = hashlib.sha256(args.config.read_bytes()).hexdigest()
    sources = {}
    initial = None

    def call(label, *command):
        if hashlib.sha256(args.config.read_bytes()).hexdigest() != config_digest:
            raise RuntimeError("Selected configuration changed during collection")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", label):
            raise RuntimeError("Unsafe native receipt label")
        result = run([sys.executable, str(SKILL_ROOT / "scripts/run.py"), "gateway.py", *command],
                     capture_output=True, text=True, encoding="utf-8", timeout=90, env=env)
        if hashlib.sha256(args.config.read_bytes()).hexdigest() != config_digest:
            raise RuntimeError("Selected configuration changed during collection")
        raw = result.stdout.encode("utf-8")
        (args.output / f"{label}.json").write_bytes(raw)
        (args.output / f"{label}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        sources[f"{label}.json"] = hashlib.sha256(raw).hexdigest()
        payload = json.loads(result.stdout)
        if result.returncode or not payload.get("ok"):
            raise RuntimeError(f"{label} failed; evidence preserved at {args.output}")
        if not payload.get("offline") and "detected_version" in payload:
            if payload["detected_version"] != args.version or payload.get("is_command_line") is not (args.host == "wwise-console"):
                raise RuntimeError("Native host/version differs from requested collection")
        if initial is not None and command[0] in {"waapi-schema", "typed-zero-call"}:
            if not isinstance(payload.get("reflection_context"), dict):
                raise RuntimeError("Native read attestation missing")
            if attestation({"wwise": payload["reflection_context"]}) != initial:
                raise RuntimeError("Native session changed during collection")
        return payload

    def attestation(payload):
        info = payload["wwise"]
        if info.get("isCommandLine") is not (args.host == "wwise-console"):
            raise RuntimeError("Native attestation host mismatch")
        build = ".".join(str(info["version"][key]) for key in ("year", "major", "minor", "build"))
        if build != args.build or not build.startswith(args.version + "."):
            raise RuntimeError(f"Native build mismatch: expected {args.build}, observed {build}")
        if not info.get("sessionId") or not info.get("processId"):
            raise RuntimeError("Native session/process identity missing")
        return {"host": args.host, "build": build, "session_id": info["sessionId"], "process_id": info["processId"]}

    initial = attestation(call("status-start", "status"))
    inventories = {}
    inventory_commands = {}
    for kind in ("functions", "topics"):
        uri = "ak.wwise.waapi.get" + kind.title()
        contract = call(f"{kind}-contract", "request-schema", uri)
        command = contract["continuation"]["gateway_argv"]
        if command[:2] != ["typed-zero-call", uri]:
            raise RuntimeError("Unexpected reflection continuation")
        inventory_commands[kind] = command
        result = call(kind, *command)
        inventories[kind] = result["agent_result"]["uris"]
    schemas = {}
    for uri in sorted(set(inventories["functions"] + inventories["topics"])):
        flags = ("--exclude-examples",) if args.version in ("2024.1", "2025.1") else ()
        schemas[uri] = call(uri, "waapi-schema", uri, *flags)["agent_result"]
        print(f"Collected {uri}", flush=True)
    for kind, command in inventory_commands.items():
        if call(f"{kind}-end", *command)["agent_result"]["uris"] != inventories[kind]:
            raise RuntimeError("Native inventory changed during collection")
    final = attestation(call("status-end", "status"))
    if final != initial:
        raise RuntimeError("Native session changed during collection")
    definitions_path = SKILL_ROOT / "resources/manifest" / args.version / "definitions.json"
    definitions = json.loads(definitions_path.read_text(encoding="utf-8"))
    if definitions["wwise_build"] != args.build:
        raise RuntimeError("Matching-build referenced definitions must be collected before publication")
    catalog = {"contract": "waapi-skill.native-catalog/v1", "version": args.version,
               **inventories, "schemas": schemas, "definitions": definitions,
               "provenance": {**initial, "collected_at": datetime.now(timezone.utc).isoformat(),
                              "evidence_kind": "reflection_only", "configuration_sha256": config_digest,
                              "sources": sources, "definitions_source": {"path": f"resources/manifest/{args.version}/definitions.json", "sha256": hashlib.sha256(definitions_path.read_bytes()).hexdigest()}}}
    validate_native_catalog(catalog)
    catalog["content_sha256"] = digest(catalog)
    (args.output / "native-catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
