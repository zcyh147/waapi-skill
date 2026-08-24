"""Deterministic planning kernel for closed Business Declaration Adapters.

Operation-specific Adapters expand declarations into effects and materialize
the final closed operation request.  This kernel owns dependency ordering,
batch layout, strict bounds, canonical request validation, verifier aggregation,
and the readable/detail Preview split.
"""

from __future__ import annotations

import heapq
import math
import re
import shlex
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .business_declaration_state import (
    BusinessDeclarationSession,
    BusinessPreview,
)
from .business_declarations import BusinessDeclarationError, business_repair
from .canonical import canonical_json_bytes, canonical_sha256, strict_json_copy
from .operation_registry import OperationContractError, parse_operation_request
from .operation_import import (
    ImportContractError,
    regular_file_proof,
    verify_regular_file_proof,
)
from .platform_commands import (
    WINDOWS_MODEL_COMMAND_FAMILY,
    WINDOWS_POWERSHELL_ENCODED_FAMILY,
    decode_windows_model_argv,
    decode_windows_powershell_argv,
)


BUSINESS_EFFECT_CONTRACT = "waapi-skill.business-effect/v1"
BUSINESS_BATCH_CONTRACT = "waapi-skill.business-batch/v1"
COMPILED_BUSINESS_PLAN_CONTRACT = "waapi-skill.compiled-business-plan/v1"

MAX_BUSINESS_EFFECTS = 4_096
MAX_BUSINESS_EFFECT_DEPENDENCIES = 256
MAX_BUSINESS_EFFECT_BYTES = 128 * 1024
MAX_BUSINESS_PLAN_BYTES = 1024 * 1024
MAX_BUSINESS_BATCHES = 4_096
MAX_BUSINESS_FILES = 2_048
MAX_BUSINESS_FILE_BYTES = 8 * 1024 * 1024 * 1024
MAX_BUSINESS_TOTAL_FILE_BYTES = 64 * 1024 * 1024 * 1024
MAX_BUSINESS_PLANNING_SECONDS = 30.0
MAX_BUSINESS_CONTINUATION_BYTES = 64 * 1024

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
class BusinessFileEvidence:
    path: str
    size_bytes: int
    sha256: str
    mtime_ns: int | None = None
    device: int | None = None
    inode: int | None = None

    @classmethod
    def create(
        cls,
        *,
        path: str,
        size_bytes: int,
        sha256: str,
        mtime_ns: int | None = None,
        device: int | None = None,
        inode: int | None = None,
    ) -> "BusinessFileEvidence":
        if not isinstance(path, str) or not path or path != path.strip():
            raise ValueError("file evidence path must be non-empty text")
        if (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
        ):
            raise ValueError("file evidence size must be non-negative")
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("file evidence digest must be a lowercase SHA-256")
        for name, value in (
            ("mtime_ns", mtime_ns),
            ("device", device),
            ("inode", inode),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"file evidence {name} must be non-negative")
        return cls(
            path=path,
            size_bytes=size_bytes,
            sha256=sha256,
            mtime_ns=mtime_ns,
            device=device,
            inode=inode,
        )

    @classmethod
    def from_path(cls, path: str) -> "BusinessFileEvidence":
        proof = regular_file_proof(path, field="business file evidence")
        return cls.create(
            path=str(proof["path"]),
            size_bytes=int(proof["size"]),
            sha256=str(proof["sha256"]),
            mtime_ns=int(proof["mtime_ns"]),
            device=int(proof["device"]),
            inode=int(proof["inode"]),
        )

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }
        if self.mtime_ns is not None:
            payload.update(
                {
                    "mtime_ns": self.mtime_ns,
                    "device": self.device,
                    "inode": self.inode,
                }
            )
        return payload

    def as_import_proof(self) -> dict[str, Any]:
        if self.mtime_ns is None or self.device is None or self.inode is None:
            raise ValueError("matching request files require complete immutable evidence")
        return {
            "path": self.path,
            "size": self.size_bytes,
            "sha256": self.sha256,
            "mtime_ns": self.mtime_ns,
            "device": self.device,
            "inode": self.inode,
        }


