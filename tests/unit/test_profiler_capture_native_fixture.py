"""Owned capture collector through the real Gateway and final category writer.

The external host is fake. These tests grant no native capture evidence.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from tests.unit.test_authoring_batch_adapter import owned_authoring
from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env, gateway
from tests.support.gateway_config import set_gateway_config


def _committed_capture_objects():
    """Fixture relationships come from WWU structure, not collector constants."""
    fixture = Path(__file__).resolve().parents[1] / '_org/2025.1'
    rows = {}
    for section in ('Containers', 'Busses'):
        root = ET.parse(fixture / section / 'Default Work Unit.wwu').getroot()
        parents = {child: parent for parent in root.iter() for child in parent}
        for name in ('RFL_Tail', 'WAAPI_V2_Weapons', 'Default Work Unit', 'Main Audio Bus'):
            matches = [node for node in root.iter() if node.tag in ('Sound', 'Bus', 'WorkUnit') and node.get('Name') == name]
            if not matches:
                continue
            node, = matches
            ancestors, current = [], node
            while current is not root:
                if current.get('Name'):
                    ancestors.append(current)
                current = parents[current]
            row = {'id': node.get('ID'), 'name': name, 'type': node.tag,
                'path': '\\' + '\\'.join([section, *[item.get('Name') for item in reversed(ancestors)]])}
            if section == 'Busses' and node.tag == 'Bus':
                parent = ancestors[1]
                row['parent'] = {'id': parent.get('ID'), 'name': parent.get('Name')}
                row['@Volume'] = 0.0
            if section == 'Busses' and node.tag == 'WorkUnit':
                row['workunitIsDefault'] = True
            rows[row['id']] = row
    sound = next(row for row in rows.values() if row['name'] == 'RFL_Tail')
    sound_node, = [node for node in ET.parse(fixture / 'Containers/Default Work Unit.wwu').iter()
        if node.get('ID') == sound['id']]
    bus = next(row for row in rows.values() if row['name'] == 'WAAPI_V2_Weapons')
    assert sound_node.find("ReferenceList/Reference[@Name='OutputBus']/ObjectRef").get('ID') == bus['id']
    source = sound_node.find('ChildrenList/AudioFileSource')
    assert source.findtext('AudioFile') == r'WAAPI Skill Integration V2\audit_tail.wav'
    assert sound_node.find('ActiveSourceList/ActiveSource').get('ID') == source.get('ID')
    bus['parent.workunitIsDefault'] = rows[bus['parent']['id']]['workunitIsDefault']
    return rows


def _capture_host(owner, tmp_path, monkeypatch, *, failure=None):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.profiler_capture import (
        NODEID, SOUND_ID, BUS_ID, collect_owned_capture,
    )
    runtime = owner.runtime
    runtime.lifecycle.ready_result['version']['displayName'] = 'v2025.1.7.9143'
    media = runtime.sandbox.sandbox_path / 'Originals/SFX/WAAPI Skill Integration V2/audit_tail.wav'
    media.parent.mkdir(parents=True)
    import wave
    with wave.open(str(media), 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(48000)
        output.writeframes(b'\x01\x00' * 5567)

    class Client(_RuntimeControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path)
            self.calls, self.transport, self.playing, self.user_time = [], False, False, 0
            self.registered = False
            self.logs = {'general': [], 'sourceControl': [{'message': 'preserve unselected channel',
                'severity': 'Message', 'time': 1, 'messageId': 'Custom'}]}
            self.rows = _committed_capture_objects()
            self.rows[SOUND_ID].update({'classId': 65552, '@IsLoopingEnabled': False, '@IsLoopingInfinite': True})
            self.rows[BUS_ID]['classId'] = 1376272
            if failure == 'wrong-parent':
                sibling = next(row for row in self.rows.values() if row['name'] == 'Main Audio Bus')
                self.rows[BUS_ID]['parent'] = {key: sibling[key] for key in ('id', 'name')}

        def call(self, uri, args=None, options=None):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getInfo'):
                info = super().call(uri, args, options)
                info['version'].update(runtime.lifecycle.ready_result['version'])
                info['version']['displayName'] = 'v2025.1.7.9143'
                return {**info, **deepcopy(runtime.lifecycle.ready_result), 'version': info['version']}
            if uri.endswith('getProjectInfo'):
                return {'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'SampleProject',
                    'path': str(runtime.sandbox.sandbox_project), 'isDirty': False}
            if uri.endswith('object.get'):
                ids = args.get('from', {}).get('id', [])
                if 'waql' in args:
                    ids = [identity for identity in self.rows if identity in args['waql']]
                return {'return': [{key: deepcopy(row[key] if key in row else row['@' + key])
                    for key in options['return'] if key in row or '@' + key in row}
                    for identity in ids if (row := self.rows.get(identity))]}
            if uri.endswith('getPropertyAndReferenceNames'):
                return {'return': ['IsLoopingEnabled', 'IsLoopingInfinite'] if args.get('object') == SOUND_ID
                    else ['Volume']}
            if uri.endswith('getPropertyInfo'):
                token = args['property']
                return {'name': token, 'type': 'bool' if token.startswith('IsLooping') else 'Real64',
                    'display': {'name': token}, 'default': token == 'IsLoopingInfinite',
                    'dependencies': ([{'type': 'property', 'name': 'IsLoopingEnabled', 'action': 'Enable',
                        'values': [True]}] if token == 'IsLoopingInfinite' else []), 'supports': {}, 'restriction': {}}
            if uri.endswith('object.setProperty'):
                self.rows[args['object']]['@' + args['property']] = args['value']
                return {}
            if uri.endswith('transport.getList'):
                return {'list': [{'transport': 74, 'object': SOUND_ID, 'gameObject': 1}] if self.transport else []}
            if uri.endswith('transport.create'):
                self.transport = True
                return {'transport': 74}
            if uri.endswith('transport.destroy'):
                self.transport = False
                return {}
            if uri.endswith('transport.executeAction'):
                self.playing = args['action'] == 'play'
                return {}
            if uri.endswith('transport.getState'):
                return {'state': 'playing' if self.playing else 'stopped'}
            if uri.endswith('profiler.getCursorTime'):
                return {'return': 1500 if args['cursor'] == 'capture' else self.user_time}
            if uri.endswith('profiler.setCursorTime'):
                self.user_time = 1490
                return {'return': self.user_time}
            if uri.endswith('profiler.getMeters'):
                if failure == 'empty-meter':
                    return {'meters': []}
                row = self.rows[BUS_ID]
                return {'meters': [{'object': {key: deepcopy(row[key]) for key in options.get('return', ['id', 'name']) if key in row},
                    'source': 'Bus', 'configurationName': '1.0', 'configurationMask': 4,
                    'configurationType': 'Standard', 'channels': [{'name': 'C', 'value': -12.5}]}]}
            if uri.endswith('profiler.registerMeter'):
                self.registered = True
                return {}
            if uri.endswith('profiler.unregisterMeter'):
                if failure == 'cleanup':
                    raise RuntimeError('fake unregister failure')
                self.registered = False
                return {}
            if uri.endswith('profiler.saveCapture'):
                Path(args['file']).write_bytes(b'opaque fake capture; no native format claim')
                return {}
            if uri.endswith('log.get'):
                return {'items': deepcopy(self.logs[args['channel']])}
            if uri.endswith('log.addItem'):
                self.logs['general'].append({'message': args['message'], 'severity': args['severity'],
                    'time': 2, 'messageId': 'Custom'})
                return {}
            if uri.endswith('log.clear'):
                self.logs[args['channel']] = []
                return {}
            if uri.endswith('profiler.stopCapture') and failure == 'explicit-stop-capture':
                raise RuntimeError('fake explicit stop capture failure')
            if uri.endswith(('profiler.startCapture', 'profiler.stopCapture')):
                return {'return': 1500}
            if uri.endswith(('profiler.enableProfilerData', 'transport.useOriginals')):
                return {}
            return super().call(uri, args, options)

    client = Client()
    def factory(*, skill_source, runtime, version, receipts):
        env = _env(runtime.owned_root)
        set_gateway_config(env, wwise_version='2025.1', project_modification_policy='ask_before_changes')
        env['WWISE_EVIDENCE_DIR'] = runtime.runner_environment['WWISE_EVIDENCE_DIR']
        def call(argv):
            code, payload = gateway.execute_gateway(['--state-dir', str(runtime.owned_root / 'setup-state'), *argv],
                env=env, client_factory=lambda _: client)
            receipts.append({'argv': list(argv), 'exit_code': code, 'payload': payload})
            assert code == 0, payload
            return payload
        return call
    monkeypatch.setattr(authoring_batch, 'fixture_gateway', factory)
    batch = authoring_batch.AuthoringBatchAdapter(owner=owner, repo_root=tmp_path, selected_nodeids=[NODEID])
    call = batch.node_gateway(NODEID)
    return batch, call, client, collect_owned_capture


def _finish(batch, tmp_path, monkeypatch, *, passed):
    from tests.destructive.support import authoring_batch
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle
    from wwise_waapi.headless import CleanupReport, HeadlessLifecycle
    target = tmp_path / 'capture-categories.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    def shutdown(process, sandbox, **kwargs):
        process.process = None
        process.cleanup_report = CleanupReport(launch_pid=1234, wine_prefix=None, process_exited=True)
        sandbox.metadata.process_cleanup_result = 'cleaned'
        sandbox.metadata.process_cleanup_details = {'residual_processes': []}
    monkeypatch.setattr(lifecycle, 'shutdown_sandboxed_wwise', shutdown)
    monkeypatch.setattr(authoring_batch, 'wait_for_port_release', lambda *_: None)
    monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(12345, 'fake pytest process')])
    item = SimpleNamespace(nodeid=batch.selected_nodeids[0],
        _waapi_phase_reports={'setup': 'passed', 'call': 'passed' if passed else 'failed'})
    batch.prepare_stop([item])
    item._waapi_phase_reports['teardown'] = 'passed'
    final = batch.finalize([item], terminal=True, exitstatus=0 if passed else 1)
    return final, json.loads(target.read_text().splitlines()[-1])


def test_owned_capture_public_flow_reaches_archived_final_categories(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch)
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS'
    categories = record['categories']
    assert {row['category'] for row in categories} == {
        'profiler-meter-object-observation', 'profiler-cursor-snap-readback', 'profiler-saved-capture-artifact',
        'runtime-owned-log-add', 'runtime-owned-log-clear'}
    assert all(row['status'] == row['business_outcome'] == 'PASS' for row in categories)
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report_root = Path(archive['artifacts']['native-evidence']['path'])
    report = json.loads((report_root / 'profiler-capture.json').read_text())
    assert report['cleanup']['complete'] is True
    assert report['outcomes']['profiler-meter-object-observation']['evidence']['meters'][0]['channels'] == [{'name': 'C', 'value': -12.5}]
    meter_object = report['outcomes']['profiler-meter-object-observation']['evidence']['meters'][0]['object']
    assert meter_object['path'] == r'\Busses\Default Work Unit\WAAPI_V2_Weapons'
    assert meter_object['volume_db'] == 0.0
    assert meter_object['related']['parent']['object'] == {
        'id': '{A74EEB4A-0805-4AFA-969C-53DCB862B550}', 'name': 'Default Work Unit'}
    assert meter_object['related']['parent']['work_unit_is_default'] is True
    assert report['outcomes']['profiler-cursor-snap-readback']['evidence']['snapped_time_ms'] == 1490
    assert report['outcomes']['profiler-saved-capture-artifact']['evidence']['capture_format_validity_verified'] is False
    assert (report_root / 'saved-capture/OwnedCapture.prof').read_bytes().startswith(b'opaque fake')
    assert not client.transport and not client.registered
    assert not batch.runtime.owned_root.exists()
    assert record['source']['hash_before'] == record['source']['hash_after']
    assert all(row['batch_finalization'] for row in categories)
    controls = [uri for uri, _, _ in client.calls if uri.endswith(('transport.destroy', 'log.addItem', 'log.clear'))]
    assert controls == ['ak.wwise.core.transport.destroy', 'ak.wwise.core.log.addItem', 'ak.wwise.core.log.clear']
    assert client.logs == {'general': [], 'sourceControl': [{'message': 'preserve unselected channel',
        'severity': 'Message', 'time': 1, 'messageId': 'Custom'}]}


def test_mismatched_structural_parent_stops_before_writes_and_final_acceptance(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, failure='wrong-parent')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL' and batch.lifecycle_result.quarantine_path
    assert all(row['business_outcome'] == 'BLOCKED' and row['status'] == 'blocked'
        and 'batch_finalization' not in row for row in record['categories'])
    artifact = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(artifact['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert report['setup'] == [] and report['public_call_count'] == 3
    assert 'Main Audio Bus' in report['errors'][0]['message']
    assert report['cleanup']['complete'] is True and report['cleanup']['receipts'] == []
    assert not client.transport and not client.registered
    assert {uri for uri, _, _ in client.calls} <= {
        'ak.wwise.core.getInfo', 'ak.wwise.core.getProjectInfo', 'ak.wwise.core.object.get',
        'ak.wwise.core.object.getPropertyAndReferenceNames', 'ak.wwise.core.object.getPropertyInfo'}
    assert record['source']['hash_before'] == record['source']['hash_after']


def test_empty_meter_retains_cursor_file_and_cleanup_as_separate_observations(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, failure='empty-meter')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL'
    categories = {row['category']: row for row in record['categories']}
    assert categories['profiler-meter-object-observation']['status'] == 'FAIL'
    for name in ('profiler-cursor-snap-readback', 'profiler-saved-capture-artifact'):
        assert categories[name]['business_outcome'] == 'PASS' and categories[name]['status'] == 'blocked'
    assert all(row['cleanup_complete'] is True and 'batch_finalization' not in row for row in categories.values())
    assert not client.transport and not client.registered
    assert batch.lifecycle_result.quarantine_path
    assert record['source']['hash_before'] == record['source']['hash_after']
    artifact = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report_root = Path(artifact['artifacts']['native-evidence']['path'])
    report = json.loads((report_root / 'profiler-capture.json').read_text())
    assert report['outcomes']['profiler-meter-object-observation']['outcome'] == 'FAIL'
    assert (report_root / 'saved-capture/OwnedCapture.prof').is_file()


def test_cleanup_failure_retains_each_business_observation_without_acceptance(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, failure='cleanup')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL'
    assert all(row['status'] == 'blocked' and row['business_outcome'] == 'PASS'
        and row['cleanup_complete'] is False and 'batch_finalization' not in row for row in record['categories'])
    assert sum(uri.endswith('profiler.unregisterMeter') for uri, _, _ in client.calls) == 1
    assert not client.transport and client.registered
    archived = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    root = Path(archived['artifacts']['native-evidence']['path'])
    report = json.loads((root / 'profiler-capture.json').read_text())
    assert report['cleanup']['errors'][0]['action'] == 'unregister-meter'
    assert any('fake unregister failure' in json.dumps(row['payload']) for row in archived['receipts'])
    assert batch.lifecycle_result.quarantine_path and not batch.batch_seal_path.exists()


def test_failed_explicit_stop_capture_persists_incomplete_cleanup_without_retry(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, failure='explicit-stop-capture')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL'
    assert all(row['cleanup_complete'] is False and row['status'] == 'blocked'
        and 'batch_finalization' not in row for row in record['categories'])
    assert sum(uri == 'ak.wwise.core.profiler.stopCapture' for uri, _, _ in client.calls) == 1
    assert batch.lifecycle_result.quarantine_path and not batch.batch_seal_path.exists()
    archived = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    root = Path(archived['artifacts']['native-evidence']['path'])
    report = json.loads((root / 'profiler-capture.json').read_text())
    assert report['complete'] is False and report['cleanup']['complete'] is False
    assert [row['action'] for row in report['cleanup']['errors']] == ['stop-capture']
    assert report['outcomes']['profiler-meter-object-observation']['outcome'] == 'PASS'
    assert not any(row['action'] == 'stop-capture' for row in report['cleanup']['receipts'])
    failed = [row for row in archived['receipts'] if row['argv'][0] == 'execute'
        and row['payload'].get('dispatch_result', {}).get('api') == 'ak.wwise.core.profiler.stopCapture']
    assert len(failed) == 1 and failed[0]['exit_code'] == 2
    assert failed[0]['payload']['state'] == 'indeterminate'
    assert failed[0]['payload']['automatic_retry'] is False
    assert record['source']['hash_before'] == record['source']['hash_after']


@pytest.mark.parametrize('version,extra', [('2024.1', False), ('2025.1', True), ('2025.1', False)])
def test_capture_owner_requires_exact_single_2025_selection(tmp_path, monkeypatch, version, extra):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.profiler_capture import NODEID
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    monkeypatch.setenv('WWISE_VERSION', version)
    config = _config(tmp_path)
    config.args = [NODEID, *([NODE] if extra else [])]
    items = [SimpleNamespace(nodeid=name) for name in config.args]
    if version != '2025.1' or extra:
        with pytest.raises(pytest.UsageError, match='only its matching 2025'):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [row[0] for row in events] == ['construct', 'start', 'install']
