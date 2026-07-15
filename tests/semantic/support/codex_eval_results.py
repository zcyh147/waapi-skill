"""Strict one-line result envelope shared by semantic runner and graders."""

from __future__ import annotations

import json
from typing import Any


WAAPI_RESULT_PREFIX = "WAAPI_RESULT_JSON="


def parse_waapi_result_line(text: str) -> dict[str, Any] | None:
    """Parse exactly one strict JSON object with no surrounding text.

    Duplicate object keys and non-finite numeric constants are rejected at
    every nesting level so a model cannot satisfy two contradictory readings
    of the same final response.
    """

    if (
        not isinstance(text, str)
        or not text
        or text != text.strip()
        or len(text.splitlines()) != 1
        or not text.startswith(WAAPI_RESULT_PREFIX)
    ):
        return None
    encoded = text[len(WAAPI_RESULT_PREFIX) :]
    if not encoded:
        return None

    def reject_constant(constant: str) -> Any:
        raise ValueError(f"non-finite JSON constant {constant!r}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key {key!r}")
            value[key] = item
        return value

    try:
        payload = json.loads(
            encoded,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


__all__ = ["WAAPI_RESULT_PREFIX", "parse_waapi_result_line"]
