"""Structured semantic intent and plan contracts for WAAPI planning.

This module is intentionally schema-only: it validates typed intent envelopes and
serializes closed plan records, but it does not parse prose, call builders, or
dispatch WAAPI requests.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence, cast

from wwise_waapi.builders.common import ManifestSchemaLoader, SemanticErrorCode, SemanticValidationError
from wwise_waapi.builders.profiler import extract_profiler_parameter_guidance  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.query import QueryPredicate, build_object_get_query  # pyright: ignore[reportMissingImports]


SEMANTIC_CONFIRMATION_STATES = ("unknown", "preview", "confirmed", "rejected")
SUPPORTED_WWISE_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
SUPPORTED_SEMANTIC_FAMILIES = (
    "intent_navigation",
    "crud_authoring",
    "system_design_preview",
    "asset_import_workflow",
    "soundbank_workflow",
    "switch_assignment_workflow",
    "bounded_profiler_guidance",
    "unsupported_runtime_boundary",
)
SEMANTIC_FAMILY_BUILDER_REFS: Mapping[str, tuple[str, ...]] = {
    "intent_navigation": ("wwise_waapi.builders.query",),
    "crud_authoring": ("wwise_waapi.builders.object_mutation", "wwise_waapi.builders.properties"),
    "system_design_preview": (
        "wwise_waapi.builders.query",
        "wwise_waapi.builders.object_mutation",
        "wwise_waapi.builders.properties",
        "wwise_waapi.builders.imports",
    ),
    "asset_import_workflow": ("wwise_waapi.builders.imports",),
    "soundbank_workflow": ("wwise_waapi.builders.soundbank",),
    "switch_assignment_workflow": ("wwise_waapi.builders.switchcontainer",),
    "bounded_profiler_guidance": ("wwise_waapi.builders.profiler",),
    "unsupported_runtime_boundary": (),
}
UNSUPPORTED_BOUNDARY_ALTERNATIVES: Mapping[str, str] = {
    "scheduler_delayed_event_posting": "preview_supported_authoring_plan",
    "rtpc_ramp_over_time": "preview_supported_authoring_plan",
    "game_object_view_emitter_movement": "live_read_summary",
    "timed_ambience_playback": "preview_supported_authoring_plan",
    "audio_narrative_sequencing": "preview_supported_authoring_plan",
    "cross_app_mcp_federation": "live_read_summary",
    "runtime_orchestration": "preview_supported_authoring_plan",
}
UNSUPPORTED_BOUNDARY_REASONS: Mapping[str, str] = {
    "scheduler_delayed_event_posting": (
        "scheduler delayed event posting is runtime orchestration outside the WAAPI authoring planner boundary"
    ),
    "rtpc_ramp_over_time": "RTPC ramps over time are runtime automation outside the WAAPI authoring planner boundary",
    "game_object_view_emitter_movement": (
        "Game Object View emitter movement/control is foreground runtime UI behavior outside the WAAPI authoring planner boundary"
    ),
    "timed_ambience_playback": "timed ambience playback is runtime transport orchestration outside the WAAPI authoring planner boundary",
    "audio_narrative_sequencing": "audio narrative sequencing is runtime event choreography outside the WAAPI authoring planner boundary",
    "cross_app_mcp_federation": "cross-app MCP federation is outside the local WAAPI authoring planner boundary",
    "runtime_orchestration": "runtime orchestration capabilities are outside the WAAPI authoring planner boundary",
}
UNSUPPORTED_BOUNDARY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scheduler_delayed_event_posting", ("scheduler", "schedule", "scheduled", "delayed event", "delayed_event", "post_later", "post later")),
    ("rtpc_ramp_over_time", ("rtpc ramp", "rtpc_ramp", "ramp over time", "ramp_over_time", "runtime rtpc", "automate rtpc")),
    (
        "game_object_view_emitter_movement",
        ("game object view", "game_object_view", "emitter movement", "emitter_movement", "move emitter", "emitter control"),
    ),
    ("timed_ambience_playback", ("timed ambience", "timed_ambience", "ambience playback", "ambient playback", "play ambience")),
    (
        "audio_narrative_sequencing",
        ("narrative sequencing", "narrative_sequence", "event sequencing", "runtime sequencing", "sequence audio", "audio narrative"),
    ),
    ("cross_app_mcp_federation", ("cross-app mcp", "cross_app_mcp", "mcp federation", "federation", "multi-app mcp", "external mcp")),
)


class SemanticPlanStatus(str, Enum):
    """Closed status values for schema-only semantic plans."""

    READY = "ready"
    BLOCKED = "blocked"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"


@dataclass(slots=True, frozen=True)
class SemanticIntentTarget:
    """One structured target supplied by the caller's semantic intent envelope."""

    kind: str
    identifier: str
    display_name: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "identifier": self.identifier,
            "display_name": self.display_name,
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(slots=True, frozen=True)
class SemanticIntentConstraint:
    """One typed constraint supplied by a caller before planning."""

    field: str
    operator: str
    value: Any
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "operator": self.operator,
            "value": _json_safe(self.value),
            "reason": self.reason,
        }


