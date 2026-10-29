"""Closed import-driven Switch assignment, through the public Gateway."""
import json
import pytest
from copy import deepcopy
from pathlib import Path

from tests.unit.test_audio_import_business_gateway import ImportFieldsClient, LocalizedOwnerFieldsClient, _import_fields_draft, PARENT_ID, waapi_gateway, _env
from tests.support.gateway_config import set_gateway_config
from tests.support.riff_wave import _tone_wav_bytes

WAV_BYTES = _tone_wav_bytes()


class SwitchImportClient(ImportFieldsClient):
    GROUP = '{A1111111-1111-1111-1111-111111111111}'
    VALUE = '{22222222-2222-2222-2222-222222222222}'
    CHILD = '{33333333-3333-3333-3333-333333333333}'
    OTHER = '{44444444-4444-4444-4444-444444444444}'
    OTHER_VALUE = '{55555555-5555-5555-5555-555555555555}'

    def __init__(self, tmp_path: Path, *, effect=True, media=False, version="2025.1"):
        super().__init__(tmp_path, version)
        self.expected_directive = "<Switch Group:Surface>Snow"
        self.effect = effect
        self.media = media
        self.parent.update(type='SwitchContainer', classId=1, **{'SwitchGroupOrStateGroup': {'id': self.GROUP}})
        self.group = {'id': self.GROUP, 'name': 'Surface', 'type': 'SwitchGroup',
                      'path': r'\Switches\Default Work Unit\Surface'}
        self.value = {'id': self.VALUE, 'name': 'Snow', 'type': 'Switch',
                      'path': self.group['path'] + r'\Snow', 'parent': {'id': self.GROUP}}
        self.child = {'id': self.CHILD, 'name': 'SnowSounds', 'type': 'RandomSequenceContainer', 'classId': 2,
                      'path': self.parent['path'] + r'\SnowSounds', 'parent': {'id': PARENT_ID}}
        self.assignments = [{'child': self.OTHER, 'stateOrSwitch': self.OTHER_VALUE}]
        self.created = False
        self.source = {'id': '{66666666-6666-6666-6666-666666666666}', 'name': 'Snow', 'type': 'AudioFileSource', 'classId': 16,
                       'path': self.child['path'] + r'\Snow', 'parent': {'id': self.CHILD},
                       'audioSource:language': {'name': 'SFX'}, 'originalFilePath': str(tmp_path / 'project/Originals/SFX/Snow.wav'),
                       'originalWavFilePath': str(tmp_path / 'project/Originals/SFX/Snow.wav')}
        if media:
            self.child.update(type='Sound', classId=65552, **{'@IsVoice': False, '@Volume': -6.0, 'activeSource': {'id': self.source['id']},
                'sound:originalWavFilePath': self.source['originalWavFilePath']})

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == 'ak.wwise.core.switchContainer.getAssignments':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': deepcopy(self.assignments)}
        if uri == 'ak.wwise.core.object.getPropertyAndReferenceNames':
            self.calls.append((uri, args, options))
            return {'return': ['Volume', 'IsVoice']}
        if uri == 'ak.wwise.core.object.getPropertyInfo' and args['property'] == 'IsVoice':
            self.calls.append((uri, args, options))
            return {'name': 'IsVoice', 'type': 'bool', 'default': False, 'dependencies': []}
        if uri == 'ak.wwise.core.audio.import':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if self.media:
                owner_row, source_row = args['imports']
                assert owner_row['objectPath'] == self.parent['path'] + r'\<Sound SFX>SnowSounds'
                assert owner_row['switchAssignation'] == self.expected_directive
                assert owner_row['@Volume'] == -6.0
                assert 'audioFile' not in owner_row and 'switchAssignation' not in source_row
                assert source_row['objectPath'].endswith(r'\<Sound SFX>SnowSounds\<AudioFileSource>Snow')
                copied = Path(self.source['originalFilePath'])
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(Path(source_row['audioFile']).read_bytes())
            else:
                assert args['imports'] == [{'objectPath': self.parent['path'] + r'\<Random Container>SnowSounds',
                                            'objectType': 'RandomSequenceContainer', 'switchAssignation': self.expected_directive}]
            self.created = True
            if self.effect:
                self.assignments.append({'child': self.CHILD, 'stateOrSwitch': self.VALUE})
            result = {'objects': deepcopy([self.child, *([self.source] if self.media else [])])}
            if self.version in {'2023.1', '2024.1', '2025.1'}:
                result.update(log=[], files=[self.source['originalFilePath']] if self.media else [])
            return result
        if uri.startswith('ak.wwise.core.undo.'):
            self.calls.append((uri, args, options))
            return {}
        if uri == 'ak.wwise.core.object.get':
            source = args.get('from', {})
            rows = [self.parent, self.group, self.value, *([self.child, *([self.source] if self.media else [])] if self.created else [])]
            if 'waql' in args and self.GROUP in args['waql'] and 'Snow' in args['waql']:
                selected = [self.value] if self.value['name'] == 'Snow' else []
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {'return': [{k: deepcopy(r[k]) for k in options['return'] if k in r} for r in selected]}
            else:
                selected = [r for r in rows if r['id'] in source.get('id', []) or r['path'] in source.get('path', [])]
            if selected:
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {'return': [{k: deepcopy(r[k]) for k in options.get('return', r) if k in r} for r in selected]}
        return super().call(uri, args, options)


