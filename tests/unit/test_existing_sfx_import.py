"""Existing same-basename SFX imports retain their attested source destinations."""
from copy import deepcopy
from pathlib import Path

import pytest

from tests.unit.test_cross_family_voice_import import VoiceReader, VERSIONS, OWNER, PARENT, EN_SOURCE, JP_SOURCE
from wwise_waapi.operation_registry import (
    OPERATION_REQUEST_CONTRACT, OperationContractError, parse_operation_request,
    prepare_operation, validate_prepared_roles, verify_prepared_operation,
)

RIGHT = "{77777777-7777-7777-7777-777777777777}"


class SfxReader(VoiceReader):
    def __init__(self, root, version):
        super().__init__(root, version, [])
        self.version = version
        self.owners = []
        self.sources = []
        for name, guid, source_id in [('Left', OWNER, EN_SOURCE), ('Right', RIGHT, JP_SOURCE)]:
            path = self.root + '\\' + name
            original = self.originals_root / 'SFX' / 'Expansion' / name / 'Hit.wav'
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(name.encode())
            self.owners.append({'id': guid, 'type': 'Sound', 'classId': 65552, 'name': name, 'path': path,
                                'parent': {'id': PARENT}, 'notes': 'preserved',
                                'activeSource': {'id': source_id, 'name': 'Hit'},
                                'originalFilePath': str(original), 'sound:originalWavFilePath': str(original)})
            self.sources.append({'id': source_id, 'type': 'AudioFileSource', 'classId': 16, 'name': 'Hit',
                                 'path': path + r'\Hit', 'parent': {'id': guid},
                                 'originalFilePath': str(original), 'originalWavFilePath': str(original),
                                 'audioSource:language': {'name': 'SFX'}})

    def __call__(self, uri, args, options):
        if uri != 'ak.wwise.core.object.get' or args.get('waql') == 'from type Project take 2':
            return super().__call__(uri, args, options)
        self.calls.append((uri, dict(args), dict(options)))
        query = args.get('waql', '')
        if ' select children take ' in query:
            return {'return': [{k: deepcopy(v) for k, v in s.items() if k in options['return']}
                               for s in self.sources if any(owner['id'] in query and s['path'].startswith(owner['path'] + '\\')
                                                           for owner in self.owners)]}
        identity = args.get('from', {})
        known = [self.anchor, *self.owners, *self.sources]
        return {'return': [{k: deepcopy(v) for k, v in r.items() if k in options['return']}
                           for r in known if r.get('id') in identity.get('id', [])
                           or r.get('path') in identity.get('path', [])]}


def prepare_sfx(tmp_path, version, mutate=None):
    reader = SfxReader(tmp_path, version)
    if mutate:
        mutate(reader)
    rows = []
    for owner in reader.owners:
        media = tmp_path / 'replacement' / owner['name'] / 'Hit.wav'
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(('replacement ' + owner['name']).encode())
        rows.append({'object_path': owner['path'], 'object_type': 'Sound SFX',
                     'audio_file': str(media), 'import_language': 'SFX'})
    request = parse_operation_request({'contract': OPERATION_REQUEST_CONTRACT,
                                      'version': version, 'operation': 'audio.import',
                                      'arguments': {'import_operation': 'useExisting', 'imports': rows}})
    return prepare_operation(request, read_call=reader).as_dict(), reader


@pytest.mark.parametrize('version', VERSIONS)
def test_same_basename_existing_sfx_keeps_distinct_originals_and_source_identity(tmp_path, version):
    prepared, reader = prepare_sfx(tmp_path, version)
    rows = prepared['dispatch']['args']['imports']
    if version == '2025.1':
        assert [row['importLocation'] for row in rows] == [EN_SOURCE, JP_SOURCE]
        assert all(row['objectPath'] == '' for row in rows)
        assert all('objectType' not in row for row in rows)
    else:
        assert all('importLocation' not in row for row in rows)
    # The frozen 2025 owned-copy failure returned Originals/SFX/Hit.wav twice
    # after the Source-GUID adaptation discarded these attested destinations.
    assert [row['originalsSubFolder'] for row in rows] == [r'Expansion\Left', r'Expansion\Right']
    targets = prepared['verification_plan']['targets']
    assert [target['existing_sfx_source_id'] for target in targets] == [EN_SOURCE, JP_SOURCE]
    assert all(target['expected_audio_file_source_result_path'].endswith(r'\Hit') for target in targets)
    assert validate_prepared_roles(prepared, read_call=reader)['ok']


