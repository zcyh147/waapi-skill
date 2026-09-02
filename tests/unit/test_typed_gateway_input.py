from __future__ import annotations

import os
import shlex
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from tests.semantic.support.typed_gateway_input import (
    create_object_lifecycle_business_preview,
    declared_business_object_handle,
    discovered_business_field_handle,
)
from wwise_waapi.platform_commands import encode_windows_model_argv


OBJECT_ID = "{11111111-1111-1111-1111-111111111111}"
DRAFT_ID = "od1-11111111111111111111111111111111"
AUTHORITY = "da1-1111111111111111111111111111111111111111"
OBJECT_HANDLE = "boh1-11111111111111111111111111111111"


def _copy_command(command: Sequence[str]) -> str:
    full_argv = ["python", "/packaged/skill/scripts/run.py", "gateway.py", *command]
    return (
        encode_windows_model_argv(full_argv)
        if os.name == "nt"
        else shlex.join(full_argv)
    )


def _copy_ready(
    command_prefix: Sequence[str],
    *,
    append: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "fixed_argv_prefix_copy": _copy_command(command_prefix),
        "fixed_argv_prefix_copy_instruction": {
            "contract": "waapi-skill.operation-draft-command-copy-instruction/v1",
            "source_field": "fixed_argv_prefix_copy",
            "action": "copy_verbatim_then_append_complete_typed_action_groups",
        },
        "append": list(append),
    }


def _copy_exact(command: Sequence[str]) -> dict[str, Any]:
    return {
        "copy_command": _copy_command(command),
        "copy_exactly": True,
    }


def test_real_gateway_adapter_follows_compact_copy_ready_business_continuations() -> None:
    seen: list[list[str]] = []

    def gateway(command: Sequence[str]) -> Mapping[str, Any]:
        argv = list(command)
        seen.append(argv)
        if argv == ["operation-schema", "object.setName"]:
            return {
                "business_adapter": {
                    "start": {
                        "next_command": {
                            "gateway_argv": ["draft-start", "object.setName"]
                        }
                    }
                }
            }
        if argv == ["draft-start", "object.setName"]:
            next_prefix = [
                "draft-bind-object",
                DRAFT_ID,
                "--task-authority",
                AUTHORITY,
                "--expected-revision",
                "1",
            ]
            return {
                "task_authority": AUTHORITY,
                "draft": {
                    "draft_id": DRAFT_ID,
                    "revision": 1,
                    "next_action_binding": {
                        "contract": "waapi-skill.business-draft-next-action/v1",
                        "object_binding": {
                            "by_id": _copy_ready(
                                next_prefix,
                                append=("--object-id", "<exact-object-guid>"),
                            )
                        },
                    },
                },
            }
        if argv[0] == "draft-bind-object":
            next_prefix = [
                "draft-declare-object-change",
                DRAFT_ID,
                "--task-authority",
                AUTHORITY,
                "--expected-revision",
                "2",
            ]
            assert argv[-2:] == ["--object-id", OBJECT_ID]
            return {
                "bound_object": {"handle": OBJECT_HANDLE},
                "draft": {
                    "draft_id": DRAFT_ID,
                    "revision": 2,
                    "next_action_binding": {
                        "contract": "waapi-skill.business-draft-next-action/v1",
                        "declaration": _copy_ready(
                            next_prefix,
                            append=(
                                "--object-handle",
                                "<bound-object-handle>",
                                "--new-name",
                                "<new-name>",
                            ),
                        ),
                    },
                },
            }
        if argv[0] == "draft-declare-object-change":
            next_command = [
                "draft-check",
                DRAFT_ID,
                "--task-authority",
                AUTHORITY,
                "--expected-revision",
                "3",
            ]
            return {
                "draft": {
                    "draft_id": DRAFT_ID,
                    "revision": 3,
                    "next_action_binding": {
                        "contract": "waapi-skill.business-draft-next-action/v1",
                        "completion_candidate": _copy_exact(next_command),
                    },
                }
            }
        if argv[0] == "draft-check":
            next_command = [
                "preview-from-draft",
                DRAFT_ID,
                "--task-authority",
                AUTHORITY,
                "--expected-revision",
                "4",
            ]
            return {
                "draft": {
                    "draft_id": DRAFT_ID,
                    "revision": 4,
                    "next_action_binding": {
                        "contract": "waapi-skill.business-draft-next-action/v1",
                        "completion_candidate": _copy_exact(next_command),
                    },
                }
            }
        if argv[0] == "preview-from-draft":
            return {
                "transaction_id": "tx1-compact-copy-ready",
                "next_command": {
                    "gateway_argv": [
                        "transaction-show",
                        "tx1-compact-copy-ready",
                        "--summary-only",
                    ]
                },
            }
        raise AssertionError(f"unexpected Gateway command: {argv!r}")

    preview = create_object_lifecycle_business_preview(
        gateway,
        version="2022.1",
        operation="object.setName",
        object_id=OBJECT_ID,
        new_name="Renamed",
    )

    assert preview["transaction_id"] == "tx1-compact-copy-ready"
    assert [command[0] for command in seen] == [
        "operation-schema",
        "draft-start",
        "draft-bind-object",
        "draft-declare-object-change",
        "draft-check",
        "preview-from-draft",
    ]


def test_declared_business_object_handle_uses_compact_exact_receipt() -> None:
    payload = {
        "draft": {
            "declared_object": {
                "declaration_id": "weather",
                "result_handle": "brh1-weather",
            }
        }
    }

    assert declared_business_object_handle(payload, "weather") == "brh1-weather"

    with pytest.raises(AssertionError, match="different declaration"):
        declared_business_object_handle(payload, "rain")


def test_discovered_business_field_handle_uses_deduplicated_meaning_projection() -> None:
    payload = {
        "candidate_projection": (
            "meaning_results[].candidates_without_duplicate_top_level_rows"
        ),
        "meaning_results": [
            {
                "meaning": "volume",
                "candidate_count": 1,
                "candidates": [{"handle": "bfh1-volume", "label": "Volume"}],
            }
        ],
    }

    assert discovered_business_field_handle(payload, "volume") == "bfh1-volume"

    with pytest.raises(AssertionError, match="exactly one candidate"):
        discovered_business_field_handle(
            {
                "candidate_projection": (
                    "meaning_results[].candidates_without_duplicate_top_level_rows"
                ),
                "meaning_results": [
                    {"meaning": "volume", "candidate_count": 0, "candidates": []}
                ]
            },
            "volume",
        )


def test_discovered_business_field_handle_accepts_reviewed_single_field_projection() -> None:
    payload = {
        "candidate_count": 1,
        "selection_required": False,
        "field_candidates": [
            {
                "handle": "bfh1-volume",
                "label": "Volume",
                "matched_meanings": ["volume"],
            }
        ],
    }

    assert discovered_business_field_handle(payload, "volume") == "bfh1-volume"
