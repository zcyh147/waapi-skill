from __future__ import annotations

from tests.support.gateway_config import set_gateway_config

import importlib.util
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from wwise_waapi.canonical import canonical_sha256


LOG_GET_URI = "ak.wwise.core.log.get"
GET_CURSOR_TIME_URI = "ak.wwise.core.profiler.getCursorTime"
GET_VOICES_URI = "ak.wwise.core.profiler.getVoices"
TRANSPORT_GET_STATE_URI = "ak.wwise.core.transport.getState"
PROFILER_MOVE_CURSOR_URI = "ak.wwise.core.profiler.moveCursor"
PROFILER_SET_CURSOR_TIME_URI = "ak.wwise.core.profiler.setCursorTime"
SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_runtime_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)

from wwise_waapi.runtime_inspection_business_contracts import (  # noqa: E402
    runtime_control_business_operations,
    runtime_inspection_business_read_operations,
    runtime_inspection_business_versions,
)
from wwise_waapi.runtime_inspection_business import (  # noqa: E402
    normalize_runtime_inspection_result,
)
from wwise_waapi.runtime_transport_handles import (  # noqa: E402
    RuntimeTransportContext,
    RuntimeTransportHandleStore,
)
from wwise_waapi.transactions import TransactionStore  # noqa: E402
from wwise_waapi.execution_contracts import ExecutionContractRegistry  # noqa: E402


EXPECTED_DIRECT_READ_ROWS = {
    LOG_GET_URI: ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.profiler.getAudioObjects": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.profiler.getBusses": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    GET_CURSOR_TIME_URI: ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.profiler.getRTPCs": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    GET_VOICES_URI: ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.profiler.getCpuUsage": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.profiler.getLoadedMedia": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.profiler.getPerformanceMonitor": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.profiler.getStreamedMedia": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.profiler.getMeters": ("2024.1", "2025.1"),
    TRANSPORT_GET_STATE_URI: ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
}
EXPECTED_CONTROL_ROWS = {
    "ak.wwise.core.profiler.enableProfilerData": (
        "2021.1", "2022.1", "2023.1", "2024.1", "2025.1"
    ),
    "ak.wwise.core.remote.connect": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.transport.create": (
        "2021.1", "2022.1", "2023.1", "2024.1", "2025.1"
    ),
    "ak.wwise.core.transport.destroy": (
        "2021.1", "2022.1", "2023.1", "2024.1", "2025.1"
    ),
    "ak.wwise.core.transport.executeAction": (
        "2021.1", "2022.1", "2023.1", "2024.1", "2025.1"
    ),
    "ak.wwise.core.transport.prepare": (
        "2022.1", "2023.1", "2024.1", "2025.1"
    ),
    "ak.wwise.core.log.addItem": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.log.clear": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.profiler.saveCapture": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.transport.useOriginals": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.profiler.registerMeter": ("2024.1", "2025.1"),
    "ak.wwise.core.profiler.unregisterMeter": ("2024.1", "2025.1"),
    PROFILER_MOVE_CURSOR_URI: ("2025.1",),
    PROFILER_SET_CURSOR_TIME_URI: ("2025.1",),
}


def _env(tmp_path: Path, *, version: str = "2025.1") -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": version,
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
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


def _issue_transport_handle(
    state_dir: Path,
    *,
    project_path: Path,
    version: str = "2025.1",
    transport_id: int = 74,
    project_id: str = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
) -> str:
    return RuntimeTransportHandleStore(state_dir).issue(
        transport_id=transport_id,
        context=RuntimeTransportContext(
            endpoint_url="ws://127.0.0.1:31337/waapi",
            project_id=project_id,
            project_path=str(project_path),
            wwise_version=version,
            wwise_build=f"v{version}.0.1",
        ),
        source_transaction_id="tx1-testtransport00000000",
        source_artifact_hash="a" * 64,
        transport_row_sha256=canonical_sha256(
            {
                "transport": transport_id,
                "object": "{11111111-1111-1111-1111-111111111111}",
                "gameObject": 1,
            }
        ),
    ).handle


def test_runtime_business_direct_read_inventory_is_exactly_49_rows() -> None:
    assert runtime_inspection_business_read_operations() == frozenset(
        EXPECTED_DIRECT_READ_ROWS
    )
    assert {
        operation: runtime_inspection_business_versions(operation)
        for operation in EXPECTED_DIRECT_READ_ROWS
    } == EXPECTED_DIRECT_READ_ROWS
    assert sum(len(versions) for versions in EXPECTED_DIRECT_READ_ROWS.values()) == 49


def test_runtime_business_control_inventory_adds_two_authoring_rows() -> None:
    assert runtime_control_business_operations() == frozenset(EXPECTED_CONTROL_ROWS)
    assert {
        operation: runtime_inspection_business_versions(operation)
        for operation in EXPECTED_CONTROL_ROWS
    } == EXPECTED_CONTROL_ROWS
    assert sum(len(versions) for versions in EXPECTED_CONTROL_ROWS.values()) == 47


