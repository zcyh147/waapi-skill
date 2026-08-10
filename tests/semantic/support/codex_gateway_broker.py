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

from tests.semantic.support.codex_filesystem_security import (
    CodexFileSecurityError,
    path_is_link_or_reparse,
    read_bounded_exclusive_regular_file,
)
from wwise_waapi.operation_composer import (
    OperationComposerError,
    apply_composer_action,
    composition_projection,
    materialize_operation_request,
    new_composition,
)
from wwise_waapi.platform_commands import (
    PlatformCommandError,
    WINDOWS_MODEL_COMMAND_FAMILY,
    WINDOWS_POWERSHELL_ENCODED_FAMILY,
    encode_windows_model_argv,
    encode_windows_powershell_argv,
)


GATEWAY_RESULT_CONTRACT = "waapi-skill.gateway-result/v1"
TRANSACTION_NEXT_COMMAND_CONTRACT = "waapi-skill.gateway-next-command/v2"
TRANSACTION_COPY_INSTRUCTION_CONTRACT = (
    "waapi-skill.gateway-command-copy-instruction/v2"
)
TRANSACTION_COPY_ACTION = "execute_verbatim_as_one_shell_tool_call"
TRANSACTION_FORBIDDEN_TRANSFORMATIONS = (
    "reconstruct",
    "shorten",
    "normalize",
    "substitute_path_segments",
    "select_another_field",
)
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
SHIM_TRUSTED_PYTHON_ENV = "WAAPI_CODEX_GATEWAY_SHIM_TRUSTED_PYTHON"
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
        SHIM_TRUSTED_PYTHON_ENV,
        BASH_ENV_NAME,
        CONFIG_PATH_ENV,
        *_SUBSCRIPTION_ACK_ENV_NAMES,
    }
)
_PYTHON_IO_ENCODING_ENV = "PYTHONIOENCODING"
_PYTHON_NAMES = frozenset({"python", "python3"})
WINDOWS_SHIM_SCRIPT_NAME = "broker_shim.py"
WINDOWS_COMMAND_SHIM_NAMES = tuple(
    f"{name}.ps1" for name in sorted(_PYTHON_NAMES)
)
_WINDOWS_PATHEXT_NAME = "PATHEXT"
_WINDOWS_PATH_SEPARATOR = ";"
_WINDOWS_DEFAULT_PATHEXT = (".COM", ".EXE", ".BAT", ".CMD", ".PS1")
_WINDOWS_PATHEXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,16}$")
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
_GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
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
_AUDIO_IMPORT_IDENTITY_MAX_NAME_LENGTH = 255
_AUDIO_IMPORT_IDENTITY_MAX_TYPE_LENGTH = 128
_AUDIO_IMPORT_IDENTITY_MAX_PARENT_LENGTH = 4096
_AUDIO_IMPORT_IDENTITY_TYPE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.]+$")
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
OBJECT_SET_SCHEMA_DEFAULTS = MappingProxyType(
    {
        "list_mode": "append",
        "on_name_conflict": "fail",
        "auto_add_to_source_control": False,
    }
)
_OBJECT_SET_RTPC_REQUIRED_ARGUMENT_FIELDS = frozenset(
    {"object", "property", "control_input", "points"}
)
_OBJECT_SET_RTPC_OPTIONAL_ARGUMENT_FIELDS = frozenset({"notes", "mode"})
_OBJECT_SET_RTPC_POINT_SHAPES = frozenset(
    {
        "Constant",
        "Linear",
        "Log3",
        "Log2",
        "Log1",
        "InvertedSCurve",
        "SCurve",
        "Exp1",
        "Exp2",
        "Exp3",
    }
)
_SOUNDBANK_GENERATE_DEFAULT_FALSE_ARGUMENT_FIELDS = (
    "rebuild_soundbanks",
    "clear_audio_file_cache",
    "rebuild_init_bank",
)
_SWITCH_CONTAINER_REMOVE_ASSIGNMENT_EQUIVALENCE = (
    "switch_container_remove_assignment_v1"
)
_AUDIO_IMPORT_DEFAULT_OPERATION_EQUIVALENCE = (
    "audio_import_default_operation_v1"
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
            _AUDIO_IMPORT_DEFAULT_OPERATION_EQUIVALENCE,
            "object_operation_v1",
            "soundbank_generate_v1",
            _SWITCH_CONTAINER_REMOVE_ASSIGNMENT_EQUIVALENCE,
        }:
            raise ValueError(
                "SemanticJsonArgument.equivalence must be wire_exact, "
                "audio_import_default_operation_v1, object_operation_v1, "
                "soundbank_generate_v1, or "
                "switch_container_remove_assignment_v1"
            )
        if self.equivalence == _AUDIO_IMPORT_DEFAULT_OPERATION_EQUIVALENCE:
            try:
                _normalize_audio_import_default_operation_request(self.expected)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "audio_import_default_operation_v1 requires one valid "
                    "audio.import request"
                ) from exc
        if self.equivalence == "soundbank_generate_v1":
            try:
                _normalize_soundbank_generate_request(self.expected)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "soundbank_generate_v1 requires one valid "
                    "soundbank.generate request"
                ) from exc
        if self.equivalence == _SWITCH_CONTAINER_REMOVE_ASSIGNMENT_EQUIVALENCE:
            try:
                _switch_container_remove_assignment_arguments(self.expected)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "switch_container_remove_assignment_v1 requires one valid "
                    "switchContainer.removeAssignment request"
                ) from exc


