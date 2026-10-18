from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    object_handle = bound["bound_object"]["handle"]
    declaration_binding = bound["draft"]["next_action_binding"]["declaration"]
    assert declaration_binding["append"] == [
        value_flag,
        {
            "--notes": "<exact-notes>",
            "--new-name": "<exact-new-name>",
        }[value_flag],
    ]
    assert declaration_binding["opaque_handles_inferred_from_bound_roles"] is True
    assert "append_fields" not in declaration_binding
    code, declared = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),
        "draft-declare-object-change", draft_id,
        "--task-authority", authority,
        "--expected-revision", str(bound["draft"]["revision"]),
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

        "draft-start", "object.setNotes",
    )
    assert code == 0, unchecked
    code, parent = offline_execute(
        tmp_path,
        "--state-dir", str(state_dir),

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


def _preview_cancellation_case(tmp_path, client, *, version, cancellation, declaration_error=None, property_child=False, duplicate_property=False, parent_check_error=None, second_platform=None, child_ids=None, first_platform=None, reference_child=False):
    state_dir = tmp_path / "state"
    env = gateway_env(tmp_path, version=version)
    def run(*argv):
        code, payload = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), *argv],
            env=env, client_factory=lambda _url: client)
        assert code == 0, json.dumps(payload, ensure_ascii=False)
        return payload
    parent = run("draft-start", "waapi.undoGroup")
    draft, authority, revision = parent["draft"]["draft_id"], parent["task_authority"], str(parent["draft"]["revision"])
    children = []
    child_specs = (("object.setReference", "--target-handle", "") if reference_child else
                   ("object.setProperty", "--business-value", "2") if property_child else
                   ("object.setNotes", "--notes", "after"),
                   ("object.setProperty", "--business-value", "3") if duplicate_property else ("object.setName", "--new-name", "Renamed"))
    for child_index, (operation, flag, value) in enumerate(child_specs):
        phase = run("draft-start-undo-child", draft, "--task-authority", authority,
                    "--expected-revision", revision, "--operation", operation)
        child, child_authority = phase["draft"]["draft_id"], phase["task_authority"]
        phase = run("draft-bind-object", child, "--task-authority", child_authority,
                    "--expected-revision", str(phase["draft"]["revision"]), "--object-id",
                    child_ids[child_index] if child_ids else OBJECT_GUID)
        if operation in {"object.setProperty", "object.setReference"}:
            object_handle = phase["bound_object"]["handle"]
            if operation == "object.setReference":
                phase = run("draft-bind-object", child, "--task-authority", child_authority,
                    "--expected-revision", str(phase["draft"]["revision"]), "--object-id", client.parent["id"])
                value = phase["bound_object"]["handle"]
            phase = run("draft-discover-fields", child, "--task-authority", child_authority,
                "--expected-revision", str(phase["draft"]["revision"]), "--object-handle", object_handle,
                "--meaning", "attenuation" if reference_child else "volume",
                *(("--platform", first_platform) if child_index == 0 and first_platform else ()),
                *(("--platform", second_platform) if child_index == 1 and second_platform else ()))
            phase = run("draft-declare-field-change", child, "--task-authority", child_authority,
                "--expected-revision", str(phase["draft"]["revision"]), "--object-handle", object_handle,
                "--field-handle", phase["field_candidates"][0]["handle"], flag, value)
        else:
            phase = run("draft-declare-object-change", child, "--task-authority", child_authority,
                        "--expected-revision", str(phase["draft"]["revision"]), flag, value)
        run("draft-check", child, "--task-authority", child_authority, "--expected-revision", str(phase["draft"]["revision"]))
        children.extend(("--child-draft", child, child_authority))
    declaration = ("draft-declare-undo-plan", draft, "--task-authority", authority,
        "--expected-revision", revision, "--display-name", "Cancellation case", *children,
        "--failure-cancellation", cancellation)
    if declaration_error:
        code, rejected = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), *declaration],
            env=env, client_factory=lambda _url: client)
        assert code == 2 and declaration_error in json.dumps(rejected), rejected
        return state_dir, env, rejected
    phase = run(*declaration)
    check = ("draft-check", draft, "--task-authority", authority, "--expected-revision", str(phase["draft"]["revision"]))
    if parent_check_error:
        code, rejected = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), *check],
            env=env, client_factory=lambda _url: client)
        assert code == 2 and parent_check_error in json.dumps(rejected), rejected
        return state_dir, env, rejected
    phase = run(*check)
    preview = run("preview-from-draft", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]), "--apply")
    shown = run("transaction-show", preview["transaction_id"], "--summary-only")
    run(*shown["next_command"]["gateway_argv"])
    return state_dir, env, preview


def _cancellation_client(version, *, fault=None):
    from tests.unit.test_object_graph_business_gateway import _info
    class Client(ObjectLifecycleClient):
        def __init__(self):
            super().__init__()
            if fault == "missing-notes-before":
                self.source.pop("notes")
            self.before = dict(self.source)
        def call(self, uri, native_args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if version == "2021.1" and uri == "ak.wwise.core.object.get" and native_args.get("waql") == "from type Project take 1":
                from tests.unit.test_operation_input_gateway import project_row
                project = project_row()
                return {"return": [{**project, "type": "Project", "filePath": project["path"]}]}
            if uri == "ak.wwise.core.object.get" and getattr(self, "cancelled", False) and fault == "read-error":
                raise RuntimeError("fixture cancellation observation unavailable")
            if uri.startswith("ak.wwise.core.undo."):
                self.calls.append((uri, native_args, options))
                if uri.endswith("cancelGroup"):
                    self.cancelled = True
                    if fault == "cancel-error":
                        return {"fixture_invalid_cancel_result": True}
                    if native_args.get("undo") is True and fault != "not-restored":
                        self.source = dict(self.before)
                return {}
            if uri in {"ak.wwise.core.object.setNotes", "ak.wwise.core.object.setName"}:
                self.calls.append((uri, native_args, options))
                if uri.endswith("setNotes"):
                    self.source["notes"] = native_args["value"]
                    return {}
                self.source.update(name=native_args["value"], path="\\Actor-Mixer Hierarchy\\Default Work Unit\\" + native_args["value"])
                if fault == "child-exception":
                    raise RuntimeError("fixture unknown rename outcome")
                return {"fixture_invalid_native_result": True}
            return super().call(uri, native_args, options)
    return Client()


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("cancellation,args", (("undo-changes", {"undo": True}),
    ("preserve-changes", {"undo": False}), ("native-default", {})))
def test_compound_failure_cancellation_keeps_native_choices_and_observes_partial_state(tmp_path, version, cancellation, args):
    client = _cancellation_client(version)
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version=version, cancellation=cancellation)
    plan = TransactionStore(state_dir).load_preview(preview["transaction_id"]).artifact["prepared_operation"]["pre_state"]["execution_plan"]
    assert plan["cancel"]["args"] == args
    code, result = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and result["status"] == "execution_cancelled", json.dumps(result, ensure_ascii=False)
    assert result["rollback_verified"] is (cancellation == "undo-changes")
    observation = result["compound_execution"]["cancellation_observation"]
    assert observation["complete"] is True
    assert observation["pre_state_restored"] is (cancellation == "undo-changes")
    assert observation["scope"] == "sealed_child_preflight_readbacks_only"
    assert result["verified"] is False and result["automatic_retry"] is False
    writes = [call for call in client.calls if call[0].startswith("ak.wwise.core.undo.") or call[0] in {
        "ak.wwise.core.object.setNotes", "ak.wwise.core.object.setName"}]
    assert [call[0] for call in writes] == ["ak.wwise.core.undo.beginGroup", "ak.wwise.core.object.setNotes",
        "ak.wwise.core.object.setName", "ak.wwise.core.undo.cancelGroup"]
    assert writes[-1][1] == args


@pytest.mark.parametrize("fault", ("not-restored", "read-error", "cancel-error", "read-budget", "byte-budget", "missing-notes-before"))
def test_compound_cancellation_does_not_turn_acknowledgement_or_missing_reads_into_rollback(tmp_path, monkeypatch, fault):
    from wwise_waapi import compound_undo_observation
    client = _cancellation_client("2025.1", fault=fault)
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version="2025.1", cancellation="undo-changes")
    if fault == "read-budget":
        monkeypatch.setattr(compound_undo_observation, "MAX_CANCELLATION_READS", 0)
    if fault == "byte-budget":
        monkeypatch.setattr(compound_undo_observation, "MAX_CANCELLATION_OBSERVATION_BYTES", 4096)
    code, result = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and result["verified"] is False, result
    assert result.get("rollback_verified", False) is False
    assert result["automatic_retry"] is False
    if fault == "cancel-error":
        assert result["status"] == "indeterminate" and "cancellation_observation" not in result["compound_execution"]
    else:
        observed = result["compound_execution"]["cancellation_observation"]
        assert observed["pre_state_restored"] is False
        assert observed["complete"] is (fault == "not-restored")
        if fault in {"read-error", "read-budget", "byte-budget"}:
            assert all(row["complete"] is False for row in observed["children"])
        assert len(json.dumps(observed).encode()) <= compound_undo_observation.MAX_CANCELLATION_OBSERVATION_BYTES
    writes = [row for row in client.calls if row[0] in {"ak.wwise.core.object.setNotes", "ak.wwise.core.object.setName"}]
    assert len(writes) == 2
    code, repeated = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2
    assert len([row for row in client.calls if row[0] in {"ak.wwise.core.object.setNotes", "ak.wwise.core.object.setName"}]) == 2


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_compound_cancellation_discovery_retains_exact_version_choices(tmp_path, version):
    code, result = offline_execute(tmp_path, "--version", version, "operation-schema", "waapi.undoGroup", version=version)
    assert code == 0, result
    choices = result["business_adapter"]["declaration"]["failure_cancellation"]["choices"]
    assert choices == (["native-default"] if version in {"2021.1", "2022.1"}
                       else ["undo-changes", "preserve-changes", "native-default"])


