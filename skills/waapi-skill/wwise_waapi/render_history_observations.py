"""Existing Render chain preservation attached to actual source verification.

The native history action still addresses the latest project history entry.
This module supplies scoped stored-state expectations, never a stack entry ID.
"""
from __future__ import annotations

from copy import deepcopy

from .canonical import canonical_sha256
from .object_lifecycle_graph import lifecycle_snapshot_equal

KIND = "existing_render_chain"


def _model(chain, observed):
    from .edit_history_business import _reference_value, _identity
    from .operation_registry import _has_field, _field_value

    model = deepcopy(observed)
    if set(model) != ({"source", "slot_types", "metadata", "snapshots", "targets"}
            | ({"order"} if chain.get("kind") != "legacy-scalars" else {"targets_complete"})):
        raise ValueError("Render history requires its complete typed observed chain model")
    if chain.get("kind") == "legacy-scalars" and model["targets_complete"] is not True:
        raise ValueError("Legacy Render history target observations are incomplete")
    reference_fields = [f"Effect{i}" for i in range(4)] if chain.get("kind") == "legacy-scalars" else ["Effect"]
    for item in model["snapshots"]:
        rows = item["rows"]
        if (len(rows) != 1 or _identity(rows[0])["id"] != item["object_id"].upper()
                or type(rows[0].get("classId")) is not int):
            raise ValueError("Render history member requires one exact GUID/class observation")
        row = rows[0]
        for field in reference_fields:
            if not _has_field(row, field):
                raise ValueError("Render history requires every original Effect reference")
            key = field if field in row else "@" + field
            row[key] = _reference_value(_field_value(row, field))
    for target in model["targets"]:
        if (len(target["rows"]) != 1 or _identity(target["rows"][0])["id"] != target["object_id"].upper()
                or type(target["rows"][0].get("classId")) is not int):
            raise ValueError("Render history Effect target requires its exact identity/class")
    return model


def _before_model(chain):
    return _model(chain, {"source": chain["source"], "slot_types": [chain["slot_type"]],
        "metadata": chain["metadata"], "snapshots": [{"object_id": item["object_id"], "rows": [item["before"]]}
            for item in chain["snapshots"]],
        "targets": [{"object_id": item["before"]["id"], "rows": [item["before"]]} for item in chain.get("targets", [])],
        **({"order": chain["before_order"]} if chain.get("kind") != "legacy-scalars" else {"targets_complete": True})})


def _owner(chain, model):
    from .edit_history_business import _identity
    if chain.get("kind") == "legacy-scalars":
        rows = [item["rows"][0] for item in model["snapshots"] if item["object_id"] == chain["owner_id"]]
        if len(rows) != 1:
            raise ValueError("Legacy Render history requires its exact original owner")
        return _identity(rows[0]), rows[0]["classId"]
    scope = model["source"]["scope"]
    identity = _identity(scope["owner"])
    if identity["id"] != chain["owner_id"].upper() or type(scope.get("class_id")) is not int:
        raise ValueError("Render history owner GUID/class differs from its exact List source")
    return identity, scope["class_id"]


