"""Shared durable-authorization vocabulary for WAAPI transactions."""

from __future__ import annotations


AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION = "explicit_confirmation"
AUTHORIZATION_MODE_POLICY = "policy_authorization"
DEFAULT_TRANSACTION_AUTHORIZATION_MODES = (
    AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,
    AUTHORIZATION_MODE_POLICY,
)
EXPLICIT_CONFIRMATION_ONLY_OPERATIONS = frozenset(
    {
        "debug.restartWaapiServers",
        "debug.testAssert",
        "debug.testCrash",
    }
)
EXPLICIT_CONFIRMATION_ONLY_URIS = frozenset(
    {
        "ak.wwise.debug.restartWaapiServers",
        "ak.wwise.debug.testAssert",
        "ak.wwise.debug.testCrash",
    }
)


def accepted_authorization_modes_for_operation(operation: str) -> tuple[str, ...]:
    """Return the closed durable authority set for one named operation."""

    if operation in EXPLICIT_CONFIRMATION_ONLY_OPERATIONS:
        return (AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,)
    return DEFAULT_TRANSACTION_AUTHORIZATION_MODES


def accepted_authorization_modes_for_uri(uri: str) -> tuple[str, ...]:
    """Return the closed durable authority set for one reflected mutation URI."""

    if uri in EXPLICIT_CONFIRMATION_ONLY_URIS:
        return (AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,)
    return DEFAULT_TRANSACTION_AUTHORIZATION_MODES


__all__ = [
    "AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION",
    "AUTHORIZATION_MODE_POLICY",
    "DEFAULT_TRANSACTION_AUTHORIZATION_MODES",
    "EXPLICIT_CONFIRMATION_ONLY_OPERATIONS",
    "EXPLICIT_CONFIRMATION_ONLY_URIS",
    "accepted_authorization_modes_for_operation",
    "accepted_authorization_modes_for_uri",
]
