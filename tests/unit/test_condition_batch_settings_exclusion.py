"""A user scope decision excludes only internal Batch Rename window settings."""
from pathlib import Path
from copy import deepcopy
import json
import shutil

import pytest

from tests.support.condition_completion_mapping import (
    definition_mapping, validate_mapping_attachment, mapping_evidence_result)
from tests.maintenance.map_condition_completion import main
from tests.maintenance.branch_coverage_audit import portable_binding_inputs, digest
from tests.maintenance.branch_audit_completion import evaluate_coverage


ROOT = Path(__file__).parents[2]
AUTHORITY = ('docs/plans/full-waapi-coverage/SPEC.md#'
             'user-approved-batch-rename-window-boundary--2026-10-28')


def test_only_the_exact_window_configuration_members_receive_the_exclusion():
    mapping = definition_mapping(ROOT)
    original = json.loads((ROOT / 'tests/fixtures/branch-evidence/product/'
                           'condition-definitions-195-r1/mapping.json').read_bytes())
    expected = {m['id']: m['shape_sha256'] for row in original['occurrences']
                if row['dependency_kind'] == 'batch' for m in row['members']}
    excluded = [row for row in mapping['occurrences'] if 'approved_exclusion' in row]
    assert {m['id']: m['shape_sha256'] for row in excluded for m in row['members']} == expected
    assert len(expected) == 240
    for row in excluded:
        assert row['approved_exclusion']['authority'] == AUTHORITY
        assert row['approved_exclusion']['execution_credit'] is False
        assert row['approved_exclusion']['native_absence_claim'] is False
        assert row['source_parent']['catalog']['classId'] == 3342352
        assert row['consumers'][0]['catalog'] == {
            'classId': 65011712, 'name': 'BatchRenameSettings', 'type': 'Inner'}


@pytest.fixture(scope='module')
def successor(tmp_path_factory):
    destination = tmp_path_factory.mktemp('batch-successor') / 'export'
    assert main(['--output-directory', str(destination)]) == 0
    return destination


def test_combined_successor_preserves_three_separate_dispositions(successor):
    requirements = json.loads((successor / 'requirements.json').read_bytes())
    imported, base, _ = portable_binding_inputs(successor / 'evidence-index.json', requirements)
    assert base == successor
    result = json.loads((successor / 'assessment.json').read_bytes())
    assert result['completion']['states'] == {
        'source_definition_verified': 7042, 'approved_exclusion': 240, 'implementation_dependency': 15}
    assert result['completion']['complete'] is False
    original = json.loads((ROOT / 'tests/fixtures/branch-evidence/product/'
                           'condition-definitions-195-r1/mapping.json').read_bytes())
    assert {r['id']: r['shape_sha256'] for r in result['obligations']} == {
        m['id']: m['shape_sha256'] for r in original['occurrences'] for m in r['members']}
    assert {r['id'] for r in result['obligations'] if r['state'] == 'implementation_dependency'} == {
        m['id'] for r in original['occurrences'] if r['dependency_kind'] == 'music' for m in r['members']}
    for row in result['obligations']:
        if row['state'] != 'approved_exclusion':
            continue
        identity = row['id']
        assert row['exclusion']['authority'] == AUTHORITY
        assert row['exclusion']['execution_credit'] is False
        assert row['exclusion']['native_absence_claim'] is False
        assert row['direct_recipient_native_effect'] == 'not_observed'
        assert row['requirements'] == requirements['branches'][identity]['categories'] == []
        binding = imported['bindings'][identity]
        assert binding['evidence'] == {}
        assert 'public_mechanism' not in binding


