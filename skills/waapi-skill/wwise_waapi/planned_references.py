"""Bind declaration result handles to normalized graph occurrences, never guessed GUIDs."""
from __future__ import annotations

import re
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


def compile_result_reference(session, field, handle, *, native_type, allowed_types=None):
    rows = [row for row in session.declarations if row.result_handle == handle
        and isinstance(row.target, NewDescendantTarget)]
    if len(rows) != 1:
        raise business_repair("PLANNED_REFERENCE_TARGET_NOT_AVAILABLE", field=field.token,
            action="copy one new declaration result handle from this same Draft")
    target_type = native_type(session, rows[0].target.kind)
    allowed = field.restrictions.get("allowed_target_types", []) if allowed_types is None else allowed_types
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
        owned = node.get("rtpc", {}).get("control_input", {}).get("new_control_input")
        if owned is not None:
            bindings.append({"result_handle": result_handles[id(owned)], "request_path": path + ".control_input"})
        for ref in node.get("references", []):
            target = ref["target"]
            if isinstance(target, Mapping) and "new_control_input" in target:
                bindings.append({"result_handle": result_handles[id(target["new_control_input"])],
                    "request_path": path + ".owned_control_input"})
            if isinstance(target, Mapping) and target.get("kind") == "id" and str(target.get("value", "")).startswith("bnh1-"):
                targets.add(target["value"])
        for index, child in enumerate(node.get("children", [])):
            visit(child, f"{path}.children[{index}]")
        for index, descriptor in enumerate(node.get("lists", [])):
            for offset, child in enumerate(descriptor["objects"]):
                visit(child, f"{path}.lists[{index}].objects[{offset}]")
    for node, path in roots:
        visit(node, path)
    if not targets and not any("rtpc" in node for node, _ in roots):
        # Nested unnamed outcomes also require stable result bindings.
        def has_rtpc(node):
            return "rtpc" in node or node.get("anonymous") is True or any(isinstance(ref["target"], Mapping) and "new_control_input" in ref["target"] for ref in node.get("references", [])) or any(has_rtpc(child) for child in node.get("children", [])) or any(
                has_rtpc(child) for descriptor in node.get("lists", []) for child in descriptor["objects"])
        def has_duplicate_children(node):
            if "plugin" in node or "rtpc" in node or node.get("anonymous") is True:
                return False
            children = node.get("children", [])
            ordinary = [child for child in children if "plugin" not in child
                and "rtpc" not in child and child.get("anonymous") is not True]
            names = [child["name"].casefold() for child in ordinary]
            return len(names) != len(set(names)) or any(has_duplicate_children(child) for child in ordinary)
        if not any(has_rtpc(node) or has_duplicate_children(node) for node, _ in roots):
            return []
    if targets - {row["result_handle"] for row in bindings}:
        raise ValueError("Every planned reference target must belong to this compiled graph")
    return bindings


