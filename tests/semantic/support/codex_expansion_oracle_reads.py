"""Fixed, version-pinned read projections for runner-only independent oracles.

The callable is held by the existing owned WAAPI actor. It is never installed
in the Agent workspace and cannot accept caller-authored URIs or projections.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping, Sequence

from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError


_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")
_IDENTITY = ("id", "name", "type", "path", "parent")
_VIEWS = {
    "identity": _IDENTITY,
    "music_track": (*_IDENTITY, "@Volume", "@Sequences"),
    "music_sequence": (*_IDENTITY, "@Clips"),
    "music_clip": (*_IDENTITY, "@Volume", "originalFilePath"),
    "audio_source": (*_IDENTITY, "originalFilePath", "audioSource:language", "@VolumeOffset"),
    "rtpc_owner": (*_IDENTITY, "@RTPC", "@Volume", "@OutputBus", "notes"),
    "rtpc": (*_IDENTITY, "@PropertyName", "@ControlInput", "@Curve", "notes"),
    "music_stinger": (*_IDENTITY, "@Trigger", "@Segment", "@NumSegmentAdvance", "@PlaySegmentAt", "notes"),
    "music_stinger_owner": (*_IDENTITY, "@Stingers"),
    "effect_slot": (*_IDENTITY, "owner", "@Effect"),
    "effect_plugin": (*_IDENTITY, "owner", "classId", "notes"),
}


def expansion_oracle_reader(
    *, version: str,
    read_call: Callable[[str, Mapping[str, Any], Mapping[str, Any]], Any],
) -> Callable[[str, Sequence[str]], tuple[Mapping[str, Any], ...]]:
    if version not in {"2022.1", "2025.1"}:
        raise CaseBoundaryError("oracle projection has no reviewed version lane")
    views = {**_VIEWS, "effect_owner": (
        *_IDENTITY,
        *(("@Effect0", "@Effect1", "@Effect2", "@Effect3") if version == "2022.1" else ("@Effects",)),
        "@Volume", "notes",
    )}

    def read(view: str, object_ids: Sequence[str]) -> tuple[Mapping[str, Any], ...]:
        ids = tuple(object_ids)
        if (view not in views or not 1 <= len(ids) <= 64
                or any(not isinstance(item, str) or not _GUID.fullmatch(item) for item in ids)
                or len({item.upper() for item in ids}) != len(ids)):
            raise CaseBoundaryError("oracle needs one fixed view and bounded unique exact GUIDs")
        payload = read_call("ak.wwise.core.object.get", {"from": {"id": list(ids)}},
                            {"return": list(views[view])})
        if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 131_072:
            raise CaseBoundaryError("oracle read exceeded its byte ceiling")
        result = payload.get("return") if isinstance(payload, Mapping) else None
        if not isinstance(result, list) or len(result) != len(ids):
            raise CaseBoundaryError("oracle read omitted or added identities")
        by_id: dict[str, Mapping[str, Any]] = {}
        for row in result:
            key = row.get("id") if isinstance(row, Mapping) else None
            if not isinstance(key, str) or not _GUID.fullmatch(key) or key.upper() in by_id:
                raise CaseBoundaryError("oracle identity is malformed or duplicated")
            by_id[key.upper()] = row
        if set(by_id) != {item.upper() for item in ids}:
            raise CaseBoundaryError("oracle read returned another target")
        return tuple(by_id[item.upper()] for item in ids)

    return read
