"""Runner-owned gateway broker for fresh Codex semantic evaluations.

The evaluated model receives a temporary ``python``/``python3`` shim on PATH.
The shim can only relay the packaged WAAPI gateway command to this broker.  The
broker validates every invocation against an ordered allow-list and executes
the packaged runner with a trusted interpreter and runner-owned state.

This module is deliberately independent from :mod:`codex_harness` so the
harness can consume its resolver and evidence APIs without making the broker's
audit trail writable by the evaluated model.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence


GATEWAY_RESULT_CONTRACT = "waapi-skill.gateway-result/v1"
STATE_DIRECTORY_ENV = "WAAPI_SKILL_STATE_DIR"
EVIDENCE_DIRECTORY_ENV = "WWISE_EVIDENCE_DIR"
CONFIG_PATH_ENV = "WAAPI_SKILL_CONFIG_PATH"
BROKER_TRANSPORT_ENV = "WAAPI_CODEX_GATEWAY_BROKER_TRANSPORT"
BROKER_ENDPOINT_ENV = "WAAPI_CODEX_GATEWAY_BROKER_ENDPOINT"
BROKER_TOKEN_ENV = "WAAPI_CODEX_GATEWAY_BROKER_TOKEN"
GATEWAY_REQUIRED_ENV = "WAAPI_CODEX_GATEWAY_REQUIRED"
BASH_ENV_NAME = "BASH_ENV"
_BROKER_ENV_NAMES = frozenset(
    {
        BROKER_TRANSPORT_ENV,
        BROKER_ENDPOINT_ENV,
        BROKER_TOKEN_ENV,
        GATEWAY_REQUIRED_ENV,
        BASH_ENV_NAME,
        CONFIG_PATH_ENV,
    }
)
_PYTHON_NAMES = frozenset({"python", "python3"})
_SUPPORTED_WWISE_VERSIONS = frozenset({"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"})
_BROKER_READY = "READY"
_BROKER_RUNNING = "RUNNING"
_BROKER_FAILED = "FAILED"
_BROKER_COMPLETE = "COMPLETE"
_FORBIDDEN_GLOBAL_ARGUMENTS = frozenset({"--state-dir", "--evidence-dir"})
_MODEL_VERSION_SELECTORS = frozenset({"--version", "--wwise-version"})
_GATEWAY_GLOBAL_OPTIONS_WITH_VALUES = frozenset(
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
_RUNNER_TERMINATE_GRACE_SECONDS = 0.25
_RUNNER_REAP_TIMEOUT_SECONDS = 5.0
_BROKER_THREAD_JOIN_SECONDS = 5.0


class GatewayBrokerError(RuntimeError):
    """Base error for broker configuration and lifecycle failures."""


class GatewayInvocationError(GatewayBrokerError, ValueError):
    """The model command is not the exact packaged gateway invocation."""


@dataclass(frozen=True, slots=True)
class SemanticJsonArgument:
    """One argv value compared by canonical JSON semantics, not spelling."""

    expected: Any


@dataclass(frozen=True, slots=True)
class ResponseBinding:
    """Bind one argv value to a JSON field returned by an earlier step.

    ``pointer`` is an RFC 6901 JSON pointer.  Top-level examples are
    ``/transaction_id`` and ``/artifact_hash``.
    """

    step: str
    pointer: str


ExpectedArgument = str | SemanticJsonArgument | ResponseBinding


@dataclass(frozen=True, slots=True)
class ExpectedGatewayStep:
    """One exact, ordered packaged gateway invocation."""

    name: str
    subcommand: str
    arguments: tuple[ExpectedArgument, ...] = ()
    allowed_exit_codes: tuple[int, ...] = (0,)
    gateway_global_arguments: tuple[str, ...] = ()
    allow_omitted_empty_json_objects: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("ExpectedGatewayStep.name must be non-empty")
        if not self.subcommand or not self.subcommand.strip():
            raise ValueError("ExpectedGatewayStep.subcommand must be non-empty")
        if not self.allowed_exit_codes:
            raise ValueError("ExpectedGatewayStep.allowed_exit_codes must be non-empty")
        if self.allowed_exit_codes != (0,):
            raise ValueError("ExpectedGatewayStep.allowed_exit_codes must be exactly (0,)")
        for argument in self.gateway_global_arguments:
            if not isinstance(argument, str) or not argument:
                raise ValueError(
                    "ExpectedGatewayStep.gateway_global_arguments must contain non-empty strings"
                )
            option = argument.split("=", 1)[0]
            if option in _FORBIDDEN_GLOBAL_ARGUMENTS:
                raise ValueError(
                    f"ExpectedGatewayStep.gateway_global_arguments cannot override runner-owned {option}"
                )
        if self.allow_omitted_empty_json_objects:
            expected_shape = (
                len(self.arguments) == 5
                and isinstance(self.arguments[0], str)
                and self.arguments[1] == "--args-json"
                and isinstance(self.arguments[2], SemanticJsonArgument)
                and self.arguments[2].expected == {}
                and self.arguments[3] == "--options-json"
                and isinstance(self.arguments[4], SemanticJsonArgument)
                and self.arguments[4].expected == {}
            )
            if self.subcommand != "call" or not expected_shape:
                raise ValueError(
                    "allow_omitted_empty_json_objects requires a call step with canonical "
                    "--args-json {} --options-json {} arguments"
                )


TrustedStepObserver = Callable[
    [ExpectedGatewayStep, Mapping[str, Any], Path, Path],
    None,
]
TrustedStepPreObserver = Callable[
    [ExpectedGatewayStep, Path, Path],
    None,
]


@dataclass(frozen=True, slots=True)
class ResolvedGatewayInvocation:
    """Normalized facts from one model-side command argv."""

    interpreter: str
    raw_model_argv: tuple[str, ...]
    runner_path: str
    gateway_script: str
    gateway_arguments: tuple[str, ...]
    normalized_model_argv: tuple[str, ...]
    argv_sha256: str

    @property
    def subcommand(self) -> str:
        return _gateway_subcommand(self.gateway_arguments)


@dataclass(frozen=True, slots=True)
class GatewayBrokerRecord:
    """Immutable broker-side evidence for one shim request."""

    sequence: int
    step_name: str | None
    authenticated: bool
    accepted: bool
    rejection: str
    model_argv: tuple[str, ...]
    normalized_model_argv: tuple[str, ...]
    gateway_arguments: tuple[str, ...]
    raw_argv_sha256: str
    argv_sha256: str
    semantic_argv_sha256: str
    started_at_unix: float
    finished_at_unix: float
    duration_seconds: float
    exit_code: int | None
    runner_exit_code: int | None
    stdout: str
    stderr: str
    payload: Mapping[str, Any] | None
    payload_sha256: str
    payload_error: str
    runner_command_sha256: str
    allowed_exit_codes: tuple[int, ...]

    @property
    def succeeded(self) -> bool:
        return (
            self.authenticated
            and self.accepted
            and self.exit_code == self.runner_exit_code
            and self.runner_exit_code in self.allowed_exit_codes
            and self.payload is not None
            and not self.payload_error
        )


@dataclass(frozen=True, slots=True)
class GatewayBrokerEvidence:
    """Trusted in-memory evidence snapshot consumed by the harness."""

    expected_step_names: tuple[str, ...]
    consumed_step_names: tuple[str, ...]
    records: tuple[GatewayBrokerRecord, ...]
    state_directory: str
    evidence_directory: str
    runner_path: str
    terminal_state: str
    complete: bool

    @property
    def rejected_records(self) -> tuple[GatewayBrokerRecord, ...]:
        return tuple(record for record in self.records if not record.accepted)

    @property
    def accepted_records(self) -> tuple[GatewayBrokerRecord, ...]:
        return tuple(record for record in self.records if record.accepted)

    @property
    def successful_records(self) -> tuple[GatewayBrokerRecord, ...]:
        return tuple(record for record in self.records if record.succeeded)

    @property
    def passed(self) -> bool:
        return (
            self.complete
            and self.terminal_state == _BROKER_COMPLETE
            and len(self.successful_records) == len(self.expected_step_names)
            and len(self.records) == len(self.expected_step_names)
            and not self.rejected_records
            and all(record.succeeded for record in self.records)
        )

    def as_dict(self, *, include_output: bool = False) -> dict[str, Any]:
        payload = asdict(self)
        payload["passed"] = self.passed
        for record_payload, record in zip(payload["records"], self.records):
            record_payload["succeeded"] = record.succeeded
        if not include_output:
            for record in payload["records"]:
                record.pop("stdout", None)
                record.pop("stderr", None)
        return payload


@dataclass(frozen=True, slots=True)
class GatewayBrokerReconciliation:
    """Result of matching harness-observed commands to broker evidence."""

    passed: bool
    observed_command_count: int
    accepted_record_count: int
    errors: tuple[str, ...]


def _gateway_subcommand(arguments: Sequence[str]) -> str:
    """Return the gateway subcommand after the closed global-option prefix."""

    values = tuple(str(value) for value in arguments)
    index = 0
    while index < len(values):
        value = values[index]
        if value.startswith("--"):
            if any(
                value.startswith(f"{option}=")
                for option in _GATEWAY_GLOBAL_OPTIONS_WITH_VALUES
            ):
                index += 1
                continue
            if value in _GATEWAY_GLOBAL_OPTIONS_WITH_VALUES:
                if index + 1 >= len(values):
                    return ""
                index += 2
                continue
            return ""
        return value
    return ""


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GatewayInvocationError(f"value is not canonical JSON: {exc}") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _argv_sha256(argv: Sequence[str]) -> str:
    return _sha256_bytes(_canonical_json_bytes(list(argv)))


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _require_real_directory(path: Path, *, label: str) -> Path:
    candidate = _absolute_lexical(path)
    if candidate.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {candidate}")
    if not candidate.is_dir():
        raise ValueError(f"{label} must be an existing directory: {candidate}")
    return candidate


def resolve_gateway_invocation(
    argv: Sequence[str],
    *,
    skill_source: Path,
    shim_directory: Path | None = None,
) -> ResolvedGatewayInvocation:
    """Resolve and strictly validate one model-side gateway command argv.

    The canonical accepted shape is::

        python ABS_SKILL/scripts/run.py gateway.py ...

    The production runner's one closed compatibility spelling is accepted too::

        python ABS_SKILL/scripts/run.py --version VERSION gateway.py ...

    ``python3`` is also accepted.  When ``shim_directory`` is supplied, an
    absolute interpreter path must point to its ``python`` or ``python3`` shim.
    The skill runner is compared lexically to the configured absolute locator;
    a different symlink spelling is intentionally rejected.
    """

    values = tuple(str(value) for value in argv)
    if len(values) < 4:
        raise GatewayInvocationError("gateway command must contain python, run.py, gateway.py, and a subcommand")

    interpreter_path = Path(values[0])
    interpreter_name = interpreter_path.name
    if interpreter_name not in _PYTHON_NAMES:
        raise GatewayInvocationError("gateway command interpreter must be python or python3")
    if interpreter_path.parent != Path("."):
        if shim_directory is None or not interpreter_path.is_absolute():
            raise GatewayInvocationError("Python interpreter must be bare or an absolute broker shim path")
        expected_parent = _absolute_lexical(shim_directory)
        if _absolute_lexical(interpreter_path).parent != expected_parent:
            raise GatewayInvocationError("absolute Python interpreter is not the broker shim")

    expected_runner = _absolute_lexical(skill_source) / "scripts" / "run.py"
    supplied_runner = Path(values[1])
    if not supplied_runner.is_absolute() or supplied_runner != expected_runner:
        raise GatewayInvocationError(f"runner path must be exactly {expected_runner}")
    if values[2] == "gateway.py":
        gateway_arguments = values[3:]
    else:
        selector = values[2]
        if selector in _MODEL_VERSION_SELECTORS:
            if len(values) < 6:
                raise GatewayInvocationError(
                    "runner-level version selector requires VERSION, gateway.py, and a subcommand"
                )
            supplied_version = values[3]
            gateway_target = values[4]
            remainder = values[5:]
            canonical_selector = (selector, supplied_version)
        elif any(selector.startswith(f"{option}=") for option in _MODEL_VERSION_SELECTORS):
            if len(values) < 5:
                raise GatewayInvocationError(
                    "runner-level version selector requires gateway.py and a subcommand"
                )
            gateway_target = values[3]
            remainder = values[4:]
            canonical_selector = (selector,)
        else:
            raise GatewayInvocationError("packaged runner target must be exactly gateway.py")
        if gateway_target != "gateway.py":
            raise GatewayInvocationError(
                "runner-level version selector is allowed only before the exact target gateway.py"
            )
        gateway_arguments = (*canonical_selector, *remainder)

    normalized = (interpreter_name, str(expected_runner), "gateway.py", *gateway_arguments)
    return ResolvedGatewayInvocation(
        interpreter=interpreter_name,
        raw_model_argv=values,
        runner_path=str(expected_runner),
        gateway_script="gateway.py",
        gateway_arguments=gateway_arguments,
        normalized_model_argv=normalized,
        argv_sha256=_argv_sha256(normalized),
    )


def reconcile_gateway_commands(
    command_argvs: Sequence[Sequence[str]],
    evidence: GatewayBrokerEvidence,
    *,
    skill_source: Path,
    shim_directory: Path | None = None,
) -> GatewayBrokerReconciliation:
    """Cross-check harness-observed argv against accepted broker records."""

    errors: list[str] = []
    resolved: list[ResolvedGatewayInvocation] = []
    for index, argv in enumerate(command_argvs):
        try:
            resolved.append(
                resolve_gateway_invocation(
                    argv,
                    skill_source=skill_source,
                    shim_directory=shim_directory,
                )
            )
        except GatewayInvocationError as exc:
            errors.append(f"command {index}: {exc}")

    accepted = evidence.accepted_records
    if len(resolved) != len(accepted):
        errors.append(
            f"resolved command count {len(resolved)} does not match accepted broker record count {len(accepted)}"
        )
    for index, (command, record) in enumerate(zip(resolved, accepted)):
        if command.normalized_model_argv != record.normalized_model_argv:
            errors.append(f"command {index}: normalized argv differs from broker record")
        if command.argv_sha256 != record.argv_sha256:
            errors.append(f"command {index}: argv hash differs from broker record")
        if not record.succeeded:
            errors.append(f"command {index}: broker record did not succeed")
    if evidence.rejected_records:
        errors.append("broker recorded one or more rejected shim requests")
    if not evidence.complete:
        errors.append("broker did not consume every expected step")
    if not evidence.passed:
        errors.append("broker evidence did not pass its terminal success contract")

    return GatewayBrokerReconciliation(
        passed=not errors,
        observed_command_count=len(command_argvs),
        accepted_record_count=len(accepted),
        errors=tuple(errors),
    )


def _json_pointer(payload: Any, pointer: str) -> Any:
    if pointer == "":
        return payload
    if not pointer.startswith("/"):
        raise GatewayInvocationError(f"response binding pointer must be RFC 6901 JSON pointer: {pointer!r}")
    current = payload
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if part not in current:
                raise GatewayInvocationError(f"response binding field is absent: {pointer!r}")
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise GatewayInvocationError(f"response binding index is invalid: {pointer!r}") from exc
        else:
            raise GatewayInvocationError(f"response binding cannot traverse: {pointer!r}")
    return current


def _decode_json_argument(value: str) -> Any:
    def reject_constant(constant: str) -> Any:
        raise ValueError(f"non-finite JSON constant {constant!r}")

    try:
        return json.loads(value, parse_constant=reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise GatewayInvocationError(f"argument is not strict JSON: {exc}") from exc


def _extract_payload(stdout: str, *, required_contract: str | None = None) -> Mapping[str, Any]:
    stripped = stdout.strip()
    if not stripped:
        raise GatewayInvocationError("packaged runner emitted no JSON payload")
    def reject_constant(constant: str) -> Any:
        raise ValueError(f"non-finite JSON constant {constant!r}")

    decoder = json.JSONDecoder(parse_constant=reject_constant)
    candidates: list[tuple[int, int, Mapping[str, Any]]] = []
    for position, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(stripped, position)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, Mapping):
            candidates.append((end - position, -position, value))
    if not candidates:
        raise GatewayInvocationError("packaged runner output contains no JSON object")
    if required_contract is not None:
        contract_candidates = [
            candidate for candidate in candidates if candidate[2].get("contract") == required_contract
        ]
        if contract_candidates:
            candidates = contract_candidates
    # Pretty-printed gateway results contain nested JSON objects.  Choosing the
    # last decodable object would therefore select an inner field.  The outer
    # gateway envelope is the widest decodable object in the output.
    _, _, payload = max(candidates, key=lambda candidate: (candidate[0], candidate[1]))
    return dict(payload)


_SHIM_SOURCE = r'''#!{python}
from __future__ import annotations
import json
import os
import socket
import sys

transport = os.environ.get({transport_env!r}, "")
endpoint = os.environ.get({endpoint_env!r}, "")
token = os.environ.get({token_env!r}, "")
request = json.dumps({{"token": token, "interpreter": sys.argv[0], "argv": sys.argv[1:]}}, separators=(",", ":")) + "\n"
try:
    if transport == "unix":
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.connect(endpoint)
    elif transport == "tcp":
        host, port = endpoint.rsplit(":", 1)
        connection = socket.create_connection((host, int(port)), timeout=30)
    else:
        raise RuntimeError("Codex gateway broker transport is not configured")
    with connection:
        connection.sendall(request.encode("utf-8"))
        chunks = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    response = json.loads(b"".join(chunks).decode("utf-8"))
    sys.stdout.write(response.get("stdout", ""))
    sys.stderr.write(response.get("stderr", ""))
    raise SystemExit(int(response.get("exit_code", 125)))
except Exception as exc:
    sys.stderr.write("Codex gateway broker shim failed: " + str(exc) + "\n")
    raise SystemExit(125)
'''


class CodexGatewayBroker:
    """One-run local broker for an ordered semantic gateway scenario."""

    def __init__(
        self,
        *,
        skill_source: Path,
        expected_steps: Sequence[ExpectedGatewayStep],
        gateway_global_arguments: Sequence[str] = (),
        expected_wwise_version: str = "",
        runner_environment: Mapping[str, str] | None = None,
        trusted_python: Path | None = None,
        runner_cwd: Path | None = None,
        working_root: Path | None = None,
        existing_state_directory: Path | None = None,
        transport: str = "auto",
        runner_timeout_seconds: float = 120.0,
        required_contract: str | None = GATEWAY_RESULT_CONTRACT,
        trusted_step_pre_observer: TrustedStepPreObserver | None = None,
        trusted_step_observer: TrustedStepObserver | None = None,
    ) -> None:
        self.skill_source = _absolute_lexical(skill_source)
        self.runner_path = self.skill_source / "scripts" / "run.py"
        self.expected_steps = tuple(expected_steps)
        self.gateway_global_arguments = tuple(str(value) for value in gateway_global_arguments)
        self.expected_wwise_version = str(expected_wwise_version)
        self.trusted_python = _absolute_lexical(trusted_python or Path(sys.executable))
        self.runner_cwd = _absolute_lexical(runner_cwd or self.skill_source)
        self._requested_working_root = _absolute_lexical(working_root) if working_root else None
        self._existing_state_directory = (
            _require_real_directory(existing_state_directory, label="existing_state_directory")
            if existing_state_directory is not None
            else None
        )
        self.transport_preference = transport
        self.runner_timeout_seconds = float(runner_timeout_seconds)
        self.required_contract = required_contract
        self.trusted_step_pre_observer = trusted_step_pre_observer
        self.trusted_step_observer = trusted_step_observer
        self._runner_environment = dict(os.environ if runner_environment is None else runner_environment)

        if transport not in {"auto", "unix", "tcp"}:
            raise ValueError("transport must be auto, unix, or tcp")
        if self.runner_timeout_seconds <= 0:
            raise ValueError("runner_timeout_seconds must be positive")
        if not self.expected_steps:
            raise ValueError("expected_steps must contain at least one step")
        if self.expected_wwise_version and self.expected_wwise_version not in _SUPPORTED_WWISE_VERSIONS:
            raise ValueError(
                "expected_wwise_version must be empty or one of "
                f"{tuple(sorted(_SUPPORTED_WWISE_VERSIONS))!r}"
            )
        if self.required_contract != GATEWAY_RESULT_CONTRACT:
            raise ValueError(
                f"required_contract must be exactly {GATEWAY_RESULT_CONTRACT!r}"
            )
        if self.trusted_step_observer is not None and not callable(self.trusted_step_observer):
            raise TypeError("trusted_step_observer must be callable or None")
        if self.trusted_step_pre_observer is not None and not callable(
            self.trusted_step_pre_observer
        ):
            raise TypeError("trusted_step_pre_observer must be callable or None")
        for argument in self.gateway_global_arguments:
            option = argument.split("=", 1)[0]
            if option in _FORBIDDEN_GLOBAL_ARGUMENTS:
                raise ValueError(
                    f"gateway_global_arguments cannot override runner-owned {option}"
                )
        names = [step.name for step in self.expected_steps]
        if len(names) != len(set(names)):
            raise ValueError("ExpectedGatewayStep names must be unique")

        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        self._working_root: Path | None = None
        self._shim_directory: Path | None = None
        self._bash_env_path: Path | None = None
        self._state_directory: Path | None = None
        self._evidence_directory: Path | None = None
        self._config_path: Path | None = None
        self._socket: socket.socket | None = None
        self._socket_path: Path | None = None
        self._transport = ""
        self._endpoint = ""
        self._token = ""
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._active_process: subprocess.Popen[str] | None = None
        self._active_process_done = threading.Event()
        self._active_process_done.set()
        self._records: list[GatewayBrokerRecord] = []
        self._next_step = 0
        self._payloads_by_step: dict[str, Mapping[str, Any]] = {}
        self._terminal_state = _BROKER_READY
        self._started = False
        self._ever_started = False
        self._created_directories: list[Path] = []
        self._working_root_created = False

    @property
    def shim_directory(self) -> Path:
        if self._shim_directory is None:
            raise GatewayBrokerError("broker has not started")
        return self._shim_directory

    @property
    def state_directory(self) -> Path:
        if self._state_directory is None:
            raise GatewayBrokerError("broker has not started")
        return self._state_directory

    @property
    def evidence_directory(self) -> Path:
        if self._evidence_directory is None:
            raise GatewayBrokerError("broker has not started")
        return self._evidence_directory

    @property
    def config_path(self) -> Path:
        if self._config_path is None:
            raise GatewayBrokerError("broker has not started")
        return self._config_path

    @property
    def bash_env_path(self) -> Path:
        if self._bash_env_path is None:
            raise GatewayBrokerError("broker has not started")
        return self._bash_env_path

    @property
    def transport(self) -> str:
        if not self._transport:
            raise GatewayBrokerError("broker has not started")
        return self._transport

    @property
    def endpoint(self) -> str:
        if not self._endpoint:
            raise GatewayBrokerError("broker has not started")
        return self._endpoint

    def __enter__(self) -> CodexGatewayBroker:
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            self.close()
        except BaseException as close_exc:  # noqa: BLE001 - never mask the body failure
            if exc is None:
                raise
            if hasattr(exc, "add_note"):
                exc.add_note(
                    "CodexGatewayBroker.close() also failed: "
                    f"{type(close_exc).__name__}: {close_exc}"
                )

    def start(self) -> CodexGatewayBroker:
        if self._started:
            raise GatewayBrokerError("broker is already started")
        if self._ever_started:
            raise GatewayBrokerError("a broker instance cannot be restarted")
        # A broker is deliberately one-shot even when a start attempt fails
        # part-way through.  Reusing partially initialized authentication or
        # filesystem state would make the audit boundary ambiguous.
        self._ever_started = True
        try:
            if not self.runner_path.is_file():
                raise GatewayBrokerError(f"packaged runner does not exist: {self.runner_path}")
            if not self.trusted_python.is_file():
                raise GatewayBrokerError(f"trusted Python does not exist: {self.trusted_python}")

            if self._requested_working_root is None:
                self._temporary_directory = tempfile.TemporaryDirectory(prefix="waapi-codex-broker-")
                root = Path(self._temporary_directory.name)
            else:
                root = self._requested_working_root
                self._working_root_created = not root.exists()
                root.mkdir(parents=True, exist_ok=True)
            self._working_root = root
            self._shim_directory = root / "bin"
            self._state_directory = self._existing_state_directory or (root / "state")
            self._evidence_directory = root / "evidence"
            config_directory = root / "config"
            self._config_path = config_directory / "config.json"
            for directory in (self._shim_directory, self._evidence_directory, config_directory):
                directory.mkdir(parents=True, exist_ok=False)
                self._created_directories.append(directory)
            if self._existing_state_directory is None:
                self._state_directory.mkdir(parents=True, exist_ok=False)
                self._created_directories.append(self._state_directory)
            else:
                self._state_directory = _require_real_directory(
                    self._state_directory,
                    label="existing_state_directory",
                )
            self._config_path.write_text(
                json.dumps(
                    {
                        "wwise_version": None,
                        "waapi_host": "127.0.0.1",
                        "waapi_port": None,
                        "project_modification_policy": "preview_then_confirm",
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            self._token = secrets.token_urlsafe(32)
            self._bind_socket(root)
            self._write_shims()
            self._stop.clear()
            self._terminal_state = _BROKER_RUNNING
            self._thread = threading.Thread(
                target=self._serve,
                name="codex-gateway-broker",
                daemon=True,
            )
            self._thread.start()
            self._started = True
            return self
        except BaseException as exc:  # noqa: BLE001 - rollback must include interrupts
            cleanup_errors = self._rollback_failed_start()
            if cleanup_errors and hasattr(exc, "add_note"):
                exc.add_note("Broker start rollback errors: " + "; ".join(cleanup_errors))
            raise

    def close(self) -> None:
        if not self._started:
            return
        self._stop.set()
        self._wake_server()

        # A packaged runner can launch Wwise/Wine descendants.  It therefore
        # runs in its own process group and close always signals the group,
        # gives it a short grace period, then kills the group.  The serving
        # thread owns communicate()/reaping; the event prevents concurrent
        # Popen.wait()/communicate() calls and their associated deadlocks.
        with self._process_lock:
            active_process = self._active_process
        if active_process is not None:
            self._signal_runner_group(active_process, terminate=True)
            self._active_process_done.wait(_RUNNER_TERMINATE_GRACE_SECONDS)
            # Kill the group even if its leader already exited: a descendant
            # may have ignored SIGTERM while retaining the process group.
            self._signal_runner_group(active_process, terminate=False)

        if self._thread is not None:
            self._thread.join(timeout=_RUNNER_REAP_TIMEOUT_SECONDS)
            if self._thread.is_alive():
                # Closing the listening socket is a final accept() unblock; it
                # cannot interrupt an active request, which was handled above.
                if self._socket is not None:
                    self._socket.close()
                self._thread.join(timeout=_BROKER_THREAD_JOIN_SECONDS)
            if self._thread.is_alive():
                raise GatewayBrokerError("broker thread did not exit after runner process-group teardown")
        if active_process is not None:
            if not self._active_process_done.is_set() or active_process.poll() is None:
                raise GatewayBrokerError("packaged gateway runner was not reaped during broker close")
        if self._socket is not None:
            self._socket.close()
        if self._socket_path is not None:
            self._socket_path.unlink(missing_ok=True)
        self._started = False
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
            self._temporary_directory = None

    def _rollback_failed_start(self) -> list[str]:
        """Best-effort transactional rollback that never replaces start's error."""

        errors: list[str] = []
        self._stop.set()
        self._wake_server()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError as exc:
                errors.append(f"socket close: {exc}")
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=_BROKER_THREAD_JOIN_SECONDS)
            if self._thread.is_alive():
                errors.append("broker thread did not exit")
        if self._socket_path is not None:
            try:
                self._socket_path.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(f"socket path cleanup: {exc}")

        if self._temporary_directory is not None:
            try:
                self._temporary_directory.cleanup()
            except OSError as exc:
                errors.append(f"temporary directory cleanup: {exc}")
        else:
            for directory in reversed(self._created_directories):
                try:
                    if directory.is_symlink():
                        directory.unlink(missing_ok=True)
                    elif directory.exists():
                        shutil.rmtree(directory)
                except OSError as exc:
                    errors.append(f"directory cleanup {directory}: {exc}")
            if self._working_root_created and self._working_root is not None:
                try:
                    self._working_root.rmdir()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    errors.append(f"working root cleanup {self._working_root}: {exc}")

        self._temporary_directory = None
        self._working_root = None
        self._shim_directory = None
        self._bash_env_path = None
        self._state_directory = None
        self._evidence_directory = None
        self._config_path = None
        self._socket = None
        self._socket_path = None
        self._transport = ""
        self._endpoint = ""
        self._token = ""
        self._thread = None
        self._terminal_state = _BROKER_FAILED
        self._started = False
        self._created_directories.clear()
        self._working_root_created = False
        return errors

    def model_environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """Return model env with only broker connection data and shimmed PATH."""

        if not self._started:
            raise GatewayBrokerError("broker has not started")
        environment = dict(os.environ if base is None else base)
        environment.update(self.model_environment_overrides(environment.get("PATH")))
        return environment

    def model_environment_overrides(self, existing_path: str | None = None) -> dict[str, str]:
        """Return the small overlay suitable for ``CodexCliHarness.extra_env``.

        Unlike :meth:`model_environment`, this does not copy ``HOME``,
        ``CODEX_HOME``, or any other caller state into the result.
        """

        if not self._started:
            raise GatewayBrokerError("broker has not started")
        old_path = existing_path if existing_path is not None else os.environ.get("PATH", os.defpath)
        return {
            "PATH": os.pathsep.join((str(self.shim_directory), old_path)),
            BASH_ENV_NAME: str(self.bash_env_path),
            BROKER_TRANSPORT_ENV: self.transport,
            BROKER_ENDPOINT_ENV: self.endpoint,
            BROKER_TOKEN_ENV: self._token,
            GATEWAY_REQUIRED_ENV: "1",
        }

    def evidence(self) -> GatewayBrokerEvidence:
        with self._lock:
            records = tuple(self._records)
            consumed = tuple(step.name for step in self.expected_steps[: self._next_step])
            successful_count = sum(record.succeeded for record in records)
            complete = (
                self._terminal_state == _BROKER_COMPLETE
                and self._next_step == len(self.expected_steps)
                and successful_count == len(self.expected_steps)
                and len(records) == len(self.expected_steps)
                and all(record.succeeded for record in records)
            )
            terminal_state = self._terminal_state
        return GatewayBrokerEvidence(
            expected_step_names=tuple(step.name for step in self.expected_steps),
            consumed_step_names=consumed,
            records=records,
            state_directory=str(self.state_directory),
            evidence_directory=str(self.evidence_directory),
            runner_path=str(self.runner_path),
            terminal_state=terminal_state,
            complete=complete,
        )

    def reconcile(self, command_argvs: Sequence[Sequence[str]]) -> GatewayBrokerReconciliation:
        return reconcile_gateway_commands(
            command_argvs,
            self.evidence(),
            skill_source=self.skill_source,
            shim_directory=self.shim_directory,
        )

    def _bind_socket(self, root: Path) -> None:
        use_unix = self.transport_preference in {"auto", "unix"} and hasattr(socket, "AF_UNIX")
        socket_path = root / "broker.sock"
        server: socket.socket | None = None
        bound_socket_path: Path | None = None
        try:
            if use_unix and len(os.fsencode(socket_path)) < 100:
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(str(socket_path))
                bound_socket_path = socket_path
                transport = "unix"
                endpoint = str(socket_path)
            elif self.transport_preference == "unix":
                raise GatewayBrokerError("Unix socket is unavailable or its path is too long")
            else:
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.bind(("127.0.0.1", 0))
                host, port = server.getsockname()
                transport = "tcp"
                endpoint = f"{host}:{port}"
            server.listen(8)
            server.settimeout(0.25)
        except BaseException:  # noqa: BLE001 - local socket must not leak on partial bind
            if server is not None:
                server.close()
            if bound_socket_path is not None:
                bound_socket_path.unlink(missing_ok=True)
            raise

        self._socket = server
        self._socket_path = bound_socket_path
        self._transport = transport
        self._endpoint = endpoint

    def _write_shims(self) -> None:
        source = _SHIM_SOURCE.format(
            python=self.trusted_python,
            transport_env=BROKER_TRANSPORT_ENV,
            endpoint_env=BROKER_ENDPOINT_ENV,
            token_env=BROKER_TOKEN_ENV,
        )
        for name in sorted(_PYTHON_NAMES):
            path = self.shim_directory / name
            path.write_text(source, encoding="utf-8")
            path.chmod(0o700)
        self._bash_env_path = self.shim_directory / "bash_env"
        self._bash_env_path.write_text(
            "unset -f python python3 2>/dev/null || :\n"
            "unalias python python3 2>/dev/null || :\n"
            f"export PATH={shlex.quote(str(self.shim_directory))}:\"${{PATH:-/usr/bin:/bin}}\"\n"
            "hash -r 2>/dev/null || :\n",
            encoding="utf-8",
        )
        self._bash_env_path.chmod(0o400)

    def _wake_server(self) -> None:
        try:
            if self._transport == "unix":
                connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                connection.settimeout(0.2)
                connection.connect(self._endpoint)
            elif self._transport == "tcp":
                host, port = self._endpoint.rsplit(":", 1)
                connection = socket.create_connection((host, int(port)), timeout=0.2)
            else:
                return
            connection.close()
        except OSError:
            pass

    @staticmethod
    def _signal_runner_group(process: subprocess.Popen[str], *, terminate: bool) -> None:
        """Signal the runner's process group, tolerating an already-dead group."""

        if os.name == "posix":
            signum = signal.SIGTERM if terminate else signal.SIGKILL
            try:
                # Do not skip this because the leader exited: descendants can
                # retain the process group after Popen.poll() becomes non-None.
                os.killpg(process.pid, signum)
            except ProcessLookupError:
                pass
            return

        # Non-POSIX fallback cannot portably address a descendant process tree,
        # but it still preserves the broker's parent-process lifecycle.
        if process.poll() is not None:
            return
        try:
            if terminate:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass

    def _launch_runner(
        self,
        command: Sequence[str],
        *,
        runner_env: Mapping[str, str],
    ) -> subprocess.Popen[str]:
        """Launch and atomically publish one active packaged runner."""

        popen_arguments: dict[str, Any] = {
            "cwd": self.runner_cwd,
            "env": dict(runner_env),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if os.name == "posix":
            popen_arguments["start_new_session"] = True
        elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            popen_arguments["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        # close() sets _stop before acquiring this lock.  Holding it across
        # Popen construction closes the only launch/teardown race: close either
        # sees the registered process, or launch sees the stop request.
        with self._process_lock:
            if self._stop.is_set():
                raise GatewayBrokerError("broker is closing before packaged runner launch")
            process = subprocess.Popen(command, **popen_arguments)
            self._active_process_done.clear()
            self._active_process = process
        return process

    def _communicate_runner(
        self,
        process: subprocess.Popen[str],
    ) -> tuple[str, str]:
        """Communicate with one runner and guarantee owner-thread reaping."""

        try:
            try:
                return process.communicate(timeout=self.runner_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                self._signal_runner_group(process, terminate=True)
                try:
                    stdout, stderr = process.communicate(
                        timeout=_RUNNER_TERMINATE_GRACE_SECONDS
                    )
                except subprocess.TimeoutExpired:
                    self._signal_runner_group(process, terminate=False)
                    stdout, stderr = process.communicate()
                exc.stdout = stdout
                exc.stderr = stderr
                raise
        finally:
            # An unexpected communicate error must not orphan the runner.
            if process.poll() is None:
                self._signal_runner_group(process, terminate=True)
                try:
                    process.wait(timeout=_RUNNER_TERMINATE_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    self._signal_runner_group(process, terminate=False)
                    process.wait(timeout=_RUNNER_REAP_TIMEOUT_SECONDS)
            with self._process_lock:
                if self._active_process is process:
                    self._active_process = None
                    self._active_process_done.set()

    def _serve(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                connection, _ = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                request: Mapping[str, Any] | None = None
                try:
                    request = self._read_request(connection)
                    response = self._handle_request(request)
                except Exception as exc:  # noqa: BLE001 - fail-closed shim protocol
                    if self._stop.is_set():
                        continue
                    token = request.get("token") if request is not None else None
                    authenticated = isinstance(token, str) and secrets.compare_digest(token, self._token)
                    response = self._reject(
                        (),
                        f"unexpected broker protocol failure: {type(exc).__name__}: {exc}",
                        authenticated=authenticated,
                        response_exit=125,
                        payload_error=str(exc),
                    )
                try:
                    connection.sendall(_canonical_json_bytes(response))
                except OSError:
                    pass

    @staticmethod
    def _read_request(connection: socket.socket) -> Mapping[str, Any]:
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > 4 * 1024 * 1024:
                raise GatewayInvocationError("shim request exceeds 4 MiB")
            if b"\n" in chunk:
                break
        raw = b"".join(chunks).split(b"\n", 1)[0]
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise GatewayInvocationError("shim request must be a JSON object")
        return payload

    def _handle_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        token = request.get("token")
        raw_argv = request.get("argv")
        interpreter = request.get("interpreter")
        authenticated = isinstance(token, str) and secrets.compare_digest(token, self._token)
        if not isinstance(raw_argv, list) or not all(isinstance(value, str) for value in raw_argv):
            return self._reject(
                (),
                "shim argv must be a string array",
                authenticated=authenticated,
            )
        model_argv = (str(interpreter or ""), *raw_argv)
        if not authenticated:
            return self._reject(
                model_argv,
                "broker authentication failed",
                authenticated=False,
            )

        with self._lock:
            if self._terminal_state != _BROKER_RUNNING:
                return self._reject_locked(
                    None,
                    f"broker is terminal {self._terminal_state}",
                    model_argv=model_argv,
                    authenticated=True,
                )

        try:
            resolved = resolve_gateway_invocation(
                model_argv,
                skill_source=self.skill_source,
                shim_directory=self.shim_directory,
            )
        except GatewayInvocationError as exc:
            return self._reject(model_argv, str(exc), authenticated=True)
        except Exception as exc:  # noqa: BLE001 - authenticated failures are terminal and recorded
            return self._reject(
                model_argv,
                f"unexpected invocation resolver failure: {type(exc).__name__}: {exc}",
                authenticated=True,
                response_exit=125,
                payload_error=str(exc),
            )

        with self._lock:
            if self._terminal_state != _BROKER_RUNNING:
                return self._reject_locked(
                    resolved,
                    f"broker is terminal {self._terminal_state}",
                    authenticated=True,
                )
            step = self.expected_steps[self._next_step]
            try:
                semantic_hash, execution_arguments = self._validate_step(
                    step,
                    resolved.gateway_arguments,
                )
            except GatewayInvocationError as exc:
                return self._reject_locked(resolved, str(exc), authenticated=True)
            except Exception as exc:  # noqa: BLE001 - authenticated failures are terminal and recorded
                return self._reject_locked(
                    resolved,
                    f"unexpected allow-list validation failure: {type(exc).__name__}: {exc}",
                    authenticated=True,
                    response_exit=125,
                    payload_error=str(exc),
                )

        return self._execute(
            step,
            resolved,
            semantic_hash,
            execution_arguments=execution_arguments,
        )

    def _validate_step(
        self,
        step: ExpectedGatewayStep,
        actual: Sequence[str],
    ) -> tuple[str, tuple[str, ...]]:
        actual_values = tuple(str(value) for value in actual)
        supplied_version = ""
        version_selector_seen = False
        if actual_values and self.expected_wwise_version:
            first = actual_values[0]
            if first in {"--version", "--wwise-version"}:
                version_selector_seen = True
                if len(actual_values) < 2:
                    raise GatewayInvocationError(f"{first} requires one version value")
                supplied_version = actual_values[1]
                actual_values = actual_values[2:]
            elif first.startswith("--version=") or first.startswith("--wwise-version="):
                version_selector_seen = True
                supplied_version = first.split("=", 1)[1]
                actual_values = actual_values[1:]
            if version_selector_seen and supplied_version != self.expected_wwise_version:
                raise GatewayInvocationError(
                    "model version selector must match the runner-owned session version "
                    f"{self.expected_wwise_version!r}; received {supplied_version!r}"
                )

        expected_prefix = (
            *self.gateway_global_arguments,
            *step.gateway_global_arguments,
            step.subcommand,
        )
        if actual_values[: len(expected_prefix)] != expected_prefix:
            raise GatewayInvocationError(
                f"expected step {step.name!r} argv prefix {expected_prefix!r}; received {tuple(actual)!r}"
            )
        supplied_arguments = actual_values[len(expected_prefix) :]
        validation_arguments = supplied_arguments
        if (
            step.allow_omitted_empty_json_objects
            and supplied_arguments == (step.arguments[0],)
        ):
            validation_arguments = (
                supplied_arguments[0],
                "--args-json",
                "{}",
                "--options-json",
                "{}",
            )
        if len(validation_arguments) != len(step.arguments):
            raise GatewayInvocationError(
                f"expected step {step.name!r} to have {len(step.arguments)} arguments; "
                f"received {len(supplied_arguments)}"
            )

        semantic_values: list[Any] = [
            "runner-owned-version",
            self.expected_wwise_version,
            *expected_prefix,
        ]
        for index, (supplied, expected) in enumerate(
            zip(validation_arguments, step.arguments)
        ):
            if isinstance(expected, str):
                if supplied != expected:
                    raise GatewayInvocationError(
                        f"step {step.name!r} argument {index} must be exactly {expected!r}"
                    )
                semantic_values.append(expected)
            elif isinstance(expected, SemanticJsonArgument):
                actual_json = _decode_json_argument(supplied)
                if _canonical_json_bytes(actual_json) != _canonical_json_bytes(expected.expected):
                    raise GatewayInvocationError(
                        f"step {step.name!r} argument {index} JSON is not semantically equal to the allow-list"
                    )
                semantic_values.append(expected.expected)
            elif isinstance(expected, ResponseBinding):
                source = self._payloads_by_step.get(expected.step)
                if source is None:
                    raise GatewayInvocationError(
                        f"step {step.name!r} binding source {expected.step!r} is unavailable"
                    )
                bound = _json_pointer(source, expected.pointer)
                if not isinstance(bound, (str, int, float, bool)) or bound is None:
                    raise GatewayInvocationError(
                        f"step {step.name!r} binding {expected.pointer!r} is not a scalar argv value"
                    )
                if supplied != str(bound):
                    raise GatewayInvocationError(
                        f"step {step.name!r} argument {index} does not match {expected.step}{expected.pointer}"
                    )
                semantic_values.append(bound)
            else:  # pragma: no cover - type checker prevents this for normal callers
                raise GatewayInvocationError(f"unsupported expected argument at index {index}")
        return _sha256_bytes(_canonical_json_bytes(semantic_values)), actual_values

    def _execute(
        self,
        step: ExpectedGatewayStep,
        resolved: ResolvedGatewayInvocation,
        semantic_hash: str,
        *,
        execution_arguments: Sequence[str],
    ) -> dict[str, Any]:
        started = time.time()
        started_monotonic = time.monotonic()
        command = [
            str(self.trusted_python),
            str(self.runner_path),
            "gateway.py",
            *execution_arguments,
        ]
        exit_code: int | None = None
        stdout = ""
        stderr = ""
        failures: list[str] = []
        try:
            command[1] = str(self.runner_path.resolve(strict=True))
            runner_env = dict(self._runner_environment)
            for name in _BROKER_ENV_NAMES:
                runner_env.pop(name, None)
            runner_env[STATE_DIRECTORY_ENV] = str(self.state_directory)
            runner_env[EVIDENCE_DIRECTORY_ENV] = str(self.evidence_directory)
            runner_env[CONFIG_PATH_ENV] = str(self.config_path)
            shim_path = str(self.shim_directory)
            runner_env["PATH"] = os.pathsep.join(
                part
                for part in runner_env.get("PATH", os.defpath).split(os.pathsep)
                if part != shim_path
            )
            if self.trusted_step_pre_observer is not None:
                self.trusted_step_pre_observer(
                    step,
                    self.state_directory,
                    self.evidence_directory,
                )
            process = self._launch_runner(command, runner_env=runner_env)
            stdout, stderr = self._communicate_runner(process)
            exit_code = int(process.returncode)
            stdout = stdout or ""
            stderr = stderr or ""
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
            stderr_value = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr or ""
            stderr = stderr_value + "Packaged gateway runner timed out.\n"
            failures.append("packaged gateway runner timed out")
        except Exception as exc:  # noqa: BLE001 - runner launch failures must become durable evidence
            failures.append(f"packaged gateway runner failed: {type(exc).__name__}: {exc}")

        payload: Mapping[str, Any] | None = None
        if exit_code not in step.allowed_exit_codes:
            failures.append(
                f"packaged gateway runner exit {exit_code!r} is not allowed; "
                f"expected one of {step.allowed_exit_codes!r}"
            )
        try:
            payload = _extract_payload(stdout, required_contract=self.required_contract)
            if payload.get("contract") != self.required_contract:
                raise GatewayInvocationError(
                    f"gateway payload contract must be {self.required_contract!r}"
                )
            if payload.get("ok") is not True:
                raise GatewayInvocationError("gateway payload ok must be exactly true")
            if payload.get("command") != step.subcommand:
                raise GatewayInvocationError(
                    f"gateway payload command must be exactly {step.subcommand!r}"
                )
        except GatewayInvocationError as exc:
            failures.append(str(exc))
        except Exception as exc:  # noqa: BLE001 - malformed payload evidence must fail closed
            failures.append(f"unexpected gateway payload failure: {type(exc).__name__}: {exc}")

        payload_hash = ""
        if payload is not None:
            try:
                payload_hash = _sha256_bytes(_canonical_json_bytes(payload))
            except GatewayInvocationError as exc:
                failures.append(str(exc))
        if not failures and payload is not None and self.trusted_step_observer is not None:
            try:
                self.trusted_step_observer(
                    step,
                    MappingProxyType(dict(payload)),
                    self.state_directory,
                    self.evidence_directory,
                )
            except Exception as exc:  # noqa: BLE001 - observer failures must become durable evidence
                failures.append(
                    f"trusted step observer failed: {type(exc).__name__}: {exc}"
                )

        finished = time.time()
        payload_error = "; ".join(failures)
        response_stderr = stderr
        response_exit = exit_code if exit_code is not None else 125
        if payload_error:
            response_stderr += f"Gateway broker rejected runner evidence: {payload_error}\n"
            response_exit = 125

        record = GatewayBrokerRecord(
            sequence=0,
            step_name=step.name,
            authenticated=True,
            accepted=True,
            rejection="",
            model_argv=resolved.raw_model_argv,
            normalized_model_argv=resolved.normalized_model_argv,
            gateway_arguments=resolved.gateway_arguments,
            raw_argv_sha256=_argv_sha256(resolved.raw_model_argv),
            argv_sha256=resolved.argv_sha256,
            semantic_argv_sha256=semantic_hash,
            started_at_unix=started,
            finished_at_unix=finished,
            duration_seconds=time.monotonic() - started_monotonic,
            exit_code=response_exit,
            runner_exit_code=exit_code,
            stdout=stdout,
            stderr=response_stderr,
            payload=payload,
            payload_sha256=payload_hash,
            payload_error=payload_error,
            runner_command_sha256=_argv_sha256(command),
            allowed_exit_codes=step.allowed_exit_codes,
        )
        with self._lock:
            record = self._append_record_locked(record)
            if record.succeeded:
                self._payloads_by_step[step.name] = payload
                self._next_step += 1
                if self._next_step == len(self.expected_steps):
                    self._terminal_state = _BROKER_COMPLETE
            else:
                self._terminal_state = _BROKER_FAILED

        return {"exit_code": response_exit, "stdout": stdout, "stderr": response_stderr}

    def _reject(
        self,
        model_argv: Sequence[str],
        reason: str,
        *,
        authenticated: bool,
        response_exit: int = 126,
        payload_error: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            try:
                resolved = resolve_gateway_invocation(
                    model_argv,
                    skill_source=self.skill_source,
                    shim_directory=self.shim_directory,
                )
            except Exception:  # noqa: BLE001 - rejection evidence must never recurse into resolver failure
                resolved = None
            return self._reject_locked(
                resolved,
                reason,
                model_argv=model_argv,
                authenticated=authenticated,
                response_exit=response_exit,
                payload_error=payload_error,
            )

    def _reject_locked(
        self,
        resolved: ResolvedGatewayInvocation | None,
        reason: str,
        *,
        model_argv: Sequence[str] = (),
        authenticated: bool,
        response_exit: int = 126,
        payload_error: str = "",
    ) -> dict[str, Any]:
        if authenticated:
            self._terminal_state = _BROKER_FAILED
        now = time.time()
        normalized = resolved.normalized_model_argv if resolved is not None else ()
        raw = tuple(model_argv) if model_argv else normalized
        response_stderr = f"Gateway broker rejected command: {reason}\n"
        record = GatewayBrokerRecord(
            sequence=0,
            step_name=(
                self.expected_steps[self._next_step].name
                if self._next_step < len(self.expected_steps)
                else None
            ),
            authenticated=authenticated,
            accepted=False,
            rejection=reason,
            model_argv=raw,
            normalized_model_argv=normalized,
            gateway_arguments=resolved.gateway_arguments if resolved is not None else (),
            raw_argv_sha256=_argv_sha256(raw),
            argv_sha256=resolved.argv_sha256 if resolved is not None else _argv_sha256(raw),
            semantic_argv_sha256="",
            started_at_unix=now,
            finished_at_unix=now,
            duration_seconds=0.0,
            exit_code=response_exit,
            runner_exit_code=None,
            stdout="",
            stderr=response_stderr,
            payload=None,
            payload_sha256="",
            payload_error=payload_error,
            runner_command_sha256="",
            allowed_exit_codes=(),
        )
        self._append_record_locked(record)
        return {"exit_code": response_exit, "stdout": "", "stderr": response_stderr}

    def _append_record_locked(self, record: GatewayBrokerRecord) -> GatewayBrokerRecord:
        numbered = replace(record, sequence=len(self._records) + 1)
        self._records.append(numbered)
        return numbered


__all__ = [
    "BASH_ENV_NAME",
    "BROKER_ENDPOINT_ENV",
    "BROKER_TOKEN_ENV",
    "BROKER_TRANSPORT_ENV",
    "CodexGatewayBroker",
    "ExpectedGatewayStep",
    "GatewayBrokerError",
    "GatewayBrokerEvidence",
    "GatewayBrokerRecord",
    "GatewayBrokerReconciliation",
    "GatewayInvocationError",
    "ResolvedGatewayInvocation",
    "ResponseBinding",
    "SemanticJsonArgument",
    "TrustedStepObserver",
    "TrustedStepPreObserver",
    "reconcile_gateway_commands",
    "resolve_gateway_invocation",
]
