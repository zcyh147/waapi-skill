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
    def state_bytes():
        root = state_dir / "transactions"
        return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
                for path in root.rglob("*")}
    def reject_without_parent_artifact(arguments, expected):
        before, calls_before = state_bytes(), len(client.calls)
        parent_path = state_dir / "operation-drafts-v1" / "records" / (draft + ".json")
        parent_before = json.loads(parent_path.read_text())
        code, rejected = waapi_gateway.execute_gateway(["--state-dir", str(state_dir), *arguments],
            env=env, client_factory=lambda _url: client)
        assert code == 2 and expected in json.dumps(rejected), rejected
        assert not rejected.get("transaction_id"), rejected
        assert state_bytes() == before  # every existing immutable child artifact/journal byte remains exact
        parent_after = json.loads(parent_path.read_text())
        unchanged = lambda record: {key: value for key, value in record.items()
            if key not in {"audit", "record_digest", "connection_binding"}}
        assert unchanged(parent_after) == unchanged(parent_before)
        assert parent_after["connection_binding"]["configuration"] == parent_before["connection_binding"]["configuration"]
        if "live" in parent_before["connection_binding"]:
            assert parent_after["connection_binding"]["live"] == parent_before["connection_binding"]["live"]
        else:
            live = parent_after["connection_binding"]["live"]
            assert live["project_id"] == "{33333333-3333-3333-3333-333333333333}"
            assert live["version"]["year"] == int(version[:4]) and live["version"]["major"] == 1
        # First live attestation/rejection audit may be recorded; no parent Preview/seal/reservation is created.
        assert not any(uri.startswith("ak.wwise.core.undo.") or uri.endswith(("object.setNotes", "object.setName", "object.setProperty", "object.setReference"))
                       for uri, _args, _options in client.calls[calls_before:])
        return rejected
    if declaration_error:
        rejected = reject_without_parent_artifact(declaration, declaration_error)
        return state_dir, env, rejected
    phase = run(*declaration)
    check = ("draft-check", draft, "--task-authority", authority, "--expected-revision", str(phase["draft"]["revision"]))
    if parent_check_error:
        rejected = reject_without_parent_artifact(check, parent_check_error)
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
    assert not any(uri.startswith("ak.wwise.core.undo.") for uri, _args, _options in client.calls)
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
            return {**result, "displayTitle": "SampleProject", "isDirty": False,
                    "currentLanguageId": "{66666666-6666-6666-6666-666666666666}",
                    "referenceLanguageId": "{66666666-6666-6666-6666-666666666666}",
                    "languages": [{"id": "{66666666-6666-6666-6666-666666666666}", "name": "English(US)", "shortId": 1}],
                    "defaultConversion": {"id": "{77777777-7777-7777-7777-777777777777}", "name": "Default"},
                    "directories": {name: "/project/" + name for name in
                        ("root", "cache", "originals", "soundBankOutputRoot", "commands", "properties")},
                    "currentPlatformId": client.current_platform,
                    "platforms": [{"id": object_id, "name": name, "baseName": name,
                        "baseDisplayName": name, "soundBankPath": "/project/SoundBanks/" + name,
                        "copiedMediaPath": "/project/Media/" + name}
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
        assert not any(uri.startswith("ak.wwise.core.undo.") for uri, _args, _options in client.calls)
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
    assert not any(uri.startswith("ak.wwise.core.undo.") for uri, _args, _options in client.calls)
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
    assert not any(uri.startswith("ak.wwise.core.undo.") for uri, _args, _options in client.calls)
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
    assert not any(uri.startswith("ak.wwise.core.undo.") for uri, _args, _options in client.calls)
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
    assert not any(uri.startswith("ak.wwise.core.undo.") for uri, _args, _options in client.calls)
    assert not any(row[0].startswith("ak.wwise.core.undo.") for row in client.calls)


@pytest.mark.parametrize("platform", ("Windows", "{44444444-4444-4444-4444-444444444444}".lower()))
def test_compound_alias_of_current_unlinked_platform_still_overlaps(tmp_path, platform):
    client = _property_cancellation_client("2025.1")
    client.linked = False
    state_dir, _env, _rejected = _preview_cancellation_case(tmp_path, client, version="2025.1",
        cancellation="undo-changes", property_child=True, duplicate_property=True, second_platform=platform,
        parent_check_error="UNDO_GROUP_OVERLAPPING_OUTCOME")
    assert not any(uri.startswith("ak.wwise.core.undo.") for uri, _args, _options in client.calls)
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
    assert not any(uri.startswith("ak.wwise.core.undo.") for uri, _args, _options in client.calls)
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


def _owned_notes_history_case(tmp_path, *, version="2025.1", direction="undo", effect=True, source_operation="object.setNotes", initial_notes="before history edit", verify_source=True, history_values=None, declaration_error=False, confirm_history=True, history_policy=None, compound_ancestor=False, compound_property=False, omitted_property_name=False, reference_clear=False, reference_platform="{55555555-5555-5555-5555-555555555555}", omitted_reference_metadata=False, source_prepared_only=False, compound_reference=False, platform_inventory=True, property_platform="{55555555-5555-5555-5555-555555555555}", source_platform_observer_error=False, inherited_reference=False, reference_extensions=False):
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
                for row in result["return"]:
                    if row["id"] == self.source["id"] and "Attenuation" in options.get("return", []) and "@Attenuation" in row:
                        row["Attenuation"] = ({"id": "{77777777-7777-7777-7777-777777777777}"}
                            if inherited_reference else row.get("@Attenuation"))
                return result
            if uri == "ak.wwise.core.object.getTypes" and reference_case:
                self.calls.append((uri, args, options))
                return {"return": [{"name": "Sound", "classId": 65552, "type": "WObject"},
                    {"name": "Attenuation", "classId": 2686992, "type": "WObject"}]}
            if uri == "ak.wwise.core.object.setReference":
                self.calls.append((uri, args, options))
                self.source["@Attenuation"] = (None if not reference_extensions else {
                    "id": args["value"], "name": "", "future": {"enabled": False, "count": 0}}
                    ) if args["value"] == "{00000000-0000-0000-0000-000000000000}" else {"id": args["value"]}
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
        if reference_extensions and reference_clear:
            client.source["@Attenuation"].update(name="Stored target", future={"enabled": False, "count": 0})
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


@pytest.mark.parametrize("direction", ["undo", "redo"])
@pytest.mark.parametrize("effect", [True, False])
@pytest.mark.parametrize("extensions", [False, True])
def test_standalone_history_clear_receipt_observes_stored_state_despite_inheritance(tmp_path, direction, effect, extensions):
    client, state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path,
        source_operation="object.setReference", reference_clear=True, inherited_reference=True,
        direction=direction, effect=effect, reference_extensions=extensions)
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["prepared_operation"]["pre_state"]["history_binding"]
    observation = binding["observations"][0]
    assert observation["reference_observation"]["value_source"] == "local_stored"
    assert observation["before"] == client.parent["id"] and observation["after"] is None
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    assert code == (0 if effect else 2) and verified["verified"] is effect, verified
    events = TransactionStore(state).read_events(preview["transaction_id"])
    readbacks = next(event["details"]["verification"]["readbacks"] for event in reversed(events)
        if event["event_type"] == "verification_recorded")
    assert any(read["uri"] == "ak.wwise.core.object.get" and "@Attenuation" in read["options"].get("return", []) for read in readbacks)
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
@pytest.mark.parametrize("damage", ["wrong-guid", "missing", "path", "malformed-name", "boolean", "read-error", "identity", "metadata"])
def test_standalone_history_reference_wrong_or_missing_observation_never_proves_effect(tmp_path, stage, damage):
    client, state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, source_operation="object.setReference")
    if stage == "readback":
        code, executed = run("execute", preview["transaction_id"])
        assert code == 0, executed
    value = {"wrong-guid": {"id": "{77777777-7777-7777-7777-777777777777}"}, "path": r"\Attenuations\Destination",
        "malformed-name": {"id": client.parent["id"], "name": False}, "boolean": True}.get(damage)
    if damage in {"wrong-guid", "path", "malformed-name", "boolean"}:
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
    source_class_metadata=None, sound_class_id=2, nested=False, declaration_only=False, compound=False, setup=None):
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, SECOND, CHILD, ROOT
    task = OwnedGraphTask(tmp_path, version, "object.create")
    original_create = task._create
    def create_with_actual_class(node, parent, **kwargs):
        result = original_create(node, parent, **kwargs)
        row = task.objects[result['id']]
        row['classId'] = next(info['classId'] for info in task.types if info['name'] == row['type'])
        return result
    task._create = create_with_actual_class
    if compound:
        _start_parent_owned_graph_child(task, "object.create")
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
    if setup:
        setup(task)
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
    task.created_parent_handle = parent
    if declaration_only:
        return task, None, None
    if compound:
        assert task.step("draft-check")[0] == 0
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
    platform="{44444444-4444-4444-4444-444444444444}", prepared_only=False, postread_error=False, compound=False):
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, CHILD, ROOT

    task = OwnedGraphTask(tmp_path, version, "object.set")
    if compound:
        _start_parent_owned_graph_child(task, "object.set")
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
    if compound:
        assert task.step("draft-check")[0] == 0
        return task, None, before, after
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
    platform="{44444444-4444-4444-4444-444444444444}", prepared_only=False, platform_inventory=True, target_read_failure=None, compound=False, opaque_members=False):
    from copy import deepcopy
    from tests.unit.test_list_merge_existing_conditions_gateway import list_task
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT, CHILD
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT

    task, _ = list_task(tmp_path, version=version, operation=operation)
    if compound:
        _start_parent_owned_graph_child(task, operation)
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
        if opaque_members:
            for identity in (ROOT, CHILD):
                task.objects[identity]['path'] = '\\PluginInnerObject\\' + identity
                task.objects[identity]['owner'] = {'id': FIRST, 'name': task.objects[FIRST]['name']}
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
    if compound:
        assert task.step("draft-check")[0] == 0
        return task, None, before, after, writes
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

def _collect_history_pages(run, command, client):
    from copy import deepcopy
    from wwise_waapi.canonical import canonical_sha256
    calls = deepcopy(client.calls)
    entries, pages, offset = [], [], 0
    for _ in range(1000):
        code, payload = run(*command["gateway_argv"])
        assert code == 0, payload
        assert "confirmation" not in payload and "authorization" not in payload
        assert len(json.dumps(payload, ensure_ascii=False, indent=2).encode()) <= 32768
        page = payload["history_view"]
        assert page["mutation_authority"] is False and page["offset"] == offset and len(page["entries"]) <= 64
        if pages:
            assert page["scope"] == pages[0]["scope"] and page["value_sha256"] == pages[0]["value_sha256"]
        pages.append(page)
        entries.extend(page["entries"])
        offset += len(page["entries"])
        if page["complete"]:
            assert page["remaining_entries"] == 0 and page["next_page"] is None and "next_command" not in payload
            break
        command = payload["next_command"]
        assert command["gateway_argv"][0] == "transaction-show" and "--history-view" in command["gateway_argv"]
        assert "--outcome-page" in command["gateway_argv"]
    else:
        pytest.fail("History page chain did not terminate")
    root = None
    for row in entries:
        parts = [part.replace("~1", "/").replace("~0", "~") for part in row["pointer"].split("/")[1:]]
        parent = root
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = (int(parts[-1]) if isinstance(parent, list) else parts[-1]) if parts else None
        if row["kind"] == "object": value = {}
        elif row["kind"] == "array": value = [None] * row["length"]
        elif row["kind"] == "string-fragment":
            previous = parent[key] if row["offset"] else ""
            assert len(previous) == row["offset"]
            value = previous + row["value"]
        else: value = row["value"]
        if parts: parent[key] = value
        else: root = value
    assert canonical_sha256(root) == pages[0]["value_sha256"]
    assert client.calls == calls
    return root, pages


def test_large_real_notes_history_review_and_verification_are_losslessly_pageable(tmp_path, monkeypatch):
    from copy import deepcopy
    protected = []
    original = waapi_gateway.project_successful_transaction_verify_payload
    def protect(payload, **kwargs):
        before = deepcopy(payload["agent_result"])
        encoded = json.dumps(before, ensure_ascii=False, separators=(",", ":")).encode()
        result = original(payload, **kwargs)
        assert result["agent_result"] == before
        assert json.dumps(result["agent_result"], ensure_ascii=False, separators=(",", ":")).encode() == encoded
        assert list(result)[-1] == "agent_result"
        protected.append(True)
        return result
    monkeypatch.setattr(waapi_gateway, "project_successful_transaction_verify_payload", protect)
    client, state, source, preview, shown, run = _owned_notes_history_case(tmp_path,
        initial_notes="Original multilingual notes Ω/雪\"\n" * 600, confirm_history=False)
    tx = preview["transaction_id"]
    notice = shown["preview_summary"]["history_action"]
    assert notice["observations_complete"] is False and notice["observation_count"] == 1
    expectation, pages = _collect_history_pages(run, notice["detail"], client)
    assert len(pages) > 1 and any(entry["kind"] == "string-fragment" for page in pages for entry in page["entries"])
    code, full = run("transaction-show", tx)
    assert code == 0, full
    assert expectation == full["artifact"]["prepared_operation"]["pre_state"]["history_binding"]
    assert expectation["observations"][0]["before"] == client.history_before["notes"]
    assert expectation["observations"][0]["after"] == "after history edit"
    assert expectation["source_receipt"]["transaction_id"] == source["transaction_id"]
    assert run(*shown["next_command"]["gateway_argv"])[0] == 0
    assert run("execute", tx)[0] == 0
    code, verified = run("verify", tx)
    assert code == 0 and verified["verified"] is True, verified
    agent = deepcopy(verified["agent_result"])
    observed, actual_pages = _collect_history_pages(run, verified["verification"]["history_detail"], client)
    code, full = run("transaction-show", tx)
    event, = [row for row in full["events"] if row["event_type"] == "verification_recorded"]
    assert observed == event["details"]["verification"]
    assert actual_pages[0]["scope"]["verification_event_hash"] == event["event_hash"]
    assert verified["agent_result"] == agent and list(verified)[-1] == "agent_result"
    assert client.source["notes"] == client.history_before["notes"]



def test_history_pages_reject_cross_view_cursor_artifact_event_and_store_tamper(tmp_path):
    from copy import deepcopy
    import shutil
    from tests.unit.test_remaining_core_business_gateway import _env
    client, state, _source, preview, shown, run = _owned_notes_history_case(tmp_path,
        initial_notes="Owned notes Ω/雪\n" * 1400)
    tx = preview["transaction_id"]
    first_command = shown["preview_summary"]["history_action"]["detail"]["gateway_argv"]
    code, first = run(*first_command)
    assert code == 0 and first["history_view"]["next_page"], first
    next_command = first["next_command"]["gateway_argv"]
    before_calls = deepcopy(client.calls)
    wrong_cursor = next_command.copy()
    wrong_cursor[-1] = wrong_cursor[-1][:-1] + ("0" if wrong_cursor[-1][-1] != "0" else "1")
    wrong_artifact = next_command.copy()
    wrong_artifact[wrong_artifact.index("--outcome-artifact-hash") + 1] = "0" * 64
    for command in (wrong_cursor, wrong_artifact, [*first_command, "--outcome-event-hash", "0" * 64]):
        assert run(*command)[0] == 2
    assert client.calls == before_calls
    assert run("execute", tx)[0] == 0
    code, verified = run("verify", tx)
    assert code == 0, verified
    actual_command = verified["verification"]["history_detail"]["gateway_argv"]
    code, full = run("transaction-show", tx)
    assert code == 0, full
    wrong_type_event = next(row["event_hash"] for row in full["events"] if row["event_type"] == "execution_completed")
    for event in (wrong_type_event, "0" * 64):
        command = actual_command.copy()
        command[command.index("--outcome-event-hash") + 1] = event
        assert run(*command)[0] == 2
    assert run(*actual_command, "--outcome-page", first["history_view"]["next_page"])[0] == 2
    assert run(*actual_command[:-2])[0] == 2  # No silently selected latest event.
    other = tmp_path / "copied-state"
    shutil.copytree(state, other)
    code, rejected = waapi_gateway.execute_gateway(["--state-dir", str(other), *next_command], env=_env(tmp_path),
        client_factory=lambda _url: pytest.fail("Offline page must not connect"))
    assert code == 2 and "store" in rejected["message"].casefold(), rejected


