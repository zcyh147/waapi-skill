from __future__ import annotations

import importlib.util
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest


LOG_GET_URI = "ak.wwise.core.log.get"
GET_CURSOR_TIME_URI = "ak.wwise.core.profiler.getCursorTime"
GET_VOICES_URI = "ak.wwise.core.profiler.getVoices"
TRANSPORT_GET_STATE_URI = "ak.wwise.core.transport.getState"
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
    runtime_inspection_business_operations,
    runtime_inspection_business_versions,
)


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


def _env(tmp_path: Path, *, version: str = "2025.1") -> dict[str, str]:
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


def test_runtime_business_direct_read_inventory_is_exactly_49_rows() -> None:
    assert runtime_inspection_business_operations() == frozenset(
        EXPECTED_DIRECT_READ_ROWS
    )
    assert {
        operation: runtime_inspection_business_versions(operation)
        for operation in EXPECTED_DIRECT_READ_ROWS
    } == EXPECTED_DIRECT_READ_ROWS
    assert sum(len(versions) for versions in EXPECTED_DIRECT_READ_ROWS.values()) == 49


def test_log_get_schema_exposes_business_channel_and_bounded_result_only(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", "2025.1", "request-schema", LOG_GET_URI],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert code == 0, payload
    assert payload["business_adapter"] == {
        "contract": "waapi-skill.runtime-inspection-business/v1",
        "operation": LOG_GET_URI,
        "version": "2025.1",
        "input_mode": "business_declaration",
        "execution_shape": "bounded_read",
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
            "--version",
            "2025.1",
            "core-call",
            LOG_GET_URI,
            "--log-channel",
            "soundbank-generation",
            "--max-results",
            "2",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert (LOG_GET_URI, {"channel": "soundbankGenerate"}, {}) in client.calls
    assert payload["agent_result"] == {
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
            "--version",
            "2025.1",
            "core-call",
            LOG_GET_URI,
            "--log-channel",
            "general",
            "--max-results",
            limit,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"invalid input connected to {url}"),
    )

    assert code == 2
    assert "1 to 1000" in payload["message"]


def test_log_get_rejects_native_channel_token_before_connection(tmp_path: Path) -> None:
    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "core-call",
            LOG_GET_URI,
            "--log-channel",
            "soundbankGenerate",
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"native token connected to {url}"),
    )

    assert code == 2
    assert "soundbank-generation" in payload["message"]


def test_log_get_rejects_later_log_view_on_older_wwise_before_connection(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "core-call",
            LOG_GET_URI,
            "--log-channel",
            "source-control",
        ],
        env=_env(tmp_path, version="2022.1"),
        client_factory=lambda url: pytest.fail(f"version mismatch connected to {url}"),
    )

    assert code == 2
    assert "available Wwise log view" in payload["message"]


def test_log_get_blocks_retired_typed_call_before_connection(tmp_path: Path) -> None:
    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "typed-call",
            LOG_GET_URI,
            "--schema-digest",
            "0" * 64,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"typed bypass connected to {url}"),
    )

    assert code == 2
    assert "closed Core business" in payload["message"]


def test_log_get_blocks_retired_draft_before_state_or_connection(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            LOG_GET_URI,
        ],
        env=_env(tmp_path),
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


def test_profiler_voice_read_derives_native_time_projection_and_handle(
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
            GET_VOICES_URI: [
                {
                    "return": [
                        {
                            "pipelineID": 41,
                            "objectName": "Old",
                            "gameObjectName": "Player",
                            "baseVolume": -6.0,
                            "isStarted": True,
                            "isVirtual": False,
                        },
                        {
                            "pipelineID": 42,
                            "objectName": "Rifle",
                            "gameObjectName": "Player",
                            "baseVolume": -4.0,
                            "isStarted": True,
                            "isVirtual": False,
                        },
                    ]
                }
            ],
        }
    )

    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "core-call",
            GET_VOICES_URI,
            "--profiler-position",
            "capture-latest",
            "--result-view",
            "summary",
            "--voice-instance-handle",
            "voice-instance-0000002a",
            "--max-results",
            "1",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert (
        GET_VOICES_URI,
        {"time": "capture", "voicePipelineID": 42},
        {
            "return": [
                "pipelineID",
                "objectName",
                "gameObjectName",
                "baseVolume",
                "isStarted",
                "isVirtual",
            ]
        },
    ) in client.calls
    assert payload["agent_result"] == {
        "profiler_position": "capture-latest",
        "return": [
            {
                "pipelineID": 42,
                "objectName": "Rifle",
                "gameObjectName": "Player",
                "baseVolume": -4.0,
                "isStarted": True,
                "isVirtual": False,
                "voice_instance_handle": "voice-instance-0000002a",
            }
        ],
        "returned_count": 1,
        "truncated": True,
    }


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
            "--version",
            "2025.1",
            "core-call",
            GET_CURSOR_TIME_URI,
            "--profiler-cursor",
            "user-cursor",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert (GET_CURSOR_TIME_URI, {"cursor": "user"}, {}) in client.calls
    assert payload["agent_result"] == {
        "profiler_cursor": "user-cursor",
        "position_ms": 1234,
    }


def test_profiler_voice_read_rejects_invented_handle_before_connection(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "core-call",
            GET_VOICES_URI,
            "--profiler-position",
            "capture-latest",
            "--voice-instance-handle",
            "42",
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"invalid handle connected to {url}"),
    )

    assert code == 2
    assert "copied exactly" in payload["message"]


def test_transport_state_read_maps_gateway_handle_without_exposing_native_id(
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
            TRANSPORT_GET_STATE_URI: [{"state": "paused"}],
        }
    )

    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "core-call",
            TRANSPORT_GET_STATE_URI,
            "--transport-handle",
            "transport-session-0000004a",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert (TRANSPORT_GET_STATE_URI, {"transport": 74}, {}) in client.calls
    assert payload["agent_result"] == {
        "transport_handle": "transport-session-0000004a",
        "state": "paused",
    }
    assert payload["business_request"] == {
        "operation": TRANSPORT_GET_STATE_URI,
        "transport_handle": "transport-session-0000004a",
        "max_results": 1,
    }


def test_transport_state_rejects_invented_native_id_before_connection(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "core-call",
            TRANSPORT_GET_STATE_URI,
            "--transport-handle",
            "74",
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"native transport connected to {url}"),
    )

    assert code == 2
    assert "copied exactly" in payload["message"]
