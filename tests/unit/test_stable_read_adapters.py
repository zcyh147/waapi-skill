from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from tests.support.public_route_probes import request_and_result_from_schema
from wwise_waapi.builders.stable_reads import (
    GET_GAME_OBJECTS_URI,
    GET_PROJECT_INFO_URI,
    GET_VOICE_CONTRIBUTIONS_URI,
    StableReadContractError,
    build_profiler_game_objects_request,
    build_profiler_voice_contributions_request,
    normalize_profiler_game_objects_result,
    normalize_profiler_time,
    normalize_profiler_voice_contributions_result,
    normalize_project_default_work_units_result,
)
from wwise_waapi.capabilities import CapabilityCatalog


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_gateway_stable_read_tests",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


class FakeClient:
    def __init__(self, responses: Mapping[str, Any]) -> None:
        self.responses = dict(responses)
        self.calls: list[
            tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]
        ] = []
        self.disconnected = False

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        return self.responses[uri]

    def disconnect(self) -> None:
        self.disconnected = True


def _live_info(version: str) -> dict[str, Any]:
    year, major = (int(item) for item in version.split("."))
    return {
        "displayName": "Wwise",
        "isCommandLine": False,
        "version": {
            "year": year,
            "major": major,
            "minor": 1,
            "build": 1,
            "displayName": f"v{version}.1",
        },
    }


def _gateway_env(tmp_path: Path, version: str) -> dict[str, str]:
    config_path = tmp_path / "config.json"
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
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": version,
        "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence"),
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", 0),
        ("60000", 60000),
        ("user", "user"),
        ("capture", "capture"),
    ],
)
def test_profiler_time_accepts_only_closed_milliseconds_or_cursor_tokens(
    raw: str,
    expected: int | str,
) -> None:
    assert normalize_profiler_time(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["-1", "1.5", "latest", " capture ", str(1 << 53)],
)
def test_profiler_time_rejects_unreviewed_or_out_of_range_values(raw: str) -> None:
    with pytest.raises(
        StableReadContractError,
        match="Profiler time",
    ) as exc:
        normalize_profiler_time(raw)
    assert exc.value.error_code == "INVALID_STABLE_READ_INPUT"


def test_game_objects_builder_and_projection_normalize_the_2022_field_names() -> None:
    request = build_profiler_game_objects_request(
        version="2022.1",
        time="capture",
    )
    assert request.dispatch_payload() == {
        "uri": GET_GAME_OBJECTS_URI,
        "args": {"time": "capture"},
        "options": {},
    }
    projection = normalize_profiler_game_objects_result(
        version="2022.1",
        result={
            "return": [
                {
                    "id": 1001,
                    "name": "Player",
                    "registrationTime": 20,
                    "unregistrationTime": -1,
                }
            ]
        },
    )
    assert projection == {
        "count": 1,
        "game_objects": [
            {
                "id": 1001,
                "name": "Player",
                "register_time": 20,
                "unregister_time": -1,
            }
        ],
    }


def test_game_objects_projection_uses_the_same_shape_for_2023_and_later() -> None:
    projection = normalize_profiler_game_objects_result(
        version="2025.1",
        result={
            "return": [
                {
                    "id": 1001,
                    "name": "Player",
                    "registerTime": 20,
                    "unregisterTime": -1,
                }
            ]
        },
    )
    assert projection["game_objects"][0]["register_time"] == 20
    assert projection["game_objects"][0]["unregister_time"] == -1


def test_game_objects_result_mismatch_is_not_converted_to_an_empty_list() -> None:
    with pytest.raises(StableReadContractError) as exc:
        normalize_profiler_game_objects_result(
            version="2022.1",
            result={
                "return": [
                    {
                        "id": 1001,
                        "name": "Player",
                        "registerTime": 20,
                        "unregisterTime": -1,
                    }
                ]
            },
        )
    assert exc.value.error_code == "INVALID_STABLE_READ_RESULT"
    assert exc.value.details["missing_field"] == "registrationTime"


def test_game_objects_builder_closes_the_2021_absence() -> None:
    with pytest.raises(StableReadContractError) as exc:
        build_profiler_game_objects_request(
            version="2021.1",
            time="capture",
        )
    assert exc.value.error_code == "UNSUPPORTED_STABLE_READ_VERSION"


