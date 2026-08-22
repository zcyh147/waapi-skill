from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from wwise_waapi.capabilities import CapabilityCatalog
from wwise_waapi.operation_composer import (
    OPERATION_DRAFT_ACTION_CONTRACT,
    apply_composer_action,
    materialize_operation_request,
    new_composition,
    operation_composer_contract,
    parse_typed_action_cli_argument_sequence,
)
from wwise_waapi.platform_commands import encode_windows_model_argv
from wwise_waapi.transactions import TransactionStore
from wwise_waapi.typed_requests import request_contract


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_generic_typed_draft_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


URI = "ak.soundengine.setPosition"


def test_draft_completion_copy_command_uses_exact_native_shell_spelling() -> None:
    full_argv = [
        "python",
        r"C:\Agent Workspace\.agents\skills\waapi-skill\scripts\run.py",
        "gateway.py",
        "draft-check",
        "od1-0123456789abcdef0123456789abcdef",
        "--task-authority",
        "da1-0123456789abcdef0123456789abcdef01234567",
        "--expected-revision",
        "5",
    ]

    assert gateway.operation_draft_copy_command(
        full_argv,
        platform_name="posix",
    ) == shlex.join(full_argv)
    assert gateway.operation_draft_copy_command(
        full_argv,
        platform_name="nt",
    ) == encode_windows_model_argv(full_argv)


def _env(tmp_path: Path, version: str = "2022.1") -> dict[str, str]:
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
        "WWISE_VERSION": version,
    }


def _action(action: str, **facts: object) -> dict[str, object]:
    return {
        "contract": OPERATION_DRAFT_ACTION_CONTRACT,
        "action": action,
        **facts,
    }


def test_typed_action_batch_parser_preserves_option_looking_business_values() -> None:
    actions = parse_typed_action_cli_argument_sequence(
        [
            "--action",
            "add_typed_fact",
            "--fact-action",
            "set",
            "--field-handle",
            "trh1-000000000000000000000000",
            "--value-type",
            "string",
            "--fact-value",
            "--action",
            "--action",
            "add_typed_fact",
            "--fact-action",
            "set",
            "--field-handle",
            "trh1-111111111111111111111111",
            "--value-type",
            "string",
            "--fact-value",
            "next",
        ]
    )

    assert [action["value"] for action in actions] == ["--action", "next"]


def test_typed_action_batch_parser_accepts_exact_ceiling_and_rejects_next() -> None:
    action_argv = (
        "--action",
        "add_typed_fact",
        "--fact-action",
        "present",
        "--field-handle",
        "trh1-000000000000000000000000",
    )

    assert len(
        parse_typed_action_cli_argument_sequence(action_argv * 6)
    ) == 6
    with pytest.raises(Exception, match="batch|ceiling|invalid"):
        parse_typed_action_cli_argument_sequence(action_argv * 7)


def test_complex_generic_schema_discloses_draft_as_the_only_normal_entry(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        ["request-schema", URI],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("request-schema must be offline"),
    )

    assert code == 0
    assert payload["input_shape"] == "draft"
    assert payload["continuation"]["subcommand"] == "draft-start"
    assert payload["continuation"]["operation"] == URI
    assert payload["continuation"]["business_values_required"] is True
    assert payload["continuation"]["start_command"] == {
        "argv": ["draft-start", URI],
        "execute_alone": True,
        "typed_facts_on_draft_start": "invalid",
    }
    assert payload["continuation"]["after_start"] == {
        "fact_command_prefix_pointer": (
            "/draft/next_action_binding/fixed_argv_prefix"
        ),
        "append_one_or_more_complete_actions": True,
        "minimum_actions": 1,
        "maximum_actions": 6,
        "ordered_atomic_batch": True,
        "then_read_next_response": True,
    }
    assert payload["continuation"]["fact_value_argv_policy"] == {
        "one_business_value_is_one_argv_token": True,
        "whitespace_or_shell_metacharacters": (
            "shell-quote the complete value; splitting it is invalid"
        ),
        "preserve_value_text_exactly": True,
    }
    assert set(payload["continuation"]["action_argv"]) == {
        "add_typed_fact",
        "correct_typed_fact",
        "remove_typed_fact",
    }
    assert payload["continuation"]["completion"] == (
        "draft-check then preview-from-draft"
    )
    encoded = json.dumps(payload)
    assert "request-json" not in encoded
    assert "action-json" not in encoded


