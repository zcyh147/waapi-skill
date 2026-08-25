"""Fail-closed interpretation of reflected Wwise metadata restrictions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class MetadataRestrictionError(ValueError):
    error_code: str
    message: str

    def __str__(self) -> str:
        return self.message


def reference_allowed_types(restriction: Mapping[str, Any]) -> tuple[str, ...]:
    """Return exact allowed reference types or reject unproven constraints."""

    if not isinstance(restriction, Mapping):
        raise MetadataRestrictionError(
            "INVALID_METADATA",
            "Reference restriction metadata must be an object.",
        )
    rows = restriction.get("restrictions")
    if rows is None:
        return ()
    if not isinstance(rows, list):
        raise MetadataRestrictionError(
            "INVALID_METADATA",
            "Reference restriction metadata must be an array when present.",
        )
    allowed: set[str] = set()
    for row in rows:
        if isinstance(row, str):
            if row == "notNull":
                continue
            if row == "playable":
                raise MetadataRestrictionError(
                    "CONSTRAINED_REFERENCE_BOUNDARY",
                    "Playable reference restrictions require a dedicated live target classifier.",
                )
            raise MetadataRestrictionError(
                "INVALID_METADATA",
                "Reference restriction metadata contains an unknown string flag.",
            )
        if not isinstance(row, Mapping):
            raise MetadataRestrictionError(
                "INVALID_METADATA",
                "Reference restriction entries must be objects or supported string flags.",
            )
        values = row.get("type")
        if values is None:
            continue
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values
        ):
            raise MetadataRestrictionError(
                "INVALID_METADATA",
                "Reference restriction type entries must be non-empty string arrays.",
            )
        allowed.update(values)
    return tuple(sorted(allowed))


def reference_type_token(value: str) -> str:
    """Normalize one reflected/live Wwise reference target type consistently."""

    if not isinstance(value, str) or not value:
        raise ValueError("reference target type must be a non-empty string")
    token = "".join(character for character in value.casefold() if character.isalnum())
    aliases = {
        "audiobus": "bus",
        "auxiliarybus": "auxbus",
        "auxbus": "auxbus",
    }
    return aliases.get(token, token)


__all__ = [
    "MetadataRestrictionError",
    "reference_allowed_types",
    "reference_type_token",
]