def test_voice_contributions_builder_owns_pipeline_order_and_dry_path() -> None:
    dry = build_profiler_voice_contributions_request(
        version="2021.1",
        time="capture",
        voice_pipeline_id="17",
    )
    routed = build_profiler_voice_contributions_request(
        version="2025.1",
        time="1200",
        voice_pipeline_id="17",
        bus_pipeline_ids=("21", "22"),
    )
    assert dry.args == {
        "voicePipelineID": 17,
        "bussesPipelineID": [],
        "time": "capture",
    }
    assert routed.args["bussesPipelineID"] == [21, 22]


def test_voice_contributions_never_fabricates_an_older_dsf_value() -> None:
    projection = normalize_profiler_voice_contributions_result(
        version="2024.1",
        result={
            "return": {
                "volume": -3.0,
                "LPF": 2.0,
                "HPF": 1.0,
                "objects": [{"name": "Voice", "children": []}],
            }
        },
    )
    assert projection["dsf"] == {
        "feature_available": False,
        "reported": False,
        "value": None,
    }


def test_voice_contributions_distinguishes_2025_dsf_availability_and_report() -> None:
    projection = normalize_profiler_voice_contributions_result(
        version="2025.1",
        result={
            "return": {
                "volume": -3.0,
                "LPF": 2.0,
                "HPF": 1.0,
                "DSF": -0.5,
                "objects": [],
            }
        },
    )
    assert projection["dsf"] == {
        "feature_available": True,
        "reported": True,
        "value": -0.5,
    }


def test_voice_contributions_rejects_2025_dsf_in_an_older_lane() -> None:
    with pytest.raises(StableReadContractError) as exc:
        normalize_profiler_voice_contributions_result(
            version="2024.1",
            result={
                "return": {
                    "volume": -3.0,
                    "LPF": 2.0,
                    "HPF": 1.0,
                    "DSF": -0.5,
                    "objects": [],
                }
            },
        )
    assert exc.value.error_code == "INVALID_STABLE_READ_RESULT"


def test_project_defaults_distinguish_unavailable_from_available_not_reported() -> None:
    old = normalize_project_default_work_units_result(
        version="2021.1",
        result=None,
    )
    current = normalize_project_default_work_units_result(
        version="2025.1",
        result={},
    )
    assert old["default_work_units"] == {
        "feature_available": False,
        "reported": False,
        "value": None,
    }
    assert current["default_work_units"] == {
        "feature_available": True,
        "reported": False,
        "value": None,
    }


def test_project_defaults_rejects_2025_fields_in_an_older_lane() -> None:
    with pytest.raises(StableReadContractError) as exc:
        normalize_project_default_work_units_result(
            version="2024.1",
            result={"defaultWorkUnits": {}},
        )
    assert exc.value.error_code == "INVALID_STABLE_READ_RESULT"


def test_gateway_game_objects_dispatches_one_closed_2022_request(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2022.1"),
            GET_GAME_OBJECTS_URI: {
                "return": [
                    {
                        "id": 1001,
                        "name": "Player",
                        "registrationTime": 20,
                        "unregistrationTime": -1,
                    }
                ]
            },
        }
    )
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--time", "capture"],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["agent_result"]["game_objects"][0]["register_time"] == 20
    assert list(payload)[-1] == "agent_result"
    assert client.calls == [
        ("ak.wwise.core.getInfo", None, None),
        (GET_GAME_OBJECTS_URI, {"time": "capture"}, {}),
    ]
    assert client.disconnected is True


def test_gateway_game_objects_returns_structured_result_mismatch(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2022.1"),
            GET_GAME_OBJECTS_URI: {
                "return": [
                    {
                        "id": 1001,
                        "name": "Player",
                        "registerTime": 20,
                        "unregisterTime": -1,
                    }
                ]
            },
        }
    )
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--time", "capture"],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error_code"] == "INVALID_STABLE_READ_RESULT"
    assert payload["details"]["missing_field"] == "registrationTime"