@dataclass(frozen=True, slots=True)
class SealedQueryIdentityBoundJsonArgument(SemanticJsonArgument):
    """One object operation with two identities bound to one prior query row.

    This is deliberately narrower than the general object-operation matcher.
    Only the declared request locations may alternate between the exact path in
    ``expected`` and the GUID returned beside that path by ``source_step``.
    """

    source_step: str = ""
    target_pointers: tuple[str, ...] = ()
    equivalence: str = "object_operation_v1"

    def __post_init__(self) -> None:
        SemanticJsonArgument.__post_init__(self)
        if self.equivalence != "object_operation_v1":
            raise ValueError(
                "SealedQueryIdentityBoundJsonArgument requires "
                "object_operation_v1 equivalence"
            )
        if (
            not isinstance(self.source_step, str)
            or not self.source_step
            or self.source_step != self.source_step.strip()
            or len(self.source_step) > 160
        ):
            raise ValueError(
                "SealedQueryIdentityBoundJsonArgument.source_step must be non-empty"
            )
        if (
            not isinstance(self.target_pointers, tuple)
            or len(self.target_pointers) != 2
            or len(set(self.target_pointers)) != 2
            or any(
                not isinstance(pointer, str)
                or not pointer.startswith("/")
                or not pointer.endswith("/target")
                or len(pointer) > 512
                for pointer in self.target_pointers
            )
        ):
            raise ValueError(
                "SealedQueryIdentityBoundJsonArgument requires two unique "
                "target JSON pointers"
            )
        if (
            not isinstance(self.expected, Mapping)
            or self.expected.get("operation") != "object.set"
        ):
            raise ValueError(
                "SealedQueryIdentityBoundJsonArgument requires object.set"
            )
        for pointer in self.target_pointers:
            try:
                target = _json_pointer(self.expected, pointer)
                reference = _json_pointer(
                    self.expected,
                    pointer.removesuffix("/target"),
                )
            except GatewayInvocationError as exc:
                raise ValueError(
                    "SealedQueryIdentityBoundJsonArgument target pointer is invalid"
                ) from exc
            if (
                not isinstance(reference, Mapping)
                or reference.get("name") != "OutputBus"
                or not isinstance(target, Mapping)
                or set(target) != {"kind", "value"}
                or target.get("kind") != "path"
                or not isinstance(target.get("value"), str)
                or not str(target["value"]).startswith("\\")
            ):
                raise ValueError(
                    "SealedQueryIdentityBoundJsonArgument expected targets must "
                    "be exact Wwise paths"
                )


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
class BoundedIntegerArgument:
    """One canonical decimal argv integer inside a closed inclusive range."""

    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if (
            type(self.minimum) is not int
            or type(self.maximum) is not int
            or not 0 <= self.minimum <= self.maximum <= 2**63 - 1
        ):
            raise ValueError(
                "BoundedIntegerArgument requires an ordered non-negative "
                "64-bit integer range"
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
class GatewayDerivedReferenceActivationAllowance:
    """One runner-owned audio.import property the Gateway may derive.

    The allowance is deliberately row-local and binds the Boolean activation
    property to the exact reference that causes the production Gateway to
    derive it.  It is test-oracle provenance, never Agent-authored input.
    """

    row_index: int
    property_name: str
    property_value: bool
    reference_name: str

    def __post_init__(self) -> None:
        if type(self.row_index) is not int or self.row_index < 0:
            raise ValueError(
                "GatewayDerivedReferenceActivationAllowance.row_index "
                "must be a non-negative integer"
            )
        for field, value in (
            ("property_name", self.property_name),
            ("reference_name", self.reference_name),
        ):
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or value.startswith("@")
                or len(value) > 256
                or any(
                    ord(character) < 32 or ord(character) == 127
                    for character in value
                )
            ):
                raise ValueError(
                    "GatewayDerivedReferenceActivationAllowance."
                    f"{field} must be one bounded exact live name"
                )
        if self.property_name.casefold() == self.reference_name.casefold():
            raise ValueError(
                "GatewayDerivedReferenceActivationAllowance property and "
                "reference names must differ"
            )
        if self.property_value is not True:
            raise ValueError(
                "GatewayDerivedReferenceActivationAllowance.property_value "
                "must be the supported Boolean activation value true"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "row_index": self.row_index,
            "property_name": self.property_name,
            "property_value": self.property_value,
            "reference_name": self.reference_name,
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
    gateway_derived_reference_activations: tuple[
        GatewayDerivedReferenceActivationAllowance, ...
    ] = ()

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
            not isinstance(self.required_tokens, tuple)
            or not self.required_tokens
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
            "object_set_rtpc_v1",
        }:
            raise ValueError(
                "MetadataBoundJsonArgument.equivalence must be "
                "wire_exact, audio_import_v1, audio_import_tab_v1, "
                "object_set_v1, or object_set_rtpc_v1"
            )
        allowances = self.gateway_derived_reference_activations
        if (
            not isinstance(allowances, tuple)
            or any(
                not isinstance(
                    item,
                    GatewayDerivedReferenceActivationAllowance,
                )
                for item in allowances
            )
            or len(allowances)
            != len(
                {
                    (
                        item.row_index,
                        item.property_name.casefold(),
                        item.reference_name.casefold(),
                    )
                    for item in allowances
                }
            )
        ):
            raise ValueError(
                "MetadataBoundJsonArgument gateway-derived reference "
                "activation allowances must be unique trusted rows"
            )
        if allowances and self.equivalence != "audio_import_v1":
            raise ValueError(
                "Gateway-derived reference activation allowances are only "
                "valid for audio_import_v1"
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
            _validate_gateway_derived_reference_activation_allowances(
                self,
                normalized,
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
        elif self.equivalence == "object_set_rtpc_v1":
            try:
                _normalize_object_set_rtpc_request(self.expected)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "object_set_rtpc_v1 requires one valid "
                    "object.setRTPC request"
                ) from exc


@dataclass(frozen=True, slots=True)
class ResponseBinding:
    """Bind one argv value to a JSON field returned by an earlier step.

    ``pointer`` is an RFC 6901 JSON pointer.  Examples include
    ``/transaction_id`` and the nested ``/confirmation/token``.
    """

    step: str
    pointer: str


_DRAFT_HANDLE_ARGUMENT_NAMES = frozenset(
    {
        "target_handle",
        "owner_handle",
        "parent_handle",
        "node_handle",
        "list_handle",
        "file_handle",
        "import_handle",
    }
)
_DRAFT_HANDLE_POINTERS = frozenset(f"/{name}" for name in _DRAFT_HANDLE_ARGUMENT_NAMES)
_DRAFT_FORBIDDEN_ACTION_KEYS = frozenset(
    {"request", "arguments", "uri", "args", "options", "waql", "request_json"}
)
_DRAFT_ACTION_HANDLE_FIELDS_BY_OPERATION = {
    "object.set": {
        "set_request_option": None,
        "clear_request_option": None,
        "add_target": None,
        "set_target_field": "target_handle",
        "clear_target_field": "target_handle",
        "set_property": "target_handle",
        "remove_property": "target_handle",
        "set_reference": "owner_handle",
        "remove_reference": "owner_handle",
        "remove_target": "target_handle",
        "add_child": "parent_handle",
        "set_node_field": "node_handle",
        "clear_node_field": "node_handle",
        "set_node_property": "node_handle",
        "remove_node_property": "node_handle",
        "remove_node": "node_handle",
        "add_list": "target_handle",
        "remove_list": "list_handle",
        "add_list_member": "list_handle",
        "add_import_file": "owner_handle",
        "set_import_option": "owner_handle",
        "clear_import_option": "owner_handle",
        "set_import_file_field": "file_handle",
        "clear_import_file_field": "file_handle",
        "remove_import_file": "file_handle",
        "remove_import": "owner_handle",
    },
    "audio.import": {
        "set_import_option": None,
        "clear_import_option": None,
        "set_import_default": None,
        "clear_import_default": None,
        "add_import_row": None,
        "set_import_row_field": "import_handle",
        "clear_import_row_field": "import_handle",
        "remove_import_row": "import_handle",
    },
}


def _draft_action_contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if (
                not isinstance(key, str)
                or key.startswith("@")
                or key in _DRAFT_FORBIDDEN_ACTION_KEYS
                or _draft_action_contains_forbidden_key(nested)
            ):
                return True
        return False
    if isinstance(value, list):
        return any(_draft_action_contains_forbidden_key(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class DraftActionResponseBinding:
    """Inject one Gateway-generated handle into a typed Draft action JSON."""

    pointer: str
    step: str
    response_pointer: str

    def __post_init__(self) -> None:
        if self.pointer not in _DRAFT_HANDLE_POINTERS:
            raise ValueError(
                "DraftActionResponseBinding.pointer must name one reviewed handle field"
            )
        if (
            not isinstance(self.step, str)
            or not self.step
            or self.step != self.step.strip()
            or len(self.step) > 160
        ):
            raise ValueError("DraftActionResponseBinding.step must be one bounded step name")
        if (
            not isinstance(self.response_pointer, str)
            or not (
                (
                    self.response_pointer.startswith("/draft/current_facts/")
                    and self.response_pointer.endswith("/handle")
                )
                or self.response_pointer
                == "/draft/action_result/created_handles/0"
            )
            or len(self.response_pointer) > 512
        ):
            raise ValueError(
                "DraftActionResponseBinding.response_pointer must select one Gateway handle"
            )


@dataclass(frozen=True, slots=True)
class DraftActionQueryIdentityBinding:
    """Allow one typed reference target to reuse an exact queried Bus identity."""

    pointer: str
    step: str

    def __post_init__(self) -> None:
        if not (
            self.pointer == "/target"
            or re.fullmatch(r"/references/(0|[1-9][0-9]*)/target", self.pointer)
        ):
            raise ValueError(
                "DraftActionQueryIdentityBinding.pointer must select one typed reference target"
            )
        if (
            not isinstance(self.step, str)
            or not self.step
            or self.step != self.step.strip()
            or len(self.step) > 160
        ):
            raise ValueError(
                "DraftActionQueryIdentityBinding.step must be one bounded step name"
            )


@dataclass(frozen=True, slots=True)
class DraftActionMetadataBinding:
    """Bind dynamic property/reference tokens to one prior live discovery."""

    step: str
    object_type: str
    required_tokens: tuple[str, ...]
    expected_projection: tuple[MetadataTokenProjection, ...] | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.step, str)
            or not self.step
            or self.step != self.step.strip()
            or len(self.step) > 160
        ):
            raise ValueError("Draft action metadata step must be bounded")
        if (
            not isinstance(self.object_type, str)
            or not self.object_type
            or self.object_type != self.object_type.strip()
            or len(self.object_type) > 256
        ):
            raise ValueError("Draft action metadata object type must be bounded")
        if (
            not self.required_tokens
            or any(
                not isinstance(token, str)
                or not token
                or token != token.strip()
                or token.startswith("@")
                or len(token) > 256
                for token in self.required_tokens
            )
            or len({token.casefold() for token in self.required_tokens})
            != len(self.required_tokens)
        ):
            raise ValueError("Draft action metadata tokens must be unique exact names")
        if self.expected_projection is not None:
            if (
                not isinstance(self.expected_projection, tuple)
                or any(
                    not isinstance(item, MetadataTokenProjection)
                    for item in self.expected_projection
                )
                or tuple(item.name for item in self.expected_projection)
                != self.required_tokens
            ):
                raise ValueError(
                    "Draft action metadata projection must match required tokens"
                )


@dataclass(frozen=True, slots=True)
class DraftActionJsonArgument:
    """One fixed business action with only Gateway response handles left dynamic."""

    expected: Mapping[str, Any]
    response_bindings: tuple[DraftActionResponseBinding, ...] = ()
    query_identity_bindings: tuple[DraftActionQueryIdentityBinding, ...] = ()
    operation: str = "object.set"
    metadata_binding: DraftActionMetadataBinding | None = None

    def __post_init__(self) -> None:
        try:
            normalized = json.loads(_canonical_json_bytes(dict(self.expected)).decode("utf-8"))
        except (
            GatewayInvocationError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise ValueError("DraftActionJsonArgument.expected must be strict JSON") from exc
        if (
            not isinstance(normalized, dict)
            or normalized.get("contract") != "waapi-skill.operation-draft-action/v1"
            or not isinstance(normalized.get("action"), str)
            or not normalized["action"]
            or normalized["action"] != normalized["action"].strip()
            or len(normalized["action"]) > 80
        ):
            raise ValueError(
                "DraftActionJsonArgument requires one versioned typed action"
            )
        forbidden = _draft_action_contains_forbidden_key(normalized)
        authored_handles = _DRAFT_HANDLE_ARGUMENT_NAMES & set(normalized)
        if forbidden or authored_handles:
            raise ValueError(
                "DraftActionJsonArgument cannot contain a complete request, native payload, "
                "or model-authored handle"
            )
        if (
            not isinstance(self.operation, str)
            or not self.operation
            or self.operation != self.operation.strip()
            or len(self.operation) > 160
        ):
            raise ValueError("DraftActionJsonArgument operation must be bounded")
        operation_actions = _DRAFT_ACTION_HANDLE_FIELDS_BY_OPERATION.get(self.operation)
        if operation_actions is None:
            raise ValueError("DraftActionJsonArgument operation is not reviewed")
        expected_handle = operation_actions.get(str(normalized["action"]), ...)
        if expected_handle is ...:
            raise ValueError("DraftActionJsonArgument action is not in the reviewed vocabulary")
        if (
            not isinstance(self.response_bindings, tuple)
            or any(
                not isinstance(binding, DraftActionResponseBinding)
                for binding in self.response_bindings
            )
            or len({binding.pointer for binding in self.response_bindings})
            != len(self.response_bindings)
        ):
            raise ValueError(
                "DraftActionJsonArgument.response_bindings must target unique handles"
            )
        bound_handle_fields = {
            binding.pointer.removeprefix("/") for binding in self.response_bindings
        }
        if bound_handle_fields != ({expected_handle} if expected_handle is not None else set()):
            raise ValueError(
                "DraftActionJsonArgument must bind exactly the handle required by its action"
            )
        if self.metadata_binding is not None:
            if self.operation != "audio.import" or not isinstance(
                self.metadata_binding, DraftActionMetadataBinding
            ):
                raise ValueError(
                    "Draft action metadata binding is valid only for audio.import"
                )
            dynamic_tokens: set[str] = set()
            if normalized["action"] == "add_import_row":
                for field in ("properties", "references"):
                    rows = normalized.get(field, [])
                    if isinstance(rows, list):
                        dynamic_tokens.update(
                            str(row.get("name"))
                            for row in rows
                            if isinstance(row, Mapping)
                            and isinstance(row.get("name"), str)
                        )
            elif (
                normalized["action"] == "set_import_default"
                and normalized.get("name") in {"properties", "references"}
                and isinstance(normalized.get("value"), list)
            ):
                dynamic_tokens.update(
                    str(row.get("name"))
                    for row in normalized["value"]
                    if isinstance(row, Mapping)
                    and isinstance(row.get("name"), str)
                )
            if not dynamic_tokens or not dynamic_tokens.issubset(
                set(self.metadata_binding.required_tokens)
            ):
                raise ValueError(
                    "Draft action dynamic tokens must come from its metadata binding"
                )
        if (
            not isinstance(self.query_identity_bindings, tuple)
            or any(
                not isinstance(binding, DraftActionQueryIdentityBinding)
                for binding in self.query_identity_bindings
            )
            or len(
                {binding.pointer for binding in self.query_identity_bindings}
            )
            != len(self.query_identity_bindings)
        ):
            raise ValueError(
                "DraftActionJsonArgument query identity bindings must be unique"
            )
        for binding in self.query_identity_bindings:
            try:
                target = _json_pointer(normalized, binding.pointer)
            except GatewayInvocationError as exc:
                raise ValueError(
                    "DraftActionJsonArgument query-bound target is absent"
                ) from exc
            valid_binding_shape = (
                normalized.get("action") == "set_reference"
                and binding.pointer == "/target"
            ) or (
                normalized.get("action") == "add_target"
                and binding.pointer.startswith("/references/")
            )
            if (
                not valid_binding_shape
                or not isinstance(target, Mapping)
                or set(target) != {"kind", "value"}
                or target.get("kind") != "path"
                or not isinstance(target.get("value"), str)
                or not target["value"].startswith("\\")
            ):
                raise ValueError(
                    "DraftActionJsonArgument query identity is valid only for "
                    "one exact path reference target"
                )


ExpectedArgument = (
    str
    | SemanticJsonArgument
    | SealedQueryIdentityBoundJsonArgument
    | MetadataQueryArgument
    | BoundedIntegerArgument
    | MetadataBoundJsonArgument
    | ResponseBinding
    | DraftActionJsonArgument
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


CommutativeReadOnlyStepGroups = tuple[tuple[str, str], ...]
CommutativeComposerSetupStepGroups = tuple[tuple[str, ...], ...]


def _is_closed_exact_id_query_step(step: ExpectedGatewayStep) -> bool:
    """Return whether one step is the fixed identity-only object read shape."""

    arguments = step.arguments
    return (
        step.subcommand == "query-object"
        and len(arguments) == 10
        and arguments[0] == "--object-id"
        and isinstance(arguments[1], str)
        and bool(arguments[1])
        and arguments[2:]
        == (
            "--return-field",
            "id",
            "--return-field",
            "name",
            "--return-field",
            "type",
            "--return-field",
            "path",
        )
    )


def validate_commutative_read_only_step_groups(
    expected_steps: Sequence[ExpectedGatewayStep],
    groups: Sequence[Sequence[str]],
) -> CommutativeReadOnlyStepGroups:
    """Validate explicitly declared adjacent read-only step permutations."""

    steps = tuple(expected_steps)
    names = tuple(step.name for step in steps)
    indexes = {name: index for index, name in enumerate(names)}
    normalized: list[tuple[str, str]] = []
    claimed: set[str] = set()
    for raw_group in groups:
        group = tuple(raw_group)
        if (
            len(group) != 2
            or any(not isinstance(name, str) or not name for name in group)
            or group[0] == group[1]
            or any(name not in indexes for name in group)
            or indexes[group[1]] != indexes[group[0]] + 1
            or any(name in claimed for name in group)
        ):
            raise ValueError(
                "commutative read-only groups must name disjoint adjacent "
                "expected steps in canonical order"
            )
        grouped_steps = (steps[indexes[group[0]]], steps[indexes[group[1]]])
        schema_metadata_pair = {
            step.subcommand for step in grouped_steps
        } == {"operation-schema", "metadata"}
        exact_id_query_pair = all(
            _is_closed_exact_id_query_step(step) for step in grouped_steps
        )
        if not schema_metadata_pair and not exact_id_query_pair:
            raise ValueError(
                "commutative read-only groups are limited to one "
                "operation-schema/metadata pair or two closed exact-ID "
                "query-object steps"
            )
        claimed.update(group)
        normalized.append((group[0], group[1]))
    return tuple(normalized)


def validate_commutative_composer_setup_step_groups(
    expected_steps: Sequence[ExpectedGatewayStep],
    groups: Sequence[Sequence[str]],
) -> CommutativeComposerSetupStepGroups:
    """Validate one metadata step moving across local, metadata-free setup.

    Starting an empty Draft and applying typed actions that carry no dynamic
    property/reference facts have no Wwise side effect and do not consume the
    metadata result.  Metadata may move across that exact contiguous setup
    prefix, but it must remain before the first metadata-bound action.
    """

    steps = tuple(expected_steps)
    names = tuple(step.name for step in steps)
    indexes = {name: index for index, name in enumerate(names)}
    normalized: list[tuple[str, ...]] = []
    claimed: set[str] = set()
    for raw_group in groups:
        group = tuple(raw_group)
        if (
            len(group) < 2
            or any(not isinstance(name, str) or not name for name in group)
            or len(set(group)) != len(group)
            or any(name not in indexes for name in group)
            or tuple(indexes[name] for name in group)
            != tuple(range(indexes[group[0]], indexes[group[0]] + len(group)))
            or any(name in claimed for name in group)
        ):
            raise ValueError(
                "commutative Composer setup groups must name disjoint contiguous "
                "expected steps in canonical order"
            )
        grouped_steps = tuple(steps[indexes[name]] for name in group)
        metadata_free_actions = grouped_steps[2:]
        if (
            grouped_steps[0].subcommand != "metadata"
            or grouped_steps[1].subcommand != "draft-start"
            or grouped_steps[1].arguments != ("audio.import",)
            or any(
                step.subcommand != "draft-apply"
                for step in metadata_free_actions
            )
            or any(
                not any(
                    isinstance(argument, DraftActionJsonArgument)
                    and argument.operation == "audio.import"
                    and argument.metadata_binding is None
                    for argument in step.arguments
                )
                for step in metadata_free_actions
            )
        ):
            raise ValueError(
                "commutative Composer setup groups are limited to metadata, "
                "audio.import draft-start, then metadata-free typed actions"
            )
        claimed.update(group)
        normalized.append(group)
    return tuple(normalized)


def _commutative_composer_setup_pairs(
    groups: Sequence[Sequence[str]],
) -> set[frozenset[str]]:
    """Return only the adjacent swaps reachable by moving metadata right."""

    pairs: set[frozenset[str]] = set()
    for raw_group in groups:
        group = tuple(raw_group)
        if len(group) >= 2:
            pairs.update(
                frozenset((group[0], name)) for name in group[1:]
            )
    return pairs


_DRAFT_SUBCOMMANDS = frozenset(
    {
        "draft-start",
        "draft-inspect",
        "draft-apply",
        "draft-check",
        "draft-cancel",
        "preview-from-draft",
    }
)
_DRAFT_ID_RE = re.compile(r"^od1-[0-9a-f]{32}$")
_DRAFT_AUTHORITY_RE = re.compile(r"^da1-[0-9a-f]{40}$")
_DRAFT_HANDLE_RE = re.compile(r"^odh1-[0-9a-f]{24}$")
_NUMBERED_DRAFT_ACTION_STEP_RE = re.compile(r"^(?P<prefix>.+\.action\.)\d{3}$")


def _draft_projection_handles(value: Any) -> set[str]:
    handles: set[str] = set()
    if isinstance(value, Mapping):
        handle = value.get("handle")
        if isinstance(handle, str):
            handles.add(handle)
        for nested in value.values():
            handles.update(_draft_projection_handles(nested))
    elif isinstance(value, list):
        for nested in value:
            handles.update(_draft_projection_handles(nested))
    return handles


def _draft_compact_action_result(
    draft: Mapping[str, Any],
) -> tuple[str, set[str], set[str], Mapping[str, Any]]:
    result = draft.get("action_result")
    summary = draft.get("current_facts_summary")
    if (
        not isinstance(result, Mapping)
        or set(result)
        != {"contract", "action", "created_handles", "affected_handles"}
        or result.get("contract")
        != "waapi-skill.operation-draft-action-result/v1"
        or not isinstance(result.get("action"), str)
        or not isinstance(result.get("created_handles"), list)
        or not isinstance(result.get("affected_handles"), list)
        or any(
            not isinstance(handle, str)
            or _DRAFT_HANDLE_RE.fullmatch(handle) is None
            for key in ("created_handles", "affected_handles")
            for handle in result[key]
        )
        or len(set(result["created_handles"])) != len(result["created_handles"])
        or len(set(result["affected_handles"])) != len(result["affected_handles"])
        or not isinstance(summary, Mapping)
        or set(summary)
        != {
            "contract",
            "target_count",
            "handle_count",
            "canonical_sha256",
        }
        or summary.get("contract")
        != "waapi-skill.operation-draft-facts-summary/v1"
        or type(summary.get("target_count")) is not int
        or type(summary.get("handle_count")) is not int
        or summary["target_count"] < 0
        or summary["handle_count"] < 0
        or not isinstance(summary.get("canonical_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", summary["canonical_sha256"]) is None
        or "current_facts" in draft
    ):
        raise GatewayInvocationError(
            "compact Draft action response has an invalid bounded projection"
        )
    return (
        str(result["action"]),
        set(result["created_handles"]),
        set(result["affected_handles"]),
        summary,
    )


def validate_operation_draft_protocol_steps(
    expected_steps: Sequence[ExpectedGatewayStep],
) -> None:
    """Fail closed unless every Draft flow binds authority to prior responses."""

    steps = tuple(expected_steps)
    draft_steps = tuple(step for step in steps if step.subcommand in _DRAFT_SUBCOMMANDS)
    if not draft_steps:
        return
    starts = tuple(step for step in draft_steps if step.subcommand == "draft-start")
    if len(starts) > 1:
        indexes = {step.name: index for index, step in enumerate(steps)}
        start_indexes = tuple(indexes[step.name] for step in starts)
        terminal_indexes: list[int] = []
        for flow_index, start_index in enumerate(start_indexes):
            next_start = (
                start_indexes[flow_index + 1]
                if flow_index + 1 < len(start_indexes)
                else len(steps)
            )
            terminals = tuple(
                index
                for index in range(start_index + 1, next_start)
                if steps[index].subcommand
                in {"draft-cancel", "preview-from-draft"}
            )
            if len(terminals) != 1:
                raise ValueError(
                    "each typed Draft flow requires exactly one terminal command"
                )
            terminal_indexes.append(terminals[0])
        covered_draft_indexes: set[int] = set()
        for flow_index, terminal_index in enumerate(terminal_indexes):
            segment_start = (
                0 if flow_index == 0 else terminal_indexes[flow_index - 1] + 1
            )
            segment = steps[segment_start : terminal_index + 1]
            validate_operation_draft_protocol_steps(segment)
            covered_draft_indexes.update(
                range(segment_start, terminal_index + 1)
            )
        if any(
            index not in covered_draft_indexes
            for index, step in enumerate(steps)
            if step.subcommand in _DRAFT_SUBCOMMANDS
        ):
            raise ValueError("typed Draft command lies outside one complete flow")
        return
    if len(starts) != 1:
        raise ValueError("a typed Draft protocol requires exactly one draft-start step")
    start = starts[0]
    if (
        len(start.arguments) != 1
        or not isinstance(start.arguments[0], str)
        or not start.arguments[0]
        or start.arguments[0] != start.arguments[0].strip()
    ):
        raise ValueError("draft-start must bind one exact operation name")
    draft_operation = start.arguments[0]
    for step in steps:
        if step.subcommand not in {"preview", "legacy-preview"}:
            continue
        request_arguments = tuple(
            argument.expected
            for argument in step.arguments
            if isinstance(
                argument,
                (
                    SemanticJsonArgument,
                    MetadataBoundJsonArgument,
                    SealedQueryIdentityBoundJsonArgument,
                ),
            )
        )
        if any(request.get("operation") == draft_operation for request in request_arguments):
            raise ValueError(
                "a typed Draft protocol cannot expose a complete JSON ingress "
                "for the same operation"
            )
    indexes = {step.name: index for index, step in enumerate(steps)}
    start_index = indexes[start.name]
    terminal_draft_indexes = tuple(
        indexes[step.name]
        for step in draft_steps
        if step.subcommand in {"draft-cancel", "preview-from-draft"}
    )
    if len(terminal_draft_indexes) > 1:
        raise ValueError("a typed Draft protocol has only one terminal Draft command")
    if (
        terminal_draft_indexes
        and terminal_draft_indexes[0] != indexes[draft_steps[-1].name]
    ):
        raise ValueError("no typed Draft command may follow its terminal command")
    draft_end_index = (
        terminal_draft_indexes[0]
        if terminal_draft_indexes
        else indexes[draft_steps[-1].name]
    )
    if any(
        step.subcommand not in _DRAFT_SUBCOMMANDS
        for step in steps[start_index : draft_end_index + 1]
    ):
        raise ValueError(
            "typed Draft composition cannot be interrupted by another Gateway route"
        )

    def require_prior_binding(
        value: Any,
        *,
        step: ExpectedGatewayStep,
        source_step: str,
        pointer: str,
        label: str,
    ) -> None:
        if (
            not isinstance(value, ResponseBinding)
            or value.step != source_step
            or value.pointer != pointer
            or indexes.get(value.step, len(steps)) >= indexes[step.name]
        ):
            raise ValueError(f"{step.subcommand} must bind {label} to {source_step}{pointer}")

    latest_revision_step = start.name
    for step in draft_steps:
        index = indexes[step.name]
        if step is start:
            continue
        if index <= start_index:
            raise ValueError("all typed Draft commands must follow draft-start")
        arguments = step.arguments
        minimum = 3 if step.subcommand == "draft-inspect" else 5
        if len(arguments) < minimum:
            raise ValueError(f"{step.subcommand} arguments are incomplete")
        require_prior_binding(
            arguments[0],
            step=step,
            source_step=start.name,
            pointer="/draft/draft_id",
            label="draft ID",
        )
        if arguments[1] != "--task-authority":
            raise ValueError(f"{step.subcommand} must carry task authority")
        require_prior_binding(
            arguments[2],
            step=step,
            source_step=start.name,
            pointer="/task_authority",
            label="task authority",
        )
        if step.subcommand == "draft-inspect":
            if len(arguments) != 3:
                raise ValueError("draft-inspect accepts only its bound draft authority")
            latest_revision_step = step.name
            continue
        if arguments[3] != "--expected-revision" or not isinstance(
            arguments[4], ResponseBinding
        ):
            raise ValueError(f"{step.subcommand} must bind one expected revision")
        revision_binding = arguments[4]
        if (
            revision_binding.pointer != "/draft/revision"
            or revision_binding.step != latest_revision_step
            or indexes.get(revision_binding.step, len(steps)) >= index
            or steps[indexes[revision_binding.step]].subcommand
            not in {"draft-start", "draft-apply", "draft-check", "draft-inspect"}
        ):
            raise ValueError(
                f"{step.subcommand} expected revision must come from one prior Draft response"
            )
        if step.subcommand == "draft-apply":
            compact_action = (
                len(arguments) == 8
                and arguments[5:7] == ("--compact", "--action-json")
                and isinstance(arguments[7], DraftActionJsonArgument)
            )
            legacy_full_action = (
                len(arguments) == 7
                and arguments[5] == "--action-json"
                and isinstance(arguments[6], DraftActionJsonArgument)
            )
            if not compact_action and not legacy_full_action:
                raise ValueError(
                    "draft-apply must carry exactly one typed Draft action"
                )
            action_argument = arguments[-1]
            assert isinstance(action_argument, DraftActionJsonArgument)
            if action_argument.operation != draft_operation:
                raise ValueError(
                    "typed Draft action operation must match draft-start"
                )
            for binding in action_argument.response_bindings:
                source_index = indexes.get(binding.step)
                if (
                    source_index is None
                    or source_index >= index
                    or steps[source_index].subcommand != "draft-apply"
                ):
                    raise ValueError(
                        "typed Draft action handles must come from one prior draft-apply response"
                    )
            for binding in action_argument.query_identity_bindings:
                source_index = indexes.get(binding.step)
                if (
                    source_index is None
                    or source_index >= start_index
                    or steps[source_index].subcommand != "query-object"
                ):
                    raise ValueError(
                        "typed Draft action query identities must come from one "
                        "pre-Draft query-object response"
                    )
            metadata_binding = action_argument.metadata_binding
            if metadata_binding is not None:
                source_index = indexes.get(metadata_binding.step)
                if (
                    source_index is None
                    or source_index >= start_index
                    or steps[source_index].subcommand != "metadata"
                ):
                    raise ValueError(
                        "typed Draft action metadata must come from one pre-Draft read"
                    )
        elif any(isinstance(value, DraftActionJsonArgument) for value in arguments):
            raise ValueError("typed Draft actions are valid only on draft-apply")
        if step.subcommand in {"draft-check", "draft-cancel"} and len(arguments) != 5:
            raise ValueError(f"{step.subcommand} accepts only bound Draft authority and revision")
        if step.subcommand == "preview-from-draft":
            trailing = arguments[5:]
            valid_trailing = trailing in {
                (),
                ("--apply",),
            } or (
                len(trailing) in {2, 3}
                and trailing[-2] == "--ttl"
                and isinstance(trailing[-1], str)
                and trailing[-1].isdigit()
                and int(trailing[-1]) > 0
                and (len(trailing) == 2 or trailing[0] == "--apply")
            )
            if not valid_trailing:
                raise ValueError(
                    "preview-from-draft trailing policy arguments must be fixed literals"
                )
        latest_revision_step = step.name


def gateway_step_prefix_matches(
    expected: Sequence[str],
    actual: Sequence[str],
    groups: Sequence[Sequence[str]] = (),
    composer_setup_groups: Sequence[Sequence[str]] = (),
) -> bool:
    """Match one dependency-valid observed prefix of the expected sequence."""

    expected_names = tuple(expected)
    actual_names = tuple(actual)
    if len(actual_names) > len(expected_names):
        return False
    permitted_pairs = {
        frozenset(tuple(group))
        for group in tuple(groups)
        if len(tuple(group)) == 2
    } | _commutative_composer_setup_pairs(composer_setup_groups)
    reachable = {expected_names}
    pending = [expected_names]
    while pending:
        current = pending.pop()
        for index in range(len(current) - 1):
            if frozenset(current[index : index + 2]) not in permitted_pairs:
                continue
            swapped = (
                *current[:index],
                current[index + 1],
                current[index],
                *current[index + 2 :],
            )
            if swapped not in reachable:
                reachable.add(swapped)
                pending.append(swapped)

    return any(
        _gateway_step_prefix_matches_one_order(order, actual_names)
        for order in reachable
    )


def _gateway_step_prefix_matches_one_order(
    expected_names: tuple[str, ...],
    actual_names: tuple[str, ...],
) -> bool:
    """Match one fixed order plus dependency-ready numbered Draft actions."""

    index = 0
    while index < len(actual_names):
        numbered = _NUMBERED_DRAFT_ACTION_STEP_RE.fullmatch(
            expected_names[index]
        )
        if numbered is not None:
            prefix = numbered.group("prefix")
            end = index
            while (
                end < len(expected_names)
                and (candidate := _NUMBERED_DRAFT_ACTION_STEP_RE.fullmatch(
                    expected_names[end]
                ))
                is not None
                and candidate.group("prefix") == prefix
            ):
                end += 1
            expected_group = expected_names[index:end]
            supplied_group = actual_names[index : min(end, len(actual_names))]
            if (
                len(set(supplied_group)) != len(supplied_group)
                or not set(supplied_group) <= set(expected_group)
            ):
                return False
            index += len(supplied_group)
            continue
        if actual_names[index] != expected_names[index]:
            return False
        index += 1
    return True


def gateway_step_sequence_matches(
    expected: Sequence[str],
    actual: Sequence[str],
    groups: Sequence[Sequence[str]] = (),
    composer_setup_groups: Sequence[Sequence[str]] = (),
) -> bool:
    """Match declared pair swaps and exact numbered Draft-action permutations."""

    return len(tuple(expected)) == len(tuple(actual)) and gateway_step_prefix_matches(
        expected,
        actual,
        groups,
        composer_setup_groups,
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
    commutative_read_only_step_groups: CommutativeReadOnlyStepGroups = ()
    commutative_composer_setup_step_groups: CommutativeComposerSetupStepGroups = ()

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
        record_names = tuple(record.step_name for record in self.records)
        return (
            self.complete
            and self.terminal_state == _BROKER_COMPLETE
            and len(self.successful_records) == len(self.expected_step_names)
            and len(self.records) == len(self.expected_step_names)
            and not self.rejected_records
            and all(record.succeeded for record in self.records)
            and record_names == self.consumed_step_names
            and gateway_step_sequence_matches(
                self.expected_step_names,
                self.consumed_step_names,
                self.commutative_read_only_step_groups,
                self.commutative_composer_setup_step_groups,
            )
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
        if not self.commutative_read_only_step_groups:
            payload.pop("commutative_read_only_step_groups")
        if not self.commutative_composer_setup_step_groups:
            payload.pop("commutative_composer_setup_step_groups")
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


def _switch_container_remove_assignment_arguments(
    value: Any,
) -> Mapping[str, Any]:
    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or set(value) != {"contract", "version", "operation", "arguments"}
        or value.get("contract") != "waapi-skill.operation-request/v1"
        or value.get("version") not in _SUPPORTED_WWISE_VERSIONS
        or value.get("operation") != "switchContainer.removeAssignment"
    ):
        raise ValueError(
            "switch_container_remove_assignment_v1 requires one closed "
            "switchContainer.removeAssignment request"
        )
    arguments = value.get("arguments")
    if (
        not isinstance(arguments, Mapping)
        or not all(isinstance(key, str) for key in arguments)
        or set(arguments)
        != {"switch_container", "child", "state_or_switch"}
        or any(
            not isinstance(arguments.get(field), Mapping)
            for field in ("switch_container", "child", "state_or_switch")
        )
    ):
        raise ValueError(
            "switch_container_remove_assignment_v1 arguments are not closed"
        )
    return arguments


def _scoped_name_exact_child_path(value: Any) -> str | None:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"kind", "name", "type", "parent"}
        or value.get("kind") != "scoped-name"
        or not isinstance(value.get("name"), str)
        or not value.get("name")
        or len(value["name"]) > _AUDIO_IMPORT_IDENTITY_MAX_NAME_LENGTH
        or "\\" in value["name"]
        or not isinstance(value.get("type"), str)
        or not value.get("type")
        or len(value["type"]) > _AUDIO_IMPORT_IDENTITY_MAX_TYPE_LENGTH
        or _AUDIO_IMPORT_IDENTITY_TYPE_TOKEN_RE.fullmatch(value["type"])
        is None
    ):
        return None
    parent = value.get("parent")
    if (
        not isinstance(parent, Mapping)
        or set(parent) != {"kind", "value"}
        or parent.get("kind") != "path"
        or not isinstance(parent.get("value"), str)
        or not parent.get("value").startswith("\\")
        or parent.get("value").endswith("\\")
        or len(parent["value"]) > _AUDIO_IMPORT_IDENTITY_MAX_PARENT_LENGTH
    ):
        return None
    return f'{parent["value"]}\\{value["name"]}'


def _switch_remove_identity_equal(actual: Any, expected: Any) -> bool:
    if _canonical_json_bytes(actual) == _canonical_json_bytes(expected):
        return True
    exact_child_path = _scoped_name_exact_child_path(expected)
    return bool(
        exact_child_path is not None
        and isinstance(actual, Mapping)
        and set(actual) == {"kind", "value"}
        and actual.get("kind") == "path"
        and actual.get("value") == exact_child_path
    )


def _switch_remove_container_identity_equal(actual: Any, expected: Any) -> bool:
    if _canonical_json_bytes(actual) == _canonical_json_bytes(expected):
        return True
    if (
        not isinstance(expected, Mapping)
        or set(expected) != {"kind", "value"}
        or expected.get("kind") != "path"
        or not isinstance(expected.get("value"), str)
        or not expected.get("value").startswith("\\")
        or expected.get("value").endswith("\\")
    ):
        return False
    expected_name = expected["value"].rsplit("\\", 1)[-1]
    return bool(
        expected_name
        and isinstance(actual, Mapping)
        and set(actual) == {"kind", "type", "name"}
        and actual.get("kind") == "exact-type-name"
        and actual.get("type") == "SwitchContainer"
        and actual.get("name") == expected_name
    )


def _switch_container_remove_assignment_json_equal(
    actual: Any,
    expected: Any,
) -> bool:
    """Accept only exact scoped identities or their one sealed full path.

    The equivalence belongs solely to ``switchContainer.removeAssignment``.
    Its container identity may use the sealed exact path or the exact
    ``SwitchContainer`` type/name derived from that path; live Gateway
    resolution must still prove uniqueness.  Child/value path alternatives are
    derived from the expected scoped-name's already sealed parent and exact
    direct-child name, so basename, suffix, or deeper-descendant matches are
    never accepted.
    """

    try:
        actual_arguments = _switch_container_remove_assignment_arguments(actual)
        expected_arguments = _switch_container_remove_assignment_arguments(
            expected
        )
    except (TypeError, ValueError):
        return False
    if (
        actual.get("contract") != expected.get("contract")
        or actual.get("version") != expected.get("version")
        or actual.get("operation") != expected.get("operation")
        or not _switch_remove_container_identity_equal(
            actual_arguments["switch_container"],
            expected_arguments["switch_container"],
        )
    ):
        return False
    return all(
        _switch_remove_identity_equal(
            actual_arguments[field],
            expected_arguments[field],
        )
        for field in ("child", "state_or_switch")
    )


def _semantic_json_equal(actual: Any, expected: SemanticJsonArgument) -> bool:
    if expected.equivalence == "wire_exact":
        return _canonical_json_bytes(actual) == _canonical_json_bytes(
            expected.expected
        )
    if expected.equivalence == _SWITCH_CONTAINER_REMOVE_ASSIGNMENT_EQUIVALENCE:
        return _switch_container_remove_assignment_json_equal(
            actual,
            expected.expected,
        )
    if expected.equivalence == _AUDIO_IMPORT_DEFAULT_OPERATION_EQUIVALENCE:
        try:
            normalized_actual = _normalize_audio_import_default_operation_request(
                actual
            )
            normalized_expected = _normalize_audio_import_default_operation_request(
                expected.expected
            )
        except (TypeError, ValueError):
            return False
        return _canonical_json_bytes(normalized_actual) == _canonical_json_bytes(
            normalized_expected
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


def _normalize_audio_import_default_operation_request(
    value: Any,
) -> dict[str, Any]:
    """Normalize only audio.import's documented createNew batch default."""

    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or set(value) != {"contract", "version", "operation", "arguments"}
        or value.get("contract") != "waapi-skill.operation-request/v1"
        or value.get("version") not in _SUPPORTED_WWISE_VERSIONS
        or value.get("operation") != "audio.import"
    ):
        raise ValueError(
            "audio_import_default_operation_v1 requires one closed "
            "audio.import request"
        )
    arguments_value = value.get("arguments")
    if (
        not isinstance(arguments_value, Mapping)
        or not all(isinstance(key, str) for key in arguments_value)
        or "imports" not in arguments_value
        or set(arguments_value)
        - {
            "imports",
            "import_operation",
            "defaults",
            "auto_add_to_source_control",
        }
    ):
        raise ValueError(
            "audio_import_default_operation_v1 arguments are not closed"
        )
    if (
        "auto_add_to_source_control" in arguments_value
        and not isinstance(arguments_value["auto_add_to_source_control"], bool)
    ):
        raise ValueError(
            "audio_import_default_operation_v1 auto_add_to_source_control "
            "must be a JSON boolean"
        )
    # Reuse the full validator only as a validity check.  Its broader semantic
    # normalization is intentionally discarded: this equivalence permits one
    # omission and keeps every other JSON value and array order wire-exact.
    _normalize_audio_import_request(value)
    normalized = dict(value)
    arguments = dict(arguments_value)
    operation = arguments.get("import_operation", "createNew")
    if operation not in _AUDIO_IMPORT_TAB_OPERATIONS:
        raise ValueError(
            "audio_import_default_operation_v1 import_operation is invalid"
        )
    arguments["import_operation"] = operation
    normalized["arguments"] = arguments
    return normalized


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
                metadata_bound=expected,
            ):
                return False
            normalized_actual = _normalize_metadata_bound_audio_import_request(
                actual,
                expected,
            )
            normalized_expected = (
                _normalize_metadata_bound_audio_import_request(
                    expected.expected,
                    expected,
                )
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
        elif expected.equivalence == "object_set_rtpc_v1":
            normalized_actual = _normalize_object_set_rtpc_request(actual)
            normalized_expected = _normalize_object_set_rtpc_request(
                expected.expected
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
        return _normalize_metadata_bound_audio_import_request(actual, expected)
    if expected.equivalence == "audio_import_tab_v1":
        return _normalize_audio_import_tab_request(actual)
    if expected.equivalence == "object_set_v1":
        return _normalize_metadata_bound_object_set_request(actual, expected)
    if expected.equivalence == "object_set_rtpc_v1":
        return _normalize_object_set_rtpc_request(actual)
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
    for field, default in OBJECT_SET_SCHEMA_DEFAULTS.items():
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
    return _normalize_metadata_bound_real_property_values(
        normalized,
        expected,
    )


def _normalize_metadata_bound_audio_import_request(
    value: Any,
    expected: MetadataBoundJsonArgument,
) -> dict[str, Any]:
    """Canonicalize reviewed audio.import semantic equivalences."""

    normalized = _normalize_audio_import_request(value)
    normalized = _normalize_metadata_bound_real_property_values(
        normalized,
        expected,
    )
    expected_normalized = _normalize_metadata_bound_real_property_values(
        _normalize_audio_import_request(expected.expected),
        expected,
    )
    return _materialize_gateway_derived_reference_activations(
        normalized,
        expected_normalized=expected_normalized,
        allowances=expected.gateway_derived_reference_activations,
    )


def _validate_gateway_derived_reference_activation_allowances(
    expected: MetadataBoundJsonArgument,
    normalized_request: Mapping[str, Any],
) -> None:
    """Bind every allowance to trusted request rows and live metadata."""

    allowances = expected.gateway_derived_reference_activations
    if not allowances:
        return
    projection = expected.expected_required_token_projection
    if projection is None:
        raise ValueError(
            "Gateway-derived reference activation allowances require a "
            "trusted live metadata projection"
        )
    projection_by_name = {item.name: item for item in projection}
    raw_arguments = (
        expected.expected.get("arguments")
        if isinstance(expected.expected, Mapping)
        else None
    )
    raw_imports = (
        raw_arguments.get("imports")
        if isinstance(raw_arguments, Mapping)
        else None
    )
    normalized_arguments = normalized_request.get("arguments")
    normalized_imports = (
        normalized_arguments.get("imports")
        if isinstance(normalized_arguments, Mapping)
        else None
    )
    if not isinstance(raw_imports, list) or not isinstance(
        normalized_imports,
        list,
    ):
        raise ValueError(
            "Gateway-derived reference activation allowances require "
            "audio.import rows"
        )
    default_properties, default_references = (
        _audio_import_default_named_fields(expected.expected)
    )
    for allowance in allowances:
        property_projection = projection_by_name.get(
            allowance.property_name
        )
        reference_projection = projection_by_name.get(
            allowance.reference_name
        )
        if (
            property_projection is None
            or property_projection.kind != "property"
            or property_projection.metadata_type.casefold()
            not in {"bool", "boolean"}
            or reference_projection is None
            or reference_projection.kind != "reference"
        ):
            raise ValueError(
                "Gateway-derived reference activation allowances must bind "
                "one live Boolean property and one live reference"
            )
        if (
            allowance.property_name in default_properties
            or allowance.reference_name in default_references
        ):
            raise ValueError(
                "Gateway-derived reference activation allowances must be "
                "bound to explicit import rows, not defaults"
            )
        if allowance.row_index >= len(raw_imports):
            raise ValueError(
                "Gateway-derived reference activation allowance row is "
                "outside the trusted import request"
            )
        raw_row = raw_imports[allowance.row_index]
        normalized_row = normalized_imports[allowance.row_index]
        if not isinstance(raw_row, Mapping) or not isinstance(
            normalized_row,
            Mapping,
        ):
            raise ValueError(
                "Gateway-derived reference activation allowance row is invalid"
            )
        row_properties = _named_audio_import_fields(
            raw_row.get("properties", []),
            path=(
                "arguments.imports"
                f"[{allowance.row_index}].properties"
            ),
            kind="property",
        )
        row_references = _named_audio_import_fields(
            raw_row.get("references", []),
            path=(
                "arguments.imports"
                f"[{allowance.row_index}].references"
            ),
            kind="reference",
        )
        property_item = row_properties.get(allowance.property_name)
        if (
            property_item is None
            or property_item.get("value")
            is not allowance.property_value
            or allowance.reference_name not in row_references
        ):
            raise ValueError(
                "Gateway-derived reference activation allowance must match "
                "an explicit trusted row property and related reference"
            )


def _materialize_gateway_derived_reference_activations(
    normalized: dict[str, Any],
    *,
    expected_normalized: Mapping[str, Any],
    allowances: Sequence[GatewayDerivedReferenceActivationAllowance],
) -> dict[str, Any]:
    """Fill only omitted row activators the production Gateway will derive."""

    if not allowances:
        return normalized
    arguments = normalized.get("arguments")
    expected_arguments = expected_normalized.get("arguments")
    imports = (
        arguments.get("imports")
        if isinstance(arguments, Mapping)
        else None
    )
    expected_imports = (
        expected_arguments.get("imports")
        if isinstance(expected_arguments, Mapping)
        else None
    )
    if not isinstance(imports, list) or not isinstance(
        expected_imports,
        list,
    ):
        raise ValueError(
            "audio_import_v1 Gateway derivation rows are unavailable"
        )
    for allowance in allowances:
        if allowance.row_index >= len(imports):
            continue
        row = imports[allowance.row_index]
        expected_row = expected_imports[allowance.row_index]
        if not isinstance(row, Mapping) or not isinstance(
            expected_row,
            Mapping,
        ):
            continue
        actual_properties = _named_audio_import_fields(
            row.get("properties", []),
            path=(
                "arguments.imports"
                f"[{allowance.row_index}].properties"
            ),
            kind="property",
        )
        if any(
            name.casefold() == allowance.property_name.casefold()
            for name in actual_properties
        ):
            continue
        actual_references = _named_audio_import_fields(
            row.get("references", []),
            path=(
                "arguments.imports"
                f"[{allowance.row_index}].references"
            ),
            kind="reference",
        )
        if allowance.reference_name not in actual_references:
            continue
        expected_properties = _named_audio_import_fields(
            expected_row.get("properties", []),
            path=(
                "trusted.arguments.imports"
                f"[{allowance.row_index}].properties"
            ),
            kind="property",
        )
        expected_item = expected_properties.get(allowance.property_name)
        if (
            expected_item is None
            or expected_item.get("value")
            is not allowance.property_value
        ):
            raise ValueError(
                "trusted Gateway-derived reference activation is invalid"
            )
        updated_row = dict(row)
        updated_row["properties"] = sorted(
            [*actual_properties.values(), dict(expected_item)],
            key=lambda item: str(item["name"]),
        )
        imports[allowance.row_index] = updated_row
    updated_arguments = dict(arguments)
    updated_arguments["imports"] = imports
    result = dict(normalized)
    result["arguments"] = updated_arguments
    return result


def _normalize_metadata_bound_real_property_values(
    normalized: dict[str, Any],
    expected: MetadataBoundJsonArgument,
) -> dict[str, Any]:
    """Canonicalize integral spellings only for live-proven real properties."""

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


def _normalize_object_set_rtpc_request(value: Any) -> dict[str, Any]:
    """Normalize only RTPC numeric spellings and its declared default mode."""

    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or set(value) != {"contract", "version", "operation", "arguments"}
        or value.get("contract") != "waapi-skill.operation-request/v1"
        or value.get("version") not in _OBJECT_SET_SUPPORTED_VERSIONS
        or value.get("operation") != "object.setRTPC"
    ):
        raise ValueError(
            "object_set_rtpc_v1 requires one closed object.setRTPC request"
        )
    arguments = value.get("arguments")
    if (
        not isinstance(arguments, Mapping)
        or not all(isinstance(key, str) for key in arguments)
        or not _OBJECT_SET_RTPC_REQUIRED_ARGUMENT_FIELDS.issubset(arguments)
        or set(arguments)
        - (
            _OBJECT_SET_RTPC_REQUIRED_ARGUMENT_FIELDS
            | _OBJECT_SET_RTPC_OPTIONAL_ARGUMENT_FIELDS
        )
        or not isinstance(arguments.get("object"), Mapping)
        or not isinstance(arguments.get("control_input"), Mapping)
        or not isinstance(arguments.get("property"), str)
        or not arguments["property"]
        or arguments["property"] != arguments["property"].strip()
        or (
            "notes" in arguments
            and not isinstance(arguments.get("notes"), str)
        )
        or arguments.get("mode", "add_or_replace")
        not in {"add", "add_or_replace"}
    ):
        raise ValueError("object_set_rtpc_v1 arguments are not closed")
    points = arguments.get("points")
    if (
        not isinstance(points, list)
        or not 1 <= len(points) <= 256
    ):
        raise ValueError(
            "object_set_rtpc_v1 points must be a bounded non-empty array"
        )
    normalized_points: list[dict[str, Any]] = []
    for index, point in enumerate(points):
        if (
            not isinstance(point, Mapping)
            or not all(isinstance(key, str) for key in point)
            or set(point) != {"x", "y", "shape"}
            or type(point.get("x")) not in {int, float}
            or type(point.get("y")) not in {int, float}
            or not math.isfinite(float(point["x"]))
            or not math.isfinite(float(point["y"]))
            or point.get("shape") not in _OBJECT_SET_RTPC_POINT_SHAPES
        ):
            raise ValueError(
                f"object_set_rtpc_v1 points[{index}] is invalid"
            )
        x = float(point["x"])
        y = float(point["y"])
        normalized_points.append(
            {
                "x": 0.0 if x == 0.0 else x,
                "y": 0.0 if y == 0.0 else y,
                "shape": point["shape"],
            }
        )
    normalized_arguments = dict(arguments)
    normalized_arguments["points"] = normalized_points
    normalized_arguments.setdefault("mode", "add_or_replace")
    normalized = dict(value)
    normalized["arguments"] = normalized_arguments
    return normalized


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
    *,
    metadata_bound: MetadataBoundJsonArgument,
) -> bool:
    """Permit trusted defaults to remain or expand, never to be refactored."""

    actual_properties, actual_references = (
        _audio_import_default_named_fields(actual)
    )
    expected_properties, expected_references = (
        _audio_import_default_named_fields(expected)
    )
    real_property_names = {
        item.name
        for item in (
            metadata_bound.expected_required_token_projection or ()
        )
        if item.kind == "property"
        and item.metadata_type.casefold()
        in {"real32", "real64", "float", "double"}
    }
    for actual_fields, expected_fields, property_fields in (
        (actual_properties, expected_properties, True),
        (actual_references, expected_references, False),
    ):
        if any(
            name not in expected_fields
            or _canonical_json_bytes(
                _normalize_named_real_property_item(
                    item,
                    real_property_names=real_property_names,
                )
                if property_fields
                else item
            )
            != _canonical_json_bytes(
                _normalize_named_real_property_item(
                    expected_fields[name],
                    real_property_names=real_property_names,
                )
                if property_fields
                else expected_fields[name]
            )
            for name, item in actual_fields.items()
        ):
            return False
    return True


def _normalize_named_real_property_item(
    item: Mapping[str, Any],
    *,
    real_property_names: set[str],
) -> dict[str, Any]:
    normalized = dict(item)
    value = normalized.get("value")
    if normalized.get("name") in real_property_names and type(value) is int:
        converted = float(value)
        if math.isfinite(converted) and converted == value:
            normalized["value"] = converted
    return normalized


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
        _canonicalize_audio_import_media_object_type(row)
        normalized_imports.append(row)

    normalized_arguments["imports"] = normalized_imports
    normalized_request["arguments"] = normalized_arguments
    return normalized_request


def _canonicalize_audio_import_media_object_type(
    row: dict[str, Any],
) -> None:
    """Normalize only production-proven generic Sound import semantics.

    The production import contract treats ``Sound`` as the generic spelling
    behind the reviewed ``Sound SFX`` and ``Sound Voice`` import forms.  Those
    two specialized forms are not interchangeable: the effective import
    language decides which one can be equivalent to ``Sound``.  Structure-only
    rows stay exact.  An untyped row with exactly one effective media source
    may omit ``object_type`` because the production import Builder deliberately
    leaves the native field absent and Wwise creates the generic Sound object.
    Typed final path segments are inferred by production rather than defaulted,
    so they remain exact here.

    Other reviewed import-syntax pairs are deliberately excluded.  For
    example, Random/Sequence Container and ActorMixer/PropertyContainer make a
    typed path compatible with an explicit field; they do not make two complete
    operation requests semantically identical.
    """

    media_fields = tuple(
        field
        for field in ("audio_file", "audio_file_base64")
        if field in row
    )
    if len(media_fields) != 1:
        return
    if "object_type" not in row:
        object_path = row.get("object_path")
        if not isinstance(object_path, str) or not object_path:
            return
        leaf = object_path.rsplit("\\", 1)[-1]
        if "<" in leaf or ">" in leaf:
            return
        row["object_type"] = "Sound"
    object_type = row.get("object_type")
    import_language = row.get("import_language")
    if not isinstance(object_type, str) or not isinstance(
        import_language,
        str,
    ):
        return
    object_type_token = re.sub(
        r"[^a-z0-9]",
        "",
        object_type.casefold(),
    )
    language_is_sfx = import_language.casefold() == "sfx"
    compatible_tokens = (
        {"sound", "soundsfx"}
        if language_is_sfx
        else {"sound", "soundvoice"}
    )
    if object_type_token in compatible_tokens:
        row["object_type"] = "Sound"


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
            isinstance(identity, str) and bool(identity.strip())
        ) or (
            isinstance(identity, int) and not isinstance(identity, bool)
        )
    if kind == "path" and set(value) == {"kind", "value"}:
        path = value.get("value")
        return isinstance(path, str) and path.startswith("\\")
    if kind == "exact-type-name" and set(value) == {
        "kind",
        "type",
        "name",
    }:
        return _is_audio_import_exact_type(value.get("type")) and (
            _is_audio_import_exact_name(value.get("name"))
        )
    if kind == "direct-child" and set(value) == {
        "kind",
        "parent",
        "type",
    }:
        parent = value.get("parent")
        object_type = value.get("type")
        return (
            _is_audio_import_parent_identity(parent)
            and isinstance(object_type, str)
            and bool(object_type)
            and object_type == object_type.strip()
            and len(object_type) <= _AUDIO_IMPORT_IDENTITY_MAX_TYPE_LENGTH
            and _is_audio_import_waql_literal(object_type)
        )
    if kind == "scoped-name" and set(value) == {
        "kind",
        "name",
        "type",
        "parent",
    }:
        parent = value.get("parent")
        return (
            _is_audio_import_exact_name(value.get("name"))
            and _is_audio_import_exact_type(value.get("type"))
            and _is_audio_import_parent_identity(parent)
        )
    return False


def _is_audio_import_exact_type(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= _AUDIO_IMPORT_IDENTITY_MAX_TYPE_LENGTH
        and _AUDIO_IMPORT_IDENTITY_TYPE_TOKEN_RE.fullmatch(value) is not None
    )


def _is_audio_import_exact_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= _AUDIO_IMPORT_IDENTITY_MAX_NAME_LENGTH
        and "\\" not in value
        and _is_audio_import_waql_literal(value)
    )


