"""One pinned legacy reference-Playlist workflow in the existing owned sandbox."""
import hashlib
import json
import os
from xml.etree import ElementTree

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _bind_business_object, _complete_business_draft, _start_business_draft,
    _update_business_draft, workflow_sandbox_runtime,
)


pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2023.1',
        reason='Legacy reference-Playlist effect is pinned to Console 2023.1.19.8928')]

PROJECT = '{16164796-C6E6-491A-8799-C42A33110A84}'
OWNER = '{8C0FD1AD-E45D-408D-9BF3-874970CCC123}'
UP = '{0DD1BBE3-BB1E-424A-9648-BEBFBB212426}'
LOOP = '{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}'
SOURCE_MEMBER = 'Actor-Mixer Hierarchy/Minigun.wwu'
SOURCE_SHA256 = '6c07774ee8c79adb01336cbed53088bf554c58e6289532fac7d0d2f7fcbca580'
PROJECT_SHA256 = '6936b9719114606e3e9883afa970979b5d5105246506a14b6d939033ac0f54ce'


def test_legacy_playlist_replace_append_clear_preserves_hierarchy(workflow_sandbox_runtime):
    _observe_legacy_playlist_reference_workflow(workflow_sandbox_runtime, ('replace-all', 'append', 'clear'))


def test_legacy_playlist_append_clear_preserves_hierarchy(workflow_sandbox_runtime):
    _observe_legacy_playlist_reference_workflow(workflow_sandbox_runtime, ('append', 'clear'))


def test_legacy_playlist_clear_preserves_hierarchy(workflow_sandbox_runtime):
    _observe_legacy_playlist_reference_workflow(workflow_sandbox_runtime, ('clear',))


