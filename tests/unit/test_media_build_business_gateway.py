from __future__ import annotations

from tests.support.gateway_config import set_gateway_config

import importlib.util
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest
from wwise_waapi.media_build_business_contracts import (
    MEDIA_POOL_GET_URI,
    PEAKS_REGION_URI,
    PEAKS_TRIMMED_URI,
    SOUNDBANK_GET_INCLUSIONS_URI,
    media_build_business_operations,
    media_build_business_versions,
)


MEDIA_DB_ID = "{44444444-4444-4444-4444-444444444444}"


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_media_build_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


SOURCE_ID = "{11111111-1111-1111-1111-111111111111}"
INCLUDED_ID = "{22222222-2222-2222-2222-222222222222}"
SOUNDBANK_ID = "{33333333-3333-3333-3333-333333333333}"
PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"


class FakeClient:
    def __init__(self, responses: Mapping[str, Sequence[Any]]) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}
        self.calls: list[tuple[str, Any, Any]] = []

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        self.calls.append((uri, args, options))
        values = self.responses.get(uri)
        if not values:
            raise AssertionError(f"Unexpected WAAPI call: {uri} {args!r} {options!r}")
        return values.popleft()

    def disconnect(self) -> None:
        return None


def _info() -> dict[str, Any]:
    return {
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


def _project(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / "project" / "SampleProject.wproj"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<Project />\n", encoding="utf-8")
    return {"id": PROJECT_ID, "name": "SampleProject", "path": str(path)}


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
    return {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_VERSION": version}


def test_peak_region_request_schema_exposes_only_business_fields(tmp_path: Path) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["request-schema", PEAKS_REGION_URI],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert exit_code == 0, payload
    assert payload["contract"] == "waapi-skill.core-business-route/v1"
    assert payload["business_adapter"]["declaration"]["required_fields"] == [
        "audio_source_id",
        "start_seconds",
        "end_seconds",
        "peak_pair_count",
    ]
    assert payload["continuation"] == {
        "subcommand": "core-call",
        "gateway_argv_prefix": ["core-call", PEAKS_REGION_URI],
        "append_only_disclosed_business_fields": True,
    }
    encoded = json.dumps(payload, sort_keys=True)
    assert "typed-call" not in encoded
    assert "numPeaks" not in encoded
    assert "timeFrom" not in encoded


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation in sorted(media_build_business_operations())
        for version in media_build_business_versions(operation)
    ],
)
def test_every_issue_85_lane_has_one_business_schema_and_no_typed_bypass(
    tmp_path: Path,
    operation: str,
    version: str,
) -> None:
    schema_code, schema = gateway.execute_gateway(
        ["--version", version, "request-schema", operation],
        env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert schema_code == 0, schema
    assert schema["business_adapter"]["operation"] == operation
    assert schema["business_adapter"]["version"] == version
    if operation in {PEAKS_REGION_URI, PEAKS_TRIMMED_URI}:
        assert schema["business_adapter"]["result_projection"]["optional_native_fields"] == "preserve absence; return partial observation when decoding facts are missing"
    bypass_code, bypass = gateway.execute_gateway(
        [ "typed-call", operation, "--schema-digest", "0" * 64],
        env=set_gateway_config(_env(tmp_path, version=version), wwise_version=version),
        client_factory=lambda url: pytest.fail(f"typed bypass connected to {url}"),
    )
    assert bypass_code == 2
    assert "closed Core business" in bypass["message"]


def test_media_pool_cannot_reopen_the_retired_typed_draft(tmp_path: Path) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), "draft-start", MEDIA_POOL_GET_URI],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"typed draft connected to {url}"),
    )

    assert exit_code == 2
    assert "closed Core business" in payload["message"]
    assert not (tmp_path / "state" / "operation-drafts-v1").exists()


@pytest.mark.parametrize("command", ("draft-apply", "draft-check", "preview-from-draft"))
def test_retired_media_pool_draft_cannot_continue_through_an_old_state_record(
    tmp_path: Path,
    command: str,
) -> None:
    state_dir = tmp_path / "state"
    started = gateway.OperationDraftStore(state_dir).start(
        operation=MEDIA_POOL_GET_URI,
        version="2025.1",
        connection_binding={"configuration": gateway.selected_connection_binding(_env(tmp_path))},
        schema_digest=gateway.operation_draft_schema_digest(
            MEDIA_POOL_GET_URI,
            "2025.1",
        ),
        composer_digest=gateway.operation_composer_digest(
            MEDIA_POOL_GET_URI,
            "2025.1",
        ),
    )
    argv = [
        "--state-dir",
        str(state_dir),
        command,
        started.record.draft_id,
        "--task-authority",
        started.task_authority,
        "--expected-revision",
        str(started.record.revision),
    ]
    if command == "draft-apply":
        argv.extend(
            [
                "--facts",
                "--action",
                "add_typed_fact",
                "--fact-action",
                "set",
                "--field-handle",
                "retired",
                "--value-type",
                "string",
                "--fact-value",
                "x",
            ]
        )

    exit_code, payload = gateway.execute_gateway(
        argv,
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"retired Draft connected to {url}"),
    )

    assert exit_code == 2
    assert "retired typed Draft" in payload["message"]


