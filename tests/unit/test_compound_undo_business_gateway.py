from __future__ import annotations

import json
from pathlib import Path

from tests.unit.test_operation_input_gateway import (
    OBJECT_GUID,
    ObjectLifecycleClient,
    gateway_env,
    offline_execute,
    waapi_gateway,
)
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.operation_drafts import OperationDraftStore
from wwise_waapi.transactions import TransactionState, TransactionStore


def _checked_object_child(
    tmp_path: Path,
    state_dir: Path,
    *,
    operation: str,
    value_flag: str,
    value: str,
    client: ObjectLifecycleClient,
    parent: tuple[str, str, int] | None = None,
) -> tuple[str, str, str, int]:
    start_arguments = (
        (
            "--state-dir", str(state_dir),
            "--version", "2022.1",
            "draft-start", operation,
        )
        if parent is None
        else (
            "--state-dir", str(state_dir),
            "draft-start-undo-child", parent[0],
            "--task-authority", parent[1],
            "--expected-revision", str(parent[2]),
            "--operation", operation,
        )
    )
    code, started = offline_execute(tmp_path, *start_arguments)
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    code, bound = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-bind-object", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(started["draft"]["revision"]),
            "--object-id", OBJECT_GUID,
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, bound
    code, declared = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "draft-declare-object-change", draft_id,
        "--task-authority", authority,
        "--expected-revision", str(bound["draft"]["revision"]),
        "--object-handle", bound["bound_object"]["handle"],
        value_flag, value,
    )
    assert code == 0, declared
    code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-check", draft_id,
            "--task-authority", authority,
            "--expected-revision", str(declared["draft"]["revision"]),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked
    return (
        draft_id,
        authority,
        bound["bound_object"]["handle"],
        checked["draft"]["revision"],
    )


def test_parent_owned_compound_child_returns_handoff_and_cannot_preview(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = ObjectLifecycleClient()
    code, parent = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "--version", "2022.1",
        "draft-start", "waapi.undoGroup",
    )
    assert code == 0, parent
    parent_id = parent["draft"]["draft_id"]
    parent_authority = parent["task_authority"]
    parent_start = parent["draft"]["next_action_binding"]["start_child"]
    assert "draft-start-undo-child" in parent_start["fixed_argv_prefix_copy"]
    assert parent_start["append"] == [
        "--operation <eligible-child-operation>"
    ]
    code, child = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "draft-start-undo-child", parent_id,
        "--task-authority", parent_authority,
        "--expected-revision", str(parent["draft"]["revision"]),
        "--operation", "object.setNotes",
    )
    assert code == 0, child
    child_id = child["draft"]["draft_id"]
    child_authority = child["task_authority"]
    code, bound = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-bind-object", child_id,
            "--task-authority", child_authority,
            "--expected-revision", str(child["draft"]["revision"]),
            "--object-id", OBJECT_GUID,
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, bound
    code, declared = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "draft-declare-object-change", child_id,
        "--task-authority", child_authority,
        "--expected-revision", str(bound["draft"]["revision"]),
        "--object-handle", bound["bound_object"]["handle"],
        "--notes", "Exterior rain loop",
    )
    assert code == 0, declared
    code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-check", child_id,
            "--task-authority", child_authority,
            "--expected-revision", str(declared["draft"]["revision"]),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked
    assert "next_command" not in checked
    assert "preview-from-draft" not in checked["draft"]["allowed_actions"]
    handoff = checked["draft"]["next_action_binding"]
    assert handoff["required_next_phase"] == (
        "return_checked_child_to_compound_parent"
    )
    assert handoff["checked_child_argument"] == [
        "--child-draft",
        child_id,
        child_authority,
    ]
    assert "draft-start-undo-child" in handoff["start_next_child"][
        "fixed_argv_prefix_copy"
    ]

    code, rejected = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "preview-from-draft", child_id,
            "--task-authority", child_authority,
            "--expected-revision", str(checked["draft"]["revision"]),
            "--apply",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 2
    assert "Compound Undo child" in rejected["message"]


