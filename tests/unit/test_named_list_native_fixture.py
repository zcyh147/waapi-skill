"""Exercise the native collector through the public Gateway and existing fake transport."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    return importlib.import_module('tests.destructive.test_named_list_native_stages')


def test_named_list_native_collects_one_existing_lifecycle_node(collector, request):
    module = pytest.Module.from_parent(request.session, path=Path(collector.__file__))
    item, = list(module.collect())
    assert item.name == 'test_2025_native_named_set_with_owned_metadata_slot'
    assert 'workflow_sandbox_runtime' in item.fixturenames


@pytest.mark.parametrize('fault', ['none', 'wrong-slot-owner'])
def test_named_list_native_collector_end_to_end_real_gateway_fake_transport(tmp_path, collector, fault):
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask
    from tests.destructive import test_gateway_workflow_transaction_matrix as workflow
    new = {'bus': '{11111111-1111-1111-1111-111111111111}',
        'sound': '{22222222-2222-2222-2222-222222222222}', 'slot': '{33333333-3333-3333-3333-333333333333}'}
    observed_bus_name = 'Observed native Bus'

    class ListTask(OwnedGraphTask):
        def call(self, uri, args=None, options=None):
            args, options = args or {}, options or {}
            if uri == collector.GET and args.get('waql') != 'from type Project take 1':
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                if 'waql' in args:
                    match = re.fullmatch(r'from object "([^"\n]+)"(?: select (children|descendants|@Metadata))? take [0-9]+', args['waql'])
                    assert match is not None, args
                    identities, relation = [match[1]], match[2]
                    rows = [row for row in self.objects.values() if row['id'] in identities or row['path'] in identities]
                else:
                    source = args['from']
                    rows = [row for row in self.objects.values() if row['id'] in source.get('id', []) or row['path'] in source.get('path', [])]
                    relation = args.get('transform', [{}])[0].get('select', [None])[0]
                if relation:
                    parent, = rows
                    if relation == 'children':
                        rows = [row for row in self.objects.values() if row.get('parent') == {'id': parent['id']}]
                    elif relation == 'descendants':
                        rows = [row for row in self.objects.values() if row['path'].startswith(parent['path'] + '\\')]
                    else:
                        assert relation == '@Metadata'
                        rows = [self.objects[member['id']] for member in parent['@Metadata']]
                return {'return': self.project_rows(rows, options)}
            if uri == collector.SET:
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                result = []
                def create(node, parent, *, owned=False):
                    role = {collector.REQUESTED['bus']: 'bus', collector.REQUESTED['sound']: 'sound', collector.REQUESTED['slot']: 'slot'}[node['name']]
                    oid = new[role]
                    name = observed_bus_name if role == 'bus' else node['name']
                    self.objects[oid] = {'id': oid, 'name': name, 'type': 'PluginInnerObject' if owned else node['type'],
                        'classId': collector.CLASSES[role], 'notes': '',
                        'path': r'\opaque observed MetadataSlot' if owned else self.objects[parent]['path'] + '\\' + name,
                        **({'owner': {'id': collector.CONTAINERS if fault == 'wrong-slot-owner' else parent}}
                            if owned else {'parent': {'id': parent}})}
                    returned = {'id': oid, 'name': name}
                    if '@Metadata' in node:
                        slots = [create(slot, oid, owned=True) for slot in node['@Metadata']]
                        self.objects[oid]['@Metadata'] = [{'id': row['id']} for row in slots]
                        returned['@Metadata'] = slots
                    return returned
                for node in args['objects']:
                    parent = node['object']
                    row = {'id': parent, 'name': self.objects[parent]['name']}
                    if 'children' in node:
                        row['children'] = [create(child, parent) for child in node['children']]
                    if '@OutputBus' in node:
                        bus, = [row for row in self.objects.values() if row['path'] == node['@OutputBus']]
                        self.objects[parent]['@OutputBus'] = {'id': bus['id']}
                    result.append(row)
                return {'objects': result}
            result = super().call(uri, args, options)
            if uri.endswith('getInfo'):
                result['version'].update(year=2025, major=1, minor=7, build=9143)
            elif uri.endswith('getProjectInfo'):
                result.update(currentPlatformId=collector.WINDOWS, platforms=[{'id': collector.WINDOWS, 'name': 'Windows'}])
            return result

    task = ListTask(tmp_path, '2025.1', 'object.set')
    task.metadata = {'OutputBus': {'name': 'OutputBus', 'type': 'Reference',
        'restriction': {'type': 'reference', 'restrictions': [{'type': ['Bus']}, 'notNull']}}}
    task.types = [{'classId': cid, 'name': name, 'type': 'WObject'} for name, cid in (
        ('Bus', 1376272), ('Sound', 65552), ('MetadataSlot', 5570560), ('WorkUnit', 1638416), ('PropertyContainer', 524304))]
    task.objects = {
        collector.OWNER: {'id': collector.OWNER, 'name': 'SFX', 'type': 'Bus', 'classId': 1376272,
            'path': collector.OWNER_PATH, 'parent': {'id': collector.ANCESTOR}, 'notes': 'keep SFX'},
        collector.ANCESTOR: {'id': collector.ANCESTOR, 'name': 'Environmental', 'type': 'Bus', 'classId': 1376272,
            'path': collector.OWNER_PATH.rsplit('\\', 1)[0], 'parent': {'id': '{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}'}, 'notes': 'keep ancestor'},
        collector.CONTAINERS: {'id': collector.CONTAINERS, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
            'path': collector.CONTAINERS_PATH, 'parent': None, 'notes': 'keep containers'},
        collector.RETAINED_CONTAINER: {'id': collector.RETAINED_CONTAINER, 'name': 'WAAPI Skill Integration V2',
            'type': 'PropertyContainer', 'classId': 524304, 'path': collector.CONTAINERS_PATH + r'\WAAPI Skill Integration V2',
            'parent': {'id': collector.CONTAINERS}, 'notes': 'keep complete direct child'},
        collector.WINDOWS: {'id': collector.WINDOWS, 'name': 'Windows', 'type': 'Platform', 'path': r'\Platforms\Windows'},
    }
    for identity, name in ((collector.GUNS, 'Guns'), (collector.CARS, 'Cars')):
        task.objects[identity] = {'id': identity, 'name': name, 'type': 'Bus', 'classId': 1376272,
            'path': collector.OWNER_PATH + '\\' + name, 'parent': {'id': collector.OWNER}, 'notes': 'keep ' + name}
    packets = tmp_path / 'packets'
    packets.mkdir()
    runtime = SimpleNamespace(version='2025.1', sandbox=SimpleNamespace(metadata=SimpleNamespace(
        get_info_version=dict(year=2025, major=1, minor=7, build=9143))), state_dir=tmp_path / 'collector-state',
        lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'), port=31337,
        env={**task.env, 'WWISE_EVIDENCE_DIR': str(packets)}, candidate='program-only', category_results=[])
    commands = []
    def raw(argv):
        commands.append(list(argv))
        return workflow.waapi_gateway.execute_gateway(['--timeout', '30', '--state-dir', str(runtime.state_dir), *argv],
            env=runtime.env, client_factory=lambda _: task)
    runtime.raw_gateway = raw
    if fault == 'none':
        collector.test_2025_native_named_set_with_owned_metadata_slot(runtime)
    else:
        with pytest.raises(AssertionError):
            collector.test_2025_native_named_set_with_owned_metadata_slot(runtime)
    category, = runtime.category_results
    body = Path(category['observation_path']).read_bytes()
    observation = json.loads(body)
    assert category['observation_sha256'] == hashlib.sha256(body).hexdigest()
    assert commands[0] == ['status']
    assert 'agent_result' not in observation['calls'][0]['payload']
    assert all(argv.count('--include-field') <= 8 for argv in commands if argv[0] == 'query-object')
    writes = [(uri, args) for uri, args, _ in task.calls if uri == collector.SET]
    assert not any(uri.startswith('ak.wwise.core.undo.') for uri, _, _ in task.calls)
    if fault == 'none':
        assert category['status'] == 'PASS' and category['business_effect_verified'] is True
        assert len(observation['reads']) == 15 and len(observation['transactions']) == 1
        assert [argv[0] for argv in commands].count('execute') == [argv[0] for argv in commands].count('verify') == 1
        assert [argv[0] for argv in commands].count('draft-start') == 1
        assert len(writes) == 3 and len(observation['native_evidence']) > 0
        assert len(observation['stage_packet_paths']) == 3
        assert observation['created']['bus']['name'] == observed_bus_name
        assert observation['independent_created']['slot']['type'] == 'PluginInnerObject'
        assert 'parent' not in observation['independent_created']['slot']
    else:
        assert category['status'] == 'FAIL' and category['business_effect_verified'] is False
        assert len(writes) == 2 and 'after' not in observation
