"""Finalize original condition probes through their one ScenarioLifecycle owner."""
from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from tests.destructive.support.exact_real_evidence import append_finalized_scenario_evidence
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle
from tests.support import condition_branch_evidence
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from wwise_waapi.headless import assert_port_free


def prepare_condition_finalization(*, item, owner: ScenarioLifecycle, status, reason, repo_root,
                                   candidate, version, started_at_unix_ns, host,
                                   observation_path: Path, transactions, capture):
    """Stop the original host, retaining successful resources until real teardown.

    This attaches to an already-owned lifecycle. It neither launches a host nor
    creates another owner, and it never promotes historical observations.
    """
    runtime = owner.runtime
    if runtime is None or owner._finished or not owner._lock_acquired:
        raise ValueError('Condition finalization needs its active original lifecycle')
    try:
        if (item.nodeid != capture['nodeid'] or candidate != capture['git_candidate']
                or version != runtime.version or host.get('isCommandLine') is not True):
            raise ValueError('Condition finalization differs from the original node/host/candidate')
        lock_handle = owner.lock._handle
        process = runtime.lifecycle.process
        launch_pid = process.pid if process is not None else None
        prefix = runtime.lifecycle._owned_wine_prefix()
        observation_hash = sha256(observation_path.read_bytes()).hexdigest()
    except BaseException as exc:
        # Evidence I/O/header failure must not strand an already-running native
        # owner. Stop once as blocked and retain the original diagnostic root.
        owner.finish('BLOCKED', reason=f'condition finalization preparation:{type(exc).__name__}:{str(exc)[:4096]}')
        raise
    prepared = owner.finish(status, reason='' if status == 'PASS' else reason,
                            defer_success_cleanup=status == 'PASS')

    def append(result, reports, *, original):
        append_finalized_scenario_evidence(
            repo_root=repo_root, candidate=candidate, version=version, nodeid=item.nodeid,
            phase_reports=reports, started_at_unix_ns=started_at_unix_ns,
            lifecycle=result.as_dict(), sandbox=runtime.sandbox, host=host,
            observation_path=observation_path, transactions=transactions,
            original_publisher=(lambda record: condition_branch_evidence.publish_condition_native_capture(
                capture, record, observation_path)) if original else None)

    def fresh_resources(actual):
        if (actual is not runtime or not owner._lock_acquired or owner.lock._handle is not lock_handle
                or lock_handle is None or lock_handle.closed):
            raise ValueError('Condition original lifecycle lock is no longer held')
        condition_branch_evidence.validate_condition_frozen_source(capture)
        if sha256(observation_path.read_bytes()).hexdigest() != observation_hash:
            raise ValueError('Condition original observation changed after host shutdown')
        lifecycle = runtime.lifecycle
        report = lifecycle.cleanup_report
        metadata = runtime.sandbox.metadata
        if (lifecycle.process is not None or report is None or not report.is_clean
                or launch_pid is None or report.launch_pid != launch_pid
                or metadata.process_cleanup_result != 'cleaned'
                or (metadata.process_cleanup_details or {}).get('residual_processes') != []):
            raise ValueError('Condition original native process cleanup is incomplete')
        if os.name == 'nt':
            raise ValueError('Native Windows condition post-teardown process attestation remains required')
        current_prefix = lifecycle._owned_wine_prefix()
        if (prefix is None or current_prefix != prefix
                or not prefix.resolve(strict=True).is_relative_to(runtime.owned_root.resolve(strict=True))):
            raise ValueError('Condition owned native prefix context changed')
        rows = lifecycle._process_rows(include_env=True, require_env=True)
        if not rows:
            raise ValueError('Condition fresh owned process inspection is unavailable')
        residual = [{'pid': pid, 'command': command} for pid, command in rows
                    if str(prefix) in command and (lifecycle._is_owned_wine_process_command(command, str(prefix))
                                                    or 'wwiseconsole.exe' in command.casefold())]
        if residual:
            raise ValueError('Condition owned native resources reappeared after teardown')
        assert_port_free(runtime.host, runtime.port)
        (runtime.evidence_root / 'condition-final-resources.json').write_text(json.dumps({
            'cleanup_report': asdict(report), 'owned_prefix': str(prefix), 'residual_processes': residual,
            'fresh_inspection': {'checked_at_unix_ns': time.time_ns(), 'row_count': len(rows)},
            'port': {'host': runtime.host, 'port': runtime.port, 'released': True}}, sort_keys=True), encoding='utf-8')

    def finalize(reports):
        complete = set(reports) == {'setup', 'call', 'teardown'} and all(
            reports.get(phase) in {'passed', 'failed', 'skipped'} for phase in ('setup', 'call', 'teardown'))
        passed = complete and all(value == 'passed' for value in reports.values())
        if not prepared.cleanup_deferred:
            append(prepared, reports, original=False)
            return
        if not passed:
            # The prepared receipt remains original. Revoke release permanently;
            # actual late node failure retains its sandbox rather than cleaning.
            owner.cancel_prepared_cleanup()
            outcome = 'FAIL' if 'failed' in reports.values() else 'BLOCKED'
            retained = replace(prepared, final_status=outcome, cleanup_deferred=False,
                               sandbox_retained=runtime.sandbox.sandbox_path.exists(),
                               errors=(*prepared.errors, 'node-phase:original pytest phases did not all pass'))
            (runtime.evidence_root / 'condition-node-outcome.json').write_text(json.dumps({
                'outcome': outcome, 'phase_reports': reports, 'lifecycle': retained.as_dict(),
                'prepared_lifecycle': prepared.as_dict(), 'acceptance': 'withheld'}, sort_keys=True), encoding='utf-8')
            if complete:
                append(retained, reports, original=False)
            else:
                raise ValueError('Condition original pytest phase reports are incomplete')
            return
        publication_started = False
        def publish(result):
            nonlocal publication_started
            publication_started = True
            append(result, reports, original=True)
        try:
            owner.release_prepared_cleanup(post_teardown_check=fresh_resources, publication_hook=publish)
        except BaseException as exc:
            # A publisher can fail after truthful finalized cleanup. Preserve
            # that receipt and diagnostics, withhold acceptance, never claim the
            # already-deleted sandbox was retained or the native edit failed.
            (runtime.evidence_root / 'condition-finalization-error.json').write_text(json.dumps({
                'phase': 'publication' if publication_started else 'post-teardown-or-cleanup',
                'acceptance': 'withheld', 'phase_reports': reports,
                'sandbox_retained': runtime.sandbox.sandbox_path.exists(),
                'error': {'type': type(exc).__name__, 'message': str(exc)[:4096]},
                'prepared_lifecycle': prepared.as_dict()}, sort_keys=True), encoding='utf-8')
            raise

    try:
        register_exact_evidence_finalizer(item, finalize)
    except BaseException:
        owner.cancel_prepared_cleanup()
        raise
    return prepared