def _is_audio_import_parent_identity(value: Any) -> bool:
    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, str) for key in value)
        or set(value) != {"kind", "value"}
        or value.get("kind") not in {"id", "path"}
    ):
        return False
    identity = value.get("value")
    if value.get("kind") == "id":
        if isinstance(identity, int) and not isinstance(identity, bool):
            return True
        return (
            isinstance(identity, str)
            and bool(identity.strip())
            and len(identity) <= _AUDIO_IMPORT_IDENTITY_MAX_PARENT_LENGTH
            and _is_audio_import_waql_literal(identity)
        )
    return (
        isinstance(identity, str)
        and identity.startswith("\\")
        and len(identity) <= _AUDIO_IMPORT_IDENTITY_MAX_PARENT_LENGTH
        and _is_audio_import_waql_literal(identity)
    )


def _is_audio_import_waql_literal(value: str) -> bool:
    return (
        bool(value)
        and '"' not in value
        and not any(
            ord(character) < 32
            or ord(character) == 127
            or character in {"\u2028", "\u2029"}
            for character in value
        )
    )


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
) -> tuple[tuple[str, ...], int] | None:
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
    configured_limit = (
        step.arguments[-1]
        if len(step.arguments) >= 2 and step.arguments[-2] == "--limit"
        else None
    )
    if not (
        isinstance(configured_limit, str)
        and configured_limit in {str(value) for value in range(1, 9)}
        or isinstance(configured_limit, BoundedIntegerArgument)
        and 1 <= configured_limit.minimum <= configured_limit.maximum <= 8
    ):
        raise GatewayInvocationError(
            "metadata discover allow-list must use one literal or bounded "
            "canonical --limit from 1 through 8"
        )
    configured_shape: list[Any] = [
        "discover",
        "--object-type",
        object_type,
    ]
    for query_spec in query_specs:
        configured_shape.extend(("--query", query_spec))
    configured_shape.extend(("--limit", configured_limit))
    if list(step.arguments) != configured_shape:
        raise GatewayInvocationError(
            "metadata discover allow-list must contain only its exact "
            "object-type, 1..8 query slots, and configured --limit"
        )

    if (
        len(supplied_arguments) < 7
        or len(supplied_arguments) > 21
        or (len(supplied_arguments) - 1) % 2
        or supplied_arguments[0] != "discover"
    ):
        raise GatewayInvocationError(
            "metadata discover scope must be exactly the configured "
            "object-type, 1..8 bounded --query pairs, and configured --limit"
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
    supplied_limit = supplied_limits[0] if len(supplied_limits) == 1 else ""
    if supplied_limit not in {str(value) for value in range(1, 9)}:
        raise GatewayInvocationError(
            "metadata discover --limit must be one canonical decimal integer"
        )
    supplied_limit_value = int(supplied_limit)
    limit_matches = (
        supplied_limit == configured_limit
        if isinstance(configured_limit, str)
        else configured_limit.minimum
        <= supplied_limit_value
        <= configured_limit.maximum
    )
    if (
        supplied_object_types != [object_type]
        or not limit_matches
        or not 1 <= len(queries) <= 8
    ):
        raise GatewayInvocationError(
            "metadata discover scope must be exactly one configured "
            "--object-type, 1..8 --query values, and one matching --limit"
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
    return query_values, supplied_limit_value


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


def _broker_platform_name() -> str:
    """Return the standard-library host discriminator used by shim policy."""

    return os.name


def _windows_process_parent_map() -> dict[int, int]:
    """Snapshot native Windows process ancestry with the standard library."""

    if os.name != "nt":
        raise GatewayBrokerError(
            "Windows process ancestry is unavailable on this host"
        )

    # ``ctypes`` stays local to the Windows-only branch so importing the
    # semantic harness remains portable on POSIX hosts.
    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_snapshot = kernel32.CreateToolhelp32Snapshot
    process_first = kernel32.Process32FirstW
    process_next = kernel32.Process32NextW
    close_handle = kernel32.CloseHandle
    create_snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    create_snapshot.restype = wintypes.HANDLE
    process_first.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    process_first.restype = wintypes.BOOL
    process_next.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    process_next.restype = wintypes.BOOL
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    snapshot = create_snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        raise OSError(error, "CreateToolhelp32Snapshot failed")
    entry = ProcessEntry32W()
    entry.dwSize = ctypes.sizeof(entry)
    parents: dict[int, int] = {}
    try:
        if not process_first(snapshot, ctypes.byref(entry)):
            error = ctypes.get_last_error()
            raise OSError(error, "Process32FirstW failed")
        while True:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            entry.dwSize = ctypes.sizeof(entry)
            if process_next(snapshot, ctypes.byref(entry)):
                continue
            error = ctypes.get_last_error()
            if error == 18:  # ERROR_NO_MORE_FILES
                break
            raise OSError(error, "Process32NextW failed")
    finally:
        close_handle(snapshot)
    return parents


def _process_is_self_or_descendant(
    process_id: int,
    ancestor_process_id: int,
    parent_process_ids: Mapping[int, int],
) -> bool:
    """Return whether one PID reaches the ancestor through a finite parent chain."""

    if process_id <= 0 or ancestor_process_id <= 0:
        return False
    current = process_id
    visited: set[int] = set()
    while current not in visited:
        if current == ancestor_process_id:
            return True
        visited.add(current)
        parent = parent_process_ids.get(current)
        if parent is None or parent <= 0 or parent == current:
            return False
        current = parent
    return False


def _subscription_ack_process_binding_is_valid(
    *,
    platform_name: str,
    launched_process_id: int,
    reported_parent_process_id: int,
    gateway_process_id: int,
) -> bool:
    """Validate the packaged ACK writer against the native launch chain.

    POSIX virtual environments execute the selected interpreter in the launched
    process, so the gateway's reported parent must remain the exact ``Popen``
    PID.  Windows virtual-environment ``python.exe`` files are redirectors that
    create and wait for another interpreter process.  There the reported
    gateway parent must instead be the launcher itself or one of its live
    descendants.  The live gateway writer's native immediate parent must also
    match the ACK.
    """

    if (
        launched_process_id <= 0
        or reported_parent_process_id <= 0
        or gateway_process_id <= 0
        or gateway_process_id == launched_process_id
        or gateway_process_id == reported_parent_process_id
    ):
        return False
    if platform_name == "posix":
        return reported_parent_process_id == launched_process_id
    if platform_name != "nt":
        return False

    parent_process_ids = _windows_process_parent_map()
    if not _process_is_self_or_descendant(
        reported_parent_process_id,
        launched_process_id,
        parent_process_ids,
    ):
        return False
    return parent_process_ids.get(gateway_process_id) == reported_parent_process_id


def _remove_environment_names(
    environment: dict[str, str],
    names: Sequence[str],
    *,
    platform_name: str,
) -> None:
    """Remove exact POSIX names or case-insensitive Windows names in place."""

    if platform_name == "nt":
        folded = {name.casefold() for name in names}
        for key in tuple(environment):
            if key.casefold() in folded:
                environment.pop(key, None)
        return
    for name in names:
        environment.pop(name, None)


def _environment_value(
    environment: Mapping[str, str],
    name: str,
    *,
    platform_name: str,
) -> str | None:
    """Read one environment field with native Windows key semantics."""

    if platform_name != "nt":
        return environment.get(name)
    matches = [
        str(value)
        for key, value in environment.items()
        if str(key).casefold() == name.casefold()
    ]
    if len(matches) > 1:
        raise GatewayBrokerError(
            f"Windows model environment contains duplicate {name} spellings"
        )
    return matches[0] if matches else None


def _normalize_windows_pathext(value: str | None) -> str:
    """Return one closed PATHEXT with the broker's script shim preferred."""

    raw = (
        _WINDOWS_PATH_SEPARATOR.join(_WINDOWS_DEFAULT_PATHEXT)
        if value is None
        else str(value)
    )
    parts = raw.split(_WINDOWS_PATH_SEPARATOR)
    if not parts or any(
        not part or part != part.strip() or _WINDOWS_PATHEXT_RE.fullmatch(part) is None
        for part in parts
    ):
        raise GatewayBrokerError(
            "Windows PATHEXT must be a non-empty semicolon-delimited list of safe extensions"
        )
    normalized: list[str] = [".PS1"]
    seen = {".ps1"}
    for part in parts:
        folded = part.casefold()
        if folded in seen:
            continue
        normalized.append(part.upper())
        seen.add(folded)
    return _WINDOWS_PATH_SEPARATOR.join(normalized)


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
    invocation_skill_source: Path | None = None,
    shim_directory: Path | None = None,
) -> ResolvedGatewayInvocation:
    """Resolve and strictly validate one model-side gateway command argv.

    The canonical accepted shape is::

        python ABS_SKILL/scripts/run.py gateway.py ...

    The production runner's one closed compatibility spelling is accepted too::

        python ABS_SKILL/scripts/run.py --version VERSION gateway.py ...

    ``python3`` is also accepted.  When ``shim_directory`` is supplied, an
    absolute interpreter path must point to its ``python`` or ``python3`` shim.
    The skill runner is compared lexically to the configured absolute locator.
    A distinct ``invocation_skill_source`` allows a detached task-workspace
    copy to be model-visible while the broker still executes the immutable
    candidate under ``skill_source``.  The candidate locator remains accepted
    because a packaged transaction response can legitimately return its exact
    runner path for the next command.  Every other spelling is rejected.
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

    candidate_runner = _absolute_lexical(skill_source) / "scripts" / "run.py"
    invocation_runner = (
        _absolute_lexical(invocation_skill_source) / "scripts" / "run.py"
        if invocation_skill_source is not None
        else candidate_runner
    )
    allowed_runners = tuple(dict.fromkeys((invocation_runner, candidate_runner)))
    supplied_runner = Path(values[1])
    if not supplied_runner.is_absolute() or supplied_runner not in allowed_runners:
        expected = " or ".join(str(path) for path in allowed_runners)
        raise GatewayInvocationError(f"runner path must be exactly {expected}")
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

    normalized = (interpreter_name, str(supplied_runner), "gateway.py", *gateway_arguments)
    return ResolvedGatewayInvocation(
        interpreter=interpreter_name,
        raw_model_argv=values,
        runner_path=str(supplied_runner),
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
    invocation_skill_source: Path | None = None,
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
                    invocation_skill_source=invocation_skill_source,
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
    invocation_skill_source: Path | None = None,
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
                    invocation_skill_source=invocation_skill_source,
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
    if not gateway_step_sequence_matches(
        expected_prefix,
        evidence.consumed_step_names,
        evidence.commutative_read_only_step_groups,
        evidence.commutative_composer_setup_step_groups,
    ):
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
    if tuple(record.step_name for record in accepted) != evidence.consumed_step_names:
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


def _set_json_pointer(payload: Any, pointer: str, value: Any) -> None:
    if not pointer.startswith("/") or pointer == "/":
        raise GatewayInvocationError(
            f"response binding pointer must select one field: {pointer!r}"
        )
    parts = pointer[1:].split("/")
    parent_pointer = "" if len(parts) == 1 else "/" + "/".join(parts[:-1])
    parent = _json_pointer(payload, parent_pointer)
    part = parts[-1].replace("~1", "/").replace("~0", "~")
    if isinstance(parent, Mapping):
        if part not in parent or not isinstance(parent, dict):
            raise GatewayInvocationError(
                f"response binding field is absent or immutable: {pointer!r}"
            )
        parent[part] = value
        return
    if isinstance(parent, list):
        try:
            index = int(part)
            parent[index] = value
        except (ValueError, IndexError) as exc:
            raise GatewayInvocationError(
                f"response binding index is invalid: {pointer!r}"
            ) from exc
        return
    raise GatewayInvocationError(f"response binding cannot update: {pointer!r}")


def _sealed_query_identity_object_operation_equal(
    actual: Any,
    expected: SealedQueryIdentityBoundJsonArgument,
    *,
    source_payload: Mapping[str, Any],
    source_step: ExpectedGatewayStep,
) -> tuple[bool, Mapping[str, str]]:
    """Compare one request after sealing two aliases to one prior query row."""

    identity = _exact_query_bus_identity(
        source_payload=source_payload,
        source_step=source_step,
        expected_step_name=expected.source_step,
    )
    object_id = identity["id"]
    object_path = identity["path"]

    try:
        normalized = json.loads(_canonical_json_bytes(actual))
    except (json.JSONDecodeError, GatewayInvocationError):
        return False, identity
    path_identity = {"kind": "path", "value": object_path}
    id_identity = {"kind": "id", "value": object_id}
    allowed = {
        _canonical_json_bytes(path_identity),
        _canonical_json_bytes(id_identity),
    }
    for pointer in expected.target_pointers:
        try:
            expected_target = _json_pointer(expected.expected, pointer)
            actual_target = _json_pointer(actual, pointer)
            normalized_target = _json_pointer(normalized, pointer)
        except GatewayInvocationError:
            return False, identity
        if (
            _canonical_json_bytes(expected_target)
            != _canonical_json_bytes(path_identity)
            or _canonical_json_bytes(actual_target) not in allowed
            or not isinstance(normalized_target, dict)
        ):
            return False, identity
        normalized_target.clear()
        normalized_target.update(path_identity)
    return (
        _object_operation_json_equal(normalized, expected.expected),
        identity,
    )


def _exact_query_bus_identity(
    *,
    source_payload: Mapping[str, Any],
    source_step: ExpectedGatewayStep,
    expected_step_name: str,
) -> Mapping[str, str]:
    """Return one exact-ID Bus query row after validating command and payload."""

    if (
        source_step.name != expected_step_name
        or source_step.subcommand != "query-object"
        or len(source_step.arguments) != 10
        or source_step.arguments[0] != "--object-id"
        or not isinstance(source_step.arguments[1], str)
        or not source_step.arguments[1]
        or tuple(source_step.arguments[2:])
        != (
            "--return-field",
            "id",
            "--return-field",
            "name",
            "--return-field",
            "type",
            "--return-field",
            "path",
        )
    ):
        raise GatewayInvocationError(
            "sealed query identity source is not one exact-ID identity read"
        )
    objects = source_payload.get("objects")
    if (
        source_payload.get("ok") is not True
        or source_payload.get("command") != "query-object"
        or source_payload.get("count") != 1
        or not isinstance(objects, list)
        or len(objects) != 1
        or not isinstance(objects[0], Mapping)
    ):
        raise GatewayInvocationError(
            "sealed query identity source lacks one successful object row"
        )
    row = objects[0]
    object_id = row.get("id")
    object_path = row.get("path")
    if (
        not isinstance(object_id, str)
        or _GUID_RE.fullmatch(object_id) is None
        or object_id.casefold() != source_step.arguments[1].casefold()
        or not isinstance(object_path, str)
        or not object_path.startswith("\\")
        or not isinstance(row.get("name"), str)
        or not row.get("name")
        or row.get("type") != "Bus"
    ):
        raise GatewayInvocationError(
            "sealed query identity source row is not the exact requested Bus"
        )

    return MappingProxyType({"id": object_id, "path": object_path})


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


def _extract_payload_span(
    stdout: str,
    *,
    required_contract: str | None = None,
) -> tuple[Mapping[str, Any], int, int]:
    stripped = stdout.strip()
    if not stripped:
        raise GatewayInvocationError("packaged runner emitted no JSON payload")
    leading_bytes = len(stdout) - len(stdout.lstrip())
    def reject_constant(constant: str) -> Any:
        raise ValueError(f"non-finite JSON constant {constant!r}")

    decoder = json.JSONDecoder(parse_constant=reject_constant)
    candidates: list[tuple[int, int, Mapping[str, Any], int, int]] = []
    for position, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(stripped, position)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, Mapping):
            candidates.append(
                (
                    end - position,
                    -position,
                    value,
                    leading_bytes + position,
                    leading_bytes + end,
                )
            )
    if not candidates:
        raise GatewayInvocationError("packaged runner output contains no JSON object")
    if required_contract is not None:
        contract_candidates = [
            candidate
            for candidate in candidates
            if candidate[2].get("contract") == required_contract
        ]
        if contract_candidates:
            candidates = contract_candidates
    # Pretty-printed gateway results contain nested JSON objects.  Choosing the
    # last decodable object would therefore select an inner field.  The outer
    # gateway envelope is the widest decodable object in the output.
    _, _, payload, start, end = max(
        candidates,
        key=lambda candidate: (candidate[0], candidate[1]),
    )
    return dict(payload), start, end


def _extract_payload(stdout: str, *, required_contract: str | None = None) -> Mapping[str, Any]:
    payload, _, _ = _extract_payload_span(
        stdout,
        required_contract=required_contract,
    )
    return payload


def _project_next_command_runner(
    value: Mapping[str, Any],
    *,
    candidate_runner: Path,
    invocation_runner: Path,
    platform_name: str,
) -> dict[str, Any]:
    """Project one trusted continuation onto the model-facing Skill locator."""

    optional_keys = {
        "requires_explicit_user_confirmation",
        "requires_later_user_message",
    }
    common_keys = {
        "contract",
        "command",
        "gateway_argv",
        "full_argv",
        "copy_exactly",
        "shell_family",
        "copy_instruction",
    }
    representation_keys = {
        "shell_command",
        "model_shell_family",
        "model_command",
    }
    if not set(value).issubset(common_keys | optional_keys | representation_keys):
        raise GatewayInvocationError(
            "Gateway continuation contains an unexpected field"
        )
    gateway_argv = value.get("gateway_argv")
    full_argv = value.get("full_argv")
    instruction = value.get("copy_instruction")
    expected_candidate = str(candidate_runner.resolve(strict=True))
    if (
        value.get("contract") != TRANSACTION_NEXT_COMMAND_CONTRACT
        or value.get("copy_exactly") is not True
        or not isinstance(value.get("command"), str)
        or not value.get("command")
        or not isinstance(gateway_argv, list)
        or not gateway_argv
        or any(not isinstance(item, str) for item in gateway_argv)
        or gateway_argv[0] != value.get("command")
        or not isinstance(full_argv, list)
        or full_argv
        != ["python", expected_candidate, "gateway.py", *gateway_argv]
        or any(value.get(key) is not True for key in optional_keys & set(value))
        or not isinstance(instruction, Mapping)
        or set(instruction)
        != {"contract", "source_field", "action", "forbidden_transformations"}
        or instruction.get("contract") != TRANSACTION_COPY_INSTRUCTION_CONTRACT
        or instruction.get("action") != TRANSACTION_COPY_ACTION
        or instruction.get("forbidden_transformations")
        != list(TRANSACTION_FORBIDDEN_TRANSFORMATIONS)
    ):
        raise GatewayInvocationError(
            "Gateway continuation is not bound to the sealed candidate runner"
        )

    expected_keys = common_keys | (optional_keys & set(value))
    if platform_name == "nt":
        expected_shell_family = WINDOWS_POWERSHELL_ENCODED_FAMILY
        expected_shell_command = encode_windows_powershell_argv(full_argv)
        try:
            expected_model_command = encode_windows_model_argv(full_argv)
        except PlatformCommandError:
            expected_model_command = None
        if expected_model_command is not None:
            expected_keys |= {
                "shell_command",
                "model_shell_family",
                "model_command",
            }
            representation_is_exact = (
                value.get("model_shell_family") == WINDOWS_MODEL_COMMAND_FAMILY
                and value.get("model_command") == expected_model_command
                and instruction.get("source_field") == "model_command"
            )
        else:
            expected_keys.add("shell_command")
            representation_is_exact = (
                "model_shell_family" not in value
                and "model_command" not in value
                and instruction.get("source_field") == "shell_command"
            )
    elif platform_name == "posix":
        expected_shell_family = "posix-sh"
        expected_shell_command = shlex.join(full_argv)
        expected_keys.add("shell_command")
        representation_is_exact = (
            "model_shell_family" not in value
            and "model_command" not in value
            and instruction.get("source_field") == "shell_command"
        )
    else:
        raise GatewayInvocationError(
            f"unsupported Gateway continuation platform {platform_name!r}"
        )
    if (
        set(value) != expected_keys
        or value.get("shell_family") != expected_shell_family
        or value.get("shell_command") != expected_shell_command
        or not representation_is_exact
    ):
        raise GatewayInvocationError(
            "Gateway continuation command representation is not exact"
        )

    projected_argv = [
        "python",
        str(invocation_runner),
        "gateway.py",
        *gateway_argv,
    ]
    result: dict[str, Any] = {
        "contract": TRANSACTION_NEXT_COMMAND_CONTRACT,
        "command": value["command"],
        "gateway_argv": list(gateway_argv),
        "full_argv": projected_argv,
        "copy_exactly": True,
    }
    for key in ("requires_explicit_user_confirmation", "requires_later_user_message"):
        if key in value:
            result[key] = True

    model_command: str | None = None
    if platform_name == "nt":
        result["shell_family"] = WINDOWS_POWERSHELL_ENCODED_FAMILY
        shell_command = encode_windows_powershell_argv(projected_argv)
        try:
            model_command = encode_windows_model_argv(projected_argv)
        except PlatformCommandError:
            model_command = None
    elif platform_name == "posix":
        result["shell_family"] = "posix-sh"
        shell_command = shlex.join(projected_argv)
    if model_command is not None:
        result["shell_command"] = shell_command
        result["model_shell_family"] = WINDOWS_MODEL_COMMAND_FAMILY
    source_field = "model_command" if model_command is not None else "shell_command"
    result["copy_instruction"] = {
        "contract": TRANSACTION_COPY_INSTRUCTION_CONTRACT,
        "source_field": source_field,
        "action": TRANSACTION_COPY_ACTION,
        "forbidden_transformations": list(TRANSACTION_FORBIDDEN_TRANSFORMATIONS),
    }
    result[source_field] = model_command if model_command is not None else shell_command
    return result


def _project_model_visible_runner(
    value: Any,
    *,
    candidate_runner: Path,
    invocation_runner: Path,
    platform_name: str,
) -> Any:
    """Rewrite only closed continuations; preserve every other payload value."""

    if isinstance(value, Mapping):
        if value.get("contract") == TRANSACTION_NEXT_COMMAND_CONTRACT:
            return _project_next_command_runner(
                value,
                candidate_runner=candidate_runner,
                invocation_runner=invocation_runner,
                platform_name=platform_name,
            )
        return {
            key: _project_model_visible_runner(
                nested,
                candidate_runner=candidate_runner,
                invocation_runner=invocation_runner,
                platform_name=platform_name,
            )
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [
            _project_model_visible_runner(
                nested,
                candidate_runner=candidate_runner,
                invocation_runner=invocation_runner,
                platform_name=platform_name,
            )
            for nested in value
        ]
    return value


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


_SHIM_SOURCE = r'''{shim_header}
from __future__ import annotations
import json
import os
import socket
import sys
import time

OUTPUT_ARM_SECONDS = {output_arm!r}
OUTPUT_DRAIN_SECONDS = {output_drain!r}
WINDOWS_WRAPPER = {windows_wrapper!r}

def write_all(descriptor, value):
    encoded = str(value).encode("utf-8")
    remaining = memoryview(encoded)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise RuntimeError("Codex gateway broker shim could not publish output")
        remaining = remaining[written:]
    return bool(encoded)

if WINDOWS_WRAPPER:
    if len(sys.argv) < 2 or sys.argv[1] not in {{"python", "python3"}}:
        raise SystemExit(125)
    shim_interpreter = sys.argv[1]
    shim_argv = sys.argv[2:]
else:
    shim_interpreter = sys.argv[0]
    shim_argv = sys.argv[1:]

transport = os.environ.get({transport_env!r}, "")
endpoint = os.environ.get({endpoint_env!r}, "")
token = os.environ.get({token_env!r}, "")
request = json.dumps(
    {{"token": token, "interpreter": shim_interpreter, "argv": shim_argv}},
    separators=(",", ":"),
) + "\n"
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


def _windows_command_shim_source(interpreter_name: str) -> bytes:
    """Build one BOM-free PowerShell relay with a fixed invocation shape."""

    if interpreter_name not in _PYTHON_NAMES:
        raise GatewayBrokerError(
            f"unsupported Windows shim interpreter name: {interpreter_name!r}"
        )
    lines = (
        "$ErrorActionPreference = 'Stop'",
        "$PSNativeCommandArgumentPassing = 'Standard'",
        "$PSNativeCommandUseErrorActionPreference = $false",
        (
            "$trustedPython = [Environment]::GetEnvironmentVariable("
            f"'{SHIM_TRUSTED_PYTHON_ENV}', 'Process')"
        ),
        (
            "if ([String]::IsNullOrWhiteSpace($trustedPython)) { "
            "[System.Environment]::Exit(125) }"
        ),
        (
            "$brokerShim = [System.IO.Path]::Combine("
            f"$PSScriptRoot, '{WINDOWS_SHIM_SCRIPT_NAME}')"
        ),
        "try {",
        f"    & $trustedPython $brokerShim '{interpreter_name}' @args",
        "    if ($null -eq $LASTEXITCODE) { [System.Environment]::Exit(125) }",
        "    [System.Environment]::Exit([int]$LASTEXITCODE)",
        "} catch {",
        "    [Console]::Error.WriteLine('Codex gateway broker relay failed.')",
        "    [System.Environment]::Exit(125)",
        "}",
        "",
    )
    return "\n".join(lines).encode("utf-8")


class CodexGatewayBroker:
    """One-run local broker for an ordered semantic gateway scenario."""

    def __init__(
        self,
        *,
        skill_source: Path,
        invocation_skill_source: Path | None = None,
        expected_steps: Sequence[ExpectedGatewayStep],
        commutative_read_only_step_groups: Sequence[Sequence[str]] = (),
        commutative_composer_setup_step_groups: Sequence[Sequence[str]] = (),
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
        self.invocation_skill_source = _absolute_lexical(
            invocation_skill_source or self.skill_source
        )
        self.invocation_runner_path = (
            self.invocation_skill_source / "scripts" / "run.py"
        )
        self.platform_name = _broker_platform_name()
        self.expected_steps = tuple(expected_steps)
        self.commutative_read_only_step_groups = (
            validate_commutative_read_only_step_groups(
                self.expected_steps,
                commutative_read_only_step_groups,
            )
        )
        self.commutative_composer_setup_step_groups = (
            validate_commutative_composer_setup_step_groups(
                self.expected_steps,
                commutative_composer_setup_step_groups,
            )
        )
        self._execution_steps = list(self.expected_steps)
        self._commutative_step_pairs = {
            frozenset(group)
            for group in self.commutative_read_only_step_groups
        } | _commutative_composer_setup_pairs(
            self.commutative_composer_setup_step_groups
        )
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
        validate_operation_draft_protocol_steps(self.expected_steps)
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
        self._submitted_draft_actions_by_step: dict[str, Mapping[str, Any]] = {}
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
            if self.platform_name not in {"posix", "nt"}:
                raise GatewayBrokerError(
                    "gateway broker shims support only native POSIX or Windows hosts; "
                    f"got os.name={self.platform_name!r}"
                )
            if not self.runner_path.is_file():
                raise GatewayBrokerError(f"packaged runner does not exist: {self.runner_path}")
            if not self.invocation_runner_path.is_file():
                raise GatewayBrokerError(
                    "model-visible packaged runner does not exist: "
                    f"{self.invocation_runner_path}"
                )
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
        existing_path = _environment_value(
            environment,
            "PATH",
            platform_name=self.platform_name,
        )
        existing_pathext = _environment_value(
            environment,
            _WINDOWS_PATHEXT_NAME,
            platform_name=self.platform_name,
        )
        replaced_names = {
            *_SUBSCRIPTION_ACK_ENV_NAMES,
            BROKER_TRANSPORT_ENV,
            BROKER_ENDPOINT_ENV,
            BROKER_TOKEN_ENV,
            GATEWAY_REQUIRED_ENV,
            SHIM_TRUSTED_PYTHON_ENV,
            "PATH",
        }
        if self.platform_name == "nt":
            replaced_names.update({BASH_ENV_NAME, _WINDOWS_PATHEXT_NAME})
        _remove_environment_names(
            environment,
            tuple(replaced_names),
            platform_name=self.platform_name,
        )
        environment.update(
            self.model_environment_overrides(
                existing_path,
                existing_pathext=existing_pathext,
            )
        )
        return environment

    def model_environment_overrides(
        self,
        existing_path: str | None = None,
        *,
        existing_pathext: str | None = None,
    ) -> dict[str, str]:
        """Return the small overlay suitable for ``CodexCliHarness.extra_env``.

        Unlike :meth:`model_environment`, this does not copy ``HOME``,
        ``CODEX_HOME``, or any other caller state into the result.
        """

        if not self._started:
            raise GatewayBrokerError("broker has not started")
        old_path = existing_path if existing_path is not None else os.environ.get("PATH", os.defpath)
        common = {
            BROKER_TRANSPORT_ENV: self.transport,
            BROKER_ENDPOINT_ENV: self.endpoint,
            BROKER_TOKEN_ENV: self._token,
            GATEWAY_REQUIRED_ENV: "1",
        }
        if self.platform_name == "posix":
            return {
                "PATH": os.pathsep.join((str(self.shim_directory), old_path)),
                BASH_ENV_NAME: str(self.bash_env_path),
                **common,
            }
        if self.platform_name == "nt":
            pathext = (
                existing_pathext
                if existing_pathext is not None
                else _environment_value(
                    os.environ,
                    _WINDOWS_PATHEXT_NAME,
                    platform_name="nt",
                )
            )
            return {
                "PATH": _WINDOWS_PATH_SEPARATOR.join(
                    (str(self.shim_directory), old_path)
                ),
                _WINDOWS_PATHEXT_NAME: _normalize_windows_pathext(pathext),
                SHIM_TRUSTED_PYTHON_ENV: str(self.trusted_python),
                **common,
            }
        raise GatewayBrokerError(
            f"gateway broker has no model environment for os.name={self.platform_name!r}"
        )

    def evidence(self) -> GatewayBrokerEvidence:
        with self._lock:
            records = tuple(self._records)
            consumed = tuple(
                step.name for step in self._execution_steps[: self._next_step]
            )
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
            commutative_read_only_step_groups=(
                self.commutative_read_only_step_groups
            ),
            commutative_composer_setup_step_groups=(
                self.commutative_composer_setup_step_groups
            ),
        )

    def reconcile(self, command_argvs: Sequence[Sequence[str]]) -> GatewayBrokerReconciliation:
        return reconcile_gateway_commands(
            command_argvs,
            self.evidence(),
            skill_source=self.skill_source,
            invocation_skill_source=self.invocation_skill_source,
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
            invocation_skill_source=self.invocation_skill_source,
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
            shim_header=(
                f"#!{self.trusted_python}"
                if self.platform_name == "posix"
                else ""
            ),
            windows_wrapper=self.platform_name == "nt",
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
        if self.platform_name == "posix":
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
            return
        if self.platform_name == "nt":
            source_path = self.shim_directory / WINDOWS_SHIM_SCRIPT_NAME
            source_path.write_text(source, encoding="utf-8")
            for name in sorted(_PYTHON_NAMES):
                path = self.shim_directory / f"{name}.ps1"
                path.write_bytes(_windows_command_shim_source(name))
            self._bash_env_path = None
            return
        raise GatewayBrokerError(
            f"gateway broker cannot write shims for os.name={self.platform_name!r}"
        )

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
            "encoding": "utf-8",
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
        platform_name: str,
    ) -> Mapping[str, Any]:
        """Wait for and independently validate a live packaged-child ACK."""

        expectation = credential.expectation
        path = expectation.path
        deadline = time.monotonic() + _SUBSCRIPTION_ACK_WAIT_SECONDS
        while True:
            try:
                candidate_metadata = path.lstat()
            except FileNotFoundError:
                candidate_metadata = None
            except OSError as exc:
                raise GatewayInvocationError(
                    f"broker subscription ACK is unavailable: {exc}"
                ) from exc
            if candidate_metadata is not None:
                if path_is_link_or_reparse(path, metadata=candidate_metadata):
                    raise GatewayInvocationError(
                        "broker subscription ACK target became a link or reparse point"
                    )
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

        try:
            parent_metadata = path.parent.lstat()
        except OSError as exc:
            raise GatewayInvocationError(
                f"broker subscription ACK parent cannot be inspected: {exc}"
            ) from exc
        if (
            path_is_link_or_reparse(path.parent, metadata=parent_metadata)
            or not stat.S_ISDIR(parent_metadata.st_mode)
        ):
            raise GatewayInvocationError(
                "broker subscription ACK parent is not one exact real directory"
            )
        try:
            snapshot = read_bounded_exclusive_regular_file(
                path,
                max_bytes=_SUBSCRIPTION_ACK_MAX_BYTES,
            )
            raw = snapshot.raw
        except CodexFileSecurityError as exc:
            raise GatewayInvocationError(
                f"broker subscription ACK is not one private bounded regular file: {exc}"
            ) from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayInvocationError(
                f"broker subscription ACK is not strict UTF-8 JSON: {exc}"
            ) from exc
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
            or type(payload.get("gateway_process_id")) is not int
            or type(payload.get("subscribed_at_unix_ns")) is not int
            or type(payload.get("subscribed_at_monotonic_ns")) is not int
            or payload.get("subscribed_at_monotonic_ns", 0) <= 0
        ):
            raise GatewayInvocationError(
                "broker subscription ACK identity, nonce, or packaged process binding is invalid"
            )
        if not _subscription_ack_process_binding_is_valid(
            platform_name=platform_name,
            launched_process_id=runner_process.pid,
            reported_parent_process_id=int(payload["runner_parent_process_id"]),
            gateway_process_id=int(payload["gateway_process_id"]),
        ):
            raise GatewayInvocationError(
                "broker subscription ACK packaged process binding is invalid"
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
                invocation_skill_source=self.invocation_skill_source,
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
            step = self._execution_steps[self._next_step]
            try:
                semantic_hash, execution_arguments = self._validate_step(
                    step,
                    resolved.gateway_arguments,
                )
            except GatewayInvocationError as first_error:
                try:
                    reordered = self._match_dependency_ready_draft_action(
                        resolved.gateway_arguments,
                    )
                except GatewayInvocationError as reorder_error:
                    return self._reject_locked(
                        resolved,
                        str(reorder_error),
                        authenticated=True,
                    )
                if reordered is not None:
                    step, semantic_hash, execution_arguments = reordered
                elif self._next_step + 1 >= len(self._execution_steps):
                    return self._reject_locked(
                        resolved,
                        str(first_error),
                        authenticated=True,
                    )
                else:
                    alternate = self._execution_steps[self._next_step + 1]
                    if frozenset((step.name, alternate.name)) not in (
                        self._commutative_step_pairs
                    ):
                        return self._reject_locked(
                            resolved,
                            str(first_error),
                            authenticated=True,
                        )
                    try:
                        semantic_hash, execution_arguments = self._validate_step(
                            alternate,
                            resolved.gateway_arguments,
                        )
                    except GatewayInvocationError as second_error:
                        return self._reject_locked(
                            resolved,
                            "command matches neither declared commutative "
                            f"step: {first_error}; {second_error}",
                            authenticated=True,
                        )
                    self._execution_steps[
                        self._next_step : self._next_step + 2
                    ] = (alternate, step)
                    step = alternate
            except Exception as exc:  # noqa: BLE001 - authenticated failures are terminal and recorded
                return self._reject_locked(
                    resolved,
                    f"unexpected allow-list validation failure: {type(exc).__name__}: {exc}",
                    authenticated=True,
                    response_exit=125,
                    payload_error=str(exc),
                )

        submitted_draft_action: Mapping[str, Any] | None = None
        if step.subcommand == "draft-apply":
            action_index = resolved.gateway_arguments.index("--action-json") + 1
            decoded_action = _decode_json_argument(
                resolved.gateway_arguments[action_index],
                reject_duplicate_keys=True,
            )
            if not isinstance(decoded_action, Mapping):
                return self._reject(
                    resolved.raw_model_argv,
                    "validated typed Draft action did not decode to an object",
                    authenticated=True,
                )
            submitted_draft_action = json.loads(
                _canonical_json_bytes(decoded_action).decode("utf-8")
            )

        return self._execute(
            step,
            resolved,
            semantic_hash,
            execution_arguments=execution_arguments,
            submitted_draft_action=submitted_draft_action,
        )

    def _match_dependency_ready_draft_action(
        self,
        actual: Sequence[str],
    ) -> tuple[ExpectedGatewayStep, str, tuple[str, ...]] | None:
        """Select one equivalent typed action without fixing its linearization."""

        current = self._execution_steps[self._next_step]
        current_match = _NUMBERED_DRAFT_ACTION_STEP_RE.fullmatch(current.name)
        if current.subcommand != "draft-apply" or current_match is None:
            return None
        current_argument = next(
            (
                argument
                for argument in current.arguments
                if isinstance(argument, DraftActionJsonArgument)
            ),
            None,
        )
        if (
            isinstance(current_argument, DraftActionJsonArgument)
            and current_argument.operation == "audio.import"
        ):
            # Import row order is part of the canonical operation request and
            # therefore part of its business meaning.  Unlike object.set's
            # handle-independent edits, audio.import actions are not
            # commutative.
            return None
        prefix = current_match.group("prefix")
        matches: list[
            tuple[int, ExpectedGatewayStep, str, tuple[str, ...]]
        ] = []
        for index in range(self._next_step + 1, len(self._execution_steps)):
            candidate = self._execution_steps[index]
            candidate_match = _NUMBERED_DRAFT_ACTION_STEP_RE.fullmatch(
                candidate.name
            )
            if (
                candidate.subcommand != "draft-apply"
                or candidate_match is None
                or candidate_match.group("prefix") != prefix
            ):
                break
            try:
                semantic_hash, execution_arguments = self._validate_step(
                    candidate,
                    actual,
                )
            except GatewayInvocationError:
                continue
            matches.append(
                (index, candidate, semantic_hash, execution_arguments)
            )
        if not matches:
            return None
        if len(matches) != 1:
            raise GatewayInvocationError(
                "typed Draft action matches multiple dependency-ready business facts"
            )
        index, candidate, semantic_hash, execution_arguments = matches[0]
        self._execution_steps.insert(
            self._next_step,
            self._execution_steps.pop(index),
        )
        return candidate, semantic_hash, execution_arguments

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
        metadata_discovery = _validate_metadata_discover_query_arguments(
            step,
            validation_arguments,
        )
        if (
            metadata_discovery is None
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
        if metadata_discovery is not None:
            metadata_queries, metadata_limit = metadata_discovery
            semantic_values.extend(
                (
                    "metadata-discover-query-set/v1",
                    step.arguments[2],
                    list(metadata_queries),
                    metadata_limit,
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
                elif isinstance(
                    expected,
                    SealedQueryIdentityBoundJsonArgument,
                ):
                    actual_json = _decode_json_argument(supplied)
                    source = self._payloads_by_step.get(expected.source_step)
                    if source is None:
                        raise GatewayInvocationError(
                            f"step {step.name!r} sealed identity source "
                            f"{expected.source_step!r} is unavailable"
                        )
                    source_steps = tuple(
                        candidate
                        for candidate in self.expected_steps
                        if candidate.name == expected.source_step
                    )
                    if len(source_steps) != 1:
                        raise GatewayInvocationError(
                            f"step {step.name!r} sealed identity source is not unique"
                        )
                    equal, identity = (
                        _sealed_query_identity_object_operation_equal(
                            actual_json,
                            expected,
                            source_payload=source,
                            source_step=source_steps[0],
                        )
                    )
                    if not equal:
                        raise GatewayInvocationError(
                            f"step {step.name!r} argument {index} JSON is not "
                            "semantically equal to the sealed query-identity "
                            "allow-list"
                        )
                    semantic_values.extend(
                        (
                            _normalize_object_set_request(expected.expected),
                            "sealed-query-identity/v1",
                            expected.source_step,
                            list(expected.target_pointers),
                            dict(identity),
                        )
                    )
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
                elif isinstance(expected, BoundedIntegerArgument):
                    raise GatewayInvocationError(
                        "bounded integer slot escaped its closed metadata "
                        "discover validator"
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
                                "object_set_rtpc_v1",
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
                            [
                                item.as_dict()
                                for item in (
                                    expected.gateway_derived_reference_activations
                                )
                            ],
                        )
                    )
                elif isinstance(expected, DraftActionJsonArgument):
                    actual_json = _decode_json_argument(
                        supplied,
                        reject_duplicate_keys=True,
                    )
                    bound_expected = json.loads(
                        _canonical_json_bytes(dict(expected.expected)).decode("utf-8")
                    )
                    binding_evidence: list[dict[str, Any]] = []
                    for binding in expected.response_bindings:
                        source = self._payloads_by_step.get(binding.step)
                        if source is None:
                            raise GatewayInvocationError(
                                f"step {step.name!r} Draft handle source "
                                f"{binding.step!r} is unavailable"
                            )
                        bound = _json_pointer(source, binding.response_pointer)
                        if (
                            not isinstance(bound, str)
                            or _DRAFT_HANDLE_RE.fullmatch(bound) is None
                        ):
                            raise GatewayInvocationError(
                                f"step {step.name!r} Draft handle binding is invalid"
                            )
                        bound_expected[binding.pointer.removeprefix("/")] = bound
                        binding_evidence.append(
                            {
                                "pointer": binding.pointer,
                                "step": binding.step,
                                "response_pointer": binding.response_pointer,
                                "value": bound,
                            }
                        )
                    normalized_actual = json.loads(
                        _canonical_json_bytes(actual_json).decode("utf-8")
                    )
                    identity_evidence: list[dict[str, Any]] = []
                    for binding in expected.query_identity_bindings:
                        source = self._payloads_by_step.get(binding.step)
                        if source is None:
                            raise GatewayInvocationError(
                                f"step {step.name!r} query identity source "
                                f"{binding.step!r} is unavailable"
                            )
                        source_steps = tuple(
                            candidate
                            for candidate in self.expected_steps
                            if candidate.name == binding.step
                        )
                        if len(source_steps) != 1:
                            raise GatewayInvocationError(
                                f"step {step.name!r} query identity source is not unique"
                            )
                        identity = _exact_query_bus_identity(
                            source_payload=source,
                            source_step=source_steps[0],
                            expected_step_name=binding.step,
                        )
                        expected_target = _json_pointer(
                            bound_expected,
                            binding.pointer,
                        )
                        actual_target = _json_pointer(
                            actual_json,
                            binding.pointer,
                        )
                        normalized_target = _json_pointer(
                            normalized_actual,
                            binding.pointer,
                        )
                        path_identity = {
                            "kind": "path",
                            "value": identity["path"],
                        }
                        id_identity = {
                            "kind": "id",
                            "value": identity["id"],
                        }
                        if (
                            expected_target != path_identity
                            or actual_target not in (path_identity, id_identity)
                            or not isinstance(normalized_target, dict)
                        ):
                            raise GatewayInvocationError(
                                f"step {step.name!r} typed Draft action query-bound "
                                "identity does not match the exact Bus row"
                            )
                        normalized_target.clear()
                        normalized_target.update(path_identity)
                        identity_evidence.append(
                            {
                                "pointer": binding.pointer,
                                "step": binding.step,
                                "id": identity["id"],
                                "path": identity["path"],
                            }
                        )
                    metadata_evidence: dict[str, Any] | None = None
                    metadata_binding = expected.metadata_binding
                    if metadata_binding is not None:
                        source = self._payloads_by_step.get(metadata_binding.step)
                        source_steps = tuple(
                            candidate
                            for candidate in self.expected_steps
                            if candidate.name == metadata_binding.step
                        )
                        if (
                            source is None
                            or len(source_steps) != 1
                            or source_steps[0].subcommand != "metadata"
                            or len(source_steps[0].arguments) < 3
                            or source_steps[0].arguments[:2]
                            != ("discover", "--object-type")
                            or source_steps[0].arguments[2]
                            != metadata_binding.object_type
                        ):
                            raise GatewayInvocationError(
                                f"step {step.name!r} Draft metadata source is unavailable"
                            )
                        actual_projection = project_required_metadata_tokens(
                            source,
                            object_type=metadata_binding.object_type,
                            required_tokens=metadata_binding.required_tokens,
                        )
                        if (
                            metadata_binding.expected_projection is not None
                            and actual_projection
                            != metadata_binding.expected_projection
                        ):
                            raise GatewayInvocationError(
                                f"step {step.name!r} live metadata projection differs "
                                "from the trusted Draft projection"
                            )
                        metadata_evidence = {
                            "step": metadata_binding.step,
                            "object_type": metadata_binding.object_type,
                            "required_tokens": list(
                                metadata_binding.required_tokens
                            ),
                            "projection": [
                                item.as_dict() for item in actual_projection
                            ],
                        }
                    if normalized_actual != bound_expected:
                        raise GatewayInvocationError(
                            f"step {step.name!r} typed Draft action is not exactly equal "
                            "to its business facts and Gateway response bindings"
                        )
                    semantic_values.extend(
                        (
                            dict(expected.expected),
                            "draft-action-json/v1",
                            binding_evidence,
                            identity_evidence,
                        )
                    )
                    if expected.operation != "object.set":
                        semantic_values.extend(
                            (
                                "draft-action-operation/v1",
                                expected.operation,
                                metadata_evidence,
                            )
                        )
                elif isinstance(expected, ResponseBinding):
                    source = self._payloads_by_step.get(expected.step)
                    if (
                        step.subcommand in _DRAFT_SUBCOMMANDS
                        and expected.pointer == "/draft/revision"
                        and index > 0
                        and validation_arguments[index - 1]
                        == "--expected-revision"
                    ):
                        latest_source = next(
                            (
                                self._payloads_by_step.get(prior.name)
                                for prior in reversed(
                                    self._execution_steps[: self._next_step]
                                )
                                if isinstance(
                                    self._payloads_by_step.get(prior.name),
                                    Mapping,
                                )
                                and isinstance(
                                    self._payloads_by_step[prior.name].get("draft"),
                                    Mapping,
                                )
                            ),
                            None,
                        )
                        if latest_source is not None:
                            source = latest_source
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
        submitted_draft_action: Mapping[str, Any] | None,
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
            _remove_environment_names(
                runner_env,
                (*_BROKER_ENV_NAMES, _PYTHON_IO_ENCODING_ENV),
                platform_name=self.platform_name,
            )
            # The parent reads strict UTF-8.  Own the packaged Python runner's
            # stream encoding too, including case-insensitive Windows aliases,
            # so locale/ACP settings cannot corrupt structured gateway output.
            runner_env[_PYTHON_IO_ENCODING_ENV] = "utf-8:strict"
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
                            platform_name=self.platform_name,
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
        payload_start = 0
        payload_end = 0
        if exit_code not in step.allowed_exit_codes:
            failures.append(
                f"packaged gateway runner exit {exit_code!r} is not allowed; "
                f"expected one of {step.allowed_exit_codes!r}"
            )
        try:
            payload, payload_start, payload_end = _extract_payload_span(
                stdout,
                required_contract=self.required_contract,
            )
            if payload.get("contract") != self.required_contract:
                raise GatewayInvocationError(
                    f"gateway payload contract must be {self.required_contract!r}"
                )
            confirmation_is_consumed_later = any(
                isinstance(argument, ResponseBinding)
                and argument.step == step.name
                and argument.pointer == "/confirmation/token"
                for later_step in self._execution_steps[self._next_step + 1 :]
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
                if step.subcommand in _DRAFT_SUBCOMMANDS:
                    self._validate_operation_draft_payload(step, payload)
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

        if not failures and payload is not None:
            try:
                projected_payload = _project_model_visible_runner(
                    payload,
                    candidate_runner=self.runner_path,
                    invocation_runner=self.invocation_runner_path,
                    platform_name=self.platform_name,
                )
                if projected_payload != payload:
                    projected_json = json.dumps(
                        projected_payload,
                        ensure_ascii=False,
                        allow_nan=False,
                        indent=2,
                    )
                    stdout = (
                        stdout[:payload_start]
                        + projected_json
                        + stdout[payload_end:]
                    )
                    payload = projected_payload
            except GatewayInvocationError as exc:
                failures.append(str(exc))
            except Exception as exc:  # noqa: BLE001 - projection is evidence-critical
                failures.append(
                    "unexpected Gateway continuation projection failure: "
                    f"{type(exc).__name__}: {exc}"
                )

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
                if submitted_draft_action is not None:
                    self._submitted_draft_actions_by_step[step.name] = (
                        submitted_draft_action
                    )
                self._next_step += 1
                if terminal_indeterminate:
                    self._terminal_state = _BROKER_INDETERMINATE
                elif self._next_step == len(self.expected_steps):
                    self._terminal_state = _BROKER_COMPLETE
            else:
                self._terminal_state = _BROKER_FAILED

        return {"exit_code": response_exit, "stdout": stdout, "stderr": response_stderr}

    def _validate_operation_draft_payload(
        self,
        step: ExpectedGatewayStep,
        payload: Mapping[str, Any],
    ) -> None:
        """Bind every successful Draft response to the reviewed Draft flow."""

        if "task_authority" in payload and step.subcommand != "draft-start":
            raise GatewayInvocationError(
                "only draft-start may disclose the task authority"
            )
        if step.subcommand == "preview-from-draft":
            if not isinstance(payload.get("transaction_id"), str) or not payload[
                "transaction_id"
            ]:
                raise GatewayInvocationError(
                    "preview-from-draft must return one transaction ID"
                )
            if payload.get("state") not in {
                "awaiting_confirmation",
                "policy_authorized",
            }:
                raise GatewayInvocationError(
                    "preview-from-draft must return one reviewable transaction state"
                )
            agent_result = payload.get("agent_result")
            if not isinstance(agent_result, Mapping):
                raise GatewayInvocationError(
                    "preview-from-draft must return one exact agent_result"
                )
            expected_request = self._replay_expected_operation_draft_request(step)
            actual_request = self._normalize_operation_draft_query_identities(
                agent_result.get("request"),
                preview_step=step,
            )
            if actual_request != expected_request:
                raise GatewayInvocationError(
                    "preview-from-draft canonical request does not replay from "
                    "the reviewed typed actions"
                )
            if list(payload)[-1] != "agent_result":
                raise GatewayInvocationError(
                    "preview-from-draft must keep agent_result final"
                )
            return

        draft = payload.get("draft")
        if not isinstance(draft, Mapping):
            raise GatewayInvocationError(
                f"{step.subcommand} must return one Draft projection"
            )
        draft_id = draft.get("draft_id")
        revision = draft.get("revision")
        lifecycle_state = draft.get("lifecycle_state")
        binding = draft.get("binding")
        if not isinstance(draft_id, str) or _DRAFT_ID_RE.fullmatch(draft_id) is None:
            raise GatewayInvocationError("Draft response contains an invalid draft ID")
        if type(revision) is not int or revision < 1:
            raise GatewayInvocationError("Draft response contains an invalid revision")
        if not isinstance(binding, Mapping):
            raise GatewayInvocationError("Draft response is missing its immutable binding")

        step_index = self._execution_steps.index(step)
        prior_starts = tuple(
            value
            for value in self._execution_steps[: step_index + 1]
            if value.subcommand == "draft-start"
        )
        if not prior_starts:
            raise GatewayInvocationError(
                "Draft response is missing its flow-local draft-start"
            )
        start = prior_starts[-1]
        operation = start.arguments[0]
        version = binding.get("version")
        if binding.get("operation") != operation:
            raise GatewayInvocationError(
                "Draft response operation does not match draft-start"
            )
        if not isinstance(version, str) or version not in _SUPPORTED_WWISE_VERSIONS:
            raise GatewayInvocationError("Draft response contains an invalid Wwise version")
        if self.expected_wwise_version and version != self.expected_wwise_version:
            raise GatewayInvocationError(
                "Draft response version does not match the sealed Wwise version"
            )

        if step.subcommand == "draft-start":
            authority = payload.get("task_authority")
            if (
                not isinstance(authority, str)
                or _DRAFT_AUTHORITY_RE.fullmatch(authority) is None
            ):
                raise GatewayInvocationError(
                    "draft-start must return one valid task authority"
                )
            if revision != 1 or lifecycle_state != "editable":
                raise GatewayInvocationError(
                    "draft-start must return editable revision 1"
                )
            return

        start_payload = self._payloads_by_step.get(start.name)
        if not isinstance(start_payload, Mapping):
            raise GatewayInvocationError("Draft response is missing its prior start binding")
        start_draft = start_payload.get("draft")
        if not isinstance(start_draft, Mapping) or draft_id != start_draft.get("draft_id"):
            raise GatewayInvocationError(
                "Draft response ID does not match draft-start"
            )

        previous_draft: Mapping[str, Any] | None = None
        start_index = self._execution_steps.index(start)
        for prior in reversed(self._execution_steps[start_index:step_index]):
            prior_payload = self._payloads_by_step.get(prior.name)
            if not isinstance(prior_payload, Mapping):
                continue
            candidate = prior_payload.get("draft")
            if isinstance(candidate, Mapping):
                previous_draft = candidate
                break
        if previous_draft is None or type(previous_draft.get("revision")) is not int:
            raise GatewayInvocationError(
                "Draft response is missing its prior revision binding"
            )
        expected_revision = int(previous_draft["revision"])
        if step.subcommand != "draft-inspect":
            expected_revision += 1
        if revision != expected_revision:
            raise GatewayInvocationError(
                "Draft response revision does not follow the reviewed transition"
            )
        expected_state = "cancelled" if step.subcommand == "draft-cancel" else "editable"
        if lifecycle_state != expected_state:
            raise GatewayInvocationError(
                "Draft response lifecycle state does not follow the reviewed transition"
            )

    def _normalize_operation_draft_query_identities(
        self,
        value: Any,
        *,
        preview_step: ExpectedGatewayStep,
    ) -> Any:
        """Normalize only exact pre-Draft Bus GUIDs to their reviewed paths."""

        preview_index = self._execution_steps.index(preview_step)
        identities: dict[str, str] = {}
        for action_step in self._execution_steps[:preview_index]:
            if action_step.subcommand != "draft-apply":
                continue
            argument = action_step.arguments[-1]
            if not isinstance(argument, DraftActionJsonArgument):
                continue
            for binding in argument.query_identity_bindings:
                source = self._payloads_by_step.get(binding.step)
                source_step = next(
                    (
                        candidate
                        for candidate in self.expected_steps
                        if candidate.name == binding.step
                    ),
                    None,
                )
                if not isinstance(source, Mapping) or source_step is None:
                    raise GatewayInvocationError(
                        "Draft query identity normalization lacks its exact source"
                    )
                identity = _exact_query_bus_identity(
                    source_payload=source,
                    source_step=source_step,
                    expected_step_name=binding.step,
                )
                expected_target = _json_pointer(argument.expected, binding.pointer)
                if expected_target != {
                    "kind": "path",
                    "value": identity["path"],
                }:
                    raise GatewayInvocationError(
                        "Draft query identity normalization differs from the reviewed path"
                    )
                identities[identity["id"]] = identity["path"]

        def normalize(item: Any) -> Any:
            if isinstance(item, Mapping):
                if (
                    set(item) == {"kind", "value"}
                    and item.get("kind") == "id"
                    and item.get("value") in identities
                ):
                    return {
                        "kind": "path",
                        "value": identities[str(item["value"])],
                    }
                return {str(key): normalize(nested) for key, nested in item.items()}
            if isinstance(item, list):
                return [normalize(nested) for nested in item]
            return item

        return normalize(value)

    def _replay_expected_operation_draft_request(
        self,
        preview_step: ExpectedGatewayStep,
    ) -> Mapping[str, Any]:
        preview_index = self._execution_steps.index(preview_step)
        prior_starts = tuple(
            step
            for step in self._execution_steps[:preview_index]
            if step.subcommand == "draft-start"
        )
        if not prior_starts:
            raise GatewayInvocationError(
                "Draft canonical replay is missing its flow-local draft-start"
            )
        start = prior_starts[-1]
        start_index = self._execution_steps.index(start)
        operation = str(start.arguments[0])
        start_payload = self._payloads_by_step.get(start.name)
        start_draft = (
            start_payload.get("draft")
            if isinstance(start_payload, Mapping)
            else None
        )
        version = (
            start_draft.get("binding", {}).get("version")
            if isinstance(start_draft, Mapping)
            and isinstance(start_draft.get("binding"), Mapping)
            else None
        )
        if not isinstance(version, str) or version not in _SUPPORTED_WWISE_VERSIONS:
            raise GatewayInvocationError(
                "Draft canonical replay is missing its version binding"
            )
        composition = new_composition(operation, version)
        actual_composition = new_composition(operation, version)
        for action_step in self._execution_steps[start_index + 1 : preview_index]:
            if action_step.subcommand != "draft-apply":
                continue
            argument = action_step.arguments[-1]
            if not isinstance(argument, DraftActionJsonArgument):
                raise GatewayInvocationError(
                    "Draft canonical replay found an untyped action"
                )
            action = json.loads(
                _canonical_json_bytes(dict(argument.expected)).decode("utf-8")
            )
            for binding in argument.response_bindings:
                source = self._payloads_by_step.get(binding.step)
                if source is None:
                    raise GatewayInvocationError(
                        "Draft canonical replay is missing a handle source"
                    )
                bound = _json_pointer(source, binding.response_pointer)
                if not isinstance(bound, str) or _DRAFT_HANDLE_RE.fullmatch(bound) is None:
                    raise GatewayInvocationError(
                        "Draft canonical replay received an invalid handle"
                    )
                action[binding.pointer.removeprefix("/")] = bound

            submitted_action = self._submitted_draft_actions_by_step.get(
                action_step.name
            )
            actual_action = json.loads(
                _canonical_json_bytes(
                    submitted_action if submitted_action is not None else action
                ).decode("utf-8")
            )
            for binding in argument.query_identity_bindings:
                source = self._payloads_by_step.get(binding.step)
                source_step = next(
                    (
                        candidate
                        for candidate in self.expected_steps
                        if candidate.name == binding.step
                    ),
                    None,
                )
                if not isinstance(source, Mapping) or source_step is None:
                    raise GatewayInvocationError(
                        "Draft canonical replay lacks its exact query identity"
                    )
                identity = _exact_query_bus_identity(
                    source_payload=source,
                    source_step=source_step,
                    expected_step_name=binding.step,
                )
                expected_target = _json_pointer(action, binding.pointer)
                if expected_target != {
                    "kind": "path",
                    "value": identity["path"],
                }:
                    raise GatewayInvocationError(
                        "Draft canonical replay query identity differs from the "
                        "reviewed path"
                    )
                if submitted_action is None:
                    _set_json_pointer(
                        actual_action,
                        binding.pointer,
                        {
                            "kind": "id",
                            "value": identity["id"],
                        },
                    )
                elif _json_pointer(actual_action, binding.pointer) not in (
                    expected_target,
                    {"kind": "id", "value": identity["id"]},
                ):
                    raise GatewayInvocationError(
                        "Draft canonical replay submitted query identity differs "
                        "from the exact Bus row"
                    )

            response = self._payloads_by_step.get(action_step.name)
            response_draft = (
                response.get("draft") if isinstance(response, Mapping) else None
            )
            if not isinstance(response_draft, Mapping):
                raise GatewayInvocationError(
                    "Draft canonical replay is missing an action response"
                )
            compact_result: tuple[
                str,
                set[str],
                set[str],
                Mapping[str, Any],
            ] | None = None
            response_facts = response_draft.get("current_facts")
            if isinstance(response_facts, list):
                before_handles = _draft_projection_handles(
                    composition_projection(operation, version, composition)[
                        "current_facts"
                    ]
                )
                after_handles = _draft_projection_handles(response_facts)
                remaining_handles = sorted(after_handles - before_handles)
            else:
                compact_result = _draft_compact_action_result(response_draft)
                remaining_handles = sorted(compact_result[1])

            created_handles = list(remaining_handles)

            def handle_factory() -> str:
                if not remaining_handles:
                    raise OperationComposerError(
                        "Draft action response is missing its generated handle."
                    )
                return remaining_handles.pop(0)

            try:
                composition, action_name = apply_composer_action(
                    operation,
                    version,
                    composition,
                    action,
                    handle_factory=handle_factory,
                )
            except OperationComposerError as exc:
                raise GatewayInvocationError(
                    f"Draft canonical replay rejected one reviewed action: {exc}"
                ) from exc
            actual_handles = list(created_handles)

            def actual_handle_factory() -> str:
                if not actual_handles:
                    raise OperationComposerError(
                        "Draft action response is missing its generated handle."
                    )
                return actual_handles.pop(0)

            try:
                actual_composition, actual_action_name = apply_composer_action(
                    operation,
                    version,
                    actual_composition,
                    actual_action,
                    handle_factory=actual_handle_factory,
                )
            except OperationComposerError as exc:
                raise GatewayInvocationError(
                    f"Draft canonical replay rejected one query-bound action: {exc}"
                ) from exc
            if actual_handles or actual_action_name != action_name:
                raise GatewayInvocationError(
                    "Draft canonical replay produced inconsistent action facts"
                )
            actual_projection = composition_projection(
                operation,
                version,
                actual_composition,
            )
            if compact_result is not None:
                result_action, _created, affected, summary = compact_result
                expected_affected = {
                    value
                    for key, value in action.items()
                    if key.endswith("_handle") and isinstance(value, str)
                }
                projected_facts = actual_projection["current_facts"]
                projected_handles = _draft_projection_handles(projected_facts)
                compact_matches = (
                    not remaining_handles
                    and result_action == action_name
                    and affected == expected_affected
                    and summary["target_count"] == len(projected_facts)
                    and summary["handle_count"] == len(projected_handles)
                    and summary["canonical_sha256"]
                    == _sha256_bytes(_canonical_json_bytes(projected_facts))
                )
            else:
                compact_matches = not remaining_handles and not any(
                    response_draft.get(key) != value
                    for key, value in actual_projection.items()
                )
            if not compact_matches:
                raise GatewayInvocationError(
                    "Draft action response for "
                    f"{action_step.name!r} does not match deterministic composition"
                )
        try:
            return materialize_operation_request(operation, version, composition)
        except OperationComposerError as exc:
            raise GatewayInvocationError(
                f"Draft canonical request cannot be materialized: {exc}"
            ) from exc

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
                self._execution_steps[self._next_step].name
                if self._next_step < len(self._execution_steps)
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
    "SHIM_TRUSTED_PYTHON_ENV",
    "WINDOWS_COMMAND_SHIM_NAMES",
    "WINDOWS_SHIM_SCRIPT_NAME",
    "CodexGatewayBroker",
    "DraftActionJsonArgument",
    "DraftActionMetadataBinding",
    "DraftActionQueryIdentityBinding",
    "DraftActionResponseBinding",
    "ExpectedGatewayStep",
    "GatewayBrokerError",
    "GatewayBrokerEvidence",
    "GatewayBrokerRecord",
    "GatewayBrokerReconciliation",
    "GatewayInvocationError",
    "GatewayDerivedReferenceActivationAllowance",
    "MetadataBoundJsonArgument",
    "MetadataQueryArgument",
    "MetadataTokenProjection",
    "OBJECT_SET_SCHEMA_DEFAULTS",
    "ResolvedGatewayInvocation",
    "ResponseBinding",
    "SealedQueryIdentityBoundJsonArgument",
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
    "validate_operation_draft_protocol_steps",
    "validate_transaction_show_confirmation_payload",
]