def _draft(tmp_path, *, effect=True, media=False, version="2025.1"):
    client = SwitchImportClient(tmp_path, effect=effect, media=media, version=version)
    command, parent, _ = _import_fields_draft(tmp_path, version, client)
    if media:
        (tmp_path / 'Snow.wav').write_bytes(WAV_BYTES)
    command('draft-declare-new', '--declaration-id', 'snow', '--parent-handle', parent,
            '--name', 'SnowSounds', '--kind', 'sound-sfx' if media else 'random-container', '--switch-value', 'Snow',
            *(('--field', 'media_file', str(tmp_path / 'Snow.wav'), '--field', 'volume_db', '-6') if media else ()))
    return command, client


def test_import_assigns_new_owner_to_bound_switch_and_preserves_unrelated_pairs(tmp_path):
    command, client = _draft(tmp_path)
    command('draft-check')
    preview = command('preview-from-draft')
    assert not any(u == 'ak.wwise.core.audio.import' for u, _, _ in client.calls)
    tx = preview['transaction_id']
    shown = command('transaction-show', tx, '--summary-only')
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    verified = command('verify', tx)
    assert verified['verified'] is True, json.dumps(verified, indent=2)
    assert client.assignments == [{'child': client.OTHER, 'stateOrSwitch': client.OTHER_VALUE},
                                  {'child': client.CHILD, 'stateOrSwitch': client.VALUE}]
    assert len([u for u, _, _ in client.calls if u == 'ak.wwise.core.audio.import']) == 1
    assert not any(u.endswith('.addAssignment') or u.endswith('.setReference') for u, _, _ in client.calls)


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_import_media_assignment_stays_on_sound_owner_during_source_expansion(tmp_path, version):
    command, client = _draft(tmp_path, media=True, version=version)
    command('draft-check')
    tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx, '--summary-only')
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    verified = command('verify', tx)
    assert verified['verified'] is True, verified
    assert client.assignments[-1] == {'child': client.CHILD, 'stateOrSwitch': client.VALUE}
    assert Path(client.source['originalFilePath']).read_bytes() == WAV_BYTES
    assert len([u for u, _, _ in client.calls if u == 'ak.wwise.core.audio.import']) == 1


def test_import_rejects_value_from_another_group_before_preview(tmp_path):
    command, client = _draft(tmp_path)
    client.value['parent'] = {'id': client.OTHER_VALUE}
    command('draft-check', expected_error='IDENTITY_MISMATCH')
    assert not any(u == 'ak.wwise.core.audio.import' for u, _, _ in client.calls)


def test_import_rejects_missing_exact_switch_value_before_preview(tmp_path):
    command, client = _draft(tmp_path)
    client.value['name'] = 'Rain'
    # Model the exact scoped lookup: the requested Snow value is absent.
    client.value['path'] = client.group['path'] + r'\Rain'
    command('draft-check', expected_error='AMBIGUOUS_IDENTITY')
    assert not any(u == 'ak.wwise.core.audio.import' for u, _, _ in client.calls)


