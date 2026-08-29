from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from wwise_waapi.transactions import TransactionStore


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_soundengine_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


def _env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
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
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_VERSION": "2022.1",
        "WWISE_WAAPI_PORT": "31337",
    }


class _SoundEngineDraftClient:
    event_id = "{11111111-1111-1111-1111-111111111111}"

    def __init__(self, tmp_path: Path) -> None:
        project_root = tmp_path / "SampleProject"
        project_root.mkdir()
        self.project_file = project_root / "SampleProject.wproj"
        self.project_file.write_text("fixture", encoding="utf-8")
        self.event_name = "Play_Weather"
        self.soundengine_calls: list[str] = []

    def call(self, uri: str, args: object = None, options: object = None) -> object:
        if uri == "ak.wwise.core.getInfo":
            return {
                "displayName": "WwiseConsole",
                "isCommandLine": True,
                "apiVersion": 1,
                "platform": "macosx",
                "configuration": "release",
                "version": {
                    "year": 2022,
                    "major": 1,
                    "minor": 0,
                    "build": 1,
                    "displayName": "v2022.1.0.1",
                },
            }
        if uri == "ak.wwise.core.getProjectInfo":
            return {
                "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "name": "SampleProject",
                "path": str(self.project_file),
            }
        if uri == "ak.wwise.core.object.get" and isinstance(args, dict):
            requested = args.get("from", {}).get("id", [])
            if requested == [self.event_id]:
                return {
                    "return": [
                        {
                            "id": self.event_id,
                            "name": self.event_name,
                            "type": "Event",
                            "path": r"\Events\Default Work Unit\Play_Weather",
                        }
                    ]
                }
            raise AssertionError(f"unexpected object ids {requested!r}")
        if uri in {
            "ak.soundengine.registerGameObj",
            "ak.soundengine.unregisterGameObj",
        }:
            self.soundengine_calls.append(uri)
            return {}
        if uri == "ak.soundengine.postEvent":
            self.soundengine_calls.append(uri)
            return {"return": 1234}
        raise AssertionError(f"unexpected WAAPI call {uri}: {args!r} {options!r}")

    def disconnect(self) -> None:
        return None


def test_monitor_message_uses_one_business_draft_and_seals_native_preview(
    tmp_path: Path,
) -> None:
    operation = "ak.soundengine.postMsgMonitor"
    env = _env(tmp_path)
    state_dir = tmp_path / "state"
    message = 'Runtime "Weather"\nline 2; $HOME'

    code, schema = gateway.execute_gateway(
        ["--version", "2022.1", "request-schema", operation],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )
    assert code == 0, schema
    assert schema["input_shape"] == "business_declaration"
    assert schema["business_adapter"]["contract"] == (
        "waapi-skill.soundengine-control-business/v1"
    )
    assert schema["business_adapter"]["declaration"] == {
        "subcommand": "draft-declare-soundengine-plan",
        "required_fields": ["monitor_message"],
        "optional_fields": [],
        "field_types": {"monitor_message": "bounded_exact_monitor_message"},
        "input_forms": {
            "monitor_message": {
                "flag": "--monitor-message",
                "repeatable": False,
            }
        },
    }
    assert schema["continuation"] == {
        "subcommand": "draft-start",
        "gateway_argv": ["draft-start", operation],
        "copy_exactly": True,
        "append_arguments": "forbidden",
    }
    assert "fields" not in schema

    code, started = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    draft = started["draft"]
    authority = started["task_authority"]
    assert draft["next_action_binding"]["required_next_phase"] == (
        "declare_complete_soundengine_plan"
    )

    client = _SoundEngineDraftClient(tmp_path)
    code, declared = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "draft-declare-soundengine-plan",
            draft["draft_id"],
            "--task-authority",
            authority,
            "--expected-revision",
            str(draft["revision"]),
            "--monitor-message",
            message,
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, declared

    code, checked = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "draft-check",
            draft["draft_id"],
            "--task-authority",
            authority,
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, json.dumps(checked, indent=2, ensure_ascii=False)

    code, previewed = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "preview-from-draft",
            draft["draft_id"],
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked["draft"]["revision"]),
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, previewed
    artifact = TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact
    assert artifact["request"]["arguments"] == {
        "api": operation,
        "args": {"message": message},
        "options": {},
    }
    assert artifact["prepared_operation"]["verification_plan"]["kind"] == (
        "result-schema"
    )


