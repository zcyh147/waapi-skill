from __future__ import annotations

import importlib.util
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.operation_registry import audio_import_business_contract


def test_audio_import_draft_digest_binds_only_the_registry_business_adapter() -> None:
    version = "2022.1"

    assert operation_composer_digest("audio.import", version) == canonical_sha256(
        {
            "contract": "waapi-skill.audio-import-draft-binding/v1",
            "business_adapter": audio_import_business_contract(version),
        }
    )
from wwise_waapi.operation_drafts import (
    OperationDraftState,
    OperationDraftStore,
    parse_operation_draft_archive_bytes,
)
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


def _project_path(tmp_path: Path) -> Path:
    return tmp_path / "project" / "SampleProject.wproj"


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


class BusinessCheckClient:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[tuple[str, Any, Any]] = []

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            return _info()
        if uri == "ak.wwise.core.getProjectInfo":
            return {
                "id": PROJECT_ID,
                "name": "SampleProject",
                "path": str(_project_path(self.tmp_path)),
            }
        if uri == "ak.wwise.core.object.getTypes":
            return {
                "return": [
                    {"classId": 1, "name": "ActorMixer", "type": "ActorMixer"},
                    {
                        "classId": 2,
                        "name": "RandomSequenceContainer",
                        "type": "RandomSequenceContainer",
                    },
                ]
            }
        if uri == "ak.wwise.core.object.get":
            source = args.get("from", {}) if isinstance(args, Mapping) else {}
            paths = source.get("path", []) if isinstance(source, Mapping) else []
            ids = source.get("id", []) if isinstance(source, Mapping) else []
            if ids == [PARENT_ID] or paths == [
                r"\Actor-Mixer Hierarchy\Default Work Unit\Weather"
            ]:
                return {
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
            return {"return": []}
        raise AssertionError(f"Unexpected WAAPI call: {uri} {args!r} {options!r}")

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


def test_audio_import_business_binds_one_unique_visible_name_without_a_path(
    tmp_path: Path,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "audio.import")
    assert code == 0, started
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(_project_path(tmp_path)),
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
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--object-name",
            "Weather",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert bind_code == 0, bound
    assert bound["bound_object"] == {
        "handle": bound["bound_object"]["handle"],
        "name": "Weather",
        "type": "ActorMixer",
        "semantic_kind": None,
    }
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {
            "waql": (
                'from search "Weather" where name = "Weather" take 2'
            )
        },
        {"return": ["id", "name", "type", "path"]},
    )


def test_audio_import_business_unique_name_binding_returns_bounded_candidates(
    tmp_path: Path,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "audio.import")
    assert code == 0, started
    rows = [
        {
            "id": f"{{11111111-1111-1111-1111-11111111111{index}}}",
            "name": "Weather",
            "type": "ActorMixer",
            "path": rf"\Actor-Mixer Hierarchy\Work Unit {index}\Weather",
        }
        for index in (1, 2)
    ]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(_project_path(tmp_path)),
                }
            ],
            "ak.wwise.core.object.get": [{"return": rows}],
        }
    )

    bind_code, boundary = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-object",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--object-name",
            "Weather",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert bind_code == 2
    assert boundary["error_code"] == "BUSINESS_OBJECT_NOT_UNIQUE"
    assert boundary["details"] == {
        "actual_count": 2,
        "candidates": rows,
    }
    record = OperationDraftStore(tmp_path / "state").inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )
    assert record.revision == 1