def test_compound_client_error_retains_failure_and_scoped_restoration_without_replay(tmp_path):
    client = _cancellation_client("2025.1", fault="child-exception")
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version="2025.1", cancellation="undo-changes")
    code, result = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and result["status"] == "execution_cancelled", result
    assert result["compound_execution"]["failed_phase"]["failure"]["kind"] == "dispatch_failed"
    assert "fixture unknown rename outcome" in json.dumps(result["compound_execution"]["failed_phase"])
    assert result["compound_execution"]["cancellation_observation"]["pre_state_restored"] is True
    assert result["verified"] is False and result["automatic_retry"] is False
    assert len([row for row in client.calls if row[0].endswith("cancelGroup")]) == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
def test_older_compound_native_default_is_observed_without_inventing_undo_option(tmp_path, version):
    client = _cancellation_client(version)
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version=version, cancellation="native-default")
    code, result = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and result["status"] == "execution_cancelled", result
    assert [row[1] for row in client.calls if row[0].endswith("cancelGroup")] == [{}]
    assert result["rollback_verified"] is False
    assert result["compound_execution"]["cancellation_observation"]["complete"] is True


@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
@pytest.mark.parametrize("cancellation", ("undo-changes", "preserve-changes"))
def test_older_compound_rejects_unpinned_cancel_option_before_parent_preview(tmp_path, version, cancellation):
    client = _cancellation_client(version)
    state_dir, _env, _rejected = _preview_cancellation_case(tmp_path, client, version=version,
        cancellation=cancellation, declaration_error="UNSUPPORTED_CANCELLATION_OPTION")
    assert not (state_dir / "transactions").exists()
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


