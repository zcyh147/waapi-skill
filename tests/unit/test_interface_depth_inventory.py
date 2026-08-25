from __future__ import annotations

import json
from collections import Counter

from wwise_waapi.operation_registry import OPERATION_SPECS
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS

from tests.maintenance.interface_depth_inventory import (
    INVENTORY_DOC_PATH,
    INVENTORY_PATH,
    build_interface_depth_inventory,
    render_interface_depth_inventory,
)


def _inventory() -> dict[str, object]:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def test_generated_inventory_is_current_and_exactly_covers_both_surfaces() -> None:
    inventory = _inventory()
    assert inventory == build_interface_depth_inventory()
    native = inventory["native_lanes"]
    operations = inventory["operation_lanes"]
    assert len(native) == 824
    assert len({(row["version"], row["item_type"], row["uri"]) for row in native}) == 824
    expected_operations = {
        (name, version)
        for name, spec in OPERATION_SPECS.items()
        for version in spec.supported_versions
    }
    assert len(operations) == 153
    assert {(row["operation"], row["version"]) for row in operations} == expected_operations
    assert INVENTORY_DOC_PATH.read_text(encoding="utf-8") == render_interface_depth_inventory(inventory)


def test_every_model_value_and_planning_mechanic_has_one_reviewed_owner() -> None:
    inventory = _inventory()
    ownership = set(inventory["ownership_classes"])
    assert set(inventory["mechanic_owners"]) == {
        "ambiguous_continuation_selection",
        "batch_layout",
        "dependency_order",
        "metadata_scope",
        "native_object_path",
        "property_or_reference_token",
        "request_fragment",
        "revision_arithmetic",
        "shell_quoting",
        "wire_type",
    }
    assert set(inventory["mechanic_owners"].values()) <= ownership
    for row in (*inventory["native_lanes"], *inventory["operation_lanes"]):
        assert row["disposition"] in {
            "already_deep",
            "migration_required",
            "prohibited_boundary",
        }
        assert set(row["leaked_mechanics"]) <= set(inventory["mechanic_owners"])
    for contract in (*inventory["field_contracts"], *inventory["argument_contracts"]):
        for encoded in contract["model_values"]:
            field = json.loads(encoded)
            assert field["value_ownership"] in ownership
            assert field["transport_ownership"] == "gateway_derivation"


def test_stable_scalars_artifacts_expressions_and_bound_handles_remain_distinct() -> None:
    inventory = _inventory()
    values = Counter(
        json.loads(encoded)["value_ownership"]
        for contract in (*inventory["field_contracts"], *inventory["argument_contracts"])
        for encoded in contract["model_values"]
    )
    assert values["stable_business_declaration"] > 0
    assert values["exact_user_artifact"] > 0
    assert values["bounded_domain_expression"] > 0
    assert values["live_bound_handle"] > 0
    assert values["reviewed_adapter"] > 0
    argument_contracts = {
        contract["sha256"]: [
            json.loads(encoded) for encoded in contract["model_values"]
        ]
        for contract in inventory["argument_contracts"]
    }
    crash = next(
        row for row in inventory["operation_lanes"]
        if row["operation"] == "debug.testCrash"
    )
    assert crash["disposition"] == "migration_required"
    assert argument_contracts[crash["argument_contract_sha256"]][0]["value_ownership"] == "gateway_derivation"


def test_every_migration_row_has_exactly_one_rollup_and_ticket_family() -> None:
    inventory = _inventory()
    tickets = {
        row: family["id"]
        for family in inventory["ticket_families"]
        for row in family["rows"]
    }
    expected = {
        f"{row['version']}|{row['item_type']}|{row['uri']}"
        for row in inventory["native_lanes"]
        if row["disposition"] == "migration_required"
    } | {
        f"{row['version']}|operation|{row['operation']}"
        for row in inventory["operation_lanes"]
        if row["disposition"] == "migration_required"
    }
    assert set(tickets) == expected
    assert all(
        row["owner_issue"] in {56, 57}
        for row in (*inventory["native_lanes"], *inventory["operation_lanes"])
        if row["disposition"] == "migration_required"
    )
    assert inventory["summary"]["unowned_migration_rows"] == 0


def test_historical_construction_baseline_is_preserved_without_depth_claim() -> None:
    baseline = _inventory()["historical_baseline"]
    assert baseline == {
        "contract": "waapi-skill.typed-request-surface/v1",
        "total_lanes": 824,
        "construction_coverage_is_depth_evidence": False,
    }
    assert set(SUPPORTED_WWISE_VERSION_KEYS) == {
        row["version"] for row in _inventory()["native_lanes"]
    }
