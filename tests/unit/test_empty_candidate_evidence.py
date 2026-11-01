"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import gzip

import json

import pytest

from pathlib import Path

from tests.maintenance import branch_coverage_audit as audit

from tests.unit.test_runtime_business_gateway import _env, gateway

ROOT = Path(__file__).resolve().parents[2]

ROUTE = '2025.1|wwise-console|2025.1.7.9143|function|ak.wwise.core.log.get'

def _log_receipt(tmp_path, severity):
    class Client:
        def __init__(self): self.calls = []
        def disconnect(self): pass
        def call(self, uri, args=None, options=None):
            if uri == 'ak.wwise.core.getInfo':
                result = {'displayName': 'Wwise', 'isCommandLine': True,
                          'version': {'year': 2025, 'major': 1, 'minor': 7, 'build': 9143,
                                      'displayName': 'v2025.1.7.9143'}}
            elif uri == 'ak.wwise.core.getProjectInfo':
                result = {'id': '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}', 'name': 'SampleProject', 'path': str(tmp_path / 'Sample.wproj')}
            else:
                assert uri == 'ak.wwise.core.log.get'
                result = {'items': [{'message': 'owned marker', 'severity': severity, 'time': 1, 'messageId': 'Custom'}]}
            self.calls.append({'uri': uri, 'args': deepcopy(args or {}), 'options': deepcopy(options or {}), 'result': deepcopy(result)})
            return result
    client = Client()
    argv = ['--state-dir', str(tmp_path / 'state'), 'core-call', 'ak.wwise.core.log.get', '--log-channel', 'general']
    code, payload = gateway.execute_gateway(argv, env=_env(tmp_path), client_factory=lambda _: client)
    return {'gateway': {'argv': argv, 'exit_code': code, 'payload': payload}, 'native_calls': client.calls}

def test_empty_log_severity_requires_exact_public_result_rejection(tmp_path):
    valid = _log_receipt(tmp_path, 'Message')
    invalid = _log_receipt(tmp_path, '')
    assert valid['gateway']['exit_code'] == 0, valid
    assert invalid['gateway']['exit_code'] == 2
    assert 'agent_result' not in invalid['gateway']['payload']

def test_empty_public_severity_is_rejected_before_dispatch_with_valid_preview_counterpart(tmp_path, request):
    import contextlib
    import io
    from tests.unit.test_console_log_observer_gateway import ConsoleLogClient
    client = ConsoleLogClient(tmp_path)
    recorded = []
    original_call = client.call
    def call(uri, args=None, options=None):
        result = original_call(uri, args, options)
        recorded.append({'uri': uri, 'args': deepcopy(args or {}), 'options': deepcopy(options or {}), 'result': deepcopy(result)})
        return result
    client.call = call
    def invoke(argv):
        recorded.clear()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code, payload = gateway.execute_gateway(argv, env=_env(tmp_path), client_factory=lambda _: client)
            except SystemExit as exc:
                code, payload = exc.code, None
        return {'gateway': {'argv': argv, 'exit_code': code, 'payload': payload,
                            'stdout': out.getvalue(), 'stderr': err.getvalue()}, 'native_calls': deepcopy(recorded)}
    prefix = ['--state-dir', str(tmp_path / 'state')]
    started = invoke([*prefix, 'draft-start', 'ak.wwise.core.log.addItem'])['gateway']['payload']
    declaration = [*prefix, 'draft-declare-runtime-control-plan', started['draft']['draft_id'],
                   '--task-authority', started['task_authority'], '--expected-revision', str(started['draft']['revision']),
                   '--message', 'owned marker', '--severity', '']
    invalid = invoke(declaration)
    assert invalid['gateway']['exit_code'] == 2 and invalid['gateway']['payload'] is None
    assert invalid['native_calls'] == []
    valid = invoke([*declaration[:-1], 'message'])
    assert valid['gateway']['exit_code'] == 0, valid
    current = valid['gateway']['payload']
    checked = invoke([*prefix, 'draft-check', current['draft']['draft_id'], '--task-authority', started['task_authority'],
                      '--expected-revision', str(current['draft']['revision'])])['gateway']['payload']
    compiled = invoke([*prefix, 'preview-from-draft', checked['draft']['draft_id'], '--task-authority', started['task_authority'],
                       '--expected-revision', str(checked['draft']['revision'])])
    assert compiled['gateway']['exit_code'] == 0, compiled
    assert compiled['gateway']['payload']['agent_result']['request']['arguments']['args']['severity'] == 'Message'