def test_history_page_reads_sealed_expectation_without_recapturing_source_journal(tmp_path):
    client, state, source, _preview, shown, run = _owned_notes_history_case(tmp_path,
        initial_notes="Retained exact source value " * 900, confirm_history=False)
    source_journal = state / "transactions" / source["transaction_id"] / "events.jsonl"
    source_journal.write_bytes(source_journal.read_bytes() + b'{"unsealed_source_change":true}\n')
    value, _pages = _collect_history_pages(run, shown["preview_summary"]["history_action"]["detail"], client)
    assert value["observations"][0]["before"] == client.history_before["notes"]


def test_history_page_zero_observations_is_complete_and_strictly_read_only(tmp_path):
    client, _state, preview, _shown, run = _latest_history_without_owned_receipt(tmp_path)
    calls = list(client.calls)
    code, page = run("transaction-show", preview["transaction_id"], "--history-view", "expectation",
        "--outcome-artifact-hash", preview["artifact_hash"])
    assert code == 0, page
    assert page["history_view"]["total_count"] == 0 and page["history_view"]["complete"] is True
    assert page["history_view"]["next_page"] is None and "next_command" not in page
    assert "confirmation" not in page and client.calls == calls

    assert run(*_shown["next_command"]["gateway_argv"])[0] == 0
    assert run("execute", preview["transaction_id"])[0] == 0
    code, weak = run("verify", preview["transaction_id"])
    assert code == 0 and weak["verified"] is False and weak["result_schema_checked"] is True, weak
    code, full = run("transaction-show", preview["transaction_id"])
    assert code == 0, full
    event, = [row for row in full["events"] if row["event_type"] == "verification_recorded"]
    calls = list(client.calls)
    code, page = run("transaction-show", preview["transaction_id"], "--history-view", "verification",
        "--outcome-artifact-hash", preview["artifact_hash"], "--outcome-event-hash", event["event_hash"])
    assert code == 0 and page["history_view"]["mutation_authority"] is False, page
    assert client.calls == calls and "confirmation" not in page


def test_history_page_cli_discloses_fixed_views_and_generated_hash_options(capsys):
    with pytest.raises(SystemExit) as outcome:
        waapi_gateway.execute_gateway(["transaction-show", "--help"])
    assert outcome.value.code == 0
    text = capsys.readouterr().out
    assert "--history-view {expectation,verification}" in text
    assert "--outcome-artifact-hash" in text and "--outcome-event-hash" in text and "--outcome-page" in text


@pytest.mark.parametrize('read_error', [False, True])
def test_history_verification_page_preserves_failed_or_incomplete_recorded_outcome(tmp_path, read_error):
    client, _state, _source, preview, _shown, run = _owned_notes_history_case(tmp_path, effect=False)
    tx = preview['transaction_id']
    assert run('execute', tx)[0] == 0
    if read_error:
        original = client.call
        def unavailable(uri, args=None, options=None):
            if uri.endswith('object.get') and 'notes' in (options or {}).get('return', []):
                raise RuntimeError('Exact history read unavailable')
            return original(uri, args, options)
        client.call = unavailable
    code, failed = run('verify', tx)
    assert code == 2 and failed['verified'] is False, failed
    code, full = run('transaction-show', tx)
    assert code == 0, full
    event, = [row for row in full['events'] if row['event_type'] == 'verification_recorded']
    command = {'gateway_argv': ['transaction-show', tx, '--history-view', 'verification',
        '--outcome-artifact-hash', full['artifact_hash'], '--outcome-event-hash', event['event_hash']]}
    value, _pages = _collect_history_pages(run, command, client)
    assert value == event['details']['verification'] and value['ok'] is False
    assert value['status'] == 'verification_failed'
    if read_error:
        assert 'Exact history read unavailable' in json.dumps(value)


def test_compound_history_uses_actual_indexed_child_execution_and_verification(tmp_path):
    from wwise_waapi.canonical import canonical_sha256
    client, _state, source, history, _shown, run = _owned_notes_history_case(
        tmp_path, source_operation="waapi.undoGroup")
    code, shown = run("transaction-show", source["transaction_id"])
    assert code == 0, shown
    artifact = shown["artifact"]
    events = shown["events"]
    executed = next(event["details"]["dispatch_result"] for event in events
        if event["event_type"] == "execution_completed")
    verified = next(event["details"]["verification"] for event in events
        if event["event_type"] == "verification_recorded")
    associations = [item["evidence"] for item in verified["assertions"]
        if item.get("kind") == "compound_child_observation"]
    assert len(associations) == 2
    calls = artifact["prepared_operation"]["pre_state"]["execution_plan"]["calls"]
    for index, association in enumerate(associations):
        assert association["index"] == index
        assert association["prepared_sha256"] == canonical_sha256(calls[index]["prepared_operation"])
        assert association["dispatch_sha256"] == canonical_sha256(executed["result"]["phases"][index + 1]["dispatch_result"])
        assert association["verification"]["business_state_verified"] is True
    code, result = run("execute", history["transaction_id"])
    assert code == 0, result
    code, result = run("verify", history["transaction_id"])
    assert code == 0 and result["verified"] is True, result
    assert (client.source["name"], client.source["notes"]) == (
        client.history_before["name"], client.history_before["notes"])


def _start_parent_owned_graph_child(task, operation):
    code, phase = task.run("draft-start", "waapi.undoGroup")
    assert code == 0, phase
    parent = (phase["draft"]["draft_id"], phase["task_authority"], phase["draft"]["revision"])
    code, phase = task.run("draft-start-undo-child", parent[0], "--task-authority", parent[1],
        "--expected-revision", str(parent[2]), "--operation", operation)
    assert code == 0, json.dumps(phase)
    task.compound_parent = parent
    task.draft, task.authority, task.revision = phase["draft"]["draft_id"], phase["task_authority"], phase["draft"]["revision"]


def _compound_from_graph_task(task, *, notes_id, expected_error=None, companion="object.setNotes", field=None, value="false", creation_first=True, rename_existing=False, notes_companion_id=None, additional_rename_id=None, additional_rename_name="Outer renamed", expected_verified=True, before_parent_check=None, notes_child_order=None, notes_child_operation="object.setNotes", notes_child_id=None, prepared_only=False):
    from copy import deepcopy
    before = deepcopy(task.objects)
    original = task.call
    def call(uri, args=None, options=None):
        if uri in {"ak.wwise.core.undo.beginGroup", "ak.wwise.core.undo.endGroup", "ak.wwise.core.undo.cancelGroup"}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {}
        if uri == "ak.wwise.core.object.setNotes":
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            task.objects[args["object"]]["notes"] = args["value"]
            return {}
        return original(uri, args, options)
    task.call = call
    children = [task.draft, task.authority]
    parent, authority, revision = task.compound_parent
    code, phase = task.run("draft-start-undo-child", parent, "--task-authority", authority,
        "--expected-revision", str(revision), "--operation", companion)
    assert code == 0, json.dumps(phase)
    task.draft, task.authority, task.revision = phase["draft"]["draft_id"], phase["task_authority"], phase["draft"]["revision"]
    owner = task.bind(notes_id)
    if field:
        code, fields = task.step("draft-discover-fields", "--object-handle", owner, "--meaning", field,
            "--platform", "{44444444-4444-4444-4444-444444444444}")
        assert code == 0, fields
        selected = fields.get("field_candidates", fields.get("meaning_results", [{}])[0].get("candidates"))[0]["handle"]
        if companion == "object.setProperty":
            code, declared = task.step("draft-declare-field-change", "--object-handle", owner,
                "--field-handle", selected, "--business-value", value)
        else:
            code, declared = task.step("draft-declare-existing", "--declaration-id", "companion", "--object-handle", owner,
                "--field-value", selected, value)
        assert code == 0, declared
    elif companion == "object.set":
        assert task.step("draft-declare-existing", "--declaration-id", "companion", "--object-handle", owner,
            *(["--field", "new_name", "Renamed parent"] if rename_existing else ["--field", "notes", "Compound companion notes"]))[0] == 0
    elif companion == "object.setName":
        assert task.step("draft-declare-object-change", "--new-name", "Renamed parent")[0] == 0
    elif companion == "object.create":
        assert task.step("draft-declare-new", "--declaration-id", "companion", "--parent-handle", owner,
            "--kind", "sound-sfx", "--name", "History root")[0] == 0
    else:
        assert task.step("draft-declare-object-change", "--notes", "Compound companion notes")[0] == 0
    if notes_companion_id:
        handle = task.bind(notes_companion_id)
        code, declared = task.step('draft-declare-existing', '--declaration-id', 'descendant-notes',
            '--object-handle', handle, '--field', 'notes', 'Companion descendant note')
        assert code == 0, declared
    assert task.step("draft-check")[0] == 0
    children.extend([task.draft, task.authority])
    if additional_rename_id:
        code, phase = task.run('draft-start-undo-child', parent, '--task-authority', authority,
            '--expected-revision', str(revision), '--operation', 'object.setName')
        assert code == 0, phase
        task.draft, task.authority, task.revision = phase['draft']['draft_id'], phase['task_authority'], phase['draft']['revision']
        task.bind(additional_rename_id)
        assert task.step('draft-declare-object-change', '--new-name', additional_rename_name)[0] == 0
        assert task.step('draft-check')[0] == 0
        children.extend([task.draft, task.authority])
    if not creation_first:
        children = children[2:] + children[:2]
    if notes_child_order:
        code, phase = task.run('draft-start-undo-child', parent, '--task-authority', authority,
            '--expected-revision', str(revision), '--operation', notes_child_operation)
        assert code == 0, phase
        task.draft, task.authority, task.revision = phase['draft']['draft_id'], phase['task_authority'], phase['draft']['revision']
        notes_owner = task.bind(notes_child_id or notes_id)
        if notes_child_operation == 'object.setNotes':
            assert task.step('draft-declare-object-change', '--notes', 'Earlier declared notes')[0] == 0
        else:
            assert task.step('draft-declare-existing', '--declaration-id', 'notes-child',
                '--object-handle', notes_owner, '--field', 'notes', 'Earlier declared notes')[0] == 0
        assert task.step('draft-check')[0] == 0
        offset = 0 if notes_child_order == 'before' else 2
        children[offset:offset] = [task.draft, task.authority]
    task.draft, task.authority, task.revision = parent, authority, revision
    code, phase = task.step("draft-declare-undo-plan", "--display-name", "Owned compound fields",
        *[token for index in range(0, len(children), 2) for token in ("--child-draft", children[index], children[index + 1])])
    assert code == 0, json.dumps(phase)
    if before_parent_check:
        before_parent_check(task)
    if expected_error:
        code, rejected = task.step("draft-check")
        assert code == 2 and rejected["error_code"] == expected_error, rejected
        assert task.objects == before
        return rejected
    source, shown = task.preview()
    if prepared_only:
        return source, before, shown
    code, result = task.finish(source, shown)
    assert code == (0 if expected_verified else 2) and result["verified"] is expected_verified, json.dumps(result)
    task.source_verification = result
    after = deepcopy(task.objects)
    source_call = task.call
    def history(uri, args=None, options=None):
        if uri in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            task.objects = deepcopy(before if uri.endswith(".undo") else after)
            return {}
        return source_call(uri, args, options)
    task.call = history
    return source, before, after


@pytest.mark.parametrize("version", ["2022.1", "2025.1"])
def test_compound_created_leaf_history_uses_actual_returned_identity_and_all_fields(tmp_path, version):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT
    task, _unused_preview, _shown = _created_leaf_history_case(tmp_path,
        version=version, created_fields=True, reference="null", compound=True)
    source, before, after = _compound_from_graph_task(task, notes_id=FIRST)
    created = next(row for row in after.values() if row["name"] == "Rain")
    for direction, expected in [("undo", before), *([] if version == "2022.1" else [("redo", after)])]:
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run("execute", tx)[0] == 0
        code, verified = task.run("verify", tx)
        assert code == 0 and verified["verified"] is True, verified
        assert task.objects == expected
        assert (created["id"] in task.objects) is (direction == "redo")
    assert after[FIRST]["notes"] == "Compound companion notes"
    assert created["@IsLoopingEnabled"] is True and created["@IsLoopingInfinite"] is True
    assert created["@Volume"] == -6 and created["@Attenuation"] is None
    assert len([row for row in task.calls if row[0] == "ak.wwise.core.object.create"]) == 1


@pytest.mark.parametrize("operation", ["object.setProperty", "object.set"])
def test_compound_render_and_notes_history_restores_actual_full_chain(tmp_path, operation):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT, CHILD
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT
    task, _, _, _, _ = _render_history_case(tmp_path, operation=operation, compound=True)
    source, before, after = _compound_from_graph_task(task, notes_id=FIRST)
    for direction, expected in (("undo", before), ("redo", after)):
        tx = _created_leaf_history_preview(task, source, direction)
        code, compact = task.run("transaction-show", tx, "--summary-only")
        assert code == 0, compact
        notice = compact["preview_summary"]["history_action"]
        assert notice["observations_complete"] is False
        binding, pages = _collect_history_pages(task.run, notice["detail"], task)
        code, full = task.run("transaction-show", tx)
        assert code == 0, full
        assert binding == full["artifact"]["prepared_operation"]["pre_state"]["history_binding"]
        assert any(row.get("kind") == "existing_render_chain" for row in binding["observations"])
        assert any(row.get("field") == "notes" and row["after"] == "Compound companion notes" for row in binding["observations"])
        assert pages[-1]["complete"] is True
        assert task.run("execute", tx)[0] == 0
        code, verified = task.run("verify", tx)
        assert code == 0 and verified["verified"] is True, verified
        assert task.objects == expected
        assert task.objects[EFFECT] == before[EFFECT]
        assert task.objects[ROOT]["@Bypass"] is True and task.objects[CHILD]["@Bypass"] is False
    assert after[ROOT]["@Render"] is True and after[CHILD]["@Render"] is True
    assert before[ROOT]["@Render"] is False and before[CHILD]["@Render"] is False
    assert after[FIRST]["notes"] == "Compound companion notes"


