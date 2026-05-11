"""Thin operator intent and policy decisions for WAAPI wrappers."""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .builders.common import SemanticValidationError
from .builders.query import MUTATING_WORDS as QUERY_MUTATING_WORDS
from .builders.query import build_object_get_query
from .config import SkillConfig
from .dispatcher import DEFAULT_TIMEOUT_SECONDS, DispatcherRequest, WwiseDispatcher
from .waql import WAQL_API_URI


OPERATOR_INTENT_FAMILIES = (
    "operator_read",
    "operator_waql",
    "operator_mutation_preview",
    "operator_mutation_confirmed",
    "compound_read_then_confirm",
    "research_explicit",
    "blocked_setup",
)

MUTATION_POLICIES = ("never", "preview_then_confirm", "allow_with_notice")
CONFIRMATION_STATES = ("unknown", "preview", "confirmed", "rejected")

READ_KEYWORDS = frozenset(
    {
        "get",
        "list",
        "read",
        "show",
        "find",
        "inspect",
        "query",
        "search",
        "status",
        "info",
    }
)
WAQL_KEYWORDS = ("waql", "from type", "from search", "from query", "select descendants", "where ")
MUTATION_KEYWORDS = frozenset(
    {
        "create",
        "delete",
        "destroy",
        "import",
        "move",
        "rename",
        "set",
        "update",
        "change",
        "assign",
    }
)
RESEARCH_WORDS = frozenset({"research", "documentation", "docs", "repository", "repo", "manual", "explanation", "comparison"})
RESEARCH_PHRASES = (
    "source review",
    "source code",
    "source docs",
    "source documentation",
    "docs comparison",
    "repository investigation",
    "implementation investigation",
    "investigate implementation",
)
COMPOUND_MARKERS = (" then ", " after ", " once ", " before ")
DEFAULT_READ_RETURN_FIELDS = ("id", "name", "type", "path")
GET_INFO_URI = "ak.wwise.core.getInfo"


@dataclass(slots=True, frozen=True)
class OperatorConfigSnapshot:
    """Public config fields used by the operator policy layer."""

    wwise_version: str | None
    waapi_host: str
    waapi_port: int | None
    project_modification_policy: str

    @classmethod
    def from_config(cls, config: SkillConfig) -> "OperatorConfigSnapshot":
        return cls(
            wwise_version=config.wwise_version,
            waapi_host=config.waapi_host,
            waapi_port=config.waapi_port,
            project_modification_policy=config.project_modification_policy,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "wwise_version": self.wwise_version,
            "waapi_host": self.waapi_host,
            "waapi_port": self.waapi_port,
            "project_modification_policy": self.project_modification_policy,
        }


@dataclass(slots=True, frozen=True)
class OperatorInputs:
    """Explicit wrapper-supplied request shape used before any execution."""

    prompt: str = ""
    waql: str | None = None
    api: str | None = None
    mutation_requested: bool | None = None
    read_before_mutation: bool = False
    confirmation_state: str = "unknown"
    connection_host: str | None = None
    connection_port: int | None = None
    connection_available: bool | None = None

    def __post_init__(self) -> None:
        if self.confirmation_state not in CONFIRMATION_STATES:
            raise ValueError(f"confirmation_state must be one of: {', '.join(CONFIRMATION_STATES)}")
        if self.connection_port is not None and (isinstance(self.connection_port, bool) or not isinstance(self.connection_port, int)):
            raise ValueError("connection_port must be an integer or None")


