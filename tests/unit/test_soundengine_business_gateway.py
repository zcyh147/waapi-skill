from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from wwise_waapi.capabilities import CapabilityCatalog
from wwise_waapi.soundengine_business_contracts import (
    soundengine_control_business_operations,
    soundengine_control_business_read_operations,
    soundengine_control_business_versions,
)
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


@pytest.mark.parametrize(
    "version",
    ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
)
def test_all_reflected_soundengine_rows_use_one_deep_business_route(
    tmp_path: Path,
    version: str,
) -> None:
    expected = {
        capability.uri
        for capability in CapabilityCatalog().entries(version)
        if capability.item_type == "function"
        and capability.uri.startswith("ak.soundengine.")
    }
    actual = {
        operation
        for operation in soundengine_control_business_operations()
        if version in soundengine_control_business_versions(operation)
    }
    assert actual == expected
    for operation in sorted(expected):
        code, schema = gateway.execute_gateway(
            ["--version", version, "request-schema", operation],
            env=_env(tmp_path, version),
            client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
        )
        assert code == 0, schema
        assert schema["input_shape"] == "business_declaration"
        assert schema["native_request_fields_disclosed"] is False
        assert "fields" not in schema
        assert schema["business_adapter"]["legacy_typed_call_public"] is False
        if operation in soundengine_control_business_read_operations():
            assert schema["business_adapter"]["execution_shape"] == "bounded_read"
            assert schema["continuation"]["subcommand"] == "core-call"
        else:
            assert schema["business_adapter"]["execution_shape"] == "draft_mutation"
            assert schema["continuation"] == {
                "subcommand": "draft-start",
                "gateway_argv": ["draft-start", operation],
                "copy_exactly": True,
                "append_arguments": "forbidden",
            }


def test_operations_catalog_lists_all_soundengine_business_routes(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        ["operations"],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline operations connected to {url}"),
    )
    assert code == 0, payload
    all_rows = {
        row["api"]: row
        for row in payload["request_schema_routes"]
    }
    rows = {
        api: row
        for api, row in all_rows.items()
        if api.startswith("ak.soundengine.")
    }
    assert set(rows) == soundengine_control_business_operations()
    assert len(rows) == 26
    assert rows["ak.soundengine.loadBank"]["supported_versions"] == [
        "2023.1",
        "2024.1",
        "2025.1",
    ]
    assert rows["ak.soundengine.postMsgMonitor"]["intent"] == (
        "post one exact message to the runtime Profiler Capture Log"
    )
    assert all_rows["ak.wwise.core.log.addItem"]["intent"] == (
        "add one message to a named Authoring Log view"
    )
    assert payload["request_schema_command_template"] == [
        "request-schema",
        "<api>",
    ]
    assert all("next_command" not in row for row in rows.values())


def test_event_draft_exposes_one_copy_ready_exact_name_binding(
    tmp_path: Path,
) -> None:
    operation = "ak.soundengine.executeActionOnEvent"
    code, started = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "--state-dir",
            str(tmp_path / "state"),
            "draft-start",
            operation,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )

    assert code == 0, started
    next_action = started["draft"]["next_action_binding"]
    assert next_action["required_next_phase"] == "bind_next_soundengine_role"
    binding = next_action["object_binding"]
    assert binding["next_role"] == "event"
    assert binding["direct_query_before_binding"] == "forbidden"
    exact_name = binding["by_exact_name"]
    assert exact_name["fixed_argv_prefix"][-4:] == [
        "--role",
        "event",
        "--exact-type-name",
        "Event",
    ]
    assert exact_name["append"] == ["<exact-event-name>"]
    assert "query" not in binding["selection_rule"]


def _env(tmp_path: Path, version: str = "2022.1") -> dict[str, str]:
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
        "WWISE_VERSION": version,
        "WWISE_WAAPI_PORT": "31337",
    }


