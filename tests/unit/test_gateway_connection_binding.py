from __future__ import annotations

import pytest

from test_gateway_session_context import FakeClient, configured_env, waapi_gateway


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_live_connection_uses_selected_config_despite_ambient_overrides(tmp_path, version):
    env = configured_env(tmp_path, version=version, port=8123)
    env.update(WWISE_WAAPI_HOST="foreign.example", WWISE_WAAPI_PORT="9999", WWISE_VERSION="2020.1")
    client = FakeClient({
        "ak.wwise.core.getInfo": {"displayName": "Wwise", "isCommandLine": True, "version": {"year": int(version[:4]), "major": 1, "minor": 0, "build": 1}},
        "ak.wwise.core.getProjectInfo": {"id": "{11111111-1111-1111-1111-111111111111}", "name": "Project", "path": "\\Project"},
        "ak.wwise.core.object.get": {"return": [{"id": "{11111111-1111-1111-1111-111111111111}", "name": "Project", "type": "Project", "path": "\\Project"}]},
    })
    urls = []
    def connect(url):
        urls.append(url)
        return client
    code, result = waapi_gateway.execute_gateway(["status"], env=env, client_factory=connect)
    assert code == 0, result
    assert urls == ["ws://127.0.0.1:8123/waapi"]
    assert result["detected_version"] == version


@pytest.mark.parametrize("flag,value", [("--host", "foreign.example"), ("--port", "9999")])
def test_connection_overrides_are_absent_from_public_parser(flag, value):
    with pytest.raises(SystemExit):
        waapi_gateway.build_parser().parse_args([flag, value, "status"])


@pytest.mark.parametrize("command", [["status"], ["draft-start", "object.set"]])
def test_version_override_is_only_for_offline_catalogs(tmp_path, command):
    code, result = waapi_gateway.execute_gateway(
        ["--version", "2025.1", *command], env=configured_env(tmp_path),
        client_factory=lambda url: pytest.fail("must reject before connecting"),
    )
    assert code == 2
    assert "offline" in result["message"].lower()


@pytest.mark.parametrize("field,value", [("--waapi-port", "8124"), ("--waapi-host", "other.example"), ("--wwise-version", "2025.1")])
def test_draft_continuation_rejects_changed_config_before_connecting(tmp_path, field, value):
    env = configured_env(tmp_path)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    code, started = waapi_gateway.execute_gateway(["draft-start", "object.set"], env=env)
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    code, changed = waapi_gateway.execute_gateway(["config-set", field, value], env=env)
    assert code == 0, changed
    code, result = waapi_gateway.execute_gateway(
        ["draft-inspect", draft_id, "--task-authority", authority], env=env,
        client_factory=lambda url: pytest.fail("configuration drift must not connect"),
    )
    assert code == 2, result
    assert "configuration" in result["message"].lower()


class BindingClient:
    def __init__(self, version, project_id="{11111111-1111-1111-1111-111111111111}", build=1):
        self.version = version
        self.project_id = project_id
        self.build = build
        self.object_reads = 0

    def call(self, uri, args=None, options=None):
        if uri == "ak.wwise.core.getInfo":
            return {"displayName": "Wwise", "isCommandLine": False, "version": {"year": int(self.version[:4]), "major": 1, "minor": 0, "build": self.build, "displayName": f"{self.version}.0.{self.build}"}}
        project = {"id": self.project_id, "name": "Project", "type": "Project", "path": "/tmp/config-binding/Project.wproj"}
        if uri == "ak.wwise.core.getProjectInfo":
            return project
        if uri == "ak.wwise.core.object.get":
            if "from type Project" in args.get("waql", ""):
                return {"return": [project]}
            self.object_reads += 1
            return {"return": [{"id": "{22222222-2222-2222-2222-222222222222}", "name": "Sound", "type": "Sound", "path": "\\Actor-Mixer Hierarchy\\Sound"}]}
        raise AssertionError(uri)

    def disconnect(self):
        pass


