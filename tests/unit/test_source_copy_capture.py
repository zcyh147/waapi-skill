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
        'tests/support/exact_evidence_finalization.py',
        'skills/waapi-skill/wwise_waapi/topic_compatibility.py',
        'skills/waapi-skill/resources/semantic/2025.1/structure-changed-notes-compatibility.json',
        'tests/fixtures/source-copy/2021-native-donor.json',
        'tests/fixtures/source-copy/2021-native-donor.wwu'} <= set(context['relevant_sources'])
    assert {'tests/unit/test_source_copy_repeated_fixture.py', 'tests/unit/test_source_copy_modern_collector.py',
        'tests/unit/test_source_copy_saved_continuation_gateway.py', 'tests/support/gateway_config.py',
        'tests/support/source_copy_branch_evidence.py'} <= set(context['capture_sources'])
    path = tmp_path / 'context.json'
    write_json(path, context)
    node = next(iter(context['nodes']))
    assert load_source_capture(path, node)['nodeid'] == node
    for key, dependency in [('relevant_sources', 'tests/conftest.py'),
                            ('relevant_sources', 'skills/waapi-skill/wwise_waapi/topic_compatibility.py'),
                            ('relevant_sources', 'skills/waapi-skill/resources/semantic/2025.1/structure-changed-notes-compatibility.json'),
                            ('capture_sources', 'tests/unit/test_source_copy_saved_continuation_gateway.py')]:
        altered = json.loads(json.dumps(context))
        del altered[key][dependency]
        write_json(path, altered)
        with pytest.raises(ValueError, match='frozen Source capture'):
            load_source_capture(path, node)


def test_source_successor_current_review_admits_exact_dependencies_and_preserves_r92(tmp_path):
    """Admit a current context without recapturing a native or program observation."""
    import hashlib
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.source_copy_branch_evidence import write_json
    from tests.support.source_copy_native_evidence import (
        SUCCESSOR_REVIEW_PATH, SUCCESSOR_REVIEW_SHA256,
        successor_dependency_review, validate_successor_context,
    )
    product = audit.ROOT / 'tests/fixtures/branch-evidence/product'
    historical_path = audit.ROOT / 'tests/fixtures/source-copy/branch-successor-review-r92.json'
    historical_bytes = historical_path.read_bytes()
    assert hashlib.sha256(historical_bytes).hexdigest() == '278fcf8f3f404aba71d12995a6e42cc447bdabb2606800f6456a2751f9bd032f'
    historical = json.loads(historical_bytes)
    review = successor_dependency_review()
    prior_path = audit.ROOT / 'tests/fixtures/source-copy/branch-successor-review-r123.json'
    prior_bytes = prior_path.read_bytes()
    assert hashlib.sha256(prior_bytes).hexdigest() == '4f2ccb1aad3e3826b0db88e484919dce06b909d6136a5a3794dc8fc469c2f714'
    prior = json.loads(prior_bytes)
    successor = review['current_source_successor_review']
    assert successor['predecessor_current_sources'] == prior['current_sources']
    assert successor['predecessor_added_dependencies'] == prior['added_dependencies']
    assert review['historical_current_sources'] == prior['historical_current_sources']
    assert review['selected_native_shapes'] == historical['selected_native_shapes']
    assert len(review['selected_native_shapes']) == 26
    assert review['predecessor_attachments'] == historical['predecessor_attachments']
    assert len(review['predecessor_attachments']) == 5
    predecessor = next(row for row in review['predecessor_attachments'] if '2022.1' in row['artifact'])
    native = completion.read_sealed_artifact(predecessor, product)
    record = completion.read_sealed_artifact(native['evidence'], product)
    # Copy only the exact existing metadata read by context admission. These
    # are immutable native descriptors, not a new native/program capture.
    for descriptor in (predecessor, native['evidence'], record['source_context']):
        source = product / descriptor['artifact']
        destination = tmp_path / descriptor['artifact']
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    review_bytes = (audit.ROOT / SUCCESSOR_REVIEW_PATH).read_bytes()
    (tmp_path / 'review.json').write_bytes(review_bytes)
    context = {
        'contract': 'waapi-skill.source-copy-successor-context/v1',
        'review': {'artifact': 'review.json', 'sha256': SUCCESSOR_REVIEW_SHA256},
        'predecessor': predecessor,
        'original_source_context': record['source_context'],
        'current_candidate_sha256': 'a' * 64,
        'current_sources': review['current_sources'],
    }
    descriptor = write_json(tmp_path / 'context.json', context)
    assert validate_successor_context(descriptor, tmp_path, candidate='a' * 64) == (context, native)
    # Re-sign the outer descriptor to exercise the complete current map rather
    # than merely detecting stale JSON bytes. The new dependency is mandatory.
    observer = 'skills/waapi-skill/wwise_waapi/runtime_log_observer.py'
    altered = {**context, 'current_sources': {key: value for key, value in context['current_sources'].items() if key != observer}}
    omitted = write_json(tmp_path / 'omitted-observer.json', altered)
    with pytest.raises(ValueError, match='Complete reviewed Source successor context differs'):
        validate_successor_context(omitted, tmp_path, candidate='a' * 64)
    # A reviewed map never exempts future changed bytes from the real reader.
    from unittest.mock import patch
    original_read = Path.read_bytes
    primary = 'skills/waapi-skill/references/semantic/2025.1/media-pool-database-sources/ak_wwise_core_object_set_example_creating_a_media_pool_database.html'
    for dependency in (observer, 'skills/waapi-skill/wwise_waapi/control_surface_construction.py', primary):
        target = audit.ROOT / dependency
        with patch.object(Path, 'read_bytes', lambda path: original_read(path) + b' ' if path == target else original_read(path)):
            with pytest.raises(ValueError, match='^Source successor current dependency changed$'):
                validate_successor_context(descriptor, tmp_path, candidate='a' * 64)
    assert historical_path.read_bytes() == historical_bytes
    assert prior_path.read_bytes() == prior_bytes


