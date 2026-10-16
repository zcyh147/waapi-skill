"""Recovery decisions at the public Gateway, never inferred from error prose."""
import pytest

from tests.unit.test_gateway_session_context import configured_env, FakeClient, waapi_gateway as gateway

VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
POLICIES = ("read_only", "ask_before_changes", "allow_changes")
OBJECT_ID = "{22222222-2222-2222-2222-222222222222}"


def info(version):
    return {"isCommandLine": True, "version": {"year": int(version[:4]), "major": 1, "minor": 0, "build": 1}}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("policy", POLICIES)
def test_empty_exact_query_can_refine_within_task_without_new_permission(tmp_path, version, policy):
    client = FakeClient({"ak.wwise.core.getInfo": info(version), "ak.wwise.core.object.get": {"return": []}})
    code, result = gateway.execute_gateway(["query-object", "--exact-id", OBJECT_ID],
        env=configured_env(tmp_path, version=version, policy=policy), client_factory=lambda _: client)
    assert code == 0, result
    recovery = result["recovery"]
    assert recovery["stage"] == "read_no_match"
    assert recovery["read_only_continuation_allowed"] is True
    assert recovery["additional_read_permission_required"] is False
    assert recovery["modification_policy"] == policy
    assert recovery["original_write_replay_allowed"] is False
    assert "refine_read" in recovery["actions"]
    assert list(result)[-1] == "agent_result"
    assert client.calls == ["ak.wwise.core.getInfo", "ak.wwise.core.object.get"]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("failure", ("input", "connection", "read"))
