"""Closed Console project alternatives through the real public Draft chain.

Pinned schemas establish construction; injected clients do not establish native
project effects or permit any native process launch.
"""
from copy import deepcopy
import json
from xml.etree import ElementTree as ET

import pytest

from tests.unit.test_field_interface_closure_gateway import FieldTask


VERSIONS = ('2023.1', '2024.1', '2025.1')
CREATE = 'ak.wwise.console.project.create'


class ConsoleProjectTask(FieldTask):
    def __init__(self, path, version):
        self.created_file = path / 'Created' / 'Created.wproj'
        self.created_file.parent.mkdir()
        super().__init__(path, version, CREATE)

    def call(self, uri, args=None, options=None):
        if uri.endswith('object.get') and args.get('waql') == 'from type Project take 2':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [{'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': self.project_file.stem,
                'type': 'Project', 'path': '\\', 'filePath': str(self.project_file)}]}
        if uri == CREATE:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            self.write_created_project(args)
            self.project_file = self.created_file
            return {}
        return super().call(uri, args, options)


    def write_created_project(self, args):
        document = ET.Element('WwiseDocument', Type='Project',
            SchemaVersion={'2023.1': '119', '2024.1': '123', '2025.1': '133'}[self.version],
            WwiseVersion='v' + self.version + '.0', WwiseBuild='1')
        project = ET.SubElement(ET.SubElement(document, 'ProjectInfo'), 'Project',
            Name='Created', ID='{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}')
        platforms = ET.SubElement(project, 'Platforms')
        rows = args.get('platforms', {'basePlatform': 'Windows'})
        if isinstance(rows, dict):
            rows = [rows]
        for index, row in enumerate(rows):
            ET.SubElement(platforms, 'Platform', Name=row.get('name', row['basePlatform']),
                ReferencePlatform=row['basePlatform'], ID=f'{{CCCCCCCC-CCCC-CCCC-CCCC-{index + 1:012X}}}')
        languages = ET.SubElement(project, 'LanguageList')
        names = args.get('languages', ['English(US)'])
        for index, name in enumerate(['SFX', *names]):
            ET.SubElement(languages, 'Language', Name=name,
                ID=f'{{DDDDDDDD-DDDD-DDDD-DDDD-{index + 1:012X}}}')
        ET.SubElement(ET.SubElement(project, 'PropertyList'), 'Property', Name='DefaultLanguage',
            Type='string', Value=names[0] if names else 'English(US)')
        self.created_file.write_bytes(ET.tostring(document, encoding='utf-8'))


class NewDirectoryProjectTask(ConsoleProjectTask):
    def write_created_project(self, args):
        self.created_file.parent.mkdir(parents=True)
        super().write_created_project(args)


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('nested', [False, True])
def test_console_create_allows_native_creation_of_missing_project_directories(tmp_path, version, nested):
    task = NewDirectoryProjectTask(tmp_path, version)
    missing = tmp_path / 'Missing 项目'
    task.created_file = (missing / 'Nested' if nested else missing) / 'Created.wproj'
    code, payload = task.step('draft-declare-cli-console-plan',
        '--value', 'project_file', str(task.created_file))
    assert code == 0, payload
    code, payload = task.step('draft-check')
    assert code == 0, payload
    code, payload = task.step('preview-from-draft')
    assert code == 0, payload
    tx = payload['transaction_id']
    assert not missing.exists()
    assert not any(uri == CREATE for uri, _, _ in task.calls)
    code, payload = task.run('transaction-show', tx)
    assert code == 0, payload
    code, payload = task.run('confirm', tx, '--confirmation-token', payload['confirmation']['token'])
    assert code == 0, payload
    code, payload = task.run('execute', tx)
    assert code == 0, payload
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is True, payload
    assert task.created_file.is_file()
    assert len([row for row in task.calls if row[0] == CREATE]) == 1


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('drift', ['ancestor-replaced', 'directory-appears', 'directory-is-file'])
def test_console_create_missing_directory_boundary_cannot_drift_before_write(tmp_path, version, drift):
    task = NewDirectoryProjectTask(tmp_path, version)
    ancestor = tmp_path / 'Destination'
    ancestor.mkdir()
    task.created_file = ancestor / 'Missing' / 'Created.wproj'
    def change_destination():
        if drift == 'ancestor-replaced':
            ancestor.rename(tmp_path / 'Retained-destination')
            ancestor.mkdir()
        elif drift == 'directory-appears':
            task.created_file.parent.mkdir()
        else:
            task.created_file.parent.write_text('unrelated user file')
    _, code, payload = execute_console_creation(task, before_execute=change_destination)
    assert code != 0, payload
    assert not any(row[0] == CREATE for row in task.calls)
    if drift == 'directory-is-file':
        assert task.created_file.parent.read_text() == 'unrelated user file'


