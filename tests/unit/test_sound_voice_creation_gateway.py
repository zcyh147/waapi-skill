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


def test_existing_voice_merge_keeps_language_effect_boundary_and_original_selector(tmp_path):
    task = language_voice_task(tmp_path)
    voice_id = '{99999999-9999-9999-9999-999999999999}'
    task.objects[voice_id] = {'id': voice_id, 'name': 'Rain', 'type': 'Sound', 'classId': 65552,
        'path': task.objects[SECOND]['path'] + r'\Rain', 'parent': {'id': SECOND},
        'notes': 'Existing voice', '@IsVoice': True, '@Volume': -6, 'activeSource': None}
    task.bind(SECOND)
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    code, declared = declare_voice(task, extra=('--field', 'language', 'Japanese'))
    assert code == 0, declared
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'OPERATION_DRAFT_CHECK_FAILED', rejected
    issue = rejected['details']['issues'][0]
    assert issue['error_code'] == 'OBJECT_SET_VOICE_LANGUAGE_EFFECT_UNRESOLVED', rejected
    assert 'existing' in issue['message']
    code, draft = task.run('draft-inspect', task.draft, '--task-authority', task.authority)
    assert code == 0 and 'Japanese' in json.dumps(draft), draft
    assert task.objects[voice_id]['notes'] == 'Existing voice'
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
        else 'requested_media_language_independently_verified;new_empty_Voice_language_is_validated_native_construction_context_not_persisted_language_or_localized_Source;existing_merge_language_effect_unresolved;declared_Source_plugins_have_separate_language_and_closed_childset_verification')


JAPANESE = '{AAAAAAAA-1111-1111-1111-111111111111}'


def language_voice_task(path, version='2023.1'):
    from copy import deepcopy
    task = voice_task(path, version, 'object.set')
    task.languages = [{'id': JAPANESE, 'name': 'Japanese', 'shortId': 2}]
    original = task.call
    def call(uri, args=None, options=None):
        before_ids = set(task.objects) if uri.endswith('object.set') else set()
        result = original(uri, args, options)
        if uri.endswith('getProjectInfo'):
            result.update(displayTitle='Fixture', isDirty=False, currentLanguageId=JAPANESE,
                referenceLanguageId=JAPANESE, currentPlatformId=SECOND,
                languages=deepcopy(task.languages), platforms=[],
                defaultConversion={'id': SECOND, 'name': 'Default'},
                directories={key: str(task.project_file.parent) for key in
                    ('root', 'cache', 'originals', 'soundBankOutputRoot', 'commands', 'properties')})
        if uri.endswith('object.set'):
            for object_id, row in task.objects.items():
                if object_id not in before_ids and row['type'] == 'Sound':
                    row['activeSource'] = None
        return result
    task.call = call
    return task


def test_new_empty_voice_preserves_explicit_construction_language(tmp_path):
    task = language_voice_task(tmp_path)
    existing = '{88888888-8888-8888-8888-888888888888}'
    active = '{77777777-7777-7777-7777-777777777777}'
    task.objects[existing] = {'id': existing, 'name': 'Existing voice', 'type': 'Sound', 'classId': 65552,
        'path': task.objects[SECOND]['path'] + r'\Existing voice', 'parent': {'id': SECOND},
        'notes': 'Keep recording', '@IsVoice': True, 'activeSource': {'id': active}}
    task.objects[active] = {'id': active, 'name': 'Keep recording', 'type': 'AudioFileSource', 'classId': 16,
        'path': task.objects[existing]['path'] + r'\Keep recording', 'parent': {'id': existing}}
    code, declared = declare_voice(task, extra=('--field', 'language', 'Japanese'))
    assert code == 0, declared
    tx, shown = task.preview()
    prepared = shown['artifact']['prepared_operation']
    native = prepared['dispatch']['args']['objects'][0]['children'][0]
    assert native == {'type': 'Sound', 'name': 'Rain', 'notes': 'Keep voice',
                      'language': 'Japanese', '@IsVoice': True, '@Volume': -6}
    context = prepared['verification_plan']['nodes'][1]['construction_language']
    assert context['requested'] == 'Japanese' and context['selected'] == {'id': JAPANESE, 'name': 'Japanese'}
    assert context['role'] == 'voice-construction-context' and context['expected_sources'] == []
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    voice = next(row for row in task.objects.values() if row['name'] == 'Rain')
    assert voice['@IsVoice'] is True and voice['@Volume'] == -6 and voice['parent'] == {'id': SECOND}
    assert task.objects[existing]['activeSource'] == {'id': active}
    assert task.objects[active]['parent'] == {'id': existing}
    writes = [args for uri, args, _ in task.calls if uri.endswith('object.set')]
    assert len(writes) == 1
    assert any(args.get('transform') == [{'select': ['children']}]
               and args['from'] == {'id': [voice['id']]}
               for uri, args, _ in task.verification_calls if uri.endswith('object.get'))