@pytest.mark.parametrize(
    "operation",
    ("ak.wwise.core.log.addItem", "ak.wwise.core.log.clear"),
)
def test_log_controls_are_runtime_mutations_not_project_mutations(operation: str) -> None:
    contract = ExecutionContractRegistry().describe("2025.1", operation)
    assert contract.effect == "runtime_mutation"
    assert contract.route == "managed_transaction"


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation, versions in EXPECTED_CONTROL_ROWS.items()
        for version in versions
    ],
)
def test_every_runtime_control_lane_exposes_one_business_draft_and_blocks_typed(
    tmp_path: Path,
    operation: str,
    version: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", version, "request-schema", operation],
        env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert code == 0, payload
    assert payload["business_adapter"]["contract"] == (
        "waapi-skill.runtime-control-business/v1"
    )
    assert payload["continuation"]["subcommand"] == "draft-start"
    bypass_code, bypass = gateway.execute_gateway(
        [

            "typed-call",
            operation,
            "--schema-digest",
            "0" * 64,
        ],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda url: pytest.fail(f"typed bypass connected to {url}"),
    )
    assert bypass_code == 2
    assert "closed Core business" in bypass["message"]


def test_log_get_schema_exposes_business_channel_and_bounded_result_only(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", "2025.1", "request-schema", LOG_GET_URI],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert code == 0, payload
    assert payload["business_adapter"]["result_delivery"]["mode"] == "immutable_bounded_observation"
    assert {key: value for key, value in payload["business_adapter"].items() if key != "result_delivery"} == {
        "contract": "waapi-skill.runtime-inspection-business/v1",
        "operation": LOG_GET_URI,
        "version": "2025.1",
        "input_mode": "business_declaration",
        "execution_shape": "bounded_read",
        "host_requirement": "wwise-console-or-authoring",
        "start": {
            "subcommand": "core-call",
            "gateway_argv_prefix": ["core-call", LOG_GET_URI],
        },
        "declaration": {
            "subcommand": "core-call",
            "required_fields": ["log_channel"],
            "optional_fields": ["max_results"],
            "field_types": {
                "log_channel": "wwise_log_view",
                "max_results": "bounded_result_limit",
            },
            "input_forms": {
                "log_channel": {"flag": "--log-channel", "repeatable": False},
                "max_results": {"flag": "--max-results", "repeatable": False},
            },
            "value_choices": {"log_channel": [
                "soundbank-generation", "audio-conversion", "platform-settings-copy",
                "waapi", "project-load", "general", "source-control", "lua",
            ]},
        },
        "gateway_derivations": [
            "versioned_native_log_channel",
            "native_request",
            "result_projection",
            "result_bound",
            "continuation",
        ],
        "legacy_typed_call_public": False,
    }
    assert payload["continuation"] == {
        "subcommand": "core-call",
        "gateway_argv_prefix": ["core-call", LOG_GET_URI],
        "append_only_disclosed_business_fields": True,
    }
    assert "typed-call" not in json.dumps(payload, sort_keys=True)
    assert "soundbankGenerate" not in json.dumps(payload, sort_keys=True)


@pytest.mark.parametrize(
    "operation",
    (
        "ak.wwise.core.remote.connect",
        "ak.wwise.core.transport.create",
        TRANSPORT_GET_STATE_URI,
    ),
)
def test_remote_and_transport_contracts_disclose_authoring_host_requirement(
    tmp_path: Path,
    operation: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", "2022.1", "request-schema", operation],
        env=_env(tmp_path, version="2022.1"),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert code == 0, payload
    assert payload["business_adapter"]["host_requirement"] == "wwise-authoring"


class FakeClient:
    def __init__(self, responses: Mapping[str, Sequence[Any]]) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}
        self.calls: list[tuple[str, Any, Any]] = []

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        self.calls.append((uri, args, options))
        values = self.responses.get(uri)
        if not values:
            raise AssertionError(f"unexpected WAAPI call: {uri}")
        return values.popleft()

    def disconnect(self) -> None:
        return None


def test_log_get_core_call_maps_channel_and_returns_latest_bounded_items(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [
                {
                    "displayName": "Wwise",
                    "isCommandLine": True,
                    "sessionId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                    "processId": 4242,
                    "processPath": "/Applications/Wwise/WwiseConsole",
                    "apiVersion": 1,
                    "platform": "macosx",
                    "configuration": "release",
                    "version": {
                        "year": 2025,
                        "major": 1,
                        "minor": 0,
                        "build": 1,
                        "displayName": "v2025.1.0.1",
                    },
                }
            ],
            "ak.wwise.core.getProjectInfo": [{"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", "name": "SampleProject", "path": str(tmp_path / "project" / "Sample.wproj")}],
            LOG_GET_URI: [
                {
                    "items": [
                        {"message": "old", "severity": "Message"},
                        {"message": "warning", "severity": "Warning"},
                        {"message": "latest", "severity": "Error"},
                    ]
                }
            ],
        }
    )

    code, payload = gateway.execute_gateway(
        [

            "--state-dir", str(tmp_path / "state"), "core-call",
            LOG_GET_URI,
            "--log-channel",
            "soundbank-generation",
            "--max-results",
            "2",
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert (LOG_GET_URI, {"channel": "soundbankGenerate"}, {}) in client.calls
    assert {key: payload["agent_result"][key] for key in ("channel", "items", "returned_count", "truncated")} == {
        "channel": "soundbank-generation",
        "items": [
            {"message": "warning", "severity": "Warning"},
            {"message": "latest", "severity": "Error"},
        ],
        "returned_count": 2,
        "truncated": True,
    }


@pytest.mark.parametrize(
    "version",
    ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
)
def test_log_get_has_one_business_schema_in_every_supported_lane(
    tmp_path: Path,
    version: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", version, "request-schema", LOG_GET_URI],
        env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert code == 0, payload
    assert payload["business_adapter"]["version"] == version
    assert payload["business_adapter"]["operation"] == LOG_GET_URI


@pytest.mark.parametrize("limit", ("0", "1001"))
def test_log_get_rejects_out_of_bounds_result_limit_before_connection(
    tmp_path: Path,
    limit: str,
) -> None:
    code, payload = gateway.execute_gateway(
        [

            "core-call",
            LOG_GET_URI,
            "--log-channel",
            "general",
            "--max-results",
            limit,
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda url: pytest.fail(f"invalid input connected to {url}"),
    )

    assert code == 2
    assert "1 to 1000" in payload["message"]


def test_log_get_rejects_native_channel_token_before_connection(tmp_path: Path) -> None:
    code, payload = gateway.execute_gateway(
        [

            "core-call",
            LOG_GET_URI,
            "--log-channel",
            "soundbankGenerate",
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda url: pytest.fail(f"native token connected to {url}"),
    )

    assert code == 2
    assert "soundbank-generation" in payload["message"]


def test_log_get_rejects_later_log_view_on_older_wwise_before_connection(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        [

            "core-call",
            LOG_GET_URI,
            "--log-channel",
            "source-control",
        ],
        env=set_gateway_config(_env(tmp_path, version="2022.1"), wwise_version="2022.1"),
        client_factory=lambda url: pytest.fail(f"version mismatch connected to {url}"),
    )

    assert code == 2
    assert "available Wwise log view" in payload["message"]


def test_log_get_blocks_retired_typed_call_before_connection(tmp_path: Path) -> None:
    code, payload = gateway.execute_gateway(
        [

            "typed-call",
            LOG_GET_URI,
            "--schema-digest",
            "0" * 64,
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda url: pytest.fail(f"typed bypass connected to {url}"),
    )

    assert code == 2
    assert "closed Core business" in payload["message"]


def test_log_get_blocks_retired_draft_before_state_or_connection(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    code, payload = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-start",
            LOG_GET_URI,
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda url: pytest.fail(f"typed draft connected to {url}"),
    )

    assert code == 2
    assert "closed Core business" in payload["message"]
    assert not (state_dir / "operation-drafts-v1").exists()


def test_profiler_voice_schema_exposes_position_view_bound_and_handle_only(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", "2025.1", "request-schema", GET_VOICES_URI],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert code == 0, payload
    declaration = payload["business_adapter"]["declaration"]
    assert declaration["required_fields"] == ["profiler_position"]
    assert declaration["optional_fields"] == [
        "max_results",
        "result_view",
        "voice_instance_handle",
    ]
    encoded = json.dumps(payload, sort_keys=True)
    assert "voicePipelineID" not in encoded
    assert '"return"' not in encoded
    assert "typed-call" not in encoded


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_profiler_voice_read_derives_native_time_projection_and_handle(tmp_path: Path, version: str) -> None:
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    calls = []
    row = {"pipelineID": 42, "objectGUID": client.target_id, "gameObjectID": 1,
           "objectName": "Rifle", "gameObjectName": "Player"}
    def call(uri, args=None, options=None):
        calls.append((uri, args, options))
        if uri == GET_CURSOR_TIME_URI:
            return {"return": 123}
        if uri == GET_VOICES_URI:
            return {"return": [dict(row)]}
        return original(uri, args, options)
    client.call = call
    env = _env(tmp_path, version=version)
    prefix = ["--state-dir", str(tmp_path / "state"), "core-call", GET_VOICES_URI,
              "--profiler-position", "capture-latest"]
    code, observed = gateway.execute_gateway(prefix, env=env, client_factory=lambda _url: client)
    assert code == 0, observed
    handle = observed["agent_result"]["return"][0]["voice_instance_handle"]
    assert handle.startswith("rph1-") and "0000002a" not in handle
    calls.clear()
    code, wrong_position = gateway.execute_gateway([
        "--state-dir", str(tmp_path / "state"), "core-call", GET_VOICES_URI,
        "--profiler-position", "124", "--voice-instance-handle", handle],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and "another capture position" in wrong_position["message"], wrong_position
    assert not any(uri == GET_VOICES_URI for uri, _args, _options in calls)
    code, selected = gateway.execute_gateway([*prefix, "--voice-instance-handle", handle],
        env=env, client_factory=lambda _url: client)
    assert code == 0, selected
    assert any(uri == GET_VOICES_URI and args == {"time": 123, "voicePipelineID": 42} for uri, args, _options in calls)
    row["objectGUID"] = client.meter_id
    calls.clear()
    code, stale = gateway.execute_gateway([*prefix, "--voice-instance-handle", handle],
        env=env, client_factory=lambda _url: client)
    assert code == 2, stale
    assert "identity changed" in stale["message"]
    assert not any(uri == GET_VOICES_URI and "voicePipelineID" in args for uri, args, _options in calls)


def test_profiler_cursor_read_maps_business_cursor_and_projects_milliseconds(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [
                {
                    "displayName": "Wwise",
                    "isCommandLine": True,
                    "apiVersion": 1,
                    "platform": "macosx",
                    "configuration": "release",
                    "version": {
                        "year": 2025,
                        "major": 1,
                        "minor": 0,
                        "build": 1,
                        "displayName": "v2025.1.0.1",
                    },
                }
            ],
            GET_CURSOR_TIME_URI: [{"return": 1234}],
        }
    )

    code, payload = gateway.execute_gateway(
        [

            "core-call",
            GET_CURSOR_TIME_URI,
            "--profiler-cursor",
            "user-cursor",
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert (GET_CURSOR_TIME_URI, {"cursor": "user"}, {}) in client.calls
    assert payload["agent_result"] == {
        "profiler_cursor": "user-cursor",
        "available": True,
        "position_ms": 1234,
    }


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_profiler_cursor_choices_are_disclosed_before_the_live_read(tmp_path: Path, version: str) -> None:
    env = _env(tmp_path, version=version)
    code, schema = gateway.execute_gateway(
        ["request-schema", GET_CURSOR_TIME_URI], env=env,
        client_factory=lambda _url: pytest.fail("Offline schema must not connect"),
    )
    assert code == 0, schema
    choices = schema["business_adapter"]["declaration"]["value_choices"]["profiler_cursor"]
    assert choices == ["capture-latest", "user-cursor"]
    native_choices = {"capture-latest": "capture", "user-cursor": "user"}
    for choice in choices:
        client = FakeClient({
            "ak.wwise.core.getInfo": [{
                "displayName": "Wwise", "isCommandLine": True, "apiVersion": 1,
                "platform": "macosx", "configuration": "release",
                "version": {"year": int(version[:4]), "major": 1, "minor": 0, "build": 1,
                            "displayName": f"v{version}.0.1"},
            }],
            GET_CURSOR_TIME_URI: [{"return": 1234}],
        })
        code, result = gateway.execute_gateway(
            [*schema["continuation"]["gateway_argv_prefix"], "--profiler-cursor", choice],
            env=env, client_factory=lambda _url: client,
        )
        assert code == 0, result
        assert (GET_CURSOR_TIME_URI, {"cursor": native_choices[choice]}, {}) in client.calls
        assert result["agent_result"] == {"profiler_cursor": choice, "available": True, "position_ms": 1234}


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_runtime_schema_discloses_accepted_business_meanings_and_position_forms(tmp_path: Path, version: str) -> None:
    channels = ["soundbank-generation", "audio-conversion", "platform-settings-copy", "waapi", "project-load", "general"]
    if version not in {"2021.1", "2022.1"}:
        channels += ["source-control", "lua"]
    expectations = {
        LOG_GET_URI: {"log_channel": channels},
        GET_VOICES_URI: {"result_view": ["summary", "identity", "diagnostics", "capture-defaults", "empty-selection"]},
        "ak.wwise.core.transport.executeAction": {
            "audition_action": ["play", "stop", "pause", "toggle-play-stop", "play-directly"],
            "transport_scope": ["one-transport", "all-active"],
        },
    }
    if version not in {"2021.1", "2022.1"}:
        expectations["ak.wwise.core.log.addItem"] = {"log_channel": channels, "severity": ["message", "warning", "error", "fatal"]}
        expectations["ak.wwise.core.transport.useOriginals"] = {"audition_media": ["originals", "converted"]}
    if version == "2025.1":
        expectations[PROFILER_MOVE_CURSOR_URI] = {"cursor_move": ["first-frame", "last-frame", "next-frame", "previous-frame"]}
    for operation, expected in expectations.items():
        code, schema = gateway.execute_gateway(
            ["request-schema", operation], env=_env(tmp_path, version=version),
            client_factory=lambda _url: pytest.fail("Offline schema must not connect"),
        )
        assert code == 0, schema
        declaration = schema["business_adapter"]["declaration"]
        assert declaration.get("value_choices") == expected, operation
        if operation == GET_VOICES_URI:
            assert declaration["input_forms"]["profiler_position"]["value_forms"] == {
                "named": ["capture-latest", "user-cursor"],
                "integer_milliseconds": {"minimum": 0, "encoding": "ASCII decimal string", "maximum_input_bytes": 1024, "bound_owner": "Gateway request resource policy"},
            }


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_log_control_draft_and_invalid_choice_preserve_disclosed_meanings(tmp_path: Path, version: str) -> None:
    env = _env(tmp_path, version=version)
    state = tmp_path / "state"
    code, started = gateway.execute_gateway(
        ["--state-dir", str(state), "draft-start", "ak.wwise.core.log.clear"],
        env=env, client_factory=lambda _url: pytest.fail("Offline Draft start must not connect"),
    )
    assert code == 0, started
    next_action = started["draft"]["next_action_binding"]
    disclosed = next_action["declaration"]["append_fields"]["value_choices"]["log_channel"]
    assert "source-control" in disclosed
    assert next_action["business_contract"]["declaration"]["value_choices"]["log_channel"] == disclosed
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    code, rejected = gateway.execute_gateway(
        ["--state-dir", str(state), "draft-declare-runtime-control-plan", started["draft"]["draft_id"],
         "--task-authority", started["task_authority"], "--expected-revision", str(started["draft"]["revision"]),
         "--log-channel", "invented-log-view"],
        env=env, client_factory=lambda _url: client,
    )
    assert code == 2, rejected
    assert rejected["error_code"] == "BUSINESS_ENUM_INVALID"
    repair = rejected["details"]["repair"]
    assert repair["field"] == "log_channel"
    assert set(repair["choices"]) == set(disclosed)
    assert repair["draft_changed"] is False


def test_profiler_cursor_unavailable_sentinel_is_hidden_from_business_result() -> None:
    assert normalize_runtime_inspection_result(
        GET_CURSOR_TIME_URI,
        {"return": -1},
        business_request={"profiler_cursor": "user-cursor"},
        max_results=1,
    ) == {
        "profiler_cursor": "user-cursor",
        "available": False,
        "position_ms": None,
    }


def test_profiler_cursor_invalid_live_shape_preserves_bounded_diagnostics(
    tmp_path: Path,
) -> None:
    observed = {"return": -2}
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [
                {
                    "displayName": "Wwise",
                    "isCommandLine": True,
                    "apiVersion": 1,
                    "platform": "macosx",
                    "configuration": "release",
                    "version": {
                        "year": 2025,
                        "major": 1,
                        "minor": 0,
                        "build": 1,
                        "displayName": "v2025.1.0.1",
                    },
                }
            ],
            GET_CURSOR_TIME_URI: [observed],
        }
    )

    code, payload = gateway.execute_gateway(
        [

            "core-call",
            GET_CURSOR_TIME_URI,
            "--profiler-cursor",
            "user-cursor",
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert payload["error_code"] == "RUNTIME_INSPECTION_RESULT_INVALID"
    assert payload["details"] == {
        "api": GET_CURSOR_TIME_URI,
        "observed_result": observed,
    }


def test_profiler_voice_read_rejects_invented_handle_before_connection(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        [

            "core-call",
            GET_VOICES_URI,
            "--profiler-position",
            "capture-latest",
            "--voice-instance-handle",
            "42",
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda url: pytest.fail(f"invalid handle connected to {url}"),
    )

    assert code == 2
    assert "copied exactly" in payload["message"]


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_profiler_read_accepts_native_nonnegative_time_without_int32_ceiling(tmp_path: Path, version: str) -> None:
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    calls = []
    def call(uri, args=None, options=None):
        calls.append((uri, args, options))
        if uri == GET_VOICES_URI:
            return {"return": []}
        return original(uri, args, options)
    client.call = call
    code, payload = gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), "core-call", GET_VOICES_URI, "--profiler-position", "4294967296"],
        env=_env(tmp_path, version=version), client_factory=lambda _url: client,
    )
    assert code == 0, payload
    assert any(uri == GET_VOICES_URI and args == {"time": 4294967296} for uri, args, _options in calls)


def test_profiler_numeric_encoded_handle_is_not_gateway_issued_authority(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": [{"isCommandLine": True,
        "version": {"year": 2025, "major": 1, "minor": 0, "build": 1, "displayName": "v2025.1.0.1"}}],
        GET_VOICES_URI: [{"return": []}]})
    code, payload = gateway.execute_gateway(
        ["core-call", GET_VOICES_URI, "--profiler-position", "123", "--voice-instance-handle", "voice-instance-0000002a"],
        env=_env(tmp_path), client_factory=lambda _url: client)
    assert code == 2, payload
    assert not any(uri == GET_VOICES_URI for uri, _args, _options in client.calls)


def test_profiler_complete_snapshot_continuation_retains_original_rows_without_live_reread(tmp_path: Path) -> None:
    client = _RuntimeControlDraftClient(tmp_path)
    client.rows = [{"pipelineID": index + 1, "objectName": f"Voice{index}", "gameObjectName": "Player"} for index in range(5)]
    original_call = client.call
    def call(uri, args=None, options=None):
        if uri == GET_VOICES_URI:
            return {"return": client.rows}
        return original_call(uri, args, options)
    client.call = call
    env = _env(tmp_path)
    prefix = ["--state-dir", str(tmp_path / "state")]
    code, payload = gateway.execute_gateway([*prefix, "core-call", GET_VOICES_URI,
        "--profiler-position", "123", "--max-results", "2"], env=env, client_factory=lambda _url: client)
    assert code == 0, json.dumps(payload, indent=2)
    pages = [payload["agent_result"]]
    while pages[-1].get("next_command"):
        code, payload = gateway.execute_gateway(pages[-1]["next_command"]["full_argv"][3:], env=env,
            client_factory=lambda _url: pytest.fail("Snapshot continuation must not read a newer capture"))
        assert code == 0, payload
        pages.append(payload["agent_result"])
    assert len(pages) == 3
    assert [row["objectName"] for page in pages for row in page["return"]] == ["Voice3", "Voice4", "Voice1", "Voice2", "Voice0"]
    assert pages[-1]["complete"] is True
    assert all(page["observation"] == "retained_profiler_capture_snapshot" for page in pages)


@pytest.mark.parametrize("message", ["界" * 12000, '\\"' * 12000])
def test_runtime_snapshot_fragments_preserve_every_character_under_terminal_bound(tmp_path: Path, message: str) -> None:
    client = _RuntimeControlDraftClient(tmp_path)
    original = client.call
    def call(uri, args=None, options=None):
        return {"items": [{"message": message, "severity": "Message"}]} if uri == LOG_GET_URI else original(uri, args, options)
    client.call = call
    env = _env(tmp_path)
    code, payload = gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), "core-call", LOG_GET_URI,
        "--log-channel", "general"], env=env, client_factory=lambda _url: client)
    assert code == 0, json.dumps(payload)
    fragments = []
    while True:
        assert len(json.dumps(payload, ensure_ascii=False, indent=2).encode()) <= gateway.MAX_GATEWAY_RESULT_JSON_BYTES
        result = payload["agent_result"]
        assert list(payload)[-1] == "agent_result"
        fragments.append(result["row_fragment"]["value"])
        if result["complete"]:
            break
        code, payload = gateway.execute_gateway(result["next_command"]["full_argv"][3:], env=env,
            client_factory=lambda _url: pytest.fail("Fragment continuation must be offline"))
        assert code == 0, payload
    assert json.loads("".join(fragments)) == {"message": message, "severity": "Message"}


def _public_runtime_preview(tmp_path, client, state_dir, operation, declaration=()):
    env = _env(tmp_path, version=client.version)
    def invoke(argv):
        code, result = gateway.execute_gateway(["--state-dir", str(state_dir), *argv], env=env, client_factory=lambda _url: client)
        assert code == 0, json.dumps(result, indent=2)
        return result
    started = invoke(["draft-start", operation])
    draft, authority = started["draft"]["draft_id"], started["task_authority"]
    current = started
    if operation.endswith(".create"):
        current = invoke(["draft-bind-object", draft, "--task-authority", authority,
            "--expected-revision", str(current["draft"]["revision"]), "--role", "target", "--object-id", client.target_id])
        declaration = ("--target-handle", current["bound_object"]["handle"], *declaration)
    current = invoke(["draft-declare-runtime-control-plan", draft, "--task-authority", authority,
        "--expected-revision", str(current["draft"]["revision"]), *declaration])
    current = invoke(["draft-check", draft, "--task-authority", authority,
        "--expected-revision", str(current["draft"]["revision"])])
    previewed = invoke(["preview-from-draft", draft, "--task-authority", authority,
        "--expected-revision", str(current["draft"]["revision"])])
    shown = invoke(previewed["next_command"]["gateway_argv"])
    invoke(shown["next_command"]["gateway_argv"])
    return previewed, invoke


@pytest.mark.parametrize("intervention", ("replacement", "destroy"))
@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_transport_late_creation_verification_cannot_resurrect_prior_lifetime(tmp_path: Path, intervention: str, version: str) -> None:
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    client.calls = []
    def call(uri, args=None, options=None):
        client.calls.append((uri, args, options))
        if uri == "ak.wwise.core.transport.create":
            return {"transport": 74}
        if uri == "ak.wwise.core.transport.destroy":
            return {}
        if uri == TRANSPORT_GET_STATE_URI:
            return {"state": "stopped"}
        return original(uri, args, options)
    client.call = call
    state_dir = tmp_path / "state"
    pending, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.create")
    invoke(["execute", pending["transaction_id"]])
    successor, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.create")
    invoke(["execute", successor["transaction_id"]])
    published = invoke(["verify", successor["transaction_id"]])
    handle = published["agent_result"]["business_result"]["transport_handle"]
    if intervention == "destroy":
        destroyed, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.destroy", ("--transport-handle", handle))
        invoke(["execute", destroyed["transaction_id"]])
        # Native ID has been recycled outside Gateway before the delayed read.
        # Identical rows cannot confer the old transaction's publication right.
    code, result = gateway.execute_gateway(["--state-dir", str(state_dir), "verify", pending["transaction_id"]],
        env=_env(tmp_path, version=version), client_factory=lambda _url: client)
    assert code == 2, result
    assert result["error_code"] in {"TRANSPORT_HANDLE_GENERATION_DRIFT", "TRANSPORT_HANDLE_LIFETIME_RETIRED"}
    assert result["automatic_retry"] is False
    assert result["verified"] is False
    assert result["state"] == "verification_failed"
    assert result["verification"]["business_state_verified"] is False
    shown = invoke(["transaction-show", pending["transaction_id"]])
    assert shown["state"] == "verification_failed"
    verifications = [event for event in shown["events"] if event["event_type"] == "verification_recorded"]
    assert verifications[-1]["details"]["verification"]["business_state_verified"] is False


def test_transport_retired_lifetime_capacity_is_reusable_and_old_verification_stays_rejected(tmp_path: Path, monkeypatch) -> None:
    import wwise_waapi.runtime_transport_handles as handles
    monkeypatch.setattr(handles, "_MAX_RECORDS", 2)
    client = _RuntimeControlDraftClient(tmp_path)
    original = client.call
    active = {}
    next_id = 0
    def call(uri, args=None, options=None):
        nonlocal next_id
        if uri == "ak.wwise.core.transport.create":
            native_id = next_id
            next_id += 1
            active[native_id] = {"transport": native_id, "object": client.target_id, "gameObject": 1}
            return {"transport": native_id}
        if uri == "ak.wwise.core.transport.destroy":
            active.pop(args["transport"])
            return {}
        if uri == "ak.wwise.core.transport.getList":
            return {"list": list(active.values())}
        if uri == TRANSPORT_GET_STATE_URI:
            return {"state": "stopped"}
        return original(uri, args, options)
    client.call = call
    state_dir = tmp_path / "state"
    for _ in range(3):
        created, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.create")
        invoke(["execute", created["transaction_id"]])
        verified = invoke(["verify", created["transaction_id"]])
        handle = verified["agent_result"]["business_result"]["transport_handle"]
        destroyed, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.destroy", ("--transport-handle", handle))
        invoke(["execute", destroyed["transaction_id"]])
        verified = invoke(["verify", destroyed["transaction_id"]])
        assert verified["agent_result"]["business_result"]["retired_transport_handle_count"] == 1
    assert next_id == 3 and active == {}
    assert len(list((state_dir / "runtime-transport-handles-v1" / "lifetimes").iterdir())) <= 2


def test_transport_unknown_destroy_outcome_consumes_authority_before_dispatch(tmp_path: Path) -> None:
    client = _RuntimeControlDraftClient(tmp_path)
    original = client.call
    attempts = []
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.transport.create":
            return {"transport": 74}
        if uri == TRANSPORT_GET_STATE_URI:
            return {"state": "stopped"}
        if uri == "ak.wwise.core.transport.destroy":
            attempts.append(uri)
            raise RuntimeError("native reply lost")
        return original(uri, args, options)
    client.call = call
    state_dir = tmp_path / "state"
    created, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.create")
    invoke(["execute", created["transaction_id"]])
    verified = invoke(["verify", created["transaction_id"]])
    handle = verified["agent_result"]["business_result"]["transport_handle"]
    destroyed, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.destroy", ("--transport-handle", handle))
    prefix = ["--state-dir", str(state_dir)]
    code, result = gateway.execute_gateway([*prefix, "execute", destroyed["transaction_id"]], env=_env(tmp_path), client_factory=lambda _url: client)
    assert code == 2 and result["automatic_retry"] is False, result
    code, result = gateway.execute_gateway([*prefix, "core-call", TRANSPORT_GET_STATE_URI, "--transport-handle", handle],
        env=_env(tmp_path), client_factory=lambda _url: client)
    assert code == 2 and result["error_code"] == "TRANSPORT_HANDLE_RETIRED", result
    assert attempts == ["ak.wwise.core.transport.destroy"]


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("subject", ("Busses", "AudioObjects"))
def test_profiler_diagnostics_requests_every_pinned_native_projection_field(tmp_path: Path, version: str, subject: str) -> None:
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    operation = "ak.wwise.core.profiler.get" + subject
    calls = []
    def call(uri, args=None, options=None):
        calls.append((uri, args, options))
        if uri == operation:
            return {"return": []}
        return original(uri, args, options)
    client.call = call
    code, payload = gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), "core-call", operation,
        "--profiler-position", "123", "--result-view", "diagnostics"], env=_env(tmp_path, version=version), client_factory=lambda _url: client)
    assert code == 0, payload
    returned = next(options["return"] for uri, _args, options in calls if uri == operation)
    expected = ({"mixerID"} if version in {"2021.1", "2022.1"} else {"effectCount"}) if subject == "Busses" else {"busID", "effectClassID", "effectIndex"}
    assert expected <= set(returned)
    if subject == "Busses":
        assert ("effectCount" if version in {"2021.1", "2022.1"} else "mixerID") not in returned


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("view,expected", (("capture-defaults", {}), ("empty-selection", {"return": []})))
@pytest.mark.parametrize("operation", (GET_VOICES_URI, "ak.wwise.core.profiler.getBusses", "ak.wwise.core.profiler.getAudioObjects"))
def test_profiler_native_default_and_explicit_empty_projection_remain_distinct(tmp_path: Path, version: str, view: str, expected: dict, operation: str) -> None:
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    calls = []
    def call(uri, args=None, options=None):
        calls.append((uri, args, options))
        return {"return": []} if uri == operation else original(uri, args, options)
    client.call = call
    code, payload = gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), "core-call", operation,
        "--profiler-position", "123", "--result-view", view], env=_env(tmp_path, version=version), client_factory=lambda _url: client)
    assert code == 0, payload
    assert next(options for uri, _args, options in calls if uri == operation) == expected


