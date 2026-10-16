from __future__ import annotations

import json

import pytest

from test_gateway_connection_binding import BindingClient
from test_gateway_session_context import configured_env, waapi_gateway as gateway
from wwise_waapi.transactions import TransactionStore, new_transaction_id


def legacy_preview(tmp_path, version="2022.1", kind="discard-case-owned-project-copy-and-output-root"):
    env = configured_env(tmp_path, version=version)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    api = "ak.wwise.core.project.save" if version == "2021.1" else "ak.wwise.core.undo.undo"
    code, schema = gateway.execute_gateway(["request-schema", api], env=env)
    assert code == 0, schema
    code, preview = gateway.execute_gateway(schema["continuation"]["gateway_argv"], env=env, client_factory=lambda _: BindingClient(version))
    assert code == 0, preview
    code, shown = gateway.execute_gateway(["transaction-show", preview["transaction_id"]], env=env)
    assert code == 0, shown
    artifact = shown["artifact"]
    artifact["prepared_operation"]["cleanup"] = {
        "kind": kind, "automatic": False,
        "failure_policy": "seal_or_quarantine_failed_sandbox_and_never_reuse",
        "success_policy": "discard_the_complete_case_owned_sandbox",
    }
    artifact["prepared_operation"]["semantic_preview"]["evidence_plan"].append({
        "kind": "readback", "expectation": "create one object under the resolved parent; read back created id/name/type/path and delete it during cleanup if still present",
    })
    artifact["prepared_operation"]["pre_state"]["closed_import_plan"] = {
        "operation_policy": {"import_operation": "replaceExisting", "cleanup_policy": "discard_owned_project_copy; in_place_restore_is_not_claimed", "disposable_project_required": True, "owned_project_copy_required_for_clean_test": True},
    }
    store = TransactionStore(tmp_path / "state")
    legacy_id = new_transaction_id()
    store.create_preview(legacy_id, artifact)
    return env, store, legacy_id


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("kind", [
    "discard-case-owned-project-copy", "discard-case-owned-project-copy-after-replace",
    "discard-case-owned-project-copy-and-output-root", "discard-owned-sandbox-or-restore-captured-fields",
    "restore-rtpc-snapshot-or-discard-owned-sandbox", "none-after-delete",
])
@pytest.mark.parametrize("phase", ["preview", "executed", "verified", "failed", "indeterminate"])
def test_product_summary_retains_outputs_of_historical_previews(tmp_path, version, kind, phase):
    env, store, transaction_id = legacy_preview(tmp_path, version, kind)
    if phase != "preview":
        store.authorize_by_policy(transaction_id, policy="allow_changes", authority="historical-fixture")
        store.begin_execution(transaction_id, expected_authorization="policy_authorized")
        if phase == "failed":
            store.mark_execution_failed(transaction_id)
        elif phase == "indeterminate":
            store.mark_execution_indeterminate(transaction_id)
        else:
            store.mark_executed_unverified(transaction_id)
            if phase == "verified":
                store.record_verification(transaction_id, "verified")
    original_hash = store.verify_artifact(transaction_id)
    code, result = gateway.execute_gateway(["transaction-show", transaction_id, "--summary-only"], env=env)
    assert code == 0, result
    cleanup = result["preview_summary"]["cleanup"]
    assert cleanup["status"] == "not_required"
    assert cleanup["spec"]["project_policy"] == "retain"
    assert cleanup["spec"]["output_policy"] == "retain"
    assert "discard" not in json.dumps(result)
    assert "quarantine" not in json.dumps(result)
    assert store.verify_artifact(transaction_id) == original_hash


def test_full_historical_artifact_is_projected_without_discard_instructions(tmp_path):
    env, store, transaction_id = legacy_preview(tmp_path)
    original_hash = store.verify_artifact(transaction_id)
    code, result = gateway.execute_gateway(["transaction-show", transaction_id], env=env)
    assert code == 0, result
    assert "discard" not in json.dumps(result)
    assert "never_reuse" not in json.dumps(result)
    assert "delete it during cleanup" not in json.dumps(result)
    assert result["artifact_hash"] == original_hash
    assert store.verify_artifact(transaction_id) == original_hash


def test_import_schema_does_not_instruct_disposable_project_cleanup(tmp_path):
    code, result = gateway.execute_gateway(["operation-schema", "audio.import"], env=configured_env(tmp_path))
    assert code == 0, result
    assert "disposable project" not in json.dumps(result)


class CreateClient(BindingClient):
    def call(self, uri, args=None, options=None):
        if uri == "ak.wwise.core.object.getTypes":
            return {"return": [{"classId": 1, "name": "Sound", "type": "Sound"}]}
        if uri == "ak.wwise.core.object.get" and "from type Project" not in args.get("waql", ""):
            if "children" in json.dumps(args) or "Persistent" in json.dumps(args):
                return {"return": []}
            return {"return": [{"id": "{22222222-2222-2222-2222-222222222222}", "name": "Default Work Unit", "type": "WorkUnit", "path": "\\Actor-Mixer Hierarchy\\Default Work Unit"}]}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_new_object_preview_retains_the_created_object(tmp_path, version):
    env = configured_env(tmp_path, version=version)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    client = CreateClient(version)
    code, result = gateway.execute_gateway(["draft-start", "object.create"], env=env)
    assert code == 0, result
    draft_id, authority = result["draft"]["draft_id"], result["task_authority"]
    def step(command, *fields):
        nonlocal result
        code, result = gateway.execute_gateway([command, draft_id, "--task-authority", authority, "--expected-revision", str(result["draft"]["revision"]), *fields], env=env, client_factory=lambda _: client)
        assert code == 0, result
        return result
    bound = step("draft-bind-object", "--object-id", "{22222222-2222-2222-2222-222222222222}")
    step("draft-declare-new", "--declaration-id", "sound", "--parent-handle", bound["bound_object"]["handle"], "--name", "Persistent", "--kind", "sound-sfx")
    step("draft-check")
    preview = step("preview-from-draft")
    assert preview["cleanup"]["status"] == "not_required"
    assert "delete-returned" not in json.dumps(preview)
    assert "delete it during cleanup" not in json.dumps(preview)
    code, full = gateway.execute_gateway(["transaction-show", preview["transaction_id"]], env=env)
    assert code == 0, full
    assert "delete it during cleanup" not in json.dumps(full)
    assert "delete-created" not in json.dumps(full)
    assert "artifact_projection" not in full


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_profiler_pairing_remains_required_after_persistent_project_cleanup(tmp_path, version):
    env = configured_env(tmp_path, version=version)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    code, schema = gateway.execute_gateway(["request-schema", "ak.wwise.core.profiler.startCapture"], env=env)
    assert code == 0, schema
    code, preview = gateway.execute_gateway(schema["continuation"]["gateway_argv"], env=env, client_factory=lambda _: BindingClient(version))
    assert code == 0, preview
    cleanup = preview["cleanup"]
    assert cleanup["status"] == "not_started"
    assert cleanup["projection"]["companion_request"]["api"] == "ak.wwise.core.profiler.stopCapture"
    assert cleanup["projection"]["cleanup_requirement"] == "required_cleanup"