class _SoundEngineDraftClient:
    event_id = "{11111111-1111-1111-1111-111111111111}"
    other_event_id = "{10101010-1010-1010-1010-101010101010}"
    state_group_id = "{22222222-2222-2222-2222-222222222222}"
    state_id = "{33333333-3333-3333-3333-333333333333}"
    switch_group_id = "{44444444-4444-4444-4444-444444444444}"
    switch_id = "{55555555-5555-5555-5555-555555555555}"
    trigger_id = "{66666666-6666-6666-6666-666666666666}"
    game_parameter_id = "{77777777-7777-7777-7777-777777777777}"
    sound_bank_id = "{88888888-8888-8888-8888-888888888888}"
    aux_bus_id = "{99999999-9999-9999-9999-999999999999}"

    def __init__(self, tmp_path: Path, version: str = "2022.1") -> None:
        project_root = tmp_path / "SampleProject"
        project_root.mkdir()
        self.project_file = project_root / "SampleProject.wproj"
        self.project_file.write_text("fixture", encoding="utf-8")
        self.event_name = "Play_Weather"
        self.post_event_return = 1234
        self.version = version
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
                    "year": int(self.version.split(".", 1)[0]),
                    "major": 1,
                    "minor": 0,
                    "build": 1,
                    "displayName": f"v{self.version}.0.1",
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
            rows = {
                self.event_id: {
                    "id": self.event_id,
                    "name": self.event_name,
                    "type": "Event",
                    "path": r"\Events\Default Work Unit\Play_Weather",
                },
                self.other_event_id: {
                    "id": self.other_event_id,
                    "name": "Play_Alarm",
                    "type": "Event",
                    "path": r"\Events\Default Work Unit\Play_Alarm",
                },
                self.state_group_id: {
                    "id": self.state_group_id,
                    "name": "Weather",
                    "type": "StateGroup",
                    "path": r"\States\Default Work Unit\Weather",
                },
                self.state_id: {
                    "id": self.state_id,
                    "name": "Storm",
                    "type": "State",
                    "path": r"\States\Default Work Unit\Weather\Storm",
                },
                self.switch_group_id: {
                    "id": self.switch_group_id,
                    "name": "Surface",
                    "type": "SwitchGroup",
                    "path": r"\Switches\Default Work Unit\Surface",
                },
                self.switch_id: {
                    "id": self.switch_id,
                    "name": "Metal",
                    "type": "Switch",
                    "path": r"\Switches\Default Work Unit\Surface\Metal",
                },
                self.trigger_id: {
                    "id": self.trigger_id,
                    "name": "Thunder",
                    "type": "Trigger",
                    "path": r"\Triggers\Default Work Unit\Thunder",
                },
                self.game_parameter_id: {
                    "id": self.game_parameter_id,
                    "name": "Wind_Intensity",
                    "type": "GameParameter",
                    "path": r"\Game Parameters\Default Work Unit\Wind_Intensity",
                },
                self.sound_bank_id: {
                    "id": self.sound_bank_id,
                    "name": "Combat_Main",
                    "type": "SoundBank",
                    "path": r"\SoundBanks\Default Work Unit\Combat_Main",
                },
                self.aux_bus_id: {
                    "id": self.aux_bus_id,
                    "name": "Cave_Reverb",
                    "type": "AuxBus",
                    "path": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\Cave_Reverb",
                },
            }
            if requested and all(object_id in rows for object_id in requested):
                return {"return": [rows[object_id] for object_id in requested]}
            raise AssertionError(f"unexpected object ids {requested!r}")
        if uri in {
            "ak.soundengine.registerGameObj",
            "ak.soundengine.unregisterGameObj",
            "ak.soundengine.executeActionOnEvent",
            "ak.soundengine.seekOnEvent",
            "ak.soundengine.setState",
            "ak.soundengine.setSwitch",
            "ak.soundengine.postTrigger",
            "ak.soundengine.setRTPCValue",
            "ak.soundengine.resetRTPCValue",
            "ak.soundengine.loadBank",
            "ak.soundengine.unloadBank",
            "ak.soundengine.setDefaultListeners",
            "ak.soundengine.setListeners",
            "ak.soundengine.setPosition",
            "ak.soundengine.setMultiplePositions",
            "ak.soundengine.setObjectObstructionAndOcclusion",
            "ak.soundengine.setScalingFactor",
            "ak.soundengine.setGameObjectOutputBusVolume",
            "ak.soundengine.setListenerSpatialization",
            "ak.soundengine.setGameObjectAuxSendValues",
            "ak.soundengine.stopAll",
        }:
            self.soundengine_calls.append(uri)
            return {}
        if uri == "ak.soundengine.postEvent":
            self.soundengine_calls.append(uri)
            return {"return": self.post_event_return}
        if uri == "ak.soundengine.getState":
            self.soundengine_calls.append(uri)
            return {"id": self.state_id, "name": "Storm"}
        if uri == "ak.soundengine.getSwitch":
            self.soundengine_calls.append(uri)
            return {"id": self.switch_id, "name": "Metal"}
        if uri == "ak.soundengine.stopPlayingID":
            self.soundengine_calls.append(uri)
            return {}
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
    version: str = "2022.1",
) -> tuple[dict[str, object], dict[str, object]]:
    code, started = gateway.execute_gateway(
        [
            "--version",
            version,
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
                version,
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
            version,
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
            version,
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
            version,
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


def _declare_soundengine_plan_result(
    *,
    state_dir: Path,
    env: dict[str, str],
    client: _SoundEngineDraftClient,
    operation: str,
    declaration: list[str],
    role_bindings: tuple[tuple[str, str], ...] = (),
    version: str = "2022.1",
) -> tuple[int, dict[str, object]]:
    code, started = gateway.execute_gateway(
        [
            "--version",
            version,
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
    current = draft
    bound_handles: dict[str, str] = {}
    for role, object_id in role_bindings:
        code, bound = gateway.execute_gateway(
            [
                "--version",
                version,
                "--state-dir",
                str(state_dir),
                "draft-bind-object",
                draft["draft_id"],
                "--task-authority",
                started["task_authority"],
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
    resolved = [
        bound_handles[value.removeprefix("<bound:").removesuffix(">")]
        if value.startswith("<bound:") and value.endswith(">")
        else value
        for value in declaration
    ]
    return gateway.execute_gateway(
        [
            "--version",
            version,
            "--state-dir",
            str(state_dir),
            "draft-declare-soundengine-plan",
            draft["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(current["revision"]),
            *resolved,
        ],
        env=env,
        client_factory=lambda _url: client,
    )


def _execute_and_verify_soundengine(
    *,
    state_dir: Path,
    env: dict[str, str],
    client: _SoundEngineDraftClient,
    previewed: dict[str, object],
    version: str = "2022.1",
) -> dict[str, object]:
    transaction_id = str(previewed["transaction_id"])
    snapshot = TransactionStore(state_dir).load_snapshot(transaction_id)
    code, confirmed = gateway.execute_gateway(
        [
            "--version",
            version,
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
            version,
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
            version,
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


def test_reregistered_game_object_uses_distinct_generation_and_cleanup(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path)
    first_handle, first_id = _register_game_object_for_test(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        name="Repeated Weather Listener",
    )
    second_handle, second_id = _register_game_object_for_test(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        name="Repeated Weather Listener",
    )

    assert first_id != second_id
    assert first_handle != second_handle
    for handle in (first_handle, second_handle):
        unregister_preview, _ = _preview_soundengine_plan(
            tmp_path=tmp_path,
            state_dir=state_dir,
            env=env,
            client=client,
            operation="ak.soundengine.unregisterGameObj",
            declaration=["--game-object-handle", handle],
        )
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


def test_listener_and_multi_position_schemas_disclose_complete_list_bounds(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    for operation in (
        "ak.soundengine.setDefaultListeners",
        "ak.soundengine.setListeners",
    ):
        code, schema = gateway.execute_gateway(
            ["--version", "2022.1", "request-schema", operation],
            env=env,
            client_factory=lambda url: pytest.fail(
                f"offline schema connected to {url}"
            ),
        )
        assert code == 0, schema
        assert schema["business_adapter"]["declaration"]["input_forms"][
            "listener_handles"
        ] == {
            "flag": "--listener-handle",
            "repeatable": True,
            "minimum_items": 1,
            "maximum_items": 64,
            "unique_items": True,
        }

    code, schema = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "request-schema",
            "ak.soundengine.setMultiplePositions",
        ],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )
    assert code == 0, schema
    assert schema["business_adapter"]["declaration"]["input_forms"][
        "position_frames"
    ] == {
        "flag": "--position-frame",
        "repeatable": True,
        "arity": 9,
        "minimum_items": 1,
        "maximum_items": 256,
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


def test_post_event_issues_opaque_playing_handle_that_drives_stop(
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
    posted = _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=post_preview,
    )
    business_result = posted["agent_result"]["business_result"]
    assert business_result["contract"] == (
        "waapi-skill.soundengine-control-result/v1"
    )
    playing_handle = business_result["playing_handle"]
    assert playing_handle.startswith("plh1-")
    assert posted["agent_result"]["result"] == {
        "playing_handle": playing_handle,
    }

    operation = "ak.soundengine.stopPlayingID"
    code, schema = gateway.execute_gateway(
        ["--version", "2022.1", "request-schema", operation],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )
    assert code == 0, schema
    declaration = schema["business_adapter"]["declaration"]
    assert declaration["required_fields"] == ["playing_handle"]
    assert declaration["optional_fields"] == [
        "fade_duration_ms",
        "fade_curve",
    ]
    stop_preview, artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation=operation,
        declaration=[
            "--playing-handle",
            playing_handle,
            "--fade-duration-ms",
            "180",
            "--fade-curve",
            "Linear",
        ],
    )
    assert artifact["request"]["arguments"] == {
        "api": operation,
        "args": {
            "playingId": 1234,
            "transitionDuration": 180,
            "fadeCurve": 4,
        },
        "options": {},
    }
    stopped = _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=stop_preview,
    )
    assert stopped["agent_result"]["business_result"] == {
        "contract": "waapi-skill.soundengine-control-result/v1",
        "retired_playing_handle_count": 1,
    }
    assert stopped["agent_result"]["result"] == {}


def test_stop_playing_revalidates_handle_at_execute_and_never_reuses_it(
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
            registered["agent_result"]["business_result"]["game_object_handle"],
        ],
        role_bindings=(("event", client.event_id),),
    )
    posted = _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=post_preview,
    )
    playing_handle = posted["agent_result"]["business_result"]["playing_handle"]
    first_preview, _ = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.stopPlayingID",
        declaration=["--playing-handle", playing_handle],
    )
    stale_preview, stale_artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.stopPlayingID",
        declaration=["--playing-handle", playing_handle],
    )
    assert stale_artifact["request"]["arguments"]["args"] == {
        "playingId": 1234,
        "transitionDuration": 0,
        "fadeCurve": 4,
    }
    _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=first_preview,
    )

    transaction_id = str(stale_preview["transaction_id"])
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
    assert stopped["error_code"] == "PLAYING_HANDLE_NOT_AVAILABLE"
    assert stopped["executed"] is False
    assert client.soundengine_calls == calls_before


def test_post_event_zero_result_is_a_bounded_failure_without_playing_handle(
    tmp_path: Path,
) -> None:
    version = "2024.1"
    env = _env(tmp_path, version)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path, version)
    client.post_event_return = 0
    previewed, _ = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.postEvent",
        declaration=["--event-handle", "<bound:event>"],
        role_bindings=(("event", client.event_id),),
        version=version,
    )
    transaction_id = str(previewed["transaction_id"])
    snapshot = TransactionStore(state_dir).load_snapshot(transaction_id)
    code, confirmed = gateway.execute_gateway(
        [
            "--version",
            version,
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
            version,
            "--state-dir",
            str(state_dir),
            "execute",
            transaction_id,
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 0, executed
    code, failed = gateway.execute_gateway(
        [
            "--version",
            version,
            "--state-dir",
            str(state_dir),
            "verify",
            transaction_id,
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 2, failed
    assert failed["status"] == "soundengine_playback_not_started"
    assert failed["error_code"] == "PLAYING_HANDLE_NOT_STARTED"
    assert failed["agent_result"] is None
    records = state_dir / "soundengine-playing-handles-v1" / "records"
    assert not list(records.glob("plh1-*.json"))


def test_event_action_and_stop_all_hide_native_enums_and_wildcards(
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
    game_object_id = register_artifact["request"]["arguments"]["args"][
        "gameObject"
    ]

    action_preview, action_artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.executeActionOnEvent",
        declaration=[
            "--event-handle",
            "<bound:event>",
            "--action",
            "Pause",
            "--game-object-handle",
            game_object_handle,
            "--fade-duration-ms",
            "250",
            "--fade-curve",
            "SCurve",
        ],
        role_bindings=(("event", client.event_id),),
    )
    assert action_artifact["request"]["arguments"] == {
        "api": "ak.soundengine.executeActionOnEvent",
        "args": {
            "event": client.event_id,
            "actionType": 1,
            "gameObject": game_object_id,
            "transitionDuration": 250,
            "fadeCurve": 5,
        },
        "options": {},
    }
    _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=action_preview,
    )

    stop_all_preview, stop_all_artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.stopAll",
        declaration=[],
    )
    assert stop_all_artifact["request"]["arguments"] == {
        "api": "ak.soundengine.stopAll",
        "args": {"gameObject": 0xFFFFFFFFFFFFFFFF},
        "options": {},
    }
    _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=stop_all_preview,
    )


def test_seek_event_compiles_business_position_and_opaque_playing_target(
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
            registered["agent_result"]["business_result"]["game_object_handle"],
        ],
        role_bindings=(("event", client.event_id),),
    )
    posted = _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=post_preview,
    )
    playing_handle = posted["agent_result"]["business_result"]["playing_handle"]

    seek_preview, seek_artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.seekOnEvent",
        declaration=[
            "--event-handle",
            "<bound:event>",
            "--playing-handle",
            playing_handle,
            "--position-percent",
            "25",
            "--nearest-marker",
        ],
        role_bindings=(("event", client.event_id),),
    )
    assert seek_artifact["request"]["arguments"] == {
        "api": "ak.soundengine.seekOnEvent",
        "args": {
            "event": client.event_id,
            "gameObject": 0xFFFFFFFFFFFFFFFF,
            "percent": 0.25,
            "seekToNearestMarker": True,
            "playingId": 1234,
        },
        "options": {},
    }
    _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=seek_preview,
    )