def test_transport_preview_cannot_transfer_to_recycled_identical_native_row(tmp_path: Path) -> None:
    client = _RuntimeControlDraftClient(tmp_path)
    original = client.call
    calls = []
    def call(uri, args=None, options=None):
        calls.append(uri)
        if uri == "ak.wwise.core.transport.create":
            return {"transport": 74}
        if uri == "ak.wwise.core.transport.destroy":
            return {}
        if uri == TRANSPORT_GET_STATE_URI:
            return {"state": "stopped"}
        return original(uri, args, options)
    client.call = call
    state_dir = tmp_path / "state"
    first, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.create")
    invoke(["execute", first["transaction_id"]])
    first_result = invoke(["verify", first["transaction_id"]])
    handle = first_result["agent_result"]["business_result"]["transport_handle"]
    old_destroy, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.destroy", ("--transport-handle", handle))
    replacement, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.create")
    invoke(["execute", replacement["transaction_id"]])
    invoke(["verify", replacement["transaction_id"]])
    calls.clear()
    code, result = gateway.execute_gateway(["--state-dir", str(state_dir), "execute", old_destroy["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _url: client)
    assert code == 2, result
    assert result["status"] == "repreview_required"
    assert result["error_code"] == "TRANSPORT_HANDLE_GENERATION_DRIFT"
    assert "ak.wwise.core.transport.destroy" not in calls


def test_transport_state_read_maps_gateway_handle_without_exposing_native_id(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    project_root = tmp_path / "project"
    project_root.mkdir()
    project_file = project_root / "SampleProject.wproj"
    project_file.write_text("fixture", encoding="utf-8")
    transport_handle = _issue_transport_handle(
        state_dir,
        project_path=project_file,
        transport_id=0,
    )
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [
                {
                    "displayName": "Wwise",
                    "isCommandLine": False,
                    "apiVersion": 1,
                    "platform": "macosx",
                    "configuration": "release",
                    "version": {
                        "year": 2025,
                        "major": 1,
                        "minor": 0,
                        "build": 1,
                        "displayName": "v2025.1.0.1",
                    },
                }
            ],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                    "name": "SampleProject",
                    "path": str(project_file),
                }
            ],
            "ak.wwise.core.transport.getList": [
                {
                    "list": [
                        {
                            "transport": 0,
                            "object": "{11111111-1111-1111-1111-111111111111}",
                            "gameObject": 1,
                        }
                    ]
                }
            ],
            TRANSPORT_GET_STATE_URI: [{"state": "paused"}],
        }
    )

    code, payload = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "core-call",
            TRANSPORT_GET_STATE_URI,
            "--transport-handle",
            transport_handle,
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert (TRANSPORT_GET_STATE_URI, {"transport": 0}, {}) in client.calls
    assert payload["agent_result"] == {
        "transport_handle": transport_handle,
        "state": "paused",
    }
    assert payload["business_request"] == {
        "operation": TRANSPORT_GET_STATE_URI,
        "transport_handle": transport_handle,
        "max_results": 1,
    }


