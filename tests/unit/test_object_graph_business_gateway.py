from __future__ import annotations

import importlib.util
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

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
    "waapi_object_graph_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
PARENT_ID = "{11111111-1111-1111-1111-111111111111}"
CONTROL_ID = "{22222222-2222-2222-2222-222222222222}"


class FakeClient:
    def __init__(self, responses: Mapping[str, Sequence[Any]]) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
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
        client_factory=lambda url: (_ for _ in ()).throw(
            AssertionError(f"offline command connected to {url}")
        ),
    )


def _live_client(tmp_path: Path, extra: Mapping[str, Sequence[Any]]) -> FakeClient:
    return FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            **extra,
        }
    )


def test_gateway_discovers_long_tail_type_then_compiles_only_its_handle(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.create")
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    bind_client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Default Work Unit",
                            "type": "WorkUnit",
                            "path": r"\Events\Default Work Unit",
                        }
                    ]
                }
            ]
        },
    )
    bind_code, bound = gateway.execute_gateway(
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
    parent_handle = bound["bound_object"]["handle"]
    bind_next = bound["draft"]["next_action_binding"]
    assert bind_next["required_next_phase"] == (
        "declare_named_object_or_discover_long_tail_kind"
    )
    assert bind_next["type_discovery"]["native_type_input"] == "forbidden"
    assert "--token" not in json.dumps(bind_next)

    discover_client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {"classId": 3_276_960, "name": "Event", "type": "WObject"},
                        {"classId": 3_276_961, "name": "Action", "type": "WObject"},
                    ]
                }
            ]
        },
    )
    discover_code, discovered = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-discover-types",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "2",
            "--meaning",
            "event",
            "--role",
            "object",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: discover_client,
    )
    assert discover_code == 0, discovered
    assert discovered["type_candidates"] == [
        {
            "handle": discovered["type_candidates"][0]["handle"],
            "label": "Event",
            "role": "object",
            "matched_meanings": ["event"],
        }
    ]
    kind_handle = discovered["type_candidates"][0]["handle"]
    assert kind_handle.startswith("bth1-")
    assert "classId" not in json.dumps(discovered)
    discovered_next = discovered["draft"]["next_action_binding"]
    assert discovered_next["declaration"]["append"][7] == (
        "<stable-semantic-kind-or-selected-type-handle>"
    )

    declare_code, declared = _offline(
        tmp_path,
        "draft-declare-new",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--declaration-id",
        "weather-event",
        "--parent-handle",
        parent_handle,
        "--name",
        "Play_Weather",
        "--kind",
        kind_handle,
    )
    assert declare_code == 0, declared
    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=4,
        schema_digest=gateway.operation_draft_schema_digest(
            "object.create",
            "2025.1",
        ),
        composer_digest=operation_composer_digest(
            "object.create",
            "2025.1",
        ),
    )
    assert materialized.request["arguments"] == {
        "parent": {"kind": "id", "value": PARENT_ID},
        "type": "Event",
        "name": "Play_Weather",
    }


