"""Modern original fixtures through the actual public Save-child collector."""
from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tests.unit.test_workflow_source_guard import workflow
from tests.unit.test_source_copy_saved_continuation_gateway import modern_saved_source_task
from tests.unit.test_legacy_source_copy_collector import SOURCE, COPIED, DEST, SAVED_OWNER, SAVED_ROLES

PROFILE = 'modern-original-owned-source/v1'


def modern_collector_runtime(tmp_path, version='2022.1', *, fault=None):
    runtime, writes, task = modern_saved_source_task(tmp_path, version)
    del task.objects[DEST]
    folder = 'Containers' if version == '2025.1' else 'Actor-Mixer Hierarchy'
    relative = Path(folder) / 'MIDI.wwu'
    source_root = Path(__file__).parents[1] / '_org' / version
    path = task.project_file.parent / relative
    path.parent.mkdir(exist_ok=True)
    path.write_bytes((source_root / relative).read_bytes())
    runtime.sandbox.source_root = source_root
    document = ET.parse(path)
    unit = next(document.iter('WorkUnit')); unit_id = unit.get('ID')
    source = next(node for node in document.iter('SourcePlugin') if node.get('ID') == SOURCE)
    task.objects[unit_id].update(filePath=str(path), path='\\' + folder + '\\MIDI')
    for identity in (SOURCE, SAVED_OWNER):
        task.objects[identity].update(filePath=str(path), workunit={'id': unit_id})
    for node in unit.find('ChildrenList'):
        if node.get('ID') not in task.objects:
            task.objects[node.get('ID')] = {'id': node.get('ID'), 'name': node.get('Name'),
                'type': node.tag, 'classId': 1900560, 'parent': {'id': unit_id},
                'path': task.objects[unit_id]['path'] + '\\' + node.get('Name'), 'notes': ''}
    mapping = {value[0]: value[1] for value in SAVED_ROLES.values()}
    # Accepted919 probe returns a named ControlInput reference; Curve instead
    # returns id/points/@Flags. Preserve these distinct native shapes.
    task.objects[SAVED_ROLES['rtpc'][0]]['@ControlInput']['name'] = task.objects[SAVED_ROLES['control_input'][0]]['name']
    points = deepcopy(task.objects[SAVED_ROLES['rtpc'][0]]['@Curve']['points'])
    task.objects[SAVED_ROLES['curve'][0]]['points'] = points
    if fault == 'consistent-wrong-scalar':
        task.objects[SAVED_ROLES['control_input'][0]]['@LfoFrequency'] = 99.0
    original = task.call
    native_calls = []
    def observed(uri, args=None, options=None):
        args, options = args or {}, options or {}
        native_calls.append((uri, deepcopy(args), deepcopy(options)))
        if uri.endswith('project.save'):
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, {}))
            current = ET.parse(path); children = next(current.iter('WorkUnit')).find('ChildrenList')
            for row in task.objects.values():
                if row.get('parent') == {'id': unit_id} and row['type'] == 'Sound' and row['id'] != SAVED_OWNER:
                    if not any(node.get('ID') == row['id'] for node in children):
                        ET.SubElement(children, 'Sound', {'ID': row['id'], 'Name': row['name']})
            if COPIED in task.objects:
                copied = deepcopy(source)
                for node in copied.iter():
                    if node.get('ID') in mapping:
                        node.set('ID', mapping[node.get('ID')])
                        if 'ShortID' in node.attrib: node.set('ShortID', str(task.objects[node.get('ID')]['shortId']))
                destination = next(node for node in children if node.get('ID') == task.objects[COPIED]['parent']['id'])
                ET.SubElement(destination, 'ChildrenList').append(copied)
            if fault == 'reordered-root' and COPIED in task.objects:
                children[:] = list(reversed(children))
            current.write(path)
            task.objects[unit_id]['workunitIsDirty'] = False
            return {}
        result = original(uri, args, options)
        if uri.endswith('object.create'):
            task.objects[result['id']].update(workunit={'id': args['parent']}, filePath=task.objects[args['parent']]['filePath'])
            task.objects[args['parent']]['workunitIsDirty'] = True
        if uri.endswith('object.copy'):
            task.objects[COPIED].update(filePath=str(path), workunit={'id': unit_id})
            task.objects[SAVED_ROLES['curve'][1]]['points'] = deepcopy(points)
            task.objects[SAVED_ROLES['rtpc'][1]]['@ControlInput']['name'] = task.objects[SAVED_ROLES['control_input'][1]]['name']
        return result
    task.call = observed
    runtime.fixture_native_calls = native_calls
    return runtime, writes, task


