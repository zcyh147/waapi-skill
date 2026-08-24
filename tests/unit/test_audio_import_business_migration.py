from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.maintenance.audio_import_business_migration import (
    AUDIO_IMPORT_MIGRATION_INVENTORY_CONTRACT,
    AUDIO_IMPORT_MIGRATION_RESOURCE,
    build_audio_import_migration_inventory,
    load_frozen_audio_import_contract,
)
from wwise_waapi.operation_registry import audio_import_business_contract
from wwise_waapi.business_declarations import SUPPORTED_WWISE_VERSIONS


def test_generated_inventory_covers_every_old_field_action_and_version_once() -> None:
    inventory = build_audio_import_migration_inventory()

    assert inventory["contract"] == AUDIO_IMPORT_MIGRATION_INVENTORY_CONTRACT
    assert inventory["versions"] == list(SUPPORTED_WWISE_VERSIONS)
    assert inventory["operation"] == "audio.import"
    assert inventory["cutover_policy"] == {
        "status": "deep_business_interface_public",
        "public_input_mode": "business_declaration",
        "old_interface": "deleted_from_packaged_runtime",
        "legacy_internal_role": "test_maintenance_frozen_contract_only",
        "fallback": False,
        "historical_evidence": "frozen_commits_only",
    }
    assert len(inventory["lanes"]) == len(SUPPORTED_WWISE_VERSIONS)

    frozen = load_frozen_audio_import_contract()
    destinations = set(inventory["destination_kinds"])
    for lane in inventory["lanes"]:
        version = lane["version"]
        fragments = frozen["versions"][version]
        assert [row["source"] for row in lane["request_options"]] == sorted(
            fragments["request_options"]
        )
        assert [row["source"] for row in lane["row_fields"]] == sorted(
            fragments["row_fields"]
        )
        assert [row["source"] for row in lane["actions"]] == sorted(
            {
                "add_import_row",
                "clear_import_default",
                "clear_import_option",
                "clear_import_row_field",
                "remove_import_row",
                "set_import_default",
                "set_import_operation",
                "set_import_option",
                "set_import_row_field",
            }
        )
        assert len({row["source"] for row in lane["request_options"]}) == len(
            lane["request_options"]
        )
        assert len({row["source"] for row in lane["row_fields"]}) == len(
            lane["row_fields"]
        )
        assert len({row["source"] for row in lane["actions"]}) == len(
            lane["actions"]
        )
        for family in ("request_options", "row_fields", "nested_fields", "actions"):
            assert all(
                row["destination_kind"] in destinations
                and row["cutover"] == "remove_old_model_input"
                for row in lane[family]
            )
        expected_contract_inventory = {
            f"{family}.{source}": dict(_flatten_contract(contract))
            for family in ("request_options", "row_fields", "actions")
            for source, contract in fragments[family].items()
        }
        assert set(lane["source_contract_inventory"]) == set(
            expected_contract_inventory
        )
        for source, expected_leaves in expected_contract_inventory.items():
            recorded = lane["source_contract_inventory"][source]
            assert recorded["contract_leaves"] == expected_leaves
            assert recorded["leaf_count"] == len(expected_leaves)
            assert recorded["migration_source"] == source.partition(".")[2]


def test_inventory_keeps_native_mechanics_gateway_owned_and_dynamic_fields_bound() -> None:
    inventory = build_audio_import_migration_inventory()

    for lane in inventory["lanes"]:
        by_field = {row["source"]: row for row in lane["row_fields"]}
        assert by_field["object_path"]["destination_kind"] == "gateway_derivation"
        assert by_field["object_type"]["destination_kind"] == "gateway_derivation"
        assert by_field["properties"]["destination_kind"] == "live_field_handle"
        assert by_field["references"]["destination_kind"] == "live_field_handle"
        assert by_field["audio_file"]["destination_kind"] == "exact_user_artifact"
        assert by_field["audio_file_base64"]["destination_kind"] == (
            "exact_user_artifact"
        )
        nested = {row["source"]: row for row in lane["nested_fields"]}
        assert nested["properties[].name"]["destination"] == "field_handle"
        assert nested["properties[].value"]["destination"] == "typed_field_value"
        assert nested["references[].name"]["destination"] == "field_handle"
        assert nested["references[].target"]["destination"] == (
            "bound_object_handle"
        )
        assert nested["event.path"]["destination"] == "bound_event_parent_handle"
        assert nested["event.action"]["destination"] == "event_action"
        assert nested["add_import_row.assignment.mode"]["destination"] == (
            "switch_value.mode"
        )
        assert nested["add_import_row.assignment.value"]["destination"] == (
            "switch_value"
        )