def test_console_create_missing_directory_symlink_redirect_is_rejected(tmp_path):
    import os
    if os.name == 'nt':
        pytest.skip('POSIX symlink control; native Windows reparse behavior requires its own host evidence')
    task = NewDirectoryProjectTask(tmp_path, '2025.1')
    ancestor = tmp_path / 'Destination'
    ancestor.mkdir()
    task.created_file = ancestor / 'Missing' / 'Created.wproj'
    unrelated = tmp_path / 'Unrelated'
    unrelated.mkdir()
    marker = unrelated / 'keep.txt'
    marker.write_text('keep')
    _, code, payload = execute_console_creation(task,
        before_execute=lambda: task.created_file.parent.symlink_to(unrelated, target_is_directory=True))
    assert code != 0, payload
    assert not any(row[0] == CREATE for row in task.calls)
    assert list(unrelated.iterdir()) == [marker] and marker.read_text() == 'keep'


def test_console_create_without_native_output_directory_cannot_verify_or_retry(tmp_path):
    class MissingOutputTask(ConsoleProjectTask):
        def write_created_project(self, args):
            pass
    task = MissingOutputTask(tmp_path, '2025.1')
    task.created_file = tmp_path / 'Missing' / 'Created.wproj'
    tx, code, payload = execute_console_creation(task)
    assert code == 0, payload
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'verification_failed', payload
    assert not task.created_file.parent.exists()
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == CREATE]) == 1


def test_console_create_unreadable_new_directory_remains_unknown(tmp_path, monkeypatch):
    from pathlib import Path
    task = NewDirectoryProjectTask(tmp_path, '2025.1')
    task.created_file = tmp_path / 'Missing' / 'Created.wproj'
    tx, code, payload = execute_console_creation(task)
    assert code == 0, payload
    original_lstat = Path.lstat
    def unreadable(path, *args, **kwargs):
        if path == task.created_file.parent:
            raise PermissionError('Directory metadata is unavailable')
        return original_lstat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', unreadable)
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'executed_unverified', payload
    assert payload['error_code'] == 'INVALID_IO_ROOT', payload
    assert len([row for row in task.calls if row[0] == CREATE]) == 1


