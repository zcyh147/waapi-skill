"""Switch Container assignment semantic builders and topic expectations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence, cast

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION  # pyright: ignore[reportMissingImports]

from .common import (  # pyright: ignore[reportMissingImports]
    BuilderContext,
    BuilderFamily,
    ManifestSchemaLoader,
    SemanticEnvelope,
    SemanticErrorCode,
    SemanticPreview,
    SemanticReadbackPlan,
    SemanticValidationError,
    SourceNoteCheck,
    SourceNoteChecker,
)
from .identity import ObjectIdentity, ResolutionPlan, ResolvedObject, resolve_object_identity  # pyright: ignore[reportMissingImports]
from .schema import SemanticSchemaValidator  # pyright: ignore[reportMissingImports]
from .source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]


GET_ASSIGNMENTS_URI = "ak.wwise.core.switchContainer.getAssignments"
ADD_ASSIGNMENT_URI = "ak.wwise.core.switchContainer.addAssignment"
REMOVE_ASSIGNMENT_URI = "ak.wwise.core.switchContainer.removeAssignment"
ASSIGNMENT_ADDED_TOPIC_URI = "ak.wwise.core.switchContainer.assignmentAdded"
ASSIGNMENT_REMOVED_TOPIC_URI = "ak.wwise.core.switchContainer.assignmentRemoved"
DEFAULT_TOPIC_RETURN_FIELDS = ("id", "name", "type", "path")


class SwitchContainerOperation(str, Enum):
    """Supported Switch Container assignment operations."""

    GET_ASSIGNMENTS = "getAssignments"
    ADD_ASSIGNMENT = "addAssignment"
    REMOVE_ASSIGNMENT = "removeAssignment"


@dataclass(slots=True, frozen=True)
class AssignmentPair:
    """One Switch Container assignment pair from getAssignments readback."""

    child: str | int
    state_or_switch: str | int
    raw: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"child": self.child, "stateOrSwitch": self.state_or_switch, "raw": dict(self.raw)}


@dataclass(slots=True, frozen=True)
class TopicExpectation:
    """Evidence-only expectation for Switch Container assignment topics."""

    uri: str
    options: Mapping[str, Any]
    expected_container: str | int
    expected_child: str | int
    expected_state_or_switch: str | int
    assignment_id: str | int | None = None
    metadata: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload_identity = {
            "switchContainer": self.expected_container,
            "child": self.expected_child,
            "stateOrSwitch": self.expected_state_or_switch,
        }
        if self.assignment_id is not None:
            payload_identity["assignment"] = self.assignment_id
        return {
            "uri": self.uri,
            "options": dict(self.options),
            "payload_identity": payload_identity,
            "assignment_id_required_when_available": True,
            "hidden_subscription": False,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(slots=True, frozen=True)
class SwitchContainerAssignmentBuilder:
    """Build source-grounded Switch Container assignment previews without dispatching."""

    version: str = DEFAULT_WWISE_VERSION
    source_note_checker: SourceNoteChecker | None = None
    manifest_loader: ManifestSchemaLoader = field(default_factory=ManifestSchemaLoader)

    def get_assignments(self, *, switch_container: ObjectIdentity | str | int) -> SemanticPreview:
        source_note, validator = self._validated_context()
        container = _resolve_required_exact(switch_container, role="switchContainer", destructive_use=False)
        args = {"id": container.object}
        options: dict[str, Any] = {}
        schema_validation = validator.validate(GET_ASSIGNMENTS_URI, args=args, options=options)
        envelope = SemanticEnvelope(
            GET_ASSIGNMENTS_URI,
            args=args,
            options=options,
            metadata={
                "builder_family": BuilderFamily.SWITCHCONTAINER.value,
                "operation": SwitchContainerOperation.GET_ASSIGNMENTS.value,
                "source_note": source_note.as_dict(),
                "schema_validation": schema_validation.as_dict(),
                "read_only": True,
                "identity_resolution": {"switchContainer": container.as_dict()},
                "return_expectation": {
                    "parser": "parse_get_assignments_result",
                    "shape": "object-with-return-assignment-array",
                    "required_fields": ["return[].child", "return[].stateOrSwitch"],
                },
            },
        )
        return SemanticPreview(
            envelope=envelope,
            source_note_family=BuilderFamily.SWITCHCONTAINER.value,
            version=self.version,
            readback_plan=(
                SemanticReadbackPlan(
                    GET_ASSIGNMENTS_URI,
                    args=args,
                    options=options,
                    description="read back Switch Container assignment pairs",
                ),
            ),
            evidence_plan=(
                {"kind": "source-note", "family": BuilderFamily.SWITCHCONTAINER.value, "version": self.version},
                {"kind": "schema", "uri": GET_ASSIGNMENTS_URI, "version": self.version},
            ),
        )

    def add_assignment(
        self,
        *,
        switch_container: ObjectIdentity | str | int,
        child: ObjectIdentity | str | int,
        state_or_switch: ObjectIdentity | str | int,
        existing_assignments: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    ) -> SemanticPreview:
        return self._mutation_preview(
            SwitchContainerOperation.ADD_ASSIGNMENT,
            switch_container=switch_container,
            child=child,
            state_or_switch=state_or_switch,
            existing_assignments=existing_assignments,
        )

    def remove_assignment(
        self,
        *,
        switch_container: ObjectIdentity | str | int,
        child: ObjectIdentity | str | int,
        state_or_switch: ObjectIdentity | str | int,
        existing_assignments: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    ) -> SemanticPreview:
        return self._mutation_preview(
            SwitchContainerOperation.REMOVE_ASSIGNMENT,
            switch_container=switch_container,
            child=child,
            state_or_switch=state_or_switch,
            existing_assignments=existing_assignments,
        )

    def topic_expectation(
        self,
        uri: str,
        *,
        switch_container: ObjectIdentity | str | int,
        child: ObjectIdentity | str | int,
        state_or_switch: ObjectIdentity | str | int,
        assignment_id: str | int | None = None,
        return_fields: Sequence[str] = DEFAULT_TOPIC_RETURN_FIELDS,
    ) -> TopicExpectation:
        if uri not in {ASSIGNMENT_ADDED_TOPIC_URI, ASSIGNMENT_REMOVED_TOPIC_URI}:
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
                f"Unsupported Switch Container assignment topic: {uri!r}",
                details={"uri": uri},
            )
        source_note, validator = self._validated_context()
        options = {"return": _return_fields(return_fields)}
        validation = validator.validate(uri, args={}, options=options)
        container = _resolve_required_exact(switch_container, role="switchContainer", destructive_use=False)
        resolved_child = _resolve_required_exact(child, role="child", destructive_use=False)
        resolved_state = _resolve_required_exact(state_or_switch, role="stateOrSwitch", destructive_use=False)
        return TopicExpectation(
            uri=uri,
            options=options,
            expected_container=container.object,
            expected_child=resolved_child.object,
            expected_state_or_switch=resolved_state.object,
            assignment_id=assignment_id,
            metadata={
                "builder_family": BuilderFamily.SWITCHCONTAINER.value,
                "source_note": source_note.as_dict(),
                "schema_validation": validation.as_dict(),
                "readback_required": "getAssignments must prove the assignment pair around the mutation before topic evidence passes",
            },
        )

    def assignment_added_expectation(self, **kwargs: Any) -> TopicExpectation:
        return self.topic_expectation(ASSIGNMENT_ADDED_TOPIC_URI, **kwargs)

    def assignment_removed_expectation(self, **kwargs: Any) -> TopicExpectation:
        return self.topic_expectation(ASSIGNMENT_REMOVED_TOPIC_URI, **kwargs)

    def _mutation_preview(
        self,
        operation: SwitchContainerOperation,
        *,
        switch_container: ObjectIdentity | str | int,
        child: ObjectIdentity | str | int,
        state_or_switch: ObjectIdentity | str | int,
        existing_assignments: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    ) -> SemanticPreview:
        source_note, validator = self._validated_context()
        container = _resolve_required_exact(switch_container, role="switchContainer", destructive_use=True)
        resolved_child = _resolve_required_exact(child, role="child", destructive_use=True)
        resolved_state = _resolve_required_exact(state_or_switch, role="stateOrSwitch", destructive_use=True)
        rows = parse_get_assignments_result(existing_assignments)
        _validate_relationship_state(operation, rows, child=resolved_child.object, state_or_switch=resolved_state.object)

        uri = ADD_ASSIGNMENT_URI if operation == SwitchContainerOperation.ADD_ASSIGNMENT else REMOVE_ASSIGNMENT_URI
        args = {"child": resolved_child.object, "stateOrSwitch": resolved_state.object}
        options: dict[str, Any] = {}
        schema_validation = validator.validate(uri, args=args, options=options)
        preflight = SemanticReadbackPlan(
            GET_ASSIGNMENTS_URI,
            args={"id": container.object},
            options={},
            description="preflight getAssignments must prove existing relationship state before mutation",
        )
        readback = SemanticReadbackPlan(
            GET_ASSIGNMENTS_URI,
            args={"id": container.object},
            options={},
            description=f"post-{operation.value} getAssignments readback must verify the assignment pair",
        )
        envelope = SemanticEnvelope(
            uri,
            args=args,
            options=options,
            metadata={
                "builder_family": BuilderFamily.SWITCHCONTAINER.value,
                "operation": operation.value,
                "source_note": source_note.as_dict(),
                "schema_validation": schema_validation.as_dict(),
                "read_only": False,
                "destructive_gate": {"required": True, "env": {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1"}, "allow_source_mutation": False},
                "identity_resolution": {
                    "switchContainer": container.as_dict(),
                    "child": resolved_child.as_dict(),
                    "stateOrSwitch": resolved_state.as_dict(),
                },
                "preflight_plan": preflight.as_dict(),
                "post_mutation_readback_plan": readback.as_dict(),
                "relationship_rule": _relationship_rule(operation),
                "existing_assignment_count": len(rows),
                "no_op_allowed": False,
            },
        )
        return SemanticPreview(
            envelope=envelope,
            source_note_family=BuilderFamily.SWITCHCONTAINER.value,
            version=self.version,
            readback_plan=(preflight, readback),
            evidence_plan=(
                {"kind": "source-note", "family": BuilderFamily.SWITCHCONTAINER.value, "version": self.version},
                {"kind": "schema", "uri": uri, "version": self.version},
                {"kind": "preflight", "uri": GET_ASSIGNMENTS_URI, "must_execute_before": uri},
                {"kind": "readback", "uri": GET_ASSIGNMENTS_URI, "must_execute_after": uri},
            ),
            requires_destructive_gate=True,
        )

    def _validated_context(self) -> tuple[SourceNoteCheck, SemanticSchemaValidator]:
        context = BuilderContext(
            BuilderFamily.SWITCHCONTAINER,
            version=self.version,
            source_note_checker=self.source_note_checker or SemanticSourceNoteChecker(),
            manifest_loader=self.manifest_loader,
        )
        context.require_supported_family()
        source_note = context.require_source_note()
        validator = SemanticSchemaValidator(manifest_loader=self.manifest_loader, version=self.version)
        validator.require_supported_version()
        return source_note, validator


def build_get_assignments_preview(**kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).get_assignments(**kwargs)


def build_add_assignment_preview(**kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).add_assignment(**kwargs)


def build_remove_assignment_preview(**kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).remove_assignment(**kwargs)


def build_assignment_added_expectation(**kwargs: Any) -> TopicExpectation:
    return _builder_from_kwargs(kwargs).assignment_added_expectation(**kwargs)


def build_assignment_removed_expectation(**kwargs: Any) -> TopicExpectation:
    return _builder_from_kwargs(kwargs).assignment_removed_expectation(**kwargs)


def _builder_from_kwargs(kwargs: dict[str, Any]) -> SwitchContainerAssignmentBuilder:
    return SwitchContainerAssignmentBuilder(
        version=kwargs.pop("version", DEFAULT_WWISE_VERSION),
        source_note_checker=kwargs.pop("source_note_checker", None),
    )


def parse_get_assignments_result(payload: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None) -> tuple[AssignmentPair, ...]:
    """Parse getAssignments rows and fail closed when state is absent or malformed."""

    if payload is None:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Switch Container mutation previews require explicit getAssignments preflight rows.",
            details={"missing": "existing_assignments"},
        )
    rows = _assignment_rows(payload)
    parsed: list[AssignmentPair] = []
    for index, row in enumerate(rows):
        if "child" not in row or "stateOrSwitch" not in row:
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
                "getAssignments rows must include child and stateOrSwitch.",
                details={"row_index": index, "row": dict(row), "missing_fields": [field for field in ("child", "stateOrSwitch") if field not in row]},
            )
        child = _object_ref(row["child"])
        state = _object_ref(row["stateOrSwitch"])
        if child is None or state is None:
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
                "getAssignments row identities must resolve to id, path, name, or scalar values.",
                details={"row_index": index, "row": dict(row)},
            )
        parsed.append(AssignmentPair(child=child, state_or_switch=state, raw=dict(row)))
    return tuple(parsed)


def _resolve_required_exact(value: ObjectIdentity | str | int, *, role: str, destructive_use: bool) -> ResolvedObject:
    identity: ObjectIdentity
    if isinstance(value, ObjectIdentity):
        identity = value
    else:
        identity = ObjectIdentity(id=value)
    resolved = resolve_object_identity(identity, destructive_use=destructive_use)
    if not isinstance(resolved, ResolvedObject):
        plan = cast(ResolutionPlan, resolved)
        raise SemanticValidationError(
            SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY,
            f"Switch Container assignment previews require exact or resolved {role} identity.",
            details={"role": role, "identity": identity.as_dict(), "resolution_plan": plan.as_dict()},
        )
    return resolved


def _assignment_rows(payload: Sequence[Mapping[str, Any]] | Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    if isinstance(payload, Mapping):
        value = payload.get("return")
        if not isinstance(value, list):
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
                "getAssignments result must contain a return array.",
                details={"payload": dict(payload)},
            )
        return tuple(row for row in value if isinstance(row, Mapping))
    return tuple(row for row in payload if isinstance(row, Mapping))


def _object_ref(value: Any) -> str | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int)):
        return value if value != "" else None
    if isinstance(value, Mapping):
        for key in ("id", "path", "name"):
            candidate = value.get(key)
            if isinstance(candidate, (str, int)) and not isinstance(candidate, bool) and candidate != "":
                return candidate
    return None


def _validate_relationship_state(operation: SwitchContainerOperation, rows: Sequence[AssignmentPair], *, child: str | int, state_or_switch: str | int) -> None:
    exact = [row for row in rows if row.child == child and row.state_or_switch == state_or_switch]
    same_child = [row for row in rows if row.child == child]
    if operation == SwitchContainerOperation.ADD_ASSIGNMENT:
        if exact:
            raise SemanticValidationError(
                SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED,
                "addAssignment would be a duplicate/no-op; source notes do not allow claiming no-op success.",
                details={"child": child, "stateOrSwitch": state_or_switch, "existing": [row.as_dict() for row in exact]},
            )
        if same_child:
            raise SemanticValidationError(
                SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED,
                "addAssignment requires fail-closed relationship state: child is already assigned to another stateOrSwitch.",
                details={"child": child, "stateOrSwitch": state_or_switch, "existing": [row.as_dict() for row in same_child]},
            )
        return
    if not exact:
        raise SemanticValidationError(
            SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED,
            "removeAssignment requires a proven existing child/stateOrSwitch pair; no-op removal is not source-note allowed.",
            details={"child": child, "stateOrSwitch": state_or_switch, "existing": [row.as_dict() for row in rows]},
        )


def _relationship_rule(operation: SwitchContainerOperation) -> str:
    if operation == SwitchContainerOperation.ADD_ASSIGNMENT:
        return "fail closed unless preflight getAssignments proves the child has no existing assignment and target pair is absent"
    return "fail closed unless preflight getAssignments proves the target child/stateOrSwitch pair exists before removal"


def _return_fields(return_fields: Sequence[str]) -> list[str]:
    fields = [field for field in return_fields if isinstance(field, str) and field]
    if len(fields) != len(tuple(return_fields)) or not fields:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Topic expectations require explicit non-empty return fields.",
            details={"return_fields": list(return_fields)},
        )
    return fields
