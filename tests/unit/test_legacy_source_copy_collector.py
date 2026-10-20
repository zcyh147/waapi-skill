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
        with pytest.raises(AssertionError, match='Original Source/owner/observed owned objects changed'):
            workflow._collect_legacy_source_copy_feasibility(runtime, prefix='WAAPI_SYNTH_FIELDS')
        assert len([uri for uri, _ in writes if uri.endswith('object.copy')]) == 1
        if fault == 'owner-voice':
            receipt = json.loads((runtime.state_dir / 'legacy-source-copy-feasibility.json').read_text())
            owner_reads = [json.loads(Path(row['reply']['path']).read_text()) for row in receipt['calls']
                if row['argv'][0] == 'query-object' and FIRST in row['argv'] and '--include-field' in row['argv']]
            assert [row['objects'][0]['properties']['IsVoice'] for row in owner_reads] == [False, True]
            assert task.objects[SOURCE]['@Osc1Transpose'] == -1200
    pages = [argv for argv in commands if argv[0] == 'query-object' and SOURCE in argv and '--include-field' in argv]
    assert len(pages) >= 3 and all(argv.count('--include-field') <= 8 for argv in pages)
    assert {argv[index + 1] for argv in pages for index, token in enumerate(argv) if token == '--include-field'} == set(names)


def test_legacy_source_copy_collector_records_admission_without_full_copy_claim(tmp_path, workflow):
    runtime, commands, writes, task = legacy_runtime(tmp_path)
    category = workflow._collect_legacy_source_copy_feasibility(runtime, prefix='WAAPI_LEGACY_COPY')
    receipt = json.loads(Path(category['observation_path']).read_text())
    assert category['status'] == 'PASS' and receipt['native_admission_verified'] is True
    assert receipt['business_effect_verified'] is False and receipt['diagnostic_only'] is True
    assert [uri.rsplit('.', 1)[-1] for uri, _ in writes] == ['create', 'copy']
    assert writes[1][1] == {'object': SOURCE, 'parent': receipt['destination_id'], 'onNameConflict': 'fail'}
    assert receipt['copy_observation']['new_id'] == COPIED
    assert receipt['copy_observation']['class_id'] == 9699330
    assert all('payload' not in row and 'reply' in row for row in receipt['calls'])
    assert receipt['copy_observation']['owned_state_mapping'] == 'unverified; no copied-GUID equality assumed'


@pytest.mark.parametrize('fault', ['native-error', 'copied-class', 'original-field'])
def test_legacy_source_copy_failure_preserves_attempt_without_fallback(tmp_path, workflow, fault):
    runtime, commands, writes, task = legacy_runtime(tmp_path, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_legacy_source_copy_feasibility(runtime, prefix='WAAPI_LEGACY_COPY')
    receipt = json.loads((runtime.state_dir / 'legacy-source-copy-feasibility.json').read_text())
    assert receipt['native_admission_verified'] is (fault == 'original-field')
    assert receipt['collection_complete'] is False
    assert len([uri for uri, _ in writes if uri.endswith('object.copy')]) == 1
    assert len([argv for argv in commands if argv[0] == 'execute']) == 2
    assert len(receipt['phases']) == 2 and receipt['phases'][1]['execution_attempted'] is True
    assert runtime.category_results[0]['status'] == 'FAIL' and receipt['failure']
    assert receipt['native_evidence']
    assert not any(uri.endswith('object.set') for uri, _ in writes)
