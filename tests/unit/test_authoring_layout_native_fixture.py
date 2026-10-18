"""Exercise future native fixture calls through the public Gateway with a fake host."""
from types import SimpleNamespace
import importlib
import json

import pytest

from tests.support.gateway_config import set_gateway_config
from tests.unit.test_authoring_layout_mutation_gateway import LayoutClient, URI
from tests.unit.test_waapi_gateway import gateway_env, waapi_gateway as gateway
from tests.unit.test_authoring_batch_adapter import owned_authoring, _install_public_gateway


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_owned_layout_registration_switch_fixture_uses_separate_verified_transactions(tmp_path, monkeypatch, version):
    for key in ('WWISE_LIVE', 'WWISE_DESTRUCTIVE', 'WWISE_AUTHORING_LIVE'):
        monkeypatch.setenv(key, '1')
    native = importlib.import_module('tests.destructive.test_authoring_ui_business_live')
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version, project_modification_policy='ask_before_changes')
    state = ['--state-dir', str(tmp_path / 'state')]
    client = LayoutClient(tmp_path, version=version)
    receipts = []
    def call(argv):
        code, payload = gateway.execute_gateway([*state, *argv], env=env, client_factory=lambda _: client)
        receipts.append((argv, code, payload))
        assert code == 0, payload
        return payload
    native.test_authoring_layout_owned_registration_and_switch(
        owned_authoring_layout_node=(SimpleNamespace(runtime=SimpleNamespace(version=version)), call))
    assert client.current == 'Designer'
    assert set(client.layouts) == {'Designer', 'Profiler'}
    executed = [row for row in client.calls if row[0] in {URI + name for name in ('setLayout', 'switchLayout', 'removeLayout')}]
    assert [row[0] for row in executed] == [URI + 'setLayout', URI + 'switchLayout', URI + 'switchLayout', URI + 'removeLayout']
    assert len({payload['transaction_id'] for argv, _, payload in receipts if argv[0] == 'preview-from-draft'}) == 4
    assert len([argv for argv, _, payload in receipts if argv[0] == 'verify' and payload['verification']['business_state_verified']]) == 4


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_owned_view_fixture_proves_creation_reuse_and_applicable_close(tmp_path, monkeypatch, version):
    for key in ('WWISE_LIVE', 'WWISE_DESTRUCTIVE', 'WWISE_AUTHORING_LIVE'):
        monkeypatch.setenv(key, '1')
    native = importlib.import_module('tests.destructive.test_authoring_ui_business_live')
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version, project_modification_policy='ask_before_changes')
    client = LayoutClient(tmp_path, version=version)
    def call(argv):
        code, payload = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), *argv], env=env, client_factory=lambda _: client)
        assert code == 0, payload
        return payload
    native.test_authoring_layout_owned_view_lifecycle(
        owned_authoring_layout_node=(SimpleNamespace(runtime=SimpleNamespace(version=version)), call),
        initial_position=('--initial-x', '17', '--initial-y', '29'))
    assert client.current == 'Designer'
    assert set(client.layouts) == {'Designer', 'Profiler'}
    creates = [args for uri, args, _ in client.calls if uri == URI + 'getOrCreateView']
    assert creates == [{'name': 'ProjectExplorer', 'posX': 17, 'posY': 29}, {'name': 'ProjectExplorer'}]
    assert len([uri for uri, _, _ in client.calls if uri == URI + 'closeView']) == (1 if version == '2025.1' else 0)


