"""Source-backed existing-reference applicability for fields and transactions.

Structural Show conditions and explicit Master Sink target denials stay distinct.
Neither reports native property-enabled state, changes topology, or supplies defaults.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re

from .builders.metadata import parse_get_types_result
from .canonical import canonical_sha256
from .metadata_restrictions import is_master_bus_visibility_dependency
from .operation_object import DEFAULT_MAX_DEPTH

_SOURCE = Path(__file__).resolve().parents[1] / "resources/metadata/reference-master-bus-applicability.json"
_SINK_SOURCE = _SOURCE.with_name("reference-master-sink-capabilities.json")
_GUID = re.compile(r"\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}")
_FIELDS = ("id", "name", "type", "path", "classId", "parent")


def is_reference(info):
    restriction = info.get("restriction", {}) if isinstance(info, dict) else info.restriction
    kind = info.get("type") if isinstance(info, dict) else info.type
    return restriction.get("type") == "reference" or str(kind).casefold() in {"reference", "objectreference"}


def needs_structural_proof(info):
    return is_reference(info) and any(is_master_bus_visibility_dependency(item) and item["value"] is True
        for item in info.dependencies)


def _source(version):
    raw = _SOURCE.read_bytes()
    if len(raw) > 65536:
        raise ValueError("Structural applicability source exceeds its fixed bound")
    source = json.loads(raw)
    if (source.get("contract") != "waapi-skill.reference-master-bus-source/v1"
            or canonical_sha256({key: value for key, value in source.items() if key != "sha256"}) != source.get("sha256")):
        raise ValueError("Structural applicability source seal is invalid")
    lane = source["versions"].get(version)
    if lane is None:
        raise ValueError("No matching topmost-Bus reference condition source for this version")
    catalog_bytes = (_SOURCE.parent / version / "object-types.json").read_bytes()
    if hashlib.sha256(catalog_bytes).hexdigest() != lane["types_sha256"]:
        raise ValueError("Structural applicability class source has changed")
    catalog = json.loads(catalog_bytes)["types"]
    if any(len([row for row in catalog if row["name"] == kind and row["classId"] == class_id]) != 1
            for kind, class_id in source["classes"].items()):
        raise ValueError("Structural applicability classes contradict the matching catalog")
    return source, lane


def _row(read, identity):
    if not isinstance(identity, str) or not _GUID.fullmatch(identity):
        raise ValueError("Structural applicability requires canonical exact parent GUIDs")
    result = read("ak.wwise.core.object.get", {"from": {"id": [identity]}}, {"return": list(_FIELDS)})
    rows = result.get("return") if isinstance(result, dict) else None
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or not isinstance(rows[0].get("id"), str) or rows[0]["id"].casefold() != identity.casefold()):
        raise ValueError("Structural ancestry must resolve each exact GUID once")
    return {key: rows[0][key] for key in _FIELDS if key in rows[0]}


def prove(*, version, object_id, info, read, platform=None):
    if not needs_structural_proof(info):
        return None
    source, lane = _source(version)
    root_path = lane["hierarchy_path"]
    catalog = parse_get_types_result(read("ak.wwise.core.object.getTypes", {}, {}))
    rows, classes, seen = [], {}, set()
    identity = object_id
    for _ in range(DEFAULT_MAX_DEPTH + 1):
        if not isinstance(identity, str) or identity.casefold() in seen:
            raise ValueError("Structural ancestry must be finite and acyclic")
        seen.add(identity.casefold())
        row = _row(read, identity)
        if not isinstance(row.get("name"), str) or not row["name"] or not isinstance(row.get("path"), str):
            raise ValueError("Structural ancestry needs actual names and paths")
        if rows and rows[-1]["path"] != row["path"] + "\\" + rows[-1]["name"]:
            raise ValueError("Structural parent GUID edge contradicts actual paths")
        rows.append(row)
        if row["path"] == root_path:
            # The canonical hierarchy boundary is read by the actual parent GUID.
            # It is not a mutation target and needs no invented native root class.
            if len(rows) < 2 or row["name"] != root_path[1:]:
                raise ValueError("Structural ancestry has an invalid Bus hierarchy boundary")
            return {"kind": "structural-reference-visibility", "version": version, "object_id": object_id,
                "field": info.name, "platform": platform, "native_enabled_state": "not_queried",
                "condition": {"type": "isMasterBus", "value": True, "action": "Show", "context": "Self"},
                "metadata": info.as_dict(), "source_sha256": source["sha256"], "rows": rows,
                "classes": [classes[key] for key in sorted(classes)]}
        expected_types = {"Bus"} if len(rows) == 1 else {"WorkUnit", "Folder"}
        kind = row.get("type")
        class_id = row.get("classId")
        if (kind not in expected_types or type(class_id) is not int
                or class_id != source["classes"].get(kind)
                or len([item for item in catalog if item.name == kind and item.class_id == class_id]) != 1
                or any(item.name == kind and item.class_id != class_id for item in catalog)
                or any(item.class_id == class_id and item.name != kind for item in catalog)
                or not row["path"].startswith(root_path + "\\")):
            raise ValueError("Reference visibility requires a topmost Bus with source-proven WorkUnit/Folder ancestry")
        classes[kind] = {"name": kind, "class_id": class_id}
        parent = row.get("parent")
        if not isinstance(parent, dict) or ("name" in parent and not isinstance(parent["name"], str)):
            raise ValueError("Structural ancestry requires an actual canonical parent edge")
        identity = parent.get("id")
    raise ValueError("Structural ancestry exceeds the fixed graph depth bound")


def proof_current(proof, *, read, info, after_write=False, edits=()):
    from .operation_registry import _native_snapshot_equal
    expected = dict(proof)
    if after_write and edits:
        from .object_graph_paths import expected_snapshot
        expected["rows"] = [expected_snapshot(row, edits=edits, read_row=lambda identity: _row(read, identity))
            for row in proof["rows"]]
    observed = prove(version=proof["version"], object_id=proof["object_id"], info=info,
        read=read, platform=proof["platform"])
    return _native_snapshot_equal(observed, expected)


def master_sink_target(*, version, source_id, target_id, info, read):
    """Bind the explicit target denial to an existing Bus/reference and live class.

    Unspecified capabilities do not become false or true. The installed SDK is
    provenance only; runtime uses this sealed resource and fresh WAAPI facts.
    """
    if source_id is None or info.name != "AudioDevice" or not is_reference(info):
        return None
    owner = _row(read, source_id)
    if owner.get("type") != "Bus":
        return None
    raw = _SINK_SOURCE.read_bytes()
    if len(raw) > 65536:
        raise ValueError("Master Sink capability source exceeds its fixed bound")
    source = json.loads(raw)
    if (source.get("contract") != "waapi-skill.reference-master-sink-capabilities/v1"
            or canonical_sha256({key: value for key, value in source.items() if key != "sha256"}) != source.get("sha256")):
        raise ValueError("Master Sink capability source seal is invalid")
    lane = source["versions"].get(version)
    if lane is None:
        raise ValueError("No matching Master Sink target capability source for this version")
    catalog_bytes = (_SOURCE.parent / version / "object-types.json").read_bytes()
    if hashlib.sha256(catalog_bytes).hexdigest() != lane["types_sha256"]:
        raise ValueError("Master Sink capability class source has changed")
    denied_class = source["target_class"]
    catalog = json.loads(catalog_bytes)["types"]
    owner_class = source["source_role"]["classId"]
    if (catalog.count(denied_class) != 1 or type(owner.get("classId")) is not int
            or owner["classId"] != owner_class
            or len([item for item in catalog if item.get("name") == "Bus" and item.get("classId") == owner_class]) != 1):
        raise ValueError("Master Sink capability classes contradict matching source")
    target = _row(read, target_id)
    class_id = target.get("classId")
    live = parse_get_types_result(read("ak.wwise.core.object.getTypes", {}, {}))
    matches = [item for item in live if item.class_id == class_id]
    if (type(class_id) is not int or target.get("type") != "AudioDevice"
            or len(matches) != 1 or matches[0].type != "AudioDevice"
            or not isinstance(matches[0].name, str) or not matches[0].name
            or len([item for item in live if item.name == matches[0].name]) != 1):
        raise ValueError("Master Sink target requires one fresh installed AudioDevice class")
    actual_class = matches[0].as_dict()
    known = class_id == denied_class["classId"] or actual_class["name"] == denied_class["name"]
    if known and actual_class != denied_class:
        raise ValueError("Installed Master Sink target class contradicts matching capability source")
    return {"kind": "master_sink_target", "version": version, "source_id": source_id,
        "target_id": target_id, "reference": info.name, "source_class_id": owner["classId"],
        "class": actual_class, "source_sha256": source["sha256"],
        "CanBeMasterSink": source["capability"]["CanBeMasterSink"] if known else "unspecified"}
