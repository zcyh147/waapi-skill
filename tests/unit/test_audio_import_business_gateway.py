from __future__ import annotations

import importlib.util
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.operation_drafts import OperationDraftStore
from wwise_waapi.operation_registry import operation_request_schema_digest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_audio_import_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
PARENT_ID = "{11111111-1111-1111-1111-111111111111}"


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
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": "2022.1",
    }


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
            "year": 2022,
            "major": 1,
            "minor": 0,
            "build": 1,
            "displayName": "v2022.1.0.1",
        },
    }


def _offline(tmp_path: Path, *argv: str) -> tuple[int, dict[str, Any]]:
    def reject_connection(url: str) -> None:
        raise AssertionError(f"offline business command connected to {url}")

    return waapi_gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *argv],
        env=_env(tmp_path),
        client_factory=reject_connection,
    )


def test_audio_import_business_gateway_binds_and_declares_without_native_facts(
    tmp_path: Path,
) -> None:
    media = tmp_path / "rain.wav"
    media.write_bytes(b"RIFF-test")
    code, started = _offline(tmp_path, "draft-start", "audio.import")
    assert code == 0, started
    start_next = started["draft"]["next_action_binding"]
    assert start_next["required_next_phase"] == "bind_required_business_objects"
    assert start_next["object_binding"]["by_id"][3] == "draft-bind-object"
    assert "draft-apply" not in json.dumps(start_next)
    assert "wwise_path_discipline" not in start_next
    assert "object_path" in start_next["forbidden_inputs"]
    assert "object_type" in start_next["forbidden_inputs"]
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(tmp_path / "SampleProject.wproj"),
                }
            ],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Weather",
                            "type": "ActorMixer",
                            "path": (
                                r"\Actor-Mixer Hierarchy\Default Work Unit\Weather"
                            ),
                        }
                    ]
                }
            ],
        }
    )

    bind_code, bound = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "1",
            "--object-id",
            PARENT_ID,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert bind_code == 0, json.dumps(bound, indent=2)
    parent_handle = bound["bound_object"]["handle"]
    assert parent_handle.startswith("boh1-")
    assert bound["draft"]["revision"] == 2

    field_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(tmp_path / "SampleProject.wproj"),
                }
            ],
            "ak.wwise.core.object.getTypes": [
                {"return": [{"classId": 65552, "name": "Sound", "type": "Sound"}]}
            ],
            "ak.wwise.core.object.getPropertyAndReferenceNames": [
                {"return": ["CustomGain"]}
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "CustomGain",
                    "type": "Real32",
                    "restriction": {"type": "range", "min": -12.0, "max": 12.0},
                }
            ],
        }
    )
    field_code, field_bound = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-field",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "2",
            "--class-name",
            "Sound",
            "--token",
            "CustomGain",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: field_client,
    )
    assert field_code == 0, json.dumps(
        {"payload": field_bound, "calls": field_client.calls}, indent=2
    )
    field_handle = field_bound["bound_field"]["handle"]
    assert field_bound["bound_field"]["restrictions"] == {
        "maximum": 12.0,
        "minimum": -12.0,
    }

    config_code, configured = _offline(
        tmp_path,
        "draft-business-configure",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--mode",
        "create",
        "--add-to-source-control",
    )
    assert config_code == 0, configured
    declare_code, declared = _offline(
        tmp_path,
        "draft-declare-new",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--declaration-id",
        "rain-bed",
        "--parent-handle",
        parent_handle,
        "--name",
        "Rain_Bed",
        "--kind",
        "sound-sfx",
        "--field",
        "media_file",
        str(media),
        "--field",
        "language",
        "SFX",
        "--field",
        "volume_db",
        "-4",
        "--field",
        "loop",
        "infinite",
        "--field-value",
        field_handle,
        "-2.5",
    )
    assert declare_code == 0, declared
    assert declared["draft"]["revision"] == 5
    assert declared["draft"]["declarations"][0]["fields"] == {
        "language": "SFX",
        "loop": "infinite",
        "media_file": str(media),
        "volume_db": -4.0,
        "field_values": {field_handle: -2.5},
    }

    store = OperationDraftStore(tmp_path / "state")
    materialized = store.materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=5,
        schema_digest=operation_request_schema_digest("audio.import", "2022.1"),
        composer_digest=operation_composer_digest("audio.import", "2022.1"),
    )
    assert materialized.request["arguments"]["imports"][0] == {
        "audio_file": str(media),
        "import_language": "SFX",
        "object_path": (
            r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\<Sound SFX>Rain_Bed"
        ),
        "object_type": "Sound SFX",
        "properties": [
            {"name": "IsLoopingEnabled", "value": True},
            {"name": "IsLoopingInfinite", "value": True},
            {"name": "Volume", "value": -4.0},
            {"name": "CustomGain", "value": -2.5},
        ],
    }