def test_2025_flattened_copy_collision_retains_all_frozen_verification_failures(tmp_path):
    """Replay the failed owned-copy outcome without granting it native credit."""
    from tests.unit.test_operation_registry_import_verifier import _result
    prepared, reader = prepare_sfx(tmp_path, '2025.1')
    flat = reader.originals_root / 'SFX' / 'Hit.wav'
    flat.write_bytes(Path(prepared['dispatch']['args']['imports'][0]['audioFile']).read_bytes())
    reader.sources[0]['originalFilePath'] = str(flat)
    reader.sources[0]['originalWavFilePath'] = str(flat)
    reader.owners[0]['originalFilePath'] = str(flat)
    reader.owners[0]['sound:originalWavFilePath'] = str(flat)
    # The actual result named only the original Left Source and reported the
    # same flat file twice. Right retained its original media bytes/readback.
    result = verify_prepared_operation(prepared, execution_result=_result(
        '2025.1', [reader.sources[0]], [flat, flat]), read_call=reader)
    assert not result.ok
    failed = {assertion['name'] for assertion in result.assertions if not assertion['passed']}
    assert failed == {
        'import target 0 existing SFX source identities and placement preserved',
        'import target 0 Originals subfolder matches',
        'import target 0 copied original WAV is reported exactly once',
        'import target 1 copied original WAV hash matches the source',
        'import target 1 copied original WAV is reported exactly once',
    }


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('fault', ['duplicate-source', 'wrong-source', 'outside-originals', 'traversal', 'filename'])
def test_existing_sfx_rejects_ambiguous_or_unsafe_source_before_preview(tmp_path, version, fault):
    def corrupt(reader):
        if fault == 'duplicate-source':
            extra = deepcopy(reader.sources[0]); extra['id'] = '{88888888-8888-8888-8888-888888888888}'
            reader.sources.append(extra)
        elif fault == 'wrong-source':
            reader.sources[0]['path'] += '_foreign'
        elif fault == 'outside-originals':
            outside = tmp_path / 'Hit.wav'; outside.write_bytes(b'outside')
            reader.sources[0]['originalFilePath'] = str(outside)
            reader.sources[0]['originalWavFilePath'] = str(outside)
        elif fault == 'traversal':
            reader.sources[0]['originalFilePath'] = str(reader.originals_root / 'SFX' / 'Expansion' / 'Left' / '..' / 'Left' / 'Hit.wav')
            reader.sources[0]['originalWavFilePath'] = reader.sources[0]['originalFilePath']
        else:
            other = Path(reader.sources[0]['originalFilePath']).with_name('Other.wav'); other.write_bytes(b'other')
            reader.sources[0]['originalFilePath'] = str(other)
            reader.sources[0]['originalWavFilePath'] = str(other)
    with pytest.raises(OperationContractError) as rejected:
        prepare_sfx(tmp_path, version, corrupt)
    assert rejected.value.error_code == {
        'duplicate-source': 'AMBIGUOUS_SFX_SOURCE', 'wrong-source': 'AMBIGUOUS_SFX_SOURCE',
        'outside-originals': 'UNSAFE_ORIGINALS_PATH', 'traversal': 'INVALID_PROJECT_CONTEXT',
        'filename': 'SFX_SOURCE_FILENAME_MISMATCH',
    }[fault]


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('change', ['none', 'reordered', 'source-guid', 'source-placement', 'extra-source'])
def test_existing_sfx_execution_guard_binds_full_source_collection(tmp_path, version, change):
    prepared, reader = prepare_sfx(tmp_path, version)
    if change == 'reordered':
        reader.sources.reverse()
    elif change == 'source-guid':
        reader.sources[0]['id'] = '{88888888-8888-8888-8888-888888888888}'
    elif change == 'source-placement':
        reader.sources[0]['originalFilePath'] = str(tmp_path / 'elsewhere.wav')
        reader.sources[0]['originalWavFilePath'] = str(tmp_path / 'elsewhere.wav')
    elif change == 'extra-source':
        extra = deepcopy(reader.sources[0]); extra['id'] = '{88888888-8888-8888-8888-888888888888}'
        extra['path'] += '_01'; reader.sources.append(extra)
    assert validate_prepared_roles(prepared, read_call=reader)['ok'] is (change in {'none', 'reordered'})


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('changed_guid', [False, True])
def test_existing_sfx_verification_requires_original_source_guid(tmp_path, version, changed_guid):
    from tests.unit.test_operation_registry_import_verifier import _result
    prepared, reader = prepare_sfx(tmp_path, version)
    copied = []
    for row, source in zip(prepared['dispatch']['args']['imports'], reader.sources):
        original = Path(source['originalFilePath'])
        original.write_bytes(Path(row['audioFile']).read_bytes())
        copied.append(original)
    if changed_guid:
        new_guid = '{88888888-8888-8888-8888-888888888888}'
        reader.sources[0]['id'] = new_guid
        reader.owners[0]['activeSource']['id'] = new_guid
    result = verify_prepared_operation(prepared, execution_result=_result(
        version, [*reader.owners, *reader.sources], copied), read_call=reader)
    assert result.ok is (not changed_guid), [a for a in result.assertions if not a['passed']]


