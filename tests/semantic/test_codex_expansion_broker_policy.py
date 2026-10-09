from pathlib import Path
import json
from dataclasses import replace

import pytest

from tests.semantic.support.codex_expansion_broker_policy import ExpansionBrokerPolicy
from tests.semantic.support.codex_expansion_cases import PreparedExpansionCase
from tests.semantic.support.codex_expansion_policy import ExpansionPolicyError, ExpansionReadScope
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker, ResponseBinding


SKILL = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
OWNER = "{11111111-1111-1111-1111-111111111111}"
EVENT = "{33333333-3333-3333-3333-333333333333}"
ACTION = "{44444444-4444-4444-4444-444444444444}"
OTHER_EVENT = "{55555555-5555-5555-5555-555555555555}"
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


def make_event_read_policy(*, includes=("action-type", "target"), fields=()):
    case = PreparedExpansionCase(
        prompt="Check the Event's existing playback actions", operation="audio.import",
        policy="allow_changes", before={"event": EVENT},
        read_object_ids=frozenset({EVENT, ACTION, OTHER_EVENT}),
        relationship_sources=frozenset({EVENT}),
        read_includes=frozenset(includes),
        read_fields=frozenset(fields),
        required_assertions=frozenset({"media"}), approve_preview=lambda _: True,
        snapshot=lambda: {"event": EVENT}, verify=lambda _old, _new: {"media": True},
    )
    policy = ExpansionBrokerPolicy(
        prepared=case, version="2025.1", skill_source=SKILL,
        scoped_paths={EVENT: r"\Events\Default Work Unit\Play_Line_01"},
    )
    policy.begin_turn(1)
    return policy


def event_actions_argv(*, event_id=EVENT, extra=(), includes=("action-type", "target"),
                       max_results=None):
    argv = ["query-object", "--exact-id", event_id, "--relationship", "event-actions"]
    for output in includes:
        argv.extend(("--include", output))
    argv.extend(extra)
    if max_results is not None:
        argv.extend(("--max-results", str(max_results)))
    return tuple(argv)


def event_actions_receipt(rows=(ACTION,), *, bound=100, count=None, limit_reached=False):
    objects = [
        {"id": object_id, "name": f"Action_{index}", "type": "Action", "path": rf"\Events\Play\Action_{index}",
         "action_type": "Play", "target": {"id": OWNER, "name": "Voice", "type": "Sound", "path": PATH}}
        for index, object_id in enumerate(rows, 1)
    ]
    return {"ok": True, "command": "query-object", "objects": objects,
            "count": len(objects) if count is None else count,
            "query_bound": {"mode": "take", "value": bound},
            "limit_reached": limit_reached}


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
                 ("query-object", "--exact-id", OWNER, "--relationship", "children", "--max-results", "8"),
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


@pytest.mark.parametrize("limit", [100, 1000])
def test_owned_children_read_uses_public_gateway_budget_at_authenticated_broker(monkeypatch, tmp_path, limit):
    from types import SimpleNamespace
    policy = make_policy()
    argv = ("query-object", "--exact-id", OWNER, "--relationship", "children",
            "--include", "parent", "--include", "source-language", "--include", "original-file-path",
            "--include", "file-path", "--max-results", str(limit))
    args = policy.gateway_module.build_parser().parse_args(["--version", policy.version, *argv])
    policy.gateway_module.preflight_query_object_input(args, env={})
    assert args.take == limit
    dispatched = []
    with CodexGatewayBroker(skill_source=SKILL, expected_steps=(), runner_environment={},
                            transport="tcp", expansion_outcome_policy=policy,
                            working_root=tmp_path / "broker") as broker:
        def launch(command, *, runner_env):
            dispatched.append(command[3:])
            payload = {"contract": "waapi-skill.gateway-result/v1", "ok": True, "command": "query-object", "objects": [], "count": 0,
                       "query_bound": {"mode": "take", "value": limit}}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload))
        monkeypatch.setattr(broker, "_launch_runner", launch)
        monkeypatch.setattr(broker, "_communicate_runner", lambda process: (process.stdout, ""))
        response = broker._handle_request({"token": broker._token, "interpreter": "python",
            "argv": [str(broker.runner_path), "gateway.py", *argv]})
        assert response["exit_code"] == 0, response
        record = broker.evidence().records[0]
        assert record.authenticated and record.accepted and record.succeeded
    assert dispatched == [list(argv)] and len(policy.reads.receipts) == 1