def test_source_capture_seals_both_successor_reviews_and_new_log_dependency():
    from tests.support.source_copy_branch_evidence import capture_sources, relevant_sources
    from tests.support.source_copy_native_evidence import SUCCESSOR_REVIEW_PATH, successor_dependency_review
    assert {'tests/fixtures/source-copy/branch-successor-review-r92.json',
        'tests/fixtures/source-copy/branch-successor-review-r123.json', SUCCESSOR_REVIEW_PATH} <= capture_sources().keys()
    observer = 'skills/waapi-skill/wwise_waapi/runtime_log_observer.py'
    review = successor_dependency_review()
    assert observer in relevant_sources()
    assert review['added_dependencies'][observer]['historical'] is None
    assert review['added_dependencies'][observer]['current_sha256'] == review['current_sources'][observer]


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


def _assert_complete_source_review_bridge(tmp_path, version, monkeypatch):
    from copy import deepcopy
    from tests.support.source_copy_branch_evidence import dependency_review, SYMBOLS, REVIEW_SHA256, write_json
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.source_copy_native_evidence import write_source_dependency_review, native_source_maps
    from tests.support.source_copy_branch_evidence import native_route
    import hashlib
    import subprocess
    review = dependency_review()
    basis = review['current_source_basis']
    historical = {**review['current_sources'],
        **review['launcher_and_dependency_config_source_maps'][basis],
        **review['pinned_project_input_source_maps'][basis]}
    # This is the v1 reader's historical filesystem, not a current-source exemption.
    # Current-source v1 rejection is independently exercised by the successor controls.
    original_read = Path.read_bytes
    historical_bytes = {}
    def read_historical(path):
        name = path.relative_to(audit.ROOT).as_posix() if path.is_relative_to(audit.ROOT) else None
        if name not in historical:
            return original_read(path)
        if name not in historical_bytes:
            raw = original_read(path)
            if hashlib.sha256(raw).hexdigest() != historical[name]:
                raw = subprocess.check_output(['git', 'show', basis + ':' + name], cwd=audit.ROOT)
            assert hashlib.sha256(raw).hexdigest() == historical[name]
            historical_bytes[name] = raw
        return historical_bytes[name]
    monkeypatch.setattr(Path, 'read_bytes', read_historical)
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
    binding = {'relevant_sources': sorted(historical), 'source_copy_native_proof': {'artifact': 'native/proof.json', 'sha256': 'b' * 64},
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
    current_sources = historical
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


def test_2021_source_equivalence_accepts_only_the_reviewed_complete_six_delta_bridge(tmp_path, monkeypatch):
    _assert_complete_source_review_bridge(tmp_path, '2021.1', monkeypatch)


@pytest.mark.parametrize('version', ('2022.1', '2023.1', '2024.1', '2025.1'))
def test_modern_source_equivalence_accepts_only_reviewed_complete_bridge(tmp_path, version, monkeypatch):
    _assert_complete_source_review_bridge(tmp_path, version, monkeypatch)


@pytest.fixture(scope='module')
def source_successor_case(tmp_path_factory, inventory):
    """Current public program + untouched original native proof in one importer."""
    from copy import deepcopy
    import tempfile
    import importlib
    from tests.support.source_copy_branch_evidence import (
        source_capture_plan, finish_source_capture, write_json)
    from tests.unit.test_source_copy_modern_collector import modern_collector_runtime
    from tests.maintenance import branch_audit_completion as completion
    product = audit.ROOT / 'tests/fixtures/branch-evidence/product'
    import os
    from contextlib import nullcontext
    cache = os.getenv('WAAPI_SOURCE_SUCCESSOR_READER_FIXTURE')
    cache = str(Path(cache).resolve()) if cache else None
    if cache and (Path(cache)/'case.json').exists():
        saved=json.loads((Path(cache)/'case.json').read_bytes())
        for key in ('index','base','output'):saved[key]=Path(saved[key])
        # Common reader corruption controls reuse these frozen program bytes.
        # Final current-source acceptance uses the separate five-node capture.
        audit.portable_binding_inputs(saved['index'],saved['requirements'])
        yield saved
        return
    if cache:
        Path(cache).mkdir(parents=True,exist_ok=False)
    manager=nullcontext(cache) if cache else tempfile.TemporaryDirectory(prefix='.source-successor-test-',dir=product)
    with manager as directory:
        output = Path(directory)
        reuse_program = os.getenv('WAAPI_SOURCE_SUCCESSOR_PROGRAM_INDEX')
        if reuse_program:
            program_index=Path(reuse_program).resolve(strict=True)
            frozen=json.loads((program_index.parent/'program.json').read_bytes())
            inventory={**inventory,'native_coverage':{**inventory['native_coverage'],
                'candidate_sha256':frozen['candidate_sha256']}}
        else:
            public = tmp_path_factory.mktemp('source-successor-public')
            with pytest.MonkeyPatch.context() as environment:
                environment.setenv('WWISE_LIVE', '1'); environment.setenv('WWISE_DESTRUCTIVE', '1')
                workflow = importlib.import_module('tests.destructive.test_gateway_workflow_transaction_matrix')
            runtime, _, _ = modern_collector_runtime(public)
            category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='SUCCESSOR', saved_copy=True,
                saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile='modern-original-owned-source/v1')
            plan = source_capture_plan(output / 'capture', inventory=inventory)
            node = next(k for k,v in plan['nodes'].items() if v['version'] == '2022.1')
            context = {**plan, **plan['nodes'][node], 'nodeid': node}
            program_index = finish_source_capture(context,
                {'setup':'passed','call':'passed','teardown':'passed'}, Path(category['observation_path']))
        bundle = program_index.parent
        def emit(name, value):
            path = output / name
            return {**write_json(path,value),'artifact':path.relative_to(product).as_posix()}
        def ref(name):
            path = bundle / name
            import hashlib
            return {'artifact':path.relative_to(product).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        from tests.support.source_copy_native_evidence import successor_dependency_review, SUCCESSOR_REVIEW_PATH
        predecessor=next(x for x in successor_dependency_review()['predecessor_attachments'] if '2022.1' in x['artifact'])
        native=completion.read_sealed_artifact(predecessor,product)
        original_binding=json.loads((bundle/'bindings.json').read_bytes())
        projected=deepcopy(original_binding)
        for binding in projected['bindings'].values():binding['evidence']['program']['artifact']=ref('program.json')['artifact']
        proof=json.loads((bundle/'proof.json').read_bytes())
        for value in proof['files'].values():value['artifact']=(bundle/value['artifact']).relative_to(product).as_posix()
        attachment=json.loads((bundle/'attachment.json').read_bytes());attachment['proof']=emit('program-proof.json',proof)
        program_attachment=emit('program-attachment.json',attachment)
        program_projection=emit('bindings.json',projected)
        successor_review=json.loads((audit.ROOT/SUCCESSOR_REVIEW_PATH).read_bytes())
        native_record=completion.read_sealed_artifact({k:native['evidence'][k] for k in ('artifact','sha256')},product)
        import hashlib
        review_raw=(audit.ROOT/SUCCESSOR_REVIEW_PATH).read_bytes()
        (output/'review.json').write_bytes(review_raw)
        review_descriptor={'artifact':(output/'review.json').relative_to(product).as_posix(),
            'sha256':hashlib.sha256(review_raw).hexdigest()}
        successor_context=emit('successor-context.json',{
            'contract':'waapi-skill.source-copy-successor-context/v1',
            'review':review_descriptor,'predecessor':predecessor,
            'original_source_context':native_record['source_context'],
            'current_candidate_sha256':inventory['native_coverage']['candidate_sha256'],
            'current_sources':successor_review['current_sources']})
        successor={**deepcopy(native),'contract':'waapi-skill.source-copy-native-attachment/v2',
            'predecessor':predecessor,'successor_context':successor_context,'equivalence':{},'native_equivalence':{}}
        program=json.loads((bundle/'program.json').read_bytes())
        for identity,binding in projected['bindings'].items():
            binding=deepcopy(binding)
            binding.update(source_copy_proof=attachment['proof'],source_business_fact=attachment['business_fact_id'],
                source_copy_native_proof=native['proof'],source_copy_successor_context=successor_context,
                native_observations_sha256={k:v['sha256'] for k,v in native_record['observation_artifacts'].items()})
            for kind in ('equivalence','native_equivalence'):
                oldproof=completion.read_sealed_artifact(native[kind][identity],product)
                proof={**oldproof,'to_candidate':inventory['native_coverage']['candidate_sha256'],
                    'binding_semantics_sha256':audit.digest(completion.binding_semantics(binding)),
                    'source_copy_successor_context':successor_context}
                successor[kind][identity]=emit(kind+'-'+str(len(successor[kind]))+'.json',proof)
        successor_descriptor=emit('native-successor.json',successor)
        index={'contract':'waapi-skill.branch-evidence-index/v1','base':os.path.relpath(product,output),
            'entries':[{'id':'source-successor-2022.1','bindings':program_projection,
                'origin':{k:ref(v) for k,v in {'bindings':'bindings.json','program':'program.json',
                    'requirements':'requirements.json','capture':'capture.json'}.items()}}],
            'source_attachments':[program_attachment],'source_native_attachments':[successor_descriptor]}
        path=output/'index.json';write_json(path,index)
        case={'index':path,'requirements':json.loads((bundle/'requirements.json').read_bytes()),
            'base':product,'output':output,'inventory':inventory,'predecessor':predecessor,
            'successor':successor_descriptor}
        if cache:
            from tests.support.source_copy_branch_evidence import native_route
            compact={**case,'inventory':{'native_coverage':{
                'candidate_sha256':inventory['native_coverage']['candidate_sha256'],
                'obligations':[r for r in inventory['native_coverage']['obligations']
                    if r['route']==native_route('2022.1')]}}}
            (output/'case.json').write_text(json.dumps(compact,default=str,sort_keys=True)+'\n')
        yield case


def test_current_source_successor_reuses_unchanged_original_native_through_importer(source_successor_case):
    from tests.maintenance import branch_audit_completion as completion
    case=source_successor_case
    bindings,base,_=audit.portable_binding_inputs(case['index'],case['requirements'])
    assert len(bindings['bindings'])==4
    rows={row['id']:row for row in case['inventory']['native_coverage']['obligations']}
    for identity,binding in bindings['bindings'].items():
        for category in ('program','native'):
            assert completion.evidence_result(binding['evidence'][category],rows[identity],
                case['inventory']['native_coverage']['candidate_sha256'],category,'product',base,
                binding,source_root=audit.ROOT, reference_edges={k:v for k,v in rows.items() if v['kind']=='reference'})==('passed',None)


@pytest.fixture(scope='module')
def source_accounting_case(inventory):
    """Only sidecars are new; all five program/native packets are committed inputs."""
    import tempfile
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.source_copy_native_evidence import publish_source_native_successor
    product = audit.ROOT / 'tests/fixtures/branch-evidence/product'
    with tempfile.TemporaryDirectory(prefix='.source-accounting-', dir=product) as temporary:
        output = Path(temporary)
        cases = {}
        for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'):
            packet = product / ('source-195-current-88a6cbbe-' + version)
            old_index = packet / 'portable/index.json'
            old = json.loads(old_index.read_bytes())
            native = completion.read_sealed_artifact(old['source_native_attachments'][0], product)
            requirements = completion.read_sealed_artifact(old['entries'][0]['origin']['requirements'], product)
            index = publish_source_native_successor(old_index, predecessor=native['predecessor'],
                inventory=inventory, product_base=product, destination=output / version, accounting=True)
            cases[version] = {'index': index, 'old_index': old_index, 'requirements': requirements}
        yield {'cases': cases, 'inventory': inventory, 'product': product, 'output': output}


def test_accounting_successor_admits_five_retained_programs_without_recapture(source_accounting_case):
    from tests.maintenance import branch_audit_completion as completion
    case = source_accounting_case
    rows = {row['id']: row for row in case['inventory']['native_coverage']['obligations']}
    references = {key: row for key, row in rows.items() if row['kind'] == 'reference'}
    total = 0
    for version, packet in case['cases'].items():
        old = json.loads(packet['old_index'].read_bytes())
        new = json.loads(packet['index'].read_bytes())
        assert new['entries'][0]['origin'] == old['entries'][0]['origin']
        assert new['source_attachments'] == old['source_attachments']
        old_native = completion.read_sealed_artifact(old['source_native_attachments'][0], case['product'])
        new_native = completion.read_sealed_artifact(new['source_native_attachments'][0], case['product'])
        for field in ('branch_ids', 'business_fact_id', 'proof', 'evidence', 'predecessor'):
            assert new_native[field] == old_native[field]
        for index, candidate in ((packet['old_index'], '0383d01b4b400a52c94b1f3924a9234915e32a06583c89cd9aaaf8cb628ebdc3'),
                                 (packet['index'], case['inventory']['native_coverage']['candidate_sha256'])):
            document, base, projection = audit.portable_binding_inputs(index, packet['requirements'])
            assert projection['source_business_facts'] == [version + '|source-copy-synth-owned-graph']
            for identity, binding in document['bindings'].items():
                program = completion.read_sealed_artifact(binding['evidence']['program'], base)
                assert program['git_candidate'] == '88a6cbbeccee1b8f5934f61f7b75503e2a084073'
                assert program['candidate_sha256'] == '0383d01b4b400a52c94b1f3924a9234915e32a06583c89cd9aaaf8cb628ebdc3'
                for category in ('program', 'native'):
                    assert completion.evidence_result(binding['evidence'][category], rows[identity], candidate,
                        category, 'product', base, binding, source_root=audit.ROOT,
                        reference_edges=references) == ('passed', None)
            if index == packet['index']:
                total += len(document['bindings'])
    assert total == 26


@pytest.mark.parametrize('damage', ('missing-review', 'wrong-candidate', 'wrong-descriptor',
    'cross-version', 'native-credit', 'escaping-review', 'missing-program-bridge',
    'wrong-program-candidate', 'wrong-program-evidence'))
def test_accounting_successor_rejects_changed_attribution_through_ordinary_reader(source_accounting_case, damage):
    from copy import deepcopy
    import os
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.source_copy_branch_evidence import write_json
    case = source_accounting_case
    packet = case['cases']['2022.1']
    product = case['product']
    output = case['output'] / ('control-' + damage)
    output.mkdir()
    def emit(name, value):
        return {**write_json(output / name, value), 'artifact': (output / name).relative_to(product).as_posix()}
    index = json.loads(packet['index'].read_bytes())
    native = completion.read_sealed_artifact(index['source_native_attachments'][0], product)
    context = completion.read_sealed_artifact(native['successor_context'], product)
    identity = native['branch_ids'][0]
    if damage == 'missing-review':
        del context['review']
    elif damage == 'wrong-candidate':
        context['current_candidate_sha256'] = '0' * 64
    elif damage == 'wrong-descriptor':
        context['previous_index']['sha256'] = '0' * 64
    elif damage == 'cross-version':
        other = case['cases']['2023.1']['old_index']
        import hashlib
        context['previous_index'] = {'artifact': other.relative_to(product).as_posix(),
                                     'sha256': hashlib.sha256(other.read_bytes()).hexdigest()}
    elif damage == 'native-credit':
        origin = index['entries'][0]['origin']
        capture = completion.read_sealed_artifact(origin['capture'], product)
        capture['native_credit'] = True
        origin['capture'] = emit('capture.json', capture)
    elif damage == 'escaping-review':
        context['review']['artifact'] = '../outside-review.json'
    elif damage == 'missing-program-bridge':
        del native['program_equivalence'][identity]
    else:
        proof = completion.read_sealed_artifact(native['program_equivalence'][identity], product)
        proof['from_candidate' if damage == 'wrong-program-candidate' else 'evidence_sha256'] = '0' * 64
        native['program_equivalence'][identity] = emit('program-equivalence.json', proof)
    # Re-seal the changed context only when it is itself the damaged input.
    # Other controls retain the valid binding semantics and reach their intended check.
    if damage in {'missing-review', 'wrong-candidate', 'wrong-descriptor', 'cross-version', 'escaping-review'}:
        native['successor_context'] = emit('context.json', context)
    index['source_native_attachments'] = [emit('native.json', native)]
    index['base'] = os.path.relpath(product, output)
    path = output / 'index.json'
    write_json(path, index)
    if damage in {'wrong-candidate', 'wrong-program-candidate', 'wrong-program-evidence'}:
        document, base, _ = audit.portable_binding_inputs(path, packet['requirements'])
        binding = document['bindings'][identity]
        branch = next(row for row in case['inventory']['native_coverage']['obligations'] if row['id'] == identity)
        result = completion.evidence_result(binding['evidence']['program'], branch,
            case['inventory']['native_coverage']['candidate_sha256'], 'program', 'product', base,
            binding, source_root=audit.ROOT)
        assert result[0] == 'missing'
        assert ('admitted candidate' if damage == 'wrong-candidate' else 'stale or nonexact') in result[1]
    else:
        with pytest.raises(ValueError, match='Source|[Ss]ource|relative|archive'):
            audit.portable_binding_inputs(path, packet['requirements'])


@pytest.mark.parametrize('damage', ('second-pin-assignment', 'altered-pin-assignment',
    'other-reader-byte', 'unlisted-audit-change', 'runtime-effect-change', 'new-condition-proof'))
def test_accounting_successor_rejects_unreviewed_source_changes(source_accounting_case, monkeypatch, damage):
    from tests.support.source_copy_native_evidence import ACCOUNTING_READER, ACCOUNTING_REVIEW_SHA256
    packet = source_accounting_case['cases']['2022.1']
    names = {
        'unlisted-audit-change': 'tests/maintenance/branch_audit_completion.py',
        'runtime-effect-change': 'skills/waapi-skill/wwise_waapi/source_copy_proof.py',
        'new-condition-proof': 'tests/fixtures/metadata-conditions/new-condition-current-program-r3.json.gz'}
    target = audit.ROOT / names.get(damage, ACCOUNTING_READER)
    read_bytes = Path.read_bytes
    def damaged_bytes(path):
        raw = read_bytes(path)
        if path != target:
            return raw
        assignment = b"ACCOUNTING_REVIEW_SHA256 = '" + ACCOUNTING_REVIEW_SHA256.encode() + b"'"
        if damage == 'second-pin-assignment':
            return raw + b'\n' + assignment + b'\n'
        if damage == 'altered-pin-assignment':
            return raw.replace(assignment, assignment.replace(b' = ', b': str = '))
        return raw + b'\n# unreviewed dependency change\n'
    monkeypatch.setattr(Path, 'read_bytes', damaged_bytes)
    expected = 'digest literal assignment' if damage in {'second-pin-assignment', 'altered-pin-assignment'} else 'current dependency changed'
    with pytest.raises(ValueError, match=expected):
        audit.portable_binding_inputs(packet['index'], packet['requirements'])


def test_unbound_source_program_equivalence_cannot_borrow_valid_old_context(source_accounting_case):
    from copy import deepcopy
    from tests.maintenance import branch_audit_completion as completion
    case = source_accounting_case
    packet = case['cases']['2022.1']
    old, base, _ = audit.portable_binding_inputs(packet['old_index'], packet['requirements'])
    current, _, _ = audit.portable_binding_inputs(packet['index'], packet['requirements'])
    identity = next(iter(old['bindings']))
    binding = deepcopy(old['bindings'][identity])
    binding['source_copy_program_equivalence'] = current['bindings'][identity]['source_copy_program_equivalence']
    branch = next(row for row in case['inventory']['native_coverage']['obligations'] if row['id'] == identity)
    result = completion.evidence_result(binding['evidence']['program'], branch,
        case['inventory']['native_coverage']['candidate_sha256'], 'program', 'product', base,
        binding, source_root=audit.ROOT)
    assert result == ('missing', 'Unbound Source accounting program equivalence')


def test_source_successor_rejects_resigned_predecessor_substitution(source_successor_case):
    """Equal parsed v1 JSON is not permission to substitute its original bytes."""
    import hashlib
    from copy import deepcopy
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.source_copy_branch_evidence import write_json
    case=source_successor_case; base=case['base']; output=case['output']
    import uuid
    prefix='substitution-'+uuid.uuid4().hex+'-'
    original=base/case['predecessor']['artifact']; raw=original.read_bytes()+b' '
    changed=output/(prefix+'predecessor.json'); changed.write_bytes(raw)
    replacement={'artifact':changed.relative_to(base).as_posix(),'sha256':hashlib.sha256(raw).hexdigest()}
    attachment=deepcopy(completion.read_sealed_artifact(case['successor'],base))
    context=completion.read_sealed_artifact(attachment['successor_context'],base)
    context['predecessor']=replacement
    def emit(name,value):
        target=output/(prefix+name)
        return {**write_json(target,value),'artifact':target.relative_to(base).as_posix()}
    attachment['predecessor']=replacement;attachment['successor_context']=emit('substituted-context.json',context)
    index=json.loads(case['index'].read_bytes());index['source_native_attachments']=[emit('substituted-native.json',attachment)]
    target=output/(prefix+'index.json');write_json(target,index)
    with pytest.raises(ValueError,match='original predecessor'):
        audit.portable_binding_inputs(target,case['requirements'])


@pytest.mark.parametrize('fault,reason',(
    ('omitted_current','successor context differs'),
    ('extra_current','successor context differs'),
    ('changed_current','successor context differs'),
    ('wrong_review','successor context differs'),
    ('forged_review','successor context differs'),
    ('wrong_original_context','artifact digest mismatch'),
    ('wrong_candidate','current complete product program'),
    ('wrong_predecessor','original predecessor'),
    ('absolute_context','path|relative'),
    ('traversal_context','path|traversal|relative'),
    ('escaped_context','escapes'),
    ('original_proof_replaced','original native attribution'),
    ('branch_replaced','original native attribution'),
    ('v1_stale','Original Source proof/context'),
))
def test_source_successor_inner_guards_reject_resigned_outer_descriptors(source_successor_case,fault,reason,tmp_path):
    from copy import deepcopy
    import hashlib
    import uuid
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.source_copy_branch_evidence import write_json
    case=source_successor_case; base=case['base']; prefix=fault+'-'+uuid.uuid4().hex+'-'
    def emit(name,value):
        target=case['output']/(prefix+name)
        return {**write_json(target,value),'artifact':target.relative_to(base).as_posix()}
    attachment=deepcopy(completion.read_sealed_artifact(case['successor'],base))
    context=deepcopy(completion.read_sealed_artifact(attachment['successor_context'],base))
    if fault=='omitted_current':context['current_sources'].pop('skills/waapi-skill/scripts/gateway.py')
    elif fault=='extra_current':context['current_sources']['unreviewed.py']='0'*64
    elif fault=='changed_current':context['current_sources']['skills/waapi-skill/scripts/gateway.py']='0'*64
    elif fault=='wrong_review':context['review']['sha256']='0'*64
    elif fault=='forged_review':
        review=completion.read_sealed_artifact(context['review'],base);review['scope']='self-authorized'
        context['review']=emit('review.json',review)
    elif fault=='wrong_original_context':context['original_source_context']['sha256']='0'*64
    elif fault=='wrong_candidate':context['current_candidate_sha256']='f'*64
    elif fault=='wrong_predecessor':context['predecessor']['sha256']='0'*64
    elif fault=='original_proof_replaced':attachment['proof']['sha256']='0'*64
    elif fault=='branch_replaced':attachment['branch_ids'][0]=attachment['branch_ids'][0].replace('/anyOf/1','/anyOf/0')
    descriptor=emit('context.json',context)
    if fault=='absolute_context':descriptor['artifact']=str((base/descriptor['artifact']).resolve())
    elif fault=='traversal_context':descriptor['artifact']='../'+descriptor['artifact']
    elif fault=='escaped_context':
        external=tmp_path/(prefix+'outside.json')
        external.write_bytes((base/descriptor['artifact']).read_bytes())
        link=case['output']/(prefix+'link.json');link.symlink_to(external)
        descriptor['artifact']=link.relative_to(base).as_posix()
    attachment['successor_context']=descriptor
    index=json.loads(case['index'].read_bytes())
    index['source_native_attachments']=[case['predecessor'] if fault=='v1_stale' else emit('attachment.json',attachment)]
    path=case['output']/(prefix+'index.json');write_json(path,index)
    with pytest.raises((ValueError,TypeError),match=reason):
        audit.portable_binding_inputs(path,case['requirements'])


def test_source_successor_producer_preserves_original_native_descriptors(source_successor_case):
    import uuid
    from tests.support.source_copy_native_evidence import publish_source_native_successor
    from tests.maintenance import branch_audit_completion as completion
    case=source_successor_case
    index=json.loads(case['index'].read_bytes())
    program_index=(case['base']/index['entries'][0]['origin']['program']['artifact']).parent/'index.json'
    published=publish_source_native_successor(program_index,predecessor=case['predecessor'],
        inventory=case['inventory'],product_base=case['base'],
        destination=case['output']/('published-'+uuid.uuid4().hex))
    output=json.loads(published.read_bytes())
    successor=completion.read_sealed_artifact(output['source_native_attachments'][0],case['base'])
    original=completion.read_sealed_artifact(case['predecessor'],case['base'])
    assert {k:successor[k] for k in ('branch_ids','business_fact_id','proof','evidence')}=={
        k:original[k] for k in ('branch_ids','business_fact_id','proof','evidence')}
    assert successor['predecessor']==case['predecessor']
    bindings,base,_=audit.portable_binding_inputs(published,case['requirements'])
    assert len(bindings['bindings'])==4


def test_source_successor_reads_portable_proof_with_old_origins_unavailable(source_successor_case,monkeypatch):
    from tests.maintenance import branch_audit_completion as completion
    case=source_successor_case
    attachment=completion.read_sealed_artifact(case['successor'],case['base'])
    proof=completion.read_sealed_artifact(attachment['proof'],case['base'])
    old_origins=set(proof['files'])
    read_bytes=Path.read_bytes
    def bounded_read(path):
        if str(path) in old_origins:
            raise OSError('Original native provenance origin is unavailable')
        return read_bytes(path)
    monkeypatch.setattr(Path,'read_bytes',bounded_read)
    bindings,base,_=audit.portable_binding_inputs(case['index'],case['requirements'])
    rows={r['id']:r for r in case['inventory']['native_coverage']['obligations']}
    for identity,binding in bindings['bindings'].items():
        assert completion.evidence_result(binding['evidence']['native'],rows[identity],
            case['inventory']['native_coverage']['candidate_sha256'],'native','product',base,binding,
            source_root=audit.ROOT,reference_edges={k:v for k,v in rows.items() if v['kind']=='reference'})==('passed',None)


def test_source_successor_rejects_new_dependency_bytes(source_successor_case, monkeypatch):
    from tests.support.source_copy_native_evidence import successor_dependency_review
    case = source_successor_case
    review = successor_dependency_review()
    dependency = next(name for name in review['added_dependencies'] if name.endswith('.py'))
    target = audit.ROOT / dependency
    read_bytes = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: read_bytes(path) + b' ' if path == target else read_bytes(path))
    with pytest.raises(ValueError, match='current dependency changed'):
        audit.portable_binding_inputs(case['index'], case['requirements'])