def test_peak_region_core_call_returns_decoded_business_result(tmp_path: Path) -> None:
    import base64
    import struct

    encoded = base64.b64encode(struct.pack("<2h", -32768, 32767)).decode()
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": SOURCE_ID,
                            "name": "Alarm_01",
                            "type": "AudioFileSource",
                            "path": (
                                r"\Actor-Mixer Hierarchy\Default Work Unit"
                                r"\Alarm\Alarm_01"
                            ),
                        }
                    ]
                }
            ],
            PEAKS_REGION_URI: [
                {
                    "numChannels": 1,
                    "peaksArrayLength": 1,
                    "peaksBinaryStrings": [encoded],
                    "peaksDataSize": 4,
                    "maxAbsValue": 32768,
                    "channelConfig": "1.0",
                }
            ],
        }
    )
    env = _env(tmp_path)
    env.update({"WWISE_WAAPI_HOST": "127.0.0.1", "WWISE_WAAPI_PORT": "31337"})

    exit_code, payload = gateway.execute_gateway(
        [
            "core-call",
            PEAKS_REGION_URI,
            "--audio-source-id",
            SOURCE_ID,
            "--start-seconds",
            "0",
            "--end-seconds",
            "1.5",
            "--peak-pair-count",
            "1",
            "--channel-mode",
            "per-channel",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"]["kind"] == "decoded_peaks"
    assert payload["agent_result"]["channels"] == [
        {
            "channel_index": 0,
            "pairs_normalized": [[-1.0, 32767 / 32768]],
        }
    ]
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.core.object.get",
        PEAKS_REGION_URI,
    ]


def test_soundbank_inclusion_core_call_resolves_business_identities(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": SOUNDBANK_ID,
                            "name": "Main",
                            "type": "SoundBank",
                            "path": r"\SoundBanks\Default Work Unit\Main",
                        }
                    ]
                },
                {
                    "return": [
                        {
                            "id": INCLUDED_ID,
                            "name": "Play_Alarm",
                            "type": "Event",
                            "path": r"\Events\Default Work Unit\Play_Alarm",
                        }
                    ]
                },
            ],
            SOUNDBANK_GET_INCLUSIONS_URI: [
                {"inclusions": [{"object": INCLUDED_ID, "filter": ["media", "events"]}]}
            ],
        }
    )
    env = _env(tmp_path)
    env.update({"WWISE_WAAPI_HOST": "127.0.0.1", "WWISE_WAAPI_PORT": "31337"})

    exit_code, payload = gateway.execute_gateway(
        [
            "core-call",
            SOUNDBANK_GET_INCLUSIONS_URI,
            "--soundbank-id",
            SOUNDBANK_ID,
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {
        "contract": "waapi-skill.media-build-result/v1",
        "kind": "soundbank_inclusions",
        "count": 1,
        "inclusions": [
            {
                "object_id": INCLUDED_ID,
                "name": "Play_Alarm",
                "type": "Event",
                "path": r"\Events\Default Work Unit\Play_Alarm",
                "includes": ["events", "media"],
            }
        ],
    }
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.core.object.get",
        SOUNDBANK_GET_INCLUSIONS_URI,
        "ak.wwise.core.object.get",
    ]


def test_media_pool_core_call_binds_live_fields_and_returns_business_rows(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.mediaPool.getFields": [
                {
                    "return": [
                        "Path",
                        "FileId",
                        "Db",
                        "Filename",
                        "WAV/Duration",
                        "IXML/Scene",
                    ]
                }
            ],
            MEDIA_POOL_GET_URI: [
                {
                    "return": [
                        {
                            "Path": "/Audio/Rain_Light.wav",
                            "FileId": "light-id",
                            "Db": {
                                "id": MEDIA_DB_ID,
                                "name": "Project Originals",
                            },
                            "Filename": "Rain_Light.wav",
                            "WAV/Duration": 1.25,
                            "IXML/Scene": "Exterior",
                        },
                        {
                            "Path": "/Audio/rain_wrong_case.wav",
                            "FileId": "wrong-id",
                            "Db": {
                                "id": MEDIA_DB_ID,
                                "name": "Project Originals",
                            },
                            "Filename": "rain_wrong_case.wav",
                            "WAV/Duration": 2.5,
                            "IXML/Scene": "Exterior",
                        },
                        {
                            "Path": "/Audio/Rain_Heavy.wav",
                            "FileId": "heavy-id",
                            "Db": {
                                "id": MEDIA_DB_ID,
                                "name": "Project Originals",
                            },
                            "Filename": "Rain_Heavy.wav",
                            "WAV/Duration": 4.0,
                            "IXML/Scene": "Exterior",
                        },
                    ]
                }
            ],
        }
    )
    env = _env(tmp_path)
    env.update({"WWISE_WAAPI_HOST": "127.0.0.1", "WWISE_WAAPI_PORT": "31337"})

    exit_code, payload = gateway.execute_gateway(
        [
            "core-call",
            MEDIA_POOL_GET_URI,
            "--max-results",
            "10",
            "--database-scope",
            "project-originals",
            "--search-text",
            "rain",
            "--text-filter",
            "scene",
            "equals",
            "Exterior",
            "--include-field",
            "filename",
            "--include-field",
            "duration-seconds",
            "--exact-name-contains",
            "Rain",
            "--final-limit",
            "2",
            "--sort-by",
            "duration-seconds",
            "descending",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {
        "contract": "waapi-skill.media-build-result/v1",
        "kind": "media_pool_rows",
        "field_bindings": [
            {"meaning": "scene", "field": "IXML/Scene"},
            {"meaning": "filename", "field": "Filename", "value_key": "filename"},
            {"meaning": "duration-seconds", "field": "WAV/Duration", "value_key": "duration_seconds"},
        ],
        "complete": True,
        "candidate_count": 3,
        "returned_count": 2,
        "candidate_limit": 10,
        "incomplete_reason": None,
        "items": [
            {
                "path": "/Audio/Rain_Heavy.wav",
                "file_id": "heavy-id",
                "database_id": MEDIA_DB_ID,
                "database_name": "Project Originals",
                "values": {"filename": "Rain_Heavy.wav", "duration_seconds": 4.0},
            },
            {
                "path": "/Audio/Rain_Light.wav",
                "file_id": "light-id",
                "database_id": MEDIA_DB_ID,
                "database_name": "Project Originals",
                "values": {"filename": "Rain_Light.wav", "duration_seconds": 1.25},
            },
        ],
    }
    assert client.calls[-2] == ("ak.wwise.core.mediaPool.getFields", {}, {})
    assert client.calls[-1][0] == MEDIA_POOL_GET_URI
    assert client.calls[-1][1] == {
        "maxResults": 10,
        "databases": [r"\Databases\Project Originals"],
        "searchText": "rain",
        "filters": [
            {
                "type": "field",
                "field": "IXML/Scene",
                "operator": "equals",
                "value": "Exterior",
            },
            {
                "type": "field",
                "field": "Filename",
                "operator": "contains",
                "value": "Rain",
            },
        ],
    }


def test_media_pool_exact_case_filter_fails_closed_at_candidate_ceiling(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.mediaPool.getFields": [
                {"return": ["Path", "FileId", "Db", "Filename"]}
            ],
            MEDIA_POOL_GET_URI: [
                {
                    "return": [
                        {
                            "Path": "/Audio/rain.wav",
                            "FileId": "candidate-id",
                            "Db": {
                                "id": MEDIA_DB_ID,
                                "name": "Project Originals",
                            },
                            "Filename": "rain.wav",
                        }
                    ]
                }
            ],
        }
    )
    env = _env(tmp_path)
    env.update({"WWISE_WAAPI_HOST": "127.0.0.1", "WWISE_WAAPI_PORT": "31337"})

    exit_code, payload = gateway.execute_gateway(
        [
            "core-call",
            MEDIA_POOL_GET_URI,
            "--max-results",
            "1",
            "--exact-name-contains",
            "Rain",
            "--final-limit",
            "1",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["status"] == "incomplete_boundary"
    assert payload["error_code"] == "MEDIA_POOL_POST_FILTER_INCOMPLETE"
    assert payload["agent_result"] is None


def test_media_pool_hostile_number_is_rejected_before_connection(tmp_path: Path) -> None:
    connected = False

    def reject_connection(_url: str) -> None:
        nonlocal connected
        connected = True
        raise AssertionError("invalid Media Pool input reached WAAPI")

    exit_code, payload = gateway.execute_gateway(
        [
            "core-call",
            MEDIA_POOL_GET_URI,
            "--max-results",
            "10",
            "--number-filter",
            "duration-seconds",
            "greaterThan",
            "nan",
        ],
        env=_env(tmp_path),
        client_factory=reject_connection,
    )

    assert exit_code == 2
    assert "finite number" in payload["message"]
    assert connected is False


def test_media_business_fields_cannot_leak_into_an_existing_core_read(
    tmp_path: Path,
) -> None:
    exit_code, payload = gateway.execute_gateway(
        [
            "core-call",
            "ak.wwise.core.object.diff",
            "--source-id",
            SOURCE_ID,
            "--target-id",
            INCLUDED_ID,
            "--soundbank-id",
            SOUNDBANK_ID,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"foreign input connected to {url}"),
    )

    assert exit_code == 2
    assert "does not accept media/build fields" in payload["message"]


def test_peak_read_rejects_a_non_audio_source_before_native_dispatch(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": SOURCE_ID,
                            "name": "Alarm",
                            "type": "Sound",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Alarm",
                        }
                    ]
                }
            ],
        }
    )
    env = _env(tmp_path)
    env.update({"WWISE_WAAPI_HOST": "127.0.0.1", "WWISE_WAAPI_PORT": "31337"})

    exit_code, payload = gateway.execute_gateway(
        [
            "core-call",
            PEAKS_REGION_URI,
            "--audio-source-id",
            SOURCE_ID,
            "--start-seconds",
            "0",
            "--end-seconds",
            "1",
            "--peak-pair-count",
            "8",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "MEDIA_BUILD_IDENTITY_MISMATCH"
    assert all(call[0] != PEAKS_REGION_URI for call in client.calls)


def test_media_pool_live_field_miss_stops_before_the_pool_query(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.mediaPool.getFields": [
                {"return": ["Path", "FileId", "Db"]}
            ],
        }
    )
    env = _env(tmp_path)
    env.update({"WWISE_WAAPI_HOST": "127.0.0.1", "WWISE_WAAPI_PORT": "31337"})

    exit_code, payload = gateway.execute_gateway(
        [
            "core-call",
            MEDIA_POOL_GET_URI,
            "--max-results",
            "10",
            "--include-field",
            "filename",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "MEDIA_BUILD_FIELD_AMBIGUOUS"
    assert payload["details"]["field_choices"] == []
    assert [call[0] for call in client.calls][-1] == (
        "ak.wwise.core.mediaPool.getFields"
    )
    assert all(call[0] != MEDIA_POOL_GET_URI for call in client.calls)


def test_operations_catalog_lists_all_media_business_routes(tmp_path: Path) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["operations", "--detail"],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline catalog connected to {url}"),
    )

    assert exit_code == 0, payload
    rows = {
        row["api"]: row
        for row in payload["request_schema_routes"]
        if row["api"] in media_build_business_operations()
    }
    assert set(rows) == media_build_business_operations()
    assert payload["request_schema_command_template"] == [
        "request-schema",
        "<api>",
    ]
    assert all(row["next_command"] for row in rows.values())


def test_media_pool_projection_distinguishes_unavailable_fields_from_explicit_null(tmp_path: Path) -> None:
    client = FakeClient({
        "ak.wwise.core.getInfo": [_info()],
        "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Path", "FileId", "Db", "WAV/Duration", "IXML/Scene"]}],
        MEDIA_POOL_GET_URI: [{"return": [
            {"Path": "/Audio/NoScene.wav", "FileId": "one", "WAV/Duration": 1.0},
            {"Path": "/Audio/NullScene.wav", "FileId": "two", "IXML/Scene": None, "WAV/Duration": 2.0},
        ]}],
    })
    code, payload = gateway.execute_gateway([
        "core-call", MEDIA_POOL_GET_URI, "--max-results", "10", "--include-field", "scene",
        "--include-field", "duration-seconds"], env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, payload
    items = payload["agent_result"]["items"]
    assert items[0]["values"] == {"duration_seconds": 1.0}
    assert items[0]["unavailable_values"] == ["scene"]
    assert items[1]["values"] == {"scene": None, "duration_seconds": 2.0}
    assert "unavailable_values" not in items[1]
    assert client.calls[-1] == (MEDIA_POOL_GET_URI, {"maxResults": 10}, {"return": ["Path", "FileId", "Db", "IXML/Scene", "WAV/Duration"]})


def test_media_pool_empty_search_and_empty_text_filter_are_preserved(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": [_info()], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
                         "ak.wwise.core.mediaPool.getFields": [{"return": ["Path", "FileId", "Db", "Filename"]}],
                         MEDIA_POOL_GET_URI: [{"return": []}]})
    code, payload = gateway.execute_gateway(["core-call", MEDIA_POOL_GET_URI, "--max-results", "5", "--search-text", "", "--text-filter", "filename", "equals", ""], env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, payload
    assert payload["agent_result"]["items"] == []
    assert client.calls[-1] == (MEDIA_POOL_GET_URI, {"maxResults": 5, "searchText": "", "filters": [{"type": "field", "field": "Filename", "operator": "equals", "value": ""}]}, {"return": ["Path", "FileId", "Db", "Filename"]})


@pytest.mark.parametrize("weight", [-0.25, 1.25])
def test_media_pool_finite_weights_reach_native_without_clamping(tmp_path: Path, weight: float) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": [_info()], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
                         "ak.wwise.core.mediaPool.getFields": [{"return": ["Path", "FileId", "Db"]}],
                         MEDIA_POOL_GET_URI: [{"return": []}]})
    code, payload = gateway.execute_gateway(["core-call", MEDIA_POOL_GET_URI, "--max-results", "5", "--weighted-audio-description", "rain", str(weight)], env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, payload
    assert client.calls[-1][1] == {"maxResults": 5, "filters": [{"type": "audioDescription", "value": "rain", "weight": weight}]}


def _pool_rows(count: int) -> list[dict[str, str]]:
    return [{"Path": f"/owned/source-{index}.wav", "FileId": str(index)} for index in range(count)]


def test_media_pool_prefix_continuations_keep_useful_rows_and_verify_prior_prefix(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": [_info()] * 3,
        "ak.wwise.core.getProjectInfo": [_project(tmp_path)] * 3,
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename"]}] * 3,
        MEDIA_POOL_GET_URI: [{"return": _pool_rows(2)}, {"return": _pool_rows(4)}, {"return": _pool_rows(5)}]})
    env = _env(tmp_path)
    code, first = gateway.execute_gateway(["core-call", MEDIA_POOL_GET_URI, "--max-results", "2", "--search-text", ""], env=env, client_factory=lambda _: client)
    assert code == 0, first
    assert first["status"] == "partial"
    page = first["agent_result"]
    assert page["complete"] is False and page["incomplete_reason"] == "candidate_limit_reached"
    assert [item["file_id"] for item in page["items"]] == ["0", "1"]
    command = page["next_command"]
    assert command["copy_instruction"]["action"] == "execute_verbatim_as_one_shell_tool_call"
    code, second = gateway.execute_gateway(command["gateway_argv"], env=env, client_factory=lambda _: client)
    assert code == 0, second
    assert [item["file_id"] for item in second["agent_result"]["items"]] == ["2", "3"]
    assert second["agent_result"]["page"]["mode"] == "larger_bounded_prefix_reread"
    assert second["agent_result"]["page"]["native_offset_supported"] is False
    code, last = gateway.execute_gateway(second["agent_result"]["next_command"]["gateway_argv"], env=env, client_factory=lambda _: client)
    assert code == 0, last
    assert [item["file_id"] for item in last["agent_result"]["items"]] == ["4"]
    assert last["agent_result"]["complete"] is True
    assert "next_command" not in last["agent_result"]
    assert [args["maxResults"] for uri, args, _ in client.calls if uri == MEDIA_POOL_GET_URI] == [2, 4, 6]