def test_state_switch_and_trigger_compile_only_from_bound_business_roles(
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
    game_object_id = register_artifact["request"]["arguments"]["args"][
        "gameObject"
    ]

    cases = (
        (
            "ak.soundengine.setState",
            [
                "--state-group-handle",
                "<bound:state_group>",
                "--state-handle",
                "<bound:state>",
            ],
            (
                ("state_group", client.state_group_id),
                ("state", client.state_id),
            ),
            {
                "stateGroup": client.state_group_id,
                "state": client.state_id,
            },
        ),
        (
            "ak.soundengine.setSwitch",
            [
                "--switch-group-handle",
                "<bound:switch_group>",
                "--switch-handle",
                "<bound:switch>",
                "--game-object-handle",
                game_object_handle,
            ],
            (
                ("switch_group", client.switch_group_id),
                ("switch", client.switch_id),
            ),
            {
                "switchGroup": client.switch_group_id,
                "switchState": client.switch_id,
                "gameObject": game_object_id,
            },
        ),
        (
            "ak.soundengine.postTrigger",
            [
                "--trigger-handle",
                "<bound:trigger>",
                "--game-object-handle",
                game_object_handle,
            ],
            (("trigger", client.trigger_id),),
            {
                "trigger": client.trigger_id,
                "gameObject": game_object_id,
            },
        ),
    )
    for operation, declaration, bindings, expected_args in cases:
        previewed, artifact = _preview_soundengine_plan(
            tmp_path=tmp_path,
            state_dir=state_dir,
            env=env,
            client=client,
            operation=operation,
            declaration=declaration,
            role_bindings=bindings,
        )
        assert artifact["request"]["arguments"] == {
            "api": operation,
            "args": expected_args,
            "options": {},
        }
        _execute_and_verify_soundengine(
            state_dir=state_dir,
            env=env,
            client=client,
            previewed=previewed,
        )


def test_seek_requires_one_position_and_an_event_matched_playing_handle(
    tmp_path: Path,
) -> None:
    version = "2024.1"
    env = _env(tmp_path, version)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path, version)
    before_calls = list(client.soundengine_calls)
    for position_fields in (
        [],
        ["--position-ms", "250", "--position-percent", "50"],
    ):
        code, rejected = _declare_soundengine_plan_result(
            state_dir=state_dir,
            env=env,
            client=client,
            operation="ak.soundengine.seekOnEvent",
            declaration=["--event-handle", "<bound:event>", *position_fields],
            role_bindings=(("event", client.event_id),),
            version=version,
        )
        assert code == 2, rejected
        assert rejected["error_code"] == "SOUNDENGINE_SEEK_TARGET_INVALID"
    assert client.soundengine_calls == before_calls

    post_preview, _ = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.postEvent",
        declaration=["--event-handle", "<bound:event>"],
        role_bindings=(("event", client.event_id),),
        version=version,
    )
    posted = _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=post_preview,
        version=version,
    )
    playing_handle = posted["agent_result"]["business_result"]["playing_handle"]
    before_calls = list(client.soundengine_calls)
    code, rejected = _declare_soundengine_plan_result(
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.seekOnEvent",
        declaration=[
            "--event-handle",
            "<bound:event>",
            "--playing-handle",
            playing_handle,
            "--position-percent",
            "25",
        ],
        role_bindings=(("event", client.other_event_id),),
        version=version,
    )
    assert code == 2, rejected
    assert rejected["error_code"] == "PLAYING_HANDLE_EVENT_MISMATCH"
    assert client.soundengine_calls == before_calls