def test_branch_and_empty_container_actions_require_no_placeholder_values(
    tmp_path: Path,
) -> None:
    uri = "ak.wwise.core.object.setAttenuationCurve"
    version = "2025.1"
    state_dir = tmp_path / "state"
    contract = request_contract(version, uri)
    object_branch = next(
        field for field in contract.fields if field.path == ("object",) and field.shape == "branch"
    )
    object_guid_choice = next(
        field
        for field in contract.fields
        if field.parent_handle == object_branch.handle
        and any(
            "a-fA-F0-9" in pattern
            for pattern in field.as_dict().get("patterns", [])
        )
    )
    points = next(field for field in contract.fields if field.path == ("points",))
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", uri],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    assert start_code == 0

    choose_code, chosen = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir), "draft-apply", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", "1", "--facts",
            "--action", "add_typed_fact", "--fact-action", "choose",
            "--field-handle", object_branch.handle,
            "--fact-value", object_guid_choice.handle,
        ],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )
    assert choose_code == 0, chosen
    assert chosen["draft"]["revision"] == 2

    present_code, present = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir), "draft-apply", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", "2", "--facts",
            "--action", "add_typed_fact", "--fact-action", "present",
            "--field-handle", points.handle,
        ],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )
    assert present_code == 0, present
    assert present["draft"]["revision"] == 3


def test_draft_apply_batches_ordered_typed_actions_in_one_atomic_write(
    tmp_path: Path,
) -> None:
    contract = request_contract("2022.1", URI)
    handles = {".".join(field.path): field.handle for field in contract.fields}
    state_dir = tmp_path / "state"
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", URI],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    assert start_code == 0

    code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-apply",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--compact",
            "--facts",
            "--action",
            "add_typed_fact",
            "--fact-action",
            "set",
            "--field-handle",
            handles["gameObject"],
            "--value-type",
            "integer",
            "--fact-value",
            "7",
            "--action",
            "add_typed_fact",
            "--fact-action",
            "set",
            "--field-handle",
            handles["position.orientationFront.x"],
            "--value-type",
            "number",
            "--fact-value",
            "1",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )

    assert code == 0, payload
    assert payload["draft"]["revision"] == 3
    assert payload["draft"]["action_result"] == {
        "contract": "waapi-skill.operation-draft-action-result/v1",
        "action": "batch",
        "last_action": "add_typed_fact",
        "action_count": 2,
        "applied_atomically": True,
        "created_handles": payload["draft"]["action_result"]["created_handles"],
        "affected_handles": payload["draft"]["action_result"]["affected_handles"],
    }
    assert payload["draft"]["action_result"]["affected_handles"] == sorted(
        [handles["gameObject"], handles["position.orientationFront.x"]]
    )
    assert len(payload["draft"]["action_result"]["created_handles"]) == 2
    assert payload["draft"]["next_action_binding"][
        "typed_fact_batch_discipline"
    ] == {
        "batch_size": "6 until fewer than 6 facts remain",
        "final_batch": "include every remaining complete action; never split",
        "top_level_facts_before_dynamic_disclosure": True,
        "branch_choice_requires_selected_branch_facts": True,
        "schema_candidates_without_business_values": "skip",
    }
    assert payload["draft"]["next_action_binding"]["next_phase_decision"] == {
        "business_presence_source": "current_user_business_request",
        "evaluate_in_order": [
            {
                "candidate": "remaining_top_level_fact_batch",
                "condition": (
                    "unsubmitted_top_level_or_selected_branch_fact_is_present"
                ),
                "action": "use_fixed_argv_prefix_for_next_full_or_final_batch",
            },
            {
                "candidate": "dynamic_disclosure",
                "condition": "no_remaining_top_level_or_selected_branch_fact",
            },
        ],
        "first_true_candidate_is_the_only_next_phase": True,
    }
    assert payload["draft"]["schema_required_fields_status"] == "incomplete"
    assert (
        "completion_candidate"
        not in payload["draft"]["next_action_binding"]
    )
    assert "current_facts" not in payload["draft"]
    inspect_code, inspected = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-inspect",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("draft-inspect must be offline"),
    )
    assert inspect_code == 0
    assert [
        (row["fact_action"], row["field_handle"], row["value"])
        for row in inspected["draft"]["current_facts"]
    ] == [
        ("set", handles["gameObject"], "7"),
        ("set", handles["position.orientationFront.x"], "1"),
    ]


