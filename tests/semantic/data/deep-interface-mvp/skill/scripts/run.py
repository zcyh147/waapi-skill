#!/usr/bin/env python3
"""Test-only stateful fake Gateway for the #52 Fresh Agent MVP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


CONTRACT = "waapi-skill.gateway-result/v1"
ROOT_HANDLE = "mvp-obj-root000000000000000001"
BUS_HANDLE = "mvp-obj-bus000000000000000002"
STRUCTURE_HANDLE = "mvp-new-weather00000000000003"
RIFLE_HANDLE = "mvp-obj-rifle0000000000000004"
FOOTSTEPS_HANDLE = "mvp-obj-footsteps000000000005"
WEAPONS_HANDLE = "mvp-obj-weapons000000000000006"
STATE_ENV = "WAAPI_SKILL_STATE_DIR"
FAMILIES = frozenset({"weather", "rifle", "footsteps", "weapons"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("script")
    sub = parser.add_subparsers(dest="command", required=True)
    context = sub.add_parser("mvp-context", add_help=False)
    context.add_argument("--family", required=True)
    structure = sub.add_parser("mvp-structure", add_help=False)
    structure.add_argument("--parent", required=True)
    structure.add_argument("--name", required=True)
    structure.add_argument("--kind", required=True)
    asset = sub.add_parser("mvp-asset", add_help=False)
    asset.add_argument("--parent", required=True)
    asset.add_argument("--name", required=True)
    asset.add_argument("--kind", required=True)
    asset.add_argument("--media", required=True)
    asset.add_argument("--language", required=True)
    asset.add_argument("--volume-db", type=float)
    asset.add_argument("--loop")
    asset.add_argument("--output-bus")
    asset.add_argument("--switch-value")
    existing = sub.add_parser("mvp-existing-asset", add_help=False)
    existing.add_argument("--target", required=True)
    existing.add_argument("--media", required=True)
    existing.add_argument("--language", required=True)
    sub.add_parser("mvp-preview", add_help=False)
    return parser


def _state_path() -> Path:
    root = Path(os.environ.get(STATE_ENV, ".mvp-state")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / "deep-import-mvp.json"


def _load() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"family": None, "structure": None, "assets": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("MVP state is malformed")
    return value


def _save(value: dict[str, Any]) -> None:
    path = _state_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _result(command: str, agent_result: dict[str, Any]) -> int:
    payload = {
        "contract": CONTRACT,
        "ok": True,
        "command": command,
        "session_context": {
            "test_only": True,
            "wwise_connected": False,
            "project_modification_policy": "read_only",
        },
        "agent_result": agent_result,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return 0


def _context(family: str) -> dict[str, Any]:
    family_context = {
        "weather": {
            "parent_handle": ROOT_HANDLE,
            "media_keys": ["rain", "wind"],
        },
        "rifle": {"target_handle": RIFLE_HANDLE, "media_keys": ["rifle"]},
        "footsteps": {
            "parent_handle": FOOTSTEPS_HANDLE,
            "media_keys": ["snow_step"],
        },
        "weapons": {
            "parent_handle": WEAPONS_HANDLE,
            "media_keys": ["mechanical", "tail"],
        },
    }[family]
    return {
        "contract": "waapi-skill.audio-import-mvp-context/v1",
        "family": family,
        "output_bus_handle": BUS_HANDLE,
        **family_context,
        "business_kinds": ["actor-mixer", "sound-sfx"],
        "loop_values": ["infinite"],
        "command_schemas": {
            "mvp-structure": {
                "required": ["--parent", "--name", "--kind"],
                "use_when": "one requested new business container",
            },
            "mvp-asset": {
                "required": [
                    "--parent",
                    "--name",
                    "--kind",
                    "--media",
                    "--language",
                ],
                "optional_when_requested": [
                    "--volume-db",
                    "--loop",
                    "--output-bus",
                    "--switch-value",
                ],
            },
            "mvp-existing-asset": {
                "required": ["--target", "--media", "--language"],
                "use_when": "re-import one already bound target",
            },
            "mvp-preview": {
                "required": [],
                "use_when": "every requested business declaration is complete",
            },
        },
        "help_commands_forbidden": True,
        "compiler_owns": [
            "wwise_path",
            "wire_type",
            "metadata_scope",
            "native_row_order",
            "batching",
            "continuation",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.script != "gateway.py":
        raise SystemExit(2)
    if args.command == "mvp-context":
        if args.family not in FAMILIES:
            raise SystemExit(2)
        _save({"family": args.family, "structure": None, "assets": []})
        return _result(args.command, _context(args.family))

    state = _load()
    if args.command == "mvp-structure":
        if state.get("family") != "weather" or (
            args.parent,
            args.name,
            args.kind,
        ) != (ROOT_HANDLE, "Weather", "actor-mixer"):
            raise SystemExit(2)
        state["structure"] = {
            "handle": STRUCTURE_HANDLE,
            "name": args.name,
            "kind": args.kind,
        }
        _save(state)
        return _result(
            args.command,
            {
                "declared": True,
                "object_handle": STRUCTURE_HANDLE,
                "draft_changed": True,
            },
        )

    if args.command == "mvp-asset":
        family = str(state.get("family"))
        expected = {
            "weather": {
                "Rain_Bed": (STRUCTURE_HANDLE, "rain", -4.0, "infinite", BUS_HANDLE, None),
                "Wind_Bed": (STRUCTURE_HANDLE, "wind", -6.0, "infinite", BUS_HANDLE, None),
            },
            "footsteps": {
                "Snow_Step": (FOOTSTEPS_HANDLE, "snow_step", -2.0, None, BUS_HANDLE, "Snow"),
            },
            "weapons": {
                "Rifle_Mechanical": (WEAPONS_HANDLE, "mechanical", -3.0, None, BUS_HANDLE, None),
                "Rifle_Tail": (WEAPONS_HANDLE, "tail", -6.0, None, BUS_HANDLE, None),
            },
        }.get(family, {})
        actual = (
            args.parent,
            args.media,
            args.volume_db,
            args.loop,
            args.output_bus,
            args.switch_value,
        )
        if (
            args.kind != "sound-sfx"
            or args.language != "SFX"
            or expected.get(args.name) != actual
        ):
            raise SystemExit(2)
        assets = list(state.get("assets", []))
        if any(item.get("name") == args.name for item in assets):
            raise SystemExit(2)
        assets.append(
            {
                "name": args.name,
                "kind": args.kind,
                "media": args.media,
                "language": args.language,
                "volume_db": args.volume_db,
                "loop": args.loop,
                "output_bus": args.output_bus,
                "switch_value": args.switch_value,
            }
        )
        state["assets"] = assets
        _save(state)
        return _result(
            args.command,
            {"declared": True, "asset_count": len(assets), "draft_changed": True},
        )

    if args.command == "mvp-existing-asset":
        if (
            state.get("family") != "rifle"
            or args.target != RIFLE_HANDLE
            or args.media != "rifle"
            or args.language != "SFX"
        ):
            raise SystemExit(2)
        state["assets"] = [
            {
                "name": "Rifle",
                "target": args.target,
                "media": args.media,
                "language": args.language,
                "mode": "re-import",
            }
        ]
        _save(state)
        return _result(
            args.command,
            {"declared": True, "mode": "re-import", "draft_changed": True},
        )

    if args.command == "mvp-preview":
        family = str(state.get("family"))
        names = sorted(item.get("name") for item in state.get("assets", []))
        expected_names = {
            "weather": ["Rain_Bed", "Wind_Bed"],
            "rifle": ["Rifle"],
            "footsteps": ["Snow_Step"],
            "weapons": ["Rifle_Mechanical", "Rifle_Tail"],
        }.get(family)
        if names != expected_names or (
            family == "weather"
            and state.get("structure", {}).get("name") != "Weather"
        ):
            raise SystemExit(2)
        preview_by_family = {
            "weather": [
                "对象：Weather",
                "类型：Actor-Mixer",
                "对象：Rain_Bed",
                "类型：Sound SFX",
                "循环方式：Infinite",
                "音量：-4 dB",
                "输出总线：Weather_Bus",
                "对象：Wind_Bed",
                "类型：Sound SFX",
                "循环方式：Infinite",
                "音量：-6 dB",
                "输出总线：Weather_Bus",
            ],
            "rifle": ["对象：Rifle", "操作：Re-import", "类型：Sound SFX"],
            "footsteps": ["对象：Snow_Step", "类型：Sound SFX", "Switch 值：Snow", "音量：-2 dB"],
            "weapons": ["对象：Rifle_Mechanical", "音量：-3 dB", "对象：Rifle_Tail", "音量：-6 dB"],
        }
        return _result(
            args.command,
            {
                "contract": "waapi-skill.audio-import-business-preview/v1",
                "test_only": True,
                "wwise_mutated": False,
                "native_call_count": 1,
                "compiler_evidence": {
                    "metadata_scope": "Sound",
                    "wire_type": "Sound SFX",
                    "path_owner": "gateway",
                    "native_order": ["structure", "sound", "media"],
                },
                "preview": preview_by_family[family],
            },
        )
    raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(main())