def test_versioned_game_object_requirements_follow_each_reflected_overload(
    tmp_path: Path,
) -> None:
    expected = {
        "ak.soundengine.postEvent": ("2023.1", "2024.1"),
        "ak.soundengine.setSwitch": ("2022.1", "2023.1"),
        "ak.soundengine.postTrigger": ("2022.1", "2023.1"),
        "ak.soundengine.setRTPCValue": ("2022.1", "2023.1"),
        "ak.soundengine.resetRTPCValue": ("2022.1", "2023.1"),
    }
    for operation, (required_version, optional_version) in expected.items():
        code, required_schema = gateway.execute_gateway(
            ["--version", required_version, "request-schema", operation],
            env=_env(tmp_path, required_version),
            client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
        )
        assert code == 0, required_schema
        required_declaration = required_schema["business_adapter"]["declaration"]
        assert "game_object_handle" in required_declaration["required_fields"]
        assert "game_object_handle" not in required_declaration["optional_fields"]

        code, optional_schema = gateway.execute_gateway(
            ["--version", optional_version, "request-schema", operation],
            env=_env(tmp_path, optional_version),
            client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
        )
        assert code == 0, optional_schema
        optional_declaration = optional_schema["business_adapter"]["declaration"]
        assert "game_object_handle" not in optional_declaration["required_fields"]
        assert "game_object_handle" in optional_declaration["optional_fields"]

    version = "2023.1"
    env = _env(tmp_path, version)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path, version)
    previewed, artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.setSwitch",
        declaration=[
            "--switch-group-handle",
            "<bound:switch_group>",
            "--switch-handle",
            "<bound:switch>",
        ],
        role_bindings=(
            ("switch_group", client.switch_group_id),
            ("switch", client.switch_id),
        ),
        version=version,
    )
    assert artifact["request"]["arguments"]["args"] == {
        "switchGroup": client.switch_group_id,
        "switchState": client.switch_id,
    }
    _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=previewed,
        version=version,
    )


