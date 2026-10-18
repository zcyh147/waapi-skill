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
    assert any("materialized_scalars_and_existing_reference_or_null" in item
        for item in declaration["history"]["expectation_receipt"]["initial_observers"])
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
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["prepared_operation"]["pre_state"]["history_binding"]
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
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["prepared_operation"]["pre_state"]["history_binding"]
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
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["prepared_operation"]["pre_state"]["history_binding"]
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
    observation = shown["artifact"]["prepared_operation"]["pre_state"]["history_binding"]["observations"][0]
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
    binding = shown["artifact"]["prepared_operation"]["pre_state"]["history_binding"]
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
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["prepared_operation"]["pre_state"]["history_binding"]
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
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["prepared_operation"]["pre_state"]["history_binding"]
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
    full_binding = full["artifact"]["prepared_operation"]["pre_state"]["history_binding"]
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
    observation = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["prepared_operation"]["pre_state"]["history_binding"]["observations"][0]
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
    observation = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["prepared_operation"]["pre_state"]["history_binding"]["observations"][0]
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


def _created_leaf_history_case(tmp_path, *, version="2025.1", notes="Created notes", source_notes="observed",
    created_fields=False, reference=None, observer="complete", prepared_only=False, platform=None,
    source_class_metadata=None, sound_class_id=2, nested=False, declaration_only=False):
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, SECOND, CHILD, ROOT
    task = OwnedGraphTask(tmp_path, version, "object.create")
    if created_fields or reference:
        task.metadata.update(IsLoopingEnabled={"name": "IsLoopingEnabled", "type": "bool", "default": False},
            IsLoopingInfinite={"name": "IsLoopingInfinite", "type": "bool", "default": False},
            Volume={"name": "Volume", "type": "Real32", "restriction": {"type": "range", "min": -96, "max": 6}})
        original_source_fields = task.call
        task.current_platform = "{44444444-4444-4444-4444-444444444444}"
        task.platform_rows = [{"id": "{44444444-4444-4444-4444-444444444444}", "name": "Windows"},
            {"id": "{55555555-5555-5555-5555-555555555555}", "name": "Mac"}]
        def source_fields(uri, args=None, options=None):
            if uri.endswith("getPropertyInfo") and args.get("object") in task.objects and observer == "metadata-error":
                raise RuntimeError("fixture optional created-field metadata read failed")
            result = original_source_fields(uri, args, options)
            if uri.endswith("getPropertyInfo") and args.get("object") in task.objects and observer == "reference-metadata-omission":
                result = {key: value for key, value in result.items() if key not in {"name", "type"}}
            elif uri.endswith("getPropertyInfo") and args.get("object") in task.objects:
                if observer == "wrong-metadata-name": result = {**result, "name": "OtherField"}
                elif observer == "unknown-metadata-type": result = {**result, "type": "UncertifiedScalar"}
            if uri.endswith("getProjectInfo") and observer != "no-platform":
                result.update(currentPlatformId=task.current_platform, platforms=task.platform_rows)
            if uri.endswith("object.create"):
                task.objects[result["id"]]["classId"] = sound_class_id
                if source_class_metadata is not None:
                    for row in task.objects.values():
                        if row["type"] in {"Sound", "ActorMixer"}:
                            row["classId"] = next(info["classId"] for info in task.types if info["name"] == row["type"])
                        if row["type"] == "Sound":
                            for name, info in source_class_metadata.items():
                                if "default" in info: row.setdefault("@" + name, deepcopy(info["default"]))
            return result
        task.call = source_fields
    if reference:
        task.objects[ROOT] = {"id": ROOT, "name": "Rain attenuation", "type": "Attenuation",
            "path": r"\Attenuations\Default Work Unit\Rain attenuation", "notes": "Keep target"}
        task.types.append({"classId": 655376, "name": "Attenuation", "type": "WObject"})
        task.metadata["Attenuation"] = {"name": "Attenuation", "type": "Reference",
            "restriction": {"type": "reference", "restrictions": [{"type": ["Attenuation"]}]}}
    if source_class_metadata is not None:
        task.metadata.update(deepcopy(source_class_metadata))
        next(row for row in task.types if row["name"] == "Sound")["classId"] = sound_class_id
    parent = task.bind(SECOND)
    if platform is not None:
        code, configured = task.step("draft-business-configure", "--platform", platform)
        assert code == 0, configured
    values = []
    if created_fields:
        code, fields = task.step("draft-discover-fields", "--semantic-kind", "sound-sfx", "--meaning", "Volume")
        assert code == 0, fields
        values = ["--field", "loop", "infinite", "--field-value", fields["meaning_results"][0]["candidates"][0]["handle"], "-6.0"]
    if reference:
        target = task.bind(ROOT)
        code, fields = task.step("draft-discover-fields", "--semantic-kind", "sound-sfx", "--meaning", "Attenuation")
        assert code == 0, fields
        values.extend(["--field-value", fields["meaning_results"][0]["candidates"][0]["handle"],
            "null" if reference == "null" else target])
    if nested:
        code, container = task.step("draft-declare-new", "--declaration-id", "container", "--parent-handle", parent,
            "--kind", "actor-mixer", "--name", "Container", "--field", "notes", "Keep container")
        assert code == 0, container
        parent = container["draft"]["declared_object"]["result_handle"]
    code, declared = task.step("draft-declare-new", "--declaration-id", "leaf", "--parent-handle", parent,
        "--kind", "sound-sfx", "--name", "Rain",
        *([] if notes is None else ["--field", "notes", notes]), *values)
    assert code == 0, declared
    if declaration_only:
        return task, None, None
    source, shown = task.preview()
    if prepared_only:
        return task, source, shown
    if source_notes != "observed":
        source_call = task.call
        def source_boundary(uri, args=None, options=None):
            result = source_call(uri, args, options)
            if uri.endswith("object.create") and source_notes == "native-default":
                task.objects[result["id"]]["notes"] = "Native observed default"
            if uri.endswith("object.get") and source_notes == "missing":
                for row in result.get("return", []):
                    if row.get("name") == "Rain":
                        row.pop("notes", None)
            return result
        task.call = source_boundary
    code, verified = task.finish(source, shown)
    assert code == 0 and verified["verified"] is True, verified
    created = deepcopy(next(row for row in task.objects.values() if row["name"] == "Rain"))
    created_id = created["id"]
    original = task.call
    task.history_effect = True
    def call(uri, args=None, options=None):
        if uri in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if task.history_effect:
                if uri.endswith(".undo"):
                    task.objects.pop(created_id, None)
                else:
                    task.objects[created_id] = deepcopy(created)
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
    assert code == 0, json.dumps(phase)
    for command in ("draft-check", "preview-from-draft"):
        code, result = task.run(command, draft, "--task-authority", authority,
            "--expected-revision", str(phase["draft"]["revision"]))
        assert code == 0, json.dumps(result)
        if "draft" in result:
            phase = result
    tx = result["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    return tx


def test_created_source_missing_acknowledgement_is_indeterminate_and_never_replayed(tmp_path):
    task, source, shown = _created_leaf_history_case(tmp_path, version="2022.1",
        created_fields=True, reference="null", prepared_only=True)
    original = task.call

    def lost_response(uri, args=None, options=None):
        result = original(uri, args, options)
        # A write may have reached Wwise before the client loses its response.
        return None if uri == "ak.wwise.core.object.create" else result

    task.call = lost_response
    code, confirmed = task.run("confirm", source, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, failed = task.run("execute", source)
    assert code == 2 and failed["state"] == "indeterminate", failed
    assert failed["status"] == "indeterminate" and failed["automatic_retry"] is False
    assert failed["dispatch_result"]["result"] is None
    assert failed["dispatch_result"]["error_code"] == "WAAPI_RESPONSE_MISSING"
    assert failed["dispatch_result"]["failure_origin"] == "missing_response"
    assert failed["dispatch_result"]["details"]["effects_unknown"] is True
    assert failed["recovery"]["stage"] == "unknown_write_outcome"
    assert failed["recovery"]["project_write_outcome"] == "unknown"
    assert failed["recovery"]["original_write_replay_allowed"] is False
    assert "agent_result" not in failed and "verification" not in failed
    code, full = task.run("transaction-show", source)
    assert code == 0, full
    events = full["events"]
    assert [event["event_type"] for event in events][-2:] == ["execution_started", "execution_indeterminate"]
    assert not any(event["event_type"] in {"execution_completed", "verification_recorded"} for event in events)
    assert "Rain" in [row["name"] for row in task.objects.values()]
    code, replay = task.run("execute", source)
    assert code == 2 and replay.get("verified") is not True, replay
    code, verify = task.run("verify", source)
    assert code == 2 and verify.get("verified") is not True, verify
    writes = [row for row in task.calls if row[0] == "ak.wwise.core.object.create"]
    assert len(writes) == 1 and writes[0][1]["@Attenuation"] is None
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in task.calls)


def _existing_fields_history_case(tmp_path, *, version="2025.1", second=False,
    platform="{44444444-4444-4444-4444-444444444444}", prepared_only=False, postread_error=False):
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, CHILD, ROOT

    task = OwnedGraphTask(tmp_path, version, "object.set")
    task.require_class_projection = True
    task.types = [{"classId": value, "name": name, "type": "WObject"}
        for name, value in (("Sound", 65552), ("Attenuation", 655376), ("WorkUnit", 1638416))]
    task.objects = {
        SECOND: {"id": SECOND, "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
            "path": r"\Actor-Mixer Hierarchy\Default Work Unit", "notes": "Keep parent"},
        FIRST: {"id": FIRST, "name": "Rain", "type": "Sound", "classId": 65552,
            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain", "notes": "Keep Rain",
            "parent": {"id": SECOND}, "@Volume": -3.0, "@Priority": 50, "@Attenuation": {"id": ROOT}},
        ROOT: {"id": ROOT, "name": "Rain attenuation", "type": "Attenuation", "classId": 655376,
            "path": r"\Attenuations\Default Work Unit\Rain attenuation", "notes": "Keep target"},
    }
    if second:
        task.objects[CHILD] = {**task.objects[FIRST], "id": CHILD, "name": "Wind", "notes": "Keep Wind",
            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Wind", "@Volume": -9.0, "@Priority": 70, "@Attenuation": None}
    task.metadata = {
        "Volume": {"name": "Volume", "type": "Real64", "default": 0.0,
            "restriction": {"type": "range", "min": -96, "max": 6}},
        "Priority": {"name": "Priority", "type": "int16", "default": 50,
            "restriction": {"type": "range", "min": 0, "max": 100}},
        "Attenuation": {"name": "Attenuation", "type": "Reference", "restriction": {
            "type": "reference", "restrictions": [{"type": ["Attenuation"]}]}},
    }
    original = task.call
    task.current_platform = "{44444444-4444-4444-4444-444444444444}"
    task.history_effect = True
    before = deepcopy(task.objects)
    after = None

    def call(uri, args=None, options=None):
        nonlocal after
        if uri.endswith("isPropertyEnabled"):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {"return": True}
        if uri in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if task.history_effect:
                task.objects = deepcopy(before if uri.endswith(".undo") else after)
            return {}
        if (postread_error and after is not None and uri.endswith("object.get")
                and options.get("return", [])[:7] == ["id", "name", "type", "path", "classId", "parent", "notes"]):
            raise RuntimeError("optional existing-field history postread unavailable")
        result = original(uri, args, options)
        if uri.endswith("getProjectInfo"):
            result.update(currentPlatformId=task.current_platform, platforms=[
                {"id": "{44444444-4444-4444-4444-444444444444}", "name": "Windows"},
                {"id": "{55555555-5555-5555-5555-555555555555}", "name": "Mac"}])
        if uri.endswith("object.set"):
            after = deepcopy(task.objects)
        return result

    task.call = call
    target = task.bind(ROOT)
    if platform is not None:
        code, configured = task.step("draft-business-configure", "--platform", platform)
        assert code == 0, configured
    for identity, volume, priority, attenuation in [(FIRST, "-6", "42", "null"),
            *([(CHILD, "-12", "12", target)] if second else [])]:
        owner = task.bind(identity)
        fields = [task.discover(owner, name) for name in ("Volume", "Priority", "Attenuation")]
        code, declared = task.step("draft-declare-existing", "--declaration-id", "rain" if identity == FIRST else "wind",
            "--object-handle", owner, "--field-value", fields[0], volume,
            "--field-value", fields[1], priority, "--field-value", fields[2], attenuation)
        assert code == 0, declared
    tx, shown = task.preview()
    task.source_preview = shown
    if prepared_only:
        return task, tx, before, None
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified["verified"] is True, verified
    return task, tx, before, after


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
def test_existing_multi_field_set_receipt_undo_redo_observes_every_scalar_and_null(tmp_path, version):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT
    task, source, before, after = _existing_fields_history_case(tmp_path, version=version)
    assert task.objects[FIRST]["@Attenuation"] is None
    assert task.objects[FIRST]["@Volume"] == -6 and task.objects[FIRST]["@Priority"] == 42
    undo = _created_leaf_history_preview(task, source)
    code, executed = task.run("execute", undo)
    assert code == 0, executed
    code, verified = task.run("verify", undo)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST] == before[FIRST] and task.objects[ROOT] == before[ROOT]
    if version == "2022.1":
        return  # Matching native catalog has undo, no redo URI.
    redo = _created_leaf_history_preview(task, source, "redo")
    code, executed = task.run("execute", redo)
    assert code == 0, executed
    code, verified = task.run("verify", redo)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST] == after[FIRST] and task.objects[ROOT] == before[ROOT]
    assert verified["verification_strength"] == "scoped_history_effect_readback"
    assert len([row for row in task.calls if row[0] == "ak.wwise.core.object.set"]) == 1


