"""Owned scoped expectations for a native latest-project-history action.

A receipt supplies observable before/after state, never a native history entry ID.
"""
from __future__ import annotations

from pathlib import Path
import math
import re
from typing import Any, Callable, Mapping

from .business_declarations import normalize_live_object_identity
from .canonical import canonical_json_bytes
from .builders.metadata import bind_get_property_info_result, parse_property_and_reference_names_result
from .metadata_discovery import metadata_typed_value_type
from .object_lifecycle_graph import lifecycle_snapshot_equal
from .transactions import TransactionState, TransactionStore
from .transaction_runtime import canonical_project_path

from .edit_history_contracts import HISTORY_VERSIONS

CONTRACT = "waapi-skill.owned-history-expectation/v1"
GET = "ak.wwise.core.object.get"
NAMES = "ak.wwise.core.object.getPropertyAndReferenceNames"
INFO = "ak.wwise.core.object.getPropertyInfo"
IDENTITY = ("id", "name", "type", "path")
MAX_OBSERVATIONS = 128
MAX_BINDING_BYTES = 64 * 1024
_GUID = re.compile(r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}\Z")


class HistoryObservationError(ValueError):
    """Keep the original bounded read even when its observation is incomplete."""
    def __init__(self, message: str, readback: Mapping[str, Any] | list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.readbacks = [dict(readback)] if isinstance(readback, Mapping) else list(readback)


def _scalar_matches(actual: Any, expected: Any, metadata_type: str) -> bool:
    kind = metadata_typed_value_type(metadata_type)
    if kind == "number":
        try:
            return (not isinstance(actual, bool) and not isinstance(expected, bool)
                and isinstance(actual, (int, float)) and isinstance(expected, (int, float))
                and math.isfinite(actual) and math.isfinite(expected)
                and math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-5))
        except (OverflowError, ValueError):
            return False
    value_type = {"string": str, "boolean": bool, "integer": int}.get(kind)
    return value_type is not None and type(actual) is value_type and type(expected) is value_type and actual == expected


def _identity(row: Any) -> dict[str, Any]:
    bound = normalize_live_object_identity(row)
    return {"id": bound.object_id, "name": bound.name, "type": bound.object_type, "path": bound.path}


def _receipt_observations(prepared: Mapping[str, Any]) -> list[dict[str, Any]]:
    plan, state = prepared.get("verification_plan"), prepared.get("pre_state")
    if not isinstance(plan, Mapping) or not isinstance(state, Mapping):
        raise ValueError("History expectation receipt lacks a prepared business observation")
    if plan.get("kind") == "undo-group-result-schemas":
        calls = state.get("execution_plan", {}).get("calls")
        if not isinstance(calls, list) or not calls:
            raise ValueError("Compound history receipt lacks its exact prepared children")
        observations = []
        for child in calls:
            if not isinstance(child, Mapping) or not isinstance(child.get("prepared_operation"), Mapping):
                raise ValueError("Compound history receipt lacks a recoverable child observation")
            observations.extend(_receipt_observations(child["prepared_operation"]))
        if not 1 <= len(observations) <= MAX_OBSERVATIONS:
            raise ValueError("Compound history receipt exceeds its observation bound")
        before_by_id, after_by_id = {}, {}
        outcomes = set()
        for row in observations:
            identity = row["object_before"]
            object_id = identity["id"]
            if object_id in before_by_id and before_by_id[object_id] != identity:
                raise ValueError("Compound history children disagree about their before identity")
            before_by_id[object_id] = identity
            key = (object_id, row["field"], row.get("platform"))
            if key in outcomes:
                raise ValueError("Compound history receipt has overlapping observed outcomes")
            outcomes.add(key)
            if row["field"] == "name":
                after_by_id[object_id] = row["object_after"]
        for row in observations:
            after = dict(after_by_id.get(row["object_before"]["id"], row["object_after"]))
            # A rename changes the native hierarchy path of observed descendants
            # too. Apply deepest ancestors first, always using the sealed before
            # path to distinguish hierarchy segments from matching name prefixes.
            for object_id in sorted(after_by_id, key=lambda key: len(before_by_id[key]["path"]), reverse=True):
                before_path = before_by_id[object_id]["path"]
                if row["object_before"]["path"].startswith(before_path + "\\"):
                    after["path"] = after_by_id[object_id]["path"] + after["path"][len(before_path):]
            row["object_after"] = after
        return observations
    if plan.get("kind") == "same-guid-property":
        identity = _identity(state.get("object"))
        field, platform, metadata_type = plan.get("field"), plan.get("platform"), plan.get("metadata_type")
        field_before, info = state.get("field_before", {}), state.get("field_info", {})
        if not isinstance(platform, str) or not _GUID.fullmatch(platform):
            raise ValueError("Property receipt effective platform is not yet certified; current/named-platform receipt resolution remains implementation work")
        old, new = field_before.get("value"), plan.get("expected_value")
        if (identity["id"] != str(plan.get("object_id")).upper() or not isinstance(field, str)
            or field_before.get("field") != field or field_before.get("platform") != platform
            or not isinstance(info, Mapping) or info.get("type") != metadata_type
            or not _scalar_matches(old, old, metadata_type) or not _scalar_matches(new, new, metadata_type)):
            raise ValueError("Property receipt requires an exact typed before/after value and platform view")
        return [{"object_before": identity, "object_after": dict(identity), "field": field,
            "before": old, "after": new, "platform": platform, "metadata_type": metadata_type, "field_info": dict(info)}]
    if plan.get("kind") not in {"same-guid-notes", "same-guid-renamed"}:
        raise ValueError("This receipt observer is not yet implemented; it remains an edit-history implementation obligation")
    before = state.get("object")
    identity = _identity(before)
    field = "notes" if plan["kind"] == "same-guid-notes" else "name"
    old, new = before.get(field), plan.get("expected_" + field)
    after_identity = dict(identity)
    if field == "name" and isinstance(new, str):
        after_identity.update(name=new, path=identity["path"].rsplit("\\", 1)[0] + "\\" + new)
    if identity["id"] != str(plan.get("object_id")).upper() or not isinstance(old, str) or not isinstance(new, str):
        raise ValueError("History expectation requires an observed before value and an exact verified after value")
    return [{"object_before": identity, "object_after": after_identity, "field": field, "before": old, "after": new}]


