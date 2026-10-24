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

GET_VOICES_URI = "ak.wwise.core.profiler.getVoices"
GET_BUSSES_URI = "ak.wwise.core.profiler.getBusses"


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
                "wwise_version": version,
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
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
                        "registerTime": True,
                    }
                ]
            },
        )
    assert exc.value.error_code == "INVALID_STABLE_READ_RESULT"
    assert exc.value.details["field"] == "registerTime"


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


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_gateway_game_objects_dispatches_one_closed_request_per_exact_lane(
    tmp_path: Path,
    version: str,
) -> None:
    register_field = "registrationTime" if version == "2022.1" else "registerTime"
    unregister_field = (
        "unregistrationTime" if version == "2022.1" else "unregisterTime"
    )
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info(version),
            GET_GAME_OBJECTS_URI: {
                "return": [
                    {
                        "id": 1001,
                        "name": "Player",
                        register_field: 20,
                        unregister_field: -1,
                    }
                ]
            },
        }
    )
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture", "latest"],
        env=_gateway_env(tmp_path, version),
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


def test_gateway_game_objects_accepts_recorded_2022_authoring_timestamps(
    tmp_path: Path,
) -> None:
    recorded = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "query"
         / "profiler-game-objects-2022-authoring-recorded.json").read_text(encoding="utf-8")
    )
    info = _live_info("2022.1")
    info["version"].update(minor=19, build=8584, displayName="v2022.1.19")
    client = FakeClient({
        "ak.wwise.core.getInfo": info,
        GET_GAME_OBJECTS_URI: recorded["result"],
    })
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture-ms", "39861"],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 0, payload
    assert payload["agent_result"] == {
        "count": 1,
        "game_objects": [{
            "id": 18446744073709551614,
            "name": "Transport/Soundcaster",
            "register_time": 22634,
            "unregister_time": 2147483647,
        }],
    }
    assert list(payload)[-1] == "agent_result"
    assert client.calls == [
        ("ak.wwise.core.getInfo", None, None),
        (GET_GAME_OBJECTS_URI, {"time": 39861}, {}),
    ]
    assert client.disconnected is True


def test_gateway_game_objects_preserves_empty_2022_rows_as_unreported(
    tmp_path: Path,
) -> None:
    client = FakeClient({
        "ak.wwise.core.getInfo": _live_info("2022.1"),
        GET_GAME_OBJECTS_URI: {"return": [{}]},
    })
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture", "latest"],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 0, payload
    assert payload["agent_result"] == {"count": 1, "game_objects": [{
        "id": None, "name": None, "register_time": None, "unregister_time": None,
        "unreported_fields": ["id", "name", "register_time", "unregister_time"],
    }]}
    assert list(payload)[-1] == "agent_result"
    assert client.disconnected is True