@pytest.mark.parametrize('version,selector,nested,merge', [
    ('2022.1', 'Japanese', False, False), ('2024.1', 'Japanese', False, False),
    ('2025.1', 'Japanese', False, False), ('2023.1', JAPANESE, False, False),
    ('2023.1', 'Japanese', True, False), ('2023.1', 'Japanese', False, True)])
def test_empty_voice_construction_language_version_and_composition_paths(tmp_path, version, selector, nested, merge):
    task = language_voice_task(tmp_path, version)
    if merge:
        task.bind(SECOND)
        code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
        assert code == 0, configured
    code, declared = declare_voice(task, nested=nested, extra=('--field', 'language', selector))
    assert code == 0, declared
    tx, shown = task.preview()
    native = shown['artifact']['prepared_operation']['dispatch']['args']['objects'][0]['children'][0]
    voice_native = native['children'][0] if nested else native
    assert voice_native['language'] == selector and voice_native['@IsVoice'] is True
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len([uri for uri, _, _ in task.calls if uri.endswith('object.set')]) == 1
    assert all('language' not in options for uri, _, options in task.verification_calls if uri.endswith('object.get'))


def execute_voice(task, tx, shown):
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    return task.run('execute', tx)


@pytest.mark.parametrize('fault', ['unexpected-source', 'missing-children', 'incomplete-children', 'missing-active-source'])
def test_empty_voice_requires_independent_complete_source_observation(tmp_path, fault):
    task = language_voice_task(tmp_path)
    code, declared = declare_voice(task, extra=('--field', 'language', 'Japanese'))
    assert code == 0, declared
    tx, shown = task.preview()
    code, executed = execute_voice(task, tx, shown)
    assert code == 0, executed
    voice = next(row for row in task.objects.values() if row['name'] == 'Rain')
    if fault == 'unexpected-source':
        source = '{88888888-8888-8888-8888-888888888888}'
        task.objects[source] = {'id': source, 'name': 'Unexpected recording', 'type': 'AudioFileSource',
            'path': voice['path'] + r'\Unexpected recording', 'parent': {'id': voice['id']}}
    elif fault == 'missing-active-source':
        del voice['activeSource']
    else:
        original = task.call
        def call(uri, args=None, options=None):
            result = original(uri, args, options)
            if uri.endswith('object.get') and args.get('from') == {'id': [voice['id']]} and args.get('transform'):
                return {} if fault == 'missing-children' else {'return': [{}]}
            return result
        task.call = call
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified
    code, replay = task.run('execute', tx)
    assert code == 2, replay
    assert len([uri for uri, _, _ in task.calls if uri.endswith('object.set')]) == 1