@dataclass(frozen=True, slots=True)
class BusinessPlanningDeadline:
    started_at: float
    expires_at: float
    draft_revision: int
    clock: Callable[[], float]

    @classmethod
    def create(
        cls,
        *,
        draft_revision: int,
        clock: Callable[[], float],
    ) -> "BusinessPlanningDeadline":
        started_at = clock()
        if not isinstance(started_at, (int, float)) or not math.isfinite(started_at):
            raise ValueError("planning clock must return a finite number")
        return cls(
            started_at=float(started_at),
            expires_at=float(started_at) + MAX_BUSINESS_PLANNING_SECONDS,
            draft_revision=draft_revision,
            clock=clock,
        )

    def checkpoint(self) -> None:
        observed = self.clock()
        if (
            not isinstance(observed, (int, float))
            or not math.isfinite(observed)
            or observed < self.started_at
            or observed > self.expires_at
        ):
            raise business_repair(
                "BUSINESS_PLANNING_TIMEOUT",
                field="plan",
                draft_revision=self.draft_revision,
                timeout_seconds=MAX_BUSINESS_PLANNING_SECONDS,
                action="stop the Adapter and retry from fresh live evidence",
            )


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
    continuation: Mapping[str, Any]

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
                    "continuation": dict(self.continuation),
                }
            )
        return payload


@dataclass(frozen=True, slots=True)
class PlannedBusinessRequest:
    """Canonical request planning result before any public continuation exists."""

    operation: str
    version: str
    source_revision: int
    ordered_effect_ids: tuple[str, ...]
    batches: tuple[BusinessBatch, ...]
    request: Mapping[str, Any]
    request_digest: str
    verifier_expectations: tuple[Mapping[str, Any], ...]
    file_evidence: tuple[BusinessFileEvidence, ...]
    readable_lines: tuple[str, ...]
    deadline: BusinessPlanningDeadline


MaterializePlan = Callable[
    [Sequence[BusinessBatch], BusinessPlanningDeadline],
    Mapping[str, Any],
]
BuildContinuation = Callable[
    [Mapping[str, Any], str, BusinessPlanningDeadline],
    Mapping[str, Any],
]


def compile_business_plan(
    session: BusinessDeclarationSession,
    *,
    operation: str,
    effects: Sequence[BusinessEffect],
    materialize: MaterializePlan,
    build_continuation: BuildContinuation,
    file_evidence: Sequence[BusinessFileEvidence],
    clock: Callable[[], float] = time.monotonic,
) -> CompiledBusinessPlan:
    """Compile one complete, exact-revision business plan without mutation."""

    planned = plan_business_request(
        session,
        operation=operation,
        effects=effects,
        materialize=materialize,
        file_evidence=file_evidence,
        clock=clock,
    )
    deadline = planned.deadline
    if not callable(build_continuation):
        raise TypeError("build_continuation must be callable")
    try:
        raw_continuation = build_continuation(
            planned.request,
            planned.request_digest,
            deadline,
        )
        continuation = _validate_continuation(raw_continuation)
    except BusinessDeclarationError:
        raise
    except Exception as exc:
        raise business_repair(
            "BUSINESS_CONTINUATION_INVALID",
            field="continuation",
            draft_revision=session.revision,
            action="repair the Gateway-owned single continuation builder",
        ) from exc
    detail = {
        "contract": COMPILED_BUSINESS_PLAN_CONTRACT,
        "ordered_effect_ids": list(planned.ordered_effect_ids),
        "batches": [batch.as_dict() for batch in planned.batches],
        "native_request": planned.request,
        "native_request_digest": planned.request_digest,
        "verifier_expectations": [
            dict(row) for row in planned.verifier_expectations
        ],
        "file_evidence": [row.as_dict() for row in planned.file_evidence],
        "continuation": continuation,
    }
    if len(canonical_json_bytes(detail)) > MAX_BUSINESS_PLAN_BYTES:
        raise business_repair(
            "BUSINESS_PLAN_LIMIT_EXCEEDED",
            field="plan",
            draft_revision=session.revision,
            action="split the task into bounded business declaration batches",
        )
    try:
        preview = BusinessPreview.create(
            source_revision=session.revision,
            readable_lines=planned.readable_lines,
            detail=detail,
        )
    except ValueError as exc:
        raise business_repair(
            "BUSINESS_PLAN_LIMIT_EXCEEDED",
            field="preview",
            draft_revision=session.revision,
            action="split the task into bounded business declaration batches",
        ) from exc
    deadline.checkpoint()
    return CompiledBusinessPlan(
        operation=planned.operation,
        version=planned.version,
        source_revision=planned.source_revision,
        ordered_effect_ids=planned.ordered_effect_ids,
        batches=planned.batches,
        request=planned.request,
        request_digest=planned.request_digest,
        verifier_expectations=planned.verifier_expectations,
        preview=preview,
        continuation=continuation,
    )