def test_import_media_success_does_not_verify_an_ignored_switch_assignment(tmp_path):
    command, client = _draft(tmp_path, effect=False, media=True)
    command('draft-check')
    tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx, '--summary-only')
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    code, result = waapi_gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), 'verify', tx],
        env=set_gateway_config(_env(tmp_path), wwise_version='2025.1'), client_factory=lambda _url: client)
    assert code == 2, result
    assert result['verified'] is False
    assert Path(client.source['originalFilePath']).read_bytes() == WAV_BYTES
    assert any(not row['passed'] and 'Switch assignment effect' in row['name'] for row in result['verification']['assertions'])


@pytest.mark.parametrize("drift", ("assignments", "group"))
def test_import_switch_assignment_prestate_drift_blocks_single_import(tmp_path, drift):
    command, client = _draft(tmp_path)
    command('draft-check')
    tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx, '--summary-only')
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    if drift == "assignments":
        client.assignments.clear()
    else:
        client.parent["SwitchGroupOrStateGroup"] = {"id": client.OTHER_VALUE}
    command('execute', tx, expected_error='ROLE_GUARD_MISMATCH')
    assert not any(u == 'ak.wwise.core.audio.import' for u, _, _ in client.calls)


def test_import_switch_value_does_not_accept_caller_native_directive_grammar(tmp_path):
    command, client = _draft(tmp_path)
    command('draft-revise-declaration', '--declaration-id', 'snow', '--switch-value', '<Switch Group:Surface>Snow')
    command('draft-check', expected_error='INVALID_SWITCH_VALUE')
    assert not any(u == 'ak.wwise.core.audio.import' for u, _, _ in client.calls)


class ExistingSfxSwitchImportClient(SwitchImportClient):
    """Existing Sound reuse with no unrelated field to force owner splitting."""

    def __init__(self, tmp_path, version="2025.1"):
        super().__init__(tmp_path, media=True, version=version)
        self.created = True
        self.child.pop('@Volume')
        self.child['notes'] = 'keep owner notes'
        self.source['notes'] = 'keep source notes'
        self.source['audioSource:language']['id'] = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
        self.source['originalFilePath'] = str(tmp_path / 'project/Originals/SFX/Footsteps/Snow.wav')
        self.source['originalWavFilePath'] = self.source['originalFilePath']
        self.child['sound:originalWavFilePath'] = self.source['originalFilePath']
        original = Path(self.source['originalFilePath'])
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(_tone_wav_bytes(samples=[100] * 8))

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == 'ak.wwise.core.object.get' and args.get('waql') == f'from object "{self.CHILD}" select children take 129':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [{k: deepcopy(self.source[k]) for k in options['return'] if k in self.source}]}
        if uri == 'ak.wwise.core.audio.import':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args['importOperation'] == 'useExisting'
            owner_row, source_row = args['imports']
            owner_path = self.child['path']
            assert owner_row == {'objectPath': owner_path, 'objectType': 'Sound SFX',
                                 'switchAssignation': self.expected_directive}
            expected_media = {'audioFile': str(self.tmp_path / 'Snow.wav'), 'importLanguage': 'SFX', 'originalsSubFolder': 'Footsteps'}
            if self.version == '2025.1':
                expected_media.update(objectPath='', importLocation=self.source['id'])
            else:
                expected_media['objectPath'] = owner_path + r'\<AudioFileSource>Snow'
            assert source_row == expected_media
            Path(self.source['originalFilePath']).write_bytes(Path(source_row['audioFile']).read_bytes())
            self.assignments.append({'child': self.CHILD, 'stateOrSwitch': self.VALUE})
            result = {'objects': deepcopy([self.child, self.source])}
            if self.version in {'2023.1', '2024.1', '2025.1'}:
                result.update(log=[], files=[self.source['originalFilePath']])
            return result
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_existing_sfx_media_and_switch_only_reimport_keeps_directive_on_owner(tmp_path, version):
    client = ExistingSfxSwitchImportClient(tmp_path, version)
    before_owner, before_source = deepcopy(client.child), deepcopy(client.source)
    before_assignments = deepcopy(client.assignments)
    command, _, _ = _import_fields_draft(tmp_path, version, client)
    (tmp_path / 'Snow.wav').write_bytes(WAV_BYTES)
    bound = command('draft-bind-object', '--object-id', client.CHILD)
    command('draft-declare-existing', '--declaration-id', 'snow', '--object-handle', bound['bound_object']['handle'],
            '--field', 'media_file', str(tmp_path / 'Snow.wav'), '--switch-value', 'Snow')
    command('draft-check')
    tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx)
    rows = shown['artifact']['prepared_operation']['dispatch']['args']['imports']
    assert len(rows) == 2, rows
    assert rows[0]['switchAssignation'] == '<Switch Group:Surface>Snow'
    assert 'audioFile' not in rows[0] and 'switchAssignation' not in rows[1]
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    verified = command('verify', tx)
    assert verified['verified'] is True, verified
    assert client.assignments == [*before_assignments, {'child': client.CHILD, 'stateOrSwitch': client.VALUE}]
    assert client.child == before_owner and client.source == before_source
    assert Path(client.source['originalFilePath']).read_bytes() == WAV_BYTES
    assert len([u for u, _, _ in client.calls if u == 'ak.wwise.core.audio.import']) == 1
    assert not any(u.endswith('.addAssignment') or u.endswith('.setReference') for u, _, _ in client.calls)


