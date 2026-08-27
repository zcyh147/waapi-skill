from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid

import pytest  # pyright: ignore[reportMissingImports]


if (
    os.getenv("WWISE_LIVE") != "1"
    or os.getenv("WWISE_DESTRUCTIVE") != "1"
    or os.getenv("WWISE_AUTHORING_LIVE") != "1"
):
    pytest.skip(
        "WWISE_LIVE=1, WWISE_DESTRUCTIVE=1, and WWISE_AUTHORING_LIVE=1 "
        "are required for externally launched Authoring business tests",
        allow_module_level=True,
    )


from wwise_waapi.transactions import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    TransactionState,
    TransactionStore,
)
from wwise_waapi.host_paths import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    localize_waapi_host_path,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = REPO_ROOT / "skills" / "waapi-skill" / "scripts" / "gateway.py"
GATEWAY_SPEC = importlib.util.spec_from_file_location(
    "waapi_authoring_ui_business_live_gateway",
    GATEWAY_PATH,
)
assert GATEWAY_SPEC is not None and GATEWAY_SPEC.loader is not None
gateway = importlib.util.module_from_spec(GATEWAY_SPEC)
sys.modules[GATEWAY_SPEC.name] = gateway
GATEWAY_SPEC.loader.exec_module(gateway)


def _gateway_env(tmp_path: Path, *, version: str) -> dict[str, str]:
    sandbox = Path(os.environ["WWISE_AUTHORING_SANDBOX_PROJECT"]).resolve(
        strict=True
    )
    if sandbox.suffix.casefold() != ".wproj":
        raise AssertionError("WWISE_AUTHORING_SANDBOX_PROJECT must be a .wproj")
    source = Path(os.environ["WWISE_SAMPLE_PROJECT_PATH"]).resolve(strict=True)
    if sandbox == source or source.parent == sandbox.parent:
        raise AssertionError("Authoring business tests require a copied sandbox")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": version,
                "waapi_host": os.getenv("WWISE_WAAPI_HOST", "127.0.0.1"),
                "waapi_port": int(os.getenv("WWISE_WAAPI_PORT", "8080")),
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        **os.environ,
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_VERSION": version,
    }


def _call(
    argv: list[str],
    *,
    env: dict[str, str],
    state_dir: Path,
) -> dict[str, object]:
    code, payload = gateway.execute_gateway(
        ["--state-dir", str(state_dir), *argv],
        env=env,
    )
    assert code == 0, json.dumps(payload, indent=2, ensure_ascii=False)
    assert payload["ok"] is True
    return payload


def _preview_business_plan(
    operation: str,
    declaration_args: list[str],
    *,
    env: dict[str, str],
    state_dir: Path,
    registration_key: str | None = None,
) -> dict[str, object]:
    started = _call(
        ["draft-start", operation],
        env=env,
        state_dir=state_dir,
    )
    draft = started["draft"]
    assert isinstance(draft, dict)
    draft_id = str(draft["draft_id"])
    authority = str(started["task_authority"])
    declared = _call(
        [
            "draft-declare-ui-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(draft["revision"]),
            *declaration_args,
        ],
        env=env,
        state_dir=state_dir,
    )
    current = declared["draft"]
    assert isinstance(current, dict)
    if operation == "ui.commands.register":
        assert registration_key is not None
        current = _call(
            [
                "draft-add-ui-command",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                str(current["revision"]),
                "--key",
                registration_key,
                "--display-name",
                "WAAPI Skill live notification",
                "--handler-kind",
                "notification",
            ],
            env=env,
            state_dir=state_dir,
        )["draft"]
        assert isinstance(current, dict)
    checked = _call(
        [
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
        ],
        env=env,
        state_dir=state_dir,
    )
    checked_draft = checked["draft"]
    assert isinstance(checked_draft, dict)
    return _call(
        [
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked_draft["revision"]),
            "--apply",
        ],
        env=env,
        state_dir=state_dir,
    )


