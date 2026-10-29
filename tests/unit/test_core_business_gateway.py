from __future__ import annotations

from tests.support.gateway_config import set_gateway_config

import importlib.util
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest
from wwise_waapi.core_business_contracts import (
    core_business_operations,
    core_business_versions,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_core_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


SOURCE_ID = "{11111111-1111-1111-1111-111111111111}"
TARGET_ID = "{22222222-2222-2222-2222-222222222222}"
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


def _env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": "2025.1",
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_VERSION": "2025.1",
    }


def test_request_schema_replaces_object_diff_typed_fields_with_one_business_read(
    tmp_path: Path,
) -> None:
    operation = "ak.wwise.core.object.diff"

    exit_code, payload = gateway.execute_gateway(
        ["request-schema", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline command connected to {url}"),
    )

    assert exit_code == 0, payload
    assert payload["contract"] == "waapi-skill.core-business-route/v1"
    assert payload["business_adapter"]["execution_shape"] == "bounded_read"
    assert payload["business_adapter"]["start"]["subcommand"] == "core-call"
    assert payload["continuation"] == {
        "subcommand": "core-call",
        "gateway_argv_prefix": ["core-call", operation],
        "append_only_disclosed_business_fields": True,
    }
    encoded = json.dumps(payload, sort_keys=True)
    assert "typed-call" not in encoded
    assert "schema_digest" not in encoded
    assert "field_handle" not in encoded


def test_request_schema_routes_project_save_to_one_business_draft(tmp_path: Path) -> None:
    operation = "ak.wwise.core.project.save"

    exit_code, payload = gateway.execute_gateway(
        ["request-schema", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline command connected to {url}"),
    )

    assert exit_code == 0, payload
    adapter = payload["business_adapter"]
    assert adapter["execution_shape"] == "draft_mutation"
    assert adapter["start"]["subcommand"] == "draft-start"
    assert payload["continuation"]["subcommand"] == "draft-start"
    assert payload["continuation"]["gateway_argv"] == ["draft-start", operation]
    assert "typed-call" not in json.dumps(payload, sort_keys=True)


@pytest.mark.parametrize("version", ["2021.1", "2022.1"])
def test_project_save_older_versions_disclose_one_empty_business_plan(
    tmp_path: Path, version: str,
) -> None:
    operation = "ak.wwise.core.project.save"

    exit_code, payload = gateway.execute_gateway(
        ["--version", version, "request-schema", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert exit_code == 0, payload
    assert payload["contract"] == "waapi-skill.core-business-route/v1"
    assert payload["input_shape"] == "business_declaration"
    declaration = payload["business_adapter"]["declaration"]
    assert declaration["required_fields"] == []
    assert declaration["optional_fields"] == []
    assert declaration["field_types"] == {}
    assert declaration["input_forms"] == {}
    assert "field_semantics" not in declaration
    assert payload["continuation"]["gateway_argv"] == ["draft-start", operation]


@pytest.mark.parametrize("operation", sorted(gateway.core_business_operations()))
def test_every_issue_84_route_blocks_typed_call_bypass(
    tmp_path: Path,
    operation: str,
) -> None:
    called = False

    def reject_connection(url: str) -> None:
        nonlocal called
        called = True
        raise AssertionError(f"typed bypass connected to {url}")

    exit_code, payload = gateway.execute_gateway(
        ["typed-call", operation, "--schema-digest", "0" * 64],
        env=_env(tmp_path),
        client_factory=reject_connection,
    )

    assert exit_code == 2
    assert "closed Core business" in payload["message"]
    assert called is False


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation in sorted(core_business_operations())
        for version in core_business_versions(operation)
    ],
)
def test_every_issue_84_version_lane_has_one_business_schema(
    tmp_path: Path,
    operation: str,
    version: str,
) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["--version", version, "request-schema", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert exit_code == 0, payload
    assert payload["business_adapter"]["operation"] == operation
    assert payload["business_adapter"]["version"] == version


def test_project_save_draft_start_returns_only_core_business_continuation(
    tmp_path: Path,
) -> None:
    operation = "ak.wwise.core.project.save"

    exit_code, payload = gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), "draft-start", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline command connected to {url}"),
    )

    assert exit_code == 0, payload
    next_action = payload["draft"]["next_action_binding"]
    assert next_action["required_next_phase"] == "declare_complete_core_plan"
    declaration = next_action["declaration"]
    assert declaration["fixed_argv_prefix"][3] == "draft-declare-core-plan"
    assert declaration["append_fields"] == {
        "subcommand": "draft-declare-core-plan",
        "required_fields": [],
        "optional_fields": ["auto_check_out"],
        "field_types": {"auto_check_out": "boolean"},
        "field_semantics": {
            "auto_check_out": {
                "intent_binding": (
                    "include_when_user_explicitly_allows_or_forbids_auto_checkout"
                ),
                "omitted_effect": "wwise_native_default_true",
                "true_effect": (
                    "automatically_checkout_affected_work_units_and_project"
                ),
                "false_effect": "do_not_automatically_checkout",
            }
        },
        "input_forms": {
            "auto_check_out": {
                "flag": "--value",
                "repeatable": False,
                "arguments": ["auto_check_out", "VALUE"],
            },
        },
    }
    assert "draft-apply" not in json.dumps(payload, sort_keys=True)


def test_project_save_core_plan_closes_business_draft_without_dispatch(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", "ak.wwise.core.project.save"],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline command connected to {url}"),
    )
    assert start_code == 0, started
    draft = started["draft"]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        }
    )
    env = _env(tmp_path)
    set_gateway_config(env, waapi_host="127.0.0.1")
    set_gateway_config(env, waapi_port=int("31337"))

    exit_code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-declare-core-plan",
            draft["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(draft["revision"]),
            "--value",
            "auto_check_out",
            "true",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    updated = payload["draft"]
    assert updated["revision"] == 2
    assert updated["business_revision"] == 1
    assert "missing_fields_status" not in updated
    assert updated["response_integrity"] == {
        "complete": True,
        "truncated": False,
        "projection": "business_update_and_copy_ready_continuation",
        "compact_projection_is_not_truncation": True,
    }
    assert updated["next_action_binding"]["required_next_phase"] == (
        "check_complete_core_plan"
    )
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]

    check_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        }
    )
    check_code, checked = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-check",
            draft["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "2",
        ],
        env=env,
        client_factory=lambda _url: check_client,
    )
    assert check_code == 0, checked
    assert checked["next_command"]["gateway_argv"][0] == "preview-from-draft"
    assert all(
        call[0] != "ak.wwise.core.project.save" for call in check_client.calls
    )

    preview_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        }
    )
    preview_code, previewed = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "preview-from-draft",
            draft["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(checked["draft"]["revision"]),
        ],
        env=env,
        client_factory=lambda _url: preview_client,
    )
    assert preview_code == 0, previewed
    assert previewed["state"] == "awaiting_confirmation"
    assert previewed["agent_result"]["request"] == {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.core.project.save",
            "args": {"autoCheckOutToSourceControl": True},
            "options": {},
        },
    }
    assert all(
        call[0] != "ak.wwise.core.project.save" for call in preview_client.calls
    )