@pytest.mark.parametrize("is_console", (False, True))
def test_gateway_game_objects_preserves_2022_identity_and_timestamp_omissions(
    tmp_path: Path,
    is_console: bool,
) -> None:
    info = _live_info("2022.1")
    info["isCommandLine"] = is_console
    client = FakeClient({
        "ak.wwise.core.getInfo": info,
        GET_GAME_OBJECTS_URI: {"return": [
            {"id": 0},
            {"name": ""},
            {"registrationTime": 0, "unregistrationTime": -1},
            {"id": 1001, "name": "Player"},
            {"id": 1002, "registrationTime": -2147483648},
            {"name": "Partial", "unregisterTime": 2147483647},
        ]},
    })
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture-ms", "0"],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 0, payload
    assert payload["agent_result"] == {"count": 6, "game_objects": [
        {"id": 0, "name": None, "register_time": None, "unregister_time": None,
         "unreported_fields": ["name", "register_time", "unregister_time"]},
        {"id": None, "name": "", "register_time": None, "unregister_time": None,
         "unreported_fields": ["id", "register_time", "unregister_time"]},
        {"id": None, "name": None, "register_time": 0, "unregister_time": -1,
         "unreported_fields": ["id", "name"]},
        {"id": 1001, "name": "Player", "register_time": None, "unregister_time": None,
         "unreported_fields": ["register_time", "unregister_time"]},
        {"id": 1002, "name": None, "register_time": -2147483648, "unregister_time": None,
         "unreported_fields": ["name", "unregister_time"]},
        {"id": None, "name": "Partial", "register_time": None, "unregister_time": 2147483647,
         "unreported_fields": ["id", "register_time"]},
    ]}
    assert list(payload)[-1] == "agent_result"
    assert client.calls[-1] == (GET_GAME_OBJECTS_URI, {"time": 0}, {})
    assert client.disconnected is True


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("is_console", (False, True))
@pytest.mark.parametrize(
    ("object_id", "accepted_in_unsigned", "accepted_in_id64bits"),
    [
        (0, True, True),
        (18446744073709551615, True, True),
        (-1, False, True),
        (-9223372036854775808, False, True),
        (-9223372036854775809, False, False),
        (18446744073709551616, False, False),
        (True, False, False),
        (1.0, False, False),
        ("1", False, False),
        (None, False, False),
    ],
)
def test_gateway_game_objects_enforces_reflected_id_domains_on_both_hosts(
    tmp_path: Path,
    version: str,
    is_console: bool,
    object_id: Any,
    accepted_in_unsigned: bool,
    accepted_in_id64bits: bool,
) -> None:
    info = _live_info(version)
    info["isCommandLine"] = is_console
    timestamps = (
        {"registrationTime": 20, "unregistrationTime": -1}
        if version == "2022.1" else {"registerTime": 20, "unregisterTime": -1}
    )
    client = FakeClient({
        "ak.wwise.core.getInfo": info,
        GET_GAME_OBJECTS_URI: {"return": [{"id": object_id, "name": "Player", **timestamps}]},
    })
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture", "latest"],
        env=_gateway_env(tmp_path, version),
        client_factory=lambda url: client,
    )
    accepted = accepted_in_unsigned if version in {"2022.1", "2023.1"} else accepted_in_id64bits
    if accepted:
        assert exit_code == 0, payload
        assert payload["agent_result"] == {"count": 1, "game_objects": [{
            "id": object_id, "name": "Player", "register_time": 20, "unregister_time": -1,
        }]}
        assert list(payload)[-1] == "agent_result"
    else:
        assert exit_code == 2, payload
        assert payload["error_code"] == "INVALID_STABLE_READ_RESULT"
        assert payload["details"]["field"] == "id"
        assert "agent_result" not in payload
    assert client.disconnected is True


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("missing_field", ("id", "name", "registerTime", "unregisterTime"))
def test_gateway_game_objects_retains_required_row_fields_from_2023(
    tmp_path: Path,
    version: str,
    missing_field: str,
) -> None:
    row = {"id": 1001, "name": "Player", "registerTime": 20, "unregisterTime": -1}
    del row[missing_field]
    client = FakeClient({
        "ak.wwise.core.getInfo": _live_info(version),
        GET_GAME_OBJECTS_URI: {"return": [row]},
    })
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture", "latest"],
        env=_gateway_env(tmp_path, version),
        client_factory=lambda url: client,
    )
    assert exit_code == 2, payload
    assert payload["error_code"] == "SemanticValidationError"
    assert "agent_result" not in payload
    assert client.disconnected is True


def test_gateway_game_objects_keeps_2021_unavailable_before_connect(tmp_path: Path) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture", "latest"],
        env=_gateway_env(tmp_path, "2021.1"),
        client_factory=lambda url: pytest.fail("2021.1 must remain unavailable before connecting"),
    )
    assert exit_code == 2, payload
    assert payload["error_code"] == "UNSUPPORTED_STABLE_READ_VERSION"
    assert "agent_result" not in payload


