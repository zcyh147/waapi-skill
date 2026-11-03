"""Read-only older Playlist question in the existing copied-project lifecycle."""
import hashlib
import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _bind_business_object, _start_business_draft, _update_business_draft,
    workflow_sandbox_runtime,
)
from wwise_waapi.host_paths import localize_waapi_host_path


pytestmark = [pytest.mark.live, pytest.mark.destructive]
MEMBER = 'Actor-Mixer Hierarchy/Minigun.wwu'
# Each lane was independently inspected; identical identities are not assumed.
SOURCES = {
    '2021.1': {
        'build': (2021, 1, 14, 8108),
        'member_sha256': '0a9b95cb19266cdf23f9f2bc0b8e1b77f5a47fa2ed0529a15a7a3f266d804341',
        'project_sha256': 'ff34b54bec62409a1e09c3467a6f000836544398bca3af33fa8d557d2c67c8be',
        'owner': '{8C0FD1AD-E45D-408D-9BF3-874970CCC123}',
        'roster': ['{0DD1BBE3-BB1E-424A-9648-BEBFBB212426}', '{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}'],
    },
    '2022.1': {
        'build': (2022, 1, 19, 8584),
        'member_sha256': '063df63e6b6da0d1f8ced1acc13d740b4fc08debef1a494f3d44396c9a769377',
        'project_sha256': '6ef42c1b859c3ab578169079b0d01c2650da38cad44cda8a357f052fdc0b1aa7',
        'owner': '{8C0FD1AD-E45D-408D-9BF3-874970CCC123}',
        'roster': ['{0DD1BBE3-BB1E-424A-9648-BEBFBB212426}', '{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}'],
    },
}


@pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2021.1', reason='Exact 2021.1.14.8108 read probe')
def test_2021_playlist_read_access(workflow_sandbox_runtime):
    collect_older_playlist_read(workflow_sandbox_runtime)


@pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2022.1', reason='Exact 2022.1.19.8584 read probe')
def test_2022_playlist_read_access(workflow_sandbox_runtime):
    collect_older_playlist_read(workflow_sandbox_runtime)


def source_identity(source_root, version):
    """Independently bind the old direct Playlist/ItemRef serialized form."""
    expected = SOURCES[version]
    raw = (source_root / MEMBER).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected['member_sha256'], 'Matching source Work Unit changed'
    project_raw = (source_root / 'SampleProject.wproj').read_bytes()
    assert hashlib.sha256(project_raw).hexdigest() == expected['project_sha256'], 'Matching source project changed'
    project, = ET.fromstring(project_raw).iter('Project')
    xml = ET.fromstring(raw)
    parents = {child: parent for parent in xml.iter() for child in parent}
    owner, = [row for row in xml.iter('RandomSequenceContainer') if row.get('ID') == expected['owner']]
    items = owner.findall('./Playlist/ItemRef')
    assert [row.get('ID') for row in items] == expected['roster'] and len(items) > 0
    children = {row.get('ID'): row for row in owner.find('ChildrenList')}
    assert all(children[row.get('ID')].tag == 'Sound' and
        children[row.get('ID')].get('Name') == row.get('Name') for row in items)
    segments, cursor = [], owner
    while cursor in parents:
        if cursor.get('Name'):
            segments.insert(0, cursor.get('Name'))
        cursor = parents[cursor]
    path = '\\Actor-Mixer Hierarchy\\' + '\\'.join(segments)
    return {'member': MEMBER, **expected, 'project_id': project.get('ID'),
        'owner_name': owner.get('Name'), 'owner_path': path,
        'owner_parent': parents[parents[owner]].get('ID'),
        'targets': [{'id': row.get('ID'), 'name': row.get('Name'),
            'path': path + '\\' + row.get('Name')} for row in items],
        'serialized_relationship': 'RandomSequenceContainer/Playlist/ItemRef'}


