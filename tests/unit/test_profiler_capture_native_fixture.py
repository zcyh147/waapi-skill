"""Owned capture collector through the real Gateway and final category writer.

The external host is fake. These tests grant no native capture evidence.
"""
from copy import deepcopy
from dataclasses import replace
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


def _committed_2024_capture_objects():
    fixture = Path(__file__).resolve().parents[1] / '_org/2024.1'
    rows = {}
    for section, filename, names in (
        ('Actor-Mixer Hierarchy', 'Minigun.wwu', ('MnGn_Barrel_Loop',)),
        ('Master-Mixer Hierarchy', 'Default Work Unit.wwu', ('Guns', 'SFX', 'Master Audio Bus')),
    ):
        root = ET.parse(fixture / section / filename).getroot()
        parents = {child: parent for parent in root.iter() for child in parent}
        for node in root.iter():
            if node.tag not in ('Sound', 'Bus') or node.get('Name') not in names:
                continue
            lineage, current = [], node
            while current is not root:
                if current.get('Name'):
                    lineage.append(current)
                current = parents[current]
            row = {'id': node.get('ID'), 'name': node.get('Name'), 'type': node.tag,
                'path': '\\' + '\\'.join([section, *[item.get('Name') for item in reversed(lineage)]])}
            if node.tag == 'Bus':
                row.update({'classId': 1376272, '@Volume': 0.0,
                    'parent': {'id': lineage[1].get('ID'), 'name': lineage[1].get('Name')},
                    'parent.classId': 1376272 if lineage[1].tag == 'Bus' else 1638416})
                if lineage[1].tag == 'Bus':
                    row['parent.@Volume'] = 0.0
                # Matching WObjects default: Same as parent, hence Guns has no
                # independent processing/meter until configured explicitly.
                if node.get('Name') == 'Guns':
                    assert node.find("PropertyList/Property[@Name='BusChannelConfig']") is None
                    row['@BusChannelConfig'] = 0
            else:
                assert node.find("PropertyList/Property[@Name='IsLoopingEnabled']").get('Value') == 'True'
                # Stored child Master references are unused: no child overrides;
                # the top ActorMixer's ordinary OutputBus resolves to Guns.
                assert all(item.find("PropertyList/Property[@Name='OverrideOutput']") is None for item in lineage[:-2])
                output = lineage[-2].find("ReferenceList/Reference[@Name='OutputBus']/ObjectRef")
                row.update({'classId': 65552, '@IsLoopingEnabled': True, '@IsLoopingInfinite': True,
                    'OutputBus': {'id': output.get('ID'), 'name': output.get('Name')}})
                source = node.find('ChildrenList/AudioFileSource')
                assert source.findtext('AudioFile') == r'Minigun\MnGn_Barrel_Loop.wav'
                assert node.find('ActiveSourceList/ActiveSource').get('ID') == source.get('ID')
            rows[row['id']] = row
    return rows


