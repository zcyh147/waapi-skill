"""Selected historical native facts stay separate from current CODE proof."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.unit.test_runtime_log_branch_evidence import log_inventory

PREFIX = 'tests/fixtures/branch-evidence/product/runtime-remaining-195-r1/'
REVIEW = PREFIX + 'selected-native-source-successor.json'
METER = '2025.1|wwise-authoring|2025.1.7.9143|function|ak.wwise.core.profiler.getMeters'


def retained_input():
    packet = audit.ROOT / PREFIX / 'retained-meter-r137'
    requirements = json.loads((packet / 'requirements.json').read_bytes())
    imported, base, _ = audit.portable_binding_inputs(packet / 'index.json', requirements)
    binding = deepcopy(imported['bindings'][METER + '|/resultSchema'])
    prefix = packet.relative_to(audit.ROOT).as_posix()
    binding['evidence'] = {'native': {**binding['evidence']['native'],
        'artifact': prefix + '/' + binding['evidence']['native']['artifact']}}
    binding['qualified_runtime_read_attachment'] = {**binding['qualified_runtime_read_attachment'],
        'artifact': prefix + '/' + binding['qualified_runtime_read_attachment']['artifact']}
    binding['native_only_base'] = prefix
    binding['native_only_review'] = {'artifact': REVIEW,
        'sha256': hashlib.sha256((audit.ROOT / REVIEW).read_bytes()).hexdigest()}
    inventory = log_inventory(METER, pointers={'/resultSchema'})
    branch, = inventory['native_coverage']['obligations']
    return binding, branch


def test_selected_meter_native_remains_valid_without_fake_current_code():
    binding, branch = retained_input()
    result = completion.evidence_result(binding['evidence']['native'], branch, 'e' * 64,
        'native', 'product', audit.ROOT, binding=binding, source_root=audit.ROOT)
    assert result == ('passed', None), result
    assert 'program' not in binding['evidence']


@pytest.fixture
def native_output():
    parent = audit.ROOT / ".waapi-skill-state"
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="selected-native-test-", dir=parent) as name:
        yield Path(name)


def test_partial_cpu_native_conversion_does_not_create_current_program(native_output):
    from tests.support import extra_runtime_read_evidence as extra
    route = '2024.1|wwise-authoring|2024.1.13.9056|function|ak.wwise.core.profiler.getCpuUsage'
    identity = route + '|/resultSchema'
    index = extra.write_bundle(native_output / 'native-only', [],
        inventory=log_inventory(route, pointers={'/resultSchema'}), retained_native=[identity])
    document = json.loads(index.read_bytes())
    assert document['qualified_runtime_read_attachments']
    assert document['entries']
    assert not any('program' in binding['evidence']
        for entry in document['entries']
        for binding in completion.read_sealed_artifact(entry['bindings'], audit.ROOT)['bindings'].values())
    policies = json.loads((index.parent / 'requirements.json').read_bytes())
    imported, base, _ = audit.portable_binding_inputs(index, policies)
    binding = imported['bindings'][identity]
    produced_native = base / binding['evidence']['native']['artifact']
    assert produced_native.resolve().is_relative_to(native_output.resolve())
    inventory = log_inventory(route, pointers={'/resultSchema'})
    def consume():
        return completion.evaluate_coverage(audit.ROOT, inventory, imported,
            digest=audit.digest, evidence_base=base, requirements_document=policies)['obligations'][0]
    row = consume()
    assert row['evidence_results']['native']['outcome'] == 'passed', row['evidence_results']
    assert row['evidence_results']['program']['outcome'] == 'missing'
    assert row['state'] != 'verified'
    # Damage this actual emitted artifact, rather than a committed packet.
    qualified = json.loads(produced_native.read_bytes())
    qualified['retained_facts']['original_public_complete'] = True
    produced_native.write_text(json.dumps(qualified))
    damaged, _, _ = audit.portable_binding_inputs(index, policies)
    imported = damaged
    row = consume()
    assert row['evidence_results']['native']['outcome'] == 'missing'
    assert row['state'] != 'verified'


@pytest.fixture(scope='module')
def selected_native_inputs():
    from tests.support import runtime_observation_evidence as runtime
    review = runtime.selected_runtime_source_successor()
    routes = [identity.removesuffix('|/resultSchema') for identity in review['scope_ids']]
    inventory = log_inventory(routes, pointers={'/resultSchema'})
    branches = {branch['id']: branch for branch in inventory['native_coverage']['obligations']}
    bindings = {}
    prefixes = sorted({member['base'] for member in review['members'].values()})
    for prefix in prefixes:
        packet = audit.ROOT / prefix
        policies = json.loads((packet / 'requirements.json').read_bytes())
        imported, base, _ = audit.portable_binding_inputs(packet / 'index.json', policies)
        for identity, original in imported['bindings'].items():
            if identity not in review['members']:
                continue
            binding = deepcopy(original)
            if 'native_only_base' not in binding:
                binding['evidence'] = {'native': {**binding['evidence']['native'],
                    'artifact': prefix + '/' + binding['evidence']['native']['artifact']}}
                binding['qualified_runtime_read_attachment'] = {**binding['qualified_runtime_read_attachment'],
                    'artifact': prefix + '/' + binding['qualified_runtime_read_attachment']['artifact']}
                binding['native_only_base'] = prefix
                binding['native_only_review'] = {'artifact': REVIEW,
                    'sha256': hashlib.sha256((audit.ROOT / REVIEW).read_bytes()).hexdigest()}
            bindings[identity] = binding
    assert set(bindings) == set(review['scope_ids'])
    return inventory, branches, bindings, review


def native_result(binding, branch):
    return completion.evidence_result(binding['evidence']['native'], branch, 'e' * 64,
        'native', 'product', audit.ROOT, binding=binding, source_root=audit.ROOT)


def test_adopted_shared_native_converters_preserve_all_original_fact_boundaries(selected_native_inputs):
    inventory, branches, bindings, review = selected_native_inputs
    from tests.support.runtime_remaining_completion_mapping import runtime_gateway_argv
    for identity, binding in bindings.items():
        if binding['input'].get('native_observation_only'):
            assert binding['input']['gateway_argv'] == runtime_gateway_argv(branches[identity]['route'].split('|')[-1])
    failures = {identity: native_result(binding, branches[identity])
        for identity, binding in bindings.items()}
    assert set(failures.values()) == {('passed', None)}, {key: value for key, value in failures.items() if value != ('passed', None)}
    cpu = next(member for identity, member in review['members'].items()
        if '|wwise-authoring|' in identity and identity.endswith('getCpuUsage|/resultSchema'))
    assert cpu['facts']['original_finalization'] == 'BLOCKED'
    assert cpu['facts']['original_public_complete'] is False
    assert cpu['facts']['native_nonempty_rows'] == 34
    assert all('program' not in binding['evidence'] for binding in bindings.values())


@pytest.mark.parametrize('damage', ['identity', 'mapping', 'source-review', 'qualification-candidate',
    'partial-as-complete', 'capture', 'assessment', 'native-source'])
def test_selected_native_tampering_cannot_inherit_validity(selected_native_inputs, native_output, damage):
    _, branches, bindings, _ = selected_native_inputs
    identity = next(i for i in bindings if '|wwise-authoring|' in i and i.endswith('getCpuUsage|/resultSchema'))
    binding = deepcopy(bindings[identity]); branch = deepcopy(branches[identity])
    if damage == 'identity': branch['id'] = branch['id'].replace('wwise-authoring', 'wwise-console')
    elif damage == 'mapping': binding['input']['selector'] = '/native_call/args'
    elif damage == 'source-review': binding['native_only_review']['sha256'] = '0' * 64
    elif damage in {'qualification-candidate', 'partial-as-complete', 'native-source'}:
        record = completion.read_sealed_artifact(binding['evidence']['native'], audit.ROOT)
        if damage == 'qualification-candidate': record['candidate_sha256'] = '0' * 40
        elif damage == 'partial-as-complete': record['retained_facts']['original_public_complete'] = True
        else: record['relevant_sources']['skills/waapi-skill/scripts/run.py'] = '0' * 64
        path = native_output / 'tampered-qualified.json'
        path.write_text(json.dumps(record))
        binding['evidence']['native'] = {'artifact': path.relative_to(audit.ROOT).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    elif damage == 'assessment': binding['qualified_runtime_read_attachment']['sha256'] = '0' * 64
    else:
        # A capture tamper changes an exact protected member descriptor.
        member = json.loads((audit.ROOT / REVIEW).read_bytes())['members'][identity]
        capture_path = audit.ROOT / member['capture']['artifact']
        original = capture_path.read_bytes()
        try:
            capture_path.write_bytes(original + b' ')
            assert native_result(binding, branch)[0] == 'missing'
        finally:
            capture_path.write_bytes(original)
        return
    assert native_result(binding, branch)[0] == 'missing'


def test_missing_current_code_leaves_requirement_incomplete_and_native_fact_intact(selected_native_inputs):
    inventory, branches, bindings, _ = selected_native_inputs
    identity = next(i for i in bindings if '|wwise-authoring|' in i and i.endswith('getCpuUsage|/resultSchema'))
    binding = bindings[identity]
    one = deepcopy(inventory)
    one['native_coverage']['obligations'] = [branches[identity]]
    from tests.support import runtime_remaining_evidence as remaining
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1',
        'branches': {identity: remaining.policy(remaining.exact_entry(branches[identity]))}}
    result = completion.evaluate_coverage(audit.ROOT, one,
        {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {identity: binding}},
        digest=audit.digest, evidence_base=audit.ROOT, requirements_document=requirements)
    row, = result['obligations']
    assert row['evidence_results']['native']['outcome'] == 'passed', row['evidence_results']
    assert row['evidence_results']['program']['outcome'] == 'missing'
    assert row['state'] != 'verified'


def test_scoped_native_reuse_does_not_relax_legacy_source_or_cache_guards(selected_native_inputs):
    from tests.support import runtime_observation_evidence as runtime
    from tests.support import runtime_cursor_evidence as cursor
    old = audit.ROOT / runtime.RUNTIME_SOURCE_SUCCESSOR
    assert hashlib.sha256(old.read_bytes()).hexdigest() == 'da83fa524df905daf8b3ced0b83269777f085d7bb4d23f54b05f34a055cc7381'
    review = runtime.runtime_source_successor()
    assert len(review['members']) == 300
    assert len(review['packaged_sources']) == 483
    # Both finite reviews reject an actually unreviewed package change.
    source = audit.ROOT / 'skills/waapi-skill/scripts/run.py'
    original = source.read_bytes()
    try:
        source.write_bytes(original + b'\n# Unreviewed source change.\n')
        with pytest.raises(ValueError, match='exact current source'):
            runtime.runtime_source_successor()
        with pytest.raises(ValueError, match='exact current source|exact source/identity'):
            runtime.selected_runtime_source_successor()
    finally:
        source.write_bytes(original)
    route = '2024.1|wwise-authoring|2024.1.13.9056|function|ak.wwise.core.profiler.getCursorTime'
    with pytest.raises(ValueError, match='source delta'):
        cursor.original_cursor(route)



@pytest.mark.parametrize('damage', ['review-locator', 'scope'])
def test_selected_review_locator_and_scope_fail_closed(selected_native_inputs, damage):
    _, branches, bindings, _ = selected_native_inputs
    identity = next(i for i in bindings if '|wwise-authoring|' in i and i.endswith('getCpuUsage|/resultSchema'))
    binding = deepcopy(bindings[identity])
    if damage == 'review-locator':
        binding['native_only_review']['artifact'] = 'missing-selected-source-review.json'
        result = native_result(binding, branches[identity])
    else:
        result = completion.evidence_result(binding['evidence']['native'], branches[identity], 'e' * 64,
            'native', 'controlled', audit.ROOT, binding=binding, source_root=audit.ROOT)
    assert result[0] == 'missing'


@pytest.fixture(scope='module')
def legacy_native_packet():
    """Locator-only projection of two actual legacy packets, with original seals."""
    product = audit.ROOT / 'tests/fixtures/branch-evidence/product'
    packet = product / 'runtime-read-log-195-r1'
    original = json.loads((packet / 'native-index.json').read_bytes())
    entries = [original['entries'][number] for number in (0, 28)]
    policies = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    reference_ids = set()
    for entry in entries:
        requirements = completion.read_sealed_artifact(entry['origin']['requirements'], product)
        policies['branches'].update(requirements['branches'])
        bindings = completion.read_sealed_artifact(entry['bindings'], product)
        for binding in bindings['bindings'].values():
            reference_ids.update(binding['reference_chain'])
    identities = set(policies['branches'])
    routes = [identity.rsplit('|', 1)[0] for identity in identities]
    inventory = log_inventory(routes)
    inventory['native_coverage']['obligations'] = [row for row in inventory['native_coverage']['obligations']
        if row['id'] in identities or row['kind'] == 'reference' and row['id'] in reference_ids]
    assert identities <= {row['id'] for row in inventory['native_coverage']['obligations']}
    parent = audit.ROOT / '.waapi-skill-state'
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='legacy-native-test-', dir=parent) as name:
        index = Path(name) / 'index.json'
        document = {'contract': original['contract'], 'base': os.path.relpath(product, index.parent),
            'entries': entries,
            'runtime_observation_attachments': original['runtime_observation_attachments'][:1],
            'qualified_runtime_read_attachments': original['qualified_runtime_read_attachments'][:1]}
        index.write_text(json.dumps(document))
        yield {'index': index, 'requirements': policies, 'inventory': inventory}


def test_reviewed_legacy_native_packets_reach_portable_completion_without_current_code(legacy_native_packet):
    packet = legacy_native_packet
    imported, base, _ = audit.portable_binding_inputs(packet['index'], packet['requirements'])
    result = completion.evaluate_coverage(audit.ROOT, packet['inventory'], imported,
        digest=audit.digest, evidence_base=base, requirements_document=packet['requirements'])
    rows = [row for row in result['obligations'] if row['id'] in packet['requirements']['branches']]
    assert len(rows) == 2
    for row in rows:
        assert row['evidence_results']['native']['outcome'] == 'passed', row['evidence_results']
        assert row['evidence_results']['program']['outcome'] == 'missing'
        assert row['state'] != 'verified'
    from tests.support import runtime_observation_evidence as runtime
    original = json.loads((audit.ROOT / runtime.RUNTIME_SOURCE_SUCCESSOR).read_bytes())
    transitioned = runtime.runtime_source_successor()
    for key in set(original) - {'packaged_sources'}:
        assert transitioned[key] == original[key]


@pytest.mark.parametrize('damage', ['seal', 'schema', 'original-locator', 'current-locator',
    'missing-delta', 'wrong-before', 'missing-reason', 'original-bytes', 'current-bytes'])
def test_legacy_transition_tampering_is_rejected_by_portable_import(legacy_native_packet, native_output, monkeypatch, damage):
    from tests.support import runtime_observation_evidence as runtime
    packet = legacy_native_packet
    path = audit.ROOT / runtime.RUNTIME_SOURCE_TRANSITION
    transition = json.loads(path.read_bytes())
    if damage in {'original-bytes', 'current-bytes'}:
        descriptor = transition['original' if damage == 'original-bytes' else 'current']
        artifact = audit.ROOT / descriptor['artifact']
        original = artifact.read_bytes()
        try:
            artifact.write_bytes(original + b' ')
            with pytest.raises(ValueError, match='artifact digest mismatch'):
                audit.portable_binding_inputs(packet['index'], packet['requirements'])
        finally:
            artifact.write_bytes(original)
        return
    if damage == 'schema': transition['unreviewed'] = True
    elif damage == 'original-locator': transition['original']['artifact'] = '../source-successor.json'
    elif damage == 'current-locator': transition['current']['artifact'] = 'other-selected-source-successor.json'
    elif damage == 'missing-delta': transition['changed_files'].pop('skills/waapi-skill/scripts/gateway.py')
    elif damage == 'wrong-before': transition['changed_files']['skills/waapi-skill/scripts/gateway.py']['before'] = '0' * 64
    elif damage == 'missing-reason': next(iter(transition['reasons'].values()))['paths'].pop()
    altered = native_output / 'transition.json'
    altered.write_text(json.dumps(transition))
    monkeypatch.setattr(runtime, 'RUNTIME_SOURCE_TRANSITION', altered.relative_to(audit.ROOT).as_posix())
    # Resealing only the outer review tests semantic checks behind its byte seal.
    if damage != 'seal':
        monkeypatch.setattr(runtime, 'RUNTIME_SOURCE_TRANSITION_SHA', hashlib.sha256(altered.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='artifact digest mismatch|transition descriptors|transition delta/reasons|transition reasons'):
        audit.portable_binding_inputs(packet['index'], packet['requirements'])


@pytest.mark.parametrize('lane', ['legacy', 'selected'])
@pytest.mark.parametrize('damage', ['seal', 'original-locator', 'current-locator',
    'missing-delta', 'wrong-before', 'missing-reason', 'duplicate-reason', 'current-map'])
def test_current_package_transition_tampering_rejects_retained_native(
        legacy_native_packet, native_output, monkeypatch, lane, damage):
    """A resealed outer review cannot change the admitted sources or predecessor."""
    from tests.support import runtime_observation_evidence as runtime
    # Construct the real selected binding before damaging its admission inputs.
    selected_binding, selected_branch = retained_input() if lane == 'selected' else (None, None)
    transition = json.loads((audit.ROOT / runtime.CURRENT_RUNTIME_SOURCE_TRANSITION).read_bytes())
    if damage == 'original-locator':
        transition['original']['artifact'] = runtime.RUNTIME_SOURCE_SUCCESSOR
    elif damage == 'current-locator':
        transition['current']['artifact'] = REVIEW
    elif damage == 'missing-delta':
        transition['changed_files'].pop('skills/waapi-skill/wwise_waapi/operation_import.py')
    elif damage == 'wrong-before':
        transition['changed_files']['skills/waapi-skill/scripts/gateway.py']['before'] = '0' * 64
    elif damage == 'missing-reason':
        transition['reasons'].pop('registry_shared')
    elif damage == 'duplicate-reason':
        transition['reasons']['duplicate'] = deepcopy(transition['reasons']['registry_shared'])
    elif damage == 'current-map':
        sources = completion.read_sealed_artifact(transition['current'], audit.ROOT)
        sources['skills/waapi-skill/scripts/run.py'] = '0' * 64
        path = native_output / 'current-sources.json'
        path.write_text(json.dumps(sources))
        descriptor = {'artifact': path.relative_to(audit.ROOT).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        transition['current'] = descriptor
        monkeypatch.setattr(runtime, 'CURRENT_RUNTIME_PACKAGED_SOURCES', descriptor['artifact'])
        monkeypatch.setattr(runtime, 'CURRENT_RUNTIME_PACKAGED_SOURCES_SHA', descriptor['sha256'])
    altered = native_output / 'current-transition.json'
    altered.write_text(json.dumps(transition))
    monkeypatch.setattr(runtime, 'CURRENT_RUNTIME_SOURCE_TRANSITION', altered.relative_to(audit.ROOT).as_posix())
    if damage != 'seal':
        monkeypatch.setattr(runtime, 'CURRENT_RUNTIME_SOURCE_TRANSITION_SHA', hashlib.sha256(altered.read_bytes()).hexdigest())
    if lane == 'legacy':
        packet = legacy_native_packet
        with pytest.raises(ValueError, match='artifact digest mismatch|transition descriptors|transition delta/reasons|transition reasons|exact current source'):
            audit.portable_binding_inputs(packet['index'], packet['requirements'])
    else:
        result = native_result(selected_binding, selected_branch)
        assert result[0] == 'missing', result


@pytest.fixture(scope='module')
def portable_selected_native_packets():
    """Two locator namespaces over the same exact seven original packets."""
    from tests.support import runtime_observation_evidence as runtime
    product = audit.ROOT / 'tests/fixtures/branch-evidence/product'
    review = runtime.selected_runtime_source_successor()
    originals = {}
    for prefix in sorted({member['base'] for member in review['members'].values()}):
        path = audit.ROOT / prefix / 'index.json'
        index = json.loads(path.read_bytes())
        base = (path.parent / index['base']).resolve()
        for entry in index['entries']:
            bindings = completion.read_sealed_artifact(entry['origin']['bindings'], base)
            policies = completion.read_sealed_artifact(entry['origin']['requirements'], base)
            for identity, binding in bindings['bindings'].items():
                if identity in review['members']:
                    originals[identity] = (binding, policies['branches'][identity])
    parent = product / '.waapi-skill-state'
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='portable-native35-', dir=parent) as name:
        output = Path(name)
        packets = {}
        for namespace, base in (('root', audit.ROOT), ('product', product)):
            directory = output / namespace
            directory.mkdir()
            def locator(descriptor):
                return {**descriptor, 'artifact': (audit.ROOT / descriptor['artifact']).relative_to(base).as_posix()}
            def write(filename, value):
                path = directory / filename
                path.write_text(json.dumps(value), encoding='utf-8')
                return {'artifact': path.relative_to(base).as_posix(),
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            index = {'contract': 'waapi-skill.branch-evidence-index/v1',
                'base': os.path.relpath(base, directory), 'entries': [],
                'qualified_runtime_read_attachments': []}
            requirements = {'contract': audit.REQUIREMENTS_CONTRACT, 'branches': {}}
            for number, identity in enumerate(review['scope_ids']):
                member = review['members'][identity]
                original, policy = originals[identity]
                binding = deepcopy(original)
                binding['evidence'] = {}
                binding['native_only_base'] = (audit.ROOT / member['base']).relative_to(base).as_posix()
                binding['native_only_review'] = locator({'artifact': REVIEW,
                    'sha256': runtime.SELECTED_RUNTIME_SOURCE_SUCCESSOR_SHA})
                descriptor = write(f'{number:02}-bindings.json',
                    {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {identity: binding}})
                requirements['branches'][identity] = deepcopy(policy)
                policy_descriptor = write(f'{number:02}-requirements.json',
                    {'contract': audit.REQUIREMENTS_CONTRACT, 'branches': {identity: policy}})
                index['entries'].append({'id': f'native35-{number}', 'bindings': descriptor,
                    'origin': {'bindings': descriptor, 'requirements': policy_descriptor,
                        'program': locator(member['program']), 'capture': locator(member['capture'])}})
                index['qualified_runtime_read_attachments'].append(write(f'{number:02}-attachment.json',
                    {'contract': 'waapi-skill.qualified-retained-read-attachment/v1',
                        'branch_id': identity, 'assessment': locator(member['assessment']),
                        'evidence': locator(member['qualification'])}))
            write('index.json', index)
            packets[namespace] = {'index': directory / 'index.json', 'requirements': requirements}
        routes = [identity.rsplit('|', 1)[0] for identity in review['scope_ids']]
        inventory = log_inventory(routes, pointers={'/resultSchema'})
        # One original validator from each packet family, plus the distinct ACK
        # boundary. All 35 identities still pass ordinary portable admission.
        representatives = {}
        for identity in review['scope_ids']:
            member = review['members'][identity]
            key = (member['base'], member['facts'].get('business_boundary'))
            representatives.setdefault(key, identity)
            if member['facts'].get('original_public_complete') is False:
                representatives[key] = identity
        inventory['native_coverage']['obligations'] = [row
            for row in inventory['native_coverage']['obligations']
            if row['id'] in representatives.values()]
        yield {'packets': packets, 'review': review, 'inventory': inventory, 'output': output}


def test_selected_native35_product_base_matches_root_base_through_completion(portable_selected_native_packets):
    packet = portable_selected_native_packets
    expected = set(packet['review']['scope_ids'])
    for namespace, selected in packet['packets'].items():
        document, base, _ = audit.portable_binding_inputs(selected['index'], selected['requirements'])
        assert set(document['bindings']) == expected
        assert all(set(binding['evidence']) == {'native'} for binding in document['bindings'].values())
        ids = {row['id'] for row in packet['inventory']['native_coverage']['obligations']}
        bounded = {**document, 'bindings': {identity: document['bindings'][identity] for identity in ids}}
        requirements = {**selected['requirements'], 'branches': {
            identity: selected['requirements']['branches'][identity] for identity in ids}}
        result = completion.evaluate_coverage(audit.ROOT, packet['inventory'], bounded,
            digest=audit.digest, evidence_base=base, requirements_document=requirements)
        path = packet['output'] / f'{namespace}-completion.json'
        path.write_text(json.dumps(result), encoding='utf-8')
        rows = json.loads(path.read_bytes())['obligations']
        assert len(rows) == 8
        assert all(row['evidence_results']['native']['outcome'] == 'passed'
            and row['evidence_results']['program']['outcome'] == 'missing'
            and row['state'] != 'verified' for row in rows), rows
        if namespace == 'product':
            # Canonical Source v3 originals already use this same namespace.
            source_index = json.loads((base / 'source-195-current-88a6cbbe-2022.1/portable/index.json').read_bytes())
            descriptor = source_index['entries'][0]['origin']['program']
            assert completion.read_sealed_artifact(descriptor, base)
    cpu = next(member for identity, member in packet['review']['members'].items()
        if identity.startswith('2024.1|wwise-authoring|') and 'getCpuUsage|' in identity)
    assert cpu['facts']['native_nonempty_rows'] == 34
    assert cpu['facts']['original_public_complete'] is False
    assert cpu['facts']['original_finalization'] == 'BLOCKED'
    from tests.support import runtime_observation_evidence as runtime
    capture = completion.read_sealed_artifact(cpu['capture'], audit.ROOT)
    archive = runtime.archive_reader(capture['archive'], audit.ROOT)
    report = json.loads(archive(capture['capture_original_path']))
    public = report['outcomes']['profiler-cpu-observation']['evidence']['agent_result']
    assert (len(public['return']), public['returned_count'], public['total_count'],
        public['truncated'], public['complete']) == (16, 16, 34, True, False)
    assert all(member['facts']['global_pass_transferred'] is False
        for member in packet['review']['members'].values())


def test_product_base_native_import_keeps_locator_origin_and_scope_guards(portable_selected_native_packets):
    packet = portable_selected_native_packets
    selected = packet['packets']['product']
    index = json.loads(selected['index'].read_bytes())
    base = (selected['index'].parent / index['base']).resolve()
    identity = next(identity for identity in packet['review']['scope_ids']
        if identity.startswith('2024.1|wwise-authoring|') and 'getCpuUsage|' in identity)
    number = packet['review']['scope_ids'].index(identity)
    entry = index['entries'][number]
    attachment_descriptor = index['qualified_runtime_read_attachments'][number]
    original = completion.read_sealed_artifact(entry['bindings'], base)
    policy = {**selected['requirements'], 'branches': {identity: selected['requirements']['branches'][identity]}}
    directory = packet['output'] / 'controls'
    directory.mkdir()
    def write(name, value):
        path = directory / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return {'artifact': path.relative_to(base).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    for damage in ('review-locator', 'review-seal', 'mapping', 'origin-capture', 'assessment-seal'):
        binding = deepcopy(original)
        changed_entry = deepcopy(entry)
        attachment = completion.read_sealed_artifact(attachment_descriptor, base)
        native = binding['bindings'][identity]
        if damage == 'review-locator': native['native_only_review']['artifact'] = 'missing-selected-review.json'
        elif damage == 'review-seal': native['native_only_review']['sha256'] = '0' * 64
        elif damage == 'mapping': native['input']['selector'] = '/native_call/args'
        elif damage == 'origin-capture': changed_entry['origin']['capture'] = index['entries'][0]['origin']['capture']
        else: attachment['assessment']['sha256'] = '0' * 64
        descriptor = write(f'{damage}-bindings.json', binding)
        changed_entry['bindings'] = changed_entry['origin']['bindings'] = descriptor
        thin = {**index, 'base': os.path.relpath(base, directory), 'entries': [changed_entry],
            'qualified_runtime_read_attachments': [write(f'{damage}-attachment.json', attachment)]}
        write(f'{damage}-index.json', thin)
        with pytest.raises((OSError, ValueError), match='No such file|differs|digest mismatch'):
            audit.portable_binding_inputs(directory / f'{damage}-index.json', policy)
    thin = {**index, 'base': os.path.relpath(base, directory), 'entries': [entry],
        'qualified_runtime_read_attachments': [attachment_descriptor]}
    write('valid-index.json', thin)
    imported, _, _ = audit.portable_binding_inputs(directory / 'valid-index.json', policy)
    branch = next(row for row in packet['inventory']['native_coverage']['obligations'] if row['id'] == identity)
    for damage in ('qualification-seal', 'partial-as-complete', 'scope'):
        binding = deepcopy(imported['bindings'][identity])
        if damage == 'qualification-seal': binding['evidence']['native']['sha256'] = '0' * 64
        elif damage == 'partial-as-complete':
            record = completion.read_sealed_artifact(binding['evidence']['native'], base)
            record['retained_facts']['original_public_complete'] = True
            binding['evidence']['native'] = write('false-complete.json', record)
        result = completion.evidence_result(binding['evidence']['native'], branch, 'e' * 64,
            'native', 'controlled' if damage == 'scope' else 'product', base,
            binding=binding, source_root=audit.ROOT)
        assert result[0] == 'missing', (damage, result)


def current_mapping_successor(index_path, policies, inventory, mapper, output, *, selected_code=None):
    """Join real portable origins to actual current mapping through the standard reader."""
    from tests.maintenance.branch_audit_mapping import MAPPING_FIELDS
    original, base, _ = audit.portable_binding_inputs(index_path, policies)
    bindings = (mapper.runtime_bindings(audit.ROOT, inventory) if hasattr(mapper, 'runtime_bindings')
        else mapper.object_bindings(audit.ROOT, inventory))
    requirements = deepcopy(policies)
    requirements['representative_mechanisms'] = {}
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    proposed, predecessors, groups = {}, {}, {}
    for identity, current in bindings.items():
        old = original['bindings'].get(identity)
        proposed[identity] = {**deepcopy(current), **({key: deepcopy(value) for key, value in old.items()
            if key not in MAPPING_FIELDS | {'evidence'}} if old else {}), 'evidence': {}}
        mechanism = current['representative_mechanism']
        groups.setdefault(mechanism, []).append(identity)
        requirements['branches'][identity] = {**deepcopy(policies['branches'].get(identity,
            {'native_shape_sha256': rows[identity]['shape_sha256'], 'categories': ['program'],
                'reason': 'Current interface requires its actual ordinary CODE anchor'})),
            'representative_mechanism': mechanism}
        predecessors[identity] = ({'binding_sha256': audit.digest(old),
            'policy_sha256': audit.digest(policies['branches'][identity])} if old else None)
    for mechanism, identities in groups.items():
        categories = {category for identity in identities for category in requirements['branches'][identity]['categories']}
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
            'reviewed_reason': 'Current mapping and separate retained category evidence; no current CODE receipt invented',
            'sources': {name: hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest() for name in mapper.SOURCES},
            'members': {identity: {'native_route': rows[identity]['route'],
                'native_shape_sha256': rows[identity]['shape_sha256'],
                'mapping_sha256': audit.digest({key: value for key, value in proposed[identity].items() if key != 'evidence'})}
                for identity in identities},
            'selected_proofs': {category: [selected_code if category == 'program' and selected_code in identities
                else min(identity for identity in identities if category in requirements['branches'][identity]['categories'])]
                for category in categories}}
    output.mkdir()
    def emit(name, body):
        path = output / name
        path.write_text(json.dumps(body), encoding='utf-8')
        return {'artifact': path.relative_to(base).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    attachment = {'contract': 'waapi-skill.branch-mapping-attachment/v1', 'scope_kind': 'product',
        'requirements_sha256': audit.digest(requirements), 'mechanisms': sorted(groups),
        'bindings': proposed, 'predecessors': predecessors}
    index = json.loads(index_path.read_bytes())
    index.update(base=os.path.relpath(base, output), mapping_attachments=[emit('mapping.json', attachment)])
    emit('index.json', index)
    return {'index': output / 'index.json', 'requirements': requirements, 'inventory': inventory,
        'original': original, 'attachment': attachment, 'base': base, 'output': output, 'index_document': index}


@pytest.fixture(scope='module')
def native_current_mapping_case(portable_selected_native_packets):
    from tests.support import runtime_remaining_completion_mapping as mapper
    packet = portable_selected_native_packets
    selected = packet['packets']['product']
    ids = {identity for identity, member in packet['review']['members'].items()
        if identity.startswith('2024.1|wwise-authoring|') and ('getCpuUsage|' in identity or
            identity.endswith('transport.prepare|/resultSchema'))}
    assert len(ids) == 2
    directory = packet['output'] / 'current-native-origin'
    directory.mkdir()
    index = json.loads(selected['index'].read_bytes())
    base = (selected['index'].parent / index['base']).resolve()
    positions = [packet['review']['scope_ids'].index(identity) for identity in ids]
    index.update(base=os.path.relpath(base, directory), entries=[index['entries'][n] for n in positions],
        qualified_runtime_read_attachments=[index['qualified_runtime_read_attachments'][n] for n in positions])
    path = directory / 'index.json'
    path.write_text(json.dumps(index), encoding='utf-8')
    policies = {**selected['requirements'], 'branches': {identity: selected['requirements']['branches'][identity] for identity in ids}}
    inventory = log_inventory([identity.rsplit('|', 1)[0] for identity in ids], pointers={'/resultSchema'})
    for route in inventory['routes']:
        version, _, uri = route['id'].split('|')
        route['public_contracts'] = [audit.digest(mapper.public_contract(uri, version))]
    inventory['native_locations'] = dict.fromkeys(ids, [[]])
    inventory['runtime_roster_sha256'] = audit.digest([(row['id'], row['shape_sha256']) for row in inventory['native_coverage']['obligations']])
    inventory['runtime_routes_sha256'] = audit.digest(inventory['native_coverage']['routes'])
    return current_mapping_successor(path, policies, inventory, mapper, packet['output'] / 'current-native')


def test_current_runtime_mapping_retains_partial_cpu_and_transport_ack_without_code(native_current_mapping_case):
    case = native_current_mapping_case
    document, base, _ = audit.portable_binding_inputs(case['index'], case['requirements'])
    assert all(binding['input'].get('correspondence') for binding in document['bindings'].values())
    assert document['bindings'] != case['original']['bindings']
    result = completion.evaluate_coverage(audit.ROOT, case['inventory'], document, digest=audit.digest,
        evidence_base=base, requirements_document=case['requirements'])
    rows = result['obligations']
    assert len(rows) == 2
    assert all(row['evidence_results']['native']['outcome'] == 'passed' for row in rows), {row['id']: row['evidence_results'] for row in rows}
    assert all(row['evidence_results']['program']['outcome'] == 'missing' and row['state'] != 'verified' for row in rows)
    from tests.support import runtime_observation_evidence as runtime
    review = runtime.selected_runtime_source_successor()
    cpu = next(review['members'][row['id']] for row in rows if 'getCpuUsage|' in row['id'])
    assert (cpu['facts']['native_nonempty_rows'], cpu['facts']['original_public_complete'],
        cpu['facts']['original_finalization']) == (34, False, 'BLOCKED')
    capture = completion.read_sealed_artifact(cpu['capture'], audit.ROOT)
    archive = runtime.archive_reader(capture['archive'], audit.ROOT)
    report = json.loads(archive(capture['capture_original_path']))
    public = report['outcomes']['profiler-cpu-observation']['evidence']['agent_result']
    assert (len(public['return']), public['returned_count'], public['total_count'],
        public['truncated'], public['complete']) == (16, 16, 34, True, False)
    ack = next(review['members'][row['id']] for row in rows if 'transport.prepare|' in row['id'])
    assert ack['facts']['business_boundary'] == 'acknowledgment_schema_only'
    assert ack['facts']['acoustic_output_verified'] is False
    assert ack['facts']['global_mode_restoration_verified'] is False
    assert all('program' not in binding['evidence'] for binding in document['bindings'].values())
    assert all({key: value for key, value in binding.items() if key != 'evidence'} ==
        {key: value for key, value in case['attachment']['bindings'][identity].items() if key != 'evidence'}
        for identity, binding in document['bindings'].items())


def reject_current_mapping_damage(case, damage, identity):
    """Re-sign outer transport while preserving the guard being challenged."""
    import uuid
    requirements = deepcopy(case['requirements'])
    attachment = deepcopy(case['attachment'])
    index = deepcopy(case['index_document'])
    directory = case['output'] / ('negative-' + uuid.uuid4().hex)
    directory.mkdir()
    base = case['base']
    def emit(name, body):
        path = directory / name
        path.write_text(json.dumps(body), encoding='utf-8')
        return {'artifact': path.relative_to(base).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    binding = attachment['bindings'][identity]
    review = requirements['representative_mechanisms'][binding['representative_mechanism']]
    if damage == 'current-mapping':
        binding['input']['selector'] = '/unreviewed-current-selector'
    elif damage == 'current-review':
        review['sources'][next(iter(review['sources']))] = '0' * 64
    elif damage == 'predecessor':
        attachment['predecessors'][identity]['binding_sha256'] = '0' * 64
    elif damage == 'foreign-view':
        binding['category_evidence_mapping'] = deepcopy(case['original']['bindings'][identity]['input'])
        review['members'][identity]['mapping_sha256'] = audit.digest({key: value for key, value in binding.items() if key != 'evidence'})
    elif damage in {'original-binding', 'capture'}:
        entry = next(entry for entry in index['entries']
            if identity in completion.read_sealed_artifact(entry['bindings'], base)['bindings'])
        if damage == 'original-binding':
            original = completion.read_sealed_artifact(entry['origin']['bindings'], base)
            projected = completion.read_sealed_artifact(entry['bindings'], base)
            for document in (original, projected):
                document['bindings'][identity]['input']['selector'] = '/altered-original-selector'
            entry['origin']['bindings'] = emit('altered-original.json', original)
            entry['bindings'] = emit('altered-projection.json', projected)
        else:
            capture = completion.read_sealed_artifact(entry['origin']['capture'], base)
            capture['candidate'] = '0' * 40
            entry['origin']['capture'] = emit('altered-capture.json', capture)
    else:
        raise AssertionError(damage)
    attachment['requirements_sha256'] = audit.digest(requirements)
    index.update(base=os.path.relpath(base, directory), mapping_attachments=[emit('mapping.json', attachment)])
    emit('index.json', index)
    with pytest.raises((OSError, ValueError), match='differs|changed|source|original|metadata|exact'):
        audit.portable_binding_inputs(directory / 'index.json', requirements)


@pytest.mark.parametrize('damage', ['current-mapping', 'current-review', 'predecessor', 'foreign-view', 'original-binding', 'capture'])
def test_current_native_mapping_cannot_bypass_review_or_original_guards(native_current_mapping_case, damage):
    case = native_current_mapping_case
    identity = next(identity for identity in case['original']['bindings'] if 'getCpuUsage|' in identity)
    reject_current_mapping_damage(case, damage, identity)


@pytest.mark.parametrize('damage', ['shape', 'qualification-seal', 'qualification-facts', 'foreign-category-view'])
def test_current_native_category_keeps_exact_seals_and_partial_limits(native_current_mapping_case, damage):
    case = native_current_mapping_case
    document, base, _ = audit.portable_binding_inputs(case['index'], case['requirements'])
    identity = next(identity for identity in document['bindings'] if 'getCpuUsage|' in identity)
    binding = deepcopy(document['bindings'][identity])
    branch = deepcopy(next(row for row in case['inventory']['native_coverage']['obligations'] if row['id'] == identity))
    descriptor = deepcopy(binding['evidence']['native'])
    if damage == 'shape':
        branch['shape_sha256'] = '0' * 64
    elif damage == 'qualification-seal':
        descriptor['sha256'] = '0' * 64
    elif damage == 'qualification-facts':
        record = completion.read_sealed_artifact(descriptor, base)
        record['retained_facts']['original_public_complete'] = True
        path = case['output'] / 'false-complete-qualification.json'
        path.write_text(json.dumps(record), encoding='utf-8')
        descriptor = {'artifact': path.relative_to(base).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    else:
        # An invented native view cannot replace the actual current mapping.
        reject_current_mapping_damage(case, 'foreign-view', identity)
        return
    result = completion.evidence_result(descriptor, branch, case['inventory']['native_coverage']['candidate_sha256'],
        'native', 'product', base, binding=binding, source_root=audit.ROOT)
    assert result[0] == 'missing', result