def test_compound_undo_rejects_checked_child_not_owned_by_parent(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = ObjectLifecycleClient()
    child = _checked_object_child(
        tmp_path,
        state_dir,
        operation="object.setNotes",
        value_flag="--notes",
        value="unlinked",
        client=client,
    )
    code, parent = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "--version", "2022.1",
        "draft-start", "waapi.undoGroup",
    )
    assert code == 0, parent
    code, rejected = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-declare-undo-plan", parent["draft"]["draft_id"],
            "--task-authority", parent["task_authority"],
            "--expected-revision", str(parent["draft"]["revision"]),
            "--display-name", "Reject unlinked child",
            "--child-draft", child[0], child[1],
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 2
    assert "parent-owned" in rejected["message"]


def test_public_compound_undo_snapshots_checked_business_children_into_one_preview(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = ObjectLifecycleClient()
    code, started = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "--version", "2022.1",
        "draft-start", "waapi.undoGroup",
    )
    assert code == 0, started
    parent_id = started["draft"]["draft_id"]
    parent_authority = started["task_authority"]
    parent = (parent_id, parent_authority, started["draft"]["revision"])
    notes = _checked_object_child(
        tmp_path,
        state_dir,
        operation="object.setNotes",
        value_flag="--notes",
        value="first",
        client=client,
        parent=parent,
    )
    rename = _checked_object_child(
        tmp_path,
        state_dir,
        operation="object.setName",
        value_flag="--new-name",
        value="Second",
        client=client,
        parent=parent,
    )
    code, declared = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-declare-undo-plan", parent_id,
            "--task-authority", parent_authority,
            "--expected-revision", str(started["draft"]["revision"]),
            "--display-name", "Reviewed batch",
            "--child-draft", notes[0], notes[1],
            "--child-draft", rename[0], rename[1],
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, declared
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_compound_undo_plan"
    )
    record = OperationDraftStore(state_dir).inspect(
        parent_id,
        task_authority=parent_authority,
    )
    session = BusinessDeclarationSession.from_dict(
        record.composition["business_session"]
    )
    children = session.settings["undo_plan"]["children"]
    assert [row["operation"] for row in children] == [
        "object.setNotes",
        "object.setName",
    ]
    assert all("handle" not in row for row in children)

    code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-check", parent_id,
            "--task-authority", parent_authority,
            "--expected-revision", str(declared["draft"]["revision"]),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked
    code, previewed = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "preview-from-draft", parent_id,
            "--task-authority", parent_authority,
            "--expected-revision", str(checked["draft"]["revision"]),
            "--apply",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, previewed
    assert previewed["state"] == TransactionState.AWAITING_CONFIRMATION.value
    artifact = TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact
    request = artifact["request"]
    assert [row["request"]["operation"] for row in request["arguments"]["calls"]] == [
        "object.setNotes",
        "object.setName",
    ]
    plan = artifact["prepared_operation"]["pre_state"]["execution_plan"]
    assert [row["child_operation"] for row in plan["calls"]] == [
        "object.setNotes",
        "object.setName",
    ]
    assert plan["begin"]["uri"] == "ak.wwise.core.undo.beginGroup"
    assert plan["end"]["args"] == {"displayName": "Reviewed batch"}
    assert plan["cancel"]["uri"] == "ak.wwise.core.undo.cancelGroup"


