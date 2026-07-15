"""Writable container suitability checks for semantic builder previews.

The service in this module never mutates Wwise.  It only classifies a target
path and, when a safe read client is supplied, may perform read-only child
resolution to provide candidate guidance for a later confirmation step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from wwise_waapi.waql import quote_waql_literal  # pyright: ignore[reportMissingImports]

from .common import (
    DEFAULT_WORK_UNIT_NAME,
    KNOWN_WWISE_MANAGEMENT_ROOTS,
    candidate_writable_child_container,
    split_wwise_path,
)


OBJECT_GET_URI = "ak.wwise.core.object.get"
DEFAULT_RETURN_FIELDS = ("id", "name", "type", "path")


class SafeReadClient(Protocol):
    """Minimal read-only WAAPI client surface used by this suitability check."""

    def call(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        """Perform a WAAPI read call."""
        ...


@dataclass(slots=True, frozen=True)
class ContainerSuitabilityResult:
    """Structured suitability verdict for a potential writable container."""

    valid: bool
    invalid_target: str | None = None
    reason: str = ""
    candidate_targets: tuple[str, ...] = ()
    requires_user_confirmation: bool = False
    requires_live_verification: bool = False
    resolved_identity: Mapping[str, Any] | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "valid": self.valid,
            "invalid_target": self.invalid_target,
            "reason": self.reason,
            "candidate_targets": list(self.candidate_targets),
            "requires_user_confirmation": self.requires_user_confirmation,
            "requires_live_verification": self.requires_live_verification,
        }
        if self.resolved_identity is not None:
            data["resolved_identity"] = dict(self.resolved_identity)
        if self.details:
            data["details"] = dict(self.details)
        return data


def assess_writable_container_suitability(
    target: str | int,
    *,
    safe_read_client: SafeReadClient | None = None,
    allow_confirmed_candidate: bool = False,
) -> ContainerSuitabilityResult:
    """Classify whether ``target`` is suitable for a direct write operation.

    Candidate targets are only guidance by default.  Passing
    ``allow_confirmed_candidate=True`` is an explicit policy hook for future
    callers that already obtained user confirmation; this service still does
    not rewrite or dispatch a mutation payload.
    """

    if not isinstance(target, str):
        return ContainerSuitabilityResult(valid=True, reason="non-path-target")

    path = target.strip()
    if not path:
        return ContainerSuitabilityResult(valid=False, invalid_target=target, reason="empty-target")

    segments = split_wwise_path(path)
    if not segments:
        return ContainerSuitabilityResult(valid=False, invalid_target=target, reason="no-path-segments")

    root = segments[0]
    if root not in KNOWN_WWISE_MANAGEMENT_ROOTS:
        return _live_or_blocked(path, safe_read_client, reason="unknown-management-root")

    heuristic_candidate = candidate_writable_child_container(path)
    if heuristic_candidate is not None:
        reason = "management-root-not-directly-writable" if len(segments) == 1 else "type-segment-not-directly-writable"
        if allow_confirmed_candidate:
            return ContainerSuitabilityResult(
                valid=True,
                invalid_target=path,
                reason=reason,
                candidate_targets=(heuristic_candidate,),
                requires_user_confirmation=False,
                requires_live_verification=False,
            )
        return ContainerSuitabilityResult(
            valid=False,
            invalid_target=path,
            reason=reason,
            candidate_targets=(heuristic_candidate,),
            requires_user_confirmation=True,
            requires_live_verification=False,
        )

    if len(segments) >= 2 and segments[1] == DEFAULT_WORK_UNIT_NAME:
        return ContainerSuitabilityResult(valid=True, reason="writable-default-work-unit-target")

    return _live_or_blocked(path, safe_read_client, reason="no-obvious-writable-candidate")


def _live_or_blocked(path: str, safe_read_client: SafeReadClient | None, *, reason: str) -> ContainerSuitabilityResult:
    if safe_read_client is None:
        return ContainerSuitabilityResult(
            valid=False,
            invalid_target=path,
            reason=reason,
            requires_live_verification=True,
        )

    try:
        rows = _read_default_work_unit_children(path, safe_read_client)
    except ValueError as exc:
        return ContainerSuitabilityResult(
            valid=False,
            invalid_target=path,
            reason="unsupported-waql-literal",
            requires_live_verification=False,
            details={"message": str(exc), "boundary": "packaged-waql-literal-evidence"},
        )
    if len(rows) == 1:
        candidate = _row_path(rows[0])
        if candidate is not None:
            return ContainerSuitabilityResult(
                valid=False,
                invalid_target=path,
                reason="live-child-candidate-requires-confirmation",
                candidate_targets=(candidate,),
                requires_user_confirmation=True,
                requires_live_verification=False,
                resolved_identity=rows[0],
            )
    if len(rows) > 1:
        return ContainerSuitabilityResult(
            valid=False,
            invalid_target=path,
            reason="ambiguous-live-child-candidates",
            candidate_targets=tuple(candidate for row in rows if (candidate := _row_path(row)) is not None),
            requires_user_confirmation=True,
            requires_live_verification=False,
            details={"candidate_count": len(rows)},
        )
    return ContainerSuitabilityResult(
        valid=False,
        invalid_target=path,
        reason=reason,
        requires_live_verification=False,
    )


def _read_default_work_unit_children(path: str, safe_read_client: SafeReadClient) -> tuple[Mapping[str, Any], ...]:
    waql = (
        f"from object {quote_waql_literal(path)} "
        f"select children where name = {quote_waql_literal(DEFAULT_WORK_UNIT_NAME)}"
    )
    result = safe_read_client.call(OBJECT_GET_URI, {"waql": waql}, {"return": list(DEFAULT_RETURN_FIELDS)})
    rows = result.get("return", ())
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ()
    return tuple(row for row in rows if isinstance(row, Mapping) and _is_default_work_unit_child(row, path))


def _is_default_work_unit_child(row: Mapping[str, Any], parent_path: str) -> bool:
    if row.get("name") != DEFAULT_WORK_UNIT_NAME or row.get("type") != "WorkUnit":
        return False
    child_path = _row_path(row)
    if child_path is None:
        return False
    parent_segments = split_wwise_path(parent_path)
    child_segments = split_wwise_path(child_path)
    return len(child_segments) == len(parent_segments) + 1 and child_segments[:-1] == parent_segments and child_segments[-1] == DEFAULT_WORK_UNIT_NAME


def _row_path(row: Mapping[str, Any]) -> str | None:
    path = row.get("path")
    if isinstance(path, str) and path.strip():
        return path
    return None
