"""Exact-table repeated Switch columns bind and prove every requested pair."""
import csv
import json
from copy import deepcopy
from pathlib import Path
import pytest

from tests.unit.test_import_switch_assignment_gateway import SwitchImportClient, WAV_BYTES
from tests.unit.test_audio_import_business_gateway import PARENT_ID, waapi_gateway, _env
from tests.support.gateway_config import set_gateway_config
from tests.unit.test_transaction_gateway import z_wire_path
from wwise_waapi.host_paths import localize_waapi_host_path


class TabSwitchClient(SwitchImportClient):
    SECOND_VALUE = '{77777777-7777-7777-7777-777777777777}'

    def __init__(self, tmp_path, version):
        super().__init__(tmp_path, media=True, version=version)
        self.second = {**deepcopy(self.value), 'id': self.SECOND_VALUE, 'name': 'Rain',
                       'path': self.group['path'] + r'\Rain'}
        self.effect_count = 2

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == 'ak.wwise.core.object.get':
            if self.GROUP in args.get('waql', '') and 'Rain' in args['waql']:
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {'return': [{k: deepcopy(self.second[k]) for k in options['return'] if k in self.second}]
                        if self.second['name'] == 'Rain' else []}
            if self.SECOND_VALUE in args.get('from', {}).get('id', []):
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                rows = [self.parent, self.group, self.value, self.second]
                return {'return': [{k: deepcopy(r[k]) for k in options['return'] if k in r}
                                   for r in rows if r['id'] in args['from']['id']]}
        if uri == 'ak.wwise.core.audio.importTabDelimited':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args['importOperation'] == 'useExisting'
            assert 'imports' not in args
            with Path(args['importFile']).open(encoding='utf-8', newline='') as stream:
                rows = list(csv.reader(stream, delimiter='\t'))
            assert rows[0] == ['Object Path', 'Audio File', 'Switch Assignation', 'Switch Assignation']
            assert rows[1][0] == '<Sound SFX>SnowSounds'
            assert rows[1][2:] == ['<Switch Group:Surface>Snow', '<Switch Group:Surface>Rain']
            destination = Path(self.source['originalFilePath'])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(Path(localize_waapi_host_path(rows[1][1])).read_bytes())
            self.created = True
            for value in [self.VALUE, self.SECOND_VALUE][:self.effect_count]:
                self.assignments.append({'child': self.CHILD, 'stateOrSwitch': value})
            return {'objects': deepcopy([self.child, self.source])}
        return super().call(uri, args, options)


