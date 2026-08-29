"""Pure lifecycle cleanup specifications for packaged WAAPI transactions.

The transaction gateway persists the returned specification inside its
immutable preview artifact.  This module deliberately performs no WAAPI calls
and owns no transaction state; it only binds a reviewed opener to the exact
packaged companion request that can be disclosed at each transaction phase.

All public inputs and outputs are strict JSON values.  Inputs are recursively
copied, and every cleanup specification carries a canonical SHA-256 digest so
later projection fails closed if the persisted document was changed.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping


CLEANUP_SPEC_CONTRACT = "waapi-skill.transaction-cleanup-spec/v1"
CLEANUP_PROJECTION_CONTRACT = "waapi-skill.transaction-cleanup-projection/v1"

CLEANUP_PHASES = frozenset({"preview", "executed", "verified", "indeterminate"})
UINT32_MAX = (1 << 32) - 1


@dataclass(frozen=True, slots=True)
class _LifecycleBinding:
    companion_api: str
    source_kind: str
    source_field: str | None = None
    target_field: str | None = None
    lifecycle_strategy: str = "paired_follow_up_required"
    cleanup_requirement: str = "required_cleanup"
    warnings: tuple[str, ...] = ()


_OPENERS: Mapping[str, _LifecycleBinding] = {
    "ak.soundengine.loadBank": _LifecycleBinding(
        "ak.soundengine.unloadBank",
        "request_argument",
        "soundBank",
        "soundBank",
    ),
    "ak.soundengine.registerGameObj": _LifecycleBinding(
        "ak.soundengine.unregisterGameObj",
        "request_argument",
        "gameObject",
        "gameObject",
    ),
    "ak.wwise.core.profiler.registerMeter": _LifecycleBinding(
        "ak.wwise.core.profiler.unregisterMeter",
        "request_argument",
        "object",
        "object",
    ),
    "ak.wwise.core.profiler.startCapture": _LifecycleBinding(
        "ak.wwise.core.profiler.stopCapture",
        "no_arguments",
    ),
    "ak.wwise.core.remote.connect": _LifecycleBinding(
        "ak.wwise.core.remote.disconnect",
        "no_arguments",
    ),
    "ak.wwise.core.transport.create": _LifecycleBinding(
        "ak.wwise.core.transport.destroy",
        "execution_result",
        "result.transport",
        "transport",
    ),
    "ak.wwise.core.workUnit.load": _LifecycleBinding(
        "ak.wwise.core.workUnit.unload",
        "request_argument",
        "object",
        "object",
        lifecycle_strategy="reversible_state_change",
        cleanup_requirement="available_reversal",
        warnings=(
            "Loading or unloading a Work Unit clears the Wwise Undo history.",
            "The available unload reversal can fail when the Work Unit has unsaved modifications.",
        ),
    ),
}

_CLOSERS = frozenset(binding.companion_api for binding in _OPENERS.values())

_SPEC_KEYS = frozenset(
    {
        "contract",
        "api",
        "lifecycle_action",
        "lifecycle_strategy",
        "cleanup_requirement",
        "companion_request",
        "binding",
        "warnings",
        "automatic_cleanup",
        "automatic_retry",
        "spec_sha256",
    }
)


class TransactionCleanupError(ValueError):
    """A cleanup document is not strict, reviewed, or internally consistent."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = _strict_json_copy(details or {}, path="details")

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": _strict_json_copy(self.details, path="details"),
        }