@dataclass(slots=True, frozen=True)
class SemanticIntent:
    """Structured planner input; arbitrary natural-language strings are not accepted."""

    family: str
    goal: str
    version: str
    targets: Sequence[SemanticIntentTarget | Mapping[str, Any]]
    constraints: Sequence[SemanticIntentConstraint | Mapping[str, Any]]
    requested_operations: Sequence[str]
    confirmation_state: str
    source_prompt_excerpt: str

    def __post_init__(self) -> None:
        _require_supported_family(self.family)
        if not self.goal:
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
                "Semantic intent requires a non-empty goal.",
                details={"field": "goal"},
            )
        _require_confirmation_state(self.confirmation_state)
        object.__setattr__(self, "targets", tuple(_intent_target(target) for target in self.targets))
        object.__setattr__(self, "constraints", tuple(_intent_constraint(constraint) for constraint in self.constraints))
        object.__setattr__(self, "requested_operations", tuple(str(operation) for operation in self.requested_operations))

    def as_dict(self) -> dict[str, Any]:
        targets = cast(tuple[SemanticIntentTarget, ...], self.targets)
        constraints = cast(tuple[SemanticIntentConstraint, ...], self.constraints)
        return {
            "family": self.family,
            "goal": self.goal,
            "version": self.version,
            "targets": [target.as_dict() for target in targets],
            "constraints": [constraint.as_dict() for constraint in constraints],
            "requested_operations": list(self.requested_operations),
            "confirmation_state": self.confirmation_state,
            "source_prompt_excerpt": self.source_prompt_excerpt,
        }


@dataclass(slots=True, frozen=True)
class SemanticPlanPreview:
    """Serializable preview identity generated by a later builder-backed planner."""

    preview_id: str
    preview_hash: str
    summary: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "preview_id": self.preview_id,
            "preview_hash": self.preview_hash,
            "summary": self.summary,
            "payload": _json_safe_mapping(self.payload),
        }


@dataclass(slots=True, frozen=True)
class SemanticPlanVerification:
    """One deterministic verification step expected after preview or execution."""

    kind: str
    description: str
    preview_hash: str = ""
    readback_plan: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "description": self.description,
            "preview_hash": self.preview_hash,
            "readback_plan": _json_safe_mapping(self.readback_plan),
        }


@dataclass(slots=True, frozen=True)
class SemanticPlanStep:
    """Closed schema for one future planner step; no dispatch behavior is attached."""

    step_id: str
    operation: str
    family: str
    preview: SemanticPlanPreview | Mapping[str, Any] | None = None
    inputs: Mapping[str, Any] = field(default_factory=dict)
    source_builder_ref: str = ""
    builder_ref: str = ""
    api: str = ""
    args_preview: Mapping[str, Any] = field(default_factory=dict)
    options_preview: Mapping[str, Any] = field(default_factory=dict)
    target_identity: Mapping[str, Any] = field(default_factory=dict)
    read_only: bool = False
    project_changing: bool = False

    def __post_init__(self) -> None:
        _require_supported_family(self.family)
        if self.preview is not None and not isinstance(self.preview, SemanticPlanPreview):
            object.__setattr__(self, "preview", _plan_preview(self.preview))

    def as_dict(self) -> dict[str, Any]:
        preview = cast(SemanticPlanPreview | None, self.preview)
        return {
            "step_id": self.step_id,
            "operation": self.operation,
            "family": self.family,
            "preview": preview.as_dict() if preview is not None else None,
            "inputs": _json_safe_mapping(self.inputs),
            "source_builder_ref": self.source_builder_ref,
            "builder_ref": self.builder_ref or self.source_builder_ref,
            "api": self.api,
            "args_preview": _json_safe_mapping(self.args_preview),
            "options_preview": _json_safe_mapping(self.options_preview),
            "target_identity": _json_safe_mapping(self.target_identity),
            "read_only": self.read_only,
            "project_changing": self.project_changing,
        }