@pytest.mark.parametrize("corruption", ["raw-metadata-extension", "class", "numeric-bool", "missing-field", "reference-target"])
def test_existing_field_history_rejects_incomplete_or_changed_original_scope_before_write(tmp_path, corruption):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT
    task, source, _before, _after = _existing_fields_history_case(tmp_path)
    draft, authority, revision = _created_history_reference_draft(task, source)
    if corruption == "raw-metadata-extension": task.metadata["Volume"]["nativeExtension"] = None
    elif corruption == "class": task.objects[FIRST]["classId"] = 65553
    elif corruption == "numeric-bool": task.objects[FIRST]["@Priority"] = True
    elif corruption == "missing-field": del task.objects[FIRST]["@Attenuation"]
    else: task.objects[ROOT]["name"] = "Changed reference target"
    code, rejected = task.run("draft-check", draft, "--task-authority", authority, "--expected-revision", str(revision))
    assert code == 2, rejected
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in task.calls)
    assert "readback" in json.dumps(rejected).casefold()


def test_existing_field_history_optional_postread_failure_keeps_source_verified(tmp_path):
    task, source, _before, _after = _existing_fields_history_case(tmp_path, postread_error=True)
    code, full = task.run("transaction-show", source)
    assert code == 0 and full["state"] == "verified", full
    observation = next(event["details"]["verification"] for event in full["events"] if event["event_type"] == "verification_recorded")
    optional = [row for row in observation["readbacks"] if row.get("role") == "existing-field-history-source-after"]
    assert len(optional) == 1 and optional[0]["status"] == "unobserved"
    assert "optional existing-field history postread unavailable" in json.dumps(optional)
    code, phase = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, phase
    code, rejected = task.run("draft-declare-core-plan", phase["draft"]["draft_id"],
        "--task-authority", phase["task_authority"], "--expected-revision", str(phase["draft"]["revision"]),
        "--value", "history_scope", "latest_project_history", "--value", "expectation_receipt", source)
    assert code == 2 and "unavailable" in rejected["message"], rejected
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in task.calls)


@pytest.mark.parametrize("platform", [None, "Windows"])
def test_existing_field_source_keeps_original_certified_read_view_before_write(tmp_path, platform):
    task, source, _before, _after = _existing_fields_history_case(tmp_path, platform=platform, prepared_only=True)
    task.current_platform = "{55555555-5555-5555-5555-555555555555}"
    if platform == "Windows":
        original = task.call
        def renamed_platform(uri, args=None, options=None):
            result = original(uri, args, options)
            if uri.endswith("getProjectInfo"):
                result["platforms"][0]["name"] = "Old Windows"
                result["platforms"][1]["name"] = "Windows"
            return result
        task.call = renamed_platform
    assert task.run("confirm", source, "--confirmation-token", task.source_preview["confirmation"]["token"])[0] == 0
    code, rejected = task.run("execute", source)
    assert code == 2 and rejected.get("executed") is not True, rejected
    assert not any(row[0] == "ak.wwise.core.object.set" for row in task.calls)


