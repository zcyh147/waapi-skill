from __future__ import annotations

import math
from collections import Counter
from copy import deepcopy
from typing import Mapping

import pytest

from wwise_waapi.authorization import (
    DEFAULT_TRANSACTION_AUTHORIZATION_MODES,
    EXPLICIT_CONFIRMATION_ONLY_URIS,
    AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,
)
from wwise_waapi.capabilities import CapabilityCatalog
from wwise_waapi.execution_contracts import (
    LIFECYCLE_COMPANIONS,
    POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY,
    POST_EXECUTION_PROJECT_GUARD_REVALIDATE,
    PROJECT_GUARD_INVARIANT,
    PROJECT_GUARD_TRANSITION_TO_NONE,
    PROJECT_GUARD_TRANSITION_TO_PATH,
    ExecutionContractRegistry,
)
from wwise_waapi.native_surface_policy import (
    NativeSurfacePolicyError,
    load_native_surface_policy,
    validate_native_surface_policy,
)
from wwise_waapi.operation_registry import (
    FORBIDDEN_MODEL_AUTHORED_COMMAND_FIELDS,
)
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


EXECUTABLE_ROUTES = {
    "fixed_command",
    "bounded_call",
    "bounded_topic_wait",
    "transaction",
    "managed_transaction",
    "isolated_transaction",
    "compound_transaction_member",
}
TRANSACTION_ROUTES = {
    "transaction",
    "managed_transaction",
    "isolated_transaction",
    "compound_transaction_member",
}


def test_every_registry_row_has_one_complete_route_contract() -> None:
    registry = ExecutionContractRegistry()
    rows = [entry for version in SUPPORTED_WWISE_VERSION_KEYS for entry in registry.entries(version)]

    assert len(rows) == 814
    assert len({(row.version, row.item_type, row.uri) for row in rows}) == 814
    assert Counter(row.route for row in rows) == {
        "bounded_call": 72,
        "bounded_topic_wait": 152,
        "excluded": 6,
            "fixed_command": 56,
        "isolated_transaction": 141,
            "managed_transaction": 248,
        "compound_transaction_member": 15,
        "transaction": 124,
    }

    for row in rows:
        if row.route == "excluded":
            assert row.gateway_commands == ()
            assert row.timeout_seconds == 0
            assert row.result_limit_bytes == 0
            assert row.excluded_reason
            assert row.requires_authorization is False
            assert row.accepted_authorization_modes == ()
            continue

        assert row.route in EXECUTABLE_ROUTES
        assert row.gateway_commands
        assert math.isfinite(row.timeout_seconds) and row.timeout_seconds > 0
        assert 0 < row.result_limit_bytes <= 1024 * 1024
        assert row.verification_strategy != "none"
        assert row.program_case
        assert row.requires_authorization is (row.route in TRANSACTION_ROUTES)
        if row.route not in TRANSACTION_ROUTES:
            assert row.accepted_authorization_modes == ()
        elif row.effect == "read" or row.uri in EXPLICIT_CONFIRMATION_ONLY_URIS:
            assert row.accepted_authorization_modes == (
                AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,
            )
        else:
            assert (
                row.accepted_authorization_modes
                == DEFAULT_TRANSACTION_AUTHORIZATION_MODES
            )


def test_all_transaction_reads_are_explicit_confirmation_only() -> None:
    registry = ExecutionContractRegistry()
    rows = [
        entry
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for entry in registry.entries(version)
        if entry.route in TRANSACTION_ROUTES and entry.effect == "read"
    ]

    assert len(rows) == 47
    assert len({row.uri for row in rows}) == 12
    assert all(
        row.accepted_authorization_modes
        == (AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,)
        for row in rows
    )