def test_invalid_later_batched_typed_action_leaves_identical_draft_bytes(
    tmp_path: Path,
) -> None:
    contract = request_contract("2022.1", URI)
    game_object = next(
        field.handle for field in contract.fields if field.path == ("gameObject",)
    )
    state_dir = tmp_path / "state"
    _start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", URI],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    record_path = next(state_dir.rglob("*.json"))
    before = record_path.read_bytes()

    code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-apply",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--facts",
            "--action",
            "add_typed_fact",
            "--fact-action",
            "set",
            "--field-handle",
            game_object,
            "--value-type",
            "integer",
            "--fact-value",
            "7",
            "--action",
            "add_typed_fact",
            "--fact-action",
            "set",
            "--field-handle",
            "trf1-000000000000000000000000",
            "--value-type",
            "integer",
            "--fact-value",
            "9",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )

    assert code == 2
    assert payload["error_code"] == "OPERATION_DRAFT_ACTION_INVALID"
    assert record_path.read_bytes() == before


def test_dynamic_draft_continuation_exposes_only_the_draft_action_form(
    tmp_path: Path,
) -> None:
    uri = "ak.soundengine.setMultiplePositions"
    contract = request_contract("2022.1", uri)
    positions = next(field for field in contract.fields if field.path == ("positions",))

    code, payload = gateway.execute_gateway(
        [
            "request-array-item", uri,
            "--schema-digest", contract.schema_digest,
            "--array-handle", positions.handle,
            "--index", "0",
            "--shape", "object",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("container disclosure must be offline"),
    )

    assert code == 0, payload
    assert payload["continuation"]["subcommand"] == "draft-apply"
    assert payload["continuation"]["deferred_fact"]["argv"] == [
        "--action", "add_typed_fact",
        "--fact-action", "append",
        "--field-handle", positions.handle,
        "--value-type", "object",
        "--fact-value", payload["handle"],
    ]
    assert payload["continuation"]["deferred_fact"]["is_next_command"] is False
    assert "action_argv" not in payload["continuation"]
    assert [
        (row["key"], row["shape"], row["required"])
        for row in payload["continuation"]["nested_container_disclosures"]
    ] == [("position", "object", True)]
    assert "fact" not in payload["continuation"]


def test_generic_draft_facts_materialize_one_canonical_waapi_call() -> None:
    contract = request_contract("2022.1", URI)
    handles = {".".join(field.path): field.handle for field in contract.fields}
    composition = new_composition(URI, "2022.1")
    fact_handles: list[str] = []

    def add(field: str, value_type: str, value: str) -> None:
        nonlocal composition
        composition, action_name = apply_composer_action(
            URI,
            "2022.1",
            composition,
            _action(
                "add_typed_fact",
                fact_action="set",
                field_handle=handles[field],
                value_type=value_type,
                value=value,
            ),
        )
        assert action_name == "add_typed_fact"
        fact_handles.append(composition["facts"][-1]["handle"])

    add("gameObject", "integer", "7")
    for prefix, values in {
        "position.orientationFront": ("1", "0", "0"),
        "position.orientationTop": ("0", "1", "0"),
        "position.position": ("1.5", "2.5", "3.5"),
    }.items():
        for axis, value in zip(("x", "y", "z"), values, strict=True):
            add(f"{prefix}.{axis}", "number", value)

    request = materialize_operation_request(URI, "2022.1", composition)
    assert request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "waapi.call",
        "arguments": {
            "api": URI,
            "args": {
                "gameObject": 7,
                "position": {
                    "orientationFront": {"x": 1.0, "y": 0.0, "z": 0.0},
                    "orientationTop": {"x": 0.0, "y": 1.0, "z": 0.0},
                    "position": {"x": 1.5, "y": 2.5, "z": 3.5},
                },
            },
            "options": {},
        },
    }
    assert len(fact_handles) == 10
    assert len(set(fact_handles)) == 10


