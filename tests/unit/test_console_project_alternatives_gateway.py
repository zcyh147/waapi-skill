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
            SchemaVersion={'2021.1': '103', '2022.1': '110', '2023.1': '119', '2024.1': '123', '2025.1': '133'}[self.version],
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
        if type(self) is CliProjectTask:
            self.unit = saved_fixture_project(self)
            if operation == 'ak.wwise.cli.addNewPlatform':
                tree = ET.parse(self.project_file)
                tree.find('./ProjectInfo/Project/Platforms/Platform').set('Name', 'Windows_Old')
                tree.write(self.project_file)
                self.unit.write_text(self.unit.read_text().replace('Platform="Windows"', 'Platform="Windows_Old"'))

    def call(self, uri, args=None, options=None):
        if uri == self.operation:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if type(self) is CliProjectTask and uri == 'ak.wwise.cli.addNewPlatform':
                tree = ET.parse(self.project_file)
                ET.SubElement(tree.find('./ProjectInfo/Project/Platforms'), 'Platform',
                    Name=args.get('new-platform-name', args['new-platform-base']),
                    ReferencePlatform=args['new-platform-base'], ID='{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}')
                tree.write(self.project_file)
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
    assert code == 0 and payload['state'] == 'verified', payload
    assert payload['verification']['business_state_verified'] is True
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


class CliCreateEffectTask(ConsoleProjectTask):
    def __init__(self, path, version):
        self.created_file = path / 'New parent' / 'Created.wproj'
        self.operation = 'ak.wwise.cli.createNewProject'
        FieldTask.__init__(self, path, version, self.operation)
    def call(self, uri, args=None, options=None):
        if uri == self.operation:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            self.created_file.parent.mkdir(parents=True)
            self.write_created_project({'platforms': [{'basePlatform': 'Windows'}, {'basePlatform': 'Android'}]})
            return {'result': 0}
        return FieldTask.call(self, uri, args, options)

@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
def test_cli_create_verifies_saved_project_without_a_post_terminal_native_call(tmp_path, version):
    task = CliCreateEffectTask(tmp_path, version)
    code, payload = task.step('draft-declare-cli-console-plan', '--value', 'project_file',
        str(task.created_file), '--item', 'platforms', 'Windows', '--item', 'platforms', 'Android')
    assert code == 0, payload
    code, payload = task.step('draft-check')
    assert code == 0, payload
    code, payload = task.step('preview-from-draft')
    assert code == 0, payload
    tx = payload['transaction_id']
    code, payload = task.run('transaction-show', tx)
    assert code == 0, payload
    code, payload = task.run('confirm', tx, '--confirmation-token', payload['confirmation']['token'])
    assert code == 0, payload
    code, payload = task.run('execute', tx)
    assert code == 0, payload
    before = len(task.calls)
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is True, payload
    assert not any(row[0].endswith('object.get') for row in task.calls[before:])
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('failure', ['missing', 'malformed', 'wrong-platform', 'wrong-name', 'too-large'])
def test_cli_create_missing_or_wrong_artifact_never_verifies_or_reexecutes(tmp_path, failure):
    task = CliCreateEffectTask(tmp_path, '2025.1')
    original = task.write_created_project
    def write(args):
        original(args)
        if failure == 'missing':
            task.created_file.unlink()
        elif failure == 'malformed':
            task.created_file.write_text('<Project />')
        elif failure == 'too-large':
            task.created_file.write_bytes(b' ' * (8 * 1024 * 1024 + 1))
        else:
            tree = ET.parse(task.created_file)
            if failure == 'wrong-platform':
                tree.find('./ProjectInfo/Project/Platforms/Platform').set('ReferencePlatform', 'Mac')
            else:
                tree.find('./ProjectInfo/Project').set('Name', 'Wrong')
            tree.write(task.created_file)
    task.write_created_project = write
    # The common public chain owns authorization and creates no directories.
    task.project_file = task.created_file
    tx = CliProjectTask.execute_plan(task, '--item', 'platforms', 'Windows', '--item', 'platforms', 'Android')
    code, payload = task.run('verify', tx)
    assert code != 0 and payload.get('verified') is not True, payload
    assert payload['state'] == ('executed_unverified' if failure == 'too-large' else 'verification_failed'), payload
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


