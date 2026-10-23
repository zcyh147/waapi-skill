"""Selected transport observations use the public Gateway and persisted final writer.

The external Wwise process is substituted; no native semantics credit.
"""
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tests.unit.test_authoring_batch_adapter import owned_authoring
from tests.unit.test_profiler_capture_native_fixture import _committed_capture_objects, _finish
from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env, gateway
from tests.support.gateway_config import set_gateway_config


def _host(owner, tmp_path, monkeypatch, *, failure=None):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.transport_semantics import NODEID, collect_selected_transport_semantics
    sound_id = '{FBF74BF9-8B83-44A8-AC8A-BA85372ECDC4}'
    source_id = '{6F767F75-9ED2-4860-A745-A5D905C6DF9C}'
    fixture = Path(__file__).resolve().parents[1] / '_org/2025.1'
    root = ET.parse(fixture / 'Containers/Default Work Unit.wwu').getroot()
    sound, = [s for s in root.iter('Sound') if s.get('Name') == 'RFL_Tail']
    assert sound.get('ID') == sound_id and sound.find('ChildrenList/AudioFileSource').get('ID') == source_id
    assert sound.find('ActiveSourceList/ActiveSource').get('ID') == source_id
    media = owner.runtime.sandbox.sandbox_path / 'Originals/SFX/WAAPI Skill Integration V2/audit_tail.wav'
    media.parent.mkdir(parents=True)
    media.write_bytes((fixture / 'Originals/SFX/WAAPI Skill Integration V2/audit_tail.wav').read_bytes())

    class Client(_RuntimeControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path)
            self.project_file = owner.runtime.sandbox.sandbox_project
            self.calls, self.active, self.state = [], False, 'stopped'
            self.rows = _committed_capture_objects()
            self.rows[sound_id].update({'classId': 65552, '@IsLoopingEnabled': False,
                '@IsLoopingInfinite': True, 'activeSource': {'id': source_id, 'name': 'audit_tail'}})
            self.rows[source_id] = {'id': source_id, 'name': 'audit_tail', 'type': 'AudioFileSource',
                'path': self.rows[sound_id]['path'] + '\\audit_tail'}

        def call(self, uri, args=None, options=None):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getInfo'):
                return deepcopy(owner.runtime.lifecycle.ready_result)
            if uri.endswith('object.get'):
                ids = args.get('from', {}).get('id', [])
                if 'waql' in args:
                    ids = [x for x in self.rows if x in args['waql']]
                rows = [self.rows[x] for x in ids if x in self.rows]
                return {'return': [{k: deepcopy(row[k] if k in row else row['@' + k]) for k in options.get('return', ['id','name','type','path']) if k in row or '@' + k in row} for row in rows]}
            if uri.endswith('object.getPropertyAndReferenceNames'):
                return {'return': ['IsLoopingEnabled', 'IsLoopingInfinite']}
            if uri.endswith('object.getPropertyInfo'):
                token = args['property']
                return {'name': token, 'type': 'bool', 'display': {'name': token},
                    'default': token == 'IsLoopingInfinite', 'dependencies': [], 'supports': {}, 'restriction': {}}
            if uri.endswith('object.setProperty'):
                self.rows[args['object']]['@' + args['property']] = args['value']
                return {}
            if uri.endswith('transport.getList'):
                return {'list': [{'transport': 0, 'object': sound_id, 'gameObject': 1}] if self.active else []}
            if uri.endswith('transport.create'):
                self.active = True
                return {'transport': 0}
            if uri.endswith('transport.destroy'):
                if failure == 'cleanup':
                    raise RuntimeError('fake uncertain destroy')
                self.active = False
                return {}
            if uri.endswith('transport.getState'):
                return {'state': self.state}
            if uri.endswith('transport.executeAction'):
                action = args['action']
                if action == 'stop': self.state = 'stopped'
                elif action in ('play', 'playDirectly'): self.state = 'playing'
                elif action == 'pause':
                    self.state = ('stopped' if failure == 'missing-paused' else 'paused') if self.state == 'playing' else 'playing' if self.state == 'paused' else 'stopped'
                elif action == 'playStop': self.state = 'stopped' if self.state in ('playing','paused') else 'playing'
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
    batch = authoring_batch.AuthoringBatchAdapter(owner=owner, repo_root=tmp_path, selected_nodeids=[NODEID])
    return batch, batch.node_gateway(NODEID), client, collect_selected_transport_semantics


