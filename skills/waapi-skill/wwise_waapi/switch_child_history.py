"""Tagged scalar observations inside the shared owned-receipt history observer."""
from collections.abc import Mapping

from .object_lifecycle_graph import lifecycle_snapshot_equal as equal
from .switch_child_context import GET, FIELDS, validate

KIND = "switch_child_property"


def receipt_observations(prepared):
    from .edit_history_business import _receipt_platform, _scalar_matches
    from .operation_registry import _has_field, _field_value
    state, plan, request = prepared["pre_state"], prepared["verification_plan"], prepared["request"]
    proof = state["switch_child_context"]
    # Re-derive the pinned seals and structural facts from the owned receipt;
    # live state is separately revalidated before and after the history action.
    def source_read(uri, args, options):
        if uri == GET:
            rows = {row["id"]: row for row in proof["rows"].values()}
            return {"return": [rows[key] for key in args["from"]["id"] if key in rows]}
        if uri == "ak.wwise.core.object.getTypes":
            return {"return": proof["classes"]}
        raise ValueError("Unexpected structural receipt proof read")
    validate(proof, read=source_read)
    obj, before, info = state["object"], state["field_before"], state["field_info"]
    args, field = request["arguments"], plan.get("field")
    context_id, old, new = proof["context_id"], before.get("value"), plan.get("expected_value")
    expected_args = {"object": context_id, "property": field, "value": new,
        **({"platform": plan["platform"]} if plan.get("platform") is not None else {})}
    if (prepared.get("operation") != "object.setProperty" or request.get("operation") != "object.setProperty"
        or request.get("version") != proof["version"] or plan.get("kind") != "same-guid-property"
        or not equal(args.get("switch_child_context"), proof) or not equal(obj, proof["rows"]["context"])
        or args.get("object") != {"kind": "id", "value": context_id} or plan.get("object_id") != context_id
        or args.get("property") != field or args.get("platform") != plan.get("platform")
        or not equal(args.get("value"), new) or not equal(prepared.get("dispatch"), {
            "uri": "ak.wwise.core.object.setProperty", "args": expected_args, "options": {}})
        or before.get("field") != field or before.get("platform") != plan.get("platform")
        or before.get("observation_platform") != plan.get("observation_platform")
        or not isinstance(field, str) or info.get("field_binding", {}).get("token", info.get("name")) != field or info.get("type") != plan.get("metadata_type")
        or not _has_field(before.get("row", {}), field) or before["row"].get("id") != context_id
        or before["row"].get("path") != obj["path"] or not equal(_field_value(before["row"], field), old)
        or not _scalar_matches(old, old, info["type"]) or not _scalar_matches(new, new, info["type"])):
        raise ValueError("Structural property receipt lacks matching identity, request, field projection or typed values")
    guards = {key: state[key] for key in ("switch_child_context", "condition_metadata", "related_conditions") if key in state}
    metadata = guards.get("condition_metadata", {})
    if (metadata.get("object_id") != context_id or metadata.get("platform") != plan.get("platform")
        or not any(equal(info, row) for row in metadata.get("fields", []))
        or not any(row.get("token") == field and isinstance(row.get("metadata"), Mapping)
            for row in metadata.get("native_fields", []))):
        raise ValueError("Structural property receipt lacks its exact condition metadata")
    for dependency in info.get("dependencies", []):
        if dependency.get("action") == "Enable" and dependency.get("context") == "AssocParent":
            matches = [row for row in guards.get("related_conditions", [])
                if row.get("source_id") == context_id and row.get("owner_id") == proof["owner_id"]
                and row.get("property") == dependency.get("property") and row.get("platform") == plan.get("platform")]
            if len(matches) != 1:
                raise ValueError("Structural property receipt lacks its association condition guard")
    if any(chain.get("derived") for chain in state.get("effect_render_chains", [])):
        raise ValueError("Structural property side effects need a complete history observation")
    # A field explicitly certified as nonlinkable has one applicable value.
    # Its original omitted-platform projection is sufficient without inventing
    # a current platform GUID. Unknown/linkable fields use the ordinary proof.
    independent = (plan.get("platform") is None and plan.get("observation_platform") is None
        and info.get("supports", {}).get("unlink") is False)
    platform = None if independent else _receipt_platform(plan, state)
    return [{"kind": KIND, "object_before": obj, "object_after": dict(obj), "field": field,
        "before": old, "after": new, "platform": platform, "metadata_type": info["type"],
        "field_info": info, "guards": guards,
        "activation_requirements": before.get("activation_requirements", {}),
        "activation_reference_requirements": before.get("activation_reference_requirements", {}),
        "value_view": "nonlinkable_property" if independent else "certified_platform"}]


def observe(expected, side, *, read):
    from .edit_history_business import _scalar_matches
    from .operation_registry import _condition_metadata_assertions, _related_condition_assertions, _field_value, _has_field
    guards = expected["guards"]
    checks = _condition_metadata_assertions(guards, read=read)
    related, _ = _related_condition_assertions(guards.get("related_conditions", []), read=read)
    checks.extend(related)
    field, obj = expected["field"], expected["object_" + side]
    activators = expected["activation_requirements"]
    references = expected["activation_reference_requirements"]
    result = read(GET, {"from": {"id": [obj["id"]]}}, {"return": list(dict.fromkeys([*FIELDS, field, *activators, *references])),
        **({"platform": expected["platform"]} if expected["platform"] is not None else {})})
    rows = result.get("return") if isinstance(result, Mapping) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping) or rows[0].get("id") != obj["id"]:
        raise ValueError("Structural history field requires its exact context GUID once")
    row = rows[0]
    actual = _field_value(row, field)
    identity = {key: value for key, value in row.items() if key in FIELDS}
    from .operation_registry import condition_values_equal, _reference_requirement_matches
    active = all(_has_field(row, key) and condition_values_equal(_field_value(row, key), value) for key, value in activators.items())
    active = active and all(_reference_requirement_matches(row, key, value) for key, value in references.items())
    return {"object": obj, "field": field, "platform": expected["platform"], "value_view": expected["value_view"],
        "expected": expected[side], "actual": actual, "guards": checks,
        "passed": all(check["passed"] for check in checks) and active and equal(identity, obj)
            and _has_field(row, field) and _scalar_matches(actual, expected[side], expected["metadata_type"])}