def _capture_host(owner, tmp_path, monkeypatch, *, failure=None, version='2025.1'):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.profiler_capture import (
        NODEID, SOUND_ID, BUS_ID, collect_owned_capture,
    )
    runtime = owner.runtime
    nodeid, sound_id, bus_id = NODEID, SOUND_ID, BUS_ID
    media_relative = 'Originals/SFX/WAAPI Skill Integration V2/audit_tail.wav'
    build = '2025.1.7.9143'
    if version == '2024.1':
        nodeid = 'tests/destructive/test_authoring_ui_business_live.py::test_runtime_owned_2024_meter_projection'
        sound_id, bus_id = '{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}', '{06362E8D-5A32-497A-B063-3DA95963CE47}'
        media_relative, build = 'Originals/SFX/Minigun/MnGn_Barrel_Loop.wav', '2024.1.13.9056'
        owner.version = version
        owner.runtime = runtime = replace(runtime, version=version)
        runtime.sandbox.metadata.wwise_version = version
        runtime.lifecycle.ready_result['version'].update(year=2024, minor=13, build=9056)
    runtime.lifecycle.ready_result['version']['displayName'] = 'v' + build
    media = (tmp_path / 'matching-installed-originals/SFX/Minigun/MnGn_Barrel_Loop.wav'
        if version == '2024.1' else runtime.sandbox.sandbox_path / media_relative)
    media.parent.mkdir(parents=True)
    import wave
    with wave.open(str(media), 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(48000)
        output.writeframes(b'\x01\x00' * 5567)
    if version == '2024.1':
        from tests.destructive.support import profiler_capture
        monkeypatch.setattr(profiler_capture, 'METER_2024_MEDIA_SOURCE', media)
        # Synthetic external file, pinned independently; no native media credit.
        monkeypatch.setattr(profiler_capture, 'METER_2024_MEDIA_SHA256',
            'e352d2a9e296b862eebc1a2d357a0dea696774b257db04da1abd2ecccb70fa52')
        runtime.io_root.mkdir(parents=True, exist_ok=True)
        profiler_capture.stage_owned_2024_meter_media(runtime.sandbox, runtime.io_root)

    class Client(_RuntimeControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path, version=version)
            self.calls, self.transport, self.playing, self.user_time = [], False, False, 0
            self.registered = False
            self.logs = {'general': [], 'sourceControl': [{'message': 'preserve unselected channel',
                'severity': 'Message', 'time': 1, 'messageId': 'Custom'}]}
            self.rows = _committed_2024_capture_objects() if version == '2024.1' else _committed_capture_objects()
            if version == '2025.1':
                self.rows[sound_id].update({'classId': 65552, '@IsLoopingEnabled': False, '@IsLoopingInfinite': True})
            self.rows[bus_id]['classId'] = 1376272
            if failure == 'wrong-parent':
                sibling = next(row for row in self.rows.values() if row['name'] == 'Main Audio Bus')
                self.rows[bus_id]['parent'] = {key: sibling[key] for key in ('id', 'name')}

        def call(self, uri, args=None, options=None):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getInfo'):
                info = super().call(uri, args, options)
                info['version'].update(runtime.lifecycle.ready_result['version'])
                info['version']['displayName'] = 'v' + build
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
                return {'return': ['IsLoopingEnabled', 'IsLoopingInfinite'] if args.get('object') == sound_id
                    else ['Volume', 'BusChannelConfig'] if version == '2024.1' and args.get('object') == bus_id else ['Volume']}
            if uri.endswith('getPropertyInfo'):
                token = args['property']
                if version == '2024.1' and token == 'BusChannelConfig':
                    return {'name': token, 'type': 'int32', 'display': {'name': 'Bus Configuration'},
                        'default': 0, 'dependencies': [], 'supports': {},
                        'restriction': {'type': 'enum', 'values': [
                            {'value': 0, 'displayName': 'Same as parent'}, {'value': 12546, 'displayName': '2.0'}]}}
                return {'name': token, 'type': 'bool' if token.startswith('IsLooping') else 'Real64',
                    'display': {'name': token}, 'default': token == 'IsLoopingInfinite',
                    'dependencies': ([{'type': 'property', 'name': 'IsLoopingEnabled', 'action': 'Enable',
                        'values': [True]}] if token == 'IsLoopingInfinite' else []), 'supports': {}, 'restriction': {}}
            if uri.endswith('object.setProperty'):
                self.rows[args['object']]['@' + args['property']] = args['value']
                return {}
            if uri.endswith('transport.getList'):
                return {'list': [{'transport': 74, 'object': sound_id, 'gameObject': 1}] if self.transport else []}
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
                row = self.rows[bus_id]
                if version == '2024.1' and row['@BusChannelConfig'] == 0:
                    row = next(item for item in self.rows.values() if item['name'] == 'Master Audio Bus')
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
        env = _env(runtime.owned_root, version=version)
        set_gateway_config(env, wwise_version=version, project_modification_policy='ask_before_changes')
        env['WWISE_EVIDENCE_DIR'] = runtime.runner_environment['WWISE_EVIDENCE_DIR']
        def call(argv):
            code, payload = gateway.execute_gateway(['--state-dir', str(runtime.owned_root / 'setup-state'), *argv],
                env=env, client_factory=lambda _: client)
            receipts.append({'argv': list(argv), 'exit_code': code, 'payload': payload})
            assert code == 0, payload
            return payload
        return call
    monkeypatch.setattr(authoring_batch, 'fixture_gateway', factory)
    batch = authoring_batch.AuthoringBatchAdapter(owner=owner, repo_root=tmp_path, selected_nodeids=[nodeid])
    call = batch.node_gateway(nodeid)
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


def test_owned_2024_meter_public_flow_reaches_its_archived_final_category(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, version='2024.1')
    collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS' and record['version'] == '2024.1'
    category, = record['categories']
    assert category['category'] == 'profiler-meter-object-observation'
    assert category['status'] == category['business_outcome'] == 'PASS' and category['batch_finalization']
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    assert list(report['outcomes']) == ['profiler-meter-object-observation']
    obj = report['outcomes']['profiler-meter-object-observation']['evidence']['meters'][0]['object']
    assert obj['path'] == r'\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\Environmental\SFX\Guns'
    assert obj['volume_db'] == 0.0 and obj['related']['parent']['volume_db'] == 0.0
    assert obj['related']['parent']['object'] == {'id': '{ED2BCAC8-D7B6-4448-8900-439B557894F4}', 'name': 'SFX'}
    assert report['fixture_before']['sound']['output_bus']['id'] == '{06362E8D-5A32-497A-B063-3DA95963CE47}'
    assert report['fixture_after'] == report['fixture_before'] and report['cleanup']['complete'] is True
    assert report['fixture_before']['bus']['properties']['BusChannelConfig'] == 0
    assert next(row['bus_processing'] for row in report['setup'] if 'bus_processing' in row)['verification']['business_state_verified'] is True
    assert any(row['action'] == 'restore-bus-configuration' for row in report['cleanup']['receipts'])
    assert report['fixture_media']['proof']['sha256'] == report['fixture_media']['staging']['source']['sha256']
    assert report['cleanup']['capture_settings_prior_state_restored'] is False
    assert report['cleanup']['audition_media_prior_state_restored'] is False
    assert not client.transport and not client.registered and not batch.runtime.owned_root.exists()
    assert record['source']['hash_before'] == record['source']['hash_after']
    assert not any(uri.endswith(('setCursorTime', 'saveCapture', 'log.addItem', 'log.clear')) for uri, _, _ in client.calls)
    assert [(args['object'], args['property'], args['value']) for uri, args, _ in client.calls if uri.endswith('object.setProperty')] == [
        ('{06362E8D-5A32-497A-B063-3DA95963CE47}', 'BusChannelConfig', 12546),
        ('{06362E8D-5A32-497A-B063-3DA95963CE47}', 'BusChannelConfig', 0)]


def test_owned_2024_empty_meter_fails_final_acceptance_after_complete_cleanup(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, collect = _capture_host(owned_authoring, tmp_path, monkeypatch, version='2024.1', failure='empty-meter')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL' and record['version'] == '2024.1'
    category, = record['categories']
    assert category['category'] == 'profiler-meter-object-observation'
    assert category['status'] == category['business_outcome'] == 'FAIL'
    assert category['cleanup_complete'] is True and 'batch_finalization' not in category
    assert batch.lifecycle_result.quarantine_path and not client.transport and not client.registered
    archive = json.loads(Path(batch.observation_artifacts[batch.selected_nodeids[0]]['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())
    observation, = report['outcomes'].values()
    assert observation['outcome'] == 'FAIL' and 'missing from actual meter frame' in observation['error']['message']
    assert report['fixture_after'] == report['fixture_before']
    assert report['fixture_after']['bus']['properties']['BusChannelConfig'] == 0
    assert [args['value'] for uri, args, _ in client.calls if uri.endswith('object.setProperty')] == [12546, 0]
    assert any(row['action'] == 'restore-bus-configuration' for row in report['cleanup']['receipts'])
    assert record['source']['hash_before'] == record['source']['hash_after']
    cleanup = [uri for uri, _, _ in client.calls if uri.endswith(('profiler.stopCapture', 'transport.destroy', 'profiler.unregisterMeter'))]
    assert cleanup == ['ak.wwise.core.profiler.stopCapture', 'ak.wwise.core.transport.destroy', 'ak.wwise.core.profiler.unregisterMeter']


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
        message = 'Selected owned Authoring node is not available on the requested version' if version != '2025.1' else 'only its matching 2025'
        with pytest.raises(pytest.UsageError, match=message):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [row[0] for row in events] == ['construct', 'start', 'install']