def test_core_call_resolves_two_exact_objects_and_dispatches_one_bounded_diff(
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
                            "name": "Source",
                            "type": "Sound",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Source",
                        },
                        {
                            "id": TARGET_ID,
                            "name": "Target",
                            "type": "Sound",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Target",
                        },
                    ]
                }
            ],
            "ak.wwise.core.object.diff": [
                {"properties": ["Volume"], "lists": []}
            ],
        }
    )
    env = _env(tmp_path)
    set_gateway_config(env, waapi_host="127.0.0.1")
    set_gateway_config(env, waapi_port=int("31337"))

    exit_code, payload = gateway.execute_gateway(
        [
            "core-call",
            "ak.wwise.core.object.diff",
            "--source-id",
            SOURCE_ID,
            "--target-id",
            TARGET_ID,
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {
        "properties": ["Volume"],
        "lists": [],
    }
    assert payload["business_request"] == {
        "operation": "ak.wwise.core.object.diff",
        "roles": {"source": SOURCE_ID, "target": TARGET_ID},
    }
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.diff",
    ]


@pytest.mark.parametrize(
    ("object_type", "path"),
    (
        ("Action", r"\Events\Default Work Unit\Play_Rain\[Play - Rain]"),
        (
            "EffectSlot",
            r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\[Effect Slot 0]",
        ),
    ),
)
def test_core_call_accepts_real_wwise_unnamed_identity(
    tmp_path: Path,
    object_type: str,
    path: str,
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
                            "name": "",
                            "type": object_type,
                            "path": path,
                        },
                        {
                            "id": TARGET_ID,
                            "name": "Target",
                            "type": "Sound",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Target",
                        },
                    ]
                }
            ],
            "ak.wwise.core.object.diff": [{"properties": [], "lists": []}],
        }
    )
    env = _env(tmp_path)
    set_gateway_config(env, waapi_host="127.0.0.1")
    set_gateway_config(env, waapi_port=int("31337"))

    exit_code, payload = gateway.execute_gateway(
        [
            "core-call",
            "ak.wwise.core.object.diff",
            "--source-id",
            SOURCE_ID,
            "--target-id",
            TARGET_ID,
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {"properties": [], "lists": []}


@pytest.mark.parametrize(
    ("operation", "result"),
    [
        (
            "ak.wwise.core.switchContainer.getAssignments",
            {"return": [{"child": SOURCE_ID, "stateOrSwitch": TARGET_ID}]},
        ),
        (
            "ak.wwise.core.blendContainer.getAssignments",
            {
                "return": [
                    {
                        "child": TARGET_ID,
                        "index": 0,
                        "edges": [
                            {
                                "edgePosition": 0.0,
                                "fadeMode": "None",
                                "fadeShape": "Linear",
                            },
                            {
                                "edgePosition": 100.0,
                                "fadeMode": "None",
                                "fadeShape": "Linear",
                            },
                        ],
                    }
                ]
            },
        ),
    ],
)
def test_core_call_dispatches_single_object_relationship_reads(
    tmp_path: Path,
    operation: str,
    result: dict[str, Any],
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
                            "name": "Relationship owner",
                            "type": "SwitchContainer",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Owner",
                        }
                    ]
                }
            ],
            operation: [result],
        }
    )
    env = _env(tmp_path)
    set_gateway_config(env, waapi_host="127.0.0.1")
    set_gateway_config(env, waapi_port=int("31337"))

    exit_code, payload = gateway.execute_gateway(
        ["core-call", operation, "--object-id", SOURCE_ID],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == result
    assert [call[0] for call in client.calls][-1] == operation


def test_core_call_discovers_is_linked_field_from_business_meaning(
    tmp_path: Path,
) -> None:
    property_info = {
        "name": "Volume",
        "type": "Real32",
        "display": {"name": "Volume", "group": "General"},
        "restriction": {"type": "range", "min": -96.3, "max": 96.3},
        "supports": {"unlink": True},
    }
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
            "ak.wwise.core.object.getPropertyAndReferenceNames": [
                {"return": ["Volume", "OutputBus"]},
                {"return": ["Volume", "OutputBus"]},
            ],
            "ak.wwise.core.object.getPropertyInfo": [property_info, property_info],
            "ak.wwise.core.object.isLinked": [{"linked": False}],
        }
    )
    env = _env(tmp_path)
    set_gateway_config(env, waapi_host="127.0.0.1")
    set_gateway_config(env, waapi_port=int("31337"))

    exit_code, payload = gateway.execute_gateway(
        [
            "core-call",
            "ak.wwise.core.object.isLinked",
            "--object-id",
            SOURCE_ID,
            "--field-meaning",
            "volume",
            "--platform-name",
            "Windows",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {"linked": False}
    assert client.calls[-1] == (
        "ak.wwise.core.object.isLinked",
        {"object": SOURCE_ID, "property": "Volume", "platform": "Windows"},
        {},
    )


def test_core_mutation_check_rejects_bound_object_drift_before_dispatch(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    env = _env(tmp_path)
    set_gateway_config(env, waapi_host="127.0.0.1")
    set_gateway_config(env, waapi_port=int("31337"))
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", "ak.wwise.core.audio.mute"],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    original_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Alarm"
    bind_client = FakeClient(
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
                            "path": original_path,
                        }
                    ]
                }
            ],
        }
    )
    bind_code, bound = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "1",
            "--role",
            "object",
            "--object-id",
            SOURCE_ID,
        ],
        env=env,
        client_factory=lambda _url: bind_client,
    )
    assert bind_code == 0, bound
    assert bound["draft"]["response_integrity"] == {
        "complete": True,
        "truncated": False,
        "projection": "bound_object_and_copy_ready_continuation",
        "compact_projection_is_not_truncation": True,
    }
    assert "created_at" not in bound["draft"]
    assert '"fixed_argv_prefix":' not in json.dumps(bound["draft"])
    object_handle = bound["bound_object"]["handle"]
    declare_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        }
    )
    declare_code, declared = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-declare-core-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "2",
            "--role",
            "object_handles",
            object_handle,
            "--value",
            "muted",
            "true",
        ],
        env=env,
        client_factory=lambda _url: declare_client,
    )
    assert declare_code == 0, declared
    stale_client = FakeClient(
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
                            "path": r"\Actor-Mixer Hierarchy\Moved\Alarm",
                        }
                    ]
                }
            ],
        }
    )
    check_code, rejected = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "3",
        ],
        env=env,
        client_factory=lambda _url: stale_client,
    )

    assert check_code == 2
    assert rejected["error_code"] == "OBJECT_HANDLE_STALE"
    assert all(call[0] != "ak.wwise.core.audio.mute" for call in stale_client.calls)