def prepare_result_context(bindings, nodes, roots, *, resolve_type, read, references=(), capture_collision=None):
    """Index normalized occurrences and observe paths; construct no native tree."""
    if not bindings:
        return None
    by_path = {node.request_path: node for node in nodes}
    handles, paths = {}, {}
    if len(nodes) > DEFAULT_MAX_NODES or len(bindings) != len(nodes):
        raise ObjectOperationContractError("PLANNED_REFERENCE_BINDING_INVALID", "Result bindings must cover the bounded normalized new graph")
    for binding in bindings:
        if (set(binding) != {"result_handle", "request_path"} or binding["request_path"] not in by_path
                or not isinstance(binding["result_handle"], str) or re.fullmatch(r"bnh1-[0-9a-f]{32}", binding["result_handle"]) is None
                or binding["result_handle"] in handles or binding["request_path"] in paths):
            raise ObjectOperationContractError("PLANNED_REFERENCE_BINDING_INVALID", "Each result handle binds one new graph occurrence")
        handles[binding["result_handle"]] = binding["request_path"]
        paths[binding["request_path"]] = binding["result_handle"]
    all_references = [reference for node in nodes for reference in node.references] + list(references)
    used = {reference.target.value for reference in all_references
        if getattr(reference.target, "kind", None) == "id" and str(reference.target.value).startswith("bnh1-")}
    if used - set(handles):
        raise ObjectOperationContractError("PLANNED_REFERENCE_BINDING_INVALID", "A scalar result target left this normalized graph")
    selected = {handles[handle] for handle in used}
    ancestors = set(selected)
    for path in tuple(selected):
        parent_path = by_path[path].parent_request_path
        while parent_path is not None:
            ancestors.add(parent_path)
            parent_path = by_path[parent_path].parent_request_path
    projection = ["id", "name", "type", "path", "classId", "parent", "owner", "notes"]
    facts, snapshots, names, renames, root_paths, root_names = {}, [], {}, [], {}, {}

    def observed(path):
        result = read("ak.wwise.core.object.get", {"from": {"path": [path]}}, {"return": projection})
        rows = result.get("return") if isinstance(result, Mapping) else None
        if (not isinstance(rows, list) or len(rows) > 1 or any(not isinstance(row, Mapping)
                or not isinstance(row.get("id"), str) or re.fullmatch(r"\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}", row["id"]) is None
                or not isinstance(row.get("path"), str) or row["path"].casefold() != path.casefold() for row in rows)):
            raise ObjectOperationContractError("AMBIGUOUS_IDENTITY", "A planned reference path needs at most one exact canonical collision")
        normalized = [{key: row[key] for key in projection if key in row} for row in rows]
        snapshots.append({"path": path, "fields": projection, "rows": normalized})
        return normalized

    def chosen_name(request_path, name, parent_path, policy, *, exclude_id=None, reserved=()):
        path = parent_path.rstrip("\\") + "\\" + name
        rows = observed(path)
        collisions = [row for row in rows if row["id"] != exclude_id]
        if policy != "rename" or not collisions:
            return name, path, rows
        if capture_collision is None:
            raise ObjectOperationContractError("PLANNED_REFERENCE_BINDING_INVALID", "Rename preservation requires the graph observer")
        renames.append({"request_path": request_path, "requested_name": name,
            "collision_state": [capture_collision(row) for row in collisions],
            "name_policy": "native_selected_name_bound_after_creation"})
        return name, path, rows

    def root_for(path):
        matches = [(prefix, value) for prefix, value in roots.items() if path == prefix or path.startswith(prefix + ".")]
        if len(matches) != 1:
            raise ObjectOperationContractError("PLANNED_REFERENCE_BINDING_INVALID", "A planned node needs one exact live root")
        return matches[0]

    def root_path(prefix, root):
        if prefix not in root_paths:
            current = root[0].row["path"]
            requested_name = root[2] if len(root) > 2 else None
            if requested_name is None:
                root_paths[prefix] = current
            else:
                path = current.rsplit("\\", 1)[0] + "\\" + requested_name
                collisions = [row for row in observed(path) if row['id'].casefold() != root[0].object.casefold()]
                if collisions:
                    raise ObjectOperationContractError("TARGET_EXISTS",
                        "Existing-object rename requires its exact requested name; child creation policy cannot rename this GUID.",
                        details={"path": path, "rows": collisions, "name_conflict_scope": "new_children_and_list_members"})
                root_paths[prefix] = path
        return root_paths[prefix]

    def resolve(path):
        if path in facts:
            return facts[path]
        node = by_path[path]
        prefix, root = root_for(path)
        if node.parent_request_path is not None:
            parent = resolve(node.parent_request_path)
            parent_native_path, parent_identity = parent["path"], parent["result_handle"]
        else:
            parent_native_path, parent_identity = root_path(prefix, root), root[0].object
        if node.rtpc is not None or node.anonymous or node.collection == "ControlInput" or (node.plugin is not None and node.plugin.kind == "effect" and node.plugin.placement == "owner"):
            if path in selected:
                raise ObjectOperationContractError("PLANNED_REFERENCE_TARGET_UNAVAILABLE", "Unnamed RTPC result has no source-proven native reference expression")
            info = resolve_type(node)
            fact = {"result_handle": paths[path], "request_path": path, "path": None, "name": node.name,
                "type": node.plugin.object_type if node.plugin is not None else info.name, "class_name": info.name,
                "class_id": info.class_id, "parent_identity": parent_identity,
                "relation": "owner", **({"rtpc_property": node.rtpc.property} if node.rtpc is not None else {})}
            facts[path] = fact
            return fact
        name, native_path, rows = node.name, parent_native_path.rstrip("\\") + "\\" + node.name, []
        if path in ancestors:
            reserved = {other.name.casefold() for other in nodes if other.request_path != path
                and other.parent_request_path == node.parent_request_path and root_for(other.request_path)[0] == prefix}
            name, native_path, rows = chosen_name(path, node.name, parent_native_path, root[1], reserved=reserved)
            if name != node.name:
                names[path] = name
            elif root[1] == "merge" and rows:
                native_path = rows[0]["path"]
                name = rows[0]["name"]
        info = resolve_type(node)
        fact = {"result_handle": paths[path], "request_path": path, "path": native_path, "name": name,
            "type": node.plugin.object_type if node.plugin is not None else info.name, "class_name": info.name,
            "class_id": info.class_id, "parent_identity": parent_identity,
            "relation": "parent" if node.collection == "children" else "owner"}
        facts[path] = fact
        return fact
    def ordinary_rename(path):
        node = by_path[path]
        return (root_for(path)[1][1] == "rename" and node.collection == "children"
            and node.plugin is None and node.rtpc is None and not node.anonymous)

    sibling_names = {}
    for path in paths:
        node = by_path[path]
        if node.collection == "children" and node.plugin is None and node.rtpc is None and not node.anonymous:
            key = (root_for(path)[0], node.parent_request_path, node.name.casefold())
            sibling_names.setdefault(key, []).append(path)
        resolve(path)
    duplicate_groups = [group for group in sibling_names.values() if len(group) > 1]
    if any(not all(ordinary_rename(path) for path in group) for group in duplicate_groups):
        raise ObjectOperationContractError("AMBIGUOUS_IDENTITY", "Duplicate planned siblings require ordinary rename occurrences")
    # A renamed ancestor also makes each descendant's prospective path opaque,
    # even when those descendant request names are distinct.
    ambiguous_paths = {path for path in paths if any(path == member or path.startswith(member + ".")
        for group in duplicate_groups for member in group)}
    prospective_paths = {}
    for path, fact in facts.items():
        if fact["path"] is not None:
            prospective_paths.setdefault(fact["path"].casefold(), []).append(path)
        if path in ambiguous_paths:
            fact["prospective_path_ambiguous"] = True
    if any(len(group) > 1 and not all(path in ambiguous_paths and ordinary_rename(path) for path in group)
            for group in prospective_paths.values()):
        raise ObjectOperationContractError("AMBIGUOUS_IDENTITY", "Planned reference paths must name distinct new occurrences outside ordinary rename groups")
    return {"handles": handles, "facts": facts, "target_paths": sorted(selected), "bound_paths": sorted(ancestors),
        "path_snapshots": snapshots, "prepared_names": names, "renames": renames, "root_paths": root_paths,
        "root_prepared_names": root_names, "metadata": [],
        "duplicate_sibling_groups": duplicate_groups, "ambiguous_paths": sorted(ambiguous_paths)}


