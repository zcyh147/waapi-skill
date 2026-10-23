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
# These exact 2025 classes inherit the same MetadataReferences InnerType.
METADATA_INNER_OWNERS = {
    3997712: "AuxBus", 1900560: "BlendContainer", 1376272: "Bus",
    2228240: "MusicPlaylistContainer", 1769488: "MusicSegment", 2293776: "MusicSwitchContainer",
    1835024: "MusicTrack", 524304: "PropertyContainer", 589840: "RandomSequenceContainer",
    65552: "Sound", 655376: "SwitchContainer",
}


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


def resolve_class_list_evidence(version, class_id, name):
    from .business_declarations import business_repair
    catalog, row, scope = scope_evidence(version, scope_kind="class", scope_value=class_id, read=None)
    fields = row["lists"] if row else []
    matches = [field for field in fields if field["name"] == name]
    if len(matches) != 1:
        raise business_repair("DOCUMENTED_LIST_SELECTION_REQUIRED", field="object_list",
            action="choose one documented List of this exact planned class; unlisted source remains unresolved",
            choices=[field["name"] for field in fields])
    return field_evidence(catalog, row, scope, matches[0])


def resolve_planned_list_evidence(session, value, *, owner_handle):
    """Use the existing declaration's class; the result handle binds its occurrence."""
    from .business_declarations import NewDescendantTarget, resolve_semantic_kind, business_repair
    owners = [row for row in session.declarations if row.result_handle == owner_handle
        and isinstance(row.target, NewDescendantTarget)]
    if len(owners) != 1:
        raise ValueError("The planned List owner declaration is not unique")
    kind = owners[0].target.kind
    if kind.startswith("bth1-"):
        class_id = session.handles.resolve_type(kind).class_id
    else:
        metadata_type = resolve_semantic_kind(kind, version=session.context.wwise_version).metadata_object_type
        classes = [row for row in load_catalog(session.context.wwise_version)["classes"] if row["name"] == metadata_type]
        if len(classes) != 1:
            raise business_repair("PLANNED_LIST_CLASS_EVIDENCE_REQUIRED", field="object_list",
                action="discover the planned owner's exact live Type Handle and List declaration")
        class_id = classes[0]["class_id"]
    selected = session.handles.bound_field(value) if value.startswith("bfh1-") else None
    name = selected.token if selected is not None else value
    evidence = resolve_class_list_evidence(session.context.wwise_version, class_id, name)
    if selected is not None and (selected.field_kind != "list" or selected.scope_kind != "class"
            or selected.scope_value != class_id or selected.restrictions.get("documented_list") != evidence):
        raise business_repair("FIELD_HANDLE_SCOPE_MISMATCH", field="object_list",
            action="select the List for this planned owner's exact class")
    return evidence



def manual_marker_profile(version):
    """One SDK-certified anonymous WObject profile, separate from Inner naming."""
    if version not in {"2023.1", "2024.1", "2025.1"}:
        return None
    path = Path(__file__).resolve().parents[1] / "references" / "semantic" / version / "manual-marker-construction-source.json"
    source = json.loads(path.read_text(encoding="utf-8"))
    catalog = load_catalog(version)
    if (source["contract"] != "waapi-skill.manual-marker-construction-source/v1" or source["version"] != version
            or source["source"]["build"] != catalog["source"]["build"]
            or source["source"]["archive_sha256"] != catalog["source"]["archive_sha256"]
            or (source["owner_class_id"], source["collection"], source["element_class_id"], source["element_type"], source["native_name"])
                != (16, "Markers", 5373968, "Marker", "")
            or source["sdk_example"] != {"marker_input_mode": 2, "list_mode": "append",
                "marker": {"type": "Marker", "name": "", "@Time": 1, "@Label": "Waapi Generated"}}):
        raise ValueError("Manual Marker constructor differs from its matching SDK authority")
    binding = resolve_class_list_evidence(version, 16, "Markers")
    if binding["declaration"]["element_classes"] != [{"name": "Marker", "class_id": 5373968}]:
        raise ValueError("Manual Marker requires the exact AudioFileSource List declaration")
    return {**source, "source_sha256": canonical_sha256(source), "list_source": binding}


def is_manual_marker_class(version, name, class_id):
    return version in {"2023.1", "2024.1", "2025.1"} and (name, class_id) == ("Marker", 5373968)


