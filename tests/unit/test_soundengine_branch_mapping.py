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
    assert percent['public_route_sha256'] == digest(next(row for row in inventory['routes']
        if row['id'] == percent['public_route']))
    spatial_prefix = prefix.replace('seekOnEvent', 'setMultiplePositions')
    top_z = bindings[spatial_prefix + '/argsSchema/properties/positions/items/properties/position/properties/orientationTop/properties/z']
    assert top_z['input']['correspondence']['value_paths'] == ['position_frames[*][8]']

def test_soundengine_mapping_retains_five_versions_and_reachable_definitions(component):
    from collections import Counter
    native = component['native']
    assert len(native['routes']) == 248
    assert len(native['parameters']) == 15050
    assert Counter(row['version'] for row in native['routes']) == {'2021.1': 44, '2022.1': 48, '2023.1': 52, '2024.1': 52, '2025.1': 52}
    references = [row for row in native['parameters'] if row['kind'] == 'reference']
    identities = {row['id'] for row in native['parameters']}
    assert all(row['reference']['target'] in identities for row in references)

def test_soundengine_getter_maps_forwarded_scope_and_exact_declared_spelling(component):
    from tests.maintenance.soundengine_branch_mapping import soundengine_bindings
    bindings = soundengine_bindings(ROOT, component)
    native = next(row for row in component['native']['parameters'] if row.get('value') == 'suppportsRandomizer'
        and row['id'].startswith('2025.1|wwise-authoring|') and '|ak.soundengine.getState|' in row['id'])
    spelling = bindings[native['id']]['input']['correspondence']
    assert spelling['public_choices'] == ['suppportsRandomizer']
    assert spelling['native_choice'] == 'suppportsRandomizer'
    platform = next(binding for identity, binding in bindings.items() if '|ak.soundengine.getState|' in identity
        and identity.startswith('2025.1|wwise-authoring|') and identity.endswith('/definitions/objectReturnOptions/properties/platform'))
    assert platform['input']['correspondence']['public_fields'] == ['platform']
    assert platform['input']['correspondence']['rule'] == 'forwarded_closed_getter_return_options'

@pytest.mark.parametrize('version', ('2022.1', '2023.1', '2024.1', '2025.1'))
def test_get_switch_mapping_separates_required_present_and_native_omission(component, version):
    from tests.maintenance.soundengine_branch_mapping import soundengine_bindings
    bindings = soundengine_bindings(ROOT, component)
    native = next(row for row in component['native']['routes']
        if row['version'] == version and row['host'] == 'wwise-authoring' and row['uri'] == 'ak.soundengine.getSwitch')
    identity = native['id'] + '|/argsSchema/properties/gameObject'
    root = bindings[identity]['input']['correspondence']
    assert root['game_object_scope']['required'] is (version == '2022.1')
    assert root['game_object_scope']['present'] == 'active_context_bound_runtime_generation'
    assert root['game_object_scope']['absent'] == ('rejected_required_field' if version == '2022.1' else 'native_argument_omitted')
    assert root['game_object_scope']['native_default'] == ('AK_INVALID_GAME_OBJECT' if version == '2025.1' else 'not_stated_by_pinned_schema')
    assert root['game_object_scope']['setter_omission_equivalence'] == 'not_claimed'
    if version == '2022.1':
        assert identity + '/@presence/absent' not in bindings
    else:
        absent = bindings[identity + '/@presence/absent']['input']['correspondence']
        present = bindings[identity + '/@presence/present']['input']['correspondence']
        assert absent['game_object_scope']['selected_native_presence'] == 'omitted'
        assert present['game_object_scope']['selected_native_presence'] == 'present_bound_generation'

def test_soundengine_string_nodes_map_compilers_constraints_and_input_rejection(component):
    from tests.maintenance.soundengine_branch_mapping import soundengine_bindings, soundengine_gaps
    bindings = soundengine_bindings(ROOT, component)
    rows = [row for row in component['native']['parameters']
        if '/optionsSchema/@definition/waapi_definitions.json/definitions/returnExpression/items/anyOf/1' in row['id']]
    assert len(rows) == 32
    rules = {}
    for row in rows:
        correspondence = bindings[row['id']]['input']['correspondence']
        rules[correspondence['rule']] = rules.get(correspondence['rule'], 0) + 1
        assert correspondence['native_language_equivalence'] == 'not_claimed'
        assert correspondence['helper_values_are_native_getter_values'] is False
    assert rules == {'metadata_compiled_getter_accessor': 16,
        'native_accessor_grammar_constraint': 4, 'gateway_empty_accessor_rejection': 12}
    assert soundengine_gaps(component, bindings)['members'] == {}

@pytest.mark.parametrize('damage', ['missing-choice', 'wrong-choice', 'missing-version'])
def test_soundengine_component_rejects_native_choice_and_version_drift(component, monkeypatch, damage):
    import tests.maintenance.soundengine_branch_mapping as mapping
    changed = deepcopy(component['native'])
    if damage == 'missing-version':
        changed['parameters'] = [row for row in changed['parameters'] if not row['id'].startswith('2021.1|')]
    else:
        row = next(row for row in changed['parameters'] if row['kind'] == 'enum_value')
        if damage == 'missing-choice':
            changed['parameters'].remove(row)
        else:
            row['shape_sha256'] = '0' * 64
    monkeypatch.setattr(mapping, 'discover_soundengine', lambda root: changed)
    with pytest.raises(ValueError, match='field/choice/version'):
        mapping.soundengine_component(ROOT)

def test_soundengine_mapping_rejects_an_unknown_native_argument(component):
    from tests.maintenance.soundengine_branch_mapping import soundengine_bindings
    changed = deepcopy(component)
    row = deepcopy(next(row for row in changed['native']['parameters'] if row['pointer'] == '/argsSchema/properties/actionType'))
    row['id'] = row['route'] + '|/argsSchema/properties/newUnreviewedValue'
    row['pointer'] = '/argsSchema/properties/newUnreviewedValue'
    changed['native']['parameters'].append(row)
    with pytest.raises(ValueError, match='native argument field'):
        soundengine_bindings(ROOT, changed)

def test_soundengine_mapping_rejects_a_removed_public_choice_field(component, monkeypatch):
    from tests.maintenance.soundengine_branch_mapping import soundengine_bindings
    from wwise_waapi import soundengine_business_contracts as contracts
    original = contracts.soundengine_control_business_contract_data
    def removed(operation, version):
        contract = original(operation, version)
        if operation == 'ak.soundengine.executeActionOnEvent':
            contract['declaration']['optional_fields'].remove('fade_curve')
        return contract
    monkeypatch.setattr(contracts, 'soundengine_control_business_contract_data', removed)
    with pytest.raises(ValueError, match='public field/choice is not disclosed'):
        soundengine_bindings(ROOT, component)
