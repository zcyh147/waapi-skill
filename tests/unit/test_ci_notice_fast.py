from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ci.test_driver import main


ROOT = Path(__file__).resolve().parents[2]


def test_notice_fast_launcher_forces_offline_and_preserves_child_failure():
    calls = []

    def child(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 7)

    assert main(
        ['--mode', 'notice-fast', '--', '-q', '-ra'],
        environment={'WWISE_LIVE': '1', 'WWISE_DESTRUCTIVE': '1',
                     'WWISE_STRICT_REAL': '1', 'PYTEST_ADDOPTS': 'tests/live', 'PYTHONUTF8': '0'},
        python_executable=sys.executable, command_runner=child,
    ) == 7
    command, options = calls[0]
    assert command == (sys.executable, str(ROOT / 'ci/run_notice_fast_tests.py'), '-q', '-ra')
    assert options['shell'] is False
    assert {key: options['env'][key] for key in
            ('WWISE_LIVE', 'WWISE_DESTRUCTIVE', 'WWISE_STRICT_REAL')} == {
                'WWISE_LIVE': '0', 'WWISE_DESTRUCTIVE': '0', 'WWISE_STRICT_REAL': '0'}
    assert 'PYTEST_ADDOPTS' not in options['env']
    assert options['env']['PYTHONUTF8'] == '1'


def test_notice_fast_collection_is_explicit_and_missing_selection_cannot_pass(tmp_path):
    from ci.run_notice_fast_tests import load_notice_fast_nodes

    nodes = load_notice_fast_nodes(ROOT / 'ci/notice-fast-test-nodes.txt', repo_root=ROOT)
    assert 'tests/semantic/test_codex_expansion_task_runner.py' in nodes
    assert 'tests/semantic/test_codex_expansion_archive.py' in nodes
    assert 'tests/semantic/test_codex_ancillary_role_notices.py' in nodes
    assert all(node.startswith('tests/semantic/test_') for node in nodes)
    assert 'tests/semantic/test_run_codex_skill_campaign.py::test_candidate_drift_during_child_is_sealed_as_blocked' in nodes
    manifest = tmp_path / 'selection.txt'
    manifest.write_text('# no tests\n')
    with pytest.raises(ValueError, match='no pytest nodes'):
        load_notice_fast_nodes(manifest, repo_root=ROOT)
    manifest.write_text('tests/semantic/test_codex_missing.py\n')
    with pytest.raises(ValueError, match='missing or escaping'):
        load_notice_fast_nodes(manifest, repo_root=ROOT)


@pytest.mark.parametrize('extra', [
    ['tests/live'], ['--pyargs', 'tests'], ['-m', 'live'],
    ['-p', 'anything'], ['--ignore=tests/semantic'],
])
def test_notice_fast_rejects_collection_overrides(extra):
    result = subprocess.run(
        [sys.executable, str(ROOT / 'ci/run_notice_fast_tests.py'), *extra],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert 'selection error' in result.stderr


def test_notice_fast_empty_filter_is_not_a_pass():
    result = subprocess.run(
        [sys.executable, str(ROOT / 'ci/test_driver.py'), '--mode', 'notice-fast',
         '--', '-q', '-k', 'this_test_name_does_not_exist_158'],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 5, result.stdout + result.stderr
    assert 'deselected' in result.stdout


def test_notice_fast_preserves_interpreter_preflight_and_rejects_real_version(monkeypatch):
    from ci import test_driver

    def blocked(**options):
        raise test_driver.TestEnvironmentError('incomplete developer interpreter')

    monkeypatch.setattr(test_driver, 'validate_test_environment', blocked)
    assert main(['--mode', 'notice-fast']) == 4
    assert main(['--mode', 'notice-fast', '--version', '2025.1']) == 1