@pytest.mark.parametrize("change", ["prefix", "query", "session", "configuration", "project"])
def test_media_pool_prefix_continuation_rejects_changed_binding_or_rows(tmp_path: Path, change: str) -> None:
    changed_info = _info()
    if change == "session":
        changed_info["sessionId"] = "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"
    second_rows = _pool_rows(4)
    if change == "prefix":
        second_rows[0], second_rows[1] = second_rows[1], second_rows[0]
    second_project = _project(tmp_path / "other") if change == "project" else _project(tmp_path)
    client = FakeClient({"ak.wwise.core.getInfo": [_info(), changed_info],
        "ak.wwise.core.getProjectInfo": [_project(tmp_path), second_project],
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename"]}] * 2,
        MEDIA_POOL_GET_URI: [{"return": _pool_rows(2)}, {"return": second_rows}]})
    env = _env(tmp_path)
    code, first = gateway.execute_gateway(["core-call", MEDIA_POOL_GET_URI, "--max-results", "2"], env=env, client_factory=lambda _: client)
    assert code == 0, first
    command = first["agent_result"]["next_command"]["gateway_argv"]
    if change == "query":
        command += ["--search-text", "changed"]
    if change == "configuration":
        set_gateway_config(env, waapi_port=31338)
    code, stopped = gateway.execute_gateway(command, env=env, client_factory=lambda _: client)
    assert code == 2, stopped
    assert stopped["error_code"] == "MEDIA_POOL_CONTINUATION_CHANGED"
    reads = [call for call in client.calls if call[0] == MEDIA_POOL_GET_URI]
    assert len(reads) == (2 if change == "prefix" else 1)
    if change == "prefix":
        assert stopped["details"]["call"]["ok"] is True
        assert stopped["details"]["native_observation"] == {"return": second_rows}


