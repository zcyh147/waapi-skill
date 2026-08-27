"""Compile checked child Business Draft snapshots into one Undo Group request."""

from __future__ import annotations

from typing import Any, Mapping

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import business_repair
from .canonical import canonical_sha256


MAX_UNDO_CHILDREN = 32
MAX_UNDO_DISPLAY_NAME = 256
_SNAPSHOT_FIELDS = {
    "source_draft_id",
    "source_revision",
    "operation",
    "child_schema_digest",
    "request_sha256",
    "request",
}


def build_compound_undo_child_snapshot(
    *,
    version: str,
    source_draft_id: str,
    source_revision: int,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze one checked closed child request for ordered reuse."""

    from .operation_registry import (
        operation_uses_business_declaration,
        parse_operation_request,
    )
    from .typed_operations import (
        compound_child_operations,
        compound_child_request_contract,
    )

    requested_operation = request.get("operation")
    if not isinstance(requested_operation, str) or requested_operation == "waapi.undoGroup":
        raise _repair("UNDO_CHILD_BUSINESS_REQUIRED", field="child_drafts")
    try:
        parsed = parse_operation_request(request, expected_version=version)
    except (TypeError, ValueError) as exc:
        raise _repair("UNDO_CHILD_INVALID", field="child_drafts") from exc
    operation = parsed.operation
    child_operation = operation
    if operation == "waapi.call":
        child_operation = parsed.arguments.get("api")
    if (
        not isinstance(child_operation, str)
        or child_operation not in compound_child_operations(version)
        or (
            operation != "waapi.call"
            and not operation_uses_business_declaration(operation, version)
        )
    ):
        raise _repair("UNDO_CHILD_BUSINESS_REQUIRED", field="child_drafts")
    if not isinstance(source_draft_id, str) or not source_draft_id:
        raise _repair("UNDO_CHILD_INVALID", field="child_drafts")
    if type(source_revision) is not int or source_revision < 1:
        raise _repair("UNDO_CHILD_INVALID", field="child_drafts")
    normalized = parsed.as_dict()
    return {
        "source_draft_id": source_draft_id,
        "source_revision": source_revision,
        "operation": child_operation,
        "child_schema_digest": compound_child_request_contract(
            child_operation,
            version,
        ).schema_digest,
        "request_sha256": canonical_sha256(normalized),
        "request": normalized,
    }


def materialize_compound_undo_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    if operation != "waapi.undoGroup":
        raise ValueError("compound Undo Adapter received the wrong operation")
    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    if set(session.settings) != {"undo_plan"}:
        raise _session_repair(session, "BUSINESS_DECLARATION_INCOMPLETE", "undo_plan")
    raw_plan = session.settings["undo_plan"]
    if not isinstance(raw_plan, Mapping) or set(raw_plan) != {
        "display_name",
        "children",
    }:
        raise _session_repair(session, "INVALID_ARGUMENT", "undo_plan")
    display_name = raw_plan.get("display_name")
    if (
        not isinstance(display_name, str)
        or not display_name.strip()
        or display_name != display_name.strip()
        or len(display_name) > MAX_UNDO_DISPLAY_NAME
    ):
        raise _session_repair(session, "INVALID_ARGUMENT", "display_name")
    children = raw_plan.get("children")
    if not isinstance(children, list) or not 1 <= len(children) <= MAX_UNDO_CHILDREN:
        raise _session_repair(session, "INVALID_ARGUMENT", "children")
    calls: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for index, raw_child in enumerate(children):
        if not isinstance(raw_child, Mapping) or set(raw_child) != _SNAPSHOT_FIELDS:
            raise _session_repair(session, "UNDO_CHILD_INVALID", f"children[{index}]")
        child = dict(raw_child)
        source_id = child.get("source_draft_id")
        if not isinstance(source_id, str) or source_id in source_ids:
            raise _session_repair(session, "UNDO_CHILD_INVALID", f"children[{index}]")
        source_ids.add(source_id)
        request = child.get("request")
        if not isinstance(request, Mapping) or canonical_sha256(request) != child.get(
            "request_sha256"
        ):
            raise _session_repair(
                session,
                "UNDO_CHILD_SNAPSHOT_STALE",
                f"children[{index}]",
            )
        rebuilt = build_compound_undo_child_snapshot(
            version=session.context.wwise_version,
            source_draft_id=source_id,
            source_revision=child.get("source_revision"),
            request=request,
        )
        if rebuilt != child:
            raise _session_repair(
                session,
                "UNDO_CHILD_SNAPSHOT_STALE",
                f"children[{index}]",
            )
        calls.append(
            {
                "schema_digest": child["child_schema_digest"],
                "request": rebuilt["request"],
            }
        )
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": session.context.wwise_version,
        "operation": "waapi.undoGroup",
        "arguments": {"display_name": display_name, "calls": calls},
    }


def _repair(error_code: str, *, field: str):
    return business_repair(
        error_code,
        field=field,
        draft_revision=0,
        action="use one checked supported closed child Draft",
    )


def _session_repair(
    session: BusinessDeclarationSession,
    error_code: str,
    field: str,
):
    return business_repair(
        error_code,
        field=field,
        draft_revision=session.revision,
        action="redeclare the ordered checked child Business Draft snapshots",
    )


__all__ = [
    "MAX_UNDO_CHILDREN",
    "MAX_UNDO_DISPLAY_NAME",
    "build_compound_undo_child_snapshot",
    "materialize_compound_undo_business_request",
]
