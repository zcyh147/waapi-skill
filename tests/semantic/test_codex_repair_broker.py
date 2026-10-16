from pathlib import Path
import json
import pytest
from tests.semantic.support.codex_expansion_cases import PreparedExpansionCase
from tests.semantic.support.codex_repair_broker_policy import RepairBrokerPolicy
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker

SKILL = Path(__file__).parents[2] / "skills/waapi-skill"
TARGET = "{22222222-2222-2222-2222-222222222222}"


def test_read_only_broker_accepts_miss_then_refinement_without_transaction(tmp_path):
    prepared = PreparedExpansionCase(prompt="Find the named parameter, refining a missed spelling.",
        operation="ak.wwise.core.object.get", policy="read_only", before={"unchanged": True},
        read_object_ids=frozenset({TARGET}), relationship_sources=frozenset(), read_includes=frozenset(),
        required_assertions=frozenset({"unchanged", "read_refinement"}), approve_preview=lambda _: False,
        snapshot=lambda: {"unchanged": True}, verify=lambda old, new: {"unchanged": old == new},
        archive_oracle_parameters={"target_id": TARGET})
    policy = RepairBrokerPolicy(prepared=prepared, version="2025.1", skill_source=SKILL, scoped_paths={TARGET: r"\Game Parameters\Target"})
    policy.begin_turn(1)
    fake = tmp_path / "skill"
    (fake / "scripts").mkdir(parents=True)
    (fake / "scripts/run.py").write_text('''import json,sys
rows = [] if "Missing" in sys.argv else [{"id": "{22222222-2222-2222-2222-222222222222}", "name":"Target", "type":"GameParameter", "path":"\\\\Game Parameters\\\\Target"}]
print(json.dumps({"contract":"waapi-skill.gateway-result/v1", "ok":True, "command":"query-object", "objects":rows, "count":len(rows), "query_bound":{"mode":"take", "value":10}, "limit_reached":False}))
''')
    with CodexGatewayBroker(skill_source=fake, expected_steps=(), runner_environment={}, transport="tcp", expansion_outcome_policy=policy) as broker:
        def invoke(*args):
            return broker._handle_request({"token": broker._token, "interpreter": "python",
                "argv": [str(broker.runner_path), "gateway.py", *args]})
        assert invoke("query-object", "--search-text", "Missing", "--max-results", "10")["exit_code"] == 0
        assert not policy.complete
        assert invoke("query-object", "--search-text", "Target", "--max-results", "10")["exit_code"] == 0
        policy.finish_read()
        assert policy.complete
        broker.seal_expansion_outcome()
        assert broker.evidence().complete
        assert not (broker.state_directory / "transactions").exists()


@pytest.mark.parametrize("argv", [("draft-start", "object.create"), ("execute", "tx1-other"), ("confirm", "tx1-other")])
def test_read_only_repair_rejects_write_lane_before_dispatch(tmp_path, argv):
    from tests.semantic.support.codex_expansion_policy import ExpansionPolicyError
    prepared = PreparedExpansionCase(prompt="Read only", operation="ak.wwise.core.object.get", policy="read_only",
        before={}, read_object_ids=frozenset({TARGET}), relationship_sources=frozenset(), read_includes=frozenset(),
        required_assertions=frozenset({"read_refinement"}), approve_preview=lambda _: False,
        snapshot=lambda: {}, verify=lambda *_: {})
    policy = RepairBrokerPolicy(prepared=prepared, version="2025.1", skill_source=SKILL, scoped_paths={})
    policy.begin_turn(1)
    with pytest.raises(ExpansionPolicyError):
        policy.prepare(argv, state_directory=tmp_path)
