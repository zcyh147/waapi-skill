"""New-profile bounded reads through the existing authenticated Broker."""

from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_policy import ExpansionReadScope
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker, ExpectedGatewayStep


OWNER = "{11111111-1111-1111-1111-111111111111}"


def broker(tmp_path: Path, *, scope: bool = True, oversized: bool = False, outcome_policy=None):
    skill = tmp_path / "skill"
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text(
        "import json, sys\n"
        "command = sys.argv[2]\n"
        "payload = {'contract':'waapi-skill.gateway-result/v1','ok':True,'command':command}\n"
        "if '--include-field' in sys.argv:\n"
        " payload.update(ok=False,error_code='GatewayInputError',message='field needs clarification')\n"
        " print(json.dumps(payload)); sys.exit(2)\n"
        "if command == 'query-object':\n"
        f" payload.update(objects=[{{'id':{OWNER!r}}}] * {2 if oversized else 1}, count={2 if oversized else 1})\n"
        " payload['query_bound'] = ({'mode':'take','value':int(sys.argv[sys.argv.index('--max-results')+1])} "
        "if '--max-results' in sys.argv else {'mode':'exact-object'})\n"
        "print(json.dumps(payload))\n",
        encoding="utf-8",
    )
    return CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(() if outcome_policy is not None else (ExpectedGatewayStep("done", "status", ()),)),
        runner_environment={}, transport="tcp",
        expansion_outcome_policy=outcome_policy,
        expansion_read_scope=(ExpansionReadScope(
            object_ids=frozenset({OWNER}), operations=frozenset({"audio.import"}),
            fields=frozenset({"Volume"}), max_calls=3,
        ) if scope and outcome_policy is None else None),
    )


def invoke(value, *argv):
    return value._handle_request({
        "token": value._token, "interpreter": "python",
        "argv": [str(value.runner_path), "gateway.py", *argv],
    })


def test_existing_broker_executes_variable_read_prefix_with_auditable_receipts(tmp_path):
    with broker(tmp_path) as value:
        assert invoke(value, "operations")["exit_code"] == 0
        assert invoke(value, "query-object", "--max-results", "1", "--exact-id", OWNER)["exit_code"] == 0
        assert invoke(value, "operations")["exit_code"] == 0
        assert invoke(value, "status")["exit_code"] == 0
        evidence = value.evidence()
        assert evidence.complete
        assert len(evidence.records) == 4
        assert all(row.authenticated and row.succeeded for row in evidence.records)
        assert evidence.consumed_step_names == (
            "expansion.read.0001", "expansion.read.0002", "expansion.read.0003", "done",
        )


def test_legacy_broker_does_not_accept_new_read_freedom_by_default(tmp_path):
    with broker(tmp_path, scope=False) as value:
        assert invoke(value, "operations")["exit_code"] != 0
        assert not value.evidence().complete


@pytest.mark.parametrize("arguments", [
    ("query-object", "--exact-id", OWNER, "--max-results", "65"),
    ("request-schema", "ak.wwise.core.executeLuaScript"),
    ("query-object", "--exact-id", "{22222222-2222-2222-2222-222222222222}", "--max-results", "1"),
])
def test_scope_failure_never_falls_back_to_legacy_alternatives(tmp_path, arguments):
    with broker(tmp_path) as value:
        result = invoke(value, *arguments)
        assert result["exit_code"] != 0
        assert all(not record.accepted for record in value.evidence().records)


def test_bad_public_readback_prevents_remaining_transaction_steps(tmp_path):
    with broker(tmp_path, oversized=True) as value:
        result = invoke(value, "query-object", "--exact-id", OWNER, "--max-results", "1")
        assert result["exit_code"] != 0
        assert "read receipt rejected" in result["stderr"]
        assert invoke(value, "status")["exit_code"] != 0
        assert not value.evidence().complete


