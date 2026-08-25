from __future__ import annotations

import importlib.util
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.operation_drafts import OperationDraftStore


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_switch_assignment_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
CONTAINER_ID = "{11111111-1111-1111-1111-111111111111}"
CHILD_ID = "{22222222-2222-2222-2222-222222222222}"
VALUE_ID = "{33333333-3333-3333-3333-333333333333}"


class FakeClient:
    def __init__(self, responses: Mapping[str, Sequence[Any]]) -> None:
        self.responses = {
            uri: deque(values) for uri, values in responses.items()
        }

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        values = self.responses.get(uri)
        if not values:
            raise AssertionError(
                f"Unexpected WAAPI call: {uri} {args!r} {options!r}"
            )
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
        "WWISE_VERSION": "2025.1",
    }


def _project(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / "project" / "SampleProject.wproj"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<Project />\n", encoding="utf-8")
    return {"id": PROJECT_ID, "name": "SampleProject", "path": str(path)}


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


def _offline(tmp_path: Path, *argv: str) -> tuple[int, dict[str, Any]]:
    return gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *argv],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline command connected to {url}"),
    )


def _bind(
    tmp_path: Path,
    *,
    draft_id: str,
    authority: str,
    revision: int,
    object_id: str,
    name: str,
    object_type: str,
    path: str,
) -> dict[str, Any]:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": object_id,
                            "name": name,
                            "type": object_type,
                            "path": path,
                        }
                    ]
                }
            ],
        }
    )
    code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--object-id",
            object_id,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, payload
    return payload


@pytest.mark.parametrize(
    "operation",
    (
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
    ),
)
def test_gateway_binds_three_roles_then_materializes_assignment(
    tmp_path: Path,
    operation: str,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", operation)
    assert start_code == 0, started
    assert started["draft"]["allowed_actions"] == ["bind-object"]
    assert "typed_operation" not in started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    container = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=1,
        object_id=CONTAINER_ID,
        name="Footsteps",
        object_type="SwitchContainer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps",
    )
    child = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=2,
        object_id=CHILD_ID,
        name="Snow_Step",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps\Snow_Step",
    )
    value = _bind(
        tmp_path,
        draft_id=draft_id,
        authority=authority,
        revision=3,
        object_id=VALUE_ID,
        name="Snow",
        object_type="Switch",
        path=r"\Switches\Default Work Unit\Surface\Snow",
    )
    binding = value["draft"]["next_action_binding"]
    assert binding["required_next_phase"] == (
        "declare_complete_switch_assignment"
    )
    declaration = binding["declaration"]
    assert declaration["append"] == [
        "--switch-container-handle",
        "<bound-switch-container-handle>",
        "--child-handle",
        "<bound-child-handle>",
        "--state-or-switch-handle",
        "<bound-state-or-switch-handle>",
    ]
    declaration_text = json.dumps(declaration).casefold()
    assert "direct-child" not in declaration_text
    assert "scoped-name" not in declaration_text

    declare_code, declared = _offline(
        tmp_path,
        "draft-declare-switch-assignment",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--switch-container-handle",
        container["bound_object"]["handle"],
        "--child-handle",
        child["bound_object"]["handle"],
        "--state-or-switch-handle",
        value["bound_object"]["handle"],
    )
    assert declare_code == 0, declared
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_business_declaration"
    )

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=5,
        schema_digest=gateway.operation_draft_schema_digest(
            operation,
            "2025.1",
        ),
        composer_digest=operation_composer_digest(operation, "2025.1"),
    )
    assert materialized.request["arguments"] == {
        "switch_container": {"kind": "id", "value": CONTAINER_ID},
        "child": {"kind": "id", "value": CHILD_ID},
        "state_or_switch": {"kind": "id", "value": VALUE_ID},
    }


@pytest.mark.parametrize("version", ("2021.1", "2025.1"))
@pytest.mark.parametrize(
    "operation",
    (
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
    ),
)
def test_operation_schema_exposes_only_switch_assignment_business_adapter(
    tmp_path: Path,
    version: str,
    operation: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )

    assert code == 0, payload
    assert payload["operation"]["input_mode"] == "business_declaration"
    assert payload["business_adapter"]["contract"] == (
        "waapi-skill.switch-assignment-business/v1"
    )
    assert payload["business_adapter"]["legacy_inline_typed_public"] is False
    assert "typed_operation" not in payload