@pytest.mark.parametrize("version", ("2022.1", "2023.1"))
def test_gateway_game_objects_rejects_negative_ids_before_id64bits_versions(
    tmp_path: Path,
    version: str,
) -> None:
    timestamps = (
        {"registrationTime": 20, "unregistrationTime": -1}
        if version == "2022.1" else {"registerTime": 20, "unregisterTime": -1}
    )
    client = FakeClient({
        "ak.wwise.core.getInfo": _live_info(version),
        GET_GAME_OBJECTS_URI: {"return": [{"id": -1, "name": "Player", **timestamps}]},
    })
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture", "latest"],
        env=_gateway_env(tmp_path, version),
        client_factory=lambda url: client,
    )
    assert exit_code == 2, payload
    assert payload["error_code"] == "INVALID_STABLE_READ_RESULT"
    assert payload["details"]["field"] == "id"
    assert "agent_result" not in payload
    assert client.disconnected is True


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_gateway_game_objects_schema_discloses_result_domains_and_unreported_fields(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["request-schema", GET_GAME_OBJECTS_URI],
        env=_gateway_env(tmp_path, version),
        client_factory=lambda url: pytest.fail("schema discovery must remain offline"),
    )
    assert exit_code == 0, payload
    assert payload["native_request_fields_disclosed"] is False
    assert payload["input_shape"] == "fixed_business_command"
    contract = payload["commands"][0]["result_contract"]
    assert contract["row_fields"] == ["id", "name", "register_time", "unregister_time"]
    assert contract["id"] == {
        "domain": "uint64" if version in {"2022.1", "2023.1"} else "int64-or-uint64",
        "minimum": 0 if version in {"2022.1", "2023.1"} else -9223372036854775808,
        "maximum": 18446744073709551615,
    }
    assert contract["timestamps"] == {"domain": "int32", "minimum": -2147483648, "maximum": 2147483647}
    assert contract["unreported_fields"] == {
        "permitted": version == "2022.1", "value": None,
        "listed_by": "unreported_fields", "list_present_only_when_unreported": True,
        "order": ["id", "name", "register_time", "unregister_time"],
    }
    assert contract["limits"] == {"maximum_rows": 4096, "maximum_name_utf8_bytes": 4096,
                                  "maximum_result_bytes": 262144}


@pytest.mark.parametrize(
    ("rows", "expected_error", "expected_detail"),
    [
        ([{}] * 4097, "INVALID_STABLE_READ_RESULT", {"maximum_rows": 4096, "actual_count": 4097}),
        ([{"name": "é" * 2049}], "INVALID_STABLE_READ_RESULT", {"field": "name"}),
        ([{"name": None}], "SemanticValidationError", {}),
    ],
)
def test_gateway_game_objects_keeps_partial_2022_rows_bounded_and_typed(
    tmp_path: Path,
    rows: list[dict[str, Any]],
    expected_error: str,
    expected_detail: dict[str, Any],
) -> None:
    client = FakeClient({
        "ak.wwise.core.getInfo": _live_info("2022.1"),
        GET_GAME_OBJECTS_URI: {"return": rows},
    })
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture", "latest"],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 2, payload
    assert payload["error_code"] == expected_error
    assert expected_detail.items() <= payload.get("details", {}).items()
    assert "agent_result" not in payload
    assert client.disconnected is True


def test_gateway_game_objects_keeps_2022_alias_selection_row_local(
    tmp_path: Path,
) -> None:
    client = FakeClient({
        "ak.wwise.core.getInfo": _live_info("2022.1"),
        GET_GAME_OBJECTS_URI: {"return": [
            {"id": 1001, "name": "Reflected", "registrationTime": 20, "unregistrationTime": -1},
            {"id": 1002, "name": "Observed", "registerTime": 21, "unregisterTime": -1},
            {"id": 1003, "name": "Matching aliases", "registrationTime": -(1 << 31),
             "unregistrationTime": 2147483647, "registerTime": -(1 << 31),
             "unregisterTime": 2147483647, "futureNativeField": "ignored as before"},
            {"id": 1004, "name": "Reflected again", "registrationTime": 22, "unregistrationTime": -1},
        ]},
    })
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture", "latest"],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 0, payload
    assert payload["agent_result"] == {"count": 4, "game_objects": [
        {"id": 1001, "name": "Reflected", "register_time": 20, "unregister_time": -1},
        {"id": 1002, "name": "Observed", "register_time": 21, "unregister_time": -1},
        {"id": 1003, "name": "Matching aliases", "register_time": -2147483648, "unregister_time": 2147483647},
        {"id": 1004, "name": "Reflected again", "register_time": 22, "unregister_time": -1},
    ]}
    assert list(payload)[-1] == "agent_result"


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_gateway_game_objects_does_not_extend_2022_aliases_to_later_versions(
    tmp_path: Path,
    version: str,
) -> None:
    client = FakeClient({
        "ak.wwise.core.getInfo": _live_info(version),
        GET_GAME_OBJECTS_URI: {"return": [
            {"id": 1001, "name": "Player", "registrationTime": 20, "unregistrationTime": -1},
        ]},
    })
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture", "latest"],
        env=_gateway_env(tmp_path, version),
        client_factory=lambda url: client,
    )
    assert exit_code == 2
    # Later schemas require the modern fields before normalization is reached.
    assert payload["error_code"] == "SemanticValidationError"
    assert "agent_result" not in payload
    assert client.disconnected is True


