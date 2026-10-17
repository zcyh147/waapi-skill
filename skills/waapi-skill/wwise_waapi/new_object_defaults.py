"""Bounded class-scoped condition plans for genuinely new objects.

Only live class metadata supplies defaults. Missing or incompatible defaults
require explicit business intent; class metadata never certifies an existing
object's state. Native effect evidence remains separate from this compiler.
"""
from __future__ import annotations

import re
from typing import Mapping

from .builders.metadata import GET_PROPERTY_INFO_URI, parse_get_property_info_result
from .metadata_restrictions import (
    MetadataRestrictionError, condition_matches, condition_restriction,
    intersect_condition_restrictions, is_terminal_override_dependency,
    reference_presence_condition,
)


class NewObjectDefaultError(ValueError):
    def __init__(self, message, *, error_code="NEW_OBJECT_DEPENDENCY_UNSUPPORTED", details=None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def class_default_evidence(*, infos, scope, read_call, supplied_values=None,
                           supplied_references=None, discovery=False, validate_scalar=None):
    """Collect the complete graph, then evaluate combined prerequisites.

    Discovery certifies grammar and seals metadata without choosing missing
    user values. Preparation evaluates the complete declaration atomically.
    """
    from .condition_limits import MAX_CONDITION_CONTROLLERS, MAX_CONDITION_PATH_FIELDS

    metadata = {info.name: info for info in infos}
    supplied = supplied_values or {}
    references = supplied_references or {}
    restrictions, presences = {}, {}
    visited, controllers, override_controllers = set(), set(), set()
    derived_properties = {}

    def visit(info, path):
        name = info.name
        if name in path:
            raise NewObjectDefaultError("Class conditions contain a cycle.", error_code="REFERENCE_DEPENDENCY_CYCLE")
        if name in visited:
            return
        if len(path) >= MAX_CONDITION_PATH_FIELDS:
            raise NewObjectDefaultError("Class condition path exceeds the bounded field budget.", error_code="REFERENCE_DEPENDENCY_LIMIT")
        for dependency in info.dependencies:
            if is_terminal_override_dependency(name, info.type, dependency):
                continue
            kind, action, context = (dependency.get(key) for key in ("type", "action", "context"))
            fields = {"type", "action", "context", "property"}
            if kind in {"property", "reference"}:
                fields.add("conditions")
            controller = dependency.get("property")
            if (kind not in {"property", "override", "reference"} or set(dependency) != fields
                    or action not in {"Enable", "Show"} or context not in {"Self", "Parent", "AssocParent"}
                    or not isinstance(controller, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", controller) is None):
                raise NewObjectDefaultError("Class condition needs object-scoped metadata or an unimplemented native grammar.")
            if kind == "reference":
                requirement = reference_presence_condition(dependency["conditions"])
            elif kind == "property":
                requirement = condition_restriction(dependency["conditions"])
            else:
                requirement = {"type": "enum", "values": [{"value": True}]}
            if action == "Show":
                continue
            if context != "Self":
                raise NewObjectDefaultError("Related-object conditions require verified object-scoped configuration.")
            controllers.add(controller)
            if len(controllers) > MAX_CONDITION_CONTROLLERS:
                raise NewObjectDefaultError("Class conditions exceed the bounded controller budget.", error_code="REFERENCE_DEPENDENCY_LIMIT")
            child = metadata.get(controller)
            if child is None:
                child = parse_get_property_info_result(read_call(GET_PROPERTY_INFO_URI, {**scope, "property": controller}, {}))
                if child.name != controller:
                    raise NewObjectDefaultError("Class controller metadata names a different field.", error_code="INVALID_METADATA")
                metadata[controller] = child
            reference_type = child.type and child.type.casefold() in {"reference", "objectreference"}
            if kind == "reference":
                if not reference_type and child.restriction.get("type") != "reference":
                    raise NewObjectDefaultError("Reference condition controller is not a reference.", error_code="INVALID_METADATA")
                presences.setdefault(controller, set()).add(requirement)
            else:
                if reference_type or (kind == "override" and (child.type or "").casefold() not in {"bool", "boolean"}):
                    raise NewObjectDefaultError("Scalar condition controller metadata has an incompatible type.", error_code="INVALID_METADATA")
                restrictions.setdefault(controller, []).append(requirement)
                if kind == "override":
                    override_controllers.add(controller)
            visit(child, (*path, name))
        visited.add(name)

    try:
        for info in tuple(metadata.values()):
            visit(info, ())
        requirements = []
        for name, rows in restrictions.items():
            restriction = intersect_condition_restrictions(rows)
            info = metadata[name]
            value = supplied.get(name, info.default)
            resolved = name in supplied or "default" in info.raw
            matches = resolved and condition_matches(restriction, value)
            if not discovery and not matches and name in override_controllers and name not in supplied:
                value = True
                matches = condition_matches(restriction, value)
                if matches:
                    derived_properties[name] = value
            if not discovery and not matches:
                raise NewObjectDefaultError(
                    "Declare a compatible prerequisite value before creating this object.",
                    error_code="NEW_OBJECT_DEPENDENCY_CONFLICT" if name in supplied else "REFERENCE_ACTIVATION_REQUIRED",
                    details={"property": name, "restriction": restriction, "mutation_dispatched": False},
                )
            if not discovery and validate_scalar is not None:
                validate_scalar(info, value)
            requirements.append({"name": name, "kind": "property", "restriction": restriction,
                                 "effective_value": value, "value_resolved": bool(matches),
                                 "source": "explicit" if name in supplied else "derived" if name in derived_properties else "class_default"})
        for name, states in presences.items():
            if len(states) != 1:
                raise NewObjectDefaultError("Class reference-presence conditions conflict.", error_code="NEW_OBJECT_DEPENDENCY_CONFLICT")
            info = metadata[name]
            value = references.get(name, info.default)
            resolved = name in references or "default" in info.raw
            if isinstance(value, Mapping):
                if ("id" not in value or set(value) - {"id", "name", "type", "path"}
                        or any(not isinstance(item, str) for item in value.values())):
                    raise NewObjectDefaultError("Reference class default has an unimplemented native shape.", error_code="INVALID_METADATA")
                value = value["id"]
            if value is not None and (not isinstance(value, str) or re.fullmatch(
                    r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}", value) is None):
                raise NewObjectDefaultError("Reference class default must be a canonical GUID or native null.", error_code="INVALID_METADATA")
            if isinstance(value, str):
                value = value.upper()
            if value == "{00000000-0000-0000-0000-000000000000}":
                value = None
            present = value is not None
            required = next(iter(states))
            if not discovery and (not resolved or present != required):
                raise NewObjectDefaultError("Choose an explicit reference prerequisite or configure the verified created object separately.",
                    error_code="REFERENCE_ACTIVATION_REQUIRED", details={"property": name, "required_presence": required, "mutation_dispatched": False})
            requirements.append({"name": name, "kind": "reference", "required_presence": required,
                                 "effective_value": value, "value_resolved": resolved,
                                 "source": "explicit" if name in references else "class_default"})
    except MetadataRestrictionError as exc:
        raise NewObjectDefaultError(str(exc), error_code=("NEW_OBJECT_DEPENDENCY_CONFLICT" if exc.error_code == "CONDITION_CONFLICT" else exc.error_code)) from exc
    return {"class_scope": dict(scope), "requirements": requirements, "derived_properties": derived_properties,
            "default_presence": {name: "default" in info.raw for name, info in metadata.items()},
            "metadata": {name: info.as_dict() for name, info in metadata.items()}}