def test_structured_read_failure_is_a_bounded_repair_opportunity_not_business_credit(tmp_path):
    with broker(tmp_path) as value:
        failed = invoke(value, "query-object", "--exact-id", OWNER, "--include-field", "Volume")
        assert failed["exit_code"] == 2
        assert invoke(value, "query-object", "--exact-id", OWNER)["exit_code"] == 0
        assert invoke(value, "status")["exit_code"] == 0
        assert value.evidence().complete
        assert len(value._expansion_reads.failed_receipts) == 1
        assert len(value._expansion_reads.receipts) == 1


def query_timeout_receipt():
    """Public query envelope from EXP25-C08; no successful object result."""
    details = {
        "provenance": "waapi-skill.gateway-deadline/v1",
        "phase": "WAAPI call ak.wwise.core.object.get",
        "configured_timeout_seconds": 10.0, "timeout_mode": "finite",
        "elapsed_seconds": 10.10397154185921, "deadline_exhausted": True,
        "cleanup_pending": True, "abort_requested": True,
        "operation_timeout_seconds": 1.0167032503522933,
    }
    return {
        "contract": "waapi-skill.gateway-result/v1", "ok": False,
        "status": "error", "command": "query-object", "detected_version": "2025.1",
        "query_bound": {"mode": "exact-object"},
        "call": {"api": "ak.wwise.core.object.get", "item_type": "function",
                 "category": None, "version": "2025.1", "ok": False,
                 "risk_level": None, "error_code": "TIMEOUT",
                 "message": "Gateway timed out during WAAPI call ak.wwise.core.object.get",
                 "details": details, "evidence_path": "/owned/evidence/query.json"},
        "count": None, "objects": None,
        "details": {"cleanup_failure": {"error_code": "TIMEOUT",
            "message": "Gateway timed out during WAAPI call ak.wwise.core.object.get",
            "details": details}},
        "agent_result": None,
    }


def failure_broker(tmp_path, payload, *, outcome_policy=None):
    value = broker(tmp_path, outcome_policy=outcome_policy)
    value.runner_path.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        f"with Path({str(tmp_path / 'runner-invocations.txt')!r}).open('a') as log: log.write('dispatch\\n')\n"
        f"print(json.dumps({payload!r})); sys.exit(2)\n", encoding="utf-8",
    )
    return value


def test_authentic_public_query_timeout_is_preserved_without_retry_or_safe_checkpoint(tmp_path):
    import json

    payload = query_timeout_receipt()
    with failure_broker(tmp_path, payload) as value:
        failed = invoke(value, "query-object", "--exact-id", OWNER)
        assert failed["exit_code"] == 2
        assert json.loads(failed["stdout"]) == payload
        evidence = value.evidence()
        assert evidence.records[0].succeeded  # Receipt provenance, never read success.
        assert evidence.records[0].payload["agent_result"] is None
        assert evidence.terminal_state == "INDETERMINATE"
        assert not evidence.complete
        assert len(value._expansion_reads.failed_receipts) == 1
        assert value._expansion_reads.receipts == []
        assert invoke(value, "query-object", "--exact-id", OWNER)["exit_code"] == 126
        assert invoke(value, "status")["exit_code"] == 126
        assert len([row for row in value.evidence().records if row.accepted]) == 1
        assert (tmp_path / "runner-invocations.txt").read_text() == "dispatch\n"


