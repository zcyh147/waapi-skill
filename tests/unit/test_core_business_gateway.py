from __future__ import annotations

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


def test_project_save_keeps_its_zero_input_route_before_business_fields_exist(
    tmp_path: Path,
) -> None:
    operation = "ak.wwise.core.project.save"

    exit_code, payload = gateway.execute_gateway(
        ["--version", "2022.1", "request-schema", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert exit_code == 0, payload
    assert payload["contract"] == "waapi-skill.typed-request-schema/v1"
    assert payload["input_shape"] == "zero"
    assert payload["continuation"]["gateway_argv"] == [
        "typed-zero-call",
        operation,
        "--schema-digest",
        payload["schema_digest"],
        "--apply",
    ]


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
                "arguments": ["FIELD", "VALUE"],
            }
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
    env["WWISE_WAAPI_HOST"] = "127.0.0.1"
    env["WWISE_WAAPI_PORT"] = "31337"

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
    env["WWISE_WAAPI_HOST"] = "127.0.0.1"
    env["WWISE_WAAPI_PORT"] = "31337"

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
    env["WWISE_WAAPI_HOST"] = "127.0.0.1"
    env["WWISE_WAAPI_PORT"] = "31337"

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
    env["WWISE_WAAPI_HOST"] = "127.0.0.1"
    env["WWISE_WAAPI_PORT"] = "31337"

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
    env["WWISE_WAAPI_HOST"] = "127.0.0.1"
    env["WWISE_WAAPI_PORT"] = "31337"
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
    env["WWISE_WAAPI_HOST"] = "127.0.0.1"
    env["WWISE_WAAPI_PORT"] = "31337"
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
            "audio_object",
            "--object-id",
            SOURCE_ID,
        ],
        env=env,
        client_factory=lambda _url: bind_client,
    )
    assert bind_code == 0, bound
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
    env["WWISE_WAAPI_HOST"] = "127.0.0.1"
    env["WWISE_WAAPI_PORT"] = "31337"
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
