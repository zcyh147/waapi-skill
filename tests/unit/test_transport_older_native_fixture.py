"""Eight older observations through the real Gateway and final archive writer.

Only external Wwise and its media are substituted. No native semantics credit.
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
    from tests.destructive.support import transport_semantics as module
    from tests.destructive.support.transport_semantics import OLDER_NODEID, collect_older_transport_semantics
    version = owner.runtime.version
    fixtures = Path(__file__).resolve().parents[1] / '_org'
    project = ET.parse(fixtures/version/'SampleProject.wproj').getroot()
    platform, = [node for node in project.iter('Platform') if node.get('Name') == 'Mac']
    language, = [node for node in project.iter('Language') if node.get('Name') == 'SFX']
    view_rows = {node.get('ID'): {'id':node.get('ID'),'name':node.get('Name'),'type':kind,
        'path':'\\'+kind+'s\\'+node.get('Name')} for kind,node in (('Platform',platform),('Language',language))}
    language_ref = {'id':language.get('ID'), 'name':'SFX'}
    if version != '2022.1':
        import hashlib
        from wwise_waapi.native_catalog import load_native_catalog
        installed = tmp_path/'Audiokinetic'
        build = load_native_catalog(version,'wwise-authoring')['provenance']['build']
        source_root = installed/('SampleProject'+build)/'SampleProject'
        monkeypatch.setattr(module,'INSTALLED_SAMPLE_ROOT',installed)
        media_hashes = {}
    files = [('Default Work Unit.wwu', ('RFL_Tail', 'Rifle_Mechanical'))] if version == '2022.1' else [
        ('Minigun.wwu', ('MnGn_Barrel_Loop',)), ('Car Engine.wwu', ('Outside_Idle_1000',))]
    rows, initial_loops = {}, {}
    for filename, names in files:
        root = ET.parse(fixtures / version / 'Actor-Mixer Hierarchy' / filename).getroot()
        parents = {child: parent for parent in root.iter() for child in parent}
        for name in names:
            sound, = [node for node in root.iter('Sound') if node.get('Name') == name]
            source = sound.find('ChildrenList/AudioFileSource')
            assert sound.find('ActiveSourceList/ActiveSource').get('ID') == source.get('ID')
            relative = Path('Originals/SFX') / Path(source.findtext('AudioFile').replace('\\', '/'))
            media = owner.runtime.sandbox.sandbox_path / relative
            media.parent.mkdir(parents=True, exist_ok=True)
            # Substitute media without relying on a developer's installed app.
            pcm = (fixtures / '2022.1/Originals/SFX/WAAPI Skill Integration V2/audit_tail.wav').read_bytes()
            if version == '2022.1':
                media.write_bytes(pcm)
            else:
                installed_media = source_root/relative
                installed_media.parent.mkdir(parents=True,exist_ok=True)
                installed_media.write_bytes(pcm)
                media_hashes[str(relative)] = hashlib.sha256(pcm).hexdigest()
            ancestry, node = [], sound
            while node is not root:
                if node.get('Name'):
                    ancestry.append(node.get('Name'))
                node = parents[node]
            path = '\\Actor-Mixer Hierarchy\\' + '\\'.join(reversed(ancestry))
            loop = sound.find("PropertyList/Property[@Name='IsLoopingEnabled']")
            enabled = loop is not None and loop.get('Value') == 'True'
            parent = parents[sound]
            while parent.get('ID') is None:
                parent = parents[parent]
            initial_loops[sound.get('ID')] = enabled
            rows[sound.get('ID')] = {'id': sound.get('ID'), 'name': name, 'type': 'Sound', 'path': path,
                'classId': 65552, '@IsLoopingEnabled': enabled, '@IsLoopingInfinite': True,
                'activeSource': {'id': source.get('ID'), 'name': source.get('Name')},
                'parent': {'id':parent.get('ID')}, 'originalWavFilePath':str(media), 'audioSource:language':language_ref}
            rows[source.get('ID')] = {'id': source.get('ID'), 'name': source.get('Name'),
                'type': 'AudioFileSource', 'path': path + '\\' + source.get('Name'), 'classId':16,
                'parent': {'id':sound.get('ID')}, 'originalWavFilePath':str(media), 'audioSource:language':language_ref}
    if version != '2022.1':
        monkeypatch.setattr(module,'OLDER_MEDIA_HASHES',media_hashes)
        owner.runtime.io_root.mkdir(parents=True,exist_ok=True)
        module.stage_owned_older_transport_media(owner.runtime.sandbox,owner.runtime.io_root,version=version)

    class Client(_RuntimeControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path, version=version)
            self.project_file = owner.runtime.sandbox.sandbox_project
            self.rows, self.calls, self.transports, self.states = rows, [], {}, {}
            self.rows.update(view_rows)
            self.originals, self.prepared, self.all_actions = False, set(), []
            self.rows['{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'] = {
                'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'SampleProject',
                'type': 'Project', 'path': '\\', 'filePath': str(self.project_file)}

        def call(self, uri, args=None, options=None):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getInfo'):
                return deepcopy(owner.runtime.lifecycle.ready_result)
            if uri.endswith('object.get'):
                ids = args.get('from', {}).get('id', [])
                query = args.get('waql','')
                if query.startswith('from type Project'):
                    ids = ['{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}']
                elif query.startswith('from type Platform'):
                    ids = [platform.get('ID')]
                elif query.startswith('from type Language'):
                    ids = [language.get('ID')]
                elif 'select children' in query:
                    ids = [key for key,row in self.rows.items() if row['type'] == 'AudioFileSource' and row['parent']['id'] in query]
                elif 'waql' in args:
                    ids = [identity for identity in self.rows if identity in args['waql']]
                return {'return': [{key: deepcopy(row.get(key, row.get('@' + key)))
                    for key in options.get('return', ['id','name','type','path'])
                    if key in row or '@' + key in row}
                    for identity in ids if (row := self.rows.get(identity))]}
            if uri.endswith('object.getTypes'):
                return {'return':[{'classId':65552,'name':'Sound','type':'WObject'},
                    {'classId':16,'name':'AudioSource','type':'WObject'}]}
            if uri.endswith('object.getPropertyAndReferenceNames'):
                return {'return': ['IsLoopingEnabled', 'IsLoopingInfinite']}
            if uri.endswith('object.getPropertyInfo'):
                return {'name': args['property'], 'type': 'bool', 'display': {'name': args['property']},
                    'default': args['property'] == 'IsLoopingInfinite', 'dependencies': [], 'supports': {}, 'restriction': {}}
            if uri.endswith('object.setProperty'):
                self.rows[args['object']]['@' + args['property']] = args['value']
                return {}
            if uri.endswith('transport.useOriginals'):
                assert version in ('2023.1', '2024.1')
                self.originals = args['enable']
                return {}
            if uri.endswith('transport.prepare'):
                assert version == '2022.1'
                if failure == 'prepare':
                    raise RuntimeError('fake preparation unavailable')
                self.prepared.add(args['object'])
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
                if failure == 'witness' and args['transport'] == 91 and any(
                        old_uri.endswith('transport.executeAction') and old_args['action'] == 'playDirectly'
                        for old_uri,old_args,_ in self.calls):
                    raise RuntimeError('fake unselected poststate unavailable')
                return {'state': self.states[args['transport']]}
            if uri.endswith('transport.executeAction'):
                action = args['action']
                ids = [args['transport']] if 'transport' in args else list(self.transports)
                if 'transport' not in args:
                    self.all_actions.append((action, deepcopy(self.states)))
                for native in ids:
                    state = self.states[native]
                    if action == 'stop': state = 'stopped'
                    elif action in ('play', 'playDirectly'):
                        ready = version == '2021.1' or self.transports[native]['object'] in self.prepared or self.originals
                        state = 'playing' if ready and failure != 'missing-playing' else 'stopped'
                    elif action == 'pause': state = {'playing': 'paused', 'paused': 'playing', 'stopped': 'stopped'}[state]
                    elif action == 'playStop': state = 'stopped' if state == 'playing' else 'playing'
                    if failure == 'mismatch' and 'transport' not in args and len(self.all_actions) == 3:
                        state = 'playing'
                    self.states[native] = state
                return {}
            return super().call(uri, args, options)

    info = owner.runtime.lifecycle.ready_result['version']
    info['displayName'] = f"v{info['year']}.{info['major']}.{info['minor']}"
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
    batch = authoring_batch.AuthoringBatchAdapter(owner=owner, repo_root=tmp_path, selected_nodeids=[OLDER_NODEID])
    return batch, batch.node_gateway(OLDER_NODEID), client, collect_older_transport_semantics, initial_loops


def _saved(category):
    archive = json.loads(Path(category['observation_artifact']['path']).read_text())
    report = json.loads((Path(archive['artifacts']['native-evidence']['path']) / 'transport-older-semantics.json').read_text())
    return archive, report


@pytest.mark.parametrize('owned_authoring', ['2021.1','2022.1','2023.1','2024.1'], indirect=True)
def test_older_eight_observations_reach_persisted_diagnostic_category_with_bounded_cleanup(
    owned_authoring, tmp_path, monkeypatch,
):
    batch, call, client, collect, initial = _host(owned_authoring, tmp_path, monkeypatch)
    report = collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=True)
    category, = record['categories']
    archive, saved = _saved(category)
    assert final['outcome'] == 'PASS' and saved == report
    assert category['status'] == 'blocked' and category['observation_task_status'] == 'PASS'
    assert category['business_effect_verified'] is False and category['coverage_credit'] == 'none_pending_semantics'
    assert [(case['case_id'], [row['state'] for row in case['before']],
        [row['observed_state'] for row in case['after']]) for case in saved['cases']] == [
            ('D-one', ['stopped','stopped'], ['playing']),
            ('P-one', ['stopped','stopped'], ['stopped']),
            ('T-one', ['paused','stopped'], ['playing']),
            ('D-all', ['playing','paused'], ['playing','playing']),
            ('P-all-SP', ['stopped','playing'], ['stopped','paused']),
            ('P-all-PQ', ['playing','paused'], ['paused','playing']),
            ('T-all-SP', ['stopped','playing'], ['playing','stopped']),
            ('T-all-QS', ['paused','stopped'], ['playing','playing'])]
    assert all(case['unselected_after']['state'] == 'stopped' for case in saved['cases'][:3])
    assert [row['transport'] for row in saved['members']] == [17, 91]
    assert len({row['object'] for row in saved['members']}) == len({row['transport_handle'] for row in saved['members']}) == 2
    assert all(case['observation_status'] == 'OBSERVED' and case['business_effect_verified'] is False for case in saved['cases'])
    assert saved['cleanup']['complete'] and not client.transports
    assert {key: row['@IsLoopingEnabled'] for key,row in client.rows.items() if row['type'] == 'Sound'} == initial
    expected = {'2021.1': (407,36), '2022.1': (466,56), '2023.1': (415,36), '2024.1': (415,36)}
    total, cleanup = expected[owned_authoring.version]
    assert saved['public_call_count'] == total
    assert saved['cleanup']['public_call_count'] == cleanup <= saved['limits']['cleanup_reserved_calls'] == 64
    attachment_calls = 3 if owned_authoring.version == '2021.1' else 2
    assert len(archive['receipts']) == total + attachment_calls <= 480
    assert total - cleanup <= 480 - 64
    assert saved['playback_gate']['complete'] is True
    assert [row['action'] for row in saved['playback_gate']['receipts']] == ['play','stop','play','stop']
    assert len([receipt for receipt in archive['receipts'] if receipt['argv'][0] == 'execute']) == len(archive['transactions'])
    prepares = [row for row in saved['setup'] if 'prepared' in row]
    assert len(prepares) == (2 if owned_authoring.version == '2022.1' else 0)
    assert all(row['prepared']['verification_state'] == 'result_schema_checked'
        and row['prepared']['business_effect_verified'] is False for row in prepares)
    assert sum(uri.endswith('transport.useOriginals') for uri,_,_ in client.calls) == (1 if owned_authoring.version in ('2023.1','2024.1') else 0)
    if owned_authoring.version != '2022.1':
        assert saved['media_staging']['complete'] and len(saved['media_staging']['staged']) == 2
    if owned_authoring.version == '2021.1':
        active_queries = [row['argv'] for row in archive['receipts'] if row['argv'][0] == 'query-object' and 'active-source' in row['argv']]
        assert len(active_queries) == 4 and all('--platform' in argv and '--language' in argv and '--max-results' in argv for argv in active_queries)
        assert not any('activeSource' in (options or {}).get('return',[]) for uri,_,options in client.calls if uri.endswith('object.get'))


@pytest.mark.parametrize('owned_authoring,failure,observed,cleanup', [
    ('2021.1','missing-playing',0,True), ('2022.1','prepare',0,False), ('2022.1','mismatch',5,False),
], indirect=['owned_authoring'])
def test_older_partial_setup_or_verifier_failure_reaches_blocked_final_archive(
    owned_authoring, tmp_path, monkeypatch, failure, observed, cleanup,
):
    batch, call, client, collect, _ = _host(owned_authoring, tmp_path, monkeypatch, failure=failure)
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    category, = record['categories']
    archive, saved = _saved(category)
    assert final['outcome'] == 'FAIL' and record['residual_state']['quarantine_path']
    assert category['status'] == 'blocked' and category['observation_task_status'] == 'BLOCKED'
    assert category['business_effect_verified'] is False and category['coverage_credit'] == 'none_pending_semantics'
    assert category['cleanup_complete'] is cleanup and not saved['complete']
    assert 'batch_finalization' not in category and not batch.batch_seal_path.exists()
    assert sum(case['observation_status'] == 'OBSERVED' for case in saved['cases']) == observed
    if failure == 'missing-playing':
        assert saved['playback_gate']['complete'] is False
        assert not any(uri.endswith('executeAction') and args['action'] in ('playDirectly','pause','playStop')
            for uri,args,_ in client.calls)
        assert not client.transports
    else:
        failed, = [row for row in archive['receipts'] if row['exit_code'] != 0]
        assert archive['receipts'][-1] == failed
        assert saved['cleanup']['public_call_count'] == 0
        assert [row['action'] for row in saved['cleanup']['errors']] == ['further-writes-suppressed']
        if failure == 'prepare':
            assert sum(uri.endswith('transport.prepare') for uri,_,_ in client.calls) == 1
            assert not any(uri.endswith(('transport.create','transport.executeAction')) for uri,_,_ in client.calls)
        else:
            assert failed['argv'] == ['verify', saved['cases'][5]['transaction_id']]
            assert failed['payload']['state'] == 'verification_failed'
            assert failed['payload']['verification']['verification_scope']['observation']['membership_matches'] is True
            assert saved['cases'][5]['acknowledgement']['executed'] is True
            assert len(client.all_actions) == 3
            assert saved['public_call_count'] == 332


@pytest.mark.parametrize('owned_authoring', ['2021.1'], indirect=True)
def test_selected_scope_witness_failure_retains_target_state_without_completing_case(
    owned_authoring, tmp_path, monkeypatch,
):
    batch, call, client, collect, _ = _host(owned_authoring, tmp_path, monkeypatch, failure='witness')
    with pytest.raises(AssertionError):
        collect(batch, call)
    final, record = _finish(batch, tmp_path, monkeypatch, passed=False)
    category, = record['categories']
    archive, saved = _saved(category)
    assert final['outcome'] == 'FAIL' and record['residual_state']['quarantine_path']
    assert category['status'] == 'blocked' and category['observation_task_status'] == 'BLOCKED'
    assert category['cleanup_complete'] is False and category['business_effect_verified'] is False
    assert saved['cases'][0]['after'][0]['observed_state'] == 'playing'
    assert all(case['observation_status'] == 'BLOCKED' for case in saved['cases'])
    assert 'unselected_after' not in saved['cases'][0]
    assert saved['public_call_count'] == 84 and saved['cleanup']['public_call_count'] == 0
    failed, = [row for row in archive['receipts'] if row['exit_code'] != 0]
    assert failed['argv'] == ['core-call','ak.wwise.core.transport.getState','--transport-handle',saved['members'][1]['transport_handle']]
    assert archive['receipts'][-1] == failed and 'batch_finalization' not in category
    assert sum(uri.endswith('transport.executeAction') and args['action'] == 'playDirectly' for uri,args,_ in client.calls) == 1


@pytest.mark.parametrize('version,extra', [('2021.1',False),('2022.1',False),('2023.1',False),('2024.1',False),('2025.1',False),('2022.1',True)])
def test_older_combined_node_uses_exact_versioned_single_owner_and_child_setup(tmp_path, monkeypatch, version, extra):
    from types import SimpleNamespace
    from tests.destructive.support import authoring_batch
    from tests.destructive.support.transport_semantics import OLDER_NODEID
    from tests.unit.test_authoring_batch_owner import _fakes, _config, NODE
    events = _fakes(monkeypatch, tmp_path)
    stages = []
    monkeypatch.setattr(authoring_batch, 'stage_owned_older_transport_media', lambda sandbox, io, *, version: stages.append(version))
    monkeypatch.setenv('WWISE_VERSION', version)
    monkeypatch.delenv('AK_AUTOMATION_MODE', raising=False)
    config = _config(tmp_path)
    config.args = [OLDER_NODEID, *([NODE] if extra else [])]
    items = [SimpleNamespace(nodeid=name) for name in config.args]
    if version == '2025.1' or extra:
        with pytest.raises(pytest.UsageError):
            authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert not events and not stages
    else:
        authoring_batch.configure_authoring_batch_owner(config, items, repo_root=tmp_path)
        assert [row[0] for row in events] == ['construct','start','install'] and stages == [version]
        assert events[0][1]['live_environment']['AK_AUTOMATION_MODE'] == '1'
        assert events[0][1]['version'] == version
        assert 'AK_AUTOMATION_MODE' not in authoring_batch.os.environ


def _media_fixture(tmp_path, monkeypatch, version):
    from types import SimpleNamespace
    import hashlib
    from tests.destructive.support import transport_semantics as module
    installed = tmp_path / 'Audiokinetic'
    monkeypatch.setattr(module, 'INSTALLED_SAMPLE_ROOT', installed)
    build = {'2021.1':'2021.1.14.8108','2023.1':'2023.1.19.8928','2024.1':'2024.1.13.9056'}[version]
    source = installed / ('SampleProject' + build) / 'SampleProject'
    relative = ('Originals/SFX/Minigun/MnGn_Barrel_Loop.wav','Originals/SFX/Car Engine/Porsche_Outside_Idle_1000_01.wav')
    pcm = (Path(__file__).resolve().parents[1] / '_org/2022.1/Originals/SFX/WAAPI Skill Integration V2/audit_tail.wav').read_bytes()
    for name in relative:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pcm)
    # Substitute only the external installed-file proofs; keep the real stager.
    monkeypatch.setattr(module, 'OLDER_MEDIA_HASHES', dict.fromkeys(relative, hashlib.sha256(pcm).hexdigest()))
    sandbox = SimpleNamespace(sandbox_path=tmp_path/'owned-copy', source_root=tmp_path/'committed-source')
    sandbox.sandbox_path.mkdir(); sandbox.source_root.mkdir()
    for folder in (sandbox.sandbox_path,sandbox.source_root):
        (folder/'fixture.wwu').write_bytes(b'unchanged XML')
    io = tmp_path/'owned-io'; io.mkdir()
    return module, sandbox, io, source, relative, pcm


@pytest.mark.parametrize('version', ['2021.1','2023.1','2024.1'])
def test_older_media_stages_only_two_missing_matching_originals_without_xml_changes(tmp_path, monkeypatch, version):
    module, sandbox, io, source, relative, pcm = _media_fixture(tmp_path, monkeypatch, version)
    module.stage_owned_older_transport_media(sandbox, io, version=version)
    report = json.loads((io/'transport-media.json').read_text())
    assert report['complete'] and report['version'] == version and len(report['staged']) == 2
    assert report['authored_xml_changed'] is False
    for name in relative:
        assert (source/name).read_bytes() == (sandbox.sandbox_path/name).read_bytes() == pcm
    assert (sandbox.sandbox_path/'fixture.wwu').read_bytes() == (sandbox.source_root/'fixture.wwu').read_bytes() == b'unchanged XML'


@pytest.mark.parametrize('damage', ['hash','link','overwrite'])
def test_older_media_refuses_changed_source_links_and_existing_destination(tmp_path, monkeypatch, damage):
    module, sandbox, io, source, relative, pcm = _media_fixture(tmp_path, monkeypatch, '2023.1')
    target = sandbox.sandbox_path/relative[0]
    if damage == 'hash':
        (source/relative[0]).write_bytes(b'changed external file')
    elif damage == 'link':
        outside = tmp_path/'outside'; outside.mkdir()
        (sandbox.sandbox_path/'Originals').symlink_to(outside, target_is_directory=True)
    else:
        target.parent.mkdir(parents=True)
        target.write_bytes(b'keep this file')
    with pytest.raises((AssertionError, ValueError, FileExistsError)):
        module.stage_owned_older_transport_media(sandbox, io, version='2023.1')
    assert not json.loads((io/'transport-media.json').read_text())['complete']
    if damage == 'overwrite':
        assert target.read_bytes() == b'keep this file'
    else:
        assert not target.exists()
