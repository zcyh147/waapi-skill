"""Explicit populated Transition scalar investigation; no Fresh or M04 credit."""
import pytest

from tests.destructive.test_expansion_case_preflight import expansion_runtime
from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
from tests.semantic.support.codex_music_oracle_probes import xml_music_witness
from tests.semantic.support.codex_music_switch_reference_goal import append_bounded_goal_receipt
from tests.semantic.support.codex_music_transition_goal import run_transition_scalar_goal, transition_scalar_snapshot

pytestmark = [pytest.mark.live, pytest.mark.destructive]


def test_existing_transition_boolean_preserves_populated_rule_graph(expansion_runtime):
    runtime = expansion_runtime
    relative = ('Interactive Music Hierarchy/Music.wwu' if runtime.version == '2022.1' else 'Containers/Music/Music.wwu')
    owned = runtime.sandbox.sandbox_path / relative
    owned.resolve(strict=True).relative_to(runtime.sandbox.sandbox_path.resolve(strict=True))
    witness = xml_music_witness(owned, runtime.version)
    receipts = []
    report = {'category': 'music-transition-populated-scalar-goal', 'status': 'FAIL',
        'scope': 'existing_post_exit_boolean_and_saved_sibling_graph_not_full_M04',
        'agent_pass': False, 'scalar_maintenance_verified': False, 'complete_M04_verified': False,
        'gateway_receipts': receipts, 'transaction_ids': [], 'xml_witness': witness}
    runtime.category_results.append(report)
    def gateway(argv):
        if len(receipts) >= 128:
            raise AssertionError('Transition scalar goal exceeded its public call ceiling')
        code, payload = runtime.raw_gateway(argv)
        append_bounded_goal_receipt(receipts, argv, code, payload)
        assert code == 0 and payload.get('ok') is True, payload
        if payload.get('transaction_id') and argv[0] in {'preview-from-draft', 'typed-zero-call'}:
            report['transaction_ids'].append(payload['transaction_id'])
        if payload.get('endpoint') is not None:
            assert payload['endpoint'] == {'host': runtime.lifecycle.host, 'port': runtime.port, 'url': runtime.lifecycle.waapi_url}
        if payload.get('detected_version') is not None:
            assert payload['detected_version'] == runtime.version
        return payload
    ctx = ExpansionCaseContext(runtime.version, 'TRANSITION_SCALAR_GOAL', runtime.sandbox.sandbox_project,
        runtime.sandbox.sandbox_path / 'TransitionGoalAssets', gateway)
    result = run_transition_scalar_goal(ctx, witness, lambda: transition_scalar_snapshot(ctx, owned, witness))
    report.update(result)