def test_existing_import_adds_value_without_discarding_another_assignment(tmp_path):
    client = ExistingSfxSwitchImportClient(tmp_path)
    client.assignments.append({'child': client.CHILD, 'stateOrSwitch': client.OTHER_VALUE})
    before = deepcopy(client.assignments)
    command, _, _ = _import_fields_draft(tmp_path, '2025.1', client)
    (tmp_path / 'Snow.wav').write_bytes(WAV_BYTES)
    bound = command('draft-bind-object', '--object-id', client.CHILD)
    command('draft-declare-existing', '--declaration-id', 'snow', '--object-handle', bound['bound_object']['handle'],
            '--field', 'media_file', str(tmp_path / 'Snow.wav'), '--switch-value', 'Snow')
    command('draft-check')
    tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx, '--summary-only')
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    result = command('verify', tx)
    assert result['verified'] is True, result
    assert client.assignments == [*before, {'child': client.CHILD, 'stateOrSwitch': client.VALUE}]
    assert Path(client.source['originalFilePath']).read_bytes() == WAV_BYTES


class ReplacingSwitchImportClient(SwitchImportClient):
    REPLACEMENT = '{99999999-9999-9999-9999-999999999999}'

    def __init__(self, tmp_path, version):
        super().__init__(tmp_path, version=version)
        self.created = True
        self.child['@RandomOrSequence'] = 0
        self.assignments.extend([{'child': self.CHILD, 'stateOrSwitch': self.VALUE},
                                 {'child': self.CHILD, 'stateOrSwitch': self.OTHER_VALUE}])
        self.leave_old_pair = False

    def call(self, uri, args=None, options=None):
        if uri == 'ak.wwise.core.audio.import':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args['importOperation'] == 'replaceExisting'
            assert args['imports'] == [{'objectPath': self.child['path'],
                'objectType': 'RandomSequenceContainer', 'switchAssignation': self.expected_directive}]
            if not self.leave_old_pair:
                self.assignments = [pair for pair in self.assignments if pair['child'] != self.CHILD]
            self.child['id'] = self.REPLACEMENT
            self.assignments.append({'child': self.REPLACEMENT, 'stateOrSwitch': self.VALUE})
            return {'objects': deepcopy([self.child]), **({'log': [], 'files': []}
                if self.version in {'2023.1', '2024.1', '2025.1'} else {})}
        return super().call(uri, args, options)


def _replace_draft(tmp_path, version):
    client = ReplacingSwitchImportClient(tmp_path, version)
    command, _, _ = _import_fields_draft(tmp_path, version, client)
    bound = command('draft-bind-object', '--object-id', client.CHILD)
    command('draft-business-configure', '--mode', 'replace')
    command('draft-declare-existing', '--declaration-id', 'snow',
            '--object-handle', bound['bound_object']['handle'], '--switch-value', 'Snow')
    return command, client


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'))
def test_switch_replacement_rebinds_new_owner_and_removes_only_old_owner_pairs(tmp_path, version):
    command, client = _replace_draft(tmp_path, version)
    command('draft-check')
    tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx)
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    verified = command('verify', tx)
    assert verified['verified'] is True, verified
    assert client.assignments == [{'child': client.OTHER, 'stateOrSwitch': client.OTHER_VALUE},
                                  {'child': client.REPLACEMENT, 'stateOrSwitch': client.VALUE}]
    assert len([u for u, _, _ in client.calls if u == 'ak.wwise.core.audio.import']) == 1


