"""Bounded channel observations for the existing log-control transaction seam."""

from collections import Counter
from typing import Any, Mapping

from .builders.schema import validate_resolved_semantic_result
from .canonical import canonical_json_bytes
from .runtime_inspection_business_contracts import LOG_ADD_ITEM_URI, LOG_GET_URI

MAX_LOG_OBSERVATION_ITEMS = 1000
MAX_LOG_OBSERVATION_BYTES = 64 * 1024


def channel_snapshot(result: Any, *, version: str) -> dict[str, Any]:
    """Keep complete rows only; an oversized observation is never truncated."""
    if not isinstance(result, Mapping) or not isinstance(result.get("items"), list):
        raise ValueError("Log observation requires an object with an items array.")
    rows = result["items"]
    size = len(canonical_json_bytes(result))
    if len(rows) > MAX_LOG_OBSERVATION_ITEMS or size > MAX_LOG_OBSERVATION_BYTES:
        return {"outcome": "oversized", "item_count": len(rows), "size_bytes": size}
    validate_resolved_semantic_result(LOG_GET_URI, result, version=version)
    return {"outcome": "complete", "items": list(rows), "item_count": len(rows)}


def same_channel_contents(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return (before.get("outcome") == after.get("outcome") == "complete"
        and Counter(canonical_json_bytes(row) for row in before["items"])
        == Counter(canonical_json_bytes(row) for row in after["items"]))


def compare_channel(plan: Mapping[str, Any], before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    observation = {"channel": plan["channel"], "before_items": before["item_count"],
        "after_items": after["item_count"], "exclusive_causation_verified": False,
        "continuing_channel_state_verified": False, "entry_identity_verified": False}
    if after["outcome"] != "complete":
        return {**observation, "outcome": "oversized", "size_bytes": after["size_bytes"], "effect_observed": False}
    if plan["console"]:
        return {**observation, "outcome": "console_log_unobservable", "effect_observed": False}
    prior, current = before["items"], after["items"]
    if plan["uri"] == LOG_ADD_ITEM_URI:
        matches = lambda row: row["message"] == plan["message"] and row["severity"] == plan["severity"]
        old_count, new_count = sum(map(matches, prior)), sum(map(matches, current))
        observed = new_count > old_count
        return {**observation, "outcome": "new_matching_item" if observed else "no_matching_increase",
            "matching_items_before": old_count, "matching_items_after": new_count,
            "competing_items_after": len(current) - new_count, "effect_observed": observed}
    overlap = sum((Counter(canonical_json_bytes(row) for row in prior)
        & Counter(canonical_json_bytes(row) for row in current)).values())
    return {**observation, "outcome": "prior_contents_absent" if not overlap else "indistinguishable_prior_contents",
        "indistinguishable_prior_items_after": overlap, "post_channel_empty": not current,
        "competing_items_after": len(current) - overlap, "effect_observed": not overlap}
