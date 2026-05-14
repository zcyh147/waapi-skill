"""OpenCode lifecycle harness support for WAAPI semantic scenarios."""

from __future__ import annotations

import os
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from tests.semantic.support.archive import write_semantic_archive_record


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SKILL_INSTALL_PATH = Path("/Users/xiye/Documents/Git/waapi_skill_test/.agents/skills/waapi-skill")
DEFAULT_SKILL_SOURCE_PATH = Path("/Users/xiye/Documents/Git/waapi-skills/skills/waapi-skill")
DEFAULT_TEST_WORKSPACE = Path("/Users/xiye/Documents/Git/waapi_skill_test")
DEFAULT_WAAPI_HOST = "127.0.0.1"
DEFAULT_WAAPI_PORT = 8080
DEFAULT_WWISE_VERSION = "2022.1"
DEFAULT_OPENCODE_SERVE_PORT = 4096
DEFAULT_OPENCODE_RUN_TIMEOUT_SECONDS = 900.0


class OpenCodeHarnessError(RuntimeError):
    """Raised when the OpenCode semantic harness cannot safely run."""


class OpenCodeCommandError(OpenCodeHarnessError):
    """Raised when an attempted OpenCode command fails semantic harness requirements."""

    def __init__(self, message: str, *, command: Sequence[str], output: str, exit_status: int) -> None:
        self.command = [str(part) for part in command]
        self.output = str(output)
        self.exit_status = int(exit_status)
        super().__init__(f"{message}; exit_status={self.exit_status}; output_summary={_output_summary(self.output)}")


class ProcessLike(Protocol):
    pid: int

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ProcessFactory = Callable[..., ProcessLike]
SandboxLauncher = Callable[[], "WwiseSandboxMetadata"]


@dataclass(frozen=True, slots=True)
class SkillSymlinkRequirement:
    """Required symlinked skill install for the OpenCode test workspace."""

    install_path: Path = DEFAULT_SKILL_INSTALL_PATH
    source_path: Path = DEFAULT_SKILL_SOURCE_PATH

    def verify(self) -> "SkillSymlinkProof":
        install = self.install_path.expanduser()
        expected = self.source_path.expanduser().resolve(strict=True)
        if not install.exists() and not install.is_symlink():
            raise OpenCodeHarnessError(f"OpenCode skill install is missing: {install}")
        if not install.is_symlink():
            raise OpenCodeHarnessError(
                f"OpenCode skill install must be a symlink to {expected}; copied directories are not allowed: {install}"
            )
        actual = install.resolve(strict=True)
        if actual != expected:
            raise OpenCodeHarnessError(
                f"OpenCode skill symlink points to {actual}, expected {expected}; recreate it with: "
                f"ln -sfn {expected} {install}"
            )
        return SkillSymlinkProof(install_path=install, source_path=expected, resolved_path=actual)


@dataclass(frozen=True, slots=True)
class SkillSymlinkProof:
    install_path: Path
    source_path: Path
    resolved_path: Path

    def summary(self) -> str:
        return f"{self.install_path} -> {self.resolved_path}"


@dataclass(frozen=True, slots=True)
class WwiseSandboxMetadata:
    """Reference-only Wwise sandbox metadata used by semantic archives."""

    wwise_version: str = DEFAULT_WWISE_VERSION
    waapi_host: str = DEFAULT_WAAPI_HOST
    waapi_port: int = DEFAULT_WAAPI_PORT
    sandbox_metadata_path: Path | None = None


@dataclass(frozen=True, slots=True)
class OpenCodeCommandResult:
    command: list[str]
    prompt: str
    output: str
    exit_status: int
    session_id: str


@dataclass(frozen=True, slots=True)
class OpenCodeArchiveCapture:
    command_result: OpenCodeCommandResult
    archive_path: Path


@dataclass(slots=True)
class OpenCodeServeHandle:
    command: list[str]
    cwd: Path
    server_url: str
    process: ProcessLike | None = None
    mocked: bool = False
    output: str = ""

    @property
    def pid(self) -> int | None:
        return getattr(self.process, "pid", None) if self.process is not None else None

    def shutdown(self, *, timeout: float = 5.0) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=timeout)


