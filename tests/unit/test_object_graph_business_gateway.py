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
from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.object_capabilities import NON_INTRINSIC_NAME_OBJECT_TYPES


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


def test_object_binding_returns_version_stable_business_kind(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    target_path = r"\Containers\Default Work Unit\SemanticLab\UI\Confirm"
    client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Confirm",
                            "type": "PropertyContainer",
                            "path": target_path,
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
            "1",
            "--object-id",
            PARENT_ID,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert payload["bound_object"] == {
        "handle": payload["bound_object"]["handle"],
        "name": "Confirm",
        "type": "PropertyContainer",
        "path": target_path,
        "business_kind": "actor-mixer",
        "business_kind_resolution": {
            "status": "resolved",
            "candidates": ["actor-mixer"],
            "reflected_type": "PropertyContainer",
        },
        "semantic_kind": None,
    }
    continuation = payload["draft"]["next_action_binding"]
    assert continuation["object_binding"]["repeat_selector_form"] == "by_id"
    assert set(continuation["object_binding"]) == {
        "repeat_selector_form",
        "by_id",
    }
    assert set(continuation) == {
        "contract",
        "required_next_phase",
        "object_binding",
        "field_discovery",
        "declare_existing",
        "more_actions",
        "shell_tool_timeout_ms",
        "then_read_next_response",
        "precompute_or_increment_revision",
    }
    assert "fixed_full_argv" not in continuation["more_actions"]
    assert "draft-inspect" in continuation["more_actions"]["copy_command"]
    assert len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) < 8_000


def test_literal_random_container_path_resolves_ambiguous_live_kind(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
    assert start_code == 0, started
    target_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons\Rifle"
    client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Rifle",
                            "type": "RandomSequenceContainer",
                            "path": target_path,
                        }
                    ]
                },
                {"return": [{"id": PARENT_ID, "@RandomOrSequence": 1}]},
            ]
        },
    )

    code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-object",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--object-path-segment",
            "Actor-Mixer Hierarchy",
            "--object-path-segment",
            "Default Work Unit",
            "--object-path-segment",
            "Weapons",
            "--object-path-segment",
            "Rifle",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, json.dumps(payload, ensure_ascii=False, indent=2)
    assert payload["bound_object"]["business_kind"] == "random-container"
    assert payload["bound_object"]["business_kind_resolution"] == {
        "status": "resolved",
        "candidates": ["random-container", "sequence-container"],
        "reflected_type": "RandomSequenceContainer",
        "source": "live_random_or_sequence_discriminator",
    }


def test_typed_random_container_path_is_rejected_before_live_dispatch(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
    assert start_code == 0, started
    target_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons\Rifle"
    client = _live_client(tmp_path, {})

    code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-object",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--object-path-segment",
            "Actor-Mixer Hierarchy",
            "--object-path-segment",
            "Default Work Unit",
            "--object-path-segment",
            "<Virtual Folder>Weapons",
            "--object-path-segment",
            "<Random Container>Rifle",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "Wwise type syntax" in payload["message"]


@pytest.mark.parametrize("discriminator", (None, True, 2, "0"))
def test_random_sequence_binding_rejects_invalid_live_discriminator(
    tmp_path: Path,
    discriminator: object,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
    assert start_code == 0, started
    target_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons\Rifle"
    client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Rifle",
                            "type": "RandomSequenceContainer",
                            "path": target_path,
                        }
                    ]
                },
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "@RandomOrSequence": discriminator,
                        }
                    ]
                },
            ]
        },
    )

    code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-object",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--object-id",
            PARENT_ID,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert payload["error_code"] == "BUSINESS_OBJECT_KIND_UNRESOLVED"
    assert payload["details"] == {
        "required_fields": ["id", "@RandomOrSequence"]
    }


