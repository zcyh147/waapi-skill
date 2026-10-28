"""Source-owned WorkUnit and saved Query constructor boundaries.

Query criteria use the matching SDK's WWU procedure and shipped factory
criteria names. These sources establish construction input, not execution or
query-match evidence. Ordinary query-object reads do not use this module.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from .canonical import canonical_sha256
from .host_paths import localize_waapi_host_path, parse_relative_host_path

SOURCE = Path(__file__).resolve().parents[1] / "resources/metadata/saved-object-constructor-sources.json"
TYPES = {"WorkUnit": "workunit_class_id", "Query": "query_class_id", "SearchCriteria": "criterion_class_id"}
WORKUNIT_EFFECTS = ["undo_redo_history_cleared", "clipboard_cleared", "corresponding_WWU_saved_in_active_project"]


class SavedConstructorError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def authority(version, object_type):
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    if (data.get("contract") != "waapi-skill.saved-object-constructor-sources/v1"
            or data.get("sha256") != canonical_sha256({k: v for k, v in data.items() if k != "sha256"})):
        raise SavedConstructorError("SAVED_CONSTRUCTOR_SOURCE_DRIFT", "Saved object constructor sources changed.")
    lane = data["versions"][version]
    if object_type != "WorkUnit" and not lane["query_constructible"]:
        raise SavedConstructorError("QUERY_CONSTRUCTOR_UNAVAILABLE", "Matching SDK definitions prohibit saved Query construction in Wwise 2021.1/2022.1; ordinary query-object reads remain available.")
    return {"version": version, "object_type": object_type, "class_id": data[TYPES[object_type]],
        "source_sha256": data["sha256"], "sdk_member": lane["sdk_member"], "sdk_sha256": lane["sdk_sha256"],
        "build": lane["build"], **({"criteria": lane["criteria"], "factory_member": lane["factory_member"],
            "factory_sha256": lane["factory_sha256"]} if object_type == "SearchCriteria" else {})}


def criterion(version, choice):
    proof = authority(version, "SearchCriteria")
    if choice not in proof["criteria"]:
        raise SavedConstructorError("QUERY_CRITERION_CHOICE_REQUIRED", "Use a disclosed saved Query criterion choice as the declaration name; caller-authored SearchOperationID GUIDs are not accepted.")
    return {**proof, "choice": choice, "native_name": proof["criteria"][choice]}


def declaration_contract(version):
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    lane = data["versions"][version]
    return {"WorkUnit": {"status": "supported", "source_sha256": data["sha256"], "parent": "bound_WorkUnit_or_Folder_in_active_project",
            "name": "one_portable_filename_component_without_path_syntax",
            "name_conflict": ["fail", "rename", "merge"], "effects": WORKUNIT_EFFECTS,
            "io_scope": "every_exact_existing_owner_and_owning_WorkUnit_in_connected_ancestry_within_same_active_project; corresponding_WWU_destination_is_native_owned_not_synthesized",
            "same_batch_owner_rename": "all_SET_rows_checked_for_owner_owning_WorkUnit_or_proven_ancestor_overlap; separate_rename_Preview_then_bind_actual_existing_parent_for_WorkUnit_creation; unrelated_renames_remain_allowed",
            "verification": "GUID_class_parent_name_and_requested_fields; history_clipboard_and_saved_WWU_bytes_unobserved"},
        "Query": {"status": "supported" if lane["query_constructible"] else "unavailable_in_matching_SDK", "source_sha256": data["sha256"],
            "parent": "Queries_hierarchy_WorkUnit_or_Folder", "ordinary_query_object_reads": "unaffected",
            "criteria": {"kind": "selected_SearchCriteria_Type_Handle", "parent": "bound_or_planned_Query",
                "name": "copy_one_disclosed_criterion_choice; Gateway_owns_SearchOperationID_name",
                "choices": list(lane["criteria"]), "fields": "selected_live_class_Field_Handles",
                "verification": "GUID_class_Query_parent_and_requested_fields; SearchOperationID_and_query_matches_unobserved"}}}


def graph_boundary(nodes, *, parent, version, conflict, read):
    selected = [node for node in nodes if "saved_constructor" in node]
    if not selected:
        return None
    if any(node["canonical_type"] == "WorkUnit" for node in selected) and conflict == "replace":
        raise SavedConstructorError("WORKUNIT_REPLACE_UNSUPPORTED", "Matching SDK permits only fail, merge or rename for Work Unit construction.")
    if any(node["canonical_type"] == "SearchCriteria" for node in selected) and conflict != "fail":
        raise SavedConstructorError("QUERY_CRITERION_CONFLICT_BOUNDARY", "New source-selected criteria use fail mode; edit existing criteria through their bound field handles.")
    specs = {node["request_path"]: node for node in nodes}
    path = parent.row.get("path", "")
    for node in selected:
        kind = node["canonical_type"]
        if kind == "WorkUnit":
            try:
                name = parse_relative_host_path(node["requested_name"])
                if len(name.components) != 1:
                    raise ValueError("one filename component required")
            except ValueError as exc:
                raise SavedConstructorError("WORKUNIT_NAME_INVALID", "Work Unit name must be one portable filename component, without traversal or path syntax.") from exc
        owner = specs.get(node.get("parent_request_path"))
        owner_type = owner["canonical_type"] if owner else parent.row.get("type")
        if owner_type not in ({"Query"} if kind == "SearchCriteria" else {"WorkUnit", "Folder"}):
            raise SavedConstructorError("SAVED_CONSTRUCTOR_PARENT_INVALID", "Saved object construction requires its reviewed WorkUnit/Folder or exact Query owner.")
        if kind in {"Query", "SearchCriteria"} and not (path == "\\Queries" or path.startswith("\\Queries\\")):
            raise SavedConstructorError("QUERY_HIERARCHY_REQUIRED", "Saved Query construction requires a bound owner in the Queries hierarchy.")
    snapshots = []
    fields = ["id", "name", "type", "path", "classId", "parent", "filePath", "workunit", "workunitType"]
    owner_classes = {"WorkUnit": 1638416, "Folder": 131088, "Query": 2097168}
    captured = {}

    def capture(object_id, *, expected=None, kind=None):
        # Graph identities and canonical relationship GUIDs are already live
        # evidence, but malformed links must fail before another read.
        if not isinstance(object_id, str):
            raise ValueError("missing exact constructor owner GUID")
        UUID(object_id)
        if object_id not in captured:
            rows = read("ak.wwise.core.object.get", {"from": {"id": [object_id]}}, {"return": fields}).get("return")
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict) or rows[0].get("id") != object_id:
                raise ValueError("constructor owner must resolve exactly once")
            captured[object_id] = rows[0]
            snapshots.append({"object": object_id, "fields": fields, "rows": rows})
        row = captured[object_id]
        if (row.get("type") not in owner_classes or row.get("classId") != owner_classes[row["type"]]
                or kind is not None and row["type"] != kind
                or expected is not None and any(row.get(field) != expected[field]
                    for field in ("id", "name", "type", "path", "classId", "parent") if field in expected)):
            raise ValueError("constructor owner identity or class changed")
        return row

    try:
        root_owner = capture(parent.object, expected=parent.row)
    except (KeyError, TypeError, ValueError) as exc:
        raise SavedConstructorError("SAVED_CONSTRUCTOR_PARENT_INVALID", "Constructor owner requires its exact live class, name, type and path.") from exc
    project_root, project_snapshot, file_scope = None, None, None
    file_scopes, ancestry = [], []
    if any(node["canonical_type"] == "WorkUnit" for node in selected):
        project_snapshot = read("ak.wwise.core.object.get", {"waql": "from type Project take 1"}, {"return": ["id", "filePath"]}).get("return")
        try:
            if not isinstance(project_snapshot, list) or len(project_snapshot) != 1:
                raise ValueError("one active project required")
            project_id = project_snapshot[0]["id"]
            if not isinstance(project_id, str):
                raise ValueError("active project needs its exact GUID")
            UUID(project_id)
            project_file = project_snapshot[0]["filePath"]
            project_root = Path(localize_waapi_host_path(project_file)).resolve(strict=False).parent
            owners = {parent.object: root_owner}
            for node in selected:
                if node["canonical_type"] != "WorkUnit":
                    continue
                current, seen, chain = node, set(), []
                while current is not None:
                    request_path = current["request_path"]
                    if request_path in seen or len(seen) >= len(specs):
                        raise ValueError("ambiguous constructor ancestry")
                    seen.add(request_path)
                    kind = current["canonical_type"]
                    if kind not in {"WorkUnit", "Folder"}:
                        raise ValueError("constructor ancestry lacks a reviewed owner class")
                    identity = current.get("target_id") if current.get("existing_target") else current.get("preexisting_id")
                    if identity is not None:
                        if current.get("existing_target") and current.get("requested_name") != current.get("original_name"):
                            raise ValueError("owner rename requires a separate Preview before binding its new file context")
                        row = capture(identity, expected=current.get("pre_state"), kind=kind)
                        owners[identity] = row
                        chain.append({"request_path": request_path, "existing_owner": identity})
                    else:
                        # A new owner has no native file yet. Its only authority
                        # is this fresh exact class and connected owned ancestry.
                        name = parse_relative_host_path(current["requested_name"])
                        if (current.get("class_id") != owner_classes[kind] or current.get("collection") != "children"
                                or len(name.components) != 1 or kind == "WorkUnit" and not current.get("saved_constructor")):
                            raise ValueError("fresh constructor owner is not source/class certified")
                        chain.append({"request_path": request_path, "planned_class_id": current["class_id"]})
                    parent_path = current.get("parent_request_path")
                    if parent_path is None:
                        current = None
                    elif parent_path in specs:
                        current = specs[parent_path]
                    else:
                        raise ValueError("constructor ancestry has an unresolved owner")
                ancestry.append({"request_path": node["request_path"], "chain": chain, "bound_parent": parent.object})

            def retain_scope(row):
                raw = row["filePath"]
                local = Path(localize_waapi_host_path(raw)).resolve(strict=False)
                if local == project_root or not local.is_relative_to(project_root):
                    raise ValueError("constructor owner file scope outside active project")
                scope = {"object": row["id"], "project_file": project_file, "owner_file": raw,
                    "resolved_owner_file": str(local), "destination": "native_corresponding_WWU_path_not_synthesized"}
                if scope not in file_scopes:
                    file_scopes.append(scope)

            for row in owners.values():
                if row["type"] == "Folder":
                    link = row.get("workunit")
                    owner_id = link.get("id") if isinstance(link, dict) else None
                    owned = capture(owner_id, kind="WorkUnit")
                    # A supplied Folder filepath is also native file authority;
                    # it cannot escape merely because its workunit link is local.
                    if row.get("filePath"):
                        retain_scope(row)
                    row = owned
                if row["type"] != "WorkUnit" or row.get("workunitType") not in {"folder", "rootFile", "nestedFile"}:
                    raise ValueError("constructor owner needs its exact Work Unit file type")
                retain_scope(row)
            file_scope = file_scopes[0]
        except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
            raise SavedConstructorError("WORKUNIT_PROJECT_IO_BOUNDARY", "Every existing constructor owner and owning Work Unit must resolve inside the same active project; for an unresolved chain, bind the exact existing parent and prepare a direct WorkUnit Preview.") from exc
    return {"version": version, "sources": [node["saved_constructor"] for node in selected],
        "parent_snapshots": snapshots, "project_root": str(project_root) if project_root else None,
        "project_snapshot": project_snapshot, "file_scope": file_scope, "file_scopes": file_scopes, "owned_ancestry": ancestry,
        "workunit_effects": WORKUNIT_EFFECTS if project_root else [],
        "verification": {"observed": ["GUID_class_name_parent_and_requested_fields"],
            "unobserved": (["history_and_clipboard_contents", "WWU_file_bytes_and_save_completeness"] if project_root else [])
                + (["SearchOperationID", "saved_Query_matches"] if any(node["canonical_type"] == "SearchCriteria" for node in selected) else [])}}


def guard_matches(boundary, read):
    try:
        if boundary.get("file_scope"):
            projects = read("ak.wwise.core.object.get", {"waql": "from type Project take 1"}, {"return": ["id", "filePath"]}).get("return")
            if projects != boundary["project_snapshot"]:
                return False
            for scope in boundary["file_scopes"]:
                root = Path(localize_waapi_host_path(scope["project_file"])).resolve(strict=False).parent
                owner_file = Path(localize_waapi_host_path(scope["owner_file"])).resolve(strict=False)
                if str(root) != boundary["project_root"] or str(owner_file) != scope["resolved_owner_file"] or not owner_file.is_relative_to(root):
                    return False
        for proof in boundary["sources"]:
            current = criterion(proof["version"], proof["choice"]) if "choice" in proof else authority(proof["version"], proof["object_type"])
            if current != proof:
                return False
        return all(read("ak.wwise.core.object.get", {"from": {"id": [snapshot["object"]]}},
            {"return": snapshot["fields"]}).get("return") == snapshot["rows"] for snapshot in boundary["parent_snapshots"])
    except (SavedConstructorError, OSError, ValueError, KeyError, TypeError, RuntimeError):
        return False


def verification_scope(boundaries):
    observed = list(dict.fromkeys(item for boundary in boundaries for item in boundary["verification"]["observed"]))
    unobserved = list(dict.fromkeys(item for boundary in boundaries for item in boundary["verification"]["unobserved"]))
    return {"mode": "saved_object_identity_and_fields", "observed": observed, "unobserved": unobserved,
        "complete_business_verification": not unobserved}


def reject_batch_owner_renames(boundaries, specs, *, read):
    """Keep all SET name edits outside sealed constructor owner/path contexts.

    Identity overlap is exact. Ancestor overlap reuses the existing bounded
    GUID/path proof; it makes no assertion about native file relocation.
    """
    from .object_graph_paths import prepare_ancestor_path_guards
    renamed = [node for node in specs if node.get("existing_target") is True
        and node.get("requested_name") != node.get("original_name")]
    if not renamed:
        return
    protected = {row["id"].casefold(): row for boundary in boundaries if boundary.get("file_scopes")
        for snapshot in boundary["parent_snapshots"] for row in snapshot["rows"]}
    if not protected:
        return
    guards = {node["target_id"].casefold(): node["ancestor_rename_path_guard"] for node in specs
        if node.get("ancestor_rename_path_guard")}
    message = "A SET name edit overlaps a WorkUnit constructor owner or its proven ancestor. Prepare the rename separately, then bind the actual existing parent for a new WorkUnit Preview."
    unproved = "The SET name edit cannot be certified independent of a captured WorkUnit owner path. Prepare it separately, then bind the actual existing parent for a new WorkUnit Preview."
    for node in renamed:
        identity = node["target_id"].casefold()
        if identity in protected:
            raise SavedConstructorError("WORKUNIT_PROJECT_IO_BOUNDARY", message)
        for row in protected.values():
            old_path = node["pre_state"]["path"]
            if not isinstance(row.get("path"), str):
                raise SavedConstructorError("WORKUNIT_PROJECT_IO_BOUNDARY", unproved)
            if not row["path"].startswith(old_path + "\\"):
                continue
            # The full SET proof normally covers its constructor target. A
            # linked owning WorkUnit can be outside the SET targets; acquire
            # only that missing pair's ordinary bounded ancestry proof.
            guard = guards.get(row["id"].casefold())
            if guard is None:
                context = {"existing_target": True, "target_id": row["id"], "pre_state": row,
                    "requested_name": row["name"], "original_name": row["name"]}
                try:
                    prepare_ancestor_path_guards([node, context], read=read)
                except (ValueError, KeyError, TypeError) as exc:
                    raise SavedConstructorError("WORKUNIT_PROJECT_IO_BOUNDARY", unproved) from exc
                guard = context.get("ancestor_rename_path_guard")
            if not guard or identity not in {ancestor["id"].casefold() for ancestor in guard["ancestors"]}:
                raise SavedConstructorError("WORKUNIT_PROJECT_IO_BOUNDARY", unproved)
            raise SavedConstructorError("WORKUNIT_PROJECT_IO_BOUNDARY", message)