def test_gateway_voice_contributions_dispatches_closed_pipeline_args(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2025.1"),
            GET_VOICE_CONTRIBUTIONS_URI: {
                "return": {
                    "volume": -3.0,
                    "LPF": 2.0,
                    "HPF": 1.0,
                    "DSF": -0.5,
                    "objects": [],
                }
            },
        }
    )
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "profiler-voice-contributions",
            "--time",
            "1200",
            "--voice-pipeline-id",
            "17",
            "--bus-pipeline-id",
            "21",
            "--bus-pipeline-id",
            "22",
        ],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 0
    assert payload["agent_result"]["dsf"]["value"] == -0.5
    assert client.calls[-1] == (
        GET_VOICE_CONTRIBUTIONS_URI,
        {
            "voicePipelineID": 17,
            "bussesPipelineID": [21, 22],
            "time": 1200,
        },
        {},
    )


@pytest.mark.parametrize("version", ["2021.1", "2024.1"])
def test_gateway_project_defaults_do_not_fabricate_2025_fields(
    tmp_path: Path,
    version: str,
) -> None:
    responses: dict[str, Any] = {
        "ak.wwise.core.getInfo": _live_info(version),
    }
    if version != "2021.1":
        capability = CapabilityCatalog().describe(version, GET_PROJECT_INFO_URI)
        _, _, project_result = request_and_result_from_schema(capability.schema)
        responses[GET_PROJECT_INFO_URI] = project_result
    client = FakeClient(responses)

    exit_code, payload = waapi_gateway.execute_gateway(
        ["project-default-work-units"],
        env=_gateway_env(tmp_path, version),
        client_factory=lambda url: client,
    )
    assert exit_code == 0
    assert payload["agent_result"]["default_work_units"] == {
        "feature_available": False,
        "reported": False,
        "value": None,
    }
    expected_uris = ["ak.wwise.core.getInfo"]
    if version != "2021.1":
        expected_uris.append(GET_PROJECT_INFO_URI)
    assert [call[0] for call in client.calls] == expected_uris


def test_gateway_project_defaults_reports_real_2025_values(
    tmp_path: Path,
) -> None:
    capability = CapabilityCatalog().describe("2025.1", GET_PROJECT_INFO_URI)
    _, _, project_result = request_and_result_from_schema(capability.schema)
    result_schema = capability.schema["resultSchema"]
    categories = tuple(
        result_schema["properties"]["defaultWorkUnits"]["properties"]
    )
    work_unit = {
        "id": "{11111111-1111-1111-1111-111111111111}",
        "name": "Default Work Unit",
        "path": r"\Events\Default Work Unit",
        "filePath": "/sandbox/Default Work Unit.wwu",
    }
    project_result["defaultWorkUnits"] = {
        category: dict(work_unit)
        for category in categories
    }
    project_result["defaultImportWorkUnit"] = dict(work_unit)
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2025.1"),
            GET_PROJECT_INFO_URI: project_result,
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["project-default-work-units"],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 0
    assert payload["agent_result"]["default_work_units"]["feature_available"] is True
    assert payload["agent_result"]["default_work_units"]["reported"] is True
    assert payload["agent_result"]["default_import_work_unit"]["reported"] is True
    assert payload["agent_result"]["default_work_units"]["value"]["Events"] == work_unit


def test_fixed_profiler_uri_rejects_generic_call_before_connect(
    tmp_path: Path,
) -> None:
    factory_called = False

    def factory(url: str) -> FakeClient:
        nonlocal factory_called
        factory_called = True
        raise AssertionError("generic fixed-route boundary must not connect")

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            GET_GAME_OBJECTS_URI,
            "--args-json",
            '{"time":"capture"}',
            "--options-json",
            "{}",
        ],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=factory,
    )
    assert exit_code == 2
    assert payload["error_code"] == "FIXED_COMMAND_REQUIRED"
    assert payload["required_command"] == "profiler-game-objects"
    assert factory_called is False


def test_invalid_profiler_input_fails_before_connect(tmp_path: Path) -> None:
    factory_called = False

    def factory(url: str) -> FakeClient:
        nonlocal factory_called
        factory_called = True
        raise AssertionError("invalid fixed-read input must not connect")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--time", "latest"],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=factory,
    )
    assert exit_code == 2
    assert payload["error_code"] == "INVALID_STABLE_READ_INPUT"
    assert factory_called is False
