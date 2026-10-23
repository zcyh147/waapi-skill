"""Authoring nodes attach to an existing owned ScenarioLifecycle; no launcher."""
from __future__ import annotations

from pathlib import Path
import os
import json
import shutil
import time
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from typing import Sequence
import pytest

from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle, ScenarioRuntime
from tests.destructive.support.sandbox_fixture import hash_project, wait_for_port_release
from tests.destructive.support.category_evidence import exact_git_candidate, append_category_evidence, exact_transaction_outcomes
from wwise_waapi.native_catalog import load_native_catalog
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
from wwise_waapi.host_paths import localize_waapi_host_path
from tests.semantic.support.codex_expansion_runtime import fixture_gateway
from wwise_waapi.filesystem_security import path_is_link_or_reparse
from tests.destructive.support.transport_semantics import (
    NODEID as TRANSPORT_SEMANTICS_NODEID, CONTRACT as TRANSPORT_SEMANTICS_CONTRACT,
    MIXED_NODEID as TRANSPORT_MIXED_NODEID, MIXED_CONTRACT as TRANSPORT_MIXED_CONTRACT,
    OLDER_NODEID as TRANSPORT_OLDER_NODEID, OLDER_CONTRACT as TRANSPORT_OLDER_CONTRACT,
    OLDER_FIXTURES, stage_owned_older_transport_media,
)
from tests.destructive.support.profiler_capture import (
    NODEID as PROFILER_CAPTURE_NODEID, METER_2024_NODEID, READERS_2025_NODEID, CAPTURE_READS_NODEID, CAPTURE_MISSING_NODEID, CAPTURE_NODE_OUTCOMES,
    stage_owned_2024_meter_media,
    capture_node_outcomes,
    stage_owned_capture_read_media,
    READER_OUTCOMES, CAPTURE_READ_OUTCOMES,
)
from tests.destructive.support.loaded_media_probe import NODEID as LOADED_EVENT_NODEID, OUTCOME as LOADED_EVENT_OUTCOME

CAPTURE_NODE_OUTCOMES = {**CAPTURE_NODE_OUTCOMES, LOADED_EVENT_NODEID: (LOADED_EVENT_OUTCOME,)}


MEDIA_PRESERVATION_DIAGNOSTIC_NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_authoring_2024_media_preservation_metadata_diagnostic')

SOUNDCASTER_FRONTEND_DIAGNOSTIC_NODEID = ('tests/destructive/test_authoring_ui_business_live.py::'
    'test_authoring_2024_soundcaster_frontend_image_diagnostic')
