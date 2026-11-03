"""Prepared randomizer witness through the real Gateway and fake native transport."""
import copy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from tests.unit.test_query_field_conditions import FieldTask
from tests.unit.test_workflow_source_guard import workflow


@pytest.mark.parametrize('version', ['2025.1', '2021.1'])
@pytest.mark.parametrize('fault', ['none', 'missing-member', 'wrong-member'])
def test_randomizer_witness_keeps_real_gateway_and_both_member_planners(tmp_path, workflow, monkeypatch, version, fault):
    from tests.destructive import test_query_randomizer_outputs as witness
    source = tmp_path / 'source'; owned = tmp_path / 'owned'; sandbox = owned / 'project'
    relative = witness._wwu(version)
    (source / relative).parent.mkdir(parents=True)
    shutil.copyfile(witness.REPO / 'tests/_org' / version / relative, source / relative)
    (source / 'SampleProject.wproj').write_text('<WwiseDocument/>')
    shutil.copytree(source, sandbox)
    task_root = tmp_path / 'transport'; task_root.mkdir()
    task = FieldTask(task_root, version)
    build = witness.BUILDS[version]
    task.info['version'].update(dict(zip(('year', 'major', 'minor', 'build'), build)))
    task.info['isCommandLine'] = True
    task.project['filePath'] = str(sandbox / 'SampleProject.wproj')
    catalog = json.loads((witness.REPO / 'skills/waapi-skill/resources/metadata' / version / 'object-types.json').read_text())
    types = {row['name']: row['classId'] for row in catalog['types']}
    owner_class, child_class = types['SwitchContainer'], types['SwitchContainer']
    prefix = '\\Containers' if version == '2025.1' else '\\Actor-Mixer Hierarchy'
    parent = {'id': witness.OWNER, 'name': 'Footstep_Types'}
    owner = {**parent, 'type': 'SwitchContainer', 'classId': owner_class, 'path': prefix + '\\Footsteps\\Footstep_Types',
        'randomizer("Pitch").@Enabled': True, 'randomizer("Pitch").@Min': -200.0,
        'randomizer("Pitch").@Max': 200.0, 'randomizer("Volume").@Min': -5.0}
    children = {}
    for identity, name in witness.CHILDREN.items():
        children[identity] = {'id': identity, 'name': name, 'type': 'SwitchContainer',
            'classId': child_class, 'path': owner['path'] + '\\' + name, 'parent': parent, 'parent.classId': owner_class,
            'parent.randomizer("Pitch").@Enabled': True, 'parent.randomizer("Pitch").@Min': -200.0,
            'parent.randomizer("Pitch").@Max': 200.0}
    owner['children'] = [{key: row[key] for key in ('id', 'name')} for row in reversed(list(children.values()))]
    task.rows = [owner]; task.objects = {witness.OWNER: owner, **children}; task.members = children
    task.metadata = {owner_class: {'Pitch': {'name': 'Pitch', 'type': 'int32'},
        'Volume': {'name': 'Volume', 'type': 'Real64'}}}
    task.metadata[witness.OWNER] = copy.deepcopy(task.metadata[owner_class])
    original = task.call
    def native(uri, args=None, options=None):
        if uri.endswith('object.get') and (args or {}).get('waql', '').startswith('from type Project take '):
            task.calls.append((uri, args, options))
            return {'return': [task.projection(task.project, options['return'])]}
        result = original(uri, args, options)
        if phase == 'members' and fault != 'none' and uri.endswith('object.get'):
            def change(row):
                if isinstance(row, dict):
                    if row.get('id') == witness.CHILD and 'parent.randomizer("Pitch").@Max' in row:
                        if fault == 'missing-member': row.pop('parent.randomizer("Pitch").@Max')
                        else: row['parent.randomizer("Pitch").@Min'] = False
                    for value in row.values(): change(value)
                elif isinstance(row, list):
                    for value in row: change(value)
            change(result)
        return result
    task.call = native
    packets = owned / 'packets'; packets.mkdir()
    runtime = SimpleNamespace(version=version, candidate='program-only', category_results=[], state_dir=owned / 'state',
        sandbox=SimpleNamespace(source_root=source, sandbox_path=sandbox,
            metadata=SimpleNamespace(get_info_version=task.info['version'])), env=task.env)
    task.env.update(WWISE_EVIDENCE_DIR=str(packets), WAAPI_SKILL_STATE_DIR=str(runtime.state_dir))
    default_attempts = []
    def forbidden_default_client(url):
        default_attempts.append(url)
        raise AssertionError('Fake collector must never construct a real client or attempt a socket')
    monkeypatch.setattr(workflow.waapi_gateway, 'default_client_factory', forbidden_default_client)
    execute_gateway = workflow.waapi_gateway.execute_gateway
    def fake_gateway(argv, **kwargs):
        kwargs['client_factory'] = lambda _: task
        return execute_gateway(argv, **kwargs)
    monkeypatch.setattr(workflow.waapi_gateway, 'execute_gateway', fake_gateway)
    phase = ''
    def raw(argv):
        nonlocal phase
        phase = 'members' if 'children' in argv else 'other'
        return workflow.waapi_gateway.execute_gateway(['--timeout', '30', '--state-dir', str(runtime.state_dir), *argv],
            env=runtime.env)
    runtime.raw_gateway = raw
    if fault == 'none': witness.test_property_bound_randomizer_values_keep_owner_and_member_scope(runtime, monkeypatch)
    else:
        with pytest.raises(AssertionError):
            witness.test_property_bound_randomizer_values_keep_owner_and_member_scope(runtime, monkeypatch)
    assert not default_attempts
    category, = runtime.category_results
    body = Path(category['observation_path']).read_bytes()
    assert witness.sha(body) == category['observation_sha256']
    receipt = json.loads(body)
    if fault == 'none':
        assert category['status'] == 'PASS' and receipt['typed_randomizer_return_proof'] is True
        assert len(receipt['reads']) == 6 and receipt['dispatch_count'] <= 128
    else:
        assert category['status'] == 'FAIL' and receipt['typed_randomizer_return_proof'] is False
        assert category['business_effect_verified'] is False
        assert len(receipt['reads']) == 5 and receipt['reads'][-1]['label'] == 'full-and-selected-member-parent-randomizers'
    assert receipt['reads'][2]['invocations'][0]['payload']['agent_result'][0]['related']['randomizers']['Pitch']['enabled'] is True