def test_inventory_exhaustively_records_defaults_enums_and_assignment_shape() -> None:
    inventory = build_audio_import_migration_inventory()

    for lane in inventory["lanes"]:
        leaves = {
            f"{source}{pointer}": value
            for source, inventory in lane["source_contract_inventory"].items()
            for pointer, value in inventory["contract_leaves"].items()
        }
        assert leaves[
            "request_options.import_operation/default"
        ] == "createNew"
        import_modes = {
            value
            for path, value in leaves.items()
            if path.startswith("request_options.import_operation/enum/")
        }
        assert import_modes == {"createNew", "useExisting", "replaceExisting"}
        assignment_modes = {
            value
            for path, value in leaves.items()
            if path.startswith(
                "actions.add_import_row/field_contracts/assignment/oneOf/"
            )
            and path.endswith("/properties/mode/const")
        }
        assert assignment_modes == {"none", "switch"}
        assert any(
            path.startswith(
                "actions.add_import_row/field_contracts/assignment/oneOf/"
            )
            and path.endswith("/properties/value/type")
            and value == "string"
            for path, value in leaves.items()
        )
        default_names = {
            value
            for path, value in leaves.items()
            if path.startswith(
                "actions.set_import_default/field_contracts/name/enum/"
            )
        }
        assert default_names == {
            row["source"] for row in lane["row_fields"]
        }


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_inventory_pins_version_delta_omission_and_safety_rules(version: str) -> None:
    lane = next(
        row
        for row in build_audio_import_migration_inventory()["lanes"]
        if row["version"] == version
    )
    options = {row["source"]: row for row in lane["request_options"]}
    checkout = options["auto_check_out_to_source_control"]
    assert checkout["available"] is (version in {"2023.1", "2024.1", "2025.1"})
    assert checkout["omission"] == "gateway_version_default_false_or_absent"

    row_fields = {row["source"]: row for row in lane["row_fields"]}
    assert all(row["omission"] for row in row_fields.values())
    assert row_fields["originals_subfolder"]["omission"] == "preserve_omission"
    assert row_fields["notes"]["omission"] == "preserve_omission"
    assert row_fields["audio_source_notes"]["omission"] == "preserve_omission"
    assert lane["safety_rules"]
    assert lane["limits"]["source"] == "frozen_pre_cutover_contract"
    assert lane["source_schema_digest"] == (
        load_frozen_audio_import_contract()["versions"][version][
            "source_schema_digest"
        ]
    )


def test_committed_inventory_resource_matches_generator_exactly() -> None:
    committed = json.loads(Path(AUDIO_IMPORT_MIGRATION_RESOURCE).read_text("utf-8"))
    assert committed == build_audio_import_migration_inventory()


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_every_migration_destination_is_owned_by_the_deep_adapter(version: str) -> None:
    contract = audio_import_business_contract(version)
    lane = next(
        row
        for row in build_audio_import_migration_inventory()["lanes"]
        if row["version"] == version
    )
    owned = {
        *contract["settings"],
        *contract["declaration_fields"],
        *contract["gateway_derivations"],
        *contract["live_handles"],
        *contract["exact_user_artifacts"],
        "mode",
        "add_to_source_control",
        "check_out_from_source_control",
        "audio_source_notes",
        "dialogue_event_directive",
        "event_declaration",
        "language",
        "notes",
        "originals_subfolder",
        "property_field_values",
        "reference_field_values",
        "switch_value",
        "switch_value.mode",
        "event_action",
        "bound_event_parent_handle",
        "inline_wav.relative_path",
        "inline_wav.opaque_base64",
        "target_parent_handle.form",
        "bound_parent_expected_type",
        "bound_parent_exact_name",
        "bound_parent_scope_handle",
        "batch.mode",
        "batch.settings",
        "batch.settings.omit",
        "batch.explicit_defaults",
        "batch.explicit_defaults.omit",
        "declaration.add",
        "declaration.revise",
        "declaration.revise_with_omission",
        "declaration.remove",
    }
    for family in ("request_options", "row_fields", "nested_fields", "actions"):
        assert {row["destination"] for row in lane[family]} <= owned


def _flatten_contract(value: object, pointer: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        if not value:
            return [(pointer, {})]
        return [
            row
            for key in sorted(value)
            for row in _flatten_contract(
                value[key],
                f"{pointer}/{str(key).replace('~', '~0').replace('/', '~1')}",
            )
        ]
    if isinstance(value, list):
        if not value:
            return [(pointer, [])]
        return [
            row
            for index, item in enumerate(value)
            for row in _flatten_contract(item, f"{pointer}/{index}")
        ]
    return [(pointer, value)]