def test_transport_state_rejects_handle_store_inside_live_project(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    project_file = project_root / "SampleProject.wproj"
    project_file.write_text("fixture", encoding="utf-8")
    state_dir = project_root / ".waapi-skill-state"
    transport_handle = _issue_transport_handle(
        state_dir,
        project_path=project_file,
    )
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [
                {
                    "displayName": "Wwise",
                    "isCommandLine": False,
                    "apiVersion": 1,
                    "platform": "macosx",
                    "configuration": "release",
                    "version": {
                        "year": 2025,
                        "major": 1,
                        "minor": 0,
                        "build": 1,
                        "displayName": "v2025.1.0.1",
                    },
                }
            ],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                    "name": "SampleProject",
                    "path": str(project_file),
                }
            ],
        }
    )

    code, payload = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "core-call",
            TRANSPORT_GET_STATE_URI,
            "--transport-handle",
            transport_handle,
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert "outside the live Wwise project" in payload["message"]
    assert all(call[0] != TRANSPORT_GET_STATE_URI for call in client.calls)


def test_transport_state_rejects_invented_native_id_before_connection(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        [

            "core-call",
            TRANSPORT_GET_STATE_URI,
            "--transport-handle",
            "74",
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda url: pytest.fail(f"native transport connected to {url}"),
    )

    assert code == 2
    assert "copied exactly" in payload["message"]


def test_transport_state_returns_authoring_boundary_before_transport_dispatch(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [
                {
                    "displayName": "WwiseConsole",
                    "isCommandLine": True,
                    "apiVersion": 1,
                    "platform": "macosx",
                    "configuration": "release",
                    "version": {
                        "year": 2025,
                        "major": 1,
                        "minor": 0,
                        "build": 1,
                        "displayName": "v2025.1.0.1",
                    },
                }
            ],
        }
    )

    code, payload = gateway.execute_gateway(
        [

            "core-call",
            TRANSPORT_GET_STATE_URI,
            "--transport-handle",
            "trh1-" + "61" * 16,
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert payload["error_code"] == "AUTHORING_HOST_REQUIRED"
    assert payload["executed"] is False
    assert client.calls == [("ak.wwise.core.getInfo", None, None)]


def test_transport_state_rejects_well_formed_but_non_live_handle_before_state_call(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    project_root = tmp_path / "project"
    project_root.mkdir()
    project_file = project_root / "SampleProject.wproj"
    project_file.write_text("fixture", encoding="utf-8")
    transport_handle = _issue_transport_handle(
        state_dir,
        project_path=project_file,
    )
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [
                {
                    "displayName": "Wwise",
                    "isCommandLine": False,
                    "apiVersion": 1,
                    "platform": "macosx",
                    "configuration": "release",
                    "version": {
                        "year": 2025,
                        "major": 1,
                        "minor": 0,
                        "build": 1,
                        "displayName": "v2025.1.0.1",
                    },
                }
            ],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                    "name": "SampleProject",
                    "path": str(project_file),
                }
            ],
            "ak.wwise.core.transport.getList": [{"list": []}],
        }
    )

    code, payload = gateway.execute_gateway(
        [
             "--state-dir", str(state_dir),
            "core-call", TRANSPORT_GET_STATE_URI,
            "--transport-handle", transport_handle,
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert payload["error_code"] == "TRANSPORT_HANDLE_NOT_LIVE"
    assert all(call[0] != TRANSPORT_GET_STATE_URI for call in client.calls)


@pytest.mark.parametrize(
    "operation",
    (PROFILER_MOVE_CURSOR_URI, PROFILER_SET_CURSOR_TIME_URI),
)
def test_profiler_cursor_controls_expose_one_business_draft_without_typed_fields(
    tmp_path: Path,
    operation: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", "2025.1", "request-schema", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert code == 0, payload
    assert payload["business_adapter"]["contract"] == (
        "waapi-skill.runtime-control-business/v1"
    )
    assert payload["continuation"] == {
        "subcommand": "draft-start",
        "gateway_argv": ["draft-start", operation],
        "copy_exactly": True,
        "append_arguments": "forbidden",
    }
    encoded = json.dumps(payload, sort_keys=True)
    assert "typed-call" not in encoded
    assert '"position":' not in encoded
    assert '"time":' not in encoded


def test_profiler_cursor_control_draft_starts_with_one_closed_declaration(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        [

            "--state-dir",
            str(tmp_path / "state"),
            "draft-start",
            PROFILER_MOVE_CURSOR_URI,
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )

    assert code == 0, payload
    next_action = payload["draft"]["next_action_binding"]
    assert next_action["required_next_phase"] == (
        "declare_complete_runtime_control_plan"
    )
    declaration = next_action["declaration"]
    assert "draft-declare-runtime-control-plan" in declaration["fixed_argv_prefix"]
    assert declaration["append"] == [
        "--cursor-move first-frame|last-frame|next-frame|previous-frame"
    ]
    assert declaration["native_request_input"] == "forbidden"


class _RuntimeControlDraftClient:
    target_id = "{11111111-1111-1111-1111-111111111111}"
    meter_id = "{22222222-2222-2222-2222-222222222222}"

    def __init__(self, tmp_path: Path, *, version: str = "2025.1") -> None:
        self.version = version
        self.project_root = tmp_path / "SampleProject"
        self.project_root.mkdir()
        self.project_file = self.project_root / "SampleProject.wproj"
        self.project_file.write_text("fixture", encoding="utf-8")

    def call(self, uri: str, args: object = None, options: object = None) -> object:
        if uri == "ak.wwise.core.remote.getConnectionStatus":
            return {"isConnected": False, "status": "Not connected"}
        if uri == "ak.wwise.core.getInfo":
            year, major = (int(part) for part in self.version.split("."))
            return {
                "displayName": "Wwise",
                "isCommandLine": False,
                "sessionId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "processId": 4242,
                "processPath": "/Applications/Wwise/Wwise.app",
                "apiVersion": 1,
                "platform": "macosx",
                "configuration": "release",
                "version": {
                    "year": year,
                    "major": major,
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
        if uri == "ak.wwise.core.transport.getList":
            return {
                "list": [
                    {
                        "transport": 74,
                        "object": self.target_id,
                        "gameObject": 1,
                    }
                ]
            }
        if (
            uri == "ak.wwise.core.object.get"
            and self.version == "2021.1"
            and isinstance(args, dict)
            and args.get("waql") == "from type Project take 1"
        ):
            return {
                "return": [
                    {
                        "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                        "name": "SampleProject",
                        "type": "Project",
                        "path": "\\",
                        "filePath": str(self.project_file),
                    }
                ]
            }
        if uri == "ak.wwise.core.object.get" and isinstance(args, dict):
            requested = args.get("from", {}).get("id", [])
            rows = []
            for object_id in requested:
                if str(object_id).upper() == self.target_id:
                    rows.append(
                        {
                            "id": self.target_id,
                            "name": "Play_Weather",
                            "type": "Event",
                            "path": r"\Events\Default Work Unit\Play_Weather",
                        }
                    )
                elif str(object_id).upper() == self.meter_id:
                    rows.append(
                        {
                            "id": self.meter_id,
                            "name": "Master Audio Bus",
                            "type": "Bus",
                            "path": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus",
                        }
                    )
                else:
                    raise AssertionError(f"unexpected object id {object_id}")
            return {"return": rows}
        raise AssertionError(f"unexpected WAAPI call {uri}: {args!r} {options!r}")

    def disconnect(self) -> None:
        return None


class _RemoteLifecycleClient(_RuntimeControlDraftClient):
    def __init__(self, tmp_path: Path, *, version: str, observation: str):
        super().__init__(tmp_path, version=version)
        self.observation = observation
        self.connected = False
        self.calls = []

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.remote.connect":
            self.connected = True
            return {}
        if uri == "ak.wwise.core.remote.disconnect":
            self.connected = False
            return {}
        console = {"host": "127.0.0.2" if self.observation == "wrong-host" else "127.0.0.1",
            "appName": "Wrong Game" if self.observation == "wrong-app" else "Game Preview",
            "name": "Remote Console", "platform": "Windows", "customPlatform": "Windows"}
        if uri == "ak.wwise.core.remote.getConnectionStatus":
            return {"isConnected": self.connected, "status": "Connected" if self.connected else "Not connected",
                **({"console": console} if self.connected and self.observation != "missing-console" else {})}
        if uri == "ak.wwise.core.remote.getAvailableConsoles":
            rows = [{**console, "commandPort": 24026 if self.observation == "wrong-port" else 24024,
                **({"notificationPort": 24025} if self.version == "2021.1" else {})}]
            if self.observation == "ambiguous-port":
                rows.append({**rows[0], "commandPort": 24027})
            return {"consoles": rows}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version,observation", [
    (version, observation) for version in ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"]
    for observation in ["exact", "wrong-host", "wrong-app", "exact-port", "wrong-port", "ambiguous-port", "hostname-alias", "missing-console", "connection-drift"]
] + [(version, "host-port") for version in ["2022.1", "2023.1", "2024.1", "2025.1"]])
def test_remote_public_lifecycle_verifies_the_requested_host_and_application(tmp_path: Path, version: str, observation: str) -> None:
    client = _RemoteLifecycleClient(tmp_path, version=version, observation=observation)
    state = tmp_path / "remote-state"
    env = _env(tmp_path, version=version)
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(state), *argv], env=env, client_factory=lambda _: client)
    code, started = run("draft-start", "ak.wwise.core.remote.connect")
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    host = "game-host" if observation == "hostname-alias" else "127.0.0.1:24024" if observation == "host-port" else "127.0.0.1"
    operands = ["--remote-host", host, "--application-name", "Game Preview"]
    if observation.endswith("port") and observation != "host-port":
        operands += ["--command-port", "24024"]
        if version == "2021.1":
            operands += ["--notification-port", "24025"]
    code, declared = run("draft-declare-runtime-control-plan", draft_id, "--task-authority", authority,
        "--expected-revision", str(started["draft"]["revision"]), *operands)
    assert code == 0, declared
    code, checked = run("draft-check", draft_id, "--task-authority", authority, "--expected-revision", str(declared["draft"]["revision"]))
    assert code == 0, checked
    code, previewed = run("preview-from-draft", draft_id, "--task-authority", authority, "--expected-revision", str(checked["draft"]["revision"]))
    assert code == 0, previewed
    transaction = previewed["transaction_id"]
    snapshot = TransactionStore(state).load_snapshot(transaction)
    code, confirmed = run("confirm", transaction, "--confirmation-token", snapshot.confirmation_token)
    assert code == 0, confirmed
    if observation == "connection-drift":
        client.connected = True
    code, executed = run("execute", transaction)
    if observation == "connection-drift":
        assert code == 2, executed
        assert not any(call[0] == "ak.wwise.core.remote.connect" for call in client.calls)
        return
    assert code == 0, executed
    code, verified = run("verify", transaction)
    diagnostic = json.dumps(verified, ensure_ascii=False)
    if observation == "exact":
        assert code == 0 and verified["verified"] is True, diagnostic
    elif observation in {"wrong-host", "wrong-app"}:
        assert code == 2 and verified.get("verification", {}).get("status") == "verification_failed", diagnostic
    else:
        assert code == 0 and verified["verified"] is False, verified
        assert verified["verification"]["business_state_verified"] is False
        assert verified["verification"]["verification_strength"] == "partial_remote_target_observation"
        if observation.endswith("port"):
            observed = next(row for row in verified["verification"]["readbacks"] if row.get("kind") == "remote-target-observation")
            assert any(row["reason"] == "connected_status_has_no_port_or_process_identity" for row in observed["unresolved"])
            assert not any(row["field"] in {"commandPort", "notificationPort"} for row in observed["checks"])
            if observation in {"exact-port", "wrong-port", "host-port"}:
                corroboration = next(row for row in observed["corroboration"] if row["field"] == "commandPort")
                assert corroboration["matches_requested"] is (observation != "wrong-port")
                assert corroboration["connected_instance_identity_proven"] is False
    assert len([call for call in client.calls if call[0] == "ak.wwise.core.remote.connect"]) == 1
    code, rejected = run("execute", transaction)
    assert code == 2, rejected
    assert len([call for call in client.calls if call[0] == "ak.wwise.core.remote.connect"]) == 1


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("drift", [False, True])
def test_remote_disconnect_public_preview_preserves_connection_identity(tmp_path: Path, version: str, drift: bool) -> None:
    client = _RemoteLifecycleClient(tmp_path, version=version, observation="exact")
    client.connected = True
    state = tmp_path / "disconnect-state"
    env = _env(tmp_path, version=version)
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(state), *argv], env=env, client_factory=lambda _: client)
    code, schema = run("request-schema", "ak.wwise.core.remote.disconnect")
    assert code == 0, schema
    code, previewed = run(*schema["continuation"]["gateway_argv"])
    assert code == 0, previewed
    transaction = previewed["transaction_id"]
    token = TransactionStore(state).load_snapshot(transaction).confirmation_token
    code, confirmed = run("confirm", transaction, "--confirmation-token", token)
    assert code == 0, confirmed
    if drift:
        client.observation = "wrong-app"
    code, executed = run("execute", transaction)
    if drift:
        assert code == 2, executed
        assert not any(call[0] == "ak.wwise.core.remote.disconnect" for call in client.calls)
    else:
        assert code == 0, executed
        code, verified = run("verify", transaction)
        assert code == 0 and verified["verified"] is True, verified
        assert len([call for call in client.calls if call[0] == "ak.wwise.core.remote.disconnect"]) == 1
    code, rejected = run("execute", transaction)
    assert code == 2, rejected
    assert len([call for call in client.calls if call[0] == "ak.wwise.core.remote.disconnect"]) == (0 if drift else 1)