def plan_business_request(
    session: BusinessDeclarationSession,
    *,
    operation: str,
    effects: Sequence[BusinessEffect],
    materialize: MaterializePlan,
    file_evidence: Sequence[BusinessFileEvidence],
    verify_file_evidence: bool = True,
    clock: Callable[[], float] = time.monotonic,
) -> PlannedBusinessRequest:
    """Plan and validate one request without manufacturing a continuation."""

    if not isinstance(session, BusinessDeclarationSession):
        raise TypeError("session must be BusinessDeclarationSession")
    if not callable(clock):
        raise TypeError("clock must be callable")
    deadline = BusinessPlanningDeadline.create(
        draft_revision=session.revision,
        clock=clock,
    )
    deadline.checkpoint()
    normalized_operation = _token(operation, field="operation")
    if not session.declarations or session.revision < 1:
        raise business_repair(
            "BUSINESS_DECLARATION_INCOMPLETE",
            field="declarations",
            draft_revision=session.revision,
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
            draft_revision=session.revision,
            action="expand declarations into one bounded closed effect graph",
        )
    if not callable(materialize):
        raise TypeError("materialize must be callable")
    if not isinstance(verify_file_evidence, bool):
        raise TypeError("verify_file_evidence must be a boolean")
    normalized_files = _validate_file_evidence(
        file_evidence,
        draft_revision=session.revision,
    )
    effect_rows = tuple(effects)
    by_id = {row.effect_id: row for row in effect_rows}
    if len(by_id) != len(effect_rows):
        raise business_repair(
            "BUSINESS_PLAN_EFFECT_ID_CONFLICT",
            field="effect_id",
            draft_revision=session.revision,
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
            draft_revision=session.revision,
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
            draft_revision=session.revision,
            missing_dependencies=missing_dependencies,
            action="supply every Gateway-owned prerequisite effect",
        )
    ordered = _topological_order(effect_rows, draft_revision=session.revision)
    batches = _layout_batches(ordered, draft_revision=session.revision)
    deadline.checkpoint()
    try:
        raw_request = materialize(batches, deadline)
    except BusinessDeclarationError:
        raise
    except Exception as exc:
        raise business_repair(
            "BUSINESS_PLAN_MATERIALIZATION_FAILED",
            field="native_request",
            draft_revision=session.revision,
            action="repair the closed Adapter instead of authoring native parameters",
        ) from exc
    if not isinstance(raw_request, Mapping):
        raise business_repair(
            "BUSINESS_PLAN_REQUEST_INVALID",
            field="native_request",
            draft_revision=session.revision,
            action="repair the closed Adapter's canonical request materializer",
        )
    if (
        raw_request.get("operation") != normalized_operation
        or raw_request.get("version") != session.context.wwise_version
    ):
        raise business_repair(
            "BUSINESS_PLAN_REQUEST_MISMATCH",
            field="native_request",
            draft_revision=session.revision,
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
            draft_revision=session.revision,
            cause_error_code=exc.error_code,
            action="repair the closed Adapter's canonical request materializer",
        ) from exc
    request_digest = canonical_sha256(request)
    deadline.checkpoint()
    if verify_file_evidence:
        try:
            request_files = _request_file_paths(normalized_operation, request)
        except ValueError as exc:
            raise business_repair(
                "BUSINESS_FILE_EVIDENCE_INVALID",
                field="files",
                draft_revision=session.revision,
                action="repair the closed Adapter's canonical request-file mapping",
            ) from exc
        evidence_paths = tuple(row.path for row in normalized_files)
        if Counter(request_files) != Counter(evidence_paths):
            raise business_repair(
                "BUSINESS_FILE_EVIDENCE_MISMATCH",
                field="files",
                draft_revision=session.revision,
                request_file_count=len(request_files),
                evidence_file_count=len(evidence_paths),
                action="bind every native request file to exact immutable evidence",
            )
        try:
            for row in normalized_files:
                verify_regular_file_proof(
                    row.as_import_proof(),
                    field="business file evidence",
                )
        except (ImportContractError, ValueError) as exc:
            raise business_repair(
                "BUSINESS_FILE_EVIDENCE_STALE",
                field="files",
                draft_revision=session.revision,
                action="refresh immutable file evidence before Preview",
            ) from exc
    verifier_expectations = tuple(
        dict(row.verifier_expectation) for row in ordered
    )
    deadline.checkpoint()
    return PlannedBusinessRequest(
        operation=normalized_operation,
        version=session.context.wwise_version,
        source_revision=session.revision,
        ordered_effect_ids=tuple(row.effect_id for row in ordered),
        batches=batches,
        request=request,
        request_digest=request_digest,
        verifier_expectations=verifier_expectations,
        file_evidence=normalized_files,
        readable_lines=tuple(
            line for row in ordered for line in row.readable_lines
        ),
        deadline=deadline,
    )