@pytest.mark.parametrize("argv", [
    ("query-object", "--exact-id", OWNER, "--relationship", "children", "--max-results", "1001"),
    ("query-object", "--exact-id", OWNER, "--relationship", "children"),
    ("--host", "elsewhere", "query-object", "--exact-id", OWNER, "--max-results", "100"),
    ("call", "ak.wwise.core.object.get"),
])
def test_owned_public_row_budget_does_not_admit_unbounded_or_outside_gateway_reads(tmp_path, argv):
    with pytest.raises(ExpansionPolicyError):
        make_policy().prepare(argv, state_directory=tmp_path)


def test_sealed_owned_64_row_scope_retains_its_original_limit_and_digest(tmp_path):
    policy = make_policy()
    scope = policy.reads.scope
    historical = {**scope.__dict__, "max_rows": 64}
    policy.reads.scope = ExpansionReadScope(**historical)
    digest = policy.reads.scope.digest
    with pytest.raises(ExpansionPolicyError, match="bounded public source"):
        policy.prepare(("query-object", "--exact-id", OWNER, "--relationship", "children",
                        "--max-results", "100"), state_directory=tmp_path)
    assert policy.reads.scope.max_rows == 64 and policy.reads.scope.digest == digest


@pytest.mark.parametrize("restriction", ["bytes", "calls"])
def test_owned_public_row_budget_preserves_other_read_capacity(tmp_path, restriction):
    policy = make_policy()
    policy.reads.scope = replace(policy.reads.scope, **(
        {"max_result_bytes": 80} if restriction == "bytes" else {"max_calls": 1}))
    step = policy.prepare(("query-schema",), state_directory=tmp_path)
    if restriction == "bytes":
        with pytest.raises(ExpansionPolicyError, match="byte"):
            policy.observe(step, {"ok": True, "command": "query-schema", "text": "音" * 30}, state_directory=tmp_path)
        assert not policy.reads.receipts
    else:
        policy.observe(step, {"ok": True, "command": "query-schema"}, state_directory=tmp_path)
        with pytest.raises(ExpansionPolicyError, match="capacity"):
            policy.prepare(("operations",), state_directory=tmp_path)


@pytest.mark.parametrize("max_results", [None, 100])
def test_owned_event_actions_read_uses_gateway_fixed_bound_and_sealed_projection(tmp_path, max_results):
    policy = make_event_read_policy()
    for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"):
        schema = policy.gateway_module.query_business_schema_payload(version, advanced=False)
        assert schema["relationship_presets"]["event-actions"]["fixed_max_results"] == 100
        assert schema["relationship_presets"]["event-actions"]["automatic_outputs"] == ["action-type", "target"]

    argv = event_actions_argv(max_results=max_results)
    public_args = policy.gateway_module.build_parser().parse_args(
        ["--version", policy.version, *argv]
    )
    policy.gateway_module.preflight_query_object_input(public_args, env={})
    assert public_args.max_results == public_args.take == 100
    assert public_args.select == ["children"]
    assert {binding[2] for binding in public_args.query_output_bindings} == {"action_type", "target"}

    step = policy.prepare(argv, state_directory=tmp_path)
    assert step.arguments == argv[1:]  # the accepted Agent argv is recorded unchanged
    policy.observe(step, event_actions_receipt(), state_directory=tmp_path)

    assert policy.reads.scope.max_rows == 1000
    assert policy.reads.receipts[0][0] == argv
    assert policy.prepared.read_object_ids == frozenset({EVENT, ACTION, OTHER_EVENT})
    assert not policy.reads.failed_receipts


@pytest.mark.parametrize("argv", [
    event_actions_argv(event_id=OTHER_EVENT),
    event_actions_argv(extra=("--relationship", "children")),
    event_actions_argv(max_results=64),
    event_actions_argv(max_results=99),
    event_actions_argv(extra=("--max-results", "100"), max_results=100),
    event_actions_argv(extra=("--exact-id", EVENT)),
    event_actions_argv(includes=("action-type", "target", "notes")),
    event_actions_argv(includes=("action-type", "target", "target")),
    ("query-object", "--kind", "event", "--relationship", "event-actions", "--max-results", "100"),
])
def test_owned_event_actions_read_rejects_unsealed_or_composed_preset(argv, tmp_path):
    policy = make_event_read_policy()
    with pytest.raises(ExpansionPolicyError):
        policy.prepare(argv, state_directory=tmp_path)