def _media_diagnostic_host(tmp_path, monkeypatch, *, names=None, fail_names=False):
    from copy import deepcopy
    for key in ('WWISE_LIVE', 'WWISE_DESTRUCTIVE', 'WWISE_AUTHORING_LIVE'):
        monkeypatch.setenv(key, '1')
    native = importlib.import_module('tests.destructive.test_authoring_ui_business_live')
    sessions = {
        '{9C02096E-8E29-4029-9D49-778F85015C87}': 'MIDI',
        '{1C5BA931-9550-4DC8-B1C7-13689B8AE813}': 'Minigun',
        '{F4B8069C-3C15-4157-B570-8A41AB2463C2}': 'Music',
    }
    rev = '{29975930-6548-4A1B-BEE0-7AA549180D4F}'
    class Client(LayoutClient):
        def __init__(self):
            super().__init__(tmp_path, version='2024.1')
            self.responses['ak.wwise.core.getInfo']['version'].update(minor=13, build=9056, schema=123)
            self.rows = {identity: {'id': identity, 'name': name, 'type': 'SoundcasterSession',
                'path': '\\Soundcaster Sessions\\' + name, 'classId': 1703952}
                for identity, name in sessions.items()}
            self.rows[rev] = {'id': rev, 'name': 'Chevrolet Camaro SS', 'type': 'SourcePlugin',
                'path': '\\Actor-Mixer Hierarchy\\Car Engine\\Chevrolet Camaro SS',
                'classId': 27267154, 'pluginName': 'CrankcaseAudio REV'}
        def call(self, uri, args=None, options=None):
            if uri.endswith('object.get'):
                self.calls.append((uri, args, options))
                ids = args.get('from', {}).get('id', [])
                if 'waql' in args:
                    ids = [value for value in self.rows if value in args['waql']]
                if ids:
                    return {'return': [deepcopy(self.rows[value]) for value in ids]}
                return {'return': [{'id': '{11111111-1111-1111-1111-111111111111}',
                    'name': 'Sandbox', 'type': 'Project', 'path': '\\',
                    'filePath': str(tmp_path / 'project' / 'Sandbox.wproj')}]}
            if uri.endswith('getPropertyAndReferenceNames'):
                self.calls.append((uri, args, options))
                if fail_names:
                    raise RuntimeError('diagnostic names read failed')
                # A fake-disclosed relevant name exercises selection, without
                # claiming that this field exists in native Soundcaster metadata.
                return {'return': names if names is not None else ['Color', 'CurrentStateList']}
            if uri.endswith('getPropertyInfo'):
                self.calls.append((uri, args, options))
                assert args['property'] == 'CurrentStateList'
                return {'default': None, 'supports': {'unlink': False}}
            if uri.endswith('getTypes'):
                self.calls.append((uri, args, options))
                return {'return': [{'name': 'CrankcaseAudio REV', 'type': 'Source', 'classId': 27267154}]}
            if uri == 'ak.wwise.core.log.get':
                self.calls.append((uri, args, options))
                return {'items': [{'message': 'Retained diagnostic warning', 'severity': 'Warning'}]}
            return super().call(uri, args, options)
    client = Client()
    project = tmp_path / 'project' / 'Sandbox.wproj'
    settings = project.with_name('Sandbox.testuser.wsettings')
    settings.write_text('<WwiseDocument Type="UserProjectSettings"><UserProjectSettingsInfo>'
        '<UserProjectSettings><PropertyList>'
        '<Property Name="RTPC\\GameParameterSimValue\\{F8E0D6FA-52B7-40EB-B9A1-AEB6B9FD6B86}" Type="Real64" Value="50"/>'
        '<Property Name="UnrelatedPrivateSetting" Type="string" Value="must-not-be-retained"/>'
        '</PropertyList></UserProjectSettings></UserProjectSettingsInfo></WwiseDocument>')
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version='2024.1', project_modification_policy='read_only')
    runtime = SimpleNamespace(version='2024.1', owned_root=tmp_path,
        sandbox=SimpleNamespace(sandbox_project=project))
    node_runtime = SimpleNamespace(runner_environment={'WWISE_EVIDENCE_DIR': str(tmp_path / 'native-evidence')})
    nodeid = 'tests/destructive/test_authoring_ui_business_live.py::test_authoring_2024_media_preservation_metadata_diagnostic'
    batch = SimpleNamespace(runtime=runtime, info=client.responses['ak.wwise.core.getInfo'],
        node_runtimes={nodeid: node_runtime})
    receipts = []
    def call(argv):
        code, payload = gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), *argv],
            env=env, client_factory=lambda _: client)
        receipts.append((argv, code, payload))
        assert code == 0, payload
        return payload
    return native, batch, call, client, receipts, tmp_path / 'native-evidence' / 'media-preservation-diagnostic.json'