DIAGNOSTIC_NODEIDS = (MEDIA_PRESERVATION_DIAGNOSTIC_NODEID, SOUNDCASTER_FRONTEND_DIAGNOSTIC_NODEID)
TRANSPORT_OBSERVATION_NODES = {
    TRANSPORT_SEMANTICS_NODEID: (TRANSPORT_SEMANTICS_CONTRACT, 'transport-semantics.json', 'selected-transport-semantics-observations'),
    TRANSPORT_MIXED_NODEID: (TRANSPORT_MIXED_CONTRACT, 'transport-mixed-semantics.json', 'mixed-transport-semantics-observations'),
    TRANSPORT_OLDER_NODEID: (TRANSPORT_OLDER_CONTRACT, 'transport-older-semantics.json', 'older-transport-semantics-observations'),
}


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
        if build != load_native_catalog(owner.version, 'wwise-authoring')['provenance']['build']:
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
        self.owner_lock_handle = owner.lock._handle
        self.launch_pid = runtime.lifecycle.process.pid
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
        if (any(observed.get(field) != self.info.get(field) for field in ('isCommandLine', 'processId', 'sessionId', 'version'))
                or observed.get('isCommandLine') is not False
                or endpoint != {'host': runtime.host, 'port': runtime.port, 'url': f'ws://{runtime.host}:{runtime.port}/waapi'}):
            raise ValueError('Node live Authoring ownership differs from its lifecycle proof')
        project_identity = status.get('project')
        if not isinstance(project_identity, dict):
            raise ValueError('Node live Authoring ownership lacks its exact sandbox project')
        if runtime.version == '2021.1':
            # 2021 status exposes the Project hierarchy identity, not its file.
            identity_fields = ('id', 'name', 'type', 'path')
            if (project_identity.get('type') != 'Project'
                    or any(not isinstance(project_identity.get(key), str) or not project_identity[key] for key in identity_fields)):
                raise ValueError('Node live Authoring ownership lacks its exact Project identity')
            observation = gateway(['query-object', '--exact-id', project_identity['id'],
                '--include', 'file-path', '--max-results', '1'])
            rows = observation.get('objects')
            if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
                    or observation.get('projection_complete') is False
                    or any(rows[0].get(key) != project_identity[key] for key in identity_fields)
                    or not isinstance(rows[0].get('file_path'), str) or not rows[0]['file_path']):
                raise ValueError('Node live Authoring ownership lacks its exact Project file observation')
            project_path = rows[0]['file_path']
        else:
            project_path = project_identity.get('path', '')
        try:
            project = Path(localize_waapi_host_path(project_path)).resolve(strict=True)
        except (ValueError, OSError, TypeError) as exc:
            raise ValueError('Node live Authoring ownership lacks its exact sandbox project') from exc
        if project != self.runtime.sandbox.sandbox_project.resolve(strict=True):
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
        categories = [{'category': ('soundcaster-frontend-diagnostic' if row['nodeid'] == SOUNDCASTER_FRONTEND_DIAGNOSTIC_NODEID else 'media-preservation-diagnostic' if row['nodeid'] == MEDIA_PRESERVATION_DIAGNOSTIC_NODEID else 'authoring-layout'), 'nodeid': row['nodeid'],
                         'status': ('FAIL' if row['outcome'] == 'FAIL' else 'blocked') if row['nodeid'] in DIAGNOSTIC_NODEIDS else ('PASS' if outcome == 'PASS' else 'FAIL' if row['outcome'] == 'FAIL' else 'blocked'),
                         'verifier_strength': ('bounded_public_diagnostic_no_business_effect_proof' if row['nodeid'] == SOUNDCASTER_FRONTEND_DIAGNOSTIC_NODEID else 'bounded_public_read_only_diagnostic_no_business_effect_proof' if row['nodeid'] == MEDIA_PRESERVATION_DIAGNOSTIC_NODEID else 'public_gateway_exact_node_and_post_teardown_owned_proofs'),
                         **({'business_preservation_verified': False,
                             'coverage_credit': 'none; diagnostic observation only',
                             'reason': ('Captured images require independent selected-session/value review; no preservation proof'
                                 if row['nodeid'] == SOUNDCASTER_FRONTEND_DIAGNOSTIC_NODEID else
                                 'Collected metadata/settings do not prove media maintenance or preservation')}
                            if row['nodeid'] in DIAGNOSTIC_NODEIDS else {}),
                         **({'observation_artifact': self.observation_artifacts[row['nodeid']]}
                            if row['nodeid'] in self.observation_artifacts else {}),
                         **({'batch_finalization': self.batch_seal_descriptor}
                            if outcome == 'PASS' else {})} for row in outcomes if row['nodeid'] not in CAPTURE_NODE_OUTCOMES and row['nodeid'] not in TRANSPORT_OBSERVATION_NODES]
        for capture_nodeid in (node for node in self.selected_nodeids if node in CAPTURE_NODE_OUTCOMES):
            # Consume the exact archived collector output, including partial
            # observations. A passing sibling never fills another outcome.
            report = {}
            descriptor = self.observation_artifacts.get(capture_nodeid)
            if descriptor:
                archived = json.loads(Path(descriptor['path']).read_text(encoding='utf-8'))
                root = Path(archived['artifacts']['native-evidence']['path'])
                report_path = root / 'profiler-capture.json'
                if report_path.exists():
                    report = json.loads(report_path.read_text(encoding='utf-8'))
                    if (report.get('contract') != 'waapi-skill.owned-profiler-capture/v1'
                            or report.get('candidate') != self.candidate or report.get('version') != runtime.version):
                        raise ValueError('Profiler capture report context differs from its owned batch')
            names = ((LOADED_EVENT_OUTCOME,) if capture_nodeid == LOADED_EVENT_NODEID
                else capture_node_outcomes(capture_nodeid, runtime.version))
            for name in names:
                observation = report.get('outcomes', {}).get(name, {'outcome': 'BLOCKED'})
                business = observation.get('outcome', 'BLOCKED')
                categories.append({'category': name, 'nodeid': capture_nodeid,
                    'status': 'PASS' if outcome == 'PASS' and business == 'PASS' else 'FAIL' if business == 'FAIL' else 'blocked',
                    'business_outcome': business, 'cleanup_complete': report.get('cleanup', {}).get('complete', False),
                    'verifier_strength': 'independent_public_capture_outcome_and_owned_post_teardown_proofs',
                    **({'reader_observation_status': observation.get('evidence', {}).get('observation_status', 'BLOCKED'),
                        'owned_identity_observed': observation.get('evidence', {}).get('owned_identity_observed', False),
                        'attribution_boundary': 'A nonempty read alone grants no owned reader-obligation credit; no acoustic or measurement-effect proof',
                        **({'attribution_scope': observation.get('evidence', {}).get('attribution_scope', 'owned-object'),
                            'attribution_boundary': 'Attribution follows the reader scope; capture-level data does not establish Sound/control effects; no acoustic proof',
                            **({'preparation_or_streaming_control_effect_verified': False}
                                if name in ('profiler-loaded-media-observation', 'profiler-streamed-media-observation') else {})}
                            if capture_nodeid in (CAPTURE_READS_NODEID, CAPTURE_MISSING_NODEID, LOADED_EVENT_NODEID) else {})}
                        if (capture_nodeid in (READERS_2025_NODEID, LOADED_EVENT_NODEID) or capture_nodeid in (CAPTURE_READS_NODEID, CAPTURE_MISSING_NODEID)
                            and name in (*READER_OUTCOMES, *CAPTURE_READ_OUTCOMES)) else {}),
                    **({'coverage_scope': 'selected_missing_runtime_reads', 'parent_workflow_complete': False,
                        'remaining_same_parent_obligations': report.get('remaining_same_parent_obligations', {})}
                        if capture_nodeid == CAPTURE_MISSING_NODEID else {}),
                    **({'observation_artifact': descriptor} if descriptor else {}),
                    **({'batch_finalization': self.batch_seal_descriptor} if outcome == 'PASS' else {})})
        for nodeid in (node for node in self.selected_nodeids if node in TRANSPORT_OBSERVATION_NODES):
            contract, filename, category = TRANSPORT_OBSERVATION_NODES[nodeid]
            descriptor = self.observation_artifacts.get(nodeid)
            report = {}
            if descriptor:
                archive = json.loads(Path(descriptor['path']).read_text(encoding='utf-8'))
                path = Path(archive['artifacts']['native-evidence']['path']) / filename
                if path.exists():
                    report = json.loads(path.read_text(encoding='utf-8'))
                    if (report.get('contract') != contract
                            or report.get('candidate') != self.candidate or report.get('version') != runtime.version
                            or report.get('business_effect_verified') is not False
                            or report.get('coverage_credit') != 'none_pending_semantics'):
                        raise ValueError('Transport observation report context or effect boundary changed')
            observed = (outcome == 'PASS' and report.get('complete') is True
                and report.get('cleanup', {}).get('complete') is True
                and report.get('observation_task_status') == 'PASS')
            categories.append({'category': category,
                'nodeid': nodeid, 'status': 'blocked',
                'observation_task_status': 'PASS' if observed else 'BLOCKED',
                'business_effect_verified': False, 'coverage_credit': 'none_pending_semantics',
                'cleanup_complete': report.get('cleanup', {}).get('complete', False),
                'verifier_strength': 'bounded_state_observations_semantics_unresolved',
                'cases': report.get('cases', []),
                **({'observation_artifact': descriptor} if descriptor else {}),
                **({'batch_finalization': self.batch_seal_descriptor} if observed else {})})
        append_category_evidence(repo_root=self.repo_root, candidate=self.candidate, version=runtime.version,
            host={'display_name': self.info['displayName'], 'is_command_line': False, 'version': self.info['version']},
            categories=categories,
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
        if (not self.owner._lock_acquired or self.owner.lock._handle is not self.owner_lock_handle
                or self.owner_lock_handle.closed):
            raise ValueError('Post-teardown Authoring owner lock is no longer held')
        self._archive_observations()
        report = lifecycle.cleanup_report
        if (lifecycle.process is not None or report is None or not report.is_clean or report.launch_pid != self.launch_pid
                or runtime.sandbox.metadata.process_cleanup_result != 'cleaned'):
            raise ValueError('Post-teardown Authoring host cleanup is incomplete')
        # This exact owned-prefix inspection is read-only. Never kill a new
        # process or retry a mutation during evidence release.
        prefix = lifecycle._owned_wine_prefix()
        if os.name == 'nt':
            raise ValueError('Native Windows Authoring post-teardown process attestation remains required')
        if (prefix is None or prefix != self.owned_prefix or not prefix.resolve(strict=True).is_relative_to(runtime.owned_root)):
            raise ValueError('Post-teardown Authoring owned prefix context changed')
        rows = lifecycle._process_rows(include_env=True, require_env=True)
        if not rows:
            raise ValueError('Post-teardown owned process inspection is unavailable')
        residual = [{'pid': pid, 'command': command} for pid, command in rows
                    if str(prefix) in command and (lifecycle._is_owned_wine_process_command(command, str(prefix))
                                                   or 'wwise.exe' in command.casefold())]
        self.last_resources = {'residual_processes': residual}
        if residual:
            raise ValueError('Owned Authoring resources reappeared after teardown')
        # A clean process can precede socket release; keep the existing fixed
        # deadline and exact port, with no new host or mutation attempt.
        wait_for_port_release(runtime.host, runtime.port)
        self.last_resources.update(cleanup_report=asdict(report), owned_prefix=str(prefix),
            fresh_inspection={'checked_at_unix_ns': time.time_ns(), 'row_count': len(rows)},
            port={'host': runtime.host, 'port': runtime.port, 'released': True})

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
             'tests/semantic/support', 'tests/conftest.py', 'tests/support/exact_evidence_finalization.py',
             'tests/maintenance/branch_audit_completion.py', 'ci/test_driver.py',
             'ci/run_live_test_command.py', 'ci/resolve_live_test_config.py', 'ci/test_readiness.py']
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
    """Install the actual owner after the caller validates the exact collection."""
    if getattr(config, '_waapi_authoring_batch', None) is not None:
        raise ValueError('An owned Authoring batch is already installed')
    batch = AuthoringBatchAdapter(owner=owner, repo_root=repo_root, selected_nodeids=selected_nodeids)
    config.pluginmanager.register(batch, 'waapi-owned-authoring-batch')
    config._waapi_authoring_batch = batch
    return batch