@dataclass(slots=True, frozen=True)
class SemanticPlan:
    """Top-level semantic plan envelope returned by the schema-only planner."""

    status: SemanticPlanStatus | str
    family: str
    version: str
    steps: Sequence[SemanticPlanStep | Mapping[str, Any]]
    preview_id: str
    preview_hash: str
    risk_flags: Sequence[str]
    requires_confirmation: bool
    blocked_reason: str
    needs_clarification: bool
    unsupported_capability: bool
    verification_steps: Sequence[SemanticPlanVerification | Mapping[str, Any]]
    source_builder_refs: Sequence[str]
    clarification: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_supported_family(self.family)
        status = SemanticPlanStatus(self.status)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "steps", tuple(_plan_step(step) for step in self.steps))
        object.__setattr__(self, "risk_flags", tuple(str(flag) for flag in self.risk_flags))
        object.__setattr__(self, "verification_steps", tuple(_plan_verification(step) for step in self.verification_steps))
        object.__setattr__(self, "source_builder_refs", tuple(str(ref) for ref in self.source_builder_refs))

    def as_dict(self) -> dict[str, Any]:
        status = cast(SemanticPlanStatus, self.status)
        steps = cast(tuple[SemanticPlanStep, ...], self.steps)
        verification_steps = cast(tuple[SemanticPlanVerification, ...], self.verification_steps)
        return {
            "status": status.value,
            "family": self.family,
            "version": self.version,
            "steps": [step.as_dict() for step in steps],
            "preview_id": self.preview_id,
            "preview_hash": self.preview_hash,
            "risk_flags": list(self.risk_flags),
            "requires_confirmation": self.requires_confirmation,
            "blocked_reason": self.blocked_reason,
            "needs_clarification": self.needs_clarification,
            "unsupported_capability": self.unsupported_capability,
            "verification_steps": [step.as_dict() for step in verification_steps],
            "source_builder_refs": list(self.source_builder_refs),
            "clarification": _json_safe_mapping(self.clarification),
        }


class SemanticPlanner:
    """Schema-only planner boundary that accepts typed intent envelopes only."""

    def __init__(self, *, manifest_loader: ManifestSchemaLoader | None = None) -> None:
        self._manifest_loader = manifest_loader or ManifestSchemaLoader()

    def plan(self, intent: SemanticIntent) -> SemanticPlan:
        if not isinstance(intent, SemanticIntent):
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
                "Semantic planner input must be a structured SemanticIntent.",
                details={"expected": "SemanticIntent", "received": type(intent).__name__},
        )
        _require_supported_family(intent.family)

        version_error = _version_support_error(intent.version, self._manifest_loader)
        if version_error is not None:
            return _blocked_version_plan(intent, version_error)

        ambiguous_target = _ambiguous_target_clarification(intent)
        if ambiguous_target is not None:
            return _needs_target_clarification_plan(intent, ambiguous_target)

        unsupported_reason = _unsupported_boundary_capability(intent)
        if intent.family == "unsupported_runtime_boundary" or unsupported_reason:
            return _unsupported_boundary_plan(intent, unsupported_reason or "runtime_orchestration")

        if intent.family == "intent_navigation":
            steps = _navigation_steps(intent)
        elif intent.family == "system_design_preview":
            steps = _system_design_candidate_steps(intent)
        elif intent.family == "bounded_profiler_guidance":
            steps = _profiler_guidance_steps(intent)
        else:
            steps = _candidate_steps(intent)

        status = SemanticPlanStatus.READY
        needs_clarification = False
        blocked_reason = ""
        if any(_step_missing_input(step) for step in steps):
            status = SemanticPlanStatus.NEEDS_CLARIFICATION
            needs_clarification = True
            blocked_reason = "structured intent is missing concrete builder inputs required for preview construction"

        project_changing = any(step.project_changing for step in steps)
        risk_flags = _risk_flags(steps)
        preview_id = f"semantic-preview:{intent.family}:{_stable_intent_suffix(intent)}"
        verification_step_templates = _verification_steps(steps, preview_hash="")
        preview_hash = _stable_preview_hash(intent.family, intent.version, steps, risk_flags, verification_step_templates)

        return SemanticPlan(
            status=status,
            family=intent.family,
            version=intent.version,
            steps=steps,
            preview_id=preview_id,
            preview_hash=preview_hash,
            risk_flags=risk_flags,
            requires_confirmation=project_changing and intent.confirmation_state != "confirmed",
            blocked_reason=blocked_reason,
            needs_clarification=needs_clarification,
            unsupported_capability=False,
            verification_steps=_verification_steps(steps, preview_hash),
            source_builder_refs=SEMANTIC_FAMILY_BUILDER_REFS[intent.family],
        )


def confirm_semantic_plan(preview: SemanticPlan, confirmation_state: str, submitted_preview_hash: str) -> SemanticPlan:
    """Return a confirmed plan only when the caller confirms the exact preview artifact."""

    _require_confirmation_state(confirmation_state)
    if confirmation_state != "confirmed":
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Semantic plan confirmation requires an explicit confirmed state.",
            details={"confirmation_state": confirmation_state, "required": "confirmed"},
        )
    if not submitted_preview_hash:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Semantic plan confirmation requires the submitted preview hash.",
            details={"submitted_preview_hash": submitted_preview_hash, "expected_preview_hash": preview.preview_hash},
        )
    if submitted_preview_hash != preview.preview_hash:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Submitted preview hash differs from the current semantic preview artifact; re-preview is required.",
            details={
                "status": "repreview_required",
                "submitted_preview_hash": submitted_preview_hash,
                "expected_preview_hash": preview.preview_hash,
                "executed": False,
                "verified": False,
            },
        )
    return replace(preview, requires_confirmation=False)


