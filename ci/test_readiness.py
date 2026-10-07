"""Read-only prerequisite checks shared by developer and Fresh launchers."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath


class ReadinessBlocked(ValueError):
    """The selected lane cannot dispatch safely with its current prerequisites."""


def report_readiness(started: float, *, reason: str = 'selected prerequisites ready', blocked: bool = False) -> None:
    print(json.dumps({
        'phase': 'test-readiness', 'status': 'blocked' if blocked else 'ready',
        'duration_seconds': round(time.perf_counter() - started, 6),
        'reason': reason[:2000], 'automatic_repair_attempted': False,
    }), file=sys.stderr if blocked else sys.stdout, flush=True)


def validate_project_materialization(project: Path, *, version: str) -> None:
    """Check declared project version and sealed payloads without hydrating media."""
    try:
        if project.stat().st_size > 16 * 1024 * 1024:
            raise ReadinessBlocked('project document exceeds readiness size limit')
        document = ET.fromstring(project.read_bytes())
        declared = document.attrib.get('WwiseVersion')
        if declared:
            declared = declared.removeprefix('v')
        if declared and not declared.startswith(version + '.') and declared != version:
            raise ReadinessBlocked(f'project WwiseVersion {declared} does not match selected {version}: {project}')
        manifest_path = project.parent / 'fixture-manifest.json'
        if not manifest_path.exists():
            return  # Installed sample projects have no repository seal.
        if manifest_path.stat().st_size > 2 * 1024 * 1024:
            raise ReadinessBlocked('fixture manifest exceeds readiness size limit')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        rows = manifest['files']
        if (manifest.get('algorithm') != 'sha256' or not isinstance(rows, list)
                or not 1 <= len(rows) <= 4096 or manifest.get('file_count') != len(rows)):
            raise ReadinessBlocked(f'invalid fixture manifest: {manifest_path}')
        seen: set[str] = set()
        total_bytes = 0
        for row in rows:
            relative = row['path']
            path = PurePosixPath(relative)
            if (not relative or path.is_absolute() or '..' in path.parts or '\\' in relative
                    or path.as_posix() != relative or relative in seen):
                raise ReadinessBlocked('fixture manifest contains an unsafe or duplicate path')
            seen.add(relative)
            target = project.parent.joinpath(*path.parts)
            if not target.resolve().is_relative_to(project.parent.resolve()):
                raise ReadinessBlocked(f'fixture payload escapes source: {relative}')
            size = row['bytes']
            if type(size) is not int or not 0 <= size <= 512 * 1024 * 1024:
                raise ReadinessBlocked(f'fixture payload exceeds readiness size limit: {relative}')
            total_bytes += size
            if total_bytes > 1024 * 1024 * 1024:
                raise ReadinessBlocked("fixture payload exceeds total readiness size limit")
            if not target.is_file() or target.stat().st_size != size:
                raise ReadinessBlocked(f'fixture payload missing or not materialized: {target}; provision it explicitly before retrying')
            digest = hashlib.sha256()
            with target.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != row['sha256']:
                raise ReadinessBlocked(f'fixture payload digest mismatch: {target}; restore the selected fixture before retrying')
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        if isinstance(exc, ReadinessBlocked):
            raise
        raise ReadinessBlocked(f'cannot validate project/fixture {project}: {exc}') from exc


def scoped_process_snapshot() -> str:
    """Bounded native process observation; never terminates a process."""
    command = (
        ('powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
         'Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress')
        if os.name == 'nt' else ('ps', '-axo', 'pid=,command=')
    )
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10,
                                shell=False, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReadinessBlocked(f'cannot inspect scoped processes: {exc}') from exc
    if result.returncode != 0 or len(result.stdout.encode('utf-8')) > 2 * 1024 * 1024:
        raise ReadinessBlocked('scoped process observation failed or exceeded its size limit')
    return result.stdout


def validate_live_readiness(
    environment: Mapping[str, str], *, process_snapshot: Callable[[], str] | None = None,
) -> None:
    project = Path(environment['WWISE_SAMPLE_PROJECT_PATH']).expanduser().resolve(strict=True)
    sandbox = Path(environment['WWISE_SANDBOX_ROOT']).expanduser().resolve()
    source = project.parent
    validate_path_separation(str(source), str(sandbox))
    validate_project_materialization(project, version=environment['WWISE_VERSION'])
    validate_process_readiness(
        (process_snapshot or scoped_process_snapshot)(), scopes=(str(project), str(sandbox)),
        real_lane=True,
    )


def validate_path_separation(source: str, sandbox: str) -> None:
    """Use the canonical owning path flavor for the read-only containment boundary."""
    from wwise_waapi.host_paths import host_path_comparison_key
    source_key = host_path_comparison_key(source)
    sandbox_key = host_path_comparison_key(sandbox)
    if source_key[:len(sandbox_key)] == sandbox_key or sandbox_key[:len(source_key)] == source_key:
        raise ReadinessBlocked('sandbox root overlaps the immutable source project; choose a separate WWISE_SANDBOX_ROOT')


def _command_mentions_scope(command: str, scope: str) -> bool:
    from wwise_waapi.host_paths import parse_absolute_host_path
    parsed = parse_absolute_host_path(scope)
    if parsed.flavor == 'posix':
        pattern = re.escape(str(parsed.pure_path))
        flags = 0
    else:
        separator = r'[\\/]'
        prefix = re.escape(parsed.drive) + ':' + separator if parsed.flavor == 'drive' else separator + '{2}'
        pattern = prefix + separator.join(re.escape(part) for part in parsed.components)
        flags = re.IGNORECASE
    return re.search(r'(?<![\w./\\])' + pattern + r'(?=$|[\s"\'\\/])', command, flags) is not None


def _proved_real_lane(command: str) -> bool:
    lowered = command.casefold()
    if any(marker in lowered for marker in ('wwiseconsole.sh', 'wwiseconsole.exe', 'wwise.exe')):
        return True
    if 'test_driver.py' in lowered:
        return re.search(r'(?:--mode|-m)\s+(?:smoke|live|destructive|matrix|focused|all)(?:\s|$)', lowered) is not None
    if 'pytest' in lowered:
        return (re.search(r'tests[\\/](?:live|destructive)(?:[\\/\s]|$)', lowered) is not None
                or re.search(r'''(?:^|\s)-m\s+["']?(?:live|destructive)\b''', lowered) is not None)
    if 'run_codex_skill_campaign.py' in lowered:
        return '--offline-only' not in lowered and '--verify-only' not in lowered
    return False


def validate_process_readiness(
    snapshot: str, *, scopes: tuple[str, ...], real_lane: bool = False,
    platform_name: str | None = None,
) -> None:
    """Observe process conflicts at the readiness boundary without dispatch or cleanup."""
    platform_name = sys.platform if platform_name is None else platform_name
    if platform_name in {'nt', 'win32'}:
        try:
            rows = json.loads(snapshot) if snapshot.strip() else []
            if isinstance(rows, dict):
                rows = [rows]
            lines = [(int(row['ProcessId']), str(row.get('CommandLine') or '')) for row in rows]
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            raise ReadinessBlocked('cannot parse scoped Windows process observation') from exc
    else:
        try:
            lines = [(int(line.split(None, 1)[0]), line.split(None, 1)[1])
                     for line in snapshot.splitlines() if line.strip()]
        except (ValueError, IndexError) as exc:
            raise ReadinessBlocked('cannot parse scoped process observation') from exc
    for pid, command in lines:
        if pid in {os.getpid(), os.getppid()}:
            continue
        if real_lane and platform_name == 'darwin' and _proved_real_lane(command):
            raise ReadinessBlocked(f'macOS shared Wwise2019x64 bottle is in use by real lane pid={pid}; let its owner finish before retrying')
        lowered = command.casefold()
        if any(marker in lowered for marker in ('wwiseconsole', 'wwise.exe', 'wwise.app', 'pytest', 'test_driver.py', 'run_codex_skill_campaign.py')) and any(_command_mentions_scope(command, scope) for scope in scopes):
            raise ReadinessBlocked(f'scoped Wwise/test process pid={pid} is still using the selected source or sandbox; inspect and resolve it before retrying')


def validate_nonlive_readiness(repo_root: Path, pytest_args: tuple[str, ...]) -> None:
    """Complete Non-live needs static fixtures, not live machine configuration."""
    focused = any(
        arg in {'-k', '-m', '--collect-only', '--deselect', '--ignore', '--ignore-glob', '--pyargs'}
        or arg.startswith(('-k', '-m', '--deselect=', '--ignore=', '--ignore-glob='))
        or (not arg.startswith('-') and (arg.endswith('.py') or '::' in arg or arg.startswith('tests/')))
        for arg in pytest_args
    )
    if focused:
        return
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        project = repo_root / 'tests' / '_org' / version / 'SampleProject.wproj'
        if not (project.parent / 'fixture-manifest.json').is_file():
            raise ReadinessBlocked(f'complete Non-live requires the static fixture manifest: {project.parent}; provision this checkout explicitly before retrying')
        validate_project_materialization(project, version=version)
    validate_process_readiness(scoped_process_snapshot(), scopes=(str(repo_root),))
