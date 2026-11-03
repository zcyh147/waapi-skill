"""Actual Action reference frames for source verification and owned history.

Display paths are observations, never strings reconstructed from target names.
The native command and reference-kind authority remain with their existing owners.
"""
from collections.abc import Mapping
from copy import deepcopy

from .business_declarations import normalize_live_object_identity
from .canonical import canonical_sha256
from .object_capabilities import object_identity_semantics

FIELDS = ("name", "type", "classId", "parent", "ActionType")
WITNESS = "verified-derived-reference-identity"


def applies(object_type, field):
    return (object_type == "Action" and field == "Target"
        and object_identity_semantics(object_type).display_identity_source == "action_and_target_path")


def frame(row):
    from .operation_registry import _reference_value_is_observed, _reference_identity
    identity = normalize_live_object_identity(row)
    parent = row.get("parent")
    parent_id = _reference_identity(parent)
    if (identity.object_type != "Action" or type(row.get("classId")) is not int or row["classId"] != 327696
            or type(row.get("ActionType")) is not int or not _reference_value_is_observed(parent)
            or not isinstance(parent_id, str)):
        raise ValueError("Derived reference identity requires actual Action class, parent and typed controller")
    from .edit_history_business import _reference_value
    if _reference_value(parent) is None:
        raise ValueError("Derived Action reference requires its actual owning parent")
    return {"object": {"id": identity.object_id, "name": identity.name, "type": identity.object_type,
        "path": identity.path}, "class_id": row["classId"], "parent_id": _reference_value(parent),
        "parent_reference": deepcopy(parent),
        "controller_values": {"ActionType": row["ActionType"]}}


def capture_before(row, source):
    from .edit_history_business import _identity, _reference_value
    actual = frame(row)
    if actual["object"] != _identity(source) or actual["parent_id"] != _reference_value(source.get("parent")):
        raise ValueError("Derived reference source identity changed during preparation")
    return actual


def matches(expected, row, *, after_write=False):
    from .operation_registry import _native_snapshot_equal
    try:
        actual = frame(row)
    except (ValueError, TypeError):
        return False
    if after_write:
        actual["object"]["path"] = expected["object"]["path"]
    return _native_snapshot_equal(actual, expected)


def native_metadata(prepared_state):
    rows = [item["metadata"] for item in prepared_state.get("condition_metadata", {}).get("native_fields", [])
        if item.get("token") == "Target" and isinstance(item.get("metadata"), Mapping)]
    if len(rows) != 1:
        raise ValueError("Derived reference requires its original exact native metadata observation")
    return dict(rows[0])


def witness(row, prepared_state):
    expected = prepared_state.get("derived_reference_context")
    if not isinstance(expected, Mapping) or not matches(expected, row, after_write=True):
        raise ValueError("Derived reference post-state lacks its unchanged identity/controller frame")
    return {"kind": WITNESS, "name": "derived reference actual identity and context observed", "passed": True,
        "evidence": {"before": dict(expected), "after": frame(row), "row": dict(row),
            "field_info_sha256": canonical_sha256(prepared_state["field_info"]),
            "native_metadata_sha256": canonical_sha256(native_metadata(prepared_state))}}


def receipt_context(prepared, verification):
    """Use only the original verified source read and its tagged association."""
    from .edit_history_business import _reference_value
    from .operation_registry import _native_snapshot_equal, _same_identity
    state, plan = prepared["pre_state"], prepared["verification_plan"]
    before = state.get("derived_reference_context")
    if not isinstance(before, Mapping) or not isinstance(verification, Mapping):
        raise ValueError("Derived reference receipt needs original before/verified-after identity observations")
    observed_before = capture_before(state.get("field_before", {}).get("row", {}), state["object"])
    if not _native_snapshot_equal(before, observed_before):
        raise ValueError("Derived reference before identity differs from its sealed source read")
    records = [item for item in verification.get("assertions", []) if item.get("kind") == WITNESS]
    if len(records) != 1 or records[0].get("passed") is not True:
        raise ValueError("Derived reference receipt requires one successful actual post-identity witness")
    evidence = records[0].get("evidence", {})
    if not isinstance(evidence, Mapping):
        raise ValueError("Derived reference receipt requires a structured actual post-identity witness")
    row = evidence.get("row")
    if (not isinstance(row, Mapping) or not _native_snapshot_equal(evidence.get("before"), before)
            or evidence.get("field_info_sha256") != canonical_sha256(state["field_info"])
            or evidence.get("native_metadata_sha256") != canonical_sha256(native_metadata(state))
            or not matches(before, row, after_write=True)
            or not _native_snapshot_equal(evidence.get("after"), frame(row))):
        raise ValueError("Derived reference witness differs from original identity/metadata observations")
    observed_field = "@" + plan["field"] if plan.get("expected_clear") is True else plan["field"]
    expected_target = None if plan.get("expected_clear") is True else plan["expected_target_id"]
    if observed_field not in row or not _same_identity(_reference_value(row[observed_field]), expected_target):
        raise ValueError("Derived reference post-identity witness has the wrong reference value")
    view = plan.get("observation_platform", plan.get("platform"))
    reads = [item for item in verification.get("readbacks", [])
        if item.get("uri") == "ak.wwise.core.object.get"
        and item.get("args") == {"from": {"id": [plan["object_id"]]}}
        and item.get("options", {}).get("platform") == view
        and set((*FIELDS, "id", "path", observed_field)) <= set(item.get("options", {}).get("return", []))
        and _native_snapshot_equal(item.get("result"), {"return": [row]})]
    if len(reads) != 1:
        raise ValueError("Derived reference witness lacks its exact retained native source read")
    return {"object_before": dict(before["object"]), "object_after": dict(evidence["after"]["object"]),
        "class_id": before["class_id"], "parent_id": before["parent_id"],
        "parent_reference": deepcopy(before["parent_reference"]),
        "controller_values": dict(before["controller_values"])}
