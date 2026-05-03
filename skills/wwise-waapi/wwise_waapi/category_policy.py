"""Phase 2 policy for WAAPI categories excluded from deep live behavior tests."""

from __future__ import annotations

from dataclasses import dataclass


WRAPPER_ONLY_CATEGORIES = frozenset({"ui", "ui.commands", "ui.project"})
SKIPPED_APPROVED_CATEGORIES = frozenset({"cli", "core.remote", "debug"})
POLICY_EXEMPT_CATEGORIES = WRAPPER_ONLY_CATEGORIES | SKIPPED_APPROVED_CATEGORIES
DEBUG_UNSAFE_LIVE_URIS = frozenset(
    {
        "ak.wwise.debug.enableAsserts",
        "ak.wwise.debug.enableAutomationMode",
        "ak.wwise.debug.testAssert",
        "ak.wwise.debug.testCrash",
    }
)


@dataclass(slots=True, frozen=True)
class CategoryPolicy:
    """User-approved non-live policy for a reflected WAAPI category."""

    category: str
    target_status: str
    user_approved_rationale: str
    risk_explanation: str
    future_review_trigger: str


def category_policy(category: str) -> CategoryPolicy | None:
    """Return the user-approved Phase 2 policy for a category, if any."""

    if category in WRAPPER_ONLY_CATEGORIES:
        return CategoryPolicy(
            category=category,
            target_status="wrapper-only",
            user_approved_rationale=(
                "User guidance keeps UI shortcut categories as wrapper-only in Phase 2; "
                "schema mapping and route diagnostics remain useful, but foreground Authoring UI state is not a deep live target."
            ),
            risk_explanation=(
                "UI calls depend on focus, selection, command registration, project windows, or foreground Authoring state, so "
                "default/live smoke suites would be flaky and could affect the operator session."
            ),
            future_review_trigger=(
                "Revisit only when a deterministic UI automation fixture is explicitly approved and can prove no user-project/UI state mutation."
            ),
        )
    if category == "cli":
        return CategoryPolicy(
            category=category,
            target_status="skipped-approved",
            user_approved_rationale=(
                "User guidance approves skipping deep CLI behavior in Phase 2; wrappers keep manifest/schema accounting only."
            ),
            risk_explanation=(
                "CLI migration, project creation, platform, and SoundBank generation commands can create or rewrite project artifacts "
                "outside the narrow live sandbox behavior scope."
            ),
            future_review_trigger=(
                "Revisit when a disposable CLI-only project fixture and explicit migration/generation acceptance criteria are approved."
            ),
        )
    if category == "core.remote":
        return CategoryPolicy(
            category=category,
            target_status="skipped-approved",
            user_approved_rationale=(
                "User guidance approves skipping remote-console behavior because a deterministic remote console environment is unavailable."
            ),
            risk_explanation=(
                "Remote connect/disconnect behavior depends on external consoles and network/session state not provided by the local sandbox."
            ),
            future_review_trigger=(
                "Revisit when a controlled remote console fixture is available and can prove connection lifecycle cleanup."
            ),
        )
    if category == "debug":
        return CategoryPolicy(
            category=category,
            target_status="skipped-approved",
            user_approved_rationale=(
                "User guidance approves skipping debug behavior; assert/crash/automation debug APIs must not run in Phase 2 default or live smoke paths."
            ),
            risk_explanation=(
                "Debug assert/crash APIs can intentionally fail, crash, or alter automation/assert handling in the running Wwise instance."
            ),
            future_review_trigger=(
                "Revisit only with explicit crash/assert sandbox approval and isolated process-failure evidence requirements."
            ),
        )
    return None


def unsupported_live_behavior_message(api: str, category: str) -> str:
    """Build a stable diagnostic for policy-exempt live behavior attempts."""

    policy = category_policy(category)
    if policy is None:
        return f"WAAPI URI {api!r} is not excluded by the Phase 2 category policy."
    return (
        f"WAAPI URI {api!r} is {policy.target_status!r} by user-approved Phase 2 policy for category "
        f"{category!r}; wrappers may validate schema/route metadata, but live behavior execution is unsupported. "
        f"Risk: {policy.risk_explanation} Review trigger: {policy.future_review_trigger}"
    )


def is_policy_exempt_category(category: str) -> bool:
    """Return whether category is wrapper-only or skipped-approved in Phase 2."""

    return category in POLICY_EXEMPT_CATEGORIES


def is_unsafe_debug_live_uri(api: str, category: str) -> bool:
    """Return whether a debug URI must be refused outside dry-run diagnostics."""

    return category == "debug" and api in DEBUG_UNSAFE_LIVE_URIS
