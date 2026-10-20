"""Sound semantics use the real Gateway and source-shaped native boundary facts."""
import json

import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, SECOND

VERSIONS = ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1']


def voice_task(path, version='2025.1', operation='object.create', fault=None):
    task = OwnedGraphTask(path, version, operation)
    next(row for row in task.types if row['name'] == 'Sound')['classId'] = 65552
    task.creation_classes['Sound'] = 65552
    # All five pinned Sound pages/WObjects publish this literal definition.
    # These native-boundary responses are fixtures, not native effect evidence.
    task.metadata.update(IsVoice={'name': 'IsVoice', 'type': 'bool', 'default': False, 'dependencies': []},
        Volume={'name': 'Volume', 'type': 'Real64', 'default': 0,
            'restriction': {'type': 'range', 'min': -200, 'max': 200}})
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith(('object.create', 'object.set')):
            for row in task.objects.values():
                if row['type'] == 'Sound':
                    if fault == 'false':
                        row['@IsVoice'] = False
                    elif fault == 'numeric':
                        row['@IsVoice'] = 1
                    elif fault == 'missing':
                        row.pop('@IsVoice', None)
        return result
    task.call = call
    return task


def declare_voice(task, *, nested=False, kind='sound-voice', extra=()):
    parent = task.bind(SECOND)
    if nested:
        code, declared = task.step('draft-declare-new', '--declaration-id', 'root', '--parent-handle', parent,
            '--kind', 'actor-mixer', '--name', 'Layers')
        assert code == 0, declared
        parent = declared['draft']['declared_object']['result_handle']
    return task.step('draft-declare-new', '--declaration-id', 'voice', '--parent-handle', parent,
        '--kind', kind, '--name', 'Rain', '--field', 'notes', 'Keep voice', '--field', 'volume_db', '-6', *extra)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('nested', [False, True])
def test_public_create_voice_container_derives_and_verifies_actual_flag(tmp_path, version, nested):
    task = voice_task(tmp_path, version)
    code, declared = declare_voice(task, nested=nested)
    assert code == 0, declared
    tx, shown = task.preview()
    args = shown['artifact']['prepared_operation']['dispatch']['args']
    sound = args['children'][0] if nested else args
    assert sound['type'] == 'Sound' and sound['@IsVoice'] is True
    assert 'language' not in sound and 'children' not in sound
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, json.dumps(verified)
    assert len([call for call in task.calls if call[0].endswith('object.create')]) == 1


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('nested', [False, True])
def test_public_graph_empty_voice_does_not_invent_language_or_source(tmp_path, version, nested):
    task = voice_task(tmp_path, version, operation='object.set')
    code, declared = declare_voice(task, nested=nested)
    assert code == 0, declared
    tx, shown = task.preview()
    child = shown['artifact']['prepared_operation']['dispatch']['args']['objects'][0]['children'][0]
    if nested:
        child = child['children'][0]
    assert child['type'] == 'Sound' and child['@IsVoice'] is True
    assert 'language' not in child and 'import' not in child
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, json.dumps(verified)


@pytest.mark.parametrize('operation', ['object.create', 'object.set'])
@pytest.mark.parametrize('fault', ['false', 'numeric', 'missing'])
def test_voice_identity_cannot_be_verified_from_sound_type_with_wrong_flag(tmp_path, operation, fault):
    task = voice_task(tmp_path, operation=operation, fault=fault)
    code, declared = declare_voice(task)
    assert code == 0, declared
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get('verified') is not True, json.dumps(verified)
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([row for row in task.calls if row[0].endswith(operation)]) == 1


def is_voice_field(task, kind='sound-voice', generic=False):
    task.bind(SECOND)
    scope = ('--type-handle', kind) if generic else ('--semantic-kind', kind)
    code, found = task.step('draft-discover-fields', *scope, '--meaning', 'IsVoice')
    assert code == 0, json.dumps(found)
    return found['meaning_results'][0]['candidates'][0]['handle']


@pytest.mark.parametrize('kind,value', [('sound-voice', 'true'), ('sound-voice', 'false'), ('sound-sfx', 'true'), ('sound-sfx', 'false')])
def test_sound_kind_and_explicit_flag_agree_without_duplicate_assignment(tmp_path, kind, value):
    task = voice_task(tmp_path)
    field = is_voice_field(task, kind)
    code, declared = declare_voice(task, kind=kind, extra=('--field-value', field, value))
    if (kind == 'sound-voice') != (value == 'true'):
        assert code == 2 and declared['error_code'] == 'SOUND_KIND_FIELD_CONFLICT', declared
        assert not any(uri.endswith('object.create') for uri, _, _ in task.calls)
        return
    assert code == 0, declared
    tx, shown = task.preview()
    args = shown['artifact']['prepared_operation']['dispatch']['args']
    assert args['@IsVoice'] is (value == 'true')
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified


