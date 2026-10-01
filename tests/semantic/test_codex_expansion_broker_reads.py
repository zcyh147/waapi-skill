"""New-profile bounded reads through the existing authenticated Broker."""

from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_policy import ExpansionReadScope
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker, ExpectedGatewayStep


OWNER = "{11111111-1111-1111-1111-111111111111}"


def broker(tmp_path: Path, *, scope: bool = True, oversized: bool = False):
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
        expected_steps=(ExpectedGatewayStep("done", "status", ()),),
        runner_environment={}, transport="tcp",
        expansion_read_scope=(ExpansionReadScope(
            object_ids=frozenset({OWNER}), operations=frozenset({"audio.import"}),
            fields=frozenset({"Volume"}), max_calls=3,
        ) if scope else None),
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
