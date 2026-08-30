"""Two-phase exact evidence and quarantine finalization for real-Wwise fixtures."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]

from tests.destructive.support.category_evidence import (
    append_category_evidence,
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
            append_record(phase="final", record_outcome=outcome, sandbox_state="quarantined")
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
            append_record(phase="final", record_outcome="FAIL", sandbox_state="quarantined")
        except BaseException as evidence_exc:  # noqa: BLE001
            deferred_error = deferred_error or evidence_exc
        return deferred_error

    try:
        append_record(phase="final", record_outcome="PASS", sandbox_state="deleted")
    except BaseException as exc:  # noqa: BLE001 - prepared row prevents a false PASS
        deferred_error = deferred_error or exc
    return deferred_error


__all__ = ["finalize_exact_real_evidence"]
