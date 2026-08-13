from __future__ import annotations

import importlib.util
import json
from collections import deque
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import pytest

from wwise_waapi.operation_composer import (
    OPERATION_DRAFT_ACTION_CONTRACT,
    OperationComposerError,
    apply_composer_action,
    materialize_operation_request,
    new_composition,
    operation_composer_contract,
    parse_typed_action_cli_arguments,
    typed_action_cli_arguments,
)
from wwise_waapi.typed_operations import compound_child_request_contract
from wwise_waapi.transactions import TransactionState, TransactionStore


VERSION = "2025.1"
SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_typed_undo_gateway", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


def _env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": VERSION,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_WAAPI_PORT": "8080",
    }


OBJECT_ID = "{11111111-1111-1111-1111-111111111111}"


class _Client:
    def __init__(self, tmp_path: Path, *, execute: bool = False) -> None:
        project_path = tmp_path / "project" / "SampleProject.wproj"
        project_path.parent.mkdir(exist_ok=True)
        project_path.write_text("<Project/>", encoding="utf-8")
        self.calls: list[str] = []
        self.responses: dict[str, deque[Mapping[str, Any]]] = {
            "ak.wwise.core.getInfo": deque(
                [
                    {
                        "displayName": "Wwise",
                        "isCommandLine": True,
                        "sessionId": "{22222222-2222-2222-2222-222222222222}",
                        "processId": 42,
                        "processPath": "/Applications/Wwise.app/Contents/MacOS/Wwise",
                        "apiVersion": 1,
                        "platform": "macosx",
                        "configuration": "release",
                        "version": {"year": 2025, "major": 1, "minor": 0, "build": 1},
                    }
                ]
            ),
            "ak.wwise.core.getProjectInfo": deque(
                [
                    {
                        "id": "{33333333-3333-3333-3333-333333333333}",
                        "name": "SampleProject",
                        "path": str(project_path),
                    }
                ]
            ),
            "ak.wwise.core.object.get": deque(
                [
                    {
                        "return": [
                            {
                                "id": OBJECT_ID,
                                "name": "A",
                                "type": "Sound",
                                "path": r"\Actor-Mixer Hierarchy\A",
                                "parent": {"id": "{44444444-4444-4444-4444-444444444444}"},
                                "notes": "before",
                            }
                        ]
                    }
                ]
            ),
        }
        if execute:
            self.responses.update(
                {
                    "ak.wwise.core.undo.beginGroup": deque([{}]),
                    "ak.wwise.core.object.setNotes": deque([{}]),
                    "ak.wwise.core.undo.endGroup": deque([{}]),
                }
            )

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        del args, options
        self.calls.append(uri)
        if uri not in self.responses or not self.responses[uri]:
            raise AssertionError(f"Unexpected or exhausted WAAPI call: {uri}")
        return self.responses[uri].popleft()

    def disconnect(self) -> None:
        pass


def _field_handle(contract: object, path: tuple[str, ...]) -> str:
    matches = [
        field.handle
        for field in contract.fields
        if field.path == path and field.shape == "scalar"
    ]
    assert len(matches) == 1
    return matches[0]


def _apply(composition: dict[str, object], action: dict[str, object], handle: str) -> dict[str, object]:
    updated, _ = apply_composer_action(
        "waapi.undoGroup",
        VERSION,
        composition,
        {"contract": OPERATION_DRAFT_ACTION_CONTRACT, **action},
        handle_factory=lambda: handle,
    )
    return updated


