"""Original program collection and producer controls; no native credit."""
from copy import deepcopy
import hashlib
from pathlib import Path
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evidence_result, installed_obligations
from tests.support import condition_branch_evidence, condition_scalar_batch
from tests.support import condition_scalar_program as producer
from tests.unit.test_scalar_condition_product_gateway import run_scalar_public_workflow, run_scalar_public_group


@pytest.fixture(scope="module")
def source_inputs():
    root = Path(__file__).parents[2]
    plan = condition_scalar_batch.scalar_plan(condition_scalar_batch.scalar_manifest(root))
    group = next(g for g in plan["groups"] if g["version"] == "2025.1" and g["field"] == "GainBand1")
    owned = installed_obligations(root, digest=audit.digest, load=audit.load)
    ids = {m["id"] for m in group["members"]} | {condition_branch_evidence.SHOW_BRANCH_ID}
    branches = {b["id"]: b for b in owned if b["id"] in ids}
    inventory = {"native_coverage": {"candidate_sha256": "c" * 64, "obligations": list(branches.values())},
                 "routes": [{"id": "2025.1|function|ak.wwise.core.object.setProperty"}]}
    return {**plan, "groups": [group]}, inventory, branches


@pytest.fixture(scope='module')
def exact_receiver_inputs():
    root = Path(__file__).parents[2]
    plan = condition_scalar_batch.scalar_plan(condition_scalar_batch.scalar_manifest(root, resolve_exact_receivers=True))
    group = next(g for g in plan['groups'] if g['version'] == '2025.1' and g['field'] == 'Max')
    ids = {m['id'] for m in group['members']} | {condition_branch_evidence.SHOW_BRANCH_ID}
    branches = {b['id']: b for b in installed_obligations(root, digest=audit.digest, load=audit.load) if b['id'] in ids}
    inventory = {'native_coverage': {'candidate_sha256': 'c' * 64, 'obligations': list(branches.values())},
        'routes': [{'id': '2025.1|function|ak.wwise.core.object.setProperty'}]}
    return {**plan, 'groups': [group]}, inventory