def saved_fixture_project(task):
    task.created_file = task.project_file
    ConsoleProjectTask.write_created_project(task, {})
    tree = ET.parse(task.project_file)
    tree.find('./ProjectInfo/Project').set('Name', 'Fixture')
    tree.write(task.project_file)
    unit = task.project_file.parent / 'Actor-Mixer Hierarchy' / 'Default Work Unit.wwu'
    unit.parent.mkdir()
    unit.write_text('''<WwiseDocument Type="WorkUnit" SchemaVersion="1" WwiseVersion="v2025.1.0">
<ActorMixerHierarchy><WorkUnit Name="Default Work Unit" ID="{11111111-1111-1111-1111-111111111111}" PersistMode="Standalone">
<ChildrenList><Sound Name="Keep" ID="{22222222-2222-2222-2222-222222222222}"><PropertyList><Property Name="Volume" Type="Real64"><ValueList><Value Platform="Windows">-6</Value></ValueList></Property></PropertyList></Sound></ChildrenList>
</WorkUnit></ActorMixerHierarchy></WwiseDocument>'''.replace('v2025.1.0', 'v' + task.version + '.0'))
    return unit


@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
@pytest.mark.parametrize('copy_settings', [False, True])
def test_cli_add_platform_checks_saved_platform_and_preserved_settings(tmp_path, version, copy_settings):
    class AddTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                tree = ET.parse(self.project_file)
                ET.SubElement(tree.find('./ProjectInfo/Project/Platforms'), 'Platform', Name='Studio',
                    ReferencePlatform='Windows', ID='{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}')
                tree.write(self.project_file)
                if copy_settings:
                    unit_tree = ET.parse(self.unit)
                    ET.SubElement(unit_tree.find('.//ValueList'), 'Value', Platform='Studio').text = '-6'
                    unit_tree.write(self.unit)
            return super().call(uri, args, options)
    task = AddTask(tmp_path, version, 'ak.wwise.cli.addNewPlatform')
    task.unit = saved_fixture_project(task)
    extra = ['--value', 'base_platform', 'Windows', '--value', 'platform_name', 'Studio']
    if copy_settings:
        extra += ['--value', 'copy_settings_from_platform', 'Windows']
    tx = task.execute_plan(*extra)
    before = len(task.calls)
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is True, payload
    assert not any(row[0].endswith('object.get') for row in task.calls[before:])
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('failure', ['missing-platform', 'wrong-base', 'wrong-name', 'existing-platform-lost',
    'existing-setting-changed', 'wrong-copy', 'elided-copy'])
def test_cli_add_platform_rejects_wrong_effect_and_keeps_elided_copy_partial(tmp_path, failure):
    class AddFailureTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                tree = ET.parse(self.project_file)
                platforms = tree.find('./ProjectInfo/Project/Platforms')
                if failure != 'missing-platform':
                    ET.SubElement(platforms, 'Platform', Name='Other' if failure == 'wrong-name' else 'Studio',
                        ReferencePlatform='Mac' if failure == 'wrong-base' else 'Windows',
                        ID='{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}')
                if failure == 'existing-platform-lost':
                    platforms.remove(platforms[0])
                tree.write(self.project_file)
                tree = ET.parse(self.unit)
                values = tree.find('.//ValueList')
                if failure == 'existing-setting-changed':
                    values[0].text = '-99'
                if failure not in {'elided-copy', 'missing-platform'}:
                    ET.SubElement(values, 'Value', Platform='Studio').text = '-99' if failure == 'wrong-copy' else '-6'
                tree.write(self.unit)
            return super().call(uri, args, options)
    task = AddFailureTask(tmp_path, '2025.1', 'ak.wwise.cli.addNewPlatform')
    task.unit = saved_fixture_project(task)
    tx = task.execute_plan('--value', 'base_platform', 'Windows', '--value', 'platform_name', 'Studio',
        '--value', 'copy_settings_from_platform', 'Windows')
    code, payload = task.run('verify', tx)
    assert payload['verified'] is False, payload
    if failure == 'elided-copy':
        assert code == 0 and payload['state'] == 'result_schema_checked', payload
        assert payload['verification']['readbacks'][-1]['unresolved'] == ['copy_settings_inherited_or_elided_native_representation']
    else:
        assert code != 0 and payload['state'] == 'verification_failed', payload
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


