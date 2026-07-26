"""Isolated Codex CLI harness for WAAPI skill semantic evaluations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import tempfile
import time
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


DEFAULT_CODEX_BINARY = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
DEFAULT_AUTH_JSON = Path.home() / ".codex" / "auth.json"
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_SERVICE_TIER = "priority"
DEFAULT_TIMEOUT_SECONDS = 180.0
PROMPT_AUDIT_TIMEOUT_SECONDS = 30.0
PROMPT_AUDIT_MAX_ATTEMPTS = 2
MEMORY_MARKERS = (
    "MEMORY_SUMMARY",
    "## Memory",
    "<oai-mem-citation>",
    "/.codex/memories",
    "\\.codex\\memories",
)
SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyw",
        ".js",
        ".ts",
        ".sh",
        ".command",
        ".rb",
        ".ps1",
        ".lua",
        ".pl",
        ".php",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".swift",
        ".go",
        ".rs",
    }
)
GATEWAY_RESULT_CONTRACT = "waapi-skill.gateway-result/v1"
SUPPORTED_WWISE_VERSIONS = frozenset({"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"})
GATEWAY_SUBCOMMANDS = frozenset(
    {
        "status",
        "config-show",
        "config-set",
        "buses",
        "selected",
        "query-object",
        "metadata",
        "wait-topic",
        "capabilities",
        "describe",
        "operations",
        "operation-schema",
        "transaction-show",
        "confirm",
        "reject",
        "preview",
        "execute",
        "verify",
        "call",
    }
)
_PROTECTED_ENV_EXACT = frozenset({"HOME", "CODEX_HOME"})
_BROKER_MODEL_ENV_NAMES = frozenset(
    {
        "BASH_ENV",
        "WAAPI_CODEX_GATEWAY_BROKER_ENDPOINT",
        "WAAPI_CODEX_GATEWAY_BROKER_TOKEN",
        "WAAPI_CODEX_GATEWAY_BROKER_TRANSPORT",
        "WAAPI_CODEX_GATEWAY_REQUIRED",
    }
)
_BROKER_MODEL_OVERLAY_NAMES = _BROKER_MODEL_ENV_NAMES | {"PATH"}
_SHELL_ASSIGNMENT_RE = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)", re.DOTALL)
_RUNNER_VERSION_SELECTORS = frozenset({"--version", "--wwise-version"})
_SKILL_LINE_RE = re.compile(
    r"(?m)^\s*-\s+(?P<name>[A-Za-z0-9_.:-]+)\s*:\s*.*?"
    r"\((?:file|source|locator)\s*:\s*(?P<locator>[^)\n]+)\)\s*$"
)
_LEGACY_WORKSPACE_SKILL_RE = re.compile(r"(?im)^\s*workspace\s+skill\s*:\s*(?P<name>[A-Za-z0-9_.:-]+)\s*$")
_CODEX_INFRASTRUCTURE_ERROR_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "quota_or_rate_limit",
        (
            "usage limit",
            "rate limit",
            "rate_limit",
            "too many requests",
            "insufficient_quota",
            "quota exceeded",
            "purchase more credits",
        ),
    ),
    (
        "authentication",
        (
            "authentication",
            "authentication failed",
            "authentication error",
            "not authenticated",
            "unauthorized",
            "invalid api key",
            "invalid_grant",
            "login required",
            "missing bearer",
            "not logged in",
            "please log in",
            "token expired",
            "status 401",
            "status 403",
            "http 401",
            "http 403",
        ),
    ),
    (
        "service_unavailable",
        (
            "service unavailable",
            "temporarily unavailable",
            "internal server error",
            "server is overloaded",
            "server overloaded",
            "failed to connect",
            "connection error",
            "connection closed",
            "connection refused",
            "error sending request",
            "network error",
            "request timed out",
            "stream disconnected",
            "upstream error",
            "gateway timeout",
            "status 502",
            "status 503",
            "status 504",
            "http 502",
            "http 503",
            "http 504",
        ),
    ),
)


class CodexHarnessError(RuntimeError):
    """Raised when a Codex semantic run cannot satisfy the isolation contract."""


@dataclass(frozen=True, slots=True)
class CodexGatewayErrorExpectation:
    """One explicitly expected, structured gateway error result.

    Exit status 2 remains a failed shell command.  The harness treats it as an
    accepted packaged-gateway result only when the caller names both the exact
    gateway command and the exact top-level ``error_code`` expected from a
    ``gateway-result/v1`` payload whose ``ok`` value is ``false``.
    """

    command: str
    error_code: str

    def __post_init__(self) -> None:
        if self.command not in GATEWAY_SUBCOMMANDS:
            raise ValueError(
                "CodexGatewayErrorExpectation.command must be a known gateway subcommand"
            )
        if not self.error_code or not self.error_code.strip():
            raise ValueError("CodexGatewayErrorExpectation.error_code must be non-empty")


@dataclass(frozen=True, slots=True)
class CodexPromptAudit:
    item_count: int
    prompt_sha256: str
    has_memory: bool
    has_target_skill: bool
    has_user_agent_skills: bool
    has_codex_system_skills: bool
    skill_inventory: tuple[tuple[str, str], ...] = ()
    system_skills: tuple[tuple[str, str], ...] = ()
    unexpected_skills: tuple[tuple[str, str], ...] = ()
    target_skill_count: int = 0
    target_skill_locator_matches: bool = False

    @property
    def passed(self) -> bool:
        return (
            self.has_target_skill
            and self.target_skill_count == 1
            and self.target_skill_locator_matches
            and not self.has_memory
            and not self.unexpected_skills
        )


@dataclass(frozen=True, slots=True)
class CodexEnvironmentAudit:
    home: str
    codex_home: str
    home_entries: tuple[str, ...]
    codex_home_entries: tuple[str, ...]
    auth_is_symlink: bool
    auth_target: str
    expected_auth_target: str
    broker_environment_keys: tuple[str, ...] = ()
    unexpected_sensitive_environment_keys: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return (
            not self.home_entries
            and self.codex_home_entries == ("auth.json",)
            and self.auth_is_symlink
            and self.auth_target == self.expected_auth_target
            and not self.unexpected_sensitive_environment_keys
            and self.broker_environment_keys
            in ((), tuple(sorted(_BROKER_MODEL_ENV_NAMES)))
        )


@dataclass(frozen=True, slots=True)
class CodexIsolationAudit:
    prompt_audit_environment: CodexEnvironmentAudit
    execution_environment: CodexEnvironmentAudit

    @property
    def passed(self) -> bool:
        audit = self.prompt_audit_environment
        execution = self.execution_environment
        return (
            audit.passed
            and execution.passed
            and audit.home != execution.home
            and audit.codex_home != execution.codex_home
        )


@dataclass(frozen=True, slots=True)
class CodexSessionAudit:
    thread_started_count: int
    turn_started_count: int
    turn_completed_count: int
    thread_ids: tuple[str, ...]
    collab_call_count: int
    file_change_count: int
    command_started_count: int
    command_completed_count: int
    incomplete_command_count: int
    unexpected_item_types: tuple[str, ...]
    invalid_json_line_count: int

    @property
    def passed(self) -> bool:
        return (
            self.thread_started_count == 1
            and self.turn_started_count == 1
            and self.turn_completed_count == 1
            and len(self.thread_ids) == 1
            and bool(self.thread_ids[0])
            and self.collab_call_count == 0
            and self.file_change_count == 0
            and self.incomplete_command_count == 0
            and not self.unexpected_item_types
            and self.invalid_json_line_count == 0
        )


@dataclass(frozen=True, slots=True)
class CodexCommandRecord:
    command: str
    exit_code: int | None
    status: str
    aggregated_output: str
    argv: tuple[str, ...]
    has_shell_operators: bool
    parse_error: str = ""

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and self.status == "completed" and not self.parse_error


@dataclass(frozen=True, slots=True)
class CodexCommandFacts:
    commands: tuple[str, ...]
    inline_python_commands: tuple[str, ...]
    direct_waapi_client_commands: tuple[str, ...]
    write_like_commands: tuple[str, ...]
    gateway_commands: tuple[str, ...]
    discovery_commands: tuple[str, ...]
    skill_read: bool
    gateway_before_discovery: bool
    command_records: tuple[CodexCommandRecord, ...] = ()
    gateway_attempt_commands: tuple[str, ...] = ()
    gateway_subcommands: tuple[str, ...] = ()
    gateway_results: tuple[Mapping[str, Any], ...] = ()
    gateway_evidence_apis: tuple[str, ...] = ()
    allowed_read_commands: tuple[str, ...] = ()
    skill_read_files: tuple[str, ...] = ()
    unexpected_commands: tuple[str, ...] = ()
    non_gateway_unexpected_commands: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CodexRunResult:
    command: tuple[str, ...]
    exit_status: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    thread_id: str
    final_response: str
    usage: Mapping[str, int]
    event_count: int
    collab_call_count: int
    file_change_count: int
    prompt_audit: CodexPromptAudit
    isolation_audit: CodexIsolationAudit
    session_audit: CodexSessionAudit
    command_facts: CodexCommandFacts
    created_files: tuple[str, ...]
    modified_files: tuple[str, ...]
    deleted_files: tuple[str, ...]
    created_source_files: tuple[str, ...]
    modified_source_files: tuple[str, ...]
    deleted_source_files: tuple[str, ...]
    skill_tree_sha256_before: str
    skill_tree_sha256_after: str
    skill_tree_unchanged: bool

    def facts_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("stdout", None)
        payload.pop("stderr", None)
        payload["prompt_audit"]["passed"] = self.prompt_audit.passed
        payload["isolation_audit"]["passed"] = self.isolation_audit.passed
        payload["session_audit"]["passed"] = self.session_audit.passed
        return payload


@dataclass(frozen=True, slots=True)
class CodexInfrastructureFailure:
    """A terminal Codex CLI failure proven to precede every agent action."""

    category: str
    message: str
    turn_failed: bool
    timed_out: bool
    agent_item_event_count: int


class CodexInfrastructureError(CodexHarnessError):
    """Raised for CLI/service failures that are not evidence about the Skill."""

    def __init__(self, failure: CodexInfrastructureFailure, result: CodexRunResult) -> None:
        self.failure = failure
        self.result = result
        super().__init__(f"Codex CLI infrastructure failure ({failure.category}): {failure.message}")


@dataclass(frozen=True, slots=True)
class CodexHarnessConfig:
    workspace: Path
    skill_source: Path
    codex_binary: Path = DEFAULT_CODEX_BINARY
    auth_json: Path = DEFAULT_AUTH_JSON
    model: str = DEFAULT_MODEL
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    service_tier: str = DEFAULT_SERVICE_TIER
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    expected_gateway_subcommands: tuple[str, ...] = ()
    expected_wwise_version: str = ""
    sandbox_mode: str = "workspace-write"
    allow_output_write: bool = True
    network_access: bool = True
    expected_gateway_errors: tuple[CodexGatewayErrorExpectation, ...] = ()

    def __post_init__(self) -> None:
        commands = tuple(expectation.command for expectation in self.expected_gateway_errors)
        if len(commands) != len(set(commands)):
            raise ValueError("CodexHarnessConfig.expected_gateway_errors commands must be unique")
        expected = frozenset(self.expected_gateway_subcommands)
        if expected and any(command not in expected for command in commands):
            raise ValueError(
                "CodexHarnessConfig.expected_gateway_errors must name expected gateway subcommands"
            )


class CodexCliHarness:
    """Run one fresh Codex CLI process with no prior memory or user configuration."""

    def __init__(self, config: CodexHarnessConfig) -> None:
        self.config = config

    def verify(self) -> None:
        binary = self.config.codex_binary.expanduser()
        auth = self.config.auth_json.expanduser()
        workspace = self.config.workspace.expanduser().resolve(strict=True)
        skill_source = self.config.skill_source.expanduser().resolve(strict=True)
        skills_dir = workspace / ".agents" / "skills"
        skill_install = skills_dir / "waapi-skill"
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise CodexHarnessError(f"Codex binary is missing or not executable: {binary}")
        if not auth.is_file():
            raise CodexHarnessError(f"Codex auth file is missing: {auth}")
        if not skill_install.is_symlink():
            raise CodexHarnessError(f"WAAPI skill install must be a symlink: {skill_install}")
        if skill_install.resolve(strict=True) != skill_source:
            raise CodexHarnessError(
                f"WAAPI skill symlink resolves to {skill_install.resolve(strict=True)}, expected {skill_source}"
            )
        installed_skills = tuple(sorted(path.name for path in skills_dir.iterdir()))
        if installed_skills != ("waapi-skill",):
            raise CodexHarnessError(
                f"Agent workspace must install only waapi-skill; found: {', '.join(installed_skills) or '<none>'}"
            )

    def run(
        self,
        prompt: str,
        *,
        output_dir: Path,
        extra_env: Mapping[str, str] | None = None,
    ) -> CodexRunResult:
        self.verify()
        output_dir = output_dir.expanduser().resolve(strict=False)
        output_dir.mkdir(parents=True, exist_ok=True)
        before_workspace = snapshot_workspace(self.config.workspace)
        before_outputs = snapshot_workspace(output_dir)
        before_skill = snapshot_workspace(self.config.skill_source)
        skill_tree_sha256_before = snapshot_tree_hash(before_skill)

        with isolated_codex_environment(self.config.auth_json, extra_env=extra_env) as audit_env:
            prompt_environment = inspect_isolated_environment(audit_env, auth_json=self.config.auth_json)
            if not prompt_environment.passed:
                raise CodexHarnessError(f"Prompt audit environment is not pristine: {prompt_environment}")
            audit = self.audit_prompt(prompt, env=audit_env)
            if not audit.passed:
                raise CodexHarnessError(f"Codex prompt isolation audit failed: {audit}")
        if snapshot_workspace(self.config.workspace) != before_workspace:
            raise CodexHarnessError("codex debug prompt-input modified the isolated agent workspace")
        if snapshot_workspace(output_dir) != before_outputs:
            raise CodexHarnessError("codex debug prompt-input modified the evaluation output directory")
        if snapshot_tree_hash(snapshot_workspace(self.config.skill_source)) != skill_tree_sha256_before:
            raise CodexHarnessError("codex debug prompt-input modified the target Skill tree")
        with isolated_codex_environment(self.config.auth_json, extra_env=extra_env) as exec_env:
            execution_environment = inspect_isolated_environment(exec_env, auth_json=self.config.auth_json)
            if not execution_environment.passed:
                raise CodexHarnessError(f"Execution environment is not pristine: {execution_environment}")
            command = build_exec_command(self.config, prompt=prompt, writable_dir=output_dir)
            completed = run_process(command, cwd=self.config.workspace, env=exec_env, timeout=self.config.timeout_seconds)

        return _finalize_codex_run(
            config=self.config,
            command=command,
            completed=completed,
            output_dir=output_dir,
            prompt_audit=audit,
            prompt_environment=prompt_environment,
            execution_environment=execution_environment,
            before_workspace=before_workspace,
            before_outputs=before_outputs,
            skill_tree_sha256_before=skill_tree_sha256_before,
        )

    def audit_prompt(self, prompt: str, *, env: Mapping[str, str]) -> CodexPromptAudit:
        command = build_prompt_audit_command(self.config, prompt=prompt)
        completed: ProcessResult | None = None
        for attempt in range(1, PROMPT_AUDIT_MAX_ATTEMPTS + 1):
            completed = run_process(
                command,
                cwd=self.config.workspace,
                env=env,
                timeout=PROMPT_AUDIT_TIMEOUT_SECONDS,
            )
            if completed.exit_status == 0:
                break
            retryable_timeout = completed.exit_status == 124 and completed.timed_out
            if not retryable_timeout or attempt == PROMPT_AUDIT_MAX_ATTEMPTS:
                raise CodexHarnessError(
                    "codex debug prompt-input failed "
                    f"after {attempt} attempt(s) with {completed.exit_status}: "
                    f"{completed.stderr.strip()}"
                )
        assert completed is not None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CodexHarnessError("codex debug prompt-input did not return JSON") from exc
        return audit_prompt_input_payload(
            payload,
            target_skill_source=self.config.skill_source,
            system_skill_root=Path(env["CODEX_HOME"]) / "skills" / ".system",
        )


class CodexCliTask:
    """One scenario-scoped Codex thread in one disposable state directory.

    The initial turn uses a non-ephemeral ``codex exec`` so the CLI can persist
    the thread inside the task's private ``CODEX_HOME``.  Every later turn
    resumes the exact thread id emitted by that initial process.  The task is
    deliberately one-shot: leaving the context destroys both ``HOME`` and
    ``CODEX_HOME`` and the instance cannot be re-entered.
    """

    def __init__(
        self,
        config: CodexHarnessConfig,
        *,
        extra_env: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self._harness = CodexCliHarness(config)
        self._extra_env = dict(extra_env or {})
        self._exit_stack: ExitStack | None = None
        self._execution_env: dict[str, str] | None = None
        self._execution_environment: CodexEnvironmentAudit | None = None
        self._thread_id = ""
        self._turn_results: list[CodexRunResult] = []
        self._state = "new"
        self._failed = False

    @property
    def thread_id(self) -> str:
        return self._thread_id

    @property
    def turn_results(self) -> tuple[CodexRunResult, ...]:
        return tuple(self._turn_results)

    @property
    def execution_environment(self) -> CodexEnvironmentAudit:
        if self._execution_environment is None:
            raise CodexHarnessError("CodexCliTask has not entered its isolated environment")
        return self._execution_environment

    def __enter__(self) -> CodexCliTask:
        if self._state != "new":
            raise CodexHarnessError("CodexCliTask is one-shot and cannot be re-entered")
        self._harness.verify()
        stack = ExitStack()
        try:
            execution_env = stack.enter_context(
                isolated_codex_environment(self.config.auth_json, extra_env=self._extra_env)
            )
            execution_environment = inspect_isolated_environment(
                execution_env,
                auth_json=self.config.auth_json,
            )
            if not execution_environment.passed:
                raise CodexHarnessError(
                    f"Execution environment is not pristine: {execution_environment}"
                )
        except BaseException:
            stack.close()
            self._state = "closed"
            raise
        self._exit_stack = stack
        self._execution_env = execution_env
        self._execution_environment = execution_environment
        self._state = "active"
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        stack = self._exit_stack
        try:
            if stack is not None:
                stack.__exit__(exc_type, exc, traceback)
        finally:
            self._execution_env = None
            self._exit_stack = None
            self._state = "closed"

    def run_initial(self, prompt: str, *, output_dir: Path) -> CodexRunResult:
        """Start the task's only thread and capture its exact emitted id."""

        self._require_active()
        if self._turn_results or self._thread_id:
            raise CodexHarnessError("CodexCliTask initial turn has already run")
        output_dir = output_dir.expanduser().resolve(strict=False)
        command = build_task_exec_command(self.config, prompt=prompt, writable_dir=output_dir)
        result = self._record_turn(prompt, output_dir=output_dir, command=command)
        if not result.thread_id:
            self._failed = True
            raise CodexHarnessError("CodexCliTask initial turn did not emit exactly one thread id")
        self._thread_id = result.thread_id
        return result

    def run_followup(self, prompt: str, *, output_dir: Path) -> CodexRunResult:
        """Resume the task's exact initial thread for one additional turn."""

        self._require_active()
        if not self._thread_id:
            raise CodexHarnessError("CodexCliTask follow-up requires a successful initial turn")
        expected_thread_id = self._thread_id
        output_dir = output_dir.expanduser().resolve(strict=False)
        command = build_task_resume_command(
            self.config,
            thread_id=expected_thread_id,
            prompt=prompt,
            writable_dir=output_dir,
        )
        result = self._record_turn(prompt, output_dir=output_dir, command=command)
        if result.thread_id != expected_thread_id:
            self._failed = True
            raise CodexHarnessError(
                "CodexCliTask resumed thread id mismatch: "
                f"expected {expected_thread_id!r}, observed {result.thread_id!r}"
            )
        return result

    def _require_active(self) -> None:
        if self._state != "active" or self._execution_env is None:
            raise CodexHarnessError("CodexCliTask must be used inside its active context")
        if self._failed:
            raise CodexHarnessError("CodexCliTask is terminal after a harness failure")

    def _record_turn(
        self,
        prompt: str,
        *,
        output_dir: Path,
        command: Sequence[str],
    ) -> CodexRunResult:
        try:
            result = self._run_turn(prompt, output_dir=output_dir, command=command)
        except CodexInfrastructureError as exc:
            self._turn_results.append(exc.result)
            self._failed = True
            raise
        except BaseException:
            self._failed = True
            raise
        self._turn_results.append(result)
        return result

    def _run_turn(
        self,
        prompt: str,
        *,
        output_dir: Path,
        command: Sequence[str],
    ) -> CodexRunResult:
        execution_env = self._execution_env
        execution_environment = self._execution_environment
        if execution_env is None or execution_environment is None:
            raise CodexHarnessError("CodexCliTask execution environment is unavailable")

        output_dir = output_dir.expanduser().resolve(strict=False)
        output_dir.mkdir(parents=True, exist_ok=True)
        before_workspace = snapshot_workspace(self.config.workspace)
        before_outputs = snapshot_workspace(output_dir)
        before_skill = snapshot_workspace(self.config.skill_source)
        skill_tree_sha256_before = snapshot_tree_hash(before_skill)

        with isolated_codex_environment(self.config.auth_json, extra_env=self._extra_env) as audit_env:
            prompt_environment = inspect_isolated_environment(
                audit_env,
                auth_json=self.config.auth_json,
            )
            if not prompt_environment.passed:
                raise CodexHarnessError(
                    f"Prompt audit environment is not pristine: {prompt_environment}"
                )
            audit = self._harness.audit_prompt(prompt, env=audit_env)
            if not audit.passed:
                raise CodexHarnessError(f"Codex prompt isolation audit failed: {audit}")
        if snapshot_workspace(self.config.workspace) != before_workspace:
            raise CodexHarnessError("codex debug prompt-input modified the isolated agent workspace")
        if snapshot_workspace(output_dir) != before_outputs:
            raise CodexHarnessError("codex debug prompt-input modified the evaluation output directory")
        if snapshot_tree_hash(snapshot_workspace(self.config.skill_source)) != skill_tree_sha256_before:
            raise CodexHarnessError("codex debug prompt-input modified the target Skill tree")

        completed = run_process(
            command,
            cwd=self.config.workspace,
            env=execution_env,
            timeout=self.config.timeout_seconds,
        )
        return _finalize_codex_run(
            config=self.config,
            command=command,
            completed=completed,
            output_dir=output_dir,
            prompt_audit=audit,
            prompt_environment=prompt_environment,
            execution_environment=execution_environment,
            before_workspace=before_workspace,
            before_outputs=before_outputs,
            skill_tree_sha256_before=skill_tree_sha256_before,
        )


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_status: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


