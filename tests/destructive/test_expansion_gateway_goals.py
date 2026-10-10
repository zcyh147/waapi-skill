"""Real public-Gateway business effects for selected expansion cases.

These probes exercise only the two closed Gateway operations. They do not
launch Codex or contribute Agent semantic credit.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from tests.destructive.test_expansion_case_preflight import (
    _LIVE_COMMANDS,
    _persist_preflight_failure,
    _record_oracle_call,
    expansion_runtime,
)
from tests.destructive.test_gateway_workflow_transaction_matrix import _WorkflowSandboxRuntime
from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, PreparedExpansionCase
from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError, make_public_gateway
from tests.semantic.support.codex_expansion_goal_probes import run_goal_probe
from tests.semantic.support.codex_expansion_oracle_reads import expansion_oracle_reader
from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall


pytestmark = [pytest.mark.live, pytest.mark.destructive]

_PREPARERS = {
    "M01": ("codex_expansion_music_case", "prepare_m01"),
    "C06": ("codex_expansion_rtpc_case", "prepare_c06"),
}


@pytest.mark.parametrize("case_id", ("M01", "C06"), ids=("M01-music-import", "C06-existing-rtpc"))
def test_expansion_gateway_goal_has_verified_business_effect(
    expansion_runtime: _WorkflowSandboxRuntime,
    case_id: str,
) -> None:
    runtime = expansion_runtime
    gateway_receipts: list[dict[str, Any]] = []
    oracle_receipts: list[dict[str, Any]] = []
    actor = OwnedDirectWaapiCall(host=runtime.lifecycle.host, port=runtime.port)
    case_result: dict[str, Any] | None = None
    failure: BaseException | None = None
    try:
        gateway = make_public_gateway(
            host=runtime.lifecycle.host,
            port=runtime.port,
            version=runtime.version,
            config_path=Path(runtime.env["WAAPI_SKILL_CONFIG_PATH"]),
            state_dir=runtime.state_dir,
            environment=runtime.env,
            receipts=gateway_receipts,
            live_commands=_LIVE_COMMANDS,
        )
        context = ExpansionCaseContext(
            version=runtime.version,
            scenario_id=f"GOAL_{runtime.version.replace('.', '_')}_{case_id}",
            project_path=runtime.sandbox.sandbox_project,
            asset_root=runtime.sandbox.sandbox_path / "ExpansionAssets" / f"goal-{case_id}",
            gateway=gateway,
            trusted_read=expansion_oracle_reader(
                version=runtime.version,
                read_call=lambda uri, args, options: _record_oracle_call(
                    actor, oracle_receipts, uri, args, options,
                ),
            ),
        )
        module_name, prepare_name = _PREPARERS[case_id]
        prepare = getattr(importlib.import_module(f"tests.semantic.support.{module_name}"),
                          prepare_name)
        prepared = prepare(context)
        assert isinstance(prepared, PreparedExpansionCase)
        assert prepared.required_assertions and prepared.read_object_ids
        result = run_goal_probe(context, case_id, prepared, gateway_receipts)
        assert all(value is True for value in result["assertions"].values())
        assert result["gateway_verification_state"] == "verified"
        assert result["business_state_verified"] is True
        case_result = {
            "category": f"expansion-gateway-goal-{case_id}",
            "status": "PASS",
            "verifier_strength": "closed_gateway_transaction_plus_independent_adapter_oracle",
            **result,
        }
    except BaseException as exc:  # noqa: BLE001 - preserve exact failed-only evidence
        failure = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        try:
            if not actor.close():
                cleanup_error = AssertionError("goal-probe trusted actor cleanup did not complete")
            elif not actor.fully_closed:
                cleanup_error = AssertionError("goal-probe trusted actor still owns a live thread")
        except BaseException as exc:  # noqa: BLE001 - preserve actor shutdown evidence
            cleanup_error = exc
        if failure is not None or cleanup_error is not None:
            report_error = failure or cleanup_error
            assert report_error is not None
            try:
                diagnostic = _persist_preflight_failure(
                    runtime,
                    case_id=f"goal-{case_id}",
                    error=report_error,
                    gateway_receipts=gateway_receipts,
                    oracle_receipts=oracle_receipts,
                    actor=actor,
                )
            except BaseException as diagnostic_error:  # noqa: BLE001 - keep primary failure
                report_error.add_note(f"Could not persist goal-probe diagnostics: {diagnostic_error}")
            else:
                runtime.category_results.append({
                    "category": f"expansion-gateway-goal-{case_id}",
                    "status": "FAIL" if failure is not None else "blocked",
                    "verifier_strength": "gateway_goal_failed_with_persisted_receipts",
                    "diagnostics_path": str(diagnostic),
                    "gateway_call_count": len(gateway_receipts),
                    "oracle_call_count": len(oracle_receipts),
                    "agent_pass": False,
                    "business_effect_verified": False,
                })
        elif case_result is not None:
            runtime.category_results.append(case_result)
        if cleanup_error is not None:
            if failure is not None:
                failure.add_note(f"Goal-probe trusted actor cleanup also failed: {cleanup_error}")
            else:
                raise cleanup_error
