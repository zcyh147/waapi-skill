"""Closed Console project alternatives through the real public Draft chain.

Pinned schemas establish construction; injected clients do not establish native
project effects or permit any native process launch.
"""
from copy import deepcopy
import json

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
            self.created_file.write_text('<WwiseDocument Type="Project" />')
            self.project_file = self.created_file
            return {}
        return super().call(uri, args, options)


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
