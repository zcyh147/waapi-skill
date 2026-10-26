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


def _draft(tmp_path, version='2025.1', *, client=None):
    client = client or TabSwitchClient(tmp_path, version)
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
    code, executed = run('execute', tx); assert code == 0, executed
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


class GroupOnlyTabClient(TabSwitchClient):
    def __init__(self, tmp_path, version):
        super().__init__(tmp_path, version)
        self.parent['classId'] = 1

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        row = {'id': '{CCCCCCCC-1111-1111-1111-111111111111}', 'name': 'Default Work Unit',
               'type': 'WorkUnit', 'path': self.parent['path'].rpartition('\\')[0]}
        if uri == 'ak.wwise.core.object.get' and (row['path'] in args.get('from', {}).get('path', [])
                or row['id'] in args.get('from', {}).get('id', [])):
            result = super().call(uri, args, options)
            result['return'].append({k: deepcopy(row[k]) for k in options['return'] if k in row})
            return result
        if uri == 'ak.wwise.core.audio.importTabDelimited':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args['importOperation'] == 'useExisting'
            table = Path(args['importFile']).read_text(encoding='utf-8')
            assert table == 'Object Path\tObject Type\tSwitch Assignation\n' + self.parent['path'] + '\tSwitch Container\t<Switch Group:Surface>\n'
            self.parent['SwitchGroupOrStateGroup'] = {'id': self.GROUP}
            return {'objects': deepcopy([self.parent])}
        return super().call(uri, args, options)


def _group_only_draft(tmp_path, version='2025.1', *, client=None):
    # Reuse the public exact-table Draft protocol; only the immutable input
    # artifact and external native behavior differ from repeated-value import.
    client = client or GroupOnlyTabClient(tmp_path, version)
    command, run, client, table = _draft(tmp_path, version, client=client)
    table.write_text('Object Path\tObject Type\tSwitch Assignation\n' + client.parent['path']
                     + '\tSwitch Container\t<Switch Group:Surface>\n', encoding='utf-8')
    return command, run, client, table


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'))
def test_group_only_table_binds_existing_group_without_creating_value_or_assignment(tmp_path, version):
    command, run, client, table = _group_only_draft(tmp_path, version)
    before_pairs = deepcopy(client.assignments); original = table.read_bytes()
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    binding = shown['artifact']['prepared_operation']['verification_plan']['targets'][0]['switch_assignment_binding']
    assert binding['value_ids'] == [] and binding['group_id'] == client.GROUP
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, executed = run('execute', tx); assert code == 0, json.dumps(executed, indent=2)
    code, verified = run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified
    assert client.assignments == before_pairs and table.read_bytes() == original
    assert len([u for u, _, _ in client.calls if u == 'ak.wwise.core.audio.importTabDelimited']) == 1
    assert not any(u.endswith('.setReference') or u.endswith('.addAssignment') for u, _, _ in client.calls)


def test_group_only_table_associates_exact_existing_group_with_empty_unbound_container(tmp_path):
    command, run, client, table = _group_only_draft(tmp_path)
    client.parent['SwitchGroupOrStateGroup'] = None
    client.assignments = []
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    binding = shown['artifact']['prepared_operation']['verification_plan']['targets'][0]['switch_assignment_binding']
    assert binding['before_group_id'] is None and binding['value_ids'] == []
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, executed = run('execute', tx); assert code == 0, executed
    code, verified = run('verify', tx); assert code == 0 and verified['verified'] is True, verified
    assert client.parent['SwitchGroupOrStateGroup'] == {'id': client.GROUP}
    assert client.assignments == []


def test_group_only_table_never_claims_to_create_absent_group(tmp_path):
    command, _, client, _ = _group_only_draft(tmp_path)
    client.group['path'] = r'\Switches\Default Work Unit\Other'
    client.parent['SwitchGroupOrStateGroup'] = None
    client.assignments = []
    command('draft-check', expected_error='AMBIGUOUS_IDENTITY')
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


