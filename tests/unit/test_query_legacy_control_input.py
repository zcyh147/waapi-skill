"""2021 RTPC ControlInput reads through the public Gateway, with native unknown kind."""
import copy
import json
from pathlib import Path

import pytest

from tests.unit.test_query_list_functions import SequenceTask
from tests.unit.test_object_query_result_pages import VERSIONS

RTPC = '{CE99046D-D354-422D-A7BB-F1305FF00B2F}'
SOURCE = '{95DDA32B-B666-4269-A54C-5ABF4E201C99}'
LFO = '{E323F786-253F-48C6-86B9-AB0335804E9F}'
ORIGINALS = Path(__file__).parents[1] / 'fixtures/branch-evidence/product/r51-replay-r55-settled-r2/originals'
NATIVE = json.loads((ORIGINALS / 'ControlInput-native.original.json').read_text())['result']


class LegacyTask(SequenceTask):
    def __init__(self, path, version='2021.1'):
        super().__init__(path, version)
        identity = json.loads((ORIGINALS / 'identity.original.json').read_text())['agent_result'][0]
        row = {key: copy.deepcopy(value) for key, value in identity.items() if key not in {'class_id', 'unavailable_fields'}}
        row.update(classId=1441808, ControlInput={'id': LFO, 'name': 'Modulator LFO (Custom)'},
            **{'@ControlInput': {'id': LFO, 'name': 'Modulator LFO (Custom)'}})
        self.rows = [row]
        self.objects[RTPC] = row
        self.metadata[1441808] = {'ControlInput': copy.deepcopy(NATIVE)}
        self.metadata[RTPC] = {'ControlInput': copy.deepcopy(NATIVE)}


def test_exact_legacy_rtpc_has_typed_control_input_without_inventing_native_metadata(tmp_path):
    task = LegacyTask(tmp_path)
    before = copy.deepcopy(task.metadata)
    code, result = task.run('query-object', '--exact-id', RTPC, '--include', 'class-id', '--include', 'owner',
        '--include-field', 'ControlInput', '--include-local-reference', 'ControlInput')
    assert code == 0 and isinstance(result.get('agent_result'), list), json.dumps(result, indent=2)
    row, = result['agent_result']
    assert row['id'] == RTPC and row['class_id'] == 1441808 and row['owner']['id'] == SOURCE
    assert row['references']['ControlInput'] == {'id': LFO, 'name': 'Modulator LFO (Custom)'}
    assert row['local_references'] == row['references']
    assert task.metadata == before and NATIVE['type'] == '' and NATIVE['restriction'] == {}
    assert list(result)[-1] == 'agent_result'


def test_legacy_control_input_reference_hop_keeps_rtpc_and_related_lfo_values(tmp_path):
    task = LegacyTask(tmp_path)
    task.rows[0].update({'ControlInput.classId': 4194320, 'ControlInput.@LfoFrequency': 2.5})
    task.metadata[4194320] = {'LfoFrequency': {'name': 'LfoFrequency', 'type': 'Real32'}}
    code, result = task.run('query-object', '--exact-id', RTPC,
        '--include-related-field', 'reference', 'ControlInput', 'LfoFrequency')
    assert code == 0 and isinstance(result.get('agent_result'), list), json.dumps(result, indent=2)
    row, = result['agent_result']
    assert row['id'] == RTPC
    assert row['related']['references']['ControlInput'] == {
        'object': {'id': LFO, 'name': 'Modulator LFO (Custom)'}, 'properties': {'LfoFrequency': 2.5}}