def test_2021_exact_returned_page_keeps_fake_client_before_any_socket(tmp_path, workflow, monkeypatch):
    from tests.unit.test_object_query_result_pages import QueryTask
    task = QueryTask(tmp_path, '2021.1')
    task.row['notes'] = '音声' * 50000
    attempts = []
    def forbidden_default(url):
        attempts.append(url)
        raise AssertionError('Missing injection must stop before constructing a real client')
    monkeypatch.setattr(workflow.waapi_gateway, 'default_client_factory', forbidden_default)
    execute_gateway = workflow.waapi_gateway.execute_gateway
    submitted = []
    def fake_gateway(argv, **kwargs):
        submitted.append(list(argv))
        return execute_gateway(argv, client_factory=lambda _: task, **kwargs)
    monkeypatch.setattr(workflow.waapi_gateway, 'execute_gateway', fake_gateway)
    code, first = workflow.waapi_gateway.execute_gateway(['query-object', '--exact-id', task.row['id'], '--include', 'notes'], env=task.env)
    assert code == 0 and first['status'] == 'partial'
    assert first['agent_result']['projection_complete'] is False
    returned = first['agent_result']['next_command']['gateway_argv']
    # Same exact-argv execute_gateway branch as the collector: no helper timeout.
    code, continued = workflow.waapi_gateway.execute_gateway(returned, env=task.env)
    assert submitted[-1] == returned and '--timeout' not in submitted[-1]
    assert code == 0 and continued['ok'] is True
    assert continued['agent_result']['page']['offset'] == first['agent_result']['page']['next_offset']
    assert not attempts
    # Deliberately omit injection once: the guard is the failure, before a socket.
    code, rejected = execute_gateway(returned, env=task.env)
    assert code == 2 and rejected['ok'] is False
    assert len(attempts) == 1