def test_cli_add_platform_freezes_all_observed_work_units_before_execution(tmp_path):
    task = CliProjectTask(tmp_path, '2025.1', 'ak.wwise.cli.addNewPlatform')
    unit = task.unit  # CliProjectTask already created the saved-model fixture.
    code, payload = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.project_file),
        '--value', 'base_platform', 'Windows', '--value', 'platform_name', 'Studio')
    assert code == 0, payload
    code, payload = task.step('draft-check')
    assert code == 0, payload
    code, payload = task.step('preview-from-draft')
    assert code == 0, payload
    tx = payload['transaction_id']
    code, payload = task.run('transaction-show', tx)
    assert code == 0, payload
    code, payload = task.run('confirm', tx, '--confirmation-token', payload['confirmation']['token'])
    assert code == 0, payload
    unit.write_text(unit.read_text().replace('-6', '-12'))
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert not any(row[0] == task.operation for row in task.calls)
    assert '-12' in unit.read_text()


@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
def test_cli_dump_reports_independent_json_artifact_without_inventing_model_format(tmp_path, version):
    class DumpTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                self.output.write_text('{"independent_fixture": ["Keep", "Fixture"]}')
            return super().call(uri, args, options)
    task = DumpTask(tmp_path, version, 'ak.wwise.cli.dumpObjects')
    task.output = tmp_path / 'objects.json'
    tx = task.execute_plan('--value', 'output_file', str(task.output), '--value', 'content', 'property_sets',
        '--toggle', 'include_session_objects', 'disable')
    before = len(task.calls)
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is False, payload
    observations = [row for row in payload['verification']['readbacks'] if row.get('kind') == 'cli-object-dump-artifact']
    assert len(observations) == 1, payload
    assert observations[0]['json_valid'] is True
    assert observations[0]['unresolved'] == ['object_model_content_and_session_representation']
    assert not any(row[0].endswith('object.get') for row in task.calls[before:])


def test_cli_dump_missing_artifact_cannot_verify_or_retry(tmp_path):
    task = CliProjectTask(tmp_path, '2025.1', 'ak.wwise.cli.dumpObjects')
    output = tmp_path / 'missing.json'
    tx = task.execute_plan('--value', 'output_file', str(output))
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'verification_failed', payload
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
def test_cli_migration_observes_target_version_and_preserves_saved_model(tmp_path, version):
    class MigrateTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                tree = ET.parse(self.project_file)
                tree.getroot().set('WwiseVersion', 'v' + version + '.0')
                tree.getroot().set('WwiseBuild', '2')
                tree.getroot().set('SchemaVersion', {'2021.1': '103', '2022.1': '110',
                    '2023.1': '119', '2024.1': '123', '2025.1': '133'}[version])
                tree.write(self.project_file)
            return super().call(uri, args, options)
    task = MigrateTask(tmp_path, version)
    saved_fixture_project(task)
    tree = ET.parse(task.project_file)
    tree.getroot().set('WwiseVersion', 'v2021.1.0')
    tree.getroot().set('SchemaVersion', '103')
    tree.write(task.project_file)
    tx = task.execute_plan()
    before = len(task.calls)
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is True, payload
    observed = [row for row in payload['verification']['readbacks'] if row.get('kind') == 'cli-migrated-project-artifact']
    assert len(observed) == 1 and observed[0]['saved_model_files'] == 2, payload
    assert not any(row[0].endswith('object.get') for row in task.calls[before:])


