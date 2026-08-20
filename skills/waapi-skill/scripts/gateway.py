#!/usr/bin/env python3
"""Stable JSON gateway from agent commands to the WAAPI Skill runtime."""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import shlex
import stat
import sys
import threading
import time
import uuid
from concurrent.futures import InvalidStateError
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SKILL_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_RUNNER_PATH = SKILL_ROOT / "scripts" / "run.py"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from wwise_waapi.capabilities import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    CapabilityCatalog,
    CapabilityNotFoundError,
    CapabilityRecord,
    FIXED_COMMANDS_BY_URI,
)
from wwise_waapi.authoring_ui_commands_manifest import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    AUTHORING_UI_COMMAND_URIS,
)
from wwise_waapi.canonical import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    canonical_json_bytes,
    canonical_sha256,
)
from wwise_waapi.builders.common import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    SemanticPreview,
    SemanticValidationError,
)
from wwise_waapi.builders.debug_lua import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    DebugLuaContractError,
    MAX_WAL_TREE_NODES,
    normalize_wal_tree_result,
)
from wwise_waapi.builders.metadata import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    MetadataBuilder,
    parse_get_attenuation_curve_result,
    parse_get_property_info_result,
    parse_get_types_result,
    parse_is_property_enabled_result,
    parse_property_and_reference_names_result,
)
from wwise_waapi.metadata_catalog import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    MAX_OBJECT_TYPE_SEARCH_RESULTS,
    MetadataCatalogError,
    MetadataCatalogMissingError,
    ObjectTypeCatalogStore,
)
from wwise_waapi.metadata_cache import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    DurableMetadataCache,
    GET_PROPERTY_AND_REFERENCE_NAMES_URI,
    GET_PROPERTY_INFO_URI as CACHE_GET_PROPERTY_INFO_URI,
    GET_TYPES_URI as CACHE_GET_TYPES_URI,
    MetadataCacheError,
    MetadataCacheLookup,
    MetadataSessionIdentity,
    SessionMetadataCache,
)
from wwise_waapi.metadata_discovery import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    DEFAULT_METADATA_DISCOVERY_LIMIT,
    MAX_METADATA_DISCOVERY_LIMIT,
    MAX_METADATA_DISCOVERY_NAME_CHARS,
    MAX_METADATA_DISCOVERY_QUERIES,
    MAX_METADATA_DISCOVERY_QUERY_CHARS,
    MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS,
    discover_metadata,
)
from wwise_waapi.host_paths import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    HostPathError,
    host_path_comparison_key,
    localize_waapi_host_path,
)
from wwise_waapi.platform_commands import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    GATEWAY_SHELL_TOOL_TIMEOUT_MS,
    PlatformCommandError,
    WINDOWS_MODEL_COMMAND_FAMILY,
    WINDOWS_POWERSHELL_ENCODED_FAMILY,
    encode_windows_model_argv,
    encode_windows_powershell_argv,
)
from wwise_waapi.builders.query import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    ADVANCED_QUERY_CONTRACT,
    MAX_QUERY_TAKE,
    STRUCTURED_QUERY_CONTRACT,
    SUPPORTED_SELECTS,
    advanced_query_schema,
    build_advanced_object_get_query,
    build_object_get_query,
    build_structured_object_get_query,
    structured_query_schema,
)
from wwise_waapi.builders.stable_reads import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    MAX_BUS_PIPELINE_IDS,
    STABLE_READ_RESULT_LIMIT_BYTES,
    build_profiler_game_objects_request,
    build_profiler_voice_contributions_request,
    build_project_default_work_units_request,
    normalize_profiler_game_objects_result,
    normalize_profiler_voice_contributions_result,
    normalize_project_default_work_units_result,
)
from wwise_waapi.typed_requests import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    TYPED_REQUEST_COMPLEX_TRACER_URI,
    TYPED_REQUEST_TRACER_URI,
    TypedRequestContract,
    TypedRequestError,
    TypedRequestFact,
    dynamic_array_item_choices,
    dynamic_array_item_handle,
    dynamic_container_disclosure,
    dynamic_map_container_choices,
    dynamic_map_entry_handle,
    materialize_typed_request,
    parse_typed_schema_lineage_token,
    request_contract,
    typed_schema_lineage_business_pointer,
    typed_schema_lineage_root_business_pointer,
    typed_schema_lineage_token,
)
from wwise_waapi.typed_queries import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    ADVANCED_TYPED_QUERY_OPERATION,
    STRUCTURED_TYPED_QUERY_OPERATION,
    materialize_typed_query,
    typed_query_contract,
    typed_query_schema_payload,
)
from wwise_waapi.typed_topics import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    TOPIC_MATCH_OPERATION_PREFIX,
    TOPIC_OPTIONS_OPERATION_PREFIX,
    materialize_typed_topic_inputs,
    topic_match_contract,
    topic_options_contract,
)
from wwise_waapi.builders.schema import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    validate_semantic_event,
    validate_semantic_payload,
    validate_semantic_result,
)
from wwise_waapi.authorization import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,
    AUTHORIZATION_MODE_POLICY,
    EXPLICIT_CONFIRMATION_ONLY_OPERATIONS,
)
from wwise_waapi.config import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    PROJECT_MODIFICATION_POLICIES,
    ResolvedSkillConfig,
    SkillConfig,
    load_effective_skill_config,
    resolve_external_config_path,
)
from wwise_waapi.dispatcher import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    SUBSCRIPTION_CLEANUP_DETAILS_KEY,
    SUBSCRIPTION_CLEANUP_FAILED,
    SUBSCRIPTION_CLEANUP_UNSUBSCRIBED,
    WwiseDispatcher,
    _normalize_exception as normalize_dispatcher_exception,
    _safe_exception_attribute as safe_exception_attribute,
    _safe_type_name as safe_type_name,
)
from wwise_waapi.execution_contracts import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    AUTHORING_UI_EXECUTION_PROFILE,
    CONTEXT_RUNTIME_ONLY_POST_EXECUTION_URIS,
    CONSOLE_EXECUTION_PROFILE,
    POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY,
    POST_EXECUTION_PROJECT_GUARD_POLICIES,
    POST_EXECUTION_PROJECT_GUARD_REVALIDATE,
    PROJECT_GUARD_INVARIANT,
    PROJECT_GUARD_MODES,
    PROJECT_GUARD_TRANSITION_TO_PATH,
)
from wwise_waapi.operation_registry import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    COMPOSER_INPUT_MODE,
    INLINE_TYPED_INPUT_MODE,
    OPERATION_REQUEST_CONTRACT,
    PACKAGED_TRANSACTION_READBACK_URIS,
    PREPARED_OPERATION_CONTRACT,
    UI_COMMAND_OPERATIONS,
    OperationContractError,
    VerificationResult,
    build_undo_group_execution_plan,
    describe_operation,
    list_operation_specs,
    operation_input_mode,
    operation_request_schema_digest,
    parse_operation_request,
    prepare_object_set_composer_check,
    validate_prepared_roles,
    verify_prepared_operation,
)
from wwise_waapi.typed_operations import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    DRAFT_TYPED_OPERATIONS,
    INLINE_OPERATIONS,
    TypedOperationInputError,
    draft_operation_request_contract,
    inline_operation_contract,
    materialize_inline_operation_request,
)
from wwise_waapi.operation_drafts import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    OPERATION_DRAFT_CONTRACT,
    OperationDraftBindingDrift,
    OperationDraftCheckRequired,
    OperationDraftRecord,
    OperationDraftSealReplayMismatch,
    OperationDraftState,
    OperationDraftStore,
)
from wwise_waapi.operation_composer import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    MAX_TYPED_ACTIONS_PER_APPLY,
    OBJECT_SET_COMPOSER_OPERATION,
    OperationComposerError,
    composition_projection,
    operation_draft_construction_boundary,
    operation_composer_contract,
    operation_composer_digest,
    parse_typed_action_cli_arguments,
    parse_typed_action_cli_argument_sequence,
)
from wwise_waapi.platform_paths import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    WWISE_WIRE_PATH_INPUT_AUDIT_CONTRACT,
    WwiseWirePathError,
    adapt_cli_dispatch_paths,
    requires_wwise_wire_path_adaptation,
)
from wwise_waapi.safety import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    BOUNDED_CALL_CANDIDATES,
    EXPLICIT_UNSUPPORTED_LIVE_URIS,
    EXPLICIT_UNSUPPORTED_TOPIC_URIS,
    REVIEWED_TOPIC_URIS,
)
from wwise_waapi.subscriptions import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    DEFAULT_LISTENER_QUEUE_SIZE,
    MAX_WAIT_EVENT_COUNT,
    SubscriptionManager,
    payload_matches,
)
from wwise_waapi.transaction_locality import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    is_loopback_waapi_host,
    local_filesystem_path_roles,
)
from wwise_waapi.transaction_runtime import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    DEFAULT_PREVIEW_TTL_SECONDS,
    PROJECT_GUARD_PHASE_POST_VERIFICATION,
    TRANSACTION_PREVIEW_CONTRACT,
    TransactionGuardError,
    build_project_guard,
    build_transaction_preview_artifact,
    validate_transaction_context_runtime_guards,
    validate_transaction_guards,
)
from wwise_waapi.transaction_cleanup import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    transaction_cleanup_payload as _transaction_cleanup_payload,
)
from wwise_waapi.transactions import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    CONFIRMATION_TOKEN_MATERIAL_CONTRACT,
    STATE_DIRECTORY_ENV,
    InvalidTransition,
    PreviewAlreadyExists,
    TransactionNotFound,
    TransactionState,
    TransactionStore,
    new_transaction_id,
)
from wwise_waapi.versions import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    SUPPORTED_WWISE_VERSION_KEYS,
    version_key_from_get_info,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_TIMEOUT = 10.0
DEFAULT_METADATA_DISCOVERY_TIMEOUT = 30.0
DEFAULT_TRANSACTION_TIMEOUT = 150.0
TRANSPORT_CLEANUP_GRACE_SECONDS = 0.05
UNBOUNDED_TOPIC_CLEANUP_TIMEOUT_SECONDS = 1.0
TOPIC_CLEANUP_RESERVE_MAX_SECONDS = 0.25
TOPIC_CLEANUP_RESERVE_RATIO = 0.20
GET_INFO_URI = "ak.wwise.core.getInfo"
GET_PROJECT_INFO_URI = "ak.wwise.core.getProjectInfo"
OBJECT_GET_URI = "ak.wwise.core.object.get"
GET_SELECTED_URI = "ak.wwise.ui.getSelectedObjects"
MEDIA_POOL_GET_URI = "ak.wwise.core.mediaPool.get"
ENV_HOST = "WWISE_WAAPI_HOST"
ENV_PORT = "WWISE_WAAPI_PORT"
ENV_VERSION = "WWISE_VERSION"
ENV_EVIDENCE_DIR = "WWISE_EVIDENCE_DIR"
OFFLINE_COMMANDS = frozenset(
    {
        "capabilities",
        "describe",
        "operations",
        "operation-schema",
        "undo-child-schema",
        "request-schema",
        "request-map-container",
        "request-array-item",
        "topic-schema",
        "query-schema",
        "object-types",
        "config-show",
        "config-set",
        "draft-start",
        "draft-apply",
        "draft-inspect",
        "draft-cancel",
        "transaction-show",
        "confirm",
        "reject",
    }
)
GATEWAY_RESULT_CONTRACT = "waapi-skill.gateway-result/v1"
TOPIC_STREAM_RECORD_CONTRACT = "waapi-skill.topic-stream/v1"
GATEWAY_CONFIG_CONTRACT = "waapi-skill.config/v2"
GATEWAY_SESSION_CONTEXT_CONTRACT = "waapi-skill.session-context/v2"
GATEWAY_SESSION_INTRODUCTION_CONTRACT = "waapi-skill.session-introduction/v2"
GATEWAY_DEADLINE_PROVENANCE = "waapi-skill.gateway-deadline/v1"
GATEWAY_RESULT_CEILING_PROVENANCE = "waapi-skill.gateway-live-result-json-ceiling/v1"
MEDIA_POOL_POST_FILTER_CONTRACT = "waapi-skill.media-pool-post-filter/v1"
ORIGINAL_FILE_REFERENCE_MATCH_CONTRACT = (
    "waapi-skill.original-file-reference-match/v1"
)
SUBSCRIPTION_CLEANUP_AFTER_RETRY = "unsubscribed_after_retry"
NAMED_OPERATION_WIRE_PATH_URIS: Mapping[str, str] = {
    "audio.importTabDelimited": "ak.wwise.core.audio.importTabDelimited",
    "lua.executeCliFile": "ak.wwise.cli.executeLuaScript",
    "soundbank.convertExternalSources": (
        "ak.wwise.core.soundbank.convertExternalSources"
    ),
    "soundbank.processDefinitionFiles": (
        "ak.wwise.core.soundbank.processDefinitionFiles"
    ),
}
PROJECT_IDENTITY_FIELDS = ("id", "name", "path")
EXPANDING_QUERY_SELECTS = frozenset({"descendants", "ancestors", "referencesTo", "children"})
MAX_GATEWAY_RESULT_JSON_BYTES = 1024 * 1024
MAX_METADATA_DISCOVERY_GATEWAY_RESULT_BYTES = 32 * 1024
MAX_TOPIC_SCHEMA_GATEWAY_RESULT_BYTES = 32 * 1024
TOPIC_STREAM_POLL_SECONDS = 0.05
TOPIC_STREAM_HEALTH_INTERVAL_SECONDS = 5.0
MAX_GATEWAY_JSON_INPUT_BYTES = 256 * 1024
MAX_GATEWAY_JSON_DEPTH = 32
MAX_GATEWAY_JSON_NODES = 10_000
MAX_GATEWAY_JSON_STRING_BYTES = 64 * 1024
# Transaction preview is the sole public JSON lane that accepts inline audio.
# Keep its envelope well below macOS argv limits while allowing one reviewed
# 180 KiB decoded WAV (roughly 240 KiB of canonical Base64).
MAX_PREVIEW_JSON_INPUT_BYTES = 384 * 1024
MAX_PREVIEW_JSON_STRING_BYTES = 256 * 1024
# ``transaction-show --summary-only`` must carry the exact immutable request,
# but every other review field has a closed projection.  This ceiling bounds
# that summary fragment independently of request complexity; the small outer
# gateway/session envelope keeps its existing contract.  Prepared runtime
# snapshots therefore cannot duplicate and multiply the request size.
TRANSACTION_SHOW_SUMMARY_FIXED_BUDGET_BYTES = 6 * 1024
# Prefer a model-visible summary below this softer target.  The 6 KiB ceiling
# remains the fail-closed boundary for cleanup specs or event chains that cannot
# be reduced further without losing required evidence.
TRANSACTION_SHOW_SUMMARY_TARGET_BYTES = 4 * 1024
TRANSACTION_SHOW_SUMMARY_CONTRACT = "waapi-skill.transaction-show-summary/v1"
TRANSACTION_NEXT_COMMAND_CONTRACT = "waapi-skill.gateway-next-command/v2"
TRANSACTION_COMMAND_COPY_INSTRUCTION_CONTRACT = (
    "waapi-skill.gateway-command-copy-instruction/v2"
)
TRANSACTION_CONFIRMATION_BINDING_CONTRACT = (
    "waapi-skill.confirmation-binding/v1"
)
# A successful non-terminal execute reply only needs enough information for the
# caller to continue with ``verify``.  The complete dispatcher result and guard
# evidence remain sealed in the transaction journal; stdout gets a bounded,
# digest-bound projection so a large import cannot hide the transaction state
# behind a tool-output truncation.  Reserve space for the session context added
# by ``finish`` after this projection is built.
TRANSACTION_EXECUTE_SUCCESS_STDOUT_BUDGET_BYTES = 24 * 1024
TRANSACTION_EXECUTE_SUCCESS_ENVELOPE_RESERVE_BYTES = 2 * 1024
TRANSACTION_EXECUTE_SUCCESS_SUMMARY_CONTRACT = (
    "waapi-skill.transaction-execute-success-summary/v1"
)
TRANSACTION_ROLE_VALIDATION_SUMMARY_CONTRACT = (
    "waapi-skill.transaction-role-validation-summary/v1"
)
# A terminal successful verification, whether strongly ``verified`` or the
# explicit weaker ``result_schema_checked`` boundary, has already sealed its
# complete evidence in ``verification_recorded``.  Keep stdout small enough
# for the agent broker while retaining the exact ``agent_result`` and a
# canonical digest that binds the projection to the journal evidence.
# Projection is intentionally delayed until transport cleanup succeeds.
TRANSACTION_VERIFY_SUCCESS_STDOUT_BUDGET_BYTES = 24 * 1024
TRANSACTION_VERIFY_SUCCESS_ENVELOPE_RESERVE_BYTES = 2 * 1024
TRANSACTION_VERIFY_SUCCESS_SUMMARY_CONTRACT = (
    "waapi-skill.transaction-verify-success-summary/v1"
)
TRANSACTION_VERIFICATION_RESULT_SUMMARY_CONTRACT = (
    "waapi-skill.transaction-verification-result-summary/v1"
)
MAX_MEDIA_POOL_RESULTS = 200
MAX_MEDIA_POOL_FILTERS = 16
MAX_MEDIA_POOL_DATABASES = 8
MAX_MEDIA_POOL_RETURN_FIELDS = 32
MAX_MEDIA_POOL_SEARCH_TEXT_CHARS = 1024
MAX_MEDIA_POOL_FILTER_TOKEN_CHARS = 256
MAX_MEDIA_POOL_FILTER_VALUE_CHARS = 4096
SELECTED_REQUIRED_RETURN_FIELDS = ("id", "name", "type", "path")
MAX_SELECTED_RETURN_FIELDS = 32
MAX_SELECTED_RETURN_FIELD_CHARS = 256
MEDIA_POOL_FLOAT_FILTER_FIELDS_BY_VERSION: Mapping[str, frozenset[str]] = {
    "2025.1": frozenset({"WAV/Duration"}),
}
ORIGINAL_FILE_REFERENCE_MATCH_VERSION = "2025.1"
ORIGINAL_FILE_REFERENCE_MATCH_TYPE = "AudioFileSource"
ORIGINAL_FILE_REFERENCE_RETURN_FIELDS = ("id", "path", "originalFilePath")
MAX_ORIGINAL_FILE_PATH_CANDIDATES = 64
MAX_ORIGINAL_FILE_PATH_BYTES = 1024
MAX_ORIGINAL_FILE_REFERENCE_PATH_BYTES = 512
_METADATA_SESSION_CACHE = SessionMetadataCache()
MAX_ORIGINAL_FILE_REFERENCE_DETAILS_PER_CANDIDATE = 4
MAX_ORIGINAL_FILE_REFERENCE_DETAILS = (
    MAX_ORIGINAL_FILE_PATH_CANDIDATES
    * MAX_ORIGINAL_FILE_REFERENCE_DETAILS_PER_CANDIDATE
)
UNDO_GROUP_CANCEL_RESERVE_MIN_SECONDS = 2.0
UNDO_GROUP_CANCEL_RESERVE_MAX_SECONDS = 10.0
UNDO_GROUP_CANCEL_RESERVE_RATIO = 0.20
# Keep the authoritative pretty-printed phase document well below the public
# 1 MiB gateway envelope.  The remaining space is reserved for the transaction
# identity, project/role guard summaries, cleanup projection, and JSON framing.
UNDO_GROUP_MAX_ACCUMULATED_RESULT_BYTES = 256 * 1024
REFLECTION_INVENTORY_CALLS = {
    "ak.wwise.waapi.getFunctions": ("functions", "function"),
    "ak.wwise.waapi.getTopics": ("topics", "topic"),
}
MAX_REFLECTION_INVENTORY_ITEMS = 4096
MAX_REFLECTION_URI_BYTES = 512


class GatewayInputError(ValueError):
    """Raised for invalid gateway input before a WAAPI call is attempted."""


class GatewayResultShapeError(ValueError):
    """Raised when a successful response violates one public gateway contract."""

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any],
        error_code: str = "INVALID_QUERY_RESULT",
    ) -> None:
        super().__init__(message)
        self.details = dict(details)
        self.error_code = error_code

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": dict(self.details),
        }


class AuthoringUiRuntimeManifestStore:
    """Read-only dispatcher adapter for the explicit Authoring UI profile."""

    def __init__(self, base_store: Any) -> None:
        self._base_store = base_store

    def load(self, version: str) -> dict[str, Any]:
        return self._base_store.load_with_authoring_ui_commands(version)


class GatewaySubscriptionCleanupError(RuntimeError):
    """A transport-owned subscription did not explicitly unsubscribe."""

    error_code = "SUBSCRIPTION_CLEANUP_FAILED"

    def __init__(self, token: int, *, reason: str) -> None:
        super().__init__("WAAPI subscription cleanup did not explicitly succeed")
        self.token = token
        self.reason = reason

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": {
                "subscription_token": self.token,
                "reason": self.reason,
            },
        }


class GatewayTimeoutError(TimeoutError):
    """Structured end-to-end gateway deadline failure."""

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        configured_timeout: float,
        elapsed: float,
        operation_timeout: float | None = None,
        cleanup_pending: bool = False,
        abort_requested: bool = False,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.configured_timeout = configured_timeout
        self.elapsed = elapsed
        self.operation_timeout = operation_timeout
        self.cleanup_pending = cleanup_pending
        self.abort_requested = abort_requested

    def mark_cleanup_pending(self, *, abort_requested: bool = False) -> None:
        self.cleanup_pending = True
        self.abort_requested = self.abort_requested or abort_requested

    def as_dict(self) -> dict[str, Any]:
        unbounded = math.isinf(self.configured_timeout)
        details: dict[str, Any] = {
            "provenance": GATEWAY_DEADLINE_PROVENANCE,
            "phase": self.phase,
            "configured_timeout_seconds": (
                None if unbounded else self.configured_timeout
            ),
            "timeout_mode": "unbounded" if unbounded else "finite",
            "elapsed_seconds": self.elapsed,
            "deadline_exhausted": (
                False if unbounded else self.elapsed >= self.configured_timeout
            ),
            "cleanup_pending": self.cleanup_pending,
            "abort_requested": self.abort_requested,
        }
        if self.operation_timeout is not None:
            details["operation_timeout_seconds"] = (
                None
                if math.isinf(self.operation_timeout)
                else self.operation_timeout
            )
        return {
            "error_code": "TIMEOUT",
            "message": str(self),
            "details": details,
        }


@dataclass(frozen=True, slots=True)
class GatewayDeadline:
    """One monotonic wall-clock budget shared by the complete live command."""

    timeout: float
    started_at: float
    expires_at: float

    @classmethod
    def start(cls, timeout: float) -> "GatewayDeadline":
        started_at = time.monotonic()
        return cls(timeout=timeout, started_at=started_at, expires_at=started_at + timeout)

    @property
    def cleanup_expires_at(self) -> float:
        if math.isinf(self.expires_at):
            return time.monotonic() + UNBOUNDED_TOPIC_CLEANUP_TIMEOUT_SECONDS
        return self.expires_at + TRANSPORT_CLEANUP_GRACE_SECONDS

    def remaining(self, *, cleanup: bool = False) -> float:
        expires_at = self.cleanup_expires_at if cleanup else self.expires_at
        return max(0.0, expires_at - time.monotonic())

    def elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    def timeout_error(
        self,
        phase: str,
        *,
        operation_timeout: float | None = None,
        cleanup_pending: bool = False,
        abort_requested: bool = False,
    ) -> GatewayTimeoutError:
        elapsed = self.elapsed()
        return GatewayTimeoutError(
            f"Gateway timed out after {elapsed:.3f}s during {phase}",
            phase=phase,
            configured_timeout=self.timeout,
            elapsed=elapsed,
            operation_timeout=operation_timeout,
            cleanup_pending=cleanup_pending,
            abort_requested=abort_requested,
        )

    def require_remaining(self, phase: str) -> float:
        remaining = self.remaining()
        if remaining <= 0:
            raise self.timeout_error(phase)
        return remaining


def _blocking_timeout(seconds: float) -> float | None:
    """Translate an internal unbounded deadline into Python's blocking API."""

    return None if math.isinf(seconds) else max(0.0, seconds)


@dataclass(frozen=True, slots=True)
class GatewayConnection:
    host: str
    port: int
    version_hint: str | None
    evidence_dir: Path | None
    timeout: float
    deadline: GatewayDeadline

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/waapi"


ClientFactory = Callable[[str], Any]


@dataclass(frozen=True, slots=True)
class _TransportRequest:
    request_id: str
    phase: str
    operation: str
    args: tuple[Any, ...]
    kwargs: Mapping[str, Any]
    response: queue.Queue[tuple[bool, Any]]
    expires_at: float
    cancelled: threading.Event


@dataclass(frozen=True, slots=True)
class _TransportSubscription:
    """Opaque reference to an EventHandler owned by the transport thread."""

    token: int


class GatewayTransport:
    """Own one WAAPI client and all of its operations on one caller thread.

    ``waapi-client`` stores an asyncio event loop on the client and mutates global
    txaio loop state. Creating or using clients from the dispatcher's short-lived
    timeout threads can therefore close a loop still referenced by another client.
    This transport serializes every synchronous client operation through one owner
    thread. Every request shares the gateway's monotonic deadline; an expired
    caller abandons its own response queue, so a late result can never satisfy a
    later request. The owner remains daemonized only for the unavoidable case of
    an injected third-party callable that neither returns nor exposes cancellation.
    """

    def __init__(
        self,
        url: str,
        client_factory: ClientFactory,
        *,
        deadline: GatewayDeadline | None = None,
    ) -> None:
        self.url = url
        self.client_factory = client_factory
        self.deadline = deadline or GatewayDeadline.start(DEFAULT_TIMEOUT)
        self._requests: queue.Queue[_TransportRequest] = queue.Queue()
        self._ready: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
        self._closed = threading.Event()
        self._abandoned = threading.Event()
        self._client: Any = None
        self._last_timeout: GatewayTimeoutError | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"waapi-gateway-owner:{uuid.uuid4().hex[:8]}",
            daemon=True,
        )
        self._thread.start()
        ready_timeout = self.deadline.remaining()
        if math.isinf(ready_timeout):
            # No-timeout applies only to the established Topic wait. A stuck
            # client constructor must not turn connection setup into an
            # unbounded phase.
            ready_timeout = DEFAULT_TIMEOUT
        if ready_timeout <= 0:
            self._abandoned.set()
            self._closed.set()
            self._requests.put(self._close_request())
            error = self.deadline.timeout_error("transport.connect", cleanup_pending=True)
            self._last_timeout = error
            raise error
        try:
            ok, payload = self._ready.get(timeout=_blocking_timeout(ready_timeout))
        except queue.Empty as exc:
            self._abandoned.set()
            self._closed.set()
            self._requests.put(self._close_request())
            abort_requested = self._abort_pending_client()
            error = self.deadline.timeout_error(
                "transport.connect",
                cleanup_pending=self._thread.is_alive(),
                abort_requested=abort_requested,
            )
            self._last_timeout = error
            raise error from exc
        if not ok:
            raise payload

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        return self._request("call", uri, args, options=options, phase=f"WAAPI call {uri}")

    def call_with_timeout(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        *,
        phase: str | None = None,
    ) -> Any:
        """Call without the dispatcher's extra helper thread.

        ``WwiseDispatcher`` feature-detects this method. The request gets the
        smaller of its local timeout and the end-to-end gateway deadline.
        """

        operation_timeout = self.deadline.remaining() if timeout is None else max(0.0, float(timeout))
        return self._request(
            "call",
            uri,
            args,
            options=options,
            phase=phase or f"WAAPI call {uri}",
            timeout=operation_timeout,
        )

    def subscribe(self, uri: str, callback: Any, options: Mapping[str, Any] | None = None) -> Any:
        setup_timeout = (
            DEFAULT_TIMEOUT if math.isinf(self.deadline.timeout) else None
        )
        return self._request(
            "subscribe",
            uri,
            callback,
            options=options,
            phase=f"WAAPI subscribe {uri}",
            timeout=setup_timeout,
        )

    def unsubscribe(self, subscription: Any) -> Any:
        return self._request("unsubscribe", subscription, phase="WAAPI unsubscribe", cleanup=True)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        request = self._close_request()
        self._requests.put(request)
        try:
            ok, payload = request.response.get(
                timeout=_blocking_timeout(self.deadline.remaining(cleanup=True))
            )
        except queue.Empty as exc:
            abort_requested = self._abort_pending_client()
            error = self._last_timeout or self.deadline.timeout_error(
                "transport.close",
                cleanup_pending=True,
                abort_requested=abort_requested,
            )
            error.mark_cleanup_pending(abort_requested=abort_requested)
            self._last_timeout = error
            raise error from exc
        self._thread.join(
            timeout=_blocking_timeout(self.deadline.remaining(cleanup=True))
        )
        if self._thread.is_alive():
            abort_requested = self._abort_pending_client()
            error = self._last_timeout or self.deadline.timeout_error(
                "transport.close",
                cleanup_pending=True,
                abort_requested=abort_requested,
            )
            error.mark_cleanup_pending(abort_requested=abort_requested)
            self._last_timeout = error
            raise error
        if self._last_timeout is not None:
            self._last_timeout.cleanup_pending = False
        if not ok:
            raise payload

    def _request(
        self,
        operation: str,
        *args: Any,
        phase: str,
        timeout: float | None = None,
        cleanup: bool = False,
        **kwargs: Any,
    ) -> Any:
        if self._closed.is_set():
            raise RuntimeError("WAAPI gateway transport is closed")
        now = time.monotonic()
        global_expires_at = self.deadline.cleanup_expires_at if cleanup else self.deadline.expires_at
        local_expires_at = global_expires_at if timeout is None else now + timeout
        expires_at = min(global_expires_at, local_expires_at)
        operation_timeout = max(0.0, expires_at - now)
        if operation_timeout <= 0:
            error = self.deadline.timeout_error(
                phase,
                operation_timeout=operation_timeout,
                cleanup_pending=self._thread.is_alive(),
            )
            self._last_timeout = error
            raise error
        response: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
        request = _TransportRequest(
            request_id=uuid.uuid4().hex,
            phase=phase,
            operation=operation,
            args=args,
            kwargs=kwargs,
            response=response,
            expires_at=expires_at,
            cancelled=threading.Event(),
        )
        self._requests.put(request)
        try:
            ok, payload = response.get(
                timeout=_blocking_timeout(
                    max(0.0, expires_at - time.monotonic())
                )
            )
        except queue.Empty as exc:
            request.cancelled.set()
            abort_requested = self._abort_pending_client()
            error = self.deadline.timeout_error(
                phase,
                operation_timeout=operation_timeout,
                cleanup_pending=self._thread.is_alive(),
                abort_requested=abort_requested,
            )
            self._last_timeout = error
            raise error from exc
        if ok:
            return payload
        raise payload

    def _close_request(self) -> _TransportRequest:
        return _TransportRequest(
            request_id=uuid.uuid4().hex,
            phase="transport.close",
            operation="close",
            args=(),
            kwargs={},
            response=queue.Queue(maxsize=1),
            expires_at=self.deadline.cleanup_expires_at,
            cancelled=threading.Event(),
        )

    def _abort_pending_client(self) -> bool:
        """Best-effort, non-blocking cancellation for the packaged waapi-client.

        waapi-client 0.8.x has no public RPC cancellation API. Stopping its
        private event loop closes the WAMP transport and releases the owner call;
        no arbitrary injected method is invoked because that could itself block.
        """

        client = self._client
        loop = getattr(client, "_loop", None)
        call_soon_threadsafe = getattr(loop, "call_soon_threadsafe", None)
        stop = getattr(loop, "stop", None)
        if not callable(call_soon_threadsafe) or not callable(stop):
            return False
        try:
            call_soon_threadsafe(stop)
        except BaseException:  # noqa: BLE001 - abort must never mask the timeout
            return False
        return True

    @staticmethod
    def _deliver(request: _TransportRequest, payload: tuple[bool, Any]) -> None:
        # ``Queue.get(timeout=...)`` is permitted to return an item that was
        # published after its timeout when the waiting thread was not scheduled
        # promptly.  Enforce the request's monotonic deadline on the producer
        # side as well, so an overloaded host cannot turn a late WAAPI result
        # into an apparent in-budget success.
        if request.cancelled.is_set() or (
            request.operation != "close"
            and time.monotonic() >= request.expires_at
        ):
            request.cancelled.set()
            return
        try:
            request.response.put_nowait(payload)
        except queue.Full:
            return

    def _run(self) -> None:
        try:
            client = self.client_factory(self.url)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the creating thread
            if not self._abandoned.is_set():
                self._ready.put((False, exc))
            return
        self._client = client
        subscriptions: dict[int, Any] = {}
        next_subscription_token = 1
        if self._abandoned.is_set():
            _close_transport_client(client, subscriptions)
            return
        self._ready.put((True, None))
        while True:
            request = self._requests.get()
            if request.operation != "close" and (
                request.cancelled.is_set() or time.monotonic() >= request.expires_at
            ):
                continue
            try:
                if request.operation == "close":
                    self._deliver(request, _close_transport_client(client, subscriptions))
                    return
                if request.operation == "call":
                    uri, args = request.args
                    options = request.kwargs.get("options")
                    if args is None and options is None:
                        result = client.call(uri)
                    elif options is None:
                        result = client.call(uri, args)
                    elif args is None:
                        result = client.call(uri, options=options)
                    else:
                        result = client.call(uri, args, options=options)
                elif request.operation == "subscribe":
                    uri, callback = request.args
                    options = request.kwargs.get("options")
                    result = client.subscribe(uri, callback) if options is None else client.subscribe(uri, callback, options)
                    if result is not None:
                        token = next_subscription_token
                        next_subscription_token += 1
                        subscriptions[token] = result
                        result = _TransportSubscription(token)
                elif request.operation == "unsubscribe":
                    (subscription,) = request.args
                    if not isinstance(subscription, _TransportSubscription):
                        raise TypeError("GatewayTransport.unsubscribe requires an opaque transport subscription")
                    handler = subscriptions.get(subscription.token)
                    if handler is None:
                        result = False
                    else:
                        result = _unsubscribe_event_handler(client, handler) is True
                        if result:
                            subscriptions.pop(subscription.token, None)
                else:
                    method = getattr(client, request.operation)
                    result = method(*request.args, **dict(request.kwargs))
                self._deliver(request, (True, result))
            except BaseException as exc:  # noqa: BLE001 - transferred to the requesting thread
                self._deliver(request, (False, exc))


def _close_transport_client(client: Any, subscriptions: dict[int, Any]) -> tuple[bool, Any]:
    """Clean one owner-thread client and preserve the first cleanup failure."""

    cleanup_error: BaseException | None = None
    for token, handler in tuple(subscriptions.items()):
        try:
            succeeded = _unsubscribe_event_handler(client, handler) is True
        except BaseException as exc:  # noqa: BLE001 - transferred to the closing thread
            if cleanup_error is None:
                cleanup_error = exc
        else:
            if not succeeded and cleanup_error is None:
                cleanup_error = GatewaySubscriptionCleanupError(
                    token,
                    reason="unsubscribe_returned_false",
                )
            if succeeded:
                subscriptions.pop(token, None)
    try:
        disconnect = getattr(client, "disconnect", None)
        result = disconnect() if callable(disconnect) else None
    except BaseException as exc:  # noqa: BLE001 - transferred to the closing thread
        if cleanup_error is None:
            cleanup_error = exc
        result = None
    return cleanup_error is None, result if cleanup_error is None else cleanup_error


def _unsubscribe_event_handler(client: Any, handler: Any) -> Any:
    """Unsubscribe one raw handler while executing on the transport owner thread."""

    unsubscribe = getattr(handler, "unsubscribe", None)
    if callable(unsubscribe):
        return unsubscribe()
    client_unsubscribe = getattr(client, "unsubscribe", None)
    if callable(client_unsubscribe):
        return client_unsubscribe(handler)
    raise RuntimeError("WAAPI subscription handler cannot be unsubscribed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gateway.py",
        description=(
            "Call the manifest-backed WAAPI Skill gateway and print one JSON result, "
            "or flushed JSON records for stream-topic."
        ),
    )
    parser.add_argument("--host", help=f"WAAPI host; defaults to ${ENV_HOST}, then saved config")
    parser.add_argument("--port", type=int, help=f"WAAPI port; defaults to ${ENV_PORT}, then saved config")
    parser.add_argument(
        "--version",
        "--wwise-version",
        dest="version",
        help=f"Expected Wwise year.major; defaults to ${ENV_VERSION}, then saved config, then live detection",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=(
            f"Whole-command deadline in seconds; defaults to {DEFAULT_TIMEOUT:g} for ordinary reads/bounded topics, "
            f"{DEFAULT_METADATA_DISCOVERY_TIMEOUT:g} for live metadata discovery, "
            f"{DEFAULT_TRANSACTION_TIMEOUT:g} for preview/execute/verify transactions, "
            "and no time limit for stream-topic"
        ),
    )
    parser.add_argument("--evidence-dir", help=f"Dispatcher evidence directory; defaults to ${ENV_EVIDENCE_DIR}")
    parser.add_argument(
        "--state-dir",
        help=(
            f"Gateway runtime state directory; defaults to ${STATE_DIRECTORY_ENV}, "
            "then $XDG_STATE_HOME/waapi-skill or $HOME/.local/state/waapi-skill"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Return live Wwise version and current project information")
    subparsers.add_parser("buses", help="Return all Bus objects with id, name, type, and path")
    selected = subparsers.add_parser(
        "selected",
        help="Return current UI selection or a clear command-line/UI boundary",
    )
    selected.add_argument(
        "--return-field",
        action="append",
        dest="return_fields",
        help=(
            "Add one bounded object accessor to the selected-object projection; "
            "id, name, type, and path are always retained"
        ),
    )
    subparsers.add_parser(
        "project-default-work-units",
        help="Report version-aware default project Work Units without fabricating unavailable fields",
    )

    profiler_game_objects = subparsers.add_parser(
        "profiler-game-objects",
        help="Return profiler game objects through a cross-version registration-time projection",
    )
    profiler_game_objects.add_argument(
        "--time",
        required=True,
        help="Non-negative capture time in milliseconds, or the exact cursor token user/capture",
    )

    profiler_voice_contributions = subparsers.add_parser(
        "profiler-voice-contributions",
        help="Return one bounded voice contribution tree with version-aware DSF availability",
    )
    profiler_voice_contributions.add_argument(
        "--time",
        required=True,
        help="Non-negative capture time in milliseconds, or the exact cursor token user/capture",
    )
    profiler_voice_contributions.add_argument(
        "--voice-pipeline-id",
        required=True,
        help="Unsigned 32-bit voice pipeline identifier",
    )
    profiler_voice_contributions.add_argument(
        "--bus-pipeline-id",
        action="append",
        default=[],
        help="Repeat in voice-path order; omit all values for the dry path",
    )

    request_schema = subparsers.add_parser(
        "request-schema",
        help="Return the one typed construction continuation for a migrated WAAPI API",
    )
    request_schema.add_argument("api")

    typed_zero_call = subparsers.add_parser(
        "typed-zero-call",
        help="Run one reflected function whose exact schema accepts no business input",
    )
    typed_zero_call.add_argument("api")
    typed_zero_call.add_argument("--schema-digest", required=True)
    typed_zero_call.add_argument(
        "--apply",
        action="store_true",
        help="Enter the existing Preview authorization lifecycle for a change",
    )
    typed_zero_call.add_argument(
        "--ttl",
        type=int,
        default=DEFAULT_PREVIEW_TTL_SECONDS,
    )

    request_map_container = subparsers.add_parser(
        "request-map-container",
        help="Issue a schema-bound child handle for one open-map key",
    )
    request_map_container.add_argument("api")
    request_map_container.add_argument("--schema-digest")
    request_map_container.add_argument("--map-handle", required=True)
    request_map_container.add_argument("--key", required=True)
    request_map_container.add_argument("--shape", choices=("object", "array"), required=True)
    request_map_container.add_argument(
        "--choice-handle",
        help="Gateway-disclosed opaque branch choice for an ambiguous map member",
    )
    request_map_container.add_argument(
        "--member-key",
        help="Exact child-object key whose opaque branch choices must be disclosed",
    )
    request_map_container.add_argument("--parent-schema-token")

    request_array_item = subparsers.add_parser(
        "request-array-item",
        help="Issue a schema-bound child handle for one ordered complex array item",
    )
    request_array_item.add_argument("api")
    request_array_item.add_argument("--schema-digest")
    request_array_item.add_argument("--array-handle", required=True)
    request_array_item.add_argument("--index", required=True, type=int)
    request_array_item.add_argument("--shape", choices=("object", "array"), required=True)
    request_array_item.add_argument(
        "--choice-handle",
        help="Gateway-disclosed opaque branch choice for an ambiguous complex item",
    )
    request_array_item.add_argument(
        "--member-key",
        help="Exact child-object key whose opaque branch choices must be disclosed",
    )
    request_array_item.add_argument("--parent-schema-token")

    typed_call = subparsers.add_parser(
        "typed-call",
        help="Run one migrated API from Gateway-owned typed field handles",
    )
    typed_call.add_argument("api")
    typed_call.add_argument("--schema-digest", required=True)
    typed_call.add_argument(
        "--io-root",
        help="Absolute caller-owned I/O authority for an isolated typed route",
    )
    typed_call.add_argument(
        "--apply",
        action="store_true",
        help="Enter the existing Preview authorization lifecycle for a change",
    )
    typed_call.add_argument(
        "--ttl",
        type=int,
        default=DEFAULT_PREVIEW_TTL_SECONDS,
    )
    typed_call.add_argument(
        "--set",
        action="append",
        nargs=3,
        metavar=("FIELD_HANDLE", "TYPE", "VALUE"),
        default=[],
        dest="typed_set_facts",
    )
    typed_call.add_argument(
        "--append",
        action="append",
        nargs=3,
        metavar=("FIELD_HANDLE", "TYPE", "VALUE"),
        default=[],
        dest="typed_append_facts",
    )
    typed_call.add_argument(
        "--present",
        action="append",
        metavar="CONTAINER_HANDLE",
        default=[],
        dest="typed_present_facts",
    )
    typed_call.add_argument(
        "--choose",
        action="append",
        nargs=2,
        metavar=("BRANCH_HANDLE", "CHOICE_HANDLE"),
        default=[],
        dest="typed_branch_facts",
    )

    typed_operation = subparsers.add_parser(
        "typed-operation",
        help="Preview one concise dedicated operation from typed business values",
    )
    typed_operation.add_argument("operation", choices=tuple(sorted(INLINE_OPERATIONS)))
    typed_operation.add_argument("--schema-digest", required=True)
    typed_operation.add_argument("--apply", action="store_true", required=True)
    typed_operation.add_argument("--ttl", type=int, default=DEFAULT_PREVIEW_TTL_SECONDS)
    typed_operation.add_argument("--object", nargs="+", dest="typed_object")
    typed_operation.add_argument("--switch-container", nargs="+")
    typed_operation.add_argument("--child", nargs="+")
    typed_operation.add_argument("--state-or-switch", nargs="+")
    typed_operation.add_argument("--text")
    typed_operation.add_argument("--property")
    typed_operation.add_argument("--reference")
    typed_operation.add_argument("--value", nargs=2, metavar=("TYPE", "VALUE"))
    typed_operation.add_argument("--platform")
    typed_operation.add_argument("--target", nargs="+")
    typed_operation.add_argument("--clear", action="store_true")
    typed_operation.add_argument("--linked", choices=("true", "false"))
    typed_operation.add_argument("--parent", nargs="+")
    typed_operation.add_argument("--on-name-conflict", choices=("fail", "rename", "replace"))
    typed_operation.add_argument("--auto-check-out", choices=("true", "false"))
    typed_operation.add_argument("--auto-add", choices=("true", "false"))
    typed_operation.add_argument("--import-file")
    typed_operation.add_argument("--import-location", nargs="+")
    typed_operation.add_argument("--import-language")
    typed_operation.add_argument(
        "--import-operation",
        choices=("createNew", "useExisting", "replaceExisting"),
    )
    typed_operation.add_argument("--file", action="append", dest="files")
    typed_operation.add_argument("--io-root")
    typed_operation.add_argument("--view-name")
    typed_operation.add_argument("--view-channel")
    typed_operation.add_argument("--rect", nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    typed_operation.add_argument("--command", dest="typed_ui_command")
    typed_operation.add_argument("--command-object", action="append", dest="command_objects")
    typed_operation.add_argument("--command-platform", action="append", dest="command_platforms")
    typed_operation.add_argument("--enable", choices=("true", "false"))
    typed_call.add_argument(
        "--choose-dynamic",
        action="append",
        nargs=3,
        metavar=("OBJECT_HANDLE", "KEY", "CHOICE_HANDLE"),
        default=[],
        dest="typed_dynamic_branch_facts",
    )
    for action_name in ("map-put", "map-correct"):
        typed_call.add_argument(
            f"--{action_name}",
            action="append",
            nargs=4,
            metavar=("MAP_HANDLE", "KEY", "TYPE", "VALUE"),
            default=[],
            dest=f"typed_{action_name.replace('-', '_')}_facts",
        )
    typed_call.add_argument(
        "--map-remove",
        action="append",
        nargs=2,
        metavar=("MAP_HANDLE", "KEY"),
        default=[],
        dest="typed_map_remove_facts",
    )

    debug_wal_tree = subparsers.add_parser(
        "debug-wal-tree",
        help="Return a bounded deterministic projection of the private WAL tree",
    )
    debug_wal_tree.add_argument(
        "--take",
        type=int,
        default=128,
        metavar=f"1..{MAX_WAL_TREE_NODES}",
        help=(
            "Maximum WAL nodes returned after the complete bounded call; "
            f"defaults to 128 and is capped at {MAX_WAL_TREE_NODES}"
        ),
    )

    query_object = subparsers.add_parser(
        "query-object",
        help="Run a source-grounded read-only object query without composing WAAPI code",
    )
    query_source = query_object.add_mutually_exclusive_group()
    query_source.add_argument("--path")
    query_source.add_argument("--object-id")
    query_source.add_argument("--type", dest="object_type")
    query_source.add_argument("--search")
    query_source.add_argument(
        "--query",
        metavar="QUERY_PATH_OR_GUID",
        help=(
            "Query Editor object specifier: canonical {GUID} or absolute "
            r"\Queries\... path; raw WAQL is not accepted"
        ),
    )
    query_source.add_argument(
        "--typed-advanced",
        action="store_true",
        help="Use Gateway-owned typed facts for the bounded advanced WAQL layer",
    )
    query_source.add_argument(
        "--typed-structured",
        action="store_true",
        help="Use Gateway-owned typed facts for the structured Builder layer",
    )
    query_object.add_argument("--schema-digest")
    query_object.add_argument("--waql")
    query_object.add_argument("--advanced-return", action="append", default=[])
    query_object.add_argument("--max-results", type=int)
    query_object.add_argument(
        "--typed-schema-digest",
        help="Bind structured typed facts to the exact configured-version query schema",
    )
    query_object.add_argument(
        "--typed-set",
        action="append",
        nargs=3,
        metavar=("FIELD_HANDLE", "TYPE", "VALUE"),
        default=[],
    )
    query_object.add_argument(
        "--typed-append",
        action="append",
        nargs=3,
        metavar=("FIELD_HANDLE", "TYPE", "VALUE"),
        default=[],
    )
    query_object.add_argument(
        "--typed-present",
        action="append",
        metavar="CONTAINER_HANDLE",
        default=[],
    )
    query_object.add_argument(
        "--typed-choose",
        action="append",
        nargs=2,
        metavar=("BRANCH_HANDLE", "CHOICE_HANDLE"),
        default=[],
    )
    query_object.add_argument(
        "--typed-choose-dynamic",
        action="append",
        nargs=3,
        metavar=("OBJECT_HANDLE", "KEY", "CHOICE_HANDLE"),
        default=[],
    )
    for action_name in ("map-put", "map-correct"):
        query_object.add_argument(
            f"--typed-{action_name}",
            action="append",
            nargs=4,
            metavar=("MAP_HANDLE", "KEY", "TYPE", "VALUE"),
            default=[],
            dest=f"typed_query_{action_name.replace('-', '_')}",
        )
    query_object.add_argument(
        "--typed-map-remove",
        action="append",
        nargs=2,
        metavar=("MAP_HANDLE", "KEY"),
        default=[],
        dest="typed_query_map_remove",
    )
    query_object.add_argument(
        "--where",
        nargs=4,
        action="append",
        default=[],
        metavar=("FIELD", "OPERATOR", "TYPE", "VALUE"),
        help=(
            "Append one typed conjunctive predicate; TYPE is string, integer, "
            "number, or boolean"
        ),
    )
    query_object.add_argument(
        "--match-original-file-path",
        action="append",
        dest="match_original_file_paths",
        metavar="ABSOLUTE_PATH",
        help=(
            "Repeat for 1..64 absolute Media Pool candidate paths; only the fixed "
            "2025.1 AudioFileSource take-1000 reference-match mode accepts this option"
        ),
    )
    query_object.add_argument(
        "--select",
        action="append",
        choices=SUPPORTED_SELECTS,
        help="Append one supported read-only WAQL select transform",
    )
    query_bound = query_object.add_mutually_exclusive_group()
    query_bound.add_argument(
        "--take",
        type=int,
        metavar=f"0..{MAX_QUERY_TAKE}",
        help=f"Bound returned rows to at most {MAX_QUERY_TAKE}; larger values fail closed",
    )
    query_bound.add_argument(
        "--all-results",
        action="store_true",
        help="Explicitly allow an unbounded broad query; otherwise broad sources/selects require --take",
    )
    query_object.add_argument("--return-field", action="append", dest="return_fields")
    query_object.add_argument(
        "--detail",
        action="store_true",
        help=(
            "Include the compiled semantic preview and dispatcher evidence on "
            "success; failures skip compact projection but still obey the "
            "global result ceiling"
        ),
    )

    metadata = subparsers.add_parser(
        "metadata",
        help="Run one fixed property/reference metadata query through its semantic builder",
    )
    metadata.add_argument(
        "operation",
        choices=(
            "types",
            "names",
            "property-info",
            "property-enabled",
            "attenuation-curve",
            "discover",
        ),
    )
    metadata.add_argument("--object")
    metadata.add_argument("--class-id", type=int)
    metadata.add_argument(
        "--object-type",
        help=(
            "Exact live Wwise object type name for metadata discover; resolved "
            "through getTypes before class-scoped discovery"
        ),
    )
    metadata.add_argument("--property")
    metadata.add_argument("--platform")
    metadata.add_argument("--curve-type")
    metadata.add_argument(
        "--query",
        action="append",
        dest="queries",
        metavar="SEARCH_PHRASE",
        help=(
            "Repeat 1..8 natural-language search phrases for metadata discover; "
            "the gateway returns live lexical candidates without selecting one"
        ),
    )
    metadata.add_argument(
        "--limit",
        type=int,
        metavar=f"1..{MAX_METADATA_DISCOVERY_LIMIT}",
        help=(
            "Maximum candidates returned per discovery phrase; defaults to "
            f"{DEFAULT_METADATA_DISCOVERY_LIMIT}"
        ),
    )
    metadata.add_argument(
        "--detail",
        action="store_true",
        help=(
            "For metadata discover only, opt into the larger legacy-v1 full "
            "live-metadata audit view; ordinary mutation selection uses the "
            "compact v2 default"
        ),
    )
    metadata.add_argument(
        "--summary-only",
        action="store_true",
        help=(
            "For metadata types only, omit the normalized type inventory and return "
            "the packaged count/ActorMixer projection"
        ),
    )

    wait_topic = subparsers.add_parser(
        "wait-topic",
        help="Collect a bounded count of manifest topic events, with optional payload match and guaranteed cleanup",
    )
    wait_topic.add_argument("api")
    add_typed_topic_input_arguments(wait_topic)
    wait_topic.add_argument(
        "--event-count",
        type=int,
        default=1,
        metavar=f"1..{MAX_WAIT_EVENT_COUNT}",
        help=(
            "Number of matching events to collect before unsubscribe; defaults to 1 "
            f"and is capped at {MAX_WAIT_EVENT_COUNT}"
        ),
    )
    wait_topic.add_argument(
        "--no-timeout",
        action="store_true",
        help=(
            "Wait without a Skill-imposed time limit until the requested bounded "
            "event count arrives or the command is cancelled; cannot be combined "
            "with global --timeout"
        ),
    )

    stream_topic = subparsers.add_parser(
        "stream-topic",
        help=(
            "Keep one manifest topic subscription open and emit each matching "
            "event immediately as a flushed JSON record"
        ),
    )
    stream_topic.add_argument("api")
    add_typed_topic_input_arguments(stream_topic)

    topic_schema = subparsers.add_parser(
        "topic-schema",
        help="Describe exact-version typed subscription options and event matching offline",
    )
    topic_schema.add_argument("api")

    capabilities = subparsers.add_parser(
        "capabilities",
        help="List a compact packaged version-aware capability matrix without connecting to Wwise",
        description=(
            "Start with --summary-only for a broad overview, then add filters for compact rows. "
            "Use describe <uri> for one known capability."
        ),
    )
    capabilities.add_argument("--all-versions", action="store_true")
    capabilities.add_argument(
        "--profile",
        choices=(CONSOLE_EXECUTION_PROFILE, AUTHORING_UI_EXECUTION_PROFILE),
        default=CONSOLE_EXECUTION_PROFILE,
        help=(
            "Inspect the packaged WwiseConsole profile (default) or the "
            "Console-plus-five-URI Authoring UI supplement; this offline "
            "selection never overrides live host detection"
        ),
    )
    capabilities.add_argument("--category")
    capabilities.add_argument("--item-type", choices=("function", "topic"))
    capabilities.add_argument("--family")
    capabilities.add_argument("--route")
    capabilities.add_argument("--query", help="Case-insensitive URI substring filter")
    capabilities.add_argument(
        "--summary-only",
        action="store_true",
        help="Return aggregate counts without any capability rows",
    )
    capabilities.add_argument(
        "--detail",
        action="store_true",
        help="Expand returned rows with interface, schema-summary, policy, and evidence detail",
    )
    capabilities.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum returned rows; defaults to 50, while 0 explicitly returns every match",
    )

    describe = subparsers.add_parser(
        "describe",
        help="Describe one URI, its schema, stable route, safety gate, request template when reviewed, and evidence boundary offline",
    )
    describe.add_argument("api")
    describe.add_argument("--all-versions", action="store_true")
    describe.add_argument(
        "--profile",
        choices=(CONSOLE_EXECUTION_PROFILE, AUTHORING_UI_EXECUTION_PROFILE),
        default=CONSOLE_EXECUTION_PROFILE,
        help=(
            "Inspect the packaged WwiseConsole profile (default) or the "
            "Console-plus-five-URI Authoring UI supplement; this offline "
            "selection never overrides live host detection"
        ),
    )
    describe.add_argument(
        "--full-schema",
        action="store_true",
        help="Include the complete reflected schema; defaults to a compact schema summary",
    )

    operations = subparsers.add_parser(
        "operations",
        help="List compact transaction operations and explicit non-executable boundaries offline",
        description=(
            "Return the compact broad operation inventory. For one named operation, use "
            "operation-schema <name> directly."
        ),
    )
    operations.add_argument(
        "--detail",
        action="store_true",
        help="Expand inventory rows with nested request contracts, constraints, and identity rules",
    )
    operation_schema = subparsers.add_parser(
        "operation-schema",
        help="Describe one closed operation request shape, versioned CLI templates when applicable, and its execution boundary offline",
    )
    operation_schema.add_argument("operation")
    undo_child_schema = subparsers.add_parser(
        "undo-child-schema",
        help="Describe one approved exact-version typed Undo Group child offline",
    )
    undo_child_schema.add_argument("child_operation")
    query_schema = subparsers.add_parser(
        "query-schema",
        help=(
            "Describe the closed structured object-query contract offline; "
            "use it only when the simple query-object flags are insufficient"
        ),
    )
    query_schema.add_argument("--all-versions", action="store_true")
    query_schema.add_argument(
        "--advanced",
        action="store_true",
        help=(
            "Disclose the third-layer bounded native WAQL contract instead "
            "of the preferred structured object-query contract"
        ),
    )

    object_types = subparsers.add_parser(
        "object-types",
        help=(
            "Search the compact packaged Wwise object-type catalog without "
            "connecting to Wwise"
        ),
    )
    object_types.add_argument("--all-versions", action="store_true")
    object_types.add_argument(
        "--query",
        help="Case-insensitive name/category keywords; all keywords must match",
    )
    object_types.add_argument(
        "--object-type",
        help="Exact broad type/category filter, for example WObject or Conversion",
    )
    object_types.add_argument(
        "--limit",
        type=int,
        default=20,
        metavar=f"1..{MAX_OBJECT_TYPE_SEARCH_RESULTS}",
        help=(
            "Maximum rows returned per version; defaults to 20 and is capped "
            f"at {MAX_OBJECT_TYPE_SEARCH_RESULTS}"
        ),
    )
    object_types.add_argument(
        "--summary-only",
        action="store_true",
        help="Return only packaged catalog counts and digests",
    )

    subparsers.add_parser(
        "config-show",
        help="Show effective public config and its external/legacy source without connecting to Wwise",
    )
    config_set = subparsers.add_parser(
        "config-set",
        help="Atomically save public config outside the Skill checkout without connecting to Wwise",
    )
    config_set.add_argument(
        "--reset",
        action="store_true",
        help="Replace an unreadable or invalid external config with validated defaults before applying changes",
    )
    config_set.add_argument("--wwise-version")
    config_set.add_argument("--clear-wwise-version", action="store_true")
    config_set.add_argument("--waapi-host")
    config_set.add_argument("--waapi-port")
    config_set.add_argument("--clear-waapi-port", action="store_true")
    config_set.add_argument("--project-modification-policy")

    draft_start = subparsers.add_parser(
        "draft-start",
        help=(
            "Start one task-capability-bound Operation Draft without connecting "
            "to Wwise or creating a transaction Preview"
        ),
    )
    draft_start.add_argument("operation")

    draft_apply = subparsers.add_parser(
        "draft-apply",
        help="Apply one closed typed action to an authorized Operation Draft offline",
    )
    draft_apply.add_argument("draft_id")
    draft_apply.add_argument("--task-authority", required=True)
    draft_apply.add_argument("--expected-revision", required=True, type=int)
    draft_apply.add_argument(
        "--compact",
        action="store_true",
        help=(
            "Return only this action's result and a bounded composition summary; "
            "use draft-inspect for the complete current facts"
        ),
    )
    draft_apply.add_argument(
        "--facts",
        nargs=argparse.REMAINDER,
        help=(
            "Treat every remaining argv item as one typed action; this keeps "
            "option-looking strings as data"
        ),
    )

    draft_check = subparsers.add_parser(
        "draft-check",
        help=(
            "Live-validate one complete Operation Draft against bounded identity, "
            "metadata, project, and runtime evidence without creating a Preview"
        ),
    )
    draft_check.add_argument("draft_id")
    draft_check.add_argument("--task-authority", required=True)
    draft_check.add_argument("--expected-revision", required=True, type=int)
    draft_check.add_argument(
        "--detail",
        action="store_true",
        help="Include complete validation and dispatch evidence",
    )
    draft_check.add_argument("--post-filter-value")
    draft_check.add_argument("--post-filter-limit", type=int)

    preview_from_draft = subparsers.add_parser(
        "preview-from-draft",
        help=(
            "Seal one successfully checked Operation Draft through the canonical "
            "transaction Preview ingress"
        ),
    )
    preview_from_draft.add_argument("draft_id")
    preview_from_draft.add_argument("--task-authority", required=True)
    preview_from_draft.add_argument("--expected-revision", required=True, type=int)
    preview_from_draft.add_argument("--apply", action="store_true")
    preview_from_draft.add_argument(
        "--ttl",
        type=int,
        default=DEFAULT_PREVIEW_TTL_SECONDS,
    )

    draft_inspect = subparsers.add_parser(
        "draft-inspect",
        help="Inspect one authorized Operation Draft without connecting to Wwise",
    )
    draft_inspect.add_argument("draft_id")
    draft_inspect.add_argument("--task-authority", required=True)

    draft_cancel = subparsers.add_parser(
        "draft-cancel",
        help="Cancel one authorized editable Operation Draft without connecting to Wwise",
    )
    draft_cancel.add_argument("draft_id")
    draft_cancel.add_argument("--task-authority", required=True)
    draft_cancel.add_argument("--expected-revision", required=True, type=int)

    transaction_show = subparsers.add_parser(
        "transaction-show",
        help="Show one immutable preview, durable state, and hash-chained event journal offline",
    )
    transaction_show.add_argument("transaction_id")
    transaction_show.add_argument(
        "--summary-only",
        action="store_true",
        help="Return the request, prepared change summary, guard fingerprints, and event-chain summary without raw artifact internals",
    )

    confirm = subparsers.add_parser(
        "confirm",
        help="Bind explicit confirmation to one immutable preview without connecting to Wwise",
    )
    confirm.add_argument("transaction_id")
    confirm.add_argument("--confirmation-token", required=True)

    reject = subparsers.add_parser("reject", help="Reject one awaiting transaction without connecting to Wwise")
    reject.add_argument("transaction_id")
    reject.add_argument("--reason", default="rejected by user")

    execute = subparsers.add_parser(
        "execute",
        help=(
            "Execute exactly one explicitly confirmed or policy-authorized "
            "immutable transaction after guard and role revalidation"
        ),
    )
    execute.add_argument("transaction_id")

    verify = subparsers.add_parser(
        "verify",
        help="Verify one executed transaction with its operation-specific readback",
    )
    verify.add_argument("transaction_id")

    return parser


def add_typed_topic_input_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the one closed typed Topic input vocabulary to a subscription command."""

    parser.add_argument("--options-schema-digest")
    parser.add_argument("--match-schema-digest")
    for prefix in ("option", "match"):
        parser.add_argument(
            f"--{prefix}-set",
            action="append",
            nargs=3,
            metavar=("FIELD_HANDLE", "TYPE", "VALUE"),
            default=[],
        )
        parser.add_argument(
            f"--{prefix}-append",
            action="append",
            nargs=3,
            metavar=("FIELD_HANDLE", "TYPE", "VALUE"),
            default=[],
        )
        parser.add_argument(
            f"--{prefix}-present",
            action="append",
            metavar="CONTAINER_HANDLE",
            default=[],
        )
        parser.add_argument(
            f"--{prefix}-choose",
            action="append",
            nargs=2,
            metavar=("BRANCH_HANDLE", "CHOICE_HANDLE"),
            default=[],
        )
        parser.add_argument(
            f"--{prefix}-choose-dynamic",
            action="append",
            nargs=3,
            metavar=("OBJECT_HANDLE", "KEY", "CHOICE_HANDLE"),
            default=[],
        )
        parser.add_argument(
            f"--{prefix}-map-put",
            action="append",
            nargs=4,
            metavar=("MAP_HANDLE", "KEY", "TYPE", "VALUE"),
            default=[],
        )


def execute_gateway(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
    stream_sink: Callable[[Mapping[str, Any]], None] | None = None,
) -> tuple[int, dict[str, Any]]:
    exit_code, payload = _execute_gateway_unconstrained(
        argv,
        env=env,
        client_factory=client_factory,
        stream_sink=stream_sink,
    )
    if payload.get("command") in OFFLINE_COMMANDS:
        return exit_code, payload
    result_limit = (
        MAX_METADATA_DISCOVERY_GATEWAY_RESULT_BYTES
        if payload.get("command") == "metadata"
        and payload.get("operation") == "discover"
        and isinstance(payload.get("agent_result"), Mapping)
        and payload["agent_result"].get("result_detail") == "compact"
        else MAX_GATEWAY_RESULT_JSON_BYTES
    )
    return constrain_live_gateway_result(
        exit_code,
        payload,
        limit_bytes=result_limit,
    )


def _execute_gateway_unconstrained(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
    stream_sink: Callable[[Mapping[str, Any]], None] | None = None,
) -> tuple[int, dict[str, Any]]:
    args = build_parser().parse_args(argv)
    source_env = dict(os.environ if env is None else env)
    runtime_endpoint: dict[str, Any] | None = None
    runtime_detected_version: str | None = None

    def finish(exit_code: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        enriched = dict(payload)
        if args.command == "stream-topic":
            gateway_contract = enriched.get("contract")
            enriched["contract"] = TOPIC_STREAM_RECORD_CONTRACT
            enriched["record_type"] = "terminal"
            if (
                isinstance(gateway_contract, str)
                and gateway_contract != TOPIC_STREAM_RECORD_CONTRACT
            ):
                enriched["gateway_result_contract"] = gateway_contract
        if runtime_endpoint is not None and "endpoint" not in enriched:
            enriched["endpoint"] = dict(runtime_endpoint)
        if runtime_detected_version is not None and "detected_version" not in enriched:
            enriched["detected_version"] = runtime_detected_version
        if args.command == "draft-apply" and getattr(args, "compact", False):
            # The Draft start response has already supplied the bounded
            # conversation/session introduction. Repeating that complete
            # projection after every typed edit makes a long composition grow
            # the model transcript without adding action-local facts. Compact
            # edits therefore return only their durable delta and continuation.
            return exit_code, enriched
        return exit_code, attach_gateway_session_context(
            enriched,
            args=args,
            env=source_env,
        )

    cleanup_failure: BaseException | None = None
    post_result_cleanup_failed = False
    try:
        if args.command == "stream-topic" and stream_sink is None:
            raise GatewayInputError(
                "stream-topic requires a live record sink; use the gateway CLI "
                "entry point so every streamed record remains observable."
            )
        if args.command == "execute":
            require_transaction_preconnection_policy(args, env=source_env)
        elif args.command in {
            "preview-from-draft",
            "typed-zero-call",
            "typed-call",
            "typed-operation",
        } and args.apply:
            require_project_modification_policy(
                env=source_env,
                action="requested project change",
            )
        route_boundary = preflight_public_route(args, env=source_env)
        if route_boundary is not None:
            return finish(2, route_boundary)
        preflight_json_inputs(args)
        if args.command == "selected":
            args.return_fields = list(
                normalize_selected_return_fields(args.return_fields)
            )
        if args.command == "query-object":
            preflight_query_object_input(args, env=source_env)
        if args.command in {"wait-topic", "stream-topic"}:
            preflight_typed_topic_input(args, env=source_env)
        if args.command == "metadata":
            preflight_metadata_input(args)
        if args.command in {
            "profiler-game-objects",
            "profiler-voice-contributions",
        }:
            preflight_stable_read_input(args, env=source_env)
        if args.command == "typed-call":
            preflight_typed_request_input(args, env=source_env)
        if args.command == "typed-operation":
            preflight_typed_operation_input(args, env=source_env)
        if args.command == "typed-zero-call":
            preflight_typed_zero_input(args, env=source_env)
        if args.command == "debug-wal-tree":
            preflight_debug_read_input(args)
        if args.command in OFFLINE_COMMANDS:
            payload = dispatch_offline_command(args, env=source_env)
            return finish(0 if payload.get("ok") else 2, payload)
        connection = resolve_connection(args, env=source_env)
        runtime_endpoint = {
            "host": connection.host,
            "port": connection.port,
            "url": connection.url,
        }
        factory = client_factory or default_client_factory
        transport = GatewayTransport(connection.url, factory, deadline=connection.deadline)
        try:
            version_detection_timeout = connection.deadline.require_remaining(
                "version_detection.getInfo"
            )
            if math.isinf(version_detection_timeout):
                version_detection_timeout = DEFAULT_TIMEOUT
            live_info = transport.call_with_timeout(
                GET_INFO_URI,
                timeout=version_detection_timeout,
                phase="version_detection.getInfo",
            )
            detected_version = version_key_from_get_info(require_mapping(live_info, "getInfo response"))
            runtime_detected_version = detected_version
            if connection.version_hint and connection.version_hint != detected_version:
                raise GatewayInputError(
                    f"Connected Wwise is {detected_version}, but the requested version is {connection.version_hint}"
                )
            dispatcher = WwiseDispatcher(client=transport)
            if live_info.get("isCommandLine") is False:
                dispatcher.manifest_store = AuthoringUiRuntimeManifestStore(
                    dispatcher.manifest_store
                )
            payload = dispatch_command(
                args,
                env=source_env,
                connection=connection,
                detected_version=detected_version,
                live_info=require_mapping(live_info, "getInfo response"),
                dispatcher=dispatcher,
                stream_sink=stream_sink,
            )
            if payload.get("ok"):
                connection.deadline.require_remaining(f"finalize {args.command}")
        except KeyboardInterrupt:
            cancellation_cleanup: dict[str, Any]
            try:
                transport.close()
            except BaseException as cleanup_exc:  # noqa: BLE001 - cancellation must report cleanup truthfully
                cancellation_cleanup = {
                    "status": "cleanup_failed",
                    "failure": cleanup_failure_evidence(cleanup_exc),
                }
            else:
                cancellation_cleanup = {"status": "transport_closed"}
            cancelled_payload: dict[str, Any] = {
                "contract": GATEWAY_RESULT_CONTRACT,
                "ok": False,
                "status": "cancelled",
                "command": args.command,
                "error_code": "CANCELLED",
                "message": (
                    "Gateway command was cancelled; transport cleanup was attempted."
                ),
                "cleanup": cancellation_cleanup,
            }
            if args.command in {"wait-topic", "stream-topic"}:
                unbounded_timeout = math.isinf(connection.timeout)
                cancelled_payload.update(
                    {
                        "topic": args.api,
                        "subscription_timeout": {
                            "mode": (
                                "unbounded" if unbounded_timeout else "finite"
                            ),
                            "seconds": (
                                None if unbounded_timeout else connection.timeout
                            ),
                            "source": (
                                "default_continuous"
                                if args.command == "stream-topic"
                                and args.timeout is None
                                else "explicit_no_timeout"
                                if unbounded_timeout
                                else "explicit"
                                if args.timeout is not None
                                else "default"
                            ),
                        },
                    }
                )
            return finish(130, cancelled_payload)
        except Exception as primary_exc:
            try:
                transport.close()
                if isinstance(primary_exc, GatewayTimeoutError):
                    primary_exc.cleanup_pending = False
            except BaseException as cleanup_exc:  # noqa: BLE001 - cleanup never masks the primary error
                cleanup_failure = cleanup_exc
                if isinstance(primary_exc, GatewayTimeoutError):
                    primary_exc.mark_cleanup_pending(
                        abort_requested=isinstance(cleanup_exc, GatewayTimeoutError)
                        and cleanup_exc.abort_requested
                    )
            raise
        else:
            try:
                transport.close()
            except BaseException as cleanup_exc:  # noqa: BLE001 - preserve completed business facts
                payload = attach_cleanup_failure(payload, cleanup_exc)
                post_result_cleanup_failed = True
            else:
                _finalize_timeout_cleanup(payload)
                _finalize_subscription_cleanup_after_close(payload)
        if (
            args.command == "verify"
            and not post_result_cleanup_failed
            and payload.get("ok") is True
            and payload.get("status") in (
                TransactionState.VERIFIED.value,
                TransactionState.RESULT_SCHEMA_CHECKED.value,
            )
            and transaction_verify_cleanup_projection_safe(payload.get("cleanup"))
        ):
            payload = project_successful_transaction_verify_payload(payload)
        if (
            args.command == "query-object"
            and not original_file_reference_match_requested(args)
            and not post_result_cleanup_failed
        ):
            payload = project_successful_query_object_payload(
                payload,
                detail=args.detail,
            )
        if (
            args.command == "draft-check"
            and payload.get("query_layer") == "structured-builder"
            and not post_result_cleanup_failed
        ):
            payload = project_successful_query_object_payload(
                payload,
                detail=args.detail,
            )
    except Exception as exc:  # noqa: BLE001 - the CLI always returns structured failure JSON
        normalized = normalize_gateway_exception(exc)
        details = normalized.get("details")
        if cleanup_failure is not None:
            merged_details = dict(details) if isinstance(details, Mapping) else {}
            merged_details["cleanup_failure"] = cleanup_failure_evidence(cleanup_failure)
            details = merged_details
        error_payload: dict[str, Any] = {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": False,
            "status": "error",
            "command": getattr(args, "command", None),
            "error_code": normalized["error_code"],
            "message": normalized["message"],
            "details": details,
        }
        if getattr(args, "command", None) == "transaction-show" and isinstance(
            details, Mapping
        ):
            for key, maximum in (
                ("transaction_id", 128),
                ("state", 80),
                ("artifact_hash", 128),
            ):
                value = bounded_gateway_label(details.get(key), maximum)
                if value is not None:
                    error_payload[key] = value
        return finish(2, error_payload)
    # ``ok`` describes the completed WAAPI/business operation. A non-zero exit
    # with ``ok: true`` means only post-result cleanup failed; callers must keep
    # mutation execution facts and must not infer that retrying is safe.
    exit_code = 2 if post_result_cleanup_failed else (0 if payload.get("ok") else 2)
    return finish(exit_code, payload)


def constrain_live_gateway_result(
    exit_code: int,
    payload: dict[str, Any],
    *,
    limit_bytes: int = MAX_GATEWAY_RESULT_JSON_BYTES,
) -> tuple[int, dict[str, Any]]:
    """Bound the complete live gateway document, including its outer envelope."""

    probe = probe_gateway_json_document_size(payload, limit_bytes)
    if probe == "ok":
        return exit_code, payload
    error_code = "RESULT_TOO_LARGE" if probe == "too_large" else "RESULT_NOT_JSON"
    reason = (
        "The final live gateway result exceeded the public JSON size limit"
        if probe == "too_large"
        else "The final live gateway result is not a strict JSON document"
    )
    details: dict[str, Any] = {
        "provenance": GATEWAY_RESULT_CEILING_PROVENANCE,
        "original_ok": payload.get("ok") is True,
        "original_status": bounded_gateway_label(payload.get("status"), 80),
    }
    if probe == "too_large":
        details.update(
            {
                "limit_bytes": limit_bytes,
                "observed_at_least_bytes": limit_bytes + 1,
            }
        )
    result: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "error",
        "command": bounded_gateway_label(payload.get("command"), 80),
        "error_code": error_code,
        "message": reason,
        "details": details,
    }
    session_context = payload.get("session_context")
    if isinstance(session_context, Mapping):
        result["session_context"] = dict(session_context)
    for key, maximum in (
        ("detected_version", 32),
        ("transaction_id", 128),
        ("state", 80),
        ("artifact_hash", 128),
    ):
        value = bounded_gateway_label(payload.get(key), maximum)
        if value is not None:
            result[key] = value
    for key in ("executed", "verified", "automatic_retry"):
        if isinstance(payload.get(key), bool):
            result[key] = payload[key]
    return 2, result


def probe_gateway_json_document_size(value: Any, limit_bytes: int) -> str:
    """Return ok/too_large/not_json for the exact terminal stdout document."""

    try:
        observed = gateway_json_document_size(value, stop_after_bytes=limit_bytes)
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        return "not_json"
    return "too_large" if observed > limit_bytes else "ok"


def gateway_json_document_size(
    value: Any,
    *,
    stop_after_bytes: int | None = None,
) -> int:
    """Return the exact UTF-8 byte size printed by :func:`main`.

    The optional early ceiling keeps hostile or malformed nested values from
    forcing an unbounded sizing pass.  Returning ``ceiling + 1`` is sufficient
    for every caller that supplied a ceiling.
    """

    encoder = gateway_stdout_json_encoder(value)
    observed = 0
    for chunk in encoder.iterencode(value):
        observed += len(chunk.encode("utf-8"))
        if stop_after_bytes is not None and observed > stop_after_bytes:
            return stop_after_bytes + 1
    return observed + 1  # print() appends one newline


def gateway_stdout_json_encoder(value: Any | None = None) -> json.JSONEncoder:
    """Build the strict, insertion-ordered encoder used for gateway stdout.

    Schema-discovery payloads use compact JSON to reduce output size. Other
    gateway documents retain the existing pretty representation.
    """

    options: dict[str, Any] = {
        "ensure_ascii": False,
        "sort_keys": False,
        "allow_nan": False,
        "check_circular": True,
    }
    if (
        isinstance(value, Mapping)
        and value.get("command")
        in {
            "operation-schema",
            "query-schema",
            "topic-schema",
            "request-map-container",
            "request-array-item",
        }
    ):
        options["separators"] = (",", ":")
    else:
        options["indent"] = 2
    return json.JSONEncoder(**options)


def bounded_gateway_label(value: Any, maximum_bytes: int) -> str | None:
    if not isinstance(value, str) or len(value) > maximum_bytes:
        return None
    try:
        return value if len(value.encode("utf-8")) <= maximum_bytes else None
    except UnicodeEncodeError:
        return None


def cleanup_failure_evidence(exc: BaseException) -> dict[str, Any]:
    """Attach cleanup failure evidence without replacing the primary failure."""

    normalized = normalize_gateway_exception(exc)
    evidence: dict[str, Any] = {
        "error_code": normalized["error_code"],
        "message": normalized["message"],
    }
    details = normalized.get("details")
    if isinstance(details, dict):
        evidence["details"] = details
    return evidence


def normalize_gateway_exception(exc: BaseException) -> dict[str, Any]:
    """Normalize one gateway exception without trusting its string or metadata hooks."""

    if isinstance(exc, SemanticValidationError):
        error_code = safe_type_name(exc, "Exception")
    elif isinstance(exc, TimeoutError):
        error_code = "TIMEOUT"
    else:
        has_error_code, candidate = safe_exception_attribute(exc, "error_code")
        error_code = (
            candidate
            if has_error_code and isinstance(candidate, str) and candidate
            else None
        )
        if error_code is None:
            error_code = safe_type_name(exc, "Exception")
    try:
        return normalize_dispatcher_exception(exc, error_code=error_code)
    except BaseException:  # noqa: BLE001 - the public CLI must fail closed on hostile exceptions
        return {
            "error_code": "ERROR_NORMALIZATION_FAILED",
            "message": "The underlying error could not be normalized safely",
        }


def attach_cleanup_failure(payload: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    """Preserve one completed business result and append bounded close evidence."""

    result = dict(payload)
    current_details = result.get("details")
    details = current_details.copy() if type(current_details) is dict else {}
    details["cleanup_failure"] = cleanup_failure_evidence(exc)
    result["details"] = details
    return result


def _finalize_timeout_cleanup(value: Any) -> None:
    """Mark copied timeout evidence complete after transport.close succeeds."""

    if isinstance(value, dict):
        details = value.get("details")
        if (
            value.get("error_code") == "TIMEOUT"
            and isinstance(details, dict)
            and details.get("provenance") == GATEWAY_DEADLINE_PROVENANCE
        ):
            details["cleanup_pending"] = False
        for item in value.values():
            _finalize_timeout_cleanup(item)
    elif isinstance(value, list):
        for item in value:
            _finalize_timeout_cleanup(item)


def _finalize_subscription_cleanup_after_close(value: Any) -> None:
    """Record that transport close explicitly cleaned a previously retained token."""

    if isinstance(value, dict):
        if value.get("cleanup") == SUBSCRIPTION_CLEANUP_FAILED:
            value["cleanup"] = SUBSCRIPTION_CLEANUP_AFTER_RETRY
        details = value.get("details")
        cleanup = (
            details.get(SUBSCRIPTION_CLEANUP_DETAILS_KEY)
            if isinstance(details, dict)
            else None
        )
        if (
            isinstance(cleanup, dict)
            and cleanup.get("status") == SUBSCRIPTION_CLEANUP_FAILED
        ):
            cleanup["status"] = SUBSCRIPTION_CLEANUP_AFTER_RETRY
        for item in value.values():
            _finalize_subscription_cleanup_after_close(item)
    elif isinstance(value, list):
        for item in value:
            _finalize_subscription_cleanup_after_close(item)


def query_object_required_payload(*, common: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "query_object_required",
        "command": "call",
        "api": OBJECT_GET_URI,
        "error_code": "QUERY_OBJECT_REQUIRED",
        "message": (
            "The public generic call path does not accept ak.wwise.core.object.get. "
            "Use query-object so simple flags, the structured Builder, or the "
            "bounded advanced WAQL contract retain Gateway-owned result limits."
        ),
        "required_command": "query-object",
        "executed": False,
    }
    if common is not None:
        payload.update(dict(common))
    return payload


def fixed_command_required_payload(
    api: str,
    commands: Sequence[str],
    *,
    common: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep reviewed fixed-function URIs inside their packaged command contracts."""

    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "fixed_command_required",
        "command": "call",
        "api": api,
        "error_code": "FIXED_COMMAND_REQUIRED",
        "message": (
            f"The public generic call path does not accept {api}. "
            f"Use its packaged fixed command: {', '.join(commands)}."
        ),
        "required_commands": list(commands),
        "executed": False,
    }
    if len(commands) == 1:
        payload["required_command"] = commands[0]
    if common is not None:
        payload.update(dict(common))
    return payload


def wait_topic_required_payload(api: str, *, common: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Keep reviewed topic observation inside the bounded wait contract."""

    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "wait_topic_required",
        "command": "call",
        "api": api,
        "error_code": "WAIT_TOPIC_REQUIRED",
        "message": (
            f"The public generic call path does not accept topic {api}. "
            "Use wait-topic so the observation is deadline-bounded and always unsubscribed."
        ),
        "required_command": "wait-topic",
        "executed": False,
    }
    if common is not None:
        payload.update(dict(common))
    return payload


def unsupported_interface_payload(
    api: str,
    reason: str,
    *,
    command: str,
    common: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject one catalog safety boundary before business dispatch or subscription."""

    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "unsupported_by_skill_interface",
        "command": command,
        "api": api,
        "error_code": "UNSUPPORTED_BY_SKILL_INTERFACE",
        "message": reason,
        "executed": False,
    }
    if common is not None:
        payload.update(dict(common))
    return payload


def unreflected_interface_payload(
    api: str,
    version: str,
    *,
    command: str,
    common: Mapping[str, Any] | None = None,
    safety_context: str | None = None,
) -> dict[str, Any]:
    """Return the public unsupported boundary for a URI absent from one manifest."""

    message = (
        f"WAAPI URI {api!r} is not reflected by Wwise {version} and has no "
        "packaged executable route in the Skill interface."
    )
    if safety_context:
        message += f" The immutable Skill safety policy also blocks this URI: {safety_context}"
    return unsupported_interface_payload(
        api,
        message,
        command=command,
        common=common,
    )


def transaction_required_payload(
    api: str,
    *,
    capability: CapabilityRecord | None = None,
    common: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep a closed mutation URI out of generic call, including dry-run."""

    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "transaction_required",
        "command": "call",
        "api": api,
        "error_code": "TRANSACTION_REQUIRED",
        "message": (
            "This URI is available only through the packaged preview, authorization, execution, "
            "and verification transaction interface; generic call and --dry-run cannot bypass it."
        ),
        "executed": False,
        "verified": False,
    }
    if capability is not None:
        payload["capability"] = capability.as_dict(detail=False)
    if common is not None:
        payload.update(dict(common))
    return payload


def catalog_route_boundary_payload(
    capability: CapabilityRecord,
    *,
    command: str,
    common: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Translate the catalog's one public route into a gateway boundary payload."""

    if command in {"wait-topic", "stream-topic"}:
        if capability.item_type != "topic":
            raise GatewayInputError(
                f"{command} requires a reflected topic URI, got {capability.item_type}: {capability.uri}"
            )
        if capability.safety.interface_status == "unsupported_by_skill_interface":
            return unsupported_interface_payload(
                capability.uri,
                capability.safety.reason,
                command=command,
                common=common,
            )
        if capability.preferred_route != "bounded_topic_wait":
            return unsupported_interface_payload(
                capability.uri,
                "This topic has no reviewed subscription route in the packaged Skill interface.",
                command=command,
                common=common,
            )
        return None

    if command != "call":
        return None
    if capability.item_type == "topic":
        if capability.safety.interface_status == "unsupported_by_skill_interface":
            return unsupported_interface_payload(
                capability.uri,
                capability.safety.reason,
                command="call",
                common=common,
            )
        return wait_topic_required_payload(capability.uri, common=common)
    if capability.safety.interface_status == "unsupported_by_skill_interface":
        return unsupported_interface_payload(
            capability.uri,
            capability.safety.reason,
            command="call",
            common=common,
        )
    if capability.preferred_route == "fixed_command":
        if capability.uri == OBJECT_GET_URI:
            return query_object_required_payload(common=common)
        return fixed_command_required_payload(
            capability.uri,
            capability.fixed_commands,
            common=common,
        )
    if capability.preferred_route == "transaction_operation":
        return transaction_required_payload(
            capability.uri,
            capability=capability,
            common=common,
        )
    if capability.preferred_route == "manifest_dispatch":
        return None
    return unsupported_interface_payload(
        capability.uri,
        "The catalog does not expose a public generic-call route for this URI.",
        command="call",
        common=common,
    )


def live_capability(
    version: str,
    api: str,
    *,
    live_info: Mapping[str, Any],
) -> CapabilityRecord:
    """Resolve a capability from the host profile proven by live getInfo."""

    catalog = CapabilityCatalog()
    if live_info.get("isCommandLine") is False:
        return catalog.authoring_ui_describe(version, api)
    return catalog.describe(version, api)


def authoring_host_required_payload(
    *,
    api: str | None,
    command: str,
    live_info: Mapping[str, Any],
    common: Mapping[str, Any] | None = None,
    operation: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "authoring_host_required",
        "command": command,
        "error_code": "AUTHORING_HOST_REQUIRED",
        "message": (
            "This Wwise UI-command capability requires Wwise Authoring; "
            "WwiseConsole cannot expose or execute it."
        ),
        "details": {
            "is_command_line": live_info.get("isCommandLine"),
            "required_host": "wwise-authoring",
        },
        "executed": False,
        "verified": False,
    }
    if api is not None:
        payload["api"] = api
    if operation is not None:
        payload["operation"] = operation
    if common is not None:
        payload.update(dict(common))
    return payload


def authoring_host_platform(live_info: Mapping[str, Any]) -> str:
    """Map only the official live getInfo platform values used by Authoring."""

    platform = live_info.get("platform")
    if not isinstance(platform, str):
        raise OperationContractError(
            "HOST_PLATFORM_UNAVAILABLE",
            "Wwise Authoring getInfo did not return a usable platform.",
            details={"platform": platform, "supported": ["x64", "win32", "macosx"]},
        )
    mapped = {
        "x64": "windows",
        "win32": "windows",
        "macosx": "macos",
    }.get(platform.strip().casefold())
    if mapped is None:
        raise OperationContractError(
            "HOST_PLATFORM_UNAVAILABLE",
            "Wwise Authoring reported a platform that the closed command-registration adapter does not support.",
            details={
                "platform": platform,
                "supported": ["x64", "win32", "macosx"],
            },
        )
    return mapped


def live_authoring_api_boundary(
    api: str,
    *,
    command: str,
    live_info: Mapping[str, Any],
    common: Mapping[str, Any],
) -> dict[str, Any] | None:
    if api not in AUTHORING_UI_COMMAND_URIS:
        return None
    if live_info.get("isCommandLine") is False:
        return None
    return authoring_host_required_payload(
        api=api,
        command=command,
        live_info=live_info,
        common=common,
    )


def live_authoring_transaction_boundary(
    request_payload: Mapping[str, Any],
    *,
    command: str,
    live_info: Mapping[str, Any],
    common: Mapping[str, Any],
) -> dict[str, Any] | None:
    operation = request_payload.get("operation")
    if operation not in {*UI_COMMAND_OPERATIONS, "ui.captureScreen"}:
        return None
    if live_info.get("isCommandLine") is not False:
        return authoring_host_required_payload(
            api=None,
            command=command,
            live_info=live_info,
            common=common,
            operation=str(operation),
        )
    arguments = request_payload.get("arguments")
    owned_unregister = (
        operation == "ui.commands.unregister"
        and isinstance(arguments, Mapping)
        and "commands" in arguments
    )
    if operation == "ui.commands.register" or owned_unregister:
        # Fail before project reads or preview creation when the live platform
        # cannot be represented by the closed register adapter.
        authoring_host_platform(live_info)
    return None


def local_filesystem_host_required_payload(
    *,
    command: str,
    endpoint_host: str,
    operation: str,
    path_roles: Sequence[str],
    common: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "local_waapi_host_required",
        "command": command,
        "operation": operation,
        "error_code": "LOCAL_WAAPI_HOST_REQUIRED",
        "message": (
            "This transaction binds filesystem state proved on the gateway "
            "machine or uses the fail-closed isolated transaction route, so "
            "its WAAPI endpoint must be an explicit loopback host."
        ),
        "details": {
            "boundary_basis": (
                "gateway_local_filesystem_or_isolated_transaction"
            ),
            "endpoint_host": endpoint_host,
            "path_roles": list(path_roles),
            "required_endpoint_scope": "loopback",
            "local_proof_is_remote_host_proof": False,
        },
        "executed": False,
        "verified": False,
        **dict(common),
    }


def local_filesystem_transaction_boundary(
    request_payload: Mapping[str, Any],
    *,
    command: str,
    endpoint_host: str,
    common: Mapping[str, Any],
) -> dict[str, Any] | None:
    operation = request_payload.get("operation")
    if not isinstance(operation, str):
        return None
    path_roles = local_filesystem_path_roles(request_payload)
    if not path_roles or is_loopback_waapi_host(endpoint_host):
        return None
    return local_filesystem_host_required_payload(
        command=command,
        endpoint_host=endpoint_host,
        operation=operation,
        path_roles=path_roles,
        common=common,
    )


def preflight_public_route(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> dict[str, Any] | None:
    """Fail closed before connecting when the requested public route is already known."""

    if args.command not in {"wait-topic", "stream-topic"}:
        return None
    api = args.api

    # When a version is already known, the versioned packaged manifest is the
    # first authority. Cross-version safety/route allowlists intentionally
    # contain APIs that do not exist in every release; consulting them first
    # could otherwise recommend a fixed command or topic wait for an API that
    # this exact Wwise version does not reflect.
    config = load_gateway_config(env).config
    version = args.version or env.get(ENV_VERSION) or config.wwise_version
    if version is not None:
        if version not in SUPPORTED_WWISE_VERSION_KEYS:
            raise GatewayInputError(
                f"Unsupported Wwise version {version!r}; supported versions: "
                f"{', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
            )
        try:
            catalog = CapabilityCatalog()
            capability = (
                catalog.authoring_ui_describe(str(version), api)
                if api in AUTHORING_UI_COMMAND_URIS
                else catalog.describe(str(version), api)
            )
        except CapabilityNotFoundError:
            safety_context = EXPLICIT_UNSUPPORTED_TOPIC_URIS.get(api)
            return unreflected_interface_payload(
                api,
                str(version),
                command=args.command,
                safety_context=safety_context,
            )
        return catalog_route_boundary_payload(capability, command=args.command)

    # With no configured version, retain the static bootstrap boundaries that
    # can reject or redirect a request without opening WAAPI. If no such
    # boundary applies, live getInfo detection selects the manifest later.
    if api in AUTHORING_UI_COMMAND_URIS:
        capability = CapabilityCatalog().authoring_ui_describe("2022.1", api)
        return catalog_route_boundary_payload(
            capability,
            command=args.command,
        )
    explicit_topic_boundary = EXPLICIT_UNSUPPORTED_TOPIC_URIS.get(api)
    if explicit_topic_boundary is not None:
        return unsupported_interface_payload(
            api,
            explicit_topic_boundary,
            command=args.command,
        )
    return None


def preflight_typed_request_input(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> None:
    """Bind all typed facts to one exact packaged schema before connecting."""

    versions = resolve_catalog_versions(args, env=env)
    if len(versions) != 1:
        raise GatewayInputError("typed-call requires one exact Wwise version")
    contract = request_contract(versions[0], args.api)
    if (
        contract.as_gateway_payload()["input_shape"] == "draft"
        and contract.uri != TYPED_REQUEST_COMPLEX_TRACER_URI
    ):
        raise GatewayInputError(
            "This complex typed request must use its single draft-start entry."
        )
    facts = [
        TypedRequestFact("set", handle, value_type, value)
        for handle, value_type, value in args.typed_set_facts
    ]
    facts.extend(
        TypedRequestFact("append", handle, value_type, value)
        for handle, value_type, value in args.typed_append_facts
    )
    facts.extend(
        TypedRequestFact("present", handle, "null", "null")
        for handle in args.typed_present_facts
    )
    facts.extend(
        TypedRequestFact("choose", handle, "branch", choice)
        for handle, choice in args.typed_branch_facts
    )
    facts.extend(
        TypedRequestFact("choose-dynamic", handle, "choice", choice, key=key)
        for handle, key, choice in args.typed_dynamic_branch_facts
    )
    for action_name in ("map_put", "map_correct"):
        facts.extend(
            TypedRequestFact(
                action_name.replace("_", "-"),
                handle,
                value_type,
                value,
                key=key,
            )
            for handle, key, value_type, value in getattr(
                args, f"typed_{action_name}_facts"
            )
        )
    facts.extend(
        TypedRequestFact("map-remove", handle, "null", "null", key=key)
        for handle, key in args.typed_map_remove_facts
    )
    args.typed_request = materialize_typed_request(
        contract,
        schema_digest=args.schema_digest,
        facts=facts,
    )
    capability = CapabilityCatalog().describe(versions[0], args.api)
    isolated = capability.execution_contract["route"] == "isolated_transaction"
    if isolated and not isinstance(args.io_root, str):
        raise GatewayInputError(
            "isolated typed-call requires --io-root for caller-owned file authority"
        )
    if not isolated and args.io_root is not None:
        raise GatewayInputError(
            "typed-call --io-root is accepted only for isolated routes"
        )
    args.typed_io_root = args.io_root if isolated else None
    requires_preview = capability.execution_contract["effect"] != "read"
    if not requires_preview and args.apply:
        raise GatewayInputError("typed-call --apply is reserved for changes")
    if requires_preview and not args.apply:
        raise GatewayInputError(
            "typed-call requires --apply to enter the Preview lifecycle for this API"
        )
    args.typed_requires_preview = requires_preview
    args.typed_read_timeout = (
        float(capability.execution_contract["timeout_seconds"])
        if not requires_preview
        else None
    )
    if args.typed_request.uri == TYPED_REQUEST_TRACER_URI:
        args.typed_stable_request = build_profiler_voice_contributions_request(
            version=args.typed_request.version,
            time=args.typed_request.args["time"],
            voice_pipeline_id=args.typed_request.args["voicePipelineID"],
            bus_pipeline_ids=tuple(
                args.typed_request.args.get("bussesPipelineID", ())
            ),
        )
    elif args.typed_request.uri == TYPED_REQUEST_COMPLEX_TRACER_URI:
        target_uri = args.typed_request.args.get("id")
        if not isinstance(target_uri, str) or not target_uri.startswith("ak."):
            raise GatewayInputError("typed debug validation requires an exact target API id")
        try:
            target = CapabilityCatalog().describe(versions[0], target_uri)
        except CapabilityNotFoundError as exc:
            raise GatewayInputError(str(exc)) from exc
        if target.item_type != "function":
            raise GatewayInputError("typed debug validation accepts only a function URI")


def preflight_typed_operation_input(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> None:
    """Materialize one exact dedicated operation before opening WAAPI."""

    versions = resolve_catalog_versions(args, env=env)
    if len(versions) != 1:
        raise GatewayInputError("typed-operation requires one configured Wwise version")
    version = versions[0]
    if operation_input_mode(args.operation, version) != INLINE_TYPED_INPUT_MODE:
        raise GatewayInputError(
            "This operation is not available through the concise typed-operation entry"
        )
    if operation_request_schema_digest(args.operation, version) != args.schema_digest:
        raise GatewayInputError("Typed operation schema digest is stale")
    values: dict[str, object] = {}
    if args.typed_object is not None:
        values["object"] = tuple(args.typed_object)
    if args.switch_container is not None:
        values["switch_container"] = tuple(args.switch_container)
    if args.child is not None:
        values["child"] = tuple(args.child)
    if args.state_or_switch is not None:
        values["state_or_switch"] = tuple(args.state_or_switch)
    for field in ("text", "property", "reference", "platform", "linked"):
        value = getattr(args, field)
        if value is not None:
            values[field] = value
    if args.enable is not None:
        values["enable"] = args.enable
    if args.parent is not None:
        values["parent"] = tuple(args.parent)
    if args.on_name_conflict is not None:
        values["on_name_conflict"] = args.on_name_conflict
    if args.auto_check_out is not None:
        values["auto_check_out_to_source_control"] = args.auto_check_out
    if args.auto_add is not None:
        values["auto_add_to_source_control"] = args.auto_add
    if args.import_file is not None:
        values["import_file"] = args.import_file
    if args.import_location is not None:
        values["import_location"] = tuple(args.import_location)
    if args.import_language is not None:
        values["import_language"] = args.import_language
    if args.import_operation is not None:
        values["import_operation"] = args.import_operation
    if args.files is not None:
        values["files"] = tuple(args.files)
    if args.io_root is not None:
        values["io_root"] = args.io_root
    if args.view_name is not None:
        values["view_name"] = args.view_name
    if args.view_channel is not None:
        values["view_channel"] = args.view_channel
    if args.rect is not None:
        values["rect"] = tuple(args.rect)
    if args.typed_ui_command is not None:
        values["command"] = args.typed_ui_command
    if args.command_objects is not None:
        values["objects"] = tuple(args.command_objects)
    if args.command_platforms is not None:
        values["platforms"] = tuple(args.command_platforms)
    if args.value is not None:
        values["value_type"], values["value"] = args.value
    if args.target is not None:
        values["target"] = tuple(args.target)
    if args.clear:
        values["clear"] = True
    try:
        args.typed_operation_request = materialize_inline_operation_request(
            args.operation,
            version,
            values,
        )
    except TypedOperationInputError as exc:
        raise GatewayInputError(str(exc)) from exc


def preflight_typed_zero_input(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> None:
    """Bind a zero-input read to its exact generated schema before connecting."""

    versions = resolve_catalog_versions(args, env=env)
    if len(versions) != 1:
        raise GatewayInputError("typed-zero-call requires one configured Wwise version")
    contract = request_contract(versions[0], args.api)
    dedicated_zero = {
        "ak.wwise.debug.restartWaapiServers": "debug.restartWaapiServers",
        "ak.wwise.debug.testAssert": "debug.testAssert",
        "ak.wwise.debug.testCrash": "debug.testCrash",
    }.get(args.api)
    if dedicated_zero is not None:
        raise GatewayInputError(
            "This dangerous host control uses operation-schema "
            f"{dedicated_zero} and typed-operation as its single entry."
        )
    if contract.schema_digest != args.schema_digest:
        raise GatewayInputError("Typed request schema digest is stale")
    if contract.fields:
        raise GatewayInputError("typed-zero-call is available only for zero-input schemas")
    execution = {
        "effect": contract.effect,
        "route": contract.route,
    }
    if contract.route == "fixed_command" and contract.uri != "ak.wwise.core.getInfo":
        raise GatewayInputError(
            "This zero-input API retains its packaged fixed command: "
            + ", ".join(contract.gateway_commands)
        )
    requires_preview = execution.get("effect") != "read"
    if not requires_preview and execution.get("effect") == "read" and args.apply:
        raise GatewayInputError("typed-zero-call --apply is reserved for changes")
    if execution.get("effect") != "read" and not args.apply:
        raise GatewayInputError(
            "typed-zero-call requires --apply to enter the Preview lifecycle for this API"
        )
    args.typed_zero_requires_preview = requires_preview
    args.typed_zero_read_timeout = (
        float(contract.timeout_seconds)
        if not requires_preview
        else None
    )
    args.typed_request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(),
    )


def preflight_query_object_input(args: argparse.Namespace, *, env: Mapping[str, str]) -> None:
    """Reject closed query input errors before opening a WAAPI transport."""

    if getattr(args, "typed_structured", False):
        _require_typed_structured_query_option_exclusivity(args)
        (preflight_version,) = resolve_catalog_versions(args, env=env)
        contract = typed_query_contract(preflight_version)
        if not isinstance(args.typed_schema_digest, str):
            raise GatewayInputError(
                "typed structured query requires --typed-schema-digest"
            )
        facts = [
            TypedRequestFact("set", handle, value_type, value)
            for handle, value_type, value in args.typed_set
        ]
        facts.extend(
            TypedRequestFact("append", handle, value_type, value)
            for handle, value_type, value in args.typed_append
        )
        facts.extend(
            TypedRequestFact("present", handle, "null", "null")
            for handle in args.typed_present
        )
        facts.extend(
            TypedRequestFact("choose", handle, "branch", choice)
            for handle, choice in args.typed_choose
        )
        facts.extend(
            TypedRequestFact("choose-dynamic", handle, "choice", choice, key=key)
            for handle, key, choice in args.typed_choose_dynamic
        )
        for action_name in ("map_put", "map_correct"):
            facts.extend(
                TypedRequestFact(
                    action_name.replace("_", "-"),
                    handle,
                    value_type,
                    value,
                    key=key,
                )
                for handle, key, value_type, value in getattr(
                    args, f"typed_query_{action_name}"
                )
            )
        facts.extend(
            TypedRequestFact("map-remove", handle, "null", "null", key=key)
            for handle, key in args.typed_query_map_remove
        )
        args.typed_query = materialize_typed_query(
            STRUCTURED_TYPED_QUERY_OPERATION,
            preflight_version,
            args.typed_schema_digest,
            tuple(facts),
        )
        _require_structured_exact_identity_return_field(args.typed_query.preview)
        args.typed_query_read_timeout = DEFAULT_TIMEOUT
        return
    if getattr(args, "typed_advanced", False):
        _require_typed_advanced_query_option_exclusivity(args)
        (preflight_version,) = resolve_catalog_versions(args, env=env)
        contract = typed_query_contract(preflight_version, advanced=True)
        fields = {field.name: field for field in contract.fields}
        if not isinstance(args.schema_digest, str):
            raise GatewayInputError("typed advanced query requires --schema-digest")
        if not isinstance(args.waql, str):
            raise GatewayInputError("typed advanced query requires --waql")
        if not args.advanced_return:
            raise GatewayInputError("typed advanced query requires --advanced-return")
        if args.max_results is None:
            raise GatewayInputError("typed advanced query requires --max-results")
        args.typed_query = materialize_typed_query(
            ADVANCED_TYPED_QUERY_OPERATION,
            preflight_version,
            args.schema_digest,
            (
                TypedRequestFact("set", fields["waql"].handle, "string", args.waql),
                *(
                    TypedRequestFact("append", fields["return"].handle, "string", value)
                    for value in args.advanced_return
                ),
                TypedRequestFact(
                    "set", fields["max_results"].handle, "integer", str(args.max_results)
                ),
            ),
        )
        args.typed_query_read_timeout = DEFAULT_TIMEOUT
        return
    if any(
        (
            args.schema_digest is not None,
            args.waql is not None,
            bool(args.advanced_return),
            args.max_results is not None,
        )
    ):
        raise GatewayInputError(
            "--schema-digest, --waql, --advanced-return, and --max-results "
            "require query-object --typed-advanced"
        )
    if any(
        (
            args.typed_schema_digest is not None,
            bool(args.typed_set),
            bool(args.typed_append),
            bool(args.typed_present),
            bool(args.typed_choose),
            bool(args.typed_choose_dynamic),
            bool(args.typed_query_map_put),
            bool(args.typed_query_map_correct),
            bool(args.typed_query_map_remove),
        )
    ):
        raise GatewayInputError(
            "structured typed fact flags require query-object --typed-structured"
        )
    if original_file_reference_match_requested(args):
        (preflight_version,) = resolve_catalog_versions(args, env=env)
        validate_original_file_reference_match_input(
            args,
            version=preflight_version,
        )
        build_object_get_query(
            type=ORIGINAL_FILE_REFERENCE_MATCH_TYPE,
            take=MAX_QUERY_TAKE,
            return_fields=ORIGINAL_FILE_REFERENCE_RETURN_FIELDS,
            version=preflight_version,
        )
        return

    if not any(
        (
            args.path is not None,
            args.object_id is not None,
            args.object_type is not None,
            args.search is not None,
            args.query is not None,
        )
    ):
        raise GatewayInputError(
            "query-object requires one simple source or one typed/structured query layer"
        )

    where = typed_query_predicates(args)
    return_fields = tuple(args.return_fields or ("id", "name", "type", "path"))
    _require_exact_identity_return_field(args, return_fields)
    (preflight_version,) = resolve_catalog_versions(args, env=env)
    build_object_get_query(
        path=args.path,
        object_id=args.object_id,
        type=args.object_type,
        search=args.search,
        query=args.query,
        where=where,
        select=tuple(args.select or ()),
        take=args.take,
        return_fields=return_fields,
        version=preflight_version,
    )
    _require_explicit_query_bound(args)


def original_file_reference_match_requested(args: argparse.Namespace) -> bool:
    """Return whether the caller selected the closed candidate-match mode."""

    return bool(getattr(args, "match_original_file_paths", None))


def validate_original_file_reference_match_input(
    args: argparse.Namespace,
    *,
    version: str,
) -> None:
    """Bind candidate matching to one reviewed, complete object.get request."""

    if version != ORIGINAL_FILE_REFERENCE_MATCH_VERSION:
        raise GatewayInputError(
            "--match-original-file-path is currently supported only for Wwise "
            f"{ORIGINAL_FILE_REFERENCE_MATCH_VERSION}"
        )
    if args.object_type != ORIGINAL_FILE_REFERENCE_MATCH_TYPE:
        raise GatewayInputError(
            "--match-original-file-path requires exactly "
            f"--type {ORIGINAL_FILE_REFERENCE_MATCH_TYPE}"
        )
    if args.where:
        raise GatewayInputError(
            "--match-original-file-path cannot be combined with --where"
        )
    if args.select:
        raise GatewayInputError(
            "--match-original-file-path cannot be combined with --select"
        )
    if args.all_results:
        raise GatewayInputError(
            "--match-original-file-path cannot be combined with --all-results"
        )
    if args.return_fields:
        raise GatewayInputError(
            "--match-original-file-path uses the fixed id, path, originalFilePath "
            "projection and cannot be combined with --return-field"
        )
    if args.take != MAX_QUERY_TAKE:
        raise GatewayInputError(
            "--match-original-file-path requires exactly "
            f"--take {MAX_QUERY_TAKE}"
        )
    normalized_original_file_candidates(args)


def normalized_original_file_candidates(
    args: argparse.Namespace,
) -> list[tuple[str, tuple[str, ...]]]:
    """Validate, normalize, and de-duplicate candidate paths in caller order."""

    raw_candidates = tuple(getattr(args, "match_original_file_paths", None) or ())
    if not 1 <= len(raw_candidates) <= MAX_ORIGINAL_FILE_PATH_CANDIDATES:
        raise GatewayInputError(
            "--match-original-file-path must be repeated between 1 and "
            f"{MAX_ORIGINAL_FILE_PATH_CANDIDATES} times"
        )
    candidates: list[tuple[str, tuple[str, ...]]] = []
    seen: dict[tuple[str, ...], int] = {}
    for index, raw_path in enumerate(raw_candidates):
        try:
            key = normalize_original_file_system_path(raw_path)
        except ValueError as exc:
            raise GatewayInputError(
                f"--match-original-file-path value {index + 1} is invalid: {exc}"
            ) from exc
        previous = seen.get(key)
        if previous is not None:
            raise GatewayInputError(
                "--match-original-file-path values must remain unique after "
                f"normalization; values {previous + 1} and {index + 1} collide"
            )
        seen[key] = index
        candidates.append((raw_path, key))
    return candidates


def normalize_original_file_system_path(value: Any) -> tuple[str, ...]:
    """Return a lexical comparison key for one absolute native or drive path."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("expected a nonempty absolute path without outer whitespace")
    try:
        encoded_size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("path is not valid UTF-8 text") from exc
    if encoded_size > MAX_ORIGINAL_FILE_PATH_BYTES:
        raise ValueError(
            f"path exceeds the {MAX_ORIGINAL_FILE_PATH_BYTES}-byte limit"
        )
    if any(
        ord(character) < 32
        or ord(character) == 127
        or character in {"\u2028", "\u2029"}
        for character in value
    ):
        raise ValueError("path contains a control character")

    return host_path_comparison_key(value)


def preflight_metadata_input(args: argparse.Namespace) -> None:
    """Reject metadata projection modes that have no packaged result contract."""

    if args.summary_only and args.operation != "types":
        raise GatewayInputError("metadata --summary-only is supported only for the types operation")
    discovery_only_supplied = (
        args.object_type is not None
        or args.queries is not None
        or args.limit is not None
        or args.detail
    )
    if args.operation != "discover":
        if discovery_only_supplied:
            raise GatewayInputError(
                "metadata --object-type, --query, --limit, and --detail are "
                "supported only for the discover operation"
            )
        return

    if any(
        value is not None
        for value in (args.property, args.platform, args.curve_type)
    ):
        raise GatewayInputError(
            "metadata discover does not accept --property, --platform, or --curve-type"
        )
    supplied_scopes = sum(
        value is not None
        for value in (args.object_type, args.class_id, args.object)
    )
    if supplied_scopes != 1:
        raise GatewayInputError(
            "metadata discover requires exactly one of --object-type, --class-id, "
            "or --object"
        )
    if args.object_type is not None and (
        not args.object_type.strip()
        or args.object_type != args.object_type.strip()
        or len(args.object_type) > MAX_METADATA_DISCOVERY_NAME_CHARS
    ):
        raise GatewayInputError(
            "metadata discover --object-type must be non-empty, have no outer "
            "whitespace, and contain at most "
            f"{MAX_METADATA_DISCOVERY_NAME_CHARS} characters"
        )
    if args.class_id is not None and not 0 <= args.class_id <= 0xFFFFFFFF:
        raise GatewayInputError(
            "metadata discover --class-id must be a uint32 integer"
        )
    if args.object is not None and (
        not args.object.strip()
        or args.object != args.object.strip()
        or len(args.object) > MAX_METADATA_DISCOVERY_NAME_CHARS * 8
    ):
        raise GatewayInputError(
            "metadata discover --object must be non-empty, have no outer "
            "whitespace, and remain within the bounded identifier length"
        )
    queries = args.queries
    if not isinstance(queries, list) or not (
        1 <= len(queries) <= MAX_METADATA_DISCOVERY_QUERIES
    ):
        raise GatewayInputError(
            "metadata discover requires 1.."
            f"{MAX_METADATA_DISCOVERY_QUERIES} --query values"
        )
    total_query_chars = 0
    seen_queries: set[str] = set()
    for query in queries:
        if (
            not isinstance(query, str)
            or not query.strip()
            or query != query.strip()
            or len(query) > MAX_METADATA_DISCOVERY_QUERY_CHARS
        ):
            raise GatewayInputError(
                "each metadata discover --query must be non-empty, have no outer "
                "whitespace, and contain at most "
                f"{MAX_METADATA_DISCOVERY_QUERY_CHARS} characters"
            )
        total_query_chars += len(query)
        folded_query = " ".join(query.split()).casefold()
        if folded_query in seen_queries:
            raise GatewayInputError(
                "metadata discover --query values must be distinct"
            )
        seen_queries.add(folded_query)
    if total_query_chars > MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS:
        raise GatewayInputError(
            "metadata discover query text exceeds the combined "
            f"{MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS}-character limit"
        )
    limit = (
        DEFAULT_METADATA_DISCOVERY_LIMIT
        if args.limit is None
        else args.limit
    )
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_METADATA_DISCOVERY_LIMIT
    ):
        raise GatewayInputError(
            "metadata discover --limit must be between 1 and "
            f"{MAX_METADATA_DISCOVERY_LIMIT}"
        )


def preflight_stable_read_input(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> None:
    """Validate closed profiler scalars before opening a WAAPI transport."""

    (version,) = resolve_catalog_versions(args, env=env)
    if args.command == "profiler-game-objects":
        build_profiler_game_objects_request(
            version=version,
            time=args.time,
        )
        return
    if len(args.bus_pipeline_id) > MAX_BUS_PIPELINE_IDS:
        raise GatewayInputError(
            "profiler-voice-contributions accepts at most "
            f"{MAX_BUS_PIPELINE_IDS} --bus-pipeline-id values"
        )
    build_profiler_voice_contributions_request(
        version=version,
        time=args.time,
        voice_pipeline_id=args.voice_pipeline_id,
        bus_pipeline_ids=tuple(args.bus_pipeline_id),
    )


def preflight_debug_read_input(args: argparse.Namespace) -> None:
    """Reject fixed debug-read scalar boundaries before opening WAAPI."""

    if args.command == "debug-wal-tree":
        if (
            isinstance(args.take, bool)
            or not isinstance(args.take, int)
            or not 1 <= args.take <= MAX_WAL_TREE_NODES
        ):
            raise GatewayInputError(
                f"debug-wal-tree --take must be between 1 and {MAX_WAL_TREE_NODES}"
            )
        return


def preflight_json_inputs(args: argparse.Namespace) -> None:
    """Validate the remaining typed command-line documents before WAAPI."""

    if args.command in {"wait-topic", "stream-topic"}:
        if (
            args.command == "wait-topic"
            and args.no_timeout
            and args.timeout is not None
        ):
            raise GatewayInputError(
                "wait-topic --no-timeout cannot be combined with global --timeout"
            )
        if (
            args.command == "wait-topic"
            and not 1 <= args.event_count <= MAX_WAIT_EVENT_COUNT
        ):
            raise GatewayInputError(
                f"wait-topic --event-count must be between 1 and {MAX_WAIT_EVENT_COUNT}"
            )
    elif args.command == "draft-apply":
        parse_operation_draft_cli_actions(args)


def topic_typed_input_requested(args: argparse.Namespace) -> bool:
    """Return whether one subscription invocation selected its typed input surface."""

    return any(
        (
            getattr(args, "options_schema_digest", None),
            getattr(args, "match_schema_digest", None),
            *(getattr(args, name, ()) for name in (
                "option_set",
                "option_append",
                "option_present",
                "option_choose",
                "option_choose_dynamic",
                "option_map_put",
                "match_set",
                "match_append",
                "match_present",
                "match_choose",
                "match_choose_dynamic",
                "match_map_put",
            )),
        )
    )


def _typed_topic_facts(args: argparse.Namespace, prefix: str) -> tuple[TypedRequestFact, ...]:
    facts = [
        TypedRequestFact("set", handle, value_type, value)
        for handle, value_type, value in getattr(args, f"{prefix}_set")
    ]
    facts.extend(
        TypedRequestFact("append", handle, value_type, value)
        for handle, value_type, value in getattr(args, f"{prefix}_append")
    )
    facts.extend(
        TypedRequestFact("present", handle, "null", "null")
        for handle in getattr(args, f"{prefix}_present")
    )
    facts.extend(
        TypedRequestFact("choose", handle, "branch", choice)
        for handle, choice in getattr(args, f"{prefix}_choose")
    )
    facts.extend(
        TypedRequestFact("choose-dynamic", handle, "choice", choice, key=key)
        for handle, key, choice in getattr(args, f"{prefix}_choose_dynamic")
    )
    facts.extend(
        TypedRequestFact("map-put", handle, value_type, value, key=key)
        for handle, key, value_type, value in getattr(args, f"{prefix}_map_put")
    )
    return tuple(facts)


def preflight_typed_topic_input(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> None:
    """Materialize exact Topic options and subset match before connecting."""

    if not isinstance(args.options_schema_digest, str) or not isinstance(
        args.match_schema_digest, str
    ):
        raise GatewayInputError(
            "Typed Topic input requires both schema digests from topic-schema"
        )
    (version,) = resolve_catalog_versions(args, env=env)
    args.typed_topic_input = materialize_typed_topic_inputs(
        version=version,
        topic=args.api,
        options_schema_digest=args.options_schema_digest,
        option_facts=_typed_topic_facts(args, "option"),
        match_schema_digest=args.match_schema_digest,
        match_facts=_typed_topic_facts(args, "match"),
    )


_LEGACY_OPERATION_PROJECTION_FIELDS = frozenset(
    {
        "request_contract",
        "required_arguments",
        "optional_arguments",
        "additional_properties",
        "argument_contract",
        "constraints",
        "identity_contract",
        "parent_child_contract",
        "file_read_policy",
        "preview_owns",
    }
)


def composer_operation_projection(
    spec: Any,
    *,
    version: str | None,
) -> dict[str, Any]:
    """Return normal discovery without a copyable Legacy request shape.

    Descriptive constraints remain useful model-facing routing facts.  Only
    the machine request document and its duplicated field schema are removed;
    the typed operation/Composer contract below owns executable construction.
    """

    projection = spec.as_dict(version=version)
    for field in _LEGACY_OPERATION_PROJECTION_FIELDS:
        projection.pop(field, None)
    for field in ("constraints", "identity_contract", "parent_child_contract"):
        value = spec.as_dict(version=version).get(field)
        if value is not None:
            projection[field] = value
    if spec.name in {
        "debug.restartWaapiServers",
        "debug.testAssert",
        "debug.testCrash",
    }:
        projection.pop("constraints", None)
    return projection


def operation_composer_input_contract(
    operation: str,
    version: str,
    *,
    inventory: bool = False,
) -> dict[str, Any]:
    """Project the single normal Composer entry and its typed lifecycle."""

    contract = operation_composer_contract(operation, version)
    if inventory:
        fragments = contract.get("registry_fragments")
        if fragments is not None:
            fragments = require_mapping(
                fragments,
                "operation Composer registry fragments",
            )
            source_schema_digest = fragments["source_schema_digest"]
        else:
            source_schema_digest = contract.get("typed_request_schema_digest")
            if not isinstance(source_schema_digest, str) or not source_schema_digest:
                raise GatewayInputError(
                    "operation Composer typed request schema digest must be a non-empty string"
                )
        return {
            "contract": contract["contract"],
            "operation": operation,
            "version": version,
            "action_contract": contract["action_contract"],
            "actions": list(contract["actions"]),
            "limits": dict(contract["limits"]),
            "registry_source_schema_digest": source_schema_digest,
            "inspect_with": f"operation-schema {operation}",
        }
    start_preconditions = contract.get("start_preconditions")
    fragments = contract.get("registry_fragments")
    if isinstance(start_preconditions, Mapping) and isinstance(fragments, Mapping):
        default_container = next(
            (
                fragments.get(key)
                for key in (
                    "default_container_target_contract",
                    "default_container_parent_contract",
                )
                if isinstance(fragments.get(key), Mapping)
            ),
            None,
        )
        metadata_scope = (
            default_container.get("dynamic_actor_mixer_metadata_scope")
            if isinstance(default_container, Mapping)
            else None
        )
        actor_mixer_type = (
            metadata_scope.get("actor_mixer_object_type")
            if isinstance(metadata_scope, Mapping)
            else None
        )
        if isinstance(actor_mixer_type, str) and actor_mixer_type:
            exact_preconditions = dict(start_preconditions)
            exact_preconditions["reviewed_default_container_metadata_argv"] = {
                "applies_when": (
                    "all requested targets use the Registry-resolved default "
                    "Actor-Mixer container scope"
                ),
                "gateway_argv_template": [
                    "metadata",
                    "discover",
                    "--object-type",
                    actor_mixer_type,
                    "--query",
                    "<requested-field-name>",
                    "--limit",
                    "<1..8>",
                ],
                "replace_only": ["<requested-field-name>", "<1..8>"],
            }
            contract = {**contract, "start_preconditions": exact_preconditions}
    audio_import_option_names = (
        contract.get("action_shapes", {})
        .get("set_import_option", {})
        .get("allowed_names", [])
    )
    if operation == "audio.import" and (
        not isinstance(audio_import_option_names, list)
        or not audio_import_option_names
        or not all(isinstance(name, str) and name for name in audio_import_option_names)
    ):
        raise RuntimeError("audio.import source-control option projection is invalid")
    audio_import_option_choice = "(" + "|".join(audio_import_option_names) + ")"
    generic_typed_action_argv = {
        "add_typed_fact": [
            "--fact-action", "ACTION", "--field-handle", "HANDLE",
            "[--value-type TYPE]", "[--fact-value VALUE]", "[--key KEY]",
        ],
        "correct_typed_fact": [
            "--fact-handle", "HANDLE", "--fact-action", "ACTION",
            "--field-handle", "HANDLE", "[--value-type TYPE]",
            "[--fact-value VALUE]", "[--key KEY]",
        ],
        "remove_typed_fact": ["--fact-handle", "HANDLE"],
    }
    fact_action_argv = {
        "set": [
            "--fact-action", "set", "--field-handle", "HANDLE",
            "--value-type", "TYPE", "--fact-value", "VALUE",
        ],
        "append": [
            "--fact-action", "append", "--field-handle", "HANDLE",
            "--value-type", "TYPE", "--fact-value", "VALUE",
        ],
        "present": [
            "--fact-action", "present", "--field-handle", "HANDLE",
        ],
        "choose": [
            "--fact-action", "choose", "--field-handle", "HANDLE",
            "--fact-value", "CHOICE_HANDLE",
        ],
        "choose-dynamic": [
            "--fact-action", "choose-dynamic", "--field-handle", "HANDLE",
            "--key", "KEY", "--fact-value", "CHOICE_HANDLE",
        ],
        "map-put": [
            "--fact-action", "map-put", "--field-handle", "HANDLE",
            "--key", "KEY", "--value-type", "TYPE",
            "--fact-value", "VALUE",
        ],
    }
    action_argv_by_operation = {
        "object.set": {
            "set_request_option": ["--option", "NAME", "TYPE", "VALUE"],
            "clear_request_option": ["--option", "NAME"],
            "add_target": [
                "--target", "SELECTOR_KIND", "SELECTOR_VALUES...",
                "[--name VALUE]", "[--notes VALUE]", "[--platform VALUE]",
                "[--list-mode VALUE]", "[--on-name-conflict VALUE]",
                "[--property NAME TYPE VALUE]...",
                "[--reference NAME SELECTOR_KIND SELECTOR_VALUES...]...",
            ],
            "set_target_field": [
                "--target-handle", "HANDLE", "--field", "NAME", "TYPE", "VALUE"
            ],
            "clear_target_field": ["--target-handle", "HANDLE", "--field", "NAME"],
            "set_property": [
                "--target-handle", "HANDLE", "--property", "NAME", "TYPE", "VALUE"
            ],
            "remove_property": ["--target-handle", "HANDLE", "--property", "NAME"],
            "set_reference": [
                "--owner-handle", "HANDLE", "--reference", "NAME",
                "SELECTOR_KIND", "SELECTOR_VALUES...",
            ],
            "remove_reference": ["--owner-handle", "HANDLE", "--reference", "NAME"],
            "add_child": [
                "--parent-handle", "HANDLE", "--type", "TYPE", "--name", "NAME"
            ],
            "set_node_field": [
                "--node-handle", "HANDLE", "--field", "NAME", "TYPE", "VALUE"
            ],
            "clear_node_field": ["--node-handle", "HANDLE", "--field", "NAME"],
            "set_node_property": [
                "--node-handle", "HANDLE", "--property", "NAME", "TYPE", "VALUE"
            ],
            "remove_node_property": ["--node-handle", "HANDLE", "--property", "NAME"],
            "remove_node": ["--node-handle", "HANDLE"],
            "add_list": ["--target-handle", "HANDLE", "--list", "NAME"],
            "remove_list": ["--list-handle", "HANDLE"],
            "add_list_member": [
                "--list-handle", "HANDLE", "--type", "TYPE", "--name", "NAME"
            ],
            "remove_target": ["--target-handle", "HANDLE"],
            "add_import_file": [
                "--owner-handle", "HANDLE", "(--audio-file PATH | --audio-file-base64 DATA)",
                "[--originals-subfolder VALUE]", "[--language VALUE]", "[--object-type VALUE]",
            ],
            "set_import_file_field": [
                "--file-handle", "HANDLE", "--field", "NAME", "TYPE", "VALUE"
            ],
            "clear_import_file_field": ["--file-handle", "HANDLE", "--field", "NAME"],
            "remove_import_file": ["--file-handle", "HANDLE"],
            "set_import_option": [
                "--owner-handle", "HANDLE", "--option", "NAME", "TYPE", "VALUE"
            ],
            "clear_import_option": ["--owner-handle", "HANDLE", "--option", "NAME"],
            "remove_import": ["--owner-handle", "HANDLE"],
        },
        "audio.import": {
            "set_import_operation": ["--mode", "MODE"],
            "set_import_option": [
                "--option",
                audio_import_option_choice,
                "boolean",
                "VALUE",
            ],
            "clear_import_option": [
                "--option",
                audio_import_option_choice,
            ],
            "set_import_default": [
                "(--default NAME TYPE VALUE | --import-location SELECTOR_KIND SELECTOR_VALUES... | --event ACTION PATH | --event-path PATH | --property NAME TYPE VALUE... | --empty-properties | --reference NAME SELECTOR_KIND SELECTOR_VALUES... | --empty-references)"
            ],
            "clear_import_default": ["--default", "NAME"],
            "add_import_row": [
                "--object-path", "PATH", "--object-type", "TYPE",
                "[--audio-file PATH]", "[--audio-file-base64 DATA]",
                "[--audio-source-notes VALUE]", "[--dialogue-event VALUE]",
                "[(--event ACTION PATH | --event-path PATH)]", "[--import-language VALUE]",
                "[--import-location SELECTOR_KIND SELECTOR_VALUES...]", "[--notes VALUE]",
                "[--originals-subfolder VALUE]",
                "[--property NAME TYPE VALUE]...",
                "[--empty-properties]",
                "[--reference NAME SELECTOR_KIND SELECTOR_VALUES...]...",
                "[--empty-references]",
                "(--assignment none | --assignment switch VALUE)",
            ],
            "set_import_row_field": [
                "--import-handle", "HANDLE",
                "(--field NAME TYPE VALUE | --import-location SELECTOR_KIND SELECTOR_VALUES... | --event ACTION PATH | --event-path PATH | --property NAME TYPE VALUE... | --empty-properties | --reference NAME SELECTOR_KIND SELECTOR_VALUES... | --empty-references)",
            ],
            "clear_import_row_field": ["--import-handle", "HANDLE", "--field", "NAME"],
            "remove_import_row": ["--import-handle", "HANDLE"],
        },
        **{
            operation_name: generic_typed_action_argv
            for operation_name in DRAFT_TYPED_OPERATIONS
        },
        "waapi.undoGroup": {
            "set_display_name": ["--display-name", "VALUE"],
            "add_child_call": ["--child-operation", "OPERATION"],
            "add_child_typed_fact": [
                "--child-handle", "HANDLE", "--fact-action", "ACTION",
                "--field-handle", "HANDLE", "[--value-type TYPE]",
                "[--fact-value VALUE]", "[--key KEY]",
            ],
            "correct_child_typed_fact": [
                "--child-handle", "HANDLE", "--fact-handle", "HANDLE",
                "--fact-action", "ACTION", "--field-handle", "HANDLE",
                "[--value-type TYPE]", "[--fact-value VALUE]", "[--key KEY]",
            ],
            "remove_child_typed_fact": [
                "--child-handle", "HANDLE", "--fact-handle", "HANDLE",
            ],
            "remove_child_call": ["--child-handle", "HANDLE"],
        },
    }
    operation_argv = action_argv_by_operation[operation]
    if not set(contract["actions"]).issubset(operation_argv):
        raise RuntimeError("Operation Composer CLI vocabulary is incomplete")
    action_argv = {
        action_name: operation_argv[action_name]
        for action_name in contract["actions"]
    }
    selector_kinds = [
        "id-string VALUE",
        "id-integer VALUE",
        "path VALUE",
        "exact-type-name TYPE NAME",
        "direct-child TYPE PARENT_SELECTOR...",
        "scoped-name TYPE NAME PARENT_SELECTOR...",
    ]
    apply_contract = {
        "subcommand": "draft-apply",
        "action_flag": "--action",
        "gateway_argv": [
            "draft-apply",
            "<draft_id>",
            "--task-authority",
            "<task_authority>",
            "--expected-revision",
            "<revision>",
            "--compact",
            "--facts",
            "--action",
            "<action-name>",
            "<typed-fact-arguments>",
        ],
        "action_argv": action_argv,
        **(
            {"fact_action_argv": fact_action_argv}
            if "add_typed_fact" in action_argv
            or "add_child_typed_fact" in action_argv
            else {}
        ),
        "scalar_types": ["string", "number", "integer", "boolean"],
        **(
            {"selector_kinds": selector_kinds}
            if any(
                "SELECTOR" in token
                for tokens in action_argv.values()
                for token in tokens
            )
            else {}
        ),
        "bind_from_prior_response": [
            "draft_id",
            "task_authority",
            "revision",
        ],
        "revision_discipline": {
            "mode": "one_ordered_atomic_batch_then_read",
            "action_count": {
                "minimum": 1,
                "maximum": MAX_TYPED_ACTIONS_PER_APPLY,
            },
            "repeat_complete_action_group": [
                "--action",
                "<action-name>",
                "<typed-fact-arguments>",
            ],
            "revision_delta": "action_count",
            "failure": "unchanged",
            "expected_revision_source": "/draft/revision",
            "next_action_template_source": (
                "/draft/next_action_binding/fixed_argv_prefix"
            ),
            "precompute_or_increment_revision": False,
        },
    }
    return {
        **contract,
        "start": {
            "subcommand": "draft-start",
            "gateway_argv": ["draft-start", operation],
            **(
                {"preconditions": dict(contract["start_preconditions"])}
                if "start_preconditions" in contract
                else {}
            ),
        },
        "dynamic_container_commands": {
            "map_value": "request-map-container",
            "array_item": "request-array-item",
            "schema_digest": contract.get("typed_request_schema_digest"),
            "map_value_argv": [
                "request-map-container",
                operation,
                "--schema-digest",
                contract.get("typed_request_schema_digest"),
                "--map-handle",
                "<parent_handle>",
                "--key",
                "<key>",
                "--shape",
                "<object|array>",
            ],
            "array_item_argv": [
                "request-array-item",
                operation,
                "--schema-digest",
                contract.get("typed_request_schema_digest"),
                "--array-handle",
                "<parent_handle>",
                "--index",
                "<zero_based_index>",
                "--shape",
                "<object|array>",
            ],
            "draft_binding": False,
            "nested_parent_argv": [
                "--parent-schema-token",
                "<schema_lineage_token_from_parent_disclosure>",
            ],
            "scalar_map_entry_action": (
                "use draft-apply add_typed_fact with fact-action map-put directly; "
                "request-map-container is only for an object or array value"
            ),
            "sequence": (
                "disclose each complex child with the operation and schema digest; "
                "then add the append/map-put Draft fact with the returned child handle; "
                "disclosure never consumes or changes the Draft revision; a nested "
                "child must append --parent-schema-token with the exact token returned "
                "by its parent disclosure; do not add --member-key until the parent "
                "response explicitly returns branch_disclosure"
            ),
        },
        "apply": apply_contract,
        "check": {
            "subcommand": "draft-check",
            "gateway_argv": [
                "draft-check",
                "<draft_id>",
                "--task-authority",
                "<task_authority>",
                "--expected-revision",
                "<revision>",
            ],
        },
        "seal": {
            "subcommand": "preview-from-draft",
            "gateway_argv": [
                "preview-from-draft",
                "<draft_id>",
                "--task-authority",
                "<task_authority>",
                "--expected-revision",
                "<revision>",
                "--apply",
            ],
        },
        "cancel": {
            "subcommand": "draft-cancel",
            "gateway_argv": [
                "draft-cancel",
                "<draft_id>",
                "--task-authority",
                "<task_authority>",
                "--expected-revision",
                "<revision>",
            ],
        },
        "check_subcommand": "draft-check",
        "seal_subcommand": "preview-from-draft",
        "cancel_subcommand": "draft-cancel",
        "complete_request_authored_by_gateway": True,
    }


def operation_draft_schema_digest(operation: str, version: str) -> str:
    """Bind named-operation and exact-URI Drafts to their owning schema."""

    if operation.startswith("ak."):
        return request_contract(version, operation).schema_digest
    if operation in DRAFT_TYPED_OPERATIONS:
        return draft_operation_request_contract(operation, version).schema_digest
    return operation_request_schema_digest(operation, version)


def public_typed_contract(version: str, api: str) -> Any:
    """Resolve one function or query construction contract by exact public key."""

    if api == STRUCTURED_TYPED_QUERY_OPERATION:
        return typed_query_contract(version)
    if api == ADVANCED_TYPED_QUERY_OPERATION:
        return typed_query_contract(version, advanced=True)
    if api.startswith(TOPIC_OPTIONS_OPERATION_PREFIX):
        return topic_options_contract(
            version, api.removeprefix(TOPIC_OPTIONS_OPERATION_PREFIX)
        )
    if api.startswith(TOPIC_MATCH_OPERATION_PREFIX):
        return topic_match_contract(
            version, api.removeprefix(TOPIC_MATCH_OPERATION_PREFIX)
        )
    if api.startswith("undo-child:"):
        from wwise_waapi.typed_operations import compound_child_request_contract

        return compound_child_request_contract(
            api.removeprefix("undo-child:"), version
        )
    if api in DRAFT_TYPED_OPERATIONS:
        return draft_operation_request_contract(api, version)
    return request_contract(version, api)


def typed_topic_contract_payload(contract: Any) -> dict[str, Any]:
    """Project one shared Core contract with Topic-specific continuation names."""

    payload = contract.as_gateway_payload()
    # Topic discovery already owns one outer fact-selection continuation and
    # exposes a compact, lossless field table for each of its two subcontracts.
    # Repeating the request-wide Draft plan in both nested projections adds no
    # construction authority and can push the final public document past its
    # fixed visible ceiling.
    payload.pop("construction_order", None)
    payload.pop("top_level_fact_plan", None)
    payload["fields"] = contract.gateway_field_table()
    payload["input_shape"] = "typed-facts"
    payload["continuation"] = {
        "dynamic_container_commands": {
            "map_value": "request-map-container",
            "array_item": "request-array-item",
        },
        "request_key": contract.uri,
    }
    return payload


def _container_schema_binding_argv(
    contract: TypedRequestContract,
    *,
    parent_schema_token: str | None,
) -> list[str]:
    """Bind a root container by digest or a nested container by exact lineage."""

    return (
        []
        if parent_schema_token is not None
        else ["--schema-digest", contract.schema_digest]
    )


def _dynamic_branch_disclosure_continuation(
    args: argparse.Namespace,
    *,
    contract: Any,
    child_handle: str,
    child_contract: Mapping[str, Any],
    lineage_token: str,
) -> dict[str, Any]:
    """Return the sole next disclosure for one newly issued object handle."""

    if args.member_key is not None or args.shape != "object":
        return {}
    branch_rows = child_contract.get("branch_choices")
    if not isinstance(branch_rows, list):
        branch_rows = []
    has_container_choice = any(
        isinstance(row, Mapping)
        and isinstance(row.get("choices"), list)
        and any(
            isinstance(choice, Mapping)
            and isinstance(choice.get("accepted_types"), list)
            and any(
                value_type in {"object", "array"}
                for value_type in choice["accepted_types"]
            )
            for choice in row["choices"]
        )
        for row in branch_rows
    )
    if child_contract.get("member_key_disclosure_required"):
        command = [
            args.command,
            args.api,
            *_container_schema_binding_argv(
                contract,
                parent_schema_token=args.parent_schema_token,
            ),
            *(
                ["--map-handle", args.map_handle, "--key", args.key]
                if args.command == "request-map-container"
                else ["--array-handle", args.array_handle, "--index", str(args.index)]
            ),
            "--shape",
            args.shape,
            *(
                ["--choice-handle", args.choice_handle]
                if args.choice_handle is not None
                else []
            ),
            "--member-key",
            "<exact-key>",
            *(
                ["--parent-schema-token", args.parent_schema_token]
                if args.parent_schema_token is not None
                else []
            ),
        ]
    elif has_container_choice:
        command = [
            "request-map-container",
            args.api,
            "--map-handle",
            child_handle,
            "--key",
            "<exact-key>",
            "--shape",
            "object",
            "--parent-schema-token",
            lineage_token,
            "--choice-handle",
            "<selected-choice-handle-from-child_contract>",
        ]
    else:
        return {}
    return {"branch_disclosure": command}


def _fixed_nested_container_disclosures(
    args: argparse.Namespace,
    *,
    contract: Any,
    child_handle: str,
    child_contract: Mapping[str, Any],
    lineage_token: str,
) -> list[dict[str, Any]]:
    """Return direct schema-owned child containers in canonical property order."""

    if args.member_key is not None or args.shape != "object":
        return []
    rows = child_contract.get("fixed_container_members")
    if not isinstance(rows, list):
        return []
    branch_rows = child_contract.get("branch_choices")
    branch_keys: set[Any] = set()
    if isinstance(branch_rows, list):
        branch_keys = {
            row.get("key")
            for row in branch_rows
            if isinstance(row, Mapping)
            and isinstance(row.get("key"), str)
            and isinstance(row.get("choices"), list)
            and row["choices"]
        }
    result: list[dict[str, Any]] = []
    for queue_index, row in enumerate(rows, start=1):
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("key"), str)
            or row.get("shape") not in {"object", "array"}
        ):
            continue
        key = str(row["key"])
        shape = str(row["shape"])
        if key in branch_keys:
            continue
        result.append(
            {
                "key": key,
                "shape": shape,
                "required": row.get("required") is True,
                "condition": "current_business_request_contains_member",
                "queue_index": queue_index,
                "is_next_command": False,
                "argv": [
                    "request-map-container",
                    args.api,
                    "--map-handle",
                    child_handle,
                    "--key",
                    key,
                    "--shape",
                    shape,
                    "--parent-schema-token",
                    lineage_token,
                ],
            }
        )
    return result


def _dynamic_deferred_queue_contract() -> dict[str, Any]:
    """Return the one request-wide ordering contract for returned-handle facts."""

    return {
        "scope": "current_disclosed_root",
        "root_boundary": (
            "current_root_disclosures_then_current_root_facts_before_next_root"
        ),
        "drain_after": "root_dynamic_disclosures",
        "traversal": "response_tree_preorder",
        "node_steps": [
            "deferred_parent_fact",
            "child_contract_facts",
            "descendant_response_nodes",
        ],
        "parent_dependency": (
            "deferred_parent_fact_before_every_fact_using_response_handle"
        ),
        "array_traversal": "response_tree_preorder_within_current_root",
        "sibling_order": "ascending_business_present_index",
    }


def _bind_dynamic_branch_facts(
    child_contract: dict[str, Any],
    *,
    child_handle: str,
    draft_shape: bool,
    undo_child_shape: bool,
    query_shape: bool,
    topic_prefix: str | None,
) -> None:
    """Attach exact public facts for schema-owned child values and choices."""

    scalar_rows = child_contract.pop("fixed_scalar_members", None)
    if isinstance(scalar_rows, list):
        bound_scalar_rows: list[dict[str, Any]] = []
        for row in scalar_rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("key"), str):
                continue
            accepted_types = row.get("accepted_types")
            if not isinstance(accepted_types, list) or not all(
                isinstance(value_type, str) for value_type in accepted_types
            ):
                continue
            argv_by_type: dict[str, list[str]] = {}
            for value_type in accepted_types:
                deferred = _deferred_dynamic_fact_payload(
                    [
                        "--map-put",
                        child_handle,
                        str(row["key"]),
                        value_type,
                        "<business-value>",
                    ],
                    draft_shape=draft_shape,
                    undo_child_shape=undo_child_shape,
                    query_shape=query_shape,
                    topic_prefix=topic_prefix,
                )
                payload = deferred.get("deferred_fact")
                if isinstance(payload, Mapping) and isinstance(payload.get("argv"), list):
                    argv_by_type[value_type] = list(payload["argv"])
            if not argv_by_type:
                continue
            bound = dict(row)
            bound.update(
                {
                    "fact_argv_by_type": argv_by_type,
                    "execute_after": "deferred_parent_fact",
                    "is_next_command": False,
                    "consume_once": True,
                    "replay_allowed": False,
                }
            )
            bound_scalar_rows.append(bound)
        if bound_scalar_rows:
            child_contract["fixed_scalar_member_facts"] = bound_scalar_rows

    constant_rows = child_contract.get("constant_field_facts")
    if isinstance(constant_rows, list):
        for row in constant_rows:
            if not isinstance(row, dict):
                continue
            typed_fact = row.get("typed_fact")
            if not isinstance(typed_fact, Mapping):
                continue
            key = typed_fact.get("key")
            value_type = typed_fact.get("value_type")
            value = typed_fact.get("value")
            if not all(isinstance(item, str) for item in (key, value_type, value)):
                continue
            deferred = _deferred_dynamic_fact_payload(
                ["--map-put", child_handle, key, value_type, value],
                draft_shape=draft_shape,
                undo_child_shape=undo_child_shape,
                query_shape=query_shape,
                topic_prefix=topic_prefix,
            )
            if isinstance(deferred.get("deferred_fact"), dict):
                deferred["deferred_fact"].pop("must_precede", None)
                deferred["deferred_fact"].update(
                    {
                        "execute_after": "deferred_parent_fact",
                        "queue_phase": "child_contract",
                        "queue_order_ref": (
                            "/continuation/request_wide_order/deferred_fact_queue"
                        ),
                        "is_next_command": False,
                        "consume_once": True,
                        "replay_allowed": False,
                    }
                )
            row.update(deferred)

    rows = child_contract.get("branch_choices")
    if not isinstance(rows, list):
        return
    for queue_index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or not isinstance(row.get("key"), str):
            continue
        key = str(row["key"])
        row.update(
            {
                "queue_index": queue_index,
                "fact_sequence": (
                    "choose_one_then_map_put_same_key_before_next_branch"
                ),
                "next_branch_blocked_until_complete": True,
            }
        )
        if (
            (draft_shape or undo_child_shape)
            and not query_shape
            and topic_prefix is None
        ):
            action_prefix = [
                "--action",
                "add_child_typed_fact" if undo_child_shape else "add_typed_fact",
                *(
                    ["--child-handle", "<child_handle>"]
                    if undo_child_shape
                    else []
                ),
            ]
            choose_argv = [
                *action_prefix,
                "--fact-action",
                "choose-dynamic",
                "--field-handle",
                child_handle,
                "--fact-value",
                "<selected-choice-handle>",
                "--key",
                key,
            ]
            map_put_argv = [
                *action_prefix,
                "--fact-action",
                "map-put",
                "--field-handle",
                child_handle,
                "--key",
                key,
                "--value-type",
                "<selected-accepted-type>",
                "--fact-value",
                "<selected-choice-enum-or-business-value>",
            ]
        elif query_shape:
            choose_argv = [
                "--typed-choose-dynamic",
                child_handle,
                key,
                "<selected-choice-handle>",
            ]
            map_put_argv = [
                "--typed-map-put",
                child_handle,
                key,
                "<selected-accepted-type>",
                "<selected-choice-enum-or-business-value>",
            ]
        elif topic_prefix is not None:
            choose_argv = [
                f"--{topic_prefix}-choose-dynamic",
                child_handle,
                key,
                "<selected-choice-handle>",
            ]
            map_put_argv = [
                f"--{topic_prefix}-map-put",
                child_handle,
                key,
                "<selected-accepted-type>",
                "<selected-choice-enum-or-business-value>",
            ]
        else:
            choose_argv = [
                "--choose-dynamic",
                child_handle,
                key,
                "<selected-choice-handle>",
            ]
            map_put_argv = [
                "--map-put",
                child_handle,
                key,
                "<selected-accepted-type>",
                "<selected-choice-enum-or-business-value>",
            ]
        row["fact_construction"] = {
            "choose_dynamic_argv": choose_argv,
            "map_put_argv": map_put_argv,
            "selected_choice_source": "choices/<selected-by-business-value>",
            "execute_after": "deferred_parent_fact",
            "queue_phase": "child_contract",
            "queue_order_ref": (
                "/continuation/request_wide_order/deferred_fact_queue"
            ),
            "consume_each_fact_once": True,
            "replay_allowed": False,
        }
        choices = row.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict) or not isinstance(
                choice.get("handle"), str
            ):
                continue
            enum_values = choice.get("enum")
            choice["map_put_required"] = True
            choice["map_put_value_source"] = (
                "sole_enum"
                if isinstance(enum_values, list) and len(enum_values) == 1
                else "business_value"
            )


def _compact_fixed_scalar_member_facts(child_contract: dict[str, Any]) -> None:
    """Table repeated scalar fact policy without losing any public fact argv."""

    rows = child_contract.get("fixed_scalar_member_facts")
    if not isinstance(rows, list) or len(rows) < 3:
        return
    columns = [
        "key",
        "required",
        "accepted_types",
        "business_value_pointer",
        "fact_argv_by_type",
        "description",
    ]
    table_rows: list[list[Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            return
        table_rows.append(
            [
                row.get("key"),
                row.get("required") is True,
                row.get("accepted_types", []),
                row.get("business_value_pointer"),
                row.get("fact_argv_by_type", {}),
                row.get("description"),
            ]
        )
    child_contract.pop("fixed_scalar_member_facts")
    child_contract["fixed_scalar_member_fact_table"] = {
        "columns": columns,
        "rows": table_rows,
        "shared_policy": {
            "condition": "current_business_request_contains_member",
            "execute_after": "deferred_parent_fact",
            "queue_phase": "child_contract",
            "queue_order_ref": (
                "/continuation/request_wide_order/deferred_fact_queue"
            ),
            "must_precede": "all_descendant_response_facts",
            "is_next_command": False,
            "consume_once": True,
            "replay_allowed": False,
        },
    }


def _deferred_dynamic_fact_payload(
    fact: Sequence[str],
    *,
    draft_shape: bool,
    undo_child_shape: bool,
    query_shape: bool,
    topic_prefix: str | None,
) -> dict[str, Any]:
    """Describe one returned-handle fact without presenting it as the next command."""

    if undo_child_shape:
        argv = [
            "--action", "add_child_typed_fact",
            "--child-handle", "<child_handle>",
            "--fact-action", fact[0].removeprefix("--"),
            "--field-handle", str(fact[1]),
            "--value-type", str(fact[-2]),
            "--fact-value", str(fact[-1]),
            *(["--key", str(fact[2])] if fact[0] == "--map-put" else []),
        ]
    elif draft_shape and not query_shape and topic_prefix is None:
        argv = [
            "--action", "add_typed_fact",
            "--fact-action", fact[0].removeprefix("--"),
            "--field-handle", str(fact[1]),
            "--value-type", str(fact[-2]),
            "--fact-value", str(fact[-1]),
            *(["--key", str(fact[2])] if fact[0] == "--map-put" else []),
        ]
    else:
        argv = [
            (
                f"--typed-{fact[0].removeprefix('--')}"
                if query_shape
                else f"--{topic_prefix}-{fact[0].removeprefix('--')}"
                if topic_prefix is not None
                else fact[0]
            ),
            *fact[1:],
        ]
    return {
        "deferred_fact": {
            "argv": argv,
            "execute_after": "all_dynamic_disclosures_for_current_root",
            "queue_phase": "parent_response",
            "queue_order_ref": (
                "/continuation/request_wide_order/deferred_fact_queue"
            ),
            "must_precede": {
                "all_facts_with_field_handle": str(fact[-1]),
                "reason": "attach_returned_handle_to_its_parent_first",
            },
            "is_next_command": False,
            "consume_once": True,
            "replay_allowed": False,
        }
    }


def _next_array_item_disclosure(
    args: argparse.Namespace,
    *,
    contract: TypedRequestContract,
    child_handle: str,
    lineage_token: str,
) -> dict[str, Any]:
    """Expose the sole nested-array continuation before its parent fact."""

    if args.shape != "array":
        return {}
    try:
        lineage = parse_typed_schema_lineage_token(
            contract,
            token=lineage_token,
            parent_handle=child_handle,
        )
    except TypedRequestError:
        # A legacy caller may mint a nested container without replaying its
        # parent lineage. Preserve that bounded response, but do not advertise
        # a descendant continuation that the Gateway cannot revalidate.
        return {}
    if lineage is None:
        return {}
    child_schema, child_section = lineage
    argv_by_shape: dict[str, list[str]] = {}
    for shape in ("object", "array"):
        if not dynamic_array_item_choices(
            contract,
            array_handle=child_handle,
            index=0,
            shape=shape,
            parent_schema=child_schema,
            parent_section=child_section,
        ):
            continue
        argv_by_shape[shape] = [
            "request-array-item",
            args.api,
            "--array-handle",
            child_handle,
            "--index",
            "<zero_based_business_present_index>",
            "--shape",
            shape,
            "--parent-schema-token",
            lineage_token,
        ]
    if not argv_by_shape:
        return {}
    return {
        "next_item_disclosure": {
            "condition": "for_each_business_present_item",
            "index_order": "ascending_zero_based_index",
            "must_finish_before": "deferred_fact",
            "is_next_command": True,
            "business_cardinality_authority": {
                "source": "current_business_request",
                "schema_does_not_require_another_item": True,
                "do_not_disclose_absent_index": True,
            },
            "argv_by_shape": argv_by_shape,
        }
    }


def _next_array_sibling_disclosure(
    args: argparse.Namespace,
    *,
    contract: TypedRequestContract,
    parent_schema: Mapping[str, Any] | None,
    parent_section: str | None,
    current_business_value_pointer: str | None,
) -> dict[str, Any]:
    """Expose the exact conditional next complex sibling for one array item."""

    if args.command != "request-array-item":
        return {}
    if args.parent_schema_token is None and not any(
        field.handle == args.array_handle for field in contract.fields
    ):
        # A legacy caller may use a dynamic child handle without its lineage.
        # The current item remains bounded, but no sibling command can be
        # rederived safely from the root contract alone.
        return {}
    next_index = args.index + 1
    argv_by_shape: dict[str, list[str]] = {}
    for shape in ("object", "array"):
        if not dynamic_array_item_choices(
            contract,
            array_handle=args.array_handle,
            index=next_index,
            shape=shape,
            parent_schema=parent_schema,
            parent_section=parent_section,
        ):
            continue
        argv_by_shape[shape] = [
            "request-array-item",
            args.api,
            *_container_schema_binding_argv(
                contract,
                parent_schema_token=args.parent_schema_token,
            ),
            "--array-handle",
            args.array_handle,
            "--index",
            str(next_index),
            "--shape",
            shape,
            *(
                ["--parent-schema-token", args.parent_schema_token]
                if args.parent_schema_token is not None
                else []
            ),
        ]
    if not argv_by_shape:
        return {}
    if current_business_value_pointer is None:
        return {}
    return {
        "next_sibling_disclosure": {
            "condition": "current_business_request_contains_next_complex_item",
            "business_value_pointer": (
                f"{current_business_value_pointer.rsplit('/', 1)[0]}/{next_index}"
            ),
            "index": next_index,
            "must_follow": "current_root_fact_apply_success",
            "absent_or_scalar_next_item_forbidden": True,
            "is_next_command": False,
            "argv_by_shape": argv_by_shape,
        }
    }


def _next_nested_disclosure_selector(
    rows: Sequence[Mapping[str, Any]],
    *,
    next_sibling_disclosure: Mapping[str, Any],
) -> dict[str, Any]:
    """Tell the caller how to select the next exact business-present child."""

    if not rows:
        return {}
    return {
        "next_business_present_nested_disclosure": {
            "candidate_pointer": "/continuation/nested_container_disclosures",
            "selection": "first_business_present_member_by_queue_index",
            "repeat_for_descendants": True,
            "when_none": (
                "follow_next_sibling_then_drain_deferred_fact_queue"
                if next_sibling_disclosure.get(
                    "next_sibling_disclosure", {}
                ).get("is_next_command") is True
                else "drain_deferred_fact_queue_then_follow_next_sibling"
            ),
            "is_next_command": True,
        }
    }


def _dynamic_next_command_decision(
    *,
    draft_shape: bool,
    outermost_disclosed_root_pointer: str | None,
    branch_continuation: Mapping[str, Any],
    nested_container_disclosures: Sequence[Mapping[str, Any]],
    next_item_disclosure: Mapping[str, Any],
    next_sibling_disclosure: Mapping[str, Any],
    deferred_fact: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one ordered, machine-readable decision for the next action."""

    candidates: list[dict[str, Any]] = []
    current_object_pointers = {
        str(row["business_value_pointer"]).rsplit("/", 1)[0]
        for row in nested_container_disclosures
        if isinstance(row.get("business_value_pointer"), str)
        and "/" in str(row["business_value_pointer"])
    }
    current_object_pointer = (
        next(iter(current_object_pointers))
        if len(current_object_pointers) == 1
        else None
    )
    if branch_continuation:
        candidates.append(
            {
                "candidate": "branch_disclosure",
                "condition": "current_business_value_requires_disclosed_branch",
                "command_pointer": "/continuation/branch_disclosure",
            }
        )
    if nested_container_disclosures:
        candidates.append(
            {
                "candidate": "nested_container_disclosures",
                "condition": (
                    "first_business_present_member_by_queue_index_on_exact_current_object"
                ),
                "business_value_pointers": [
                    str(row["business_value_pointer"])
                    for row in nested_container_disclosures
                    if isinstance(row.get("business_value_pointer"), str)
                ],
                "command_pointer": (
                    "/continuation/nested_container_disclosures/<selected>/argv"
                ),
            }
        )
    if next_item_disclosure:
        candidates.append(
            {
                "candidate": "next_item_disclosure",
                "condition": "next_business_present_item_by_ascending_index",
                "command_pointer": (
                    "/continuation/next_item_disclosure/argv_by_shape/"
                    "<exact-business-shape>"
                ),
            }
        )

    sibling = next_sibling_disclosure.get("next_sibling_disclosure", {})
    nested_sibling = (
        isinstance(sibling, Mapping) and sibling.get("is_next_command") is True
    )
    sibling_candidate = (
        {
            "candidate": "next_sibling_disclosure",
            "condition": (
                "current_object_has_no_business_present_nested_member_and_"
                "business_value_pointer_is_present"
            ),
            "business_value_pointer": sibling.get("business_value_pointer"),
            "command_pointer": (
                "/continuation/next_sibling_disclosure/argv_by_shape/"
                "<exact-business-shape>"
            ),
        }
        if isinstance(sibling, Mapping) and sibling
        else None
    )
    if nested_sibling and sibling_candidate is not None:
        candidates.append(sibling_candidate)
    if deferred_fact:
        candidates.append(
            {
                "candidate": "deferred_fact_queue",
                "condition": (
                    "no_earlier_business_present_disclosure_for_exact_current_object"
                ),
                "action": (
                    "return_to_outermost_disclosed_root_then_drain_"
                    "response_tree_preorder"
                ),
                "start_at": "outermost_disclosed_root_response",
                "first_command_pointer": "/continuation/deferred_fact/argv",
                "batch_facts": (
                    f"current_root_only_next_up_to_{MAX_TYPED_ACTIONS_PER_APPLY}_"
                    "deferred_facts_in_queue_order"
                ),
                "first_fact_only": "invalid",
            }
        )
    if not nested_sibling and sibling_candidate is not None:
        candidates.append(sibling_candidate)

    return {
        "next_command_decision": {
            "business_presence_source": "current_user_business_request",
            **(
                {"current_business_object_pointer": current_object_pointer}
                if current_object_pointer is not None
                else {}
            ),
            "schema_members_are_not_business_facts": True,
            "candidate_without_its_exact_business_pointer": "forbidden",
            "conditional_candidates_do_not_block_when_absent": True,
            **(
                {
                    "preview_construction_boundary": {
                        "complete": False,
                        "confirmation_before_preview": "invalid",
                        "final_response_before_preview": "invalid",
                    }
                }
                if draft_shape
                else {}
            ),
            **(
                {
                    "deferred_fact_root_barrier": {
                        "outermost_disclosed_root_pointer": (
                            outermost_disclosed_root_pointer
                        ),
                        "start_at_response_with_current_value_pointer": (
                            outermost_disclosed_root_pointer
                        ),
                        "descendant_facts_before_root_parent_and_child_facts": (
                            "forbidden"
                        ),
                    }
                }
                if outermost_disclosed_root_pointer is not None
                else {}
            ),
            **(
                {
                    "if_current_business_object_is_declared_leaf": {
                        "condition": (
                            "current_business_object_has_no_properties_"
                            "references_or_children"
                        ),
                        "nested_container_disclosures": "forbidden",
                        "next_action": (
                            "deferred_fact_queue_then_next_sibling_disclosure"
                        ),
                    }
                }
                if nested_container_disclosures
                else {}
            ),
            "evaluate_in_order": candidates,
            "first_true_candidate_is_the_only_next_action": True,
            **(
                {
                    "draft_check_or_cancel_with_remaining_candidate_or_deferred_fact": (
                        "invalid"
                    )
                }
                if draft_shape
                else {
                    "terminal_command_with_remaining_candidate_or_deferred_fact": (
                        "invalid"
                    )
                }
            ),
        }
    }


def dispatch_offline_command(args: argparse.Namespace, *, env: Mapping[str, str]) -> dict[str, Any]:
    """Run catalog commands without requiring a WAAPI port or live Wwise."""

    if args.command == "topic-schema":
        (version,) = resolve_catalog_versions(args, env=env)
        options = topic_options_contract(version, args.api)
        match = topic_match_contract(version, args.api)
        payload = {
            "contract": "waapi-skill.typed-topic-input/v1",
            "ok": True,
            "status": "ok",
            "command": "topic-schema",
            "offline": True,
            "version": version,
            "topic": args.api,
            "bounds": {
                "stdout_utf8_bytes": MAX_TOPIC_SCHEMA_GATEWAY_RESULT_BYTES,
            },
            "continuation": {
                "subcommands": ["wait-topic", "stream-topic"],
                "fact_selection": (
                    "row action; present only when empty; disclose-* rows only"
                ),
                "wait_argv_prefix": [
                    "--timeout",
                    "<positive-seconds>",
                    "wait-topic",
                    args.api,
                    "--event-count",
                    "<exact-count:1..64>",
                    "--options-schema-digest",
                    options.schema_digest,
                    "--match-schema-digest",
                    match.schema_digest,
                ],
                "fact_order": "options ordered; match facts commute",
                "bind": {
                    "--options-schema-digest": options.schema_digest,
                    "--match-schema-digest": match.schema_digest,
                },
                "fact_argv": {
                    "prefixes": ["option", "match"],
                    "templates": {
                        "set": "--<prefix>-set <handle> <type> <value>",
                        "append": "--<prefix>-append <handle> <type> <value>",
                        "present": "--<prefix>-present <handle>",
                        "choose": "--<prefix>-choose <handle> <choice_handle>",
                        "choose_dynamic": (
                            "--<prefix>-choose-dynamic <handle> <key> <choice_handle>"
                        ),
                        "map_put": (
                            "--<prefix>-map-put <handle> <key> <type> <value>"
                        ),
                    },
                },
                "lifecycle": {
                    "wait-topic": "bounded; unsubscribe",
                    "stream-topic": "cancel/timeout; unsubscribe",
                },
            },
            "options": typed_topic_contract_payload(options),
            "event_match": typed_topic_contract_payload(match),
        }
        final_payload = attach_gateway_session_context(
            payload,
            args=args,
            env=env,
        )
        observed = gateway_json_document_size(
            final_payload,
            stop_after_bytes=MAX_TOPIC_SCHEMA_GATEWAY_RESULT_BYTES,
        )
        if observed > MAX_TOPIC_SCHEMA_GATEWAY_RESULT_BYTES:
            # Qualified duplicate-name paths are a readability aid over the
            # already lossless parent_row lineage.  Near-ceiling Topics keep
            # that canonical lineage and omit only this redundant aid.
            for section_name in ("event_match", "options"):
                section = payload.get(section_name)
                fields = section.get("fields") if isinstance(section, Mapping) else None
                if isinstance(fields, dict):
                    fields.pop("duplicate_name_paths", None)
            final_payload = attach_gateway_session_context(
                payload,
                args=args,
                env=env,
            )
            observed = gateway_json_document_size(
                final_payload,
                stop_after_bytes=MAX_TOPIC_SCHEMA_GATEWAY_RESULT_BYTES,
            )
        if observed > MAX_TOPIC_SCHEMA_GATEWAY_RESULT_BYTES:
            raise ValueError(
                "Typed Topic schema exceeds its fixed 32 KiB public output ceiling"
            )
        return payload
    if args.command in {"request-schema", "request-map-container", "request-array-item"}:
        versions = resolve_catalog_versions(args, env=env)
        if len(versions) != 1:
            raise GatewayInputError(f"{args.command} requires one exact Wwise version")
        contract = public_typed_contract(versions[0], args.api)
        if args.command == "request-schema" and args.api.startswith("undo-child:"):
            raise GatewayInputError(
                "Undo Group child contracts use undo-child-schema as their single schema entry."
            )
        if args.command == "request-schema" and args.api in {
            STRUCTURED_TYPED_QUERY_OPERATION,
            ADVANCED_TYPED_QUERY_OPERATION,
        }:
            raise GatewayInputError(
                "Typed object queries use query-schema as their single schema entry."
            )
        if args.command == "request-schema" and args.api.startswith(
            (TOPIC_OPTIONS_OPERATION_PREFIX, TOPIC_MATCH_OPERATION_PREFIX)
        ):
            raise GatewayInputError(
                "Typed Topics use topic-schema <topic-uri> as their single schema entry."
            )
        if args.command == "request-schema":
            dedicated_zero = {
                "ak.wwise.debug.restartWaapiServers": "debug.restartWaapiServers",
                "ak.wwise.debug.testAssert": "debug.testAssert",
                "ak.wwise.debug.testCrash": "debug.testCrash",
            }.get(args.api)
            if dedicated_zero is not None:
                raise GatewayInputError(
                    "This dangerous host control uses operation-schema "
                    f"{dedicated_zero} as its single typed entry."
                )
        if args.command == "request-schema":
            return contract.as_gateway_payload()
        draft_shape = contract.as_gateway_payload()["input_shape"] == "draft"
        undo_child_shape = args.api.startswith("undo-child:")
        query_shape = args.api in {
            STRUCTURED_TYPED_QUERY_OPERATION,
            ADVANCED_TYPED_QUERY_OPERATION,
        }
        topic_prefix = (
            "option"
            if args.api.startswith(TOPIC_OPTIONS_OPERATION_PREFIX)
            else "match"
            if args.api.startswith(TOPIC_MATCH_OPERATION_PREFIX)
            else None
        )
        if args.schema_digest is None and args.parent_schema_token is None:
            raise GatewayInputError(
                "A root typed container requires its exact schema digest"
            )
        if (
            args.schema_digest is not None
            and args.schema_digest != contract.schema_digest
        ):
            raise GatewayInputError("Typed request schema digest is stale")
        parent_handle = (
            args.map_handle
            if args.command == "request-map-container"
            else args.array_handle
        )
        parent_lineage = parse_typed_schema_lineage_token(
            contract,
            parent_handle=parent_handle,
            token=args.parent_schema_token,
        )
        parent_schema = parent_lineage[0] if parent_lineage is not None else None
        parent_section = parent_lineage[1] if parent_lineage is not None else None
        if args.command == "request-map-container":
            map_choices = dynamic_map_container_choices(
                contract,
                map_handle=args.map_handle,
                key=args.key,
                shape=args.shape,
                parent_schema=parent_schema,
                parent_section=parent_section,
            )
            if len(map_choices) > 1 and args.choice_handle is None:
                return {
                    "contract": "waapi-skill.typed-map-container-choices/v1",
                    "ok": True,
                    "status": "choice_required",
                    "command": args.command,
                    "version": contract.version,
                    "uri": contract.uri,
                    "schema_digest": contract.schema_digest,
                    "map_handle": args.map_handle,
                    "key": args.key,
                    "shape": args.shape,
                    "choices": [
                        {
                            "handle": choice_handle,
                            "accepted_type": str(variant.get("type")),
                            "required_keys": list(variant.get("required", ())),
                        }
                        for choice_handle, _variant_index, variant in map_choices
                    ],
                    "continuation": {
                        "subcommand": "request-map-container",
                        "choice_flag": "--choice-handle <choice_handle>",
                        "choice_argv": [
                            "request-map-container",
                            args.api,
                            *_container_schema_binding_argv(
                                contract,
                                parent_schema_token=args.parent_schema_token,
                            ),
                            "--map-handle",
                            args.map_handle,
                            "--key",
                            args.key,
                            "--shape",
                            args.shape,
                            *(
                                ["--parent-schema-token", args.parent_schema_token]
                                if args.parent_schema_token is not None
                                else []
                            ),
                            "--choice-handle",
                            "<choice_handle_from_this_response>",
                        ],
                    },
                }
            child_handle = dynamic_map_entry_handle(
                contract,
                map_handle=args.map_handle,
                key=args.key,
                shape=args.shape,
                choice_handle=args.choice_handle,
                parent_schema=parent_schema,
                parent_section=parent_section,
            )
            key: str | int = args.key
            fact = ["--map-put", args.map_handle, args.key, args.shape, child_handle]
        else:
            array_choices = (
                dynamic_array_item_choices(
                    contract,
                    array_handle=args.array_handle,
                    index=args.index,
                    shape=args.shape,
                    parent_schema=parent_schema,
                    parent_section=parent_section,
                )
                if args.array_handle in contract.fields_by_handle
                or parent_schema is not None
                else ()
            )
            if len(array_choices) > 1 and args.choice_handle is None:
                return {
                    "contract": "waapi-skill.typed-array-item-choices/v1",
                    "ok": True,
                    "status": "choice_required",
                    "command": args.command,
                    "version": contract.version,
                    "uri": contract.uri,
                    "schema_digest": contract.schema_digest,
                    "array_handle": args.array_handle,
                    "index": args.index,
                    "shape": args.shape,
                    "choices": [
                        {
                            "handle": choice_handle,
                            "accepted_type": str(variant.get("type")),
                            "required_keys": list(variant.get("required", ())),
                        }
                        for choice_handle, _variant_index, variant in array_choices
                    ],
                    "continuation": {
                        "subcommand": "request-array-item",
                        "choice_flag": "--choice-handle <choice_handle>",
                        "choice_argv": [
                            "request-array-item",
                            args.api,
                            *_container_schema_binding_argv(
                                contract,
                                parent_schema_token=args.parent_schema_token,
                            ),
                            "--array-handle",
                            args.array_handle,
                            "--index",
                            str(args.index),
                            "--shape",
                            args.shape,
                            *(
                                ["--parent-schema-token", args.parent_schema_token]
                                if args.parent_schema_token is not None
                                else []
                            ),
                            "--choice-handle",
                            "<choice_handle_from_this_response>",
                        ],
                    },
                }
            child_handle = dynamic_array_item_handle(
                contract,
                array_handle=args.array_handle,
                index=args.index,
                shape=args.shape,
                choice_handle=args.choice_handle,
                parent_schema=parent_schema,
                parent_section=parent_section,
            )
            key = args.index
            fact = ["--append", args.array_handle, args.shape, child_handle]
        child_contract = dynamic_container_disclosure(
            contract,
            parent_handle=parent_handle,
            key=str(key),
            shape=args.shape,
            child_handle=child_handle,
            member_key=args.member_key,
            parent_schema=parent_schema,
            parent_section=parent_section,
            choice_handle=getattr(args, "choice_handle", None),
        )
        child_contract.pop("schema_lineage")
        _bind_dynamic_branch_facts(
            child_contract,
            child_handle=child_handle,
            draft_shape=draft_shape,
            undo_child_shape=undo_child_shape,
            query_shape=query_shape,
            topic_prefix=topic_prefix,
        )
        child_contract["fact_literal_policy"] = {
            "copy_handles_and_choice_handles_exactly": True,
            "placeholder_or_added_punctuation": "invalid",
            "business_value_placeholders_must_be_replaced": True,
        }
        lineage_token = typed_schema_lineage_token(
            contract,
            child_handle=child_handle,
            parent_token=args.parent_schema_token,
            parent_handle=parent_handle,
            key=str(key),
            shape=args.shape,
            choice_handle=getattr(args, "choice_handle", None),
        )
        try:
            current_business_value_pointer = typed_schema_lineage_business_pointer(
                contract,
                child_handle=child_handle,
                token=lineage_token,
            )
            outermost_disclosed_root_pointer = (
                typed_schema_lineage_root_business_pointer(
                    contract,
                    child_handle=child_handle,
                    token=lineage_token,
                )
            )
        except TypedRequestError:
            # Legacy unlineaged dynamic parents remain usable for their bounded
            # current response, but cannot claim a canonical business pointer.
            current_business_value_pointer = None
            outermost_disclosed_root_pointer = None
        nested_container_disclosures = _fixed_nested_container_disclosures(
            args,
            contract=contract,
            child_handle=child_handle,
            child_contract=child_contract,
            lineage_token=lineage_token,
        )
        if current_business_value_pointer is not None:
            scalar_member_facts = child_contract.get("fixed_scalar_member_facts")
            if isinstance(scalar_member_facts, list):
                for row in scalar_member_facts:
                    if not isinstance(row, dict):
                        continue
                    member_key = row.get("key")
                    if not isinstance(member_key, str):
                        continue
                    escaped_key = member_key.replace("~", "~0").replace("/", "~1")
                    row["business_value_pointer"] = (
                        f"{current_business_value_pointer}/{escaped_key}"
                    )
                    row["condition"] = (
                        "current_business_request_contains_member"
                    )
            for row in nested_container_disclosures:
                key_value = str(row["key"]).replace("~", "~0").replace("/", "~1")
                row["business_value_pointer"] = (
                    f"{current_business_value_pointer}/{key_value}"
                )
        _compact_fixed_scalar_member_facts(child_contract)
        branch_continuation = _dynamic_branch_disclosure_continuation(
            args,
            contract=contract,
            child_handle=child_handle,
            child_contract=child_contract,
            lineage_token=lineage_token,
        )
        next_item_disclosure = _next_array_item_disclosure(
            args,
            contract=contract,
            child_handle=child_handle,
            lineage_token=lineage_token,
        )
        next_sibling_disclosure = _next_array_sibling_disclosure(
            args,
            contract=contract,
            parent_schema=parent_schema,
            parent_section=parent_section,
            current_business_value_pointer=current_business_value_pointer,
        )
        deferred_fact = _deferred_dynamic_fact_payload(
            fact,
            draft_shape=draft_shape,
            undo_child_shape=undo_child_shape,
            query_shape=query_shape,
            topic_prefix=topic_prefix,
        )
        if "deferred_fact" in deferred_fact:
            blocked_by: list[str] = []
            if args.parent_schema_token is not None:
                blocked_by.extend(
                    [
                        "ancestor_deferred_parent_facts",
                        "ancestor_child_contract_facts",
                    ]
                )
            if next_item_disclosure:
                blocked_by.extend(
                    ["next_item_disclosure", "all_descendant_disclosures"]
                )
            if next_sibling_disclosure:
                sibling = next_sibling_disclosure["next_sibling_disclosure"]
                if sibling.get("is_next_command") is True:
                    blocked_by.extend(
                        ["next_sibling_disclosure", "all_descendant_disclosures"]
                    )
            if blocked_by:
                deferred_fact["deferred_fact"]["blocked_by"] = blocked_by
        response = {
            "contract": "waapi-skill.typed-container-handle/v1",
            "ok": True,
            "status": "ok",
            "command": args.command,
            "version": contract.version,
            "uri": contract.uri,
            "schema_digest": contract.schema_digest,
            "parent_handle": parent_handle,
            "key": key,
            "shape": args.shape,
            "handle": child_handle,
            **(
                {
                    "business_value_scope": {
                        "current_value_pointer": current_business_value_pointer,
                        "outermost_disclosed_root_pointer": (
                            outermost_disclosed_root_pointer
                        ),
                        "current_value_only": True,
                        "unrelated_prompt_objects_do_not_satisfy_member_conditions": True,
                    }
                }
                if current_business_value_pointer is not None
                else {}
            ),
            "schema_lineage_token": lineage_token,
            "schema_lineage_authority": {
                "returned_token_scope": (
                    "direct_descendants_of_this_handle_only"
                ),
                "returned_token_handle": child_handle,
                "not_valid_for": "sibling_items_in_parent_array",
                **(
                    {
                        "sibling_item_parent": {
                            "array_handle": parent_handle,
                            "parent_schema_token": args.parent_schema_token,
                            "copy_parent_schema_token_exactly": True,
                            "index_source": (
                                "next_business_present_sibling_index"
                            ),
                            "disclosure_condition": (
                                "current_business_request_contains_that_index"
                            ),
                            "allowed_after": (
                                "current_root_fact_apply_success"
                            ),
                            "absent_index_forbidden": True,
                            "is_next_command": False,
                        }
                    }
                    if args.command == "request-array-item"
                    and args.parent_schema_token is not None
                    else {}
                ),
            },
            "continuation": {
                **_dynamic_next_command_decision(
                    draft_shape=(
                        (draft_shape or undo_child_shape)
                        and not query_shape
                        and topic_prefix is None
                    ),
                    outermost_disclosed_root_pointer=(
                        outermost_disclosed_root_pointer
                    ),
                    branch_continuation=branch_continuation,
                    nested_container_disclosures=nested_container_disclosures,
                    next_item_disclosure=next_item_disclosure,
                    next_sibling_disclosure=next_sibling_disclosure,
                    deferred_fact=deferred_fact,
                ),
                "request_wide_order": {
                    "phase": "dynamic_disclosure",
                    "root_boundary": (
                        "finish_current_root_disclosures_and_facts_before_next_root"
                    ),
                    "traversal": "response_tree_preorder",
                    "nested_member_order": "schema_property_order",
                    "child_fact_order": "child_contract_schema_order",
                    "deferred_fact_queue": {
                        "traversal": "response_tree_preorder",
                        "node_steps": [
                            "deferred_parent_fact",
                            "child_contract_facts",
                            "descendant_response_nodes",
                        ],
                        "forbidden": [
                            "descendant_fact_before_current_node_parent_or_child_facts",
                            "next_sibling_disclosure_before_current_root_facts",
                            "one_fact_apply_batch_spanning_sibling_roots",
                        ],
                    },
                    "this_handle_is_not_a_complete_request": True,
                },
                "subcommand": (
                    "query-object"
                    if query_shape
                    else "topic-input-fact" if topic_prefix is not None
                    else "draft-apply" if undo_child_shape
                    else "draft-apply" if draft_shape else "typed-call"
                ),
                **(
                    {
                        "draft_fact_execution": {
                            "prefix_source": (
                                "latest_draft_response.next_action_binding."
                                "fixed_argv_prefix"
                            ),
                            "batch_scope": "current_root_only_next_deferred_facts",
                            "complete_action_groups_in_queue_order": True,
                            "maximum_actions": MAX_TYPED_ACTIONS_PER_APPLY,
                            "copy_returned_handles_exactly": True,
                        }
                    }
                    if (draft_shape or undo_child_shape)
                    and not query_shape
                    and topic_prefix is None
                    else {}
                ),
                **next_item_disclosure,
                **next_sibling_disclosure,
                **deferred_fact,
                **(
                    {
                        "valid_subscription_subcommands": [
                            "wait-topic",
                            "stream-topic",
                        ]
                    }
                    if topic_prefix is not None
                    else {}
                ),
                **(
                    {
                        "nested_container_disclosures": (
                            nested_container_disclosures
                        ),
                        "nested_container_order": (
                            "branch_then_schema_members_then_descendants_then_facts"
                            if branch_continuation
                            else "schema_members_then_descendants_then_facts"
                        ),
                    }
                    if nested_container_disclosures
                    else {}
                ),
                **branch_continuation,
                **_next_nested_disclosure_selector(
                    nested_container_disclosures,
                    next_sibling_disclosure=next_sibling_disclosure,
                ),
            },
            # Keep the control-flow contract before the potentially large
            # schema table. Fresh agents must see the exact next-action
            # decision even when a shell tool renders only an output prefix.
            "child_contract": child_contract,
        }
        if draft_shape or undo_child_shape:
            read_only_draft = (
                draft_shape
                and not undo_child_shape
                and args.api.startswith("ak.")
                and contract.effect == "read"
            )
            response["construction_state"] = {
                "complete": False,
                "disclosure_replay_allowed": False,
                "next_phase": (
                    "finish_dynamic_disclosures_then_apply_deferred_facts"
                ),
                "completion_boundary": (
                    "draft-check" if read_only_draft else "draft-check_then_preview"
                ),
                "construction_boundary": (
                    operation_draft_construction_boundary(
                        read_only=read_only_draft
                    )
                ),
            }
        return response
    if args.command == "draft-start":
        request_version = resolve_operation_schema_version(args, env=env)
        if request_version is None:
            raise GatewayInputError(
                "draft-start requires an explicit or configured Wwise version."
            )
        schema_digest = operation_draft_schema_digest(
            args.operation, request_version
        )
        composer_digest = operation_composer_digest(
            args.operation,
            request_version,
        )
        store = OperationDraftStore(
            resolve_transaction_state_directory(args, env=env)
        )
        started = store.start(
            operation=args.operation,
            version=request_version,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
        )
        payload = operation_draft_payload(args.command, started.record)
        payload["task_authority"] = started.task_authority
        return payload
    if args.command == "draft-apply":
        store = OperationDraftStore(
            resolve_transaction_state_directory(args, env=env)
        )
        inspected = store.inspect(
            args.draft_id,
            task_authority=args.task_authority,
        )
        schema_digest = operation_draft_schema_digest(
            inspected.operation, inspected.version
        )
        composer_digest = operation_composer_digest(
            inspected.operation,
            inspected.version,
        )
        parsed_actions = parse_operation_draft_cli_actions(args)
        record = store.apply_actions(
            args.draft_id,
            task_authority=args.task_authority,
            expected_revision=args.expected_revision,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
            actions=parsed_actions,
        )
        return operation_draft_payload(
            args.command,
            record,
            compact_actions=parsed_actions if args.compact else None,
            prior_record=inspected if args.compact else None,
            task_authority=args.task_authority,
        )
    if args.command in {"draft-inspect", "draft-cancel"}:
        store = OperationDraftStore(
            resolve_transaction_state_directory(args, env=env)
        )
        if args.command == "draft-inspect":
            record = store.inspect(
                args.draft_id,
                task_authority=args.task_authority,
            )
        else:
            record = store.cancel(
                args.draft_id,
                task_authority=args.task_authority,
                expected_revision=args.expected_revision,
            )
        return operation_draft_payload(
            args.command,
            record,
        )

    if args.command == "config-show":
        return config_result_payload("config-show", load_gateway_config(env))
    if args.command == "config-set":
        changes = parse_config_set_changes(args)
        if args.reset:
            try:
                external_path = resolve_external_config_path(env, skill_root=SKILL_ROOT)
            except ValueError as exc:
                raise GatewayInputError(f"Public WAAPI Skill config path is invalid: {exc}") from exc
            config = SkillConfig(SKILL_ROOT)
            resolution = ResolvedSkillConfig(
                config=config,
                source="reset_defaults",
                external_path=external_path,
                legacy_path=config.config_path,
                legacy_fallback_used=False,
            )
        else:
            resolution = load_gateway_config(env)
        config = resolution.config
        for field, value in changes.items():
            setattr(config, field, value)
        try:
            config.save(resolution.external_path)
        except (OSError, ValueError) as exc:
            raise GatewayInputError(f"Could not save public WAAPI Skill config: {exc}") from exc
        saved = load_gateway_config(env)
        return config_result_payload(
            "config-set",
            saved,
            changed_fields=tuple(changes),
            migrated_from_legacy=resolution.legacy_fallback_used,
            reset=bool(args.reset),
        )

    if args.command == "capabilities":
        catalog = CapabilityCatalog()
        versions = resolve_catalog_versions(args, env=env)
        profile = args.profile
        if args.limit < 0:
            raise GatewayInputError("--limit must be zero or greater")
        selected = []
        for version in versions:
            selected.extend(
                catalog.select_for_profile(
                    version,
                    profile=profile,
                    category=args.category,
                    item_type=args.item_type,
                    semantic_family=args.family,
                    preferred_route=args.route,
                    query=args.query,
                )
            )
        total_matches = len(selected)
        visible = selected[: args.limit] if args.limit else selected
        payload: dict[str, Any] = {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "capabilities",
            "offline": True,
            "profile": profile,
            "versions": list(versions),
            "summary": catalog.summary_for_profile(
                versions,
                profile=profile,
            ),
            "filters": {
                "profile": profile,
                "category": args.category,
                "item_type": args.item_type,
                "semantic_family": args.family,
                "preferred_route": args.route,
                "query": args.query,
            },
            "match_count": total_matches,
            "returned_count": 0 if args.summary_only else len(visible),
            "truncated": (not args.summary_only) and len(visible) < total_matches,
        }
        if not args.summary_only:
            payload["capabilities"] = [
                entry.as_dict(detail=False) if args.detail else entry.as_compact_dict()
                for entry in visible
            ]
        return payload
    if args.command == "describe":
        catalog = CapabilityCatalog()
        versions = resolve_catalog_versions(args, env=env)
        profile = args.profile
        availability: dict[str, Any] = {}
        found = 0
        for version in versions:
            try:
                entry = catalog.describe_for_profile(
                    version,
                    args.api,
                    profile=profile,
                )
            except CapabilityNotFoundError:
                availability[version] = {
                    "available": False,
                    "status": "absent_from_version_manifest",
                    "fallback_allowed": False,
                }
            else:
                found += 1
                version_row: dict[str, Any] = {
                    "available": True,
                    "capability": entry.as_dict(detail=bool(args.full_schema)),
                }
                availability[version] = version_row
        if found == 0:
            raise CapabilityNotFoundError(
                f"WAAPI URI {args.api!r} is not reflected by requested versions: {', '.join(versions)}"
            )
        return {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "describe",
            "offline": True,
            "profile": profile,
            "api": args.api,
            "versions": list(versions),
            "schema_detail": "full" if args.full_schema else "summary",
            "availability": availability,
        }
    if args.command == "object-types":
        if (
            isinstance(args.limit, bool)
            or not isinstance(args.limit, int)
            or not 1 <= args.limit <= MAX_OBJECT_TYPE_SEARCH_RESULTS
        ):
            raise GatewayInputError(
                "object-types --limit must be an integer from 1 to "
                f"{MAX_OBJECT_TYPE_SEARCH_RESULTS}"
            )
        if args.summary_only and (
            args.query is not None or args.object_type is not None
        ):
            raise GatewayInputError(
                "object-types --summary-only cannot be combined with "
                "--query or --object-type because summary counts describe the "
                "complete packaged catalog"
            )
        versions = resolve_catalog_versions(args, env=env)
        store = ObjectTypeCatalogStore()
        catalogs: dict[str, Any] = {}
        total_matches = 0
        total_returned = 0
        for version in versions:
            try:
                catalog = store.load(version)
                matches = (
                    ()
                    if args.summary_only
                    else catalog.search(
                        args.query,
                        object_type=args.object_type,
                        limit=args.limit,
                    )
                )
            except (MetadataCatalogError, MetadataCatalogMissingError) as exc:
                raise GatewayInputError(
                    f"Packaged object-type metadata is invalid for Wwise "
                    f"{version}: {exc}"
                ) from exc
            if args.summary_only:
                match_count: int | None = None
                returned = 0
            else:
                # ``search`` deliberately returns a bounded page.  Report
                # whether the page is full without loading the complete
                # catalog into the agent response.
                match_count = len(matches)
                returned = len(matches)
                total_matches += match_count
                total_returned += returned
            row: dict[str, Any] = {
                **catalog.as_summary(),
                "filters": {
                    "query": args.query,
                    "object_type": args.object_type,
                },
                "returned_count": returned,
            }
            if match_count is not None:
                row["match_count_in_bounded_page"] = match_count
                row["page_full"] = match_count == args.limit
                row["types"] = [record.as_dict() for record in matches]
            catalogs[version] = row
        return {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "object-types",
            "offline": True,
            "versions": list(versions),
            "summary_only": bool(args.summary_only),
            "returned_count": total_returned,
            "match_count_in_bounded_pages": total_matches,
            "catalogs": catalogs,
        }
    if args.command == "query-schema":
        versions = resolve_catalog_versions(args, env=env)
        if len(versions) == 1:
            return {
                **typed_query_schema_payload(versions[0], advanced=args.advanced),
                "offline": True,
                "versions": list(versions),
            }
        return {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "query-schema",
            "offline": True,
            "query_layer": (
                "advanced-native-waql" if args.advanced else "structured-builder"
            ),
            "query_contract": (
                ADVANCED_QUERY_CONTRACT if args.advanced else STRUCTURED_QUERY_CONTRACT
            ),
            "versions": list(versions),
            "schemas": {
                version: (
                    advanced_query_schema(version=version)
                    if args.advanced
                    else structured_query_schema(version=version)
                )
                for version in versions
            },
            "contracts": {
                version: typed_query_schema_payload(
                    version, advanced=args.advanced
                )
                for version in versions
            },
            "boundary": (
                {
                    "fixed_api": OBJECT_GET_URI,
                    "read_only": True,
                    "native_waql_accepted": True,
                    "gateway_appends_final_take": True,
                    "all_results_available": False,
                    "arbitrary_uri_args_or_options_accepted": False,
                    "gateway_json_input_bytes": MAX_GATEWAY_JSON_INPUT_BYTES,
                    "gateway_result_bytes": MAX_GATEWAY_RESULT_JSON_BYTES,
                    "version_specific_syntax_validated_by": "connected Wwise",
                    "fallback_or_retry_on_invalid_query": False,
                }
                if args.advanced
                else {
                    "raw_waql_accepted": False,
                    "raw_expression_accepted": False,
                    "result_limit_required_for": [
                        "broad sources",
                        "multiple object sources",
                        "select transforms",
                    ],
                    "deferred_syntax": [
                        "skip",
                        "orderby",
                        "distinct",
                        "regular-expression literals",
                        "WAQL 2.0 list functions",
                    ],
                    "advanced_fallback": {
                        "available": True,
                        "disclose_with": "query-schema --advanced",
                        "execute_with": "query-object --typed-advanced",
                        "use_only_when": (
                            "the structured schema cannot express the requested "
                            "read-only WAQL construct"
                        ),
                    },
                }
            ),
        }
    if args.command == "operations":
        operations: list[dict[str, Any]] = []
        for spec in list_operation_specs():
            if spec.name == "waapi.call":
                continue
            if not args.detail:
                operations.append(spec.as_compact_dict())
                continue
            modes = {
                version: operation_input_mode(spec.name, version)
                for version in spec.supported_versions
            }
            if COMPOSER_INPUT_MODE not in modes.values():
                if INLINE_TYPED_INPUT_MODE in modes.values():
                    projection = composer_operation_projection(spec, version=None)
                    projection["input_modes_by_version"] = modes
                    operations.append(projection)
                else:
                    operations.append(spec.as_dict())
                continue
            projection = composer_operation_projection(spec, version=None)
            projection["composer_contracts_by_version"] = {
                version: operation_composer_input_contract(
                    spec.name,
                    version,
                    inventory=True,
                )
                for version, mode in modes.items()
                if mode == COMPOSER_INPUT_MODE
            }
            operations.append(projection)
        return {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "operations",
            "offline": True,
            "count": len(operations),
            "implemented_count": sum(item["implemented"] is True for item in operations),
            "operations": operations,
        }
    if args.command == "undo-child-schema":
        (version,) = resolve_catalog_versions(args, env=env)
        from wwise_waapi.typed_operations import compound_child_request_contract

        contract = compound_child_request_contract(args.child_operation, version)
        return {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "undo-child-schema",
            "offline": True,
            "child_operation": args.child_operation,
            "version": version,
            "typed_request": contract.as_gateway_payload(),
            "fact_actions": [
                "add_child_typed_fact",
                "correct_child_typed_fact",
                "remove_child_typed_fact",
            ],
        }
    if args.command == "operation-schema":
        if args.operation == "waapi.call":
            raise OperationContractError(
                "INTERNAL_CANONICAL_OPERATION",
                "waapi.call is an internal canonical transaction representation; "
                "use request-schema with the exact reflected WAAPI URI.",
                details={
                    "operation": "waapi.call",
                    "next_command": "request-schema <exact-waapi-uri>",
                },
            )
        spec = describe_operation(args.operation)
        request_version = resolve_operation_schema_version(args, env=env)
        input_mode = (
            operation_input_mode(spec.name, request_version)
            if request_version in spec.supported_versions
            else None
        )
        normal_composer = input_mode == COMPOSER_INPUT_MODE
        normal_inline = input_mode == INLINE_TYPED_INPUT_MODE
        unsupported_version = (
            request_version is not None
            and request_version not in spec.supported_versions
        )
        if unsupported_version:
            operation_projection = spec.as_compact_dict()
            operation_projection.pop("required_arguments", None)
            operation_projection.pop("optional_arguments", None)
            operation_projection["availability"] = {
                "status": "unsupported_version",
                "requested_version": request_version,
                "supported_versions": list(spec.supported_versions),
            }
        else:
            operation_projection = (
                composer_operation_projection(spec, version=request_version)
                if normal_composer or normal_inline
                else spec.as_dict(version=request_version)
            )
        payload = {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok" if spec.implemented else "unsupported_boundary",
            "command": args.command,
            "offline": True,
            "operation": operation_projection,
        }
        if normal_composer and request_version is not None:
            payload["composer"] = operation_composer_input_contract(
                spec.name,
                request_version,
            )
        if normal_inline and request_version is not None:
            operation_projection["input_mode"] = INLINE_TYPED_INPUT_MODE
            payload["typed_operation"] = inline_operation_contract(
                spec.name,
                request_version,
            )
        return payload
    if args.command in {"transaction-show", "confirm", "reject"}:
        store = resolve_transaction_store(args, env=env)
        transaction_id = args.transaction_id
        if args.command == "transaction-show":
            snapshot = store.load_snapshot(transaction_id)
            record = snapshot.record
            preview = snapshot.preview
            events = snapshot.events
            payload = {
                "contract": GATEWAY_RESULT_CONTRACT,
                "ok": True,
                "status": "ok",
                "command": "transaction-show",
                "offline": True,
                "transaction_id": transaction_id,
                "state": record.state.value,
                "artifact_hash": preview.artifact_hash,
            }
            if args.summary_only:
                try:
                    payload.update(transaction_show_summary(preview.artifact, events))
                except GatewayResultShapeError as exc:
                    exc.details.update(
                        {
                            "transaction_id": transaction_id,
                            "state": record.state.value,
                            "artifact_hash": preview.artifact_hash,
                        }
                    )
                    raise
            else:
                payload.update({"artifact": preview.artifact, "events": list(events)})
            if record.state is TransactionState.AWAITING_CONFIRMATION:
                confirmation_token = snapshot.confirmation_token
                if confirmation_token is None:
                    raise GatewayInputError(
                        "awaiting transaction snapshot did not produce a confirmation token"
                    )
                # Keep the actionable continuation after the complete review
                # body.  If a large result is truncated before the immutable
                # request or event evidence is visible, the confirm argv is
                # not exposed early enough to invite an unsafe continuation.
                payload["confirmation"] = {
                    "contract": TRANSACTION_CONFIRMATION_BINDING_CONTRACT,
                    "token": confirmation_token,
                    "binding": {
                        "material_contract": CONFIRMATION_TOKEN_MATERIAL_CONTRACT,
                        "transaction_id": transaction_id,
                        "artifact_hash": preview.artifact_hash,
                        "state": record.state.value,
                        "event_sequence": record.event_sequence,
                        "last_event_hash": record.last_event_hash,
                    },
                }
                payload["next_command"] = transaction_next_command(
                    "confirm",
                    [
                        "confirm",
                        transaction_id,
                        "--confirmation-token",
                        confirmation_token,
                    ],
                    requires_explicit_user_confirmation=True,
                )
            elif record.state is TransactionState.POLICY_AUTHORIZED:
                authorization = transaction_authorization(
                    record=record,
                    events=events,
                )
                current_policy = load_gateway_config(env).config.project_modification_policy
                payload["authorization"] = {
                    **authorization,
                    "current_policy": current_policy,
                }
                if current_policy == "allow_changes":
                    payload["next_command"] = transaction_next_command(
                        "execute",
                        ["execute", transaction_id],
                    )
                else:
                    payload["policy_execution_blocked"] = True
                    payload["repreview_required"] = True
            return payload
        if args.command == "confirm":
            require_transaction_confirmation_policy(
                store=store,
                transaction_id=transaction_id,
                env=env,
            )
            record = store.confirm(
                transaction_id,
                confirmation_token=args.confirmation_token,
            )
            return transaction_state_payload("confirm", record, offline=True)
        record = store.reject(transaction_id, details={"reason": args.reason})
        return transaction_state_payload("reject", record, offline=True)
    raise GatewayInputError(f"unsupported offline command: {args.command}")


def load_gateway_config(env: Mapping[str, str]) -> ResolvedSkillConfig:
    """Resolve the one public external-first config source used by the gateway."""

    try:
        return load_effective_skill_config(SKILL_ROOT, env=env)
    except (OSError, RecursionError, ValueError) as exc:
        raise GatewayInputError(f"Public WAAPI Skill config is invalid: {exc}") from exc


def attach_gateway_session_context(
    payload: Mapping[str, Any],
    *,
    args: argparse.Namespace,
    env: Mapping[str, str],
) -> dict[str, Any]:
    """Attach bounded onboarding facts without opening another WAAPI connection."""

    agent_result = payload.get("agent_result")
    next_command = payload.get("next_command")
    result = {
        key: value
        for key, value in payload.items()
        if key not in {"agent_result", "next_command"}
    }
    result["session_context"] = build_gateway_session_context(
        args=args,
        env=env,
        payload=payload,
    )
    if "next_command" in payload:
        # Keep the exact executable continuation as the final actionable
        # top-level field.  This makes the packaged absolute launcher path
        # salient after all evidence and onboarding context.
        result["next_command"] = next_command
    if "agent_result" in payload:
        # Machine-readable callers rely on this projection remaining the final
        # insertion-ordered field so it can be emitted verbatim and then stop.
        result["agent_result"] = agent_result
    return result


def gateway_one_time_introduction(
    *,
    endpoint_url: str | None,
    adapter_version: str | None,
    project_modification_policy: str | None,
) -> dict[str, Any]:
    """Describe the atomic, natural first reply without fixing its wording."""

    return {
        "contract": GATEWAY_SESSION_INTRODUCTION_CONTRACT,
        "emit_condition": "visible_conversation_intro_absent",
        "emit_timing": "first_agent_message_after_gateway_result",
        "atomic": True,
        "style": "natural_prose_in_user_language",
        "facts": {
            "skill_name": "waapi-skill",
            "endpoint_url": endpoint_url,
            "adapter_version": adapter_version,
            "project_modification_policy": project_modification_policy,
            "available_project_modification_policies": list(
                PROJECT_MODIFICATION_POLICIES
            ),
        },
        "machine_readable_result_policy": "separate_progress_message",
    }


def build_gateway_session_context(
    *,
    args: argparse.Namespace,
    env: Mapping[str, str],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve the user-facing address, adapter version, and mutation policy."""

    base: dict[str, Any] = {
        "contract": GATEWAY_SESSION_CONTEXT_CONTRACT,
        "available": False,
        "endpoint": {"host": None, "port": None, "url": None},
        "adapter_version": None,
        "adapter_version_source": "unavailable",
        "project_modification_policy": None,
        "available_project_modification_policies": list(PROJECT_MODIFICATION_POLICIES),
        "one_time_introduction": gateway_one_time_introduction(
            endpoint_url=None,
            adapter_version=None,
            project_modification_policy=None,
        ),
    }
    try:
        config = load_gateway_config(env).config
        effective = config.as_dict()
    except GatewayInputError:
        return base

    payload_endpoint = payload.get("endpoint")
    host: str | None = None
    port: int | None = None
    url: str | None = None
    if isinstance(payload_endpoint, Mapping):
        candidate_host = payload_endpoint.get("host")
        candidate_port = payload_endpoint.get("port")
        candidate_url = payload_endpoint.get("url")
        if isinstance(candidate_host, str) and candidate_host:
            host = candidate_host
        if isinstance(candidate_port, int) and not isinstance(candidate_port, bool):
            port = candidate_port
        if isinstance(candidate_url, str) and candidate_url:
            url = candidate_url

    if host is None:
        raw_host = args.host or env.get(ENV_HOST) or effective["waapi_host"] or DEFAULT_HOST
        try:
            host = SkillConfig(SKILL_ROOT, waapi_host=str(raw_host)).as_dict()["waapi_host"]
        except ValueError:
            host = None
    if port is None:
        raw_port: Any = args.port if args.port is not None else env.get(ENV_PORT)
        if raw_port is None:
            raw_port = effective["waapi_port"]
        try:
            candidate_port = int(raw_port) if raw_port is not None else None
        except (TypeError, ValueError):
            candidate_port = None
        if candidate_port is not None and 1 <= candidate_port <= 65535:
            port = candidate_port
    if url is None and host is not None and port is not None:
        url = f"ws://{host}:{port}/waapi"

    detected_version = payload.get("detected_version")
    configured_version = args.version or env.get(ENV_VERSION) or effective["wwise_version"]
    payload_versions = payload.get("versions")
    command_version = (
        str(payload_versions[0])
        if isinstance(payload_versions, Sequence)
        and not isinstance(payload_versions, (str, bytes, bytearray))
        and len(payload_versions) == 1
        and payload_versions[0] in SUPPORTED_WWISE_VERSION_KEYS
        else None
    )
    if detected_version in SUPPORTED_WWISE_VERSION_KEYS:
        adapter_version = str(detected_version)
        adapter_version_source = "live_detection"
    elif configured_version in SUPPORTED_WWISE_VERSION_KEYS:
        adapter_version = str(configured_version)
        adapter_version_source = "configured"
    elif command_version is not None:
        adapter_version = command_version
        adapter_version_source = "command_resolution"
    else:
        adapter_version = None
        adapter_version_source = "unavailable"

    policy = effective["project_modification_policy"]
    available = (
        host is not None
        and port is not None
        and url is not None
        and adapter_version is not None
        and policy is not None
    )

    return {
        "contract": GATEWAY_SESSION_CONTEXT_CONTRACT,
        "available": available,
        "endpoint": {"host": host, "port": port, "url": url},
        "adapter_version": adapter_version,
        "adapter_version_source": adapter_version_source,
        "project_modification_policy": policy,
        "available_project_modification_policies": list(PROJECT_MODIFICATION_POLICIES),
        "one_time_introduction": gateway_one_time_introduction(
            endpoint_url=url,
            adapter_version=adapter_version,
            project_modification_policy=policy,
        ),
    }


def require_project_modification_policy(
    *,
    env: Mapping[str, str],
    action: str,
) -> str:
    """Re-read and return the canonical policy at each mutation boundary."""

    policy = load_gateway_config(env).config.project_modification_policy
    if policy == "read_only":
        raise GatewayInputError(
            f"project_modification_policy=read_only blocks transaction {action}"
        )
    return policy


POLICY_AUTHORIZATION_AUTHORITY = "caller_asserted_current_user_change_request"


def sealed_read_transaction_contract(
    artifact: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    """Return a current, immutable read-transaction contract or fail closed.

    A handful of reflected read functions use the transaction lane for bounded
    schema validation and result verification.  ``read_only`` must permit those
    reads without permitting a model to relabel a mutation.  Classification is
    therefore restricted to a hash-checked ``waapi.call`` artifact whose
    request, dispatch, sealed contract, and current packaged catalog all agree.
    """

    if artifact.get("contract") != TRANSACTION_PREVIEW_CONTRACT:
        return None
    request = artifact.get("request")
    prepared = artifact.get("prepared_operation")
    if not isinstance(request, Mapping) or not isinstance(prepared, Mapping):
        return None
    if request.get("operation") != "waapi.call" or prepared.get("request") != request:
        return None
    version = request.get("version")
    arguments = request.get("arguments")
    dispatch_payload = prepared.get("dispatch")
    pre_state = prepared.get("pre_state")
    if (
        not isinstance(version, str)
        or not isinstance(arguments, Mapping)
        or not isinstance(dispatch_payload, Mapping)
        or not isinstance(pre_state, Mapping)
    ):
        return None
    api = arguments.get("api")
    call_args = arguments.get("args", {})
    call_options = arguments.get("options", {})
    if (
        not isinstance(api, str)
        or not isinstance(call_args, Mapping)
        or not isinstance(call_options, Mapping)
        or dict(dispatch_payload)
        != {
            "uri": api,
            "args": dict(call_args),
            "options": dict(call_options),
        }
    ):
        return None
    sealed_contract = pre_state.get("execution_contract")
    if not isinstance(sealed_contract, Mapping):
        return None
    try:
        capability = CapabilityCatalog().describe(version, api)
    except (CapabilityNotFoundError, ValueError):
        return None
    current_contract = capability.execution_contract
    try:
        request_validation = validate_semantic_payload(
            api,
            call_args,
            call_options,
            version=version,
        )
    except (SemanticValidationError, TypeError, ValueError):
        return None
    expected_sealed_contract = {
        **dict(current_contract),
        "request_validation": request_validation.as_dict(),
        "request_validation_strength": (
            "partial_reflected_schema"
            if request_validation.unresolved_refs
            else "complete_reflected_schema"
        ),
        "io_audit": None,
    }
    if (
        capability.preferred_route != "transaction_operation"
        or "waapi.call" not in capability.transaction_operations
        or current_contract.get("effect") != "read"
        or tuple(current_contract.get("accepted_authorization_modes", ()))
        != (AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,)
        or dict(sealed_contract) != expected_sealed_contract
    ):
        return None
    execution_policy = artifact.get("execution_policy")
    if (
        not isinstance(execution_policy, Mapping)
        or execution_policy.get("requires_authorization") is not True
        or tuple(execution_policy.get("accepted_authorization_modes", ()))
        != (AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,)
    ):
        return None
    return current_contract


def require_transaction_preconnection_policy(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> str:
    """Block read-only policy violations before opening a WAAPI connection."""

    policy = load_gateway_config(env).config.project_modification_policy
    if policy != "read_only":
        return policy
    store = resolve_transaction_store(args, env=env)
    try:
        artifact = store.load_preview(args.transaction_id).artifact
    except TransactionNotFound as exc:
        raise GatewayInputError(
            "project_modification_policy=read_only blocks transaction execution"
        ) from exc
    if not isinstance(artifact, Mapping) or sealed_read_transaction_contract(artifact) is None:
        raise GatewayInputError(
            "project_modification_policy=read_only blocks transaction execution"
        )
    return policy


def require_transaction_confirmation_policy(
    *,
    store: TransactionStore,
    transaction_id: str,
    env: Mapping[str, str],
) -> str:
    """Permit explicit confirmation in read-only mode only for sealed reads."""

    policy = load_gateway_config(env).config.project_modification_policy
    if policy != "read_only":
        return policy
    try:
        artifact = store.load_preview(transaction_id).artifact
    except TransactionNotFound as exc:
        raise GatewayInputError(
            "project_modification_policy=read_only blocks transaction confirmation"
        ) from exc
    if not isinstance(artifact, Mapping) or sealed_read_transaction_contract(artifact) is None:
        raise GatewayInputError(
            "project_modification_policy=read_only blocks transaction confirmation"
        )
    return policy


def transaction_authorization(
    *,
    record: Any,
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Project the durable execution authority without conflating policy and consent."""

    if record.state is TransactionState.CONFIRMED:
        if not any(event.get("event_type") == "confirmed" for event in events):
            raise GatewayInputError(
                "confirmed transaction is missing its durable confirmation event"
            )
        return {
            "mode": AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,
            "explicit_confirmation": True,
            "notice_required": False,
        }
    if record.state is TransactionState.POLICY_AUTHORIZED:
        event = next(
            (
                candidate
                for candidate in reversed(events)
                if candidate.get("event_type") == "policy_authorized"
            ),
            None,
        )
        details = event.get("details") if isinstance(event, Mapping) else None
        if not isinstance(details, Mapping):
            raise GatewayInputError(
                "policy-authorized transaction is missing its durable authorization event"
            )
        if (
            details.get("policy") != "allow_changes"
            or details.get("authority") != POLICY_AUTHORIZATION_AUTHORITY
            or details.get("explicit_confirmation") is not False
        ):
            raise GatewayInputError(
                "policy-authorized transaction has invalid durable authorization evidence"
            )
        return {
            "mode": AUTHORIZATION_MODE_POLICY,
            "policy": "allow_changes",
            "authority": POLICY_AUTHORIZATION_AUTHORITY,
            "explicit_confirmation": False,
            "notice_required": True,
        }
    raise InvalidTransition(
        f"Transaction {record.transaction_id!r} is not authorized for execution; "
        f"current state is {record.state.value!r}."
    )


def require_transaction_execution_authorization(
    *,
    record: Any,
    events: Sequence[Mapping[str, Any]],
    env: Mapping[str, str],
    read_only_transaction: bool = False,
) -> dict[str, Any]:
    """Revalidate durable authority and the current external policy before dispatch."""

    authorization = transaction_authorization(record=record, events=events)
    current_policy = load_gateway_config(env).config.project_modification_policy
    if read_only_transaction:
        if (
            record.state is not TransactionState.CONFIRMED
            or authorization.get("mode")
            != AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION
        ):
            raise GatewayInputError(
                "Read transactions require durable explicit confirmation."
            )
        return {
            **authorization,
            "current_policy": current_policy,
            "read_only_transaction": True,
        }
    if current_policy == "read_only":
        raise GatewayInputError(
            "project_modification_policy=read_only blocks transaction execution"
        )
    if (
        record.state is TransactionState.POLICY_AUTHORIZED
        and current_policy != "allow_changes"
    ):
        raise GatewayInputError(
            "A policy-authorized transaction can execute only while "
            "project_modification_policy=allow_changes; create a new preview "
            "under the current policy."
        )
    return {**authorization, "current_policy": current_policy}


def parse_config_set_changes(args: argparse.Namespace) -> dict[str, Any]:
    """Normalize one explicit config update before any filesystem write."""

    if args.wwise_version is not None and args.clear_wwise_version:
        raise GatewayInputError("--wwise-version and --clear-wwise-version are mutually exclusive")
    if args.waapi_port is not None and args.clear_waapi_port:
        raise GatewayInputError("--waapi-port and --clear-waapi-port are mutually exclusive")

    changes: dict[str, Any] = {}
    if args.wwise_version is not None:
        changes["wwise_version"] = args.wwise_version
    elif args.clear_wwise_version:
        changes["wwise_version"] = None
    if args.waapi_host is not None:
        changes["waapi_host"] = args.waapi_host
    if args.waapi_port is not None:
        try:
            changes["waapi_port"] = int(args.waapi_port)
        except (TypeError, ValueError) as exc:
            raise GatewayInputError(f"waapi_port must be an integer, got {args.waapi_port!r}") from exc
    elif args.clear_waapi_port:
        changes["waapi_port"] = None
    if args.project_modification_policy is not None:
        changes["project_modification_policy"] = args.project_modification_policy
    if not changes and not args.reset:
        raise GatewayInputError("config-set requires at least one public config change")
    return changes


def config_result_payload(
    command: str,
    resolution: ResolvedSkillConfig,
    *,
    changed_fields: Sequence[str] = (),
    migrated_from_legacy: bool = False,
    reset: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "config_contract": GATEWAY_CONFIG_CONTRACT,
        "ok": True,
        "status": "ok",
        "command": command,
        "offline": True,
        "effective": resolution.config.as_dict(),
        "source": resolution.source,
        "external_path": str(resolution.external_path),
        "legacy_fallback_used": resolution.legacy_fallback_used,
    }
    if command == "config-set":
        payload.update(
            {
                "saved": True,
                "changed_fields": list(changed_fields),
                "migrated_from_legacy": migrated_from_legacy,
                "reset": reset,
            }
        )
    return payload


def resolve_operation_schema_version(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> str | None:
    """Return only an explicitly configured request version for a schema envelope.

    Catalog browsing retains its historical 2022.1 default, but a mutation
    request must never acquire a version merely because no version was
    configured.  A missing value therefore produces a non-ready envelope and
    leaves the caller to select a supported version explicitly.
    """

    config = load_gateway_config(env).config
    version = args.version or env.get(ENV_VERSION) or config.wwise_version
    if version is None:
        return None
    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise GatewayInputError(
            f"Unsupported Wwise version {version!r}; supported versions: "
            f"{', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
        )
    return str(version)


def resolve_catalog_versions(args: argparse.Namespace, *, env: Mapping[str, str]) -> tuple[str, ...]:
    if bool(getattr(args, "all_versions", False)):
        return tuple(SUPPORTED_WWISE_VERSION_KEYS)
    config = load_gateway_config(env).config
    version = args.version or env.get(ENV_VERSION) or config.wwise_version or "2022.1"
    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise GatewayInputError(
            f"Unsupported Wwise version {version!r}; supported versions: {', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
        )
    return (str(version),)


def resolve_connection(args: argparse.Namespace, *, env: Mapping[str, str]) -> GatewayConnection:
    config = load_gateway_config(env).config
    host = args.host or env.get(ENV_HOST) or config.waapi_host or DEFAULT_HOST
    try:
        host = SkillConfig(SKILL_ROOT, waapi_host=str(host)).as_dict()["waapi_host"]
    except ValueError as exc:
        raise GatewayInputError(str(exc)) from exc
    raw_port: int | str | None = args.port if args.port is not None else env.get(ENV_PORT)
    if raw_port is None:
        raw_port = config.waapi_port
    if raw_port is None:
        raise GatewayInputError(
            f"WAAPI port is required via --port, ${ENV_PORT}, or saved config; "
            "use config-show/config-set to inspect or change saved values"
        )
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise GatewayInputError(f"WAAPI port must be an integer, got {raw_port!r}") from exc
    if not 1 <= port <= 65535:
        raise GatewayInputError(f"WAAPI port must be between 1 and 65535, got {port}")
    version_hint = args.version or env.get(ENV_VERSION) or config.wwise_version
    if version_hint is not None and version_hint not in SUPPORTED_WWISE_VERSION_KEYS:
        raise GatewayInputError(
            f"Unsupported Wwise version {version_hint!r}; supported versions: "
            f"{', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
        )
    evidence_text = args.evidence_dir or env.get(ENV_EVIDENCE_DIR)
    evidence_dir = (
        resolve_external_runtime_directory(
            evidence_text,
            label="--evidence-dir" if args.evidence_dir else f"${ENV_EVIDENCE_DIR}",
        )
        if evidence_text
        else None
    )
    no_topic_timeout = bool(
        args.command == "wait-topic" and getattr(args, "no_timeout", False)
    )
    continuous_topic_timeout = bool(
        args.command == "stream-topic" and args.timeout is None
    )
    raw_timeout = (
        math.inf
        if no_topic_timeout or continuous_topic_timeout
        else (
            args.timeout
            if args.timeout is not None
            else (
                DEFAULT_TRANSACTION_TIMEOUT
                if args.command
                in {
                    "preview-from-draft",
                    "execute",
                    "verify",
                }
                or (
                    args.command == "typed-zero-call"
                    and bool(getattr(args, "typed_zero_requires_preview", False))
                )
                or (
                    args.command == "typed-call"
                    and bool(getattr(args, "typed_requires_preview", False))
                )
                or args.command == "typed-operation"
                else float(args.typed_zero_read_timeout)
                if (
                    args.command == "typed-zero-call"
                    and getattr(args, "typed_zero_read_timeout", None) is not None
                )
                else float(args.typed_read_timeout)
                if (
                    args.command == "typed-call"
                    and getattr(args, "typed_read_timeout", None) is not None
                )
                else DEFAULT_METADATA_DISCOVERY_TIMEOUT
                if args.command == "metadata" and args.operation == "discover"
                else DEFAULT_TIMEOUT
            )
        )
    )
    if (
        raw_timeout <= 0
        or (
            not math.isfinite(raw_timeout)
            and not (
                (no_topic_timeout or continuous_topic_timeout)
                and raw_timeout == math.inf
            )
        )
    ):
        raise GatewayInputError("timeout must be finite and greater than zero")
    timeout = float(raw_timeout)
    return GatewayConnection(
        host=host,
        port=port,
        version_hint=str(version_hint) if version_hint else None,
        evidence_dir=evidence_dir,
        timeout=timeout,
        deadline=GatewayDeadline.start(timeout),
    )


def dispatch_profiler_voice_contributions_request(
    request: Any,
    *,
    connection: GatewayConnection,
    detected_version: str,
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the one existing bounded voice-contribution read adapter."""

    request_validation = validate_semantic_payload(
        request.uri,
        request.args,
        request.options,
        version=detected_version,
    )
    result = dispatch(
        dispatcher,
        request.uri,
        connection=connection,
        version=detected_version,
        args=request.args,
        options=request.options,
        result_limit_bytes=STABLE_READ_RESULT_LIMIT_BYTES,
    )
    if not result.get("ok"):
        return {
            "ok": False,
            "status": "error",
            **dict(common),
            "semantic_preview": request.as_dict(),
            "schema_validation": {
                "request": request_validation.as_dict(),
                "result": None,
            },
            "call": dispatch_call_summary(result),
        }
    raw_result = result.get("result")
    result_validation = validate_semantic_result(
        request.uri,
        raw_result,
        version=detected_version,
    )
    projection = normalize_profiler_voice_contributions_result(
        version=detected_version,
        result=raw_result,
    )
    return {
        "ok": True,
        "status": "ok",
        **dict(common),
        "semantic_preview": request.as_dict(),
        "schema_validation": {
            "request": request_validation.as_dict(),
            "result": result_validation.as_dict(),
        },
        "call": dispatch_call_summary(result),
        "agent_result": projection,
    }


def dispatch_typed_debug_validation(
    typed_request: Any,
    *,
    connection: GatewayConnection,
    detected_version: str,
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the existing bounded Debug validateCall adapter from typed facts."""

    api = TYPED_REQUEST_COMPLEX_TRACER_URI
    capability = CapabilityCatalog().describe(detected_version, api)
    call_args = dict(typed_request.args)
    supplied_sections = [
        name for name in ("args", "options", "result") if name in call_args
    ]
    request_validation = validate_semantic_payload(
        api, call_args, {}, version=detected_version
    )
    result = dispatch(
        dispatcher,
        api,
        connection=connection,
        version=detected_version,
        args=call_args,
        options={},
        result_limit_bytes=int(capability.execution_contract["result_limit_bytes"]),
        operation_timeout=float(capability.execution_contract["timeout_seconds"]),
    )
    result_validation = (
        validate_semantic_result(api, result.get("result"), version=detected_version)
        if result.get("ok")
        else None
    )
    return {
        "ok": bool(result.get("ok")),
        "status": "ok" if result.get("ok") else "error",
        **dict(common),
        "api_attempted": api,
        "validated_api": call_args["id"],
        "supplied_sections": supplied_sections,
        "call": dispatch_call_summary(result),
        "schema_validation": {
            "request": request_validation.as_dict(),
            "result": result_validation.as_dict() if result_validation else None,
        },
        "agent_result": (
            {
                "validated_api": call_args["id"],
                "supplied_sections": supplied_sections,
                "accepted_by_wwise": True,
            }
            if result.get("ok")
            else None
        ),
    }


def dispatch_command(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    stream_sink: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    common = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "command": args.command,
        "endpoint": {"host": connection.host, "port": connection.port, "url": connection.url},
        "detected_version": detected_version,
        "is_command_line": bool(live_info.get("isCommandLine")),
    }
    if args.command == "draft-check":
        return dispatch_operation_draft_check(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command == "preview-from-draft":
        return dispatch_operation_draft_preview(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command == "status":
        info = dispatch(
            dispatcher,
            GET_INFO_URI,
            connection=connection,
            version=detected_version,
        )
        info_payload = (
            require_status_info(
                strict_call_result_mapping(
                    info,
                    command="status getInfo",
                    error_code="INVALID_STATUS_RESULT",
                ),
                expected_version=detected_version,
            )
            if info.get("ok")
            else None
        )
        if detected_version == "2021.1":
            project_call = dispatch(
                dispatcher,
                OBJECT_GET_URI,
                connection=connection,
                version=detected_version,
                args={"waql": "from type Project take 1"},
                options={"return": ["id", "name", "type", "path"]},
            )
            project_rows = (
                strict_object_get_rows(
                    project_call,
                    command="status project",
                    maximum_rows=1,
                    error_code="INVALID_STATUS_RESULT",
                )
                if project_call.get("ok")
                else []
            )
            project = (
                require_single_result_row(
                    project_rows,
                    command="status project",
                    error_code="INVALID_STATUS_RESULT",
                )
                if project_call.get("ok")
                else None
            )
        else:
            project_call = dispatch(
                dispatcher,
                GET_PROJECT_INFO_URI,
                connection=connection,
                version=detected_version,
            )
            project = (
                strict_call_result_mapping(
                    project_call,
                    command="status getProjectInfo",
                    error_code="INVALID_STATUS_RESULT",
                )
                if project_call.get("ok")
                else None
            )
        if project is not None:
            project = require_project_identity(
                project,
                command="status project",
                error_code="INVALID_STATUS_RESULT",
            )
        ok = bool(info.get("ok") and project_call.get("ok") and project is not None)
        return {
            "ok": ok,
            "status": "ok" if ok else "error",
            **common,
            "calls": [dispatch_call_summary(info), dispatch_call_summary(project_call)],
            "wwise": status_wwise_summary(info_payload),
            "project": status_project_summary(project),
        }
    if args.command == "project-default-work-units":
        if detected_version == "2021.1":
            projection = normalize_project_default_work_units_result(
                version=detected_version,
                result=None,
            )
            return {
                "ok": True,
                "status": "ok",
                **common,
                "api_attempted": None,
                "call": None,
                "message": (
                    "Wwise 2021.1 has no reflected getProjectInfo API; "
                    "the 2025.1 default Work Unit fields are unavailable."
                ),
                "agent_result": projection,
            }
        request = build_project_default_work_units_request(
            version=detected_version,
        )
        request_validation = validate_semantic_payload(
            request.uri,
            request.args,
            request.options,
            version=detected_version,
        )
        result = dispatch(
            dispatcher,
            request.uri,
            connection=connection,
            version=detected_version,
            args=request.args,
            options=request.options,
            result_limit_bytes=STABLE_READ_RESULT_LIMIT_BYTES,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "status": "error",
                **common,
                "semantic_preview": request.as_dict(),
                "schema_validation": {
                    "request": request_validation.as_dict(),
                    "result": None,
                },
                "call": dispatch_call_summary(result),
            }
        raw_result = result.get("result")
        result_validation = validate_semantic_result(
            request.uri,
            raw_result,
            version=detected_version,
        )
        projection = normalize_project_default_work_units_result(
            version=detected_version,
            result=raw_result,
        )
        return {
            "ok": True,
            "status": "ok",
            **common,
            "semantic_preview": request.as_dict(),
            "schema_validation": {
                "request": request_validation.as_dict(),
                "result": result_validation.as_dict(),
            },
            "call": dispatch_call_summary(result),
            "agent_result": projection,
        }
    if args.command == "typed-call":
        typed_request = args.typed_request
        if typed_request.version != detected_version:
            raise GatewayInputError(
                "Typed request version changed after preflight; request-schema must be rerun"
            )
        if typed_request.uri != TYPED_REQUEST_TRACER_URI:
            if typed_request.uri == TYPED_REQUEST_COMPLEX_TRACER_URI:
                return dispatch_typed_debug_validation(
                    typed_request,
                    connection=connection,
                    detected_version=detected_version,
                    dispatcher=dispatcher,
                    common={
                        **common,
                        "typed_request": {
                            "contract": typed_request.as_dict()["contract"],
                            "schema_digest": typed_request.schema_digest,
                        },
                    },
                )
            capability = live_capability(
                detected_version,
                typed_request.uri,
                live_info=live_info,
            )
            if capability.execution_contract["effect"] != "read":
                request_payload = {
                    "contract": OPERATION_REQUEST_CONTRACT,
                    "version": detected_version,
                    "operation": "waapi.call",
                    "arguments": {
                        "api": typed_request.uri,
                        "args": dict(typed_request.args),
                        "options": dict(typed_request.options),
                        **(
                            {"io_root": args.typed_io_root}
                            if args.typed_io_root is not None
                            else {}
                        ),
                    },
                }
                return create_transaction_preview(
                    request_payload,
                    args=args,
                    env=env,
                    connection=connection,
                    detected_version=detected_version,
                    live_info=live_info,
                    dispatcher=dispatcher,
                    common={
                        **common,
                        "typed_request": {
                            "contract": typed_request.as_dict()["contract"],
                            "schema_digest": typed_request.schema_digest,
                        },
                    },
                )
            request_validation = validate_semantic_payload(
                typed_request.uri,
                typed_request.args,
                typed_request.options,
                version=detected_version,
                authoring_ui_profile=live_info.get("isCommandLine") is False,
            )
            result = dispatch(
                dispatcher,
                typed_request.uri,
                connection=connection,
                version=detected_version,
                args=typed_request.args,
                options=typed_request.options,
                allow_destructive=True,
                result_limit_bytes=int(
                    capability.execution_contract["result_limit_bytes"]
                ),
                operation_timeout=float(
                    capability.execution_contract["timeout_seconds"]
                ),
            )
            result_validation = (
                validate_semantic_result(
                    typed_request.uri,
                    result.get("result"),
                    version=detected_version,
                    authoring_ui_profile=live_info.get("isCommandLine") is False,
                )
                if result.get("ok")
                else None
            )
            return {
                "ok": bool(result.get("ok")),
                "status": "ok" if result.get("ok") else "error",
                **common,
                "api_attempted": typed_request.uri,
                "typed_request": {
                    "contract": typed_request.as_dict()["contract"],
                    "schema_digest": typed_request.schema_digest,
                },
                "call": dispatch_call_summary(result),
                "schema_validation": {
                    "request": request_validation.as_dict(),
                    "result": (
                        result_validation.as_dict() if result_validation else None
                    ),
                },
                "agent_result": result.get("result") if result.get("ok") else None,
            }
        request = args.typed_stable_request
        return dispatch_profiler_voice_contributions_request(
            request,
            connection=connection,
            detected_version=detected_version,
            dispatcher=dispatcher,
            common={
                **common,
                "typed_request": {
                "contract": typed_request.as_dict()["contract"],
                "schema_digest": typed_request.schema_digest,
            },
            },
        )
    if args.command == "typed-operation":
        return create_transaction_preview(
            args.typed_operation_request,
            args=args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common={
                **common,
                "typed_operation": {
                    "operation": args.operation,
                    "schema_digest": args.schema_digest,
                },
            },
        )
    if args.command == "typed-zero-call":
        typed_request = args.typed_request
        if typed_request.version != detected_version:
            raise GatewayInputError(
                "Typed request version changed after preflight; request-schema must be rerun"
            )
        authoring_boundary = live_authoring_api_boundary(
            typed_request.uri,
            command="typed-zero-call",
            live_info=live_info,
            common=common,
        )
        if authoring_boundary is not None:
            return authoring_boundary
        capability = live_capability(
            detected_version,
            typed_request.uri,
            live_info=live_info,
        )
        if capability.execution_contract["effect"] != "read":
            if tuple(capability.transaction_operations) == ("waapi.call",):
                request_payload = {
                    "contract": OPERATION_REQUEST_CONTRACT,
                    "version": detected_version,
                    "operation": "waapi.call",
                    "arguments": {
                        "api": typed_request.uri,
                        "args": {},
                        "options": {},
                    },
                }
            else:
                raise GatewayInputError(
                    "This zero-input API does not have an executable typed Preview route"
                )
            return create_transaction_preview(
                request_payload,
                args=args,
                env=env,
                connection=connection,
                detected_version=detected_version,
                live_info=live_info,
                dispatcher=dispatcher,
                common={
                    **common,
                    "typed_request": {
                        "contract": typed_request.as_dict()["contract"],
                        "schema_digest": typed_request.schema_digest,
                        "business_values_required": False,
                        "gateway_owned_acknowledgement": False,
                    },
                },
            )
        request_validation = validate_semantic_payload(
            typed_request.uri,
            typed_request.args,
            typed_request.options,
            version=detected_version,
            authoring_ui_profile=live_info.get("isCommandLine") is False,
        )
        result = dispatch(
            dispatcher,
            typed_request.uri,
            connection=connection,
            version=detected_version,
            args=typed_request.args,
            options=typed_request.options,
            allow_destructive=(
                capability.execution_contract["effect"] == "read"
            ),
            result_limit_bytes=int(capability.execution_contract["result_limit_bytes"]),
            operation_timeout=float(capability.execution_contract["timeout_seconds"]),
        )
        result_validation = (
            validate_semantic_result(
                typed_request.uri,
                result.get("result"),
                version=detected_version,
                authoring_ui_profile=live_info.get("isCommandLine") is False,
            )
            if result.get("ok")
            else None
        )
        inventory = (
            normalize_reflection_inventory_result(
                typed_request.uri,
                result,
                version=detected_version,
            )
            if result.get("ok") and typed_request.uri in REFLECTION_INVENTORY_CALLS
            else None
        )
        return {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "api_attempted": typed_request.uri,
            "typed_request": {
                "contract": typed_request.as_dict()["contract"],
                "schema_digest": typed_request.schema_digest,
                "business_values_required": False,
            },
            "call": dispatch_call_summary(result),
            "schema_validation": {
                "request": request_validation.as_dict(),
                "result": result_validation.as_dict() if result_validation else None,
            },
            "inventory": inventory,
            "agent_result": (
                inventory
                if inventory is not None
                else result.get("result") if result.get("ok") else None
            ),
        }
    if args.command == "profiler-game-objects":
        request = build_profiler_game_objects_request(
            version=detected_version,
            time=args.time,
        )
        request_validation = validate_semantic_payload(
            request.uri,
            request.args,
            request.options,
            version=detected_version,
        )
        result = dispatch(
            dispatcher,
            request.uri,
            connection=connection,
            version=detected_version,
            args=request.args,
            options=request.options,
            result_limit_bytes=STABLE_READ_RESULT_LIMIT_BYTES,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "status": "error",
                **common,
                "semantic_preview": request.as_dict(),
                "schema_validation": {
                    "request": request_validation.as_dict(),
                    "result": None,
                },
                "call": dispatch_call_summary(result),
            }
        raw_result = result.get("result")
        result_validation = validate_semantic_result(
            request.uri,
            raw_result,
            version=detected_version,
        )
        projection = normalize_profiler_game_objects_result(
            version=detected_version,
            result=raw_result,
        )
        return {
            "ok": True,
            "status": "ok",
            **common,
            "semantic_preview": request.as_dict(),
            "schema_validation": {
                "request": request_validation.as_dict(),
                "result": result_validation.as_dict(),
            },
            "call": dispatch_call_summary(result),
            "agent_result": projection,
        }
    if args.command == "profiler-voice-contributions":
        request = build_profiler_voice_contributions_request(
            version=detected_version,
            time=args.time,
            voice_pipeline_id=args.voice_pipeline_id,
            bus_pipeline_ids=tuple(args.bus_pipeline_id),
        )
        return dispatch_profiler_voice_contributions_request(
            request,
            connection=connection,
            detected_version=detected_version,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command == "debug-wal-tree":
        api = "ak.wwise.debug.getWalTree"
        try:
            capability = CapabilityCatalog().describe(detected_version, api)
        except CapabilityNotFoundError:
            return unreflected_interface_payload(
                api,
                detected_version,
                command=args.command,
                common=common,
            )
        if (
            capability.preferred_route != "fixed_command"
            or args.command not in capability.fixed_commands
        ):
            raise GatewayInputError(
                f"{api} is not bound to the packaged {args.command} route in Wwise {detected_version}"
            )
        request_validation = validate_semantic_payload(
            api,
            {},
            {},
            version=detected_version,
        )
        result = dispatch(
            dispatcher,
            api,
            connection=connection,
            version=detected_version,
            args={},
            options={},
            result_limit_bytes=int(
                capability.execution_contract["result_limit_bytes"]
            ),
            operation_timeout=float(
                capability.execution_contract["timeout_seconds"]
            ),
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "status": "error",
                **common,
                "api_attempted": api,
                "call": dispatch_call_summary(result),
                "schema_validation": {
                    "request": request_validation.as_dict(),
                    "result": None,
                },
            }
        result_validation = validate_semantic_result(
            api,
            result.get("result"),
            version=detected_version,
        )
        try:
            projection = normalize_wal_tree_result(
                result.get("result"),
                take=args.take,
            )
        except DebugLuaContractError as exc:
            raise GatewayResultShapeError(
                str(exc),
                details=exc.details,
                error_code=exc.error_code,
            ) from exc
        return {
            "ok": True,
            "status": "ok",
            **common,
            "api_attempted": api,
            "call": dispatch_call_summary(result),
            "schema_validation": {
                "request": request_validation.as_dict(),
                "result": result_validation.as_dict(),
            },
            "agent_result": projection,
        }
    if args.command == "buses":
        preview = build_object_get_query(
            type="Bus",
            take=MAX_QUERY_TAKE,
            return_fields=("id", "name", "type", "path"),
            version=detected_version,
        )
        envelope = preview.envelope
        result = dispatch(
            dispatcher,
            envelope.uri,
            connection=connection,
            version=detected_version,
            args=envelope.args,
            options=envelope.options,
        )
        rows = (
            strict_object_get_rows(
                result,
                command="buses",
                maximum_rows=MAX_QUERY_TAKE,
                required_string_fields=("id", "name", "type", "path"),
            )
            if result.get("ok")
            else []
        )
        return {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "semantic_preview": preview.as_dict(),
            "query_bound": {
                "mode": "take",
                "value": MAX_QUERY_TAKE,
                "source": "fixed-command-default",
            },
            "call": dispatch_call_summary(result),
            "count": len(rows) if result.get("ok") else None,
            "buses": rows if result.get("ok") else None,
            "possibly_truncated": (
                len(rows) == MAX_QUERY_TAKE if result.get("ok") else None
            ),
        }
    if args.command == "selected":
        return_fields = normalize_selected_return_fields(args.return_fields)
        request_validation = None
        try:
            selected_capability = CapabilityCatalog().describe(
                detected_version,
                GET_SELECTED_URI,
            )
        except CapabilityNotFoundError:
            # Preserve the existing explicit absent-from-manifest boundary and
            # its dispatcher evidence for versions without this reflected API.
            pass
        else:
            if (
                selected_capability.preferred_route != "fixed_command"
                or "selected" not in selected_capability.fixed_commands
            ):
                raise GatewayInputError(
                    f"{GET_SELECTED_URI} is not bound to the packaged selected route "
                    f"in Wwise {detected_version}"
                )
            request_validation = validate_semantic_payload(
                GET_SELECTED_URI,
                {},
                {"return": list(return_fields)},
                version=detected_version,
            )
        result = dispatch(
            dispatcher,
            GET_SELECTED_URI,
            connection=connection,
            version=detected_version,
            args={},
            options={"return": list(return_fields)},
        )
        if not result.get("ok") and selected_ui_boundary(result, live_info=live_info):
            absent = result.get("error_code") == "API_NOT_FOUND"
            return {
                "ok": True,
                "status": "unsupported_boundary",
                **common,
                "api_attempted": GET_SELECTED_URI,
                "call": dispatch_call_summary(result),
                "return_fields": list(return_fields),
                "schema_validation": {
                    "request": (
                        request_validation.as_dict()
                        if request_validation is not None
                        else None
                    ),
                    "result": None,
                },
                "message": (
                    "ak.wwise.ui.getSelectedObjects is absent from this version's packaged manifest."
                    if absent
                    else (
                        "The connected Wwise instance is command-line/headless, so "
                        "ak.wwise.ui.getSelectedObjects is unavailable."
                    )
                ),
                "count": None,
                "objects": None,
            }
        rows = strict_selected_rows(result) if result.get("ok") else []
        result_validation = (
            validate_semantic_result(
                GET_SELECTED_URI,
                result.get("result"),
                version=detected_version,
            )
            if result.get("ok")
            else None
        )
        return {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "api_attempted": GET_SELECTED_URI,
            "call": dispatch_call_summary(result),
            "return_fields": list(return_fields),
            "schema_validation": {
                "request": (
                    request_validation.as_dict()
                    if request_validation is not None
                    else None
                ),
                "result": (
                    result_validation.as_dict()
                    if result_validation is not None
                    else None
                ),
            },
            "count": len(rows) if result.get("ok") else None,
            "objects": rows if result.get("ok") else None,
        }
    if args.command == "query-object":
        if original_file_reference_match_requested(args):
            return dispatch_original_file_reference_match(
                args,
                connection=connection,
                detected_version=detected_version,
                dispatcher=dispatcher,
                common=common,
            )
        if getattr(args, "typed_structured", False):
            typed_query = args.typed_query
            if typed_query.version != detected_version:
                raise GatewayInputError(
                    "Typed query version changed after preflight; query-schema must be rerun"
                )
            preview = typed_query.preview
            _require_structured_exact_identity_return_field(preview)
            envelope = preview.envelope
            exact_identity = _structured_query_exact_identity(preview)
            query_bound = _structured_query_bound(preview)
            result = dispatch(
                dispatcher,
                envelope.uri,
                connection=connection,
                version=detected_version,
                args=envelope.args,
                options=envelope.options,
                exact_object_lookup=exact_identity is not None,
            )
            rows = (
                strict_object_get_rows(
                    result,
                    command="query-object --typed-structured",
                    maximum_rows=_structured_query_result_maximum(
                        query_bound,
                        exact_identity=exact_identity,
                    ),
                )
                if result.get("ok")
                else []
            )
            if result.get("ok"):
                validate_structured_exact_query_identity(exact_identity, rows)
            payload = {
                "ok": bool(result.get("ok")),
                "status": "ok" if result.get("ok") else "error",
                **common,
                "query_layer": "structured-builder",
                "query_contract": STRUCTURED_QUERY_CONTRACT,
                "typed_query": {"schema_digest": typed_query.schema_digest},
                "semantic_preview": preview.as_dict(),
                "query_bound": query_bound,
                "call": dispatch_call_summary(result),
                "count": len(rows) if result.get("ok") else None,
                "objects": rows if result.get("ok") else None,
                "agent_result": rows if result.get("ok") else None,
            }
            return payload
        if getattr(args, "typed_advanced", False):
            typed_query = args.typed_query
            if typed_query.version != detected_version:
                raise GatewayInputError(
                    "Typed query version changed after preflight; query-schema must be rerun"
                )
            preview = typed_query.preview
            envelope = preview.envelope
            query_bound = _advanced_query_bound(preview)
            maximum_rows = query_bound["value"]
            result = dispatch(
                dispatcher,
                envelope.uri,
                connection=connection,
                version=detected_version,
                args=envelope.args,
                options=envelope.options,
                exact_object_lookup=False,
            )
            rows = (
                strict_object_get_rows(
                    result,
                    command="query-object --typed-advanced",
                    maximum_rows=maximum_rows,
                )
                if result.get("ok")
                else []
            )
            return {
                "ok": bool(result.get("ok")),
                "status": "ok" if result.get("ok") else "error",
                **common,
                "query_layer": "advanced-native-waql",
                "query_contract": ADVANCED_QUERY_CONTRACT,
                "typed_query": {"schema_digest": typed_query.schema_digest},
                "semantic_preview": preview.as_dict(),
                "query_bound": query_bound,
                "call": dispatch_call_summary(result),
                "count": len(rows) if result.get("ok") else None,
                "limit_reached": len(rows) == maximum_rows if result.get("ok") else None,
                "objects": rows if result.get("ok") else None,
                "agent_result": rows if result.get("ok") else None,
            }
        where = typed_query_predicates(args)
        return_fields = tuple(args.return_fields or ("id", "name", "type", "path"))
        _require_exact_identity_return_field(args, return_fields)
        preview = build_object_get_query(
            path=args.path,
            object_id=args.object_id,
            type=args.object_type,
            search=args.search,
            query=args.query,
            where=where,
            select=tuple(args.select or ()),
            take=args.take,
            return_fields=return_fields,
            version=detected_version,
        )
        _require_explicit_query_bound(args)
        envelope = preview.envelope
        result = dispatch(
            dispatcher,
            envelope.uri,
            connection=connection,
            version=detected_version,
            args=envelope.args,
            options=envelope.options,
            exact_object_lookup=_canonical_exact_query_request(args),
        )
        rows = (
            strict_object_get_rows(
                result,
                command="query-object",
                maximum_rows=_query_result_maximum(args),
            )
            if result.get("ok")
            else []
        )
        if result.get("ok"):
            validate_exact_query_identity(args, rows)
        return {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "semantic_preview": preview.as_dict(),
            "query_bound": _query_bound_summary(args),
            "call": dispatch_call_summary(result),
            "count": len(rows) if result.get("ok") else None,
            "objects": rows if result.get("ok") else None,
        }
    if args.command == "metadata":
        if args.operation == "discover":
            read_call = transaction_read_call(
                dispatcher,
                connection=connection,
                version=detected_version,
            )
            project: Mapping[str, Any] | None
            try:
                project, _project_call = current_project(
                    dispatcher,
                    connection=connection,
                    version=detected_version,
                    allow_none=True,
                )
            except (
                GatewayInputError,
                GatewayResultShapeError,
                OperationContractError,
            ):
                # Project/session binding is a cache optimization for this
                # read-only command.  A failed probe must not prevent the
                # authoritative live metadata reads below.
                project = None
            state_dir = prepare_read_only_metadata_cache_state_directory(
                args,
                env=env,
                project=project,
            )
            read_call = metadata_cached_read_call(
                read_call,
                connection=connection,
                version=detected_version,
                live_info=live_info,
                project=project,
                state_dir=state_dir,
            )
            discovery = discover_metadata(
                read_call=read_call,
                queries=tuple(args.queries),
                object_type=args.object_type,
                class_id=args.class_id,
                object=args.object,
                limit=(
                    DEFAULT_METADATA_DISCOVERY_LIMIT
                    if args.limit is None
                    else args.limit
                ),
            )
            payload = {
                "ok": True,
                "status": "ok",
                **common,
                "operation": args.operation,
                "metadata_authority": "live-waapi",
            }
            payload["agent_result"] = discovery.as_dict(detail=args.detail)
            return payload
        preview = build_metadata_command_preview(args, version=detected_version)
        envelope = preview.envelope
        result = dispatch(
            dispatcher,
            envelope.uri,
            connection=connection,
            version=detected_version,
            args=envelope.args,
            options=envelope.options,
        )
        normalized = normalize_metadata_result(args.operation, result) if result.get("ok") else None
        payload = {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "operation": args.operation,
            "semantic_preview": preview.as_dict(),
            "call": dispatch_call_summary(result),
        }
        if args.summary_only:
            payload["summary_only"] = True
            if result.get("ok"):
                if not isinstance(normalized, list):
                    raise GatewayResultShapeError(
                        "metadata types summary requires a normalized type array.",
                        details={"operation": args.operation},
                        error_code="INVALID_METADATA_RESULT",
                    )
                payload["agent_result"] = {
                    "count": len(normalized),
                    "contains_actor_mixer": any(
                        row.get("name") == "ActorMixer" or row.get("type") == "ActorMixer"
                        for row in normalized
                    ),
                }
            return payload
        payload["normalized"] = normalized
        return payload
    if args.command == "stream-topic":
        return dispatch_topic_stream(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
            stream_sink=stream_sink,
        )
    if args.command == "wait-topic":
        typed_topic_input = args.typed_topic_input
        request_options = dict(typed_topic_input.options)
        match = dict(typed_topic_input.match)
        authoring_boundary = live_authoring_api_boundary(
            args.api,
            command="wait-topic",
            live_info=live_info,
            common=common,
        )
        if authoring_boundary is not None:
            return authoring_boundary
        try:
            capability = live_capability(
                detected_version,
                args.api,
                live_info=live_info,
            )
        except CapabilityNotFoundError:
            return unreflected_interface_payload(
                args.api,
                detected_version,
                command="wait-topic",
                common=common,
            )
        route_boundary = catalog_route_boundary_payload(
            capability,
            command="wait-topic",
            common=common,
        )
        if route_boundary is not None:
            return route_boundary
        result = dispatch(
            dispatcher,
            args.api,
            connection=connection,
            version=detected_version,
            options=request_options,
            topic_match=match or None,
            topic_event_count=args.event_count,
            operation_timeout=reserved_topic_wait_timeout(connection),
            result_limit_bytes=int(capability.execution_contract["result_limit_bytes"]),
        )
        unbounded_timeout = math.isinf(connection.timeout)
        payload: dict[str, Any] = {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "topic": args.api,
            "match": match or None,
            "subscription_timeout": {
                "mode": "unbounded" if unbounded_timeout else "finite",
                "seconds": None if unbounded_timeout else connection.timeout,
                "source": (
                    "explicit_no_timeout"
                    if unbounded_timeout
                    else "explicit"
                    if args.timeout is not None
                    else "default"
                ),
            },
            "call": dispatch_call_summary(result),
        }
        cleanup = topic_subscription_cleanup_status(result)
        if args.event_count == 1:
            event = normalize_topic_event_result(result, expected_topic=args.api) if result.get("ok") else None
            event_validation = (
                validate_semantic_event(
                    args.api,
                    event,
                    version=detected_version,
                    authoring_ui_profile=live_info.get("isCommandLine") is False,
                )
                if event is not None
                else None
            )
            payload["event"] = event
            payload["event_validation"] = (
                event_validation.as_dict() if event_validation is not None else None
            )
            payload["cleanup"] = cleanup
            return payload

        events = (
            normalize_topic_events_result(
                result,
                expected_topic=args.api,
                expected_count=args.event_count,
            )
            if result.get("ok")
            else None
        )
        event_validations = (
            [
                validate_semantic_event(
                    args.api,
                    event,
                    version=detected_version,
                    authoring_ui_profile=live_info.get("isCommandLine") is False,
                ).as_dict()
                for event in events
            ]
            if events is not None
            else None
        )
        payload["requested_event_count"] = args.event_count
        payload["event_count"] = len(events) if events is not None else None
        payload["events"] = events
        payload["event_validations"] = event_validations
        payload["cleanup"] = cleanup
        return payload
    if args.command in {"execute", "verify"}:
        return dispatch_transaction_command(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    raise GatewayInputError(f"unsupported command: {args.command}")


def dispatch_topic_stream(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
    stream_sink: Callable[[Mapping[str, Any]], None] | None,
) -> dict[str, Any]:
    """Keep one reviewed topic subscription open and publish events immediately."""

    typed_topic_input = args.typed_topic_input
    request_options = dict(typed_topic_input.options)
    match = dict(typed_topic_input.match)
    authoring_boundary = live_authoring_api_boundary(
        args.api,
        command="stream-topic",
        live_info=live_info,
        common=common,
    )
    if authoring_boundary is not None:
        return authoring_boundary
    try:
        capability = live_capability(
            detected_version,
            args.api,
            live_info=live_info,
        )
    except CapabilityNotFoundError:
        return unreflected_interface_payload(
            args.api,
            detected_version,
            command="stream-topic",
            common=common,
        )
    route_boundary = catalog_route_boundary_payload(
        capability,
        command="stream-topic",
        common=common,
    )
    if route_boundary is not None:
        return route_boundary

    result_limit_bytes = int(
        capability.execution_contract["result_limit_bytes"]
    )
    manager = SubscriptionManager(dispatcher.client)  # type: ignore[arg-type]
    event_stream = manager.open_stream(
        args.api,
        options=request_options,
        queue_size=DEFAULT_LISTENER_QUEUE_SIZE,
        max_event_bytes=result_limit_bytes,
    )
    stream_started_at = time.monotonic()
    unbounded_timeout = math.isinf(connection.timeout)
    timeout_policy = {
        "mode": "unbounded" if unbounded_timeout else "finite",
        "seconds": None if unbounded_timeout else connection.timeout,
        "source": (
            "default_continuous"
            if args.timeout is None
            else "explicit"
        ),
    }
    stream_common = {
        **dict(common),
        "contract": TOPIC_STREAM_RECORD_CONTRACT,
        "command": "stream-topic",
        "topic": args.api,
        "match": match or None,
        "subscription_timeout": timeout_policy,
    }
    started_record = attach_gateway_session_context(
        {
            **stream_common,
            "record_type": "started",
            "ok": True,
            "status": "streaming",
            "buffer_limit_events": DEFAULT_LISTENER_QUEUE_SIZE,
            "event_result_limit_bytes": result_limit_bytes,
        },
        args=args,
        env=env,
    )

    event_count = 0
    primary_error: Exception | None = None
    cleanup_status = "unknown"
    cleanup_failure: dict[str, Any] | None = None
    try:
        emit_topic_stream_record(
            started_record,
            sink=stream_sink,
            limit_bytes=MAX_GATEWAY_RESULT_JSON_BYTES,
        )
        collection_timeout = (
            math.inf
            if unbounded_timeout
            else reserved_topic_wait_timeout(connection)
        )
        collection_expires_at = (
            math.inf
            if math.isinf(collection_timeout)
            else time.monotonic() + collection_timeout
        )
        next_health_at = (
            time.monotonic() + TOPIC_STREAM_HEALTH_INTERVAL_SECONDS
        )
        while True:
            now = time.monotonic()
            remaining = collection_expires_at - now
            if remaining <= 0:
                break
            if now >= next_health_at:
                require_topic_stream_health(
                    dispatcher,
                    expected_version=detected_version,
                )
                next_health_at = (
                    time.monotonic() + TOPIC_STREAM_HEALTH_INTERVAL_SECONDS
                )
                continue
            event = event_stream.poll(
                min(
                    TOPIC_STREAM_POLL_SECONDS,
                    max(0.0, next_health_at - now),
                    remaining,
                )
            )
            if event is None:
                continue
            if match and not payload_matches(event.payload, match):
                continue
            payload_probe = probe_gateway_json_document_size(
                event.payload,
                result_limit_bytes,
            )
            if payload_probe != "ok":
                raise GatewayResultShapeError(
                    "stream-topic event exceeded its reflected JSON result boundary.",
                    details={
                        "topic": args.api,
                        "limit_bytes": result_limit_bytes,
                        "reason": payload_probe,
                    },
                    error_code=(
                        "RESULT_TOO_LARGE"
                        if payload_probe == "too_large"
                        else "RESULT_NOT_JSON"
                    ),
                )
            validation = validate_semantic_event(
                args.api,
                event.payload,
                version=detected_version,
                authoring_ui_profile=live_info.get("isCommandLine") is False,
            )
            sequence = event_count + 1
            emit_topic_stream_record(
                {
                    "contract": TOPIC_STREAM_RECORD_CONTRACT,
                    "record_type": "event",
                    "sequence": sequence,
                    "topic": args.api,
                    "event": event.payload,
                    "event_validation": validation.as_dict(),
                },
                sink=stream_sink,
                limit_bytes=result_limit_bytes,
            )
            event_count = sequence
    except KeyboardInterrupt:
        try:
            event_stream.close()
        except BaseException:
            pass
        raise
    except Exception as exc:  # noqa: BLE001 - terminal record preserves the structured error
        primary_error = exc

    try:
        cleanup_succeeded = event_stream.close()
    except Exception as exc:  # noqa: BLE001 - cleanup is reported separately
        cleanup_status = SUBSCRIPTION_CLEANUP_FAILED
        cleanup_failure = cleanup_failure_evidence(exc)
    else:
        cleanup_status = (
            SUBSCRIPTION_CLEANUP_UNSUBSCRIBED
            if cleanup_succeeded
            else SUBSCRIPTION_CLEANUP_FAILED
        )
        if not cleanup_succeeded:
            cleanup_failure = {
                "error_code": "SUBSCRIPTION_CLEANUP_FAILED",
                "message": "Subscription cleanup returned false and remains active",
                "details": {"reason": "unsubscribe_returned_false"},
            }

    terminal: dict[str, Any] = {
        **stream_common,
        "record_type": "terminal",
        "event_count": event_count,
        "elapsed_seconds": max(0.0, time.monotonic() - stream_started_at),
        "cleanup": cleanup_status,
    }
    if primary_error is not None:
        normalized = normalize_gateway_exception(primary_error)
        terminal.update(
            {
                "ok": False,
                "status": "error",
                "error_code": normalized["error_code"],
                "message": normalized["message"],
                "details": normalized.get("details"),
            }
        )
        if cleanup_failure is not None:
            details = (
                dict(terminal["details"])
                if isinstance(terminal.get("details"), Mapping)
                else {}
            )
            details["cleanup_failure"] = cleanup_failure
            terminal["details"] = details
        return terminal
    if cleanup_failure is not None:
        terminal.update(
            {
                "ok": False,
                "status": "error",
                "error_code": "SUBSCRIPTION_CLEANUP_FAILED",
                "message": "Persistent topic stream ended but cleanup did not explicitly succeed.",
                "details": {"cleanup_failure": cleanup_failure},
            }
        )
        return terminal
    terminal.update(
        {
            "ok": True,
            "status": "completed",
            "completion_reason": "duration_elapsed",
        }
    )
    return terminal


def require_topic_stream_health(
    dispatcher: WwiseDispatcher,
    *,
    expected_version: str,
) -> None:
    """Boundedly detect a lost or replaced WAAPI connection during a long stream."""

    call_with_timeout = getattr(dispatcher.client, "call_with_timeout", None)
    if not callable(call_with_timeout):
        raise GatewayInputError(
            "stream-topic transport does not expose the required bounded health check."
        )
    response = call_with_timeout(
        GET_INFO_URI,
        timeout=DEFAULT_TIMEOUT,
        phase="stream-topic health check",
    )
    actual_version = version_key_from_get_info(
        require_mapping(response, "stream-topic health getInfo response")
    )
    if actual_version != expected_version:
        raise GatewayInputError(
            "The WAAPI host version changed during stream-topic: "
            f"expected {expected_version}, got {actual_version}."
        )


def topic_stream_stdout_json_encoder() -> json.JSONEncoder:
    """Build the compact strict encoder used for each flushed stream record."""

    return json.JSONEncoder(
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
        allow_nan=False,
        check_circular=True,
    )


def emit_topic_stream_record(
    record: Mapping[str, Any],
    *,
    sink: Callable[[Mapping[str, Any]], None] | None,
    limit_bytes: int,
) -> None:
    """Validate one compact stream record's size before exposing it."""

    encoder = topic_stream_stdout_json_encoder()
    observed = 1  # stdout adds one newline
    try:
        for chunk in encoder.iterencode(record):
            observed += len(chunk.encode("utf-8"))
            if observed > limit_bytes:
                raise GatewayResultShapeError(
                    "stream-topic record exceeded its JSON output boundary.",
                    details={
                        "limit_bytes": limit_bytes,
                        "observed_at_least_bytes": limit_bytes + 1,
                    },
                    error_code="RESULT_TOO_LARGE",
                )
    except GatewayResultShapeError:
        raise
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise GatewayResultShapeError(
            "stream-topic record is not a strict JSON document.",
            details={"record_type": record.get("record_type")},
            error_code="RESULT_NOT_JSON",
        ) from exc
    if sink is not None:
        sink(record)


def _validated_tab_import_wire_path_input_audit(
    *,
    call_uri: str,
    prepared: Mapping[str, Any],
    import_guard: Mapping[str, Any],
    io_audit: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Bind the one reviewed tab-import read path to dispatch and file proof."""

    if (
        io_audit.get("contract") != WWISE_WIRE_PATH_INPUT_AUDIT_CONTRACT
        or io_audit.get("uri") != call_uri
        or io_audit.get("scope") != "transient_dispatch_read_paths_only"
    ):
        raise WwiseWirePathError(
            "WIRE_PATH_AUDIT_MISMATCH",
            "The tab-delimited import path audit has an unsupported contract, URI, or scope.",
        )
    audit_paths = io_audit.get("paths")
    if not isinstance(audit_paths, list) or len(audit_paths) != 1:
        raise WwiseWirePathError(
            "WIRE_PATH_AUDIT_MISMATCH",
            "The tab-delimited import path audit must contain exactly one path.",
        )
    audit_path = audit_paths[0]
    expected_path_keys = {
        "section",
        "json_path",
        "field",
        "role",
        "raw_path",
        "resolved_path",
    }
    if (
        not isinstance(audit_path, Mapping)
        or set(audit_path) != expected_path_keys
        or audit_path.get("section") != "args"
        or audit_path.get("json_path") != "$.args.importFile"
        or audit_path.get("field") != "importFile"
        or audit_path.get("role") != "read"
    ):
        raise WwiseWirePathError(
            "WIRE_PATH_AUDIT_MISMATCH",
            "The tab-delimited import path audit does not name the reviewed importFile input.",
        )

    dispatch = prepared.get("dispatch")
    dispatch_args = dispatch.get("args") if isinstance(dispatch, Mapping) else None
    import_file = (
        dispatch_args.get("importFile")
        if isinstance(dispatch_args, Mapping)
        else None
    )
    file_proofs = import_guard.get("file_proofs")
    if (
        import_guard.get("source_operation") != "audio.importTabDelimited"
        or not isinstance(dispatch, Mapping)
        or dispatch.get("uri") != call_uri
        or not isinstance(import_file, str)
        or not isinstance(file_proofs, list)
    ):
        raise WwiseWirePathError(
            "WIRE_PATH_AUDIT_MISMATCH",
            "The tab-delimited import path audit is not bound to one prepared importFile proof.",
        )
    import_file_proof_rows = [
        row
        for row in file_proofs
        if isinstance(row, Mapping) and row.get("field") == "import_file"
    ]
    if len(import_file_proof_rows) != 1:
        raise WwiseWirePathError(
            "WIRE_PATH_AUDIT_MISMATCH",
            "The tab-delimited import path audit requires one unique importFile proof.",
        )
    file_proof = import_file_proof_rows[0].get("proof")
    proven_path = file_proof.get("path") if isinstance(file_proof, Mapping) else None
    if (
        not isinstance(proven_path, str)
        or not Path(proven_path).is_absolute()
        or audit_path.get("raw_path") != import_file
        or audit_path.get("resolved_path") != proven_path
        or import_file != proven_path
    ):
        raise WwiseWirePathError(
            "WIRE_PATH_AUDIT_MISMATCH",
            "The tab-delimited import dispatch, path audit, and canonical file proof differ.",
        )
    return io_audit


def prepared_wire_path_io_audit(
    *,
    operation: str,
    call_uri: str,
    prepared: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return the sealed I/O audit for one closed path-bearing dispatch."""

    pre_state = prepared.get("pre_state")
    if not isinstance(pre_state, Mapping):
        raise WwiseWirePathError(
            "WIRE_PATH_AUDIT_MISSING",
            "The authorized preview lacks sealed execution state for path adaptation.",
        )
    import_guard: Mapping[str, Any] | None = None
    if operation == "waapi.call" and call_uri.startswith("ak.wwise.cli."):
        execution_contract = pre_state.get("execution_contract")
        io_audit = (
            execution_contract.get("io_audit")
            if isinstance(execution_contract, Mapping)
            else None
        )
        context = "CLI"
    else:
        expected_uri = NAMED_OPERATION_WIRE_PATH_URIS.get(operation)
        if expected_uri != call_uri:
            raise WwiseWirePathError(
                "WIRE_PATH_OPERATION_MISMATCH",
                "The path-bearing dispatch does not match a reviewed named operation.",
                details={
                    "operation": operation,
                    "uri": call_uri,
                    "expected_uri": expected_uri,
                },
            )
        if operation == "lua.executeCliFile":
            io_audit = pre_state.get("lua_io_audit")
            context = "Lua"
        elif operation == "audio.importTabDelimited":
            import_guard = pre_state.get("import_guard")
            io_audit = (
                import_guard.get("wire_path_input_audit")
                if isinstance(import_guard, Mapping)
                else None
            )
            context = "tab-delimited import"
        else:
            soundbank_guard = pre_state.get("soundbank_guard")
            io_audit = (
                soundbank_guard.get("io_audit")
                if isinstance(soundbank_guard, Mapping)
                else None
            )
            context = "SoundBank"
    if not isinstance(io_audit, Mapping):
        audit_name = (
            "path audit"
            if operation == "audio.importTabDelimited"
            else "isolated-I/O audit"
        )
        raise WwiseWirePathError(
            "WIRE_PATH_AUDIT_MISSING",
            f"The authorized {context} preview lacks its sealed {audit_name}.",
        )
    if operation == "audio.importTabDelimited":
        if not isinstance(import_guard, Mapping):
            raise WwiseWirePathError(
                "WIRE_PATH_AUDIT_MISSING",
                "The authorized tab-delimited import preview lacks its sealed import guard.",
            )
        return _validated_tab_import_wire_path_input_audit(
            call_uri=call_uri,
            prepared=prepared,
            import_guard=import_guard,
            io_audit=io_audit,
        )
    if io_audit.get("uri") != call_uri:
        raise WwiseWirePathError(
            "WIRE_PATH_AUDIT_MISMATCH",
            "The sealed isolated-I/O audit names a different dispatch URI.",
            details={"uri": call_uri, "audit_uri": io_audit.get("uri")},
        )
    return io_audit


def dispatch_operation_draft_check(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Run a bounded live validation, then CAS-publish only check evidence."""

    state_dir = resolve_transaction_state_directory(args, env=env)
    store = OperationDraftStore(state_dir)
    inspected = store.inspect(
        args.draft_id,
        task_authority=args.task_authority,
    )
    schema_digest = operation_draft_schema_digest(
        inspected.operation, inspected.version
    )
    composer_digest = operation_composer_digest(
        inspected.operation,
        inspected.version,
    )
    materialized = store.materialize_request(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
    )
    if materialized.record.version != detected_version:
        raise OperationDraftBindingDrift(
            "Operation Draft version does not match the connected Wwise version.",
            details={
                "draft_version": materialized.record.version,
                "live_version": detected_version,
            },
        )
    request_payload = dict(materialized.request)
    if inspected.operation.startswith("ak."):
        capability = live_capability(
            detected_version,
            inspected.operation,
            live_info=live_info,
        )
        if capability.execution_contract["effect"] == "read":
            arguments = require_mapping(
                request_payload.get("arguments"),
                "typed Draft request arguments",
            )
            request_args = require_mapping(
                arguments.get("args"), "typed Draft request args"
            )
            request_options = require_mapping(
                arguments.get("options"), "typed Draft request options"
            )
            post_filter = media_pool_post_filter_spec_from_args(args)
            if post_filter is not None:
                validate_media_pool_post_filter_request(
                    api=inspected.operation,
                    spec=post_filter,
                    request_args=request_args,
                    request_options=request_options,
                    dry_run=False,
                )
            validation = validate_semantic_payload(
                inspected.operation,
                request_args,
                request_options,
                version=detected_version,
                authoring_ui_profile=live_info.get("isCommandLine") is False,
            )
            result = dispatch(
                dispatcher,
                inspected.operation,
                connection=connection,
                version=detected_version,
                args=request_args,
                options=request_options,
                result_limit_bytes=int(
                    capability.execution_contract["result_limit_bytes"]
                ),
                operation_timeout=float(
                    capability.execution_contract["timeout_seconds"]
                ),
            )
            result_validation = (
                validate_semantic_result(
                    inspected.operation,
                    result.get("result"),
                    version=detected_version,
                    authoring_ui_profile=live_info.get("isCommandLine") is False,
                )
                if result.get("ok")
                else None
            )
            agent_result = result.get("result") if result.get("ok") else None
            post_filter_audit = None
            if post_filter is not None and result.get("ok"):
                agent_result, post_filter_audit = apply_media_pool_post_filter(
                    result.get("result"),
                    spec=post_filter,
                    request_max_results=request_args["maxResults"],
                    evidence_path=result.get("evidence_path"),
                )
                if agent_result is None:
                    return {
                        "contract": GATEWAY_RESULT_CONTRACT,
                        "ok": False,
                        "status": "incomplete_boundary",
                        "command": args.command,
                        "offline": False,
                        **common,
                        "api_attempted": inspected.operation,
                        "error_code": "MEDIA_POOL_POST_FILTER_INCOMPLETE",
                        "message": (
                            "The Media Pool candidate response reached maxResults, so "
                            "the case-sensitive post-filter cannot prove completeness."
                        ),
                        "post_filter": post_filter_audit,
                        "agent_result": None,
                    }
            payload = {
                "contract": GATEWAY_RESULT_CONTRACT,
                "ok": bool(result.get("ok")),
                "status": "ok" if result.get("ok") else "error",
                "command": args.command,
                "offline": False,
                **common,
                "api_attempted": inspected.operation,
                "typed_request": {
                    "contract": "waapi-skill.typed-request/v1",
                    "schema_digest": schema_digest,
                },
                "call": dispatch_call_summary(result),
                "schema_validation": {
                    "request": validation.as_dict(),
                    "result": (
                        result_validation.as_dict()
                        if result_validation is not None
                        else None
                    ),
                },
                "agent_result": agent_result,
            }
            if post_filter_audit is not None:
                payload = {
                    **{key: value for key, value in payload.items() if key != "agent_result"},
                    "post_filter": post_filter_audit,
                    "agent_result": agent_result,
                }
            return payload
    canonical_request = parse_operation_request(
        request_payload,
        expected_version=detected_version,
    )
    authoring_boundary = live_authoring_transaction_boundary(
        request_payload,
        command=args.command,
        live_info=live_info,
        common=common,
    )
    if authoring_boundary is not None:
        return authoring_boundary
    locality_boundary = local_filesystem_transaction_boundary(
        request_payload,
        command=args.command,
        endpoint_host=connection.host,
        common=common,
    )
    if locality_boundary is not None:
        return locality_boundary
    project_guard_mode, target_project_path = transaction_project_guard_spec(
        request_payload,
        version=detected_version,
    )
    project, project_call = current_project(
        dispatcher,
        connection=connection,
        version=detected_version,
        allow_none=project_guard_mode != PROJECT_GUARD_INVARIANT,
    )
    if project is not None:
        require_runtime_directory_outside_project(state_dir, project=project)
    if target_project_path is not None:
        require_runtime_directory_outside_project(
            state_dir,
            project={"path": target_project_path},
        )
    project_guard = build_project_guard(
        endpoint=common["endpoint"],
        version=detected_version,
        live_info=live_info,
        project=project,
        project_guard_mode=project_guard_mode,
        target_project_path=target_project_path,
    )
    read_call = transaction_read_call(
        dispatcher,
        connection=connection,
        version=detected_version,
    )
    read_call = metadata_cached_read_call(
        read_call,
        connection=connection,
        version=detected_version,
        live_info=live_info,
        project=project,
        state_dir=state_dir,
    )
    if canonical_request.operation == OBJECT_SET_COMPOSER_OPERATION:
        read_call = prepare_object_set_composer_check(
            canonical_request,
            read_call=read_call,
        )
    checked_artifact = build_transaction_preview_artifact(
        request_payload,
        live_version=detected_version,
        read_call=read_call,
        project_guard=project_guard,
        skill_root=SKILL_ROOT,
        ttl_seconds=DEFAULT_PREVIEW_TTL_SECONDS,
    ).as_dict()
    prepared = require_mapping(
        checked_artifact.get("prepared_operation"),
        "checked prepared operation",
    )
    runtime_guard = require_mapping(
        checked_artifact.get("runtime_guard"),
        "checked runtime guard",
    )
    runtime_fingerprint = runtime_guard.get("fingerprint")
    if not isinstance(runtime_fingerprint, str):
        raise GatewayInputError("Checked runtime guard lacks its fingerprint")
    record = store.record_check(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        request_digest=materialized.request_digest,
        project_guard=project_guard,
        runtime_guard_fingerprint=runtime_fingerprint,
        prepared_digest=canonical_sha256(prepared),
    )
    payload = operation_draft_payload(
        args.command,
        record,
        offline=False,
    )
    payload.update(
        {
            "endpoint": dict(common["endpoint"]),
            "detected_version": detected_version,
            "is_command_line": common["is_command_line"],
            "project_call": dispatch_call_summary(project_call),
        }
    )
    payload["next_command"] = transaction_next_command(
        "preview-from-draft",
        [
            "preview-from-draft",
            record.draft_id,
            "--task-authority",
            args.task_authority,
            "--expected-revision",
            str(record.revision),
            "--apply",
        ],
    )
    return payload


def dispatch_operation_draft_preview(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Reserve, create/resume through canonical ingress, then commit the seal."""

    state_dir = resolve_transaction_state_directory(args, env=env)
    draft_store = OperationDraftStore(state_dir)
    inspected = draft_store.inspect(
        args.draft_id,
        task_authority=args.task_authority,
    )
    schema_digest = operation_draft_schema_digest(
        inspected.operation, inspected.version
    )
    composer_digest = operation_composer_digest(
        inspected.operation,
        inspected.version,
    )
    if inspected.version != detected_version:
        raise OperationDraftBindingDrift(
            "Operation Draft version does not match the connected Wwise version.",
            details={
                "draft_version": inspected.version,
                "live_version": detected_version,
            },
        )
    policy = load_gateway_config(env).config.project_modification_policy
    reservation: Any | None = None
    reserve_transaction_id: Callable[[], str] | None = None
    if inspected.state is OperationDraftState.EDITABLE:
        materialized = draft_store.materialize_request(
            args.draft_id,
            task_authority=args.task_authority,
            expected_revision=args.expected_revision,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
        )
        check = inspected.check
        if (
            not isinstance(check, Mapping)
            or check.get("source_revision") != inspected.revision - 1
            or check.get("request_digest") != materialized.request_digest
            or check.get("schema_digest") != inspected.schema_digest
            or check.get("composer_digest") != inspected.composer_digest
            or check.get("live_version") != inspected.version
            or not isinstance(check.get("project_guard"), Mapping)
            or not isinstance(check.get("prepared_digest"), str)
            or not isinstance(check.get("runtime_guard_fingerprint"), str)
        ):
            raise OperationDraftCheckRequired(
                "The current Operation Draft revision needs matching successful "
                "live-check evidence before Preview."
            )
        request_payload = materialized.request
        expected_project_guard = check["project_guard"]
        expected_prepared_digest = check["prepared_digest"]
        expected_runtime_guard_fingerprint = check[
            "runtime_guard_fingerprint"
        ]

        def reserve_after_live_validation() -> str:
            nonlocal reservation
            reservation = draft_store.reserve_seal(
                args.draft_id,
                task_authority=args.task_authority,
                expected_revision=args.expected_revision,
                schema_digest=schema_digest,
                composer_digest=composer_digest,
                transaction_id=new_transaction_id(),
                apply=bool(args.apply),
                ttl_seconds=args.ttl,
                policy=policy,
            )
            return reservation.transaction_id

        reserve_transaction_id = reserve_after_live_validation
    else:
        reservation = draft_store.reserve_seal(
            args.draft_id,
            task_authority=args.task_authority,
            expected_revision=args.expected_revision,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
            transaction_id=new_transaction_id(),
            apply=bool(args.apply),
            ttl_seconds=args.ttl,
            policy=policy,
        )
        request_payload = reservation.request
        expected_project_guard = reservation.project_guard
        expected_prepared_digest = reservation.check_prepared_digest
        expected_runtime_guard_fingerprint = (
            reservation.check_runtime_guard_fingerprint
        )
    sealed_transaction_state: str | None = None
    sealed_artifact_hash: str | None = None
    if (
        reservation is not None
        and reservation.record.state is OperationDraftState.SEALED
    ):
        seal = reservation.record.seal
        if not isinstance(seal, Mapping):
            raise OperationDraftSealReplayMismatch(
                "Sealed Operation Draft is missing its durable Preview binding."
            )
        sealed_transaction_state = seal.get("transaction_state")
        sealed_artifact_hash = seal.get("artifact_hash")
        if not isinstance(sealed_transaction_state, str) or not isinstance(
            sealed_artifact_hash, str
        ):
            raise OperationDraftSealReplayMismatch(
                "Sealed Operation Draft has an incomplete durable Preview binding."
            )
        transaction_store = TransactionStore(state_dir)
        try:
            sealed_snapshot = transaction_store.load_snapshot(
                reservation.transaction_id
            )
        except TransactionNotFound as exc:
            raise OperationDraftSealReplayMismatch(
                "Sealed Operation Draft cannot be replayed because its immutable "
                "transaction Preview is missing."
            ) from exc
        _validate_draft_transaction_snapshot(
            snapshot=sealed_snapshot,
            reservation=reservation,
            artifact_hash=sealed_artifact_hash,
            transaction_state=sealed_transaction_state,
            ttl_seconds=args.ttl,
        )
    previewed = create_transaction_preview(
        request_payload,
        args=args,
        env=env,
        connection=connection,
        detected_version=detected_version,
        live_info=live_info,
        dispatcher=dispatcher,
        common=common,
        reserved_transaction_id=(
            None if reservation is None else reservation.transaction_id
        ),
        reserve_transaction_id=reserve_transaction_id,
        expected_project_guard=expected_project_guard,
        expected_policy=policy,
        expected_prepared_digest=expected_prepared_digest,
        expected_runtime_guard_fingerprint=expected_runtime_guard_fingerprint,
        existing_preview_required=(
            reservation is not None
            and reservation.record.state is OperationDraftState.SEALED
        ),
        expected_artifact_hash=sealed_artifact_hash,
        expected_transaction_state=sealed_transaction_state,
    )
    if previewed.get("ok") is not True:
        return previewed
    if reservation is None:
        raise OperationDraftSealReplayMismatch(
            "Canonical ingress completed without publishing the Draft seal reservation."
        )
    transaction_id = previewed.get("transaction_id")
    artifact_hash = previewed.get("artifact_hash")
    transaction_state = previewed.get("state")
    if (
        transaction_id != reservation.transaction_id
        or not isinstance(artifact_hash, str)
        or not isinstance(transaction_state, str)
    ):
        raise OperationDraftSealReplayMismatch(
            "Canonical ingress returned a different reserved Preview binding."
        )
    transaction_store = TransactionStore(state_dir)
    snapshot = transaction_store.load_snapshot(reservation.transaction_id)
    _validate_draft_transaction_snapshot(
        snapshot=snapshot,
        reservation=reservation,
        artifact_hash=artifact_hash,
        transaction_state=transaction_state,
        ttl_seconds=args.ttl,
    )
    draft_store.commit_seal(
        args.draft_id,
        task_authority=args.task_authority,
        source_revision=reservation.source_revision,
        transaction_id=reservation.transaction_id,
        artifact_hash=artifact_hash,
        transaction_state=transaction_state,
    )
    return previewed


def create_transaction_preview(
    request_payload: Mapping[str, Any],
    *,
    args: argparse.Namespace,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
    reserved_transaction_id: str | None = None,
    reserve_transaction_id: Callable[[], str] | None = None,
    expected_project_guard: Mapping[str, Any] | None = None,
    expected_policy: str | None = None,
    expected_prepared_digest: str | None = None,
    expected_runtime_guard_fingerprint: str | None = None,
    existing_preview_required: bool = False,
    expected_artifact_hash: str | None = None,
    expected_transaction_state: str | None = None,
) -> dict[str, Any]:
    """Create one durable Preview from raw canonical operation-request JSON.

    This is the single production ingress shared by every current or future
    request Adapter.  It owns the complete fail-fast host/locality checks,
    project and runtime guards, canonical reparse/preparation, immutable store
    write, authorization state, and bounded review result.
    """

    if reserved_transaction_id is not None and reserve_transaction_id is not None:
        raise ValueError(
            "reserved_transaction_id and reserve_transaction_id are mutually exclusive"
        )
    if not isinstance(request_payload, Mapping) or (
        request_payload.get("contract")
        in {PREPARED_OPERATION_CONTRACT, TRANSACTION_PREVIEW_CONTRACT}
        or "prepared_operation" in request_payload
    ):
        raise GatewayInputError(
            "Transaction preview ingress requires one raw canonical "
            "operation-request JSON object; parsed, prepared, and Preview "
            "objects cannot bypass canonical reparse."
        )

    authoring_boundary = live_authoring_transaction_boundary(
        request_payload,
        command=args.command,
        live_info=live_info,
        common=common,
    )
    if authoring_boundary is not None:
        return authoring_boundary
    locality_boundary = local_filesystem_transaction_boundary(
        request_payload,
        command=args.command,
        endpoint_host=connection.host,
        common=common,
    )
    if locality_boundary is not None:
        return locality_boundary

    # Every request that reaches Preview construction is reparsed here.  The
    # artifact builder below repeats that parse at the immutable seam.  The
    # raw host/locality boundaries intentionally precede semantic parsing so
    # unavailable-host and remote-filesystem failures remain fail-fast.
    canonical_request = parse_operation_request(
        request_payload,
        expected_version=detected_version,
    ).as_dict()
    project_guard_mode, target_project_path = transaction_project_guard_spec(
        canonical_request,
        version=detected_version,
    )
    project, project_call = current_project(
        dispatcher,
        connection=connection,
        version=detected_version,
        allow_none=project_guard_mode != PROJECT_GUARD_INVARIANT,
    )
    state_dir = resolve_transaction_state_directory(args, env=env)
    if project is not None:
        require_runtime_directory_outside_project(state_dir, project=project)
    if target_project_path is not None:
        require_runtime_directory_outside_project(
            state_dir,
            project={"path": target_project_path},
        )
    project_guard = build_project_guard(
        endpoint=common["endpoint"],
        version=detected_version,
        live_info=live_info,
        project=project,
        project_guard_mode=project_guard_mode,
        target_project_path=target_project_path,
    )
    if expected_project_guard is not None and (
        not isinstance(expected_project_guard, Mapping)
        or dict(expected_project_guard) != project_guard
    ):
        raise OperationDraftBindingDrift(
            "Live project/runtime context changed after the Operation Draft check."
        )
    current_policy = load_gateway_config(env).config.project_modification_policy
    if expected_policy is not None and current_policy != expected_policy:
        raise OperationDraftSealReplayMismatch(
            "Project modification policy changed after the seal reservation.",
            details={
                "reserved_policy": expected_policy,
                "current_policy": current_policy,
            },
        )
    if args.apply and current_policy == "read_only":
        raise GatewayInputError(
            "project_modification_policy=read_only blocks transaction "
            "requested project change"
        )
    store = TransactionStore(state_dir)
    if reserved_transaction_id is not None:
        try:
            existing_snapshot = store.load_snapshot(reserved_transaction_id)
        except TransactionNotFound:
            existing_snapshot = None
        if existing_snapshot is not None:
            return _resume_reserved_transaction_preview(
                snapshot=existing_snapshot,
                store=store,
                canonical_request=canonical_request,
                project_guard=project_guard,
                ttl_seconds=args.ttl,
                apply=bool(args.apply),
                policy=current_policy,
                common=common,
                project_call=project_call,
                expected_prepared_digest=expected_prepared_digest,
                expected_runtime_guard_fingerprint=(
                    expected_runtime_guard_fingerprint
                ),
                expected_artifact_hash=expected_artifact_hash,
                expected_transaction_state=expected_transaction_state,
            )
        if existing_preview_required:
            raise OperationDraftSealReplayMismatch(
                "Sealed Operation Draft cannot be replayed because its immutable "
                "transaction Preview is missing."
            )
    read_call = transaction_read_call(
        dispatcher,
        connection=connection,
        version=detected_version,
    )
    read_call = metadata_cached_read_call(
        read_call,
        connection=connection,
        version=detected_version,
        live_info=live_info,
        project=project,
        state_dir=state_dir,
    )
    artifact = build_transaction_preview_artifact(
        request_payload,
        live_version=detected_version,
        read_call=read_call,
        project_guard=project_guard,
        skill_root=SKILL_ROOT,
        ttl_seconds=args.ttl,
    ).as_dict()
    prepared = require_mapping(
        artifact.get("prepared_operation"),
        "prepared operation",
    )
    pre_state = require_mapping(
        prepared.get("pre_state"),
        "prepared pre-state",
    )
    sealed_contract = pre_state.get("execution_contract")
    if (
        isinstance(sealed_contract, Mapping)
        and sealed_contract.get("effect") == "read"
    ):
        if sealed_read_transaction_contract(artifact) is None:
            raise GatewayInputError(
                "Read transaction preview did not match its current packaged "
                "execution contract."
            )
        if args.apply:
            raise GatewayInputError(
                "preview --apply is reserved for project or process changes; "
                "omit --apply for this read transaction."
            )
    if (
        expected_prepared_digest is not None
        and canonical_sha256(prepared) != expected_prepared_digest
    ):
        raise OperationDraftBindingDrift(
            "Live identity, metadata, or pre-state changed after the Operation Draft check."
        )
    runtime_guard = require_mapping(artifact.get("runtime_guard"), "runtime guard")
    if (
        expected_runtime_guard_fingerprint is not None
        and runtime_guard.get("fingerprint") != expected_runtime_guard_fingerprint
    ):
        raise OperationDraftBindingDrift(
            "Packaged runtime changed after the Operation Draft check."
        )
    transaction_id = (
        reserved_transaction_id
        or (reserve_transaction_id() if reserve_transaction_id is not None else None)
        or new_transaction_id()
    )
    try:
        created = store.create_preview(transaction_id, artifact)
    except PreviewAlreadyExists:
        if reserved_transaction_id is None:
            raise
        existing_snapshot = store.load_snapshot(transaction_id)
        return _resume_reserved_transaction_preview(
            snapshot=existing_snapshot,
            store=store,
            canonical_request=canonical_request,
            project_guard=project_guard,
            ttl_seconds=args.ttl,
            apply=bool(args.apply),
            policy=current_policy,
            common=common,
            project_call=project_call,
            candidate_artifact=artifact,
            expected_prepared_digest=expected_prepared_digest,
            expected_runtime_guard_fingerprint=(
                expected_runtime_guard_fingerprint
            ),
        )
    operation = canonical_request.get("operation")
    confirmation_only = operation in EXPLICIT_CONFIRMATION_ONLY_OPERATIONS
    if args.apply and current_policy == "allow_changes" and not confirmation_only:
        transaction = store.authorize_by_policy(
            transaction_id,
            policy="allow_changes",
            authority=POLICY_AUTHORIZATION_AUTHORITY,
        )
        authorization = {
            "mode": AUTHORIZATION_MODE_POLICY,
            "policy": "allow_changes",
            "authority": POLICY_AUTHORIZATION_AUTHORITY,
            "explicit_confirmation": False,
            "notice_required": True,
        }
        next_command = transaction_next_command(
            "execute",
            ["execute", transaction_id],
        )
        status = TransactionState.POLICY_AUTHORIZED.value
    else:
        transaction = store.submit_for_confirmation(transaction_id)
        authorization = {
            "mode": AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,
            "policy": current_policy,
            "explicit_confirmation": False,
            "notice_required": True,
            "requires_later_user_message": True,
        }
        if confirmation_only:
            authorization["reason"] = "dangerous_host_control_requires_confirmation"
        next_command = transaction_next_command(
            "transaction-show",
            ["transaction-show", transaction_id, "--summary-only"],
            requires_later_user_message=True,
        )
        status = TransactionState.AWAITING_CONFIRMATION.value
    cleanup = transaction_cleanup_payload(prepared, phase="preview")
    try:
        review = transaction_show_summary(
            artifact,
            store.read_events(transaction_id),
        )
    except GatewayResultShapeError as exc:
        exc.details.update(
            {
                "transaction_id": transaction_id,
                "state": transaction.state.value,
                "artifact_hash": created.artifact_hash,
            }
        )
        raise
    project_call_summary = (
        dispatch_call_summary(project_call)
        if isinstance(project_call, Mapping)
        else None
    )
    agent_result = transaction_agent_result(
        request=require_mapping(artifact.get("request"), "transaction request"),
        transaction_id=transaction_id,
        artifact_hash=created.artifact_hash,
        state=transaction.state.value,
        executed=False,
        authorization=authorization,
        cleanup=cleanup,
        next_command=next_command,
    )
    return {
        "ok": True,
        "status": status,
        **common,
        "transaction_id": transaction_id,
        "state": transaction.state.value,
        "artifact_hash": created.artifact_hash,
        **review,
        "project_call": project_call_summary,
        "executed": False,
        "verified": False,
        "change_requested": bool(args.apply),
        "authorization": authorization,
        "cleanup": cleanup,
        "next_command": next_command,
        "agent_result": agent_result,
    }


def _resume_reserved_transaction_preview(
    *,
    snapshot: Any,
    store: TransactionStore,
    canonical_request: Mapping[str, Any],
    project_guard: Mapping[str, Any],
    ttl_seconds: int,
    apply: bool,
    policy: str,
    common: Mapping[str, Any],
    project_call: Mapping[str, Any],
    candidate_artifact: Mapping[str, Any] | None = None,
    expected_prepared_digest: str | None = None,
    expected_runtime_guard_fingerprint: str | None = None,
    expected_artifact_hash: str | None = None,
    expected_transaction_state: str | None = None,
) -> dict[str, Any]:
    """Resume one reserved immutable Preview without allocating another id."""

    artifact = snapshot.preview.artifact
    if not isinstance(artifact, Mapping):
        raise OperationDraftSealReplayMismatch(
            "Reserved transaction Preview is not a JSON object."
        )
    if (
        artifact.get("request") != canonical_request
        or artifact.get("project_guard") != project_guard
        or _preview_artifact_ttl_seconds(artifact) != ttl_seconds
    ):
        raise OperationDraftSealReplayMismatch(
            "Reserved transaction Preview does not match the durable Draft seal."
        )
    prepared = artifact.get("prepared_operation")
    runtime_guard = artifact.get("runtime_guard")
    if not isinstance(prepared, Mapping) or not isinstance(runtime_guard, Mapping):
        raise OperationDraftSealReplayMismatch(
            "Reserved transaction is missing its checked prepared/runtime binding."
        )
    if (
        expected_prepared_digest is not None
        and canonical_sha256(prepared) != expected_prepared_digest
    ):
        raise OperationDraftSealReplayMismatch(
            "Reserved transaction prepared state differs from the checked Draft."
        )
    if (
        expected_runtime_guard_fingerprint is not None
        and runtime_guard.get("fingerprint")
        != expected_runtime_guard_fingerprint
    ):
        raise OperationDraftSealReplayMismatch(
            "Reserved transaction runtime differs from the checked Draft."
        )
    if candidate_artifact is not None and _preview_artifact_replay_core(
        artifact
    ) != _preview_artifact_replay_core(candidate_artifact):
        raise OperationDraftSealReplayMismatch(
            "Concurrent seal preparation disagreed with the immutable reserved Preview."
        )
    if (
        expected_artifact_hash is not None
        and snapshot.preview.artifact_hash != expected_artifact_hash
    ):
        raise OperationDraftSealReplayMismatch(
            "Reserved transaction artifact hash differs from the sealed Draft."
        )
    transaction_id = snapshot.record.transaction_id
    operation = canonical_request.get("operation")
    confirmation_only = operation in EXPLICIT_CONFIRMATION_ONLY_OPERATIONS
    desired_state = (
        TransactionState.POLICY_AUTHORIZED
        if apply and policy == "allow_changes" and not confirmation_only
        else TransactionState.AWAITING_CONFIRMATION
    )
    record = snapshot.record
    if (
        expected_transaction_state is not None
        and record.state.value != expected_transaction_state
    ):
        raise OperationDraftSealReplayMismatch(
            "Reserved transaction state differs from the sealed Draft.",
            details={
                "expected_state": expected_transaction_state,
                "actual_state": record.state.value,
            },
        )
    if record.state is TransactionState.DRAFT:
        if desired_state is TransactionState.POLICY_AUTHORIZED:
            record = store.authorize_by_policy(
                transaction_id,
                policy="allow_changes",
                authority=POLICY_AUTHORIZATION_AUTHORITY,
            )
        else:
            record = store.submit_for_confirmation(transaction_id)
    elif record.state is not desired_state:
        raise OperationDraftSealReplayMismatch(
            "Reserved transaction already advanced to an incompatible state.",
            details={
                "expected_state": desired_state.value,
                "actual_state": record.state.value,
            },
        )
    if desired_state is TransactionState.POLICY_AUTHORIZED:
        authorization = {
            "mode": AUTHORIZATION_MODE_POLICY,
            "policy": "allow_changes",
            "authority": POLICY_AUTHORIZATION_AUTHORITY,
            "explicit_confirmation": False,
            "notice_required": True,
        }
        next_command = transaction_next_command(
            "execute",
            ["execute", transaction_id],
        )
    else:
        authorization = {
            "mode": AUTHORIZATION_MODE_EXPLICIT_CONFIRMATION,
            "policy": policy,
            "explicit_confirmation": False,
            "notice_required": True,
            "requires_later_user_message": True,
        }
        if confirmation_only:
            authorization["reason"] = "dangerous_host_control_requires_confirmation"
        next_command = transaction_next_command(
            "transaction-show",
            ["transaction-show", transaction_id, "--summary-only"],
            requires_later_user_message=True,
        )
    cleanup = transaction_cleanup_payload(prepared, phase="preview")
    events = store.read_events(transaction_id)
    review = transaction_show_summary(artifact, events)
    agent_result = transaction_agent_result(
        request=require_mapping(artifact.get("request"), "transaction request"),
        transaction_id=transaction_id,
        artifact_hash=snapshot.preview.artifact_hash,
        state=record.state.value,
        executed=False,
        authorization=authorization,
        cleanup=cleanup,
        next_command=next_command,
    )
    return {
        "ok": True,
        "status": record.state.value,
        **common,
        "transaction_id": transaction_id,
        "state": record.state.value,
        "artifact_hash": snapshot.preview.artifact_hash,
        **review,
        "project_call": dispatch_call_summary(project_call),
        "executed": False,
        "verified": False,
        "change_requested": apply,
        "authorization": authorization,
        "cleanup": cleanup,
        "next_command": next_command,
        "agent_result": agent_result,
    }


def _validate_draft_transaction_snapshot(
    *,
    snapshot: Any,
    reservation: Any,
    artifact_hash: str,
    transaction_state: str,
    ttl_seconds: int,
) -> None:
    """Require the exact immutable transaction bound to one Draft reservation."""

    artifact = snapshot.preview.artifact
    if not isinstance(artifact, Mapping):
        raise OperationDraftSealReplayMismatch(
            "Operation Draft transaction Preview is not a JSON object."
        )
    prepared = artifact.get("prepared_operation")
    runtime_guard = artifact.get("runtime_guard")
    if not isinstance(prepared, Mapping) or not isinstance(runtime_guard, Mapping):
        raise OperationDraftSealReplayMismatch(
            "Draft transaction is missing its checked prepared/runtime binding."
        )
    if (
        snapshot.preview.artifact_hash != artifact_hash
        or snapshot.record.state.value != transaction_state
        or artifact.get("request") != reservation.request
        or artifact.get("project_guard") != reservation.project_guard
        or _preview_artifact_ttl_seconds(artifact) != ttl_seconds
        or canonical_sha256(prepared) != reservation.check_prepared_digest
        or runtime_guard.get("fingerprint")
        != reservation.check_runtime_guard_fingerprint
    ):
        raise OperationDraftSealReplayMismatch(
            "Immutable transaction state does not match the durable Draft binding."
        )


def _preview_artifact_ttl_seconds(artifact: Mapping[str, Any]) -> int | None:
    created_at = artifact.get("created_at")
    expires_at = artifact.get("expires_at")
    if not isinstance(created_at, str) or not isinstance(expires_at, str):
        return None
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    seconds = (expires - created).total_seconds()
    return int(seconds) if seconds.is_integer() and seconds > 0 else None


def _preview_artifact_replay_core(
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        key: value
        for key, value in artifact.items()
        if key not in {"created_at", "expires_at"}
    }


def dispatch_transaction_command(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    read_call = transaction_read_call(
        dispatcher,
        connection=connection,
        version=detected_version,
    )

    store = resolve_transaction_store(args, env=env)
    transaction_id = args.transaction_id
    record = store.load(transaction_id)
    preview = store.load_preview(transaction_id)
    artifact = preview.artifact
    if not isinstance(artifact, Mapping):
        raise GatewayInputError("transaction preview artifact must be a JSON object")
    prepared = require_mapping(artifact.get("prepared_operation"), "prepared operation")
    sealed_request = require_mapping(artifact.get("request"), "transaction request")
    authoring_boundary = live_authoring_transaction_boundary(
        sealed_request,
        command=args.command,
        live_info=live_info,
        common=common,
    )
    if authoring_boundary is not None:
        return authoring_boundary
    locality_boundary = local_filesystem_transaction_boundary(
        sealed_request,
        command=args.command,
        endpoint_host=connection.host,
        common=common,
    )
    if locality_boundary is not None:
        return locality_boundary
    if record.state is TransactionState.EXECUTING:
        recovered = store.mark_execution_indeterminate(
            transaction_id,
            details={
                "reason": "A previous process stopped after execution_started without recording a result.",
                "automatic_retry": False,
            },
        )
        return {
            "ok": False,
            "status": "indeterminate",
            **common,
            "transaction_id": transaction_id,
            "state": recovered.state.value,
            "message": "The previous execution attempt is indeterminate and will not be retried automatically.",
            "cleanup": transaction_cleanup_payload(prepared, phase="indeterminate"),
            "automatic_retry": False,
        }

    if args.command == "execute":
        if record.state not in {
            TransactionState.CONFIRMED,
            TransactionState.POLICY_AUTHORIZED,
        }:
            raise InvalidTransition(
                f"Transaction {transaction_id!r} must be explicitly confirmed or "
                "policy-authorized before execution; "
                f"current state is {record.state.value!r}."
            )
        authorization_events = store.read_events(transaction_id)
        authorization = transaction_authorization(
            record=record,
            events=authorization_events,
        )
        current_policy = load_gateway_config(env).config.project_modification_policy
        if (
            record.state is TransactionState.POLICY_AUTHORIZED
            and current_policy != "allow_changes"
        ):
            repreview = store.require_repreview(
                transaction_id,
                expected_authorization=record.state,
                details={
                    "error_code": "PROJECT_MODIFICATION_POLICY_CHANGED",
                    "authorized_policy": "allow_changes",
                    "current_policy": current_policy,
                    "executed": False,
                },
            )
            return {
                "ok": False,
                "status": "repreview_required",
                **common,
                "transaction_id": transaction_id,
                "state": repreview.state.value,
                "error_code": "PROJECT_MODIFICATION_POLICY_CHANGED",
                "message": (
                    "The transaction was authorized by allow_changes, but the "
                    f"current policy is {current_policy}; create a new preview."
                ),
                "authorization": {
                    **authorization,
                    "current_policy": current_policy,
                },
                "executed": False,
                "verified": False,
                "cleanup": transaction_cleanup_payload(prepared, phase="preview"),
            }
        request_payload = require_mapping(artifact.get("request"), "transaction request")
        project_guard_mode, target_project_path = transaction_project_guard_spec(
            request_payload,
            version=detected_version,
        )
        project, project_call = current_project(
            dispatcher,
            connection=connection,
            version=detected_version,
            allow_none=project_guard_mode != PROJECT_GUARD_INVARIANT,
        )
        current_guard = build_project_guard(
            endpoint=common["endpoint"],
            version=detected_version,
            live_info=live_info,
            project=project,
            project_guard_mode=project_guard_mode,
            target_project_path=target_project_path,
        )
        try:
            guard_validation = validate_transaction_guards(
                artifact,
                current_project_guard=current_guard,
                skill_root=SKILL_ROOT,
            )
        except TransactionGuardError as exc:
            repreview = store.require_repreview(
                transaction_id,
                expected_authorization=record.state,
                details=exc.as_dict(),
            )
            return {
                "ok": False,
                "status": "repreview_required",
                **common,
                "transaction_id": transaction_id,
                "state": repreview.state.value,
                "error_code": exc.error_code,
                "message": str(exc),
                "details": exc.details,
                "guard_validation": exc.as_dict(),
                "executed": False,
                "verified": False,
                "cleanup": transaction_cleanup_payload(prepared, phase="preview"),
            }
        role_validation = validate_prepared_roles(prepared, read_call=read_call)
        if role_validation.get("ok") is not True:
            repreview = store.require_repreview(
                transaction_id,
                expected_authorization=record.state,
                details={"error_code": "ROLE_GUARD_MISMATCH", "role_validation": role_validation},
            )
            return {
                "ok": False,
                "status": "repreview_required",
                **common,
                "transaction_id": transaction_id,
                "state": repreview.state.value,
                "error_code": "ROLE_GUARD_MISMATCH",
                "role_validation": role_validation,
                "executed": False,
                "verified": False,
                "cleanup": transaction_cleanup_payload(prepared, phase="preview"),
            }
        dispatch_payload = require_mapping(prepared.get("dispatch"), "prepared dispatch")
        operation = str(request_payload.get("operation"))
        spec = describe_operation(operation)
        call_uri = dispatch_payload.get("uri")
        if not isinstance(call_uri, str):
            raise OperationContractError(
                "PREVIEW_DISPATCH_MISMATCH",
                "Immutable prepared dispatch lacks a WAAPI URI.",
            )
        if operation != "waapi.call" and call_uri != spec.uri:
            raise OperationContractError(
                "PREVIEW_DISPATCH_MISMATCH",
                "Immutable prepared dispatch URI does not match its closed operation registry entry.",
                details={"operation": operation, "expected": spec.uri, "actual": dispatch_payload.get("uri")},
            )
        capability = live_capability(
            detected_version,
            call_uri,
            live_info=live_info,
        )
        read_transaction_contract = sealed_read_transaction_contract(artifact)
        if (
            capability.execution_contract.get("effect") == "read"
            and read_transaction_contract is None
        ):
            raise OperationContractError(
                "PREVIEW_DISPATCH_MISMATCH",
                "Immutable read transaction no longer matches its sealed and "
                "current packaged execution contract.",
                details={
                    "operation": operation,
                    "uri": call_uri,
                },
            )
        if operation == "waapi.call" and capability.preferred_route != "transaction_operation":
            raise OperationContractError(
                "PREVIEW_DISPATCH_MISMATCH",
                "waapi.call preview no longer resolves to a reviewed transaction route.",
                details={"operation": operation, "uri": call_uri, "route": capability.preferred_route},
            )
        if operation == "waapi.undoGroup":
            request_arguments = request_payload.get("arguments")
            if not isinstance(request_arguments, Mapping):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Immutable waapi.undoGroup request lacks its arguments object.",
                )
            request_plan = build_undo_group_execution_plan(
                detected_version,
                request_arguments,
            )
            stored_pre_state = prepared.get("pre_state")
            stored_plan = (
                stored_pre_state.get("execution_plan")
                if isinstance(stored_pre_state, Mapping)
                else None
            )
            if not isinstance(stored_plan, Mapping):
                raise OperationContractError(
                    "PREVIEW_DISPATCH_MISMATCH",
                    "Immutable waapi.undoGroup execution plan is missing.",
                )
            stored_calls = stored_plan.get("calls")
            request_calls = request_plan.get("calls")
            binding_keys = (
                "child_operation", "child_request", "child_schema_digest", "api",
                "timeout_seconds", "result_limit_bytes",
            )
            plan_bound = (
                isinstance(stored_calls, list)
                and isinstance(request_calls, list)
                and len(stored_calls) == len(request_calls)
                and stored_plan.get("begin") == request_plan.get("begin")
                and stored_plan.get("end") == request_plan.get("end")
                and stored_plan.get("cancel") == request_plan.get("cancel")
                and all(
                    isinstance(stored, Mapping)
                    and all(stored.get(key) == requested.get(key) for key in binding_keys)
                    for stored, requested in zip(stored_calls, request_calls, strict=True)
                )
            )
            if not plan_bound:
                raise OperationContractError(
                    "PREVIEW_DISPATCH_MISMATCH",
                    "Immutable waapi.undoGroup execution plan no longer matches its request.",
                )
            execution_plan = stored_plan
            role_validation_output = undo_group_role_validation_summary(role_validation)
            authorization = require_transaction_execution_authorization(
                record=record,
                events=authorization_events,
                env=env,
                read_only_transaction=False,
            )
            store.begin_execution(
                transaction_id,
                expected_authorization=record.state,
            )
            try:
                compound = dispatch_undo_group_execution_plan(
                    dispatcher,
                    connection=connection,
                    version=detected_version,
                    execution_plan=execution_plan,
                )
            except Exception as exc:  # noqa: BLE001 - begin may already have reached Wwise
                indeterminate = store.mark_execution_indeterminate(
                    transaction_id,
                    details={
                        "reason": "exception during same-connection Undo Group execution",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                        "automatic_retry": False,
                    },
                )
                return {
                    "ok": False,
                    "status": "indeterminate",
                    **common,
                    "transaction_id": transaction_id,
                    "state": indeterminate.state.value,
                    "message": str(exc),
                    "same_connection": True,
                    "cleanup": transaction_cleanup_payload(prepared, phase="indeterminate"),
                    "automatic_retry": False,
                }
            if compound["status"] == "execution_cancelled":
                cancelled = store.mark_execution_cancelled(
                    transaction_id,
                    details={"compound_execution": compound, "automatic_retry": False},
                )
                return {
                    "ok": False,
                    "status": "execution_cancelled",
                    **common,
                    "transaction_id": transaction_id,
                    "state": cancelled.state.value,
                    "artifact_hash": preview.artifact_hash,
                    "compound_execution": compound,
                    "role_validation": role_validation_output,
                    "guard_validation": guard_validation,
                    "project_call": project_call,
                    "executed": True,
                    "cancelled": True,
                    "rollback_verified": False,
                    "verified": False,
                    "cleanup": transaction_cleanup_payload(prepared, phase="execution_cancelled"),
                    "automatic_retry": False,
                }
            if compound["status"] == "indeterminate":
                indeterminate = store.mark_execution_indeterminate(
                    transaction_id,
                    details={"compound_execution": compound, "automatic_retry": False},
                )
                return {
                    "ok": False,
                    "status": "indeterminate",
                    **common,
                    "transaction_id": transaction_id,
                    "state": indeterminate.state.value,
                    "artifact_hash": preview.artifact_hash,
                    "compound_execution": compound,
                    "role_validation": role_validation_output,
                    "guard_validation": guard_validation,
                    "project_call": project_call,
                    "executed": True,
                    "verified": False,
                    "cleanup": transaction_cleanup_payload(prepared, phase="indeterminate"),
                    "automatic_retry": False,
                }
            result = require_mapping(compound.get("dispatch_result"), "Undo Group dispatch result")
            compound_summary = {
                "status": compound["status"],
                "same_connection": compound["same_connection"],
                "automatic_retry": compound["automatic_retry"],
                "phase_count": len(
                    require_mapping(result.get("result"), "Undo Group result").get("phases", ())
                ),
                "authoritative_phases": "dispatch_result.result.phases",
            }
            try:
                executed = store.mark_executed_unverified(
                    transaction_id,
                    details={"dispatch_result": result, "automatic_retry": False},
                )
            except Exception as exc:  # noqa: BLE001 - same-session success must not become replayable
                persistence_payload = execution_success_persistence_failure_payload(
                    common,
                    store=store,
                    transaction_id=transaction_id,
                    artifact_hash=preview.artifact_hash,
                    prepared=prepared,
                    dispatch_result=result,
                    exc=exc,
                )
                persistence_payload.update(
                    {
                        "compound_execution": compound_summary,
                        "role_validation": role_validation_output,
                        "guard_validation": guard_validation,
                        "project_call": project_call,
                        "same_connection": True,
                    }
                )
                return persistence_payload
            return {
                "ok": True,
                "status": "executed_unverified",
                **common,
                "transaction_id": transaction_id,
                "state": executed.state.value,
                "artifact_hash": preview.artifact_hash,
                "dispatch_result": result,
                "compound_execution": compound_summary,
                "role_validation": role_validation_output,
                "guard_validation": guard_validation,
                "project_call": project_call,
                "executed": True,
                "verified": False,
                "same_connection": True,
                "cleanup": transaction_cleanup_payload(
                    prepared,
                    phase="executed",
                    execution_result=result,
                ),
                "automatic_retry": False,
                "next_command": transaction_next_command(
                    "verify",
                    ["verify", transaction_id],
                ),
            }
        call_args = require_mapping(dispatch_payload.get("args", {}), "prepared dispatch args")
        call_options = require_mapping(dispatch_payload.get("options", {}), "prepared dispatch options")
        schema_validation = validate_semantic_payload(
            call_uri,
            call_args,
            call_options,
            version=detected_version,
            authoring_ui_profile=live_info.get("isCommandLine") is False,
        )
        verification_plan = require_mapping(
            prepared.get("verification_plan"),
            "prepared verification plan",
        )
        if verification_plan.get("kind") == "host-control-terminal":
            return dispatch_host_control_transaction(
                env=env,
                connection=connection,
                detected_version=detected_version,
                dispatcher=dispatcher,
                common=common,
                store=store,
                transaction_id=transaction_id,
                artifact_hash=preview.artifact_hash,
                prepared=prepared,
                call_uri=call_uri,
                call_args=call_args,
                call_options=call_options,
                capability=capability,
                schema_validation=schema_validation.as_dict(),
                role_validation=role_validation,
                guard_validation=guard_validation,
                project_call=project_call,
                verification_plan=verification_plan,
            )
        runtime_call_args = call_args
        runtime_call_options = call_options
        wire_path_adaptation: Mapping[str, Any] | None = None
        if requires_wwise_wire_path_adaptation(call_uri):
            sealed_project_guard = artifact.get("project_guard")
            try:
                io_audit = prepared_wire_path_io_audit(
                    operation=operation,
                    call_uri=call_uri,
                    prepared=prepared,
                )
                if not isinstance(sealed_project_guard, Mapping):
                    raise WwiseWirePathError(
                        "WIRE_PATH_CONTEXT_UNAVAILABLE",
                        "The authorized path-bearing preview lacks its sealed project guard.",
                    )
                adapted_dispatch = adapt_cli_dispatch_paths(
                    uri=call_uri,
                    args=call_args,
                    options=call_options,
                    io_audit=io_audit,
                    project_guard=sealed_project_guard,
                    current_project_guard=current_guard,
                )
            except WwiseWirePathError as exc:
                adaptation_error = exc.as_dict()
                repreview = store.require_repreview(
                    transaction_id,
                    expected_authorization=record.state,
                    details={
                        "error_code": exc.error_code,
                        "wire_path_adaptation": adaptation_error,
                    },
                )
                return {
                    "ok": False,
                    "status": "repreview_required",
                    **common,
                    "transaction_id": transaction_id,
                    "state": repreview.state.value,
                    "artifact_hash": preview.artifact_hash,
                    "error_code": exc.error_code,
                    "message": str(exc),
                    "details": exc.details,
                    "schema_validation": schema_validation.as_dict(),
                    "wire_path_adaptation": adaptation_error,
                    "role_validation": role_validation,
                    "guard_validation": guard_validation,
                    "project_call": project_call,
                    "executed": False,
                    "verified": False,
                    "cleanup": transaction_cleanup_payload(prepared, phase="preview"),
                    "automatic_retry": False,
                }
            runtime_call_args = adapted_dispatch.args
            runtime_call_options = adapted_dispatch.options
            wire_path_adaptation = adapted_dispatch.proof
        wire_path_output = (
            {"wire_path_adaptation": dict(wire_path_adaptation)}
            if wire_path_adaptation is not None
            else {}
        )
        # Re-read at the final mutation boundary as well as before connecting.
        # A policy change during live guard validation must still stop execution.
        authorization = require_transaction_execution_authorization(
            record=record,
            events=authorization_events,
            env=env,
            read_only_transaction=read_transaction_contract is not None,
        )
        store.begin_execution(
            transaction_id,
            expected_authorization=record.state,
        )
        try:
            result = dispatch(
                dispatcher,
                call_uri,
                connection=connection,
                version=detected_version,
                args=runtime_call_args,
                options=runtime_call_options,
                allow_destructive=True,
                operation_timeout=float(capability.execution_contract["timeout_seconds"]),
                result_limit_bytes=int(capability.execution_contract["result_limit_bytes"]),
            )
        except Exception as exc:  # noqa: BLE001 - execution may already have reached Wwise
            indeterminate = store.mark_execution_indeterminate(
                transaction_id,
                details={
                    "reason": "exception after execution_started",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "automatic_retry": False,
                    **wire_path_output,
                },
            )
            return {
                "ok": False,
                "status": "indeterminate",
                **common,
                "transaction_id": transaction_id,
                "state": indeterminate.state.value,
                "message": str(exc),
                **wire_path_output,
                "cleanup": transaction_cleanup_payload(prepared, phase="indeterminate"),
                "automatic_retry": False,
            }
        if result.get("ok") is not True:
            indeterminate = store.mark_execution_indeterminate(
                transaction_id,
                details={
                    "dispatch_result": result,
                    "automatic_retry": False,
                    **wire_path_output,
                },
            )
            return {
                "ok": False,
                "status": "indeterminate",
                **common,
                "transaction_id": transaction_id,
                "state": indeterminate.state.value,
                "dispatch_result": result,
                **wire_path_output,
                "role_validation": role_validation,
                "guard_validation": guard_validation,
                "cleanup": transaction_cleanup_payload(
                    prepared,
                    phase="indeterminate",
                    execution_result=result,
                ),
                "automatic_retry": False,
            }
        try:
            executed = store.mark_executed_unverified(
                transaction_id,
                details={
                    "dispatch_result": result,
                    "schema_validation": schema_validation.as_dict(),
                    "role_validation": role_validation,
                    "guard_validation": guard_validation,
                    "project_call": project_call,
                    "automatic_retry": False,
                    **wire_path_output,
                },
            )
        except Exception as exc:  # noqa: BLE001 - WAAPI success must survive a local journal failure
            persistence_payload = execution_success_persistence_failure_payload(
                common,
                store=store,
                transaction_id=transaction_id,
                artifact_hash=preview.artifact_hash,
                prepared=prepared,
                dispatch_result=result,
                exc=exc,
            )
            persistence_payload.update(
                {
                    "schema_validation": schema_validation.as_dict(),
                    "role_validation": role_validation,
                    "guard_validation": guard_validation,
                    "project_call": project_call,
                    **wire_path_output,
                }
            )
            return persistence_payload
        execute_payload = {
            "ok": True,
            "status": "executed_unverified",
            **common,
            "transaction_id": transaction_id,
            "state": executed.state.value,
            "artifact_hash": preview.artifact_hash,
            "dispatch_result": result,
            **wire_path_output,
            "schema_validation": schema_validation.as_dict(),
            "role_validation": role_validation,
            "guard_validation": guard_validation,
            "project_call": project_call,
            "executed": True,
            "verified": False,
            "cleanup": transaction_cleanup_payload(
                prepared,
                phase="executed",
                execution_result=result,
            ),
            "automatic_retry": False,
        }
        if call_uri != "ak.wwise.cli.migrate":
            execute_payload["next_command"] = transaction_next_command(
                "verify",
                ["verify", transaction_id],
            )
        return project_successful_transaction_execute_payload(execute_payload)

    if args.command == "verify":
        if record.state is not TransactionState.EXECUTED_UNVERIFIED:
            raise InvalidTransition(
                f"Transaction {transaction_id!r} must be executed_unverified before verification; "
                f"current state is {record.state.value!r}."
            )
        request_payload = require_mapping(artifact.get("request"), "transaction request")
        project_guard_mode, target_project_path = transaction_project_guard_spec(
            request_payload,
            version=detected_version,
        )
        post_execution_project_guard_policy = transaction_post_execution_project_guard_policy(
            request_payload,
            prepared,
            version=detected_version,
        )
        # Load the immutable execution evidence before any live verification
        # probe.  A guard/readback failure must not discard a result-bound
        # lifecycle identity such as the ID returned by transport.create.
        events = store.read_events(transaction_id)
        execution_events = [event for event in events if event.get("event_type") == "execution_completed"]
        event_details = execution_events[-1].get("details") if execution_events else None
        execution_result = event_details.get("dispatch_result") if isinstance(event_details, Mapping) else None
        if not isinstance(execution_result, Mapping):
            execution_result = {}
        if (
            post_execution_project_guard_policy
            == POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY
            and not execution_events
        ):
            indeterminate = store.record_verification(
                transaction_id,
                TransactionState.INDETERMINATE,
                details={"error_code": "EXECUTION_EVIDENCE_MISSING"},
            )
            return {
                "ok": False,
                "status": "indeterminate",
                **common,
                "transaction_id": transaction_id,
                "state": indeterminate.state.value,
                "error_code": "EXECUTION_EVIDENCE_MISSING",
                "project_call": None,
                "cleanup": transaction_cleanup_payload(prepared, phase="indeterminate"),
                "automatic_retry": False,
            }
        project_call: Mapping[str, Any] | None = None
        try:
            if (
                post_execution_project_guard_policy
                == POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY
            ):
                guard_validation = validate_transaction_context_runtime_guards(
                    artifact,
                    endpoint=common["endpoint"],
                    version=detected_version,
                    live_info=live_info,
                    skill_root=SKILL_ROOT,
                )
            else:
                project, project_call = current_project(
                    dispatcher,
                    connection=connection,
                    version=detected_version,
                    allow_none=project_guard_mode != PROJECT_GUARD_INVARIANT,
                )
                current_guard = build_project_guard(
                    endpoint=common["endpoint"],
                    version=detected_version,
                    live_info=live_info,
                    project=project,
                    project_guard_mode=project_guard_mode,
                    target_project_path=target_project_path,
                )
                guard_validation = validate_transaction_guards(
                    artifact,
                    current_project_guard=current_guard,
                    skill_root=SKILL_ROOT,
                    check_expiry=False,
                    project_phase=PROJECT_GUARD_PHASE_POST_VERIFICATION,
                )
        except TransactionGuardError as exc:
            deferred = {
                "ok": False,
                "status": "verification_deferred",
                **common,
                "transaction_id": transaction_id,
                "state": record.state.value,
                "error_code": exc.error_code,
                "message": str(exc),
                "guard_validation": exc.as_dict(),
                "cleanup": transaction_cleanup_payload(
                    prepared,
                    phase="executed",
                    execution_result=execution_result,
                ),
                "automatic_retry": False,
                "manual_verification_retry_allowed": True,
            }
            if (
                post_execution_project_guard_policy
                == POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY
            ):
                deferred["project_call"] = None
            return deferred
        except Exception as exc:  # noqa: BLE001 - read-only verification may be retried manually
            return verification_deferred_payload(
                common,
                transaction_id=transaction_id,
                state=record.state.value,
                exc=exc,
                cleanup=transaction_cleanup_payload(
                    prepared,
                    phase="executed",
                    execution_result=execution_result,
                ),
            )
        if not execution_events:
            indeterminate = store.record_verification(
                transaction_id,
                TransactionState.INDETERMINATE,
                details={"error_code": "EXECUTION_EVIDENCE_MISSING"},
            )
            return {
                "ok": False,
                "status": "indeterminate",
                **common,
                "transaction_id": transaction_id,
                "state": indeterminate.state.value,
                "error_code": "EXECUTION_EVIDENCE_MISSING",
                "cleanup": transaction_cleanup_payload(prepared, phase="indeterminate"),
                "automatic_retry": False,
            }
        try:
            verification = verify_prepared_operation(
                prepared,
                execution_result=execution_result,
                read_call=read_call,
            )
            if project_guard_mode != PROJECT_GUARD_INVARIANT:
                verification = strengthen_project_transition_verification(
                    verification,
                    guard_validation=guard_validation,
                    project_call=project_call,
                )
        except Exception as exc:  # noqa: BLE001 - read-only verification may be retried manually
            return verification_deferred_payload(
                common,
                transaction_id=transaction_id,
                state=record.state.value,
                exc=exc,
                cleanup=transaction_cleanup_payload(
                    prepared,
                    phase="executed",
                    execution_result=execution_result,
                ),
            )
        outcome = {
            "verified": TransactionState.VERIFIED,
            "result_schema_checked": TransactionState.RESULT_SCHEMA_CHECKED,
            "verification_failed": TransactionState.VERIFICATION_FAILED,
            "indeterminate": TransactionState.INDETERMINATE,
        }[verification.status]
        final_record = store.record_verification(
            transaction_id,
            outcome,
            details={"verification": verification.as_dict()},
        )
        payload = {
            "ok": verification.ok,
            "status": verification.status,
            **common,
            "transaction_id": transaction_id,
            "state": final_record.state.value,
            "artifact_hash": preview.artifact_hash,
            "verification": verification.as_dict(),
            "guard_validation": guard_validation,
            "project_call": project_call,
            "executed": True,
            "verified": verification.business_state_verified and verification.ok,
            "result_schema_checked": verification.status == "result_schema_checked",
            "verification_strength": verification.verification_strength,
            "cleanup": transaction_cleanup_payload(
                prepared,
                phase="verified",
                execution_result=execution_result,
            ),
            "automatic_retry": False,
        }
        if verification.ok:
            agent_result = transaction_agent_result(
                request=require_mapping(artifact.get("request"), "transaction request"),
                transaction_id=transaction_id,
                artifact_hash=preview.artifact_hash,
                state=final_record.state.value,
                executed=True,
                verified=verification.business_state_verified,
                cleanup=payload["cleanup"],
            )
            if agent_result["operation"] in {"waapi.call", "waapi.undoGroup"}:
                agent_result["result"] = execution_result.get("result")
            payload["agent_result"] = agent_result
        return payload
    raise GatewayInputError(f"unsupported transaction command: {args.command}")


def dispatch_host_control_transaction(
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
    store: TransactionStore,
    transaction_id: str,
    artifact_hash: str,
    prepared: Mapping[str, Any],
    call_uri: str,
    call_args: Mapping[str, Any],
    call_options: Mapping[str, Any],
    capability: CapabilityRecord,
    schema_validation: Mapping[str, Any],
    role_validation: Mapping[str, Any],
    guard_validation: Mapping[str, Any],
    project_call: Mapping[str, Any] | None,
    verification_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Dispatch one deliberately terminal debug host control exactly once.

    A returned empty result does not prove that a restart, assertion handler,
    or process crash completed.  Conversely, a dropped WAAPI connection cannot
    prove that the request reached Wwise.  Both outcomes therefore terminate
    in a durable indeterminate state with explicit lifecycle evidence and no
    retry/reconnect/verify command.
    """

    expected_disconnect = verification_plan.get("expected_disconnect")
    process_expectation = verification_plan.get("process_expectation")
    if not isinstance(expected_disconnect, bool) or not isinstance(
        process_expectation, str
    ):
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Host-control verification lacks its expected disconnect and process lifecycle.",
        )
    authorization_record = store.load(transaction_id)
    if authorization_record.state is not TransactionState.CONFIRMED:
        raise InvalidTransition(
            "Dangerous host-control transactions require durable explicit "
            "confirmation and cannot execute from policy authorization."
        )
    authorization = require_transaction_execution_authorization(
        record=authorization_record,
        events=store.read_events(transaction_id),
        env=env,
        read_only_transaction=False,
    )
    store.begin_execution(
        transaction_id,
        expected_authorization=authorization_record.state,
    )
    result: Mapping[str, Any] | None = None
    exception_evidence: Mapping[str, Any] | None = None
    try:
        result = dispatch(
            dispatcher,
            call_uri,
            connection=connection,
            version=detected_version,
            args=call_args,
            options=call_options,
            allow_destructive=True,
            operation_timeout=float(
                capability.execution_contract["timeout_seconds"]
            ),
            result_limit_bytes=int(
                capability.execution_contract["result_limit_bytes"]
            ),
        )
    except Exception as exc:  # noqa: BLE001 - disconnect is part of this contract
        exception_evidence = {
            "error_type": safe_type_name(exc, "Exception"),
            "message": bounded_gateway_label(str(exc), 2048),
        }

    dispatch_accepted = bool(result is not None and result.get("ok") is True)
    if dispatch_accepted:
        delivery = "waapi_result_returned"
        disconnect_observation = "not_observed_before_result"
    elif result is not None:
        delivery = "indeterminate_after_dispatch_attempt"
        disconnect_observation = (
            "call_failed_or_connection_loss_observed"
            if expected_disconnect
            else "unexpected_call_failure_observed"
        )
    else:
        delivery = "exception_after_dispatch_started"
        disconnect_observation = (
            "exception_compatible_with_expected_disconnect"
            if expected_disconnect
            else "unexpected_exception_observed"
        )
    lifecycle = {
        "expected": process_expectation,
        "observed": "not_observed_by_gateway",
        "gateway_process_action": "none",
        "reconnect_attempted": False,
    }
    durable_details = {
        "host_control": call_uri,
        "expected_disconnect": expected_disconnect,
        "disconnect_observation": disconnect_observation,
        "dispatch_delivery": delivery,
        "dispatch_accepted": dispatch_accepted,
        "process_lifecycle": lifecycle,
        "dispatch_result": dict(result) if result is not None else None,
        "exception": dict(exception_evidence) if exception_evidence else None,
        "automatic_retry": False,
    }
    indeterminate = store.mark_execution_indeterminate(
        transaction_id,
        details=durable_details,
    )
    return {
        "ok": False,
        "status": (
            "expected_disconnect_indeterminate"
            if expected_disconnect
            else "host_control_effect_indeterminate"
        ),
        **common,
        "transaction_id": transaction_id,
        "state": indeterminate.state.value,
        "artifact_hash": artifact_hash,
        "host_control": call_uri,
        "expected_disconnect": expected_disconnect,
        "disconnect_observation": disconnect_observation,
        "dispatch_delivery": delivery,
        "dispatch_accepted": dispatch_accepted,
        "process_lifecycle": lifecycle,
        "call": (
            dispatch_call_summary(result)
            if isinstance(result, Mapping)
            else None
        ),
        "exception": dict(exception_evidence) if exception_evidence else None,
        "schema_validation": schema_validation,
        "role_validation": role_validation,
        "guard_validation": guard_validation,
        "project_call": (
            dispatch_call_summary(project_call)
            if isinstance(project_call, Mapping)
            else None
        ),
        "executed": True if dispatch_accepted else None,
        "verified": False,
        "cleanup": transaction_cleanup_payload(
            prepared,
            phase="indeterminate",
            execution_result=result,
        ),
        "automatic_retry": False,
        "reconnect_attempted": False,
        "generic_verify_allowed": False,
    }


def dispatch_undo_group_execution_plan(
    dispatcher: WwiseDispatcher,
    *,
    connection: GatewayConnection,
    version: str,
    execution_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute one reviewed Undo Group plan on the existing dispatcher/client.

    No phase is retried.  Only an inner-call failure attempts ``cancelGroup``;
    uncertainty in begin/end/cancel is terminal because replay could duplicate a
    mutation or close a different session-scoped group.
    """

    if execution_plan.get("kind") != "same_connection_undo_group":
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Undo Group execution plan kind is missing or unsupported.",
        )
    if execution_plan.get("version") != version:
        raise OperationContractError(
            "VERSION_MISMATCH",
            "Undo Group execution plan version does not match live Wwise.",
        )
    begin = require_mapping(execution_plan.get("begin"), "Undo Group begin phase")
    inner_calls = execution_plan.get("calls")
    end = require_mapping(execution_plan.get("end"), "Undo Group end phase")
    cancel = require_mapping(execution_plan.get("cancel"), "Undo Group cancel phase")
    if not isinstance(inner_calls, list):
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Undo Group execution plan calls must be a JSON array.",
        )

    phases: list[dict[str, Any]] = []

    def run_phase(
        phase_name: str,
        phase: Mapping[str, Any],
        *,
        index: int | None = None,
        reserve_cancel_budget: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        uri_value = phase.get("uri", phase.get("api"))
        args_value = phase.get("args", {})
        options_value = phase.get("options", {})
        if (
            not isinstance(uri_value, str)
            or not isinstance(args_value, Mapping)
            or not isinstance(options_value, Mapping)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                f"Undo Group {phase_name} phase is malformed.",
            )
        validate_semantic_payload(
            uri_value,
            args_value,
            options_value,
            version=version,
        )
        capability = CapabilityCatalog().describe(version, uri_value)
        sealed_timeout = phase.get("timeout_seconds")
        sealed_result_limit = phase.get("result_limit_bytes")
        current_timeout = float(capability.execution_contract["timeout_seconds"])
        current_result_limit = int(
            capability.execution_contract["result_limit_bytes"]
        )
        if (
            not isinstance(sealed_timeout, (int, float))
            or isinstance(sealed_timeout, bool)
            or float(sealed_timeout) != current_timeout
            or not isinstance(sealed_result_limit, int)
            or isinstance(sealed_result_limit, bool)
            or sealed_result_limit != current_result_limit
        ):
            raise OperationContractError(
                "PREVIEW_DISPATCH_MISMATCH",
                "Undo Group child execution limits no longer match the sealed contract.",
                details={"index": index, "uri": uri_value},
            )
        remaining = connection.deadline.require_remaining(
            f"Undo Group {phase_name} {uri_value}"
        )
        cancel_reserve = 0.0
        if reserve_cancel_budget:
            cancel_reserve = min(
                UNDO_GROUP_CANCEL_RESERVE_MAX_SECONDS,
                max(
                    UNDO_GROUP_CANCEL_RESERVE_MIN_SECONDS,
                    remaining * UNDO_GROUP_CANCEL_RESERVE_RATIO,
                ),
            )
        operation_timeout = min(
            float(sealed_timeout),
            max(0.001, remaining - cancel_reserve),
        )
        result = dispatch(
            dispatcher,
            uri_value,
            connection=connection,
            version=version,
            args=args_value,
            options=options_value,
            allow_destructive=True,
            operation_timeout=operation_timeout,
            result_limit_bytes=(
                int(sealed_result_limit)
            ),
        )
        row: dict[str, Any] = {
            "phase": phase_name,
            "uri": uri_value,
            "dispatch_result": result,
            "operation_timeout_seconds": operation_timeout,
            "cancel_reserve_seconds": cancel_reserve,
        }
        if index is not None:
            row["index"] = index
        try:
            accumulated_size = len(
                json.dumps(
                    [*phases, row],
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                ).encode("utf-8")
            )
        except (TypeError, ValueError):
            accumulated_size = UNDO_GROUP_MAX_ACCUMULATED_RESULT_BYTES + 1
        if accumulated_size > UNDO_GROUP_MAX_ACCUMULATED_RESULT_BYTES:
            row["dispatch_result"] = dispatch_call_summary(result)
            row["failure"] = {
                "kind": "compound_result_limit_exceeded",
                "limit_bytes": UNDO_GROUP_MAX_ACCUMULATED_RESULT_BYTES,
                "observed_at_least_bytes": accumulated_size,
            }
            phases.append(row)
            return row, False
        if result.get("ok") is not True:
            row["failure"] = {
                "kind": "dispatch_failed",
                "error_code": result.get("error_code"),
                "message": result.get("message"),
            }
            phases.append(row)
            return row, False
        try:
            validate_semantic_result(
                uri_value,
                result.get("result"),
                version=version,
            )
        except SemanticValidationError as exc:
            row["failure"] = {
                "kind": "result_schema_mismatch",
                "validation": exc.as_dict(),
            }
            phases.append(row)
            return row, False
        # The immutable request plan already records request validation, and
        # verification re-validates every recorded dispatch result.  Avoid
        # copying both validation documents into the live phase envelope.
        phases.append(row)
        return row, True

    def best_effort_cancel() -> tuple[Mapping[str, Any], bool]:
        try:
            return run_phase("cancel", cancel)
        except Exception as exc:  # noqa: BLE001 - evidence only; caller remains indeterminate
            return (
                {
                    "phase": "cancel",
                    "failure": {
                        "kind": "cancel_exception",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                },
                False,
            )

    try:
        begin_row, begin_ok = run_phase("begin", begin, reserve_cancel_budget=True)
    except Exception as exc:  # noqa: BLE001 - begin may have reached Wwise
        cancel_row, cancel_ok = best_effort_cancel()
        return {
            "status": "indeterminate",
            "same_connection": True,
            "automatic_retry": False,
            "reason": "beginGroup raised and is not safely replayable",
            "failed_phase": {
                "phase": "begin",
                "failure": {
                    "kind": "begin_exception",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            },
            "cancel_phase": cancel_row,
            "cancel_succeeded": cancel_ok,
            "phases": phases,
        }
    if not begin_ok:
        cancel_row, cancel_ok = best_effort_cancel()
        return {
            "status": "indeterminate",
            "same_connection": True,
            "automatic_retry": False,
            "reason": "beginGroup outcome is not safely replayable",
            "failed_phase": begin_row,
            "cancel_phase": cancel_row,
            "cancel_succeeded": cancel_ok,
            "phases": phases,
        }

    for index, inner in enumerate(inner_calls):
        if not isinstance(inner, Mapping):
            raise OperationContractError(
                "INVALID_PREVIEW",
                f"Undo Group inner call {index} is malformed.",
            )
        try:
            inner_row, inner_ok = run_phase(
                "inner",
                inner,
                index=index,
                reserve_cancel_budget=True,
            )
        except Exception as exc:  # noqa: BLE001 - inner mutation outcome is uncertain
            cancel_row, cancel_ok = best_effort_cancel()
            return {
                "status": "indeterminate",
                "same_connection": True,
                "automatic_retry": False,
                "reason": "an inner Undo Group mutation raised and is not safely replayable",
                "failed_phase": {
                    "phase": "inner",
                    "index": index,
                    "failure": {
                        "kind": "inner_exception",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                },
                "cancel_phase": cancel_row,
                "cancel_succeeded": cancel_ok,
                "phases": phases,
            }
        if inner_ok:
            continue
        cancel_row, cancel_ok = best_effort_cancel()
        if not cancel_ok:
            return {
                "status": "indeterminate",
                "same_connection": True,
                "automatic_retry": False,
                "reason": "cancelGroup outcome is uncertain after an inner-call failure",
                "failed_phase": inner_row,
                "cancel_phase": cancel_row,
                "phases": phases,
            }
        return {
            "status": "execution_cancelled",
            "same_connection": True,
            "automatic_retry": False,
            "failed_phase": inner_row,
            "cancel_phase": cancel_row,
            "phases": phases,
            "rollback_verified": False,
            "message": "The open Undo Group was cancelled on the same connection; rollback state was not verified.",
        }

    try:
        end_row, end_ok = run_phase("end", end, reserve_cancel_budget=True)
    except Exception as exc:  # noqa: BLE001 - best-effort cancel cannot make end certain
        cancel_row, cancel_ok = best_effort_cancel()
        return {
            "status": "indeterminate",
            "same_connection": True,
            "automatic_retry": False,
            "reason": "endGroup raised and is not safely replayable",
            "failed_phase": {
                "phase": "end",
                "failure": {
                    "kind": "end_exception",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            },
            "cancel_phase": cancel_row,
            "cancel_succeeded": cancel_ok,
            "phases": phases,
        }
    if not end_ok:
        cancel_row, cancel_ok = best_effort_cancel()
        return {
            "status": "indeterminate",
            "same_connection": True,
            "automatic_retry": False,
            "reason": "endGroup outcome is not safely replayable",
            "failed_phase": end_row,
            "cancel_phase": cancel_row,
            "cancel_succeeded": cancel_ok,
            "phases": phases,
        }
    dispatch_result = {
        "ok": True,
        "api": "waapi.undoGroup",
        "version": version,
        "result": {"same_connection": True, "phases": phases},
        "error_code": None,
        "message": "ok",
    }
    return {
        "status": "completed",
        "same_connection": True,
        "automatic_retry": False,
        "dispatch_result": dispatch_result,
    }


def undo_group_role_validation_summary(
    role_validation: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the successful Undo guard facts without duplicating its plan."""

    raw_assertions = role_validation.get("assertions")
    assertions = raw_assertions if isinstance(raw_assertions, list) else []
    return {
        "contract": role_validation.get("contract"),
        "operation": role_validation.get("operation"),
        "ok": role_validation.get("ok") is True,
        "status": role_validation.get("status"),
        "assertions": [
            {
                "name": assertion.get("name"),
                "passed": assertion.get("passed") is True,
            }
            for assertion in assertions
            if isinstance(assertion, Mapping)
        ],
        "readbacks": [],
        "evidence_location": "immutable transaction preview artifact",
    }


def dispatch(
    dispatcher: WwiseDispatcher,
    api: str,
    *,
    connection: GatewayConnection,
    version: str,
    args: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    dry_run: bool = False,
    allow_destructive: bool = False,
    topic_mode: str = "wait",
    topic_match: Mapping[str, Any] | None = None,
    topic_event_count: int = 1,
    live_behavior: bool = False,
    exact_object_lookup: bool = False,
    operation_timeout: float | None = None,
    result_limit_bytes: int = MAX_GATEWAY_RESULT_JSON_BYTES,
) -> dict[str, Any]:
    remaining = connection.deadline.require_remaining(f"dispatch {api}")
    dispatch_timeout = (
        remaining
        if operation_timeout is None
        else min(remaining, max(0.0, float(operation_timeout)))
    )
    result = dispatcher.dispatch(
        api,
        version=version,
        args=args,
        options=options,
        timeout=dispatch_timeout,
        dry_run=dry_run,
        allow_destructive=allow_destructive,
        evidence_dir=connection.evidence_dir,
        topic_mode=topic_mode,
        topic_match=topic_match,
        topic_event_count=topic_event_count,
        live_behavior=live_behavior,
        result_limit_bytes=result_limit_bytes,
    )
    if result.get("error_code") == "TIMEOUT":
        result = dict(result)
        details = dict(result.get("details") or {})
        elapsed = connection.deadline.elapsed()
        unbounded = math.isinf(connection.timeout)
        details.setdefault("phase", f"dispatch {api}")
        details.setdefault(
            "configured_timeout_seconds",
            None if unbounded else connection.timeout,
        )
        details.setdefault("timeout_mode", "unbounded" if unbounded else "finite")
        details.setdefault(
            "operation_timeout_seconds",
            None if math.isinf(dispatch_timeout) else dispatch_timeout,
        )
        details.setdefault("elapsed_seconds", elapsed)
        details.setdefault(
            "deadline_exhausted",
            False if unbounded else elapsed >= connection.timeout,
        )
        details.setdefault("cleanup_pending", False)
        details.setdefault("abort_requested", False)
        result["details"] = details
    return normalize_exact_object_absence(
        api=api,
        args=args,
        result=result,
        exact_object_lookup=exact_object_lookup,
    )


def reserved_topic_wait_timeout(connection: GatewayConnection) -> float:
    """Leave bounded in-deadline time for unsubscribe, evidence, and close."""

    remaining = connection.deadline.require_remaining("prepare bounded topic wait")
    reserve = min(
        TOPIC_CLEANUP_RESERVE_MAX_SECONDS,
        remaining * TOPIC_CLEANUP_RESERVE_RATIO,
    )
    return max(0.0, remaining - reserve)


def normalize_exact_object_absence(
    *,
    api: str,
    args: Mapping[str, Any] | None,
    result: Mapping[str, Any],
    exact_object_lookup: bool = False,
) -> dict[str, Any]:
    """Normalize Wwise's unknown-object error for one exact object.get lookup.

    Wwise versions differ on whether a missing GUID/path returns an empty
    ``return`` array or ``ak.wwise.query.unknown_object``.  For an exact
    single-identity lookup these mean the same thing.  Broader WAQL/search
    failures remain errors and are never swallowed.
    """

    if (
        result.get("ok") is True
        or api != OBJECT_GET_URI
        or not (exact_object_lookup or _single_exact_lookup(args))
        or result.get("error_code") != "WaapiRequestFailed"
    ):
        return dict(result)
    error_uri = result.get("waapi_error_uri")
    error_details = result.get("waapi_error_details")
    if error_uri == "ak.wwise.query.unknown_object":
        source = "ak.wwise.query.unknown_object"
    elif error_uri == "ak.wwise.query.invalid_query" and _structured_contains_object_not_found(error_details):
        source = "ak.wwise.query.invalid_query:object-not-found"
    else:
        return dict(result)
    message = str(result.get("message") or "")
    original = {
        "error_code": result.get("error_code"),
        "waapi_error_uri": error_uri,
        "waapi_error_details": error_details,
        "message": message,
        "evidence_path": result.get("evidence_path"),
    }
    return {
        **dict(result),
        "ok": True,
        "result": {"return": []},
        "error_code": None,
        "message": "Exact object identity is absent; normalized to an empty object.get result.",
        "normalization": {
            "kind": "exact-object-absence",
            "source": source,
            "original": original,
        },
    }


def _single_exact_lookup(args: Mapping[str, Any] | None) -> bool:
    if not isinstance(args, Mapping):
        return False
    if set(args) != {"from"}:
        return False
    source = args.get("from")
    if not isinstance(source, Mapping) or set(source) not in ({"id"}, {"path"}):
        return False
    values = source.get("id", source.get("path"))
    if not (
        isinstance(values, list)
        and len(values) == 1
        and isinstance(values[0], str)
    ):
        return False
    value = values[0]
    if "id" in source:
        return _canonical_guid(value)
    return _canonical_wwise_path(value)


def _require_typed_advanced_query_option_exclusivity(
    args: argparse.Namespace,
) -> None:
    """Keep the short typed advanced continuation authoritative."""

    conflicting: list[str] = []
    if args.where:
        conflicting.append("--where")
    if args.match_original_file_paths:
        conflicting.append("--match-original-file-path")
    if args.select:
        conflicting.append("--select")
    if args.take is not None:
        conflicting.append("--take")
    if args.all_results:
        conflicting.append("--all-results")
    if args.return_fields:
        conflicting.append("--return-field")
    if args.typed_structured:
        conflicting.append("--typed-structured")
    if conflicting:
        raise GatewayInputError(
            "query-object --typed-advanced owns the WAQL scalar, return expressions, "
            "and result bound; it cannot be combined with "
            + ", ".join(conflicting)
            + "."
        )


def _require_typed_structured_query_option_exclusivity(
    args: argparse.Namespace,
) -> None:
    """Keep typed structured facts authoritative for the complete read."""

    conflicting: list[str] = []
    for enabled, label in (
        (bool(args.where), "--where"),
        (bool(args.match_original_file_paths), "--match-original-file-path"),
        (bool(args.select), "--select"),
        (args.take is not None, "--take"),
        (bool(args.all_results), "--all-results"),
        (bool(args.return_fields), "--return-field"),
        (bool(args.typed_advanced), "--typed-advanced"),
    ):
        if enabled:
            conflicting.append(label)
    if conflicting:
        raise GatewayInputError(
            "query-object --typed-structured owns the complete structured read; "
            "it cannot be combined with " + ", ".join(conflicting) + "."
        )


def _advanced_query_bound(preview: SemanticPreview) -> dict[str, Any]:
    """Read the builder-owned final native WAQL row cap."""

    bound = preview.envelope.metadata.get("query_bound")
    if not isinstance(bound, Mapping) or set(bound) != {"mode", "value"}:
        raise GatewayResultShapeError(
            "Advanced query builder returned an invalid result-bound contract.",
            details={"command": "query-object --typed-advanced"},
            error_code="INVALID_ADVANCED_QUERY_PLAN",
        )
    mode = bound.get("mode")
    value = bound.get("value")
    if (
        mode != "gateway-appended-take"
        or isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_QUERY_TAKE
    ):
        raise GatewayResultShapeError(
            "Advanced query builder returned an invalid final row cap.",
            details={
                "command": "query-object --typed-advanced",
                "mode": mode,
                "value": value,
            },
            error_code="INVALID_ADVANCED_QUERY_PLAN",
        )
    return {"mode": mode, "value": value}


def _structured_query_exact_identity(
    preview: SemanticPreview,
) -> dict[str, str] | None:
    """Read the builder-owned exact identity without reparsing generated WAQL."""

    metadata = preview.envelope.metadata
    identity = metadata.get("exact_identity")
    if identity is None:
        return None
    if not isinstance(identity, Mapping) or set(identity) != {"kind", "value"}:
        raise GatewayResultShapeError(
            "Structured query builder returned an invalid exact-identity contract.",
            details={"command": "query-object"},
            error_code="INVALID_STRUCTURED_QUERY_PLAN",
        )
    kind = identity.get("kind")
    value = identity.get("value")
    if kind == "id":
        valid = _canonical_guid(value)
    elif kind == "path":
        valid = _canonical_wwise_path(value)
    else:
        valid = False
    if not valid:
        raise GatewayResultShapeError(
            "Structured query builder returned an invalid exact-identity value.",
            details={
                "command": "query-object",
                "identity_kind": kind,
            },
            error_code="INVALID_STRUCTURED_QUERY_PLAN",
        )
    assert isinstance(kind, str) and isinstance(value, str)
    return {"kind": kind, "value": value}


def _structured_query_bound(preview: SemanticPreview) -> dict[str, Any]:
    """Read and validate the strongest builder-owned public result bound."""

    bound = preview.envelope.metadata.get("query_bound")
    if not isinstance(bound, Mapping) or set(bound) != {"mode", "value"}:
        raise GatewayResultShapeError(
            "Structured query builder returned an invalid result-bound contract.",
            details={"command": "query-object"},
            error_code="INVALID_STRUCTURED_QUERY_PLAN",
        )
    mode = bound.get("mode")
    value = bound.get("value")
    valid = (
        mode == "take"
        and isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_QUERY_TAKE
    ) or (mode == "exact-object" and value == 1)
    if not valid:
        raise GatewayResultShapeError(
            "Structured query builder returned an invalid result bound.",
            details={
                "command": "query-object",
                "mode": mode,
                "value": value,
            },
            error_code="INVALID_STRUCTURED_QUERY_PLAN",
        )
    return {"mode": mode, "value": value}


def _structured_query_result_maximum(
    query_bound: Mapping[str, Any],
    *,
    exact_identity: Mapping[str, str] | None,
) -> int:
    value = query_bound["value"]
    assert isinstance(value, int) and not isinstance(value, bool)
    return min(value, 1) if exact_identity is not None else value


def _require_structured_exact_identity_return_field(
    preview: SemanticPreview,
) -> None:
    """Keep exact structured lookups independently identity-verifiable."""

    identity = _structured_query_exact_identity(preview)
    if identity is None:
        return
    return_fields = preview.envelope.options.get("return")
    required = "id" if identity["kind"] == "id" else "path"
    if (
        not isinstance(return_fields, list)
        or required not in return_fields
    ):
        raise GatewayInputError(
            "An exact structured object query must include "
            f"{required!r} in its return array so the packaged Gateway can "
            "verify the returned identity."
        )


def validate_structured_exact_query_identity(
    identity: Mapping[str, str] | None,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Reject successful structured exact lookups whose identity drifted."""

    if identity is None:
        return
    kind = identity["kind"]
    value = identity["value"]
    field = "id" if kind == "id" else "path"
    if kind == "id":
        expected = value.casefold()
        mismatches = [
            {"index": index, "actual": row.get(field)}
            for index, row in enumerate(rows)
            if not isinstance(row.get(field), str)
            or not _canonical_guid(row.get(field))
            or str(row.get(field)).casefold() != expected
        ]
    else:
        expected = _normalize_wwise_identity_path(value)
        mismatches = [
            {"index": index, "actual": row.get(field)}
            for index, row in enumerate(rows)
            if _normalize_wwise_identity_path(row.get(field)) != expected
        ]
    if mismatches:
        raise GatewayResultShapeError(
            "Structured query-object exact lookup returned a different identity.",
            details={
                "command": "query-object",
                "identity_field": field,
                "expected": value,
                "mismatches": mismatches,
            },
        )


def _canonical_exact_query_request(args: argparse.Namespace) -> bool:
    """Trust exactness from parsed CLI fields, never by reparsing generated WAQL."""

    if args.where or args.select or args.take is not None:
        return False
    if args.path is not None:
        return _canonical_wwise_path(args.path)
    if args.object_id is not None:
        return _canonical_guid(args.object_id)
    return False


def _require_explicit_query_bound(args: argparse.Namespace) -> None:
    broad_source = args.object_type is not None or args.search is not None or args.query is not None
    transformed = bool(args.select)
    if (broad_source or transformed) and args.take is None and not args.all_results:
        raise GatewayInputError(
            "Broad query-object sources and --select transforms require an explicit --take limit "
            "or the explicit --all-results opt-in."
        )


def _require_exact_identity_return_field(
    args: argparse.Namespace,
    return_fields: Sequence[str],
) -> None:
    """Keep an untransformed exact lookup independently identity-verifiable."""

    if args.select:
        return
    required_field: str | None = None
    source_option: str | None = None
    if args.path is not None:
        required_field = "path"
        source_option = "--path"
    elif args.object_id is not None:
        required_field = "id"
        source_option = "--object-id"
    if required_field is None or required_field in return_fields:
        return
    raise GatewayInputError(
        f"Exact {source_option} query-object lookups require --return-field {required_field} "
        "so the packaged gateway can verify the returned identity."
    )


def dispatch_original_file_reference_match(
    args: argparse.Namespace,
    *,
    connection: GatewayConnection,
    detected_version: str,
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Match a closed candidate set against one complete AudioFileSource scan."""

    validate_original_file_reference_match_input(args, version=detected_version)
    candidates = normalized_original_file_candidates(args)
    preview = build_object_get_query(
        type=ORIGINAL_FILE_REFERENCE_MATCH_TYPE,
        take=MAX_QUERY_TAKE,
        return_fields=ORIGINAL_FILE_REFERENCE_RETURN_FIELDS,
        version=detected_version,
    )
    envelope = preview.envelope
    result = dispatch(
        dispatcher,
        envelope.uri,
        connection=connection,
        version=detected_version,
        args=envelope.args,
        options=envelope.options,
    )
    query_bound = {
        "mode": "take",
        "value": MAX_QUERY_TAKE,
        "source": "original-file-reference-match-fixed",
    }
    base: dict[str, Any] = {
        **common,
        "semantic_preview": preview.as_dict(),
        "query_bound": query_bound,
        "call": dispatch_call_summary(result),
    }
    if not result.get("ok"):
        return {
            "ok": False,
            "status": "error",
            **base,
            "original_file_reference_match": original_file_reference_match_audit(
                status="not_applied",
                candidate_count=len(candidates),
            ),
        }

    rows = strict_object_get_rows(
        result,
        command="query-object original-file reference match",
        maximum_rows=MAX_QUERY_TAKE,
        required_string_fields=ORIGINAL_FILE_REFERENCE_RETURN_FIELDS,
        error_code="INVALID_ORIGINAL_FILE_REFERENCE_RESULT",
    )
    matches = index_original_file_reference_rows(
        rows,
        candidates=candidates,
        evidence_path=result.get("evidence_path"),
    )
    reference_count = sum(len(values) for values in matches.values())
    referenced_candidate_count = sum(bool(values) for values in matches.values())

    if len(rows) == MAX_QUERY_TAKE:
        return {
            "ok": False,
            "status": "incomplete_boundary",
            **base,
            "error_code": "ORIGINAL_FILE_REFERENCE_SCAN_INCOMPLETE",
            "message": (
                "The AudioFileSource response reached take 1000, so candidate "
                "reference classifications cannot be proven complete."
            ),
            "details": {
                "scan_count": len(rows),
                "scan_take": MAX_QUERY_TAKE,
                "evidence_path": result.get("evidence_path"),
            },
            "original_file_reference_match": original_file_reference_match_audit(
                status="scan_limit_reached",
                candidate_count=len(candidates),
                scan_count=len(rows),
                scan_complete=False,
            ),
        }

    candidate_results: list[dict[str, Any]] = []
    returned_reference_detail_count = 0
    for original_path, key in candidates:
        references = sorted(
            matches[key],
            key=lambda reference: (
                reference["path"].casefold(),
                reference["id"].casefold(),
            ),
        )
        returned_references = references[
            :MAX_ORIGINAL_FILE_REFERENCE_DETAILS_PER_CANDIDATE
        ]
        returned_reference_detail_count += len(returned_references)
        candidate_results.append(
            {
                "originalFilePath": original_path,
                "classification": "referenced" if references else "unreferenced",
                "reference_count": len(references),
                "references": returned_references,
                "references_truncated": (
                    len(references)
                    > MAX_ORIGINAL_FILE_REFERENCE_DETAILS_PER_CANDIDATE
                ),
            }
        )
    payload = {
        "ok": True,
        "status": "ok",
        **base,
        "original_file_reference_match": original_file_reference_match_audit(
            status="complete",
            candidate_count=len(candidates),
            scan_count=len(rows),
            scan_complete=True,
            referenced_candidate_count=referenced_candidate_count,
            reference_count=reference_count,
            returned_reference_detail_count=returned_reference_detail_count,
        ),
    }
    payload["agent_result"] = {
        "contract": ORIGINAL_FILE_REFERENCE_MATCH_CONTRACT,
        "scan_complete": True,
        "scanned_audio_source_count": len(rows),
        "scan_limit": MAX_QUERY_TAKE,
        "candidates": candidate_results,
    }
    return payload


def original_file_reference_match_audit(
    *,
    status: str,
    candidate_count: int,
    scan_count: int | None = None,
    scan_complete: bool = False,
    referenced_candidate_count: int | None = None,
    reference_count: int | None = None,
    returned_reference_detail_count: int | None = None,
) -> dict[str, Any]:
    """Build the bounded completeness audit for candidate path matching."""

    return {
        "contract": ORIGINAL_FILE_REFERENCE_MATCH_CONTRACT,
        "status": status,
        "version": ORIGINAL_FILE_REFERENCE_MATCH_VERSION,
        "source_type": ORIGINAL_FILE_REFERENCE_MATCH_TYPE,
        "return_fields": list(ORIGINAL_FILE_REFERENCE_RETURN_FIELDS),
        "candidate_count": candidate_count,
        "candidate_limit": MAX_ORIGINAL_FILE_PATH_CANDIDATES,
        "scan_take": MAX_QUERY_TAKE,
        "scan_count": scan_count,
        "scan_complete": scan_complete,
        "referenced_candidate_count": referenced_candidate_count,
        "unreferenced_candidate_count": (
            None
            if referenced_candidate_count is None
            else candidate_count - referenced_candidate_count
        ),
        "reference_count": reference_count,
        "returned_reference_detail_count": returned_reference_detail_count,
        "reference_detail_limit_per_candidate": (
            MAX_ORIGINAL_FILE_REFERENCE_DETAILS_PER_CANDIDATE
        ),
        "reference_detail_limit": MAX_ORIGINAL_FILE_REFERENCE_DETAILS,
    }


def index_original_file_reference_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    candidates: Sequence[tuple[str, tuple[str, ...]]],
    evidence_path: Any,
) -> dict[tuple[str, ...], list[dict[str, str]]]:
    """Validate all returned rows and index only exact normalized candidate hits."""

    matches: dict[tuple[str, ...], list[dict[str, str]]] = {
        key: [] for _, key in candidates
    }
    seen_ids: dict[str, int] = {}
    for index, row in enumerate(rows):
        object_id = row["id"]
        hierarchy_path = row["path"]
        original_file_path = row["originalFilePath"]
        if not _canonical_guid(object_id):
            raise_invalid_original_file_reference_row(
                index=index,
                field="id",
                reason="expected a canonical braced GUID",
                evidence_path=evidence_path,
            )
        identity_key = object_id.casefold()
        previous = seen_ids.get(identity_key)
        if previous is not None:
            raise GatewayResultShapeError(
                "query-object original-file reference match returned a duplicate object id.",
                details={
                    "command": "query-object original-file reference match",
                    "duplicate_id": object_id,
                    "first_index": previous,
                    "duplicate_index": index,
                    "evidence_path": evidence_path,
                },
                error_code="INVALID_ORIGINAL_FILE_REFERENCE_RESULT",
            )
        seen_ids[identity_key] = index
        if not _canonical_wwise_path(hierarchy_path):
            raise_invalid_original_file_reference_row(
                index=index,
                field="path",
                reason="expected a canonical absolute Wwise hierarchy path",
                evidence_path=evidence_path,
            )
        try:
            hierarchy_path_size = len(hierarchy_path.encode("utf-8"))
        except UnicodeEncodeError:
            hierarchy_path_size = MAX_ORIGINAL_FILE_REFERENCE_PATH_BYTES + 1
        if hierarchy_path_size > MAX_ORIGINAL_FILE_REFERENCE_PATH_BYTES:
            raise_invalid_original_file_reference_row(
                index=index,
                field="path",
                reason=(
                    "path exceeds the closed "
                    f"{MAX_ORIGINAL_FILE_REFERENCE_PATH_BYTES}-byte detail limit"
                ),
                evidence_path=evidence_path,
            )
        try:
            original_key = normalize_original_file_system_path(original_file_path)
        except ValueError as exc:
            raise_invalid_original_file_reference_row(
                index=index,
                field="originalFilePath",
                reason=str(exc),
                evidence_path=evidence_path,
            )
        if original_key in matches:
            matches[original_key].append(
                {
                    "id": object_id,
                    "path": hierarchy_path,
                }
            )
    return matches


def raise_invalid_original_file_reference_row(
    *,
    index: int,
    field: str,
    reason: str,
    evidence_path: Any,
) -> None:
    """Raise one stable fail-closed result error without echoing an arbitrary row."""

    raise GatewayResultShapeError(
        "query-object original-file reference match returned a malformed row.",
        details={
            "command": "query-object original-file reference match",
            "invalid_index": index,
            "field": field,
            "reason": reason,
            "evidence_path": evidence_path,
        },
        error_code="INVALID_ORIGINAL_FILE_REFERENCE_RESULT",
    )


def _query_result_maximum(args: argparse.Namespace) -> int | None:
    """Return the strongest applicable result bound for one closed query."""

    take = args.take
    exact_source = args.path is not None or args.object_id is not None
    expanding = any(value in EXPANDING_QUERY_SELECTS for value in (args.select or ()))
    semantic_maximum = 1 if exact_source and not expanding else None
    if take is None:
        return semantic_maximum
    if semantic_maximum is None:
        return take
    return min(take, semantic_maximum)


def validate_exact_query_identity(
    args: argparse.Namespace,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Reject a successful exact lookup whose returned identity drifted."""

    if args.select:
        return
    if args.path is not None:
        expected = _normalize_wwise_identity_path(args.path)
        mismatches = [
            {
                "index": index,
                "actual": row.get("path"),
            }
            for index, row in enumerate(rows)
            if _normalize_wwise_identity_path(row.get("path")) != expected
        ]
        identity_field = "path"
    elif args.object_id is not None:
        expected = args.object_id.casefold()
        mismatches = [
            {
                "index": index,
                "actual": row.get("id"),
            }
            for index, row in enumerate(rows)
            if not isinstance(row.get("id"), str)
            or not _canonical_guid(row.get("id"))
            or str(row.get("id")).casefold() != expected
        ]
        identity_field = "id"
    else:
        return
    if mismatches:
        raise GatewayResultShapeError(
            "query-object exact lookup returned an object with a different identity.",
            details={
                "command": "query-object",
                "identity_field": identity_field,
                "expected": args.path if args.path is not None else args.object_id,
                "mismatches": mismatches,
            },
        )


def _normalize_wwise_identity_path(value: Any) -> str | None:
    """Normalize hierarchy separators and case for exact-path identity checks."""

    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("/", "\\")
    if not normalized.startswith("\\"):
        return None
    segments = [segment for segment in normalized.split("\\") if segment]
    if not segments:
        return "\\"
    return ("\\" + "\\".join(segments)).casefold()


def _query_bound_summary(args: argparse.Namespace) -> dict[str, Any]:
    if args.take is not None:
        return {"mode": "take", "value": args.take}
    if args.all_results:
        return {"mode": "all-results-explicit"}
    return {"mode": "exact-object"}


def project_successful_query_object_payload(
    payload: Mapping[str, Any],
    *,
    detail: bool,
) -> dict[str, Any]:
    """Keep ordinary successful query output focused on business rows.

    The complete compiled preview and dispatch/evidence summary remain available
    through ``query-object --detail``.  Failed and boundary results are never
    projected because their complete evidence is required for a truthful stop.
    """

    if detail or payload.get("ok") is not True:
        return dict(payload)
    compact_keys = (
        "contract",
        "ok",
        "status",
        "command",
        "endpoint",
        "detected_version",
        "is_command_line",
        "query_layer",
        "query_contract",
        "query_bound",
        "count",
        "limit_reached",
        "objects",
    )
    projected = {key: payload[key] for key in compact_keys if key in payload}
    if "agent_result" in payload:
        # Preserve the exact object and keep it insertion-order last.  The outer
        # session-context attachment repeats the same terminal-order guarantee.
        projected["agent_result"] = payload["agent_result"]
    return projected


def _canonical_wwise_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("\\"):
        return False
    if value != "\\" and (value.startswith("\\\\") or value.endswith("\\") or "\\\\" in value):
        return False
    if "/" in value or '"' in value:
        return False
    if any(ord(character) < 32 or ord(character) == 127 or character in {"\u2028", "\u2029"} for character in value):
        return False
    return value == "\\" or all(segment for segment in value[1:].split("\\"))


def _canonical_guid(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 38 or value[0] != "{" or value[-1] != "}":
        return False
    body = value[1:-1]
    if tuple(index for index, character in enumerate(body) if character == "-") != (8, 13, 18, 23):
        return False
    return all(character in "0123456789abcdefABCDEF-" for character in body)


def _structured_contains_object_not_found(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    message = value.get("message")
    return isinstance(message, str) and "object not found" in message.casefold()


def _stabilize_waapi_client_shutdown(client: Any) -> Any:
    """Suppress only waapi-client's duplicate completion during disconnect."""

    decoupler = getattr(client, "_decoupler", None)
    original = getattr(decoupler, "unblock_caller", None)
    marker = "_waapi_skill_shutdown_stabilized"
    if not callable(original) or bool(getattr(decoupler, marker, False)):
        return client

    def safe_unblock_caller() -> Any:
        future = getattr(decoupler, "_future", None)
        done = getattr(future, "done", None)
        if callable(done) and done():
            return None
        try:
            return original()
        except InvalidStateError:
            current = getattr(decoupler, "_future", None)
            current_done = getattr(current, "done", None)
            if current is future and callable(current_done) and current_done():
                return None
            raise

    setattr(decoupler, "unblock_caller", safe_unblock_caller)
    setattr(decoupler, marker, True)
    return client


def default_client_factory(url: str) -> Any:
    from waapi import WaapiClient  # type: ignore[import-not-found]  # noqa: PLC0415

    # Structured dispatcher errors are more reliable than waapi-client's default
    # behavior of logging failures to stderr and returning ``None`` as success data.
    client = WaapiClient(url=url, allow_exception=True)
    return _stabilize_waapi_client_shutdown(client)


def selected_ui_boundary(result: Mapping[str, Any], *, live_info: Mapping[str, Any]) -> bool:
    if result.get("error_code") == "API_NOT_FOUND":
        return True
    unavailable_uri = "ak.wwise.unavailable"
    message = str(result.get("message") or "").casefold()
    error_code = str(result.get("error_code") or "").casefold()
    structured_uri = str(result.get("waapi_error_uri") or "").casefold()
    unavailable = (
        structured_uri == unavailable_uri
        or error_code == unavailable_uri
        or unavailable_uri in message
    )
    return unavailable and bool(live_info.get("isCommandLine"))


def dispatch_call_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    """Keep audit identity and evidence without duplicating a potentially huge WAAPI result."""

    keys = (
        "api",
        "item_type",
        "category",
        "version",
        "ok",
        "dry_run",
        "risk_level",
        "error_code",
        "message",
        "details",
        "waapi_error_uri",
        "waapi_error_details",
        "normalization",
        "evidence_path",
        "timeout",
    )
    summary = {key: result.get(key) for key in keys if key in result}
    if "normalization" in result and result.get("result") == {"return": []}:
        summary["result"] = {"return": []}
    return summary


def successful_role_validation_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    """Digest one successful role guard without duplicating live readbacks."""

    raw_assertions = value.get("assertions")
    assertions = raw_assertions if isinstance(raw_assertions, list) else []
    raw_readbacks = value.get("readbacks")
    readbacks = raw_readbacks if isinstance(raw_readbacks, list) else []
    return {
        "summary_contract": TRANSACTION_ROLE_VALIDATION_SUMMARY_CONTRACT,
        "contract": value.get("contract"),
        "operation": value.get("operation"),
        "ok": value.get("ok") is True,
        "status": value.get("status"),
        "assertion_count": len(assertions),
        "passed_assertion_count": sum(
            1
            for assertion in assertions
            if isinstance(assertion, Mapping) and assertion.get("passed") is True
        ),
        "assertions_canonical_sha256": canonical_sha256(assertions),
        "readback_count": len(readbacks),
        "readbacks_canonical_sha256": canonical_sha256(readbacks),
        "full_evidence_in_stdout": False,
    }


def successful_dispatch_result_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a successful dispatch outcome while digesting its raw result."""

    summary = dispatch_call_summary(value)
    summary["result_summary"] = transaction_value_summary(
        value.get("result"),
        include_keys=True,
    )
    summary["result_included"] = False
    return summary


def successful_execute_component_summary(
    value: Any,
    *,
    preserve: Sequence[str] = (),
) -> dict[str, Any]:
    """Return a closed digest projection for a secondary execute component."""

    summary = transaction_value_summary(value, include_keys=True)
    if isinstance(value, Mapping):
        for key in preserve:
            candidate = value.get(key)
            if isinstance(candidate, (str, int, float, bool)) or candidate is None:
                if key in value:
                    summary[key] = candidate
    return summary


def project_successful_transaction_execute_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Bound stdout for one persisted successful non-terminal execution.

    This function is deliberately never used for drift, failed dispatch,
    persistence failure, cancellation, or indeterminate outcomes.  Those
    states retain their complete failure evidence and cannot be made to look
    successful by projection.
    """

    if payload.get("ok") is not True or payload.get("status") != "executed_unverified":
        raise GatewayResultShapeError(
            "Only a persisted executed_unverified payload can use the success projection",
            details={
                "ok": payload.get("ok"),
                "status": payload.get("status"),
                "required_ok": True,
                "required_status": "executed_unverified",
            },
            error_code="INVALID_EXECUTE_SUCCESS_PROJECTION",
        )

    projected = dict(payload)
    agent_result_sentinel = object()
    agent_result = projected.pop("agent_result", agent_result_sentinel)
    role_validation = projected.get("role_validation")
    if not isinstance(role_validation, Mapping) or role_validation.get("ok") is not True:
        raise GatewayResultShapeError(
            "A successful execute payload lacks a successful role validation",
            details={
                "role_validation_type": type(role_validation).__name__,
                "role_validation_ok": (
                    role_validation.get("ok")
                    if isinstance(role_validation, Mapping)
                    else None
                ),
            },
            error_code="INVALID_EXECUTE_SUCCESS_PROJECTION",
        )
    projected["role_validation"] = successful_role_validation_summary(role_validation)
    project_call = projected.get("project_call")
    if isinstance(project_call, Mapping):
        projected["project_call"] = dispatch_call_summary(project_call)

    projection = {
        "contract": TRANSACTION_EXECUTE_SUCCESS_SUMMARY_CONTRACT,
        "detail_level": "full-dispatch-result",
        "fixed_projection_limit_bytes": (
            TRANSACTION_EXECUTE_SUCCESS_STDOUT_BUDGET_BYTES
            - TRANSACTION_EXECUTE_SUCCESS_ENVELOPE_RESERVE_BYTES
        ),
        "stdout_budget_bytes": TRANSACTION_EXECUTE_SUCCESS_STDOUT_BUDGET_BYTES,
        "session_context_reserve_bytes": (
            TRANSACTION_EXECUTE_SUCCESS_ENVELOPE_RESERVE_BYTES
        ),
        "projected_payload_bytes": 0,
        "full_dispatch_result_in_stdout": True,
        "full_role_validation_in_stdout": False,
        "full_execution_evidence_persisted": True,
        "journal_event": "execution_completed",
        "truncated": False,
    }
    projected["stdout_projection"] = projection
    fixed_limit = int(projection["fixed_projection_limit_bytes"])

    def append_agent_result() -> None:
        projected.pop("agent_result", None)
        if agent_result is not agent_result_sentinel:
            projected["agent_result"] = agent_result

    def stabilize_size() -> int:
        append_agent_result()
        for _ in range(8):
            observed = gateway_json_document_size(projected)
            if projection["projected_payload_bytes"] == observed:
                return observed
            projection["projected_payload_bytes"] = observed
        return gateway_json_document_size(projected)

    if stabilize_size() > fixed_limit:
        dispatch_result = payload.get("dispatch_result")
        if not isinstance(dispatch_result, Mapping) or dispatch_result.get("ok") is not True:
            raise GatewayResultShapeError(
                "A successful execute payload lacks a successful dispatch result",
                details={
                    "dispatch_result_type": type(dispatch_result).__name__,
                    "dispatch_result_ok": (
                        dispatch_result.get("ok")
                        if isinstance(dispatch_result, Mapping)
                        else None
                    ),
                },
                error_code="INVALID_EXECUTE_SUCCESS_PROJECTION",
            )
        projected.pop("agent_result", None)
        projected["dispatch_result"] = successful_dispatch_result_summary(
            dispatch_result
        )
        projection["detail_level"] = "digest-dispatch-result"
        projection["full_dispatch_result_in_stdout"] = False

    if stabilize_size() > fixed_limit:
        projected.pop("agent_result", None)
        for key, preserve in (
            (
                "schema_validation",
                ("contract", "ok", "status", "schema_id"),
            ),
            (
                "guard_validation",
                (
                    "ok",
                    "status",
                    "project_guard_mode",
                    "project_guard_phase",
                    "project_guard_fingerprint",
                    "runtime_guard_fingerprint",
                    "expires_at",
                ),
            ),
            (
                "cleanup",
                (
                    "contract",
                    "status",
                    "phase",
                    "automatic_cleanup",
                    "automatic_retry",
                ),
            ),
            (
                "wire_path_adaptation",
                (
                    "contract",
                    "mode",
                    "applied",
                    "translated_path_count",
                    "project_guard_fingerprint",
                    "current_project_guard_fingerprint",
                ),
            ),
        ):
            if key in projected:
                projected[key] = successful_execute_component_summary(
                    projected[key],
                    preserve=preserve,
                )
        projection["detail_level"] = "minimal-digest"

    if stabilize_size() > fixed_limit:
        projected.pop("agent_result", None)
        keep = (
            "ok",
            "status",
            "contract",
            "command",
            "endpoint",
            "detected_version",
            "is_command_line",
            "transaction_id",
            "state",
            "artifact_hash",
            "dispatch_result",
            "wire_path_adaptation",
            "schema_validation",
            "role_validation",
            "guard_validation",
            "project_call",
            "executed",
            "verified",
            "cleanup",
            "automatic_retry",
            "next_command",
            "stdout_projection",
        )
        projected = {key: projected[key] for key in keep if key in projected}
        projection = projected["stdout_projection"]
        projection["detail_level"] = "minimal-allowlist-digest"

    observed = stabilize_size()
    if observed > fixed_limit:
        raise GatewayResultShapeError(
            "The successful execute projection could not fit its fixed stdout budget",
            error_code="EXECUTE_SUCCESS_SUMMARY_BUDGET_EXCEEDED",
            details={
                "contract": TRANSACTION_EXECUTE_SUCCESS_SUMMARY_CONTRACT,
                "limit_bytes": fixed_limit,
                "observed_bytes": observed,
                "transaction_id": payload.get("transaction_id"),
                "state": payload.get("state"),
                "artifact_hash": payload.get("artifact_hash"),
                "executed": True,
                "automatic_retry": False,
                "truncated": False,
            },
        )
    append_agent_result()
    return projected


def transaction_verify_cleanup_projection_safe(value: Any) -> bool:
    """Return whether a cleanup boundary can remain exact in a success summary."""

    if not isinstance(value, Mapping):
        return False
    status = value.get("status")
    if not isinstance(status, str) or status.casefold() in {
        "failed",
        "indeterminate",
        "unknown",
    }:
        return False
    projection = value.get("projection")
    if not isinstance(projection, Mapping):
        return False
    projection_status = projection.get("status")
    if not isinstance(projection_status, str) or projection_status.casefold() in {
        "failed",
        "indeterminate",
        "unknown",
    }:
        return False
    return "error" not in projection


def successful_verification_result_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    """Digest complete successful verification evidence already in the journal."""

    raw_assertions = value.get("assertions")
    assertions = raw_assertions if isinstance(raw_assertions, list) else []
    raw_readbacks = value.get("readbacks")
    readbacks = raw_readbacks if isinstance(raw_readbacks, list) else []
    passed_assertion_count = sum(
        1
        for assertion in assertions
        if isinstance(assertion, Mapping) and assertion.get("passed") is True
    )
    return {
        "summary_contract": TRANSACTION_VERIFICATION_RESULT_SUMMARY_CONTRACT,
        "contract": value.get("contract"),
        "operation": value.get("operation"),
        "status": value.get("status"),
        "ok": value.get("ok") is True,
        "verification_strength": value.get("verification_strength"),
        "business_state_verified": value.get("business_state_verified") is True,
        "assertion_count": len(assertions),
        "passed_assertion_count": passed_assertion_count,
        "failed_assertion_count": len(assertions) - passed_assertion_count,
        "assertions_canonical_sha256": canonical_sha256(assertions),
        "readback_count": len(readbacks),
        "readbacks_canonical_sha256": canonical_sha256(readbacks),
        "canonical_sha256": canonical_sha256(value),
        "full_evidence_in_stdout": False,
    }


def validate_successful_transaction_verify_projection(
    payload: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    """Reject internally inconsistent terminal success before it is compacted."""

    verification = payload.get("verification")
    agent_result = payload.get("agent_result")
    cleanup = payload.get("cleanup")
    invalid_reasons: list[str] = []
    status = payload.get("status")
    projectable_statuses = (
        TransactionState.VERIFIED.value,
        TransactionState.RESULT_SCHEMA_CHECKED.value,
    )
    strong_success = status == TransactionState.VERIFIED.value
    expected_state = status if status in projectable_statuses else None
    expected_verified = strong_success
    expected_result_schema_checked = (
        status == TransactionState.RESULT_SCHEMA_CHECKED.value
    )

    if payload.get("ok") is not True:
        invalid_reasons.append("top-level ok is not true")
    if status not in projectable_statuses:
        invalid_reasons.append("top-level status is not a projectable success")
    if payload.get("state") != expected_state:
        invalid_reasons.append("transaction state does not match success status")
    if payload.get("executed") is not True:
        invalid_reasons.append("top-level executed is not true")
    if payload.get("verified") is not expected_verified:
        invalid_reasons.append("top-level verified does not match success status")
    if payload.get("result_schema_checked") is not expected_result_schema_checked:
        invalid_reasons.append(
            "result_schema_checked does not match success status"
        )
    if payload.get("automatic_retry") is not False:
        invalid_reasons.append("automatic_retry is not false")

    if not isinstance(verification, Mapping):
        invalid_reasons.append("verification is not an object")
        verification = {}
    else:
        if verification.get("ok") is not True:
            invalid_reasons.append("verification ok is not true")
        if verification.get("status") != expected_state:
            invalid_reasons.append(
                "verification status does not match top-level success status"
            )
        if verification.get("business_state_verified") is not expected_verified:
            invalid_reasons.append(
                "business verification strength does not match success status"
            )
        if payload.get("verification_strength") != verification.get(
            "verification_strength"
        ):
            invalid_reasons.append("verification strength does not match")
        assertions = verification.get("assertions")
        if not isinstance(assertions, list):
            invalid_reasons.append("verification assertions are not an array")
        elif any(
            not isinstance(assertion, Mapping)
            or assertion.get("passed") is not True
            for assertion in assertions
        ):
            invalid_reasons.append("verified assertions are not all passed")
        readbacks = verification.get("readbacks")
        if not isinstance(readbacks, list):
            invalid_reasons.append("verification readbacks are not an array")

    if not isinstance(agent_result, Mapping):
        invalid_reasons.append("agent_result is not an object")
        agent_result = {}
    else:
        for key in (
            "transaction_id",
            "artifact_hash",
            "state",
            "executed",
            "verified",
        ):
            if agent_result.get(key) != payload.get(key):
                invalid_reasons.append(f"agent_result {key} does not match")
        request = agent_result.get("request")
        operation = agent_result.get("operation")
        if not isinstance(request, Mapping):
            invalid_reasons.append("agent_result request is not an object")
        elif request.get("operation") != operation:
            invalid_reasons.append("agent_result request operation does not match")
        if operation != verification.get("operation"):
            invalid_reasons.append("verification operation does not match agent_result")

    if not isinstance(cleanup, Mapping):
        invalid_reasons.append("cleanup is not an object")
        cleanup = {}
    elif canonical_sha256(agent_result.get("cleanup")) != canonical_sha256(cleanup):
        invalid_reasons.append("agent_result cleanup does not match")

    if invalid_reasons:
        raise GatewayResultShapeError(
            "A terminal verify success payload is internally inconsistent",
            error_code="INVALID_VERIFY_SUCCESS_PROJECTION",
            details={
                "contract": TRANSACTION_VERIFY_SUCCESS_SUMMARY_CONTRACT,
                "reasons": invalid_reasons,
                "transaction_id": bounded_gateway_label(
                    payload.get("transaction_id"),
                    128,
                ),
                "state": bounded_gateway_label(payload.get("state"), 80),
                "artifact_hash": bounded_gateway_label(
                    payload.get("artifact_hash"),
                    128,
                ),
            },
        )
    return verification, agent_result, cleanup


def project_successful_transaction_verify_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Bound one terminal verify success without altering agent_result.

    Complete assertions and readbacks were durably written to the
    ``verification_recorded`` journal event before this function can run.
    Both strong ``verified`` and explicit weak ``result_schema_checked``
    outcomes enter this projection.  Failure, indeterminate, and cleanup-error
    boundaries never do.
    """

    verification, agent_result, _cleanup = (
        validate_successful_transaction_verify_projection(payload)
    )
    verification_summary = successful_verification_result_summary(verification)
    projected = dict(payload)
    projected.pop("agent_result", None)
    projection = {
        "contract": TRANSACTION_VERIFY_SUCCESS_SUMMARY_CONTRACT,
        "detail_level": "full-verification-evidence",
        "fixed_projection_limit_bytes": (
            TRANSACTION_VERIFY_SUCCESS_STDOUT_BUDGET_BYTES
            - TRANSACTION_VERIFY_SUCCESS_ENVELOPE_RESERVE_BYTES
        ),
        "stdout_budget_bytes": TRANSACTION_VERIFY_SUCCESS_STDOUT_BUDGET_BYTES,
        "session_context_reserve_bytes": (
            TRANSACTION_VERIFY_SUCCESS_ENVELOPE_RESERVE_BYTES
        ),
        "projected_payload_bytes": 0,
        "verification_canonical_sha256": verification_summary["canonical_sha256"],
        "assertion_count": verification_summary["assertion_count"],
        "passed_assertion_count": verification_summary["passed_assertion_count"],
        "readback_count": verification_summary["readback_count"],
        "full_verification_evidence_in_stdout": True,
        "full_verification_evidence_persisted": True,
        "journal_event": "verification_recorded",
        "agent_result_exact": True,
        "cleanup_exact": True,
        "truncated": False,
    }
    projected["stdout_projection"] = projection
    fixed_limit = int(projection["fixed_projection_limit_bytes"])

    def append_agent_result() -> None:
        projected.pop("agent_result", None)
        projected["agent_result"] = agent_result

    def stabilize_size() -> int:
        append_agent_result()
        for _ in range(8):
            observed = gateway_json_document_size(projected)
            if projection["projected_payload_bytes"] == observed:
                return observed
            projection["projected_payload_bytes"] = observed
        return gateway_json_document_size(projected)

    if stabilize_size() > fixed_limit:
        projected.pop("agent_result", None)
        projected["verification"] = verification_summary
        projection["detail_level"] = "digest-verification-evidence"
        projection["full_verification_evidence_in_stdout"] = False

    if stabilize_size() > fixed_limit:
        projected.pop("agent_result", None)
        guard_validation = projected.get("guard_validation")
        if isinstance(guard_validation, Mapping):
            projected["guard_validation"] = successful_execute_component_summary(
                guard_validation,
                preserve=(
                    "ok",
                    "status",
                    "project_guard_mode",
                    "project_guard_phase",
                    "project_guard_fingerprint",
                    "runtime_guard_fingerprint",
                ),
            )
        project_call = projected.get("project_call")
        if isinstance(project_call, Mapping):
            projected["project_call"] = successful_execute_component_summary(
                project_call,
                preserve=("api", "ok", "status", "version", "risk_level"),
            )
        projection["detail_level"] = "minimal-digest"

    if stabilize_size() > fixed_limit:
        projected.pop("agent_result", None)
        keep = (
            "ok",
            "status",
            "contract",
            "command",
            "endpoint",
            "detected_version",
            "is_command_line",
            "transaction_id",
            "state",
            "artifact_hash",
            "verification",
            "guard_validation",
            "project_call",
            "executed",
            "verified",
            "result_schema_checked",
            "verification_strength",
            "cleanup",
            "automatic_retry",
            "stdout_projection",
        )
        projected = {key: projected[key] for key in keep if key in projected}
        projection = projected["stdout_projection"]
        projection["detail_level"] = "minimal-allowlist-digest"

    observed = stabilize_size()
    if observed > fixed_limit:
        raise GatewayResultShapeError(
            "The successful verify projection could not fit its fixed stdout budget",
            error_code="VERIFY_SUCCESS_SUMMARY_BUDGET_EXCEEDED",
            details={
                "contract": TRANSACTION_VERIFY_SUCCESS_SUMMARY_CONTRACT,
                "limit_bytes": fixed_limit,
                "observed_bytes": observed,
                "transaction_id": bounded_gateway_label(
                    payload.get("transaction_id"),
                    128,
                ),
                "state": bounded_gateway_label(payload.get("state"), 80),
                "artifact_hash": bounded_gateway_label(
                    payload.get("artifact_hash"),
                    128,
                ),
                "executed": True,
                "verified": payload.get("verified") is True,
                "result_schema_checked": (
                    payload.get("result_schema_checked") is True
                ),
                "automatic_retry": False,
                "agent_result_exact": True,
                "truncated": False,
            },
        )
    append_agent_result()
    return projected


def topic_subscription_cleanup_status(result: Mapping[str, Any]) -> str:
    """Project only an explicit dispatcher cleanup fact; never infer from outcome."""

    details = result.get("details")
    cleanup = (
        details.get(SUBSCRIPTION_CLEANUP_DETAILS_KEY)
        if isinstance(details, Mapping)
        else None
    )
    status = cleanup.get("status") if isinstance(cleanup, Mapping) else None
    if status in {
        SUBSCRIPTION_CLEANUP_UNSUBSCRIBED,
        SUBSCRIPTION_CLEANUP_FAILED,
        SUBSCRIPTION_CLEANUP_AFTER_RETRY,
    }:
        return str(status)
    return "unknown"


def status_wwise_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    keys = (
        "apiVersion",
        "displayName",
        "isCommandLine",
        "processId",
        "processPath",
        "sessionId",
        "version",
    )
    return {key: value.get(key) for key in keys if key in value}


def status_project_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    keys = (
        "id",
        "name",
        "type",
        "path",
        "displayTitle",
        "isDirty",
        "currentLanguageId",
        "currentPlatformId",
    )
    return {key: value.get(key) for key in keys if key in value}


def strict_call_result_mapping(
    result: Mapping[str, Any],
    *,
    command: str,
    error_code: str,
) -> dict[str, Any]:
    """Require a successful call result to be one JSON object."""

    payload = result.get("result")
    if not isinstance(payload, Mapping):
        raise GatewayResultShapeError(
            f"{command} expected the successful WAAPI result to be a JSON object.",
            details={
                "command": command,
                "expected": "object",
                "actual_result_type": type(payload).__name__,
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    return dict(payload)


def strict_object_get_rows(
    result: Mapping[str, Any],
    *,
    command: str,
    maximum_rows: int | None = None,
    required_string_fields: Sequence[str] = (),
    error_code: str = "INVALID_QUERY_RESULT",
) -> list[dict[str, Any]]:
    """Validate the public object.get result shape without converting drift to absence."""

    payload = result.get("result")
    if not isinstance(payload, Mapping):
        raise GatewayResultShapeError(
            f"{command} expected object.get result to be a JSON object.",
            details={
                "command": command,
                "expected": {"return": "array<object>"},
                "actual_result_type": type(payload).__name__,
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    rows = payload.get("return")
    if not isinstance(rows, list):
        raise GatewayResultShapeError(
            f"{command} expected object.get result.return to be an array.",
            details={
                "command": command,
                "expected": {"return": "array<object>"},
                "actual_return_type": type(rows).__name__,
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    invalid_indices = [index for index, row in enumerate(rows) if not isinstance(row, Mapping)]
    if invalid_indices:
        raise GatewayResultShapeError(
            f"{command} expected every object.get result.return row to be a JSON object.",
            details={
                "command": command,
                "expected": {"return": "array<object>"},
                "invalid_row_indices": invalid_indices,
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    if maximum_rows is not None and len(rows) > maximum_rows:
        raise GatewayResultShapeError(
            f"{command} returned {len(rows)} rows, exceeding its maximum of {maximum_rows}.",
            details={
                "command": command,
                "maximum_rows": maximum_rows,
                "actual_count": len(rows),
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    invalid_field_rows = {
        index: [
            field
            for field in required_string_fields
            if not isinstance(row.get(field), str) or not str(row.get(field)).strip()
        ]
        for index, row in enumerate(rows)
        if isinstance(row, Mapping)
    }
    invalid_field_rows = {
        index: fields for index, fields in invalid_field_rows.items() if fields
    }
    if invalid_field_rows:
        raise GatewayResultShapeError(
            f"{command} returned rows without the required string fields.",
            details={
                "command": command,
                "required_string_fields": list(required_string_fields),
                "invalid_rows": invalid_field_rows,
                "evidence_path": result.get("evidence_path"),
            },
            error_code=error_code,
        )
    return [dict(row) for row in rows]


def normalize_selected_return_fields(
    requested: Sequence[str] | None,
) -> tuple[str, ...]:
    """Return a bounded projection while retaining stable selection identity."""

    fields = list(SELECTED_REQUIRED_RETURN_FIELDS)
    for value in requested or ():
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > MAX_SELECTED_RETURN_FIELD_CHARS
            or any(ord(character) < 0x20 for character in value)
        ):
            raise GatewayInputError(
                "selected --return-field values must be non-empty, trimmed "
                f"accessors of at most {MAX_SELECTED_RETURN_FIELD_CHARS} characters"
            )
        if value not in fields:
            fields.append(value)
        if len(fields) > MAX_SELECTED_RETURN_FIELDS:
            raise GatewayInputError(
                f"selected accepts at most {MAX_SELECTED_RETURN_FIELDS} unique "
                "return fields including id, name, type, and path"
            )
    return tuple(fields)


def strict_selected_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Require the exact documented selected-object success shape."""

    payload = result.get("result")
    if not isinstance(payload, Mapping):
        raise GatewayResultShapeError(
            "selected expected the successful WAAPI result to be a JSON object.",
            details={
                "command": "selected",
                "expected": {"objects": "array<object>"},
                "actual_result_type": type(payload).__name__,
                "evidence_path": result.get("evidence_path"),
            },
            error_code="INVALID_SELECTION_RESULT",
        )
    rows = payload.get("objects")
    if not isinstance(rows, list):
        raise GatewayResultShapeError(
            "selected expected result.objects to be an array.",
            details={
                "command": "selected",
                "expected": {"objects": "array<object>"},
                "actual_objects_type": type(rows).__name__,
                "evidence_path": result.get("evidence_path"),
            },
            error_code="INVALID_SELECTION_RESULT",
        )
    invalid_indices = [index for index, row in enumerate(rows) if not isinstance(row, Mapping)]
    if invalid_indices:
        raise GatewayResultShapeError(
            "selected expected every result.objects row to be a JSON object.",
            details={
                "command": "selected",
                "expected": {"objects": "array<object>"},
                "invalid_row_indices": invalid_indices,
                "evidence_path": result.get("evidence_path"),
            },
            error_code="INVALID_SELECTION_RESULT",
        )
    invalid_field_rows = {
        index: [
            field
            for field in SELECTED_REQUIRED_RETURN_FIELDS
            if not isinstance(row.get(field), str) or not str(row.get(field)).strip()
        ]
        for index, row in enumerate(rows)
        if isinstance(row, Mapping)
    }
    invalid_field_rows = {
        index: fields for index, fields in invalid_field_rows.items() if fields
    }
    if invalid_field_rows:
        raise GatewayResultShapeError(
            "selected returned rows without id, name, type, and path strings.",
            details={
                "command": "selected",
                "required_string_fields": list(SELECTED_REQUIRED_RETURN_FIELDS),
                "invalid_rows": invalid_field_rows,
                "evidence_path": result.get("evidence_path"),
            },
            error_code="INVALID_SELECTION_RESULT",
        )
    return [dict(row) for row in rows]


def require_single_result_row(
    rows: Sequence[Mapping[str, Any]],
    *,
    command: str,
    error_code: str,
) -> dict[str, Any]:
    if len(rows) != 1:
        raise GatewayResultShapeError(
            f"{command} expected exactly one row, received {len(rows)}.",
            details={
                "command": command,
                "expected_count": 1,
                "actual_count": len(rows),
            },
            error_code=error_code,
        )
    return dict(rows[0])


def require_project_identity(
    value: Mapping[str, Any],
    *,
    command: str,
    error_code: str = "INVALID_PROJECT_RESULT",
) -> dict[str, Any]:
    """Require the stable canonical-id/name/path identity shared by all supported versions."""

    project = dict(value)
    invalid_fields: list[str] = []
    if not _canonical_guid(project.get("id")):
        invalid_fields.append("id")
    invalid_fields.extend(
        field
        for field in ("name", "path")
        if not isinstance(project.get(field), str) or not str(project.get(field)).strip()
    )
    if invalid_fields:
        raise GatewayResultShapeError(
            f"{command} requires a canonical project GUID and non-empty name and path fields.",
            details={
                "command": command,
                "required_fields": list(PROJECT_IDENTITY_FIELDS),
                "id_format": "{8-4-4-4-12}",
                "invalid_fields": invalid_fields,
            },
            error_code=error_code,
        )
    return project


def require_status_info(
    value: Mapping[str, Any],
    *,
    expected_version: str,
) -> dict[str, Any]:
    """Require the stable getInfo fields used by the public status contract."""

    info = dict(value)
    invalid_fields: list[str] = []
    if not isinstance(info.get("displayName"), str) or not str(info.get("displayName")).strip():
        invalid_fields.append("displayName")
    if not isinstance(info.get("isCommandLine"), bool):
        invalid_fields.append("isCommandLine")
    actual_version: str | None = None
    if not isinstance(info.get("version"), Mapping):
        invalid_fields.append("version")
    else:
        try:
            actual_version = version_key_from_get_info(info)
        except (TypeError, ValueError):
            invalid_fields.append("version")
    if invalid_fields:
        raise GatewayResultShapeError(
            "status getInfo requires displayName, isCommandLine, and version fields.",
            details={
                "command": "status getInfo",
                "required_fields": ["displayName", "isCommandLine", "version"],
                "invalid_fields": invalid_fields,
            },
            error_code="INVALID_STATUS_RESULT",
        )
    if actual_version != expected_version:
        raise GatewayResultShapeError(
            "status getInfo version does not match the detected live version.",
            details={
                "command": "status getInfo",
                "expected_version": expected_version,
                "actual_version": actual_version,
            },
            error_code="INVALID_STATUS_RESULT",
        )
    return info


def resolve_transaction_store(args: argparse.Namespace, *, env: Mapping[str, str]) -> TransactionStore:
    return TransactionStore(resolve_transaction_state_directory(args, env=env))


def resolve_transaction_state_directory(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> Path:
    if args.state_dir is not None:
        configured = args.state_dir
        label = "--state-dir"
    elif STATE_DIRECTORY_ENV in env:
        configured = env[STATE_DIRECTORY_ENV]
        label = f"${STATE_DIRECTORY_ENV}"
    else:
        xdg_state_home = env.get("XDG_STATE_HOME")
        home = env.get("HOME")
        if xdg_state_home:
            configured = str(Path(xdg_state_home) / "waapi-skill")
            label = "$XDG_STATE_HOME/waapi-skill"
        elif home:
            configured = str(Path(home) / ".local" / "state" / "waapi-skill")
            label = "$HOME/.local/state/waapi-skill"
        else:
            raise GatewayInputError(
                "Transaction state directory could not be resolved because neither "
                f"${STATE_DIRECTORY_ENV}, $XDG_STATE_HOME, nor $HOME is available."
            )
    return resolve_external_runtime_directory(
        str(configured),
        label=label,
    )


def prepare_read_only_metadata_cache_state_directory(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    project: Mapping[str, Any] | None,
) -> Path | None:
    """Best-effort durable-cache root for a read-only metadata command.

    Metadata discovery must remain usable when local state is unavailable.  It
    therefore creates only the external state root needed by
    :class:`DurableMetadataCache`; it never constructs a transaction store or
    turns a cache/configuration problem into a discovery failure.
    """

    if project is None:
        return None
    try:
        state_dir = resolve_transaction_state_directory(args, env=env)
        require_runtime_directory_outside_project(state_dir, project=project)
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        state_stat = state_dir.lstat()
    except (GatewayInputError, OSError):
        return None
    if (
        stat.S_ISLNK(state_stat.st_mode)
        or not stat.S_ISDIR(state_stat.st_mode)
        or (
            os.name != "nt"
            and bool(state_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
        )
    ):
        return None
    return state_dir


def resolve_external_runtime_directory(value: str, *, label: str) -> Path:
    """Resolve one explicit runtime directory without ambient-home expansion."""

    if not isinstance(value, str) or not value.strip():
        raise GatewayInputError(f"{label} must be a non-empty absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise GatewayInputError(f"{label} must be an absolute path")
    resolved = path.resolve(strict=False)
    skill_root = SKILL_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(skill_root)
    except ValueError:
        return resolved
    raise GatewayInputError(f"{label} must be outside the Skill checkout: {resolved}")


def require_runtime_directory_outside_project(
    runtime_dir: Path,
    *,
    project: Mapping[str, Any],
) -> None:
    """Reject runtime state inside the live project across native/Wine paths."""

    project_value: str | None = None
    for key in ("filePath", "projectPath", "path"):
        value = project.get(key)
        if isinstance(value, str) and value:
            project_value = value
            break
    if project_value is None:
        raise GatewayInputError(
            "The live project does not expose an absolute filesystem path; "
            "transaction state containment cannot be proven."
        )
    try:
        localized_project = localize_waapi_host_path(project_value)
    except HostPathError as exc:
        raise GatewayInputError(
            "The live project filesystem path cannot be localized safely: "
            f"{project_value}: {exc}"
        ) from exc
    project_root = Path(localized_project).resolve(strict=False).parent
    resolved_runtime = runtime_dir.resolve(strict=False)
    try:
        resolved_runtime.relative_to(project_root)
    except ValueError:
        return
    raise GatewayInputError(
        "Transaction state directory must be outside the live Wwise project: "
        f"{resolved_runtime}"
    )


def transaction_next_command(
    command: str,
    gateway_argv: Sequence[str],
    *,
    requires_explicit_user_confirmation: bool = False,
    requires_later_user_message: bool = False,
) -> dict[str, Any]:
    """Return one canonical continuation without model-rebuilt path segments."""

    normalized = [str(value) for value in gateway_argv]
    full_argv = [
        "python",
        str(GATEWAY_RUNNER_PATH),
        "gateway.py",
        *normalized,
    ]
    payload: dict[str, Any] = {
        "contract": TRANSACTION_NEXT_COMMAND_CONTRACT,
        "command": command,
        "gateway_argv": normalized,
        "full_argv": full_argv,
        "copy_exactly": True,
    }
    if requires_explicit_user_confirmation:
        payload["requires_explicit_user_confirmation"] = True
    if requires_later_user_message:
        payload["requires_later_user_message"] = True
    model_command: str | None = None
    if os.name == "nt":
        payload["shell_family"] = WINDOWS_POWERSHELL_ENCODED_FAMILY
        shell_command = encode_windows_powershell_argv(full_argv)
        try:
            model_command = encode_windows_model_argv(full_argv)
        except PlatformCommandError:
            model_command = None
    else:
        payload["shell_family"] = "posix-sh"
        shell_command = shlex.join(full_argv)
    if model_command is not None:
        payload["shell_command"] = shell_command
        payload["model_shell_family"] = WINDOWS_MODEL_COMMAND_FAMILY
    payload["copy_instruction"] = {
        "contract": TRANSACTION_COMMAND_COPY_INSTRUCTION_CONTRACT,
        "source_field": (
            "model_command" if model_command is not None else "shell_command"
        ),
        "action": "execute_verbatim_as_one_shell_tool_call",
        "forbidden_transformations": [
            "reconstruct",
            "shorten",
            "normalize",
            "substitute_path_segments",
            "select_another_field",
        ],
    }
    if model_command is not None:
        payload["model_command"] = model_command
    else:
        payload["shell_command"] = shell_command
    return payload


def transaction_state_payload(command: str, record: Any, *, offline: bool) -> dict[str, Any]:
    payload = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": True,
        "status": record.state.value,
        "command": command,
        "offline": offline,
        "transaction_id": record.transaction_id,
        "state": record.state.value,
        "artifact_hash": record.artifact_hash,
    }
    if command == "confirm" and record.state is TransactionState.CONFIRMED:
        payload["next_command"] = transaction_next_command(
            "execute",
            ["execute", record.transaction_id],
        )
    return payload


def _operation_draft_projection_handles(value: Any) -> set[str]:
    handles: set[str] = set()
    if isinstance(value, Mapping):
        handle = value.get("handle")
        if isinstance(handle, str):
            handles.add(handle)
        for nested in value.values():
            handles.update(_operation_draft_projection_handles(nested))
    elif isinstance(value, list):
        for nested in value:
            handles.update(_operation_draft_projection_handles(nested))
    return handles


def _operation_draft_projection_handles_in_order(value: Any) -> tuple[str, ...]:
    handles: list[str] = []
    seen: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            handle = item.get("handle")
            if isinstance(handle, str) and handle not in seen:
                seen.add(handle)
                handles.append(handle)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return tuple(handles)


def _operation_draft_facts_summary(current_facts: list[Any]) -> dict[str, Any]:
    return {
        "contract": "waapi-skill.operation-draft-facts-summary/v1",
        "target_count": len(current_facts),
        "handle_count": len(_operation_draft_projection_handles(current_facts)),
        "canonical_sha256": canonical_sha256(current_facts),
    }


def _operation_draft_compact_action_projection(
    *,
    actions: Sequence[Mapping[str, Any]],
    prior_record: OperationDraftRecord,
    record: OperationDraftRecord,
    current_facts: list[Any],
) -> dict[str, Any]:
    if (
        prior_record.composition is None
        or record.composition is None
        or prior_record.operation != record.operation
        or prior_record.version != record.version
    ):
        raise GatewayInputError(
            "Compact Draft action projection requires one bound Composer transition."
        )
    prior_facts = composition_projection(
        prior_record.operation,
        prior_record.version,
        prior_record.composition,
    )["current_facts"]
    prior_handles = _operation_draft_projection_handles(prior_facts)
    current_handles = _operation_draft_projection_handles(current_facts)
    if not actions:
        raise GatewayInputError("Compact Draft action result lacks its action batch.")
    action = actions[-1]
    action_name = action.get("action")
    if not isinstance(action_name, str) or not action_name:
        raise GatewayInputError("Compact Draft action result lacks its action name.")
    affected_handles = sorted(
        {
            value
            for row in actions
            for key, value in row.items()
            if key.endswith("_handle") and isinstance(value, str)
        }
    )
    action_result: dict[str, Any] = {
        "contract": "waapi-skill.operation-draft-action-result/v1",
        "action": action_name,
        "created_handles": [
            handle
            for handle in _operation_draft_projection_handles_in_order(current_facts)
            if handle not in prior_handles
        ],
        "affected_handles": affected_handles,
    }
    fact_action = action.get("fact_action")
    field_handle = action.get("field_handle")
    value = action.get("value")
    key = action.get("key")
    dynamic_field = (
        field_handle
        if isinstance(field_handle, str) and field_handle.startswith("trm1-")
        else None
    )
    dynamic_value = (
        value
        if isinstance(value, str) and value.startswith("trm1-")
        else None
    )
    if fact_action in {"append", "set", "map-put", "choose-dynamic"} and (
        dynamic_field is not None or dynamic_value is not None
    ):
        continuation: dict[str, Any] = {
            "source": "most_recent_typed_container_handle_response",
            "response_was_complete_not_truncated": True,
            "current_handle": dynamic_field or dynamic_value,
            "completed_fact_action": fact_action,
            "next_rule": (
                "map_put_the_same_key_from_its_disclosed_choice"
                if fact_action == "choose-dynamic"
                else (
                    "continue_with_child_contract_facts_for_the_appended_value"
                    if fact_action == "append" and dynamic_value is not None
                    else (
                        "continue_with_the_next_business_present_child_contract_"
                        "fact_in_queue_index_order"
                    )
                )
            ),
            "stop_cancel_or_claim_truncation_before_current_root_is_complete": (
                "invalid"
            ),
        }
        if isinstance(key, str):
            continuation["current_key"] = key
        action_result["construction_continuation"] = continuation
    if action.get("fact_action") == "choose" and isinstance(
        action.get("value"), str
    ):
        field_payloads = draft_operation_request_contract(
            record.operation, record.version
        ).gateway_field_payloads()
        selected_handle = action["value"]
        selected = next(
            (
                field
                for field in field_payloads
                if field.get("handle") == selected_handle
            ),
            None,
        )
        constants = (
            selected.get("branch_choice_constants")
            if isinstance(selected, Mapping)
            else None
        )
        if isinstance(constants, Mapping) and constants:
            required_followups: list[dict[str, Any]] = []
            for field in field_payloads:
                name = field.get("name")
                if (
                    field.get("parent_handle") != selected_handle
                    or not isinstance(name, str)
                    or name not in constants
                ):
                    continue
                value = constants[name]
                if isinstance(value, bool):
                    value_type, value_text = "boolean", "true" if value else "false"
                elif isinstance(value, int):
                    value_type, value_text = "integer", str(value)
                elif isinstance(value, float) and math.isfinite(value):
                    value_type, value_text = (
                        "number",
                        json.dumps(value, ensure_ascii=False, allow_nan=False),
                    )
                elif isinstance(value, str):
                    value_type, value_text = "string", value
                else:
                    raise GatewayInputError(
                        "Selected branch constant has an unsupported typed value."
                    )
                required_followups.append(
                    {
                        "reason": "selected_branch_constant",
                        "typed_fact_arguments": [
                            "--action",
                            "add_typed_fact",
                            "--fact-action",
                            "set",
                            "--field-handle",
                            field["handle"],
                            "--value-type",
                            value_type,
                            "--fact-value",
                            value_text,
                        ],
                    }
                )
            if required_followups:
                action_result["required_followup_facts"] = required_followups
    return {
        "current_facts_summary": _operation_draft_facts_summary(current_facts),
        "action_result": action_result,
    }


def operation_draft_payload(
    command: str,
    record: OperationDraftRecord,
    *,
    offline: bool = True,
    compact_actions: Sequence[Mapping[str, Any]] | None = None,
    prior_record: OperationDraftRecord | None = None,
    task_authority: str | None = None,
) -> dict[str, Any]:
    """Project bounded lifecycle facts without inventing adapter-owned fields."""

    read_only_draft = (
        record.operation.startswith("ak.")
        and public_typed_contract(record.version, record.operation).effect == "read"
    )

    if record.composer_digest is not None and record.composition is not None:
        projection = composition_projection(
            record.operation,
            record.version,
            record.composition,
        )
        if record.state is not OperationDraftState.EDITABLE:
            projection["allowed_actions"] = []
            if record.state in {
                OperationDraftState.CANCELLED,
                OperationDraftState.EXPIRED,
            }:
                projection["missing_fields"] = []
                projection["missing_fields_status"] = "lifecycle_terminal"
        if record.check is None:
            projection["check"] = None
        else:
            projection["check"] = {
                "status": "passed",
                "checked_at": record.check["checked_at"],
                "source_revision": record.check["source_revision"],
                "request_digest": record.check["request_digest"],
            }
            if record.state is OperationDraftState.EDITABLE:
                projection["allowed_actions"] = [
                    action
                    for action in projection["allowed_actions"]
                    if action != "check"
                ]
                projection["allowed_actions"].extend(
                    ["check", "preview-from-draft"]
                )
            if command == "draft-check":
                current_facts = projection.pop("current_facts")
                if not isinstance(current_facts, list):
                    raise GatewayInputError(
                        "Checked Draft projection requires bounded current facts."
                    )
                projection["current_facts_summary"] = (
                    _operation_draft_facts_summary(current_facts)
                )
                projection["response_integrity"] = {
                    "complete": True,
                    "truncated": False,
                    "projection": "checked_draft_receipt",
                    "compact_projection_is_not_truncation": True,
                    "draft_inspect_required_before_preview": False,
                }
                projection["construction_state"] = {
                    "draft_complete": True,
                    "preview_created": False,
                    "required_next_phase": "preview-from-draft",
                    "execute_returned_next_command_exactly": True,
                    "construction_boundary": (
                        operation_draft_construction_boundary(
                            read_only=read_only_draft
                        )
                    ),
                }
        if record.seal is None:
            projection["seal"] = None
        else:
            projection["seal"] = {
                "status": (
                    "sealed"
                    if record.state is OperationDraftState.SEALED
                    else "reserved"
                ),
                "source_revision": record.seal["source_revision"],
                "transaction_id": record.seal["transaction_id"],
                "artifact_hash": record.seal["artifact_hash"],
            }
        if compact_actions is not None:
            if command != "draft-apply" or prior_record is None:
                raise GatewayInputError(
                    "Compact Draft action projection is valid only for draft-apply."
                )
            current_facts = projection.pop("current_facts")
            if not isinstance(current_facts, list):
                raise GatewayInputError(
                    "Compact Draft action projection requires bounded current facts."
                )
            projection.update(
                _operation_draft_compact_action_projection(
                    actions=compact_actions,
                    prior_record=prior_record,
                    record=record,
                    current_facts=current_facts,
                )
            )
            if len(compact_actions) > 1:
                action_result = projection.get("action_result")
                if not isinstance(action_result, dict):
                    raise GatewayInputError(
                        "Compact Draft batch projection lacks its action result."
                    )
                action_result["last_action"] = action_result.pop("action")
                action_result["action"] = "batch"
                action_result["action_count"] = len(compact_actions)
                action_result["applied_atomically"] = True
                action_result.pop("construction_continuation", None)
            projection["schema_required_fields_status"] = projection.pop(
                "missing_fields_status"
            )
            projection["response_integrity"] = {
                "complete": True,
                "truncated": False,
                "projection": "action_delta_and_draft_receipt",
                "compact_projection_is_not_truncation": True,
                "construction_boundary": (
                    operation_draft_construction_boundary(
                        read_only=read_only_draft
                    )
                ),
            }
            projection = {
                key: projection[key]
                for key in (
                    "schema_required_fields_status",
                    "current_facts_summary",
                    "action_result",
                    "response_integrity",
                )
            }
    else:
        projection = {
            "current_facts": [],
            "missing_fields": [],
            "missing_fields_status": "no_operation_adapter",
            "allowed_actions": (
                ["inspect", "cancel"]
                if record.state is OperationDraftState.EDITABLE
                else []
            ),
        }
    draft = {
        "contract": OPERATION_DRAFT_CONTRACT,
        "draft_id": record.draft_id,
        "lifecycle_state": record.state.value,
        "revision": record.revision,
        "binding": {
            "operation": record.operation,
            "version": record.version,
            "schema_digest": record.schema_digest,
        },
        **(
            {}
            if compact_actions is not None
            else {
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "expires_at": record.expires_at,
            }
        ),
        **projection,
    }
    if record.state is OperationDraftState.EDITABLE:
        generic_typed_draft = record.operation.startswith("ak.") or (
            record.operation in DRAFT_TYPED_OPERATIONS
            and record.operation != "waapi.undoGroup"
        )
        next_action_binding: dict[str, Any] = {
            "contract": "waapi-skill.operation-draft-next-action/v1",
        }
        if generic_typed_draft:
            next_action_binding["typed_fact_batch_discipline"] = {
                "batch_size": "6 until fewer than 6 facts remain",
                "top_level_facts_before_dynamic_disclosure": True,
                "branch_choice_requires_selected_branch_facts": True,
                "schema_candidates_without_business_values": "skip",
            }
            next_action_binding["next_phase_decision"] = {
                "business_presence_source": "current_user_business_request",
                "evaluate_in_order": [
                    {
                        "candidate": "remaining_top_level_fact_batch",
                        "condition": (
                            "unsubmitted_top_level_or_selected_branch_fact_is_present"
                        ),
                        "action": (
                            "use_fixed_argv_prefix_for_next_full_or_final_batch"
                        ),
                    },
                    {
                        "candidate": "dynamic_disclosure",
                        "condition": (
                            "no_remaining_top_level_or_selected_branch_fact"
                        ),
                    },
                ],
                "first_true_candidate_is_the_only_next_phase": True,
            }
        if compact_actions is not None:
            next_action_binding["shell_tool_timeout_ms"] = (
                GATEWAY_SHELL_TOOL_TIMEOUT_MS
            )
        if compact_actions is None:
            next_action_binding.update(
                {
                    "draft_id": record.draft_id,
                    "expected_revision": record.revision,
                    "one_atomic_action_batch_only": True,
                    "minimum_actions": 1,
                    "maximum_actions": MAX_TYPED_ACTIONS_PER_APPLY,
                    "then_read_next_response": True,
                    "precompute_or_increment_revision": False,
                }
            )
            if (
                record.revision == 1
                and record.check is None
                and generic_typed_draft
            ):
                next_action_binding.update(
                    {
                        "required_next_phase": "typed_fact_batch",
                        "fact_order_source": (
                            "/operation-schema/composer/construction_order"
                            if not record.operation.startswith("ak.")
                            else "/request-schema/construction_order"
                        ),
                        "first_batch_rule": (
                            "submit the next 6 schema-ordered facts when "
                            "available; otherwise submit every remaining fact "
                            "before disclosure"
                        ),
                        "branch_choice_rule": (
                            "after choose, add required selected-branch "
                            "constant and prompt-value facts before the next "
                            "top-level fact"
                        ),
                        "dynamic_disclosure_before_first_fact": "invalid",
                    }
                )
        if record.check is not None:
            next_action_binding.update(
                {
                    "fixed_full_argv_template": [
                        "python",
                        str(GATEWAY_RUNNER_PATH),
                        "gateway.py",
                        "preview-from-draft",
                        record.draft_id,
                        "--task-authority",
                        task_authority or "<task-authority-from-draft-start>",
                        "--expected-revision",
                        str(record.revision),
                        "--apply",
                    ],
                    "replace_only": (
                        []
                        if task_authority is not None
                        else ["<task-authority-from-draft-start>"]
                    ),
                }
            )
        else:
            next_action_binding.update(
                {
                    "fixed_argv_prefix": [
                        "python",
                        str(GATEWAY_RUNNER_PATH),
                        "gateway.py",
                        "draft-apply",
                        record.draft_id,
                        "--task-authority",
                        task_authority or "<task-authority-from-draft-start>",
                        "--expected-revision",
                        str(record.revision),
                        "--compact",
                        "--facts",
                    ],
                    "append_one_or_more_complete_typed_actions": [
                        "--action",
                        "<action-name>",
                        "<typed-fact-arguments>",
                    ],
                    "replace_only": [
                        "<action-name>",
                        "<typed-fact-arguments>",
                    ],
                }
            )
            if task_authority is None:
                next_action_binding["replace_only"].insert(
                    0, "<task-authority-from-draft-start>"
                )
        if compact_actions is None:
            next_action_binding["copy_all_other_values_exactly"] = True
        elif record.check is None:
            action_result = draft.get("action_result")
            construction_continuation = (
                action_result.get("construction_continuation")
                if isinstance(action_result, Mapping)
                else None
            )
            if compact_actions is not None and not isinstance(
                construction_continuation, Mapping
            ):
                next_action_binding["completion_candidate"] = {
                    "condition": (
                        "all_current_business_request_facts_and_disclosures_submitted"
                    ),
                    "is_next_command_when_condition_true": True,
                    "fixed_argv_prefix": [
                        "python",
                        str(GATEWAY_RUNNER_PATH),
                        "gateway.py",
                        "draft-check",
                        record.draft_id,
                        "--task-authority",
                        task_authority or "<task-authority-from-draft-start>",
                        "--expected-revision",
                        str(record.revision),
                    ],
                    "allowed_suffix_source": (
                        "request_schema_terminal_arguments_only"
                    ),
                    "draft_apply_action_check": "invalid",
                    "when_condition_false": (
                        "continue_with_one_atomic_typed_action_batch_or_dynamic_disclosure"
                    ),
                }
            followups = (
                action_result.get("required_followup_facts")
                if isinstance(action_result, Mapping)
                else None
            )
            prefix = next_action_binding.get("fixed_argv_prefix")
            if isinstance(followups, list) and isinstance(prefix, list):
                for followup in followups:
                    arguments = (
                        followup.get("typed_fact_arguments")
                        if isinstance(followup, dict)
                        else None
                    )
                    if not isinstance(arguments, list):
                        continue
                    followup.update(
                        {
                            "is_next_command": True,
                            "literal_copy_policy": {
                                "copy_fixed_full_argv_exactly": True,
                                "business_value_substitution": "invalid",
                            },
                            "fixed_full_argv": [*prefix, *arguments],
                        }
                    )
        if not (command == "draft-check" and record.check is not None):
            draft["next_action_binding"] = next_action_binding
    return {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": True,
        "status": record.state.value,
        "command": command,
        "offline": offline,
        "draft": draft,
    }


def transaction_agent_result(
    *,
    request: Mapping[str, Any],
    transaction_id: str,
    artifact_hash: str,
    state: str,
    executed: bool,
    verified: bool | None = None,
    authorization: Mapping[str, Any] | None = None,
    cleanup: Mapping[str, Any] | None = None,
    next_command: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project an immutable transaction artifact into the agent JSON contract.

    The request is the exact object loaded from the immutable preview artifact;
    callers must not reconstruct it from command arguments or verification
    evidence.  Only successful preview and successful terminal verification
    responses expose this projection.
    """

    operation = request.get("operation")
    if not isinstance(operation, str) or not operation:
        raise GatewayInputError("transaction request must contain a non-empty operation")
    result: dict[str, Any] = {
        "operation": operation,
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "state": state,
        "executed": executed,
        "request": request,
    }
    if verified is not None:
        result["verified"] = verified
    if authorization is not None:
        result["authorization"] = dict(authorization)
    if cleanup is not None:
        result["cleanup"] = dict(cleanup)
    if next_command is not None:
        # A preview mirrors the exact top-level continuation here so the final
        # machine-readable field also ends on the selected continuation.
        result["next_command"] = next_command
    return result


def transaction_cleanup_payload(
    prepared: Mapping[str, Any],
    *,
    phase: str,
    execution_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve the immutable cleanup spec and add an honest phase status."""

    return _transaction_cleanup_payload(
        prepared,
        phase=phase,
        execution_result=execution_result,
    )


def transaction_show_summary(
    artifact: Any,
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a bounded review projection of one immutable transaction preview.

    The exact request remains visible because it is the object the user reviews
    before authorization.  The committed summary shape is returned unchanged
    whenever its fixed (non-request) portion fits the public budget.  Only an
    oversized artifact switches to explicitly labelled digest projections so a
    large object graph is not printed two or three times.  Nothing is
    byte-truncated.
    """

    artifact_map = dict(artifact) if isinstance(artifact, Mapping) else {}
    prepared_raw = artifact_map.get("prepared_operation")
    prepared = dict(prepared_raw) if isinstance(prepared_raw, Mapping) else {}
    project_guard_raw = artifact_map.get("project_guard")
    project_guard = dict(project_guard_raw) if isinstance(project_guard_raw, Mapping) else {}
    runtime_guard_raw = artifact_map.get("runtime_guard")
    runtime_guard = dict(runtime_guard_raw) if isinstance(runtime_guard_raw, Mapping) else {}
    event_rows = [
        {
            key: event.get(key)
            for key in ("sequence", "event_type", "from_state", "to_state", "event_hash")
            if event.get(key) is not None
        }
        for event in events
    ]
    current_state = next(
        (
            str(event.get("to_state"))
            for event in reversed(events)
            if isinstance(event.get("to_state"), str)
        ),
        TransactionState.DRAFT.value,
    )
    cleanup_phase = {
        TransactionState.EXECUTING.value: "indeterminate",
        TransactionState.INDETERMINATE.value: "indeterminate",
        TransactionState.EXECUTED_UNVERIFIED.value: "executed",
        TransactionState.VERIFIED.value: "verified",
        TransactionState.RESULT_SCHEMA_CHECKED.value: "verified",
        TransactionState.VERIFICATION_FAILED.value: "verified",
        TransactionState.EXECUTION_CANCELLED.value: "execution_cancelled",
    }.get(current_state, "preview")
    execution_result: Mapping[str, Any] | None = None
    for event in reversed(events):
        if event.get("event_type") != "execution_completed":
            continue
        details = event.get("details")
        candidate = details.get("dispatch_result") if isinstance(details, Mapping) else None
        if isinstance(candidate, Mapping):
            execution_result = candidate
        break
    cleanup = transaction_cleanup_payload(
        prepared,
        phase=cleanup_phase,
        execution_result=execution_result,
    )
    request = artifact_map.get("request")

    # ``transaction-show --summary-only`` predates the bounded projections.
    # Preserve that committed public shape exactly for ordinary transactions;
    # consumers can keep reading exact dispatch, role, pre-state, and verifier
    # objects.  Oversized artifacts are the only compatibility boundary where
    # returning the legacy shape would defeat the result ceiling.
    legacy_result = {
        "summary_only": True,
        "preview_summary": {
            "contract": artifact_map.get("contract"),
            "request": request,
            "dispatch": prepared.get("dispatch"),
            "resolved_roles": prepared.get("resolved_roles"),
            "pre_state": prepared.get("pre_state"),
            "verification_plan": prepared.get("verification_plan"),
            "cleanup": cleanup,
            "project_guard_fingerprint": project_guard.get("fingerprint"),
            "runtime_guard_fingerprint": runtime_guard.get("fingerprint"),
            "expires_at": artifact_map.get("expires_at"),
        },
        "event_count": len(event_rows),
        "events": event_rows,
    }
    legacy_fixed_result = {
        "summary_only": True,
        "preview_summary": {
            key: value
            for key, value in legacy_result["preview_summary"].items()
            if key != "request"
        },
        "event_count": len(event_rows),
        "events": event_rows,
    }
    if (
        gateway_json_document_size(
            legacy_fixed_result,
            stop_after_bytes=TRANSACTION_SHOW_SUMMARY_FIXED_BUDGET_BYTES,
        )
        <= TRANSACTION_SHOW_SUMMARY_FIXED_BUDGET_BYTES
    ):
        return legacy_result

    request_digest = canonical_sha256(request)
    request_bytes = len(canonical_json_bytes(request))

    variants = (
        {
            "detail_level": "review",
            "include_dispatch_payload": True,
            "include_role_items": True,
            "include_names_and_sections": True,
        },
        {
            "detail_level": "compact-dispatch",
            "include_dispatch_payload": False,
            "include_role_items": True,
            "include_names_and_sections": True,
        },
        {
            "detail_level": "digest",
            "include_dispatch_payload": False,
            "include_role_items": False,
            "include_names_and_sections": False,
        },
    )
    observed_by_variant: dict[str, int] = {}
    bounded_fallback: dict[str, Any] | None = None
    for variant in variants:
        detail_level = str(variant["detail_level"])
        result = {
            "summary_only": True,
            "preview_summary": {
                # Preserve the legacy artifact contract field for consumers
                # that already display it; ``summary_contract`` versions the
                # compact shape introduced here.
                "contract": artifact_map.get("contract"),
                "summary_contract": TRANSACTION_SHOW_SUMMARY_CONTRACT,
                "detail_level": detail_level,
                "request": request,
                "request_canonical_sha256": request_digest,
                "dispatch": transaction_dispatch_summary(
                    prepared.get("dispatch"),
                    include_payload=bool(variant["include_dispatch_payload"]),
                    include_key_names=bool(variant["include_names_and_sections"]),
                ),
                "resolved_roles": transaction_roles_summary(
                    prepared.get("resolved_roles"),
                    include_items=bool(variant["include_role_items"]),
                    include_role_names=bool(variant["include_names_and_sections"]),
                ),
                "pre_state": transaction_value_summary(
                    prepared.get("pre_state"),
                    include_keys=bool(variant["include_names_and_sections"]),
                    include_sections=bool(variant["include_names_and_sections"]),
                ),
                "verification_plan": transaction_verification_summary(
                    prepared.get("verification_plan"),
                    include_keys=bool(variant["include_names_and_sections"]),
                ),
                # Cleanup is a safety obligation rather than optional review
                # detail.  Preserve the complete immutable spec (including a
                # companion request and binding) in every detail level.
                "cleanup": cleanup,
                "project_guard_fingerprint": project_guard.get("fingerprint"),
                "runtime_guard_fingerprint": runtime_guard.get("fingerprint"),
                "expires_at": artifact_map.get("expires_at"),
                "fixed_projection_limit_bytes": TRANSACTION_SHOW_SUMMARY_FIXED_BUDGET_BYTES,
                "fixed_projection_target_bytes": TRANSACTION_SHOW_SUMMARY_TARGET_BYTES,
                "fixed_projection_bytes": 0,
            },
            "event_count": len(event_rows),
            "events": event_rows,
        }
        observed = stabilize_transaction_summary_size(result)
        observed_by_variant[detail_level] = observed
        if observed <= TRANSACTION_SHOW_SUMMARY_FIXED_BUDGET_BYTES:
            if observed <= TRANSACTION_SHOW_SUMMARY_TARGET_BYTES:
                return result
            # Keep walking toward a smaller projection.  If even the digest
            # variant cannot hit the preferred target, the last bounded
            # candidate is still honest and remains below the hard ceiling.
            bounded_fallback = result

    if bounded_fallback is not None:
        return bounded_fallback

    raise GatewayResultShapeError(
        "The transaction review summary could not fit its fixed JSON budget",
        error_code="SUMMARY_BUDGET_EXCEEDED",
        details={
            "contract": TRANSACTION_SHOW_SUMMARY_CONTRACT,
            "limit_bytes": TRANSACTION_SHOW_SUMMARY_FIXED_BUDGET_BYTES,
            "target_bytes": TRANSACTION_SHOW_SUMMARY_TARGET_BYTES,
            "observed_fixed_projection_bytes": observed_by_variant,
            "request_bytes_excluded_from_limit": request_bytes,
            "request_canonical_sha256": request_digest,
            "truncated": False,
        },
    )


def transaction_dispatch_summary(
    value: Any,
    *,
    include_payload: bool,
    include_key_names: bool = True,
) -> dict[str, Any]:
    """Project a prepared dispatch without duplicating an arbitrarily large request."""

    summary = transaction_value_summary(value, include_keys=include_key_names)
    dispatch = value if isinstance(value, Mapping) else {}
    uri = dispatch.get("uri")
    args = dispatch.get("args")
    options = dispatch.get("options")
    if isinstance(uri, str):
        summary["uri"] = uri
    summary["args_canonical_sha256"] = canonical_sha256(args)
    summary["options_canonical_sha256"] = canonical_sha256(options)
    summary["argument_key_count"] = len(args) if isinstance(args, Mapping) else 0
    summary["option_key_count"] = len(options) if isinstance(options, Mapping) else 0
    summary["key_names_included"] = include_key_names
    if include_key_names:
        summary["argument_keys"] = (
            sorted(str(key) for key in args) if isinstance(args, Mapping) else []
        )
        summary["option_keys"] = (
            sorted(str(key) for key in options) if isinstance(options, Mapping) else []
        )
    summary["payload_included"] = include_payload
    if include_payload:
        summary["args"] = args
        summary["options"] = options
    return summary


def transaction_roles_summary(
    value: Any,
    *,
    include_items: bool,
    include_role_names: bool = True,
) -> dict[str, Any]:
    """Return stable role evidence with optional bounded identity rows."""

    summary = transaction_value_summary(value, include_keys=include_role_names)
    roles = value if isinstance(value, Mapping) else {}
    role_names = sorted(str(role) for role in roles)
    summary["role_count"] = len(role_names)
    summary["role_names_included"] = include_role_names
    if include_role_names:
        summary["role_names"] = role_names
    summary["items_included"] = include_items
    if not include_items:
        return summary

    items: list[dict[str, Any]] = []
    for role in role_names:
        raw = roles.get(role)
        item: dict[str, Any] = {
            "role": role,
            "canonical_sha256": canonical_sha256(raw),
        }
        if isinstance(raw, Mapping):
            for key in ("resolution", "object"):
                candidate = raw.get(key)
                if isinstance(candidate, (str, int, float, bool)) or candidate is None:
                    item[key] = candidate
            identity = raw.get("row")
            if not isinstance(identity, Mapping):
                identity = raw.get("identity")
            if isinstance(identity, Mapping):
                projected = {
                    key: identity.get(key)
                    for key in ("id", "path", "name", "type")
                    if identity.get(key) is not None
                }
                if projected:
                    item["identity"] = projected
        items.append(item)
    summary["items"] = items
    return summary


def transaction_value_summary(
    value: Any,
    *,
    include_keys: bool = True,
    include_sections: bool = False,
) -> dict[str, Any]:
    """Describe one JSON value by type, shape, and canonical digest."""

    summary: dict[str, Any] = {"canonical_sha256": canonical_sha256(value)}
    if isinstance(value, Mapping):
        keys = sorted(str(key) for key in value)
        summary.update(
            {
                "json_type": "object",
                "key_count": len(keys),
                "key_names_included": include_keys,
            }
        )
        if include_keys:
            summary["keys"] = keys
        if include_sections:
            summary["sections"] = [
                {
                    "name": key,
                    **transaction_value_summary(value.get(key), include_keys=include_keys),
                }
                for key in keys
            ]
    elif isinstance(value, list):
        summary.update({"json_type": "array", "item_count": len(value)})
    elif value is None:
        summary["json_type"] = "null"
    elif isinstance(value, bool):
        summary["json_type"] = "boolean"
    elif isinstance(value, (int, float)):
        summary["json_type"] = "number"
    elif isinstance(value, str):
        summary.update({"json_type": "string", "utf8_bytes": len(value.encode("utf-8"))})
    else:
        # Transaction artifacts are strict JSON.  Keeping a distinct label here
        # makes a malformed stored artifact fail during canonical hashing rather
        # than being silently represented as valid JSON evidence.
        summary["json_type"] = type(value).__name__
    return summary


def transaction_verification_summary(
    value: Any,
    *,
    include_keys: bool = True,
) -> dict[str, Any]:
    """Keep the verification strategy legible while hashing its full plan."""

    summary = transaction_value_summary(value, include_keys=include_keys)
    plan = value if isinstance(value, Mapping) else {}
    for key in (
        "kind",
        "strategy",
        "uri",
        "version",
        "on_name_conflict",
        "parent_id",
    ):
        candidate = plan.get(key)
        if isinstance(candidate, (str, int, float, bool)) or candidate is None:
            if key in plan:
                summary[key] = candidate
    for key in (
        "nodes",
        "preexisting_root_rows",
        "replaced_subtree_rows",
        "readbacks",
        "assertions",
    ):
        candidate = plan.get(key)
        if isinstance(candidate, list):
            summary[f"{key}_count"] = len(candidate)
            summary[f"{key}_canonical_sha256"] = canonical_sha256(candidate)
    return summary


def stabilize_transaction_summary_size(result: Mapping[str, Any]) -> int:
    """Record the exact pretty JSON size of the fixed projection.

    The request is deliberately removed for this calculation.  The size field
    itself is included and iterated to a fixed point so the published number is
    exact for the returned summary projection.
    """

    preview_raw = result.get("preview_summary")
    if not isinstance(preview_raw, dict):
        raise GatewayResultShapeError(
            "transaction summary preview must be a JSON object",
            details={"summary_contract": TRANSACTION_SHOW_SUMMARY_CONTRACT},
            error_code="INVALID_TRANSACTION_SUMMARY",
        )
    fixed_preview = {key: value for key, value in preview_raw.items() if key != "request"}
    fixed_result = {
        "summary_only": result.get("summary_only"),
        "preview_summary": fixed_preview,
        "event_count": result.get("event_count"),
        "events": result.get("events"),
    }
    observed = -1
    for _ in range(8):
        fixed_preview["fixed_projection_bytes"] = max(observed, 0)
        next_observed = gateway_json_document_size(fixed_result)
        if next_observed == observed:
            preview_raw["fixed_projection_bytes"] = observed
            return observed
        observed = next_observed
    fixed_preview["fixed_projection_bytes"] = observed
    observed = gateway_json_document_size(fixed_result)
    preview_raw["fixed_projection_bytes"] = observed
    return observed


def verification_deferred_payload(
    common: Mapping[str, Any],
    *,
    transaction_id: str,
    state: str,
    exc: Exception,
    cleanup: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    structured = exc.as_dict() if hasattr(exc, "as_dict") and callable(exc.as_dict) else {}
    error_code = structured.get("error_code") if isinstance(structured, Mapping) else None
    details = structured.get("details") if isinstance(structured, Mapping) else None
    payload = {
        "ok": False,
        "status": "verification_deferred",
        **common,
        "transaction_id": transaction_id,
        "state": state,
        "error_code": error_code or type(exc).__name__,
        "message": str(exc),
        "details": details,
        "automatic_retry": False,
        "manual_verification_retry_allowed": True,
    }
    if cleanup is not None:
        payload["cleanup"] = dict(cleanup)
    return payload


def execution_success_persistence_failure_payload(
    common: Mapping[str, Any],
    *,
    store: TransactionStore,
    transaction_id: str,
    artifact_hash: str,
    prepared: Mapping[str, Any],
    dispatch_result: Mapping[str, Any],
    exc: BaseException,
) -> dict[str, Any]:
    """Preserve a completed mutation when its terminal journal write fails.

    Retrying a successful WAAPI mutation merely because the local completion
    record failed can duplicate work.  This response therefore keeps the
    execution and cleanup evidence, reports the best durable state we can read,
    and explicitly forbids automatic replay.
    """

    persistence_error = normalize_gateway_exception(exc)
    observed_state: str | None = None
    observation_error: dict[str, Any] | None = None
    try:
        observed_state = store.load(transaction_id).state.value
    except BaseException as state_exc:  # noqa: BLE001 - report, never mask, the primary write failure
        observation_error = normalize_gateway_exception(state_exc)
    details: dict[str, Any] = {
        "attempted_transition": TransactionState.EXECUTED_UNVERIFIED.value,
        "persistence_error": persistence_error,
        "durable_state_observed": observed_state is not None,
        "retry_warning": "The WAAPI call succeeded; replay could duplicate the mutation.",
    }
    if observed_state is not None:
        details["observed_durable_state"] = observed_state
    if observation_error is not None:
        details["state_observation_error"] = observation_error
    payload: dict[str, Any] = {
        "ok": False,
        "status": "execution_succeeded_persistence_failed",
        **common,
        "transaction_id": transaction_id,
        "artifact_hash": artifact_hash,
        "error_code": "TRANSACTION_PERSISTENCE_FAILED",
        "message": (
            "The WAAPI mutation succeeded, but its durable transaction completion "
            "could not be recorded. Do not retry it automatically."
        ),
        "details": details,
        "dispatch_result": dict(dispatch_result),
        "executed": True,
        "verified": False,
        "cleanup": transaction_cleanup_payload(
            prepared,
            phase="executed",
            execution_result=dispatch_result,
        ),
        "automatic_retry": False,
    }
    if observed_state is not None:
        payload["state"] = observed_state
    return payload


def transaction_project_guard_spec(
    request: Mapping[str, Any],
    *,
    version: str,
) -> tuple[str, str | None]:
    """Resolve the immutable project guard mode from the public API contract."""

    if request.get("operation") != "waapi.call":
        return PROJECT_GUARD_INVARIANT, None
    arguments = request.get("arguments")
    if not isinstance(arguments, Mapping):
        return PROJECT_GUARD_INVARIANT, None
    api = arguments.get("api")
    if not isinstance(api, str):
        return PROJECT_GUARD_INVARIANT, None
    capability = CapabilityCatalog().describe(version, api)
    mode = capability.execution_contract.get("project_guard_mode", PROJECT_GUARD_INVARIANT)
    if not isinstance(mode, str) or mode not in PROJECT_GUARD_MODES:
        raise GatewayInputError(
            f"Execution contract for {api!r} has unsupported project_guard_mode {mode!r}"
        )
    target_project_path: str | None = None
    if mode == PROJECT_GUARD_TRANSITION_TO_PATH:
        call_args = arguments.get("args")
        target_value = call_args.get("path") if isinstance(call_args, Mapping) else None
        if not isinstance(target_value, str) or not target_value.strip():
            raise GatewayInputError(
                f"Project transition {api!r} requires an explicit target WPROJ path"
            )
        target_project_path = target_value
    return mode, target_project_path


def transaction_post_execution_project_guard_policy(
    request: Mapping[str, Any],
    prepared: Mapping[str, Any],
    *,
    version: str,
) -> str:
    """Read the post-execution project policy sealed into the preview."""

    if request.get("operation") != "waapi.call":
        return POST_EXECUTION_PROJECT_GUARD_REVALIDATE
    arguments = require_mapping(request.get("arguments"), "waapi.call arguments")
    api = arguments.get("api")
    if not isinstance(api, str):
        raise GatewayInputError("waapi.call preview lacks an API URI")
    prepared_request = require_mapping(prepared.get("request"), "prepared request")
    if prepared_request != request:
        raise GatewayInputError(
            "Prepared request does not match the immutable transaction request"
        )
    dispatch_payload = require_mapping(prepared.get("dispatch"), "prepared dispatch")
    expected_dispatch = {
        "uri": api,
        "args": dict(require_mapping(arguments.get("args", {}), "waapi.call args")),
        "options": dict(require_mapping(arguments.get("options", {}), "waapi.call options")),
    }
    if dispatch_payload != expected_dispatch:
        raise GatewayInputError(
            "Prepared dispatch does not match the immutable transaction request"
        )
    pre_state = require_mapping(prepared.get("pre_state"), "prepared pre-state")
    sealed_contract = require_mapping(
        pre_state.get("execution_contract"),
        "prepared execution contract",
    )
    if sealed_contract.get("version") != version or sealed_contract.get("uri") != api:
        raise GatewayInputError(
            "Prepared execution contract does not match the immutable versioned request"
        )
    policy = sealed_contract.get("post_execution_project_guard_policy")
    if not isinstance(policy, str) or policy not in POST_EXECUTION_PROJECT_GUARD_POLICIES:
        raise GatewayInputError(
            f"Execution contract for {api!r} has unsupported "
            f"post_execution_project_guard_policy {policy!r}"
        )
    current_contract = CapabilityCatalog().describe(version, api).execution_contract
    current_policy = current_contract.get("post_execution_project_guard_policy")
    if not isinstance(current_policy, str) or current_policy not in POST_EXECUTION_PROJECT_GUARD_POLICIES:
        raise GatewayInputError(
            f"Packaged execution contract for {api!r} lacks an explicit supported "
            "post-execution project-guard policy"
        )
    if policy != current_policy:
        raise GatewayInputError(
            f"Prepared execution contract for {api!r} no longer matches the packaged "
            "post-execution project-guard policy"
        )
    if (
        policy == POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY
        and (
            api not in CONTEXT_RUNTIME_ONLY_POST_EXECUTION_URIS
            or sealed_contract.get("route") != "isolated_transaction"
            or sealed_contract.get("project_guard_mode") != PROJECT_GUARD_INVARIANT
            or sealed_contract.get("verification_strategy") != "result_schema"
            or current_contract.get("route") != "isolated_transaction"
            or current_contract.get("project_guard_mode") != PROJECT_GUARD_INVARIANT
            or current_contract.get("verification_strategy") != "result_schema"
            or require_mapping(
                prepared.get("verification_plan"),
                "prepared verification plan",
            )
            != {
                "kind": "result-schema",
                "uri": api,
                "version": version,
                "strategy": "result_schema",
            }
        )
    ):
        raise GatewayInputError(
            "The context/runtime-only post-execution policy requires the sealed "
            "reviewed explicit-project Wwise CLI isolated/result-schema contract"
        )
    return policy


def strengthen_project_transition_verification(
    verification: VerificationResult,
    *,
    guard_validation: Mapping[str, Any],
    project_call: Mapping[str, Any],
) -> VerificationResult:
    """Upgrade a generic result-schema receipt after a proven project transition."""

    if not verification.ok:
        return verification
    transition = guard_validation.get("project_transition")
    if not isinstance(transition, Mapping) or transition.get("matched") is not True:
        raise GatewayInputError(
            "Project transition verification requires one matched structured postcondition"
        )
    assertion = {
        "name": "live project matches the immutable transition postcondition",
        "passed": True,
        "evidence": dict(transition),
    }
    readback = {
        "kind": "project-transition-observation",
        "call": dispatch_call_summary(project_call),
        "project": transition.get("actual"),
    }
    return VerificationResult(
        operation=verification.operation,
        status="verified",
        assertions=(*verification.assertions, assertion),
        readbacks=(*verification.readbacks, readback),
        message="The returned WAAPI payload and live project transition postcondition both passed.",
        verification_strength=f"{verification.verification_strength}+project_transition_readback",
        business_state_verified=True,
    )


def current_project(
    dispatcher: WwiseDispatcher,
    *,
    connection: GatewayConnection,
    version: str,
    allow_none: bool = False,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any]]:
    if allow_none:
        # A successful bounded object query with zero Project rows is the only
        # accepted no-project observation.  WAAPI errors and malformed payloads
        # stay failures because their cross-version no-project shape is not a
        # safe contract to guess.
        project_call = dispatch(
            dispatcher,
            OBJECT_GET_URI,
            connection=connection,
            version=version,
            args={"waql": "from type Project take 2"},
            options={"return": ["id", "name", "type", "path", "filePath"]},
        )
        if project_call.get("ok") is not True:
            raise GatewayInputError(
                "Project transition probe failed; refusing to infer that no project is open"
            )
        rows = strict_object_get_rows(
            project_call,
            command="transaction project transition guard",
            maximum_rows=1,
            error_code="INVALID_PROJECT_RESULT",
        )
        if not rows:
            return None, project_call
        project = require_single_result_row(
            rows,
            command="transaction project transition guard",
            error_code="INVALID_PROJECT_RESULT",
        )
        return require_project_identity(
            project,
            command="transaction project transition guard",
        ), project_call
    if version == "2021.1":
        project_call = dispatch(
            dispatcher,
            OBJECT_GET_URI,
            connection=connection,
            version=version,
            args={"waql": "from type Project take 1"},
            options={"return": ["id", "name", "type", "path", "filePath"]},
        )
        rows = (
            strict_object_get_rows(
                project_call,
                command="transaction project guard",
                maximum_rows=1,
                error_code="INVALID_PROJECT_RESULT",
            )
            if project_call.get("ok")
            else []
        )
        if project_call.get("ok") is not True:
            raise GatewayInputError("2021.1 project guard object.get call failed")
        project = require_single_result_row(
            rows,
            command="transaction project guard",
            error_code="INVALID_PROJECT_RESULT",
        )
        return require_project_identity(project, command="transaction project guard"), project_call
    project_call = dispatch(
        dispatcher,
        GET_PROJECT_INFO_URI,
        connection=connection,
        version=version,
    )
    if project_call.get("ok") is not True:
        raise GatewayInputError("getProjectInfo failed while building the transaction project guard")
    project = strict_call_result_mapping(
        project_call,
        command="transaction project guard getProjectInfo",
        error_code="INVALID_PROJECT_RESULT",
    )
    return require_project_identity(project, command="transaction project guard"), project_call


def transaction_read_call(
    dispatcher: WwiseDispatcher,
    *,
    connection: GatewayConnection,
    version: str,
) -> Callable[[str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]:
    def read(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        if uri not in PACKAGED_TRANSACTION_READBACK_URIS:
            raise OperationContractError(
                "UNREVIEWED_READBACK_URI",
                f"Transaction readback URI {uri!r} is not in the packaged read-only allowlist.",
                details={"uri": uri},
            )
        result = dispatch(
            dispatcher,
            uri,
            connection=connection,
            version=version,
            args=args,
            options=options,
            # These exact URIs are operation-owned readbacks.  Some are routed
            # as policy-gated transactions for public use, so the generic
            # dispatcher gate must be bypassed internally without broadening
            # the public direct-call surface.
            allow_destructive=True,
        )
        if result.get("ok") is not True:
            raise OperationContractError(
                "READBACK_FAILED",
                f"Read-only transaction preflight failed for {uri}.",
                details={"call": result},
            )
        payload = result.get("result")
        if not isinstance(payload, Mapping):
            raise OperationContractError(
                "INVALID_READBACK",
                f"Read-only transaction preflight for {uri} did not return a JSON object.",
                details={"call": result},
            )
        return dict(payload)

    return read


def metadata_cached_read_call(
    read_call: Callable[
        [str, Mapping[str, Any], Mapping[str, Any]],
        Mapping[str, Any],
    ],
    *,
    connection: GatewayConnection,
    version: str,
    live_info: Mapping[str, Any],
    project: Mapping[str, Any] | None,
    state_dir: Path | None,
) -> Callable[
    [str, Mapping[str, Any], Mapping[str, Any]],
    Mapping[str, Any],
]:
    """Memoize immutable metadata reads for one exact live Wwise session.

    The cache is never an authority for dynamic values.  Its identity binds the
    endpoint, Wwise build/schema/session/process, project, and packaged
    object-type catalog digest.  If any identity fact is unavailable, the
    gateway safely retains the uncached read path.  This wrapper is shared by
    read-only metadata discovery and mutation preview so a discovery result can
    be reused without weakening preview's live validation.
    """

    if project is None or not isinstance(state_dir, Path) or not state_dir.is_absolute():
        return read_call
    try:
        catalog = ObjectTypeCatalogStore().load(version)
        identity = MetadataSessionIdentity.from_live_context(
            endpoint=connection.url,
            live_info=live_info,
            project=project,
            resource_digest=catalog.resource_sha256,
        )
    except (
        MetadataCacheError,
        MetadataCatalogError,
        MetadataCatalogMissingError,
    ):
        return read_call
    try:
        durable_cache: DurableMetadataCache | None = DurableMetadataCache(
            state_dir=state_dir,
        )
    except MetadataCacheError:
        durable_cache = None
    preview_cache = SessionMetadataCache()

    def cached_read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        lookup = metadata_cache_lookup(uri, args=args, options=options)
        if lookup is None:
            return read_call(uri, args, options)
        hot_cache = (
            _METADATA_SESSION_CACHE
            if lookup.durable_safe
            else preview_cache
        )
        cached = hot_cache.get(identity, lookup)
        if cached is not None:
            if not isinstance(cached, Mapping):  # pragma: no cover - cache invariant
                raise OperationContractError(
                    "INVALID_METADATA_CACHE",
                    "A cached metadata result is not a JSON object.",
                    details={"uri": uri},
                )
            return dict(cached)
        durable = (
            durable_cache.get(identity, lookup)
            if durable_cache is not None
            else None
        )
        if isinstance(durable, Mapping) and valid_metadata_cache_result(
            lookup,
            durable,
        ):
            try:
                hot_cache.put(identity, lookup, durable)
            except MetadataCacheError:
                pass
            return dict(durable)
        result = read_call(uri, args, options)
        if not valid_metadata_cache_result(lookup, result):
            return result
        try:
            hot_cache.put(identity, lookup, result)
        except MetadataCacheError:
            # Oversized or otherwise uncacheable results still remain valid
            # live evidence for this transaction; caching is only an
            # optimization and must not block the operation.
            pass
        else:
            if durable_cache is not None:
                durable_cache.put(identity, lookup, result)
        return result

    return cached_read


def metadata_cached_transaction_read_call(
    read_call: Callable[
        [str, Mapping[str, Any], Mapping[str, Any]],
        Mapping[str, Any],
    ],
    *,
    connection: GatewayConnection,
    version: str,
    live_info: Mapping[str, Any],
    project: Mapping[str, Any] | None,
    state_dir: Path,
) -> Callable[
    [str, Mapping[str, Any], Mapping[str, Any]],
    Mapping[str, Any],
]:
    """Compatibility alias for callers that still use the old narrow name."""

    return metadata_cached_read_call(
        read_call,
        connection=connection,
        version=version,
        live_info=live_info,
        project=project,
        state_dir=state_dir,
    )


def valid_metadata_cache_result(
    lookup: MetadataCacheLookup,
    result: Mapping[str, Any],
) -> bool:
    """Accept only parsed metadata successes into either cache layer."""

    try:
        if lookup.uri == CACHE_GET_TYPES_URI:
            return bool(parse_get_types_result(result))
        if lookup.uri == GET_PROPERTY_AND_REFERENCE_NAMES_URI:
            parse_property_and_reference_names_result(result)
            return True
        if lookup.uri == CACHE_GET_PROPERTY_INFO_URI:
            info = parse_get_property_info_result(result)
            return info.name == lookup.property_name
    except (SemanticValidationError, TypeError, ValueError):
        return False
    return False


def metadata_cache_lookup(
    uri: str,
    *,
    args: Mapping[str, Any],
    options: Mapping[str, Any],
) -> MetadataCacheLookup | None:
    """Translate only exact reviewed metadata calls into cache keys."""

    if options or not isinstance(args, Mapping):
        return None
    try:
        if uri == CACHE_GET_TYPES_URI and not args:
            return MetadataCacheLookup.types()
        if uri == GET_PROPERTY_AND_REFERENCE_NAMES_URI:
            if set(args) == {"classId"}:
                return MetadataCacheLookup.names(class_id=args["classId"])
            if set(args) == {"object"}:
                return MetadataCacheLookup.names(object_id=args["object"])
            return None
        if uri == CACHE_GET_PROPERTY_INFO_URI:
            if set(args) == {"classId", "property"}:
                return MetadataCacheLookup.property_info(
                    class_id=args["classId"],
                    property_name=args["property"],
                )
            if set(args) == {"object", "property"}:
                return MetadataCacheLookup.property_info(
                    object_id=args["object"],
                    property_name=args["property"],
                )
    except MetadataCacheError:
        return None
    return None


def parse_json_object(
    text: str,
    option_name: str,
    *,
    max_document_bytes: int = MAX_GATEWAY_JSON_INPUT_BYTES,
    max_string_bytes: int = MAX_GATEWAY_JSON_STRING_BYTES,
) -> dict[str, Any]:
    payload = parse_strict_json(
        text,
        option_name,
        max_document_bytes=max_document_bytes,
        max_string_bytes=max_string_bytes,
    )
    if not isinstance(payload, dict):
        raise GatewayInputError(f"{option_name} must decode to a JSON object")
    return payload


def parse_operation_draft_cli_actions(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], ...]:
    """Build one bounded ordered production Draft action batch."""

    if not args.facts:
        raise GatewayInputError("draft-apply requires --facts --action and typed facts")
    try:
        return parse_typed_action_cli_argument_sequence(args.facts)
    except OperationComposerError as exc:
        raise GatewayInputError(str(exc)) from exc


def parse_optional_json(text: str | None, option_name: str) -> Any:
    if text is None:
        return None
    return parse_strict_json(text, option_name)


def typed_query_predicates(args: argparse.Namespace) -> Any:
    """Return repeated typed simple predicates."""

    predicates: list[dict[str, Any]] = []
    for field, operator, value_type, raw_value in args.where:
        if value_type == "string":
            value: Any = raw_value
        elif value_type == "integer":
            if re.fullmatch(r"-?(0|[1-9][0-9]*)", raw_value) is None:
                raise GatewayInputError("--where integer values must be canonical")
            value = int(raw_value)
        elif value_type == "number":
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise GatewayInputError("--where number values must be numeric") from exc
            if not math.isfinite(value):
                raise GatewayInputError("--where number values must be finite")
        elif value_type == "boolean":
            if raw_value not in {"true", "false"}:
                raise GatewayInputError("--where boolean values must be true or false")
            value = raw_value == "true"
        else:
            raise GatewayInputError(
                "--where TYPE must be string, integer, number, or boolean"
            )
        predicates.append({"field": field, "operator": operator, "value": value})
    return predicates or None


def parse_strict_json(
    text: str,
    option_name: str,
    *,
    max_document_bytes: int = MAX_GATEWAY_JSON_INPUT_BYTES,
    max_string_bytes: int = MAX_GATEWAY_JSON_STRING_BYTES,
) -> Any:
    """Parse one bounded strict JSON document and validate its value graph."""

    if not isinstance(text, str):
        raise GatewayInputError(f"{option_name} must be a JSON string")
    try:
        encoded_size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise GatewayInputError(f"{option_name} must contain valid Unicode") from exc
    if encoded_size > max_document_bytes:
        raise GatewayInputError(
            f"{option_name} exceeds the {max_document_bytes}-byte JSON input limit"
        )
    try:
        payload = json.loads(
            text,
            parse_constant=_reject_non_json_constant,
            parse_float=_parse_strict_json_float,
            object_pairs_hook=_reject_duplicate_gateway_json_keys,
        )
    except json.JSONDecodeError as exc:
        raise GatewayInputError(f"{option_name} must be valid JSON: {exc.msg}") from exc
    except RecursionError as exc:
        raise GatewayInputError(
            f"{option_name} exceeds the {MAX_GATEWAY_JSON_DEPTH}-level JSON depth limit"
        ) from exc
    except ValueError as exc:
        raise GatewayInputError(f"{option_name} must be strict JSON: {exc}") from exc
    _validate_gateway_json_graph(
        payload,
        option_name=option_name,
        max_string_bytes=max_string_bytes,
    )
    return payload


def _reject_non_json_constant(token: str) -> Any:
    raise ValueError(f"non-finite number {token!r} is not JSON")


def _parse_strict_json_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError(f"non-finite number {token!r} is not JSON")
    return value


def media_pool_post_filter_spec(
    value: Any,
    limit: Any,
) -> dict[str, Any]:
    """Validate the one closed typed Media Pool post-filter contract."""

    if not isinstance(value, str) or not value:
        raise GatewayInputError("--post-filter-value must be a nonempty string")
    if len(value) > MAX_MEDIA_POOL_SEARCH_TEXT_CHARS:
        raise GatewayInputError(
            "--post-filter-value exceeds the reviewed "
            f"{MAX_MEDIA_POOL_SEARCH_TEXT_CHARS}-code-point literal limit"
        )
    if type(limit) is not int or not 1 <= limit <= MAX_MEDIA_POOL_RESULTS:
        raise GatewayInputError(
            "--post-filter-limit must be an integer between 1 and "
            f"{MAX_MEDIA_POOL_RESULTS}"
        )
    return {
        "field": "Filename",
        "operator": "containsCaseSensitive",
        "value": value,
        "limit": limit,
    }


def media_pool_post_filter_spec_from_args(
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    """Build the closed Media Pool filter from its normal typed scalars."""

    typed_value = getattr(args, "post_filter_value", None)
    typed_limit = getattr(args, "post_filter_limit", None)
    if typed_value is None and typed_limit is None:
        return None
    if typed_value is None or typed_limit is None:
        raise GatewayInputError(
            "Media Pool post-filter requires both --post-filter-value and --post-filter-limit"
        )
    return media_pool_post_filter_spec(typed_value, typed_limit)


def validate_media_pool_post_filter_request(
    *,
    api: str,
    spec: Mapping[str, Any],
    request_args: Mapping[str, Any],
    request_options: Mapping[str, Any],
    dry_run: bool,
) -> None:
    """Bind a post-filter to one bounded superset request before connecting."""

    if api != MEDIA_POOL_GET_URI:
        raise GatewayInputError(
            "Typed post-filter fields are supported only for ak.wwise.core.mediaPool.get"
        )
    if dry_run:
        raise GatewayInputError(
            "Typed post-filter fields require a live result and cannot be combined with --dry-run"
        )
    max_results = request_args.get("maxResults")
    if (
        type(max_results) is not int
        or not 1 <= max_results <= MAX_MEDIA_POOL_RESULTS
    ):
        raise GatewayInputError(
            "A Media Pool post-filter requires request maxResults between 1 and "
            f"{MAX_MEDIA_POOL_RESULTS}"
        )
    if max_results < spec["limit"]:
        raise GatewayInputError(
            "A Media Pool post-filter requires request maxResults to be greater "
            "than or equal to its limit"
        )
    filters = request_args.get("filters")
    if not isinstance(filters, list) or not any(
        isinstance(item, Mapping)
        and item.get("type") == "field"
        and item.get("field") == spec["field"]
        and item.get("operator") == "contains"
        and item.get("value") == spec["value"]
        for item in filters
    ):
        raise GatewayInputError(
            "A Media Pool post-filter requires a matching Filename contains field "
            "filter with the same value in the typed request"
        )
    return_fields = request_options.get("return")
    if not isinstance(return_fields, list) or "Filename" not in return_fields:
        raise GatewayInputError(
            "A Media Pool post-filter requires options.return to include 'Filename'"
        )


def media_pool_post_filter_audit(
    spec: Mapping[str, Any],
    *,
    request_max_results: int,
    status: str,
    raw_count: int | None = None,
    matched_count: int | None = None,
    returned_count: int | None = None,
) -> dict[str, Any]:
    """Build a bounded audit projection without echoing the arbitrary match text."""

    value = spec["value"]
    return {
        "contract": MEDIA_POOL_POST_FILTER_CONTRACT,
        "status": status,
        "field": "Filename",
        "operator": "containsCaseSensitive",
        "value_sha256": canonical_sha256({"value": value}),
        "value_code_points": len(value),
        "value_utf8_bytes": len(value.encode("utf-8")),
        "limit": spec["limit"],
        "request_max_results": request_max_results,
        "raw_count": raw_count,
        "matched_count": matched_count,
        "returned_count": returned_count,
        "truncated_to_limit": (
            None
            if matched_count is None or returned_count is None
            else matched_count > returned_count
        ),
    }


def apply_media_pool_post_filter(
    raw_result: Any,
    *,
    spec: Mapping[str, Any],
    request_max_results: int,
    evidence_path: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Apply code-point case-sensitive containment only to a proven-complete candidate set."""

    if not isinstance(raw_result, Mapping) or set(raw_result) != {"return"}:
        raise GatewayResultShapeError(
            "mediaPool.get post-filter expected exactly one top-level return array.",
            details={
                "expected": {"return": "array<object>"},
                "actual_result_type": type(raw_result).__name__,
                "evidence_path": evidence_path,
            },
            error_code="INVALID_MEDIA_POOL_POST_FILTER_RESULT",
        )
    raw_rows = raw_result.get("return")
    if not isinstance(raw_rows, list):
        raise GatewayResultShapeError(
            "mediaPool.get post-filter expected result.return to be an array.",
            details={
                "expected": "array<object>",
                "actual_return_type": type(raw_rows).__name__,
                "evidence_path": evidence_path,
            },
            error_code="INVALID_MEDIA_POOL_POST_FILTER_RESULT",
        )
    rows: list[dict[str, Any]] = []
    for index, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, Mapping):
            raise GatewayResultShapeError(
                "mediaPool.get post-filter expected every return row to be an object.",
                details={
                    "invalid_index": index,
                    "actual_row_type": type(raw_row).__name__,
                    "evidence_path": evidence_path,
                },
                error_code="INVALID_MEDIA_POOL_POST_FILTER_RESULT",
            )
        filename = raw_row.get("Filename")
        if not isinstance(filename, str):
            raise GatewayResultShapeError(
                "mediaPool.get post-filter expected every return row Filename to be a string.",
                details={
                    "invalid_index": index,
                    "actual_filename_type": type(filename).__name__,
                    "evidence_path": evidence_path,
                },
                error_code="INVALID_MEDIA_POOL_POST_FILTER_RESULT",
            )
        rows.append(dict(raw_row))

    raw_count = len(rows)
    if raw_count >= request_max_results:
        return None, media_pool_post_filter_audit(
            spec,
            request_max_results=request_max_results,
            status="incomplete",
            raw_count=raw_count,
        )

    value = spec["value"]
    matches = [row for row in rows if value in row["Filename"]]
    filtered_rows = matches[: spec["limit"]]
    return {"return": filtered_rows}, media_pool_post_filter_audit(
        spec,
        request_max_results=request_max_results,
        status="applied",
        raw_count=raw_count,
        matched_count=len(matches),
        returned_count=len(filtered_rows),
    )


def canonicalize_bounded_direct_call_request(
    api: str,
    version: str,
    request_args: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply exact versioned WAAPI numeric representations after schema validation."""

    normalized = dict(request_args)
    float_fields = (
        MEDIA_POOL_FLOAT_FILTER_FIELDS_BY_VERSION.get(version)
        if api == MEDIA_POOL_GET_URI
        else None
    )
    if not float_fields:
        return normalized

    filters = request_args.get("filters")
    if not isinstance(filters, list):
        return normalized

    normalized_filters: list[Any] = []
    for index, raw_filter in enumerate(filters):
        if not isinstance(raw_filter, Mapping):
            normalized_filters.append(raw_filter)
            continue
        item = dict(raw_filter)
        value = item.get("value")
        if (
            item.get("type") == "field"
            and item.get("field") in float_fields
            and type(value) is int
        ):
            try:
                canonical_value = float(value)
            except OverflowError as exc:
                raise GatewayInputError(
                    f"mediaPool.get filters[{index}].value for {item['field']} "
                    "must be exactly representable as a finite WAAPI double"
                ) from exc
            if not math.isfinite(canonical_value) or int(canonical_value) != value:
                raise GatewayInputError(
                    f"mediaPool.get filters[{index}].value for {item['field']} "
                    "must be exactly representable as a finite WAAPI double"
                )
            item["value"] = canonical_value
        normalized_filters.append(item)
    normalized["filters"] = normalized_filters
    return normalized


def validate_bounded_direct_call_request(
    api: str,
    request_args: Mapping[str, Any],
    request_options: Mapping[str, Any],
) -> None:
    """Apply URI-specific ceilings that reflected schemas do not express."""

    if api != MEDIA_POOL_GET_URI:
        return
    max_results = request_args.get("maxResults")
    if (
        not isinstance(max_results, int)
        or isinstance(max_results, bool)
        or not 1 <= max_results <= MAX_MEDIA_POOL_RESULTS
    ):
        raise GatewayInputError(
            "mediaPool.get requires an explicit maxResults between 1 and "
            f"{MAX_MEDIA_POOL_RESULTS}"
        )
    filters = request_args.get("filters", [])
    databases = request_args.get("databases", [])
    return_fields = request_options.get("return", [])
    if not isinstance(filters, list):
        raise GatewayInputError("mediaPool.get filters must be an array")
    if not isinstance(databases, list):
        raise GatewayInputError("mediaPool.get databases must be an array")
    if not isinstance(return_fields, list):
        raise GatewayInputError("mediaPool.get return must be an array")
    if len(filters) > MAX_MEDIA_POOL_FILTERS:
        raise GatewayInputError(
            f"mediaPool.get accepts at most {MAX_MEDIA_POOL_FILTERS} filters"
        )
    if len(databases) > MAX_MEDIA_POOL_DATABASES:
        raise GatewayInputError(
            f"mediaPool.get accepts at most {MAX_MEDIA_POOL_DATABASES} databases"
        )
    if len(return_fields) > MAX_MEDIA_POOL_RETURN_FIELDS:
        raise GatewayInputError(
            f"mediaPool.get accepts at most {MAX_MEDIA_POOL_RETURN_FIELDS} return fields"
        )
    if len(set(return_fields)) != len(return_fields):
        raise GatewayInputError("mediaPool.get return fields must be unique")
    if not all(isinstance(item, str) and item for item in databases):
        raise GatewayInputError("mediaPool.get databases must contain non-empty strings")
    if len(set(databases)) != len(databases):
        raise GatewayInputError("mediaPool.get databases must be unique")
    for index, raw_filter in enumerate(filters):
        _validate_media_pool_filter(raw_filter, index=index)
    search_text = request_args.get("searchText")
    if isinstance(search_text, str) and len(search_text) > MAX_MEDIA_POOL_SEARCH_TEXT_CHARS:
        raise GatewayInputError(
            "mediaPool.get searchText exceeds the reviewed "
            f"{MAX_MEDIA_POOL_SEARCH_TEXT_CHARS}-character limit"
        )


def _validate_media_pool_filter(raw_filter: Any, *, index: int) -> None:
    path = f"mediaPool.get filters[{index}]"
    if not isinstance(raw_filter, Mapping):
        raise GatewayInputError(f"{path} must be an object")
    filter_type = raw_filter.get("type")
    if filter_type == "field":
        required = {"type", "field", "operator", "value"}
        allowed = required
    elif filter_type == "audioDescription":
        required = {"type", "value"}
        allowed = required | {"weight"}
    elif filter_type == "audioSimilarity":
        required = {"type", "value"}
        allowed = required | {"weight"}
    else:
        raise GatewayInputError(
            f"{path}.type must be field, audioDescription, or audioSimilarity"
        )
    actual = set(raw_filter)
    missing = sorted(required - actual)
    unknown = sorted(actual - allowed)
    if missing or unknown:
        raise GatewayInputError(
            f"{path} does not match the closed {filter_type} filter shape; "
            f"missing={missing}, unknown={unknown}"
        )

    value = raw_filter.get("value")
    if filter_type == "field":
        field = raw_filter.get("field")
        operator = raw_filter.get("operator")
        if (
            not isinstance(field, str)
            or not field
            or len(field) > MAX_MEDIA_POOL_FILTER_TOKEN_CHARS
        ):
            raise GatewayInputError(
                f"{path}.field must be a non-empty string of at most "
                f"{MAX_MEDIA_POOL_FILTER_TOKEN_CHARS} characters"
            )
        if (
            not isinstance(operator, str)
            or not operator
            or len(operator) > MAX_MEDIA_POOL_FILTER_TOKEN_CHARS
        ):
            raise GatewayInputError(
                f"{path}.operator must be a non-empty string of at most "
                f"{MAX_MEDIA_POOL_FILTER_TOKEN_CHARS} characters"
            )
        if isinstance(value, str):
            if len(value) > MAX_MEDIA_POOL_FILTER_VALUE_CHARS:
                raise GatewayInputError(
                    f"{path}.value exceeds the "
                    f"{MAX_MEDIA_POOL_FILTER_VALUE_CHARS}-character limit"
                )
        elif (
            not _is_finite_waapi_number(value)
        ):
            raise GatewayInputError(
                f"{path}.value must be a finite number or bounded string"
            )
        return

    if not isinstance(value, str) or not value:
        raise GatewayInputError(f"{path}.value must be a non-empty string")
    if len(value) > MAX_MEDIA_POOL_FILTER_VALUE_CHARS:
        raise GatewayInputError(
            f"{path}.value exceeds the "
            f"{MAX_MEDIA_POOL_FILTER_VALUE_CHARS}-character limit"
        )
    weight = raw_filter.get("weight", 1.0)
    if (
        not _is_finite_waapi_number(weight)
        or not 0 <= weight <= 1
    ):
        raise GatewayInputError(
            f"{path}.weight must be a finite number from 0 through 1"
        )
    if filter_type == "audioDescription":
        return

    source = Path(value)
    if not source.is_absolute():
        raise GatewayInputError(
            f"{path}.value must be an absolute regular audio-file path"
        )
    try:
        file_mode = source.lstat().st_mode
    except OSError as exc:
        raise GatewayInputError(
            f"{path}.value must name an existing absolute regular audio file"
        ) from exc
    if stat.S_ISLNK(file_mode) or not stat.S_ISREG(file_mode):
        raise GatewayInputError(
            f"{path}.value must name a non-symlink regular audio file"
        )
    if not os.access(source, os.R_OK):
        raise GatewayInputError(f"{path}.value must be readable")


def _is_finite_waapi_number(value: Any) -> bool:
    """Return whether a JSON number has one finite WAAPI double representation."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float):
        return math.isfinite(value)
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        return False
    return math.isfinite(converted)


def _reject_duplicate_gateway_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key {key!r}")
        payload[key] = value
    return payload


def _validate_gateway_json_graph(
    value: Any,
    *,
    option_name: str,
    max_string_bytes: int = MAX_GATEWAY_JSON_STRING_BYTES,
) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        if depth > MAX_GATEWAY_JSON_DEPTH:
            raise GatewayInputError(
                f"{option_name} exceeds the {MAX_GATEWAY_JSON_DEPTH}-level JSON depth limit"
            )
        nodes += 1
        if nodes > MAX_GATEWAY_JSON_NODES:
            raise GatewayInputError(
                f"{option_name} exceeds the {MAX_GATEWAY_JSON_NODES}-node JSON input limit"
            )
        if isinstance(current, str):
            _validate_gateway_json_string(
                current,
                option_name=option_name,
                max_string_bytes=max_string_bytes,
            )
            continue
        if isinstance(current, float) and not math.isfinite(current):
            raise GatewayInputError(f"{option_name} must not contain non-finite numbers")
        if isinstance(current, dict):
            nodes += len(current)
            if nodes > MAX_GATEWAY_JSON_NODES:
                raise GatewayInputError(
                    f"{option_name} exceeds the {MAX_GATEWAY_JSON_NODES}-node JSON input limit"
                )
            for key, item in current.items():
                _validate_gateway_json_string(
                    key,
                    option_name=option_name,
                    max_string_bytes=max_string_bytes,
                )
                stack.append((item, depth + 1))
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _validate_gateway_json_string(
    value: str,
    *,
    option_name: str,
    max_string_bytes: int = MAX_GATEWAY_JSON_STRING_BYTES,
) -> None:
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise GatewayInputError(f"{option_name} must contain valid Unicode") from exc
    if size > max_string_bytes:
        raise GatewayInputError(
            f"{option_name} contains a string longer than the "
            f"{max_string_bytes}-byte string limit"
        )


def build_metadata_command_preview(args: argparse.Namespace, *, version: str) -> Any:
    builder = MetadataBuilder(version=version)
    if args.operation == "types":
        return builder.get_types()
    if args.operation == "names":
        return builder.get_property_and_reference_names(object=args.object, class_id=args.class_id)
    if args.operation == "property-info":
        return builder.get_property_info(property=args.property, object=args.object, class_id=args.class_id)
    if args.operation == "property-enabled":
        return builder.is_property_enabled(object=args.object, property=args.property, platform=args.platform)
    if args.operation == "attenuation-curve":
        return builder.get_attenuation_curve(
            object=args.object,
            curve_type=args.curve_type,
            platform=args.platform,
        )
    raise GatewayInputError(f"unsupported metadata operation: {args.operation}")


def normalize_metadata_result(operation: str, result: Mapping[str, Any]) -> Any:
    payload = result.get("result")
    if not isinstance(payload, Mapping):
        raise GatewayInputError(f"metadata {operation} result must be a JSON object")
    if operation == "types":
        return [record.as_dict() for record in parse_get_types_result(payload)]
    if operation == "names":
        return [record.as_dict() for record in parse_property_and_reference_names_result(payload)]
    if operation == "property-info":
        return parse_get_property_info_result(payload).as_dict()
    if operation == "property-enabled":
        return parse_is_property_enabled_result(payload).as_dict()
    if operation == "attenuation-curve":
        record = parse_get_attenuation_curve_result(payload, allow_documented_empty=True)
        return record.as_dict() if record is not None else None
    raise GatewayInputError(f"unsupported metadata operation: {operation}")


def normalize_topic_event_result(
    result: Mapping[str, Any],
    *,
    expected_topic: str,
) -> Any:
    """Unwrap and validate the dispatcher's SubscriptionEvent envelope."""

    wrapper = result.get("result")
    if not isinstance(wrapper, Mapping) or set(wrapper) != {"topic", "payload", "args", "kwargs"}:
        raise GatewayResultShapeError(
            "wait-topic requires the exact dispatcher event envelope.",
            details={
                "expected_fields": ["topic", "payload", "args", "kwargs"],
                "actual_fields": sorted(str(key) for key in wrapper) if isinstance(wrapper, Mapping) else None,
            },
            error_code="INVALID_TOPIC_RESULT",
        )
    if wrapper.get("topic") != expected_topic:
        raise GatewayResultShapeError(
            "wait-topic dispatcher result changed the subscribed topic.",
            details={
                "expected_topic": expected_topic,
                "actual_topic": wrapper.get("topic"),
            },
            error_code="INVALID_TOPIC_RESULT",
        )
    event_args = wrapper.get("args")
    event_kwargs = wrapper.get("kwargs")
    if not isinstance(event_args, (list, tuple)) or not isinstance(event_kwargs, Mapping):
        raise GatewayResultShapeError(
            "wait-topic dispatcher event args/kwargs have invalid shapes.",
            details={
                "args_type": type(event_args).__name__,
                "kwargs_type": type(event_kwargs).__name__,
            },
            error_code="INVALID_TOPIC_RESULT",
        )
    expected_payload: Any
    if len(event_args) == 1:
        expected_payload = event_args[0]
    elif event_args:
        expected_payload = event_args
    else:
        expected_payload = event_kwargs
    payload = wrapper.get("payload")
    if payload != expected_payload:
        raise GatewayResultShapeError(
            "wait-topic dispatcher payload disagrees with its callback args/kwargs.",
            details={"topic": expected_topic},
            error_code="INVALID_TOPIC_RESULT",
        )
    return payload


def normalize_topic_events_result(
    result: Mapping[str, Any],
    *,
    expected_topic: str,
    expected_count: int,
) -> list[Any]:
    """Unwrap the dispatcher's exact bounded multi-event envelope."""

    wrapper = result.get("result")
    expected_fields = {"requested_event_count", "events"}
    if not isinstance(wrapper, Mapping) or set(wrapper) != expected_fields:
        raise GatewayResultShapeError(
            "wait-topic multi-event mode requires the exact dispatcher collection envelope.",
            details={
                "expected_fields": sorted(expected_fields),
                "actual_fields": sorted(str(key) for key in wrapper) if isinstance(wrapper, Mapping) else None,
            },
            error_code="INVALID_TOPIC_RESULT",
        )
    if wrapper.get("requested_event_count") != expected_count:
        raise GatewayResultShapeError(
            "wait-topic dispatcher result changed the requested event count.",
            details={
                "expected_count": expected_count,
                "actual_count": wrapper.get("requested_event_count"),
            },
            error_code="INVALID_TOPIC_RESULT",
        )
    event_wrappers = wrapper.get("events")
    if not isinstance(event_wrappers, list) or len(event_wrappers) != expected_count:
        raise GatewayResultShapeError(
            "wait-topic dispatcher result did not contain the requested number of events.",
            details={
                "expected_count": expected_count,
                "actual_count": len(event_wrappers) if isinstance(event_wrappers, list) else None,
            },
            error_code="INVALID_TOPIC_RESULT",
        )
    return [
        normalize_topic_event_result(
            {"result": event_wrapper},
            expected_topic=expected_topic,
        )
        for event_wrapper in event_wrappers
    ]


def normalize_reflection_inventory_result(
    api: str,
    result: Mapping[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    """Validate and normalize the two zero-input public reflection lists."""

    field, item_type = REFLECTION_INVENTORY_CALLS[api]
    payload = result.get("result")
    if not isinstance(payload, Mapping) or set(payload) != {field}:
        raise GatewayResultShapeError(
            f"{api} requires an exact result object containing only {field!r}.",
            details={
                "api": api,
                "expected_fields": [field],
                "actual_fields": sorted(str(key) for key in payload) if isinstance(payload, Mapping) else None,
            },
            error_code="INVALID_REFLECTION_RESULT",
        )
    raw_entries = payload.get(field)
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_REFLECTION_INVENTORY_ITEMS:
        raise GatewayResultShapeError(
            f"{api} requires a bounded JSON string array.",
            details={
                "api": api,
                "field": field,
                "maximum_items": MAX_REFLECTION_INVENTORY_ITEMS,
                "actual_count": len(raw_entries) if isinstance(raw_entries, list) else None,
            },
            error_code="INVALID_REFLECTION_RESULT",
        )
    live_uris: list[str] = []
    for index, uri in enumerate(raw_entries):
        if not isinstance(uri, str) or not uri or uri != uri.strip() or not uri.startswith("ak."):
            raise GatewayResultShapeError(
                f"{api} returned an invalid URI at index {index}.",
                details={"api": api, "field": field, "invalid_index": index},
                error_code="INVALID_REFLECTION_RESULT",
            )
        try:
            uri_size = len(uri.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise GatewayResultShapeError(
                f"{api} returned invalid Unicode at index {index}.",
                details={"api": api, "field": field, "invalid_index": index},
                error_code="INVALID_REFLECTION_RESULT",
            ) from exc
        if uri_size > MAX_REFLECTION_URI_BYTES:
            raise GatewayResultShapeError(
                f"{api} returned an oversized URI at index {index}.",
                details={
                    "api": api,
                    "field": field,
                    "invalid_index": index,
                    "maximum_uri_bytes": MAX_REFLECTION_URI_BYTES,
                },
                error_code="INVALID_REFLECTION_RESULT",
            )
        live_uris.append(uri)
    if len(set(live_uris)) != len(live_uris):
        raise GatewayResultShapeError(
            f"{api} returned duplicate URIs.",
            details={"api": api, "field": field, "actual_count": len(live_uris)},
            error_code="INVALID_REFLECTION_RESULT",
        )

    normalized = sorted(live_uris)
    packaged = sorted(
        entry.uri
        for entry in CapabilityCatalog().select(version, item_type=item_type)
    )
    live_set = set(normalized)
    packaged_set = set(packaged)
    missing = sorted(packaged_set - live_set)
    extra = sorted(live_set - packaged_set)
    return {
        "kind": item_type,
        "count": len(normalized),
        "uris": normalized,
        "packaged_manifest": {
            "count": len(packaged),
            "matches": not missing and not extra,
            "missing_count": len(missing),
            "extra_count": len(extra),
            "missing_sample": missing[:20],
            "extra_sample": extra[:20],
        },
    }


def require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GatewayInputError(f"{label} must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    def stream_stdout_sink(record: Mapping[str, Any]) -> None:
        print(topic_stream_stdout_json_encoder().encode(record), flush=True)

    command_line = tuple(sys.argv[1:] if argv is None else argv)
    if "stream-topic" in command_line:
        exit_code, payload = execute_gateway(
            argv,
            stream_sink=stream_stdout_sink,
        )
    else:
        exit_code, payload = execute_gateway(argv)
    if payload.get("contract") == TOPIC_STREAM_RECORD_CONTRACT:
        print(topic_stream_stdout_json_encoder().encode(payload), flush=True)
    else:
        print(gateway_stdout_json_encoder(payload).encode(payload))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
