"""Closed Console project alternatives through the real public Draft chain.

Pinned schemas establish construction; injected clients do not establish native
project effects or permit any native process launch.
"""
from copy import deepcopy
import json
import os
from xml.etree import ElementTree as ET

import pytest

from tests.unit.test_field_interface_closure_gateway import FieldTask


VERSIONS = ('2023.1', '2024.1', '2025.1')
CREATE = 'ak.wwise.console.project.create'
OPEN = 'ak.wwise.console.project.open'


class WaapiRequestFailed(Exception):
    """Literal shape observed in the owned 2023 no-project native receipt."""
    def __init__(self, procedure, uri='ak.wwise.no_project_loaded'):
        self.uri = uri
        self.kwargs = {'details': {'procedureUri': procedure}, 'message': 'No project is loaded.'}
        super().__init__('native structured project absence')


class NoProjectConsoleTask(FieldTask):
    def __init__(self, path, version, operation=CREATE, *, absence='native-error'):
        self.created_file = path / 'Created' / 'Created.wproj'
        self.created_file.parent.mkdir()
        self.opened, self.absence, self.operation = False, absence, operation
        self.info_overrides, self.effect = {}, 'exact'
        self.expected_args = {'path': str(self.created_file)}
        super().__init__(path, version, operation)
        if operation == OPEN:
            ConsoleProjectTask.write_created_project(self, {})

    def call(self, uri, args=None, options=None):
        if uri.endswith('getInfo'):
            return {**super().call(uri, args, options), **self.info_overrides}
        if uri.endswith('getProjectInfo') or (uri.endswith('object.get') and args == {'waql': 'from type Project take 2'}):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if not self.opened:
                if uri.endswith('object.get') and self.absence == 'empty-query':
                    return {'return': []}
                error = WaapiRequestFailed(uri)
                if uri.endswith('getProjectInfo'):
                    if self.absence == 'transport':
                        raise ConnectionError('ak.wwise.no_project_loaded in a transport message is not native absence')
                    if self.absence == 'timeout':
                        raise TimeoutError('ak.wwise.no_project_loaded')
                    if self.absence == 'timeout-with-native-attributes':
                        timeout = TimeoutError('unobserved native result')
                        timeout.uri, timeout.kwargs = error.uri, error.kwargs
                        raise timeout
                    if self.absence == 'message-only':
                        raise RuntimeError('ak.wwise.no_project_loaded')
                    if self.absence == 'wrong-uri':
                        error.uri = 'ak.wwise.invalid_arguments'
                    if self.absence == 'wrong-procedure':
                        error.kwargs['details']['procedureUri'] = 'ak.wwise.core.object.get'
                    if self.absence == 'malformed-details':
                        error.kwargs['details'] = []
                raise error
            row = {'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'Created',
                'type': 'Project', 'path': '\\', 'filePath': str(self.created_file)}
            if self.effect == 'wrong-guid':
                row['id'] = '{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}'
            if self.effect == 'wrong-name':
                row['name'] = 'Other'
            if self.effect == 'wrong-path':
                row['filePath'] = str(self.created_file.parent / 'Other.wproj')
            if uri.endswith('getProjectInfo'):
                return {'id': row['id'], 'name': row['name'], 'path': row['filePath']}
            return {'return': [row]}
        if uri == self.operation:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args == self.expected_args, args
            assert not self.opened
            if self.effect == 'native-error':
                raise WaapiRequestFailed(uri, 'ak.wwise.invalid_arguments')
            if self.effect == 'indeterminate':
                raise TimeoutError('native response was not observed')
            if self.operation == CREATE:
                ConsoleProjectTask.write_created_project(self, args)
            self.opened = self.effect != 'stay-none'
            return {}
        return super().call(uri, args, options)


class WineNoProjectConsoleTask(NoProjectConsoleTask):
    """Native-shaped Wine process/paths; public plans still use owned POSIX files."""
    def __init__(self, path, version, operation):
        super().__init__(path, version, operation)
        self.info_overrides.update(platform='x64', processPath=r'c:\Program Files\Audiokinetic\Wwise\WwiseConsole.exe')
        if operation == CREATE:
            self.created_file = path / 'Fresh' / 'Nested' / 'Created.wproj'
            self.expected_args = {'path': r'Y:\Fresh\Nested\Created.wproj'}
        else:
            self.expected_args = {'path': r'Y:\Created\Created.wproj'}

    def call(self, uri, args=None, options=None):
        if uri == CREATE:
            self.created_file.parent.mkdir(parents=True)
        result = super().call(uri, args, options)
        if self.opened:
            if uri.endswith('getProjectInfo'):
                result['path'] = self.expected_args['path']
            elif uri.endswith('object.get') and args.get('waql') == 'from type Project take 2':
                for row in result['return']:
                    row['filePath'] = self.expected_args['path']
        return result


@pytest.mark.skipif(os.name == 'nt', reason='Injected POSIX Wine path context; no native Windows evidence')
@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('operation', [CREATE, OPEN])
@pytest.mark.parametrize('inside_home', [True, False])
def test_console_load_from_none_translates_only_transient_wine_path_and_strongly_verifies(tmp_path, monkeypatch, version, operation, inside_home):
    from types import SimpleNamespace
    from wwise_waapi import platform_paths
    home = tmp_path if inside_home else tmp_path / 'AccountHome'
    home.mkdir(exist_ok=True)
    monkeypatch.setattr(platform_paths.pwd, 'getpwuid', lambda _uid: SimpleNamespace(pw_dir=str(home)))
    task = WineNoProjectConsoleTask(tmp_path, version, operation)
    if not inside_home:
        task.expected_args = {'path': 'Z:\\' + '\\'.join(task.created_file.resolve().parts[1:])}
    preview = _console_load_preview(task)
    tx = _authorize_console_load(task, preview)
    code, before = task.run('transaction-show', tx)
    assert code == 0, before
    sealed = before['artifact']['prepared_operation']['dispatch']
    assert sealed == {'uri': operation, 'args': {'path': str(task.created_file)}, 'options': {}}
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    assert executed['wire_path_adaptation']['mapping']['anchor_source'] == 'transition_target'
    assert executed['wire_path_adaptation']['mapping']['round_trip_verified'] is True
    assert [args for uri, args, _ in task.calls if uri == operation] == [task.expected_args]
    code, after = task.run('transaction-show', tx)
    assert code == 0 and after['artifact']['prepared_operation']['dispatch'] == sealed, after
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified
    assert verified['verification']['business_state_verified'] is True
    code, repeated = task.run('execute', tx)
    assert code != 0, repeated
    assert [uri for uri, _, _ in task.calls].count(operation) == 1


@pytest.mark.skipif(os.name == 'nt', reason='Injected POSIX Wine context')
@pytest.mark.parametrize('drift', ['remote', 'configuration', 'runtime', 'file'])
def test_console_wine_none_load_retains_endpoint_runtime_and_file_guards(tmp_path, monkeypatch, drift):
    from types import SimpleNamespace
    from wwise_waapi import platform_paths
    monkeypatch.setattr(platform_paths.pwd, 'getpwuid', lambda _uid: SimpleNamespace(pw_dir=str(tmp_path)))
    task = WineNoProjectConsoleTask(tmp_path, '2023.1', OPEN)
    if drift == 'remote':
        code, configured = task.run('config-set', '--waapi-host', '192.0.2.10')
        assert code == 0, configured
        code, restarted = task.run('draft-start', OPEN)
        assert code == 0, restarted
        task.draft, task.authority, task.revision = restarted['draft']['draft_id'], restarted['task_authority'], restarted['draft']['revision']
        code, declared = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.created_file))
        assert code == 0, declared
        code, rejected = task.step('draft-check')
        assert code != 0 and rejected['error_code'] == 'LOCAL_WAAPI_HOST_REQUIRED', rejected
        assert not any(uri == OPEN for uri, _, _ in task.calls)
        return
    tx = _authorize_console_load(task, _console_load_preview(task))
    if drift == 'configuration':
        code, configured = task.run('config-set', '--waapi-port', '31338')
        assert code == 0, configured
    elif drift == 'runtime':
        task.info_overrides['processPath'] = r'D:\Foreign\WwiseConsole.exe'
    elif drift == 'file':
        task.created_file.write_text(task.created_file.read_text() + '\n<!-- changed after preview -->')
    code, rejected = task.run('execute', tx)
    assert code != 0 and rejected.get('executed') is not True, rejected
    assert not any(uri == OPEN for uri, _, _ in task.calls)


@pytest.mark.skipif(os.name == 'nt', reason='Foreign native drive is not a local POSIX file')
def test_console_none_wine_load_does_not_map_caller_foreign_drive(tmp_path):
    task = WineNoProjectConsoleTask(tmp_path, '2023.1', OPEN)
    code, payload = task.step('draft-declare-cli-console-plan', '--value', 'project_file', r'W:\Foreign\Created.wproj')
    if code == 0:
        code, payload = task.step('draft-check')
    assert code != 0, payload
    assert not any(uri == OPEN for uri, _, _ in task.calls)


@pytest.mark.skipif(os.name == 'nt', reason='Injected POSIX Wine readback')
def test_console_none_wine_load_refuses_foreign_drive_readback_without_replaying(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from wwise_waapi import platform_paths
    monkeypatch.setattr(platform_paths.pwd, 'getpwuid', lambda _uid: SimpleNamespace(pw_dir=str(tmp_path)))
    task = WineNoProjectConsoleTask(tmp_path, '2023.1', OPEN)
    tx = _authorize_console_load(task, _console_load_preview(task))
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    task.expected_args = {'path': r'W:\Foreign\Created.wproj'}
    code, rejected = task.run('verify', tx)
    assert code != 0 and rejected.get('verified') is not True, rejected
    code, repeated = task.run('execute', tx)
    assert code != 0, repeated
    assert [uri for uri, _, _ in task.calls].count(OPEN) == 1


def test_console_project_create_from_exact_native_no_project_reaches_verified_once(tmp_path):
    task = NoProjectConsoleTask(tmp_path, '2023.1')
    tx, code, executed = execute_console_creation(task)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([call for call in task.calls if call[0] == CREATE]) == 1


def test_console_project_open_checks_saved_target_identity_after_no_project(tmp_path):
    task = NoProjectConsoleTask(tmp_path, '2025.1', OPEN)
    task.effect = 'wrong-guid'
    tx, code, executed = execute_console_creation(task)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 2 and verified.get('verified') is not True, verified
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert len([call for call in task.calls if call[0] == OPEN]) == 1


@pytest.mark.parametrize('change', [{'sessionId': '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'}, {'processId': 43}])
def test_console_no_project_declaration_retains_its_original_runtime_before_check(tmp_path, change):
    task = NoProjectConsoleTask(tmp_path, '2025.1', OPEN)
    code, declared = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.created_file))
    assert code == 0, declared
    task.info_overrides.update(change)
    code, rejected = task.step('draft-check')
    assert code == 2, rejected
    assert not any(call[0] == OPEN for call in task.calls)


def _console_load_preview(task, *, policy='ask_before_changes', extra=()):
    code, configured = task.run('config-set', '--project-modification-policy', policy)
    assert code == 0, configured
    code, declared = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.created_file), *extra)
    assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 0, checked
    code, preview = task.step('preview-from-draft')
    if policy == 'read_only':
        assert code == 2 and 'read_only' in json.dumps(preview), preview
        return preview
    assert code == 0, preview
    return preview


