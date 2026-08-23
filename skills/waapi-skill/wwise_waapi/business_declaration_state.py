"""Immutable, bounded state for one task-local Business Declaration batch."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    BusinessHandleRegistry,
    ExistingObjectTarget,
    NewDescendantTarget,
    business_repair,
    repair_at_draft_revision,
    resolve_semantic_kind,
)
from .canonical import canonical_json_bytes, canonical_sha256, strict_json_copy


BUSINESS_DECLARATION_SESSION_CONTRACT = (
    "waapi-skill.business-declaration-session/v1"
)
BUSINESS_DECLARATION_CONTRACT = "waapi-skill.business-declaration/v1"
BUSINESS_PREVIEW_CONTRACT = "waapi-skill.business-preview/v1"
BUSINESS_PREVIEW_AUDIT_CONTRACT = "waapi-skill.business-preview-audit/v1"

MAX_BUSINESS_DECLARATIONS = 2_048
MAX_BUSINESS_DECLARATION_FIELDS = 128
MAX_BUSINESS_DECLARATION_BYTES = 256 * 1024
MAX_BUSINESS_SESSION_BYTES = 768 * 1024
MAX_BUSINESS_PREVIEW_LINES = 4_096
MAX_BUSINESS_PREVIEW_BYTES = 256 * 1024
MAX_BUSINESS_PREVIEW_AUDIT = 64
MAX_BUSINESS_PREVIEW_DETAIL_BYTES = 256 * 1024
BUSINESS_SESSION_UPDATE_EVENTS = frozenset(
    {
        "declaration.added",
        "declaration.revised",
        "preview.recorded",
    }
)

_DECLARATION_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_BUSINESS_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_NATIVE_FIELDS = frozenset(
    {
        "object_path",
        "object_type",
        "metadata_scope",
        "native_request",
        "native_rows",
        "shell_command",
        "model_command",
        "draft_revision",
    }
)


@dataclass(frozen=True, slots=True)
class BusinessDeclaration:
    declaration_id: str
    target: NewDescendantTarget | ExistingObjectTarget
    fields: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        target = (
            {
                "form": "new-descendant",
                "parent_handle": self.target.parent_handle,
                "name": self.target.name,
                "kind": self.target.kind,
            }
            if isinstance(self.target, NewDescendantTarget)
            else {
                "form": "existing-object",
                "object_handle": self.target.object_handle,
            }
        )
        return {
            "contract": BUSINESS_DECLARATION_CONTRACT,
            "declaration_id": self.declaration_id,
            "target": target,
            "fields": dict(self.fields),
        }


@dataclass(frozen=True, slots=True)
class BusinessPreview:
    source_revision: int
    readable_lines: tuple[str, ...]
    detail: Mapping[str, Any]
    preview_digest: str

    @classmethod
    def create(
        cls,
        *,
        source_revision: int,
        readable_lines: Sequence[str],
        detail: Mapping[str, Any],
    ) -> "BusinessPreview":
        if (
            isinstance(source_revision, bool)
            or not isinstance(source_revision, int)
            or source_revision < 1
        ):
            raise ValueError("preview source_revision must be positive")
        if (
            not isinstance(readable_lines, Sequence)
            or isinstance(readable_lines, (str, bytes, bytearray))
            or not readable_lines
            or len(readable_lines) > MAX_BUSINESS_PREVIEW_LINES
        ):
            raise ValueError("preview readable lines are invalid or exceed their limit")
        normalized_lines = tuple(
            _bounded_text(line, field="readable line", maximum_bytes=8 * 1024)
            for line in readable_lines
        )
        if any(":" not in line and "：" not in line for line in normalized_lines):
            raise ValueError("preview lines must use readable field: value form")
        normalized_detail = _strict_json_object(detail, label="preview detail")
        if len(canonical_json_bytes(normalized_detail)) > MAX_BUSINESS_PREVIEW_DETAIL_BYTES:
            raise ValueError("preview detail exceeds its fixed byte limit")
        material = {
            "contract": BUSINESS_PREVIEW_CONTRACT,
            "source_revision": source_revision,
            "readable_lines": list(normalized_lines),
            "detail": normalized_detail,
        }
        if len(canonical_json_bytes(material)) > MAX_BUSINESS_PREVIEW_BYTES:
            raise ValueError("business Preview exceeds its fixed byte limit")
        return cls(
            source_revision=source_revision,
            readable_lines=normalized_lines,
            detail=normalized_detail,
            preview_digest=canonical_sha256(material),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": BUSINESS_PREVIEW_CONTRACT,
            "source_revision": self.source_revision,
            "readable_lines": list(self.readable_lines),
            "detail": dict(self.detail),
            "preview_digest": self.preview_digest,
        }

    def readable_projection(self) -> dict[str, Any]:
        return {
            "contract": BUSINESS_PREVIEW_CONTRACT,
            "source_revision": self.source_revision,
            "readable_lines": list(self.readable_lines),
            "preview_digest": self.preview_digest,
            "detail_available": True,
        }


@dataclass(frozen=True, slots=True)
class BusinessDeclarationSession:
    context: BusinessContext
    handles: BusinessHandleRegistry
    revision: int
    declarations: tuple[BusinessDeclaration, ...]
    active_preview: BusinessPreview | None
    preview_audit: tuple[Mapping[str, Any], ...]

    @classmethod
    def create(cls, context: BusinessContext) -> "BusinessDeclarationSession":
        return cls(
            context=context,
            handles=BusinessHandleRegistry(context),
            revision=0,
            declarations=(),
            active_preview=None,
            preview_audit=(),
        )

    def with_new_declaration(
        self,
        *,
        declaration_id: str,
        target: NewDescendantTarget,
        fields: Mapping[str, Any],
    ) -> "BusinessDeclarationSession":
        return self._with_declaration(
            declaration_id=declaration_id,
            target=target,
            fields=fields,
            replace=False,
        )

    def with_existing_declaration(
        self,
        *,
        declaration_id: str,
        target: ExistingObjectTarget,
        fields: Mapping[str, Any],
    ) -> "BusinessDeclarationSession":
        return self._with_declaration(
            declaration_id=declaration_id,
            target=target,
            fields=fields,
            replace=False,
        )

    def revise_declaration(
        self,
        *,
        declaration_id: str,
        fields: Mapping[str, Any],
    ) -> "BusinessDeclarationSession":
        matches = tuple(
            row for row in self.declarations if row.declaration_id == declaration_id
        )
        if len(matches) != 1:
            raise business_repair(
                "DECLARATION_NOT_AVAILABLE",
                field="declaration_id",
                draft_revision=self.revision,
                action="use one declaration id from the current task",
            )
        return self._with_declaration(
            declaration_id=declaration_id,
            target=matches[0].target,
            fields=fields,
            replace=True,
        )

    def with_preview(self, preview: BusinessPreview) -> "BusinessDeclarationSession":
        if not isinstance(preview, BusinessPreview):
            raise TypeError("preview must be BusinessPreview")
        if preview.source_revision != self.revision or not self.declarations:
            raise business_repair(
                "PREVIEW_SOURCE_REVISION_STALE",
                field="source_revision",
                draft_revision=self.revision,
                action="compile a new Preview from the current declaration revision",
            )
        candidate = BusinessDeclarationSession(
            context=self.context,
            handles=self.handles,
            revision=self.revision,
            declarations=self.declarations,
            active_preview=preview,
            preview_audit=self.preview_audit,
        )
        try:
            candidate.as_dict()
        except ValueError as exc:
            raise business_repair(
                "PREVIEW_LIMIT_EXCEEDED",
                field="preview",
                draft_revision=self.revision,
                action="split the task into bounded business declaration batches",
            ) from exc
        return candidate

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "contract": BUSINESS_DECLARATION_SESSION_CONTRACT,
            "context": self.context.as_binding_dict(),
            "handles": self.handles.as_dict(),
            "revision": self.revision,
            "declarations": [row.as_dict() for row in self.declarations],
            "active_preview": (
                None if self.active_preview is None else self.active_preview.as_dict()
            ),
            "preview_audit": [strict_json_copy(row) for row in self.preview_audit],
        }
        if len(canonical_json_bytes(payload)) > MAX_BUSINESS_SESSION_BYTES:
            raise ValueError("business declaration session exceeds its fixed byte limit")
        return payload

    @classmethod
    def from_dict(cls, payload: Any) -> "BusinessDeclarationSession":
        expected = {
            "contract",
            "context",
            "handles",
            "revision",
            "declarations",
            "active_preview",
            "preview_audit",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("business declaration session fields are invalid")
        if payload.get("contract") != BUSINESS_DECLARATION_SESSION_CONTRACT:
            raise ValueError("business declaration session contract is invalid")
        context = BusinessContext.from_binding_dict(payload.get("context"))
        handles = BusinessHandleRegistry.from_dict(payload.get("handles"))
        if handles.context != context:
            raise ValueError("business declaration session handle context differs")
        revision = payload.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("business declaration session revision is invalid")
        raw_declarations = payload.get("declarations")
        if (
            not isinstance(raw_declarations, list)
            or len(raw_declarations) > MAX_BUSINESS_DECLARATIONS
        ):
            raise ValueError("business declarations are invalid or exceed their limit")
        declarations = tuple(
            _declaration_from_dict(row, handles=handles) for row in raw_declarations
        )
        ids = tuple(row.declaration_id for row in declarations)
        if len(ids) != len(set(ids)) or revision < len(declarations):
            raise ValueError("business declaration ids or revision are invalid")
        active = payload.get("active_preview")
        preview = None if active is None else _preview_from_dict(active)
        if preview is not None and preview.source_revision != revision:
            raise ValueError("active business Preview is stale")
        raw_audit = payload.get("preview_audit")
        if not isinstance(raw_audit, list) or len(raw_audit) > MAX_BUSINESS_PREVIEW_AUDIT:
            raise ValueError("business Preview audit is invalid or exceeds its limit")
        audit = tuple(_preview_audit_from_dict(row) for row in raw_audit)
        session = cls(
            context=context,
            handles=handles,
            revision=revision,
            declarations=declarations,
            active_preview=preview,
            preview_audit=audit,
        )
        session.as_dict()
        return session

    @classmethod
    def validate_transition(
        cls,
        previous_payload: Mapping[str, Any],
        candidate: "BusinessDeclarationSession",
        *,
        event_type: str,
    ) -> None:
        """Validate one closed durable transition from an immutable snapshot."""

        if event_type not in BUSINESS_SESSION_UPDATE_EVENTS:
            raise ValueError("event_type must be one closed business session update")
        if not isinstance(candidate, BusinessDeclarationSession):
            raise TypeError("candidate must be BusinessDeclarationSession")
        previous = cls.from_dict(previous_payload)
        candidate_payload = candidate.as_dict()
        if candidate.context != previous.context:
            raise ValueError("business session transition changed its live binding")
        if event_type.startswith("declaration."):
            if (
                candidate.revision != previous.revision + 1
                or candidate.active_preview is not None
                or candidate_payload["declarations"]
                == previous_payload["declarations"]
            ):
                raise ValueError(
                    "declaration transition must change exactly one revision and invalidate Preview"
                )
            return
        if (
            candidate.revision != previous.revision
            or candidate_payload["declarations"]
            != previous_payload["declarations"]
            or candidate_payload["handles"] != previous_payload["handles"]
            or candidate.active_preview is None
            or candidate.active_preview.source_revision != previous.revision
        ):
            raise ValueError(
                "Preview transition must preserve facts and bind the current revision"
            )

    def _with_declaration(
        self,
        *,
        declaration_id: str,
        target: NewDescendantTarget | ExistingObjectTarget,
        fields: Mapping[str, Any],
        replace: bool,
    ) -> "BusinessDeclarationSession":
        normalized_id = _declaration_id(
            declaration_id, draft_revision=self.revision
        )
        current = {
            row.declaration_id: row for row in self.declarations
        }
        if replace != (normalized_id in current):
            raise business_repair(
                "DECLARATION_ID_CONFLICT" if not replace else "DECLARATION_NOT_AVAILABLE",
                field="declaration_id",
                draft_revision=self.revision,
                action="use a unique new id or revise one current declaration id",
            )
        normalized_target = _validate_target(
            target,
            handles=self.handles,
            draft_revision=self.revision,
        )
        normalized_fields = _normalize_fields(
            fields,
            draft_revision=self.revision,
        )
        declaration = BusinessDeclaration(
            declaration_id=normalized_id,
            target=normalized_target,
            fields=normalized_fields,
        )
        if len(canonical_json_bytes(declaration.as_dict())) > MAX_BUSINESS_DECLARATION_BYTES:
            raise business_repair(
                "DECLARATION_LIMIT_EXCEEDED",
                field="declaration",
                draft_revision=self.revision,
                action="split the requested business facts into a bounded batch",
            )
        rows = tuple(
            declaration if row.declaration_id == normalized_id else row
            for row in self.declarations
        ) if replace else (*self.declarations, declaration)
        if len(rows) > MAX_BUSINESS_DECLARATIONS:
            raise business_repair(
                "DECLARATION_LIMIT_EXCEEDED",
                field="declarations",
                draft_revision=self.revision,
                action="finish the current bounded batch before declaring more work",
            )
        audit = self.preview_audit
        if self.active_preview is not None:
            if len(audit) >= MAX_BUSINESS_PREVIEW_AUDIT:
                raise business_repair(
                    "PREVIEW_AUDIT_LIMIT_EXCEEDED",
                    field="preview",
                    draft_revision=self.revision,
                    action="finish or abandon the current task-local Draft",
                )
            audit = (
                *audit,
                {
                    "contract": BUSINESS_PREVIEW_AUDIT_CONTRACT,
                    "preview": self.active_preview.as_dict(),
                    "invalidated_by_revision": self.revision + 1,
                },
            )
        candidate = BusinessDeclarationSession(
            context=self.context,
            handles=self.handles,
            revision=self.revision + 1,
            declarations=rows,
            active_preview=None,
            preview_audit=audit,
        )
        try:
            candidate.as_dict()
        except ValueError as exc:
            raise business_repair(
                "DECLARATION_LIMIT_EXCEEDED",
                field="declaration",
                draft_revision=self.revision,
                action="finish or abandon the current bounded task-local Draft",
            ) from exc
        return candidate


def _validate_target(
    target: Any,
    *,
    handles: BusinessHandleRegistry,
    draft_revision: int | None = None,
) -> NewDescendantTarget | ExistingObjectTarget:
    if isinstance(target, NewDescendantTarget):
        missing = [
            field
            for field, value in (
                ("parent_handle", target.parent_handle),
                ("name", target.name),
                ("kind", target.kind),
            )
            if not isinstance(value, str) or not value
        ]
        if missing:
            raise business_repair(
                "DECLARATION_INCOMPLETE",
                field="target",
                draft_revision=draft_revision,
                missing_fields=missing,
                action="provide every required new-object business fact",
            )
        try:
            handles.resolve_object(target.parent_handle)
        except BusinessDeclarationError as exc:
            raise repair_at_draft_revision(
                exc,
                draft_revision=0 if draft_revision is None else draft_revision,
            ) from exc
        if any(character in target.name for character in ("\\", "<", ">")):
            raise business_repair(
                "INVALID_CHILD_NAME",
                field="name",
                draft_revision=draft_revision,
                action="provide one child name without Wwise path syntax",
            )
        try:
            resolve_semantic_kind(target.kind, version=handles.context.wwise_version)
        except BusinessDeclarationError as exc:
            raise repair_at_draft_revision(
                exc,
                draft_revision=0 if draft_revision is None else draft_revision,
            ) from exc
        return target
    if isinstance(target, ExistingObjectTarget):
        try:
            handles.resolve_object(target.object_handle)
        except BusinessDeclarationError as exc:
            raise repair_at_draft_revision(
                exc,
                draft_revision=0 if draft_revision is None else draft_revision,
            ) from exc
        return target
    raise business_repair(
        "DECLARATION_TARGET_INVALID",
        field="target",
        draft_revision=draft_revision,
        action="use a new-descendant or exact existing-object target",
    )


def _normalize_fields(
    fields: Any,
    *,
    draft_revision: int | None = None,
) -> dict[str, Any]:
    if not isinstance(fields, Mapping) or len(fields) > MAX_BUSINESS_DECLARATION_FIELDS:
        raise business_repair(
            "DECLARATION_FIELDS_INVALID",
            field="fields",
            draft_revision=draft_revision,
            action="provide one bounded object of stable business fields",
        )
    normalized: dict[str, Any] = {}
    for name, value in fields.items():
        if not isinstance(name, str) or not _BUSINESS_FIELD.fullmatch(name):
            raise business_repair(
                "DECLARATION_FIELD_NAME_INVALID",
                field="fields",
                draft_revision=draft_revision,
                action="use one disclosed stable business field name",
            )
        if name in _NATIVE_FIELDS:
            raise business_repair(
                "NATIVE_PLANNING_FIELD_FORBIDDEN",
                field=name,
                draft_revision=draft_revision,
                action="provide business meaning and let the Gateway derive native planning",
            )
        try:
            normalized[name] = _strict_json(value, label=f"field {name}")
        except ValueError as exc:
            raise business_repair(
                "DECLARATION_FIELD_VALUE_INVALID",
                field=name,
                draft_revision=draft_revision,
                action="provide one bounded strict-JSON business value",
            ) from exc
    return dict(sorted(normalized.items()))


def _declaration_from_dict(
    payload: Any,
    *,
    handles: BusinessHandleRegistry,
) -> BusinessDeclaration:
    if not isinstance(payload, Mapping) or set(payload) != {
        "contract",
        "declaration_id",
        "target",
        "fields",
    }:
        raise ValueError("business declaration fields are invalid")
    if payload.get("contract") != BUSINESS_DECLARATION_CONTRACT:
        raise ValueError("business declaration contract is invalid")
    target_payload = payload.get("target")
    if not isinstance(target_payload, Mapping):
        raise ValueError("business declaration target is invalid")
    form = target_payload.get("form")
    if form == "new-descendant" and set(target_payload) == {
        "form",
        "parent_handle",
        "name",
        "kind",
    }:
        target: NewDescendantTarget | ExistingObjectTarget = NewDescendantTarget(
            parent_handle=str(target_payload.get("parent_handle")),
            name=str(target_payload.get("name")),
            kind=str(target_payload.get("kind")),
        )
    elif form == "existing-object" and set(target_payload) == {
        "form",
        "object_handle",
    }:
        target = ExistingObjectTarget(
            object_handle=str(target_payload.get("object_handle"))
        )
    else:
        raise ValueError("business declaration target form is invalid")
    normalized_target = _validate_target(target, handles=handles)
    declaration = BusinessDeclaration(
        declaration_id=_declaration_id(payload.get("declaration_id")),
        target=normalized_target,
        fields=_normalize_fields(payload.get("fields")),
    )
    if len(canonical_json_bytes(declaration.as_dict())) > MAX_BUSINESS_DECLARATION_BYTES:
        raise ValueError("business declaration exceeds its fixed byte limit")
    return declaration


def _preview_from_dict(payload: Any) -> BusinessPreview:
    if not isinstance(payload, Mapping) or set(payload) != {
        "contract",
        "source_revision",
        "readable_lines",
        "detail",
        "preview_digest",
    }:
        raise ValueError("business Preview fields are invalid")
    if payload.get("contract") != BUSINESS_PREVIEW_CONTRACT:
        raise ValueError("business Preview contract is invalid")
    preview = BusinessPreview.create(
        source_revision=payload.get("source_revision"),
        readable_lines=payload.get("readable_lines"),
        detail=payload.get("detail"),
    )
    if payload.get("preview_digest") != preview.preview_digest:
        raise ValueError("business Preview digest is invalid")
    return preview


def _preview_audit_from_dict(payload: Any) -> dict[str, Any]:
    expected = {
        "contract",
        "preview",
        "invalidated_by_revision",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("business Preview audit fields are invalid")
    if payload.get("contract") != BUSINESS_PREVIEW_AUDIT_CONTRACT:
        raise ValueError("business Preview audit contract is invalid")
    preview = _preview_from_dict(payload.get("preview"))
    invalidated = payload.get("invalidated_by_revision")
    if (
        isinstance(invalidated, bool)
        or not isinstance(invalidated, int)
        or invalidated <= preview.source_revision
    ):
        raise ValueError("business Preview audit values are invalid")
    return {
        "contract": BUSINESS_PREVIEW_AUDIT_CONTRACT,
        "preview": preview.as_dict(),
        "invalidated_by_revision": invalidated,
    }


def _declaration_id(
    value: Any,
    *,
    draft_revision: int | None = None,
) -> str:
    if not isinstance(value, str) or not _DECLARATION_ID.fullmatch(value):
        raise business_repair(
            "DECLARATION_ID_INVALID",
            field="declaration_id",
            draft_revision=draft_revision,
            action="provide one short task-local declaration id",
        )
    return value


def _strict_json_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): _strict_json(item, label=label) for key, item in value.items()}


def _strict_json(value: Any, *, label: str, depth: int = 0) -> Any:
    del depth
    try:
        return strict_json_copy(value)
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise ValueError(f"{label} must contain bounded strict JSON values") from exc


def _bounded_text(value: Any, *, field: str, maximum_bytes: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise ValueError(f"{field} is empty, padded, or exceeds its byte limit")
    return value


__all__ = [
    "BUSINESS_DECLARATION_CONTRACT",
    "BUSINESS_DECLARATION_SESSION_CONTRACT",
    "BUSINESS_PREVIEW_AUDIT_CONTRACT",
    "BUSINESS_PREVIEW_CONTRACT",
    "BUSINESS_SESSION_UPDATE_EVENTS",
    "BusinessDeclaration",
    "BusinessDeclarationSession",
    "BusinessPreview",
]
