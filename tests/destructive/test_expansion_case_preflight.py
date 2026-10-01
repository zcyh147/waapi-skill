"""Real setup/oracle preflight for expansion cases, never Fresh Agent acceptance.

Each parameter owns a separate copied SampleProject and existing lifecycle.
Only fixture setup executes mutations; the requested Agent change is not run.
Select this file explicitly with the repository destructive test driver after
freezing the candidate. This module never starts Codex.
"""

from __future__ import annotations

import importlib
import hashlib
import json
import os
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _WorkflowSandboxRuntime,
    workflow_sandbox_runtime as _existing_workflow_sandbox_runtime,
)
from tests.semantic.support.codex_expansion_cases import (
    ExpansionCaseContext,
    ExpectedCapabilityBoundary,
    PreparedExpansionCase,
)
from tests.semantic.support.codex_expansion_case_helpers import (
    CaseBoundaryError,
    make_public_gateway,
)
from tests.semantic.support.codex_expansion_oracle_reads import expansion_oracle_reader
from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall


pytestmark = [pytest.mark.live, pytest.mark.destructive]


def canonical_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _record_oracle_call(
    actor: OwnedDirectWaapiCall,
    receipts: list[dict[str, Any]],
    uri: str,
    args: Mapping[str, Any],
    options: Mapping[str, Any],
) -> Any:
    if uri != "ak.wwise.core.object.get" or len(receipts) >= 128:
        raise CaseBoundaryError("trusted preflight oracle exceeded its fixed read contract")
    row: dict[str, Any] = {"uri": uri, "args": dict(args), "options": dict(options)}
    started = time.monotonic()
    try:
        result = actor(uri, args, options)
    except BaseException as exc:  # noqa: BLE001 - preserve the exact bounded actor failure
        row.update({
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
            "error": str(exc)[:4_096],
        })
        receipts.append(row)
        raise
    try:
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        row.update({
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
            "error": "oracle result is not finite JSON",
        })
        receipts.append(row)
        raise CaseBoundaryError("trusted preflight oracle returned a non-JSON result") from exc
    row["elapsed_seconds"] = round(time.monotonic() - started, 3)
    row["response_bytes"] = len(encoded)
    if len(encoded) <= 32_768:
        row["response"] = result
    else:
        row["response_sha256"] = hashlib.sha256(encoded).hexdigest()
        row["response_excerpt"] = encoded[:4_096].decode("utf-8", errors="replace")
    receipts.append(row)
    return result


def _persist_preflight_failure(
    runtime: _WorkflowSandboxRuntime,
    *,
    case_id: str,
    error: BaseException,
    gateway_receipts: Sequence[Mapping[str, Any]],
    oracle_receipts: Sequence[Mapping[str, Any]],
    actor: OwnedDirectWaapiCall,
) -> Path:
    root = runtime.state_dir.parent / "expansion-preflight-diagnostics"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{runtime.version.replace('.', '-')}-{case_id}.json"
    data = {
        "contract": "waapi-skill.expansion-case-preflight-diagnostics/v1",
        "case_id": case_id,
        "version": runtime.version,
        "candidate": runtime.candidate,
        "endpoint": {"host": actor.host, "port": actor.port},
        "error": {"type": type(error).__name__, "message": str(error)[:8_192]},
        "gateway_receipts": list(gateway_receipts),
        "oracle_receipts": list(oracle_receipts),
        "trusted_actor_fully_closed": actor.fully_closed,
        "trusted_actor_calls": actor.calls,
    }
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if len(encoded.encode("utf-8")) > 8 * 1_048_576:
        raise CaseBoundaryError("preflight failure diagnostics exceeded the 8 MiB evidence ceiling")
    path.write_text(encoded, encoding="utf-8")
    return path