def test_compound_undo_rejects_unchecked_or_stale_child_before_parent_write(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    code, parent = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "--version", "2022.1",
        "draft-start", "waapi.undoGroup",
    )
    assert code == 0, parent
    code, child = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "draft-start-undo-child", parent["draft"]["draft_id"],
        "--task-authority", parent["task_authority"],
        "--expected-revision", str(parent["draft"]["revision"]),
        "--operation", "object.setNotes",
    )
    assert code == 0, child
    code, rejected = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-declare-undo-plan", parent["draft"]["draft_id"],
            "--task-authority", parent["task_authority"],
            "--expected-revision", str(parent["draft"]["revision"]),
            "--display-name", "Rejected batch",
            "--child-draft", child["draft"]["draft_id"], child["task_authority"],
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: ObjectLifecycleClient(),
    )

    assert code == 2
    assert "must be checked" in rejected["message"] or "cannot materialize" in rejected[
        "message"
    ]
    parent_record = OperationDraftStore(state_dir).inspect(
        parent["draft"]["draft_id"],
        task_authority=parent["task_authority"],
    )
    assert parent_record.revision == parent["draft"]["revision"]
    assert "business_session" not in parent_record.composition


def test_compound_undo_repair_preserves_hostile_business_values_exactly(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = ObjectLifecycleClient()
    code, unchecked = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "--version", "2022.1",
        "draft-start", "object.setNotes",
    )
    assert code == 0, unchecked
    code, parent = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "--version", "2022.1",
        "draft-start", "waapi.undoGroup",
    )
    assert code == 0, parent
    parent_id = parent["draft"]["draft_id"]
    parent_authority = parent["task_authority"]
    parent_revision = parent["draft"]["revision"]
    code, rejected = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-declare-undo-plan", parent_id,
            "--task-authority", parent_authority,
            "--expected-revision", str(parent_revision),
            "--display-name", "first rejected declaration",
            "--child-draft", unchecked["draft"]["draft_id"],
            unchecked["task_authority"],
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 2, rejected

    hostile_notes = "原样备注 \"quoted\"\n$(not-a-command) & | < > \\"
    hostile_display_name = "撤销 \"quoted\"\n$(not-a-command) & | < > \\"
    repaired_child = _checked_object_child(
        tmp_path,
        state_dir,
        operation="object.setNotes",
        value_flag="--notes",
        value=hostile_notes,
        client=client,
        parent=(parent_id, parent_authority, parent_revision),
    )
    code, declared = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-declare-undo-plan", parent_id,
            "--task-authority", parent_authority,
            "--expected-revision", str(parent_revision),
            "--display-name", hostile_display_name,
            "--child-draft", repaired_child[0], repaired_child[1],
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, declared
    code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-check", parent_id,
            "--task-authority", parent_authority,
            "--expected-revision", str(declared["draft"]["revision"]),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked
    code, previewed = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "preview-from-draft", parent_id,
            "--task-authority", parent_authority,
            "--expected-revision", str(checked["draft"]["revision"]),
            "--apply",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, previewed
    request = TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact["request"]
    assert request["arguments"]["display_name"] == hostile_display_name
    assert request["arguments"]["calls"][0]["request"]["arguments"][
        "value"
    ] == hostile_notes


