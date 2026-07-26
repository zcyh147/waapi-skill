"""Execution-policy notes for WAAPI categories with special runtime guards."""

from __future__ import annotations

from dataclasses import dataclass


WRAPPER_ONLY_CATEGORIES = frozenset()
SKIPPED_APPROVED_CATEGORIES = frozenset()
POLICY_EXEMPT_CATEGORIES = WRAPPER_ONLY_CATEGORIES | SKIPPED_APPROVED_CATEGORIES
DEBUG_UNSAFE_LIVE_URIS = frozenset()


@dataclass(slots=True, frozen=True)
class CategoryPolicy:
    """User-approved execution policy for a reflected WAAPI category."""

    category: str
    target_status: str
    user_approved_rationale: str
    risk_explanation: str
    future_review_trigger: str


def category_policy(category: str) -> CategoryPolicy | None:
    """Return the high-coverage execution policy for a guarded category."""

    if category in {"ui", "ui.commands", "ui.project"}:
        return CategoryPolicy(
            category=category,
            target_status="guarded-execution",
            user_approved_rationale=(
                "UI functions are part of the reviewed high-coverage contract and execute through bounded reads "
                "or confirmed transactions instead of ad-hoc automation code."
            ),
            risk_explanation=(
                "UI calls depend on focus, selection, command registration, project windows, or foreground Authoring state, so "
                "mutating UI routes require an immutable preview and explicit confirmation."
            ),
            future_review_trigger=(
                "Revisit when a version changes a UI schema or the deterministic program contract no longer matches."
            ),
        )
    if category == "cli":
        return CategoryPolicy(
            category=category,
            target_status="isolated-transaction",
            user_approved_rationale=(
                "CLI functions are executable only through a confirmed, schema-validated, timeout-bounded transaction."
            ),
            risk_explanation=(
                "CLI migration, project creation, platform, and SoundBank generation commands can create or rewrite project artifacts "
                "outside the active Authoring project and therefore require explicit external-I/O intent."
            ),
            future_review_trigger=(
                "Revisit when path confinement or expected-disconnect handling needs a version-specific override."
            ),
        )
    if category == "core.remote":
        return CategoryPolicy(
            category=category,
            target_status="managed-transaction",
            user_approved_rationale=(
                "Remote-console calls are part of the high-coverage contract but require a confirmed managed-session transaction."
            ),
            risk_explanation=(
                "Remote connect/disconnect behavior depends on external consoles and network/session state not provided by the local sandbox."
            ),
            future_review_trigger=(
                "Revisit when a controlled console fixture reveals a version-specific lifecycle or cleanup difference."
            ),
        )
    if category == "debug":
        return CategoryPolicy(
            category=category,
            target_status="guarded-execution",
            user_approved_rationale=(
                "Debug reads, process-wide modes, and deliberate host controls are exposed only through "
                "separate fixed or confirmed routes with explicit lifecycle evidence."
            ),
            risk_explanation=(
                "Debug assert/crash APIs intentionally fail or terminate the host, while automation/assert "
                "modes affect process-wide behavior and private reads may exist only in Debug builds."
            ),
            future_review_trigger=(
                "Revisit when a version changes a private schema, disconnect behavior, or process lifecycle."
            ),
        )
    return None


def unsupported_live_behavior_message(api: str, category: str) -> str:
    """Build a stable diagnostic for policy-exempt live behavior attempts."""

    policy = category_policy(category)
    if policy is None:
        return f"WAAPI URI {api!r} is not excluded by the Phase 2 category policy."
    return (
        f"WAAPI URI {api!r} is {policy.target_status!r} by the reviewed execution policy for category "
        f"{category!r}. "
        f"Risk: {policy.risk_explanation} Review trigger: {policy.future_review_trigger}"
    )


def is_policy_exempt_category(category: str) -> bool:
    """Return whether an entire category is blocked from live execution."""

    return category in POLICY_EXEMPT_CATEGORIES


def is_unsafe_debug_live_uri(api: str, category: str) -> bool:
    """Return whether a debug URI must be refused outside dry-run diagnostics."""

    return category == "debug" and api in DEBUG_UNSAFE_LIVE_URIS
