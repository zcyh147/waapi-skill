"""Version-pinned Save declarations through the public transaction lifecycle."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.support.gateway_config import set_gateway_config
from tests.unit.test_gateway_connection_binding import BindingClient
from tests.unit.test_gateway_session_context import configured_env, waapi_gateway
from tests.unit.test_workflow_source_guard import workflow


SAVE = "ak.wwise.core.project.save"
VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")


class SaveClient(BindingClient):
    def __init__(self, version):
        super().__init__(version)
        self.saves = []

    def call(self, uri, args=None, options=None):
        if uri == SAVE:
            self.saves.append((deepcopy(args), deepcopy(options)))
            return {}
        return super().call(uri, args, options)


class SaveTask:
    def __init__(self, path, version, policy="ask_before_changes"):
        self.env = configured_env(path, version=version)
        self.env["WAAPI_SKILL_STATE_DIR"] = str(path / "state")
        set_gateway_config(self.env, project_modification_policy=policy)
        self.client = SaveClient(version)
        code, self.schema = self.run("request-schema", SAVE)
        assert code == 0, self.schema
        assert self.schema["input_shape"] == "business_declaration"
        code, self.current = self.run(*self.schema["continuation"]["gateway_argv"])
        assert code == 0, self.current
        self.authority = self.current["task_authority"]

    def run(self, *argv):
        return waapi_gateway.execute_gateway(list(argv), env=self.env, client_factory=lambda _: self.client)

    def step(self, command, *fields):
        draft = self.current["draft"]
        code, result = self.run(command, draft["draft_id"], "--task-authority", self.authority,
            "--expected-revision", str(draft["revision"]), *fields)
        if code == 0:
            self.current = result
        return code, result

    def preview(self, *fields):
        for command, values in (("draft-declare-core-plan", fields), ("draft-check", ()),
                ("preview-from-draft", ())):
            code, result = self.step(command, *values)
            assert code == 0, result
        return result


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("policy", ["ask_before_changes", "allow_changes"])
def test_empty_save_plan_executes_once_and_keeps_result_schema_boundary(tmp_path, version, policy):
    task = SaveTask(tmp_path, version, policy)
    preview = task.preview()
    transaction = preview["transaction_id"]
    assert task.client.saves == []
    assert preview["agent_result"]["request"]["arguments"] == {"api": SAVE, "args": {}, "options": {}}
    code, shown = task.run("transaction-show", transaction)
    assert code == 0, shown
    if policy == "ask_before_changes":
        assert preview["state"] == "awaiting_confirmation"
        assert task.run("execute", transaction)[0] == 2
        assert task.client.saves == []
        code, confirmed = task.run("confirm", transaction, "--confirmation-token", shown["confirmation"]["token"])
        assert code == 0, confirmed
    else:
        assert preview["state"] == "policy_authorized"
        assert preview["authorization"]["explicit_confirmation"] is False
    code, executed = task.run("execute", transaction)
    assert code == 0 and executed["state"] == "executed_unverified", executed
    assert task.client.saves == [({}, {})]
    assert task.run("execute", transaction)[0] == 2
    assert task.client.saves == [({}, {})]
    code, verified = task.run("verify", transaction)
    assert code == 0 and verified["state"] == "result_schema_checked", verified
    assert verified["verified"] is False and verified["result_schema_checked"] is True
    assert verified["verification"]["business_state_verified"] is False
    code, after = task.run("transaction-show", transaction)
    assert code == 0, after
    assert after["artifact"] == shown["artifact"]
    assert task.client.saves == [({}, {})]


@pytest.mark.parametrize("version", VERSIONS)
def test_read_only_save_has_no_execution_authority(tmp_path, version):
    task = SaveTask(tmp_path, version, "read_only")
    assert task.step("draft-declare-core-plan")[0] == 0
    assert task.step("draft-check")[0] == 0
    code, result = task.step("preview-from-draft")
    assert code == 2, result
    assert "read_only" in result["message"]
    assert task.client.saves == []


@pytest.mark.parametrize("version", ["2021.1", "2022.1"])
@pytest.mark.parametrize("value", ["true", "false"])
def test_older_save_rejects_checkout_choice_atomically_before_dispatch(tmp_path, version, value):
    task = SaveTask(tmp_path, version)
    before = deepcopy(task.current["draft"])
    code, rejected = task.step("draft-declare-core-plan", "--value", "auto_check_out", value)
    assert code == 2, rejected
    assert task.client.saves == []
    code, inspected = task.run("draft-inspect", before["draft_id"], "--task-authority", task.authority)
    assert code == 0, inspected
    assert inspected["draft"]["revision"] == before["revision"]
    assert task.preview()["state"] == "awaiting_confirmation"
    assert task.client.saves == []


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("value,expected", [(None, {}), ("true", {"autoCheckOutToSourceControl": True}),
    ("false", {"autoCheckOutToSourceControl": False})])
def test_later_save_preserves_explicit_checkout_choice_and_native_omission(tmp_path, version, value, expected):
    task = SaveTask(tmp_path, version, "allow_changes")
    declaration = task.schema["business_adapter"]["declaration"]
    assert declaration["optional_fields"] == ["auto_check_out"]
    assert declaration["field_semantics"]["auto_check_out"]["omitted_effect"] == "wwise_native_default_true"
    fields = () if value is None else ("--value", "auto_check_out", value)
    preview = task.preview(*fields)
    assert preview["agent_result"]["request"]["arguments"] == {"api": SAVE, "args": expected, "options": {}}
    assert task.client.saves == []
    transaction = preview["transaction_id"]
    code, executed = task.run("execute", transaction)
    assert code == 0, executed
    assert task.client.saves == [(expected, {})]
    code, result = task.run("verify", transaction)
    assert code == 0 and result["state"] == "result_schema_checked", result


@pytest.mark.parametrize("version", VERSIONS)
def test_save_discovery_and_draft_start_have_only_the_versioned_business_input(tmp_path, version):
    task = SaveTask(tmp_path, version)
    declared = task.current["draft"]["next_action_binding"]["declaration"]["append_fields"]
    assert declared == task.schema["business_adapter"]["declaration"]
    code, catalog = task.run("operations")
    assert code == 0, catalog
    assert SAVE in {row["api"] for row in catalog["request_schema_routes"]}
    code, blocked = task.run("typed-zero-call", SAVE, "--schema-digest", "0" * 64, "--apply")
    assert code == 2, blocked
    assert task.client.saves == []


@pytest.mark.parametrize("version", VERSIONS)
def test_sandbox_save_helper_follows_the_disclosed_checkout_contract(tmp_path, version, workflow):
    task = SaveTask(tmp_path, version)

    def gateway(argv, *, live):
        code, result = task.run(*argv)
        assert code == 0, result
        return result

    saved = workflow._save_sandbox_project(SimpleNamespace(gateway=gateway, version=version))
    expected = {} if version in {"2021.1", "2022.1"} else {"autoCheckOutToSourceControl": False}
    assert task.client.saves == [(expected, {})]
    assert saved["preview"]["agent_result"]["request"]["arguments"] == {"api": SAVE, "args": expected, "options": {}}
    assert saved["verify"]["state"] == "result_schema_checked"
