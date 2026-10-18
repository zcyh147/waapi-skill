"""Owned Effect rendering conditions shared by creation and field edits.

The five pinned Authoring Help ``rendering_effects`` sections specify that
rendering a later Effect also renders its predecessors. Bypass precedence
concerns processing; it does not make a stored Boolean combination invalid.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
from copy import deepcopy


class EffectRenderConditionError(ValueError):
    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def plan_chain(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Plan the true prefix without changing any explicit false or Bypass."""
    explicit_true = [i for i, entry in enumerate(entries) if entry.get("render_intent") is True]
    derived: list[dict[str, Any]] = []
    if explicit_true:
        last = max(explicit_true)
        for i, entry in enumerate(entries[:last]):
            if entry.get("render_intent") is False:
                raise EffectRenderConditionError(
                    "EFFECT_RENDER_CHAIN_CONFLICT",
                    "A later rendered Effect necessarily renders every predecessor; explicit false before true is contradictory.",
                    details={"false_member": entry["key"], "later_true_member": entries[last]["key"],
                             "mutation_dispatched": False},
                )
            if entry.get("render_intent") is None and entry.get("render_before") is not True:
                derived.append({"key": entry["key"], "before": entry.get("render_before"), "after": True})
    final = [entry.get("render_intent") if entry.get("render_intent") is not None
             else entry.get("render_before") for entry in entries]
    for i, entry in enumerate(entries):
        if entry.get("render_intent") is False and any(value is True for value in final[i + 1:]):
            raise EffectRenderConditionError("EFFECT_RENDER_SUFFIX_OBSERVATION_REQUIRED",
                "Clearing a Render flag before a retained rendered successor requires a separately observed suffix rule.",
                details={"member": entry["key"], "mutation_dispatched": False,
                         "remaining_obligation": "observe native stored-flag clearing/suffix behavior"})
    return {"derived": derived, "bypass_policy": "preserve_stored_flags; Bypass takes precedence during processing",
            "acceptance_scope": "stored_slot_state_not_rendered_audio"}


def reject_explicit_graph_conflicts(specs: Sequence[Mapping[str, Any]]) -> None:
    groups: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for spec in specs:
        if spec.get("collection") != "Effects" or spec.get("canonical_type") != "EffectSlot":
            continue
        intent = next((row["value"] for row in spec.get("properties", []) if row["name"] == "Render"), None)
        groups.setdefault((spec.get("parent_request_path"), spec.get("platform")), []).append(
            {"key": spec["request_path"], "render_intent": intent})
    for entries in groups.values():
        plan_chain(entries)


