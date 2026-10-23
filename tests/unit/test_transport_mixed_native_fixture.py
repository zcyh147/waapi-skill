"""Mixed scope observations through the public Gateway and persisted category.

Only the external Wwise host is substituted. No native effect credit.
"""
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tests.unit.test_authoring_batch_adapter import owned_authoring
from tests.unit.test_profiler_capture_native_fixture import _finish
from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env, gateway
from tests.support.gateway_config import set_gateway_config


def _host(owner, tmp_path, monkeypatch, *, failure=None):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.transport_semantics import MIXED_NODEID, collect_mixed_transport_semantics
    fixture = Path(__file__).resolve().parents[1] / '_org/2025.1'
    root = ET.parse(fixture / 'Containers/Default Work Unit.wwu').getroot()
    parents = {child: parent for parent in root.iter() for child in parent}
    rows, sounds = {}, []
    for name in ('RFL_Tail', 'Rifle_Mechanical'):
        sound, = [node for node in root.iter('Sound') if node.get('Name') == name]
        source = sound.find('ChildrenList/AudioFileSource')
        assert sound.find('ActiveSourceList/ActiveSource').get('ID') == source.get('ID')
        relative = Path('Originals/SFX') / Path(source.findtext('AudioFile').replace('\\', '/'))
        media = owner.runtime.sandbox.sandbox_path / relative
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes((fixture / relative).read_bytes())
        ancestry, node = [], sound
        while node is not root:
            if node.get('Name'):
                ancestry.append(node.get('Name'))
            node = parents[node]
        path = '\\Containers\\' + '\\'.join(reversed(ancestry))
        rows[sound.get('ID')] = {'id': sound.get('ID'), 'name': name, 'type': 'Sound', 'path': path,
            'classId': 65552, '@IsLoopingEnabled': False, '@IsLoopingInfinite': True,
            'activeSource': {'id': source.get('ID'), 'name': source.get('Name')}}
        rows[source.get('ID')] = {'id': source.get('ID'), 'name': source.get('Name'),
            'type': 'AudioFileSource', 'path': path + '\\' + source.get('Name')}
        sounds.append(sound.get('ID'))

    class Client(_RuntimeControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path)
            self.project_file = owner.runtime.sandbox.sandbox_project
            self.rows, self.calls, self.transports, self.states = rows, [], {}, {}
            self.originals = False
            self.all_actions = []

        def call(self, uri, args=None, options=None):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getInfo'):
                return deepcopy(owner.runtime.lifecycle.ready_result)
            if uri.endswith('object.get'):
                ids = args.get('from', {}).get('id', [])
                if 'waql' in args:
                    ids = [identity for identity in self.rows if identity in args['waql']]
                return {'return': [{key: deepcopy(row.get(key, row.get('@' + key)))
                    for key in options.get('return', ['id','name','type','path'])
                    if key in row or '@' + key in row}
                    for identity in ids if (row := self.rows.get(identity))]}
            if uri.endswith('object.getPropertyAndReferenceNames'):
                return {'return': ['IsLoopingEnabled', 'IsLoopingInfinite']}
            if uri.endswith('object.getPropertyInfo'):
                return {'name': args['property'], 'type': 'bool', 'display': {'name': args['property']},
                    'default': args['property'] == 'IsLoopingInfinite', 'dependencies': [], 'supports': {}, 'restriction': {}}
            if uri.endswith('object.setProperty'):
                self.rows[args['object']]['@' + args['property']] = args['value']
                return {}
            if uri.endswith('transport.useOriginals'):
                self.originals = args['enable']
                return {}
            if uri.endswith('transport.getList'):
                return {'list': list(deepcopy(self.transports).values())}
            if uri.endswith('transport.create'):
                native = (17, 91)[len(self.transports)]
                self.transports[native] = {'transport': native, 'object': args['object'], 'gameObject': native + 100}
                self.states[native] = 'stopped'
                return {'transport': native}
            if uri.endswith('transport.destroy'):
                del self.transports[args['transport']]
                return {}
            if uri.endswith('transport.getState'):
                return {'state': self.states[args['transport']]}
            if uri.endswith('transport.executeAction'):
                action = args['action']
                ids = [args['transport']] if 'transport' in args else list(self.transports)
                if 'transport' not in args:
                    self.all_actions.append((action, deepcopy(self.states)))
                for native in ids:
                    state = self.states[native]
                    if action == 'stop': state = 'stopped'
                    elif action in ('play', 'playDirectly'): state = 'playing' if self.originals else 'stopped'
                    elif action == 'pause': state = {'playing': 'paused', 'paused': 'playing', 'stopped': 'stopped'}[state]
                    elif action == 'playStop': state = 'stopped' if state == 'playing' else 'playing'
                    if failure == 'mixed-pause-mismatch' and 'transport' not in args and len(self.all_actions) == 3:
                        state = 'playing'
                    self.states[native] = state
                return {}
            return super().call(uri, args, options)

    owner.runtime.lifecycle.ready_result['version']['displayName'] = 'v2025.1.7'
    client = Client()
    def factory(*, skill_source, runtime, version, receipts):
        env = _env(runtime.owned_root, version=version)
        set_gateway_config(env, wwise_version=version, project_modification_policy='ask_before_changes')
        def call(argv):
            code, payload = gateway.execute_gateway(['--state-dir', str(runtime.owned_root / 'setup-state'), *argv],
                env=env, client_factory=lambda _: client)
            receipts.append({'argv': list(argv), 'exit_code': code, 'payload': payload})
            assert code == 0, payload
            return payload
        return call
    monkeypatch.setattr(authoring_batch, 'fixture_gateway', factory)
    batch = authoring_batch.AuthoringBatchAdapter(owner=owner, repo_root=tmp_path, selected_nodeids=[MIXED_NODEID])
    return batch, batch.node_gateway(MIXED_NODEID), client, collect_mixed_transport_semantics


