"""Pinned Authoring-only core routes approved independently of Console."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .authoring_ui_commands_manifest import AuthoringUiCommandsSupplementError
from .canonical import canonical_sha256


COMMON_URIS = frozenset({
    "ak.wwise.core.remote.connect", "ak.wwise.core.remote.disconnect",
    "ak.wwise.core.remote.getAvailableConsoles", "ak.wwise.core.remote.getConnectionStatus",
    "ak.wwise.ui.bringToForeground", "ak.wwise.ui.getSelectedObjects",
    "ak.wwise.ui.project.close", "ak.wwise.ui.project.create", "ak.wwise.ui.project.open",
})
FILENAME = "authoring-core-supplement.json"
PINNED_SHA256 = {
    "2024.1": "0c8ad3a286ce9c2ffcd76701c84b51629fe70e5d55f169180db142e0173f845e",
    "2025.1": "c6b8c815ecd0c6fe18c3a69d3dc5b500cded78ab9b57ca40a57b1a159325faa2",
}


def requires_core_supplement(version: str, uri: str) -> bool:
    return version in PINNED_SHA256 and (
        uri in COMMON_URIS or (version == "2025.1" and uri == "ak.wwise.ui.getSelectedFiles")
    )


def merge_authoring_core(
    manifest: Mapping[str, Any], *, root: Path | None, version: str,
) -> dict[str, Any]:
    result = deepcopy(dict(manifest))
    if version not in PINNED_SHA256:
        return result
    if root is None:
        raise AuthoringUiCommandsSupplementError("Authoring core requires pinned resources")
    try:
        payload = json.loads((root / version / FILENAME).read_bytes())
    except (OSError, ValueError) as exc:
        raise AuthoringUiCommandsSupplementError("Missing or invalid Authoring core evidence") from exc
    expected = COMMON_URIS | ({"ak.wwise.ui.getSelectedFiles"} if version == "2025.1" else set())
    if (canonical_sha256(payload) != PINNED_SHA256[version]
            or payload.get("contract") != "waapi-authoring-core-supplement/v1"
            or payload.get("version") != version or payload.get("host") != "wwise-authoring"
            or set(payload.get("schemas", {})) != expected):
        raise AuthoringUiCommandsSupplementError("Authoring core evidence identity or digest mismatch")
    existing = {row["uri"] for row in result["functions"]}
    for uri, schema in sorted(payload["schemas"].items()):
        if uri in existing or not all(isinstance(schema.get(key), dict) for key in (
            "argsSchema", "optionsSchema", "resultSchema",
        )):
            raise AuthoringUiCommandsSupplementError("Authoring core cannot replace or omit schema contracts")
        result["functions"].append({"uri": uri, "description": schema.get("description", ""),
                                    "host_surface": "wwise-authoring"})
        result["schemas"].append({"uri": uri, "status": "ok", "schema": schema})
    result["functions"].sort(key=lambda row: row["uri"])
    result["schemas"].sort(key=lambda row: row["uri"])
    result.setdefault("metadata", {})["authoring_core_evidence"] = {
        "wwise_build": payload["wwise_build"], "sha256": PINNED_SHA256[version],
        "full_authoring_inventory_reflected": False,
    }
    return result
