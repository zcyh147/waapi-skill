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