def test_owned_media_diagnostic_uses_public_scoped_reads_and_whitelisted_settings(tmp_path, monkeypatch):
    native, batch, call, client, receipts, path = _media_diagnostic_host(tmp_path, monkeypatch)
    native.test_authoring_2024_media_preservation_metadata_diagnostic((batch, call))
    report = json.loads(path.read_text())
    assert report['business_preservation_verified'] is False
    assert report['coverage_credit'] == 'none; diagnostic observation only'
    assert report['complete'] is True
    assert [row['name'] for row in report['sessions']] == ['MIDI', 'Minigun', 'Music']
    assert all(row['field_names'] == ['Color', 'CurrentStateList'] for row in report['sessions'])
    assert len(report['field_details']) == 3
    for detail in report['field_details']:
        assert 'name' not in detail['metadata'] and 'type' not in detail['metadata']
        assert detail['metadata']['default'] is None
    assert len(report['settings']['before']['files'][0]['fields']) == 1
    assert report['settings']['before'] == report['settings']['after']
    assert 'must-not-be-retained' not in path.read_text()
    assert {args['channel'] for uri, args, _ in client.calls if uri == 'ak.wwise.core.log.get'} == {'projectLoad', 'general'}
    assert all(argv[0] in {'query-object', 'metadata', 'core-call'} for argv, _, _ in receipts)
    assert not any('moveMedia' in uri or 'set' in uri or 'create' in uri or 'capture' in uri for uri, _, _ in client.calls)


@pytest.mark.parametrize('failure', ['identity-drift', 'names-error', 'names-overflow', 'settings-link', 'settings-byte-bound'])
def test_owned_media_diagnostic_retains_incomplete_observations_without_retry(tmp_path, monkeypatch, failure):
    names = [f'OrdinaryField{i:03}' for i in range(300)] if failure == 'names-overflow' else None
    native, batch, call, client, receipts, path = _media_diagnostic_host(
        tmp_path, monkeypatch, names=names, fail_names=failure == 'names-error')
    settings = tmp_path / 'project' / 'Sandbox.testuser.wsettings'
    if failure == 'settings-link':
        settings.unlink()
        settings.symlink_to(tmp_path / 'private-settings')
        (tmp_path / 'private-settings').write_text('never-read-or-retain-this-private-content')
    if failure == 'settings-byte-bound':
        settings.write_bytes(b'x' * (1024 * 1024 + 1))
    if failure == 'identity-drift':
        client.rows['{9C02096E-8E29-4029-9D49-778F85015C87}']['name'] = 'Foreign session'
    with pytest.raises(AssertionError):
        native.test_authoring_2024_media_preservation_metadata_diagnostic((batch, call))
    report = json.loads(path.read_text())
    assert report['complete'] is False and report['errors']
    assert report['business_preservation_verified'] is False
    assert 'never-read-or-retain-this-private-content' not in path.read_text()
    if failure.startswith('names-'):
        assert report['settings']['after']['complete'] is True
        assert len([argv for argv, _, _ in receipts if argv[:2] == ['metadata', 'list']]) == (4 if failure == 'names-overflow' else 1)
    elif failure == 'identity-drift':
        assert len(receipts) == 1 and receipts[0][0][0] == 'query-object'
        assert report['settings']['after']['complete'] is True
    else:
        assert receipts == []
    assert not any(uri.endswith('getPropertyInfo') for uri, _, _ in client.calls)