def test_switch_replacement_cannot_hide_stale_old_owner_assignment(tmp_path):
    command, client = _replace_draft(tmp_path, '2025.1')
    client.leave_old_pair = True
    command('draft-check')
    tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx)
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    code, verified = waapi_gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), 'verify', tx],
        env=set_gateway_config(_env(tmp_path), wwise_version='2025.1'), client_factory=lambda _url: client)
    assert code == 2 and verified['verified'] is False, verified
    assert any(not row['passed'] and 'Switch assignment effect' in row['name']
               for row in verified['verification']['assertions'])


class LocalizedSwitchImportClient(LocalizedOwnerFieldsClient):
    GROUP = SwitchImportClient.GROUP
    VALUE = SwitchImportClient.VALUE

    def __init__(self, tmp_path, version):
        super().__init__(tmp_path, version)
        self.parent.update(type='SwitchContainer', classId=1, SwitchGroupOrStateGroup={'id': self.GROUP})
        self.group = {'id': self.GROUP, 'name': 'Surface', 'type': 'SwitchGroup',
                      'path': r'\Switches\Default Work Unit\Surface'}
        self.value = {'id': self.VALUE, 'name': 'Snow', 'type': 'Switch',
                      'path': self.group['path'] + r'\Snow', 'parent': {'id': self.GROUP}}
        self.assignments = [{'child': '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}', 'stateOrSwitch': self.VALUE}]
        self.assignment_effect = True

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == 'ak.wwise.core.switchContainer.getAssignments':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': deepcopy(self.assignments)}
        if uri == 'ak.wwise.core.audio.import':
            owner, source = args['imports']
            assert owner['switchAssignation'] == '<Switch Group:Surface>Snow'
            assert 'audioFile' not in owner and 'switchAssignation' not in source
            assert source['importLanguage'] == 'English(US)'
            result = super().call(uri, args, options)
            if self.assignment_effect:
                self.assignments.append({'child': self.OWNER, 'stateOrSwitch': self.VALUE})
            return result
        if uri == 'ak.wwise.core.object.get':
            source = args.get('from', {})
            rows = [r for r in (self.group, self.value)
                    if r['id'] in source.get('id', []) or r['path'] in source.get('path', [])]
            scoped_value = self.GROUP in args.get('waql', '') and 'Snow' in args['waql']
            if scoped_value:
                rows = [self.value]
            if rows:
                result = {'return': []} if scoped_value else super().call(uri, args, options)
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                result['return'].extend({k: deepcopy(r[k]) for k in options['return'] if k in r} for r in rows)
                return result
        return super().call(uri, args, options)


def _localized_switch_draft(tmp_path, version):
    client = LocalizedSwitchImportClient(tmp_path, version)
    command, _, _ = _import_fields_draft(tmp_path, version, client)
    media = tmp_path / 'Line.wav'; media.write_bytes(WAV_BYTES)
    bound = command('draft-bind-object', '--object-id', client.OWNER)
    command('draft-declare-existing', '--declaration-id', 'voice', '--object-handle', bound['bound_object']['handle'],
            '--field', 'media_file', str(media), '--field', 'language', 'English(US)', '--switch-value', 'Snow')
    return command, client


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'))
def test_localized_switch_reimport_assigns_owner_and_preserves_other_language_source(tmp_path, version):
    command, client = _localized_switch_draft(tmp_path, version)
    before_sources, before_owner = deepcopy(client.sources), deepcopy(client.owner)
    other_bytes = client.other_file.read_bytes()
    before_pairs = deepcopy(client.assignments)
    command('draft-check')
    tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx)
    owner, source = shown['artifact']['prepared_operation']['dispatch']['args']['imports']
    if version == '2025.1':
        assert owner['objectPath'] == client.owner['path']
    else:
        assert owner['objectPath'].endswith(r'\<Sound Voice>Voice')
    assert owner['switchAssignation'] == '<Switch Group:Surface>Snow'
    assert 'switchAssignation' not in source
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    verified = command('verify', tx)
    assert verified['verified'] is True, verified
    assert client.assignments == [*before_pairs, {'child': client.OWNER, 'stateOrSwitch': client.VALUE}]
    assert client.sources == before_sources and client.owner == before_owner
    assert client.copied.read_bytes() == WAV_BYTES and client.other_file.read_bytes() == other_bytes
    assert len([u for u, _, _ in client.calls if u == 'ak.wwise.core.audio.import']) == 1


