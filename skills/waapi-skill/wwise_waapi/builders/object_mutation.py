"""Source-grounded object mutation preview builders that never dispatch WAAPI calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION

from .common import (
    BuilderContext,
    BuilderFamily,
    DEFAULT_WORK_UNIT_NAME,
    ManifestSchemaLoader,
    SemanticEnvelope,
    SemanticErrorCode,
    SemanticPreview,
    SemanticReadbackPlan,
    SemanticValidationError,
    SourceNoteChecker,
    candidate_writable_child_container,
)
from wwise_waapi.builders.identity import (  # pyright: ignore[reportMissingImports]
    OBJECT_GET_URI,
    ObjectIdentity,
    ResolvedObject,
    resolve_object_identity,
)
from .schema import SchemaValidationResult, SemanticSchemaValidator  # pyright: ignore[reportMissingImports]
from .source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]


OBJECT_CREATE_URI = "ak.wwise.core.object.create"
OBJECT_SET_URI = "ak.wwise.core.object.set"
OBJECT_DELETE_URI = "ak.wwise.core.object.delete"
OBJECT_COPY_URI = "ak.wwise.core.object.copy"
OBJECT_MOVE_URI = "ak.wwise.core.object.move"
OBJECT_DIFF_URI = "ak.wwise.core.object.diff"
OBJECT_PASTE_PROPERTIES_URI = "ak.wwise.core.object.pasteProperties"
UNDO_BEGIN_GROUP_URI = "ak.wwise.core.undo.beginGroup"
UNDO_END_GROUP_URI = "ak.wwise.core.undo.endGroup"
UNDO_UNDO_URI = "ak.wwise.core.undo.undo"

DEFAULT_MUTATION_RETURN_FIELDS = ("id", "name", "type", "path")
CONFLICT_POLICIES = ("rename", "replace", "fail", "merge")
COPY_MOVE_CONFLICT_POLICIES = ("rename", "replace", "fail")
LIST_MODES = ("replaceAll", "append")
PASTE_MODES = ("replaceEntire", "addReplace", "addKeep")
class ObjectMutationOperation(str, Enum):
    """Supported P1 object mutation operations."""

    CREATE = "object.create"
    SET = "object.set"
    DELETE = "object.delete"
    COPY = "object.copy"
    MOVE = "object.move"
    DIFF = "object.diff"
    PASTE_PROPERTIES = "object.pasteProperties"
    UNDO_BEGIN_GROUP = "undo.beginGroup"
    UNDO_END_GROUP = "undo.endGroup"
    UNDO_UNDO = "undo.undo"


SUPPORTED_MUTATION_URIS: Mapping[ObjectMutationOperation, str] = {
    ObjectMutationOperation.CREATE: OBJECT_CREATE_URI,
    ObjectMutationOperation.SET: OBJECT_SET_URI,
    ObjectMutationOperation.DELETE: OBJECT_DELETE_URI,
    ObjectMutationOperation.COPY: OBJECT_COPY_URI,
    ObjectMutationOperation.MOVE: OBJECT_MOVE_URI,
    ObjectMutationOperation.DIFF: OBJECT_DIFF_URI,
    ObjectMutationOperation.PASTE_PROPERTIES: OBJECT_PASTE_PROPERTIES_URI,
    ObjectMutationOperation.UNDO_BEGIN_GROUP: UNDO_BEGIN_GROUP_URI,
    ObjectMutationOperation.UNDO_END_GROUP: UNDO_END_GROUP_URI,
    ObjectMutationOperation.UNDO_UNDO: UNDO_UNDO_URI,
}


@dataclass(slots=True, frozen=True)
class ObjectSetMutation:
    """One explicit ``object.set`` target and caller-owned field updates."""

    identity: ObjectIdentity | ResolvedObject
    values: Mapping[str, Any] = field(default_factory=dict)
    identity_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class ObjectMutationBuilder:
    """Build destructive-gated object mutation previews without hidden WAAPI calls."""

    version: str = DEFAULT_WWISE_VERSION
    source_note_checker: SourceNoteChecker | None = None
    manifest_loader: ManifestSchemaLoader = field(default_factory=ManifestSchemaLoader)

    def create(
        self,
        *,
        parent: ObjectIdentity | ResolvedObject,
        type: str,
        name: str,
        parent_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        on_name_conflict: str = "fail",
        notes: str | None = None,
        children: Sequence[Mapping[str, Any]] | None = None,
        platform: str | int | None = None,
        auto_add_to_source_control: bool | None = None,
    ) -> SemanticPreview:
        resolved_parent = _resolve_identity("parent", parent, parent_rows)
        _require_writable_parent_container(operation=ObjectMutationOperation.CREATE, parent=resolved_parent, object_type=type)
        _require_non_empty_string("type", type)
        _require_non_empty_string("name", name)
        _require_allowed("on_name_conflict", on_name_conflict, CONFLICT_POLICIES)
        args: dict[str, Any] = {"parent": resolved_parent.object, "type": type, "name": name, "onNameConflict": on_name_conflict}
        _add_optional(args, "notes", notes)
        _add_optional(args, "children", list(children) if children is not None else None)
        _add_optional(args, "platform", platform)
        _add_optional(args, "autoAddToSourceControl", auto_add_to_source_control)
        return self._build_preview(
            ObjectMutationOperation.CREATE,
            args,
            {},
            identities={"parent": resolved_parent.as_dict()},
            readback=_created_object_readback(name=name, parent=resolved_parent.object),
            cleanup={"kind": "delete-created-object", "identity": "created object id from object.create result"},
            expectation="create one object under the resolved parent; read back created id/name/type/path and delete it during cleanup if still present",
        )

    def set(
        self,
        *,
        objects: Sequence[ObjectSetMutation | Mapping[str, Any]],
        return_fields: Sequence[str] = DEFAULT_MUTATION_RETURN_FIELDS,
        on_name_conflict: str | None = None,
        list_mode: str | None = None,
        platform: str | int | None = None,
        auto_add_to_source_control: bool | None = None,
    ) -> SemanticPreview:
        if not objects:
            raise _schema_error("object.set requires at least one object mutation.", objects=[])
        entries = [_set_entry(item) for item in objects]
        args: dict[str, Any] = {"objects": [entry["payload"] for entry in entries]}
        if on_name_conflict is not None:
            _require_allowed("on_name_conflict", on_name_conflict, CONFLICT_POLICIES)
            args["onNameConflict"] = on_name_conflict
        if list_mode is not None:
            _require_allowed("list_mode", list_mode, LIST_MODES)
            args["listMode"] = list_mode
        _add_optional(args, "platform", platform)
        _add_optional(args, "autoAddToSourceControl", auto_add_to_source_control)
        options = _return_options(return_fields)
        partial_success_risk = len(entries) > 1
        return self._build_preview(
            ObjectMutationOperation.SET,
            args,
            options,
            identities={f"objects[{index}]": entry["identity"] for index, entry in enumerate(entries)},
            readback=tuple(_object_readback(entry["payload"]["object"], f"read back object.set target {index}") for index, entry in enumerate(entries)),
            cleanup={"kind": "caller-owned-rollback", "reason": "object.set overwrites fields; restore previous values from caller evidence if needed"},
            expectation="set explicit fields on resolved objects and verify each target with object.get readback; batch previews are not atomic",
            partial_success_risk=partial_success_risk,
        )

    def delete(
        self,
        *,
        object: ObjectIdentity | ResolvedObject,
        object_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    ) -> SemanticPreview:
        resolved = _resolve_identity("object", object, object_rows)
        return self._build_preview(
            ObjectMutationOperation.DELETE,
            {"object": resolved.object},
            {},
            identities={"object": resolved.as_dict()},
            readback=(_object_absence_readback(resolved.object),),
            cleanup={"kind": "none-after-delete", "reason": "readback must confirm the object no longer exists"},
            expectation="delete exactly one resolved object and verify object.get returns no rows",
        )

    def copy(
        self,
        *,
        object: ObjectIdentity | ResolvedObject,
        parent: ObjectIdentity | ResolvedObject,
        object_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        parent_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        on_name_conflict: str = "fail",
    ) -> SemanticPreview:
        return self._copy_or_move(ObjectMutationOperation.COPY, object=object, parent=parent, object_rows=object_rows, parent_rows=parent_rows, on_name_conflict=on_name_conflict)

    def move(
        self,
        *,
        object: ObjectIdentity | ResolvedObject,
        parent: ObjectIdentity | ResolvedObject,
        object_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        parent_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        on_name_conflict: str = "fail",
    ) -> SemanticPreview:
        return self._copy_or_move(ObjectMutationOperation.MOVE, object=object, parent=parent, object_rows=object_rows, parent_rows=parent_rows, on_name_conflict=on_name_conflict)

    def diff(
        self,
        *,
        source: ObjectIdentity | ResolvedObject,
        target: ObjectIdentity | ResolvedObject,
        source_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        target_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    ) -> SemanticPreview:
        resolved_source = _resolve_identity("source", source, source_rows)
        resolved_target = _resolve_identity("target", target, target_rows)
        return self._build_preview(
            ObjectMutationOperation.DIFF,
            {"source": resolved_source.object, "target": resolved_target.object},
            {},
            identities={"source": resolved_source.as_dict(), "target": resolved_target.as_dict()},
            readback=(),
            cleanup={"kind": "none", "reason": "object.diff is side-effect-free but retained in the gated mutation family"},
            expectation="compare two resolved objects and inspect returned differing lists/properties",
        )

    def paste_properties(
        self,
        *,
        source: ObjectIdentity | ResolvedObject,
        targets: Sequence[ObjectIdentity | ResolvedObject],
        source_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        target_rows: Sequence[Sequence[Mapping[str, Any]] | Mapping[str, Any] | None] | None = None,
        inclusion: Sequence[str] | None = None,
        exclusion: Sequence[str] | None = None,
        paste_mode: str | None = None,
    ) -> SemanticPreview:
        if not targets:
            raise _schema_error("pasteProperties requires at least one target.", targets=[])
        resolved_source = _resolve_identity("source", source, source_rows)
        resolved_targets = tuple(_resolve_identity(f"targets[{index}]", target, _row_at(target_rows, index)) for index, target in enumerate(targets))
        args: dict[str, Any] = {"source": resolved_source.object, "targets": [target.object for target in resolved_targets]}
        _add_optional(args, "inclusion", list(inclusion) if inclusion is not None else None)
        _add_optional(args, "exclusion", list(exclusion) if exclusion is not None else None)
        if paste_mode is not None:
            _require_allowed("paste_mode", paste_mode, PASTE_MODES)
            args["pasteMode"] = paste_mode
        return self._build_preview(
            ObjectMutationOperation.PASTE_PROPERTIES,
            args,
            {},
            identities={"source": resolved_source.as_dict(), **{f"targets[{index}]": target.as_dict() for index, target in enumerate(resolved_targets)}},
            readback=tuple(_object_readback(target.object, f"read back pasteProperties target {index}") for index, target in enumerate(resolved_targets)),
            cleanup={"kind": "caller-owned-rollback", "reason": "properties/lists on targets may be overwritten; restore from caller evidence if needed"},
            expectation="paste selected properties from one resolved source to explicit resolved targets and verify target readbacks",
        )

    def undo_begin_group(self) -> SemanticPreview:
        return self._build_preview(
            ObjectMutationOperation.UNDO_BEGIN_GROUP,
            {},
            {},
            identities={},
            readback=(),
            cleanup={"kind": "end-or-cancel-undo-group", "reason": "caller must close the undo group explicitly"},
            expectation="begin an undo group; preview lists this WAAPI call only",
        )

    def undo_end_group(self, *, display_name: str) -> SemanticPreview:
        _require_non_empty_string("display_name", display_name)
        return self._build_preview(
            ObjectMutationOperation.UNDO_END_GROUP,
            {"displayName": display_name},
            {},
            identities={},
            readback=(),
            cleanup={"kind": "undo-available", "reason": "caller may call undo.undo to roll back the completed group"},
            expectation="end the current undo group with an explicit display name",
        )

    def undo_undo(self) -> SemanticPreview:
        return self._build_preview(
            ObjectMutationOperation.UNDO_UNDO,
            {},
            {},
            identities={},
            readback=(),
            cleanup={"kind": "readback-caller-targets", "reason": "caller must read back affected objects to prove rollback"},
            expectation="undo the last undoable operation and verify expected object state with caller readbacks",
        )

    def preview(self, operation: ObjectMutationOperation | str, **kwargs: Any) -> SemanticPreview:
        normalized = _coerce_operation(operation)
        if normalized == ObjectMutationOperation.CREATE:
            return self.create(**kwargs)
        if normalized == ObjectMutationOperation.SET:
            return self.set(**kwargs)
        if normalized == ObjectMutationOperation.DELETE:
            return self.delete(**kwargs)
        if normalized == ObjectMutationOperation.COPY:
            return self.copy(**kwargs)
        if normalized == ObjectMutationOperation.MOVE:
            return self.move(**kwargs)
        if normalized == ObjectMutationOperation.DIFF:
            return self.diff(**kwargs)
        if normalized == ObjectMutationOperation.PASTE_PROPERTIES:
            return self.paste_properties(**kwargs)
        if normalized == ObjectMutationOperation.UNDO_BEGIN_GROUP:
            return self.undo_begin_group()
        if normalized == ObjectMutationOperation.UNDO_END_GROUP:
            return self.undo_end_group(**kwargs)
        if normalized == ObjectMutationOperation.UNDO_UNDO:
            return self.undo_undo()
        raise _schema_error("Unsupported object mutation operation.", operation=str(operation))

    def _copy_or_move(
        self,
        operation: ObjectMutationOperation,
        *,
        object: ObjectIdentity | ResolvedObject,
        parent: ObjectIdentity | ResolvedObject,
        object_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
        parent_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
        on_name_conflict: str,
    ) -> SemanticPreview:
        resolved_object = _resolve_identity("object", object, object_rows)
        resolved_parent = _resolve_identity("parent", parent, parent_rows)
        _require_writable_parent_container(operation=operation, parent=resolved_parent)
        _require_allowed("on_name_conflict", on_name_conflict, COPY_MOVE_CONFLICT_POLICIES)
        return self._build_preview(
            operation,
            {"object": resolved_object.object, "parent": resolved_parent.object, "onNameConflict": on_name_conflict},
            {},
            identities={"object": resolved_object.as_dict(), "parent": resolved_parent.as_dict()},
            readback=(_object_readback(resolved_object.object, f"read back {operation.value} source/created object"),),
            cleanup={"kind": "delete-or-move-back", "reason": f"caller must clean up or restore the object after {operation.value}"},
            expectation=f"{operation.value} exactly one resolved object to an explicit resolved parent and verify readback",
        )

    def _build_preview(
        self,
        operation: ObjectMutationOperation,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
        *,
        identities: Mapping[str, Any],
        readback: tuple[SemanticReadbackPlan, ...],
        cleanup: Mapping[str, Any],
        expectation: str,
        partial_success_risk: bool = False,
    ) -> SemanticPreview:
        context = BuilderContext(
            BuilderFamily.OBJECT_MUTATION,
            version=self.version,
            source_note_checker=self.source_note_checker or SemanticSourceNoteChecker(),
            manifest_loader=self.manifest_loader,
        )
        context.require_supported_family()
        source_note = context.require_source_note()
        uri = SUPPORTED_MUTATION_URIS[operation]
        schema_validation = SemanticSchemaValidator(manifest_loader=context.manifest_loader, version=context.version).validate(uri, args, options)
        envelope = SemanticEnvelope(
            uri,
            args=dict(args),
            options=dict(options),
            metadata=_preview_metadata(operation, identities, schema_validation, source_note.as_dict(), cleanup, expectation, partial_success_risk),
        )
        return SemanticPreview(
            envelope=envelope,
            source_note_family=BuilderFamily.OBJECT_MUTATION.value,
            version=self.version,
            readback_plan=readback,
            evidence_plan=(
                {"kind": "source-note", "family": BuilderFamily.OBJECT_MUTATION.value, "status": source_note.as_dict()},
                {"kind": "schema", "validation": schema_validation.as_dict()},
                {"kind": "identity", "resolved": dict(identities)},
                {"kind": "readback", "plans": [plan.as_dict() for plan in readback], "expectation": expectation},
                {**dict(cleanup), "kind": "cleanup"},
            ),
            requires_destructive_gate=True,
        )


def build_object_mutation_preview(
    operation: ObjectMutationOperation | str,
    *,
    source_note_checker: SourceNoteChecker | None = None,
    version: str = DEFAULT_WWISE_VERSION,
    **kwargs: Any,
) -> SemanticPreview:
    """Convenience wrapper around :class:`ObjectMutationBuilder`."""

    return ObjectMutationBuilder(version=version, source_note_checker=source_note_checker).preview(operation, **kwargs)


def _resolve_identity(
    role: str,
    identity: ObjectIdentity | ResolvedObject,
    rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
) -> ResolvedObject:
    if isinstance(identity, ResolvedObject):
        return identity
    resolved = resolve_object_identity(identity, rows, destructive_use=True)
    if not isinstance(resolved, ResolvedObject):
        raise _identity_error(role, identity.as_dict())
    return resolved


def _require_writable_parent_container(
    *,
    operation: ObjectMutationOperation,
    parent: ResolvedObject,
    object_type: str | None = None,
) -> None:
    parent_path = _resolved_parent_path(parent)
    if parent_path is None:
        return
    candidate = candidate_writable_child_container(parent_path)
    if candidate is None:
        return
    message = (
        f"{operation.value} requires a writable child container, not the management root path {parent_path!r}."
    )
    if object_type is not None:
        message = (
            f"{operation.value} cannot place {object_type!r} directly under the management root path {parent_path!r}."
        )
    raise _schema_error(
        message,
        operation=operation.value,
        invalid_parent_path=parent_path,
        candidate_writable_parent=candidate,
        requires_user_confirmation=True,
        reason="Use a writable child container such as Default Work Unit instead of mutating the hierarchy/category root directly.",
    )


def _resolved_parent_path(parent: ResolvedObject) -> str | None:
    identity_path = parent.identity.path
    if isinstance(identity_path, str) and identity_path.strip():
        return identity_path
    row_path = parent.row.get("path")
    if isinstance(row_path, str) and row_path.strip():
        return row_path
    if isinstance(parent.object, str) and parent.object.startswith("\\"):
        return parent.object
    return None


def _set_entry(item: ObjectSetMutation | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(item, ObjectSetMutation):
        identity = item.identity
        values = dict(item.values)
        rows = item.identity_rows
    else:
        identity = item.get("identity")
        values = dict(item.get("values", {}))
        rows = item.get("identity_rows")
    if not isinstance(identity, (ObjectIdentity, ResolvedObject)):
        raise _schema_error("object.set entries require an ObjectIdentity or ResolvedObject identity.", entry=dict(item) if isinstance(item, Mapping) else {})
    checked_identity: ObjectIdentity | ResolvedObject = identity
    if not values:
        raise _schema_error("object.set entries require at least one explicit field to set.", identity=checked_identity.as_dict())
    if "object" in values:
        raise _schema_error("object.set values must not include object; provide identity separately.", identity=checked_identity.as_dict())
    resolved = _resolve_identity("object", checked_identity, rows)
    payload = {"object": resolved.object, **values}
    return {"payload": payload, "identity": resolved.as_dict()}


def _created_object_readback(*, name: str, parent: str | int) -> tuple[SemanticReadbackPlan, ...]:
    return (
        SemanticReadbackPlan(
            OBJECT_GET_URI,
            args={"waql": f'from object "{_escape_waql(str(parent))}" transform select children where name = "{_escape_waql(name)}"'},
            options={"return": list(DEFAULT_MUTATION_RETURN_FIELDS)},
            description="read back newly created child by resolved parent and name",
        ),
    )


def _object_readback(object_value: str | int, description: str) -> SemanticReadbackPlan:
    return SemanticReadbackPlan(
        OBJECT_GET_URI,
        args={"from": {"id": [object_value]} if isinstance(object_value, int) else {"path": [object_value]} if str(object_value).startswith("\\") else {"id": [object_value]}},
        options={"return": list(DEFAULT_MUTATION_RETURN_FIELDS)},
        description=description,
    )


def _object_absence_readback(object_value: str | int) -> SemanticReadbackPlan:
    plan = _object_readback(object_value, "verify deleted object readback returns no rows")
    return SemanticReadbackPlan(plan.uri, args=plan.args, options=plan.options, description=plan.description)


def _return_options(return_fields: Sequence[str]) -> dict[str, Any]:
    if not return_fields or not all(isinstance(field, str) and field for field in return_fields):
        raise _schema_error("Mutation previews require explicit non-empty return fields for object.set readback.", return_fields=list(return_fields or []))
    return {"return": list(return_fields)}


def _preview_metadata(
    operation: ObjectMutationOperation,
    identities: Mapping[str, Any],
    schema_validation: SchemaValidationResult,
    source_note: Mapping[str, Any],
    cleanup: Mapping[str, Any],
    expectation: str,
    partial_success_risk: bool,
) -> dict[str, Any]:
    return {
        "builder_family": BuilderFamily.OBJECT_MUTATION.value,
        "operation": operation.value,
        "source_note": dict(source_note),
        "schema_validation": schema_validation.as_dict(),
        "resolved_identities": dict(identities),
        "read_only": False,
        "destructive_gate": {"required": True, "reason": "object mutation previews must be reviewed before dispatch"},
        "readback_expectation": expectation,
        "cleanup_expectation": dict(cleanup),
        "partial_success_risk": partial_success_risk,
        "atomicity": "not-claimed" if partial_success_risk else "single-waapi-call-only",
    }


def _coerce_operation(operation: ObjectMutationOperation | str) -> ObjectMutationOperation:
    if isinstance(operation, ObjectMutationOperation):
        return operation
    for candidate, uri in SUPPORTED_MUTATION_URIS.items():
        if operation in {candidate.value, uri}:
            return candidate
    raise _schema_error("Unsupported object mutation operation.", operation=str(operation), supported=[item.value for item in ObjectMutationOperation])


def _row_at(rows: Sequence[Sequence[Mapping[str, Any]] | Mapping[str, Any] | None] | None, index: int) -> Sequence[Mapping[str, Any]] | Mapping[str, Any] | None:
    if rows is None:
        return None
    return rows[index] if index < len(rows) else None


def _add_optional(args: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        args[key] = value


def _require_non_empty_string(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise _schema_error(f"{name} must be a non-empty string.", field=name, value=value)


def _require_allowed(name: str, value: str, supported: Sequence[str]) -> None:
    if value not in supported:
        raise _schema_error(f"Unsupported {name}: {value!r}.", field=name, value=value, supported=list(supported))


def _identity_error(role: str, identity: Mapping[str, Any]) -> SemanticValidationError:
    return SemanticValidationError(
        SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY,
        f"Destructive object mutation requires exact or pre-resolved identity for {role}.",
        details={"role": role, "identity": dict(identity)},
    )


def _schema_error(message: str, **details: Any) -> SemanticValidationError:
    return SemanticValidationError(SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH, message, details=details)


def _escape_waql(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