_PREPARERS = {
    "C01": ("codex_expansion_voice_case", "prepare_c01"),
    "C03": ("codex_expansion_media_case", "prepare_c03"),
    "C06": ("codex_expansion_rtpc_case", "prepare_c06"),
    "C08": ("codex_expansion_attenuation_case", "prepare_c08"),
    "C09": ("codex_expansion_effects_case", "prepare_c09"),
    "M01": ("codex_expansion_music_case", "prepare_m01"),
    "M05": ("codex_expansion_stinger_case", "prepare_m05"),
}
_LIVE_COMMANDS = frozenset({
    "query-object", "metadata", "status", "draft-bind-object",
    "draft-discover-fields", "draft-discover-types", "draft-check",
    "preview-from-draft", "execute", "verify",
})
_SNAPSHOT_COMMANDS = frozenset({"query-object", "metadata", "status"})
_BASELINE_FALSE_ASSERTIONS = {
    "C01": {"requested_language_media_matches"},
    "C03": {"exact_media_mapping"},
    "C06": {"target_curve_matches"},
    "C08": {"requested_curve_matches"},
    "C09": {"exactly_one_added_binding", "new_effect_matches", "new_effect_owned_by_target"},
    "M01": {
        "exact_segment_track_source_topology", "each_track_has_one_sequence_and_clip",
        "media_hashes_match_each_requested_track", "clip_media_matches_its_source",
        "only_track_has_requested_volume",
    },
    "M05": {"requested_trigger_matches"},
}


class _SingleCaseSession:
    """Retain actual pytest reports but isolate this copy's evidence denominator."""

    def __init__(self, request: pytest.FixtureRequest) -> None:
        self._session = request.session
        self.items = [request.node]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


class _SingleCaseRequest:
    def __init__(self, request: pytest.FixtureRequest) -> None:
        self._request = request
        self.session = _SingleCaseSession(request)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._request, name)


