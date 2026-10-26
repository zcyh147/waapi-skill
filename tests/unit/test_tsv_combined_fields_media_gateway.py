"""Closed exact-table localized owner fields with planned Source media changes."""
import csv
from copy import deepcopy
from pathlib import Path
import pytest

from tests.unit.test_transaction_gateway import z_wire_path

from tests.unit.test_audio_import_business_gateway import LocalizedOwnerOnlyTabClient, _explicit_source_tab_draft
from tests.support.riff_wave import _tone_wav_bytes
from wwise_waapi.host_paths import localize_waapi_host_path


class CombinedFieldsMediaClient(LocalizedOwnerOnlyTabClient):
    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri != 'ak.wwise.core.audio.importTabDelimited':
            result = super().call(uri, args, options)
            if uri == 'ak.wwise.core.getInfo':
                result['isCommandLine'] = getattr(self, 'console_host', True)
                result['version'].update(minor=7, build=getattr(self, 'native_build', 9143))
            return result
        self.calls.append((uri, deepcopy(args), deepcopy(options)))
        with Path(args['importFile']).open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream, delimiter='\t'))
        for row in rows:
            assert row['Object Path'] in {'<Sound Voice>Voice', r'<Sound Voice>Voice\<AudioFileSource>Line'}
            if row.get('Property[Volume]'):
                self.owner['@Volume'] = float(row['Property[Volume]'])
            if row.get('Property[OverrideOutput]'):
                self.owner['@OverrideOutput'] = row['Property[OverrideOutput]'] == 'true'
            if row.get('Reference[OutputBus]'):
                assert row['Reference[OutputBus]'] == self.bus['path']
                self.owner['@OutputBus'] = {'id': self.BUS}
            if row.get('Audio File'):
                if getattr(self, 'fault', None) != 'ignored-media':
                    self.copied.write_bytes(Path(localize_waapi_host_path(row['Audio File'])).read_bytes())
                # Retained r1: existing bytes changed, both old GUIDs remained,
                # and native returned an extra selected-language Source.
                if len({source['audioSource:language']['name'] for source in self.sources
                        if source['path'] == self.sources[0]['path']}) > 1:
                    extra = deepcopy(self.sources[0])
                    extra['id'] = '{68892A05-8E58-4976-9AE2-144BBA01774E}'
                    self.sources.append(extra)
        if getattr(self, 'fault', None) == 'changed-other-language':
            self.other_file.write_bytes(b'unplanned Japanese change')
        return {'objects': deepcopy([self.owner, *([self.sources[0]] if any(row.get('Audio File') for row in rows) else [])])}


def _draft(tmp_path, *, shared_path=False, native_build=9143, console_host=True):
    client = CombinedFieldsMediaClient(tmp_path, '2025.1')
    client.native_build, client.console_host = native_build, console_host
    command, run, client, table = _explicit_source_tab_draft(tmp_path, '2025.1', client=client, unique_source_path=not shared_path)
    media = tmp_path / 'Line.wav'
    media.write_bytes(_tone_wav_bytes())
    native_media = z_wire_path(media)
    table.write_text('Object Path\tAudio File\tProperty[Volume]\tProperty[OverrideOutput]\tReference[OutputBus]\n'
                     '<Sound Voice>Voice\t' + native_media + '\t-6\ttrue\t' + client.bus['path'] + '\n', encoding='utf-8')
    return command, run, client, table


def test_combined_duplicate_source_path_is_refused_before_preview_on_observed_console(tmp_path):
    command, _, client, table = _draft(tmp_path, shared_path=True)
    original = table.read_bytes(); before = deepcopy(client.sources)
    command('draft-check', expected_error='TSV_COMBINED_SOURCE_IDENTITY_UNSAFE_ON_HOST')
    assert client.sources == before and table.read_bytes() == original
    assert client.copied.read_bytes() == b'old English media'
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)
    assert not list((tmp_path / 'state/transactions').glob('tx1-*'))


def test_extra_source_counterexample_does_not_verify_partial_success_on_unobserved_fake_host(tmp_path):
    # This external fault models the retained Source outcome, not evidence of
    # the unobserved build. The new boundary must not become a global ban.
    command, run, client, table = _draft(tmp_path, shared_path=True, native_build=9142)
    before = deepcopy(client.sources)
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert run('execute', tx)[0] == 0
    code, result = run('verify', tx)
    assert code == 2 and result['verified'] is False, result
    assert client.owner['@Volume'] == -6 and client.owner['@OverrideOutput'] is True
    assert client.owner['@OutputBus'] == {'id': client.BUS}
    assert client.copied.read_bytes() == _tone_wav_bytes()
    assert client.sources[:2] == before and len(client.sources) == 3
    assert client.sources[2]['path'] == before[0]['path'] and client.sources[2]['audioSource:language'] == before[0]['audioSource:language']
    assert client.other_file.read_bytes() == b'keep Japanese media'


def test_combined_historical_preview_stops_when_current_host_matches_unsafe_console(tmp_path):
    command, run, client, table = _draft(tmp_path, shared_path=True, native_build=9142)
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    client.native_build = 9143
    code, result = run('execute', tx)
    assert code == 2 and result['executed'] is False and result['status'] == 'repreview_required', result
    assert result['error_code'] == 'TSV_COMBINED_SOURCE_IDENTITY_UNSAFE_ON_HOST'
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


