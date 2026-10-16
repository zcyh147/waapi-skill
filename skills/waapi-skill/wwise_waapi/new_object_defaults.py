"""Reviewed new GameParameter conditions; live metadata remains authoritative.

Five-version native creation evidence establishes that Min/Max can be supplied
in the create call when their same-object built-in parameter condition is met.
Other classes and dependency grammars retain the object-scoped boundary.
"""
from __future__ import annotations

from typing import Any, Mapping

from .builders.metadata import GET_PROPERTY_INFO_URI, parse_get_property_info_result


class NewObjectDefaultError(ValueError):
    pass


def game_parameter_default_evidence(*, class_name, info, scope, read_call,
                                    supplied_values=None):
    if class_name != "GameParameter" or info.name not in {"Min", "Max"}:
        return None
    if not info.dependencies:
        return None
    allowed = None
    for dependency in info.dependencies:
        if (set(dependency) != {"type", "action", "property", "context", "conditions"}
                or dependency["type"] != "property" or dependency["action"] != "Enable"
                or dependency["context"] != "Self" or dependency["property"] != "BindToBuiltInParam"):
            return None
        conditions = dependency["conditions"]
        if (not isinstance(conditions, list) or len(conditions) != 1
                or not isinstance(conditions[0], Mapping) or set(conditions[0]) != {"restriction"}):
            return None
        restriction = conditions[0]["restriction"]
        if (not isinstance(restriction, Mapping) or set(restriction) != {"type", "values"}
                or restriction["type"] != "enum" or not isinstance(restriction["values"], list)
                or not 1 <= len(restriction["values"]) <= 16):
            return None
        values = []
        for row in restriction["values"]:
            if (not isinstance(row, Mapping) or set(row) - {"value", "displayName"}
                    or type(row.get("value")) is not int):
                return None
            values.append(row["value"])
        current = set(values)
        allowed = current if allowed is None else allowed & current
    dependency = parse_get_property_info_result(read_call(
        GET_PROPERTY_INFO_URI, {**scope, "property": "BindToBuiltInParam"}, {},
    ))
    if (dependency.name != "BindToBuiltInParam" or dependency.type.casefold() != "int16"
            or dependency.dependencies or type(dependency.default) is not int):
        return None
    value = (supplied_values or {}).get(dependency.name, dependency.default)
    if type(value) is not int or value not in allowed:
        raise NewObjectDefaultError(
            f"{info.name} requires a live-supported built-in parameter value; the declared value or live default is incompatible"
        )
    return {
        "class_scope": dict(scope),
        "field": info.name,
        "dependency": dependency.name,
        "allowed_values": sorted(allowed),
        "live_default": dependency.default,
        "effective_value": value,
        "metadata": {info.name: info.as_dict(), dependency.name: dependency.as_dict()},
    }