def _authorize_console_load(task, preview):
    tx = preview['transaction_id']
    if preview['state'] == 'awaiting_confirmation':
        code, shown = task.run('transaction-show', tx)
        assert code == 0, shown
        code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
        assert code == 0, confirmed
    return tx


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('operation', [CREATE, OPEN])
@pytest.mark.parametrize('absence', ['native-error', 'empty-query'])
def test_console_project_load_from_none_uses_closed_versioned_route_once(tmp_path, version, operation, absence):
    task = NoProjectConsoleTask(tmp_path, version, operation, absence=absence)
    code, schema = task.run('request-schema', operation)
    assert code == 0 and schema['business_adapter']['project_start_state']['loaded_project'] == 'optional', schema
    preview = _console_load_preview(task)
    from wwise_waapi.transactions import TransactionStore
    artifact = TransactionStore(tmp_path / 'state').load_preview(preview['transaction_id']).artifact
    assert artifact['project_guard']['project'] == {'state': 'none'}, artifact
    assert artifact['project_guard']['project_guard_mode'] == 'transition_to_path'
    tx = _authorize_console_load(task, preview)
    code, executed = task.run('execute', tx)
    assert code == 0 and executed['automatic_retry'] is False, executed
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert [call[0] for call in task.calls].count(operation) == 1
    if absence == 'native-error':
        assert any(call[0].endswith('getProjectInfo') for call in task.calls)
    else:
        assert not any(call[0].endswith('getProjectInfo') for call in task.calls)


@pytest.mark.parametrize('operation', [CREATE, OPEN])
@pytest.mark.parametrize('policy', ['read_only', 'ask_before_changes', 'allow_changes'])
def test_console_project_load_from_none_keeps_three_modification_policies(tmp_path, operation, policy):
    task = NoProjectConsoleTask(tmp_path, '2025.1', operation)
    preview = _console_load_preview(task, policy=policy)
    assert not any(call[0] == operation for call in task.calls)
    if policy == 'read_only':
        return
    if policy == 'ask_before_changes':
        code, unconfirmed = task.run('execute', preview['transaction_id'])
        assert code == 2 and unconfirmed.get('executed') is not True, unconfirmed
    tx = _authorize_console_load(task, preview)
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified
    assert [call[0] for call in task.calls].count(operation) == 1


@pytest.mark.parametrize('absence', ['transport', 'timeout', 'message-only', 'wrong-uri', 'wrong-procedure', 'malformed-details'])
def test_console_native_absence_never_infers_none_from_other_failures(tmp_path, absence):
    task = NoProjectConsoleTask(tmp_path, '2025.1', OPEN, absence=absence)
    code, rejected = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.created_file))
    assert code == 2, rejected
    assert not any(call[0] == OPEN for call in task.calls)


@pytest.mark.parametrize('change', [{'sessionId': None}, {'processId': True}, {'processPath': ''}])
def test_console_native_absence_requires_current_proved_runtime(tmp_path, change):
    task = NoProjectConsoleTask(tmp_path, '2025.1', OPEN)
    task.info_overrides.update(change)
    code, rejected = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.created_file))
    assert code == 2, rejected
    assert not any(call[0] == OPEN for call in task.calls)


@pytest.mark.parametrize('operation', [CREATE, OPEN])
@pytest.mark.parametrize('drift', ['config', 'session', 'host', 'version', 'project-appears', 'target-file'])
def test_console_load_revalidates_none_runtime_configuration_and_target_before_write(tmp_path, operation, drift):
    task = NoProjectConsoleTask(tmp_path, '2025.1', operation)
    tx = _authorize_console_load(task, _console_load_preview(task))
    if drift == 'config':
        code, configured = task.run('config-set', '--waapi-port', '31338')
        assert code == 0, configured
    elif drift == 'session':
        task.info_overrides['sessionId'] = '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'
    elif drift == 'host':
        task.info_overrides['isCommandLine'] = False
    elif drift == 'version':
        info = task.call('ak.wwise.core.getInfo')
        task.info_overrides['version'] = {**info['version'], 'year': 2024}
    elif drift == 'project-appears':
        task.opened = True
    else:
        task.created_file.write_bytes(b'Unreviewed target-file replacement')
    before = task.created_file.read_bytes() if task.created_file.exists() else None
    code, rejected = task.run('execute', tx)
    assert code == 2 and rejected.get('executed') is not True, rejected
    assert not any(call[0] == operation for call in task.calls)
    assert (task.created_file.read_bytes() if task.created_file.exists() else None) == before


@pytest.mark.parametrize('operation', [CREATE, OPEN])
@pytest.mark.parametrize('effect', ['wrong-guid', 'wrong-name', 'wrong-path', 'stay-none', 'native-error', 'indeterminate'])
def test_console_load_never_verifies_wrong_project_or_replays_terminal_write(tmp_path, operation, effect):
    task = NoProjectConsoleTask(tmp_path, '2025.1', operation)
    task.effect = effect
    tx = _authorize_console_load(task, _console_load_preview(task))
    code, executed = task.run('execute', tx)
    if effect in {'native-error', 'indeterminate'}:
        assert code == 2 and executed['automatic_retry'] is False, executed
        assert executed['state'] in {'execution_failed', 'indeterminate'}, executed
    else:
        assert code == 0, executed
        code, verified = task.run('verify', tx)
        assert code == 2 and verified.get('verified') is not True, verified
    code, repeated = task.run('execute', tx)
    assert code == 2, repeated
    assert [call[0] for call in task.calls].count(operation) == 1


def test_console_open_identity_binding_preserves_explicit_migration_of_an_older_project(tmp_path):
    task = NoProjectConsoleTask(tmp_path, '2025.1', OPEN)
    task.created_file.write_text(task.created_file.read_text().replace('v2025.1.0', 'v2021.1.0').replace('SchemaVersion="133"', 'SchemaVersion="103"'))
    task.expected_args['onMigrationRequired'] = 'migrate'
    preview = _console_load_preview(task, extra=('--value', 'migration_policy', 'migrate'))
    tx = _authorize_console_load(task, preview)
    code, executed = task.run('execute', tx)
    assert code == 0, executed
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified


@pytest.mark.parametrize('operation,version', [(operation, version) for operation in (CREATE, OPEN) for version in ('2021.1', '2022.1')])
def test_console_load_is_not_invented_in_older_unreflected_versions(tmp_path, operation, version):
    task = FieldTask(tmp_path, version, 'object.create')
    code, rejected = task.run('request-schema', operation)
    assert code == 2, rejected
    assert not task.calls


def test_console_native_absence_does_not_relax_other_cli_project_requirements(tmp_path):
    operation = 'ak.wwise.cli.verify'
    task = NoProjectConsoleTask(tmp_path, '2025.1', operation)
    code, rejected = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.project_file))
    assert code == 2, rejected
    assert not any(call[0] == operation for call in task.calls)
    assert not any(call[0].endswith('object.get') for call in task.calls)


@pytest.mark.parametrize('operation', [CREATE, OPEN])
def test_console_no_project_load_rejects_an_authoring_host_before_declaration(tmp_path, operation):
    task = NoProjectConsoleTask(tmp_path, '2025.1', operation)
    task.info_overrides['isCommandLine'] = False
    code, rejected = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.created_file))
    assert code == 2 and rejected['error_code'] == 'COMMAND_LINE_HOST_REQUIRED', rejected
    assert not any(call[0] == operation for call in task.calls)