def _execute_and_verify(
    preview: dict[str, object],
    *,
    env: dict[str, str],
    state_dir: Path,
) -> dict[str, object]:
    transaction_id = str(preview["transaction_id"])
    snapshot = TransactionStore(state_dir).load_snapshot(transaction_id)
    _call(
        [
            "confirm",
            transaction_id,
            "--confirmation-token",
            snapshot.confirmation_token,
        ],
        env=env,
        state_dir=state_dir,
    )
    executed = _call(
        ["execute", transaction_id],
        env=env,
        state_dir=state_dir,
    )
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    return _call(
        ["verify", transaction_id],
        env=env,
        state_dir=state_dir,
    )


@pytest.mark.live
@pytest.mark.destructive
def test_authoring_ui_business_capture_execute_register_unregister(
    tmp_path: Path,
) -> None:
    version = os.environ["WWISE_VERSION"]
    assert version in {"2022.1", "2025.1"}
    env = _gateway_env(tmp_path, version=version)
    state_dir = tmp_path / "authoring-ui-state"
    key = f"live-notification-{uuid.uuid4().hex}"

    status = _call(["status"], env=env, state_dir=state_dir)
    assert status["is_command_line"] is False
    project = status["project"]
    assert isinstance(project, dict)
    observed_project = Path(
        localize_waapi_host_path(project["path"])
    ).resolve(strict=True)
    expected_project = Path(
        env["WWISE_AUTHORING_SANDBOX_PROJECT"]
    ).resolve(strict=True)
    assert observed_project == expected_project

    schema_code, schema = gateway.execute_gateway(
        ["operation-schema", "ui.commands.register"],
        env=env,
    )
    assert schema_code == 0, schema
    assert schema["operation"]["input_mode"] == "business_declaration"
    assert "typed_operation" not in schema
    assert "composer" not in schema

    capture = _preview_business_plan(
        "ui.captureScreen",
        [],
        env=env,
        state_dir=state_dir,
    )
    capture_verified = _execute_and_verify(
        capture,
        env=env,
        state_dir=state_dir,
    )
    assert capture_verified["state"] == (
        TransactionState.RESULT_SCHEMA_CHECKED.value
    )

    command = _preview_business_plan(
        "ui.commands.execute",
        ["--command-id", "SaveProject"],
        env=env,
        state_dir=state_dir,
    )
    command_verified = _execute_and_verify(
        command,
        env=env,
        state_dir=state_dir,
    )
    assert command_verified["state"] == (
        TransactionState.RESULT_SCHEMA_CHECKED.value
    )

    registration = _preview_business_plan(
        "ui.commands.register",
        ["--command-count", "1"],
        env=env,
        state_dir=state_dir,
        registration_key=key,
    )
    registration_may_exist = False
    primary_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    try:
        # Own cleanup before dispatch: a failed/ambiguous verification may follow
        # a successful non-retried registration call.
        registration_may_exist = True
        registration_verified = _execute_and_verify(
            registration,
            env=env,
            state_dir=state_dir,
        )
        assert registration_verified["state"] == TransactionState.VERIFIED.value
        unregister = _preview_business_plan(
            "ui.commands.unregister",
            ["--registered-command-key", key],
            env=env,
            state_dir=state_dir,
        )
        unregister_verified = _execute_and_verify(
            unregister,
            env=env,
            state_dir=state_dir,
        )
        assert unregister_verified["state"] == TransactionState.VERIFIED.value
        registration_may_exist = False
    except BaseException as exc:  # preserve interruption/failure through cleanup
        primary_error = exc
    finally:
        if registration_may_exist:
            try:
                cleanup = _preview_business_plan(
                    "ui.commands.unregister",
                    ["--registered-command-key", key],
                    env=env,
                    state_dir=state_dir,
                )
                cleanup_verified = _execute_and_verify(
                    cleanup,
                    env=env,
                    state_dir=state_dir,
                )
                assert cleanup_verified["state"] == TransactionState.VERIFIED.value
            except BaseException as exc:
                cleanup_error = exc
    if primary_error is not None and cleanup_error is not None:
        raise BaseExceptionGroup(
            "Authoring UI registration failed and bounded cleanup also failed",
            [primary_error, cleanup_error],
        )
    if primary_error is not None:
        raise primary_error
    if cleanup_error is not None:
        raise cleanup_error
