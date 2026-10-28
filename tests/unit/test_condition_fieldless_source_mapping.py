"""Fieldless source declarations retain accounting without inventing mutations."""
from pathlib import Path
from copy import deepcopy
import base64
import gzip
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET

import pytest

from tests.maintenance.map_condition_completion import main
from tests.maintenance.branch_coverage_audit import portable_binding_inputs
from tests.maintenance.branch_coverage_audit import digest
from tests.maintenance.branch_audit_completion import evaluate_coverage
from tests.support.condition_completion_mapping import (
    definition_mapping, validate_mapping_attachment, mapping_evidence_result)


ROOT = Path(__file__).parents[2]


@pytest.fixture(scope='module')
def successor(tmp_path_factory):
    destination = tmp_path_factory.mktemp('fieldless-successor') / 'export'
    assert main(['--output-directory', str(destination)]) == 0
    return destination


def test_successor_export_resolves_only_structural_groups_through_the_reader(successor):
    destination = successor
    assessment = json.loads((destination / 'assessment.json').read_bytes())
    assert assessment['completion']['states'] == {
        'implementation_dependency': 15, 'approved_exclusion': 240, 'source_definition_verified': 7042}
    assert assessment['completion']['complete'] is False
    requirements = json.loads((destination / 'requirements.json').read_bytes())
    imported, base, _ = portable_binding_inputs(destination / 'evidence-index.json', requirements)
    assert base == destination
    original = json.loads((ROOT / 'tests/fixtures/branch-evidence/product/'
                           'condition-definitions-195-r1/mapping.json').read_bytes())
    expected = {m['id']: m['shape_sha256'] for row in original['occurrences']
                if row['dependency_kind'] == 'fieldless' for m in row['members']}
    resolved = {row['id']: row for row in assessment['obligations'] if row['id'] in expected}
    assert len(expected) == len(resolved) == 30
    for identity, row in resolved.items():
        assert row['shape_sha256'] == expected[identity]
        assert row['state'] == 'source_definition_verified'
        assert row['requirements'] == ['program']
        assert row['metadata_scope'] == 'source_definition'
        assert row['direct_recipient_native_effect'] == 'not_observed'
        binding = imported['bindings'][identity]
        assert set(binding['evidence']) == {'program'}
        assert 'public_mechanism' not in binding
        assert binding['source_structure']['declared_fields'] == []
        assert binding['source_structure']['native_absence_claim'] is False
    assert {row['id']: row['shape_sha256'] for row in assessment['obligations']} == {
        m['id']: m['shape_sha256'] for row in original['occurrences'] for m in row['members']}
    assert {row['id'] for row in assessment['obligations']
            if row['state'] == 'implementation_dependency'} == {
        m['id'] for row in original['occurrences']
        if row['dependency_kind'] == 'music' for m in row['members']}
    mapping = json.loads((destination / 'mapping.json').read_bytes())
    # The Audio override occurrence and every other row stay byte-for-data equal.
    assert {row['occurrence_id']: row for row in mapping['occurrences']
            if 'source_structure' not in row and 'approved_exclusion' not in row} == {
        row['occurrence_id']: row for row in original['occurrences']
        if row['dependency_kind'] not in {'fieldless', 'batch'}}


@pytest.mark.parametrize('damage', ['owned-field', 'inherited-field', 'list', 'identity',
                                   'source', 'controller', 'peer', 'member', 'version'])
def test_structural_mapping_rejects_changed_mapping_facts(successor, damage):
    attachment = json.loads((successor / 'evidence-index.json').read_bytes())['condition_definition_attachments'][0]
    mapping = json.loads((successor / 'mapping.json').read_bytes())
    row = next(r for r in mapping['occurrences'] if 'source_structure' in r)
    if damage == 'owned-field': row['source_fields'].append({'name': 'AddedField'})
    elif damage == 'inherited-field': row['source_structure']['inherited_fields'].append('AddedField')
    elif damage == 'list': row['source_structure']['object_lists'].append('AddedList')
    elif damage == 'identity': row['consumers'][0]['catalog']['classId'] = 1
    elif damage == 'source': row['source_file_sha256'] = '0' * 64
    elif damage == 'controller': row['consumers'][0]['controller']['type'] = 'int16'
    elif damage == 'peer': row['source_structure']['peer_occurrence_id'] = 'unmapped'
    elif damage == 'member': row['members'].pop()
    else: row['version'] = '2025.1'
    with pytest.raises(ValueError, match='exact source definition'):
        validate_mapping_attachment(attachment, successor, ROOT, selected_mapping=mapping)