def test_generic_fact_correction_and_removal_are_handle_bound() -> None:
    contract = request_contract("2022.1", URI)
    game_object = next(
        field.handle for field in contract.fields if field.path == ("gameObject",)
    )
    composition = new_composition(URI, "2022.1")
    composition, action_name = apply_composer_action(
        URI,
        "2022.1",
        composition,
        _action(
            "add_typed_fact",
            fact_action="set",
            field_handle=game_object,
            value_type="integer",
            value="7",
        ),
    )
    assert action_name == "add_typed_fact"
    fact_handle = composition["facts"][0]["handle"]
    composition, corrected = apply_composer_action(
        URI,
        "2022.1",
        composition,
        _action(
            "correct_typed_fact",
            fact_handle=fact_handle,
            fact_action="set",
            field_handle=game_object,
            value_type="integer",
            value="8",
        ),
    )
    assert corrected == "correct_typed_fact"
    composition, removed = apply_composer_action(
        URI,
        "2022.1",
        composition,
        _action("remove_typed_fact", fact_handle=fact_handle),
    )
    assert removed == "remove_typed_fact"
    assert composition["facts"] == []


def test_generic_composer_contract_is_schema_derived() -> None:
    typed = request_contract("2025.1", URI)
    composer = operation_composer_contract(URI, "2025.1")

    assert composer["operation"] == URI
    assert composer["typed_request_schema_digest"] == typed.schema_digest
    assert composer["actions"] == [
        "add_typed_fact",
        "correct_typed_fact",
        "remove_typed_fact",
    ]
    assert composer["complete_request_is_never_an_action"] is True


def test_every_permitted_complex_generic_lane_has_one_draft_adapter() -> None:
    lanes: list[tuple[str, str]] = []
    catalog = CapabilityCatalog()
    for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"):
        for capability in catalog.entries(version):
            if capability.item_type != "function":
                continue
            try:
                typed = request_contract(version, capability.uri)
            except Exception:
                continue
            if typed.as_gateway_payload()["input_shape"] != "draft":
                continue
            lanes.append((version, capability.uri))
            composer = operation_composer_contract(capability.uri, version)
            assert composer["typed_request_schema_digest"] == typed.schema_digest
            assert composer["actions"] == [
                "add_typed_fact",
                "correct_typed_fact",
                "remove_typed_fact",
            ]

    assert len(lanes) == 28
    assert ("2022.1", "ak.soundengine.setPosition") in lanes
    assert ("2025.1", "ak.wwise.core.mediaPool.get") in lanes


def test_invalid_generic_fact_fails_before_it_can_enter_durable_state() -> None:
    contract = request_contract("2022.1", URI)
    game_object = next(
        field.handle for field in contract.fields if field.path == ("gameObject",)
    )
    composition = new_composition(URI, "2022.1")

    with pytest.raises(Exception, match="does not accept typed value"):
        apply_composer_action(
            URI,
            "2022.1",
            composition,
            _action(
                "add_typed_fact",
                fact_action="set",
                field_handle=game_object,
                value_type="string",
                value="not-an-integer",
            ),
        )

    assert composition["facts"] == []


