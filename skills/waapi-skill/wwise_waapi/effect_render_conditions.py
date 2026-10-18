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
    chains = []
    for (parent_path, platform), members in groups.items():
        if not any(any(prop["name"] == "Render" for prop in spec["properties"]) for spec in members):
            continue
        owner = by_path.get(parent_path)
        owner_id = (owner.get("target_id", owner.get("preexisting_id")) if owner else
                    root_parent.object if root_parent is not None and root_collection == "Effects" else None)
        owner_class = owner.get("class_id", owner.get("documented_list_owner_class")) if owner else None
        if owner_id is None and owner_class is None:
            raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "Render requires its exact documented owner class")
        source = (resolve_live_list_evidence(version, owner_id, "Effects", read=read) if owner_id else
                  resolve_class_list_evidence(version, owner_class, "Effects"))
        if source["declaration"]["element_classes"] != [{"name": "EffectSlot", "class_id": 5505040}]:
            raise r.OperationContractError("EFFECT_RENDER_CHAIN_UNPROVED", "Effects chain class differs from its pinned declaration")
        mode = members[0].get("list_mode", "append")
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
            if mode != "replaceAll":
                entries.append({"key": row["id"], "render_before": r._field_value(row, "Render"), "render_intent": None})
        for spec in members:
            scope = {"object_id": spec["preexisting_id"]} if spec.get("preexisting_id") else {"class_id": spec["class_id"]}
            info = r._read_property_info(read, **scope, name="Render")
            if info.type.casefold() not in {"bool", "boolean"} or type(info.raw.get("default")) is not bool:
                raise r.OperationContractError("INVALID_METADATA", "New Render intent needs its actual Boolean class default")
            metadata.append({"scope": scope, "field": "Render", "raw": dict(info.raw), "normalized": info.as_dict()})
            intent = next((prop["value"] for prop in spec["properties"] if prop["name"] == "Render"), None)
            entry = {"key": spec["request_path"], "render_before": info.raw["default"], "render_intent": intent}
            if spec.get("preexisting_id"):
                matches = [entry for entry in entries if r._same_identity(entry["key"], spec["preexisting_id"])]
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
                if r._same_identity(snapshot["object_id"], spec.get("preexisting_id")):
                    snapshot["after_changes"].update({prop["name"]: prop["value"] for prop in spec["properties"]})
        chains.append({**planned, "version": version, "platform": platform, "source": source,
            "owner_id": owner_id, "mode": mode, "before_order": [row["id"] for row in before],
            "metadata": metadata, "snapshots": snapshots})
    return chains


def chain_assertions(chains, *, read, after_write=False, edits=()):
    from . import operation_registry as r
    from .documented_list_fields import resolve_class_list_evidence, resolve_live_list_evidence
    from .object_graph_paths import expected_snapshot
    assertions = []
    for chain in chains:
        try:
            source = chain["source"]
            current = (resolve_live_list_evidence(chain["version"], chain["owner_id"], "Effects", read=read)
                if chain["owner_id"] else resolve_class_list_evidence(chain["version"], source["scope"]["class_id"], "Effects"))
            # Owner names/paths can change only through the ordinary prepared
            # identity/path guards; the source class/declaration remains exact.
            source_match = all(current[key] == source[key] for key in source if key != "scope") and current["scope"]["class_id"] == source["scope"]["class_id"]
            passed = source_match
            for field in chain["metadata"]:
                info = r._read_property_info(read, **field["scope"], name=field["field"])
                passed = passed and dict(info.raw) == field["raw"] and info.as_dict() == field["normalized"]
            for snapshot in chain["snapshots"]:
                if after_write and chain["mode"] == "replaceAll":
                    continue  # ordinary replacement verification proves deletion
                actual = r._read_object_id_rows(snapshot["object_id"], fields=snapshot["fields"], read=read, platform=chain["platform"])
                expected = deepcopy(snapshot["before"])
                if after_write:
                    expected = expected_snapshot(expected, edits=edits, read_row=lambda identity, fields: r._read_object_id_rows(identity, fields=fields, read=read))
                    for name, value in snapshot["after_changes"].items():
                        expected["@" + name] = value
                selected = {name: r._reference_identity(r._field_value(expected, name)) for name in ("Effect",) if r._has_field(expected, name)}
                strip = lambda row: {key: value for key, value in row.items() if key.lstrip("@") not in selected}
                passed = passed and len(actual) == 1 and r._native_snapshot_equal([strip(expected)], [strip(row) for row in actual]) and all(
                    r._reference_requirement_matches(actual[0], name, value) for name, value in selected.items())
            evidence = {"source_matches": source_match, "chain": chain}
        except (r.OperationContractError, ValueError, KeyError, TypeError) as exc:
            passed, evidence = False, {"error": str(exc)}
        assertions.append({"name": "Effect Render chain metadata and complete stored state match prepared intent", "passed": bool(passed), "evidence": evidence})
    return assertions
