"""Source-owned WorkUnit and saved Query constructor boundaries.

Query criteria use the matching SDK's WWU procedure and shipped factory
criteria names. These sources establish construction input, not execution or
query-match evidence. Ordinary query-object reads do not use this module.
"""
from __future__ import annotations

import json
from pathlib import Path

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
            "io_scope": "exact_native_owner_file_or_directory_within_active_project; corresponding_WWU_destination_is_native_owned_not_synthesized",
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
    fields = ["id", "name", "type", "path", "classId", "filePath", "workunit", "workunitType"]
    rows = read("ak.wwise.core.object.get", {"from": {"id": [parent.object]}}, {"return": fields}).get("return")
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("id") != parent.object:
        raise SavedConstructorError("SAVED_CONSTRUCTOR_PARENT_INVALID", "Constructor owner must resolve exactly once.")
    expected_class = {"WorkUnit": 1638416, "Folder": 131088, "Query": 2097168}.get(parent.row.get("type"))
    if (rows[0].get("classId") != expected_class
            or any(rows[0].get(field) != parent.row.get(field) for field in ("id", "name", "type", "path"))):
        raise SavedConstructorError("SAVED_CONSTRUCTOR_PARENT_INVALID", "Constructor owner requires its exact live class, name, type and path.")
    snapshots.append({"object": parent.object, "fields": fields, "rows": rows})
    # The existing project guard remains authoritative. WorkUnit writes add a
    # native file-scope check, without inventing a destination WWU filename.
    project_root = None
    file_scope = None
    if any(node["canonical_type"] == "WorkUnit" for node in selected):
        projects = read("ak.wwise.core.object.get", {"waql": "from type Project take 1"}, {"return": ["id", "filePath"]}).get("return")
        try:
            if not isinstance(projects, list) or len(projects) != 1:
                raise ValueError("one active project required")
            project_file = projects[0]["filePath"]
            project_root = Path(localize_waapi_host_path(project_file)).resolve(strict=False).parent
            container = rows[0]
            if container.get("type") == "Folder":
                owner_id = container.get("workunit", {}).get("id")
                owned = read("ak.wwise.core.object.get", {"from": {"id": [owner_id]}}, {"return": fields}).get("return")
                if not isinstance(owned, list) or len(owned) != 1 or owned[0].get("id") != owner_id:
                    raise ValueError("Folder needs exact owning Work Unit")
                snapshots.append({"object": owner_id, "fields": fields, "rows": owned})
                container = owned[0]
            local = Path(localize_waapi_host_path(container["filePath"])).resolve(strict=False)
            if (container.get("type") != "WorkUnit" or container.get("classId") != 1638416
                    or container.get("workunitType") not in {"folder", "rootFile", "nestedFile"}
                    or local == project_root or not local.is_relative_to(project_root)):
                raise ValueError("Work Unit file scope outside active project")
            file_scope = {"project_file": project_file, "owner_file": container["filePath"], "resolved_owner_file": str(local),
                "destination": "native_corresponding_WWU_path_not_synthesized"}
        except (KeyError, TypeError, ValueError) as exc:
            raise SavedConstructorError("WORKUNIT_PROJECT_IO_BOUNDARY", "Work Unit creation requires an exact native owning Work Unit file/directory inside the active project.") from exc
    return {"version": version, "sources": [node["saved_constructor"] for node in selected],
        "parent_snapshots": snapshots, "project_root": str(project_root) if project_root else None, "file_scope": file_scope,
        "workunit_effects": WORKUNIT_EFFECTS if project_root else [],
        "verification": {"observed": ["GUID_class_name_parent_and_requested_fields"],
            "unobserved": (["history_and_clipboard_contents", "WWU_file_bytes_and_save_completeness"] if project_root else [])
                + (["SearchOperationID", "saved_Query_matches"] if any(node["canonical_type"] == "SearchCriteria" for node in selected) else [])}}


def guard_matches(boundary, read):
    try:
        if boundary.get("file_scope"):
            scope = boundary["file_scope"]
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
    except (SavedConstructorError, OSError, ValueError, KeyError, TypeError):
        return False


def verification_scope(boundaries):
    observed = list(dict.fromkeys(item for boundary in boundaries for item in boundary["verification"]["observed"]))
    unobserved = list(dict.fromkeys(item for boundary in boundaries for item in boundary["verification"]["unobserved"]))
    return {"mode": "saved_object_identity_and_fields", "observed": observed, "unobserved": unobserved,
        "complete_business_verification": not unobserved}