def test_source_successor_rejects_malformed_review_descriptor(source_successor_case):
    from copy import deepcopy
    import uuid
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.source_copy_branch_evidence import write_json
    case = source_successor_case
    attachment = deepcopy(completion.read_sealed_artifact(case['successor'], case['base']))
    context = completion.read_sealed_artifact(attachment['successor_context'], case['base'])
    context['review'] = None
    path = case['output'] / ('malformed-review-' + uuid.uuid4().hex + '.json')
    descriptor = {**write_json(path, context), 'artifact': path.relative_to(case['base']).as_posix()}
    from tests.support.source_copy_native_evidence import validate_successor_context
    with pytest.raises(ValueError, match='descriptor'):
        validate_successor_context(descriptor, case['base'])


def test_source_successor_equivalence_cannot_drop_current_context(source_successor_case):
    from copy import deepcopy
    import uuid
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.source_copy_branch_evidence import write_json
    case = source_successor_case
    bindings, base, _ = audit.portable_binding_inputs(case['index'], case['requirements'])
    identity, binding = next(iter(bindings['bindings'].items()))
    binding = deepcopy(binding)
    proof = completion.read_sealed_artifact(binding['equivalence'], base)
    proof.pop('source_copy_successor_context')
    path = case['output'] / ('unbound-equivalence-' + uuid.uuid4().hex + '.json')
    binding['equivalence'] = {**write_json(path, proof), 'artifact': path.relative_to(base).as_posix()}
    branch = next(row for row in case['inventory']['native_coverage']['obligations'] if row['id'] == identity)
    result = completion.evidence_result(binding['evidence']['native'], branch,
        case['inventory']['native_coverage']['candidate_sha256'], 'native', 'product', base, binding,
        source_root=audit.ROOT, reference_edges={row['id']: row for row in case['inventory']['native_coverage']['obligations'] if row['kind'] == 'reference'})
    assert result[0] == 'missing'
    assert 'successor equivalence context differs' in result[1]


