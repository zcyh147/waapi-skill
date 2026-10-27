"""2025 custom Metadata placement on the existing source-owned Metadata List.

The matching WObjects member pinned by constructor_inputs.SOURCE declares
MetadataSlot.Metadata with SupportCustom=true. Both custom references and
ShareSet children use object.set's same recursive selected-class definition.
No native token or class arithmetic is supplied by the caller.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from uuid import UUID

from .constructor_inputs import authority, local_reference_value
from .documented_list_fields import (
    METADATA_INNER_OWNERS, observe_list_binding, owned_inner_identity,
    resolve_live_list_evidence,
)


def _guid(value):
    if isinstance(value, Mapping):
        value = value.get("id")
    if not isinstance(value, str) or re.fullmatch(r"\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}", value) is None:
        raise ValueError("Metadata placement needs an exact non-null GUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("Metadata placement needs an exact non-null GUID") from exc
    if not parsed.int:
        raise ValueError("Metadata placement needs an exact non-null GUID")
    return "{" + str(parsed).upper() + "}"


def observe_metadata_placement(version, target_id, target_type, *, read):
    """Seal the source, actual owner, ordered slots and every local reference."""
    if version != "2025.1":
        raise ValueError("Owner-local Metadata construction is packaged only for 2025.1; older direct-List ownership remains unmapped")
    source = resolve_live_list_evidence(version, target_id, "Metadata", read=read)
    owner_class = source["scope"]["class_id"]
    if METADATA_INNER_OWNERS.get(owner_class) != target_type:
        raise ValueError("Metadata placement requires its exact source-certified audio owner class")
    inner = owned_inner_identity(source, 5570560)
    spec = {"class_id": 5570560, "collection": "Metadata"}
    constructor = authority(spec, version=version)
    if inner is None or constructor is None:
        raise ValueError("Custom Metadata lost its matching slot/constructor authority")
    spec["constructor_inputs"] = constructor
    from .operation_registry import _read_property_info, _require_object_reference_metadata
    from .metadata_restrictions import reference_allowed_types
    reference = _read_property_info(read, class_id=5570560, name="Metadata")
    _require_object_reference_metadata(reference)
    allowed = reference_allowed_types(reference.restriction)
    if reference.name != "Metadata" or reference.dependencies or allowed and "Metadata" not in allowed:
        raise ValueError("Live MetadataSlot reference no longer permits its source-certified Metadata constructor")
    for restriction in reference.restriction.get("restrictions", []):
        if restriction == "notNull":
            continue
        if (not isinstance(restriction, Mapping) or "type" not in restriction
                or set(restriction) - {"type", "sharedOnlyTypes"}
                or not isinstance(restriction["type"], list)
                or any(not isinstance(value, str) for value in restriction["type"])
                or not isinstance(restriction.get("sharedOnlyTypes", []), list)
                or restriction.get("sharedOnlyTypes")):
            raise ValueError("Live MetadataSlot custom-reference classifier is unavailable or constrained")
    guard = observe_list_binding(source, read=read)
    members = guard["members"]
    for row in members:
        if row.get("type") != inner["native_type"] or not isinstance(row.get("name"), str):
            raise ValueError("Metadata members must retain their source-certified Inner representation")
        if row.get("parent") is not None and _guid(row["parent"]) != _guid(target_id):
            raise ValueError("MetadataSlot parent conflicts with its actual owner")
    ids = [_guid(row["id"]) for row in members]
    references = []
    if ids:
        options = {"return": ["id", "@Metadata"]}
        result = read("ak.wwise.core.object.get", {"from": {"id": ids}}, options)
        rows = result.get("return") if isinstance(result, Mapping) else None
        if not isinstance(rows, list) or len(rows) != len(ids):
            raise ValueError("Every MetadataSlot local reference must resolve once")
        observed = {}
        for row in rows:
            identity = _guid(row.get("id")) if isinstance(row, Mapping) else None
            if identity not in ids or identity in observed or "@Metadata" not in row:
                raise ValueError("MetadataSlot reference read has missing, duplicate or extra rows")
            raw = row["@Metadata"]
            target = _guid(local_reference_value(spec, "Metadata", raw))
            observed[identity] = {"slot_id": identity, "metadata_id": target, "native_value": raw}
        references = [observed[identity] for identity in ids]
    return {"kind": "metadata_slots", "authority": {"list": source, "inner": inner,
        "constructor": constructor, "reference_metadata": reference.as_dict(), "custom_reference": "Metadata", "support_custom": True},
        "guard": guard, "references": references,
        "preexisting_plugin_ids": list(dict.fromkeys(row["metadata_id"] for row in references))}


def appended_metadata_binding(before, after, created_slot_id, result_slot):
    """Bind the one appended slot and preserve the full ordered prior roster."""
    slot_id = _guid(created_slot_id)
    old_members, members = before["guard"]["members"], after["guard"]["members"]
    if (before["authority"] != after["authority"]
            or len(members) != len(old_members) + 1
            or members[:-1] != old_members or after["references"][:-1] != before["references"]
            or _guid(members[-1]["id"]) != slot_id or members[-1].get("name") != ""
            or slot_id in {_guid(row["id"]) for row in old_members}):
        raise ValueError("Custom Metadata must append exactly one fresh slot and preserve every prior ordered member/reference")
    reference = after["references"][-1]
    plugin_id = reference["metadata_id"]
    if (plugin_id in before["preexisting_plugin_ids"]
            or plugin_id in {_guid(row["id"]) for row in members}
            or plugin_id == _guid(after["authority"]["list"]["scope"]["scope_value"])):
        raise ValueError("Custom Metadata must resolve to a fresh independent plug-in identity")
    if "@Metadata" in result_slot:
        nested = result_slot["@Metadata"]
        if isinstance(nested, list) and len(nested) == 1:
            nested = nested[0]
        if _guid(nested) != plugin_id:
            raise ValueError("Returned and observed custom Metadata identities disagree")
    return plugin_id