def project_save_preview(env, client):
    """Prepare a real public save transaction without relying on undo routing."""
    code, schema = waapi_gateway.execute_gateway(
        ["request-schema", "ak.wwise.core.project.save"], env=env)
    assert code == 0, schema
    code, result = waapi_gateway.execute_gateway(
        schema["continuation"]["gateway_argv"], env=env, client_factory=lambda _: client)
    assert code == 0, result
    if schema["input_shape"] == "business_declaration":
        declaration = schema["business_adapter"]["declaration"]
        save_fields = (["--value", "auto_check_out", "false"]
            if "auto_check_out" in declaration["optional_fields"] else [])
        authority = result["task_authority"]
        for command, fields in (
            ("draft-declare-core-plan", save_fields),
            ("draft-check", []),
            ("preview-from-draft", []),
        ):
            draft = result["draft"]
            code, result = waapi_gateway.execute_gateway(
                [command, draft["draft_id"], "--task-authority", authority,
                 "--expected-revision", str(draft["revision"]), *fields],
                env=env, client_factory=lambda _: client)
            assert code == 0, result
    assert isinstance(result["transaction_id"], str), result
    return result


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("change", ["project", "build"])
def test_first_live_draft_binding_rejects_later_project_or_build_change(tmp_path, version, change):
    env = configured_env(tmp_path, version=version)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    code, started = waapi_gateway.execute_gateway(["draft-start", "object.delete"], env=env)
    assert code == 0, started
    command = ["draft-bind-object", started["draft"]["draft_id"], "--task-authority", started["task_authority"], "--expected-revision", "1", "--object-id", "{22222222-2222-2222-2222-222222222222}"]
    code, bound = waapi_gateway.execute_gateway(command, env=env, client_factory=lambda _: BindingClient(version))
    assert code == 0, bound
    command[command.index("--expected-revision") + 1] = str(bound["draft"]["revision"])
    changed = BindingClient(version, **({"project_id": "{33333333-3333-3333-3333-333333333333}"} if change == "project" else {"build": 2}))
    code, result = waapi_gateway.execute_gateway(command, env=env, client_factory=lambda _: changed)
    assert code == 2, result
    assert changed.object_reads == 0
    assert "binding" in result["message"].lower()


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_transaction_continuations_reject_configuration_change(tmp_path, version):
    env = configured_env(tmp_path, version=version)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    preview = project_save_preview(env, BindingClient(version))
    transaction_id = preview["transaction_id"]
    code, result = waapi_gateway.execute_gateway(["config-set", "--waapi-port", "8124"], env=env)
    assert code == 0, result
    for command in ["transaction-show", "confirm", "reject", "execute", "verify"]:
        code, result = waapi_gateway.execute_gateway([command, transaction_id, *(["--confirmation-token", "ct1-000000000000000000000000"] if command == "confirm" else [])], env=env, client_factory=lambda _: pytest.fail("drift must not connect"))
        assert code == 2, result
        assert "configuration" in result["message"].lower()


def test_draft_connection_survives_a_new_cli_process(tmp_path):
    import json
    import os
    import subprocess
    import sys

    env = configured_env(tmp_path)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    code, started = waapi_gateway.execute_gateway(["draft-start", "object.delete"], env=env)
    assert code == 0, started
    argv = [sys.executable, str(waapi_gateway.__file__), "draft-inspect", started["draft"]["draft_id"], "--task-authority", started["task_authority"]]
    completed = subprocess.run(argv, env={**os.environ, **env}, capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout)["draft"]["draft_id"] == started["draft"]["draft_id"]
    code, changed = waapi_gateway.execute_gateway(["config-set", "--waapi-port", "8124"], env=env)
    assert code == 0, changed
    completed = subprocess.run(argv, env={**os.environ, **env}, capture_output=True, text=True, timeout=20)
    assert completed.returncode == 2
    assert "configuration" in json.loads(completed.stdout)["message"].lower()


def test_same_connection_values_in_a_different_config_do_not_rebind_a_draft(tmp_path):
    env = configured_env(tmp_path)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    code, started = waapi_gateway.execute_gateway(["draft-start", "object.delete"], env=env)
    assert code == 0, started
    env.update(configured_env(tmp_path / "copy"))
    code, result = waapi_gateway.execute_gateway(["draft-inspect", started["draft"]["draft_id"], "--task-authority", started["task_authority"]], env=env)
    assert code == 2
    assert "configuration" in result["message"].lower()


def test_historical_draft_without_connection_binding_requires_recreation(tmp_path):
    from wwise_waapi.operation_drafts import OperationDraftStore

    env = configured_env(tmp_path)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    legacy = OperationDraftStore(tmp_path / "state").start(
        operation="object.delete", version="2022.1",
        schema_digest=waapi_gateway.operation_draft_schema_digest("object.delete", "2022.1"),
        composer_digest=waapi_gateway.operation_composer_digest("object.delete", "2022.1"),
    )
    code, result = waapi_gateway.execute_gateway(["draft-inspect", legacy.draft_id, "--task-authority", legacy.task_authority], env=env)
    assert code == 2
    assert "predates" in result["message"]
    assert "recreate" in result["message"]


def test_live_version_mismatch_stops_before_business_reads(tmp_path):
    env = configured_env(tmp_path, version="2022.1")
    client = BindingClient("2025.1")
    code, result = waapi_gateway.execute_gateway(["status"], env=env, client_factory=lambda _: client)
    assert code == 2
    assert "2022.1" in result["message"] and "2025.1" in result["message"]
    assert client.object_reads == 0


def test_historical_transaction_without_configuration_requires_new_preview(tmp_path):
    from wwise_waapi.transactions import TransactionStore, new_transaction_id

    env = configured_env(tmp_path)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    preview = project_save_preview(env, BindingClient("2022.1"))
    code, shown = waapi_gateway.execute_gateway(["transaction-show", preview["transaction_id"]], env=env)
    assert code == 0, shown
    legacy_artifact = dict(shown["artifact"])
    legacy_artifact.pop("connection_configuration")
    legacy_id = new_transaction_id()
    TransactionStore(tmp_path / "state").create_preview(legacy_id, legacy_artifact)
    code, result = waapi_gateway.execute_gateway(["transaction-show", legacy_id], env=env)
    assert code == 2
    assert "predates" in result["message"] and "recreate" in result["message"]
