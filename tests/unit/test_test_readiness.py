from __future__ import annotations

import hashlib
import json
import os
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
    conflict_command = f'WwiseConsole "{sandbox}"'
    conflict_snapshot = (json.dumps([{'ProcessId': 999999, 'CommandLine': conflict_command}])
                         if os.name == 'nt' else f'999999 {conflict_command}')
    snapshot = lambda: conflict_snapshot if fault == 'process-conflict' else ''
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


@pytest.mark.parametrize('version', ['2021.1', '2022.1', '2023.1', '2024.1', '2025.1'])
def test_live_launcher_accepts_actual_saved_project_header(tmp_path, version):
    import xml.etree.ElementTree as ET
    repo = Path(__file__).resolve().parents[2]
    header = ET.fromstring((repo / 'tests' / '_org' / version / 'SampleProject.wproj').read_bytes()).attrib
    console = tmp_path / 'WwiseConsole'
    console.write_text('fake')
    console.chmod(0o755)
    source = tmp_path / 'source'
    source.mkdir()
    project = source / 'SampleProject.wproj'
    project.write_bytes(ET.tostring(ET.Element('WwiseDocument', header)))
    calls = []
    result = launch((
        '--version', version, '--mode', 'live', '--repo-root', str(tmp_path),
        '--default-config', str(tmp_path / 'absent.json'), '--default-console', str(console),
        '--default-project', str(project), '--default-sandbox', str(tmp_path / 'sandbox'),
        '--', 'poetry', 'run', 'python', '-m', 'pytest',
    ), environment={}, python_executable=sys.executable,
        process_snapshot=lambda: '', command_runner=lambda command, **kwargs:
        (calls.append(command) or subprocess.CompletedProcess(command, 7)))
    assert result == 7
    assert len(calls) == 1


def test_full_nonlive_blocks_absent_static_fixture_before_pytest(tmp_path, capsys):
    repo = Path(__file__).resolve().parents[2]
    (tmp_path / 'pyproject.toml').write_bytes((repo / 'pyproject.toml').read_bytes())
    calls = []
    result = developer_launch(('--mode', 'nonlive', '--', '-q'), repo_root=tmp_path,
                             command_runner=lambda *args, **kwargs: calls.append(args))
    assert result == 1
    assert calls == []
    assert 'TEST_READINESS_BLOCKED' in capsys.readouterr().err


def test_live_launcher_blocks_other_root_macos_real_lane(tmp_path, capsys):
    if sys.platform != 'darwin':
        pytest.skip('launcher host exclusion is macOS-specific')
    console = tmp_path / 'WwiseConsole'
    console.write_text('fake')
    console.chmod(0o755)
    source = tmp_path / 'source'
    source.mkdir()
    project = source / 'SampleProject.wproj'
    project.write_text('<WwiseDocument WwiseVersion="v2025.1.7" />')
    calls = []
    result = launch((
        '--version', '2025.1', '--mode', 'live', '--repo-root', str(tmp_path),
        '--default-config', str(tmp_path / 'absent.json'), '--default-console', str(console),
        '--default-project', str(project), '--default-sandbox', str(tmp_path / 'sandbox'),
        '--', 'poetry', 'run', 'python', '-m', 'pytest',
    ), environment={}, python_executable=sys.executable,
        process_snapshot=lambda: '999999 python /other/repo/ci/test_driver.py --version 2022.1 --mode live',
        command_runner=lambda *args, **kwargs: calls.append(args))
    assert result == 1
    assert calls == []
    assert 'shared' in capsys.readouterr().err


def _static_checkout(tmp_path):
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    repo = Path(__file__).resolve().parents[2]
    (tmp_path / 'pyproject.toml').write_bytes((repo / 'pyproject.toml').read_bytes())
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        source = tmp_path / 'tests' / '_org' / version
        source.mkdir(parents=True)
        project = source / 'SampleProject.wproj'
        project.write_text(f'<WwiseDocument WwiseVersion="v{version}.0" />')
        (source / 'fixture-manifest.json').write_text(json.dumps({
            'algorithm': 'sha256', 'file_count': 1, 'files': [{
                'path': 'SampleProject.wproj', 'bytes': project.stat().st_size,
                'sha256': hashlib.sha256(project.read_bytes()).hexdigest(),
            }],
        }))


@pytest.mark.parametrize('fault', ['ready', 'dehydrated', 'process'])
def test_complete_nonlive_static_readiness_controls_child_dispatch(tmp_path, monkeypatch, fault):
    from ci import test_readiness
    _static_checkout(tmp_path)
    if fault == 'dehydrated':
        (tmp_path / 'tests' / '_org' / '2023.1' / 'SampleProject.wproj').write_bytes(b'version https://git-lfs.github.com/spec/v1')
    command = f'999999 python "{tmp_path}/ci/test_driver.py" --mode nonlive'
    snapshot = json.dumps([{'ProcessId': 999999, 'CommandLine': command}]) if os.name == 'nt' else command
    monkeypatch.setattr(test_readiness, 'scoped_process_snapshot', lambda: snapshot if fault == 'process' else '')
    calls = []
    result = developer_launch(('--mode', 'nonlive', '--', '-q'), repo_root=tmp_path,
        environment={'WWISE_TEST_CONFIG': '/missing/unrelated/live.json'},
        command_runner=lambda command, **kwargs: (calls.append((command, kwargs)) or subprocess.CompletedProcess(command, 7)))
    assert result == (7 if fault == 'ready' else 1)
    assert len(calls) == (1 if fault == 'ready' else 0)
    if calls:
        assert calls[0][1]['env']['WWISE_LIVE'] == '0'


