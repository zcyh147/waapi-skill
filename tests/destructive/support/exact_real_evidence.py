"""Two-phase exact evidence and quarantine finalization for real-Wwise fixtures."""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]

from tests.destructive.support.category_evidence import (
    append_category_evidence,
    build_category_evidence_record,
    exact_transaction_outcomes,
)
from tests.destructive.support.sandbox_fixture import (
    LiveSandboxLock,
    SandboxProject,
    cleanup_sandbox,
)


def _selected_node_outcomes(
    request: pytest.FixtureRequest,
    module_file: Path,
    *,
    active_error: BaseException | None,
) -> list[dict[str, str]]:
    selected = [
        item
        for item in request.session.items
        if Path(str(item.path)).resolve(strict=False) == module_file.resolve(strict=True)
    ]
    outcomes: list[dict[str, str]] = []
    for item in selected:
        reports = getattr(item, "_waapi_phase_reports", {})
        setup = reports.get("setup")
        call = reports.get("call")
        if setup == "failed" or call == "failed":
            outcome = "FAIL"
        elif setup == "skipped" or call == "skipped":
            outcome = "SKIP"
        elif call == "passed":
            outcome = "PASS"
        else:
            outcome = "BLOCKED"
        outcomes.append({"nodeid": item.nodeid, "outcome": outcome})
    if active_error is not None and outcomes and not any(
        row["outcome"] in {"FAIL", "SKIP"} for row in outcomes
    ):
        outcomes[-1]["outcome"] = (
            "SKIP" if isinstance(active_error, pytest.skip.Exception) else "FAIL"
        )
    return outcomes


def _overall_outcome(
    node_outcomes: Sequence[Mapping[str, str]],
    *,
    deferred_error: BaseException | None,
    active_error: BaseException | None,
) -> str:
    if deferred_error is not None:
        return "FAIL"
    statuses = {row["outcome"] for row in node_outcomes}
    if "FAIL" in statuses:
        return "FAIL"
    if active_error is not None:
        return "SKIP" if isinstance(active_error, pytest.skip.Exception) else "FAIL"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "SKIP" in statuses:
        return "SKIP"
    return "PASS" if statuses == {"PASS"} else "BLOCKED"


def _observed_nonpass_sandbox_state(
    sandbox: SandboxProject,
    quarantine_path: Path | None,
) -> str:
    if quarantine_path is not None and quarantine_path.is_dir():
        return "quarantined"
    if sandbox.sandbox_path.exists():
        return "retained"
    return "quarantine_failed"


def finalize_exact_real_evidence(
    *,
    repo_root: Path,
    candidate: str,
    version: str,
    request: pytest.FixtureRequest,
    module_file: Path,
    started_at_unix_ns: int,
    active_error: BaseException | None,
    deferred_error: BaseException | None,
    sandbox: SandboxProject,
    lock: LiveSandboxLock,
    state_dir: Path,
    host: Mapping[str, Any],
    categories: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    case_cleanup_root: Path | None = None,
) -> BaseException | None:
    """Seal exact outcomes without permitting a late false PASS or lost failure sandbox."""

    transactions: list[dict[str, Any]] = []
    try:
        transactions = exact_transaction_outcomes(state_dir)
    except BaseException as exc:  # noqa: BLE001 - transaction evidence is part of the gate
        deferred_error = deferred_error or exc

    try:
        lock.__exit__(None, None, None)
    except BaseException as exc:  # noqa: BLE001 - release failure must become non-PASS
        deferred_error = deferred_error or exc

    node_outcomes = _selected_node_outcomes(
        request,
        module_file,
        active_error=active_error,
    )
    outcome = _overall_outcome(
        node_outcomes,
        deferred_error=deferred_error,
        active_error=active_error,
    )

    quarantine_path: Path | None = None
    try:
        quarantine_path = cleanup_sandbox(sandbox, keep=True, failed=outcome != "PASS")
        if quarantine_path is None:
            raise AssertionError("two-phase exact evidence did not retain the sandbox")
        if case_cleanup_root is not None and case_cleanup_root.exists():
            shutil.rmtree(case_cleanup_root)
    except BaseException as exc:  # noqa: BLE001 - retained state remains the evidence boundary
        deferred_error = deferred_error or exc
        outcome = "FAIL"

    def append_record(*, phase: str, record_outcome: str, sandbox_state: str) -> None:
        append_category_evidence(
            repo_root=repo_root,
            candidate=candidate,
            version=version,
            host=host,
            categories=categories,
            source=source,
            residual_state={
                "sandbox": sandbox_state,
                "sandbox_path": str(sandbox.sandbox_path),
                "quarantine_path": str(quarantine_path) if quarantine_path else None,
                "process_cleanup": sandbox.metadata.process_cleanup_result,
                "residual_processes": (
                    sandbox.metadata.process_cleanup_details or {}
                ).get("residual_processes", []),
            },
            invocation={
                "selected_test_nodeids": [row["nodeid"] for row in node_outcomes],
                "node_outcomes": node_outcomes,
                "started_at_unix_ns": started_at_unix_ns,
                "finished_at_unix_ns": time.time_ns(),
                "phase": phase,
                "outcome": record_outcome,
            },
            transactions=transactions,
        )

    if outcome != "PASS":
        try:
            append_record(
                phase="final",
                record_outcome=outcome,
                sandbox_state=_observed_nonpass_sandbox_state(
                    sandbox,
                    quarantine_path,
                ),
            )
        except BaseException as exc:  # noqa: BLE001 - quarantine remains durable
            deferred_error = deferred_error or exc
        return deferred_error

    try:
        append_record(
            phase="prepared",
            record_outcome="PENDING",
            sandbox_state="quarantined_pending_release",
        )
    except BaseException as exc:  # noqa: BLE001 - quarantine remains durable
        return deferred_error or exc

    try:
        assert quarantine_path is not None
        shutil.rmtree(quarantine_path)
    except BaseException as exc:  # noqa: BLE001 - final record must report cleanup failure
        deferred_error = deferred_error or exc
        try:
            append_record(
                phase="final",
                record_outcome="FAIL",
                sandbox_state=_observed_nonpass_sandbox_state(
                    sandbox,
                    quarantine_path,
                ),
            )
        except BaseException as evidence_exc:  # noqa: BLE001
            deferred_error = deferred_error or evidence_exc
        return deferred_error

    try:
        append_record(phase="final", record_outcome="PASS", sandbox_state="deleted")
    except BaseException as exc:  # noqa: BLE001 - prepared row prevents a false PASS
        deferred_error = deferred_error or exc
    return deferred_error