class PlannedSwitchTabClient(TabSwitchClient):
    CONTAINER = '{CCCCCCCC-2222-2222-2222-222222222222}'

    def __init__(self, tmp_path, version):
        super().__init__(tmp_path, version)
        self.planned_container = {'id': self.CONTAINER, 'name': 'Cases', 'type': 'SwitchContainer', 'classId': 1,
            'path': self.parent['path'] + r'\Cases', 'parent': {'id': PARENT_ID},
            'SwitchGroupOrStateGroup': {'id': self.GROUP}}
        self.child.update(path=self.planned_container['path'] + r'\SnowSounds', parent={'id': self.CONTAINER})
        self.source['path'] = self.child['path'] + r'\Snow'
        self.planned_pairs = []
        self.assignment_effect = True
        self.group_only = False
        self.container_visible = False
        self.return_container = True
        self.other_group = {'id': '{CCCCCCCC-3333-3333-3333-333333333333}', 'name': 'Other',
            'type': 'SwitchGroup', 'path': r'\Switches\Default Work Unit\Other'}

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == 'ak.wwise.core.object.get' and self.other_group['path'] in args.get('from', {}).get('path', []):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [{k: deepcopy(self.other_group[k]) for k in options['return'] if k in self.other_group}]}
        if uri == 'ak.wwise.core.switchContainer.getAssignments' and args['id'] == self.CONTAINER:
            assert self.created, 'A planned container cannot be read before the single import'
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': deepcopy(self.planned_pairs)}
        if uri == 'ak.wwise.core.object.get' and (self.created or self.container_visible):
            identity = args.get('from', {})
            if self.CONTAINER in identity.get('id', []) or self.planned_container['path'] in identity.get('path', []):
                result = super().call(uri, args, options)
                result['return'].append({k: deepcopy(self.planned_container[k]) for k in options['return'] if k in self.planned_container})
                return result
        if uri == 'ak.wwise.core.audio.importTabDelimited':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            with Path(args['importFile']).open(encoding='utf-8', newline='') as stream:
                rows = list(csv.reader(stream, delimiter='\t'))
            if self.group_only:
                assert rows[1] == [r'<Switch Container>Cases', 'Switch Container', '<Switch Group:Surface>']
                self.created = True
                return {'objects': deepcopy([self.planned_container])}
            assert rows[1][0] == r'<Switch Container>Cases\<Sound SFX>SnowSounds'
            assert rows[1][2] == '<Switch Group:Surface>Snow'
            self.created = True
            if self.assignment_effect:
                self.planned_pairs = [{'child': self.CHILD, 'stateOrSwitch': self.VALUE}]
            destination = Path(self.source['originalFilePath'])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(Path(localize_waapi_host_path(rows[1][1])).read_bytes())
            return {'objects': deepcopy([*([self.planned_container] if self.return_container else []), self.child, self.source])}
        return super().call(uri, args, options)


def _planned_container_draft(tmp_path, version='2025.1', *, group_only=False):
    client = PlannedSwitchTabClient(tmp_path, version)
    command, run, client, table = _draft(tmp_path, version, client=client)
    table.write_text('Object Path\tAudio File\tSwitch Assignation\n'
                     + r'<Switch Container>Cases\<Sound SFX>SnowSounds' + '\t' + z_wire_path(tmp_path / 'Snow.wav')
                     + '\t<Switch Group:Surface>Snow\n', encoding='utf-8')
    if group_only:
        client.group_only = True
        table.write_text('Object Path\tObject Type\tSwitch Assignation\n'
                         + '<Switch Container>Cases\tSwitch Container\t<Switch Group:Surface>\n', encoding='utf-8')
    return command, run, client, table


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'))
def test_typed_table_creates_container_and_binds_its_direct_child_in_one_import(tmp_path, version):
    command, run, client, table = _planned_container_draft(tmp_path, version)
    before_existing = deepcopy(client.assignments); original = table.read_bytes()
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    binding = shown['artifact']['prepared_operation']['verification_plan']['targets'][0]['switch_assignment_binding']
    assert binding['container_id'] is None and binding['container_path'] == client.planned_container['path']
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, executed = run('execute', tx); assert code == 0, json.dumps(executed, indent=2)
    code, verified = run('verify', tx); assert code == 0 and verified['verified'] is True, json.dumps(verified, indent=2)
    assert client.planned_pairs == [{'child': client.CHILD, 'stateOrSwitch': client.VALUE}]
    assert client.assignments == before_existing and table.read_bytes() == original
    assert Path(client.source['originalFilePath']).read_bytes() == WAV_BYTES
    assert len([u for u, _, _ in client.calls if u == 'ak.wwise.core.audio.importTabDelimited']) == 1