def test_audio_convert_core_plan_accepts_bound_objects_names_and_exact_io_root(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    io_root = tmp_path / "convert-output"
    io_root.mkdir()
    env = _env(tmp_path)
    set_gateway_config(env, waapi_host="127.0.0.1")
    set_gateway_config(env, waapi_port=int("31337"))
    operation = "ak.wwise.core.audio.convert"
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", operation],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    binding = started["draft"]["next_action_binding"]["object_binding"]
    assert binding["next_role"] == "audio_object"
    assert binding["by_id"]["fixed_argv_prefix"][-2:] == [
        "--role",
        "audio_object",
    ]
    assert binding["by_path_segments"]["fixed_argv_prefix"][-2:] == [
        "--role",
        "audio_object",
    ]
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Alarm"
    bind_client = FakeClient(
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
                            "path": object_path,
                        }
                    ]
                },
                {"return": [{"id": SOURCE_ID, "@IsVoice": False}]},
            ],
        }
    )
    bind_code, bound = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "1",
            "--role",
            "audio_object",
            "--object-id",
            SOURCE_ID,
        ],
        env=env,
        client_factory=lambda _url: bind_client,
    )
    assert bind_code == 0, bound
    assert bound["bound_object"]["business_kind"] == "sound-sfx"
    assert bound["bound_object"]["business_kind_resolution"]["source"] == (
        "live_sound_voice_discriminator"
    )
    object_handle = bound["bound_object"]["handle"]
    declare_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        }
    )
    declare_code, declared = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-declare-core-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "2",
            "--role",
            "audio_object_handles",
            object_handle,
            "--item",
            "platform_names",
            "Windows",
            "--item",
            "languages",
            "SFX",
            "--value",
            "io_root",
            str(io_root),
        ],
        env=env,
        client_factory=lambda _url: declare_client,
    )

    assert declare_code == 0, declared
    assert "missing_fields_status" not in declared["draft"]
    assert declared["draft"]["response_integrity"]["complete"] is True
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_core_plan"
    )
    assert all(call[0] != operation for call in declare_client.calls)


def test_randomizer_core_plan_discovers_field_by_meaning_then_closes_values(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    env = _env(tmp_path)
    set_gateway_config(env, waapi_host="127.0.0.1")
    set_gateway_config(env, waapi_port=int("31337"))
    operation = "ak.wwise.core.object.setRandomizer"
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", operation],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    bind_client = FakeClient(
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
    bind_code, bound = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "1",
            "--role",
            "object",
            "--object-id",
            SOURCE_ID,
        ],
        env=env,
        client_factory=lambda _url: bind_client,
    )
    assert bind_code == 0, bound
    object_handle = bound["bound_object"]["handle"]
    property_info = {
        "name": "Volume",
        "type": "Real32",
        "display": {"name": "Volume", "group": "General"},
        "restriction": {"type": "range", "min": -96.3, "max": 96.3},
        "supports": {"unlink": True},
    }
    discover_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.object.getPropertyAndReferenceNames": [
                {"return": ["Volume", "Pitch"]},
                {"return": ["Volume", "Pitch"]},
            ],
            "ak.wwise.core.object.getPropertyInfo": [property_info, property_info],
        }
    )
    discover_code, discovered = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-discover-fields",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "2",
            "--object-handle",
            object_handle,
            "--meaning",
            "volume",
            "--platform",
            "Windows",
        ],
        env=env,
        client_factory=lambda _url: discover_client,
    )
    assert discover_code == 0, discovered
    field_handle = discovered["field_candidates"][0]["handle"]
    declare_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        }
    )
    declare_code, declared = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-declare-core-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "3",
            "--role",
            "object_handle",
            object_handle,
            "--field",
            "field_handle",
            field_handle,
            "--value",
            "enabled",
            "true",
            "--value",
            "minimum_offset",
            "-3",
            "--value",
            "platform_name",
            "Windows",
        ],
        env=env,
        client_factory=lambda _url: declare_client,
    )

    assert declare_code == 0, declared
    assert "missing_fields_status" not in declared["draft"]
    assert declared["draft"]["response_integrity"]["complete"] is True
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_core_plan"
    )
    assert all(call[0] != operation for call in declare_client.calls)


ATTENUATION_URI = "ak.wwise.core.object.setAttenuationCurve"
# Exact live identity in frozen db82de6 EXP25-C08: the role binding returned
# Attenuation but an empty 'ambiguous' classification and instructed a stop.
ATTENUATION_ROW = {
    "id": "{112E0906-8BA7-4A12-AA46-D9147F0462A9}",
    "name": "Expansion_EXP25-C08_Attenuation", "type": "Attenuation",
    "path": r"\Attenuations\Default Work Unit\Expansion_EXP25-C08_Attenuation",
}


def _core_role_binding_case(tmp_path: Path, version: str, *, operation: str = ATTENUATION_URI):
    env = _env(tmp_path)
    set_gateway_config(env, wwise_version=version)
    set_gateway_config(env, waapi_host="127.0.0.1")
    set_gateway_config(env, waapi_port=int("31337"))
    state_dir = tmp_path / "state"
    code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", operation], env=env,
        client_factory=lambda _url: pytest.fail("start must remain offline"),
    )
    assert code == 0, started
    info = _info()
    info["version"]["year"] = int(version.split(".")[0])
    info["version"]["displayName"] = f"v{version}.0.1"
    return env, state_dir, started, info


