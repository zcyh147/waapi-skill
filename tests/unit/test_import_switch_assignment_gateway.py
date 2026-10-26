"""First closed import-driven Switch assignment, through the public Gateway."""
import json
import pytest
from copy import deepcopy
from pathlib import Path

from tests.unit.test_audio_import_business_gateway import ImportFieldsClient, _import_fields_draft, PARENT_ID, waapi_gateway, _env
from tests.support.gateway_config import set_gateway_config


class SwitchImportClient(ImportFieldsClient):
    GROUP = '{A1111111-1111-1111-1111-111111111111}'
    VALUE = '{22222222-2222-2222-2222-222222222222}'
    CHILD = '{33333333-3333-3333-3333-333333333333}'
    OTHER = '{44444444-4444-4444-4444-444444444444}'
    OTHER_VALUE = '{55555555-5555-5555-5555-555555555555}'

    def __init__(self, tmp_path: Path, *, effect=True, media=False):
        super().__init__(tmp_path, '2025.1')
        self.effect = effect
        self.media = media
        self.parent.update(type='SwitchContainer', **{'SwitchGroupOrStateGroup': {'id': self.GROUP}})
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
                       'audioSource:language': {'name': 'SFX'}, 'originalFilePath': str(tmp_path / 'project/Originals/SFX/Snow.wav')}
        if media:
            self.child.update(type='Sound', classId=65552, **{'@IsVoice': False, '@Volume': -6.0, 'activeSource': {'id': self.source['id']}})

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
                assert owner_row['switchAssignation'] == '<Switch Group:Surface>Snow'
                assert owner_row['@Volume'] == -6.0
                assert 'audioFile' not in owner_row and 'switchAssignation' not in source_row
                assert source_row['objectPath'].endswith(r'\<Sound SFX>SnowSounds\<AudioFileSource>Snow')
                copied = Path(self.source['originalFilePath'])
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(Path(source_row['audioFile']).read_bytes())
            else:
                assert args['imports'] == [{'objectPath': self.parent['path'] + r'\<Random Container>SnowSounds',
                                            'objectType': 'RandomSequenceContainer', 'switchAssignation': '<Switch Group:Surface>Snow'}]
            self.created = True
            if self.effect:
                self.assignments.append({'child': self.CHILD, 'stateOrSwitch': self.VALUE})
            return {'objects': deepcopy([self.child, *([self.source] if self.media else [])]), 'log': [], 'files': [self.source['originalFilePath']] if self.media else []}
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


def _draft(tmp_path, *, effect=True, media=False):
    client = SwitchImportClient(tmp_path, effect=effect, media=media)
    command, parent, _ = _import_fields_draft(tmp_path, '2025.1', client)
    if media:
        (tmp_path / 'Snow.wav').write_bytes(b'RIFF requested media')
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


def test_import_media_assignment_stays_on_sound_owner_during_source_expansion(tmp_path):
    command, client = _draft(tmp_path, media=True)
    command('draft-check')
    tx = command('preview-from-draft')['transaction_id']
    shown = command('transaction-show', tx, '--summary-only')
    command('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    command('execute', tx)
    verified = command('verify', tx)
    assert verified['verified'] is True, verified
    assert client.assignments[-1] == {'child': client.CHILD, 'stateOrSwitch': client.VALUE}
    assert Path(client.source['originalFilePath']).read_bytes() == b'RIFF requested media'
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
    assert Path(client.source['originalFilePath']).read_bytes() == b'RIFF requested media'
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