def test_selected_observations_archive_without_business_or_coverage_pass(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _host(owned_authoring, tmp_path, monkeypatch)
    report = collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS'
    category, = record['categories']
    assert category['status'] != 'PASS' and category['observation_task_status'] == 'PASS'
    assert category['business_effect_verified'] is False
    assert category['coverage_credit'] == 'none_pending_semantics'
    archived = json.loads(Path(category['observation_artifact']['path']).read_text())
    saved = json.loads((Path(archived['artifacts']['native-evidence']['path']) / 'transport-semantics.json').read_text())
    assert saved == report
    assert [(c['case_id'], c['before']['state'], c['after']['observed_state']) for c in saved['cases']] == [
        ('D-one','stopped','playing'), ('P-one','stopped','stopped'), ('T-one','paused','stopped')]
    assert all(c['observation_status'] == 'OBSERVED' and c['business_effect_verified'] is False for c in saved['cases'])
    assert saved['cleanup']['complete'] is True and saved['public_call_count'] <= 210
    assert client.rows['{FBF74BF9-8B83-44A8-AC8A-BA85372ECDC4}']['@IsLoopingEnabled'] is False


@pytest.mark.parametrize('failure,observed', [('missing-paused', 2), ('cleanup', 3)])
def test_incomplete_transport_observations_preserve_partial_archive_without_acceptance(
    owned_authoring, tmp_path, monkeypatch, failure, observed,
):
    batch, call, client, collect = _host(owned_authoring, tmp_path, monkeypatch, failure=failure)
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL'
    category, = record['categories']
    assert category['status'] != 'PASS' and category['observation_task_status'] == 'BLOCKED'
    assert category['business_effect_verified'] is False and category['cleanup_complete'] is False
    assert category['coverage_credit'] == 'none_pending_semantics' and 'batch_finalization' not in category
    archived = json.loads(Path(category['observation_artifact']['path']).read_text())
    saved = json.loads((Path(archived['artifacts']['native-evidence']['path']) / 'transport-semantics.json').read_text())
    assert sum(case['observation_status'] == 'OBSERVED' for case in saved['cases']) == observed
    assert saved['complete'] is False
    if failure == 'missing-paused':
        assert not any(uri.endswith('executeAction') and args['action'] == 'playStop' for uri, args, _ in client.calls)
        assert saved['cases'][2]['observation_status'] == 'BLOCKED'
    else:
        assert sum(uri.endswith('transport.destroy') for uri, _, _ in client.calls) == 1
        assert saved['cleanup']['errors'][0]['action'] == 'destroy'
    assert record['residual_state']['quarantine_path']


@pytest.mark.parametrize('version,extra', [('2025.1', False), ('2024.1', False), ('2025.1', True)])
def test_selected_semantics_node_uses_exact_2025_owner_and_child_startup_recipe(tmp_path, monkeypatch, version, extra):
    from types import SimpleNamespace
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.transport_semantics import NODEID
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    monkeypatch.setenv('WWISE_VERSION', version)
    monkeypatch.delenv('AK_AUTOMATION_MODE', raising=False)
    config = _config(tmp_path)
    config.args = [NODEID, *([NODE] if extra else [])]
    items = [SimpleNamespace(nodeid=name) for name in config.args]
    if version != '2025.1' or extra:
        with pytest.raises(pytest.UsageError, match='only their matching 2025'):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [e[0] for e in events] == ['construct','start','install']
        assert events[0][1]['live_environment']['AK_AUTOMATION_MODE'] == '1'
        assert 'AK_AUTOMATION_MODE' not in authoring_batch.os.environ