def test_modern_collector_2022_preserves_original_graph_through_four_transactions(tmp_path, workflow):
    runtime, writes, task = modern_collector_runtime(tmp_path)
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='MODERN_SOURCE', saved_copy=True,
        saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=PROFILE)
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS' and receipt['saved_copy_verified'] is True
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'save', 'copy', 'save']
    assert receipt['budget']['unique_transactions'] == 4
    assert receipt['budget']['native_calls'] == len(runtime.fixture_native_calls)
    assert receipt['oracle']['ordered_point_count'] == 2
    assert len(receipt['oracle']['owned_guid_mapping']) == 4
    assert receipt['oracle']['saved_file_identity'] == 'Actor-Mixer Hierarchy/MIDI.wwu'
    assert len(receipt['oracle']['persisted_root_child_ids']) == 8
    assert all(row['file_count'] == 1 and row['complete'] for row in receipt['model_images'].values())
    acceptance = receipt['fixture_acceptance']
    assert acceptance['serialized_scalar_authority']['control_input']['LfoFrequency']['expected_value'] == 4.0
    for key in ('loaded_scalar_observation', 'scalar_observation'):
        snapshots = json.loads(Path(acceptance[key]['path']).read_text())
        assert {role: len(row['names']) for role, row in snapshots.items()} == {'source': 18, 'rtpc': 5, 'control_input': 10, 'curve': 1}
        assert all(set(row['metadata']) == set(row['native_metadata_authority']) for row in snapshots.values())
    assert not any(row['argv'][:2] == ['metadata', 'detail'] for row in receipt['calls'])
    copy_preview, = [i for i, row in enumerate(receipt['calls']) if row['argv'][:2] == ['preview-from-draft', receipt['copy_draft_id']]]
    assert acceptance['accepted_at_call_index'] < copy_preview
    print('R58 modern2022 collector budget:', json.dumps(receipt['budget']))


def test_modern_collector_rejects_stable_scalar_disagreement_before_copy_preview(tmp_path, workflow):
    runtime, writes, task = modern_collector_runtime(tmp_path, fault='consistent-wrong-scalar')
    with pytest.raises(AssertionError, match='serialized scalar value differs'):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='MODERN_SOURCE', saved_copy=True,
            saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=PROFILE)
    receipt = json.loads((runtime.state_dir / 'modern-source-copy-save-children.json').read_text())
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'save']
    assert receipt['fixture_acceptance']['status'] != 'accepted'
    assert len([row for row in receipt['calls'] if row['argv'][0] == 'preview-from-draft']) == 2
    assert not any(row['argv'][:2] == ['metadata', 'detail'] for row in receipt['calls'])