def test_owned_media_diagnostic_caps_relevant_details_after_complete_names(tmp_path, monkeypatch):
    native, batch, call, client, receipts, path = _media_diagnostic_host(tmp_path, monkeypatch,
        names=['CurrentStateList', 'CurrentStateOther', 'CurrentStateThird'])
    # This case exercises the cap, rather than a metadata-shape expectation.
    original = client.call
    def call_native(uri, args=None, options=None):
        if uri.endswith('getPropertyInfo'):
            client.calls.append((uri, args, options))
            return {'default': None}
        return original(uri, args, options)
    client.call = call_native
    native.test_authoring_2024_media_preservation_metadata_diagnostic((batch, call))
    report = json.loads(path.read_text())
    assert report['complete'] is True and report['detail_limit_reached'] is True
    assert len(report['field_details']) == 6
    assert len([row for row in client.calls if row[0].endswith('getPropertyInfo')]) == 6
    assert all(row['names_complete'] and len(row['field_names']) == 3 for row in report['sessions'])


def test_media_diagnostic_owned_batch_category_cannot_grant_business_credit(owned_authoring, tmp_path, monkeypatch):
    from tests.destructive.support import authoring_batch
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle
    from wwise_waapi.headless import CleanupReport, HeadlessLifecycle
    nodeid = 'tests/destructive/test_authoring_ui_business_live.py::test_authoring_2024_media_preservation_metadata_diagnostic'
    def shutdown(process, sandbox, **kwargs):
        process.process = None
        process.cleanup_report = CleanupReport(launch_pid=1234, wine_prefix=None, process_exited=True)
        sandbox.metadata.process_cleanup_result = 'cleaned'
        sandbox.metadata.process_cleanup_details = {'residual_processes': []}
    monkeypatch.setattr(lifecycle, 'shutdown_sandboxed_wwise', shutdown)
    monkeypatch.setattr(authoring_batch, 'wait_for_port_release', lambda *_: None)
    monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(12345, 'fake pytest process')])
    target = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    _install_public_gateway(monkeypatch, owned_authoring)
    batch = authoring_batch.AuthoringBatchAdapter(owner=owned_authoring, repo_root=tmp_path, selected_nodeids=[nodeid])
    batch.node_gateway(nodeid)
    item = SimpleNamespace(nodeid=nodeid, _waapi_phase_reports={'setup': 'passed', 'call': 'passed'})
    batch.prepare_stop([item])
    item._waapi_phase_reports['teardown'] = 'passed'
    assert batch.finalize([item], terminal=True)['outcome'] == 'PASS'
    rows = [json.loads(line)['categories'][0] for line in target.read_text().splitlines()]
    assert all(row['category'] == 'media-preservation-diagnostic' and row['status'] == 'blocked' for row in rows)
    assert all(row['business_preservation_verified'] is False and row['coverage_credit'] == 'none; diagnostic observation only' for row in rows)


@pytest.mark.parametrize('version,extra_node', [('2024.1', False), ('2025.1', False), ('2024.1', True)])
def test_media_diagnostic_owner_selects_only_one_matching_2024_node(tmp_path, monkeypatch, version, extra_node):
    from tests.destructive.support import authoring_batch
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    monkeypatch.setenv('WWISE_VERSION', version)
    nodeid = 'tests/destructive/test_authoring_ui_business_live.py::test_authoring_2024_media_preservation_metadata_diagnostic'
    config = _config(tmp_path)
    config.args = [nodeid, *([NODE] if extra_node else [])]
    items = [SimpleNamespace(nodeid=value) for value in config.args]
    if version == '2024.1' and not extra_node:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [kind for kind, _ in events] == ['construct', 'start', 'install']
        assert events[0][1]['host_kind'] == 'wwise-authoring'
    else:
        with pytest.raises(pytest.UsageError):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert events == []