def test_undo_group_materializes_ordered_named_and_generic_typed_children() -> None:
    composition = new_composition("waapi.undoGroup", VERSION)
    composition = _apply(
        composition,
        {"action": "set_display_name", "display_name": "Reviewed edits"},
        "unused",
    )
    composition = _apply(
        composition,
        {"action": "add_child_call", "child_operation": "object.setNotes"},
        "uch1-111111111111111111111111",
    )
    notes = compound_child_request_contract("object.setNotes", VERSION)
    path_value = next(
        field.handle
        for field in notes.fields
        if field.path == ("object", "value")
        and any(variant.get("pattern") == r"^\\" for variant in field.variants)
    )
    path_object = next(
        field.parent_handle
        for field in notes.fields
        if field.handle == path_value
    )
    path_kind = next(
        field.handle
        for field in notes.fields
        if field.parent_handle == path_object and field.path == ("object", "kind")
    )
    branch = next(
        field.handle
        for field in notes.fields
        if field.path == ("object",) and field.shape == "branch"
    )
    notes_handle = _field_handle(notes, ("value",))
    fact_rows = (
        ("choose", branch, "branch", path_object),
        ("set", path_kind, "string", "path"),
        ("set", path_value, "string", r"\Actor-Mixer Hierarchy\A"),
        ("set", notes_handle, "string", "hello"),
    )
    for index, (fact_action, field_handle, value_type, value) in enumerate(fact_rows):
        fact = {
            "action": "add_child_typed_fact",
            "child_handle": "uch1-111111111111111111111111",
            "fact_action": fact_action,
            "field_handle": field_handle,
            "value": value,
        }
        if fact_action != "choose":
            fact["value_type"] = value_type
        composition = _apply(
            composition,
            fact,
            f"tdh1-{index + 1:024x}",
        )

    composition = _apply(
        composition,
        {
            "action": "add_child_call",
            "child_operation": "ak.wwise.core.object.setRandomizer",
        },
        "uch1-222222222222222222222222",
    )
    randomizer = compound_child_request_contract(
        "ak.wwise.core.object.setRandomizer", VERSION
    )
    randomizer_object = next(
        field
        for field in randomizer.fields
        if field.path == ("object",)
        and field.shape == "scalar"
        and any(variant.get("pattern") == r"^\\" for variant in field.variants)
    )
    composition = _apply(
        composition,
        {
            "action": "add_child_typed_fact",
            "child_handle": "uch1-222222222222222222222222",
            "fact_action": "choose",
            "field_handle": randomizer_object.parent_handle,
            "value": randomizer_object.handle,
        },
        f"tdh1-{9:024x}",
    )
    randomizer_facts = (
        (
            randomizer_object.handle,
            "string",
            r"\Actor-Mixer Hierarchy\A",
        ),
        (_field_handle(randomizer, ("property",)), "string", "Volume"),
        (_field_handle(randomizer, ("enabled",)), "boolean", "true"),
    )
    for index, (field_handle, value_type, value) in enumerate(randomizer_facts, 10):
        composition = _apply(
            composition,
            {
                "action": "add_child_typed_fact",
                "child_handle": "uch1-222222222222222222222222",
                "fact_action": "set",
                "field_handle": field_handle,
                "value_type": value_type,
                "value": value,
            },
            f"tdh1-{index:024x}",
        )

    request = materialize_operation_request("waapi.undoGroup", VERSION, composition)
    assert request["operation"] == "waapi.undoGroup"
    assert request["arguments"]["display_name"] == "Reviewed edits"
    assert [row["request"]["operation"] for row in request["arguments"]["calls"]] == [
        "object.setNotes",
        "waapi.call",
    ]
    assert request["arguments"]["calls"][1]["request"]["arguments"]["api"] == (
        "ak.wwise.core.object.setRandomizer"
    )


def test_undo_group_child_contract_rejects_bypass_and_wrong_version() -> None:
    contract = operation_composer_contract("waapi.undoGroup", "2022.1")
    assert "object.setNotes" in contract["child_operations"]
    assert "ak.wwise.core.object.setNotes" not in contract["child_operations"]

    for child in (
        "waapi.call",
        "debug.testCrash",
        "lua.executeCoreFile",
        "ui.commands.execute",
        "soundbank.generate",
        "ak.wwise.core.object.setLinked",
    ):
        with pytest.raises(OperationComposerError):
            apply_composer_action(
                "waapi.undoGroup",
                "2022.1",
                new_composition("waapi.undoGroup", "2022.1"),
                {
                    "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                    "action": "add_child_call",
                    "child_operation": child,
                },
            )


@pytest.mark.parametrize(
    "action",
    (
        {"action": "set_display_name", "display_name": "Batch"},
        {"action": "add_child_call", "child_operation": "object.setNotes"},
        {
            "action": "add_child_typed_fact",
            "child_handle": "uch1-111111111111111111111111",
            "fact_action": "set",
            "field_handle": "trh1-111111111111111111111111",
            "value_type": "string",
            "value": "notes",
        },
        {
            "action": "correct_child_typed_fact",
            "child_handle": "uch1-111111111111111111111111",
            "fact_handle": "tdh1-111111111111111111111111",
            "fact_action": "present",
            "field_handle": "trh1-111111111111111111111111",
        },
        {
            "action": "remove_child_typed_fact",
            "child_handle": "uch1-111111111111111111111111",
            "fact_handle": "tdh1-111111111111111111111111",
        },
        {
            "action": "remove_child_call",
            "child_handle": "uch1-111111111111111111111111",
        },
    ),
)
def test_undo_group_actions_round_trip_through_the_public_cli(
    action: dict[str, str],
) -> None:
    payload = {"contract": OPERATION_DRAFT_ACTION_CONTRACT, **action}
    assert parse_typed_action_cli_arguments(
        typed_action_cli_arguments(payload)
    ) == payload


