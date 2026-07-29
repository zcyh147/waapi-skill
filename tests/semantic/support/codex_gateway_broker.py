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
import math
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
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
TRANSACTION_CONFIRMATION_BINDING_CONTRACT = (
    "waapi-skill.confirmation-binding/v1"
)
CONFIRMATION_TOKEN_MATERIAL_CONTRACT = (
    "waapi-skill.confirmation-token-material/v1"
)
STATE_DIRECTORY_ENV = "WAAPI_SKILL_STATE_DIR"
EVIDENCE_DIRECTORY_ENV = "WWISE_EVIDENCE_DIR"
CONFIG_PATH_ENV = "WAAPI_SKILL_CONFIG_PATH"
BROKER_TRANSPORT_ENV = "WAAPI_CODEX_GATEWAY_BROKER_TRANSPORT"
BROKER_ENDPOINT_ENV = "WAAPI_CODEX_GATEWAY_BROKER_ENDPOINT"
BROKER_TOKEN_ENV = "WAAPI_CODEX_GATEWAY_BROKER_TOKEN"
GATEWAY_REQUIRED_ENV = "WAAPI_CODEX_GATEWAY_REQUIRED"
SUBSCRIPTION_ACK_CONTRACT = "waapi-skill.broker-subscription-ack/v2"
VALIDATED_SUBSCRIPTION_ACK_CONTRACT = (
    "waapi-skill.broker-validated-subscription-ack/v1"
)
SUBSCRIPTION_ACK_PATH_ENV = "WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_PATH"
SUBSCRIPTION_ACK_NONCE_ENV = "WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_NONCE"
SUBSCRIPTION_ACK_TOPIC_ENV = "WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_TOPIC"
SUBSCRIPTION_ACK_STEP_ENV = "WAAPI_SKILL_BROKER_SUBSCRIPTION_ACK_STEP"
BASH_ENV_NAME = "BASH_ENV"
_SUBSCRIPTION_ACK_ENV_NAMES = frozenset(
    {
        SUBSCRIPTION_ACK_PATH_ENV,
        SUBSCRIPTION_ACK_NONCE_ENV,
        SUBSCRIPTION_ACK_TOPIC_ENV,
        SUBSCRIPTION_ACK_STEP_ENV,
    }
)
_BROKER_ENV_NAMES = frozenset(
    {
        BROKER_TRANSPORT_ENV,
        BROKER_ENDPOINT_ENV,
        BROKER_TOKEN_ENV,
        GATEWAY_REQUIRED_ENV,
        BASH_ENV_NAME,
        CONFIG_PATH_ENV,
        *_SUBSCRIPTION_ACK_ENV_NAMES,
    }
)
_PYTHON_NAMES = frozenset({"python", "python3"})
_SUPPORTED_WWISE_VERSIONS = frozenset({"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"})
_BROKER_READY = "READY"
_BROKER_RUNNING = "RUNNING"
_BROKER_FAILED = "FAILED"
_BROKER_COMPLETE = "COMPLETE"
_BROKER_INDETERMINATE = "INDETERMINATE"
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
_SHIM_RESPONSE_GRACE_SECONDS = 15.0
_SHIM_OUTPUT_ARM_SECONDS = 0.25
_SHIM_OUTPUT_DRAIN_SECONDS = 0.25
_SUBSCRIPTION_ACK_MAX_BYTES = 4096
_SUBSCRIPTION_ACK_WAIT_SECONDS = 30.0
_SUBSCRIPTION_ACK_POLL_SECONDS = 0.01
_SUBSCRIPTION_ACK_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CROCKFORD_BASE32_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
_CONFIRMATION_TOKEN_RE = re.compile(
    rf"^ct1-[{_CROCKFORD_BASE32_ALPHABET}]{{24}}$"
)
_AUDIO_IMPORT_SCALAR_ROW_FIELDS = frozenset(
    {
        "object_path",
        "object_type",
        "audio_file",
        "audio_file_base64",
        "import_language",
        "originals_subfolder",
        "notes",
        "audio_source_notes",
        "dialogue_event",
        "switch_assignment",
    }
)
_AUDIO_IMPORT_STRUCTURED_ROW_FIELDS = frozenset(
    {
        "import_location",
        "event",
    }
)
_AUDIO_IMPORT_NAMED_ROW_FIELDS = frozenset(
    {
        "properties",
        "references",
    }
)
_AUDIO_IMPORT_FIXED_ROW_FIELDS = (
    _AUDIO_IMPORT_SCALAR_ROW_FIELDS
    | _AUDIO_IMPORT_STRUCTURED_ROW_FIELDS
)
_AUDIO_IMPORT_DEFAULTABLE_ROW_FIELDS = (
    _AUDIO_IMPORT_FIXED_ROW_FIELDS
    | _AUDIO_IMPORT_NAMED_ROW_FIELDS
)
_AUDIO_IMPORT_NON_EMPTY_SCALAR_ROW_FIELDS = frozenset(
    {
        "object_path",
        "object_type",
        "audio_file",
        "audio_file_base64",
        "import_language",
        "originals_subfolder",
        "dialogue_event",
        "switch_assignment",
    }
)
_AUDIO_IMPORT_SCALAR_ROW_FIELD_LIMITS = MappingProxyType(
    {
        "object_type": 128,
        "audio_file_base64": 256 * 1024,
        "originals_subfolder": 512,
        "notes": 16 * 1024,
        "audio_source_notes": 16 * 1024,
        "dialogue_event": 16 * 1024,
        "switch_assignment": 16 * 1024,
    }
)
_AUDIO_IMPORT_EVENT_ACTIONS = frozenset(
    {"Play", "Stop", "Pause", "Resume", "Break", "Seek"}
)
_AUDIO_IMPORT_TAB_REQUIRED_ARGUMENT_FIELDS = frozenset(
    {"import_file", "import_location", "import_language"}
)
_AUDIO_IMPORT_TAB_OPTIONAL_ARGUMENT_FIELDS = frozenset(
    {
        "import_operation",
        "auto_add_to_source_control",
        "auto_check_out_to_source_control",
    }
)
_AUDIO_IMPORT_TAB_OPERATIONS = frozenset(
    {"createNew", "useExisting", "replaceExisting"}
)
_AUDIO_IMPORT_TAB_AUTO_CHECK_OUT_VERSIONS = frozenset(
    {"2023.1", "2024.1", "2025.1"}
)
_OBJECT_SET_ARGUMENT_FIELDS = frozenset(
    {
        "objects",
        "platform",
        "list_mode",
        "on_name_conflict",
        "auto_add_to_source_control",
    }
)
_OBJECT_SET_SUPPORTED_VERSIONS = frozenset(
    {"2022.1", "2023.1", "2024.1", "2025.1"}
)
_OBJECT_SET_SCHEMA_DEFAULTS = MappingProxyType(
    {
        "list_mode": "append",
        "on_name_conflict": "fail",
        "auto_add_to_source_control": False,
    }
)
_SOUNDBANK_GENERATE_DEFAULT_FALSE_ARGUMENT_FIELDS = (
    "rebuild_soundbanks",
    "clear_audio_file_cache",
    "rebuild_init_bank",
)


class GatewayBrokerError(RuntimeError):
    """Base error for broker configuration and lifecycle failures."""


class GatewayInvocationError(GatewayBrokerError, ValueError):
    """The model command is not the exact packaged gateway invocation."""


@dataclass(frozen=True, slots=True)
class SemanticJsonArgument:
    """One argv value compared by a closed JSON equivalence contract."""

    expected: Any
    equivalence: str = "wire_exact"

    def __post_init__(self) -> None:
        if self.equivalence not in {
            "wire_exact",
            "object_operation_v1",
            "soundbank_generate_v1",
        }:
            raise ValueError(
                "SemanticJsonArgument.equivalence must be wire_exact, "
                "object_operation_v1, or soundbank_generate_v1"
            )
        if self.equivalence == "soundbank_generate_v1":
            try:
                _normalize_soundbank_generate_request(self.expected)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "soundbank_generate_v1 requires one valid "
                    "soundbank.generate request"
                ) from exc


@dataclass(frozen=True, slots=True)
class MetadataQueryArgument:
    """One bounded natural-language query in a metadata-discover step.

    The business prompt may lead two fresh agents to phrase the same lookup
    differently.  Mutation authority therefore comes from the exact live
    candidate tokens used later, not from requiring one magic search phrase.
    """

    label: str
    maximum_chars: int = 160

    def __post_init__(self) -> None:
        if (
            isinstance(self.maximum_chars, bool)
            or not isinstance(self.maximum_chars, int)
            or not 1 <= self.maximum_chars <= 160
        ):
            raise ValueError(
                "MetadataQueryArgument.maximum_chars must be an integer from 1 through 160"
            )
        if (
            not isinstance(self.label, str)
            or not self.label
            or self.label != self.label.strip()
            or len(self.label) > self.maximum_chars
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in self.label
            )
        ):
            raise ValueError(
                "MetadataQueryArgument.label must be bounded natural-language text"
            )


@dataclass(frozen=True, slots=True)
class MetadataTokenProjection:
    """Stable live metadata fields for one mutation-relevant exact token."""

    name: str
    kind: str
    metadata_type: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or not self.name
            or self.name != self.name.strip()
            or len(self.name) > 256
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in self.name
            )
        ):
            raise ValueError(
                "MetadataTokenProjection.name must be one bounded exact value"
            )
        if self.name.startswith("@"):
            raise ValueError(
                "MetadataTokenProjection.name must omit the native @ prefix"
            )
        if self.kind not in {"property", "reference"}:
            raise ValueError(
                "MetadataTokenProjection.kind must be property or reference"
            )
        if (
            not isinstance(self.metadata_type, str)
            or self.metadata_type != self.metadata_type.strip()
            or len(self.metadata_type) > 256
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in self.metadata_type
            )
            or self.kind == "property"
            and not self.metadata_type
        ):
            raise ValueError(
                "MetadataTokenProjection.metadata_type must be bounded; "
                "only live references may omit it"
            )

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "kind": self.kind,
            "metadata_type": self.metadata_type,
        }