def _version_support_error(intent_version: str, manifest_loader: ManifestSchemaLoader) -> Mapping[str, Any] | None:
    if intent_version not in SUPPORTED_WWISE_VERSIONS:
        return {
            "reason": "unsupported-wwise-version",
            "version": intent_version,
            "supported_versions": list(SUPPORTED_WWISE_VERSIONS),
            "fallback_allowed": False,
        }
    try:
        manifest_loader.load_manifest(intent_version)
    except SemanticValidationError as exc:
        if exc.error_code is not SemanticErrorCode.UNSUPPORTED_WWISE_VERSION:
            raise
        return {
            "reason": "missing-version-manifest",
            "version": intent_version,
            "supported_versions": list(SUPPORTED_WWISE_VERSIONS),
            "fallback_allowed": False,
            "details": exc.as_dict(),
        }
    return None


def _blocked_version_plan(intent: SemanticIntent, version_error: Mapping[str, Any]) -> SemanticPlan:
    reason = str(version_error.get("reason") or "unsupported-wwise-version")
    return SemanticPlan(
        status=SemanticPlanStatus.BLOCKED,
        family=intent.family,
        version=intent.version,
        steps=(),
        preview_id="",
        preview_hash="",
        risk_flags=(),
        requires_confirmation=False,
        blocked_reason=f"{reason}; version={intent.version}; fallback_allowed=False",
        needs_clarification=False,
        unsupported_capability=False,
        verification_steps=(),
        source_builder_refs=SEMANTIC_FAMILY_BUILDER_REFS[intent.family],
        clarification=version_error,
    )


def _ambiguous_target_clarification(intent: SemanticIntent) -> Mapping[str, Any] | None:
    for target in cast(tuple[SemanticIntentTarget, ...], intent.targets):
        candidates = _target_candidate_details(target)
        ambiguous = target.metadata.get("ambiguous") is True or len(candidates) > 1
        if not ambiguous:
            continue
        return {
            "reason": str(target.metadata.get("ambiguity_reason") or target.metadata.get("reason") or "ambiguous-target-candidates"),
            "target": target.as_dict(),
            "candidates": candidates,
            "fallback_allowed": False,
        }
    return None


def _target_candidate_details(target: SemanticIntentTarget) -> list[Any]:
    value = target.metadata.get("candidate_targets", target.metadata.get("candidates", ()))
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return []


def _needs_target_clarification_plan(intent: SemanticIntent, clarification: Mapping[str, Any]) -> SemanticPlan:
    reason = str(clarification.get("reason") or "ambiguous-target-candidates")
    return SemanticPlan(
        status=SemanticPlanStatus.NEEDS_CLARIFICATION,
        family=intent.family,
        version=intent.version,
        steps=(),
        preview_id="",
        preview_hash="",
        risk_flags=("needs-target-clarification",),
        requires_confirmation=False,
        blocked_reason=f"{reason}; choose one candidate target before planning; fallback_allowed=False",
        needs_clarification=True,
        unsupported_capability=False,
        verification_steps=(),
        source_builder_refs=SEMANTIC_FAMILY_BUILDER_REFS[intent.family],
        clarification=clarification,
    )


def _unsupported_boundary_plan(intent: SemanticIntent, reason_key: str) -> SemanticPlan:
    reason = UNSUPPORTED_BOUNDARY_REASONS.get(reason_key, UNSUPPORTED_BOUNDARY_REASONS["runtime_orchestration"])
    alternative = UNSUPPORTED_BOUNDARY_ALTERNATIVES.get(reason_key, UNSUPPORTED_BOUNDARY_ALTERNATIVES["runtime_orchestration"])
    return SemanticPlan(
        status=SemanticPlanStatus.UNSUPPORTED,
        family="unsupported_runtime_boundary",
        version=intent.version,
        steps=(),
        preview_id="",
        preview_hash="",
        risk_flags=(),
        requires_confirmation=False,
        blocked_reason=f"{reason}; no project-changing steps or execution claims are produced; supported_alternative={alternative}",
        needs_clarification=False,
        unsupported_capability=True,
        verification_steps=(),
        source_builder_refs=(),
    )


def _unsupported_boundary_capability(intent: SemanticIntent) -> str:
    tokens = tuple(_structured_intent_tokens(intent))
    for reason_key, patterns in UNSUPPORTED_BOUNDARY_PATTERNS:
        if any(pattern in token for token in tokens for pattern in patterns):
            return reason_key
    return ""


def _structured_intent_tokens(intent: SemanticIntent) -> tuple[str, ...]:
    values: list[str] = [intent.family]
    values.extend(str(operation) for operation in intent.requested_operations)
    for target in cast(tuple[SemanticIntentTarget, ...], intent.targets):
        values.extend((target.kind, target.identifier, target.display_name))
        values.extend(_flatten_token_values(target.metadata))
    for constraint in cast(tuple[SemanticIntentConstraint, ...], intent.constraints):
        values.extend((constraint.field, constraint.operator, constraint.reason))
        values.extend(_flatten_token_values(constraint.value))
    return tuple(value.strip().lower().replace("-", "_") for value in values if value)


