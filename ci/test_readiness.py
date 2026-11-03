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

if __package__:
    from .run_program_tests import PROGRAM_PYTEST_OPTIONS_REQUIRING_VALUE
else:
    from run_program_tests import PROGRAM_PYTEST_OPTIONS_REQUIRING_VALUE

# Identify operands using the locked pytest core and pytest-cov option arities
# plus this repo's Authoring option. This classifies argv only; pytest still
# validates it, and Program retains its separate closed flag allowlist.
_PYTEST_OPTIONS_REQUIRING_VALUE = PROGRAM_PYTEST_OPTIONS_REQUIRING_VALUE | {
    '-m', '-r', '-c', '-o', '--override-ini', '--ignore', '--ignore-glob',
    '--deselect', '--basetemp', '--rootdir', '--confcutdir', '--junitxml',
    '--junit-xml', '--log-file', '--log-level', '--log-file-level',
    '--owned-authoring-batch-root',
    '-p', '-W', '--pythonwarnings', '--config-file', '--import-mode',
    '--verbosity', '--show-capture', '--code-highlight', '--pdbcls',
    '--pastebin', '--junitprefix', '--junit-prefix', '--doctest-report',
    '--doctest-glob', '--lfnf', '--last-failed-no-failures', '--assert',
    '--log-format', '--log-date-format', '--log-cli-level', '--log-cli-format',
    '--log-cli-date-format', '--log-file-mode', '--log-file-format',
    '--log-file-date-format', '--log-auto-indent', '--log-disable',
    '--cov-report', '--cov-config', '--cov-fail-under', '--cov-context',
}
_PYTEST_OPTIONS_WITH_OPTIONAL_VALUE = {'--debug', '--cache-show', '--cov'}


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
    # ps renders literal command text, not reusable shell-escaped argv. Only
    # inspect the fixed shell/execution prefix; punctuation in later paths is data.
    argv = command.split(None, 3)
    if argv and Path(argv[0]).name in {'bash', 'sh', 'zsh', 'fish'} and any(
        option in {'-c', '-lc', '-ic'} for option in argv[1:3]
    ):
        return False  # Script source text is not proof of a running real child.
    if any(marker in lowered for marker in ('wwiseconsole.sh', 'wwiseconsole.exe', 'wwise.exe')):
        return True
    if 'test_driver.py' in lowered:
        return (re.search(r'(?:--mode|-m)\s+(?:smoke|live|destructive|matrix|focused|all)(?:\s|$)', lowered) is not None
                or re.search(r'''test_driver\.py["']?\s+(?:202[1-5]\.1|all)\s+(?:smoke|live|destructive|matrix|focused|all)(?:\s|$)''', lowered) is not None)
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


# Closed, fixture-dependent selections already present in the developer suite.
_STATIC_FIXTURE_TEST_VERSIONS = {
    'tests/unit/test_org_fixture_source.py': ('2022.1',),
    'tests/unit/test_2023_fixture_source.py': ('2023.1',),
    'tests/unit/test_2024_fixture_inventory.py': ('2024.1',),
    'tests/unit/test_2025_1_fixture_inventory.py': ('2025.1',),
    'tests/unit/test_2023_cross_version_audit.py': ('2023.1',),
    'tests/unit/test_2024_cross_version_audit.py': ('2024.1',),
}


# These selected nodes prove fake safety/resource behavior without source payloads.
_STATIC_FIXTURE_FREE_NODES = {
    'test_2023_destructive_target_rejects_installed_and_org_fixture_paths',
    'test_2024_destructive_target_rejects_installed_and_org_fixture_paths',
    'test_2025_1_destructive_target_rejects_installed_and_org_fixture_paths',
}
_STATIC_AUDIT_FIXTURE_NODES = {
    'tests/unit/test_2023_cross_version_audit.py': {
        'test_2023_and_2022_resources_are_independently_addressable',
        'test_2023_fixture_tree_is_versioned_and_contains_no_committed_runtime_artifacts',
    },
    'tests/unit/test_2024_cross_version_audit.py': {
        'test_default_dispatcher_remains_2022_1_and_explicit_2024_1_dispatch_succeeds',
    },
}


def pytest_token_roles(arguments: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Identify positive locators without reinterpreting or validating pytest values."""
    selectors: list[str] = []
    options: list[str] = []
    expects_value = False
    optional_value = False
    literal_selectors = False
    for argument in arguments:
        if literal_selectors:
            selectors.append(argument)
            continue
        if expects_value:
            expects_value = False
            if not optional_value or not argument.startswith("-"):
                continue
        if argument == '--':
            literal_selectors = True
            continue
        if argument.startswith('-'):
            options.append(argument.split('=', 1)[0])
            optional_value = argument in _PYTEST_OPTIONS_WITH_OPTIONAL_VALUE
            expects_value = optional_value or argument in _PYTEST_OPTIONS_REQUIRING_VALUE
            continue
        selectors.append(argument)
    return tuple(selectors), tuple(options)


def validate_nonlive_readiness(repo_root: Path, pytest_args: tuple[str, ...]) -> None:
    """Check bounded known static selections, not general pytest dependencies."""
    selectors, options = pytest_token_roles(pytest_args)
    if any(option in {'--collect-only', '--co'} for option in options):
        return
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    root = repo_root.resolve()
    broad_roots = {root, root / 'tests', root / 'tests' / 'unit'}
    selected_versions: set[str] = set()
    broad = False
    for argument in selectors:
        selector = Path(argument.split('::', 1)[0]).expanduser()
        if not selector.is_absolute():
            selector = root / selector
        selector = selector.resolve(strict=False)
        if selector in broad_roots:
            broad = True
        if selector.is_relative_to(root):
            relative = selector.relative_to(root).as_posix()
            node = argument.partition('::')[2].split('::', 1)[0].split('[', 1)[0]
            if node and (node in _STATIC_FIXTURE_FREE_NODES or (
                relative in _STATIC_AUDIT_FIXTURE_NODES
                and node not in _STATIC_AUDIT_FIXTURE_NODES[relative]
            )):
                continue
            selected_versions.update(_STATIC_FIXTURE_TEST_VERSIONS.get(relative, ()))
    focused = bool(selectors) or any(
        option in {'--deselect', '--ignore', '--ignore-glob', '--pyargs'}
        or option.startswith(('-k', '-m'))
        for option in options
    )
    if broad or not focused:
        selected_versions.update(SUPPORTED_WWISE_VERSION_KEYS)
    if not selected_versions:
        return
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        if version not in selected_versions:
            continue
        project = root / 'tests' / '_org' / version / 'SampleProject.wproj'
        if not (project.parent / 'fixture-manifest.json').is_file():
            raise ReadinessBlocked(f'selected Non-live tests require the static fixture manifest: {project.parent}; provision this checkout explicitly before retrying')
        validate_project_materialization(project, version=version)
    validate_process_readiness(scoped_process_snapshot(), scopes=(str(root),))