def _verified_snapshot(store: TransactionStore, transaction_id: str) -> Any:
    snapshot = store.load_snapshot(transaction_id)
    if snapshot.record.state != TransactionState.VERIFIED:
        raise ValueError("History expectation requires an owned successfully business-verified receipt")
    verification = next((event.get("details", {}).get("verification") for event in reversed(snapshot.events)
                         if event.get("event_type") == "verification_recorded"), None)
    if not isinstance(verification, Mapping) or verification.get("business_state_verified") is not True:
        raise ValueError("A schema-only receipt is not an observed history-effect expectation")
    return snapshot


def capture_history_binding(uri: str, store: TransactionStore, transaction_id: str | None, *, current_guard: Mapping[str, Any]) -> dict[str, Any]:
    if transaction_id is None:
        binding = {"contract": CONTRACT, "uri": uri, "version": current_guard.get("version"),
            "scope": "latest_project_history", "source_context_fingerprint": current_guard.get("context_fingerprint"),
            "source_receipt": None, "observations": []}
        return validate_history_binding(uri, str(binding["version"]), binding)
    snapshot = _verified_snapshot(store, transaction_id)
    artifact = snapshot.preview.artifact
    source_guard = artifact.get("project_guard", {})
    before_project, current_project = source_guard.get("project", {}), current_guard.get("project", {})
    if (source_guard.get("context_fingerprint") != current_guard.get("context_fingerprint")
        or str(before_project.get("id")).upper() != str(current_project.get("id")).upper()
        or canonical_project_path(before_project.get("path")) != canonical_project_path(current_project.get("path"))):
        raise ValueError("History expectation receipt belongs to another project or Wwise runtime")
    version = current_guard.get("version")
    binding = {"contract": CONTRACT, "uri": uri, "version": version, "scope": "latest_project_history",
        "source_context_fingerprint": source_guard["context_fingerprint"],
        "source_receipt": {"state_dir": str(store.state_dir), "transaction_id": transaction_id,
            "artifact_hash": snapshot.preview.artifact_hash, "event_sequence": snapshot.record.event_sequence,
            "last_event_hash": snapshot.record.last_event_hash},
        "observations": _receipt_observations(artifact["prepared_operation"])}
    validate_history_binding(uri, str(version), binding)
    return binding


def validate_history_binding(uri: str, version: str, value: Any) -> dict[str, Any]:
    keys = {"contract", "uri", "version", "scope", "source_context_fingerprint", "source_receipt", "observations"}
    if (uri not in HISTORY_VERSIONS or version not in HISTORY_VERSIONS[uri] or not isinstance(value, Mapping)
        or set(value) != keys or value.get("contract") != CONTRACT or value.get("uri") != uri
        or value.get("version") != version or value.get("scope") != "latest_project_history"):
        raise ValueError("History actions require their closed latest-project-history expectation proof")
    if len(canonical_json_bytes(value)) > MAX_BINDING_BYTES:
        raise ValueError("History expectation exceeds its bounded proof size")
    receipt = value["source_receipt"]
    if receipt is None:
        if value["observations"] != [] or not isinstance(value["source_context_fingerprint"], str) or not value["source_context_fingerprint"]:
            raise ValueError("Unobserved latest-history action must not contain fabricated effect expectations")
        return dict(value)
    if not isinstance(receipt, Mapping) or set(receipt) != {"state_dir", "transaction_id", "artifact_hash", "event_sequence", "last_event_hash"}:
        raise ValueError("History expectation requires one exact owned receipt identity")
    snapshot = _verified_snapshot(TransactionStore(Path(receipt["state_dir"])), receipt["transaction_id"])
    if (snapshot.preview.artifact_hash != receipt["artifact_hash"] or snapshot.record.last_event_hash != receipt["last_event_hash"]
        or snapshot.record.event_sequence != receipt["event_sequence"]
        or snapshot.preview.artifact.get("project_guard", {}).get("context_fingerprint") != value["source_context_fingerprint"]):
        raise ValueError("History expectation receipt changed after it was selected")
    observations = _receipt_observations(snapshot.preview.artifact["prepared_operation"])
    if not any(row["before"] != row["after"] for row in observations):
        raise ValueError("History expectation receipt has no observable transition")
    if not 1 <= len(observations) <= MAX_OBSERVATIONS or not lifecycle_snapshot_equal(value["observations"], observations):
        raise ValueError("History expected states differ from their immutable owned receipt")
    return dict(value)


