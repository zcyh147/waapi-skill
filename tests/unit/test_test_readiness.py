from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ci.run_live_test_command import main as launch
from ci.test_driver import main as developer_launch


def test_live_launcher_blocks_missing_materialized_media_before_child(tmp_path, capsys):
    console = tmp_path / 'WwiseConsole'
    console.write_text('fake console')
    console.chmod(0o755)
    project = tmp_path / 'source' / 'SampleProject.wproj'
    project.parent.mkdir()
    project.write_text('<Project />')
    (project.parent / 'fixture-manifest.json').write_text(json.dumps({
        'algorithm': 'sha256', 'file_count': 1,
        'files': [{'path': 'Originals/missing.wav', 'bytes': 4,
                   'sha256': hashlib.sha256(b'RIFF').hexdigest()}],
    }))
    calls = []
    def child(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 7)
    result = launch((
        '--version', '2025.1', '--mode', 'live', '--repo-root', str(tmp_path),
        '--default-config', str(tmp_path / 'absent.json'), '--default-console', str(console),
        '--default-project', str(project), '--default-sandbox', str(tmp_path / 'sandbox'),
        '--', 'poetry', 'run', 'python', '-m', 'pytest', '-q',
    ), environment={}, python_executable=sys.executable, command_runner=child)
    assert result == 1
    assert calls == []
    assert 'TEST_READINESS_BLOCKED' in capsys.readouterr().err


@pytest.mark.parametrize("sealed", [False, True])
def test_live_launcher_ready_preserves_child_status_and_flags(tmp_path, capsys, sealed):
    console = tmp_path / 'WwiseConsole'
    console.write_text('fake console')
    console.chmod(0o755)
    project = tmp_path / 'source' / 'SampleProject.wproj'
    project.parent.mkdir()
    project.write_text('<WwiseDocument WwiseVersion="2025.1.7" />')
    (project.parent / 'sound.wav').write_bytes(b'RIFFready')
    if sealed:
        (project.parent / 'fixture-manifest.json').write_text(json.dumps({
            'algorithm': 'sha256', 'file_count': 1, 'files': [{
                'path': 'sound.wav', 'bytes': 9,
                'sha256': 'e1a07d8ee9e2f9624783861cd6fadc46125b0a90fd1b2e8c52b19ef466a63f42',
            }],
        }))
    calls = []
    def child(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 7)
    result = launch((
        '--version', '2025.1', '--mode', 'destructive', '--repo-root', str(tmp_path),
        '--default-config', str(tmp_path / 'absent.json'), '--default-console', str(console),
        '--default-project', str(project), '--default-sandbox', str(tmp_path / 'sandbox'),
        '--', 'poetry', 'run', 'python', '-m', 'pytest', '-q',
    ), environment={}, python_executable=sys.executable, command_runner=child,
        process_snapshot=lambda: '')
    assert result == 7
    assert len(calls) == 1
    command, options = calls[0]
    assert command == (sys.executable, '-m', 'pytest', '-q')
    assert options['shell'] is False
    assert options['env']['WWISE_DESTRUCTIVE'] == '1'
    assert options['env']['WWISE_STRICT_REAL'] == '1'
    assert '"status": "ready"' in capsys.readouterr().out


@pytest.mark.parametrize('fault', ['project-version', 'media-digest', 'source-overlap', 'process-conflict'])
def test_live_launcher_blocks_selected_mismatched_prerequisite(tmp_path, capsys, fault):
    console = tmp_path / 'WwiseConsole'
    console.write_text('fake console')
    console.chmod(0o755)
    project = tmp_path / 'source' / 'SampleProject.wproj'
    project.parent.mkdir()
    project.write_text('<WwiseDocument WwiseVersion="2025.1.7" />')
    media = project.parent / 'sound.wav'
    media.write_bytes(b'wrong')
    sandbox = tmp_path / 'sandbox'
    if fault == 'project-version':
        project.write_text('<WwiseDocument WwiseVersion="2022.1.19" />')
    elif fault == 'media-digest':
        (project.parent / 'fixture-manifest.json').write_text(json.dumps({
            'algorithm': 'sha256', 'file_count': 1, 'files': [{
                'path': 'sound.wav', 'bytes': 5, 'sha256': hashlib.sha256(b'right').hexdigest(),
            }],
        }))
    elif fault == 'source-overlap':
        sandbox = project.parent / 'sandbox'
    calls = []
    def child(command, **options):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)
    snapshot = lambda: f'123 WwiseConsole {sandbox}' if fault == 'process-conflict' else ''
    result = launch((
        '--version', '2025.1', '--mode', 'live', '--repo-root', str(tmp_path),
        '--default-config', str(tmp_path / 'absent.json'), '--default-console', str(console),
        '--default-project', str(project), '--default-sandbox', str(sandbox),
        '--', 'poetry', 'run', 'python', '-m', 'pytest',
    ), environment={}, python_executable=sys.executable, command_runner=child,
        process_snapshot=snapshot)
    assert result == 1
    assert calls == []
    assert '"status": "blocked"' in capsys.readouterr().err


def test_program_readiness_ignores_unrelated_live_prerequisites(capsys):
    calls = []
    def child(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 7)
    result = developer_launch(('--mode', 'program'), environment={
        'WWISE_TEST_CONFIG': '/missing/live.json', 'WWISE_CONSOLE': '/missing/console',
    }, command_runner=child)
    assert result == 7
    assert len(calls) == 1
    assert 'WWISE_TEST_CONFIG' not in calls[0][1]['env']
    assert '"status": "ready"' in capsys.readouterr().out


def test_developer_launcher_blocks_mismatched_runtime_before_child(tmp_path, capsys):
    repo = Path(__file__).resolve().parents[2]
    (tmp_path / 'pyproject.toml').write_text(
        (repo / 'pyproject.toml').read_text().replace('pytest = "==8.4.2"', 'pytest = "==999.0"'))
    calls = []
    result = developer_launch(('--mode', 'program'), repo_root=tmp_path,
                             command_runner=lambda *args, **kwargs: calls.append(args))
    assert result == 4
    assert calls == []
    assert 'does not match locked 999.0' in capsys.readouterr().err