@pytest.mark.parametrize('kind', ['ordinary-field', 'music-inner'])
def test_non_batch_members_cannot_borrow_the_window_exclusion(successor, kind):
    attachment = json.loads((successor / 'evidence-index.json').read_bytes())['condition_definition_attachments'][0]
    context = validate_mapping_attachment(attachment, successor, ROOT)
    exclusion = next(r['approved_exclusion'] for r in context['mapping']['occurrences']
                     if 'approved_exclusion' in r)
    row = next(r for r in context['mapping']['occurrences'] if
        (r['dependency_kind'] == 'music' if kind == 'music-inner' else
         r['version'] == '2025.1' and r['source_pointer'].endswith('Property[BaseFrequency]/Dependencies')))
    identity = row['members'][0]['id']
    requirements = json.loads((successor / 'requirements.json').read_bytes())
    policy = requirements['branches'][identity]
    policy.update(categories=[], approved_exclusion=deepcopy(exclusion))
    bindings = json.loads((successor / 'bindings.json').read_bytes())
    binding = bindings['bindings'][identity]
    binding.update(evidence={}, approved_exclusion=deepcopy(exclusion))
    bindings['bindings'] = {identity: binding}
    result = evaluate_coverage(ROOT, {'routes': [], 'native_coverage': {
        'candidate_sha256': 'c' * 64, 'catalogs': {}, 'routes': [],
        'obligations': [deepcopy(context['branches'][identity])]}}, bindings, digest=digest,
        evidence_base=successor, requirements_document={
            'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {identity: policy}})
    assert result['obligations'][0]['state'] == 'unresolved'


@pytest.mark.parametrize('damage', ['class', 'parent', 'decision', 'native-absence', 'member'])
def test_exclusion_receipt_cannot_change_its_exact_approved_scope(successor, damage):
    attachment = json.loads((successor / 'evidence-index.json').read_bytes())['condition_definition_attachments'][0]
    mapping = json.loads((successor / 'mapping.json').read_bytes())
    row = next(r for r in mapping['occurrences'] if 'approved_exclusion' in r)
    if damage == 'class': row['consumers'][0]['catalog']['classId'] = 1
    elif damage == 'parent': row['source_parent']['catalog']['classId'] = 1
    elif damage == 'decision': row['approved_exclusion']['authority'] = 'unapproved'
    elif damage == 'native-absence': row['approved_exclusion']['native_absence_claim'] = True
    else: row['members'].pop()
    with pytest.raises(ValueError, match='exact source definition'):
        validate_mapping_attachment(attachment, successor, ROOT, selected_mapping=mapping)


@pytest.mark.parametrize('damage', ['missing', 'changed'])
def test_exclusion_requires_the_recorded_user_decision(tmp_path, damage):
    from tests.support.condition_completion_mapping import FIELDLESS_REVIEW_PATH, BATCH_EXCLUSION_REVIEW_PATH
    review = json.loads((ROOT / FIELDLESS_REVIEW_PATH).read_bytes())
    for name in (FIELDLESS_REVIEW_PATH, BATCH_EXCLUSION_REVIEW_PATH, review['original_mapping']['path'],
                 review['source_snapshot']['path'], 'docs/plans/full-waapi-coverage/SPEC.md'):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    path = tmp_path / 'docs/plans/full-waapi-coverage/SPEC.md'
    content = path.read_text()
    if damage == 'missing': content = content.split('## User-approved Batch Rename window boundary', 1)[0]
    else: content = content.replace('The user explicitly excludes configuration', 'The user includes configuration')
    path.write_text(content)
    with pytest.raises(ValueError, match='window exclusion decision'):
        definition_mapping(tmp_path)


def test_exclusion_does_not_supply_execution_or_metadata_evidence(successor):
    attachment = json.loads((successor / 'evidence-index.json').read_bytes())['condition_definition_attachments'][0]
    context = validate_mapping_attachment(attachment, successor, ROOT)
    row = next(r for r in context['mapping']['occurrences'] if 'approved_exclusion' in r)
    identity = row['members'][0]['id']
    binding = json.loads((successor / 'bindings.json').read_bytes())['bindings'][identity]
    for category in ('program', 'native', 'live_metadata'):
        outcome, _ = mapping_evidence_result(attachment, context['branches'][identity], category,
            'product', successor, binding, ROOT, context=context)
        assert outcome == 'missing'