def test_compound_cancellation_observation_keeps_matching_read_contract_byte_limit(tmp_path):
    from copy import deepcopy
    client = _cancellation_client("2025.1")
    original = client.call

    def oversized_after_cancel(uri, native_args=None, options=None):
        result = original(uri, native_args, options)
        if (uri == "ak.wwise.core.object.get" and getattr(client, "cancelled", False)
                and native_args.get("from", {}).get("id") == [OBJECT_GUID]):
            result = deepcopy(result)
            result["return"][0]["notes"] = "x" * (300 * 1024)
        return result

    client.call = oversized_after_cancel
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version="2025.1", cancellation="undo-changes")
    code, result = waapi_gateway.execute_gateway([
        "--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and result["status"] == "execution_cancelled", result
    observed = result["compound_execution"]["cancellation_observation"]
    assert observed["complete"] is False, observed
    assert observed["pre_state_restored"] is False and result["rollback_verified"] is False
    assert any(read.get("call", {}).get("error_code") == "RESULT_TOO_LARGE" for read in observed["readbacks"]), observed
    assert result["verified"] is False and result["automatic_retry"] is False
    assert len([uri for uri, _args, _options in client.calls if uri.endswith("cancelGroup")]) == 1


def _property_cancellation_client(version, *, wrong_scalar=False):
    client = _cancellation_client(version)
    client.source["@Volume"] = 1.0
    client.before = dict(client.source)
    client.current_platform = "{44444444-4444-4444-4444-444444444444}"
    client.linked = True
    client.platform_values = {"{44444444-4444-4444-4444-444444444444}": 1.0,
                              "{55555555-5555-5555-5555-555555555555}": 1.0}
    client.platform_names = {"Windows": "{44444444-4444-4444-4444-444444444444}",
                             "Mac": "{55555555-5555-5555-5555-555555555555}"}
    original = client.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.getProjectInfo":
            result = original(uri, args, options)
            return {**result, "currentPlatformId": client.current_platform,
                    "platforms": [{"id": object_id, "name": name}
                                  for name, object_id in client.platform_names.items()]}
        if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            client.calls.append((uri, args, options))
            return {"return": ["Volume"]}
        if uri == "ak.wwise.core.object.getPropertyInfo":
            client.calls.append((uri, args, options))
            return {"name": "Volume", "type": "Real32", "default": 0,
                    "restriction": {"type": "range", "min": -96, "max": 6},
                    "supports": {"unlink": True}}
        if uri == "ak.wwise.core.object.isLinked":
            client.calls.append((uri, args, options))
            return {"linked": client.linked}
        if uri == "ak.wwise.core.object.isPropertyEnabled":
            client.calls.append((uri, args, options))
            return {"return": True}
        if uri == "ak.wwise.core.object.setProperty":
            client.calls.append((uri, args, options))
            client.source["@Volume"] = args["value"]
            selector = args.get("platform", client.current_platform)
            selected = client.platform_names.get(selector, selector)
            for platform in client.platform_values:
                if client.linked or platform == selected:
                    client.platform_values[platform] = args["value"]
            return {}
        result = original(uri, args, options)
        if uri.endswith("cancelGroup"):
            if (args or {}).get("undo") is True:
                client.platform_values = dict.fromkeys(client.platform_values, 1.0)
            if wrong_scalar:
                client.source["@Volume"] = True
                client.platform_values[client.current_platform] = True
        if uri == "ak.wwise.core.object.get":
            selector = (options or {}).get("platform", client.current_platform)
            selected = client.platform_names.get(selector, selector)
            for row in result.get("return", []):
                if row.get("id") == OBJECT_GUID and "@Volume" in row:
                    row["@Volume"] = client.platform_values[selected]
        return result
    client.call = call
    return client


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_compound_property_child_keeps_legal_current_platform_omission(tmp_path, version):
    client = _property_cancellation_client(version)
    choice = "native-default" if version in {"2021.1", "2022.1"} else "undo-changes"
    if version == "2021.1":
        state_dir, _env, rejected = _preview_cancellation_case(tmp_path, client, version=version,
            cancellation=choice, property_child=True, parent_check_error="UNDO_GROUP_PLATFORM_SCOPE_UNPROVEN")
        assert not (state_dir / "transactions").exists()
        assert "current_platform_or_global_linkage_observer" in json.dumps(rejected)
        return
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version=version,
        cancellation=choice, property_child=True)
    artifact = TransactionStore(state_dir).load_preview(preview["transaction_id"]).artifact
    native = artifact["prepared_operation"]["pre_state"]["execution_plan"]["calls"][0]["args"]
    assert native == {"object": OBJECT_GUID, "property": "Volume", "value": 2.0}
    code, result = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and result["status"] == "execution_cancelled", result
    observed = result["compound_execution"]["cancellation_observation"]
    assert observed["complete"] is True
    assert observed["pre_state_restored"] is (version not in {"2021.1", "2022.1"})


def test_compound_same_current_platform_field_still_rejects_overlapping_children(tmp_path):
    client = _property_cancellation_client("2025.1")
    state_dir, _env, _rejected = _preview_cancellation_case(tmp_path, client, version="2025.1",
        cancellation="undo-changes", property_child=True, duplicate_property=True,
        parent_check_error="UNDO_GROUP_OVERLAPPING_OUTCOME")
    assert not (state_dir / "transactions").exists()
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_compound_numeric_prestate_one_is_not_restored_by_boolean_true(tmp_path, version):
    client = _property_cancellation_client(version, wrong_scalar=True)
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version=version,
        cancellation="undo-changes", property_child=True)
    code, result = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and result["status"] == "execution_cancelled", result
    observed = result["compound_execution"]["cancellation_observation"]
    assert observed["complete"] is True
    assert observed["pre_state_restored"] is False and result["rollback_verified"] is False
    assert observed["children"][0] == {"index": 0, "complete": True, "pre_state_match": False}


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_compound_current_and_named_platform_cannot_assume_distinct_outcomes(tmp_path, version):
    client = _property_cancellation_client(version)
    state_dir, _env, _rejected = _preview_cancellation_case(tmp_path, client, version=version,
        cancellation="native-default", property_child=True, duplicate_property=True,
        second_platform="{44444444-4444-4444-4444-444444444444}",
        parent_check_error="UNDO_GROUP_OVERLAPPING_OUTCOME")
    assert not (state_dir / "transactions").exists()
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_compound_current_platform_drift_requires_new_aggregate_preview(tmp_path, version):
    client = _property_cancellation_client(version)
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version=version,
        cancellation="native-default", property_child=True)
    client.current_platform = "{55555555-5555-5555-5555-555555555555}"
    code, rejected = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and rejected["status"] == "repreview_required", rejected
    assert rejected["executed"] is False
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_compound_unlinked_current_and_distinct_named_platforms_rebind_linkage(tmp_path, version):
    client = _property_cancellation_client(version)
    client.linked = False
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version=version,
        cancellation="undo-changes", property_child=True, duplicate_property=True,
        second_platform="Mac")
    artifact = TransactionStore(state_dir).load_preview(preview["transaction_id"]).artifact
    calls = artifact["prepared_operation"]["pre_state"]["execution_plan"]["calls"]
    assert "platform" not in calls[0]["args"]
    assert calls[1]["args"]["platform"] == "Mac"
    client.linked = True
    code, rejected = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and rejected["status"] == "repreview_required", rejected
    assert rejected["executed"] is False
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_compound_distinct_platforms_need_actual_unlinked_evidence(tmp_path, version):
    client = _property_cancellation_client(version)
    error = "UNDO_GROUP_PLATFORM_SCOPE_UNPROVEN" if version == "2022.1" else "UNDO_GROUP_OVERLAPPING_OUTCOME"
    state_dir, _env, _rejected = _preview_cancellation_case(tmp_path, client, version=version,
        cancellation="native-default", property_child=True, duplicate_property=True,
        second_platform="Mac", parent_check_error=error)
    assert not (state_dir / "transactions").exists()
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_compound_schema_discloses_effective_platform_proof_and_unfinished_lanes(tmp_path, version):
    code, result = offline_execute(tmp_path, "--version", version, "operation-schema", "waapi.undoGroup", version=version)
    assert code == 0, result
    scope = result["business_adapter"]["safety"]["field_platform_scope"]
    assert scope["selector_spelling_proves_independence"] is False
    assert scope["current_platform_observer"] == ("unimplemented_for_pinned_lane" if version == "2021.1" else "getProjectInfo.currentPlatformId")
    assert scope["linked_state_observer"] == ("object.isLinked" if version in {"2023.1", "2024.1", "2025.1"} else "not_in_pinned_catalog")
    assert scope["unknown_effective_scope"] == "guarded_before_preview; remains_implementation_obligation"


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_compound_independent_unlinked_platform_children_execute_and_verify_exact_views(tmp_path, version):
    client = _property_cancellation_client(version)
    client.linked = False
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version=version,
        cancellation="undo-changes", property_child=True, duplicate_property=True, second_platform="Mac")
    def run(command):
        return waapi_gateway.execute_gateway(["--state-dir", str(state_dir), command, preview["transaction_id"]],
            env=env, client_factory=lambda _url: client)
    code, executed = run("execute")
    assert code == 0 and executed["executed"] is True, executed
    code, verified = run("verify")
    assert code == 0 and verified["verified"] is True, verified
    writes = [row for row in client.calls if row[0] == "ak.wwise.core.object.setProperty"]
    assert [row[1] for row in writes] == [
        {"object": OBJECT_GUID, "property": "Volume", "value": 2.0},
        {"object": OBJECT_GUID, "property": "Volume", "value": 3.0, "platform": "Mac"}]
    assert client.platform_values == {"{44444444-4444-4444-4444-444444444444}": 2.0,
                                      "{55555555-5555-5555-5555-555555555555}": 3.0}
    code, replay = run("execute")
    assert code == 2 and len([row for row in client.calls if row[0].endswith("setProperty")]) == 2, replay


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_compound_platform_name_rebinding_requires_new_aggregate_preview(tmp_path, version):
    client = _property_cancellation_client(version)
    client.linked = False
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version=version,
        cancellation="undo-changes", property_child=True, duplicate_property=True, second_platform="Mac")
    client.platform_names["Mac"] = "{66666666-6666-6666-6666-666666666666}"
    client.platform_values[client.platform_names["Mac"]] = 1.0
    code, rejected = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and rejected["status"] == "repreview_required", rejected
    assert rejected["executed"] is False
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_compound_nonboolean_link_readback_cannot_authorize_platform_children(tmp_path, version):
    client = _property_cancellation_client(version)
    client.linked = False
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version=version,
        cancellation="undo-changes", property_child=True, duplicate_property=True, second_platform="Mac")
    client.linked = 0
    code, rejected = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and rejected["ok"] is False, rejected
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("platform", ("broken", True))
def test_compound_malformed_current_platform_cannot_seal_field_scope(tmp_path, platform):
    client = _property_cancellation_client("2025.1")
    client.current_platform = platform
    # Preserve an ordinary field read so malformed platform identity reaches
    # the public scope binder rather than failing inside the fake view store.
    client.platform_values[platform] = 1.0
    state_dir, _env, _rejected = _preview_cancellation_case(tmp_path, client, version="2025.1",
        cancellation="undo-changes", property_child=True, parent_check_error="INVALID_READBACK")
    assert not (state_dir / "transactions").exists()
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("platform", ("Windows", "{44444444-4444-4444-4444-444444444444}".lower()))
def test_compound_alias_of_current_unlinked_platform_still_overlaps(tmp_path, platform):
    client = _property_cancellation_client("2025.1")
    client.linked = False
    state_dir, _env, _rejected = _preview_cancellation_case(tmp_path, client, version="2025.1",
        cancellation="undo-changes", property_child=True, duplicate_property=True, second_platform=platform,
        parent_check_error="UNDO_GROUP_OVERLAPPING_OUTCOME")
    assert not (state_dir / "transactions").exists()
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("fault", ("null-guid", "not-a-project-platform"))
def test_compound_current_platform_must_be_a_real_project_platform_before_preview(tmp_path, fault):
    client = _property_cancellation_client("2025.1")
    if fault == "null-guid":
        client.current_platform = "{00000000-0000-0000-0000-000000000000}"
        client.platform_names["Windows"] = client.current_platform
        client.platform_values[client.current_platform] = 1.0
    else:
        # The schema-valid current GUID has no corresponding project row.
        del client.platform_names["Windows"]
    state_dir, _env, _rejected = _preview_cancellation_case(tmp_path, client, version="2025.1",
        cancellation="undo-changes", property_child=True, parent_check_error="INVALID_READBACK")
    assert not (state_dir / "transactions").exists()
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("fault", ("removed-platform", "duplicate-platform-id"))
def test_compound_current_platform_membership_drift_blocks_before_begin_group(tmp_path, fault):
    client = _property_cancellation_client("2025.1")
    state_dir, env, preview = _preview_cancellation_case(tmp_path, client, version="2025.1",
        cancellation="undo-changes", property_child=True)
    if fault == "removed-platform":
        del client.platform_names["Windows"]
    else:
        client.platform_names["Alias Windows"] = client.current_platform
    code, rejected = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), "execute", preview["transaction_id"]],
        env=env, client_factory=lambda _url: client)
    assert code == 2 and rejected["status"] == "repreview_required", rejected
    assert rejected["executed"] is False
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)
    assert not any(row[0].endswith("setProperty") for row in client.calls)