def certify_anonymous_marker(spec, binding):
    """Bind the actual owner scope, never a base-name or Inner substitution."""
    if not spec.get("manual_marker"):
        return
    profile = manual_marker_profile(binding["version"])
    if (profile is None or binding["scope"]["class_id"] != 16
            or binding["declaration"] != profile["list_source"]["declaration"]
            or binding["scope"]["scope_kind"] == "object" and binding["scope"].get("owner", {}).get("type") != "AudioFileSource"
            or spec["class_metadata"].get("type") != "WObject"):
        raise ValueError("Anonymous Marker requires exact AudioFileSource16/Markers/Marker5373968 WObject placement")
    spec["manual_marker"] = profile


def owned_inner_identity(binding, member_class):
    """One observed Inner representation, bound to its exact List source.

    The R87 native MetadataSlot result is unnamed PluginInnerObject. Other
    Inner classes/versions retain their own unresolved representation rules.
    """
    owner_class = binding.get("scope", {}).get("class_id")
    if (type(owner_class) is not int or owner_class not in METADATA_INNER_OWNERS
            or (binding.get("version"), binding.get("declaration", {}).get("name"), member_class)
                != ("2025.1", "Metadata", 5570560)):
        return None
    expected = resolve_class_list_evidence("2025.1", owner_class, "Metadata")
    if expected["declaration"]["element_classes"] != [{"name": "MetadataSlot", "class_id": 5570560}]:
        raise ValueError("Inner identity requires the sole exact MetadataSlot element class")
    if any(binding.get(key) != expected[key] for key in ("kind", "version", "catalog_sha256", "source_member", "source_sha256", "declaration")):
        raise ValueError("Inner identity requires its matching exact owner/List/element source")
    return {"kind": "source-certified-owned-inner/v1", "version": "2025.1", "owner_class_id": owner_class,
        "collection": "Metadata", "element_class_id": 5570560, "class_name": "MetadataSlot",
        "catalog_sha256": expected["catalog_sha256"], "source_member": expected["source_member"],
        "source_sha256": expected["source_sha256"], "native_type": "PluginInnerObject", "native_name": "",
        "declaration_name_role": "label"}


def inner_result_candidate(spec, object_id, name):
    """Closed Inner representation relation shared by both result consumers."""
    profile = spec.get("inner_identity")
    if profile is None:
        return None
    from .operation_registry import _same_identity
    retained = spec.get("preexisting_id")
    if retained is not None:
        return _same_identity(object_id, retained) and name == spec["pre_state"]["name"]
    return name == profile["native_name"]


def validate_planned_list_source(binding, *, read):
    evidence = {key: value for key, value in binding.items() if key not in {"planned_owner", "reference_targets"}}
    if evidence.get("scope", {}).get("scope_kind") != "class":
        raise ValueError("A planned List owner requires class-scoped source evidence")
    actual = resolve_class_list_evidence(evidence["version"], evidence["scope"]["class_id"], evidence["declaration"]["name"])
    if actual != evidence:
        raise ValueError("The planned List class/source changed")
    catalog = load_catalog(evidence["version"])
    row = next(row for row in catalog["classes"] if row["class_id"] == evidence["scope"]["class_id"])
    result = read("ak.wwise.core.object.getTypes", {}, {})
    types = result.get("return") if isinstance(result, Mapping) else None
    matches = [item for item in types if isinstance(item, Mapping) and item.get("classId") == row["class_id"]
        and not isinstance(item.get("classId"), bool) and item.get("name") == row["name"]] if isinstance(types, list) else []
    if len(matches) != 1:
        raise ValueError("The planned List owner class no longer matches exact live getTypes")
    for element in evidence["declaration"]["element_classes"]:
        profile = owned_inner_identity(evidence, element["class_id"])
        if profile is not None:
            members = [item for item in types if isinstance(item, Mapping) and item.get("classId") == profile["element_class_id"]]
            if len(members) != 1 or members[0].get("name") != profile["class_name"] or members[0].get("type") != "Inner":
                raise ValueError("The selected Inner element lost its exact live class/category")
    return evidence


def observe_planned_list(binding, owner_id, *, read):
    """Resolve a planned occurrence only after its real GUID is independently known."""
    evidence = {key: value for key, value in binding.items() if key not in {"planned_owner", "reference_targets"}}
    actual = resolve_live_list_evidence(evidence["version"], owner_id, evidence["declaration"]["name"], read=read)
    if (actual["scope"]["class_id"] != evidence["scope"]["class_id"]
            or any(actual[key] != evidence[key] for key in ("catalog_sha256", "source_member", "source_sha256", "declaration"))):
        raise ValueError("The actual planned owner differs from its declared List class/source")
    return observe_list_binding(actual, read=read)


