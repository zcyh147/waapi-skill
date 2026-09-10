from __future__ import annotations

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
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
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
    bypass_code, bypass = gateway.execute_gateway(
        ["--version", version, "typed-call", operation, "--schema-digest", "0" * 64],
        env=_env(tmp_path, version=version),
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
    assert payload["error_code"] == "GatewayInputError"
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
    assert all("next_command" not in row for row in rows.values())
