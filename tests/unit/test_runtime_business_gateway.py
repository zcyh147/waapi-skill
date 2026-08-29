from __future__ import annotations

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
    "ak.wwise.core.remote.connect": ("2021.1", "2022.1", "2023.1"),
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


def test_runtime_business_control_inventory_is_exactly_45_rows() -> None:
    assert runtime_control_business_operations() == frozenset(EXPECTED_CONTROL_ROWS)
    assert {
        operation: runtime_inspection_business_versions(operation)
        for operation in EXPECTED_CONTROL_ROWS
    } == EXPECTED_CONTROL_ROWS
    assert sum(len(versions) for versions in EXPECTED_CONTROL_ROWS.values()) == 45


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
            "--version",
            version,
            "typed-call",
            operation,
            "--schema-digest",
            "0" * 64,
        ],
        env=_env(tmp_path, version=version),
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
    assert payload["business_adapter"] == {
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
    assert "pipelineID" not in json.dumps(payload["agent_result"], sort_keys=True)


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
        "available": True,
        "position_ms": 1234,
    }


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
            "ak.wwise.core.transport.getList": [
                {
                    "list": [
                        {
                            "transport": 74,
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
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "core-call",
            TRANSPORT_GET_STATE_URI,
            "--transport-handle",
            transport_handle,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert (TRANSPORT_GET_STATE_URI, {"transport": 74}, {}) in client.calls
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
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "core-call",
            TRANSPORT_GET_STATE_URI,
            "--transport-handle",
            transport_handle,
        ],
        env=_env(tmp_path),
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
            "--version",
            "2025.1",
            "core-call",
            TRANSPORT_GET_STATE_URI,
            "--transport-handle",
            "trh1-" + "61" * 16,
        ],
        env=_env(tmp_path),
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
            "--version", "2025.1", "--state-dir", str(state_dir),
            "core-call", TRANSPORT_GET_STATE_URI,
            "--transport-handle", transport_handle,
        ],
        env=_env(tmp_path),
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
            "--version",
            "2025.1",
            "--state-dir",
            str(tmp_path / "state"),
            "draft-start",
            PROFILER_MOVE_CURSOR_URI,
        ],
        env=_env(tmp_path),
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
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=_env(tmp_path, version="2022.1"),
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
            "--version",
            "2022.1",
            "--state-dir",
            str(state_dir),
            "draft-declare-runtime-control-plan",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(started["draft"]["revision"]),
        ],
        env=_env(tmp_path, version="2022.1"),
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
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    code, declared = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
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
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, declared

    code, checked = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked

    code, previewed = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked["draft"]["revision"]),
        ],
        env=_env(tmp_path),
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
        "result-schema"
    )


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
            "--version", version,
            "--state-dir", str(state_dir),
            "draft-start", operation,
        ],
        env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    code, declared = gateway.execute_gateway(
        [
            "--version", version,
            "--state-dir", str(state_dir),
            "draft-declare-runtime-control-plan", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(started["draft"]["revision"]),
            *declaration_values,
        ],
        env=_env(tmp_path, version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, declared
    code, checked = gateway.execute_gateway(
        [
            "--version", version,
            "--state-dir", str(state_dir),
            "draft-check", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(declared["draft"]["revision"]),
        ],
        env=_env(tmp_path, version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked
    code, previewed = gateway.execute_gateway(
        [
            "--version", version,
            "--state-dir", str(state_dir),
            "preview-from-draft", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(checked["draft"]["revision"]),
        ],
        env=_env(tmp_path, version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, previewed
    return TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact


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
        ["--version", version, "--state-dir", str(state_dir), "draft-start", operation],
        env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    assert started["draft"]["next_action_binding"]["object_binding"]["next_role"] == role
    code, bound = gateway.execute_gateway(
        [
            "--version", version,
            "--state-dir", str(state_dir),
            "draft-bind-object", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(started["draft"]["revision"]),
            "--role", role,
            "--object-id", object_id,
        ],
        env=_env(tmp_path, version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, bound
    code, declared = gateway.execute_gateway(
        [
            "--version", version,
            "--state-dir", str(state_dir),
            "draft-declare-runtime-control-plan", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(bound["draft"]["revision"]),
            handle_flag, bound["bound_object"]["handle"],
            *extra,
        ],
        env=_env(tmp_path, version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, declared
    code, checked = gateway.execute_gateway(
        [
            "--version", version,
            "--state-dir", str(state_dir),
            "draft-check", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(declared["draft"]["revision"]),
        ],
        env=_env(tmp_path, version=version),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked
    code, previewed = gateway.execute_gateway(
        [
            "--version", version,
            "--state-dir", str(state_dir),
            "preview-from-draft", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(checked["draft"]["revision"]),
        ],
        env=_env(tmp_path, version=version),
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
            ("--remote-host", "127.0.0.1", "--notification-port", "24025"),
            "not disclosed",
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
        ["--version", version, "--state-dir", str(state_dir), "draft-start", operation],
        env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    code, rejected = gateway.execute_gateway(
        [
            "--version", version,
            "--state-dir", str(state_dir),
            "draft-declare-runtime-control-plan", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(started["draft"]["revision"]),
            *declaration,
        ],
        env=_env(tmp_path, version=version),
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
