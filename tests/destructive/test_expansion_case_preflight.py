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
from collections.abc import Iterator, Mapping, Sequence
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
from tests.semantic.support.codex_expansion_oracle_reads import expansion_oracle_reader
from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall


pytestmark = [pytest.mark.live, pytest.mark.destructive]


def canonical_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()

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
    gateway_commands: list[tuple[str, ...]] = []

    def gateway(command: Sequence[str]) -> Mapping[str, Any]:
        argv = tuple(command)
        assert argv and all(isinstance(value, str) for value in argv), command
        gateway_commands.append(argv)
        return runtime.gateway(argv, live=argv[0] in _LIVE_COMMANDS)

    actor = OwnedDirectWaapiCall(host=runtime.lifecycle.host, port=runtime.port)
    try:
        context = ExpansionCaseContext(
            version=runtime.version,
            scenario_id=f"PREFLIGHT-{runtime.version.replace('.', '-')}-{case_id}",
            project_path=runtime.sandbox.sandbox_project,
            asset_root=runtime.sandbox.sandbox_path / "ExpansionAssets" / case_id,
            gateway=gateway,
            trusted_read=expansion_oracle_reader(version=runtime.version, read_call=actor),
        )
        try:
            prepared = prepare(context)
        except ExpectedCapabilityBoundary as boundary:
            assert (case_id, runtime.version) == ("M05", "2022.1"), boundary
            assert (boundary.case_id, boundary.version) == (case_id, runtime.version)
            assert boundary.evidence.get("agent_executed") is False
            assert boundary.evidence.get("business_effect_verified") is False
            assert not any(command[0] == "execute" for command in gateway_commands)
            runtime.category_results.append({
                "category": f"expansion-preflight-{case_id}",
                "status": "blocked",
                "verifier_strength": "affirmatively_observed_version_boundary_no_agent_execution",
                "boundary_code": boundary.boundary_code,
                "evidence": boundary.evidence,
                "agent_pass": False,
                "business_effect_verified": False,
            })
            return

        assert isinstance(prepared, PreparedExpansionCase)
        assert prepared.required_assertions and prepared.read_object_ids
        sealed_before = canonical_digest(prepared.before)
        snapshot_start = len(gateway_commands)
        first = prepared.snapshot()
        second = prepared.snapshot()
        assert canonical_digest(first) == sealed_before, "first independent read drifted from prepared baseline"
        assert canonical_digest(second) == sealed_before, "repeated independent read changed the baseline"
        assert all(command[0] in _SNAPSHOT_COMMANDS for command in gateway_commands[snapshot_start:])
        assertions = prepared.verify(prepared.before, second)
        assert set(assertions) == prepared.required_assertions
        assert all(type(value) is bool for value in assertions.values()), assertions
        assert {name for name, value in assertions.items() if value is False} == _BASELINE_FALSE_ASSERTIONS[case_id], (
            "baseline must preserve every protected fact and lack exactly the requested new effect", assertions,
        )
        # The trusted actor receives only fixed, bounded read projections.
        assert all(call["uri"] == "ak.wwise.core.object.get" for call in actor.calls)
        runtime.category_results.append({
            "category": f"expansion-preflight-{case_id}",
            "status": "PASS",
            "verifier_strength": "fixture_setup_and_repeated_independent_snapshot_only",
            "before_sha256": sealed_before,
            "setup_execute_count": sum(command[0] == "execute" for command in gateway_commands[:snapshot_start]),
            "assertion_names": sorted(assertions),
            "baseline_assertions": dict(assertions),
            "agent_pass": False,
            "business_effect_verified": False,
        })
    finally:
        assert actor.close(), "trusted read-only actor cleanup did not complete"
        assert actor.fully_closed, "trusted read-only actor still owns a live thread"