def _draft(tmp_path, version='2025.1'):
    client = TabSwitchClient(tmp_path, version)
    media = tmp_path / 'Snow.wav'; media.write_bytes(WAV_BYTES)
    table = tmp_path / 'switch.tsv'
    table.write_text('Object Path\tAudio File\tSwitch Assignation\tSwitch Assignation\n'
                     '<Sound SFX>SnowSounds\t' + z_wire_path(media)
                     + '\t<Switch Group:Surface>Snow\t<Switch Group:Surface>Rain\n', encoding='utf-8')
    env = set_gateway_config(_env(tmp_path), wwise_version=version)
    def run(*argv):
        return waapi_gateway.execute_gateway(['--state-dir', str(tmp_path / 'state'), *argv],
            env=env, client_factory=lambda _url: client)
    code, started = run('draft-start', 'audio.importTabDelimited'); assert code == 0, started
    draft, authority, revision = started['draft']['draft_id'], started['task_authority'], 1
    def command(name, *argv, expected_error=None):
        nonlocal revision
        code, result = run(name, draft, '--task-authority', authority, '--expected-revision', str(revision), *argv)
        assert code == (2 if expected_error else 0), json.dumps(result, indent=2)
        if expected_error: assert result['error_code'] == expected_error, result
        if 'draft' in result: revision = result['draft']['revision']
        return result
    bound = command('draft-bind-object', '--role', 'import_location', '--object-id', PARENT_ID)
    command('draft-declare-artifact-plan', '--table-file', str(table), '--location-handle',
            bound['bound_object']['handle'], '--language', 'SFX', '--mode', 'reimport')
    return command, run, client, table


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'))
def test_exact_table_two_switch_values_prove_media_owner_and_preserved_pairs(tmp_path, version):
    command, run, client, table = _draft(tmp_path, version)
    original = table.read_bytes(); before = deepcopy(client.assignments)
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    prepared = shown['artifact']['prepared_operation']
    assert prepared['verification_plan']['native_directive_boundaries'] == []
    binding = prepared['verification_plan']['targets'][0]['switch_assignment_binding']
    assert binding['value_ids'] == [client.VALUE, client.SECOND_VALUE]
    assert prepared['dispatch']['args']['importFile'] == str(table.resolve())
    assert 'imports' not in prepared['dispatch']['args']
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert run('execute', tx)[0] == 0
    code, verified = run('verify', tx); assert code == 0 and verified['verified'] is True, verified
    assert client.assignments == [*before, {'child': client.CHILD, 'stateOrSwitch': client.VALUE},
                                  {'child': client.CHILD, 'stateOrSwitch': client.SECOND_VALUE}]
    assert Path(client.source['originalFilePath']).read_bytes() == WAV_BYTES
    assert table.read_bytes() == original
    assert len([u for u, _, _ in client.calls if u == 'ak.wwise.core.audio.importTabDelimited']) == 1
    assert not any(u.endswith('.addAssignment') or u.endswith('.setReference') for u, _, _ in client.calls)


@pytest.mark.parametrize('fault,error', (
    ('group', 'IMPORT_SWITCH_GROUP_MISMATCH'),
    ('value-parent', 'IDENTITY_MISMATCH'),
    ('missing-value', 'AMBIGUOUS_IDENTITY'),
))
def test_exact_table_rejects_unbound_switch_column_before_preview(tmp_path, fault, error):
    command, _, client, table = _draft(tmp_path)
    if fault == 'group':
        table.write_text(table.read_text().replace('<Switch Group:Surface>Rain', '<Switch Group:Other>Rain'))
    elif fault == 'value-parent':
        client.second['parent'] = {'id': client.OTHER_VALUE}
    else:
        client.second['name'] = 'Absent'
    original = table.read_bytes()
    command('draft-check', expected_error=error)
    assert table.read_bytes() == original and not client.created
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)
    assert not list((tmp_path / 'state/transactions').glob('tx1-*'))


def test_exact_table_media_success_cannot_hide_missing_second_assignment(tmp_path):
    command, run, client, table = _draft(tmp_path)
    client.effect_count = 1
    original = table.read_bytes(); before = deepcopy(client.assignments)
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert run('execute', tx)[0] == 0
    code, verified = run('verify', tx)
    assert code == 2 and verified['verified'] is False, verified
    assert any(not row['passed'] and 'Switch assignment effect' in row['name']
               for row in verified['verification']['assertions'])
    assert client.assignments == [*before, {'child': client.CHILD, 'stateOrSwitch': client.VALUE}]
    assert Path(client.source['originalFilePath']).read_bytes() == WAV_BYTES
    assert table.read_bytes() == original


@pytest.mark.parametrize('drift', ('value', 'assignments', 'table'))
def test_exact_table_switch_binding_drift_blocks_import(tmp_path, drift):
    command, run, client, table = _draft(tmp_path)
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    if drift == 'value':
        client.second['parent'] = {'id': client.OTHER_VALUE}
    elif drift == 'assignments':
        client.assignments.clear()
    else:
        table.write_text(table.read_text().replace('>Rain', '>Snow'))
    code, result = run('execute', tx)
    assert code == 2 and result['executed'] is False and result['status'] == 'repreview_required', result
    assert not client.created
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)
