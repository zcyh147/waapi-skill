from pathlib import Path
import json

import pytest

from tests.semantic.support.codex_expansion_broker_policy import ExpansionBrokerPolicy
from tests.semantic.support.codex_expansion_cases import PreparedExpansionCase
from tests.semantic.support.codex_expansion_policy import ExpansionPolicyError
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker, ResponseBinding


SKILL = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
OWNER = "{11111111-1111-1111-1111-111111111111}"
PATH = r"\Containers\Default Work Unit\Music"


def make_policy(operation="audio.import", request_schema_uri=None, approve_preview=None):
    case = PreparedExpansionCase(
        prompt="导入两个音乐轨道并完成核验", operation=operation, policy="allow_changes",
        before={"objects": [OWNER]}, read_object_ids=frozenset({OWNER}),
        relationship_sources=frozenset({OWNER}), read_includes=frozenset({"parent"}),
        required_assertions=frozenset({"media"}), approve_preview=approve_preview or (lambda _: True),
        snapshot=lambda: {"objects": [OWNER]}, verify=lambda _old, _new: {"media": True},
        request_schema_uri=request_schema_uri,
    )
    policy = ExpansionBrokerPolicy(prepared=case, version="2025.1", skill_source=SKILL,
                                   scoped_paths={OWNER: PATH})
    policy.begin_turn(1)
    return policy


def start(policy, tmp_path):
    step = policy.prepare(("draft-start", "audio.import"), state_directory=tmp_path)
    policy.observe(step, {"draft": {"draft_id": "draft-test", "revision": 1},
                          "task_authority": "authority-test"}, state_directory=tmp_path)


@pytest.mark.parametrize("selector", [
    ("--object-id", OWNER),
    ("--object-path-segment", "Containers", "--object-path-segment", "Default Work Unit",
     "--object-path-segment", "Music"),
])
def test_dynamic_business_binding_accepts_exact_id_or_same_sealed_path(tmp_path, selector):
    policy = make_policy()
    start(policy, tmp_path)
    step = policy.prepare(("draft-bind-object", "draft-test", "--task-authority", "authority-test",
                           "--expected-revision", "1", *selector), state_directory=tmp_path)
    assert isinstance(step.arguments[0], ResponseBinding)
    assert step.arguments[0].pointer == "/draft/draft_id"


@pytest.mark.parametrize("argv", [
    ("call", "ak.wwise.core.object.get"),
    ("draft-start", "object.delete"),
    ("--host", "elsewhere", "operations"),
    ("config-set", "--project-modification-policy", "allow_changes"),
    ("execute", "tx1-unapproved"),
])
def test_outcome_mode_does_not_turn_into_generic_gateway_or_transaction_access(tmp_path, argv):
    policy = make_policy()
    with pytest.raises(ExpansionPolicyError):
        policy.prepare(argv, state_directory=tmp_path)


def test_scope_and_revision_checked_before_metadata_reads_or_declaration(tmp_path):
    policy = make_policy()
    start(policy, tmp_path)
    for identity, revision in (("{22222222-2222-2222-2222-222222222222}", "1"), (OWNER, "2")):
        with pytest.raises(ExpansionPolicyError):
            policy.prepare(("draft-bind-object", "draft-test", "--task-authority", "authority-test",
                            "--expected-revision", revision, "--object-id", identity), state_directory=tmp_path)


def test_new_case_preview_uses_production_auto_apply_contract_without_magic_flag(tmp_path):
    policy = make_policy()
    start(policy, tmp_path)
    step = policy.prepare(("preview-from-draft", "draft-test", "--task-authority", "authority-test",
                           "--expected-revision", "1"), state_directory=tmp_path)
    assert step.subcommand == "preview-from-draft"
    assert policy.before_preview is not None
    assert policy.transaction.state == "unprepared"  # no fabricated Preview/authorization


def test_wrong_effect_preview_is_bound_as_rejected_without_runner_authorization(tmp_path):
    from tests.semantic.test_codex_transaction_seal import _artifact
    from wwise_waapi.transactions import TransactionStore

    policy = make_policy(approve_preview=lambda _artifact: False)
    start(policy, tmp_path)
    step = policy.prepare(("preview-from-draft", "draft-test", "--task-authority", "authority-test",
                           "--expected-revision", "1"), state_directory=tmp_path)
    tx = "tx1-" + "1" * 20
    artifact = _artifact()
    record = TransactionStore(tmp_path).create_preview(tx, artifact)

    policy.observe(step, {"ok": True, "command": "preview-from-draft", "transaction_id": tx,
                          "artifact_hash": record.artifact_hash}, state_directory=tmp_path)

    assert policy.transaction_id == tx
    assert policy.artifact_hash == record.artifact_hash
    assert policy.oracle_evidence["transaction_id"] == tx
    assert policy.oracle_evidence["artifact_hash"] == record.artifact_hash
    assert policy.oracle_evidence["preview_approved"] is False
    assert policy.transaction.state == "preview_rejected"
    assert policy.permit is None
    assert policy.oracle_evidence["authorization"] is None
    assert policy.oracle_evidence["permit"] is None
    for command in (
        ("confirm", tx, "--confirmation-token", "ct1-" + "a" * 24),
        ("execute", tx),
    ):
        with pytest.raises(ExpansionPolicyError, match="rejected Preview"):
            policy.prepare(command, state_directory=tmp_path)


