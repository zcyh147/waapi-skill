"""Authoring nodes attach to an existing owned ScenarioLifecycle; no launcher."""
from __future__ import annotations

from pathlib import Path
import os
import json
import shutil
import time
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from typing import Sequence
import pytest

from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle, ScenarioRuntime
from tests.destructive.support.sandbox_fixture import hash_project
from tests.destructive.support.category_evidence import exact_git_candidate, append_category_evidence, exact_transaction_outcomes
from wwise_waapi.headless import assert_port_free
from wwise_waapi.native_catalog import load_native_catalog
from wwise_waapi.host_paths import localize_waapi_host_path
from tests.semantic.support.codex_expansion_runtime import fixture_gateway
from wwise_waapi.filesystem_security import path_is_link_or_reparse


class AuthoringBatchAdapter:
    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, items):
        yield
        actual = [item.nodeid for item in items]
        if len(actual) != len(self.selected_nodeids) or set(actual) != set(self.selected_nodeids):
            raise pytest.UsageError('Collected tests differ from the exact owned Authoring node selection')

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        result = yield
        report = result.get_result()
        reports = getattr(item, '_waapi_phase_reports', {})
        reports[report.when] = report.outcome
        item._waapi_phase_reports = reports

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_sessionfinish(self, session, exitstatus):
        """Wait for every teardown and other session hook before granting credit."""
        hooks = yield
        try:
            hooks.get_result()
        except BaseException:
            if not session.exitstatus:
                session.exitstatus = pytest.ExitCode.TESTS_FAILED
        try:
            result = self.finalize(session.items, exitstatus=int(session.exitstatus))
            if result['outcome'] != 'PASS' and not session.exitstatus:
                session.exitstatus = pytest.ExitCode.TESTS_FAILED
        except BaseException as exc:
            if not session.exitstatus:
                session.exitstatus = pytest.ExitCode.TESTS_FAILED
            self._invalidate_batch_seal()
            payload = {'outcome': 'BLOCKED', 'error': {'type': type(exc).__name__, 'message': str(exc)[:4096]}}
            try:
                if not self.owner._finished:
                    self.lifecycle_result = self.owner.finish('BLOCKED', reason='batch session finalization failed')
            except BaseException as cleanup_exc:
                payload['cleanup_error'] = {'type': type(cleanup_exc).__name__, 'message': str(cleanup_exc)[:4096]}
            finally:
                self.owner.cancel_prepared_cleanup()
            (self.runtime.evidence_root / 'authoring-batch-sessionfinish-error.json').write_text(
                json.dumps(payload, ensure_ascii=False) + '\n', encoding='utf-8')

    def __init__(self, *, owner: ScenarioLifecycle, repo_root: Path, selected_nodeids: Sequence[str]):
        if not isinstance(owner, ScenarioLifecycle) or owner.runtime is None or not owner._lock_acquired or owner._finished:
            raise ValueError('Authoring batch requires an active ScenarioLifecycle and its held lock')
        runtime = owner.runtime
        if not isinstance(runtime, ScenarioRuntime) or runtime.version != owner.version or runtime.scenario_root != owner.scenario_root:
            raise ValueError('Authoring runtime context differs from its lifecycle owner')
        info = runtime.lifecycle.ready_result
        if not isinstance(info, dict) or info.get('isCommandLine') is not False:
            raise ValueError('Batch owner must prove a matching Wwise Authoring host')
        version = info.get('version', {})
        build = '.'.join(str(version.get(key)) for key in ('year', 'major', 'minor', 'build'))
        if owner.version not in {'2024.1', '2025.1'} or build != load_native_catalog(owner.version, 'wwise-authoring')['provenance']['build']:
            raise ValueError('Authoring owner build differs from the independently pinned native context')
        if owner.lock._handle is None or owner.lock._handle.closed:
            raise ValueError('Authoring ownership lock is not held')
        sandbox = runtime.sandbox
        paths = [runtime.scenario_root, runtime.owned_root, sandbox.source_project,
                 sandbox.sandbox_project, sandbox.sandbox_root, sandbox.sandbox_path]
        if any(not path.is_absolute() or any(path_is_link_or_reparse(part) for part in (path, *path.parents)) for path in paths):
            raise ValueError('Authoring ownership paths must be absolute without links/reparse points')
        source, project = sandbox.source_project.resolve(strict=True), sandbox.sandbox_project.resolve(strict=True)
        owned = runtime.owned_root.resolve(strict=True)
        metadata = sandbox.metadata
        if (not owned.is_relative_to(runtime.scenario_root.resolve(strict=True))
                or not project.is_relative_to(owned) or source.is_relative_to(owned)
                or project == source or project.parent == source.parent
                or metadata.source_path != str(source) or metadata.sandbox_project_path != str(project)
                or metadata.launch_project_path != str(project) or metadata.identity_verified is not True
                or metadata.wwise_version != runtime.version
                or metadata.selected_port != runtime.lifecycle.port
                or runtime.lifecycle.process is None or runtime.lifecycle.process.poll() is not None):
            raise ValueError('Authoring sandbox ownership/project/process context is inconsistent')
        if (runtime.source_hash_before.strategy != 'full'
                or metadata.source_hash != runtime.source_hash_before
                or hash_project(sandbox.source_root, preferred_strategy='full') != runtime.source_hash_before
                or source.stat().st_mtime_ns != runtime.source_mtime_before_ns):
            raise ValueError('Authoring source context differs from its full prelaunch proof')
        user_keys = ('USERPROFILE', 'APPDATA', 'LOCALAPPDATA') if os.name == 'nt' else ('HOME',)
        overrides = owner.launch_environment_overrides
        if (not set(user_keys) <= set(overrides)
                or any(runtime.runner_environment.get(key) != value
                       or not Path(value).is_dir() or not Path(value).resolve(strict=True).is_relative_to(owned)
                       for key, value in overrides.items())):
            raise ValueError('Authoring batch requires lifecycle-bound isolated user state')
        if not selected_nodeids or len(selected_nodeids) > 64 or len(set(selected_nodeids)) != len(selected_nodeids):
            raise ValueError('Authoring batch needs a bounded exact unique node selection')
        self.runtime = runtime
        self.owner = owner
        self.repo_root = repo_root
        self.selected_nodeids = tuple(selected_nodeids)
        self.source_context = candidate_source_context(repo_root)
        self.candidate = self.source_context["candidate"]
        self.info = deepcopy(info)
        self.receipts = {}
        self.node_runtimes = {}
        self.started_at = time.time_ns()
        self.lifecycle_result = None
        self.finalized = False
        self.prepared_written = False
        self.observation_artifacts = {}
        self.transactions = []
        self.last_resources = {}
        self.owned_prefix = runtime.lifecycle._owned_wine_prefix()
        self.batch_seal_path = runtime.evidence_root / 'authoring-batch-finalization.json'
        self.batch_seal_descriptor = None

    def node_gateway(self, nodeid: str):
        if (nodeid not in self.selected_nodeids or self.owner.runtime is not self.runtime
                or self.owner._finished or not self.owner._lock_acquired
                or self.runtime.lifecycle.process is None):
            raise ValueError('Node has no active live Authoring ownership')
        if nodeid in self.receipts:
            raise ValueError('A native node cannot be attached twice')
        node_root = self.runtime.owned_root / 'authoring-nodes' / sha256(nodeid.encode()).hexdigest()[:24]
        node_root.mkdir(parents=True, exist_ok=False)
        runtime = replace(self.runtime, owned_root=node_root,
            runner_environment={**self.runtime.runner_environment, 'WWISE_EVIDENCE_DIR': str(node_root / 'native-evidence')})
        receipts = self.receipts[nodeid] = []
        self.node_runtimes[nodeid] = runtime
        gateway = fixture_gateway(skill_source=self.repo_root / 'skills/waapi-skill', runtime=runtime,
                                  version=runtime.version, receipts=receipts)
        gateway(['config-set', '--wwise-version', runtime.version, '--waapi-host', runtime.host,
                 '--waapi-port', str(runtime.port), '--project-modification-policy', 'ask_before_changes'])
        status = gateway(['status'])
        observed, endpoint = status.get('wwise', {}), status.get('endpoint', {})
        try:
            project = Path(localize_waapi_host_path(status.get('project', {}).get('path', ''))).resolve(strict=True)
        except (ValueError, OSError, TypeError) as exc:
            raise ValueError('Node live Authoring ownership lacks its exact sandbox project') from exc
        if (any(observed.get(field) != self.info.get(field) for field in ('isCommandLine', 'processId', 'sessionId', 'version'))
                or observed.get('isCommandLine') is not False
                or endpoint != {'host': runtime.host, 'port': runtime.port, 'url': f'ws://{runtime.host}:{runtime.port}/waapi'}
                or project != self.runtime.sandbox.sandbox_project.resolve(strict=True)):
            raise ValueError('Node live Authoring ownership differs from its lifecycle proof')
        return gateway

    def _node_outcomes(self, items):
        indexed = {item.nodeid: item for item in items}
        outcomes = []
        for nodeid in self.selected_nodeids:
            reports = getattr(indexed.get(nodeid), '_waapi_phase_reports', {})
            states = [reports.get(phase) for phase in ('setup', 'call', 'teardown')]
            state = ('FAIL' if 'failed' in states else 'SKIP' if 'skipped' in states
                     else 'PASS' if states == ['passed', 'passed', 'passed'] else 'BLOCKED')
            outcomes.append({'nodeid': nodeid, 'outcome': state})
        return outcomes

    def _archive_observations(self):
        """Seal original Gateway receipts and exact state/native evidence trees."""
        destination = self.runtime.evidence_root / 'authoring-node-observations'
        destination.mkdir(exist_ok=True)
        transactions = []
        for nodeid, receipts in self.receipts.items():
            token = sha256(nodeid.encode()).hexdigest()[:24]
            target = destination / (token + '.json')
            runtime = self.node_runtimes[nodeid]
            state = runtime.owned_root / 'setup-state'
            node_transactions = exact_transaction_outcomes(state)
            artifacts = {}
            for name in ('setup-state', 'native-evidence'):
                source = runtime.owned_root / name
                manifest = evidence_tree_manifest(source)
                archive = destination / (token + '-' + name)
                if source.exists() and not target.exists():
                    shutil.copytree(source, archive)
                if evidence_tree_manifest(archive) != manifest:
                    raise ValueError('Authoring original and archived observation trees differ')
                artifacts[name] = {'path': str(archive), 'files': manifest}
            raw = (json.dumps({'nodeid': nodeid, 'candidate': self.candidate, 'source_context': self.source_context,
                'receipts': receipts, 'transactions': node_transactions, 'artifacts': artifacts},
                ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError('Authoring node receipts exceed their archive byte ceiling')
            descriptor = {'path': str(target), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
            if target.exists():
                if (path_is_link_or_reparse(target) or target.read_bytes() != raw
                        or self.observation_artifacts.get(nodeid) != descriptor):
                    raise ValueError('Authoring node observations changed after preparation')
            else:
                with target.open('xb') as stream:
                    stream.write(raw)
                self.observation_artifacts[nodeid] = descriptor
            transactions.extend(node_transactions)
        if len({row['transaction_id'] for row in transactions}) != len(transactions):
            raise ValueError('Native nodes cannot share one transaction identity')
        self.transactions = transactions

    def _append(self, outcomes, *, phase, outcome):
        runtime, sandbox = self.runtime, self.runtime.sandbox
        source_after, mtime_after = None, None
        if phase == 'final':
            try:
                source_after = hash_project(sandbox.source_root, preferred_strategy='full').digest
                mtime_after = sandbox.source_project.stat().st_mtime_ns
            except (OSError, ValueError):
                pass
        append_category_evidence(repo_root=self.repo_root, candidate=self.candidate, version=runtime.version,
            host={'display_name': self.info['displayName'], 'is_command_line': False, 'version': self.info['version']},
            categories=[{'category': 'authoring-layout', 'nodeid': row['nodeid'],
                         'status': 'PASS' if outcome == 'PASS' else 'FAIL' if row['outcome'] == 'FAIL' else 'blocked',
                         'verifier_strength': 'public_gateway_exact_node_and_post_teardown_owned_proofs',
                         **({'observation_artifact': self.observation_artifacts[row['nodeid']]}
                            if row['nodeid'] in self.observation_artifacts else {}),
                         **({'batch_finalization': self.batch_seal_descriptor}
                            if outcome == 'PASS' else {})} for row in outcomes],
            source={'project': str(sandbox.source_project), 'hash_scope': 'all-source-regular-file-content',
                    'hash_algorithm': 'sha256', 'hash_before': runtime.source_hash_before.digest,
                    'hash_after': source_after, 'mtime_before_ns': runtime.source_mtime_before_ns, 'mtime_after_ns': mtime_after},
            residual_state={'sandbox': 'deleted' if not runtime.owned_root.exists() else 'retained',
                            'sandbox_path': str(sandbox.sandbox_path),
                            'quarantine_path': self.lifecycle_result.quarantine_path if self.lifecycle_result else None,
                            'process_cleanup': sandbox.metadata.process_cleanup_result or 'pending',
                            'residual_processes': self.last_resources.get('residual_processes', [])},
            invocation={'selected_test_nodeids': list(self.selected_nodeids), 'node_outcomes': outcomes,
                        'started_at_unix_ns': self.started_at, 'finished_at_unix_ns': time.time_ns(),
                        'phase': phase, 'outcome': outcome}, transactions=self.transactions)

    def prepare_stop(self, items):
        """A module fixture may stop the owner; its last report still gates release."""
        if self.lifecycle_result is not None or self.owner._finished:
            raise ValueError('Authoring batch owner was already stopped')
        self._archive_observations()
        indexed = {item.nodeid: item for item in items}
        body_passed = all(all(getattr(indexed.get(nodeid), '_waapi_phase_reports', {}).get(phase) == 'passed'
                             for phase in ('setup', 'call')) for nodeid in self.selected_nodeids)
        body_passed = body_passed and all(
            getattr(indexed.get(nodeid), '_waapi_phase_reports', {}).get('teardown') in {None, 'passed'}
            for nodeid in self.selected_nodeids)
        coherent = candidate_source_context(self.repo_root) == self.source_context
        self.lifecycle_result = self.owner.finish('PASS' if body_passed and coherent else 'BLOCKED',
                                                  defer_success_cleanup=body_passed and coherent)
        self.finalize(items, terminal=False)
        return self.lifecycle_result

    def _fresh_resource_check(self, runtime):
        lifecycle = runtime.lifecycle
        self._archive_observations()
        report = lifecycle.cleanup_report
        if (lifecycle.process is not None or report is None or not report.is_clean
                or runtime.sandbox.metadata.process_cleanup_result != 'cleaned'):
            raise ValueError('Post-teardown Authoring host cleanup is incomplete')
        # This exact owned-prefix inspection is read-only. Never kill a new
        # process or retry a mutation during evidence release.
        prefix = lifecycle._owned_wine_prefix()
        if os.name == 'nt':
            raise ValueError('Native Windows Authoring post-teardown process attestation remains required')
        if (prefix is None or prefix != self.owned_prefix or not prefix.resolve(strict=True).is_relative_to(runtime.owned_root)):
            raise ValueError('Post-teardown Authoring owned prefix context changed')
        rows = lifecycle._process_rows(include_env=True)
        if not rows:
            raise ValueError('Post-teardown owned process inspection is unavailable')
        residual = [{'pid': pid, 'command': command} for pid, command in rows
                    if str(prefix) in command and (lifecycle._is_owned_wine_process_command(command, str(prefix))
                                                   or 'wwise.exe' in command.casefold())]
        self.last_resources = {'residual_processes': residual}
        if residual:
            raise ValueError('Owned Authoring resources reappeared after teardown')
        assert_port_free(runtime.host, runtime.port)

    def _invalidate_batch_seal(self):
        if self.batch_seal_path.exists():
            self.batch_seal_path.rename(self.runtime.evidence_root / f'authoring-batch-finalization-failed-{time.time_ns()}.json')

    def _publish(self, outcomes, result):
        """Only the last successful publication makes all node rows consumable."""
        self.lifecycle_result = result
        seal = {'contract': 'waapi-skill.authoring-batch-finalization/v1', 'outcome': 'PASS',
                'candidate': self.candidate, 'version': self.runtime.version,
                'host': {'display_name': self.info['displayName'], 'is_command_line': False, 'version': self.info['version']},
                'selected_test_nodeids': list(self.selected_nodeids), 'node_outcomes': outcomes,
                'started_at_unix_ns': self.started_at, 'source_context': self.source_context,
                'observations': self.observation_artifacts, 'transactions': self.transactions,
                'lifecycle': result.as_dict(), 'resources': self.last_resources}
        raw = (json.dumps(seal, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
        self.batch_seal_descriptor = {'artifact': str(self.batch_seal_path), 'sha256': sha256(raw).hexdigest()}
        self._append(outcomes, phase='final', outcome='PASS')
        with self.batch_seal_path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def finalize(self, items, *, terminal: bool = True, exitstatus: int = 0):
        """Only complete actual phase reports plus fresh release proof grant PASS."""
        if self.finalized:
            raise ValueError('Authoring batch was already finalized')
        outcomes = self._node_outcomes(items)
        if not terminal:
            if not self.prepared_written:
                self._append(outcomes, phase='prepared', outcome='PENDING')
                self.prepared_written = True
            return {'outcome': 'PENDING', 'phase': 'prepared'}
        eligible = (exitstatus == 0 and all(row['outcome'] == 'PASS' for row in outcomes)
                    and set(self.receipts) == set(self.selected_nodeids)
                    and candidate_source_context(self.repo_root) == self.source_context)
        if self.lifecycle_result is None:
            if self.owner._finished:
                raise ValueError('Unprepared external owner shutdown cannot certify native results')
            self.prepare_stop(items)
        if eligible and self.lifecycle_result.cleanup_deferred:
            def publish(result):
                self._publish(outcomes, result)
            try:
                self.lifecycle_result = self.owner.release_prepared_cleanup(
                    post_teardown_check=self._fresh_resource_check, publication_hook=publish)
            except BaseException as exc:
                self._invalidate_batch_seal()
                self.finalization_error = {'type': type(exc).__name__, 'message': str(exc)[:4096]}
                (self.runtime.evidence_root / 'authoring-batch-finalization-error.json').write_text(
                    json.dumps({'outcome': 'BLOCKED', 'error': self.finalization_error}, ensure_ascii=False) + '\n', encoding='utf-8')
                outcome = 'BLOCKED'
            else:
                self.finalized = True
                return {'outcome': 'PASS', 'phase': 'final'}
        else:
            # A known node/batch failure permanently revokes this preparation;
            # a later caller cannot release an originally non-passing root.
            self.owner.cancel_prepared_cleanup()
            outcome = 'FAIL' if any(row['outcome'] == 'FAIL' for row in outcomes) else 'BLOCKED'
        self._append(outcomes, phase='final', outcome=outcome)
        self.finalized = True
        return {'outcome': outcome, 'phase': 'final'}


def candidate_source_context(repo_root: Path):
    """Bind the fixture, lifecycle and packaged sources to one clean Git commit."""
    import subprocess
    roots = ['skills/waapi-skill', 'tests/destructive/support', 'tests/destructive/test_authoring_ui_business_live.py',
             'tests/semantic/support', 'tests/conftest.py', 'tests/maintenance/branch_audit_completion.py']
    changed = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=normal', '--', *roots],
        cwd=repo_root, text=True, capture_output=True, check=True).stdout
    if changed.strip():
        raise ValueError('Authoring native evidence requires a clean frozen source candidate')
    files = subprocess.run(['git', 'ls-files', '--', *roots], cwd=repo_root,
                           text=True, capture_output=True, check=True).stdout.splitlines()
    if not files:
        raise ValueError('Authoring native source candidate has no tracked proof files')
    return {'candidate': exact_git_candidate(repo_root), 'sources': {
        name: sha256((repo_root / name).read_bytes()).hexdigest() for name in sorted(files)}}


def install_authoring_batch(config, *, owner: ScenarioLifecycle, repo_root: Path, selected_nodeids: Sequence[str]):
    """The existing lifecycle owner supplies the object before pytest collection."""
    if getattr(config, '_waapi_authoring_batch', None) is not None:
        raise ValueError('An owned Authoring batch is already installed')
    batch = AuthoringBatchAdapter(owner=owner, repo_root=repo_root, selected_nodeids=selected_nodeids)
    config.pluginmanager.register(batch, 'waapi-owned-authoring-batch')
    config._waapi_authoring_batch = batch
    return batch


def evidence_tree_manifest(root: Path):
    """Bounded regular-file archive identities; links and changing bytes fail."""
    if not root.exists():
        if root.is_symlink():
            raise ValueError('Authoring observation tree contains a link')
        return []
    if not root.is_dir() or path_is_link_or_reparse(root):
        raise ValueError('Authoring observation tree must be a regular directory')
    rows, total = [], 0
    for path in sorted(root.rglob('*')):
        if path_is_link_or_reparse(path):
            raise ValueError('Authoring observation tree contains a link/reparse point')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('Authoring observation tree contains a non-regular file')
        size = path.stat().st_size
        total += size
        if len(rows) >= 4096 or total > 32 * 1024 * 1024:
            raise ValueError('Authoring observation tree exceeds archive bounds')
        raw = path.read_bytes()
        if len(raw) != size:
            raise ValueError('Authoring observation file changed during archive')
        rows.append({'path': path.relative_to(root).as_posix(), 'sha256': sha256(raw).hexdigest(), 'bytes': size})
    return rows
