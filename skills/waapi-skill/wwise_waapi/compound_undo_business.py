"""Compile checked child Business Draft snapshots into one Undo Group request."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import re
from typing import Any, Callable, Mapping, Sequence

from .business_declaration_state import BusinessDeclarationSession
from .business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    business_repair,
)
from .canonical import canonical_sha256


_SNAPSHOT_FIELDS = {
    "source_draft_id",
    "source_revision",
    "operation",
    "child_schema_digest",
    "request_sha256",
    "request",
}
_DRAFT_ID_PATTERN = re.compile(r"^od1-[0-9a-f]{32}$")
_TASK_AUTHORITY_PATTERN = re.compile(r"^da1-[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class CompoundParentDraftBinding:
    """Private link from one checked child back to its owning Undo Draft."""

    draft_id: str
    task_authority: str
    expected_revision: int

    @classmethod
    def from_dict(cls, value: object) -> "CompoundParentDraftBinding":
        if not isinstance(value, Mapping) or set(value) != {
            "draft_id",
            "task_authority",
            "expected_revision",
        }:
            raise ValueError("Compound parent binding is malformed")
        draft_id = value.get("draft_id")
        task_authority = value.get("task_authority")
        expected_revision = value.get("expected_revision")
        if not isinstance(draft_id, str) or not _DRAFT_ID_PATTERN.fullmatch(
            draft_id
        ):
            raise ValueError("Compound parent draft id is malformed")
        if not isinstance(
            task_authority, str
        ) or not _TASK_AUTHORITY_PATTERN.fullmatch(task_authority):
            raise ValueError("Compound parent task authority is malformed")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("Compound parent revision is malformed")
        return cls(
            draft_id=draft_id,
            task_authority=task_authority,
            expected_revision=expected_revision,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "draft_id": self.draft_id,
            "task_authority": self.task_authority,
            "expected_revision": self.expected_revision,
        }


@dataclass(frozen=True, slots=True)
class CheckedChildDraftBinding:
    """One exact task-local capability copied from a checked child Draft."""

    draft_id: str
    task_authority: str

    @classmethod
    def from_cli_pair(
        cls,
        value: object,
        *,
        index: int,
    ) -> "CheckedChildDraftBinding":
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise ValueError(
                f"Compound Undo child {index} binding is malformed"
            )
        return cls(draft_id=value[0], task_authority=value[1])


@dataclass(frozen=True, slots=True)
class CompoundUndoSnapshotScope:
    """Trusted parent context required to snapshot checked child Drafts."""

    store: Any
    parent_draft_id: str
    parent_task_authority: str
    parent_revision: int
    parent_context: BusinessContext
    project_guard: Mapping[str, Any]
    version: str
    schema_digest_for: Callable[[str, str], str]
    composer_digest_for: Callable[[str, str], str]


def snapshot_checked_compound_undo_children(
    scope: CompoundUndoSnapshotScope,
    bindings: Sequence[CheckedChildDraftBinding],
) -> tuple[dict[str, Any], ...]:
    """Validate and freeze all child capabilities behind the domain seam."""

    from .operation_drafts import OperationDraftBindingDrift
    from .operation_registry import operation_uses_business_declaration

    snapshots: list[dict[str, Any]] = []
    for index, binding in enumerate(bindings):
        child_record = scope.store.inspect(
            binding.draft_id,
            task_authority=binding.task_authority,
        )
        if child_record.draft_id == scope.parent_draft_id:
            raise ValueError("A Compound Undo plan cannot include itself")
        raw_parent = (
            child_record.composition.get("compound_parent")
            if child_record.composition is not None
            else None
        )
        try:
            parent = CompoundParentDraftBinding.from_dict(raw_parent)
        except ValueError as exc:
            raise ValueError(
                f"Compound Undo child {index} must be parent-owned"
            ) from exc
        if (
            parent.draft_id != scope.parent_draft_id
            or not hmac.compare_digest(
                parent.task_authority,
                scope.parent_task_authority,
            )
            or parent.expected_revision != scope.parent_revision
        ):
            raise ValueError(
                f"Compound Undo child {index} belongs to another parent"
            )
        if not operation_uses_business_declaration(
            child_record.operation,
            child_record.version,
        ):
            raise ValueError(
                "Compound Undo children must use a checked closed Business Draft "
                "with business-outcome verification"
            )
        check = child_record.check
        if (
            not isinstance(check, Mapping)
            or check.get("source_revision") != child_record.revision - 1
            or check.get("schema_digest") != child_record.schema_digest
            or check.get("composer_digest") != child_record.composer_digest
            or check.get("live_version") != child_record.version
            or check.get("project_guard") != scope.project_guard
        ):
            raise ValueError(
                f"Compound Undo child {index} must be checked at its current revision"
            )
        materialized = scope.store.materialize_request(
            child_record.draft_id,
            task_authority=binding.task_authority,
            expected_revision=child_record.revision,
            schema_digest=scope.schema_digest_for(
                child_record.operation,
                child_record.version,
            ),
            composer_digest=scope.composer_digest_for(
                child_record.operation,
                child_record.version,
            ),
        )
        if check.get("request_digest") != materialized.request_digest:
            raise ValueError(
                f"Compound Undo child {index} must be checked at its current revision"
            )
        raw_composition = child_record.composition
        raw_session = (
            raw_composition.get("business_session")
            if isinstance(raw_composition, Mapping)
            else None
        )
        if not isinstance(raw_session, Mapping):
            raise ValueError(
                f"Compound Undo child {index} lacks a Business Declaration session"
            )
        child_context = BusinessDeclarationSession.from_dict(raw_session).context
        if any(
            getattr(child_context, field) != getattr(scope.parent_context, field)
            for field in (
                "project_id",
                "project_path",
                "wwise_version",
                "wwise_build",
            )
        ):
            raise OperationDraftBindingDrift(
                f"Compound Undo child {index} belongs to another live project or Wwise build."
            )
        try:
            snapshot = build_compound_undo_child_snapshot(
                version=scope.version,
                source_draft_id=child_record.draft_id,
                source_revision=child_record.revision,
                request=materialized.request,
            )
        except BusinessDeclarationError as exc:
            raise ValueError(
                f"Compound Undo child {index} is not an eligible checked "
                f"business mutation: {exc}"
            ) from exc
        snapshots.append(snapshot)
    return tuple(snapshots)


def build_compound_undo_child_snapshot(
    *,
    version: str,
    source_draft_id: str,
    source_revision: int,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze one checked closed child request for ordered reuse."""

    from .operation_registry import (
        parse_operation_request,
    )
    from .typed_operations import (
        compound_business_child_operations,
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
    if (
        operation == "waapi.call"
        or operation not in compound_business_child_operations(version)
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
        "operation": operation,
        "child_schema_digest": compound_child_request_contract(
            operation,
            version,
        ).schema_digest,
        "request_sha256": canonical_sha256(normalized),
        "request": normalized,
    }


def materialize_compound_undo_business_request(
    operation: str,
    session: BusinessDeclarationSession,
) -> Mapping[str, Any]:
    from .operation_registry import (
        UNDO_GROUP_MAX_CALLS,
        UNDO_GROUP_MAX_DISPLAY_NAME_LENGTH,
    )

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
        or len(display_name) > UNDO_GROUP_MAX_DISPLAY_NAME_LENGTH
    ):
        raise _session_repair(session, "INVALID_ARGUMENT", "display_name")
    children = raw_plan.get("children")
    if not isinstance(children, list) or not 1 <= len(children) <= UNDO_GROUP_MAX_CALLS:
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
    "CheckedChildDraftBinding",
    "CompoundParentDraftBinding",
    "CompoundUndoSnapshotScope",
    "build_compound_undo_child_snapshot",
    "materialize_compound_undo_business_request",
    "snapshot_checked_compound_undo_children",
]