@dataclass(slots=True, frozen=True)
class OperatorPolicyDecision:
    """Deterministic policy outcome for a wrapper to consume."""

    intent_family: str
    setup_ready: bool
    live_waapi_attempt: bool
    live_waapi_required: bool
    research_allowed: bool
    mutation_allowed: bool
    mutation_preview: bool
    mutation_confirmed: bool
    mutation_confirmation_required: bool
    dispatcher_dry_run: bool
    dispatcher_allow_destructive: bool
    config: OperatorConfigSnapshot
    blockers: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    inputs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.intent_family not in OPERATOR_INTENT_FAMILIES:
            raise ValueError(f"intent_family must be one of: {', '.join(OPERATOR_INTENT_FAMILIES)}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent_family": self.intent_family,
            "setup_ready": self.setup_ready,
            "live_waapi_attempt": self.live_waapi_attempt,
            "live_waapi_required": self.live_waapi_required,
            "research_allowed": self.research_allowed,
            "mutation_allowed": self.mutation_allowed,
            "mutation_preview": self.mutation_preview,
            "mutation_confirmed": self.mutation_confirmed,
            "mutation_confirmation_required": self.mutation_confirmation_required,
            "dispatcher_dry_run": self.dispatcher_dry_run,
            "dispatcher_allow_destructive": self.dispatcher_allow_destructive,
            "config": self.config.as_dict(),
            "blockers": list(self.blockers),
            "reasons": list(self.reasons),
            "inputs": dict(self.inputs),
        }


@dataclass(slots=True, frozen=True)
class OperatorExecutionResult:
    """User-facing operator execution outcome plus machine evidence."""

    status: str
    summary: str
    policy: OperatorPolicyDecision
    evidence: Mapping[str, Any] = field(default_factory=dict)
    rows: tuple[Mapping[str, Any], ...] = ()
    blockers: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "policy": self.policy.as_dict(),
            "evidence": dict(self.evidence),
            "rows": [dict(row) for row in self.rows],
            "blockers": list(self.blockers),
        }


@dataclass(slots=True, frozen=True)
class OperatorStageRecord:
    """One compound operator stage artifact with isolated evidence."""

    stage_id: str
    status: str
    summary: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    rows: tuple[Mapping[str, Any], ...] = ()
    blockers: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "status": self.status,
            "summary": self.summary,
            "evidence": dict(self.evidence),
            "rows": [dict(row) for row in self.rows],
            "blockers": list(self.blockers),
        }


@dataclass(slots=True, frozen=True)
class OperatorCompoundStageResult:
    """Compound read-then-confirm staging result that never mutates by itself."""

    status: str
    summary: str
    policy: OperatorPolicyDecision
    stages: tuple[OperatorStageRecord, ...] = ()
    blockers: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "policy": self.policy.as_dict(),
            "stages": [stage.as_dict() for stage in self.stages],
            "blockers": list(self.blockers),
        }


def decide_operator_policy(
    prompt: str = "",
    *,
    config: SkillConfig | None = None,
    skill_root: str | Path | None = None,
    config_path: str | Path | None = None,
    waql: str | None = None,
    api: str | None = None,
    mutation_requested: bool | None = None,
    read_before_mutation: bool = False,
    confirmation_state: str = "unknown",
    connection_host: str | None = None,
    connection_port: int | None = None,
    connection_available: bool | None = None,
) -> OperatorPolicyDecision:
    """Classify one operator request and map persisted mutation policy.

    The function is deliberately deterministic: wrapper-provided shape fields win,
    prompt text is only checked for stable keywords, and no WAAPI call is made here.
    """

    loaded_config = _load_config(config, skill_root, config_path)
    inputs = OperatorInputs(
        prompt=prompt,
        waql=waql,
        api=api,
        mutation_requested=mutation_requested,
        read_before_mutation=read_before_mutation,
        confirmation_state=confirmation_state,
        connection_host=connection_host,
        connection_port=connection_port,
        connection_available=connection_available,
    )
    return decide_operator_policy_for_inputs(inputs, loaded_config)