def build_transaction_cleanup_spec(
    api: str,
    args: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one digest-bound strict-JSON cleanup specification.

    Request-derived bindings are copied from ``args``.  The transport ID is the
    sole delayed binding and is intentionally absent until an execution result
    is projected.  An unreviewed lifecycle companion fails closed instead of
    being represented as ordinary/no-cleanup work.
    """

    if not isinstance(api, str) or not api:
        raise TransactionCleanupError(
            "INVALID_CLEANUP_INPUT",
            "api must be a non-empty string.",
        )
    args_copy = _require_json_object(args, path="args")
    contract_copy = _require_json_object(execution_contract, path="execution_contract")
    contract_api = contract_copy.get("uri")
    if contract_api is not None and contract_api != api:
        raise TransactionCleanupError(
            "CLEANUP_CONTRACT_MISMATCH",
            "The execution contract URI does not match the cleanup API.",
            details={"api": api, "contract_uri": contract_api},
        )
    declared_companions = contract_copy.get("companion_uris", [])
    if not isinstance(declared_companions, list) or not all(
        isinstance(item, str) and item for item in declared_companions
    ):
        raise TransactionCleanupError(
            "CLEANUP_CONTRACT_MISMATCH",
            "execution_contract.companion_uris must be an array of non-empty strings.",
            details={"api": api, "companion_uris": declared_companions},
        )

    binding = _OPENERS.get(api)
    if binding is not None:
        expected_companions = [binding.companion_api]
        if declared_companions != expected_companions:
            raise TransactionCleanupError(
                "CLEANUP_CONTRACT_MISMATCH",
                "The execution contract does not declare the reviewed lifecycle companion.",
                details={
                    "api": api,
                    "expected_companion_uris": expected_companions,
                    "actual_companion_uris": declared_companions,
                },
            )
        companion_args, binding_payload = _build_opener_binding(api, args_copy, binding)
        base = {
            "contract": CLEANUP_SPEC_CONTRACT,
            "api": api,
            "lifecycle_action": "opener",
            "lifecycle_strategy": binding.lifecycle_strategy,
            "cleanup_requirement": binding.cleanup_requirement,
            "companion_request": {
                "api": binding.companion_api,
                "args": companion_args,
                "options": {},
            },
            "binding": binding_payload,
            "warnings": list(binding.warnings),
            "automatic_cleanup": False,
            "automatic_retry": False,
        }
        return _seal_spec(base)

    if declared_companions:
        raise TransactionCleanupError(
            "UNREVIEWED_LIFECYCLE_BINDING",
            "The execution contract declares a lifecycle companion without a packaged binding.",
            details={"api": api, "companion_uris": declared_companions},
        )

    if api in _CLOSERS:
        base = {
            "contract": CLEANUP_SPEC_CONTRACT,
            "api": api,
            "lifecycle_action": "closer",
            "lifecycle_strategy": "not_required",
            "cleanup_requirement": "not_required",
            "companion_request": None,
            "binding": {"kind": "none", "materialized": True},
            "warnings": [],
            "automatic_cleanup": False,
            "automatic_retry": False,
        }
        return _seal_spec(base)

    base = {
        "contract": CLEANUP_SPEC_CONTRACT,
        "api": api,
        "lifecycle_action": "none",
        "lifecycle_strategy": "not_required",
        "cleanup_requirement": "not_required",
        "companion_request": None,
        "binding": {"kind": "none", "materialized": True},
        "warnings": [],
        "automatic_cleanup": False,
        "automatic_retry": False,
    }
    return _seal_spec(base)


def project_transaction_cleanup(
    spec: Mapping[str, Any],
    *,
    phase: str,
    execution_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a sealed cleanup specification into one transaction phase.

    ``execution_result`` is ignored for request-bound companions, preventing a
    result payload from replacing the user's confirmed cleanup identity.  It is
    consulted only for ``transport.create`` and only at post-execution phases.
    """

    spec_copy = _validate_and_copy_spec(spec)
    if phase not in CLEANUP_PHASES:
        raise TransactionCleanupError(
            "INVALID_CLEANUP_PHASE",
            f"Unsupported cleanup projection phase {phase!r}.",
            details={"supported_phases": sorted(CLEANUP_PHASES)},
        )
    result_copy = (
        _require_json_object(execution_result, path="execution_result")
        if execution_result is not None
        else None
    )

    lifecycle_action = spec_copy["lifecycle_action"]
    if lifecycle_action != "opener":
        status = "not_required"
    elif spec_copy["cleanup_requirement"] == "available_reversal":
        status = "unknown" if phase == "indeterminate" else "available_reversal"
    elif phase == "preview":
        status = "not_started"
    elif phase == "indeterminate":
        status = "unknown"
    else:
        status = "pending"

    companion_request = _strict_json_copy(
        spec_copy["companion_request"],
        path="spec.companion_request",
    )
    binding = _require_json_object(spec_copy["binding"], path="spec.binding")
    if (
        lifecycle_action == "opener"
        and binding.get("kind") == "execution_result"
        and phase != "preview"
        and result_copy is not None
    ):
        transport_id = _transport_id_from_execution_result(result_copy)
        if not isinstance(companion_request, dict):
            raise TransactionCleanupError(
                "INVALID_CLEANUP_SPEC",
                "A delayed transport binding requires a companion request object.",
            )
        companion_request["args"] = {"transport": transport_id}
        binding["materialized"] = True

    return {
        "contract": CLEANUP_PROJECTION_CONTRACT,
        "cleanup_spec_sha256": spec_copy["spec_sha256"],
        "api": spec_copy["api"],
        "phase": phase,
        "lifecycle_action": lifecycle_action,
        "lifecycle_strategy": spec_copy["lifecycle_strategy"],
        "cleanup_requirement": spec_copy["cleanup_requirement"],
        "status": status,
        "companion_request": companion_request,
        "binding": binding,
        "warnings": _strict_json_copy(spec_copy["warnings"], path="spec.warnings"),
        "automatic_cleanup": False,
        "automatic_retry": False,
    }


def _build_opener_binding(
    api: str,
    args: Mapping[str, Any],
    binding: _LifecycleBinding,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if binding.source_kind == "no_arguments":
        return {}, {"kind": "none", "materialized": True}
    if binding.source_kind == "request_argument":
        source_field = binding.source_field
        target_field = binding.target_field
        if source_field is None or target_field is None or source_field not in args:
            raise TransactionCleanupError(
                "CLEANUP_BINDING_MISSING",
                "The authorized immutable request lacks the argument required by its cleanup companion.",
                details={"api": api, "required_argument": source_field},
            )
        value = _strict_json_copy(args[source_field], path=f"args.{source_field}")
        return {target_field: value}, {
            "kind": "request_argument",
            "source": f"args.{source_field}",
            "target": f"args.{target_field}",
            "materialized": True,
        }
    if binding.source_kind == "execution_result":
        return {}, {
            "kind": "execution_result",
            "source": "execution_result.result.transport",
            "target": "args.transport",
            "materialized": False,
        }
    raise TransactionCleanupError(
        "INVALID_CLEANUP_SPEC",
        f"Unsupported packaged lifecycle binding kind {binding.source_kind!r}.",
    )


def _transport_id_from_execution_result(execution_result: Mapping[str, Any]) -> int:
    payload = execution_result.get("result")
    if not isinstance(payload, Mapping):
        raise TransactionCleanupError(
            "CLEANUP_BINDING_MISSING",
            "transport.create cleanup requires execution_result.result.transport.",
        )
    transport_id = payload.get("transport")
    if (
        isinstance(transport_id, bool)
        or not isinstance(transport_id, int)
        or not 0 <= transport_id <= UINT32_MAX
    ):
        raise TransactionCleanupError(
            "INVALID_TRANSPORT_ID",
            "transport.create returned an invalid cleanup transport ID.",
            details={"transport": transport_id, "minimum": 0, "maximum": UINT32_MAX},
        )
    return transport_id


def _seal_spec(base: Mapping[str, Any]) -> dict[str, Any]:
    payload = _require_json_object(base, path="cleanup_spec")
    payload["spec_sha256"] = _digest_without_seal(payload)
    return payload


def _validate_and_copy_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    payload = _require_json_object(spec, path="spec")
    if set(payload) != _SPEC_KEYS:
        raise TransactionCleanupError(
            "INVALID_CLEANUP_SPEC",
            "Cleanup specification fields do not match the packaged contract.",
            details={
                "missing": sorted(_SPEC_KEYS - set(payload)),
                "unexpected": sorted(set(payload) - _SPEC_KEYS),
            },
        )
    if payload.get("contract") != CLEANUP_SPEC_CONTRACT:
        raise TransactionCleanupError(
            "INVALID_CLEANUP_SPEC",
            "Cleanup specification contract is missing or unsupported.",
        )
    expected = payload.get("spec_sha256")
    actual = _digest_without_seal(payload)
    if not isinstance(expected, str) or expected != actual:
        raise TransactionCleanupError(
            "CLEANUP_SPEC_TAMPERED",
            "Cleanup specification digest does not match its contents.",
            details={"expected": expected, "actual": actual},
        )
    return payload


def _digest_without_seal(payload: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "spec_sha256"}
    canonical = json.dumps(
        unsigned,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _require_json_object(value: Any, *, path: str) -> dict[str, Any]:
    copied = _strict_json_copy(value, path=path)
    if not isinstance(copied, dict):
        raise TransactionCleanupError(
            "INVALID_CLEANUP_JSON",
            f"{path} must be a JSON object.",
            details={"path": path, "actual_type": type(value).__name__},
        )
    return copied


def _strict_json_copy(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TransactionCleanupError(
                "INVALID_CLEANUP_JSON",
                f"{path} contains a non-finite number.",
                details={"path": path},
            )
        return value
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TransactionCleanupError(
                    "INVALID_CLEANUP_JSON",
                    f"{path} contains a non-string object key.",
                    details={"path": path, "key_type": type(key).__name__},
                )
            copied[key] = _strict_json_copy(item, path=f"{path}.{key}")
        return copied
    if isinstance(value, list):
        return [
            _strict_json_copy(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise TransactionCleanupError(
        "INVALID_CLEANUP_JSON",
        f"{path} contains a non-JSON value.",
        details={"path": path, "actual_type": type(value).__name__},
    )


def transaction_cleanup_payload(
    prepared: Mapping[str, Any],
    *,
    phase: str,
    execution_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one immutable cleanup spec into its deterministic phase result."""

    raw_spec = prepared.get("cleanup")
    spec = dict(raw_spec) if isinstance(raw_spec, Mapping) else {"kind": "none"}
    if spec.get("contract") == CLEANUP_SPEC_CONTRACT:
        try:
            projection = project_transaction_cleanup(
                spec,
                phase=phase,
                execution_result=execution_result,
            )
        except TransactionCleanupError as exc:
            projection = {
                "contract": CLEANUP_PROJECTION_CONTRACT,
                "phase": phase,
                "status": "unknown",
                "automatic_cleanup": False,
                "automatic_retry": False,
                "error": exc.as_dict(),
            }
        return {
            "spec": spec,
            "status": projection["status"],
            "projection": projection,
        }

    kind = spec.get("kind")
    if phase == "indeterminate":
        status = "unknown"
    elif kind in {None, "none", "none-after-delete"}:
        status = "not_required"
    elif kind == "same_connection_cancel_on_inner_failure":
        status = (
            "armed_during_execution"
            if phase == "preview"
            else "handled_same_connection"
            if phase == "execution_cancelled"
            else "not_required"
        )
    elif phase == "preview":
        status = "not_started"
    else:
        status = "pending"
    projection = {
        "contract": CLEANUP_PROJECTION_CONTRACT,
        "phase": phase,
        "status": status,
        "kind": kind,
        "automatic_cleanup": bool(spec.get("automatic_cleanup") is True),
        "automatic_retry": False,
    }
    return {"spec": spec, "status": status, "projection": projection}


__all__ = [
    "CLEANUP_PHASES",
    "CLEANUP_PROJECTION_CONTRACT",
    "CLEANUP_SPEC_CONTRACT",
    "TransactionCleanupError",
    "build_transaction_cleanup_spec",
    "project_transaction_cleanup",
    "transaction_cleanup_payload",
]