@pytest.mark.parametrize('phase,missing', (
    ('setup', False), ('call', False), ('teardown', False),
    ('setup', True), ('call', True), ('teardown', True),
))
def test_source_successor_rejects_incomplete_capture_phases(source_successor_case, phase, missing):
    """Re-sealed failed/missing phases cannot authorize the old native facts."""
    import os
    import uuid
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.source_copy_branch_evidence import write_json
    case = source_successor_case
    # Establish that the unchanged baseline reaches both real final readers.
    baseline, base, _ = audit.portable_binding_inputs(case['index'], case['requirements'])
    rows = {row['id']: row for row in case['inventory']['native_coverage']['obligations']}
    references = {key: row for key, row in rows.items() if row['kind'] == 'reference'}
    for identity, binding in baseline['bindings'].items():
        for category in ('program', 'native'):
            assert completion.evidence_result(binding['evidence'][category], rows[identity],
                case['inventory']['native_coverage']['candidate_sha256'], category, 'product', base,
                binding, source_root=audit.ROOT, reference_edges=references) == ('passed', None)
    index = json.loads(case['index'].read_bytes())
    capture = completion.read_sealed_artifact(index['entries'][0]['origin']['capture'], base)
    assert capture['phase_reports'] == dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
    if missing:
        capture['phase_reports'].pop(phase)
    else:
        capture['phase_reports'][phase] = 'failed'
    output = case['output'] / ('phase-control-' + uuid.uuid4().hex)
    output.mkdir()
    path = output / 'capture.json'
    index['entries'][0]['origin']['capture'] = {
        **write_json(path, capture), 'artifact': path.relative_to(base).as_posix()}
    index['base'] = os.path.relpath(base, output)
    changed = output / 'index.json'
    write_json(changed, index)
    with pytest.raises(ValueError, match='complete successful capture phases'):
        audit.portable_binding_inputs(changed, case['requirements'])