@pytest.mark.parametrize('damage', ['wrong-receiver', 'missing-model-provenance'])
def test_exact_receiver_producer_refuses_generic_identity_or_missing_source_model_provenance(tmp_path, request, exact_receiver_inputs, damage):
    plan, inventory = deepcopy(exact_receiver_inputs)
    group = plan['groups'][0]
    capture = producer.prepare_program_batch(tmp_path / 'capture', [request.node.nodeid], plan, inventory)
    observed = run_scalar_public_group(tmp_path / 'workflow', group)
    for flow in observed['workflows'].values():
        if damage == 'wrong-receiver':
            flow['observations']['before']['type'] = 'Sound'
            flow['observations']['after']['type'] = 'Sound'
        else:
            del flow['input_fact_provenance']
    with pytest.raises(ValueError, match='exact source receiver'):
        producer.finish_program_node(capture, request.node.nodeid,
            {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, {group['id']: observed})
    assert not (capture['root'] / 'batch-final.json').exists()


def test_exact_receiver_controlled_producer_seals_original_class_fixture_and_each_member(tmp_path, request, exact_receiver_inputs):
    plan, inventory = deepcopy(exact_receiver_inputs)
    group = plan['groups'][0]
    capture = producer.prepare_program_batch(tmp_path / 'capture', [request.node.nodeid], plan, inventory)
    fixture = group['model']['source_receiver']['native_class_fixture']
    assert capture['relevant_sources'][fixture['path']] == fixture['sha256']
    observed = run_scalar_public_group(tmp_path / 'workflow', group)
    producer.finish_program_node(capture, request.node.nodeid,
        {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, {group['id']: observed})
    published = capture['root'] / 'published'
    bindings = json.loads((published / 'bindings.json').read_text())['bindings']
    assert set(bindings) == {m['id'] for m in group['members']}
    branches = {b['id']: b for b in inventory['native_coverage']['obligations']}
    for identity, binding in bindings.items():
        assert evidence_result(binding['evidence']['program'], branches[identity], 'c' * 64,
            'program', 'controlled', published, binding) == ('passed', None)
        assert evidence_result(binding['evidence']['program'], branches[identity], 'c' * 64,
            'program', 'product', published, binding)[0] == 'missing'


def test_original_batch_has_explicit_per_id_observations_without_product_credit(tmp_path, request, source_inputs):
    plan, inventory, branches = deepcopy(source_inputs)
    capture = producer.prepare_program_batch(tmp_path / "capture", [request.node.nodeid], plan, inventory,
                                             scope_kind="controlled")
    group = plan["groups"][0]
    observation = run_scalar_public_group(tmp_path / "workflow", group)
    producer.finish_program_node(capture, request.node.nodeid,
        {"setup": "passed", "call": "passed", "teardown": "passed"}, {group["id"]: observation})
    published = capture["root"] / "published"
    bindings = json.loads((published / "bindings.json").read_text())["bindings"]
    assert set(bindings) == {m["id"] for m in group["members"]}
    assert not (published / "requirements.json").exists()
    for identity, binding in bindings.items():
        status, reason = evidence_result(binding["evidence"]["program"], branches[identity], "c" * 64,
            "program", "controlled", published, binding)
        assert (status, reason) == ("passed", None)
        status, reason = evidence_result(binding["evidence"]["program"], branches[identity], "c" * 64,
            "program", "product", published, binding)
        assert status == "missing" and "controlled evidence" in reason


@pytest.mark.parametrize("damage", ["wrong-node", "missing-field", "extra-field", "metadata-value", "controller",
                                   "changed-field", "typed-field", "wrong-write", "unverified", "changed-plan", "changed-source"])
def test_original_batch_refuses_incomplete_or_changed_member_proof(tmp_path, request, source_inputs, damage):
    plan, inventory, _ = deepcopy(source_inputs)
    capture = producer.prepare_program_batch(tmp_path / "capture", [request.node.nodeid], plan, inventory, scope_kind="controlled")
    group = plan["groups"][0]
    observed = run_scalar_public_group(tmp_path / "workflow", group)
    observations = {group["id"]: observed}
    flow_observed = next(iter(observed["workflows"].values()))
    node = request.node.nodeid
    if damage == "wrong-node": node = "unexecuted-node"
    if damage == "missing-field": observations.clear()
    if damage == "extra-field": observations["not-predeclared"] = deepcopy(observed)
    if damage == "metadata-value": flow_observed["observations"]["metadata"]["dependencies"][0]["conditions"][0]["restriction"]["values"][0]["value"] = 1
    if damage == "controller": flow_observed["observations"]["before"]["OnOffBand1"] = False
    if damage == "changed-field": flow_observed["observations"]["after"]["GainBand1"] = 999
    if damage == "typed-field": flow_observed["observations"]["after"]["GainBand1"] = int(group["model"]["requested"])
    if damage == "wrong-write": flow_observed["native_call"]["args"]["property"] = "OtherField"
    if damage == "unverified": flow_observed["gateway"]["payload"]["verified"] = False
    if damage == "changed-plan": capture["plan"]["credit"] = "invented-credit"
    if damage == "changed-source": capture["relevant_sources"][next(iter(capture["relevant_sources"]))] = "0" * 64
    with pytest.raises((ValueError, AssertionError)):
        producer.finish_program_node(capture, node, {"setup": "passed", "call": "passed", "teardown": "passed"}, observations)
    assert not (capture["root"] / "published").exists()


@pytest.mark.parametrize("reports", [{"setup": "passed", "call": "passed"},
    {"setup": "passed", "call": "passed", "teardown": "failed"}])
def test_late_or_missing_reports_withhold_the_whole_original_batch(tmp_path, request, source_inputs, reports):
    plan, inventory, _ = deepcopy(source_inputs)
    capture = producer.prepare_program_batch(tmp_path / "capture", [request.node.nodeid], plan, inventory, scope_kind="controlled")
    group = plan["groups"][0]
    observed = run_scalar_public_group(tmp_path / "workflow", group)
    producer.finish_program_node(capture, request.node.nodeid, reports, {group["id"]: observed})
    assert not (capture["root"] / "published").exists()
    assert not (capture["root"] / "batch-final.json").exists()
    assert not (capture["root"] / "published").exists()
    assert json.loads((capture["root"] / "outcome.json").read_text())["outcome"] == "FAIL"
    assert list(capture["root"].glob("observations-*.json"))


@pytest.mark.parametrize("phase", ["directory", "final-seal"])
def test_unpublished_staged_program_cannot_bypass_final_publication_failure(tmp_path, request, source_inputs, monkeypatch, phase):
    plan, inventory, branches = deepcopy(source_inputs)
    capture = producer.prepare_program_batch(tmp_path / "capture", [request.node.nodeid], plan, inventory, scope_kind="controlled")
    group = plan["groups"][0]
    observed = run_scalar_public_group(tmp_path / "workflow", group)
    original_rename = Path.rename
    def fail_publication(source, target):
        if (phase == "directory" and source.name.startswith(".program-pending-")) or (phase == "final-seal" and source.name == ".batch-final.pending"):
            raise OSError("original publication failed")
        return original_rename(source, target)
    monkeypatch.setattr(Path, "rename", fail_publication)
    with pytest.raises(OSError, match="original publication failed"):
        producer.finish_program_node(capture, request.node.nodeid,
            {"setup": "passed", "call": "passed", "teardown": "passed"}, {group["id"]: observed})
    assert (capture["root"] / "published").exists() is (phase == "final-seal")
    assert not (capture["root"] / "batch-final.json").exists()
    staged = capture["root"] / "published" if phase == "final-seal" else next(capture["root"].glob(".program-pending-*"))
    bindings = json.loads((staged / "bindings.json").read_text())["bindings"]
    identity, binding = next(iter(bindings.items()))
    original = staged / Path(binding["evidence"]["program"]["artifact"]).name
    descriptor = {**binding["evidence"]["program"], "artifact": str(original),
                  "sha256": hashlib.sha256(original.read_bytes()).hexdigest()}
    status, reason = evidence_result(descriptor, branches[identity], "c" * 64, "program", "controlled", staged, binding)
    assert status == "missing" and "batch-final.json" in reason


def test_source_model_batch_cannot_emit_product_evidence_without_reviewed_requirements(tmp_path, source_inputs):
    plan, inventory, _ = deepcopy(source_inputs)
    node = "tests/unit/test_scalar_condition_product_gateway.py::test_product_self_scalar_source_conditions[2025.1]"
    with pytest.raises(ValueError, match="reviewed requirements"):
        producer.prepare_program_batch(tmp_path / "capture", [node], plan, inventory, scope_kind="product")
    assert not (tmp_path / "capture").exists()


def test_no_batch_receipt_is_published_before_all_selected_nodes_report(tmp_path, request, source_inputs):
    plan, inventory, _ = deepcopy(source_inputs)
    last_node = request.node.nodeid + "-last-node-control"
    capture = producer.prepare_program_batch(tmp_path / "capture", [request.node.nodeid, last_node], plan, inventory, scope_kind="controlled")
    group = plan["groups"][0]
    observed = run_scalar_public_group(tmp_path / "workflow", group)
    reports = {"setup": "passed", "call": "passed", "teardown": "passed"}
    producer.finish_program_node(capture, request.node.nodeid, reports, {group["id"]: observed})
    assert not (capture["root"] / "published").exists()
    producer.finish_program_node(capture, last_node, {**reports, "teardown": "failed"}, {})
    assert not (capture["root"] / "batch-final.json").exists()


def test_each_enum_choice_runs_a_real_public_workflow_with_that_controller_value(tmp_path, source_inputs):
    from tests.unit import test_scalar_condition_product_gateway as workflows
    plan, _, _ = deepcopy(source_inputs)
    group = plan["groups"][0]
    observed = workflows.run_scalar_public_group(tmp_path / "workflows", group)
    assert {value["observations"]["before"]["FilterTypeBand1"] for value in observed["workflows"].values()} == {4, 5, 6}
    assert all(value["gateway"]["payload"]["verified"] is True for value in observed["workflows"].values())
    assert all(value["observations"]["after"]["FilterTypeBand1"] == value["observations"]["before"]["FilterTypeBand1"]
               for value in observed["workflows"].values())


def test_independent_group_failures_are_aggregated_with_partial_original_observations(tmp_path, monkeypatch):
    from tests.unit import test_scalar_condition_product_gateway as workflows
    calls, observed = [], {}
    def run(path, group, *, before_values=None):
        calls.append(group['id'])
        if group['id'] == 'first' and len(calls) == 2:
            raise AssertionError('λ' * 10000)
        return {'original': group['id'], 'before': before_values}
    monkeypatch.setattr(workflows, 'run_scalar_public_workflow', run)
    groups = {identity: {'id': identity, 'workflows': [{'id': str(i), 'before': {'Gate': i}} for i in range(2)],
        'negative_controls': []} for identity in ('first', 'second')}
    failures = workflows.run_original_scalar_groups(tmp_path, groups, list(groups), observed)
    assert calls == ['first', 'first', 'second', 'second']
    assert set(failures) == {'first'}
    assert failures['first']['error_type'] == 'AssertionError'
    assert len(failures['first']['message'].encode('utf-8')) <= 4096
    assert set(observed['first']['workflows']) == {'0'}
    assert set(observed['second']['workflows']) == {'0', '1'}
    assert observed['first']['failure'] == failures['first']


def test_failed_group_marker_cannot_publish_even_with_incorrect_pass_reports(tmp_path, request, source_inputs):
    plan, inventory, _ = deepcopy(source_inputs)
    capture = producer.prepare_program_batch(tmp_path / 'capture', [request.node.nodeid], plan, inventory)
    group = plan['groups'][0]
    observed = run_scalar_public_group(tmp_path / 'workflow', group)
    observed['failure'] = {'error_type': 'AssertionError', 'message': 'original group failed'}
    with pytest.raises(ValueError, match='failed original group'):
        producer.finish_program_node(capture, request.node.nodeid,
            {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, {group['id']: observed})
    assert not (capture['root'] / 'published').exists()
    assert not (capture['root'] / 'batch-final.json').exists()


def test_missing_enum_behavior_cannot_be_replaced_by_its_disclosed_metadata(tmp_path, request, source_inputs):
    plan, inventory, _ = deepcopy(source_inputs)
    capture = producer.prepare_program_batch(tmp_path / "capture", [request.node.nodeid], plan, inventory, scope_kind="controlled")
    group = plan["groups"][0]
    flow = group["workflows"][0]
    observed = run_scalar_public_workflow(tmp_path / "workflow", group, before_values=flow["before"])
    with pytest.raises(ValueError, match="behavioral workflows"):
        producer.finish_program_node(capture, request.node.nodeid,
            {"setup": "passed", "call": "passed", "teardown": "passed"},
            {group["id"]: {"workflows": {flow["id"]: observed}, "negative_controls": {}}})
    assert not (capture["root"] / "batch-final.json").exists()


def test_range_endpoints_interior_and_outside_value_have_actual_public_observations(tmp_path, request):
    root = Path(__file__).parents[2]
    plan = condition_scalar_batch.scalar_plan(condition_scalar_batch.scalar_manifest(root))
    group = next(g for g in plan['groups'] if g['version'] == '2025.1' and g['field'] == 'EnvelopeStopPlayback')
    plan['groups'] = [group]
    owned = installed_obligations(root, digest=audit.digest, load=audit.load)
    ids = {m['id'] for m in group['members']} | {condition_branch_evidence.SHOW_BRANCH_ID}
    branches = {b['id']: b for b in owned if b['id'] in ids}
    inventory = {'native_coverage': {'candidate_sha256': 'c' * 64, 'obligations': list(branches.values())},
        'routes': [{'id': '2025.1|function|ak.wwise.core.object.setProperty'}]}
    capture = producer.prepare_program_batch(tmp_path / 'capture', [request.node.nodeid], plan, inventory)
    observed = run_scalar_public_group(tmp_path / 'workflow', group)
    assert {flow['observations']['before']['TimeModLoops'] for flow in observed['workflows'].values()} == {1, 50, 100}
    assert all(control['before']['TimeModLoops'] == 0 and control['mutation_calls'] == [] for control in observed['negative_controls'].values())
    producer.finish_program_node(capture, request.node.nodeid,
        {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, {group['id']: observed})
    published = capture['root'] / 'published'
    bindings = json.loads((published / 'bindings.json').read_text())['bindings']
    for identity, binding in bindings.items():
        assert evidence_result(binding['evidence']['program'], branches[identity], 'c' * 64,
            'program', 'controlled', published, binding) == ('passed', None)


@pytest.mark.parametrize('damage', ['wrong-choice-linkage', 'missing-range-workflow', 'missing-outside-control'])
def test_behavior_linkage_and_range_controls_are_required_before_publication(tmp_path, request, damage):
    root = Path(__file__).parents[2]
    plan = condition_scalar_batch.scalar_plan(condition_scalar_batch.scalar_manifest(root))
    group = next(g for g in plan['groups'] if g['version'] == '2025.1' and g['field'] == (
        'GainBand1' if damage == 'wrong-choice-linkage' else 'EnvelopeStopPlayback'))
    plan['groups'] = [group]
    if damage == 'wrong-choice-linkage':
        member = next(m for m in group['members'] if '/value/' in m['alternative'] and m['expected'] == 6)
        member['behavioral_workflow_ids'] = [next(f['id'] for f in group['workflows'] if f['before']['FilterTypeBand1'] == 4)]
    owned = installed_obligations(root, digest=audit.digest, load=audit.load)
    ids = {m['id'] for m in group['members']} | {condition_branch_evidence.SHOW_BRANCH_ID}
    inventory = {'native_coverage': {'candidate_sha256': 'c' * 64, 'obligations': [b for b in owned if b['id'] in ids]},
        'routes': [{'id': '2025.1|function|ak.wwise.core.object.setProperty'}]}
    capture = producer.prepare_program_batch(tmp_path / 'capture', [request.node.nodeid], plan, inventory)
    observed = run_scalar_public_group(tmp_path / 'workflow', group)
    if damage == 'missing-range-workflow':
        observed['workflows'].pop(next(iter(observed['workflows'])))
    if damage == 'missing-outside-control':
        observed['negative_controls'].clear()
    with pytest.raises(ValueError, match='behavior|outside-value'):
        producer.finish_program_node(capture, request.node.nodeid,
            {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, {group['id']: observed})
    assert not (capture['root'] / 'batch-final.json').exists()


@pytest.fixture(scope='module')
def reviewed_source_inputs():
    from tests.support import condition_scalar_requirements as requirements
    root = Path(__file__).parents[2]
    plan = condition_scalar_batch.scalar_plan(condition_scalar_batch.scalar_manifest(root))
    return plan, requirements.load_program_review(root), audit.build_inventory()


def test_product_program_requires_exact_review_but_keeps_native_and_metadata_missing(tmp_path, request, reviewed_source_inputs):
    from tests.support import condition_scalar_requirements as requirements
    from tests.maintenance.branch_audit_completion import evaluate_coverage
    root = Path(__file__).parents[2]
    plan, review, inventory = reviewed_source_inputs
    group = next(g for g in plan['groups'] if g['version'] == '2025.1' and g['field'] == 'GainBand1')
    capture = producer.prepare_program_batch(tmp_path / 'capture', [request.node.nodeid], plan, inventory,
        scope_kind='product', reviewed_requirements=review, node_groups={request.node.nodeid: [group['id']]})
    producer.finish_program_node(capture, request.node.nodeid,
        {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'},
        {group['id']: run_scalar_public_group(tmp_path / 'workflow', group)})
    published = capture['root'] / 'published'
    bindings = json.loads((published / 'bindings.json').read_text())
    policies = json.loads((published / 'requirements.json').read_text())
    result = evaluate_coverage(root, inventory, bindings, digest=audit.digest, evidence_base=published,
        requirements_document=policies)
    rows = {row['id']: row for row in result['obligations']}
    for identity, binding in bindings['bindings'].items():
        assert rows[identity]['state'] == 'implemented_unverified', rows[identity]
        assert rows[identity]['evidence_results']['program']['outcome'] == 'passed'
        assert rows[identity]['evidence_results']['native']['outcome'] == 'missing'
        assert rows[identity]['evidence_results']['live_metadata']['outcome'] == 'missing'
        assert evidence_result(binding['evidence']['program'], rows[identity], inventory['native_coverage']['candidate_sha256'],
            'program', 'controlled', published, binding)[0] == 'missing'
    unresolved = plan['unresolved'][0]['id']
    assert unresolved in policies['branches'] and unresolved not in bindings['bindings']
    assert rows[unresolved]['state'] == 'unresolved'
    assert not result['completion']['complete']


@pytest.mark.parametrize('damage', ['native-category', 'unresolved-member', 'shape', 'partial-plan',
    'extra-node', 'duplicate-group', 'unknown-group', 'missing-inventory-member'])
def test_product_admission_cannot_relax_reviewed_categories_members_or_roster(tmp_path, request, reviewed_source_inputs, damage):
    plan, review, inventory = reviewed_source_inputs
    plan, review = deepcopy(plan), deepcopy(review)
    group = next(g for g in plan['groups'] if g['version'] == '2025.1' and g['field'] == 'GainBand1')
    roster = {request.node.nodeid: [group['id']]}
    identity = group['members'][0]['id']
    if damage == 'native-category': review['requirements']['branches'][identity]['categories'].remove('native')
    if damage == 'unresolved-member': plan['unresolved'].pop()
    if damage == 'shape': review['requirements']['branches'][identity]['native_shape_sha256'] = '0' * 64
    if damage == 'partial-plan': plan['groups'] = [group]
    if damage == 'extra-node': roster['not-selected-original-node'] = []
    if damage == 'duplicate-group': roster[request.node.nodeid].append(group['id'])
    if damage == 'unknown-group': roster[request.node.nodeid].append('unreviewed-source-group')
    if damage == 'missing-inventory-member':
        inventory = {**inventory, 'native_coverage': {**inventory['native_coverage'],
            'obligations': [b for b in inventory['native_coverage']['obligations'] if b['id'] != plan['unresolved'][0]['id']]}}
    with pytest.raises(ValueError, match='reviewed|roster'):
        producer.prepare_program_batch(tmp_path / 'capture', [request.node.nodeid], plan, inventory,
            scope_kind='product', reviewed_requirements=review, node_groups=roster)
    assert not (tmp_path / 'capture').exists()


def test_product_node_roster_is_frozen_before_any_workflow_executes(tmp_path, request, reviewed_source_inputs):
    plan, review, inventory = reviewed_source_inputs
    group = next(g for g in plan['groups'] if g['version'] == '2025.1' and g['field'] == 'GainBand1')
    node = request.node.nodeid
    capture = producer.prepare_program_batch(tmp_path / 'capture', [node], plan, inventory,
        scope_kind='product', reviewed_requirements=review, node_groups={node: [group['id']]})
    capture['node_groups'][node] = []
    capture['selected_group_ids'] = []
    with pytest.raises(ValueError, match='predeclared.*roster'):
        producer.finish_program_node(capture, node, {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, {})
    assert not (capture['root'] / 'batch-final.json').exists()


@pytest.mark.parametrize('damage', ['requirements-source', 'requirements-artifact', 'missing-workflow', 'wrong-workflow'])
def test_product_capture_withholds_program_on_source_policy_or_behavior_drift(tmp_path, request, reviewed_source_inputs, damage):
    plan, review, inventory = reviewed_source_inputs
    group = next(g for g in plan['groups'] if g['version'] == '2025.1' and g['field'] == 'GainBand1')
    node = request.node.nodeid
    capture = producer.prepare_program_batch(tmp_path / 'capture', [node], plan, inventory,
        scope_kind='product', reviewed_requirements=review, node_groups={node: [group['id']]})
    observed = run_scalar_public_group(tmp_path / 'workflow', group)
    if damage == 'requirements-source': capture['relevant_sources']['tests/support/condition_scalar_requirements.py'] = '0' * 64
    if damage == 'requirements-artifact': (capture['root'] / 'requirements.json').write_text('{}')
    if damage == 'missing-workflow': observed['workflows'].pop(next(iter(observed['workflows'])))
    if damage == 'wrong-workflow':
        flow = next(iter(observed['workflows'].values()))
        flow['observations']['before']['FilterTypeBand1'] = 6 if flow['observations']['before']['FilterTypeBand1'] != 6 else 4
    with pytest.raises(ValueError):
        producer.finish_program_node(capture, node, {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, {group['id']: observed})
    assert not (capture['root'] / 'published').exists()


def test_failed_original_product_node_retains_partial_observations_without_program_pass(tmp_path, request, reviewed_source_inputs):
    plan, review, inventory = reviewed_source_inputs
    group = next(g for g in plan['groups'] if g['version'] == '2025.1' and g['field'] == 'GainBand1')
    node = request.node.nodeid
    capture = producer.prepare_program_batch(tmp_path / 'capture', [node], plan, inventory,
        scope_kind='product', reviewed_requirements=review, node_groups={node: [group['id']]})
    producer.finish_program_node(capture, node, {'setup': 'passed', 'call': 'failed', 'teardown': 'passed'}, {})
    assert (capture['root'] / 'observations-1.json').exists()
    assert json.loads((capture['root'] / 'outcome.json').read_text())['outcome'] == 'FAIL'
    assert not (capture['root'] / 'batch-final.json').exists()
