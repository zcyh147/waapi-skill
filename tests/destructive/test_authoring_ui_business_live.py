from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Mapping
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


def _preview_runtime_plan(
    operation: str,
    declaration_args: list[str],
    *,
    env: dict[str, str],
    state_dir: Path,
    target_id: str | None = None,
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
    current = draft
    arguments = list(declaration_args)
    if target_id is not None:
        bound = _call(
            [
                "draft-bind-object",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                str(current["revision"]),
                "--role",
                "target",
                "--object-id",
                target_id,
            ],
            env=env,
            state_dir=state_dir,
        )
        current = bound["draft"]
        bound_object = bound["bound_object"]
        assert isinstance(current, dict)
        assert isinstance(bound_object, dict)
        arguments = ["--target-handle", str(bound_object["handle"]), *arguments]
    declared = _call(
        [
            "draft-declare-runtime-control-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
            *arguments,
        ],
        env=env,
        state_dir=state_dir,
    )
    current = declared["draft"]
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
    current = checked["draft"]
    assert isinstance(current, dict)
    return _call(
        [
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
        ],
        env=env,
        state_dir=state_dir,
    )


def _preview_soundengine_plan(
    operation: str,
    declaration_args: list[str],
    *,
    env: dict[str, str],
    state_dir: Path,
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
            "draft-declare-soundengine-plan",
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
    current = checked["draft"]
    assert isinstance(current, dict)
    return _call(
        [
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
        ],
        env=env,
        state_dir=state_dir,
    )


def _preview_zero_input_plan(
    operation: str,
    *,
    env: dict[str, str],
    state_dir: Path,
) -> dict[str, object]:
    schema = _call(
        ["request-schema", operation],
        env=env,
        state_dir=state_dir,
    )
    assert schema["input_shape"] == "zero"
    continuation = schema["continuation"]
    assert isinstance(continuation, dict)
    assert continuation["subcommand"] == "typed-zero-call"
    gateway_argv = continuation["gateway_argv"]
    assert isinstance(gateway_argv, list)
    assert all(isinstance(value, str) for value in gateway_argv)
    return _call(
        list(gateway_argv),
        env=env,
        state_dir=state_dir,
    )


def _runtime_business_result(verified: Mapping[str, object]) -> Mapping[str, object]:
    agent_result = verified.get("agent_result")
    assert isinstance(agent_result, Mapping), verified
    business_result = agent_result.get("business_result")
    assert isinstance(business_result, Mapping), agent_result
    return business_result


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


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_business_profiler_and_transport_lifecycle_on_authoring(
    tmp_path: Path,
) -> None:
    version = os.environ["WWISE_VERSION"]
    assert version in {"2022.1", "2025.1"}
    env = _gateway_env(tmp_path, version=version)
    state_dir = tmp_path / "runtime-authoring-state"

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

    event_id = "{1AF4A3BA-682A-4664-AC31-45C0F0E6F8D1}"
    event = _call(
        ["query-object", "--exact-id", event_id],
        env=env,
        state_dir=state_dir,
    )
    assert event["count"] == 1
    rows = event["objects"]
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0]["type"] == "Event"

    profiler_enabled = False
    transport_handle: str | None = None
    primary_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    try:
        profiler = _preview_runtime_plan(
            "ak.wwise.core.profiler.enableProfilerData",
            ["--capture-data", "voices", "enable"],
            env=env,
            state_dir=state_dir,
        )
        # Cleanup ownership begins before execute: the call can succeed even if
        # its weak result-schema verification later fails.
        profiler_enabled = True
        profiler_verified = _execute_and_verify(
            profiler,
            env=env,
            state_dir=state_dir,
        )
        assert profiler_verified["state"] == (
            TransactionState.RESULT_SCHEMA_CHECKED.value
        )
        created = _preview_runtime_plan(
            "ak.wwise.core.transport.create",
            [],
            env=env,
            state_dir=state_dir,
            target_id=event_id,
        )
        created_verified = _execute_and_verify(
            created,
            env=env,
            state_dir=state_dir,
        )
        assert created_verified["state"] == TransactionState.VERIFIED.value
        create_result = _runtime_business_result(created_verified)
        transport_handle = str(create_result["transport_handle"])

        state = _call(
            [
                "core-call",
                "ak.wwise.core.transport.getState",
                "--transport-handle",
                transport_handle,
            ],
            env=env,
            state_dir=state_dir,
        )
        assert state["agent_result"]["transport_handle"] == transport_handle
        assert state["agent_result"]["state"] in {"playing", "paused", "stopped"}

        stopped = _preview_runtime_plan(
            "ak.wwise.core.transport.executeAction",
            [
                "--audition-action",
                "stop",
                "--transport-scope",
                "one-transport",
                "--transport-handle",
                transport_handle,
            ],
            env=env,
            state_dir=state_dir,
        )
        stopped_verified = _execute_and_verify(
            stopped,
            env=env,
            state_dir=state_dir,
        )
        assert stopped_verified["state"] == (
            TransactionState.RESULT_SCHEMA_CHECKED.value
        )

        destroyed = _preview_runtime_plan(
            "ak.wwise.core.transport.destroy",
            ["--transport-handle", transport_handle],
            env=env,
            state_dir=state_dir,
        )
        destroyed_verified = _execute_and_verify(
            destroyed,
            env=env,
            state_dir=state_dir,
        )
        assert destroyed_verified["state"] == TransactionState.VERIFIED.value
        assert _runtime_business_result(destroyed_verified)[
            "retired_transport_handle_count"
        ] == 1
        transport_handle = None
    except BaseException as exc:
        primary_error = exc
    finally:
        if transport_handle is not None:
            try:
                cleanup = _preview_runtime_plan(
                    "ak.wwise.core.transport.destroy",
                    ["--transport-handle", transport_handle],
                    env=env,
                    state_dir=state_dir,
                )
                _execute_and_verify(cleanup, env=env, state_dir=state_dir)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if profiler_enabled:
            try:
                cleanup = _preview_runtime_plan(
                    "ak.wwise.core.profiler.enableProfilerData",
                    ["--capture-data", "voices", "disable"],
                    env=env,
                    state_dir=state_dir,
                )
                _execute_and_verify(cleanup, env=env, state_dir=state_dir)
            except BaseException as exc:
                cleanup_errors.append(exc)
    if primary_error is not None or cleanup_errors:
        raise BaseExceptionGroup(
            "Authoring runtime lifecycle or bounded cleanup failed",
            [*([primary_error] if primary_error is not None else []), *cleanup_errors],
        )


@pytest.mark.live
@pytest.mark.destructive
def test_soundengine_business_runtime_and_spatial_families_on_authoring(
    tmp_path: Path,
) -> None:
    version = os.environ["WWISE_VERSION"]
    assert version in {"2022.1", "2025.1"}
    env = _gateway_env(tmp_path, version=version)
    state_dir = tmp_path / "soundengine-authoring-state"

    status = _call(["status"], env=env, state_dir=state_dir)
    assert status["is_command_line"] is False
    project = status["project"]
    assert isinstance(project, dict)
    assert Path(localize_waapi_host_path(project["path"])).resolve(
        strict=True
    ) == Path(env["WWISE_AUTHORING_SANDBOX_PROJECT"]).resolve(strict=True)

    handles: list[str] = []
    primary_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []

    def complete(operation: str, declaration: list[str]) -> dict[str, object]:
        return _execute_and_verify(
            _preview_soundengine_plan(
                operation,
                declaration,
                env=env,
                state_dir=state_dir,
            ),
            env=env,
            state_dir=state_dir,
        )

    try:
        monitor = complete(
            "ak.soundengine.postMsgMonitor",
            ["--monitor-message", f"waapi-skill authoring probe {version}"],
        )
        assert monitor["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value

        for name in ("WAAPI Skill Emitter", "WAAPI Skill Listener"):
            registered = complete(
                "ak.soundengine.registerGameObj",
                ["--game-object-name", name],
            )
            business = _runtime_business_result(registered)
            handle = str(business["game_object_handle"])
            assert handle.startswith("goh1-")
            handles.append(handle)
        emitter, listener = handles

        operations = (
            (
                "ak.soundengine.setPosition",
                [
                    "--game-object-handle", emitter,
                    "--position-frame", "1", "2", "3", "1", "0", "0", "0", "1", "0",
                ],
            ),
            (
                "ak.soundengine.setMultiplePositions",
                [
                    "--game-object-handle", emitter,
                    "--multi-position-mode", "MultiSources",
                    "--position-frame", "1", "2", "3", "1", "0", "0", "0", "1", "0",
                    "--position-frame", "4", "5", "6", "1", "0", "0", "0", "1", "0",
                ],
            ),
            (
                "ak.soundengine.setDefaultListeners",
                ["--listener-handle", listener],
            ),
            (
                "ak.soundengine.setListeners",
                ["--emitter-handle", emitter, "--listener-handle", listener],
            ),
            (
                "ak.soundengine.setObjectObstructionAndOcclusion",
                [
                    "--emitter-handle", emitter,
                    "--listener-handle", listener,
                    "--obstruction-percent", "25",
                    "--occlusion-percent", "50",
                ],
            ),
            (
                "ak.soundengine.setScalingFactor",
                ["--game-object-handle", emitter, "--attenuation-scale-percent", "150"],
            ),
            (
                "ak.soundengine.setGameObjectOutputBusVolume",
                [
                    "--emitter-handle", emitter,
                    "--listener-handle", listener,
                    "--volume-db", "-6",
                ],
            ),
            (
                "ak.soundengine.setListenerSpatialization",
                [
                    "--listener-handle", listener,
                    "--spatialization", "enabled",
                    "--channel-layout", "5.1",
                    "--speaker-offset-db", "C", "-3",
                ],
            ),
            (
                "ak.soundengine.stopAll",
                ["--game-object-handle", emitter],
            ),
        )
        for operation, declaration in operations:
            verified = complete(operation, declaration)
            assert verified["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    except BaseException as exc:
        primary_error = exc
    finally:
        for handle in reversed(handles):
            try:
                unregistered = complete(
                    "ak.soundengine.unregisterGameObj",
                    ["--game-object-handle", handle],
                )
                assert _runtime_business_result(unregistered)[
                    "retired_game_object_handle_count"
                ] == 1
            except BaseException as exc:
                cleanup_errors.append(exc)
    if primary_error is not None or cleanup_errors:
        raise BaseExceptionGroup(
            "SoundEngine Authoring workflow or bounded game-object cleanup failed",
            [*([primary_error] if primary_error is not None else []), *cleanup_errors],
        )


@pytest.mark.live
@pytest.mark.destructive
def test_runtime_business_remote_connection_lifecycle_on_authoring(
    tmp_path: Path,
) -> None:
    version = os.environ["WWISE_VERSION"]
    assert version == "2022.1"
    env = _gateway_env(tmp_path, version=version)
    state_dir = tmp_path / "remote-authoring-state"

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

    remote_host = os.environ["WWISE_AUTHORING_REMOTE_HOST"]
    application_name = os.environ["WWISE_AUTHORING_REMOTE_APPLICATION_NAME"]
    command_port = int(os.environ["WWISE_AUTHORING_REMOTE_COMMAND_PORT"])
    assert remote_host.strip() == remote_host and remote_host
    assert application_name.strip() == application_name and application_name
    assert 1 <= command_port <= 65535

    remote_may_be_connected = False
    primary_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    try:
        connect = _preview_runtime_plan(
            "ak.wwise.core.remote.connect",
            [
                "--remote-host",
                remote_host,
                "--application-name",
                application_name,
                "--command-port",
                str(command_port),
            ],
            env=env,
            state_dir=state_dir,
        )
        # Own cleanup before dispatch: connect can take effect even when its
        # non-retried response or later verification is ambiguous.
        remote_may_be_connected = True
        connected = _execute_and_verify(
            connect,
            env=env,
            state_dir=state_dir,
        )
        assert connected["state"] == TransactionState.VERIFIED.value

        disconnect = _preview_zero_input_plan(
            "ak.wwise.core.remote.disconnect",
            env=env,
            state_dir=state_dir,
        )
        disconnected = _execute_and_verify(
            disconnect,
            env=env,
            state_dir=state_dir,
        )
        assert disconnected["state"] == TransactionState.VERIFIED.value
        remote_may_be_connected = False
    except BaseException as exc:
        primary_error = exc
    finally:
        if remote_may_be_connected:
            try:
                cleanup = _preview_zero_input_plan(
                    "ak.wwise.core.remote.disconnect",
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
            "Authoring Remote lifecycle failed and bounded disconnect also failed",
            [primary_error, cleanup_error],
        )
    if primary_error is not None:
        raise primary_error
    if cleanup_error is not None:
        raise cleanup_error
