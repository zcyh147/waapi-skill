"""Gateway-owned Short ID reads from pinned selector and WAQL sources.

2022.1–2025.1 definitions.shortId.type documents the numeric codes below.
All five matching SDK WAQL references document the numeric shortId accessor;
matching Wwise Objects Reference titles establish the closed type spellings.
See references/semantic/<version>/short-id-query-sources.json for source seals.
2021.1 never borrows the later numeric codes.
"""
from __future__ import annotations

from typing import Any

from wwise_waapi.builders.query import QueryPredicate, build_object_get_query
from wwise_waapi.builders.schema import validate_resolved_semantic_payload

SHORT_ID_KIND_TYPES = {
    "event": "Event", "switch-group": "SwitchGroup", "state-group": "StateGroup",
    "effect": "Effect", "soundbank": "SoundBank", "bus": "Bus", "aux-bus": "AuxBus",
    "game-parameter": "GameParameter", "trigger": "Trigger", "audio-device": "AudioDevice",
    "dialogue-event": "DialogueEvent",
}

SHORT_ID_KIND_CODES = {
    "event": 10, "switch-group": 12, "state-group": 14, "effect": 17,
    "soundbank": 18, "bus": 19, "aux-bus": 20, "game-parameter": 22,
    "trigger": 41, "audio-device": 68,
}
SHORT_ID_KIND_VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")
SHORT_ID_VERSIONS = ("2021.1", *SHORT_ID_KIND_VERSIONS)


def short_id_query(version: str, *, number: int, kind: str | None,
                   unique: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Construct the complete bounded read; callers cannot supply native syntax.

    Ordinary reads preserve up to 64 collision candidates plus one ceiling row.
    A Definition needs one unique identity, so its second row proves ambiguity.
    """
    if version not in SHORT_ID_VERSIONS:
        raise ValueError("Short ID lookup requires a supported pinned Wwise version")
    if kind not in SHORT_ID_KIND_TYPES:
        raise ValueError("--short-id requires --short-id-kind copied from the disclosed business kinds")
    if type(number) is not int or not 0 <= number <= 0xFFFFFFFF:
        raise ValueError("Short ID requires one uint32")
    limit = 2 if unique else 65
    fields = ["id", "name", "type", "path"]
    if unique:
        fields.extend(["parent", "notes", "shortId"])
    if version in SHORT_ID_KIND_VERSIONS and kind in SHORT_ID_KIND_CODES:
        args = {"from": {"id": [short_id_selector(version, number=number, kind=kind)]},
                "transform": [{"range": [0, limit]}]}
        options = {"return": fields}
        validate_resolved_semantic_payload("ak.wwise.core.object.get", args, options, version=version)
        return args, options
    preview = build_object_get_query(version=version, type=SHORT_ID_KIND_TYPES[kind],
        where=QueryPredicate("shortId", "=", number), take=limit, return_fields=fields)
    return dict(preview.envelope.args), dict(preview.envelope.options)


def short_id_selector(version: str, *, number: int, kind: str | None) -> dict[str, int]:
    if kind not in SHORT_ID_KIND_CODES:
        raise ValueError("--short-id requires --short-id-kind copied from the disclosed business kinds")
    if version not in SHORT_ID_KIND_VERSIONS:
        raise ValueError("Numeric Short ID type codes are pinned only for Wwise 2022.1–2025.1; use the Gateway-owned typed lookup for 2021.1")
    if type(number) is not int or not 0 <= number <= 0xFFFFFFFF:
        raise ValueError("Short ID requires one uint32")
    return {"shortId": number, "type": SHORT_ID_KIND_CODES[kind]}