def planned_list_guard_assertions(guards, *, read, after_write=False):
    assertions = []
    for guard in guards:
        try:
            validate_planned_list_source(guard["binding"], read=read)
            before = guard.get("before")
            actual = (observe_planned_list(guard["binding"], before["evidence"]["scope"]["scope_value"], read=read)
                if before is not None and not after_write else None)
            passed = after_write or actual == before
            evidence = {"expected": before, "actual": actual, "member_verification": "actual_result_GUID_in_graph_verifier"}
        except (ValueError, KeyError, TypeError) as exc:
            evidence, passed = {"error": str(exc)}, False
        assertions.append({"name": "planned List source and pre-existing owner state remain bound",
            "passed": bool(passed), "evidence": evidence})
    return assertions


def prove_source_owned_empty_list(evidence, owner_row, *, read, platform=None):
    """Normalize only a source-proven fixed owned List with an independent empty read.

    A missing projection alone is never membership evidence. The fixed owned
    Lists and certified 2025 MetadataSlot profile require an independently
    empty bounded relationship read; other Lists need their own authority.
    """
    scope = evidence.get("scope", {})
    name = evidence.get("declaration", {}).get("name")
    owner = scope.get("scope_value")
    if (evidence.get("kind") != "documented-list" or scope.get("scope_kind") != "object"
            or (name not in {"RTPC", "Effects"} and owned_inner_identity(evidence, 5570560) is None)
            or not isinstance(owner_row, Mapping)
            or set(owner_row) != {"id"} or owner_row.get("id", "").upper() != owner
            or not isinstance(evidence.get("source_sha256"), str)):
        raise ValueError("Missing List projection requires its exact documented owner/source and supported empty-list representation")
    from .operation_registry import _prove_omitted_object_list_empty
    empty = _prove_omitted_object_list_empty(owner, name, read=read, platform=platform,
        **({"documented_list": evidence} if name == "Metadata" else {}))
    return {"kind": "missing-empty-object-list", "version": evidence["version"],
        "field": "@" + name, "observed_row_keys": ["id"], "normalized_value": [],
        "list_source": dict(evidence), "emptiness_readback": empty}


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
    if accessor not in rows[0]:
        # actual_evidence has just been re-resolved against this exact live
        # owner/class and immutable List declaration above.
        prove_source_owned_empty_list(evidence, rows[0], read=read)
        members = []
    else:
        members = rows[0][accessor]
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


def capture_slot_reference_targets(specs, roles):
    """Preserve observed external targets, excluding objects changed by this graph."""
    changed = {spec.get("target_id") or spec.get("preexisting_id") for spec in specs}
    selected = {identity for spec in specs if "documented_list_element_class" in spec
        for reference in spec.get("references", [])
        for identity in (reference.get("target_id") if isinstance(reference.get("target_id"), list) else [reference.get("target_id")])
        if isinstance(identity, str) and identity not in changed}
    fields = {"id", "name", "type", "path", "parent", "owner", "notes", "classId"}
    result = {}
    for role in roles.values():
        if role.object in selected:
            row = {key: value for key, value in role.row.items() if key in fields}
            previous = result.get(role.object, {})
            if any(previous[key] != row[key] for key in previous.keys() & row.keys()):
                raise ValueError("External slot reference targets disagreed within this Preview")
            # A condition guard may observe class/owner in addition to the
            # ordinary exact-identity projection. Retain their compatible union;
            # every observed field is independently revalidated and preserved.
            result[role.object] = {**previous, **row}
    if set(result) != selected or len(result) > 128:
        raise ValueError("Every external slot reference target requires a complete bounded observation")
    return [result[identity] for identity in sorted(result)]


def slot_reference_preservation_assertions(before, *, read):
    if not before:
        return []
    fields = list(dict.fromkeys(key for row in before for key in row))
    identities = [row["id"] for row in before]
    result = read("ak.wwise.core.object.get", {"from": {"id": identities}}, {"return": fields})
    rows = result.get("return") if isinstance(result, Mapping) else None
    actual = {row.get("id"): row for row in rows if isinstance(row, Mapping)} if isinstance(rows, list) else {}
    passed = (isinstance(rows, list) and len(rows) == len(before) == len(actual)
        and set(actual) == set(identities) and all(
            {key: actual[row["id"]][key] for key in row if key in actual[row["id"]]} == row for row in before))
    return [{"name": "external slot reference target observations remain unchanged", "passed": bool(passed),
        "evidence": {"expected": before, "actual": rows}}]