def _observe_legacy_playlist_reference_workflow(runtime, phases):
    """Use one selected continuation; never repeat a completed earlier mutation."""
    assert phases in {('replace-all', 'append', 'clear'), ('append', 'clear'), ('clear',)}
    suffix = '-'.join(phases)
    output = runtime.state_dir / ('legacy-playlist-reference-' + suffix + '.json')
    assert not output.exists(), 'Never overwrite an earlier Playlist workflow observation'
    output.parent.mkdir(parents=True, exist_ok=True)
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'calls': [],
        'flow': list(phases), 'transactions': [], 'business_effect_verified': False,
        'phases': [{'name': name, 'status': 'not_attempted', 'business_effect_verified': False} for name in phases]}
    category = {'category': 'legacy-playlist-reference-' + suffix, 'status': 'FAIL',
        'business_effect_verified': False, 'observation_path': str(output),
        'verifier_strength': 'independent_ordered_reference_roster_and_all_hierarchy_target_preservation'}
    runtime.category_results.append(category)
    baseline_host = None

    class ReceiptGateway:
        def raw_gateway(self, argv):
            assert len(observation['calls']) < 96, 'Legacy Playlist public command bound exceeded'
            record = {'argv': list(argv)}
            observation['calls'].append(record)
            try:
                code, payload = runtime.raw_gateway(argv)
                record.update(exit_code=code, payload=payload)
                return code, payload
            except BaseException as exc:
                record['error'] = f'{type(exc).__name__}: {exc}'
                raise

        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            if live:
                assert payload.get('detected_version') == '2023.1', payload
                if baseline_host is not None:
                    assert payload.get('endpoint') == baseline_host['endpoint'], payload
            return payload

    gateway = ReceiptGateway()

    def read(selector):
        payload = gateway.gateway(['query-object', *selector, '--max-results', '9',
            '--include', 'class-id', '--include', 'parent', '--include', 'owner', '--include', 'notes'], live=True)
        assert payload.get('projection_complete') is not False and payload.get('status') != 'partial', payload
        assert payload.get('limit_reached') is not True and list(payload)[-1] == 'agent_result', payload
        rows = payload['agent_result']
        assert isinstance(rows, list) and len(rows) < 9, payload
        return rows

    def exact(identity):
        rows = read(['--exact-id', identity])
        assert len(rows) == 1 and rows[0]['id'] == identity, rows
        return rows[0]

    def roster():
        # Repeated GUIDs are meaningful legacy Playlist occurrences, not extra objects.
        return read(['--advanced-waql', f'from object "{OWNER}" select @Playlist'])

    def snapshot(sink):
        rows = sink['roster_rows'] = roster()
        sink['actual_roster'] = [row['id'] for row in rows]
        sink['owner'] = exact(OWNER)
        sink['targets'] = {}
        for identity in (UP, LOOP):
            sink['targets'][identity] = exact(identity)
        assert sink['owner'] == observation['before']['owner'], sink
        assert sink['targets'] == observation['before']['targets'], sink
        assert all(row == observation['before']['targets'][row['id']] for row in rows), rows

    def construct(phase):
        draft = _start_business_draft(gateway, 'object.set')
        owner_handle = _bind_business_object(gateway, draft, object_id=OWNER)
        handles = {identity: _bind_business_object(gateway, draft, object_id=identity) for identity in (UP, LOOP)}
        listing = _update_business_draft(gateway, draft, 'draft-discover-fields',
            ['--object-handle', owner_handle, '--field-source', 'documented-lists', '--list'], live=True)
        choice, = [row for row in listing['agent_result']['items'] if row['name'] == 'Playlist']
        selected = _update_business_draft(gateway, draft, 'draft-discover-fields',
            ['--object-handle', owner_handle, '--field-source', 'documented-lists', '--selection', choice['selection']], live=True)
        candidate, = [row for result in selected['meaning_results'] for row in result['candidates']]
        assert candidate['field_kind'] == 'list' and candidate['evidence']['scope']['class_id'] == 589840
        field = candidate['handle']
        if phase['name'] == 'clear':
            _update_business_draft(gateway, draft, 'draft-clear-object-list',
                ['--declaration-id', 'playlist-clear', '--object-handle', owner_handle, '--list-name', field], live=False)
        else:
            _update_business_draft(gateway, draft, 'draft-business-configure',
                ['--list-behavior', phase['name']], live=False)
            assigned = [UP, LOOP, LOOP] if phase['name'] == 'replace-all' else [UP]
            _update_business_draft(gateway, draft, 'draft-declare-existing',
                ['--declaration-id', 'playlist-references', '--object-handle', owner_handle,
                 '--field-value', field, json.dumps([handles[identity] for identity in assigned])], live=False)
        receipt = {}
        observation['transactions'].append(receipt)
        phase['transaction'] = receipt
        def execute_verify(transaction_id):
            receipt['transaction_id'] = transaction_id
            code, executed = gateway.raw_gateway(['execute', transaction_id])
            receipt.update(execute=executed, execute_exit_code=code)
            assert code == 0 and executed.get('ok') is True and executed.get('automatic_retry') is False, executed
            code, verified = gateway.raw_gateway(['verify', transaction_id])
            receipt.update(verify=verified, verify_exit_code=code)
            phase['verify_exit_code'] = code
            assert verified.get('state') in {'verified', 'verification_failed'}, verified
            # Keep exact native roster/target observations even when verification
            # rejects append. No further mutation follows a failed phase.
            snapshot(phase)
            assert phase['actual_roster'] == phase['expected_roster'], phase
            assert code == 0 and verified.get('verified') is True, verified
            return executed, verified
        receipt.update(_complete_business_draft(gateway, draft, execute_verify=execute_verify))

    try:
        build = runtime.sandbox.metadata.get_info_version
        assert runtime.version == '2023.1' and isinstance(build, dict) and tuple(build.get(key)
            for key in ('year', 'major', 'minor', 'build')) == (2023, 1, 19, 8928), build
        source = runtime.sandbox.source_root / SOURCE_MEMBER
        raw = source.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256, 'Committed matching Minigun source changed'
        assert hashlib.sha256(runtime.sandbox.source_project.read_bytes()).hexdigest() == PROJECT_SHA256, 'Committed matching project changed'
        xml = ElementTree.fromstring(raw)
        parent_map = {child: parent for parent in xml.iter() for child in parent}
        owner, = [row for row in xml.iter('RandomSequenceContainer') if row.get('ID') == OWNER]
        children = {row.get('ID'): row for row in owner.find('ChildrenList')}
        assert set(children) == {UP, LOOP} and all(row.tag == 'Sound' for row in children.values())
        xml_roster = [row.get('ID') for row in owner.findall('./ObjectLists/ObjectList[@Name="Playlist"]/Reference/ObjectRef')]
        assert xml_roster == [UP, LOOP], xml_roster
        segments, cursor = [], owner
        while cursor in parent_map:
            if cursor.get('Name'):
                segments.insert(0, cursor.get('Name'))
            cursor = parent_map[cursor]
        owner_path = '\\Actor-Mixer Hierarchy\\' + '\\'.join(segments)
        observation['source_identity'] = {'member': SOURCE_MEMBER, 'sha256': SOURCE_SHA256,
            'project_sha256': PROJECT_SHA256, 'owner_path': owner_path, 'before_roster': xml_roster}
        baseline_host = gateway.gateway(['status'], live=True)
        assert baseline_host['is_command_line'] is True and baseline_host['project']['id'] == PROJECT, baseline_host
        assert tuple(baseline_host['wwise']['version'].get(key) for key in
            ('year', 'major', 'minor', 'build')) == (2023, 1, 19, 8928), baseline_host
        before = observation['before'] = {'owner': exact(OWNER), 'targets': {identity: exact(identity) for identity in (UP, LOOP)},
            'roster_rows': roster()}
        assert before['owner']['name'] == owner.get('Name') and before['owner']['path'] == owner_path
        assert before['owner']['type'] == 'RandomSequenceContainer' and before['owner']['class_id'] == 589840
        assert before['owner']['parent']['id'] == parent_map[parent_map[owner]].get('ID')
        for identity, row in before['targets'].items():
            assert row['name'] == children[identity].get('Name') and row['path'] == owner_path + '\\' + row['name']
            assert row['type'] == 'Sound' and row['class_id'] == 65552 and row['parent']['id'] == OWNER
        assert [row['id'] for row in before['roster_rows']] == xml_roster
        assert all(row == before['targets'][row['id']] for row in before['roster_rows'])
        prefix = [row['id'] for row in before['roster_rows']]
        for phase in observation['phases']:
            phase['expected_roster'] = ([UP, LOOP, LOOP] if phase['name'] == 'replace-all' else
                [*prefix, UP] if phase['name'] == 'append' else [])
            phase['status'] = 'started'
            construct(phase)
            current = gateway.gateway(['status'], live=True)
            assert current['wwise'] == baseline_host['wwise'] and current['project']['id'] == PROJECT, current
            phase.update(status='PASS', business_effect_verified=True)
            prefix = phase['actual_roster']
        observation['business_effect_verified'] = True
    except BaseException as exc:
        observation['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 8 * 1024 * 1024, 'Legacy Playlist observation byte bound exceeded'
        output.write_bytes(body)
        category.update(status='PASS' if observation['business_effect_verified'] else 'FAIL',
            business_effect_verified=observation['business_effect_verified'], observation_sha256=hashlib.sha256(body).hexdigest())