def _flatten_token_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        flattened: list[str] = []
        for key, item in value.items():
            flattened.append(str(key))
            flattened.extend(_flatten_token_values(item))
        return tuple(flattened)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        flattened = []
        for item in value:
            flattened.extend(_flatten_token_values(item))
        return tuple(flattened)
    if value is None:
        return ()
    return (str(value),)


def _navigation_steps(intent: SemanticIntent) -> tuple[SemanticPlanStep, ...]:
    target = _first_target(intent)
    return_fields = _return_fields(target, default=("id", "name", "path", "type"))
    source_kwargs = _query_source_kwargs(target)
    missing = [name for name, value in source_kwargs.items() if value is None]
    if len(source_kwargs) != 1 or missing:
        return (
            _missing_step(
                intent,
                step_id="intent-navigation-object-get",
                operation="object.get",
                builder_ref="wwise_waapi.builders.query.build_object_get_query",
                api="ak.wwise.core.object.get",
                missing_inputs=("exactly one query source target: type, path, object_id, search, or query",),
                read_only=True,
            ),
        )
    preview = build_object_get_query(
        **source_kwargs,
        where=tuple(QueryPredicate(field=constraint.field, operator=constraint.operator, value=constraint.value) for constraint in cast(tuple[SemanticIntentConstraint, ...], intent.constraints)),
        select=_metadata_sequence(target, "select"),
        take=_metadata_int(target, "take"),
        return_fields=return_fields,
        version=intent.version,
    )
    return (_step_from_preview(intent, "intent-navigation-object-get", "object.get", "wwise_waapi.builders.query.build_object_get_query", preview, target),)


def _candidate_steps(intent: SemanticIntent) -> tuple[SemanticPlanStep, ...]:
    operations = tuple(intent.requested_operations) or _default_operations(intent.family)
    return tuple(_candidate_step(intent, index, operation) for index, operation in enumerate(operations, start=1))


def _system_design_candidate_steps(intent: SemanticIntent) -> tuple[SemanticPlanStep, ...]:
    target = _first_target(intent)
    target_identity = target.as_dict() if target is not None else {}
    candidates = (
        ("system-design-discover-parent", "object.get", "wwise_waapi.builders.query.build_object_get_query", "ak.wwise.core.object.get", True, False),
        ("system-design-create-container", "object.create", "wwise_waapi.builders.object_mutation.build_object_mutation_preview", "ak.wwise.core.object.create", False, True),
        ("system-design-annotate-container", "setNotes", "wwise_waapi.builders.properties.build_set_notes_preview", "ak.wwise.core.object.setNotes", False, True),
        ("system-design-import-assets", "audio.import", "wwise_waapi.builders.imports.build_audio_import_preview", "ak.wwise.core.audio.import", False, True),
    )
    return tuple(
        _preview_shell_step(
            intent,
            step_id=step_id,
            operation=operation,
            builder_ref=builder_ref,
            api=api,
            read_only=read_only,
            project_changing=project_changing,
            target_identity=target_identity,
            inputs={
                "candidate_only": True,
                "confirmation_required": project_changing,
                "missing_structured_input": ["explicit parent identity", "object names/types", "asset file paths"] if project_changing else ["query source target"],
            },
        )
        for step_id, operation, builder_ref, api, read_only, project_changing in candidates
    )


def _profiler_guidance_steps(intent: SemanticIntent) -> tuple[SemanticPlanStep, ...]:
    uri = _profiler_uri(intent)
    builder_ref = "wwise_waapi.builders.profiler.extract_profiler_parameter_guidance"
    if not uri:
        return (
            _missing_step(
                intent,
                step_id="bounded-profiler-guidance",
                operation="profiler.guidance",
                builder_ref=builder_ref,
                api="",
                missing_inputs=("profiler/log WAAPI uri",),
                read_only=True,
            ),
        )
    guidance = extract_profiler_parameter_guidance(uri, version=intent.version).as_dict()
    return (
        _preview_shell_step(
            intent,
            step_id="bounded-profiler-guidance",
            operation="profiler.guidance",
            builder_ref=builder_ref,
            api=uri,
            read_only=True,
            project_changing=False,
            args_preview={"uri": uri},
            options_preview={},
            target_identity={"uri": uri},
            inputs={"guidance_preview": guidance},
        ),
    )


def _candidate_step(intent: SemanticIntent, index: int, operation: str) -> SemanticPlanStep:
    builder_ref, api, read_only, project_changing, missing = _candidate_metadata(intent.family, operation)
    target = _first_target(intent)
    return _preview_shell_step(
        intent,
        step_id=f"{intent.family}-{index}",
        operation=operation,
        builder_ref=builder_ref,
        api=api,
        read_only=read_only,
        project_changing=project_changing,
        target_identity=target.as_dict() if target is not None else {},
        inputs={"missing_structured_input": list(missing), "candidate_only": True},
    )


