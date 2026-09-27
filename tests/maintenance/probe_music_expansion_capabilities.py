"""Read-only public contract probes on lifecycle-owned SampleProject copies.

These explicitly selected developer probes establish oracle feasibility, not
music playback or business mutation acceptance. They intentionally expose
unsupported reads as failures and are excluded from automatic test collection.
A rejected read remains failed probe evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime


pytestmark = [pytest.mark.live, pytest.mark.destructive]


_GUID = re.compile(
    r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}"
)


def _assert_guid(value: Any) -> None:
    assert isinstance(value, str) and _GUID.fullmatch(value), value
    assert value != "{00000000-0000-0000-0000-000000000000}", value


def _assert_query_rows(code: int, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    # A metadata clarification can be ok/code 0 without a dispatched object read.
    assert code == 0 and payload.get("ok") is True, payload
    assert payload.get("status") == "ok", payload
    if "response_integrity" in payload:
        integrity = payload["response_integrity"]
        assert isinstance(integrity, Mapping), payload
        assert integrity.get("complete") is True and integrity.get("truncated") is False, payload
    rows = payload.get("objects")
    assert isinstance(rows, list) and all(isinstance(row, dict) for row in rows), payload
    assert type(payload.get("count")) is int and payload["count"] == len(rows), payload
    return rows


# Projection keys are native tokens selected by live metadata, not the input
# display meanings: Gateway _project_query_business_rows nests them under
# properties/references. The pinned WObjects RTPC definition exposes Curve as
# a reference, so that probe proves only a readable Curve identity, not points.
@pytest.mark.parametrize("object_id,field,projection,token,value_kind", [
    ("{492A2BCA-08ED-4ED9-BDA3-B4D876D2D830}", "Playlist Root",
     "references", "PlaylistRoot", "reference"),
    ("{DE090E27-2F5C-436F-A239-D02F8D5016B2}", "No. of Loops",
     "properties", "LoopCount", "integer"),
    ("{DE090E27-2F5C-436F-A239-D02F8D5016B2}", "Segment",
     "references", "Segment", "reference"),
    ("{B24173D4-7534-4C19-ACE0-F1F1B0EBD535}", "Play Source Post-exit",
     "properties", "PlaySourcePostExit", "boolean"),
    ("{B24173D4-7534-4C19-ACE0-F1F1B0EBD535}", "Play Destination Pre-entry",
     "properties", "PlayDestinationPreEntry", "boolean"),
    ("{B24173D4-7534-4C19-ACE0-F1F1B0EBD535}", "Exit Source At",
     "properties", "ExitSourceAt", "integer"),
    ("{764CAA28-CA72-4B8D-B0BB-151FABE8DA93}", "Curve",
     "references", "Curve", "reference"),
    ("{764CAA28-CA72-4B8D-B0BB-151FABE8DA93}", "Control Input",
     "references", "ControlInput", "reference"),
    ("{764CAA28-CA72-4B8D-B0BB-151FABE8DA93}", "Property",
     "properties", "PropertyName", "string"),
])
def test_music_expansion_public_field_read(
    workflow_sandbox_runtime, object_id, field, projection, token, value_kind,
):
    runtime = workflow_sandbox_runtime
    evidence = {
        "category": "music-expansion-public-field-" + field,
        "status": "FAIL",
        "stage": "gateway_read",
        "verifier_strength": "read_only_typed_public_field_not_complete_business_oracle",
        "object_id": object_id, "field": field,
        "expected_projection": projection, "expected_token": token,
        "expected_value_kind": value_kind,
        "transaction_ids": [],
    }
    runtime.category_results.append(evidence)
    code, payload = runtime.raw_gateway([
        "query-object", "--exact-id", object_id, "--include-field", field,
    ])
    evidence.update(gateway_result=payload, gateway_exit_code=code, stage="query_result")
    rows = _assert_query_rows(code, payload)
    assert payload.get("query_bound") == {"mode": "exact-object"}, payload
    assert len(rows) == 1, payload
    assert rows[0].get("id") == object_id, payload
    evidence["stage"] = "requested_field_projection"
    projected = rows[0].get(projection)
    assert isinstance(projected, Mapping) and set(projected) == {token}, payload
    value = projected[token]
    evidence["stage"] = "requested_field_value"
    if value_kind == "reference":
        assert isinstance(value, Mapping), payload
        _assert_guid(value.get("id"))
        evidence["reference_scope"] = "target_identity_only_not_nested_state_or_curve_points"
    elif value_kind == "integer":
        assert type(value) is int, payload
    elif value_kind == "boolean":
        assert type(value) is bool, payload
    else:
        assert value_kind == "string", value_kind
        assert isinstance(value, str) and value.strip(), payload
    evidence.update(status="PASS", stage="complete", observed_value=value)


@pytest.mark.parametrize("field", ["Arguments", "Entries"])
def test_music_switch_public_collection_read(workflow_sandbox_runtime, field):
    runtime = workflow_sandbox_runtime
    evidence = {
        "category": "music-switch-public-collection-" + field,
        "status": "FAIL",
        "stage": "advanced_contract_disclosure",
        "verifier_strength": "read_only_public_collection_not_path_configuration_acceptance",
        "transaction_ids": [],
    }
    runtime.category_results.append(evidence)
    runtime.gateway(["query-schema", "--advanced"], live=False)
    evidence["stage"] = "gateway_read"
    code, payload = runtime.raw_gateway([
        "query-object", "--advanced-waql",
        'from object "{A9D070F3-3BD9-49EB-9D8B-5D3312173FB4}" select @' + field,
        "--max-results", "16",
    ])
    evidence.update(gateway_result=payload, gateway_exit_code=code, stage="query_result")
    rows = _assert_query_rows(code, payload)
    # query-object uses query_bound/limit_reached, not Draft response_integrity.
    # A full 16-row result cannot prove this collection was completely observed.
    assert payload.get("query_bound") == {"mode": "gateway-appended-take", "value": 16}, payload
    assert payload.get("limit_reached") is False, payload
    assert 0 < len(rows) < 16, payload
    evidence["stage"] = "collection_identities"
    for row in rows:
        _assert_guid(row.get("id"))
        assert isinstance(row.get("type"), str) and row["type"], payload
    assert len({row["id"].casefold() for row in rows}) == len(rows), payload
    evidence.update(
        status="PASS", stage="complete", observed_count=len(rows),
        coverage_scope="complete_collection_identity_read_not_complete_path_mapping_or_order",
    )