def _soundcaster_image_owner(owned_authoring, tmp_path, monkeypatch):
    """Use the real node/archive/category owner with only its native boundary fake."""
    import base64
    from dataclasses import replace
    from pathlib import Path
    import shutil
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.sandbox_fixture import hash_project
    native, _, _, client, _, _ = _media_diagnostic_host(tmp_path, monkeypatch)
    owner = owned_authoring
    runtime = owner.runtime
    for directory in ('Soundcaster Sessions', 'States', 'Switches'):
        shutil.copytree(Path(__file__).resolve().parents[1] / '_org/2024.1' / directory,
                        runtime.sandbox.source_root / directory)
        shutil.copytree(runtime.sandbox.source_root / directory, runtime.sandbox.sandbox_path / directory)
    proof = hash_project(runtime.sandbox.source_root, preferred_strategy='full')
    runtime.sandbox.metadata.source_hash = proof
    runtime.sandbox.metadata.wwise_version = '2024.1'
    owner.version = '2024.1'
    owner.runtime = replace(runtime, version='2024.1', source_hash_before=proof)
    owner.runtime.lifecycle.ready_result = client.responses['ak.wwise.core.getInfo']
    client.responses['ak.wwise.core.getProjectInfo']['path'] = str(runtime.sandbox.sandbox_project)
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=')
    # Retain the valid image; a CRC-valid ancillary chunk forces execute's
    # existing 24KiB digest projection without another image dependency.
    import struct
    import zlib
    chunk = b'tEXt' + b'Comment\x00' + b'x' * (24 * 1024)
    png = png[:-12] + struct.pack('>I', len(chunk) - 4) + chunk + struct.pack('>I', zlib.crc32(chunk)) + png[-12:]
    offset = 8
    while offset < len(png):
        length = struct.unpack('>I', png[offset:offset + 4])[0]
        payload = png[offset + 4:offset + 8 + length]
        assert zlib.crc32(payload) == struct.unpack('>I', png[offset + 8 + length:offset + 12 + length])[0]
        offset += length + 12
    assert offset == len(png)
    client.responses[URI + 'getViewTypes']['viewTypes'].append(
        {'viewName': 'DisclosedSoundcasterView', 'viewDisplayName': 'Soundcaster'})
    client.views['Designer'] = [{'viewName': 'DisclosedSoundcasterView',
        'viewID': '{22222222-2222-2222-2222-222222222222}',
        'viewDisplayName': 'Soundcaster', 'viewIsDocked': False}]
    client.responses.update({'ak.wwise.ui.commands.getCommands': {'commands': ['Inspect']},
        'ak.wwise.ui.commands.execute': {},
        'ak.wwise.ui.captureScreen': {'contentType': 'image/png', 'contentBase64': base64.b64encode(png).decode()}})
    def factory(*, skill_source, runtime, version, receipts):
        env = gateway_env(runtime.owned_root)
        env['WWISE_EVIDENCE_DIR'] = runtime.runner_environment['WWISE_EVIDENCE_DIR']
        def call(argv):
            code, payload = gateway.execute_gateway(['--state-dir', str(runtime.owned_root / 'setup-state'), *argv],
                env=env, client_factory=lambda _: client)
            receipts.append({'argv': list(argv), 'exit_code': code, 'payload': payload})
            assert code == 0, payload
            return payload
        return call
    monkeypatch.setattr(authoring_batch, 'fixture_gateway', factory)
    nodeid = ('tests/destructive/test_authoring_ui_business_live.py::'
              'test_authoring_2024_soundcaster_frontend_image_diagnostic')
    batch = authoring_batch.AuthoringBatchAdapter(owner=owner, repo_root=tmp_path, selected_nodeids=[nodeid])
    call = batch.node_gateway(nodeid)
    return native, batch, call, client, png, nodeid


