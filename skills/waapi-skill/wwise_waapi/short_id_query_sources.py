"""Closed Short ID selector kinds from version-pinned native definitions.

2022.1–2025.1 definitions.shortId.type explicitly documents these codes.
2021.1 refers to an object index whose PluginID is not the same code table;
its business-kind mapping awaits an exact native observation, never inference
from classId or a later lane.
"""
from __future__ import annotations

SHORT_ID_KIND_CODES = {
    "event": 10, "switch-group": 12, "state-group": 14, "effect": 17,
    "soundbank": 18, "bus": 19, "aux-bus": 20, "game-parameter": 22,
    "trigger": 41, "audio-device": 68,
}
SHORT_ID_KIND_VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")


def short_id_selector(version: str, *, number: int, kind: str | None) -> dict[str, int]:
    if kind not in SHORT_ID_KIND_CODES:
        raise ValueError("--short-id requires --short-id-kind copied from the disclosed business kinds")
    if version not in SHORT_ID_KIND_VERSIONS:
        raise ValueError("Wwise 2021.1 Short ID business-kind mapping remains unresolved: its native definition refers to an object index, not the later explicit code table; use a canonical GUID/path until matching native proof is captured")
    if type(number) is not int or not 0 <= number <= 0xFFFFFFFF:
        raise ValueError("Short ID requires one uint32")
    return {"shortId": number, "type": SHORT_ID_KIND_CODES[kind]}