@pytest.mark.parametrize('phase', ['before', 'after'])
@pytest.mark.parametrize('fault', ['removed', 'remapped'])
def test_construction_language_selection_cannot_drift_between_preview_and_effect(tmp_path, phase, fault):
    task = language_voice_task(tmp_path)
    code, declared = declare_voice(task, extra=('--field', 'language', 'Japanese'))
    assert code == 0, declared
    tx, shown = task.preview()
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    def drift():
        if fault == 'removed':
            task.languages.clear()
        else:
            task.languages[0]['id'] = '{77777777-7777-7777-7777-777777777777}'
    if phase == 'before':
        drift()
    code, executed = task.run('execute', tx)
    if phase == 'before':
        assert code == 2, executed
        assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)
        return
    assert code == 0, executed
    drift()
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified
    code, replay = task.run('execute', tx)
    assert code == 2, replay
    assert len([uri for uri, _, _ in task.calls if uri.endswith('object.set')]) == 1


@pytest.mark.parametrize('fault', ['unknown', 'duplicate', 'malformed', 'sfx'])
def test_construction_language_admission_requires_valid_project_language_and_voice(tmp_path, fault):
    task = language_voice_task(tmp_path)
    if fault == 'duplicate':
        task.languages.append({'id': SECOND, 'name': 'Japanese', 'shortId': 3})
    elif fault == 'malformed':
        del task.languages[0]['id']
    code, declared = declare_voice(task, kind='sound-sfx' if fault == 'sfx' else 'sound-voice',
        extra=('--field', 'language', 'Unknown' if fault == 'unknown' else 'Japanese'))
    if fault == 'sfx':
        assert code == 2 and declared['error_code'] == 'OBJECT_SET_VOICE_LANGUAGE_INVALID', declared
        assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)
        return
    assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 2 and checked['error_code'] == 'OPERATION_DRAFT_CHECK_FAILED', checked
    assert checked['details']['issues'][0]['error_code'] == {
        'unknown': 'UNKNOWN_PROJECT_LANGUAGE', 'duplicate': 'INVALID_PROJECT_CONTEXT',
        'malformed': 'INVALID_PROJECT_CONTEXT', 'sfx': 'INVALID_LANGUAGE_TARGET'}[fault], checked
    if fault == 'unknown':
        details = checked['details']['issues'][0]['details']
        assert details['field'] == 'language' and details['requested'] == 'Unknown'
        assert details['available'] == [{'id': JAPANESE, 'name': 'Japanese'}]
        assert details['available_total'] == 1 and details['available_returned'] == 1
        assert details['available_truncated'] is False
    assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)


def test_unrelated_language_inventory_changes_do_not_invalidate_selected_constructor(tmp_path):
    task = language_voice_task(tmp_path)
    code, declared = declare_voice(task, extra=('--field', 'language', 'Japanese'))
    assert code == 0, declared
    tx, shown = task.preview()
    task.languages.append({'id': SECOND, 'name': 'French', 'shortId': 3})
    task.languages[0]['shortId'] = 987
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified


def test_discovered_sound_with_explicit_voice_flag_uses_same_language_constructor(tmp_path):
    task = language_voice_task(tmp_path)
    task.bind(SECOND)
    code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
    assert code == 0, found
    kind = found['type_candidates'][0]['handle']
    field = is_voice_field(task, kind, generic=True)
    code, declared = declare_voice(task, kind=kind,
        extra=('--field-value', field, 'true', '--field', 'language', 'Japanese'))
    assert code == 0, declared
    tx, shown = task.preview()
    native = shown['artifact']['prepared_operation']['dispatch']['args']['objects'][0]['children'][0]
    assert native['language'] == 'Japanese' and native['@IsVoice'] is True
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified


SOURCE = '{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}'
SOURCE_CLASS = 6684674


def planned_source_task(path, version='2023.1'):
    task = language_voice_task(path, version)
    task.types.append({'name': 'Wwise Tone Generator', 'classId': SOURCE_CLASS, 'type': 'Source'})
    task.metadata['Frequency'] = {'name': 'Frequency', 'type': 'Real32', 'default': 440,
        'restriction': {'type': 'range', 'min': 20, 'max': 20000}}
    task.source_language = 'Japanese'
    original = task._create
    def create(node, parent, *, owned=False):
        if node['type'] != 'Source':
            return original(node, parent, owned=owned)
        task.objects[SOURCE] = {'id': SOURCE, 'name': 'Tone', 'type': 'SourcePlugin', 'classId': SOURCE_CLASS,
            'path': task.objects[parent]['path'] + r'\Tone', 'parent': {'id': parent},
            'notes': '', '@Frequency': 440, 'audioSource:language': {'name': task.source_language}}
        return {'id': SOURCE, 'name': 'Tone'}
    task._create = create
    return task


