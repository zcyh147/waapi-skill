"""Pinned List declarations, distinct from live getPropertyInfo evidence."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time
from typing import Any, Mapping

from .canonical import canonical_sha256

CATALOG_ROOT = Path(__file__).resolve().parents[1] / "resources" / "metadata"
VERSIONS = frozenset({"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"})
MAX_CATALOG_BYTES = 2 * 1024 * 1024


def discovery_contract():
    return {"append": ["--field-source", "documented-lists", "--list"],
        "scope": "copy_exact_bound_owner_handle_or_type_handle", "selection": "copy_one_returned_scoped_selection",
        "evidence": "versioned_per_type_source_and_live_exact_class; not_getPropertyInfo",
        "absent_source": "unresolved_not_native_unavailable", "maximum_page_size": 64}


def load_catalog(version):
    if version not in VERSIONS:
        raise ValueError("No pinned documented-list source for this Wwise lane")
    with (CATALOG_ROOT / version / "documented-list-fields.json").open("rb") as source:
        raw = source.read(MAX_CATALOG_BYTES + 1)
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError("Documented-list source exceeds its byte bound")
    payload = json.loads(raw)
    if (not isinstance(payload, dict) or set(payload) != {"contract", "version", "source", "coverage", "classes", "catalog_sha256"}
            or payload["contract"] != "waapi-skill.documented-list-fields/v1" or payload["version"] != version):
        raise ValueError("Documented-list source has an invalid version or contract")
    unsigned = {key: value for key, value in payload.items() if key != "catalog_sha256"}
    if canonical_sha256(unsigned) != payload["catalog_sha256"]:
        raise ValueError("Documented-list source seal changed")
    rows = payload["classes"]
    if (not isinstance(rows, list) or not 1 <= len(rows) <= 2048
            or len({row["class_id"] for row in rows}) != len(rows)
            or payload["coverage"]["extracted_pages"] != len(rows)
            or payload["coverage"]["indexed_pages"] != len(rows) + len(payload["coverage"]["omissions"])):
        raise ValueError("Documented-list index/class coverage is malformed")
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"name", "class_id", "source_member", "source_sha256", "lists", "scalar_references"}
                or isinstance(row["class_id"], bool) or not isinstance(row["class_id"], int)
                or not 0 < row["class_id"] <= 0xFFFFFFFF
                or not re.fullmatch(r"wwiseobject_[a-z0-9_]+\.html", row["source_member"])
                or not re.fullmatch(r"[a-f0-9]{64}", row["source_sha256"])
                or not isinstance(row["lists"], list) or len(row["lists"]) > 128):
            raise ValueError("Malformed per-class documented-list source")
        if len({field["name"] for field in row["lists"]}) != len(row["lists"]):
            raise ValueError("Duplicate documented list fields")
        for field in row["lists"]:
            if (not isinstance(field, dict) or set(field) != {"name", "display_name", "declared_kind", "element_classes", "unresolved_element_types"}
                    or field["declared_kind"] != "List" or not re.fullmatch(r"[:_a-zA-Z0-9]+", field["name"])
                    or not isinstance(field["element_classes"], list) or len(field["element_classes"]) > 128):
                raise ValueError("Malformed documented list declaration")
            for element in field["element_classes"]:
                if set(element) != {"name", "class_id"} or not any(
                        element["class_id"] == selected["class_id"] and element["name"] == selected["name"] for selected in rows):
                    raise ValueError("List element class is not proved by the matching per-type index")
    return payload


def scope_evidence(version, *, scope_kind, scope_value, read):
    from .business_declarations import normalize_live_object_identity
    if scope_kind == "object":
        result = read("ak.wwise.core.object.get", {"from": {"id": [scope_value]}},
                      {"return": ["id", "name", "type", "path", "classId"]})
        rows = result.get("return") if isinstance(result, Mapping) else None
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("Documented-list discovery requires one exact live owner")
        identity = normalize_live_object_identity(rows[0])
        if identity.object_id != scope_value:
            raise ValueError("Documented-list owner GUID changed")
        class_id = rows[0].get("classId")
        owner = {"id": identity.object_id, "name": identity.name, "type": identity.object_type, "path": identity.path}
    else:
        class_id, owner = scope_value, None
    if isinstance(class_id, bool) or not isinstance(class_id, int) or not 0 < class_id <= 0xFFFFFFFF:
        raise ValueError("Exact live class ID is required; object type alone cannot identify a list class")
    catalog = load_catalog(version)
    matches = [row for row in catalog["classes"] if row["class_id"] == class_id]
    return catalog, matches[0] if matches else None, {"scope_kind": scope_kind, "scope_value": scope_value,
        "class_id": class_id, **({"owner": owner} if owner is not None else {})}


def field_evidence(catalog, row, scope, field):
    return {"kind": "documented-list", "version": catalog["version"], "catalog_sha256": catalog["catalog_sha256"],
        "source_member": row["source_member"], "source_sha256": row["source_sha256"],
        "scope": scope, "declaration": field}


def browse_lists(version, *, scope_kind, scope_value, read, context, page_size=20, page=None, selection=None):
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 64:
        raise ValueError("Documented-list page size must be 1..64")
    catalog, row, scope = scope_evidence(version, scope_kind=scope_kind, scope_value=scope_value, read=read)
    fields = row["lists"] if row else []
    snapshot = canonical_sha256({"context": context, "scope": scope, "catalog": catalog["catalog_sha256"]})
    issued, offset = int(time.time()), 0
    def locator(kind, index):
        return f"{kind}.{issued}.{index}.{canonical_sha256([kind, snapshot, issued, index])}"
    token = selection or page
    if token:
        try:
            kind, stamp, position, _digest = token.split(".")
            issued, offset = int(stamp), int(position)
            if (kind != ("dls1" if selection else "dlp1") or token != locator(kind, offset)
                    or not 0 <= offset < len(fields) or not 0 <= int(time.time()) - issued <= 900):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError("Documented-list selection changed scope/source or expired; discover this owner again") from None
    if selection:
        field = fields[offset]
        return field_evidence(catalog, row, scope, field)
    return {"items": [{"name": field["name"], "label": field["display_name"], "field_kind": "list",
        "element_classes": field["element_classes"], "unresolved_element_types": field["unresolved_element_types"],
        "selection": locator("dls1", index)} for index, field in enumerate(fields[offset:offset + page_size], offset)],
        "next_page": locator("dlp1", offset + page_size) if offset + page_size < len(fields) else None,
        "scope": scope, "catalog_sha256": catalog["catalog_sha256"], "source_coverage": catalog["coverage"],
        "availability": "documented_fields" if fields else "source_does_not_establish_list_fields_for_this_class",
        "native_unavailability_proven": False}


def bind_documented_field(registry, evidence):
    field, scope = evidence["declaration"], evidence["scope"]
    return registry.bind_field(scope_kind=scope["scope_kind"], scope_value=scope["scope_value"],
        token=field["name"], field_kind="list", value_type="list", restrictions={
            "documented_list": evidence}, metadata_digest=canonical_sha256(evidence))


def revalidate_documented_field(registry, field, *, read):
    catalog, row, scope = scope_evidence(registry.context.wwise_version,
        scope_kind=field.scope_kind, scope_value=field.scope_value, read=read)
    matches = [value for value in row["lists"] if value["name"] == field.token] if row else []
    if len(matches) != 1:
        raise ValueError("Documented list left its exact owner class/source")
    evidence = field_evidence(catalog, row, scope, matches[0])
    return registry.resolve_field(field.handle, scope_kind=field.scope_kind, scope_value=field.scope_value,
        metadata_digest=canonical_sha256(evidence))


def resolve_list_choice(session, value, *, owner_id):
    """Resolve an existing scoped handle or exact business alias, never a wire token."""
    candidates = [session.handles.bound_field(row["handle"]) for row in session.handles.as_dict()["fields"]
                  if row["field_kind"] == "list" and row["scope_kind"] == "object" and row["scope_value"] == owner_id]
    matches = [field for field in candidates if value in {field.handle, field.token}]
    if not matches or len({field.metadata_digest for field in matches}) != 1:
        from .business_declarations import business_repair
        raise business_repair("DOCUMENTED_LIST_SELECTION_REQUIRED", field="object_list",
            action="discover documented lists for this exact owner and copy its Field Handle or exact disclosed alias",
            choices=sorted({field.token for field in candidates}))
    return matches[0]


def resolve_live_list_evidence(version, owner_id, name, *, read):
    """Close a lexical alias at Preview against the exact observed class."""
    from .business_declarations import business_repair
    catalog, row, scope = scope_evidence(version, scope_kind="object", scope_value=owner_id, read=read)
    fields = row["lists"] if row else []
    matches = [field for field in fields if field["name"] == name]
    if len(matches) != 1:
        raise business_repair("DOCUMENTED_LIST_SELECTION_REQUIRED", field="object_list",
            action="choose one documented List of the exact live owner class; unlisted source scope remains unresolved",
            choices=[field["name"] for field in fields])
    return field_evidence(catalog, row, scope, matches[0])


def observe_list_binding(evidence, *, read, preserve_reference_ids=(), after_write=False):
    """Observe ordered member IDs, exact classes, and actual owner presence."""
    if not isinstance(evidence, Mapping) or evidence.get("kind") != "documented-list":
        raise ValueError("An exact documented-list proof is required")
    reference_targets = evidence.get("reference_targets")
    if reference_targets is not None and (not isinstance(reference_targets, list) or len(reference_targets) > 32
            or len(set(reference_targets)) != len(reference_targets)
            or any(not isinstance(value, str) or not re.fullmatch(r"\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}", value) for value in reference_targets)):
        raise ValueError("Documented List reference assignment needs bounded exact distinct GUIDs")
    source_evidence = {key: value for key, value in evidence.items() if key != "reference_targets"}
    scope = evidence["scope"]
    if scope["scope_kind"] != "object":
        raise ValueError("Current list state requires its exact live owner")
    catalog, row, actual_scope = scope_evidence(evidence["version"], scope_kind="object",
        scope_value=scope["scope_value"], read=read)
    fields = [field for field in row["lists"] if field["name"] == evidence["declaration"]["name"]] if row else []
    actual_evidence = field_evidence(catalog, row, actual_scope, fields[0]) if len(fields) == 1 else None
    if after_write and actual_evidence is not None:
        # The graph verifier owns requested name/path changes. Source, GUID and
        # exact class stay fixed; pre-execution still compares the full owner.
        actual_evidence = {**actual_evidence, "scope": {key: value for key, value in actual_evidence["scope"].items() if key != "owner"}}
        source_evidence = {**source_evidence, "scope": {key: value for key, value in source_evidence["scope"].items() if key != "owner"}}
    if actual_evidence != source_evidence:
        raise ValueError("Documented List source or exact owner/class changed")
    if fields[0]["unresolved_element_types"]:
        raise ValueError("The source does not establish every allowed List element class; this scope remains unresolved")
    owner = scope["scope_value"]
    accessor = "@" + fields[0]["name"]
    result = read("ak.wwise.core.object.get", {"from": {"id": [owner]}}, {"return": ["id", accessor]})
    rows = result.get("return") if isinstance(result, Mapping) else None
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("id", "").upper() != owner:
        raise ValueError("Documented List owner must resolve once")
    members = rows[0].get(accessor)
    if not isinstance(members, list) or len(members) > 128:
        raise ValueError("Documented List needs a complete bounded membership observation")
    ids = [member.get("id") if isinstance(member, Mapping) else None for member in members]
    if any(not isinstance(value, str) or not re.fullmatch(r"\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}", value) for value in ids):
        raise ValueError("List membership must contain canonical GUIDs")
    ids = [value.upper() for value in ids]
    if len(set(ids)) != len(ids):
        raise ValueError("List membership contains duplicate GUIDs")
    reference_ids = list(dict.fromkeys([*ids, *(reference_targets or []), *preserve_reference_ids]))
    if not reference_ids:
        return {"evidence": dict(evidence), "members": [], **({"reference_objects": [],
            "ownership_scope": "actual_key_presence_and_value_retained; not_inferred_from_List_or_native_type"}
            if reference_targets is not None else {})}
    projection = ["id", "name", "type", "path", "classId", "owner", "parent", "notes"]
    if len(reference_ids) > 128:
        raise ValueError("Current and requested List references exceed the complete member proof bound")
    result = read("ak.wwise.core.object.get", {"from": {"id": reference_ids}}, {"return": projection})
    rows = result.get("return") if isinstance(result, Mapping) else None
    if not isinstance(rows, list) or len(rows) != len(reference_ids):
        raise ValueError("List member proof must include every exact GUID once")
    observed = {}
    allowed = {element["class_id"] for element in fields[0]["element_classes"]}
    for member in rows:
        identity = member.get("id", "").upper()
        if identity not in reference_ids or identity in observed:
            raise ValueError("List member proof has duplicate/extra identities")
        class_id = member.get("classId")
        if isinstance(class_id, bool) or not isinstance(class_id, int) or class_id not in allowed:
            raise ValueError("Actual member class is not proved by this exact source List declaration")
        # Missing owner is deliberately different from an explicit null. Neither
        # proves permission to delete an object through an owned-list operation.
        native_owner = member.get("owner")
        owner_id = native_owner.get("id") if isinstance(native_owner, Mapping) else native_owner
        if reference_targets is None and ("owner" not in member or not isinstance(owner_id, str) or owner_id.upper() != owner):
            raise ValueError("Actual member ownership is unproved or differs from the selected List owner")
        observed[identity] = {key: member[key] for key in projection if key in member}
    result = {"evidence": dict(evidence), "members": [observed[identity] for identity in ids]}
    if reference_targets is not None:
        result["reference_objects"] = [observed[identity] for identity in sorted(reference_ids)]
        result["ownership_scope"] = "actual_key_presence_and_value_retained; not_inferred_from_List_or_native_type"
    return result


def list_guard_assertions(guards, *, read, after_write=False):
    assertions = []
    for guard in guards:
        try:
            preserve = [row["id"] for row in guard.get("reference_objects", [])]
            actual = observe_list_binding(guard["evidence"], read=read, preserve_reference_ids=preserve, after_write=after_write)
            passed = (actual.get("reference_objects") == guard.get("reference_objects") if after_write else actual == guard)
        except (ValueError, KeyError, TypeError) as exc:
            actual, passed = {"error": str(exc)}, False
        assertions.append({"name": "documented list source, owner and exact member classes remain bound",
            "passed": bool(passed), "evidence": {"expected": guard, "actual": actual}})
    return assertions