def test_gateway_discovers_long_tail_type_then_compiles_only_its_handle(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.create")
    assert start_code == 0, started
    assert started["draft"]["allowed_actions"] == ["bind-object"]
    assert started["draft"]["next_action_binding"]["object_binding"][
        "existing_same_name_root_merge_rule"
    ] == (
        "after_exact_preflight_proves_the_existing_same_name_root_and_the_user_requests_merge; "
        "bind_that_root_direct_parent_not_the_existing_root; declare_the_existing_root_name_once; "
        "configure_name_conflict_merge; never_use_the_existing_root_as_its_own_new_parent"
    )
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
        "if_exact_preflight_found_an_existing_same_name_root_configure_merge_"
        "before_its_declaration; otherwise_declare_named_object_or_discover_"
        "long_tail_kind"
    )
    assert bind_next["type_discovery"]["native_type_input"] == "forbidden"
    assert bind_next["field_discovery"]["scope_decision"] == {
        "stable_semantic_kind": [
            "--semantic-kind",
            "<disclosed-stable-semantic-kind>",
        ],
        "discovered_type": [
            "--type-handle",
            "<selected-type-handle>",
        ],
    }
    assert bind_next["field_discovery"]["token_input"] == "forbidden"
    assert bind_next["configure"]["append"] == [
        "[--name-conflict fail|rename|merge|replace]",
        "[--replace-owner-handle <bound-existing-owner-handle>]",
        "[--platform <exact-user-platform>]",
        "[--add-to-source-control|--no-add-to-source-control]",
    ]
    merge = bind_next["existing_same_name_root_merge"]
    assert merge["required_before_root_declaration"] is True
    assert merge["append"] == ["--name-conflict", "merge"]
    assert merge["fixed_argv_prefix_copy"] == bind_next["configure"][
        "fixed_argv_prefix_copy"
    ]
    assert "--token" not in json.dumps(bind_next)

    type_rows = [
        {"classId": 3_276_960, "name": "Event", "type": "WObject"},
        {"classId": 3_276_961, "name": "Action", "type": "WObject"},
    ]
    discover_client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.getTypes": [
                {"return": type_rows}
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
    inspected = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    business_session = inspected.composition["business_session"]
    assert business_session["handles"]["types"][0]["catalog_digest"] == (
        canonical_sha256({"return": type_rows})
    )
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
    stored_declaration = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    ).composition["business_session"]["declarations"][-1]
    assert declared["draft"]["declared_object"] == {
        "declaration_id": "weather-event",
        "result_handle": stored_declaration["result_handle"],
    }
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