@pytest.fixture
def expansion_runtime(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[_WorkflowSandboxRuntime]:
    """Function-scoped reuse of the complete existing sandbox/evidence lifecycle.

The original fixture is module-scoped. Its finalizer scans session.items in
that module; forwarding only this real pytest node prevents future parameters
from being incorrectly sealed as BLOCKED against the current sandbox.
    """
    if os.environ.get("WWISE_VERSION") not in {"2022.1", "2025.1"}:
        pytest.fail("expansion preflight requires an explicit reviewed 2022.1 or 2025.1 lane")
    yield from _existing_workflow_sandbox_runtime.__wrapped__(
        _SingleCaseRequest(request), tmp_path_factory,
    )


@pytest.mark.parametrize(
    ("case_id", "expansion_runtime"),
    [pytest.param(case_id, ("Japanese",) if case_id == "C01" else (), id=case_id)
     for case_id in _PREPARERS],
    indirect=["expansion_runtime"],
)
def test_expansion_case_setup_and_independent_oracle_are_stable(
    expansion_runtime: _WorkflowSandboxRuntime, case_id: str,
) -> None:
    runtime = expansion_runtime
    module_name, function_name = _PREPARERS[case_id]
    # A missing recipe is a failed prerequisite, not a skipped or credited case.
    module = importlib.import_module(f"tests.semantic.support.{module_name}")
    prepare = getattr(module, function_name)
    assert callable(prepare), f"{case_id} has no executable preparation entrypoint"
    gateway_receipts: list[dict[str, Any]] = []
    oracle_receipts: list[dict[str, Any]] = []
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
    actor = OwnedDirectWaapiCall(host=runtime.lifecycle.host, port=runtime.port)
    case_result: dict[str, Any] | None = None
    failure: BaseException | None = None
    try:
        context = ExpansionCaseContext(
            version=runtime.version,
            scenario_id=f"PREFLIGHT-{runtime.version.replace('.', '-')}-{case_id}",
            project_path=runtime.sandbox.sandbox_project,
            asset_root=runtime.sandbox.sandbox_path / "ExpansionAssets" / case_id,
            gateway=gateway,
            trusted_read=expansion_oracle_reader(
                version=runtime.version,
                read_call=lambda uri, args, options: _record_oracle_call(
                    actor, oracle_receipts, uri, args, options,
                ),
            ),
        )
        try:
            prepared = prepare(context)
        except ExpectedCapabilityBoundary as boundary:
            assert (case_id, runtime.version) == ("M05", "2022.1"), boundary
            assert (boundary.case_id, boundary.version) == (case_id, runtime.version)
            assert boundary.evidence.get("agent_executed") is False
            assert boundary.evidence.get("business_effect_verified") is False
            assert not any(row.get("argv", [None])[0] == "execute" for row in gateway_receipts)
            case_result = {
                "category": f"expansion-preflight-{case_id}",
                "status": "blocked",
                "verifier_strength": "affirmatively_observed_version_boundary_no_agent_execution",
                "boundary_code": boundary.boundary_code,
                "evidence": boundary.evidence,
                "agent_pass": False,
                "business_effect_verified": False,
            }
            return

        assert isinstance(prepared, PreparedExpansionCase)
        assert prepared.required_assertions and prepared.read_object_ids
        sealed_before = canonical_digest(prepared.before)
        snapshot_start = len(gateway_receipts)
        first = prepared.snapshot()
        second = prepared.snapshot()
        assert canonical_digest(first) == sealed_before, "first independent read drifted from prepared baseline"
        assert canonical_digest(second) == sealed_before, "repeated independent read changed the baseline"
        assert all(row.get("argv", [None])[0] in _SNAPSHOT_COMMANDS
                   for row in gateway_receipts[snapshot_start:])
        assertions = prepared.verify(prepared.before, second)
        assert set(assertions) == prepared.required_assertions
        assert all(type(value) is bool for value in assertions.values()), assertions
        assert {name for name, value in assertions.items() if value is False} == _BASELINE_FALSE_ASSERTIONS[case_id], (
            "baseline must preserve every protected fact and lack exactly the requested new effect", assertions,
        )
        # The trusted actor receives only fixed, bounded read projections.
        assert all(call["uri"] == "ak.wwise.core.object.get" for call in actor.calls)
        case_result = {
            "category": f"expansion-preflight-{case_id}",
            "status": "PASS",
            "verifier_strength": "fixture_setup_and_repeated_independent_snapshot_only",
            "before_sha256": sealed_before,
            "setup_execute_count": sum(
                row.get("argv", [None])[0] == "execute"
                for row in gateway_receipts[:snapshot_start]
            ),
            "assertion_names": sorted(assertions),
            "baseline_assertions": dict(assertions),
            "agent_pass": False,
            "business_effect_verified": False,
        }
    except BaseException as exc:  # noqa: BLE001 - retain diagnostics before pytest reports the failure
        failure = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        try:
            if not actor.close():
                cleanup_error = AssertionError("trusted read-only actor cleanup did not complete")
            elif not actor.fully_closed:
                cleanup_error = AssertionError("trusted read-only actor still owns a live thread")
        except BaseException as exc:  # noqa: BLE001 - retain cleanup failures with any setup error
            cleanup_error = exc
        if failure is not None or cleanup_error is not None:
            report_error = failure or cleanup_error
            assert report_error is not None
            try:
                diagnostics_path = _persist_preflight_failure(
                    runtime,
                    case_id=case_id,
                    error=report_error,
                    gateway_receipts=gateway_receipts,
                    oracle_receipts=oracle_receipts,
                    actor=actor,
                )
            except BaseException as diagnostic_error:  # noqa: BLE001 - preserve the original test failure
                if failure is not None:
                    failure.add_note(f"Could not persist preflight diagnostics: {diagnostic_error}")
                elif cleanup_error is not None:
                    cleanup_error.add_note(f"Could not persist preflight diagnostics: {diagnostic_error}")
            else:
                runtime.category_results.append({
                    "category": f"expansion-preflight-{case_id}",
                    "status": "FAIL" if failure is not None else "blocked",
                    "verifier_strength": "setup_failed_with_preserved_gateway_and_oracle_diagnostics",
                    "reason": str(report_error)[:8_192],
                    "diagnostics_path": str(diagnostics_path),
                    "gateway_call_count": len(gateway_receipts),
                    "oracle_call_count": len(oracle_receipts),
                    "agent_pass": False,
                    "business_effect_verified": False,
                })
        elif case_result is not None:
            runtime.category_results.append(case_result)
        if cleanup_error is not None:
            if failure is not None:
                failure.add_note(f"Trusted oracle cleanup also failed: {cleanup_error}")
            else:
                raise cleanup_error