def test_soundcaster_images_are_archived_without_business_preservation_credit(owned_authoring, tmp_path, monkeypatch):
    from pathlib import Path
    from tests.destructive.support import authoring_batch
    native, batch, call, client, png, nodeid = _soundcaster_image_owner(owned_authoring, tmp_path, monkeypatch)
    native.test_authoring_2024_soundcaster_frontend_image_diagnostic((batch, call))
    report_path = Path(batch.node_runtimes[nodeid].runner_environment['WWISE_EVIDENCE_DIR']) / 'soundcaster-frontend-diagnostic.json'
    report = json.loads(report_path.read_text())
    assert report['complete'] is True
    assert report['runtime_session_values_observed'] is False and report['business_preservation_verified'] is False
    assert report['coverage_credit'] == 'none; diagnostic observation only'
    assert report['activation_request'] == 'Inspect one exact Minigun object; Soundcaster session loading is unproven'
    assert report['source']['binding_counts'] == {'RTPC': 72, 'State': 16, 'Switch': 12}
    assert [row['name'] for row in report['sessions']] == ['Minigun']
    for row in report['sessions']:
        assert (report_path.parent / row['image']['path']).read_bytes() == png
        assert row['command']['state'] == row['capture']['state'] == 'result_schema_checked'
        assert row['view_locator']['layout_name'] == 'Designer'
        assert row['view_locator']['instance']['viewIsDocked'] is False
        assert row['view_locator']['instance']['viewName'] == 'DisclosedSoundcasterView'
        assert row['view_locator']['command_transaction_id'] == row['command']['transaction_id']
        assert row['view_locator']['session_id'] == row['id']
    writes = [(uri, args) for uri, args, _ in client.calls if uri in
        {'ak.wwise.ui.commands.execute', 'ak.wwise.ui.captureScreen'}]
    assert writes == [('ak.wwise.ui.commands.execute', {'command': 'Inspect', 'objects': ['{1C5BA931-9550-4DC8-B1C7-13689B8AE813}']}),
        ('ak.wwise.ui.captureScreen', {'viewName': 'DisclosedSoundcasterView'})]
    receipts = batch.receipts[nodeid]
    captures = [row for row in receipts if row['argv'][0] == 'execute'
        and row['payload']['stdout_projection']['full_dispatch_result_in_stdout'] is False]
    assert len(captures) == 1
    image_txs = {row['capture']['transaction_id'] for row in report['sessions']}
    reads = [row for row in receipts if row['argv'][0] == 'transaction-show'
             and row['argv'][1] in image_txs and row['payload']['state'] == 'result_schema_checked']
    assert len(reads) == 1 and {row['argv'][1] for row in reads} == image_txs
    assert len({row['payload']['transaction_id'] for row in receipts if row['argv'][0] == 'preview-from-draft'}) == 2
    assert all(row['payload']['verification']['business_state_verified'] is False
               for row in receipts if row['argv'][0] == 'verify')
    target = tmp_path / 'image-category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle
    from wwise_waapi.headless import CleanupReport, HeadlessLifecycle
    def shutdown(process, sandbox, **kwargs):
        process.process = None
        process.cleanup_report = CleanupReport(launch_pid=1234, wine_prefix=None, process_exited=True)
        sandbox.metadata.process_cleanup_result = 'cleaned'
        sandbox.metadata.process_cleanup_details = {'residual_processes': []}
    monkeypatch.setattr(lifecycle, 'shutdown_sandboxed_wwise', shutdown)
    monkeypatch.setattr(authoring_batch, 'wait_for_port_release', lambda *_: None)
    monkeypatch.setattr(HeadlessLifecycle, '_process_rows', lambda *_, **__: [(12345, 'fake pytest process')])
    item = SimpleNamespace(nodeid=nodeid, _waapi_phase_reports={'setup': 'passed', 'call': 'passed'})
    batch.prepare_stop([item])
    item._waapi_phase_reports['teardown'] = 'passed'
    assert batch.finalize([item], terminal=True)['outcome'] == 'PASS'
    assert not batch.runtime.sandbox.sandbox_path.exists()
    archived = batch.observation_artifacts[nodeid]
    archive = json.loads(Path(archived['path']).read_text())
    root = Path(archive['artifacts']['native-evidence']['path'])
    assert json.loads((root / report_path.name).read_text()) == report
    assert all((root / row['image']['path']).read_bytes() == png for row in report['sessions'])
    final = json.loads(target.read_text().splitlines()[-1])
    assert final['invocation']['phase'] == 'final' and final['invocation']['outcome'] == 'PASS'
    categories = [json.loads(line)['categories'][0] for line in target.read_text().splitlines()]
    assert categories and all(row['category'] == 'soundcaster-frontend-diagnostic' and row['status'] == 'blocked'
        and row['business_preservation_verified'] is False for row in categories)