def _owned_notes_history_case(tmp_path, *, version="2025.1", direction="undo", effect=True, source_operation="object.setNotes", initial_notes="before history edit", verify_source=True, history_values=None, declaration_error=False, confirm_history=True, history_policy=None, compound_ancestor=False, compound_property=False, omitted_property_name=False, reference_clear=False, reference_platform="{55555555-5555-5555-5555-555555555555}", omitted_reference_metadata=False, source_prepared_only=False, compound_reference=False, platform_inventory=True, property_platform="{55555555-5555-5555-5555-555555555555}", source_platform_observer_error=False):
    from tests.unit.test_remaining_core_business_gateway import _env
    from tests.unit.test_object_graph_business_gateway import _info
    reference_case = source_operation == "object.setReference" or compound_reference
    class Client(ObjectLifecycleClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                self.calls.append((uri, args, options))
                return _info(version)
            if uri == "ak.wwise.core.object.setNotes":
                self.calls.append((uri, args, options))
                self.source["notes"] = args["value"]
                self.history_after = dict(self.source)
                return {}
            if uri == "ak.wwise.core.object.setName":
                self.calls.append((uri, args, options))
                renamed = self.parent if compound_ancestor else self.source
                renamed.update(name=args["value"], path=renamed["path"].rsplit("\\", 1)[0] + "\\" + args["value"])
                if compound_ancestor:
                    self.source["path"] = self.parent["path"] + "\\" + self.source["name"]
                self.history_after = dict(self.source)
                self.history_parent_after = dict(self.parent)
                return {}
            if uri == "ak.wwise.core.getProjectInfo" and (reference_case or source_operation == "object.setProperty"):
                if hasattr(self, "project_info_successes_before_fault"):
                    if self.project_info_successes_before_fault == 0:
                        del self.project_info_successes_before_fault
                        self.calls.append((uri, args, options))
                        raise ValueError("fixture optional platform inventory read failed")
                    self.project_info_successes_before_fault -= 1
                result = super().call(uri, args, options)
                return {**result, "platforms": self.platform_rows, "currentPlatformId": self.current_platform} if platform_inventory else result
            if uri == "ak.wwise.core.object.get" and reference_case:
                result = super().call(uri, args, options)
                platform = (options or {}).get("platform") or self.current_platform
                if platform == "Windows":
                    platform = self.platform_rows[0]["id"]
                # A successful null-GUID projection cannot certify a real platform identity.
                if platform not in {self.platform_rows[0]["id"], "{00000000-0000-0000-0000-000000000000}"}:
                    for row in result["return"]:
                        if row["id"] == self.source["id"]:
                            row["@Attenuation"] = self.other_reference
                return result
            if uri == "ak.wwise.core.object.getTypes" and reference_case:
                self.calls.append((uri, args, options))
                return {"return": [{"name": "Sound", "classId": 65552, "type": "WObject"},
                    {"name": "Attenuation", "classId": 2686992, "type": "WObject"}]}
            if uri == "ak.wwise.core.object.setReference":
                self.calls.append((uri, args, options))
                self.source["@Attenuation"] = None if args["value"] == "{00000000-0000-0000-0000-000000000000}" else {"id": args["value"]}
                self.history_after = dict(self.source)
                return {}
            if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
                self.calls.append((uri, args, options))
                return {"return": ["Attenuation" if reference_case else "Volume"]}
            if uri == "ak.wwise.core.object.getPropertyInfo":
                self.calls.append((uri, args, options))
                if reference_case:
                    return {**({} if omitted_reference_metadata else {"name": "Attenuation", "type": "Reference"}),
                        "restriction": {"type": "reference", "restrictions": [{"type": ["Attenuation"]}]}}
                return {**({} if omitted_property_name else {"name": "Volume"}), "type": "Real32", "default": 0,
                    "restriction": {"type": "range", "min": -96, "max": 6}, "supports": {"unlink": True}}
            if uri == "ak.wwise.core.object.isLinked":
                self.calls.append((uri, args, options))
                return {"linked": True}
            if uri == "ak.wwise.core.object.isPropertyEnabled":
                self.calls.append((uri, args, options))
                return {"return": True}
            if uri == "ak.wwise.core.object.setProperty":
                self.calls.append((uri, args, options))
                self.source["@Volume"] = args["value"]
                self.history_after = dict(self.source)
                return {}
            if uri in {"ak.wwise.core.undo.beginGroup", "ak.wwise.core.undo.endGroup", "ak.wwise.core.undo.cancelGroup"}:
                self.calls.append((uri, args, options))
                return {}
            if uri in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"}:
                self.calls.append((uri, args, options))
                if effect:
                    self.source = dict(self.history_before if uri.endswith(".undo") else self.history_after)
                    if compound_ancestor:
                        self.parent = dict(self.history_parent_before if uri.endswith(".undo") else self.history_parent_after)
                return {}
            return super().call(uri, args, options)
    client = Client()
    if reference_case:
        client.source["classId"] = 65552
        client.parent.update(type="Attenuation", classId=2686992, path=r"\Attenuations\Default Work Unit\Destination")
        client.source["@Attenuation"] = {"id": client.parent["id"]} if reference_clear else None
    client.platform_rows = [{"id": "{55555555-5555-5555-5555-555555555555}", "name": "Windows"},
        {"id": "{66666666-6666-6666-6666-666666666666}", "name": "Mac"}]
    client.current_platform = client.platform_rows[0]["id"]
    client.other_reference = None
    client.source["notes"] = initial_notes
    client.source["@Volume"] = 1.0
    if compound_ancestor:
        client.source.update(path=client.parent["path"] + "\\" + client.source["name"], parent={"id": client.parent["id"]})
    client.history_before = dict(client.source)
    client.history_parent_before = dict(client.parent)
    state = tmp_path / "state"
    env = _env(tmp_path, version=version)
    def run(*argv):
        return waapi_gateway.execute_gateway(["--state-dir", str(state), *argv], env=env, client_factory=lambda _url: client)
    def check_preview(draft, authority, revision, *, confirm=True):
        if source_platform_observer_error and not getattr(client, "platform_fault_scheduled", False):
            client.project_info_successes_before_fault = 1
        code, checked = run("draft-check", draft, "--task-authority", authority, "--expected-revision", str(revision))
        assert code == 0, json.dumps(checked)
        if source_platform_observer_error and not getattr(client, "platform_fault_scheduled", False):
            # The mandatory project guard succeeds; only the following optional
            # source observation read fails once. Later project guards remain usable.
            client.project_info_successes_before_fault = 1
            client.platform_fault_scheduled = True
        code, preview = run("preview-from-draft", draft, "--task-authority", authority,
            "--expected-revision", str(checked["draft"]["revision"]), "--apply")
        assert code == 0, json.dumps(preview)
        code, shown = run("transaction-show", preview["transaction_id"], "--summary-only")
        assert code == 0, shown
        confirmation = shown["next_command"]["gateway_argv"]
        if confirm and confirmation[0] == "confirm":
            code, confirmed = run(*confirmation)
            assert code == 0, confirmed
        return preview, shown
    if source_operation == "waapi.undoGroup":
        state, env, source = _preview_cancellation_case(tmp_path, client, version=version,
            cancellation="native-default" if version == "2022.1" else "undo-changes",
            child_ids=(OBJECT_GUID, client.parent["id"]) if compound_ancestor else None,
            property_child=compound_property, reference_child=compound_reference,
            first_platform="{55555555-5555-5555-5555-555555555555}" if compound_property or compound_reference else None)
    else:
        code, phase = run("draft-start", source_operation)
        assert code == 0, phase
        draft, authority = phase["draft"]["draft_id"], phase["task_authority"]
        code, phase = run("draft-bind-object", draft, "--task-authority", authority,
            "--expected-revision", str(phase["draft"]["revision"]), "--object-id", OBJECT_GUID)
        assert code == 0, phase
        if source_operation == "object.setReference":
            object_handle = phase["bound_object"]["handle"]
            target_handle = "clear"
            if not reference_clear:
                code, phase = run("draft-bind-object", draft, "--task-authority", authority,
                    "--expected-revision", str(phase["draft"]["revision"]), "--object-id", client.parent["id"])
                assert code == 0, json.dumps(phase)
                target_handle = phase["bound_object"]["handle"]
            code, phase = run("draft-discover-fields", draft, "--task-authority", authority,
                "--expected-revision", str(phase["draft"]["revision"]), "--object-handle", object_handle,
                "--meaning", "attenuation", *(["--platform", reference_platform] if reference_platform is not None else []))
            assert code == 0, phase
            code, phase = run("draft-declare-field-change", draft, "--task-authority", authority,
                "--expected-revision", str(phase["draft"]["revision"]), "--object-handle", object_handle,
                "--field-handle", phase["field_candidates"][0]["handle"], *(["--clear-reference"] if reference_clear else ["--target-handle", target_handle]))
        elif source_operation == "object.setProperty":
            object_handle = phase["bound_object"]["handle"]
            code, phase = run("draft-discover-fields", draft, "--task-authority", authority,
                "--expected-revision", str(phase["draft"]["revision"]), "--object-handle", object_handle,
                "--meaning", "volume", *(["--platform", property_platform] if property_platform is not None else []))
            assert code == 0, phase
            code, phase = run("draft-declare-field-change", draft, "--task-authority", authority,
                "--expected-revision", str(phase["draft"]["revision"]), "--object-handle", object_handle,
                "--field-handle", phase["field_candidates"][0]["handle"], "--business-value", "2")
        else:
            code, phase = run("draft-declare-object-change", draft, "--task-authority", authority,
                "--expected-revision", str(phase["draft"]["revision"]),
                *( ["--notes", "after history edit"] if source_operation == "object.setNotes" else ["--new-name", "AfterHistoryName"] ))
        assert code == 0, phase
        source, _shown = check_preview(draft, authority, phase["draft"]["revision"])
    if source_prepared_only:
        return client, state, source, source, None, run
    code, result = run("execute", source["transaction_id"])
    assert code == 0, json.dumps(result)
    if verify_source:
        code, verified = run("verify", source["transaction_id"])
        assert code == 0 and verified["verified"] is True, verified
    if direction == "redo":
        client.source = dict(client.history_before)
        if compound_ancestor:
            client.parent = dict(client.history_parent_before)
    if history_policy is not None:
        code, configured = run("config-set", "--project-modification-policy", history_policy)
        assert code == 0, configured
    code, phase = run("draft-start", "ak.wwise.core.undo." + direction)
    assert code == 0, json.dumps(phase)
    draft, authority = phase["draft"]["draft_id"], phase["task_authority"]
    values = {"history_scope": "latest_project_history", "expectation_receipt": source["transaction_id"]} if history_values is None else history_values
    flags = [token for key, value in values.items() for token in ("--value", key, source["transaction_id"] if value == "<source>" else value)]
    code, phase = run("draft-declare-core-plan", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]), *flags)
    if declaration_error:
        assert code == 2, phase
        return client, state, source, phase, None, run
    assert code == 0, json.dumps(phase)
    preview, shown = check_preview(draft, authority, phase["draft"]["revision"], confirm=confirm_history)
    return client, state, source, preview, shown, run