@pytest.mark.parametrize('damage', ['owned-field', 'inherited-base', 'list', 'controller', 'peer'])
def test_structural_mapping_rejects_changed_complete_source(tmp_path, damage):
    from tests.support.condition_completion_mapping import FIELDLESS_REVIEW_PATH
    review = json.loads((ROOT / FIELDLESS_REVIEW_PATH).read_bytes())
    for name in (FIELDLESS_REVIEW_PATH, review['original_mapping']['path'], review['source_snapshot']['path']):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    snapshot_path = tmp_path / review['source_snapshot']['path']
    snapshot = json.loads(gzip.decompress(snapshot_path.read_bytes()))
    entry = snapshot['files']['2025.1.7.9143|condition|WObjects/WObjects.xml']
    source = ET.fromstring(base64.b64decode(entry['bytes_base64']))
    group = source.find("./ObjectBase[@Name='PositioningType_AudioNode']")
    if damage == 'owned-field':
        ET.SubElement(ET.SubElement(group, 'Properties'), 'Property', Name='AddedField', Type='bool')
    elif damage == 'inherited-base': ET.SubElement(group, 'ObjectBaseRef', Name='ListenerRelativePositioning')
    elif damage == 'list': ET.SubElement(ET.SubElement(group, 'ObjectLists'), 'ObjectList', Name='AddedList')
    elif damage == 'controller': group.find('./Dependencies/PropertyDependency').set('Name', 'OtherController')
    else: source.find("./ObjectBase[@Name='ListenerRelativePositioning']").remove(
        source.find("./ObjectBase[@Name='ListenerRelativePositioning']/Properties"))
    changed = ET.tostring(source)
    entry.update(bytes_base64=base64.b64encode(changed).decode(), sha256=hashlib.sha256(changed).hexdigest())
    snapshot_path.write_bytes(gzip.compress(json.dumps(snapshot).encode(), mtime=0))
    with pytest.raises(ValueError, match='fieldless source structure input differs: source_snapshot'):
        definition_mapping(tmp_path)


def test_structural_definition_does_not_supply_native_or_recipient_evidence(successor):
    attachment = json.loads((successor / 'evidence-index.json').read_bytes())['condition_definition_attachments'][0]
    context = validate_mapping_attachment(attachment, successor, ROOT)
    row = next(r for r in context['mapping']['occurrences'] if 'source_structure' in r)
    identity = row['members'][0]['id']
    binding = json.loads((successor / 'bindings.json').read_bytes())['bindings'][identity]
    for category in ('native', 'live_metadata'):
        outcome, reason = mapping_evidence_result(attachment, context['branches'][identity], category,
            'product', successor, binding, ROOT, context=context)
        assert outcome == 'missing'
        assert 'no native or recipient metadata evidence' in reason


@pytest.mark.parametrize('structural', [False, True])
def test_program_only_requirement_cannot_move_between_evidence_scopes(successor, structural):
    attachment = json.loads((successor / 'evidence-index.json').read_bytes())['condition_definition_attachments'][0]
    context = validate_mapping_attachment(attachment, successor, ROOT)
    row = next(r for r in context['mapping']['occurrences']
               if ('source_structure' in r) == structural and not r['dependencies']
               and 'approved_exclusion' not in r)
    identity = row['members'][0]['id']
    branch = deepcopy(context['branches'][identity])
    requirements = json.loads((successor / 'requirements.json').read_bytes())
    policy = requirements['branches'][identity]
    policy['categories'] = ['program', 'native'] if structural else ['program']
    bindings = json.loads((successor / 'bindings.json').read_bytes())
    bindings['bindings'] = {identity: bindings['bindings'][identity]}
    result = evaluate_coverage(ROOT, {'routes': [], 'native_coverage': {
        'candidate_sha256': 'c' * 64, 'catalogs': {}, 'routes': [], 'obligations': [branch]}},
        bindings, digest=digest, evidence_base=successor, requirements_document={
            'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {identity: policy}})
    assert result['obligations'][0]['state'] == 'unresolved'