def test_soundcaster_wrong_selected_identity_stops_before_all_ui_writes(owned_authoring, tmp_path, monkeypatch):
    from pathlib import Path
    native, batch, call, client, _, nodeid = _soundcaster_image_owner(owned_authoring, tmp_path, monkeypatch)
    selected = '{1C5BA931-9550-4DC8-B1C7-13689B8AE813}'
    client.rows[selected]['name'] = 'Different session'
    with pytest.raises(AssertionError, match='identity/class changed'):
        native.test_authoring_2024_soundcaster_frontend_image_diagnostic((batch, call))
    destination = Path(batch.node_runtimes[nodeid].runner_environment['WWISE_EVIDENCE_DIR'])
    report = json.loads((destination / 'soundcaster-frontend-diagnostic.json').read_text())
    assert report['complete'] is False and report['errors']
    assert report['business_preservation_verified'] is False and report['runtime_session_values_observed'] is False
    assert not list(destination.glob('*.png'))
    assert not any(uri.startswith('ak.wwise.ui.commands.') or uri == 'ak.wwise.ui.captureScreen'
                   for uri, _, _ in client.calls)
    assert [row['argv'][0] for row in batch.receipts[nodeid]][2:] == ['query-object']
    target = tmp_path / 'failed-image-category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    item = SimpleNamespace(nodeid=nodeid, _waapi_phase_reports={'setup': 'passed', 'call': 'failed'})
    batch.prepare_stop([item])
    rows = [json.loads(line)['categories'][0] for line in target.read_text().splitlines()]
    assert rows and all(row['status'] == 'FAIL' and row['business_preservation_verified'] is False for row in rows)


@pytest.mark.parametrize('instance_count', [0, 2], ids=['absent', 'ambiguous'])
def test_soundcaster_missing_unique_view_retains_observation_without_image(owned_authoring, tmp_path, monkeypatch, instance_count):
    from copy import deepcopy
    from pathlib import Path
    native, batch, call, client, _, nodeid = _soundcaster_image_owner(owned_authoring, tmp_path, monkeypatch)
    view = deepcopy(client.views['Designer'][0])
    client.views['Designer'] = [] if instance_count == 0 else [view, {**view,
        'viewID': '{33333333-3333-3333-3333-333333333333}'}]
    with pytest.raises(AssertionError, match='No unique actual Soundcaster instance'):
        native.test_authoring_2024_soundcaster_frontend_image_diagnostic((batch, call))
    destination = Path(batch.node_runtimes[nodeid].runner_environment['WWISE_EVIDENCE_DIR'])
    report = json.loads((destination / 'soundcaster-frontend-diagnostic.json').read_text())
    assert report['complete'] is False and report['business_preservation_verified'] is False
    assert report['runtime_session_values_observed'] is False
    observed = report['sessions'][0]['view_locator']
    assert observed['complete'] is False and len(observed['instances']) == instance_count
    assert observed['session_id'] == '{1C5BA931-9550-4DC8-B1C7-13689B8AE813}'
    assert not list(destination.glob('*.png'))
    writes = [(uri, args) for uri, args, _ in client.calls if uri in
        {'ak.wwise.ui.commands.execute', 'ak.wwise.ui.captureScreen'}]
    assert writes == [('ak.wwise.ui.commands.execute', {'command': 'Inspect',
        'objects': ['{1C5BA931-9550-4DC8-B1C7-13689B8AE813}']})]
    assert len([row for row in batch.receipts[nodeid] if row['argv'][0] == 'preview-from-draft']) == 1