def test_console_native_absence_rejects_timeout_even_with_native_error_attributes(tmp_path):
    task = NoProjectConsoleTask(tmp_path, '2025.1', OPEN, absence='timeout-with-native-attributes')
    code, rejected = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.created_file))
    assert code == 2, rejected
    assert not any(call[0] == OPEN for call in task.calls)


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
    ('2025.1', 'PluginMediaSource', 'plugin-conflicting-encodings'),
    ('2025.1', 'PluginMediaSource', 'plugin-value-list'),
    *[(version, 'AudioFileSource', 'serialization') for version in ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1']],
    *[(version, 'AudioFileSource', 'plugin-lists-reorder')
      for version in ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1']],
    *[('2021.1', 'AudioFileSource', 'plugin-lists-' + fault) for fault in
      ['effect-owner', 'inner-order', 'value', 'id', 'type', 'member-loss', 'list-loss',
       'duplicate', 'unnamed', 'list-attribute', 'container-attribute', 'list-text',
       'container-text', 'unknown-member', 'unknown-container', 'unknown-unchanged']],
    *[('2021.1', 'AudioFileSource', change) for change in
      ['serialization-rtpc', 'serialization-rtpc-change', 'serialization-rtpc-remove']],
    *[('2022.1', 'AudioFileSource', change) for change in
      ['bus-empty-reference', 'bus-nonempty-reference', 'bus-attributed-reference', 'bus-text-reference', 'other-empty-reference']],
    *[('2025.1', 'AudioFileSource', 'serialization-' + fault) for fault in
      ['value', 'platform', 'dual', 'value-attribute', 'reference', 'reference-attribute']],
    *[('2025.1', 'AudioFileSource', change) for change in ['media-id', 'source-id', 'filename',
        'language-id', 'other-language', 'duplicate-source', 'duplicate-media', 'missing-media',
        'mode-unchanged', 'work-unit-ids-remain', 'unrelated-property', 'unrelated-same-name-property']],
])
def test_cli_media_id_move_verifies_exact_source_mapping_and_storage_mode(tmp_path, version, source_kind, change, media_id_product_capture):
    class MoveMediaTask(CliProjectTask):
        def __init__(self, *args, **kwargs):
            self.public_invocations = []
            self.native_observations = []
            super().__init__(*args, **kwargs)

        def run(self, *argv):
            code, payload = super().run(*argv)
            self.public_invocations.append({'argv': ['--state-dir', str(self.path / 'state'), *argv],
                'exit_code': code, 'payload': deepcopy(payload)})
            return code, payload

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
                if change and change.startswith('serialization'):
                    field = tree.find('.//Sound/PropertyList/Property[@Name="PlainScalar"]')
                    value = field.attrib.pop('Value')
                    nested = ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value')
                    nested.text = '42' if change == 'serialization-value' else value
                    if change == 'serialization-rtpc-change':
                        field.find('.//Point/YPos').text = '99'
                    elif change == 'serialization-rtpc-remove':
                        field.remove(field.find('RTPCList'))
                    if change == 'serialization-platform':
                        nested.set('Platform', 'Windows')
                    elif change == 'serialization-dual':
                        field.set('Value', '42')
                    elif change == 'serialization-value-attribute':
                        nested.set('Unestablished', 'x')
                    slot = tree.find('.//EffectSlot')
                    slot.remove(slot.find('ReferenceList'))
                if change and (change.startswith('bus-') or change == 'other-empty-reference'):
                    owner = tree.find('.//Bus' if change.startswith('bus-') else './/Sound')
                    owner.remove(owner.find('ReferenceList'))
                if change and change.startswith('plugin-lists-'):
                    lists = tree.find('.//PluginInnerObjectList')
                    if lists is None:
                        lists = tree.find('.//UnrecognizedObjectList')
                    if change != 'plugin-lists-unknown-unchanged':
                        lists[:] = list(reversed(lists))
                    engine = lists.find('List[@Name="EngineSimulationControlData"]')
                    if change == 'plugin-lists-inner-order':
                        engine[:] = list(reversed(engine))
                    elif change == 'plugin-lists-value':
                        engine.find('.//Property').set('Value', '0.5')
                    elif change == 'plugin-lists-id':
                        engine[0].set('ID', '{BBBBBBBB-BBBB-CCCC-DDDD-EEEEEEEEEEEE}')
                    elif change == 'plugin-lists-type':
                        engine[0].set('PluginID', '418')
                    elif change == 'plugin-lists-member-loss':
                        engine.remove(engine[0])
                    elif change == 'plugin-lists-list-loss':
                        lists.remove(engine)
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
            result = super().call(uri, args, options)
            if uri == self.operation:
                self.native_observations.append({'uri': uri, 'args': deepcopy(args), 'options': deepcopy(options), 'result': deepcopy(result)})
            return result
    task = MoveMediaTask(tmp_path, version, 'ak.wwise.cli.moveMediaIdsToSingleFile',
        outcome=2 if source_kind == 'AudioFileSource' and change is None else 0)
    task.unit = saved_fixture_project(task)
    tree = ET.parse(task.unit)
    source = ET.SubElement(ET.SubElement(tree.find('.//Sound'), 'ChildrenList'),
        source_kind, Name='Renamed source', ID='{33333333-3333-3333-3333-333333333333}')
    if source_kind == 'PluginMediaSource':
        ET.SubElement(source, 'ParentPluginID').text = '27267154'
        field = ET.SubElement(ET.SubElement(source, 'PropertyList'), 'Property', Name='DataFileName', Type='string', Value='Keep.wav')
        if change in {'plugin-conflicting-encodings', 'plugin-value-list'}:
            if change == 'plugin-conflicting-encodings':
                field.set('Value', 'Other.wav')
            else:
                del field.attrib['Value']
            ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value').text = 'Keep.wav'
    else:
        ET.SubElement(source, 'Language').text = 'SFX'
        ET.SubElement(source, 'AudioFile' if source_kind == 'AudioFileSource' else 'MidiFile').text = 'Keep.wav'
    if change and change.startswith('plugin-lists-'):
        plugin = ET.SubElement(tree.find('.//Sound/ChildrenList'), 'SourcePlugin',
            Name='Chevrolet Camaro SS', ID='{29975930-6548-4A1B-BEE0-7AA549180D4F}',
            PluginName='CrankcaseAudio REV', CompanyID='261', PluginID='416')
        plugin.append(ET.fromstring('''<PluginInnerObjectList>
<List Name="EngineSimulationControlData">
<PluginInnerObject Name="" ID="{3A157243-6760-4CF8-B34C-310207907AEC}" PluginName="EngineSimulationControlData" CompanyID="261" PluginID="417"><PropertyList><Property Name="ClutchRPMSpike" Type="Real32" Value="0.66"/></PropertyList></PluginInnerObject>
<PluginInnerObject Name="" ID="{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}" PluginName="EngineSimulationControlData" CompanyID="261" PluginID="417"><PropertyList><Property Name="ClutchRPMSpike" Type="Real32" Value="0.77"/></PropertyList></PluginInnerObject>
</List>
<List Name="AccelDecelModelControlData"><PluginInnerObject Name="" ID="{CE8AB2CE-EA04-4B32-A673-7ED205ECADDC}" PluginName="AccelDecelModelControlData" CompanyID="261" PluginID="418"><PropertyList><Property Name="Acceleration" Type="Real32" Value="2"/></PropertyList></PluginInnerObject></List>
</PluginInnerObjectList>'''))
        lists = plugin.find('PluginInnerObjectList')
        if change == 'plugin-lists-effect-owner':
            plugin.tag = 'Effect'
        elif change == 'plugin-lists-duplicate':
            lists[1].set('Name', lists[0].get('Name'))
        elif change == 'plugin-lists-unnamed':
            del lists[0].attrib['Name']
        elif change == 'plugin-lists-list-attribute':
            lists[0].set('Unestablished', 'x')
        elif change == 'plugin-lists-container-attribute':
            lists.set('Unestablished', 'x')
        elif change == 'plugin-lists-list-text':
            lists[0].text = 'unestablished'
        elif change == 'plugin-lists-container-text':
            lists.text = 'unestablished'
        elif change == 'plugin-lists-unknown-member':
            lists[0][0].tag = 'UnrecognizedInnerObject'
        elif change in {'plugin-lists-unknown-container', 'plugin-lists-unknown-unchanged'}:
            lists.tag = 'UnrecognizedObjectList'
    if change and change.startswith('serialization'):
        ET.SubElement(tree.find('.//Sound/PropertyList'), 'Property', Name='PlainScalar', Type='Real32', Value='22.7')
        if change.startswith('serialization-rtpc'):
            scalar = tree.find('.//Sound/PropertyList/Property[@Name="PlainScalar"]')
            scalar.append(ET.fromstring('''<RTPCList><RTPC Name="" ID="{A75FFD27-F761-4E29-9666-2E85075CB99D}" ShortID="539810034">
<Curve Name="" ID="{B3F2A2A7-8634-4B8B-8203-B2F7BD38C9A8}"><PointList><Point><XPos>0</XPos><YPos>5</YPos><Flags>5</Flags></Point></PointList></Curve>
</RTPC></RTPCList>'''))
        references = ET.SubElement(ET.SubElement(tree.find('.//Sound'), 'EffectSlot'), 'ReferenceList')
        if change == 'serialization-reference':
            ET.SubElement(references, 'Reference', Name='Effect')
        elif change == 'serialization-reference-attribute':
            references.set('Unestablished', 'x')
    if change and (change.startswith('bus-') or change == 'other-empty-reference'):
        owner = (ET.SubElement(ET.SubElement(tree.getroot(), 'Busses'), 'Bus',
            Name='Ambience', ID='{2C5FE1AB-B90C-44C9-8760-CF255A4C9B62}')
            if change.startswith('bus-') else tree.find('.//Sound'))
        references = ET.SubElement(owner, 'ReferenceList')
        if change == 'bus-nonempty-reference':
            ET.SubElement(references, 'Reference', Name='OutputBus')
        elif change == 'bus-attributed-reference':
            references.set('Unestablished', 'x')
        elif change == 'bus-text-reference':
            references.text = 'unestablished'
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
    if change not in {None, 'already-central', 'mode-value-list', 'plugin-value-list', 'serialization', 'serialization-rtpc', 'bus-empty-reference',
            'plugin-lists-reorder', 'plugin-lists-effect-owner', 'plugin-lists-unknown-unchanged'}:
        assert code != 0 and payload['state'] == 'verification_failed', payload
        assert payload['verified'] is False
        if change == 'serialization-value':
            message = payload['verification']['message']
            assert 'failed verification' in message
            assert 'passed independent verification' not in message
            assert 'reported errors' not in message
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
    if source_kind == 'AudioFileSource' and change is None:
        from tests.support.media_id_branch_evidence import public_media_id_observation
        media_id_product_capture.update(public_media_id_observation(
            gateway=task.public_invocations[-1], public_invocations=task.public_invocations,
            native_observations=task.native_observations))


@pytest.fixture
def media_id_product_capture(request):
    import os
    from pathlib import Path
    observed = {}
    context_path = os.environ.get('WAAPI_MEDIA_ID_BRANCH_CAPTURE_CONTEXT')
    if context_path:
        from tests.support.media_id_branch_evidence import load_media_id_capture, finish_media_id_capture
        from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
        capture = load_media_id_capture(Path(context_path), request.node.nodeid)
        register_exact_evidence_finalizer(request.node, lambda reports: finish_media_id_capture(capture, reports, observed))
    return observed