def test_console_create_discloses_and_enforces_missing_directory_budget(tmp_path):
    task = NewDirectoryProjectTask(tmp_path, '2025.1')
    code, schema = task.run('--version', '2025.1', 'request-schema', CREATE)
    assert code == 0, schema
    assert schema['business_adapter']['effect_verification']['limits']['missing_project_directories'] == 64
    task.created_file = tmp_path.joinpath(*[f'level_{i}' for i in range(65)], 'Created.wproj')
    code, payload = task.step('draft-declare-cli-console-plan',
        '--value', 'project_file', str(task.created_file))
    assert code == 0, payload
    code, payload = task.step('draft-check')
    assert code != 0 and payload['error_code'] == 'LIMIT_EXCEEDED', payload
    assert not any(uri == CREATE for uri, _, _ in task.calls)
    assert not (tmp_path / 'level_0').exists()


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('shape', ['unnamed', 'same-base-named', 'omitted', 'empty', 'named-first', 'unnamed-first'])
def test_console_create_preserves_optional_platform_names_and_same_base_rows(tmp_path, version, shape):
    task = ConsoleProjectTask(tmp_path, version)
    argv = ['--value', 'project_file', str(task.created_file)]
    if shape == 'unnamed':
        argv += ['--item', 'platforms', 'Windows']
        expected = {'basePlatform': 'Windows'}
    elif shape == 'same-base-named':
        argv += ['--mapping', 'platforms', 'Windows', 'Windows_Studio',
                 '--mapping', 'platforms', 'Windows', 'Windows_Release']
        expected = [{'basePlatform': 'Windows', 'name': 'Windows_Studio'},
                    {'basePlatform': 'Windows', 'name': 'Windows_Release'}]
    elif shape == 'named-first':
        argv += ['--mapping', 'platforms', 'Windows', 'Studio', '--item', 'platforms', 'Android']
        expected = [{'basePlatform': 'Windows', 'name': 'Studio'}, {'basePlatform': 'Android'}]
    elif shape == 'unnamed-first':
        argv += ['--item', 'platforms', 'Android', '--mapping', 'platforms', 'Windows', 'Studio']
        expected = [{'basePlatform': 'Android'}, {'basePlatform': 'Windows', 'name': 'Studio'}]
    elif shape == 'empty':
        argv += ['--empty', 'platforms', '--empty', 'languages']
        expected = []
    code, declared = task.step('draft-declare-cli-console-plan', *argv)
    assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 0, json.dumps(checked)
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    assert not any(uri == CREATE for uri, _, _ in task.calls)
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    writes = [args for uri, args, _ in task.calls if uri == CREATE]
    assert writes == [{'path': str(task.created_file), **({'platforms': expected} if shape != 'omitted' else {}),
                      **({'languages': []} if shape == 'empty' else {})}]
    code, verified = task.run('verify', tx)
    assert code == 0, json.dumps(verified)
    assert verified['verified'] is (shape != 'empty'), verified
    if shape == 'empty':
        assert verified['state'] == 'result_schema_checked', verified
    assert len([row for row in task.calls if row[0] == CREATE]) == 1


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('extra', [
    ['--empty', 'platforms', '--item', 'platforms', 'Windows'],
    ['--empty', 'languages', '--item', 'languages', 'French'],
    ['--empty', 'project_file'],
    ['--empty', 'platforms', '--empty', 'platforms'],
    ['--item', 'not_a_field', 'Windows'],
])
def test_console_create_rejects_conflicting_or_undisclosed_collection_forms(tmp_path, version, extra):
    task = ConsoleProjectTask(tmp_path, version)
    code, payload = task.step('draft-declare-cli-console-plan',
        '--value', 'project_file', str(task.created_file), *extra)
    assert code != 0, payload
    assert not any(uri == CREATE for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', VERSIONS)
def test_console_create_rejects_unknown_native_base_platform_before_preview(tmp_path, version):
    task = ConsoleProjectTask(tmp_path, version)
    code, payload = task.step('draft-declare-cli-console-plan',
        '--value', 'project_file', str(task.created_file), '--item', 'platforms', 'InventedBase')
    if code == 0:
        code, payload = task.step('draft-check')
    if code == 0:
        code, payload = task.step('preview-from-draft')
    assert code != 0, payload
    assert not any(uri == CREATE for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
def test_cli_create_exposes_explicit_empty_platforms_without_defaulting(tmp_path, version):
    task = FieldTask(tmp_path, version, 'ak.wwise.cli.createNewProject')
    code, payload = task.step('draft-declare-cli-console-plan',
        '--value', 'project_file', str(tmp_path / 'New.wproj'), '--empty', 'platforms')
    assert code == 0, payload
    code, payload = task.step('draft-check')
    assert code == 0, payload
    assert not any(uri == 'ak.wwise.cli.createNewProject' for uri, _, _ in task.calls)


class CliProjectTask(FieldTask):
    def __init__(self, path, version, operation='ak.wwise.cli.migrate', outcome=0):
        self.operation, self.outcome = operation, outcome
        super().__init__(path, version, operation)

    def call(self, uri, args=None, options=None):
        if uri == self.operation:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return deepcopy(getattr(self, 'result_payload', {'result': self.outcome}))
        return super().call(uri, args, options)

    def execute_plan(self, *extra):
        code, payload = self.step('draft-declare-cli-console-plan',
            '--value', 'project_file', str(self.project_file), *extra)
        assert code == 0, payload
        code, payload = self.step('draft-check')
        assert code == 0, payload
        code, payload = self.step('preview-from-draft')
        assert code == 0, payload
        tx = payload['transaction_id']
        code, payload = self.run('transaction-show', tx)
        assert code == 0, payload
        code, payload = self.run('confirm', tx, '--confirmation-token', payload['confirmation']['token'])
        assert code == 0, payload
        code, payload = self.run('execute', tx)
        assert code == 0, payload
        return tx


def test_cli_add_platform_uses_documented_2025_default_name_when_omitted(tmp_path):
    task = CliProjectTask(tmp_path, '2025.1', 'ak.wwise.cli.addNewPlatform')
    tx = task.execute_plan('--value', 'base_platform', 'Windows')
    writes = [args for uri, args, _ in task.calls if uri == task.operation]
    assert writes == [{'project': str(task.project_file), 'new-platform-base': 'Windows'}]
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['state'] == 'result_schema_checked', payload
    assert payload['verification']['business_state_verified'] is False
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
def test_cli_add_platform_discloses_versioned_name_requirement_and_preserves_explicit_name(tmp_path, version):
    task = CliProjectTask(tmp_path, version, 'ak.wwise.cli.addNewPlatform')
    code, schema = task.run('--version', version, 'request-schema', task.operation)
    assert code == 0, schema
    declaration = schema['business_adapter']['declaration']
    assert ('platform_name' in declaration['required_fields']) is (version != '2025.1')
    assert ('platform_name' in declaration['optional_fields']) is (version == '2025.1')
    if version == '2025.1':
        assert declaration['constraints']['platform_name_when_omitted'] == 'use the base_platform name'
    code, started = task.run('draft-start', task.operation)
    assert code == 0, started
    continuation = started['draft']['next_action_binding']['declaration']
    for field in ('required_fields', 'optional_fields', 'input_forms'):
        assert continuation[field] == declaration[field]
    assert started['draft']['next_action_binding']['business_contract']['declaration'] == declaration
    tx = task.execute_plan('--value', 'base_platform', 'Windows',
                           '--value', 'platform_name', 'Studio',
                           '--value', 'copy_settings_from_platform', 'Windows_Old')
    assert [args for uri, args, _ in task.calls if uri == task.operation] == [{
        'project': str(task.project_file), 'new-platform-base': 'Windows',
        'new-platform-name': 'Studio', 'copy-from-platform': 'Windows_Old'}]
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['state'] == 'result_schema_checked', payload


def test_cli_add_platform_default_name_still_requires_documented_base(tmp_path):
    task = CliProjectTask(tmp_path, '2025.1', 'ak.wwise.cli.addNewPlatform')
    code, payload = task.step('draft-declare-cli-console-plan',
        '--value', 'project_file', str(task.project_file))
    assert code != 0, payload
    assert not any(uri == task.operation for uri, _, _ in task.calls)


@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
def test_cli_reported_error_cannot_pass_verification_or_retry(tmp_path, version):
    task = CliProjectTask(tmp_path, version, outcome=1)
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'verification_failed', payload
    assert payload['verification']['status'] == 'verification_failed'
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
@pytest.mark.parametrize(('outcome', 'meaning'), [(0, 'success'), (2, 'warnings_only')])
def test_cli_success_and_warnings_do_not_invent_file_effect_proof(tmp_path, version, outcome, meaning):
    task = CliProjectTask(tmp_path, version, outcome=outcome)
    tx = task.execute_plan()
    before = len(task.calls)
    code, payload = task.run('verify', tx)
    assert code == 0, json.dumps(payload)
    verification = payload['verification']
    assert verification['business_state_verified'] is False, verification
    observed = [row for row in verification['readbacks'] if row.get('kind') == 'cli-process-outcome']
    assert len(observed) == 1 and observed[0]['outcome'] == meaning, verification
    assert observed[0]['exit_code'] == outcome
    assert not any(row[0].endswith('object.get') for row in task.calls[before:])
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
@pytest.mark.parametrize('outcome', [True, None, 3, 0.5])
def test_cli_unknown_outcome_is_unverified_and_cannot_retry(tmp_path, version, outcome):
    task = CliProjectTask(tmp_path, version, outcome=outcome)
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'executed_unverified', payload
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version', ('2021.1', '2022.1', '2023.1'))
def test_earlier_media_id_void_result_does_not_fabricate_exit_success(tmp_path, version):
    task = CliProjectTask(tmp_path, version, 'ak.wwise.cli.moveMediaIdsToSingleFile')
    task.result_payload = {}
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert code == 0, json.dumps(payload)
    verification = payload['verification']
    assert verification['business_state_verified'] is False
    observed = [row for row in verification['readbacks'] if row.get('kind') == 'cli-process-outcome']
    assert len(observed) == 1 and observed[0]['outcome'] == 'not_reported', verification
    assert 'exit_code' not in observed[0]


@pytest.mark.parametrize('version', VERSIONS)
def test_console_platform_schema_and_continuation_disclose_pinned_choices(tmp_path, version):
    task = ConsoleProjectTask(tmp_path, version)
    code, schema = task.run('--version', version, 'request-schema', CREATE)
    assert code == 0, schema
    forms = schema['business_adapter']['declaration']['input_forms']['platforms']
    expected = ['Android', 'iOS', 'Linux', 'Mac', 'Switch', 'Ounce', 'PS4', 'PS5',
                'Windows', 'XboxOne', 'XboxSeriesX', 'Web', 'OpenHarmony']
    assert forms.get('base_platform_choices') == expected, forms
    assert forms.get('choice_scope') == 'pinned_schema_values_not_installed_availability'
    code, started = task.run('draft-start', CREATE)
    assert code == 0, started
    assert started['draft']['next_action_binding']['declaration']['input_forms']['platforms'] == forms
    code, payload = task.step('draft-declare-cli-console-plan',
        '--value', 'project_file', str(task.created_file), '--item', 'platforms', 'InventedBase')
    if code == 0:
        code, payload = task.step('draft-check')
    assert code != 0, payload
    assert all(choice in json.dumps(payload) for choice in expected), payload


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('failure', ['malformed', 'missing', 'wrong-project-id', 'wrong-platform', 'wrong-language', 'wrong-default-language', 'duplicate-project'])
def test_console_create_cannot_verify_wrong_saved_project(tmp_path, version, failure):
    task = ConsoleProjectTask(tmp_path, version)
    code, payload = task.step('draft-declare-cli-console-plan',
        '--value', 'project_file', str(task.created_file))
    assert code == 0, payload
    code, payload = task.step('draft-check')
    assert code == 0, payload
    code, payload = task.step('preview-from-draft')
    assert code == 0, payload
    tx = payload['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, payload = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, payload
    code, payload = task.run('execute', tx)
    assert code == 0, payload
    if failure == 'malformed':
        task.created_file.write_text('<WwiseDocument Type="Project" />')
    elif failure == 'missing':
        task.created_file.unlink()
    else:
        document = ET.fromstring(task.created_file.read_bytes())
        project = document.find('./ProjectInfo/Project')
        if failure == 'wrong-project-id':
            project.set('ID', '{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}')
        elif failure == 'wrong-platform':
            project.find('./Platforms/Platform').set('ReferencePlatform', 'Android')
        elif failure == 'wrong-language':
            project.find("./LanguageList/Language[@Name='English(US)']").set('Name', 'French')
        elif failure == 'wrong-default-language':
            project.find('./PropertyList/Property').set('Value', 'French')
        elif failure == 'duplicate-project':
            document.find('ProjectInfo').append(deepcopy(project))
        task.created_file.write_bytes(ET.tostring(document, encoding='utf-8'))
    retained = task.created_file.read_bytes() if task.created_file.exists() else None
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'verification_failed', payload
    assert payload.get('verified') is not True
    assert payload['cleanup']['projection']['automatic_cleanup'] is False
    assert (task.created_file.read_bytes() if task.created_file.exists() else None) == retained
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == CREATE]) == 1


def execute_console_creation(task, *extra, before_execute=None):
    code, payload = task.step('draft-declare-cli-console-plan',
        '--value', 'project_file', str(task.created_file), *extra)
    assert code == 0, payload
    code, payload = task.step('draft-check')
    assert code == 0, payload
    code, payload = task.step('preview-from-draft')
    assert code == 0, payload
    tx = payload['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, payload = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, payload
    if before_execute:
        before_execute()
    code, payload = task.run('execute', tx)
    return tx, code, payload


@pytest.mark.parametrize('version', VERSIONS)
def test_console_create_saves_requested_language_order_and_default(tmp_path, version):
    task = ConsoleProjectTask(tmp_path, version)
    tx, code, payload = execute_console_creation(task,
        '--item', 'languages', 'French', '--item', 'languages', 'Japanese')
    assert code == 0, payload
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is True, payload
    observed = [row for row in payload['verification']['readbacks'] if row.get('kind') == 'console-created-project-artifact']
    assert observed[0]['default_language'] == 'French'
    assert [row['Name'] for row in observed[0]['languages']] == ['SFX', 'French', 'Japanese']


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('missing_named', [False, True])
def test_console_create_matches_named_platform_before_base_only_saved_rows(tmp_path, version, missing_named):
    task = ConsoleProjectTask(tmp_path, version)
    tx, code, payload = execute_console_creation(task,
        '--item', 'platforms', 'Windows', '--mapping', 'platforms', 'Windows', 'Custom')
    assert code == 0, payload
    document = ET.fromstring(task.created_file.read_bytes())
    platforms = document.find('./ProjectInfo/Project/Platforms')
    rows = list(platforms)
    assert [row.get('Name') for row in rows] == ['Windows', 'Custom']
    if missing_named:
        rows[1].set('Name', 'Unrequested')
    platforms[:] = list(reversed(rows))
    task.created_file.write_bytes(ET.tostring(document, encoding='utf-8'))
    retained = task.created_file.read_bytes()
    code, verified = task.run('verify', tx)
    if missing_named:
        assert code != 0 and verified['state'] == 'verification_failed', verified
    else:
        assert code == 0 and verified['verified'] is True, verified
    assert task.created_file.read_bytes() == retained
    code, repeated = task.run('execute', tx)
    assert code != 0, repeated
    assert len([row for row in task.calls if row[0] == CREATE]) == 1


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('drift', ['destination-appears', 'root-replaced'])
def test_console_create_refuses_destination_drift_before_native_write(tmp_path, version, drift):
    task = ConsoleProjectTask(tmp_path, version)
    def change_destination():
        if drift == 'destination-appears':
            task.created_file.write_text('existing user file')
        else:
            task.created_file.parent.rename(tmp_path / 'retained-original-root')
            task.created_file.parent.mkdir()
    _, code, payload = execute_console_creation(task, before_execute=change_destination)
    assert code != 0, payload
    assert not any(row[0] == CREATE for row in task.calls)
    if drift == 'destination-appears':
        assert task.created_file.read_text() == 'existing user file'


@pytest.mark.parametrize('version', VERSIONS)
def test_console_create_observation_budget_is_unknown_not_a_proven_bad_effect(tmp_path, version):
    task = ConsoleProjectTask(tmp_path, version)
    tx, code, payload = execute_console_creation(task)
    assert code == 0, payload
    task.created_file.write_bytes(b' ' * (9 * 1024 * 1024))
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'executed_unverified', payload
    assert payload['error_code'] == 'LIMIT_EXCEEDED'
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == CREATE]) == 1