def test_game_parameter_set_and_reset_hide_rtpc_wire_naming(
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
    game_object_id = register_artifact["request"]["arguments"]["args"][
        "gameObject"
    ]
    cases = (
        (
            "ak.soundengine.setRTPCValue",
            [
                "--game-parameter-handle",
                "<bound:game_parameter>",
                "--value",
                "37.5",
                "--game-object-handle",
                game_object_handle,
            ],
            {
                "rtpc": client.game_parameter_id,
                "value": 37.5,
                "gameObject": game_object_id,
            },
        ),
        (
            "ak.soundengine.resetRTPCValue",
            [
                "--game-parameter-handle",
                "<bound:game_parameter>",
                "--game-object-handle",
                game_object_handle,
            ],
            {
                "rtpc": client.game_parameter_id,
                "gameObject": game_object_id,
            },
        ),
    )
    for operation, declaration, expected_args in cases:
        previewed, artifact = _preview_soundengine_plan(
            tmp_path=tmp_path,
            state_dir=state_dir,
            env=env,
            client=client,
            operation=operation,
            declaration=declaration,
            role_bindings=(("game_parameter", client.game_parameter_id),),
        )
        assert artifact["request"]["arguments"] == {
            "api": operation,
            "args": expected_args,
            "options": {},
        }
        _execute_and_verify_soundengine(
            state_dir=state_dir,
            env=env,
            client=client,
            previewed=previewed,
        )


def test_bank_runtime_lifecycle_uses_bound_soundbank_not_native_identifier(
    tmp_path: Path,
) -> None:
    version = "2023.1"
    env = _env(tmp_path, version)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path, version)
    for operation in ("ak.soundengine.loadBank", "ak.soundengine.unloadBank"):
        previewed, artifact = _preview_soundengine_plan(
            tmp_path=tmp_path,
            state_dir=state_dir,
            env=env,
            client=client,
            operation=operation,
            declaration=["--sound-bank-handle", "<bound:sound_bank>"],
            role_bindings=(("sound_bank", client.sound_bank_id),),
            version=version,
        )
        assert artifact["request"]["arguments"] == {
            "api": operation,
            "args": {"soundBank": client.sound_bank_id},
            "options": {},
        }
        _execute_and_verify_soundengine(
            state_dir=state_dir,
            env=env,
            client=client,
            previewed=previewed,
            version=version,
        )


def _register_game_object_for_test(
    *,
    tmp_path: Path,
    state_dir: Path,
    env: dict[str, str],
    client: _SoundEngineDraftClient,
    name: str,
    version: str = "2022.1",
) -> tuple[str, int]:
    previewed, artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.registerGameObj",
        declaration=["--game-object-name", name],
        version=version,
    )
    verified = _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=previewed,
        version=version,
    )
    return (
        verified["agent_result"]["business_result"]["game_object_handle"],
        artifact["request"]["arguments"]["args"]["gameObject"],
    )


