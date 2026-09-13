"""Pinned, read-only Authoring Topic reflection beyond the UI-command family."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .authoring_ui_commands_manifest import AuthoringUiCommandsSupplementError
from .canonical import canonical_sha256


AUTHORING_UI_OBSERVATION_TOPICS = frozenset({
    "ak.wwise.ui.selectionChanged",
    "ak.wwise.ui.signal.click",
    "ak.wwise.ui.signal.toggle",
})
FILENAME = "authoring-ui-topics-supplement.json"
CONTRACT = "waapi-authoring-ui-topics-supplement/v1"
# Canonical JSON digests keep Windows checkout line endings immaterial.
PINNED_SHA256 = {
    "2024.1": "a049822cd51963212e6d1b6d044bd63a0cbfb59d1fefa465004b3676218a9849",
    "2025.1": "ce6639ab94365ac0efbb8eb4f4f1e71f17b188bafa7265729f559eda1b5969cc",
}


def merge_authoring_ui_topics(
    manifest: Mapping[str, Any], *, root: Path | None, version: str,
) -> dict[str, Any]:
    """Add only reviewed Topics; never change the canonical Console inventory."""
    result = deepcopy(dict(manifest))
    if version not in PINNED_SHA256:
        return result
    if root is None:
        raise AuthoringUiCommandsSupplementError("Authoring Topic evidence requires a manifest root")
    path = root / version / FILENAME
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AuthoringUiCommandsSupplementError(f"Missing Authoring Topic evidence: {path}") from exc
    payload = json.loads(raw)
    if canonical_sha256(payload) != PINNED_SHA256[version]:
        raise AuthoringUiCommandsSupplementError(f"Authoring Topic evidence digest mismatch: {version}")
    if (payload.get("contract") != CONTRACT or payload.get("version") != version
            or payload.get("host") != "wwise-authoring"):
        raise AuthoringUiCommandsSupplementError("Authoring Topic evidence identity mismatch")
    schemas = payload.get("schemas")
    if not isinstance(schemas, dict) or set(schemas) != AUTHORING_UI_OBSERVATION_TOPICS:
        raise AuthoringUiCommandsSupplementError("Authoring Topic evidence must contain the reviewed three Topics")
    existing = {row["uri"] for row in result["topics"]}
    for uri, schema in sorted(schemas.items()):
        if uri in existing:
            raise AuthoringUiCommandsSupplementError(f"Authoring Topic supplement would replace an existing Topic: {uri}")
        if not isinstance(schema, dict) or not all(isinstance(schema.get(key), dict) for key in ("optionsSchema", "publishSchema")):
            raise AuthoringUiCommandsSupplementError(f"Incomplete Authoring Topic schema: {uri}")
        result["topics"].append({
            "uri": uri, "description": schema.get("description", ""),
            "host_surface": "wwise-authoring",
        })
        result["schemas"].append({"uri": uri, "status": "ok", "schema": schema})
    result["topics"].sort(key=lambda row: row["uri"])
    result["schemas"].sort(key=lambda row: row["uri"])
    result.setdefault("metadata", {})["surface_profile"] = "console-with-authoring-ui-commands-and-topics"
    result["metadata"]["authoring_ui_topics_evidence"] = {
        "wwise_build": payload["wwise_build"], "sha256": PINNED_SHA256[version],
        "full_authoring_inventory_reflected": False,
    }
    return result
