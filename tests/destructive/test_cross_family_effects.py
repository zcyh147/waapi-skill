"""Effect-slot append membership and ownership through the public Gateway.

This checks real list members and references, not audible processing order.
"""

from __future__ import annotations

from typing import Any
import uuid

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _bind_business_object,
    _complete_business_draft,
    _created_object_id,
    _discover_business_type,
    _start_business_draft,
    _update_business_draft,
    workflow_sandbox_runtime,
)

pytestmark = [pytest.mark.live, pytest.mark.destructive]


def _select(runtime: Any, owner: str, field: str) -> list[dict[str, Any]]:
    # Only fixed list/reference selectors and Gateway-observed canonical GUIDs
    # enter the advanced read. No caller-authored mutation payload is involved.
    return runtime.gateway([
        "query-object", "--advanced-waql", f'from object "{owner}" select @{field}',
        "--max-results", "8",
    ], live=True)["objects"]


def _bindings(runtime: Any, owner: str) -> dict[str, tuple[str, str]]:
    if runtime.version == "2022.1":
        result = {}
        for index in range(4):
            rows = _select(runtime, owner, f"Effect{index}")
            assert len(rows) <= 1, rows
            if rows:
                result[str(index)] = (rows[0]["id"], rows[0]["name"])
        return result
    slots = _select(runtime, owner, "Effects")
    assert all(row["type"] == "EffectSlot" for row in slots), slots
    assert len({row["id"] for row in slots}) == len(slots), slots
    result = {}
    for slot in slots:
        effects = _select(runtime, slot["id"], "Effect")
        assert len(effects) == 1, effects
        result[slot["id"]] = (effects[0]["id"], effects[0]["name"])
    return result


def test_cross_family_effect_append_preserves_existing_slots_and_bindings(
    workflow_sandbox_runtime: Any,
) -> None:
    runtime = workflow_sandbox_runtime
    if runtime.version == "2021.1":
        code, result = runtime.raw_gateway(["draft-start", "object.createPlugin"])
        assert code == 2 and result["error_code"] == "UNAVAILABLE_IN_VERSION", result
        runtime.category_results.append({
            "category": "cross-family-effects", "status": "PASS",
            "verifier_strength": "explicit_2021_unsupported_boundary_no_mutation",
        })
        return
    runtime.gateway(["query-schema", "--advanced"], live=False)
    draft = _start_business_draft(runtime, "object.create")
    root = "Containers" if runtime.version == "2025.1" else "Actor-Mixer Hierarchy"
    parent = _bind_business_object(runtime, draft, path_segments=(root, "Default Work Unit"))
    _update_business_draft(runtime, draft, "draft-declare-new", [
        "--declaration-id", "owner", "--parent-handle", parent,
        "--name", "CrossFamilyEffects_" + uuid.uuid4().hex[:10], "--kind", "sound-sfx",
    ], live=False)
    owner = _created_object_id(_complete_business_draft(runtime, draft)["execute"])
    before = _bindings(runtime, owner)
    assert before == {}, before
    transactions = []
    for index in range(2):
        draft = _start_business_draft(runtime, "object.createPlugin")
        handle = _bind_business_object(runtime, draft, object_id=owner)
        plugin_type = _discover_business_type(runtime, draft, meaning="Wwise Gain",
                                             role="effect", expected_label="Wwise Gain")
        _update_business_draft(runtime, draft, "draft-declare-existing", [
            "--declaration-id", "gain", "--object-handle", handle,
            "--field", "plugin_role", "effect", "--field", "plugin_name", f"Gain_{index}",
            "--field", "plugin_type_handle", plugin_type,
        ], live=False)
        result = _complete_business_draft(runtime, draft)
        transactions.append(result["verify"]["transaction_id"])
        after = _bindings(runtime, owner)
        assert len(after) == len(before) + 1, (before, after)
        assert all(after.get(slot) == effect for slot, effect in before.items()), (before, after)
        added = set(after) - set(before)
        assert len(added) == 1, (before, after)
        assert after[added.pop()][1] == f"Gain_{index}", after
        before = after
    runtime.category_results.append({
        "category": "cross-family-effects", "status": "PASS",
        "verifier_strength": "two_appends_preserve_old_slot_guids_and_effect_bindings_not_audible_order",
        "transaction_ids": transactions,
    })