def _finalize_codex_run(
    *,
    config: CodexHarnessConfig,
    command: Sequence[str],
    completed: ProcessResult,
    output_dir: Path,
    prompt_audit: CodexPromptAudit,
    prompt_environment: CodexEnvironmentAudit,
    execution_environment: CodexEnvironmentAudit,
    before_workspace: Mapping[str, str],
    before_outputs: Mapping[str, str],
    skill_tree_sha256_before: str,
) -> CodexRunResult:
    """Build one immutable turn result using the shared V2/V3 audit logic."""

    isolation_audit = CodexIsolationAudit(
        prompt_audit_environment=prompt_environment,
        execution_environment=execution_environment,
    )
    after_workspace = snapshot_workspace(config.workspace)
    after_outputs = snapshot_workspace(output_dir)
    after_skill = snapshot_workspace(config.skill_source)
    skill_tree_sha256_after = snapshot_tree_hash(after_skill)
    workspace_created, workspace_modified = workspace_changes(before_workspace, after_workspace)
    output_created, output_modified = workspace_changes(before_outputs, after_outputs)
    workspace_deleted = tuple(sorted(set(before_workspace) - set(after_workspace)))
    output_deleted = tuple(sorted(set(before_outputs) - set(after_outputs)))
    created = tuple(workspace_created) + tuple(f"outputs/{path}" for path in output_created)
    modified = tuple(workspace_modified) + tuple(f"outputs/{path}" for path in output_modified)
    deleted = tuple(workspace_deleted) + tuple(f"outputs/{path}" for path in output_deleted)
    events = parse_jsonl_events(completed.stdout)
    command_records = completed_command_records(events)
    command_facts = classify_commands(
        command_records,
        skill_source=config.skill_source,
        expected_gateway_subcommands=config.expected_gateway_subcommands,
        expected_gateway_errors=config.expected_gateway_errors,
        expected_wwise_version=config.expected_wwise_version,
    )
    final_response = final_agent_message(events)
    usage = turn_usage(events)
    session_audit = audit_session_events(
        events,
        invalid_json_line_count=count_invalid_jsonl_lines(completed.stdout),
    )
    thread_ids = session_audit.thread_ids
    created_source_files = tuple(path for path in created if Path(path).suffix.lower() in SOURCE_SUFFIXES)
    modified_source_files = tuple(path for path in modified if Path(path).suffix.lower() in SOURCE_SUFFIXES)
    deleted_source_files = tuple(path for path in deleted if Path(path).suffix.lower() in SOURCE_SUFFIXES)
    result = CodexRunResult(
        command=tuple(command),
        exit_status=completed.exit_status,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=completed.duration_seconds,
        timed_out=completed.timed_out,
        thread_id=thread_ids[0] if len(thread_ids) == 1 else "",
        final_response=final_response,
        usage=usage,
        event_count=len(events),
        collab_call_count=session_audit.collab_call_count,
        file_change_count=session_audit.file_change_count,
        prompt_audit=prompt_audit,
        isolation_audit=isolation_audit,
        session_audit=session_audit,
        command_facts=command_facts,
        created_files=created,
        modified_files=modified,
        deleted_files=deleted,
        created_source_files=created_source_files,
        modified_source_files=modified_source_files,
        deleted_source_files=deleted_source_files,
        skill_tree_sha256_before=skill_tree_sha256_before,
        skill_tree_sha256_after=skill_tree_sha256_after,
        skill_tree_unchanged=skill_tree_sha256_before == skill_tree_sha256_after,
    )
    infrastructure_failure = classify_codex_infrastructure_failure(
        events,
        stderr=completed.stderr,
        timed_out=completed.timed_out,
    )
    if infrastructure_failure is not None:
        raise CodexInfrastructureError(infrastructure_failure, result)
    return result


