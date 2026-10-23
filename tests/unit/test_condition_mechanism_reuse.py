"""Accepted mechanism reuse never fabricates a native recipient observation."""
from copy import deepcopy
import base64
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evidence_result, installed_obligations, read_sealed_artifact
from tests.support import condition_scalar_batch, condition_scalar_program
from tests.support.condition_mechanism_reuse import attach_condition_mechanisms, load_review
from tests.support.condition_branch_evidence import SHOW_BRANCH_ID
from tests.unit.test_scalar_condition_product_gateway import run_scalar_public_group

ROOT = Path(__file__).parents[2]


def write(path, value):
    path.write_text(json.dumps(value, indent=2))
    return {'artifact': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture(scope='module')
def inputs():
    plan = condition_scalar_batch.scalar_plan(condition_scalar_batch.scalar_manifest(ROOT))
    group = next(g for g in plan['groups'] if g['version'] == '2025.1' and g['field'] == 'LfoSmoothing')
    ids = {m['id'] for m in group['members']} | {SHOW_BRANCH_ID}
    branches = {b['id']: b for b in installed_obligations(ROOT, digest=audit.digest, load=audit.load) if b['id'] in ids}
    return plan, group, branches


@pytest.fixture(scope='module')
def program(tmp_path_factory, inputs):
    plan, group, branches = deepcopy(inputs)
    root = tmp_path_factory.mktemp('condition-mechanism-program')
    inventory = {'native_coverage': {'candidate_sha256': 'c' * 64, 'obligations': list(branches.values())},
        'routes': [{'id': '2025.1|function|ak.wwise.core.object.setProperty'}]}
    node = 'tests/unit/test_condition_mechanism_reuse.py::controlled_current_public_lfo_flow'
    capture = condition_scalar_program.prepare_program_batch(root / 'capture', [node], {**plan, 'groups': [group]}, inventory)
    observed = run_scalar_public_group(root / 'workflow', group, capture_scope=True)
    condition_scalar_program.finish_program_node(capture, node,
        {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}, {group['id']: observed})
    published = root / 'capture/published'
    return published, json.loads((published / 'bindings.json').read_text())['bindings']


def bundle(tmp_path, program):
    published, bindings = program
    bindings = deepcopy(bindings)
    originals = json.loads(gzip.decompress((ROOT / 'tests/fixtures/metadata-conditions/lfo-eq-originals.json.gz').read_bytes()))
    descriptors = {}
    for name, entry in originals.items():
        raw = base64.b64decode(entry['bytes_base64'], validate=True)
        assert hashlib.sha256(raw).hexdigest() == entry['sha256']
        (tmp_path / name).write_bytes(raw)
        descriptors[name] = {'artifact': name, 'sha256': entry['sha256']}
    review = load_review(ROOT)
    (tmp_path / 'review.json').write_bytes((ROOT / 'tests/fixtures/metadata-conditions/lfo-eq-mechanism-review.json').read_bytes())
    descriptor = {'artifact': 'review.json', 'sha256': hashlib.sha256((tmp_path / 'review.json').read_bytes()).hexdigest()}
    attachment = {'contract': 'waapi-skill.condition-mechanism-attachment/v1', 'review': descriptor,
        'members': [{'branch_id': i, 'shape_sha256': s, 'owner_issue': 177, 'parent_issue': 174}
                    for i, s in review['selected_members'].items()],
        'originals': {'category': {**descriptors['eq-category.jsonl'], 'record_index': 1, 'nodeid': review['witness']['nodeid']},
            'observation': descriptors['eq-observation.json'], 'class_metadata': descriptors['lfo-class-metadata.json'],
            'accepted_review': descriptors['accepted-r85.json']},
        'direct_recipient_native_effect': 'not_observed', 'new_native_runs': 0}
    # Program descriptors remain the original current producer paths. The
    # attachment itself and every archived native dependency remain portable.
    def read(descriptor, *, record_index=None):
        return read_sealed_artifact({**descriptor, **({'record_index': record_index} if record_index is not None else {})}, tmp_path)
    return bindings, attachment, read


def test_exact_accepted_lfo_reuse_is_distinct_from_a_native_recipient_pass(tmp_path, inputs, program):
    _, _, branches = inputs
    bindings, attachment, read = bundle(tmp_path, program)
    descriptor = write(tmp_path / 'attachment.json', attachment)
    facts = attach_condition_mechanisms([descriptor], bindings, read, tmp_path, ROOT)
    assert facts == [{'review_id': 'r85-lfo-smoothing-2025-eq',
        'original_witness_run_id': 'r84-eq-gain-66a2a1f1-2025-r2',
        'direct_recipient_native_effect': 'not_observed', 'new_native_runs': 0}]
    for identity, binding in bindings.items():
        assert evidence_result(binding['evidence']['program'], branches[identity], 'c' * 64,
            'program', 'controlled', tmp_path, binding, ROOT) == ('passed', None)
        assert evidence_result(binding['evidence']['native'], branches[identity], 'c' * 64,
            'native', 'controlled', tmp_path, binding, ROOT) == ('reviewed_mechanism_reuse',
                'r85-lfo-smoothing-2025-eq; original_witness_run_id=r84-eq-gain-66a2a1f1-2025-r2; direct_recipient_native_effect=not_observed; new_native_runs=0')
        assert evidence_result(binding['evidence']['native'], branches[identity], 'c' * 64,
            'native', 'product', tmp_path, binding, ROOT)[0] == 'missing'
    assert 'branch_assertions' not in read(attachment['originals']['observation'])


@pytest.mark.parametrize('damage', ['type', 'show', 'controller', 'topology'])
def test_changed_current_program_graph_cannot_borrow_the_native_mechanism(tmp_path, inputs, program, damage):
    bindings, attachment, read = bundle(tmp_path, program)
    descriptor = write(tmp_path / 'attachment.json', attachment)
    attach_condition_mechanisms([descriptor], bindings, read, tmp_path, ROOT)
    identity = next(iter(bindings))
    binding = bindings[identity]
    record = read_sealed_artifact(binding['evidence']['program'], tmp_path)
    metadata = record['observations']['metadata']
    if damage == 'type':
        metadata['type'] = 'string'
    elif damage == 'show':
        metadata['dependencies'][0]['action'] = 'Show'
    elif damage == 'controller':
        metadata['dependencies'][0]['property'] = 'OtherWaveform'
    else:
        metadata['dependencies'].append(deepcopy(metadata['dependencies'][0]))
    # Even a coherent rewritten assertion cannot turn a different public graph
    # into the pinned reviewed graph. This is not a digest-only corruption test.
    for assertion in record['branch_assertions'].values():
        for check in assertion['checks']:
            if check['pointer'].startswith('/observations/metadata/'):
                check['equals'] = deepcopy(record['observations']['metadata']['dependencies'][0])
    changed = write(tmp_path / 'changed-program.json', record)
    binding['evidence']['program'] = {**changed, 'nodeid': binding['evidence']['program']['nodeid']}
    result = evidence_result(binding['evidence']['native'], inputs[2][identity], 'c' * 64,
        'native', 'controlled', tmp_path, binding, ROOT)
    assert result[0] == 'missing' and 'program metadata graph' in result[1]


@pytest.mark.parametrize('damage', ['missing-member', 'extra-member', 'duplicate-member', 'owner',
    'native-promotion', 'new-run', 'wrong-witness-digest', 'untrusted-review', 'absolute-path',
    'traversal-path', 'duplicate-attachments', 'conflicting-native'])
def test_only_the_exact_owned_review_can_attach_without_native_promotion(tmp_path, inputs, program, damage):
    bindings, attachment, read = bundle(tmp_path, program)
    if damage == 'missing-member': attachment['members'].pop()
    elif damage == 'extra-member': attachment['members'].append({**attachment['members'][0], 'branch_id': 'not-reviewed'})
    elif damage == 'duplicate-member': attachment['members'].append(deepcopy(attachment['members'][0]))
    elif damage == 'owner': attachment['members'][0]['owner_issue'] = 181
    elif damage == 'native-promotion': attachment['direct_recipient_native_effect'] = 'observed'
    elif damage == 'new-run': attachment['new_native_runs'] = 1
    elif damage == 'wrong-witness-digest': attachment['originals']['observation']['sha256'] = '0' * 64
    elif damage == 'untrusted-review':
        review = load_review(ROOT)
        review['justification'] = 'Caller says the whole family passed'
        attachment['review'] = write(tmp_path / 'unreviewed.json', review)
    elif damage == 'absolute-path': attachment['originals']['observation']['artifact'] = str(tmp_path / 'eq-observation.json')
    elif damage == 'traversal-path': attachment['originals']['observation']['artifact'] = '../eq-observation.json'
    elif damage == 'conflicting-native': next(iter(bindings.values()))['evidence']['native'] = {'artifact': 'not-original'}
    descriptor = write(tmp_path / 'attachment.json', attachment)
    before = deepcopy(bindings)
    with pytest.raises(ValueError):
        attach_condition_mechanisms([descriptor, descriptor] if damage == 'duplicate-attachments' else [descriptor],
            bindings, read, tmp_path, ROOT)
    assert bindings == before


@pytest.mark.parametrize('damage', ['version', 'build', 'shape', 'source', 'owner', 'parent'])
def test_native_reuse_does_not_flow_to_another_branch_context(tmp_path, inputs, program, damage):
    bindings, attachment, read = bundle(tmp_path, program)
    attach_condition_mechanisms([write(tmp_path / 'attachment.json', attachment)], bindings, read, tmp_path, ROOT)
    identity = next(iter(bindings))
    branch = deepcopy(inputs[2][identity])
    if damage == 'version': branch['version'] = '2024.1'
    elif damage == 'build': branch['build'] = '2025.1.0.0'
    elif damage == 'shape': branch['shape_sha256'] = '0' * 64
    elif damage == 'source': branch['source_file_sha256'] = '0' * 64
    elif damage == 'owner': branch['owner_issue'] = 181
    else: branch['parent_issue'] = 999
    binding = bindings[identity]
    result = evidence_result(binding['evidence']['native'], branch, 'c' * 64,
        'native', 'controlled', tmp_path, binding, ROOT)
    assert result[0] == 'missing' and 'ownership/shape/host' in result[1]


def test_completion_counts_one_reviewed_witness_and_keeps_metadata_unproven(tmp_path, inputs, program):
    from tests.maintenance.branch_audit_completion import evaluate_coverage
    bindings, attachment, read = bundle(tmp_path, program)
    attach_condition_mechanisms([write(tmp_path / 'attachment.json', attachment)], bindings, read, tmp_path, ROOT)
    public = {'id': '2025.1|function|ak.wwise.core.object.setProperty'}
    for binding in bindings.values():
        binding['additional_requirements'] = ['native']
    branches = [deepcopy(inputs[2][identity]) for identity in bindings]
    inventory = {'routes': [public], 'native_coverage': {'candidate_sha256': 'c' * 64,
        'catalogs': {}, 'routes': [{'id': None, 'uri': 'source-condition', 'public_route': public['id']}],
        'obligations': branches}}
    scope = {'contract': 'waapi-skill.controlled-branch-scope/v1', 'credit': 'controlled_program_only',
        'id': 'condition-adapter-control', 'requirements': ['program'], 'native_catalogs': {},
        'route_ids': [None], 'obligation_ids': list(bindings)}
    result = evaluate_coverage(ROOT, inventory, {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': bindings},
        digest=audit.digest, scope=scope, evidence_base=tmp_path)
    assert {b['state'] for b in result['obligations']} == {'verified'}
    assert result['condition_mechanism_reuse'] == {'original_witness_run_ids': ['r84-eq-gain-66a2a1f1-2025-r2'],
        'review_ids': ['r85-lfo-smoothing-2025-eq'], 'new_native_runs': 0}
    assert {b['evidence_results']['native']['outcome'] for b in result['obligations']} == {'reviewed_mechanism_reuse'}
    assert {b['direct_recipient_native_effect'] for b in result['obligations']} == {'not_observed'}
    for binding in bindings.values():
        binding['additional_requirements'].append('live_metadata')
    missing = evaluate_coverage(ROOT, inventory, {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': bindings},
        digest=audit.digest, scope=scope, evidence_base=tmp_path)
    assert {b['state'] for b in missing['obligations']} == {'implemented_unverified'}
    assert all(b['evidence_results']['live_metadata']['outcome'] == 'missing' for b in missing['obligations'])


def test_scoped_class_metadata_reuse_does_not_claim_an_observed_instance(tmp_path, inputs, program):
    bindings, attachment, read = bundle(tmp_path, program)
    attachment['include_scoped_metadata_mechanism'] = True
    facts = attach_condition_mechanisms([write(tmp_path / 'attachment.json', attachment)], bindings, read, tmp_path, ROOT)
    identity = next(iter(bindings))
    binding = bindings[identity]
    result = evidence_result(binding['evidence']['live_metadata'], inputs[2][identity], 'c' * 64,
        'live_metadata', 'controlled', tmp_path, binding, ROOT)
    assert result == ('reviewed_class_metadata_and_object_scope_mechanism',
        'r85-lfo-smoothing-2025-eq; metadata_scope=object_type; direct_recipient_instance_metadata=not_observed')
    assert 'branch_assertions' not in read(attachment['originals']['observation'])


@pytest.mark.parametrize('damage', ['drop-read', 'drop-refresh', 'wrong-scope', 'changed-write', 'null-uri', 'fake-instance'])
def test_scoped_metadata_reuse_requires_observed_current_scope_calls(tmp_path, inputs, program, damage):
    bindings, attachment, read = bundle(tmp_path, program)
    attachment['include_scoped_metadata_mechanism'] = True
    attach_condition_mechanisms([write(tmp_path / 'attachment.json', attachment)], bindings, read, tmp_path, ROOT)
    identity = next(iter(bindings))
    binding = bindings[identity]
    record = read_sealed_artifact(binding['evidence']['program'], tmp_path)
    calls = record['object_scope_call_trace']
    if damage == 'drop-read':
        record['object_scope_call_trace'] = [c for c in calls if not c['uri'].endswith('getPropertyInfo')]
    elif damage == 'drop-refresh':
        selected = [c for c in calls if c['uri'].endswith('getPropertyInfo')]
        record['object_scope_call_trace'] = [c for c in calls if not c['uri'].endswith('getPropertyInfo')] + selected[:1]
    elif damage == 'wrong-scope':
        for call in calls:
            if call['uri'].endswith('getPropertyInfo'):
                call['args'] = {'classId': 4194320, 'property': call['args']['property']}
    elif damage == 'changed-write':
        for call in calls:
            if call['uri'].endswith('setProperty'):
                call['args']['value'] = 'not-the-observed-write'
    elif damage == 'null-uri':
        calls[0]['uri'] = None
    else:
        record['direct_recipient_instance_metadata'] = 'observed'
    changed = write(tmp_path / 'changed-scope.json', record)
    binding['evidence']['program'] = {**changed, 'nodeid': binding['evidence']['program']['nodeid']}
    result = evidence_result(binding['evidence']['live_metadata'], inputs[2][identity], 'c' * 64,
        'live_metadata', 'controlled', tmp_path, binding, ROOT)
    assert result[0] == 'missing'


def test_portable_index_imports_the_same_closed_condition_attachment(tmp_path, inputs, program):
    # Synthetic transport projection of the current controlled public flow;
    # these flattened records grant no product evidence or publication claim.
    base = tmp_path / 'bundle'
    base.mkdir()
    bindings, attachment, read = bundle(base, program)
    attachment['include_scoped_metadata_mechanism'] = True
    attachment_descriptor = write(base / 'attachment.json', attachment)
    groups = {}
    for identity, binding in bindings.items():
        groups.setdefault(binding['evidence']['program']['sha256'], []).append(identity)
    entries, policies = [], {}
    for index, ids in enumerate(groups.values()):
        original = read_sealed_artifact(bindings[ids[0]]['evidence']['program'], base)
        original['artifacts'] = []
        record = write(base / f'controlled-program-{index}.json', original)
        raw_bindings = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {i: deepcopy(bindings[i]) for i in ids}}
        for binding in raw_bindings['bindings'].values():
            binding['evidence']['program'].update(record, artifact=str(base / record['artifact']))
        original_bindings = write(base / f'original-bindings-{index}.json', raw_bindings)
        projected = deepcopy(raw_bindings)
        for binding in projected['bindings'].values():
            binding['evidence']['program']['artifact'] = record['artifact']
        projection = write(base / f'projection-{index}.json', projected)
        policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {
            i: {'native_shape_sha256': bindings[i]['native_shape_sha256'], 'categories': ['program', 'native', 'live_metadata'],
                'reason': 'Controlled attachment transport only, not product coverage.'} for i in ids}}
        policies.update(policy['branches'])
        entries.append({'id': f'controlled-{index}', 'bindings': projection, 'origin': {'bindings': original_bindings,
            'program': record, 'requirements': write(base / f'policy-{index}.json', policy),
            'capture': write(base / f'capture-{index}.json', {'control_only': True})}})
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': 'bundle', 'entries': entries,
        'condition_mechanism_attachments': [attachment_descriptor]}
    path = tmp_path / 'index.json'
    path.write_text(json.dumps(index))
    imported, evidence_base, assessment = audit.portable_binding_inputs(path,
        {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': policies})
    assert evidence_base == base.resolve()
    assert len(imported['bindings']) == 6
    assert assessment['condition_mechanism_reuse'][0]['new_native_runs'] == 0
    identity = next(iter(imported['bindings']))
    binding = imported['bindings'][identity]
    result = evidence_result(binding['evidence']['live_metadata'], inputs[2][identity], 'c' * 64,
        'live_metadata', 'controlled', evidence_base, binding, ROOT)
    assert result[0] == 'reviewed_class_metadata_and_object_scope_mechanism'


def test_condition_adapter_and_review_bytes_are_part_of_the_accounting_candidate(tmp_path):
    from tests.maintenance.branch_audit_completion import candidate_identity
    (tmp_path / 'skills/waapi-skill').mkdir(parents=True)
    (tmp_path / 'skills/waapi-skill/SKILL.md').write_text('controlled source identity')
    (tmp_path / 'tests/maintenance').mkdir(parents=True)
    for name in ('branch_coverage_audit.py', 'branch_audit_completion.py'):
        (tmp_path / 'tests/maintenance' / name).write_text('controlled accounting')
    (tmp_path / 'docs').mkdir()
    for name in ('branch-coverage-ownership.json', 'branch-coverage-condition-sources.json', 'branch-coverage-requirements.json'):
        (tmp_path / 'docs' / name).write_text('{}')
    adapter = tmp_path / 'tests/support/condition_mechanism_reuse.py'
    adapter.parent.mkdir()
    adapter.write_text('original adapter')
    review = tmp_path / 'tests/fixtures/metadata-conditions/lfo-eq-mechanism-review.json'
    review.parent.mkdir(parents=True)
    review.write_text('original trusted review')
    before = candidate_identity(tmp_path, {'sources': {}}, {}, digest=audit.digest)
    adapter.write_text('changed adapter')
    changed = candidate_identity(tmp_path, {'sources': {}}, {}, digest=audit.digest)
    assert changed != before
    review.write_text('changed trusted review')
    assert candidate_identity(tmp_path, {'sources': {}}, {}, digest=audit.digest) != changed


def test_changed_reviewed_runtime_source_requires_a_new_explicit_review(tmp_path, program):
    import shutil
    bundle_root = tmp_path / 'bundle'
    bundle_root.mkdir()
    bindings, attachment, read = bundle(bundle_root, program)
    root = tmp_path / 'source'
    review = load_review(ROOT)
    for name in [*review['current_sources'], 'tests/fixtures/metadata-conditions/lfo-eq-mechanism-review.json']:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    changed = root / 'skills/waapi-skill/wwise_waapi/operation_registry.py'
    changed.write_bytes(changed.read_bytes() + b'\n# Unreviewed source delta\n')
    with pytest.raises(ValueError, match='source dependencies changed'):
        attach_condition_mechanisms([write(bundle_root / 'attachment.json', attachment)], bindings, read, bundle_root, root)


def test_exact_member_roster_order_has_no_semantic_meaning(tmp_path, inputs, program):
    bindings, attachment, read = bundle(tmp_path, program)
    attachment['members'].reverse()
    assert attach_condition_mechanisms([write(tmp_path / 'attachment.json', attachment)], bindings, read, tmp_path, ROOT)[0]['new_native_runs'] == 0


def test_metadata_category_requires_its_explicit_scoped_mechanism_attachment(tmp_path, inputs, program):
    bindings, attachment, read = bundle(tmp_path, program)
    attach_condition_mechanisms([write(tmp_path / 'attachment.json', attachment)], bindings, read, tmp_path, ROOT)
    identity = next(iter(bindings))
    binding = bindings[identity]
    binding['condition_metadata_mechanism_attachment'] = deepcopy(binding['condition_mechanism_attachment'])
    result = evidence_result(binding['evidence']['native'], inputs[2][identity], 'c' * 64,
        'live_metadata', 'controlled', tmp_path, binding, ROOT)
    assert result[0] == 'missing' and 'explicit scoped metadata' in result[1]