def test_standalone_history_latest_action_uses_owned_receipt_only_for_observed_expectation(tmp_path):
    client, _state, _source, preview, shown, run = _owned_notes_history_case(tmp_path)
    assert "latest_project_history" in json.dumps(shown)
    assert "stack_head_observed" in json.dumps(shown)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, json.dumps(result)
    assert [row[1:] for row in client.calls if row[0] == "ak.wwise.core.undo.undo"] == [({}, {})]
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0, json.dumps(verified)
    assert verified["verification_strength"] == "scoped_history_effect_readback"
    assert verified["agent_result"]["result"] == {}
    assert list(verified)[-1] == "agent_result"
    assert any(read["result"]["return"][0]["notes"] == "before history edit" for read in verified["verification"]["readbacks"])


@pytest.mark.parametrize("version,direction", [("2022.1", "undo"), ("2023.1", "undo"), ("2024.1", "undo"), ("2025.1", "undo"),
    ("2023.1", "redo"), ("2024.1", "redo"), ("2025.1", "redo")])
def test_standalone_history_observes_expected_notes_for_each_pinned_action_version(tmp_path, version, direction):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, version=version, direction=direction)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verification_strength"] == "scoped_history_effect_readback", verified
    assert client.source["notes"] == ("before history edit" if direction == "undo" else "after history edit")
    assert [row[1:] for row in client.calls if row[0] == "ak.wwise.core.undo." + direction] == [({}, {})]
    code, repeated = run("execute", preview["transaction_id"])
    assert code == 2, repeated
    assert len([row for row in client.calls if row[0] == "ak.wwise.core.undo." + direction]) == 1


@pytest.mark.parametrize("direction", ["undo", "redo"])
def test_standalone_history_empty_native_result_without_expected_effect_fails_verification(tmp_path, direction):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, direction=direction, effect=False)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    code, verified = run("verify", preview["transaction_id"])
    assert code == 2 and verified["status"] == "verification_failed" and verified["verified"] is False, verified
    assert verified["verification_strength"] == "scoped_history_effect_readback"
    assert not any(row[0] == "ak.wwise.core.undo." + ("redo" if direction == "undo" else "undo") for row in client.calls)


@pytest.mark.parametrize("changed", ["notes", "name", "type", "path"])
def test_standalone_history_prewrite_scope_drift_never_dispatches(tmp_path, changed):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path)
    client.source[changed] = "unreviewed field value"
    code, result = run("execute", preview["transaction_id"])
    assert code == 2, result
    assert not any(row[0] in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"} for row in client.calls)


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("direction", ["undo", "redo"])
def test_standalone_history_discovery_is_versioned_and_discloses_global_scope_and_observation_only_receipt(tmp_path, version, direction):
    from tests.unit.test_remaining_core_business_gateway import _env
    code, result = waapi_gateway.execute_gateway(["--version", version, "request-schema", "ak.wwise.core.undo." + direction],
        env=_env(tmp_path, version=version), client_factory=lambda _url: pytest.fail("offline history disclosure connected"))
    supported = version != "2021.1" and (direction == "undo" or version != "2022.1")
    if not supported:
        assert code == 2, result
        return
    assert code == 0, result
    declaration = result["business_adapter"]["declaration"]
    assert set(declaration["required_fields"]) == {"history_scope"}
    assert set(declaration["optional_fields"]) == {"expectation_receipt"}
    assert declaration["history"]["history_scope"]["choices"] == ["latest_project_history"]
    assert declaration["history"]["expectation_receipt"]["native_entry_selection"] is False
    assert declaration["history"]["stack_head_observed"] is False



@pytest.mark.parametrize("direction", ["undo", "redo"])
def test_standalone_history_recovers_owned_rename_identity_and_hierarchy_path(tmp_path, direction):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, direction=direction, source_operation="object.setName")
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verification_strength"] == "scoped_history_effect_readback", verified
    expected = client.history_before if direction == "undo" else client.history_after
    assert client.source["id"] == OBJECT_GUID
    assert (client.source["name"], client.source["path"]) == (expected["name"], expected["path"])



@pytest.mark.parametrize("direction", ["undo", "redo"])
def test_standalone_history_observes_all_recoverable_children_of_owned_compound_receipt(tmp_path, direction):
    client, state, _source, preview, shown, run = _owned_notes_history_case(tmp_path,
        direction=direction, source_operation="waapi.undoGroup")
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["request"]["arguments"]["history_binding"]
    assert {row["field"] for row in binding["observations"]} == {"notes", "name"}
    assert "stack_head_observed" in json.dumps(shown)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verification_strength"] == "scoped_history_effect_readback", verified
    expected = client.history_before if direction == "undo" else client.history_after
    assert (client.source["name"], client.source["path"], client.source["notes"]) == (expected["name"], expected["path"], expected["notes"])


def test_standalone_history_incomplete_effect_readback_retains_raw_native_response(tmp_path):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    original = client.call
    def missing(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.get":
            client.calls.append((uri, args, options))
            return {"return": []}
        return original(uri, args, options)
    client.call = missing
    code, verified = run("verify", preview["transaction_id"])
    assert code == 2 and verified["verified"] is False, verified
    assert any(read.get("result") == {"return": []} for read in verified["verification"]["readbacks"]), verified
    assert len([row for row in client.calls if row[0] == "ak.wwise.core.undo.undo"]) == 1
    assert not any(row[0] == "ak.wwise.core.undo.redo" for row in client.calls)



def test_standalone_history_compound_preserves_unchanged_child_observation_alongside_real_change(tmp_path):
    client, state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation="waapi.undoGroup", initial_notes="after")
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["request"]["arguments"]["history_binding"]
    note = next(row for row in binding["observations"] if row["field"] == "notes")
    assert note["before"] == note["after"] == "after"
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0, verified
    assert client.source["name"] == client.history_before["name"] and client.source["notes"] == "after"



@pytest.mark.parametrize("values", [{},
    {"history_scope": "receipt-target", "expectation_receipt": "<source>"},
    {"history_scope": "latest_project_history", "expectation_receipt": "missing"},
    {"history_scope": "latest_project_history", "expectation_receipt": "<source>", "native_entry_id": "invented"}])