def test_localized_media_cannot_hide_ignored_switch_assignment(tmp_path):
    command, client = _localized_switch_draft(tmp_path, '2025.1')
    client.assignment_effect = False
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx)
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    code, verified = waapi_gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), 'verify', tx],
        env=set_gateway_config(_env(tmp_path), wwise_version='2025.1'), client_factory=lambda _url: client)
    assert code == 2 and verified['verified'] is False, verified
    assert client.copied.read_bytes() == WAV_BYTES
    assert any(not row['passed'] and 'Switch assignment effect' in row['name']
               for row in verified['verification']['assertions'])


class ExplicitGroupImportClient(SwitchImportClient):
    CONTAINER = '{99999999-1111-1111-1111-111111111111}'
    WORK_UNIT = '{99999999-2222-2222-2222-222222222222}'
    REPLACED_PARENT = '{99999999-3333-3333-3333-333333333333}'
    NEW_GROUP = '{99999999-4444-4444-4444-444444444444}'

    def __init__(self, tmp_path, version):
        super().__init__(tmp_path, version=version)
        self.container_created = False
        self.container = {'id': self.CONTAINER, 'name': 'Cases', 'type': 'SwitchContainer', 'classId': 1,
            'path': self.parent['path'] + r'\Cases', 'parent': {'id': PARENT_ID},
            'SwitchGroupOrStateGroup': {'id': self.GROUP}}
        self.work_unit = {'id': self.WORK_UNIT, 'name': 'Default Work Unit', 'type': 'WorkUnit',
            'path': self.parent['path'].rpartition('\\')[0]}
        self.new_pairs = []
        self.group_types = ['SwitchGroup', 'StateGroup']

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == 'ak.wwise.core.object.getPropertyInfo' and args['property'] == 'SwitchGroupOrStateGroup':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'name': 'SwitchGroupOrStateGroup', 'type': 'Reference',
                    'restriction': {'type': 'reference', 'restrictions': [{'type': list(self.group_types)}]}}
        if uri == 'ak.wwise.core.switchContainer.getAssignments' and args['id'] == self.CONTAINER:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert self.container_created
            return {'return': deepcopy(self.new_pairs)}
        if uri == 'ak.wwise.core.object.get':
            identity = args.get('from', {})
            if identity.get('id') == [PARENT_ID] and self.parent['id'] != PARENT_ID:
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {'return': []}
            extra = [self.work_unit, *([self.container] if self.container_created else [])]
            selected = [row for row in extra if row['id'] in identity.get('id', []) or row['path'] in identity.get('path', [])]
            if selected:
                result = super().call(uri, args, options)
                result['return'].extend({key: deepcopy(row[key]) for key in options['return'] if key in row} for row in selected)
                return result
        if uri == 'ak.wwise.core.audio.import':
            rows = args['imports']
            if len(rows) == 1 and rows[0]['objectPath'] == self.parent['path'] + r'\<Random Container>SnowSounds':
                return super().call(uri, args, options)
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert rows[0]['switchAssignation'] == '<Switch Group:Surface>'
            if rows[0]['objectPath'] == self.parent['path']:
                assert len(rows) == 1
                self.parent['SwitchGroupOrStateGroup'] = {'id': self.group['id']}
                if args['importOperation'] == 'replaceExisting':
                    self.parent['id'] = self.REPLACED_PARENT
                    self.assignments = []
                returned = [self.parent]
            else:
                assert rows[0]['objectPath'] == self.parent['path'] + r'\<Switch Container>Cases'
                assert rows[1]['objectPath'] == rows[0]['objectPath'] + r'\<Random Container>SnowSounds'
                assert rows[1]['switchAssignation'] == '<Switch Group:Surface>Snow'
                self.container_created = self.created = True
                self.child.update(path=self.container['path'] + r'\SnowSounds', parent={'id': self.CONTAINER})
                self.new_pairs = [{'child': self.CHILD, 'stateOrSwitch': self.VALUE}]
                returned = [self.container, self.child]
            return {'objects': deepcopy(returned), **({'log': [], 'files': []}
                if self.version in {'2023.1', '2024.1', '2025.1'} else {})}
        return super().call(uri, args, options)


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'))
def test_ordinary_bound_group_only_associates_empty_existing_switch_container(tmp_path, version):
    client = ExplicitGroupImportClient(tmp_path, version)
    client.parent['SwitchGroupOrStateGroup'] = None; client.assignments = []
    command, parent, _ = _import_fields_draft(tmp_path, version, client)
    group = command('draft-bind-object', '--object-id', client.GROUP)['bound_object']['handle']
    command('draft-declare-existing', '--declaration-id', 'group', '--object-handle', parent,
            '--field', 'switch_group', group)
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx)
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx); verified = command('verify', tx)
    assert verified['verified'] is True, verified
    assert client.parent['SwitchGroupOrStateGroup'] == {'id': client.GROUP} and client.assignments == []
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.core.audio.import']) == 1


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'))
def test_ordinary_new_container_group_and_direct_child_share_one_import(tmp_path, version):
    client = ExplicitGroupImportClient(tmp_path, version)
    command, parent, _ = _import_fields_draft(tmp_path, version, client)
    group = command('draft-bind-object', '--object-id', client.GROUP)['bound_object']['handle']
    command('draft-declare-import-batch', '--row-order', 'cases', 'snow',
            '--new-row', 'cases', parent, 'Cases', 'switch-container', '--field', 'cases', 'switch_group', group,
            '--new-row', 'snow', 'cases', 'SnowSounds', 'random-container', '--switch-value', 'snow', 'Snow')
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx)
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx); verified = command('verify', tx)
    assert verified['verified'] is True, verified
    assert client.new_pairs == [{'child': client.CHILD, 'stateOrSwitch': client.VALUE}]
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.core.audio.import']) == 1
    assert not any(uri.endswith(('.setReference', '.addAssignment')) for uri, _, _ in client.calls)


