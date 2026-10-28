"""The #185 component joins pinned native fields to closed public semantics."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json

import pytest

from tests.maintenance.branch_coverage_audit import digest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def component():
    from tests.maintenance.soundengine_branch_mapping import soundengine_component
    return soundengine_component(ROOT)


def test_soundengine_mapping_uses_percentage_and_exact_runtime_scope(component):
    from tests.maintenance.soundengine_branch_mapping import soundengine_bindings
    inventory = component
    bindings = soundengine_bindings(ROOT, inventory)
    prefix = '2025.1|wwise-authoring|2025.1.7.9143|function|ak.soundengine.seekOnEvent|'
    percent = bindings[prefix + '/argsSchema/properties/percent']
    assert percent['input']['correspondence']['public_fields'] == ['position_percent']
    assert percent['input']['correspondence']['encoding'] == 'position_percent / 100; exactly one of position_ms or position_percent'
    playing = bindings[prefix + '/argsSchema/properties/playingId']
    assert playing['input']['correspondence']['public_fields'] == ['playing_handle']
    assert 'Event' in playing['input']['correspondence']['encoding']
    assert percent['evidence'] == {}
    assert percent['public_route_sha256'] == digest(next(row for row in inventory['routes']
        if row['id'] == percent['public_route']))
    spatial_prefix = prefix.replace('seekOnEvent', 'setMultiplePositions')
    top_z = bindings[spatial_prefix + '/argsSchema/properties/positions/items/properties/position/properties/orientationTop/properties/z']
    assert top_z['input']['correspondence']['value_paths'] == ['position_frames[*][8]']


def reviewed_attachment(inventory):
    from tests.maintenance.soundengine_branch_mapping import soundengine_bindings
    bindings = soundengine_bindings(ROOT, inventory)
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    for mechanism in sorted({binding['representative_mechanism'] for binding in bindings.values()}):
        members = {identity: binding for identity, binding in bindings.items() if binding['representative_mechanism'] == mechanism}
        for identity in members:
            requirements['branches'][identity] = {'native_shape_sha256': rows[identity]['shape_sha256'],
                'categories': ['program'], 'reason': 'Controlled source mapping validation; no execution credit',
                'representative_mechanism': mechanism}
        sources = {binding[key]['source'].partition('#')[0] for binding in members.values()
            for key in ('construction', 'validation', 'verifier')}
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'reviewed_reason': 'Exact controlled mapping review; no selected receipt supplied',
            'sources': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
            'members': {identity: {'native_route': rows[identity]['route'], 'native_shape_sha256': rows[identity]['shape_sha256'],
                'mapping_sha256': digest({key: value for key, value in binding.items() if key != 'evidence'})} for identity, binding in members.items()},
            'selected_proofs': {'program': [next(iter(members))]}}
    return requirements, {'contract': 'waapi-skill.branch-mapping-attachment/v1', 'scope_kind': 'product',
        'requirements_sha256': digest(requirements), 'mechanisms': list(requirements['representative_mechanisms']),
        'bindings': bindings, 'predecessors': dict.fromkeys(bindings)}


def test_soundengine_mapping_retains_five_versions_and_reachable_definitions(component):
    from collections import Counter
    native = component['native_coverage']
    assert len(native['routes']) == 248
    assert len(native['obligations']) == 15050
    assert Counter(row['version'] for row in native['routes']) == {'2021.1': 44, '2022.1': 48, '2023.1': 52, '2024.1': 52, '2025.1': 52}
    references = [row for row in native['obligations'] if row['kind'] == 'reference']
    identities = {row['id'] for row in native['obligations']}
    assert all(row['reference']['target'] in identities for row in references)


@pytest.mark.parametrize('damage', ['missing-choice', 'wrong-choice', 'missing-version'])
def test_soundengine_component_rejects_native_choice_and_version_drift(component, monkeypatch, damage):
    import tests.maintenance.soundengine_branch_mapping as mapping
    changed = deepcopy(component['native_coverage'])
    if damage == 'missing-version':
        changed['obligations'] = [row for row in changed['obligations'] if not row['id'].startswith('2021.1|')]
    else:
        row = next(row for row in changed['obligations'] if row['kind'] == 'enum_value')
        if damage == 'missing-choice':
            changed['obligations'].remove(row)
        else:
            row['shape_sha256'] = '0' * 64
    monkeypatch.setattr(mapping, 'discover_soundengine', lambda root: changed)
    with pytest.raises(ValueError, match='field/choice/version'):
        mapping.soundengine_component(ROOT)


def test_soundengine_mapping_rejects_an_unknown_native_argument(component):
    from tests.maintenance.soundengine_branch_mapping import soundengine_bindings
    changed = deepcopy(component)
    row = deepcopy(next(row for row in changed['native_coverage']['obligations'] if row['pointer'] == '/argsSchema/properties/actionType'))
    row['id'] = row['route'] + '|/argsSchema/properties/newUnreviewedValue'
    row['pointer'] = '/argsSchema/properties/newUnreviewedValue'
    changed['native_coverage']['obligations'].append(row)
    with pytest.raises(ValueError, match='native argument field'):
        soundengine_bindings(ROOT, changed)


def test_soundengine_attachment_uses_existing_reader_without_fabricating_receipts(component):
    from tests.maintenance.branch_audit_mapping import read_mapping_attachments
    requirements, attachment = reviewed_attachment(component)
    reviewed = read_mapping_attachments([{}], requirements, lambda _: attachment, ROOT)
    assert set(reviewed['bindings']) == set(attachment['bindings'])
    assert all(binding['evidence'] == {} for binding in reviewed['bindings'].values())


@pytest.mark.parametrize('damage', ['missing-choice', 'missing-source', 'stale-source'])
def test_soundengine_attachment_rejects_missing_mapping_or_source(component, damage):
    from tests.maintenance.branch_audit_mapping import read_mapping_attachments
    requirements, attachment = reviewed_attachment(component)
    review = next(iter(requirements['representative_mechanisms'].values()))
    if damage == 'missing-choice':
        attachment['bindings'].pop(next(iter(review['members'])))
    elif damage == 'missing-source':
        review['sources'].pop(next(iter(review['sources'])))
    else:
        review['sources'][next(iter(review['sources']))] = '0' * 64
    attachment['requirements_sha256'] = digest(requirements)
    with pytest.raises(ValueError):
        read_mapping_attachments([{}], requirements, lambda _: attachment, ROOT)


def test_soundengine_export_rejects_an_unfinalized_code_anchor(tmp_path):
    from tests.maintenance.soundengine_branch_mapping import soundengine_export
    run = tmp_path / 'run'
    run.mkdir()
    for filename in ('run.plan.json', 'run.result.json', 'run.summary.json'):
        (run / filename).write_text(json.dumps({}))
    with pytest.raises(ValueError, match='anchor is missing or unfinalized'):
        soundengine_export(ROOT, tmp_path / 'out', run)
