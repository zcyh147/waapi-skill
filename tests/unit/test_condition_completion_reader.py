"""Shared source proof cannot fabricate current executions or metadata facts."""
from copy import deepcopy
from pathlib import Path
import json
import gzip
import base64
import shutil

import pytest

from tests.maintenance.branch_audit_completion import evidence_result
from tests.maintenance.branch_coverage_audit import digest, load
from tests.support.condition_completion_mapping import (definition_mapping, export_mapping,
    validate_mapping_attachment, mapping_evidence_result)

ROOT = Path(__file__).parents[2]


def test_current_class_route_rejects_a_generic_catalog_alias():
    from tests.support.condition_completion_mapping import _validate_current_program, REVIEW_PATH, PROOF_PATH
    review = json.loads((ROOT / REVIEW_PATH).read_bytes())
    files = json.loads(gzip.decompress((ROOT / PROOF_PATH).read_bytes()))
    current = json.loads(base64.b64decode(files['current-program.json']['bytes_base64']))
    current['observations']['SourcePlugin']['class_catalog']['type'] = 'WObject'
    with pytest.raises(ValueError, match='class-route'):
        _validate_current_program(current, review, ROOT, 'product')


def test_changed_original_witness_is_rejected_even_after_a_cached_read(tmp_path):
    from tests.support.condition_completion_mapping import _proofs, _review, PROOF_PATH, REVIEW_SHA256
    _copy_review_inputs(tmp_path)
    _proofs(str(tmp_path), REVIEW_SHA256)
    archive = tmp_path / PROOF_PATH
    archive.write_bytes(archive.read_bytes() + b'changed-original-witness')
    with pytest.raises(ValueError, match='Original condition proof archive changed'):
        _review(tmp_path)


def test_actual_class_receipt_must_match_the_source_graph(bundle):
    from tests.support.condition_completion_mapping import _class_metadata
    base, exported = bundle
    context = validate_mapping_attachment(exported['attachment'], base, ROOT)
    row = deepcopy(next(r for r in context['mapping']['occurrences']
        if r['version'] == '2025.1' and 'Property[LfoSmoothing]/Dependencies' in r['source_pointer']))
    row['predicate']['values'] = [0]
    with pytest.raises(ValueError, match='class metadata.*graph'):
        _class_metadata(row, context)


def test_complete_source_subset_keeps_dependencies_and_deduplicates_witnesses(bundle):
    from collections import Counter
    from tests.maintenance.branch_audit_completion import evaluate_coverage
    base, exported = bundle
    context = validate_mapping_attachment(exported['attachment'], base, ROOT)
    policies = {i: exported['requirements']['branches'][i] for i in context['branches']}
    inventory = {'routes': [], 'native_coverage': {'candidate_sha256': 'c' * 64, 'catalogs': {},
        'routes': [], 'obligations': list(context['branches'].values())}}
    result = evaluate_coverage(ROOT, inventory, exported['bindings'], digest=digest, evidence_base=base,
        requirements_document={'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': policies})
    assert result['completion']['states'] == {
        'approved_exclusion': 255, 'source_definition_verified': 7042}
    assert result['completion']['complete'] is True
    assert Counter(b['metadata_scope'] for b in result['obligations']) == {'source_definition': 7243, 'object_type': 54}
    proofs = result['condition_source_definition_reuse']
    assert proofs['new_native_runs'] == 0
    ids = [p['original_proof_id'] for p in proofs['original_native_witness_proofs']]
    assert len(ids) == len(set(ids)) == 7
    previous = load(ROOT / 'docs/branch-coverage-requirements.json')['branches']
    assert all(exported['requirements']['branches'][i] == policy for i, policy in previous.items() if i not in context['branches'])


def test_same_portable_reader_imports_full_source_scope_without_other_row_loss(bundle, tmp_path):
    from tests.maintenance.branch_coverage_audit import portable_binding_inputs
    from tests.support.condition_completion_mapping import attach_definition_mappings
    base, exported = bundle
    path = base / 'index.json'
    path.write_text(json.dumps({'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': [],
        'condition_definition_attachments': [exported['attachment']]}))
    imported, actual_base, assessment = portable_binding_inputs(path, exported['requirements'])
    assert imported == exported['bindings'] and actual_base == base
    assert assessment['condition_source_definitions']['exact_source_members'] == 7297
    for descriptors, existing in (([exported['attachment']] * 2, {}),
            ([exported['attachment']], {next(iter(imported['bindings'])): {'original': 'retain'}})):
        before = deepcopy(existing)
        with pytest.raises(ValueError):
            attach_definition_mappings(descriptors, existing, base, ROOT)
        assert existing == before


@pytest.mark.parametrize('damage', ['controlled', 'instance', 'dropped-refresh', 'null-uri'])
def test_current_shared_guard_proof_cannot_be_promoted_or_weakened(damage):
    from tests.support.condition_completion_mapping import _validate_current_program, REVIEW_PATH, PROOF_PATH
    review = json.loads((ROOT / REVIEW_PATH).read_bytes())
    files = json.loads(gzip.decompress((ROOT / PROOF_PATH).read_bytes()))
    current = json.loads(base64.b64decode(files['current-program.json']['bytes_base64']))
    if damage == 'controlled': current['scope_kind'] = 'controlled'
    elif damage == 'instance': current['direct_recipient_instance_metadata'] = 'observed'
    elif damage == 'null-uri': current['observations']['SourcePlugin']['object_scope_call_trace'][0]['uri'] = None
    else:
        flow = current['observations']['SourcePlugin']
        flow['object_scope_call_trace'] = [c for c in flow['object_scope_call_trace'] if not c['uri'].endswith('getPropertyInfo')]
    with pytest.raises(ValueError):
        _validate_current_program(current, review, ROOT, 'product')


