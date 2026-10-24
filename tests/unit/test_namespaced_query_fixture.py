"""Owned prelaunch boundaries and existing public CLI; never starts Wwise."""
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from tests.destructive.support import namespaced_query_fixture as fixture
from tests.unit.test_workflow_source_guard import workflow
from tests.support.platform_filesystem import create_symlink_or_skip


def sandbox_copy(tmp_path):
    owned = tmp_path / 'owned'; root = owned / 'project'; root.mkdir(parents=True)
    source = tmp_path / 'source'; (source / 'Containers').mkdir(parents=True)
    original = Path(__file__).parents[1] / '_org/2025.1' / fixture.WWU
    shutil.copyfile(original, source / fixture.WWU)
    (source / 'SampleProject.wproj').write_text('<WwiseDocument/>')
    shutil.copytree(source, root, dirs_exist_ok=True)
    io = owned / 'io'; io.mkdir()
    return SimpleNamespace(sandbox_path=root, sandbox_project=root / 'SampleProject.wproj', source_root=source), owned, io


def test_project_local_definition_preserves_complete_source_and_project(tmp_path):
    sandbox, owned, io = sandbox_copy(tmp_path)
    originals = {path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sandbox.source_root.rglob('*') if path.is_file()}
    project = sandbox.sandbox_project.read_bytes()
    report = fixture.prepare_namespaced_query_fixture(sandbox, owned_root=owned, io_root=io)
    assert fixture.sha((sandbox.sandbox_path / fixture.TARGET).read_bytes()) == fixture.DEFINITION_SHA
    assert report['source_wwu']['sound_id'] == fixture.SOUND and report['source_wwu']['complete_wwu_nonassignment']
    assert report['native_acceptance'] is False and report['coverage_credit'] == 'none'
    assert report['source']['build'] == '2025.1.7.9143'
    assert report == json.loads((io / 'namespaced-query-prelaunch.json').read_text())
    assert sandbox.sandbox_project.read_bytes() == project
    assert all((path.read_bytes(), path.stat().st_mtime_ns) == before for path, before in originals.items())
    with pytest.raises(AssertionError, match='earlier fixture'):
        fixture.prepare_namespaced_query_fixture(sandbox, owned_root=owned, io_root=io)


@pytest.mark.parametrize('fault', ['source-project', 'outside-report', 'wwu-drift', 'definition-drift', 'existing-file', 'other-definition', 'symlink-parent'])
def test_prelaunch_rejects_unowned_or_changed_inputs_without_replacing_files(tmp_path, monkeypatch, fault):
    sandbox, owned, io = sandbox_copy(tmp_path)
    target = sandbox.sandbox_path / fixture.TARGET
    if fault == 'source-project': sandbox.source_root = sandbox.sandbox_path
    elif fault == 'outside-report': io = tmp_path / 'outside'; io.mkdir()
    elif fault == 'wwu-drift':
        path = sandbox.sandbox_path / fixture.WWU; path.write_bytes(path.read_bytes() + b' ')
    elif fault == 'definition-drift':
        data = tmp_path / 'definitions'; shutil.copytree(fixture.FIXTURES, data)
        (data / 'status.wcustomproperties').write_text('<unapproved/>')
        monkeypatch.setattr(fixture, 'FIXTURES', data)
    elif fault == 'existing-file':
        target.parent.mkdir(parents=True); target.write_bytes(b'Keep existing data')
    elif fault == 'other-definition':
        target.parent.mkdir(parents=True); (target.parent / 'other.wcustomproperties').write_bytes(b'Keep existing definition')
    else:
        outside = tmp_path / 'outside'; outside.mkdir()
        create_symlink_or_skip(sandbox.sandbox_path / 'Add-ons', outside, target_is_directory=True)
    before = {str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob('*') if path.is_file() and not path.is_symlink()}
    with pytest.raises((AssertionError, RuntimeError)):
        fixture.prepare_namespaced_query_fixture(sandbox, owned_root=owned, io_root=io)
    after = {str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob('*') if path.is_file() and not path.is_symlink()}
    assert after == before and not (io / 'namespaced-query-prelaunch.json').exists()


@pytest.mark.parametrize('profile,version,exception', [
    ('unknown-profile', '2025.1', AssertionError),
    (fixture.PROFILE, '2021.1', pytest.skip.Exception),
    ('2021-native-donor-two-properties/v1', '2025.1', pytest.skip.Exception),
])
def test_common_fixture_rejects_unknown_or_wrong_version_profile_before_copy(workflow, monkeypatch, profile, version, exception):
    monkeypatch.setenv('WWISE_VERSION', version)
    def unexpected(*args, **kwargs):
        raise AssertionError('Profile boundary reached sandbox preparation')
    monkeypatch.setattr(workflow, 'prepare_sample_project_sandbox', unexpected)
    generator = workflow.workflow_sandbox_runtime.__wrapped__(SimpleNamespace(param=profile), None)
    with pytest.raises(exception):
        next(generator)