def append_finalized_scenario_evidence(
    *, repo_root: Path, candidate: str, version: str, nodeid: str,
    phase_reports: Mapping[str, str], started_at_unix_ns: int,
    lifecycle: Mapping[str, Any], sandbox: SandboxProject,
    host: Mapping[str, Any], observation_path: Path,
    transactions: Sequence[Mapping[str, Any]],
    original_publisher: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Use the category-v3 writer after an original ScenarioLifecycle is final.

    Called by pytest teardown, after its actual call report exists. The caller
    retains the original observation artifact; this never promotes old logs or
    supplies a new sandbox lifecycle. An original publisher stages its final
    category snapshot with its wrapper; non-PASS runs retain the category log.
    """
    if (lifecycle.get("contract") != "waapi-skill.codex-semantic-scenario-lifecycle/v3"
            or lifecycle.get("final_status") not in {"PASS", "FAIL", "BLOCKED"}
            or phase_reports.get("setup") not in {"passed", "failed", "skipped"}
            or phase_reports.get("call") not in {"passed", "failed", "skipped"}
            or phase_reports.get("teardown") not in {"passed", "failed", "skipped"}
            or not nodeid):
        raise AssertionError("scenario category evidence requires a finalized lifecycle and original pytest node report")
    outcome = ("FAIL" if "failed" in phase_reports.values() else
               "SKIP" if "skipped" in phase_reports.values() else lifecycle["final_status"])
    before, after = lifecycle.get("source_hash_before"), lifecycle.get("source_hash_after")
    cleanup = sandbox.metadata.process_cleanup_result
    residual = (sandbox.metadata.process_cleanup_details or {}).get("residual_processes")
    if outcome == "PASS" and (
        lifecycle.get("sandbox_retained") is not False or lifecycle.get("errors") != []
        or not isinstance(before, Mapping) or before.get("strategy") != "full" or not before.get("digest")
        or before != after or lifecycle.get("source_mtime_before_ns") is None
        or lifecycle["source_mtime_before_ns"] != lifecycle.get("source_mtime_after_ns")
        or sandbox.sandbox_path.exists() or cleanup != "cleaned" or residual != []
    ):
        raise AssertionError("scenario category PASS lacks exact source preservation and completed cleanup")
    native_version = host.get("version", {})
    if (type(host.get("isCommandLine")) is not bool
            or any(type(native_version.get(key)) is not int for key in ("year", "major", "minor", "build"))
            or f"{native_version['year']}.{native_version['major']}" != version):
        raise AssertionError("scenario category host requires the original exact getInfo version and host")
    observation = {"artifact": str(observation_path.resolve()),
                   "sha256": hashlib.sha256(observation_path.read_bytes()).hexdigest()}
    publish_original = original_publisher is not None and outcome == "PASS"
    writer = build_category_evidence_record if publish_original else append_category_evidence
    record = writer(
        repo_root=repo_root, candidate=candidate, version=version,
        host={"display_name": host.get("displayName"), "is_command_line": host["isCommandLine"],
              "version": dict(native_version)},
        categories=[{"category": "metadata-condition", "status": outcome if outcome in {"PASS", "FAIL"} else "blocked",
                     "verifier_strength": "operation_specific_readback", "observation": observation}],
        source={"hash_before": before.get("digest") if isinstance(before, Mapping) else None,
                "hash_after": after.get("digest") if isinstance(after, Mapping) else None,
                "mtime_before_ns": lifecycle.get("source_mtime_before_ns"),
                "mtime_after_ns": lifecycle.get("source_mtime_after_ns")},
        residual_state={"sandbox": "retained" if sandbox.sandbox_path.exists() else "deleted",
                        "sandbox_path": str(sandbox.sandbox_path), "quarantine_path": lifecycle.get("quarantine_path"),
                        "process_cleanup": cleanup, "residual_processes": residual},
        invocation={"selected_test_nodeids": [nodeid], "node_outcomes": [{"nodeid": nodeid, "outcome": outcome}],
                    "started_at_unix_ns": started_at_unix_ns, "finished_at_unix_ns": time.time_ns(),
                    "phase": "final", "outcome": outcome},
        transactions=transactions,
    )
    if publish_original:
        assert original_publisher is not None and record is not None
        original_publisher(record)


__all__ = ["finalize_exact_real_evidence", "append_finalized_scenario_evidence"]