def _validate_file_evidence(
    rows: Sequence[BusinessFileEvidence],
    *,
    draft_revision: int,
) -> tuple[BusinessFileEvidence, ...]:
    if (
        not isinstance(rows, Sequence)
        or isinstance(rows, (str, bytes, bytearray))
        or len(rows) > MAX_BUSINESS_FILES
        or any(not isinstance(row, BusinessFileEvidence) for row in rows)
    ):
        raise business_repair(
            "BUSINESS_FILE_LIMIT_EXCEEDED",
            field="files",
            draft_revision=draft_revision,
            file_limit=MAX_BUSINESS_FILES,
            action="split the task into bounded file batches",
        )
    normalized = tuple(rows)
    oversized = tuple(
        row.path for row in normalized if row.size_bytes > MAX_BUSINESS_FILE_BYTES
    )
    total = sum(row.size_bytes for row in normalized)
    if oversized or total > MAX_BUSINESS_TOTAL_FILE_BYTES:
        raise business_repair(
            "BUSINESS_FILE_LIMIT_EXCEEDED",
            field="files",
            draft_revision=draft_revision,
            file_limit=MAX_BUSINESS_FILES,
            file_bytes_limit=MAX_BUSINESS_FILE_BYTES,
            total_file_bytes_limit=MAX_BUSINESS_TOTAL_FILE_BYTES,
            action="split the task into bounded file batches",
        )
    return normalized


def _request_file_paths(
    operation: str,
    request: Mapping[str, Any],
) -> tuple[str, ...]:
    if operation != "audio.import":
        return ()
    arguments = request.get("arguments")
    if not isinstance(arguments, Mapping):
        raise ValueError("canonical audio.import request is missing arguments")
    raw_rows = arguments.get("imports")
    if not isinstance(raw_rows, list):
        raise ValueError("canonical audio.import request is missing import rows")
    defaults = arguments.get("defaults", {})
    if not isinstance(defaults, Mapping):
        raise ValueError("canonical audio.import defaults are invalid")
    files: list[str] = []
    for row in raw_rows:
        if not isinstance(row, Mapping):
            raise ValueError("canonical audio.import row is invalid")
        value = row.get("audio_file", defaults.get("audio_file"))
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            raise ValueError("canonical audio.import audio_file is invalid")
        files.append(value)
    return tuple(files)


