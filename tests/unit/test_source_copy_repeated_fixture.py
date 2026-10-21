"""Closed synthetic fixture preparation and actual Gateway collector controls."""
from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import xml.etree.ElementTree as ET

import pytest

from tests.unit.test_workflow_source_guard import workflow


def fixture_sandbox(tmp_path):
    source = Path(__file__).parents[1] / '_org/2021.1'
    owned = tmp_path / 'owned'; root = owned / 'project'; root.mkdir(parents=True)
    (root / 'Actor-Mixer Hierarchy').mkdir()
    shutil.copyfile(source / 'Actor-Mixer Hierarchy/MIDI.wwu', root / 'Actor-Mixer Hierarchy/MIDI.wwu')
    project = root / 'SampleProject.wproj'; project.write_text('<WwiseDocument/>')
    io = owned / 'prelaunch-io'; io.mkdir()
    sandbox = SimpleNamespace(sandbox_project=project, sandbox_path=root, source_root=source)
    return sandbox, owned, io


def test_prelaunch_transplants_portable_native_group_without_changing_originals(tmp_path):
    from tests.destructive.support.source_copy_fixture import prepare_repeated_source_fixture, SOURCE, SOURCE_OWNER, source_graph
    sandbox, owned, io = fixture_sandbox(tmp_path)
    original = (sandbox.source_root / 'Actor-Mixer Hierarchy/MIDI.wwu').read_bytes()
    report = prepare_repeated_source_fixture(sandbox, owned_root=owned, io_root=io)
    changed = (sandbox.sandbox_path / 'Actor-Mixer Hierarchy/MIDI.wwu').read_bytes()
    nodes = source_graph([changed], SOURCE, SOURCE_OWNER)
    assert len(nodes) == 7 and len({node.get('ID') for node in nodes.values()}) == 7
    assert report['donor']['sha256'] == '2022d6d1e9ca0badae31ce635ed802234b79dc862201a7b101a8a963b3ff9ed6'
    donor = (Path(__file__).parents[1] / 'fixtures/source-copy/2021-native-donor.wwu').read_bytes()[2239:3641]
    assert changed.count(donor) == 1
    assert report['native_acceptance'] is False and report['coverage_credit'] == 'none'
    assert {row['relative_path'] for row in report['collision_inventory']} == {'Actor-Mixer Hierarchy/MIDI.wwu', 'SampleProject.wproj'}
    midi_proof, = [row for row in report['collision_inventory'] if row['relative_path'].endswith('MIDI.wwu')]
    assert midi_proof['sha256'] == '4f4839e0457831e6d85c012847159b6f410c8716ec9a6c4ab6e9f888ff3c39e3' and midi_proof['bytes'] == len(original)
    assert (sandbox.source_root / 'Actor-Mixer Hierarchy/MIDI.wwu').read_bytes() == original
    assert json.loads((io / 'source-copy-prelaunch.json').read_text()) == report


@pytest.mark.parametrize('fault', ['source-drift', 'donor-drift', 'collision', 'symlink'])
def test_prelaunch_authority_failure_cannot_change_sandbox_source(tmp_path, monkeypatch, fault):
    from tests.destructive.support import source_copy_fixture as fixture
    sandbox, owned, io = fixture_sandbox(tmp_path)
    target = sandbox.sandbox_path / fixture.MIDI
    if fault == 'source-drift': target.write_bytes(target.read_bytes() + b' ')
    elif fault == 'donor-drift':
        donor_root = tmp_path / 'donor'; shutil.copytree(fixture.DONOR_ROOT, donor_root)
        donor = donor_root / '2021-native-donor.wwu'; donor.write_bytes(donor.read_bytes().replace(b'865369203', b'865369204'))
        monkeypatch.setattr(fixture, 'DONOR_ROOT', donor_root)
    elif fault == 'collision':
        (sandbox.sandbox_path / 'duplicate.WWU').write_text('<WwiseDocument><Sound ID="{4a926273-f070-4a69-9b9c-5e95843053ff}"/></WwiseDocument>')
    else:
        data = target.read_bytes(); target.unlink(); outside = tmp_path / 'outside.wwu'; outside.write_bytes(data); target.symlink_to(outside)
    before = target.read_bytes()
    with pytest.raises((AssertionError, RuntimeError)):
        fixture.prepare_repeated_source_fixture(sandbox, owned_root=owned, io_root=io)
    assert target.read_bytes() == before and not (io / 'source-copy-prelaunch.json').exists()