def test_standalone_history_requires_explicit_global_scope_and_valid_owned_expectation(tmp_path, values):
    client, _state, _source, _rejected, _shown, _run = _owned_notes_history_case(tmp_path,
        history_values=values, declaration_error=True)
    assert not any(row[0] in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"} for row in client.calls)


def test_standalone_history_unverified_receipt_is_not_promoted_to_effect_proof(tmp_path):
    client, _state, _source, rejected, _shown, _run = _owned_notes_history_case(tmp_path,
        verify_source=False, declaration_error=True)
    assert "successfully business-verified" in rejected["message"], rejected
    assert not any(row[0] in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"} for row in client.calls)


@pytest.mark.parametrize("direction", ["undo", "redo"])
@pytest.mark.parametrize("entry", ["typed-call", "typed-zero-call"])
def test_standalone_history_legacy_zero_input_entry_cannot_bypass_business_scope(tmp_path, direction, entry):
    from tests.unit.test_remaining_core_business_gateway import _env
    code, result = waapi_gateway.execute_gateway([entry, "ak.wwise.core.undo." + direction,
        "--schema-digest", "0" * 64, "--apply"], env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("history legacy entry connected"))
    assert code == 2 and ("business Draft" in result["message"] or "closed Core business" in result["message"]), result


def test_standalone_history_read_only_policy_stops_an_already_confirmed_history_action(tmp_path):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path)
    code, result = run("config-set", "--project-modification-policy", "read_only")
    assert code == 0, result
    code, result = run("execute", preview["transaction_id"])
    assert code == 2, result
    assert not any(row[0] in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"} for row in client.calls)


def test_standalone_history_receipt_corruption_cannot_dispatch_latest_history_action(tmp_path):
    client, state, source, preview, _shown, run = _owned_notes_history_case(tmp_path)
    receipt = state / "transactions" / source["transaction_id"] / "preview.json"
    payload = json.loads(receipt.read_text())
    payload["artifact"]["request"]["arguments"]["value"] = "tampered expectation"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    code, result = run("execute", preview["transaction_id"])
    assert code == 2, result
    assert not any(row[0] in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"} for row in client.calls)


def test_standalone_history_ambiguous_native_failure_is_not_replayed_or_compensated(tmp_path):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path)
    original = client.call
    def uncertain(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == "ak.wwise.core.undo.undo":
            raise RuntimeError("fixture lost acknowledgement after history action")
        return result
    client.call = uncertain
    code, result = run("execute", preview["transaction_id"])
    assert code == 2 and result["status"] == "indeterminate", result
    assert len([row for row in client.calls if row[0] == "ak.wwise.core.undo.undo"]) == 1
    assert not any(row[0] == "ak.wwise.core.undo.redo" for row in client.calls)
    code, repeated = run("execute", preview["transaction_id"])
    assert code == 2, repeated
    assert len([row for row in client.calls if row[0] == "ak.wwise.core.undo.undo"]) == 1


def test_standalone_history_wrong_typed_effect_value_is_failure_with_original_readback(tmp_path):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    client.source["notes"] = True
    code, verified = run("verify", preview["transaction_id"])
    assert code == 2 and verified["verified"] is False, verified
    assert any(read["result"]["return"][0]["notes"] is True for read in verified["verification"]["readbacks"])



def test_standalone_history_ask_policy_cannot_dispatch_without_explicit_confirmation(tmp_path):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, confirm_history=False)
    code, rejected = run("execute", preview["transaction_id"])
    assert code == 2, rejected
    assert not any(row[0] in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"} for row in client.calls)


def test_standalone_history_allow_policy_uses_distinct_durable_authority_and_discloses_scope(tmp_path):
    client, state, _source, preview, shown, run = _owned_notes_history_case(tmp_path,
        confirm_history=False, history_policy="allow_changes")
    assert preview["state"] == "policy_authorized", preview
    assert "latest_project_history" in json.dumps(shown) and "stack_head_observed" in json.dumps(shown)
    assert not any(row[0] in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"} for row in client.calls)
    events = TransactionStore(state).read_events(preview["transaction_id"])
    assert any(row["event_type"] == "policy_authorized" for row in events)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    assert len([row for row in client.calls if row[0] == "ak.wwise.core.undo.undo"]) == 1


def test_standalone_history_receipt_without_observable_transition_is_not_effect_proof(tmp_path):
    client, _state, _source, rejected, _shown, _run = _owned_notes_history_case(tmp_path,
        initial_notes="after history edit", declaration_error=True)
    assert "no observable transition" in rejected["message"], rejected
    assert not any(row[0] in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"} for row in client.calls)


def test_standalone_history_undo_then_explicit_redo_each_observes_its_expected_state(tmp_path):
    client, _state, source, undo, _shown, run = _owned_notes_history_case(tmp_path)
    code, executed = run("execute", undo["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", undo["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified
    assert client.source["notes"] == "before history edit"
    code, phase = run("draft-start", "ak.wwise.core.undo.redo")
    assert code == 0, phase
    draft, authority = phase["draft"]["draft_id"], phase["task_authority"]
    code, phase = run("draft-declare-core-plan", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]),
        "--value", "history_scope", "latest_project_history",
        "--value", "expectation_receipt", source["transaction_id"])
    assert code == 0, phase
    code, checked = run("draft-check", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]))
    assert code == 0, checked
    code, redo = run("preview-from-draft", draft, "--task-authority", authority,
        "--expected-revision", str(checked["draft"]["revision"]), "--apply")
    assert code == 0, redo
    code, shown = run("transaction-show", redo["transaction_id"], "--summary-only")
    assert code == 0 and "stack_head_observed" in json.dumps(shown), shown
    assert not any(row[0] == "ak.wwise.core.undo.redo" for row in client.calls)
    code, confirmed = run(*shown["next_command"]["gateway_argv"])
    assert code == 0, confirmed
    code, executed = run("execute", redo["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", redo["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified
    assert client.source["notes"] == "after history edit"
    assert len([row for row in client.calls if row[0] == "ak.wwise.core.undo.undo"]) == 1
    assert len([row for row in client.calls if row[0] == "ak.wwise.core.undo.redo"]) == 1


@pytest.mark.parametrize("direction", ["undo", "redo"])
def test_standalone_history_compound_ancestor_rename_keeps_descendant_observation_identity(tmp_path, direction):
    client, state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation="waapi.undoGroup", direction=direction, compound_ancestor=True)
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["request"]["arguments"]["history_binding"]
    child = next(row for row in binding["observations"] if row["field"] == "notes")
    assert child["object_before"]["path"] == r"\Actor-Mixer Hierarchy\Default Work Unit\Destination\OldName"
    assert child["object_after"]["path"] == r"\Actor-Mixer Hierarchy\Default Work Unit\Renamed\OldName"
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified
    expected_parent = client.history_parent_before if direction == "undo" else client.history_parent_after
    assert client.source["path"] == expected_parent["path"] + r"\OldName"
    assert client.source["parent"]["id"] == client.parent["id"] == expected_parent["id"]


def _latest_history_without_owned_receipt(tmp_path, *, version="2025.1", direction="undo"):
    from tests.unit.test_remaining_core_business_gateway import _env
    from tests.unit.test_object_graph_business_gateway import _info
    class Client(ObjectLifecycleClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                self.calls.append((uri, args, options))
                return _info(version)
            if uri == "ak.wwise.core.undo." + direction:
                self.calls.append((uri, args, options))
                return {}
            return super().call(uri, args, options)
    client, state, env = Client(), tmp_path / "state", _env(tmp_path, version=version)
    def run(*argv):
        return waapi_gateway.execute_gateway(["--state-dir", str(state), *argv], env=env,
            client_factory=lambda _url: client)
    code, phase = run("draft-start", "ak.wwise.core.undo." + direction)
    assert code == 0, phase
    draft, authority = phase["draft"]["draft_id"], phase["task_authority"]
    code, phase = run("draft-declare-core-plan", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]), "--value", "history_scope", "latest_project_history")
    assert code == 0, phase
    code, checked = run("draft-check", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]))
    assert code == 0, checked
    code, preview = run("preview-from-draft", draft, "--task-authority", authority,
        "--expected-revision", str(checked["draft"]["revision"]), "--apply")
    assert code == 0, preview
    code, shown = run("transaction-show", preview["transaction_id"], "--summary-only")
    assert code == 0, shown
    return client, state, preview, shown, run


@pytest.mark.parametrize("version,direction", [("2022.1", "undo"), ("2023.1", "undo"), ("2024.1", "undo"), ("2025.1", "undo"),
    ("2023.1", "redo"), ("2024.1", "redo"), ("2025.1", "redo")])
def test_standalone_history_latest_gui_action_without_receipt_reports_only_result_schema(tmp_path, version, direction):
    client, state, preview, shown, run = _latest_history_without_owned_receipt(tmp_path, version=version, direction=direction)
    assert len(list((state / "transactions").iterdir())) == 1
    notice = shown["preview_summary"]["history_action"]
    assert notice["scope"] == "latest_project_history" and notice["stack_head_observed"] is False
    assert notice["effect_expectation"] == "none" and notice["expectation_receipt"] is None
    assert notice["verification_boundary"] == "result_schema_only; effect_and_preservation_unobserved"
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)
    code, confirmed = run(*shown["next_command"]["gateway_argv"])
    assert code == 0, confirmed
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["status"] == "result_schema_checked", verified
    assert verified["verified"] is False and verified["verification"]["business_state_verified"] is False
    assert verified["verification_strength"] == "result_schema_only"
    assert verified["agent_result"]["result"] == {}
    assert [row[1:] for row in client.calls if row[0] == "ak.wwise.core.undo." + direction] == [({}, {})]
    code, repeated = run("execute", preview["transaction_id"])
    assert code == 2, repeated
    assert len([row for row in client.calls if row[0] == "ak.wwise.core.undo." + direction]) == 1


def test_standalone_history_without_expectation_still_requires_confirmation_and_valid_native_result(tmp_path):
    client, _state, preview, shown, run = _latest_history_without_owned_receipt(tmp_path)
    code, rejected = run("execute", preview["transaction_id"])
    assert code == 2, rejected
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)
    code, confirmed = run(*shown["next_command"]["gateway_argv"])
    assert code == 0, confirmed
    original = client.call
    def malformed(uri, args=None, options=None):
        result = original(uri, args, options)
        return {"unexpected": "not a closed empty result"} if uri == "ak.wwise.core.undo.undo" else result
    client.call = malformed
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 2 and verified["verified"] is False, verified
    assert verified["status"] == "verification_failed"
    assert not any(row[0] == "ak.wwise.core.undo.redo" for row in client.calls)


def test_standalone_history_without_expectation_still_rejects_project_drift(tmp_path):
    client, _state, preview, shown, run = _latest_history_without_owned_receipt(tmp_path)
    code, confirmed = run(*shown["next_command"]["gateway_argv"])
    assert code == 0, confirmed
    original = client.call
    def other_project(uri, args=None, options=None):
        result = original(uri, args, options)
        return {**result, "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"} if uri == "ak.wwise.core.getProjectInfo" else result
    client.call = other_project
    code, rejected = run("execute", preview["transaction_id"])
    assert code == 2 and rejected["status"] == "repreview_required", rejected
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("version,direction", [("2022.1", "undo"), ("2023.1", "undo"), ("2024.1", "undo"), ("2025.1", "undo"),
    ("2023.1", "redo"), ("2024.1", "redo"), ("2025.1", "redo")])
def test_standalone_history_recovers_owned_scalar_property_in_its_exact_platform_view(tmp_path, version, direction):
    client, state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation="object.setProperty", version=version, direction=direction)
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified
    expected = 1.0 if direction == "undo" else 2.0
    assert client.source["@Volume"] == expected
    code, shown = run("transaction-show", preview["transaction_id"])
    assert code == 0, shown
    retained = next(event["details"]["verification"] for event in reversed(shown["events"])
        if event["event_type"] == "verification_recorded")
    reads = retained["readbacks"]
    assert any(read["uri"] == "ak.wwise.core.object.get" and read["options"].get("platform") == "{55555555-5555-5555-5555-555555555555}"
        and read["result"]["return"][0]["@Volume"] == expected for read in reads)
    assert any(read["uri"] == "ak.wwise.core.object.getPropertyInfo" for read in reads)