@pytest.mark.parametrize('version,change', [
    *[(version, change) for version in ('2021.1', '2022.1', *VERSIONS)
        for change in (None, 'wrong-media-id', 'unrelated-property')],
    *[(version, 'default-elided') for version in ('2021.1', '2022.1', *VERSIONS)],
    ('2025.1', 'mode-unchanged'), ('2025.1', 'malformed-mode'), ('2025.1', 'duplicate-mode'),
])
def test_cli_media_id_transfer_back_verifies_central_records_in_work_units(tmp_path, version, change):
    class TransferBackTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                tree = ET.parse(self.unit)
                source = tree.find('.//AudioFileSource')
                ET.SubElement(ET.SubElement(source, 'MediaIDList'), 'MediaID',
                    ID='654321' if change == 'wrong-media-id' else '123456')
                if change == 'unrelated-property':
                    tree.find('.//Sound/PropertyList/Property/ValueList/Value').text = '-12'
                tree.write(self.unit)
                tree = ET.parse(self.project_file)
                if change != 'mode-unchanged':
                    tree.find('.//Property[@Name="MediaIDsInSingleFile"]/ValueList/Value').text = 'False'
                if change == 'default-elided':
                    properties = tree.find('./ProjectInfo/Project/PropertyList')
                    properties.remove(properties.find('./Property[@Name="MediaIDsInSingleFile"]'))
                elif change == 'malformed-mode':
                    tree.find('.//Property[@Name="MediaIDsInSingleFile"]/ValueList/Value').text = 'unknown'
                elif change == 'duplicate-mode':
                    properties = tree.find('./ProjectInfo/Project/PropertyList')
                    properties.append(deepcopy(properties.find('./Property[@Name="MediaIDsInSingleFile"]')))
                tree.write(self.project_file)
                # The native contract requires transfer, not deletion of the
                # inactive central file. Both retained and absent are permitted.
                if version == '2025.1':
                    self.project_file.with_suffix('.mediaid').unlink()
            return super().call(uri, args, options)

    task = TransferBackTask(tmp_path, version, 'ak.wwise.cli.moveMediaIdsToWorkUnits')
    task.unit = saved_fixture_project(task)
    tree = ET.parse(task.unit)
    source = ET.SubElement(ET.SubElement(tree.find('.//Sound'), 'ChildrenList'),
        'AudioFileSource', Name='Renamed source', ID='{33333333-3333-3333-3333-333333333333}')
    ET.SubElement(source, 'Language').text = 'SFX'
    ET.SubElement(source, 'AudioFile').text = 'Keep.wav'
    tree.write(task.unit)
    tree = ET.parse(task.project_file)
    field = ET.SubElement(tree.find('./ProjectInfo/Project/PropertyList'), 'Property',
        Name='MediaIDsInSingleFile', Type='bool')
    ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value').text = 'True'
    tree.write(task.project_file)
    task.project_file.with_suffix('.mediaid').write_text('''<WwiseDocument Type="MediaIDs"><MediaIDInfo><MediaIDs>
<Language ID="393239870" Name="SFX"><File Name="Keep.wav"><WObject ID="{33333333-3333-3333-3333-333333333333}">
<MediaID ID="123456"/></WObject></File></Language></MediaIDs></MediaIDInfo></WwiseDocument>''')
    if version in ('2021.1', '2022.1', '2023.1'):
        task.result_payload = {}
    code, schema = task.run('request-schema', task.operation)
    assert code == 0, schema
    assert schema['business_adapter']['effect_verification']['central_mapping_record_representation'] == (
        'Preview_central_records_equal_resulting_Work_Unit_source_GUID_language_file_and_all_media_ID_attributes; '
        'exact_disabled_project_storage_mode; central_file_removal_not_required')
    tx = task.execute_plan()
    before = len(task.calls)
    code, payload = task.run('verify', tx)
    assert payload['verified'] is (change in (None, 'default-elided')), payload
    assert (code == 0) is (change in (None, 'default-elided')), payload
    assert payload['state'] == ('verified' if change in (None, 'default-elided') else 'verification_failed'), payload
    if change in (None, 'default-elided'):
        observation = next(row for row in payload['verification']['readbacks']
            if row.get('kind') == 'cli-media-id-artifacts')
        assert observation['work_unit_media_id_count_before'] == 0
        assert observation['work_unit_media_id_count_after'] == 1
        assert observation['unresolved'] == []
        if change == 'default-elided':
            assert observation['project_storage_mode_after']['representation'] == 'default_elided'
            assert observation['project_storage_mode_after']['source']['version'] == version
    assert not any(row[0].endswith('object.get') for row in task.calls[before:])
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version,change', [
    *[(version, change) for version in ('2021.1', '2022.1', *VERSIONS)
        for change in (None, 'wrong-media-id', 'unrelated-property')],
    *[('2025.1', change) for change in
        ('work-unit-id', 'storage-mode', 'missing-existing-file', 'already-central')],
])
def test_cli_media_id_refresh_matches_saved_source_records_and_preserves_work_units(tmp_path, version, change):
    class RefreshTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                self.project_file.with_suffix('.mediaid').write_text('''<WwiseDocument Type="MediaIDs"><MediaIDInfo><MediaIDs>
<Language ID="393239870" Name="SFX"><File Name="Keep.wav"><WObject ID="{33333333-3333-3333-3333-333333333333}">
<MediaID ID="123456"/><Hash Platform="Windows" Value="3181527220"/>
</WObject></File></Language></MediaIDs></MediaIDInfo></WwiseDocument>''')
                if change == 'wrong-media-id':
                    mapping = self.project_file.with_suffix('.mediaid')
                    mapping.write_text(mapping.read_text().replace('123456', '654321'))
                elif change == 'unrelated-property':
                    tree = ET.parse(self.unit)
                    tree.find('.//Sound/PropertyList/Property/ValueList/Value').text = '-12'
                    tree.write(self.unit)
                elif change == 'work-unit-id':
                    tree = ET.parse(self.unit)
                    tree.find('.//MediaID').set('ID', '654321')
                    tree.write(self.unit)
                elif change == 'storage-mode':
                    tree = ET.parse(self.project_file)
                    tree.find('.//Property[@Name="MediaIDsInSingleFile"]/ValueList/Value').text = 'True'
                    tree.write(self.project_file)
                elif change == 'missing-existing-file':
                    self.project_file.with_suffix('.mediaid').unlink()
            return super().call(uri, args, options)

    task = RefreshTask(tmp_path, version, 'ak.wwise.cli.updateMediaIdsInSingleFile')
    task.unit = saved_fixture_project(task)
    tree = ET.parse(task.unit)
    source = ET.SubElement(ET.SubElement(tree.find('.//Sound'), 'ChildrenList'),
        'AudioFileSource', Name='Renamed source', ID='{33333333-3333-3333-3333-333333333333}')
    ET.SubElement(source, 'Language').text = 'SFX'
    ET.SubElement(source, 'AudioFile').text = 'Keep.wav'
    ET.SubElement(ET.SubElement(source, 'MediaIDList'), 'MediaID', ID='123456')
    tree.write(task.unit)
    tree = ET.parse(task.project_file)
    field = ET.SubElement(tree.find('./ProjectInfo/Project/PropertyList'), 'Property',
        Name='MediaIDsInSingleFile', Type='bool')
    ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value').text = 'False'
    tree.write(task.project_file)
    # An existing stale file is refreshed from the saved project records;
    # matching its own old rows would be a false success.
    task.project_file.with_suffix('.mediaid').write_text('''<WwiseDocument Type="MediaIDs"><MediaIDInfo><MediaIDs>
<Language ID="393239870" Name="SFX"><File Name="Stale.wav"><WObject ID="{44444444-4444-4444-4444-444444444444}">
<MediaID ID="654321"/></WObject></File></Language></MediaIDs></MediaIDInfo></WwiseDocument>''')
    if change == 'already-central':
        tree = ET.parse(task.unit)
        source = tree.find('.//AudioFileSource')
        source.remove(source.find('MediaIDList'))
        tree.write(task.unit)
        tree = ET.parse(task.project_file)
        tree.find('.//Property[@Name="MediaIDsInSingleFile"]/ValueList/Value').text = 'True'
        tree.write(task.project_file)
        task.project_file.with_suffix('.mediaid').write_text('''<WwiseDocument Type="MediaIDs"><MediaIDInfo><MediaIDs>
<Language ID="393239870" Name="SFX"><File Name="Keep.wav"><WObject ID="{33333333-3333-3333-3333-333333333333}">
<MediaID ID="123456"/></WObject></File></Language></MediaIDs></MediaIDInfo></WwiseDocument>''')
    if version in ('2021.1', '2022.1', '2023.1'):
        task.result_payload = {}
    code, schema = task.run('request-schema', task.operation)
    assert code == 0, schema
    assert schema['business_adapter']['effect_verification']['central_mapping_record_representation'] == (
        'existing_file_matches_exact_saved_source_media_records; already_central_uses_Preview_records; '
        'Work_Unit_media_and_storage_mode_preserved; absent_file_stays_absent')
    tx = task.execute_plan()
    before = len(task.calls)
    code, payload = task.run('verify', tx)
    expected_success = change in (None, 'already-central')
    assert payload['verified'] is expected_success, payload
    assert (code == 0) is expected_success, payload
    assert payload['state'] == ('verified' if expected_success else 'verification_failed'), payload
    if expected_success:
        observation = next(row for row in payload['verification']['readbacks']
            if row.get('kind') == 'cli-media-id-artifacts')
        assert observation['mapping_file']['media_count'] == 1
        assert observation['work_unit_media_id_count_before'] == observation['work_unit_media_id_count_after'] == (
            0 if change == 'already-central' else 1)
        assert observation['unresolved'] == []
    assert not any(row[0].endswith('object.get') for row in task.calls[before:])
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version,change', [
    *[(version, None) for version in ('2021.1', '2022.1', *VERSIONS)],
    ('2025.1', 'unexpected-file'), ('2025.1', 'changed-work-unit-id'),
])
def test_cli_media_id_refresh_without_existing_file_is_a_preserving_noop(tmp_path, version, change):
    class MissingMappingTask(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                if change == 'unexpected-file':
                    self.project_file.with_suffix('.mediaid').write_text('''<WwiseDocument Type="MediaIDs">
<MediaIDInfo><MediaIDs/></MediaIDInfo></WwiseDocument>''')
                elif change == 'changed-work-unit-id':
                    tree = ET.parse(self.unit)
                    tree.find('.//MediaID').set('ID', '654321')
                    tree.write(self.unit)
            return super().call(uri, args, options)

    task = MissingMappingTask(tmp_path, version, 'ak.wwise.cli.updateMediaIdsInSingleFile')
    task.unit = saved_fixture_project(task)
    tree = ET.parse(task.unit)
    source = ET.SubElement(ET.SubElement(tree.find('.//Sound'), 'ChildrenList'),
        'AudioFileSource', Name='Keep source', ID='{33333333-3333-3333-3333-333333333333}')
    ET.SubElement(source, 'Language').text = 'SFX'
    ET.SubElement(source, 'AudioFile').text = 'Keep.wav'
    ET.SubElement(ET.SubElement(source, 'MediaIDList'), 'MediaID', ID='123456')
    tree.write(task.unit)
    if version in ('2021.1', '2022.1', '2023.1'):
        task.result_payload = {}
    tx = task.execute_plan()
    before = len(task.calls)
    code, payload = task.run('verify', tx)
    assert payload['verified'] is (change is None), payload
    assert (code == 0) is (change is None), payload
    assert payload['state'] == ('verified' if change is None else 'verification_failed'), payload
    if change is None:
        observation = next(row for row in payload['verification']['readbacks']
            if row.get('kind') == 'cli-media-id-artifacts')
        assert observation['mapping_file']['exists'] is False
        assert observation['work_unit_media_id_count_before'] == observation['work_unit_media_id_count_after'] == 1
        assert observation['unresolved'] == []
    assert not any(row[0].endswith('object.get') for row in task.calls[before:])
    code, payload = task.run('execute', tx)
    assert code != 0, payload
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


@pytest.mark.parametrize('case', ['verified', 'unresolved', 'artifact-failure', 'native-errors'])
def test_console_verification_summary_distinguishes_process_result_and_effects(tmp_path, case):
    operation = {'verified': 'addNewPlatform', 'unresolved': 'migrate',
                 'artifact-failure': 'dumpObjects', 'native-errors': 'migrate'}[case]
    task = CliProjectTask(tmp_path, '2025.1', 'ak.wwise.cli.' + operation,
                          outcome=1 if case == 'native-errors' else 2)
    extra = ('--value', 'base_platform', 'Windows') if case == 'verified' else (
        ('--value', 'output_file', str(tmp_path / 'missing.json')) if case == 'artifact-failure' else ())
    transaction = task.execute_plan(*extra)
    code, payload = task.run('verify', transaction)
    message = payload['verification']['message']
    if case == 'verified':
        assert code == 0 and payload['verified'] is True
        assert 'passed independent verification' in message
        assert 'remain unverified' not in message
    elif case == 'unresolved':
        assert code == 0 and payload['verified'] is False
        assert 'remain unverified' in message
    elif case == 'artifact-failure':
        assert code != 0 and payload['verified'] is False
        assert 'reported errors' not in message
        assert 'failed verification' in message
    else:
        assert code != 0 and payload['verified'] is False
        assert 'reported errors' in message and 'partial effects' in message
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


class NoneStateMediaTask(CliProjectTask):
    """The saved native shape: four tracks, three old overrides, one group None."""
    group_id = '{AF599241-DE64-4286-BB8B-B0260EE20B80}'
    none_id = '{4BA09D62-D59B-4880-A78C-8BECE7D7899F}'
    states = [('a_Stealth', '{10000000-0000-0000-0000-000000000001}'),
              ('b_Stress', '{10000000-0000-0000-0000-000000000002}'),
              ('c_Fight', '{10000000-0000-0000-0000-000000000003}')]

    def __init__(self, path, version, change=None, owner_count=4, owner_name_bytes=0):
        self.change = change
        self.owner_count = owner_count
        super().__init__(path, version, 'ak.wwise.cli.moveMediaIdsToSingleFile')
        self.unit = saved_fixture_project(self)
        tree = ET.parse(self.unit)
        source = ET.SubElement(ET.SubElement(tree.find('.//Sound'), 'ChildrenList'),
            'AudioFileSource', Name='Keep', ID='{33333333-3333-3333-3333-333333333333}')
        ET.SubElement(source, 'Language').text = 'SFX'
        ET.SubElement(source, 'AudioFile').text = 'Keep.wav'
        ET.SubElement(ET.SubElement(source, 'MediaIDList'), 'MediaID', ID='123456')
        children = tree.find('.//WorkUnit/ChildrenList')
        for index in range(owner_count):
            track = ET.SubElement(children, 'MusicTrack', Name='Track ' + str(index) + 'x' * owner_name_bytes,
                ID='{20000000-0000-0000-0000-%012X}' % index)
            info = ET.SubElement(track, 'StateInfo')
            group = ET.SubElement(ET.SubElement(info, 'StateGroupList'), 'StateGroupInfo')
            ET.SubElement(group, 'StateGroupRef', Name='Music_inGame', ID=self.group_id)
            custom = ET.SubElement(info, 'CustomStateList')
            for number, (name, state_id) in enumerate(self.states):
                row = ET.SubElement(custom, 'CustomState')
                ET.SubElement(row, 'StateRef', Name=name, ID=state_id)
                inner = ET.SubElement(row, 'CustomState', Name='',
                    ID='{30000000-0000-0000-%04X-%012X}' % (index, number), ShortID=str(number + 1))
                ET.SubElement(ET.SubElement(inner, 'PropertyList'), 'Property', Name='Volume', Type='Real64', Value=str(-number))
        tree.write(self.unit)
        self.state_unit = self.project_file.parent / 'States' / 'States.wwu'
        self.state_unit.parent.mkdir()
        doc = ET.Element('WwiseDocument', Type='WorkUnit', WwiseVersion='v' + version + '.0')
        unit = ET.SubElement(ET.SubElement(doc, 'States'), 'WorkUnit', Name='States',
            ID='{40000000-0000-0000-0000-000000000000}')
        group = ET.SubElement(ET.SubElement(unit, 'ChildrenList'), 'StateGroup', Name='Music_inGame', ID=self.group_id)
        children = ET.SubElement(group, 'ChildrenList')
        for name, state_id in [('None', self.none_id), *self.states]:
            ET.SubElement(children, 'State', Name=name, ID=state_id)
        if change == 'before-group-duplicate':
            unit.find('ChildrenList').append(deepcopy(group))
        elif change == 'before-none-duplicate':
            children.append(deepcopy(children[0]))
        elif change == 'before-none-hidden-payload':
            ET.SubElement(children[0], 'PropertyList')
        elif change == 'before-none-wrong-class':
            children[0].tag = 'CustomState'
        ET.ElementTree(doc).write(self.state_unit)
        tree = ET.parse(self.unit)
        for track in tree.findall('.//MusicTrack'):
            info = track.find('StateInfo')
            if change == 'before-unknown-owner':
                track.tag = 'UnprovedOwner'
            elif change == 'before-duplicate-subscription':
                groups = info.find('StateGroupList')
                groups.append(deepcopy(groups[0]))
            elif change == 'before-unknown-info':
                ET.SubElement(info, 'UnknownPayload')
            elif change == 'before-hidden-state-properties':
                ET.SubElement(ET.SubElement(info, 'StatePropertyList'), 'UnprovedPayload')
            elif change == 'before-hidden-old-custom-state':
                ET.SubElement(info.find('./CustomStateList/CustomState/CustomState'), 'UnprovedPayload')
            elif change == 'before-group-ref-name':
                info.find('.//StateGroupRef').set('Name', 'Other')
            elif change == 'before-group-ref-hidden':
                ET.SubElement(info.find('.//StateGroupRef'), 'Hidden')
            elif change == 'before-group-ref-work-unit':
                info.find('.//StateGroupRef').set('WorkUnitID', '{99999999-0000-0000-0000-000000000000}')
            elif change == 'missing-list':
                info.remove(info.find('CustomStateList'))
            elif change == 'bare-none-ref':
                ET.SubElement(ET.SubElement(info.find('CustomStateList'), 'CustomState'),
                    'StateRef', Name='None', ID=self.none_id)
            elif change == 'source-owner-ActorMixer':
                track.tag = 'ActorMixer'
            elif change == 'source-owner-PropertyContainer':
                track.tag = 'PropertyContainer'
            elif change == 'source-owner-EffectSlot':
                track.tag = 'EffectSlot'
            if change in {'group-info-object', 'group-info-object-hidden'}:
                nested = ET.SubElement(info.find('./StateGroupList/StateGroupInfo'), 'StateGroupInfo',
                    Name='', ID=track.get('ID').replace('20000000', '60000000'), ShortID='1')
                if change == 'group-info-object-hidden':
                    ET.SubElement(nested, 'UnprovedPayload')
            if version != '2025.1':
                info.find('./StateGroupList/StateGroupInfo').set('MusicSyncType', '2')
        if change == 'unrelated-plugin':
            plugin = ET.SubElement(tree.find('.//Sound/ChildrenList'), 'SourcePlugin',
                Name='REV', ID='{70000000-0000-0000-0000-000000000000}')
            ET.SubElement(plugin, 'PluginData')
        elif change == 'unrelated-soundcaster':
            session = ET.SubElement(ET.SubElement(tree.getroot(), 'SoundcasterSessions'), 'SoundcasterSession',
                Name='Preserved session', ID='{80000000-0000-0000-0000-000000000000}', ShowAll='true')
            for tag in ('RTPCValueList', 'CurrentStateList', 'CurrentSwitchList'):
                ET.SubElement(session, tag)
        tree.write(self.unit)

    def run(self, *argv):
        code, payload = super().run(*argv)
        if argv[0] == 'preview-from-draft':
            self.public_preview = deepcopy(payload)
        return code, payload

    def call(self, uri, args=None, options=None):
        if uri == self.operation:
            self.project_file.with_suffix('.mediaid').write_text('''<WwiseDocument Type="MediaIDs"><MediaIDInfo><MediaIDs>
<Language ID="393239870" Name="SFX"><File Name="Keep.wav"><WObject ID="{33333333-3333-3333-3333-333333333333}"><MediaID ID="123456"/></WObject></File></Language>
</MediaIDs></MediaIDInfo></WwiseDocument>''')
            tree = ET.parse(self.unit)
            source = tree.find('.//AudioFileSource')
            source.remove(source.find('MediaIDList'))
            if self.change == 'missing-list':
                for info in tree.findall('.//StateInfo'):
                    ET.SubElement(info, 'CustomStateList')
            for index, custom in enumerate(tree.findall('.//StateInfo/CustomStateList')):
                if self.change == 'no-additions':
                    continue
                row = (next(n for n in custom if n.find('StateRef').get('Name') == 'None')
                    if self.change == 'bare-none-ref' else ET.Element('CustomState'))
                if self.change != 'bare-none-ref':
                    ET.SubElement(row, 'StateRef', Name='None', ID=self.none_id)
                ET.SubElement(row, 'CustomState', Name='',
                    ID='{50000000-0000-0000-0000-%012X}' % index, ShortID='1')
                if self.change != 'bare-none-ref':
                    custom.insert(1, row)
            first = tree.find('.//StateInfo/CustomStateList')
            added = next((n for n in first if n.find('StateRef').get('Name') == 'None'), None) if first is not None else None
            if added is not None:
                inner = added.find('CustomState')
                if self.change == 'wrong-state':
                    added.find('StateRef').set('ID', self.states[0][1])
                elif self.change == 'wrong-state-name':
                    added.find('StateRef').set('Name', 'Different')
                elif self.change == 'wrong-work-unit':
                    added.find('StateRef').set('WorkUnitID', 'broken')
                elif self.change == 'wrong-class':
                    inner.tag = 'Sound'
                elif self.change == 'nonempty':
                    ET.SubElement(inner, 'PropertyList')
                elif self.change == 'hidden-attribute':
                    inner.set('Unproved', 'x')
                elif self.change == 'hidden-text':
                    added.text = 'hidden'
                elif self.change == 'duplicate-new':
                    first.append(deepcopy(added))
                elif self.change == 'invalid-guid':
                    inner.set('ID', 'broken')
                elif self.change == 'zero-guid':
                    inner.set('ID', '{00000000-0000-0000-0000-000000000000}')
                elif self.change == 'old-guid':
                    inner.set('ID', first[0].find('CustomState').get('ID'))
                elif self.change == 'invalid-short-id':
                    inner.set('ShortID', '4294967296')
                elif self.change == 'no-short-id':
                    del inner.attrib['ShortID']
                elif self.change == 'new-external-reference':
                    states = ET.parse(self.state_unit)
                    ET.SubElement(states.getroot(), 'ObjectRef', Name='', ID=inner.get('ID').lower())
                    states.write(self.state_unit)
                elif self.change == 'old-state-change':
                    first[0].find('.//Property').set('Value', '12')
                elif self.change == 'old-state-order':
                    first[:] = list(reversed(first))
                elif self.change == 'old-state-loss':
                    first.remove(first[0])
                elif self.change == 'wrong-owner':
                    tree.find('.//MusicTrack').set('ID', '{99999999-0000-0000-0000-000000000001}')
                elif self.change == 'wrong-group':
                    tree.find('.//StateGroupRef').set('ID', '{99999999-0000-0000-0000-000000000002}')
                elif self.change == 'unrelated-plugin':
                    ET.SubElement(tree.find('.//SourcePlugin/PluginData'), 'Added').text = 'native changed cached data'
                elif self.change == 'unrelated-soundcaster':
                    session = tree.find('.//SoundcasterSession')
                    for tag in ('RTPCValueList', 'CurrentStateList', 'CurrentSwitchList'):
                        session.remove(session.find(tag))
            tree.write(self.unit)
            project = ET.parse(self.project_file)
            ET.SubElement(project.find('./ProjectInfo/Project/PropertyList'), 'Property',
                Name='MediaIDsInSingleFile', Type='bool', Value='True')
            project.write(self.project_file)
            if self.change == 'unknown-mapping':
                self.project_file.with_suffix('.mediaid').write_text('<UnestablishedMapping/>')
        return super().call(uri, args, options)


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_media_single_discloses_and_reports_optional_none_state_objects(tmp_path, version):
    task = NoneStateMediaTask(tmp_path, version)
    tx = task.execute_plan()
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    prepared = shown['artifact']['prepared_operation']
    outcome = prepared['semantic_preview']['envelope']['metadata']['optional_none_state_materialization']
    assert outcome['may_materialize_saved_internal_records'] is True
    assert outcome['inevitable'] is False
    assert outcome['force_save_scope'] == 'all_project_work_units'
    assert outcome['source']['version'] == version
    assert outcome['eligible_binding_count'] == 4
    assert task.public_preview['preview_summary']['optional_none_state_materialization'] == outcome
    assert outcome['relationships_complete'] is True
    assert {row['none_state']['id'] for row in outcome['eligible_groups']} == {task.none_id}
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is True, payload
    observations = payload['verification'].get('readbacks',
        payload['verification'].get('optional_none_state_materialization', []))
    if isinstance(observations, dict):
        assert observations['actual_additions_complete'] is False
        observed, count, _, _ = collect_none_state_pages(task, observations['detail'])
        assert count == 4
    else:
        observed = next(row for row in observations
            if row.get('kind') == 'optional-none-custom-state-materialization')
    assert len(observed['actual_additions']) == 4
    assert observed['remaining_model_preserved'] is True
    assert {row['object']['id'] for row in observed['actual_additions']} == {
        '{50000000-0000-0000-0000-%012X}' % index for index in range(4)}
    # ShortID 1 also occurs in old CustomStates. It is not globally unique.
    assert {row['object']['short_id'] for row in observed['actual_additions']} == {'1'}
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('change', ['wrong-state', 'wrong-state-name', 'wrong-work-unit', 'wrong-class',
    'nonempty', 'hidden-attribute', 'hidden-text', 'duplicate-new', 'invalid-guid', 'zero-guid',
    'old-guid', 'invalid-short-id', 'new-external-reference', 'old-state-change', 'old-state-order',
    'old-state-loss', 'wrong-owner', 'wrong-group', 'unrelated-plugin', 'unrelated-soundcaster',
    'before-group-duplicate', 'before-none-duplicate', 'before-none-hidden-payload', 'before-none-wrong-class',
    'before-unknown-owner', 'before-duplicate-subscription', 'before-unknown-info', 'before-group-ref-name',
    'before-group-ref-hidden', 'before-group-ref-work-unit',
    'before-hidden-state-properties', 'before-hidden-old-custom-state'])
def test_media_single_none_outcome_never_masks_unproved_model_change(tmp_path, change):
    task = NoneStateMediaTask(tmp_path, '2024.1' if change in {'unrelated-plugin', 'unrelated-soundcaster'} else '2023.1', change)
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'verification_failed', payload
    assert payload['verified'] is False
    assert any(not row['passed'] for row in payload['verification']['assertions'])
    code, repeated = task.run('execute', tx)
    assert code != 0, repeated
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('change', ['no-additions', 'no-short-id', 'missing-list', 'bare-none-ref'])
def test_media_single_none_optional_source_shapes_preserve_exact_remaining_model(tmp_path, version, change):
    task = NoneStateMediaTask(tmp_path, version, change)
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is True, payload
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    verification = next(event['details']['verification'] for event in shown['events']
        if event['event_type'] == 'verification_recorded')
    observed = next(row for row in verification['readbacks']
        if row.get('kind') == 'optional-none-custom-state-materialization')
    assert observed['actual_addition_count'] == (0 if change == 'no-additions' else 4)
    assert observed['actual_additions_complete'] is True
    assert observed['remaining_model_preserved'] is True
    if change == 'missing-list':
        assert all(row['created_custom_state_list'] for row in observed['actual_additions'])


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('owner', ['ActorMixer', 'PropertyContainer', 'EffectSlot'])
def test_media_single_none_owner_classes_follow_matching_source_lane(tmp_path, version, owner):
    allowed = ((owner == 'ActorMixer' and version != '2025.1')
        or (owner == 'PropertyContainer' and version == '2025.1')
        or (owner == 'EffectSlot' and version not in {'2021.1', '2022.1'}))
    task = NoneStateMediaTask(tmp_path, version, 'source-owner-' + owner)
    tx = task.execute_plan()
    notice = task.public_preview['preview_summary']['optional_none_state_materialization']
    assert notice['eligible_binding_count'] == (4 if allowed else 0)
    code, payload = task.run('verify', tx)
    assert (code == 0 and payload['verified'] is True) is allowed, payload


def collect_none_state_pages(task, command):
    """Follow only the produced fixed read continuations and reconstruct JSON."""
    calls_before = deepcopy(task.calls)
    entries, offset, scope, value_sha, total = [], 0, None, None, None
    for _ in range(1000):
        code, payload = task.run(*command['gateway_argv'])
        assert code == 0, payload
        assert 'confirmation' not in payload and 'authorization' not in payload
        assert len(json.dumps(payload, ensure_ascii=False, indent=2).encode()) <= 32768
        page = payload['none_state_outcome']
        assert page['mutation_authority'] is False and len(page['entries']) <= 64
        assert page['offset'] == offset
        if scope is None:
            scope, value_sha, total = page['scope'], page['value_sha256'], page['total_count']
        assert page['scope'] == scope and page['value_sha256'] == value_sha and page['total_count'] == total
        entries.extend(page['entries'])
        offset += len(page['entries'])
        if page['complete']:
            assert page['remaining_entries'] == 0 and page['next_page'] is None
            assert 'next_command' not in payload
            break
        command = payload['next_command']
        assert command['command'] == 'transaction-show'
        assert '--none-state-outcome' in command['gateway_argv'] and '--outcome-page' in command['gateway_argv']
        assert command['full_argv'][3:5] == ['--state-dir', str(task.path / 'state')]
    else:
        pytest.fail('Bounded outcome pages did not terminate')
    # Independently reconstruct the existing lossless pointer/string format.
    root = None
    for row in entries:
        parts = [part.replace('~1', '/').replace('~0', '~') for part in row['pointer'].split('/')[1:]]
        parent = root
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = (int(parts[-1]) if isinstance(parent, list) else parts[-1]) if parts else None
        if row['kind'] == 'object':
            value = {}
        elif row['kind'] == 'array':
            value = [None] * row['length']
        elif row['kind'] == 'string-fragment':
            previous = parent[key] if row['offset'] else ''
            assert len(previous) == row['offset']
            value = previous + row['value']
        else:
            value = row['value']
        if parts:
            parent[key] = value
        else:
            root = value
    from wwise_waapi.canonical import canonical_json_bytes
    import hashlib
    assert hashlib.sha256(canonical_json_bytes(root)).hexdigest() == value_sha
    assert task.calls == calls_before
    return root, total, scope, entries


def test_media_single_large_none_disclosures_offer_complete_public_detail(tmp_path, monkeypatch):
    from tests.unit.test_field_interface_closure_gateway import gateway
    captured = []
    original = gateway.project_successful_transaction_verify_payload
    def protect_agent_result(payload, **kwargs):
        before = deepcopy(payload['agent_result'])
        before_bytes = json.dumps(payload['agent_result'], ensure_ascii=False, separators=(',', ':')).encode()
        projected = original(payload, **kwargs)
        assert projected['agent_result'] == before
        assert json.dumps(projected['agent_result'], ensure_ascii=False, separators=(',', ':')).encode() == before_bytes
        assert list(projected)[-1] == 'agent_result'
        captured.append(True)
        return projected
    monkeypatch.setattr(gateway, 'project_successful_transaction_verify_payload', protect_agent_result)
    task = NoneStateMediaTask(tmp_path, '2023.1', owner_count=30)
    tx = task.execute_plan()
    notice = task.public_preview['preview_summary']['optional_none_state_materialization']
    assert notice['eligible_binding_count'] == 30 and notice['relationships_complete'] is False
    eligible, count, scope, _ = collect_none_state_pages(task, notice['detail'])
    assert count == 30 and scope['verification_event_hash'] is None
    assert {row['owner']['id'] for row in eligible['eligible_bindings']} == {
        '{20000000-0000-0000-0000-%012X}' % index for index in range(30)}
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is True, payload
    notice = payload['verification']['optional_none_state_materialization']
    assert notice['actual_addition_count'] == 30 and notice['actual_additions_complete'] is False
    observed, count, scope, _ = collect_none_state_pages(task, notice['detail'])
    assert count == 30 and scope['verification_event_hash'] is not None
    assert observed['actual_additions_complete'] is True
    assert {row['object']['id'] for row in observed['actual_additions']} == {
        '{50000000-0000-0000-0000-%012X}' % index for index in range(30)}
    assert len([row for row in task.calls if row[0] == task.operation]) == 1
    assert captured == [True]


def test_media_single_none_outcome_offline_pages_bind_exact_artifact_and_journal(tmp_path):
    task = NoneStateMediaTask(tmp_path, '2023.1', owner_count=4, owner_name_bytes=2200)
    code, payload = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.project_file))
    assert code == 0, payload
    code, payload = task.step('draft-check')
    assert code == 0, payload
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx, artifact_hash = preview['transaction_id'], preview['artifact_hash']
    notice = preview['preview_summary']['optional_none_state_materialization']
    eligible, count, scope, entries = collect_none_state_pages(task, notice['detail'])
    assert count == 4 and scope['artifact_hash'] == artifact_hash
    assert any(row['kind'] == 'string-fragment' for row in entries)
    assert [row['owner']['name'] for row in eligible['eligible_bindings']] == [
        'Track ' + str(index) + 'x' * 2200 for index in range(4)]
    assert not any(row[0] == task.operation for row in task.calls)
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    expected = shown['artifact']['prepared_operation']['pre_state']['cli_project_effect']['model_before'][
        'optional_none_state_materialization']
    assert eligible['eligible_bindings'] == expected['eligible_bindings']
    assert eligible['source'] == expected['source']
    # The fixed view has no mutation continuation, even while awaiting confirmation.
    for args in [[], ['--outcome-artifact-hash', '0' * 64]]:
        code, bad = task.run('transaction-show', tx, '--none-state-outcome', 'eligible-bindings', *args)
        assert code != 0 and 'confirmation' not in bad, bad
    code, payload = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, payload
    code, payload = task.run('execute', tx)
    assert code == 0, payload
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is True, payload
    actual_command = payload['verification']['optional_none_state_materialization']['detail']
    actual, count, _, _ = collect_none_state_pages(task, actual_command)
    assert count == 4 and len(actual['actual_additions']) == 4
    code, first = task.run(*notice['detail']['gateway_argv'])
    assert code == 0 and first['none_state_outcome']['next_page'], first
    cursor = first['none_state_outcome']['next_page']
    base = notice['detail']['gateway_argv']
    for argv in [base + ['--outcome-page', cursor[:-1] + ('0' if cursor[-1] != '0' else '1')],
                 base + ['--summary-only'],
                 actual_command['gateway_argv'] + ['--outcome-page', cursor],
                 ['transaction-show', tx, '--none-state-outcome', 'actual-additions',
                  '--outcome-artifact-hash', artifact_hash, '--outcome-event-hash', '0' * 64]]:
        code, bad = task.run(*argv)
        assert code != 0 and 'confirmation' not in bad, bad
    code, shown = task.run('transaction-show', tx)
    event = next(event for event in shown['events'] if event['event_type'] != 'verification_recorded')
    code, bad = task.run('transaction-show', tx, '--none-state-outcome', 'actual-additions',
        '--outcome-artifact-hash', artifact_hash, '--outcome-event-hash', event['event_hash'])
    assert code != 0, bad
    # A cursor from another exact transaction cannot select this transaction's rows.
    other_path = tmp_path / 'other'
    other_path.mkdir()
    other = NoneStateMediaTask(other_path, '2023.1', owner_count=4, owner_name_bytes=2200)
    other_tx = other.execute_plan()
    other_base = other.public_preview['preview_summary']['optional_none_state_materialization']['detail']['gateway_argv']
    code, bad = other.run(*other_base, '--outcome-page', cursor)
    assert code != 0, bad


