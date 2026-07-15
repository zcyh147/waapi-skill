from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.category_policy import (  # pyright: ignore[reportMissingImports]
    POLICY_EXEMPT_CATEGORIES,
    SKIPPED_APPROVED_CATEGORIES,
    WRAPPER_ONLY_CATEGORIES,
    category_policy,
    is_policy_exempt_category,
)
from wwise_waapi.deferred_registry import ApiClassifier  # pyright: ignore[reportMissingImports]
from wwise_waapi.execution_contracts import (  # pyright: ignore[reportMissingImports]
    APPROVED_EXCLUSIONS,
    ExecutionContractRegistry,
)
from wwise_waapi.safety import classify_api_safety  # pyright: ignore[reportMissingImports]
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]

# Independent acceptance set: changing the production exclusion table cannot
# silently turn a former category-wide block into additional URI exclusions.
EXPECTED_EXCLUSION_URIS = frozenset(
    {
        "ak.wwise.cli.executeLuaScript",
        "ak.wwise.core.executeLuaScript",
        "ak.wwise.debug.assertFailed",
        "ak.wwise.debug.enableAsserts",
        "ak.wwise.debug.enableAutomationMode",
        "ak.wwise.debug.getWalTree",
        "ak.wwise.debug.restartWaapiServers",
        "ak.wwise.debug.testAssert",
        "ak.wwise.debug.testCrash",
        "ak.wwise.debug.validateCall",
        "ak.wwise.ui.commands.register",
        "ak.wwise.ui.commands.execute",
    }
)
FORMER_CATEGORY_WIDE_BLOCKS = frozenset(
    {"cli", "core.remote", "debug", "ui", "ui.commands", "ui.project"}
)


def test_legacy_category_wide_exemption_sets_are_empty() -> None:
    assert WRAPPER_ONLY_CATEGORIES == frozenset()
    assert SKIPPED_APPROVED_CATEGORIES == frozenset()
    assert POLICY_EXEMPT_CATEGORIES == frozenset()

    for category in FORMER_CATEGORY_WIDE_BLOCKS:
        assert is_policy_exempt_category(category) is False


def test_category_notes_describe_guarded_routes_not_inventory_only_statuses() -> None:
    expected_statuses = {
        "cli": "isolated-transaction",
        "core.remote": "managed-transaction",
        "debug": "selective-execution",
        "ui": "guarded-execution",
        "ui.commands": "guarded-execution",
        "ui.project": "guarded-execution",
    }

    for category, expected_status in expected_statuses.items():
        policy = category_policy(category)
        assert policy is not None
        assert policy.target_status == expected_status
        assert policy.target_status not in {"wrapper-only", "skipped-approved"}
        assert policy.user_approved_rationale
        assert policy.risk_explanation
        assert policy.future_review_trigger.startswith("Revisit")


def test_formerly_blocked_categories_are_executable_except_named_exclusions() -> None:
    registry = ExecutionContractRegistry()
    classifier = ApiClassifier()
    observed_categories: set[str] = set()

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for entry in registry.entries(version):
            category = classifier.classify(entry.uri, entry.item_type).category
            if category not in FORMER_CATEGORY_WIDE_BLOCKS:
                continue
            observed_categories.add(category)
            assert entry.executable is (entry.uri not in EXPECTED_EXCLUSION_URIS), (
                version,
                category,
                entry.uri,
                entry.route,
            )

    assert observed_categories == FORMER_CATEGORY_WIDE_BLOCKS


@pytest.mark.parametrize(
    ("uri", "expected_route", "expected_commands", "requires_confirmation"),
    (
        (
            "ak.wwise.cli.dumpObjects",
            "isolated_transaction",
            ("preview", "confirm", "execute", "verify"),
            True,
        ),
        (
            "ak.wwise.core.remote.getAvailableConsoles",
            "managed_transaction",
            ("preview", "confirm", "execute", "verify"),
            True,
        ),
        ("ak.wwise.ui.getSelectedObjects", "fixed_command", ("selected",), False),
        ("ak.wwise.ui.commands.getCommands", "bounded_call", ("call",), False),
        (
                "ak.wwise.ui.project.open",
                "isolated_transaction",
            ("preview", "confirm", "execute", "verify"),
            True,
        ),
    ),
)
def test_2022_former_wrapper_only_examples_have_concrete_public_routes(
    uri: str,
    expected_route: str,
    expected_commands: tuple[str, ...],
    requires_confirmation: bool,
) -> None:
    contract = ExecutionContractRegistry().describe("2022.1", uri)

    assert contract.route == expected_route
    assert contract.gateway_commands == expected_commands
    assert contract.requires_confirmation is requires_confirmation
    assert contract.executable is True
    assert contract.excluded_reason is None


def test_safe_debug_file_api_uses_isolated_transaction_in_supported_versions() -> None:
    registry = ExecutionContractRegistry()

    for version in ("2023.1", "2024.1", "2025.1"):
        contract = registry.describe(version, "ak.wwise.debug.generateToneWAV")
        assert contract.route == "isolated_transaction"
        assert contract.effect == "external"
        assert contract.requires_confirmation is True
        assert contract.executable is True


def test_only_the_twelve_named_uris_fail_closed_before_connect() -> None:
    assert frozenset(APPROVED_EXCLUSIONS) == EXPECTED_EXCLUSION_URIS

    registry = ExecutionContractRegistry()
    observed: set[str] = set()
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for contract in registry.entries(version):
            if contract.uri not in EXPECTED_EXCLUSION_URIS:
                continue
            observed.add(contract.uri)
            assert contract.route == "excluded"
            assert contract.effect == "unsafe"
            assert contract.gateway_commands == ()
            assert contract.timeout_seconds == 0
            assert contract.result_limit_bytes == 0
            assert contract.verification_strategy == "none"
            assert contract.program_case == "excluded-before-connect"
            assert contract.executable is False
            assert contract.excluded_reason == APPROVED_EXCLUSIONS[contract.uri]

            safety = classify_api_safety(contract.uri, contract.item_type, "ignored")
            assert safety.interface_status == "unsupported_by_skill_interface"
            assert safety.requires_destructive_gate is True
            assert safety.requires_confirmation is True
            assert safety.reason == contract.excluded_reason

    assert observed == EXPECTED_EXCLUSION_URIS


def test_live_suites_do_not_attempt_explicitly_excluded_routes() -> None:
    live_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "tests" / "live").glob("*.py")
    )

    for uri in EXPECTED_EXCLUSION_URIS:
        assert uri not in live_text
