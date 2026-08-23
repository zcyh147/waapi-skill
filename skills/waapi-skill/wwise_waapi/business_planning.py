"""Deterministic planning kernel for closed Business Declaration Adapters.

Operation-specific Adapters expand declarations into effects and materialize
the final closed operation request.  This kernel owns dependency ordering,
batch layout, strict bounds, canonical request validation, verifier aggregation,
and the readable/detail Preview split.
"""

from __future__ import annotations

import heapq
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .business_declaration_state import (
    BusinessDeclarationSession,
    BusinessPreview,
)
from .business_declarations import BusinessDeclarationError, business_repair
from .canonical import canonical_json_bytes, canonical_sha256
from .operation_registry import OperationContractError, parse_operation_request


BUSINESS_EFFECT_CONTRACT = "waapi-skill.business-effect/v1"
BUSINESS_BATCH_CONTRACT = "waapi-skill.business-batch/v1"
COMPILED_BUSINESS_PLAN_CONTRACT = "waapi-skill.compiled-business-plan/v1"

MAX_BUSINESS_EFFECTS = 4_096
MAX_BUSINESS_EFFECT_DEPENDENCIES = 256
MAX_BUSINESS_EFFECT_BYTES = 128 * 1024
MAX_BUSINESS_PLAN_BYTES = 1024 * 1024
MAX_BUSINESS_BATCHES = 4_096

_PLAN_TOKEN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,255}$")


@dataclass(frozen=True, slots=True)
class BusinessEffect:
    effect_id: str
    declaration_id: str
    depends_on: tuple[str, ...]
    batch_key: str
    native_fragment: Mapping[str, Any]
    verifier_expectation: Mapping[str, Any]
    readable_lines: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        effect_id: str,
        declaration_id: str,
        depends_on: Sequence[str] = (),
        batch_key: str,
        native_fragment: Mapping[str, Any],
        verifier_expectation: Mapping[str, Any],
        readable_lines: Sequence[str],
    ) -> "BusinessEffect":
        normalized_id = _token(effect_id, field="effect_id")
        normalized_declaration = _token(
            declaration_id, field="declaration_id"
        )
        normalized_batch = _token(batch_key, field="batch_key")
        if (
            not isinstance(depends_on, Sequence)
            or isinstance(depends_on, (str, bytes, bytearray))
            or len(depends_on) > MAX_BUSINESS_EFFECT_DEPENDENCIES
        ):
            raise ValueError("effect dependencies are invalid or exceed their limit")
        dependencies = tuple(_token(value, field="depends_on") for value in depends_on)
        if len(dependencies) != len(set(dependencies)) or normalized_id in dependencies:
            raise ValueError("effect dependencies must be unique and cannot contain self")
        fragment = _strict_json_object(native_fragment, label="native fragment")
        verifier = _strict_json_object(
            verifier_expectation, label="verifier expectation"
        )
        if (
            not isinstance(readable_lines, Sequence)
            or isinstance(readable_lines, (str, bytes, bytearray))
            or not readable_lines
        ):
            raise ValueError("effect readable lines must be a non-empty array")
        lines = tuple(_readable_line(value) for value in readable_lines)
        effect = cls(
            effect_id=normalized_id,
            declaration_id=normalized_declaration,
            depends_on=dependencies,
            batch_key=normalized_batch,
            native_fragment=fragment,
            verifier_expectation=verifier,
            readable_lines=lines,
        )
        if len(canonical_json_bytes(effect.as_dict())) > MAX_BUSINESS_EFFECT_BYTES:
            raise ValueError("business effect exceeds its fixed byte limit")
        return effect

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": BUSINESS_EFFECT_CONTRACT,
            "effect_id": self.effect_id,
            "declaration_id": self.declaration_id,
            "depends_on": list(self.depends_on),
            "batch_key": self.batch_key,
            "native_fragment": dict(self.native_fragment),
            "verifier_expectation": dict(self.verifier_expectation),
            "readable_lines": list(self.readable_lines),
        }