def test_group_only_table_creates_typed_container_using_an_existing_group(tmp_path):
    command, run, client, table = _planned_container_draft(tmp_path, group_only=True)
    original = table.read_bytes()
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    binding = shown['artifact']['prepared_operation']['verification_plan']['targets'][0]['switch_assignment_binding']
    assert binding['container_id'] is None and binding['value_ids'] == []
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    code, executed = run('execute', tx); assert code == 0, executed
    code, verified = run('verify', tx); assert code == 0 and verified['verified'] is True, verified
    assert client.planned_pairs == [] and table.read_bytes() == original


def test_planned_switch_container_absence_drift_blocks_import(tmp_path):
    command, run, client, _ = _planned_container_draft(tmp_path)
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    client.container_visible = True
    code, result = run('execute', tx)
    assert code == 2 and result['executed'] is False and result['status'] == 'repreview_required', result
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


def test_planned_switch_media_success_cannot_hide_missing_assignment(tmp_path):
    command, run, client, _ = _planned_container_draft(tmp_path)
    client.assignment_effect = False
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert run('execute', tx)[0] == 0
    code, result = run('verify', tx)
    assert code == 2 and result['verified'] is False, result
    assert Path(client.source['originalFilePath']).read_bytes() == WAV_BYTES
    assert any(not row['passed'] and 'Switch assignment effect' in row['name']
               for row in result['verification']['assertions'])


def test_group_only_table_retains_prepreview_unbound_group_guard(tmp_path):
    command, run, client, _ = _group_only_draft(tmp_path)
    client.parent['SwitchGroupOrStateGroup'] = None; client.assignments = []
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    client.parent['SwitchGroupOrStateGroup'] = {'id': client.GROUP}
    code, result = run('execute', tx)
    assert code == 2 and result['executed'] is False and result['status'] == 'repreview_required', result
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


def test_group_only_table_does_not_silently_discard_occupied_group_assignments(tmp_path):
    command, _, client, _ = _group_only_draft(tmp_path)
    client.group['id'] = '{CCCCCCCC-3333-3333-3333-333333333333}'
    command('draft-check', expected_error='IMPORT_SWITCH_GROUP_CHANGE_WITH_ASSIGNMENTS_UNSUPPORTED')
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


def test_planned_switch_rows_cannot_assign_conflicting_groups_to_one_container(tmp_path):
    command, _, client, table = _planned_container_draft(tmp_path, group_only=True)
    table.write_text(table.read_text() + r'<Switch Container>Cases\<Sound SFX>OtherSound'
                     + '\tSound SFX\t<Switch Group:Other>\n', encoding='utf-8')
    command('draft-check', expected_error='IMPORT_SWITCH_GROUP_MISMATCH')
    assert not any(u == 'ak.wwise.core.audio.importTabDelimited' for u, _, _ in client.calls)


def test_planned_container_is_read_back_even_when_import_result_omits_ancestor(tmp_path):
    command, run, client, _ = _planned_container_draft(tmp_path)
    client.return_container = False
    command('draft-check'); tx = command('preview-from-draft')['transaction_id']
    code, shown = run('transaction-show', tx); assert code == 0, shown
    assert run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])[0] == 0
    assert run('execute', tx)[0] == 0
    code, verified = run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified
    assert client.planned_pairs == [{'child': client.CHILD, 'stateOrSwitch': client.VALUE}]