def test_listener_position_and_mix_controls_compile_high_level_values(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path)
    emitter_handle, emitter_id = _register_game_object_for_test(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        name="Weather Emitter",
    )
    listener_handle, listener_id = _register_game_object_for_test(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        name="Main Listener",
    )
    cases = (
        (
            "ak.soundengine.setDefaultListeners",
            ["--listener-handle", listener_handle],
            {"listeners": [listener_id]},
        ),
        (
            "ak.soundengine.setDefaultListeners",
            ["--clear-listeners"],
            {"listeners": []},
        ),
        (
            "ak.soundengine.setListeners",
            [
                "--emitter-handle",
                emitter_handle,
                "--listener-handle",
                listener_handle,
            ],
            {"emitter": emitter_id, "listeners": [listener_id]},
        ),
        (
            "ak.soundengine.setPosition",
            [
                "--game-object-handle",
                emitter_handle,
                "--position-frame",
                "1",
                "2",
                "3",
                "0",
                "0",
                "1",
                "0",
                "1",
                "0",
            ],
            {
                "gameObject": emitter_id,
                "position": {
                    "position": {"x": 1.0, "y": 2.0, "z": 3.0},
                    "orientationFront": {"x": 0.0, "y": 0.0, "z": 1.0},
                    "orientationTop": {"x": 0.0, "y": 1.0, "z": 0.0},
                },
            },
        ),
        (
            "ak.soundengine.setMultiplePositions",
            [
                "--game-object-handle",
                emitter_handle,
                "--multi-position-mode",
                "MultiDirections",
                "--position-frame",
                "1",
                "2",
                "3",
                "0",
                "0",
                "1",
                "0",
                "1",
                "0",
                "--position-frame",
                "4",
                "5",
                "6",
                "1",
                "0",
                "0",
                "0",
                "1",
                "0",
            ],
            {
                "gameObject": emitter_id,
                "positions": [
                    {
                        "position": {
                            "position": {"x": 1.0, "y": 2.0, "z": 3.0},
                            "orientationFront": {"x": 0.0, "y": 0.0, "z": 1.0},
                            "orientationTop": {"x": 0.0, "y": 1.0, "z": 0.0},
                        }
                    },
                    {
                        "position": {
                            "position": {"x": 4.0, "y": 5.0, "z": 6.0},
                            "orientationFront": {"x": 1.0, "y": 0.0, "z": 0.0},
                            "orientationTop": {"x": 0.0, "y": 1.0, "z": 0.0},
                        }
                    },
                ],
                "multiPositionType": 2,
            },
        ),
        (
            "ak.soundengine.setObjectObstructionAndOcclusion",
            [
                "--emitter-handle",
                emitter_handle,
                "--listener-handle",
                listener_handle,
                "--obstruction-percent",
                "25",
                "--occlusion-percent",
                "50",
            ],
            {
                "emitter": emitter_id,
                "listener": listener_id,
                "obstructionLevel": 0.25,
                "occlusionLevel": 0.5,
            },
        ),
        (
            "ak.soundengine.setScalingFactor",
            [
                "--game-object-handle",
                emitter_handle,
                "--attenuation-scale-percent",
                "150",
            ],
            {"gameObject": emitter_id, "attenuationScalingFactor": 1.5},
        ),
    )
    for operation, declaration, expected_args in cases:
        previewed, artifact = _preview_soundengine_plan(
            tmp_path=tmp_path,
            state_dir=state_dir,
            env=env,
            client=client,
            operation=operation,
            declaration=declaration,
        )
        assert artifact["request"]["arguments"] == {
            "api": operation,
            "args": expected_args,
            "options": {},
        }
        _execute_and_verify_soundengine(
            state_dir=state_dir,
            env=env,
            client=client,
            previewed=previewed,
        )

    output_preview, output_artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.setGameObjectOutputBusVolume",
        declaration=[
            "--emitter-handle",
            emitter_handle,
            "--listener-handle",
            listener_handle,
            "--volume-db",
            "-6",
        ],
    )
    output_args = output_artifact["request"]["arguments"]["args"]
    assert output_args["emitter"] == emitter_id
    assert output_args["listener"] == listener_id
    assert output_args["controlValue"] == pytest.approx(10 ** (-6 / 20))
    _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=output_preview,
    )

    spatial_preview, spatial_artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.setListenerSpatialization",
        declaration=[
            "--listener-handle",
            listener_handle,
            "--spatialization",
            "enabled",
            "--channel-layout",
            "5.1",
            "--speaker-offset-db",
            "C",
            "-3",
            "--speaker-offset-db",
            "LFE",
            "-3",
        ],
    )
    spatial_args = spatial_artifact["request"]["arguments"]["args"]
    channel_mask_5_1 = 0x1 | 0x2 | 0x4 | 0x8 | 0x200 | 0x400
    assert spatial_args == {
        "listener": listener_id,
        "spatialized": True,
        "channelConfig": 6 | (1 << 8) | (channel_mask_5_1 << 12),
        "volumeOffsets": [0.0, 0.0, -3.0, 0.0, 0.0, -3.0],
    }
    _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=spatial_preview,
    )

    aux_preview, aux_artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.setGameObjectAuxSendValues",
        declaration=[
            "--emitter-handle",
            emitter_handle,
            "--aux-send",
            listener_handle,
            "<bound:aux_bus>",
            "35",
        ],
        role_bindings=(("aux_bus", client.aux_bus_id),),
    )
    assert aux_artifact["request"]["arguments"] == {
        "api": "ak.soundengine.setGameObjectAuxSendValues",
        "args": {
            "gameObject": emitter_id,
            "auxSendValues": [
                {
                    "listener": listener_id,
                    "auxBus": client.aux_bus_id,
                    "controlValue": 0.35,
                }
            ],
        },
        "options": {},
    }
    _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=aux_preview,
    )
    clear_aux_preview, clear_aux_artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.setGameObjectAuxSendValues",
        declaration=["--emitter-handle", emitter_handle, "--clear-aux-sends"],
    )
    assert clear_aux_artifact["request"]["arguments"]["args"] == {
        "gameObject": emitter_id,
        "auxSendValues": [],
    }
    _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=clear_aux_preview,
    )