def test_all_six_project_transition_apis_have_explicit_versioned_guard_modes() -> None:
    registry = ExecutionContractRegistry()
    rows = {
        (entry.version, entry.uri): entry
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for entry in registry.entries(version)
        if entry.uri.startswith(("ak.wwise.ui.project.", "ak.wwise.console.project."))
    }

    assert len(rows) == 16
    for (_, uri), entry in rows.items():
        expected_mode = (
            PROJECT_GUARD_TRANSITION_TO_NONE
            if uri.endswith(".close")
            else PROJECT_GUARD_TRANSITION_TO_PATH
        )
        assert entry.project_guard_mode == expected_mode
        assert entry.verification_strategy == "result_schema_and_project_transition"
        if uri.endswith((".open", ".create")):
            assert entry.route == "isolated_transaction"


def test_only_reviewed_explicit_project_cli_calls_skip_the_post_execution_project_probe() -> None:
    registry = ExecutionContractRegistry()
    rows = [
        entry
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for entry in registry.entries(version)
    ]
    context_only = [
        entry
        for entry in rows
        if entry.post_execution_project_guard_policy
        == POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY
    ]

    assert len(context_only) == 20
    assert {entry.version for entry in context_only} == set(SUPPORTED_WWISE_VERSION_KEYS)
    assert {entry.uri for entry in context_only} == {
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.migrate",
        "ak.wwise.cli.tabDelimitedImport",
    }
    assert all(entry.project_guard_mode == PROJECT_GUARD_INVARIANT for entry in context_only)
    assert all(entry.verification_strategy == "result_schema" for entry in context_only)
    assert all(
        entry.post_execution_project_guard_policy
        == POST_EXECUTION_PROJECT_GUARD_REVALIDATE
        for entry in rows
        if entry not in context_only
    )


def test_execution_contract_and_reflected_schema_are_one_to_one() -> None:
    catalog = CapabilityCatalog()

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        rows = catalog.entries(version)
        assert all(row.schema_status == "ok" for row in rows)
        assert all(isinstance(row.schema, Mapping) for row in rows)
        assert all(row.execution_contract["version"] == version for row in rows)
        assert all(row.execution_contract["uri"] == row.uri for row in rows)
        assert all(row.execution_contract["item_type"] == row.item_type for row in rows)


def test_route_families_have_explicit_program_cleanup_or_confirmation_contracts() -> None:
    registry = ExecutionContractRegistry()
    executable = [
        entry
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for entry in registry.executable_entries(version)
    ]

    topics = [entry for entry in executable if entry.item_type == "topic"]
    assert topics
    assert all(entry.route == "bounded_topic_wait" for entry in topics)
    assert all(entry.program_case == "subscribe-event-unsubscribe" for entry in topics)

    transactions = [entry for entry in executable if entry.route in TRANSACTION_ROUTES]
    assert transactions
    assert all(entry.gateway_commands == ("request-schema",) for entry in transactions)
    assert all(entry.requires_authorization for entry in transactions)


def test_all_undo_member_rows_route_only_to_same_connection_composite() -> None:
    catalog = CapabilityCatalog()
    rows = [
        entry
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for entry in catalog.entries(version)
        if entry.uri
        in {
            "ak.wwise.core.undo.beginGroup",
            "ak.wwise.core.undo.endGroup",
            "ak.wwise.core.undo.cancelGroup",
        }
    ]

    assert len(rows) == 15
    assert all(entry.execution_mode == "compound_transaction_member" for entry in rows)
    assert all(entry.preferred_route == "transaction_operation" for entry in rows)
    assert all(entry.transaction_operations == ("waapi.undoGroup",) for entry in rows)
    assert all("waapi.call" not in entry.transaction_operations for entry in rows)
    assert all(entry.execution_contract["lifecycle_strategy"] == "same_connection_compound_only" for entry in rows)


def test_managed_session_openers_name_version_valid_companion_routes() -> None:
    registry = ExecutionContractRegistry()

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        entries = registry.entries(version)
        by_uri = {entry.uri: entry for entry in entries}
        for opener, companions in LIFECYCLE_COMPANIONS.items():
            if opener not in by_uri:
                continue
            contract = by_uri[opener]
            if opener == "ak.wwise.core.undo.beginGroup":
                assert contract.route == "compound_transaction_member"
                assert contract.lifecycle_strategy == "same_connection_compound_only"
                assert contract.companion_uris == ()
                continue
            assert contract.route == "managed_transaction"
            expected_strategy = (
                "reversible_state_change"
                if opener == "ak.wwise.core.workUnit.load"
                else "paired_follow_up_required"
            )
            assert contract.lifecycle_strategy == expected_strategy
            assert contract.companion_uris == companions
            for companion in companions:
                assert companion in by_uri
                assert by_uri[companion].executable is True
                assert by_uri[companion].lifecycle_strategy == "session_close"


