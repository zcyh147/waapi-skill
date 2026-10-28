from __future__ import annotations

from tests.support.gateway_config import set_gateway_config

import importlib.util
import base64
import json
import shlex
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
SECOND_ACTION_ID = "{33333333-3333-3333-3333-333333333333}"
THIRD_ACTION_ID = "{44444444-4444-4444-4444-444444444444}"


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


class MetadataFakeClient(FakeClient):
    def __init__(
        self,
        responses: Mapping[str, Sequence[Any]],
        metadata_by_name: Mapping[str, Mapping[str, Any]],
    ) -> None:
        super().__init__(responses)
        self.metadata_by_name = dict(metadata_by_name)

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            return {"return": list(self.metadata_by_name)}
        if uri == "ak.wwise.core.object.getPropertyInfo":
            assert isinstance(args, Mapping)
            return self.metadata_by_name[str(args["property"])]
        return super().call(uri, args, options)


def _env(tmp_path: Path, version: str = "2025.1") -> dict[str, str]:
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
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": version,
    }


def _project(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / "project" / "SampleProject.wproj"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<Project />\n", encoding="utf-8")
    return {"id": PROJECT_ID, "name": "SampleProject", "path": str(path)}


def _info(version: str = "2025.1") -> dict[str, Any]:
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
            "year": int(version.split(".")[0]),
            "major": 1,
            "minor": 0,
            "build": 1,
            "displayName": f"v{version}.0.1",
        },
    }


def _offline(
    tmp_path: Path, *argv: str, version: str | None = None,
) -> tuple[int, dict[str, Any]]:
    return gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *argv],
        env=_env(tmp_path) if version is None else _env(tmp_path, version),
        client_factory=lambda url: (_ for _ in ()).throw(
            AssertionError(f"offline command connected to {url}")
        ),
    )


def _live_client(
    tmp_path: Path, extra: Mapping[str, Sequence[Any]], *, version: str | None = None,
) -> FakeClient:
    return FakeClient(
        {
            "ak.wwise.core.getInfo": [_info() if version is None else _info(version)],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            **extra,
        }
    )


@pytest.mark.parametrize("version,native_type", [
    ("2021.1", "ActorMixer"), ("2022.1", "ActorMixer"),
    ("2023.1", "ActorMixer"), ("2024.1", "ActorMixer"),
    ("2025.1", "PropertyContainer"),
])
def test_object_binding_returns_version_stable_business_kind(
    tmp_path: Path, version: str, native_type: str,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set", version=version)
    if version == "2021.1":
        assert start_code == 2, started
        assert started["error_code"] == "UNAVAILABLE_IN_VERSION"
        return
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    hierarchy = "Containers" if version == "2025.1" else "Actor-Mixer Hierarchy"
    target_path = rf"\{hierarchy}\Default Work Unit\SemanticLab\UI\Confirm"
    client = _live_client(
        tmp_path,
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Confirm",
                            "type": native_type,
                            "path": target_path,
                        }
                    ]
                }
            ]
        }, version=version,
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
        env=_env(tmp_path, version),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert payload["bound_object"] == {
        "handle": payload["bound_object"]["handle"],
        "name": "Confirm",
        "type": native_type,
        "path": target_path,
        "business_kind": "actor-mixer",
        "business_kind_resolution": {
            "status": "resolved",
            "candidates": ["actor-mixer"],
            "reflected_type": native_type,
        },
        "semantic_kind": None,
    }
    assert payload["detected_version"] == version
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
        "declare_existing_batch",
        "declare_rtpc",
        "existing_target_count_decision",
        "more_actions",
        "shell_tool_timeout_ms",
        "then_read_next_response",
        "precompute_or_increment_revision",
    }
    assert "fixed_full_argv" not in continuation["more_actions"]
    assert continuation["declare_rtpc"] == {
        "available_via": "more_actions", "use_when": "an_rtpc_outcome_is_requested"}
    assert continuation["existing_target_count_decision"] == {
        "three_or_more_requested": (
            "bind_every_requested_existing_target_before_any_field_discovery_"
            "or_declaration_then_use_declare_existing_batch"
        ),
        "one_or_two_requested": "use_the_individual_discover_and_declare_routes",
    }
    assert "precondition" not in continuation["declare_existing_batch"]
    assert "draft-inspect" in continuation["more_actions"]["copy_command"]
    assert continuation["field_discovery"]["documented_lists"] == {
        "append": ["--field-source", "documented-lists", "--list"],
        "details_via": "more_actions",
    }
    assert len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) < 8_000
    # Execute the disclosed route in this test's isolated state directory. The
    # compact reply keeps List discovery actionable; inspect retains its scope,
    # provenance, selection, and unresolved-source boundaries in full.
    inspect_command = shlex.split(continuation["more_actions"]["copy_command"])
    inspect_code, inspected = _offline(
        tmp_path, *inspect_command[inspect_command.index("gateway.py") + 1 :],
        version=version,
    )
    assert inspect_code == 0, inspected
    assert "draft-declare-rtpc" in inspected["draft"]["next_action_binding"]["declare_rtpc"]["fixed_argv_prefix_copy"]
    assert inspected["draft"]["next_action_binding"]["declare_existing_batch"]["precondition"] == (
        "bind_every_requested_existing_target_before_starting_this_single_batch")
    assert inspected["draft"]["next_action_binding"]["field_discovery"][
        "documented_lists"
    ] == {
        "append": ["--field-source", "documented-lists", "--list"],
        "scope": "copy_exact_bound_owner_handle_or_type_handle",
        "selection": "copy_one_returned_scoped_selection",
        "evidence": "versioned_per_type_source_and_live_exact_class; not_getPropertyInfo",
        "absent_source": "unresolved_not_native_unavailable",
        "maximum_page_size": 64,
    }


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


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_gateway_builds_rtpc_curve_from_bound_business_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str,
) -> None:
    original_env, original_info = _env, _info

    def version_env(path: Path) -> dict[str, str]:
        return set_gateway_config(original_env(path), wwise_version=version)

    def version_info() -> dict[str, Any]:
        value = original_info()
        value["version"]["year"] = int(version[:4])
        value["version"]["displayName"] = f"v{version}.0.1"
        return value

    monkeypatch.setattr(sys.modules[__name__], "_env", version_env)
    monkeypatch.setattr(sys.modules[__name__], "_info", version_info)
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
    owner_next = owner["draft"]["next_action_binding"]
    assert owner_next["required_next_phase"] == (
        "discover_rtpc_property_for_bound_object"
    )
    assert "object_binding" not in owner_next

    volume_metadata = {
        "name": "Volume",
        "type": "Real32",
        "display": {"name": "Voice Volume", "group": "General"},
        "restriction": {"type": "range", "min": -200, "max": 200},
        "supports": {"rtpc": "Additive", "unlink": True},
    }
    discover_client = MetadataFakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        },
        {
            "Volume": volume_metadata,
            "OutputBusVolume": {
                **volume_metadata,
                "name": "OutputBusVolume",
                "display": {"name": "Output Bus Volume", "group": "General"},
            },
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
    assert discovered["candidate_count"] == 1
    assert discovered["field_candidates"][0]["label"] == "Voice Volume"
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
            "object.setRTPC", version
        ),
        composer_digest=operation_composer_digest(
            "object.setRTPC", version
        ),
    )
    assert materialized.request["arguments"]["property"] == "Volume"
    assert materialized.request["arguments"]["points"] == [
        {"x": 0, "y": -12, "shape": "SCurve"},
        {"x": 100, "y": 0, "shape": "Linear"},
    ]

    identities = {
        PARENT_ID: {"id": PARENT_ID, "name": "Rain", "type": "Sound", "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain"},
        CONTROL_ID: {"id": CONTROL_ID, "name": "Weather Intensity", "type": "GameParameter", "path": r"\Game Parameters\Default Work Unit\Weather Intensity"},
    }

    class CheckClient:
        def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
            if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
                return {"return": ["Volume"]}
            if uri == "ak.wwise.core.getInfo":
                return _info()
            if uri == "ak.wwise.core.getProjectInfo":
                return _project(tmp_path)
            if uri == "ak.wwise.core.object.getPropertyInfo":
                assert args["property"] == "Volume"
                return volume_metadata
            if uri == "ak.wwise.core.object.get":
                if args == {"waql": f'from object "{PARENT_ID}" select @RTPC take 1'}:
                    assert options == {"return": ["id"]}
                    return {"return": []}
                ids = args.get("from", {}).get("id")
                if ids == [PARENT_ID] and options == {"return": ["id", "@RTPC"]}:
                    return {"return": [{"id": PARENT_ID}]}
                if ids and all(item in identities for item in ids):
                    return {"return": [identities[item] for item in ids]}
            raise AssertionError(f"Unexpected WAAPI call: {uri} {args!r} {options!r}")

        def disconnect(self) -> None:
            pass

    for command, revision in (("draft-check", 5), ("preview-from-draft", 6)):
        code, payload = gateway.execute_gateway(
            ["--state-dir", str(tmp_path / "state"), command, draft_id,
             "--task-authority", authority, "--expected-revision", str(revision)],
            env=_env(tmp_path), client_factory=lambda _url: CheckClient(),
        )
        assert code == 0, json.dumps(payload, ensure_ascii=False)
        assert payload["ok"] is True
    assert payload["transaction_id"]


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
    assert "session_context" not in bound
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
    assert "session_context" not in discovered
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
        "declare_existing_batch",
        "declare_rtpc",
        "more_actions",
        "shell_tool_timeout_ms",
        "then_read_next_response",
        "precompute_or_increment_revision",
    }
    assert continuation["declare_existing"]["cardinality"] == (
        "exactly_one_declaration_per_command"
    )
    assert continuation["declare_rtpc"] == {
        "available_via": "more_actions", "use_when": "an_rtpc_outcome_is_requested"}
    assert "fixed_full_argv" not in json.dumps(continuation)
    assert "draft-inspect" in continuation["more_actions"]["copy_command"]
    assert continuation["field_discovery"]["available_via"] == "more_actions"
    # Compact continuation must not remove live metadata needed for selection.
    for result in discovered["meaning_results"]:
        metadata = result["candidates"][0]["metadata"]
        assert metadata["type"] == "Real64"
        assert metadata["supports"] == {"unlink": True}
        assert metadata["display"]["name"] == result["meaning"]
    inspect_code, inspected = _offline(
        tmp_path, "draft-inspect", draft_id, "--task-authority", authority,
    )
    assert inspect_code == 0, inspected
    assert "draft-declare-rtpc" in inspected["draft"]["next_action_binding"]["declare_rtpc"]["fixed_argv_prefix_copy"]
    more_discovery = inspected["draft"]["next_action_binding"]["field_discovery"]
    assert "draft-discover-fields" in more_discovery["fixed_argv_prefix_copy"]
    assert set(more_discovery["scope_decision"]) == {
        "existing_object", "stable_new_kind", "discovered_new_type",
    }
    assert "exact_detail_and_handle" in more_discovery["selection_modes"]
    assert len(json.dumps(discovered, separators=(",", ":")).encode("utf-8")) < 7_000, {
        "top_level_bytes": {key: len(json.dumps(value, separators=(",", ":")).encode("utf-8")) for key, value in discovered.items()},
        "continuation_bytes": {key: len(json.dumps(value, separators=(",", ":")).encode("utf-8")) for key, value in continuation.items()},
    }
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
    assert "session_context" not in declared
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