@pytest.mark.parametrize('output', ['{', '{"duplicate":1,"duplicate":2}', 'NaN', '[] trailing', '<xml/>'])
def test_cli_dump_rejects_malformed_json_output(tmp_path, output):
    class InvalidDump(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                self.output.write_text(output)
            return super().call(uri, args, options)
    task = InvalidDump(tmp_path, '2025.1', 'ak.wwise.cli.dumpObjects')
    task.output = tmp_path / 'objects.json'
    tx = task.execute_plan('--value', 'output_file', str(task.output))
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'verification_failed', payload


@pytest.mark.parametrize('failure', ['wrong-version', 'lost-workunit', 'wrong-project', 'property-transform', 'unchanged'])
def test_cli_migration_distinguishes_failed_preservation_and_unresolved_transformation(tmp_path, failure):
    class MigrateFailure(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                tree = ET.parse(self.project_file)
                if failure != 'unchanged':
                    tree.getroot().set('WwiseBuild', '2')
                    tree.getroot().set('WwiseVersion', 'v2024.1.0' if failure == 'wrong-version' else 'v2025.1.0')
                    if failure == 'wrong-project':
                        tree.find('./ProjectInfo/Project').set('ID', '{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}')
                    tree.write(self.project_file)
                if failure == 'lost-workunit':
                    self.unit.unlink()
                elif failure == 'property-transform':
                    self.unit.write_text(self.unit.read_text().replace('-6', '-12'))
            return super().call(uri, args, options)
    task = MigrateFailure(tmp_path, '2025.1')
    task.unit = saved_fixture_project(task)
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert payload['verified'] is False, payload
    if failure in {'property-transform', 'unchanged'}:
        assert code == 0 and payload['state'] == 'result_schema_checked', payload
        expected = ('migration_model_transformation_semantics' if failure == 'property-transform'
            else 'migration_save_has_no_observed_write')
        assert expected in payload['verification']['readbacks'][-1]['unresolved']
    else:
        assert code != 0 and payload['state'] == 'verification_failed', payload
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
@pytest.mark.parametrize('operation', ['moveMediaIdsToSingleFile', 'moveMediaIdsToWorkUnits', 'updateMediaIdsInSingleFile'])
def test_cli_media_ids_observe_owned_file_and_work_units_without_inventing_mapping_format(tmp_path, version, operation):
    class MediaTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                # Deliberately unknown representation: the saved bytes do not
                # establish a native container or complete mapping semantics.
                self.media.write_text('<UnestablishedMediaMappingFormat revision="after"/>')
            return super().call(uri, args, options)
    task = MediaTask(tmp_path, version, 'ak.wwise.cli.' + operation)
    saved_fixture_project(task)
    task.media = task.project_file.with_suffix('.mediaid')
    task.media.write_text('<UnestablishedMediaMappingFormat revision="before"/>')
    if version in ('2021.1', '2022.1', '2023.1'):
        task.result_payload = {}
    tx = task.execute_plan()
    before = len(task.calls)
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is False, payload
    observed = [row for row in payload['verification']['readbacks'] if row.get('kind') == 'cli-media-id-artifacts']
    assert len(observed) == 1 and observed[0]['mapping_file']['exists'] is True, payload
    assert observed[0]['mapping_file']['format'] == 'unestablished'
    assert 'central_media_id_mapping_representation' in observed[0]['unresolved']
    assert not any(row[0].endswith('object.get') for row in task.calls[before:])


@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
def test_unknown_media_id_container_is_unverified_not_a_proven_native_failure(tmp_path, version):
    class OpaqueMediaTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                self.project_file.with_suffix('.mediaid').write_bytes(b'\x00unestablished-container\xff')
            return super().call(uri, args, options)
    task = OpaqueMediaTask(tmp_path, version, 'ak.wwise.cli.moveMediaIdsToSingleFile')
    saved_fixture_project(task)
    if version in ('2021.1', '2022.1', '2023.1'):
        task.result_payload = {}
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['state'] == 'result_schema_checked', payload
    assert payload['verified'] is False
    observation = next(row for row in payload['verification']['readbacks'] if row.get('kind') == 'cli-media-id-artifacts')
    assert observation['mapping_file']['exists'] is True
    assert observation['mapping_file']['format'] == 'unestablished'
    assert 'central_media_id_mapping_representation' in observation['unresolved']
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


def test_cli_media_id_large_project_keeps_bounded_preview_and_exact_preservation(tmp_path):
    class LargeMediaTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                self.project_file.with_suffix('.mediaid').write_bytes(b'unknown-native-format')
            return super().call(uri, args, options)
    task = LargeMediaTask(tmp_path, '2021.1', 'ak.wwise.cli.moveMediaIdsToSingleFile')
    unit = saved_fixture_project(task)
    tree = ET.parse(unit)
    children = tree.find('.//ChildrenList')
    for index in range(2600):
        sound = ET.SubElement(children, 'Sound', Name='Long sound ' + 's' * 140 + str(index),
            ID='{10000000-0000-0000-0000-%012X}' % index)
        sources = ET.SubElement(sound, 'ChildrenList')
        source = ET.SubElement(sources, 'AudioFileSource', Name='Long source ' + 'a' * 140 + str(index),
            ID='{20000000-0000-0000-0000-%012X}' % index)
        ET.SubElement(source, 'Language').text = 'SFX'
        ET.SubElement(source, 'AudioFile').text = 'sample-%s.wav' % index
        ET.SubElement(ET.SubElement(source, 'MediaIDList'), 'MediaID', ID=str(index + 1))
    tree.write(unit)
    task.result_payload = {}
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['state'] == 'result_schema_checked', payload
    assert payload['verified'] is False
    observation = next(row for row in payload['verification']['readbacks']
        if row.get('kind') == 'cli-media-id-artifacts')
    assert observation['work_unit_media_id_count_before'] == 2600
    assert observation['work_unit_media_id_count_after'] == 2600
    assert len(json.dumps(payload).encode()) < 64 * 1024


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1'])
@pytest.mark.parametrize('outcome', [0, 1, 2])
def test_earlier_media_id_observed_process_result_keeps_effect_unverified(tmp_path, version, outcome):
    class ObservedResultTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                self.project_file.with_suffix('.mediaid').write_bytes(b'unknown-native-format')
            return super().call(uri, args, options)
    task = ObservedResultTask(tmp_path, version, 'ak.wwise.cli.moveMediaIdsToSingleFile', outcome)
    saved_fixture_project(task)
    code, schema = task.run('request-schema', task.operation)
    assert code == 0
    assert 'console-media-single-observed-process-result/v1' in json.dumps(schema)
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert payload['state'] == ('verification_failed' if outcome == 1 else 'result_schema_checked'), payload
    assert (code != 0) == (outcome == 1)
    assert payload['verified'] is False
    process = next(row for row in payload['verification']['readbacks'] if row.get('kind') == 'cli-process-outcome')
    assert process['outcome'] == {0: 'success', 1: 'errors', 2: 'warnings_only'}[outcome]
    assert process['partial_effects_possible'] is (outcome == 1)
    rules = [rule for assertion in payload['verification']['assertions']
        for rule in assertion.get('evidence', {}).get('compatibility_rules', [])]
    assert len(rules) == 1
    assert rules[0]['rule_id'] == 'console-media-single-observed-process-result/v1'
    assert rules[0]['version'] == version
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('native_result', [{'result': True}, {'result': 3}, {'result': '0'}, {'result': 0, 'extra': 1}])
def test_earlier_media_id_process_compatibility_rejects_unproved_shapes(tmp_path, native_result):
    task = CliProjectTask(tmp_path, '2021.1', 'ak.wwise.cli.moveMediaIdsToSingleFile')
    task.result_payload = native_result
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert code != 0 and payload.get('verified') is not True, payload
    assert payload['state'] in {'executed_unverified', 'verification_failed'}
    code, payload = task.run('execute', tx)
    assert code != 0
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('change', ['owner-id', 'owner-name', 'media-id', 'duplicate-media-row'])
def test_cli_migration_compact_identity_proofs_preserve_every_row(tmp_path, change):
    class ChangedIdentityTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                tree = ET.parse(self.unit)
                source = tree.find('.//AudioFileSource')
                if change == 'owner-id':
                    source.set('ID', '{44444444-4444-4444-4444-444444444444}')
                elif change == 'owner-name':
                    source.set('Name', 'Changed')
                elif change == 'media-id':
                    source.find('./MediaIDList/MediaID').set('ID', '654321')
                else:
                    ET.SubElement(source.find('./MediaIDList'), 'MediaID', ID='123456')
                tree.write(self.unit)
            return super().call(uri, args, options)
    task = ChangedIdentityTask(tmp_path, '2025.1')
    task.unit = saved_fixture_project(task)
    tree = ET.parse(task.unit)
    source = ET.SubElement(ET.SubElement(tree.find('.//Sound'), 'ChildrenList'),
        'AudioFileSource', Name='Keep source', ID='{33333333-3333-3333-3333-333333333333}')
    ET.SubElement(source, 'Language').text = 'SFX'
    ET.SubElement(source, 'AudioFile').text = 'Keep.wav'
    ET.SubElement(ET.SubElement(source, 'MediaIDList'), 'MediaID', ID='123456')
    tree.write(task.unit)
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'verification_failed', payload
    assert payload['verified'] is False
    code, payload = task.run('execute', tx)
    assert code != 0
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version,source_kind,change', [
    *[(version, 'AudioFileSource', None) for version in ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1']],
    ('2025.1', 'MidiFileSource', None), ('2025.1', 'PluginMediaSource', None),
    ('2025.1', 'AudioFileSource', 'already-central'),
    ('2025.1', 'AudioFileSource', 'mode-conflicting-encodings'),
    ('2025.1', 'AudioFileSource', 'mode-value-list'),
    *[('2025.1', 'AudioFileSource', change) for change in ['media-id', 'source-id', 'filename',
        'language-id', 'other-language', 'duplicate-source', 'duplicate-media', 'missing-media',
        'mode-unchanged', 'work-unit-ids-remain', 'unrelated-property', 'unrelated-same-name-property']],
])
def test_cli_media_id_move_verifies_exact_source_mapping_and_storage_mode(tmp_path, version, source_kind, change):
    class MoveMediaTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                self.project_file.with_suffix('.mediaid').write_text('''<WwiseDocument Type="MediaIDs">
<MediaIDInfo><MediaIDs><Language ID="393239870" Name="SFX"><File Name="Keep.wav">
<WObject ID="{33333333-3333-3333-3333-333333333333}"><MediaID ID="123456"/>
<Hash Platform="Windows" Value="3181527220"/></WObject>
</File></Language></MediaIDs></MediaIDInfo></WwiseDocument>''')
                mapping = self.project_file.with_suffix('.mediaid')
                tree = ET.parse(mapping)
                language = tree.find('.//Language')
                if source_kind == 'PluginMediaSource':
                    language.attrib = {'ID': '27267154'}
                owner = tree.find('.//WObject')
                if change == 'media-id':
                    owner.find('MediaID').set('ID', '654321')
                elif change == 'source-id':
                    owner.set('ID', '{44444444-4444-4444-4444-444444444444}')
                elif change == 'filename':
                    tree.find('.//File').set('Name', 'Other.wav')
                elif change == 'language-id':
                    language.set('ID', '17')
                elif change == 'other-language':
                    language.attrib = {'ID': '684519430', 'Name': 'English(US)'}
                elif change == 'duplicate-source':
                    tree.find('.//File').append(deepcopy(owner))
                elif change == 'duplicate-media':
                    owner.append(deepcopy(owner.find('MediaID')))
                elif change == 'missing-media':
                    owner.remove(owner.find('MediaID'))
                tree.write(mapping)
                tree = ET.parse(self.unit)
                source = tree.find('.//' + source_kind)
                if change != 'work-unit-ids-remain' and source.find('MediaIDList') is not None:
                    source.remove(source.find('MediaIDList'))
                if change == 'unrelated-property':
                    tree.find('.//Sound/PropertyList/Property/ValueList/Value').text = '-12'
                elif change == 'unrelated-same-name-property':
                    tree.find('.//Sound/PropertyList/Property[@Name="MediaIDsInSingleFile"]').set('Value', 'True')
                tree.write(self.unit)
                tree = ET.parse(self.project_file)
                if change != 'mode-unchanged':
                    fields = tree.find('./ProjectInfo/Project/PropertyList')
                    field = fields.find('Property[@Name="MediaIDsInSingleFile"]')
                    if field is None:
                        field = ET.SubElement(fields, 'Property', Name='MediaIDsInSingleFile', Type='bool')
                    field.set('Value', 'True')
                    if change in {'mode-conflicting-encodings', 'mode-value-list'}:
                        if change == 'mode-conflicting-encodings':
                            field.set('Value', 'False')
                        else:
                            del field.attrib['Value']
                        ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value').text = 'True'
                tree.write(self.project_file)
            return super().call(uri, args, options)
    task = MoveMediaTask(tmp_path, version, 'ak.wwise.cli.moveMediaIdsToSingleFile')
    task.unit = saved_fixture_project(task)
    tree = ET.parse(task.unit)
    source = ET.SubElement(ET.SubElement(tree.find('.//Sound'), 'ChildrenList'),
        source_kind, Name='Renamed source', ID='{33333333-3333-3333-3333-333333333333}')
    if source_kind == 'PluginMediaSource':
        ET.SubElement(source, 'ParentPluginID').text = '27267154'
        ET.SubElement(ET.SubElement(source, 'PropertyList'), 'Property', Name='DataFileName', Type='string', Value='Keep.wav')
    else:
        ET.SubElement(source, 'Language').text = 'SFX'
        ET.SubElement(source, 'AudioFile' if source_kind == 'AudioFileSource' else 'MidiFile').text = 'Keep.wav'
    if change == 'unrelated-same-name-property':
        ET.SubElement(tree.find('.//Sound/PropertyList'), 'Property', Name='MediaIDsInSingleFile', Type='bool', Value='False')
    ET.SubElement(ET.SubElement(source, 'MediaIDList'), 'MediaID', ID='123456')
    if change == 'already-central':
        source.remove(source.find('MediaIDList'))
        task.project_file.with_suffix('.mediaid').write_text('''<WwiseDocument Type="MediaIDs"><MediaIDInfo><MediaIDs>
<Language ID="393239870" Name="SFX"><File Name="Keep.wav"><WObject ID="{33333333-3333-3333-3333-333333333333}">
<MediaID ID="123456"/></WObject></File></Language></MediaIDs></MediaIDInfo></WwiseDocument>''')
        project = ET.parse(task.project_file)
        ET.SubElement(project.find('./ProjectInfo/Project/PropertyList'), 'Property',
            Name='MediaIDsInSingleFile', Type='bool', Value='True')
        project.write(task.project_file)
    tree.write(task.unit)
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    if change not in {None, 'already-central', 'mode-value-list'}:
        assert code != 0 and payload['state'] == 'verification_failed', payload
        assert payload['verified'] is False
        code, payload = task.run('execute', tx)
        assert code != 0
        assert len([row for row in task.calls if row[0] == task.operation]) == 1
        return
    assert code == 0 and payload['verified'] is True, payload
    observation = next(row for row in payload['verification']['readbacks']
        if row.get('kind') == 'cli-media-id-artifacts')
    assert observation['mapping_file']['format'] == 'wwise-media-ids-xml'
    assert observation['mapping_file']['media_count'] == 1
    assert observation['work_unit_media_id_count_before'] == (0 if change == 'already-central' else 1)
    assert observation['work_unit_media_id_count_after'] == 0
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('failure', ['missing-mapping', 'malformed-mapping', 'lost-workunit', 'unrelated-setting'])
def test_cli_media_id_artifact_or_preservation_failure_cannot_verify(tmp_path, failure):
    class MediaFailure(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                if failure == 'malformed-mapping':
                    self.media.write_text('<broken')
                elif failure != 'missing-mapping':
                    self.media.write_text('<UnknownNativeMediaFormat/>')
                if failure == 'lost-workunit':
                    self.unit.unlink()
                elif failure == 'unrelated-setting':
                    self.unit.write_text(self.unit.read_text().replace('-6', '-12'))
            return super().call(uri, args, options)
    task = MediaFailure(tmp_path, '2025.1', 'ak.wwise.cli.moveMediaIdsToSingleFile')
    task.unit = saved_fixture_project(task)
    tree = ET.parse(task.unit)
    source = ET.SubElement(tree.find('.//Sound'), 'AudioFileSource', Name='Keep.wav',
        ID='{33333333-3333-3333-3333-333333333333}')
    ET.SubElement(ET.SubElement(source, 'MediaIDList'), 'MediaID', ID='123456')
    tree.write(task.unit)
    task.media = task.project_file.with_suffix('.mediaid')
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert payload['verified'] is False, payload
    if failure == 'malformed-mapping':
        # This is malformed XML, but the native container has not been proved
        # to be XML. It therefore establishes neither success nor failure.
        assert code == 0 and payload['state'] == 'result_schema_checked', payload
    else:
        assert code != 0 and payload['state'] == 'verification_failed', payload
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


def test_cli_add_platform_does_not_hide_significant_saved_text_whitespace_change(tmp_path):
    class ChangedText(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                tree = ET.parse(self.project_file)
                ET.SubElement(tree.find('./ProjectInfo/Project/Platforms'), 'Platform', Name='Studio',
                    ReferencePlatform='Windows', ID='{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}')
                tree.write(self.project_file)
                self.unit.write_text(self.unit.read_text().replace('Keep.wav ', 'Keep.wav'))
            return super().call(uri, args, options)
    task = ChangedText(tmp_path, '2025.1', 'ak.wwise.cli.addNewPlatform')
    task.unit = saved_fixture_project(task)
    tree = ET.parse(task.unit)
    source = ET.SubElement(tree.find('.//Sound'), 'AudioFileSource', Name='Source',
        ID='{33333333-3333-3333-3333-333333333333}')
    ET.SubElement(source, 'AudioFile').text = 'Keep.wav '
    tree.write(task.unit)
    tx = task.execute_plan('--value', 'base_platform', 'Windows', '--value', 'platform_name', 'Studio')
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'verification_failed', payload


def test_cli_project_model_has_a_disclosed_directory_depth_budget(tmp_path):
    task = CliProjectTask(tmp_path, '2025.1', 'ak.wwise.cli.addNewPlatform')
    task.project_file.parent.joinpath(*['level'] * 65).mkdir(parents=True)
    code, schema = task.run('--version', '2025.1', 'request-schema', task.operation)
    assert code == 0, schema
    assert schema['business_adapter']['effect_verification']['limits'].get('model_depth') == 64
    code, payload = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.project_file),
        '--value', 'base_platform', 'Windows', '--value', 'platform_name', 'Studio')
    assert code == 0, payload
    code, payload = task.step('draft-check')
    assert code != 0 and payload['error_code'] == 'LIMIT_EXCEEDED', payload
    assert not any(row[0] == task.operation for row in task.calls)


def test_cli_dump_unavailable_read_remains_a_structured_unknown_outcome(tmp_path, monkeypatch):
    import os
    class Dump(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                self.output.write_text('{"fixture":true}')
            return super().call(uri, args, options)
    task = Dump(tmp_path, '2025.1', 'ak.wwise.cli.dumpObjects')
    task.output = tmp_path / 'objects.json'
    tx = task.execute_plan('--value', 'output_file', str(task.output))
    inode = task.output.stat().st_ino
    original = os.fdopen
    matched = 0
    class UnavailableRead:
        def __init__(self, opened):
            self.opened = opened
        def __enter__(self):
            self.opened.__enter__()
            return self
        def __exit__(self, *args):
            return self.opened.__exit__(*args)
        def read(self, *args):
            raise OSError('Injected filesystem read failure')
        def fileno(self):
            return self.opened.fileno()
    def fdopen(descriptor, *args, **kwargs):
        nonlocal matched
        selected = os.fstat(descriptor).st_ino == inode
        if selected:
            matched += 1
        opened = original(descriptor, *args, **kwargs)
        return UnavailableRead(opened) if selected and matched == 2 else opened
    monkeypatch.setattr(os, 'fdopen', fdopen)
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'executed_unverified', payload
    assert payload['error_code'] == 'INVALID_FILE', payload


def test_cli_add_platform_keeps_preexisting_unregistered_platform_values_unresolved(tmp_path):
    class OrphanValues(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                tree = ET.parse(self.project_file)
                ET.SubElement(tree.find('./ProjectInfo/Project/Platforms'), 'Platform', Name='Studio',
                    ReferencePlatform='Windows', ID='{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}')
                tree.write(self.project_file)
                tree = ET.parse(self.unit)
                tree.find('.//Value[@Platform="Studio"]').text = '-99'
                tree.write(self.unit)
            return super().call(uri, args, options)
    task = OrphanValues(tmp_path, '2025.1', 'ak.wwise.cli.addNewPlatform')
    task.unit = saved_fixture_project(task)
    tree = ET.parse(task.unit)
    ET.SubElement(tree.find('.//ValueList'), 'Value', Platform='Studio').text = '-6'
    tree.write(task.unit)
    tx = task.execute_plan('--value', 'base_platform', 'Windows', '--value', 'platform_name', 'Studio')
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is False and payload['state'] == 'result_schema_checked', payload
    assert 'preexisting_unregistered_platform_values' in payload['verification']['readbacks'][-1]['unresolved']
