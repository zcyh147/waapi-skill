"""Public 2021 active-source queries over retained native observation shapes."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.unit.test_typed_query_construction import _AdvancedQueryClient, _env, gateway
from tests.unit.test_workflow_source_guard import workflow


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


def _plugin_select_collector(tmp_path, workflow, monkeypatch, fault=None):
    """External transport fake; real public collector and category finalizer."""
    import shutil
    from types import SimpleNamespace
    from tests.unit.test_object_query_result_pages import QueryTask
    from tests.destructive import test_query_legacy_control_input as witness
    from tests.destructive.support import exact_real_evidence, sandbox_fixture

    source = tmp_path / 'source'; shutil.copytree(witness.REPO / 'tests/_org/2021.1', source)
    owned = tmp_path / 'owned'; project_root = owned / 'project'; shutil.copytree(source, project_root)
    source_project = source / 'SampleProject.wproj'; project = project_root / 'SampleProject.wproj'
    source_hash = sandbox_fixture.hash_project(source)
    metadata = sandbox_fixture.SandboxMetadata(str(source_project), str(source), str(project_root),
        str(project), '2021.1', 0, source_hash, sandbox_fixture.hash_project(project_root),
        source_project.stat().st_mtime, process_cleanup_result='cleaned', process_cleanup_details={'residual_processes': []})
    metadata.get_info_version = dict(zip(('year','major','minor','build'), (2021,1,14,8108)))
    sandbox = sandbox_fixture.SandboxProject(source_project, source, owned, project_root, project, metadata)
    backend = tmp_path / 'backend'; backend.mkdir(); task = QueryTask(backend, '2021.1')
    task.info['version'].update(metadata.get_info_version)
    task.project['filePath'] = str(project)
    native_row = {'id':witness.SOURCE,'name':'Wwise Synth One','type':'SourcePlugin',
        'path':r'\opaque-native-plugin-path','classId':9699330}
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and args != {'waql':'from type Project take 1'}:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            query = args['waql']; row = deepcopy(native_row)
            if ' select activeSource ' in query:
                if fault == 'rejection': raise RuntimeError('selected 2021 activeSource SELECT rejected')
                if fault == 'missing': return {'return':[]}
            elif fault == 'readback': row['name'] = 'Changed native source'
            return {'return':[{key:row[key] for key in options['return'] if key in row}]}
        return original(uri, args, options)
    task.call = call
    packets = owned / 'packets'; packets.mkdir(); task.env['WWISE_EVIDENCE_DIR'] = str(packets)
    def forbidden(*args, **kwargs): raise AssertionError('Fake collector must not create a socket')
    monkeypatch.setattr(workflow.waapi_gateway, 'default_client_factory', forbidden)
    execute = workflow.waapi_gateway.execute_gateway
    def injected(argv, **kwargs): return execute(argv, client_factory=lambda _:task, **kwargs)
    monkeypatch.setattr(workflow.waapi_gateway, 'execute_gateway', injected)
    runtime = workflow._WorkflowSandboxRuntime('2021.1', sandbox,
        SimpleNamespace(host='127.0.0.1',port=31337,waapi_url='ws://127.0.0.1:31337/waapi'),
        owned / 'state', task.env, workflow.exact_git_candidate(workflow.REPO_ROOT), [])
    lock = sandbox_fixture.LiveSandboxLock(tmp_path / 'locks'); lock.__enter__()
    item = SimpleNamespace(path=witness.__file__,
        nodeid='tests/destructive/test_query_legacy_control_input.py::test_legacy_plugin_active_source_uses_documented_select',
        _waapi_phase_reports={'setup':'passed'})
    error = None
    try: witness.test_legacy_plugin_active_source_uses_documented_select(runtime, monkeypatch)
    except AssertionError as exc: error = exc
    item._waapi_phase_reports['call'] = 'failed' if error else 'passed'
    target = tmp_path / 'category.jsonl'; monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    monkeypatch.setattr(sandbox_fixture, 'KEEP_ON_FAILURE_ROOT', tmp_path / 'quarantine')
    assert exact_real_evidence.finalize_exact_real_evidence(repo_root=workflow.REPO_ROOT,
        candidate=runtime.candidate,version='2021.1',request=SimpleNamespace(session=SimpleNamespace(items=[item])),
        module_file=Path(witness.__file__),started_at_unix_ns=1,active_error=error,deferred_error=None,
        sandbox=sandbox,lock=lock,state_dir=runtime.state_dir,host={'is_command_line':True,'version':'2021.1'},
        categories=runtime.category_results,source={'hash_before':source_hash.digest,'hash_after':sandbox_fixture.hash_project(source).digest}) is None
    final = json.loads(target.read_text().splitlines()[-1]); category, = final['categories']
    return task, json.loads(Path(category['observation_path']).read_text()), final, error


def test_existing_plugin_active_source_select_reaches_public_collector_and_final_writer(tmp_path, workflow, monkeypatch):
    task, receipt, final, error = _plugin_select_collector(tmp_path, workflow, monkeypatch)
    assert error is None and final['invocation']['outcome'] == 'PASS'
    assert final['residual_state']['sandbox'] == 'deleted'
    assert receipt['active_source_identity_verified'] is True and receipt['transaction_count'] == 0
    assert receipt['source_before'] == receipt['source_after']
    assert receipt['source_oracle']['active_entry']['Platform'] == 'Linked'
    assert receipt['source_oracle']['no_audio_file_element'] is True
    assert receipt['selected_source'] == receipt['readback_source']
    assert receipt['dispatch_count'] == receipt['invocation_count'] == 2
    reads = [(args, options) for uri,args,options in task.calls if uri.endswith('object.get')]
    assert len(reads) == 2 and 'select activeSource take 2' in reads[0][0]['waql']
    assert all(options['platform'] == 'Mac' and options['language'] == 'SFX' for _,options in reads)
    assert all(options['return'] == ['id','name','type','path','classId'] for _,options in reads)


@pytest.mark.parametrize('fault', ['missing','rejection','readback'])
def test_plugin_active_source_select_preserves_failed_evidence_without_retry(tmp_path, workflow, monkeypatch, fault):
    task, receipt, final, error = _plugin_select_collector(tmp_path, workflow, monkeypatch, fault)
    assert isinstance(error, AssertionError) and final['invocation']['outcome'] == 'FAIL'
    assert final['residual_state']['sandbox'] == 'quarantined'
    assert receipt['active_source_identity_verified'] is False and receipt['native_absence_proven'] is False
    assert receipt['transaction_count'] == 0 and receipt['source_before'] == receipt['source_after']
    expected = 2 if fault == 'readback' else 1
    assert receipt['invocation_count'] == receipt['dispatch_count'] == len(receipt['native_packets']) == expected
    assert sum(uri.endswith('object.get') for uri,_,_ in task.calls) == expected
    packets = [json.loads(Path(row['path']).read_text()) for row in receipt['native_packets']]
    if fault == 'rejection': assert packets[0]['ok'] is False and 'SELECT rejected' in packets[0]['message']
    elif fault == 'missing': assert packets[0]['result']['return'] == []
    else: assert packets[-1]['result']['return'][0]['name'] == 'Changed native source'