@dataclass(frozen=True, slots=True)
class MetadataBoundJsonArgument:
    """Request JSON whose dynamic names must come from one prior read."""

    expected: Any
    metadata_step: str
    object_type: str
    required_tokens: tuple[str, ...]
    expected_required_token_projection: (
        tuple[MetadataTokenProjection, ...] | None
    ) = None
    equivalence: str = "wire_exact"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.metadata_step, str)
            or not self.metadata_step
            or self.metadata_step != self.metadata_step.strip()
            or len(self.metadata_step) > 160
        ):
            raise ValueError(
                "MetadataBoundJsonArgument.metadata_step must be non-empty"
            )
        if (
            not isinstance(self.object_type, str)
            or not self.object_type
            or self.object_type != self.object_type.strip()
            or len(self.object_type) > 256
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in self.object_type
            )
        ):
            raise ValueError(
                "MetadataBoundJsonArgument.object_type must be one bounded exact name"
            )
        if (
            not self.required_tokens
            or any(
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or value.startswith("@")
                or len(value) > 256
                or any(
                    ord(character) < 32 or ord(character) == 127
                    for character in value
                )
                for value in self.required_tokens
            )
            or len(self.required_tokens)
            != len({value.casefold() for value in self.required_tokens})
        ):
            raise ValueError(
                "MetadataBoundJsonArgument.required_tokens must be unique exact live names"
            )
        projection = self.expected_required_token_projection
        if projection is not None and (
            not isinstance(projection, tuple)
            or any(
                not isinstance(item, MetadataTokenProjection)
                for item in projection
            )
            or tuple(item.name for item in projection)
            != self.required_tokens
        ):
            raise ValueError(
                "MetadataBoundJsonArgument expected projection must match required_tokens in order"
            )
        if self.equivalence not in {
            "wire_exact",
            "audio_import_v1",
            "audio_import_tab_v1",
            "object_set_v1",
        }:
            raise ValueError(
                "MetadataBoundJsonArgument.equivalence must be "
                "wire_exact, audio_import_v1, audio_import_tab_v1, "
                "or object_set_v1"
            )
        if self.equivalence == "audio_import_v1":
            try:
                normalized = _normalize_audio_import_request(self.expected)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "audio_import_v1 requires one valid audio.import request"
                ) from exc
            request_tokens = _audio_import_field_names(normalized)
            if not request_tokens.issubset(set(self.required_tokens)):
                raise ValueError(
                    "audio_import_v1 request field names must be bound to "
                    "required live metadata tokens"
                )
        elif self.equivalence == "audio_import_tab_v1":
            try:
                _normalize_audio_import_tab_request(self.expected)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "audio_import_tab_v1 requires one valid "
                    "audio.importTabDelimited request"
                ) from exc
        elif self.equivalence == "object_set_v1":
            try:
                _normalize_object_set_request(self.expected)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "object_set_v1 requires one valid object.set request"
                ) from exc


@dataclass(frozen=True, slots=True)
class ResponseBinding:
    """Bind one argv value to a JSON field returned by an earlier step.

    ``pointer`` is an RFC 6901 JSON pointer.  Examples include
    ``/transaction_id`` and the nested ``/confirmation/token``.
    """

    step: str
    pointer: str


ExpectedArgument = (
    str
    | SemanticJsonArgument
    | MetadataQueryArgument
    | MetadataBoundJsonArgument
    | ResponseBinding
)