def test_public_schema_child_discovery_and_first_actions_are_offline(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    offline = lambda url: pytest.fail(f"offline command connected to {url}")
    schema_code, schema = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "operation-schema", "waapi.undoGroup"],
        env=_env(tmp_path), client_factory=offline,
    )
    assert schema_code == 0, schema
    assert schema["composer"]["child_contract_discovery"]["gateway_argv"] == [
        "undo-child-schema", "CHILD_OPERATION"
    ]
    child_code, child = gateway.execute_gateway(
        ["undo-child-schema", "object.setNotes"],
        env=_env(tmp_path), client_factory=offline,
    )
    assert child_code == 0, child
    assert child["typed_request"]["uri"] == "undo-child:object.setNotes"

    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", "waapi.undoGroup"],
        env=_env(tmp_path), client_factory=offline,
    )
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    display_code, displayed = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir), "draft-apply", draft_id,
            "--task-authority", authority, "--expected-revision", "1", "--facts",
            "--action", "set_display_name", "--display-name", "Reviewed batch",
        ], env=_env(tmp_path), client_factory=offline,
    )
    assert display_code == 0, displayed
    child_code, added = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir), "draft-apply", draft_id,
            "--task-authority", authority, "--expected-revision", "2", "--facts",
            "--action", "add_child_call", "--child-operation", "object.setNotes",
        ], env=_env(tmp_path), client_factory=offline,
    )
    assert child_code == 0, added
    assert added["draft"]["revision"] == 3
    inspected = gateway.OperationDraftStore(state_dir).inspect(
        draft_id, task_authority=authority
    )
    assert inspected.composition["calls"][0]["operation"] == "object.setNotes"


def test_public_complex_child_schema_issues_nonempty_inclusion_row_handle(
    tmp_path: Path,
) -> None:
    offline = lambda url: pytest.fail(f"offline command connected to {url}")
    schema_code, schema = gateway.execute_gateway(
        ["undo-child-schema", "soundbank.setInclusions"],
        env=_env(tmp_path), client_factory=offline,
    )
    assert schema_code == 0, schema
    typed = schema["typed_request"]
    inclusions = next(
        field for field in typed["fields"]
        if field["path"] == ["args", "inclusions"]
    )
    item_code, item = gateway.execute_gateway(
        [
            "request-array-item", "undo-child:soundbank.setInclusions",
            "--schema-digest", typed["schema_digest"],
            "--array-handle", inclusions["handle"],
            "--index", "0", "--shape", "object",
        ],
        env=_env(tmp_path), client_factory=offline,
    )
    assert item_code == 0, item
    assert item["child_contract"]["required_keys"] == ["object", "filters"]
    object_choices = next(
        row for row in item["child_contract"]["branch_choices"]
        if row["key"] == "object"
    )
    assert len(object_choices["choices"]) == 5
    assert item["continuation"]["subcommand"] == "draft-apply"
    action_argv = item["continuation"]["action_argv"]
    assert action_argv[:4] == [
        "--action", "add_child_typed_fact", "--child-handle", "<child_handle>"
    ]
    assert action_argv[-1] == item["handle"]
    assert item["continuation"]["branch_disclosure"][1] == (
        "undo-child:soundbank.setInclusions"
    )

    wrong_code, wrong = gateway.execute_gateway(
        ["request-schema", "undo-child:soundbank.setInclusions"],
        env=_env(tmp_path), client_factory=offline,
    )
    assert wrong_code == 2, wrong
    assert "undo-child-schema" in wrong["message"]


