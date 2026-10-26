"""Runtime guards and immutable artifacts for closed WAAPI transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .authorization import (
    AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,
    AUTHORIZATION_MODE_POLICY,
    accepted_authorization_modes_for_operation,
)
from .console_project_operations import CLI_PROJECT_FILE_URIS
from .canonical import canonical_sha256, sha256_hex
from .execution_contracts import (
    CONTEXT_RUNTIME_ONLY_POST_EXECUTION_URIS,
    ExecutionContractRegistry,
    POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY,
    POST_EXECUTION_PROJECT_GUARD_POLICIES,
    POST_EXECUTION_PROJECT_GUARD_REVALIDATE,
    PROJECT_GUARD_INVARIANT,
    PROJECT_GUARD_MODES,
    PROJECT_GUARD_TRANSITION_TO_NONE,
    PROJECT_GUARD_TRANSITION_TO_PATH,
)
from .host_paths import HostPathError, parse_absolute_host_path
from .operation_registry import (
    OperationRequest,
    PreparedOperation,
    ReadCall,
    parse_operation_request,
    prepare_operation,
)
from .platform_paths import (
    WwiseWirePathError,
    adapt_cli_dispatch_paths,
    localize_live_wwise_project_path,
)


TRANSACTION_PREVIEW_CONTRACT = "waapi-skill.transaction-preview/v2"
PROJECT_GUARD_CONTRACT = "waapi-skill.project-guard/v1"
RUNTIME_GUARD_CONTRACT = "waapi-skill.runtime-guard/v1"
DEFAULT_PREVIEW_TTL_SECONDS = 30 * 60
PROJECT_GUARD_PHASE_PRE_EXECUTION = "pre_execution"
PROJECT_GUARD_PHASE_POST_VERIFICATION = "post_verification"
PROJECT_GUARD_PHASES = frozenset(
    {
        PROJECT_GUARD_PHASE_PRE_EXECUTION,
        PROJECT_GUARD_PHASE_POST_VERIFICATION,
    }
)


class TransactionGuardError(RuntimeError):
    """The live project, packaged runtime, or preview lifetime no longer matches."""

    def __init__(self, error_code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), "details": dict(self.details)}


@dataclass(frozen=True, slots=True)
class TransactionArtifact:
    request: OperationRequest
    prepared_operation: PreparedOperation
    project_guard: Mapping[str, Any]
    runtime_guard: Mapping[str, Any]
    created_at: str
    expires_at: str

    def as_dict(self) -> dict[str, Any]:
        authorization_modes = _artifact_authorization_modes(
            self.request,
            self.prepared_operation,
        )
        return {
            "contract": TRANSACTION_PREVIEW_CONTRACT,
            "request": self.request.as_dict(),
            "prepared_operation": self.prepared_operation.as_dict(),
            "project_guard": dict(self.project_guard),
            "runtime_guard": dict(self.runtime_guard),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "execution_policy": {
                "requires_authorization": True,
                "accepted_authorization_modes": list(authorization_modes),
                "authorization_selected_at_preview": True,
                "automatic_retry_allowed": False,
                # Historical v1 key: this is the pre-execution project guard
                # revalidation. The URI-specific post-execution policy is
                # sealed in prepared_operation.pre_state.execution_contract.
                "revalidate_project_guard": True,
                "revalidate_runtime_guard": True,
                "revalidate_resolved_roles": True,
                "post_execution_verification_required": True,
            },
        }


def _artifact_authorization_modes(
    request: OperationRequest,
    prepared_operation: PreparedOperation,
) -> tuple[str, ...]:
    """Bind the exact accepted durable authority set into one preview."""

    sealed_contract = prepared_operation.pre_state.get("execution_contract")
    if isinstance(sealed_contract, Mapping):
        raw_modes = sealed_contract.get("accepted_authorization_modes")
        if isinstance(raw_modes, (list, tuple)):
            modes = tuple(raw_modes)
            if (
                modes
                and len(modes) == len(set(modes))
                and all(
                    mode
                    in {
                        AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,
                        AUTHORIZATION_MODE_POLICY,
                    }
                    for mode in modes
                )
            ):
                return modes
            raise ValueError(
                "sealed execution contract has invalid accepted authorization modes"
            )
    return accepted_authorization_modes_for_operation(request.operation)


def build_project_guard(
    *,
    endpoint: Mapping[str, Any],
    version: str,
    live_info: Mapping[str, Any],
    project: Mapping[str, Any] | None,
    project_guard_mode: str = PROJECT_GUARD_INVARIANT,
    target_project_path: str | None = None,
) -> dict[str, Any]:
    mode = _require_project_guard_mode(project_guard_mode)
    if project is None and mode == PROJECT_GUARD_INVARIANT:
        raise TransactionGuardError(
            "PROJECT_REQUIRED",
            "Invariant transactions require one explicit active-project identity.",
        )
    context = _runtime_context(
        endpoint=endpoint,
        version=version,
        live_info=live_info,
    )
    project_snapshot = (
        {"state": "none"}
        if project is None
        else {
            "state": "open",
            **{
            key: project.get(key)
            for key in ("id", "name", "path", "projectPath", "filePath")
            if project.get(key) is not None
            },
        }
    )
    if mode == PROJECT_GUARD_TRANSITION_TO_PATH:
        postcondition = {
            "state": "open",
            "canonical_path": canonical_project_path(target_project_path),
        }
    elif mode == PROJECT_GUARD_TRANSITION_TO_NONE:
        if target_project_path is not None:
            raise TransactionGuardError(
                "INVALID_PROJECT_TRANSITION",
                "transition_to_none must not declare a target project path.",
            )
        postcondition = {"state": "none"}
    else:
        if target_project_path is not None:
            raise TransactionGuardError(
                "INVALID_PROJECT_TRANSITION",
                "Invariant project guards must not declare a target project path.",
            )
        postcondition = {"state": "same_project"}
    body = {
        **context,
        "project_guard_mode": mode,
        "project": project_snapshot,
        "postcondition": postcondition,
    }
    return {
        "contract": PROJECT_GUARD_CONTRACT,
        **body,
        "context_fingerprint": canonical_sha256(context),
        "fingerprint": canonical_sha256(body),
    }


def _runtime_context(
    *,
    endpoint: Mapping[str, Any],
    version: str,
    live_info: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "endpoint": {
            key: endpoint.get(key)
            for key in ("host", "port", "url")
            if endpoint.get(key) is not None
        },
        "version": version,
        "wwise": {
            "displayName": live_info.get("displayName"),
            "isCommandLine": live_info.get("isCommandLine"),
            "version": live_info.get("version"),
            "sessionId": live_info.get("sessionId"),
            "processId": live_info.get("processId"),
            "processPath": live_info.get("processPath"),
            "apiVersion": live_info.get("apiVersion"),
            "platform": live_info.get("platform"),
            "configuration": live_info.get("configuration"),
        },
    }


def canonical_project_path(value: Any) -> str:
    """Return one host-independent canonical absolute WPROJ path."""

    if not isinstance(value, str) or not value:
        raise TransactionGuardError(
            "INVALID_PROJECT_TRANSITION",
            "Project transitions require a non-empty absolute WPROJ path.",
            details={"target_project_path": value},
        )
    try:
        parsed = parse_absolute_host_path(value)
    except HostPathError as exc:
        raise TransactionGuardError(
            "INVALID_PROJECT_TRANSITION",
            "Project transition path must be a strict absolute host path.",
            details={"target_project_path": value, "path_error": str(exc)},
        ) from exc
    if not parsed.pure_path.name.casefold().endswith(".wproj"):
        raise TransactionGuardError(
            "INVALID_PROJECT_TRANSITION",
            "Project transition path must identify a .wproj file.",
            details={"target_project_path": value},
        )
    if parsed.flavor == "posix":
        return f"posix:{parsed.pure_path.as_posix()}"
    return f"windows:{str(parsed.pure_path).casefold()}"


def build_runtime_guard(skill_root: Path, version: str) -> dict[str, Any]:
    root = skill_root.resolve()
    files: dict[str, str] = {}
    for relative in _runtime_files(root, version):
        path = root / relative
        if not path.is_file():
            raise TransactionGuardError(
                "RUNTIME_FILE_MISSING",
                f"Required packaged runtime file is missing: {relative}",
                details={"relative_path": relative, "skill_root": str(root)},
            )
        files[relative] = sha256_hex(path.read_bytes())
    body = {"version": version, "files": files}
    return {"contract": RUNTIME_GUARD_CONTRACT, **body, "fingerprint": canonical_sha256(body)}


def _validate_tab_native_boundaries(
    request: Mapping[str, Any], verification: Mapping[str, Any], project_guard: Mapping[str, Any],
) -> None:
    if request.get("operation") != "audio.importTabDelimited" or request.get("version") != "2025.1":
        return
    host = project_guard.get("wwise", {})
    if not isinstance(host, Mapping):
        return
    observed_version = host.get("version", {})
    if (not isinstance(observed_version, Mapping) or host.get("isCommandLine") is not True
            or any(observed_version.get(key) != value for key, value in
                   (("year", 2025), ("major", 1), ("minor", 7), ("build", 9143)))):
        return
    targets = verification.get("targets", [])
    if not isinstance(targets, list):
        raise TransactionGuardError("INVALID_PREVIEW", "The TSV verification target list is malformed.")
    guid_rows = [{"row": target.get("row_number"), "object_path": target["requested_target_id"]}
                 for target in targets if isinstance(target, Mapping) and "requested_target_id" in target]
    if guid_rows:
        # Retained import182-tsv-guid-2025-r1: both supplied canonical GUIDs
        # produced new literal-name Sound/Source nodes, leaving targets unchanged.
        raise TransactionGuardError("TSV_GUID_OBJECT_PATH_UNSAFE_ON_HOST",
            "WwiseConsole 2025.1.7 build 9143 was observed treating TSV Object Path GUID cells as literal object names and creating unintended objects. GUID TSV targets are blocked on this host before preview or writing; the table is not rewritten.",
            details={"observed_version": dict(observed_version), "is_command_line": True,
                     "native_interpretation": "literal_object_names", "guid_rows": guid_rows,
                     "evidence_case": "import182-tsv-guid-2025-r1",
                     "other_host_version_semantics": "unproven_scope_decision_pending"})
    if verification.get("import_operation") != "useExisting":
        return
    for target in targets:
        if (not isinstance(target, Mapping) or target.get("localized_owner_fields") is not True
                or target.get("media_expected") is not True
                or not (target.get("validated_properties") or target.get("validated_references"))
                or not target.get("preexisting_id") or not target.get("localized_audio_file_source_id")):
            continue
        snapshot = target.get("localized_source_snapshot", {})
        path = target.get("expected_audio_file_source_result_path")
        if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("rows"), list):
            raise TransactionGuardError("INVALID_PREVIEW", "Combined localized Source reuse requires its sealed owner snapshot.")
        candidates = [source for source in snapshot["rows"] if isinstance(source, Mapping)
            and source.get("type") == "AudioFileSource" and isinstance(path, str)
            and str(source.get("path", "")).casefold() == path.casefold()]
        # Both shared-path and distinct-path retained attempts changed fields
        # and bytes while adding another English Source. Path uniqueness does
        # not establish safe combined reuse on this exact observed host.
        raise TransactionGuardError("TSV_COMBINED_SOURCE_IDENTITY_UNSAFE_ON_HOST",
            "WwiseConsole 2025.1.7 build 9143 added an extra Source during combined localized existing-owner fields/media reuse with both shared and distinct language Source paths. This host configuration is blocked before preview or writing; the exact table is not rewritten. The cause and a safe combined mapping remain unresolved.",
            details={"observed_version": dict(observed_version), "is_command_line": True,
                "row": target.get("row_number"), "owner_id": target["preexisting_id"],
                "selected_source_id": target["localized_audio_file_source_id"],
                "source_path": path, "candidate_ids": [source.get("id") for source in candidates],
                "evidence_cases": ["import182-tsv-combined-2025-r1", "import182-tsv-distinct-source-2025-r1"],
                "root_cause": "unproven; shared paths are not a necessary condition",
                "other_host_version_semantics": "unproven; outside this boundary"})


def _validate_tab_media_path_namespace(prepared: PreparedOperation, project_guard: Mapping[str, Any]) -> None:
    if prepared.request.operation != "audio.importTabDelimited":
        return
    guard = prepared.pre_state.get("import_guard", {})
    proofs = [item["proof"] for item in guard.get("file_proofs", [])
              if isinstance(item, Mapping) and isinstance(item.get("proof"), Mapping)
              and "native_path" in item["proof"]]
    if not proofs:
        return
    dispatch = prepared.semantic_preview.dispatch_payload()
    try:
        observed = adapt_cli_dispatch_paths(uri=dispatch["uri"], args=dispatch["args"], options=dispatch["options"],
            io_audit=guard["wire_path_input_audit"], project_guard=project_guard)
    except WwiseWirePathError as exc:
        raise TransactionGuardError(exc.error_code, str(exc), details=exc.details) from exc
    mode = observed.proof["mode"]
    for proof in proofs:
        if mode == "local_posix_wine" and proof["native_path"].startswith("/"):
            raise TransactionGuardError("NATIVE_MEDIA_PATH_REQUIRED",
                "An exact TSV for the proven Wine host requires a native Windows media path or a path relative to the table directory; its bytes cannot be rewritten.",
                details={"native_path": proof["native_path"], "host_path": proof["path"]})


def build_transaction_preview_artifact(
    request_payload: Mapping[str, Any],
    *,
    live_version: str,
    read_call: ReadCall,
    project_guard: Mapping[str, Any],
    skill_root: Path,
    history_resolver=None,
    copy_proof_context=None,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_PREVIEW_TTL_SECONDS,
) -> TransactionArtifact:
    """Build a Preview from one raw canonical request, owning its reparse.

    Callers must provide the JSON-shaped ``OperationRequest`` payload rather
    than a parsed or prepared in-memory object.  This Interface deliberately
    repeats strict parsing before every immutable Preview so no upstream
    Adapter can bypass version, shape, preparation, or verification checks.
    """

    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be greater than zero")
    request = parse_operation_request(request_payload, expected_version=live_version)
    prepared = prepare_operation(request, read_call=read_call, history_resolver=history_resolver, copy_proof_context=copy_proof_context)
    _validate_tab_native_boundaries(request.as_dict(), prepared.verification_plan, project_guard)
    _validate_tab_media_path_namespace(prepared, project_guard)
    post_execution_project_guard_policy = _prepared_post_execution_project_guard_policy(
        prepared
    )
    if (
        post_execution_project_guard_policy
        == POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY
    ):
        _require_strong_project_guard_runtime_identity(project_guard)
    created = _utc(now)
    expires = created + timedelta(seconds=ttl_seconds)
    return TransactionArtifact(
        request=request,
        prepared_operation=prepared,
        project_guard=dict(project_guard),
        runtime_guard=build_runtime_guard(skill_root, request.version),
        created_at=_timestamp(created),
        expires_at=_timestamp(expires),
    )


def _prepared_post_execution_project_guard_policy(prepared: PreparedOperation) -> str:
    if prepared.request.operation != "waapi.call":
        return POST_EXECUTION_PROJECT_GUARD_REVALIDATE
    execution_contract = prepared.pre_state.get("execution_contract")
    if not isinstance(execution_contract, Mapping):
        raise TransactionGuardError(
            "INVALID_PREVIEW",
            "Prepared waapi.call is missing its execution contract.",
        )
    policy = execution_contract.get("post_execution_project_guard_policy")
    if not isinstance(policy, str) or policy not in POST_EXECUTION_PROJECT_GUARD_POLICIES:
        raise TransactionGuardError(
            "INVALID_PREVIEW",
            "Prepared waapi.call has an unsupported post-execution project-guard policy.",
            details={"policy": policy},
        )
    return policy


def _require_strong_project_guard_runtime_identity(
    project_guard: Mapping[str, Any],
) -> None:
    wwise = project_guard.get("wwise")
    if not isinstance(wwise, Mapping):
        raise TransactionGuardError(
            "RUNTIME_CONTEXT_IDENTITY_MISSING",
            "Context/runtime-only verification requires a strong Wwise process identity at preview.",
        )
    for identity, expected_type in (
        ("sessionId", str),
        ("processId", int),
        ("processPath", str),
    ):
        value = wwise.get(identity)
        if (
            not isinstance(value, expected_type)
            or isinstance(value, bool)
            or not value
        ):
            raise TransactionGuardError(
                "RUNTIME_CONTEXT_IDENTITY_MISSING",
                "Context/runtime-only verification requires a strong Wwise process identity at preview.",
                details={"field": identity},
            )


def validate_transaction_context_runtime_guards(
    artifact: Mapping[str, Any],
    *,
    endpoint: Mapping[str, Any],
    version: str,
    live_info: Mapping[str, Any],
    skill_root: Path,
) -> Mapping[str, Any]:
    """Validate post-execution context/runtime guards without a project probe."""

    if artifact.get("contract") != TRANSACTION_PREVIEW_CONTRACT:
        raise TransactionGuardError(
            "INVALID_PREVIEW",
            "Transaction preview contract is missing or unsupported.",
        )
    request = artifact.get("request")
    if not isinstance(request, Mapping) or not isinstance(request.get("version"), str):
        raise TransactionGuardError(
            "INVALID_PREVIEW",
            "Transaction preview lacks a versioned request.",
        )
    if request.get("version") != version:
        raise TransactionGuardError(
            "PROJECT_GUARD_MISMATCH",
            "Live Wwise version no longer matches the confirmed preview.",
            details={"expected_version": request.get("version"), "actual_version": version},
        )
    if request.get("operation") != "waapi.call":
        raise TransactionGuardError(
            "INVALID_PREVIEW",
            "Context/runtime-only verification is restricted to a sealed waapi.call request.",
        )
    arguments = request.get("arguments")
    api = arguments.get("api") if isinstance(arguments, Mapping) else None
    if api not in CONTEXT_RUNTIME_ONLY_POST_EXECUTION_URIS:
        raise TransactionGuardError(
            "INVALID_PREVIEW",
            "Context/runtime-only verification is restricted to the reviewed explicit-project Wwise CLI calls.",
        )
    prepared = artifact.get("prepared_operation")
    if not isinstance(prepared, Mapping) or prepared.get("request") != request:
        raise TransactionGuardError(
            "INVALID_PREVIEW",
            "Prepared request does not match the sealed transaction request.",
        )
    dispatch = prepared.get("dispatch")
    verification_plan = prepared.get("verification_plan")
    pre_state = prepared.get("pre_state")
    sealed_contract = (
        pre_state.get("execution_contract")
        if isinstance(pre_state, Mapping)
        else None
    )
    if (
        not isinstance(dispatch, Mapping)
        or dict(dispatch)
        != {
            "uri": api,
            "args": dict(arguments.get("args", {}))
            if isinstance(arguments.get("args", {}), Mapping)
            else None,
            "options": dict(arguments.get("options", {}))
            if isinstance(arguments.get("options", {}), Mapping)
            else None,
        }
        or not isinstance(verification_plan, Mapping)
        or dict(verification_plan)
        != ({
            "kind": "console-project-process",
            "uri": api,
            "version": version,
            "base_result_strategy": "result_schema",
        } if api in CLI_PROJECT_FILE_URIS else {
            "kind": "result-schema",
            "uri": api,
            "version": version,
            "strategy": "result_schema",
        })
        or not isinstance(sealed_contract, Mapping)
    ):
        raise TransactionGuardError(
            "INVALID_PREVIEW",
            "Prepared dispatch, verification plan, or execution contract does not match the sealed request.",
        )
    current_contract = ExecutionContractRegistry().describe(
        version,
        api,
    )
    required_contract_fields = {
        "version": version,
        "uri": api,
        "route": "isolated_transaction",
        "verification_strategy": "result_schema",
        "project_guard_mode": PROJECT_GUARD_INVARIANT,
        "post_execution_project_guard_policy": (
            POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY
        ),
    }
    if any(
        sealed_contract.get(field) != expected
        or current_contract.as_dict().get(field) != expected
        for field, expected in required_contract_fields.items()
    ):
        raise TransactionGuardError(
            "INVALID_PREVIEW",
            "Sealed and current execution contracts do not match the context/runtime-only policy.",
        )
    stored_project = artifact.get("project_guard")
    stored_runtime = artifact.get("runtime_guard")
    if not isinstance(stored_project, Mapping) or not isinstance(stored_runtime, Mapping):
        raise TransactionGuardError(
            "INVALID_PREVIEW",
            "Transaction preview lacks project/runtime guards.",
        )
    mode = _require_project_guard_mode(stored_project.get("project_guard_mode"))
    if mode != PROJECT_GUARD_INVARIANT:
        raise TransactionGuardError(
            "INVALID_PREVIEW",
            "Context/runtime-only verification requires an invariant pre-execution project guard.",
        )
    current_context = _runtime_context(
        endpoint=endpoint,
        version=version,
        live_info=live_info,
    )
    stored_wwise = stored_project.get("wwise")
    current_wwise = current_context.get("wwise")
    if not isinstance(stored_wwise, Mapping) or not isinstance(current_wwise, Mapping):
        raise TransactionGuardError(
            "RUNTIME_CONTEXT_IDENTITY_MISSING",
            "Transaction context lacks a strong Wwise process identity.",
        )
    for identity, expected_type in (
        ("sessionId", str),
        ("processId", int),
        ("processPath", str),
    ):
        stored_value = stored_wwise.get(identity)
        current_value = current_wwise.get(identity)
        if (
            not isinstance(stored_value, expected_type)
            or isinstance(stored_value, bool)
            or not stored_value
            or not isinstance(current_value, expected_type)
            or isinstance(current_value, bool)
            or not current_value
        ):
            raise TransactionGuardError(
                "RUNTIME_CONTEXT_IDENTITY_MISSING",
                "Transaction context lacks a strong Wwise process identity.",
                details={"field": identity},
            )
    current_context_fingerprint = canonical_sha256(current_context)
    stored_context_fingerprint = stored_project.get("context_fingerprint")
    if stored_context_fingerprint != current_context_fingerprint:
        raise TransactionGuardError(
            "PROJECT_GUARD_MISMATCH",
            "Live endpoint/version/getInfo context no longer matches the confirmed preview.",
            details={
                "expected_context_fingerprint": stored_context_fingerprint,
                "actual_context_fingerprint": current_context_fingerprint,
            },
        )
    current_runtime = build_runtime_guard(skill_root, version)
    if stored_runtime.get("fingerprint") != current_runtime.get("fingerprint"):
        raise TransactionGuardError(
            "RUNTIME_GUARD_MISMATCH",
            "Packaged builders, schemas, or transaction runtime changed after preview.",
            details={
                "expected_fingerprint": stored_runtime.get("fingerprint"),
                "actual_fingerprint": current_runtime.get("fingerprint"),
            },
        )
    return {
        "ok": True,
        "status": "valid",
        "post_execution_project_guard_policy": (
            POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY
        ),
        "project_guard_mode": mode,
        "project_guard_phase": PROJECT_GUARD_PHASE_POST_VERIFICATION,
        "project_probe_performed": False,
        "project_identity_revalidated": False,
        "context_guard_validated": True,
        "runtime_guard_validated": True,
        "context_fingerprint": current_context_fingerprint,
        "runtime_guard_fingerprint": current_runtime["fingerprint"],
        "expires_at": artifact.get("expires_at"),
    }


def validate_transaction_guards(
    artifact: Mapping[str, Any],
    *,
    current_project_guard: Mapping[str, Any],
    skill_root: Path,
    now: datetime | None = None,
    check_expiry: bool = True,
    project_phase: str = PROJECT_GUARD_PHASE_PRE_EXECUTION,
) -> Mapping[str, Any]:
    if project_phase not in PROJECT_GUARD_PHASES:
        raise TransactionGuardError(
            "INVALID_PROJECT_GUARD_PHASE",
            f"Unsupported project guard phase {project_phase!r}.",
        )
    if artifact.get("contract") != TRANSACTION_PREVIEW_CONTRACT:
        raise TransactionGuardError("INVALID_PREVIEW", "Transaction preview contract is missing or unsupported.")
    request = artifact.get("request")
    if not isinstance(request, Mapping) or not isinstance(request.get("version"), str):
        raise TransactionGuardError("INVALID_PREVIEW", "Transaction preview lacks a versioned request.")
    if project_phase == PROJECT_GUARD_PHASE_PRE_EXECUTION:
        prepared = artifact.get("prepared_operation", {})
        verification = prepared.get("verification_plan", {}) if isinstance(prepared, Mapping) else {}
        if isinstance(verification, Mapping):
            _validate_tab_native_boundaries(request, verification, current_project_guard)
    stored_project = artifact.get("project_guard")
    stored_runtime = artifact.get("runtime_guard")
    if not isinstance(stored_project, Mapping) or not isinstance(stored_runtime, Mapping):
        raise TransactionGuardError("INVALID_PREVIEW", "Transaction preview lacks project/runtime guards.")
    expires_at = artifact.get("expires_at")
    if not isinstance(expires_at, str):
        raise TransactionGuardError("INVALID_PREVIEW", "Transaction preview lacks expires_at.")
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransactionGuardError("INVALID_PREVIEW", "Transaction preview expires_at is invalid.") from exc
    current_time = _utc(now)
    if check_expiry and current_time > expires:
        raise TransactionGuardError(
            "PREVIEW_EXPIRED",
            "Confirmed preview has expired; create and review a fresh preview.",
            details={"expires_at": expires_at, "current_time": _timestamp(current_time)},
        )

    stored_project_fingerprint = stored_project.get("fingerprint")
    current_project_fingerprint = current_project_guard.get("fingerprint")
    mode = _require_project_guard_mode(stored_project.get("project_guard_mode"))
    current_mode = _require_project_guard_mode(current_project_guard.get("project_guard_mode"))
    if current_mode != mode:
        raise TransactionGuardError(
            "PROJECT_GUARD_MISMATCH",
            "Current project observation uses a different guard mode than the immutable preview.",
            details={"expected_mode": mode, "actual_mode": current_mode},
        )

    project_transition: Mapping[str, Any] | None = None
    compare_invariant = (
        project_phase == PROJECT_GUARD_PHASE_PRE_EXECUTION
        or mode == PROJECT_GUARD_INVARIANT
    )
    if compare_invariant:
        if stored_project_fingerprint != current_project_fingerprint:
            raise TransactionGuardError(
                "PROJECT_GUARD_MISMATCH",
                "Live endpoint/project no longer matches the confirmed preview.",
                details={
                    "expected_fingerprint": stored_project_fingerprint,
                    "actual_fingerprint": current_project_fingerprint,
                    "expected": dict(stored_project),
                    "actual": dict(current_project_guard),
                },
            )
    else:
        if stored_project.get("context_fingerprint") != current_project_guard.get("context_fingerprint"):
            raise TransactionGuardError(
                "PROJECT_GUARD_MISMATCH",
                "Live endpoint/version no longer matches the confirmed project transition.",
                details={
                    "expected_context_fingerprint": stored_project.get("context_fingerprint"),
                    "actual_context_fingerprint": current_project_guard.get("context_fingerprint"),
                },
            )
        expected_postcondition = stored_project.get("postcondition")
        current_postcondition = current_project_guard.get("postcondition")
        if expected_postcondition != current_postcondition or not isinstance(expected_postcondition, Mapping):
            raise TransactionGuardError(
                "PROJECT_GUARD_MISMATCH",
                "Current project observation does not carry the immutable transition postcondition.",
                details={
                    "expected_postcondition": expected_postcondition,
                    "actual_postcondition": current_postcondition,
                },
            )
        actual_project = current_project_guard.get("project")
        if not isinstance(actual_project, Mapping):
            raise TransactionGuardError(
                "PROJECT_TRANSITION_MISMATCH",
                "Current project observation is malformed.",
                details={"expected": dict(expected_postcondition), "actual": actual_project},
            )
        if mode == PROJECT_GUARD_TRANSITION_TO_PATH:
            actual_path = _project_snapshot_path(actual_project)
            actual_path_error: Mapping[str, Any] | None = None
            if actual_project.get("state") == "open" and actual_path is not None:
                endpoint = current_project_guard.get("endpoint")
                wwise = current_project_guard.get("wwise")
                try:
                    localized_actual_path = localize_live_wwise_project_path(
                        actual_path,
                        endpoint=endpoint if isinstance(endpoint, Mapping) else {},
                        wwise=wwise if isinstance(wwise, Mapping) else {},
                    )
                    actual_canonical_path = canonical_project_path(
                        localized_actual_path
                    )
                except WwiseWirePathError as exc:
                    actual_canonical_path = None
                    actual_path_error = exc.as_dict()
            else:
                actual_canonical_path = None
            matched = actual_canonical_path == expected_postcondition.get("canonical_path")
        else:
            actual_canonical_path = None
            actual_path_error = None
            matched = (
                mode == PROJECT_GUARD_TRANSITION_TO_NONE
                and actual_project.get("state") == "none"
            )
        project_transition = {
            "mode": mode,
            "expected": dict(expected_postcondition),
            "actual": dict(actual_project),
            "actual_canonical_path": actual_canonical_path,
            **(
                {"actual_path_error": dict(actual_path_error)}
                if actual_path_error is not None
                else {}
            ),
            "matched": matched,
        }
        if not matched:
            raise TransactionGuardError(
                "PROJECT_TRANSITION_MISMATCH",
                "Live project does not match the confirmed transition postcondition.",
                details=dict(project_transition),
            )

    current_runtime = build_runtime_guard(skill_root, str(request["version"]))
    if stored_runtime.get("fingerprint") != current_runtime.get("fingerprint"):
        raise TransactionGuardError(
            "RUNTIME_GUARD_MISMATCH",
            "Packaged builders, schemas, or transaction runtime changed after preview.",
            details={
                "expected_fingerprint": stored_runtime.get("fingerprint"),
                "actual_fingerprint": current_runtime.get("fingerprint"),
            },
        )
    return {
        "ok": True,
        "status": "valid",
        "project_guard_mode": mode,
        "project_guard_phase": project_phase,
        "project_transition": dict(project_transition) if project_transition is not None else None,
        "project_guard_fingerprint": current_project_fingerprint,
        "runtime_guard_fingerprint": current_runtime["fingerprint"],
        "expires_at": expires_at,
    }


def _require_project_guard_mode(value: Any) -> str:
    if not isinstance(value, str) or value not in PROJECT_GUARD_MODES:
        raise TransactionGuardError(
            "INVALID_PROJECT_GUARD_MODE",
            f"Unsupported project guard mode {value!r}.",
        )
    return value


def _project_snapshot_path(project: Mapping[str, Any]) -> str | None:
    # In Wwise 2021.1 the Project object's ``path`` is the hierarchy value
    # ``\\``; ``filePath`` is the filesystem identity.  Later getProjectInfo
    # responses expose the WPROJ path as ``path``.  Prefer explicit filesystem
    # accessors while retaining the later-version fallback.
    for key in ("filePath", "projectPath", "path"):
        value = project.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _runtime_files(root: Path, version: str) -> tuple[str, ...]:
    package_root = root / "wwise_waapi"
    if not package_root.is_dir():
        raise TransactionGuardError(
            "RUNTIME_FILE_MISSING",
            "Required packaged runtime directory is missing: wwise_waapi",
            details={"relative_path": "wwise_waapi", "skill_root": str(root)},
        )
    # Bind the complete packaged Python implementation, not a hand-maintained
    # subset. New operation builders or helper modules must never become an
    # un-fingerprinted execution dependency after a preview was confirmed.
    scripts_root = root / "scripts"
    common = tuple(
        sorted(path.relative_to(root).as_posix() for path in package_root.rglob("*.py") if path.is_file())
    ) + tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in scripts_root.glob("*.py")
            if path.is_file() and path.name in {"gateway.py", "run.py"}
        )
    )
    versioned = (
        f"resources/manifest/{version}/manifest.json",
        f"resources/manifest/{version}/functions.json",
        f"resources/manifest/{version}/schemas.json",
        f"resources/manifest/{version}/topics.json",
        f"resources/manifest/{version}/authoring-ui-commands-supplement.json",
        f"resources/semantic/{version}/source_notes.json",
    )
    return common + versioned


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return current.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = [
    "DEFAULT_PREVIEW_TTL_SECONDS",
    "PROJECT_GUARD_CONTRACT",
    "PROJECT_GUARD_PHASE_POST_VERIFICATION",
    "PROJECT_GUARD_PHASE_PRE_EXECUTION",
    "RUNTIME_GUARD_CONTRACT",
    "TRANSACTION_PREVIEW_CONTRACT",
    "TransactionArtifact",
    "TransactionGuardError",
    "build_project_guard",
    "canonical_project_path",
    "build_runtime_guard",
    "build_transaction_preview_artifact",
    "validate_transaction_context_runtime_guards",
    "validate_transaction_guards",
]