def declare_planned_source(task, owner, *, language='Japanese'):
    code, found = task.step('draft-discover-types', '--role', 'source', '--meaning', 'Wwise Tone Generator')
    assert code == 0, found
    kind = found['type_candidates'][0]['handle']
    code, fields = task.step('draft-discover-fields', '--type-handle', kind, '--meaning', 'Frequency')
    assert code == 0, fields
    field = fields['meaning_results'][0]['candidates'][0]['handle']
    extra = ('--field', 'language', language) if language is not None else ()
    return task.step('draft-declare-new', '--declaration-id', 'source', '--parent-handle', owner,
        '--name', 'Tone', '--kind', kind, '--field', 'plugin_placement', 'owner',
        '--field-value', field, '440', *extra)


def test_planned_voice_composes_a_typed_source_with_separate_language_context(tmp_path):
    task = planned_source_task(tmp_path)
    code, voice = declare_voice(task, extra=('--field', 'language', 'Japanese'))
    assert code == 0, voice
    code, source = declare_planned_source(task, voice['draft']['declared_object']['result_handle'])
    assert code == 0, source
    tx, shown = task.preview()
    native = shown['artifact']['prepared_operation']['dispatch']['args']['objects'][0]['children'][0]
    assert native['type'] == 'Sound' and native['@IsVoice'] is True and native['language'] == 'Japanese'
    assert native['children'] == [{'type': 'Source', 'name': 'Tone', 'classId': SOURCE_CLASS,
                                  'language': 'Japanese', '@Frequency': 440}]
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    sound = next(row for row in task.objects.values() if row['name'] == 'Rain')
    assert task.objects[SOURCE]['parent'] == {'id': sound['id']}
    assert task.objects[SOURCE]['audioSource:language'] == {'name': 'Japanese'}
    assert task.objects[SOURCE]['@Frequency'] == 440
    assert len([uri for uri, _, _ in task.calls if uri.endswith('object.set')]) == 1


@pytest.mark.parametrize('version,kind,source_language,nested', [
    ('2022.1', 'sound-voice', 'Japanese', False), ('2024.1', 'sound-voice', 'Japanese', False),
    ('2025.1', 'sound-voice', 'Japanese', False), ('2023.1', 'sound-sfx', None, False),
    ('2023.1', 'generic-voice', 'Japanese', False), ('2023.1', 'sound-voice', JAPANESE, False),
    ('2023.1', 'sound-voice', 'French', False), ('2023.1', 'sound-voice', None, False),
    ('2023.1', 'sound-voice', 'Japanese', True)])
def test_planned_source_versions_and_owner_language_alternatives(tmp_path, version, kind, source_language, nested):
    task = planned_source_task(tmp_path, version)
    task.source_language = 'SFX' if kind == 'sound-sfx' else 'French' if source_language == 'French' else 'Japanese'
    if source_language == 'French':
        task.languages.append({'id': '{CDCDCDCD-CDCD-CDCD-CDCD-CDCDCDCDCDCD}', 'name': 'French', 'shortId': 3})
    extra = () if kind == 'sound-sfx' else ('--field', 'language', 'Japanese')
    if kind == 'generic-voice':
        task.bind(SECOND)
        code, found = task.step('draft-discover-types', '--role', 'object', '--meaning', 'Sound')
        assert code == 0, found
        kind = found['type_candidates'][0]['handle']
        field = is_voice_field(task, kind, generic=True)
        extra += ('--field-value', field, 'true')
    code, voice = declare_voice(task, kind=kind, nested=nested, extra=extra)
    assert code == 0, voice
    code, source = declare_planned_source(task, voice['draft']['declared_object']['result_handle'], language=source_language)
    assert code == 0, source
    tx, shown = task.preview()
    native_voice = shown['artifact']['prepared_operation']['dispatch']['args']['objects'][0]['children'][0]
    if nested:
        native_voice = native_voice['children'][0]
    source_native = native_voice['children'][0]
    assert source_native['type'] == 'Source' and source_native['classId'] == SOURCE_CLASS
    assert source_native.get('language') == source_language
    assert native_voice.get('language') == (None if task.source_language == 'SFX' else 'Japanese')
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len([uri for uri, _, _ in task.calls if uri.endswith('object.set')]) == 1


