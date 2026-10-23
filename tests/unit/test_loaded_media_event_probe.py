"""Real Gateway/collector/final writer; only external Wwise is substituted."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from tests.unit.test_authoring_batch_adapter import owned_authoring
from tests.unit.test_profiler_capture_native_fixture import _finish
from tests.unit.test_runtime_business_gateway import _RuntimeControlDraftClient, _env, gateway
from tests.support.gateway_config import set_gateway_config


def _host(owner, tmp_path, monkeypatch, *, failure=None, count=1):
    from tests.destructive.support import authoring_batch, loaded_media_probe as probe
    from tests.destructive.support.sandbox_fixture import hash_project
    runtime = owner.runtime
    runtime.lifecycle.ready_result['version']['displayName'] = 'v2025.1.7.9143'
    fixture = Path(__file__).resolve().parents[1] / '_org/2025.1'
    files = ('Events/Default Work Unit.wwu', 'Containers/Default Work Unit.wwu',
        'Originals/SFX/WAAPI Skill Integration V2/audit_close.wav')
    rows = {}
    wanted = {'{0112B248-632B-4DF4-BC80-4CD8270250BA}', '{8257E0BC-513A-4DFA-B85C-22C6997A5B19}',
        '{67C60B1B-CA2D-4DC5-B149-F773AE2C95A3}', '{98D57DD7-9AB1-41D1-8178-817BE1CA061E}'}
    for relative in files:
        for root in (runtime.sandbox.source_root, runtime.sandbox.sandbox_path):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fixture / relative, target)
        if not relative.endswith('.wwu'):
            continue
        root = ET.parse(fixture / relative).getroot()
        parents = {child: parent for parent in root.iter() for child in parent}
        for node in root.iter():
            if node.get('ID') not in wanted or node.tag not in ('Event', 'Action', 'Sound', 'AudioFileSource'):
                continue
            chain, current = [], node
            while current is not root:
                if current.get('Name') is not None:
                    chain.append(current.get('Name') or 'Play')
                current = parents[current]
            row = {'id': node.get('ID'), 'name': node.get('Name') or 'Play', 'type': node.tag,
                'path': '\\' + '\\'.join([relative.split('/')[0], *reversed(chain)])}
            parent = parents[parents[node]]
            row['parent'] = {'id': parent.get('ID'), 'name': parent.get('Name')}
            if node.tag == 'Event':
                row['childrenCount'] = len(node.findall('ChildrenList/Action'))
            elif node.tag == 'Action':
                row['ActionType'] = int(node.find("PropertyList/Property[@Name='ActionType']").get('Value'))
                target = node.find("ReferenceList/Reference[@Name='Target']/ObjectRef")
                row['Target'] = {'id': target.get('ID'), 'name': target.get('Name')}
            elif node.tag == 'Sound':
                active = node.find('ActiveSourceList/ActiveSource')
                row['activeSource'] = {'id': active.get('ID'), 'name': active.get('Name')}
            else:
                row['originalFilePath'] = str(runtime.sandbox.sandbox_path / files[-1])
            rows[row['id']] = row
    proof = hash_project(runtime.sandbox.source_root, preferred_strategy='full')
    runtime.sandbox.metadata.source_hash = proof
    owner.runtime = runtime = replace(runtime, source_hash_before=proof)
    if failure == 'wrong-target':
        rows['{8257E0BC-513A-4DFA-B85C-22C6997A5B19}']['Target']['id'] = '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}'
    if failure == 'bad-media':
        with (runtime.sandbox.sandbox_path / files[-1]).open('ab') as changed:
            changed.write(b'changed owned media')

    class Client(_RuntimeControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path, version='2025.1')
            self.calls = []

        def call(self, uri, args=None, options=None):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getInfo'):
                return {**super().call(uri, args, options), **deepcopy(runtime.lifecycle.ready_result)}
            if uri.endswith('getProjectInfo'):
                return {'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'SampleProject',
                    'path': str(runtime.sandbox.sandbox_project), 'isDirty': False}
            if uri.endswith('object.get'):
                identities = args.get('from', {}).get('id', [])
                if 'waql' in args:
                    identities = [identity for identity in rows if identity in args['waql']]
                return {'return': [{key: deepcopy(row[key]) for key in options['return'] if key in row}
                    for identity in identities if (row := rows.get(identity))]}
            if uri.endswith('profiler.enableProfilerData'):
                if failure == 'cleanup' and args['dataTypes'] == [{'dataType': 'loadedMedia', 'enable': False}]:
                    raise RuntimeError('external disable uncertainty')
                return {}
            if uri.endswith(('profiler.startCapture', 'profiler.stopCapture')):
                return {'return': 1500}
            if uri.endswith(('transport.useOriginals', 'transport.prepare')):
                return {}
            if uri.endswith('profiler.getCursorTime'):
                return {'return': -1 if failure == 'unavailable' else 1500}
            if uri.endswith('profiler.getLoadedMedia'):
                # Deliberately unrelated identity: this is a capture-level READ,
                # not a claim that Event preparation loaded our selected Sound.
                return {'return': [] if failure == 'empty' else [{'mediaId': index + 17,
                    'fileName': 'unrelated-media-' + str(index) + '.wem', 'format': 'PCM',
                    'size': 1024, 'soundBank': 'Some Bank'} for index in range(count)]}
            return super().call(uri, args, options)

    client = Client()
    def factory(*, skill_source, runtime, version, receipts):
        env = _env(runtime.owned_root, version=version)
        set_gateway_config(env, wwise_version=version, project_modification_policy='ask_before_changes')
        env['WWISE_EVIDENCE_DIR'] = runtime.runner_environment['WWISE_EVIDENCE_DIR']
        def call(argv):
            code, payload = gateway.execute_gateway(['--state-dir', str(runtime.owned_root / 'probe-state'), *argv],
                env=env, client_factory=lambda _: client)
            receipts.append({'argv': list(argv), 'exit_code': code, 'payload': payload})
            assert code == 0, json.dumps(payload, ensure_ascii=False)
            return payload
        return call
    monkeypatch.setattr(authoring_batch, 'fixture_gateway', factory)
    monkeypatch.setattr(probe.time, 'sleep', lambda _: None)
    batch = authoring_batch.AuthoringBatchAdapter(owner=owner, repo_root=tmp_path, selected_nodeids=[probe.NODEID])
    return batch, batch.node_gateway(probe.NODEID), client, probe


def _archived(batch):
    descriptor = batch.observation_artifacts[batch.selected_nodeids[0]]
    archive = json.loads(Path(descriptor['path']).read_text())
    return json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'profiler-capture.json').read_text())


def test_loaded_event_probe_reaches_final_writer_without_claiming_prepare_effect(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, probe = _host(owned_authoring, tmp_path, monkeypatch)
    probe.collect_loaded_event_probe(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS'
    row, = record['categories']
    assert row['category'] == 'profiler-loaded-media-observation' and row['status'] == 'PASS'
    assert row['attribution_scope'] == 'capture' and row['owned_identity_observed'] is False
    assert row['preparation_or_streaming_control_effect_verified'] is False
    report = _archived(batch)
    assert report['public_call_count'] == len(batch.receipts[probe.NODEID]) <= 96
    assert report['total_reply_bytes'] == sum(len(json.dumps(receipt['payload'], ensure_ascii=False).encode())
        for receipt in batch.receipts[probe.NODEID])
    assert report['cleanup']['complete'] and report['fixture_before'] == report['fixture_after']
    assert report['preparation']['verification']['status'] == 'result_schema_checked'
    assert report['preparation']['verification']['business_state_verified'] is False
    assert report['preparation']['sdk_prepare_event_equivalence_verified'] is False
    calls = [uri for uri, _, _ in client.calls]
    assert calls.count('ak.wwise.core.transport.prepare') == calls.count('ak.wwise.core.profiler.getLoadedMedia') == 1
    assert calls.index('ak.wwise.core.profiler.enableProfilerData') < calls.index('ak.wwise.core.profiler.startCapture') < calls.index('ak.wwise.core.transport.prepare')
    assert [args for uri, args, _ in client.calls if uri.endswith('transport.prepare')] == [
        {'object': '{0112B248-632B-4DF4-BC80-4CD8270250BA}'}]
    assert not any(uri.startswith('ak.soundengine.') or uri.endswith(('object.setProperty', 'object.create',
        'transport.create', 'transport.executeAction')) for uri in calls)
    assert not batch.runtime.owned_root.exists()


@pytest.mark.parametrize('failure,count', [('empty', 1), ('cleanup', 1), ('partial', 1000), ('unavailable', 1)])
def test_loaded_probe_retains_empty_partial_and_uncertain_cleanup_in_final_writer(
        owned_authoring, tmp_path, monkeypatch, failure, count):
    batch, call, client, probe = _host(owned_authoring, tmp_path, monkeypatch, failure=failure, count=count)
    with pytest.raises(AssertionError):
        probe.collect_loaded_event_probe(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    assert final['outcome'] == 'FAIL' and batch.lifecycle_result.quarantine_path
    assert not batch.batch_seal_path.exists()
    row, = record['categories']
    assert row['status'] == 'blocked'
    report = _archived(batch)
    assert report['public_call_count'] == len(batch.receipts[probe.NODEID]) <= 96
    assert report['fixture_before'] == report['fixture_after']
    assert report['cleanup']['complete'] is (failure != 'cleanup')
    assert sum(uri.endswith('profiler.getLoadedMedia') for uri, _, _ in client.calls) == (0 if failure == 'unavailable' else 1)
    if failure == 'unavailable':
        assert report['capture_position']['available'] is False and report['errors']
    else:
        evidence = report['outcomes'][probe.OUTCOME]['evidence']
        assert evidence['nonempty'] is (failure != 'empty')
        assert evidence['complete'] is (failure != 'partial')
        assert evidence['observation_status'] == ('BLOCKED' if failure == 'partial' else 'PASS')
        assert row['business_outcome'] == ('PASS' if failure == 'cleanup' else 'BLOCKED')
        if failure == 'partial':
            assert len(evidence['pages']) == 8 and evidence['pages'][-1]['next_command']
        if failure == 'cleanup':
            assert report['cleanup']['errors'][0]['action'] == 'disable-loaded-media'
    disable = [args for uri, args, _ in client.calls if uri.endswith('enableProfilerData') and not args['dataTypes'][0]['enable']]
    assert len(disable) == 1  # Cleanup uncertainty never triggers native replay.


def test_loaded_probe_consumes_cached_pages_with_one_native_read(owned_authoring, tmp_path, monkeypatch):
    batch, call, client, probe = _host(owned_authoring, tmp_path, monkeypatch, count=64)
    probe.collect_loaded_event_probe(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    assert final['outcome'] == 'PASS' and record['categories'][0]['status'] == 'PASS'
    report = _archived(batch)
    evidence = report['outcomes'][probe.OUTCOME]['evidence']
    assert len(evidence['pages']) > 1 and evidence['complete']
    assert sum(len(page['return']) for page in evidence['pages']) == 64
    assert len({page['snapshot_sha256'] for page in evidence['pages']}) == 1
    assert report['public_call_count'] == len(batch.receipts[probe.NODEID]) <= 96
    assert sum(uri.endswith('profiler.getLoadedMedia') for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize('failure', ['wrong-target', 'bad-media'])
def test_loaded_probe_requires_fixture_identity_and_bytes_before_any_control(owned_authoring, tmp_path, monkeypatch, failure):
    batch, call, client, probe = _host(owned_authoring, tmp_path, monkeypatch, failure=failure)
    with pytest.raises(AssertionError):
        probe.collect_loaded_event_probe(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    report = _archived(batch)
    assert final['outcome'] == 'FAIL' and record['categories'][0]['status'] == 'blocked'
    assert report['errors'] and report['outcomes'][probe.OUTCOME]['outcome'] == 'BLOCKED'
    assert not any('.transport.' in uri or '.profiler.' in uri for uri, _, _ in client.calls)


@pytest.mark.parametrize('version,extra', [('2021.1', False), ('2022.1', False), ('2023.1', False),
    ('2024.1', False), ('2025.1', True), ('2025.1', False)])
def test_loaded_probe_owner_accepts_only_its_single_2025_node(tmp_path, monkeypatch, version, extra):
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.loaded_media_probe import NODEID
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    monkeypatch.setenv('WWISE_VERSION', version)
    config = _config(tmp_path)
    config.args = [NODEID, *([NODE] if extra else [])]
    items = [SimpleNamespace(nodeid=name) for name in config.args]
    if version != '2025.1' or extra:
        with pytest.raises(pytest.UsageError, match='not available|exact single 2025 node'):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [row[0] for row in events] == ['construct', 'start', 'install']
        assert events[0][1]['live_environment']['AK_AUTOMATION_MODE'] == '1'