def test_modern_collector_2025_preserves_native_crlf_and_direct_rtpc_through_four_transactions(tmp_path, workflow):
    runtime, writes, task = modern_collector_runtime(tmp_path, '2025.1')
    notes_before = task.objects[SOURCE]['notes']
    assert notes_before.count('\r\n') == 8
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='MODERN_SOURCE', saved_copy=True,
        saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=PROFILE)
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS' and receipt['saved_copy_verified'] is True
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'save', 'copy', 'save']
    assert task.objects[SOURCE]['notes'] == task.objects[COPIED]['notes'] == notes_before
    assert receipt['oracle']['saved_file_identity'] == 'Containers/MIDI.wwu'
    assert receipt['oracle']['copied_native_fields_preserved'] is True
    assert receipt['native_build'] == '2025.1.7.9143'
    assert receipt['budget']['unique_transactions'] == 4
    assert receipt['budget']['native_calls'] == len(runtime.fixture_native_calls)
    assert receipt['budget']['public_calls'] <= receipt['limits']['calls'] == 160
    assert receipt['budget']['native_files_including_index'] <= receipt['limits']['native_files'] == 1280
    assert not any(row['argv'][:2] == ['metadata', 'detail'] for row in receipt['calls'])
    index_path = receipt['model_images']['after']['index_path']
    index = json.loads(Path(index_path).read_text())
    image = Path(index_path).parent / 'files' / 'Containers/MIDI.wwu'
    assert set(index['files']) == {'Containers/MIDI.wwu'}
    document = ET.fromstring(image.read_bytes())
    sources = [node for node in document.iter('SourcePlugin') if node.get('ID') in {SOURCE, COPIED}]
    assert len(sources) == 2
    assert all(node.find('ObjectLists/ObjectList/RTPC') is not None for node in sources)
    assert all(node.findtext('Comment') == notes_before.replace('\r\n', '\n') for node in sources)
    raw_native_notes = [json.loads(Path(row['reply']['path']).read_text())['objects'][0]['notes']
        for row in receipt['calls'] if row['argv'][:3] == ['query-object', '--exact-id', SOURCE]
        and '--include-field' in row['argv']]
    assert raw_native_notes and all(value == notes_before for value in raw_native_notes)
    print('R58 modern2025 collector budget:', json.dumps(receipt['budget']))


@pytest.mark.parametrize(('version', 'build'), [('2023.1', '2023.1.19.8928'), ('2024.1', '2024.1.13.9056')])
def test_modern_intermediate_versions_bind_native_build_and_local_saved_grammar(tmp_path, workflow, version, build):
    from tests.destructive.support.source_copy_fixture import MODERN_ORIGINALS, source_graph, sha
    from tests.semantic.support.typed_gateway_input import create_object_lifecycle_business_preview
    runtime, writes, task = modern_saved_source_task(tmp_path, version)
    expected_build, relative, digest = MODERN_ORIGINALS[version]
    assert expected_build == build
    raw = (Path(__file__).parents[1] / '_org' / version / relative).read_bytes()
    assert sha(raw) == digest
    nodes = source_graph([raw], SOURCE, SAVED_OWNER, version=version)
    assert nodes['rtpc'].get('ID') == SAVED_ROLES['rtpc'][0]
    assert nodes['source'].find('ObjectLists/ObjectList/Reference/Local/RTPC') is nodes['rtpc']
    def gateway(argv):
        code, payload = task.run(*argv); assert code == 0, payload
        return payload
    preview = create_object_lifecycle_business_preview(gateway, version=version,
        operation='object.copy', object_id=SOURCE, parent_id=DEST, name_conflict='fail')
    artifact = gateway(['transaction-show', preview['transaction_id']])['artifact']
    assert artifact['prepared_operation']['dispatch']['args'] == {'object': SOURCE, 'parent': DEST,
        'onNameConflict': 'fail', 'autoAddToSourceControl': False, 'autoCheckOutToSourceControl': False}
    proof = artifact['prepared_operation']['pre_state']['source_copy_saved_proof']
    assert proof['status'] == 'ready' and len(proof['role_ids']) == 4
    assert writes == []


@pytest.mark.parametrize('fault', ['wrong-Curve-hop', 'saturated-membership', 'invalid-point-number'])
def test_modern_canonical_owned_reads_reject_otherwise_valid_graph_before_changes(tmp_path, workflow, fault):
    runtime, writes, task = modern_collector_runtime(tmp_path)
    if fault == 'invalid-point-number':
        task.objects[SAVED_ROLES['curve'][0]]['points'][0]['x'] = False
        task.objects[SAVED_ROLES['rtpc'][0]]['@Curve']['points'][0]['x'] = False
    call = task.call
    def corrupted(uri, args=None, options=None):
        result = call(uri, args, options)
        expression = (args or {}).get('waql', '')
        if uri.endswith('object.get') and fault == 'wrong-Curve-hop' and ' select @Curve ' in expression:
            return {'return': task.project_rows([task.objects[SAVED_ROLES['control_input'][0]]], options)}
        if uri.endswith('object.get') and fault == 'saturated-membership' and ' select @RTPC ' in expression:
            result['return'] *= 2
        return result
    task.call = corrupted
    with pytest.raises(AssertionError):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='MODERN_SOURCE', saved_copy=True,
            saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=PROFILE)
    receipt = json.loads((runtime.state_dir / 'modern-source-copy-save-children.json').read_text())
    assert not writes and not receipt['transaction_ids']
    assert receipt['collection_complete'] is False and receipt['failure']


