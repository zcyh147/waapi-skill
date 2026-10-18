"""Canonical structured creation identity shared by Gateway and receipt observers."""
from __future__ import annotations

from typing import Any, Mapping

from .business_declarations import normalize_live_object_identity


def verified_created_root_identity(verification: Mapping[str, Any]) -> dict[str, str] | None:
    """Use the verifier's structured identity witness, even if a field failed."""
    witnesses = [row.get("evidence") for row in verification.get("assertions", [])
                 if isinstance(row, Mapping) and row.get("kind") == "verified_created_root_identity"
                 and row.get("passed") is True]
    if len(witnesses) != 1 or not isinstance(witnesses[0], Mapping):
        return None
    try:
        value = normalize_live_object_identity(witnesses[0])
    except ValueError:
        return None
    return {"id": value.object_id, "name": value.name, "type": value.object_type, "path": value.path}