def test_gateway_closes_merge_configuration_before_root_declaration(
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
                            "name": "NPC",
                            "type": "ActorMixer",
                            "path": (
                                r"\Actor-Mixer Hierarchy\Default Work Unit"
                                r"\SemanticLab\NPC"
                            ),
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
    assert "existing_same_name_root_merge" in bound["draft"][
        "next_action_binding"
    ]

    configure_code, configured = _offline(
        tmp_path,
        "draft-business-configure",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--name-conflict",
        "merge",
    )
    assert configure_code == 0, configured
    next_action = configured["draft"]["next_action_binding"]
    assert next_action["required_next_phase"] == (
        "merge_configured_declare_existing_same_name_root_once_then_requested_"
        "descendants"
    )
    assert next_action["existing_same_name_root_merge_status"] == "satisfied"
    assert "existing_same_name_root_merge" not in next_action


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
    assert discovered["draft"]["response_integrity"] == {
        "complete": True,
        "truncated": False,
        "projection": "business_update_and_copy_ready_continuation",
        "compact_projection_is_not_truncation": True,
    }
    assert "business_contract" not in discovered["draft"]["next_action_binding"]
    assert '"fixed_argv_prefix":' not in json.dumps(discovered["draft"])
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
        "SCurve",
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
        {"x": 0, "y": -12, "shape": "SCurve"},
        {"x": 100, "y": 0, "shape": "Linear"},
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
        "ignore_parent_instance_limit",
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


def test_gateway_rejects_invalid_existing_declaration_before_revision(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
    assert start_code == 0, started
    assert started["draft"]["allowed_actions"] == ["bind-object"]
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    target_client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Rain",
                            "type": "Sound",
                            "path": (
                                r"\Actor-Mixer Hierarchy\Default Work Unit\Rain"
                            ),
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
        client_factory=lambda _url: target_client,
    )
    assert bind_code == 0, bound
    revision = bound["draft"]["revision"]

    rejected_code, rejected = _offline(
        tmp_path,
        "draft-declare-existing",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(revision),
        "--declaration-id",
        "rain",
        "--object-handle",
        bound["bound_object"]["handle"],
        "--field",
        "output_bus",
        "bobj1-does-not-exist",
    )

    assert rejected_code == 2, rejected
    assert rejected["error_code"] == "OBJECT_HANDLE_NOT_AVAILABLE"
    inspected = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    assert inspected.revision == revision
    assert inspected.composition["business_session"]["declarations"] == []


@pytest.mark.parametrize(
    "object_type",
    sorted(NON_INTRINSIC_NAME_OBJECT_TYPES),
)
def test_object_set_rejects_non_intrinsic_rename_at_business_declaration(
    tmp_path: Path,
    object_type: str,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
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
                            "name": "",
                            "type": object_type,
                            "path": rf"\Fixture\[{object_type}]",
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
    revision = bound["draft"]["revision"]

    rejected_code, rejected = _offline(
        tmp_path,
        "draft-declare-existing",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(revision),
        "--declaration-id",
        "target",
        "--object-handle",
        bound["bound_object"]["handle"],
        "--field",
        "new_name",
        "Renamed",
    )

    assert rejected_code == 2, rejected
    assert rejected["error_code"] == "DERIVED_OBJECT_NAME_BOUNDARY"
    assert rejected["details"]["repair"]["object_type"] == object_type
    inspected = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    assert inspected.revision == revision
    assert inspected.composition["business_session"]["declarations"] == []


@pytest.mark.parametrize(
    "object_type",
    sorted(NON_INTRINSIC_NAME_OBJECT_TYPES),
)
def test_object_set_rejects_non_container_parent_at_business_declaration(
    tmp_path: Path,
    object_type: str,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
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
                            "name": "",
                            "type": object_type,
                            "path": rf"\Fixture\[{object_type}]",
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
    revision = bound["draft"]["revision"]

    rejected_code, rejected = _offline(
        tmp_path,
        "draft-declare-new",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(revision),
        "--declaration-id",
        "child",
        "--parent-handle",
        bound["bound_object"]["handle"],
        "--name",
        "Child",
        "--kind",
        "sound-sfx",
    )

    assert rejected_code == 2, rejected
    assert rejected["error_code"] == "INVALID_CREATE_PARENT_TYPE"
    assert rejected["details"]["repair"]["actual_type"] == object_type
    inspected = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    assert inspected.revision == revision
    assert inspected.composition["business_session"]["declarations"] == []


def test_object_set_discovers_two_business_field_meanings_in_one_revision(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
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
                            "name": "",
                            "type": "Action",
                            "path": (
                                r"\Events\Default Work Unit\Play_Rain"
                                r"\[Play - Rain]"
                            ),
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
    handle = bound["bound_object"]["handle"]
    fade = {
        "name": "FadeTime",
        "type": "Real64",
        "display": {"name": "Fade Time", "group": "Action"},
        "supports": {"unlink": True},
    }
    delay = {
        "name": "Delay",
        "type": "Real64",
        "display": {"name": "Delay", "group": "Action"},
        "supports": {"unlink": True},
    }
    discovery_client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.getPropertyAndReferenceNames": [
                {"return": ["FadeTime", "Delay"]},
                {"return": ["FadeTime", "Delay"]},
                {"return": ["FadeTime", "Delay"]},
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                fade,
                delay,
                fade,
                delay,
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
            handle,
            "--meaning",
            "Fade Time",
            "--meaning",
            "Delay",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: discovery_client,
    )

    assert discover_code == 0, discovered
    assert discovered["meaning_count"] == 2
    assert discovered["candidate_count"] == 2
    assert "field_candidates" not in discovered
    assert discovered["candidate_projection"] == (
        "meaning_results[].candidates_without_duplicate_top_level_rows"
    )
    assert discovered["selection_required"] is False
    assert [row["meaning"] for row in discovered["meaning_results"]] == [
        "Fade Time",
        "Delay",
    ]
    assert [
        row["candidates"][0]["label"]
        for row in discovered["meaning_results"]
    ] == ["Fade Time", "Delay"]
    assert all(
        row["candidate_count"] == 1
        for row in discovered["meaning_results"]
    )
    continuation = discovered["draft"]["next_action_binding"]
    assert set(continuation) == {
        "contract",
        "required_next_phase",
        "field_discovery",
        "declare_existing",
        "more_actions",
        "shell_tool_timeout_ms",
        "then_read_next_response",
        "precompute_or_increment_revision",
    }
    assert continuation["declare_existing"]["cardinality"] == (
        "exactly_one_declaration_per_command"
    )
    assert "fixed_full_argv" not in json.dumps(continuation)
    assert "draft-inspect" in continuation["more_actions"]["copy_command"]
    assert len(json.dumps(discovered, separators=(",", ":")).encode("utf-8")) < 7_000
    fade_handle = discovered["meaning_results"][0]["candidates"][0]["handle"]
    delay_handle = discovered["meaning_results"][1]["candidates"][0]["handle"]
    declared_code, declared = _offline(
        tmp_path,
        "draft-declare-existing",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--declaration-id",
        "rain_action",
        "--object-handle",
        handle,
        "--field-value",
        fade_handle,
        "0.25",
        "--field-value",
        delay_handle,
        "0",
    )
    assert declared_code == 0, declared
    declared_continuation = declared["draft"]["next_action_binding"]
    assert set(declared_continuation) == {
        "contract",
        "required_next_phase",
        "object_binding",
        "completion_candidate",
        "more_actions",
        "shell_tool_timeout_ms",
        "then_read_next_response",
        "precompute_or_increment_revision",
    }
    assert "fixed_full_argv" not in json.dumps(declared_continuation)
    assert "draft-inspect" in declared_continuation["more_actions"]["copy_command"]
    assert set(declared_continuation["object_binding"]["selector_forms"]) == {
        "by_id",
        "by_path_segments",
        "event_action_by_event_path_segments",
    }
    assert set(declared_continuation["object_binding"]) >= {
        "fixed_argv_prefix_copy",
        "fixed_argv_prefix_copy_instruction",
        "choose_exactly_one_selector_form",
        "selector_forms",
        "result",
    }
    assert declared_continuation["object_binding"]["selection_rule"]
    assert declared_continuation["object_binding"]["result"] == (
        "copy_the_returned_bound_object.handle"
    )
    assert len(json.dumps(declared, separators=(",", ":")).encode("utf-8")) < 6_000
    rejected_client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.getPropertyAndReferenceNames": [
                {"return": ["FadeTime", "Delay"]}
            ],
            "ak.wwise.core.object.getPropertyInfo": [fade, delay],
        },
    )
    rejected_code, rejected = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-discover-fields",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "4",
            "--object-handle",
            handle,
            "--meaning",
            "Fade Time",
            "--meaning",
            "Missing Field",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: rejected_client,
    )

    assert rejected_code == 2, rejected
    assert "every requested meaning" in rejected["message"]
    unchanged = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    assert unchanged.revision == 4
    assert len(unchanged.composition["business_session"]["handles"]["fields"]) == 2
    assert len(unchanged.composition["business_session"]["declarations"]) == 1