def collect_older_playlist_read(runtime):
    """No Preview/execute/save/setup; local Draft only discloses documented lists."""
    output = runtime.state_dir / 'older-playlist-read-probe.json'
    assert not output.exists(), 'Do not overwrite a previous native observation'
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'calls': [],
        'project_mutation_count': 0, 'business_effect_verified': False,
        'access_outcome': 'not_attempted', 'membership_verified': False,
        'limits': {'public_calls': 12, 'playlist_rows': 32, 'observation_bytes': 2 * 1024 * 1024}}
    category = {'category': 'older-playlist-read-access', 'status': 'FAIL',
        'verifier_strength': 'read_only_source_pinned_ordered_reference_membership',
        'business_effect_verified': False, 'observation_path': str(output)}
    runtime.category_results.append(category)
    baseline = None

    class Gateway:
        def raw_gateway(self, argv):
            assert len(observation['calls']) < 12, 'Older Playlist public call bound exceeded'
            full = ['--evidence-dir', str(runtime.state_dir / 'older-playlist-native'), *argv]
            record = {'argv': full}
            observation['calls'].append(record)
            code, payload = runtime.raw_gateway(full)
            record.update(exit_code=code, payload=payload)
            return code, payload

        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            if live:
                assert payload.get('detected_version') == runtime.version, payload
                if baseline is not None:
                    assert payload.get('endpoint') == baseline['endpoint'], payload
            return payload

    gateway = Gateway()

    def read_exact(identity, includes=('class-id', 'parent')):
        result = gateway.gateway(['query-object', '--exact-id', identity, '--max-results', '4',
            *[token for field in includes for token in ('--include', field)]], live=True)
        assert result.get('projection_complete') is not False and result.get('limit_reached') is not True, result
        rows = result['agent_result']
        assert isinstance(rows, list) and len(rows) == 1 and rows[0]['id'] == identity, result
        return rows[0]

    try:
        pin = source_identity(runtime.sandbox.source_root, runtime.version)
        observation['source'] = pin
        assert tuple(runtime.sandbox.metadata.get_info_version.get(key) for key in
            ('year', 'major', 'minor', 'build')) == pin['build']
        baseline = gateway.gateway(['status'], live=True)
        assert baseline['is_command_line'] is True and baseline['project']['id'] == pin['project_id'], baseline
        assert tuple(baseline['wwise']['version'].get(key) for key in ('year', 'major', 'minor', 'build')) == pin['build'], baseline
        assert Path(runtime.sandbox.metadata.launch_project_path).resolve() == runtime.sandbox.sandbox_project.resolve()
        assert runtime.sandbox.sandbox_project.resolve() != runtime.sandbox.source_project.resolve()
        if runtime.version == '2022.1':
            live_project_path = baseline['project']['path']
        else:
            project_row = observation['project_file_witness'] = read_exact(pin['project_id'], ('file-path',))
            assert project_row['type'] == 'Project', project_row
            live_project_path = project_row['file_path']
        assert Path(localize_waapi_host_path(live_project_path)).resolve() == runtime.sandbox.sandbox_project.resolve(), baseline
        # 2021 status uses Project.path (hierarchy), not getProjectInfo.path.
        observation['project_binding'] = {'launch_project_path': runtime.sandbox.metadata.launch_project_path,
            'live_project_path': live_project_path, 'status_project_id': baseline['project']['id'], 'endpoint': baseline['endpoint']}
        owner = observation['owner'] = read_exact(pin['owner'])
        assert (owner['name'], owner['path'], owner['type'], owner['class_id'], owner['parent']['id']) == (
            pin['owner_name'], pin['owner_path'], 'RandomSequenceContainer', 589840, pin['owner_parent']), owner
        targets = observation['targets'] = [read_exact(target['id']) for target in pin['targets']]
        for target, expected in zip(targets, pin['targets']):
            assert all(target[key] == expected[key] for key in ('id', 'name', 'path')), target
            assert target['type'] == 'Sound' and target['class_id'] == 65552 and target['parent']['id'] == pin['owner'], target
        draft = _start_business_draft(gateway, 'object.create')
        handle = _bind_business_object(gateway, draft, object_id=pin['owner'])
        listing = _update_business_draft(gateway, draft, 'draft-discover-fields',
            ['--object-handle', handle, '--field-source', 'documented-lists', '--list'], live=True)
        observation['documented_playlist'] = [row for row in listing['agent_result']['items'] if row['name'] == 'Playlist']
        schema = gateway.gateway(['query-schema', '--advanced'], live=False)
        assert schema['continuation']['query_layer'] == 'advanced-native-waql', schema
        code, result = gateway.raw_gateway(['query-object', '--advanced-waql',
            f'from object "{pin["owner"]}" select @Playlist', '--max-results', '32',
            '--include', 'class-id', '--include', 'parent', '--detail'])
        observation['playlist_result'] = result
        native_path = result.get('call', {}).get('evidence_path') or result.get('details', {}).get('evidence_path')
        if native_path:
            native_file = Path(native_path).resolve(strict=True)
            assert native_file.is_relative_to((runtime.state_dir / 'older-playlist-native').resolve()), native_file
            assert native_file.stat().st_size <= 256 * 1024, 'Native observation byte bound exceeded'
            raw = native_file.read_bytes()
            observation['native_record'] = json.loads(raw)
            observation['native_record_sha256'] = hashlib.sha256(raw).hexdigest()
        native = observation.get('native_record', {})
        if code != 0 or result.get('ok') is not True:
            observation['access_outcome'] = ('native_path_rejected' if
                result.get('call', {}).get('waapi_error_uri') == 'ak.wwise.query.invalid_query' else
                'native_error_unresolved' if native else 'gateway_refused')
        else:
            assert native.get('ok') is True and native.get('api') == 'ak.wwise.core.object.get', native
            assert result['detected_version'] == runtime.version and result['endpoint'] == baseline['endpoint'], result
            rows = result['agent_result']
            complete = result.get('projection_complete') is not False and result.get('limit_reached') is not True
            observation['membership_verified'] = complete and rows == targets
            observation['access_outcome'] = 'matching_membership' if observation['membership_verified'] else 'empty_or_unattributable'
        current = gateway.gateway(['status'], live=True)
        assert current['wwise'] == baseline['wwise'] and current['project'] == baseline['project'], current
        if not observation['membership_verified']:
            category['status'] = 'blocked'
            pytest.skip('Playlist read unresolved: ' + observation['access_outcome'] + '; no universal native absence claim')
        category.update(status='PASS', reason='Read-only ordered Playlist membership matched committed XML; no mutation acceptance')
    except BaseException as exc:
        observation['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= observation['limits']['observation_bytes']
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(access_outcome=observation['access_outcome'], membership_verified=observation['membership_verified'],
            observation_sha256=hashlib.sha256(body).hexdigest())