def test_outcome_broker_does_not_finish_on_last_discovery_or_allow_unapproved_execute(tmp_path):
    policy = make_policy()
    fake_skill = tmp_path / "fake-skill"
    scripts = fake_skill / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text(
        "import json,sys\nprint(json.dumps({'contract':'waapi-skill.gateway-result/v1',"
        "'ok':True,'command':sys.argv[2]}))\n", encoding="utf-8")
    with CodexGatewayBroker(skill_source=fake_skill, expected_steps=(), runner_environment={},
                            transport="tcp", expansion_outcome_policy=policy) as broker:
        def invoke(*argv):
            return broker._handle_request({"token": broker._token, "interpreter": "python",
                "argv": [str(broker.runner_path), "gateway.py", *argv]})
        assert invoke("operations")["exit_code"] == 0
        assert invoke("operations")["exit_code"] == 0
        assert not broker.evidence().complete
        assert invoke("execute", "tx1-unknown")["exit_code"] != 0
        assert invoke("operations")["exit_code"] != 0
        assert len([row for row in broker.evidence().records if row.accepted]) == 2


@pytest.mark.parametrize("operation,uri,command,tail", [
    ("audio.import", None, "draft-declare-existing", ("--declaration-id", "line", "--object-handle", "bo1-target", "--field", "audio_file", "/tmp/line.wav")),
    ("audio.import", None, "draft-declare-import-batch", ("--row-order", "a", "--existing-row", "a", "bo1-target", "--media-directory", "/tmp", "--media-file", "a", "hit.wav")),
    ("object.setRTPC", None, "draft-declare-rtpc", ("--object-handle", "bo1-target", "--field-handle", "bf1-volume", "--control-input-handle", "bo1-control", "--point", "0", "-48", "Linear", "--point", "100", "0", "Linear")),
    ("waapi.call", "ak.wwise.core.object.setAttenuationCurve", "draft-declare-core-plan", ("--role", "object", "bo1-target", "--value", "curve_role", "volume-dry", "--curve-point", "0", "0", "Linear", "--curve-point", "100", "-48", "Linear")),
    ("object.createPlugin", None, "draft-declare-existing", ("--declaration-id", "gain", "--object-handle", "bo1-target", "--field", "plugin_role", "effect", "--field", "plugin_name", "Added_Gain", "--field", "plugin_type_handle", "bt1-gain")),
    ("audio.import", None, "draft-declare-new", ("--declaration-id", "quiet", "--parent-handle", "bo1-parent", "--name", "Quiet", "--kind", "music-track", "--field", "volume_db", "-6", "--field", "audio_file", "/tmp/Quiet.wav")),
    ("object.setReference", None, "draft-declare-field-change", ("--object-handle", "bo1-target", "--field-handle", "bf1-trigger", "--target-handle", "bo1-trigger")),
])
def test_seven_case_declaration_families_use_real_parser_and_authenticated_broker(tmp_path, operation, uri, command, tail):
    policy = make_policy(operation, uri)
    fake_skill = tmp_path / "fake-skill"
    scripts = fake_skill / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text('''import json,os,sys
from pathlib import Path
args=sys.argv[2:]; command=args[0]
state=Path(os.environ['WAAPI_SKILL_STATE_DIR'])/'test-draft.json'
if command=='draft-start':
 d={'draft_id':'od1-'+'1'*32,'revision':1,'lifecycle_state':'editable','binding':{'operation':args[1],'version':'2025.1'}}
else:
 d=json.loads(state.read_text()); d['revision']+=1
state.write_text(json.dumps(d))
p={'contract':'waapi-skill.gateway-result/v1','command':command,'ok':True,'draft':d}
if command=='draft-start': p['task_authority']='da1-'+'2'*40
print(json.dumps(p))
''', encoding="utf-8")
    with CodexGatewayBroker(skill_source=fake_skill, expected_steps=(), runner_environment={},
                            transport="tcp", expansion_outcome_policy=policy) as broker:
        def invoke(argv):
            return broker._handle_request({"token": broker._token, "interpreter": "python",
                "argv": [str(broker.runner_path), "gateway.py", *argv]})
        first = invoke(("draft-start", uri or operation))
        assert first["exit_code"] == 0, first
        receipt = invoke((command, policy.draft_id, "--task-authority", policy.authority,
                          "--expected-revision", "1", *tail))
        assert receipt["exit_code"] == 0, receipt
        assert policy.revision == 2
        assert not broker.evidence().complete  # declaration is never business proof