@pytest.mark.parametrize('fault', ['missing-result', 'duplicate-result', 'wrong-result-guid',
    'wrong-class', 'wrong-parent', 'wrong-owner', 'ignored-field', 'ignored-language', 'unexpected-child', 'missing-readback'])
def test_planned_source_effect_failure_cannot_verify_or_replay(tmp_path, fault):
    from copy import deepcopy
    task = planned_source_task(tmp_path)
    code, voice = declare_voice(task, extra=('--field', 'language', 'Japanese'))
    assert code == 0, voice
    code, source = declare_planned_source(task, voice['draft']['declared_object']['result_handle'])
    assert code == 0, source
    tx, shown = task.preview()
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            returned = result['objects'][0]['children'][0]['children']
            if fault == 'missing-result': returned.clear()
            elif fault == 'duplicate-result': returned.append(deepcopy(returned[0]))
            elif fault == 'wrong-result-guid': returned[0]['id'] = '{DEDEDEDE-DEDE-DEDE-DEDE-DEDEDEDEDEDE}'
        if uri.endswith('object.get') and fault == 'missing-readback' and args.get('from') == {'id': [SOURCE]}:
            return {'return': []}
        return result
    task.call = call
    code, executed = execute_voice(task, tx, shown)
    assert code == 0, executed
    row = task.objects[SOURCE]
    if fault == 'wrong-class': row['classId'] = 16
    elif fault == 'wrong-parent': row['parent'] = {'id': SECOND}
    elif fault == 'wrong-owner': row['owner'] = {'id': SECOND}
    elif fault == 'ignored-field': row['@Frequency'] = 220
    elif fault == 'ignored-language': row['audioSource:language'] = {'name': 'French'}
    elif fault == 'unexpected-child':
        extra = '{EFEFEFEF-EFEF-EFEF-EFEF-EFEFEFEFEFEF}'
        task.objects[extra] = {'id': extra, 'name': 'Unexpected Source', 'type': 'SourcePlugin', 'classId': SOURCE_CLASS,
            'path': row['path'] + ' extra', 'parent': deepcopy(row['parent'])}
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified
    code, replay = task.run('execute', tx)
    assert code == 2, replay
    assert len([uri for uri, _, _ in task.calls if uri.endswith('object.set')]) == 1


@pytest.mark.parametrize('fault', ['owner', 'placement', 'category', 'unavailable', 'duplicate', 'field-drift', 'language-owner'])
def test_planned_source_invalid_placement_or_drift_cannot_write(tmp_path, fault):
    task = planned_source_task(tmp_path)
    parent = task.bind(SECOND)
    if fault == 'owner':
        code, container = task.step('draft-declare-new', '--declaration-id', 'container',
            '--parent-handle', parent, '--name', 'Layers', '--kind', 'actor-mixer')
        assert code == 0, container
        owner = container['draft']['declared_object']['result_handle']
    else:
        code, voice = declare_voice(task, kind='sound-sfx' if fault == 'language-owner' else 'sound-voice')
        assert code == 0, voice
        owner = voice['draft']['declared_object']['result_handle']
    if fault in {'placement', 'category'}:
        if fault == 'category': task.types[-1]['type'] = 'Effect'
        code, found = task.step('draft-discover-types', '--role', 'effect' if fault == 'category' else 'source', '--meaning', 'Wwise Tone Generator')
        assert code == 0, found
        code, declared = task.step('draft-declare-new', '--declaration-id', 'source', '--parent-handle', owner,
            '--kind', found['type_candidates'][0]['handle'], '--name', 'Tone', '--field', 'plugin_placement', 'shareset')
        if code == 0:
            code, declared = task.step('draft-check')
        assert code == 2, declared
    else:
        code, declared = declare_planned_source(task, owner)
        if fault in {'owner', 'language-owner'}:
            assert code == 2, declared
        else:
            assert code == 0, declared
            tx, shown = task.preview()
            if fault == 'unavailable': task.types.pop()
            elif fault == 'duplicate': task.types.append(dict(task.types[-1]))
            elif fault == 'field-drift': task.metadata['Frequency']['type'] = 'CString'
            code, result = execute_voice(task, tx, shown)
            assert code == 2, result
    assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)


