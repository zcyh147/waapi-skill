from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wwise_waapi.operation_drafts import (  # pyright: ignore[reportMissingImports]
    OperationDraftStore,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_operation_draft_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


DRAFT_ID_RE = re.compile(r"^od1-[0-9a-f]{32}$")
TASK_AUTHORITY_RE = re.compile(r"^da1-[0-9a-f]{40}$")


def gateway_env(tmp_path: Path) -> dict[str, str]:
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        "WWISE_VERSION": "2022.1",
    }


def execute(
    tmp_path: Path,
    *arguments: str,
) -> tuple[int, dict[str, Any]]:
    state_dir = tmp_path / "state"

    def fail_if_connected(url: str) -> None:
        raise AssertionError(f"Operation Draft commands must not connect to {url}")

    return waapi_gateway.execute_gateway(
        ["--state-dir", str(state_dir), *arguments],
        env=gateway_env(tmp_path),
        client_factory=fail_if_connected,
    )


def test_public_draft_lifecycle_is_offline_task_bound_and_cross_invocation(
    tmp_path: Path,
) -> None:
    start_code, started = execute(tmp_path, "draft-start", "object.set")

    assert start_code == 0
    assert started["ok"] is True
    assert started["command"] == "draft-start"
    assert started["offline"] is True
    draft_id = started["draft"]["draft_id"]
    task_authority = started["task_authority"]
    assert DRAFT_ID_RE.fullmatch(draft_id)
    assert TASK_AUTHORITY_RE.fullmatch(task_authority)
    assert started["draft"] == {
        "contract": "waapi-skill.operation-draft/v1",
        "draft_id": draft_id,
        "lifecycle_state": "editable",
        "revision": 1,
        "next_action_binding": {
            "contract": "waapi-skill.operation-draft-next-action/v1",
            "draft_id": draft_id,
            "expected_revision": 1,
            "one_action_only": True,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
            "fixed_full_argv_template": [
                "python",
                str(waapi_gateway.GATEWAY_RUNNER_PATH),
                "gateway.py",
                "draft-apply",
                draft_id,
                "--task-authority",
                "<task-authority-from-draft-start>",
                "--expected-revision",
                "1",
                "--compact",
                "--action-json",
                "<typed-action-json>",
            ],
            "replace_only": [
                "<task-authority-from-draft-start>",
                "<typed-action-json>",
            ],
            "copy_all_other_values_exactly": True,
        },
        "binding": {
            "operation": "object.set",
            "version": "2022.1",
            "schema_digest": (
                "2b6d3903c5b3e11618c3eaf0a3d5a26aa0045db26750320f3a8ce8c7da004cee"
            ),
        },
        "created_at": started["draft"]["created_at"],
        "updated_at": started["draft"]["updated_at"],
        "expires_at": started["draft"]["expires_at"],
        "current_facts": [],
        "request_options": {},
        "missing_fields": ["target"],
        "missing_fields_status": "incomplete",
        "allowed_actions": [
            "set_request_option",
            "clear_request_option",
            "add_target",
            "inspect",
            "cancel",
        ],
        "check": None,
        "seal": None,
    }
    assert started["draft"]["created_at"] == started["draft"]["updated_at"]
    assert started["draft"]["expires_at"] > started["draft"]["created_at"]
    assert task_authority not in json.dumps(started["session_context"])

    inspect_code, inspected = execute(
        tmp_path,
        "draft-inspect",
        draft_id,
        "--task-authority",
        task_authority,
    )

    assert inspect_code == 0
    assert inspected["draft"] == started["draft"]
    assert "task_authority" not in inspected
    assert task_authority not in json.dumps(inspected)

    cancel_code, cancelled = execute(
        tmp_path,
        "draft-cancel",
        draft_id,
        "--task-authority",
        task_authority,
        "--expected-revision",
        "1",
    )

    assert cancel_code == 0
    assert cancelled["draft"]["lifecycle_state"] == "cancelled"
    assert cancelled["draft"]["revision"] == 2
    assert cancelled["draft"]["current_facts"] == []
    assert cancelled["draft"]["missing_fields"] == []
    assert cancelled["draft"]["allowed_actions"] == []
    assert "task_authority" not in cancelled
    assert not (tmp_path / "state" / "transactions").exists()


def test_public_draft_denial_is_non_enumerable_and_does_not_echo_authority(
    tmp_path: Path,
) -> None:
    _start_code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    wrong_authority = "da1-" + ("0" * 40)

    wrong_code, wrong = execute(
        tmp_path,
        "draft-inspect",
        draft_id,
        "--task-authority",
        wrong_authority,
    )
    missing_code, missing = execute(
        tmp_path,
        "draft-inspect",
        "od1-00000000000000000000000000000000",
        "--task-authority",
        wrong_authority,
    )

    assert wrong_code == missing_code == 2
    assert wrong["error_code"] == "OPERATION_DRAFT_NOT_AVAILABLE"
    assert wrong == missing
    assert wrong_authority not in json.dumps(wrong)


def test_public_draft_start_rejects_invalid_registry_bindings_before_state_write(
    tmp_path: Path,
) -> None:
    for arguments, error_code in (
        (("draft-start", "missing.operation"), "UNKNOWN_OPERATION"),
        (("draft-start", "object.copy"), "OPERATION_BOUNDARY"),
    ):
        exit_code, payload = execute(tmp_path, *arguments)

        assert exit_code == 2
        assert payload["error_code"] == error_code

    assert not (tmp_path / "state").exists()


def test_public_draft_expiry_is_bounded_offline_and_does_not_create_preview(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest=(
            "2b6d3903c5b3e11618c3eaf0a3d5a26aa0045db26750320f3a8ce8c7da004cee"
        ),
        now=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )

    exit_code, payload = execute(
        tmp_path,
        "draft-inspect",
        started.draft_id,
        "--task-authority",
        started.task_authority,
    )

    assert exit_code == 2
    assert payload["error_code"] == "OPERATION_DRAFT_EXPIRED"
    assert payload["details"] == {}
    assert started.task_authority not in json.dumps(payload)
    assert not (tmp_path / "state" / "transactions").exists()