@pytest.mark.parametrize(
    ("timestamps", "register_time", "unregister_time", "unreported"),
    [
        ({"registerTime": 20}, 20, None, ["unregister_time"]),
        ({"unregisterTime": -1}, None, -1, ["register_time"]),
        ({"registrationTime": 20}, 20, None, ["unregister_time"]),
        ({"unregistrationTime": -1}, None, -1, ["register_time"]),
        ({"registrationTime": 20, "unregisterTime": -1}, 20, -1, []),
        ({"registerTime": 20, "unregistrationTime": -1}, 20, -1, []),
        ({"registrationTime": 20, "unregistrationTime": -1, "registerTime": 20}, 20, -1, []),
        ({"registrationTime": 20, "registerTime": 20, "unregisterTime": -1}, 20, -1, []),
        ({"registrationTime": 0, "registerTime": 0}, 0, None, ["unregister_time"]),
        ({"unregistrationTime": 0, "unregisterTime": 0}, None, 0, ["register_time"]),
    ],
)
def test_gateway_game_objects_accepts_independently_optional_2022_timestamps(
    tmp_path: Path,
    timestamps: dict[str, Any],
    register_time: int | None,
    unregister_time: int | None,
    unreported: list[str],
) -> None:
    client = FakeClient({
        "ak.wwise.core.getInfo": _live_info("2022.1"),
        GET_GAME_OBJECTS_URI: {"return": [{"id": 1001, "name": "Player", **timestamps}]},
    })
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture", "latest"],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 0, payload
    expected = {"id": 1001, "name": "Player", "register_time": register_time,
                "unregister_time": unregister_time}
    if unreported:
        expected["unreported_fields"] = unreported
    assert payload["agent_result"] == {"count": 1, "game_objects": [expected]}
    assert list(payload)[-1] == "agent_result"
    assert client.disconnected is True


@pytest.mark.parametrize(
    ("timestamps", "expected_detail"),
    [
        ({"registrationTime": 21, "registerTime": 20},
         {"conflicting_fields": ["registrationTime", "registerTime"]}),
        ({"unregistrationTime": 0, "unregisterTime": -1},
         {"conflicting_fields": ["unregistrationTime", "unregisterTime"]}),
        ({"registrationTime": 21, "unregistrationTime": -1, "registerTime": 20, "unregisterTime": -1},
         {"conflicting_fields": ["registrationTime", "registerTime"]}),
        ({"registrationTime": 20, "unregistrationTime": 0, "registerTime": 20, "unregisterTime": -1},
         {"conflicting_fields": ["unregistrationTime", "unregisterTime"]}),
        ({"registerTime": True, "unregisterTime": -1}, {"field": "registerTime"}),
        ({"registerTime": 20, "unregisterTime": 1 << 31}, {"field": "unregisterTime"}),
        ({"registrationTime": True, "unregistrationTime": -1, "registerTime": 1, "unregisterTime": -1},
         {"field": "registrationTime"}),
        ({"registrationTime": 20, "unregistrationTime": -(1 << 31) - 1, "registerTime": 20, "unregisterTime": -1},
         {"field": "unregistrationTime"}),
        ({"registerTime": None}, {"field": "registerTime"}),
        ({"unregisterTime": "0"}, {"field": "unregisterTime"}),
        ({"registrationTime": 0.0, "registerTime": 0}, {"field": "registrationTime"}),
        ({"unregistrationTime": False, "unregisterTime": 0}, {"field": "unregistrationTime"}),
        ({"registrationTime": 0, "registerTime": 1 << 31}, {"field": "registerTime"}),
        ({"unregistrationTime": 0, "unregisterTime": -(1 << 31) - 1}, {"field": "unregisterTime"}),
    ],
)
def test_gateway_game_objects_rejects_invalid_or_conflicting_2022_timestamps(
    tmp_path: Path,
    timestamps: dict[str, Any],
    expected_detail: dict[str, Any],
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2022.1"),
            GET_GAME_OBJECTS_URI: {
                "return": [
                    {
                        "id": 1001,
                        "name": "Player",
                        **timestamps,
                    }
                ]
            },
        }
    )
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture", "latest"],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error_code"] == "INVALID_STABLE_READ_RESULT"
    assert expected_detail.items() <= payload["details"].items()
    assert "agent_result" not in payload
    assert client.disconnected is True


