"""Actual macOS lsof field output, observed without Wwise or a network client."""
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from tests.destructive.support.integration_demo import OwnedIntegrationDemo

CONTROL = Path(__file__).parents[1] / 'fixtures/integration-demo-lsof-field-control.json'


def _owner(tmp_path, monkeypatch, fault=None):
    control = json.loads(CONTROL.read_bytes())
    stdout = control['stdout'].encode('ascii')
    if fault == 'wrong-pid':
        stdout = b'p60865\nf3\n'
    elif fault == 'no-fd':
        stdout = b'p60864\n'
    elif fault == 'malformed-fd':
        stdout = b'p60864\nf3x\n'
    elif fault == 'control-byte':
        stdout = b'p60864\nf3\x00\n'
    elif fault == 'extra-process':
        stdout += b'p60865\nf4\n'
    elif fault == 'truncated':
        stdout = stdout[:-1]
    elif fault == 'oversized':
        stdout = b'p60864\n' + b'f3\n' * 1400
    demo = OwnedIntegrationDemo(SimpleNamespace(bundle=tmp_path / 'Wwise.app'),
        SimpleNamespace(owned_root=tmp_path / 'owned', evidence_root=tmp_path / 'evidence'))
    demo.process = SimpleNamespace(pid=control['pid'], poll=lambda: None)
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 1 if fault == 'nonzero' else 0, stdout, b'')
    monkeypatch.setattr(subprocess, 'run', run)
    return demo, control, calls


def test_actual_lsof_pid_and_fd_fields_prove_exact_owned_listener(tmp_path, monkeypatch):
    demo, control, calls = _owner(tmp_path, monkeypatch)
    receipt = demo.owns_port(control['port'], '127.0.0.1', timeout_seconds=1)
    assert receipt['stdout'] == control['stdout'] == 'p60864\nf3\n'
    assert receipt['pid'] == control['pid'] and receipt['command_port'] == control['port']
    assert receipt['owned'] is True and receipt['exit_code'] == 0
    assert receipt == demo.port_ownership_receipt
    argv, options = calls[0]
    assert argv == control['argv'] and 0 < options['timeout'] <= 1


@pytest.mark.parametrize('fault', ['wrong-pid', 'no-fd', 'malformed-fd', 'control-byte',
    'extra-process', 'truncated', 'oversized', 'nonzero'])
def test_invalid_lsof_field_evidence_rejects_and_retains_bounded_receipt(tmp_path, monkeypatch, fault):
    demo, control, calls = _owner(tmp_path, monkeypatch, fault)
    with pytest.raises(ValueError, match='not owned by the exact Demo PID'):
        demo.owns_port(control['port'], '127.0.0.1', timeout_seconds=1)
    receipt = demo.port_ownership_receipt
    assert receipt['owned'] is False and receipt['command_port'] == control['port']
    assert len(receipt['stdout'].encode()) <= 4096 and len(receipt['stderr'].encode()) <= 4096
    assert receipt['output_overflow'] is (fault == 'oversized')
    assert len(calls) == 1 and demo.command_port is None