def apply_result_name_choices(specs, context):
    if not context:
        return
    for spec in specs:
        path = spec["request_path"]
        name = context["prepared_names"].get(path, context["root_prepared_names"].get(path))
        if name is not None:
            spec["original_requested_name"] = spec["requested_name"]
            spec["requested_name"] = name
        if (path in context["bound_paths"] and not context["renames"]
                and path not in context.get("ambiguous_paths", [])):
            fact = context["facts"][path]
            if name is None and fact["name"] != spec["requested_name"]:
                spec["original_requested_name"] = spec["requested_name"]
                spec["requested_name"] = fact["name"]
            spec["expected_path"] = fact["path"]
        elif spec.get("existing_target") and path in context["root_paths"]:
            spec["expected_path"] = context["root_paths"][path]


def order_result_rows(rows, result_handles, *, revision):
    """Order existing compiled associations with the shared dependency kernel.

    Owned List member order and the compiled trees themselves stay intact.
    """
    owners, dependencies = {}, [set() for _ in rows]
    def descendants(node):
        yield node
        for child in node.get("children", []):
            yield from descendants(child)
        for descriptor in node.get("lists", []):
            for member in descriptor["objects"]:
                yield from descendants(member)
    for index, root in enumerate(rows):
        for node in descendants(root):
            handle = result_handles.get(id(node))
            if handle:
                owners[handle] = index
    for index, root in enumerate(rows):
        for node in descendants(root):
            for reference in node.get("references", []):
                target = reference["target"]
                owner = owners.get(target.get("value")) if isinstance(target, Mapping) else None
                if owner is not None and owner != index:
                    dependencies[index].add(owner)
    if not any(dependencies):
        return rows
    from .business_planning import BusinessEffect, _topological_order
    effects = [BusinessEffect(effect_id=f"row-{index}", declaration_id=f"row-{index}",
        depends_on=tuple(f"row-{dependency}" for dependency in sorted(dependencies[index])),
        batch_key="single-graph", native_fragment=root, verifier_expectation={}, readable_lines=("Reference targets before consumers",))
        for index, root in enumerate(rows)]
    return [effect.native_fragment for effect in _topological_order(effects, draft_revision=revision)]
