"""Test-only helpers for canonical compound Undo transaction requests.

The public Gateway accepts only verified Business Draft children. Lower-layer
transaction tests may still need the internal generic-child boundary, so this
helper constructs that canonical request without advertising a public route.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from wwise_waapi.compound_undo_business import build_compound_undo_child_snapshot
from wwise_waapi.operation_registry import parse_operation_request
from wwise_waapi.typed_requests import request_contract


def compound_undo_request(
    *,
    version: str,
    child_requests: Sequence[Mapping[str, Any]],
    display_name: str = "Program Undo Group",
) -> dict[str, Any]:
    """Wrap child requests for transaction-layer tests only."""

    calls: list[dict[str, Any]] = []
    for index, request in enumerate(child_requests, start=1):
        parsed = parse_operation_request(request, expected_version=version)
        if parsed.operation == "waapi.call":
            api = str(parsed.arguments["api"])
            calls.append(
                {
                    "schema_digest": request_contract(version, api).schema_digest,
                    "request": parsed.as_dict(),
                }
            )
            continue
        snapshot = build_compound_undo_child_snapshot(
            version=version,
            source_draft_id=f"od1-{index:032x}",
            source_revision=1,
            request=parsed.as_dict(),
        )
        calls.append(
            {
                "schema_digest": snapshot["child_schema_digest"],
                "request": snapshot["request"],
            }
        )
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "waapi.undoGroup",
        "arguments": {"display_name": display_name, "calls": calls},
    }


__all__ = ["compound_undo_request"]