@pytest.mark.parametrize('owner_count', [0, 1])
def test_media_single_none_outcome_empty_and_last_pages_are_complete_read_only(tmp_path, owner_count):
    task = NoneStateMediaTask(tmp_path, '2023.1', 'no-additions', owner_count=owner_count)
    tx = task.execute_plan()
    code, page = task.run('transaction-show', tx, '--none-state-outcome', 'eligible-bindings',
        '--outcome-artifact-hash', task.public_preview['artifact_hash'])
    assert code == 0, page
    assert page['none_state_outcome']['complete'] is True
    assert page['none_state_outcome']['total_count'] == owner_count
    assert 'next_command' not in page and 'confirmation' not in page
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is True, payload
    code, shown = task.run('transaction-show', tx)
    event = next(event for event in shown['events'] if event['event_type'] == 'verification_recorded')
    code, actual = task.run('transaction-show', tx, '--none-state-outcome', 'actual-additions',
        '--outcome-artifact-hash', task.public_preview['artifact_hash'], '--outcome-event-hash', event['event_hash'])
    assert code == 0 and actual['none_state_outcome']['total_count'] == 0, actual
    assert actual['none_state_outcome']['complete'] is True and 'next_command' not in actual


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_media_single_schema_discloses_fixed_outcome_detail_route(tmp_path, version):
    task = CliProjectTask(tmp_path, version, 'ak.wwise.cli.moveMediaIdsToSingleFile')
    code, schema = task.run('request-schema', task.operation)
    assert code == 0, schema
    effect = schema['business_adapter']['effect_verification']['optional_saved_none_state_materialization']
    assert effect['detail']['fixed_views'] == ['eligible-bindings', 'actual-additions']
    assert effect['source'] == 'resources/semantic/' + version + '/none_state_materialization.json'
    assert effect['inevitable'] is False