@pytest.mark.parametrize(
    "operation",
    ("ak.wwise.core.remote.connect", "ak.wwise.core.transport.destroy"),
)
def test_remote_and_transport_control_return_authoring_boundary_before_project_read(
    tmp_path: Path,
    operation: str,
) -> None:
    state_dir = tmp_path / operation
    code, started = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=set_gateway_config(_env(tmp_path, version="2022.1"), wwise_version="2022.1"),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [
                {
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
            ],
        }
    )

    code, payload = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-declare-runtime-control-plan",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(started["draft"]["revision"]),
        ],
        env=set_gateway_config(_env(tmp_path, version="2022.1"), wwise_version="2022.1"),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert payload["error_code"] == "AUTHORING_HOST_REQUIRED"
    assert payload["executed"] is False
    assert client.calls == [("ak.wwise.core.getInfo", None, None)]


@pytest.mark.parametrize(
    ("operation", "declaration", "expected_args"),
    (
        (
            PROFILER_MOVE_CURSOR_URI,
            ("--cursor-move", "previous-frame"),
            {"position": "previous"},
        ),
        (
            PROFILER_SET_CURSOR_TIME_URI,
            ("--cursor-target-ms", "1234"),
            {"time": 1234},
        ),
    ),
)
def test_profiler_cursor_business_plan_seals_gateway_owned_native_preview(
    tmp_path: Path,
    operation: str,
    declaration: tuple[str, str],
    expected_args: dict[str, object],
) -> None:
    state_dir = tmp_path / "state"
    client = _RuntimeControlDraftClient(tmp_path)
    code, started = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    code, declared = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-declare-runtime-control-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(started["draft"]["revision"]),
            *declaration,
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda _url: client,
    )
    assert code == 0, declared

    code, checked = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked

    code, previewed = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked["draft"]["revision"]),
        ],
        env=set_gateway_config(_env(tmp_path), wwise_version="2025.1"),
        client_factory=lambda _url: client,
    )
    assert code == 0, previewed
    artifact = TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact
    assert artifact["request"]["arguments"] == {
        "api": operation,
        "args": expected_args,
        "options": {},
    }
    assert artifact["prepared_operation"]["verification_plan"]["kind"] == (
        "profiler-user-cursor"
    )