@pytest.mark.parametrize('version', VERSIONS)
def test_existing_sfx_verification_rejects_unreturned_extra_source(tmp_path, version):
    from tests.unit.test_operation_registry_import_verifier import _result
    prepared, reader = prepare_sfx(tmp_path, version)
    copied = []
    for row, source in zip(prepared['dispatch']['args']['imports'], reader.sources):
        original = Path(source['originalFilePath'])
        original.write_bytes(Path(row['audioFile']).read_bytes()); copied.append(original)
    returned = deepcopy([*reader.owners, *reader.sources])
    extra = deepcopy(reader.sources[0]); extra['id'] = '{88888888-8888-8888-8888-888888888888}'
    extra['path'] += '_01'; reader.sources.append(extra)
    result = verify_prepared_operation(prepared, execution_result=_result(version, returned, copied), read_call=reader)
    assert result.ok is False


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('fault', ['malformed-guid', 'foreign-parent', 'language', 'duplicate-id', 'limit'])
def test_existing_sfx_source_discovery_is_bounded_and_closed(tmp_path, version, fault):
    def corrupt(reader):
        if fault == 'malformed-guid':
            reader.sources[0]['id'] = 'not-a-guid'
        elif fault == 'foreign-parent':
            # Keep the foreign row in the response, rather than letting the fake scope filter omit it.
            reader.sources[0]['parent']['id'] = OWNER + 'foreign'
        elif fault == 'language':
            reader.sources[0]['audioSource:language']['name'] = 'Japanese'
        elif fault == 'duplicate-id':
            reader.sources.append(deepcopy(reader.sources[0]))
        else:
            reader.sources = [deepcopy(reader.sources[0]) for _ in range(129)]
    with pytest.raises(OperationContractError) as rejected:
        prepare_sfx(tmp_path, version, corrupt)
    assert rejected.value.error_code == ('SFX_SOURCE_LIMIT_EXCEEDED' if fault == 'limit' else 'INVALID_READBACK')