def run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
) -> ProcessResult:
    """Run a process in its own group so timeouts also stop internal agents."""

    started = time.monotonic()
    process = subprocess.Popen(
        [str(part) for part in command],
        cwd=str(cwd),
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return ProcessResult(
            exit_status=int(process.returncode),
            stdout=stdout or "",
            stderr=stderr or "",
            duration_seconds=round(time.monotonic() - started, 6),
        )
    except subprocess.TimeoutExpired:
        try:
            stdout, stderr = terminate_and_reap_process(process)
        except BaseException:
            # If cancellation interrupts the graceful wait, finish the hard
            # cleanup but preserve and re-raise that cancellation unchanged.
            try:
                force_kill_and_reap_process(process)
            except BaseException:
                pass
            raise
        return ProcessResult(
            exit_status=124,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_seconds=round(time.monotonic() - started, 6),
            timed_out=True,
        )
    except BaseException:
        # KeyboardInterrupt and cancellation must not orphan a Codex process or
        # any command it spawned in the new session/process group.
        try:
            terminate_and_reap_process(process)
        except BaseException:
            try:
                force_kill_and_reap_process(process)
            except BaseException:
                pass
        raise


def terminate_and_reap_process(
    process: subprocess.Popen[str],
    *,
    grace_seconds: float = 5.0,
) -> tuple[str, str]:
    """Terminate a process group, wait briefly, then kill and reap if needed."""

    if process.poll() is None:
        signal_process_group(process, signal.SIGTERM)
    try:
        return process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        return force_kill_and_reap_process(process)


def force_kill_and_reap_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Best-effort hard stop followed by an unbounded pipe/process reap."""

    if process.poll() is None:
        signal_process_group(process, signal.SIGKILL)
    return process.communicate()


def signal_process_group(process: subprocess.Popen[str], requested_signal: signal.Signals) -> None:
    """Signal the isolated process group without failing on an exit race."""

    try:
        if os.name != "nt":
            os.killpg(process.pid, requested_signal)
        elif requested_signal == signal.SIGTERM:  # pragma: no cover - Windows local harness is not used
            process.terminate()
        else:  # pragma: no cover
            process.kill()
    except ProcessLookupError:
        pass


@contextmanager
def isolated_codex_environment(
    auth_json: Path,
    *,
    extra_env: Mapping[str, str] | None = None,
) -> Iterator[dict[str, str]]:
    """Create disposable HOME/CODEX_HOME directories for exactly one prompt."""

    auth = auth_json.expanduser().resolve(strict=True)
    normalized_extra_env = {str(key): str(value) for key, value in (extra_env or {}).items()}
    validate_extra_environment(normalized_extra_env)
    with tempfile.TemporaryDirectory(prefix="codex-waapi-home-") as home_text:
        with tempfile.TemporaryDirectory(prefix="codex-waapi-state-") as codex_home_text:
            codex_home = Path(codex_home_text)
            (codex_home / "auth.json").symlink_to(auth)
            env = {
                str(key): str(value)
                for key, value in os.environ.items()
                if not is_protected_environment_key(str(key))
                and not is_evaluation_sensitive_environment_key(str(key))
            }
            env.update(normalized_extra_env)
            env.update(
                {
                    "HOME": home_text,
                    "CODEX_HOME": codex_home_text,
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            yield env


def validate_extra_environment(extra_env: Mapping[str, str]) -> None:
    """Reject state escapes and permit only the runner-owned broker overlay.

    Ambient Wwise/WAAPI controls are always removed.  A trusted runner may add
    the complete broker connection overlay, but it may not expose live Wwise
    connection details, transaction state, or evidence directories directly to
    the evaluated model.
    """

    protected = sorted(key for key in extra_env if is_protected_environment_key(key))
    if protected:
        raise CodexHarnessError(
            "extra_env may not override isolated HOME/CODEX/XDG state: " + ", ".join(protected)
        )

    forbidden_sensitive = sorted(
        key
        for key in extra_env
        if is_evaluation_sensitive_environment_key(key) and key not in _BROKER_MODEL_ENV_NAMES
    )
    if forbidden_sensitive:
        raise CodexHarnessError(
            "extra_env may not expose Wwise/WAAPI state to evaluated Codex: "
            + ", ".join(forbidden_sensitive)
        )

    broker_names = _BROKER_MODEL_ENV_NAMES.intersection(extra_env)
    if not broker_names:
        return
    missing = sorted(_BROKER_MODEL_OVERLAY_NAMES.difference(extra_env))
    if missing:
        raise CodexHarnessError(
            "broker extra_env must provide the complete controlled overlay; missing: "
            + ", ".join(missing)
        )
    validate_broker_model_overlay(extra_env)


def validate_broker_model_overlay(extra_env: Mapping[str, str]) -> None:
    """Validate the small environment shape emitted by CodexGatewayBroker."""

    if extra_env["WAAPI_CODEX_GATEWAY_REQUIRED"] != "1":
        raise CodexHarnessError("broker extra_env must require the packaged gateway")

    transport = extra_env["WAAPI_CODEX_GATEWAY_BROKER_TRANSPORT"]
    endpoint = extra_env["WAAPI_CODEX_GATEWAY_BROKER_ENDPOINT"]
    if transport == "tcp":
        host, separator, port_text = endpoint.rpartition(":")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise CodexHarnessError("broker TCP endpoint must use an integer port") from exc
        if separator != ":" or host != "127.0.0.1" or not 1 <= port <= 65535:
            raise CodexHarnessError("broker TCP endpoint must be loopback 127.0.0.1:<port>")
    elif transport == "unix":
        endpoint_path = Path(endpoint)
        if not endpoint_path.is_absolute():
            raise CodexHarnessError("broker Unix endpoint must be an absolute path")
        try:
            endpoint_stat = endpoint_path.stat()
        except OSError as exc:
            raise CodexHarnessError("broker Unix endpoint must exist") from exc
        if not stat.S_ISSOCK(endpoint_stat.st_mode):
            raise CodexHarnessError("broker Unix endpoint must be a socket")
    else:
        raise CodexHarnessError("broker transport must be tcp or unix")

    token = extra_env["WAAPI_CODEX_GATEWAY_BROKER_TOKEN"]
    if len(token) < 32 or any(character.isspace() for character in token):
        raise CodexHarnessError("broker token must be a non-empty high-entropy value")

    bash_env = Path(extra_env["BASH_ENV"])
    if not bash_env.is_absolute() or bash_env.is_symlink():
        raise CodexHarnessError("broker BASH_ENV must be an absolute, non-symlink file")
    try:
        bash_env_stat = bash_env.stat()
    except OSError as exc:
        raise CodexHarnessError("broker BASH_ENV must exist") from exc
    if not stat.S_ISREG(bash_env_stat.st_mode) or stat.S_IMODE(bash_env_stat.st_mode) != stat.S_IRUSR:
        raise CodexHarnessError("broker BASH_ENV must be a private read-only file")
    if hasattr(os, "getuid") and bash_env_stat.st_uid != os.getuid():
        raise CodexHarnessError("broker BASH_ENV must be owned by the current user")

    path_entries = extra_env["PATH"].split(os.pathsep)
    if not path_entries or not path_entries[0]:
        raise CodexHarnessError("broker PATH must begin with the shim directory")
    try:
        shim_directory = Path(path_entries[0]).resolve(strict=True)
        bash_env_parent = bash_env.parent.resolve(strict=True)
    except OSError as exc:
        raise CodexHarnessError("broker shim directory must exist") from exc
    if shim_directory != bash_env_parent:
        raise CodexHarnessError("broker PATH and BASH_ENV must bind to the same shim directory")
    for executable_name in ("python", "python3"):
        executable = shim_directory / executable_name
        if executable.is_symlink() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise CodexHarnessError(f"broker shim is missing or unsafe: {executable_name}")


def is_protected_environment_key(key: str) -> bool:
    normalized = key.upper()
    return normalized in _PROTECTED_ENV_EXACT or normalized.startswith("XDG_") or normalized.startswith("CODEX_")


def is_evaluation_sensitive_environment_key(key: str) -> bool:
    """Return whether a variable can reveal or control the live WAAPI test."""

    normalized = key.upper()
    return normalized == "BASH_ENV" or normalized.startswith(("WWISE_", "WAAPI_"))


def inspect_isolated_environment(env: Mapping[str, str], *, auth_json: Path) -> CodexEnvironmentAudit:
    home = Path(env["HOME"]).expanduser().resolve(strict=True)
    codex_home = Path(env["CODEX_HOME"]).expanduser().resolve(strict=True)
    auth_link = codex_home / "auth.json"
    expected_auth = auth_json.expanduser().resolve(strict=True)
    sensitive_environment_keys = {
        str(key) for key in env if is_evaluation_sensitive_environment_key(str(key))
    }
    return CodexEnvironmentAudit(
        home=str(home),
        codex_home=str(codex_home),
        home_entries=tuple(sorted(path.name for path in home.iterdir())),
        codex_home_entries=tuple(sorted(path.name for path in codex_home.iterdir())),
        auth_is_symlink=auth_link.is_symlink(),
        auth_target=str(auth_link.resolve(strict=True)) if auth_link.exists() else "",
        expected_auth_target=str(expected_auth),
        broker_environment_keys=tuple(sorted(sensitive_environment_keys & _BROKER_MODEL_ENV_NAMES)),
        unexpected_sensitive_environment_keys=tuple(
            sorted(sensitive_environment_keys - _BROKER_MODEL_ENV_NAMES)
        ),
    )


def build_prompt_audit_command(config: CodexHarnessConfig, *, prompt: str) -> list[str]:
    return [
        str(config.codex_binary),
        "--disable",
        "memories",
        "-c",
        f'model="{config.model}"',
        "-c",
        f'model_reasoning_effort="{config.reasoning_effort}"',
        "debug",
        "prompt-input",
        prompt,
    ]


def build_exec_command(config: CodexHarnessConfig, *, prompt: str, writable_dir: Path) -> list[str]:
    """Build the historical V2 one-process, ephemeral execution command."""

    command = _build_exec_prefix(config, writable_dir=writable_dir, ephemeral=True)
    command.append(prompt)
    return command


def build_task_exec_command(
    config: CodexHarnessConfig,
    *,
    prompt: str,
    writable_dir: Path,
) -> list[str]:
    """Build the non-ephemeral initial turn for a scenario-scoped task."""

    command = _build_exec_prefix(config, writable_dir=writable_dir, ephemeral=False)
    command.append(prompt)
    return command


def build_task_resume_command(
    config: CodexHarnessConfig,
    *,
    thread_id: str,
    prompt: str,
    writable_dir: Path,
) -> list[str]:
    """Build an exact-id resume turn; implicit ``--last`` is never allowed."""

    if not thread_id or not thread_id.strip() or thread_id == "--last":
        raise CodexHarnessError("scenario task resume requires an explicit thread id")
    command = _build_exec_prefix(config, writable_dir=writable_dir, ephemeral=False)
    command.extend(("resume", thread_id, prompt))
    return command


def _build_exec_prefix(
    config: CodexHarnessConfig,
    *,
    writable_dir: Path,
    ephemeral: bool,
) -> list[str]:
    if config.sandbox_mode not in {"read-only", "workspace-write"}:
        raise CodexHarnessError(f"unsupported semantic sandbox mode: {config.sandbox_mode}")
    command = [
        str(config.codex_binary),
        "exec",
    ]
    if ephemeral:
        command.append("--ephemeral")
    command.extend(
        [
            "--model",
            config.model,
            "-c",
            f'model_reasoning_effort="{config.reasoning_effort}"',
            "-c",
            f'service_tier="{config.service_tier}"',
            "-c",
            'approval_policy="never"',
            "-c",
            f"sandbox_workspace_write.network_access={'true' if config.network_access else 'false'}",
            "--disable",
            "memories",
            "--ignore-user-config",
            "--json",
            "--sandbox",
            config.sandbox_mode,
            "--skip-git-repo-check",
        ]
    )
    if config.allow_output_write:
        command.extend(("--add-dir", str(writable_dir)))
    command.extend(("-C", str(config.workspace)))
    return command


def audit_prompt_input_payload(
    payload: Any,
    *,
    target_skill_source: Path | None = None,
    system_skill_root: Path | None = None,
) -> CodexPromptAudit:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    serialized_casefold = serialized.casefold()
    entries = prompt_skill_inventory(payload)
    target_source = target_skill_source.expanduser().resolve(strict=False) if target_skill_source else None
    system_skills: list[tuple[str, str]] = []
    target_entries: list[tuple[str, str]] = []
    unexpected: list[tuple[str, str]] = []
    for name, locator in entries:
        if is_codex_system_skill(locator, system_skill_root=system_skill_root):
            system_skills.append((name, locator))
            continue
        locator_matches = target_source is None or skill_locator_resolves_to(locator, target_source)
        if name == "waapi-skill" and locator_matches:
            target_entries.append((name, locator))
        else:
            unexpected.append((name, locator))
    target_locator_matches = len(target_entries) == 1
    return CodexPromptAudit(
        item_count=len(payload) if isinstance(payload, list) else 0,
        prompt_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        has_memory=any(marker.casefold() in serialized_casefold for marker in MEMORY_MARKERS),
        has_target_skill=bool(target_entries),
        has_user_agent_skills=any("/.agents/skills/" in locator.replace("\\", "/") for _, locator in unexpected),
        has_codex_system_skills=bool(system_skills),
        skill_inventory=entries,
        system_skills=tuple(system_skills),
        unexpected_skills=tuple(unexpected),
        target_skill_count=len(target_entries),
        target_skill_locator_matches=target_locator_matches,
    )


def prompt_skill_inventory(payload: Any) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = []
    for text in prompt_instruction_texts(payload):
        for match in _SKILL_LINE_RE.finditer(text):
            entries.append((match.group("name"), clean_skill_locator(match.group("locator"))))
        for match in _LEGACY_WORKSPACE_SKILL_RE.finditer(text):
            entries.append((match.group("name"), ""))
    # Structured inventories are evidence only when Codex placed them in an
    # instruction role.  A user message must never be able to self-attest that
    # the target Skill was injected.
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("role") or "").lower() not in {"system", "developer"}:
            continue
        entries.extend(structured_skill_entries(item))
    return tuple(entries)


def prompt_instruction_texts(payload: Any) -> tuple[str, ...]:
    texts: list[str] = []
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").lower()
        if role not in {"system", "developer"}:
            continue
        texts.extend(nested_text_values(item.get("content")))
    return tuple(texts)


def nested_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        values: list[str] = []
        for key, child in value.items():
            if key in {"text", "content"}:
                values.extend(nested_text_values(child))
        return values
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = []
        for child in value:
            values.extend(nested_text_values(child))
        return values
    return []


def structured_skill_entries(value: Any) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in {"available_skills", "skills"} and isinstance(child, Sequence) and not isinstance(
                child, (str, bytes, bytearray)
            ):
                for item in child:
                    if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
                        continue
                    locator = next(
                        (
                            str(item[candidate])
                            for candidate in ("file", "path", "locator", "source")
                            if isinstance(item.get(candidate), str)
                        ),
                        "",
                    )
                    entries.append((str(item["name"]), clean_skill_locator(locator)))
            entries.extend(structured_skill_entries(child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            entries.extend(structured_skill_entries(child))
    return entries


def clean_skill_locator(locator: str) -> str:
    return locator.strip().strip("`\"'")


def is_codex_system_skill(locator: str, *, system_skill_root: Path | None = None) -> bool:
    if not locator:
        return False
    candidate = Path(locator).expanduser()
    if system_skill_root is not None:
        root = system_skill_root.expanduser().resolve(strict=False)
        try:
            relative = candidate.resolve(strict=False).relative_to(root)
        except (OSError, ValueError):
            return False
        return len(relative.parts) >= 2 and relative.name.lower() == "skill.md"
    normalized = locator.replace("\\", "/")
    return "/.codex/skills/.system/" in normalized


def skill_locator_resolves_to(locator: str, target_skill_source: Path) -> bool:
    if not locator:
        return False
    candidate = Path(locator).expanduser()
    if candidate.name.lower() == "skill.md":
        candidate = candidate.parent
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        resolved = candidate.resolve(strict=False)
    return resolved == target_skill_source.expanduser().resolve(strict=False)


def parse_jsonl_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.lstrip().startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def count_invalid_jsonl_lines(text: str) -> int:
    invalid = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid += 1
            continue
        if not isinstance(payload, Mapping):
            invalid += 1
    return invalid


def classify_codex_infrastructure_failure(
    events: Sequence[Mapping[str, Any]],
    *,
    stderr: str = "",
    timed_out: bool = False,
) -> CodexInfrastructureFailure | None:
    """Classify only failures that occurred before Codex emitted an agent item.

    A service-looking message after a command, file change, collaboration call,
    or agent message is deliberately left to normal semantic grading.  Once the
    model has acted, the run can contain real Skill behavior and must not be
    erased by a broad infrastructure-error heuristic.
    """

    agent_item_event_count = sum(
        event.get("type") in {"item.started", "item.completed"}
        and isinstance(event.get("item"), Mapping)
        for event in events
    )
    if agent_item_event_count:
        return None

    turn_failed = any(event.get("type") == "turn.failed" for event in events)
    messages = list(codex_error_messages(events))
    if stderr.strip():
        messages.append(stderr.strip())
    combined = "\n".join(messages).casefold()
    for category, markers in _CODEX_INFRASTRUCTURE_ERROR_MARKERS:
        if any(marker in combined for marker in markers):
            return CodexInfrastructureFailure(
                category=category,
                message=first_nonempty(messages, default=category),
                turn_failed=turn_failed,
                timed_out=timed_out,
                agent_item_event_count=agent_item_event_count,
            )

    if timed_out:
        return CodexInfrastructureFailure(
            category="timeout_before_agent_action",
            message=first_nonempty(messages, default="Codex CLI timed out before any agent action"),
            turn_failed=turn_failed,
            timed_out=True,
            agent_item_event_count=agent_item_event_count,
        )
    if turn_failed:
        return CodexInfrastructureFailure(
            category="turn_failed_before_agent_action",
            message=first_nonempty(messages, default="Codex turn failed before any agent action"),
            turn_failed=True,
            timed_out=False,
            agent_item_event_count=agent_item_event_count,
        )
    return None


def codex_error_messages(events: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Extract ordered, de-duplicated CLI error messages from JSONL events."""

    messages: list[str] = []
    for event in events:
        if event.get("type") not in {"error", "turn.failed"}:
            continue
        candidates = (event.get("message"), event.get("error"))
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                candidate = candidate.get("message")
            if isinstance(candidate, str) and candidate.strip() and candidate.strip() not in messages:
                messages.append(candidate.strip())
    return tuple(messages)


def first_nonempty(values: Sequence[str], *, default: str) -> str:
    return next((value for value in values if value.strip()), default)


def audit_session_events(
    events: Sequence[Mapping[str, Any]],
    *,
    invalid_json_line_count: int = 0,
) -> CodexSessionAudit:
    thread_ids = tuple(
        str(event.get("thread_id") or "")
        for event in events
        if event.get("type") == "thread.started"
    )
    collab_calls = collab_call_count(events)
    command_started, started_anonymous = item_ids_for_phase(events, "command_execution", "item.started")
    command_completed, completed_anonymous = item_ids_for_phase(events, "command_execution", "item.completed")
    incomplete = len(command_started ^ command_completed) + started_anonymous + completed_anonymous
    observed_item_types = {
        str(item.get("type"))
        for event in events
        if event.get("type") in {"item.started", "item.completed"}
        and isinstance((item := event.get("item")), Mapping)
        and isinstance(item.get("type"), str)
    }
    unexpected_item_types = tuple(sorted(observed_item_types - {"agent_message", "command_execution"}))
    return CodexSessionAudit(
        thread_started_count=sum(event.get("type") == "thread.started" for event in events),
        turn_started_count=sum(event.get("type") == "turn.started" for event in events),
        turn_completed_count=sum(event.get("type") == "turn.completed" for event in events),
        thread_ids=thread_ids,
        collab_call_count=collab_calls,
        file_change_count=item_attempt_count(events, "file_change"),
        command_started_count=len(command_started) + started_anonymous,
        command_completed_count=len(command_completed) + completed_anonymous,
        incomplete_command_count=incomplete,
        unexpected_item_types=unexpected_item_types,
        invalid_json_line_count=invalid_json_line_count,
    )


def item_ids_for_phase(
    events: Sequence[Mapping[str, Any]],
    item_type: str,
    event_type: str,
) -> tuple[set[str], int]:
    item_ids: set[str] = set()
    anonymous = 0
    for event in events:
        item = event.get("item")
        if event.get("type") != event_type or not isinstance(item, Mapping) or item.get("type") != item_type:
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            item_ids.add(item_id)
        else:
            anonymous += 1
    return item_ids, anonymous


def collab_call_count(events: Sequence[Mapping[str, Any]]) -> int:
    """Count attempted collab calls once, including calls that never completed."""

    item_ids: set[str] = set()
    anonymous = 0
    for event in events:
        item = event.get("item")
        if event.get("type") not in {"item.started", "item.completed"} or not isinstance(item, Mapping):
            continue
        if item.get("type") != "collab_tool_call":
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            item_ids.add(item_id)
        else:
            anonymous += 1
    return len(item_ids) + anonymous


def item_attempt_count(events: Sequence[Mapping[str, Any]], item_type: str) -> int:
    """Count one attempted item once even when JSONL contains start and completion events."""

    item_ids: set[str] = set()
    anonymous = 0
    for event in events:
        item = event.get("item")
        if event.get("type") not in {"item.started", "item.completed"} or not isinstance(item, Mapping):
            continue
        if item.get("type") != item_type:
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            item_ids.add(item_id)
        else:
            anonymous += 1
    return len(item_ids) + anonymous


def completed_commands(events: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(record.command for record in completed_command_records(events))


def completed_command_records(events: Sequence[Mapping[str, Any]]) -> tuple[CodexCommandRecord, ...]:
    records: list[CodexCommandRecord] = []
    for event in events:
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, Mapping):
            continue
        if item.get("type") == "command_execution" and isinstance(item.get("command"), str):
            command = str(item["command"])
            argv, has_operators, parse_error = parse_command_argv(command)
            raw_exit = item.get("exit_code")
            records.append(
                CodexCommandRecord(
                    command=command,
                    exit_code=int(raw_exit) if isinstance(raw_exit, int) else None,
                    status=str(item.get("status") or ""),
                    aggregated_output=str(item.get("aggregated_output") or ""),
                    argv=argv,
                    has_shell_operators=has_operators,
                    parse_error=parse_error,
                )
            )
    return tuple(records)


def parse_command_argv(command: str) -> tuple[tuple[str, ...], bool, str]:
    try:
        outer = shlex.split(command, posix=True)
    except ValueError as exc:
        return (), True, str(exc)
    if not outer:
        return (), False, "empty command"
    script = command
    shell_name = Path(outer[0]).name.lower()
    if shell_name in {"bash", "sh", "zsh", "dash", "ksh"}:
        shell_option_index = next(
            (index for index, value in enumerate(outer[1:], start=1) if value in {"-c", "-lc", "-ic"}),
            None,
        )
        if shell_option_index is None or shell_option_index + 1 >= len(outer):
            return (), True, "shell command is missing a single -c/-lc script"
        if shell_option_index + 2 != len(outer):
            return (), True, "shell command has unexpected arguments after its script"
        script = outer[shell_option_index + 1]
    has_operators = shell_script_has_operators(script)
    try:
        argv = tuple(shlex.split(script, posix=True))
    except ValueError as exc:
        return (), True, str(exc)
    return argv, has_operators, ""


def shell_script_has_operators(script: str) -> bool:
    quote = ""
    escaped = False
    index = 0
    while index < len(script):
        character = script[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote:
            if character == quote:
                quote = ""
            elif quote == '"' and (character == "`" or script[index : index + 2] == "$("):
                return True
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character in "|&;<>\n\r`" or script[index : index + 2] == "$(":
            return True
        index += 1
    return bool(quote or escaped)


def classify_commands(
    commands: Sequence[str | CodexCommandRecord],
    *,
    skill_source: Path,
    expected_gateway_subcommands: Sequence[str] = (),
    expected_gateway_errors: Sequence[CodexGatewayErrorExpectation] = (),
    expected_wwise_version: str = "",
) -> CodexCommandFacts:
    records = tuple(command_record(command) for command in commands)
    inline_python: list[str] = []
    direct_client: list[str] = []
    write_like: list[str] = []
    gateway: list[str] = []
    gateway_attempts: list[str] = []
    gateway_subcommands: list[str] = []
    gateway_results: list[Mapping[str, Any]] = []
    discovery: list[str] = []
    allowed_reads: list[str] = []
    read_files: list[str] = []
    unexpected: list[str] = []
    non_gateway_unexpected: list[str] = []
    skill_read = False
    expected = frozenset(str(value) for value in expected_gateway_subcommands)
    error_expectations: dict[str, str] = {}
    for expectation in expected_gateway_errors:
        if expectation.command in error_expectations:
            raise ValueError("expected_gateway_errors commands must be unique")
        error_expectations[expectation.command] = expectation.error_code

    for record in records:
        command = record.command
        lowered = command.lower()
        executable = Path(record.argv[0]).name.lower() if record.argv else ""
        gateway_shape = gateway_invocation(
            record,
            skill_source=skill_source,
            expected_wwise_version=expected_wwise_version,
        )
        if gateway_shape is not None:
            gateway_attempts.append(command)
        gateway_payload = successful_gateway_payload(
            record,
            skill_source=skill_source,
            expected_gateway_subcommands=expected,
            expected_wwise_version=expected_wwise_version,
        )
        if gateway_payload is None and gateway_shape is not None and (not expected or gateway_shape in expected):
            expected_error_code = error_expectations.get(gateway_shape)
            if expected_error_code is not None:
                gateway_payload = expected_gateway_error_payload(
                    record,
                    skill_source=skill_source,
                    expected_subcommand=gateway_shape,
                    expected_error_code=expected_error_code,
                    expected_wwise_version=expected_wwise_version,
                )
        is_gateway = gateway_payload is not None
        if is_gateway:
            gateway.append(command)
            gateway_results.append(gateway_payload)
            gateway_subcommands.append(str(gateway_payload.get("command") or gateway_shape or ""))

        is_python = bool(re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable))
        is_packaged_runner_attempt = packaged_runner_attempt(
            record,
            skill_source=skill_source,
        )
        if is_python and not is_gateway and not is_packaged_runner_attempt:
            inline_python.append(command)
        allowed_read = allowed_skill_read(record, skill_source=skill_source)
        if direct_waapi_command(record):
            direct_client.append(command)
        if write_like_command(record) and not allowed_read:
            write_like.append(command)
        if discovery_command(record):
            discovery.append(command)

        if allowed_read:
            allowed_reads.append(command)
            read_files.append(allowed_read)
            if allowed_read == "SKILL.md":
                skill_read = True
        if not is_gateway and not allowed_read:
            unexpected.append(command)
            if gateway_shape is None:
                non_gateway_unexpected.append(command)

    first_gateway = next((index for index, record in enumerate(records) if record.command in gateway), None)
    first_discovery = next((index for index, record in enumerate(records) if record.command in discovery), None)
    gateway_before_discovery = first_gateway is not None and (first_discovery is None or first_gateway < first_discovery)
    runtime_apis: list[str] = []
    for payload in gateway_results:
        runtime_apis.extend(gateway_runtime_apis(payload))
    return CodexCommandFacts(
        commands=tuple(record.command for record in records),
        inline_python_commands=tuple(inline_python),
        direct_waapi_client_commands=tuple(direct_client),
        write_like_commands=tuple(write_like),
        gateway_commands=tuple(gateway),
        discovery_commands=tuple(discovery),
        skill_read=skill_read,
        gateway_before_discovery=gateway_before_discovery,
        command_records=records,
        gateway_attempt_commands=tuple(gateway_attempts),
        gateway_subcommands=tuple(gateway_subcommands),
        gateway_results=tuple(gateway_results),
        gateway_evidence_apis=tuple(dict.fromkeys(runtime_apis)),
        allowed_read_commands=tuple(allowed_reads),
        skill_read_files=tuple(read_files),
        unexpected_commands=tuple(unexpected),
        non_gateway_unexpected_commands=tuple(non_gateway_unexpected),
    )


def packaged_runner_attempt(record: CodexCommandRecord, *, skill_source: Path) -> bool:
    """Identify an exact packaged runner path even when its argv is malformed.

    This is diagnostic only: malformed attempts remain unexpected commands and
    still fail broker/grader checks. They are not ad-hoc inline Python, though,
    so do not report them as code generation merely because the packaged
    invocation failed before producing a valid gateway payload.
    """

    if len(record.argv) < 2 or record.parse_error:
        return False
    executable = Path(record.argv[0]).name.lower()
    if not re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable):
        return False
    supplied_runner = Path(record.argv[1]).expanduser()
    if not supplied_runner.is_absolute():
        return False
    expected_runner = (
        skill_source.expanduser().resolve(strict=False) / "scripts" / "run.py"
    ).resolve(strict=False)
    try:
        return supplied_runner.resolve(strict=False) == expected_runner
    except OSError:
        return False