@pytest.mark.parametrize(
    ("version", "declaration", "expected_channel_config", "expected_offsets"),
    (
        (
            "2025.1",
            [
                "--channel-layout-kind",
                "Standard",
                "--channel-speaker",
                "FL",
                "--channel-speaker",
                "FR",
                "--channel-speaker",
                "HFL",
                "--channel-speaker",
                "HFR",
                "--channel-speaker",
                "LFE",
                "--speaker-offset-db",
                "HFR",
                "-2",
                "--speaker-offset-db",
                "LFE",
                "-6",
            ],
            5 | (1 << 8) | ((0x1 | 0x2 | 0x8 | 0x1000 | 0x4000) << 12),
            [0.0, 0.0, 0.0, -2.0, -6.0],
        ),
        (
            "2022.1",
            [
                "--channel-layout-kind",
                "Anonymous",
                "--channel-count",
                "3",
                "--channel-offset-db",
                "2",
                "-4",
            ],
            3,
            [0.0, -4.0, 0.0],
        ),
        (
            "2022.1",
            [
                "--channel-layout-kind",
                "Ambisonic",
                "--channel-count",
                "9",
                "--channel-offset-db",
                "9",
                "-3",
            ],
            9 | (2 << 8),
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -3.0],
        ),
        (
            "2022.1",
            ["--channel-layout-kind", "Objects"],
            3 << 8,
            [],
        ),
    ),
)
def test_listener_spatialization_compiles_every_valid_channel_config_family(
    tmp_path: Path,
    version: str,
    declaration: list[str],
    expected_channel_config: int,
    expected_offsets: list[float],
) -> None:
    env = _env(tmp_path, version)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path, version)
    listener_handle, listener_id = _register_game_object_for_test(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        name="Spatial Listener",
        version=version,
    )

    previewed, artifact = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.setListenerSpatialization",
        declaration=[
            "--listener-handle",
            listener_handle,
            "--spatialization",
            "enabled",
            *declaration,
        ],
        version=version,
    )
    assert artifact["request"]["arguments"] == {
        "api": "ak.soundengine.setListenerSpatialization",
        "args": {
            "listener": listener_id,
            "spatialized": True,
            "channelConfig": expected_channel_config,
            "volumeOffsets": expected_offsets,
        },
        "options": {},
    }
    _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=previewed,
        version=version,
    )


