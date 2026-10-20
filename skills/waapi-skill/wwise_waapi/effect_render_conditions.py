"""Owned Effect rendering conditions shared by creation and field edits.

The five pinned Authoring Help ``rendering_effects`` sections specify that
rendering a later Effect also renders its predecessors. Bypass precedence
concerns processing; it does not make a stored Boolean combination invalid.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
from copy import deepcopy
from .canonical import canonical_sha256


# Exact installed English Help member evidence, extracted without starting Wwise.
# 2024 source is the installed 9056 patch, not an invented older Help archive.
AUTHORITY = {
    "2021.1": ("2021.1.14.8108", "ch15s02s03s04.html", "409a34fbb7a36a4e1afc799c478286cd5d015cd01f2b443e0e892cc194214aa7"),
    "2022.1": ("2022.1.19.8584", "ch16s02s03s04.html", "f7aea2c6bb41365fcda0b6f7742a69331ed3e5d4f8a625012a9c141a92b26ea2"),
    "2023.1": ("2023.1.19.8928", "ch23.html", "af60eb6dcd7ba4f881f45f16077784a9f0f5f0544d9f47249847e3df06e32aac"),
    "2024.1": ("2024.1.13.9056", "ch24.html", "00549a9cfe93df65d22c3cc87115652feb20e506860e93337d3dc627b6f7088c"),
    "2025.1": ("2025.1.7.9143", "ch25.html", "1eb0c622255539a0343285cba60884f613f9d8c4c3cfd6884168c8f7257355cf"),
}


def source_authority(version):
    build, member, digest = AUTHORITY[version]
    return {"build": build, "archive": "Authoring/Help/WwiseHelp_en.chm", "member": member,
        "anchor": "rendering_effects", "html_sha256": digest,
        "rule": "rendering a later Effect automatically renders every preceding Effect",
        "stored_flag_verification_only": True, "native_acceptance": False}


# Exact Root-owned public Gateway diagnostic; stored flags only. Other versions
# require their own observation, not a borrowed version-family inference.
CLEAR_SUFFIX_OBSERVATIONS = {
    "2023.1": {"version": "2023.1", "candidate": "a4936b071bafbc3997eb9b4bab00f06429e9aa6e",
        "observation_sha256": "0274570cb87476bf13305807f9d283c1d314673a8af81b0e4f9fa8e7348093ee",
        "observed_before": [True, True], "observed_after": [False, False],
        "rule": "clearing a Render flag clears all subsequent stored Render flags",
        "acceptance_scope": "stored_slot_state_not_rendered_audio"},
    "2024.1": {"version": "2024.1", "candidate": "a4936b071bafbc3997eb9b4bab00f06429e9aa6e",
        "observation_sha256": "d8c15c727173d5799d8aa44f5ee061c4a91ff37edfe0090329f3f74f4c26269f",
        "observed_before": [True, True], "observed_after": [False, False],
        "rule": "clearing a Render flag clears all subsequent stored Render flags",
        "acceptance_scope": "stored_slot_state_not_rendered_audio"},
    "2025.1": {"version": "2025.1", "candidate": "98c1f74ff9bf2e7fbec91689980ead53a3887998",
        "observation_sha256": "bb8e143ef5b6aacbf02f10aedf042fe957115fcc860c71e346e6868aa17f0be8",
        "observed_before": [True, True], "observed_after": [False, False],
        "rule": "clearing a Render flag clears all subsequent stored Render flags",
        "acceptance_scope": "stored_slot_state_not_rendered_audio"},
}


class EffectRenderConditionError(ValueError):
    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def plan_chain(entries: Sequence[Mapping[str, Any]], *, version: str) -> dict[str, Any]:
    """Plan explicit intent and observed induced flags without changing Bypass."""
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
    suffix_rule = CLEAR_SUFFIX_OBSERVATIONS.get(version)
    for i, entry in enumerate(entries):
        if entry.get("render_intent") is False and any(value is True for value in final[i + 1:]):
            if suffix_rule is None:
                raise EffectRenderConditionError("EFFECT_RENDER_SUFFIX_OBSERVATION_REQUIRED",
                    "Clearing a Render flag before a retained rendered successor requires a separately observed suffix rule.",
                    details={"member": entry["key"], "mutation_dispatched": False,
                             "remaining_obligation": "observe native stored-flag clearing/suffix behavior"})
            for j in range(i + 1, len(entries)):
                if final[j] is True:
                    derived.append({"key": entries[j]["key"], "before": entries[j].get("render_before"), "after": False})
                    final[j] = False
    result = {"derived": derived, "bypass_policy": "preserve_stored_flags; Bypass takes precedence during processing",
            "acceptance_scope": "stored_slot_state_not_rendered_audio"}
    if any(change["after"] is False for change in derived):
        result["suffix_rule"] = deepcopy(suffix_rule)
    return result



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
    views = {}
    def view_for(selector):
        from .edit_history_business import capture_field_read_platform
        if selector not in views:
            views[selector] = capture_field_read_platform(version, selector, read=read)
        proof = views[selector]
        return proof, proof["platform_id"] if proof["status"] == "certified" else selector
    for spec in specs:
        if not spec.get("existing_target") or not any(prop["name"] == "Render" for prop in spec["properties"]):
            continue
        object_id = spec["target_id"]
        _view, read_platform = view_for(spec.get("platform"))
        rows = r._read_object_id_rows(object_id, fields=[*r.OBJECT_LIST_SNAPSHOT_FIELDS, "classId"], read=read, platform=read_platform)
        if len(rows) != 1 or not r._same_identity(rows[0].get("id"), object_id):
            raise r.OperationContractError("INVALID_READBACK", "Render field source must resolve exactly once")
        if rows[0].get("classId") != 5505040:
            continue  # an unrelated plug-in field named Render is not an EffectSlot
        owner_id = r._reference_identity(rows[0].get("owner"))
        if not r._valid_object_id(owner_id):
            raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "EffectSlot Render needs its actual owner GUID")
        exact.setdefault((owner_id, spec.get("platform")), []).append(spec)
    chains = []
    observed_members = 0
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
        view, platform = view_for(platform)
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
        observed_members += len(before) + sum(not spec.get("preexisting_id", spec.get("target_id")) for spec in members)
        if observed_members > r.OBJECT_LIST_MAX_SUBTREE_NODES:
            raise r.OperationContractError("LIST_SNAPSHOT_LIMIT_EXCEEDED", "Effect Render observations exceed the existing aggregate List snapshot bound")
        metadata, snapshots, entries, targets = [], [], [], []
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
            effect_id = r._reference_identity(r._field_value(row, "Effect"))
            if mode != "replaceAll" and not r._reference_value_is_null(r._field_value(row, "Effect")):
                if not r._valid_object_id(effect_id):
                    raise r.OperationContractError("INVALID_READBACK", "A retained Effect needs its canonical GUID or explicit native null")
                if not any(r._same_identity(target["before"]["id"], effect_id) for target in targets):
                    fields = [*r.OBJECT_LIST_SNAPSHOT_FIELDS, "classId"]
                    actual = r._read_object_id_rows(effect_id, fields=fields, read=read, platform=platform)
                    if len(actual) != 1 or not r._same_identity(actual[0].get("id"), effect_id):
                        raise r.OperationContractError("INVALID_READBACK", "Retained Effect target must independently resolve once")
                    targets.append({"fields": fields, "before": actual[0]})
            if mode != "replaceAll":
                entries.append({"key": row["id"], "render_before": r._field_value(row, "Render"), "render_intent": None})
        new_defaults = {}
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
                if not existing_id and name == "Bypass":
                    if companion.type.casefold() not in {"bool", "boolean"} or type(companion.raw.get("default")) is not bool:
                        raise r.OperationContractError("INVALID_METADATA", "New Bypass state needs its actual Boolean default")
                    new_defaults[spec["request_path"]] = {"Render": info.raw["default"], "Bypass": companion.raw["default"]}
            intent = next((prop["value"] for prop in spec["properties"] if prop["name"] == "Render"), None)
            entry = {"key": spec["request_path"], "render_before": info.raw.get("default"), "render_intent": intent}
            if existing_id:
                matches = [entry for entry in entries if r._same_identity(entry["key"], existing_id)]
                if len(matches) != 1:
                    raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "Merged slot must occur once in its owner chain")
                matches[0].update(render_intent=intent)
            else:
                entries.append(entry)
        planned = plan_chain(entries, version=version)
        for change in planned["derived"]:
            spec = by_path.get(change["key"])
            if spec:
                native_nodes[spec["request_path"]]["@Render"] = change["after"]
                spec["properties"].append({"name": "Render", "value": change["after"], "metadata_type": "bool", "derived": True,
                    "condition_source": "effect-render-prefix" if change["after"] else "effect-render-suffix"})
            else:
                snapshot = next(item for item in snapshots if r._same_identity(item["object_id"], change["key"]))
                if change["after"] is True and r._reference_value_is_null(r._field_value(snapshot["before"], "Effect")):
                    raise r.OperationContractError("REFERENCE_ACTIVATION_REQUIRED", "A derived rendered predecessor needs its actual Effect reference")
                snapshot["after_changes"]["Render"] = change["after"]
        # Explicit changes to existing members are included in the same complete
        # chain proof. Native coupling is expected, never inferred as a pass.
        for spec in specs:
            if spec.get("platform") != members[0].get("platform"):
                continue
            for snapshot in snapshots:
                if r._same_identity(snapshot["object_id"], spec.get("preexisting_id", spec.get("target_id"))):
                    snapshot["after_changes"].update({prop["name"]: prop["value"] for prop in spec["properties"]})
                    references = snapshot.setdefault("reference_changes", {})
                    for reference in spec["references"]:
                        if reference.get("condition_guard"):
                            continue
                        # A planned result is not a clear: retain its sealed request path
                        # until the ordinary graph verifier has associated actual GUIDs.
                        references[reference["name"]] = (
                            {"target_request_path": reference["target_request_path"]}
                            if "target_request_path" in reference else {"target_id": reference["target_id"]})
        for spec in members:
            for name, value in new_defaults.get(spec["request_path"], {}).items():
                if not any(prop["name"] == name for prop in spec["properties"]):
                    spec["properties"].append({"name": name, "value": value, "metadata_type": "bool", "observed_class_default": True})
        chains.append({**planned, "authority": source_authority(version), "version": version, "platform": platform, "source": source,
            "field_read_platform": view, "owner_id": owner_id, "mode": mode, "before_order": [row["id"] for row in before],
            "metadata": metadata, "snapshots": snapshots, "slot_type": slot_types[0], "targets": targets})
    chains.extend(prepare_legacy(specs, native_nodes, version=version, read=read))
    return chains


def prepare_legacy(specs, native_nodes, *, version, read, history_targets=True):
    from . import operation_registry as r
    from .documented_list_fields import load_catalog
    if version not in {"2021.1", "2022.1"}:
        return []
    catalog = load_catalog(version)
    chains = []
    # Reserve the existing four-slot scope for every potential owner before any
    # optional target read. An unavailable history witness never expands or
    # rejects the source operation's existing aggregate bound.
    target_budget = max(0, r.OBJECT_LIST_MAX_SUBTREE_NODES - 4 * sum(
        any(prop["name"] in {f"RenderEffect{i}" for i in range(4)} for prop in spec["properties"])
        for spec in specs))
    for spec in specs:
        intents = {prop["name"]: prop["value"] for prop in spec["properties"]}
        if not any(name in intents for name in (f"RenderEffect{i}" for i in range(4))):
            continue
        identity = spec.get("target_id", spec.get("preexisting_id"))
        fields = [*r.OBJECT_LIST_SNAPSHOT_FIELDS, "classId", *[field for i in range(4)
            for field in (f"Effect{i}", f"BypassEffect{i}", f"RenderEffect{i}")]]
        from .edit_history_business import capture_field_read_platform
        view = capture_field_read_platform(version, spec.get("platform"), read=read)
        platform = view["platform_id"] if view["status"] == "certified" else spec.get("platform")
        before = r._read_object_id_rows(identity, fields=fields, read=read, platform=platform) if identity else []
        if identity and (len(before) != 1 or not r._same_identity(before[0].get("id"), identity)):
            raise r.OperationContractError("INVALID_READBACK", "Legacy Render chain needs one exact owner")
        if 4 * (len(chains) + 1) > r.OBJECT_LIST_MAX_SUBTREE_NODES:
            raise r.OperationContractError("LIST_SNAPSHOT_LIMIT_EXCEEDED", "Legacy Render observations exceed the existing aggregate List snapshot bound")
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
        metadata, entries, targets = [], [], []
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
                if not identity and field.startswith("Bypass") and type(info.raw.get("default")) is not bool:
                    raise r.OperationContractError("INVALID_METADATA", "New legacy Bypass state needs its actual Boolean class default")
                if field.startswith("Render"):
                    value = r._field_value(before[0], field) if identity else info.raw.get("default")
                    if type(value) is not bool:
                        raise r.OperationContractError("INVALID_READBACK", "Legacy Render needs observed Boolean state or a fresh actual default")
                    entries.append({"key": field, "render_before": value, "render_intent": intents.get(field)})
        target_observation = {"status": "certified"}
        try:
            if identity and history_targets:
                for i in range(4):
                    value = r._field_value(before[0], f"Effect{i}")
                    if r._reference_value_is_null(value):
                        continue
                    effect_id = r._reference_identity(value)
                    if not r._valid_object_id(effect_id):
                        raise r.OperationContractError("INVALID_READBACK", "Retained legacy Effect requires its exact GUID or explicit null")
                    if not any(r._same_identity(item["before"]["id"], effect_id) for item in targets):
                        if target_budget <= 0:
                            raise r.OperationContractError("RESULT_TOO_LARGE", "Optional legacy history targets exceed the existing aggregate snapshot bound")
                        target_budget -= 1
                        target_fields = [*r.OBJECT_LIST_SNAPSHOT_FIELDS, "classId"]
                        rows = r._read_object_id_rows(effect_id, fields=target_fields, read=read, platform=platform)
                        if len(rows) != 1 or not r._same_identity(rows[0].get("id"), effect_id):
                            raise r.OperationContractError("INVALID_READBACK", "Retained legacy Effect must independently resolve once")
                        targets.append({"fields": target_fields, "before": rows[0]})
        except r.OperationContractError as exc:
            if exc.error_code not in {"READBACK_FAILED", "INVALID_READBACK", "RESULT_TOO_LARGE"}:
                raise
            # This additional witness is optional history evidence. The existing
            # legacy source verifier still owns all actual owner-field effects.
            target_observation = {"status": "unobserved", "error": exc.as_dict()}
        plan = plan_chain(entries, version=version)
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
        chains.append({**plan, "authority": source_authority(version), "kind": "legacy-scalars", "version": version, "platform": platform, "field_read_platform": view,
            "source": {"catalog_sha256": catalog["catalog_sha256"], "class": source_class}, "owner_id": identity,
            "mode": "existing", "metadata": metadata, "slot_type": live_types[0], "targets": targets,
            **({"target_observation": target_observation} if history_targets else {}),
            "snapshots": [{"object_id": identity, "fields": fields, "before": before[0], "after_changes": changes}] if identity else []})
    return chains


def prepare_property(*, object_id, field, value, version, platform, read):
    """Adapter for the named property route; native coupling stays one call."""
    if field != "Render" and field not in {f"RenderEffect{i}" for i in range(4)}:
        return []
    spec = {"request_path": "$.property", "target_id": object_id, "existing_target": True,
        "properties": [{"name": field, "value": value}], "references": [], "platform": platform}
    return prepare_graph([spec], {}, version=version, read=read)


def chain_assertions(chains, *, read, after_write=False, edits=(), resolved_ids=None):
    from . import operation_registry as r
    from .documented_list_fields import resolve_class_list_evidence, resolve_live_list_evidence
    from .object_graph_paths import expected_snapshot
    assertions = []
    def read_identity(identity):
        rows = r._read_object_id_rows(identity, fields=r.IDENTITY_RETURN_FIELDS, read=read)
        if len(rows) != 1 or not r._same_identity(rows[0].get("id"), identity):
            raise ValueError("Render preservation identity must resolve once")
        return rows[0]
    for chain in chains:
        try:
            observed = {"metadata": [], "snapshots": [], "targets": []}
            source = chain["source"]
            legacy = chain.get("kind") == "legacy-scalars"
            if legacy:
                from .documented_list_fields import load_catalog
                catalog = load_catalog(chain["version"])
                source_match = catalog["catalog_sha256"] == source["catalog_sha256"] and source["class"] in catalog["classes"]
                observed["source"] = {"catalog_sha256": catalog["catalog_sha256"], "class": source["class"]}
            else:
                current = (resolve_live_list_evidence(chain["version"], chain["owner_id"], "Effects", read=read)
                if chain["owner_id"] else resolve_class_list_evidence(chain["version"], source["scope"]["class_id"], "Effects"))
            # Owner names/paths can change only through the ordinary prepared
            # identity/path guards; the source class/declaration remains exact.
                source_match = all(current[key] == source[key] for key in source if key != "scope") and current["scope"]["class_id"] == source["scope"]["class_id"]
                observed["source"] = current
            types = [row.as_dict() for row in r._read_object_type_catalog(read)
                if row.class_id == chain["slot_type"]["classId"] and row.name == chain["slot_type"]["name"]]
            observed["slot_types"] = types
            passed = source_match and chain["authority"] == source_authority(chain["version"]) and types == [chain["slot_type"]]
            if not legacy and chain["owner_id"] and (not after_write or chain["mode"] == "existing"):
                rows = r._read_object_list(chain["owner_id"], "Effects", fields=r.OBJECT_LIST_SNAPSHOT_FIELDS,
                    read=read, platform=chain["platform"], version=chain["version"])
                observed["order"] = [row["id"] for row in rows]
                passed = passed and [row["id"] for row in rows] == chain["before_order"]
            for field in chain["metadata"]:
                if (after_write and chain["mode"] == "replaceAll" and field["scope"].get("object_id") in chain["before_order"]):
                    continue  # sealed old GUIDs must be deleted by the replacement verifier
                info = r._read_property_info(read, **field["scope"], name=field["field"])
                observed["metadata"].append({"scope": field["scope"], "field": field["field"],
                    "raw": dict(info.raw), "normalized": info.as_dict()})
                passed = passed and r._native_snapshot_equal(dict(info.raw), field["raw"]) and r._native_snapshot_equal(info.as_dict(), field["normalized"])
            for snapshot in chain["snapshots"]:
                if after_write and chain["mode"] == "replaceAll":
                    continue  # ordinary replacement verification proves deletion
                actual = r._read_object_id_rows(snapshot["object_id"], fields=snapshot["fields"], read=read, platform=chain["platform"])
                observed["snapshots"].append({"object_id": snapshot["object_id"], "rows": actual})
                expected = deepcopy(snapshot["before"])
                if after_write:
                    expected = expected_snapshot(expected, edits=edits, read_row=read_identity)
                    for name, value in snapshot["after_changes"].items():
                        expected[name if name in expected else "@" + name] = value
                selected = {name: r._reference_identity(r._field_value(expected, name)) for name in
                    (chain.get("reference_fields", [f"Effect{i}" for i in range(4)]) if legacy else ["Effect"]) if r._has_field(expected, name)}
                if after_write:
                    for name, intent in snapshot.get("reference_changes", {}).items():
                        if "target_request_path" in intent:
                            path = intent["target_request_path"]
                            identity = resolved_ids.get(path) if isinstance(resolved_ids, dict) else None
                            if (not r._valid_object_id(identity) or r._reference_value_is_null(identity)
                                    or sum(r._same_identity(value, identity) for value in resolved_ids.values()) != 1):
                                raise ValueError("Planned Render reference lacks one canonical graph result association")
                            selected[name] = identity
                        else:
                            if set(intent) != {"target_id"}:
                                raise ValueError("Render reference intent is malformed")
                            selected[name] = intent["target_id"]
                strip = lambda row: {key: value for key, value in row.items() if key.lstrip("@") not in selected}
                passed = passed and len(actual) == 1 and r._native_snapshot_equal([strip(expected)], [strip(row) for row in actual]) and all(
                    r._reference_requirement_matches(actual[0], name, value) for name, value in selected.items())
            construction = chain.get("construction")
            if after_write and construction:
                rows = r._read_object_path_rows(construction["path"], fields=construction["fields"], read=read, platform=chain["platform"])
                if len(rows) != 1 or not r._valid_object_id(rows[0].get("id")):
                    raise ValueError("New import Render owner must resolve by its one exact declared path")
                identity = rows[0]["id"]
                actual = r._read_object_id_rows(identity, fields=construction["fields"], read=read, platform=chain["platform"])
                parents = r._read_object_path_rows(construction["parent_path"], fields=r.IDENTITY_RETURN_FIELDS, read=read)
                passed = passed and len(actual) == len(parents) == 1 and r._native_snapshot_equal(actual, rows)
                if passed:
                    row = actual[0]
                    passed = (row.get("classId") == construction["class_id"] and row.get("type") == construction["type"]
                        and r._same_identity(r._reference_identity(row.get("parent")), parents[0].get("id")))
                    for name, value in construction["expected"].items():
                        passed = passed and r._has_field(row, name) and (
                            r._reference_requirement_matches(row, name, value) if name in construction["reference_fields"] else
                            r._typed_value_equal(r._field_value(row, name), value, construction["metadata_types"][name]))
            optional_targets = legacy and "target_observation" in chain
            if legacy:
                observed["targets_complete"] = not optional_targets or chain["target_observation"]["status"] == "certified"
            for target in chain.get("targets", []):
                try:
                    actual = r._read_object_id_rows(target["before"]["id"], fields=target["fields"], read=read, platform=chain["platform"])
                    observed["targets"].append({"object_id": target["before"]["id"], "rows": actual})
                    expected = target["before"]
                    if after_write:
                        expected = expected_snapshot(expected, edits=edits, read_row=read_identity)
                    target_matches = r._native_snapshot_equal(actual, [expected])
                    if optional_targets:
                        observed["targets_complete"] = observed["targets_complete"] and target_matches
                    else:
                        passed = passed and target_matches
                except r.OperationContractError as exc:
                    if not optional_targets or exc.error_code not in {"READBACK_FAILED", "INVALID_READBACK", "RESULT_TOO_LARGE"}:
                        raise
                    observed["targets_complete"] = False
                    observed["targets"].append({"object_id": target["before"]["id"], "error": exc.as_dict()})
            target_conditions = r._reference_target_condition_assertions(chain, read=read, after_write=after_write)
            passed = passed and all(item["passed"] for item in target_conditions)
            evidence = {"source_matches": source_match, "chain": chain, "target_conditions": target_conditions,
                "prepared_chain_sha256": canonical_sha256(chain), "after_write": after_write,
                "observation": observed}
        except (r.OperationContractError, ValueError, KeyError, TypeError) as exc:
            passed, evidence = False, {"error": str(exc)}
        assertions.append({"name": "Effect Render chain metadata and complete stored state match prepared intent",
            "kind": "effect_render_chain_observation", "passed": bool(passed), "evidence": evidence})
    return assertions


def require_import_adapter(*, version, class_id, properties):
    """Keep the real legacy owner-field gap explicit rather than dispatch unsafe intent."""
    if version not in {"2021.1", "2022.1"}:
        return
    selected = [row["name"] for row in properties if row["name"] in {f"RenderEffect{i}" for i in range(4)}]
    if not selected:
        return
    from .documented_list_fields import load_catalog
    matches = [row for row in load_catalog(version)["classes"] if row["class_id"] == class_id
        and all(f"Effect{i}" in row["scalar_references"] for i in range(4))]
    if matches:
        raise EffectRenderConditionError("EFFECT_RENDER_IMPORT_CHAIN_PENDING",
            "This import's owner Render fields require the complete effect-chain adapter before they can be executed together with media changes.",
            details={"fields": selected, "source_member": matches[0]["source_member"], "mutation_dispatched": False,
                "remaining_obligation": "audio.import and audio.importTabDelimited owner Render chain observations",
                "separate_supported_operation": "object.setProperty"})


def legacy_import_owner(*, version, class_id, properties):
    if version not in {"2021.1", "2022.1"} or not any(
            row["name"] in {f"RenderEffect{i}" for i in range(4)} for row in properties):
        return False
    from .documented_list_fields import load_catalog
    return any(row["class_id"] == class_id and row["name"] == "Sound"
        and all(f"Effect{i}" in row["scalar_references"] for i in range(4)) for row in load_catalog(version)["classes"])


def prepare_import(targets, *, version, operation, import_operation, read):
    """Adapt complete closed import occurrences to the shared owner-chain planner."""
    from . import operation_registry as r
    selected = [target for target in targets if target.get("legacy_effect_render")]
    if not selected:
        return {}
    from .edit_history_business import capture_field_read_platform
    view = capture_field_read_platform(version, None, read=read)
    platform = view.get("platform_id") if view["status"] == "certified" else None
    specs, native = [], {}
    for index, target in enumerate(selected):
        path = f"$.imports[{index}]"
        identity = target.get("preexisting_id") if import_operation == "useExisting" else None
        spec = {"request_path": path, "class_id": target["metadata_class_id"],
            "properties": target.setdefault("validated_properties", []),
            "references": target.setdefault("validated_references", []), "platform": platform}
        if identity:
            spec["target_id"] = identity
        specs.append(spec); native[path] = {}
    chains = prepare_legacy(specs, native, version=version, read=read, history_targets=False)
    if len(chains) != len(selected):
        raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "Every legacy import owner requires its exact documented class chain")
    for target, spec, chain in zip(selected, specs, chains, strict=True):
        identity = spec.get("target_id")
        if identity and (chain["slot_type"]["classId"] != target["metadata_class_id"]
                or chain["snapshots"][0]["before"].get("path") != target["canonical_target_path"]):
            raise r.OperationContractError("INVALID_READBACK", "Import Render owner class/path does not match its exact target")
        infos, cache = {}, {}
        scope = {"object_id": identity} if identity else {"class_id": target["metadata_class_id"]}
        properties, references = spec["properties"], spec["references"]
        desired = {row["name"].casefold(): row["target_id"] for row in references}
        for row in [*properties, *references]:
            info = r._read_property_info_cached(read, cache=cache, **scope, name=row["name"])
            infos[info.name.casefold()] = info
            if row in properties:
                r._require_object_property_value(info, row["value"])
                row["metadata_type"] = info.type
            else:
                r._require_object_reference_metadata(info)
                resolved = r._resolve_identity({"kind": "id", "value": row["target_id"]}, role="import Effect target", read=read)
                conditions = []
                r._require_reference_target_allowed(info, resolved, source_id=identity, read=read, platform=platform,
                    desired_references=desired, conditions=conditions, property_info_cache=cache, wwise_version=version)
                if conditions:
                    spec.setdefault("reference_target_conditions", []).extend(conditions)
        derived, required = {}, {}
        if identity:
            for info in tuple(infos.values()):
                r._apply_reference_activation_dependencies(info, read=read, object_id=identity,
                    property_specs=properties, property_info_by_name=infos, derived_properties=derived,
                    request_path=spec["request_path"], property_info_cache=cache,
                    _condition_sources=tuple(infos.values()), reference_requirements=required,
                    desired_references=desired, platform=platform, wwise_version=version)
            for name, value in required.items():
                if name.casefold() not in desired:
                    references.append({"name": name, "target_id": value, "condition_guard": True})
        else:
            from .new_object_defaults import class_default_evidence, NewObjectDefaultError
            try:
                evidence = class_default_evidence(infos=tuple(infos.values()), scope={"classId": target["metadata_class_id"]},
                    read_call=read, supplied_values={row["name"]: row["value"] for row in properties},
                    supplied_references={row["name"]: row["target_id"] for row in references},
                    validate_scalar=r._require_object_property_value, version=version)
            except NewObjectDefaultError as exc:
                raise r.OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
            for name, value in evidence["derived_properties"].items():
                properties.append({"name": name, "value": value, "metadata_type": evidence["metadata"][name]["type"], "derived": True})
            for name in evidence["metadata"]:
                infos[name.casefold()] = r._read_property_info_cached(read, cache=cache, **scope, name=name)
        # TSV input is immutable. Prefix coupling needs no extra column; other
        # activation writes require actual explicit user columns already admitted.
        if operation == "audio.importTabDelimited":
            supplied = {row["name"] for row in target.get("requested_dynamic_fields", [])}
            missing = [row["name"] for row in properties if row["name"] not in supplied
                and row.get("condition_source") != "effect-render-prefix"]
            if missing:
                raise r.OperationContractError("TAB_REFERENCE_DEPENDENCY_REQUIRES_COLUMN",
                    "The table requires explicit activation columns", details={"missing_properties": missing})
        for info in infos.values():
            chain["metadata"].append({"scope": scope, "field": info.name, "raw": dict(info.raw), "normalized": info.as_dict()})
        chain["reference_target_conditions"] = spec.get("reference_target_conditions", [])
        chain["reference_fields"] = list(dict.fromkeys([*[f"Effect{i}" for i in range(4)],
            *(info.name for info in infos.values() if r._metadata_is_reference(info))]))
        if identity:
            snapshot = chain["snapshots"][0]
            fields = r._dedupe_fields([*snapshot["fields"], *(info.name for info in infos.values())])
            rows = r._read_object_id_rows(identity, fields=fields, read=read, platform=platform)
            if len(rows) != 1 or any(not r._has_field(rows[0], info.name) for info in infos.values()):
                raise r.OperationContractError("INVALID_READBACK", "Import owner condition snapshot is incomplete")
            snapshot.update(fields=fields, before=rows[0])
            snapshot["after_changes"].update({row["name"]: row["value"] for row in properties})
            snapshot["after_changes"].update({row["name"]: row["target_id"] for row in references})
        else:
            metadata_types = {item["field"]: item["normalized"]["type"] for item in chain["metadata"]}
            reference_fields = chain["reference_fields"]
            expected = {item["field"]: item["raw"]["default"] for item in chain["metadata"] if "default" in item["raw"]}
            expected.update({row["name"]: row["value"] for row in properties})
            expected.update({row["name"]: row["target_id"] for row in references})
            chain["construction"] = {"path": target["canonical_target_path"], "class_id": target["metadata_class_id"],
                "type": target["metadata_object_type"], "parent_path": target["canonical_target_path"].rpartition("\\")[0],
                "fields": r._dedupe_fields([*r.IDENTITY_RETURN_FIELDS, "classId", "parent", *expected]),
                "expected": expected, "reference_fields": reference_fields, "metadata_types": metadata_types}
        target_ids = {row["target_id"] for row in references if row.get("target_id") is not None}
        if identity:
            for i in range(4):
                value = r._field_value(chain["snapshots"][0]["before"], f"Effect{i}")
                if not r._reference_value_is_null(value):
                    target_ids.add(r._reference_identity(value))
        chain["targets"] = []
        for target_id in target_ids:
            fields = [*r.OBJECT_LIST_SNAPSHOT_FIELDS, "classId"]
            rows = r._read_object_id_rows(target_id, fields=fields, read=read, platform=platform)
            if len(rows) != 1 or not r._same_identity(rows[0].get("id"), target_id):
                raise r.OperationContractError("INVALID_READBACK", "Import Effect target must independently resolve once")
            chain["targets"].append({"fields": fields, "before": rows[0]})
    if sum(4 + len(chain["targets"]) for chain in chains) > r.OBJECT_LIST_MAX_SUBTREE_NODES:
        raise r.OperationContractError("LIST_SNAPSHOT_LIMIT_EXCEEDED", "Import Render chain observations exceed the shared bound")
    return {"effect_render_chains": chains, "field_read_platform": view}