def command_record(command: str | CodexCommandRecord) -> CodexCommandRecord:
    if isinstance(command, CodexCommandRecord):
        return command
    argv, has_operators, parse_error = parse_command_argv(str(command))
    return CodexCommandRecord(
        command=str(command),
        exit_code=None,
        status="",
        aggregated_output="",
        argv=argv,
        has_shell_operators=has_operators,
        parse_error=parse_error,
    )


def normalized_gateway_command_argv(
    argv: Sequence[str],
    *,
    expected_wwise_version: str = "",
) -> tuple[str, ...]:
    """Normalize the two closed, inert model-side version spellings.

    The semantic broker owns the real runner environment, so a leading
    ``WWISE_VERSION=<session version>`` only documents model intent. Keep the
    raw command in evidence, but normalize either the direct POSIX assignment
    or the exact ``env WWISE_VERSION=...`` spelling before matching it to the
    broker record. The production runner also accepts one version selector
    immediately before the exact ``gateway.py`` target; move that selector to
    the canonical gateway-global position. Every other assignment, ``env``
    option, runner-level flag, wrong version, or wrong target remains invalid.
    """

    values = tuple(str(value) for value in argv)
    if not values:
        return values
    assignment_index = 1 if values[0] == "env" else 0
    if assignment_index >= len(values):
        return ()
    assignment = _SHELL_ASSIGNMENT_RE.fullmatch(values[assignment_index])
    if assignment is None:
        if assignment_index != 0:
            return ()
    else:
        version = assignment.group("value")
        if (
            assignment.group("name") != "WWISE_VERSION"
            or not expected_wwise_version
            or expected_wwise_version not in SUPPORTED_WWISE_VERSIONS
            or version != expected_wwise_version
        ):
            return ()
        values = values[assignment_index + 1 :]
        if values and _SHELL_ASSIGNMENT_RE.fullmatch(values[0]) is not None:
            return ()

    if len(values) < 3 or values[2] == "gateway.py":
        return values

    selector = values[2]
    if selector in _RUNNER_VERSION_SELECTORS:
        if len(values) < 6:
            return ()
        supplied_version = values[3]
        gateway_target = values[4]
        remainder = values[5:]
        canonical_selector = (selector, supplied_version)
    elif any(selector.startswith(f"{option}=") for option in _RUNNER_VERSION_SELECTORS):
        if len(values) < 5:
            return ()
        supplied_version = selector.split("=", 1)[1]
        gateway_target = values[3]
        remainder = values[4:]
        canonical_selector = (selector,)
    else:
        return values

    if (
        gateway_target != "gateway.py"
        or not expected_wwise_version
        or expected_wwise_version not in SUPPORTED_WWISE_VERSIONS
        or supplied_version != expected_wwise_version
    ):
        return ()
    return (*values[:2], "gateway.py", *canonical_selector, *remainder)


