"""Localized exact-table lifecycle at the public Draft/transaction boundary."""
import base64
import csv
from copy import deepcopy
from pathlib import Path

import pytest

from tests.unit.test_audio_import_business_gateway import LocalizedOwnerOnlyTabClient
from tests.unit.test_import_dialogue_association_gateway import _table_lifecycle_draft
from tests.unit.test_tsv_source_lifecycle_gateway import execute_table
from tests.support.riff_wave import _tone_wav_bytes

VERSIONS = ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')


class LocalizedTableClient(LocalizedOwnerOnlyTabClient):
    NEW_OWNER = '{91919191-9191-9191-9191-919191919191}'
    DEEP = '{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAC}'

    def __init__(self, tmp_path, version, *, existing=True):
        super().__init__(tmp_path, version)
        self.exists = existing
        self.sources = self.sources if existing else []
        self.retired = []
        self.fault = None
        self.owner_path = self.owner['path']
        self.deep = {'id': self.DEEP, 'path': self.owner_path + r'\Line\Nested', 'type': 'Folder', 'name': 'Nested'}

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == 'ak.wwise.core.object.get':
            identity = args.get('from', {})
            ids, paths = identity.get('id', []), identity.get('path', [])
            descendants = args.get('transform') == [{'select': ['descendants']}]
            child_query = args.get('waql', '').startswith('from object "') and 'select children' in args['waql']
            owned_ids = {self.OWNER, self.NEW_OWNER, self.SOURCE, self.OTHER_SOURCE, self.DEEP}
            if descendants or child_query or self.owner_path in paths or any(i in owned_ids for i in ids):
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                known = [self.parent, self.bus, self.initial_bus, *([self.owner] if self.exists else []), *self.sources, *self.retired]
                if self.exists and self.owner['id'] == self.OWNER:
                    known.append(self.deep)
                if descendants:
                    selected = [r for r in known if r['path'].startswith(self.owner_path + '\\')]
                elif child_query:
                    selected = self.sources
                else:
                    selected = [r for r in known if r['id'] in ids or r['path'] in paths]
                if options.get('language'):
                    selected = [r for r in selected if r['type'] != 'AudioFileSource'
                        or r['audioSource:language']['name'] == options['language']]
                return {'return': [{k: deepcopy(v) for k, v in r.items() if k in options['return']} for r in selected]}
        if uri == 'ak.wwise.core.audio.importTabDelimited':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            with Path(args['importFile']).open(encoding='utf-8', newline='') as stream:
                row, = list(csv.DictReader(stream, delimiter='\t'))
            if args['importOperation'] == 'replaceExisting' or not self.exists:
                self.owner = {**self.owner, 'id': self.NEW_OWNER, 'activeSource': None, 'notes': ''}
                self.sources = []
                self.exists = True
                if self.fault == 'kept-descendant': self.retired.append(deepcopy(self.deep))
            for name in ('Volume', 'OverrideOutput'):
                if row.get('Property[' + name + ']') and self.fault != 'ignored-field':
                    self.owner['@' + name] = float(row['Property[' + name + ']']) if name == 'Volume' else row['Property[' + name + ']'] == 'true'
            if row.get('Reference[OutputBus]'): self.owner['@OutputBus'] = {'id': self.BUS}
            if row.get('Audio File Base64') and self.fault != 'ignored-media':
                self.copied.write_bytes(base64.b64decode(row['Audio File Base64'].partition('|')[2]))
            if self.fault == 'reset-voice': self.owner['@IsVoice'] = False
            if self.fault == 'other-language': self.other_file.write_bytes(b'undeclared Japanese change')
            if self.fault == 'extra-source':
                self.sources.append({**deepcopy(self.sources[0]), 'id': self.NEW_OWNER})
            return {'objects': deepcopy([self.owner, *([self.sources[0]] if row.get('Audio File Base64') else [])])}
        return super().call(uri, args, options)