@pytest.mark.parametrize("pointer,value", [
    (("call", "error_code"), "UNKNOWN_NESTED_ERROR"),
    (("call", "error_code"), 123),
    (("call", "api"), "ak.wwise.core.object.delete"),
    (("call", "item_type"), "topic"),
    (("call", "ok"), True),
    (("call", "details"), None),
    (("call", "details", "cleanup_pending"), "true"),
    (("call", "details", "elapsed_seconds"), -1),
    (("call", "result"), {"return": []}),
    (("objects",), []),
    (("agent_result",), []),
    (("count",), 0),
    (("details",), None),
    (("command",), "metadata"),
    (("contract",), "other-contract/v1"),
    (("error_code",), "GatewayInputError"),
])
def test_malformed_nested_query_failure_stops_at_receipt_and_never_dispatches_again(tmp_path, pointer, value):
    payload = query_timeout_receipt()
    target = payload
    for key in pointer[:-1]:
        target = target[key]
    target[pointer[-1]] = value
    with failure_broker(tmp_path, payload) as broker_value:
        result = invoke(broker_value, "query-object", "--exact-id", OWNER)
        assert result["exit_code"] == 125
        assert broker_value.evidence().terminal_state == "FAILED"
        assert not broker_value.evidence().records[0].succeeded
        assert broker_value._expansion_reads.failed_receipts == []
        assert invoke(broker_value, "status")["exit_code"] == 126
        assert len([row for row in broker_value.evidence().records if row.accepted]) == 1
        assert (tmp_path / "runner-invocations.txt").read_text() == "dispatch\n"


@pytest.mark.parametrize("payload", [
    {"contract": "waapi-skill.gateway-result/v1", "command": "query-object", "ok": False,
     "call": {"error_code": "TIMEOUT"}},
    {"contract": "waapi-skill.gateway-result/v1", "command": "query-object", "ok": False},
])
def test_bare_query_failure_is_not_an_authenticated_structured_dispatch_receipt(tmp_path, payload):
    with failure_broker(tmp_path, payload) as value:
        assert invoke(value, "query-object", "--exact-id", OWNER)["exit_code"] == 125
        assert value._expansion_reads.failed_receipts == []


def test_post_verification_query_timeout_preserves_verified_write_but_blocks_sealing(tmp_path):
    from tests.semantic.test_codex_expansion_broker_policy import make_policy
    from tests.semantic.support.codex_gateway_broker import GatewayBrokerError

    policy = make_policy()
    # Stand in for the already independently verified transaction checkpoint.
    policy.transaction.state = "verified"
    policy.oracle_evidence["gateway_verification_state"] = "verified"
    with failure_broker(tmp_path, query_timeout_receipt(), outcome_policy=policy) as value:
        assert invoke(value, "query-object", "--exact-id", OWNER)["exit_code"] == 2
        assert policy.transaction.state == "verified"
        assert policy.oracle_evidence["gateway_verification_state"] == "verified"
        assert value.evidence().terminal_state == "INDETERMINATE"
        assert not value.evidence().terminal_indeterminate  # Not ambiguous mutation execution.
        assert policy.reads.receipts == []
        assert len(policy.reads.failed_receipts) == 1
        with pytest.raises(GatewayBrokerError, match="incomplete or has a failed command"):
            value.seal_expansion_outcome()
        assert invoke(value, "query-object", "--exact-id", OWNER)["exit_code"] == 126
        assert len([row for row in value.evidence().records if row.accepted]) == 1
        assert (tmp_path / "runner-invocations.txt").read_text() == "dispatch\n"


@pytest.mark.parametrize("missing", ["count", "objects", "agent_result", "call"])
def test_missing_query_failure_fields_do_not_become_null_by_default(tmp_path, missing):
    payload = query_timeout_receipt()
    del payload[missing]
    with failure_broker(tmp_path, payload) as value:
        assert invoke(value, "query-object", "--exact-id", OWNER)["exit_code"] == 125
        assert value._expansion_reads.failed_receipts == []


def test_query_failure_receipt_byte_ceiling_is_still_enforced(tmp_path):
    payload = query_timeout_receipt()
    payload["call"]["message"] = "x" * (256 * 1024)
    with failure_broker(tmp_path, payload) as value:
        assert invoke(value, "query-object", "--exact-id", OWNER)["exit_code"] == 125
        assert value._expansion_reads.failed_receipts == []
        assert not value.evidence().complete