def gateway_invocation(
    record: CodexCommandRecord,
    *,
    skill_source: Path,
    expected_wwise_version: str = "",
) -> str | None:
    argv = normalized_gateway_command_argv(
        record.argv,
        expected_wwise_version=expected_wwise_version,
    )
    if record.has_shell_operators or record.parse_error or len(argv) < 4:
        return None
    executable = Path(argv[0]).name.lower()
    if not re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable):
        return None
    runner = argv[1]
    expected_runner = (skill_source.expanduser().resolve(strict=False) / "scripts" / "run.py").resolve(strict=False)
    candidate = Path(runner).expanduser()
    if not candidate.is_absolute():
        return None
    try:
        if candidate.resolve(strict=False) != expected_runner:
            return None
    except OSError:
        return None
    if argv[2] != "gateway.py":
        return None
    return gateway_subcommand(argv[3:])


def gateway_subcommand(arguments: Sequence[str]) -> str | None:
    """Return the argparse subcommand without matching option values or payload text."""

    global_options_with_values = frozenset(
        {
            "--host",
            "--port",
            "--version",
            "--wwise-version",
            "--timeout",
            "--evidence-dir",
            "--state-dir",
        }
    )
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value in GATEWAY_SUBCOMMANDS:
            return value
        if any(value.startswith(f"{option}=") for option in global_options_with_values):
            index += 1
            continue
        if value in global_options_with_values:
            if index + 1 >= len(arguments):
                return None
            index += 2
            continue
        # Unknown flags and arbitrary positional values before the subcommand
        # are not the closed gateway invocation contract.
        return None
    return None