@pytest.mark.parametrize('boundary', ['unknown-mapping', 'native-error'])
def test_media_single_none_outcome_retains_weak_and_native_error_boundaries(tmp_path, boundary):
    task = NoneStateMediaTask(tmp_path, '2023.1', boundary)
    if boundary == 'native-error':
        task.outcome = 1
    tx = task.execute_plan()
    code, payload = task.run('verify', tx)
    assert payload['verified'] is False, payload
    assert payload['state'] == ('verification_failed' if boundary == 'native-error' else 'result_schema_checked')
    assert (code != 0) is (boundary == 'native-error')
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    event = next(row for row in shown['events'] if row['event_type'] == 'verification_recorded')
    observed = [row for row in event['details']['verification']['readbacks']
        if row.get('kind') == 'optional-none-custom-state-materialization']
    if boundary == 'native-error':
        assert not observed
        process = next(row for row in event['details']['verification']['readbacks'] if row.get('kind') == 'cli-process-outcome')
        assert process['partial_effects_possible'] is True
        code, page = task.run('transaction-show', tx, '--none-state-outcome', 'actual-additions',
            '--outcome-artifact-hash', shown['artifact_hash'], '--outcome-event-hash', event['event_hash'])
        assert code != 0, page
    else:
        assert observed[0]['actual_addition_count'] == 4 and observed[0]['remaining_model_preserved'] is True
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