def owner_draft(tmp_path, version, *, mode='create', existing=False):
    client = LocalizedTableClient(tmp_path, version, existing=existing)
    table = tmp_path / 'owner.tsv'
    table.write_text('Object Path\tProperty[Volume]\tProperty[OverrideOutput]\tReference[OutputBus]\n'
        '<Sound Voice>Voice\t-6\ttrue\t' + client.bus['path'] + '\n', encoding='utf-8')
    command, run = _table_lifecycle_draft(tmp_path, version, client, table, language='English(US)', mode=mode)
    return command, run, client, table


@pytest.mark.parametrize('version', VERSIONS)
def test_localized_owner_only_table_creates_voice_with_requested_fields(tmp_path, version):
    command, run, client, table = owner_draft(tmp_path, version)
    before = table.read_bytes()
    code, verified = execute_table(command, run)
    assert code == 0 and verified['verified'] is True, verified
    assert client.owner['id'] == client.NEW_OWNER and client.owner['@IsVoice'] is True
    assert client.owner['@Volume'] == -6 and client.owner['@OutputBus'] == {'id': client.BUS}
    assert client.sources == [] and table.read_bytes() == before


def inline_draft(tmp_path, version='2025.1'):
    client = LocalizedTableClient(tmp_path, version)
    table = tmp_path / 'inline.tsv'
    table.write_text('Object Path\tAudio File Base64\n<Sound Voice>Voice\tLine.wav|'
        + base64.b64encode(_tone_wav_bytes()).decode('ascii') + '\n', encoding='utf-8')
    command, run = _table_lifecycle_draft(tmp_path, version, client, table, language='English(US)')
    return command, run, client, table


@pytest.mark.parametrize('version', VERSIONS)
def test_localized_plain_owner_inline_wav_reuses_selected_source_and_preserves_other_language(tmp_path, version):
    command, run, client, table = inline_draft(tmp_path, version)
    sources, other, original = deepcopy(client.sources), client.other_file.read_bytes(), table.read_bytes()
    code, verified = execute_table(command, run)
    assert code == 0 and verified['verified'] is True, verified
    assert client.sources == sources and client.copied.read_bytes() == _tone_wav_bytes()
    assert client.other_file.read_bytes() == other and table.read_bytes() == original


@pytest.mark.parametrize('mode,existing', (('reimport', False), ('replace', False), ('replace', True)))
def test_localized_owner_only_table_lifecycle_retires_only_explicit_replacement(tmp_path, mode, existing):
    command, run, client, table = owner_draft(tmp_path, '2025.1', mode=mode, existing=existing)
    before = table.read_bytes(); other = client.other_file.read_bytes(); bus = deepcopy(client.bus)
    code, result = execute_table(command, run)
    assert code == 0 and result['verified'] is True, result
    assert client.owner['id'] == client.NEW_OWNER and client.owner['@Volume'] == -6
    assert client.sources == [] and client.other_file.read_bytes() == other and table.read_bytes() == before
    assert client.bus == bus


def test_owner_only_replacement_cannot_leave_deeper_retired_descendant(tmp_path):
    command, run, client, _ = owner_draft(tmp_path, '2025.1', mode='replace', existing=True)
    client.fault = 'kept-descendant'
    code, result = execute_table(command, run)
    assert code == 2 and result['verified'] is False, result
    assert any(not row['passed'] and 'complete old subtree' in row['name']
        for row in result['verification']['assertions'])


def preview_confirm(command, run):
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    return tx


@pytest.mark.parametrize('drift', ('metadata', 'subtree'))
def test_owner_only_create_or_replace_revalidates_metadata_and_complete_retirement_scope(tmp_path, drift):
    command, run, client, _ = owner_draft(tmp_path, '2025.1', mode='create' if drift == 'metadata' else 'replace',
        existing=drift == 'subtree')
    tx = preview_confirm(command, run)
    if drift == 'metadata': client.range_max = 100
    else: client.deep['path'] += 'Changed'
    code, result = run('execute', tx)
    assert code == 2 and result['executed'] is False and result['status'] == 'repreview_required', result
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