# These adapters use the same bounded registry readers as the ordinary graph.
# The import is local because Registry owns the public operation orchestration.
def prepare_graph(specs, native_nodes, *, version, read, root_parent=None, root_collection=None):
    from . import operation_registry as r
    from .documented_list_fields import resolve_class_list_evidence, resolve_live_list_evidence
    by_path = {spec["request_path"]: spec for spec in specs}
    groups = {}
    for spec in specs:
        if spec.get("collection") == "Effects" and spec.get("canonical_type") == "EffectSlot":
            groups.setdefault((spec.get("parent_request_path"), spec.get("platform")), []).append(spec)
    exact = {}
    for spec in specs:
        if not spec.get("existing_target") or not any(prop["name"] == "Render" for prop in spec["properties"]):
            continue
        object_id = spec["target_id"]
        rows = r._read_object_id_rows(object_id, fields=[*r.OBJECT_LIST_SNAPSHOT_FIELDS, "classId"], read=read, platform=spec.get("platform"))
        if len(rows) != 1 or not r._same_identity(rows[0].get("id"), object_id):
            raise r.OperationContractError("INVALID_READBACK", "Render field source must resolve exactly once")
        if rows[0].get("classId") != 5505040:
            continue  # an unrelated plug-in field named Render is not an EffectSlot
        owner_id = r._reference_identity(rows[0].get("owner"))
        if not r._valid_object_id(owner_id):
            raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "EffectSlot Render needs its actual owner GUID")
        exact.setdefault((owner_id, spec.get("platform")), []).append(spec)
    chains = []
    work = [(parent_path, platform, members, None) for (parent_path, platform), members in groups.items()]
    work.extend((None, platform, members, owner_id) for (owner_id, platform), members in exact.items())
    combined = {}
    for parent_path, platform, members, exact_owner in work:
        owner = by_path.get(parent_path)
        identity = exact_owner or (owner.get("target_id", owner.get("preexisting_id")) if owner else
            root_parent.object if root_parent is not None and root_collection == "Effects" else None)
        key = (identity or parent_path, platform)
        if key in combined:
            combined[key][2].extend(members)
        else:
            combined[key] = [parent_path, platform, list(members), exact_owner]
    for parent_path, platform, members, exact_owner in combined.values():
        if not any(any(prop["name"] == "Render" for prop in spec["properties"]) for spec in members):
            continue
        owner = by_path.get(parent_path)
        owner_id = exact_owner or (owner.get("target_id", owner.get("preexisting_id")) if owner else
                    root_parent.object if root_parent is not None and root_collection == "Effects" else None)
        owner_class = owner.get("class_id", owner.get("documented_list_owner_class")) if owner else None
        if owner_id is None and owner_class is None:
            raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "Render requires its exact documented owner class")
        catalog = r._read_object_type_catalog(read)
        slot_types = [row.as_dict() for row in catalog if row.class_id == 5505040 and row.name == "EffectSlot"]
        if len(slot_types) != 1:
            raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "Fresh exact EffectSlot class is required")
        source = (resolve_live_list_evidence(version, owner_id, "Effects", read=read) if owner_id else
                  resolve_class_list_evidence(version, owner_class, "Effects"))
        if source["declaration"]["element_classes"] != [{"name": "EffectSlot", "class_id": 5505040}]:
            raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "Effects chain class differs from its pinned declaration")
        constructing = [spec for spec in members if spec.get("collection") == "Effects"]
        mode = constructing[0].get("list_mode", "append") if constructing else "existing"
        before = (r._read_object_list(owner_id, "Effects", fields=[*r.OBJECT_LIST_SNAPSHOT_FIELDS, "classId", "@Effect", "@Bypass", "@Render"],
                    read=read, platform=platform, version=version) if owner_id else [])
        metadata, snapshots, entries = [], [], []
        for row in before:
            if row.get("classId") != 5505040 or not r._same_identity(r._reference_identity(row.get("owner")), owner_id):
                raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "Every actual EffectSlot needs its exact class and owner")
            if not all(r._has_field(row, field) for field in ("Render", "Bypass", "Effect")) or any(
                    type(r._field_value(row, field)) is not bool for field in ("Render", "Bypass")):
                raise r.OperationContractError("INVALID_READBACK", "Render chain requires complete Boolean/reference projections")
            snapshots.append({"object_id": row["id"], "fields": list(row), "before": row, "after_changes": {}})
            for name in ("Effect", "Bypass", "Render"):
                info = r._read_property_info(read, object_id=row["id"], name=name)
                metadata.append({"scope": {"object_id": row["id"]}, "field": name, "raw": dict(info.raw), "normalized": info.as_dict()})
            if mode != "replaceAll":
                entries.append({"key": row["id"], "render_before": r._field_value(row, "Render"), "render_intent": None})
        for spec in members:
            existing_id = spec.get("preexisting_id", spec.get("target_id"))
            scope = {"object_id": existing_id} if existing_id else {"class_id": spec["class_id"]}
            info = r._read_property_info(read, **scope, name="Render")
            if info.type.casefold() not in {"bool", "boolean"} or (not existing_id and type(info.raw.get("default")) is not bool):
                raise r.OperationContractError("INVALID_METADATA", "New Render intent needs its actual Boolean class default")
            metadata.append({"scope": scope, "field": "Render", "raw": dict(info.raw), "normalized": info.as_dict()})
            for name in ("Effect", "Bypass"):
                companion = r._read_property_info(read, **scope, name=name)
                metadata.append({"scope": scope, "field": name, "raw": dict(companion.raw), "normalized": companion.as_dict()})
            intent = next((prop["value"] for prop in spec["properties"] if prop["name"] == "Render"), None)
            entry = {"key": spec["request_path"], "render_before": info.raw.get("default"), "render_intent": intent}
            if existing_id:
                matches = [entry for entry in entries if r._same_identity(entry["key"], existing_id)]
                if len(matches) != 1:
                    raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "Merged slot must occur once in its owner chain")
                matches[0].update(render_intent=intent)
            else:
                entries.append(entry)
        planned = plan_chain(entries)
        for change in planned["derived"]:
            spec = by_path.get(change["key"])
            if spec:
                native_nodes[spec["request_path"]]["@Render"] = True
                spec["properties"].append({"name": "Render", "value": True, "metadata_type": "bool", "derived": True,
                    "condition_source": "effect-render-prefix"})
            else:
                snapshot = next(item for item in snapshots if r._same_identity(item["object_id"], change["key"]))
                if r._reference_value_is_null(r._field_value(snapshot["before"], "Effect")):
                    raise r.OperationContractError("REFERENCE_ACTIVATION_REQUIRED", "A derived rendered predecessor needs its actual Effect reference")
                snapshot["after_changes"]["Render"] = True
        # Explicit changes to existing members are included in the same complete
        # chain proof. Native coupling is expected, never inferred as a pass.
        for spec in members:
            for snapshot in snapshots:
                if r._same_identity(snapshot["object_id"], spec.get("preexisting_id", spec.get("target_id"))):
                    snapshot["after_changes"].update({prop["name"]: prop["value"] for prop in spec["properties"]})
        chains.append({**planned, "version": version, "platform": platform, "source": source,
            "owner_id": owner_id, "mode": mode, "before_order": [row["id"] for row in before],
            "metadata": metadata, "snapshots": snapshots, "slot_type": slot_types[0]})
    chains.extend(prepare_legacy(specs, native_nodes, version=version, read=read))
    return chains


