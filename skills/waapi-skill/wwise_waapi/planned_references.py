"""Bind declaration result handles to normalized graph occurrences, never guessed GUIDs."""
from __future__ import annotations

from typing import Mapping

from .business_declarations import NewDescendantTarget, business_repair
from .metadata_restrictions import reference_type_token
from .operation_object import DEFAULT_MAX_NODES, ObjectOperationContractError


class PlannedReferenceTarget:
    """Class/declaration facts only; this is deliberately not a live ResolvedObject."""
    def __init__(self, fact):
        self.object = fact["result_handle"]
        self.row = {"type": fact["type"], "path": fact["path"],
            fact["relation"]: {"id": fact["parent_identity"]}}
        self.resolution = "prospective-declaration-class-and-path"
        self.is_exact = False

    def as_dict(self):
        return {"planned_result_handle": self.object, "prospective": True, "facts": self.row}


def compile_result_reference(session, field, handle, *, native_type):
    rows = [row for row in session.declarations if row.result_handle == handle
        and isinstance(row.target, NewDescendantTarget)]
    if len(rows) != 1:
        raise business_repair("PLANNED_REFERENCE_TARGET_NOT_AVAILABLE", field=field.token,
            action="copy one new declaration result handle from this same Draft")
    target_type = native_type(session, rows[0].target.kind)
    allowed = field.restrictions.get("allowed_target_types", [])
    if allowed and reference_type_token(target_type) not in {reference_type_token(value) for value in allowed}:
        raise business_repair("REFERENCE_TARGET_TYPE_MISMATCH", field=field.token,
            allowed_target_types=allowed, action="choose a same-Draft result with one allowed class")
    # This is an internal binding placeholder, never a native identity. Registry
    # must consume it against graph_result_bindings before materializing a write.
    return {"kind": "id", "value": handle}


def graph_result_bindings(roots, result_handles):
    bindings, targets = [], set()
    def visit(node, path):
        handle = result_handles.get(id(node))
        if handle is not None:
            bindings.append({"result_handle": handle, "request_path": path})
        for ref in node.get("references", []):
            target = ref["target"]
            if isinstance(target, Mapping) and target.get("kind") == "id" and str(target.get("value", "")).startswith("bnh1-"):
                targets.add(target["value"])
        for index, child in enumerate(node.get("children", [])):
            visit(child, f"{path}.children[{index}]")
        for index, descriptor in enumerate(node.get("lists", [])):
            for offset, child in enumerate(descriptor["objects"]):
                visit(child, f"{path}.lists[{index}].objects[{offset}]")
    for node, path in roots:
        visit(node, path)
    if not targets:
        return []
    if targets - {row["result_handle"] for row in bindings}:
        raise ValueError("Every planned reference target must belong to this compiled graph")
    return bindings


def prepare_result_context(bindings, nodes, roots, *, resolve_type, read):
    """Observe existing roots and index normalized nodes; construct no native tree."""
    if not bindings:
        return None
    by_path = {node.request_path: node for node in nodes}
    handles, paths = {}, {}
    if len(nodes) > DEFAULT_MAX_NODES or len(bindings) != len(nodes):
        raise ObjectOperationContractError("PLANNED_REFERENCE_BINDING_INVALID", "Result bindings must cover the bounded normalized new graph", details={"bindings": bindings, "nodes": list(by_path)})
    for binding in bindings:
        if (set(binding) != {"result_handle", "request_path"} or binding["request_path"] not in by_path
                or not isinstance(binding["result_handle"], str) or not binding["result_handle"].startswith("bnh1-")
                or binding["result_handle"] in handles or binding["request_path"] in paths):
            raise ObjectOperationContractError("PLANNED_REFERENCE_BINDING_INVALID", "Each result handle binds exactly one new graph occurrence")
        handles[binding["result_handle"]] = binding["request_path"]
        paths[binding["request_path"]] = binding["result_handle"]
    used = {reference.target.value for node in nodes for reference in node.references
        if getattr(reference.target, "kind", None) == "id" and str(reference.target.value).startswith("bnh1-")}
    if used - set(handles):
        raise ObjectOperationContractError("PLANNED_REFERENCE_BINDING_INVALID", "A scalar result target left this normalized graph")
    facts = {}
    def resolve(path):
        if path in facts:
            return facts[path]
        node = by_path[path]
        parent_path = node.parent_request_path
        if parent_path is not None:
            parent = resolve(parent_path)
            parent_native_path, parent_identity = parent["path"], parent["result_handle"]
        else:
            matches = [value for prefix, value in roots.items() if path == prefix or path.startswith(prefix + ".")]
            if len(matches) != 1:
                raise ObjectOperationContractError("PLANNED_REFERENCE_BINDING_INVALID", "A planned node needs one exact live root")
            parent_native_path, parent_identity = matches[0][0].row["path"], matches[0][0].object
        info = resolve_type(node.type)
        fact = {"result_handle": paths[path], "request_path": path, "path": parent_native_path.rstrip("\\") + "\\" + node.name,
            "type": info.name, "class_id": info.class_id, "parent_identity": parent_identity,
            "relation": "parent" if node.collection == "children" else "owner"}
        facts[path] = fact
        return fact
    for path in paths:
        resolve(path)
    if len({row["path"].casefold() for row in facts.values()}) != len(facts):
        raise ObjectOperationContractError("AMBIGUOUS_IDENTITY", "Planned reference paths must name distinct new graph occurrences")
    selected = {handles[handle] for handle in used}
    ancestors = set(selected)
    for path in tuple(selected):
        parent_path = by_path[path].parent_request_path
        while parent_path is not None:
            ancestors.add(parent_path)
            parent_path = by_path[parent_path].parent_request_path
    snapshots = []
    for path in sorted(ancestors):
        fact = facts[path]
        result = read("ak.wwise.core.object.get", {"from": {"path": [fact["path"]]}},
            {"return": ["id", "name", "type", "path", "classId"]})
        rows = result.get("return") if isinstance(result, Mapping) else None
        if not isinstance(rows, list) or len(rows) > 1 or any(not isinstance(row, Mapping) for row in rows):
            raise ObjectOperationContractError("AMBIGUOUS_IDENTITY", "Each planned reference path must have at most one exact collision")
        root = next(value for prefix, value in roots.items() if path == prefix or path.startswith(prefix + "."))
        if root[1] == "rename" and rows:
            raise ObjectOperationContractError("PLANNED_REFERENCE_RENAME_COLLISION", "The same-call result reference needs a disclosed deterministic rename choice before its native path is known")
        snapshots.append({"path": fact["path"], "fields": ["id", "name", "type", "path", "classId"], "rows": rows})
    return {"handles": handles, "facts": facts, "target_paths": sorted(selected), "path_snapshots": snapshots, "metadata": []}