def test_existing_field_history_native_success_does_not_prove_all_fields_restored(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST
    task, source, before, _after = _existing_fields_history_case(tmp_path)
    history = _created_leaf_history_preview(task, source)
    original = task.call
    def partial_undo(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == "ak.wwise.core.undo.undo":
            task.objects[FIRST]["@Priority"] = True
        return result
    task.call = partial_undo
    assert task.run("execute", history)[0] == 0
    code, failed = task.run("verify", history)
    assert code == 2 and failed.get("verified") is False, failed
    assert task.objects[FIRST]["@Volume"] == before[FIRST]["@Volume"]
    assert task.objects[FIRST]["@Attenuation"] == before[FIRST]["@Attenuation"]
    assert '"actual": true' in json.dumps(failed) and '"expected": 50' in json.dumps(failed)
    assert len([row for row in task.calls if row[0] == "ak.wwise.core.undo.undo"]) == 1


@pytest.mark.parametrize("platform", [None, "Windows"])
def test_existing_history_uses_frozen_guid_view_after_source_current_platform_changes(tmp_path, platform):
    task, source, _before, _after = _existing_fields_history_case(tmp_path, platform=platform)
    task.current_platform = "{55555555-5555-5555-5555-555555555555}"
    history = _created_leaf_history_preview(task, source)
    assert task.run("execute", history)[0] == 0
    before_verify = len(task.calls)
    code, verified = task.run("verify", history)
    assert code == 0 and verified["verified"] is True, verified
    field_reads = [options for uri, _args, options in task.calls[before_verify:]
        if uri == "ak.wwise.core.object.get" and "Priority" in options.get("return", [])]
    assert field_reads and all(options["platform"] == "{44444444-4444-4444-4444-444444444444}" for options in field_reads)


@pytest.mark.parametrize("drift", [False, True])
def test_field_read_view_observer_composes_top_level_and_existing_certificates(drift):
    from wwise_waapi.edit_history_business import capture_field_read_platform, observe_field_read_platform
    windows = "{44444444-4444-4444-4444-444444444444}"
    mac = "{55555555-5555-5555-5555-555555555555}"
    current = windows
    def read(uri, args, options):
        assert (uri, args, options) == ("ak.wwise.core.getProjectInfo", {}, {})
        return {"currentPlatformId": current, "platforms": [
            {"id": windows, "name": "Windows"}, {"id": mac, "name": "Mac"}]}
    top = capture_field_read_platform("2025.1", None, read=read)
    existing = capture_field_read_platform("2025.1", "Windows", read=read)
    # No current public producer emits both groups; this shared observer admits
    # their composition and must not let one certificate mask the other.
    if drift:
        current = mac
    observed = observe_field_read_platform({"field_read_platform": top,
        "existing_field_observations": [{"status": "certified", "field_read_platform": existing}]}, read=read)
    assert observed["matches"] is not drift
    assert len(observed["views"]) == len(observed["readbacks"]) == 2
    assert {view["expected"]["selector"] for view in observed["views"]} == {None, "Windows"}
    assert [view["matches"] for view in observed["views"]].count(False) == int(drift)


@pytest.mark.parametrize("kind,value", [
    ("properties", {"name": "Volume", "array": [1, 2]}),
    ("properties", {"name": "Volume", "value": [1, 2]}),
    ("references", {"name": "Volume", "curve": {"curve_points": []}}),
    ("references", {"name": "Volume", "target_id": []}),
])
def test_optional_existing_history_unknown_union_remains_unobserved_without_read(kind, value):
    from wwise_waapi.existing_field_observations import capture_before
    from wwise_waapi.builders.metadata import parse_get_property_info_result
    node = {"request_path": "$.objects[0]", "target_id": "{11111111-1111-1111-1111-111111111111}",
        "platform": "{44444444-4444-4444-4444-444444444444}", kind: [value]}
    info = parse_get_property_info_result({"name": "Volume", "type": "Real64"})
    observed = capture_before(node, {"volume": info}, version="2025.1", catalog=[],
        read=lambda *_args: pytest.fail("An unsupported optional union must not dispatch reads"))
    assert observed["status"] == "unobserved"
    assert observed["reason"] == "field_union_requires_its_complete_history_observer"


def _render_history_case(tmp_path, *, version="2025.1", operation="object.setProperty", clear=False,
    platform="{44444444-4444-4444-4444-444444444444}", prepared_only=False, platform_inventory=True, target_read_failure=None):
    from copy import deepcopy
    from tests.unit.test_list_merge_existing_conditions_gateway import list_task
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT, CHILD
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT

    task, _ = list_task(tmp_path, version=version, operation=operation)
    legacy = version in {"2021.1", "2022.1"}
    if legacy:
        del task.objects[ROOT], task.objects[CHILD], task.objects[FIRST]["@Effects"]
        task.types = [row for row in task.types if row["name"] != "EffectSlot"]
        task.metadata = {}
        for i in range(4):
            task.objects[FIRST].update({f"@Effect{i}": {"id": EFFECT}, f"@RenderEffect{i}": False, f"@BypassEffect{i}": i == 0})
            task.metadata[f"Effect{i}"] = {"name": f"Effect{i}", "type": "", "default": None,
                "restriction": {"type": "reference", "restrictions": [{"type": ["Effect"]}]}}
            for prefix in ("Bypass", "Render"):
                task.metadata[f"{prefix}Effect{i}"] = {"name": f"{prefix}Effect{i}", "type": "bool", "default": False,
                    "dependencies": [{"type": "reference", "action": "Enable", "context": "Self", "property": f"Effect{i}",
                        "conditions": [{"referenceIsSet": True}]}]}
    else:
        task.objects[ROOT]["@Bypass"] = True
    if clear:
        task.objects[ROOT]["@Render"] = task.objects[CHILD]["@Render"] = True
    original = task.call
    before, after, writes = deepcopy(task.objects), None, []
    task.current_platform = "{44444444-4444-4444-4444-444444444444}"
    task.history_effect = True
    def call(uri, args=None, options=None):
        nonlocal after
        if uri.endswith("isPropertyEnabled"):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {"return": True}
        if uri in {"ak.wwise.core.object.set", "ak.wwise.core.object.setProperty"}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            writes.append((uri, deepcopy(args)))
            if legacy:
                task.objects[FIRST]["@RenderEffect0"] = task.objects[FIRST]["@RenderEffect1"] = True
            else:
                task.objects[ROOT]["@Render"] = task.objects[CHILD]["@Render"] = not clear
            after = deepcopy(task.objects)
            return {"objects": [{"id": node["object"], "name": task.objects[node["object"]]["name"]} for node in args["objects"]]} if operation == "object.set" else {}
        if uri in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if task.history_effect:
                task.objects = deepcopy(before if uri.endswith(".undo") else after)
            return {}
        if (target_read_failure and uri.endswith("object.get") and args.get("from") == {"id": [EFFECT]}
                and "notes" in options.get("return", []) and (target_read_failure == "before" or after is not None)):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            raise RuntimeError("Optional legacy Effect target read unavailable")
        result = original(uri, args, options)
        if uri.endswith("getProjectInfo") and platform_inventory:
            result.update(currentPlatformId=task.current_platform, platforms=[
                {"id": "{44444444-4444-4444-4444-444444444444}", "name": "Windows"},
                {"id": "{55555555-5555-5555-5555-555555555555}", "name": "Mac"}])
        return result
    task.call = call
    target = task.bind(FIRST if legacy else ROOT if clear else CHILD)
    code, discovered = task.step("draft-discover-fields", "--object-handle", target,
        "--meaning", "RenderEffect1" if legacy else "Render", *(["--platform", platform] if platform is not None else []))
    assert code == 0, discovered
    render = (discovered["field_candidates"][0]["handle"] if "field_candidates" in discovered else
        discovered["meaning_results"][0]["candidates"][0]["handle"])
    if operation == "object.setProperty":
        code, declared = task.step("draft-declare-field-change", "--object-handle", target,
            "--field-handle", render, "--business-value", "false" if clear else "true")
    else:
        code, declared = task.step("draft-declare-existing", "--declaration-id", "slot", "--object-handle", target,
            "--field-value", render, "false" if clear else "true")
    assert code == 0, declared
    source, shown = task.preview()
    task.source_preview = shown
    if not prepared_only:
        code, verified = task.finish(source, shown)
        assert code == 0 and verified["verified"] is True, verified
    return task, source, before, after, writes


@pytest.mark.parametrize("version,operation,platform,clear", [
    ("2023.1", "object.setProperty", "{44444444-4444-4444-4444-444444444444}", False),
    ("2024.1", "object.setProperty", "Windows", False),
    ("2025.1", "object.setProperty", None, False),
    ("2023.1", "object.set", None, False),
    ("2024.1", "object.set", "Windows", False),
    ("2025.1", "object.set", "{44444444-4444-4444-4444-444444444444}", False),
    ("2025.1", "object.setProperty", None, True),
])
def test_render_history_receipt_restores_complete_existing_chain_and_derived_field(tmp_path, version, operation, platform, clear):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT, CHILD
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT
    task, source, before, after, writes = _render_history_case(tmp_path, version=version, operation=operation,
        platform=platform, clear=clear)
    assert task.objects[ROOT]["@Render"] is (not clear) and task.objects[CHILD]["@Render"] is (not clear)
    # History observes the original GUID view, independent of a later UI selection.
    task.current_platform = "{55555555-5555-5555-5555-555555555555}"
    for direction, expected in (("undo", before), ("redo", after)):
        tx = _created_leaf_history_preview(task, source, direction)
        code, executed = task.run("execute", tx)
        assert code == 0, json.dumps(executed)
        code, verified = task.run("verify", tx)
        assert code == 0 and verified["verified"] is True, verified
        assert task.objects[FIRST]["@Effects"] == before[FIRST]["@Effects"]
        assert task.objects[ROOT] == expected[ROOT] and task.objects[CHILD] == expected[CHILD]
        assert task.objects[EFFECT] == before[EFFECT]
    assert len(writes) == 1
    native = writes[0][1]
    assert (native if operation == "object.setProperty" else native["objects"][0]).get("platform") == platform


@pytest.mark.parametrize("fault", ["order", "missing-member", "duplicate-member", "owner", "class", "effect", "bypass", "target", "raw-metadata"])
def test_render_history_refuses_drift_of_complete_original_chain_before_dispatch(tmp_path, fault):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT, CHILD, SECOND
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT
    task, source, _, _, _ = _render_history_case(tmp_path)
    if fault == "order": task.objects[FIRST]["@Effects"].reverse()
    elif fault == "missing-member": task.objects[FIRST]["@Effects"].pop()
    elif fault == "duplicate-member": task.objects[FIRST]["@Effects"].append({"id": ROOT})
    elif fault == "owner": task.objects[ROOT]["owner"] = {"id": SECOND}
    elif fault == "class": task.objects[ROOT]["classId"] = 65552
    elif fault == "effect": task.objects[ROOT]["@Effect"] = None
    elif fault == "bypass": task.objects[ROOT]["@Bypass"] = False
    elif fault == "target": task.objects[EFFECT]["notes"] = "Unrequested target drift"
    else: task.metadata["Render"]["nativeExtension"] = None
    draft, authority, revision = _created_history_reference_draft(task, source)
    code, rejected = task.run("draft-check", draft, "--task-authority", authority, "--expected-revision", str(revision))
    assert code == 2 and rejected["error_code"] == "HISTORY_EXPECTATION_CHANGED", rejected
    assert not any(uri.endswith("undo.undo") for uri, _, _ in task.calls)
    assert "readbacks" in rejected["details"] or "history_observation" in rejected["details"]


def test_render_history_retains_independent_readback_when_native_undo_omits_derived_change(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import ROOT, CHILD
    task, source, before, _, _ = _render_history_case(tmp_path)
    tx = _created_leaf_history_preview(task, source)
    assert task.run("execute", tx)[0] == 0
    task.objects[ROOT]["@Render"] = True
    assert task.objects[CHILD]["@Render"] == before[CHILD]["@Render"] is False
    code, verified = task.run("verify", tx)
    assert code == 2 and verified.get("verified") is not True, verified
    assert "Render" in json.dumps(verified) and "readbacks" in json.dumps(verified)
    assert task.run("execute", tx)[0] == 2
    assert len([uri for uri, _, _ in task.calls if uri.endswith("undo.undo")]) == 1


@pytest.mark.parametrize("operation", ["object.setProperty", "object.set"])
def test_legacy_render_history_restores_all_owner_flags_and_effect_targets(tmp_path, operation):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT
    task, source, before, after, writes = _render_history_case(tmp_path, version="2022.1", operation=operation)
    assert after[FIRST] == {**before[FIRST], "@RenderEffect0": True, "@RenderEffect1": True}
    tx = _created_leaf_history_preview(task, source)
    assert task.run("execute", tx)[0] == 0
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[FIRST] == before[FIRST] and task.objects[EFFECT] == before[EFFECT]
    assert len(writes) == 1
    code, redo = task.run("draft-start", "ak.wwise.core.undo.redo")
    assert code == 2 and "2022.1" in json.dumps(redo), redo


def test_legacy_render_source_2021_preserves_native_history_gate(tmp_path):
    task, source, before, after, writes = _render_history_case(tmp_path, version="2021.1")
    assert len(writes) == 1 and before != after
    code, unavailable = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 2 and "2021.1" in json.dumps(unavailable), unavailable


@pytest.mark.parametrize("platform", [None, "Windows"])
def test_render_source_original_platform_certificate_drift_blocks_write(tmp_path, platform):
    task, source, before, _, writes = _render_history_case(tmp_path, operation="object.set", platform=platform, prepared_only=True)
    task.current_platform = "{55555555-5555-5555-5555-555555555555}"
    if platform == "Windows":
        original = task.call
        def changed_names(uri, args=None, options=None):
            result = original(uri, args, options)
            if uri.endswith("getProjectInfo"):
                result["platforms"][0]["name"] = "Old Windows"
                result["platforms"][1]["name"] = "Windows"
            return result
        task.call = changed_names
    assert task.run("confirm", source, "--confirmation-token", task.source_preview["confirmation"]["token"])[0] == 0
    code, rejected = task.run("execute", source)
    assert code == 2 and rejected.get("executed") is not True and not writes, rejected
    assert task.objects == before


def test_render_history_review_keeps_exact_fields_and_full_source_raw_proof(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import ROOT, CHILD
    task, source, _, _, _ = _render_history_case(tmp_path)
    tx = _created_leaf_history_preview(task, source)
    code, compact = task.run("transaction-show", tx, "--summary-only")
    assert code == 0, compact
    chain, = compact["preview_summary"]["history_action"]["expected_observations"]
    assert [row["id"] for row in chain["members_in_original_order"]] == [ROOT, CHILD]
    assert all(row["changes"]["Render"] == {"before": False, "after": True} for row in chain["members_in_original_order"])
    assert [row["preserved"]["Bypass"] for row in chain["members_in_original_order"]] == [True, False]
    assert chain["metadata_bound"] is True and chain["all_other_projected_state_preserved"] is True
    code, full = task.run("transaction-show", tx)
    assert code == 0, full
    rows = full["artifact"]["prepared_operation"]["pre_state"]["history_binding"]["observations"]
    field_rows = [row for row in rows if row["kind"] == "existing_field"]
    assert {row["object_before"]["id"] for row in field_rows} == {ROOT, CHILD}
    assert all("raw" in row["field_info"] for row in field_rows)
    chain_row, = [row for row in rows if row["kind"] == "existing_render_chain"]
    assert all("raw" in row for row in chain_row["after"]["metadata"])
    assert task.run("execute", tx)[0] == 0
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert list(verified)[-1] == "agent_result" and verified["agent_result"]["result"] == {}


@pytest.mark.parametrize("stage", ["execute", "verify"])
def test_render_history_rechecks_unrequested_effect_target_at_durable_phases(tmp_path, stage):
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT
    task, source, _, _, _ = _render_history_case(tmp_path)
    tx = _created_leaf_history_preview(task, source)
    if stage == "verify":
        assert task.run("execute", tx)[0] == 0
    task.objects[EFFECT]["notes"] = "Unrequested drift after Preview"
    code, rejected = task.run(stage, tx)
    assert code == 2 and rejected.get("verified") is not True, rejected
    assert len([uri for uri, _, _ in task.calls if uri.endswith("undo.undo")]) == (stage == "verify")
    assert "Unrequested drift after Preview" in json.dumps(rejected)


def test_render_history_retains_actual_missing_readback_error_without_history_dispatch(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import ROOT
    task, source, _, _, _ = _render_history_case(tmp_path)
    draft, authority, revision = _created_history_reference_draft(task, source)
    original = task.call
    def unavailable(uri, args=None, options=None):
        if uri.endswith("object.get") and args.get("from") == {"id": [ROOT]}:
            task.calls.append((uri, args, options))
            raise RuntimeError("Exact Render member read unavailable")
        return original(uri, args, options)
    task.call = unavailable
    code, rejected = task.run("draft-check", draft, "--task-authority", authority, "--expected-revision", str(revision))
    assert code == 2 and "Exact Render member read unavailable" in json.dumps(rejected), rejected
    assert "readbacks" in json.dumps(rejected) and not any(uri.endswith("undo.undo") for uri, _, _ in task.calls)


def test_render_optional_uncertified_view_keeps_source_write_usable_without_strong_receipt(tmp_path):
    task, source, _, _, writes = _render_history_case(tmp_path, operation="object.set", platform=None, platform_inventory=False)
    assert len(writes) == 1
    code, full = task.run("transaction-show", source)
    assert code == 0 and full["state"] == "verified", full
    code, started = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, started
    code, rejected = task.run("draft-declare-core-plan", started["draft"]["draft_id"],
        "--task-authority", started["task_authority"], "--expected-revision", str(started["draft"]["revision"]),
        "--value", "history_scope", "latest_project_history", "--value", "expectation_receipt", source)
    assert code == 2 and "original chain read view is not certified" in rejected["message"], rejected
    assert not any(uri.endswith("undo.undo") for uri, _, _ in task.calls)


@pytest.mark.parametrize("stage", ["before", "after"])
def test_legacy_render_optional_target_observation_failure_keeps_source_usable(tmp_path, stage):
    task, source, _, _, writes = _render_history_case(tmp_path, version="2022.1", target_read_failure=stage)
    assert len(writes) == 1
    code, started = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, started
    code, rejected = task.run("draft-declare-core-plan", started["draft"]["draft_id"],
        "--task-authority", started["task_authority"], "--expected-revision", str(started["draft"]["revision"]),
        "--value", "history_scope", "latest_project_history", "--value", "expectation_receipt", source)
    assert code == 2 and "target" in rejected["message"].casefold(), rejected
    code, full = task.run("transaction-show", source)
    assert code == 0 and full["state"] == "verified", full
    assert "Optional legacy Effect target read unavailable" in json.dumps(full)
    assert not any(uri.endswith("undo.undo") for uri, _, _ in task.calls)




def test_legacy_render_optional_target_witness_preserves_existing_aggregate_bound(tmp_path, monkeypatch):
    from wwise_waapi import operation_registry
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT
    monkeypatch.setattr(operation_registry, "OBJECT_LIST_MAX_SUBTREE_NODES", 4)
    task, source, _, _, writes = _render_history_case(tmp_path, version="2022.1")
    assert len(writes) == 1
    code, started = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, started
    code, rejected = task.run("draft-declare-core-plan", started["draft"]["draft_id"],
        "--task-authority", started["task_authority"], "--expected-revision", str(started["draft"]["revision"]),
        "--value", "history_scope", "latest_project_history", "--value", "expectation_receipt", source)
    assert code == 2 and "target observation is unavailable" in rejected["message"], rejected
    assert not [uri for uri, args, options in task.calls if uri.endswith("object.get")
        and args.get("from") == {"id": [EFFECT]} and "notes" in options.get("return", [])]


def test_created_leaf_receipt_observes_undo_presence_through_public_gateway(tmp_path):
    task, source, created = _created_leaf_history_case(tmp_path)
    tx = _created_leaf_history_preview(task, source)
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    assert executed["dispatch_result"]["result"] == {}
    code, verified = task.run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    assert verified["verification_strength"] == "scoped_history_effect_readback"
    assert created["id"] not in task.objects
    assert [row[1:] for row in task.calls if row[0] == "ak.wwise.core.undo.undo"] == [({}, {})]


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
def test_created_leaf_history_restores_semantic_and_explicit_scalar_fields(tmp_path, version):
    task, source, created = _created_leaf_history_case(tmp_path, version=version, created_fields=True)
    assert created["@IsLoopingEnabled"] is True and created["@IsLoopingInfinite"] is True and created["@Volume"] == -6.0
    for direction in (["undo"] if version == "2022.1" else ["undo", "redo"]):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run("execute", tx)[0] == 0
        code, verified = task.run("verify", tx)
        assert code == 0 and verified["verified"] is True, verified
        assert verified["verification_strength"] == "scoped_history_effect_readback"
        assert list(verified)[-1] == "agent_result" and verified["agent_result"]["result"] == {}
    if version != "2022.1":
        assert task.objects[created["id"]] == created
    assert len([call for call in task.calls if call[0].endswith("object.create")]) == 1


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("reference", ["existing", "null"])
def test_created_leaf_history_restores_existing_reference_or_explicit_null(tmp_path, reference, version):
    task, source, created = _created_leaf_history_case(tmp_path, version=version, reference=reference)
    assert created["@Attenuation"] == (None if reference == "null" else "{33333333-3333-3333-3333-333333333333}")
    for direction in (["undo"] if version == "2022.1" else ["undo", "redo"]):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run("execute", tx)[0] == 0
        code, verified = task.run("verify", tx)
        assert code == 0 and verified["verified"] is True, verified
    if version != "2022.1":
        assert task.objects[created["id"]] == created


def test_created_reference_history_revalidates_its_existing_target_role(tmp_path):
    task, source, _created = _created_leaf_history_case(tmp_path, reference="existing")
    tx = _created_leaf_history_preview(task, source)
    task.objects["{33333333-3333-3333-3333-333333333333}"]["name"] = "Changed target"
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(call[0].startswith("ak.wwise.core.undo.") for call in task.calls)


def test_created_reference_metadata_omission_is_bound_from_exact_source_names(tmp_path):
    task, source, _created = _created_leaf_history_case(tmp_path, reference="existing", observer="reference-metadata-omission")
    tx = _created_leaf_history_preview(task, source)
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    binding = shown["artifact"]["prepared_operation"]["pre_state"]["history_binding"]
    field = next(item for item in binding["observations"] if item.get("kind") == "creation_field")
    assert field["field_info"]["name"] is None and field["field_info"]["type"] is None
    assert field["field_info"]["field_binding"]["token"] == "Attenuation"
    assert "name" not in field["field_info"]["raw"] and "type" not in field["field_info"]["raw"]
    assert task.run("execute", tx)[0] == 0
    assert task.run("verify", tx)[0] == 0


def test_created_fields_history_rejects_native_metadata_omission_to_null_before_dispatch(tmp_path):
    task, source, _created = _created_leaf_history_case(tmp_path, created_fields=True)
    assert "default" not in task.metadata["Volume"]
    tx = _created_leaf_history_preview(task, source)
    task.metadata["Volume"]["default"] = None
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(call[0].startswith("ak.wwise.core.undo.") for call in task.calls)
    assert '"default": null' in json.dumps(rejected)


def test_created_fields_review_is_compact_and_full_source_metadata_remains_available(tmp_path):
    task, source, _created = _created_leaf_history_case(tmp_path, created_fields=True)
    tx = _created_leaf_history_preview(task, source)
    code, compact = task.run("transaction-show", tx, "--summary-only")
    assert code == 0, compact
    presence, = compact["preview_summary"]["history_action"]["expected_observations"]
    fields = presence["fields"]
    assert {item["field"] for item in fields} == {"IsLoopingEnabled", "IsLoopingInfinite", "Volume"}
    assert all(item["metadata_bound"] is True and "field_info" not in item for item in fields)
    code, full = task.run("transaction-show", tx)
    assert code == 0, full
    raw = full["artifact"]["prepared_operation"]["pre_state"]["history_binding"]["observations"]
    assert all(item["field_info"]["type"] for item in raw if item.get("kind") == "creation_field")
    volume = next(item["field_info"] for item in raw if item.get("field") == "Volume")
    assert volume["default"] is None and "default" not in volume["raw"]
    assert volume["raw"] == task.metadata["Volume"]
    assert compact.get("agent_result") == full.get("agent_result")


@pytest.mark.parametrize("budget", ["observations", "bytes"])
def test_created_fields_history_keeps_combined_observation_and_proof_bounds(tmp_path, monkeypatch, budget):
    from wwise_waapi import edit_history_business
    task, source, _created = _created_leaf_history_case(tmp_path, created_fields=True)
    monkeypatch.setattr(edit_history_business, "MAX_OBSERVATIONS" if budget == "observations" else "MAX_BINDING_BYTES",
        3 if budget == "observations" else 1024)
    code, started = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, started
    code, rejected = task.run("draft-declare-core-plan", started["draft"]["draft_id"],
        "--task-authority", started["task_authority"], "--expected-revision", str(started["draft"]["revision"]),
        "--value", "history_scope", "latest_project_history", "--value", "expectation_receipt", source)
    assert code == 2, rejected
    assert "bound" in rejected["message"]
    assert not any(call[0].startswith("ak.wwise.core.undo.") for call in task.calls)


def test_created_fields_2021_keeps_source_creation_and_exact_native_history_boundary(tmp_path):
    task, source, _created = _created_leaf_history_case(tmp_path, version="2021.1", created_fields=True)
    assert task.run("transaction-show", source)[1]["state"] == "verified"
    code, rejected = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 2, rejected
    assert not any(call[0].startswith("ak.wwise.core.undo.") for call in task.calls)


def test_created_history_keeps_original_guid_view_after_current_platform_changes(tmp_path):
    task, source, _created = _created_leaf_history_case(tmp_path, created_fields=True)
    task.current_platform = "{55555555-5555-5555-5555-555555555555}"
    for direction in ("undo", "redo"):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run("execute", tx)[0] == 0
        assert task.run("verify", tx)[0] == 0
    field_reads = [options for uri, args, options in task.calls if uri.endswith("object.get")
        and ({"Volume", "@Volume"} & set(options.get("return", [])))]
    assert field_reads and all(options["platform"] == "{44444444-4444-4444-4444-444444444444}" for options in field_reads)


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
@pytest.mark.parametrize("platform", ["Windows", "{44444444-4444-4444-4444-444444444444}"])
def test_created_fields_named_and_guid_platform_keep_native_intent_and_frozen_history_view(tmp_path, version, platform):
    task, source, _created = _created_leaf_history_case(tmp_path, version=version, created_fields=True, platform=platform)
    native = next(args for uri, args, _options in task.calls if uri.endswith("object.create"))
    assert native["platform"] == platform
    task.current_platform = "{55555555-5555-5555-5555-555555555555}"
    task.platform_rows[0]["name"], task.platform_rows[1]["name"] = "Old Windows", "Windows"
    for direction in (["undo"] if version == "2022.1" else ["undo", "redo"]):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run("execute", tx)[0] == 0
        assert task.run("verify", tx)[0] == 0


@pytest.mark.parametrize("stage", ["prewrite", "readback"])
def test_created_fields_named_platform_drift_blocks_source_before_dispatch(tmp_path, stage):
    task, source, shown = _created_leaf_history_case(tmp_path, created_fields=True, platform="Windows", prepared_only=True)
    assert task.run("confirm", source, "--confirmation-token", shown["confirmation"]["token"])[0] == 0
    if stage == "readback":
        assert task.run("execute", source)[0] == 0
    task.platform_rows[0]["name"], task.platform_rows[1]["name"] = "Old Windows", "Windows"
    code, rejected = task.run("execute" if stage == "prewrite" else "verify", source)
    assert code == 2, rejected
    assert len([call for call in task.calls if call[0].endswith("object.create")]) == int(stage == "readback")


@pytest.mark.parametrize("observer", ["no-platform", "metadata-error", "wrong-metadata-name", "unknown-metadata-type"])
def test_created_fields_optional_observation_does_not_block_source_creation(tmp_path, observer):
    task, source, _created = _created_leaf_history_case(tmp_path, created_fields=True, observer=observer)
    code, full = task.run("transaction-show", source)
    assert code == 0 and full["state"] == "verified", full
    code, started = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, started
    code, rejected = task.run("draft-declare-core-plan", started["draft"]["draft_id"],
        "--task-authority", started["task_authority"], "--expected-revision", str(started["draft"]["revision"]),
        "--value", "history_scope", "latest_project_history", "--value", "expectation_receipt", source)
    assert code == 2, rejected
    assert len([call for call in task.calls if call[0].endswith("object.create")]) == 1
    assert not any(call[0].startswith("ak.wwise.core.undo.") for call in task.calls)
    if observer == "metadata-error":
        assert "fixture optional created-field metadata read failed" in json.dumps(full)


@pytest.mark.parametrize("stage", ["prewrite", "readback"])
def test_created_fields_source_platform_drift_blocks_creation_before_dispatch(tmp_path, stage):
    task, source, shown = _created_leaf_history_case(tmp_path, created_fields=True, prepared_only=True)
    assert task.run("confirm", source, "--confirmation-token", shown["confirmation"]["token"])[0] == 0
    if stage == "readback":
        assert task.run("execute", source)[0] == 0
    task.current_platform = "{55555555-5555-5555-5555-555555555555}"
    code, rejected = task.run("execute" if stage == "prewrite" else "verify", source)
    assert code == 2, rejected
    assert len([call for call in task.calls if call[0].endswith("object.create")]) == int(stage == "readback")


@pytest.mark.parametrize("corruption", ["scalar-type", "derived-value", "missing-field", "class", "metadata", "reference", "null-missing", "read-error"])
def test_created_fields_redo_never_passes_wrong_or_unobserved_restoration(tmp_path, corruption):
    reference = "null" if corruption == "null-missing" else "existing" if corruption == "reference" else None
    task, source, created = _created_leaf_history_case(tmp_path, created_fields=reference is None, reference=reference)
    undo = _created_leaf_history_preview(task, source)
    assert task.run("execute", undo)[0] == 0
    assert task.run("verify", undo)[0] == 0
    redo = _created_leaf_history_preview(task, source, "redo")
    assert task.run("execute", redo)[0] == 0
    row = task.objects[created["id"]]
    if corruption == "scalar-type": row["@Volume"] = True
    elif corruption == "derived-value": row["@IsLoopingInfinite"] = False
    elif corruption == "missing-field": row.pop("@Volume")
    elif corruption == "class": row["classId"] = 999
    elif corruption == "metadata": task.metadata["Volume"]["type"] = "int32"
    elif corruption == "reference": row["@Attenuation"] = None
    elif corruption == "null-missing": row.pop("@Attenuation")
    else:
        original = task.call
        def read_error(uri, args=None, options=None):
            if uri.endswith("object.get") and args.get("from") == {"id": [created["id"]]}:
                raise RuntimeError("fixture history created-field read failed")
            return original(uri, args, options)
        task.call = read_error
    code, verified = task.run("verify", redo)
    assert code == 2 and verified.get("verified") is not True, json.dumps(verified)
    assert len([call for call in task.calls if call[0].endswith("object.create")]) == 1
    assert len([call for call in task.calls if call[0].endswith("undo.redo")]) == 1
    if corruption == "read-error":
        assert "fixture history created-field read failed" in json.dumps(verified)


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("notes", [None, "Explicit creation notes"])
def test_created_leaf_history_restores_exact_guid_and_observed_default_notes(tmp_path, version, notes):
    task, source, created = _created_leaf_history_case(tmp_path, version=version, notes=notes)
    assert created["notes"] == ("" if notes is None else notes)
    for direction in (["undo"] if version == "2022.1" else ["undo", "redo"]):
        tx = _created_leaf_history_preview(task, source, direction)
        code, executed = task.run("execute", tx)
        assert code == 0, executed
        code, verified = task.run("verify", tx)
        assert code == 0 and verified["verified"] is True, json.dumps(verified)
        assert verified["verification_strength"] == "scoped_history_effect_readback"
        assert list(verified)[-1] == "agent_result"
        assert verified["agent_result"]["result"] == {}
        code, repeated = task.run("execute", tx)
        assert code == 2, repeated
    if version != "2022.1":
        assert task.objects[created["id"]] == created
    assert len([row for row in task.calls if row[0] == "ak.wwise.core.undo.undo"]) == 1
    assert len([row for row in task.calls if row[0] == "ak.wwise.core.undo.redo"]) == int(version != "2022.1")


@pytest.mark.parametrize("corruption", ["no-effect", "replacement-at-path", "missing-return", "partial-row", "duplicate", "read-error"])
def test_created_leaf_history_never_treats_incomplete_or_wrong_reads_as_absence(tmp_path, corruption):
    from copy import deepcopy
    task, source, created = _created_leaf_history_case(tmp_path)
    tx = _created_leaf_history_preview(task, source)
    if corruption == "no-effect":
        task.history_effect = False
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    if corruption == "replacement-at-path":
        replacement = {**created, "id": "{77777777-7777-7777-7777-777777777777}"}
        task.objects[replacement["id"]] = replacement
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith("object.get") and args.get("from") in ({"id": [created["id"]]}, {"path": [created["path"]]}):
            if corruption == "missing-return":
                return {}
            if corruption == "partial-row":
                return {"return": [{"id": created["id"]}]}
            if corruption == "duplicate":
                return {"return": [deepcopy(created), deepcopy(created)]}
            if corruption == "read-error":
                raise RuntimeError("object read unavailable")
        return original(uri, args, options)
    task.call = call
    code, verified = task.run("verify", tx)
    assert code == 2 and verified["verified"] is False, json.dumps(verified)
    assert verified["verification_strength"] == "scoped_history_effect_readback"
    assert len([row for row in task.calls if row[0] == "ak.wwise.core.undo.undo"]) == 1
    assert not any(row[0] == "ak.wwise.core.undo.redo" for row in task.calls)


@pytest.mark.parametrize("changed", ["id", "parent", "notes", "path"])
def test_created_leaf_history_redo_requires_original_scoped_state(tmp_path, changed):
    task, source, created = _created_leaf_history_case(tmp_path)
    undo = _created_leaf_history_preview(task, source)
    assert task.run("execute", undo)[0] == 0
    assert task.run("verify", undo)[0] == 0
    redo = _created_leaf_history_preview(task, source, "redo")
    code, executed = task.run("execute", redo)
    assert code == 0, executed
    row = task.objects[created["id"]]
    if changed == "parent":
        row["parent"] = {"id": "{77777777-7777-7777-7777-777777777777}"}
    elif changed == "id":
        del task.objects[created["id"]]
        row["id"] = "{77777777-7777-7777-7777-777777777777}"
        task.objects[row["id"]] = row
    else:
        row[changed] = "unreviewed changed state"
    code, verified = task.run("verify", redo)
    assert code == 2 and verified["verified"] is False, json.dumps(verified)


def test_created_leaf_history_scope_drift_blocks_native_history_before_dispatch(tmp_path):
    task, source, created = _created_leaf_history_case(tmp_path)
    tx = _created_leaf_history_preview(task, source)
    task.objects[created["id"]]["notes"] = "later edit"
    code, executed = task.run("execute", tx)
    assert code == 2, executed
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in task.calls)



def test_created_leaf_history_uses_durable_actual_default_without_user_notes(tmp_path):
    task, source, created = _created_leaf_history_case(tmp_path, notes=None, source_notes="native-default")
    assert created["notes"] == "Native observed default"
    undo = _created_leaf_history_preview(task, source)
    assert task.run("execute", undo)[0] == 0
    assert task.run("verify", undo)[0] == 0
    redo = _created_leaf_history_preview(task, source, "redo")
    assert task.run("execute", redo)[0] == 0
    code, verified = task.run("verify", redo)
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[created["id"]]["notes"] == "Native observed default"


def test_created_leaf_history_requires_source_notes_observation_even_when_source_did_not_request_notes(tmp_path):
    task, source, _created = _created_leaf_history_case(tmp_path, notes=None, source_notes="missing")
    code, phase = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, phase
    code, rejected = task.run("draft-declare-core-plan", phase["draft"]["draft_id"],
        "--task-authority", phase["task_authority"], "--expected-revision", str(phase["draft"]["revision"]),
        "--value", "history_scope", "latest_project_history", "--value", "expectation_receipt", source)
    assert code == 2 and "actual notes are incomplete" in json.dumps(rejected), rejected
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in task.calls)


@pytest.mark.parametrize('reference', ['existing', 'null'])
def test_created_fields_combined_receipt_review_keeps_complete_root_fields_and_exact_proof(tmp_path, reference):
    task, source, _created = _created_leaf_history_case(tmp_path, created_fields=True, reference=reference)
    tx = _created_leaf_history_preview(task, source)
    code, compact = task.run('transaction-show', tx, '--summary-only')
    assert code == 0, compact
    observations = compact['preview_summary']['history_action']['expected_observations']
    presence, = observations
    assert presence['kind'] == 'creation_presence' and presence['before'] is False and presence['after'] is True
    assert {row['field'] for row in presence['fields']} == {'IsLoopingEnabled', 'IsLoopingInfinite', 'Volume', 'Attenuation'}
    assert all(row['metadata_bound'] is True and 'field_info' not in row for row in presence['fields'])
    code, full = task.run('transaction-show', tx)
    assert code == 0, full
    sealed = full['artifact']['prepared_operation']['pre_state']['history_binding']['observations']
    field_rows = [row for row in sealed if row['kind'] == 'creation_field']
    assert len(field_rows) == 4 and all('raw' in row['field_info'] for row in field_rows)
    assert all(row['object_id'] == presence['object']['id'] for row in field_rows)
    compact_fields = [{key: value for key, value in row.items() if key not in {'kind', 'object_id', 'before', 'after', 'field_info'}}
        for row in field_rows]
    assert presence['fields'] == [{**row, 'metadata_bound': True} for row in compact_fields]
    assert task.run('execute', tx)[0] == 0
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified
    assert list(verified)[-1] == 'agent_result' and verified['agent_result']['result'] == {}


@pytest.mark.parametrize('corruption', ['missing', 'duplicate', 'other-root'])
def test_created_fields_compact_review_cannot_weaken_immutable_field_proof(tmp_path, corruption):
    from copy import deepcopy
    task, source, _created = _created_leaf_history_case(tmp_path, created_fields=True, reference='existing')
    tx = _created_leaf_history_preview(task, source)
    path = tmp_path / 'state' / 'transactions' / tx / 'preview.json'
    document = json.loads(path.read_text())
    observations = document['artifact']['prepared_operation']['pre_state']['history_binding']['observations']
    field = next(item for item in observations if item['kind'] == 'creation_field')
    if corruption == 'missing': observations.remove(field)
    elif corruption == 'duplicate': observations.append(deepcopy(field))
    else: field['object_id'] = '{33333333-3333-3333-3333-333333333333}'
    path.write_text(json.dumps(document), encoding='utf-8')
    code, rejected = task.run('execute', tx)
    assert code == 2, rejected
    assert not any(call[0].startswith('ak.wwise.core.undo.') for call in task.calls)


def _created_history_reference_draft(task, source):
    code, started = task.run('draft-start', 'ak.wwise.core.undo.undo')
    assert code == 0, started
    draft, authority = started['draft']['draft_id'], started['task_authority']
    code, declared = task.run('draft-declare-core-plan', draft, '--task-authority', authority,
        '--expected-revision', str(started['draft']['revision']),
        '--value', 'history_scope', 'latest_project_history', '--value', 'expectation_receipt', source)
    assert code == 0, declared
    return draft, authority, declared['draft']['revision']


@pytest.mark.parametrize('corruption', ['binding-hash', 'source-artifact', 'source-tail', 'source-sequence', 'source-context', 'draft-context', 'journal', 'cross-store'])
def test_history_draft_reference_cannot_recapture_or_cross_its_original_owner(tmp_path, corruption):
    from copy import deepcopy
    import shutil
    from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
    task, source, _created = _created_leaf_history_case(tmp_path, created_fields=True, reference='existing')
    draft, authority, revision = _created_history_reference_draft(task, source)
    state = tmp_path / 'state'
    path = state / 'operation-drafts-v1' / 'records' / (draft + '.json')
    document = json.loads(path.read_text())
    reference = document['composition']['business_session']['settings']['core_plan']['history_binding']
    assert reference['contract'] == 'waapi-skill.history-draft-reference/v1'
    assert 'observations' not in reference and 'state_dir' not in reference['source_receipt']
    original = deepcopy(reference)
    if corruption == 'cross-store':
        other = tmp_path / 'other-state'
        shutil.copytree(state, other)
        # An otherwise valid copied source receipt must not become this Draft's owner.
        code, rejected = waapi_gateway.execute_gateway(['--state-dir', str(other), 'draft-check', draft,
            '--task-authority', authority, '--expected-revision', str(revision)], env=task.env,
            client_factory=lambda _url: task)
    else:
        if corruption == 'binding-hash': reference['binding_sha256'] = '0' * 64
        elif corruption == 'source-artifact': reference['source_receipt']['artifact_hash'] = '0' * 64
        elif corruption == 'source-tail': reference['source_receipt']['last_event_hash'] = '0' * 64
        elif corruption == 'source-sequence': reference['source_receipt']['event_sequence'] += 1
        elif corruption == 'source-context': reference['source_context_fingerprint'] = '0' * 64
        elif corruption == 'draft-context': reference['draft_context']['wwise_build'] = '2025.1.0.2'
        elif corruption == 'journal':
            events = state / 'transactions' / source / 'events.jsonl'
            events.write_bytes(events.read_bytes() + b'{"event_type":"changed"}\n')
        if corruption != 'journal':
            document.pop('record_digest')
            document['record_digest'] = canonical_sha256({'contract': 'waapi-skill.operation-draft-record-digest/v1', 'record': document})
            path.write_bytes(canonical_json_bytes(document))
        code, rejected = task.run('draft-check', draft, '--task-authority', authority, '--expected-revision', str(revision))
    assert code == 2, rejected
    assert not any(call[0].startswith('ak.wwise.core.undo.') for call in task.calls)
    # No later lookup may silently substitute updated source or current context.
    if corruption == 'cross-store':
        assert json.loads(path.read_text())['composition']['business_session']['settings']['core_plan']['history_binding'] == original


def test_history_request_reference_and_complete_proof_must_name_the_same_source(tmp_path):
    """Two actual Gateway source receipts cannot be mixed under one new hash."""
    from copy import deepcopy
    client, state, _source, _preview, shown, run = _owned_notes_history_case(tmp_path)
    code, full = run('transaction-show', _preview['transaction_id'])
    assert code == 0, full
    artifact = deepcopy(full['artifact'])
    code, started = run('draft-start', 'object.setNotes')
    assert code == 0, started
    draft, authority = started['draft']['draft_id'], started['task_authority']
    code, bound = run('draft-bind-object', draft, '--task-authority', authority,
        '--expected-revision', str(started['draft']['revision']), '--object-id', client.source['id'])
    assert code == 0, bound
    code, declared = run('draft-declare-object-change', draft, '--task-authority', authority,
        '--expected-revision', str(bound['draft']['revision']), '--notes', 'Second owned source')
    assert code == 0, declared
    phase = declared
    for command in ('draft-check', 'preview-from-draft'):
        code, phase = run(command, draft, '--task-authority', authority,
            '--expected-revision', str(phase['draft']['revision']))
        assert code == 0, phase
    second_source = phase['transaction_id']
    code, second_shown = run('transaction-show', second_source)
    assert code == 0, second_shown
    assert run('confirm', second_source, '--confirmation-token', second_shown['confirmation']['token'])[0] == 0
    assert run('execute', second_source)[0] == 0
    assert run('verify', second_source)[0] == 0
    # Capture B's independently valid proof through the same public declaration.
    from types import SimpleNamespace
    draft, authority, revision = _created_history_reference_draft(SimpleNamespace(run=run), second_source)
    for command in ('draft-check', 'preview-from-draft'):
        code, phase = run(command, draft, '--task-authority', authority, '--expected-revision', str(revision))
        assert code == 0, phase
        if 'draft' in phase: revision = phase['draft']['revision']
    code, second_history = run('transaction-show', phase['transaction_id'])
    assert code == 0, second_history
    proof = second_history['artifact']['prepared_operation']['pre_state']['history_binding']
    assert proof['source_receipt']['transaction_id'] == second_source
    artifact['prepared_operation']['pre_state']['history_binding'] = deepcopy(proof)
    artifact['prepared_operation']['verification_plan']['history_binding'] = deepcopy(proof)
    # Storage corruption setup: both source proofs were captured publicly. Even
    # a fresh internally consistent storage hash cannot authorize their mixture.
    store = TransactionStore(state)
    store.create_preview('mixed-history-proof', artifact)
    store.submit_for_confirmation('mixed-history-proof')
    code, mixed = run('transaction-show', 'mixed-history-proof')
    assert code == 0, mixed
    assert run('confirm', 'mixed-history-proof', '--confirmation-token', mixed['confirmation']['token'])[0] == 0
    code, rejected = run('execute', 'mixed-history-proof')
    assert code == 2, rejected
    assert 'History request reference differs from its complete sealed proof' in json.dumps(rejected)
    assert not any(row[0].startswith('ak.wwise.core.undo.') for row in client.calls)


@pytest.mark.parametrize('stage', ['preview', 'execute', 'verify'])
def test_history_original_source_journal_is_revalidated_at_each_durable_phase(tmp_path, stage):
    task, source, _created = _created_leaf_history_case(tmp_path, created_fields=True)
    draft, authority, revision = _created_history_reference_draft(task, source)
    code, checked = task.run('draft-check', draft, '--task-authority', authority, '--expected-revision', str(revision))
    assert code == 0, checked
    def corrupt_source():
        events = tmp_path / 'state' / 'transactions' / source / 'events.jsonl'
        events.write_bytes(events.read_bytes() + b'{"event_type":"unsealed-later-source-event"}\n')
    if stage == 'preview':
        corrupt_source()
        code, rejected = task.run('preview-from-draft', draft, '--task-authority', authority,
            '--expected-revision', str(checked['draft']['revision']))
    else:
        code, preview = task.run(*checked['next_command']['gateway_argv'])
        assert code == 0, preview
        tx = preview['transaction_id']
        code, shown = task.run('transaction-show', tx)
        assert code == 0, shown
        assert task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
        if stage == 'execute':
            corrupt_source()
            code, rejected = task.run('execute', tx)
        else:
            assert task.run('execute', tx)[0] == 0
            corrupt_source()
            code, rejected = task.run('verify', tx)
    assert code == 2 and rejected.get('verified') is not True, rejected
    assert len([call for call in task.calls if call[0].startswith('ak.wwise.core.undo.')]) == (1 if stage == 'verify' else 0)


def _literal_2022_null_creation_metadata():
    """Failed native2022 Sound condition/default grammar; display data omitted in fixture."""
    override = {'type': 'override', 'action': 'Enable', 'context': 'Self', 'property': 'OverridePositioning'}
    return {
        'IsLoopingEnabled': {'name': 'IsLoopingEnabled', 'type': 'bool', 'default': False},
        'IsLoopingInfinite': {'name': 'IsLoopingInfinite', 'type': 'bool', 'default': True,
            'dependencies': [{'type': 'property', 'action': 'Enable', 'context': 'Self', 'property': 'IsLoopingEnabled',
                'conditions': [{'restriction': {'type': 'enum', 'values': [{'displayName': 'True', 'value': True}]}}]}]},
        'Volume': {'name': 'Volume', 'type': 'Real64', 'default': 0.0, 'restriction': {'type': 'range', 'min': -200.0, 'max': 200.0}},
        'Attenuation': {'name': 'Attenuation', 'type': '', 'default': None,
            'restriction': {'type': 'reference', 'restrictions': [{'type': ['Attenuation'], 'sharedOnlyTypes': []}]},
            'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': True},
            'dependencies': [{'type': 'property', 'action': 'Enable', 'context': 'Self', 'property': 'ListenerRelativeRouting',
                'conditions': [{'restriction': {'type': 'enum', 'values': [{'displayName': 'True', 'value': True}]}}]}, override]},
        'ListenerRelativeRouting': {'name': 'ListenerRelativeRouting', 'type': 'bool', 'default': True, 'dependencies': [override]},
        'OverridePositioning': {'name': 'OverridePositioning', 'type': 'bool', 'default': False, 'dependencies': [override]},
    }


def test_2022_new_sound_null_intent_uses_default_without_losing_source_or_history(tmp_path):
    metadata = _literal_2022_null_creation_metadata()
    task, source, shown = _created_leaf_history_case(tmp_path, version='2022.1', reference='null', created_fields=True,
        prepared_only=True, source_class_metadata=metadata, sound_class_id=65552)
    artifact = shown['artifact']; native = artifact['prepared_operation']['dispatch']['args']
    assert artifact['request']['arguments']['references'] == [{'name': 'Attenuation', 'target': None}]
    assert '@Attenuation' not in native
    assert native['@OverridePositioning'] is True and native['@IsLoopingEnabled'] is True and native['@IsLoopingInfinite'] is True
    assert native['@Volume'] == -6 and native['onNameConflict'] == 'fail'
    spec = artifact['prepared_operation']['pre_state']['object_create_nodes'][0]
    assert spec['references'] == [{'name': 'Attenuation', 'target_id': None}]
    assert spec['native_default_reference_omissions'] == ['Attenuation']
    code, verified = task.finish(source, shown)
    assert code == 0 and verified['verified'] is True, verified
    created = next(row for row in task.objects.values() if row['name'] == 'Rain')
    assert '@Attenuation' in created and created['@Attenuation'] is None and created['@OverridePositioning'] is True
    assert len([row for row in task.calls if row[0].endswith('object.create')]) == 1
    tx = _created_leaf_history_preview(task, source)
    code, history = task.run('transaction-show', tx)
    assert code == 0, history
    fields = history['artifact']['prepared_operation']['pre_state']['history_binding']['observations']
    null_field = next(row for row in fields if row.get('kind') == 'creation_field' and row.get('field') == 'Attenuation')
    assert null_field['value'] is None and null_field['field_info']['default'] is None
    presence = next(row for row in fields if row['kind'] == 'creation_presence')
    assert presence['platform'] == artifact['prepared_operation']['pre_state']['field_read_platform']['platform_id']


def test_2022_new_nested_sound_null_uses_absent_root_hierarchy_and_actual_child(tmp_path):
    task, source, shown = _created_leaf_history_case(tmp_path, version='2022.1', reference='null', created_fields=True,
        prepared_only=True, source_class_metadata=_literal_2022_null_creation_metadata(), sound_class_id=65552, nested=True)
    prepared = shown['artifact']['prepared_operation']
    assert prepared['dispatch']['args']['type'] == 'ActorMixer'
    child = prepared['dispatch']['args']['children'][0]
    assert child['type'] == 'Sound' and '@Attenuation' not in child and child['@OverridePositioning'] is True
    assert shown['artifact']['request']['arguments']['children'][0]['references'] == [{'name': 'Attenuation', 'target': None}]
    spec = next(row for row in prepared['pre_state']['object_create_nodes'] if row['canonical_type'] == 'Sound')
    assert spec['native_default_reference_omissions'] == ['Attenuation']
    assert prepared['pre_state']['object_graph_guard']['path_snapshots'][0]['rows'] == []
    code, verified = task.finish(source, shown)
    assert code == 0 and verified['verified'] is True, verified
    container = next(row for row in task.objects.values() if row['name'] == 'Container')
    created = next(row for row in task.objects.values() if row['name'] == 'Rain')
    assert created['parent']['id'] == container['id'] and created['@Attenuation'] is None
    assert created['classId'] == 65552 and len([row for row in task.calls if row[0].endswith('object.create')]) == 1


@pytest.mark.parametrize('default', ['missing', 'non-null'])
def test_2022_new_sound_null_without_actual_null_class_default_cannot_dispatch(tmp_path, default):
    metadata = _literal_2022_null_creation_metadata()
    if default == 'missing': metadata['Attenuation'].pop('default')
    else: metadata['Attenuation']['default'] = '{33333333-3333-3333-3333-333333333333}'
    task, _, _ = _created_leaf_history_case(tmp_path, version='2022.1', reference='null', created_fields=True,
        declaration_only=True, source_class_metadata=metadata, sound_class_id=65552)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'NEW_OBJECT_NULL_DEFAULT_UNPROVEN', rejected
    assert not any(row[0].endswith('object.create') for row in task.calls)


@pytest.mark.parametrize('corruption', ['null-missing', 'inherited-reference', 'wrong-class', 'controller-false', 'post-metadata'])
def test_2022_omitted_native_null_still_requires_actual_present_null(tmp_path, corruption):
    task, source, shown = _created_leaf_history_case(tmp_path, version='2022.1', reference='null', created_fields=True,
        prepared_only=True, source_class_metadata=_literal_2022_null_creation_metadata(), sound_class_id=65552)
    assert task.run('confirm', source, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, executed = task.run('execute', source)
    assert code == 0 and executed['state'] == 'executed_unverified', executed
    created = next(row for row in task.objects.values() if row['name'] == 'Rain')
    if corruption == 'null-missing': del created['@Attenuation']
    elif corruption == 'inherited-reference': created['@Attenuation'] = {'id': '{33333333-3333-3333-3333-333333333333}'}
    elif corruption == 'wrong-class': created['classId'] = 2
    elif corruption == 'controller-false': created['@OverridePositioning'] = False
    else: task.metadata['Attenuation']['default'] = '{33333333-3333-3333-3333-333333333333}'
    code, rejected = task.run('verify', source)
    assert code == 2 and rejected.get('verified') is not True, rejected
    assert len([row for row in task.calls if row[0].endswith('object.create')]) == 1


@pytest.mark.parametrize('fault', ['default-presence', 'default-target', 'controller', 'dependency', 'collision'])
def test_2022_omission_default_conditions_and_absence_are_fresh_before_execute(tmp_path, fault):
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task, source, shown = _created_leaf_history_case(tmp_path, version='2022.1', reference='null', created_fields=True,
        prepared_only=True, source_class_metadata=_literal_2022_null_creation_metadata(), sound_class_id=65552)
    assert task.run('confirm', source, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    if fault == 'default-presence': task.metadata['Attenuation'].pop('default')
    elif fault == 'default-target': task.metadata['Attenuation']['default'] = '{33333333-3333-3333-3333-333333333333}'
    elif fault == 'controller': task.metadata['ListenerRelativeRouting']['default'] = False
    elif fault == 'dependency': task.metadata['Attenuation']['dependencies'][0]['context'] = 'Parent'
    else:
        row = deepcopy(task.objects[SECOND])
        row.update(id='{99999999-9999-9999-9999-999999999999}', type='Sound', name='Rain', parent={'id': SECOND},
            path=task.objects[SECOND]['path'] + '\\Rain', classId=65552)
        task.objects[row['id']] = row
    code, rejected = task.run('execute', source)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert not any(row[0].endswith('object.create') for row in task.calls)


@pytest.mark.parametrize('version,sound_class_id,reference', [
    ('2021.1', 65552, 'null'), ('2023.1', 65552, 'null'), ('2024.1', 65552, 'null'), ('2025.1', 65552, 'null'),
    ('2022.1', 2, 'null'), ('2022.1', 65552, 'existing'),
])
def test_null_constructor_compatibility_does_not_change_other_lanes_or_existing_targets(tmp_path, version, sound_class_id, reference):
    # One literal2022 condition fixture checks scope isolation, not metadata/native credit in other versions.
    task, source, shown = _created_leaf_history_case(tmp_path, version=version, reference=reference, created_fields=True,
        prepared_only=True, source_class_metadata=_literal_2022_null_creation_metadata(), sound_class_id=sound_class_id)
    native = shown['artifact']['prepared_operation']['dispatch']['args']
    assert '@Attenuation' in native and native['@Attenuation'] == (None if reference == 'null' else '{33333333-3333-3333-3333-333333333333}')
    assert all('native_default_reference_omissions' not in row for row in shown['artifact']['prepared_operation']['pre_state']['object_create_nodes'])
    assert not any(row[0].endswith('object.create') for row in task.calls)


def test_2022_null_default_cannot_waive_incompatible_creation_controller(tmp_path):
    metadata = _literal_2022_null_creation_metadata()
    metadata['ListenerRelativeRouting']['default'] = False
    task, _, _ = _created_leaf_history_case(tmp_path, version='2022.1', reference='null', created_fields=True,
        declaration_only=True, source_class_metadata=metadata, sound_class_id=65552)
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'REFERENCE_ACTIVATION_REQUIRED', rejected
    assert not any(row[0].endswith('object.create') for row in task.calls)


@pytest.mark.parametrize('mode', ['merge', 'rename'])
def test_2022_null_omission_never_changes_native_assignment_for_other_conflict_modes(tmp_path, mode):
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    metadata = _literal_2022_null_creation_metadata()
    task, _, _ = _created_leaf_history_case(tmp_path, version='2022.1', reference='null', created_fields=True,
        declaration_only=True, source_class_metadata=metadata, sound_class_id=65552)
    if mode == 'merge':
        identity = '{99999999-9999-9999-9999-999999999999}'
        task.objects[identity] = {'id': identity, 'name': 'Rain', 'type': 'Sound', 'classId': 65552,
            'path': task.objects[SECOND]['path'] + '\\Rain', 'parent': {'id': SECOND}, 'notes': 'Keep existing',
            **{'@' + name: deepcopy(info['default']) for name, info in metadata.items() if 'default' in info}}
        task.objects[identity]['@Attenuation'] = {'id': '{33333333-3333-3333-3333-333333333333}'}
    code, configured = task.step('draft-business-configure', '--name-conflict', mode)
    assert code == 0, configured
    source, shown = task.preview()
    prepared = shown['artifact']['prepared_operation']; native = prepared['dispatch']['args']
    assert native['onNameConflict'] == mode and '@Attenuation' in native and native['@Attenuation'] is None
    assert all('native_default_reference_omissions' not in row for row in prepared['pre_state']['object_create_nodes'])
    if mode == 'merge': assert prepared['pre_state']['object_create_nodes'][0]['preexisting_id'] == identity
    assert not any(row[0].endswith('object.create') for row in task.calls)