@pytest.mark.parametrize("companion,field,owner", [
    ("object.setProperty", "Volume", "ordinary"),
    ("object.set", "Render", "derived"),
    ("object.setProperty", "Render", "derived"),
])
def test_compound_cross_kind_and_render_derived_field_collisions_block_before_write(tmp_path, companion, field, owner):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT
    if owner == "ordinary":
        task, _, _, _ = _existing_fields_history_case(tmp_path, compound=True)
    else:
        task, _, _, _, _ = _render_history_case(tmp_path, compound=True)
    _compound_from_graph_task(task, notes_id=FIRST if owner == "ordinary" else ROOT,
        companion=companion, field=field, value="-12" if owner == "ordinary" else "true",
        expected_error="UNDO_GROUP_OVERLAPPING_OUTCOME")
    assert not any(uri.startswith("ak.wwise.core.undo.") or uri.endswith(("object.set", "object.setProperty"))
        for uri, _, _ in task.calls)


def test_compound_existing_multi_field_receipt_preserves_actual_scalar_and_reference_outcomes(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, SECOND, ROOT
    task, _, _, _ = _existing_fields_history_case(tmp_path, compound=True)
    source, before, after = _compound_from_graph_task(task, notes_id=SECOND)
    for direction, expected in (("undo", before), ("redo", after)):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run("execute", tx)[0] == 0
        code, verified = task.run("verify", tx)
        assert code == 0 and verified["verified"] is True, verified
        assert task.objects == expected
        assert task.objects[ROOT] == before[ROOT]
    assert after[FIRST]["@Volume"] == -6 and after[FIRST]["@Priority"] == 42
    assert after[FIRST]["@Attenuation"] is None



def test_compound_same_uri_children_keep_distinct_actual_observation_ranges(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, SECOND
    task, _, _, _ = _existing_fields_history_case(tmp_path, compound=True)
    source, before, after = _compound_from_graph_task(task, notes_id=SECOND, companion="object.set")
    code, shown = task.run("transaction-show", source)
    assert code == 0, shown
    verification = next(row["details"]["verification"] for row in shown["events"] if row["event_type"] == "verification_recorded")
    records = [row["evidence"] for row in verification["assertions"] if row.get("kind") == "compound_child_observation"]
    assert [row["index"] for row in records] == [0, 1]
    assert records[0]["prepared_sha256"] != records[1]["prepared_sha256"]
    assert records[0]["dispatch_sha256"] != records[1]["dispatch_sha256"]
    writes = [args for uri, args, _ in task.calls if uri == "ak.wwise.core.object.set"]
    assert [args["objects"][0]["object"] for args in writes] == [FIRST, SECOND]
    for direction, expected in (("undo", before), ("redo", after)):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run("execute", tx)[0] == 0
        code, verified = task.run("verify", tx)
        assert code == 0 and verified["verified"] is True, verified
        assert task.objects == expected


@pytest.mark.parametrize("fault", ["missing", "prepared", "dispatch", "index", "boolean-index", "range", "phase-index", "weak-child",
    "assertion-boolean-tag", "assertion-wrong-tag", "readback-boolean-tag", "readback-wrong-tag"])
def test_compound_history_rejects_structurally_valid_but_misassociated_child_events(tmp_path, fault):
    from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
    client, state, source, _, _, run = _owned_notes_history_case(tmp_path,
        source_operation="waapi.undoGroup", source_prepared_only=True)
    assert run("execute", source["transaction_id"])[0] == 0
    assert run("verify", source["transaction_id"])[0] == 0
    code, shown = run("transaction-show", source["transaction_id"])
    assert code == 0, shown
    events = shown["events"]
    verification = next(row["details"]["verification"] for row in events if row["event_type"] == "verification_recorded")
    associations = [row for row in verification["assertions"] if row.get("kind") == "compound_child_observation"]
    proof = associations[0]["evidence"]
    if fault == "missing": verification["assertions"].remove(associations[0])
    elif fault == "prepared": proof["prepared_sha256"] = associations[1]["evidence"]["prepared_sha256"]
    elif fault == "dispatch": proof["dispatch_sha256"] = associations[1]["evidence"]["dispatch_sha256"]
    elif fault == "index": proof["index"] = 1
    elif fault == "boolean-index": proof["index"] = False
    elif fault == "weak-child": proof["verification"]["business_state_verified"] = False
    elif fault == "range": proof["readbacks"] = associations[1]["evidence"]["readbacks"]
    elif fault.endswith("-tag"):
        section = "assertions" if fault.startswith("assertion-") else "readbacks"
        bounds = associations[1]["evidence"][section]
        rows = verification[section][bounds["start"]:bounds["start"] + bounds["count"]]
        assert rows
        rows[0]["compound_child_index"] = True if "boolean" in fault else 0
        bounds["sha256"] = canonical_sha256(rows)
    else:
        execution = next(row["details"]["dispatch_result"] for row in events if row["event_type"] == "execution_completed")
        execution["result"]["phases"][1]["index"] = 1
    # Model a malformed persisted producer, with a valid journal chain. The
    # public receipt consumer must check semantic associations as well as hashes.
    previous = ""
    for event in events:
        event["previous_event_hash"] = previous
        event.pop("event_hash")
        event["event_hash"] = previous = canonical_sha256(event)
    directory = state / "transactions" / source["transaction_id"]
    (directory / "events.jsonl").write_bytes(b"".join(canonical_json_bytes(event) + b"\n" for event in events))
    state_path = directory / "state.json"
    record = json.loads(state_path.read_text())
    record["last_event_hash"] = previous
    state_path.write_bytes(canonical_json_bytes(record))
    code, loaded = run("transaction-show", source["transaction_id"])
    assert code == 0 and loaded["state"] == "verified", loaded
    code, phase = run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, phase
    code, rejected = run("draft-declare-core-plan", phase["draft"]["draft_id"], "--task-authority", phase["task_authority"],
        "--expected-revision", str(phase["draft"]["revision"]), "--value", "history_scope", "latest_project_history",
        "--value", "expectation_receipt", source["transaction_id"])
    assert code == 2 and "Compound" in rejected["message"], rejected
    assert not any(uri in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"} for uri, _, _ in client.calls)


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_compound_discovery_exposes_exact_versioned_ordinary_children_and_proof_boundary(tmp_path, version):
    code, schema = offline_execute(tmp_path, "--version", version, "operation-schema", "waapi.undoGroup", version=version)
    assert code == 0, schema
    declaration = schema["business_adapter"]["declaration"]
    choices = declaration["eligible_child_operations"]
    assert "object.create" in choices
    assert ("object.set" in choices) is (version != "2021.1")
    assert "object.createPlugin" not in choices and "object.setRTPC" not in choices
    scope = declaration["child_observation_scope"]
    assert "ordinary_new_fail_or_owned_native_rename_hierarchy" in scope["object.create"]
    assert "actual_parent_execution_phase" in scope["history_receipt"]
    assert "remaining_same_parent" in scope["graph_list_merge_replace_restoration"]
    assert 'exact_intent_GUID_bound' in scope['created_graph_ancestor_rename']
    assert 'owned_actual_GUID_names_and_deferred_reference_stages' in scope['created_graph_ancestor_rename']
    assert 'typed_List_history_remains_implementation_obligation' in scope['graph_list_merge_replace_restoration']
    assert declaration["native_request_input"] == "forbidden"



def test_compound_history_display_names_do_not_define_child_ownership(tmp_path):
    from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
    client, state, source, _, _, run = _owned_notes_history_case(tmp_path,
        source_operation="waapi.undoGroup", source_prepared_only=True)
    assert run("execute", source["transaction_id"])[0] == 0
    assert run("verify", source["transaction_id"])[0] == 0
    code, shown = run("transaction-show", source["transaction_id"])
    assert code == 0, shown
    events = shown["events"]
    verification = next(row["details"]["verification"] for row in events if row["event_type"] == "verification_recorded")
    associations = [row["evidence"] for row in verification["assertions"] if row.get("kind") == "compound_child_observation"]
    for index, proof in enumerate(associations):
        for section in ("assertions", "readbacks"):
            bounds = proof[section]
            rows = verification[section][bounds["start"]:bounds["start"] + bounds["count"]]
            assert rows
            assert all(type(row.get("compound_child_index")) is int and row["compound_child_index"] == index for row in rows)
            if section == "assertions":
                for row in rows:
                    row["name"] = "Translated display text; no child ownership encoded here"
                bounds["sha256"] = canonical_sha256(rows)
    previous = ""
    for event in events:
        event["previous_event_hash"] = previous
        event.pop("event_hash")
        event["event_hash"] = previous = canonical_sha256(event)
    directory = state / "transactions" / source["transaction_id"]
    (directory / "events.jsonl").write_bytes(b"".join(canonical_json_bytes(event) + b"\n" for event in events))
    record_path = directory / "state.json"
    record = json.loads(record_path.read_text())
    record["last_event_hash"] = previous
    record_path.write_bytes(canonical_json_bytes(record))
    code, phase = run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, phase
    draft, authority = phase["draft"]["draft_id"], phase["task_authority"]
    code, phase = run("draft-declare-core-plan", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]), "--value", "history_scope", "latest_project_history",
        "--value", "expectation_receipt", source["transaction_id"])
    assert code == 0, phase
    code, phase = run("draft-check", draft, "--task-authority", authority, "--expected-revision", str(phase["draft"]["revision"]))
    assert code == 0, phase
    code, preview = run("preview-from-draft", draft, "--task-authority", authority, "--expected-revision", str(phase["draft"]["revision"]))
    assert code == 0, preview
    code, full = run("transaction-show", preview["transaction_id"])
    assert code == 0, full
    assert run("confirm", preview["transaction_id"], "--confirmation-token", full["confirmation"]["token"])[0] == 0
    assert run("execute", preview["transaction_id"])[0] == 0
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["verified"] is True, verified
    assert (client.source["name"], client.source["notes"]) == (client.history_before["name"], client.history_before["notes"])


def _created_graph_history_case(tmp_path, *, version='2025.1', compound=False, prepared_only=False, long_notes=False, setup=None):
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST
    task, _, _ = _created_leaf_history_case(tmp_path, version=version, nested=True,
        created_fields=True, reference='null', declaration_only=True, compound=compound,
        notes=('Nested graph note.\n' * 600) if long_notes else 'Created notes', setup=setup)
    code, inner = task.step('draft-declare-new', '--declaration-id', 'inner',
        '--parent-handle', task.created_parent_handle, '--kind', 'actor-mixer', '--name', 'Inner')
    assert code == 0, inner
    code, wind = task.step('draft-declare-new', '--declaration-id', 'wind',
        '--parent-handle', inner['draft']['declared_object']['result_handle'],
        '--kind', 'sound-sfx', '--name', 'Wind', '--field', 'notes', 'Nested wind')
    assert code == 0, wind
    ids = {name: '{' + str(index) * 8 + '-' + str(index) * 4 + '-' + str(index) * 4 + '-' + str(index) * 4 + '-' + str(index) * 12 + '}'
        for index, name in enumerate(('Container', 'Rain', 'Inner', 'Wind'), 6)}
    def create(node, parent, **_kwargs):
        identity = ids[node['name']]
        actual_type = 'PropertyContainer' if version == '2025.1' and node['type'] == 'ActorMixer' else node['type']
        task.objects[identity] = {'id': identity, 'name': node['name'], 'type': actual_type,
            'classId': next(row['classId'] for row in task.types if row['name'] == actual_type),
            'path': task.objects[parent]['path'] + '\\' + node['name'], 'parent': {'id': parent},
            'notes': node.get('notes', 'Native default ' + node['name']),
            **{key: deepcopy(value) for key, value in node.items() if key.startswith('@')}}
        children = [create(child, identity) for child in node.get('children', [])]
        return {'id': identity, 'name': node['name'], **({'children': children} if children else {})}
    task._create = create
    original = task.call
    def actual_classes(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.create'):
            for identity in ids.values():
                row = task.objects[identity]
                row['classId'] = next(item['classId'] for item in task.types if item['name'] == row['type'])
        return result
    task.call = actual_classes
    before = deepcopy(task.objects)
    if compound:
        assert task.step('draft-check')[0] == 0
        if prepared_only:
            return task, None, before, None
        source, before, after = _compound_from_graph_task(task, notes_id=FIRST)
        return task, source, before, after
    source, shown = task.preview()
    if prepared_only:
        return task, source, before, shown
    code, verified = task.finish(source, shown)
    assert code == 0 and verified['verified'] is True, verified
    after = deepcopy(task.objects)
    source_call = task.call
    def history(uri, args=None, options=None):
        if uri in {'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            task.objects = deepcopy(before if uri.endswith('.undo') else after)
            return {}
        return source_call(uri, args, options)
    task.call = history
    return task, source, before, after


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('compound', [False, True])
def test_created_graph_history_observes_every_actual_node_and_nested_fields(tmp_path, version, compound):
    task, source, before, after = _created_graph_history_case(tmp_path, version=version, compound=compound)
    for direction in (('undo',) if version == '2022.1' else ('undo', 'redo')):
        tx = _created_leaf_history_preview(task, source, direction)
        code, full = task.run('transaction-show', tx)
        assert code == 0, full
        observations = full['artifact']['prepared_operation']['pre_state']['history_binding']['observations']
        nodes = [row for row in observations if row.get('kind') == 'creation_presence']
        assert {row['object']['name'] for row in nodes} == {'Container', 'Rain', 'Inner', 'Wind'}
        assert all(type(row.get('class_id')) is int for row in nodes)
        assert task.run('execute', tx)[0] == 0
        code, verified = task.run('verify', tx)
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects == (before if direction == 'undo' else after)
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.create']) == 1


def _exercise_created_graph_internal_reference_history(tmp_path, version, *, target_name='Destination', compound=False, creation_first=True, external=False, external_ancestor_only=False, rename_operation='object.setName', notes_child_order=None, notes_child_operation='object.setNotes', notes_child_id=None, prepared_only=False, native_rename=False, set_graph=False, collision=True, planned_reference=True, platform_certified=True, multiple_roots=False, duplicate_siblings=False, retained_duplicates=False, suffix_like=False, source_only=False, create_constructor=False):
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, SECOND
    operation = 'object.set' if (native_rename or set_graph) and not create_constructor else 'object.create'
    task = OwnedGraphTask(tmp_path, version, operation)
    task.types = [{'classId': cid, 'name': name, 'type': 'WObject'} for cid, name in
        ((1638416, 'WorkUnit'), (1376272, 'Bus'), (3997712, 'AuxBus'))]
    task.objects = {SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
        'path': r'\Master-Mixer Hierarchy\Default Work Unit', 'parent': None, 'notes': 'Keep buses'}}
    task.metadata = {'UserAuxSend0': {'name': 'UserAuxSend0', 'type': 'Reference',
        'restriction': {'type': 'reference', 'restrictions': [{'type': ['AuxBus']}]}}}
    if compound:
        _start_parent_owned_graph_child(task, operation)
    if native_rename and collision:
        collision_id = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
        task.objects[collision_id] = {'id': collision_id, 'name': 'Routing', 'type': 'Bus', 'classId': 1376272,
            'path': task.objects[SECOND]['path'] + r'\Routing', 'parent': {'id': SECOND}, 'notes': 'Keep collision'}
        if multiple_roots:
            task.objects['{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}'] = {'id': '{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}',
                'name': 'Backup', 'type': 'Bus', 'classId': 1376272, 'path': task.objects[SECOND]['path'] + r'\Backup',
                'parent': {'id': SECOND}, 'notes': 'Keep second collision'}
    if external:
        from tests.unit.test_object_graph_owned_choices_gateway import ROOT
        task.objects[ROOT] = {'id': ROOT, 'name': 'External', 'type': 'AuxBus', 'classId': 3997712,
            'path': task.objects[SECOND]['path'] + r'\External', 'parent': {'id': SECOND}, 'notes': 'Keep external'}
        if external_ancestor_only:
            from tests.unit.test_object_graph_owned_choices_gateway import PROJECT_GROUP
            task.objects[PROJECT_GROUP] = {'id': PROJECT_GROUP, 'name': 'External buses', 'type': 'WorkUnit',
                'classId': 1638416, 'path': r'\Master-Mixer Hierarchy\External buses', 'parent': None, 'notes': 'Keep external unit'}
            task.objects[ROOT].update(path=r'\Master-Mixer Hierarchy\External buses\External', parent={'id': PROJECT_GROUP})

    ids = {'Routing': '{66666666-6666-6666-6666-666666666666}',
        'Backup': '{99999999-9999-9999-9999-999999999999}',
        'Destination': '{77777777-7777-7777-7777-777777777777}', 'Sender': '{88888888-8888-8888-8888-888888888888}'}
    platform = '{44444444-4444-4444-4444-444444444444}'
    original = task.call
    duplicate_created, duplicate_roots_created = [], []
    def create(node, parent):
        if retained_duplicates and node['type'] == 'Bus':
            key = ('Routing', 'Backup')[len(duplicate_roots_created)]
            duplicate_roots_created.append(key)
            identity, name = ids[key], ('Routing19' if key == 'Routing' else 'Routing83')
        elif suffix_like and node['name'] == 'Send37':
            identity, name = ids['Backup'], 'Send88'
        elif duplicate_siblings and node['name'] == 'Send':
            key = ('Destination', 'Sender')[len(duplicate_created)]
            duplicate_created.append(key)
            identity, name = ids[key], ('Send' if key == 'Destination' else 'Send37')
        else:
            identity = ids[node['name']]
            name = node['name']
        name = node['name'] + ('19' if node['name'] == 'Routing' else '37') if native_rename and collision and not retained_duplicates and node['name'] in {'Routing', 'Backup'} else name
        task.objects[identity] = {'id': identity, 'name': name, 'type': node['type'],
            'classId': 1376272 if node['type'] == 'Bus' else 3997712, 'parent': {'id': parent},
            'path': task.objects[parent]['path'] + '\\' + name, 'notes': '',
            **{key: {'id': value} for key, value in node.items() if key.startswith('@')}}
        children = [create(child, identity) for child in node.get('children', [])]
        return {'id': identity, 'name': name, **({'children': list(reversed(children))} if children else {})}
    def call(uri, args=None, options=None):
        if platform_certified and uri.endswith('getProjectInfo'):
            return {**original(uri, args, options), 'currentPlatformId': platform, 'platforms': [{'id': platform, 'name': 'Windows'}]}
        if (native_rename or set_graph) and uri.endswith('object.set') and any('children' in item or '@UserAuxSend0' in item for item in args['objects']):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if any('children' in item for item in args['objects']):
                assert args['onNameConflict'] == ('rename' if native_rename else 'fail')
                if not duplicate_siblings:
                    assert args['objects'][0]['children'][0]['name'] in ({'Routing', 'Backup'} if multiple_roots else {'Routing'})
                if multiple_roots:
                    assert len(args['objects']) == 1 and len(args['objects'][0]['children']) == 1
                    assert set(args['objects'][0]) == {'object', 'children'}
                parent_id = args['objects'][0]['object']
                children = [create(child, parent_id) for child in args['objects'][0]['children']]
                assert '@UserAuxSend0' not in task.objects.get(ids['Sender'], {})
                return {'objects': [{'id': parent_id, 'name': task.objects[parent_id]['name'], 'children': children}]}
            for item in args['objects']:
                assert set(item) == {'object', '@UserAuxSend0'}, item
                matches = [row['id'] for row in task.objects.values() if row['path'] == item['@UserAuxSend0']]
                assert matches == [ids['Destination']]
                task.objects[item['object']]['@UserAuxSend0'] = {'id': matches[0]}
            return {'objects': []}
        if create_constructor and uri == 'ak.wwise.core.object.setReference':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args['object'] in {ids['Sender'], ids['Backup']} and args['reference'] == 'UserAuxSend0'
            assert args['value'] == ids['Destination']
            task.objects[args['object']]['@UserAuxSend0'] = {'id': args['value']}
            return {}
        if create_constructor and uri.endswith('object.create'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args['onNameConflict'] == 'rename'
            return create(args, args['parent'])
        if uri.endswith('object.create'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            base = task.objects[SECOND]['path'] + r'\Routing'
            for key, name, cid, parent in (('Routing', 'Routing', 1376272, SECOND), ('Destination', target_name, 3997712, ids['Routing']), ('Sender', 'Sender', 3997712, ids['Routing'])):
                task.objects[ids[key]] = {'id': ids[key], 'name': name, 'classId': cid,
                    'type': 'Bus' if key == 'Routing' else 'AuxBus', 'parent': {'id': parent}, 'notes': '',
                    'path': base + ('' if key == 'Routing' else '\\' + name)}
            native_target = args['children'][1]['@UserAuxSend0']
            actual_targets = [row['id'] for row in task.objects.values() if row['path'] == native_target]
            assert len(actual_targets) == 1, native_target
            task.objects[ids['Sender']]['@UserAuxSend0'] = {'id': actual_targets[0]}
            if external:
                assert args['children'][0]['@UserAuxSend0'] == ROOT
                task.objects[ids['Destination']]['@UserAuxSend0'] = {'id': ROOT}
            return {'id': ids['Routing'], 'name': 'Routing', 'children': [
                {'id': ids['Destination'], 'name': target_name}, {'id': ids['Sender'], 'name': 'Sender'}]}
        if uri in {'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            task.objects = deepcopy(before if uri.endswith('.undo') else after)
            return {}
        return original(uri, args, options)
    task.call = call
    parent = task.bind(SECOND)
    if native_rename:
        code, configured = task.step('draft-business-configure', '--name-conflict', 'rename')
        assert code == 0, json.dumps(configured)
    kinds = {}
    for name in ('Bus', 'AuxBus'):
        code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', name)
        assert code == 0, found
        kinds[name] = found['type_candidates'][0]['handle']
    code, found = task.step('draft-discover-fields', '--type-handle', kinds['AuxBus'], '--meaning', 'UserAuxSend0')
    assert code == 0, found
    field = found['meaning_results'][0]['candidates'][0]['handle']
    code, root = task.step('draft-declare-new', '--declaration-id', 'root', '--parent-handle', parent, '--kind', kinds['Bus'], '--name', 'Routing')
    assert code == 0, root
    root = root['draft']['declared_object']['result_handle']
    external_fields = ['--field-value', field, task.bind(ROOT)] if external else []
    code, target = task.step('draft-declare-new', '--declaration-id', 'target', '--parent-handle', root, '--kind', kinds['AuxBus'], '--name', 'Send' if duplicate_siblings else target_name, *external_fields)
    assert code == 0, target
    if multiple_roots:
        code, second = task.step('draft-declare-new', '--declaration-id', 'backup', '--parent-handle', parent, '--kind', kinds['Bus'], '--name', 'Routing' if retained_duplicates else 'Backup')
        assert code == 0, second
        root = second['draft']['declared_object']['result_handle']
    code, sender = task.step('draft-declare-new', '--declaration-id', 'sender', '--parent-handle', root, '--kind', kinds['AuxBus'], '--name', 'Send' if duplicate_siblings else 'Sender',
        *(['--field-value', field, target['draft']['declared_object']['result_handle']] if planned_reference else []))
    assert code == 0, sender
    if suffix_like:
        assert task.step('draft-declare-new', '--declaration-id', 'suffix-like', '--parent-handle', root,
            '--kind', kinds['AuxBus'], '--name', 'Send37',
            *(['--field-value', field, target['draft']['declared_object']['result_handle']] if create_constructor else []))[0] == 0
    before = deepcopy(task.objects)
    if compound:
        _install_created_graph_rename_client(task)
        assert task.step('draft-check')[0] == 0
        source, before, after = _compound_from_graph_task(task, notes_id=PROJECT_GROUP if external_ancestor_only else SECOND,
            companion=rename_operation, rename_existing=rename_operation == 'object.set', creation_first=creation_first,
            notes_child_order=notes_child_order, notes_child_operation=notes_child_operation, notes_child_id=notes_child_id, prepared_only=prepared_only)
        if prepared_only:
            return task, source, before, after
        if external_ancestor_only:
            assert after[SECOND] == before[SECOND]
            assert after[ROOT] == {**before[ROOT], 'path': r'\Master-Mixer Hierarchy\Renamed parent\External'}
            assert after[ids['Sender']]['path'] == r'\Master-Mixer Hierarchy\Default Work Unit\Routing\Sender'
    else:
        source, shown = task.preview()
        if prepared_only:
            return task, source, before, shown
        code, verified = task.finish(source, shown)
        assert code == 0 and verified['verified'] is True, verified
        task.source_verification = verified
        after = deepcopy(task.objects)
    if source_only:
        return task, source, before, after
    if version == '2021.1':
        assert task.run('draft-start', 'ak.wwise.core.undo.undo')[0] == 2
        return
    for direction in (('undo',) if version == '2022.1' else ('undo', 'redo')):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run('execute', tx)[0] == 0
        code, verified = task.run('verify', tx)
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects == (before if direction == 'undo' else after)

    return task, source, before, after


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_created_graph_history_restores_internal_reference_without_preserving_absent_target(tmp_path, version):
    _exercise_created_graph_internal_reference_history(tmp_path, version)


def test_created_graph_internal_reference_target_may_share_root_basename(tmp_path):
    _exercise_created_graph_internal_reference_history(tmp_path, '2025.1', target_name='Routing')


@pytest.mark.parametrize('compound', [False, True])
def test_2021_created_graph_source_and_compound_admission_do_not_invent_history_uri(tmp_path, compound):
    task, source, before, after = _created_graph_history_case(tmp_path, version='2021.1', compound=compound)
    assert len(after) - len(before) == 4
    code, rejected = task.run('draft-start', 'ak.wwise.core.undo.undo')
    assert code == 2 and '2021.1' in json.dumps(rejected), rejected
    assert not any(row[0] == 'ak.wwise.core.undo.undo' for row in task.calls)


@pytest.mark.parametrize('damage', ['surviving-child', 'new-guid', 'empty-container-class', 'parent', 'nested-field', 'extra-descendant'])
def test_created_graph_history_false_native_success_cannot_certify_partial_graph(tmp_path, damage):
    from copy import deepcopy
    task, source, before, after = _created_graph_history_case(tmp_path)
    undo = _created_leaf_history_preview(task, source)
    assert task.run('execute', undo)[0] == 0
    if damage == 'surviving-child':
        child = next(row for row in after.values() if row['name'] == 'Wind')
        task.objects[child['id']] = deepcopy(child)
        target = undo
    else:
        assert task.run('verify', undo)[0] == 0
        target = _created_leaf_history_preview(task, source, 'redo')
        assert task.run('execute', target)[0] == 0
        if damage == 'new-guid':
            row = next(row for row in task.objects.values() if row['name'] == 'Wind')
            del task.objects[row['id']]
            row['id'] = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'
            task.objects[row['id']] = row
        elif damage == 'empty-container-class':
            next(row for row in task.objects.values() if row['name'] == 'Inner')['classId'] = 999
        elif damage == 'parent':
            next(row for row in task.objects.values() if row['name'] == 'Wind')['parent'] = {'id': next(row['id'] for row in task.objects.values() if row['name'] == 'Container')}
        elif damage == 'nested-field':
            next(row for row in task.objects.values() if row['name'] == 'Rain')['@Volume'] = True
        else:
            parent = next(row for row in task.objects.values() if row['name'] == 'Container')
            extra = {'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'Extra', 'type': 'Sound', 'classId': 2,
                'parent': {'id': parent['id']}, 'notes': '', 'path': parent['path'] + r'\Extra'}
            task.objects[extra['id']] = extra
    code, failed = task.run('verify', target)
    assert code == 2 and failed.get('verified') is False, failed
    count = len([row for row in task.calls if row[0] in {'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'}])
    assert count == (1 if damage == 'surviving-child' else 2)


def _rewrite_created_graph_verification(task, source, mutate):
    from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
    code, shown = task.run('transaction-show', source)
    assert code == 0, shown
    events = shown['events']
    verification = next(row['details']['verification'] for row in events if row['event_type'] == 'verification_recorded')
    mutate(verification)
    previous = ''
    for event in events:
        event['previous_event_hash'] = previous
        event.pop('event_hash')
        event['event_hash'] = previous = canonical_sha256(event)
    directory = task.path / 'state' / 'transactions' / source
    (directory / 'events.jsonl').write_bytes(b''.join(canonical_json_bytes(event) + b'\n' for event in events))
    state_path = directory / 'state.json'
    record = json.loads(state_path.read_text())
    record['last_event_hash'] = previous
    state_path.write_bytes(canonical_json_bytes(record))


def _reject_created_graph_receipt(task, source):
    code, phase = task.run('draft-start', 'ak.wwise.core.undo.undo')
    assert code == 0, phase
    code, rejected = task.run('draft-declare-core-plan', phase['draft']['draft_id'], '--task-authority', phase['task_authority'],
        '--expected-revision', str(phase['draft']['revision']), '--value', 'history_scope', 'latest_project_history',
        '--value', 'expectation_receipt', source)
    assert code == 2, rejected
    assert not any(row[0] == 'ak.wwise.core.undo.undo' for row in task.calls)
    return rejected


@pytest.mark.parametrize('fault', ['missing-node', 'metadata-node', 'boolean-class', 'extra-membership'])
def test_created_graph_receipt_rejects_incomplete_or_misassociated_actual_producer_proof(tmp_path, fault):
    from copy import deepcopy
    task, source, _, _ = _created_graph_history_case(tmp_path)
    def damage(verification):
        nodes = [row for row in verification['assertions'] if row.get('kind') == 'verified_created_node_identity']
        if fault == 'missing-node':
            verification['assertions'].remove(nodes[-1])
        elif fault == 'boolean-class':
            nodes[0]['evidence']['class_id'] = True
        elif fault == 'metadata-node':
            row = next(row for row in verification['readbacks'] if row.get('role') == 'created-root-history-field-metadata')
            row['request_path'] = '$.children[99]'
        else:
            membership = next(row for row in verification['readbacks'] if row.get('role') == 'created-graph-history-membership')
            extra = deepcopy(membership['result']['return'][0])
            extra.update(id='{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', name='Unreported', path=extra['path'] + r'\Unreported')
            membership['result']['return'].append(extra)
    _rewrite_created_graph_verification(task, source, damage)
    _reject_created_graph_receipt(task, source)


def test_compound_created_graph_complete_bound_stops_before_write(tmp_path, monkeypatch):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, SECOND
    from wwise_waapi import edit_history_business
    task, _, _, _ = _created_graph_history_case(tmp_path, compound=True, prepared_only=True)
    monkeypatch.setattr(edit_history_business, 'MAX_OBSERVATIONS', 8)
    _compound_from_graph_task(task, notes_id=FIRST, companion='object.setNotes',
        expected_error='UNDO_GROUP_OBSERVATION_LIMIT_EXCEEDED')
    assert not any(row[0] in {'ak.wwise.core.object.create', 'ak.wwise.core.undo.beginGroup'} for row in task.calls)


@pytest.mark.parametrize('drift', ['nested-notes', 'raw-metadata'])
def test_created_graph_history_revalidates_complete_scope_before_native_action(tmp_path, drift):
    task, source, _, _ = _created_graph_history_case(tmp_path)
    tx = _created_leaf_history_preview(task, source)
    if drift == 'nested-notes':
        next(row for row in task.objects.values() if row['name'] == 'Wind')['notes'] = 'Later edit'
    else:
        task.metadata['Volume']['nativeExtension'] = None
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert not any(row[0] == 'ak.wwise.core.undo.undo' for row in task.calls)


def test_created_graph_optional_object_metadata_failure_keeps_source_but_blocks_stronger_receipt(tmp_path):
    task, source, _, shown = _created_graph_history_case(tmp_path, prepared_only=True)
    original = task.call
    def metadata_failure(uri, args=None, options=None):
        if uri.endswith('getPropertyInfo') and args.get('object') in task.objects and task.objects[args['object']]['name'] == 'Rain':
            raise RuntimeError('Graph optional exact-object metadata unavailable')
        return original(uri, args, options)
    task.call = metadata_failure
    code, verified = task.finish(source, shown)
    assert code == 0 and verified['verified'] is True, verified
    rejected = _reject_created_graph_receipt(task, source)
    assert 'metadata' in json.dumps(rejected).lower()


def test_created_graph_history_review_pages_reconstruct_complete_original_graph(tmp_path):
    task, source, before, _ = _created_graph_history_case(tmp_path, long_notes=True)
    tx = _created_leaf_history_preview(task, source)
    code, compact = task.run('transaction-show', tx, '--summary-only')
    assert code == 0, compact
    detail = compact['preview_summary']['history_action']['detail']
    binding, pages = _collect_history_pages(task.run, detail, task)
    code, full = task.run('transaction-show', tx)
    assert code == 0, full
    assert binding == full['artifact']['prepared_operation']['pre_state']['history_binding']
    assert {row['object']['name'] for row in binding['observations'] if row['kind'] == 'creation_presence'} == {'Container', 'Rain', 'Inner', 'Wind'}
    assert pages[-1]['complete'] is True
    assert task.run('execute', tx)[0] == 0
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified
    assert task.objects == before


def test_created_graph_history_full_proof_keeps_existing_byte_ceiling(tmp_path, monkeypatch):
    from wwise_waapi import edit_history_business
    task, source, _, _ = _created_graph_history_case(tmp_path)
    monkeypatch.setattr(edit_history_business, 'MAX_BINDING_BYTES', 1024)
    rejected = _reject_created_graph_receipt(task, source)
    assert 'bounded proof size' in rejected['message']


def test_compound_created_graph_cannot_borrow_another_child_observation_tag(tmp_path):
    from wwise_waapi.canonical import canonical_sha256
    task, source, _, _ = _created_graph_history_case(tmp_path, compound=True)
    def wrong_child(verification):
        association = next(row['evidence'] for row in verification['assertions'] if row.get('kind') == 'compound_child_observation')
        bounds = association['readbacks']
        rows = verification['readbacks'][bounds['start']:bounds['start'] + bounds['count']]
        next(row for row in rows if row.get('role') == 'created-node-history-source')['compound_child_index'] = 1
        bounds['sha256'] = canonical_sha256(rows)
    _rewrite_created_graph_verification(task, source, wrong_child)
    rejected = _reject_created_graph_receipt(task, source)
    assert 'typed child index' in rejected['message']


def test_compound_created_graph_complete_bound_includes_existing_render_observations(tmp_path, monkeypatch):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    from wwise_waapi import edit_history_business
    task, _, _, _, _ = _render_history_case(tmp_path, compound=True)
    monkeypatch.setattr(edit_history_business, 'MAX_OBSERVATIONS', 3)
    _compound_from_graph_task(task, notes_id=SECOND, companion='object.create',
        expected_error='UNDO_GROUP_OBSERVATION_LIMIT_EXCEEDED')
    assert not any(row[0] in {'ak.wwise.core.object.create', 'ak.wwise.core.undo.beginGroup'} for row in task.calls)


def _install_created_graph_rename_client(task):
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    # Explicit native null is a parent fact; omission is tested separately.
    task.objects[SECOND].setdefault('parent', None)
    original = task.call
    def rename(uri, args=None, options=None):
        if uri == 'ak.wwise.core.object.set':
            for item in args['objects']:
                if 'name' in item:
                    row = task.objects[item['object']]
                    old = row['path']
                    row.update(name=item['name'], path=old.rsplit('\\', 1)[0] + '\\' + item['name'])
                    for child in task.objects.values():
                        if child['path'].startswith(old + '\\'):
                            child['path'] = row['path'] + child['path'][len(old):]
        if uri == 'ak.wwise.core.object.setName':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            row = task.objects[args['object']]
            old = row['path']
            row.update(name=args['value'], path=old.rsplit('\\', 1)[0] + '\\' + args['value'])
            for child in task.objects.values():
                if child['path'].startswith(old + '\\'):
                    child['path'] = row['path'] + child['path'][len(old):]
            return {}
        return original(uri, args, options)
    task.call = rename


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_created_graph_and_parent_rename_share_actual_source_and_history_paths(tmp_path, version):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task, _, _, _ = _created_graph_history_case(tmp_path, version=version, compound=True, prepared_only=True)
    _install_created_graph_rename_client(task)
    if version == '2025.1':
        original = task.call
        def canonical_native_parents(uri, args=None, options=None):
            result = original(uri, args, options)
            if uri == 'ak.wwise.core.object.get':
                for row in result.get('return', []):
                    if isinstance(row.get('parent'), dict):
                        row['parent'] = row['parent']['id'].lower()
            return result
        task.call = canonical_native_parents
    source, before, after = _compound_from_graph_task(task, notes_id=SECOND, companion='object.setName')
    assert after[SECOND]['name'] == 'Renamed parent'
    assert all(row['path'].startswith(r'\Actor-Mixer Hierarchy\Renamed parent\Container')
        for row in after.values() if row['name'] in {'Container', 'Rain', 'Inner', 'Wind'})
    if version == '2021.1':
        assert task.run('draft-start', 'ak.wwise.core.undo.undo')[0] == 2
        return
    for direction in (('undo',) if version == '2022.1' else ('undo', 'redo')):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run('execute', tx)[0] == 0
        code, verified = task.run('verify', tx)
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects == (before if direction == 'undo' else after)
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.create']) == 1


@pytest.mark.parametrize('creation_first', [True, False])
def test_created_graph_ancestor_rename_binds_internal_native_path_and_external_target_history(tmp_path, creation_first):
    _exercise_created_graph_internal_reference_history(tmp_path, '2025.1', compound=True,
        creation_first=creation_first, external=True)


def _created_graph_higher_ancestor_source(tmp_path, *, bad_ancestry=False, rename_parent=False):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND, PROJECT_GROUP, FIRST
    def setup(task):
        task.require_class_projection = True
        old = task.objects[SECOND]['path']
        for row in task.objects.values():
            row['path'] = row['path'].replace(old, r'\Actor-Mixer Hierarchy\Outer\Default Work Unit', 1)
        task.objects[SECOND]['parent'] = {'id': PROJECT_GROUP}
        task.objects[FIRST]['classId'] = 1
        task.objects[SECOND]['classId'] = 3
        if bad_ancestry:
            task.objects[SECOND]['parent'] = {'id': FIRST}
        task.objects[PROJECT_GROUP] = {'id': PROJECT_GROUP, 'name': 'Outer', 'type': 'Folder',
            'classId': 4, 'path': r'\Actor-Mixer Hierarchy\Outer', 'parent': None, 'notes': 'Keep outer'}
        task.types.append({'classId': 4, 'name': 'Folder', 'type': 'WObject'})
    task, _, _, _ = _created_graph_history_case(tmp_path, compound=True, prepared_only=True, setup=setup)
    original = task.call
    def rename(uri, args=None, options=None):
        if uri == 'ak.wwise.core.object.set':
            for item in args['objects']:
                if 'name' in item:
                    row = task.objects[item['object']]
                    old = row['path']
                    row.update(name=item['name'], path=old.rsplit('\\', 1)[0] + '\\' + item['name'])
                    for child in task.objects.values():
                        if child['path'].startswith(old + '\\'):
                            child['path'] = row['path'] + child['path'][len(old):]
        return original(uri, args, options)
    task.call = rename
    if bad_ancestry:
        rejected = _compound_from_graph_task(task, notes_id=PROJECT_GROUP, companion='object.set', rename_existing=True,
            expected_error='UNDO_GROUP_GRAPH_PATH_DEPENDENCY_UNPROVEN')
        return task, rejected
    source, before, after = _compound_from_graph_task(task, notes_id=SECOND if rename_parent else PROJECT_GROUP, companion='object.set', rename_existing=True, notes_companion_id=FIRST)
    return task, source, before, after


def test_created_graph_higher_ancestor_object_set_rename_keeps_existing_companion_proof(tmp_path):
    task, source, before, after = _created_graph_higher_ancestor_source(tmp_path)
    for direction in ('undo', 'redo'):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run('execute', tx)[0] == 0
        code, result = task.run('verify', tx)
        assert code == 0 and result['verified'] is True, result
        assert task.objects == (before if direction == 'undo' else after)


def test_created_graph_nested_ancestor_renames_keep_original_component_positions(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND, PROJECT_GROUP
    def setup(task):
        for row in task.objects.values():
            row['path'] = row['path'].replace(r'\Actor-Mixer Hierarchy\Default Work Unit', r'\Actor-Mixer Hierarchy\Outer\Default Work Unit', 1)
        task.objects[SECOND]['parent'] = {'id': PROJECT_GROUP}
        task.objects[PROJECT_GROUP] = {'id': PROJECT_GROUP, 'name': 'Outer', 'type': 'Folder',
            'classId': 4, 'path': r'\Actor-Mixer Hierarchy\Outer', 'parent': None, 'notes': 'Keep outer'}
    task, _, _, _ = _created_graph_history_case(tmp_path, compound=True, prepared_only=True, setup=setup)
    _install_created_graph_rename_client(task)
    source, before, after = _compound_from_graph_task(task, notes_id=SECOND, companion='object.setName', additional_rename_id=PROJECT_GROUP)
    assert next(row for row in after.values() if row['name'] == 'Wind')['path'] == r'\Actor-Mixer Hierarchy\Outer renamed\Renamed parent\Container\Inner\Wind'
    for direction in ('undo', 'redo'):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run('execute', tx)[0] == 0
        code, verified = task.run('verify', tx)
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects == (before if direction == 'undo' else after)


@pytest.mark.parametrize('fault', ['guards', 'snapshot', 'phase-args'])
def test_created_graph_receipt_cannot_reseal_an_incomplete_parent_path_context(tmp_path, fault):
    from copy import deepcopy
    from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
    task, source, _, _ = _created_graph_higher_ancestor_source(tmp_path)
    directory = task.path / 'state' / 'transactions' / source
    document = json.loads((directory / 'preview.json').read_text())
    prepared = document['artifact']['prepared_operation']
    plan = prepared['pre_state']['execution_plan']
    if fault == 'guards':
        assert plan['path_context']['guards']
        plan['path_context']['guards'] = []
    elif fault == 'snapshot':
        plan['path_context']['snapshots'].pop(0)
    else:
        plan['calls'][0]['args']['name'] = 'Unreviewed graph'
    def replace_plan(value):
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if key == 'execution_plan': value[key] = deepcopy(plan)
                else: replace_plan(item)
        elif isinstance(value, list):
            for item in value: replace_plan(item)
    replace_plan(prepared)
    document['artifact_hash'] = canonical_sha256(document['artifact'])
    (directory / 'preview.json').write_bytes(canonical_json_bytes(document))
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    previous = ''
    for event in events:
        event['artifact_hash'] = document['artifact_hash']
        if event['event_type'] == 'verification_recorded':
            for assertion in event['details']['verification']['assertions']:
                if assertion.get('kind') == 'compound_path_context':
                    assertion['evidence']['sha256'] = canonical_sha256(plan['path_context'])
                elif assertion.get('kind') == 'compound_child_observation':
                    proof = assertion['evidence']; proof['path_context_sha256'] = canonical_sha256(plan['path_context'])
                    proof['phase_args_sha256'] = canonical_sha256(plan['calls'][proof['index']]['args'])
        event['previous_event_hash'] = previous; event.pop('event_hash')
        event['event_hash'] = previous = canonical_sha256(event)
    (directory / 'events.jsonl').write_bytes(b''.join(canonical_json_bytes(event) + b'\n' for event in events))
    record = json.loads((directory / 'state.json').read_text());record.update(artifact_hash=document['artifact_hash'], last_event_hash=previous)
    (directory / 'state.json').write_bytes(canonical_json_bytes(record))
    rejected = _reject_created_graph_receipt(task, source)
    assert any(word in json.dumps(rejected) for word in ('context', 'ancestor', 'phase args')), rejected


def test_created_graph_undo_checks_absence_at_original_path_after_parent_restoration(tmp_path):
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task, _, _, _ = _created_graph_history_case(tmp_path, compound=True, prepared_only=True)
    _install_created_graph_rename_client(task)
    source, before, after = _compound_from_graph_task(task, notes_id=SECOND, companion='object.setName')
    original = task.call
    def surviving_path(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.undo.undo':
            row = deepcopy(next(row for row in after.values() if row['name'] == 'Wind'))
            row.update(id='{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}', path=r'\Actor-Mixer Hierarchy\Default Work Unit\Container\Inner\Wind')
            task.objects[row['id']] = row
        return result
    task.call = surviving_path
    tx = _created_leaf_history_preview(task, source)
    assert task.run('execute', tx)[0] == 0
    code, rejected = task.run('verify', tx)
    assert code == 2 and rejected['verified'] is False, rejected
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.undo.undo']) == 1


def test_created_graph_compound_final_rename_collision_is_rejected_before_write(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND, PROJECT_GROUP
    def setup(task):
        task.objects[PROJECT_GROUP] = {'id': PROJECT_GROUP, 'name': 'Sibling', 'type': 'WorkUnit',
            'path': r'\Actor-Mixer Hierarchy\Sibling', 'notes': 'Keep sibling'}
    task, _, _, _ = _created_graph_history_case(tmp_path, compound=True, prepared_only=True, setup=setup)
    rejected = _compound_from_graph_task(task, notes_id=SECOND, companion='object.setName',
        additional_rename_id=PROJECT_GROUP, additional_rename_name='Renamed parent',
        expected_error='UNDO_GROUP_GRAPH_PATH_DEPENDENCY_UNPROVEN')
    assert 'collision' in rejected['message'], rejected
    assert not any(row[0] in {'ak.wwise.core.undo.beginGroup', 'ak.wwise.core.object.create'} for row in task.calls)


def test_created_graph_ancestor_chain_mismatch_stops_before_begin(tmp_path):
    task, rejected = _created_graph_higher_ancestor_source(tmp_path, bad_ancestry=True)
    assert 'GUID' in rejected['message'], rejected
    assert not any(row[0] in {'ak.wwise.core.undo.beginGroup', 'ak.wwise.core.object.create'} for row in task.calls)


def test_created_graph_ancestor_aggregate_identity_bound_stops_before_begin(tmp_path, monkeypatch):
    from wwise_waapi import object_graph_paths
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND, PROJECT_GROUP
    def setup(task):
        task.objects[PROJECT_GROUP] = {'id': PROJECT_GROUP, 'name': 'Sibling', 'type': 'WorkUnit',
            'path': r'\Actor-Mixer Hierarchy\Sibling', 'notes': 'Keep sibling'}
    task, _, _, _ = _created_graph_history_case(tmp_path, compound=True, prepared_only=True, setup=setup)
    monkeypatch.setattr(object_graph_paths, 'MULTI_IDENTITY_READ_MAX_IDS', 1)
    rejected = _compound_from_graph_task(task, notes_id=SECOND, companion='object.setName', additional_rename_id=PROJECT_GROUP,
        expected_error='UNDO_GROUP_GRAPH_PATH_DEPENDENCY_UNPROVEN')
    assert 'bound' in rejected['message'], rejected
    assert not any(row[0] == 'ak.wwise.core.undo.beginGroup' for row in task.calls)


def test_created_graph_ancestor_false_success_cannot_keep_old_descendant_path(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task, _, _, _ = _created_graph_history_case(tmp_path, compound=True, prepared_only=True)
    _install_created_graph_rename_client(task)
    original = task.call
    def stale_path(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.object.setName':
            next(row for row in task.objects.values() if row['name'] == 'Wind')['path'] = r'\Actor-Mixer Hierarchy\Default Work Unit\Container\Inner\Wind'
        return result
    task.call = stale_path
    source, _, _ = _compound_from_graph_task(task, notes_id=SECOND, companion='object.setName', expected_verified=False)
    assert task.run('transaction-show', source)[1]['state'] == 'verification_failed'
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.create']) == 1
    assert not any(row[0] in {'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'} for row in task.calls)


def test_created_graph_parent_object_set_rename_verifies_final_created_child_closure(tmp_path):
    task, source, before, after = _created_graph_higher_ancestor_source(tmp_path, rename_parent=True)
    for direction in ('undo', 'redo'):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run('execute', tx)[0] == 0
        code, verified = task.run('verify', tx)
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects == (before if direction == 'undo' else after)


def test_created_graph_missing_original_parent_fact_cannot_claim_complete_ancestry(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task, _, _, _ = _created_graph_history_case(tmp_path, compound=True, prepared_only=True)
    _install_created_graph_rename_client(task)
    original = task.call
    def missing_parent(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.object.get':
            for row in result.get('return', []):
                if row['id'] == SECOND: row.pop('parent', None)
        return result
    task.call = missing_parent
    source, _, _ = _compound_from_graph_task(task, notes_id=SECOND, companion='object.setName', expected_verified=False)
    code, shown = task.run('transaction-show', source)
    assert code == 0 and shown['state'] == 'verification_failed', shown
    verification = next(row['details']['verification'] for row in shown['events'] if row['event_type'] == 'verification_recorded')
    witness = next(row for row in verification['assertions'] if row.get('kind') == 'compound_path_context')
    assert witness['passed'] is False and witness['evidence']['missing_original_parent_facts'] == [SECOND]
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.create']) == 1


def test_created_graph_history_stale_renamed_parent_stops_before_native_action(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task, source, _, _ = _created_graph_higher_ancestor_source(tmp_path, rename_parent=True)
    tx = _created_leaf_history_preview(task, source)
    task.objects[SECOND]['path'] = r'\Actor-Mixer Hierarchy\Unreviewed parent'
    code, rejected = task.run('execute', tx)
    assert code == 2, rejected
    assert not any(row[0] in {'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'} for row in task.calls)


def test_created_graph_external_reference_ancestor_rename_activates_independent_target_history(tmp_path):
    _exercise_created_graph_internal_reference_history(tmp_path, '2025.1', compound=True,
        external=True, external_ancestor_only=True)


def test_prior_notes_exact_existing_rename_and_dependent_graph_have_owned_history(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND
    task, source, before, after = _exercise_created_graph_internal_reference_history(
        tmp_path, '2025.1', compound=True, creation_first=False, external=True,
        rename_operation='object.set', notes_child_order='before')
    assert before[SECOND]['notes'] == 'Keep buses'
    assert after[SECOND]['notes'] == 'Earlier declared notes'
    assert after[SECOND]['name'] == 'Renamed parent'


@pytest.mark.parametrize('order,operation', [('before', 'object.set'), ('after', 'object.setNotes'), ('after', 'object.set')])
def test_exact_ancestor_rename_keeps_notes_child_phase_and_final_names(tmp_path, order, operation):
    _exercise_created_graph_internal_reference_history(tmp_path, '2025.1', compound=True,
        creation_first=False, external=True, rename_operation='object.set',
        notes_child_order=order, notes_child_operation=operation)


@pytest.mark.parametrize('fault', ['ignored-notes', 'unrelated-notes', 'premature-phase-name'])
def test_exact_ancestor_notes_history_cannot_hide_false_effects(tmp_path, fault):
    from tests.unit.test_object_graph_owned_choices_gateway import SECOND, ROOT
    task, source, before, shown = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, creation_first=False, external=True, rename_operation='object.set',
        notes_child_order='before', notes_child_operation='object.set' if fault == 'premature-phase-name' else 'object.setNotes',
        prepared_only=True)
    original = task.call
    def damaged(uri, args=None, options=None):
        result = original(uri, args, options)
        if fault == 'ignored-notes' and uri.endswith('object.setNotes'):
            task.objects[SECOND]['notes'] = before[SECOND]['notes']
        elif fault == 'unrelated-notes' and uri.endswith('undo.endGroup'):
            task.objects[ROOT]['notes'] = 'Unrequested notes'
        elif fault == 'premature-phase-name' and uri.endswith('object.set') and 'name' not in args['objects'][0]:
            result['objects'][0]['name'] = 'Renamed parent'
        return result
    task.call = damaged
    assert task.run('confirm', source, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert task.run('execute', source)[0] == 0
    code, failed = task.run('verify', source)
    assert code == 2 and failed['verified'] is False, failed
    _reject_created_graph_receipt(task, source)


def test_exact_ancestor_rename_keeps_declared_notes_on_retained_existing_child(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import ROOT
    task, source, before, after = _exercise_created_graph_internal_reference_history(
        tmp_path, '2025.1', compound=True, creation_first=False, external=True,
        rename_operation='object.set', notes_child_order='before', notes_child_id=ROOT)
    assert before[ROOT]['notes'] == 'Keep external'
    assert after[ROOT]['notes'] == 'Earlier declared notes'
    assert after[ROOT]['name'] == before[ROOT]['name']
    assert after[ROOT]['path'] == r'\Master-Mixer Hierarchy\Renamed parent\External'


def test_compound_render_owner_exact_rename_restores_full_chain_and_history(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT, CHILD
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT
    task, _, _, _, _ = _render_history_case(tmp_path, compound=True)
    _install_created_graph_rename_client(task)
    source, before, after = _compound_from_graph_task(task, notes_id=FIRST, companion='object.setName')
    assert after[FIRST]['name'] == 'Renamed parent'
    assert after[ROOT]['path'] == r'\Actor-Mixer Hierarchy\Default Work Unit\Renamed parent\Slot'
    assert after[ROOT]['@Render'] is True and after[CHILD]['@Render'] is True
    assert after[ROOT]['@Bypass'] == before[ROOT]['@Bypass']
    assert after[ROOT]['@Effect'] == after[CHILD]['@Effect'] == {'id': EFFECT}
    for direction, expected in (('undo', before), ('redo', after)):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run('execute', tx)[0] == 0
        code, verified = task.run('verify', tx)
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects == expected


def test_compound_render_retained_effect_ancestor_rename_activates_full_history_context(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT, CHILD
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT, EFFECT_PARENT
    task, _, _, _, _ = _render_history_case(tmp_path, compound=True)
    _install_created_graph_rename_client(task)
    source, before, after = _compound_from_graph_task(task, notes_id=EFFECT_PARENT, companion='object.setName')
    assert after[FIRST] == before[FIRST]  # No Render owner/name dependency activates this context.
    assert after[EFFECT]['path'] == r'\Effects\Renamed parent\Existing Effect'
    assert after[EFFECT]['notes'] == before[EFFECT]['notes']
    assert after[ROOT]['@Render'] is True and after[CHILD]['@Render'] is True
    for direction, expected in (('undo', before), ('redo', after)):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run('execute', tx)[0] == 0
        code, verified = task.run('verify', tx)
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects == expected


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2025.1'])
def test_compound_render_rename_first_preserves_distinct_models(tmp_path, version):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT, CHILD
    task, _, _, _, _ = _render_history_case(tmp_path, version=version, compound=True,
        opaque_members=version == '2025.1')
    _install_created_graph_rename_client(task)
    original = task.call
    def owner_labels(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.setName'):
            for row in task.objects.values():
                if row.get('owner', {}).get('id') == args['object'] and 'name' in row['owner']:
                    row['owner']['name'] = args['value']
        return result
    task.call = owner_labels
    source, before, after = _compound_from_graph_task(task, notes_id=FIRST,
        companion='object.setName', creation_first=False)
    assert after[FIRST]['name'] == 'Renamed parent'
    if version == '2025.1':
        for identity in (ROOT, CHILD):
            assert after[identity]['path'] == before[identity]['path']
            assert after[identity]['owner'] == {'id': FIRST, 'name': 'Renamed parent'}
            assert after[identity]['@Render'] is True
    else:
        assert after[FIRST]['@RenderEffect0'] is True and after[FIRST]['@RenderEffect1'] is True
    if version == '2021.1':
        code, unavailable = task.run('draft-start', 'ak.wwise.core.undo.undo')
        assert code == 2 and '2021.1' in json.dumps(unavailable), unavailable
        return
    for direction, expected in [('undo', before), *([('redo', after)] if version == '2025.1' else [])]:
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run('execute', tx)[0] == 0
        code, verified = task.run('verify', tx)
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects == expected


@pytest.mark.parametrize('fault', ['member-notes', 'target-class', 'order', 'derived-render'])
def test_compound_render_rename_cannot_hide_unrequested_full_model_changes(tmp_path, fault):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT
    task, _, _, _, _ = _render_history_case(tmp_path, compound=True)
    _install_created_graph_rename_client(task)
    source, before, shown = _compound_from_graph_task(task, notes_id=FIRST,
        companion='object.setName', prepared_only=True)
    original = task.call
    def damaged(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('undo.endGroup'):
            if fault == 'member-notes': task.objects[ROOT]['notes'] = 'Undeclared slot note'
            elif fault == 'target-class': task.objects[EFFECT]['classId'] = True
            elif fault == 'order': task.objects[FIRST]['@Effects'].reverse()
            else: task.objects[ROOT]['@Render'] = False  # Selected later slot remains true.
        return result
    task.call = damaged
    assert task.run('confirm', source, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert task.run('execute', source)[0] == 0
    code, rejected = task.run('verify', source)
    assert code == 2 and rejected['verified'] is False, rejected
    _reject_created_graph_receipt(task, source)


@pytest.mark.parametrize('missing', ['owner', 'target'])
def test_compound_render_receipt_rejects_resealed_missing_required_identity_context(tmp_path, missing):
    from copy import deepcopy
    from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST
    from tests.unit.test_list_merge_existing_conditions_gateway import EFFECT, EFFECT_PARENT
    task, _, _, _, _ = _render_history_case(tmp_path, compound=True)
    _install_created_graph_rename_client(task)
    source, _, _ = _compound_from_graph_task(task,
        notes_id=FIRST if missing == 'owner' else EFFECT_PARENT, companion='object.setName')
    directory = task.path / 'state' / 'transactions' / source
    document = json.loads((directory / 'preview.json').read_text())
    prepared = document['artifact']['prepared_operation']
    plan = prepared['pre_state']['execution_plan']
    omitted = FIRST if missing == 'owner' else EFFECT
    snapshots = plan['path_context']['snapshots']
    assert any(row['id'] == omitted for row in snapshots)
    plan['path_context']['snapshots'] = [row for row in snapshots if row['id'] != omitted]
    def replace_plan(value):
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if key == 'execution_plan': value[key] = deepcopy(plan)
                else: replace_plan(item)
        elif isinstance(value, list):
            for item in value: replace_plan(item)
    replace_plan(prepared)
    document['artifact_hash'] = canonical_sha256(document['artifact'])
    (directory / 'preview.json').write_bytes(canonical_json_bytes(document))
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    previous = ''
    for event in events:
        event['artifact_hash'] = document['artifact_hash']
        if event['event_type'] == 'verification_recorded':
            for assertion in event['details']['verification']['assertions']:
                if assertion.get('kind') == 'compound_path_context':
                    assertion['evidence']['sha256'] = canonical_sha256(plan['path_context'])
                elif assertion.get('kind') == 'compound_child_observation':
                    assertion['evidence']['path_context_sha256'] = canonical_sha256(plan['path_context'])
        event['previous_event_hash'] = previous
        event.pop('event_hash')
        event['event_hash'] = previous = canonical_sha256(event)
    (directory / 'events.jsonl').write_bytes(b''.join(canonical_json_bytes(event) + b'\n' for event in events))
    record = json.loads((directory / 'state.json').read_text())
    record.update(artifact_hash=document['artifact_hash'], last_event_hash=previous)
    (directory / 'state.json').write_bytes(canonical_json_bytes(record))
    rejected = _reject_created_graph_receipt(task, source)
    assert 'context' in json.dumps(rejected).lower(), rejected


def test_compound_render_receipt_requires_its_exact_parent_context_association(tmp_path):
    from wwise_waapi.canonical import canonical_sha256
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST
    task, _, _, _, _ = _render_history_case(tmp_path, compound=True)
    _install_created_graph_rename_client(task)
    source, _, _ = _compound_from_graph_task(task, notes_id=FIRST, companion='object.setName')
    def wrong_context(verification):
        assertions = verification['assertions']
        actual, = [row for row in assertions if row.get('kind') == 'effect_render_chain_observation']
        actual['evidence']['compound_path_context_sha256'] = '0' * 64
        for row in assertions:
            if row.get('kind') == 'compound_child_observation':
                bounds = row['evidence']['assertions']
                bounds['sha256'] = canonical_sha256(assertions[bounds['start']:bounds['start'] + bounds['count']])
    _rewrite_created_graph_verification(task, source, wrong_context)
    rejected = _reject_created_graph_receipt(task, source)
    assert 'Render observation differs from its sealed parent identity context' in json.dumps(rejected), rejected


@pytest.mark.parametrize('contradictory_class_type', [False, True], ids=['exact-reflection', 'contradictory-type'])
def test_render_graph_revalidation_preserves_original_retained_target_before_declared_rename_and_notes(tmp_path, contradictory_class_type):
    from copy import deepcopy
    from tests.unit.test_list_merge_existing_conditions_gateway import list_task, select_field, EFFECT
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, ROOT, CHILD
    task, _ = list_task(tmp_path, operation='object.set')
    # Exact getTypes row from the pinned 2025.1 object-types inventory.
    task.types.append({'name': 'Wwise Meter', 'classId': 8454147,
        'type': 'Source' if contradictory_class_type else 'Effect'})
    task.require_class_projection = True
    before = deepcopy(task.objects)
    after = None
    original = task.call
    writes = []
    def call(uri, args=None, options=None):
        nonlocal after
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': True}
        if uri in {'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            task.objects = deepcopy(before if uri.endswith('.undo') else after)
            return {}
        if uri == 'ak.wwise.core.object.set':
            writes.append(deepcopy(args))
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            task.objects[ROOT]['@Render'] = task.objects[CHILD]['@Render'] = True
            effect = task.objects[EFFECT]
            effect.update(name='Renamed effect', notes='Declared effect notes',
                path=r'\Effects\Default Work Unit\Renamed effect')
            after = deepcopy(task.objects)
            return {'objects': [{'id': row['object'], 'name': task.objects[row['object']]['name']}
                for row in args['objects']]}
        result = original(uri, args, options)
        if uri.endswith('getProjectInfo'):
            result.update(currentPlatformId='{44444444-4444-4444-4444-444444444444}', platforms=[
                {'id': '{44444444-4444-4444-4444-444444444444}', 'name': 'Windows'}])
        return result
    task.call = call
    slot = task.bind(CHILD)
    render = select_field(task, owner=slot, token='Render')
    assert task.step('draft-declare-existing', '--declaration-id', 'render', '--object-handle', slot,
        '--field-value', render, 'true')[0] == 0
    target = task.bind(EFFECT)
    assert task.step('draft-declare-existing', '--declaration-id', 'effect', '--object-handle', target,
        '--field', 'new_name', 'Renamed effect', '--field', 'notes', 'Declared effect notes')[0] == 0
    source, shown = task.preview()
    code, verified = task.finish(source, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(writes) == 1
    assert task.objects[FIRST] == before[FIRST]
    assert task.objects[EFFECT] == {**before[EFFECT], 'name': 'Renamed effect',
        'path': r'\Effects\Default Work Unit\Renamed effect', 'notes': 'Declared effect notes'}
    assert task.objects[ROOT]['@Render'] is True and task.objects[CHILD]['@Render'] is True
    if contradictory_class_type:
        rejected = _reject_created_graph_receipt(task, source)
        assert 'Existing-field receipt original view/before/verified-after observations are unavailable' in rejected['message']
        return
    for direction, expected in (('undo', before), ('redo', after)):
        tx = _created_leaf_history_preview(task, source, direction)
        assert task.run('execute', tx)[0] == 0
        code, verified = task.run('verify', tx)
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects == expected


def test_render_source_without_compound_context_rejects_undeclared_opaque_member_owner_path_change(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, SECOND
    task, source, _, _, _ = _render_history_case(tmp_path, prepared_only=True, opaque_members=True)
    original = task.call
    def changed_ancestor(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.object.setProperty':
            task.objects[SECOND].update(name='Unexpected ancestor', path=r'\Actor-Mixer Hierarchy\Unexpected ancestor')
            task.objects[FIRST]['path'] = r'\Actor-Mixer Hierarchy\Unexpected ancestor\Sender'
        return result
    task.call = changed_ancestor
    assert task.run('confirm', source, '--confirmation-token', task.source_preview['confirmation']['token'])[0] == 0
    assert task.run('execute', source)[0] == 0
    code, rejected = task.run('verify', source)
    assert code == 2 and rejected['verified'] is False, rejected
    observations = [row for row in rejected['verification']['assertions']
        if row.get('kind') == 'effect_render_chain_observation']
    assert len(observations) == 1 and observations[0]['evidence']['source_matches'] is False, observations


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('creation_first', [False, True])
def test_compound_native_named_set_graph_binds_actual_result_before_reference_and_history(tmp_path, version, creation_first):
    task, source, before, after = _exercise_created_graph_internal_reference_history(tmp_path, version,
        compound=True, creation_first=creation_first, external=True, native_rename=True)
    assert next(row for row in after.values() if row['name'] == 'Routing19')['path'].endswith(r'\Renamed parent\Routing19')
    assert after['{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}']['notes'] == 'Keep collision'
    calls = [row for row in task.calls if row[0] == 'ak.wwise.core.object.set']
    assert len(calls) == 2
    assert '_waapi_' not in json.dumps(calls)


def test_2021_native_named_set_graph_and_history_keep_explicit_pinned_boundary(tmp_path):
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask
    task = OwnedGraphTask(tmp_path, '2021.1', 'object.create')
    for operation in ('object.set', 'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'):
        code, rejected = task.run('draft-start', operation)
        assert code == 2 and '2021.1' in json.dumps(rejected), rejected
    assert not task.calls


@pytest.mark.parametrize('fault', ['collision-drift', 'duplicate-result', 'missing-child', 'wrong-class',
    'wrong-parent', 'name-disagreement', 'receiver-metadata', 'changed-collision', 'lost-create-ack', 'lost-reference-ack'])
def test_native_named_set_graph_stops_bad_association_without_dependent_write_or_retry(tmp_path, fault):
    from copy import deepcopy
    task, source, before, shown = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, creation_first=False, external=True, native_rename=True, prepared_only=True)
    code, confirmed = task.run('confirm', source, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    original = task.call
    if fault == 'collision-drift':
        task.objects['{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}']['notes'] = 'Unreviewed change'
    def damaged(uri, args=None, options=None):
        if fault == 'receiver-metadata' and uri.endswith('getPropertyInfo') and args.get('object') == '{88888888-8888-8888-8888-888888888888}':
            return {**original(uri, args, options), 'type': 'String'}
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            creation = any('children' in item for item in args['objects'])
            if creation:
                root = result['objects'][0]['children'][0]
                if fault == 'duplicate-result':
                    root['children'].append(deepcopy(root['children'][0]))
                elif fault == 'missing-child':
                    root['children'].pop()
                elif fault == 'wrong-class':
                    task.objects['{77777777-7777-7777-7777-777777777777}']['classId'] = 1376272
                elif fault == 'wrong-parent':
                    task.objects['{77777777-7777-7777-7777-777777777777}']['parent'] = {'id': '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'}
                elif fault == 'name-disagreement':
                    root['name'] = 'Routing20'
                elif fault == 'changed-collision':
                    task.objects['{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}']['notes'] = 'Unexpected write'
                elif fault == 'lost-create-ack':
                    raise TimeoutError('Creation acknowledgement lost')
            elif fault == 'lost-reference-ack':
                raise TimeoutError('Reference acknowledgement lost')
        return result
    task.call = damaged
    code, rejected = task.run('execute', source)
    assert code == 2, rejected
    assert rejected.get('executed') is (fault != 'collision-drift'), rejected
    writes = [row for row in task.calls if row[0] == 'ak.wwise.core.object.set']
    assert len(writes) == (0 if fault == 'collision-drift' else 2 if fault == 'lost-reference-ack' else 1), rejected
    if fault != 'collision-drift':
        assert rejected['state'] == 'indeterminate' and rejected['automatic_retry'] is False, rejected
    count = len(task.calls)
    assert task.run('execute', source)[0] == 2
    assert not any(row[0] == 'ak.wwise.core.object.set' for row in task.calls[count:])


def test_native_named_set_graph_false_reference_effect_cannot_be_verified_or_replayed(tmp_path):
    task, source, before, shown = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, creation_first=False, external=True, native_rename=True, prepared_only=True)
    assert task.run('confirm', source, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert task.run('execute', source)[0] == 0
    task.objects['{88888888-8888-8888-8888-888888888888}']['@UserAuxSend0'] = {'id': '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'}
    code, failed = task.run('verify', source)
    assert code == 2 and failed['verified'] is False, failed
    count = len(task.calls)
    assert task.run('execute', source)[0] == 2
    assert not any(row[0] == 'ak.wwise.core.object.set' for row in task.calls[count:])


@pytest.mark.parametrize('creation_first', [True, False])
def test_native_named_graph_exact_object_set_ancestor_rename_closes_actual_created_child_roster(tmp_path, creation_first):
    task, source, before, after = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, creation_first=creation_first, external=True, native_rename=True, rename_operation='object.set')
    assert next(row for row in after.values() if row['name'] == 'Routing19')['path'].endswith(r'\Renamed parent\Routing19')
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.set']) == 3


@pytest.mark.parametrize('version,creation_first,rename_policy', [('2022.1', False, False), ('2025.1', False, False), ('2025.1', True, True)])
def test_compound_set_graph_without_collision_keeps_public_stage_and_owned_history(tmp_path, version, creation_first, rename_policy):
    task, source, before, after = _exercise_created_graph_internal_reference_history(tmp_path, version,
        compound=True, creation_first=creation_first, external=True, set_graph=True, collision=False, native_rename=rename_policy)
    created = after['{66666666-6666-6666-6666-666666666666}']
    assert created['name'] == 'Routing' and created['path'].endswith(r'\Renamed parent\Routing')
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.set']) == 2


def test_compound_set_graph_without_result_reference_still_owns_complete_creation_history(tmp_path):
    task, source, before, after = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, creation_first=True, external=True, set_graph=True, collision=False, planned_reference=False)
    code, shown = task.run('transaction-show', source)
    assert code == 0, shown
    child = next(call['prepared_operation'] for call in shown['artifact']['prepared_operation']['pre_state']['execution_plan']['calls']
        if 'owned_result_stages' in call['prepared_operation']['pre_state'])
    assert child['semantic_preview']['envelope']['metadata']['result_reference_execution']['stage_count'] == 1
    assert after['{77777777-7777-7777-7777-777777777777}']['@UserAuxSend0'] == {'id': '{33333333-3333-3333-3333-333333333333}'}
    assert '@UserAuxSend0' not in after['{88888888-8888-8888-8888-888888888888}']
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.set']) == 1


def test_compound_set_fieldless_graph_history_uses_truthful_no_platform_view(tmp_path):
    task, source, before, after = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, creation_first=False, external=False, set_graph=True, collision=False,
        planned_reference=False, platform_certified=False)
    assert len(after) - len(before) == 3


@pytest.mark.parametrize('version,creation_first', [('2022.1', False), ('2023.1', True), ('2024.1', False), ('2025.1', True)])
def test_compound_two_collision_roots_bind_each_actual_result_before_cross_tree_reference_and_history(tmp_path, version, creation_first):
    task, source, before, after = _exercise_created_graph_internal_reference_history(tmp_path, version,
        compound=True, creation_first=creation_first, external=True, native_rename=True, multiple_roots=True)
    assert after['{66666666-6666-6666-6666-666666666666}']['name'] == 'Routing19'
    assert after['{99999999-9999-9999-9999-999999999999}']['name'] == 'Backup37'
    assert after['{88888888-8888-8888-8888-888888888888}']['@UserAuxSend0'] == {'id': '{77777777-7777-7777-7777-777777777777}'}
    assert after['{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}']['notes'] == 'Keep second collision'
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.set']) == 3
    code, shown = task.run('transaction-show', source)
    assert code == 0, shown
    child = next(call['prepared_operation'] for call in shown['artifact']['prepared_operation']['pre_state']['execution_plan']['calls']
        if 'owned_result_stages' in call['prepared_operation']['pre_state'])
    assert child['semantic_preview']['envelope']['metadata']['result_reference_execution']['stage_count'] == 3
    execution = next(event['details']['dispatch_result'] for event in shown['events'] if event['event_type'] == 'execution_completed')
    actual = next(phase['dispatch_result'] for phase in execution['result']['phases'] if 'owned_result_execution' in phase['dispatch_result'])
    stages = actual['owned_result_execution']['stages']
    assert actual['result'] == stages[0]['dispatch_result']['result']
    assert [stage['dispatch_result']['result']['objects'][0]['children'][0]['id'] for stage in stages[:2]] == [
        '{66666666-6666-6666-6666-666666666666}', '{99999999-9999-9999-9999-999999999999}']


@pytest.mark.parametrize('fault', ['earlier-target-drift', 'earlier-owned-extra-child', 'earlier-owned-class-drift', 'reused-guid', 'prewrite-parent-drift', 'second-collision-drift', 'prewrite-second-collision-drift'])
def test_two_owned_creation_stages_stop_bad_association_before_reference_and_never_retry(tmp_path, fault):
    task, source, before, shown = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, creation_first=False, external=True, native_rename=True, multiple_roots=True, prepared_only=True)
    assert task.run('confirm', source, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    original = task.call
    creations = []
    def damaged(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.set') and any('children' in item for item in args['objects']):
            creations.append(args)
            if len(creations) == 1 and fault == 'second-collision-drift':
                task.objects['{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}']['notes'] = 'Unexpected collision edit'
            if len(creations) == 2:
                if fault == 'earlier-target-drift':
                    task.objects['{77777777-7777-7777-7777-777777777777}']['path'] += 'Changed'
                elif fault == 'earlier-owned-extra-child':
                    identity = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'
                    parent = task.objects['{66666666-6666-6666-6666-666666666666}']
                    task.objects[identity] = {'id': identity, 'name': 'Rogue', 'type': 'AuxBus', 'classId': 3997712,
                        'parent': {'id': parent['id']}, 'path': parent['path'] + r'\Rogue', 'notes': ''}
                elif fault == 'earlier-owned-class-drift':
                    task.objects['{66666666-6666-6666-6666-666666666666}']['classId'] = 3997712
                elif fault == 'reused-guid':
                    result['objects'][0]['children'][0]['id'] = '{66666666-6666-6666-6666-666666666666}'
        return result
    task.call = damaged
    if fault == 'prewrite-parent-drift':
        from tests.unit.test_object_graph_owned_choices_gateway import SECOND
        task.objects[SECOND]['notes'] = 'Changed after Preview'
    if fault == 'prewrite-second-collision-drift':
        task.objects['{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}']['notes'] = 'Changed after Preview'
    code, failed = task.run('execute', source)
    assert code == 2, failed
    writes = [row for row in task.calls if row[0] == 'ak.wwise.core.object.set']
    assert len(writes) == (0 if fault.startswith('prewrite-') else 1 if fault == 'second-collision-drift' else 2), failed
    assert all(any('children' in item for item in args['objects']) for _, args, _ in writes)
    if not fault.startswith('prewrite-'):
        assert failed['state'] == 'indeterminate' and failed['automatic_retry'] is False, failed
    if fault == 'earlier-owned-extra-child':
        code, full = task.run('transaction-show', source)
        assert code == 0, full
        execution = next(event['details']['compound_execution'] for event in full['events'] if event['event_type'] == 'execution_indeterminate')
        actual = execution['failed_phase']['dispatch_result']
        records = actual['owned_result_execution']['creation_bindings'][1]['readbacks']
        membership = [row for row in records if row['args'] == {'from': {'id': ['{66666666-6666-6666-6666-666666666666}']},
            'transform': [{'select': ['children']}]}]
        assert len(membership) == 1
        assert {row['id'] for row in membership[0]['result']['return']} == {
            '{77777777-7777-7777-7777-777777777777}', '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'}
    count = len(task.calls)
    assert task.run('execute', source)[0] == 2
    assert not any(uri == 'ak.wwise.core.object.set' for uri, _, _ in task.calls[count:])


def test_split_creation_verification_requires_retained_complete_earlier_owned_membership(tmp_path):
    from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
    task, source, before, shown = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, creation_first=False, external=True, native_rename=True, multiple_roots=True, prepared_only=True)
    assert task.run('confirm', source, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert task.run('execute', source)[0] == 0
    code, full = task.run('transaction-show', source)
    assert code == 0, full
    events = full['events']
    execution = next(event['details']['dispatch_result'] for event in events if event['event_type'] == 'execution_completed')
    actual = next(phase['dispatch_result'] for phase in execution['result']['phases'] if 'owned_result_execution' in phase['dispatch_result'])
    records = actual['owned_result_execution']['creation_bindings'][1]['readbacks']
    membership = [row for row in records if row['args'] == {'from': {'id': ['{66666666-6666-6666-6666-666666666666}']},
        'transform': [{'select': ['children']}]}]
    assert len(membership) == 1
    records.remove(membership[0])
    # A valid journal hash cannot replace the missing semantic ownership read.
    previous = ''
    for event in events:
        event['previous_event_hash'] = previous
        event.pop('event_hash')
        event['event_hash'] = previous = canonical_sha256(event)
    directory = task.path / 'state' / 'transactions' / source
    (directory / 'events.jsonl').write_bytes(b''.join(canonical_json_bytes(event) + b'\n' for event in events))
    state_path = directory / 'state.json'
    record = json.loads(state_path.read_text())
    record['last_event_hash'] = previous
    state_path.write_bytes(canonical_json_bytes(record))
    count = len([row for row in task.calls if row[0] == 'ak.wwise.core.object.set'])
    code, failed = task.run('verify', source)
    assert code == 2 and failed.get('verified') is not True, failed
    assert 'Owned creation stage lost its exact read association' in json.dumps(failed), failed
    assert task.run('execute', source)[0] == 2
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.set']) == count


def test_compound_nested_duplicate_siblings_keep_occurrence_reference_and_owned_history(tmp_path):
    task, source, before, after = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, native_rename=True, duplicate_siblings=True)
    destination, sender = '{77777777-7777-7777-7777-777777777777}', '{88888888-8888-8888-8888-888888888888}'
    assert after[destination]['name'] == 'Send' and after[sender]['name'] == 'Send37'
    assert after[sender]['@UserAuxSend0'] == {'id': destination}
    assert after[destination]['parent'] == after[sender]['parent'] == {'id': '{66666666-6666-6666-6666-666666666666}'}
    assert after['{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}']['notes'] == before['{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}']['notes']
    writes = [args for uri, args, _ in task.calls if uri == 'ak.wwise.core.object.set']
    assert len(writes) == 4
    assert writes[1]['objects'][0]['object'] == writes[2]['objects'][0]['object'] == '{66666666-6666-6666-6666-666666666666}'
    assert writes[1]['objects'][0]['children'][0]['name'] == writes[2]['objects'][0]['children'][0]['name'] == 'Send'
    assert all('name' not in row for args in writes for row in args['objects'])
    roster = task.source_verification['agent_result']['business_result']['created_objects']
    assert {row['object']['id'] for row in roster} == set(after) - set(before)
    duplicates = [row for row in roster if row['requested_name'] == 'Send']
    assert len(duplicates) == 2 and len({row['result_handle'] for row in duplicates}) == 2
    assert {row['object']['name'] for row in duplicates} == {'Send', 'Send37'}


@pytest.mark.parametrize('shape', ['retained-parent', 'no-reference', 'suffix-like'])
def test_duplicate_rename_source_keeps_each_owned_occurrence_without_path_guessing(tmp_path, shape):
    task, source, before, after = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=shape != 'no-reference', native_rename=True, duplicate_siblings=shape != 'retained-parent',
        multiple_roots=shape == 'retained-parent', retained_duplicates=shape == 'retained-parent',
        suffix_like=shape == 'suffix-like', planned_reference=shape != 'no-reference', source_only=True)
    assert len(after) - len(before) == (4 if shape in {'retained-parent', 'suffix-like'} else 3)
    destination, sender = '{77777777-7777-7777-7777-777777777777}', '{88888888-8888-8888-8888-888888888888}'
    if shape == 'no-reference':
        assert '@UserAuxSend0' not in after[sender]
    else:
        assert after[sender]['@UserAuxSend0'] == {'id': destination}
    if shape == 'retained-parent':
        assert after['{99999999-9999-9999-9999-999999999999}']['name'] == 'Routing83'
    if shape == 'suffix-like':
        assert after[sender]['name'] == 'Send37'
        assert after['{99999999-9999-9999-9999-999999999999}']['name'] == 'Send88'
    code, shown = task.run('transaction-show', source)
    assert code == 0, shown
    execution = next(event['details']['dispatch_result'] for event in shown['events'] if event['event_type'] == 'execution_completed')
    actual = next(row['dispatch_result'] for row in execution['result']['phases'] if 'owned_result_execution' in row['dispatch_result']) if shape != 'no-reference' else execution
    proof = actual['owned_result_execution']
    assert actual['result'] == proof['stages'][0]['dispatch_result']['result']
    assert len(proof['stages']) == (5 if shape == 'suffix-like' else 3)
    assert not any(uri in {'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'} for uri, _, _ in task.calls)


@pytest.mark.parametrize('fault,expected_writes', [('wrong-parent-association', 2), ('reused-owned-guid', 3),
    ('extra-earlier-child', 2), ('changed-owned-parent', 3), ('changed-reference-metadata', 3), ('between-stages-extra-child', 1)])
def test_nested_duplicate_stages_stop_bad_owned_proof_before_reference_without_retry(tmp_path, fault, expected_writes):
    from copy import deepcopy
    task, source, before, shown = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, native_rename=True, duplicate_siblings=True, prepared_only=True)
    assert task.run('confirm', source, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    original = task.call
    writes = []
    injected = False
    root, destination = '{66666666-6666-6666-6666-666666666666}', '{77777777-7777-7777-7777-777777777777}'
    def damaged(uri, args=None, options=None):
        nonlocal injected
        result = original(uri, args, options)
        if (fault == 'between-stages-extra-child' and len(writes) == 1 and not injected
                and uri == 'ak.wwise.core.object.get'
                and args == {'from': {'id': ['{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}']}, 'transform': [{'select': ['children']}]}):
            injected = True
            identity = '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}'
            task.objects[identity] = {'id': identity, 'name': 'Rogue', 'type': 'AuxBus', 'classId': 3997712,
                'parent': {'id': root}, 'path': task.objects[root]['path'] + r'\Rogue', 'notes': ''}
        if uri.endswith('object.set') and any('children' in row for row in args['objects']):
            writes.append(deepcopy(args))
            if len(writes) == 2:
                if fault == 'wrong-parent-association':
                    result['objects'][0]['id'] = '{22222222-2222-2222-2222-222222222222}'
                elif fault == 'extra-earlier-child':
                    identity = '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}'
                    task.objects[identity] = {'id': identity, 'name': 'Rogue', 'type': 'AuxBus', 'classId': 3997712,
                        'parent': {'id': root}, 'path': task.objects[root]['path'] + r'\Rogue', 'notes': ''}
            if len(writes) == 3:
                if fault == 'reused-owned-guid':
                    result['objects'][0]['children'][0]['id'] = destination
                elif fault == 'changed-owned-parent':
                    task.objects[root]['notes'] = 'Unexpected parent edit'
                elif fault == 'changed-reference-metadata':
                    task.metadata['UserAuxSend0']['type'] = 'String'
        return result
    task.call = damaged
    code, failed = task.run('execute', source)
    assert code == 2 and failed['state'] == 'indeterminate' and failed['automatic_retry'] is False, failed
    assert len(writes) == expected_writes
    assert all('@UserAuxSend0' not in row for args in writes for row in args['objects'])
    assert task.run('execute', source)[0] == 2
    assert len(writes) == expected_writes


def test_nested_duplicate_stage_cannot_omit_before_write_roster_read_from_rehashed_receipt(tmp_path):
    from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
    task, source, before, shown = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, native_rename=True, duplicate_siblings=True, prepared_only=True)
    assert task.run('confirm', source, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert task.run('execute', source)[0] == 0
    code, full = task.run('transaction-show', source)
    assert code == 0, full
    events = full['events']
    execution = next(event['details']['dispatch_result'] for event in events if event['event_type'] == 'execution_completed')
    actual = next(phase['dispatch_result'] for phase in execution['result']['phases'] if 'owned_result_execution' in phase['dispatch_result'])
    reads = actual['owned_result_execution']['creation_bindings'][1]['before_readbacks']
    assert len(reads) == 2
    reads.pop()
    previous = ''
    for event in events:
        event['previous_event_hash'] = previous
        event.pop('event_hash')
        event['event_hash'] = previous = canonical_sha256(event)
    directory = task.path / 'state' / 'transactions' / source
    (directory / 'events.jsonl').write_bytes(b''.join(canonical_json_bytes(event) + b'\n' for event in events))
    state_path = directory / 'state.json'
    record = json.loads(state_path.read_text()); record['last_event_hash'] = previous
    state_path.write_bytes(canonical_json_bytes(record))
    count = len([row for row in task.calls if row[0] == 'ak.wwise.core.object.set'])
    code, failed = task.run('verify', source)
    assert code == 2 and failed.get('verified') is not True, failed
    assert 'Owned creation stage lost its exact read association' in json.dumps(failed), failed
    assert task.run('execute', source)[0] == 2
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.set']) == count


def test_create_duplicate_siblings_2021_bind_actual_occurrences_before_closed_reference(tmp_path):
    task, source, before, after = _exercise_created_graph_internal_reference_history(tmp_path, '2021.1',
        native_rename=True, duplicate_siblings=True, create_constructor=True, source_only=True)
    root, destination, sender = ('{66666666-6666-6666-6666-666666666666}',
        '{77777777-7777-7777-7777-777777777777}', '{88888888-8888-8888-8888-888888888888}')
    assert after[sender]['@UserAuxSend0'] == {'id': destination}
    assert after[destination]['name'] == 'Send' and after[sender]['name'] == 'Send37'
    assert after[destination]['parent'] == after[sender]['parent'] == {'id': root}
    creates = [args for uri, args, _ in task.calls if uri == 'ak.wwise.core.object.create']
    assert [row['name'] for row in creates] == ['Routing', 'Send', 'Send']
    assert [row['parent'] for row in creates[1:]] == [root, root]
    assert all('children' not in row for row in creates)
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.setReference']) == 1
    roster = task.source_verification['agent_result']['business_result']['created_objects']
    assert {row['object']['id'] for row in roster} == {root, destination, sender}
    assert len({row['result_handle'] for row in roster}) == 3
    assert task.run('draft-start', 'ak.wwise.core.undo.undo')[0] == 2
    assert task.run('draft-start', 'object.set')[0] == 2


def test_compound_create_duplicate_siblings_reuse_owned_roster_for_undo_redo(tmp_path):
    task, source, before, after = _exercise_created_graph_internal_reference_history(tmp_path, '2025.1',
        compound=True, native_rename=True, duplicate_siblings=True, create_constructor=True)
    destination, sender = '{77777777-7777-7777-7777-777777777777}', '{88888888-8888-8888-8888-888888888888}'
    assert after[sender]['@UserAuxSend0'] == {'id': destination}
    assert after[destination]['name'] == 'Send' and after[sender]['name'] == 'Send37'
    assert after['{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}']['notes'] == 'Keep collision'
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.create']) == 3
    assert [uri for uri, _, _ in task.calls if uri in {'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'}] == [
        'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo']
    assert len(task.source_verification['agent_result']['business_result']['created_objects']) == 3


@pytest.mark.parametrize('version,reference,suffix_like,stage_count', [
    ('2022.1', False, False, 3), ('2023.1', True, False, 4), ('2024.1', True, True, 6)])
def test_create_duplicate_sources_keep_versioned_stage_counts_and_actual_bindings(tmp_path, version, reference, suffix_like, stage_count):
    task, source, before, after = _exercise_created_graph_internal_reference_history(tmp_path, version,
        native_rename=True, duplicate_siblings=True, create_constructor=True, source_only=True,
        planned_reference=reference, suffix_like=suffix_like)
    code, shown = task.run('transaction-show', source)
    assert code == 0, shown
    prepared = shown['artifact']['prepared_operation']
    metadata = prepared['semantic_preview']['envelope']['metadata']['result_reference_execution']
    assert metadata['stage_count'] == stage_count
    execution = next(row['details']['dispatch_result'] for row in shown['events'] if row['event_type'] == 'execution_completed')
    proof = execution['owned_result_execution']
    assert len(proof['stages']) == stage_count
    assert execution['result'] == proof['stages'][0]['dispatch_result']['result']
    assert all('id' not in stage['args'] for stage in proof['stages'])
    destination, sender = '{77777777-7777-7777-7777-777777777777}', '{88888888-8888-8888-8888-888888888888}'
    if reference:
        assert after[sender]['@UserAuxSend0'] == {'id': destination}
    else:
        assert '@UserAuxSend0' not in after[sender]
    if suffix_like:
        assert after['{99999999-9999-9999-9999-999999999999}']['@UserAuxSend0'] == {'id': destination}
        assert len([stage for stage in proof['stages'] if stage['uri'] == 'ak.wwise.core.object.setReference']) == 2
    assert not any(uri.startswith('ak.wwise.core.undo.') for uri, _, _ in task.calls)


@pytest.mark.parametrize('fault,creations,references', [
    ('prewrite-parent-drift', 0, 0), ('reused-owned-guid', 2, 0),
    ('earlier-roster-drift', 2, 0), ('lost-reference-ack', 3, 1)])
def test_create_duplicate_stages_stop_invalid_proof_without_reference_or_retry(tmp_path, fault, creations, references):
    task, source, before, shown = _exercise_created_graph_internal_reference_history(tmp_path, '2021.1',
        native_rename=True, duplicate_siblings=True, create_constructor=True, prepared_only=True)
    assert task.run('confirm', source, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    if fault == 'prewrite-parent-drift':
        task.objects['{22222222-2222-2222-2222-222222222222}']['notes'] = 'Unapproved parent edit'
    original = task.call
    count = 0
    def damaged(uri, args=None, options=None):
        nonlocal count
        result = original(uri, args, options)
        if uri == 'ak.wwise.core.object.create':
            count += 1
            if count == 2 and fault == 'reused-owned-guid':
                result['id'] = '{66666666-6666-6666-6666-666666666666}'
            if count == 2 and fault == 'earlier-roster-drift':
                task.objects['{66666666-6666-6666-6666-666666666666}']['notes'] = 'Unapproved created parent edit'
        if uri == 'ak.wwise.core.object.setReference' and fault == 'lost-reference-ack':
            raise TimeoutError('Reference acknowledgement lost')
        return result
    task.call = damaged
    code, failed = task.run('execute', source)
    assert code == 2, failed
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.create']) == creations
    assert len([row for row in task.calls if row[0] == 'ak.wwise.core.object.setReference']) == references
    if creations:
        assert failed['state'] == 'indeterminate' and failed['automatic_retry'] is False, failed
    else:
        assert failed.get('executed') is not True, failed
    previous = len([row for row in task.calls if row[0] in {'ak.wwise.core.object.create', 'ak.wwise.core.object.setReference'}])
    assert task.run('execute', source)[0] == 2
    assert len([row for row in task.calls if row[0] in {'ak.wwise.core.object.create', 'ak.wwise.core.object.setReference'}]) == previous