def test_audio_import_business_gateway_binds_and_declares_without_native_facts(
    tmp_path: Path,
) -> None:
    media = tmp_path / "rain.wav"
    media.write_bytes(b"RIFF-test")
    code, started = _offline(tmp_path, "draft-start", "audio.import")
    assert code == 0, started
    start_next = started["draft"]["next_action_binding"]
    assert start_next["required_next_phase"] == (
        "bind_only_handle_typed_business_objects_then_configure_and_declare"
    )
    assert start_next["object_binding"]["by_id"][3] == "draft-bind-object"
    assert start_next["object_binding"]["by_unique_name"][3] == (
        "draft-bind-object"
    )
    assert "by_path" not in start_next["object_binding"]
    assert "switch_value" in start_next["binding_decision"]["literal_never_bind"]
    assert start_next["binding_decision"]["bound_object_handle_fields"] == [
        "output_bus",
        "event_parent",
        "custom_reference_value",
    ]
    assert start_next["configure"]["reference_default_rule"] == (
        "copy_one_bound_object_handle_never_a_path_or_name"
    )
    assert start_next["declare_new"]["known_user_fields"] == (
        "complete_on_first_submission"
    )
    assert "draft-apply" not in json.dumps(start_next)
    assert "wwise_path_discipline" not in start_next
    assert "object_path" in start_next["forbidden_inputs"]
    assert "object_type" in start_next["forbidden_inputs"]
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before_legacy_attempt = record_path.read_bytes()
    legacy_code, legacy = _offline(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--facts",
        "--action",
        "add_import_row",
        "--object-path",
        r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\Rain_Bed",
        "--object-type",
        "Sound SFX",
        "--assignment-mode",
        "none",
    )
    assert legacy_code == 2
    assert legacy["error_code"] == "GatewayInputError"
    assert "no longer accepts shallow" in legacy["message"]
    assert record_path.read_bytes() == before_legacy_attempt
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(_project_path(tmp_path)),
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
                    "path": str(_project_path(tmp_path)),
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
        "--default-field-value",
        field_handle,
        "-2.5",
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
    )
    assert declare_code == 0, declared
    assert declared["draft"]["revision"] == 5
    assert declared["draft"]["declarations"][0]["fields"] == {
        "language": "SFX",
        "loop": "infinite",
        "media_file": str(media),
        "volume_db": -4.0,
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


def test_structure_declaration_reaches_live_check_and_persists_readable_preview(
    tmp_path: Path,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "audio.import")
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    bind_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(_project_path(tmp_path)),
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
        client_factory=lambda _url: bind_client,
    )
    assert bind_code == 0, bound
    declare_code, declared = _offline(
        tmp_path,
        "draft-declare-new",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--declaration-id",
        "variants",
        "--parent-handle",
        bound["bound_object"]["handle"],
        "--name",
        "Variants",
        "--kind",
        "random-container",
    )
    assert declare_code == 0, declared
    check_client = BusinessCheckClient(tmp_path)

    check_code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "3",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: check_client,
    )

    assert check_code == 0, json.dumps(checked, indent=2)
    assert checked["draft"]["revision"] == 4
    assert checked["draft"]["preview"]["readable_lines"] == [
        "对象：Variants",
        "类型：Random Container",
    ]
    assert checked["draft"]["next_action_binding"]["required_next_phase"] == (
        "preview_from_checked_business_draft"
    )
    assert checked["next_command"]["gateway_argv"][0] == "preview-from-draft"
    assert "--apply" not in checked["next_command"]["gateway_argv"]
    record = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    assert record.composition is not None
    session = record.composition["business_session"]
    assert session["active_preview"]["readable_lines"] == [
        "对象：Variants",
        "类型：Random Container",
    ]

    preview_client = BusinessCheckClient(tmp_path)
    preview_code, previewed = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "4",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: preview_client,
    )
    assert preview_code == 0, json.dumps(previewed, indent=2)
    assert previewed["state"] == "awaiting_confirmation"
    assert previewed["agent_result"]["request"]["arguments"]["imports"] == [
        {
            "object_path": (
                r"\Actor-Mixer Hierarchy\Default Work Unit\Weather"
                r"\<Random Container>Variants"
            ),
            "object_type": "RandomSequenceContainer",
        }
    ]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    archived = parse_operation_draft_archive_bytes(
        record_path.read_bytes(),
        expected_draft_id=draft_id,
        allow_cleaned_file_evidence=True,
    )
    assert archived.state is OperationDraftState.SEALED
    assert archived.seal is not None
    assert archived.seal["request"] == previewed["agent_result"]["request"]
