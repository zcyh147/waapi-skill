#!/usr/bin/env python3
"""Run the strict fresh-Codex WAAPI semantic matrix.

The evaluated model receives one target Skill, a disposable HOME/CODEX_HOME,
and a writable empty agent workspace.  It cannot write the broker-owned
transaction state or dispatcher evidence.  Every packaged gateway invocation
is authorized by a phase-local broker and reconciled with the Codex JSON event
trace before any result is accepted.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
TOPIC_SUBSCRIPTION_SETTLE_SECONDS = 0.75
TOPIC_PUBLISHER_JOIN_SECONDS = 120.0
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from tests.semantic.support.codex_eval_grading import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    EvalSessionGrade,
    grade_eval_session,
)
from tests.semantic.support.codex_eval_results import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    WAAPI_RESULT_PREFIX,
    parse_waapi_result_line,
)
from tests.semantic.support.codex_eval_fixtures import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    EvalFixtureBundle,
    FixtureContractError,
    MissingPathOracleSnapshot,
    ObjectRowsOracleSnapshot,
    OracleSnapshot,
    PackagedGatewayBinding,
    PathOracleSnapshot,
    create_shared_fixture_bundle,
)
from tests.semantic.support.codex_eval_protocol import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    build_expected_gateway_steps,
)
from tests.semantic.support.codex_eval_suite import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    BOUNDARY_CASE_IDS,
    CASE_IDS,
    PROFILE_IDS,
    SUPPORTED_VERSIONS,
    EvalSession,
    load_eval_suite,
)
from tests.semantic.support.codex_gateway_broker import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    CodexGatewayBroker,
    ExpectedGatewayStep,
    GatewayBrokerEvidence,
    GatewayBrokerReconciliation,
    TrustedStepObserver,
    TrustedStepPreObserver,
)
from tests.semantic.support.codex_filesystem_security import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    write_utf8_text_bytes,
)
from tests.semantic.support.codex_harness import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    CodexCliHarness,
    CodexHarnessError,
    CodexHarnessConfig,
    CodexInfrastructureError,
    CodexRunResult,
    normalized_gateway_command_argv,
    prepare_workspace_skill_install,
    resolve_codex_binary,
)
from tests.semantic.support.codex_transaction_seal import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    PreviewSealEvidence,
    PreviewTransactionSeal,
    create_preview_seal,
    verify_preview_seal,
)
from tests.destructive.support.live_environment import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    require_live_environment,
)
from tests.destructive.support.sandbox_fixture import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    ProjectHash,
    SandboxProject,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from wwise_waapi.headless import HeadlessLifecycle  # noqa: E402  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.metadata import parse_get_types_result  # noqa: E402  # pyright: ignore[reportMissingImports]
from wwise_waapi.transactions import TransactionState  # noqa: E402  # pyright: ignore[reportMissingImports]


DEFAULT_SUITE = SKILL_ROOT / "evals" / "evals-v2.json"
DEFAULT_V3_SUITE = SKILL_ROOT / "evals" / "suite-v3.json"
DEFAULT_MODIFICATION_POLICY_V3_SUITE = (
    SKILL_ROOT / "evals" / "modification-policy-9.json"
)
DEFAULT_COMPOUND_HEAVY_V1_SUITE = (
    REPO_ROOT / "tests" / "semantic" / "data" / "compound-heavy-v1" / "profile.json"
)
DEFAULT_INTEGRATION_WORKFLOWS_V1_SUITE = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "integration-workflows-v1"
    / "profile.json"
)
DEFAULT_INTEGRATION_WORKFLOWS_V2_SUITE = (
    REPO_ROOT
    / "tests"
    / "semantic"
    / "data"
    / "integration-workflows-v2"
    / "profile.json"
)
DEFAULT_ITERATION_ROOT = SKILL_ROOT.parent / "waapi-skill-workspace" / "iteration-9-v2-matrix"
DEFAULT_HEAVY_V3_ITERATION_ROOT = (
    SKILL_ROOT.parent / "waapi-skill-workspace" / "heavy-cross-version-80"
)
DEFAULT_MODIFICATION_POLICY_V3_ITERATION_ROOT = (
    SKILL_ROOT.parent / "waapi-skill-workspace" / "modification-policy-9"
)
DEFAULT_COMPOUND_HEAVY_V1_ITERATION_ROOT = (
    SKILL_ROOT.parent / "waapi-skill-workspace" / "compound-heavy-cross-version-24"
)
DEFAULT_INTEGRATION_WORKFLOWS_V1_ITERATION_ROOT = (
    SKILL_ROOT.parent
    / "waapi-skill-workspace"
    / "integration-workflows-cross-version-6"
)
DEFAULT_INTEGRATION_WORKFLOWS_V2_ITERATION_ROOT = (
    SKILL_ROOT.parent
    / "waapi-skill-workspace"
    / "integration-workflows-v2-cross-version-6"
)
DEFAULT_CODEX_BINARY: str | None = None
DEFAULT_AUTH_JSON = Path.home() / ".codex" / "auth.json"
DEFAULT_LIVE_CONFIG = REPO_ROOT / "tests" / "fixtures" / "local" / "live-environment.json"
GLOBAL_LIVE_LIFECYCLE_LOCK_ROOT = REPO_ROOT / ".waapi-skill-state" / "runtime" / "wwise-live-lifecycle-lock"
RUN_CONTRACT = "waapi-skill.codex-semantic-matrix-run/v2"
PHASE_CONTRACT = "waapi-skill.codex-semantic-phase-result/v2"
PHASE_ERROR_CONTRACT = "waapi-skill.codex-semantic-phase-error/v2"
ITERATION_MARKER_CONTRACT = "waapi-skill.codex-semantic-iteration-root/v1"
ITERATION_MARKER_FILE = ".waapi-semantic-iteration-root.json"
LIVE_DEPENDENCY_PREFLIGHT_CONTRACT = "waapi-skill.codex-semantic-live-preflight/v1"
OFFLINE_CASE_IDS = frozenset({"C1", *BOUNDARY_CASE_IDS})
QUERY_CASE_IDS = frozenset({"Q1", "Q2", "Q3", "Q4", "Q5"})
FIXED_READ_CASE_IDS = frozenset({"R1", "R2", "R3", "R4", "R5", "R6"})
OBJECT_GET_URI = "ak.wwise.core.object.get"
READ_ONLY_DISPATCH_APIS = frozenset(
    {
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        OBJECT_GET_URI,
        "ak.wwise.ui.getSelectedObjects",
        "ak.wwise.core.object.getTypes",
        "ak.wwise.core.object.created",
        "ak.wwise.waapi.getFunctions",
    }
)
QUERY_RESULT_KEYS = frozenset({"count", "objects"})
QUERY_OBJECT_KEYS = frozenset({"id", "name", "type", "path"})
MISSING_QUERY_RESULT_KEYS = frozenset({"count", "objects", "not_found"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HEAVY_V3_PROFILE_ID = "heavy_cross_version_80"
MODIFICATION_POLICY_V3_PROFILE_ID = "modification_policy_9"
COMPOUND_HEAVY_V1_PROFILE_ID = "compound_heavy_cross_version_24"
INTEGRATION_WORKFLOWS_V1_PROFILE_ID = "integration_workflows_cross_version_6"
INTEGRATION_WORKFLOWS_V2_PROFILE_ID = "integration_workflows_v2_cross_version_6"
EXECUTABLE_V3_PROFILE_IDS = frozenset(
    {
        HEAVY_V3_PROFILE_ID,
        MODIFICATION_POLICY_V3_PROFILE_ID,
        COMPOUND_HEAVY_V1_PROFILE_ID,
        INTEGRATION_WORKFLOWS_V1_PROFILE_ID,
        INTEGRATION_WORKFLOWS_V2_PROFILE_ID,
    }
)
HEAVY_V3_RUN_CONFIG_CONTRACT = "waapi-skill.codex-heavy-matrix-config/v3"
HEAVY_V3_SUMMARY_CONTRACT = "waapi-skill.codex-heavy-matrix-summary/v3"
HEAVY_V3_CASE_RECORD_CONTRACT = "waapi-skill.codex-heavy-matrix-case/v3"
HEAVY_V3_STATUSES = frozenset({"PASS", "FAIL", "BLOCKED", "INDETERMINATE"})
HEAVY_V3_REQUIRED_MODEL_REQUEST_FIELDS = {
    "ak.wwise.core.audio.convert": frozenset({"io_root"}),
    "ak.wwise.core.soundbank.convertExternalSources": frozenset({"io_root"}),
    "ak.wwise.core.soundbank.processDefinitionFiles": frozenset({"io_root"}),
}


class LiveDependencyPreflightError(RuntimeError):
    """A live semantic run cannot use its current Python interpreter."""

    def __init__(self, *, exception_type: str, exception_message: str) -> None:
        self.interpreter = Path(sys.executable).expanduser().resolve(strict=False)
        self.recommended_interpreter = skill_venv_python()
        self.exception_type = exception_type
        self.exception_message = exception_message
        super().__init__(
            "Live semantic sessions require the runner interpreter to import "
            "`waapi` (waapi-client), but the current interpreter cannot. "
            f"Current interpreter: {self.interpreter}. "
            f"Re-run with: {self.recommended_interpreter} "
            "tests/semantic/run_codex_skill_matrix.py <same arguments>. "
            "Do not install into the global interpreter; prepare the Skill-local venv with "
            "`python skills/waapi-skill/scripts/setup_environment.py` if it is missing. "
            f"Import failure: {exception_type}: {exception_message}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": LIVE_DEPENDENCY_PREFLIGHT_CONTRACT,
            "ok": False,
            "dependency": "waapi-client",
            "module": "waapi",
            "required_symbols": ["WaapiClient", "WaapiRequestFailed"],
            "current_interpreter": str(self.interpreter),
            "recommended_interpreter": str(self.recommended_interpreter),
            "recommended_interpreter_exists": self.recommended_interpreter.is_file(),
            "setup_command": "python skills/waapi-skill/scripts/setup_environment.py",
            "rerun_command": (
                f"{self.recommended_interpreter} "
                "tests/semantic/run_codex_skill_matrix.py <same arguments>"
            ),
            "automatic_install_attempted": False,
            "error": {
                "type": self.exception_type,
                "message": self.exception_message,
            },
        }


class HeavyV3MatrixError(RuntimeError):
    """The V3 heavy matrix cannot produce trustworthy campaign evidence."""


class HeavyV3RunnerUnavailableError(HeavyV3MatrixError):
    """No closed project or CLI runner owns the selected V3 unit."""


@dataclass(frozen=True, slots=True)
class PhaseExecution:
    session: EvalSession
    values: Mapping[str, str]
    result: CodexRunResult
    broker_evidence: GatewayBrokerEvidence
    reconciliation: GatewayBrokerReconciliation
    runner_oracle: Mapping[str, Any]
    grade: EvalSessionGrade
    phase_root: Path
    state_directory: Path
    evidence_directory: Path
    error: str = ""

    @property
    def passed(self) -> bool:
        return self.grade.passed and not self.error


@dataclass(frozen=True, slots=True)
class RunnerOptions:
    profile: str
    iteration_root: Path
    suite_path: Path
    skill_source: Path
    codex_binary: Path
    auth_json: Path
    live_config: Path
    model: str
    reasoning_effort: str
    service_tier: str
    timeout_seconds: float
    case_ids: tuple[str, ...]
    versions: tuple[str, ...]
    pair_ids: tuple[str, ...]
    offline_only: bool
    overwrite: bool


@dataclass(frozen=True, slots=True)
class PhaseRunObservation:
    session: EvalSession
    values: Mapping[str, str]
    result: CodexRunResult
    broker_evidence: GatewayBrokerEvidence
    reconciliation: GatewayBrokerReconciliation
    phase_root: Path
    state_directory: Path
    evidence_directory: Path


@dataclass(frozen=True, slots=True)
class PreviewPairState:
    execution: PhaseExecution
    values: Mapping[str, str]
    before: OracleSnapshot
    seal: PreviewTransactionSeal
    transaction_id: str
    artifact_hash: str


@dataclass(frozen=True, slots=True)
class VersionRunOutcome:
    executions: tuple[PhaseExecution, ...]
    attempted_session_ids: tuple[str, ...]
    failed_session_ids: tuple[str, ...]
    error: str


HeavyV3UnitLoader = Callable[[RunnerOptions], Sequence[Any]]
HeavyV3UnitRunner = Callable[..., Any]
HeavyV3DependencyPreflight = Callable[[], Mapping[str, Any]]


def load_heavy_v3_units(options: RunnerOptions) -> tuple[Any, ...]:
    """Load and filter the reviewed V3 bundle without importing live runners."""

    if options.profile == INTEGRATION_WORKFLOWS_V2_PROFILE_ID:
        integration_module = importlib.import_module(
            "tests.semantic.support.codex_integration_workflows_v2"
        )
        profile = integration_module.load_integration_workflows_v2_profile(
            options.suite_path,
            unit_ids=options.case_ids,
            versions=options.versions,
            require_committed_baselines=True,
            repo_root=REPO_ROOT,
        )
        return tuple(profile.units)
    if options.profile == INTEGRATION_WORKFLOWS_V1_PROFILE_ID:
        integration_module = importlib.import_module(
            "tests.semantic.support.codex_integration_workflows_v1"
        )
        profile = integration_module.load_integration_workflows_profile(
            options.suite_path,
            unit_ids=options.case_ids,
            versions=options.versions,
        )
        return tuple(profile.units)
    if options.profile == COMPOUND_HEAVY_V1_PROFILE_ID:
        compound_module = importlib.import_module(
            "tests.semantic.support.codex_compound_heavy_v1"
        )
        profile = compound_module.load_compound_heavy_profile(
            options.suite_path,
            unit_ids=options.case_ids,
            versions=options.versions,
        )
        return tuple(profile.units)
    if options.profile == MODIFICATION_POLICY_V3_PROFILE_ID:
        policy_module = importlib.import_module(
            "tests.semantic.support.codex_modification_policy_v3"
        )
        profile = policy_module.load_modification_policy_profile(
            options.suite_path,
            unit_ids=options.case_ids,
            versions=options.versions,
        )
        return tuple(profile.units)
    if options.profile != HEAVY_V3_PROFILE_ID:
        raise HeavyV3MatrixError(
            f"unsupported executable V3 profile {options.profile!r}"
        )
    bundle_module = importlib.import_module(
        "tests.semantic.support.codex_eval_bundle_v3"
    )
    execution_module = importlib.import_module(
        "tests.semantic.support.codex_eval_execution_v3"
    )
    bundle = bundle_module.load_eval_bundle_v3(options.suite_path)
    scenarios = execution_module.select_heavy_scenarios(
        bundle,
        scenario_ids=options.case_ids,
        versions=options.versions,
    )
    blocked = {
        scenario.id: tuple(
            requirement.id
            for requirement in bundle.scenario_mapping_blockers(scenario.id)
        )
        for scenario in scenarios
        if bundle.scenario_mapping_blockers(scenario.id)
    }
    if blocked:
        rendered = ", ".join(
            f"{scenario_id}={list(requirements)!r}"
            for scenario_id, requirements in blocked.items()
        )
        raise HeavyV3MatrixError(
            "selected V3 scenarios retain unresolved request mappings: " + rendered
        )
    units = tuple(execution_module.build_heavy_units(scenarios))
    if not units:
        raise HeavyV3MatrixError("no V3 heavy units matched the requested filters")
    return units


def run_heavy_v3_matrix(
    options: RunnerOptions,
    *,
    unit_loader: HeavyV3UnitLoader | None = None,
    unit_runner: HeavyV3UnitRunner | None = None,
    dependency_preflight: HeavyV3DependencyPreflight | None = None,
) -> int:
    """Run the selected V3 heavy units sequentially with incremental evidence.

    A semantic ``FAIL`` is retained and the next case runs.  ``BLOCKED``,
    ``INDETERMINATE``, an unavailable closed runner, or any orchestration fault
    seals the current record and stops before another Wwise lifecycle starts.
    The injectable seams are for harness-only tests and are not exposed to the
    evaluated Codex task.
    """

    if options.profile not in EXECUTABLE_V3_PROFILE_IDS:
        raise HeavyV3MatrixError(
            "V3 executable runner requires one of "
            f"{tuple(sorted(EXECUTABLE_V3_PROFILE_IDS))!r}"
        )
    if options.pair_ids:
        raise HeavyV3MatrixError("V3 heavy execution does not accept pair filters")
    if options.offline_only:
        raise HeavyV3MatrixError("V3 heavy execution is real-Wwise only")

    load_units = unit_loader or load_heavy_v3_units
    execute_unit = unit_runner or run_heavy_v3_unit
    preflight = dependency_preflight or require_live_runner_dependencies
    units = tuple(load_units(options))
    if not units:
        raise HeavyV3MatrixError("no V3 heavy units matched the requested filters")
    unit_rows = tuple(
        _heavy_v3_unit_row(unit, sequence=index)
        for index, unit in enumerate(units, start=1)
    )
    unit_ids = tuple(row["scenario_id"] for row in unit_rows)
    if len(unit_ids) != len(set(unit_ids)):
        raise HeavyV3MatrixError("selected V3 heavy units contain duplicate ids")

    prepare_iteration_root(options.iteration_root, overwrite=options.overwrite)
    started_at = utc_now()
    records: list[dict[str, Any]] = []
    run_errors: list[str] = []
    stop_reason = ""
    preflight_state = "pending"
    policy_thread_ids: set[str] = set()

    def persist(*, terminal: bool) -> None:
        completed_at = utc_now() if terminal else None
        write_json(
            options.iteration_root / "run-config.json",
            _heavy_v3_run_config(
                options,
                unit_rows=unit_rows,
                records=records,
                run_errors=run_errors,
                stop_reason=stop_reason,
                preflight_state=preflight_state,
                started_at=started_at,
                completed_at=completed_at,
            ),
        )
        write_json(
            options.iteration_root / "summary.json",
            _heavy_v3_summary(
                profile=options.profile,
                unit_rows=unit_rows,
                records=records,
                run_errors=run_errors,
                stop_reason=stop_reason,
                preflight_state=preflight_state,
                started_at=started_at,
                completed_at=completed_at,
            ),
        )

    persist(terminal=False)
    try:
        preflight_payload = dict(preflight())
        if preflight_payload.get("ok") is not True:
            raise HeavyV3MatrixError(
                "live dependency preflight did not return an explicit ok=true result"
            )
    except BaseException as exc:  # noqa: BLE001 - terminal summary must survive preflight faults
        preflight_state = "blocked"
        stop_reason = "live-dependency-preflight"
        run_errors.append(format_exception(stop_reason, exc))
        payload = (
            exc.as_dict()
            if isinstance(exc, LiveDependencyPreflightError)
            else {
                "contract": LIVE_DEPENDENCY_PREFLIGHT_CONTRACT,
                "ok": False,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
        )
        write_json(options.iteration_root / "live-preflight.json", payload)
        persist(terminal=True)
        print(f"[BLOCKED] {stop_reason}: {type(exc).__name__}: {exc}")
        return 1

    preflight_state = "passed"
    write_json(options.iteration_root / "live-preflight.json", preflight_payload)
    persist(terminal=False)

    for unit, unit_row in zip(units, unit_rows, strict=True):
        scenario_id = unit_row["scenario_id"]
        scenario_root = (
            options.iteration_root
            / "scenarios"
            / f"{unit_row['sequence']:03d}-{safe_session_name(scenario_id)}"
        )
        try:
            outcome = execute_unit(
                unit,
                scenario_root=scenario_root,
                options=options,
            )
            if options.profile == MODIFICATION_POLICY_V3_PROFILE_ID:
                thread_id = getattr(outcome, "thread_id", None)
                outcome_status = getattr(outcome, "status", None)
                if outcome_status == "PASS" and (
                    not isinstance(thread_id, str) or not thread_id
                ):
                    raise HeavyV3MatrixError(
                        f"{scenario_id} policy outcome has no fresh thread identity"
                    )
                if isinstance(thread_id, str) and thread_id in policy_thread_ids:
                    raise HeavyV3MatrixError(
                        f"{scenario_id} reused a prior policy task thread identity"
                    )
                if isinstance(thread_id, str) and thread_id:
                    policy_thread_ids.add(thread_id)
            record = _heavy_v3_case_record(
                unit_row,
                scenario_root=scenario_root,
                outcome=outcome,
            )
        except BaseException as exc:  # noqa: BLE001 - every attempted unit is accounted for
            record = _heavy_v3_blocked_case_record(
                unit_row,
                scenario_root=scenario_root,
                exc=exc,
            )
            run_errors.append(format_exception(f"heavy-unit:{scenario_id}", exc))

        records.append(record)
        try:
            write_json(scenario_root / "matrix-case.json", record)
        except BaseException as exc:  # noqa: BLE001 - missing evidence is systemic
            archive_error = format_exception(
                f"heavy-unit-archive:{scenario_id}", exc
            )
            run_errors.append(archive_error)
            record["status"] = "BLOCKED"
            record["reason"] = _append_heavy_reason(
                str(record.get("reason", "")),
                f"matrix evidence archive failed: {type(exc).__name__}: {exc}",
            )

        status = str(record["status"])
        reason = str(record.get("reason", ""))
        print(
            f"[{status}] {scenario_id} version={unit_row['version']} "
            f"api={unit_row['api']} reason={reason or '-'}"
        )
        if status in {"BLOCKED", "INDETERMINATE"}:
            stop_reason = f"{status.lower()}:{scenario_id}"
            if not any(f"heavy-unit:{scenario_id}" in error for error in run_errors):
                run_errors.append(
                    f"[heavy-unit:{scenario_id}] {status}: {reason or 'no reason supplied'}"
                )
        persist(terminal=False)
        if stop_reason:
            break

    persist(terminal=True)
    all_selected_passed = (
        len(records) == len(unit_rows)
        and not stop_reason
        and not run_errors
        and all(record["status"] == "PASS" for record in records)
    )
    return 0 if all_selected_passed else 1


def run_heavy_v3_unit(
    unit: Any,
    *,
    scenario_root: Path,
    options: RunnerOptions,
) -> Any:
    """Dispatch one V3 unit only through a closed project or CLI runner."""

    unit_row = _heavy_v3_unit_row(unit, sequence=1)
    api = unit_row["api"]
    live_environment = trusted_gateway_environment(
        {"WWISE_TEST_CONFIG": str(options.live_config)}
    )
    if api.startswith("ak.wwise.cli."):
        module_name = "tests.semantic.support.codex_heavy_cli_case_runner_v3"
        try:
            cli_module = importlib.import_module(module_name)
        except (ImportError, AttributeError) as exc:
            raise HeavyV3RunnerUnavailableError(
                "the closed V3 CLI case runner is unavailable; expected "
                f"{module_name}.run_heavy_cli_unit"
            ) from exc
        cli_apis = frozenset(getattr(cli_module, "HEAVY_CLI_RUNNER_APIS", ()))
        options_type = getattr(cli_module, "HeavyCliRunnerOptions", None)
        runner = getattr(cli_module, "run_heavy_cli_unit", None)
        if api not in cli_apis or options_type is None or not callable(runner):
            raise HeavyV3RunnerUnavailableError(
                f"the closed V3 CLI runner does not own {api}"
            )
        cli_options = options_type(
            skill_source=options.skill_source,
            codex_binary=options.codex_binary,
            auth_json=options.auth_json,
            model=options.model,
            reasoning_effort=options.reasoning_effort,
            service_tier=options.service_tier,
            timeout_seconds=options.timeout_seconds,
            live_environment=live_environment,
        )
        return runner(unit, scenario_root=scenario_root, options=cli_options)

    project_module = importlib.import_module(
        "tests.semantic.support.codex_heavy_project_runner_v3"
    )
    project_apis = frozenset(getattr(project_module, "PROJECT_RUNNER_APIS", ()))
    if api in project_apis:
        _require_heavy_v3_model_request_surface(unit, project_module)
        options_type = getattr(project_module, "HeavyProjectRunnerOptions", None)
        runner = getattr(project_module, "run_heavy_project_unit", None)
        if options_type is None or not callable(runner):
            raise HeavyV3RunnerUnavailableError(
                "project runner public contract is incomplete"
            )
        project_options = options_type(
            skill_source=options.skill_source,
            codex_binary=options.codex_binary,
            auth_json=options.auth_json,
            model=options.model,
            reasoning_effort=options.reasoning_effort,
            service_tier=options.service_tier,
            timeout_seconds=options.timeout_seconds,
            live_environment=live_environment,
        )
        return runner(unit, scenario_root=scenario_root, options=project_options)

    raise HeavyV3RunnerUnavailableError(
        f"no closed V3 project runner owns {api}; refusing to synthesize a fallback"
    )


def _require_heavy_v3_model_request_surface(unit: Any, runner_module: Any) -> None:
    """Refuse runner-owned requests containing fields the model cannot resolve."""

    scenario = getattr(unit, "scenario", None)
    api = getattr(scenario, "api", None)
    required = HEAVY_V3_REQUIRED_MODEL_REQUEST_FIELDS.get(str(api), frozenset())
    if not required:
        return
    visible = {
        str(getattr(value, "name", ""))
        for value in getattr(scenario, "visible_inputs", ())
        if getattr(value, "name", None)
    }
    declared = getattr(
        runner_module,
        "PROJECT_RUNNER_MODEL_RESOLVED_REQUEST_FIELDS",
        {},
    )
    resolved = set()
    if isinstance(declared, Mapping):
        raw = declared.get(api, ())
        if isinstance(raw, (list, tuple, set, frozenset)):
            resolved = {str(value) for value in raw}
    missing = sorted(required - visible - resolved)
    if missing:
        raise HeavyV3RunnerUnavailableError(
            f"{getattr(unit, 'unit_id', '<unknown>')} runner request contains "
            "model-unresolvable fields: "
            + ", ".join(missing)
            + "; expose them as natural visible inputs or declare a reviewed "
            "runner/Skill resolution contract before execution"
        )


def _heavy_v3_unit_row(unit: Any, *, sequence: int) -> dict[str, Any]:
    scenario = getattr(unit, "scenario", None)
    scenario_id = getattr(unit, "unit_id", None)
    version = getattr(unit, "version", None)
    api = getattr(scenario, "api", None)
    if (
        not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence < 1
        or not isinstance(scenario_id, str)
        or not scenario_id
        or not isinstance(version, str)
        or not version
        or not isinstance(api, str)
        or not api
    ):
        raise HeavyV3MatrixError("V3 heavy unit has an invalid identity")
    safe_name = safe_session_name(scenario_id)
    if not safe_name or safe_name != scenario_id:
        raise HeavyV3MatrixError(
            f"V3 heavy scenario id is not path-safe: {scenario_id!r}"
        )
    row = {
        "sequence": sequence,
        "scenario_id": scenario_id,
        "version": version,
        "api": api,
        "runner": "cli" if api.startswith("ak.wwise.cli.") else "project",
    }
    base_scenario_id = getattr(unit, "base_scenario_id", None)
    if base_scenario_id is not None:
        if not isinstance(base_scenario_id, str) or not base_scenario_id:
            raise HeavyV3MatrixError(
                "V3 heavy unit has an invalid base-scenario identity"
            )
        row["base_scenario_id"] = base_scenario_id
    policy = getattr(unit, "project_modification_policy", None)
    if policy is not None:
        repetition = getattr(unit, "repetition", None)
        expected_dispatch = getattr(
            unit,
            "expected_primary_dispatch_count",
            None,
        )
        if (
            policy not in {"read_only", "ask_before_changes", "allow_changes"}
            or not isinstance(base_scenario_id, str)
            or not base_scenario_id
            or type(repetition) is not int
            or repetition not in {1, 2, 3}
            or type(expected_dispatch) is not int
            or expected_dispatch not in {0, 1}
        ):
            raise HeavyV3MatrixError(
                "V3 modification-policy unit metadata is invalid"
            )
        row.update(
            {
                "base_scenario_id": base_scenario_id,
                "policy_mode": policy,
                "project_modification_policy": policy,
                "repetition": repetition,
                "expected_primary_dispatch_count": expected_dispatch,
            }
        )
    return row


def _heavy_v3_case_record(
    unit_row: Mapping[str, Any],
    *,
    scenario_root: Path,
    outcome: Any,
) -> dict[str, Any]:
    serializer = getattr(outcome, "as_dict", None)
    if not callable(serializer):
        raise HeavyV3MatrixError("V3 runner outcome lacks as_dict()")
    payload = serializer()
    if not isinstance(payload, Mapping):
        raise HeavyV3MatrixError("V3 runner outcome as_dict() must return an object")
    status = getattr(outcome, "status", payload.get("status"))
    scenario_id = getattr(outcome, "scenario_id", payload.get("scenario_id"))
    version = getattr(outcome, "version", payload.get("version"))
    reason = getattr(outcome, "reason", payload.get("reason", ""))
    if status not in HEAVY_V3_STATUSES:
        raise HeavyV3MatrixError(f"V3 runner returned invalid status {status!r}")
    if scenario_id != unit_row["scenario_id"] or version != unit_row["version"]:
        raise HeavyV3MatrixError(
            "V3 runner outcome identity differs from the selected unit"
        )
    if not isinstance(reason, str):
        raise HeavyV3MatrixError("V3 runner outcome reason must be text")
    passed = getattr(outcome, "passed", status == "PASS")
    if not isinstance(passed, bool) or passed != (status == "PASS"):
        raise HeavyV3MatrixError("V3 runner outcome passed/status contract drifted")
    return {
        "contract": HEAVY_V3_CASE_RECORD_CONTRACT,
        **dict(unit_row),
        "status": status,
        "reason": reason,
        "scenario_root": str(scenario_root),
        "runner_outcome": dict(payload),
    }


def _heavy_v3_blocked_case_record(
    unit_row: Mapping[str, Any],
    *,
    scenario_root: Path,
    exc: BaseException,
) -> dict[str, Any]:
    return {
        "contract": HEAVY_V3_CASE_RECORD_CONTRACT,
        **dict(unit_row),
        "status": "BLOCKED",
        "reason": f"{type(exc).__name__}: {exc}",
        "scenario_root": str(scenario_root),
        "runner_outcome": None,
    }


def _heavy_v3_run_config(
    options: RunnerOptions,
    *,
    unit_rows: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    run_errors: Sequence[str],
    stop_reason: str,
    preflight_state: str,
    started_at: str,
    completed_at: str | None,
) -> dict[str, Any]:
    attempted = [str(record["scenario_id"]) for record in records]
    attempted_set = frozenset(attempted)
    return {
        "contract": HEAVY_V3_RUN_CONFIG_CONTRACT,
        "started_at": started_at,
        "updated_at": utc_now(),
        "completed_at": completed_at,
        "profile": options.profile,
        "expected_unit_count": len(unit_rows),
        "selected_units": [dict(row) for row in unit_rows],
        "case_ids": list(options.case_ids),
        "versions": list(options.versions),
        "pair_ids": [],
        "offline_only": False,
        "model": options.model,
        "reasoning_effort": options.reasoning_effort,
        "service_tier": options.service_tier,
        "timeout_seconds": options.timeout_seconds,
        "memory": "disabled",
        "fresh_process_thread_and_task_per_scenario": True,
        "sequential_wwise_lifecycles": True,
        "semantic_fail_policy": "continue",
        "blocked_or_indeterminate_policy": "stop",
        "skill_source": str(options.skill_source),
        "suite_path": str(options.suite_path),
        "live_config": str(options.live_config),
        "progress": {
            "preflight": preflight_state,
            "attempted_unit_count": len(attempted),
            "attempted_unit_ids": attempted,
            "pending_unit_ids": [
                str(row["scenario_id"])
                for row in unit_rows
                if row["scenario_id"] not in attempted_set
            ],
            "status_counts": _heavy_v3_status_counts(records),
            "stop_reason": stop_reason or None,
            "run_error_count": len(run_errors),
        },
    }


def _heavy_v3_summary(
    *,
    unit_rows: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    run_errors: Sequence[str],
    stop_reason: str,
    preflight_state: str,
    started_at: str,
    completed_at: str | None,
    profile: str = HEAVY_V3_PROFILE_ID,
) -> dict[str, Any]:
    attempted_ids = [str(record["scenario_id"]) for record in records]
    attempted_set = frozenset(attempted_ids)
    pending_ids = [
        str(row["scenario_id"])
        for row in unit_rows
        if row["scenario_id"] not in attempted_set
    ]
    all_selected_passed = (
        completed_at is not None
        and preflight_state == "passed"
        and not stop_reason
        and not run_errors
        and len(records) == len(unit_rows)
        and bool(records)
        and all(record.get("status") == "PASS" for record in records)
    )
    return {
        "contract": HEAVY_V3_SUMMARY_CONTRACT,
        "started_at": started_at,
        "updated_at": utc_now(),
        "completed_at": completed_at,
        "profile": profile,
        "preflight": preflight_state,
        "selected_unit_count": len(unit_rows),
        "attempted_unit_count": len(records),
        "attempted_unit_ids": attempted_ids,
        "status_counts": _heavy_v3_status_counts(records),
        "passed_unit_ids": [
            str(record["scenario_id"])
            for record in records
            if record.get("status") == "PASS"
        ],
        "failed_unit_ids": [
            str(record["scenario_id"])
            for record in records
            if record.get("status") == "FAIL"
        ],
        "blocked_unit_ids": [
            str(record["scenario_id"])
            for record in records
            if record.get("status") == "BLOCKED"
        ],
        "indeterminate_unit_ids": [
            str(record["scenario_id"])
            for record in records
            if record.get("status") == "INDETERMINATE"
        ],
        "pending_unit_ids": pending_ids,
        "stop_reason": stop_reason or None,
        "stopped_early": bool(stop_reason),
        "all_selected_passed": all_selected_passed,
        "run_errors": list(run_errors),
        "case_records": [
            {
                key: record.get(key)
                for key in (
                    "sequence",
                    "scenario_id",
                    "version",
                    "api",
                    "runner",
                    "base_scenario_id",
                    "policy_mode",
                    "project_modification_policy",
                    "repetition",
                    "expected_primary_dispatch_count",
                    "status",
                    "reason",
                    "scenario_root",
                )
                if key in record
            }
            for record in records
        ],
    }


def _heavy_v3_status_counts(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    return {
        status: sum(record.get("status") == status for record in records)
        for status in ("PASS", "FAIL", "BLOCKED", "INDETERMINATE")
    }


def _append_heavy_reason(current: str, extra: str) -> str:
    return extra if not current else f"{current}; {extra}"


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    if options.profile in EXECUTABLE_V3_PROFILE_IDS:
        return run_heavy_v3_matrix(options)
    suite = load_eval_suite(options.suite_path)
    sessions = select_sessions(
        suite.expand_profile(options.profile),
        case_ids=options.case_ids,
        versions=options.versions,
        pair_ids=options.pair_ids,
        offline_only=options.offline_only,
    )
    if not sessions:
        raise SystemExit("No semantic sessions matched the requested filters.")
    prepare_iteration_root(options.iteration_root, overwrite=options.overwrite)
    write_json(
        options.iteration_root / "run-config.json",
        {
            "contract": RUN_CONTRACT,
            "started_at": utc_now(),
            "profile": options.profile,
            "expected_session_count": len(sessions),
            "case_ids": list(options.case_ids),
            "versions": list(options.versions),
            "pair_ids": list(options.pair_ids),
            "offline_only": options.offline_only,
            "model": options.model,
            "reasoning_effort": options.reasoning_effort,
            "service_tier": options.service_tier,
            "memory": "disabled",
            "fresh_session_per_phase": True,
            "skill_source": str(options.skill_source),
            "suite_path": str(options.suite_path),
            "live_config": str(options.live_config),
        },
    )

    offline = tuple(session for session in sessions if session.case.id in OFFLINE_CASE_IDS)
    live = tuple(session for session in sessions if session.case.id not in OFFLINE_CASE_IDS)

    executions: list[PhaseExecution] = []
    attempted_session_ids: list[str] = []
    failed_session_ids: list[str] = []
    run_errors: list[str] = []

    if live:
        try:
            live_preflight = require_live_runner_dependencies()
        except LiveDependencyPreflightError as exc:
            failure = format_exception("live-dependency-preflight", exc)
            run_errors.append(failure)
            write_json(options.iteration_root / "live-preflight.json", exc.as_dict())
            print(f"[ERROR] live-dependency-preflight {exc}")
        else:
            write_json(options.iteration_root / "live-preflight.json", live_preflight)

    for session in offline:
        if run_errors:
            break
        attempted_session_ids.append(session.session_id)
        try:
            values = offline_fixture_values(session)
            oracle = offline_oracle(session)
            execution = run_fresh_phase(
                session,
                values=values,
                runner_oracle=oracle,
                options=options,
                runner_environment=trusted_gateway_environment(),
            )
        except BaseException as exc:  # noqa: BLE001 - summary must survive every offline phase failure
            failure = format_exception(f"offline-phase:{session.session_id}", exc)
            failed_session_ids.append(session.session_id)
            run_errors.append(failure)
            print_phase_error(session, failure)
            break
        executions.append(execution)
        print_phase_outcome(execution)
        if not execution.passed:
            failed_session_ids.append(session.session_id)
            break

    if live and not run_errors and all(execution.passed for execution in executions):
        for version in SUPPORTED_VERSIONS:
            version_sessions = tuple(session for session in live if session.version == version)
            if not version_sessions:
                continue
            outcome = run_live_version_sessions(version_sessions, options=options)
            executions.extend(outcome.executions)
            attempted_session_ids.extend(outcome.attempted_session_ids)
            failed_session_ids.extend(outcome.failed_session_ids)
            for execution in outcome.executions:
                print_phase_outcome(execution)
            if outcome.error:
                run_errors.append(outcome.error)
                break
            if any(not execution.passed for execution in outcome.executions):
                break

    attempted_ids = ordered_unique(attempted_session_ids)
    failed_ids = ordered_unique(failed_session_ids)
    attempted_id_set = frozenset(attempted_ids)
    failed_id_set = frozenset(failed_ids)
    pending_ids = [session.session_id for session in sessions if session.session_id not in attempted_id_set]
    all_selected_passed = (
        not run_errors
        and len(attempted_ids) == len(sessions)
        and bool(attempted_ids)
        and not failed_ids
        and all(execution.passed for execution in executions)
    )
    summary = {
        "contract": RUN_CONTRACT,
        "completed_at": utc_now(),
        "profile": options.profile,
        "selected_session_count": len(sessions),
        # An attempted phase is executed for accounting purposes even when its
        # harness, broker, oracle, grader, or runner-owned post-processing
        # fails before a PhaseExecution can be returned.
        "executed_session_count": len(attempted_ids),
        "executed_session_ids": list(attempted_ids),
        "passed_session_count": sum(
            execution.passed and execution.session.session_id not in failed_id_set
            for execution in executions
        ),
        "failed_session_ids": list(failed_ids),
        "all_selected_passed": all_selected_passed,
        "pending_session_ids": pending_ids,
        "run_errors": run_errors,
    }
    write_json(options.iteration_root / "summary.json", summary)
    return 0 if all_selected_passed else 1


def run_live_version_sessions(
    sessions: Sequence[EvalSession],
    *,
    options: RunnerOptions,
) -> VersionRunOutcome:
    if not sessions:
        raise ValueError("live version session group must be non-empty")
    version = sessions[0].version
    if version not in SUPPORTED_VERSIONS or any(session.version != version for session in sessions):
        raise ValueError("live version session group must contain one supported version")
    if any(session.case.id in OFFLINE_CASE_IDS for session in sessions):
        raise ValueError("offline semantic cases cannot enter a live Wwise lifecycle")

    version_root = options.iteration_root / "versions" / version
    version_root.mkdir(parents=True, exist_ok=False)
    executions: list[PhaseExecution] = []
    errors: list[str] = []
    sandbox: SandboxProject | None = None
    lifecycle: HeadlessLifecycle | None = None
    bundle: EvalFixtureBundle | None = None
    source_hash_before: ProjectHash | None = None
    source_hash_after: ProjectHash | None = None
    source_mtime_before: float | None = None
    transaction_rows: list[dict[str, Any]] = []
    attempted_session_ids: list[str] = []
    failed_session_ids: list[str] = []
    sandbox_root = version_root / "sandbox-root"
    # Every semantic-matrix process contends on one repository-stable lock.
    # Its mutable project copies remain private to this iteration/version.
    lock = LiveSandboxLock(GLOBAL_LIVE_LIFECYCLE_LOCK_ROOT)
    lock_acquired = False

    try:
        lock.__enter__()
        lock_acquired = True
        live_env = live_version_environment(version, options=options, version_root=version_root)
        contract = require_live_environment(live_env)
        if contract.version != version or contract.sample_project_source is None:
            raise FixtureContractError("live environment did not resolve the exact requested Wwise version/project")

        sandbox = prepare_sample_project_sandbox(
            live_env,
            sandbox_root=sandbox_root,
            hash_strategy="full",
        )
        source_hash_before = hash_project(sandbox.source_root, preferred_strategy="full")
        source_mtime_before = sandbox.source_project.stat().st_mtime
        lifecycle = launch_sandboxed_wwise(sandbox, live_env)
        if lifecycle.port is None or str(sandbox.sandbox_project) not in lifecycle.command:
            raise FixtureContractError("Wwise lifecycle did not prove the sandbox project and dynamic WAAPI port")

        runner_environment = trusted_gateway_environment(
            {
                **sandbox.env,
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_VERSION": version,
                "WWISE_FIXTURE_PROJECT": str(sandbox.sandbox_project),
                "WWISE_SANDBOX_ROOT": str(sandbox.sandbox_root),
                "WWISE_WAAPI_HOST": lifecycle.host,
                "WWISE_WAAPI_PORT": str(lifecycle.port),
            }
        )
        bundle = create_shared_fixture_bundle(
            version=version,
            host=lifecycle.host,
            port=lifecycle.port,
            sandbox_path=sandbox.sandbox_path,
            private_root=version_root / "private-fixture",
            runner_env=runner_environment,
            packaged_gateway_binding=PackagedGatewayBinding(options.skill_source),
            timeout_seconds=30.0,
        )
        confirm_pair_ids = {session.pair_id for session in sessions if session.phase == "confirm"}
        preview_pairs: dict[str, PreviewPairState] = {}

        for session in sessions:
            attempted_session_ids.append(session.session_id)
            try:
                if session.phase == "confirm":
                    pair = preview_pairs.get(session.pair_id)
                    if pair is None:
                        raise FixtureContractError(
                            f"confirm phase {session.session_id} has no passed runner-owned preview dependency"
                        )
                    execution = run_live_confirm_phase(
                        session,
                        pair=pair,
                        bundle=bundle,
                        options=options,
                        runner_environment=runner_environment,
                    )
                elif session.case.id in QUERY_CASE_IDS:
                    execution = run_live_query_phase(
                        session,
                        bundle=bundle,
                        options=options,
                        runner_environment=runner_environment,
                    )
                elif session.case.id in FIXED_READ_CASE_IDS:
                    execution = run_live_fixed_read_phase(
                        session,
                        bundle=bundle,
                        options=options,
                        runner_environment=runner_environment,
                    )
                else:
                    execution, pair = run_live_preview_phase(
                        session,
                        bundle=bundle,
                        options=options,
                        runner_environment=runner_environment,
                        needs_confirm=session.pair_id in confirm_pair_ids,
                    )
                    if pair is not None:
                        preview_pairs[session.pair_id] = pair
            except BaseException as exc:  # noqa: BLE001 - retain exact failed-session accounting
                failure = format_exception(f"live-phase:{session.session_id}", exc)
                failed_session_ids.append(session.session_id)
                errors.append(failure)
                print_phase_error(session, failure)
                break

            executions.append(execution)
            if not execution.passed:
                failed_session_ids.append(session.session_id)
                if execution.error:
                    errors.append(execution.error)
                break
    except BaseException as exc:  # noqa: BLE001 - archive the original live failure and still tear down
        errors.append(format_exception("live-version-run", exc))
    finally:
        if bundle is not None:
            try:
                bundle.cleanup()
            except BaseException as exc:  # noqa: BLE001 - Wwise shutdown and source proof still run
                errors.append(format_exception("fixture-cleanup", exc))
            finally:
                transaction_rows = [json_safe_dataclass(item) for item in bundle.transactions]

        if lifecycle is not None and sandbox is not None:
            try:
                shutdown_sandboxed_wwise(lifecycle, sandbox, suppress_errors=False)
            except BaseException as exc:  # noqa: BLE001 - source proof and lock release still run
                errors.append(format_exception("wwise-shutdown", exc))

        if sandbox is not None and source_hash_before is not None:
            try:
                source_hash_after = hash_project(sandbox.source_root, preferred_strategy="full")
                if source_hash_after != source_hash_before:
                    raise AssertionError(
                        "immutable SampleProject source hash changed: "
                        f"before={source_hash_before.digest} after={source_hash_after.digest}"
                    )
                if source_mtime_before is None or sandbox.source_project.stat().st_mtime != source_mtime_before:
                    raise AssertionError("immutable SampleProject source project mtime changed")
            except BaseException as exc:  # noqa: BLE001
                errors.append(format_exception("source-project-proof", exc))

        phase_failed = any(not execution.passed for execution in executions)
        retained = bool(errors) or phase_failed
        if sandbox is not None:
            try:
                if retained:
                    sandbox.metadata.keep_decision = "retained-in-iteration-root-for-semantic-failure"
                    sandbox.write_metadata()
                else:
                    cleanup_sandbox(sandbox, keep=False, failed=False)
            except BaseException as exc:  # noqa: BLE001
                errors.append(format_exception("sandbox-cleanup", exc))
                retained = True

        if lock_acquired:
            try:
                lock.__exit__(None, None, None)
            except BaseException as exc:  # noqa: BLE001
                errors.append(format_exception("sandbox-lock-release", exc))

        write_json(
            version_root / "runtime.json",
            {
                "contract": "waapi-skill.codex-semantic-version-runtime/v2",
                "version": version,
                "session_ids": [session.session_id for session in sessions],
                "executed_session_ids": list(ordered_unique(attempted_session_ids)),
                "failed_session_ids": list(ordered_unique(failed_session_ids)),
                "global_lifecycle_lock": str(lock.path),
                "iteration_sandbox_root": str(sandbox_root),
                "source_hash_before": asdict(source_hash_before) if source_hash_before else None,
                "source_hash_after": asdict(source_hash_after) if source_hash_after else None,
                "sandbox_metadata": asdict(sandbox.metadata) if sandbox is not None else None,
                "fixture_transactions": transaction_rows,
                "sandbox_retained": retained,
                "errors": list(errors),
            },
        )

    return VersionRunOutcome(
        executions=tuple(executions),
        attempted_session_ids=ordered_unique(attempted_session_ids),
        failed_session_ids=ordered_unique(failed_session_ids),
        error="\n\n".join(errors),
    )


def run_live_query_phase(
    session: EvalSession,
    *,
    bundle: EvalFixtureBundle,
    options: RunnerOptions,
    runner_environment: Mapping[str, str],
) -> PhaseExecution:
    values = bundle.prompt_values(session.case.id, adapter=session.case.adapter)
    before = bundle.snapshot(session.case.id)

    def oracle_factory(observation: PhaseRunObservation) -> Mapping[str, Any]:
        after = bundle.snapshot(session.case.id)
        comparison = bundle.compare(session.case.id, before, after, expectation="unchanged")
        payload = broker_payload(observation.broker_evidence, "query-object")
        dispatch_rows = read_dispatch_evidence(observation.evidence_directory)
        object_get_dispatch_count = sum(
            row.get("api") == OBJECT_GET_URI for row in dispatch_rows
        )
        live_read_only = query_dispatch_evidence_matches(
            case_id=session.case.id,
            gateway_payload=payload,
            dispatch_rows=dispatch_rows,
        )
        oracle_matches = comparison.passed and query_payload_matches_fixture(payload, before)
        write_json(observation.phase_root / "outputs" / "oracle-comparison.json", json_safe_dataclass(comparison))
        write_json(
            observation.phase_root / "outputs" / "dispatcher-audit.json",
            {
                "records": dispatch_rows,
                "read_only": live_read_only,
                "object_get_dispatch_count": object_get_dispatch_count,
            },
        )
        return {
            "live_read_only": live_read_only,
            "object_get_dispatch_count": object_get_dispatch_count,
            "oracle_matches": oracle_matches,
            "final_response_matches": final_query_response_matches(
                observation.result.final_response,
                before,
            ),
        }

    return run_fresh_phase(
        session,
        values=values,
        oracle_factory=oracle_factory,
        options=options,
        runner_environment=runner_environment,
    )


def run_live_fixed_read_phase(
    session: EvalSession,
    *,
    bundle: EvalFixtureBundle,
    options: RunnerOptions,
    runner_environment: Mapping[str, str],
) -> PhaseExecution:
    """Run one closed fixed-command read with model-unwritable evidence."""

    if session.case.id not in FIXED_READ_CASE_IDS:
        raise ValueError(f"not a fixed-read semantic case: {session.case.id}")
    values = bundle.prompt_values(session.case.id, adapter=session.case.adapter)
    publisher_threads: list[threading.Thread] = []
    publisher_results: list[Mapping[str, Any]] = []
    publisher_errors: list[BaseException] = []
    publisher_abort = threading.Event()
    publisher_transaction_started = threading.Event()
    publisher_observed = False

    def publish_topic_probe() -> None:
        try:
            # The broker authorizes the exact wait command before its child
            # process opens the WAAPI subscription. Give that short-lived
            # process the same bounded setup window used by the real topic
            # matrix so the runner-owned create cannot win the startup race.
            # Infrastructure failure can cancel this pre-transaction wait;
            # after the transaction starts, teardown must instead wait for the
            # runner-owned create/delete sequence to reach a terminal state.
            if publisher_abort.wait(TOPIC_SUBSCRIPTION_SETTLE_SECONDS):
                return
            publisher_transaction_started.set()
            publisher_results.append(
                bundle.publish_object_created_probe(values["topic_probe_name"])
            )
        except BaseException as exc:  # noqa: BLE001 - transferred to the trusted oracle
            publisher_errors.append(exc)

    def pre_observer(
        step: ExpectedGatewayStep,
        state_directory: Path,
        evidence_directory: Path,
    ) -> None:
        del state_directory, evidence_directory
        if session.case.id != "R5" or step.name != "wait-topic":
            raise AssertionError("topic publisher hook reached an unexpected semantic step")
        if publisher_threads:
            raise AssertionError("topic publisher may start exactly once")
        thread = threading.Thread(
            target=publish_topic_probe,
            name=f"waapi-semantic-topic-{safe_session_name(session.session_id)}",
            daemon=False,
        )
        publisher_threads.append(thread)
        thread.start()

    def drain_publisher(*, abort_pending: bool, context: str) -> FixtureContractError | None:
        """Stop a pending publisher or drain its in-flight transaction safely.

        Python cannot safely terminate a thread that may own a WAAPI
        transaction.  The bounded join is therefore a deadline for accepting
        the phase, not permission to race version cleanup.  If that deadline
        expires, keep teardown closed behind an unbounded terminal barrier;
        packaged gateway subprocesses have their own timeouts, and the phase
        fails after the thread has stopped.
        """

        if abort_pending:
            publisher_abort.set()
        if not publisher_threads:
            return None
        if len(publisher_threads) != 1:
            return FixtureContractError("R5 topic publisher lifecycle lost its single-owner invariant")

        thread = publisher_threads[0]
        thread.join(timeout=TOPIC_PUBLISHER_JOIN_SECONDS)
        if not thread.is_alive():
            return None

        transaction_state = (
            "after the runner-owned transaction started"
            if publisher_transaction_started.is_set()
            else "before the runner-owned transaction start was observed"
        )
        # Fail closed: do not return to version-level fixture/Wwise teardown
        # while this thread can still create, read, or delete a probe object.
        thread.join()
        if thread.is_alive():  # pragma: no cover - a completed unbounded join cannot remain alive
            return FixtureContractError(
                f"R5 topic publisher remained alive during {context} {transaction_state}"
            )
        return FixtureContractError(
            "R5 topic publisher exceeded the "
            f"{TOPIC_PUBLISHER_JOIN_SECONDS:g}-second {context} deadline {transaction_state}; "
            "the in-flight publisher was drained before version teardown"
        )

    def publisher_failure() -> FixtureContractError | None:
        if not publisher_errors:
            return None
        error = publisher_errors[0]
        failure = FixtureContractError(
            f"R5 topic publisher failed: {type(error).__name__}: {error}"
        )
        failure.__cause__ = error
        return failure

    def await_publisher() -> Mapping[str, Any] | None:
        nonlocal publisher_observed
        if session.case.id != "R5":
            return None
        publisher_observed = True
        if len(publisher_threads) != 1:
            raise FixtureContractError("R5 broker did not start exactly one topic publisher")
        drain_error = drain_publisher(abort_pending=False, context="oracle")
        failure = publisher_failure()
        if drain_error is not None:
            if failure is not None:
                drain_error.add_note(str(failure))
            raise drain_error
        if failure is not None:
            raise failure
        if len(publisher_results) != 1:
            raise FixtureContractError("R5 topic publisher produced no unique evidence")
        return publisher_results[0]

    def oracle_factory(observation: PhaseRunObservation) -> Mapping[str, Any]:
        publisher = await_publisher()
        step_name = session.gateway_steps[0]
        payload = broker_payload(observation.broker_evidence, step_name)
        dispatch_rows = read_dispatch_evidence(observation.evidence_directory)
        live_read_only = fixed_read_dispatch_evidence_matches(
            case_id=session.case.id,
            version=session.version,
            gateway_payload=payload,
            dispatch_rows=dispatch_rows,
        )
        oracle_matches = fixed_read_payload_is_valid(
            case_id=session.case.id,
            version=session.version,
            gateway_payload=payload,
            dispatch_rows=dispatch_rows,
            values=values,
            publisher=publisher,
        )
        r4_dispatch_summary = (
            fixed_read_r4_dispatch_summary(dispatch_rows)
            if session.case.id == "R4"
            else None
        )
        write_json(
            observation.phase_root / "outputs" / "dispatcher-audit.json",
            {
                "records": dispatch_rows,
                "read_only": live_read_only,
                "expected_case": session.case.id,
            },
        )
        write_json(
            observation.phase_root / "outputs" / "fixed-read-oracle.json",
            {
                "payload_valid": oracle_matches,
                "dispatcher_summary": r4_dispatch_summary,
                "publisher": dict(publisher) if isinstance(publisher, Mapping) else None,
            },
        )
        return {
            "live_read_only": live_read_only,
            "oracle_matches": oracle_matches,
            "final_response_matches": final_fixed_read_response_matches(
                observation.result.final_response,
                case_id=session.case.id,
                gateway_payload=payload,
                dispatch_rows=dispatch_rows,
                values=values,
            ),
        }

    active_error: BaseException | None = None
    try:
        return run_fresh_phase(
            session,
            values=values,
            oracle_factory=oracle_factory,
            options=options,
            runner_environment=runner_environment,
            trusted_step_pre_observer=pre_observer if session.case.id == "R5" else None,
        )
    except BaseException as exc:  # noqa: BLE001 - preserve phase failure after publisher drain
        active_error = exc
        raise
    finally:
        # Infrastructure failure after broker acceptance must not race Wwise
        # teardown or leave a runner-owned probe transaction in flight.
        drain_error = drain_publisher(abort_pending=True, context="teardown")
        terminal_error = drain_error
        if terminal_error is None and not publisher_observed:
            terminal_error = publisher_failure()
        if terminal_error is not None:
            if active_error is not None:
                active_error.add_note(str(terminal_error))
            else:
                raise terminal_error


def run_live_preview_phase(
    session: EvalSession,
    *,
    bundle: EvalFixtureBundle,
    options: RunnerOptions,
    runner_environment: Mapping[str, str],
    needs_confirm: bool,
) -> tuple[PhaseExecution, PreviewPairState | None]:
    values = bundle.prompt_values(session.case.id, adapter=session.case.adapter)
    before = bundle.snapshot(session.case.id)

    def oracle_factory(observation: PhaseRunObservation) -> Mapping[str, Any]:
        after = bundle.snapshot(session.case.id)
        comparison = bundle.compare(session.case.id, before, after, expectation="unchanged")
        preview = broker_payload(observation.broker_evidence, "preview")
        mutation_count = count_dispatch_api(observation.evidence_directory, session.case.mutation_uri)
        write_json(observation.phase_root / "outputs" / "oracle-comparison.json", json_safe_dataclass(comparison))
        write_json(
            observation.phase_root / "outputs" / "dispatcher-audit.json",
            {
                "mutation_uri": session.case.mutation_uri,
                "mutation_uri_count": mutation_count,
                "records": read_dispatch_evidence(observation.evidence_directory),
            },
        )
        oracle: dict[str, Any] = {
            "transaction_state": preview.get("state"),
            "mutation_uri_count": mutation_count,
            "target_unchanged": comparison.passed,
            "final_response_matches": final_preview_response_matches(
                observation.result.final_response,
                preview,
                str(session.case.operation),
                session.render_request(values),
            ),
        }
        if session.case.id == "M2":
            oracle["imperative_does_not_bypass_confirmation"] = (
                preview.get("state") == TransactionState.AWAITING_CONFIRMATION.value
                and mutation_count == 0
                and comparison.passed
            )
        return oracle

    execution = run_fresh_phase(
        session,
        values=values,
        oracle_factory=oracle_factory,
        options=options,
        runner_environment=runner_environment,
    )
    if not execution.passed or not needs_confirm:
        return execution, None

    postprocess_stage = "preview-binding"
    try:
        transaction_id, artifact_hash = preview_binding(execution.broker_evidence)
        postprocess_stage = "preview-request-binding"
        preview = broker_payload(execution.broker_evidence, "preview")
        preview_summary = preview.get("preview_summary")
        expected_request = session.render_request(values)
        if not isinstance(preview_summary, Mapping) or not strict_json_equal(
            preview_summary.get("request"), expected_request
        ):
            raise FixtureContractError("trusted preview evidence did not preserve the exact rendered request")
        postprocess_stage = "preview-seal-create"
        seal = create_preview_seal(execution.state_directory, transaction_id)
        postprocess_stage = "preview-seal-verify"
        seal_evidence = verify_preview_seal(
            execution.state_directory,
            transaction_id,
            seal,
            allowed_states={TransactionState.AWAITING_CONFIRMATION},
        )
        write_json(execution.phase_root / "outputs" / "transaction-seal.json", seal.as_dict())
        write_json(
            execution.phase_root / "outputs" / "transaction-seal-evidence.json",
            seal_evidence.as_dict(),
        )
    except BaseException as exc:  # noqa: BLE001 - a passed model grade is not a completed paired preview
        return mark_phase_execution_failed(
            execution,
            prompt=session.render_prompt(values),
            stage=postprocess_stage,
            exc=exc,
        ), None
    return (
        execution,
        PreviewPairState(
            execution=execution,
            values=dict(values),
            before=before,
            seal=seal,
            transaction_id=transaction_id,
            artifact_hash=artifact_hash,
        ),
    )


def run_live_confirm_phase(
    session: EvalSession,
    *,
    pair: PreviewPairState,
    bundle: EvalFixtureBundle,
    options: RunnerOptions,
    runner_environment: Mapping[str, str],
) -> PhaseExecution:
    before_confirm = bundle.snapshot(session.case.id)
    unchanged = bundle.compare(session.case.id, pair.before, before_confirm, expectation="unchanged")
    unchanged.assert_passed()
    pre_b_seal = verify_preview_seal(
        pair.execution.state_directory,
        pair.transaction_id,
        pair.seal,
        allowed_states={TransactionState.AWAITING_CONFIRMATION},
    )
    observer_evidence: list[PreviewSealEvidence] = []
    expected_states = {
        "transaction-show": TransactionState.AWAITING_CONFIRMATION,
        "confirm": TransactionState.CONFIRMED,
        "execute": TransactionState.EXECUTED_UNVERIFIED,
        "verify": TransactionState.VERIFIED,
    }

    def observer(
        step: ExpectedGatewayStep,
        payload: Mapping[str, Any],
        state_directory: Path,
        evidence_directory: Path,
    ) -> None:
        del evidence_directory
        expected_state = expected_states[step.name]
        if payload.get("transaction_id") != pair.transaction_id:
            raise AssertionError(f"{step.name} payload changed transaction id")
        if payload.get("artifact_hash") != pair.artifact_hash:
            raise AssertionError(f"{step.name} payload changed artifact hash")
        if payload.get("state") != expected_state.value:
            raise AssertionError(
                f"{step.name} payload state {payload.get('state')!r} != {expected_state.value!r}"
            )
        if step.name == "transaction-show":
            confirmation = payload.get("confirmation")
            if not isinstance(confirmation, Mapping) or set(confirmation) != {
                "contract",
                "token",
                "binding",
            }:
                raise AssertionError(
                    "transaction-show payload has no closed confirmation binding"
                )
            token = confirmation.get("token")
            binding = confirmation.get("binding")
            expected_binding = {
                "material_contract": (
                    "waapi-skill.confirmation-token-material/v1"
                ),
                "transaction_id": pair.transaction_id,
                "artifact_hash": pair.artifact_hash,
                "state": TransactionState.AWAITING_CONFIRMATION.value,
                "event_sequence": pair.seal.event_sequence,
                "last_event_hash": pair.seal.last_event_hash,
            }
            if (
                confirmation.get("contract")
                != "waapi-skill.confirmation-binding/v1"
                or not isinstance(token, str)
                or not token
                or binding != expected_binding
            ):
                raise AssertionError(
                    "transaction-show confirmation binding differs from the sealed preview"
                )
        observer_evidence.append(
            verify_preview_seal(
                state_directory,
                pair.transaction_id,
                pair.seal,
                allowed_states={expected_state},
            )
        )

    values = {
        **pair.values,
        "transaction_id": pair.transaction_id,
        "preview_hash": pair.artifact_hash,
    }
    expected_request = session.render_request(values)

    def oracle_factory(observation: PhaseRunObservation) -> Mapping[str, Any]:
        after = bundle.snapshot(session.case.id)
        comparison = bundle.compare(session.case.id, before_confirm, after, expectation="applied")
        final_seal = verify_preview_seal(
            observation.state_directory,
            pair.transaction_id,
            pair.seal,
            allowed_states={
                TransactionState.AWAITING_CONFIRMATION,
                TransactionState.CONFIRMED,
                TransactionState.EXECUTED_UNVERIFIED,
                TransactionState.VERIFIED,
            },
        )
        payloads = [record.payload for record in observation.broker_evidence.records]
        complete_payloads = len(payloads) == 4 and all(isinstance(payload, Mapping) for payload in payloads)
        same_binding = complete_payloads and all(
            payload.get("transaction_id") == pair.transaction_id
            and payload.get("artifact_hash") == pair.artifact_hash
            for payload in payloads
            if isinstance(payload, Mapping)
        )
        show_payload = broker_payload(observation.broker_evidence, "transaction-show")
        show_summary = show_payload.get("preview_summary")
        same_binding = (
            same_binding
            and isinstance(show_summary, Mapping)
            and strict_json_equal(show_summary.get("request"), expected_request)
        )
        verify_payload = broker_payload(observation.broker_evidence, "verify")
        verification = verify_payload.get("verification")
        assertions = verification.get("assertions") if isinstance(verification, Mapping) else None
        verified = (
            verify_payload.get("state") == TransactionState.VERIFIED.value
            and verify_payload.get("verified") is True
            and isinstance(assertions, list)
            and bool(assertions)
            and all(isinstance(item, Mapping) and item.get("passed") is True for item in assertions)
            and final_seal.state == TransactionState.VERIFIED.value
            and tuple(item.state for item in observer_evidence)
            == tuple(state.value for state in expected_states.values())
        )
        dispatcher_mutation_count = count_dispatch_api(
            observation.evidence_directory,
            session.case.mutation_uri,
        )
        journal_mutation_count = count_journal_mutation(
            observation.state_directory,
            pair.transaction_id,
            str(session.case.mutation_uri),
        )
        mutation_count = (
            dispatcher_mutation_count
            if dispatcher_mutation_count == journal_mutation_count
            else -1
        )
        write_json(observation.phase_root / "outputs" / "oracle-comparison.json", json_safe_dataclass(comparison))
        write_json(observation.phase_root / "outputs" / "transaction-seal.json", pair.seal.as_dict())
        write_json(
            observation.phase_root / "outputs" / "transaction-seal-evidence.json",
            {
                "before_confirm": pre_b_seal.as_dict(),
                "step_checkpoints": [item.as_dict() for item in observer_evidence],
                "after_confirm": final_seal.as_dict(),
            },
        )
        write_json(
            observation.phase_root / "outputs" / "dispatcher-audit.json",
            {
                "mutation_uri": session.case.mutation_uri,
                "mutation_uri_count": mutation_count,
                "dispatcher_mutation_uri_count": dispatcher_mutation_count,
                "journal_mutation_uri_count": journal_mutation_count,
                "records": read_dispatch_evidence(observation.evidence_directory),
            },
        )
        return {
            "same_transaction_and_artifact_hash": same_binding,
            "mutation_uri_count": mutation_count,
            "verified": verified,
            "readback_matches": comparison.passed,
            "final_response_matches": final_confirm_response_matches(
                observation.result.final_response,
                verify_payload,
                pair.transaction_id,
                pair.artifact_hash,
                str(session.case.operation),
                expected_request,
            ),
        }

    return run_fresh_phase(
        session,
        values=values,
        oracle_factory=oracle_factory,
        options=options,
        runner_environment=runner_environment,
        existing_state_directory=pair.execution.state_directory,
        trusted_step_observer=observer,
    )


def run_fresh_phase(
    session: EvalSession,
    *,
    values: Mapping[str, str],
    runner_oracle: Mapping[str, Any] | None = None,
    oracle_factory: Callable[[PhaseRunObservation], Mapping[str, Any]] | None = None,
    options: RunnerOptions,
    runner_environment: Mapping[str, str],
    existing_state_directory: Path | None = None,
    trusted_step_pre_observer: TrustedStepPreObserver | None = None,
    trusted_step_observer: TrustedStepObserver | None = None,
) -> PhaseExecution:
    if (runner_oracle is None) == (oracle_factory is None):
        raise ValueError("provide exactly one of runner_oracle or oracle_factory")
    phase_root = options.iteration_root / "sessions" / safe_session_name(session.session_id)
    if phase_root.exists():
        raise RuntimeError(f"semantic phase directory already exists: {phase_root}")
    phase_root.mkdir(parents=True, exist_ok=False)
    workspace = phase_root / "agent-workspace"
    output_dir = phase_root / "outputs"
    output_dir.mkdir(parents=True, exist_ok=False)
    broker_root = phase_root / "broker"
    prompt = ""
    result: CodexRunResult | None = None
    broker: CodexGatewayBroker | None = None
    broker_evidence: GatewayBrokerEvidence | None = None
    reconciliation: GatewayBrokerReconciliation | None = None
    state_directory: Path | None = existing_state_directory
    evidence_directory: Path | None = None
    resolved_oracle: Mapping[str, Any] | None = None
    stage = "render-prompt"

    try:
        prompt = session.render_prompt(values)
        write_text(output_dir / "prompt.txt", prompt + "\n")
        stage = "prepare-agent-workspace"
        skill_install = prepare_agent_workspace(workspace, options.skill_source)
        stage = "build-gateway-protocol"
        expected_steps = build_expected_gateway_steps(session, values)
        stage = "broker-initialize"
        broker = CodexGatewayBroker(
            skill_source=options.skill_source,
            invocation_skill_source=(skill_install if os.name == "nt" else None),
            expected_steps=expected_steps,
            expected_wwise_version=session.version,
            runner_environment=runner_environment,
            working_root=broker_root,
            existing_state_directory=existing_state_directory,
            transport="tcp",
            runner_timeout_seconds=120,
            trusted_step_pre_observer=trusted_step_pre_observer,
            trusted_step_observer=trusted_step_observer,
        )
        stage = "broker-start"
        with broker:
            state_directory = broker.state_directory
            evidence_directory = broker.evidence_directory
            stage = "harness-initialize"
            harness = CodexCliHarness(
                CodexHarnessConfig(
                    workspace=workspace,
                    skill_source=options.skill_source,
                    codex_binary=options.codex_binary,
                    auth_json=options.auth_json,
                    model=options.model,
                    reasoning_effort=options.reasoning_effort,
                    service_tier=options.service_tier,
                    timeout_seconds=options.timeout_seconds,
                    expected_gateway_subcommands=session.gateway_steps,
                    expected_wwise_version=session.version,
                    # Localhost broker IPC is blocked by Codex's read-only profile.
                    # Only this empty workspace is writable; state/evidence remain
                    # outside it and every write is a hard grading failure.
                    sandbox_mode="workspace-write",
                    allow_output_write=False,
                    network_access=True,
                )
            )
            stage = "harness-run"
            try:
                result = harness.run(
                    prompt,
                    output_dir=output_dir,
                    extra_env=broker.model_environment_overrides(),
                )
            except CodexInfrastructureError as exc:
                # Preserve the completed CLI event stream while preventing a
                # pre-action service failure from entering Skill grading.
                result = exc.result
                stage = "codex-cli-infrastructure"
                raise
            stage = "broker-evidence"
            gateway_argvs = gateway_candidate_argvs(
                result,
                skill_source=skill_install,
                alternate_skill_sources=(options.skill_source,),
                expected_wwise_version=session.version,
            )
            broker_evidence = broker.evidence()
            stage = "broker-reconciliation"
            reconciliation = broker.reconcile(gateway_argvs)

        if state_directory is None or evidence_directory is None:
            raise AssertionError("broker completed without private state/evidence directories")
        if broker_evidence is None or reconciliation is None or result is None:
            raise AssertionError("fresh phase completed without harness/broker evidence")
        observation = PhaseRunObservation(
            session=session,
            values=dict(values),
            result=result,
            broker_evidence=broker_evidence,
            reconciliation=reconciliation,
            phase_root=phase_root,
            state_directory=state_directory,
            evidence_directory=evidence_directory,
        )
        stage = "runner-oracle"
        resolved_oracle = (
            dict(oracle_factory(observation))
            if oracle_factory is not None
            else dict(runner_oracle or {})
        )
        stage = "grader"
        grade = grade_eval_session(
            session,
            result,
            broker_evidence,
            reconciliation,
            workspace=workspace,
            skill_source=options.skill_source,
            broker_state_directory=state_directory,
            broker_evidence_directory=evidence_directory,
            runner_oracle=resolved_oracle,
        )
        execution = PhaseExecution(
            session=session,
            values=dict(values),
            result=result,
            broker_evidence=broker_evidence,
            reconciliation=reconciliation,
            runner_oracle=resolved_oracle,
            grade=grade,
            phase_root=phase_root,
            state_directory=state_directory,
            evidence_directory=evidence_directory,
        )
        stage = "phase-archive"
        archive_phase(execution, prompt=prompt)
        return execution
    except BaseException as exc:  # noqa: BLE001 - preserve original failure after immediate evidence archive
        if broker is not None:
            if state_directory is None:
                state_directory = best_effort_broker_path(broker, "state_directory")
            if evidence_directory is None:
                evidence_directory = best_effort_broker_path(broker, "evidence_directory")
            if broker_evidence is None:
                broker_evidence = best_effort_broker_evidence(broker)
        archive_phase_failure(
            session=session,
            values=values,
            prompt=prompt,
            phase_root=phase_root,
            stage=stage,
            exc=exc,
            result=result,
            broker_evidence=broker_evidence,
            reconciliation=reconciliation,
            runner_oracle=resolved_oracle,
            state_directory=state_directory,
            evidence_directory=evidence_directory,
        )
        raise


def gateway_candidate_argvs(
    result: CodexRunResult,
    *,
    skill_source: Path,
    alternate_skill_sources: Sequence[Path] = (),
    expected_wwise_version: str = "",
) -> tuple[tuple[str, ...], ...]:
    """Return every event command shaped like the target packaged runner.

    This deliberately does not require the broker shim interpreter.  A direct
    ``/usr/bin/python3`` bypass must be sent to reconciliation and fail rather
    than being filtered out before grading.
    """

    expected_runners = {
        os.path.abspath(os.fspath(source / "scripts" / "run.py"))
        for source in (skill_source, *alternate_skill_sources)
    }
    candidates: list[tuple[str, ...]] = []
    for record in result.command_facts.command_records:
        argv = normalized_gateway_command_argv(
            record.argv,
            expected_wwise_version=expected_wwise_version,
        )
        if (
            len(argv) >= 4
            and os.path.abspath(os.path.expanduser(argv[1])) in expected_runners
            and argv[2] == "gateway.py"
        ):
            candidates.append(argv)
    return tuple(candidates)


def archive_phase(execution: PhaseExecution, *, prompt: str) -> None:
    output_dir = execution.phase_root / "outputs"
    write_text(output_dir / "prompt.txt", prompt + "\n")
    write_json(
        output_dir / "phase.json",
        {
            "contract": PHASE_CONTRACT,
            "session_id": execution.session.session_id,
            "pair_id": execution.session.pair_id,
            "profile_id": execution.session.profile_id,
            "case_id": execution.session.case.id,
            "phase": execution.session.phase,
            "version": execution.session.version,
            "repetition": execution.session.repetition,
            "prompt": prompt,
            "template_values": dict(execution.values),
            "passed": execution.passed,
            "grade_passed": execution.grade.passed,
            "error": execution.error,
        },
    )
    write_json(output_dir / "codex-facts.json", execution.result.facts_dict())
    write_json(output_dir / "broker-evidence.json", execution.broker_evidence.as_dict(include_output=False))
    write_json(output_dir / "broker-reconciliation.json", asdict(execution.reconciliation))
    write_json(output_dir / "runner-oracle.json", execution.runner_oracle)
    write_json(output_dir / "grading.json", execution.grade.as_dict())
    write_text(output_dir / "events.jsonl", execution.result.stdout)
    write_text(output_dir / "stderr.txt", execution.result.stderr)
    write_text(output_dir / "final.txt", execution.result.final_response + "\n")


def mark_phase_execution_failed(
    execution: PhaseExecution,
    *,
    prompt: str,
    stage: str,
    exc: BaseException,
) -> PhaseExecution:
    """Turn runner-owned post-processing failure into an accounted phase FAIL."""

    failed = replace(execution, error=format_exception(stage, exc))
    try:
        archive_phase(failed, prompt=prompt)
    except BaseException:
        # archive_phase_failure below records both the original contract
        # failure and any artifacts still readable from the execution.
        pass
    archive_phase_failure(
        session=failed.session,
        values=failed.values,
        prompt=prompt,
        phase_root=failed.phase_root,
        stage=stage,
        exc=exc,
        result=failed.result,
        broker_evidence=failed.broker_evidence,
        reconciliation=failed.reconciliation,
        runner_oracle=failed.runner_oracle,
        state_directory=failed.state_directory,
        evidence_directory=failed.evidence_directory,
        grade_passed=failed.grade.passed,
    )
    return failed


def archive_phase_failure(
    *,
    session: EvalSession,
    values: Mapping[str, str],
    prompt: str,
    phase_root: Path,
    stage: str,
    exc: BaseException,
    result: CodexRunResult | None,
    broker_evidence: GatewayBrokerEvidence | None,
    reconciliation: GatewayBrokerReconciliation | None,
    runner_oracle: Mapping[str, Any] | None,
    state_directory: Path | None,
    evidence_directory: Path | None,
    grade_passed: bool = False,
) -> None:
    """Best-effort raw evidence archive that never masks the phase exception."""

    output_dir = phase_root / "outputs"
    infrastructure_payload = asdict(exc.failure) if isinstance(exc, CodexInfrastructureError) else None
    infrastructure_failure = infrastructure_payload is not None
    archive_errors: list[str] = []
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except BaseException as archive_exc:  # noqa: BLE001
        return

    if prompt:
        try:
            write_text(output_dir / "prompt.txt", prompt + "\n")
        except BaseException as archive_exc:  # noqa: BLE001
            archive_errors.append(f"prompt.txt: {type(archive_exc).__name__}: {archive_exc}")

    phase_payload = {
        "contract": PHASE_CONTRACT,
        "session_id": session.session_id,
        "pair_id": session.pair_id,
        "profile_id": session.profile_id,
        "case_id": session.case.id,
        "phase": session.phase,
        "version": session.version,
        "repetition": session.repetition,
        "prompt": prompt,
        "template_values": dict(values),
        "passed": False,
        "grade_passed": bool(grade_passed),
        "failure_class": "infrastructure" if infrastructure_failure else "phase_execution",
        "error": format_exception(stage, exc),
    }
    try_write_json(output_dir / "phase.json", phase_payload, archive_errors=archive_errors)

    if result is not None:
        try:
            facts = result.facts_dict()
        except BaseException as archive_exc:  # noqa: BLE001
            facts = {"facts_error": f"{type(archive_exc).__name__}: {archive_exc}"}
        try_write_json(output_dir / "codex-facts.json", facts, archive_errors=archive_errors)
        try_write_json(
            output_dir / "harness-result-raw.json",
            {
                "facts": facts,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "final_response": result.final_response,
            },
            archive_errors=archive_errors,
        )
        try_write_text(output_dir / "events.jsonl", result.stdout, archive_errors=archive_errors)
        try_write_text(output_dir / "stderr.txt", result.stderr, archive_errors=archive_errors)
        try_write_text(output_dir / "final.txt", result.final_response + "\n", archive_errors=archive_errors)

    if broker_evidence is not None:
        try:
            filtered = broker_evidence.as_dict(include_output=False)
            raw = broker_evidence.as_dict(include_output=True)
        except BaseException as archive_exc:  # noqa: BLE001
            archive_errors.append(f"broker evidence serialization: {type(archive_exc).__name__}: {archive_exc}")
        else:
            try_write_json(output_dir / "broker-evidence.json", filtered, archive_errors=archive_errors)
            try_write_json(output_dir / "broker-evidence-raw.json", raw, archive_errors=archive_errors)
    if reconciliation is not None:
        try:
            reconciliation_payload = asdict(reconciliation)
        except BaseException as archive_exc:  # noqa: BLE001
            archive_errors.append(f"broker reconciliation serialization: {type(archive_exc).__name__}: {archive_exc}")
        else:
            try_write_json(
                output_dir / "broker-reconciliation.json",
                reconciliation_payload,
                archive_errors=archive_errors,
            )
    if runner_oracle is not None:
        try_write_json(output_dir / "runner-oracle.json", runner_oracle, archive_errors=archive_errors)

    state_snapshot = archive_private_directory(
        state_directory,
        output_dir / "failure-state-snapshot",
    )
    evidence_snapshot = archive_private_directory(
        evidence_directory,
        output_dir / "failure-evidence-snapshot",
    )
    try_write_json(
        output_dir / "private-directory-snapshots.json",
        {"state": state_snapshot, "evidence": evidence_snapshot},
        archive_errors=archive_errors,
    )

    error_payload = {
        "contract": PHASE_ERROR_CONTRACT,
        "archived_at": utc_now(),
        "session_id": session.session_id,
        "stage": stage,
        "failure_class": "infrastructure" if infrastructure_failure else "phase_execution",
        "infrastructure_failure": infrastructure_payload,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        "prompt_archived": bool(prompt),
        "harness_result_available": result is not None,
        "broker_evidence_available": broker_evidence is not None,
        "reconciliation_available": reconciliation is not None,
        "state_directory": str(state_directory) if state_directory is not None else None,
        "evidence_directory": str(evidence_directory) if evidence_directory is not None else None,
        "archive_errors": archive_errors,
    }
    try_write_json(output_dir / "phase-error.json", error_payload, archive_errors=[])


def archive_private_directory(source: Path | None, destination: Path) -> dict[str, Any]:
    """Copy regular files without following links; return a fail-closed manifest."""

    manifest: dict[str, Any] = {
        "source": str(source) if source is not None else None,
        "destination": str(destination),
        "available": False,
        "copied_files": [],
        "errors": [],
    }
    if source is None:
        return manifest
    try:
        root = source.expanduser().resolve(strict=True)
        if source.is_symlink() or not root.is_dir():
            raise RuntimeError("private evidence source must be a real directory")
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True, exist_ok=False)
        manifest["available"] = True
        copied: list[str] = []
        errors: list[str] = []
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            target = destination / relative
            try:
                if path.is_symlink():
                    raise RuntimeError("refusing to follow symlink")
                if path.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif path.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
                    copied.append(relative.as_posix())
                else:
                    raise RuntimeError("unsupported non-regular filesystem entry")
            except BaseException as exc:  # noqa: BLE001
                errors.append(f"{relative.as_posix()}: {type(exc).__name__}: {exc}")
        manifest["copied_files"] = copied
        manifest["errors"] = errors
    except BaseException as exc:  # noqa: BLE001
        manifest["errors"] = [f"{type(exc).__name__}: {exc}"]
    return manifest


def try_write_json(path: Path, payload: Mapping[str, Any], *, archive_errors: list[str]) -> None:
    try:
        write_json(path, payload)
    except BaseException as exc:  # noqa: BLE001
        archive_errors.append(f"{path.name}: {type(exc).__name__}: {exc}")


def try_write_text(path: Path, text: str, *, archive_errors: list[str]) -> None:
    try:
        write_text(path, text)
    except BaseException as exc:  # noqa: BLE001
        archive_errors.append(f"{path.name}: {type(exc).__name__}: {exc}")


def best_effort_broker_path(broker: CodexGatewayBroker, attribute: str) -> Path | None:
    try:
        value = getattr(broker, attribute)
    except BaseException:  # noqa: BLE001
        return None
    return value if isinstance(value, Path) else None


def best_effort_broker_evidence(broker: CodexGatewayBroker) -> GatewayBrokerEvidence | None:
    try:
        return broker.evidence()
    except BaseException:  # noqa: BLE001
        return None


def live_version_environment(
    version: str,
    *,
    options: RunnerOptions,
    version_root: Path,
) -> dict[str, str]:
    return trusted_gateway_environment(
        {
            "WWISE_LIVE": "1",
            "WWISE_DESTRUCTIVE": "1",
            "WWISE_VERSION": version,
            "WWISE_TEST_CONFIG": str(options.live_config),
            "WWISE_SANDBOX_ROOT": str(version_root / "sandbox-root"),
        }
    )


def broker_payload(evidence: GatewayBrokerEvidence, step_name: str) -> Mapping[str, Any]:
    matches = [
        record.payload
        for record in evidence.records
        if record.step_name == step_name and isinstance(record.payload, Mapping)
    ]
    return dict(matches[0]) if len(matches) == 1 else {}


def preview_binding(evidence: GatewayBrokerEvidence) -> tuple[str, str]:
    preview = broker_payload(evidence, "preview")
    transaction_id = preview.get("transaction_id")
    artifact_hash = preview.get("artifact_hash")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise FixtureContractError("trusted preview evidence has no transaction id")
    if not isinstance(artifact_hash, str) or not _SHA256_RE.fullmatch(artifact_hash):
        raise FixtureContractError("trusted preview evidence has no canonical artifact hash")
    if preview.get("state") != TransactionState.AWAITING_CONFIRMATION.value:
        raise FixtureContractError("trusted preview evidence is not awaiting confirmation")
    if preview.get("executed") is not False or preview.get("verified") is not False:
        raise FixtureContractError("trusted preview evidence claims execution or verification")
    return transaction_id, artifact_hash


def read_dispatch_evidence(directory: Path) -> list[dict[str, Any]]:
    root = directory.expanduser().resolve(strict=True)
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            raise FixtureContractError(f"dispatcher evidence must be a regular file: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FixtureContractError(f"invalid dispatcher evidence {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise FixtureContractError(f"dispatcher evidence must be a JSON object: {path}")
        if payload.get("evidence_path") != str(path):
            raise FixtureContractError(f"dispatcher evidence path binding mismatch: {path}")
        api = payload.get("api")
        if not isinstance(api, str) or not api:
            raise FixtureContractError(f"dispatcher evidence has no API: {path}")
        rows.append(payload)
    return rows


def count_dispatch_api(directory: Path, uri: str | None) -> int:
    if not isinstance(uri, str) or not uri:
        raise FixtureContractError("mutation semantic case has no closed mutation URI")
    return sum(row.get("api") == uri for row in read_dispatch_evidence(directory))


def count_journal_mutation(
    state_directory: Path,
    transaction_id: str,
    mutation_uri: str,
) -> int:
    path = state_directory / "transactions" / transaction_id / "events.jsonl"
    if path.is_symlink() or not path.is_file():
        raise FixtureContractError(f"transaction journal is not a regular file: {path}")
    count = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FixtureContractError(f"invalid transaction journal line {line_number}: {exc}") from exc
        if not isinstance(event, Mapping):
            raise FixtureContractError(f"transaction journal line {line_number} is not an object")
        if event.get("event_type") != "execution_completed":
            continue
        details = event.get("details")
        dispatch_result = details.get("dispatch_result") if isinstance(details, Mapping) else None
        if (
            isinstance(dispatch_result, Mapping)
            and dispatch_result.get("ok") is True
            and dispatch_result.get("api") == mutation_uri
        ):
            count += 1
    return count


def fixed_read_dispatch_evidence_matches(
    *,
    case_id: str,
    version: str,
    gateway_payload: Mapping[str, Any],
    dispatch_rows: Sequence[Mapping[str, Any]],
) -> bool:
    """Require the exact read-only dispatcher sequence for R1-R6."""

    if case_id not in FIXED_READ_CASE_IDS or version not in SUPPORTED_VERSIONS:
        return False
    if not isinstance(gateway_payload, Mapping) or gateway_payload.get("ok") is not True:
        return False
    if not isinstance(dispatch_rows, Sequence) or isinstance(
        dispatch_rows, (str, bytes, bytearray)
    ):
        return False
    rows = tuple(dispatch_rows)
    if not rows or any(not isinstance(row, Mapping) for row in rows):
        return False
    if any(row.get("api") not in READ_ONLY_DISPATCH_APIS for row in rows):
        return False

    expected: tuple[str, ...]
    if case_id == "R1":
        expected = (
            "ak.wwise.core.getInfo",
            OBJECT_GET_URI if version == "2021.1" else "ak.wwise.core.getProjectInfo",
        )
    else:
        expected = {
            "R2": (OBJECT_GET_URI,),
            "R3": ("ak.wwise.ui.getSelectedObjects",),
            "R4": ("ak.wwise.core.object.getTypes",),
            "R5": ("ak.wwise.core.object.created",),
            "R6": ("ak.wwise.waapi.getFunctions",),
        }[case_id]
    if tuple(row.get("api") for row in rows) != expected:
        return False
    if case_id == "R3" and gateway_payload.get("status") == "unsupported_boundary":
        return rows[0].get("ok") is False
    return all(row.get("ok") is True for row in rows)


def fixed_read_payload_is_valid(
    *,
    case_id: str,
    version: str,
    gateway_payload: Mapping[str, Any],
    dispatch_rows: Sequence[Mapping[str, Any]],
    values: Mapping[str, str],
    publisher: Mapping[str, Any] | None,
) -> bool:
    """Validate one fixed-command payload without trusting model output."""

    if (
        case_id not in FIXED_READ_CASE_IDS
        or version not in SUPPORTED_VERSIONS
        or gateway_payload.get("ok") is not True
        or gateway_payload.get("detected_version") != version
    ):
        return False
    if case_id == "R1":
        project = gateway_payload.get("project")
        wwise = gateway_payload.get("wwise")
        return (
            gateway_payload.get("status") == "ok"
            and isinstance(project, Mapping)
            and all(isinstance(project.get(key), str) and project.get(key) for key in ("id", "name", "path"))
            and isinstance(wwise, Mapping)
            and isinstance(wwise.get("isCommandLine"), bool)
        )
    if case_id == "R2":
        buses = gateway_payload.get("buses")
        return (
            type(gateway_payload.get("count")) is int
            and isinstance(buses, list)
            and gateway_payload.get("count") == len(buses)
            and all(
                isinstance(row, Mapping)
                and all(isinstance(row.get(key), str) and row.get(key) for key in QUERY_OBJECT_KEYS)
                and row.get("type") == "Bus"
                for row in buses
            )
        )
    if case_id == "R3":
        status = gateway_payload.get("status")
        if status == "unsupported_boundary":
            return (
                gateway_payload.get("is_command_line") is True
                and gateway_payload.get("count") is None
                and gateway_payload.get("objects") is None
            )
        objects = gateway_payload.get("objects")
        return (
            status == "ok"
            and type(gateway_payload.get("count")) is int
            and isinstance(objects, list)
            and gateway_payload.get("count") == len(objects)
            and all(
                isinstance(row, Mapping)
                and all(isinstance(row.get(key), str) and row.get(key) for key in QUERY_OBJECT_KEYS)
                for row in objects
            )
        )
    if case_id == "R4":
        expected = fixed_read_r4_dispatch_summary(dispatch_rows)
        agent_result = gateway_payload.get("agent_result")
        return (
            gateway_payload.get("status") == "ok"
            and gateway_payload.get("operation") == "types"
            and gateway_payload.get("summary_only") is True
            and "normalized" not in gateway_payload
            and tuple(gateway_payload)[-1:] == ("agent_result",)
            and expected is not None
            and strict_json_equal(agent_result, expected)
        )
    if case_id == "R5":
        event = gateway_payload.get("event")
        event_object = event.get("object") if isinstance(event, Mapping) else None
        expected_name = values.get("topic_probe_name")
        expected_event_type = values.get("topic_probe_event_type")
        event_object_id = event_object.get("id") if isinstance(event_object, Mapping) else None
        publisher_object_id = publisher.get("object_id") if isinstance(publisher, Mapping) else None
        return (
            gateway_payload.get("topic") == "ak.wwise.core.object.created"
            and gateway_payload.get("match") == {"object": {"type": expected_event_type}}
            and gateway_payload.get("cleanup") == "unsubscribed"
            and isinstance(event_object, Mapping)
            and event_object.get("type") == expected_event_type
            and isinstance(event_object_id, str)
            and bool(event_object_id)
            and isinstance(publisher, Mapping)
            and publisher.get("name") == expected_name
            and isinstance(publisher_object_id, str)
            and bool(publisher_object_id)
            and event_object_id.casefold() == publisher_object_id.casefold()
            and publisher.get("created") is True
            and publisher.get("deleted") is True
        )
    inventory = gateway_payload.get("inventory")
    packaged = inventory.get("packaged_manifest") if isinstance(inventory, Mapping) else None
    uris = inventory.get("uris") if isinstance(inventory, Mapping) else None
    return (
        case_id == "R6"
        and isinstance(inventory, Mapping)
        and inventory.get("kind") == "function"
        and type(inventory.get("count")) is int
        and isinstance(uris, list)
        and inventory.get("count") == len(uris)
        and all(isinstance(uri, str) and uri.startswith("ak.") for uri in uris)
        and len(uris) == len(set(uris))
        and uris == sorted(uris)
        and isinstance(packaged, Mapping)
        and isinstance(packaged.get("matches"), bool)
    )


def final_fixed_read_response_matches(
    text: str,
    *,
    case_id: str,
    gateway_payload: Mapping[str, Any],
    dispatch_rows: Sequence[Mapping[str, Any]],
    values: Mapping[str, str],
) -> bool:
    result = parse_waapi_result_line(text)
    if result is None or case_id not in FIXED_READ_CASE_IDS:
        return False
    if case_id == "R1":
        project = gateway_payload.get("project")
        expected = {
            "detected_version": gateway_payload.get("detected_version"),
            "project": (
                {key: project.get(key) for key in ("id", "name", "path")}
                if isinstance(project, Mapping)
                else None
            ),
        }
    elif case_id == "R2":
        expected = {"count": gateway_payload.get("count"), "buses": gateway_payload.get("buses")}
    elif case_id == "R3":
        expected = {
            "status": gateway_payload.get("status"),
            "count": gateway_payload.get("count"),
            "objects": gateway_payload.get("objects"),
        }
    elif case_id == "R4":
        expected = fixed_read_r4_dispatch_summary(dispatch_rows)
        if (
            expected is None
            or not strict_json_equal(gateway_payload.get("agent_result"), expected)
        ):
            return False
    elif case_id == "R5":
        event = gateway_payload.get("event")
        event_object = event.get("object") if isinstance(event, Mapping) else None
        event_object_id = event_object.get("id") if isinstance(event_object, Mapping) else None
        if not isinstance(event_object_id, str) or not event_object_id:
            return False
        expected = {
            "topic": gateway_payload.get("topic"),
            "event_object_id": event_object_id,
            "cleanup": gateway_payload.get("cleanup"),
        }
    else:
        inventory = gateway_payload.get("inventory")
        packaged = inventory.get("packaged_manifest") if isinstance(inventory, Mapping) else None
        if not isinstance(inventory, Mapping) or not isinstance(packaged, Mapping):
            return False
        expected = {
            "kind": inventory.get("kind"),
            "count": inventory.get("count"),
            "matches_packaged": packaged.get("matches"),
        }
    return strict_json_equal(result, expected)


def fixed_read_r4_dispatch_summary(
    dispatch_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Independently derive the R4 answer from runner-owned dispatcher evidence."""

    if not isinstance(dispatch_rows, Sequence) or isinstance(
        dispatch_rows, (str, bytes, bytearray)
    ):
        return None
    matches = tuple(
        row
        for row in dispatch_rows
        if isinstance(row, Mapping)
        and row.get("api") == "ak.wwise.core.object.getTypes"
    )
    if len(matches) != 1 or matches[0].get("ok") is not True:
        return None
    raw_result = matches[0].get("result")
    if not isinstance(raw_result, Mapping):
        return None
    try:
        records = parse_get_types_result(raw_result)
    except Exception:  # noqa: BLE001 - malformed trusted evidence must fail closed
        return None
    return {
        "count": len(records),
        "contains_actor_mixer": any(
            record.name == "ActorMixer" or record.type == "ActorMixer"
            for record in records
        ),
    }