@dataclass(frozen=True, slots=True)
class ExpectedGatewayStep:
    """One exact, ordered packaged gateway invocation."""

    name: str
    subcommand: str
    arguments: tuple[ExpectedArgument, ...] = ()
    allowed_exit_codes: tuple[int, ...] = (0,)
    gateway_global_arguments: tuple[str, ...] = ()
    allow_omitted_empty_json_objects: bool = False
    allow_omitted_default_event_count_one: bool = False
    expected_error_code: str = ""
    expected_result_command: str = ""
    terminal_execute: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("ExpectedGatewayStep.name must be non-empty")
        if not self.subcommand or not self.subcommand.strip():
            raise ValueError("ExpectedGatewayStep.subcommand must be non-empty")
        if type(self.allow_omitted_default_event_count_one) is not bool:
            raise ValueError(
                "ExpectedGatewayStep.allow_omitted_default_event_count_one must be a bool"
            )
        allowed_shapes = {(0,), (2,), (0, 2)}
        if self.allowed_exit_codes not in allowed_shapes:
            raise ValueError(
                "ExpectedGatewayStep.allowed_exit_codes must be exactly (0,), the "
                "explicit structured-error form (2,), or the terminal-disconnect "
                "form (0, 2)"
            )
        if self.terminal_execute:
            if self.subcommand != "execute":
                raise ValueError(
                    "terminal_execute is valid only for execute"
                )
            if self.allowed_exit_codes != (0, 2):
                raise ValueError(
                    "terminal_execute requires allowed_exit_codes=(0, 2)"
                )
            if self.expected_error_code or self.expected_result_command:
                raise ValueError(
                    "terminal disconnect cannot also declare a structured error"
                )
        elif self.allowed_exit_codes == (0, 2) and self.subcommand != "execute":
            raise ValueError(
                "allowed_exit_codes=(0, 2) is valid only for execute"
            )
        if self.allowed_exit_codes == (2,):
            if not self.expected_error_code or not self.expected_error_code.strip():
                raise ValueError(
                    "exit 2 requires a non-empty ExpectedGatewayStep.expected_error_code"
                )
            if not self.expected_result_command or not self.expected_result_command.strip():
                raise ValueError(
                    "exit 2 requires a non-empty ExpectedGatewayStep.expected_result_command"
                )
        elif (
            not self.terminal_execute
            and (self.expected_error_code or self.expected_result_command)
        ):
            raise ValueError(
                "structured error expectations are valid only when allowed_exit_codes is (2,)"
            )
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
        if self.allow_omitted_default_event_count_one:
            event_count_indexes = tuple(
                index
                for index, argument in enumerate(self.arguments)
                if argument == "--event-count"
            )
            has_joined_event_count = any(
                isinstance(argument, str)
                and argument.startswith("--event-count=")
                for argument in self.arguments
            )
            expected_shape = (
                self.subcommand == "wait-topic"
                and len(event_count_indexes) == 1
                and event_count_indexes[0] + 1 < len(self.arguments)
                and self.arguments[event_count_indexes[0] + 1] == "1"
                and not has_joined_event_count
            )
            if not expected_shape:
                raise ValueError(
                    "allow_omitted_default_event_count_one requires a wait-topic "
                    "step containing exactly the canonical --event-count 1 pair"
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
class TrustedSubscriptionAckSpec:
    """One broker-owned wait-topic step that requires a post-subscribe ACK."""

    step_name: str
    topic: str

    def __post_init__(self) -> None:
        if not isinstance(self.step_name, str) or not self.step_name.strip():
            raise ValueError("TrustedSubscriptionAckSpec.step_name must be non-empty")
        if not isinstance(self.topic, str) or not self.topic.strip():
            raise ValueError("TrustedSubscriptionAckSpec.topic must be non-empty")


@dataclass(frozen=True, slots=True)
class TrustedSubscriptionAckExpectation:
    """Non-secret ACK view delivered to a trusted publisher observer.

    The raw nonce remains broker-private and is injected only into the exact
    packaged gateway child.  A publisher can authenticate a completed ACK by
    hashing the nonce found in that file, but cannot pre-create the file from
    this observer view.
    """

    contract: str
    step_name: str
    topic: str
    path: Path
    nonce_sha256: str


@dataclass(frozen=True, slots=True)
class _TrustedSubscriptionAckCredential:
    """Broker-private raw credential for one exact wait-topic step."""

    expectation: TrustedSubscriptionAckExpectation
    nonce: str


TrustedSubscriptionAckObserver = Callable[
    [TrustedSubscriptionAckExpectation],
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
    started_at_unix_ns: int = 0
    finished_at_unix_ns: int = 0
    subscription_ack: Mapping[str, Any] | None = None

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

    @property
    def terminal_indeterminate(self) -> bool:
        """Whether an exact ordinary execute ended the protocol ambiguously.

        This is a valid, non-retryable protocol branch, not a passing business
        outcome.  The successful transaction path still has to consume its
        later ``verify`` step and reach ``COMPLETE``.
        """

        if (
            self.terminal_state != _BROKER_INDETERMINATE
            or self.complete
            or not self.records
            or len(self.records) != len(self.consumed_step_names)
            or self.rejected_records
            or not all(record.succeeded for record in self.records)
        ):
            return False
        final = self.records[-1]
        return (
            final.step_name == self.consumed_step_names[-1]
            and final.runner_exit_code == 2
            and isinstance(final.payload, Mapping)
            and _is_exact_indeterminate_execute_payload(
                final.payload,
                exit_code=final.runner_exit_code,
            )
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


def _query_object_return_field_value_indexes(
    supplied_arguments: Sequence[str],
    expected_arguments: Sequence[ExpectedArgument],
) -> frozenset[int]:
    """Validate unordered ``query-object --return-field`` projections.

    The repeated option positions remain exact.  Only their values may be
    permuted, and both sides must describe the same non-empty, duplicate-free
    field set.
    """

    expected_option_indexes = tuple(
        index
        for index, value in enumerate(expected_arguments)
        if value == "--return-field"
    )
    if not expected_option_indexes:
        return frozenset()

    supplied_option_indexes = tuple(
        index
        for index, value in enumerate(supplied_arguments)
        if value == "--return-field"
    )
    if supplied_option_indexes != expected_option_indexes:
        raise GatewayInvocationError(
            "query-object --return-field option positions must match the allow-list"
        )
    if any(index + 1 >= len(expected_arguments) for index in expected_option_indexes):
        raise GatewayInvocationError(
            "query-object allow-listed --return-field values must be present"
        )

    expected_fields = tuple(
        expected_arguments[index + 1] for index in expected_option_indexes
    )
    supplied_fields = tuple(
        supplied_arguments[index + 1] for index in supplied_option_indexes
    )
    if any(
        not isinstance(field, str) or not field.strip()
        for field in expected_fields
    ):
        raise GatewayInvocationError(
            "query-object allow-listed --return-field values must be non-empty strings"
        )
    if any(not field.strip() for field in supplied_fields):
        raise GatewayInvocationError(
            "query-object supplied --return-field values must be non-empty strings"
        )
    if len(set(expected_fields)) != len(expected_fields):
        raise GatewayInvocationError(
            "query-object allow-listed --return-field values must not contain duplicates"
        )
    if len(set(supplied_fields)) != len(supplied_fields):
        raise GatewayInvocationError(
            "query-object supplied --return-field values must not contain duplicates"
        )
    if set(supplied_fields) != set(expected_fields):
        raise GatewayInvocationError(
            "query-object supplied --return-field set must match the allow-list"
        )
    return frozenset(index + 1 for index in expected_option_indexes)


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


def _encode_crockford_120(value: int) -> str:
    """Encode one 120-bit confirmation digest prefix independently."""

    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 1 << 120:
        raise GatewayInvocationError("confirmation token digest is outside 120 bits")
    encoded = ["0"] * 24
    for index in range(23, -1, -1):
        encoded[index] = _CROCKFORD_BASE32_ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(encoded)


def validate_transaction_show_confirmation_payload(
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate one complete state-bound ``transaction-show`` confirmation.

    The broker deliberately derives the expected token independently from the
    public binding fields.  A scalar at ``/confirmation/token`` is insufficient:
    the contract, immutable artifact, awaiting state, and exact journal head
    must all form one closed binding before a later confirm argv may consume it.
    """

    transaction_id = payload.get("transaction_id")
    artifact_hash = payload.get("artifact_hash")
    state = payload.get("state")
    confirmation = payload.get("confirmation")
    if (
        not isinstance(transaction_id, str)
        or not transaction_id
        or not isinstance(artifact_hash, str)
        or _SHA256_RE.fullmatch(artifact_hash) is None
        or state != "awaiting_confirmation"
        or not isinstance(confirmation, Mapping)
        or set(confirmation) != {"contract", "token", "binding"}
    ):
        raise GatewayInvocationError(
            "transaction-show lacks a complete awaiting-confirmation binding"
        )
    token = confirmation.get("token")
    binding = confirmation.get("binding")
    if (
        confirmation.get("contract")
        != TRANSACTION_CONFIRMATION_BINDING_CONTRACT
        or not isinstance(token, str)
        or _CONFIRMATION_TOKEN_RE.fullmatch(token) is None
        or not isinstance(binding, Mapping)
        or set(binding)
        != {
            "material_contract",
            "transaction_id",
            "artifact_hash",
            "state",
            "event_sequence",
            "last_event_hash",
        }
    ):
        raise GatewayInvocationError(
            "transaction-show confirmation contract or closed binding is invalid"
        )
    event_sequence = binding.get("event_sequence")
    last_event_hash = binding.get("last_event_hash")
    if (
        binding.get("material_contract")
        != CONFIRMATION_TOKEN_MATERIAL_CONTRACT
        or binding.get("transaction_id") != transaction_id
        or binding.get("artifact_hash") != artifact_hash
        or binding.get("state") != state
        or type(event_sequence) is not int
        or event_sequence < 1
        or not isinstance(last_event_hash, str)
        or _SHA256_RE.fullmatch(last_event_hash) is None
    ):
        raise GatewayInvocationError(
            "transaction-show confirmation binding differs from its response"
        )
    material = {
        "contract": CONFIRMATION_TOKEN_MATERIAL_CONTRACT,
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "state": state,
        "event_sequence": event_sequence,
        "last_event_hash": last_event_hash,
    }
    digest_prefix = hashlib.sha256(_canonical_json_bytes(material)).hexdigest()[:30]
    expected_token = "ct1-" + _encode_crockford_120(int(digest_prefix, 16))
    if not secrets.compare_digest(token, expected_token):
        raise GatewayInvocationError(
            "transaction-show confirmation token does not bind its journal head"
        )
    return MappingProxyType(
        {
            "contract": confirmation["contract"],
            "token": token,
            "binding": MappingProxyType(dict(binding)),
        }
    )


def _semantic_json_equal(actual: Any, expected: SemanticJsonArgument) -> bool:
    if expected.equivalence == "wire_exact":
        return _canonical_json_bytes(actual) == _canonical_json_bytes(
            expected.expected
        )
    if expected.equivalence == "soundbank_generate_v1":
        try:
            normalized_actual = _normalize_soundbank_generate_request(actual)
            normalized_expected = _normalize_soundbank_generate_request(
                expected.expected
            )
        except (TypeError, ValueError):
            return False
        return _canonical_json_bytes(
            normalized_actual
        ) == _canonical_json_bytes(normalized_expected)
    return _object_operation_json_equal(actual, expected.expected)


def _normalize_soundbank_generate_request(value: Any) -> dict[str, Any]:
    """Insert only reviewed false defaults at their original schema scopes.

    A per-Bank ``rebuild`` value is never promoted to or replaced by the
    batch-wide ``rebuild_soundbanks`` value.  Every non-default field remains
    wire-significant after this narrow normalization.
    """

    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or set(value)
        != {"contract", "version", "operation", "arguments"}
        or value.get("contract") != "waapi-skill.operation-request/v1"
        or value.get("version") not in _SUPPORTED_WWISE_VERSIONS
        or value.get("operation") != "soundbank.generate"
    ):
        raise ValueError(
            "soundbank_generate_v1 requires one closed "
            "soundbank.generate request"
        )
    arguments = value.get("arguments")
    if (
        not isinstance(arguments, Mapping)
        or not all(isinstance(key, str) for key in arguments)
    ):
        raise ValueError(
            "soundbank_generate_v1 arguments must be one JSON object"
        )
    for field in _SOUNDBANK_GENERATE_DEFAULT_FALSE_ARGUMENT_FIELDS:
        if field in arguments and type(arguments[field]) is not bool:
            raise ValueError(
                f"soundbank_generate_v1 {field} must be a JSON boolean"
            )

    soundbanks = arguments.get("soundbanks")
    if not isinstance(soundbanks, list) or not soundbanks:
        raise ValueError(
            "soundbank_generate_v1 requires a non-empty soundbanks array"
        )
    normalized_soundbanks: list[dict[str, Any]] = []
    for row in soundbanks:
        if (
            not isinstance(row, Mapping)
            or not all(isinstance(key, str) for key in row)
            or (
                "rebuild" in row
                and type(row["rebuild"]) is not bool
            )
        ):
            raise ValueError(
                "soundbank_generate_v1 SoundBank rows must be JSON objects "
                "with boolean rebuild values"
            )
        normalized_row = dict(row)
        normalized_row.setdefault("rebuild", False)
        normalized_soundbanks.append(normalized_row)

    normalized_arguments = dict(arguments)
    normalized_arguments["soundbanks"] = normalized_soundbanks
    for field in _SOUNDBANK_GENERATE_DEFAULT_FALSE_ARGUMENT_FIELDS:
        normalized_arguments.setdefault(field, False)
    normalized = dict(value)
    normalized["arguments"] = normalized_arguments
    return normalized


def _metadata_bound_json_equal(
    actual: Any,
    expected: MetadataBoundJsonArgument,
) -> bool:
    if expected.equivalence == "wire_exact":
        return _canonical_json_bytes(actual) == _canonical_json_bytes(
            expected.expected
        )
    try:
        if expected.equivalence == "audio_import_v1":
            if not _audio_import_actual_defaults_are_expected_subset(
                actual,
                expected.expected,
            ):
                return False
            normalized_actual = _normalize_audio_import_request(actual)
            normalized_expected = _normalize_audio_import_request(
                expected.expected
            )
        elif expected.equivalence == "object_set_v1":
            normalized_actual = _normalize_metadata_bound_object_set_request(
                actual,
                expected,
            )
            normalized_expected = (
                _normalize_metadata_bound_object_set_request(
                    expected.expected,
                    expected,
                )
            )
        else:
            normalized_actual = _normalize_audio_import_tab_request(actual)
            normalized_expected = _normalize_audio_import_tab_request(
                expected.expected
            )
    except (TypeError, ValueError):
        return False
    return _canonical_json_bytes(
        normalized_actual
    ) == _canonical_json_bytes(normalized_expected)


def _metadata_bound_semantic_value(
    actual: Any,
    expected: MetadataBoundJsonArgument,
) -> Any:
    if expected.equivalence == "audio_import_v1":
        return _normalize_audio_import_request(actual)
    if expected.equivalence == "audio_import_tab_v1":
        return _normalize_audio_import_tab_request(actual)
    if expected.equivalence == "object_set_v1":
        return _normalize_metadata_bound_object_set_request(actual, expected)
    return actual


def _normalize_object_set_request(value: Any) -> dict[str, Any]:
    """Remove only reviewed root defaults declared by the object.set schema.

    The equivalence intentionally does not inherit the broader object-operation
    matcher. Nested row defaults, ``on_name_conflict``, integer-property numeric
    types, and empty collections all remain wire-significant. A later
    metadata-bound pass normalizes only equal JSON integer/float spellings for
    properties proven by live metadata to be real-valued.
    """

    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or set(value)
        != {"contract", "version", "operation", "arguments"}
        or value.get("contract") != "waapi-skill.operation-request/v1"
        or value.get("version") not in _OBJECT_SET_SUPPORTED_VERSIONS
        or value.get("operation") != "object.set"
    ):
        raise ValueError(
            "object_set_v1 requires one closed object.set request"
        )
    arguments = value.get("arguments")
    if (
        not isinstance(arguments, Mapping)
        or not all(isinstance(key, str) for key in arguments)
        or set(arguments) - _OBJECT_SET_ARGUMENT_FIELDS
    ):
        raise ValueError("object_set_v1 arguments are not closed")
    objects = arguments.get("objects")
    if (
        not isinstance(objects, list)
        or not objects
        or any(
            not isinstance(item, Mapping)
            or not all(isinstance(key, str) for key in item)
            for item in objects
        )
    ):
        raise ValueError(
            "object_set_v1 requires a non-empty objects array"
        )
    if (
        "platform" in arguments
        and (
            not isinstance(arguments["platform"], str)
            or not arguments["platform"]
        )
    ):
        raise ValueError("object_set_v1 platform is invalid")
    if (
        "list_mode" in arguments
        and arguments["list_mode"] not in {"append", "replaceAll"}
    ):
        raise ValueError("object_set_v1 list_mode is invalid")
    if (
        "on_name_conflict" in arguments
        and arguments["on_name_conflict"]
        not in {"fail", "rename", "merge"}
    ):
        raise ValueError("object_set_v1 on_name_conflict is invalid")
    if (
        "auto_add_to_source_control" in arguments
        and type(arguments["auto_add_to_source_control"]) is not bool
    ):
        raise ValueError(
            "object_set_v1 auto_add_to_source_control must be a JSON boolean"
        )

    normalized_arguments = dict(arguments)
    for field, default in _OBJECT_SET_SCHEMA_DEFAULTS.items():
        if (
            field in normalized_arguments
            and type(normalized_arguments[field]) is type(default)
            and normalized_arguments[field] == default
        ):
            normalized_arguments.pop(field)
    normalized = dict(value)
    normalized["arguments"] = normalized_arguments
    return normalized


def _normalize_metadata_bound_object_set_request(
    value: Any,
    expected: MetadataBoundJsonArgument,
) -> dict[str, Any]:
    """Canonicalize equal spellings only for live-proven real properties."""

    normalized = _normalize_object_set_request(value)
    projection = expected.expected_required_token_projection
    if projection is None:
        return normalized
    real_property_names = {
        item.name
        for item in projection
        if item.kind == "property"
        and item.metadata_type.casefold()
        in {"real32", "real64", "float", "double"}
    }
    if not real_property_names:
        return normalized

    def visit(item: Any) -> Any:
        if isinstance(item, list):
            return [visit(child) for child in item]
        if not isinstance(item, Mapping):
            return item
        result = {key: visit(child) for key, child in item.items()}
        properties = result.get("properties")
        if not isinstance(properties, list):
            return result
        normalized_properties: list[Any] = []
        for descriptor in properties:
            if not isinstance(descriptor, Mapping):
                normalized_properties.append(descriptor)
                continue
            row = dict(descriptor)
            property_value = row.get("value")
            if (
                row.get("name") in real_property_names
                and type(property_value) is int
            ):
                try:
                    converted = float(property_value)
                except (OverflowError, ValueError):
                    converted = None
                if (
                    converted is not None
                    and math.isfinite(converted)
                    and converted == property_value
                ):
                    row["value"] = converted
            normalized_properties.append(row)
        result["properties"] = normalized_properties
        return result

    canonical = visit(normalized)
    assert isinstance(canonical, dict)
    return canonical


def _normalize_audio_import_tab_request(value: Any) -> dict[str, Any]:
    """Normalize only schema-declared no-op tab-import defaults.

    Every business-bearing field remains wire-exact.  Wwise 2021.1/2022.1 do
    not expose ``auto_check_out_to_source_control`` at all, so even an explicit
    false value is rejected in those lanes rather than normalized away.
    """

    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or set(value)
        != {"contract", "version", "operation", "arguments"}
        or value.get("contract") != "waapi-skill.operation-request/v1"
        or value.get("operation") != "audio.importTabDelimited"
    ):
        raise ValueError(
            "audio_import_tab_v1 requires one closed "
            "audio.importTabDelimited request"
        )
    version = value.get("version")
    if version not in _SUPPORTED_WWISE_VERSIONS:
        raise ValueError(
            "audio_import_tab_v1 requires one supported Wwise version"
        )
    arguments = value.get("arguments")
    if (
        not isinstance(arguments, Mapping)
        or not all(isinstance(key, str) for key in arguments)
        or not _AUDIO_IMPORT_TAB_REQUIRED_ARGUMENT_FIELDS.issubset(arguments)
        or set(arguments)
        - (
            _AUDIO_IMPORT_TAB_REQUIRED_ARGUMENT_FIELDS
            | _AUDIO_IMPORT_TAB_OPTIONAL_ARGUMENT_FIELDS
        )
    ):
        raise ValueError(
            "audio_import_tab_v1 arguments are not closed"
        )
    if (
        not isinstance(arguments.get("import_file"), str)
        or not arguments["import_file"]
        or "\x00" in arguments["import_file"]
        or not _is_audio_import_identity(arguments.get("import_location"))
        or not isinstance(arguments.get("import_language"), str)
        or not arguments["import_language"]
        or arguments["import_language"]
        != arguments["import_language"].strip()
        or "\x00" in arguments["import_language"]
    ):
        raise ValueError(
            "audio_import_tab_v1 required arguments are invalid"
        )
    if (
        "import_operation" in arguments
        and arguments["import_operation"] not in _AUDIO_IMPORT_TAB_OPERATIONS
    ):
        raise ValueError(
            "audio_import_tab_v1 import_operation is invalid"
        )
    for field in (
        "auto_add_to_source_control",
        "auto_check_out_to_source_control",
    ):
        if field in arguments and type(arguments[field]) is not bool:
            raise ValueError(
                f"audio_import_tab_v1 {field} must be a JSON boolean"
            )
    if (
        version not in _AUDIO_IMPORT_TAB_AUTO_CHECK_OUT_VERSIONS
        and "auto_check_out_to_source_control" in arguments
    ):
        raise ValueError(
            "audio_import_tab_v1 auto_check_out_to_source_control is "
            "unsupported in this Wwise version"
        )

    normalized_arguments = dict(arguments)
    normalized_arguments.setdefault("import_operation", "createNew")
    normalized_arguments.setdefault("auto_add_to_source_control", False)
    if version in _AUDIO_IMPORT_TAB_AUTO_CHECK_OUT_VERSIONS:
        normalized_arguments.setdefault(
            "auto_check_out_to_source_control",
            False,
        )
    normalized = dict(value)
    normalized["arguments"] = normalized_arguments
    return normalized


def _audio_import_actual_defaults_are_expected_subset(
    actual: Any,
    expected: Any,
) -> bool:
    """Permit trusted defaults to remain or expand, never to be refactored."""

    actual_properties, actual_references = (
        _audio_import_default_named_fields(actual)
    )
    expected_properties, expected_references = (
        _audio_import_default_named_fields(expected)
    )
    for actual_fields, expected_fields in (
        (actual_properties, expected_properties),
        (actual_references, expected_references),
    ):
        if any(
            name not in expected_fields
            or _canonical_json_bytes(item)
            != _canonical_json_bytes(expected_fields[name])
            for name, item in actual_fields.items()
        ):
            return False
    return True


def _audio_import_default_named_fields(
    request: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(request, Mapping):
        raise ValueError("audio_import_v1 request must be an object")
    arguments = request.get("arguments")
    if not isinstance(arguments, Mapping):
        raise ValueError("audio_import_v1 arguments must be an object")
    defaults = arguments.get("defaults", {})
    if not isinstance(defaults, Mapping):
        raise ValueError("audio_import_v1 defaults must be an object")
    return (
        _named_audio_import_fields(
            defaults.get("properties", []),
            path="arguments.defaults.properties",
            kind="property",
        ),
        _named_audio_import_fields(
            defaults.get("references", []),
            path="arguments.defaults.references",
            kind="reference",
        ),
    )


def _normalize_audio_import_request(value: Any) -> dict[str, Any]:
    """Expand safe audio.import defaults into deterministic effective rows.

    ``properties`` and ``references`` are closed name-keyed collections.
    Defaults apply to every import row and an exact row name replaces the
    corresponding default item.  Their array order is immaterial, and the
    separate trusted-default subset check prevents an actual request from
    inventing dynamic defaults.  Closed non-named row fields use the public
    operation's ordinary default-then-row replacement semantics.  Every field
    outside the closed row schema remains invalid.
    """

    if (
        not isinstance(value, Mapping)
        or value.get("operation") != "audio.import"
        or not all(isinstance(key, str) for key in value)
    ):
        raise ValueError(
            "audio_import_v1 requires an audio.import request object"
        )
    arguments = value.get("arguments")
    if (
        not isinstance(arguments, Mapping)
        or not all(isinstance(key, str) for key in arguments)
    ):
        raise ValueError(
            "audio_import_v1 requires an arguments object"
        )
    imports = arguments.get("imports")
    if not isinstance(imports, list) or not imports:
        raise ValueError(
            "audio_import_v1 requires a non-empty imports array"
        )

    raw_defaults = arguments.get("defaults", {})
    if not isinstance(raw_defaults, Mapping) or not all(
        isinstance(key, str) for key in raw_defaults
    ):
        raise ValueError(
            "audio_import_v1 defaults must be an object"
        )
    _validate_audio_import_row_scope(
        raw_defaults,
        path="arguments.defaults",
    )
    fixed_defaults = {
        key: raw_defaults[key]
        for key in raw_defaults
        if key in _AUDIO_IMPORT_FIXED_ROW_FIELDS
    }
    default_properties = _named_audio_import_fields(
        raw_defaults.get("properties", []),
        path="arguments.defaults.properties",
        kind="property",
    )
    default_references = _named_audio_import_fields(
        raw_defaults.get("references", []),
        path="arguments.defaults.references",
        kind="reference",
    )
    _reject_cross_kind_audio_import_names(
        default_properties,
        default_references,
        path="arguments.defaults",
    )

    normalized_request = dict(value)
    normalized_arguments = dict(arguments)
    normalized_defaults = {
        key: item
        for key, item in raw_defaults.items()
        if key not in _AUDIO_IMPORT_FIXED_ROW_FIELDS
    }
    normalized_defaults.pop("properties", None)
    normalized_defaults.pop("references", None)
    if normalized_defaults:
        normalized_arguments["defaults"] = normalized_defaults
    else:
        normalized_arguments.pop("defaults", None)

    normalized_imports: list[dict[str, Any]] = []
    for index, raw_row in enumerate(imports):
        if not isinstance(raw_row, Mapping) or not all(
            isinstance(key, str) for key in raw_row
        ):
            raise ValueError(
                f"audio_import_v1 imports[{index}] must be an object"
            )
        _validate_audio_import_row_scope(
            raw_row,
            path=f"arguments.imports[{index}]",
        )
        row = {**fixed_defaults, **raw_row}
        row_properties = _named_audio_import_fields(
            row.get("properties", []),
            path=f"arguments.imports[{index}].properties",
            kind="property",
        )
        row_references = _named_audio_import_fields(
            row.get("references", []),
            path=f"arguments.imports[{index}].references",
            kind="reference",
        )
        _reject_cross_kind_audio_import_names(
            row_properties,
            row_references,
            path=f"arguments.imports[{index}]",
        )
        effective_properties = _merge_audio_import_fields(
            default_properties,
            row_properties,
            path=f"arguments.imports[{index}].properties",
        )
        effective_references = _merge_audio_import_fields(
            default_references,
            row_references,
            path=f"arguments.imports[{index}].references",
        )
        _reject_cross_kind_audio_import_names(
            effective_properties,
            effective_references,
            path=f"arguments.imports[{index}] effective fields",
        )
        if effective_properties:
            row["properties"] = [
                effective_properties[name]
                for name in sorted(effective_properties)
            ]
        else:
            row.pop("properties", None)
        if effective_references:
            row["references"] = [
                effective_references[name]
                for name in sorted(effective_references)
            ]
        else:
            row.pop("references", None)
        normalized_imports.append(row)

    normalized_arguments["imports"] = normalized_imports
    normalized_request["arguments"] = normalized_arguments
    return normalized_request


def _validate_audio_import_row_scope(
    value: Mapping[str, Any],
    *,
    path: str,
) -> None:
    unsupported = sorted(
        set(value) - _AUDIO_IMPORT_DEFAULTABLE_ROW_FIELDS
    )
    if unsupported:
        raise ValueError(
            f"audio_import_v1 {path} contains unsupported or case-mismatched "
            f"fields: {unsupported!r}"
        )
    for name in _AUDIO_IMPORT_SCALAR_ROW_FIELDS:
        if name not in value:
            continue
        item = value[name]
        if (
            not isinstance(item, str)
            or "\x00" in item
            or name in _AUDIO_IMPORT_NON_EMPTY_SCALAR_ROW_FIELDS
            and (
                not item
                or item != item.strip()
            )
        ):
            raise ValueError(
                f"audio_import_v1 {path}.{name} is not a valid string"
            )
        limit = _AUDIO_IMPORT_SCALAR_ROW_FIELD_LIMITS.get(name)
        if limit is not None and len(item) > limit:
            raise ValueError(
                f"audio_import_v1 {path}.{name} exceeds its closed limit"
            )
        if name in {"dialogue_event", "switch_assignment"} and any(
            character in item for character in ("\r", "\n", "\t")
        ):
            raise ValueError(
                f"audio_import_v1 {path}.{name} must be one line"
            )
    if (
        "import_location" in value
        and not _is_audio_import_identity(value["import_location"])
    ):
        raise ValueError(
            f"audio_import_v1 {path}.import_location is not a closed identity"
        )
    if "event" in value:
        event = value["event"]
        if (
            not isinstance(event, Mapping)
            or not all(isinstance(key, str) for key in event)
            or set(event) - {"path", "action"}
            or "path" not in event
            or not isinstance(event.get("path"), str)
            or not event["path"]
            or event["path"] != event["path"].strip()
            or "\x00" in event["path"]
            or not event["path"].startswith("\\Events\\")
            or (
                "action" in event
                and (
                    not isinstance(event["action"], str)
                    or event["action"] not in _AUDIO_IMPORT_EVENT_ACTIONS
                )
            )
        ):
            raise ValueError(
                f"audio_import_v1 {path}.event is not a closed event"
            )


def _named_audio_import_fields(
    value: Any,
    *,
    path: str,
    kind: str,
) -> dict[str, dict[str, Any]]:
    if kind not in {"property", "reference"}:
        raise AssertionError("audio import named-field kind is invalid")
    if not isinstance(value, list):
        raise ValueError(f"audio_import_v1 {path} must be an array")
    result: dict[str, dict[str, Any]] = {}
    folded_names: set[str] = set()
    for index, raw in enumerate(value):
        if (
            not isinstance(raw, Mapping)
            or not all(isinstance(key, str) for key in raw)
        ):
            raise ValueError(
                f"audio_import_v1 {path}[{index}] must be an object"
            )
        name = raw.get("name")
        if (
            not isinstance(name, str)
            or not name
            or name != name.strip()
            or name.startswith("@")
            or len(name) > 256
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in name
            )
        ):
            raise ValueError(
                f"audio_import_v1 {path}[{index}].name is invalid"
            )
        folded_name = name.casefold()
        if folded_name in folded_names:
            raise ValueError(
                f"audio_import_v1 {path} repeats name {name!r}"
            )
        if kind == "property":
            if set(raw) != {"name", "value"} or not _is_audio_import_property_value(
                raw.get("value")
            ):
                raise ValueError(
                    f"audio_import_v1 {path}[{index}] is not a closed property"
                )
        elif set(raw) != {"name", "target"} or not _is_audio_import_identity(
            raw.get("target")
        ):
            raise ValueError(
                f"audio_import_v1 {path}[{index}] is not a closed reference"
            )
        folded_names.add(folded_name)
        result[name] = dict(raw)
    return result


def _reject_cross_kind_audio_import_names(
    properties: Mapping[str, Any],
    references: Mapping[str, Any],
    *,
    path: str,
) -> None:
    overlap = {
        name.casefold() for name in properties
    } & {
        name.casefold() for name in references
    }
    if overlap:
        raise ValueError(
            f"audio_import_v1 {path} repeats names across properties "
            "and references"
        )


def _merge_audio_import_fields(
    defaults: Mapping[str, dict[str, Any]],
    row: Mapping[str, dict[str, Any]],
    *,
    path: str,
) -> dict[str, dict[str, Any]]:
    default_spelling = {
        name.casefold(): name for name in defaults
    }
    for name in row:
        prior = default_spelling.get(name.casefold())
        if prior is not None and prior != name:
            raise ValueError(
                f"audio_import_v1 {path} has a case-colliding "
                f"default/row name: {prior!r} and {name!r}"
            )
    return {**defaults, **row}


def _is_audio_import_property_value(value: Any) -> bool:
    if isinstance(value, (str, bool)):
        return True
    if isinstance(value, int) and not isinstance(value, bool):
        try:
            return math.isfinite(float(value))
        except OverflowError:
            return False
    return isinstance(value, float) and math.isfinite(value)


def _is_audio_import_identity(value: Any) -> bool:
    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
    ):
        return False
    kind = value.get("kind")
    if kind == "id" and set(value) == {"kind", "value"}:
        identity = value.get("value")
        return (
            isinstance(identity, str) and bool(identity)
        ) or (
            isinstance(identity, int) and not isinstance(identity, bool)
        )
    if kind in {"path", "waql"} and set(value) == {"kind", "value"}:
        return isinstance(value.get("value"), str) and bool(value["value"])
    if kind == "scoped-name" and set(value) == {
        "kind",
        "name",
        "type",
        "parent",
    }:
        parent = value.get("parent")
        return (
            isinstance(value.get("name"), str)
            and bool(value["name"])
            and isinstance(value.get("type"), str)
            and bool(value["type"])
            and isinstance(parent, Mapping)
            and parent.get("kind") in {"id", "path"}
            and _is_audio_import_identity(parent)
        )
    return False


def _audio_import_field_names(
    normalized_request: Mapping[str, Any],
) -> frozenset[str]:
    arguments = normalized_request["arguments"]
    result: set[str] = set()
    for row in arguments["imports"]:
        for key in ("properties", "references"):
            for item in row.get(key, []):
                result.add(item["name"])
    return frozenset(result)


def _validate_metadata_discover_query_arguments(
    step: ExpectedGatewayStep,
    supplied_arguments: Sequence[str],
) -> tuple[str, ...] | None:
    """Close the one flexible argv surface used by compound metadata reads."""

    query_specs = tuple(
        item
        for item in step.arguments
        if isinstance(item, MetadataQueryArgument)
    )
    if not query_specs:
        return None
    if step.subcommand != "metadata" or step.arguments[0] != "discover":
        raise GatewayInvocationError(
            "MetadataQueryArgument is valid only for metadata discover"
        )
    if not 1 <= len(query_specs) <= 8:
        raise GatewayInvocationError(
            "metadata discover allow-list must contain 1..8 bounded queries"
        )
    object_type = (
        step.arguments[2]
        if len(step.arguments) >= 3
        and step.arguments[:2] == ("discover", "--object-type")
        else None
    )
    if (
        not isinstance(object_type, str)
        or not object_type
        or object_type != object_type.strip()
        or len(object_type) > 256
    ):
        raise GatewayInvocationError(
            "metadata discover allow-list must use one bounded object-type scope"
        )
    configured_shape: list[Any] = [
        "discover",
        "--object-type",
        object_type,
    ]
    for query_spec in query_specs:
        configured_shape.extend(("--query", query_spec))
    configured_shape.extend(("--limit", "8"))
    if list(step.arguments) != configured_shape:
        raise GatewayInvocationError(
            "metadata discover allow-list must contain only its exact "
            "object-type, 1..8 query slots, and --limit 8"
        )

    if (
        len(supplied_arguments) < 7
        or len(supplied_arguments) > 21
        or (len(supplied_arguments) - 1) % 2
        or supplied_arguments[0] != "discover"
    ):
        raise GatewayInvocationError(
            "metadata discover scope must be exactly the configured "
            "object-type, 1..8 bounded --query pairs, and --limit 8"
        )

    supplied_object_types: list[str] = []
    supplied_limits: list[str] = []
    queries: list[str] = []
    for index in range(1, len(supplied_arguments), 2):
        flag = supplied_arguments[index]
        value = supplied_arguments[index + 1]
        if flag == "--object-type":
            supplied_object_types.append(value)
        elif flag == "--query":
            queries.append(value)
        elif flag == "--limit":
            supplied_limits.append(value)
        else:
            raise GatewayInvocationError(
                "metadata discover accepts only its configured --object-type, "
                "--query, and --limit options"
            )
    if (
        supplied_object_types != [object_type]
        or supplied_limits != ["8"]
        or not 1 <= len(queries) <= 8
    ):
        raise GatewayInvocationError(
            "metadata discover scope must be exactly one configured "
            "--object-type, 1..8 --query values, and one --limit 8"
        )
    query_values = tuple(queries)
    maximum_chars = min(item.maximum_chars for item in query_specs)
    if any(
        not query
        or query != query.strip()
        or query.startswith("--")
        or len(query) > maximum_chars
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in query
        )
        for query in query_values
    ):
        raise GatewayInvocationError(
            "metadata discover query values must be bounded, non-empty "
            "natural-language text"
        )
    normalized = [
        " ".join(query.split()).casefold()
        for query in query_values
    ]
    if len(normalized) != len(set(normalized)):
        raise GatewayInvocationError(
            "metadata discover query values must be distinct"
        )
    if sum(len(query) for query in query_values) > 640:
        raise GatewayInvocationError(
            "metadata discover query text exceeds the combined bound"
        )
    return query_values


def _metadata_discovery_live_projection(
    payload: Mapping[str, Any],
    *,
    object_type: str,
) -> Mapping[str, MetadataTokenProjection]:
    """Return stable exact-token fields from one brokered discovery result."""

    agent_result = payload.get("agent_result", payload)
    if (
        not isinstance(agent_result, Mapping)
        or agent_result.get("contract") != "waapi-skill.metadata-discovery/v2"
        or agent_result.get("result_detail") != "compact"
        or agent_result.get("authority") != "live-waapi"
        or agent_result.get("selection_required") is not True
        or agent_result.get("exact_live_name_required_for_mutation") is not True
        or agent_result.get("dependency_closure_complete") is not True
        or agent_result.get("unresolved_dependencies") != []
    ):
        raise GatewayInvocationError(
            "metadata-bound mutation requires one complete live discovery payload"
        )
    scope = agent_result.get("scope")
    resolved = scope.get("resolved") if isinstance(scope, Mapping) else None
    if (
        not isinstance(scope, Mapping)
        or scope.get("kind") != "object_type"
        or scope.get("requested") != object_type
        or not isinstance(resolved, Mapping)
        or resolved.get("name") != object_type
    ):
        raise GatewayInvocationError(
            "metadata-bound mutation requires the exact configured live object-type scope"
        )
    projections: list[MetadataTokenProjection] = []
    for key in ("candidates", "dependency_candidates"):
        rows = agent_result.get(key)
        if not isinstance(rows, list):
            raise GatewayInvocationError(
                f"metadata discovery {key} evidence is malformed"
            )
        for row in rows:
            name = row.get("name") if isinstance(row, Mapping) else None
            kind = row.get("kind") if isinstance(row, Mapping) else None
            metadata = row.get("metadata") if isinstance(row, Mapping) else None
            metadata_type = (
                metadata.get("type")
                if isinstance(metadata, Mapping)
                else None
            )
            if (
                not isinstance(name, str)
                or not name
                or name != name.strip()
                or len(name) > 256
                or name.startswith("@")
                or kind not in {"property", "reference"}
                or not isinstance(metadata_type, str)
                or kind == "property"
                and not metadata_type
            ):
                raise GatewayInvocationError(
                    f"metadata discovery {key} lacks one stable token projection"
                )
            try:
                projections.append(
                    MetadataTokenProjection(
                        name=name,
                        kind=kind,
                        metadata_type=metadata_type,
                    )
                )
            except ValueError as exc:
                raise GatewayInvocationError(
                    f"metadata discovery {key} contains an invalid token projection"
                ) from exc
    if len(projections) != len(
        {item.name.casefold() for item in projections}
    ):
        raise GatewayInvocationError(
            "metadata discovery repeats a candidate/dependency name"
        )
    return MappingProxyType({item.name: item for item in projections})


def project_required_metadata_tokens(
    payload: Mapping[str, Any],
    *,
    object_type: str,
    required_tokens: Sequence[str],
) -> tuple[MetadataTokenProjection, ...]:
    """Project only mutation-relevant stable fields from live discovery.

    Ranking, candidate order, matched queries, display metadata, defaults, and
    other version-sensitive details are deliberately excluded.
    """

    tokens = tuple(required_tokens)
    if (
        not tokens
        or any(
            not isinstance(token, str)
            or not token
            or token != token.strip()
            or token.startswith("@")
            for token in tokens
        )
        or len(tokens) != len({token.casefold() for token in tokens})
    ):
        raise GatewayInvocationError(
            "required metadata tokens must be unique exact names"
        )
    available = _metadata_discovery_live_projection(
        payload,
        object_type=object_type,
    )
    missing = [token for token in tokens if token not in available]
    if missing:
        raise GatewayInvocationError(
            f"required metadata tokens are absent from live discovery: {missing!r}"
        )
    return tuple(available[token] for token in tokens)


def _object_operation_json_equal(actual: Any, expected: Any) -> bool:
    """Compare one operation request with closed public-schema equivalences.

    The public object operations default an omitted ``on_name_conflict`` to
    ``fail``.  Their live property metadata also accepts an integral JSON number
    for the real-valued ``Volume`` and ``Pitch`` properties.  Empty optional
    node arrays have the same normalized tree meaning as omission.  Those forms
    are equivalent only inside this matcher; generic WAAPI JSON remains exact.
    """

    if not isinstance(expected, Mapping) or expected.get("operation") not in {
        "object.create",
        "object.set",
    }:
        return False

    def compare(
        left: Any,
        right: Any,
        path: tuple[str | int, ...],
        *,
        real_property_value: bool = False,
    ) -> bool:
        if isinstance(right, Mapping):
            if not isinstance(left, Mapping):
                return False
            right_keys = set(right)
            left_keys = set(left)
            ignored_right: set[Any] = set()
            ignored_left: set[Any] = set()
            if (
                path == ("arguments",)
                and right.get("on_name_conflict") == "fail"
                and "on_name_conflict" not in left
            ):
                ignored_right.add("on_name_conflict")

            node_mapping = (
                {"type", "name"}.issubset(right_keys | left_keys)
                or (
                    "object" in (right_keys | left_keys)
                    and len(path) >= 2
                    and isinstance(path[-1], int)
                    and path[-2] == "objects"
                )
            )
            if node_mapping:
                for key in ("properties", "references", "children"):
                    if key in right and right[key] == [] and key not in left:
                        ignored_right.add(key)
                    if key in left and left[key] == [] and key not in right:
                        ignored_left.add(key)

            if left_keys - ignored_left != right_keys - ignored_right:
                return False
            return all(
                compare(
                    left[key],
                    value,
                    (*path, str(key)),
                    real_property_value=(
                        key == "value"
                        and right.get("name") in {"Volume", "Pitch"}
                    ),
                )
                for key, value in right.items()
                if key not in ignored_right
            )
        if isinstance(right, list):
            return (
                isinstance(left, list)
                and len(left) == len(right)
                and all(
                    compare(left_item, right_item, (*path, index))
                    for index, (left_item, right_item) in enumerate(
                        zip(left, right, strict=True)
                    )
                )
            )
        if real_property_value and {type(left), type(right)} == {int, float}:
            float_value = left if type(left) is float else right
            int_value = left if type(left) is int else right
            return (
                math.isfinite(float_value)
                and float_value.is_integer()
                and int(float_value) == int_value
            )
        return _canonical_json_bytes(left) == _canonical_json_bytes(right)

    return compare(actual, expected, ())


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


def reconcile_gateway_command_prefix(
    command_argvs: Sequence[Sequence[str]],
    evidence: GatewayBrokerEvidence,
    *,
    expected_step_count: int,
    skill_source: Path,
    shim_directory: Path | None = None,
) -> GatewayBrokerReconciliation:
    """Reconcile one exact successful prefix without weakening final checks.

    A V3 scenario may span several Codex turns while using one broker.  This
    checkpoint proves that the broker has consumed exactly the caller-selected
    prefix and that the cumulative harness commands match it byte-for-byte
    after canonical gateway normalization.  It never accepts a failed broker
    or an extra/missing step.  The sole early terminal checkpoint is the exact
    non-retryable indeterminate branch of an ordinary execute step.
    """

    if isinstance(expected_step_count, bool) or not isinstance(expected_step_count, int):
        raise ValueError("expected_step_count must be an integer")
    total_steps = len(evidence.expected_step_names)
    if not 1 <= expected_step_count <= total_steps:
        raise ValueError(
            f"expected_step_count must be between 1 and {total_steps}, inclusive"
        )

    expected_prefix = evidence.expected_step_names[:expected_step_count]
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
    if len(command_argvs) != expected_step_count:
        errors.append(
            f"observed command count {len(command_argvs)} does not match expected prefix count "
            f"{expected_step_count}"
        )
    if evidence.consumed_step_names != expected_prefix:
        errors.append(
            "broker consumed steps do not match the requested expected-step prefix"
        )
    if len(evidence.records) != expected_step_count:
        errors.append(
            f"broker record count {len(evidence.records)} does not match expected prefix count "
            f"{expected_step_count}"
        )
    if len(accepted) != expected_step_count:
        errors.append(
            f"accepted broker record count {len(accepted)} does not match expected prefix count "
            f"{expected_step_count}"
        )
    if tuple(record.step_name for record in accepted) != expected_prefix:
        errors.append("accepted broker record names do not match the expected-step prefix")
    if len(resolved) != len(accepted):
        errors.append(
            f"resolved command count {len(resolved)} does not match accepted broker record count "
            f"{len(accepted)}"
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
    if len(evidence.successful_records) != expected_step_count:
        errors.append("broker successful record count does not match the expected prefix")

    if expected_step_count == total_steps:
        if not evidence.complete:
            errors.append("broker did not consume every expected step")
        if not evidence.passed:
            errors.append("broker evidence did not pass its terminal success contract")
    else:
        if evidence.complete:
            errors.append("broker completed before the requested partial prefix checkpoint")
        if evidence.terminal_indeterminate:
            if expected_step_count != len(evidence.consumed_step_names):
                errors.append(
                    "terminal indeterminate checkpoint must end at the consumed execute step"
                )
        elif evidence.terminal_state != _BROKER_RUNNING:
            errors.append(
                "partial prefix checkpoint requires broker terminal_state RUNNING"
            )

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


def _decode_json_argument(
    value: str,
    *,
    reject_duplicate_keys: bool = False,
) -> Any:
    def reject_constant(constant: str) -> Any:
        raise ValueError(f"non-finite JSON constant {constant!r}")

    def object_pairs(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if reject_duplicate_keys and key in result:
                raise ValueError(f"duplicate JSON object key {key!r}")
            result[key] = item
        return result

    try:
        return json.loads(
            value,
            parse_constant=reject_constant,
            object_pairs_hook=object_pairs,
        )
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


def _validate_terminal_execute_payload(
    payload: Mapping[str, Any],
    *,
    exit_code: int | None,
) -> None:
    """Accept only the closed migration terminal execute shapes.

    ``ak.wwise.cli.migrate`` may terminate its isolated WAAPI host server while
    the execute request is returning, but it may also leave the separate
    control host alive.  This exception is deliberately much narrower than a
    generic exit-2 allowance: the command must be ``execute`` and the durable
    transaction state must prove either completed execution or an
    indeterminate, non-retryable attempt.  It does not assert a disconnect;
    lifecycle evidence classifies that later.  Pre-dispatch ``status:error``
    envelopes are never accepted here.
    """

    if payload.get("command") != "execute":
        raise GatewayInvocationError(
            "terminal-execute payload command must be exactly 'execute'"
        )
    status = payload.get("status")
    state = payload.get("state")
    if payload.get("automatic_retry") is not False:
        raise GatewayInvocationError(
            "terminal-execute payload automatic_retry must be exactly false"
        )
    if payload.get("ok") is True:
        if status != "executed_unverified" or state != "executed_unverified":
            raise GatewayInvocationError(
                "successful terminal-execute payload must be executed_unverified"
            )
        if payload.get("executed") is not True or payload.get("verified") is not False:
            raise GatewayInvocationError(
                "successful terminal-execute payload must prove executed=true and verified=false"
            )
        if exit_code not in {0, 2}:
            raise GatewayInvocationError(
                "successful terminal-execute payload requires runner exit 0 or 2"
            )
        return
    if payload.get("ok") is False:
        if exit_code != 2:
            raise GatewayInvocationError(
                "indeterminate terminal-execute payload requires runner exit 2"
            )
        if status != "indeterminate" or state != "indeterminate":
            raise GatewayInvocationError(
                "failed terminal-execute payload must be exactly indeterminate"
            )
        return
    raise GatewayInvocationError(
        "terminal-execute payload ok must be exactly true or false"
    )


def _is_exact_indeterminate_execute_payload(
    payload: Mapping[str, Any],
    *,
    exit_code: int | None,
) -> bool:
    return (
        exit_code == 2
        and payload.get("contract") == GATEWAY_RESULT_CONTRACT
        and payload.get("ok") is False
        and payload.get("command") == "execute"
        and payload.get("status") == "indeterminate"
        and payload.get("state") == "indeterminate"
        and payload.get("automatic_retry") is False
    )


def _validate_branching_execute_payload(
    payload: Mapping[str, Any],
    *,
    exit_code: int | None,
) -> None:
    """Validate an ordinary execute with success and indeterminate branches.

    A successful ordinary mutation must continue to its separately allow-listed
    ``verify`` step.  Only the exact non-retryable exit-2 shape may terminate at
    execute; arbitrary gateway errors never become an accepted branch.
    """

    if payload.get("command") != "execute":
        raise GatewayInvocationError(
            "branching execute payload command must be exactly 'execute'"
        )
    if payload.get("ok") is True:
        if exit_code != 0:
            raise GatewayInvocationError(
                "successful branching execute payload requires runner exit 0"
            )
        if (
            payload.get("status") != "executed_unverified"
            or payload.get("state") != "executed_unverified"
            or payload.get("executed") is not True
            or payload.get("verified") is not False
            or payload.get("automatic_retry") is not False
        ):
            raise GatewayInvocationError(
                "successful branching execute payload must be exactly executed_unverified"
            )
        return
    if _is_exact_indeterminate_execute_payload(payload, exit_code=exit_code):
        return
    raise GatewayInvocationError(
        "failed branching execute payload must be exactly non-retryable indeterminate"
    )


_SHIM_SOURCE = r'''#!{python}
from __future__ import annotations
import json
import os
import socket
import sys
import time

OUTPUT_ARM_SECONDS = {output_arm!r}
OUTPUT_DRAIN_SECONDS = {output_drain!r}

def write_all(descriptor, value):
    encoded = str(value).encode("utf-8")
    remaining = memoryview(encoded)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise RuntimeError("Codex gateway broker shim could not publish output")
        remaining = remaining[written:]
    return bool(encoded)

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
        # ``socket.create_connection(..., timeout=30)`` leaves that timeout on
        # the TCP socket.  Heavy bounded calls such as a 120-second topic wait
        # legitimately outlive it, so give the local relay the broker runner's
        # finite execution budget plus a small response/reaping margin.
        connection.settimeout({response_timeout!r})
        connection.sendall(request.encode("utf-8"))
        chunks = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    response = json.loads(b"".join(chunks).decode("utf-8"))
    stdout_value = response.get("stdout", "")
    stderr_value = response.get("stderr", "")
    if stdout_value or stderr_value:
        # Fast broker calls can finish before the bundled Codex collector has
        # armed its command-output subscription.  Wait before the first byte;
        # a post-write delay cannot recover bytes that were published early.
        time.sleep(OUTPUT_ARM_SECONDS)
    stdout_written = write_all(1, stdout_value)
    stderr_written = write_all(2, stderr_value)
    if stdout_written or stderr_written:
        # The bundled Codex command collector has intermittently archived a
        # short final gateway payload as an empty ``aggregated_output`` when
        # the shim exits in the same scheduling slice.  The broker already
        # validated this payload; publish it without Python text buffering and
        # give the collector one small, finite drain window before exit.
        time.sleep(OUTPUT_DRAIN_SECONDS)
    raise SystemExit(int(response.get("exit_code", 125)))
except Exception as exc:
    error_value = "Codex gateway broker shim failed: " + str(exc) + "\n"
    time.sleep(OUTPUT_ARM_SECONDS)
    write_all(2, error_value)
    time.sleep(OUTPUT_DRAIN_SECONDS)
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
        project_modification_policy: str = "ask_before_changes",
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
        trusted_subscription_ack: TrustedSubscriptionAckSpec | None = None,
        trusted_subscription_ack_observer: TrustedSubscriptionAckObserver | None = None,
    ) -> None:
        self.skill_source = _absolute_lexical(skill_source)
        self.runner_path = self.skill_source / "scripts" / "run.py"
        self.expected_steps = tuple(expected_steps)
        self.gateway_global_arguments = tuple(str(value) for value in gateway_global_arguments)
        self.expected_wwise_version = str(expected_wwise_version)
        self.project_modification_policy = str(project_modification_policy)
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
        self.trusted_subscription_ack = trusted_subscription_ack
        self.trusted_subscription_ack_observer = trusted_subscription_ack_observer
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
        if self.project_modification_policy not in {
            "read_only",
            "ask_before_changes",
            "allow_changes",
        }:
            raise ValueError(
                "project_modification_policy must be read_only, "
                "ask_before_changes, or allow_changes"
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
        if self.trusted_subscription_ack is not None and not isinstance(
            self.trusted_subscription_ack,
            TrustedSubscriptionAckSpec,
        ):
            raise TypeError(
                "trusted_subscription_ack must be TrustedSubscriptionAckSpec or None"
            )
        if self.trusted_subscription_ack_observer is not None and not callable(
            self.trusted_subscription_ack_observer
        ):
            raise TypeError(
                "trusted_subscription_ack_observer must be callable or None"
            )
        if (
            self.trusted_subscription_ack is None
            and self.trusted_subscription_ack_observer is not None
        ):
            raise ValueError(
                "trusted_subscription_ack_observer requires trusted_subscription_ack"
            )
        for argument in self.gateway_global_arguments:
            option = argument.split("=", 1)[0]
            if option in _FORBIDDEN_GLOBAL_ARGUMENTS:
                raise ValueError(
                    f"gateway_global_arguments cannot override runner-owned {option}"
                )
        names = [step.name for step in self.expected_steps]
        if len(names) != len(set(names)):
            raise ValueError("ExpectedGatewayStep names must be unique")
        terminal_execute_steps = tuple(
            index
            for index, step in enumerate(self.expected_steps)
            if step.terminal_execute
        )
        if terminal_execute_steps and terminal_execute_steps != (
            len(self.expected_steps) - 1,
        ):
            raise ValueError(
                "terminal_execute must be the one final broker step"
            )
        if self.trusted_subscription_ack is not None:
            matching_steps = tuple(
                step
                for step in self.expected_steps
                if step.name == self.trusted_subscription_ack.step_name
            )
            if len(matching_steps) != 1:
                raise ValueError(
                    "trusted subscription ACK step must identify one expected step"
                )
            ack_step = matching_steps[0]
            if (
                ack_step.subcommand != "wait-topic"
                or not ack_step.arguments
                or ack_step.arguments[0] != self.trusted_subscription_ack.topic
            ):
                raise ValueError(
                    "trusted subscription ACK must bind the exact literal wait-topic URI"
                )

        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        self._working_root: Path | None = None
        self._shim_directory: Path | None = None
        self._bash_env_path: Path | None = None
        self._state_directory: Path | None = None
        self._evidence_directory: Path | None = None
        self._config_path: Path | None = None
        self._subscription_ack_path: Path | None = None
        self._subscription_ack_nonce = ""
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
    def subscription_ack_expectation(self) -> TrustedSubscriptionAckExpectation | None:
        """Return the non-secret trusted ACK binding after broker startup."""

        if self.trusted_subscription_ack is None:
            return None
        if self._subscription_ack_path is None or not self._subscription_ack_nonce:
            raise GatewayBrokerError("broker subscription ACK is not initialized")
        return TrustedSubscriptionAckExpectation(
            contract=SUBSCRIPTION_ACK_CONTRACT,
            step_name=self.trusted_subscription_ack.step_name,
            topic=self.trusted_subscription_ack.topic,
            path=self._subscription_ack_path,
            nonce_sha256=hashlib.sha256(
                self._subscription_ack_nonce.encode("utf-8")
            ).hexdigest(),
        )

    def _subscription_ack_credential(
        self,
    ) -> _TrustedSubscriptionAckCredential | None:
        expectation = self.subscription_ack_expectation
        if expectation is None:
            return None
        return _TrustedSubscriptionAckCredential(
            expectation=expectation,
            nonce=self._subscription_ack_nonce,
        )

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
            if self.trusted_subscription_ack is not None:
                self._subscription_ack_nonce = secrets.token_urlsafe(32)
                self._subscription_ack_path = self._evidence_directory / (
                    f"subscription-ack-{secrets.token_hex(16)}.json"
                )
                if (
                    self._subscription_ack_path.exists()
                    or self._subscription_ack_path.is_symlink()
                ):
                    raise GatewayBrokerError(
                        "fresh broker subscription ACK target already exists"
                    )
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
                        "project_modification_policy": self.project_modification_policy,
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
        self._subscription_ack_path = None
        self._subscription_ack_nonce = ""
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
        for name in _SUBSCRIPTION_ACK_ENV_NAMES:
            environment.pop(name, None)
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

    def reconcile_prefix(
        self,
        command_argvs: Sequence[Sequence[str]],
        *,
        expected_step_count: int,
    ) -> GatewayBrokerReconciliation:
        return reconcile_gateway_command_prefix(
            command_argvs,
            self.evidence(),
            expected_step_count=expected_step_count,
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
            response_timeout=max(
                30.0,
                self.runner_timeout_seconds + _SHIM_RESPONSE_GRACE_SECONDS,
            ),
            output_arm=_SHIM_OUTPUT_ARM_SECONDS,
            output_drain=_SHIM_OUTPUT_DRAIN_SECONDS,
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
            except PermissionError:
                # A short-lived wrapper can leave/reap its process group
                # between validation and teardown on macOS.  Fall back to the
                # still-owned leader without converting an ACK rejection into
                # an unrelated close failure.
                if process.poll() is None:
                    try:
                        process.terminate() if terminate else process.kill()
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

    def _subscription_ack_for_step(
        self,
        step: ExpectedGatewayStep,
    ) -> _TrustedSubscriptionAckCredential | None:
        credential = self._subscription_ack_credential()
        if (
            credential is None
            or credential.expectation.step_name != step.name
        ):
            return None
        return credential

    @staticmethod
    def _validate_subscription_ack(
        credential: _TrustedSubscriptionAckCredential,
        *,
        runner_process: subprocess.Popen[str],
        started_at_unix_ns: int,
    ) -> Mapping[str, Any]:
        """Wait for and independently validate a live packaged-child ACK."""

        expectation = credential.expectation
        path = expectation.path
        deadline = time.monotonic() + _SUBSCRIPTION_ACK_WAIT_SECONDS
        while True:
            if path.is_symlink():
                raise GatewayInvocationError(
                    "broker subscription ACK target became a symlink"
                )
            try:
                candidate_metadata = path.lstat()
            except FileNotFoundError:
                candidate_metadata = None
            except OSError as exc:
                raise GatewayInvocationError(
                    f"broker subscription ACK is unavailable: {exc}"
                ) from exc
            if candidate_metadata is not None:
                if (
                    stat.S_ISREG(candidate_metadata.st_mode)
                    and candidate_metadata.st_nlink == 1
                ):
                    break
                if (
                    not stat.S_ISREG(candidate_metadata.st_mode)
                    or candidate_metadata.st_nlink != 2
                ):
                    raise GatewayInvocationError(
                        "broker subscription ACK is not an exclusive regular file"
                    )
                # The packaged writer briefly exposes the completed inode with
                # two hard links, then removes its private temp name.  Only
                # that exact transitional state is retryable.
            if runner_process.poll() is not None and candidate_metadata is None:
                raise GatewayInvocationError(
                    "broker subscription ACK is missing after packaged runner exit"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GatewayInvocationError(
                    "broker subscription ACK did not arrive before its bounded deadline"
                )
            time.sleep(min(_SUBSCRIPTION_ACK_POLL_SECONDS, remaining))

        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if path.parent.is_symlink() or not path.parent.is_dir():
            raise GatewayInvocationError(
                "broker subscription ACK parent is not one exact real directory"
            )
        descriptor: int | None = None
        try:
            descriptor = os.open(path, flags)
            metadata = os.fstat(descriptor)
            chunks: list[bytes] = []
            remaining_bytes = _SUBSCRIPTION_ACK_MAX_BYTES + 1
            while remaining_bytes > 0:
                chunk = os.read(descriptor, min(65536, remaining_bytes))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining_bytes -= len(chunk)
            raw = b"".join(chunks)
            final_metadata = path.lstat()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayInvocationError(
                f"broker subscription ACK is not strict UTF-8 JSON: {exc}"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
            or metadata.st_size > _SUBSCRIPTION_ACK_MAX_BYTES
            or metadata.st_size != len(raw)
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or final_metadata.st_dev != metadata.st_dev
            or final_metadata.st_ino != metadata.st_ino
            or final_metadata.st_nlink != 1
        ):
            raise GatewayInvocationError(
                "broker subscription ACK is not one private bounded regular file"
            )
        expected_keys = {
            "contract",
            "step_name",
            "topic",
            "nonce",
            "runner_parent_process_id",
            "gateway_process_id",
            "subscribed_at_unix_ns",
            "subscribed_at_monotonic_ns",
        }
        nonce = payload.get("nonce") if isinstance(payload, Mapping) else None
        nonce_sha256 = (
            hashlib.sha256(nonce.encode("utf-8")).hexdigest()
            if isinstance(nonce, str)
            else ""
        )
        validated_at_unix_ns = time.time_ns()
        if (
            not isinstance(payload, Mapping)
            or set(payload) != expected_keys
            or payload.get("contract") != expectation.contract
            or payload.get("step_name") != expectation.step_name
            or payload.get("topic") != expectation.topic
            or not isinstance(nonce, str)
            or _SUBSCRIPTION_ACK_NONCE_RE.fullmatch(nonce) is None
            or not secrets.compare_digest(nonce, credential.nonce)
            or not secrets.compare_digest(
                nonce_sha256,
                expectation.nonce_sha256,
            )
            or type(payload.get("runner_parent_process_id")) is not int
            or payload.get("runner_parent_process_id") != runner_process.pid
            or type(payload.get("gateway_process_id")) is not int
            or payload.get("gateway_process_id", 0) <= 0
            or payload.get("gateway_process_id") == runner_process.pid
            or type(payload.get("subscribed_at_unix_ns")) is not int
            or type(payload.get("subscribed_at_monotonic_ns")) is not int
            or payload.get("subscribed_at_monotonic_ns", 0) <= 0
        ):
            raise GatewayInvocationError(
                "broker subscription ACK identity, nonce, or packaged process binding is invalid"
            )
        subscribed_at_unix_ns = int(payload["subscribed_at_unix_ns"])
        if not started_at_unix_ns <= subscribed_at_unix_ns <= validated_at_unix_ns:
            raise GatewayInvocationError(
                "broker subscription ACK timestamp is outside its gateway step"
            )
        canonical = _canonical_json_bytes(payload) + b"\n"
        if raw != canonical:
            raise GatewayInvocationError(
                "broker subscription ACK is not canonical JSON"
            )
        temporary_pattern = f".{path.name}.*.tmp"
        if any(path.parent.glob(temporary_pattern)):
            raise GatewayInvocationError(
                "broker subscription ACK left an ambiguous temporary artifact"
            )
        return MappingProxyType(
            {
                "contract": VALIDATED_SUBSCRIPTION_ACK_CONTRACT,
                "ack_contract": expectation.contract,
                "step_name": expectation.step_name,
                "topic": expectation.topic,
                "ack_path": str(path),
                "ack_file_sha256": hashlib.sha256(raw).hexdigest(),
                "nonce_sha256": nonce_sha256,
                "runner_parent_process_id": int(
                    payload["runner_parent_process_id"]
                ),
                "gateway_process_id": int(payload["gateway_process_id"]),
                "subscribed_at_unix_ns": subscribed_at_unix_ns,
                "subscribed_at_monotonic_ns": int(
                    payload["subscribed_at_monotonic_ns"]
                ),
                "step_started_at_unix_ns": started_at_unix_ns,
                "validated_at_unix_ns": validated_at_unix_ns,
            }
        )

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
        execution_arguments = actual_values
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
            execution_arguments = (*expected_prefix, *validation_arguments)
        if (
            step.allow_omitted_default_event_count_one
            and len(supplied_arguments) == len(step.arguments) - 2
            and "--event-count" not in supplied_arguments
            and not any(
                value.startswith("--event-count=")
                for value in supplied_arguments
            )
        ):
            event_count_index = step.arguments.index("--event-count")
            validation_arguments = (
                *supplied_arguments[:event_count_index],
                "--event-count",
                "1",
                *supplied_arguments[event_count_index:],
            )
            execution_arguments = (*expected_prefix, *validation_arguments)
        metadata_queries = _validate_metadata_discover_query_arguments(
            step,
            validation_arguments,
        )
        if (
            metadata_queries is None
            and len(validation_arguments) != len(step.arguments)
        ):
            raise GatewayInvocationError(
                f"expected step {step.name!r} to have {len(step.arguments)} arguments; "
                f"received {len(supplied_arguments)}"
            )

        unordered_return_field_indexes = frozenset()
        if step.subcommand == "query-object":
            unordered_return_field_indexes = (
                _query_object_return_field_value_indexes(
                    validation_arguments,
                    step.arguments,
                )
            )

        semantic_values: list[Any] = [
            "runner-owned-version",
            self.expected_wwise_version,
            *expected_prefix,
        ]
        if metadata_queries is not None:
            semantic_values.extend(
                (
                    "metadata-discover-query-set/v1",
                    step.arguments[2],
                    list(metadata_queries),
                    8,
                )
            )
        else:
            for index, (supplied, expected) in enumerate(
                zip(validation_arguments, step.arguments)
            ):
                if isinstance(expected, str):
                    if (
                        index not in unordered_return_field_indexes
                        and supplied != expected
                    ):
                        raise GatewayInvocationError(
                            f"step {step.name!r} argument {index} must be exactly {expected!r}"
                        )
                    semantic_values.append(expected)
                elif isinstance(expected, SemanticJsonArgument):
                    actual_json = _decode_json_argument(
                        supplied,
                        reject_duplicate_keys=(
                            expected.equivalence
                            == "soundbank_generate_v1"
                        ),
                    )
                    if not _semantic_json_equal(actual_json, expected):
                        raise GatewayInvocationError(
                            f"step {step.name!r} argument {index} JSON is not semantically equal to the allow-list"
                        )
                    semantic_values.append(expected.expected)
                elif isinstance(expected, MetadataQueryArgument):
                    raise GatewayInvocationError(
                        "metadata query slot escaped its closed discover validator"
                    )
                elif isinstance(expected, MetadataBoundJsonArgument):
                    actual_json = _decode_json_argument(
                        supplied,
                        reject_duplicate_keys=(
                            expected.equivalence
                            in {
                                "audio_import_v1",
                                "audio_import_tab_v1",
                                "object_set_v1",
                            }
                        ),
                    )
                    if not _metadata_bound_json_equal(actual_json, expected):
                        raise GatewayInvocationError(
                            f"step {step.name!r} argument {index} JSON is not "
                            "semantically equal to the metadata-bound allow-list"
                        )
                    source = self._payloads_by_step.get(expected.metadata_step)
                    if source is None:
                        raise GatewayInvocationError(
                            f"step {step.name!r} metadata source "
                            f"{expected.metadata_step!r} is unavailable"
                        )
                    source_steps = tuple(
                        candidate
                        for candidate in self.expected_steps
                        if candidate.name == expected.metadata_step
                    )
                    if (
                        len(source_steps) != 1
                        or source_steps[0].subcommand != "metadata"
                        or len(source_steps[0].arguments) < 3
                        or source_steps[0].arguments[:2]
                        != ("discover", "--object-type")
                        or source_steps[0].arguments[2] != expected.object_type
                    ):
                        raise GatewayInvocationError(
                            f"step {step.name!r} metadata source does not bind "
                            f"object type {expected.object_type!r}"
                        )
                    actual_projection = project_required_metadata_tokens(
                        source,
                        object_type=expected.object_type,
                        required_tokens=expected.required_tokens,
                    )
                    expected_projection = (
                        expected.expected_required_token_projection
                    )
                    if (
                        expected_projection is not None
                        and actual_projection != expected_projection
                    ):
                        raise GatewayInvocationError(
                            f"step {step.name!r} live metadata projection differs "
                            f"from the trusted projection for {expected.metadata_step!r}"
                        )
                    semantic_values.extend(
                        (
                            _metadata_bound_semantic_value(
                                actual_json,
                                expected,
                            ),
                            expected.equivalence,
                            expected.metadata_step,
                            expected.object_type,
                            list(expected.required_tokens),
                            (
                                [
                                    item.as_dict()
                                    for item in expected_projection
                                ]
                                if expected_projection is not None
                                else None
                            ),
                        )
                    )
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
        return (
            _sha256_bytes(_canonical_json_bytes(semantic_values)),
            tuple(execution_arguments),
        )

    def _execute(
        self,
        step: ExpectedGatewayStep,
        resolved: ResolvedGatewayInvocation,
        semantic_hash: str,
        *,
        execution_arguments: Sequence[str],
    ) -> dict[str, Any]:
        started_at_unix_ns = time.time_ns()
        started = started_at_unix_ns / 1_000_000_000
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
        validated_ack: dict[str, Any] | None = None
        terminal_indeterminate = False
        ack_credential = self._subscription_ack_for_step(step)
        try:
            command[1] = str(self.runner_path.resolve(strict=True))
            runner_env = dict(self._runner_environment)
            for name in _BROKER_ENV_NAMES:
                runner_env.pop(name, None)
            runner_env[STATE_DIRECTORY_ENV] = str(self.state_directory)
            runner_env[EVIDENCE_DIRECTORY_ENV] = str(self.evidence_directory)
            runner_env[CONFIG_PATH_ENV] = str(self.config_path)
            if ack_credential is not None:
                ack_expectation = ack_credential.expectation
                if ack_expectation.path.exists() or ack_expectation.path.is_symlink():
                    raise GatewayBrokerError(
                        "broker subscription ACK target was pre-created or forged"
                    )
                runner_env.update(
                    {
                        SUBSCRIPTION_ACK_PATH_ENV: str(ack_expectation.path),
                        SUBSCRIPTION_ACK_NONCE_ENV: ack_credential.nonce,
                        SUBSCRIPTION_ACK_TOPIC_ENV: ack_expectation.topic,
                        SUBSCRIPTION_ACK_STEP_ENV: ack_expectation.step_name,
                    }
                )
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
            if (
                ack_credential is not None
                and self.trusted_subscription_ack_observer is not None
            ):
                self.trusted_subscription_ack_observer(
                    ack_credential.expectation
                )
            process = self._launch_runner(command, runner_env=runner_env)
            if ack_credential is not None:
                try:
                    validated_ack = dict(
                        self._validate_subscription_ack(
                            ack_credential,
                            runner_process=process,
                            started_at_unix_ns=started_at_unix_ns,
                        )
                    )
                except GatewayInvocationError as exc:
                    failures.append(str(exc))
                    self._signal_runner_group(process, terminate=True)
                except Exception as exc:  # noqa: BLE001 - malformed ACK fails the record
                    failures.append(
                        "unexpected broker subscription ACK failure: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    self._signal_runner_group(process, terminate=True)
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
            confirmation_is_consumed_later = any(
                isinstance(argument, ResponseBinding)
                and argument.step == step.name
                and argument.pointer == "/confirmation/token"
                for later_step in self.expected_steps[self._next_step + 1 :]
                for argument in later_step.arguments
            )
            if (
                step.subcommand == "transaction-show"
                and (
                    "confirmation" in payload
                    or confirmation_is_consumed_later
                )
            ):
                validate_transaction_show_confirmation_payload(payload)
            if step.terminal_execute:
                _validate_terminal_execute_payload(payload, exit_code=exit_code)
            elif step.allowed_exit_codes == (0, 2):
                _validate_branching_execute_payload(payload, exit_code=exit_code)
                terminal_indeterminate = _is_exact_indeterminate_execute_payload(
                    payload,
                    exit_code=exit_code,
                )
            elif step.allowed_exit_codes == (0,):
                if payload.get("ok") is not True:
                    raise GatewayInvocationError("gateway payload ok must be exactly true")
                if payload.get("command") != step.subcommand:
                    raise GatewayInvocationError(
                        f"gateway payload command must be exactly {step.subcommand!r}"
                    )
            else:
                if payload.get("ok") is not False:
                    raise GatewayInvocationError(
                        "expected exit-2 gateway payload ok must be exactly false"
                    )
                if payload.get("error_code") != step.expected_error_code:
                    raise GatewayInvocationError(
                        "expected exit-2 gateway payload error_code must be exactly "
                        f"{step.expected_error_code!r}"
                    )
                if payload.get("command") != step.expected_result_command:
                    raise GatewayInvocationError(
                        "expected exit-2 gateway payload command must be exactly "
                        f"{step.expected_result_command!r}"
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

        finished_at_unix_ns = time.time_ns()
        finished = finished_at_unix_ns / 1_000_000_000
        if validated_ack is not None:
            validated_ack["step_finished_at_unix_ns"] = finished_at_unix_ns
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
            started_at_unix_ns=started_at_unix_ns,
            finished_at_unix_ns=finished_at_unix_ns,
            subscription_ack=validated_ack,
        )
        with self._lock:
            record = self._append_record_locked(record)
            if record.succeeded:
                self._payloads_by_step[step.name] = payload
                self._next_step += 1
                if terminal_indeterminate:
                    self._terminal_state = _BROKER_INDETERMINATE
                elif self._next_step == len(self.expected_steps):
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
        now_ns = time.time_ns()
        now = now_ns / 1_000_000_000
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
            started_at_unix_ns=now_ns,
            finished_at_unix_ns=now_ns,
            subscription_ack=None,
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
    "MetadataBoundJsonArgument",
    "MetadataQueryArgument",
    "MetadataTokenProjection",
    "ResolvedGatewayInvocation",
    "ResponseBinding",
    "SemanticJsonArgument",
    "SUBSCRIPTION_ACK_CONTRACT",
    "SUBSCRIPTION_ACK_NONCE_ENV",
    "SUBSCRIPTION_ACK_PATH_ENV",
    "SUBSCRIPTION_ACK_STEP_ENV",
    "SUBSCRIPTION_ACK_TOPIC_ENV",
    "CONFIRMATION_TOKEN_MATERIAL_CONTRACT",
    "TRANSACTION_CONFIRMATION_BINDING_CONTRACT",
    "VALIDATED_SUBSCRIPTION_ACK_CONTRACT",
    "TrustedSubscriptionAckExpectation",
    "TrustedSubscriptionAckObserver",
    "TrustedSubscriptionAckSpec",
    "TrustedStepObserver",
    "TrustedStepPreObserver",
    "reconcile_gateway_commands",
    "project_required_metadata_tokens",
    "resolve_gateway_invocation",
    "validate_transaction_show_confirmation_payload",
]