def receipt_observations(prepared, verification):
    """Return shared changed-field rows plus full ordered preservation witnesses."""
    from .edit_history_business import _GUID, _identity, _scalar_matches, _receipt_platform
    from .operation_registry import _has_field, _field_value

    state, plan = prepared["pre_state"], prepared["verification_plan"]
    chains = state.get("effect_render_chains", [])
    fields, preservation, covered = [], [], {}
    for chain in chains:
        if (chain.get("mode") != "existing" or chain.get("construction") or not chain.get("snapshots")
                or not _GUID.fullmatch(str(chain.get("owner_id")))):
            raise ValueError("Render creation/List/restoration requires its complete source producer")
        if chain.get("kind") == "legacy-scalars" and chain.get("target_observation", {}).get("status") != "certified":
            raise ValueError("Legacy Render receipt target observation is unavailable")
        view = chain.get("field_read_platform", {})
        platform = chain.get("platform")
        if view.get("status") != "certified" or view.get("platform_id") != platform:
            raise ValueError("Render receipt original chain read view is not certified")
        if not _GUID.fullmatch(str(platform)) or platform == "{00000000-0000-0000-0000-000000000000}":
            raise ValueError("Render receipt original chain read view is not certified")
        if plan["kind"] == "same-guid-property" and _receipt_platform(plan, state) != platform:
            raise ValueError("Render source selected field and complete chain views differ")
        records = [item["evidence"] for item in verification.get("assertions", [])
            if item.get("kind") == "effect_render_chain_observation" and item.get("passed") is True
            and item.get("evidence", {}).get("after_write") is True
            and item["evidence"].get("prepared_chain_sha256") == canonical_sha256(chain)]
        if (len(records) != 1 or not lifecycle_snapshot_equal(records[0].get("chain"), chain)
                or records[0].get("source_matches") is not True):
            raise ValueError("Render receipt requires one actual verified-after chain association")
        before, after = _before_model(chain), _model(chain, records[0]["observation"])
        expected = deepcopy(before)
        for original, projected in zip(chain["snapshots"], expected["snapshots"], strict=True):
            for name, value in original["after_changes"].items():
                row = projected["rows"][0]
                if not _has_field(row, name):
                    raise ValueError("Render source change lacks its original full-field observation")
                row[name if name in row else "@" + name] = value
        if not lifecycle_snapshot_equal(expected, after):
            raise ValueError("Render verified-after chain differs from the complete prepared field/preservation outcome")
        owner_before, owner_class = _owner(chain, before)
        owner_after, after_class = _owner(chain, after)
        if owner_class != after_class:
            raise ValueError("Render source owner class changed")
        for original, old, new in zip(chain["snapshots"], before["snapshots"], after["snapshots"], strict=True):
            identity = original["object_id"].upper()
            metadata = [item for item in chain["metadata"] if str(item["scope"].get("object_id")).upper() == identity]
            covered.setdefault((identity, platform), set()).update(item["field"] for item in metadata)
            for name in original["after_changes"]:
                infos = [item for item in metadata if item["field"] == name]
                if not infos or any(not lifecycle_snapshot_equal(item, infos[0]) for item in infos):
                    raise ValueError("Render changed field lacks exact source raw metadata")
                info = infos[0]
                old_value, new_value = _field_value(old["rows"][0], name), _field_value(new["rows"][0], name)
                if not _scalar_matches(old_value, old_value, info["normalized"]["type"]) or not _scalar_matches(new_value, new_value, info["normalized"]["type"]):
                    raise ValueError("Render changed source field is not an observed typed scalar")
                fields.append({"kind": "existing_field", "object_before": _identity(old["rows"][0]),
                    "object_after": _identity(new["rows"][0]), "class_id": old["rows"][0]["classId"],
                    "field": name, "field_kind": "scalar", "before": old_value, "after": new_value,
                    "platform": platform, "metadata_type": info["normalized"]["type"],
                    "field_info": {**info["normalized"], "raw": info["raw"]}})
        preservation.append({"kind": KIND, "object_before": owner_before, "object_after": owner_after,
            "class_id": owner_class, "field": "render_chain_preservation", "platform": platform,
            "before": before, "after": after, "chain": chain,
            "edits": state.get("object_set_nodes", [])})
    return [*fields, *preservation], covered


def observe_chain(expected, side, *, read):
    """Reuse the source chain reader; raw replies stay in the owning read journal."""
    from .effect_render_conditions import chain_assertions
    actual, = chain_assertions([expected["chain"]], read=read, after_write=side == "after", edits=expected["edits"])
    evidence = actual["evidence"]
    model = _model(expected["chain"], evidence["observation"]) if actual["passed"] else None
    return {"object": expected["object_" + side], "field": "render_chain_preservation",
        "expected_sha256": canonical_sha256(expected[side]),
        "actual_sha256": canonical_sha256(model) if model is not None else None,
        **({"error": evidence} if model is None else {}),
        "full_observations": "sealed_expectation_and_retained_readbacks",
        "passed": actual["passed"] and lifecycle_snapshot_equal(expected[side], model)}


def summary(row):
    """Disclose every changed/preserved field once; full projections stay sealed."""
    from .edit_history_business import _identity
    from .operation_registry import _field_value
    chain = row["chain"]
    members = []
    for old, new in zip(row["before"]["snapshots"], row["after"]["snapshots"], strict=True):
        before, after = old["rows"][0], new["rows"][0]
        preserved, changes = {}, {}
        for info in chain["metadata"]:
            if info["scope"].get("object_id") != old["object_id"]:
                continue
            name = info["field"]
            a, b = _field_value(before, name), _field_value(after, name)
            if lifecycle_snapshot_equal(a, b):
                preserved[name] = a
            else:
                changes[name] = {"before": a, "after": b}
        members.append({"id": old["object_id"], "class_id": before["classId"],
            "preserved": preserved, "changes": changes})
    common = {"kind": KIND, "owner": row["object_before"], "owner_class_id": row["class_id"],
        "platform": row["platform"], "effect_targets": [{**_identity(item["rows"][0]), "class_id": item["rows"][0]["classId"]}
            for item in row["before"]["targets"]],
        "metadata_bound": True, "all_other_projected_state_preserved": True,
        "full_raw_proof": "immutable_artifact_and_source_verification_event"}
    if chain.get("kind") == "legacy-scalars":
        common["owner_fields"] = {key: members[0][key] for key in ("preserved", "changes")}
    else:
        common["members_in_original_order"] = members
    return common
