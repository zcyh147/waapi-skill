"""Public admission and diagnostic collection; no native copy claim from fakes."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.test_workflow_source_guard import workflow
from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND

SOURCE = '{95DDA32B-B666-4269-A54C-5ABF4E201C99}'
COPIED = '{ACACACAC-ACAC-ACAC-ACAC-ACACACACACAC}'
DEST = '{DADADADA-DADA-DADA-DADA-DADADADADADA}'


def legacy_runtime(tmp_path, *, fault=None):
    task = OwnedGraphTask(tmp_path, '2021.1', 'object.copy')
    catalog = Path(__file__).parents[2] / 'skills/waapi-skill/resources/metadata/2021.1/object-types.json'
    task.types = json.loads(catalog.read_text())['types']
    task.creation_classes.update(Sound=65552, WorkUnit=1638416)
    task.objects = {
        SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
            'path': r'\Actor-Mixer Hierarchy\Default Work Unit', 'parent': None, 'notes': ''},
        FIRST: {'id': FIRST, 'name': 'Existing Synth owner', 'type': 'Sound', 'classId': 65552,
            'path': r'\Actor-Mixer Hierarchy\MIDI\Existing Synth owner', 'parent': {'id': SECOND},
            'notes': 'Keep owner', '@IsVoice': False},
        SOURCE: {'id': SOURCE, 'name': 'Wwise Synth One', 'type': 'SourcePlugin', 'classId': 9699330,
            'path': r'\Actor-Mixer Hierarchy\MIDI\Existing Synth owner\Wwise Synth One',
            'parent': {'id': FIRST}, 'notes': 'Keep Source', '@Osc1Transpose': -1200,
            'audioSource:language': {'name': 'SFX'}},
        DEST: {'id': DEST, 'name': 'Empty SFX destination', 'type': 'Sound', 'classId': 65552,
            'path': r'\Actor-Mixer Hierarchy\Default Work Unit\Empty SFX destination',
            'parent': {'id': SECOND}, 'notes': '', '@IsVoice': False}}
    # This fake observes one real Synth field from MIDI.wwu:12187. It does not
    # claim a complete native Synth catalog; the collector lists live names.
    task.metadata = {'Osc1Transpose': {'name': 'Osc1Transpose', 'type': 'int32'},
                     'IsVoice': {'name': 'IsVoice', 'type': 'bool', 'default': False}}
    task.env['WWISE_EVIDENCE_DIR'] = str(tmp_path / 'native')
    Path(task.env['WWISE_EVIDENCE_DIR']).mkdir()
    task.env['WWISE_CATEGORY_EVIDENCE_PATH'] = str(tmp_path / 'category.jsonl')
    original = task.call
    writes, commands = [], []
    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith('object.copy'):
            writes.append((uri, deepcopy(args)))
            if fault == 'native-error':
                raise RuntimeError('Source-only copy rejected; do not retry')
            row = deepcopy(task.objects[args['object']])
            row.update(id=COPIED, parent={'id': args['parent']},
                path=task.objects[args['parent']]['path'] + '\\' + row['name'])
            task.objects[COPIED] = row
            if fault == 'copied-class': task.objects[COPIED]['classId'] = 6619138
            if fault == 'original-field': task.objects[SOURCE]['@Osc1Transpose'] = 0
            if fault == 'owner-voice': task.objects[FIRST]['@IsVoice'] = True
            return {'id': COPIED, 'name': row['name']}
        if uri.endswith('getPropertyAndReferenceNames'):
            row = task.objects.get(args['object'], {})
            return {'return': [key[1:] for key in row if key.startswith('@')]}
        if uri.endswith('object.get') and args.get('transform') == [{'select': ['children']}, {'range': [0, 130]}]:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            identity = args['from']['id'][0]
            children = [row for row in task.objects.values() if row.get('parent') == {'id': identity}]
            return {'return': task.project_rows(children[:130], options)}
        if uri.endswith('object.get') and args.get('waql', '').startswith('from object "'):
            expression = args['waql']; identity = expression.split('"')[1]
            rows = [row for row in task.objects.values() if row['id'] == identity or row['path'] == identity]
            if ' select children ' in expression:
                rows = [row for row in task.objects.values() if row.get('parent') == {'id': identity}]
            elif ' select descendants ' in expression:
                root, = rows
                rows = [row for row in task.objects.values() if row['path'].startswith(root['path'] + '\\')]
            return {'return': task.project_rows(rows, options)}
        result = original(uri, args, options)
        if uri.endswith('getInfo'):
            result['version'].update(minor=14, build=8108, displayName='v2021.1.14.8108')
        if uri.endswith('object.create'):
            writes.append((uri, deepcopy(args)))
            task.objects[result['id']]['@IsVoice'] = False
        return result
    task.call = call
    runtime = SimpleNamespace(version='2021.1', candidate='a' * 40, category_results=[],
        state_dir=tmp_path / 'state', env=task.env, port=31337,
        sandbox=SimpleNamespace(source_project=task.project_file),
        lifecycle=SimpleNamespace(host='127.0.0.1', port=31337, waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw(argv):
        commands.append(list(argv)); return task.run(*argv)
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


def test_existing_2021_public_copy_admits_bound_source_and_sound(tmp_path, workflow):
    runtime, commands, writes, task = legacy_runtime(tmp_path)
    from tests.semantic.support.typed_gateway_input import create_object_lifecycle_business_preview
    def gateway(argv):
        code, payload = runtime.raw_gateway(argv)
        assert code == 0, json.dumps(payload, ensure_ascii=False)
        return payload
    preview = create_object_lifecycle_business_preview(
        gateway,
        version='2021.1', operation='object.copy', object_id=SOURCE, parent_id=DEST, name_conflict='fail')
    assert preview['transaction_id'] and writes == []


def test_legacy_source_copy_fresh_lifecycle_initializes_state(tmp_path, workflow):
    import shutil
    runtime, commands, writes, task = legacy_runtime(tmp_path)
    shutil.rmtree(runtime.state_dir)  # Only this test's preliminary fake Draft.
    assert not runtime.state_dir.exists()
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='WAAPI_FRESH_STATE')
    assert category['status'] == 'PASS'
    assert (runtime.state_dir / 'legacy-source-copy-feasibility.json').is_file()


@pytest.mark.parametrize('fault', [None, 'original-field', 'owner-voice'])
def test_legacy_source_copy_pages_all_documented_synth_read_fields(tmp_path, workflow, fault):
    runtime, commands, writes, task = legacy_runtime(tmp_path, fault=fault)
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/synth-one-2021-sdk-read-fields.json').read_text())
    assert fixture['class'] == {'name': 'Wwise Synth One', 'classId': 9699330, 'type': 'Source'}
    names = []
    for row in fixture['properties']:
        name, kind, value = row['name'], row['type'], row['sdk_default_text']
        names.append(name)
        task.metadata[name] = {'name': name, 'type': kind, 'display': {'name': row['display_name']}}
        # Fake read observations from matching SDK values, not production defaults.
        task.objects[SOURCE].setdefault('@' + name, bool(int(value)) if kind == 'bool' else
            int(value) if kind == 'int32' else float(value))
    assert len(names) == 18
    if fault is None:
        category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='WAAPI_SYNTH_FIELDS')
        assert category['status'] == 'PASS'
        # Full Source observations stay paged; owners need only exact frames.
        assert len(commands) == 55
        receipt_path = Path(category['observation_path'])
        receipt = json.loads(receipt_path.read_text())
        index = json.loads(Path(receipt['native_file_proofs']['path']).read_text())
        assert receipt['contract'] == 'waapi-skill.legacy-source-copy-feasibility/v2'
        assert index['count'] == len(receipt['native_evidence'])
        assert len(receipt['native_evidence']) + 1 <= receipt['limits']['native_files'] == 512
        assert receipt_path.stat().st_size <= receipt['limits']['receipt_bytes'] == 256 * 1024
        assert [row['archive'] for row in index['files']] == receipt['native_evidence']
        for row in index['files']:
            raw = Path(row['archive']['path']).read_bytes()
            assert raw == Path(row['native_file_proof']['path']).read_bytes()
            assert row['archive']['sha256'] == row['native_file_proof']['sha256']
        print('R55 normal indexed receipt:', receipt_path.stat().st_size, 'bytes;', index['count'], 'native proofs')
        receipt = json.loads(Path(category['observation_path']).read_text())
        owner_ids = {FIRST, receipt['destination_id']}
        assert not any(argv[:2] == ['metadata', 'list'] and any(identity in argv for identity in owner_ids)
            for argv in commands)
        owner_reads = [argv for argv in commands if argv[0] == 'query-object' and '--include-field' in argv
            and any(identity in argv for identity in owner_ids)]
        assert len(owner_reads) == 4 and all(argv.count('--include-field') == 1
            and argv[argv.index('--include-field') + 1] == 'IsVoice' for argv in owner_reads)
    else:
        if fault == 'original-field':
            # Osc1Transpose lies on page2 of the genuine SDK field list.
            assert names.index('Osc1Transpose') >= 8
        with pytest.raises(AssertionError):
            workflow._collect_legacy_source_copy_feasibility(runtime, prefix='WAAPI_SYNTH_FIELDS')
        assert len([uri for uri, _ in writes if uri.endswith('object.copy')]) == 1
        receipt = json.loads((runtime.state_dir / 'legacy-source-copy-feasibility.json').read_text())
        failed = _failed_source_copy_verify(receipt)
        expected = ('original Source fields and frame are unchanged' if fault == 'original-field' else 'Source-copy owner frame unchanged: ' + FIRST)
        assert any(row['name'] == expected and row['passed'] is False for row in failed['verification']['assertions'])
        assert receipt['native_admission_verified'] is False and receipt['collection_complete'] is False
        if fault == 'owner-voice':
            receipt = json.loads((runtime.state_dir / 'legacy-source-copy-feasibility.json').read_text())
            owner_reads = [json.loads(Path(row['reply']['path']).read_text()) for row in receipt['calls']
                if row['argv'][0] == 'query-object' and FIRST in row['argv'] and '--include-field' in row['argv']]
            # The production verifier catches corruption before collector re-read.
            assert [row['objects'][0]['properties']['IsVoice'] for row in owner_reads] == [False]
            assert task.objects[SOURCE]['@Osc1Transpose'] == -1200
    pages = [argv for argv in commands if argv[0] == 'query-object' and SOURCE in argv and '--include-field' in argv]
    assert len(pages) >= 3 and all(argv.count('--include-field') <= 8 for argv in pages)
    assert {argv[index + 1] for argv in pages for index, token in enumerate(argv) if token == '--include-field'} == set(names)


def test_legacy_source_copy_collector_records_admission_without_full_copy_claim(tmp_path, workflow, request):
    runtime, commands, writes, task = legacy_runtime(tmp_path)
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='WAAPI_LEGACY_COPY')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS' and receipt['native_admission_verified'] is True
    assert receipt['business_effect_verified'] is False and receipt['diagnostic_only'] is True
    assert receipt['contract'] == 'waapi-skill.legacy-source-copy-feasibility/v2'
    assert receipt['native_evidence_storage'] == 'indexed-native-file-proofs/v1'
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'copy']
    assert writes[1][1] == {'object': SOURCE, 'parent': receipt['destination_id'], 'onNameConflict': 'fail'}
    assert receipt['copy_observation']['new_id'] == COPIED
    assert receipt['copy_observation']['class_id'] == 9699330
    assert all('payload' not in row and 'reply' in row for row in receipt['calls'])
    assert receipt['copy_observation']['owned_state_mapping'] == 'unverified; no copied-GUID equality assumed'
    # Exercise the real v3 schema seam used by lifecycle finalization. A body
    # PASS alone previously hid an incomplete category from this fake control.
    from tests.destructive.support.category_evidence import build_category_evidence_record
    from tests.destructive.support.exact_real_evidence import exact_transaction_outcomes
    record = build_category_evidence_record(repo_root=workflow.REPO_ROOT, candidate=runtime.candidate,
        version=runtime.version, host={'is_command_line': True, 'version': {'year': 2021, 'major': 1,
            'minor': 14, 'build': 8108}}, categories=[category], source={},
        residual_state={'sandbox': 'quarantined_pending_release', 'quarantine_path': str(tmp_path / 'quarantine')},
        invocation={'selected_test_nodeids': [request.node.nodeid], 'node_outcomes': [
            {'nodeid': request.node.nodeid, 'outcome': 'PASS'}], 'started_at_unix_ns': 1,
            'finished_at_unix_ns': 2, 'phase': 'prepared', 'outcome': 'PENDING'},
        transactions=exact_transaction_outcomes(runtime.state_dir))
    assert record['contract'] == 'waapi-skill.host-category-evidence/v3'
    assert record['categories'][0]['diagnostic_only'] is True
    assert record['categories'][0]['business_effect_verified'] is False


def _failed_source_copy_verify(receipt):
    failed_call, = [row for row in receipt['calls'] if row['argv'][0] == 'verify' and row.get('exit_code') == 2]
    failed = json.loads(Path(failed_call['reply']['path']).read_text())
    assert failed['state'] == 'verification_failed' and failed['verification']['status'] == 'verification_failed'
    assert failed['transaction_id'] == receipt['phases'][-1]['transaction_id']
    assert len([row for row in receipt['calls'] if row['argv'] == ['execute', failed['transaction_id']]]) == 1
    return failed


@pytest.mark.parametrize('fault', ['native-error', 'copied-class', 'original-field'])
def test_legacy_source_copy_failure_preserves_attempt_without_fallback(tmp_path, workflow, fault):
    runtime, commands, writes, task = legacy_runtime(tmp_path, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='WAAPI_LEGACY_COPY')
    receipt = json.loads((runtime.state_dir / 'legacy-source-copy-feasibility.json').read_text())
    assert receipt['native_admission_verified'] is False
    if fault == 'original-field':
        failed = _failed_source_copy_verify(receipt)
        assert any(row['name'] == 'original Source fields and frame are unchanged' and row['passed'] is False
            for row in failed['verification']['assertions'])
    assert receipt['collection_complete'] is False
    assert len([uri for uri, _ in writes if uri.endswith('object.copy')]) == 1
    assert len([argv for argv in commands if argv[0] == 'execute']) == 2
    assert len(receipt['phases']) == 2 and receipt['phases'][1]['execution_attempted'] is True
    assert runtime.category_results[0]['status'] == 'FAIL' and receipt['failure']
    assert receipt['native_evidence']
    assert not any(uri.endswith('object.set') for uri, _ in writes)


def legacy_owned_read_runtime(tmp_path, *, fault=None):
    """2021 SDK fields and retained genuine owned identities, not modern points."""
    runtime, commands, writes, task = legacy_runtime(tmp_path)
    rtpc, lfo, curve = ('{CE99046D-D354-422D-A7BB-F1305FF00B2F}',
        '{E323F786-253F-48C6-86B9-AB0335804E9F}', '{0B357DC6-5FE7-4E50-9C31-23CDE7F34307}')
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/synth-one-2021-sdk-read-fields.json').read_text())
    for field in fixture['properties']:
        name, kind, value = field['name'], field['type'], field['sdk_default_text']
        task.metadata[name] = {'name': name, 'type': kind}
        task.objects[SOURCE].setdefault('@' + name, bool(int(value)) if kind == 'bool' else
            int(value) if kind == 'int32' else float(value))
    # SDK 2021.1.14 wwiseobject_paramcontrol/curve/modulatorlfo pages; these
    # fixtures prove public routing only, never that the live hops succeed.
    task.metadata.update(Color={'name': 'Color', 'type': 'int16'},
        OverrideColor={'name': 'OverrideColor', 'type': 'bool'},
        # Retained 8e9b9f17 native metadata has empty type/restriction, despite
        # the SDK describing this as Reference. Do not fabricate certification.
        ControlInput={'name': 'ControlInput', 'type': '', 'restriction': {}},
        Flags={'name': 'Flags', 'type': 'int32'})
    task.objects[rtpc] = {'id': rtpc, 'name': '', 'type': 'RTPC', 'classId': 1441808,
        'path': task.objects[SOURCE]['path'] + r'\[RTPC: Output Level, Modulator LFO (Custom)]',
        'owner': {'id': SOURCE}, 'notes': '', '@ControlInput': {'id': lfo}, '@Color': 0, '@OverrideColor': False}
    task.objects[lfo] = {'id': lfo, 'name': 'Modulator LFO (Custom)', 'type': 'ModulatorLfo', 'classId': 4194320,
        'path': 'Modulator LFO (Custom)', 'owner': {'id': rtpc}, 'notes': '', '@Color': 0, '@OverrideColor': False}
    for name, kind, value in (('LfoAttack', 'Real64', 0.0), ('LfoDepth', 'Real64', 100.0),
            ('LfoFrequency', 'Real64', 1.0), ('LfoInitialPhase', 'Real64', 0.0), ('LfoPWM', 'Real64', 50.0),
            ('LfoSmoothing', 'Real64', 0.0), ('LfoWaveform', 'int32', 0), ('ModulatorScope', 'int32', 1)):
        task.metadata[name] = {'name': name, 'type': kind}
        task.objects[lfo]['@' + name] = value
    task.objects[curve] = {'id': curve, 'name': '', 'type': 'Curve', 'classId': 917520,
        'path': task.objects[rtpc]['path'] + r'\<Unnamed Curve>', 'owner': {'id': rtpc}, 'notes': '', '@Flags': 0}
    original = task.call
    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        expression = args.get('waql', '')
        if uri.endswith('object.get') and ' select @' in expression:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if ' select @RTPC ' in expression:
                raise RuntimeError('Unknown property RTPC (61)')  # Actual R50 native rejection.
            if ' select @Curve ' in expression:
                raise RuntimeError('No source-backed 2021 Curve hop')
            if fault == 'hop-error':
                raise RuntimeError('Pinned ControlInput read rejected; no alternate spelling')
            assert expression == f'from object "{rtpc}" select @ControlInput take 2', expression
            return {'return': task.project_rows([task.objects[lfo]], options)}
        return original(uri, args, options)
    task.call = call
    return runtime, commands, writes, task


def test_legacy_owned_read_uses_public_metadata_and_never_starts_copy(tmp_path, workflow, request):
    runtime, commands, writes, task = legacy_owned_read_runtime(tmp_path)
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='UNUSED', owned_read_only=True)
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert receipt['collection_complete'] is True and category['diagnostic_only'] is True
    assert category['status'] == 'blocked'
    assert category['business_effect_verified'] is False and category['transaction_ids'] == []
    assert receipt['curve_points']['status'] == 'unavailable_in_2021_public_contract'
    assert receipt['metadata_unreadable_fields'] == {'{CE99046D-D354-422D-A7BB-F1305FF00B2F}': ['ControlInput']}
    assert writes == [] and not any(argv[0] in {'draft-start', 'preview', 'execute', 'confirm'} for argv in commands)
    assert all(argv[0] in {'status', 'metadata', 'query-object'} for argv in commands)
    assert any(argv[:2] == ['metadata', 'detail'] and '--selection' in argv for argv in commands)
    queries = [argv for argv in commands if argv[0] == 'query-object']
    assert all(argv.count('--include-field') <= 8 and 'curve-points' not in argv for argv in queries)
    source_pages = [argv for argv in queries if SOURCE in argv and '--include-field' in argv]
    assert source_pages == []  # R50 already read all18 Source fields; observe only missing owned semantics.
    assert receipt['owned_observation']['source_membership_complete'] is False
    assert receipt['owned_observation']['binding'] == 'retained exact RTPC GUID/class/Source-owner edge'
    assert not any('select @RTPC' in str(argv) for argv in commands)
    assert not any('select @Curve' in str(argv) for argv in commands)
    from tests.destructive.support.category_evidence import build_category_evidence_record
    record = build_category_evidence_record(repo_root=workflow.REPO_ROOT, candidate=runtime.candidate,
        version='2021.1', host={'is_command_line': True}, categories=[category], source={},
        residual_state={'sandbox': 'quarantined_pending_release', 'quarantine_path': str(tmp_path)},
        invocation={'selected_test_nodeids': [request.node.nodeid], 'node_outcomes': [
            {'nodeid': request.node.nodeid, 'outcome': 'PASS'}], 'started_at_unix_ns': 1,
            'finished_at_unix_ns': 2, 'phase': 'prepared', 'outcome': 'PENDING'}, transactions=[])
    assert record['contract'] == 'waapi-skill.host-category-evidence/v3'


def test_legacy_owned_read_preserves_first_hop_error_without_writes_or_fallback(tmp_path, workflow):
    runtime, commands, writes, task = legacy_owned_read_runtime(tmp_path, fault='hop-error')
    with pytest.raises(AssertionError):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='UNUSED', owned_read_only=True)
    receipt = json.loads((runtime.state_dir / 'legacy-source-owned-read.json').read_text())
    assert receipt['collection_complete'] is False and receipt['failure']
    assert writes == [] and len([argv for argv in commands if '--advanced-waql' in argv]) == 1
    assert receipt['calls'][-1]['exit_code'] != 0 and receipt['calls'][-1]['reply']
    failed = json.loads(Path(receipt['calls'][-1]['reply']['path']).read_text())
    assert failed['call']['message'] == 'Pinned ControlInput read rejected; no alternate spelling'
    assert receipt['owned_observation']['curve_field_names'] == ['Flags']
    assert receipt['owned_observation']['control_input_hop'] == 'attempted'
    assert receipt['native_evidence'] and runtime.category_results[0]['status'] == 'FAIL'


@pytest.mark.parametrize('corruption', ['class', 'Source-owner'])
def test_legacy_exact_owned_read_rejects_changed_rtpc_binding_before_metadata(tmp_path, workflow, corruption):
    runtime, commands, writes, task = legacy_owned_read_runtime(tmp_path)
    rtpc = task.objects['{CE99046D-D354-422D-A7BB-F1305FF00B2F}']
    if corruption == 'class': rtpc['classId'] = 917520  # Genuine Curve class, not RTPC.
    else: rtpc['owner'] = {'id': FIRST}  # A Sound is not the retained Source owner.
    with pytest.raises(AssertionError, match='Retained RTPC class/Source-owner binding changed'):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='UNUSED', owned_read_only=True)
    receipt = json.loads((runtime.state_dir / 'legacy-source-owned-read.json').read_text())
    assert receipt['collection_complete'] is False and writes == []
    assert not any(argv[:2] == ['metadata', 'list'] or '--advanced-waql' in argv for argv in commands)


SAVED_ROLES = {
    'source': (SOURCE, COPIED, 'SourcePlugin', 9699330, 883831456, 10001),
    'rtpc': ('{CE99046D-D354-422D-A7BB-F1305FF00B2F}', '{B1111111-1111-4111-8111-111111111111}', 'RTPC', 1441808, 274268052, 10002),
    'control_input': ('{E323F786-253F-48C6-86B9-AB0335804E9F}', '{B2222222-2222-4222-8222-222222222222}', 'ModulatorLfo', 4194320, 641284001, 10003),
    'curve': ('{0B357DC6-5FE7-4E50-9C31-23CDE7F34307}', '{B3333333-3333-4333-8333-333333333333}', 'Curve', 917520, None, None),
}
SAVED_OWNER = '{63E5A1E6-4265-463E-A5C5-322F742423E1}'


def saved_copy_example():
    """Genuine 2021 MIDI content; generated identities model only fake copy output."""
    import xml.etree.ElementTree as ET
    path = Path(__file__).parents[1] / '_org/2021.1/Actor-Mixer Hierarchy/MIDI.wwu'
    before = path.read_bytes()
    tree = ET.fromstring(before)
    source, = [node for node in tree.iter('SourcePlugin') if node.get('ID') == SOURCE]
    copied = deepcopy(source)
    for original, replacement, tag, cls, old_short, new_short in SAVED_ROLES.values():
        node, = [node for node in copied.iter(tag) if node.get('ID') == original]
        node.set('ID', replacement)
        if new_short is not None: node.set('ShortID', str(new_short))
    destination = ET.SubElement(tree.find('.//WorkUnit/ChildrenList'), 'Sound', {'Name': 'Copy destination', 'ID': DEST})
    ET.SubElement(destination, 'ChildrenList').append(copied)
    def live(which):
        result = {}
        for role, row in SAVED_ROLES.items():
            original, replacement, tag, cls, old_short, new_short = row
            identity = original if which == 'before' else replacement
            owner = (SAVED_OWNER if which == 'before' else DEST) if role == 'source' else (
                SAVED_ROLES['source' if role == 'rtpc' else 'rtpc'][0 if which == 'before' else 1])
            node, = [node for node in (source if which == 'before' else copied).iter(tag) if node.get('ID') == identity]
            result[role] = {'id': identity, 'name': node.get('Name'), 'type': tag, 'class_id': cls,
                'notes': node.findtext('Comment', ''), 'parent' if role == 'source' else 'owner': {'id': owner}}
            if old_short is not None: result[role]['short_id'] = old_short if which == 'before' else new_short
        return result
    return before, tree, copied, live('before'), live('copy')


def test_legacy_saved_copy_oracle_preserves_genuine_owned_points_and_live_bound_identities(workflow):
    import xml.etree.ElementTree as ET
    before, tree, copied, before_live, copied_live = saved_copy_example()
    result = workflow._legacy_saved_source_copy_oracle([before], [ET.tostring(tree)],
        source_id=SOURCE, copied_id=COPIED, original_owner_id=SAVED_OWNER, destination_id=DEST,
        before_live=before_live, copied_live=copied_live)
    assert result['owned_guid_mapping'] == {row[0]: row[1] for row in SAVED_ROLES.values()}
    assert result['original_preserved'] is True and result['ordered_point_count'] == 2
    assert result['short_id_classification'] == 'serialized declaration identity bound independently to live short_id'


@pytest.mark.parametrize('fault', ['point-value', 'point-order', 'alias', 'missing-member', 'short-id', 'unknown-attribute', 'original-field', 'whitespace-notes'])
def test_legacy_saved_copy_oracle_rejects_unexplained_saved_or_live_change(workflow, fault):
    import xml.etree.ElementTree as ET
    before, tree, copied, before_live, copied_live = saved_copy_example()
    if fault == 'point-value': copied.find('.//Curve/PointList/Point/YPos').text = '-4'
    elif fault == 'point-order': copied.find('.//Curve/PointList')[:] = list(reversed(copied.find('.//Curve/PointList')))
    elif fault == 'alias': copied.find('.//ModulatorLfo').set('ID', SAVED_ROLES['rtpc'][1])
    elif fault == 'missing-member': copied.find('.//Reference/Custom').clear()
    elif fault == 'short-id': copied_live['rtpc']['short_id'] += 1
    elif fault == 'unknown-attribute': copied.find('.//Curve').set('Unexpected', 'retained?')
    elif fault == 'whitespace-notes':
        baseline = ET.fromstring(before)
        source, = [node for node in baseline.iter('SourcePlugin') if node.get('ID') == SOURCE]
        retained, = [node for node in tree.iter('SourcePlugin') if node.get('ID') == SOURCE]
        source.find('Comment').text = retained.find('Comment').text = before_live['source']['notes'] = ' '
        copied.find('Comment').text = copied_live['source']['notes'] = '  '
        before = ET.tostring(baseline)
    else:
        original, = [node for node in tree.iter('SourcePlugin') if node.get('ID') == SOURCE]
        original.find("PropertyList/Property[@Name='Osc1Transpose']").set('Value', '0')
    with pytest.raises(AssertionError):
        workflow._legacy_saved_source_copy_oracle([before], [ET.tostring(tree)], source_id=SOURCE,
            copied_id=COPIED, original_owner_id=SAVED_OWNER, destination_id=DEST,
            before_live=before_live, copied_live=copied_live)


def saved_copy_runtime(tmp_path, *, fault=None):
    import xml.etree.ElementTree as ET
    runtime, commands, writes, task = legacy_runtime(tmp_path)
    before, tree, copied, before_live, copied_live = saved_copy_example()
    midi = ET.fromstring(before)
    midi_unit = midi.find('.//WorkUnit')
    midi_id = midi_unit.get('ID')
    directory = task.project_file.parent / 'Actor-Mixer Hierarchy'; directory.mkdir()
    midi_path, default_path = directory / 'MIDI.wwu', directory / 'Default Work Unit.wwu'
    midi_path.write_bytes(before)
    default_path.write_text('<WwiseDocument/>')
    runtime.sandbox.sandbox_project = task.project_file
    runtime.sandbox.sandbox_path = task.project_file.parent
    task.objects[SAVED_OWNER] = task.objects.pop(FIRST)
    task.objects[SAVED_OWNER].update(id=SAVED_OWNER, name='Synth', path=r'\Actor-Mixer Hierarchy\MIDI\Synth',
        parent={'id': midi_id})
    task.objects[SECOND]['filePath'] = str(default_path)
    task.objects[midi_id] = {'id': midi_id, 'name': 'MIDI', 'type': 'WorkUnit', 'classId': 1638416,
        'path': r'\Actor-Mixer Hierarchy\MIDI', 'filePath': str(midi_path)}
    del task.objects[DEST]
    for role, row in before_live.items():
        original, replacement, tag, cls, old_short, new_short = SAVED_ROLES[role]
        task.objects[original] = {**row, 'classId': cls, 'shortId': old_short,
            'path': r'\Actor-Mixer Hierarchy\MIDI\Synth\Wwise Synth One' if role == 'source' else tag,
            **({'workunit': {'id': midi_id}} if role == 'source' else {})}
        task.objects[original].pop('class_id')
    # Restore genuine field read frames lost when the saved-role identity rows
    # replace legacy_runtime's Source row. Values are matching XML overrides or
    # explicitly SDK-backed fake defaults, never production/native assumptions.
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/synth-one-2021-sdk-read-fields.json').read_text())
    source_xml, = [node for node in midi.iter('SourcePlugin') if node.get('ID') == SOURCE]
    overrides = {node.get('Name'): node.get('Value') for node in source_xml.findall('./PropertyList/Property') if node.get('Value') is not None}
    for field in fixture['properties']:
        name, kind = field['name'], field['type']
        text = overrides.get(name, field['sdk_default_text'])
        task.metadata[name] = {'name': name, 'type': kind, 'display': {'name': field['display_name']}}
        task.objects[SOURCE]['@' + name] = bool(int(text)) if kind == 'bool' else int(text) if kind == 'int32' else float(text)
    from tests.unit.test_field_interface_closure_gateway import PROJECT
    task.objects[PROJECT] = {'id': PROJECT, 'name': 'Fixture', 'type': 'Project', 'path': '\\',
        'filePath': str(tmp_path / 'unowned/Other.wproj') if fault == 'wrong-project' else str(task.project_file)}
    original = task.call
    def call(uri, args=None, options=None):
        if fault == 'wrong-project' and uri.endswith('object.get') and (args or {}).get('waql') == 'from type Project take 1':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            from tests.unit.test_field_interface_closure_gateway import PROJECT
            return {'return': task.project_rows([{'id': PROJECT, 'name': 'Other project', 'type': 'Project',
                'path': '\\', 'filePath': str(tmp_path / 'unowned/Other.wproj')}], options)}
        if uri.endswith('project.save'):
            task.calls.append((uri, deepcopy(args or {}), deepcopy(options or {}))); writes.append((uri, {}))
            document = ET.Element('WwiseDocument')
            unit = ET.SubElement(document, 'WorkUnit', {'ID': SECOND, 'Name': 'Default Work Unit'})
            children = ET.SubElement(unit, 'ChildrenList')
            destinations = [row for row in task.objects.values() if row.get('parent') == {'id': SECOND} and row['type'] == 'Sound']
            for row in destinations:
                sound = ET.SubElement(children, 'Sound', {'ID': row['id'], 'Name': row['name']})
                if COPIED in task.objects:
                    ET.SubElement(sound, 'ChildrenList').append(deepcopy(copied))
            if fault == 'save-error' and COPIED in task.objects:
                raise RuntimeError('Final Save failed; preserve first attempt')
            default_path.write_bytes(ET.tostring(document))
            return {}
        if uri.endswith('object.get') and ' select @ControlInput ' in (args or {}).get('waql', ''):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            identity = args['waql'].split('"')[1]
            assert identity == SAVED_ROLES['rtpc'][1]
            return {'return': task.project_rows([task.objects[SAVED_ROLES['control_input'][1]]], options)}
        result = original(uri, args, options)
        if uri.endswith('object.copy'):
            for role, row in copied_live.items():
                if role == 'source':
                    task.objects[COPIED].update(shortId=row['short_id'], notes=row['notes'], workunit={'id': SECOND})
                    continue
                task.objects[row['id']] = {**row, 'classId': row['class_id'],
                    'shortId': row.get('short_id'), 'path': row['type']}
            if fault == 'point-value': copied.find('.//Curve/PointList/Point/YPos').text = '99'
            if fault == 'live-owner': task.objects[SAVED_ROLES['control_input'][1]]['owner'] = {'id': SOURCE}
        return result
    task.call = call
    if fault == 'project-drift':
        original_raw = runtime.raw_gateway
        def drift_after_copy_verify(argv):
            result = original_raw(argv)
            if argv[0] == 'verify' and COPIED in task.objects:
                task.objects[PROJECT]['filePath'] = str(tmp_path / 'unowned/Other.wproj')
            return result
        runtime.raw_gateway = drift_after_copy_verify
    return runtime, commands, writes, task


def test_legacy_saved_copy_collector_uses_four_public_transactions_and_bounded_file_proofs(tmp_path, workflow, request):
    runtime, commands, writes, task = saved_copy_runtime(tmp_path)
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='SAVED_COPY', saved_copy=True)
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS' and category['business_effect_verified'] is False
    assert receipt['saved_copy_verified'] is True and receipt['collection_complete'] is True
    assert [row['name'] for row in receipt['phases']] == ['save_baseline', 'create_empty_destination', 'copy_source_only', 'save_final']
    copy_phase, = [row for row in receipt['phases'] if row['name'] == 'copy_source_only']
    assert copy_phase['gateway_verification_strength'] == 'source_default_view_fields_and_owner_frames_only'
    assert copy_phase['gateway_verification_scope']['copied_scalar_field_count'] == 18
    assert copy_phase['gateway_verification_scope']['complete_copy_preservation'] is False
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['save', 'create', 'copy', 'save']
    assert len([argv for argv in commands if argv[0] == 'execute']) == 4
    assert len(commands) <= receipt['limits']['calls'] == 128
    assert not any(argv[:2] in (['metadata', 'list'], ['metadata', 'detail']) for argv in commands)
    proof_index = json.loads(Path(receipt['native_file_proofs']['path']).read_text())
    assert proof_index['count'] == len(receipt['native_evidence'])
    assert [row['archive'] for row in proof_index['files']] == receipt['native_evidence']
    assert all(row['native_file_proof']['sha256'] == row['archive']['sha256'] for row in proof_index['files'])
    assert receipt['oracle']['ordered_point_count'] == 2 and receipt['oracle']['original_preserved']
    assert set(receipt['model_images']) == {'before', 'after'}
    assert all(value['complete'] for value in receipt['model_images'].values())
    from tests.destructive.support.category_evidence import build_category_evidence_record
    from tests.destructive.support.exact_real_evidence import exact_transaction_outcomes
    record = build_category_evidence_record(repo_root=workflow.REPO_ROOT, candidate=runtime.candidate,
        version='2021.1', host={'is_command_line': True}, categories=[category], source={},
        residual_state={'sandbox': 'quarantined_pending_release', 'quarantine_path': str(tmp_path)},
        invocation={'selected_test_nodeids': [request.node.nodeid], 'node_outcomes': [
            {'nodeid': request.node.nodeid, 'outcome': 'PASS'}], 'started_at_unix_ns': 1,
            'finished_at_unix_ns': 2, 'phase': 'prepared', 'outcome': 'PENDING'},
        transactions=exact_transaction_outcomes(runtime.state_dir))
    assert record['categories'][0]['diagnostic_only'] is True
    assert record['categories'][0]['business_effect_verified'] is False
    assert len(record['transactions']) == 4
    (tmp_path / 'budget.json').write_text(json.dumps({key: receipt[key] for key in ('archive_bytes', 'total_reply_bytes')}
        | {'calls': len(commands), 'native_files': len(receipt['native_evidence']),
           'max_reply_bytes': max(row['reply']['size'] for row in receipt['calls']),
           'receipt_bytes': Path(category['observation_path']).stat().st_size,
           'model_bytes': sum(row['total_bytes'] for row in receipt['model_images'].values())}))


@pytest.mark.parametrize('fault', ['point-value', 'live-owner', 'save-error'])
def test_legacy_saved_copy_failure_keeps_single_attempt_and_original_evidence(tmp_path, workflow, fault):
    runtime, commands, writes, task = saved_copy_runtime(tmp_path, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='SAVED_COPY', saved_copy=True)
    receipt = json.loads((runtime.state_dir / 'legacy-source-saved-copy.json').read_text())
    assert receipt['collection_complete'] is False and receipt['saved_copy_verified'] is False
    assert runtime.category_results[0]['status'] == 'FAIL' and receipt['failure']
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['save', 'create', 'copy', 'save']
    executed = [argv[1] for argv in commands if argv[0] == 'execute']
    assert len(executed) == len(set(executed)) == 4
    assert all(phase['execution_attempted'] for phase in receipt['phases'])
    assert receipt['native_evidence'] and receipt['model_images']['before']['complete']
    if fault == 'save-error':
        failed = json.loads(Path(receipt['calls'][-1]['reply']['path']).read_text())
        assert 'Final Save failed; preserve first attempt' in json.dumps(failed)
        assert 'after' not in receipt['model_images']
    else:
        assert receipt['model_images']['after']['complete']


@pytest.mark.parametrize('fault', ['wrong-project', 'project-drift'])
def test_legacy_saved_copy_refuses_save_outside_exact_owned_project(tmp_path, workflow, fault):
    runtime, commands, writes, task = saved_copy_runtime(tmp_path, fault=fault)
    with pytest.raises(AssertionError, match='Save requires the exact owned sandbox project'):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='SAVED_COPY', saved_copy=True)
    if fault == 'wrong-project':
        assert writes == [] and not any(argv[0] in {'typed-zero-call', 'draft-start', 'execute'} for argv in commands)
    else:
        assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['save', 'create', 'copy']
        receipt = json.loads((runtime.state_dir / 'legacy-source-saved-copy.json').read_text())
        saves = [row for row in receipt['phases'] if row['name'].startswith('save_')]
        assert len(saves) == 1 and saves[0]['name'] == 'save_baseline' and saves[0]['execution_attempted']
        assert len([argv for argv in commands if argv == ['execute', saves[0]['transaction_id']]]) == 1


def test_legacy_saved_copy_rejects_tampered_native_proof_index_without_replay(tmp_path, workflow, monkeypatch):
    runtime, commands, writes, task = saved_copy_runtime(tmp_path)
    observe = workflow.observe_console_file
    def tamper(path, *, io_root):
        if Path(path).name == 'native-proofs.json': Path(path).write_text('{}')
        return observe(path, io_root=io_root)
    monkeypatch.setattr(workflow, 'observe_console_file', tamper)
    with pytest.raises(AssertionError, match='Native proof index hash/size changed'):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='SAVED_COPY', saved_copy=True)
    receipt = json.loads((runtime.state_dir / 'legacy-source-saved-copy.json').read_text())
    assert receipt['collection_complete'] is False
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['save', 'create', 'copy', 'save']
    assert len([argv for argv in commands if argv[0] == 'execute']) == 4


def continuation_copy_runtime(tmp_path):
    # Reuse the genuine complete-owned metadata fixture and actual Gateway.
    from tests.unit.test_source_copy_saved_continuation_gateway import saved_source_task
    runtime, writes, task = saved_source_task(tmp_path)
    del task.objects[DEST]
    call = task.call
    task.collector_native_calls = []
    def observed(uri, args=None, options=None):
        task.collector_native_calls.append((uri, deepcopy(args), deepcopy(options)))
        result = call(uri, args, options)
        if uri.endswith('object.create'):
            unit = task.objects[SECOND]
            task.objects[result['id']].update(workunit={'id': SECOND}, filePath=unit['filePath'])
            unit['workunitIsDirty'] = True
        return result
    task.call = observed
    return runtime, writes, task


def test_saved_copy_successor_consumes_generated_children_and_original_parent(tmp_path, workflow):
    runtime, writes, task = continuation_copy_runtime(tmp_path)
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='SAVED_COPY', saved_copy=True,
        saved_copy_protocol='gateway-owned-save-children/v1')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS' and category['business_effect_verified'] is False
    assert receipt['contract'] == 'waapi-skill.source-copy-save-children-collector/v1'
    assert receipt['limits']['native_files'] == 1024 and receipt['limits']['receipt_bytes'] == 1024 * 1024
    assert [row['name'] for row in receipt['phases']] == [
        'create_empty_destination', 'save_baseline', 'copy_source_only', 'save_final']
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'save', 'copy', 'save']
    phases = {row['name']: row for row in receipt['phases']}
    copy = phases['copy_source_only']
    assert copy['pending_state'] == 'executed_unverified'
    assert copy['gateway_verification_scope']['complete_copy_preservation'] is True
    assert copy['gateway_verification_strength'] == 'saved_source_graph_and_live_roles'
    assert receipt['saved_copy_verified'] is True and receipt['collection_complete'] is True
    assert receipt['oracle']['ordered_point_count'] == 2 and receipt['oracle']['object_ref_count'] == 0
    assert receipt['oracle']['original_preserved'] is True
    assert len(set(receipt['transaction_ids'])) == 4
    links = receipt['continuation_links']
    assert [row['stage'] for row in links] == ['baseline', 'final']
    assert links[0]['parent_draft_id'] == receipt['copy_draft_id']
    assert links[0]['save_transaction_id'] == phases['save_baseline']['transaction_id']
    assert links[1]['parent_transaction_id'] == copy['transaction_id']
    assert links[1]['save_transaction_id'] == phases['save_final']['transaction_id']
    assert links[1]['return_gateway_argv'] == ['verify', copy['transaction_id']]
    budget = receipt['budget']
    assert budget['public_calls'] == len(receipt['calls']) <= 128
    assert budget['native_calls'] == len(task.collector_native_calls)
    assert budget['native_dispatcher_packets'] + budget['native_version_handshakes'] == budget['native_calls']
    assert budget['native_files_including_index'] > 512 and budget['receipt_bytes'] > 256 * 1024
    artifacts = Path(category['observation_path']).with_name('source-copy-save-children-artifacts')
    files = [path for path in artifacts.rglob('*') if path.is_file()]
    assert budget['archive_files'] == len(files)
    assert budget['archive_bytes'] == sum(path.stat().st_size for path in files)
    baseline, final = links
    assert baseline['save_receipt'] == phases['save_baseline']['authority_receipt']
    assert final['save_receipt'] == copy['gateway_verification_scope']['final_save_receipt']
    assert all(final['origin']['parent'][key] == value for key, value in copy['authority_receipt'].items())
    assert receipt['lifecycle_final_reference']['category'] == category['category']
    assert budget['native_files_including_index'] == len(receipt['native_evidence']) + 1 <= 1024
    assert budget['receipt_bytes'] == Path(category['observation_path']).stat().st_size <= 1024 * 1024
    assert budget['archive_bytes'] == receipt['archive_bytes'] <= 64 * 1024 * 1024
    assert budget['total_reply_bytes'] == receipt['total_reply_bytes'] <= 16 * 1024 * 1024
    assert not any(row['argv'][0] == 'typed-zero-call' for row in receipt['calls'])
    (tmp_path / 'successor-budget.json').write_text(json.dumps(budget, indent=2))
    print('R55 complete collector budget:', json.dumps(budget))


@pytest.mark.parametrize('fault', ['missing-index', 'tampered-index', 'missing-archive', 'tampered-archive', 'archive-link', 'index-link'])
def test_saved_copy_successor_rejects_invalid_native_proof_index(tmp_path, workflow, monkeypatch, fault):
    runtime, writes, task = continuation_copy_runtime(tmp_path)
    observe = workflow.observe_console_file
    def invalidate_index(path, *, io_root):
        path = Path(path)
        if path.name == 'native-proofs.json':
            # A valid index hash alone cannot establish its referenced bytes.
            archive = path.with_name('native-0.json')
            if fault == 'index-link':
                outside = tmp_path / 'outside-index.json'
                outside.write_bytes(path.read_bytes())
                path.unlink(); path.symlink_to(outside)
            elif fault == 'missing-index': path.unlink()
            elif fault == 'tampered-index': path.write_text('{}')
            elif fault == 'missing-archive': archive.unlink()
            elif fault == 'tampered-archive': archive.write_text('{}')
            elif fault == 'archive-link':
                outside = tmp_path / 'outside-native.json'
                outside.write_bytes(archive.read_bytes())
                archive.unlink(); archive.symlink_to(outside)
        return observe(path, io_root=io_root)
    monkeypatch.setattr(workflow, 'observe_console_file', invalidate_index)
    with pytest.raises(Exception):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='SAVED_COPY', saved_copy=True,
            saved_copy_protocol='gateway-owned-save-children/v1')
    receipt = json.loads((runtime.state_dir / 'source-copy-save-children.json').read_text())
    assert receipt['collection_complete'] is False and receipt['archive_failure']
    assert runtime.category_results[0]['status'] == 'FAIL'
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'save', 'copy', 'save']
    assert len(set(receipt['transaction_ids'])) == 4


@pytest.mark.parametrize('fault,expected_writes', [
    ('missing-baseline', ['create']),
    ('missing-final', ['create', 'save', 'copy']),
    ('wrong-child-parent', ['create']),
    ('wrong-baseline-revision', ['create']),
    ('wrong-final-parent-return', ['create', 'save', 'copy', 'save']),
    ('wrong-final-receipt', ['create', 'save', 'copy', 'save']),
])
def test_saved_copy_successor_rejects_invalid_generated_continuation(tmp_path, workflow, fault, expected_writes):
    runtime, writes, task = continuation_copy_runtime(tmp_path)
    invoke = runtime.raw_gateway
    def corrupt(argv):
        code, payload = invoke(argv)
        payload = deepcopy(payload)
        proof = payload.get('source_copy_saved_proof', {})
        if fault == 'missing-baseline' and proof.get('status') == 'baseline_save_pending':
            payload.pop('next_command', None)
        elif fault == 'missing-final' and payload.get('status') == 'source_copy_saved_proof_pending':
            payload.pop('next_command', None)
        elif fault == 'wrong-child-parent' and proof.get('stage') == 'baseline':
            proof['parent']['draft_id'] = 'od1-' + '1' * 32
        elif fault == 'wrong-baseline-revision' and argv[0] == 'transaction-show':
            origin = payload.get('artifact', {}).get('prepared_operation', {}).get('pre_state', {}).get('source_copy_save_origin')
            if origin and origin['stage'] == 'baseline': origin['parent']['source_revision'] += 1
        elif fault == 'wrong-final-receipt' and payload.get('verification', {}).get('verification_scope', {}).get('complete_copy_preservation') is True:
            payload['verification']['verification_scope']['final_save_receipt']['transaction_id'] = 'tx1-unrelated'
        elif fault == 'wrong-final-parent-return' and argv[0] == 'verify' and payload.get('state') == 'result_schema_checked':
            command = payload.get('next_command', {})
            if command.get('command') == 'verify': command['gateway_argv'] = ['verify', 'tx1-unrelated']
        return code, payload
    runtime.raw_gateway = corrupt
    with pytest.raises(AssertionError, match='continuation|parent|revision|receipt'):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='SAVED_COPY', saved_copy=True,
            saved_copy_protocol='gateway-owned-save-children/v1')
    receipt = json.loads((runtime.state_dir / 'source-copy-save-children.json').read_text())
    assert receipt['collection_complete'] is False and receipt['saved_copy_verified'] is False
    assert receipt['failure'] and receipt['native_evidence'] and runtime.category_results[0]['status'] == 'FAIL'
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == expected_writes
    attempted = [row['argv'][1] for row in receipt['calls'] if row['argv'][0] == 'execute']
    assert len(attempted) == len(set(attempted)) == len(expected_writes)
    assert not any(row['argv'] == ['verify', 'tx1-unrelated'] for row in receipt['calls'])


@pytest.mark.parametrize('fault', ['missing', 'tampered'])
def test_normal_source_copy_diagnostic_rejects_invalid_native_index(tmp_path, workflow, monkeypatch, fault):
    runtime, commands, writes, task = legacy_runtime(tmp_path)
    observe = workflow.observe_console_file
    def invalid(path, *, io_root):
        if Path(path).name == 'native-proofs.json':
            if fault == 'missing': Path(path).unlink()
            else: Path(path).write_text('{}')
        return observe(path, io_root=io_root)
    monkeypatch.setattr(workflow, 'observe_console_file', invalid)
    with pytest.raises(Exception):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='INDEX_CONTROL')
    receipt = json.loads((runtime.state_dir / 'legacy-source-copy-feasibility.json').read_text())
    assert receipt['contract'] == 'waapi-skill.legacy-source-copy-feasibility/v2'
    assert receipt['collection_complete'] is False and receipt['archive_failure']
    assert runtime.category_results[0]['status'] == 'FAIL'
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'copy']
    assert len([argv for argv in commands if argv[0] == 'execute']) == 2


def test_legacy_saved_copy_rejects_other_operation_in_active_save_preview(tmp_path, workflow):
    runtime, commands, writes, task = saved_copy_runtime(tmp_path)
    invoke = runtime.raw_gateway
    def wrong_operation(argv):
        code, payload = invoke(argv)
        if argv[0] == 'preview-from-draft':
            payload = deepcopy(payload)
            payload['preview_summary']['request']['arguments']['api'] = 'ak.wwise.core.project.close'
        return code, payload
    runtime.raw_gateway = wrong_operation
    with pytest.raises(AssertionError, match='Active Save Preview must identify exact project.save operation'):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='WRONG_SAVE', saved_copy=True)
    receipt = json.loads((runtime.state_dir / 'legacy-source-saved-copy.json').read_text())
    assert writes == [] and receipt['phases'] == [] and receipt['transaction_ids'] == []
    assert not any(argv[0] == 'execute' for argv in commands)
    assert receipt['failure'] and receipt['collection_complete'] is False


def test_normal_source_copy_diagnostic_retains_original_failure_when_index_fails(tmp_path, workflow, monkeypatch):
    runtime, commands, writes, task = legacy_runtime(tmp_path, fault='original-field')
    observe = workflow.observe_console_file
    def tampered(path, *, io_root):
        if Path(path).name == 'native-proofs.json': Path(path).write_text('{}')
        return observe(path, io_root=io_root)
    monkeypatch.setattr(workflow, 'observe_console_file', tampered)
    with pytest.raises(AssertionError, match='Native proof index hash/size changed'):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='DOUBLE_FAILURE')
    receipt = json.loads((runtime.state_dir / 'legacy-source-copy-feasibility.json').read_text())
    assert receipt['failure'] and receipt['archive_failure']
    failed = _failed_source_copy_verify(receipt)
    assert any(row['name'] == 'original Source fields and frame are unchanged' and row['passed'] is False
        for row in failed['verification']['assertions'])
    assert receipt['collection_complete'] is False and receipt['native_admission_verified'] is False
    assert runtime.category_results[0]['status'] == 'FAIL'
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'copy']


def selected_owned_probe_runtime(tmp_path, *, fault=None, version='2022.1'):
    """Real public read commands; native fake models the predeclared modern graph."""
    runtime, commands, writes, task = legacy_owned_read_runtime(tmp_path)
    owner = '{63E5A1E6-4265-463E-A5C5-322F742423E1}'
    rtpc, lfo, curve = ('{CE99046D-D354-422D-A7BB-F1305FF00B2F}',
        '{E323F786-253F-48C6-86B9-AB0335804E9F}', '{0B357DC6-5FE7-4E50-9C31-23CDE7F34307}')
    task.objects[owner] = task.objects.pop(FIRST); task.objects[owner]['id'] = owner
    task.objects[SOURCE]['parent'] = {'id': owner}
    task.version = runtime.version = version
    task.run('config-set', '--wwise-version', version)
    task.objects[owner]['shortId'] = 69157655
    task.objects[SOURCE]['shortId'] = 883831456
    task.objects[rtpc]['shortId'] = 274268052
    task.objects[lfo]['shortId'] = 641284001
    # Boundary is deliberately real public discovery: RTPC is not a listed
    # field, while the separately declared traversal is modeled as available.
    task.metadata['PropertyName'] = {'name': 'PropertyName', 'type': 'string'}
    task.objects[rtpc]['@PropertyName'] = 'OutputLevel'
    task.objects[curve]['points'] = [{'x': 0, 'y': -5.67053, 'shape': 'Linear'},
        {'x': 1, 'y': 0, 'shape': 'Linear'}]
    root = Path(__file__).parents[2]
    relative = Path('Containers' if version == '2025.1' else 'Actor-Mixer Hierarchy') / 'MIDI.wwu'
    midi = task.project_file.parent / relative
    midi.parent.mkdir(parents=True, exist_ok=True)
    midi.write_bytes((root / 'tests/_org' / version / relative).read_bytes())
    import xml.etree.ElementTree as ET
    xml = ET.fromstring(midi.read_bytes())
    for identity in (owner, SOURCE, rtpc, lfo, curve):
        node, = [node for node in xml.iter() if node.get('ID') == identity and node.tag in {'Sound', 'SourcePlugin', 'RTPC', 'ModulatorLfo', 'Curve'}]
        task.objects[identity].update(name=node.get('Name', ''), notes=node.findtext('Comment') or '')
    runtime.sandbox.sandbox_project = task.project_file
    runtime.sandbox.sandbox_path = task.project_file.parent
    previous = task.call
    task.probe_native_calls = []
    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        task.probe_native_calls.append((uri, deepcopy(args), deepcopy(options)))
        expression = args.get('waql', '')
        if uri.endswith('object.get') and ' select @' in expression:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            identity = {f'from object "{SOURCE}" select @RTPC take 2': rtpc,
                f'from object "{rtpc}" select @ControlInput take 2': lfo,
                f'from object "{rtpc}" select @Curve take 2': curve}[expression]
            rows = [task.objects[identity]]
            if fault == 'saturated' and identity == rtpc: rows *= 2
            return {'return': task.project_rows(rows, options)}
        result = previous(uri, args, options)
        if uri.endswith('getInfo'):
            values = {'2022.1': (2022, 19, 8584), '2023.1': (2023, 19, 8928), '2024.1': (2024, 13, 9056), '2025.1': (2025, 7, 9143)}
            year, minor, build = values[version]
            result['version'].update(year=year, minor=minor, build=build, displayName=f'v{year}.1.{minor}.{build}')
        return result
    task.call = call
    if fault == 'auth':
        original_raw = runtime.raw_gateway
        def raw(argv):
            if '--include-field' in argv and argv[-1] == 'RTPC':
                commands.append(list(argv))
                return 1, {'ok': False, 'error_code': 'AUTHORIZATION_REQUIRED'}
            return original_raw(argv)
        runtime.raw_gateway = raw
    return runtime, commands, writes, task


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
def test_selected_source_probe_retains_projection_boundary_and_independent_hops(tmp_path, workflow, request, version):
    runtime, commands, writes, task = selected_owned_probe_runtime(tmp_path, version=version)
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='', selected_owned_probe=True)
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert receipt['collection_complete'] is True and category['status'] == 'blocked'
    assert receipt['selected_owned_probe']['membership']['owner_array']['available'] is False
    assert receipt['selected_owned_probe']['membership']['traversal']['complete'] is True
    assert set(receipt['selected_owned_probe']['hops']) == {'ControlInput', 'Curve'}
    assert set(receipt['selected_owned_probe']['fields']) == {'source', 'rtpc', 'lfo', 'curve'}
    assert receipt['selected_owned_probe']['fields']['source']['names']
    assert receipt['budget']['public_calls'] == len(commands) <= 128
    assert receipt['budget']['native_files_including_index'] <= 512
    assert receipt['budget']['receipt_bytes'] == Path(category['observation_path']).stat().st_size <= 256 * 1024
    assert writes == [] and receipt['transaction_ids'] == []
    assert all(uri in {'ak.wwise.core.getInfo', 'ak.wwise.core.getProjectInfo', 'ak.wwise.core.object.get',
        'ak.wwise.core.object.getPropertyInfo', 'ak.wwise.core.object.getPropertyAndReferenceNames',
        'ak.wwise.core.object.getTypes'} for uri, _, _ in task.probe_native_calls), {uri for uri, _, _ in task.probe_native_calls}
    assert receipt['budget']['native_calls'] == len(task.probe_native_calls)
    request.node.user_properties.append(('probe_budget', receipt['budget']))


@pytest.mark.parametrize('fault', ['saturated', 'auth', 'call-budget'])
def test_selected_source_probe_stops_on_incomplete_or_unexpected_read(tmp_path, workflow, fault):
    runtime, commands, writes, task = selected_owned_probe_runtime(tmp_path, fault=fault)
    if fault == 'call-budget':
        # Large but valid live inventory: expose the real fixed public-call cap,
        # rather than monkeypatching a limit or calling collector internals.
        for index in range(90):
            name = f'FixtureField{index:03d}'
            task.objects[SOURCE]['@' + name] = index
            task.metadata[name] = {'name': name, 'type': 'int32'}
    with pytest.raises(AssertionError):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='', selected_owned_probe=True)
    receipt = json.loads((runtime.state_dir / 'selected-source-owned-probe.json').read_text())
    assert receipt['collection_complete'] is False and receipt['failure']
    assert runtime.category_results[0]['status'] == 'FAIL' and writes == []
    assert receipt['selected_owned_probe']['diagnostic_transport_complete'] is False
    if fault == 'saturated':
        assert 'below two-row cap' in receipt['failure']['message']
        assert len([argv for argv in commands if '--advanced-waql' in argv]) == 1
    elif fault == 'auth':
        assert not any('--advanced-waql' in argv for argv in commands)
        assert receipt['calls'][-1]['exit_code'] == 1
    else:
        assert 'public call bound' in receipt['failure']['message'] and len(commands) == 128