def test_combined_shared_path_authoring_preview_is_outside_observed_console_boundary(tmp_path):
    command, _, client, _ = _draft(tmp_path, shared_path=True, console_host=False)
    command('draft-check'); command('preview-from-draft')
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


def test_combined_safe_preview_stops_if_a_cross_language_source_path_later_collides(tmp_path):
    command, run, client, _ = _draft(tmp_path)
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    client.sources[1].update(name='Line', path=client.sources[0]['path'])
    code, result = run('execute', tx)
    assert code == 2 and result['executed'] is False and result['status'] == 'repreview_required', result
    assert client.copied.read_bytes() == b'old English media' and client.owner['@Volume'] == 0
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


def test_shared_path_pure_media_preview_is_outside_combined_host_boundary(tmp_path):
    command, _, client, table = _draft(tmp_path, shared_path=True)
    table.write_text('Object Path\tAudio File\n<Sound Voice>Voice\t' + z_wire_path(tmp_path / 'Line.wav') + '\n', encoding='utf-8')
    command('draft-check'); command('preview-from-draft')
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


def test_shared_path_owner_only_fields_remain_supported_on_observed_console(tmp_path):
    command, run, client, table = _draft(tmp_path, shared_path=True)
    table.write_text('Object Path\tProperty[Volume]\tProperty[OverrideOutput]\tReference[OutputBus]\n'
        '<Sound Voice>Voice\t-6\ttrue\t' + client.bus['path'] + '\n', encoding='utf-8')
    before = deepcopy(client.sources); media = client.copied.read_bytes(), client.other_file.read_bytes()
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert run('execute', tx)[0] == 0
    code, result = run('verify', tx); assert code == 0 and result['verified'] is True, result
    assert client.owner['@Volume'] == -6 and client.owner['@OutputBus'] == {'id': client.BUS}
    assert client.sources == before and (client.copied.read_bytes(), client.other_file.read_bytes()) == media


def test_exact_table_localized_media_and_owner_fields_verify_independent_effects(tmp_path):
    command, run, client, table = _draft(tmp_path)
    original = table.read_bytes()
    before_sources = deepcopy(client.sources)
    other_bytes = client.other_file.read_bytes()
    old_media = client.copied.read_bytes()
    assert client.owner['@OutputBus']['id'] == client.INITIAL_BUS != client.BUS
    command('draft-check')
    tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    prepared = shown['artifact']['prepared_operation']
    assert prepared['dispatch']['args']['importFile'] == str(table.resolve())
    assert 'imports' not in prepared['dispatch']['args']
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, executed = run('execute', tx); assert code == 0, executed
    code, verified = run('verify', tx); assert code == 0 and verified['verified'] is True, verified
    assert client.owner['@Volume'] == -6 and client.owner['@OverrideOutput'] is True
    assert client.owner['@OutputBus'] == {'id': client.BUS}
    assert client.owner['notes'] == 'keep owner notes' and client.sources == before_sources
    assert client.copied.read_bytes() == _tone_wav_bytes() != old_media
    assert client.other_file.read_bytes() == other_bytes and table.read_bytes() == original
    assert len([u for u, _, _ in client.calls if u == 'ak.wwise.core.audio.importTabDelimited']) == 1


def test_exact_table_owner_fields_and_same_owner_source_media_share_planned_change(tmp_path):
    command, run, client, table = _draft(tmp_path)
    table.write_text('Object Path\tAudio File\tProperty[Volume]\tProperty[OverrideOutput]\tReference[OutputBus]\n'
                     '<Sound Voice>Voice\t\t-6\ttrue\t' + client.bus['path'] + '\n'
                     '<Sound Voice>Voice\\<AudioFileSource>Line\t' + z_wire_path(tmp_path / 'Line.wav') + '\t\t\t\n', encoding='utf-8')
    original, other = table.read_bytes(), client.other_file.read_bytes()
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert run('execute', tx)[0] == 0
    code, result = run('verify', tx); assert code == 0 and result['verified'] is True, result
    assert client.owner['@Volume'] == -6 and client.owner['@OutputBus'] == {'id': client.BUS}
    assert client.copied.read_bytes() == _tone_wav_bytes() and client.other_file.read_bytes() == other
    assert table.read_bytes() == original


def test_combined_table_rejects_wrong_source_ownership_before_preview(tmp_path):
    command, _, client, table = _draft(tmp_path)
    client.sources[0]['parent'] = {'id': client.BUS}
    original = table.read_bytes()
    command('draft-check', expected_error='INVALID_READBACK')
    assert table.read_bytes() == original
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


@pytest.mark.parametrize('drift', ('metadata', 'input'))
def test_combined_table_sealed_metadata_and_input_drift_block_write(tmp_path, drift):
    command, run, client, table = _draft(tmp_path)
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    if drift == 'metadata':
        client.range_max = 100
    else:
        (tmp_path / 'Line.wav').write_bytes(b'changed input')
    code, result = run('execute', tx)
    assert code == 2 and result['executed'] is False and result['status'] == 'repreview_required', result
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


@pytest.mark.parametrize('fault', ('ignored-media', 'changed-other-language'))
def test_combined_table_requires_planned_media_and_untouched_language_files(tmp_path, fault):
    command, run, client, table = _draft(tmp_path)
    client.fault = fault
    original = table.read_bytes()
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert run('execute', tx)[0] == 0
    code, result = run('verify', tx)
    assert code == 2 and result['verified'] is False, result
    assert client.owner['@Volume'] == -6 and client.owner['@OutputBus'] == {'id': client.BUS}
    assert table.read_bytes() == original