def prepare_legacy(specs, native_nodes, *, version, read):
    from . import operation_registry as r
    from .documented_list_fields import load_catalog
    if version not in {"2021.1", "2022.1"}:
        return []
    catalog = load_catalog(version)
    chains = []
    for spec in specs:
        intents = {prop["name"]: prop["value"] for prop in spec["properties"]}
        if not any(name in intents for name in (f"RenderEffect{i}" for i in range(4))):
            continue
        identity = spec.get("target_id", spec.get("preexisting_id"))
        fields = [*r.OBJECT_LIST_SNAPSHOT_FIELDS, "classId", *[field for i in range(4)
            for field in (f"Effect{i}", f"BypassEffect{i}", f"RenderEffect{i}")]]
        before = r._read_object_id_rows(identity, fields=fields, read=read, platform=spec.get("platform")) if identity else []
        if identity and (len(before) != 1 or not r._same_identity(before[0].get("id"), identity)):
            raise r.OperationContractError("INVALID_READBACK", "Legacy Render chain needs one exact owner")
        class_id = before[0].get("classId") if identity else spec["class_id"]
        classes = [row for row in catalog["classes"] if row["class_id"] == class_id
                   and all(f"Effect{i}" in row["scalar_references"] for i in range(4))]
        if not classes:
            continue  # no global matching by a plug-in property name
        source_class = classes[0]
        live_types = [row.as_dict() for row in r._read_object_type_catalog(read)
                      if row.class_id == class_id and row.name == source_class["name"]]
        if len(live_types) != 1:
            raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "Legacy owner needs its fresh exact documented class")
        metadata, entries = [], []
        references = {row["name"]: row for row in spec["references"]}
        scope = {"object_id": identity} if identity else {"class_id": class_id}
        for i in range(4):
            for field in (f"Effect{i}", f"BypassEffect{i}", f"RenderEffect{i}"):
                info = r._read_property_info(read, **scope, name=field)
                metadata.append({"scope": scope, "field": field, "raw": dict(info.raw), "normalized": info.as_dict()})
                if field.startswith(("Render", "Bypass")) and info.type.casefold() not in {"bool", "boolean"}:
                    raise r.OperationContractError("INVALID_METADATA", "Legacy render/bypass state must be Boolean")
                if identity and not r._has_field(before[0], field):
                    raise r.OperationContractError("INVALID_READBACK", "Legacy chain projection is incomplete")
                if field.startswith("Render"):
                    value = r._field_value(before[0], field) if identity else info.raw.get("default")
                    if type(value) is not bool:
                        raise r.OperationContractError("INVALID_READBACK", "Legacy Render needs observed Boolean state or a fresh actual default")
                    entries.append({"key": field, "render_before": value, "render_intent": intents.get(field)})
        plan = plan_chain(entries)
        changes = {name: value for name, value in intents.items() if name in fields}
        for change in plan["derived"]:
            field = change["key"]
            reference = "Effect" + field[-1]
            supplied = references.get(reference)
            if not supplied and (not identity or r._reference_value_is_null(r._field_value(before[0], reference))):
                raise r.OperationContractError("REFERENCE_ACTIVATION_REQUIRED", "A rendered predecessor needs its actual bound Effect reference")
            changes[field] = True
            # Native setProperty already performs the owner-chain change; graph
            # rows may state it explicitly and verify the identical final intent.
            if native_nodes.get(spec["request_path"]) is not None:
                native_nodes[spec["request_path"]]["@" + field] = True
                spec["properties"].append({"name": field, "value": True, "metadata_type": "bool", "derived": True,
                    "condition_source": "effect-render-prefix"})
        chains.append({**plan, "kind": "legacy-scalars", "version": version, "platform": spec.get("platform"),
            "source": {"catalog_sha256": catalog["catalog_sha256"], "class": source_class}, "owner_id": identity,
            "mode": "existing", "metadata": metadata, "slot_type": live_types[0],
            "snapshots": [{"object_id": identity, "fields": fields, "before": before[0], "after_changes": changes}] if identity else []})
    return chains


