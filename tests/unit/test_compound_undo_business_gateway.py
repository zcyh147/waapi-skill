from __future__ import annotations

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
) -> tuple[str, str, str, int]:
    code, started = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "--version",
        "2022.1",
        "draft-start",
        operation,
    )
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


def test_public_compound_undo_snapshots_checked_business_children_into_one_preview(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = ObjectLifecycleClient()
    notes = _checked_object_child(
        tmp_path,
        state_dir,
        operation="object.setNotes",
        value_flag="--notes",
        value="first",
        client=client,
    )
    rename = _checked_object_child(
        tmp_path,
        state_dir,
        operation="object.setName",
        value_flag="--new-name",
        value="Second",
        client=client,
    )
    code, started = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "--version", "2022.1",
        "draft-start", "waapi.undoGroup",
    )
    assert code == 0, started
    parent_id = started["draft"]["draft_id"]
    parent_authority = started["task_authority"]
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
    code, child = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "--version", "2022.1",
        "draft-start", "object.setNotes",
    )
    assert code == 0, child
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


def test_generic_undo_child_is_not_promoted_to_a_checked_business_draft(
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
    assert schema["input_shape"] == "inline"
    assert "draft_requirement" not in schema


def test_compound_undo_rejects_child_changed_after_check_before_parent_snapshot(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = ObjectLifecycleClient()
    child_id, child_authority, _object_handle, checked_revision = (
        _checked_object_child(
            tmp_path,
            state_dir,
            operation="object.setNotes",
            value_flag="--notes",
            value="first",
            client=client,
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
    code, parent = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "--version",
        "2022.1",
        "draft-start",
        "waapi.undoGroup",
    )
    assert code == 0, parent

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
    child_id, child_authority, _object_handle, checked_revision = (
        _checked_object_child(
            tmp_path,
            state_dir,
            operation="object.setNotes",
            value_flag="--notes",
            value="snapshotted",
            client=client,
        )
    )
    code, parent = offline_execute(
        tmp_path,
        "--state-dir",
        str(state_dir),
        "--version",
        "2022.1",
        "draft-start",
        "waapi.undoGroup",
    )
    assert code == 0, parent
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