def test_register_game_object_derives_native_id_and_binds_cleanup(
    tmp_path: Path,
) -> None:
    operation = "ak.soundengine.registerGameObj"
    env = _env(tmp_path)
    state_dir = tmp_path / "state"

    code, schema = gateway.execute_gateway(
        ["--version", "2022.1", "request-schema", operation],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )
    assert code == 0, schema
    assert schema["input_shape"] == "business_declaration"
    declaration = schema["business_adapter"]["declaration"]
    assert declaration["required_fields"] == ["game_object_name"]
    assert declaration["optional_fields"] == []
    assert declaration["input_forms"] == {
        "game_object_name": {
            "flag": "--game-object-name",
            "repeatable": False,
        }
    }

    code, started = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    draft = started["draft"]
    authority = started["task_authority"]
    client = _SoundEngineDraftClient(tmp_path)
    code, declared = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "draft-declare-soundengine-plan",
            draft["draft_id"],
            "--task-authority",
            authority,
            "--expected-revision",
            str(draft["revision"]),
            "--game-object-name",
            "Weather Listener",
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, declared
    code, checked = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "draft-check",
            draft["draft_id"],
            "--task-authority",
            authority,
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, json.dumps(checked, indent=2, ensure_ascii=False)
    code, previewed = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "preview-from-draft",
            draft["draft_id"],
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked["draft"]["revision"]),
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, previewed
    artifact = TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact
    native = artifact["request"]["arguments"]
    assert native["api"] == operation
    assert native["args"]["name"] == "Weather Listener"
    game_object_id = native["args"]["gameObject"]
    assert isinstance(game_object_id, int) and not isinstance(game_object_id, bool)
    assert 1 <= game_object_id <= 0x7FFFFFFFFFFFFFFF
    assert native["options"] == {}
    cleanup = artifact["prepared_operation"]["cleanup"]
    assert cleanup["companion_request"] == {
        "api": "ak.soundengine.unregisterGameObj",
        "args": {"gameObject": game_object_id},
        "options": {},
    }


def _preview_soundengine_plan(
    *,
    tmp_path: Path,
    state_dir: Path,
    env: dict[str, str],
    client: _SoundEngineDraftClient,
    operation: str,
    declaration: list[str],
    role_bindings: tuple[tuple[str, str], ...] = (),
) -> tuple[dict[str, object], dict[str, object]]:
    code, started = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    draft = started["draft"]
    authority = started["task_authority"]
    current = draft
    bound_handles: dict[str, str] = {}
    for role, object_id in role_bindings:
        code, bound = gateway.execute_gateway(
            [
                "--version",
                "2022.1",
                "--state-dir",
                str(state_dir),
                "draft-bind-object",
                draft["draft_id"],
                "--task-authority",
                authority,
                "--expected-revision",
                str(current["revision"]),
                "--role",
                role,
                "--object-id",
                object_id,
            ],
            env=env,
            client_factory=lambda _url: client,
        )
        assert code == 0, bound
        current = bound["draft"]
        bound_handles[role] = bound["bound_object"]["handle"]
    declaration = [
        bound_handles[value.removeprefix("<bound:").removesuffix(">")]
        if value.startswith("<bound:") and value.endswith(">")
        else value
        for value in declaration
    ]
    code, declared = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "draft-declare-soundengine-plan",
            draft["draft_id"],
            "--task-authority",
            authority,
            "--expected-revision",
            str(current["revision"]),
            *declaration,
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, declared
    code, checked = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "draft-check",
            draft["draft_id"],
            "--task-authority",
            authority,
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, json.dumps(checked, indent=2, ensure_ascii=False)
    code, previewed = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "preview-from-draft",
            draft["draft_id"],
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked["draft"]["revision"]),
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, previewed
    artifact = TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact
    return previewed, artifact


def _execute_and_verify_soundengine(
    *,
    state_dir: Path,
    env: dict[str, str],
    client: _SoundEngineDraftClient,
    previewed: dict[str, object],
) -> dict[str, object]:
    transaction_id = str(previewed["transaction_id"])
    snapshot = TransactionStore(state_dir).load_snapshot(transaction_id)
    code, confirmed = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "confirm",
            transaction_id,
            "--confirmation-token",
            snapshot.confirmation_token,
        ],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline confirm connected to {url}"),
    )
    assert code == 0, confirmed
    code, executed = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "execute",
            transaction_id,
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, executed
    code, verified = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "verify",
            transaction_id,
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, verified
    return verified


