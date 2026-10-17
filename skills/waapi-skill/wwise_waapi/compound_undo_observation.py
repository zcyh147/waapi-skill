"""Bounded read-only state observations after a compound cancellation.

Only the immutable child preparers supply these reads. A successful cancel call
and restoration of these scoped observations are deliberately separate facts.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from .canonical import canonical_json_bytes, canonical_sha256
from .metadata_restrictions import condition_values_equal

MAX_CANCELLATION_READS = 128
MAX_CANCELLATION_OBSERVATION_BYTES = 32 * 1024


def _snapshot_equal(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(_snapshot_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_snapshot_equal(a, b) for a, b in zip(left, right))
    return condition_values_equal(left, right)



def _has_affected_prestate(prepared: Mapping[str, Any]) -> bool:
    """Do not certify restoration when the affected value was never observed."""
    plan, state = prepared.get("verification_plan"), prepared.get("pre_state")
    if not isinstance(plan, Mapping) or not isinstance(state, Mapping):
        return False
    kind = plan.get("kind")
    if kind in {"same-guid-notes", "same-guid-renamed"}:
        target = state.get("object")
        required = {"id", "notes"} if kind == "same-guid-notes" else {"id", "name", "path", "type", "parent"}
        return isinstance(target, Mapping) and required.issubset(target) and target["id"] == plan.get("object_id")
    if kind in {"same-guid-property", "same-guid-reference"}:
        before = state.get("field_before")
        return (isinstance(before, Mapping) and before.get("field") == plan.get("field")
                and "value" in before and isinstance(before.get("row"), Mapping))
    if kind == "object-linked-state":
        before = state.get("linked_before")
        return (isinstance(before, Mapping) and before.get("object_id") == plan.get("object_id")
                and before.get("property") == plan.get("property") and isinstance(before.get("linked"), bool))
    if kind == "soundbank-inclusions-exact":
        before = state.get("soundbank_inclusions")
        return (isinstance(before, Mapping) and before.get("soundbank_id") == plan.get("soundbank_id")
                and isinstance(before.get("before"), list))
    if kind == "switch-assignment-pair":
        before = state.get("switch_assignment")
        return (isinstance(before, Mapping) and before.get("switch_container_id") == plan.get("switch_container_id")
                and isinstance(before.get("assignments"), list))
    return False


def observe_cancelled_child_state(
    children: Sequence[Mapping[str, Any]],
    *,
    observe_read: Callable[[str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare sealed preflight observations; never execute a repair or retry."""
    report: dict[str, Any] = {"scope": "sealed_child_preflight_readbacks_only", "complete": True,
        "pre_state_restored": False, "readbacks": [], "children": [], "boundaries": [],
        "group_lifetime_verified": False, "external_effects_verified": False}
    snapshots: dict[bytes, tuple[Mapping[str, Any], list[int]]] = {}
    incomplete_children: set[int] = set()
    for index, child in enumerate(children):
        prepared = child.get("prepared_operation")
        reads = prepared.get("preflight_reads") if isinstance(prepared, Mapping) else None
        if not isinstance(prepared, Mapping) or not _has_affected_prestate(prepared):
            report["boundaries"].append({"child_index": index, "reason": "affected_child_prestate_not_observed"})
            report["complete"] = False
            incomplete_children.add(index)
        if not isinstance(reads, list) or not reads:
            report["boundaries"].append({"child_index": index, "reason": "sealed_child_preflight_reads_missing"})
            report["complete"] = False
            incomplete_children.add(index)
            continue
        for read in reads:
            if (not isinstance(read, Mapping) or not isinstance(read.get("uri"), str)
                    or any(not isinstance(read.get(key), Mapping) for key in ("args", "options", "result"))):
                report["boundaries"].append({"child_index": index, "reason": "sealed_read_incomplete"})
                report["complete"] = False
                incomplete_children.add(index)
                continue
            key = canonical_json_bytes({name: read[name] for name in ("uri", "args", "options")})
            previous = snapshots.get(key)
            if previous is not None:
                if not _snapshot_equal(previous[0]["result"], read["result"]):
                    report["boundaries"].append({"child_index": index, "reason": "sealed_preflight_observations_disagree"})
                    report["complete"] = False
                    incomplete_children.update([index, *previous[1]])
                previous[1].append(index)
            else:
                snapshots[key] = (read, [index])
    matched_by_child: dict[int, list[bool]] = {index: [] for index in range(len(children))}
    for index, (before, child_indices) in enumerate(snapshots.values()):
        if index >= MAX_CANCELLATION_READS:
            report["complete"] = False
            report["boundaries"].append({"reason": "cancellation_read_bound_reached", "maximum": MAX_CANCELLATION_READS})
            break
        record: dict[str, Any] = {"read_index": index, "child_indices": sorted(set(child_indices)),
            "uri": before["uri"], "before_sha256": canonical_sha256(before["result"]), "pre_state_match": False}
        try:
            observed = observe_read(before["uri"], before["args"], before["options"])
            record["call"] = observed.get("call")
            if observed.get("error") is not None:
                raise ValueError(str(observed["error"]))
            result = observed.get("result")
            if not isinstance(result, Mapping):
                raise ValueError("Cancellation read did not return a complete native object")
            record.update(after_sha256=canonical_sha256(result), call=observed.get("call"),
                          pre_state_match=_snapshot_equal(before["result"], result))
        except Exception as exc:  # a failed observation never changes the write's terminal outcome
            report["complete"] = False
            incomplete_children.update(child_indices)
            record["observation_error"] = {"type": type(exc).__name__, "message": str(exc)[:512]}
        if len(canonical_json_bytes(report)) + len(canonical_json_bytes(record)) > MAX_CANCELLATION_OBSERVATION_BYTES - 4096:
            report["complete"] = False
            report["boundaries"].append({"reason": "cancellation_observation_byte_bound_reached",
                                          "maximum_bytes": MAX_CANCELLATION_OBSERVATION_BYTES})
            break
        report["readbacks"].append(record)
        for child_index in set(child_indices):
            matched_by_child[child_index].append(record["pre_state_match"])
    for index, matches in matched_by_child.items():
        expected_count = sum(index in child_indices for _read, child_indices in snapshots.values())
        complete = index not in incomplete_children and bool(expected_count) and len(matches) == expected_count
        report["children"].append({"index": index, "complete": complete,
                                   "pre_state_match": complete and all(matches)})
    report["pre_state_restored"] = report["complete"] and bool(snapshots) and all(
        row["pre_state_match"] for row in report["children"])
    return report
