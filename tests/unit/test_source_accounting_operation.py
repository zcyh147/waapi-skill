"""Source admission reuses only a validated review inside one owned operation."""
import json
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.support import source_copy_native_evidence as source


@pytest.fixture
def accounting_packet(tmp_path, monkeypatch):
    """Real immutable packet with a tiny, filesystem-selected current policy."""
    from tests.support.source_copy_branch_evidence import write_json, native_route
    from tests.maintenance import branch_audit_completion as completion
    from tests.unit.test_runtime_log_branch_evidence import log_inventory
    product = audit.ROOT / 'tests/fixtures/branch-evidence/product'
    original = product / 'source-195-current-88a6cbbe-2022.1/portable/index.json'
    index = json.loads(original.read_bytes())
    native = completion.read_sealed_artifact(index['source_native_attachments'][0], product)
    requirements = completion.read_sealed_artifact(index['entries'][0]['origin']['requirements'], product)
    policy = tmp_path / 'requirements.json'
    audit.write_requirements(policy, {'contract': audit.REQUIREMENTS_CONTRACT, 'branches': {}})
    view = {audit.ROOT / source.REQUIREMENTS_SOURCE: policy}
    for part in json.loads(policy.read_bytes())['parts']:
        view[audit.ROOT / 'docs' / part['path']] = policy.parent / part['path']
    original_open = Path.open
    def selected_open(path, *args, **kwargs):
        return original_open(view.get(path, path), *args, **kwargs)
    monkeypatch.setattr(Path, 'open', selected_open)
    review = json.loads((audit.ROOT / source.ACCOUNTING_REVIEW_PATH).read_bytes())
    review['current_accounting_sources'] = source.accounting_source_seals(review['current_accounting_sources'])
    review['source_changes'] = {name: {'captured_sha256': review['captured_capture_sources'].get(name),
        'current_sha256': seal, 'reason': 'Test-owned exact current accounting bytes and tiny policy.'}
        for name, seal in review['current_accounting_sources'].items()
        if review['captured_capture_sources'].get(name) != seal}
    review_path = tmp_path / 'review.json'
    descriptor = write_json(review_path, review)
    reader = tmp_path / 'reader.py'
    reader.write_bytes((audit.ROOT / source.ACCOUNTING_READER).read_bytes().replace(
        source.ACCOUNTING_REVIEW_SHA256.encode(), descriptor['sha256'].encode()))
    view[audit.ROOT / source.ACCOUNTING_REVIEW_PATH] = review_path
    view[audit.ROOT / source.ACCOUNTING_READER] = reader
    monkeypatch.setattr(source, 'ACCOUNTING_REVIEW_SHA256', descriptor['sha256'])
    reads = []
    def counted_open(path, *args, **kwargs):
        if path == audit.ROOT / source.ACCOUNTING_REVIEW_PATH:
            reads.append(path)
        return selected_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', counted_open)
    # Own the destination below the real product boundary; preserve diagnostics.
    import tempfile
    temporary = tempfile.TemporaryDirectory(prefix='.source-accounting-operation-', dir=product)
    yield {'original': original, 'native': native, 'requirements': requirements,
        'inventory': log_inventory(native_route('2022.1')), 'product': product,
        'output': Path(temporary.name), 'reads': reads, 'view': view, 'policy': policy}
    temporary.cleanup()


def test_publisher_validates_full_accounting_only_at_operation_boundaries(accounting_packet):
    case = accounting_packet
    result = source.publish_source_native_successor(case['original'], predecessor=case['native']['predecessor'],
        inventory=case['inventory'], product_base=case['product'], destination=case['output'] / 'publication', accounting=True)
    assert result.name == 'index.json' and result.is_file()
    assert len(case['reads']) == 2


def _publish(case, name='publication'):
    return source.publish_source_native_successor(case['original'], predecessor=case['native']['predecessor'],
        inventory=case['inventory'], product_base=case['product'], destination=case['output'] / name, accounting=True)


def test_import_and_nested_coverage_each_validate_once_at_their_boundaries(accounting_packet):
    from tests.maintenance import branch_audit_completion as completion
    case = accounting_packet
    index = _publish(case)
    case['reads'].clear()
    document, base, _ = audit.portable_binding_inputs(index, case['requirements'])
    assert len(document['bindings']) == 4 and len(case['reads']) == 2
    case['reads'].clear()
    result = completion.evaluate_coverage(audit.ROOT, case['inventory'], document, digest=audit.digest,
        evidence_base=base, requirements_document=case['requirements'])
    assert len(case['reads']) == 2
    rows = {row['id']: row for row in result['obligations']}
    assert all(rows[identity]['evidence_results'][category]['outcome'] == 'passed'
        for identity in document['bindings'] for category in ('program', 'native'))


def test_consecutive_evidence_operations_and_standalone_reviews_are_fresh(accounting_packet):
    from tests.maintenance import branch_audit_completion as completion
    case = accounting_packet
    index = _publish(case)
    document, base, _ = audit.portable_binding_inputs(index, case['requirements'])
    identity, binding = next(iter(document['bindings'].items()))
    branch = next(row for row in case['inventory']['native_coverage']['obligations'] if row['id'] == identity)
    references = {row['id']: row for row in case['inventory']['native_coverage']['obligations'] if row['kind'] == 'reference'}
    for _ in range(2):
        case['reads'].clear()
        assert completion.evidence_result(binding['evidence']['program'], branch,
            case['inventory']['native_coverage']['candidate_sha256'], 'program', 'product', base,
            binding, source_root=audit.ROOT, reference_edges=references) == ('passed', None)
        assert len(case['reads']) == 2
    case['reads'].clear()
    assert source.accounting_dependency_review() == source.accounting_dependency_review()
    assert len(case['reads']) == 2