@dataclass(frozen=True, slots=True)
class OpenCodeHarnessConfig:
    workspace: Path = DEFAULT_TEST_WORKSPACE
    skill_requirement: SkillSymlinkRequirement = field(default_factory=SkillSymlinkRequirement)
    wwise: WwiseSandboxMetadata = field(default_factory=WwiseSandboxMetadata)
    live: bool = False
    opencode_binary: str = "opencode"
    serve_host: str = "127.0.0.1"
    serve_port: int = DEFAULT_OPENCODE_SERVE_PORT
    opencode_run_timeout_seconds: float | None = DEFAULT_OPENCODE_RUN_TIMEOUT_SECONDS


class OpenCodeSemanticHarness:
    """Models OpenCode serve/run attach behavior with a safe mocked default."""

    def __init__(
        self,
        config: OpenCodeHarnessConfig | None = None,
        *,
        runner: CommandRunner | None = None,
        process_factory: ProcessFactory | None = None,
        sandbox_launcher: SandboxLauncher | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config or OpenCodeHarnessConfig()
        self._runner = runner or subprocess.run
        self._process_factory = process_factory or subprocess.Popen
        self._sandbox_launcher = sandbox_launcher
        self._live_wwise: WwiseSandboxMetadata | None = None
        self._env = dict(env if env is not None else os.environ)

    def verify_skill_symlink(self) -> SkillSymlinkProof:
        return self.config.skill_requirement.verify()

    def start_serve(self) -> OpenCodeServeHandle:
        self.verify_skill_symlink()
        self._require_live_sandbox_if_needed()
        command = [
            self.config.opencode_binary,
            "serve",
            "--hostname",
            self.config.serve_host,
            "--port",
            str(self.config.serve_port),
        ]
        server_url = f"http://{self.config.serve_host}:{self.config.serve_port}"
        cwd = self.config.workspace.expanduser().resolve(strict=False)
        if not self.config.live:
            return OpenCodeServeHandle(command=command, cwd=cwd, server_url=server_url, mocked=True, output="mocked opencode serve lifecycle")
        process = self._process_factory(command, cwd=cwd, env=self._env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return OpenCodeServeHandle(command=command, cwd=cwd, server_url=server_url, process=process, mocked=False)

    def run_attached(
        self,
        *,
        prompt: str,
        attach_url: str | None = None,
        attach_session_id: str | None = None,
        explicit_session_id: str | None = None,
    ) -> OpenCodeCommandResult:
        self.verify_skill_symlink()
        self._require_live_sandbox_if_needed()
        workspace = self.config.workspace.expanduser().resolve(strict=False)
        server_url = attach_url or f"http://{self.config.serve_host}:{self.config.serve_port}"
        command = [self.config.opencode_binary, "run", "--attach", server_url, "--dir", str(workspace), "--format", "json"]
        if attach_session_id:
            command.extend(["--session", attach_session_id])
        command.append(prompt)
        try:
            completed = self._runner(
                command,
                cwd=workspace,
                env=self._env,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.config.opencode_run_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            timeout = exc.timeout if exc.timeout is not None else self.config.opencode_run_timeout_seconds
            timeout_label = f"{float(timeout):g}" if timeout is not None else "configured"
            raise OpenCodeCommandError(
                f"OpenCode attached run timed out after {timeout_label} seconds",
                command=command,
                output=_combined_timeout_output(exc),
                exit_status=124,
            ) from exc
        output = _combined_output(completed)
        session_id = explicit_session_id or extract_opencode_session_id(output) or attach_session_id
        if not session_id:
            raise OpenCodeCommandError(
                "OpenCode session id was not found in attached run output or explicit metadata",
                command=command,
                output=output,
                exit_status=int(completed.returncode),
            )
        return OpenCodeCommandResult(
            command=command,
            prompt=prompt,
            output=output,
            exit_status=int(completed.returncode),
            session_id=session_id,
        )

    def run_attached_and_archive(
        self,
        *,
        scenario_id: str,
        prompt: str,
        expected_assertions: Sequence[str],
        verdict: str = "pass",
        bug_classes: Sequence[str] = (),
        attach_url: str | None = None,
        attach_session_id: str | None = None,
        explicit_session_id: str | None = None,
        archive_root: str | Path | None = None,
        dispatcher_evidence_paths: Sequence[str | Path] = (),
        evidence_references: Sequence[str | Path] = (),
        failure_notes: Sequence[str] = (),
    ) -> OpenCodeArchiveCapture:
        result = self.run_attached(
            prompt=prompt,
            attach_url=attach_url,
            attach_session_id=attach_session_id,
            explicit_session_id=explicit_session_id,
        )
        archive_path = write_semantic_archive_record(
            archive_root=archive_root,
            scenario_id=scenario_id,
            prompt=prompt,
            expected_assertions=expected_assertions,
            assistant_output=result.output,
            verdict=verdict,
            bug_classes=bug_classes,
            wwise_version=self.wwise_metadata.wwise_version,
            waapi_host=self.wwise_metadata.waapi_host,
            waapi_port=self.wwise_metadata.waapi_port,
            opencode_session_id=result.session_id,
            sandbox_metadata_path=self.wwise_metadata.sandbox_metadata_path,
            dispatcher_evidence_paths=dispatcher_evidence_paths,
            evidence_references=evidence_references,
            command_line=result.command,
            command_exit_status=result.exit_status,
            failure_notes=failure_notes,
            run_id=result.session_id,
        )
        return OpenCodeArchiveCapture(command_result=result, archive_path=archive_path)

    @property
    def wwise_metadata(self) -> WwiseSandboxMetadata:
        return self._live_wwise or self.config.wwise

    def _require_live_sandbox_if_needed(self) -> WwiseSandboxMetadata:
        if not self.config.live:
            return self.config.wwise
        if self._live_wwise is not None:
            return self._live_wwise
        if self._sandbox_launcher is None:
            raise OpenCodeHarnessError(
                "live OpenCode semantic runs require an explicit Wwise sandbox launcher that returns sandbox metadata"
            )
        metadata = self._sandbox_launcher()
        if metadata.sandbox_metadata_path is None:
            raise OpenCodeHarnessError("live Wwise sandbox launcher must return a sandbox_metadata_path")
        self._live_wwise = metadata
        return metadata


def extract_opencode_session_id(output: str) -> str | None:
    """Extract a stable OpenCode session id from CLI output without transcript snapshots."""

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        session_id = _session_id_from_json_record(record)
        if session_id:
            return session_id

    patterns = (
        r"(?im)^\s*(?:opencode\s+)?session(?:\s+id)?\s*[:=]\s*([A-Za-z0-9_.:-]+)\s*$",
        r"(?im)^\s*attached\s+to\s+(?:opencode\s+)?session\s+([A-Za-z0-9_.:-]+)\s*$",
        r"\b(ses_[A-Za-z0-9_.:-]+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            return match.group(1)
    return None


def _session_id_from_json_record(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    for key in ("sessionID", "sessionId", "session_id"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    session = record.get("session")
    if isinstance(session, dict):
        for key in ("id", "sessionID", "sessionId", "session_id"):
            value = session.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _combined_output(completed: subprocess.CompletedProcess[str]) -> str:
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout or stderr


def _combined_timeout_output(exc: subprocess.TimeoutExpired) -> str:
    stdout = _coerce_timeout_output(getattr(exc, "output", None))
    stderr = _coerce_timeout_output(getattr(exc, "stderr", None))
    parts = [part for part in (stdout, stderr) if part]
    timeout = f"{float(exc.timeout):g}" if exc.timeout is not None else "configured"
    parts.append(f"OpenCode attached run timed out after {timeout} seconds.")
    return "\n".join(parts)


def _coerce_timeout_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _output_summary(output: str, *, limit: int = 500) -> str:
    normalized = re.sub(r"\s+", " ", output.strip())
    if len(normalized) <= limit:
        return normalized or "<empty>"
    return normalized[: limit - 3] + "..."


__all__ = [
    "DEFAULT_SKILL_INSTALL_PATH",
    "DEFAULT_SKILL_SOURCE_PATH",
    "DEFAULT_TEST_WORKSPACE",
    "DEFAULT_WAAPI_HOST",
    "DEFAULT_WAAPI_PORT",
    "DEFAULT_WWISE_VERSION",
    "DEFAULT_OPENCODE_SERVE_PORT",
    "DEFAULT_OPENCODE_RUN_TIMEOUT_SECONDS",
    "OpenCodeArchiveCapture",
    "OpenCodeCommandError",
    "OpenCodeCommandResult",
    "OpenCodeHarnessConfig",
    "OpenCodeHarnessError",
    "OpenCodeSemanticHarness",
    "OpenCodeServeHandle",
    "SandboxLauncher",
    "SkillSymlinkProof",
    "SkillSymlinkRequirement",
    "WwiseSandboxMetadata",
    "extract_opencode_session_id",
]