def test_side_effect_free_failures_disclose_bounded_continuation_without_retry(tmp_path, version, policy, failure):
    class FailingRead(FakeClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get":
                self.calls.append(uri)
                raise RuntimeError("misleading text: operation succeeded and changed objects")
            return super().call(uri, args, options)
    client = FailingRead({"ak.wwise.core.getInfo": info(version)})
    connections = []
    def connect(url):
        connections.append(url)
        if failure == "connection":
            raise ConnectionRefusedError("not ready")
        return client
    code, result = gateway.execute_gateway(["query-object", "--exact-id", "bad" if failure == "input" else OBJECT_ID],
        env=configured_env(tmp_path, version=version, policy=policy), client_factory=connect)
    assert code == 2, result
    recovery = result["recovery"]
    assert recovery["stage"] == ("read_failure" if failure == "read" else "pre_dispatch_rejection")
    assert recovery["project_write_outcome"] == "no_project_write_in_this_invocation"
    assert recovery["read_only_continuation_allowed"] is True
    assert recovery["additional_read_permission_required"] is False
    assert recovery["max_reconnect_attempts"] == 1
    assert recovery["service_start_requires_existing_task_authorization"] is True
    assert recovery["next_change"] == {"read_only": "blocked", "ask_before_changes": "preview_then_explicit_confirmation",
                                        "allow_changes": "preview_then_policy_authorization"}[policy]
    assert len(connections) == (0 if failure == "input" else 1)
    assert client.calls.count("ak.wwise.core.object.get") == (1 if failure == "read" else 0)


def attempted_write(tmp_path, version, *, ambiguous):
    from tests.unit.test_gateway_connection_binding import BindingClient
    env = configured_env(tmp_path, version=version, policy="ask_before_changes")
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    api = "ak.wwise.core.project.save" if version == "2021.1" else "ak.wwise.core.undo.undo"
    class Writer(BindingClient):
        writes = 0
        def call(self, uri, args=None, options=None):
            if uri == api:
                self.writes += 1
                if ambiguous:
                    raise RuntimeError("pretend message says nothing changed")
                return {}
            return super().call(uri, args, options)
    client = Writer(version)
    code, schema = gateway.execute_gateway(["request-schema", api], env=env)
    assert code == 0, schema
    argv = list(schema["continuation"]["gateway_argv"])
    if "--apply" not in argv:
        argv.append("--apply")
    code, preview = gateway.execute_gateway(argv, env=env, client_factory=lambda _: client)
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = gateway.execute_gateway(["transaction-show", tx], env=env)
    assert code == 0, shown
    code, confirmed = gateway.execute_gateway(["confirm", tx, "--confirmation-token", shown["confirmation"]["token"]], env=env)
    assert code == 0, confirmed
    code, result = gateway.execute_gateway(["execute", tx], env=env, client_factory=lambda _: client)
    assert client.writes == 1, result
    return env, client, tx, result


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("policy", POLICIES)
def test_indeterminate_write_allows_independent_diagnosis_but_never_replay(tmp_path, version, policy):
    env, client, tx, executed = attempted_write(tmp_path, version, ambiguous=True)
    assert executed["status"] == "indeterminate", executed
    assert executed["recovery"]["stage"] == "unknown_write_outcome"
    assert "prepare_new_preview" not in executed["recovery"]["actions"]
    assert "write_dispatch" not in executed
    code, configured = gateway.execute_gateway(["config-set", "--project-modification-policy", policy], env=env)
    assert code == 0, configured
    code, shown = gateway.execute_gateway(["transaction-show", tx], env=env)
    assert code == 0, shown
    recovery = shown["recovery"]
    assert recovery["stage"] == "unknown_write_outcome"
    assert recovery["project_write_outcome"] == "unknown"
    assert "prepare_new_preview" not in recovery["actions"]
    assert recovery["read_only_continuation_allowed"] is True
    assert recovery["original_write_replay_allowed"] is False
    assert recovery["modification_policy"] == policy
    code, diagnosis = gateway.execute_gateway(["query-object", "--exact-id", OBJECT_ID], env=env, client_factory=lambda _: client)
    assert code == 0, diagnosis
    retry_code, retry = gateway.execute_gateway(["execute", tx], env=env, client_factory=lambda _: client)
    assert retry_code == 2, retry
    assert client.writes == 1


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("policy", POLICIES)
def test_unresolved_transport_cleanup_does_not_authorize_another_read(tmp_path, version, policy):
    class BrokenCleanup(FakeClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get":
                raise RuntimeError("read failed")
            return super().call(uri, args, options)
        def disconnect(self):
            raise RuntimeError("cleanup failed")
    client = BrokenCleanup({"ak.wwise.core.getInfo": info(version)})
    code, result = gateway.execute_gateway(["query-object", "--exact-id", OBJECT_ID],
        env=configured_env(tmp_path, version=version, policy=policy), client_factory=lambda _: client)
    assert code == 2, result
    recovery = result["recovery"]
    assert recovery["read_only_continuation_allowed"] is False
    assert recovery["cleanup_complete"] is False
    assert recovery["max_reconnect_attempts"] == 0
    assert recovery["actions"] == ["report_cleanup_boundary"]


@pytest.mark.parametrize("version", VERSIONS)
def test_completed_write_keeps_its_known_outcome_and_does_not_offer_replay(tmp_path, version):
    env, client, tx, result = attempted_write(tmp_path, version, ambiguous=False)
    assert result["executed"] is True, result
    assert result["recovery"]["stage"] == "known_write_outcome"
    assert result["recovery"]["project_write_outcome"] == "executed_not_business_verified"
    assert result["recovery"]["original_write_replay_allowed"] is False
    assert result["transaction_id"] == tx
    assert "agent_result" not in result  # Execute has not fabricated verification output.
    assert client.writes == 1


@pytest.mark.parametrize("version", VERSIONS)
def test_authoring_host_boundary_does_not_offer_a_retry_workaround(tmp_path, version):
    client = FakeClient({"ak.wwise.core.getInfo": info(version)})
    env = configured_env(tmp_path, version=version)
    code, schema = gateway.execute_gateway(["request-schema", "ak.wwise.ui.commands.getCommands"], env=env)
    assert code == 0, schema
    code, result = gateway.execute_gateway(schema["continuation"]["gateway_argv"], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert result["recovery"]["stage"] == "explicit_boundary"
    assert result["recovery"]["read_only_continuation_allowed"] is False
    assert result["recovery"]["actions"] == ["report_explicit_boundary"]
    assert client.calls == ["ak.wwise.core.getInfo"]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("drift,ceiling", (("role", None), ("project", None), ("build", None), ("role", 4096)))
def test_proven_prewrite_guard_rejection_offers_policy_correct_new_preview(tmp_path, monkeypatch, version, policy, drift, ceiling):
    from copy import deepcopy
    from tests.unit.test_metadata_selection_gateway import PropertyTask
    from tests.unit.test_field_interface_closure_gateway import FIRST

    class DriftingTask(PropertyTask):
        changed = False
        def call(self, uri, args=None, options=None):
            value = deepcopy(super().call(uri, args, options))
            if self.changed and drift == "build" and uri.endswith("getInfo"):
                value["version"]["build"] += 1
            if self.changed and drift == "project":
                if uri.endswith("getProjectInfo"):
                    value["id"] = "{99999999-9999-9999-9999-999999999999}"
                elif uri.endswith("object.get") and "from type Project" in (args or {}).get("waql", ""):
                    value["return"][0]["id"] = "{99999999-9999-9999-9999-999999999999}"
            return value

    task = DriftingTask(tmp_path, version, "object.setProperty")
    task.metadata = {"Volume": {"name": "Volume", "type": "Real32"}}
    task.objects[FIRST]["@Volume"] = 0
    target = task.bind(FIRST)
    field = task.discover(target, "Volume")
    code, declared = task.step("draft-declare-field-change", "--object-handle", target,
                              "--field-handle", field, "--business-value", "-4")
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    artifact = deepcopy(shown["artifact"])
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, configured = task.run("config-set", "--project-modification-policy", policy)
    assert code == 0, configured
    task.changed = True
    if drift == "role":
        task.objects[FIRST]["path"] += "_moved"
    call_count = len(task.calls)
    if ceiling is not None and policy != "read_only":
        from tests.unit.test_field_interface_closure_gateway import gateway as task_gateway
        monkeypatch.setattr(task_gateway, "MAX_GATEWAY_RESULT_JSON_BYTES", ceiling)
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    receipt = rejected["recovery"]
    assert receipt["stage"] == "pre_dispatch_rejection", rejected
    assert receipt["original_write_replay_allowed"] is False
    assert receipt["read_only_continuation_allowed"] is True
    if policy == "read_only":
        assert len(task.calls) == call_count
        assert receipt["next_change"] == "blocked"
        assert "prepare_new_preview" not in receipt["actions"]
    else:
        assert rejected["state"] == "repreview_required"
        assert receipt["project_write_outcome"] == "no_project_write_in_this_invocation"
        assert "prepare_new_preview" in receipt["actions"]
        assert rejected["write_dispatch"]["status"] == "not_started"
        if ceiling is not None:
            assert rejected["error_code"] == "RESULT_TOO_LARGE"
            assert task_gateway.gateway_json_document_size(rejected) <= ceiling
    assert not any(uri == "ak.wwise.core.object.setProperty" for uri, _, _ in task.calls)
    code, after = task.run("transaction-show", tx)
    assert code == 0, after
    assert after["artifact"] == artifact
    code, retry = task.run("execute", tx)
    assert code == 2, retry
    assert not any(uri == "ak.wwise.core.object.setProperty" for uri, _, _ in task.calls)