@pytest.fixture(scope='module')
def bundle(tmp_path_factory):
    base = tmp_path_factory.mktemp('condition-full-map')
    return base, export_mapping(ROOT, base)


def test_source_definition_reuse_is_not_observed_class_metadata(bundle):
    base, exported = bundle
    context = validate_mapping_attachment(exported['attachment'], base, ROOT)
    identity = next(i for i, row in context['members'].items()
                    if row['version'] == '2025.1' and row['source_pointer'].endswith('Property[BaseFrequency]/Dependencies'))
    branch = context['branches'][identity]
    binding = exported['bindings']['bindings'][identity]
    result = evidence_result(binding['evidence']['program'], branch, 'c' * 64, 'program', 'product', base, binding, ROOT)
    assert result[0] == 'reviewed_source_definition_and_public_mechanism'
    assert mapping_evidence_result(binding['evidence']['live_metadata'], branch, 'live_metadata', 'product', base, binding, ROOT)[0] == 'missing'


@pytest.mark.parametrize('damage', ['type', 'literal', 'context', 'action', 'version', 'class', 'controller', 'source', 'omitted', 'owner'])
def test_source_mapping_changes_cannot_borrow_a_recipe(bundle, tmp_path, damage):
    base, exported = bundle
    mapping = deepcopy(exported['mapping'])
    row = next(r for r in mapping['occurrences'] if r['version'] == '2025.1' and r['predicate'] is not None)
    if damage == 'type': row['predicate']['type'] = 'string'
    elif damage == 'literal': row['predicate']['values'] = ['invented']
    elif damage == 'context': row['source_attributes']['Context'] = 'Parent'
    elif damage == 'action': row['source_attributes']['Action'] = 'Show'
    elif damage == 'version': row['version'] = '2021.1'
    elif damage == 'class': row['consumers'][0]['catalog']['classId'] = 1
    elif damage == 'controller': row['source_attributes']['Name'] = 'invented'
    elif damage == 'source': row['source_file_sha256'] = '0' * 64
    elif damage == 'omitted': row['members'].pop()
    else: mapping['owner_issue'] = 195
    with pytest.raises(ValueError, match='exact source definition'):
        validate_mapping_attachment(exported['attachment'], base, ROOT, selected_mapping=mapping)


def test_reconciled_sources_retain_original_program_authority(bundle):
    """The portable attachment keeps original proof while admitting reviewed source changes."""
    base, exported = bundle
    context = validate_mapping_attachment(exported['attachment'], base, ROOT)
    current_program = json.loads(context['files']['current-program.json'])
    source = 'skills/waapi-skill/wwise_waapi/operation_registry.py'
    assert context['review']['current_sources'][source] == current_program['sources'][source]
    assert context['review']['current_sources'][source] == '2d8c26f100194adc7081c27aa04d8207c654f420c6a77e1bb29206a2c5e53023'
    assert len(context['members']) == 7297
    assert sum(len(row['members']) for row in context['mapping']['occurrences'] if row['dependencies']) == 0
    assert context['review']['source_definition_policy']['new_native_runs'] == 0


def _copy_review_inputs(destination):
    from tests.support.condition_completion_mapping import (
        REVIEW_PATH, PROOF_PATH, SOURCE_RECONCILIATION_PATH)
    review = json.loads((ROOT / REVIEW_PATH).read_bytes())
    successor = json.loads((ROOT / SOURCE_RECONCILIATION_PATH).read_bytes())
    names = {REVIEW_PATH, PROOF_PATH, SOURCE_RECONCILIATION_PATH,
        'docs/branch-coverage-condition-sources.json',
        'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz',
        *review['current_sources'], *successor['source_additions']}
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)


@pytest.mark.parametrize('damage, error', [
    ('current', 'Reviewed current public condition mechanism source changed'),
    ('original', 'Exact reviewed condition completion proof differs'),
    ('added-resource', 'Reviewed current public condition mechanism source changed'),
    ('added-python', 'Reviewed current public condition mechanism source changed'),
    ('reconciliation', 'Exact condition source reconciliation differs'),
])
def test_condition_source_successor_rejects_changed_inputs(tmp_path, damage, error):
    from tests.support.condition_completion_mapping import REVIEW_PATH, SOURCE_RECONCILIATION_PATH
    root = tmp_path / 'isolated-root'
    _copy_review_inputs(root)
    names = {
        'current': 'skills/waapi-skill/wwise_waapi/operation_registry.py',
        'original': REVIEW_PATH,
        'added-resource': 'skills/waapi-skill/resources/metadata/reference-master-sink-capabilities.json',
        'added-python': 'skills/waapi-skill/wwise_waapi/control_surface_construction.py',
        'reconciliation': SOURCE_RECONCILIATION_PATH,
    }
    target = root / names[damage]
    target.write_bytes(target.read_bytes() + b'changed-evidence')
    with pytest.raises(ValueError, match=error):
        export_mapping(root, tmp_path / 'rejected-export')
