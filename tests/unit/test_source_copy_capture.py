"""Frozen Source capture accepts only the reviewed complete dependencies."""
import json
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit


@pytest.fixture(scope='module')
def inventory():
    return audit.build_inventory()


def test_source_capture_rejects_omitted_runtime_or_current_producer_dependencies(tmp_path, inventory):
    from tests.support.source_copy_branch_evidence import source_capture_plan, load_source_capture, write_json
    context = source_capture_plan(tmp_path / 'output', inventory=inventory)
    assert len(context['nodes']) == 5
    assert {'tests/conftest.py', 'tests/support/host_path_relatives.py',
        'tests/support/exact_evidence_finalization.py', 'tests/fixtures/source-copy/2021-native-donor.json',
        'tests/fixtures/source-copy/2021-native-donor.wwu'} <= set(context['relevant_sources'])
    assert {'tests/unit/test_source_copy_repeated_fixture.py', 'tests/unit/test_source_copy_modern_collector.py',
        'tests/unit/test_source_copy_saved_continuation_gateway.py', 'tests/support/gateway_config.py',
        'tests/support/source_copy_branch_evidence.py'} <= set(context['capture_sources'])
    path = tmp_path / 'context.json'
    write_json(path, context)
    node = next(iter(context['nodes']))
    assert load_source_capture(path, node)['nodeid'] == node
    for key, dependency in [('relevant_sources', 'tests/conftest.py'),
                            ('capture_sources', 'tests/unit/test_source_copy_saved_continuation_gateway.py')]:
        altered = json.loads(json.dumps(context))
        del altered[key][dependency]
        write_json(path, altered)
        with pytest.raises(ValueError, match='frozen Source capture'):
            load_source_capture(path, node)