def test_owned_project_reads_allow_relations_new_guids_and_disclosed_advanced_without_expanding_write_scope(tmp_path):
    policy = make_policy()
    new_id = "{22222222-2222-2222-2222-222222222222}"
    for argv in (("status",), ("query-object", "--exact-id", new_id),
                 ("query-object", "--exact-id", OWNER, "--relationship", "event-actions", "--max-results", "8"),
                 ("query-schema", "--advanced"),
                 ("query-object", "--advanced-waql", f'from object "{OWNER}" select @Effects', "--max-results", "8")):
        step = policy.prepare(argv, state_directory=tmp_path)
        payload = {"ok": True, "command": argv[0]}
        if argv[0] == "query-object":
            mode = "gateway-appended-take" if "--advanced-waql" in argv else "take" if "--max-results" in argv else "exact-object"
            payload.update(objects=[], count=0, query_bound={"mode": mode, **({"value": 8} if "--max-results" in argv else {})})
        policy.observe(step, payload, state_directory=tmp_path)
    assert new_id not in policy.prepared.read_object_ids
    start(policy, tmp_path)
    with pytest.raises(ExpansionPolicyError, match="outside"):
        policy.prepare(("draft-bind-object", "draft-test", "--task-authority", "authority-test",
                        "--expected-revision", "1", "--object-id", new_id), state_directory=tmp_path)


def test_malformed_runner_receipt_makes_outcome_broker_terminal_before_next_dispatch(tmp_path):
    policy = make_policy()
    scripts = tmp_path / "fake-skill" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text("print('not a gateway result')\n")
    with CodexGatewayBroker(skill_source=scripts.parent, expected_steps=(), runner_environment={},
                            transport="tcp", expansion_outcome_policy=policy) as broker:
        def invoke():
            return broker._handle_request({"token": broker._token, "interpreter": "python",
                "argv": [str(broker.runner_path), "gateway.py", "operations"]})
        assert invoke()["exit_code"] != 0
        assert invoke()["exit_code"] != 0
        assert len([record for record in broker.evidence().records if record.runner_command_sha256]) == 1


def test_authenticated_execute_then_new_identity_read_and_no_second_execute(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from wwise_waapi.transactions import TransactionStore
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    policy = make_policy()
    scripts = tmp_path / "fake-skill" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text("# fake process seam; never launched\n")
    new_id = "{22222222-2222-2222-2222-222222222222}"
    calls = []
    with CodexGatewayBroker(skill_source=scripts.parent, expected_steps=(), runner_environment={},
                            transport="tcp", expansion_outcome_policy=policy,
                            working_root=tmp_path.resolve() / "broker") as broker:
        store = TransactionStore(broker.state_directory)
        tx = "tx1-" + "1" * 20
        artifact = {"request": {"operation": "audio.import"}, "approved_new_path": PATH + "\\Imported"}
        record = store.create_preview(tx, artifact)
        policy.transaction.seal_preview(transaction_id=tx, artifact=artifact, artifact_sha256=record.artifact_hash,
            before_sha256=canonical_digest(policy.prepared.before), after_sha256=canonical_digest(policy.prepared.before))
        policy.transaction_id, policy.artifact_hash = tx, record.artifact_hash
        store.authorize_by_policy(tx, policy="allow_changes", authority=policy.gateway_module.POLICY_AUTHORIZATION_AUTHORITY)
        def launch(command, *, runner_env):
            argv = command[3:]
            calls.append(argv)
            payload = {"contract": "waapi-skill.gateway-result/v1", "ok": True, "command": argv[0]}
            if argv[0] == "execute":
                store.begin_execution(tx, expected_authorization="policy_authorized")
                store.mark_executed_unverified(tx)
                payload.update(transaction_id=tx, artifact_hash=record.artifact_hash, state="executed_unverified",
                               status="executed_unverified", executed=True, verified=False, automatic_retry=False)
            else:
                payload.update(objects=[{"id": new_id}], count=1, query_bound={"mode": "exact-object"})
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload))
        monkeypatch.setattr(broker, "_launch_runner", launch)
        monkeypatch.setattr(broker, "_communicate_runner", lambda process: (process.stdout, ""))
        def invoke(*argv):
            return broker._handle_request({"token": broker._token, "interpreter": "python",
                "argv": [str(broker.runner_path), "gateway.py", *argv]})
        assert invoke("execute", tx)["exit_code"] == 0
        assert invoke("query-object", "--exact-id", new_id)["exit_code"] == 0
        assert new_id not in policy.prepared.read_object_ids
        assert invoke("execute", tx)["exit_code"] != 0
        assert len(calls) == 2