@pytest.mark.parametrize('mode', ('create', 'replace'))
def test_new_owner_fields_require_explicit_reference_activation_even_if_replaced_owner_satisfied_it(tmp_path, mode):
    command, _, client, table = owner_draft(tmp_path, '2025.1', mode=mode, existing=mode == 'replace')
    client.owner['@OverrideOutput'] = True
    table.write_text(table.read_text().replace('\tProperty[OverrideOutput]', '').replace('\ttrue\t', '\t'))
    command('draft-check', expected_error='TAB_REFERENCE_DEPENDENCY_REQUIRES_COLUMN')
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


@pytest.mark.parametrize('fault', ('ignored-media', 'other-language', 'extra-source'))
def test_plain_owner_inline_wav_requires_media_and_untouched_language_sources(tmp_path, fault):
    command, run, client, table = inline_draft(tmp_path)
    original = table.read_bytes(); client.fault = fault
    code, result = execute_table(command, run)
    assert code == 2 and result['verified'] is False, result
    assert table.read_bytes() == original


def test_plain_owner_inline_wav_revalidates_other_language_file_before_write(tmp_path):
    command, run, client, _ = inline_draft(tmp_path)
    tx = preview_confirm(command, run)
    client.other_file.write_bytes(b'changed after Preview')
    code, result = run('execute', tx)
    assert code == 2 and result['executed'] is False and result['status'] == 'repreview_required', result
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


def test_localized_dialogue_only_inline_table_keeps_selected_source_and_weaker_path_evidence(tmp_path):
    from tests.unit.test_import_dialogue_association_gateway import LocalizedDialogueClient, WAV_BYTES
    class DialogueInlineClient(LocalizedDialogueClient):
        def call(self, uri, args=None, options=None):
            if uri == 'ak.wwise.core.audio.importTabDelimited':
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                with Path(args['importFile']).open(encoding='utf-8', newline='') as stream:
                    row, = list(csv.DictReader(stream, delimiter='\t'))
                assert row['Dialogue Event'] == self.dialogue['path'] + '@Path:<Switch Group:Surface>Snow'
                self.copied.write_bytes(base64.b64decode(row['Audio File Base64'].partition('|')[2]))
                self.associated = True
                return {'objects': deepcopy([self.owner, self.sources[0]])}
            return super().call(uri, args, options)
    client = DialogueInlineClient(tmp_path, '2025.1')
    table = tmp_path / 'dialogue-inline.tsv'
    table.write_text('Object Path\tAudio File Base64\tDialogue Event\n<Sound Voice>Voice\tLine.wav|'
        + base64.b64encode(WAV_BYTES).decode('ascii') + '\t' + client.dialogue['path']
        + '@Path:<Switch Group:Surface>Snow\n', encoding='utf-8')
    command, run = _table_lifecycle_draft(tmp_path, '2025.1', client, table, language='English(US)')
    before, other, sources = table.read_bytes(), client.other_file.read_bytes(), deepcopy(client.sources)
    code, result = execute_table(command, run)
    assert code == 0 and result['verification']['failed_assertion_count'] == 0, result
    assert not result['verified']  # Explicit decision-path sequence is not reconstructed.
    assert client.sources == sources and client.other_file.read_bytes() == other and table.read_bytes() == before
    assert client.copied.read_bytes() == WAV_BYTES


@pytest.mark.parametrize('fault', ('ignored-field', 'reset-voice'))
def test_owner_only_new_voice_requires_requested_field_effect(tmp_path, fault):
    command, run, client, _ = owner_draft(tmp_path, '2025.1')
    client.fault = fault
    code, result = execute_table(command, run)
    assert code == 2 and not result['verified'], result
    expected = 'property Volume' if fault == 'ignored-field' else 'remains a Sound Voice'
    assert any(not row['passed'] and expected in row['name'] for row in result['verification']['assertions'])
