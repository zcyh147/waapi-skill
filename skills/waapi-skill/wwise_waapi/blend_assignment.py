"""Bounded indexed assignment observations; no inferred reassignment/edge effects."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping
import re
import uuid

from .canonical import canonical_json_bytes
from .business_declarations import normalize_live_object_identity
from .builders.schema import validate_resolved_semantic_result

ADD = "ak.wwise.core.blendContainer.addAssignment"
GET = "ak.wwise.core.blendContainer.getAssignments"
OBJECT_GET = "ak.wwise.core.object.get"
# Same byte ceiling as the existing public bounded getAssignments read.
MAX_BYTES = 256 * 1024
_GUID = re.compile(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}")


class BlendAssignmentError(ValueError):
    pass


def _guid(value):
    if not isinstance(value, str) or _GUID.fullmatch(value) is None:
        raise BlendAssignmentError("Blend assignment observations require canonical GUIDs")
    parsed = uuid.UUID(value)
    if parsed.int == 0:
        raise BlendAssignmentError("Blend assignment observations require nonzero GUIDs")
    return "{" + str(parsed).upper() + "}"


def _reference(value):
    return _guid(value.get("id") if isinstance(value, Mapping) else value)


def _objects(ids, read, fields, version):
    result = read(OBJECT_GET, {"from": {"id": ids}}, {"return": fields})
    rows = result.get("return")
    if not isinstance(rows, list) or len(rows) != len(ids):
        raise BlendAssignmentError("Blend identities must resolve exactly once")
    by_id = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise BlendAssignmentError("Blend identity row is malformed")
        identity = _guid(row.get("id"))
        if identity not in ids or identity in by_id or any(not isinstance(row.get(k), str) or not row[k] for k in ("name", "type", "path")):
            raise BlendAssignmentError("Blend identity set is missing, duplicated, extra or malformed")
        try:
            normalize_live_object_identity(row, version=version)
        except ValueError as exc:
            raise BlendAssignmentError("Blend identity must match its bounded version/type profile") from exc
        by_id[identity] = {**dict(row), "id": identity}
    return by_id


def observe(track_id, child_id, *, read, version):
    """Explicit indices own order; missing indices never borrow array positions."""
    track_id, child_id = _guid(track_id), _guid(child_id)
    fields = ["id", "name", "type", "path", "parent"]
    rows = _objects([track_id, child_id], read, fields, version)
    track, child = rows[track_id], rows[child_id]
    if track["type"] != "BlendTrack":
        raise BlendAssignmentError("Assignment object must be a BlendTrack")
    owner_id = _reference(child.get("parent"))
    owner = _objects([owner_id], read, ["id", "name", "type", "path", "blendTracks"], version)[owner_id]
    tracks = owner.get("blendTracks")
    if owner["type"] != "BlendContainer" or not isinstance(tracks, list):
        raise BlendAssignmentError("Assignment child must have a BlendContainer parent with observed tracks")
    track_ids = [_reference(item) for item in tracks]
    if len(set(track_ids)) != len(track_ids) or track_ids.count(track_id) != 1:
        raise BlendAssignmentError("BlendTrack must belong to the child's exact BlendContainer")
    result = read(GET, {"object": track_id}, {})
    try:
        if len(canonical_json_bytes(result)) > MAX_BYTES:
            raise BlendAssignmentError("Blend assignment snapshot exceeds the bounded read ceiling")
    except (TypeError, ValueError) as exc:
        raise BlendAssignmentError("Blend assignment snapshot is not bounded finite JSON") from exc
    try:
        validate_resolved_semantic_result(GET, result, version=version)
    except ValueError as exc:
        raise BlendAssignmentError("Blend assignment snapshot does not match the pinned result definitions") from exc
    assignments = result.get("return")
    if not isinstance(assignments, list):
        raise BlendAssignmentError("Blend assignments require the complete native return array")
    positions, identities = {}, set()
    for row in assignments:
        if not isinstance(row, Mapping):
            raise BlendAssignmentError("Blend assignment row is malformed")
        identity, index = _guid(row.get("child")), row.get("index")
        if type(index) is not int or not 0 <= index < len(assignments) or index in positions or identity in identities:
            raise BlendAssignmentError("Blend assignment indices and child identities must cover each position exactly once")
        positions[index] = {**deepcopy(dict(row)), "child": identity}
        identities.add(identity)
    # No sorting or inferred default index. Only the complete explicit 0..n-1 set.
    ordered = [positions[index] for index in range(len(assignments))]
    return {"track": {k: track[k] for k in ("id", "name", "type", "path")},
            "child": {**{k: child[k] for k in ("id", "name", "type", "path")}, "parent": owner_id},
            "owner": {k: owner[k] for k in ("id", "name", "type", "path", "blendTracks")},
            "assignments": ordered, "native_assignments": deepcopy(assignments)}


def prepare(args, *, read, version):
    before = observe(args["object"], args["child"], read=read, version=version)
    order = [row["child"] for row in before["assignments"]]
    position = max(0, min(args.get("index", len(order)), len(order)))
    existing = _guid(args["child"]) in order
    expected = None if existing else [*order[:position], _guid(args["child"]), *order[position:]]
    unobserved = []
    if existing:
        unobserved.append("existing_assignment_reassignment_semantics")
    if "edges" in args:
        unobserved.append("requested_edges_crossfade_applicability_and_effect")
    if any("edges" not in row for row in before["assignments"] if row["child"] != _guid(args["child"])):
        unobserved.append("unreturned_non_target_edges")
    return {"before": before, "expected_position": position, "expected_order": expected,
            "requested_index": args.get("index"), "requested_edges": deepcopy(args.get("edges")),
            "verification_scope": {"observed": ["track_child_owner_identity", "indexed_assignment_order", "returned_non_target_edges"],
                                   "unobserved": unobserved, "default_edge_geometry_promised": False}}


def notice(plan):
    return {"requested_index": plan["requested_index"], "omitted_index_means": "append",
            "observed_assignment_count": len(plan["before"]["assignments"]),
            "expected_position": plan["expected_position"],
            "order_prediction": "new_assignment_insertion" if plan["expected_order"] is not None else "existing_assignment_effect_unproven",
            "verification_scope": plan["verification_scope"]}


def compare(plan, after):
    before = plan["before"]
    checks = [{"name": "Blend track, child parent and owner membership remain unchanged",
               "passed": all(before[k] == after[k] for k in ("track", "child", "owner"))}]
    if plan["expected_order"] is not None:
        actual = [row["child"] for row in after["assignments"]]
        checks.append({"name": "Complete indexed Blend assignment order matches the clamped insertion",
                       "passed": actual == plan["expected_order"], "evidence": {"expected": plan["expected_order"], "actual": actual}})
    by_id = {row["child"]: row for row in after["assignments"]}
    retained = [row for row in before["assignments"] if row["child"] != before["child"]["id"]]
    checks.append({"name": "All observed non-target assignment data and edges are preserved",
                   "passed": all(row["child"] in by_id and all(by_id[row["child"]].get(k) == v for k, v in row.items() if k != "index") for row in retained)})
    return checks