def test_probe_candidates_use_existing_offline_advanced_and_metadata_cli(tmp_path, workflow):
    gateway = workflow.waapi_gateway
    code, schema = gateway.execute_gateway(['--version', '2025.1', 'query-schema', '--advanced'], env={})
    assert code == 0 and schema['boundary']['read_only'] is True
    assert schema['boundary']['fixed_api'] == 'ak.wwise.core.object.get'
    assert schema['boundary']['gateway_appends_final_take'] is True
    args = gateway.build_parser().parse_args(['metadata', 'discover', '--exact-id', fixture.SOUND, '--meaning', fixture.TOKEN])
    gateway.preflight_metadata_input(args, env={})
    assert args.object == fixture.SOUND and args.queries == [fixture.TOKEN]
    from wwise_waapi.builders.query import ADVANCED_QUERY_CONTRACT, build_advanced_object_get_query
    for prefix in ('@', '@@'):
        expression = f'from object "{fixture.SOUND}" where {prefix}{fixture.TOKEN} = 0'
        preview = build_advanced_object_get_query({'contract': ADVANCED_QUERY_CONTRACT,
            'waql': expression, 'return': ['id', 'name', 'type', 'path'], 'max_results': 1}, version='2025.1')
        assert preview.envelope.args == {'waql': expression + ' take 1'}
        assert preview.envelope.uri == 'ak.wwise.core.object.get'


def test_probe_freezes_first_native_syntax_error_with_failed_finalized_category(tmp_path, workflow, monkeypatch):
    from tests.destructive import test_query_namespaced_property as probe
    sandbox, owned, io = sandbox_copy(tmp_path)
    report = fixture.prepare_namespaced_query_fixture(sandbox, owned_root=owned, io_root=io)
    sandbox.metadata = SimpleNamespace(get_info_version=dict(year=2025, major=1, minor=7, build=9143))
    evidence = owned / 'packets'; evidence.mkdir()
    runtime = SimpleNamespace(version='2025.1', sandbox=sandbox, namespaced_query_prelaunch=report,
        state_dir=owned / 'state', env={'WWISE_EVIDENCE_DIR': str(evidence)}, candidate='program-only', category_results=[])
    syntax_calls, all_calls = [], []
    def fake_dispatch(_dispatcher, api, *, version, args, options=None):
        if api.endswith('getPropertyAndReferenceNames'): result, ok = {'return': [fixture.TOKEN]}, True
        elif api.endswith('getPropertyInfo'):
            result, ok = {'name': fixture.TOKEN, 'type': 'int16', 'default': 0,
                'restriction': {'type': 'enum', 'values': [{'value': value} for value in (0, 1, 2)]}}, True
        else:
            assert api.endswith('object.get') and '@MyCompany:Status = 0' in args['waql']
            result, ok = {'message': 'Program-only simulated native syntax rejection'}, False
        packet = {'api': api, 'ok': ok, 'result': result}
        path = evidence / f'{len(all_calls):04d}.json'; path.write_text(json.dumps(packet))
        all_calls.append(api)
        return {'ok': ok, 'result': result, 'evidence_path': str(path)}
    monkeypatch.setattr(workflow.waapi_gateway.WwiseDispatcher, 'dispatch', fake_dispatch)
    sound = {'id': fixture.SOUND, 'name': 'Footstep_Crouching_Concrete_01', 'type': 'Sound',
        'path': '\\Containers\\Footsteps\\Footstep_Crouching_Concrete_01', 'class_id': 65552}
    def raw(argv):
        if argv[0] == 'query-schema':
            return 0, {'query_layer': 'advanced-native-waql',
                'boundary': {'fixed_api': 'ak.wwise.core.object.get', 'gateway_appends_final_take': True}}
        if argv[0] == 'metadata':
            for uri, args in [('getPropertyAndReferenceNames', {'object': fixture.SOUND}),
                    ('getPropertyInfo', {'object': fixture.SOUND, 'property': fixture.TOKEN})]:
                workflow.waapi_gateway.WwiseDispatcher.dispatch(None, 'ak.wwise.core.object.' + uri,
                    version='2025.1', args=args)
            return 0, {'ok': True, 'agent_result': {'candidates': [{'name': fixture.TOKEN}]}}
        if '--advanced-waql' not in argv: return 0, {'ok': True, 'agent_result': [sound]}
        syntax_calls.append(list(argv))
        expression = argv[argv.index('--advanced-waql') + 1]
        workflow.waapi_gateway.WwiseDispatcher.dispatch(None, 'ak.wwise.core.object.get', version='2025.1',
            args={'waql': expression + ' take 1'}, options={'return': ['id', 'name', 'type', 'path']})
        return 1, {'ok': False, 'error_code': 'SIMULATED_NATIVE_SYNTAX_ERROR', 'agent_result': None}
    runtime.raw_gateway = raw
    with pytest.raises(AssertionError, match='SIMULATED_NATIVE_SYNTAX_ERROR'):
        probe.test_namespaced_custom_property_where_uses_native_membership(runtime, monkeypatch)
    assert len(syntax_calls) == 1 and len(all_calls) == 3
    category, = runtime.category_results
    assert category['status'] == 'FAIL' and category['business_effect_verified'] is False
    body = Path(category['observation_path']).read_bytes()
    assert fixture.sha(body) == category['observation_sha256']
    receipt = json.loads(body)
    assert receipt['native_membership'] == [] and receipt['custom_return_proof'] is False
    assert receipt['override_difference_proof'] is False and len(receipt['reads']) == 3