@pytest.mark.parametrize('version', VERSIONS)
def test_bound_existing_sfx_source_may_be_omitted_from_native_result_with_complete_live_proof(tmp_path, version):
    from tests.unit.test_operation_registry_import_verifier import _result
    prepared, reader = prepare_sfx(tmp_path, version)
    copied = []
    for row, source in zip(prepared['dispatch']['args']['imports'], reader.sources):
        original = Path(source['originalFilePath'])
        original.write_bytes(Path(row['audioFile']).read_bytes())
        copied.append(original)
    result = verify_prepared_operation(prepared, execution_result=_result(
        version, reader.owners, copied), read_call=reader)
    assert result.ok, [a for a in result.assertions if not a['passed']]


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('fault', ['unbound', 'wrong-bound-id', 'missing', 'new-source', 'extra', 'foreign-parent', 'wrong-language', 'wrong-media'])
def test_omitted_existing_sfx_source_requires_every_bound_live_proof(tmp_path, version, fault):
    from tests.unit.test_operation_registry_import_verifier import _result
    prepared, reader = prepare_sfx(tmp_path, version)
    copied = []
    for row, source in zip(prepared['dispatch']['args']['imports'], reader.sources):
        original = Path(source['originalFilePath'])
        original.write_bytes(Path(row['audioFile']).read_bytes())
        copied.append(original)
    target = prepared['verification_plan']['targets'][0]
    other_guid = '{88888888-8888-8888-8888-888888888888}'
    if fault == 'unbound':
        target.pop('existing_sfx_source_snapshot')
    elif fault == 'wrong-bound-id':
        target['existing_sfx_source_id'] = other_guid
    elif fault == 'missing':
        reader.sources.pop(0)
    elif fault == 'new-source':
        reader.sources[0]['id'] = other_guid
        reader.owners[0]['activeSource']['id'] = other_guid
    elif fault == 'extra':
        extra = deepcopy(reader.sources[0]); extra['id'] = other_guid
        reader.sources.append(extra)
    elif fault == 'foreign-parent':
        reader.sources[0]['parent']['id'] = RIGHT
    elif fault == 'wrong-language':
        reader.sources[0]['audioSource:language']['name'] = 'Japanese'
    else:
        copied[0].write_bytes(b'incorrect replacement')
    result = verify_prepared_operation(prepared, execution_result=_result(
        version, reader.owners, copied), read_call=reader)
    assert result.ok is False, fault


@pytest.mark.parametrize('version', VERSIONS)
def test_source_bound_reimport_still_rejects_changed_input_media_before_execute(tmp_path, version):
    prepared, reader = prepare_sfx(tmp_path, version)
    Path(prepared['dispatch']['args']['imports'][0]['audioFile']).write_bytes(b'changed after Preview')
    assert validate_prepared_roles(prepared, read_call=reader)['ok'] is False