def decide_operator_policy_for_inputs(inputs: OperatorInputs, config: SkillConfig) -> OperatorPolicyDecision:
    """Return a policy decision for already-normalized wrapper inputs."""

    snapshot = OperatorConfigSnapshot.from_config(config)
    setup_ready, setup_blockers = _setup_status(snapshot, inputs)
    shape = _shape(inputs)
    reason = shape.reason

    if shape.research:
        return _decision(
            "research_explicit",
            snapshot,
            setup_ready,
            inputs,
            research_allowed=True,
            reasons=(reason,),
        )

    if shape.live_required and not setup_ready:
        return _decision(
            "blocked_setup",
            snapshot,
            setup_ready,
            inputs,
            live_required=True,
            research_allowed=True,
            blockers=setup_blockers,
            reasons=(reason, "live WAAPI is blocked until public config and connection inputs are ready"),
        )

    if shape.compound:
        return _decision(
            "compound_read_then_confirm",
            snapshot,
            setup_ready,
            inputs,
            live_attempt=setup_ready,
            live_required=True,
            mutation_preview=True,
            mutation_confirmation_required=True,
            dispatcher_dry_run=True,
            reasons=(reason, "compound mutation must stage preview before confirmation"),
        )

    if shape.mutation:
        return _mutation_decision(snapshot, setup_ready, inputs, reason)

    if shape.waql:
        return _decision(
            "operator_waql",
            snapshot,
            setup_ready,
            inputs,
            live_attempt=setup_ready,
            live_required=True,
            reasons=(reason,),
        )

    return _decision(
        "operator_read",
        snapshot,
        setup_ready,
        inputs,
        live_attempt=setup_ready,
        live_required=True,
        reasons=(reason,),
    )