def observe_planned_reference_targets(binding, *, read):
    identities = binding.get("reference_targets")
    if (not isinstance(identities, list) or len(identities) > 32 or len(set(identities)) != len(identities)
            or any(not isinstance(value, str) or not re.fullmatch(r"\{[A-F0-9]{8}(?:-[A-F0-9]{4}){3}-[A-F0-9]{12}\}", value) for value in identities)):
        raise ValueError("Planned reference Lists require bounded distinct canonical target GUIDs")
    if not identities:
        return []
    result = read("ak.wwise.core.object.get", {"from": {"id": identities}},
        {"return": ["id", "name", "type", "path", "classId", "parent", "owner", "notes"]})
    rows = result.get("return") if isinstance(result, Mapping) else None
    allowed = {item["class_id"] for item in binding["declaration"]["element_classes"]}
    actual = {row.get("id"): row for row in rows if isinstance(row, Mapping)} if isinstance(rows, list) else {}
    if (not isinstance(rows, list) or len(rows) != len(identities) or len(actual) != len(identities)
            or set(actual) != set(identities) or binding["declaration"]["unresolved_element_types"]
            or any(isinstance(row.get("classId"), bool) or row.get("classId") not in allowed for row in rows)):
        raise ValueError("Each actual planned reference List target must have one exact permitted class")
    return [actual[identity] for identity in identities]


def planned_reference_guard_assertions(guards, *, read):
    assertions = []
    for guard in guards:
        try:
            validate_planned_list_source(guard["binding"], read=read)
            actual = observe_planned_reference_targets(guard["binding"], read=read)
            mutable = set(guard.get("changed_target_ids", []))
            passed = all(({key: row.get(key) for key in ("id", "classId")} ==
                {key: expected.get(key) for key in ("id", "classId")} if row["id"] in mutable else row == expected)
                for row, expected in zip(actual, guard["targets"], strict=True))
            evidence = {"expected": guard["targets"], "actual": actual}
        except (ValueError, KeyError, TypeError) as exc:
            evidence, passed = {"error": str(exc)}, False
        assertions.append({"name": "planned reference List source, target classes and unchanged external state remain bound",
            "passed": bool(passed), "evidence": evidence})
    return assertions


def owned_empty_identity_candidate(version, row):
    """Finite observed identity profiles; generic empty names remain invalid."""
    return (row.get('name') == '' and type(row.get('classId')) is int
        and ((version == '2025.1' and (row.get('type'), row['classId']) == ('PluginInnerObject', 5570560))
            or is_manual_marker_class(version, row.get('type'), row['classId'])))


def owned_empty_identity_descriptor(version, native_type, class_id, owner_class_id):
    if type(class_id) is not int or type(owner_class_id) is not int:
        return None
    if is_manual_marker_class(version, native_type, class_id) and owner_class_id == 16:
        profile = manual_marker_profile(version)
        return {'version': version, 'native_type': native_type, 'class_id': class_id,
            'owner_class_id': owner_class_id, 'owner_type': 'AudioFileSource', 'collection': 'Markers',
            'source': profile['list_source'], 'profile': profile}
    if ((version, native_type, class_id) != ('2025.1', 'PluginInnerObject', 5570560) or owner_class_id not in METADATA_INNER_OWNERS):
        return None
    source = resolve_class_list_evidence(version, owner_class_id, 'Metadata')
    return {'version': version, 'native_type': native_type, 'class_id': class_id,
        'owner_class_id': owner_class_id, 'owner_type': METADATA_INNER_OWNERS[owner_class_id], 'collection': 'Metadata', 'source': source,
        'profile': owned_inner_identity(source, class_id)}