def _public_2021_sfx_reimport(tmp_path, filename='Beta.wav', *, outcome='normal'):
    from tests.support.gateway_config import set_gateway_config
    from tests.unit.test_waapi_gateway import gateway_env, waapi_gateway
    reader = SfxReader(tmp_path, '2021.1')
    owner, active = reader.owners[0], reader.sources[0]
    active_file = Path(active['originalWavFilePath']).with_name('Alpha.wav')
    active_file.write_bytes(b'active alpha media')
    active.update(name='Alpha', path=owner['path'] + r'\Alpha',
        originalFilePath=str(active_file), originalWavFilePath=str(active_file))
    owner.update(activeSource={'id': active['id'], 'name': 'Alpha'},
        originalFilePath=str(active_file), **{'sound:originalWavFilePath': str(active_file), '@IsVoice': False})
    inactive_file = active_file.with_name('Beta.wav')
    inactive_file.write_bytes(b'inactive beta media')
    inactive = {**deepcopy(active), 'id': '{88888888-8888-8888-8888-888888888888}', 'name': 'Beta',
        'path': owner['path'] + r'\Beta', 'originalFilePath': str(inactive_file), 'originalWavFilePath': str(inactive_file)}
    reader.sources.append(inactive)
    replacement = tmp_path / 'replacement'; replacement.mkdir()
    (replacement / filename).write_bytes(b'new requested media')
    calls = []
    class Client:
        imported = False

        def call(self, uri, args=None, options=None):
            args, options = args or {}, options or {}
            calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri == 'ak.wwise.core.getInfo':
                from tests.unit.test_audio_import_business_gateway import _info
                info = _info(); info['version']['year'] = 2021; info['version']['displayName'] = 'v2021.1.0.1'
                return info
            if uri == 'ak.wwise.core.object.get' and args.get('waql') == 'from type Project take 1':
                return reader(uri, {'waql': 'from type Project take 2'}, options)
            if uri == 'ak.wwise.core.object.getPropertyAndReferenceNames':
                return {'return': ['IsVoice']}
            if uri == 'ak.wwise.core.object.getPropertyInfo':
                assert args['property'] == 'IsVoice', args
                return {'name': 'IsVoice', 'type': 'bool', 'default': False, 'dependencies': []}
            if uri in {'ak.wwise.core.undo.beginGroup', 'ak.wwise.core.undo.endGroup', 'ak.wwise.core.undo.cancelGroup'}:
                return {}
            if uri == 'ak.wwise.core.audio.import':
                self.imported = True
                assert len(args['imports']) == 1
                assert Path(args['imports'][0]['audioFile']).name == 'Alpha.wav'
                incoming = Path(args['imports'][0]['audioFile']).read_bytes()
                if not any(source['id'] == active['id'] for source in reader.sources):
                    reader.sources.append(active)
                    owner['sound:originalWavFilePath'] = str(active_file)
                    owner['originalFilePath'] = str(active_file)
                if outcome != 'stale-selected':
                    active_file.write_bytes(incoming)
                if outcome == 'changed-active':
                    # Same complete Source collection and valid returned Alpha;
                    # Beta also hashes correctly, but is now selected by the Sound.
                    inactive_file.write_bytes(incoming)
                    owner['sound:originalWavFilePath'] = str(inactive_file)
                    owner['originalFilePath'] = str(inactive_file)
                if outcome == 'contradictory-source-path':
                    inactive_file.write_bytes(incoming)
                returned = [owner] if outcome == 'omitted' else [owner, active]
                return {'objects': deepcopy(returned)}
            if (outcome == 'contradictory-source-path' and self.imported
                    and uri == 'ak.wwise.core.object.get' and args.get('from', {}).get('id') == [active['id']]
                    and 'originalWavFilePath' in options.get('return', [])):
                result = reader(uri, args, options)
                result['return'][0]['originalWavFilePath'] = str(inactive_file)
                return result
            return reader(uri, args, options)
        def disconnect(self):
            pass
    client = Client()
    env = set_gateway_config(gateway_env(tmp_path), wwise_version='2021.1')
    state = ['--state-dir', str(tmp_path / 'state')]
    def run(*argv):
        return waapi_gateway.execute_gateway([*state, *argv], env=env, client_factory=lambda _: client)
    code, started = run('draft-start', 'audio.import')
    assert code == 0, started
    draft, authority = started['draft']['draft_id'], started['task_authority']
    code, bound = run('draft-bind-object', draft, '--task-authority', authority,
        '--expected-revision', '1', '--object-id', owner['id'])
    assert code == 0, bound
    code, declared = run('draft-declare-import-batch', draft, '--task-authority', authority,
        '--expected-revision', str(bound['draft']['revision']), '--row-order', 'hit',
        '--existing-row', 'hit', bound['bound_object']['handle'], '--field', 'hit', 'language', 'SFX',
        '--media-directory', str(replacement), '--media-file', 'hit', filename)
    assert code == 0, declared
    return run, reader, calls, draft, authority, declared


def test_public_2021_sfx_reimport_cannot_bind_an_inactive_filename_as_active(tmp_path):
    run, reader, calls, draft, authority, declared = _public_2021_sfx_reimport(tmp_path)
    code, checked = run('draft-check', draft, '--task-authority', authority,
        '--expected-revision', str(declared['draft']['revision']))
    assert code == 2, checked
    assert 'AMBIGUOUS_SFX_SOURCE' in str(checked)
    assert not any(uri == 'ak.wwise.core.audio.import' for uri, _, _ in calls)