def execute_operator_read(
    prompt: str = "",
    *,
    config: SkillConfig | None = None,
    skill_root: str | Path | None = None,
    config_path: str | Path | None = None,
    waql: str | None = None,
    api: str | None = None,
    return_fields: Sequence[str] | None = None,
    dispatcher: WwiseDispatcher | None = None,
    waapi_client: Any | None = None,
    evidence_dir: str | Path | None = None,
    research_hook: Callable[[], Any] | None = None,
    connection_host: str | None = None,
    connection_port: int | None = None,
    connection_available: bool | None = None,
    probe_connection: bool = True,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> OperatorExecutionResult:
    """Execute a ready read-only or WAQL operator request through ``WwiseDispatcher``.

    ``research_hook`` exists only as a testable proof point: operator-first reads must
    not use repository/docs research as a substitute for live WAAPI execution.
    """

    loaded_config = _load_config(config, skill_root, config_path)
    inputs = OperatorInputs(
        prompt=prompt,
        waql=waql,
        api=api,
        connection_host=connection_host,
        connection_port=connection_port,
        connection_available=connection_available,
    )
    policy = decide_operator_policy_for_inputs(inputs, loaded_config)
    if policy.intent_family == "blocked_setup":
        return _blocked_execution(policy)
    if policy.intent_family not in {"operator_read", "operator_waql"}:
        return OperatorExecutionResult(
            "read_only_violation",
            "Request is not a read-only operator execution.",
            policy,
            evidence={"research_called": False, "dispatcher_called": False},
            blockers=("request is not classified as operator_read/operator_waql",),
        )

    fields = tuple(return_fields or DEFAULT_READ_RETURN_FIELDS)
    try:
        request = _read_dispatcher_request(prompt, waql=waql, api=api, return_fields=fields, version=policy.config.wwise_version or "")
    except SemanticValidationError as exc:
        return OperatorExecutionResult(
            "read_only_violation",
            exc.message,
            policy,
            evidence={"error_code": exc.error_code.value, "details": exc.details, "research_called": False, "dispatcher_called": False},
            blockers=(exc.message,),
        )
    except ValueError as exc:
        return OperatorExecutionResult(
            "read_only_violation",
            str(exc),
            policy,
            evidence={"research_called": False, "dispatcher_called": False},
            blockers=(str(exc),),
        )

    active_dispatcher = dispatcher or WwiseDispatcher(client=waapi_client)
    evidence: dict[str, Any] = {
        "research_called": False,
        "dispatcher_called": False,
        "dispatcher_request": _dispatcher_request_dict(request),
        "no_research_proof": "research_hook_not_invoked",
    }
    if research_hook is not None:
        evidence["research_hook_supplied"] = True

    if probe_connection and connection_available is not True:
        probe_result = active_dispatcher.dispatch(
            GET_INFO_URI,
            version=policy.config.wwise_version or "",
            timeout=timeout,
            evidence_dir=evidence_dir,
        )
        evidence["probe_result"] = probe_result
        if not probe_result.get("ok"):
            return OperatorExecutionResult(
                "blocked_setup",
                f"Live WAAPI probe failed: {probe_result.get('message') or probe_result.get('error_code')}",
                policy,
                evidence=evidence,
                blockers=(f"live WAAPI probe failed: {probe_result.get('error_code')}",),
            )

    dispatcher_result = active_dispatcher.dispatch(_request_with_runtime_options(request, timeout=timeout, evidence_dir=evidence_dir))
    evidence["dispatcher_called"] = True
    evidence["dispatcher_result"] = dispatcher_result
    evidence["dispatcher_evidence_path"] = dispatcher_result.get("evidence_path")
    if not dispatcher_result.get("ok"):
        return OperatorExecutionResult(
            "blocked_setup",
            f"Live WAAPI read failed: {dispatcher_result.get('message') or dispatcher_result.get('error_code')}",
            policy,
            evidence=evidence,
            blockers=(f"live WAAPI read failed: {dispatcher_result.get('error_code')}",),
        )

    rows = _result_rows(dispatcher_result.get("result"))
    summary = _summary_for_rows(rows, request.api)
    return OperatorExecutionResult("ok", summary, policy, evidence=evidence, rows=rows)


def execute_operator_compound_staging(
    prompt: str,
    *,
    config: SkillConfig | None = None,
    skill_root: str | Path | None = None,
    config_path: str | Path | None = None,
    dispatcher: WwiseDispatcher | None = None,
    waapi_client: Any | None = None,
    evidence_dir: str | Path | None = None,
    connection_host: str | None = None,
    connection_port: int | None = None,
    connection_available: bool | None = None,
    probe_connection: bool = True,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    read_evidence: Mapping[str, Any] | None = None,
    read_rows: Sequence[Mapping[str, Any]] | None = None,
    preview_evidence: Mapping[str, Any] | None = None,
    confirmation_state: str = "unknown",
) -> OperatorCompoundStageResult:
    """Stage a compound read-then-confirm request without executing mutation."""

    loaded_config = _load_config(config, skill_root, config_path)
    policy = decide_operator_policy_for_inputs(
        OperatorInputs(
            prompt=prompt,
            mutation_requested=True,
            read_before_mutation=True,
            confirmation_state=confirmation_state,
            connection_host=connection_host,
            connection_port=connection_port,
            connection_available=connection_available,
        ),
        loaded_config,
    )
    if policy.intent_family == "blocked_setup":
        stage = OperatorStageRecord(
            "read-1",
            "blocked",
            "Read stage is blocked until live WAAPI setup is ready.",
            evidence={"dispatcher_called": False, "mutation_preview_created": False},
            blockers=policy.blockers,
        )
        return OperatorCompoundStageResult("blocked", stage.summary, policy, stages=(stage,), blockers=policy.blockers)

    if read_evidence is None:
        read_result = execute_operator_read(
            _compound_read_prompt(prompt),
            config=loaded_config,
            dispatcher=dispatcher,
            waapi_client=waapi_client,
            evidence_dir=evidence_dir,
            connection_host=connection_host,
            connection_port=connection_port,
            connection_available=connection_available,
            probe_connection=probe_connection,
            timeout=timeout,
        )
        stage_status = "read_complete" if read_result.status == "ok" else "blocked"
        stage = OperatorStageRecord(
            "read-1",
            stage_status,
            read_result.summary,
            evidence={**dict(read_result.evidence), "mutation_preview_created": False, "mutation_dispatcher_called": False},
            rows=read_result.rows,
            blockers=read_result.blockers,
        )
        if read_result.status != "ok":
            return OperatorCompoundStageResult("blocked", read_result.summary, policy, stages=(stage,), blockers=read_result.blockers)
        return OperatorCompoundStageResult(
            "read_complete",
            "Read stage complete; mutation preview is intentionally deferred until this read evidence is carried forward.",
            policy,
            stages=(stage,),
        )

    rows = tuple(dict(row) for row in (read_rows or ()))
    target_identity = _stage_target_identity(rows)
    read_stage = OperatorStageRecord(
        "read-1",
        "read_complete",
        _summary_for_rows(rows, WAQL_API_URI),
        evidence=dict(read_evidence),
        rows=rows,
    )
    preview_stage = OperatorStageRecord(
        "preview-1",
        "preview_ready",
        "Mutation preview artifact is staged from prior read evidence; live mutation is not executed in this task.",
        evidence={
            "preview_ready": True,
            "read_stage_id": read_stage.stage_id,
            "candidate_count": len(rows),
            "target_identity": list(target_identity),
            "requires_confirmation": True,
            "dispatcher_called": False,
            "allow_destructive": False,
        },
    )
    if confirmation_state != "confirmed":
        confirm_stage = OperatorStageRecord(
            "confirm-1",
            "awaiting_confirmation",
            "Explicit confirmation is required before any mutation execution stage can run.",
            evidence={
                "preview_stage_id": preview_stage.stage_id,
                "confirmation_state": confirmation_state,
                "executed": False,
                "verified": False,
                "dispatcher_called": False,
            },
            blockers=("explicit confirmation state is required",),
        )
        return OperatorCompoundStageResult(
            "awaiting_confirmation",
            confirm_stage.summary,
            policy,
            stages=(read_stage, preview_stage, confirm_stage),
            blockers=confirm_stage.blockers,
        )

    if preview_evidence is not None:
        preview_identity = _evidence_target_identity(preview_evidence)
        if preview_identity != target_identity:
            repreview_stage = OperatorStageRecord(
                "preview-1",
                "blocked",
                "Preview target identity no longer matches read evidence; abort and re-preview before confirmation.",
                evidence={
                    "read_stage_id": read_stage.stage_id,
                    "expected_target_identity": list(target_identity),
                    "provided_target_identity": list(preview_identity),
                    "executed": False,
                    "verified": False,
                    "dispatcher_called": False,
                },
                blockers=("preview target identity must be revalidated before confirmation",),
            )
            return OperatorCompoundStageResult("blocked", repreview_stage.summary, policy, stages=(read_stage, repreview_stage), blockers=repreview_stage.blockers)

    execute_stage = OperatorStageRecord(
        "execute-1",
        "blocked",
        "Mutation execution is blocked in compound staging; a future confirmation turn must execute and verify separately.",
        evidence={
            "preview_stage_id": preview_stage.stage_id,
            "confirmation_state": confirmation_state,
            "executed": False,
            "verified": False,
            "dispatcher_called": False,
        },
        blockers=("compound staging does not execute mutation",),
    )
    return OperatorCompoundStageResult("blocked", execute_stage.summary, policy, stages=(read_stage, preview_stage, execute_stage), blockers=execute_stage.blockers)


def _blocked_execution(policy: OperatorPolicyDecision) -> OperatorExecutionResult:
    missing = "; ".join(policy.blockers) or "live WAAPI setup is incomplete"
    return OperatorExecutionResult(
        "blocked_setup",
        f"Live WAAPI execution is blocked: {missing}.",
        policy,
        evidence={"research_called": False, "dispatcher_called": False},
        blockers=policy.blockers,
    )


@dataclass(slots=True, frozen=True)
class _RequestShape:
    read: bool
    waql: bool
    mutation: bool
    compound: bool
    research: bool
    reason: str

    @property
    def live_required(self) -> bool:
        return self.read or self.waql or self.mutation or self.compound


def _load_config(config: SkillConfig | None, skill_root: str | Path | None, config_path: str | Path | None) -> SkillConfig:
    if config is not None:
        return config
    if skill_root is None:
        raise ValueError("skill_root is required when config is not supplied")
    path = Path(config_path) if config_path is not None else None
    return SkillConfig.load(Path(skill_root), path)


def _shape(inputs: OperatorInputs) -> _RequestShape:
    text = _normalized(inputs.prompt)
    words = frozenset(text.split())
    waql = _has_text(inputs.waql) or _api_is_waql(inputs.api) or any(keyword in text for keyword in WAQL_KEYWORDS)
    explicit_mutation = inputs.mutation_requested is True
    mutation = explicit_mutation or bool(words & MUTATION_KEYWORDS)
    research = _explicit_research_requested(text, words)
    read = inputs.mutation_requested is False or bool(words & READ_KEYWORDS) or _has_text(inputs.api) or waql or not mutation
    compound = mutation and (inputs.read_before_mutation or (read and any(marker in f" {text} " for marker in COMPOUND_MARKERS)))

    if research:
        reason = "explicit research/source/docs keyword requested"
    elif compound:
        reason = "request shape includes read-before-mutation sequencing"
    elif mutation:
        reason = "request shape includes mutation keyword or wrapper mutation flag"
    elif waql:
        reason = "request shape includes WAQL text or object.get WAQL API"
    else:
        reason = "request shape is read-only by keyword/default"
    return _RequestShape(read=read, waql=waql, mutation=mutation, compound=compound, research=research, reason=reason)


def _mutation_decision(
    snapshot: OperatorConfigSnapshot,
    setup_ready: bool,
    inputs: OperatorInputs,
    reason: str,
) -> OperatorPolicyDecision:
    policy = snapshot.project_modification_policy
    if policy not in MUTATION_POLICIES:
        raise ValueError(f"project_modification_policy must be one of: {', '.join(MUTATION_POLICIES)}")

    if inputs.confirmation_state == "rejected":
        return _decision(
            "operator_mutation_preview",
            snapshot,
            setup_ready,
            inputs,
            mutation_confirmation_required=True,
            dispatcher_dry_run=True,
            blockers=("mutation confirmation was rejected",),
            reasons=(reason,),
        )
    if policy == "never":
        return _decision(
            "operator_mutation_preview",
            snapshot,
            setup_ready,
            inputs,
            mutation_preview=True,
            mutation_confirmation_required=True,
            dispatcher_dry_run=True,
            blockers=("project_modification_policy=never blocks live mutation",),
            reasons=(reason, "preview-only behavior remains allowed"),
        )
    if inputs.confirmation_state == "preview":
        return _decision(
            "operator_mutation_preview",
            snapshot,
            setup_ready,
            inputs,
            mutation_preview=True,
            mutation_confirmation_required=True,
            dispatcher_dry_run=True,
            reasons=(reason, f"project_modification_policy={policy} requires preview before destructive execution"),
        )
    if inputs.confirmation_state == "confirmed":
        return _decision(
            "operator_mutation_confirmed",
            snapshot,
            setup_ready,
            inputs,
            live_attempt=setup_ready,
            live_required=True,
            mutation_allowed=True,
            mutation_confirmed=True,
            dispatcher_allow_destructive=True,
            reasons=(reason, "explicit confirmation state permits destructive dispatcher opt-in"),
        )
    if policy == "allow_with_notice" and inputs.mutation_requested is True:
        return _decision(
            "operator_mutation_confirmed",
            snapshot,
            setup_ready,
            inputs,
            live_attempt=setup_ready,
            live_required=True,
            mutation_allowed=True,
            mutation_confirmed=True,
            dispatcher_allow_destructive=True,
            reasons=(reason, "project_modification_policy=allow_with_notice permits explicit wrapper mutation intent"),
        )
    return _decision(
        "operator_mutation_preview",
        snapshot,
        setup_ready,
        inputs,
        mutation_confirmation_required=True,
        dispatcher_dry_run=True,
        blockers=("unknown mutation confirmation state is blocked",),
        reasons=(reason, "destructive permission is not inferred from prompt tone"),
    )


def _read_dispatcher_request(
    prompt: str,
    *,
    waql: str | None,
    api: str | None,
    return_fields: Sequence[str],
    version: str,
) -> DispatcherRequest:
    if waql is not None and _has_text(waql):
        _reject_mutating_operator_waql(waql)
        if api not in (None, "", WAQL_API_URI):
            raise ValueError("WAQL read execution only supports ak.wwise.core.object.get")
        return DispatcherRequest(
            api=WAQL_API_URI,
            version=version,
            args={"waql": waql.strip()},
            options={"return": list(return_fields)},
            dry_run=False,
            allow_destructive=False,
        )

    preview = build_object_get_query(**_read_query_kwargs(prompt), return_fields=return_fields, version=version)
    payload = preview.dispatch_payload()
    return DispatcherRequest(
        api=payload["uri"],
        version=version,
        args=payload["args"],
        options=payload["options"],
        dry_run=False,
        allow_destructive=False,
    )


def _read_query_kwargs(prompt: str) -> dict[str, Any]:
    descendant_query = _descendant_query_from_prompt(prompt)
    if descendant_query is not None:
        return descendant_query
    return {"type": _read_type_from_prompt(prompt), "select": _read_select_from_prompt(prompt)}


def _compound_read_prompt(prompt: str) -> str:
    text = f" {prompt} "
    lowered = text.lower()
    marker_positions = [lowered.find(marker) for marker in COMPOUND_MARKERS if lowered.find(marker) > 0]
    if not marker_positions:
        return prompt
    read_part = text[: min(marker_positions)].strip()
    return read_part or prompt


def _descendant_query_from_prompt(prompt: str) -> dict[str, Any] | None:
    text = _normalized(prompt)
    if "descendant" not in text and "descendants" not in text:
        return None

    hierarchy_path = _hierarchy_path_from_prompt(prompt)
    if hierarchy_path is None:
        return None

    query: dict[str, Any] = {"path": hierarchy_path, "select": "descendants"}
    prefix = _name_prefix_from_prompt(prompt)
    if prefix is not None:
        query["where"] = {"field": "name", "operator": ":", "value": f"{prefix}*"}
    return query


def _hierarchy_path_from_prompt(prompt: str) -> str | None:
    text = _normalized(prompt)
    if "master mixer hierarchy" in text:
        return r"\Master-Mixer Hierarchy"
    if "actor mixer hierarchy" in text:
        return r"\Actor-Mixer Hierarchy"
    return None


def _name_prefix_from_prompt(prompt: str) -> str | None:
    match = re.search(r"\bname\s+starts\s+with\s+([A-Za-z0-9_]+)", prompt, flags=re.IGNORECASE)
    if match is None:
        return None
    return match.group(1)


def _read_type_from_prompt(prompt: str) -> str:
    text = _normalized(prompt)
    if "bus" in text or "buses" in text:
        return "Bus"
    if "event" in text or "events" in text:
        return "Event"
    if "sound" in text or "sounds" in text or "audio source" in text:
        return "Sound"
    return "Object"


def _read_select_from_prompt(prompt: str) -> str | None:
    text = _normalized(prompt)
    if "descendant" in text or "descendants" in text:
        return "descendants"
    if "ancestor" in text or "ancestors" in text:
        return "ancestors"
    if "references to" in text:
        return "referencesTo"
    return None


def _reject_mutating_operator_waql(waql: str) -> None:
    found = tuple(word for word in QUERY_MUTATING_WORDS if re.search(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])", waql, re.IGNORECASE))
    if found:
        raise ValueError(f"Mutating WAQL is rejected by the read-only operator: {', '.join(found)}")


def _dispatcher_request_dict(request: DispatcherRequest) -> dict[str, Any]:
    return {
        "api": request.api,
        "version": request.version,
        "args": dict(request.args or {}),
        "options": dict(request.options or {}),
        "dry_run": request.dry_run,
        "allow_destructive": request.allow_destructive,
    }


def _request_with_runtime_options(request: DispatcherRequest, *, timeout: float, evidence_dir: str | Path | None) -> DispatcherRequest:
    return DispatcherRequest(
        api=request.api,
        version=request.version,
        args=request.args,
        options=request.options,
        timeout=timeout,
        dry_run=request.dry_run,
        allow_destructive=request.allow_destructive,
        evidence_dir=Path(evidence_dir) if evidence_dir is not None else None,
        topic_mode=request.topic_mode,
        live_behavior=request.live_behavior,
    )


def _result_rows(result: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(result, Mapping):
        rows = result.get("return") or result.get("objects") or result.get("items")
        if isinstance(rows, list):
            return tuple(row for row in rows if isinstance(row, Mapping))
        if all(key in result for key in ("id", "name")):
            return (result,)
    if isinstance(result, list):
        return tuple(row for row in result if isinstance(row, Mapping))
    return ()


def _summary_for_rows(rows: tuple[Mapping[str, Any], ...], api: str) -> str:
    if not rows:
        return f"Live WAAPI read via {api} returned no rows."
    names = [str(row.get("name")) for row in rows[:3] if row.get("name")]
    suffix = f": {', '.join(names)}" if names else "."
    return f"Live WAAPI read via {api} returned {len(rows)} row(s){suffix}"


def _stage_target_identity(rows: tuple[Mapping[str, Any], ...]) -> tuple[str, ...]:
    identities: list[str] = []
    for row in rows:
        value = row.get("id") or row.get("path") or row.get("name")
        if value is not None:
            identities.append(str(value))
    return tuple(identities)


def _evidence_target_identity(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    value = evidence.get("target_identity")
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    return ()


def _decision(
    intent_family: str,
    snapshot: OperatorConfigSnapshot,
    setup_ready: bool,
    inputs: OperatorInputs,
    *,
    live_attempt: bool = False,
    live_required: bool = False,
    research_allowed: bool = False,
    mutation_allowed: bool = False,
    mutation_preview: bool = False,
    mutation_confirmed: bool = False,
    mutation_confirmation_required: bool = False,
    dispatcher_dry_run: bool = False,
    dispatcher_allow_destructive: bool = False,
    blockers: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
) -> OperatorPolicyDecision:
    return OperatorPolicyDecision(
        intent_family=intent_family,
        setup_ready=setup_ready,
        live_waapi_attempt=live_attempt,
        live_waapi_required=live_required,
        research_allowed=research_allowed,
        mutation_allowed=mutation_allowed,
        mutation_preview=mutation_preview,
        mutation_confirmed=mutation_confirmed,
        mutation_confirmation_required=mutation_confirmation_required,
        dispatcher_dry_run=dispatcher_dry_run,
        dispatcher_allow_destructive=dispatcher_allow_destructive,
        config=snapshot,
        blockers=blockers,
        reasons=reasons,
        inputs=_input_snapshot(inputs),
    )


def _setup_status(snapshot: OperatorConfigSnapshot, inputs: OperatorInputs) -> tuple[bool, tuple[str, ...]]:
    blockers: list[str] = []
    host = inputs.connection_host or snapshot.waapi_host
    port = inputs.connection_port if inputs.connection_port is not None else snapshot.waapi_port
    if not _has_text(snapshot.wwise_version):
        blockers.append("wwise_version is not configured")
    if not _has_text(host):
        blockers.append("waapi_host is not configured")
    if port is None:
        blockers.append("waapi_port is not configured")
    if inputs.connection_available is False:
        blockers.append("live WAAPI connection is unavailable")
    return not blockers, tuple(blockers)


def _input_snapshot(inputs: OperatorInputs) -> dict[str, Any]:
    return {
        "prompt": inputs.prompt,
        "waql_supplied": _has_text(inputs.waql),
        "api": inputs.api,
        "mutation_requested": inputs.mutation_requested,
        "read_before_mutation": inputs.read_before_mutation,
        "confirmation_state": inputs.confirmation_state,
        "connection_host": inputs.connection_host,
        "connection_port": inputs.connection_port,
        "connection_available": inputs.connection_available,
    }


def _api_is_waql(api: str | None) -> bool:
    return api == "ak.wwise.core.object.get"


def _explicit_research_requested(text: str, words: frozenset[str]) -> bool:
    if words & RESEARCH_WORDS:
        return True
    return any(phrase in text for phrase in RESEARCH_PHRASES)


def _has_text(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalized(text: str) -> str:
    return " ".join(text.lower().replace("_", " ").replace("-", " ").split())


__all__ = [
    "OPERATOR_INTENT_FAMILIES",
    "OperatorConfigSnapshot",
    "OperatorInputs",
    "OperatorPolicyDecision",
    "OperatorExecutionResult",
    "OperatorStageRecord",
    "OperatorCompoundStageResult",
    "decide_operator_policy",
    "decide_operator_policy_for_inputs",
    "execute_operator_read",
    "execute_operator_compound_staging",
]
