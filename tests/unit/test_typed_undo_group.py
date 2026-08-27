from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


VERSION = "2025.1"
SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location("waapi_typed_undo_gateway", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


def _env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": VERSION,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_WAAPI_PORT": "8080",
    }


def test_public_undo_schema_discloses_only_checked_business_draft_input(
    tmp_path: Path,
) -> None:
    offline = lambda url: pytest.fail(f"offline command connected to {url}")
    code, payload = gateway.execute_gateway(
        ["operation-schema", "waapi.undoGroup"],
        env=_env(tmp_path),
        client_factory=offline,
    )

    assert code == 0, payload
    adapter = payload["business_adapter"]
    assert adapter["declaration"]["subcommand"] == "draft-declare-undo-plan"
    assert adapter["declaration"]["child_input"] == (
        "ordered_checked_closed_draft_snapshot"
    )
    assert adapter["declaration"]["native_request_input"] == "forbidden"
    assert adapter["declaration"]["child_call_handle_input"] == "forbidden"
    assert adapter["declaration"]["action_ordering_grammar"] == "forbidden"
    assert "composer" not in payload


def test_undo_child_schema_command_is_not_public() -> None:
    parser = gateway.build_parser()
    command_action = next(
        action
        for action in parser._actions
        if getattr(action, "dest", None) == "command"
    )

    assert "undo-child-schema" not in command_action.choices


def test_undo_draft_rejects_legacy_draft_apply_before_durable_write(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    offline = lambda url: pytest.fail(f"offline command connected to {url}")
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", "waapi.undoGroup"],
        env=_env(tmp_path),
        client_factory=offline,
    )
    assert start_code == 0, started

    code, rejected = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-apply",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(started["draft"]["revision"]),
            "--facts",
            "--action",
            "set_display_name",
            "--display-name",
            "Legacy batch",
        ],
        env=_env(tmp_path),
        client_factory=offline,
    )

    assert code == 2
    assert "no longer accepts shallow draft-apply" in rejected["message"]
    record = gateway.OperationDraftStore(state_dir).inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )
    assert record.revision == started["draft"]["revision"]