def _validate_continuation(value: Any) -> dict[str, Any]:
    continuation = _strict_json_object(value, label="continuation")
    if len(canonical_json_bytes(continuation)) > MAX_BUSINESS_CONTINUATION_BYTES:
        raise ValueError("continuation exceeds its fixed byte limit")
    required = {
        "contract",
        "gateway_argv",
        "full_argv",
        "shell_command",
        "shell_family",
        "copy_exactly",
        "copy_instruction",
    }
    if not required.issubset(continuation):
        raise ValueError("continuation is missing its complete execution envelope")
    if continuation.get("contract") != "waapi-skill.transaction-next-command/v2":
        raise ValueError("continuation contract is invalid")
    for field in ("gateway_argv", "full_argv"):
        argv = continuation.get(field)
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) and item for item in argv)
        ):
            raise ValueError(f"continuation {field} is invalid")
    gateway_argv = continuation["gateway_argv"]
    full_argv = continuation["full_argv"]
    assert isinstance(gateway_argv, list) and isinstance(full_argv, list)
    if len(full_argv) <= len(gateway_argv) or full_argv[-len(gateway_argv) :] != gateway_argv:
        raise ValueError("continuation full_argv and gateway_argv disagree")
    if not isinstance(continuation.get("shell_command"), str) or not continuation[
        "shell_command"
    ]:
        raise ValueError("continuation shell_command is invalid")
    if continuation.get("copy_exactly") is not True:
        raise ValueError("continuation must require exact copying")
    copy_instruction = continuation.get("copy_instruction")
    if not isinstance(copy_instruction, Mapping):
        raise ValueError("continuation copy instruction is invalid")
    if copy_instruction.get("contract") != (
        "waapi-skill.gateway-command-copy-instruction/v2"
    ):
        raise ValueError("continuation copy instruction contract is invalid")
    source_field = copy_instruction.get("source_field")
    if (
        not isinstance(source_field, str)
        or not isinstance(continuation.get(source_field), str)
        or not continuation[source_field]
    ):
        raise ValueError("continuation source field does not name one complete command")
    shell_family = continuation.get("shell_family")
    shell_command = continuation["shell_command"]
    if shell_family == "posix-sh":
        if shlex.join(full_argv) != shell_command:
            raise ValueError("POSIX continuation does not encode full_argv exactly")
    elif shell_family == WINDOWS_POWERSHELL_ENCODED_FAMILY:
        if decode_windows_powershell_argv(shell_command) != tuple(full_argv):
            raise ValueError("Windows continuation does not encode full_argv exactly")
    else:
        raise ValueError("continuation shell family is unsupported")
    if source_field == "model_command":
        if continuation.get("model_shell_family") != WINDOWS_MODEL_COMMAND_FAMILY:
            raise ValueError("Windows model continuation family is invalid")
        if decode_windows_model_argv(continuation["model_command"]) != tuple(full_argv):
            raise ValueError("Windows model continuation does not encode full_argv exactly")
    elif source_field != "shell_command":
        raise ValueError("continuation source field is unsupported")
    return continuation


def _topological_order(
    effects: Sequence[BusinessEffect],
    *,
    draft_revision: int,
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
            draft_revision=draft_revision,
            cycle_candidates=candidates,
            action="repair the Gateway-owned dependency graph",
        )
    return tuple(ordered)


def _layout_batches(
    ordered: Sequence[BusinessEffect],
    *,
    draft_revision: int,
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
            draft_revision=draft_revision,
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
        normalized = strict_json_copy(dict(value))
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise ValueError(f"{label} must contain strict JSON") from exc
    assert isinstance(normalized, dict)
    return normalized


__all__ = [
    "BUSINESS_BATCH_CONTRACT",
    "BUSINESS_EFFECT_CONTRACT",
    "COMPILED_BUSINESS_PLAN_CONTRACT",
    "BusinessBatch",
    "BusinessEffect",
    "BusinessFileEvidence",
    "BusinessPlanningDeadline",
    "PlannedBusinessRequest",
    "CompiledBusinessPlan",
    "MAX_BUSINESS_FILE_BYTES",
    "MAX_BUSINESS_PLANNING_SECONDS",
    "compile_business_plan",
    "plan_business_request",
]