def successful_gateway_payload(
    record: CodexCommandRecord,
    *,
    skill_source: Path,
    expected_gateway_subcommands: frozenset[str],
    expected_wwise_version: str = "",
) -> Mapping[str, Any] | None:
    subcommand = gateway_invocation(
        record,
        skill_source=skill_source,
        expected_wwise_version=expected_wwise_version,
    )
    if subcommand is None or (expected_gateway_subcommands and subcommand not in expected_gateway_subcommands):
        return None
    if not record.succeeded:
        return None
    try:
        payload = json.loads(record.aggregated_output.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    if (
        payload.get("contract") != GATEWAY_RESULT_CONTRACT
        or payload.get("command") != subcommand
        or payload.get("ok") is not True
    ):
        return None
    return dict(payload)


def expected_gateway_error_payload(
    record: CodexCommandRecord,
    *,
    skill_source: Path,
    expected_subcommand: str,
    expected_error_code: str,
    expected_wwise_version: str = "",
) -> Mapping[str, Any] | None:
    """Return one explicitly expected gateway exit-2 payload, or ``None``.

    This is intentionally separate from :attr:`CodexCommandRecord.succeeded`:
    an exit-2 process is still a failed shell command and becomes acceptable
    only under the caller's closed command/error-code expectation.
    """

    subcommand = gateway_invocation(
        record,
        skill_source=skill_source,
        expected_wwise_version=expected_wwise_version,
    )
    if (
        subcommand != expected_subcommand
        or record.exit_code != 2
        or record.status != "failed"
        or record.has_shell_operators
        or record.parse_error
    ):
        return None
    try:
        payload = json.loads(record.aggregated_output.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    if (
        payload.get("contract") != GATEWAY_RESULT_CONTRACT
        or payload.get("command") != expected_subcommand
        or payload.get("ok") is not False
        or payload.get("error_code") != expected_error_code
    ):
        return None
    return dict(payload)


def gateway_runtime_apis(payload: Any) -> tuple[str, ...]:
    apis: list[str] = []
    if isinstance(payload, Mapping):
        attempted = payload.get("api_attempted")
        if isinstance(attempted, str):
            apis.append(attempted)
        for key, child in payload.items():
            if key in {"calls", "call", "dispatch_result"} or key.endswith("_call"):
                apis.extend(call_payload_apis(child))
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for child in payload:
            apis.extend(gateway_runtime_apis(child))
    return tuple(dict.fromkeys(apis))


def call_payload_apis(value: Any) -> tuple[str, ...]:
    apis: list[str] = []
    if isinstance(value, Mapping):
        api = value.get("api")
        if isinstance(api, str):
            apis.append(api)
        for key, child in value.items():
            if key in {"calls", "call", "dispatch_result"} or key.endswith("_call"):
                apis.extend(call_payload_apis(child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            apis.extend(call_payload_apis(child))
    return tuple(dict.fromkeys(apis))


def allowed_skill_read(record: CodexCommandRecord, *, skill_source: Path) -> str | None:
    if not record.succeeded or record.parse_error or not record.argv:
        return None
    if record.has_shell_operators:
        return allowed_skill_bootstrap_read(record, skill_source=skill_source)
    executable = Path(record.argv[0]).name.lower()
    complete_skill_read = False
    if executable == "cat":
        if len(record.argv) != 2:
            return None
        path_text = record.argv[1]
        minimum_lines = None
    elif executable == "sed":
        if len(record.argv) != 4 or record.argv[1] != "-n":
            return None
        match = re.fullmatch(r"1,(\d+)p", record.argv[2])
        complete_skill_read = record.argv[2] == "1,$p"
        if match is None and not complete_skill_read:
            return None
        path_text = record.argv[3]
        minimum_lines = int(match.group(1)) if match is not None else None
    else:
        return None
    validated = validated_skill_read(path_text, record.aggregated_output, skill_source=skill_source)
    if validated is None:
        return None
    relative, content = validated
    if executable == "sed" and complete_skill_read and relative != "SKILL.md":
        return None
    if minimum_lines is not None and minimum_lines < len(content.splitlines()):
        return None
    return relative


def allowed_skill_bootstrap_read(record: CodexCommandRecord, *, skill_source: Path) -> str | None:
    """Accept only the host's length-check plus complete initial SKILL.md read.

    The model cannot follow instructions inside ``SKILL.md`` before loading it.
    Codex may therefore bootstrap that first load with ``wc -l ... && sed ...``.
    Keeping the shape exact prevents this exception from authorizing compound
    reference reads, gateway calls, arbitrary commands, or partial content.
    """

    argv = record.argv
    if (
        len(argv) != 8
        or Path(argv[0]).name.lower() != "wc"
        or argv[1] != "-l"
        or argv[3] != "&&"
        or Path(argv[4]).name.lower() != "sed"
        or argv[5] != "-n"
        or argv[2] != argv[7]
    ):
        return None
    range_match = re.fullmatch(r"1,(\d+)p", argv[6])
    output_match = re.fullmatch(r"\s*(\d+)\s+([^\n]+)\n([\s\S]*)", record.aggregated_output)
    if range_match is None or output_match is None or output_match.group(2) != argv[2]:
        return None
    content = output_match.group(3)
    validated = validated_skill_read(argv[2], content, skill_source=skill_source)
    if validated is None:
        return None
    relative, expected_content = validated
    if (
        relative != "SKILL.md"
        or int(range_match.group(1)) < len(expected_content.splitlines())
        or int(output_match.group(1)) != expected_content.count("\n")
    ):
        return None
    return relative


def validated_skill_read(
    path_text: str,
    aggregated_output: str,
    *,
    skill_source: Path,
) -> tuple[str, str] | None:
    """Prove that one approved Skill file was read completely from its absolute locator."""

    candidate = Path(path_text).expanduser()
    if not candidate.is_absolute():
        return None
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(skill_source.expanduser().resolve(strict=True)).as_posix()
    except (OSError, ValueError):
        return None
    allowed = {
        "SKILL.md",
        "references/waapi-setup.md",
        "references/waapi-query.md",
        "references/waapi-operate.md",
    }
    if relative not in allowed:
        return None
    try:
        content = resolved.read_text(encoding="utf-8")
    except OSError:
        return None
    if aggregated_output != content:
        return None
    return relative, content


def direct_waapi_command(record: CodexCommandRecord) -> bool:
    lowered = record.command.lower()
    patterns = (
        r"\bwaapiclient\b",
        r"\bfrom\s+waapi\s+import\b",
        r"\bimport\s+waapi\b",
        r"\bwwise_waapi\.dispatcher\b",
        r"\b(?:curl|wget)\b[^\n]*\bwaapi\b",
        r"\b(?:websocket|websockets|autobahn)\b",
        r"\bws://[^\s]+/waapi\b",
    )
    return any(re.search(pattern, lowered) for pattern in patterns)


def write_like_command(record: CodexCommandRecord) -> bool:
    if record.has_shell_operators:
        return True
    if not record.argv:
        return False
    executable = Path(record.argv[0]).name.lower()
    if executable in {"apply_patch", "tee", "touch", "mkdir", "cp", "mv", "rm", "install", "dd", "printf", "echo"}:
        return True
    if executable == "sed" and any(value == "-i" or value.startswith("-i") for value in record.argv[1:]):
        return True
    if executable in {"perl", "ruby"} and any(value in {"-e", "-i"} or value.startswith("-i") for value in record.argv[1:]):
        return True
    return False


def discovery_command(record: CodexCommandRecord) -> bool:
    if not record.argv:
        return False
    executable = Path(record.argv[0]).name.lower()
    if executable in {"rg", "grep", "find", "ls", "fd", "tree", "locate", "which"}:
        return True
    return executable == "command" and "-v" in record.argv[1:]


def final_agent_message(events: Sequence[Mapping[str, Any]]) -> str:
    for event in reversed(events):
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, Mapping):
            continue
        if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            return item["text"]
    return ""


def first_gateway_backed_agent_message(
    stdout: str,
    *,
    validated_gateway_commands: Sequence[str],
) -> str | None:
    """Return the first visible reply after the first validated gateway result.

    The caller supplies commands already accepted as gateway results by the
    common grader.  We intentionally inspect only completed ``agent_message``
    items after the first matching completed command, rather than searching raw
    stdout or falling back to the final response.  A later message therefore
    cannot satisfy a first-response contract retroactively.
    """

    gateway_commands = frozenset(str(command) for command in validated_gateway_commands)
    if not gateway_commands:
        return None

    first_gateway_completed = False
    for event in parse_jsonl_events(stdout):
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, Mapping):
            continue
        if (
            item.get("type") == "command_execution"
            and item.get("command") in gateway_commands
        ):
            first_gateway_completed = True
            continue
        if (
            first_gateway_completed
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            return item["text"]
    return None


def turn_usage(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    for event in reversed(events):
        usage = event.get("usage")
        if event.get("type") == "turn.completed" and isinstance(usage, Mapping):
            return {str(key): int(value) for key, value in usage.items() if isinstance(value, int)}
    return {}


def snapshot_workspace(root: Path) -> dict[str, str]:
    """Hash files and link targets without following installed Skill symlinks."""

    resolved = root.expanduser().resolve(strict=True)
    snapshot: dict[str, str] = {}
    for directory, dirnames, filenames in os.walk(resolved, followlinks=False):
        directory_path = Path(directory)
        retained_dirnames: list[str] = []
        for name in dirnames:
            path = directory_path / name
            if path.is_symlink():
                relative = path.relative_to(resolved).as_posix()
                metadata = path.lstat()
                snapshot[relative] = hashlib.sha256(
                    b"symlink\0"
                    + f"{stat.S_IMODE(metadata.st_mode)}\0{metadata.st_ctime_ns}\0".encode("ascii")
                    + os.readlink(path).encode("utf-8", errors="surrogateescape")
                ).hexdigest()
            else:
                retained_dirnames.append(name)
        dirnames[:] = retained_dirnames
        for filename in filenames:
            path = directory_path / filename
            relative = path.relative_to(resolved).as_posix()
            if path.is_symlink():
                metadata = path.lstat()
                snapshot[relative] = hashlib.sha256(
                    b"symlink\0"
                    + f"{stat.S_IMODE(metadata.st_mode)}\0{metadata.st_ctime_ns}\0".encode("ascii")
                    + os.readlink(path).encode("utf-8", errors="surrogateescape")
                ).hexdigest()
                continue
            if not path.is_file():
                continue
            metadata = path.stat()
            snapshot[relative] = hashlib.sha256(
                b"file\0"
                + f"{stat.S_IMODE(metadata.st_mode)}\0{metadata.st_size}\0{metadata.st_ctime_ns}\0".encode("ascii")
                + path.read_bytes()
            ).hexdigest()
    return snapshot


def snapshot_tree_hash(snapshot: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for path, file_hash in sorted(snapshot.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def workspace_changes(before: Mapping[str, str], after: Mapping[str, str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    created = tuple(sorted(set(after) - set(before)))
    modified = tuple(sorted(path for path in set(before) & set(after) if before[path] != after[path]))
    return created, modified


__all__ = [
    "CodexCliHarness",
    "CodexCommandRecord",
    "CodexCommandFacts",
    "CodexEnvironmentAudit",
    "CodexHarnessConfig",
    "CodexHarnessError",
    "CodexInfrastructureError",
    "CodexInfrastructureFailure",
    "CodexIsolationAudit",
    "CodexPromptAudit",
    "CodexRunResult",
    "CodexSessionAudit",
    "ProcessResult",
    "audit_prompt_input_payload",
    "audit_session_events",
    "build_exec_command",
    "build_prompt_audit_command",
    "classify_commands",
    "classify_codex_infrastructure_failure",
    "codex_error_messages",
    "completed_command_records",
    "completed_commands",
    "count_invalid_jsonl_lines",
    "final_agent_message",
    "first_gateway_backed_agent_message",
    "gateway_runtime_apis",
    "inspect_isolated_environment",
    "is_protected_environment_key",
    "isolated_codex_environment",
    "normalized_gateway_command_argv",
    "parse_jsonl_events",
    "parse_command_argv",
    "prompt_skill_inventory",
    "run_process",
    "snapshot_workspace",
    "snapshot_tree_hash",
    "turn_usage",
    "workspace_changes",
]
