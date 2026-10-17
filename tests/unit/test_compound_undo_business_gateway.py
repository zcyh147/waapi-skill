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


def _preview_cancellation_case(tmp_path, client, *, version, cancellation, declaration_error=None, property_child=False, duplicate_property=False, parent_check_error=None, second_platform=None):
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
    child_specs = (("object.setProperty", "--business-value", "2") if property_child else
                   ("object.setNotes", "--notes", "after"),
                   ("object.setProperty", "--business-value", "3") if duplicate_property else ("object.setName", "--new-name", "Renamed"))
    for child_index, (operation, flag, value) in enumerate(child_specs):
        phase = run("draft-start-undo-child", draft, "--task-authority", authority,
                    "--expected-revision", revision, "--operation", operation)
        child, child_authority = phase["draft"]["draft_id"], phase["task_authority"]
        phase = run("draft-bind-object", child, "--task-authority", child_authority,
                    "--expected-revision", str(phase["draft"]["revision"]), "--object-id", OBJECT_GUID)
        if operation == "object.setProperty":
            object_handle = phase["bound_object"]["handle"]
            phase = run("draft-discover-fields", child, "--task-authority", child_authority,
                "--expected-revision", str(phase["draft"]["revision"]), "--object-handle", object_handle,
                "--meaning", "volume",
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