def _step_from_preview(
    intent: SemanticIntent,
    step_id: str,
    operation: str,
    builder_ref: str,
    preview: Any,
    target: SemanticIntentTarget | None,
) -> SemanticPlanStep:
    preview_dict = preview.as_dict()
    envelope = _mapping_value(preview_dict["envelope"])
    metadata = _mapping_value(envelope.get("metadata", {}))
    read_only = bool(metadata.get("read_only", not preview_dict.get("requires_destructive_gate", False)))
    project_changing = not read_only or bool(preview_dict.get("requires_destructive_gate", False))
    return _preview_shell_step(
        intent,
        step_id=step_id,
        operation=operation,
        builder_ref=builder_ref,
        api=str(envelope.get("uri", "")),
        args_preview=_mapping_value(envelope.get("args", {})),
        options_preview=_mapping_value(envelope.get("options", {})),
        target_identity=target.as_dict() if target is not None else _preview_target_identity(metadata),
        read_only=read_only,
        project_changing=project_changing,
        inputs={"builder_preview": preview_dict},
    )


def _preview_shell_step(
    intent: SemanticIntent,
    *,
    step_id: str,
    operation: str,
    builder_ref: str,
    api: str,
    read_only: bool,
    project_changing: bool,
    args_preview: Mapping[str, Any] | None = None,
    options_preview: Mapping[str, Any] | None = None,
    target_identity: Mapping[str, Any] | None = None,
    inputs: Mapping[str, Any] | None = None,
) -> SemanticPlanStep:
    payload = {
        "api": api,
        "args_preview": dict(args_preview or {}),
        "options_preview": dict(options_preview or {}),
        "target_identity": dict(target_identity or {}),
        "read_only": read_only,
        "project_changing": project_changing,
    }
    return SemanticPlanStep(
        step_id=step_id,
        operation=operation,
        family=intent.family,
        preview=SemanticPlanPreview(
            preview_id=f"{step_id}:preview",
            preview_hash=_stable_hash(payload),
            summary=f"{operation} preview via {builder_ref}",
            payload=payload,
        ),
        inputs=inputs or {},
        source_builder_ref=builder_ref,
        builder_ref=builder_ref,
        api=api,
        args_preview=args_preview or {},
        options_preview=options_preview or {},
        target_identity=target_identity or {},
        read_only=read_only,
        project_changing=project_changing,
    )


def _missing_step(
    intent: SemanticIntent,
    *,
    step_id: str,
    operation: str,
    builder_ref: str,
    api: str,
    missing_inputs: Sequence[str],
    read_only: bool,
) -> SemanticPlanStep:
    target = _first_target(intent)
    return _preview_shell_step(
        intent,
        step_id=step_id,
        operation=operation,
        builder_ref=builder_ref,
        api=api,
        read_only=read_only,
        project_changing=not read_only,
        target_identity=target.as_dict() if target is not None else {},
        inputs={"missing_structured_input": list(missing_inputs), "candidate_only": True},
    )


def _first_target(intent: SemanticIntent) -> SemanticIntentTarget | None:
    targets = cast(tuple[SemanticIntentTarget, ...], intent.targets)
    return targets[0] if targets else None


def _query_source_kwargs(target: SemanticIntentTarget | None) -> dict[str, Any]:
    if target is None:
        return {}
    key_by_kind = {
        "path": "path",
        "object_id": "object_id",
        "id": "object_id",
        "type": "type",
        "search": "search",
        "query": "query",
        "waql": "query",
    }
    key = key_by_kind.get(target.kind)
    if key is None:
        metadata_source = target.metadata.get("query_source")
        if isinstance(metadata_source, str):
            key = key_by_kind.get(metadata_source)
    return {key: target.identifier} if key is not None and target.identifier else {}


def _return_fields(target: SemanticIntentTarget | None, *, default: Sequence[str]) -> tuple[str, ...]:
    fields = _metadata_sequence(target, "return")
    return tuple(fields or default)


def _metadata_sequence(target: SemanticIntentTarget | None, key: str) -> tuple[str, ...]:
    if target is None:
        return ()
    value = target.metadata.get(key)
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    return ()


def _metadata_int(target: SemanticIntentTarget | None, key: str) -> int | None:
    if target is None:
        return None
    value = target.metadata.get(key)
    return value if isinstance(value, int) else None


def _default_operations(family: str) -> tuple[str, ...]:
    defaults = {
        "crud_authoring": ("object.create", "object.set", "setName", "setProperty"),
        "asset_import_workflow": ("audio.import", "audio.importTabDelimited"),
        "soundbank_workflow": ("getInclusions", "setInclusions", "generate"),
        "switch_assignment_workflow": ("getAssignments", "addAssignment", "removeAssignment"),
    }
    return defaults.get(family, ())


