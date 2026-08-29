from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.operation_registry import OPERATION_SPECS
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS

from tests.maintenance.interface_depth_inventory import (
    INVENTORY_DOC_PATH,
    INVENTORY_PATH,
    _gateway_parser_contract_rows,
    build_interface_depth_inventory,
    render_interface_depth_inventory,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _inventory() -> dict[str, object]:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _model_values(
    inventory: dict[str, object], row: dict[str, object]
) -> list[dict[str, object]]:
    collection_name, digest_name = (
        ("argument_contracts", "argument_contract_sha256")
        if "operation" in row
        else ("field_contracts", "field_contract_sha256")
    )
    return next(
        contract["model_values"]
        for contract in inventory[collection_name]
        if contract["sha256"] == row[digest_name]
    )


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


def test_maintenance_entrypoint_runs_directly_from_the_repository_root() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(
                REPO_ROOT
                / "tests"
                / "maintenance"
                / "generate_interface_depth_inventory.py"
            ),
            "--help",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--check" in result.stdout


def test_every_public_gateway_parser_flag_is_sealed_authoritatively() -> None:
    inventory = _inventory()
    contracts = _gateway_parser_contract_rows()
    assert canonical_sha256(contracts) == inventory["source_contracts"][
        "gateway_parser_sha256"
    ]
    by_command = {row["command"]: row["parameters"] for row in contracts}
    assert {row["name"] for row in by_command["wait-topic"]} >= {
        "event-count",
        "no-timeout",
        "option-set",
        "match-set",
    }
    assert {row["name"] for row in by_command["typed-call"]} >= {
        "set",
        "append",
        "choose",
    }
    assert {row["name"] for row in by_command["operation-schema"]} >= {
        "operation",
    }


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
        assert set(row["mechanic_states"]) == set(inventory["mechanic_owners"])
        assert set(row["mechanic_states"].values()) <= {
            "gateway_owned",
            "model_owned_leak",
        }
    for contract in (*inventory["field_contracts"], *inventory["argument_contracts"]):
        for field in contract["model_values"]:
            assert field["value_ownership"] in ownership
            assert field["transport_ownership"] == "gateway_derivation"


def test_stable_scalars_artifacts_expressions_and_bound_handles_remain_distinct() -> None:
    inventory = _inventory()
    values = Counter(
        field["value_ownership"]
        for contract in (*inventory["field_contracts"], *inventory["argument_contracts"])
        for field in contract["model_values"]
    )
    assert values["stable_business_declaration"] > 0
    assert values["exact_user_artifact"] > 0
    assert values["bounded_domain_expression"] > 0
    assert values["live_bound_handle"] > 0
    assert values["reviewed_adapter"] > 0
    all_model_values = [
        field
        for contract in (*inventory["field_contracts"], *inventory["argument_contracts"])
        for field in contract["model_values"]
    ]
    assert all(
        field["value_ownership"] == "exact_user_artifact"
        for field in all_model_values
        if field["name"] == "wa_args"
    )
    assert all(
        field["value_ownership"] == "gateway_derivation"
        for field in all_model_values
        if field["name"] == "transform"
    )
    assert {
        field["name"]
        for field in all_model_values
        if field["value_ownership"] == "bounded_domain_expression"
    } == {"advanced-waql"}
    argument_contracts = {
        contract["sha256"]: contract["model_values"]
        for contract in inventory["argument_contracts"]
    }
    crash = next(
        row for row in inventory["operation_lanes"]
        if row["operation"] == "debug.testCrash"
    )
    assert crash["disposition"] == "already_deep"
    assert argument_contracts[crash["argument_contract_sha256"]] == []


def test_nested_operation_values_and_exact_paths_are_explicitly_classified() -> None:
    inventory = _inventory()
    audio_import = next(
        row for row in inventory["operation_lanes"]
        if row["operation"] == "audio.import" and row["version"] == "2025.1"
    )
    audio_values = {
        tuple(value["path"]): value["value_ownership"]
        for value in _model_values(inventory, audio_import)
    }
    assert audio_values[("declaration", "media_file")] == "exact_user_artifact"
    assert audio_values[("declaration", "output_bus")] == "live_bound_handle"
    assert audio_values[("target", "new", "semantic_kind")] == "stable_business_declaration"
    assert audio_values[("settings", "defaults", "event", "parent_handle")] == "live_bound_handle"
    assert audio_values[("settings", "defaults", "event", "name")] == "stable_business_declaration"
    assert audio_values[("declaration", "field_values", "<field_handle>")] == "live_bound_handle"
    assert audio_values[("declaration", "field_values", "<value_variant>", "scalar_business_value")] == "stable_business_declaration"
    assert audio_values[("declaration", "field_values", "<value_variant>", "reference_object_handle")] == "live_bound_handle"
    assert not any("object_path" in path for path in audio_values)

    object_create = next(
        row for row in inventory["operation_lanes"]
        if row["operation"] == "object.create" and row["version"] == "2025.1"
    )
    create_values = {
        tuple(value["path"]): value["value_ownership"]
        for value in _model_values(inventory, object_create)
    }
    assert create_values[("declaration", "new", "parent_handle")] == (
        "live_bound_handle"
    )
    assert create_values[("declaration", "new", "kind")] == (
        "stable_business_declaration"
    )
    assert create_values[("declaration", "new", "field_values")] == (
        "live_bound_handle"
    )
    assert create_values[("settings", "replace_owner_handle")] == (
        "live_bound_handle"
    )
    assert not any("object_path" in path for path in create_values)

    object_set = next(
        row for row in inventory["operation_lanes"]
        if row["operation"] == "object.set" and row["version"] == "2025.1"
    )
    set_values = {
        tuple(value["path"]): value["value_ownership"]
        for value in _model_values(inventory, object_set)
    }
    assert set_values[("declaration", "existing", "object_list")] == (
        "exact_user_artifact"
    )
    assert set_values[("declaration", "existing", "media_files")] == (
        "exact_user_artifact"
    )
    assert set_values[("declaration", "existing", "list_behavior")] == (
        "stable_business_declaration"
    )
    assert set_values[("declaration", "existing", "output_bus")] == (
        "live_bound_handle"
    )

    ui_open = next(
        row for row in inventory["native_lanes"]
        if row["version"] == "2023.1" and row["uri"] == "ak.wwise.ui.project.open"
    )
    assert any(
        value["name"] == "path"
        and value["value_ownership"] == "exact_user_artifact"
        for value in _model_values(inventory, ui_open)
    )
    cli_generate = next(
        row for row in inventory["native_lanes"]
        if row["version"] == "2025.1" and row["uri"] == "ak.wwise.cli.generateSoundbank"
    )
    assert any(
        value["name"] in {"header-file-path", "root-output-path"}
        and value["value_ownership"] == "exact_user_artifact"
        for value in _model_values(inventory, cli_generate)
    )

    object_get = next(
        row for row in inventory["native_lanes"]
        if row["version"] == "2025.1" and row["uri"] == "ak.wwise.core.object.get"
    )
    query_values = _model_values(inventory, object_get)
    assert any(
        value["channel"] == "fixed.query-object"
        and value["name"] == "path-segment"
        and value["value_ownership"] == "stable_business_declaration"
        for value in query_values
    )
    assert any(
        value["channel"] == "fixed.query-object"
        and value["name"] == "kind"
        and value["value_ownership"] == "reviewed_adapter"
        for value in query_values
    )
    assert any(
        value["channel"] == "fixed.query-object"
        and value["name"] == "advanced-waql"
        and value["value_ownership"] == "bounded_domain_expression"
        for value in query_values
    )


def test_continuation_and_shell_mechanics_are_detected_per_exact_lane() -> None:
    inventory = _inventory()
    topics = [
        row for row in inventory["native_lanes"]
        if row["item_type"] == "topic"
    ]
    assert len(topics) == 154
    assert all(
        row["mechanic_states"]["ambiguous_continuation_selection"]
        == "model_owned_leak"
        and row["continuation_commands"] == ["wait-topic", "stream-topic"]
        for row in topics
    )
    cli_rows = [
        row for row in inventory["native_lanes"]
        if row["uri"].startswith(("ak.wwise.cli.", "ak.wwise.console."))
    ]
    assert cli_rows
    assert all(
        row["mechanic_states"]["shell_quoting"] == "gateway_owned"
        for row in cli_rows
    )


def test_every_already_deep_or_prohibited_family_has_explicit_audit_evidence() -> None:
    inventory = _inventory()
    reviewed = [
        row for row in (*inventory["native_lanes"], *inventory["operation_lanes"])
        if row["disposition"] != "migration_required"
    ]
    assert reviewed
    assert all(isinstance(row["audit_evidence"], str) and row["audit_evidence"] for row in reviewed)
    report = INVENTORY_DOC_PATH.read_text(encoding="utf-8")
    for classification in {row["classification"] for row in reviewed}:
        assert f"`{classification}`" in report


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
    assert {family["github_issue"] for family in inventory["ticket_families"]} == {
        *range(77, 94),
    } - {77, 78, 79, 80, 81, 82, 83, 84, 85, 92, 93}
    assert all(
        row["owner_issue"] in {56, 57}
        for row in (*inventory["native_lanes"], *inventory["operation_lanes"])
        if row["disposition"] == "migration_required"
    )
    assert inventory["summary"]["unowned_migration_rows"] == 0


def test_completed_core_family_retains_the_authoritative_issue_84_row_seal() -> None:
    inventory = _inventory()
    completed = {
        family["id"]: family
        for family in inventory["completed_family_seals"]
    }
    core = completed["generic-core-project-object"]

    assert core["github_issue"] == 84
    assert core["row_count"] == len(core["rows"]) == 55
    assert core["rows_sha256"] == (
        "caf467378cbabccb637cd93d18cc4e87e"
        "5356d409ce110da1f040825af4245ed"
    )

    media = completed["generic-core-media-build"]
    assert media["github_issue"] == 85
    assert media["row_count"] == len(media["rows"]) == 16
    assert media["rows_sha256"] == (
        "eb0692ad57f0a504bf110f38355997bb"
        "9abca7519ed412c4ed97c223a6a0decf"
    )


def test_every_supported_named_operation_uses_or_migrates_to_the_business_path() -> None:
    inventory = _inventory()
    assert inventory["summary"]["operation_dispositions"] == {
        "already_deep": 148,
        "prohibited_boundary": 5,
    }
    for row in inventory["operation_lanes"]:
        if row["operation"] == "audio.import":
            assert row["disposition"] == "already_deep"
            assert row["input_mode"] == "business_declaration"
        elif row["operation"] in {
            "object.copy",
            "object.delete",
            "object.move",
            "object.setName",
            "object.setNotes",
            "object.setLinked",
            "object.setProperty",
            "object.setReference",
            "object.create",
            "object.createPlugin",
            "object.set",
            "object.setRTPC",
                "switchContainer.addAssignment",
                "switchContainer.removeAssignment",
                "soundbank.convertExternalSources",
                "soundbank.generate",
                "soundbank.processDefinitionFiles",
                "soundbank.setInclusions",
                "audio.importTabDelimited",
                "lua.executeCliFile",
                "lua.executeCoreFile",
                "lua.executeCoreInline",
                "ui.captureScreen",
                "ui.commands.execute",
                "ui.commands.register",
                "ui.commands.unregister",
                "debug.restartWaapiServers",
                "debug.setAsserts",
                "debug.setAutomationMode",
                "debug.testAssert",
                "debug.testCrash",
                "waapi.undoGroup",
            }:
            assert row["disposition"] == "already_deep"
            assert row["input_mode"] == "business_declaration"
        elif row["operation"] == "waapi.call":
            assert row["disposition"] == "prohibited_boundary"
            assert row["input_mode"] == "internal_canonical"
        else:
            assert row["disposition"] == "migration_required"
            assert row["owner_issue"] == 56


def test_fixed_commands_are_audited_from_their_actual_public_parameters() -> None:
    inventory = _inventory()
    issue_96_apis = {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.getAttenuationCurve",
        "ak.wwise.core.object.getPropertyAndReferenceNames",
        "ak.wwise.core.object.getPropertyInfo",
        "ak.wwise.core.object.getTypes",
        "ak.wwise.core.object.isPropertyEnabled",
        "ak.wwise.core.profiler.getGameObjects",
        "ak.wwise.core.profiler.getVoiceContributions",
        "ak.wwise.debug.getWalTree",
        "ak.wwise.debug.validateCall",
        "ak.wwise.ui.getSelectedObjects",
    }
    issue_96_rows = [
        row for row in inventory["native_lanes"] if row["uri"] in issue_96_apis
    ]
    assert len(issue_96_rows) == 47
    assert all(
        row["disposition"] == "already_deep" and row["owner_issue"] is None
        for row in issue_96_rows
    )
    object_get = next(
        row
        for row in inventory["native_lanes"]
        if row["version"] == "2025.1"
        and row["uri"] == "ak.wwise.core.object.get"
    )
    assert object_get["classification"] == "generic-fixed-query-metadata"
    assert object_get["disposition"] == "already_deep"
    assert object_get["owner_issue"] is None
    query_values = _model_values(inventory, object_get)
    assert any(
        value["channel"] == "fixed.query-object"
        and value["name"] == "advanced-waql"
        and value["value_ownership"] == "bounded_domain_expression"
        for value in query_values
    )
    names = {value["name"] for value in query_values}
    assert {"path-segment", "predicate", "relationship", "include"} <= names
    assert not {
        "where",
        "select",
        "return-field",
        "typed-advanced",
        "typed-structured",
        "advanced-return",
    } & names

    selected = next(
        row
        for row in inventory["native_lanes"]
        if row["version"] == "2023.1"
        and row["uri"] == "ak.wwise.ui.getSelectedObjects"
    )
    assert selected["disposition"] == "already_deep"
    assert _model_values(inventory, selected) == []

    for row in inventory["native_lanes"]:
        if row["classification"] == "generic-fixed-command-audited-deep":
            assert _model_values(inventory, row) == []


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