def test_complex_generic_rejects_direct_typed_call_before_connection(
    tmp_path: Path,
) -> None:
    contract = request_contract("2022.1", URI)
    game_object = next(
        field.handle for field in contract.fields if field.path == ("gameObject",)
    )
    code, payload = gateway.execute_gateway(
        [
            "typed-call", URI,
            "--schema-digest", contract.schema_digest,
            "--set", game_object, "integer", "7",
            "--apply",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("bypass must fail before connection"),
    )

    assert code == 2
    assert "draft-start" in payload["message"]


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
def test_fixed_complex_tracer_cannot_bypass_its_typed_call_with_a_draft(
    tmp_path: Path,
    version: str,
) -> None:
    uri = "ak.wwise.debug.validateCall"
    contract = request_contract(version, uri)
    assert contract.as_gateway_payload()["input_shape"] == "inline"

    code, payload = gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), "draft-start", uri],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("rejection must be offline"),
    )

    assert code == 2
    assert payload["error_code"] == "OPERATION_DRAFT_ADAPTER_UNAVAILABLE"
    assert not (tmp_path / "state" / "operation-drafts-v1").exists()


class _ReadClient:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []
        self.rows = list(rows or [])

    def call(self, uri: str, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            return {
                "isCommandLine": True,
                "version": {"year": 2025, "major": 1},
            }
        if uri == "ak.wwise.core.mediaPool.get":
            return {"return": self.rows}
        raise AssertionError(f"unexpected call {uri}")

    def disconnect(self) -> None:
        pass


class _MutationPreviewClient:
    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []

    def call(self, uri: str, args=None, options=None):
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            return {
                "displayName": "Wwise",
                "isCommandLine": True,
                "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "processId": 4242,
                "processPath": "/Applications/Wwise/WwiseConsole",
                "apiVersion": 1,
                "platform": "macosx",
                "configuration": "release",
                "version": {
                    "year": 2022, "major": 1, "minor": 0, "build": 1,
                    "displayName": "v2022.1.0",
                },
            }
        if uri == "ak.wwise.core.getProjectInfo":
            return {
                "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "name": "SampleProject",
                "path": str(self.project_path),
            }
        raise AssertionError(f"unexpected call {uri}")

    def disconnect(self) -> None:
        pass


def test_complex_read_draft_check_dispatches_directly_without_preview(
    tmp_path: Path,
) -> None:
    uri = "ak.wwise.core.mediaPool.get"
    env = _env(tmp_path, "2025.1")
    state_dir = tmp_path / "state"
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", uri],
        env=env,
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    assert start_code == 0
    contract = request_contract("2025.1", uri)
    search = next(field.handle for field in contract.fields if field.name == "searchText")
    apply_code, applied = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-apply", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", "1",
            "--facts", "--action", "add_typed_fact",
            "--fact-action", "set",
            "--field-handle", search,
            "--value-type", "string",
            "--fact-value", "rain",
        ],
        env=env,
        client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
    )
    assert apply_code == 0

    client = _ReadClient()
    check_code, checked = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-check", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(applied["draft"]["revision"]),
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert check_code == 0, checked
    assert checked["agent_result"] == {"return": []}
    assert list(checked)[-1] == "agent_result"
    assert client.calls[-1] == (
        uri,
        {"searchText": "rain"},
        {},
    )
    assert not (state_dir / "transactions").exists()


def test_media_pool_request_schema_discloses_typed_result_filter(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        ["request-schema", "ak.wwise.core.mediaPool.get"],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("request-schema must be offline"),
    )

    assert code == 0
    assert payload["continuation"]["gateway_argv_prefix"] == [
        "draft-start",
        "ak.wwise.core.mediaPool.get",
    ]
    assert "do not pass it to draft-start" in payload["continuation"][
        "schema_digest_usage"
    ]
    assert list(payload).index("top_level_fact_plan") < list(payload).index("fields")
    table = payload["top_level_fact_plan"]
    plan = [
        dict(zip(table["columns"], row, strict=True)) for row in table["rows"]
    ]
    assert [row["name"] for row in plan] == [
        "databases",
        "maxResults",
        "searchText",
        "return",
        "filters",
    ]
    assert [row["phase"] for row in plan] == [
        "fact",
        "fact",
        "fact",
        "fact",
        "disclosure",
    ]
    assert table["string_argv_rule"] == (
        "one exact string argv; PowerShell single-quotes it, doubles embedded "
        "single quotes, and never leaves whitespace unquoted"
    )
    assert payload["result_filter"] == {
        "contract": "waapi-skill.media-pool-post-filter/v1",
        "availability": "optional_after_complete_typed_candidate_request",
        "completion_subcommand": "draft-check",
        "typed_scalars": {
            "value": "--post-filter-value <exact case-sensitive text>",
            "limit": "--post-filter-limit <1..1000>",
        },
        "business_value_sources": {
            "value": (
                "current user requested exact-case substring; do not substitute "
                "the server candidate filter spelling"
            ),
            "limit": (
                "current user requested final return limit; never copy the typed "
                "request maxResults candidate ceiling"
            ),
        },
        "requirements": [
            "typed request filters includes Filename contains with the same value",
            "typed request options return includes Filename",
            "typed request maxResults is greater than or equal to the filter limit",
        ],
    }