@pytest.mark.parametrize("swapped_row_values", (False, True))
def test_object_set_batch_declares_selected_fields_with_per_object_metadata_binding(
    tmp_path: Path,
    swapped_row_values: bool,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    handles: list[str] = []
    for revision, object_id, name in (
        (1, PARENT_ID, "Play_Rain"),
        (2, SECOND_ACTION_ID, "Play_Wind"),
        (3, THIRD_ACTION_ID, "Play_Thunder"),
    ):
        bind_client = _live_client(
            tmp_path,
            {
                "ak.wwise.core.object.get": [
                    {
                        "return": [
                            {
                                "id": object_id,
                                "name": "",
                                "type": "Action",
                                "path": rf"\Events\Default Work Unit\{name}\[Play]",
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
                str(revision),
                "--object-id",
                object_id,
            ],
            env=_env(tmp_path),
            client_factory=lambda _url, client=bind_client: client,
        )
        assert bind_code == 0, bound
        handles.append(bound["bound_object"]["handle"])
    continuation = bound["draft"]["next_action_binding"]
    assert "declare_existing_batch" in continuation
    assert "field_discovery" in continuation
    assert "declare_existing" not in continuation
    assert continuation["declare_existing_batch"]["row_value_orders"] == [
        "task_local_id_then_bound_object_handle",
        "bound_object_handle_then_task_local_id",
    ]
    assert continuation["declare_existing_batch"]["gateway_disambiguation"] == (
        "the_exact_boh1_object_handle_contract_identifies_the_handle"
    )
    assert "field_selection_rule" in continuation["declare_existing_batch"]

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
    delayed_resume = {
        "name": "PauseDelayedResumeAction",
        "type": "Boolean",
        "display": {"name": "Pause Delayed Resume Action", "group": "Action"},
        "supports": {"unlink": True},
    }
    batch_client = MetadataFakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
        },
        {
            "FadeTime": fade,
            "Delay": delay,
            "PauseDelayedResumeAction": delayed_resume,
        },
    )
    selected = {}
    for revision, (row_id, handle) in enumerate(zip(("rain", "wind", "thunder"), handles, strict=True), start=4):
        client = MetadataFakeClient(
            {"ak.wwise.core.getInfo": [_info()],
             "ak.wwise.core.getProjectInfo": [_project(tmp_path)]},
            {"FadeTime": fade, "Delay": delay, "PauseDelayedResumeAction": delayed_resume},
        )
        code, found = gateway.execute_gateway(
            ["--state-dir", str(tmp_path / "state"), "draft-discover-fields", draft_id,
             "--task-authority", authority, "--expected-revision", str(revision),
             "--object-handle", handle, "--meaning", "Fade Time", "--meaning", "Delay"],
            env=_env(tmp_path), client_factory=lambda _url: client,
        )
        assert code == 0, found
        selected[row_id] = [result["candidates"][0]["handle"] for result in found["meaning_results"]]
    row_arguments = [
        value
        for declaration_id, handle in zip(
            ("rain", "wind", "thunder"), handles, strict=True
        )
        for value in (
            "--row",
            handle if swapped_row_values else declaration_id,
            declaration_id if swapped_row_values else handle,
        )
    ]
    batch_code, batch = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-declare-existing-batch",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "7",
            "--row-order",
            "rain",
            "--row-order",
            "wind",
            "--row-order",
            "thunder",
            *row_arguments,
            "--field-value",
            "rain",
            selected["rain"][0],
            "0.25 seconds",
            "--field-value",
            "rain",
            selected["rain"][1],
            "0",
            "--field-value",
            "wind",
            selected["wind"][0],
            "0.4",
            "--field-value",
            "wind",
            selected["wind"][1],
            "0.1",
            "--field-value",
            "thunder",
            selected["thunder"][0],
            "0.05",
            "--field-value",
            "thunder",
            selected["thunder"][1],
            "0",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: batch_client,
    )

    assert batch_code == 0, json.dumps(batch, ensure_ascii=False)
    assert batch["batch_receipt"] == {
        "row_count": 3,
        "field_count": 6,
        "metadata_scope": "each_exact_bound_object",
        "applied_atomically": True,
    }
    assert batch["draft"]["revision"] == 8
    assert len(json.dumps(batch, separators=(",", ":")).encode("utf-8")) < 7_000
    stored = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    session = stored.composition["business_session"]
    assert [row["declaration_id"] for row in session["declarations"]] == [
        "rain",
        "wind",
        "thunder",
    ]
    fields = session["handles"]["fields"]
    assert len(fields) == 6
    assert {field["scope_value"] for field in fields} == {
        PARENT_ID,
        SECOND_ACTION_ID,
        THIRD_ACTION_ID,
    }
    tokens = {field["handle"]: field["token"] for field in fields}
    rain_values = session["declarations"][0]["fields"]["field_values"]
    assert {tokens[handle]: value for handle, value in rain_values.items()} == {
        "FadeTime": 0.25,
        "Delay": 0.0,
    }


def test_object_set_batch_keeps_disclosed_stable_fields_out_of_metadata(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.set")
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    handles: dict[str, str] = {}
    targets = (
        (PARENT_ID, "Rifle_Close", "Sound", r"\Weapons\Rifle_Close"),
        (SECOND_ACTION_ID, "RFL_Tail", "Sound", r"\Weapons\RFL_Tail"),
        (
            THIRD_ACTION_ID,
            "RFL_Mechanical",
            "Sound",
            r"\Weapons\RFL_Mechanical",
        ),
        (CONTROL_ID, "WAAPI_V2_Weapons", "Bus", r"\Busses\WAAPI_V2_Weapons"),
    )
    for revision, (object_id, name, object_type, path) in enumerate(
        targets,
        start=1,
    ):
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
        bind_code, bound = gateway.execute_gateway(
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
            client_factory=lambda _url, client=client: client,
        )
        assert bind_code == 0, bound
        handles[name] = bound["bound_object"]["handle"]

    batch_client = _live_client(tmp_path, {})
    batch_code, batch = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-declare-existing-batch",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "5",
            "--row-order",
            "rifle_close",
            "--row",
            "rifle_close",
            handles["Rifle_Close"],
            "--field",
            "rifle_close",
            "new_name",
            "RFL_Close",
            "--field",
            "rifle_close",
            "output_bus",
            handles["WAAPI_V2_Weapons"],
            "--field",
            "rifle_close",
            "notes",
            "release-ready | close",
            "--row-order",
            "rfl_tail",
            "--row",
            "rfl_tail",
            handles["RFL_Tail"],
            "--field",
            "rfl_tail",
            "volume_db",
            "-3",
            "--row-order",
            "rfl_mechanical",
            "--row",
            "rfl_mechanical",
            handles["RFL_Mechanical"],
            "--field",
            "rfl_mechanical",
            "output_bus",
            handles["WAAPI_V2_Weapons"],
            "--field",
            "rfl_mechanical",
            "notes",
            "release-ready | mechanical",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: batch_client,
    )

    assert batch_code == 0, json.dumps(batch, ensure_ascii=False, indent=2)
    assert batch["batch_receipt"] == {
        "row_count": 3,
        "field_count": 6,
        "metadata_scope": "each_exact_bound_object",
        "applied_atomically": True,
    }
    stored = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    declarations = stored.composition["business_session"]["declarations"]
    assert declarations[0]["fields"] == {
        "new_name": "RFL_Close",
        "output_bus": handles["WAAPI_V2_Weapons"],
        "notes": "release-ready | close",
    }
    assert declarations[1]["fields"] == {"volume_db": -3.0}
    assert declarations[2]["fields"] == {
        "output_bus": handles["WAAPI_V2_Weapons"],
        "notes": "release-ready | mechanical",
    }


@pytest.mark.parametrize("source_control", (None, False, True), ids=("omitted", "disabled", "enabled"))
@pytest.mark.parametrize("source_form", ("inline-wav", "media-file"))
def test_gateway_adds_subordinate_media_without_model_authored_json(
    tmp_path: Path, source_form: str, source_control: bool | None,
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

    media = tmp_path / "Storm Warning 现场.wav"
    media.write_bytes(b"RIFF-fixture")
    source_value = (
        "StormWarning.wav|UklGRgAAAAAA"
        if source_form == "inline-wav"
        else str(media)
    )
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
        f"--{source_form}",
        source_value,
        "--kind",
        "sound-voice",
        "--language",
        "English(US)",
        "--originals-subfolder",
        "Weather/Warnings",
        *([] if source_control is None else ["--add-to-source-control" if source_control else "--no-add-to-source-control"]),
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

    if source_control is not None:
        before_bytes = {path: path.read_bytes() for path in (tmp_path / "state" / "drafts").rglob("*") if path.is_file()}
        code, rejected = _offline(tmp_path, "draft-add-media", draft_id,
            "--task-authority", authority, "--expected-revision", "4", "--declaration-id", "voice",
            "--inline-wav", "Other.wav|UklGRgAAAAAA",
            "--no-add-to-source-control" if source_control else "--add-to-source-control")
        assert code == 2 and rejected["error_code"] == "OBJECT_SET_IMPORT_SOURCE_CONTROL_CONFLICT", rejected
        assert {path: path.read_bytes() for path in before_bytes} == before_bytes


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
        **({} if source_control is None else {"auto_add_to_source_control": source_control}),
        "files": [
            {
                ("audio_file_base64" if source_form == "inline-wav" else "audio_file"): source_value,
                "originals_subfolder": "Weather/Warnings",
                "language": "English(US)",
                "object_type": "Sound",
            }
        ]
    }


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("configured", (False, True), ids=("defaults", "explicit-global"))
def test_object_set_global_settings_materialize_at_request_scope(
    tmp_path: Path, version: str, configured: bool,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "object.set", version=version)
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    root = "Containers" if version == "2025.1" else "Actor-Mixer Hierarchy"
    client = _live_client(tmp_path, {
        "ak.wwise.core.object.get": [{"return": [{
            "id": PARENT_ID,
            "name": "Default Work Unit",
            "type": "WorkUnit",
            "path": rf"\{root}\Default Work Unit",
        }]}],
    }, version=version)
    code, bound = gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), "draft-bind-object", draft_id,
         "--task-authority", authority, "--expected-revision", "1",
         "--object-id", PARENT_ID],
        env=_env(tmp_path, version), client_factory=lambda _url: client,
    )
    assert code == 0, bound
    code, declared = _offline(
        tmp_path, "draft-declare-new", draft_id, "--task-authority", authority,
        "--expected-revision", "2", "--declaration-id", "member",
        "--parent-handle", bound["bound_object"]["handle"],
        "--name", "Rain Layer", "--kind", "sound-sfx",
        "--field", "object_list", "CustomList", version=version,
    )
    assert code == 0, declared
    revision = declared["draft"]["revision"]
    if configured:
        code, configured_result = _offline(
            tmp_path, "draft-business-configure", draft_id,
            "--task-authority", authority, "--expected-revision", str(revision),
            "--name-conflict", "merge", "--list-behavior", "replace-all",
            "--add-to-source-control", version=version,
        )
        assert code == 0, configured_result
        revision = configured_result["draft"]["revision"]

    store = OperationDraftStore(tmp_path / "state")
    materialized = store.materialize_request(
        draft_id, task_authority=authority, expected_revision=revision,
        schema_digest=gateway.operation_draft_schema_digest("object.set", version),
        composer_digest=operation_composer_digest("object.set", version),
    )
    expected_arguments: dict[str, Any] = {
        "objects": [{
            "object": {"kind": "id", "value": PARENT_ID},
            "lists": [{"name": "CustomList", "objects": [
                {"type": "Sound", "name": "Rain Layer"},
            ]}],
        }],
    }
    if configured:
        expected_arguments.update({
            "on_name_conflict": "merge",
            "list_mode": "replaceAll",
            "auto_add_to_source_control": True,
        })
    assert materialized.request["arguments"] == expected_arguments

    # Replacement is a native child/list conflict choice in object.set too.
    code, replaced = _offline(
        tmp_path, "draft-business-configure", draft_id,
        "--task-authority", authority, "--expected-revision", str(revision),
        "--name-conflict", "replace", version=version,
    )
    assert code == 0, replaced
    after = store.materialize_request(
        draft_id, task_authority=authority, expected_revision=replaced["draft"]["revision"],
        schema_digest=gateway.operation_draft_schema_digest("object.set", version),
        composer_digest=operation_composer_digest("object.set", version),
    )
    assert after.request["arguments"]["on_name_conflict"] == "replace"


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
        == "selected_List_Field_Handle_or_exact_source_proven_alias_for_this_owner"
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


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("conflict", ("fail", "rename", "merge"))
def test_gateway_creates_recursive_root_in_owned_list(
    tmp_path: Path, version: str, conflict: str,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "object.create", version=version)
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    # An owned list does not require its owner to be a hierarchy container.
    client = _live_client(tmp_path, {
        "ak.wwise.core.object.get": [
            *([{"return": [_project(tmp_path)]}] if version == "2021.1" else []),
            {"return": [{
            "id": PARENT_ID, "name": "Weather", "type": "Sound",
            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
        }]}],
    }, version=version)
    code, bound = gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), "draft-bind-object", draft_id,
         "--task-authority", authority, "--expected-revision", "1",
         "--object-id", PARENT_ID],
        env=_env(tmp_path, version), client_factory=lambda _url: client,
    )
    assert code == 0, bound
    code, configured = _offline(
        tmp_path, "draft-business-configure", draft_id, "--task-authority", authority,
        "--expected-revision", "2", "--name-conflict", conflict, version=version,
    )
    assert code == 0, configured
    code, declared = _offline(
        tmp_path, "draft-declare-new", draft_id, "--task-authority", authority,
        "--expected-revision", "3", "--declaration-id", "list-root",
        "--parent-handle", bound["bound_object"]["handle"], "--name", "Layers",
        "--kind", "actor-mixer", "--field", "object_list", "CustomList",
        version=version,
    )
    assert code == 0, declared
    root_handle = declared["draft"]["declared_object"]["result_handle"]
    code, child = _offline(
        tmp_path, "draft-declare-new", draft_id, "--task-authority", authority,
        "--expected-revision", "4", "--declaration-id", "rain",
        "--parent-handle", root_handle, "--name", "Rain", "--kind", "sound-sfx",
        "--field", "notes", "Rain bed", version=version,
    )
    assert code == 0, child
    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id, task_authority=authority, expected_revision=5,
        schema_digest=gateway.operation_draft_schema_digest("object.create", version),
        composer_digest=operation_composer_digest("object.create", version),
    )
    assert materialized.request["arguments"] == {
        "parent": {"kind": "id", "value": PARENT_ID},
        "type": "ActorMixer", "name": "Layers", "list": "CustomList",
        "children": [{"type": "Sound", "name": "Rain", "notes": "Rain bed"}],
        **({} if conflict == "fail" else {"on_name_conflict": conflict}),
    }


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("conflict", ("fail", "rename", "merge"))
def test_gateway_set_preserves_global_platform_and_per_target_choices(
    tmp_path: Path, version: str, conflict: str,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "object.set", version=version)
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    client = _live_client(tmp_path, {
        "ak.wwise.core.object.get": [{"return": [{
            "id": PARENT_ID, "name": "Default Work Unit", "type": "WorkUnit",
            "path": r"\Actor-Mixer Hierarchy\Default Work Unit",
        }]}],
    }, version=version)
    code, bound = gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), "draft-bind-object", draft_id,
         "--task-authority", authority, "--expected-revision", "1",
         "--object-id", PARENT_ID],
        env=_env(tmp_path, version), client_factory=lambda _url: client,
    )
    assert code == 0, bound
    code, configured = _offline(
        tmp_path, "draft-business-configure", draft_id, "--task-authority", authority,
        "--expected-revision", "2", "--platform", "Windows", version=version,
    )
    assert code == 0, configured
    code, declared = _offline(
        tmp_path, "draft-declare-existing", draft_id, "--task-authority", authority,
        "--expected-revision", "3", "--declaration-id", "owner",
        "--object-handle", bound["bound_object"]["handle"],
        "--field", "notes", "Weather layers", "--field", "name_conflict", conflict,
        "--field", "platform", "Mac", version=version,
    )
    assert code == 0, declared
    code, child = _offline(
        tmp_path, "draft-declare-new", draft_id, "--task-authority", authority,
        "--expected-revision", "4", "--declaration-id", "rain",
        "--parent-handle", bound["bound_object"]["handle"],
        "--name", "Rain", "--kind", "sound-sfx", version=version,
    )
    assert code == 0, child
    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id, task_authority=authority, expected_revision=5,
        schema_digest=gateway.operation_draft_schema_digest("object.set", version),
        composer_digest=operation_composer_digest("object.set", version),
    )
    assert materialized.request["arguments"] == {
        "platform": "Windows",
        "objects": [{
            "object": {"kind": "id", "value": PARENT_ID},
            "notes": "Weather layers", "platform": "Mac", "on_name_conflict": conflict,
            "children": [{"type": "Sound", "name": "Rain"}],
        }],
    }