def test_modern_saved_oracle_rejects_root_reordering_independently_of_runtime_proof(tmp_path, workflow):
    runtime, writes, task = modern_collector_runtime(tmp_path, fault='reordered-root')
    with pytest.raises(AssertionError, match='Saved MIDI root order changed'):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='MODERN_SOURCE', saved_copy=True,
            saved_copy_protocol='gateway-owned-save-children/v1', fixture_profile=PROFILE)
    receipt = json.loads((runtime.state_dir / 'modern-source-copy-save-children.json').read_text())
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'save', 'copy', 'save']
    phase, = [row for row in receipt['phases'] if row['name'] == 'copy_source_only']
    assert phase['gateway_verification_scope']['complete_copy_preservation'] is True
    assert receipt['saved_copy_verified'] is False and receipt['collection_complete'] is False


def test_modern_independent_oracle_rejects_native_notes_change_that_xml_parsing_hides():
    from tests.destructive.support.source_copy_fixture import source_graph, repeated_copy_oracle
    from tests.unit.test_legacy_source_copy_collector import SAVED_ROLES
    raw = (Path(__file__).parents[1] / '_org/2025.1/Containers/MIDI.wwu').read_bytes()
    before_nodes = source_graph([raw], SOURCE, SAVED_OWNER, version='2025.1')
    after = ET.fromstring(raw)
    children = next(after.iter('WorkUnit')).find('ChildrenList')
    destination = ET.SubElement(children, 'Sound', {'ID': DEST, 'Name': 'Destination'})
    copied = deepcopy(before_nodes['source'])
    bindings = {binding[0]: binding[1] for binding in SAVED_ROLES.values()}
    short_ids = {binding[1]: binding[5] for binding in SAVED_ROLES.values()}
    for node in copied.iter():
        if node.get('ID') in bindings:
            node.set('ID', bindings[node.get('ID')])
            if 'ShortID' in node.attrib: node.set('ShortID', str(short_ids[node.get('ID')]))
    ET.SubElement(destination, 'ChildrenList').append(copied)
    after_raw = ET.tostring(after)
    copied_nodes = source_graph([after_raw], COPIED, DEST, version='2025.1')
    def frames(nodes, owner):
        rows = {}
        for role, node in nodes.items():
            binding = SAVED_ROLES[role]
            row = {'id': node.get('ID'), 'name': node.get('Name'), 'type': node.tag, 'class_id': binding[3],
                'notes': node.findtext('Comment', '').replace('\n', '\r\n')}
            row['parent' if role == 'source' else 'owner'] = {'id': owner if role == 'source' else nodes['source' if role == 'rtpc' else 'rtpc'].get('ID')}
            if 'ShortID' in node.attrib: row['short_id'] = int(node.get('ShortID'))
            rows[role] = row
        return rows
    before_live, copied_live = frames(before_nodes, SAVED_OWNER), frames(copied_nodes, DEST)
    assert repeated_copy_oracle([raw], [after_raw], source_id=SOURCE, copied_id=COPIED,
        original_owner_id=SAVED_OWNER, destination_id=DEST, before_live=before_live, copied_live=copied_live,
        version='2025.1')['original_preserved'] is True
    copied_live['source']['notes'] = copied_live['source']['notes'].replace('\r\n', '\n')
    with pytest.raises(AssertionError, match='Copied native notes differ'):
        repeated_copy_oracle([raw], [after_raw], source_id=SOURCE, copied_id=COPIED,
            original_owner_id=SAVED_OWNER, destination_id=DEST, before_live=before_live, copied_live=copied_live, version='2025.1')