def test_gateway_adds_subordinate_media_without_model_authored_json(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Default Work Unit",
                            "type": "WorkUnit",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit",
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
        client_factory=lambda _url: client,
    )
    assert bind_code == 0, bound
    parent_handle = bound["bound_object"]["handle"]
    set_next = bound["draft"]["next_action_binding"]
    assert set_next["field_discovery"]["scope_decision"] == {
        "existing_object": [
            "--object-handle",
            "<bound-existing-target-handle>",
        ],
        "stable_new_kind": [
            "--semantic-kind",
            "<disclosed-stable-semantic-kind>",
        ],
        "discovered_new_type": [
            "--type-handle",
            "<selected-type-handle>",
        ],
    }
    assert "configure" not in set_next
    assert "fixed_full_argv" not in set_next["more_actions"]
    assert "draft-inspect" in set_next["more_actions"]["copy_command"]
    inspect_code, inspected = _offline(
        tmp_path,
        "draft-inspect",
        draft_id,
        "--task-authority",
        authority,
    )
    assert inspect_code == 0, inspected
    assert "[--list-behavior append|replace-all]" in inspected["draft"][
        "next_action_binding"
    ]["configure"]["append"]

    declare_code, declared = _offline(
        tmp_path,
        "draft-declare-new",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--declaration-id",
        "voice",
        "--parent-handle",
        parent_handle,
        "--name",
        "Storm Warning",
        "--kind",
        "sound-voice",
        "--field",
        "language",
        "English(US)",
        "--field",
        "platform",
        "Windows",
    )
    assert declare_code == 0, declared
    media_binding = declared["draft"]["next_action_binding"]["add_media"]
    assert media_binding["native_import_fragment_input"] == "forbidden"

    media_code, added = _offline(
        tmp_path,
        "draft-add-media",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--declaration-id",
        "voice",
        "--inline-wav",
        "StormWarning.wav|UklGRgAAAAAA",
        "--kind",
        "sound-voice",
        "--language",
        "English(US)",
        "--originals-subfolder",
        "Weather/Warnings",
    )
    assert media_code == 0, added
    serialized_session = json.dumps(added["draft"])
    assert '"import"' not in serialized_session
    assert "media_files" not in serialized_session
    assert added["draft"]["response_integrity"] == {
        "complete": True,
        "truncated": False,
        "projection": "business_update_and_copy_ready_continuation",
        "compact_projection_is_not_truncation": True,
    }
    stored = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    assert "media_files" in json.dumps(stored.composition)

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=4,
        schema_digest=gateway.operation_draft_schema_digest(
            "object.set",
            "2025.1",
        ),
        composer_digest=operation_composer_digest(
            "object.set",
            "2025.1",
        ),
    )
    child = materialized.request["arguments"]["objects"][0]["children"][0]
    assert child["import"] == {
        "files": [
            {
                "audio_file_base64": "StormWarning.wav|UklGRgAAAAAA",
                "originals_subfolder": "Weather/Warnings",
                "language": "English(US)",
                "object_type": "Sound",
            }
        ]
    }


