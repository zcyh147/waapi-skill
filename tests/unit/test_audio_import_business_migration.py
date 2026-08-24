from __future__ import annotations

import json
from pathlib import Path

import pytest

from wwise_waapi.audio_import_business_migration import (
    AUDIO_IMPORT_MIGRATION_INVENTORY_CONTRACT,
    AUDIO_IMPORT_MIGRATION_RESOURCE,
    MIGRATION_DESTINATION_KINDS,
    build_audio_import_migration_inventory,
)
from wwise_waapi.audio_import_business import audio_import_business_contract
from wwise_waapi.business_declarations import SUPPORTED_WWISE_VERSIONS
from wwise_waapi.operation_composer import operation_composer_contract
from wwise_waapi.operation_registry import audio_import_composer_fragment_contract


def test_generated_inventory_covers_every_old_field_action_and_version_once() -> None:
    inventory = build_audio_import_migration_inventory()

    assert inventory["contract"] == AUDIO_IMPORT_MIGRATION_INVENTORY_CONTRACT
    assert inventory["versions"] == list(SUPPORTED_WWISE_VERSIONS)
    assert inventory["operation"] == "audio.import"
    assert inventory["cutover_policy"] == {
        "status": "deep_business_interface_public",
        "public_input_mode": "business_declaration",
        "old_interface": "retired_from_gateway_and_agent_contracts",
        "legacy_internal_role": "sealed_archive_compatibility_only",
        "fallback": False,
        "historical_evidence": "frozen_commits_only",
    }
    assert len(inventory["lanes"]) == len(SUPPORTED_WWISE_VERSIONS)

    for lane in inventory["lanes"]:
        version = lane["version"]
        fragments = audio_import_composer_fragment_contract(version)
        composer = operation_composer_contract("audio.import", version)
        assert [row["source"] for row in lane["request_options"]] == sorted(
            fragments["request_options"]
        )
        assert [row["source"] for row in lane["row_fields"]] == sorted(
            fragments["row_fields"]
        )
        assert [row["source"] for row in lane["actions"]] == sorted(
            composer["actions"]
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
                row["destination_kind"] in MIGRATION_DESTINATION_KINDS
                and row["cutover"] == "remove_old_model_input"
                for row in lane[family]
            )


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
    assert lane["limits"]["source"] == "registry_contract"
    assert lane["source_schema_digest"] == (
        audio_import_composer_fragment_contract(version)["source_schema_digest"]
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