# Only nodes that consume this actual owner can enter its native batch. Other
# families remain explicit integration work until they use the same protocol.
OWNED_AUTHORING_NODEIDS = (
    *DIAGNOSTIC_NODEIDS,
    TRANSPORT_SEMANTICS_NODEID,
    TRANSPORT_MIXED_NODEID,
    TRANSPORT_OLDER_NODEID,
    PROFILER_CAPTURE_NODEID,
    READERS_2025_NODEID,
    CAPTURE_READS_NODEID,
    LOADED_EVENT_NODEID,
    CAPTURE_MISSING_NODEID,
    METER_2024_NODEID,
    'tests/destructive/test_authoring_ui_business_live.py::test_authoring_layout_owned_registration_and_switch',
    *('tests/destructive/test_authoring_ui_business_live.py::test_authoring_layout_owned_view_lifecycle[' + variant + ']'
      for variant in ('omitted', 'x-only', 'y-only', 'both')),
)

# General hostability does not grant a node new version support. New older-host
# collectors need their own explicit entry after their matching fixture proof.
OWNED_AUTHORING_NODE_VERSIONS = {
    **dict.fromkeys(OWNED_AUTHORING_NODEIDS, ('2024.1', '2025.1')),
    **dict.fromkeys(DIAGNOSTIC_NODEIDS, ('2024.1',)),
    METER_2024_NODEID: ('2024.1',),
    PROFILER_CAPTURE_NODEID: ('2025.1',),
    READERS_2025_NODEID: ('2025.1',),
    CAPTURE_READS_NODEID: SUPPORTED_WWISE_VERSION_KEYS,
    LOADED_EVENT_NODEID: ('2025.1',),
    CAPTURE_MISSING_NODEID: SUPPORTED_WWISE_VERSION_KEYS,
    TRANSPORT_SEMANTICS_NODEID: ('2025.1',),
    TRANSPORT_MIXED_NODEID: ('2025.1',),
    TRANSPORT_OLDER_NODEID: tuple(OLDER_FIXTURES),
}