def _bind_core_role(env, state_dir, started, info, tmp_path, rows, *, role="attenuation", selector=None):
    project = _project(tmp_path)
    object_results = [{"return": rows}]
    if info.get("version", {}).get("year") == 2021:
        object_results.insert(0, {"return": [{**project, "type": "Project", "filePath": project["path"]}]})
    client = FakeClient({
        "ak.wwise.core.getInfo": [info],
        "ak.wwise.core.getProjectInfo": [project],
        "ak.wwise.core.object.get": object_results,
    })
    code, payload = gateway.execute_gateway([
        "--state-dir", str(state_dir), "draft-bind-object", started["draft"]["draft_id"],
        "--task-authority", started["task_authority"], "--expected-revision", "1",
        *([] if role is None else ["--role", role]),
        *(selector or ["--object-id", ATTENUATION_ROW["id"]]),
    ], env=env, client_factory=lambda _url: client)
    return code, payload, client


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("scope", ("id", "path"))
def test_exact_frozen_attenuation_role_has_resolved_live_class_comparison(version, tmp_path, scope):
    env, state, started, info = _core_role_binding_case(tmp_path, version)
    selector = (["--object-id", ATTENUATION_ROW["id"]] if scope == "id" else
                [token for name in ("Attenuations", "Default Work Unit", ATTENUATION_ROW["name"])
                 for token in ("--object-path-segment", name)])
    code, bound, client = _bind_core_role(env, state, started, info, tmp_path, [dict(ATTENUATION_ROW)], selector=selector)
    assert code == 0, bound
    assert bound["bound_object"]["business_kind"] == "attenuation"
    assert bound["bound_object"]["business_kind_resolution"] == {
        "status": "resolved", "candidates": ["attenuation"], "reflected_type": "Attenuation",
        "source": "closed_role_live_type",
    }
    assert bound["bound_object"]["semantic_kind"] is None  # Not a new creatable kind.
    next_action = bound["draft"]["next_action_binding"]
    assert next_action["required_next_phase"] == "declare_complete_core_plan"
    assert next_action["object_binding"]["next_role"] == "attenuation"
    assert next_action["declaration"]["append_fields"]["required_fields"][0] == "attenuation_handle"
    assert "when_status_is_ambiguous_stop_only" in next_action["object_binding"]["result_validation_rule"]
    assert client.calls[-1] == (
        "ak.wwise.core.object.get", {"from": {scope: [ATTENUATION_ROW[scope]]}},
        {"return": ["id", "name", "type", "path", "classId"]},
    )


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("damage", ("wrong_id", "missing_id", "duplicate", "missing_row", "missing_name", "missing_path", "wrong_path", "missing_class", "wrong_class", "wrong_role", "missing_role", "version_drift", "missing_version"))
def test_attenuation_role_classification_never_certifies_invalid_binding(version, damage, tmp_path):
    env, state, started, info = _core_role_binding_case(tmp_path, version)
    row = dict(ATTENUATION_ROW)
    rows = [row]
    role = "attenuation"
    selector = None
    if damage == "wrong_id": row["id"] = TARGET_ID
    elif damage == "missing_id": row.pop("id")
    elif damage == "duplicate": rows.append(dict(row))
    elif damage == "missing_row": rows.clear()
    elif damage == "missing_name": row.pop("name")
    elif damage == "missing_path": row.pop("path")
    elif damage == "wrong_path":
        selector = [token for name in ("Attenuations", "Default Work Unit", ATTENUATION_ROW["name"])
                    for token in ("--object-path-segment", name)]
        row["path"] = r"\Attenuations\Default Work Unit\AnotherAttenuation"
    elif damage == "missing_class": row.pop("type")
    elif damage == "wrong_class": row["type"] = "Sound"
    elif damage == "wrong_role": role = "object"
    elif damage == "missing_role": role = None
    elif damage == "missing_version": info.pop("version")
    else:
        actual = "2022.1" if version == "2021.1" else "2021.1"
        info["version"]["year"] = int(actual.split(".")[0])
        info["version"]["displayName"] = f"v{actual}.0.1"
    code, rejected, client = _bind_core_role(env, state, started, info, tmp_path, rows, role=role, selector=selector)
    assert code == 2, rejected
    assert rejected["ok"] is False
    assert "bound_object" not in rejected
    assert all(call[0] != ATTENUATION_URI for call in client.calls)
    inspect_code, inspected = gateway.execute_gateway([
        "--state-dir", str(state), "draft-inspect", started["draft"]["draft_id"],
        "--task-authority", started["task_authority"],
    ], env=env, client_factory=lambda _url: pytest.fail("inspect must remain offline"))
    assert inspect_code == 0, inspected
    assert inspected["draft"]["revision"] == 1
    assert "boh1-" not in json.dumps(inspected)


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_attenuation_live_class_is_not_a_global_business_or_creatable_kind(version, tmp_path):
    env, state, started, info = _core_role_binding_case(
        tmp_path, version, operation="ak.wwise.core.object.setRandomizer",
    )
    code, bound, _client = _bind_core_role(env, state, started, info, tmp_path, [dict(ATTENUATION_ROW)], role="object")
    assert code == 0, bound
    assert bound["bound_object"]["business_kind"] is None
    assert bound["bound_object"]["business_kind_resolution"] == {
        "status": "ambiguous", "candidates": [], "reflected_type": "Attenuation",
    }
    assert "when_status_is_ambiguous_stop_only" in bound["draft"]["next_action_binding"]["object_binding"]["result_validation_rule"]


@pytest.mark.parametrize("version", ("2020.1", "2026.1"))
def test_attenuation_role_contract_is_unavailable_outside_pinned_versions(version, tmp_path):
    env = _env(tmp_path)
    set_gateway_config(env, wwise_version=version)
    code, rejected = gateway.execute_gateway(["draft-start", ATTENUATION_URI], env=env,
        client_factory=lambda _url: pytest.fail("unsupported version must fail offline"))
    assert code == 2, rejected
    assert rejected["ok"] is False
    assert "draft" not in rejected