def query_payload_matches_fixture(
    payload: Mapping[str, Any],
    snapshot: OracleSnapshot,
) -> bool:
    expected_rows = _query_oracle_objects(snapshot)
    if expected_rows is None:
        return False
    rows = payload.get("objects")
    if (
        isinstance(payload.get("count"), bool)
        or payload.get("count") != len(expected_rows)
        or not isinstance(rows, list)
        or len(rows) != len(expected_rows)
    ):
        return False
    observed: dict[str, tuple[str, str, str, str]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not all(
            isinstance(row.get(field), str) for field in ("id", "name", "type", "path")
        ):
            return False
        key = row["id"].casefold()
        if key in observed:
            return False
        observed[key] = (row["id"], row["name"], row["type"], row["path"])
    expected = {
        item.id.casefold(): (item.id, item.name, item.type, item.path)
        for item in expected_rows
    }
    if len(expected) != len(expected_rows) or set(observed) != set(expected):
        return False
    return all(
        observed[key][1:] == expected[key][1:]
        for key in expected
    )


def query_dispatch_evidence_matches(
    *,
    case_id: str,
    gateway_payload: Mapping[str, Any],
    dispatch_rows: Sequence[Mapping[str, Any]],
) -> bool:
    """Prove one business object.get and only read-only auxiliary dispatches.

    ``ak.wwise.core.getInfo`` is performed by the gateway transport before the
    dispatcher and normally has no dispatcher record.  This contract does not
    assume that will remain true: auxiliary dispatcher rows are allowed only
    when they are successful and read-only, while the business object.get must
    occur exactly once.  Q5 also accepts the packaged gateway's structured
    exact-absence normalization, whose underlying dispatcher row is a known
    Wwise request failure on some supported versions.
    """

    if case_id not in QUERY_CASE_IDS or not isinstance(gateway_payload, Mapping):
        return False
    if not isinstance(dispatch_rows, Sequence) or isinstance(
        dispatch_rows, (str, bytes, bytearray)
    ):
        return False
    rows = tuple(dispatch_rows)
    if not rows or any(not isinstance(row, Mapping) for row in rows):
        return False
    if any(row.get("api") not in READ_ONLY_DISPATCH_APIS for row in rows):
        return False
    object_get_rows = tuple(row for row in rows if row.get("api") == OBJECT_GET_URI)
    if len(object_get_rows) != 1:
        return False
    if any(
        row.get("ok") is not True
        for row in rows
        if row.get("api") != OBJECT_GET_URI
    ):
        return False

    business = object_get_rows[0]
    if business.get("ok") is True:
        return True
    if case_id != "Q5":
        return False
    return _q5_normalized_absence_matches_dispatch(gateway_payload, business)


def _q5_normalized_absence_matches_dispatch(
    gateway_payload: Mapping[str, Any],
    dispatcher_row: Mapping[str, Any],
) -> bool:
    normalization_source = _q5_dispatch_normalization_source(dispatcher_row)
    if normalization_source is None:
        return False
    if "call" not in gateway_payload:
        return (
            gateway_payload.get("ok") is True
            and gateway_payload.get("status") == "ok"
            and gateway_payload.get("command") == "query-object"
            and gateway_payload.get("query_bound") == {"mode": "exact-object"}
            and type(gateway_payload.get("count")) is int
            and gateway_payload.get("count") == 0
            and gateway_payload.get("objects") == []
        )

    call = gateway_payload.get("call")
    if not isinstance(call, Mapping):
        return False
    normalization = call.get("normalization")
    if not isinstance(normalization, Mapping) or set(normalization) != {
        "kind",
        "source",
        "original",
    }:
        return False
    original = normalization.get("original")
    if not isinstance(original, Mapping) or set(original) != {
        "error_code",
        "waapi_error_uri",
        "waapi_error_details",
        "message",
        "evidence_path",
    }:
        return False
    provenance_fields = (
        "error_code",
        "waapi_error_uri",
        "waapi_error_details",
        "message",
        "evidence_path",
    )
    return (
        gateway_payload.get("ok") is True
        and gateway_payload.get("count") == 0
        and gateway_payload.get("objects") == []
        and call.get("ok") is True
        and call.get("api") == OBJECT_GET_URI
        and call.get("result") == {"return": []}
        and normalization.get("kind") == "exact-object-absence"
        and normalization.get("source") == normalization_source
        and all(original.get(field) == dispatcher_row.get(field) for field in provenance_fields)
    )


def _q5_dispatch_normalization_source(
    dispatcher_row: Mapping[str, Any],
) -> str | None:
    """Return the exact gateway normalization source for trusted Q5 evidence."""

    if (
        dispatcher_row.get("ok") is not False
        or dispatcher_row.get("error_code") != "WaapiRequestFailed"
        or "result" not in dispatcher_row
        or dispatcher_row.get("result") is not None
        or not isinstance(dispatcher_row.get("evidence_path"), str)
        or not dispatcher_row.get("evidence_path")
        or not isinstance(dispatcher_row.get("message"), str)
        or not dispatcher_row.get("message")
    ):
        return None
    error_uri = dispatcher_row.get("waapi_error_uri")
    if error_uri == "ak.wwise.query.unknown_object":
        return error_uri
    details = dispatcher_row.get("waapi_error_details")
    if (
        error_uri == "ak.wwise.query.invalid_query"
        and isinstance(details, Mapping)
        and isinstance(details.get("message"), str)
        and "object not found" in details["message"].casefold()
    ):
        return "ak.wwise.query.invalid_query:object-not-found"
    return None


def final_query_response_matches(text: str, snapshot: OracleSnapshot) -> bool:
    if snapshot.case_id not in QUERY_CASE_IDS:
        return False
    payload = _parse_waapi_result_line(text)
    if payload is None:
        return False
    if isinstance(snapshot.payload, MissingPathOracleSnapshot):
        return (
            snapshot.case_id == "Q5"
            and set(payload) == MISSING_QUERY_RESULT_KEYS
            and type(payload.get("count")) is int
            and payload.get("count") == 0
            and payload.get("objects") == []
            and payload.get("not_found") == snapshot.payload.path
        )
    if snapshot.case_id == "Q5" or not isinstance(
        snapshot.payload, (PathOracleSnapshot, ObjectRowsOracleSnapshot)
    ):
        return False
    if set(payload) != QUERY_RESULT_KEYS:
        return False
    objects = payload.get("objects")
    if not isinstance(objects, list) or any(
        not isinstance(row, Mapping) or set(row) != QUERY_OBJECT_KEYS
        for row in objects
    ):
        return False
    return query_payload_matches_fixture(payload, snapshot)


def _parse_waapi_result_line(text: str) -> dict[str, Any] | None:
    """Backward-compatible private alias for focused runner tests."""

    return parse_waapi_result_line(text)


def _query_oracle_objects(snapshot: OracleSnapshot) -> tuple[Any, ...] | None:
    if isinstance(snapshot.payload, PathOracleSnapshot):
        return (snapshot.payload.object,)
    if isinstance(snapshot.payload, ObjectRowsOracleSnapshot):
        return snapshot.payload.objects
    if isinstance(snapshot.payload, MissingPathOracleSnapshot):
        return ()
    return None


def final_preview_response_matches(
    text: str,
    preview: Mapping[str, Any],
    operation: str,
    expected_request: Mapping[str, Any],
) -> bool:
    payload = parse_waapi_result_line(text)
    transaction_id = preview.get("transaction_id")
    artifact_hash = preview.get("artifact_hash")
    preview_summary = preview.get("preview_summary")
    expected = {
        "operation": operation,
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "state": TransactionState.AWAITING_CONFIRMATION.value,
        "executed": False,
        "request": expected_request,
    }
    return (
        isinstance(payload, Mapping)
        and isinstance(transaction_id, str)
        and bool(transaction_id)
        and isinstance(artifact_hash, str)
        and bool(_SHA256_RE.fullmatch(artifact_hash))
        and isinstance(preview_summary, Mapping)
        and strict_json_equal(preview_summary.get("request"), expected_request)
        and strict_json_equal(preview.get("agent_result"), expected)
        and strict_json_equal(payload, expected)
    )


def final_confirm_response_matches(
    text: str,
    verify: Mapping[str, Any],
    transaction_id: str,
    artifact_hash: str,
    operation: str,
    expected_request: Mapping[str, Any],
) -> bool:
    payload = parse_waapi_result_line(text)
    expected = {
        "operation": operation,
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "state": TransactionState.VERIFIED.value,
        "executed": True,
        "verified": True,
        "request": expected_request,
    }
    return (
        isinstance(payload, Mapping)
        and isinstance(transaction_id, str)
        and bool(transaction_id)
        and isinstance(artifact_hash, str)
        and bool(_SHA256_RE.fullmatch(artifact_hash))
        and verify.get("transaction_id") == transaction_id
        and verify.get("artifact_hash") == artifact_hash
        and verify.get("state") == TransactionState.VERIFIED.value
        and verify.get("executed") is True
        and verify.get("verified") is True
        and strict_json_equal(verify.get("agent_result"), expected)
        and strict_json_equal(payload, expected)
    )


def strict_json_equal(left: Any, right: Any) -> bool:
    """Compare parsed JSON recursively without Python's bool/int coercions."""

    if isinstance(left, Mapping) or isinstance(right, Mapping):
        return (
            isinstance(left, Mapping)
            and isinstance(right, Mapping)
            and set(left) == set(right)
            and all(strict_json_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(strict_json_equal(a, b) for a, b in zip(left, right))
        )
    return type(left) is type(right) and left == right


def json_safe_dataclass(value: Any) -> dict[str, Any]:
    payload = asdict(value)
    return json_safe_mapping(payload)


def json_safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    def convert(item: Any) -> Any:
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, Mapping):
            return {str(key): convert(nested) for key, nested in item.items()}
        if isinstance(item, (list, tuple)):
            return [convert(nested) for nested in item]
        return item

    return convert(value)


def format_exception(stage: str, exc: BaseException) -> str:
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
    return f"[{stage}] {rendered}"


def offline_fixture_values(session: EvalSession) -> dict[str, str]:
    if session.case.id == "C1":
        return {}
    if session.case.id in BOUNDARY_CASE_IDS:
        return {}
    raise ValueError(f"case {session.case.id} is not an offline semantic case")


def offline_oracle(session: EvalSession) -> dict[str, Any]:
    if session.case.id == "C1":
        return {"offline_no_wwise": True}
    if session.case.id in BOUNDARY_CASE_IDS:
        return {
            "offline_no_wwise": True,
            "mutation_uri_count": 0,
        }
    raise ValueError(f"case {session.case.id} is not an offline semantic case")


def skill_venv_python() -> Path:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return (SKILL_ROOT / ".venv" / relative).resolve(strict=False)


def require_live_runner_dependencies() -> dict[str, Any]:
    """Fail before Codex or Wwise when the live fixture cannot import WAAPI.

    The offline-only semantic lane deliberately has no dependency on
    ``waapi-client``.  Callers invoke this only after selecting at least one
    live session.  This function performs no installation or environment
    mutation.
    """

    try:
        module = importlib.import_module("waapi")
        for symbol in ("WaapiClient", "WaapiRequestFailed"):
            getattr(module, symbol)
    except Exception as exc:
        raise LiveDependencyPreflightError(
            exception_type=type(exc).__name__,
            exception_message=str(exc),
        ) from exc

    interpreter = Path(sys.executable).expanduser().resolve(strict=False)
    return {
        "contract": LIVE_DEPENDENCY_PREFLIGHT_CONTRACT,
        "ok": True,
        "dependency": "waapi-client",
        "module": "waapi",
        "required_symbols": ["WaapiClient", "WaapiRequestFailed"],
        "current_interpreter": str(interpreter),
        "automatic_install_attempted": False,
    }


def trusted_gateway_environment(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the broker-side environment without exposing ambient Wwise state."""

    environment = {
        str(key): str(value)
        for key, value in os.environ.items()
        if not str(key).startswith(("WWISE_", "WAAPI_")) and str(key) != "BASH_ENV"
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if overrides:
        environment.update({str(key): str(value) for key, value in overrides.items()})
    return environment


def prepare_agent_workspace(
    workspace: Path,
    skill_source: Path,
    *,
    platform_name: str | None = None,
) -> Path:
    return prepare_workspace_skill_install(
        workspace,
        skill_source,
        platform_name=platform_name,
    )


def select_sessions(
    sessions: Sequence[EvalSession],
    *,
    case_ids: Sequence[str],
    versions: Sequence[str],
    pair_ids: Sequence[str] = (),
    offline_only: bool = False,
) -> tuple[EvalSession, ...]:
    selected_cases = frozenset(case_ids)
    selected_versions = frozenset(versions)
    selected_pairs = frozenset(pair_ids)
    available_pairs = frozenset(session.pair_id for session in sessions)
    unknown_pairs = tuple(pair_id for pair_id in pair_ids if pair_id not in available_pairs)

    selected = tuple(
        session
        for session in sessions
        if (not selected_cases or session.case.id in selected_cases)
        and (not selected_versions or session.version in selected_versions)
        and (not selected_pairs or session.pair_id in selected_pairs)
        and (not offline_only or session.case.id in OFFLINE_CASE_IDS)
    )
    selected_pair_ids = frozenset(session.pair_id for session in selected)
    excluded_pairs = tuple(
        pair_id
        for pair_id in pair_ids
        if pair_id in available_pairs and pair_id not in selected_pair_ids
    )
    selection_errors: list[str] = []
    if unknown_pairs:
        selection_errors.append(
            "requested --pair-id values do not exist in the expanded profile: "
            + ", ".join(unknown_pairs)
        )
    if excluded_pairs:
        selection_errors.append(
            "requested --pair-id values were excluded by the case/version/offline filters: "
            + ", ".join(excluded_pairs)
        )
    if selection_errors:
        raise SystemExit("; ".join(selection_errors))

    # Legacy profile/case/version selections intentionally include some
    # preview-only formal-matrix coverage.  Preserve that behavior unless the
    # caller opts into pair-addressable execution, where partial transaction
    # pairs would make retry/resume evidence unsafe.
    if selected_pairs:
        validate_atomic_session_pairs(selected)
    return selected


def validate_atomic_session_pairs(sessions: Sequence[EvalSession]) -> None:
    grouped: dict[str, list[EvalSession]] = {}
    for session in sessions:
        grouped.setdefault(session.pair_id, []).append(session)

    for pair_id, pair_sessions in grouped.items():
        phases = tuple(session.phase for session in pair_sessions)
        if phases not in {("single",), ("preview",), ("preview", "confirm")}:
            raise SystemExit(
                f"Selected pair {pair_id!r} is incomplete or malformed: expected exactly "
                f"('single',), ('preview',), or ('preview', 'confirm'), got {phases!r}."
            )
        identities = {
            (session.profile_id, session.case.id, session.version, session.repetition)
            for session in pair_sessions
        }
        if len(identities) != 1:
            raise SystemExit(
                f"Selected pair {pair_id!r} crosses profile/case/version/repetition boundaries."
            )


def prepare_iteration_root(path: Path, *, overwrite: bool) -> None:
    resolved = path.expanduser().resolve(strict=False)
    allowed_root = (SKILL_ROOT.parent / "waapi-skill-workspace").resolve(strict=False)
    if resolved == allowed_root:
        raise SystemExit(f"Refusing to use or recursively replace the semantic workspace root itself: {allowed_root}")
    try:
        relative = resolved.relative_to(allowed_root)
    except ValueError as exc:
        raise SystemExit(f"Iteration root must be a child of {allowed_root}: {resolved}") from exc
    if not relative.parts:
        raise SystemExit(f"Iteration root must name a run directory below {allowed_root}: {resolved}")
    if resolved.exists():
        if not overwrite:
            raise SystemExit(f"Iteration root exists; pass --overwrite to replace it: {resolved}")
        marker = resolved / ITERATION_MARKER_FILE
        if not valid_iteration_marker(marker, expected_root=resolved) and not valid_legacy_run_config(
            resolved / "run-config.json"
        ):
            raise SystemExit(
                "Refusing to replace an unmarked directory; expected a semantic iteration marker "
                f"or compatible run-config.json: {resolved}"
            )
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=False)
    write_json(
        resolved / ITERATION_MARKER_FILE,
        {
            "contract": ITERATION_MARKER_CONTRACT,
            "iteration_root": str(resolved),
            "created_at": utc_now(),
        },
    )


def valid_iteration_marker(path: Path, *, expected_root: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, Mapping)
        and payload.get("contract") == ITERATION_MARKER_CONTRACT
        and payload.get("iteration_root") == str(expected_root)
    )


def valid_legacy_run_config(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, Mapping)
        and payload.get("contract") == RUN_CONTRACT
        and isinstance(payload.get("expected_session_count"), int)
        and payload.get("expected_session_count", 0) > 0
        and payload.get("memory") == "disabled"
        and payload.get("fresh_session_per_phase") is True
        and isinstance(payload.get("skill_source"), str)
        and bool(payload.get("skill_source"))
        and isinstance(payload.get("suite_path"), str)
        and bool(payload.get("suite_path"))
    )


def safe_session_name(session_id: str) -> str:
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in session_id)
    return safe.strip("-")


def ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values))


def print_phase_outcome(execution: PhaseExecution) -> None:
    verdict = "PASS" if execution.passed else "FAIL"
    phase_error = execution.error.splitlines()[0] if execution.error else "-"
    print(
        f"[{verdict}] {execution.session.session_id} "
        f"duration={execution.result.duration_seconds:.3f}s "
        f"failed_gates={','.join(execution.grade.failed_gate_ids) or '-'} "
        f"phase_error={phase_error}"
    )


def print_phase_error(session: EvalSession, error: str) -> None:
    headline = error.splitlines()[0] if error else "unclassified phase failure"
    print(f"[ERROR] {session.session_id} {headline}")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_utf8_text_bytes(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_utf8_text_bytes(path, text)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_args(argv: Sequence[str] | None) -> RunnerOptions:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=(*PROFILE_IDS, *sorted(EXECUTABLE_V3_PROFILE_IDS)),
        default="screening",
    )
    parser.add_argument("--suite")
    parser.add_argument("--iteration-root")
    parser.add_argument("--skill-source", default=str(SKILL_ROOT))
    parser.add_argument(
        "--codex-binary",
        default=DEFAULT_CODEX_BINARY,
        help="explicit Codex CLI path; otherwise discover the host-native executable",
    )
    parser.add_argument("--auth-json", default=str(DEFAULT_AUTH_JSON))
    parser.add_argument("--live-config", default=str(DEFAULT_LIVE_CONFIG))
    parser.add_argument("--model")
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high", "xhigh", "ultra"),
        default="medium",
    )
    parser.add_argument("--service-tier")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--version", action="append", choices=SUPPORTED_VERSIONS, default=[])
    parser.add_argument("--pair-id", action="append", default=[])
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    is_executable_v3 = args.profile in EXECUTABLE_V3_PROFILE_IDS
    is_policy_v3 = args.profile == MODIFICATION_POLICY_V3_PROFILE_ID
    is_compound_v1 = args.profile == COMPOUND_HEAVY_V1_PROFILE_ID
    is_integration_v1 = args.profile == INTEGRATION_WORKFLOWS_V1_PROFILE_ID
    is_integration_v2 = args.profile == INTEGRATION_WORKFLOWS_V2_PROFILE_ID
    is_terra_v3 = (
        is_policy_v3
        or is_compound_v1
        or is_integration_v1
        or is_integration_v2
    )
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if len(set(args.version)) != len(args.version):
        parser.error("--version values must be unique")
    if len(set(args.pair_id)) != len(args.pair_id):
        parser.error("--pair-id values must be unique")
    if is_executable_v3 and args.pair_id:
        parser.error(f"--pair-id is not supported by {args.profile}")
    if is_executable_v3 and args.offline_only:
        parser.error(f"--offline-only is not supported by {args.profile}")
    if not is_executable_v3:
        unknown_case_ids = sorted(set(args.case_id) - set(CASE_IDS))
        if unknown_case_ids:
            parser.error(
                "unknown v2 --case-id values: " + ", ".join(unknown_case_ids)
            )
    if is_policy_v3 and args.version and args.version != ["2022.1"]:
        parser.error(
            f"{MODIFICATION_POLICY_V3_PROFILE_ID} supports only --version 2022.1"
        )
    if (is_compound_v1 or is_integration_v1 or is_integration_v2) and any(
        version not in {"2022.1", "2025.1"} for version in args.version
    ):
        parser.error(
            f"{args.profile} supports only "
            "--version 2022.1 and 2025.1"
        )
    model = args.model or (
        "gpt-5.6-terra" if is_terra_v3 else "gpt-5.6-sol"
    )
    service_tier = args.service_tier or (
        "default" if is_terra_v3 else "priority"
    )
    if is_terra_v3 and (
        model != "gpt-5.6-terra"
        or args.reasoning_effort != "medium"
        or service_tier != "default"
    ):
        parser.error(
            f"{args.profile} requires "
            "gpt-5.6-terra / medium / default"
        )
    suite = args.suite or str(
        (
            DEFAULT_MODIFICATION_POLICY_V3_SUITE
            if is_policy_v3
            else (
                DEFAULT_INTEGRATION_WORKFLOWS_V2_SUITE
                if is_integration_v2
                else (
                    DEFAULT_INTEGRATION_WORKFLOWS_V1_SUITE
                    if is_integration_v1
                    else DEFAULT_COMPOUND_HEAVY_V1_SUITE
                )
            )
        )
        if is_terra_v3
        else (DEFAULT_V3_SUITE if is_executable_v3 else DEFAULT_SUITE)
    )
    iteration_root = args.iteration_root or str(
        (
            DEFAULT_MODIFICATION_POLICY_V3_ITERATION_ROOT
            if is_policy_v3
            else (
                DEFAULT_INTEGRATION_WORKFLOWS_V2_ITERATION_ROOT
                if is_integration_v2
                else (
                    DEFAULT_INTEGRATION_WORKFLOWS_V1_ITERATION_ROOT
                    if is_integration_v1
                    else DEFAULT_COMPOUND_HEAVY_V1_ITERATION_ROOT
                )
            )
        )
        if is_terra_v3
        else (
            DEFAULT_HEAVY_V3_ITERATION_ROOT
            if is_executable_v3
            else DEFAULT_ITERATION_ROOT
        )
    )
    try:
        codex_binary = resolve_codex_binary(args.codex_binary)
    except CodexHarnessError as exc:
        parser.error(str(exc))
    return RunnerOptions(
        profile=str(args.profile),
        iteration_root=Path(iteration_root).expanduser().resolve(strict=False),
        suite_path=Path(suite).expanduser().resolve(strict=True),
        skill_source=Path(args.skill_source).expanduser().resolve(strict=True),
        codex_binary=codex_binary,
        auth_json=Path(args.auth_json).expanduser().resolve(strict=True),
        # This is a machine-local prerequisite, not part of argument syntax.
        # Keep its canonical host path even when the optional local fixture has
        # not been configured yet; real-Wwise preflight remains responsible for
        # requiring and validating the file before a live lifecycle starts.
        live_config=Path(args.live_config).expanduser().resolve(strict=False),
        model=str(model),
        reasoning_effort=str(args.reasoning_effort),
        service_tier=str(service_tier),
        timeout_seconds=float(args.timeout),
        case_ids=tuple(str(value) for value in args.case_id),
        versions=tuple(str(value) for value in args.version),
        pair_ids=tuple(str(value) for value in args.pair_id),
        offline_only=bool(args.offline_only),
        overwrite=bool(args.overwrite),
    )


if __name__ == "__main__":
    raise SystemExit(main())
