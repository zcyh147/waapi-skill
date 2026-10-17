"""Owned scoped expectations for a native latest-project-history action.

A receipt supplies observable before/after state, never a native history entry ID.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from .business_declarations import normalize_live_object_identity
from .canonical import canonical_json_bytes
from .transactions import TransactionState, TransactionStore
from .transaction_runtime import canonical_project_path

from .edit_history_contracts import HISTORY_VERSIONS

CONTRACT = "waapi-skill.owned-history-expectation/v1"
GET = "ak.wwise.core.object.get"
IDENTITY = ("id", "name", "type", "path")
MAX_OBSERVATIONS = 128
MAX_BINDING_BYTES = 64 * 1024


class HistoryObservationError(ValueError):
    """Keep the original bounded read even when its observation is incomplete."""
    def __init__(self, message: str, readback: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.readbacks = [dict(readback)]


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
            key = (object_id, row["field"])
            if key in outcomes:
                raise ValueError("Compound history receipt has overlapping observed outcomes")
            outcomes.add(key)
            if row["field"] == "name":
                after_by_id[object_id] = row["object_after"]
        for row in observations:
            row["object_after"] = after_by_id.get(row["object_before"]["id"], row["object_after"])
        return observations
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


def capture_history_binding(uri: str, store: TransactionStore, transaction_id: str, *, current_guard: Mapping[str, Any]) -> dict[str, Any]:
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
    if not 1 <= len(observations) <= MAX_OBSERVATIONS or value["observations"] != observations:
        raise ValueError("History expected states differ from their immutable owned receipt")
    return dict(value)


def observe_history_state(binding: Mapping[str, Any], *, after_action: bool, read: Callable[..., Any]) -> dict[str, Any]:
    uri, version = binding["uri"], binding["version"]
    validate_history_binding(uri, version, binding)
    side = ("before" if uri.endswith(".undo") else "after") if after_action else ("after" if uri.endswith(".undo") else "before")
    observations = binding["observations"]
    ids = list(dict.fromkeys(row["object_" + side]["id"] for row in observations))
    args = {"from": {"id": ids}}
    options = {"return": list(dict.fromkeys([*IDENTITY, *(row["field"] for row in observations)]))}
    result = read(GET, args, options)
    readback = {"uri": GET, "args": args, "options": options,
                "result": dict(result) if isinstance(result, Mapping) else result}
    try:
        rows = result.get("return") if isinstance(result, Mapping) else None
        if not isinstance(rows, list) or len(rows) != len(ids):
            raise ValueError("History observation must return every exact object GUID once")
        found = {}
        for row in rows:
            identity = _identity(row)
            if identity["id"] not in ids or identity["id"] in found:
                raise ValueError("History observation contains duplicate or unrelated GUIDs")
            found[identity["id"]] = row
        checks = []
        for expected in observations:
            identity = expected["object_" + side]
            row = found[identity["id"]]
            actual = row.get(expected["field"])
            checks.append({"object": identity, "field": expected["field"], "expected": expected[side], "actual": actual,
                "passed": _identity(row) == identity and isinstance(actual, str) and actual == expected[side]})
    except ValueError as exc:
        raise HistoryObservationError(str(exc), readback) from exc
    return {"scope": "owned_receipt_observation_only", "stack_head_observed": False,
        "outside_scope_preservation_observed": False, "matches": all(row["passed"] for row in checks),
        "checks": checks, "readbacks": [readback]}


def history_summary(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {"scope": "latest_project_history", "action": binding["uri"].rsplit(".", 1)[-1],
        "expectation_receipt": binding["source_receipt"]["transaction_id"],
        "receipt_role": "scoped_effect_expectation_only; does_not_select_a_native_history_entry",
        "stack_head_observed": False, "outside_scope_preservation_observed": False,
        "automatic_retry": False, "automatic_compensation": False,
        "expected_observations": binding["observations"]}
