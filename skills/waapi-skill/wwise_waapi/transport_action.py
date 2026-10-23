"""Bounded, operation-local transport action observations.

The matching 2021.1–2025.1 SDK examples specify play, stop, pause/resume
and play/stop toggles. They do not specify playDirectly or the stopped-pause
and paused-playStop edges. A later stopped read cannot disprove transient play.
"""
from __future__ import annotations

from collections.abc import Mapping
import re

from .builders.schema import validate_semantic_result


LIST = "ak.wwise.core.transport.getList"
STATE = "ak.wwise.core.transport.getState"
MAX_TARGETS = 64
STATES = {"playing", "paused", "stopped"}
_GUID = re.compile(r"\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}")


def snapshot(args: Mapping, *, version: str, read) -> dict:
    """Bind exact target associations and only the state needed by toggles."""
    result = read(LIST, {}, {})
    validate_semantic_result(LIST, result, version=version)
    rows = result.get("list") if isinstance(result, Mapping) else None
    if not isinstance(rows, list) or ("transport" not in args and len(rows) > MAX_TARGETS):
        raise ValueError("Transport list is missing or exceeds the 64-target observation bound.")
    targets = []
    seen = set()
    for row in rows:
        native_id = row.get("transport") if isinstance(row, Mapping) else None
        object_id = row.get("object") if isinstance(row, Mapping) else None
        game_object = row.get("gameObject") if isinstance(row, Mapping) else None
        if (type(native_id) is not int or not 0 <= native_id <= 0xFFFFFFFF
                or native_id in seen or not isinstance(object_id, str) or not _GUID.fullmatch(object_id)
                or type(game_object) is not int or not 0 <= game_object <= 0xFFFFFFFFFFFFFFFF):
            raise ValueError("Transport list has malformed or duplicate target associations.")
        seen.add(native_id)
        if "transport" in args and native_id != args["transport"]:
            continue
        target = {"transport": native_id, "object": object_id.upper(), "gameObject": game_object}
        if args["action"] in {"pause", "playStop"}:
            state_result = read(STATE, {"transport": native_id}, {})
            validate_semantic_result(STATE, state_result, version=version)
            state = state_result.get("state") if isinstance(state_result, Mapping) else None
            if state not in STATES:
                raise ValueError("Transport toggle prestate is unavailable or malformed.")
            target["state"] = state
        targets.append(target)
    if "transport" in args and len(targets) != 1:
        raise ValueError("Selected transport does not resolve to one exact live target.")
    return {"scope": "one-transport" if "transport" in args else "all-active",
        "targets": sorted(targets, key=lambda row: row["transport"])}


def expected_state(action: str, before: Mapping) -> tuple[str | None, str | None]:
    if action == "stop":
        return "stopped", None
    if action == "play":
        return "playing", None
    if action == "pause":
        return ({"playing": "paused", "paused": "playing"}.get(before.get("state")),
            "pause_from_stopped_semantics_unresolved" if before.get("state") == "stopped" else None)
    if action == "playStop":
        return ({"playing": "stopped", "stopped": "playing"}.get(before.get("state")),
            "play_stop_from_paused_semantics_unresolved" if before.get("state") == "paused" else None)
    return None, "play_directly_semantics_unresolved"