def test_media_pool_ultimate_prefix_boundary_never_claims_collection_complete(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": [_info()],
        "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename"]}],
        MEDIA_POOL_GET_URI: [{"return": _pool_rows(200)}]})
    code, result = gateway.execute_gateway(["core-call", MEDIA_POOL_GET_URI, "--max-results", "200"], env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, result
    page = result["agent_result"]
    assert len(page["items"]) == 200
    assert page["complete"] is False
    assert page["page"]["resource_boundary_reached"] is True
    assert "next_command" not in page


@pytest.mark.parametrize("change", ["expired", "tampered", "foreign-route"])
def test_media_pool_continuation_preflight_stops_invalid_reuse(tmp_path: Path, change: str, monkeypatch) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": [_info()], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename"]}], MEDIA_POOL_GET_URI: [{"return": _pool_rows(2)}]})
    env = _env(tmp_path)
    code, result = gateway.execute_gateway(["core-call", MEDIA_POOL_GET_URI, "--max-results", "2"], env=env, client_factory=lambda _: client)
    assert code == 0, result
    command = result["agent_result"]["next_command"]["gateway_argv"]
    if change == "expired":
        import time
        later = time.time() + 901
        monkeypatch.setattr(time, "time", lambda: later)
    elif change == "tampered":
        command[-1] += "invalid"
    else:
        command[1] = PEAKS_REGION_URI
    code, rejected = gateway.execute_gateway(command, env=env, client_factory=lambda _: pytest.fail("invalid continuation connected"))
    assert code == 2, rejected
    assert rejected["error_code"] == "GatewayInputError"