def test_gateway_builds_rtpc_curve_from_bound_business_facts(tmp_path: Path) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.setRTPC")
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    owner_client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Rain",
                            "type": "Sound",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
                        }
                    ]
                }
            ]
        },
    )
    owner_code, owner = gateway.execute_gateway(
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
        client_factory=lambda _url: owner_client,
    )
    assert owner_code == 0, owner
    owner_handle = owner["bound_object"]["handle"]
    assert owner["draft"]["next_action_binding"]["required_next_phase"] == (
        "discover_rtpc_property_for_bound_object"
    )

    discover_client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.getPropertyAndReferenceNames": [
                {"return": ["Volume"]},
                {"return": ["Volume"]},
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "display": {"name": "Volume", "group": "General"},
                    "restriction": {"type": "range", "min": -200, "max": 200},
                    "supports": {"rtpc": "Additive", "unlink": True},
                },
                {
                    "name": "Volume",
                    "type": "Real32",
                    "display": {"name": "Volume", "group": "General"},
                    "restriction": {"type": "range", "min": -200, "max": 200},
                    "supports": {"rtpc": "Additive", "unlink": True},
                },
            ],
        },
    )
    discover_code, discovered = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-discover-fields",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "2",
            "--object-handle",
            owner_handle,
            "--meaning",
            "volume",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: discover_client,
    )
    assert discover_code == 0, discovered
    field_handle = discovered["field_candidates"][0]["handle"]
    assert discovered["draft"]["next_action_binding"]["required_next_phase"] == (
        "bind_rtpc_control_input"
    )

    control_client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": CONTROL_ID,
                            "name": "Weather Intensity",
                            "type": "GameParameter",
                            "path": r"\Game Parameters\Default Work Unit\Weather Intensity",
                        }
                    ]
                }
            ]
        },
    )
    control_code, control = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "3",
            "--object-id",
            CONTROL_ID,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: control_client,
    )
    assert control_code == 0, control
    control_handle = control["bound_object"]["handle"]
    assert control["draft"]["next_action_binding"]["required_next_phase"] == (
        "declare_complete_rtpc_curve"
    )

    declare_code, declared = _offline(
        tmp_path,
        "draft-declare-rtpc",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--object-handle",
        owner_handle,
        "--field-handle",
        field_handle,
        "--control-input-handle",
        control_handle,
        "--point",
        "0",
        "-12",
        "Linear",
        "--point",
        "100",
        "0",
        "SCurve",
        "--notes",
        "Weather curve",
    )
    assert declare_code == 0, declared
    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=5,
        schema_digest=gateway.operation_draft_schema_digest(
            "object.setRTPC", "2025.1"
        ),
        composer_digest=operation_composer_digest(
            "object.setRTPC", "2025.1"
        ),
    )
    assert materialized.request["arguments"]["property"] == "Volume"
    assert materialized.request["arguments"]["points"] == [
        {"x": 0, "y": -12, "shape": "Linear"},
        {"x": 100, "y": 0, "shape": "SCurve"},
    ]


def test_gateway_compiles_object_create_settings_and_stable_fields(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.create")
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    def bind_object(
        *,
        revision: int,
        object_id: str,
        name: str,
        object_type: str,
        path: str,
    ) -> str:
        client = _live_client(
            tmp_path,
            {
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
                ]
            },
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
        return payload["bound_object"]["handle"]

    parent_handle = bind_object(
        revision=1,
        object_id=PARENT_ID,
        name="Default Work Unit",
        object_type="WorkUnit",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit",
    )
    bus_handle = bind_object(
        revision=2,
        object_id="{22222222-2222-2222-2222-222222222222}",
        name="Weather Bus",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Weather Bus",
    )
    configure_code, configured = _offline(
        tmp_path,
        "draft-business-configure",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--name-conflict",
        "fail",
        "--platform",
        "Windows",
        "--add-to-source-control",
    )
    assert configure_code == 0, configured
    declare_code, declared = _offline(
        tmp_path,
        "draft-declare-new",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--declaration-id",
        "rain",
        "--parent-handle",
        parent_handle,
        "--name",
        "Rain",
        "--kind",
        "sound-sfx",
        "--field",
        "loop",
        "infinite",
        "--field",
        "max_instances",
        "4",
        "--field",
        "output_bus",
        bus_handle,
        "--field",
        "override_parent_instance_limit",
        "true",
        "--field",
        "volume_db",
        "-4",
    )
    assert declare_code == 0, declared

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=5,
        schema_digest=gateway.operation_draft_schema_digest(
            "object.create",
            "2025.1",
        ),
        composer_digest=operation_composer_digest(
            "object.create",
            "2025.1",
        ),
    )
    assert materialized.request["arguments"] == {
        "parent": {"kind": "id", "value": PARENT_ID},
        "type": "Sound",
        "name": "Rain",
        "platform": "Windows",
        "properties": [
            {"name": "IsLoopingEnabled", "value": True},
            {"name": "IsLoopingInfinite", "value": True},
            {"name": "Volume", "value": -4.0},
            {"name": "UseMaxSoundPerInstance", "value": True},
            {"name": "MaxSoundPerInstance", "value": 4},
            {"name": "IgnoreParentMaxSoundInstance", "value": True},
        ],
        "references": [
            {
                "name": "OutputBus",
                "target": {
                    "kind": "id",
                    "value": "{22222222-2222-2222-2222-222222222222}",
                },
            }
        ],
        "auto_add_to_source_control": True,
    }