@pytest.mark.parametrize(
    "version",
    ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
)
def test_gateway_voice_contributions_resolves_identity_in_every_exact_lane(
    tmp_path: Path,
    version: str,
) -> None:
    voice_id = "{11111111-1111-1111-1111-111111111111}"
    result = {
        "volume": -3.0,
        "LPF": 2.0,
        "HPF": 1.0,
        "objects": [],
    }
    if version == "2025.1":
        result["DSF"] = -0.5
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info(version),
            GET_VOICES_URI: {
                "return": [
                    {
                        "pipelineID": 17,
                        "gameObjectID": 1001,
                        "objectGUID": voice_id,
                        "objectName": "Rain",
                        "gameObjectName": "Weather",
                    }
                ]
            },
            GET_VOICE_CONTRIBUTIONS_URI: {"return": result},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "profiler-voice-contributions",
            "--capture",
            "latest",
            "--voice-object-id",
            voice_id,
        ],
        env=_gateway_env(tmp_path, version),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert client.calls[-1] == (
        GET_VOICE_CONTRIBUTIONS_URI,
        {
            "voicePipelineID": 17,
            "bussesPipelineID": [],
            "time": "capture",
        },
        {},
    )
    assert payload["agent_result"]["volume"] == -3.0


def test_gateway_voice_contributions_resolves_business_object_identities(
    tmp_path: Path,
) -> None:
    voice_id = "{11111111-1111-1111-1111-111111111111}"
    first_bus = "{22222222-2222-2222-2222-222222222222}"
    second_bus = "{33333333-3333-3333-3333-333333333333}"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2025.1"),
            GET_VOICES_URI: {
                "return": [
                    {
                        "pipelineID": 17,
                        "gameObjectID": 1001,
                        "objectGUID": voice_id,
                        "objectName": "Rain",
                        "gameObjectName": "Weather",
                    }
                ]
            },
            GET_BUSSES_URI: {
                "return": [
                    {
                        "pipelineID": 21,
                        "gameObjectID": 1001,
                        "objectGUID": first_bus,
                        "objectName": "Weather Bus",
                        "gameObjectName": "Weather",
                    },
                    {
                        "pipelineID": 22,
                        "gameObjectID": 1001,
                        "objectGUID": second_bus,
                        "objectName": "Master Audio Bus",
                        "gameObjectName": "Weather",
                    },
                ]
            },
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
            "--capture-ms",
            "1200",
            "--voice-object-id",
            voice_id,
            "--bus-object-id",
            first_bus,
            "--bus-object-id",
            second_bus,
        ],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )
    assert exit_code == 0, payload
    assert payload["agent_result"]["dsf"]["value"] == -0.5
    assert client.calls[-3:-1] == [
        (
            GET_VOICES_URI,
            {"time": 1200},
            {
                "return": [
                    "pipelineID",
                    "gameObjectID",
                    "objectGUID",
                    "objectName",
                    "gameObjectName",
                ]
            },
        ),
        (
            GET_BUSSES_URI,
            {"time": 1200},
            {
                "return": [
                    "pipelineID",
                    "gameObjectID",
                    "objectGUID",
                    "objectName",
                    "gameObjectName",
                ]
            },
        ),
    ]
    assert client.calls[-1] == (
        GET_VOICE_CONTRIBUTIONS_URI,
        {
            "voicePipelineID": 17,
            "bussesPipelineID": [21, 22],
            "time": 1200,
        },
        {},
    )