class _ProfilerCursorControlClient(_RuntimeControlDraftClient):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path)
        self.calls: list[tuple[str, object, object]] = []
        self.control_result: object = {"return": 1230}
        self.cursor_result: object = {"return": 1230}

    def call(self, uri: str, args: object = None, options: object = None) -> object:
        self.calls.append((uri, args, options))
        if uri in {PROFILER_MOVE_CURSOR_URI, PROFILER_SET_CURSOR_TIME_URI}:
            return self.control_result
        if uri == GET_CURSOR_TIME_URI:
            if isinstance(self.cursor_result, Exception):
                raise self.cursor_result
            return self.cursor_result
        return super().call(uri, args, options)


def test_profiler_cursor_setter_verifies_returned_snapped_time_through_public_transaction(tmp_path: Path) -> None:
    client = _ProfilerCursorControlClient(tmp_path)
    state_dir = tmp_path / "cursor-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state_dir,
        PROFILER_SET_CURSOR_TIME_URI, ("--cursor-target-ms", "1234"))
    assert not any(uri in {PROFILER_SET_CURSOR_TIME_URI, GET_CURSOR_TIME_URI} for uri, _, _ in client.calls)
    executed = invoke(["execute", previewed["transaction_id"]])
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is True, verified
    assert verified["verification"]["business_state_verified"] is True
    assert verified["verification"]["verification_strength"] == "independent_profiler_user_cursor_observation"
    shown = invoke(["transaction-show", previewed["transaction_id"]])
    evidence = next(event["details"]["verification"] for event in reversed(shown["events"])
        if event["event_type"] == "verification_recorded")
    assert {"uri": GET_CURSOR_TIME_URI, "args": {"cursor": "user"}, "options": {},
        "result": {"return": 1230}} in evidence["readbacks"]
    assert "Capture data completeness" in evidence["message"]
    assert (PROFILER_SET_CURSOR_TIME_URI, {"time": 1234}, {}) in client.calls
    assert sum(uri == GET_CURSOR_TIME_URI for uri, _, _ in client.calls) == 1
    assert (GET_CURSOR_TIME_URI, {"cursor": "user"}, {}) in client.calls
    code, rejected = gateway.execute_gateway(["--state-dir", str(state_dir), "execute", previewed["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _url: client)
    assert code == 2, rejected
    assert sum(uri == PROFILER_SET_CURSOR_TIME_URI for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("move,native,time_ms", [
    ("first-frame", "first", 0), ("last-frame", "last", 4560),
    ("next-frame", "next", 0), ("previous-frame", "previous", 0),
])
def test_profiler_cursor_moves_verify_observed_time_without_requiring_motion(
    tmp_path: Path, move: str, native: str, time_ms: int,
) -> None:
    client = _ProfilerCursorControlClient(tmp_path)
    client.control_result = client.cursor_result = {"return": time_ms}
    previewed, invoke = _public_runtime_preview(tmp_path, client, tmp_path / "cursor-state",
        PROFILER_MOVE_CURSOR_URI, ("--cursor-move", move))
    executed = invoke(["execute", previewed["transaction_id"]])
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is True, verified
    assert (PROFILER_MOVE_CURSOR_URI, {"position": native}, {}) in client.calls
    assert sum(uri == GET_CURSOR_TIME_URI for uri, _, _ in client.calls) == 1
    assert verified["verification"]["verification_scope"]["cursor_observation"] == {
        "kind": "profiler-user-cursor-observation", "returned_time_ms": time_ms,
        "observed_time_ms": time_ms, "capture_data_verified": False, "outcome": "matched"}


@pytest.mark.parametrize("operation,declaration", [
    (PROFILER_MOVE_CURSOR_URI, ("--cursor-move", "next-frame")),
    (PROFILER_SET_CURSOR_TIME_URI, ("--cursor-target-ms", "1234")),
])
@pytest.mark.parametrize("returned,observed,outcome", [
    (1230, 1234, "changed"), (1230, 1220, "changed"),
    (1230, -1, "unavailable"), (-1, -1, "unavailable"), (-1, 1230, "unavailable"),
])
def test_profiler_cursor_changed_or_unavailable_observation_never_verifies_effect(
    tmp_path: Path, operation: str, declaration: tuple[str, ...], returned: int, observed: int, outcome: str,
) -> None:
    client = _ProfilerCursorControlClient(tmp_path)
    client.control_result, client.cursor_result = {"return": returned}, {"return": observed}
    state_dir = tmp_path / "cursor-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state_dir, operation, declaration)
    executed = invoke(["execute", previewed["transaction_id"]])
    code, verified = gateway.execute_gateway(["--state-dir", str(state_dir), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path), client_factory=lambda _url: client)
    assert code == (2 if outcome == "changed" else 0), verified
    assert verified["verified"] is False
    assert verified["state"] == ("verification_failed" if outcome == "changed" else "result_schema_checked")
    assert verified["verification"]["business_state_verified"] is False
    assert verified["verification"]["verification_scope"]["cursor_observation"]["outcome"] == outcome
    assert verified["automatic_retry"] is False
    code, rejected = gateway.execute_gateway(["--state-dir", str(state_dir), "execute", previewed["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _url: client)
    assert code == 2, rejected
    assert sum(uri == operation for uri, _, _ in client.calls) == 1
    assert sum(uri == GET_CURSOR_TIME_URI for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("stage", ("control", "readback"))
@pytest.mark.parametrize("native_result", [
    {}, {"time": 1230}, {"return": True}, {"return": 1230.5}, {"return": None},
    {"return": -2}, {"return": 1230, "time": 1230},
], ids=("missing", "wrong-field", "boolean", "fraction", "null", "invalid-negative", "extra-field"))
def test_profiler_cursor_malformed_result_cannot_verify_a_valid_looking_other_result(
    tmp_path: Path, stage: str, native_result: dict[str, object],
) -> None:
    client = _ProfilerCursorControlClient(tmp_path)
    if stage == "control":
        client.control_result = native_result
    else:
        client.cursor_result = native_result
    state_dir = tmp_path / "cursor-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state_dir,
        PROFILER_SET_CURSOR_TIME_URI, ("--cursor-target-ms", "1234"))
    executed = invoke(["execute", previewed["transaction_id"]])
    code, verified = gateway.execute_gateway(["--state-dir", str(state_dir), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path), client_factory=lambda _url: client)
    assert code == 2, verified
    assert verified["state"] == "verification_failed"
    assert verified["verification"]["business_state_verified"] is False
    assert verified["verification"]["verification_scope"]["cursor_observation"]["outcome"] == (
        "malformed" if stage == "readback" else "malformed_control_result")
    assert verified["automatic_retry"] is False
    assert sum(uri == GET_CURSOR_TIME_URI for uri, _, _ in client.calls) == (1 if stage == "readback" else 0)
    assert len(json.dumps(verified, ensure_ascii=False).encode("utf-8")) < gateway.MAX_GATEWAY_RESULT_JSON_BYTES


@pytest.mark.parametrize("native_result,error_code", [
    ([], "INVALID_READBACK"), (RuntimeError("cursor observation unavailable"), "READBACK_FAILED"),
])
def test_profiler_cursor_read_error_retains_executed_unverified_transaction(
    tmp_path: Path, native_result: object, error_code: str,
) -> None:
    client = _ProfilerCursorControlClient(tmp_path)
    client.cursor_result = native_result
    state_dir = tmp_path / "cursor-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state_dir,
        PROFILER_MOVE_CURSOR_URI, ("--cursor-move", "last-frame"))
    executed = invoke(["execute", previewed["transaction_id"]])
    code, verified = gateway.execute_gateway(["--state-dir", str(state_dir), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path), client_factory=lambda _url: client)
    assert code == 2, verified
    assert verified["status"] == "verification_deferred"
    assert verified["state"] == "executed_unverified"
    assert verified["error_code"] == error_code
    assert verified["automatic_retry"] is False
    assert verified["manual_verification_retry_allowed"] is True
    code, rejected = gateway.execute_gateway(["--state-dir", str(state_dir), "execute", previewed["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _url: client)
    assert code == 2, rejected
    assert sum(uri == PROFILER_MOVE_CURSOR_URI for uri, _, _ in client.calls) == 1
    assert sum(uri == GET_CURSOR_TIME_URI for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1"))
@pytest.mark.parametrize("operation", (PROFILER_MOVE_CURSOR_URI, PROFILER_SET_CURSOR_TIME_URI))
@pytest.mark.parametrize("command", ("request-schema", "draft-start"))
def test_profiler_cursor_controls_do_not_offer_a_route_on_earlier_definitions(
    tmp_path: Path, version: str, operation: str, command: str,
) -> None:
    code, result = gateway.execute_gateway([command, operation], env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"unavailable cursor route connected to {url}"))
    assert code == 2, result
    assert result["error_code"] == "TypedRequestError", result
    assert operation in result["message"] and version in result["message"], result


def _seal_runtime_control_preview(
    tmp_path: Path,
    *,
    operation: str,
    version: str,
    declaration: tuple[str, ...],
) -> dict[str, object]:
    state_dir = tmp_path / ("state-" + operation.rsplit(".", 1)[-1])
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    declaration_values = tuple(declaration)
    if "transport-session-0000004a" in declaration_values:
        issued_handle = _issue_transport_handle(
            state_dir,
            project_path=client.project_file,
            version=version,
        )
        declaration_values = tuple(
            issued_handle if value == "transport-session-0000004a" else value
            for value in declaration_values
        )
    code, started = gateway.execute_gateway(
        [

            "--state-dir", str(state_dir),
            "draft-start", operation,
        ],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    code, declared = gateway.execute_gateway(
        [

            "--state-dir", str(state_dir),
            "draft-declare-runtime-control-plan", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(started["draft"]["revision"]),
            *declaration_values,
        ],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, declared
    code, checked = gateway.execute_gateway(
        [

            "--state-dir", str(state_dir),
            "draft-check", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(declared["draft"]["revision"]),
        ],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked
    code, previewed = gateway.execute_gateway(
        [

            "--state-dir", str(state_dir),
            "preview-from-draft", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(checked["draft"]["revision"]),
        ],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, previewed
    return TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
def test_remote_notification_port_is_disclosed_and_preserved_as_native_unused_input(tmp_path: Path, version: str) -> None:
    code, schema = gateway.execute_gateway(["request-schema", "ak.wwise.core.remote.connect"],
        env=_env(tmp_path, version=version), client_factory=lambda _: pytest.fail("schema must be offline"))
    assert code == 0, schema
    declaration = schema["business_adapter"]["declaration"]
    assert "notification_port" in declaration["optional_fields"]
    assert declaration["field_semantics"]["notification_port"]["native_effect"] == "unused"
    assert declaration["field_semantics"]["notification_port"]["selector_used_by_native"] is False
    assert declaration["field_semantics"]["notification_port"]["target_identity_evidence"] is False
    artifact = _seal_runtime_control_preview(tmp_path, operation="ak.wwise.core.remote.connect", version=version,
        declaration=("--remote-host", "127.0.0.1", "--notification-port", "0"))
    assert artifact["request"]["arguments"]["args"] == {"host": "127.0.0.1", "notificationPort": 0}


@pytest.mark.parametrize(
    ("operation", "version", "declaration", "expected_arguments"),
    (
        (
            "ak.wwise.core.profiler.enableProfilerData",
            "2021.1",
            (
                "--capture-data", "soundbanks", "enable",
                "--capture-data", "inactive-game-syncs", "disable",
            ),
            {
                "args": {
                    "dataTypes": [
                        {"dataType": "soundBanks", "enable": True},
                        {"dataType": "inactiveGameSyncs", "enable": False},
                    ]
                },
                "options": {},
            },
        ),
        (
            "ak.wwise.core.profiler.enableProfilerData",
            "2025.1",
            ("--capture-data", "customer-support-data", "enable"),
            {
                "args": {
                    "dataTypes": [
                        {"dataType": "customerSupportData", "enable": True}
                    ]
                },
                "options": {},
            },
        ),
        (
            "ak.wwise.core.log.addItem",
            "2025.1",
            (
                "--message", 'Build "Weather"\nline 2; $HOME',
                "--log-channel", "soundbank-generation",
                "--severity", "warning",
            ),
            {
                "args": {
                    "message": 'Build "Weather"\nline 2; $HOME',
                    "channel": "soundbankGenerate",
                    "severity": "Warning",
                },
                "options": {},
            },
        ),
        (
            "ak.wwise.core.log.clear",
            "2023.1",
            ("--log-channel", "source-control"),
            {"args": {"channel": "sourceControl"}, "options": {}},
        ),
        (
            "ak.wwise.core.remote.connect",
            "2021.1",
            (
                "--remote-host", "127.0.0.1",
                "--application-name", "Game Preview",
                "--command-port", "24024",
                "--notification-port", "24025",
            ),
            {
                "args": {
                    "host": "127.0.0.1",
                    "appName": "Game Preview",
                    "commandPort": 24024,
                    "notificationPort": 24025,
                },
                "options": {},
            },
        ),
        (
            "ak.wwise.core.transport.destroy",
            "2025.1",
            ("--transport-handle", "transport-session-0000004a"),
            {"args": {"transport": 74}, "options": {}},
        ),
            (
                "ak.wwise.core.transport.executeAction",
            "2025.1",
            ("--audition-action", "toggle-play-stop", "--transport-scope", "all-active"),
            {"args": {"action": "playStop"}, "options": {}},
        ),
        (
            "ak.wwise.core.transport.useOriginals",
            "2023.1",
            ("--audition-media", "converted"),
            {"args": {"enable": False}, "options": {}},
        ),
    ),
)
def test_runtime_control_business_values_compile_to_exact_native_preview(
    tmp_path: Path,
    operation: str,
    version: str,
    declaration: tuple[str, ...],
    expected_arguments: dict[str, object],
) -> None:
    artifact = _seal_runtime_control_preview(
        tmp_path,
        operation=operation,
        version=version,
        declaration=declaration,
    )
    assert artifact["request"]["arguments"] == {
        "api": operation,
        **expected_arguments,
    }
    if operation == "ak.wwise.core.remote.connect":
        assert artifact["prepared_operation"]["verification_plan"]["kind"] == (
            "remote-connection-state"
        )
        assert artifact["prepared_operation"]["cleanup"]["companion_request"]["api"] == (
            "ak.wwise.core.remote.disconnect"
        )


def test_profiler_save_capture_joins_authorized_directory_and_prof_extension(
    tmp_path: Path,
) -> None:
    output = tmp_path / "captures"
    output.mkdir()
    capture_name = "Weather A" if sys.platform == "win32" else 'Weather "A"'
    artifact = _seal_runtime_control_preview(
        tmp_path,
        operation="ak.wwise.core.profiler.saveCapture",
        version="2025.1",
        declaration=(
            "--capture-output-directory", str(output),
            "--capture-name", capture_name,
        ),
    )

    assert artifact["request"]["arguments"] == {
        "api": "ak.wwise.core.profiler.saveCapture",
        "args": {"file": str(output / f"{capture_name}.prof")},
        "options": {},
        "io_root": str(output),
    }


@pytest.mark.parametrize(
    ("operation", "version", "role", "object_id", "handle_flag", "extra", "expected_args"),
    (
        (
            "ak.wwise.core.transport.create",
            "2025.1",
            "target",
            _RuntimeControlDraftClient.target_id,
            "--target-handle",
            ("--game-object-id", "18446744073709551615"),
            {
                "object": _RuntimeControlDraftClient.target_id,
                "gameObject": 18446744073709551615,
            },
        ),
        (
            "ak.wwise.core.transport.prepare",
            "2022.1",
            "target",
            _RuntimeControlDraftClient.target_id,
            "--target-handle",
            (),
            {"object": _RuntimeControlDraftClient.target_id},
        ),
        (
            "ak.wwise.core.profiler.registerMeter",
            "2024.1",
            "meter_object",
            _RuntimeControlDraftClient.meter_id,
            "--meter-object-handle",
            (),
            {"object": _RuntimeControlDraftClient.meter_id},
        ),
        (
            "ak.wwise.core.profiler.unregisterMeter",
            "2025.1",
            "meter_object",
            _RuntimeControlDraftClient.meter_id,
            "--meter-object-handle",
            (),
            {"object": _RuntimeControlDraftClient.meter_id},
        ),
    ),
)
def test_runtime_object_control_binds_role_then_seals_native_guid_preview(
    tmp_path: Path,
    operation: str,
    version: str,
    role: str,
    object_id: str,
    handle_flag: str,
    extra: tuple[str, ...],
    expected_args: dict[str, object],
) -> None:
    state_dir = tmp_path / "state-bound-runtime"
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    code, started = gateway.execute_gateway(
        [ "--state-dir", str(state_dir), "draft-start", operation],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    assert started["draft"]["next_action_binding"]["object_binding"]["next_role"] == role
    code, bound = gateway.execute_gateway(
        [

            "--state-dir", str(state_dir),
            "draft-bind-object", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(started["draft"]["revision"]),
            "--role", role,
            "--object-id", object_id,
        ],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, bound
    code, declared = gateway.execute_gateway(
        [

            "--state-dir", str(state_dir),
            "draft-declare-runtime-control-plan", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(bound["draft"]["revision"]),
            handle_flag, bound["bound_object"]["handle"],
            *extra,
        ],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, declared
    code, checked = gateway.execute_gateway(
        [

            "--state-dir", str(state_dir),
            "draft-check", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(declared["draft"]["revision"]),
        ],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked
    code, previewed = gateway.execute_gateway(
        [

            "--state-dir", str(state_dir),
            "preview-from-draft", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(checked["draft"]["revision"]),
        ],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, previewed
    artifact = TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact
    assert artifact["request"]["arguments"] == {
        "api": operation,
        "args": expected_args,
        "options": {},
    }
    if operation == "ak.wwise.core.transport.create":
        assert artifact["prepared_operation"]["verification_plan"]["kind"] == (
            "transport-created"
        )
        assert artifact["prepared_operation"]["cleanup"]["companion_request"]["api"] == (
            "ak.wwise.core.transport.destroy"
        )
    if operation == "ak.wwise.core.profiler.registerMeter":
        assert artifact["prepared_operation"]["cleanup"]["companion_request"]["api"] == (
            "ak.wwise.core.profiler.unregisterMeter"
        )


@pytest.mark.parametrize(
    ("operation", "version", "declaration", "message_fragment"),
    (
        (
            "ak.wwise.core.profiler.enableProfilerData",
            "2022.1",
            ("--capture-data", "customer-support-data", "enable"),
            "BUSINESS_ENUM_INVALID",
        ),
        (
            "ak.wwise.core.remote.connect",
            "2022.1",
            ("--remote-host", "127.0.0.1", "--notification-port", "65536"),
            "BUSINESS_VALUE_INVALID",
        ),
        (
            "ak.wwise.core.remote.connect",
            "2021.1",
            (
                "--remote-host", "127.0.0.1",
                "--application-name", "Game",
                "--command-port", "24024",
            ),
            "REMOTE_TARGET_INCOMPLETE",
        ),
        (
            "ak.wwise.core.transport.executeAction",
            "2025.1",
            ("--audition-action", "play", "--transport-scope", "one-transport"),
            "copied exactly",
        ),
        (
            "ak.wwise.core.transport.executeAction",
            "2025.1",
            (
                "--audition-action", "play",
                    "--transport-scope", "one-transport",
                    "--transport-handle", "transport-session-0000004b",
                ),
                "TRANSPORT_HANDLE_INVALID",
            ),
        (
            "ak.wwise.core.transport.executeAction",
            "2025.1",
            (
                "--audition-action", "play",
                "--transport-scope", "all-active",
                "--transport-handle", "transport-session-0000004a",
            ),
            "BUSINESS_VALUE_CONFLICT",
        ),
        (
            "ak.wwise.core.profiler.saveCapture",
            "2025.1",
            (
                "--capture-output-directory", "/tmp",
                "--capture-name", "../escape",
            ),
            "INVALID_HOST_PATH",
        ),
    ),
)
def test_runtime_control_invalid_or_half_filled_intent_returns_repair_before_preview(
    tmp_path: Path,
    operation: str,
    version: str,
    declaration: tuple[str, ...],
    message_fragment: str,
) -> None:
    state_dir = tmp_path / "state-invalid-runtime"
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    code, started = gateway.execute_gateway(
        [ "--state-dir", str(state_dir), "draft-start", operation],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    code, rejected = gateway.execute_gateway(
        [

            "--state-dir", str(state_dir),
            "draft-declare-runtime-control-plan", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(started["draft"]["revision"]),
            *declaration,
        ],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert message_fragment in json.dumps(rejected, sort_keys=True)
    assert not (state_dir / "transactions-v1").exists()


def test_meter_control_rejects_bound_non_meter_object_with_repair(tmp_path: Path) -> None:
    operation = "ak.wwise.core.profiler.registerMeter"
    state_dir = tmp_path / "state-wrong-meter"
    client = _RuntimeControlDraftClient(tmp_path)
    code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    code, bound = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-bind-object", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(started["draft"]["revision"]),
            "--role", "meter_object",
            "--object-id", client.target_id,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, bound
    code, rejected = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-declare-runtime-control-plan", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(bound["draft"]["revision"]),
            "--meter-object-handle", bound["bound_object"]["handle"],
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert "BOUND_OBJECT_ROLE_MISMATCH" in json.dumps(rejected, sort_keys=True)
    assert "AudioDevice" in json.dumps(rejected, sort_keys=True)


class _TransportCreateAssociationClient(_RuntimeControlDraftClient):
    def __init__(self, tmp_path: Path, *, version: str, observed_object: str, observed_game_object: int = 123) -> None:
        super().__init__(tmp_path, version=version)
        self.observed_object = observed_object
        self.observed_game_object = observed_game_object
        self.created = False
        self.calls: list[tuple[str, object, object]] = []

    def call(self, uri: str, args: object = None, options: object = None) -> object:
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.transport.create":
            self.created = True
            return {"transport": 0}
        if uri == "ak.wwise.core.transport.getList":
            return {"list": [{"transport": 0, "object": self.observed_object, "gameObject": self.observed_game_object}]
                if self.created else []}
        if uri == TRANSPORT_GET_STATE_URI:
            return {"state": "stopped"}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_transport_create_wrong_object_cannot_publish_handle(tmp_path: Path, version: str) -> None:
    client = _TransportCreateAssociationClient(tmp_path, version=version,
        observed_object=_RuntimeControlDraftClient.meter_id)
    state_dir = tmp_path / "state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state_dir, "ak.wwise.core.transport.create")
    assert not any(uri == "ak.wwise.core.transport.create" for uri, _, _ in client.calls)
    invoke(["execute", previewed["transaction_id"]])
    before_verify = len(client.calls)
    code, verified = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "verify", previewed["transaction_id"]],
        env=_env(tmp_path, version=version), client_factory=lambda _url: client)
    assert code == 2, verified
    assert verified["state"] == "verification_failed"
    assert verified["verified"] is False
    assert "agent_result" not in verified
    assert any(not assertion["passed"] and "object" in assertion["name"]
        for assertion in verified["verification"]["assertions"])
    assert sum(uri == "ak.wwise.core.transport.getList" for uri, _, _ in client.calls[before_verify:]) == 1
    shown = invoke(["transaction-show", previewed["transaction_id"]])
    assert shown["state"] == "verification_failed"
    code, rejected = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "execute", previewed["transaction_id"]],
        env=_env(tmp_path, version=version), client_factory=lambda _url: client)
    assert code == 2, rejected
    assert sum(uri == "ak.wwise.core.transport.create" for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_transport_create_wrong_explicit_game_object_cannot_publish_handle(tmp_path: Path, version: str) -> None:
    client = _TransportCreateAssociationClient(tmp_path, version=version,
        observed_object=_RuntimeControlDraftClient.target_id)
    state_dir = tmp_path / "state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state_dir,
        "ak.wwise.core.transport.create", ("--game-object-id", "0"))
    invoke(["execute", previewed["transaction_id"]])
    before_verify = len(client.calls)
    code, verified = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "verify", previewed["transaction_id"]],
        env=_env(tmp_path, version=version), client_factory=lambda _url: client)
    assert code == 2, verified
    assert verified["state"] == "verification_failed"
    assert verified["verified"] is False
    assert "agent_result" not in verified
    assert any(not assertion["passed"] and "Game Object" in assertion["name"]
        for assertion in verified["verification"]["assertions"])
    assert sum(uri == "ak.wwise.core.transport.getList" for uri, _, _ in client.calls[before_verify:]) == 1
    assert sum(uri == "ak.wwise.core.transport.create" for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("game_object_id", (None, 0, 18446744073709551615), ids=("native-default", "explicit-zero", "explicit-uint64-max"))
def test_transport_create_matching_association_publishes_usable_zero_id_handle(
    tmp_path: Path, version: str, game_object_id: int | None,
) -> None:
    client = _TransportCreateAssociationClient(tmp_path, version=version,
        observed_object="{ABCDEFAB-ABCD-ABCD-ABCD-ABCDEFABCDEF}".lower(),
        observed_game_object=123 if game_object_id is None else game_object_id)
    client.target_id = "{ABCDEFAB-ABCD-ABCD-ABCD-ABCDEFABCDEF}"
    state_dir = tmp_path / "state"
    declaration = () if game_object_id is None else ("--game-object-id", str(game_object_id))
    previewed, invoke = _public_runtime_preview(tmp_path, client, state_dir,
        "ak.wwise.core.transport.create", declaration)
    assert not any(uri == "ak.wwise.core.transport.create" for uri, _, _ in client.calls)
    executed = invoke(["execute", previewed["transaction_id"]])
    before_verify = len(client.calls)
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["state"] == "verified"
    assert verified["verified"] is True
    assert sum(uri == "ak.wwise.core.transport.getList" for uri, _, _ in client.calls[before_verify:]) == 1
    handle = verified["agent_result"]["business_result"]["transport_handle"]
    assert handle.startswith("trh1-")
    state = invoke(["core-call", TRANSPORT_GET_STATE_URI, "--transport-handle", handle])
    assert state["agent_result"] == {"transport_handle": handle, "state": "stopped"}
    creates = [args for uri, args, _ in client.calls if uri == "ak.wwise.core.transport.create"]
    assert creates == [{"object": client.target_id, **({"gameObject": game_object_id} if game_object_id is not None else {})}]
    code, rejected = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "execute", previewed["transaction_id"]],
        env=_env(tmp_path, version=version), client_factory=lambda _url: client)
    assert code == 2, rejected
    assert sum(uri == "ak.wwise.core.transport.create" for uri, _, _ in client.calls) == 1