def test_compound_undo_rejects_two_children_that_own_the_same_final_outcome(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = ObjectLifecycleClient()
    code, parent = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "--version", "2022.1",
        "draft-start", "waapi.undoGroup",
    )
    assert code == 0, parent
    parent_binding = (
        parent["draft"]["draft_id"],
        parent["task_authority"],
        parent["draft"]["revision"],
    )
    first = _checked_object_child(
        tmp_path,
        state_dir,
        operation="object.setNotes",
        value_flag="--notes",
        value="first",
        client=client,
        parent=parent_binding,
    )
    second = _checked_object_child(
        tmp_path,
        state_dir,
        operation="object.setNotes",
        value_flag="--notes",
        value="second",
        client=client,
        parent=parent_binding,
    )
    code, declared = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-declare-undo-plan", parent["draft"]["draft_id"],
            "--task-authority", parent["task_authority"],
            "--expected-revision", str(parent["draft"]["revision"]),
            "--display-name", "overlapping notes",
            "--child-draft", first[0], first[1],
            "--child-draft", second[0], second[1],
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, declared
    code, rejected = waapi_gateway.execute_gateway(
        [
            "--state-dir", str(state_dir),
            "draft-check", parent["draft"]["draft_id"],
            "--task-authority", parent["task_authority"],
            "--expected-revision", str(declared["draft"]["revision"]),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 2, rejected
    assert rejected["error_code"] == "UNDO_GROUP_OVERLAPPING_OUTCOME"


def test_migrated_core_child_exposes_business_draft_without_typed_fallback(
    tmp_path: Path,
) -> None:
    operation = "ak.wwise.core.object.setRandomizer"
    code, schema = offline_execute(
        tmp_path,
        "--version",
        "2022.1",
        "request-schema",
        operation,
    )
    assert code == 0, schema
    assert schema["input_shape"] == "business_declaration"
    assert schema["business_adapter"]["execution_shape"] == "draft_mutation"
    assert schema["continuation"]["subcommand"] == "draft-start"
    assert "typed-call" not in json.dumps(schema, sort_keys=True)


def test_compound_undo_rejects_child_changed_after_check_before_parent_snapshot(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = ObjectLifecycleClient()
    code, parent = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "--version", "2022.1",
        "draft-start", "waapi.undoGroup",
    )
    assert code == 0, parent
    parent_binding = (
        parent["draft"]["draft_id"],
        parent["task_authority"],
        parent["draft"]["revision"],
    )
    child_id, child_authority, _object_handle, checked_revision = (
        _checked_object_child(
            tmp_path,
            state_dir,
            operation="object.setNotes",
            value_flag="--notes",
            value="first",
            client=client,
            parent=parent_binding,
        )
    )
    code, cancelled = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "draft-cancel",
        child_id,
        "--task-authority",
        child_authority,
        "--expected-revision",
        str(checked_revision),
    )
    assert code == 0, cancelled
    code, rejected = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-declare-undo-plan",
            parent["draft"]["draft_id"],
            "--task-authority",
            parent["task_authority"],
            "--expected-revision",
            str(parent["draft"]["revision"]),
            "--display-name",
            "Rejected stale child",
            "--child-draft",
            child_id,
            child_authority,
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert "must be checked" in rejected["message"] or "cannot materialize" in rejected[
        "message"
    ]
    parent_record = OperationDraftStore(state_dir).inspect(
        parent["draft"]["draft_id"],
        task_authority=parent["task_authority"],
    )
    assert parent_record.revision == parent["draft"]["revision"]


def test_parent_snapshot_is_unchanged_when_checked_child_is_revised_later(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = ObjectLifecycleClient()
    code, parent = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "--version", "2022.1",
        "draft-start", "waapi.undoGroup",
    )
    assert code == 0, parent
    parent_binding = (
        parent["draft"]["draft_id"],
        parent["task_authority"],
        parent["draft"]["revision"],
    )
    child_id, child_authority, _object_handle, checked_revision = (
        _checked_object_child(
            tmp_path,
            state_dir,
            operation="object.setNotes",
            value_flag="--notes",
            value="snapshotted",
            client=client,
            parent=parent_binding,
        )
    )
    code, declared = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-declare-undo-plan",
            parent["draft"]["draft_id"],
            "--task-authority",
            parent["task_authority"],
            "--expected-revision",
            str(parent["draft"]["revision"]),
            "--display-name",
            "Stable snapshot",
            "--child-draft",
            child_id,
            child_authority,
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, declared

    code, cancelled = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "draft-cancel",
        child_id,
        "--task-authority",
        child_authority,
        "--expected-revision",
        str(checked_revision),
    )
    assert code == 0, cancelled

    code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-check",
            parent["draft"]["draft_id"],
            "--task-authority",
            parent["task_authority"],
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, checked
    record = OperationDraftStore(state_dir).inspect(
        parent["draft"]["draft_id"],
        task_authority=parent["task_authority"],
    )
    session = BusinessDeclarationSession.from_dict(
        record.composition["business_session"]
    )
    snapshotted = session.settings["undo_plan"]["children"][0]
    assert snapshotted["request"]["arguments"]["value"] == "snapshotted"