@pytest.mark.parametrize('version', VERSIONS)
def test_unknown_kind_read_authority_is_only_2021_but_native_reference_metadata_still_works(tmp_path, version):
    task = LegacyTask(tmp_path, version)
    flags = ('query-object', '--exact-id', RTPC, '--include-local-reference', 'ControlInput')
    code, result = task.run(*flags)
    if version == '2021.1':
        assert code == 0 and result['agent_result'][0]['local_references']['ControlInput']['id'] == LFO, result
    else:
        assert code == 0 and isinstance(result['agent_result'], dict), result
        assert result['agent_result']['unresolved'][0]['candidate_names'] == ['ControlInput']
    task.metadata[RTPC]['ControlInput']['type'] = 'Reference'
    code, result = task.run(*flags)
    assert code == 0 and result['agent_result'][0]['local_references']['ControlInput']['id'] == LFO, result


@pytest.mark.parametrize('fault', ['class', 'type', 'missing-field', 'scalar', 'other-field'])
def test_legacy_read_proof_cannot_replace_scope_or_contradict_native_metadata(tmp_path, fault):
    task = LegacyTask(tmp_path)
    field = 'ControlInput'
    if fault == 'class': task.objects[RTPC]['classId'] = 65552
    elif fault == 'type': task.objects[RTPC]['type'] = 'ParamControl'
    elif fault == 'missing-field': task.metadata[RTPC].clear()
    elif fault == 'scalar': task.metadata[RTPC]['ControlInput'].update(type='', restriction={'type': 'range', 'min': 0, 'max': 1})
    else:
        field = 'OtherInput'
        task.metadata[RTPC][field] = {**copy.deepcopy(NATIVE), 'name': field}
        task.objects[RTPC]['@' + field] = {'id': LFO}
    code, result = task.run('query-object', '--exact-id', RTPC, '--include-local-reference', field)
    assert code == 2 or isinstance(result.get('agent_result'), dict), result
    assert not any('@' + field in (options or {}).get('return', []) for uri, _, options in task.calls if uri.endswith('object.get'))