def observe_history_state(binding: Mapping[str, Any], *, after_action: bool, read: Callable[..., Any]) -> dict[str, Any]:
    uri, version = binding["uri"], binding["version"]
    validate_history_binding(uri, version, binding)
    if binding["source_receipt"] is None:
        raise ValueError("Latest-history action has no selected effect expectation to observe")
    side = ("before" if uri.endswith(".undo") else "after") if after_action else ("after" if uri.endswith(".undo") else "before")
    observations = binding["observations"]
    readbacks, checks = [], []
    def retained_read(uri, args, options):
        result = read(uri, args, options)
        readbacks.append({"uri": uri, "args": args, "options": options,
            "result": dict(result) if isinstance(result, Mapping) else result})
        return result
    try:
        groups = {}
        metadata_cache = {}
        for expected in observations:
            groups.setdefault(expected.get("platform"), []).append(expected)
            if "field_info" in expected:
                object_id, field = expected["object_" + side]["id"], expected["field"]
                key = (object_id, field)
                if key not in metadata_cache:
                    names = [row.name for row in parse_property_and_reference_names_result(retained_read(NAMES, {"object": object_id}, {}))]
                    info = bind_get_property_info_result(retained_read(INFO, {"object": object_id, "property": field}, {}),
                        field_token=field, available_names=names)
                    if info.name != field or info.type != expected["metadata_type"]:
                        raise ValueError("History property metadata does not match its exact field/type")
                    metadata_cache[key] = info.as_dict()
                if not lifecycle_snapshot_equal(metadata_cache[key], expected["field_info"]):
                    raise ValueError("History property metadata changed since the owned receipt")
        for platform, group in groups.items():
            ids = list(dict.fromkeys(row["object_" + side]["id"] for row in group))
            args = {"from": {"id": ids}}
            options = {"return": list(dict.fromkeys([*IDENTITY, *(row["field"] for row in group)])),
                **({"platform": platform} if platform is not None else {})}
            result = retained_read(GET, args, options)
            rows = result.get("return") if isinstance(result, Mapping) else None
            if not isinstance(rows, list) or len(rows) != len(ids):
                raise ValueError("History observation must return every exact object GUID once")
            found = {}
            for row in rows:
                identity = _identity(row)
                if identity["id"] not in ids or identity["id"] in found:
                    raise ValueError("History observation contains duplicate or unrelated GUIDs")
                found[identity["id"]] = row
            for expected in group:
                identity = expected["object_" + side]
                row = found[identity["id"]]
                field = expected["field"]
                actual = row[field] if field in row else row.get("@" + field)
                equal = (_scalar_matches(actual, expected[side], expected["metadata_type"])
                    if "metadata_type" in expected else isinstance(actual, str) and actual == expected[side])
                checks.append({"object": identity, "field": field, "platform": platform,
                    "expected": expected[side], "actual": actual, "passed": _identity(row) == identity and equal})
    except ValueError as exc:
        raise HistoryObservationError(str(exc), readbacks) from exc
    return {"scope": "owned_receipt_observation_only", "stack_head_observed": False,
        "outside_scope_preservation_observed": False, "matches": all(row["passed"] for row in checks),
        "checks": checks, "readbacks": readbacks}


def history_summary(binding: Mapping[str, Any]) -> dict[str, Any]:
    receipt = binding["source_receipt"]
    return {"scope": "latest_project_history", "action": binding["uri"].rsplit(".", 1)[-1],
        "expectation_receipt": receipt["transaction_id"] if receipt else None,
        "effect_expectation": "owned_receipt_scoped_state" if receipt else "none",
        "receipt_role": "scoped_effect_expectation_only; does_not_select_a_native_history_entry" if receipt else "none",
        "verification_boundary": "owned_receipt_scoped_state_only" if receipt else "result_schema_only; effect_and_preservation_unobserved",
        "stack_head_observed": False, "outside_scope_preservation_observed": False,
        "automatic_retry": False, "automatic_compensation": False,
        "expected_observations": binding["observations"]}