@pytest.mark.parametrize('outcome', ['normal', 'omitted', 'reordered', 'prewrite-bytes', 'changed-active', 'stale-selected', 'contradictory-source-path'])
def test_public_2021_sfx_reimport_binds_selection_and_own_media(tmp_path, outcome):
    run, reader, calls, draft, authority, declared = _public_2021_sfx_reimport(tmp_path, 'Alpha.wav', outcome=outcome)
    code, checked = run('draft-check', draft, '--task-authority', authority,
        '--expected-revision', str(declared['draft']['revision']))
    assert code == 0, checked
    code, preview = run('preview-from-draft', draft, '--task-authority', authority,
        '--expected-revision', str(checked['draft']['revision']))
    assert code == 0, preview
    transaction = preview['transaction_id']
    code, shown = run('transaction-show', transaction, '--summary-only')
    assert code == 0, shown
    code, confirmed = run('confirm', transaction, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    if outcome == 'prewrite-bytes':
        Path(reader.sources[0]['originalWavFilePath']).write_bytes(b'concurrent change without metadata drift')
    elif outcome == 'reordered':
        reader.sources.reverse()
    code, executed = run('execute', transaction)
    writes = [call for call in calls if call[0] == 'ak.wwise.core.audio.import']
    if outcome == 'prewrite-bytes':
        assert code == 2, executed
        assert not writes
        assert 'existing_sfx_active_original' in str(executed)
        return
    assert code == 0, executed
    assert len(writes) == 1
    code, verified = run('verify', transaction)
    if outcome in {'changed-active', 'stale-selected', 'contradictory-source-path'}:
        assert code == 2, verified
        assert verified['verified'] is False
        expected = {'changed-active': 'preview-bound GUID', 'stale-selected': 'hash matches',
                    'contradictory-source-path': 'original-file path remains bound'}[outcome]
        assert expected in str(verified)
    else:
        assert code == 0, verified
        assert verified['verified'] is True


@pytest.mark.parametrize('fault', ['missing', 'null', 'ambiguous', 'empty'])
def test_public_2021_sfx_reimport_requires_observable_unique_active_path(tmp_path, fault):
    run, reader, calls, draft, authority, declared = _public_2021_sfx_reimport(tmp_path, 'Alpha.wav')
    if fault == 'missing':
        del reader.owners[0]['sound:originalWavFilePath']
    elif fault == 'null':
        reader.owners[0]['sound:originalWavFilePath'] = None
    elif fault == 'empty':
        reader.owners[0]['sound:originalWavFilePath'] = None
        reader.sources = [source for source in reader.sources if source['parent']['id'] != reader.owners[0]['id']]
    else:
        reader.sources[-1]['originalWavFilePath'] = reader.sources[0]['originalWavFilePath']
    code, checked = run('draft-check', draft, '--task-authority', authority,
        '--expected-revision', str(declared['draft']['revision']))
    assert code == (0 if fault == 'empty' else 2), checked
    if fault != 'empty':
        assert ('INVALID_READBACK' if fault == 'missing' else 'AMBIGUOUS_SFX_SOURCE') in str(checked)
    assert not any(uri == 'ak.wwise.core.audio.import' for uri, _, _ in calls)


@pytest.mark.parametrize('insert_no_file_source', [False, True])
def test_public_2021_empty_sfx_preview_binds_no_source_precondition(tmp_path, insert_no_file_source):
    run, reader, calls, draft, authority, declared = _public_2021_sfx_reimport(tmp_path, 'Alpha.wav')
    owner = reader.owners[0]
    owner['sound:originalWavFilePath'] = None
    owner['activeSource'] = None
    reader.sources = [source for source in reader.sources if source['parent']['id'] != owner['id']]
    code, checked = run('draft-check', draft, '--task-authority', authority,
        '--expected-revision', str(declared['draft']['revision']))
    assert code == 0, checked
    code, preview = run('preview-from-draft', draft, '--task-authority', authority,
        '--expected-revision', str(checked['draft']['revision']))
    assert code == 0, preview
    transaction = preview['transaction_id']
    code, shown = run('transaction-show', transaction, '--summary-only')
    assert code == 0, shown
    code, confirmed = run('confirm', transaction, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    if insert_no_file_source:
        reader.sources.append({'id': '{99999999-9999-9999-9999-999999999999}', 'name': 'Tone',
            'type': 'Source', 'classId': 6684674, 'path': owner['path'] + r'\Tone', 'parent': {'id': owner['id']}})
    code, executed = run('execute', transaction)
    writes = [call for call in calls if call[0] == 'ak.wwise.core.audio.import']
    if insert_no_file_source:
        assert code == 2, executed
        assert not writes
    else:
        assert code == 0 and len(writes) == 1, executed
        code, verified = run('verify', transaction)
        assert code == 0 and verified['verified'] is True, verified