def test_focused_fake_nonlive_does_not_require_static_fixtures(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    (tmp_path / 'pyproject.toml').write_bytes((repo / 'pyproject.toml').read_bytes())
    calls = []
    result = developer_launch(('--mode', 'nonlive', '--', 'tests/unit/fake.py', '-q'), repo_root=tmp_path,
        command_runner=lambda command, **kwargs: (calls.append(command) or subprocess.CompletedProcess(command, 7)))
    assert result == 7
    assert len(calls) == 1


@pytest.mark.parametrize('platform,scope,command,conflict', [
    ('linux', '/repo/溪 夜&;$()/sandbox', 'pytest "/repo/溪 夜&;$()/sandbox/test.py"', True),
    ('linux', '/repo/Source', 'pytest /repo/source/test.py', False),
    ('win32', r'C:\Repo\溪 夜&;$(x)\sandbox', r'pytest "c:/repo/溪 夜&;$(x)/sandbox/test.py"', True),
    ('win32', r'C:\Repo\source', r'pytest "D:\repo\source\test.py"', False),
    ('win32', r'\\Server\Share\溪 夜&;$(x)\sandbox', r'pytest "//server/share/溪 夜&;$(x)/sandbox/test.py"', True),
    ('win32', r'\\Server\Share\Source', r'pytest "\\server\other\source\test.py"', False),
])
def test_readiness_scoped_process_paths_obey_host_flavor(platform, scope, command, conflict):
    from ci.test_readiness import ReadinessBlocked, validate_process_readiness
    snapshot = json.dumps([{'ProcessId': 999999, 'CommandLine': command}]) if platform == 'win32' else f'999999 {command}'
    if conflict:
        with pytest.raises(ReadinessBlocked, match='pid=999999'):
            validate_process_readiness(snapshot, scopes=(scope,), platform_name=platform)
    else:
        validate_process_readiness(snapshot, scopes=(scope,), platform_name=platform)


@pytest.mark.parametrize('source,sandbox,blocked', [
    ('/repo/Source', '/repo/source/sandbox', False),
    ('/repo/source', '/repo/source/../sandbox', True),
    (r'C:\Repo\SOURCE', 'c:/repo/source/sandbox', True),
    (r'C:\Repo\Source', r'C:\Repo\Source\..\sandbox', True),
    (r'\\Server\Share\SOURCE', '//server/share/source/sandbox', True),
    (r'\\Server\Share\source', r'\\Server\Share\source\..\sandbox', True),
    (r'C:\Repo\溪 夜&;$(x)', r'D:\Repo\溪 夜&;$(x)', False),
])
def test_readiness_path_separation_rejects_overlap_and_traversal(source, sandbox, blocked):
    from ci.test_readiness import validate_path_separation
    if blocked:
        with pytest.raises(ValueError):
            validate_path_separation(source, sandbox)
    else:
        validate_path_separation(source, sandbox)


@pytest.mark.parametrize('platform,command,blocked', [
    ('darwin', 'python /other/repo/ci/test_driver.py --mode live --version 2022.1', True),
    ('darwin', 'pytest /other/repo/tests/destructive/test_real.py', True),
    ('darwin', '/other/WwiseConsole.sh waapi-server /other/source.wproj', True),
    ('darwin', 'python /other/run_codex_skill_campaign.py --profile integration', True),
    ('darwin', 'pytest /other/repo/tests/unit/fake.py', False),
    ('darwin', 'python /other/ci/test_driver.py --mode notice-fast', False),
    ('darwin', 'python /other/run_codex_skill_campaign.py --offline-only', False),
    ('linux', '/other/WwiseConsole.sh waapi-server /other/source.wproj', False),
])
def test_readiness_shared_bottle_exclusion_is_platform_and_lane_scoped(platform, command, blocked):
    from ci.test_readiness import ReadinessBlocked, validate_process_readiness
    if blocked:
        with pytest.raises(ReadinessBlocked, match='shared'):
            validate_process_readiness(f'999999 {command}', scopes=('/selected/source',), real_lane=True, platform_name=platform)
    else:
        validate_process_readiness(f'999999 {command}', scopes=('/selected/source',), real_lane=True, platform_name=platform)


def test_launcher_keeps_windows_path_metacharacters_as_argv_data(tmp_path):
    from ci.run_live_test_command import resolve_live_python_command
    values = (r'C:\Repo\溪 夜&;$(x)\source.wav', r'\\Server\Share\溪 夜&;$(x)\source.wav')
    command = ('poetry', 'run', 'python', '-m', 'pytest', *values)
    assert resolve_live_python_command(command, python_executable=sys.executable) == (
        sys.executable, '-m', 'pytest', *values,
    )