@pytest.mark.parametrize('change', ['inventory', 'metadata', 'identity'])
def test_legacy_kind_binding_rejects_drift_after_the_value_read(tmp_path, change):
    task = LegacyTask(tmp_path)
    original = task.call
    def drift(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.get') and '@ControlInput' in (options or {}).get('return', []):
            if change == 'inventory': task.metadata[RTPC].clear()
            elif change == 'metadata': task.metadata[RTPC]['ControlInput']['type'] = 'int16'
            else: task.objects[RTPC]['classId'] = 65552
        return result
    task.call = drift
    code, result = task.run('query-object', '--exact-id', RTPC, '--include-local-reference', 'ControlInput')
    assert code == 2 and result['error_code'] == 'QUERY_REFERENCE_KIND_CHANGED' and result.get('agent_result') is None, result


@pytest.mark.parametrize('view', ['full', 'selected', 'combined'])
def test_legacy_read_kind_binding_serves_list_selected_and_combined_occurrences(tmp_path, view):
    task = LegacyTask(tmp_path)
    # Controlled relationship transport exercises the existing grouped planner;
    # it makes no claim about 2021 RTPC membership discovery in native Wwise.
    owner = {'id': SOURCE, 'name': 'Owner', 'type': 'SourcePlugin', 'path': r'\Owner', 'classId': 9699330,
        'children': [{'id': RTPC, 'name': ''}]}
    task.rows = [owner]
    task.objects[SOURCE] = owner
    task.members[RTPC] = task.objects[RTPC]
    path = {'full': ['children'], 'selected': ['children', 'first'],
        'combined': ['combine', 'children', 'and', 'children', 'end']}[view]
    code, result = task.run('query-object', '--exact-id', SOURCE,
        '--include-related-field', *path, 'ControlInput',
        '--include-related-local-reference', *path, 'ControlInput')
    assert code == 0 and isinstance(result.get('agent_result'), list), json.dumps(result, indent=2)
    row, = result['agent_result']
    context = row['related']['children'] if view == 'full' else row['related']['projections'][0]
    items = context['items']
    assert [item['object']['id'] for item in items] == [RTPC] * (2 if view == 'combined' else 1)
    assert all(item['references']['ControlInput']['id'] == LFO and item['local_references']['ControlInput']['id'] == LFO for item in items)


@pytest.mark.parametrize('version', VERSIONS)
def test_query_schema_discloses_exact_read_only_kind_source_and_retains_version_boundary(tmp_path, version):
    import hashlib
    from wwise_waapi.canonical import canonical_sha256
    task = LegacyTask(tmp_path, version)
    code, result = task.run('query-schema')
    assert code == 0, result
    contract = result['custom_outputs']['reference_kind_evidence']
    assert contract == result['related_outputs']['reference_kind_evidence']
    assert contract['fields'] == ([{'class_id': 1441808, 'registered_name': 'ParamControl',
        'native_type': 'RTPC', 'field': 'ControlInput'}] if version == '2021.1' else [])
    assert contract['mutation_authority'] is False and contract['target_restrictions_authority'] == 'native metadata only'
    source = json.loads((Path(__file__).parents[2] / 'skills/waapi-skill/resources/metadata/reference-kind-sources.json').read_text())
    assert canonical_sha256({k: v for k, v in source.items() if k != 'sha256'}) == contract['source_sha256']
    selected, = source['query_read_fields']
    assert hashlib.sha256(selected['sdk']['section'].encode()).hexdigest() == selected['sdk']['section_sha256']
    assert '<td><b>ControlInput</b></td><td>Control Input</td><td>Reference</td>' in selected['sdk']['section']
    assert selected['sdk']['raw_member_sha256'] == '6c9d0b8b83998caec78590b2979b2cda2957c627f9c9560eb835e5bfd3b6e0e3'
    assert not task.calls


def test_related_legacy_proof_revalidates_metadata_and_does_not_authorize_another_field(tmp_path):
    task = LegacyTask(tmp_path)
    task.objects[RTPC].update({'ControlInput.classId': 4194320, 'ControlInput.@LfoFrequency': 2.5})
    task.metadata[4194320] = {'LfoFrequency': {'name': 'LfoFrequency', 'type': 'Real32'}}
    task.metadata[RTPC]['OtherInput'] = {**copy.deepcopy(NATIVE), 'name': 'OtherInput'}
    task.metadata[1441808]['OtherInput'] = copy.deepcopy(task.metadata[RTPC]['OtherInput'])
    task.objects[RTPC]['OtherInput'] = {'id': LFO}
    code, result = task.run('query-object', '--exact-id', RTPC, '--include-field', 'ControlInput',
        '--include-related', 'reference', 'OtherInput', 'class-id')
    assert code == 0 and isinstance(result['agent_result'], dict), result
    assert result['agent_result']['unresolved'][0]['meaning'] == 'OtherInput'
    task.metadata[RTPC].pop('OtherInput')
    original = task.call
    def drift(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.get') and 'ControlInput.@LfoFrequency' in (options or {}).get('return', []):
            task.metadata[RTPC]['ControlInput']['default'] = 'changed'
        return result
    task.call = drift
    code, result = task.run('query-object', '--exact-id', RTPC,
        '--include-related-field', 'reference', 'ControlInput', 'LfoFrequency')
    assert code == 2 and result['error_code'] == 'QUERY_REFERENCE_KIND_CHANGED', result


def test_legacy_proof_stays_current_across_invocations_and_never_changes_mutation_discovery(tmp_path):
    task = LegacyTask(tmp_path)
    flags = ('query-object', '--exact-id', RTPC, '--include-local-reference', 'ControlInput')
    code, result = task.run(*flags)
    assert code == 0 and result['agent_result'][0]['local_references']['ControlInput']['id'] == LFO, result
    task.objects[RTPC]['type'] = 'Sound'
    code, result = task.run(*flags)
    assert code == 0 and isinstance(result['agent_result'], dict), result
    task.objects[RTPC]['type'] = 'RTPC'
    code, result = task.run('metadata', 'discover', '--exact-id', RTPC, '--meaning', 'ControlInput')
    assert code == 0, result
    assert result['agent_result']['candidates'][0]['kind'] == 'unknown', result