def test_native_surface_policy_partitions_every_function_and_binds_high_risk_differences() -> None:
    summary = validate_native_surface_policy()

    assert summary["route_audit"] == {
        "contract": "waapi-skill.public-function-route-audit/v1",
        "profiles": {
            "wwise-console": {
                "function_rows": 662,
                "unique_function_uris": 167,
                "generic_reflected_rows": 440,
                "generic_reflected_unique_uris": 116,
                "special_rows": 222,
                "special_unique_uris": 51,
            },
            "wwise-authoring-ui": {
                "function_rows": 670,
                "unique_function_uris": 167,
                "generic_reflected_rows": 442,
                "generic_reflected_unique_uris": 116,
                "special_rows": 228,
                "special_unique_uris": 51,
            },
        },
        "reviewed_special_uri_count": 51,
        "reviewed_generic_restriction_count": 6,
    }
    assert summary["version_rows"] == 111
    assert summary["rules"] == 45
    assert summary["scopes"] == 254
    assert summary["schema_selectors"] == 870
    assert summary["semantic_boundaries"] == 63
    assert sum(summary["selectors_by_status"].values()) == 870
    assert summary["selectors_by_status"]["intentionally_blocked"] > 0
    assert summary["selectors_by_status"]["missing"] == 0


def test_native_surface_policy_records_closed_import_semantic_boundaries() -> None:
    payload = load_native_surface_policy()
    rules = payload["rules"]
    direct_rules = [
        rule for rule in rules if rule["uri"] == "ak.wwise.core.audio.import"
    ]
    tab_rules = [
        rule
        for rule in rules
        if rule["uri"] == "ak.wwise.core.audio.importTabDelimited"
    ]

    for rule in direct_rules:
        boundaries = {
            row["selector"]: row["status"]
            for row in rule["semantic_boundaries"]
        }
        assert boundaries[
            "args.imports[].event::relative-existing-or-duplicate-target"
        ] == "intentionally_blocked"
        assert boundaries[
            "args.default-or-imports[].pattern:@reference::childOfReference"
        ] == "intentionally_blocked"

    for rule in tab_rules:
        boundaries = {
            row["selector"]: row["status"]
            for row in rule["semantic_boundaries"]
        }
        assert boundaries[
            "tab-columns.Event::relative-existing-or-duplicate-target"
        ] == "intentionally_blocked"
        assert boundaries[
            "tab-columns.Reference[]-or-@reference::childOfReference"
        ] == "intentionally_blocked"
        assert boundaries[
            "tab-columns.Object Path::blank-audio-name-inference"
        ] == "intentionally_blocked"
        assert boundaries[
            "tab-columns.Audio File::relative-to-import-file"
        ] == "intentionally_blocked"


def test_native_surface_policy_records_closed_switch_assignment_boundaries() -> None:
    payload = load_native_surface_policy()
    rules = {
        rule["uri"]: rule
        for rule in payload["rules"]
        if rule["uri"].startswith("ak.wwise.core.switchContainer.")
        and rule["uri"].endswith("Assignment")
    }

    assert set(rules) == {
        "ak.wwise.core.switchContainer.addAssignment",
        "ak.wwise.core.switchContainer.removeAssignment",
    }
    for uri, rule in rules.items():
        args_scope = next(
            scope for scope in rule["scopes"] if scope["pointer"] == "/argsSchema"
        )
        assert args_scope["classifications"]["normalized_equivalent"] == [
            "child",
            "stateOrSwitch",
        ]
        boundaries = {row["selector"]: row for row in rule["semantic_boundaries"]}
        assert boundaries["gateway.switch_container::relationship-owner"]["status"] == (
            "normalized_equivalent"
        )
        expected_prestate = (
            "relationship.prestate::child-unassigned"
            if uri.endswith("addAssignment")
            else "relationship.prestate::exact-pair-present"
        )
        assert boundaries[expected_prestate]["status"] == "normalized_equivalent"