def configure_authoring_batch_owner(config, items, *, repo_root: Path):
    """Allocate the existing lifecycle only after a closed exact collection."""
    raw_root = config.getoption('owned_authoring_batch_root', default=None)
    if raw_root is None:
        return None
    selected = tuple(item.nodeid for item in items)
    if (not selected or len(selected) > 64 or len(set(selected)) != len(selected)
            or not set(selected).issubset(OWNED_AUTHORING_NODEIDS)
            or tuple(config.args) != selected):
        raise pytest.UsageError('Owned Authoring requires exact explicitly selected owner-aware node IDs')
    if any(config.getoption(key, default=None) for key in ('keyword', 'markexpr', 'deselect', 'numprocesses', 'forked')):
        raise pytest.UsageError('Owned Authoring does not accept filtered or parallel native batches')
    if os.getenv('PYTEST_XDIST_WORKER'):
        raise pytest.UsageError('Owned Authoring cannot launch from a parallel worker')
    if config.getoption('collectonly', default=False) or config.getoption('setupplan', default=False):
        return None
    if (os.getenv('WWISE_VERSION') not in SUPPORTED_WWISE_VERSION_KEYS
            or any(os.getenv(name) != '1' for name in ('WWISE_LIVE', 'WWISE_DESTRUCTIVE', 'WWISE_AUTHORING_LIVE'))):
        raise pytest.UsageError('Owned Authoring requires an explicit supported destructive Authoring test context')
    if any(os.getenv('WWISE_VERSION') not in OWNED_AUTHORING_NODE_VERSIONS[nodeid] for nodeid in selected):
        raise pytest.UsageError('Selected owned Authoring node is not available on the requested version')
    if (set(selected).intersection(DIAGNOSTIC_NODEIDS)
            and (len(selected) != 1 or os.getenv('WWISE_VERSION') != '2024.1')):
        raise pytest.UsageError('Media preservation diagnosis requires only its one matching 2024 Authoring node')
    if PROFILER_CAPTURE_NODEID in selected and (len(selected) != 1 or os.getenv('WWISE_VERSION') != '2025.1'):
        raise pytest.UsageError('Owned Profiler capture requires only its matching 2025 Authoring node')
    if READERS_2025_NODEID in selected and (len(selected) != 1 or os.getenv('WWISE_VERSION') != '2025.1'):
        raise pytest.UsageError('Owned Profiler readers require only their matching 2025 Authoring node')
    if set(selected).intersection((CAPTURE_READS_NODEID, CAPTURE_MISSING_NODEID)) and len(selected) != 1:
        raise pytest.UsageError('Owned capture reads require their exact single node')
    if LOADED_EVENT_NODEID in selected and len(selected) != 1:
        raise pytest.UsageError('Loaded Event probe requires its exact single 2025 node')
    if METER_2024_NODEID in selected and (len(selected) != 1 or os.getenv('WWISE_VERSION') != '2024.1'):
        raise pytest.UsageError('Owned meter projection requires only its matching 2024 Authoring node')
    if set(selected).intersection((TRANSPORT_SEMANTICS_NODEID, TRANSPORT_MIXED_NODEID)) and (len(selected) != 1 or os.getenv('WWISE_VERSION') != '2025.1'):
        raise pytest.UsageError('Transport observations require only their matching 2025 Authoring node')
    if TRANSPORT_OLDER_NODEID in selected and len(selected) != 1:
        raise pytest.UsageError('Older transport observations require their exact single node')
    root = Path(raw_root)
    if (not root.is_absolute() or os.path.lexists(root)
            or any(path_is_link_or_reparse(part) for part in root.parents)
            or root != root.resolve(strict=False)):
        raise ValueError('Owned Authoring batch root must be a fresh absolute path without aliases')
    source_context = candidate_source_context(repo_root)
    def check_frozen_source(_sandbox, _assets, _io):
        if candidate_source_context(repo_root) != source_context:
            raise ValueError('Owned Authoring source candidate changed before launch')
        if selected == (METER_2024_NODEID,):
            stage_owned_2024_meter_media(_sandbox, _io)
        if selected == (TRANSPORT_OLDER_NODEID,):
            stage_owned_older_transport_media(_sandbox, _io, version=os.environ['WWISE_VERSION'])
        if selected in ((CAPTURE_READS_NODEID,), (CAPTURE_MISSING_NODEID,)):
            stage_owned_capture_read_media(_sandbox, _io, version=os.environ['WWISE_VERSION'])
    live_environment = dict(os.environ)
    if selected in ((PROFILER_CAPTURE_NODEID,), (READERS_2025_NODEID,), (CAPTURE_READS_NODEID,), (CAPTURE_MISSING_NODEID,), (LOADED_EVENT_NODEID,), (METER_2024_NODEID,), (TRANSPORT_SEMANTICS_NODEID,), (TRANSPORT_MIXED_NODEID,), (TRANSPORT_OLDER_NODEID,)):
        live_environment['AK_AUTOMATION_MODE'] = '1'
    owner = ScenarioLifecycle(scenario_id='owned-authoring-batch', version=os.environ['WWISE_VERSION'],
        scenario_root=root, live_environment=live_environment, host_kind='wwise-authoring',
        launch_environment_overrides={'HOME': str(root / 'owned/private-home')},
        prelaunch_hook=check_frozen_source)
    owner.start()
    try:
        return install_authoring_batch(config, owner=owner, repo_root=repo_root, selected_nodeids=selected)
    except BaseException:
        if not owner._finished:
            owner.finish('BLOCKED', reason='owned Authoring adapter installation failed')
        raise


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