@pytest.mark.parametrize(
    ("version", "operation"),
    [(version, "object.create") for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")]
    + [(version, "object.set") for version in ("2022.1", "2023.1", "2024.1", "2025.1")],
)
@pytest.mark.parametrize("native_case", ["scalar", "null", "empty-array", "malformed-object", "missing-definition"])
def test_public_graph_preview_validates_reachable_native_definitions(
    tmp_path: Path, version: str, operation: str, native_case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "Containers" if version == "2025.1" else "Actor-Mixer Hierarchy"
    parent = {
        "id": PARENT_ID, "name": "Default Work Unit", "type": "WorkUnit", "classId": 3,
        "path": rf"\{root}\Default Work Unit", "@Volume": 0.0,
    }
    calls: list[str] = []

    class GraphClient:
        def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
            calls.append(uri)
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == "ak.wwise.core.getProjectInfo":
                return _project(tmp_path)
            if uri == "ak.wwise.core.object.getTypes":
                return {"return": [
                    {"classId": 1, "name": "PropertyContainer" if version == "2025.1" else "ActorMixer", "type": "WObject"},
                    {"classId": 2, "name": "Sound", "type": "Sound"},
                    {"classId": 3, "name": "WorkUnit", "type": "WObject"},
                ]}
            if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
                return {"return": ["Volume"]}
            if uri == "ak.wwise.core.object.getPropertyInfo":
                assert args["property"] == "Volume"
                return {"name": "Volume", "type": "Real64", "supports": {"unlink": True}}
            if uri == "ak.wwise.core.object.get":
                if args == {"waql": "from type Project take 1"}:
                    return {"return": [{**_project(tmp_path), "type": "Project"}]}
                if args.get("from", {}).get("id") == [PARENT_ID] and not args.get("transform"):
                    return {"return": [{key: parent[key] for key in options["return"] if key in parent}]}
                return {"return": []}
            raise AssertionError(f"Unexpected native dispatch: {uri} {args!r} {options!r}")

        def disconnect(self) -> None:
            pass

    def online(*argv: str) -> tuple[int, dict[str, Any]]:
        return gateway.execute_gateway(
            ["--state-dir", str(tmp_path / "state"), *argv],
            env=_env(tmp_path, version), client_factory=lambda _url: GraphClient(),
        )

    code, started = _offline(tmp_path, "draft-start", operation, version=version)
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    code, bound = online(
        "draft-bind-object", draft_id, "--task-authority", authority,
        "--expected-revision", "1", "--object-id", PARENT_ID,
    )
    assert code == 0, bound
    code, declared = _offline(
        tmp_path, "draft-declare-new", draft_id, "--task-authority", authority,
        "--expected-revision", "2", "--declaration-id", "group",
        "--parent-handle", bound["bound_object"]["handle"],
        "--name", "Weather", "--kind", "actor-mixer", version=version,
    )
    assert code == 0, declared
    revision = declared["draft"]["revision"]
    group_handle = declared["draft"]["declared_object"]["result_handle"]
    parent_handle = group_handle
    child_count = {"depth-limit": 7, "node-limit": 126 if operation == "object.set" else 127}.get(native_case, 1)
    branch_handles: list[str] = []
    for index in range(1, child_count + 1):
        if native_case == "node-limit":
            parent_handle = group_handle if index <= 32 else branch_handles[(index - 33) // 32]
        kind = "sound-sfx"
        if (
            native_case == "depth-limit" and index < child_count
            or native_case == "node-limit" and index <= 3
        ):
            kind = "actor-mixer"
        code, child = _offline(
            tmp_path, "draft-declare-new", draft_id, "--task-authority", authority,
            "--expected-revision", str(revision), "--declaration-id", f"rain{index}",
            "--parent-handle", parent_handle,
            "--name", "Rain" if child_count == 1 else f"Rain{index}", "--kind", kind,
            *(["--field", "volume_db", "-4"] if kind == "sound-sfx" else []),
            version=version,
        )
        assert code == 0, child
        revision = child["draft"]["revision"]
        if native_case == "depth-limit":
            parent_handle = child["draft"]["declared_object"]["result_handle"]
        elif native_case == "node-limit" and index <= 3:
            branch_handles.append(child["draft"]["declared_object"]["result_handle"])
    rejected = native_case in {"malformed-object", "missing-definition", "reference-cycle"} or (
        native_case == "empty-array" and operation == "object.create"
    )
    injected_rows: list[dict[str, Any]] = []

    def install_compiler_control() -> None:
        # Test-only native output, never a caller-authored payload route. Legal
        # shapes stay stable across check and preview; faulty output is added
        # after the valid check to exercise the Preview gate itself.
        import wwise_waapi.operation_registry as registry
        if native_case in {"null", "empty-array", "malformed-object"}:
            materialize = registry._materialize_canonical_object_node

            def injected_node(*args: Any, **kwargs: Any) -> dict[str, Any]:
                node = materialize(*args, **kwargs)

                def inject(row: dict[str, Any]) -> None:
                    if row.get("type") == "Sound":
                        row["@OutputBus"] = {
                            "null": None, "empty-array": [],
                            "malformed-object": {"unrecognized": True},
                        }[native_case]
                        injected_rows.append(dict(row))
                    for child in row.get("children", []):
                        inject(child)
                inject(node)
                return node

            monkeypatch.setattr(registry, "_materialize_canonical_object_node", injected_node)
        elif native_case in {"missing-definition", "reference-cycle"}:
            import wwise_waapi.schema_inventory as inventory
            resolve = inventory.resolve_schema_reference

            def missing_object_arg(reference: str, **kwargs: Any) -> Any:
                if reference.endswith("/objectArg"):
                    if native_case == "missing-definition":
                        raise inventory.SchemaInventoryError("test dependency loss: objectArg")
                    from dataclasses import replace
                    return replace(resolve(reference, **kwargs), target={"$ref": reference})
                return resolve(reference, **kwargs)

            monkeypatch.setattr(inventory, "resolve_schema_reference", missing_object_arg)

    if not rejected:
        install_compiler_control()
    code, checked = online(
        "draft-check", draft_id, "--task-authority", authority, "--expected-revision", str(revision),
    )
    assert code == 0, json.dumps(checked)
    if rejected:
        install_compiler_control()
    code, previewed = online(
        "preview-from-draft", draft_id, "--task-authority", authority, "--expected-revision", str(revision + 1),
    )
    if rejected:
        assert code == 2, json.dumps(previewed)
        assert previewed["error_code"] == "SemanticValidationError", previewed
        assert previewed["details"]["uri"] == f"ak.wwise.core.{operation}"
        assert not list((tmp_path / "state" / "transactions").glob("*/preview.json"))
        if native_case not in {"missing-definition", "reference-cycle"}:
            expected_bad_value: Any = [] if native_case == "empty-array" else {"unrecognized": True}
            assert injected_rows and injected_rows[-1]["@OutputBus"] == expected_bad_value
        if native_case == "reference-cycle":
            assert previewed["details"]["maximum_depth"] == 32
            assert "reference depth budget" in previewed["message"]
        assert "transaction_id" not in previewed
        assert not any(uri in {"ak.wwise.core.object.create", "ak.wwise.core.object.set"} for uri in calls)
        return
    assert code == 0, json.dumps(previewed)
    code, shown = _offline(
        tmp_path, "transaction-show", previewed["transaction_id"], version=version,
    )
    assert code == 0, shown
    prepared = shown["artifact"]["prepared_operation"]
    dispatch = prepared["dispatch"]
    metadata = prepared["semantic_preview"]["envelope"]["metadata"]
    assert metadata["request_validation_strength"] == "complete_reflected_schema", metadata
    assert metadata["schema_validation"]["unresolved_refs"] == []
    group = dispatch["args"] if operation == "object.create" else dispatch["args"]["objects"][0]["children"][0]
    if native_case in {"depth-limit", "node-limit"}:
        def sizes(row: Mapping[str, Any]) -> tuple[int, int]:
            children = [sizes(child) for child in row.get("children", [])]
            return 1 + sum(size for size, _depth in children), 1 + max((depth for _size, depth in children), default=0)
        assert sizes(group) == ((8, 8) if native_case == "depth-limit" else (child_count + 1, 3))
        assert not any(uri in {"ak.wwise.core.object.create", "ak.wwise.core.object.set"} for uri in calls)
        return
    expected_child: dict[str, Any] = {"type": "Sound", "name": "Rain", "@Volume": -4.0}
    if native_case in {"null", "empty-array"}:
        expected_child["@OutputBus"] = None if native_case == "null" else []
    assert group["children"][0] == expected_child
    assert not any(uri in {"ak.wwise.core.object.create", "ak.wwise.core.object.set"} for uri in calls)


@pytest.mark.parametrize("operation", ["object.create", "object.set"])
@pytest.mark.parametrize("native_case", ["depth-limit", "node-limit"])
def test_public_graph_declared_limits_remain_valid_with_resolved_schemas(
    tmp_path: Path, operation: str, native_case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_public_graph_preview_validates_reachable_native_definitions(
        tmp_path, "2025.1", operation, native_case, monkeypatch,
    )


def test_public_graph_preview_bounds_recursive_schema_reference_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_public_graph_preview_validates_reachable_native_definitions(
        tmp_path, "2025.1", "object.create", "reference-cycle", monkeypatch,
    )


INLINE_PCM_PADDED = "UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA="
INLINE_PCM_UNPADDED = "UklGRigAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAAAAAAA"


def _public_inline_wav_preview(tmp_path, version, source_value, *, nested=True, verification_case=None):
    """Drive the actual public Draft/Preview with only the native client faked."""
    from tests.unit.test_object_native_surface import _project_info

    root = "Containers" if version == "2025.1" else "Actor-Mixer Hierarchy"
    parent = {"id": PARENT_ID, "name": "Default Work Unit", "type": "WorkUnit", "classId": 3,
              "path": rf"\{root}\Default Work Unit"}
    container_import = verification_case == "container-import"
    if container_import:
        parent.update(name="Weather", notes="", classId=1, type="PropertyContainer" if version == "2025.1" else "ActorMixer",
                      path=parent["path"] + r"\Weather")
    project = _project(tmp_path)
    project_root = Path(project["path"]).parent
    complete_project = _project_info(project_root, language="SFX")
    complete_project.update(project)
    project = complete_project
    calls = []
    executed = False
    copied = project_root / "Originals" / "SFX" / "Inline.wav"
    sound = {"id": SECOND_ACTION_ID, "name": "Rain", "type": "Sound", "classId": 2, "notes": "",
             "path": parent["path"] + r"\Rain", "parent": {"id": PARENT_ID},
             "activeSource": {"id": THIRD_ACTION_ID}, "originalFilePath": str(copied)}
    source = {"id": THIRD_ACTION_ID, "name": "Inline", "type": "AudioFileSource", "classId": 16, "notes": "",
              "path": sound["path"] + r"\Inline", "parent": {"id": SECOND_ACTION_ID},
              "audioSource:language": {"id": CONTROL_ID, "name": "SFX"}, "originalFilePath": str(copied)}
    if container_import:
        sound.update(name="Inline", path=parent["path"] + r"\Inline")
        source["path"] = sound["path"] + r"\Inline"
    if verification_case == "wrong-target-class":
        sound["classId"] = 16
    elif verification_case == "wrong-source-class":
        source["classId"] = 2
    elif verification_case == "wrong-active-source":
        sound["activeSource"] = {"id": CONTROL_ID}
    elif verification_case == "wrong-parent":
        source["parent"] = {"id": CONTROL_ID}
    elif verification_case == "wrong-source-type":
        source["type"] = "SourcePlugin"

    class Client:
        def call(self, uri, args=None, options=None):
            nonlocal executed
            calls.append(uri)
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == "ak.wwise.core.getProjectInfo":
                return project
            if uri == "ak.wwise.core.object.getTypes":
                return {"return": [
                    {"classId": 1, "name": "PropertyContainer" if version == "2025.1" else "ActorMixer", "type": "WObject"},
                    {"classId": 2, "name": "Sound", "type": "Sound"},
                    {"classId": 3, "name": "WorkUnit", "type": "WObject"},
                    {"classId": 16, "name": "AudioFileSource", "type": "WObject"},
                ]}
            if uri == "ak.wwise.core.object.get":
                if args == {"waql": "from type Project take 1"}:
                    return {"return": [{**project, "type": "Project"}]}
                if args.get("from", {}).get("id") == [PARENT_ID] and not args.get("transform"):
                    return {"return": [parent]}
                if executed:
                    ids = args.get("from", {}).get("id")
                    if args.get("transform"):
                        rows = ([sound, source] if container_import and args["transform"] == [{"select": ["descendants"]}]
                                else [sound] if ids == [PARENT_ID] else [source])
                        if verification_case == "extra-child" and ids == [SECOND_ACTION_ID] and args["transform"] == [{"select": ["children"]}]:
                            rows = [*rows, {"id": CONTROL_ID, "name": "Unexpected", "type": "Sound",
                                           "path": sound["path"] + r"\Unexpected", "parent": {"id": SECOND_ACTION_ID}}]
                        return {"return": rows}
                    if ids == [SECOND_ACTION_ID]:
                        return {"return": [sound]}
                    if ids == [THIRD_ACTION_ID]:
                        return {"return": [source]}
                return {"return": []}
            if uri == "ak.wwise.core.object.set" and verification_case is not None:
                executed = True
                copied.parent.mkdir(parents=True)
                audio = base64.b64decode(source_value.partition("|")[2])
                copied.write_bytes(audio[:-1] + b"\1" if verification_case == "wrong-bytes" else audio)
                if container_import:
                    return {"objects": [{"id": PARENT_ID, "name": parent["name"],
                                         "import": {"logs": [], "objects": [sound, source]}}]}
                return {"objects": [{"id": PARENT_ID, "name": parent["name"], "children": [{
                    **{key: sound[key] for key in ("id", "name", "type", "path", "parent", "notes")},
                    "import": {"logs": [], "objects": [source]},
                }]}]}
            raise AssertionError(f"Unexpected native call {uri}: {args}")

        def disconnect(self):
            pass

    def invoke(*argv):
        return gateway.execute_gateway(
            ["--state-dir", str(tmp_path / "state"), *argv],
            env=_env(tmp_path, version), client_factory=lambda _url: Client(),
        )

    code, started = invoke("draft-start", "object.set")
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    revision = started["draft"]["revision"]

    def update(command, *argv):
        nonlocal revision
        code, payload = invoke(command, draft_id, "--task-authority", authority,
                               "--expected-revision", str(revision), *argv)
        if code == 0 and "draft" in payload:
            revision = payload["draft"]["revision"]
        return code, payload

    code, bound = update("draft-bind-object", "--object-id", PARENT_ID)
    assert code == 0, bound
    handle = bound["bound_object"]["handle"]
    if nested:
        code, group = update("draft-declare-new", "--declaration-id", "weather",
                             "--parent-handle", handle, "--name", "Weather", "--kind", "actor-mixer")
        assert code == 0, group
        handle = group["draft"]["declared_object"]["result_handle"]
    code, declared_sound = (
        update("draft-declare-existing", "--declaration-id", "rain", "--object-handle", handle,
               "--field", "notes", "")
        if container_import else
        update("draft-declare-new", "--declaration-id", "rain",
               "--parent-handle", handle, "--name", "Rain", "--kind", "sound-sfx")
    )
    assert code == 0, declared_sound
    code, added = update("draft-add-media", "--declaration-id", "rain", "--inline-wav", source_value,
                         "--kind", "sound-sfx", "--language", "SFX")
    if code != 0:
        return code, added, calls
    code, checked = update("draft-check")
    if code != 0:
        return code, checked, calls
    code, previewed = update("preview-from-draft")
    if code != 0:
        return code, previewed, calls
    code, shown = invoke("transaction-show", previewed["transaction_id"])
    assert code == 0, shown
    if verification_case is not None:
        transaction_id = previewed["transaction_id"]
        code, confirmed = invoke("confirm", transaction_id, "--confirmation-token", shown["confirmation"]["token"])
        assert code == 0, confirmed
        code, dispatched = invoke("execute", transaction_id)
        assert code == 0, json.dumps(dispatched)
        code, verified = invoke("verify", transaction_id)
        return code, verified, calls
    return code, shown["artifact"]["prepared_operation"], calls


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("source_form", ["padded", "unpadded", "extra-padding"])
@pytest.mark.parametrize("nested", [False, True], ids=["direct", "nested"])
def test_public_object_set_inline_wav_reaches_immutable_preview_unchanged(tmp_path, version, source_form, nested):
    encoded = INLINE_PCM_PADDED if source_form == "padded" else INLINE_PCM_UNPADDED
    source = "Inline.wav|" + encoded + ("=" if source_form == "extra-padding" else "")
    code, prepared, calls = _public_inline_wav_preview(tmp_path, version, source, nested=nested)
    assert code == 0, json.dumps(prepared)
    node = prepared["dispatch"]["args"]["objects"][0]["children"][0]
    if nested:
        node = node["children"][0]
    actual = node["import"]["files"][0]["audioFileBase64"]
    assert actual == "Inline.wav|" + encoded
    assert base64.b64decode(actual.partition("|")[2], validate=True) == base64.b64decode(encoded, validate=True)
    validation = prepared["semantic_preview"]["envelope"]["metadata"]["schema_validation"]
    assert validation["unresolved_refs"] == []
    assert validation["compatibility_rules"] == [{
        "rule_id": "object-set-inline-wav-canonical-base64/v1", "uri": "ak.wwise.core.object.set",
        "version": version, "document": "waapi_definitions.json", "definition_pointer": "/definitions/oneImportFile",
        "field": "audioFileBase64", "reflected_definition_sha256": "e98c169fbd4c3fbe76d961020a251e5f87d10f981fc29838c9cb2c88f84ce9ac",
        "native_observation_build": {"2023.1": "2023.1.19.8928", "2024.1": "2024.1.13.9056", "2025.1": "2025.1.7.9143"}[version],
        "section": "args.objects[0].children[0]" + (".children[0]" if nested else "") + ".import.files[0].audioFileBase64",
    }]
    assert "ak.wwise.core.object.set" not in calls


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("bad_source", ["alphabet", "broken-padding", "not-wave", "too-large", "unsafe-path"])
def test_public_object_set_inline_wav_keeps_existing_input_rejections(tmp_path, version, bad_source):
    source = {
        "alphabet": "Inline.wav|" + INLINE_PCM_UNPADDED[:-1] + "!",
        "broken-padding": "Inline.wav|" + INLINE_PCM_PADDED[:-2],
        "not-wave": "Inline.wav|" + base64.b64encode(b"this is not WAV").decode(),
        "too-large": "Inline.wav|" + base64.b64encode(b"RIFF0000WAVE" + b"\0" * (180 * 1024)).decode(),
        "unsafe-path": "../Inline.wav|" + INLINE_PCM_UNPADDED,
    }[bad_source]
    code, rejected, calls = _public_inline_wav_preview(tmp_path, version, source)
    assert code == 2, rejected
    assert "transaction_id" not in rejected
    assert "ak.wwise.core.object.set" not in calls
    assert not list((tmp_path / "state" / "transactions").glob("*/preview.json"))


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("changed_member", ["base64-pattern", "another-member"])
def test_public_object_set_inline_wav_stops_on_definition_drift(tmp_path, version, changed_member, monkeypatch):
    import copy
    from dataclasses import replace
    import wwise_waapi.schema_inventory as inventory

    resolve = inventory.resolve_schema_reference

    def drifted(reference, **kwargs):
        resolved = resolve(reference, **kwargs)
        if resolved.pointer == "/definitions/oneImportFile":
            target = copy.deepcopy(resolved.target)
            if changed_member == "base64-pattern":
                target["properties"]["audioFileBase64"]["pattern"] = ".*"
            else:
                target["properties"]["language"]["description"] += " changed source"
            return replace(resolved, target=target)
        return resolved

    monkeypatch.setattr(inventory, "resolve_schema_reference", drifted)
    code, rejected, calls = _public_inline_wav_preview(tmp_path, version, "Inline.wav|" + INLINE_PCM_UNPADDED)
    assert code == 2 and rejected["error_code"] == "SemanticValidationError", rejected
    assert "compatibility definition changed" in rejected["message"]
    assert "ak.wwise.core.object.set" not in calls
    assert not list((tmp_path / "state" / "transactions").glob("*/preview.json"))


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
def test_inline_wav_compatibility_rejects_noncanonical_compiler_output(tmp_path, version):
    from wwise_waapi.builders.schema import validate_resolved_semantic_payload
    from wwise_waapi.builders.common import SemanticValidationError

    code, prepared, _calls = _public_inline_wav_preview(tmp_path, version, "Inline.wav|" + INLINE_PCM_UNPADDED)
    assert code == 0, prepared
    args = prepared["dispatch"]["args"]
    args["objects"][0]["children"][0]["children"][0]["import"]["files"][0]["audioFileBase64"] += "="
    with pytest.raises(SemanticValidationError, match="must already use its canonical"):
        validate_resolved_semantic_payload("ak.wwise.core.object.set", args, {}, version=version)


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("placement", ["valid", "container-import"], ids=["declared-sound", "container"])
def test_public_object_set_inline_wav_verifies_sound_source_and_direct_children(tmp_path, version, placement):
    code, verified, calls = _public_inline_wav_preview(
        tmp_path, version, "Inline.wav|" + INLINE_PCM_UNPADDED, nested=False, verification_case=placement,
    )
    assert code == 0 and verified["state"] == "verified", json.dumps(verified)
    assert verified["verification"]["business_state_verified"] is True
    assert calls.count("ak.wwise.core.object.set") == 1


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("fault", ["wrong-active-source", "wrong-parent", "extra-child", "wrong-bytes", "wrong-source-type"])
def test_public_object_set_inline_wav_verifier_rejects_broken_media_relationships(tmp_path, version, fault):
    code, verified, calls = _public_inline_wav_preview(
        tmp_path, version, "Inline.wav|" + INLINE_PCM_UNPADDED, nested=False, verification_case=fault,
    )
    assert code == 2 and verified["state"] == "verification_failed", verified
    assert verified["verification"]["business_state_verified"] is False
    assert calls.count("ak.wwise.core.object.set") == 1


def _public_localized_inline_wav_verify(tmp_path, version, *, fault=None):
    """Existing English Voice gains French media; native reads honor language/projection."""
    from tests.unit.test_object_native_surface import _project_info

    project = _project(tmp_path)
    project_root = Path(project["path"]).parent
    project = {**_project_info(project_root, language="English(US)"), **project}
    project["languages"].append({"id": "{43000000-0000-0000-0000-000000000005}", "name": "French", "shortId": 32})
    root = "Containers" if version == "2025.1" else "Actor-Mixer Hierarchy"
    sound = {"id": PARENT_ID, "name": "Rain", "type": "Sound", "classId": 2, "notes": "",
             "path": rf"\{root}\Default Work Unit\Rain", "parent": {"id": SECOND_ACTION_ID}}
    english_file = project_root / "Originals" / "Voices" / "English(US)" / "English.wav"
    french_file = project_root / "Originals" / "Voices" / "French" / "Inline.wav"
    english_file.parent.mkdir(parents=True)
    english_file.write_bytes(base64.b64decode(INLINE_PCM_PADDED))
    english = {"id": CONTROL_ID, "name": "English", "type": "AudioFileSource", "classId": 16,
               "path": sound["path"] + r"\English", "parent": {"id": PARENT_ID},
               "audioSource:language": project["languages"][0], "originalFilePath": str(english_file)}
    french = {"id": THIRD_ACTION_ID, "name": "Inline", "type": "AudioFileSource", "classId": 16,
              "path": sound["path"] + r"\Inline", "parent": {"id": PARENT_ID},
              "audioSource:language": project["languages"][1], "originalFilePath": str(french_file)}
    executed = False
    verifying = False
    reads = []
    dispatches = []

    class Client:
        def call(self, uri, args=None, options=None):
            nonlocal executed
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == "ak.wwise.core.getProjectInfo":
                return project
            if uri == "ak.wwise.core.object.getTypes":
                return {"return": [{"classId": 2, "name": "Sound", "type": "Sound"},
                                   {"classId": 16, "name": "AudioFileSource", "type": "WObject"}]}
            if uri == "ak.wwise.core.object.get":
                assert isinstance(options.get("return"), list), options
                language = options.get("language", "English(US)")
                assert language in {"English(US)", "French"}, options
                localized_sound = {**sound, "activeSource": {"id": THIRD_ACTION_ID
                    if executed and language == "French" else CONTROL_ID},
                    "originalFilePath": str(french_file if executed and language == "French" else english_file)}
                if verifying and fault == "cross-language-active-source":
                    localized_sound["activeSource"] = {"id": THIRD_ACTION_ID if language == "English(US)" else CONTROL_ID}
                if verifying and language == "French":
                    changed_identity = {
                        "wrong-target-identity": ("id", SECOND_ACTION_ID),
                        "wrong-target-name": ("name", "Other"),
                        "wrong-target-type": ("type", "AudioFileSource"),
                        "wrong-target-path": ("path", sound["path"] + "Other"),
                        "wrong-target-parent": ("parent", {"id": CONTROL_ID}),
                    }.get(fault)
                    if changed_identity is not None:
                        localized_sound[changed_identity[0]] = changed_identity[1]
                if args == {"waql": "from type Project take 1"}:
                    rows = [{**project, "type": "Project"}]
                else:
                    ids = args.get("from", {}).get("id")
                    if args.get("transform"):
                        assert ids == [PARENT_ID], args
                        rows = [english, french] if executed else [english]
                    else:
                        rows = [{PARENT_ID: localized_sound, CONTROL_ID: english,
                                 THIRD_ACTION_ID: french}[object_id] for object_id in ids]
                # Return only requested native fields, including for all identity reads.
                rows = [{field: row[field] for field in options["return"] if field in row} for row in rows]
                if verifying:
                    reads.append({"args": args, "options": options, "rows": rows})
                return {"return": rows}
            if uri == "ak.wwise.core.object.set":
                assert not executed
                dispatches.append(args)
                executed = True
                french_file.parent.mkdir(parents=True)
                french_file.write_bytes(base64.b64decode(INLINE_PCM_UNPADDED))
                return {"objects": [{**sound, "import": {"logs": [], "objects": [french]}}]}
            raise AssertionError(f"Unexpected native call {uri}: {args}")

        def disconnect(self):
            pass

    def invoke(*argv):
        return gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), *argv],
            env=_env(tmp_path, version), client_factory=lambda _url: Client())

    code, started = invoke("draft-start", "object.set")
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    revision = started["draft"]["revision"]

    def update(command, *argv):
        nonlocal revision
        code, payload = invoke(command, draft_id, "--task-authority", authority,
                               "--expected-revision", str(revision), *argv)
        assert code == 0, payload
        if "draft" in payload:
            revision = payload["draft"]["revision"]
        return payload

    bound = update("draft-bind-object", "--object-id", PARENT_ID)
    update("draft-declare-existing", "--declaration-id", "rain", "--object-handle",
           bound["bound_object"]["handle"], "--field", "notes", "")
    update("draft-add-media", "--declaration-id", "rain", "--inline-wav", "Inline.wav|" + INLINE_PCM_UNPADDED,
           "--kind", "sound-voice", "--language", "French")
    update("draft-check")
    previewed = update("preview-from-draft")
    transaction_id = previewed["transaction_id"]
    code, shown = invoke("transaction-show", transaction_id)
    assert code == 0, shown
    code, confirmed = invoke("confirm", transaction_id, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, dispatched = invoke("execute", transaction_id)
    assert code == 0, dispatched
    verifying = True
    code, verified = invoke("verify", transaction_id)
    assert len(dispatches) == 1
    assert dispatches[0]["objects"][0]["import"]["files"][0]["language"] == "French"
    return code, verified, reads


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
def test_public_object_set_inline_wav_verifies_source_specific_language(tmp_path, version):
    code, verified, reads = _public_localized_inline_wav_verify(tmp_path, version)
    assert code == 0 and verified["state"] == "verified", json.dumps(verified)
    assert verified["verification"]["business_state_verified"] is True
    target_reads = {read["options"].get("language", "English(US)"): read["rows"][0]
                    for read in reads if read["args"] == {"from": {"id": [PARENT_ID]}}
                    and "activeSource" in read["options"]["return"]}
    assert target_reads["English(US)"]["activeSource"] == {"id": CONTROL_ID}
    assert target_reads["French"]["activeSource"] == {"id": THIRD_ACTION_ID}
    children = [read["rows"] for read in reads
                if read["args"].get("transform") == [{"select": ["children"]}]]
    assert len(children) == 1 and {row["id"] for row in children[0]} == {CONTROL_ID, THIRD_ACTION_ID}


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("fault", ["cross-language-active-source", "wrong-target-identity",
    "wrong-target-name", "wrong-target-type", "wrong-target-path", "wrong-target-parent"])
def test_public_object_set_inline_wav_rejects_cross_language_target_mismatch(tmp_path, version, fault):
    code, verified, _reads = _public_localized_inline_wav_verify(tmp_path, version, fault=fault)
    assert code == 2 and verified["state"] == "verification_failed", verified
    assert verified["verification"]["business_state_verified"] is False
    assertions = {item["name"]: item for item in verified["verification"]["assertions"]}
    assert assertions["$.objects[0].import source 0 was copied once with the exact hash"]["passed"] is True
    type_check = assertions["$.objects[0].import source 0 created the requested object type"]
    assert type_check["passed"] is False
    assert type_check["evidence"]["target_read_language"] == "French"