class _BlendAssignmentTask:
    """Existing public Draft lifecycle with a stateful external WAAPI boundary."""
    uri = "ak.wwise.core.blendContainer.addAssignment"
    getter = "ak.wwise.core.blendContainer.getAssignments"
    track = "{33333333-3333-3333-3333-333333333333}"
    owner = "{44444444-4444-4444-4444-444444444444}"
    first = "{55555555-5555-5555-5555-555555555555}"
    second = "{66666666-6666-6666-6666-666666666666}"

    def __init__(self, tmp_path, version):
        from copy import deepcopy
        self.clone = deepcopy
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.env = _env(tmp_path)
        set_gateway_config(self.env, wwise_version=version)
        self.info = _info()
        self.info["version"]["year"] = int(version[:4])
        self.project = _project(tmp_path)
        base = r"\Containers\Default Work Unit\Weather"
        self.objects = {
            self.track: {"id": self.track, "name": "Weather", "type": "BlendTrack", "path": "Weather"},
            TARGET_ID: {"id": TARGET_ID, "name": "Rain", "type": "Sound", "path": base + r"\Rain", "parent": {"id": self.owner}},
            self.owner: {"id": self.owner, "name": "Weather", "type": "BlendContainer", "path": base,
                         "blendTracks": [{"id": self.track, "name": "Weather"}]},
        }
        self.assignments = [{"child": child, "index": index, "edges": self.edges(index * 10)}
                            for index, child in enumerate((self.first, self.second))]
        self.calls = []
        self.prefix = ["--state-dir", str(tmp_path / "state")]
        started = self.run("draft-start", self.uri)
        self.draft = started["draft"]
        self.binding = [self.draft["draft_id"], "--task-authority", started["task_authority"]]
        track = self.step("draft-bind-object", "--role", "blend_track", "--object-id", self.track)["bound_object"]["handle"]
        child = self.step("draft-bind-object", "--role", "child", "--object-id", TARGET_ID)["bound_object"]["handle"]
        self.handles = ["--role", "blend_track_handle", track, "--role", "child_handle", child]

    @staticmethod
    def edges(position):
        return [{"edgePosition": position, "fadeMode": "None", "fadeShape": "Linear"},
                {"edgePosition": position + 5, "fadeMode": "None", "fadeShape": "Linear"}]

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, self.clone(args), self.clone(options)))
        if uri == "ak.wwise.core.getInfo":
            return self.clone(self.info)
        if uri == "ak.wwise.core.getProjectInfo":
            return self.clone(self.project)
        if uri == "ak.wwise.core.object.get":
            return {"return": [self.clone(self.objects[identity]) for identity in args["from"]["id"] if identity in self.objects]}
        if uri == self.getter:
            return {"return": self.clone(self.assignments)}
        if uri == self.uri:
            retained = next((item for item in self.assignments if item["child"] == args["child"]), None)
            if retained is not None:
                # An admitted outcome for the deliberately unpredicted duplicate lane.
                return self.clone(retained)
            row = {"child": args["child"], "edges": self.clone(args.get("edges", self.edges(0)))}
            position = max(0, min(args.get("index", len(self.assignments)), len(self.assignments)))
            self.assignments.insert(position, row)
            for index, item in enumerate(self.assignments):
                item["index"] = index
            return self.clone(row)
        raise AssertionError((uri, args, options))

    def disconnect(self):
        pass

    def raw(self, *argv):
        return gateway.execute_gateway([*self.prefix, *argv], env=self.env, client_factory=lambda _: self)

    def run(self, *argv):
        code, result = self.raw(*argv)
        assert code == 0, result
        return result

    def step(self, command, *argv):
        result = self.run(command, *self.binding, "--expected-revision", str(self.draft["revision"]), *argv)
        self.draft = result.get("draft", self.draft)
        return result

    def preview(self, index=None, *, edges=False):
        self.step("draft-declare-core-plan", *self.handles,
            *([] if index is None else ["--value", "insertion_index", str(index)]),
            *(["--blend-edge", "0", "none", "none", "linear", "--blend-edge", "5", "none", "none", "linear"] if edges else []))
        self.step("draft-check")
        preview = self.step("preview-from-draft")
        self.tx = preview["transaction_id"]
        self.shown = self.run("transaction-show", self.tx)
        self.artifact = self.shown["artifact"]["prepared_operation"]
        return preview

    def execute(self):
        self.run("confirm", self.tx, "--confirmation-token", self.shown["confirmation"]["token"])
        return self.raw("execute", self.tx)


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_blend_assignment_negative_index_preview_and_independent_order(tmp_path, version):
    task = _BlendAssignmentTask(tmp_path, version)
    preview = task.preview(-9)
    assert preview["preview_summary"]["blend_assignment"]["expected_position"] == 0
    assert task.artifact["verification_plan"]["expected_order"] == [TARGET_ID, task.first, task.second]
    assert task.execute()[0] == 0
    result = task.run("verify", task.tx)
    assert result["verification"]["business_state_verified"] is True
    assert [row["child"] for row in task.assignments] == [TARGET_ID, task.first, task.second]
    assert sum(uri == task.uri for uri, _, _ in task.calls) == 1


def test_blend_assignment_null_observation_blocks_preview(tmp_path):
    task = _BlendAssignmentTask(tmp_path, "2024.1")
    task.assignments[0]["child"] = "{00000000-0000-0000-0000-000000000000}"
    task.step("draft-declare-core-plan", *task.handles, "--value", "insertion_index", "-9")
    code, result = task.raw("draft-check", *task.binding, "--expected-revision", str(task.draft["revision"]))
    assert code != 0
    assert "INVALID_BLEND_ASSIGNMENT_OBSERVATION" in json.dumps(result)
    assert not any(uri == task.uri for uri, _, _ in task.calls)


