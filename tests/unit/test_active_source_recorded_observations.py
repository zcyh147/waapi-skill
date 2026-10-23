"""Public 2021 active-source queries over retained native observation shapes."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_typed_query_construction import _AdvancedQueryClient, _env, gateway


def _observations():
    path = Path(__file__).parents[1] / 'fixtures/query/active-source-2021-recorded.json'
    return json.loads(path.read_text(encoding='utf-8'))


class RecordedClient(_AdvancedQueryClient):
    def __init__(self, observations):
        super().__init__('2021.1')
        self.observations = observations
        self.child_reads = 0
        self.sound_reads = 0

    def call(self, uri, args=None, options=None):
        if uri != 'ak.wwise.core.object.get' and uri != 'ak.wwise.core.object.getTypes':
            return super().call(uri, args, options)
        self.calls.append((uri, deepcopy(args or {}), deepcopy(options or {})))
        if uri.endswith('getTypes'):
            return {'return': deepcopy(self.observations['class_catalog'])}
        query = args['waql']
        if query.startswith('from type Platform'):
            rows = self.observations['platforms']
        elif query.startswith('from type Language'):
            rows = self.observations['languages']
        elif query.startswith('from type Project'):
            rows = [self.observations['project']]
        elif 'select children' in query:
            self.child_reads += 1
            rows = self.observations['children']
        else:
            assert self.observations['sound']['id'] in query, query
            self.sound_reads += 1
            rows = [self.observations['sound']]
        return {'return': [{key: deepcopy(row[key]) for key in options['return'] if key in row} for row in rows]}


@pytest.mark.parametrize('language_selector', ['SFX', '{85A66963-A627-476E-91C1-2770B39D245A}'])
def test_recorded_2021_language_page_completes_public_active_source_proof(tmp_path, language_selector):
    observations = _observations()
    # Reverse retained child order to prove the saved independent oracle wins.
    observations['children'].reverse()
    client = RecordedClient(observations)
    code, result = gateway.execute_gateway(['query-object', '--exact-id', observations['sound']['id'],
        '--platform', 'Mac', '--language', language_selector, '--include', 'active-source', '--detail'],
        env=_env(tmp_path, '2021.1'), client_factory=lambda _: client)
    assert code == 0, result
    assert result['agent_result'] == [{key: observations['sound'][key] for key in ('id', 'name', 'type', 'path')} |
        {'active_source': {'id': '{49F9623F-8C35-4964-936A-0D272C64F925}', 'name': 'Zeta_1'}}]
    assert list(result)[-1] == 'agent_result'
    proof = result['active_source_resolution']
    assert proof['platform'] == observations['platforms'][2]
    assert proof['language'] == observations['languages'][3]
    assert proof['complete'] and proof['stable_observation'] and proof['source_count'] == 2
    assert client.sound_reads == 2 and client.child_reads == 2
    source_reads = [options for uri, args, options in client.calls
        if uri.endswith('object.get') and observations['sound']['id'] in args.get('waql', '')]
    assert len(source_reads) == 4
    assert all(options['platform'] == '{9C6217D5-DD11-4795-87C1-6CE02853C541}'
        and options['language'] == '{85A66963-A627-476E-91C1-2770B39D245A}' for options in source_reads)
    assert all('activeSource' not in options['return'] for options in source_reads)


@pytest.mark.parametrize('change,expected', [
    ({'path': 'Other'}, 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ({'name': 'SFX/Child', 'path': 'SFX/Child'}, 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ({'name': 'SFX\\Child', 'path': 'SFX\\Child'}, 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ({'name': 'SFX\x00Child', 'path': 'SFX\x00Child'}, 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ({'name': 'SFX\nChild', 'path': 'SFX\nChild'}, 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ({'name': 'SFX\x7fChild', 'path': 'SFX\x7fChild'}, 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ({'name': '', 'path': ''}, 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ({'name': 'x' * 513, 'path': 'x' * 513}, 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ({'path': None}, 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ({'id': '{00000000-0000-0000-0000-000000000000}'}, 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ({'id': 'not-a-guid'}, 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ({'type': 'Sound'}, 'ACTIVE_SOURCE_SELECTION_UNRESOLVED'),
])
def test_recorded_2021_query_rejects_malformed_language_identity_before_source_reads(tmp_path, change, expected):
    observations = _observations()
    observations['languages'][3].update(change)
    client = RecordedClient(observations)
    code, result = gateway.execute_gateway(['query-object', '--exact-id', observations['sound']['id'],
        '--platform', 'Mac', '--language', '{85A66963-A627-476E-91C1-2770B39D245A}', '--include', 'active-source'],
        env=_env(tmp_path, '2021.1'), client_factory=lambda _: client)
    assert code == 2 and result['error_code'] == expected, result
    assert not result.get('agent_result') and not result.get('continuations')
    assert result['details']['native_absence_proven'] is False
    assert client.child_reads == 0 and client.sound_reads == 0


@pytest.mark.parametrize('fault,expected', [
    ('missing-source-class', 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ('wrong-source-parent', 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ('wrong-child-hierarchy', 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ('relative-sound-path', 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ('missing-language-guid', 'ACTIVE_SOURCE_INVALID_OBSERVATION'),
    ('wrong-language-view', 'ACTIVE_SOURCE_SELECTION_UNRESOLVED'),
    ('ambiguous-path', 'ACTIVE_SOURCE_SELECTION_UNRESOLVED'),
])
def test_recorded_2021_scope_acceptance_retains_dependent_source_proof_boundaries(tmp_path, fault, expected):
    observations = _observations()
    active, inactive = observations['children']
    if fault == 'missing-source-class':
        del active['classId']
    elif fault == 'wrong-source-parent':
        active['parent'] = {'id': observations['project']['id']}
    elif fault == 'wrong-child-hierarchy':
        active['path'] = r'\Other\Zeta_1'
    elif fault == 'relative-sound-path':
        observations['sound']['path'] = observations['sound']['name']
    elif fault == 'missing-language-guid':
        del active['audioSource:language']['id']
    elif fault == 'wrong-language-view':
        active['audioSource:language'] = {'id': observations['languages'][0]['id'], 'name': 'English(US)'}
    elif fault == 'ambiguous-path':
        inactive['originalWavFilePath'] = active['originalWavFilePath']
    client = RecordedClient(observations)
    code, result = gateway.execute_gateway(['query-object', '--exact-id', observations['sound']['id'],
        '--platform', 'Mac', '--language', 'SFX', '--include', 'active-source'],
        env=_env(tmp_path, '2021.1'), client_factory=lambda _: client)
    assert code == 2 and result['error_code'] == expected, result
    assert not result.get('agent_result') and not result.get('continuations')
    assert result['details']['native_absence_proven'] is False
    assert client.sound_reads == 1
    assert client.child_reads == (0 if fault == 'relative-sound-path' else 1)
    assert all('activeSource' not in options.get('return', ()) for _, _, options in client.calls)
