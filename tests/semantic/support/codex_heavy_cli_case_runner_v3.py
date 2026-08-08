"""Fresh-Codex/WwiseConsole executor for the 20 reviewed V3 CLI scenarios.

The business operation is always performed by the evaluated Codex task through
the packaged gateway.  Runner-owned direct WAAPI access exists only in the
optional project-loaded setup phase and the later read-only oracle phase.  The
business phase is a fresh case-owned ``WwiseConsole waapi-server`` process
started against a separate control project; the immutable ``waapi.call``
request alone supplies the operation project.  This keeps every target isolated
from the business server's startup, including migration's legacy source/target.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

from tests.semantic.support.codex_business_oracle_plan_v3 import (
    BusinessOraclePlanEvidence,
    business_family_for_api,
    write_business_oracle_plan,
)
from tests.semantic.support.codex_cli_business_plan_v3 import (
    CliBusinessPlanSections,
    compile_cli_business_plan,
    validate_cli_business_plan,
)
from tests.destructive.support.live_environment import require_live_environment
from tests.destructive.support.sandbox_fixture import LiveSandboxLock, hash_project
from tests.semantic.support.codex_campaign import stable_tree_sha256
from tests.semantic.support.codex_cli_runtime_v3 import (
    CLI_APIS,
    MAX_LOG_BYTES,
    CliDispatchEvidence,
    CliEventRecord,
    CliLifecyclePlan,
    CliObjectRecord,
    CliRuntimeBackend,
    CliRuntimeError,
    ClosedDirectCliBackend,
    PreparedCliRuntime,
    ProcessPhaseEvidence,
    ProcessPhaseSpec,
    SetupAudioImport,
    _canonical_language,
    _is_reviewed_2022_warnings_only_result,
    build_cli_runtime_plan,
    materialize_cli_runtime,
)
from tests.semantic.support.codex_eval_execution_v3 import (
    HeavyScenarioUnit,
    build_heavy_units,
)
from tests.semantic.support.codex_filesystem_security import write_utf8_text_bytes
from tests.semantic.support.codex_gateway_broker import (
    ExpectedGatewayStep,
    GatewayBrokerEvidence,
)
from tests.semantic.support.codex_harness import (
    CodexHarnessError,
    CodexInfrastructureError,
    WindowsPowerShellCoreHost,
    first_gateway_backed_agent_message,
)
from tests.semantic.support.codex_scenario_lifecycle_v3 import (
    GLOBAL_LIVE_LIFECYCLE_LOCK_ROOT,
)
from tests.semantic.support.codex_task_runner_v3 import V3TaskRun, run_v3_codex_task
from tests.semantic.support.codex_prompt_provenance_v3 import (
    serialize_protocol,
    write_prompt_provenance,
)
from tests.semantic.support.codex_transaction_seal import (
    validate_transaction_show_confirmation_against_store,
)
from tests.semantic.support.codex_project_prelaunch_v3 import (
    ProjectPrelaunchRequest,
    normalize_project_copy,
)
from wwise_waapi.headless import HeadlessLifecycle, find_free_port


HEAVY_CLI_RUN_CONTRACT = "waapi-skill.codex-heavy-cli-run/v3"
HEAVY_CLI_LIFECYCLE_CONTRACT = "waapi-skill.codex-heavy-cli-lifecycle/v3"
HEAVY_CLI_RUNNER_APIS = frozenset(CLI_APIS)
_SUPPORTED_VERSION = "2022.1"
HEAVY_CLI_REVIEWED_CASE_APIS = MappingProxyType(
    {
        "O22-CLI-CONVERT-EXTERNAL-01": "ak.wwise.cli.convertExternalSource",
        "O22-CLI-CONVERT-EXTERNAL-02": "ak.wwise.cli.convertExternalSource",
        "O22-CLI-CONVERT-EXTERNAL-03": "ak.wwise.cli.convertExternalSource",
        "O22-CLI-CONVERT-EXTERNAL-04": "ak.wwise.cli.convertExternalSource",
        "O22-CLI-CONVERT-EXTERNAL-05": "ak.wwise.cli.convertExternalSource",
        "O22-CLI-GENERATE-BANK-01": "ak.wwise.cli.generateSoundbank",
        "O22-CLI-GENERATE-BANK-02": "ak.wwise.cli.generateSoundbank",
        "O22-CLI-GENERATE-BANK-03": "ak.wwise.cli.generateSoundbank",
        "O22-CLI-GENERATE-BANK-04": "ak.wwise.cli.generateSoundbank",
        "O22-CLI-GENERATE-BANK-05": "ak.wwise.cli.generateSoundbank",
        "O22-CLI-MIGRATE-01": "ak.wwise.cli.migrate",
        "O22-CLI-MIGRATE-02": "ak.wwise.cli.migrate",
        "O22-CLI-MIGRATE-03": "ak.wwise.cli.migrate",
        "O22-CLI-MIGRATE-04": "ak.wwise.cli.migrate",
        "O22-CLI-MIGRATE-05": "ak.wwise.cli.migrate",
        "O22-CLI-TAB-IMPORT-01": "ak.wwise.cli.tabDelimitedImport",
        "O22-CLI-TAB-IMPORT-02": "ak.wwise.cli.tabDelimitedImport",
        "O22-CLI-TAB-IMPORT-03": "ak.wwise.cli.tabDelimitedImport",
        "O22-CLI-TAB-IMPORT-04": "ak.wwise.cli.tabDelimitedImport",
        "O22-CLI-TAB-IMPORT-05": "ak.wwise.cli.tabDelimitedImport",
    }
)
_REVIEWED_CLI_SCENARIO_SHA256 = MappingProxyType(
    {
        "O22-CLI-CONVERT-EXTERNAL-01": "52357dc6f63ae6ef5032158ed5d05b8c72c21fab6a520dde47bbfdb4e72d6fd9",
        "O22-CLI-CONVERT-EXTERNAL-02": "190f400ec802ff1d2ad0ffe93318d36981738183174b4a5415203f1c251282a2",
        "O22-CLI-CONVERT-EXTERNAL-03": "2b5d304b524be879dc6a80b5bf946fa22da280e5b4c68c434fcba15232d44839",
        "O22-CLI-CONVERT-EXTERNAL-04": "34b2b68e63fa4b4b99cd7ea246d715673e4777a336d4420f837d09cf7f9df244",
        "O22-CLI-CONVERT-EXTERNAL-05": "64e70f611a46f90f46d4f6a6de31ccfdfb60c074ae07da90060cb30f2007e718",
        "O22-CLI-GENERATE-BANK-01": "5d872cc0f51f3a28c0166d7bde69586a1ae2c3c89422dae7096633484e3f5fd5",
        "O22-CLI-GENERATE-BANK-02": "be0f843ae6f007d68c24bedbf6eb6d1572aa8d48f35b07a64f942f1d630bc5ce",
        "O22-CLI-GENERATE-BANK-03": "fdcf30a1a986d02f2b9287963a5f0d7adf3f78457bec5a47e48dda8f1d7d9ebc",
        "O22-CLI-GENERATE-BANK-04": "1e3114aeb1c3bfc7d189fd1aa2ca2a4e3ba50d9a4ceaf8717dc0292ddd9e4029",
        "O22-CLI-GENERATE-BANK-05": "6726d2ca8c9e3c00466ed34a51e85da80db64c7dbaa242a89dd9bcaf39d196e7",
        "O22-CLI-MIGRATE-01": "2d1aa07464e59376080992450cc4d0834ae37b189e11b8e44190b4c4f01d5496",
        "O22-CLI-MIGRATE-02": "c78962c7f0b7504090f89fee8e3b7a97a9307aa06156b6b3effe53de18719ccd",
        "O22-CLI-MIGRATE-03": "259b60e37dabb348d6484f8989566d502c7b3715499b9ccec9d392821fec0542",
        "O22-CLI-MIGRATE-04": "dc79118bb4ff391599d8fbebdb67792d2c80a95d76d77f4112ed7e672f5f8948",
        "O22-CLI-MIGRATE-05": "adc5ebb8780535e6123a5796256fa2d4e6022664738206a4c0e62665e5897f88",
        "O22-CLI-TAB-IMPORT-01": "17f08b2ee4000595cf5e6ac176229837c83fe431132f1659cb0ef308e06a2d44",
        "O22-CLI-TAB-IMPORT-02": "75c1da4f207eb49a8a634996b2140e559400c6743619f3ecb14068a2aff362ed",
        "O22-CLI-TAB-IMPORT-03": "54acc76e97ac86520dd39893c997e4572aed16fefa287ec5dd7d0da2727d43f2",
        "O22-CLI-TAB-IMPORT-04": "1997322548f8a2568709ee92648b202105f8870ab2e33efc514ec1278530eb13",
        "O22-CLI-TAB-IMPORT-05": "970591dcf222f08ff82ef07126521a944d40bf026bcfde3545f5359971b32475",
    }
)
_MAX_DISPATCH_RECORDS = 512
_MAX_DISPATCH_BYTES = 2 * 1024 * 1024
_DISPATCH_SUPPORT_API = "ak.wwise.core.getProjectInfo"
_DISPATCH_SUCCESS_KEYS = frozenset(
    {
        "api",
        "category",
        "dry_run",
        "error_code",
        "evidence_path",
        "item_type",
        "message",
        "ok",
        "result",
        "risk_level",
        "timeout",
        "version",
    }
)
_DISPATCH_RISK_LEVELS = MappingProxyType(
    {
        _DISPATCH_SUPPORT_API: "low",
        "ak.wwise.cli.convertExternalSource": "medium",
        "ak.wwise.cli.generateSoundbank": "medium",
        "ak.wwise.cli.migrate": "high",
        "ak.wwise.cli.tabDelimitedImport": "medium",
    }
)
_MIGRATION_EXIT_WAIT_SECONDS = 5.0
_PROJECT_PRELAUNCH_LANGUAGES = MappingProxyType(
    {
        "O22-CLI-GENERATE-BANK-02": ("Japanese", "Chinese(PRC)"),
        "O22-CLI-TAB-IMPORT-01": ("Japanese",),
    }
)
_LOAD_ISSUE_RE = re.compile(
    r"(?:load\s+issue|(?:warning|error).{0,80}(?:project|load)|"
    r"(?:project|load).{0,80}(?:warning|error))",
    re.I,
)
_WARNING_SEVERITY_RE = re.compile(r"\bwarning\b", re.I)
_ERROR_SEVERITY_RE = re.compile(r"\b(?:error|fatal|unresolved)\b", re.I)


class HeavyCliRunnerError(RuntimeError):
    """The CLI unit cannot produce trustworthy executable evidence."""


class _SemanticFailure(HeavyCliRunnerError):
    """Codex routing or the business oracle failed after the live task began."""


class _IndeterminateOutcome(HeavyCliRunnerError):
    """One exact execute reached the durable non-retryable indeterminate state."""


class _InfrastructureFailure(HeavyCliRunnerError):
    """The runner lifecycle, prerequisite, or cleanup proof is untrustworthy."""


@dataclass(frozen=True, slots=True)
class HeavyCliRunnerOptions:
    skill_source: Path
    codex_binary: Path
    auth_json: Path
    model: str
    reasoning_effort: str
    service_tier: str
    timeout_seconds: float
    live_environment: Mapping[str, str]
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None


@dataclass(frozen=True, slots=True)
class HeavyCliRunOutcome:
    scenario_id: str
    version: str
    status: str
    reason: str
    scenario_root: str
    task_root: str | None
    thread_id: str | None
    checks: Mapping[str, Any]
    lifecycle: Mapping[str, Any] | None

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": HEAVY_CLI_RUN_CONTRACT,
            "scenario_id": self.scenario_id,
            "version": self.version,
            "status": self.status,
            "reason": self.reason,
            "scenario_root": self.scenario_root,
            "task_root": self.task_root,
            "thread_id": self.thread_id,
            "checks": _json_value(self.checks),
            "lifecycle": _json_value(self.lifecycle),
        }


class CliPhaseSession(Protocol):
    spec: ProcessPhaseSpec
    host: str
    port: int

    def start(self) -> None: ...

    def close(self, *, expect_natural_exit: bool = False) -> "CliPhaseResult": ...


class CliBackendSession(Protocol):
    backend: CliRuntimeBackend
    call_count: int

    def close(self) -> None: ...


PhaseFactory = Callable[[ProcessPhaseSpec, Mapping[str, str]], CliPhaseSession]
BackendSessionFactory = Callable[[str, str, int], CliBackendSession]
TaskRunner = Callable[..., V3TaskRun]


@dataclass(frozen=True, slots=True)
class HeavyCliRunnerDependencies:
    """Narrow injection seam for focused fake tests; production uses defaults."""

    environment_resolver: Callable[[Mapping[str, str]], Any] = require_live_environment
    port_allocator: Callable[[str], int] = find_free_port
    lock_factory: Callable[[Path], Any] = LiveSandboxLock
    source_hasher: Callable[..., Any] = hash_project
    materialize_runtime: Callable[[Any], PreparedCliRuntime] = materialize_cli_runtime
    task_runner: TaskRunner = run_v3_codex_task
    phase_factory: PhaseFactory | None = None
    backend_session_factory: BackendSessionFactory | None = None


@dataclass(frozen=True, slots=True)
class CliPhaseResult:
    evidence: ProcessPhaseEvidence
    stdout: str
    stderr: str
    log_overflow: bool
    ready_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence": asdict(self.evidence),
            "stdout_sha256": hashlib.sha256(self.stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(self.stderr.encode("utf-8")).hexdigest(),
            "log_overflow": self.log_overflow,
            "ready_version": self.ready_version,
        }


class OwnedDirectCliCall:
    """One runner-owned direct client that is never exposed to Codex."""

    def __init__(self, *, host: str, port: int) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise _InfrastructureFailure("trusted direct WAAPI host must be loopback")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise _InfrastructureFailure("trusted direct WAAPI port is invalid")
        try:
            from waapi import WaapiClient, WaapiRequestFailed  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - live prerequisite
            raise _InfrastructureFailure("live CLI runner cannot import waapi-client") from exc
        self._client = WaapiClient(
            url=f"ws://{host}:{port}/waapi",
            allow_exception=True,
        )
        self._request_failed_type = WaapiRequestFailed
        self._closed = False
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def __call__(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Any:
        if self._closed:
            raise _InfrastructureFailure("trusted direct WAAPI client is closed")
        call_args = dict(args)
        call_options = dict(options)
        try:
            result = self._client.call(uri, call_args, options=call_options)
        except Exception as exc:
            if (
                isinstance(exc, self._request_failed_type)
                and _single_exact_object_lookup(uri, call_args)
                and _known_exact_object_absence(exc)
            ):
                result = {"return": []}
            else:
                raise
        self.calls.append((uri, call_args, call_options))
        return result

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        disconnect = getattr(self._client, "disconnect", None)
        if callable(disconnect):
            disconnect()


class _DirectBackendSession:
    def __init__(self, role: str, host: str, port: int) -> None:
        if role not in {"setup", "oracle"}:
            raise _InfrastructureFailure("direct backend is forbidden in the business phase")
        self._call = OwnedDirectCliCall(host=host, port=port)
        self.backend = ClosedDirectCliBackend(self._call)

    @property
    def call_count(self) -> int:
        return len(self._call.calls)

    def close(self) -> None:
        self._call.close()


class _HeadlessCliPhase:
    """Exact-argv WwiseConsole owner with an explicit case-owned project cwd."""

    def __init__(self, spec: ProcessPhaseSpec, launch_environment: Mapping[str, str]) -> None:
        self.spec = spec
        self.host = "127.0.0.1"
        try:
            port_index = spec.argv.index("--wamp-port") + 1
            self.port = int(spec.argv[port_index])
        except (ValueError, IndexError) as exc:
            raise _InfrastructureFailure(
                f"{spec.role} WwiseConsole argv lacks one valid --wamp-port"
            ) from exc
        self._started = False
        self._closed = False
        self._ready_version: str | None = None

        def process_factory(command: list[str], **kwargs: Any) -> Any:
            if kwargs.get("shell") not in {None, False}:
                raise _InfrastructureFailure("WwiseConsole phase attempted shell execution")
            actual_cwd = kwargs.get("cwd")
            if actual_cwd is not None and _resolved(actual_cwd) != _resolved(spec.cwd):
                raise _InfrastructureFailure("HeadlessLifecycle supplied the wrong phase cwd")
            kwargs["cwd"] = spec.cwd
            return subprocess.Popen(command, **kwargs)

        self.lifecycle = HeadlessLifecycle(
            console_path=Path(spec.argv[0]),
            project_path=Path(spec.project_path) if spec.project_path else None,
            port=self.port,
            host=self.host,
            launch_env=dict(launch_environment),
            process_factory=process_factory,
        )

    def start(self) -> None:
        if self._started or self._closed:
            raise _InfrastructureFailure("CLI process phase is single-use")
        # Mark the ownership attempt before launch so the runner's outer
        # ``finally`` can always call ``close`` after an early process exit or
        # readiness exception.  ``HeadlessLifecycle.shutdown`` is idempotent
        # when launch failed before a process was created.
        self._started = True
        self._ready_version = _ready_wwise_version(
            self.lifecycle.run_until_ready()
        )
        if self._ready_version != _SUPPORTED_VERSION:
            raise _InfrastructureFailure(
                f"{self.spec.role} WwiseConsole version mismatch: "
                f"expected {_SUPPORTED_VERSION}, got {self._ready_version}"
            )
        if tuple(self.lifecycle.command) != self.spec.argv:
            raise _InfrastructureFailure(f"{self.spec.role} WwiseConsole argv drifted")

    def close(self, *, expect_natural_exit: bool = False) -> CliPhaseResult:
        if not self._started or self._closed:
            raise _InfrastructureFailure("CLI process phase is not active")
        self._closed = True
        process = self.lifecycle.process
        if expect_natural_exit and process is not None:
            deadline = time.monotonic() + _MIGRATION_EXIT_WAIT_SECONDS
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
        returncode = process.poll() if process is not None else None
        natural_exit_before_shutdown = returncode is not None
        runner_shutdown_requested = returncode is None
        shutdown_error: str | None = None
        try:
            self.lifecycle.shutdown(suppress_errors=False)
        except BaseException as exc:  # noqa: BLE001 - preserved as blocking evidence
            shutdown_error = f"{type(exc).__name__}: {exc}"
        if returncode is None and process is not None:
            returncode = process.poll()
        report = self.lifecycle.cleanup_report
        residual = tuple(
            int(item.pid) for item in (report.residual_processes if report else ())
        )
        evidence = ProcessPhaseEvidence(
            role=self.spec.role,
            argv=tuple(self.lifecycle.command),
            cwd=self.spec.cwd,
            shell=False,
            started=True,
            ready=self.lifecycle.ready_result is not None,
            process_exited=bool(report is not None and report.process_exited),
            residual_pids=residual,
            shutdown_error=shutdown_error,
            open_project_path=self.spec.project_path,
            returncode=returncode,
            natural_exit_before_shutdown=natural_exit_before_shutdown,
            runner_shutdown_requested=runner_shutdown_requested,
        )
        stdout, stdout_over = _bounded_log("".join(self.lifecycle.output.stdout))
        stderr, stderr_over = _bounded_log("".join(self.lifecycle.output.stderr))
        return CliPhaseResult(
            evidence=evidence,
            stdout=stdout,
            stderr=stderr,
            log_overflow=stdout_over or stderr_over,
            ready_version=self._ready_version,
        )


class _SealedCliBackend:
    """In-memory oracle captured before its direct client/process are closed."""

    def __init__(
        self,
        *,
        context: Mapping[str, Any],
        objects: Sequence[CliObjectRecord],
        events: Sequence[CliEventRecord],
    ) -> None:
        self._context = MappingProxyType(dict(context))
        objects_by_path: dict[str, list[CliObjectRecord]] = {}
        localized_objects: dict[tuple[str, str], CliObjectRecord] = {}
        unlocalized_paths: set[str] = set()
        for item in objects:
            path_key = item.path.casefold()
            objects_by_path.setdefault(path_key, []).append(item)
            if item.language is None:
                if path_key in unlocalized_paths:
                    raise _InfrastructureFailure(
                        "sealed oracle contains duplicate unlocalized object paths"
                    )
                unlocalized_paths.add(path_key)
                continue
            language_key = _sealed_language(item.language)
            localized_key = (path_key, language_key)
            if localized_key in localized_objects:
                raise _InfrastructureFailure(
                    "sealed oracle contains duplicate canonical path/language "
                    "object bindings"
                )
            localized_objects[localized_key] = item
        self._objects_by_path = {
            path: tuple(rows) for path, rows in objects_by_path.items()
        }
        self._localized_objects = localized_objects

        events_by_path: dict[str, CliEventRecord] = {}
        for item in events:
            path_key = item.path.casefold()
            if path_key in events_by_path:
                raise _InfrastructureFailure(
                    "sealed oracle contains duplicate Event paths"
                )
            events_by_path[path_key] = item
        self._events = events_by_path

    def get_context(self) -> Mapping[str, Any]:
        return self._context

    def read_object(self, path: str) -> CliObjectRecord | None:
        rows = self._objects_by_path.get(path.casefold(), ())
        if len(rows) > 1:
            raise _InfrastructureFailure(
                "sealed oracle path-only object read is ambiguous across records"
            )
        return rows[0] if rows else None

    def read_localized_object(
        self,
        path: str,
        *,
        language: str,
    ) -> CliObjectRecord | None:
        language_key = _sealed_language(language)
        return self._localized_objects.get((path.casefold(), language_key))

    def read_event(self, path: str) -> CliEventRecord | None:
        return self._events.get(path.casefold())

    def ensure_object(self, *, path: str, object_type: str) -> CliObjectRecord:
        del path, object_type
        raise _InfrastructureFailure("sealed oracle cannot mutate objects")

    def import_audio(self, request: SetupAudioImport) -> CliObjectRecord:
        del request
        raise _InfrastructureFailure("sealed oracle cannot import audio")

    def replace_soundbank_inclusions(
        self,
        *,
        soundbank_path: str,
        event_paths: Sequence[str],
        filters: Sequence[str],
    ) -> None:
        del soundbank_path, event_paths, filters
        raise _InfrastructureFailure("sealed oracle cannot change inclusions")

    def save_project(self) -> None:
        raise _InfrastructureFailure("sealed oracle cannot save the project")


def _sealed_language(value: str) -> str:
    try:
        return _canonical_language(value)
    except CliRuntimeError as exc:
        raise _InfrastructureFailure(
            f"sealed oracle contains an unreviewed language: {value!r}"
        ) from exc


class _TaskObservers:
    def __init__(self, runtime: PreparedCliRuntime, *, endpoint: str) -> None:
        self.runtime = runtime
        self.endpoint = endpoint
        self.payloads: dict[str, Mapping[str, Any]] = {}
        self.checks: dict[str, Any] = {}

    def before_step(
        self,
        step: ExpectedGatewayStep,
        _state_directory: Path,
        _evidence_directory: Path,
    ) -> None:
        del step

    def after_step(
        self,
        step: ExpectedGatewayStep,
        payload: Mapping[str, Any],
        _state_directory: Path,
        _evidence_directory: Path,
    ) -> None:
        self.payloads[step.name] = MappingProxyType(dict(payload))
        if step.name.endswith(".transaction-show"):
            self.checks[f"{step.name}.confirmation_binding"] = (
                validate_transaction_show_confirmation_against_store(
                    payload,
                    _state_directory,
                )
            )
        if step.name.endswith(".preview"):
            verification = self.runtime.verify_preview_unchanged()
            verification.assert_passed()
            self.checks["preview_unchanged"] = True

    def after_turn(
        self,
        turn_index: int,
        result: Any,
        _broker_evidence: GatewayBrokerEvidence,
    ) -> None:
        if turn_index == 1:
            intro_response = first_gateway_backed_agent_message(
                result.stdout,
                validated_gateway_commands=result.command_facts.gateway_commands,
            )
            if intro_response is None:
                raise _SemanticFailure(
                    "first Skill-backed response has no visible agent message "
                    "after the first validated gateway command"
                )
            _require_natural_intro(
                intro_response,
                endpoint=self.endpoint,
                version=self.runtime.plan.version,
            )
            self.checks["first_use_intro"] = True
        if not result.final_response.strip():
            raise _SemanticFailure("Codex final response is empty")
        self.checks[f"turn_{turn_index:02d}_response_nonempty"] = True


def _project_prelaunch_request(
    unit: HeavyScenarioUnit,
) -> ProjectPrelaunchRequest | None:
    languages = _PROJECT_PRELAUNCH_LANGUAGES.get(unit.scenario.id, ())
    isolate_optional_sample_plugins = (
        unit.scenario.api == "ak.wwise.cli.generateSoundbank"
    )
    if not languages and not isolate_optional_sample_plugins:
        return None
    return ProjectPrelaunchRequest(
        scenario_id=unit.scenario.id,
        languages=languages,
        isolate_optional_sample_plugins=isolate_optional_sample_plugins,
    )


def _reviewed_scenario_sha256(unit: HeavyScenarioUnit) -> str:
    payload = json.dumps(
        asdict(unit.scenario),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_reviewed_cli_unit(unit: HeavyScenarioUnit) -> None:
    """Bind execution to the exact 20 reviewed suite rows and turn plans."""

    scenario_id = unit.scenario.id
    expected_api = HEAVY_CLI_REVIEWED_CASE_APIS.get(scenario_id)
    if expected_api is None:
        raise HeavyCliRunnerError(
            f"CLI runner does not own reviewed case id {scenario_id!r}"
        )
    if unit.scenario.api != expected_api:
        raise HeavyCliRunnerError(
            f"reviewed CLI case {scenario_id} is bound to {expected_api}, "
            f"not {unit.scenario.api}"
        )
    if unit.version != _SUPPORTED_VERSION or unit.scenario.versions != (
        _SUPPORTED_VERSION,
    ):
        raise HeavyCliRunnerError(
            "the reviewed CLI runner is pinned to one exact Wwise 2022.1 lane"
        )
    expected_sha256 = _REVIEWED_CLI_SCENARIO_SHA256[scenario_id]
    if _reviewed_scenario_sha256(unit) != expected_sha256:
        raise HeavyCliRunnerError(
            f"reviewed CLI scenario identity drifted for {scenario_id}"
        )
    expected_turns = build_heavy_units((unit.scenario,))[0].turns
    if unit.turns != expected_turns:
        raise HeavyCliRunnerError(
            f"reviewed CLI turn topology drifted for {scenario_id}"
        )


def run_heavy_cli_unit(
    unit: HeavyScenarioUnit,
    *,
    scenario_root: Path,
    options: HeavyCliRunnerOptions,
    dependencies: HeavyCliRunnerDependencies | None = None,
) -> HeavyCliRunOutcome:
    """Run one reviewed CLI unit with setup/business/oracle separation."""

    _validate_reviewed_cli_unit(unit)
    deps = dependencies or HeavyCliRunnerDependencies()
    phase_factory = deps.phase_factory or _default_phase_factory
    backend_factory = deps.backend_session_factory or _default_backend_factory
    root_input = Path(scenario_root).expanduser()
    root = root_input.resolve(strict=False)
    if root.exists() or root_input.is_symlink():
        raise HeavyCliRunnerError(f"fresh CLI scenario root already exists: {root}")
    if options.timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    evidence_root = root / "evidence"
    owned_root = root / "owned"
    case_root = owned_root / "case"
    task_root = evidence_root / "codex-task"
    checks: dict[str, Any] = {}
    phase_results: list[CliPhaseResult] = []
    task: V3TaskRun | None = None
    runtime: PreparedCliRuntime | None = None
    lifecycle: CliLifecyclePlan | None = None
    source_hash_before: Any = None
    source_hash_after: Any = None
    source_mtime_before: int | None = None
    source_mtime_after: int | None = None
    source_project: Path | None = None
    source_template_root: Path | None = None
    lock: Any = None
    lock_acquired = False
    active_phase: CliPhaseSession | None = None
    active_backend: CliBackendSession | None = None
    requested_status = "BLOCKED"
    reason = ""
    cleanup_errors: list[str] = []
    lifecycle_payload: dict[str, Any] | None = None
    cancelled: BaseException | None = None

    try:
        evidence_root.mkdir(parents=True, exist_ok=False)
        case_root.mkdir(parents=True, exist_ok=False)
        env = dict(options.live_environment)
        env.update(
            {
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_VERSION": unit.version,
            }
        )
        contract = deps.environment_resolver(env)
        if (
            contract.version != unit.version
            or contract.console_path is None
            or contract.sample_project_source is None
        ):
            raise _InfrastructureFailure(
                "live environment did not resolve exact 2022.1 console and SampleProject"
            )
        console_path = Path(contract.console_path).resolve(strict=True)
        sample_project = Path(contract.sample_project_source).resolve(strict=True)
        _assert_regular_project(sample_project)

        lock = deps.lock_factory(GLOBAL_LIVE_LIFECYCLE_LOCK_ROOT)
        lock.__enter__()
        lock_acquired = True
        project_root = case_root / "project"
        project_path = project_root / (
            "SampleProject.wproj" if unit.scenario.api == "ak.wwise.cli.migrate" else sample_project.name
        )
        prelaunch_request: ProjectPrelaunchRequest | None = None
        if unit.scenario.api != "ak.wwise.cli.migrate":
            source_template_root = sample_project.parent
            source_project = sample_project
            _assert_tree_has_no_symlinks(source_template_root)
            source_hash_before = deps.source_hasher(
                source_template_root,
                preferred_strategy="full",
            )
            source_mtime_before = source_project.stat().st_mtime_ns
            shutil.copytree(source_template_root, project_root, symlinks=False)
            prelaunch_request = _project_prelaunch_request(unit)
            if prelaunch_request is not None:
                prelaunch_io_root = case_root / "project-prelaunch-io"
                prelaunch_io_root.mkdir(parents=True, exist_ok=False)
                prelaunch_report = normalize_project_copy(
                    project_path,
                    io_root=prelaunch_io_root,
                    owned_root=case_root,
                    request=prelaunch_request,
                )
                checks["project_prelaunch_languages"] = list(
                    prelaunch_request.languages
                )
                checks["project_prelaunch_optional_plugins_isolated"] = (
                    prelaunch_request.isolate_optional_sample_plugins
                )
                checks["project_prelaunch_report"] = prelaunch_report.as_dict()
        plan = build_cli_runtime_plan(
            unit.scenario,
            version=unit.version,
            case_root=case_root,
            project_path=project_path,
            source_template_root=(
                None
                if unit.scenario.api == "ak.wwise.cli.migrate"
                else sample_project.parent
            ),
        )
        if source_template_root is None:
            source_template_root = plan.source_template_root
            source_project = source_template_root / "SampleProject.wproj"
            _assert_regular_project(source_project)
            _assert_tree_has_no_symlinks(source_template_root)
            source_hash_before = deps.source_hasher(
                source_template_root,
                preferred_strategy="full",
            )
            source_mtime_before = source_project.stat().st_mtime_ns
        elif plan.source_template_root != source_template_root:
            raise _InfrastructureFailure("CLI source template identity changed")
        runtime = deps.materialize_runtime(plan)
        _assert_tab_path_identity_closed(runtime)

        # WwiseConsole 2022.1 rejects ``waapi-server`` without a project.  A
        # separate control copy satisfies that product requirement while every
        # operation target remains solely in the broker-approved request.  The
        # control project is never exposed to Codex and is case-owned cleanup.
        host_root = plan.business_server_project_path.parent
        if host_root.exists():
            raise _InfrastructureFailure("CLI business-host project already exists")
        if plan.business_server_project_path == plan.project_path:
            raise _InfrastructureFailure("CLI business host must differ from target")
        host_source_root = (
            project_root
            if prelaunch_request is not None
            and prelaunch_request.isolate_optional_sample_plugins
            else sample_project.parent
        )
        _assert_tree_has_no_symlinks(host_source_root)
        shutil.copytree(host_source_root, host_root, symlinks=False)
        _assert_regular_project(plan.business_server_project_path)
        if host_source_root == project_root:
            project_pre_setup_sha256 = stable_tree_sha256(project_root)
            business_host_sha256 = stable_tree_sha256(host_root)
            if business_host_sha256 != project_pre_setup_sha256:
                raise _InfrastructureFailure(
                    "CLI business host differs from the normalized pre-setup project"
                )
            checks["business_host_normalized_copy_sha256"] = business_host_sha256

        port_count = 1 + int(plan.requires_setup) + int(plan.requires_oracle)
        ports = _allocate_distinct_ports(port_count, deps.port_allocator)
        cursor = iter(ports)
        setup_port = next(cursor) if plan.requires_setup else None
        business_port = next(cursor)
        oracle_port = next(cursor) if plan.requires_oracle else None
        lifecycle = plan.lifecycle_plan(
            console_path=console_path,
            setup_port=setup_port,
            business_port=business_port,
            oracle_port=oracle_port,
        )
        checks["lifecycle_contract"] = dict(runtime.lifecycle_contract)
        checks["phase_order"] = [phase.role for phase in lifecycle.phases]
        launch_env = _launch_environment(env, owned_root=owned_root, project_path=project_path)

        setup_evidence: ProcessPhaseEvidence | None = None
        if lifecycle.setup is not None:
            active_phase = phase_factory(lifecycle.setup, launch_env)
            active_phase.start()
            active_backend = backend_factory("setup", active_phase.host, active_phase.port)
            runtime.prepare_setup(active_backend.backend)
            checks["setup_direct_call_count"] = active_backend.call_count
            active_backend.close()
            active_backend = None
            setup_result = active_phase.close()
            active_phase = None
            phase_results.append(setup_result)
            _require_clean_phase(lifecycle.setup, setup_result)
            setup_evidence = setup_result.evidence
        runtime.seal_before(lifecycle=lifecycle, setup_evidence=setup_evidence)
        protocol = runtime.gateway_protocol()
        typed_business_plan = compile_cli_business_plan(runtime, protocol)
        validate_cli_business_plan(
            typed_business_plan,
            runtime,
            protocol,
            verify_files=True,
        )
        request_provenance = dict(runtime.request_provenance())
        if typed_business_plan.static_expectation["request_provenance"] != request_provenance:
            raise _InfrastructureFailure(
                "typed CLI business plan request provenance differs from runtime"
            )
        checks["request_provenance"] = request_provenance

        active_phase = phase_factory(lifecycle.business, launch_env)
        active_phase.start()
        business_phase = active_phase
        runner_environment = {
            **launch_env,
            "WWISE_FIXTURE_PROJECT": str(project_path),
            "WWISE_SANDBOX_ROOT": str(case_root),
            "WWISE_WAAPI_HOST": business_phase.host,
            "WWISE_WAAPI_PORT": str(business_phase.port),
            "WWISE_VERSION": unit.version,
        }
        prompts = (runtime.render_prompt(), *(turn.prompt for turn in unit.turns[1:]))
        if len(prompts) != len(protocol.turn_prefix_counts):
            raise _InfrastructureFailure("CLI prompt topology differs from broker protocol")
        observer = _TaskObservers(
            runtime,
            endpoint=f"{business_phase.host}:{business_phase.port}",
        )
        provenance = write_prompt_provenance(
            scenario=unit.scenario,
            version=unit.version,
            scenario_root=root,
            prompts=prompts,
            visible_values=runtime.visible_values,
            protocol=protocol,
        )
        business_oracle_plan = _write_common_business_oracle_plan(
            scenario=unit.scenario,
            version=unit.version,
            scenario_root=root,
            protocol=protocol,
            provenance=provenance,
            runner="cli",
            typed_sections=typed_business_plan,
        )
        task_runner_failed = False
        try:
            task = deps.task_runner(
                scenario_id=unit.unit_id,
                version=unit.version,
                scenario=unit.scenario,
                prompts=prompts,
                protocol=protocol,
                task_root=task_root,
                skill_source=options.skill_source,
                codex_binary=options.codex_binary,
                windows_powershell_core_host=options.windows_powershell_core_host,
                auth_json=options.auth_json,
                model=options.model,
                reasoning_effort=options.reasoning_effort,
                service_tier=options.service_tier,
                timeout_seconds=options.timeout_seconds,
                runner_environment=runner_environment,
                required_reference="references/waapi-operate.md",
                business_oracle_plan=business_oracle_plan,
                trusted_step_pre_observer=observer.before_step,
                trusted_step_observer=observer.after_step,
                turn_observer=observer.after_turn,
            )
        except BaseException:  # noqa: BLE001 - close must preserve failure cleanup proof
            task_runner_failed = True
            raise
        finally:
            # Migration may asynchronously close its separate control host.
            # Wait only for that bounded possibility; a later runner shutdown
            # remains distinct evidence and never proves a disconnect.
            business_result = business_phase.close(
                expect_natural_exit=plan.business_disconnect_may_occur
            )
            active_phase = None
            phase_results.append(business_result)
            # When the task raises, control skips the ordinary clean-phase gate
            # below.  Preserve any residual process, shutdown, readiness, or
            # log blocker now so a Codex service/quota error can never turn
            # uncertain Wwise cleanup into a retryable campaign observation.
            if task_runner_failed:
                cleanup_errors.extend(
                    _phase_blockers(lifecycle.business, business_result)
                )
        _require_clean_phase(lifecycle.business, business_result)
        if task is None:
            raise _InfrastructureFailure("fresh Codex CLI task returned no evidence")
        _validate_task_run(
            unit,
            task=task,
            task_root=task_root,
            expected_turn_count=len(prompts),
        )
        checks.update(observer.checks)
        checks["task_passed"] = bool(task.passed)
        checks["thread_id"] = task.thread_id
        if bool(getattr(task, "terminal_indeterminate", False)):
            checks["task_terminal_indeterminate"] = True
            raise _IndeterminateOutcome(
                "fresh Codex task stopped after an exact non-retryable "
                "indeterminate execute result"
            )

        dispatch = _build_dispatch_evidence(
            runtime,
            task=task,
            business=business_result,
        )
        checks["primary_dispatch"] = {
            "api": dispatch.api,
            "count": dispatch.primary_dispatch_count,
            "connection_lost": dispatch.connection_lost,
            "connection_lost_after_dispatch": dispatch.connection_lost_after_dispatch,
        }
        if dispatch.classified_load_issues:
            # Preserve the exact bounded Wwise diagnostics in outcome evidence;
            # a result=2 migration warning is accepted only by this explicit
            # product/result classification, never by dropping log lines.
            checks["classified_migration_load_warnings"] = list(
                dispatch.classified_load_issues
            )

        sealed_oracle: CliRuntimeBackend | None = None
        oracle_evidence: ProcessPhaseEvidence | None = None
        if lifecycle.oracle is not None:
            active_phase = phase_factory(lifecycle.oracle, launch_env)
            active_phase.start()
            active_backend = backend_factory("oracle", active_phase.host, active_phase.port)
            sealed_oracle = _capture_sealed_oracle(runtime, active_backend.backend)
            checks["oracle_direct_call_count"] = active_backend.call_count
            active_backend.close()
            active_backend = None
            oracle_result = active_phase.close()
            active_phase = None
            phase_results.append(oracle_result)
            _require_clean_phase(lifecycle.oracle, oracle_result)
            oracle_evidence = oracle_result.evidence
            checks["oracle_captured_before_close_and_used_after_close"] = True

        verification = runtime.verify_after(
            dispatch=dispatch,
            lifecycle=lifecycle,
            business_evidence=business_result.evidence,
            oracle_backend=sealed_oracle,
            oracle_evidence=oracle_evidence,
        )
        checks["business_verification"] = _oracle_evidence(
            scenario=unit.scenario,
            version=unit.version,
            business_oracle_plan_sha256=business_oracle_plan.sha256,
            verification=verification,
        )
        if not verification.passed:
            raise _SemanticFailure("; ".join(verification.failures))
        requested_status = "PASS"
    except BaseException as exc:  # noqa: BLE001 - cleanup and source proof still run
        reason = f"{type(exc).__name__}: {exc}"
        checks["exception"] = reason
        requested_status = _failure_status(
            exc,
            task_root=task_root,
            terminal_execute_indeterminate=_terminal_execute_is_indeterminate(task),
        )
        checks["failure_classification"] = requested_status
        if isinstance(exc, CodexInfrastructureError):
            checks["codex_infrastructure_failure"] = (
                _codex_infrastructure_failure_evidence(exc)
            )
        if not isinstance(exc, Exception):
            cancelled = exc
    finally:
        if active_backend is not None:
            try:
                active_backend.close()
            except BaseException as exc:  # noqa: BLE001
                cleanup_errors.append(f"direct-client-close:{type(exc).__name__}:{exc}")
        if active_phase is not None:
            try:
                abandoned = active_phase.close(
                    expect_natural_exit=(
                        runtime is not None
                        and active_phase.spec.role == "business"
                        and runtime.plan.business_disconnect_may_occur
                    )
                )
                phase_results.append(abandoned)
                if _phase_blockers(active_phase.spec, abandoned):
                    cleanup_errors.extend(_phase_blockers(active_phase.spec, abandoned))
            except BaseException as exc:  # noqa: BLE001
                cleanup_errors.append(f"phase-close:{type(exc).__name__}:{exc}")

        if source_template_root is not None and source_project is not None:
            try:
                source_hash_after = deps.source_hasher(
                    source_template_root,
                    preferred_strategy="full",
                )
                source_mtime_after = source_project.stat().st_mtime_ns
                if source_hash_after != source_hash_before:
                    raise _InfrastructureFailure("immutable source project tree changed")
                if source_mtime_after != source_mtime_before:
                    raise _InfrastructureFailure("immutable source project mtime changed")
                checks["source_template_unchanged"] = True
            except BaseException as exc:  # noqa: BLE001
                cleanup_errors.append(f"source-proof:{type(exc).__name__}:{exc}")

        if lock_acquired:
            try:
                lock.__exit__(None, None, None)
                lock_acquired = False
            except BaseException as exc:  # noqa: BLE001
                cleanup_errors.append(
                    f"lifecycle-lock-release:{type(exc).__name__}:{exc}"
                )

        if cleanup_errors:
            requested_status = "BLOCKED"
            reason = _append_reason(reason, "; ".join(cleanup_errors))

        if root.exists():
            retained = requested_status != "PASS"
            quarantine_path: str | None = None
            try:
                if requested_status == "PASS":
                    if owned_root.exists():
                        shutil.rmtree(owned_root, ignore_errors=False)
                    if owned_root.exists():
                        raise _InfrastructureFailure(
                            "successful CLI case retained runner-owned state"
                        )
                elif owned_root.exists():
                    quarantine = evidence_root / "quarantine.json"
                    _write_json(
                        quarantine,
                        {
                            "contract": HEAVY_CLI_LIFECYCLE_CONTRACT,
                            "status": requested_status,
                            "owned_root": str(owned_root),
                            "owned_tree_sha256": stable_tree_sha256(owned_root),
                            "never_reuse": True,
                        },
                    )
                    quarantine_path = str(quarantine)
            except BaseException as exc:  # noqa: BLE001
                requested_status = "BLOCKED"
                retained = True
                reason = _append_reason(
                    reason,
                    f"owned-cleanup:{type(exc).__name__}:{exc}",
                )
            lifecycle_payload = {
                "contract": HEAVY_CLI_LIFECYCLE_CONTRACT,
                "requested_status": requested_status,
                "final_status": requested_status,
                "owned_state_retained": retained,
                "quarantine_path": quarantine_path,
                "source_hash_before": _json_value(source_hash_before),
                "source_hash_after": _json_value(source_hash_after),
                "source_mtime_before_ns": source_mtime_before,
                "source_mtime_after_ns": source_mtime_after,
                "phases": [item.as_dict() for item in phase_results],
                "errors": list(cleanup_errors),
            }
            _write_json(evidence_root / "lifecycle.json", lifecycle_payload)

    outcome = HeavyCliRunOutcome(
        scenario_id=unit.unit_id,
        version=unit.version,
        status=requested_status,
        reason=reason,
        scenario_root=str(root),
        task_root=str(task_root) if task_root.exists() else None,
        thread_id=task.thread_id if task is not None else None,
        checks=MappingProxyType(dict(checks)),
        lifecycle=MappingProxyType(dict(lifecycle_payload)) if lifecycle_payload else None,
    )
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "outcome.json", outcome.as_dict())
    if cancelled is not None:
        raise cancelled
    return outcome


def _codex_infrastructure_failure_evidence(
    exc: CodexInfrastructureError,
) -> dict[str, Any]:
    """Archive the closed pre-agent facts without parsing exception prose."""

    failure = exc.failure
    return {
        "category": failure.category,
        "turn_failed": failure.turn_failed,
        "timed_out": failure.timed_out,
        "agent_item_event_count": failure.agent_item_event_count,
    }


def _default_phase_factory(
    spec: ProcessPhaseSpec,
    environment: Mapping[str, str],
) -> CliPhaseSession:
    return _HeadlessCliPhase(spec, environment)


def _default_backend_factory(role: str, host: str, port: int) -> CliBackendSession:
    return _DirectBackendSession(role, host, port)


def _capture_sealed_oracle(
    runtime: PreparedCliRuntime,
    backend: CliRuntimeBackend,
) -> CliRuntimeBackend:
    _assert_tab_path_identity_closed(runtime)
    context = backend.get_context()
    snapshot = runtime.snapshot(backend=backend)
    return _SealedCliBackend(
        context=context,
        objects=snapshot.objects,
        events=snapshot.events,
    )


def _assert_tab_path_identity_closed(runtime: PreparedCliRuntime) -> None:
    if runtime.plan.operation != "tabDelimitedImport":
        return
    paths = tuple(
        str(row["path"])
        for row in runtime.plan.asset_spec["expected"]["objects"]
    )
    if len(paths) != len({path.casefold() for path in paths}):
        raise _InfrastructureFailure(
            "tab-delimited runtime requires path-unique before/post identities"
        )


def _validate_task_run(
    unit: HeavyScenarioUnit,
    *,
    task: V3TaskRun,
    task_root: Path,
    expected_turn_count: int,
) -> None:
    if task.scenario_id != unit.unit_id or task.version != unit.version:
        raise _InfrastructureFailure(
            "fresh CLI task returned another scenario/version identity"
        )
    if Path(task.task_root).resolve(strict=True) != task_root.resolve(strict=True):
        raise _InfrastructureFailure(
            "fresh CLI task evidence root is not bound to the scenario lifecycle"
        )
    terminal_indeterminate = bool(
        getattr(task, "terminal_indeterminate", False)
    )
    if terminal_indeterminate:
        if (
            not 1 <= len(task.turns) <= expected_turn_count
            or len(task.turn_grades) != len(task.turns)
            or not all(grade.passed for grade in task.turn_grades)
        ):
            raise _InfrastructureFailure(
                "terminal indeterminate CLI task has invalid completed-turn evidence"
            )
    elif (
        len(task.turns) != expected_turn_count
        or len(task.turn_grades) != expected_turn_count
    ):
        raise _InfrastructureFailure(
            "fresh CLI task did not return the exact planned turn cardinality"
        )
    if not task.thread_id:
        raise _InfrastructureFailure(
            "fresh CLI task completed without one exact thread identity"
        )
    if not task.passed and not terminal_indeterminate:
        raise _SemanticFailure(
            "fresh Codex CLI task did not pass its broker/harness gates"
        )


def _failure_status(
    exc: BaseException,
    *,
    task_root: Path,
    terminal_execute_indeterminate: bool,
) -> str:
    """Separate completed semantic evidence from infrastructure failures."""

    if isinstance(exc, _IndeterminateOutcome):
        return "INDETERMINATE"
    if isinstance(exc, _SemanticFailure):
        return "INDETERMINATE" if terminal_execute_indeterminate else "FAIL"
    if isinstance(
        exc,
        (
            _InfrastructureFailure,
            CodexInfrastructureError,
            CodexHarnessError,
        ),
    ):
        return "BLOCKED"
    if not isinstance(exc, Exception):
        return "BLOCKED"
    turns_root = task_root / "turns"
    if turns_root.is_dir() and any(turns_root.glob("turn-*/turn-grade.json")):
        return "FAIL"
    return "BLOCKED"


def _terminal_execute_is_indeterminate(task: V3TaskRun | None) -> bool:
    if task is None:
        return False
    records = getattr(task.broker_evidence, "records", ())
    execute_records = tuple(
        record
        for record in records
        if getattr(record, "step_name", "").endswith(".execute")
    )
    if len(execute_records) != 1:
        return False
    payload = execute_records[0].payload
    return (
        isinstance(payload, Mapping)
        and payload.get("ok") is False
        and payload.get("command") == "execute"
        and payload.get("status") == "indeterminate"
        and payload.get("state") == "indeterminate"
        and payload.get("automatic_retry") is False
    )


def _build_dispatch_evidence(
    runtime: PreparedCliRuntime,
    *,
    task: V3TaskRun,
    business: CliPhaseResult,
) -> CliDispatchEvidence:
    rows = _read_dispatch_evidence(
        Path(task.broker_evidence.evidence_directory).resolve(strict=True),
        expected_version=runtime.plan.version,
        expected_primary_api=runtime.plan.scenario.api,
        expected_primary_count=runtime.plan.scenario.primary_dispatch.count,
        expected_support_count=len(task.turns),
    )
    target = tuple(row for row in rows if row.get("api") == runtime.plan.scenario.api)
    execute_record = next(
        (
            record
            for record in task.broker_evidence.records
            if record.step_name and record.step_name.endswith(".execute")
        ),
        None,
    )
    verify_record = next(
        (
            record
            for record in task.broker_evidence.records
            if record.step_name and record.step_name.endswith(".verify")
        ),
        None,
    )
    execute_payload = execute_record.payload if execute_record is not None else None
    verify_payload = verify_record.payload if verify_record is not None else None
    row = target[0] if len(target) == 1 else None
    row_ok = isinstance(row, Mapping) and row.get("ok") is True
    disconnect_may_occur = runtime.plan.business_disconnect_may_occur
    natural_disconnect = bool(
        disconnect_may_occur
        and business.evidence.natural_exit_before_shutdown
        and not business.evidence.runner_shutdown_requested
    )
    after_dispatch = bool(
        natural_disconnect
        and len(target) == 1
        and execute_record is not None
        and execute_record.succeeded
    )
    verify_state = None
    if isinstance(verify_payload, Mapping):
        verify_state = str(verify_payload.get("state") or verify_payload.get("status") or "") or None
    stdout = business.stdout
    stderr = business.stderr
    load_issues = _load_issue_lines(stdout, stderr)
    classified_issues, issues = _classify_load_issues(
        version=runtime.plan.version,
        api=runtime.plan.scenario.api,
        operation=runtime.plan.operation,
        process_result=_process_result(row),
        lines=load_issues,
    )
    if business.log_overflow:
        issues.append("WwiseConsole process log exceeded the runner evidence ceiling")
    return CliDispatchEvidence(
        api=runtime.plan.scenario.api,
        primary_dispatch_count=len(target),
        dispatch_started=bool(target),
        dispatch_completed=bool(row_ok and execute_record is not None and execute_record.succeeded),
        gateway_verify_state=(
            verify_state
            or (
                str(execute_payload.get("state") or execute_payload.get("status") or "")
                if isinstance(execute_payload, Mapping)
                else None
            )
        ),
        process_result=_process_result(row),
        connection_lost=natural_disconnect,
        connection_lost_after_dispatch=after_dispatch,
        stdout=stdout,
        stderr=stderr,
        classified_load_issues=classified_issues,
        unclassified_load_issues=tuple(issues),
    )


def _read_dispatch_evidence(
    directory: Path,
    *,
    expected_version: str,
    expected_primary_api: str,
    expected_primary_count: int,
    expected_support_count: int,
) -> tuple[Mapping[str, Any], ...]:
    if expected_version != _SUPPORTED_VERSION:
        raise _SemanticFailure(
            "dispatcher evidence contract is pinned to Wwise 2022.1"
        )
    if expected_primary_api not in HEAVY_CLI_RUNNER_APIS:
        raise _SemanticFailure(
            f"dispatcher evidence contract does not own {expected_primary_api}"
        )
    if expected_primary_count != 1 or expected_support_count != 2:
        raise _SemanticFailure(
            "reviewed CLI dispatcher evidence requires two session-context rows "
            "and one primary row"
        )

    rows: list[Mapping[str, Any]] = []
    total_bytes = 0
    paths = sorted(directory.glob("*.json"))
    if len(paths) > _MAX_DISPATCH_RECORDS:
        raise _SemanticFailure("dispatcher evidence exceeded the record ceiling")
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise _SemanticFailure(f"dispatcher evidence is not a regular file: {path}")
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > _MAX_DISPATCH_BYTES:
            raise _SemanticFailure("dispatcher evidence exceeded the byte ceiling")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _SemanticFailure(
                f"dispatcher evidence is not one valid JSON record: {path}"
            ) from exc
        _validate_dispatch_success_row(
            path,
            value,
            expected_version=expected_version,
            expected_primary_api=expected_primary_api,
        )
        rows.append(MappingProxyType(dict(value)))

    allowed_apis = {_DISPATCH_SUPPORT_API, expected_primary_api}
    actual_apis = {row["api"] for row in rows}
    if actual_apis - allowed_apis:
        raise _SemanticFailure(
            "dispatcher evidence contains an unreviewed URI: "
            + ", ".join(sorted(actual_apis - allowed_apis))
        )
    primary_count = sum(row["api"] == expected_primary_api for row in rows)
    if primary_count != expected_primary_count:
        raise _SemanticFailure(
            f"primary API {expected_primary_api} must be dispatched exactly once; "
            f"found {primary_count}"
        )
    support_count = sum(row["api"] == _DISPATCH_SUPPORT_API for row in rows)
    if support_count != expected_support_count:
        raise _SemanticFailure(
            "dispatcher evidence must contain exactly two gateway-owned "
            f"session-context rows; found {support_count}"
        )
    if len(rows) != expected_primary_count + expected_support_count:
        raise _SemanticFailure(
            "dispatcher evidence row cardinality exceeds the reviewed contract"
        )
    return tuple(rows)


def _validate_dispatch_success_row(
    path: Path,
    value: Any,
    *,
    expected_version: str,
    expected_primary_api: str,
) -> None:
    if not isinstance(value, Mapping):
        raise _SemanticFailure(f"dispatcher evidence row is not an object: {path}")
    keys = frozenset(value)
    if keys != _DISPATCH_SUCCESS_KEYS:
        raise _SemanticFailure(
            f"dispatcher evidence success schema drifted at {path}; "
            f"missing={sorted(_DISPATCH_SUCCESS_KEYS - keys)}, "
            f"unknown={sorted(keys - _DISPATCH_SUCCESS_KEYS)}"
        )
    api = value["api"]
    if api not in {_DISPATCH_SUPPORT_API, expected_primary_api}:
        raise _SemanticFailure(f"dispatcher evidence contains an unreviewed URI: {api}")
    if value["version"] != expected_version:
        raise _SemanticFailure(
            f"dispatcher evidence version is not {expected_version}: {path}"
        )
    expected_category = "core" if api == _DISPATCH_SUPPORT_API else "cli"
    if (
        value["item_type"] != "function"
        or value["category"] != expected_category
        or value["risk_level"] != _DISPATCH_RISK_LEVELS[api]
        or value["dry_run"] is not False
        or value["ok"] is not True
        or value["error_code"] is not None
        or value["message"] != "ok"
        or value["evidence_path"] != str(path)
    ):
        raise _SemanticFailure(
            f"dispatcher evidence success envelope is invalid: {path}"
        )
    timeout = value["timeout"]
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
        or (api == expected_primary_api and timeout != 120.0)
    ):
        raise _SemanticFailure(f"dispatcher evidence timeout is invalid: {path}")

    result = value["result"]
    if not isinstance(result, Mapping):
        raise _SemanticFailure(f"dispatcher evidence result schema is invalid: {path}")
    if api == expected_primary_api:
        process_result = result.get("result")
        if (
            frozenset(result) != {"result"}
            or not isinstance(process_result, int)
            or isinstance(process_result, bool)
        ):
            raise _SemanticFailure(
                f"CLI dispatcher process-result schema is invalid: {path}"
            )
        return

    if (
        not all(
            isinstance(result.get(key), str) and result.get(key)
            for key in ("id", "name", "path")
        )
        or not isinstance(result.get("platforms"), list)
        or not isinstance(result.get("languages"), list)
    ):
        raise _SemanticFailure(
            f"session-context dispatcher result schema is invalid: {path}"
        )


def _process_result(row: Mapping[str, Any] | None) -> int | None:
    if not isinstance(row, Mapping):
        return None
    result = row.get("result")
    if not isinstance(result, Mapping):
        return None
    value = result.get("result")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _require_clean_phase(spec: ProcessPhaseSpec, result: CliPhaseResult) -> None:
    blockers = _phase_blockers(spec, result)
    if blockers:
        raise _InfrastructureFailure("; ".join(blockers))


def _phase_blockers(spec: ProcessPhaseSpec, result: CliPhaseResult) -> tuple[str, ...]:
    failures = list(spec.validate_evidence(result.evidence))
    if result.ready_version != _SUPPORTED_VERSION:
        failures.append(
            f"{spec.role} WwiseConsole readiness did not prove {_SUPPORTED_VERSION}"
        )
    if result.log_overflow:
        failures.append(f"{spec.role} WwiseConsole log exceeded the bounded ceiling")
    return tuple(failures)


def _allocate_distinct_ports(
    count: int,
    allocator: Callable[[str], int],
) -> tuple[int, ...]:
    result: list[int] = []
    attempts = 0
    while len(result) < count and attempts < count * 32:
        attempts += 1
        value = allocator("127.0.0.1")
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 1 <= value <= 65535
            and value not in result
        ):
            result.append(value)
    if len(result) != count:
        raise _InfrastructureFailure("could not allocate distinct CLI lifecycle ports")
    return tuple(result)


def _launch_environment(
    source: Mapping[str, str],
    *,
    owned_root: Path,
    project_path: Path,
) -> dict[str, str]:
    wine_prefix = owned_root / "wine-prefix"
    result = dict(source)
    result.update(
        {
            "WWISE_LIVE": "1",
            "WWISE_DESTRUCTIVE": "1",
            "WWISE_VERSION": _SUPPORTED_VERSION,
            "WWISE_FIXTURE_PROJECT": str(project_path),
            "WWISE_SANDBOX_ROOT": str(owned_root),
            "WINEPREFIX": str(wine_prefix),
        }
    )
    return result


def _load_issue_lines(stdout: str, stderr: str) -> tuple[str, ...]:
    if (
        len(stdout.encode("utf-8", errors="replace"))
        + len(stderr.encode("utf-8", errors="replace"))
        > MAX_LOG_BYTES
    ):
        raise _SemanticFailure(
            "WwiseConsole load-issue scan exceeded the process-log byte ceiling"
        )
    rows: list[str] = []
    seen: set[str] = set()
    for line in (stdout + "\n" + stderr).splitlines():
        text = line.strip()
        if not text or not _LOAD_ISSUE_RE.search(text) or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return tuple(rows)


def _classify_load_issues(
    *,
    version: str,
    api: str,
    operation: str,
    process_result: int | None,
    lines: tuple[str, ...],
) -> tuple[tuple[str, ...], list[str]]:
    """Classify bounded warning-only diagnostics for reviewed 2022.1 CLI rows.

    The shipped Wwise 2022.1 schema defines process result ``2`` as warnings
    only. Keep every bounded line as evidence, but classify it only when the
    exact reviewed URI/version/result triple proves that severity and every
    line is warning-only. Fatal and unresolved-reference text is independently
    rejected later by ``_dispatch_failures``.
    """

    if (
        lines
        and operation == CLI_APIS.get(api)
        and _is_reviewed_2022_warnings_only_result(
            version=version,
            api=api,
            process_result=process_result,
        )
        and all(
            _WARNING_SEVERITY_RE.search(line)
            and not _ERROR_SEVERITY_RE.search(line)
            for line in lines
        )
    ):
        return lines, []
    return (), list(lines)


def _ready_wwise_version(value: Any) -> str:
    if not isinstance(value, Mapping):
        raise _InfrastructureFailure("WwiseConsole readiness proof is not an object")
    version = value.get("version")
    if not isinstance(version, Mapping):
        raise _InfrastructureFailure("WwiseConsole readiness proof has no version object")
    year = version.get("year")
    major = version.get("major")
    if (
        not isinstance(year, int)
        or isinstance(year, bool)
        or not isinstance(major, int)
        or isinstance(major, bool)
    ):
        raise _InfrastructureFailure(
            "WwiseConsole readiness proof lacks integer year/major fields"
        )
    return f"{year}.{major}"


def _bounded_log(value: str) -> tuple[str, bool]:
    data = value.encode("utf-8", errors="replace")
    if len(data) <= MAX_LOG_BYTES // 2:
        return value, False
    bounded = data[: MAX_LOG_BYTES // 2].decode("utf-8", errors="replace")
    return bounded, True


def _assert_regular_project(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or path.suffix.casefold() != ".wproj":
        raise _InfrastructureFailure(f"project must be a regular .wproj file: {path}")


def _assert_tree_has_no_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise _InfrastructureFailure(f"project tree contains a symlink: {path}")


def _require_natural_intro(text: str, *, endpoint: str, version: str) -> None:
    folded = text.casefold()
    required = {
        "skill": "waapi-skill" in folded,
        "endpoint": endpoint.casefold() in folded,
        "version": version.casefold() in folded,
        "policy": "ask_before_changes" in folded,
        "mode_read_only": "read_only" in folded,
        "mode_allow_changes": "allow_changes" in folded,
    }
    missing = [key for key, passed in required.items() if not passed]
    if missing:
        raise _SemanticFailure(
            "first Skill-backed response lacks session context: " + ", ".join(missing)
        )


def _single_exact_object_lookup(uri: str, args: Mapping[str, Any]) -> bool:
    if uri != "ak.wwise.core.object.get" or set(args) != {"from"}:
        return False
    source = args.get("from")
    if not isinstance(source, Mapping) or set(source) not in ({"id"}, {"path"}):
        return False
    values = source.get("id", source.get("path"))
    return (
        isinstance(values, list)
        and len(values) == 1
        and isinstance(values[0], str)
        and bool(values[0])
    )


def _known_exact_object_absence(exc: Exception) -> bool:
    error_uri = getattr(exc, "uri", None)
    if error_uri == "ak.wwise.query.unknown_object":
        return True
    if error_uri != "ak.wwise.query.invalid_query":
        return False
    value = getattr(exc, "kwargs", None)
    return isinstance(value, Mapping) and "object not found" in str(value.get("message") or "").casefold()


def _resolved(value: str | os.PathLike[str] | None) -> Path:
    if value is None:
        raise _InfrastructureFailure("phase cwd is missing")
    return Path(value).expanduser().resolve(strict=False)


def _append_reason(existing: str, value: str) -> str:
    return f"{existing}; {value}" if existing else value


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _json_value(asdict(value))
    return repr(value)


def _oracle_evidence(
    *,
    scenario: OnlineScenario,
    version: str,
    business_oracle_plan_sha256: str,
    verification: Any,
) -> dict[str, Any]:
    """Bind one bounded CLI oracle to the exact scenario/version lane."""

    return {
        "contract": "waapi-skill.heavy-oracle/v2",
        "scenario_id": scenario.id,
        "version": version,
        "api": scenario.api,
        "runner": "cli",
        "business_oracle_plan_sha256": business_oracle_plan_sha256,
        "verification": _json_value(verification),
    }


def _write_common_business_oracle_plan(
    *,
    scenario: OnlineScenario,
    version: str,
    scenario_root: Path,
    protocol: Any,
    provenance: Any,
    runner: str,
    typed_sections: CliBusinessPlanSections,
) -> BusinessOraclePlanEvidence:
    """Seal the typed CLI plan before the task can create Codex."""

    if not isinstance(typed_sections, CliBusinessPlanSections):
        raise _InfrastructureFailure("CLI business plan lacks typed sections")
    if scenario.api not in CLI_APIS:
        raise _InfrastructureFailure("CLI typed business plan API is outside CLI runner")
    static = typed_sections.static_expectation
    expected_protocol_sha256 = provenance.payload["protocol"]["sha256"]
    protocol_sha256 = hashlib.sha256(
        json.dumps(
            serialize_protocol(protocol),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if (
        static["family"] != "cli"
        or static["scenario_id"] != scenario.id
        or static["version"] != version
        or static["api"] != scenario.api
        or static["protocol_sha256"] != expected_protocol_sha256
        or static["protocol_sha256"] != protocol_sha256
    ):
        raise _InfrastructureFailure(
            "typed CLI business plan is not bound to runner scenario/protocol"
        )
    writer_kwargs = typed_sections.writer_kwargs()
    return write_business_oracle_plan(
        scenario_id=scenario.id,
        version=version,
        api=scenario.api,
        runner=runner,
        family=business_family_for_api(scenario.api),
        scenario_root=scenario_root,
        fixture_spec=writer_kwargs["fixture_spec"],
        protocol_sha256=expected_protocol_sha256,
        provenance_sha256=provenance.sha256,
        primary_dispatch_count=scenario.primary_dispatch.count,
        payload_bindings=writer_kwargs["payload_bindings"],
        assertion_ids=writer_kwargs["assertion_ids"],
        static_expectation=writer_kwargs["static_expectation"],
        live_binding=writer_kwargs["live_binding"],
        delta_rules=writer_kwargs["delta_rules"],
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_utf8_text_bytes(
        path,
        json.dumps(
            _json_value(payload),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
    )


__all__ = [
    "HEAVY_CLI_RUN_CONTRACT",
    "HEAVY_CLI_REVIEWED_CASE_APIS",
    "HEAVY_CLI_RUNNER_APIS",
    "CliBackendSession",
    "CliPhaseResult",
    "CliPhaseSession",
    "HeavyCliRunOutcome",
    "HeavyCliRunnerDependencies",
    "HeavyCliRunnerError",
    "HeavyCliRunnerOptions",
    "OwnedDirectCliCall",
    "run_heavy_cli_unit",
]