def test_media_single_none_eligible_binding_drift_stops_before_dispatch(tmp_path):
    task = NoneStateMediaTask(tmp_path, '2023.1')
    code, payload = task.step('draft-declare-cli-console-plan', '--value', 'project_file', str(task.project_file))
    assert code == 0, payload
    code, payload = task.step('draft-check')
    assert code == 0, payload
    code, preview = task.step('preview-from-draft')
    assert code == 0, preview
    tx = preview['transaction_id']
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    code, payload = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, payload
    tree = ET.parse(task.state_unit)
    tree.find('.//State[@Name="None"]').set('ID', '{99999999-0000-0000-0000-000000000003}')
    tree.write(task.state_unit)
    code, payload = task.run('execute', tx)
    assert code != 0, payload
    assert not any(row[0] == task.operation for row in task.calls)


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_media_single_none_state_group_info_object_follows_exact_source_shape(tmp_path, version):
    task = NoneStateMediaTask(tmp_path, version, 'group-info-object')
    tx = task.execute_plan()
    notice = task.public_preview['preview_summary']['optional_none_state_materialization']
    assert notice['eligible_binding_count'] == (4 if version == '2025.1' else 0)
    code, payload = task.run('verify', tx)
    assert (code == 0 and payload['verified'] is True) is (version == '2025.1'), payload


def test_media_single_none_group_info_object_hidden_payload_is_not_eligible(tmp_path):
    task = NoneStateMediaTask(tmp_path, '2025.1', 'group-info-object-hidden')
    tx = task.execute_plan()
    assert task.public_preview['preview_summary']['optional_none_state_materialization']['eligible_binding_count'] == 0
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['verified'] is False, payload


def test_media_single_none_materialization_preserves_exact_native_2023_saved_state_shapes(tmp_path):
    # Offline source: retained933 before-image Music.wwu SHA256
    # 8d756edd197dfa12ac5e67101d0a735b79edd4113fc69fe312424d55d6edcd4d.
    # These are saved-model shapes, not a new native execution or PASS receipt.
    task = NoneStateMediaTask(tmp_path, '2023.1')
    bindings = [({'Name': 'Stealth', 'ID': '{9861812D-295E-47DC-BB84-803555479814}', 'ShortID': '904240640'},
      '<StateInfo><StateGroupList><StateGroupInfo><StateGroupRef Name="Music_inGame" '
      'ID="{AF599241-DE64-4286-BB8B-B0260EE20B80}" '
      '/></StateGroupInfo></StateGroupList><CustomStateList><CustomState><StateRef Name="c_Fight" '
      'ID="{20A3B196-D22F-42F7-8592-A37A3E5B467A}" /><CustomState Name="Custom State" '
      'ID="{4C10E9EB-9AC1-4134-93D8-5EF9364E4E06}" ShortID="315654336"><PropertyList><Property '
      'Name="Volume" Type="Real64" Value="-96.3" '
      '/></PropertyList></CustomState></CustomState><CustomState><StateRef Name="b_Stress" '
      'ID="{885FDC4C-AE0A-4B71-A9FB-82FBAE4A3270}" /><CustomState Name="Custom State" '
      'ID="{14476B77-B4F8-46AD-94A0-F4B77E3AE06E}" ShortID="798376448"><PropertyList><Property '
      'Name="Volume" Type="Real64" Value="-96.3" '
      '/></PropertyList></CustomState></CustomState><CustomState><StateRef Name="a_Stealth" '
      'ID="{43C6702F-3A30-4D5C-B16D-C862BE5989EF}" /><CustomState Name="" '
      'ID="{D1694BCE-4CF8-4523-A305-9FBCE115A4A5}" ShortID="826896996" '
      '/></CustomState></CustomStateList></StateInfo>'),
     ({'Name': 'Stress', 'ID': '{D80292EF-1987-4266-BE2E-F014E5B502C7}', 'ShortID': '740093312'},
      '<StateInfo><StateGroupList><StateGroupInfo><StateGroupRef Name="Music_inGame" '
      'ID="{AF599241-DE64-4286-BB8B-B0260EE20B80}" '
      '/></StateGroupInfo></StateGroupList><CustomStateList><CustomState><StateRef Name="c_Fight" '
      'ID="{20A3B196-D22F-42F7-8592-A37A3E5B467A}" /><CustomState Name="Custom State" '
      'ID="{7E6166E0-3BE3-4CE7-B8B8-F121790D6760}" ShortID="291287712"><PropertyList><Property '
      'Name="Volume" Type="Real64" Value="-96.3" '
      '/></PropertyList></CustomState></CustomState><CustomState><StateRef Name="b_Stress" '
      'ID="{885FDC4C-AE0A-4B71-A9FB-82FBAE4A3270}" /><CustomState Name="" '
      'ID="{B04BC407-C16D-4F40-A43A-E3146FCBD454}" ShortID="526775693" '
      '/></CustomState><CustomState><StateRef Name="a_Stealth" '
      'ID="{43C6702F-3A30-4D5C-B16D-C862BE5989EF}" /><CustomState Name="Custom State" '
      'ID="{8A9370DF-4DE2-4A95-897A-9B09DA0C1576}" ShortID="791280512"><PropertyList><Property '
      'Name="Volume" Type="Real64" Value="-96.3" '
      '/></PropertyList></CustomState></CustomState></CustomStateList></StateInfo>'),
     ({'Name': 'Stealth', 'ID': '{9DFD6677-5C7D-4928-969D-15DAB99D0A13}', 'ShortID': '683160055'},
      '<StateInfo><StateGroupList><StateGroupInfo><StateGroupRef Name="Music_inGame" '
      'ID="{AF599241-DE64-4286-BB8B-B0260EE20B80}" '
      '/></StateGroupInfo></StateGroupList><CustomStateList><CustomState><StateRef Name="c_Fight" '
      'ID="{20A3B196-D22F-42F7-8592-A37A3E5B467A}" /><CustomState Name="Custom State" '
      'ID="{8C7A076C-D063-4A1C-90E2-B255EE58FCDB}" ShortID="969400522"><PropertyList><Property '
      'Name="Volume" Type="Real64" Value="-96.3" '
      '/></PropertyList></CustomState></CustomState><CustomState><StateRef Name="b_Stress" '
      'ID="{885FDC4C-AE0A-4B71-A9FB-82FBAE4A3270}" /><CustomState Name="Custom State" '
      'ID="{A31D2C06-93F0-4B6F-849B-24319F8AC9DD}" ShortID="278624134"><PropertyList><Property '
      'Name="Volume" Type="Real64" Value="-96.3" '
      '/></PropertyList></CustomState></CustomState><CustomState><StateRef Name="a_Stealth" '
      'ID="{43C6702F-3A30-4D5C-B16D-C862BE5989EF}" /><CustomState Name="" '
      'ID="{26E60B22-7DC6-40F8-A871-76F31339288D}" ShortID="11996196" '
      '/></CustomState></CustomStateList></StateInfo>'),
     ({'Name': 'Stress', 'ID': '{517CE370-E59A-4B43-816C-E6156D8C71B1}', 'ShortID': '722825636'},
      '<StateInfo><StateGroupList><StateGroupInfo><StateGroupRef Name="Music_inGame" '
      'ID="{AF599241-DE64-4286-BB8B-B0260EE20B80}" '
      '/></StateGroupInfo></StateGroupList><CustomStateList><CustomState><StateRef Name="c_Fight" '
      'ID="{20A3B196-D22F-42F7-8592-A37A3E5B467A}" /><CustomState Name="Custom State" '
      'ID="{220040B4-E4CB-4D3C-B5FD-702BAA6231BA}" ShortID="119466417"><PropertyList><Property '
      'Name="Volume" Type="Real64" Value="-96.3" '
      '/></PropertyList></CustomState></CustomState><CustomState><StateRef Name="b_Stress" '
      'ID="{885FDC4C-AE0A-4B71-A9FB-82FBAE4A3270}" /><CustomState Name="" '
      'ID="{6DAFE3FC-6723-4268-AB25-23DB2AB01CD7}" ShortID="307726341" '
      '/></CustomState><CustomState><StateRef Name="a_Stealth" '
      'ID="{43C6702F-3A30-4D5C-B16D-C862BE5989EF}" /><CustomState Name="Custom State" '
      'ID="{C5103B10-17BF-46EB-AA29-57CB328AC250}" ShortID="660986203"><PropertyList><Property '
      'Name="Volume" Type="Real64" Value="-96.3" '
      '/></PropertyList></CustomState></CustomState></CustomStateList></StateInfo>')]
    tree = ET.parse(task.unit)
    for track, (attrs, state_info) in zip(tree.findall('.//MusicTrack'), bindings):
        track.attrib = attrs
        track.remove(track.find('StateInfo'))
        track.append(ET.fromstring(state_info))
    tree.write(task.unit)
    tree = ET.parse(task.state_unit)
    parent = tree.find('.//WorkUnit/ChildrenList')
    parent.remove(parent.find('StateGroup'))
    parent.append(ET.fromstring('<StateGroup Name="Music_inGame" ID="{AF599241-DE64-4286-BB8B-B0260EE20B80}"><PropertyList><Property Name="DefaultTransitionTime" Type="Real64" Value="2" /></PropertyList><ChildrenList><State Name="None" ID="{4BA09D62-D59B-4880-A78C-8BECE7D7899F}" /><State Name="a_Stealth" ID="{43C6702F-3A30-4D5C-B16D-C862BE5989EF}" /><State Name="b_Stress" ID="{885FDC4C-AE0A-4B71-A9FB-82FBAE4A3270}" /><State Name="c_Fight" ID="{20A3B196-D22F-42F7-8592-A37A3E5B467A}" /></ChildrenList><TransitionList><Transition><StartState Name="None" ID="{4BA09D62-D59B-4880-A78C-8BECE7D7899F}" /><EndState Name="a_Stealth" ID="{43C6702F-3A30-4D5C-B16D-C862BE5989EF}" /><Time>0</Time><IsShared>false</IsShared></Transition><Transition><StartState Name="None" ID="{4BA09D62-D59B-4880-A78C-8BECE7D7899F}" /><EndState Name="b_Stress" ID="{885FDC4C-AE0A-4B71-A9FB-82FBAE4A3270}" /><Time>0</Time><IsShared>false</IsShared></Transition><Transition><StartState Name="None" ID="{4BA09D62-D59B-4880-A78C-8BECE7D7899F}" /><EndState Name="c_Fight" ID="{20A3B196-D22F-42F7-8592-A37A3E5B467A}" /><Time>0</Time><IsShared>false</IsShared></Transition><Transition><StartState Name="b_Stress" ID="{885FDC4C-AE0A-4B71-A9FB-82FBAE4A3270}" /><EndState Name="a_Stealth" ID="{43C6702F-3A30-4D5C-B16D-C862BE5989EF}" /><Time>2.5</Time><IsShared>false</IsShared></Transition><Transition><StartState Name="a_Stealth" ID="{43C6702F-3A30-4D5C-B16D-C862BE5989EF}" /><EndState Name="b_Stress" ID="{885FDC4C-AE0A-4B71-A9FB-82FBAE4A3270}" /><Time>2.5</Time><IsShared>false</IsShared></Transition></TransitionList></StateGroup>'))
    tree.write(task.state_unit)
    tx = task.execute_plan()
    assert task.public_preview['preview_summary']['optional_none_state_materialization']['eligible_binding_count'] == 4
    code, verified = task.run('verify', tx)
    assert code == 0 and verified['verified'] is True, verified
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    event = next(row for row in shown['events'] if row['event_type'] == 'verification_recorded')
    outcome = next(row for row in event['details']['verification']['readbacks']
        if row.get('kind') == 'optional-none-custom-state-materialization')
    assert outcome['actual_addition_count'] == 4 and outcome['remaining_model_preserved'] is True
    assert {row['owner']['id'] for row in outcome['actual_additions']} == {attrs['ID'] for attrs, _ in bindings}