def _candidate_metadata(family: str, operation: str) -> tuple[str, str, bool, bool, tuple[str, ...]]:
    table = {
        "object.create": ("wwise_waapi.builders.object_mutation.build_object_mutation_preview", "ak.wwise.core.object.create", False, True, ("parent identity", "object type", "object name")),
        "object.set": ("wwise_waapi.builders.object_mutation.build_object_mutation_preview", "ak.wwise.core.object.set", False, True, ("resolved object identity", "field values")),
        "object.delete": ("wwise_waapi.builders.object_mutation.build_object_mutation_preview", "ak.wwise.core.object.delete", False, True, ("resolved object identity",)),
        "object.copy": ("wwise_waapi.builders.object_mutation.build_object_mutation_preview", "ak.wwise.core.object.copy", False, True, ("source object identity", "parent identity")),
        "object.move": ("wwise_waapi.builders.object_mutation.build_object_mutation_preview", "ak.wwise.core.object.move", False, True, ("source object identity", "parent identity")),
        "setName": ("wwise_waapi.builders.properties.build_set_name_preview", "ak.wwise.core.object.setName", False, True, ("resolved object identity", "new name")),
        "setNotes": ("wwise_waapi.builders.properties.build_set_notes_preview", "ak.wwise.core.object.setNotes", False, True, ("resolved object identity", "notes value")),
        "setProperty": ("wwise_waapi.builders.properties.build_set_property_preview", "ak.wwise.core.object.setProperty", False, True, ("resolved object identity", "property metadata", "property value")),
        "audio.import": ("wwise_waapi.builders.imports.build_audio_import_preview", "ak.wwise.core.audio.import", False, True, ("import items", "object paths", "audio file paths")),
        "audio.importTabDelimited": ("wwise_waapi.builders.imports.build_import_tab_delimited_preview", "ak.wwise.core.audio.importTabDelimited", False, True, ("import file or tab-delimited plan", "language", "import operation")),
        "getInclusions": ("wwise_waapi.builders.soundbank.build_get_inclusions_preview", "ak.wwise.core.soundbank.getInclusions", True, False, ("soundbank identity",)),
        "setInclusions": ("wwise_waapi.builders.soundbank.build_set_inclusions_preview", "ak.wwise.core.soundbank.setInclusions", False, True, ("soundbank identity", "inclusion rows", "operation")),
        "generate": ("wwise_waapi.builders.soundbank.build_generate_preview", "ak.wwise.core.soundbank.generate", False, True, ("soundbank generation request",)),
        "getAssignments": ("wwise_waapi.builders.switchcontainer.build_get_assignments_preview", "ak.wwise.core.switchContainer.getAssignments", True, False, ("switch container identity",)),
        "addAssignment": ("wwise_waapi.builders.switchcontainer.build_add_assignment_preview", "ak.wwise.core.switchContainer.addAssignment", False, True, ("switch container identity", "child identity", "state or switch identity", "existing assignments")),
        "removeAssignment": ("wwise_waapi.builders.switchcontainer.build_remove_assignment_preview", "ak.wwise.core.switchContainer.removeAssignment", False, True, ("switch container identity", "child identity", "state or switch identity", "existing assignments")),
    }
    if operation in table:
        return table[operation]
    module_ref = SEMANTIC_FAMILY_BUILDER_REFS[family][0]
    return (module_ref, "", False, True, ("supported operation-specific structured inputs",))


def _profiler_uri(intent: SemanticIntent) -> str:
    target = _first_target(intent)
    if target is not None and target.kind in {"uri", "api"} and target.identifier.startswith("ak."):
        return target.identifier
    constraints = cast(tuple[SemanticIntentConstraint, ...], intent.constraints)
    for constraint in constraints:
        if constraint.field in {"uri", "api"} and isinstance(constraint.value, str) and constraint.value.startswith("ak."):
            return constraint.value
    return ""