def test_gateway_voice_contributions_accepts_copy_ready_voice_and_bus_handles(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2025.1"),
            GET_VOICES_URI: {
                "return": [
                    {
                        "pipelineID": 17,
                        "gameObjectID": 1001,
                        "objectGUID": "{11111111-1111-1111-1111-111111111111}",
                        "objectName": "Rain",
                        "gameObjectName": "Weather",
                    }
                ]
            },
            GET_BUSSES_URI: {
                "return": [
                    {
                        "pipelineID": pipeline_id,
                        "gameObjectID": 1001,
                        "objectGUID": object_guid,
                        "objectName": name,
                        "gameObjectName": "Weather",
                    }
                    for pipeline_id, object_guid, name in (
                        (21, "{22222222-2222-2222-2222-222222222222}", "Weather Bus"),
                        (22, "{33333333-3333-3333-3333-333333333333}", "Master Bus"),
                    )
                ]
            },
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

    project_root = tmp_path / "project"
    project_root.mkdir()
    project_file = project_root / "SampleProject.wproj"
    project_file.write_text("fixture", encoding="utf-8")
    client.responses[GET_PROJECT_INFO_URI] = {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        "name": "SampleProject", "path": str(project_file)}
    env = {**_gateway_env(tmp_path, "2025.1"), "WAAPI_SKILL_STATE_DIR": str(tmp_path / "state")}
    observed = []
    for operation in (GET_VOICES_URI, GET_BUSSES_URI):
        code, result = waapi_gateway.execute_gateway(["core-call", operation, "--profiler-position", "1200"],
            env=env, client_factory=lambda _url: client)
        assert code == 0, result
        observed.append(result["agent_result"]["return"])
    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-voice-contributions", "--capture-ms", "1200",
         "--voice-instance-handle", observed[0][0]["voice_instance_handle"],
         "--bus-instance-handle", observed[1][0]["bus_instance_handle"],
         "--bus-instance-handle", observed[1][1]["bus_instance_handle"]],
        env=env, client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert client.calls[-1] == (
        GET_VOICE_CONTRIBUTIONS_URI,
        {
            "voicePipelineID": 17,
            "bussesPipelineID": [21, 22],
            "time": 1200,
        },
        {},
    )


def test_profiler_read_parser_has_no_native_time_or_pipeline_parameters() -> None:
    parser = waapi_gateway.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if "profiler-voice-contributions" in (getattr(action, "choices", None) or {})
    )
    voice = subparsers.choices["profiler-voice-contributions"]
    options = {
        option
        for action in voice._actions
        for option in action.option_strings
    }

    assert {
        "--capture",
        "--capture-ms",
        "--voice-object-id",
        "--bus-object-id",
        "--voice-instance-handle",
        "--bus-instance-handle",
    } <= options
    assert not {"--time", "--voice-pipeline-id", "--bus-pipeline-id"} & options


def test_gateway_voice_contributions_returns_bounded_semantic_ambiguity(
    tmp_path: Path,
) -> None:
    voice_id = "{11111111-1111-1111-1111-111111111111}"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2025.1"),
            GET_VOICES_URI: {
                "return": [
                    {
                        "pipelineID": pipeline_id,
                        "gameObjectID": game_object_id,
                        "objectGUID": voice_id,
                        "objectName": "Rain",
                        "gameObjectName": game_object_name,
                    }
                    for pipeline_id, game_object_id, game_object_name in (
                        (17, 1001, "Weather A"),
                        (18, 1002, "Weather B"),
                    )
                ]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "profiler-voice-contributions",
            "--capture",
            "latest",
            "--voice-object-id",
            voice_id,
        ],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["status"] == "needs_clarification"
    assert payload["agent_result"]["matching_voice_count"] == 2
    assert "pipelineID" not in json.dumps(payload["agent_result"])
    assert GET_VOICE_CONTRIBUTIONS_URI not in [call[0] for call in client.calls]


def test_gateway_voice_contributions_rejects_malformed_identity_rows(
    tmp_path: Path,
) -> None:
    voice_id = "{11111111-1111-1111-1111-111111111111}"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2025.1"),
            GET_VOICES_URI: {
                "return": [
                    {
                        "pipelineID": 17,
                        "gameObjectID": 1001,
                        "objectGUID": voice_id,
                        "objectName": "Rain",
                    }
                ]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "profiler-voice-contributions",
            "--capture",
            "latest",
            "--voice-object-id",
            voice_id,
        ],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_STABLE_READ_RESULT"
    assert GET_VOICE_CONTRIBUTIONS_URI not in [call[0] for call in client.calls]


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


def test_invalid_profiler_input_fails_before_connect(tmp_path: Path) -> None:
    factory_called = False

    def factory(url: str) -> FakeClient:
        nonlocal factory_called
        factory_called = True
        raise AssertionError("invalid fixed-read input must not connect")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["profiler-game-objects", "--capture-ms", "-1"],
        env=_gateway_env(tmp_path, "2022.1"),
        client_factory=factory,
    )
    assert exit_code == 2
    assert payload["error_code"] == "INVALID_STABLE_READ_INPUT"
    assert factory_called is False