def test_ordinary_explicit_group_value_reuses_exact_group_without_discarding_pairs(tmp_path):
    client = ExplicitGroupImportClient(tmp_path, '2025.1')
    command, parent, _ = _import_fields_draft(tmp_path, '2025.1', client)
    group = command('draft-bind-object', '--object-id', client.GROUP)['bound_object']['handle']
    command('draft-declare-new', '--declaration-id', 'snow', '--parent-handle', parent,
            '--name', 'SnowSounds', '--kind', 'random-container', '--field', 'switch_group', group, '--switch-value', 'Snow')
    before = deepcopy(client.assignments)
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx)
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx); verified = command('verify', tx)
    assert verified['verified'] is True, verified
    assert client.assignments == [*before, {'child': client.CHILD, 'stateOrSwitch': client.VALUE}]


@pytest.mark.parametrize('fault', ('wrong-handle-type', 'metadata-drift', 'occupied-group'))
def test_ordinary_group_input_keeps_exact_type_metadata_and_occupied_pair_guards(tmp_path, fault):
    client = ExplicitGroupImportClient(tmp_path, '2025.1')
    command, parent, _ = _import_fields_draft(tmp_path, '2025.1', client)
    if fault == 'occupied-group':
        client.group['id'] = client.NEW_GROUP
    group = (parent if fault == 'wrong-handle-type' else
             command('draft-bind-object', '--object-id', client.group['id'])['bound_object']['handle'])
    command('draft-declare-existing', '--declaration-id', 'group', '--object-handle', parent,
            '--field', 'switch_group', group)
    if fault == 'wrong-handle-type':
        command('draft-check', expected_error='OPERATION_DRAFT_ACTION_INVALID')
    elif fault == 'occupied-group':
        command('draft-check', expected_error='IMPORT_SWITCH_GROUP_CHANGE_WITH_ASSIGNMENTS_UNSUPPORTED')
    elif fault == 'metadata-drift':
        command('draft-check'); tx = command('preview-from-draft')['transaction_id']
        shown = command('transaction-show', tx)
        command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        client.group_types = ['StateGroup']
        command('execute', tx, expected_error='ROLE_GUARD_MISMATCH')
    assert not any(uri == 'ak.wwise.core.audio.import' for uri, _, _ in client.calls)


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'))
def test_explicit_whole_container_replacement_can_bind_a_different_group(tmp_path, version):
    client = ExplicitGroupImportClient(tmp_path, version)
    client.group['id'] = client.NEW_GROUP
    command, parent, _ = _import_fields_draft(tmp_path, version, client)
    group = command('draft-bind-object', '--object-id', client.group['id'])['bound_object']['handle']
    command('draft-business-configure', '--mode', 'replace')
    command('draft-declare-existing', '--declaration-id', 'replace', '--object-handle', parent,
            '--field', 'switch_group', group)
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx)
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    code, verified = waapi_gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), 'verify', tx],
        env=set_gateway_config(_env(tmp_path), wwise_version=version), client_factory=lambda _url: client)
    assert code == 0 and verified['verified'] is True, [row for row in verified['verification']['assertions'] if not row['passed']]
    assert client.parent['id'] == client.REPLACED_PARENT and client.assignments == []
    assert client.parent['SwitchGroupOrStateGroup'] == {'id': client.group['id']}
    assert len([uri for uri, _, _ in client.calls if uri == 'ak.wwise.core.audio.import']) == 1