@dataclass(frozen=True, slots=True)
class BusinessBatch:
    batch_key: str
    effect_ids: tuple[str, ...]
    native_fragments: tuple[Mapping[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": BUSINESS_BATCH_CONTRACT,
            "batch_key": self.batch_key,
            "effect_ids": list(self.effect_ids),
            "native_fragments": [dict(row) for row in self.native_fragments],
        }


@dataclass(frozen=True, slots=True)
class CompiledBusinessPlan:
    operation: str
    version: str
    source_revision: int
    ordered_effect_ids: tuple[str, ...]
    batches: tuple[BusinessBatch, ...]
    request: Mapping[str, Any]
    request_digest: str
    verifier_expectations: tuple[Mapping[str, Any], ...]
    preview: BusinessPreview

    def as_dict(self, *, detail: bool = False) -> dict[str, Any]:
        payload = {
            "contract": COMPILED_BUSINESS_PLAN_CONTRACT,
            "operation": self.operation,
            "version": self.version,
            "source_revision": self.source_revision,
            "ordered_effect_ids": list(self.ordered_effect_ids),
            "batch_count": len(self.batches),
            "request_digest": self.request_digest,
            "preview": (
                self.preview.as_dict()
                if detail
                else self.preview.readable_projection()
            ),
        }
        if detail:
            payload.update(
                {
                    "batches": [batch.as_dict() for batch in self.batches],
                    "request": dict(self.request),
                    "verifier_expectations": [
                        dict(row) for row in self.verifier_expectations
                    ],
                }
            )
        return payload


MaterializePlan = Callable[[Sequence[BusinessBatch]], Mapping[str, Any]]


def compile_business_plan(
    session: BusinessDeclarationSession,
    *,
    operation: str,
    effects: Sequence[BusinessEffect],
    materialize: MaterializePlan,
) -> CompiledBusinessPlan:
    """Compile one complete, exact-revision business plan without mutation."""

    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    normalized_operation = _token(operation, field="operation")
    if not session.declarations or session.revision < 1:
        raise business_repair(
            "BUSINESS_DECLARATION_INCOMPLETE",
            field="declarations",
            missing_fields=("business_declaration",),
            action="complete at least one declaration before Preview",
        )
    if (
        not isinstance(effects, Sequence)
        or isinstance(effects, (str, bytes, bytearray))
        or not effects
        or len(effects) > MAX_BUSINESS_EFFECTS
        or any(not isinstance(effect, BusinessEffect) for effect in effects)
    ):
        raise business_repair(
            "BUSINESS_PLAN_EFFECTS_INVALID",
            field="effects",
            action="expand declarations into one bounded closed effect graph",
        )
    if not callable(materialize):
        raise TypeError("materialize must be callable")
    effect_rows = tuple(effects)
    by_id = {row.effect_id: row for row in effect_rows}
    if len(by_id) != len(effect_rows):
        raise business_repair(
            "BUSINESS_PLAN_EFFECT_ID_CONFLICT",
            field="effect_id",
            action="issue one unique Gateway-owned effect id per plan node",
        )
    declaration_ids = {row.declaration_id for row in session.declarations}
    unknown_declarations = sorted(
        {row.declaration_id for row in effect_rows} - declaration_ids
    )
    if unknown_declarations:
        raise business_repair(
            "BUSINESS_PLAN_DECLARATION_MISSING",
            field="declaration_id",
            missing_declarations=unknown_declarations,
            action="expand only declarations in the current task revision",
        )
    missing_dependencies = sorted(
        {
            dependency
            for row in effect_rows
            for dependency in row.depends_on
            if dependency not in by_id
        }
    )
    if missing_dependencies:
        raise business_repair(
            "BUSINESS_PLAN_DEPENDENCY_MISSING",
            field="depends_on",
            missing_dependencies=missing_dependencies,
            action="supply every Gateway-owned prerequisite effect",
        )
    ordered = _topological_order(effect_rows)
    batches = _layout_batches(ordered)
    try:
        raw_request = materialize(batches)
    except BusinessDeclarationError:
        raise
    except Exception as exc:
        raise business_repair(
            "BUSINESS_PLAN_MATERIALIZATION_FAILED",
            field="native_request",
            action="repair the closed Adapter instead of authoring native parameters",
        ) from exc
    if not isinstance(raw_request, Mapping):
        raise business_repair(
            "BUSINESS_PLAN_REQUEST_INVALID",
            field="native_request",
            action="repair the closed Adapter's canonical request materializer",
        )
    if (
        raw_request.get("operation") != normalized_operation
        or raw_request.get("version") != session.context.wwise_version
    ):
        raise business_repair(
            "BUSINESS_PLAN_REQUEST_MISMATCH",
            field="native_request",
            action="materialize the current operation and exact Wwise version",
        )
    try:
        request = parse_operation_request(
            raw_request,
            expected_version=session.context.wwise_version,
        ).as_dict()
    except OperationContractError as exc:
        raise business_repair(
            "BUSINESS_PLAN_REQUEST_INVALID",
            field="native_request",
            cause_error_code=exc.error_code,
            action="repair the closed Adapter's canonical request materializer",
        ) from exc
    request_digest = canonical_sha256(request)
    verifier_expectations = tuple(
        dict(row.verifier_expectation) for row in ordered
    )
    detail = {
        "contract": COMPILED_BUSINESS_PLAN_CONTRACT,
        "ordered_effect_ids": [row.effect_id for row in ordered],
        "batches": [batch.as_dict() for batch in batches],
        "native_request": request,
        "native_request_digest": request_digest,
        "verifier_expectations": [dict(row) for row in verifier_expectations],
    }
    if len(canonical_json_bytes(detail)) > MAX_BUSINESS_PLAN_BYTES:
        raise business_repair(
            "BUSINESS_PLAN_LIMIT_EXCEEDED",
            field="plan",
            action="split the task into bounded business declaration batches",
        )
    preview = BusinessPreview.create(
        source_revision=session.revision,
        readable_lines=tuple(
            line for row in ordered for line in row.readable_lines
        ),
        detail=detail,
    )
    return CompiledBusinessPlan(
        operation=normalized_operation,
        version=session.context.wwise_version,
        source_revision=session.revision,
        ordered_effect_ids=tuple(row.effect_id for row in ordered),
        batches=batches,
        request=request,
        request_digest=request_digest,
        verifier_expectations=verifier_expectations,
        preview=preview,
    )


def _topological_order(
    effects: Sequence[BusinessEffect],
) -> tuple[BusinessEffect, ...]:
    by_id = {row.effect_id: row for row in effects}
    incoming = {row.effect_id: len(row.depends_on) for row in effects}
    dependents: dict[str, list[str]] = {row.effect_id: [] for row in effects}
    for row in effects:
        for dependency in row.depends_on:
            dependents[dependency].append(row.effect_id)
    ready = [effect_id for effect_id, count in incoming.items() if count == 0]
    heapq.heapify(ready)
    ordered: list[BusinessEffect] = []
    while ready:
        effect_id = heapq.heappop(ready)
        ordered.append(by_id[effect_id])
        for dependent in sorted(dependents[effect_id]):
            incoming[dependent] -= 1
            if incoming[dependent] == 0:
                heapq.heappush(ready, dependent)
    if len(ordered) != len(effects):
        candidates = sorted(
            effect_id for effect_id, count in incoming.items() if count > 0
        )
        raise business_repair(
            "BUSINESS_PLAN_DEPENDENCY_CYCLE",
            field="depends_on",
            cycle_candidates=candidates,
            action="repair the Gateway-owned dependency graph",
        )
    return tuple(ordered)


def _layout_batches(
    ordered: Sequence[BusinessEffect],
) -> tuple[BusinessBatch, ...]:
    batches: list[BusinessBatch] = []
    current: list[BusinessEffect] = []
    current_key: str | None = None
    for effect in ordered:
        if current and effect.batch_key != current_key:
            batches.append(_batch(current_key, current))
            current = []
        current_key = effect.batch_key
        current.append(effect)
    if current:
        batches.append(_batch(current_key, current))
    if len(batches) > MAX_BUSINESS_BATCHES:
        raise business_repair(
            "BUSINESS_PLAN_BATCH_LIMIT_EXCEEDED",
            field="batches",
            action="split the task into bounded business declaration batches",
        )
    return tuple(batches)


def _batch(
    batch_key: str | None,
    effects: Sequence[BusinessEffect],
) -> BusinessBatch:
    assert batch_key is not None
    return BusinessBatch(
        batch_key=batch_key,
        effect_ids=tuple(row.effect_id for row in effects),
        native_fragments=tuple(dict(row.native_fragment) for row in effects),
    )


def _token(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _PLAN_TOKEN.fullmatch(value):
        raise ValueError(f"{field} must be one bounded plan token")
    return value


def _readable_line(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > 8 * 1024
        or (":" not in value and "：" not in value)
    ):
        raise ValueError("readable Preview lines must use bounded field: value form")
    return value


def _strict_json_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    try:
        canonical_json_bytes(value)
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise ValueError(f"{label} must contain strict JSON") from exc
    return dict(value)


__all__ = [
    "BUSINESS_BATCH_CONTRACT",
    "BUSINESS_EFFECT_CONTRACT",
    "COMPILED_BUSINESS_PLAN_CONTRACT",
    "BusinessBatch",
    "BusinessEffect",
    "CompiledBusinessPlan",
    "compile_business_plan",
]