@pytest.mark.parametrize("damage", ["assignment-null", "owner-null", "owner-malformed-guid"])
@pytest.mark.parametrize("phase", ["preview", "prewrite", "postwrite"])
def test_blend_assignment_invalid_member_observations_fail_closed(tmp_path, damage, phase):
    task = _BlendAssignmentTask(tmp_path, "2024.1")
    if phase != "preview":
        task.preview(-9)
    if phase == "postwrite":
        assert task.execute()[0] == 0
    null = "{00000000-0000-0000-0000-000000000000}"
    if damage == "assignment-null":
        task.assignments[-1]["child"] = null
    else:
        identity = null if damage == "owner-null" else "{1234567-81234-1234-1234-123456789ABC}"
        task.objects[task.owner]["blendTracks"].append({"id": identity})
    if phase == "preview":
        task.step("draft-declare-core-plan", *task.handles, "--value", "insertion_index", "-9")
        code, result = task.raw("draft-check", *task.binding, "--expected-revision", str(task.draft["revision"]))
        assert code == 2 and "INVALID_BLEND_ASSIGNMENT_OBSERVATION" in json.dumps(result), result
    elif phase == "prewrite":
        code, result = task.execute()
        assert code == 2 and "STALE_BLEND_ASSIGNMENT" in json.dumps(result), result
    else:
        code, result = task.raw("verify", task.tx)
        assert code == 2 and result["verified"] is False, result
        assert result["verification"]["business_state_verified"] is False
        assert task.raw("execute", task.tx)[0] == 2
    assert sum(uri == task.uri for uri, _, _ in task.calls) == (1 if phase == "postwrite" else 0)


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_blend_assignment_valid_mixedcase_member_observations_remain_accepted(tmp_path, version):
    task = _BlendAssignmentTask(tmp_path, version)
    task.assignments[0]["child"] = "{aBcDeFaB-1234-5678-9AbC-aBcDeF123456}"
    task.objects[task.owner]["blendTracks"].append({"id": "{BcDeFaBc-2345-6789-aBcD-bCdEfA234567}"})
    task.preview(-9)
    assert task.artifact["verification_plan"]["expected_order"] == [
        TARGET_ID, "{ABCDEFAB-1234-5678-9ABC-ABCDEF123456}", task.second]
    assert task.execute()[0] == 0
    result = task.run("verify", task.tx)
    assert result["verification"]["business_state_verified"] is True
    assert sum(uri == task.uri for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize(("index", "expected"), [(None, 2), (0, 0), (1, 1), (99, 2)])
def test_blend_assignment_documented_positions_and_retained_edges(tmp_path, version, index, expected):
    task = _BlendAssignmentTask(tmp_path, version)
    original = task.clone(task.assignments)
    preview = task.preview(index)
    assert preview["preview_summary"]["blend_assignment"]["expected_position"] == expected
    assert task.execute()[0] == 0
    verified = task.run("verify", task.tx)["verification"]
    assert verified["business_state_verified"] is True
    assert task.assignments[expected]["child"] == TARGET_ID
    retained = {row["child"]: row["edges"] for row in task.assignments if row["child"] != TARGET_ID}
    assert retained == {row["child"]: row["edges"] for row in original}
    assert verified["verification_scope"]["default_edge_geometry_promised"] is False


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_blend_assignment_empty_and_explicit_indices_own_order(tmp_path, version):
    task = _BlendAssignmentTask(tmp_path, version)
    # Native array transport order is not inferred assignment order.
    task.assignments.reverse()
    task.preview(1)
    assert task.artifact["verification_plan"]["expected_order"] == [task.first, TARGET_ID, task.second]
    task.assignments.reverse()  # Same explicit indices, different transport array order.
    assert task.execute()[0] == 0
    assert task.run("verify", task.tx)["verification"]["business_state_verified"] is True
    other = _BlendAssignmentTask(tmp_path / "empty", version)
    other.assignments = []
    assert other.preview(-1)["preview_summary"]["blend_assignment"]["expected_position"] == 0
    assert other.execute()[0] == 0
    assert other.run("verify", other.tx)["verification"]["business_state_verified"] is True


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize("kind", ["edge", "reassignment", "missing-observed-edges"])
def test_blend_assignment_existing_admitted_lanes_keep_truthful_weak_result(tmp_path, version, kind):
    task = _BlendAssignmentTask(tmp_path, version)
    if kind == "reassignment":
        task.assignments[0]["child"] = TARGET_ID
    if kind == "missing-observed-edges":
        task.assignments[0].pop("edges")
    preview = task.preview(1, edges=kind == "edge")
    assert preview["preview_summary"]["blend_assignment"]["verification_scope"]["unobserved"]
    assert task.execute()[0] == 0
    result = task.run("verify", task.tx)
    assert result["verification"]["business_state_verified"] is False
    assert result["verification"]["status"] == "result_schema_checked"
    assert result["verification"]["verification_strength"] == "blend_assignment_partial_observation"
    assert sum(uri == task.uri for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize("damage", ["order", "edge", "parent", "owner-track", "track-name", "missing-index", "extra"])
def test_blend_assignment_prewrite_snapshot_drift_never_dispatches(tmp_path, version, damage):
    task = _BlendAssignmentTask(tmp_path, version)
    task.preview(-3)
    if damage == "order":
        task.assignments[0]["index"], task.assignments[1]["index"] = 1, 0
    elif damage == "edge":
        task.assignments[0]["edges"][0]["edgePosition"] = -0.5
    elif damage == "parent":
        task.objects[TARGET_ID]["parent"] = {"id": PROJECT_ID}
    elif damage == "owner-track":
        task.objects[task.owner]["blendTracks"] = []
    elif damage == "track-name":
        task.objects[task.track]["name"] = "Changed"
    elif damage == "missing-index":
        task.assignments[0].pop("index")
    else:
        task.assignments.append({"child": SOURCE_ID, "index": 2})
    code, result = task.execute()
    assert code == 2, result
    assert all(uri != task.uri for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize("damage", ["order", "edge", "parent", "missing-index", "extra", "missing-target"])
def test_blend_assignment_independent_post_read_catches_partial_effects(tmp_path, version, damage):
    task = _BlendAssignmentTask(tmp_path, version)
    task.preview(-4)
    assert task.execute()[0] == 0
    if damage == "order":
        task.assignments[0]["index"], task.assignments[1]["index"] = 1, 0
    elif damage == "edge":
        task.assignments[1]["edges"][0]["edgePosition"] = 99
    elif damage == "parent":
        task.objects[TARGET_ID]["parent"] = {"id": PROJECT_ID}
    elif damage == "missing-index":
        task.assignments[1].pop("index")
    elif damage == "missing-target":
        task.assignments.pop(0)
        for i, row in enumerate(task.assignments):
            row["index"] = i
    else:
        task.assignments.append({"child": SOURCE_ID, "index": 3})
    code, result = task.raw("verify", task.tx)
    assert code == 2 and result["verified"] is False, result
    assert result["verification"]["business_state_verified"] is False
    assert sum(uri == task.uri for uri, _, _ in task.calls) == 1
    replay_code, replay = task.raw("execute", task.tx)
    assert replay_code == 2, replay
    assert sum(uri == task.uri for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize("damage", ["index", "duplicate-index", "duplicate-child", "wrong-owner", "wrong-track-type"])
def test_blend_assignment_missing_material_facts_are_not_guessed(tmp_path, version, damage):
    task = _BlendAssignmentTask(tmp_path, version)
    if damage == "index":
        task.assignments[0].pop("index")
    elif damage == "duplicate-index":
        task.assignments[1]["index"] = 0
    elif damage == "duplicate-child":
        task.assignments[1]["child"] = task.first
    elif damage == "wrong-owner":
        task.objects[task.owner]["type"] = "ActorMixer"
    else:
        task.objects[task.track]["type"] = "Sound"
    task.step("draft-declare-core-plan", *task.handles, "--value", "insertion_index", "-2")
    code, result = task.raw("draft-check", *task.binding, "--expected-revision", str(task.draft["revision"]))
    if code == 0:
        task.draft = result["draft"]
        code, result = task.raw("preview-from-draft", *task.binding, "--expected-revision", str(task.draft["revision"]))
        assert result["error_code"] == "INVALID_BLEND_ASSIGNMENT_OBSERVATION", result
    if damage == "wrong-track-type":
        assert result["error_code"] in {"OBJECT_READBACK_INVALID"}, result
    else:
        assert result["error_code"] == "INVALID_BLEND_ASSIGNMENT_OBSERVATION", result
    assert code == 2, result
    assert all(uri != task.uri for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_blend_assignment_configuration_drift_is_still_prewrite_blocked(tmp_path, version):
    task = _BlendAssignmentTask(tmp_path, version)
    task.preview(-2)
    set_gateway_config(task.env, waapi_port=31338)
    code, result = task.raw("confirm", task.tx, "--confirmation-token", task.shown["confirmation"]["token"])
    assert code == 2, result
    assert all(uri != task.uri for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize("damage", ["wrong-type", "different-path", "noncanonical-id", "type-name-selector"])
def test_blend_assignment_relative_track_identity_is_guid_comparison_only(tmp_path, version, damage):
    task = _BlendAssignmentTask(tmp_path, version)
    started = task.run("draft-start", task.uri)
    binding = [started["draft"]["draft_id"], "--task-authority", started["task_authority"], "--expected-revision", "1", "--role", "blend_track"]
    if damage == "wrong-type":
        task.objects[task.track]["type"] = "Sound"
    elif damage == "different-path":
        task.objects[task.track]["path"] = "Another"
    elif damage == "noncanonical-id":
        task.objects[task.track]["id"] = task.track.strip("{}")
    else:
        # Exact type/name resolution still must not promote display text to a selector.
        original_call = task.call
        def selector_call(uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get" and "waql" in args:
                return {"return": [task.clone(task.objects[task.track])]}
            return original_call(uri, args, options)
        task.call = selector_call
    selector = (["--exact-type-name", "BlendTrack", "Weather"]
                if damage == "type-name-selector" else ["--object-id", task.track])
    code, result = task.raw("draft-bind-object", *binding, *selector)
    assert code == 2, result
    assert all(uri != task.uri for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize("index", ["true", "1.5", "NaN"])
def test_blend_assignment_index_requires_an_integer(tmp_path, version, index):
    task = _BlendAssignmentTask(tmp_path, version)
    code, result = task.raw("draft-declare-core-plan", *task.binding,
        "--expected-revision", str(task.draft["revision"]), *task.handles,
        "--value", "insertion_index", index)
    assert code == 2, result
    assert all(uri != task.uri for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_blend_assignment_schema_discloses_clamping_and_edge_effect_boundary(tmp_path, version):
    env = _env(tmp_path)
    set_gateway_config(env, wwise_version=version)
    code, result = gateway.execute_gateway(["request-schema", _BlendAssignmentTask.uri], env=env,
        client_factory=lambda _: pytest.fail("schema discovery must be offline"))
    assert code == 0, result
    declaration = result["business_adapter"]["declaration"]
    assert declaration["field_types"]["insertion_index"] == "integer_clamped_to_assignment_count"
    assert declaration["field_semantics"]["insertion_index"]["input"] == "integer_including_negative"
    assert declaration["field_semantics"]["insertion_index"]["omitted_effect"] == "append"
    assert declaration["field_semantics"]["edges"]["effect_scope"] == "crossfade_GameParameter_only"
    assert "unproved" in declaration["field_semantics"]["edges"]["verification_boundary"]


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize(("requested", "effective"), [(-9, 0), (99, 2)])
def test_blend_assignment_materializes_documented_clamp_in_immutable_native_envelope(tmp_path, version, requested, effective):
    task = _BlendAssignmentTask(tmp_path, version)
    native = task.call
    received = []
    def observed_negative_append(uri, args=None, options=None):
        if uri == task.uri:
            received.append(dict(args))
            # Exact 2024 native observation: a raw negative index appended.
            # The shared fake must not hide missing Gateway materialization.
            if args.get("index", 0) < 0:
                args = {**args, "index": 99}
        return native(uri, args, options)
    task.call = observed_negative_append
    preview = task.preview(requested)
    assert preview["preview_summary"]["blend_assignment"]["requested_index"] == requested
    assert task.artifact["dispatch"]["args"]["index"] == effective
    assert task.artifact["semantic_preview"]["envelope"]["args"]["index"] == effective
    assert task.artifact["request"]["arguments"]["args"]["index"] == requested
    code, executed = task.execute()
    assert code == 0, json.dumps({key: executed.get(key) for key in ("error_code", "message", "details")})
    code, verified = task.raw("verify", task.tx)
    assert code == 0, json.dumps({key: verified.get(key) for key in ("error_code", "message", "details", "verification")})
    assert verified["verification"]["business_state_verified"] is True
    assert len(received) == 1 and received[0]["index"] == effective


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_blend_automatic_neighbor_geometry_remains_disclosed_partial_observation(tmp_path, version):
    task = _BlendAssignmentTask(tmp_path, version)
    task.assignments[1]["edges"][1].update(
        fadeMode="Automatic", edgePosition=15, fadePosition=20,
    )
    preview = task.preview()
    scope = preview["preview_summary"]["blend_assignment"]["verification_scope"]
    assert "automatic_non_target_edge_geometry" in scope["unobserved"]
    assert task.execute()[0] == 0
    # R90 retained fact: appending can adjust the preceding Automatic right edge.
    task.assignments[1]["edges"][1].update(edgePosition=25, fadePosition=30)
    result = task.run("verify", task.tx)["verification"]
    assert result["status"] == "result_schema_checked"
    assert result["business_state_verified"] is False
    assert result["verification_strength"] == "blend_assignment_partial_observation"


@pytest.mark.parametrize("damage", ["mode", "shape", "opposite-manual", "unrelated-automatic"])
def test_blend_automatic_neighbor_does_not_waive_stable_or_unrelated_fields(tmp_path, damage):
    task = _BlendAssignmentTask(tmp_path, "2024.1")
    task.assignments[1]["edges"][1]["fadeMode"] = "Automatic"
    task.assignments[1]["edges"][0].update(fadeMode="Manual", fadePosition=12)
    task.assignments[0]["edges"][1]["fadeMode"] = "Automatic"
    task.preview()
    assert task.execute()[0] == 0
    if damage == "mode":
        task.assignments[1]["edges"][1]["fadeMode"] = "None"
    elif damage == "shape":
        task.assignments[1]["edges"][1]["fadeShape"] = "Sine"
    elif damage == "opposite-manual":
        task.assignments[1]["edges"][0]["fadePosition"] = 13
    else:
        task.assignments[0]["edges"][1]["edgePosition"] = 6
    code, result = task.raw("verify", task.tx)
    assert code == 2 and result["verified"] is False, result
    assert result["verification"]["business_state_verified"] is False


class _StateReplacementTask:
    """Public Core mutation flow with one external object and result-only setter."""
    def __init__(self, tmp_path, version, suffix):
        self.uri = "ak.wwise.core.object." + suffix
        self.env = _env(tmp_path)
        set_gateway_config(self.env, wwise_version=version)
        self.info = _info()
        self.info["version"]["year"] = int(version[:4])
        self.project = _project(tmp_path)
        self.object = {"id": SOURCE_ID, "name": "Alarm", "type": "Sound",
                       "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Alarm"}
        self.calls = []
        self.prefix = ["--state-dir", str(tmp_path / "state")]
        started = self.run("draft-start", self.uri)
        self.draft = started["draft"]
        self.binding = [self.draft["draft_id"], "--task-authority", started["task_authority"]]
        self.handle = self.step("draft-bind-object", "--role", "object", "--object-id", SOURCE_ID)["bound_object"]["handle"]

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            return self.info
        if uri == "ak.wwise.core.getProjectInfo":
            return self.project
        if uri == "ak.wwise.core.object.get":
            return {"return": [dict(self.object)]}
        if uri == self.uri:
            return {}
        raise AssertionError((uri, args, options))

    disconnect = _BlendAssignmentTask.disconnect
    raw = _BlendAssignmentTask.raw
    run = _BlendAssignmentTask.run
    step = _BlendAssignmentTask.step


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize(("suffix", "field", "native"), [
    ("setStateGroups", "state_group_handles", "stateGroups"),
    ("setStateProperties", "field_handles", "stateProperties"),
])
def test_state_replacement_explicit_empty_is_callable_and_result_only(tmp_path, version, suffix, field, native):
    task = _StateReplacementTask(tmp_path, version, suffix)
    schema = task.run("request-schema", task.uri)["business_adapter"]["declaration"]
    assert schema["input_forms"][field]["empty"] == {"flag": "--empty", "arguments": [field]}
    task.step("draft-declare-core-plan", "--role", "object_handle", task.handle, "--empty", field)
    task.step("draft-check")
    preview = task.step("preview-from-draft")
    task.tx = preview["transaction_id"]
    task.shown = task.run("transaction-show", task.tx)
    assert task.shown["artifact"]["prepared_operation"]["dispatch"]["args"] == {"object": SOURCE_ID, native: []}
    task.run("confirm", task.tx, "--confirmation-token", task.shown["confirmation"]["token"])
    task.run("execute", task.tx)
    verified = task.run("verify", task.tx)["verification"]
    assert verified["status"] == "result_schema_checked"
    assert verified["business_state_verified"] is False
    assert sum(uri == task.uri for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("kind", ["mixed-items", "repeated-empty", "wrong-field"])
def test_state_empty_declaration_rejects_conflicts_atomically(tmp_path, kind):
    task = _StateReplacementTask(tmp_path, "2025.1", "setStateGroups")
    extra = {
        "mixed-items": ["--role", "state_group_handles", task.handle],
        "repeated-empty": ["--empty", "state_group_handles"],
        "wrong-field": ["--empty", "object_handle"],
    }[kind]
    code, result = task.raw("draft-declare-core-plan", *task.binding,
        "--expected-revision", str(task.draft["revision"]),
        "--role", "object_handle", task.handle, "--empty", "state_group_handles", *extra)
    assert code == 2, result
    # The unchanged revision remains usable after invalid input.
    task.step("draft-declare-core-plan", "--role", "object_handle", task.handle,
              "--empty", "state_group_handles")
    task.step("draft-check")
    assert all(uri != task.uri for uri, _, _ in task.calls)


class _PasteSelectionTask:
    uri = "ak.wwise.core.object.pasteProperties"

    def __init__(self, tmp_path, version):
        self.env = _env(tmp_path)
        set_gateway_config(self.env, wwise_version=version)
        self.info = _info()
        self.info["version"]["year"] = int(version[:4])
        self.project = _project(tmp_path)
        self.objects = {identity: {"id": identity, "name": name, "type": "Sound",
                        "path": "\\Actor-Mixer Hierarchy\\Default Work Unit\\" + name}
                        for identity, name in ((SOURCE_ID, "Source"), (TARGET_ID, "Target"))}
        self.calls = []
        self.prefix = ["--state-dir", str(tmp_path / "state")]
        started = self.run("draft-start", self.uri)
        self.draft = started["draft"]
        self.binding = [self.draft["draft_id"], "--task-authority", started["task_authority"]]
        self.source = self.step("draft-bind-object", "--role", "source", "--object-id", SOURCE_ID)["bound_object"]["handle"]
        self.target = self.step("draft-bind-object", "--role", "target", "--object-id", TARGET_ID)["bound_object"]["handle"]
        self.fields = self.discover(self.source)

    def discover(self, handle):
        discovered = self.step("draft-discover-fields", "--object-handle", handle,
                               "--meaning", "volume", "--meaning", "pitch")
        return {row["label"]: row["handle"] for row in discovered["field_candidates"]}

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            return self.info
        if uri == "ak.wwise.core.getProjectInfo":
            return self.project
        if uri == "ak.wwise.core.object.get":
            return {"return": [dict(self.objects[identity]) for identity in args["from"]["id"]]}
        if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            return {"return": ["Volume", "Pitch"]}
        if uri == "ak.wwise.core.object.getPropertyInfo":
            name = args["property"]
            return {"name": name, "type": "Real32", "display": {"name": name, "group": "General"},
                    "restriction": {"type": "range", "min": -96, "max": 96}}
        if uri == self.uri:
            return {}
        raise AssertionError((uri, args, options))

    disconnect = _BlendAssignmentTask.disconnect
    raw = _BlendAssignmentTask.raw
    run = _BlendAssignmentTask.run
    step = _BlendAssignmentTask.step

    def declare(self, fields=None):
        fields = self.fields if fields is None else fields
        return self.step("draft-declare-core-plan", "--role", "source_handle", self.source,
            "--role", "target_handles", self.target,
            "--field", "include_field_handles", fields["Volume"],
            "--field", "exclude_field_handles", fields["Pitch"])


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_paste_accepts_both_documented_lists_without_claiming_combined_effect(tmp_path, version):
    task = _PasteSelectionTask(tmp_path, version)
    task.declare()
    task.step("draft-check")
    preview = task.step("preview-from-draft")
    assert "combined inclusion/exclusion effect remains unverified" in json.dumps(preview).lower()
    transaction = preview["transaction_id"]
    shown = task.run("transaction-show", transaction)
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"] == {
        "source": SOURCE_ID, "targets": [TARGET_ID], "inclusion": ["Volume"], "exclusion": ["Pitch"],
    }
    task.run("confirm", transaction, "--confirmation-token", shown["confirmation"]["token"])
    task.run("execute", transaction)
    verified = task.run("verify", transaction)["verification"]
    assert verified["status"] == "result_schema_checked" and verified["business_state_verified"] is False
    assert sum(uri == task.uri for uri, _, _ in task.calls) == 1


def test_paste_combined_selection_still_requires_source_scoped_fields(tmp_path):
    task = _PasteSelectionTask(tmp_path, "2025.1")
    foreign_fields = task.discover(task.target)
    code, result = task.raw("draft-declare-core-plan", *task.binding,
        "--expected-revision", str(task.draft["revision"]),
        "--role", "source_handle", task.source, "--role", "target_handles", task.target,
        "--field", "include_field_handles", task.fields["Volume"],
        "--field", "exclude_field_handles", foreign_fields["Pitch"])
    assert code == 2 and result["error_code"] == "FIELD_HANDLE_SCOPE_MISMATCH", result
    task.declare()
    assert all(uri != task.uri for uri, _, _ in task.calls)