def test_owned_event_actions_read_requires_the_automatic_projection_in_case_scope(tmp_path):
    policy = make_event_read_policy(includes=("action-type",))
    with pytest.raises(ExpansionPolicyError, match="projection"):
        policy.prepare(event_actions_argv(includes=("action-type",)), state_directory=tmp_path)


def test_owned_event_actions_read_rejects_publicly_unsupported_custom_fields(tmp_path):
    policy = make_event_read_policy(fields=("volume-db",))
    argv = event_actions_argv(extra=("--include-field", "volume-db"))
    public_args = policy.gateway_module.build_parser().parse_args(
        ["--version", policy.version, *argv]
    )
    with pytest.raises(policy.gateway_module.GatewayInputError, match="cannot be combined with --relationship"):
        policy.gateway_module.preflight_query_object_input(public_args, env={})
    with pytest.raises(ExpansionPolicyError, match="projection"):
        policy.prepare(argv, state_directory=tmp_path)


def test_owned_event_actions_read_rejects_rows_over_the_gateway_fixed_budget(tmp_path):
    policy = make_event_read_policy()
    step = policy.prepare(event_actions_argv(), state_directory=tmp_path)
    rows = tuple(f"{{00000000-0000-0000-0000-{index:012X}}}" for index in range(1, 102))
    with pytest.raises(ExpansionPolicyError, match="rows exceed scope"):
        policy.observe(step, event_actions_receipt(rows), state_directory=tmp_path)
    assert policy.reads.receipts == []


def test_owned_event_actions_ceiling_or_mismatched_receipt_never_proves_a_read(tmp_path):
    policy = make_event_read_policy()
    step = policy.prepare(event_actions_argv(), state_directory=tmp_path)
    rows = tuple(f"{{00000000-0000-0000-0000-{index:012X}}}" for index in range(1, 65))
    assert policy.reads.observe(event_actions_receipt(rows, limit_reached=True)) is False
    assert policy.reads.receipts == [] and len(policy.reads.failed_receipts) == 1

    step = policy.prepare(event_actions_argv(), state_directory=tmp_path)
    with pytest.raises(ExpansionPolicyError, match="completeness"):
        policy.observe(step, event_actions_receipt(bound=64), state_directory=tmp_path)
    assert len(policy.reads.receipts) == 0


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


def _schema_checked_policy(state_directory):
    from dataclasses import replace
    from wwise_waapi.transactions import TransactionStore
    from tests.semantic.support.codex_expansion_policy import canonical_digest

    prepared = replace(make_policy().prepared,
        accepted_verification_states=frozenset({"result_schema_checked"}))
    policy = ExpansionBrokerPolicy(prepared=prepared, version="2025.1", skill_source=SKILL,
                                   scoped_paths={OWNER: PATH})
    policy.begin_turn(1)
    store = TransactionStore(state_directory)
    tx = "tx1-" + "6" * 20
    artifact = {"request": {"operation": prepared.operation}}
    record = store.create_preview(tx, artifact)
    baseline = canonical_digest(prepared.before)
    policy.transaction.seal_preview(transaction_id=tx, artifact=artifact,
        artifact_sha256=record.artifact_hash, before_sha256=baseline, after_sha256=baseline)
    permit = policy.transaction.authorize(turn_prompt_sha256=canonical_digest(prepared.prompt),
                                          explicit_intent="perform_changes")
    store.authorize_by_policy(tx, policy="allow_changes",
                              authority=policy.gateway_module.POLICY_AUTHORIZATION_AUTHORITY)
    policy.transaction.reserve_execute(permit, live_artifact_sha256=record.artifact_hash,
                                        gateway_authorization_bound=True)
    store.begin_execution(tx, expected_authorization="policy_authorized")
    store.mark_executed_unverified(tx)
    policy.transaction.observe_execution(transaction_id=tx, artifact_sha256=record.artifact_hash,
                                          completed=True)
    policy.transaction_id, policy.artifact_hash = tx, record.artifact_hash
    step = policy.prepare(("verify", tx), state_directory=state_directory)
    store.record_verification(tx, outcome="result_schema_checked")
    policy.observe(step, {"ok": True, "command": "verify", "transaction_id": tx,
                         "artifact_hash": record.artifact_hash, "state": "result_schema_checked"},
                   state_directory=state_directory)
    assert policy.complete
    return policy, store, tx