def test_registered_game_object_handle_drives_unregister_and_retires(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path)
    register_preview, register_artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.registerGameObj",
        declaration=["--game-object-name", "Weather Listener"],
    )
    registered = _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=register_preview,
    )
    business_result = registered["agent_result"]["business_result"]
    assert business_result["contract"] == (
        "waapi-skill.soundengine-control-result/v1"
    )
    game_object_handle = business_result["game_object_handle"]
    assert isinstance(game_object_handle, str)

    code, schema = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "request-schema",
            "ak.soundengine.unregisterGameObj",
        ],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )
    assert code == 0, schema
    assert schema["business_adapter"]["declaration"]["required_fields"] == [
        "game_object_handle"
    ]

    unregister_preview, unregister_artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.unregisterGameObj",
        declaration=["--game-object-handle", game_object_handle],
    )
    registered_id = register_artifact["request"]["arguments"]["args"]["gameObject"]
    assert unregister_artifact["request"]["arguments"] == {
        "api": "ak.soundengine.unregisterGameObj",
        "args": {"gameObject": registered_id},
        "options": {},
    }
    unregistered = _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=unregister_preview,
    )
    assert unregistered["agent_result"]["business_result"] == {
        "contract": "waapi-skill.soundengine-control-result/v1",
        "retired_game_object_handle_count": 1,
    }


def test_post_event_binds_event_and_uses_opaque_game_object_handle(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path)
    register_preview, register_artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.registerGameObj",
        declaration=["--game-object-name", "Weather Listener"],
    )
    registered = _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=register_preview,
    )
    game_object_handle = registered["agent_result"]["business_result"][
        "game_object_handle"
    ]

    operation = "ak.soundengine.postEvent"
    code, schema = gateway.execute_gateway(
        ["--version", "2022.1", "request-schema", operation],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )
    assert code == 0, schema
    contract = schema["business_adapter"]
    assert contract["binding"]["roles"] == ["event"]
    assert contract["declaration"]["required_fields"] == [
        "event_handle",
        "game_object_handle",
    ]

    previewed, artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation=operation,
        declaration=[
            "--event-handle",
            "<bound:event>",
            "--game-object-handle",
            game_object_handle,
        ],
        role_bindings=(("event", client.event_id),),
    )
    registered_id = register_artifact["request"]["arguments"]["args"]["gameObject"]
    assert artifact["request"]["arguments"] == {
        "api": operation,
        "args": {
            "event": client.event_id,
            "gameObject": registered_id,
        },
        "options": {},
    }
    resolved_roles = artifact["prepared_operation"]["resolved_roles"]
    assert resolved_roles["event"]["object"] == client.event_id
    assert resolved_roles["event"]["row"] == {
        "id": client.event_id,
        "name": "Play_Weather",
        "type": "Event",
        "path": r"\Events\Default Work Unit\Play_Weather",
    }


def test_post_event_stops_before_dispatch_when_bound_event_drifts(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path)
    register_preview, _ = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.registerGameObj",
        declaration=["--game-object-name", "Weather Listener"],
    )
    registered = _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=register_preview,
    )
    game_object_handle = registered["agent_result"]["business_result"][
        "game_object_handle"
    ]
    post_preview, _ = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.postEvent",
        declaration=[
            "--event-handle",
            "<bound:event>",
            "--game-object-handle",
            game_object_handle,
        ],
        role_bindings=(("event", client.event_id),),
    )
    transaction_id = str(post_preview["transaction_id"])
    snapshot = TransactionStore(state_dir).load_snapshot(transaction_id)
    code, confirmed = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "confirm",
            transaction_id,
            "--confirmation-token",
            snapshot.confirmation_token,
        ],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline confirm connected to {url}"),
    )
    assert code == 0, confirmed
    client.event_name = "Play_Weather_Renamed"
    calls_before = list(client.soundengine_calls)
    code, stopped = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "execute",
            transaction_id,
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 2, stopped
    assert stopped["status"] == "repreview_required"
    assert stopped["executed"] is False
    assert client.soundengine_calls == calls_before
