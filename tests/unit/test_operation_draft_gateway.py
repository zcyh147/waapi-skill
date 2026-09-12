from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from wwise_waapi.canonical import canonical_json_bytes

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


@pytest.mark.parametrize("age_days", [0, 3])
def test_gateway_new_draft_checks_retention_before_historical_business_content(
    tmp_path: Path, age_days: int,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    old = store.start(
        operation="object.create", version="2025.1",
        schema_digest="a" * 64, composer_digest="b" * 64,
        now=datetime.now(timezone.utc) - timedelta(days=age_days),
    )
    # Historical pre-business object.create, with intact storage digests/audit.
    record = replace(old.record, composition={
        "contract": "waapi-skill.operation-composition/v1",
        "typed_request_schema_digest": "c" * 64,
        "facts": [],
    })
    old_path = store.records_dir / f"{old.draft_id}.json"
    before = canonical_json_bytes(record.as_durable_dict())
    old_path.write_bytes(before)

    code, result = execute(tmp_path, "draft-start", "object.set")

    if age_days == 3:
        assert code == 0, result
        assert result["draft"]["binding"]["operation"] == "object.set"
        assert result["draft"]["binding"]["version"] == "2022.1"
        assert not old_path.exists()
    else:
        assert code == 2, result
        assert result["error_code"] == "OPERATION_DRAFT_STORAGE_CORRUPTION"
        assert result["details"]["draft_id"] == old.draft_id
        assert result["details"]["stage"] == "business_content"
        assert old_path.read_bytes() == before
    assert not (tmp_path / "state" / "transactions").exists()


def test_public_business_draft_lifecycle_is_offline_task_bound_and_cross_invocation(
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

    draft = started["draft"]
    assert draft["lifecycle_state"] == "editable"
    assert draft["revision"] == 1
    assert draft["binding"]["operation"] == "object.set"
    assert draft["binding"]["version"] == "2022.1"
    assert draft["business_revision"] == 0
    assert draft["declarations"] == []
    assert draft["missing_fields"] == ["business_declaration"]
    assert draft["allowed_actions"] == ["bind-object"]
    binding = draft["next_action_binding"]
    assert binding["contract"] == "waapi-skill.business-draft-next-action/v1"
    assert binding["required_next_phase"] == "bind_existing_business_object"
    assert binding["responsibility_split"] == {
        "agent": "natural_language_to_closed_high_level_business_facts",
        "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
    }
    assert "draft-apply" not in json.dumps(binding)
    assert task_authority not in json.dumps(started["session_context"])

    inspect_code, inspected = execute(
        tmp_path,
        "draft-inspect",
        draft_id,
        "--task-authority",
        task_authority,
    )

    assert inspect_code == 0
    assert "task_authority" not in inspected
    assert task_authority not in json.dumps(inspected)
    inspected_binding = inspected["draft"]["next_action_binding"]
    assert "<task-authority-from-draft-start>" in json.dumps(inspected_binding)
    assert inspected["draft"]["binding"] == draft["binding"]
    assert inspected["draft"]["declarations"] == []

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
    assert cancelled["draft"]["declarations"] == []
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
    exit_code, payload = execute(tmp_path, "draft-start", "missing.operation")

    assert exit_code == 2
    assert payload["error_code"] == "UNKNOWN_OPERATION"

    assert not (tmp_path / "state").exists()


def test_public_draft_expiry_is_bounded_offline_and_does_not_create_preview(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest=(
            "c1545e0d05010c77fb80cd859f4cb6c0b77ad313a332b1241be94f9a43d11c6a"
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
