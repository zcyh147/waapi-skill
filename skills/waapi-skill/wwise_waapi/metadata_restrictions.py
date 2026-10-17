"""Fail-closed interpretation of reflected Wwise metadata restrictions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import math


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


def condition_restriction(conditions: Any) -> dict[str, Any]:
    """Validate the native scalar condition without selecting a business value."""
    if not isinstance(conditions, list) or len(conditions) != 1 or not isinstance(conditions[0], Mapping) or set(conditions[0]) != {"restriction"}:
        raise MetadataRestrictionError("INVALID_METADATA", "A scalar dependency requires one restriction condition.")
    restriction = conditions[0]["restriction"]
    if not isinstance(restriction, Mapping):
        raise MetadataRestrictionError("INVALID_METADATA", "Condition restriction must be an object.")
    if restriction.get("type") == "enum" and set(restriction) == {"type", "values"}:
        values = restriction["values"]
        if isinstance(values, list) and values and all(
            isinstance(row, Mapping) and "value" in row and set(row) <= {"value", "displayName"}
            and isinstance(row["value"], (str, bool, int, float))
            and (not isinstance(row["value"], float) or math.isfinite(row["value"]))
            for row in values
        ):
            return dict(restriction)
    if restriction.get("type") == "range" and set(restriction) == {"type", "min", "max"}:
        if all(isinstance(restriction[key], (int, float)) and not isinstance(restriction[key], bool)
               and math.isfinite(restriction[key]) for key in ("min", "max")) and restriction["min"] <= restriction["max"]:
            return dict(restriction)
    raise MetadataRestrictionError("INVALID_METADATA", "Condition restriction is malformed or has an unimplemented native shape.")


def condition_values_equal(left: Any, right: Any) -> bool:
    """Compare native scalars without treating Boolean values as numbers."""
    if isinstance(left, (int, float)) and not isinstance(left, bool):
        return (isinstance(right, (int, float)) and not isinstance(right, bool)
                and math.isfinite(left) and math.isfinite(right) and left == right)
    return type(left) is type(right) and left == right


def condition_matches(restriction: Mapping[str, Any], value: Any) -> bool:
    """Evaluate a validated scalar condition with Boolean/number distinction."""
    if restriction["type"] == "enum":
        return any(condition_values_equal(value, row["value"]) for row in restriction["values"])
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and restriction["min"] <= value <= restriction["max"])


def intersect_condition_restrictions(restrictions: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Combine accumulated native requirements before selecting any value."""
    enums = [item for item in restrictions if item["type"] == "enum"]
    if enums:
        values = [dict(row) for row in enums[0]["values"]
                  if all(condition_matches(item, row["value"]) for item in restrictions)]
        if values:
            return {"type": "enum", "values": values}
    else:
        minimum = max(item["min"] for item in restrictions)
        maximum = min(item["max"] for item in restrictions)
        if minimum <= maximum:
            return {"type": "range", "min": minimum, "max": maximum}
    raise MetadataRestrictionError("CONDITION_CONFLICT", "Accumulated dependency conditions have no shared value.")


def supports_property_prerequisite_workflow(dependencies: Any) -> bool:
    """A disabled field may be acquired for the closed prerequisite planner."""
    activations = [item for item in dependencies if item.get("action") != "Show"]
    if not activations:
        return False
    for item in activations:
        if item.get("context") != "Self" or item.get("action") != "Enable":
            return False
        if item.get("type") == "override" and set(item) == {"type", "action", "context", "property"}:
            continue
        if item.get("type") == "reference" and set(item) == {"type", "action", "context", "property", "conditions"}:
            try:
                reference_presence_condition(item["conditions"])
            except MetadataRestrictionError:
                return False
            continue
        if item.get("type") != "property" or set(item) != {"type", "action", "context", "property", "conditions"}:
            return False
        try:
            condition_restriction(item["conditions"])
        except MetadataRestrictionError:
            return False
    return True


def reference_presence_condition(conditions: Any) -> bool:
    if (not isinstance(conditions, list) or len(conditions) != 1
            or not isinstance(conditions[0], Mapping) or set(conditions[0]) != {"referenceIsSet"}
            or type(conditions[0]["referenceIsSet"]) is not bool):
        raise MetadataRestrictionError("INVALID_METADATA", "Reference-presence condition requires one native Boolean referenceIsSet value.")
    return conditions[0]["referenceIsSet"]