@pytest.mark.parametrize('drift', ('policy-bytes', 'policy-part', 'index-bytes', 'source-bytes'))
def test_publication_exit_drift_rejects_before_final_index(accounting_packet, monkeypatch, tmp_path, drift):
    case = accounting_packet
    original_open = Path.open
    triggered = []
    def drifted_open(path, *args, **kwargs):
        mode = kwargs.get('mode', args[0] if args else None)
        if path.name == 'index.json.pending' and mode == 'rb' and not triggered:
            triggered.append(path)
            if drift == 'policy-bytes':
                target = case['policy']
            elif drift == 'policy-part':
                target = case['policy'].parent / json.loads(case['policy'].read_bytes())['parts'][0]['path']
            elif drift == 'source-bytes':
                target = case['view'][audit.ROOT / source.ACCOUNTING_READER]
            else:
                canonical = audit.ROOT / 'docs/branch-coverage-evidence-index.json'
                target = tmp_path / 'changed-index.json'
                target.write_bytes(canonical.read_bytes())
                case['view'][canonical] = target
            triggered.append(target)
            with original_open(target, 'ab') as stream:
                stream.write(b'\n')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', drifted_open)
    with pytest.raises(ValueError, match='changed during operation|digest mismatch|dependency changed'):
        _publish(case)
    assert triggered
    portable = case['output'] / 'publication/portable'
    assert not (portable / 'index.json').exists()
    assert (portable / 'index.json.pending').is_file()
    with original_open(triggered[1], 'r+b') as stream:
        stream.seek(-1, 2)
        stream.truncate()
    case['reads'].clear()
    assert _publish(case, 'after-failure').is_file()
    assert len(case['reads']) == 2


@pytest.mark.parametrize('damage', ('candidate', 'packet', 'equivalence', 'missing-branch'))
def test_cached_review_does_not_admit_damaged_binding_attribution(accounting_packet, damage):
    from copy import deepcopy
    import os
    from tests.support.source_copy_branch_evidence import write_json
    from tests.maintenance import branch_audit_completion as completion
    case = accounting_packet
    index_path = _publish(case)
    index = json.loads(index_path.read_bytes())
    output = case['output'] / 'damaged'; output.mkdir()
    def emit(name, value):
        path = output / name
        return {**write_json(path, value), 'artifact': path.relative_to(case['product']).as_posix()}
    native = completion.read_sealed_artifact(index['source_native_attachments'][0], case['product'])
    native = deepcopy(native)
    if damage in {'candidate', 'packet'}:
        context = completion.read_sealed_artifact(native['successor_context'], case['product'])
        if damage == 'candidate': context['current_candidate_sha256'] = '0' * 64
        else: context['previous_index']['sha256'] = '0' * 64
        native['successor_context'] = emit('context.json', context)
    elif damage == 'equivalence':
        identity = next(iter(native['program_equivalence']))
        proof = completion.read_sealed_artifact(native['program_equivalence'][identity], case['product'])
        proof['binding_semantics_sha256'] = '0' * 64
        native['program_equivalence'][identity] = emit('equivalence.json', proof)
    else:
        native['branch_ids'].pop()
    index['source_native_attachments'] = [emit('native.json', native)]
    index['base'] = os.path.relpath(case['product'], output)
    changed = output / 'index.json'; write_json(changed, index)
    if damage in {'packet', 'missing-branch'}:
        with pytest.raises(ValueError):
            audit.portable_binding_inputs(changed, case['requirements'])
    else:
        document, base, _ = audit.portable_binding_inputs(changed, case['requirements'])
        result = completion.evaluate_coverage(audit.ROOT, case['inventory'], document, digest=audit.digest,
            evidence_base=base, requirements_document=case['requirements'])
        rows = {row['id']: row for row in result['obligations']}
        assert any(rows[identity]['evidence_results']['program']['outcome'] == 'missing'
            for identity in document['bindings'])
        assert not result['completion']['complete']


def test_unrelated_evidence_does_not_load_source_policy(tmp_path):
    from tests.maintenance import branch_audit_completion as completion
    result = completion.evidence_result(None, {'id': 'unrelated', 'route': 'unrelated'},
        'a' * 64, 'program', 'product', tmp_path, source_root=tmp_path)
    assert result[0] == 'missing'


def test_operation_never_snapshots_an_unvalidated_requirements_part(accounting_packet, monkeypatch):
    case = accounting_packet
    policy = json.loads(case['policy'].read_bytes())
    policy['parts'][0]['path'] = '../outside.json'
    case['policy'].write_text(json.dumps(policy))
    original_open = Path.open
    def checked_open(path, *args, **kwargs):
        assert '..' not in path.parts, 'Unvalidated policy part was read'
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', checked_open)
    with pytest.raises(ValueError, match='requirements part'):
        _publish(case)
    assert not (case['output'] / 'publication/portable/index.json').exists()