@pytest.mark.parametrize("changed_revision", [False, True])
def test_preparation_failure_is_repairable_only_with_unchanged_durable_draft(monkeypatch, tmp_path, changed_revision):
    from types import SimpleNamespace
    from wwise_waapi.operation_drafts import OperationDraftStore
    policy = make_policy("object.createPlugin")
    start_step = policy.prepare(("draft-start", "object.createPlugin"), state_directory=tmp_path)
    policy.observe(start_step, {"draft": {"draft_id": "draft-test", "revision": 1},
                               "task_authority": "authority-test"}, state_directory=tmp_path)
    monkeypatch.setattr(OperationDraftStore, "inspect", lambda *args, **kwargs:
                        SimpleNamespace(revision=2 if changed_revision else 1))
    step = policy.prepare(("draft-discover-types", "draft-test", "--task-authority", "authority-test",
                           "--expected-revision", "1", "--meaning", "Gain", "--role", "effect"), state_directory=tmp_path)
    payload = {"ok": False, "command": "draft-discover-types", "error_code": "CAPABILITY_UNAVAILABLE"}
    if changed_revision:
        with pytest.raises(ExpansionPolicyError, match="changed"):
            policy.observe(step, payload, state_directory=tmp_path)
    else:
        policy.observe(step, payload, state_directory=tmp_path)
        repair = policy.prepare(("draft-discover-types", "draft-test", "--task-authority", "authority-test",
                                  "--expected-revision", "1", "--meaning", "Wwise Gain", "--role", "effect"), state_directory=tmp_path)
        assert repair.subcommand == "draft-discover-types"
        assert policy.preparation_failures == [payload]


def test_incomplete_project_query_is_repairable_but_not_complete_read_evidence(tmp_path):
    policy = make_policy()
    step = policy.prepare(("query-object", "--kind", "sound-sfx", "--max-results", "1"), state_directory=tmp_path)
    policy.observe(step, {"ok": True, "command": "query-object", "count": 1,
                         "objects": [{"id": OWNER}], "query_bound": {"mode": "take", "value": 1}}, state_directory=tmp_path)
    assert not policy.reads.receipts and len(policy.reads.failed_receipts) == 1
    policy.prepare(("query-object", "--exact-id", OWNER), state_directory=tmp_path)


def test_structured_indeterminate_execution_is_a_terminal_non_retryable_receipt(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from wwise_waapi.transactions import TransactionStore
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    policy = make_policy()
    with CodexGatewayBroker(skill_source=SKILL, expected_steps=(), runner_environment={},
                            transport="tcp", expansion_outcome_policy=policy,
                            working_root=tmp_path.resolve() / "broker") as broker:
        store = TransactionStore(broker.state_directory)
        tx = "tx1-" + "3" * 20
        artifact = {"request": {"operation": "audio.import"}}
        record = store.create_preview(tx, artifact)
        policy.transaction.seal_preview(transaction_id=tx, artifact=artifact, artifact_sha256=record.artifact_hash,
            before_sha256=canonical_digest(policy.prepared.before), after_sha256=canonical_digest(policy.prepared.before))
        policy.transaction_id, policy.artifact_hash = tx, record.artifact_hash
        store.authorize_by_policy(tx, policy="allow_changes", authority=policy.gateway_module.POLICY_AUTHORIZATION_AUTHORITY)
        launches = []
        def launch(command, *, runner_env):
            launches.append(command)
            store.begin_execution(tx, expected_authorization="policy_authorized")
            store.mark_execution_indeterminate(tx)
            payload = {"contract": "waapi-skill.gateway-result/v1", "ok": False, "command": "execute",
                "status": "indeterminate", "state": "indeterminate", "automatic_retry": False,
                "transaction_id": tx, "artifact_hash": record.artifact_hash}
            return SimpleNamespace(returncode=2, stdout=json.dumps(payload))
        monkeypatch.setattr(broker, "_launch_runner", launch)
        monkeypatch.setattr(broker, "_communicate_runner", lambda process: (process.stdout, ""))
        def invoke():
            return broker._handle_request({"token": broker._token, "interpreter": "python",
                "argv": [str(broker.runner_path), "gateway.py", "execute", tx]})
        assert invoke()["exit_code"] == 2
        assert policy.transaction.state == "indeterminate"
        assert broker.evidence().terminal_indeterminate
        assert invoke()["exit_code"] != 0
        assert len(launches) == 1
