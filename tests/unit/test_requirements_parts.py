"""Split requirements remain the ordinary audit's flat semantic input."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion


def write(path, document):
    path.write_text(json.dumps(document, sort_keys=True, separators=(',', ':')), encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def policy():
    return {'contract': 'waapi-skill.branch-evidence-requirements/v1',
            'branches': {'a': {'categories': ['program']}, 'b': {'categories': ['native']}},
            'representative_mechanisms': {'one': {'candidate_sha256': 'old', 'detail': 'preserved'}}}


def split(path, document):
    parts = []
    for index, (branches, mechanisms) in enumerate(((document['branches'], {}), ({}, document.get('representative_mechanisms', {})))):
        part = {'contract': document['contract'], 'branches': branches, 'representative_mechanisms': mechanisms}
        name = f'part-{index}.json'
        parts.append({'path': name, 'sha256': write(path.parent / name, part)})
    value = {'contract': 'waapi-skill.branch-evidence-requirements-index/v1',
             'parts': parts, 'document_sha256': audit.digest(document)}
    write(path, value)
    return value


def test_index_loads_standard_parts_as_exact_flat_document(tmp_path):
    document = policy()
    flat, index = tmp_path / 'flat.json', tmp_path / 'requirements.json'
    write(flat, document)
    split(index, document)
    assert audit.load(index) == audit.load(flat) == document
    assert audit.digest(audit.load(index)) == audit.digest(document)


def identity_root(path):
    for folder in ('docs', 'tests/maintenance', 'skills/waapi-skill'):
        (path / folder).mkdir(parents=True)
    for name in ('branch-coverage-ownership.json', 'branch-coverage-condition-sources.json'):
        write(path / 'docs' / name, {})
    for name in ('branch_coverage_audit.py', 'branch_audit_completion.py'):
        (path / 'tests/maintenance' / name).write_text('# fixed source\n')
    (path / 'skills/waapi-skill/SKILL.md').write_text('fixed Skill')
    return path / 'docs/branch-coverage-requirements.json'


def test_candidate_identity_normalizes_assembled_self_attestations(tmp_path):
    path = identity_root(tmp_path)
    document = policy()
    write(path, document)
    inventory = {'sources': {}}
    flat = completion.candidate_identity(tmp_path, inventory, {}, digest=audit.digest)
    split(path, document)
    assert completion.candidate_identity(tmp_path, inventory, {}, digest=audit.digest) == flat
    document['representative_mechanisms']['one']['candidate_sha256'] = 'another stamp'
    split(path, document)
    assert completion.candidate_identity(tmp_path, inventory, {}, digest=audit.digest) == flat
    document['representative_mechanisms']['one']['detail'] = 'changed policy'
    split(path, document)
    assert completion.candidate_identity(tmp_path, inventory, {}, digest=audit.digest) != flat


@pytest.mark.parametrize('damage', ['missing', 'tamper', 'semantic', 'duplicate-path', 'duplicate-branch',
    'duplicate-mechanism', 'nested-index', 'part-schema', 'index-schema', 'descriptor-schema',
    'traversal', 'absolute', 'windows', 'backslash', 'symlink', 'duplicate-json-key'])
def test_index_rejects_invalid_or_unsealed_parts(tmp_path, damage):
    path = tmp_path / 'index.json'
    document = policy()
    index = split(path, document)
    part = tmp_path / index['parts'][0]['path']
    if damage == 'missing':
        part.unlink()
    elif damage == 'tamper':
        part.write_text('{}')
    elif damage == 'semantic':
        index['document_sha256'] = '0' * 64
    elif damage == 'duplicate-path':
        index['parts'].append(index['parts'][0])
    elif damage in ('duplicate-branch', 'duplicate-mechanism', 'nested-index', 'part-schema'):
        other = tmp_path / index['parts'][1]['path']
        value = json.loads(other.read_bytes())
        if damage == 'duplicate-branch':
            value['branches'] = document['branches']
        elif damage == 'duplicate-mechanism':
            first = json.loads(part.read_bytes())
            first['representative_mechanisms'] = document['representative_mechanisms']
            index['parts'][0]['sha256'] = write(part, first)
        elif damage == 'nested-index':
            value = index
        else:
            value['branches'] = []
        index['parts'][1]['sha256'] = write(other, value)
    elif damage == 'index-schema':
        index['extra'] = True
    elif damage == 'descriptor-schema':
        index['parts'][0]['extra'] = True
    elif damage in ('traversal', 'absolute', 'windows', 'backslash'):
        index['parts'][0]['path'] = {'traversal': '../part.json', 'absolute': str(part),
            'windows': 'C:part.json', 'backslash': '..\\part.json'}[damage]
    elif damage == 'symlink':
        outside = tmp_path.parent / (tmp_path.name + '-outside.json')
        outside.write_bytes(part.read_bytes())
        part.unlink()
        part.symlink_to(outside)
    else:
        part.write_text('{"contract":"waapi-skill.branch-evidence-requirements/v1","branches":{"a":{},"a":{}}}')
        index['parts'][0]['sha256'] = hashlib.sha256(part.read_bytes()).hexdigest()
    write(path, index)
    with pytest.raises((ValueError, OSError)):
        audit.load(path)


@pytest.mark.parametrize('bound,value', [('REQUIREMENTS_MAX_PARTS', 1),
    ('REQUIREMENTS_MAX_PART_BYTES', 8), ('REQUIREMENTS_MAX_TOTAL_BYTES', 8),
    ('REQUIREMENTS_MAX_INDEX_BYTES', 8)])
def test_index_enforces_packaged_resource_bounds(tmp_path, monkeypatch, bound, value):
    path = tmp_path / 'index.json'
    split(path, policy())
    monkeypatch.setattr(audit, bound, value)
    with pytest.raises(ValueError):
        audit.load(path)


def test_deterministic_writer_retains_complete_items_and_rejects_indivisible_item(tmp_path):
    document = policy()
    document['branches']['雪 space & shell'] = {'detail': 'x' * 220}
    document['representative_mechanisms']['one']['detail'] = 'y' * 180
    path = tmp_path / 'requirements.json'
    audit.write_requirements(path, document, max_part_bytes=400)
    first = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert audit.load(path) == document
    index = json.loads(path.read_bytes())
    assert len(index['parts']) > 1
    assert all((tmp_path / row['path']).stat().st_size <= 400 for row in index['parts'])
    audit.write_requirements(path, document, max_part_bytes=400)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == first
    oversized = deepcopy(document)
    oversized['representative_mechanisms']['one']['detail'] = 'z' * 1000
    with pytest.raises(ValueError, match='indivisible'):
        audit.write_requirements(tmp_path / 'rejected.json', oversized, max_part_bytes=400)
    assert not (tmp_path / 'rejected.json').exists()


def ordinary_case(tmp_path):
    root = tmp_path
    (root / 'docs').mkdir()
    route = '2025.1|wwise-console|2025.1.7.9143|function|ak.wwise.core.ping'
    identity = route + '|/resultSchema'
    document = {'contract': audit.REQUIREMENTS_CONTRACT, 'branches': {
        identity: {'native_shape_sha256': '1' * 64, 'categories': ['program', 'native']}}}
    bindings = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {identity: {
        'evidence': {'program': {'artifact': 'historical-locator.json', 'sha256': write(root / 'program.json', {})}}}}}
    def descriptor(name, value):
        return {'artifact': name, 'sha256': write(root / name, value)}
    origins = {'bindings': descriptor('original-bindings.json', bindings),
               'requirements': descriptor('original-requirements.json', document),
               'program': {'artifact': 'program.json', 'sha256': bindings['bindings'][identity]['evidence']['program']['sha256']},
               'capture': descriptor('capture.json', {})}
    projected = deepcopy(bindings)
    projected['bindings'][identity]['evidence']['program']['artifact'] = 'program.json'
    index = root / 'evidence-index.json'
    write(index, {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': [{
        'id': 'original', 'bindings': descriptor('projection.json', projected), 'origin': origins}]})
    inventory = {'routes': [], 'branches': [], 'summary': {}, 'native_coverage': {
        'candidate_sha256': 'candidate', 'catalogs': {},
        'routes': [{'id': route, 'uri': 'ak.wwise.core.ping', 'host': 'wwise-console', 'public_route': None}],
        'obligations': [{'id': identity, 'route': route, 'pointer': '/resultSchema',
            'kind': 'schema', 'shape_sha256': '1' * 64, 'owner_issue': 187}]}}
    return document, projected, index, inventory


def test_existing_portable_consumer_default_evaluator_and_cli_accept_index(tmp_path, monkeypatch, capsys):
    document, expected_bindings, binding_index, inventory = ordinary_case(tmp_path)
    path = tmp_path / 'docs/branch-coverage-requirements.json'
    write(path, document)
    monkeypatch.setattr(audit, 'ROOT', tmp_path)
    monkeypatch.setattr(audit, 'build_inventory', lambda: deepcopy(inventory))
    def consume():
        bindings, base, inputs = audit.portable_binding_inputs(binding_index, audit.load(path))
        assert bindings == expected_bindings
        evaluated = completion.evaluate_coverage(tmp_path, inventory, bindings, digest=audit.digest, evidence_base=base)
        assert evaluated['requirements_sha256'] == audit.digest(document)
        output = tmp_path / 'output.json'
        assert audit.main(['--output', str(output), '--binding-index', str(binding_index)]) == 0
        capsys.readouterr()
        persisted = audit.load(output)['native_coverage']
        assert persisted['requirements_sha256'] == audit.digest(document)
        assert persisted['completion']['complete'] is False
        assert persisted['completion']['states'] == {'missing_implementation': 1}
        return evaluated, persisted, inputs
    flat = consume()
    audit.write_requirements(path, document, max_part_bytes=500)
    assert consume() == flat
    # The real CLI fails closed before evaluating a damaged requirements input.
    part = tmp_path / 'docs' / json.loads(path.read_bytes())['parts'][0]['path']
    part.write_text('{}')
    assert audit.main(['--output', str(tmp_path / 'rejected.json'), '--binding-index', str(binding_index)]) == 1
    assert 'digest mismatch' in capsys.readouterr().out
    assert not (tmp_path / 'rejected.json').exists()


def test_metadata_collection_plan_reads_assembled_canonical_requirements(tmp_path, monkeypatch):
    from tests.maintenance import collect_class_metadata as collector
    baseline = collector.collection_plan('2021.1')
    current = audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json')
    (tmp_path / 'docs').mkdir()
    metadata = tmp_path / 'skills/waapi-skill/resources/metadata'
    metadata.parent.mkdir(parents=True)
    metadata.symlink_to(audit.ROOT / 'skills/waapi-skill/resources/metadata', target_is_directory=True)
    document = {'contract': audit.REQUIREMENTS_CONTRACT, 'branches': {
        identity: current['branches'][identity] for identity in baseline['eligible_branch_ids']}}
    audit.write_requirements(tmp_path / 'docs/branch-coverage-requirements.json', document)
    monkeypatch.setattr(collector, 'REPO', tmp_path)
    assert collector.collection_plan('2021.1') == baseline


def test_candidate_semantics_do_not_depend_on_format_without_mechanisms(tmp_path):
    path = identity_root(tmp_path)
    document = policy()
    document.pop('representative_mechanisms')
    write(path, document)
    flat = completion.candidate_identity(tmp_path, {'sources': {}}, {}, digest=audit.digest)
    audit.write_requirements(path, document)
    assert audit.load(path) == document
    assert completion.candidate_identity(tmp_path, {'sources': {}}, {}, digest=audit.digest) == flat


def test_loader_rejects_oversized_source_before_open_or_decode(tmp_path, monkeypatch):
    path = tmp_path / 'oversized.json'
    path.write_bytes(b'invalid JSON beyond bound')
    monkeypatch.setattr(audit, 'AUDIT_MAX_DOCUMENT_BYTES', 8, raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail('oversized source reached file open or JSON decoding')
    monkeypatch.setattr(Path, 'open', forbidden)
    monkeypatch.setattr(audit.json, 'loads', forbidden)
    with pytest.raises(ValueError, match='audit document byte bound exceeded'):
        audit.load(path)


def test_loader_bounded_read_rejects_growth_after_size_check(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path = tmp_path / 'grown.json'
    path.write_bytes(b'invalid JSON beyond bound')
    monkeypatch.setattr(audit, 'AUDIT_MAX_DOCUMENT_BYTES', 8, raising=False)
    original_stat = Path.stat
    monkeypatch.setattr(Path, 'stat', lambda self, **kwargs:
        SimpleNamespace(st_size=1) if self == path else original_stat(self, **kwargs))
    original_open = Path.open
    requests = []
    class BoundedStream:
        def __enter__(self):
            self.stream = original_open(path, 'rb')
            return self
        def __exit__(self, *args):
            self.stream.close()
        def read(self, size=-1):
            requests.append(size)
            assert size == 9
            return self.stream.read(size)
    monkeypatch.setattr(Path, 'open', lambda self, *args, **kwargs: BoundedStream())
    monkeypatch.setattr(audit.json, 'loads', lambda *args, **kwargs: pytest.fail('oversized read reached JSON decoding'))
    with pytest.raises(ValueError, match='audit document byte bound exceeded'):
        audit.load(path)
    assert requests == [9]


@pytest.mark.parametrize('contract', [audit.REQUIREMENTS_CONTRACT, 'waapi-skill.branch-audit/v2'])
def test_loader_keeps_legacy_flat_documents_above_index_ceiling(tmp_path, contract):
    document = {'contract': contract, 'branches': {
        'legacy': {'reason': 'x' * (audit.REQUIREMENTS_MAX_INDEX_BYTES + 1)}}}
    path = tmp_path / 'legacy-flat.json'
    write(path, document)
    assert path.stat().st_size > audit.REQUIREMENTS_MAX_INDEX_BYTES
    assert audit.load(path) == document
