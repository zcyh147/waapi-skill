"""Confidential provider calls reduced before generic serialization or evidence."""
from __future__ import annotations

from typing import Any, Callable, Mapping
import math

from .source_control_profiles import SET_PROVIDER, resolve_profile

MAX_PROTECTED_NATIVE_BYTES = 64 * 1024
MAX_PROTECTED_NATIVE_NODES = 4096


def _bounded_native(value: Any) -> None:
    # Conservative JSON-size upper bound without serializing confidential data.
    pending = [(value, 0)]
    nodes = 0
    size = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 24 or nodes > MAX_PROTECTED_NATIVE_NODES:
            raise ValueError
        size += 16
        if isinstance(item, str):
            if len(item) > MAX_PROTECTED_NATIVE_BYTES:
                raise ValueError
            size += 6 * len(item.encode("utf-8"))
        elif isinstance(item, Mapping):
            if len(item) > MAX_PROTECTED_NATIVE_NODES:
                raise ValueError
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError
                pending.extend(((key, depth + 1), (child, depth + 1)))
        elif isinstance(item, list):
            if len(item) > MAX_PROTECTED_NATIVE_NODES:
                raise ValueError
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, int) and not isinstance(item, bool):
            size += item.bit_length() // 3 + 2
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError
            size += 32
        elif item is not None and not isinstance(item, bool):
            raise ValueError
        if size > MAX_PROTECTED_NATIVE_BYTES:
            raise ValueError


def protected_provider_call(binding: Mapping[str, Any], *, version: str,
                            call: Callable[[Mapping[str, Any]], Any]) -> dict[str, Any]:
    """No native value or arbitrary exception text may leave this function."""
    try:
        from .builders.schema import validate_resolved_semantic_payload, validate_resolved_semantic_result
        native_args = resolve_profile(binding)
        validate_resolved_semantic_payload(SET_PROVIDER, native_args, {}, version=version)
    except Exception:
        return {"ok": False, "error_code": "PROTECTED_PROVIDER_PROFILE_INVALID"}
    try:
        native = call(native_args)
    except TimeoutError:
        return {"ok": False, "error_code": "TIMEOUT"}
    except Exception:
        return {"ok": False, "error_code": "PROTECTED_PROVIDER_CALL_FAILED"}
    finally:
        # Python cannot promise memory zeroization; no secret is persisted.
        del native_args
    try:
        _bounded_native(native)
    except Exception:
        return {"ok": False, "error_code": "PROTECTED_PROVIDER_RESULT_LIMIT"}
    try:
        validate_resolved_semantic_result(SET_PROVIDER, native, version=version)
        count = len(native["log"])
    except Exception:
        return {"ok": False, "error_code": "PROTECTED_PROVIDER_RESULT_INVALID"}
    return {"ok": True, "result": {"protected_native_result": True,
            "native_result_schema_valid": True, "native_log_count": count,
            "native_text_disclosed": False, "provider_identity_verified": False,
            "provider_effects_verified": False, "redaction": "entire_native_result_and_exception_text_suppressed"}}