def prepare_property(*, object_id, field, value, version, platform, read):
    """Adapter for the named property route; native coupling stays one call."""
    if field != "Render" and field not in {f"RenderEffect{i}" for i in range(4)}:
        return []
    spec = {"request_path": "$.property", "target_id": object_id, "existing_target": True,
        "properties": [{"name": field, "value": value}], "references": [], "platform": platform}
    return prepare_graph([spec], {}, version=version, read=read)


def chain_assertions(chains, *, read, after_write=False, edits=()):
    from . import operation_registry as r
    from .documented_list_fields import resolve_class_list_evidence, resolve_live_list_evidence
    from .object_graph_paths import expected_snapshot
    assertions = []
    for chain in chains:
        try:
            source = chain["source"]
            legacy = chain.get("kind") == "legacy-scalars"
            if legacy:
                from .documented_list_fields import load_catalog
                catalog = load_catalog(chain["version"])
                source_match = catalog["catalog_sha256"] == source["catalog_sha256"] and source["class"] in catalog["classes"]
            else:
                current = (resolve_live_list_evidence(chain["version"], chain["owner_id"], "Effects", read=read)
                if chain["owner_id"] else resolve_class_list_evidence(chain["version"], source["scope"]["class_id"], "Effects"))
            # Owner names/paths can change only through the ordinary prepared
            # identity/path guards; the source class/declaration remains exact.
                source_match = all(current[key] == source[key] for key in source if key != "scope") and current["scope"]["class_id"] == source["scope"]["class_id"]
            passed = source_match and [row.as_dict() for row in r._read_object_type_catalog(read)
                if row.class_id == chain["slot_type"]["classId"] and row.name == chain["slot_type"]["name"]] == [chain["slot_type"]]
            if not legacy and chain["owner_id"] and (not after_write or chain["mode"] == "existing"):
                rows = r._read_object_list(chain["owner_id"], "Effects", fields=r.OBJECT_LIST_SNAPSHOT_FIELDS,
                    read=read, platform=chain["platform"], version=chain["version"])
                passed = passed and [row["id"] for row in rows] == chain["before_order"]
            for field in chain["metadata"]:
                info = r._read_property_info(read, **field["scope"], name=field["field"])
                passed = passed and dict(info.raw) == field["raw"] and info.as_dict() == field["normalized"]
            for snapshot in chain["snapshots"]:
                if after_write and chain["mode"] == "replaceAll":
                    continue  # ordinary replacement verification proves deletion
                actual = r._read_object_id_rows(snapshot["object_id"], fields=snapshot["fields"], read=read, platform=chain["platform"])
                expected = deepcopy(snapshot["before"])
                if after_write:
                    expected = expected_snapshot(expected, edits=edits, read_row=lambda identity: r._read_object_id_rows(identity, fields=r.IDENTITY_RETURN_FIELDS, read=read)[0])
                    for name, value in snapshot["after_changes"].items():
                        expected["@" + name] = value
                selected = {name: r._reference_identity(r._field_value(expected, name)) for name in
                    ([f"Effect{i}" for i in range(4)] if legacy else ["Effect"]) if r._has_field(expected, name)}
                strip = lambda row: {key: value for key, value in row.items() if key.lstrip("@") not in selected}
                passed = passed and len(actual) == 1 and r._native_snapshot_equal([strip(expected)], [strip(row) for row in actual]) and all(
                    r._reference_requirement_matches(actual[0], name, value) for name, value in selected.items())
            evidence = {"source_matches": source_match, "chain": chain}
        except (r.OperationContractError, ValueError, KeyError, TypeError) as exc:
            passed, evidence = False, {"error": str(exc)}
        assertions.append({"name": "Effect Render chain metadata and complete stored state match prepared intent", "passed": bool(passed), "evidence": evidence})
    return assertions