class SwitchDirectiveFormsClient(ExistingSfxSwitchImportClient):
    def __init__(self, tmp_path, form):
        super().__init__(tmp_path)
        if form == 'nested-state':
            self.group.update(type='StateGroup', path=r'\States\Default Work Unit\Biome\Winter\Surface')
            self.value['type'] = 'State'
            self.expected_directive = r'<State Group:Biome\Winter\Surface>Snow'
        else:
            self.group['path'] = r'\Switches\Default Work Unit\Biome\Winter\Surface'
            self.expected_directive = r'<Switch Group:Biome\Winter\Surface>Snow'
        self.group['parent'] = {'id': '{A2222222-2222-2222-2222-222222222222}'}
        self.value['path'] = self.group['path'] + r'\Snow'


@pytest.mark.parametrize('form', ('nested-state', 'nested-switch'))
def test_switch_import_resolves_state_and_nested_virtual_folder_group_forms(tmp_path, form):
    client = SwitchDirectiveFormsClient(tmp_path, form)
    before = deepcopy(client.assignments)
    command, _, _ = _import_fields_draft(tmp_path, '2025.1', client)
    (tmp_path / 'Snow.wav').write_bytes(WAV_BYTES)
    bound = command('draft-bind-object', '--object-id', client.CHILD)
    command('draft-declare-existing', '--declaration-id', 'snow', '--object-handle', bound['bound_object']['handle'],
            '--field', 'media_file', str(tmp_path / 'Snow.wav'), '--switch-value', 'Snow')
    command('draft-check')
    tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx)
    assert shown['artifact']['prepared_operation']['dispatch']['args']['imports'][0]['switchAssignation'] == client.expected_directive
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    result = command('verify', tx)
    assert result['verified'] is True, result
    assert client.assignments == [*before, {'child': client.CHILD, 'stateOrSwitch': client.VALUE}]
    assert Path(client.source['originalFilePath']).read_bytes() == WAV_BYTES


def test_switch_import_rejects_value_type_mismatched_to_actual_state_group(tmp_path):
    client = SwitchDirectiveFormsClient(tmp_path, 'nested-state')
    client.value['type'] = 'Switch'
    command, parent, _ = _import_fields_draft(tmp_path, '2025.1', client)
    command('draft-declare-new', '--declaration-id', 'snow', '--parent-handle', parent,
            '--name', 'OtherSnow', '--kind', 'random-container', '--switch-value', 'Snow')
    command('draft-check', expected_error='IDENTITY_MISMATCH')
    assert not any(uri == 'ak.wwise.core.audio.import' for uri, _, _ in client.calls)