def test_media_single_none_failed_remainder_never_claims_complete_difference_accounting(tmp_path):
    task = NoneStateMediaTask(tmp_path, '2023.1', 'wrong-class')
    tx = task.execute_plan()
    code, failed = task.run('verify', tx)
    assert code != 0 and failed['verified'] is False, failed
    outcome = next(row for row in failed['verification']['readbacks']
        if row.get('kind') == 'optional-none-custom-state-materialization')
    assert outcome['actual_additions_complete'] is False
    assert outcome['recognized_additions_complete'] is True
    assert outcome['actual_addition_count'] == 3 and outcome['remaining_model_preserved'] is False
    assert outcome['added_saved_model_identities_observed'] is False
    assert outcome['freshness_proof'].startswith('not_established')
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    event = next(row for row in shown['events'] if row['event_type'] == 'verification_recorded')
    command = {'gateway_argv': ['transaction-show', tx, '--none-state-outcome', 'actual-additions',
        '--outcome-artifact-hash', shown['artifact_hash'], '--outcome-event-hash', event['event_hash']]}
    exact, count, _, _ = collect_none_state_pages(task, command)
    assert count == 3 and exact == outcome
    assert exact['actual_additions_complete'] is False and exact['remaining_model_preserved'] is False


def test_cli_dump_large_json_artifact_is_separate_from_public_reply_budget(tmp_path):
    class LargeDump(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                self.output.write_text(json.dumps([0] * 100000), encoding='utf-8')
            return super().call(uri, args, options)
    task = LargeDump(tmp_path, '2024.1', 'ak.wwise.cli.dumpObjects')
    task.output = tmp_path / 'large-objects.json'
    tx = task.execute_plan('--value', 'output_file', str(task.output), '--value', 'content', 'property_sets',
        '--toggle', 'include_session_objects', 'enable')
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['state'] == 'result_schema_checked', payload
    assert payload['verified'] is False and payload['verification']['business_state_verified'] is False
    observations = [row for row in payload['verification']['readbacks'] if row.get('kind') == 'cli-object-dump-artifact']
    assert len(observations) == 1 and observations[0]['json_nodes'] == 100001
    assert task.output.stat().st_size == 300000 > 256 * 1024
    assert len(json.dumps(payload).encode('utf-8')) < 16384
    assert len([row for row in task.calls if row[0] == task.operation]) == 1
    code, schema = task.run('--version', '2024.1', 'request-schema', task.operation)
    assert code == 0, schema
    limits = schema['business_adapter']['effect_verification']['limits']
    assert limits == {'file_bytes': 8 * 1024 * 1024, 'json_work': 'linear_in_bounded_artifact_bytes', 'json_depth': 64}


@pytest.mark.parametrize(('raw', 'expected_code'), [
    (b'{', 'INVALID_PROJECT_ARTIFACT'),
    (b'{"same":1,"same":2}', 'INVALID_PROJECT_ARTIFACT'),
    (b'[1e999]', 'INVALID_PROJECT_ARTIFACT'),
    (b'[NaN]', 'INVALID_PROJECT_ARTIFACT'),
    (b'\xff', 'INVALID_PROJECT_ARTIFACT'),
    (b'[' * 64 + b'0' + b']' * 64, 'LIMIT_EXCEEDED'),
    (b'[' * 1100 + b'0' + b']' * 1100, 'LIMIT_EXCEEDED'),
    (b' ' * (8 * 1024 * 1024 + 1), 'LIMIT_EXCEEDED'),
], ids=['malformed', 'duplicate', 'overflow', 'nonfinite', 'utf8', 'depth', 'decoder-depth', 'bytes'])
def test_cli_dump_artifact_errors_preserve_malformed_and_resource_distinction(tmp_path, raw, expected_code):
    class InvalidDump(CliProjectTask):
        def call(self, uri, args=None, options=None):
            if uri == self.operation:
                self.output.write_bytes(raw)
            return super().call(uri, args, options)
    task = InvalidDump(tmp_path, '2024.1', 'ak.wwise.cli.dumpObjects')
    task.output = tmp_path / 'invalid-objects.json'
    tx = task.execute_plan('--value', 'output_file', str(task.output), '--value', 'content', 'property_sets')
    code, payload = task.run('verify', tx)
    assert code != 0, payload
    if expected_code == 'LIMIT_EXCEEDED':
        assert payload['state'] == 'executed_unverified' and payload['error_code'] == expected_code, payload
    else:
        assert payload['state'] == 'verification_failed', payload
        failures = [row for row in payload['verification']['assertions'] if row['passed'] is False]
        assert len(failures) == 1 and failures[0]['evidence']['code'] == expected_code, payload
    code, repeated = task.run('execute', tx)
    assert code != 0 and repeated.get('automatic_retry') is not True, repeated
    assert len([row for row in task.calls if row[0] == task.operation]) == 1


@pytest.mark.parametrize('version', ('2021.1', '2022.1', *VERSIONS))
def test_create_resolves_only_source_proven_elided_default_language(tmp_path, version):
    task = (CliCreateEffectTask(tmp_path, version) if version in ('2021.1', '2022.1')
        else ConsoleProjectTask(tmp_path, version))
    extra = (('--item', 'platforms', 'Windows', '--item', 'platforms', 'Android') if version in ('2021.1', '2022.1') else ('--item', 'languages', 'English(US)', '--item', 'languages', 'Japanese'))
    tx, code, payload = execute_console_creation(task, *extra)
    assert code == 0, payload
    tree = ET.parse(task.created_file)
    project = tree.find('./ProjectInfo/Project')
    properties = project.find('PropertyList')
    properties.remove(properties.find('./Property[@Name="DefaultLanguage"]'))
    backing = ET.SubElement(ET.SubElement(ET.SubElement(project, 'SharedValues'), 'SharedPropertyList'), 'PropertyList')
    field = ET.SubElement(backing, 'Property', Name='DefaultLanguage', Type='string')
    ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value').text = 'English(US)'
    tree.write(task.created_file)
    code, payload = task.run('verify', tx)
    assert code == 0 and payload['verified'] is True, payload
    code, shown = task.run('transaction-show', tx)
    assert code == 0, shown
    event = next(row for row in shown['events'] if row['event_type'] == 'verification_recorded')
    observed = next(row for row in event['details']['verification']['readbacks'] if 'default_language' in row)
    assert observed['default_language'] == 'English(US)'
    proof = observed['default_language_observation']
    assert proof['representation'] == 'default_elided' and proof['property_present'] is False
    assert proof['source']['version'] == version and proof['source']['class']['Name'] == 'Project'


@pytest.mark.parametrize('fault', ['duplicate', 'wrong-type', 'empty-value', 'dual-encoding', 'missing-property-list', 'wrong-first-elided'])
def test_console_create_keeps_invalid_or_conflicting_default_language_unverified(tmp_path, fault):
    task = ConsoleProjectTask(tmp_path, '2025.1')
    extra = ('--item', 'languages', 'French', '--item', 'languages', 'Japanese') if fault == 'wrong-first-elided' else ()
    tx, code, payload = execute_console_creation(task, *extra)
    assert code == 0, payload
    tree = ET.parse(task.created_file)
    project = tree.find('./ProjectInfo/Project'); properties = project.find('PropertyList')
    field = properties.find('./Property[@Name="DefaultLanguage"]')
    if fault == 'duplicate': properties.append(deepcopy(field))
    elif fault == 'wrong-type': field.set('Type', 'bool')
    elif fault == 'empty-value': field.set('Value', '')
    elif fault == 'dual-encoding': ET.SubElement(ET.SubElement(field, 'ValueList'), 'Value').text = 'English(US)'
    elif fault == 'missing-property-list': project.remove(properties)
    elif fault == 'wrong-first-elided':
        properties.remove(field)
        backing = ET.SubElement(ET.SubElement(ET.SubElement(project, 'SharedValues'), 'SharedPropertyList'), 'PropertyList')
        ET.SubElement(backing, 'Property', Name='DefaultLanguage', Type='string', Value='French')
    tree.write(task.created_file)
    retained = task.created_file.read_bytes()
    code, payload = task.run('verify', tx)
    assert code != 0 and payload['state'] == 'verification_failed' and payload['verified'] is False, payload
    assert task.created_file.read_bytes() == retained
    code, payload = task.run('execute', tx)
    assert code != 0 and len([row for row in task.calls if row[0] == CREATE]) == 1
