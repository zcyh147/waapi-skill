from __future__ import annotations

import math
from collections import Counter
from typing import Mapping

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
        "bounded_call": 60,
        "bounded_topic_wait": 152,
        "excluded": 6,
        "fixed_command": 56,
        "isolated_transaction": 141,
        "managed_transaction": 248,
        "compound_transaction_member": 15,
        "transaction": 136,
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

    assert len(rows) == 59
    assert len({row.uri for row in rows}) == 15
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
    assert all(
        entry.gateway_commands == ("preview", "confirm", "execute", "verify")
        for entry in transactions
    )
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