def test_media_pool_typed_draft_applies_typed_post_filter_without_json(
    tmp_path: Path,
) -> None:
    uri = "ak.wwise.core.mediaPool.get"
    env = _env(tmp_path, "2025.1")
    state_dir = tmp_path / "state"
    contract = request_contract("2025.1", uri)
    fields = {field.name: field for field in contract.fields}
    filter_handle = gateway.dynamic_array_item_handle(
        contract,
        array_handle=fields["filters"].handle,
        index=0,
        shape="object",
    )
    filter_contract = gateway.dynamic_container_disclosure(
        contract,
        parent_handle=fields["filters"].handle,
        key="0",
        shape="object",
        child_handle=filter_handle,
    )
    choices = {
        row["key"]: row["choices"]
        for row in filter_contract["branch_choices"]
    }
    selected_choices = {
        "field": next(
            row["handle"] for row in choices["field"]
            if row.get("enum") == ["Filename"]
        ),
        "operator": next(
            row["handle"] for row in choices["operator"]
            if row.get("enum") == ["contains"]
        ),
        "type": next(
            row["handle"] for row in choices["type"]
            if row.get("enum") == ["field"]
        ),
        "value": choices["value"][0]["handle"],
    }
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", uri],
        env=env,
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    assert start_code == 0
    revision = 1
    facts = (
        ("append", fields["databases"].handle, "string", r"\Databases\Project Originals", None),
        ("append", fields["filters"].handle, "object", filter_handle, None),
        *(
            ("choose-dynamic", filter_handle, "choice", choice, key)
            for key, choice in selected_choices.items()
        ),
        ("map-put", filter_handle, "string", "Filename", "field"),
        ("map-put", filter_handle, "string", "contains", "operator"),
        ("map-put", filter_handle, "string", "field", "type"),
        ("map-put", filter_handle, "string", "footstep", "value"),
        ("set", fields["maxResults"].handle, "integer", "5", None),
        ("append", fields["return"].handle, "string", "Filename", None),
        ("append", fields["return"].handle, "string", "FileId", None),
    )
    for fact_index, (fact_action, handle, value_type, value, key) in enumerate(facts):
        argv = [
            "--state-dir", str(state_dir), "draft-apply", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(revision), "--facts",
            "--action", "add_typed_fact", "--fact-action", fact_action,
            "--field-handle", handle,
        ]
        if fact_action == "choose-dynamic":
            argv += ["--fact-value", value]
        else:
            argv += ["--value-type", value_type, "--fact-value", value]
        if key is not None:
            argv += ["--key", key]
        code, applied = gateway.execute_gateway(
            argv, env=env,
            client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
        )
        assert code == 0, repr(
            {"fact_index": fact_index, "fact": facts[fact_index], **applied}
        )
        revision = applied["draft"]["revision"]

    rows = [
        {"Filename": "footstep_gravel.wav", "FileId": "first"},
        {"Filename": "Footstep_decoy.wav", "FileId": "second"},
        {"Filename": "footstep_wood.wav", "FileId": "third"},
    ]
    client = _ReadClient(rows)
    code, checked = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir), "draft-check", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(revision),
            "--post-filter-value", "footstep", "--post-filter-limit", "2",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert code == 0, checked
    assert checked["agent_result"] == {"return": [rows[0], rows[2]]}
    assert checked["post_filter"]["operator"] == "containsCaseSensitive"
    assert list(checked)[-1] == "agent_result"
    assert not (state_dir / "transactions").exists()


