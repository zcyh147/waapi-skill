from pathlib import Path
import json
import pytest
from tests.semantic.support.codex_expansion_cases import PreparedExpansionCase
from tests.semantic.support.codex_repair_broker_policy import RepairBrokerPolicy
from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker

SKILL = Path(__file__).parents[2] / "skills/waapi-skill"
TARGET = "{22222222-2222-2222-2222-222222222222}"


@pytest.mark.parametrize("projection", ["complete", "split", "id_only", "missing", "wrong_identity", "wrong_value"])
def test_read_only_broker_requires_agent_visible_identity_and_values(tmp_path, projection):
    expected = {"name": "Target", "type": "GameParameter", "path": r"\Game Parameters\Target",
                "properties": {"Min": -12, "Max": 36, "InitialValue": 7}}
    prepared = PreparedExpansionCase(prompt="Find the named parameter, refining a missed spelling.",
        operation="ak.wwise.core.object.get", policy="read_only", before={"unchanged": True},
        read_object_ids=frozenset({TARGET}), relationship_sources=frozenset(), read_includes=frozenset(),
        required_assertions=frozenset({"unchanged", "read_refinement"}), approve_preview=lambda _: False,
        snapshot=lambda: {"unchanged": True}, verify=lambda old, new: {"unchanged": old == new},
        archive_oracle_parameters={"target_id": TARGET, "expected": expected})
    policy = RepairBrokerPolicy(prepared=prepared, version="2025.1", skill_source=SKILL, scoped_paths={TARGET: r"\Game Parameters\Target"})
    policy.begin_turn(1)
    fake = tmp_path / "skill"
    (fake / "scripts").mkdir(parents=True)
    target = {"id": TARGET, **expected}
    if projection == "id_only":
        target = {"id": TARGET}
    elif projection == "split":
        target = {key: value for key, value in target.items() if key != "properties"}
    elif projection == "missing":
        target = {**target, "properties": {"Min": -12, "Max": 36}}
    elif projection == "wrong_identity":
        target = {**target, "name": "Other"}
    elif projection == "wrong_value":
        target = {**target, "properties": {**expected["properties"], "InitialValue": 8}}
    (fake / "scripts/run.py").write_text(
        "import json,sys\n"
        + "target = " + repr(target) + "\n"
        + "values = " + repr(expected["properties"]) + "\n"
        + "if '--include-field' in sys.argv:\n field = sys.argv[sys.argv.index('--include-field')+1]; target['properties']={field:values[field]}\n"
        + "rows = [] if 'Missing' in sys.argv else [target]\n"
        + "bound = {'mode':'exact-object'} if '--exact-id' in sys.argv else {'mode':'take','value':10}\n"
        + "print(json.dumps({'contract':'waapi-skill.gateway-result/v1','ok':True,'command':'query-object','objects':rows,'count':len(rows),'query_bound':bound,'limit_reached':False}))\n")
    with CodexGatewayBroker(skill_source=fake, expected_steps=(), runner_environment={}, transport="tcp", expansion_outcome_policy=policy) as broker:
        def invoke(*args):
            return broker._handle_request({"token": broker._token, "interpreter": "python",
                "argv": [str(broker.runner_path), "gateway.py", *args]})
        assert invoke("query-object", "--search-text", "Missing", "--max-results", "10")["exit_code"] == 0
        assert not policy.complete
        assert invoke("query-object", "--search-text", "Target", "--max-results", "10")["exit_code"] == 0
        if projection == "split":
            for field in ("Min", "Max", "InitialValue"):
                assert invoke("query-object", "--exact-id", TARGET, "--include-field", field)["exit_code"] == 0
        policy.finish_read()
        assert policy.complete is (projection in {"complete", "split"})
        if policy.complete:
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