def test_generic_sound_type_handle_can_explicitly_select_voice_flag(tmp_path):
    task = voice_task(tmp_path)
    task.bind(SECOND)
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
    assert code == 0, json.dumps(found)
    kind = found['type_candidates'][0]['handle']
    field = is_voice_field(task, kind, generic=True)
    code, declared = declare_voice(task, kind=kind, extra=('--field-value', field, 'true'))
    assert code == 0, declared
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified


@pytest.mark.parametrize('operation', ['object.create', 'object.set'])
@pytest.mark.parametrize('phase', ['before', 'after'])
@pytest.mark.parametrize('drift', ['default', 'dependencies'])
def test_voice_class_metadata_drift_cannot_write_or_verify(tmp_path, operation, phase, drift):
    task = voice_task(tmp_path, operation=operation)
    code, declared = declare_voice(task)
    assert code == 0, declared
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    def change():
        if drift == 'default':
            task.metadata['IsVoice']['default'] = True
        else:
            task.metadata['IsVoice']['dependencies'] = [{'type': 'property', 'action': 'Enable',
                'context': 'Self', 'property': 'Volume', 'conditions': [{'restriction': {
                    'type': 'enum', 'values': [{'value': -6}]}}]}]
    if phase == 'before':
        change()
    code, executed = task.run('execute', tx)
    if phase == 'before':
        assert code == 2, executed
        assert not any(uri.endswith(operation) for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    change()
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified



@pytest.mark.parametrize('operation', ['object.create', 'object.set'])
def test_voice_derived_flag_requires_live_boolean_scalar_metadata(tmp_path, operation):
    task = voice_task(tmp_path, operation=operation)
    task.metadata['IsVoice']['type'] = 'CString'
    code, declared = declare_voice(task)
    assert code == 0, declared
    code, rejected = task.step('draft-check')
    assert code == 2, rejected
    if operation == 'object.set':
        assert rejected['error_code'] == 'OPERATION_DRAFT_CHECK_FAILED', rejected
        assert rejected['details']['issues'][0]['error_code'] == 'INVALID_PROPERTY_VALUE'
    else:
        assert rejected['error_code'] == 'INVALID_PROPERTY_VALUE', rejected
    assert not any(uri.endswith(operation) for uri, _, _ in task.calls)


def test_explicit_voice_language_without_media_retains_an_effect_evidence_boundary(tmp_path):
    task = voice_task(tmp_path, operation='object.set')
    code, declared = declare_voice(task, extra=('--field', 'language', 'French'))
    assert code == 0, declared
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'OPERATION_DRAFT_CHECK_FAILED', rejected
    assert rejected['details']['issues'][0]['error_code'] == 'OBJECT_SET_VOICE_LANGUAGE_EFFECT_UNRESOLVED'
    assert 'native' not in rejected.get('details', {}).get('repair', {}).get('action', '').lower()
    assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)


@pytest.mark.parametrize('field_name,field_type,business_value,actual,accepted', [
    ('IsVoice', 'bool', 'true', 1, False), ('Volume', 'Real64', '1.0', 1, True)])
def test_named_property_distinguishes_boolean_type_and_keeps_numeric_equivalence(tmp_path, field_name, field_type, business_value, actual, accepted):
    from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST
    task = ScalarPropertyTask(tmp_path, '2025.1')
    task.metadata = {field_name: {'name': field_name, 'type': field_type, 'default': False if field_type == 'bool' else 0}}
    task.objects[FIRST][field_name] = False if field_type == 'bool' else 0
    source = task.bind(FIRST)
    field = task.discover(source, field_name)
    code, declared = task.step('draft-declare-field-change', '--object-handle', source,
        '--field-handle', field, '--business-value', business_value)
    assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    task.objects[FIRST][field_name] = actual
    code, verified = task.run('verify', tx)
    assert code == (0 if accepted else 2) and (verified.get('verified') is True) is accepted, verified


@pytest.mark.parametrize('operation', ['object.create', 'object.set'])
def test_public_sound_creation_contract_discloses_semantic_flag_and_source_boundary(tmp_path, operation):
    task = voice_task(tmp_path)
    code, schema = task.run('--version', '2025.1', 'operation-schema', operation)
    assert code == 0, schema
    semantics = schema['business_adapter']['sound_semantics']
    assert semantics['sound_voice'] == {'native_class': 'Sound', 'initial_fields': {'IsVoice': True}, 'empty_container': True}
    assert semantics['explicit_flag_conflict'] == 'reject_before_dispatch'
    assert semantics['verification'] == 'actual_Boolean_IsVoice_and_bound_fields_identity_and_metadata'
    assert semantics['language_and_media'] == ('use_audio_import_for_localized_media' if operation == 'object.create'
        else 'requested_media_language_independently_verified;explicit_language_without_media_pending_effect_evidence')
