"""Pinned field-kind evidence, separate from native restrictions and values.

An omitted native kind is not general permission to treat a token as a
reference. Only an exact documented class/field and fresh object identity can
use this proof. It supplies no target-domain or activation semantics.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re

from .canonical import canonical_sha256

_SOURCE = Path(__file__).resolve().parents[1] / "resources/metadata/reference-kind-sources.json"
_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")


def certify(info, *, version, object_id, read):
    """Attach source authority without changing any native metadata member."""
    if info.name != "Target" or info.type not in (None, "") or info.restriction.get("type") == "reference":
        return info
    # A restriction describing a scalar contradicts this source, rather than
    # becoming an empty native reference restriction through normalization.
    if info.restriction and info.restriction.get("type") != "reference":
        return info
    source = json.loads(_SOURCE.read_text(encoding="utf-8"))
    if (source.get("contract") != "waapi-skill.reference-kind-source/v1"
            or canonical_sha256({k: v for k, v in source.items() if k != "sha256"}) != source.get("sha256")):
        raise ValueError("Reference-kind source seal changed")
    lane = source["versions"].get(version)
    if lane is None:
        return info
    catalog_bytes = (_SOURCE.parent / version / "object-types.json").read_bytes()
    if hashlib.sha256(catalog_bytes).hexdigest() != lane["types_sha256"]:
        raise ValueError("Reference-kind class source changed")
    if not isinstance(object_id, str) or not _GUID.fullmatch(object_id):
        return info
    from .builders.metadata import parse_property_and_reference_names_result
    names = parse_property_and_reference_names_result(read(
        "ak.wwise.core.object.getPropertyAndReferenceNames", {"object": object_id}, {}))
    if [item.name for item in names].count(info.name) != 1:
        return info
    result = read("ak.wwise.core.object.get", {"from": {"id": [object_id]}},
        {"return": ["id", "type", "classId", "ActionType"]})
    rows = result.get("return") if isinstance(result, dict) else None
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or not isinstance(rows[0].get("id"), str) or rows[0]["id"].casefold() != object_id.casefold()):
        return info
    row = rows[0]
    catalog = json.loads(catalog_bytes)["types"]
    matches = [field for field in source["fields"]
        if field["field"] == info.name and field["native_type"] == row.get("type")
        and type(row.get("classId")) is int and field["class_id"] == row["classId"]]
    if len(matches) != 1 or type(row.get("ActionType")) is not int:
        return info
    selected = matches[0]
    if len([item for item in catalog if item["name"] == selected["native_type"]
            and item["classId"] == selected["class_id"]]) != 1:
        raise ValueError("Reference-kind class contradicts its pinned catalog")
    proof = {"kind": "documented-reference-kind", "version": version, "object_id": object_id,
        "field": info.name, "value_kind": "reference", "source_sha256": source["sha256"],
        "sdk": lane["sdk"], "identity": {key: row[key] for key in ("id", "type", "classId", "ActionType")},
        "restrictions_authority": "native_getPropertyInfo", "native_metadata_sha256": canonical_sha256(info.raw)}
    return replace(info, reference_kind_evidence=proof)