def test_complex_mutation_draft_seals_and_replays_one_immutable_preview(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    state_dir = tmp_path / "state"
    project_path = tmp_path / "project" / "SampleProject.wproj"
    project_path.parent.mkdir()
    project_path.write_text("<Project/>", encoding="utf-8")
    contract = request_contract("2022.1", URI)
    handles = {".".join(field.path): field.handle for field in contract.fields}
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", URI],
        env=env,
        client_factory=lambda _url: pytest.fail("draft-start must be offline"),
    )
    assert start_code == 0
    revision = 1
    values = [("gameObject", "integer", "7")]
    for prefix, coordinates in {
        "position.orientationFront": ("1", "0", "0"),
        "position.orientationTop": ("0", "1", "0"),
        "position.position": ("1.5", "2.5", "3.5"),
    }.items():
        values.extend(
            (f"{prefix}.{axis}", "number", value)
            for axis, value in zip(("x", "y", "z"), coordinates, strict=True)
        )
    for field, value_type, value in values:
        apply_code, applied = gateway.execute_gateway(
            [
                "--state-dir", str(state_dir), "draft-apply", started["draft"]["draft_id"],
                "--task-authority", started["task_authority"],
                "--expected-revision", str(revision), "--compact", "--facts",
                "--action", "add_typed_fact", "--fact-action", "set",
                "--field-handle", handles[field],
                "--value-type", value_type, "--fact-value", value,
            ],
            env=env,
            client_factory=lambda _url: pytest.fail("draft-apply must be offline"),
        )
        assert apply_code == 0, applied
        revision = applied["draft"]["revision"]

    check_client = _MutationPreviewClient(project_path)
    check_code, checked = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir), "draft-check", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(revision),
        ],
        env=env,
        client_factory=lambda _url: check_client,
    )
    assert check_code == 0, checked
    checked_revision = checked["draft"]["revision"]
    assert checked["draft"]["check"]["status"] == "passed"
    assert checked["next_command"]["command"] == "preview-from-draft"
    assert [call[0] for call in check_client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    checked_record = gateway.OperationDraftStore(state_dir).inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )
    assert checked_record.revision == checked_revision

    preview_client = _MutationPreviewClient(project_path)
    preview_code, previewed = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir), "preview-from-draft", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(checked_revision), "--apply", "--ttl", "300",
        ],
        env=env,
        client_factory=lambda _url: preview_client,
    )
    assert preview_code == 0, json.dumps(previewed, indent=2)
    expected_request = materialize_operation_request(
        URI,
        "2022.1",
        gateway.OperationDraftStore(state_dir).inspect(
            started["draft"]["draft_id"],
            task_authority=started["task_authority"],
        ).composition,
    )
    assert previewed["state"] == "awaiting_confirmation"
    assert previewed["agent_result"]["request"] == expected_request
    assert list(previewed)[-1] == "agent_result"
    transaction_store = TransactionStore(state_dir)
    stored = transaction_store.load_preview(previewed["transaction_id"])
    assert stored.artifact["request"] == expected_request
    events_before_replay = transaction_store.read_events(previewed["transaction_id"])
    assert [event["event_type"] for event in events_before_replay] == [
        "preview_created",
        "confirmation_requested",
    ]

    replay_client = _MutationPreviewClient(project_path)
    replay_code, replayed = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir), "preview-from-draft", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(checked_revision), "--apply", "--ttl", "300",
        ],
        env=env,
        client_factory=lambda _url: replay_client,
    )
    assert replay_code == 0, replayed
    assert replayed["transaction_id"] == previewed["transaction_id"]
    assert replayed["artifact_hash"] == previewed["artifact_hash"]
    assert transaction_store.read_events(previewed["transaction_id"]) == events_before_replay
