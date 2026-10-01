"""Expansion adapters inside the existing real-scenario and fresh-task lanes."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, ExpectedCapabilityBoundary
from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError
from tests.semantic.support.codex_expansion_oracle_reads import expansion_oracle_reader
from tests.semantic.support.codex_expansion_reconciliation import ExpansionReconciliationGuard, ReconciliationCleanupError, run_owned_gateway
from tests.semantic.support.codex_expansion_profile import validate_model_configuration
from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall, HeavyProjectRunnerOptions
from tests.semantic.support.codex_project_prelaunch_v3 import ProjectPrelaunchRequest, make_project_prelaunch_hook
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle
from tests.semantic.support.codex_task_runner_v3 import run_expansion_codex_task


OUTCOME_CONTRACT = "waapi-skill.integration-expansion-project-outcome/v1"


@dataclass(frozen=True)
class ExpansionRunnerOptions(HeavyProjectRunnerOptions):
    campaign_inputs_sha256: str = ""
_ADAPTERS = {
    "C01": ("voice", "prepare_c01"), "C03": ("media", "prepare_c03"),
    "C06": ("rtpc", "prepare_c06"), "C08": ("attenuation", "prepare_c08"),
    "C09": ("effects", "prepare_c09"), "M01": ("music", "prepare_m01"),
    "M05": ("stinger", "prepare_m05"),
}


def fixture_gateway(*, skill_source: Path, runtime: Any, version: str, receipts: list):
    """Public setup calls own a subprocess; never share txaio with the oracle."""
    environment = {**os.environ, **runtime.runner_environment,
        "WAAPI_SKILL_CONFIG_PATH": str(runtime.owned_root / "setup-config.json"),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8:strict"}
    def gateway(arguments, *, timeout_seconds=45):
        if not arguments or str(arguments[0]).startswith("-"):
            raise CaseBoundaryError("fixture Gateway requires one public command")
        command = [sys.executable, str(skill_source / "scripts" / "run.py"), "gateway.py",
            "--host", runtime.host, "--port", str(runtime.port), "--version", version,
            "--state-dir", str(runtime.owned_root / "setup-state"), "--timeout", str(min(30, timeout_seconds)), *arguments]
        started = time.monotonic()
        try:
            completed = run_owned_gateway(command, environment=environment, timeout_seconds=timeout_seconds)
        except (subprocess.TimeoutExpired, OSError, ReconciliationCleanupError) as exc:
            receipts.append({"argv": list(arguments), "elapsed_seconds": time.monotonic() - started,
                "processes_reaped": not isinstance(exc, ReconciliationCleanupError),
                "error": {"type": type(exc).__name__, "message": str(exc).encode("utf-8")[:2048].decode("utf-8", "ignore")}})
            raise
        if len(completed.stdout.encode("utf-8")) > 1_048_576:
            raise CaseBoundaryError("fixture Gateway receipt exceeds its byte ceiling")
        try:
            payload = json.loads(completed.stdout)
        except (ValueError, TypeError) as exc:
            raise CaseBoundaryError("fixture Gateway returned no complete JSON receipt") from exc
        receipts.append({"argv": list(arguments), "exit_code": completed.returncode, "payload": payload})
        if not isinstance(payload, dict) or completed.returncode != 0 or payload.get("ok") is not True:
            raise CaseBoundaryError(f"public fixture Gateway failed: {payload}")
        endpoint = payload.get("endpoint")
        if endpoint is not None and (endpoint.get("host") != runtime.host or endpoint.get("port") != runtime.port):
            raise CaseBoundaryError("fixture Gateway reached a different endpoint")
        return payload
    return gateway


@dataclass(frozen=True)
class ExpansionOutcome:
    scenario_id: str
    version: str
    status: str
    reason: str
    scenario_root: str
    task_root: str | None
    thread_id: str | None
    checks: Mapping[str, Any]
    lifecycle: Mapping[str, Any] | None
    inputs_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {"contract": OUTCOME_CONTRACT, **asdict(self)}


def run_expansion_unit(unit: Any, *, scenario_root: Path, options: Any) -> ExpansionOutcome:
    validate_model_configuration(options.model, options.reasoning_effort, options.service_tier)
    if unit.case_id not in _ADAPTERS or unit.version not in {"2022.1", "2025.1"}:
        raise ValueError("expansion unit is outside its closed adapter registry")
    root = Path(scenario_root).resolve(strict=False)
    lifecycle = ScenarioLifecycle(
        scenario_id=unit.unit_id, version=unit.version, scenario_root=root,
        live_environment=options.live_environment,
        prelaunch_hook=make_project_prelaunch_hook(ProjectPrelaunchRequest(
            scenario_id=unit.unit_id, languages=("SFX", "English(US)", "Japanese") if unit.case_id == "C01" else ("SFX",),
            platforms=("Windows",),
        )),
    )
    runtime = None
    direct = None
    result = None
    lifecycle_result = None
    checks: dict[str, Any] = {}
    status, reason = "BLOCKED", ""
    task_root = None
    boundary_proven = False
    try:
        runtime = lifecycle.start()
        direct = OwnedDirectWaapiCall(host=runtime.host, port=runtime.port)
        checks["fixture_gateway_receipts"] = []
        gateway = fixture_gateway(skill_source=options.skill_source, runtime=runtime,
                                  version=unit.version, receipts=checks["fixture_gateway_receipts"])
        gateway(["config-set", "--project-modification-policy", "ask_before_changes"])
        reconciliation_guard = ExpansionReconciliationGuard(version=unit.version, host=runtime.host, port=runtime.port,
            gateway=gateway, trusted_read=expansion_oracle_reader(version=unit.version, read_call=direct))
        context = ExpansionCaseContext(unit.version, unit.unit_id, runtime.sandbox.sandbox_project,
            runtime.asset_root, reconciliation_guard.gateway, reconciliation_guard.trusted_read)
        module_name, function_name = _ADAPTERS[unit.case_id]
        adapter = importlib.import_module(f"tests.semantic.support.codex_expansion_{module_name}_case")
        prepared = getattr(adapter, function_name)(context)
        if prepared.policy != unit.policy:
            raise CaseBoundaryError("prepared case policy differs from frozen profile")
        scoped_paths: dict[str, str] = {}
        for object_id in sorted(prepared.read_object_ids):
            row = context.trusted_read("identity", [object_id])[0]
            if not isinstance(row.get("path"), str):
                raise CaseBoundaryError("scope identity has no exact Wwise path")
            scoped_paths[object_id] = row["path"]
        checks["fixture_prepared"] = True
        checks["fixture_before"] = prepared.before
        task_root = runtime.evidence_root / "codex-task"
        result = run_expansion_codex_task(unit=unit, prepared=prepared, task_root=task_root,
            options=options, runner_environment=runtime.runner_environment, scoped_paths=scoped_paths,
            reconcile_after_failure=lambda: reconciliation_guard.reconcile(prepared.snapshot))
        checks["task"] = result
        checks["trusted_oracle_calls"] = direct.calls
        status = result.get("status") or ("PASS" if result.get("passed") is True else "FAIL")
        reason = str(result.get("error") or "")
    except ExpectedCapabilityBoundary as exc:
        boundary_proven = (unit.case_id == "M05" and unit.version == "2022.1"
                           and exc.case_id == "M05" and exc.version == "2022.1")
        checks["capability_boundary"] = {"case_id": exc.case_id, "version": exc.version,
            "boundary_code": exc.boundary_code, "evidence": exc.evidence,
            "agent_started": False, "business_pass": False}
        reason = str(exc)
        status = "BLOCKED"  # boundary evidence is accounted separately, never a semantic PASS
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        status = "FAIL" if task_root is not None else "BLOCKED"
    finally:
        if direct is not None:
            try:
                if direct.close() is not True:
                    status, reason = "BLOCKED", "trusted oracle client did not prove disconnect"
            except Exception as exc:
                status, reason = "BLOCKED", f"trusted oracle cleanup: {exc}"
                boundary_proven = False
        if runtime is not None:
            lifecycle_result = lifecycle.finish(status, reason=reason)
            status = lifecycle_result.final_status
    if (boundary_proven and task_root is None and lifecycle_result is not None
            and lifecycle_result.source_hash_before == lifecycle_result.source_hash_after
            and lifecycle_result.source_mtime_before_ns == lifecycle_result.source_mtime_after_ns
            and not any(not item.startswith("scenario:") for item in lifecycle_result.errors)
            and direct is not None and direct.fully_closed):
        status = "BOUNDARY_PROVEN"
    outcome = ExpansionOutcome(unit.unit_id, unit.version, status, reason, str(root),
        str(task_root) if task_root else None, result.get("thread_id") if result else None,
        checks, lifecycle_result.as_dict() if lifecycle_result else None, options.campaign_inputs_sha256)
    if root.exists():
        (root / "outcome.json").write_text(json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return outcome