def repeated_collector_runtime(tmp_path, *, fault=None):
    """Actual Gateway with portable synthetic XML and only fake native I/O."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_source_copy_saved_continuation_gateway import saved_source_task
    from tests.unit.test_legacy_source_copy_collector import SOURCE, COPIED, DEST, SAVED_ROLES
    from tests.destructive.support import source_copy_fixture as fixture
    runtime, writes, task = saved_source_task(tmp_path)
    del task.objects[DEST]
    root = task.project_file.parent
    io = tmp_path / 'prelaunch-io'; io.mkdir()
    runtime.sandbox.source_root = Path(__file__).parents[1] / '_org/2021.1'
    runtime.source_copy_prelaunch = fixture.prepare_repeated_source_fixture(runtime.sandbox, owned_root=tmp_path, io_root=io)
    path = root / fixture.MIDI
    nodes = fixture.source_graph([path.read_bytes()], fixture.SOURCE, fixture.SOURCE_OWNER)
    unit_id = task.objects[SOURCE]['workunit']['id']
    # Preserve all seven actual original root declarations in the fake live
    # childset, including its six BlendContainers.
    unit_xml = next(ET.fromstring(path.read_bytes()).iter('WorkUnit'))
    for child in unit_xml.find('ChildrenList'):
        if child.get('ID') not in task.objects:
            task.objects[child.get('ID')] = {'id': child.get('ID'), 'name': child.get('Name'), 'type': child.tag, 'classId': 1900560, 'path': task.objects[unit_id]['path'] + '\\' + child.get('Name'), 'parent': {'id': unit_id}, 'notes': '', 'shortId': 0}
    mapping = {binding[0]: binding[1] for binding in SAVED_ROLES.values()}
    # saved_source_task uses the matching SDK Source field types plus original
    # MIDI overrides and retained native owned metadata/values (LFO4.0,Flags3).
    # The donor byte-preserves those same overrides; only native identities differ.
    donor_roles = {}
    for index, kind in enumerate(('rtpc', 'control', 'curve')):
        node = nodes['Osc1Level.' + kind]
        prototype = SAVED_ROLES[{'rtpc': 'rtpc', 'control': 'control_input', 'curve': 'curve'}[kind]][0]
        identity = node.get('ID'); row = deepcopy(task.objects[prototype]); row['id'] = identity
        row['shortId'] = int(node.get('ShortID', '0'))
        row['owner'] = {'id': SOURCE if kind == 'rtpc' else nodes['Osc1Level.rtpc'].get('ID')}
        task.objects[identity] = row
        mapping[identity] = '{' + str(uuid.UUID(int=0x59000000000000000000000000000000 + index)).upper() + '}'
        donor_roles[identity] = donor_roles[mapping[identity]] = prototype
    if fault == 'consistent-wrong-scalar':
        task.objects[nodes['Osc1Level.control'].get('ID')]['@LfoFrequency'] = 99.0
    original = task.call; native_calls = []
    def observed(uri, args=None, options=None):
        args = args or {}; native_calls.append((uri, deepcopy(args), deepcopy(options)))
        if fault == 'consistent-wrong-type' and uri.endswith('getPropertyInfo') and args.get('object') == SOURCE and args.get('property') == 'FrequencyMode':
            result = deepcopy(original(uri, args, options)); result['type'] = 'Real32'
            return result
        if uri.endswith(('getPropertyAndReferenceNames', 'getPropertyInfo')) and args.get('object') in donor_roles:
            return original(uri, {**args, 'object': donor_roles[args['object']]}, options)
        if uri.endswith('object.get') and ' select @ControlInput ' in args.get('waql', ''):
            identity = args['waql'].split('"')[1]
            hop = {nodes['Osc1Level.rtpc'].get('ID'): nodes['Osc1Level.control'].get('ID')}
            hop.update({mapping[key]: mapping[value] for key, value in list(hop.items())})
            if identity in hop: return {'return': task.project_rows([task.objects[hop[identity]]], options)}
        if uri.endswith('project.save'):
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, {}))
            document = ET.parse(path); unit = next(document.iter('WorkUnit')); children = unit.find('ChildrenList')
            if fault != 'missing-serialization':
                for row in task.objects.values():
                    if row.get('parent') == {'id': unit_id} and row['type'] == 'Sound' and row['id'] != fixture.SOURCE_OWNER:
                        if not any(node.get('ID') == row['id'] for node in children):
                            ET.SubElement(children, 'Sound', {'ID': row['id'], 'Name': row['name']})
                if COPIED in task.objects:
                    copied = deepcopy(nodes['source'])
                    for node in copied.iter():
                        if node.get('ID') in mapping:
                            node.set('ID', mapping[node.get('ID')])
                            if 'ShortID' in node.attrib: node.set('ShortID', str(task.objects[node.get('ID')]['shortId']))
                    destination = next(node for node in children if node.get('ID') == task.objects[COPIED]['parent']['id'])
                    ET.SubElement(destination, 'ChildrenList').append(copied)
                if fault == 'lost-graph':
                    source = next(node for node in document.iter('SourcePlugin') if node.get('ID') == SOURCE)
                    source.find("PropertyList/Property[@Name='Osc1Level']/RTPCList").clear()
                if fault == 'lost-root-child' and COPIED in task.objects:
                    children.remove(next(node for node in children if node.tag == 'BlendContainer'))
                document.write(path)
            for key in (unit_id,): task.objects[key]['workunitIsDirty'] = False
            return {}
        result = original(uri, args, options)
        if uri.endswith('object.create'):
            row = task.objects[result['id']]
            row.update(workunit={'id': args['parent']}, filePath=task.objects[args['parent']]['filePath'])
            task.objects[args['parent']]['workunitIsDirty'] = True
        if uri.endswith('object.copy'):
            for identity in [node.get('ID') for key, node in nodes.items() if key.startswith('Osc1Level')]:
                row = deepcopy(task.objects[identity]); row.update(id=mapping[identity], shortId=row['shortId'] + 1000)
                row['owner'] = {'id': mapping[row['owner']['id']]}; task.objects[row['id']] = row
            task.objects[COPIED].update(filePath=str(path), workunit={'id': unit_id})
        return result
    task.call = observed
    runtime.fixture_native_calls = native_calls
    return runtime, writes, task


def test_repeated_collector_gates_copy_on_actual_baseline_serialization(tmp_path, workflow):
    from tests.destructive.support.source_copy_fixture import PROFILE
    runtime, writes, task = repeated_collector_runtime(tmp_path)
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='REPEATED_SOURCE', saved_copy=True,
        saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=PROFILE)
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS'
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'save', 'copy', 'save']
    acceptance = receipt['fixture_acceptance']
    assert acceptance['status'] == 'accepted'
    expected = acceptance['serialized_scalar_authority']
    assert expected['source']['Osc1Pwm'] == {'type': 'Real32', 'serialized_value': '12', 'expected_value': 12.0}
    assert expected['source']['FrequencyMode']['expected_value'] == 1
    for prop in ('OutputLevel', 'Osc1Level'):
        assert expected[prop + '.control']['LfoFrequency'] == {'type': 'Real64', 'serialized_value': '4', 'expected_value': 4.0}
        assert expected[prop + '.curve']['Flags'] == {'type': 'int32', 'serialized_value': '3', 'expected_value': 3}
    for key in ('loaded_scalar_observation', 'scalar_observation'):
        snapshots = json.loads(Path(acceptance[key]['path']).read_text())
        for snapshot in snapshots.values():
            assert set(snapshot['values']) == set(snapshot['metadata']) == set(snapshot['native_metadata_authority'])
            assert all(snapshot['native_metadata_authority'].values())
    assert all(index['complete'] and index['file_count'] == 1 for index in receipt['model_images'].values())
    assert len(receipt['oracle']['persisted_root_child_ids']) == 8
    assert receipt['oracle']['saved_file_identity'] == 'Actor-Mixer Hierarchy/MIDI.wwu'
    assert receipt['oracle']['ordered_point_count'] == 4 and len(receipt['oracle']['owned_guid_mapping']) == 7
    assert receipt['budget']['unique_transactions'] == 4
    assert receipt['budget']['native_calls'] == len(runtime.fixture_native_calls)
    assert receipt['budget']['public_calls'] <= 160 and receipt['budget']['native_files_including_index'] <= 1280
    assert receipt['limits']['calls'] == 160 and receipt['limits']['native_files'] == 1280
    scope, = [row['gateway_verification_scope'] for row in receipt['phases'] if row['name'] == 'copy_source_only']
    assert scope['complete_copy_preservation'] is True and scope['owned_role_count'] == 6
    copy_preview_index, = [index for index, row in enumerate(receipt['calls']) if row['argv'][:2] == ['preview-from-draft', receipt['copy_draft_id']]]
    assert receipt['fixture_acceptance']['accepted_at_call_index'] < copy_preview_index
    artifact_files = [path for path in Path(category['observation_path']).with_name('repeated-source-copy-save-children-artifacts').rglob('*') if path.is_file()]
    assert receipt['budget']['archive_files'] == len(artifact_files)
    assert receipt['budget']['archive_bytes'] == sum(path.stat().st_size for path in artifact_files)
    print('R57 actual repeated collector budget:', json.dumps(receipt['budget']))
    (tmp_path / 'repeated-budget.json').write_text(json.dumps(receipt['budget'], indent=2))


@pytest.mark.parametrize('fault', ['missing-serialization', 'lost-graph'])
def test_repeated_fixture_acceptance_blocks_copy_preview_on_unsaved_or_lost_graph(tmp_path, workflow, fault):
    from tests.destructive.support.source_copy_fixture import PROFILE
    runtime, writes, task = repeated_collector_runtime(tmp_path, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='REPEATED_SOURCE', saved_copy=True,
            saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=PROFILE)
    receipt = json.loads((runtime.state_dir / 'repeated-source-copy-save-children.json').read_text())
    assert receipt['collection_complete'] is False and receipt['failure']
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'save']
    assert len(receipt['transaction_ids']) == 2
    assert [row['name'] for row in receipt['phases']] == ['create_empty_destination', 'save_baseline']
    assert len([row for row in receipt['calls'] if row['argv'][0] == 'preview-from-draft']) == 2
    assert receipt.get('fixture_acceptance', {}).get('status') != 'accepted'
    assert runtime.category_results[0]['status'] == 'FAIL'


@pytest.mark.parametrize('fault', ['consistent-wrong-scalar', 'consistent-wrong-type'])
def test_repeated_fixture_rejects_consistent_native_scalar_disagreement(tmp_path, workflow, fault):
    from tests.destructive.support.source_copy_fixture import PROFILE
    runtime, writes, task = repeated_collector_runtime(tmp_path, fault=fault)
    with pytest.raises(AssertionError, match='serialized scalar'):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='REPEATED_SOURCE', saved_copy=True,
            saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=PROFILE)
    receipt = json.loads((runtime.state_dir / 'repeated-source-copy-save-children.json').read_text())
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'save']
    assert receipt['collection_complete'] is False
    if fault == 'consistent-wrong-scalar':
        observed = [json.loads(Path(row['reply']['path']).read_text())['objects'][0]['properties']['LfoFrequency']
            for row in receipt['calls'] if row['argv'][0] == 'query-object' and 'LfoFrequency' in row['argv']
            and '{2B5446C9-CC6F-4AAB-88F2-89E6BC10427E}' in row['argv']]
        assert observed == [99.0, 99.0]  # Both phases agree, pinned XML says4.
    assert receipt.get('fixture_acceptance', {}).get('status') != 'accepted'
    assert len([row for row in receipt['calls'] if row['argv'][0] == 'preview-from-draft']) == 2


@pytest.mark.parametrize('fault', ['wrong-file', 'second-file', 'lost-root-child'])
def test_repeated_saved_oracle_rejects_changed_file_or_persisted_root_scope(tmp_path, workflow, monkeypatch, fault):
    from copy import deepcopy
    from tests.destructive.support.source_copy_fixture import PROFILE
    from tests.destructive.support.console_file_observation import ConsoleModelImageIndex
    runtime, writes, task = repeated_collector_runtime(tmp_path, fault=fault)
    finish = ConsoleModelImageIndex.finish
    def altered_index(index):
        if index.phase == 'after' and fault in {'wrong-file', 'second-file'}:
            entry = deepcopy(index.files['Actor-Mixer Hierarchy/MIDI.wwu'])
            if fault == 'wrong-file': index.files.clear()
            index.files['Actor-Mixer Hierarchy/Other.wwu'] = entry
        return finish(index)
    monkeypatch.setattr(ConsoleModelImageIndex, 'finish', altered_index)
    with pytest.raises(AssertionError, match='accepted MIDI file/index|Serialized MIDI root membership'):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='REPEATED_SOURCE', saved_copy=True,
            saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=PROFILE)
    receipt = json.loads((runtime.state_dir / 'repeated-source-copy-save-children.json').read_text())
    assert receipt['fixture_acceptance']['status'] == 'accepted'
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'save', 'copy', 'save']
    assert receipt['collection_complete'] is False and receipt['saved_copy_verified'] is False