def test_2021_portable_source_keeps_seven_roles_and_untyped_control_input(tmp_path, inventory):
    from pathlib import Path
    from tests.unit.test_source_copy_repeated_fixture import repeated_collector_runtime
    from tests.unit.test_workflow_source_guard import workflow
    from tests.support.source_copy_branch_evidence import write_source_program_bundle
    from tests.maintenance import branch_audit_completion as completion
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv('WWISE_LIVE', '1'); environment.setenv('WWISE_DESTRUCTIVE', '1')
        import importlib
        collector = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    public = tmp_path / 'public'; public.mkdir()
    runtime, _, _ = repeated_collector_runtime(public)
    category = collector._collect_legacy_source_copy_feasibility(runtime, prefix='SOURCE_2021', saved_copy=True,
        saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile='2021-native-donor-two-properties/v1')
    index = write_source_program_bundle(tmp_path / 'portable', Path(category['observation_path']),
        inventory=inventory, nodeid='controlled-source-2021', phase_reports={
            'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, scope_kind='controlled')
    # Original absolute evidence is deliberately made unavailable.
    runtime.state_dir.rename(runtime.state_dir.with_name('state-unavailable'))
    bindings, base, projection = audit.portable_binding_inputs(index, json.loads((index.parent / 'requirements.json').read_bytes()))
    assert len(bindings['bindings']) == 4
    assert projection['source_business_facts'] == ['2021.1|source-copy-synth-owned-graph']
    proof = json.loads((base / 'proof.json').read_bytes())
    receipt = completion.read_sealed_artifact(proof['files'][proof['receipt']['path']], base)
    assert len(receipt['oracle']['owned_guid_mapping']) == 7
    assert receipt['oracle']['ordered_point_count'] == 4
    assert 'copied_native_fields_preserved' not in receipt['oracle']
    snapshots = completion.read_sealed_artifact(proof['files'][receipt['fixture_acceptance']['scalar_observation']['path']], base)
    assert snapshots['Osc1Level.rtpc']['untyped_reference_metadata']['ControlInput']['type'] == ''


def test_product_source_finalizer_needs_complete_phases_and_frozen_sources(tmp_path, inventory):
    from tests.support.source_copy_branch_evidence import source_capture_plan, finish_source_capture
    from tests.unit.test_source_copy_modern_collector import modern_collector_runtime
    from pathlib import Path
    import importlib
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv('WWISE_LIVE', '1'); environment.setenv('WWISE_DESTRUCTIVE', '1')
        workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
    public = tmp_path / 'public'; public.mkdir()
    runtime, _, _ = modern_collector_runtime(public)
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='FINALIZER', saved_copy=True,
        saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile='modern-original-owned-source/v1')
    plan = source_capture_plan(tmp_path / 'product', inventory=inventory)
    node = next(key for key, value in plan['nodes'].items() if value['version'] == '2022.1')
    context = {**plan, **plan['nodes'][node], 'nodeid': node}
    with pytest.raises(ValueError, match='complete successful phases'):
        finish_source_capture(context, {'setup': 'passed', 'call': 'passed'}, Path(category['observation_path']))
    assert not (tmp_path / 'product/2022.1').exists()
    drifted = {**context, 'capture_sources': {}}
    with pytest.raises(ValueError, match='dependencies changed'):
        finish_source_capture(drifted, {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, Path(category['observation_path']))
    assert not (tmp_path / 'product/2022.1').exists()
    index = finish_source_capture(context, {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, Path(category['observation_path']))
    bindings, base, _ = audit.portable_binding_inputs(index, json.loads((index.parent / 'requirements.json').read_bytes()))
    from tests.maintenance import branch_audit_completion as completion
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    for identity, binding in bindings['bindings'].items():
        assert completion.evidence_result(binding['evidence']['program'], rows[identity],
            inventory['native_coverage']['candidate_sha256'], 'program', 'product', base, binding,
            source_root=audit.ROOT, reference_edges=context['reference_edges']) == ('passed', None)
        assert set(binding['evidence']) == {'program'}


def test_native_source_requires_exact_original_finalized_node_and_receipt(tmp_path):
    from tests.support.source_copy_native_evidence import read_source_native_run
    from tests.support.source_copy_branch_evidence import write_json
    node = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::ordinary_read_probe'
    record = {'contract': 'waapi-skill.host-category-evidence/v3', 'candidate': 'a' * 40,
        'version': '2022.1', 'host': {'is_command_line': True,
            'version': {'year': 2022, 'major': 1, 'minor': 19, 'build': 8584}},
        'invocation': {'phase': 'final', 'outcome': 'PASS', 'selected_test_nodeids': [node],
            'node_outcomes': [{'nodeid': node, 'outcome': 'PASS'}]},
        'source': {'hash_before': 'b' * 64, 'hash_after': 'b' * 64, 'mtime_before_ns': 1, 'mtime_after_ns': 1},
        'residual_state': {'sandbox': 'deleted', 'residual_processes': [], 'process_cleanup': 'cleaned'},
        'categories': [], 'transactions': []}
    descriptor = {**write_json(tmp_path / 'category.json', record), 'nodeid': node}
    with pytest.raises(ValueError, match='exact original Source'):
        read_source_native_run(descriptor, {'path': '/unowned/receipt', 'sha256': '0' * 64},
            {'artifact': 'absent-config', 'sha256': '0' * 64}, tmp_path)


def _assert_complete_source_review_bridge(tmp_path, version):
    from copy import deepcopy
    from tests.support.source_copy_branch_evidence import dependency_review, SYMBOLS, REVIEW_SHA256, write_json
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.source_copy_native_evidence import write_source_dependency_review, native_source_maps
    from tests.support.source_copy_branch_evidence import native_route, relevant_sources
    origin = tmp_path / 'original-evidence'
    (origin / 'native').mkdir(parents=True)
    review_descriptor = write_source_dependency_review(origin / 'native')
    assert review_descriptor == {'artifact': 'native/dependency-review.json', 'sha256': REVIEW_SHA256}
    relocated = tmp_path / 'relocated-evidence'
    origin.rename(relocated)
    assert not origin.exists()
    review = dependency_review()
    original_candidate = (review['original_native_candidate'] if version == '2021.1'
                          else review['modern_native_candidate'])
    sources = native_source_maps(original_candidate)
    route = native_route(version)
    pointer = '/argsSchema/properties/onNameConflict/enum/2'
    branch = {'id': route + '|' + pointer, 'route': route,
        'shape_sha256': review['selected_native_shapes'][route + '|' + pointer], 'pointer': pointer}
    binding = {'relevant_sources': list(relevant_sources()), 'source_copy_native_proof': {'artifact': 'native/proof.json', 'sha256': 'b' * 64},
        **{key: {'source': symbol} for key, symbol in SYMBOLS.items()}}
    proof = {'contract': 'waapi-skill.branch-evidence-equivalence/v1', 'from_candidate': original_candidate,
        'to_candidate': 'c' * 64, 'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
        'native_route': branch['route'], 'evidence_sha256': 'd' * 64,
        'binding_semantics_sha256': audit.digest(completion.binding_semantics(binding)), 'sources': sources,
        'reviewed_reason': 'Exact Root-approved Source bridge; no history credit',
        'source_native_candidate': original_candidate,
        'source_copy_review': review_descriptor}
    descriptor = write_json(relocated / 'equivalence.json', proof)
    completion.validate_equivalence(descriptor, {'sha256': 'd' * 64},
        {'candidate_sha256': original_candidate, 'relevant_sources': sources},
        branch, 'c' * 64, binding, relocated, audit.ROOT)
    binding['native_equivalence'] = descriptor
    completion.validate_native_source({'candidate': original_candidate}, {'sha256': 'd' * 64},
        branch, 'c' * 64, binding, relocated, audit.ROOT)
    for dependency in ('tests/conftest.py', 'skills/waapi-skill/wwise_waapi/source_copy_proof.py'):
        damaged = deepcopy(proof); damaged['sources'].pop(dependency)
        descriptor = write_json(relocated / 'equivalence.json', damaged)
        with pytest.raises(ValueError, match='dependencies|[Cc]omplete|[Ss]ource'):
            completion.validate_equivalence(descriptor, {'sha256': 'd' * 64},
                {'candidate_sha256': original_candidate, 'relevant_sources': damaged['sources']},
                branch, 'c' * 64, binding, relocated, audit.ROOT)

    # Re-sign the public equivalence envelope so each rejection reaches the
    # pinned Source boundary rather than merely a stale semantic digest.
    for dependency in (review['current_added_dependencies'][0], 'unreviewed/current.py'):
        damaged_binding = deepcopy(binding)
        names = set(damaged_binding['relevant_sources'])
        if dependency in names: names.remove(dependency)
        else: names.add(dependency)
        damaged_binding['relevant_sources'] = sorted(names)
        damaged = deepcopy(proof)
        damaged['binding_semantics_sha256'] = audit.digest(completion.binding_semantics(damaged_binding))
        descriptor = write_json(relocated / 'equivalence.json', damaged)
        with pytest.raises(ValueError, match='bridge differs'):
            completion.validate_equivalence(descriptor, {'sha256': 'd' * 64},
                {'candidate_sha256': original_candidate, 'relevant_sources': sources},
                branch, 'c' * 64, damaged_binding, relocated, audit.ROOT)
    damaged = deepcopy(proof)
    damaged['sources']['unreviewed/historical.py'] = '0' * 64
    descriptor = write_json(relocated / 'equivalence.json', damaged)
    with pytest.raises(ValueError):
        completion.validate_equivalence(descriptor, {'sha256': 'd' * 64},
            {'candidate_sha256': original_candidate, 'relevant_sources': damaged['sources']},
            branch, 'c' * 64, binding, relocated, audit.ROOT)
    # Portable descriptors cannot borrow the repository's matching bytes or
    # escape the relocated bundle, even with the approved content hash.
    for artifact in (str(audit.ROOT / 'tests/fixtures/source-copy/branch-dependency-review.json'),
                     '../original-evidence/native/dependency-review.json'):
        damaged = deepcopy(proof); damaged['source_copy_review']['artifact'] = artifact
        descriptor = write_json(relocated / 'equivalence.json', damaged)
        with pytest.raises(ValueError):
            completion.validate_equivalence(descriptor, {'sha256': 'd' * 64},
                {'candidate_sha256': original_candidate, 'relevant_sources': sources},
                branch, 'c' * 64, binding, relocated, audit.ROOT)
    from tests.support.source_copy_branch_evidence import relevant_sources
    current_sources = relevant_sources()
    read_bytes = Path.read_bytes
    for dependency in review['current_added_dependencies']:
        assert dependency not in sources and dependency in current_sources
    for dependency in review['current_added_dependencies']:
        target = audit.ROOT / dependency
        from unittest.mock import patch
        with patch.object(Path, 'read_bytes', lambda path: read_bytes(path) + b' ' if path == target else read_bytes(path)):
            descriptor = write_json(relocated / 'equivalence.json', proof)
            with pytest.raises(ValueError, match='bridge differs'):
                completion.validate_equivalence(descriptor, {'sha256': 'd' * 64},
                    {'candidate_sha256': original_candidate, 'relevant_sources': sources},
                    branch, 'c' * 64, binding, relocated, audit.ROOT)
    for field, value in (('route', route.replace('wwise-console', 'wwise-authoring-ui')),
                         ('pointer', '/argsSchema/properties/onNameConflict/enum/0'),
                         ('shape_sha256', '0' * 64)):
        damaged_branch = {**branch, field: value}
        descriptor = write_json(relocated / 'equivalence.json', proof)
        with pytest.raises(ValueError):
            completion.validate_equivalence(descriptor, {'sha256': 'd' * 64},
                {'candidate_sha256': original_candidate, 'relevant_sources': sources},
                damaged_branch, 'c' * 64, binding, relocated, audit.ROOT)
    portable_review = relocated / review_descriptor['artifact']
    portable_review.write_bytes(portable_review.read_bytes() + b' ')
    descriptor = write_json(relocated / 'equivalence.json', proof)
    with pytest.raises(ValueError, match='artifact digest mismatch'):
        completion.validate_equivalence(descriptor, {'sha256': 'd' * 64},
            {'candidate_sha256': original_candidate, 'relevant_sources': sources},
            branch, 'c' * 64, binding, relocated, audit.ROOT)


def test_2021_source_equivalence_accepts_only_the_reviewed_complete_six_delta_bridge(tmp_path):
    _assert_complete_source_review_bridge(tmp_path, '2021.1')


@pytest.mark.parametrize('version', ('2022.1', '2023.1', '2024.1', '2025.1'))
def test_modern_source_equivalence_accepts_only_reviewed_complete_bridge(tmp_path, version):
    _assert_complete_source_review_bridge(tmp_path, version)
