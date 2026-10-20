"""Operation-owned persisted Source proof through normal public transactions."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

from tests.unit.test_legacy_source_copy_collector import saved_copy_runtime, SOURCE, COPIED, DEST, SAVED_OWNER, SAVED_ROLES
from tests.unit.test_field_interface_closure_gateway import PROJECT, SECOND
from tests.semantic.support.typed_gateway_input import create_object_lifecycle_business_preview


def saved_source_task(path):
    runtime, commands, writes, task = saved_copy_runtime(path)
    root = task.project_file.parent
    task.project_file.write_text(f'<WwiseDocument><Project ID="{PROJECT}" Name="Fixture"/></WwiseDocument>')
    task.objects[PROJECT]['workunitIsDirty'] = False
    midi_id = task.objects[SOURCE]['workunit']['id']
    midi_path = root / 'Actor-Mixer Hierarchy/MIDI.wwu'
    default_path = root / 'Actor-Mixer Hierarchy/Default Work Unit.wwu'
    for identity, file in [(midi_id, midi_path), (SECOND, default_path)]:
        task.objects[identity].update(workunitIsDirty=False, workunitType='rootFile', filePath=str(file))
    task.objects[SAVED_OWNER].update(filePath=str(midi_path), workunit={'id': midi_id})
    task.objects[SOURCE]['filePath'] = str(midi_path)
    task.objects[DEST] = {'id': DEST, 'name': 'Destination', 'type': 'Sound', 'classId': 65552,
        'path': task.objects[SECOND]['path'] + '\\Destination', 'parent': {'id': SECOND},
        'workunit': {'id': SECOND}, 'filePath': str(default_path), 'notes': '', '@IsVoice': False}
    default_path.write_text(f'<WwiseDocument><WorkUnit ID="{SECOND}" Name="Default Work Unit"><ChildrenList>'
        f'<Sound ID="{DEST}" Name="Destination"/></ChildrenList></WorkUnit></WwiseDocument>')
    call = task.call
    def observed(uri, args=None, options=None):
        if uri.endswith('object.get') and ' select @ControlInput ' in (args or {}).get('waql', ''):
            identity = args['waql'].split('"')[1]
            if identity == SAVED_ROLES['rtpc'][0]:
                task.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {'return': task.project_rows([task.objects[SAVED_ROLES['control_input'][0]]], options)}
        result = call(uri, args, options)
        if uri.endswith('object.copy'):
            task.objects[COPIED]['filePath'] = str(default_path)
            task.objects[SECOND]['workunitIsDirty'] = True
        if uri.endswith('project.save'):
            for identity in (PROJECT, SECOND, midi_id): task.objects[identity]['workunitIsDirty'] = False
        return result
    task.call = observed
    return runtime, writes, task


def public_copy(task):
    def gateway(argv):
        code, payload = task.run(*argv)
        assert code == 0, payload
        return payload
    preview = create_object_lifecycle_business_preview(gateway, version='2021.1',
        operation='object.copy', object_id=SOURCE, parent_id=DEST, name_conflict='fail')
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx, '--summary-only'); assert code == 0, shown
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token']); assert code == 0, result
    code, result = task.run('execute', tx); assert code == 0, result
    return tx


def test_clean_saved_source_copy_defers_terminal_for_separate_final_save(tmp_path):
    runtime, writes, task = saved_source_task(tmp_path)
    tx = public_copy(task)
    code, result = task.run('verify', tx)
    assert code == 0 and result['state'] == 'executed_unverified', result
    assert result['status'] == 'source_copy_saved_proof_pending', result
    assert result['next_command']['command'] == 'continue-source-copy-proof'
    assert [uri.rsplit('.', 1)[-1] for uri, args in writes] == ['copy']
    assert result['source_copy_saved_proof']['baseline_origin'] == 'already_clean'