@pytest.mark.parametrize("argv", [
    ("query-object", "--exact-id", OWNER),
    ("metadata", "attenuation", "--exact-id", OWNER, "--curve-role", "volume-dry"),
])
def test_schema_checked_followup_dispatches_owned_project_reads_without_reopening_transaction(monkeypatch, tmp_path, argv):
    from types import SimpleNamespace

    policy, store, tx = _schema_checked_policy(tmp_path / "state")
    terminal = store.load(tx)
    events = store.read_events(tx)
    assertions = dict(policy.assertions)
    dispatched = []
    with CodexGatewayBroker(skill_source=SKILL, expected_steps=(), runner_environment={},
                            transport="tcp", expansion_outcome_policy=policy,
                            working_root=tmp_path / "broker", existing_state_directory=tmp_path / "state") as broker:
        def launch(command, *, runner_env):
            dispatched.append(command[3:])
            payload = {"contract": "waapi-skill.gateway-result/v1", "ok": True, "command": argv[0]}
            if argv[0] == "query-object":
                payload.update(objects=[], count=0, query_bound={"mode": "exact-object"})
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload))
        monkeypatch.setattr(broker, "_launch_runner", launch)
        monkeypatch.setattr(broker, "_communicate_runner", lambda process: (process.stdout, ""))
        response = broker._handle_request({"token": broker._token, "interpreter": "python",
            "argv": [str(broker.runner_path), "gateway.py", *argv]})
        assert response["exit_code"] == 0, response
        receipt = broker.evidence().records[0]
        assert receipt.authenticated and receipt.accepted and receipt.succeeded
    assert dispatched == [list(argv)]
    assert len(policy.reads.receipts) == 1
    assert store.load(tx) == terminal and store.read_events(tx) == events
    assert policy.transaction.gateway_verification_state == "result_schema_checked"
    assert policy.complete and dict(policy.assertions) == assertions


@pytest.mark.parametrize("argv", [
    ("execute", "tx1-" + "6" * 20),
    ("verify", "tx1-" + "6" * 20),
    ("draft-start", "audio.import"),
    ("config-set", "--project-modification-policy", "allow_changes"),
    ("--host", "foreign.example", "query-object", "--exact-id", OWNER),
    ("metadata", "attenuation", "--exact-id", OWNER, "--curve-role", "unknown-role"),
    ("call", "ak.wwise.core.object.get"),
])
def test_schema_checked_read_followup_never_admits_writes_reverification_or_public_scope_escape(monkeypatch, tmp_path, argv):
    policy, store, tx = _schema_checked_policy(tmp_path / "state")
    terminal = store.load(tx)
    events = store.read_events(tx)
    with CodexGatewayBroker(skill_source=SKILL, expected_steps=(), runner_environment={},
                            transport="tcp", expansion_outcome_policy=policy,
                            working_root=tmp_path / "broker", existing_state_directory=tmp_path / "state") as broker:
        monkeypatch.setattr(broker, "_launch_runner", lambda *_args, **_kwargs: pytest.fail("rejection must precede dispatch"))
        response = broker._handle_request({"token": broker._token, "interpreter": "python",
            "argv": [str(broker.runner_path), "gateway.py", *argv]})
        assert response["exit_code"] == 126, response
        receipt = broker.evidence().records[0]
        assert receipt.authenticated and not receipt.accepted and not receipt.succeeded
        assert receipt.payload is None and receipt.runner_exit_code is None
    assert store.load(tx) == terminal and store.read_events(tx) == events
    assert policy.complete and not policy.reads.receipts


def test_independent_callback_measures_cpu_work_and_agent_overlap():
    from tests.semantic.support.codex_expansion_timing import ExpansionPhaseTiming
    from dataclasses import replace
    now = [10.0]
    timing = ExpansionPhaseTiming(clock=lambda: now[0])
    policy = make_policy()
    policy.phase_timing = timing
    def snapshot():
        now[0] += 3
        return {"measured": True}
    policy.prepared = replace(policy.prepared, snapshot=snapshot)
    assert policy.observe_oracle("preview-before", policy.prepared.snapshot) == {"measured": True}
    row = timing.evidence()["intervals"][0]
    assert (row["phase"], row["scope"], row["attribution"], row["elapsed_seconds"]) == (
        "oracle", "preview-before", "agent", 3.0)
    def failed_snapshot():
        now[0] += 2
        raise OSError("proof unavailable")
    with pytest.raises(OSError):
        policy.observe_oracle("verification-snapshot", failed_snapshot)
    assert timing.evidence()["phases"]["oracle"] == {
        "elapsed_seconds": 5.0, "measured": True, "exhausted": False, "errors": 1}