def test_gateway_declares_named_object_list_without_native_row_json(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Default Work Unit",
                            "type": "WorkUnit",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit",
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
        client_factory=lambda _url: client,
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
        "custom-list-member",
        "--parent-handle",
        bound["bound_object"]["handle"],
        "--name",
        "Rain Layer",
        "--kind",
        "sound-sfx",
        "--field",
        "object_list",
        "CustomList",
        "--field",
        "list_behavior",
        "replace-all",
    )
    assert declare_code == 0, declared
    assert (
        declared["draft"]["next_action_binding"]["clear_object_list"][
            "list_name_input"
        ]
        == "exact_user_owned_wwise_object_list_name_without_at_prefix"
    )

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=3,
        schema_digest=gateway.operation_draft_schema_digest(
            "object.set",
            "2025.1",
        ),
        composer_digest=operation_composer_digest(
            "object.set",
            "2025.1",
        ),
    )
    assert materialized.request["arguments"]["objects"][0]["lists"] == [
        {
            "name": "CustomList",
            "objects": [{"type": "Sound", "name": "Rain Layer"}],
        }
    ]
    assert (
        materialized.request["arguments"]["objects"][0]["list_mode"]
        == "replaceAll"
    )


def test_gateway_clears_named_object_list_without_empty_native_dsl(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Default Work Unit",
                            "type": "WorkUnit",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit",
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
        client_factory=lambda _url: client,
    )
    assert bind_code == 0, bound

    clear_code, cleared = _offline(
        tmp_path,
        "draft-clear-object-list",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--declaration-id",
        "clear-custom-list",
        "--object-handle",
        bound["bound_object"]["handle"],
        "--list-name",
        "CustomList",
    )

    assert clear_code == 0, cleared
    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=3,
        schema_digest=gateway.operation_draft_schema_digest(
            "object.set",
            "2025.1",
        ),
        composer_digest=operation_composer_digest(
            "object.set",
            "2025.1",
        ),
    )
    assert materialized.request["arguments"]["objects"] == [
        {
            "object": {"kind": "id", "value": PARENT_ID},
            "list_mode": "replaceAll",
            "lists": [{"name": "CustomList", "objects": []}],
        }
    ]