def test_media_pool_does_not_issue_unbound_session_continuation(tmp_path: Path) -> None:
    info = _info()
    info.pop("sessionId")
    client = FakeClient({"ak.wwise.core.getInfo": [info], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename"]}], MEDIA_POOL_GET_URI: [{"return": _pool_rows(2)}]})
    code, result = gateway.execute_gateway(["core-call", MEDIA_POOL_GET_URI, "--max-results", "2"], env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, result
    assert len(result["agent_result"]["items"]) == 2
    assert result["agent_result"]["page"]["continuation_unavailable_reason"] == "host_session_identity_unavailable"
    assert "next_command" not in result["agent_result"]


def test_media_pool_complete_post_filter_replaces_prior_prefix_presentation(tmp_path: Path) -> None:
    rows = [{**row, "Filename": f"Rain-{index}.wav", "WAV/Duration": index + 1} for index, row in enumerate(_pool_rows(3))]
    client = FakeClient({"ak.wwise.core.getInfo": [_info()] * 2, "ak.wwise.core.getProjectInfo": [_project(tmp_path)] * 2,
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename", "WAV/Duration"]}] * 2,
        MEDIA_POOL_GET_URI: [{"return": rows[:2]}, {"return": rows}]})
    env = _env(tmp_path)
    code, first = gateway.execute_gateway(["core-call", MEDIA_POOL_GET_URI, "--max-results", "2", "--exact-name-contains", "Rain",
        "--sort-by", "duration-seconds", "descending", "--final-limit", "1"], env=env, client_factory=lambda _: client)
    assert code == 2 and first["error_code"] == "MEDIA_POOL_POST_FILTER_INCOMPLETE", first
    assert first["native_observation"] == {"return": rows[:2]}
    code, final = gateway.execute_gateway(first["next_command"]["gateway_argv"], env=env, client_factory=lambda _: client)
    assert code == 0, final
    assert final["agent_result"]["complete"] is True
    assert [item["file_id"] for item in final["agent_result"]["items"]] == ["2"]
    assert final["agent_result"]["page"]["presentation"] == "replace_previous_prefix"


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("operation", [PEAKS_REGION_URI, PEAKS_TRIMMED_URI])
def test_peak_read_preserves_optional_missing_native_fields_without_inventing_decoded_data(tmp_path: Path, version: str, operation: str) -> None:
    info = _info()
    info["version"].update(year=int(version[:4]), displayName=f"v{version}.0.1")
    raw = {"numChannels": 1}
    project = _project(tmp_path)
    identity_reads = [{"return": [{"id": SOURCE_ID, "name": "Source", "type": "AudioFileSource", "path": "\\Source"}]}]
    if version == "2021.1":
        identity_reads.insert(0, {"return": [{**project, "type": "Project", "filePath": project["path"], "path": "\\"}]})
    client = FakeClient({"ak.wwise.core.getInfo": [info], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.object.get": identity_reads,
        operation: [raw]})
    command = ["core-call", operation, "--audio-source-id", SOURCE_ID, "--peak-pair-count", "1"]
    if operation == PEAKS_REGION_URI:
        command += ["--start-seconds", "0", "--end-seconds", "1"]
    code, payload = gateway.execute_gateway(command, env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 0, (payload, client.calls)
    assert payload["status"] == "partial"
    observation = payload["agent_result"]
    assert observation["projection_complete"] is False
    assert observation["decode_available"] is False
    assert observation["native_result"] == raw
    assert observation["unavailable_fields"] == ["peaksArrayLength", "peaksBinaryStrings", "peaksDataSize", "maxAbsValue"]
    assert "channels" not in observation and "peak_pair_count" not in observation
    assert payload["call"]["ok"] is True


@pytest.mark.parametrize("operation", [PEAKS_REGION_URI, PEAKS_TRIMMED_URI])
@pytest.mark.parametrize("raw", [{"numChannels": None}, {"peaksArrayLength": 0.5}, {"peaksBinaryStrings": [None]},
    {"numChannels": 1, "peaksArrayLength": 0, "peaksBinaryStrings": [""], "peaksDataSize": 0, "maxAbsValue": 1, "channelConfig": None}])
def test_peak_read_rejects_malformed_present_fields_and_keeps_native_call_evidence(tmp_path: Path, operation: str, raw: dict) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": [_info()], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.object.get": [{"return": [{"id": SOURCE_ID, "name": "Source", "type": "AudioFileSource", "path": "\\Source"}]}], operation: [raw]})
    command = ["core-call", operation, "--audio-source-id", SOURCE_ID, "--peak-pair-count", "1"]
    if operation == PEAKS_REGION_URI:
        command += ["--start-seconds", "0", "--end-seconds", "1"]
    code, payload = gateway.execute_gateway(command, env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2, payload
    assert payload["error_code"] == "MEDIA_BUILD_RESULT_INVALID"
    assert payload["details"]["call"]["ok"] is True
    assert payload["details"]["native_observation"] == raw


@pytest.mark.parametrize("operation", [PEAKS_REGION_URI, PEAKS_TRIMMED_URI])
def test_peak_read_preserves_zero_divisor_without_fabricating_normalized_samples(tmp_path: Path, operation: str) -> None:
    raw = {"numChannels": 1, "peaksArrayLength": 0, "peaksBinaryStrings": [""], "peaksDataSize": 0, "maxAbsValue": 0}
    client = FakeClient({"ak.wwise.core.getInfo": [_info()], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.object.get": [{"return": [{"id": SOURCE_ID, "name": "Source", "type": "AudioFileSource", "path": "\\Source"}]}], operation: [raw]})
    command = ["core-call", operation, "--audio-source-id", SOURCE_ID, "--peak-pair-count", "1"]
    if operation == PEAKS_REGION_URI:
        command += ["--start-seconds", "0", "--end-seconds", "1"]
    code, payload = gateway.execute_gateway(command, env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, payload
    assert payload["status"] == "partial"
    assert payload["agent_result"]["decode_unavailable_reason"] == "zero_normalization_divisor"
    assert payload["agent_result"]["native_result"] == raw
    assert "channels" not in payload["agent_result"]


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("operation", [PEAKS_REGION_URI, PEAKS_TRIMMED_URI])
def test_peak_read_can_preserve_native_channel_default_without_assuming_channel_count(tmp_path: Path, version: str, operation: str) -> None:
    info = _info()
    info["version"].update(year=int(version[:4]), displayName=f"v{version}.0.1")
    project = _project(tmp_path)
    identities = [{"return": [{"id": SOURCE_ID, "name": "Source", "type": "AudioFileSource", "path": "\\Source"}]}]
    if version == "2021.1":
        identities.insert(0, {"return": [{**project, "type": "Project", "filePath": project["path"], "path": "\\"}]})
    raw = {"numChannels": 2, "peaksArrayLength": 1, "peaksBinaryStrings": ["AAAAAA==", "AAAAAA=="], "peaksDataSize": 4, "maxAbsValue": 32768}
    client = FakeClient({"ak.wwise.core.getInfo": [info], "ak.wwise.core.getProjectInfo": [project],
        "ak.wwise.core.object.get": identities, operation: [raw]})
    command = ["core-call", operation, "--audio-source-id", SOURCE_ID, "--peak-pair-count", "1", "--channel-mode", "native-default"]
    if operation == PEAKS_REGION_URI:
        command += ["--start-seconds", "0", "--end-seconds", "1"]
    code, payload = gateway.execute_gateway(command, env=_env(tmp_path, version=version), client_factory=lambda _: client)
    assert code == 0, payload
    assert payload["agent_result"]["channel_count"] == 2
    assert payload["agent_result"]["channel_mode"] == "native-default"
    assert "getCrossChannelPeaks" not in client.calls[-1][1]
    assert [channel["pairs_normalized"] for channel in payload["agent_result"]["channels"]] == [[[0.0, 0.0]], [[0.0, 0.0]]]
    schema_code, schema = gateway.execute_gateway(["--version", version, "request-schema", operation], env=_env(tmp_path), client_factory=lambda _: pytest.fail("offline schema connected"))
    assert schema_code == 0, schema
    assert "native-default" in schema["business_adapter"]["declaration"]["field_choices"]["channel_mode"]


@pytest.mark.parametrize("post_filtered", [False, True])
def test_media_pool_long_windows_continuation_roundtrips_through_short_durable_plan(tmp_path: Path, monkeypatch, post_filtered: bool) -> None:
    class WindowsEnvelopeOS:
        name = "nt"

        def __getattr__(self, name):
            import os
            return getattr(os, name)

    monkeypatch.setattr(gateway, "os", WindowsEnvelopeOS())
    rows = [{**row, "Filename": "Rain.wav"} for row in _pool_rows(3)]
    client = FakeClient({"ak.wwise.core.getInfo": [_info()] * 2, "ak.wwise.core.getProjectInfo": [_project(tmp_path)] * 2,
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename"]}] * 2, MEDIA_POOL_GET_URI: [{"return": rows[:2]}, {"return": rows}]})
    command = ["core-call", MEDIA_POOL_GET_URI, "--max-results", "2"]
    for _ in range(15 if post_filtered else 16):
        command += ["--audio-description", "雨" * 4096]
    if post_filtered:
        command += ["--text-filter", "filename", "contains", "Rain", "--exact-name-contains", "Rain", "--final-limit", "1"]
    env = {**_env(tmp_path), "WAAPI_SKILL_STATE_DIR": str(tmp_path / "external-state")}
    code, payload = gateway.execute_gateway(command, env=env, client_factory=lambda _: client)
    if post_filtered:
        assert code == 2 and payload["error_code"] == "MEDIA_POOL_POST_FILTER_INCOMPLETE", payload
        assert payload["native_observation"] == {"return": rows[:2]}
        continuation = payload["next_command"]
    else:
        assert code == 0, payload
        assert len(payload["agent_result"]["items"]) == 2
        assert payload["agent_result"]["complete"] is False
        continuation = payload["agent_result"]["next_command"]
    assert "--media-query" in continuation["gateway_argv"]
    from wwise_waapi.platform_commands import decode_windows_powershell_argv
    decoded = decode_windows_powershell_argv(continuation["shell_command"])
    assert list(decoded) == continuation["full_argv"]
    assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) < 64 * 1024
    assert len(client.calls[-1][1]["filters"]) == 16
    code, final = gateway.execute_gateway(continuation["gateway_argv"], env=env, client_factory=lambda _: client)
    assert code == 0, final
    assert final["agent_result"]["complete"] is True
    assert [item["file_id"] for item in final["agent_result"]["items"]] == (["0"] if post_filtered else ["2"])
    searches = [call for call in client.calls if call[0] == MEDIA_POOL_GET_URI]
    assert searches[0][1]["filters"] == searches[1][1]["filters"]
    assert [call[1]["maxResults"] for call in searches] == [2, 4]
    stale_code, stale = gateway.execute_gateway(continuation["gateway_argv"], env=env, client_factory=lambda _: pytest.fail("completed query state connected"))
    assert stale_code == 2 and stale["error_code"] == "GatewayInputError", stale


def test_media_pool_preserves_missing_identity_fields_as_observed_absence(tmp_path: Path) -> None:
    raw = {"return": [{"FileId": "known", "Filename": "Known.wav"}, {"Path": "/Audio/PathOnly.wav"}]}
    client = FakeClient({"ak.wwise.core.getInfo": [_info()], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename"]}], MEDIA_POOL_GET_URI: [raw]})
    code, payload = gateway.execute_gateway(["core-call", MEDIA_POOL_GET_URI, "--max-results", "5", "--include-field", "filename"],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, payload
    assert payload["status"] == "partial"
    result = payload["agent_result"]
    assert result["complete"] is True  # The bounded collection ended; row identities remain incomplete.
    assert result["projection_complete"] is False
    assert result["items"][0] == {"file_id": "known", "values": {"filename": "Known.wav"}, "unavailable_fields": ["path"]}
    assert result["items"][1] == {"path": "/Audio/PathOnly.wav", "values": {}, "unavailable_fields": ["file_id"], "unavailable_values": ["filename"]}


@pytest.mark.parametrize("change", ["missing", "tampered", "invalid-plan", "symlink", "configuration", "session", "expired", "edited-declaration"])
def test_media_pool_durable_plan_rejects_changed_or_invalid_continuations(tmp_path: Path, change: str, monkeypatch) -> None:
    info = _info()
    info["sessionId"] = "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"
    client = FakeClient({"ak.wwise.core.getInfo": [_info(), info], "ak.wwise.core.getProjectInfo": [_project(tmp_path)] * 2,
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename"]}] * 2, MEDIA_POOL_GET_URI: [{"return": _pool_rows(2)}]})
    env = {**_env(tmp_path), "WAAPI_SKILL_STATE_DIR": str(tmp_path / "external-state")}
    command = ["core-call", MEDIA_POOL_GET_URI, "--max-results", "2"]
    for _ in range(16):
        command += ["--audio-description", "rain" * 1024]
    code, first = gateway.execute_gateway(command, env=env, client_factory=lambda _: client)
    assert code == 0, first
    continuation = first["agent_result"]["next_command"]["gateway_argv"]
    assert "--media-query" in continuation
    record = next((tmp_path / "external-state").rglob("mpq1-*.json"))
    if change == "missing":
        record.unlink()
    elif change == "symlink":
        from tests.support.platform_filesystem import create_symlink_or_skip
        saved = tmp_path / "saved-plan.json"
        record.rename(saved)
        create_symlink_or_skip(record, saved)
    elif change in {"tampered", "invalid-plan"}:
        document = json.loads(record.read_text(encoding="utf-8"))
        document["plan"]["native_args"] = {}
        if change == "invalid-plan":
            from wwise_waapi.canonical import canonical_sha256
            document["sha256"] = canonical_sha256({key: value for key, value in document.items() if key != "sha256"})
        record.write_text(json.dumps(document), encoding="utf-8")
    elif change == "configuration":
        set_gateway_config(env, waapi_port=31338)
    elif change == "expired":
        import time
        later = time.time() + 901
        monkeypatch.setattr(time, "time", lambda: later)
    elif change == "edited-declaration":
        continuation += ["--search-text", "changed"]
    code, rejected = gateway.execute_gateway(continuation, env=env,
        client_factory=lambda _: client if change == "session" else pytest.fail("invalid durable continuation connected"))
    assert code == 2, rejected
    assert rejected["error_code"] == ("MEDIA_POOL_CONTINUATION_CHANGED" if change == "session" else "GatewayInputError")
    assert len([call for call in client.calls if call[0] == MEDIA_POOL_GET_URI]) == 1


def test_media_pool_durable_plan_capacity_reclaims_only_expired_query_records(tmp_path: Path, monkeypatch) -> None:
    env = {**_env(tmp_path), "WAAPI_SKILL_STATE_DIR": str(tmp_path / "external-state")}
    client = FakeClient({"ak.wwise.core.getInfo": [_info()] * 130, "ak.wwise.core.getProjectInfo": [_project(tmp_path)] * 130,
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename"]}] * 130, MEDIA_POOL_GET_URI: [{"return": _pool_rows(2)}] * 130})
    command = ["core-call", MEDIA_POOL_GET_URI, "--max-results", "2"]
    for _ in range(16):
        command += ["--audio-description", "rain" * 1024]
    for _ in range(128):
        code, page = gateway.execute_gateway(command, env=env, client_factory=lambda _: client)
        assert code == 0 and "next_command" in page["agent_result"], page
    code, full = gateway.execute_gateway(command, env=env, client_factory=lambda _: client)
    assert code == 0, full
    assert "next_command" not in full["agent_result"]
    assert "bounded capacity" in full["agent_result"]["page"]["query_state_unavailable"]
    import time
    later = time.time() + 901
    monkeypatch.setattr(time, "time", lambda: later)
    code, fresh = gateway.execute_gateway(command, env=env, client_factory=lambda _: client)
    assert code == 0 and "next_command" in fresh["agent_result"], fresh
    assert len(list((tmp_path / "external-state").rglob("mpq1-*.json"))) == 1


def test_media_pool_fields_has_one_bounded_metadata_continuation_and_pages_live_names(tmp_path: Path) -> None:
    api = "ak.wwise.core.mediaPool.getFields"
    code, schema = gateway.execute_gateway(["request-schema", api], env=_env(tmp_path), client_factory=lambda _: pytest.fail("offline schema connected"))
    assert code == 0, schema
    assert schema["input_shape"] == "fixed_business_command"
    assert schema["continuation"] == {"subcommand": "metadata", "arguments": ["media-pool-fields"], "business_values_required": False}
    contract = schema["business_contract"]
    assert contract["input_forms"]["meaning"]["flag"] == "--meaning"
    assert contract["input_forms"]["page_size"]["maximum"] == 64
    assert contract["field_types"] == "native getFields reports names only; field value types remain unknown"
    fields = ["Filename", "WAV/Duration", "IXML/Scene", "IXML/Take"]
    client = FakeClient({"ak.wwise.core.getInfo": [_info()] * 2, api: [{"return": fields}] * 2})
    command = ["metadata", "media-pool-fields", "--meaning", "IXML", "--page-size", "1"]
    code, first = gateway.execute_gateway(command, env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, first
    assert [field["name"] for field in first["agent_result"]["fields"]] == ["IXML/Scene"]
    assert first["agent_result"]["complete"] is False
    code, final = gateway.execute_gateway(first["agent_result"]["next_command"]["gateway_argv"], env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, final
    assert [field["name"] for field in final["agent_result"]["fields"]] == ["IXML/Take"]
    assert final["agent_result"]["complete"] is True
    assert final["agent_result"]["available_count"] == 4
    assert final["agent_result"]["total_count"] == 2
    assert [call for call in client.calls if call[0] == api] == [(api, {}, {}), (api, {}, {})]


@pytest.mark.parametrize("raw", [{}, {"return": []}, {"return": [None]}])
def test_media_pool_fields_distinguishes_absent_empty_and_malformed_native_lists(tmp_path: Path, raw: dict) -> None:
    api = "ak.wwise.core.mediaPool.getFields"
    client = FakeClient({"ak.wwise.core.getInfo": [_info()], api: [raw]})
    code, payload = gateway.execute_gateway(["metadata", "media-pool-fields"], env=_env(tmp_path), client_factory=lambda _: client)
    if "return" not in raw:
        assert code == 0 and payload["status"] == "partial", payload
        assert payload["agent_result"]["native_result"] == {}
        assert payload["agent_result"]["unavailable_fields"] == ["return"]
        assert "fields" not in payload["agent_result"] and "total_count" not in payload["agent_result"]
    elif raw["return"] == []:
        assert code == 0 and payload["agent_result"]["fields"] == [], payload
        assert payload["agent_result"]["total_count"] == 0 and payload["agent_result"]["complete"] is True
    else:
        assert code == 2 and payload["error_code"] == "MEDIA_POOL_FIELDS_INVALID", payload
        assert payload["details"]["call"]["ok"] is True
        assert payload["details"]["native_observation"] == raw


def test_media_pool_field_large_name_has_lossless_bounded_typed_detail_pages(tmp_path: Path) -> None:
    api = "ak.wwise.core.mediaPool.getFields"
    name = "IXML/" + "雨" * 24000
    client = FakeClient({"ak.wwise.core.getInfo": [_info()] * 30, api: [{"return": [name]}] * 30})
    env = _env(tmp_path)
    code, listed = gateway.execute_gateway(["metadata", "media-pool-fields"], env=env, client_factory=lambda _: client)
    assert code == 0, listed
    field = listed["agent_result"]["fields"][0]
    assert field["name_complete"] is False
    assert len(field["name_preview"].encode("utf-8")) <= 1024
    command = field["next_command"]["gateway_argv"]
    recovered = ""
    for _ in range(30):
        code, detail = gateway.execute_gateway(command, env=env, client_factory=lambda _: client)
        assert code == 0, detail
        assert len(json.dumps(detail, ensure_ascii=False).encode("utf-8")) < 32 * 1024
        page = detail["agent_result"]
        assert page["name_fragment"]["character_offset"] == len(recovered)
        recovered += page["name_fragment"]["value"]
        if page["complete"]:
            break
        command = page["next_command"]["gateway_argv"]
    assert recovered == name


def test_media_pool_field_pages_budget_actual_windows_detail_continuations(tmp_path: Path, monkeypatch) -> None:
    class WindowsEnvelopeOS:
        name = "nt"

        def __getattr__(self, name):
            import os
            return getattr(os, name)

    monkeypatch.setattr(gateway, "os", WindowsEnvelopeOS())
    api = "ak.wwise.core.mediaPool.getFields"
    fields = [f"IXML/{index}/" + "雨" * 3200 for index in range(20)]
    client = FakeClient({"ak.wwise.core.getInfo": [_info()] * 30, api: [{"return": fields}] * 30})
    env = _env(tmp_path)
    command = ["metadata", "media-pool-fields"]
    observed = []
    for _ in range(30):
        code, payload = gateway.execute_gateway(command, env=env, client_factory=lambda _: client)
        assert code == 0, payload
        assert len(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")) <= 32 * 1024
        result = payload["agent_result"]
        observed.extend(row["selection"] for row in result["fields"])
        if result["complete"]:
            break
        command = result["next_command"]["gateway_argv"]
    assert len(set(observed)) == len(fields)


@pytest.mark.parametrize("change", ["session", "fields", "order", "meaning", "configuration", "expired"])
def test_media_pool_field_pages_reject_inventory_filter_or_live_context_drift(tmp_path: Path, change: str, monkeypatch) -> None:
    api = "ak.wwise.core.mediaPool.getFields"
    info = _info()
    if change == "session":
        info["sessionId"] = "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"
    fields = ["IXML/Scene", "IXML/Take"]
    later_fields = fields[::-1] if change == "order" else [*fields, "IXML/Other"] if change == "fields" else fields
    client = FakeClient({"ak.wwise.core.getInfo": [_info(), info], api: [{"return": fields}, {"return": later_fields}]})
    env = _env(tmp_path)
    code, first = gateway.execute_gateway(["metadata", "media-pool-fields", "--meaning", "IXML", "--page-size", "1"], env=env, client_factory=lambda _: client)
    assert code == 0, first
    command = first["agent_result"]["next_command"]["gateway_argv"]
    if change == "configuration":
        set_gateway_config(env, waapi_port=31338)
    elif change == "meaning":
        command += ["--meaning", "WAV"]
    elif change == "expired":
        import time
        later = time.time() + 901
        monkeypatch.setattr(time, "time", lambda: later)
    code, stopped = gateway.execute_gateway(command, env=env, client_factory=lambda _: client)
    assert code == 2, stopped
    assert stopped["error_code"] == ("METADATA_SELECTION_EXPIRED" if change == "expired" else "METADATA_SELECTION_SCOPE_CHANGED")
    assert stopped["details"]["call"]["ok"] is True
    assert stopped["details"]["native_observation"] == {"return": later_fields}


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1"])
def test_media_pool_field_browse_rejects_other_version_contracts_before_connection(tmp_path: Path, version: str) -> None:
    code, payload = gateway.execute_gateway(["metadata", "media-pool-fields"], env=_env(tmp_path, version=version),
        client_factory=lambda _: pytest.fail("unpackaged field discovery version connected"))
    assert code == 2 and payload["error_code"] == "GatewayInputError", payload
    assert "2025.1 contract" in payload["message"]


def test_media_pool_can_query_an_exact_field_from_a_repeated_native_inventory(tmp_path: Path) -> None:
    client = FakeClient({
        "ak.wwise.core.getInfo": [_info()], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename", "Filename"]}],
        MEDIA_POOL_GET_URI: [{"return": [{"Path": "/Audio/Rain.wav", "FileId": "rain", "Filename": "Rain.wav"}]}],
    })
    code, payload = gateway.execute_gateway(
        ["core-call", MEDIA_POOL_GET_URI, "--max-results", "2", "--include-field", "filename"],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, payload
    assert client.calls[-1] == (MEDIA_POOL_GET_URI, {"maxResults": 2}, {"return": ["Path", "FileId", "Db", "Filename"]})
    assert payload["agent_result"]["items"][0]["values"] == {"filename": "Rain.wav"}


@pytest.mark.parametrize("selected,other", [("scene", "IXML/Scene"), ("IXML/SCENE", "IXML/Scene")])
def test_media_pool_exact_discovered_field_wins_over_aliases_and_casefold_matches(
    tmp_path: Path, selected: str, other: str,
) -> None:
    client = FakeClient({
        "ak.wwise.core.getInfo": [_info()], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.mediaPool.getFields": [{"return": [other, selected]}],
        MEDIA_POOL_GET_URI: [{"return": [{"Path": "/Audio/Rain.wav", "FileId": "rain", selected: "Exterior"}]}],
    })
    code, payload = gateway.execute_gateway(
        ["core-call", MEDIA_POOL_GET_URI, "--max-results", "2", "--text-filter", selected, "equals", "Exterior",
         "--include-field", selected], env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, payload
    assert client.calls[-1] == (MEDIA_POOL_GET_URI,
        {"maxResults": 2, "filters": [{"type": "field", "field": selected, "operator": "equals", "value": "Exterior"}]},
        {"return": ["Path", "FileId", "Db", selected]})
    assert list(payload["agent_result"]["items"][0]["values"].values()) == ["Exterior"]


def test_media_pool_projects_unicode_and_colliding_exact_field_names_without_losing_values(tmp_path: Path) -> None:
    names = ["场景", "A/B", "A B", "标签?!"]
    client = FakeClient({
        "ak.wwise.core.getInfo": [_info()], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.mediaPool.getFields": [{"return": names}],
        MEDIA_POOL_GET_URI: [{"return": [{"Path": "/Audio/Rain.wav", "FileId": "rain",
                                          "场景": "外景", "A/B": "slash", "A B": "space", "标签?!": "雨"}]}],
    })
    code, payload = gateway.execute_gateway(
        ["core-call", MEDIA_POOL_GET_URI, "--max-results", "2", "--include-field", "场景",
         "--include-field", "A/B", "--include-field", "A B", "--include-field", "标签?!"],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 0, payload
    assert client.calls[-1][2] == {"return": ["Path", "FileId", "Db", "场景", "A/B", "A B", "标签?!"]}
    assert payload["agent_result"]["items"][0]["values"] == {"场景": "外景", "A/B": "slash", "A B": "space", "标签": "雨"}
    assert payload["agent_result"]["field_bindings"] == [
        {"meaning": "场景", "field": "场景", "value_key": "场景"},
        {"meaning": "A/B", "field": "A/B", "value_key": "A/B"},
        {"meaning": "A B", "field": "A B", "value_key": "A B"},
        {"meaning": "标签?!", "field": "标签?!", "value_key": "标签"},
    ]


def test_media_pool_nonexact_ambiguous_field_discloses_exact_choices_without_query_dispatch(tmp_path: Path) -> None:
    client = FakeClient({
        "ak.wwise.core.getInfo": [_info()], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.mediaPool.getFields": [{"return": ["IXML/Scene", "IXML/SCENE", "Filename"]}],
    })
    code, payload = gateway.execute_gateway(
        ["core-call", MEDIA_POOL_GET_URI, "--max-results", "2", "--include-field", "ixml/scene"],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2, payload
    assert payload["details"] is not None, json.dumps(payload,ensure_ascii=False)
    assert payload["details"]["field_choices"] == ["IXML/Scene", "IXML/SCENE"]
    assert MEDIA_POOL_GET_URI not in [call[0] for call in client.calls]


def test_media_pool_continuation_rejects_a_changed_exact_field_binding_before_query(tmp_path: Path) -> None:
    client = FakeClient({
        "ak.wwise.core.getInfo": [_info()] * 2, "ak.wwise.core.getProjectInfo": [_project(tmp_path)] * 2,
        "ak.wwise.core.mediaPool.getFields": [{"return": ["IXML/Scene"]}, {"return": ["scene", "IXML/Scene"]}],
        MEDIA_POOL_GET_URI: [{"return": [{"Path": "/Audio/Rain.wav", "IXML/Scene": "Exterior"}]}],
    })
    env = _env(tmp_path)
    code, first = gateway.execute_gateway(
        ["core-call", MEDIA_POOL_GET_URI, "--max-results", "1", "--include-field", "scene"],
        env=env, client_factory=lambda _: client)
    assert code == 0, first
    assert first["agent_result"]["field_bindings"] == [{"meaning": "scene", "field": "IXML/Scene", "value_key": "scene"}]
    code, rejected = gateway.execute_gateway(first["agent_result"]["next_command"]["gateway_argv"],
        env=env, client_factory=lambda _: client)
    assert code == 2, rejected
    assert rejected["error_code"] == "MEDIA_POOL_CONTINUATION_CHANGED"
    assert [call[0] for call in client.calls].count(MEDIA_POOL_GET_URI) == 1


@pytest.fixture
def media_pool_product_capture(request):
    import os
    context_path = os.environ.get("WAAPI_MEDIA_POOL_BRANCH_CAPTURE_CONTEXT")
    observed = {}
    if context_path:
        from tests.support.media_pool_branch_evidence import load_media_pool_capture, finish_media_pool_capture
        from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
        capture = load_media_pool_capture(Path(context_path), request.node.nodeid)
        register_exact_evidence_finalizer(request.node, lambda reports: finish_media_pool_capture(capture, reports, observed))
    return observed


def test_product_media_pool_discovery_to_exact_filtered_projection_preserves_native_field_identity(
    tmp_path: Path, media_pool_product_capture: dict,
) -> None:
    names = ["IXML/Scene", "IXML/SCENE", "scene", "scene", "场景", "A/B", "A B", "Filename"]
    raw_row = {"Path": "/Audio/Rain.wav", "FileId": "rain", "Db": {"id": MEDIA_DB_ID, "name": "Project Originals"},
               "scene": "Exterior", "场景": "外景", "A/B": "slash", "A B": "space"}
    client = FakeClient({
        "ak.wwise.core.getInfo": [_info()] * 5, "ak.wwise.core.getProjectInfo": [_project(tmp_path)] * 5,
        "ak.wwise.core.mediaPool.getFields": [{"return": names}] * 5,
        MEDIA_POOL_GET_URI: [{"return": [raw_row]}],
    })
    env = _env(tmp_path)
    no_match_argv = ["metadata", "media-pool-fields", "--meaning", "not-a-field"]
    code, no_match = gateway.execute_gateway(no_match_argv, env=env, client_factory=lambda _: client)
    assert code == 0 and no_match["agent_result"]["fields"] == [] and no_match["agent_result"]["complete"] is True
    discovery_argv = ["metadata", "media-pool-fields", "--meaning", "场景"]
    code, discovery = gateway.execute_gateway(discovery_argv, env=env, client_factory=lambda _: client)
    assert code == 0, discovery
    assert discovery["agent_result"]["fields"] == [{"name": "场景", "name_complete": True}]
    selected = discovery["agent_result"]["fields"][0]["name"]
    argv = ["core-call", MEDIA_POOL_GET_URI, "--max-results", "2", "--text-filter", "scene", "equals", "Exterior",
            "--include-field", selected, "--include-field", "A/B", "--include-field", "A B", "--include-field", "scene"]
    code, payload = gateway.execute_gateway(argv, env=env, client_factory=lambda _: client)
    assert code == 0, payload
    expected_args = {"maxResults": 2, "filters": [{"type": "field", "field": "scene", "operator": "equals", "value": "Exterior"}]}
    expected_options = {"return": ["Path", "FileId", "Db", "场景", "A/B", "A B", "scene"]}
    assert client.calls[-1] == (MEDIA_POOL_GET_URI, expected_args, expected_options)
    assert payload["agent_result"]["items"] == [{"path": "/Audio/Rain.wav", "file_id": "rain", "database_id": MEDIA_DB_ID,
        "database_name": "Project Originals", "values": {"场景": "外景", "A/B": "slash", "A B": "space", "scene": "Exterior"}}]
    assert payload["agent_result"]["field_bindings"] == [
        {"meaning": "scene", "field": "scene", "value_key": "scene"},
        {"meaning": "场景", "field": "场景", "value_key": "场景"},
        {"meaning": "A/B", "field": "A/B", "value_key": "A/B"},
        {"meaning": "A B", "field": "A B", "value_key": "A B"},
    ]
    errors = []
    for requested, expected in [("ixml/scene", ["IXML/Scene", "IXML/SCENE"]), ("unrelated", [])]:
        rejected_argv = ["core-call", MEDIA_POOL_GET_URI, "--max-results", "2", "--include-field", requested]
        rejected_code, rejected = gateway.execute_gateway(rejected_argv, env=env, client_factory=lambda _: client)
        assert rejected_code == 2 and rejected["error_code"] == "MEDIA_BUILD_FIELD_AMBIGUOUS", rejected
        assert rejected["details"]["field_choices"] == expected
        errors.append({"argv": rejected_argv, "exit_code": rejected_code, "payload": rejected})
    assert [call[0] for call in client.calls].count(MEDIA_POOL_GET_URI) == 1
    media_pool_product_capture.update({
        "gateway": {"argv": argv, "exit_code": code, "payload": payload},
        "discovery": {"argv": discovery_argv, "exit_code": 0, "payload": discovery},
        "no_match": {"argv": no_match_argv, "exit_code": 0, "payload": no_match},
        "native_call": {"uri": MEDIA_POOL_GET_URI, "args": expected_args, "options": expected_options, "result": {"return": [raw_row]}},
        "field_discovery_call": {"uri": "ak.wwise.core.mediaPool.getFields", "args": {}, "options": {}, "result": {"return": names}},
        "rejected_reads": errors, "media_pool_dispatch_count": 1,
    })


def test_media_pool_exact_choice_does_not_hide_malformed_native_inventory_entries(tmp_path: Path) -> None:
    client = FakeClient({
        "ak.wwise.core.getInfo": [_info()], "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        "ak.wwise.core.mediaPool.getFields": [{"return": ["Filename", None]}],
        MEDIA_POOL_GET_URI: [{"return": []}],
    })
    code, payload = gateway.execute_gateway(
        ["core-call", MEDIA_POOL_GET_URI, "--max-results", "2", "--include-field", "Filename"],
        env=_env(tmp_path), client_factory=lambda _: client)
    assert code == 2, payload
    assert MEDIA_POOL_GET_URI not in [call[0] for call in client.calls]