@pytest.mark.parametrize("stage", ["prewrite", "readback"])
def test_standalone_history_numeric_property_is_not_proven_by_boolean_true(tmp_path, stage):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, source_operation="object.setProperty")
    if stage == "readback":
        code, executed = run("execute", preview["transaction_id"])
        assert code == 0, executed
    client.source["@Volume"] = True
    code, rejected = run("execute" if stage == "prewrite" else "verify", preview["transaction_id"])
    assert code == 2 and rejected.get("verified") is not True, rejected
    assert len([row for row in client.calls if row[0] == "ak.wwise.core.undo.undo"]) == (1 if stage == "readback" else 0)
    assert "true" in json.dumps(rejected)


@pytest.mark.parametrize("damage", ["wrong_name", "unknown_type", "restriction"])
def test_standalone_history_property_metadata_drift_stops_dispatch_without_downgrading(tmp_path, damage):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, source_operation="object.setProperty")
    original = client.call
    def changed(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == "ak.wwise.core.object.getPropertyInfo":
            result = {**result, **({"name": "Pitch"} if damage == "wrong_name" else {"type": "UnknownScalar"} if damage == "unknown_type" else {"restriction": {"type": "range", "min": -1, "max": 1}})}
        return result
    client.call = changed
    code, rejected = run("execute", preview["transaction_id"])
    assert code == 2, rejected
    assert not any(row[0] == "ak.wwise.core.undo.undo" for row in client.calls)
    assert "getPropertyInfo" in json.dumps(rejected)


def test_standalone_history_property_retains_exact_scoped_binding_for_omitted_native_name(tmp_path):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation="object.setProperty", omitted_property_name=True)
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified
    code, shown = run("transaction-show", preview["transaction_id"])
    assert code == 0, shown
    observation = shown["artifact"]["request"]["arguments"]["history_binding"]["observations"][0]
    assert observation["field_info"]["name"] is None
    assert observation["field_info"]["field_binding"] == {"token": "Volume", "source": "exact_scoped_getPropertyAndReferenceNames"}
    retained = next(event["details"]["verification"] for event in reversed(shown["events"]) if event["event_type"] == "verification_recorded")
    assert any(read["uri"] == "ak.wwise.core.object.getPropertyInfo" and "name" not in read["result"] for read in retained["readbacks"])


@pytest.mark.parametrize("direction", ["undo", "redo"])
@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
def test_standalone_history_multi_object_compound_recovers_property_view_and_ancestor_name(tmp_path, version, direction):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation="waapi.undoGroup", compound_property=True, compound_ancestor=True, version=version, direction=direction)
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified
    assert client.source["@Volume"] == (1.0 if direction == "undo" else 2.0)
    assert client.parent["name"] == ("Destination" if direction == "undo" else "Renamed")
    assert client.source["path"] == client.parent["path"] + r"\OldName"


@pytest.mark.parametrize("version,direction", [("2022.1", "undo"), ("2023.1", "undo"), ("2024.1", "undo"), ("2025.1", "undo"),
    ("2023.1", "redo"), ("2024.1", "redo"), ("2025.1", "redo")])
@pytest.mark.parametrize("clear", [False, True])
def test_standalone_history_observes_verified_reference_receipt_in_exact_platform(tmp_path, version, direction, clear):
    client, state, source, preview, _shown, run = _owned_notes_history_case(tmp_path, source_operation="object.setReference",
        version=version, direction=direction, reference_clear=clear)
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified
    assert verified["verification_strength"] == "scoped_history_effect_readback"
    assert client.source["@Attenuation"] == (client.history_before if direction == "undo" else client.history_after)["@Attenuation"]
    code, shown = run("transaction-show", preview["transaction_id"])
    assert code == 0, shown
    binding = shown["artifact"]["request"]["arguments"]["history_binding"]
    assert binding["source_receipt"]["transaction_id"] == source["transaction_id"]
    assert binding["observations"][0]["before"] == (client.parent["id"] if clear else None)
    assert binding["observations"][0]["after"] == (None if clear else client.parent["id"])
    assert binding["observations"][0]["platform"] == "{55555555-5555-5555-5555-555555555555}"
    assert len([call for call in client.calls if call[0] == "ak.wwise.core.undo." + direction]) == 1


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("platform", [None, "Windows"])
def test_standalone_history_reference_receipt_certifies_original_current_or_named_read_view(tmp_path, version, platform):
    client, state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, source_operation="object.setReference",
        reference_platform=platform, version=version)
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["request"]["arguments"]["history_binding"]
    assert binding["observations"][0]["platform"] == client.platform_rows[0]["id"]
    client.current_platform = client.platform_rows[1]["id"]
    if platform is not None:
        client.platform_rows[0]["name"], client.platform_rows[1]["name"] = "Renamed Windows", "Windows"
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified
    readbacks = next(event["details"]["verification"]["readbacks"] for event in reversed(TransactionStore(state).load_snapshot(preview["transaction_id"]).events)
        if event["event_type"] == "verification_recorded")
    assert any(row["uri"] == "ak.wwise.core.object.get" and "Attenuation" in row["options"].get("return", [])
        and row["options"].get("platform") == "{55555555-5555-5555-5555-555555555555}" for row in readbacks)


@pytest.mark.parametrize("stage", ["prewrite", "readback"])
@pytest.mark.parametrize("damage", ["wrong-guid", "missing", "path", "extra-member", "boolean", "read-error", "identity", "metadata"])
def test_standalone_history_reference_wrong_or_missing_observation_never_proves_effect(tmp_path, stage, damage):
    client, state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, source_operation="object.setReference")
    if stage == "readback":
        code, executed = run("execute", preview["transaction_id"])
        assert code == 0, executed
    value = {"wrong-guid": {"id": "{77777777-7777-7777-7777-777777777777}"}, "path": r"\Attenuations\Destination",
        "extra-member": {"id": client.parent["id"], "hidden": True}, "boolean": True}.get(damage)
    if damage in {"wrong-guid", "path", "extra-member", "boolean"}:
        client.source["@Attenuation"] = value
    elif damage == "missing":
        client.source.pop("@Attenuation")
    elif damage == "identity":
        client.source.update(name="Unrelated rename", path=r"\Other\Unrelated rename")
    original = client.call
    def changed(uri, args=None, options=None):
        if damage == "read-error" and uri == "ak.wwise.core.object.get" and "Attenuation" in (options or {}).get("return", []):
            raise ValueError("fixture exact reference view is unavailable")
        result = original(uri, args, options)
        if damage == "metadata" and uri == "ak.wwise.core.object.getPropertyInfo":
            return {**result, "restriction": {"type": "reference", "restrictions": [{"type": ["AuxBus"]}]}}
        return result
    client.call = changed
    code, rejected = run("execute" if stage == "prewrite" else "verify", preview["transaction_id"])
    assert code == 2 and rejected.get("verified") is not True, rejected
    assert len([call for call in client.calls if call[0] == "ak.wwise.core.undo.undo"]) == (1 if stage == "readback" else 0)
    if damage == "read-error":
        assert "fixture exact reference view is unavailable" in json.dumps(rejected)
        assert '"options": {"return": ["id", "name", "type", "path", "Attenuation"]' in json.dumps(rejected)


@pytest.mark.parametrize("platform", [None, "Windows"])
@pytest.mark.parametrize("stage", ["prewrite", "readback"])
def test_source_reference_original_read_platform_drift_stops_dispatch_or_verification(tmp_path, platform, stage):
    client, state, source, _preview, _shown, run = _owned_notes_history_case(tmp_path, source_operation="object.setReference",
        reference_platform=platform, source_prepared_only=True)
    original = TransactionStore(state).load_preview(source["transaction_id"]).artifact
    native = original["prepared_operation"]["dispatch"]["args"]
    assert ("platform" not in native) if platform is None else native["platform"] == platform
    assert original["prepared_operation"]["pre_state"]["field_read_platform"]["status"] == "certified"
    if stage == "readback":
        code, executed = run("execute", source["transaction_id"])
        assert code == 0, executed
    if platform is None:
        client.current_platform = client.platform_rows[1]["id"]
    else:
        client.platform_rows[0]["name"], client.platform_rows[1]["name"] = "Moved Windows", "Windows"
    code, rejected = run("execute" if stage == "prewrite" else "verify", source["transaction_id"])
    assert code == 2 and rejected.get("verified") is not True, rejected
    assert len([call for call in client.calls if call[0] == "ak.wwise.core.object.setReference"]) == (1 if stage == "readback" else 0)
    assert "original read-platform binding unchanged" in json.dumps(rejected)


