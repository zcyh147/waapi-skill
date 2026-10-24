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
GET_BUSSES_URI = "ak.wwise.core.profiler.getBusses"
GET_AUDIO_OBJECTS_URI = "ak.wwise.core.profiler.getAudioObjects"
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
def test_runtime_contracts_disclose_operation_host_requirement(
    tmp_path: Path,
    operation: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", "2022.1", "request-schema", operation],
        env=_env(tmp_path, version="2022.1"),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert code == 0, payload
    assert payload["business_adapter"]["host_requirement"] == (
        "wwise-authoring" if operation.startswith("ak.wwise.core.remote.") else "wwise-console-or-authoring")


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
                        {"message": "old", "severity": "Message", "time": 1, "messageId": "Custom"},
                        {"message": "warning", "severity": "Warning", "time": 2, "messageId": "Custom"},
                        {"message": "latest", "severity": "Error", "time": 3, "messageId": "Custom"},
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
            {"message": "warning", "severity": "Warning", "time": 2, "messageId": "Custom"},
            {"message": "latest", "severity": "Error", "time": 3, "messageId": "Custom"},
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


def _pinned_profiler_return_fields(version: str, operation: str, host: str = "wwise-authoring") -> list[str]:
    catalog = json.loads((Path(__file__).resolve().parents[2] / "skills/waapi-skill/resources/native-catalog"
                          / version / (host + ".json")).read_bytes())
    definition = {GET_VOICES_URI: "voiceReturnOptions", GET_BUSSES_URI: "busReturnOptions",
                  GET_AUDIO_OBJECTS_URI: "audioObjectReturnOptions"}[operation]
    schema = catalog["definitions"]["documents"]["waapi_definitions.json"]["definitions"][definition]
    assert schema["type"] == "array" and schema["items"]["type"] == "string"
    assert not schema.get("uniqueItems")
    assert isinstance(schema["items"]["enum"], list)
    return schema["items"]["enum"]


def test_profiler_voice_can_select_only_name_and_level_through_public_gateway(tmp_path: Path) -> None:
    client = _RuntimeControlDraftClient(tmp_path)
    original = client.call
    calls = []
    def call(uri, args=None, options=None):
        calls.append((uri, args, options))
        if uri == GET_VOICES_URI:
            return {"return": [{"objectName": "Rifle", "baseVolume": -3.5}]}
        return original(uri, args, options)
    client.call = call
    code, payload = gateway.execute_gateway([
        "--state-dir", str(tmp_path / "state"), "core-call", GET_VOICES_URI,
        "--profiler-position", "123", "--result-field", "objectName", "--result-field", "baseVolume",
    ], env=_env(tmp_path), client_factory=lambda _url: client)
    assert code == 0, payload
    assert next(options for uri, _args, options in calls if uri == GET_VOICES_URI) == {
        "return": ["objectName", "baseVolume"],
    }
    assert payload["agent_result"]["return"] == [{"objectName": "Rifle", "baseVolume": -3.5}]
    assert list(payload)[-1] == "agent_result"


def _profiler_field_read(tmp_path, operation, rows, *, version="2025.1", console=False):
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    calls = []
    def call(uri, args=None, options=None):
        calls.append((uri, args, options))
        if uri == operation:
            return {"return": [dict(row) for row in rows]}
        result = original(uri, args, options)
        if uri == "ak.wwise.core.getInfo":
            result["isCommandLine"] = console
        return result
    client.call = call
    env = _env(tmp_path, version=version)
    state = tmp_path / "state"
    def read(*argv):
        return gateway.execute_gateway([
            "--state-dir", str(state), "core-call", operation, "--profiler-position", "123", *argv,
        ], env=env, client_factory=lambda _url: client)
    return read, calls, state, env


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("console", (False, True))
@pytest.mark.parametrize("operation,fields,row", (
    (GET_VOICES_URI, ["objectName", "baseVolume"], {"objectName": "Rifle", "baseVolume": -3.5}),
    (GET_BUSSES_URI, ["objectName", "volume"], {"objectName": "Weapons", "volume": -2.0}),
    (GET_AUDIO_OBJECTS_URI, ["audioObjectName", "rmsMeter"], {"audioObjectName": "Rifle", "rmsMeter": [-4.0]}),
))
def test_profiler_explicit_fields_match_each_pinned_host_version_profile(
    tmp_path, version, console, operation, fields, row,
):
    read, calls, _state, env = _profiler_field_read(tmp_path, operation, [row], version=version, console=console)
    code, schema = gateway.execute_gateway(["request-schema", operation], env=env,
        client_factory=lambda _url: pytest.fail("Projection choices must be disclosed offline"))
    assert code == 0, schema
    declaration = schema["business_adapter"]["declaration"]
    choices = declaration["value_choices"]["result_fields"]
    pinned = _pinned_profiler_return_fields(version, operation, "wwise-console" if console else "wwise-authoring")
    assert set(choices) == set(pinned) and len(choices) == len(pinned)
    assert declaration["input_forms"]["result_fields"] == {
        "flag": "--result-field", "repeatable": True, "minimum_items": 1, "maximum_items": 64,
        "bound_owner": "Gateway request resource policy", "order_preserved": True,
        "repetitions_preserved": True, "mutually_exclusive_with": ["result_view"],
    }
    assert "no identity fields are appended" in declaration["result_fields_meaning"]["projection"]
    flags = [argument for field in fields for argument in ("--result-field", field)]
    code, payload = read(*flags)
    assert code == 0, payload
    assert [(args, options) for uri, args, options in calls if uri == operation] == [
        ({"time": 123}, {"return": fields}),
    ]
    assert payload["agent_result"]["return"] == [row]
    assert payload["agent_result"]["complete"] is True
    assert payload["agent_result"]["instantaneous_native_resource_authority"] is False
    assert list(payload)[-1] == "agent_result"


@pytest.mark.parametrize("operation,name_field,value_field", (
    (GET_VOICES_URI, "objectName", "baseVolume"),
    (GET_BUSSES_URI, "objectName", "volume"),
    (GET_AUDIO_OBJECTS_URI, "audioObjectName", "rmsMeter"),
))
@pytest.mark.parametrize("repeat", (False, True))
def test_profiler_explicit_field_order_and_repetition_survive_dispatch(tmp_path, operation, name_field, value_field, repeat):
    value = [-3.5] if operation == GET_AUDIO_OBJECTS_URI else -3.5
    row = {name_field: "Voice", value_field: value}
    read, calls, _state, _env_value = _profiler_field_read(tmp_path, operation, [row])
    fields = [value_field, name_field, value_field] if repeat else [value_field, name_field]
    code, payload = read(*[argument for field in fields for argument in ("--result-field", field)])
    assert code == 0, payload
    assert next(options for uri, _args, options in calls if uri == operation) == {"return": fields}
    assert payload["agent_result"]["return"] == [{value_field: value, name_field: "Voice"}]


@pytest.mark.parametrize("operation,pipeline,guid", (
    (GET_VOICES_URI, "pipelineID", "objectGUID"),
    (GET_BUSSES_URI, "pipelineID", "objectGUID"),
    (GET_AUDIO_OBJECTS_URI, "busPipelineID", "busGUID"),
))
@pytest.mark.parametrize("basis", ("pipeline-only", "pipeline-guid", "pipeline-game-object", "complete"))
def test_profiler_explicit_pipeline_fields_remain_visible_without_invented_instance_authority(
    tmp_path, operation, pipeline, guid, basis,
):
    row = {pipeline: 42}
    if basis in {"pipeline-guid", "complete"}:
        row[guid] = _RuntimeControlDraftClient.target_id
    if basis in {"pipeline-game-object", "complete"}:
        row["gameObjectID"] = 1
    fields = [pipeline, guid, "gameObjectID"]
    read, calls, _state, _env_value = _profiler_field_read(tmp_path, operation, [row])
    code, payload = read(*[argument for field in fields for argument in ("--result-field", field)])
    assert code == 0, payload
    projected = dict(payload["agent_result"]["return"][0])
    handle = projected.pop("voice_instance_handle" if operation == GET_VOICES_URI else "bus_instance_handle", None)
    assert projected == row
    assert (handle is not None) is (basis == "complete")
    assert next(options for uri, _args, options in calls if uri == operation) == {"return": fields}


def test_profiler_explicit_projection_omits_unselected_and_unreported_native_fields(tmp_path):
    read, _calls, _state, _env_value = _profiler_field_read(tmp_path, GET_VOICES_URI, [
        {"objectName": "Only label", "isStarted": True},
        {"objectName": "Label and level", "baseVolume": -3.5, "isVirtual": False},
    ])
    code, payload = read("--result-field", "objectName", "--result-field", "baseVolume")
    assert code == 0, payload
    assert payload["agent_result"]["return"] == [
        {"objectName": "Only label"}, {"objectName": "Label and level", "baseVolume": -3.5},
    ]


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("operation,name_field,value_field", (
    (GET_VOICES_URI, "objectName", "baseVolume"),
    (GET_BUSSES_URI, "objectName", "volume"),
    (GET_AUDIO_OBJECTS_URI, "audioObjectName", "rmsMeter"),
))
@pytest.mark.parametrize("select_value", (False, True))
def test_profiler_explicit_fields_validate_off_page_selected_and_unselected_values(
    tmp_path, version, operation, name_field, value_field, select_value,
):
    read, _calls, state, _env_value = _profiler_field_read(tmp_path, operation, [
        {name_field: "Off-page malformed value", value_field: None},
        {name_field: "Visible valid row", value_field: [-3.5] if operation == GET_AUDIO_OBJECTS_URI else -3.5},
    ], version=version)
    fields = [name_field, value_field] if select_value else [name_field]
    code, payload = read("--max-results", "1", *[argument for field in fields for argument in ("--result-field", field)])
    assert code == 2, payload
    assert payload["error_code"] == "SemanticValidationError"
    assert "agent_result" not in payload
    assert not list((state / "runtime-inspection-observations-v1").glob("**/*.json"))


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_profiler_explicit_fields_reject_wrong_version_choice_before_connection(tmp_path, version):
    wrong = "effectCount" if version in {"2021.1", "2022.1"} else "mixerID"
    allowed = "mixerID" if version in {"2021.1", "2022.1"} else "effectCount"
    code, payload = gateway.execute_gateway([
        "core-call", GET_BUSSES_URI, "--profiler-position", "123", "--result-field", wrong,
    ], env=_env(tmp_path, version=version), client_factory=lambda _url: pytest.fail("Wrong-version field must not connect"))
    assert code == 2, payload
    assert wrong in payload["message"] and allowed in payload["message"] and version in payload["message"]
    assert "permitted choices" in payload["message"]


@pytest.mark.parametrize("operation", (GET_VOICES_URI, GET_BUSSES_URI, GET_AUDIO_OBJECTS_URI))
def test_profiler_explicit_fields_reject_unknown_choices_and_bound_before_connection(tmp_path, operation):
    for fields, expected in ((["invented-field"], "permitted choices"), (["objectName"] * 65, "64")):
        code, payload = gateway.execute_gateway([
            "core-call", operation, "--profiler-position", "123",
            *[argument for field in fields for argument in ("--result-field", field)],
        ], env=_env(tmp_path), client_factory=lambda _url: pytest.fail("Invalid field selection must not connect"))
        assert code == 2, payload
        assert "result_fields" in payload["message"] and expected in payload["message"]


def test_profiler_explicit_fields_accept_the_disclosed_request_ceiling(tmp_path):
    read, calls, _state, _env_value = _profiler_field_read(tmp_path, GET_VOICES_URI, [{"objectName": "Voice"}])
    code, payload = read(*[argument for _ in range(64) for argument in ("--result-field", "objectName")])
    assert code == 0, payload
    assert next(options for uri, _args, options in calls if uri == GET_VOICES_URI) == {"return": ["objectName"] * 64}
    assert payload["agent_result"]["return"] == [{"objectName": "Voice"}]


@pytest.mark.parametrize("view", ("summary", "identity", "diagnostics", "capture-defaults", "empty-selection"))
def test_profiler_explicit_fields_conflict_with_every_explicit_preset(tmp_path, view):
    with pytest.raises(SystemExit) as exc:
        gateway.execute_gateway([
            "core-call", GET_VOICES_URI, "--profiler-position", "123", "--result-view", view,
            "--result-field", "objectName",
        ], env=_env(tmp_path), client_factory=lambda _url: pytest.fail("Conflicting selection must not connect"))
    assert exc.value.code == 2


@pytest.mark.parametrize("operation", (LOG_GET_URI, GET_CURSOR_TIME_URI, TRANSPORT_GET_STATE_URI,
    "ak.wwise.core.profiler.getRTPCs", "ak.wwise.core.profiler.getMeters", "ak.wwise.core.object.isLinked"))
def test_profiler_explicit_field_flag_is_not_a_projection_escape_for_other_readers(tmp_path, operation):
    code, payload = gateway.execute_gateway([
        "core-call", operation, "--result-field", "objectName",
    ], env=_env(tmp_path), client_factory=lambda _url: pytest.fail("Unrelated reader projection must not connect"))
    assert code == 2, payload
    assert "result_fields applies only" in payload["message"]


def test_profiler_explicit_field_pages_preserve_projection_without_reread_or_new_selection(tmp_path):
    read, calls, _state, env = _profiler_field_read(tmp_path, GET_VOICES_URI, [
        {"objectName": f"Voice{index}", "baseVolume": -3.5, "isStarted": True} for index in range(5)
    ])
    code, payload = read("--max-results", "2", "--result-field", "objectName", "--result-field", "baseVolume")
    assert code == 0, payload
    assert len([uri for uri, _args, _options in calls if uri == GET_VOICES_URI]) == 1
    pages = [payload["agent_result"]]
    continuation = pages[0]["next_command"]["full_argv"][3:]
    code, invalid = gateway.execute_gateway([*continuation, "--result-field", "isStarted"], env=env,
        client_factory=lambda _url: pytest.fail("Cached page cannot accept a new projection"))
    assert code == 2 and "exact runtime observation" in invalid["message"], invalid
    while pages[-1].get("next_command"):
        code, payload = gateway.execute_gateway(pages[-1]["next_command"]["full_argv"][3:], env=env,
            client_factory=lambda _url: pytest.fail("Explicit projection pages must remain offline"))
        assert code == 0, payload
        pages.append(payload["agent_result"])
    assert [row for page in pages for row in page["return"]] == [
        {"objectName": f"Voice{index}", "baseVolume": -3.5} for index in (3, 4, 1, 2, 0)
    ]
    assert pages[-1]["complete"] is True


@pytest.mark.parametrize("change", ("configuration", "version", "expiry"))
def test_profiler_explicit_field_pages_retain_configuration_version_and_lifetime_guards(tmp_path, monkeypatch, change):
    read, _calls, _state, env = _profiler_field_read(tmp_path, GET_VOICES_URI, [
        {"objectName": "First"}, {"objectName": "Second"},
    ])
    code, payload = read("--max-results", "1", "--result-field", "objectName")
    assert code == 0, payload
    continuation = payload["agent_result"]["next_command"]["full_argv"][3:]
    if change == "configuration":
        set_gateway_config(env, waapi_port=31338)
    elif change == "version":
        set_gateway_config(env, wwise_version="2024.1")
    else:
        import time
        expired = time.time() + 901
        monkeypatch.setattr(time, "time", lambda: expired)
    code, invalid = gateway.execute_gateway(continuation, env=env,
        client_factory=lambda _url: pytest.fail("Changed or expired cached reads must not connect"))
    assert code == 2, invalid
    assert ("expired" if change == "expiry" else "configuration or operation changed") in invalid["message"]
    assert "agent_result" not in invalid


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("operation", (GET_VOICES_URI, GET_BUSSES_URI, GET_AUDIO_OBJECTS_URI))
@pytest.mark.parametrize("view", (None, "summary", "identity"))
def test_profiler_existing_summary_identity_and_omitted_selection_keep_native_presets(tmp_path, version, operation, view):
    summaries = {
        GET_VOICES_URI: ["pipelineID", "objectName", "gameObjectName", "baseVolume", "isStarted", "isVirtual", "objectGUID", "gameObjectID"],
        GET_BUSSES_URI: ["pipelineID", "objectName", "gameObjectName", "volume", "downstreamGain", "voiceCount", "depth", "objectGUID", "gameObjectID"],
        GET_AUDIO_OBJECTS_URI: ["audioObjectID", "audioObjectName", "busPipelineID", "busName", "gameObjectName", "rmsMeter", "peakMeter", "busGUID", "gameObjectID"],
    }
    identities = {
        GET_VOICES_URI: ["pipelineID", "playingID", "objectGUID", "objectName", "playTargetGUID", "playTargetName", "gameObjectID", "gameObjectName"],
        GET_BUSSES_URI: ["pipelineID", "objectGUID", "objectName", "gameObjectID", "gameObjectName"],
        GET_AUDIO_OBJECTS_URI: ["audioObjectID", "audioObjectName", "busPipelineID", "busGUID", "busName", "gameObjectID", "gameObjectName", "instigatorPipelineID"],
    }
    read, calls, _state, _env_value = _profiler_field_read(tmp_path, operation, [], version=version)
    code, payload = read(*(["--result-view", view] if view is not None else []))
    assert code == 0, payload
    assert next(options for uri, _args, options in calls if uri == operation) == {
        "return": identities[operation] if view == "identity" else summaries[operation],
    }


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
        "result_fields",
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
        GET_VOICES_URI: {"result_view": ["summary", "identity", "diagnostics", "capture-defaults", "empty-selection"],
                         "result_fields": _pinned_profiler_return_fields(version, GET_VOICES_URI)},
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
        return {"items": [{"message": message, "severity": "Message", "time": 1, "messageId": "Custom"}]} if uri == LOG_GET_URI else original(uri, args, options)
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
    assert json.loads("".join(fragments)) == {"message": message, "severity": "Message", "time": 1, "messageId": "Custom"}


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


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1"])
def test_console_transport_state_rejects_unknown_handle_before_native_state(tmp_path, version):
    client = _RuntimeControlDraftClient(tmp_path, version=version)
    original = client.call
    calls = []
    def call(uri, args=None, options=None):
        calls.append(uri)
        result = original(uri, args, options)
        if uri == "ak.wwise.core.getInfo":
            result.update(isCommandLine=True, displayName="WwiseConsole")
        return result
    client.call = call
    code, payload = gateway.execute_gateway(["--state-dir", str(tmp_path / "state"),
        "core-call", TRANSPORT_GET_STATE_URI, "--transport-handle", "trh1-" + "61" * 16],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2 and payload["error_code"] == "TRANSPORT_HANDLE_UNKNOWN", payload
    assert TRANSPORT_GET_STATE_URI not in calls


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
        if uri == LOG_GET_URI:
            return {"items": []}
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
        if uri == TRANSPORT_GET_STATE_URI:
            return {"state": "stopped"}
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
    ("ak.wwise.core.remote.connect",),
)
def test_remote_control_returns_authoring_boundary_before_project_read(
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


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("operation", ("ak.wwise.core.log.addItem", "ak.wwise.core.log.clear"))
def test_log_controls_disclose_bounded_observation_and_concurrency_limits(tmp_path: Path, version: str, operation: str) -> None:
    code, schema = gateway.execute_gateway(["request-schema", operation], env=_env(tmp_path, version=version),
        client_factory=lambda _: pytest.fail("Schema is offline"))
    assert code == 0, schema
    verification = schema["business_adapter"]["declaration"]["verification"]
    assert verification["observer"] == LOG_GET_URI
    assert verification["maximum_channel_items"] == 1000
    assert verification["maximum_channel_bytes"] == 65536
    assert verification["row_identity"] == "none; messageId and time are not treated as unique or ordered"
    assert verification["console_add_observer"]["topic"] == "ak.wwise.core.log.itemAdded"
    assert verification["native_log_observation_policy"]["console_minimum_version"] == "2025.1.4"


class _LogControlClient(_RuntimeControlDraftClient):
    def __init__(self, tmp_path: Path, *, version: str = "2025.1") -> None:
        super().__init__(tmp_path, version=version)
        self.calls = []
        self.rows = [{"message": "retained", "severity": "Message", "time": 1720000000, "messageId": "Custom"}]
        self.after = None
        self.control_result = {}
        self.console = False

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri == LOG_GET_URI:
            return {"items": list(self.rows)}
        if uri == "ak.wwise.core.log.addItem":
            self.rows = self.after if self.after is not None else [*self.rows,
                {"message": args["message"], "severity": args["severity"], "time": 1720000000, "messageId": "Custom"}]
            return self.control_result
        if uri == "ak.wwise.core.log.clear":
            self.rows = self.after if self.after is not None else []
            return self.control_result
        result = super().call(uri, args, options)
        if uri == "ak.wwise.core.getInfo":
            result["isCommandLine"] = self.console
        return result


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_log_add_verifies_new_identical_item_through_public_transaction(tmp_path: Path, version: str) -> None:
    client = _LogControlClient(tmp_path, version=version)
    previewed, invoke = _public_runtime_preview(tmp_path, client, tmp_path / "log-state",
        "ak.wwise.core.log.addItem", ("--message", "retained"))
    executed = invoke(["execute", previewed["transaction_id"]])
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is True, verified
    observation = verified["verification"]["verification_scope"]["log_observation"]
    assert observation["outcome"] == "new_matching_item"
    assert observation["matching_items_before"] == 1
    assert observation["matching_items_after"] == 2
    assert observation["exclusive_causation_verified"] is False
    assert all(args == {"channel": "general"} and options == {} for uri, args, options in client.calls if uri == LOG_GET_URI)
    assert sum(uri == "ak.wwise.core.log.addItem" for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("remaining", ("empty", "competing", "identical"))
def test_log_clear_observes_prior_channel_contents_without_promising_empty_forever(
    tmp_path: Path, version: str, remaining: str,
) -> None:
    client = _LogControlClient(tmp_path, version=version)
    old = dict(client.rows[0])
    client.after = ([] if remaining == "empty" else [old] if remaining == "identical" else
        [{"message": "concurrent", "severity": "Warning", "messageId": "Custom", "time": 1}])
    previewed, invoke = _public_runtime_preview(tmp_path, client, tmp_path / "log-state",
        "ak.wwise.core.log.clear", ("--log-channel", "source-control"))
    executed = invoke(["execute", previewed["transaction_id"]])
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is (remaining != "identical"), verified
    observation = verified["verification"]["verification_scope"]["log_observation"]
    assert observation["outcome"] == ("indistinguishable_prior_contents" if remaining == "identical" else "prior_contents_absent")
    assert observation["post_channel_empty"] is (remaining == "empty")
    assert observation["continuing_channel_state_verified"] is False
    assert all(args == {"channel": "sourceControl"} for uri, args, _ in client.calls if uri == LOG_GET_URI)
    assert sum(uri == "ak.wwise.core.log.clear" for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("after", ("unchanged", "wrong-severity", "missing", "competitor"))
def test_log_add_preexisting_or_competing_content_does_not_prove_a_new_matching_item(tmp_path: Path, after: str) -> None:
    client = _LogControlClient(tmp_path)
    client.after = {"unchanged": list(client.rows), "wrong-severity": [*client.rows,
        {"message": "retained", "severity": "Warning", "time": 2, "messageId": "Custom"}],
        "missing": [], "competitor": [{"message": "another", "severity": "Message", "time": 3, "messageId": "Custom"}]}[after]
    previewed, invoke = _public_runtime_preview(tmp_path, client, tmp_path / "log-state",
        "ak.wwise.core.log.addItem", ("--message", "retained"))
    executed = invoke(["execute", previewed["transaction_id"]])
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is False, verified
    assert verified["state"] == "result_schema_checked"
    assert verified["verification"]["verification_scope"]["log_observation"]["outcome"] == "no_matching_increase"
    code, replay = gateway.execute_gateway(["--state-dir", str(tmp_path / "log-state"), "execute", previewed["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2, replay
    assert sum(uri == "ak.wwise.core.log.addItem" for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("operation,declaration", [
    ("ak.wwise.core.log.clear", ("--log-channel", "general")),
])
@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_log_console_empty_observation_never_proves_the_effect(tmp_path: Path, operation: str, declaration: tuple, version: str) -> None:
    client = _LogControlClient(tmp_path, version=version)
    client.console = True
    client.rows = client.after = []
    previewed, invoke = _public_runtime_preview(tmp_path, client, tmp_path / "log-state", operation, declaration)
    executed = invoke(["execute", previewed["transaction_id"]])
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is False, verified
    assert verified["state"] == "result_schema_checked"
    assert verified["verification"]["verification_scope"]["log_observation"]["outcome"] == "console_log_unobservable"


@pytest.mark.parametrize("operation", ("ak.wwise.core.log.addItem", "ak.wwise.core.log.clear"))
@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
@pytest.mark.parametrize("command", ("request-schema", "draft-start"))
def test_log_controls_preserve_older_packaged_route_boundary(tmp_path: Path, operation: str, version: str, command: str) -> None:
    code, result = gateway.execute_gateway([command, operation], env=_env(tmp_path, version=version),
        client_factory=lambda _: pytest.fail("Older packaged route must fail before connection"))
    assert code == 2, result
    assert result["error_code"] == "TypedRequestError"


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("severity,native", (("message", "Message"), ("warning", "Warning"), ("error", "Error"), ("fatal", "Fatal Error")))
def test_log_add_native_severity_and_optional_result_fields_are_verified(tmp_path: Path, version: str, severity: str, native: str) -> None:
    client = _LogControlClient(tmp_path, version=version)
    message = '日志 "Weather"\n$HOME; second line'
    client.after = [*client.rows, {"message": message, "severity": native, "time": 1, "messageId": "Custom",
        "parameters": ["Weather"], "platform": {"id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}", "name": "Windows"}}]
    previewed, invoke = _public_runtime_preview(tmp_path, client, tmp_path / "log-state", "ak.wwise.core.log.addItem",
        ("--message", message, "--log-channel", "soundbank-generation", "--severity", severity))
    executed = invoke(["execute", previewed["transaction_id"]])
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is True, verified
    assert ("ak.wwise.core.log.addItem", {"message": message, "channel": "soundbankGenerate", "severity": native}, {}) in client.calls
    assert all(args == {"channel": "soundbankGenerate"} for uri, args, _ in client.calls if uri == LOG_GET_URI)
    observed = verified["verification"]["verification_scope"]["log_observation"]
    assert observed["post_channel"]["items"][-1]["parameters"] == ["Weather"]
    assert list(verified)[-1] == "agent_result"


@pytest.mark.parametrize("change", ("new-message", "reordered"))
def test_log_preview_revalidates_complete_channel_multiset_before_execution(tmp_path: Path, change: str) -> None:
    client = _LogControlClient(tmp_path)
    client.rows.append({"message": "other", "severity": "Warning", "time": 2, "messageId": "Custom"})
    state = tmp_path / "log-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state, "ak.wwise.core.log.clear", ("--log-channel", "general"))
    client.rows = list(reversed(client.rows))
    if change == "new-message":
        client.rows.append({"message": "new", "severity": "Message", "time": 1, "messageId": "Custom"})
    code, result = gateway.execute_gateway(["--state-dir", str(state), "execute", previewed["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    if change == "new-message":
        assert code == 2, result
        assert result["error_code"] == "STALE_LOG_CHANNEL"
        assert not any(uri == "ak.wwise.core.log.clear" for uri, _, _ in client.calls)
    else:
        assert code == 0, result
        assert invoke(result["next_command"]["gateway_argv"])["verified"] is True


@pytest.mark.parametrize("stage", ("preview", "execute", "verify"))
@pytest.mark.parametrize("overflow", ("rows", "bytes"))
def test_log_oversized_channel_observations_stay_bounded_and_never_prove_effect(tmp_path: Path, stage: str, overflow: str) -> None:
    client = _LogControlClient(tmp_path)
    oversized = ([client.rows[0]] * 1001 if overflow == "rows" else
        [{**client.rows[0], "message": "日志" * 12000}])
    state = tmp_path / "log-state"
    if stage == "preview":
        client.rows = oversized
        code, started = gateway.execute_gateway(["--state-dir", str(state), "draft-start", "ak.wwise.core.log.clear"],
            env=_env(tmp_path), client_factory=lambda _: client)
        assert code == 0, started
        code, result = gateway.execute_gateway(["--state-dir", str(state), "draft-declare-runtime-control-plan", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"], "--expected-revision", str(started["draft"]["revision"]), "--log-channel", "general"],
            env=_env(tmp_path), client_factory=lambda _: client)
        # Declaration preparation is allowed to expose the limit before Preview.
        if code == 0:
            code, result = gateway.execute_gateway(["--state-dir", str(state), "draft-check", started["draft"]["draft_id"],
                "--task-authority", started["task_authority"], "--expected-revision", str(result["draft"]["revision"])],
                env=_env(tmp_path), client_factory=lambda _: client)
        assert code == 2, result
        assert "LOG_OBSERVATION_TOO_LARGE" in json.dumps(result), result
        assert not any(uri == "ak.wwise.core.log.clear" for uri, _, _ in client.calls)
    else:
        previewed, invoke = _public_runtime_preview(tmp_path, client, state, "ak.wwise.core.log.clear", ("--log-channel", "general"))
        if stage == "execute":
            client.rows = oversized
        else:
            client.after = oversized
        code, result = gateway.execute_gateway(["--state-dir", str(state), "execute", previewed["transaction_id"]],
            env=_env(tmp_path), client_factory=lambda _: client)
        if stage == "execute":
            assert code == 2 and result["error_code"] == "LOG_OBSERVATION_TOO_LARGE", result
            assert not any(uri == "ak.wwise.core.log.clear" for uri, _, _ in client.calls)
        else:
            assert code == 0, result
            result = invoke(result["next_command"]["gateway_argv"])
            assert result["state"] == "result_schema_checked", result
            assert result["verified"] is False
            observation = result["verification"]["verification_scope"]["log_observation"]
            assert observation["outcome"] == "oversized"
            assert "items" not in observation["post_channel"]
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) < 100000


@pytest.mark.parametrize("stage", ("control", "readback"))
@pytest.mark.parametrize("malformed", ({"unexpected": True}, {"items": [{"message": "looks-right", "severity": "Message"}]}))
def test_log_invalid_native_shapes_cannot_verify_effect(tmp_path: Path, stage: str, malformed: dict) -> None:
    client = _LogControlClient(tmp_path)
    state = tmp_path / "log-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state, "ak.wwise.core.log.addItem", ("--message", "looks-right"))
    if stage == "control":
        client.control_result = malformed
    executed = invoke(["execute", previewed["transaction_id"]])
    if stage == "readback":
        original = client.call
        client.call = lambda uri, args=None, options=None: malformed if uri == LOG_GET_URI else original(uri, args, options)
    code, verified = gateway.execute_gateway(["--state-dir", str(state), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2, verified
    assert verified["state"] == "verification_failed"
    assert verified["verification"]["business_state_verified"] is False
    assert verified["verification"]["verification_scope"]["log_observation"]["outcome"] == ("malformed" if stage == "readback" else "malformed_control_result")
    assert verified["automatic_retry"] is False


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("invalid", ({"severity": "fatal"}, {"time": True}, {"parameters": [42]}))
def test_log_referenced_native_definition_rejects_wrong_enum_and_nested_types(tmp_path: Path, version: str, invalid: dict) -> None:
    client = _LogControlClient(tmp_path, version=version)
    state = tmp_path / "log-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state, "ak.wwise.core.log.addItem", ("--message", "retained"))
    executed = invoke(["execute", previewed["transaction_id"]])
    client.rows = [{**row, **invalid} for row in client.rows]
    code, verified = gateway.execute_gateway(["--state-dir", str(state), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2 and verified["state"] == "verification_failed", verified
    assert verified["verification"]["business_state_verified"] is False
    assert verified["verification"]["verification_scope"]["log_observation"]["outcome"] == "malformed"


@pytest.mark.parametrize("native_result,error_code", (([], "INVALID_READBACK"), (RuntimeError("log observation unavailable"), "READBACK_FAILED")))
def test_log_unavailable_readback_retains_once_executed_unverified_transaction(tmp_path: Path, native_result: object, error_code: str) -> None:
    client = _LogControlClient(tmp_path)
    state = tmp_path / "log-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state, "ak.wwise.core.log.clear", ("--log-channel", "general"))
    executed = invoke(["execute", previewed["transaction_id"]])
    original = client.call
    def call(uri, args=None, options=None):
        if uri == LOG_GET_URI:
            if isinstance(native_result, Exception):
                raise native_result
            return native_result
        return original(uri, args, options)
    client.call = call
    code, verified = gateway.execute_gateway(["--state-dir", str(state), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2 and verified["state"] == "executed_unverified", verified
    assert verified["status"] == "verification_deferred"
    assert verified["error_code"] == error_code
    assert verified["automatic_retry"] is False
    code, replay = gateway.execute_gateway(["--state-dir", str(state), "execute", previewed["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2, replay
    assert sum(uri == "ak.wwise.core.log.clear" for uri, _, _ in client.calls) == 1


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


class _ProfilerEnableDataClient(_RuntimeControlDraftClient):
    def __init__(self, tmp_path: Path, *, version: str = "2025.1") -> None:
        super().__init__(tmp_path, version=version)
        self.calls: list[tuple[str, object, object]] = []
        self.control_result: object = {}

    def call(self, uri: str, args: object = None, options: object = None) -> object:
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.profiler.enableProfilerData":
            if isinstance(self.control_result, Exception):
                raise self.control_result
            return self.control_result
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("declaration,rows", [
    (("--capture-data-empty",), []),
    (("--capture-data", "voices", "enable", "--capture-data", "voices", "enable"),
        [{"dataType": "voices", "enable": True}, {"dataType": "voices", "enable": True}]),
    (("--capture-data", "voices", "enable", "--capture-data", "voices", "disable"),
        [{"dataType": "voices", "enable": True}, {"dataType": "voices", "enable": False}]),
    (("--capture-data", "voices", "disable", "--capture-data", "voices", "enable"),
        [{"dataType": "voices", "enable": False}, {"dataType": "voices", "enable": True}]),
], ids=("empty", "identical", "enable-disable", "disable-enable"))
def test_profiler_capture_data_rows_execute_once_without_claiming_settings(
    tmp_path: Path, version: str, declaration: tuple[str, ...], rows: list[dict[str, object]],
) -> None:
    operation = "ak.wwise.core.profiler.enableProfilerData"
    client = _ProfilerEnableDataClient(tmp_path, version=version)
    state = tmp_path / "capture-data-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state, operation, declaration)
    artifact = TransactionStore(state).load_preview(previewed["transaction_id"]).artifact
    assert artifact["request"]["arguments"] == {"api": operation, "args": {"dataTypes": rows}, "options": {}}
    assert not any(uri == operation for uri, _, _ in client.calls)
    executed = invoke(["execute", previewed["transaction_id"]])
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is False, verified
    assert verified["state"] == "result_schema_checked"
    assert verified["verification"]["business_state_verified"] is False
    assert [call for call in client.calls if call[0] == operation] == [(operation, {"dataTypes": rows}, {})]
    boundary = verified["verification"]["verification_scope"]
    assert boundary["enabled_settings_verified"] is False
    assert boundary["empty_effect_verified"] is False
    assert boundary["repeated_data_set_resolution_verified"] is False
    assert boundary["prior_settings_restoration_verified"] is False
    assert "acknowledged the submitted capture-data directives" in verified["verification"]["message"]
    code, rejected = gateway.execute_gateway(["--state-dir", str(state), "execute", previewed["transaction_id"]],
        env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 2, rejected
    assert sum(uri == operation for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_profiler_capture_data_schema_and_continuation_disclose_list_and_observer_boundaries(tmp_path: Path, version: str) -> None:
    operation = "ak.wwise.core.profiler.enableProfilerData"
    env = _env(tmp_path, version=version)
    def offline(*argv):
        code, payload = gateway.execute_gateway(list(argv), env=env,
            client_factory=lambda _: pytest.fail("Discovery must stay offline"))
        assert code == 0, payload
        return payload
    schema = offline("request-schema", operation)
    contract = schema["business_adapter"]["declaration"]
    assert contract["input_forms"]["capture_data_changes"]["empty_flag"] == "--capture-data-empty"
    semantics = contract["field_semantics"]["capture_data_changes"]
    assert semantics["preserve_rows_and_order"] is True
    assert semantics["empty_effect"] == "unspecified_by_native_documentation"
    assert semantics["repeated_data_set_resolution"] == "unspecified_by_native_documentation"
    assert semantics["native_legality_established_by_schema"] is False
    boundary = contract["verification"]
    assert boundary["strategy"] == "native_result_schema_only"
    assert boundary["enabled_settings_verified"] is False
    assert boundary["prior_settings_restoration_verified"] is False
    started = offline("--state-dir", str(tmp_path / "state"), "draft-start", operation)
    declaration = started["draft"]["next_action_binding"]["declaration"]
    assert declaration["append_fields"] == contract
    assert "--capture-data-empty" in declaration["append"][0]
    assert declaration["native_request_input"] == "forbidden"


@pytest.mark.parametrize("target_ms", (-1, -2))
def test_profiler_signed_cursor_input_uses_returned_time_verifier_without_sentinel_meaning(tmp_path: Path, target_ms: int) -> None:
    code, schema = gateway.execute_gateway(["request-schema", PROFILER_SET_CURSOR_TIME_URI], env=_env(tmp_path),
        client_factory=lambda _: pytest.fail("Schema is offline"))
    assert code == 0, schema
    contract = schema["business_adapter"]["declaration"]
    assert contract["field_types"]["cursor_target_ms"] == "signed_integer_milliseconds"
    assert contract["field_semantics"]["cursor_target_ms"]["negative_value_meaning"] == "not_specified_by_native_documentation"
    assert contract["verification"]["comparison"] == "returned_time_not_requested_time"
    code, started = gateway.execute_gateway(["--state-dir", str(tmp_path / "discovery-state"),
        "draft-start", PROFILER_SET_CURSOR_TIME_URI], env=_env(tmp_path),
        client_factory=lambda _: pytest.fail("Draft start is offline"))
    assert code == 0, started
    declaration = started["draft"]["next_action_binding"]["declaration"]
    assert declaration["append_fields"] == contract
    assert "signed-integer-milliseconds" in declaration["append"][0]
    client = _ProfilerCursorControlClient(tmp_path)
    state = tmp_path / "signed-cursor-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state,
        PROFILER_SET_CURSOR_TIME_URI, ("--cursor-target-ms", str(target_ms)))
    artifact = TransactionStore(state).load_preview(previewed["transaction_id"]).artifact
    assert artifact["request"]["arguments"]["args"] == {"time": target_ms}
    assert not any(uri == PROFILER_SET_CURSOR_TIME_URI for uri, _, _ in client.calls)
    executed = invoke(["execute", previewed["transaction_id"]])
    verified = invoke(executed["next_command"]["gateway_argv"])
    assert verified["verified"] is True, verified
    observed = verified["verification"]["verification_scope"]["cursor_observation"]
    assert observed["returned_time_ms"] == observed["observed_time_ms"] == 1230
    assert (PROFILER_SET_CURSOR_TIME_URI, {"time": target_ms}, {}) in client.calls
    assert sum(uri == GET_CURSOR_TIME_URI for uri, _, _ in client.calls) == 1
    code, rejected = gateway.execute_gateway(["--state-dir", str(state), "execute", previewed["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2, rejected
    assert sum(uri == PROFILER_SET_CURSOR_TIME_URI for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("declaration,parser_error", [
    ((), False),
    (("--capture-data-empty", "--capture-data", "voices", "enable"), True),
    (("--capture-data", "voices", "enable", "--capture-data-empty"), True),
    (("--capture-data", "unknown-data-set", "enable"), False),
    (("--capture-data", "voices", "null"), False),
    (("--capture-data", "voices"), True),
    (("--capture-data-empty", "--args", '{"dataTypes":[]}'), True),
], ids=("missing", "empty-plus-row", "row-plus-empty", "unknown-data-set", "null-outcome", "half-row", "native-input"))
def test_profiler_capture_data_invalid_declaration_leaves_draft_unchanged(
    tmp_path: Path, version: str, declaration: tuple[str, ...], parser_error: bool,
) -> None:
    operation = "ak.wwise.core.profiler.enableProfilerData"
    state = tmp_path / "invalid-capture-state"
    client = _ProfilerEnableDataClient(tmp_path, version=version)
    env = _env(tmp_path, version=version)
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(state), *argv], env=env, client_factory=lambda _: client)
    code, started = run("draft-start", operation)
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    code, before = run("draft-inspect", draft_id, "--task-authority", authority)
    assert code == 0, before
    argv = ("draft-declare-runtime-control-plan", draft_id, "--task-authority", authority,
        "--expected-revision", str(started["draft"]["revision"]), *declaration)
    if parser_error:
        with pytest.raises(SystemExit) as rejected:
            run(*argv)
        assert rejected.value.code == 2
    else:
        code, rejected = run(*argv)
        assert code == 2, rejected
        assert rejected["details"]["repair"]["field"] in {"runtime_control_plan", "capture_data_changes"}
        assert rejected["details"]["repair"]["draft_changed"] is False
    code, after = run("draft-inspect", draft_id, "--task-authority", authority)
    assert code == 0, after
    assert after["draft"] == before["draft"]
    assert not any(uri == operation for uri, _, _ in client.calls)
    assert not (state / "transactions-v1").exists()


@pytest.mark.parametrize("operation,declaration", [
    (PROFILER_SET_CURSOR_TIME_URI, ("--cursor-target-ms", "null")),
    (PROFILER_SET_CURSOR_TIME_URI, ("--cursor-target-ms", "true")),
    (PROFILER_SET_CURSOR_TIME_URI, ("--cursor-target-ms", "-1.5")),
    (PROFILER_MOVE_CURSOR_URI, ("--capture-data-empty",)),
])
def test_profiler_new_input_forms_do_not_admit_nonintegers_or_undisclosed_fields(
    tmp_path: Path, operation: str, declaration: tuple[str, ...],
) -> None:
    state = tmp_path / "invalid-input-state"
    client = _ProfilerEnableDataClient(tmp_path)
    env = _env(tmp_path)
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(state), *argv], env=env, client_factory=lambda _: client)
    code, started = run("draft-start", operation)
    assert code == 0, started
    argv = ("draft-declare-runtime-control-plan", started["draft"]["draft_id"],
        "--task-authority", started["task_authority"], "--expected-revision", str(started["draft"]["revision"]), *declaration)
    if operation == PROFILER_SET_CURSOR_TIME_URI:
        with pytest.raises(SystemExit) as rejected:
            run(*argv)
        assert rejected.value.code == 2
    else:
        code, rejected = run(*argv)
        assert code == 2 and "not disclosed" in rejected["message"], rejected
    assert not any(uri == operation for uri, _, _ in client.calls)
    assert not (state / "transactions-v1").exists()


@pytest.mark.parametrize("operation,version,declaration", [
    *[("ak.wwise.core.profiler.enableProfilerData", version, ("--capture-data-empty",))
        for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")],
    (PROFILER_SET_CURSOR_TIME_URI, "2025.1", ("--cursor-target-ms", "-1")),
])
@pytest.mark.parametrize("failure", ("native-error", "malformed-result"))
def test_profiler_new_input_shapes_retain_failure_and_cannot_reexecute(
    tmp_path: Path, operation: str, version: str, declaration: tuple[str, ...], failure: str,
) -> None:
    client = _ProfilerEnableDataClient(tmp_path, version=version)
    original = client.call
    def call(uri, args=None, options=None):
        if uri == operation and uri != "ak.wwise.core.profiler.enableProfilerData":
            client.calls.append((uri, args, options))
            if isinstance(client.control_result, Exception):
                raise client.control_result
            return client.control_result
        return original(uri, args, options)
    client.call = call
    client.control_result = RuntimeError("native input outcome unavailable") if failure == "native-error" else {"unexpected": True}
    state = tmp_path / "failed-input-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state, operation, declaration)
    env = _env(tmp_path, version=version)
    code, executed = gateway.execute_gateway(["--state-dir", str(state), "execute", previewed["transaction_id"]],
        env=env, client_factory=lambda _: client)
    if failure == "native-error":
        assert code == 2 and executed["automatic_retry"] is False, executed
    else:
        assert code == 0, executed
        code, verified = gateway.execute_gateway(["--state-dir", str(state), *executed["next_command"]["gateway_argv"]],
            env=env, client_factory=lambda _: client)
        assert code == 2 and verified["state"] == "verification_failed", verified
        assert verified["verification"]["business_state_verified"] is False
        assert "acknowledged the submitted" not in verified["verification"]["message"]
    code, replay = gateway.execute_gateway(["--state-dir", str(state), "execute", previewed["transaction_id"]],
        env=env, client_factory=lambda _: client)
    assert code == 2, replay
    assert sum(uri == operation for uri, _, _ in client.calls) == 1
    assert not any(uri == GET_CURSOR_TIME_URI for uri, _, _ in client.calls)


@pytest.mark.parametrize("returned,observed,outcome", [(-1, -1, "unavailable"), (1230, 1220, "changed")])
def test_profiler_signed_cursor_unavailable_or_changed_result_remains_unverified(
    tmp_path: Path, returned: int, observed: int, outcome: str,
) -> None:
    client = _ProfilerCursorControlClient(tmp_path)
    client.control_result, client.cursor_result = {"return": returned}, {"return": observed}
    state = tmp_path / "signed-cursor-state"
    previewed, invoke = _public_runtime_preview(tmp_path, client, state,
        PROFILER_SET_CURSOR_TIME_URI, ("--cursor-target-ms", "-2"))
    executed = invoke(["execute", previewed["transaction_id"]])
    code, verified = gateway.execute_gateway(["--state-dir", str(state), *executed["next_command"]["gateway_argv"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == (0 if outcome == "unavailable" else 2), verified
    assert verified["verified"] is False
    assert verified["verification"]["business_state_verified"] is False
    assert verified["verification"]["verification_scope"]["cursor_observation"]["outcome"] == outcome
    assert verified["automatic_retry"] is False
    code, replay = gateway.execute_gateway(["--state-dir", str(state), "execute", previewed["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2, replay
    assert sum(uri == PROFILER_SET_CURSOR_TIME_URI for uri, _, _ in client.calls) == 1
