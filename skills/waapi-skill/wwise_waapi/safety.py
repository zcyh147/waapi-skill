"""Safety projection for the versioned public WAAPI execution contracts.

The execution-contract registry is the authority for public routing.  This
module keeps the compact safety shape used by the dispatcher and capability
catalog while avoiding the former fixed two-function allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .execution_contracts import (
    APPROVED_EXCLUSIONS,
    BOUNDED_DIRECT_CALL_URIS,
    ExecutionContractRegistry,
    FIXED_COMMANDS_BY_URI,
    classify_function_effect,
)
from .versions import SUPPORTED_WWISE_VERSION_KEYS


REVIEWED_FIXED_FUNCTION_URIS = frozenset(FIXED_COMMANDS_BY_URI)
REVIEWED_PUBLIC_CALL_URIS = BOUNDED_DIRECT_CALL_URIS
REVIEWED_READ_ONLY_FUNCTION_URIS = REVIEWED_FIXED_FUNCTION_URIS | REVIEWED_PUBLIC_CALL_URIS


def _reviewed_topic_uris() -> frozenset[str]:
    registry = ExecutionContractRegistry()
    return frozenset(
        entry.uri
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for entry in registry.executable_entries(version)
        if entry.item_type == "topic"
    )


REVIEWED_TOPIC_URIS = _reviewed_topic_uris()

# Compatibility exports retained for callers that previously consumed the
# conservative candidate/boundary maps. All newly approved non-direct calls are
# now represented by an executable transaction contract instead.
BOUNDED_CALL_CANDIDATES: Mapping[str, str] = MappingProxyType({})
EXPLICIT_UNSUPPORTED_LIVE_URIS: Mapping[str, str] = MappingProxyType(
    dict(APPROVED_EXCLUSIONS)
)
IMMEDIATE_UNSUPPORTED_CALL_URIS = frozenset(EXPLICIT_UNSUPPORTED_LIVE_URIS)
EXPLICIT_UNSUPPORTED_TOPIC_URIS: Mapping[str, str] = MappingProxyType(
    {}
)


@dataclass(frozen=True, slots=True)
class ApiSafety:
    """Stable safety facts used by the catalog and dispatcher."""

    read_only: bool
    requires_destructive_gate: bool
    requires_confirmation: bool
    interface_status: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "read_only": self.read_only,
            "requires_destructive_gate": self.requires_destructive_gate,
            "requires_confirmation": self.requires_confirmation,
            "interface_status": self.interface_status,
            "reason": self.reason,
        }


def classify_api_safety(uri: str, item_type: str, category: str) -> ApiSafety:
    """Project one reflected URI into the public execution safety shape."""

    del category  # Namespace classification is retained by callers, not used as an authority here.
    excluded = APPROVED_EXCLUSIONS.get(uri)
    if excluded is not None:
        return ApiSafety(
            read_only=False,
            requires_destructive_gate=True,
            requires_confirmation=True,
            interface_status="unsupported_by_skill_interface",
            reason=excluded,
        )
    if item_type == "topic":
        if uri not in REVIEWED_TOPIC_URIS:
            return ApiSafety(
                read_only=False,
                requires_destructive_gate=True,
                requires_confirmation=True,
                interface_status="unsupported_by_skill_interface",
                reason="This topic is not present in the reviewed five-version execution contract.",
            )
        return ApiSafety(
            read_only=True,
            requires_destructive_gate=False,
            requires_confirmation=False,
            interface_status="available",
            reason="This reviewed topic is exposed only through one bounded wait with guaranteed unsubscribe.",
        )
    if item_type != "function":
        raise ValueError(f"Unsupported WAAPI item type: {item_type!r}")
    if uri in REVIEWED_READ_ONLY_FUNCTION_URIS:
        return ApiSafety(
            read_only=True,
            requires_destructive_gate=False,
            requires_confirmation=False,
            interface_status="available",
            reason="This function has a reviewed fixed or bounded-call execution contract.",
        )
    effect = classify_function_effect(uri)
    return ApiSafety(
        read_only=effect == "read",
        requires_destructive_gate=True,
        requires_confirmation=True,
        interface_status="available_via_transaction",
        reason=(
            f"This function is packaged as a confirmed {effect} transaction with schema validation, "
            "immutable preview binding, bounded execution, and result verification."
        ),
    )


def requires_destructive_gate(uri: str, item_type: str, category: str) -> bool:
    """Return the shared dispatcher gate decision for one API."""

    return classify_api_safety(uri, item_type, category).requires_destructive_gate


__all__ = [
    "ApiSafety",
    "BOUNDED_CALL_CANDIDATES",
    "EXPLICIT_UNSUPPORTED_LIVE_URIS",
    "EXPLICIT_UNSUPPORTED_TOPIC_URIS",
    "IMMEDIATE_UNSUPPORTED_CALL_URIS",
    "REVIEWED_FIXED_FUNCTION_URIS",
    "REVIEWED_PUBLIC_CALL_URIS",
    "REVIEWED_READ_ONLY_FUNCTION_URIS",
    "REVIEWED_TOPIC_URIS",
    "classify_api_safety",
    "requires_destructive_gate",
]