def _saved(category):
    archive = json.loads(Path(category['observation_artifact']['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'transport-mixed-semantics.json').read_text())
    return archive, report


def test_mixed_observations_preserve_distinct_members_and_never_gain_business_credit(
    owned_authoring, tmp_path, monkeypatch,
):
    batch, call, client, collect = _host(owned_authoring, tmp_path, monkeypatch)
    report = collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    category, = record['categories']
    archive, saved = _saved(category)
    assert final['outcome'] == 'PASS' and saved == report
    assert category['status'] == 'blocked' and category['observation_task_status'] == 'PASS'
    assert category['business_effect_verified'] is False and category['coverage_credit'] == 'none_pending_semantics'
    assert [(case['case_id'], [row['state'] for row in case['before']],
        [row['observed_state'] for row in case['after']]) for case in saved['cases']] == [
            ('D-all', ['playing','paused'], ['playing','playing']),
            ('P-all-SP', ['stopped','playing'], ['stopped','paused']),
            ('P-all-PQ', ['playing','paused'], ['paused','playing']),
            ('T-all-SP', ['stopped','playing'], ['playing','stopped']),
            ('T-all-QS', ['paused','stopped'], ['playing','playing'])]
    assert [action for action, _ in client.all_actions] == ['playDirectly','pause','pause','playStop','playStop']
    assert len({row['object'] for row in saved['members']}) == 2
    assert [row['transport'] for row in saved['members']] == [17, 91]
    assert len({row['transport_handle'] for row in saved['members']}) == 2
    assert all(case['observation_status'] == 'OBSERVED' and case['business_effect_verified'] is False for case in saved['cases'])
    assert saved['cleanup']['complete'] and not client.transports
    assert all(not row['@IsLoopingEnabled'] for row in client.rows.values() if row['type'] == 'Sound')
    assert saved['public_call_count'] <= 480 and saved['limits']['cleanup_reserved_calls'] == 64
    assert len([receipt for receipt in archive['receipts'] if receipt['argv'][0] == 'execute']) == len(archive['transactions'])


def test_mixed_verifier_mismatch_archives_partial_states_and_suppresses_dependent_writes(
    owned_authoring, tmp_path, monkeypatch,
):
    batch, call, client, collect = _host(owned_authoring, tmp_path, monkeypatch, failure='mixed-pause-mismatch')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    category, = record['categories']
    archive, saved = _saved(category)
    assert final['outcome'] == 'FAIL' and record['residual_state']['quarantine_path']
    assert category['status'] == 'blocked' and category['observation_task_status'] == 'BLOCKED'
    assert category['business_effect_verified'] is False and category['cleanup_complete'] is False
    assert 'batch_finalization' not in category and not batch.batch_seal_path.exists()
    assert [case['observation_status'] for case in saved['cases']] == ['OBSERVED','OBSERVED','BLOCKED','BLOCKED','BLOCKED']
    assert saved['cases'][2]['acknowledgement']['executed'] is True
    interval = saved['cases'][2]['verification_interval']
    assert saved['cases'][2]['acknowledgement']['observed_at_ns'] <= interval['started_ns'] <= interval['finished_ns']
    assert [row['action'] for row in saved['cleanup']['errors']] == ['further-writes-suppressed']
    failed, = [row for row in archive['receipts'] if row['exit_code'] != 0]
    assert failed['argv'] == ['verify', saved['cases'][2]['transaction_id']]
    assert failed['payload']['state'] == 'verification_failed'
    targets = failed['payload']['verification']['verification_scope']['observation']['targets']
    assert [(row['transport'], row['before_state'], row['observed_state'], row['outcome']) for row in targets] == [
        (17, 'playing', 'playing', 'different_state'), (91, 'paused', 'playing', 'matched')]
    assert archive['receipts'][-1] == failed
    assert len(client.all_actions) == 3
    assert not any(uri.endswith('transport.destroy') for uri, _, _ in client.calls)
    assert all(row['@IsLoopingEnabled'] for row in client.rows.values() if row['type'] == 'Sound')


@pytest.mark.parametrize('version,extra', [('2025.1', False), ('2024.1', False), ('2025.1', True)])
def test_mixed_semantics_node_requires_its_exact_single_2025_owner(tmp_path, monkeypatch, version, extra):
    from types import SimpleNamespace
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.transport_semantics import MIXED_NODEID
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    monkeypatch.setenv('WWISE_VERSION', version)
    monkeypatch.delenv('AK_AUTOMATION_MODE', raising=False)
    config = _config(tmp_path)
    config.args = [MIXED_NODEID, *([NODE] if extra else [])]
    items = [SimpleNamespace(nodeid=name) for name in config.args]
    if version != '2025.1' or extra:
        message = 'Selected owned Authoring node is not available on the requested version' if version != '2025.1' else 'only their matching 2025'
        with pytest.raises(pytest.UsageError, match=message):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [event[0] for event in events] == ['construct','start','install']
        assert events[0][1]['live_environment']['AK_AUTOMATION_MODE'] == '1'
        assert 'AK_AUTOMATION_MODE' not in authoring_batch.os.environ
