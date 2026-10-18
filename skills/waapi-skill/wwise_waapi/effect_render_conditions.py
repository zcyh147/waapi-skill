"""Owned Effect rendering conditions shared by creation and field edits.

The five pinned Authoring Help ``rendering_effects`` sections specify that
rendering a later Effect also renders its predecessors. Bypass precedence
concerns processing; it does not make a stored Boolean combination invalid.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


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