@pytest.mark.parametrize(
    ("version", "descriptor", "expected_error"),
    (
        (
            "2022.1",
            ["--channel-layout", "2.0", "--channel-layout-kind", "Objects"],
            "CHANNEL_LAYOUT_DESCRIPTOR_INVALID",
        ),
        (
            "2022.1",
            ["--channel-layout-kind", "Standard"],
            "STANDARD_CHANNEL_SPEAKERS_INVALID",
        ),
        (
            "2022.1",
            [
                "--channel-layout-kind",
                "Standard",
                "--channel-speaker",
                "HSL",
            ],
            "STANDARD_CHANNEL_SPEAKERS_INVALID",
        ),
        (
            "2022.1",
            ["--channel-layout-kind", "Anonymous", "--channel-count", "0"],
            "CHANNEL_COUNT_INVALID",
        ),
        (
            "2022.1",
            ["--channel-layout-kind", "Ambisonic", "--channel-count", "8"],
            "CHANNEL_COUNT_INVALID",
        ),
        (
            "2022.1",
            [
                "--channel-layout-kind",
                "Objects",
                "--channel-offset-db",
                "1",
                "-3",
            ],
            "OBJECT_CHANNEL_LAYOUT_INVALID",
        ),
        (
            "2022.1",
            [
                "--channel-layout-kind",
                "Anonymous",
                "--channel-count",
                "2",
                "--channel-offset-db",
                "3",
                "-3",
            ],
            "CHANNEL_OFFSET_INVALID",
        ),
    ),
)
def test_listener_spatialization_rejects_unclosed_channel_descriptors(
    tmp_path: Path,
    version: str,
    descriptor: list[str],
    expected_error: str,
) -> None:
    env = _env(tmp_path, version)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path, version)
    listener_handle, _ = _register_game_object_for_test(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        name="Rejected Listener",
        version=version,
    )
    code, started = gateway.execute_gateway(
        [
            "--version",
            version,
            "--state-dir",
            str(state_dir),
            "draft-start",
            "ak.soundengine.setListenerSpatialization",
        ],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    draft = started["draft"]
    before_calls = list(client.soundengine_calls)

    code, rejected = gateway.execute_gateway(
        [
            "--version",
            version,
            "--state-dir",
            str(state_dir),
            "draft-declare-soundengine-plan",
            draft["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(draft["revision"]),
            "--listener-handle",
            listener_handle,
            "--spatialization",
            "enabled",
            *descriptor,
        ],
        env=env,
        client_factory=lambda _url: client,
    )
    assert code == 2, rejected
    assert rejected["error_code"] == expected_error
    assert rejected["details"]["repair"]["error_code"] == expected_error
    assert client.soundengine_calls == before_calls


def test_listener_sets_positions_and_aux_rows_fail_closed_before_preview(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path)
    emitter_handle, _ = _register_game_object_for_test(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        name="Rejected Emitter",
    )
    listener_handle, _ = _register_game_object_for_test(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        name="Rejected Aux Listener",
    )
    before_calls = list(client.soundengine_calls)

    code, rejected = _declare_soundengine_plan_result(
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.setDefaultListeners",
        declaration=[
            "--listener-handle",
            listener_handle,
            "--clear-listeners",
        ],
    )
    assert code == 2, rejected
    assert rejected["error_code"] == "LISTENER_SET_INVALID"

    code, rejected = _declare_soundengine_plan_result(
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.setPosition",
        declaration=[
            "--game-object-handle",
            emitter_handle,
            "--position-frame",
            "0",
            "0",
            "0",
            "1",
            "0",
            "0",
            "2",
            "0",
            "0",
        ],
    )
    assert code == 2, rejected
    assert rejected["error_code"] == "POSITION_ORIENTATION_INVALID"

    aux_cases = (
        (
            [
                token
                for _ in range(5)
                for token in (
                    "--aux-send",
                    listener_handle,
                    "<bound:aux_bus>",
                    "25",
                )
            ],
            "AUX_SEND_LIST_INVALID",
        ),
        (
            [
                "--aux-send",
                listener_handle,
                "<bound:aux_bus>",
                "25",
                "--aux-send",
                listener_handle,
                "<bound:aux_bus>",
                "35",
            ],
            "AUX_SEND_ROW_INVALID",
        ),
        (
            [
                "--aux-send",
                listener_handle,
                "<bound:aux_bus>",
                "101",
            ],
            "AUX_SEND_ROW_INVALID",
        ),
    )
    for aux_rows, expected_error in aux_cases:
        code, rejected = _declare_soundengine_plan_result(
            state_dir=state_dir,
            env=env,
            client=client,
            operation="ak.soundengine.setGameObjectAuxSendValues",
            declaration=["--emitter-handle", emitter_handle, *aux_rows],
            role_bindings=(("aux_bus", client.aux_bus_id),),
        )
        assert code == 2, rejected
        assert rejected["error_code"] == expected_error

    assert client.soundengine_calls == before_calls


def test_retired_game_object_handle_is_rejected_before_new_soundengine_dispatch(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path)
    handle, _ = _register_game_object_for_test(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        name="Retired Emitter",
    )
    unregister_preview, _ = _preview_soundengine_plan(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.unregisterGameObj",
        declaration=["--game-object-handle", handle],
    )
    _execute_and_verify_soundengine(
        state_dir=state_dir,
        env=env,
        client=client,
        previewed=unregister_preview,
    )
    before_calls = list(client.soundengine_calls)
    code, rejected = _declare_soundengine_plan_result(
        state_dir=state_dir,
        env=env,
        client=client,
        operation="ak.soundengine.setPosition",
        declaration=[
            "--game-object-handle",
            handle,
            "--position-frame",
            "0",
            "0",
            "0",
            "1",
            "0",
            "0",
            "0",
            "1",
            "0",
        ],
    )
    assert code == 2, rejected
    assert rejected["error_code"] == "GAME_OBJECT_HANDLE_NOT_AVAILABLE"
    assert client.soundengine_calls == before_calls


def test_state_and_switch_reads_use_bounded_business_continuations(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    state_dir = tmp_path / "state"
    client = _SoundEngineDraftClient(tmp_path)
    game_object_handle, _ = _register_game_object_for_test(
        tmp_path=tmp_path,
        state_dir=state_dir,
        env=env,
        client=client,
        name="Player 01",
    )
    cases = (
        (
            "ak.soundengine.getState",
            ["--state-group-id", client.state_group_id],
            {"id": client.state_id, "name": "Storm"},
        ),
        (
            "ak.soundengine.getSwitch",
            [
                "--switch-group-id",
                client.switch_group_id,
                "--game-object-handle",
                game_object_handle,
            ],
            {"id": client.switch_id, "name": "Metal"},
        ),
    )
    for operation, declaration, expected in cases:
        code, schema = gateway.execute_gateway(
            ["--version", "2022.1", "request-schema", operation],
            env=env,
            client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
        )
        assert code == 0, schema
        assert schema["business_adapter"]["execution_shape"] == "bounded_read"
        assert schema["continuation"]["subcommand"] == "core-call"
        code, result = gateway.execute_gateway(
            [
                "--version",
                "2022.1",
                "--state-dir",
                str(state_dir),
                "core-call",
                operation,
                *declaration,
            ],
            env=env,
            client_factory=lambda _url: client,
        )
        assert code == 0, result
        assert result["agent_result"] == expected


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