def validate_owned_empty_identity(proof):
    if (not isinstance(proof, Mapping) or set(proof) != {'contract', 'descriptor', 'object_id', 'owner', 'members'}
            or proof['contract'] != 'waapi-skill.owned-empty-identity/v1'):
        raise ValueError('Owned identity proof is malformed')
    descriptor = proof['descriptor']
    if not isinstance(descriptor, Mapping):
        raise ValueError('Owned identity descriptor is malformed')
    expected = owned_empty_identity_descriptor(descriptor.get('version'), descriptor.get('native_type'),
        descriptor.get('class_id'), descriptor.get('owner_class_id'))
    owner = proof['owner']
    members = proof['members']
    from .operation_registry import _ordinary_object_type_matches
    guid = r'\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\}'
    if (expected is None or descriptor != expected or not isinstance(owner, Mapping)
            or set(owner) != {'id', 'name', 'type', 'path', 'classId'}
            or not isinstance(owner['id'], str) or re.fullmatch(guid, owner['id']) is None
            or owner['id'] == '{00000000-0000-0000-0000-000000000000}'
            or type(owner['classId']) is not int or owner['classId'] != descriptor['owner_class_id']
            or not _ordinary_object_type_matches(owner['type'],
                {'canonical_type': descriptor['owner_type'], 'requested_type': descriptor['owner_type']})
            or not isinstance(members, list) or not 1 <= len(members) <= 128
            or not isinstance(proof['object_id'], str) or re.fullmatch(guid, proof['object_id']) is None
            or proof['object_id'] == '{00000000-0000-0000-0000-000000000000}'
            or any(not isinstance(item, Mapping) or set(item) - {'notes', 'path'} != {'id', 'classId', 'type', 'owner_id', 'name'}
                or (item.get('id') == proof['object_id'] and 'path' in item)
                or type(item['classId']) is not int or item['classId'] != descriptor['class_id']
                or item['type'] != descriptor['native_type'] or item['owner_id'] != owner['id']
                or not isinstance(item['name'], str) or ('notes' in item and not isinstance(item['notes'], str))
                or ('path' in item and not isinstance(item['path'], str))
                or not isinstance(item['id'], str) or re.fullmatch(guid, item['id']) is None
                or item['id'] == '{00000000-0000-0000-0000-000000000000}' for item in members)
            or len({item['id'] for item in members}) != len(members)
            or sum(item['id'] == proof['object_id'] for item in members) != 1):
        raise ValueError('Owned identity requires its exact source, owner and complete typed member roster')
    from .business_declarations import normalize_live_object_identity
    normalize_live_object_identity(owner)
    return proof


def capture_owned_empty_identity(version, row, *, read):
    """Certify one exact selected GUID through its actual owning source/List."""
    if not owned_empty_identity_candidate(version, row):
        return None
    identity = row.get('id')
    result = read('ak.wwise.core.object.get', {'from': {'id': [identity]}},
        {'return': ['id', 'name', 'type', 'path', 'classId', 'owner']})
    rows = result.get('return') if isinstance(result, Mapping) else None
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping)
            or any(rows[0].get(key) != row.get(key) for key in ('id', 'name', 'type', 'path', 'classId'))):
        raise ValueError('Owned identity changed during exact GUID binding')
    selected = rows[0]
    owner_id = selected.get('owner', {}).get('id') if isinstance(selected.get('owner'), Mapping) else None
    if not isinstance(owner_id, str) or re.fullmatch(r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}', owner_id) is None:
        raise ValueError('Owned identity requires one canonical actual owner GUID')
    catalog, owner_class, scope = scope_evidence(version, scope_kind='object', scope_value=owner_id.upper(), read=read)
    descriptor = owned_empty_identity_descriptor(version, selected['type'], selected['classId'], scope['class_id'])
    if descriptor is None:
        raise ValueError('Owned identity has no matching owner/class/List source profile')
    fields = [field for field in owner_class['lists'] if field['name'] == descriptor['collection']] if owner_class else []
    if len(fields) != 1:
        raise ValueError('Owned identity source List is not unique')
    evidence = field_evidence(catalog, owner_class, scope, fields[0])
    validate_planned_list_source(descriptor['source'], read=read)
    observation = observe_list_binding(evidence, read=read)
    members = observation['members']
    matches = [member for member in members if member['id'].upper() == identity.upper()]
    if len(matches) != 1 or any(matches[0].get(key) != selected.get(key) for key in ('id', 'name', 'type', 'path', 'classId', 'owner')):
        raise ValueError('Selected owned GUID does not match its complete typed List observation')
    proof = {'contract': 'waapi-skill.owned-empty-identity/v1', 'descriptor': descriptor,
        'object_id': identity.upper(), 'owner': {**evidence['scope']['owner'], 'classId': evidence['scope']['class_id']},
        'members': [{'id': member['id'].upper(), 'type': member['type'], 'classId': member['classId'],
            'owner_id': owner_id.upper(), 'name': member['name'],
            **({'notes': member['notes']} if 'notes' in member else {}),
            **({'path': member['path']} if member['id'].upper() != identity.upper() and 'path' in member else {})} for member in members]}
    return validate_owned_empty_identity(proof)