@pytest.mark.parametrize("direction", ["undo", "redo"])
def test_standalone_history_compound_reference_and_name_reuse_the_scoped_observer(tmp_path, direction):
    client, state, source, preview, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation="waapi.undoGroup", compound_reference=True, direction=direction)
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["request"]["arguments"]["history_binding"]
    assert {row["field"] for row in binding["observations"]} == {"Attenuation", "name"}
    code, compact = run("transaction-show", preview["transaction_id"], "--summary-only")
    assert code == 0, compact
    summary = compact["preview_summary"]["history_action"]["expected_observations"]
    reference = next(row for row in summary if row["field"] == "Attenuation")
    assert reference["metadata_bound"] is True and reference["field_kind"] == "reference"
    assert "field_info" not in reference
    assert reference == {**{key: value for key, value in binding["observations"][0].items() if key != "field_info"}, "metadata_bound": True}
    assert "latest_project_history" in json.dumps(compact)
    code, full = run("transaction-show", preview["transaction_id"])
    assert code == 0, full
    full_binding = full["artifact"]["request"]["arguments"]["history_binding"]
    assert full_binding == binding
    assert full_binding["observations"][0]["field_info"]["restriction"]["type"] == "reference"
    code, source_full = run("transaction-show", source["transaction_id"])
    assert code == 0, source_full
    child = source_full["artifact"]["prepared_operation"]["pre_state"]["execution_plan"]["calls"][0]["prepared_operation"]
    assert child["pre_state"]["field_info"] == full_binding["observations"][0]["field_info"]
    assert child["pre_state"]["field_before"]["value"] == reference["before"]
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified
    assert verified["agent_result"]["result"] == {} and list(verified)[-1] == "agent_result"
    expected = client.history_before if direction == "undo" else client.history_after
    assert client.source["@Attenuation"] == expected["@Attenuation"] and client.source["name"] == expected["name"]


@pytest.mark.parametrize("platform", [None, "Windows"])
def test_standalone_history_scalar_receipt_reuses_original_read_platform_certification(tmp_path, platform):
    client, state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation="object.setProperty", property_platform=platform)
    observation = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["request"]["arguments"]["history_binding"]["observations"][0]
    assert observation["platform"] == "{55555555-5555-5555-5555-555555555555}"
    client.current_platform = client.platform_rows[1]["id"]
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified


def test_reference_source_without_platform_inventory_retains_receipt_limitation_without_blocking_write(tmp_path):
    client, state, source, rejected, _shown, _run = _owned_notes_history_case(tmp_path,
        source_operation="object.setReference", reference_platform=None, platform_inventory=False, declaration_error=True)
    assert "original current/named read platform is not certified" in rejected["message"]
    snapshot = TransactionStore(state).load_snapshot(source["transaction_id"])
    assert snapshot.record.state == TransactionState.VERIFIED
    assert snapshot.preview.artifact["prepared_operation"]["pre_state"]["field_read_platform"]["status"] == "unobserved"
    assert len([call for call in client.calls if call[0] == "ak.wwise.core.object.setReference"]) == 1
    assert not any(call[0] == "ak.wwise.core.undo.undo" for call in client.calls)


def test_standalone_history_reference_retains_omitted_metadata_name_and_type(tmp_path):
    client, state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation="object.setReference", omitted_reference_metadata=True)
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified
    observation = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["request"]["arguments"]["history_binding"]["observations"][0]
    assert observation["field_info"]["name"] is None and observation["field_info"]["type"] is None
    assert observation["field_info"]["field_binding"]["token"] == "Attenuation"


@pytest.mark.parametrize("null_value", ["{00000000-0000-0000-0000-000000000000}", {"id": "{00000000-0000-0000-0000-000000000000}", "name": ""}])
def test_standalone_history_reference_observer_uses_owning_explicit_null_representations(tmp_path, null_value):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, source_operation="object.setReference")
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    client.source["@Attenuation"] = null_value
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified


@pytest.mark.parametrize("platform", [None, "Windows"])
def test_history_reference_wrong_original_view_cannot_pass_from_another_current_platform(tmp_path, platform):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, source_operation="object.setReference",
        reference_platform=platform, effect=False)
    client.current_platform = client.platform_rows[1]["id"]
    assert client.other_reference is None  # A tempting but unrelated cleared view.
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == 2 and verified.get("verified") is not True, verified
    assert client.source["@Attenuation"] == {"id": client.parent["id"]}


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("clear", [False, True])
def test_history_reference_unlink_platform_is_not_a_certified_read_view(tmp_path, version, clear):
    null_platform = "{00000000-0000-0000-0000-000000000000}"
    client, _state, source, rejected, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation="object.setReference", reference_platform=null_platform,
        version=version, reference_clear=clear, declaration_error=True)
    assert "null GUID is an unlink instruction, not a certified read platform" in rejected["message"]
    code, full = run("transaction-show", source["transaction_id"])
    assert code == 0, full
    assert full["state"] == "verified"
    native = full["artifact"]["prepared_operation"]["dispatch"]["args"]
    assert native["platform"] == null_platform
    assert len([row for row in client.calls if row[0] == "ak.wwise.core.object.setReference"]) == 1
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("source_operation", ["object.setReference", "object.setProperty"])
@pytest.mark.parametrize("platform", [None, "Windows"])
def test_optional_history_platform_read_error_does_not_block_ordinary_source_write(tmp_path, source_operation, platform):
    client, _state, source, rejected, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation=source_operation, reference_platform=platform, property_platform=platform,
        source_platform_observer_error=True, declaration_error=True)
    assert "original current/named read platform is not certified" in rejected["message"]
    code, full = run("transaction-show", source["transaction_id"])
    assert code == 0 and full["state"] == "verified", full
    proof = full["artifact"]["prepared_operation"]["pre_state"]["field_read_platform"]
    assert proof["status"] == "unobserved" and proof["reason"] == "project_platform_read_failed"
    assert proof["error"]["error_code"] == "READBACK_FAILED"
    assert "fixture optional platform inventory read failed" in json.dumps(proof)
    assert proof["error"]["details"]["call"]["api"] == "ak.wwise.core.getProjectInfo"
    assert len([row for row in client.calls if row[0] == "ak.wwise.core." + source_operation]) == 1
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


def test_optional_history_observer_does_not_bypass_mandatory_project_guard_failure(tmp_path):
    client, _state, source, _preview, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation="object.setReference", reference_platform=None, source_prepared_only=True)
    original = client.call
    def failed_project(uri, args=None, options=None):
        if uri == "ak.wwise.core.getProjectInfo":
            raise ValueError("fixture required current-project read failed")
        return original(uri, args, options)
    client.call = failed_project
    code, rejected = run("execute", source["transaction_id"])
    assert code == 2 and rejected.get("executed") is not True, rejected
    assert "getProjectInfo" in rejected["message"]
    assert not any(row[0] == "ak.wwise.core.object.setReference" for row in client.calls)


def _created_leaf_history_case(tmp_path, *, version="2025.1", notes="Created notes"):
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, SECOND, CHILD
    task = OwnedGraphTask(tmp_path, version, "object.create")
    parent = task.bind(SECOND)
    code, declared = task.step("draft-declare-new", "--declaration-id", "leaf", "--parent-handle", parent,
        "--kind", "sound-sfx", "--name", "Rain", *([] if notes is None else ["--field", "notes", notes]))
    assert code == 0, declared
    source, shown = task.preview()
    code, verified = task.finish(source, shown)
    assert code == 0 and verified["verified"] is True, verified
    created = deepcopy(task.objects[CHILD])
    original = task.call
    task.history_effect = True
    def call(uri, args=None, options=None):
        if uri in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if task.history_effect:
                if uri.endswith(".undo"):
                    task.objects.pop(CHILD, None)
                else:
                    task.objects[CHILD] = deepcopy(created)
            return {}
        return original(uri, args, options)
    task.call = call
    return task, source, created


def _created_leaf_history_preview(task, source, direction="undo"):
    code, phase = task.run("draft-start", "ak.wwise.core.undo." + direction)
    assert code == 0, phase
    draft, authority, revision = phase["draft"]["draft_id"], phase["task_authority"], phase["draft"]["revision"]
    code, phase = task.run("draft-declare-core-plan", draft, "--task-authority", authority,
        "--expected-revision", str(revision), "--value", "history_scope", "latest_project_history",
        "--value", "expectation_receipt", source)
    assert code == 0, phase
    for command in ("draft-check", "preview-from-draft"):
        code, result = task.run(command, draft, "--task-authority", authority,
            "--expected-revision", str(phase["draft"]["revision"]))
        assert code == 0, result
    tx = result["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    return tx


def test_created_leaf_receipt_observes_undo_presence_through_public_gateway(tmp_path):
    task, source, created = _created_leaf_history_case(tmp_path)
    tx = _created_leaf_history_preview(task, source)
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert verified["verification_strength"] == "scoped_history_effect_readback"
    assert created["id"] not in task.objects
    assert [row[1:] for row in task.calls if row[0] == "ak.wwise.core.undo.undo"] == [({}, {})]
