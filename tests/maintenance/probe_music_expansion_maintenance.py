"""Explicit developer probes for existing music edits, including capability gaps.

Not automatically collected: these investigations retain unsupported attempts
as failures, rather than blessing them as business acceptance.
"""

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _complete_object_metadata_business_transaction, workflow_sandbox_runtime,
)


pytestmark = [pytest.mark.live, pytest.mark.destructive]


@pytest.mark.parametrize("object_id,field,token,value,preserved", [
    ("{DE090E27-2F5C-436F-A239-D02F8D5016B2}", "No. of Loops", "LoopCount", 2, ()),
    ("{B24173D4-7534-4C19-ACE0-F1F1B0EBD535}", "Play Source Post-exit", "PlaySourcePostExit", False,
     ("Play Destination Pre-entry", "Exit Source At")),
])
def test_music_existing_scalar_maintenance(
    workflow_sandbox_runtime, object_id, field, token, value, preserved,
):
    runtime = workflow_sandbox_runtime
    evidence = {"category": "music-existing-scalar-" + token, "status": "FAIL",
                "verifier_strength": "public_preview_execute_verify_and_independent_exact_field_read",
                "scope": "existing_scalar_only_not_playlist_order_or_full_transition",
                "transaction_ids": []}
    runtime.category_results.append(evidence)
    command = ["query-object", "--exact-id", object_id]
    for meaning in (field, *preserved):
        command.extend(("--include-field", meaning))
    if token == "LoopCount":
        command.extend(("--include-field", "IsLoopingInfinite"))
    before = runtime.gateway(command, live=True)
    assert before.get("status") == "ok" and before.get("count") == 1, before
    before_row = before["objects"][0]
    assert token in before_row.get("properties", {}), before
    assert before_row["properties"][token] != value, "fixture already has the requested value"
    evidence["before"] = before_row
    expected_properties = {**before_row["properties"], token: value}
    if token == "LoopCount":
        infinite = before_row["properties"].get("IsLoopingInfinite")
        assert type(infinite) is bool, before
        if infinite:
            # Wwise 2025 disables finite count while infinite looping is on.
            # The discovered dependency is a separate approved transaction.
            dependency = _complete_object_metadata_business_transaction(
                runtime, operation="object.setProperty", object_id=object_id,
                field_name="IsLoopingInfinite", value=False,
            )
            evidence["transaction_ids"].append(dependency["verify"]["transaction_id"])
            expected_properties["IsLoopingInfinite"] = False
    result = _complete_object_metadata_business_transaction(
        runtime, operation="object.setProperty", object_id=object_id, field_name=field, value=value,
    )
    evidence["transaction_ids"].append(result["verify"]["transaction_id"])
    after = runtime.gateway(command, live=True)
    assert after.get("status") == "ok" and after.get("count") == 1, after
    after_row = after["objects"][0]
    expected = {**before_row, "properties": expected_properties}
    evidence["after"] = after_row
    assert after_row == expected, (before_row, after_row)
    evidence["status"] = "PASS"
