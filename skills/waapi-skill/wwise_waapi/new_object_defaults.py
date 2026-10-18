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
    reference_presence_condition, is_master_bus_visibility_dependency,
)


class NewObjectDefaultError(ValueError):
    def __init__(self, message, *, error_code="NEW_OBJECT_DEPENDENCY_UNSUPPORTED", details=None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def class_default_evidence(*, infos, scope, read_call, supplied_values=None,
                           supplied_references=None, planned_references=None, discovery=False, validate_scalar=None,
                           structural_bus_proof=None, version=None):
    """Collect the complete graph, then evaluate combined prerequisites.

    Discovery certifies grammar and seals metadata without choosing missing
    user values. Preparation evaluates the complete declaration atomically.
    """
    from .condition_limits import MAX_CONDITION_CONTROLLERS, MAX_CONDITION_PATH_FIELDS

    metadata = {info.name: info for info in infos}
    supplied = supplied_values or {}
    references = supplied_references or {}
    planned = planned_references or {}
    restrictions, presences = {}, {}
    visited, controllers, override_controllers = set(), set(), set()
    derived_properties = {}
    structural_visibility = []
    override_applicability = []

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
            if is_master_bus_visibility_dependency(dependency) and dependency["value"] is False:
                if not discovery and structural_bus_proof is None:
                    raise NewObjectDefaultError("Non-master bus visibility requires a proved new Bus/AuxBus child below a Bus/AuxBus parent.")
                structural_visibility.append({"field": name, "dependency": dict(dependency), "proof": structural_bus_proof})
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
            if kind == "override" and (structural_bus_proof is not None or version is not None):
                from .override_applicability import prove_absent_override
                try:
                    proof = prove_absent_override(version=structural_bus_proof["version"] if structural_bus_proof else version, class_id=scope.get("classId"),
                        info=info, dependency=dependency, read=read_call, structural_proof=structural_bus_proof, discovery=discovery)
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    raise NewObjectDefaultError(str(exc), error_code="OVERRIDE_APPLICABILITY_INVALID") from exc
                if proof is not None:
                    if controller in supplied:
                        raise NewObjectDefaultError("An absent class controller cannot be supplied as a property.", error_code="NEW_OBJECT_DEPENDENCY_CONFLICT")
                    override_applicability.append(proof)
                    continue
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
            if name in planned:
                binding = planned[name]
                if (set(binding) != {"result_handle", "target_request_path"}
                        or not isinstance(binding["result_handle"], str)
                        or re.fullmatch(r"bnh1-[0-9a-f]{32}", binding["result_handle"]) is None
                        or not isinstance(binding["target_request_path"], str) or not binding["target_request_path"].startswith("$")):
                    raise NewObjectDefaultError("A planned prerequisite needs its exact graph result binding.", error_code="INVALID_METADATA")
                value = {"planned_result_handle": binding["result_handle"], "target_request_path": binding["target_request_path"]}
                resolved = True
            else:
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
                                 "source": "planned_declaration" if name in planned else "explicit" if name in references else "class_default"})
    except MetadataRestrictionError as exc:
        raise NewObjectDefaultError(str(exc), error_code=("NEW_OBJECT_DEPENDENCY_CONFLICT" if exc.error_code == "CONDITION_CONFLICT" else exc.error_code)) from exc
    return {"class_scope": dict(scope), "requirements": requirements, "derived_properties": derived_properties,
            "default_presence": {name: "default" in info.raw for name, info in metadata.items()},
            "metadata": {name: info.as_dict() for name, info in metadata.items()},
            **({"structural_visibility": structural_visibility} if structural_visibility else {}),
            **({"override_applicability": override_applicability} if override_applicability else {})}


def planned_non_master_bus_proof(*, version, node, info, nodes, resolve_type, root_parent, read, root_collection="children"):
    """Prove normal Bus/AuxBus child placement from pinned classes and this graph."""
    from .documented_list_fields import load_catalog, scope_evidence
    if node.collection != "children" or info.name not in {"Bus", "AuxBus"}:
        return None
    catalog = load_catalog(version)
    classes = {row["name"]: row for row in catalog["classes"] if row["name"] in {"Bus", "AuxBus"}}
    if info.name not in classes or info.class_id != classes[info.name]["class_id"]:
        return None
    if node.parent_request_path is not None:
        parent_node = next((item for item in nodes if item.request_path == node.parent_request_path), None)
        if parent_node is None:
            return None
        ancestor = parent_node
        while ancestor is not None:
            if ancestor.collection != "children" or (ancestor.parent_request_path is None and root_collection != "children"):
                return None
            ancestor = next((item for item in nodes if item.request_path == ancestor.parent_request_path), None)
        parent_info = resolve_type(parent_node.type)
        if parent_info.name not in classes or parent_info.class_id != classes[parent_info.name]["class_id"]:
            return None
        parent = {"request_path": parent_node.request_path, "type": parent_info.name, "class_id": parent_info.class_id}
    else:
        if root_collection != "children" or root_parent is None or root_parent.row.get("type") not in classes:
            return None
        _catalog, parent_class, scope = scope_evidence(version, scope_kind="object", scope_value=root_parent.object, read=read)
        if (parent_class is None or parent_class["name"] not in classes
                or scope["owner"] != {key: root_parent.row[key] for key in ("id", "name", "type", "path")}):
            return None
        parent = {"object_id": root_parent.object, "identity": scope["owner"],
            "type": parent_class["name"], "class_id": parent_class["class_id"]}
    return {"version": version, "catalog_sha256": catalog["catalog_sha256"],
        "request_path": node.request_path, "type": info.name, "class_id": info.class_id,
        "relation": "children", "parent": parent}


def structural_bus_proof_current(proof, *, read, after_write=False):
    """Recheck source/type bindings and any existing parent without replaying a write."""
    from .documented_list_fields import load_catalog, scope_evidence
    from .builders.metadata import GET_TYPES_URI, parse_get_types_result
    catalog = load_catalog(proof["version"])
    types = parse_get_types_result(read(GET_TYPES_URI, {}, {}))
    parent = proof["parent"]
    passed = catalog["catalog_sha256"] == proof["catalog_sha256"] and all(
        [row.class_id for row in types if row.name.casefold() == item["type"].casefold()] == [item["class_id"]]
        for item in (proof, parent))
    if "object_id" in parent:
        _catalog, parent_class, scope = scope_evidence(proof["version"], scope_kind="object", scope_value=parent["object_id"], read=read)
        identity = scope["owner"]
        passed = passed and parent_class is not None and parent_class["class_id"] == parent["class_id"]
        passed = passed and (all(identity[key] == parent["identity"][key] for key in ("id", "type"))
            if after_write else identity == parent["identity"])
    return bool(passed)