def test_native_surface_policy_records_closed_soundbank_file_and_inclusion_boundaries() -> None:
    payload = load_native_surface_policy()
    rules = {rule["uri"]: rule for rule in payload["rules"]}
    definitions = rules["ak.wwise.core.soundbank.processDefinitionFiles"]
    assert definitions["versions"] == ["2022.1", "2023.1", "2024.1", "2025.1"]
    assert definitions["scopes"][0]["classifications"]["normalized_equivalent"] == ["files"]
    assert definitions["semantic_boundaries"][0]["selector"] == (
        "gateway.io_root::required-confinement"
    )

    inclusions = rules["ak.wwise.core.soundbank.setInclusions"]
    assert inclusions["versions"] == [
        "2021.1", "2022.1", "2023.1", "2024.1", "2025.1"
    ]
    assert inclusions["scopes"][0]["classifications"]["normalized_equivalent"] == [
        "inclusions", "operation", "soundbank"
    ]
    assert inclusions["semantic_boundaries"][0]["selector"] == (
        "gateway.identities::closed-typed-resolution"
    )


def test_native_surface_policy_records_bounded_advanced_waql_equivalence() -> None:
    payload = load_native_surface_policy()
    rules = [
        rule
        for rule in payload["rules"]
        if rule["uri"] == "ak.wwise.core.object.get"
    ]

    assert len(rules) == 2
    for rule in rules:
        boundary = {
            row["selector"]: row
            for row in rule["semantic_boundaries"]
        }["args.waql::caller-supplied-raw-expression"]
        assert boundary["status"] == "normalized_equivalent"
        assert "advanced object-query contract" in boundary["reason"]
        assert "final take" in boundary["reason"]


def test_native_surface_policy_rejects_an_unreviewed_special_route() -> None:
    payload = deepcopy(load_native_surface_policy())
    payload["route_audit"]["reviewed_special_uris"].pop()

    with pytest.raises(
        NativeSurfacePolicyError,
        match="special URI inventory changed",
    ):
        validate_native_surface_policy(payload)


def test_native_surface_policy_rejects_an_unreviewed_generic_restriction() -> None:
    payload = deepcopy(load_native_surface_policy())
    payload["route_audit"]["reviewed_generic_restrictions"].pop(
        "ak.wwise.core.mediaPool.get"
    )

    with pytest.raises(
        NativeSurfacePolicyError,
        match="generic restriction inventory changed",
    ):
        validate_native_surface_policy(payload)


def test_native_surface_policy_rejects_one_unclassified_reflected_field() -> None:
    payload = deepcopy(load_native_surface_policy())
    first_scope = payload["rules"][0]["scopes"][0]["classifications"]
    removed = first_scope["mapped"].pop()

    with pytest.raises(
        NativeSurfacePolicyError,
        match=rf"unclassified=.*{removed}",
    ):
        validate_native_surface_policy(payload)


def test_native_surface_policy_owns_the_generic_custom_command_blocks() -> None:
    payload = load_native_surface_policy()
    reviewed: dict[tuple[str, str], set[str]] = {}
    for rule in payload["rules"]:
        uri = rule["uri"]
        if uri not in FORBIDDEN_MODEL_AUTHORED_COMMAND_FIELDS:
            continue
        args_scope = next(
            scope for scope in rule["scopes"] if scope["pointer"] == "/argsSchema"
        )
        blocked = set(
            args_scope["classifications"]["intentionally_blocked"]
        )
        for version in rule["versions"]:
            reviewed[(version, uri)] = blocked

    expected = {
        (version, uri): set(fields)
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for uri, fields in FORBIDDEN_MODEL_AUTHORED_COMMAND_FIELDS.items()
    }
    assert reviewed == expected