def _preview_target_identity(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    value = metadata.get("preview_target_identity") or metadata.get("identity_resolution")
    return value if isinstance(value, Mapping) else {}


def _step_missing_input(step: SemanticPlanStep) -> bool:
    missing = step.inputs.get("missing_structured_input")
    return isinstance(missing, Sequence) and not isinstance(missing, str) and len(missing) > 0


def _risk_flags(steps: Sequence[SemanticPlanStep]) -> tuple[str, ...]:
    flags: list[str] = []
    if all(step.read_only for step in steps):
        flags.append("read-only")
    if any(step.project_changing for step in steps):
        flags.append("project-changing")
    if any(_step_missing_input(step) for step in steps):
        flags.append("needs-structured-input")
    return tuple(flags)


def _verification_steps(steps: Sequence[SemanticPlanStep], preview_hash: str) -> tuple[SemanticPlanVerification, ...]:
    verifications: list[SemanticPlanVerification] = []
    for step in steps:
        if not step.api:
            continue
        kind = "readback" if step.read_only else "post-mutation-readback"
        verifications.append(
            SemanticPlanVerification(
                kind=kind,
                description=f"Verify {step.operation} preview for {step.api} before any live dispatch.",
                preview_hash=preview_hash,
                readback_plan={"uri": step.api, "args": step.args_preview, "options": step.options_preview},
            )
        )
    return tuple(verifications)


def _stable_intent_suffix(intent: SemanticIntent) -> str:
    return _stable_hash({"family": intent.family, "goal": intent.goal, "version": intent.version})[7:19]


def _stable_preview_hash(
    family: str,
    version: str,
    steps: Sequence[SemanticPlanStep],
    risk_flags: Sequence[str],
    verification_steps: Sequence[SemanticPlanVerification],
) -> str:
    return _stable_hash(
        {
            "version": version,
            "family": family,
            "steps": [_preview_artifact_step(step) for step in steps],
            "risk_flags": list(risk_flags),
            "verification_steps": [_preview_artifact_verification(step) for step in verification_steps],
        }
    )


def _preview_artifact_step(step: SemanticPlanStep) -> dict[str, Any]:
    preview = cast(SemanticPlanPreview | None, step.preview)
    preview_payload = preview.payload if preview is not None else {}
    return {
        "step_id": step.step_id,
        "operation": step.operation,
        "family": step.family,
        "builder_ref": step.builder_ref or step.source_builder_ref,
        "api": step.api,
        "args_preview": _json_safe_mapping(step.args_preview),
        "options_preview": _json_safe_mapping(step.options_preview),
        "target_identity": _json_safe_mapping(step.target_identity),
        "payload_preview": _json_safe_mapping(preview_payload),
        "read_only": step.read_only,
        "project_changing": step.project_changing,
    }


def _preview_artifact_verification(step: SemanticPlanVerification) -> dict[str, Any]:
    return {
        "kind": step.kind,
        "description": step.description,
        "readback_plan": _json_safe_mapping(step.readback_plan),
    }


def _stable_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(_json_safe_mapping(value), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _require_supported_family(family: str) -> None:
    if family not in SUPPORTED_SEMANTIC_FAMILIES:
        raise SemanticValidationError(
            SemanticErrorCode.UNSUPPORTED_BUILDER_FAMILY,
            f"Unsupported semantic intent family: {family!r}",
            details={"family": family, "supported": list(SUPPORTED_SEMANTIC_FAMILIES)},
        )


def _require_confirmation_state(confirmation_state: str) -> None:
    if confirmation_state not in SEMANTIC_CONFIRMATION_STATES:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"Unsupported semantic confirmation state: {confirmation_state!r}",
            details={"confirmation_state": confirmation_state, "supported": list(SEMANTIC_CONFIRMATION_STATES)},
        )


def _intent_target(value: SemanticIntentTarget | Mapping[str, Any]) -> SemanticIntentTarget:
    if isinstance(value, SemanticIntentTarget):
        return value
    return SemanticIntentTarget(
        kind=str(value["kind"]),
        identifier=str(value["identifier"]),
        display_name=str(value.get("display_name", "")),
        metadata=_mapping_value(value.get("metadata", {})),
    )


def _intent_constraint(value: SemanticIntentConstraint | Mapping[str, Any]) -> SemanticIntentConstraint:
    if isinstance(value, SemanticIntentConstraint):
        return value
    return SemanticIntentConstraint(
        field=str(value["field"]),
        operator=str(value["operator"]),
        value=value["value"],
        reason=str(value.get("reason", "")),
    )


def _plan_preview(value: SemanticPlanPreview | Mapping[str, Any]) -> SemanticPlanPreview:
    if isinstance(value, SemanticPlanPreview):
        return value
    return SemanticPlanPreview(
        preview_id=str(value["preview_id"]),
        preview_hash=str(value["preview_hash"]),
        summary=str(value.get("summary", "")),
        payload=_mapping_value(value.get("payload", {})),
    )


def _plan_verification(value: SemanticPlanVerification | Mapping[str, Any]) -> SemanticPlanVerification:
    if isinstance(value, SemanticPlanVerification):
        return value
    return SemanticPlanVerification(
        kind=str(value["kind"]),
        description=str(value["description"]),
        preview_hash=str(value.get("preview_hash", "")),
        readback_plan=_mapping_value(value.get("readback_plan", {})),
    )


def _plan_step(value: SemanticPlanStep | Mapping[str, Any]) -> SemanticPlanStep:
    if isinstance(value, SemanticPlanStep):
        return value
    return SemanticPlanStep(
        step_id=str(value["step_id"]),
        operation=str(value["operation"]),
        family=str(value["family"]),
        preview=value.get("preview"),
        inputs=_mapping_value(value.get("inputs", {})),
        source_builder_ref=str(value.get("source_builder_ref", "")),
        builder_ref=str(value.get("builder_ref", value.get("source_builder_ref", ""))),
        api=str(value.get("api", "")),
        args_preview=_mapping_value(value.get("args_preview", {})),
        options_preview=_mapping_value(value.get("options_preview", {})),
        target_identity=_mapping_value(value.get("target_identity", {})),
        read_only=bool(value.get("read_only", False)),
        project_changing=bool(value.get("project_changing", False)),
    )


def _mapping_value(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Semantic planner metadata fields must be mappings.",
            details={"received": type(value).__name__},
        )
    return value


def _json_safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe(item) for key, item in value.items()}


def _json_safe(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value