def test_public_undo_draft_seals_executes_once_and_replays_one_preview(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "public-state"
    offline = lambda url: pytest.fail(f"offline command connected to {url}")
    start_code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", "waapi.undoGroup"],
        env=_env(tmp_path), client_factory=offline,
    )
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    revision = 1

    def apply(action: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal revision
        argv = [
            "--state-dir", str(state_dir), "draft-apply", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(revision), "--facts",
            *typed_action_cli_arguments(
                {"contract": OPERATION_DRAFT_ACTION_CONTRACT, **action}
            ),
        ]
        code, payload = gateway.execute_gateway(
            argv, env=_env(tmp_path), client_factory=offline
        )
        assert code == 0, payload
        revision = payload["draft"]["revision"]
        return payload

    apply({"action": "set_display_name", "display_name": "Public reviewed batch"})
    apply({"action": "add_child_call", "child_operation": "object.setNotes"})
    inspected = gateway.OperationDraftStore(state_dir).inspect(
        draft_id, task_authority=authority
    )
    child_handle = inspected.composition["calls"][0]["handle"]
    contract = compound_child_request_contract("object.setNotes", VERSION)
    branch = next(
        field for field in contract.fields
        if field.path == ("object",) and field.shape == "branch"
    )
    id_object = next(
        field for field in contract.fields
        if field.path == ("object",)
        and field.shape == "object"
        and any(
            nested.parent_handle == field.handle
            and nested.path == ("object", "kind")
            and any(variant.get("const") == "id" for variant in nested.variants)
            for nested in contract.fields
        )
    )
    id_kind = next(
        field for field in contract.fields
        if field.parent_handle == id_object.handle and field.path == ("object", "kind")
    )
    id_value = next(
        field for field in contract.fields
        if field.parent_handle == id_object.handle and field.path == ("object", "value")
    )
    notes = _field_handle(contract, ("value",))
    for fact_action, field_handle, value_type, value in (
        ("choose", branch.handle, None, id_object.handle),
        ("set", id_kind.handle, "string", "id"),
        ("set", id_value.handle, "string", OBJECT_ID),
        ("set", notes, "string", "after"),
    ):
        action: dict[str, Any] = {
            "action": "add_child_typed_fact",
            "child_handle": child_handle,
            "fact_action": fact_action,
            "field_handle": field_handle,
            "value": value,
        }
        if value_type is not None:
            action["value_type"] = value_type
        apply(action)

    expected = materialize_operation_request(
        "waapi.undoGroup",
        VERSION,
        gateway.OperationDraftStore(state_dir).inspect(
            draft_id, task_authority=authority
        ).composition,
    )
    check_code, checked = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir), "draft-check", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(revision),
        ],
        env=_env(tmp_path), client_factory=lambda _url: _Client(tmp_path),
    )
    assert check_code == 0, json.dumps(checked, indent=2)
    checked_revision = checked["draft"]["revision"]
    preview_argv = [
        "--state-dir", str(state_dir), "preview-from-draft", draft_id,
        "--task-authority", authority,
        "--expected-revision", str(checked_revision), "--apply",
    ]
    preview_code, previewed = gateway.execute_gateway(
        preview_argv,
        env=_env(tmp_path), client_factory=lambda _url: _Client(tmp_path),
    )
    assert preview_code == 0, previewed
    assert previewed["agent_result"]["request"] == expected
    store = TransactionStore(state_dir)
    record = store.load_preview(previewed["transaction_id"])
    assert record.artifact["request"] == expected
    plan = record.artifact["prepared_operation"]["pre_state"]["execution_plan"]
    assert all(
        phase["timeout_seconds"] > 0 and phase["result_limit_bytes"] > 0
        for phase in (plan["begin"], *plan["calls"], plan["end"], plan["cancel"])
    )
    preview_events = store.read_events(previewed["transaction_id"])
    replay_code, replayed = gateway.execute_gateway(
        preview_argv,
        env=_env(tmp_path), client_factory=lambda _url: _Client(tmp_path),
    )
    assert replay_code == 0, replayed
    assert replayed["transaction_id"] == previewed["transaction_id"]
    assert store.read_events(previewed["transaction_id"]) == preview_events

    confirm_code, confirmed = gateway.execute_gateway(
        [
            "--state-dir", str(state_dir), "confirm", previewed["transaction_id"],
            "--confirmation-token",
            store.load_snapshot(previewed["transaction_id"]).confirmation_token,
        ],
        env=_env(tmp_path), client_factory=offline,
    )
    assert confirm_code == 0, confirmed
    execute_client = _Client(tmp_path, execute=True)
    execute_code, executed = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "execute", previewed["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _url: execute_client,
    )
    assert execute_code == 0, executed
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert execute_client.calls.count("ak.wwise.core.object.setNotes") == 1
    verify_code, verified = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "verify", previewed["transaction_id"]],
        env=_env(tmp_path), client_factory=lambda _url: _Client(tmp_path),
    )
    assert verify_code == 0, verified
    assert verified["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    final_events = store.read_events(previewed["transaction_id"])
    assert [event["event_type"] for event in final_events].count("execution_started") == 1
    assert [event["event_type"] for event in final_events].count("execution_completed") == 1