def test_planned_source_constructor_cannot_adopt_an_existing_merged_source_guid(tmp_path):
    task = planned_source_task(tmp_path)
    voice_id = '{99999999-9999-9999-9999-999999999999}'
    task.objects[voice_id] = {'id': voice_id, 'name': 'Rain', 'type': 'Sound', 'classId': 65552,
        'path': task.objects[SECOND]['path'] + r'\Rain', 'parent': {'id': SECOND},
        'notes': 'Keep voice', '@IsVoice': True, '@Volume': -6}
    task.objects[SOURCE] = {'id': SOURCE, 'name': 'Tone', 'type': 'Source', 'classId': SOURCE_CLASS,
        'path': task.objects[voice_id]['path'] + r'\Tone', 'parent': {'id': voice_id},
        'notes': 'Retain source', '@Frequency': 220, 'audioSource:language': {'name': 'Japanese'}}
    task.bind(SECOND)
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    code, voice = declare_voice(task)
    assert code == 0, voice
    code, source = declare_planned_source(task, voice['draft']['declared_object']['result_handle'])
    assert code == 0, source
    code, checked = task.step('draft-check')
    assert code == 2 and checked['details']['issues'][0]['error_code'] == 'TARGET_EXISTS', checked
    assert task.objects[SOURCE]['@Frequency'] == 220 and task.objects[SOURCE]['notes'] == 'Retain source'
    assert not any(uri.endswith('object.set') for uri, _, _ in task.calls)


def test_planned_source_return_cannot_reclassify_a_retained_child_as_new(tmp_path):
    from copy import deepcopy
    task = planned_source_task(tmp_path)
    voice_id = '{99999999-9999-9999-9999-999999999999}'
    old_source = '{BCBCBCBC-BCBC-BCBC-BCBC-BCBCBCBCBCBC}'
    task.objects[voice_id] = {'id': voice_id, 'name': 'Rain', 'type': 'Sound', 'classId': 65552,
        'path': task.objects[SECOND]['path'] + r'\Rain', 'parent': {'id': SECOND},
        'notes': 'Keep voice', '@IsVoice': True, '@Volume': -6, 'activeSource': {'id': old_source}}
    task.objects[old_source] = {'id': old_source, 'name': 'Old Tone', 'type': 'Source', 'classId': SOURCE_CLASS,
        'path': task.objects[voice_id]['path'] + r'\Old Tone', 'parent': {'id': voice_id},
        'notes': 'Retain source', '@Frequency': 220}
    task.bind(SECOND)
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    code, voice = declare_voice(task)
    assert code == 0, voice
    code, source = declare_planned_source(task, voice['draft']['declared_object']['result_handle'])
    assert code == 0, source
    tx, shown = task.preview()
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            # Native fault: rename/reuse the retained Source instead of creating a new GUID.
            task.objects[old_source] = {**deepcopy(task.objects.pop(SOURCE)), 'id': old_source}
            result['objects'][0]['children'][0]['children'][0]['id'] = old_source
        return result
    task.call = call
    code, executed = execute_voice(task, tx, shown)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified
    code, replay = task.run('execute', tx)
    assert code == 2, replay
    assert len([uri for uri, _, _ in task.calls if uri.endswith('object.set')]) == 1
