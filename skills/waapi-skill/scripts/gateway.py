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
    metadata_candidate_limit_contract,
    metadata_typed_value_type,
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
    normalize_profiler_time,
    normalize_profiler_voice_contributions_result,
    normalize_project_default_work_units_result,
)
from wwise_waapi.typed_requests import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    MAX_TYPED_ARRAY_ITEMS,
    TYPED_REQUEST_COMPLEX_TRACER_URI,
    TypedRequestContract,
    TypedRequestError,
    TypedRequestFact,
    dynamic_array_item_choices,
    dynamic_array_item_handle,
    dynamic_container_disclosure,
    dynamic_fixed_container_members,
    dynamic_map_container_choices,
    dynamic_map_entry_handle,
    materialize_typed_request,
    parse_typed_schema_lineage_token,
    request_contract,
    typed_schema_lineage_business_pointer,
    typed_schema_lineage_root_fact,
    typed_schema_lineage_root_business_pointer,
    typed_schema_lineage_token,
    typed_container_command_contract,
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
    BUSINESS_DECLARATION_INPUT_MODE,
    COMPOSER_INPUT_MODE,
    INLINE_TYPED_INPUT_MODE,
    OPERATION_REQUEST_CONTRACT,
    PACKAGED_TRANSACTION_READBACK_URIS,
    PREPARED_OPERATION_CONTRACT,
    UNDO_GROUP_MAX_CALLS,
    UI_COMMAND_OPERATIONS,
    OperationContractError,
    VerificationResult,
    audio_import_business_contract,
    operation_business_contract,
    build_undo_group_execution_plan,
    describe_operation,
    list_operation_specs,
    operation_input_mode,
    operation_uses_business_declaration,
    operation_request_schema_digest,
    parse_operation_request,
    prepare_object_set_batch_check,
    validate_prepared_roles,
    verify_prepared_operation,
)
from wwise_waapi.operation_object import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    ObjectOperationContractError,
    normalize_object_identity,
)
from wwise_waapi.waql import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    quote_waql_literal,
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
from wwise_waapi.business_declaration_state import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    BusinessDeclarationSession,
)
from wwise_waapi.business_adapters import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    business_adapter,
)
from wwise_waapi.business_declarations import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    MAX_BUSINESS_NAME_BYTES,
    MAX_BUSINESS_PATH_BYTES,
    SUPPORTED_BUSINESS_KINDS,
    BusinessContext,
    BusinessDeclarationError,
    BusinessHandleRegistry,
    ExistingObjectTarget,
    NewDescendantTarget,
    bind_live_field,
    business_repair,
    revalidate_live_field,
    revalidate_live_objects,
    revalidate_live_types,
    resolve_semantic_kind,
)
from wwise_waapi.soundbank_business_cli import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    SoundBankBusinessCliError,
    add_soundbank_plan_arguments,
    soundbank_plan_from_namespace,
)
from wwise_waapi.exact_artifact_business_cli import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    ExactArtifactBusinessCliError,
    add_exact_artifact_plan_arguments,
    exact_artifact_plan_from_namespace,
)
from wwise_waapi.exact_artifact_business import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    exact_artifact_evidence_from_request,
)
from wwise_waapi.authoring_ui_business_cli import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    AuthoringUiBusinessCliError,
    add_authoring_ui_command_arguments,
    add_authoring_ui_plan_arguments,
    authoring_ui_command_from_namespace,
    authoring_ui_plan_from_namespace,
)
from wwise_waapi.authoring_ui_business import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    append_authoring_ui_command,
    validate_authoring_ui_business_session,
)
from wwise_waapi.debug_business_cli import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    DebugBusinessCliError,
    add_debug_intent_arguments,
    debug_intent_from_namespace,
)
from wwise_waapi.compound_undo_business import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    CheckedChildDraftBinding,
    CompoundUndoSnapshotScope,
    snapshot_checked_compound_undo_children,
)
from wwise_waapi.operation_composer import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    MAX_TYPED_ACTIONS_PER_APPLY,
    OperationComposerError,
    composition_projection,
    operation_draft_public_projection,
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
TOPIC_CLEANUP_RESERVE_RATIO = 0.50
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
        "draft-add-media",
        "draft-business-configure",
        "draft-clear-object-list",
        "draft-declare-field-change",
        "draft-declare-import-batch",
        "draft-declare-object-change",
        "draft-declare-switch-assignment",
        "draft-declare-rtpc",
        "draft-declare-existing",
        "draft-declare-new",
        "draft-remove-declaration",
        "draft-revise-declaration",
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
OPERATION_DRAFT_COMMAND_COPY_INSTRUCTION_CONTRACT = (
    "waapi-skill.operation-draft-command-copy-instruction/v1"
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
QUERY_BUSINESS_PREDICATES: Mapping[str, tuple[str, str, str]] = {
    "name-is": ("name", "=", "string"),
    "name-contains": ("name", ":", "string"),
    "notes-contain": ("notes", ":", "string"),
    "volume-db-at-most": ("@Volume", "<=", "number"),
    "volume-db-at-least": ("@Volume", ">=", "number"),
    "included-is": ("isIncluded", "=", "boolean"),
    "playable-is": ("isPlayable", "=", "boolean"),
    "explicitly-muted-is": ("isExplicitMute", "=", "boolean"),
    "explicitly-soloed-is": ("isExplicitSolo", "=", "boolean"),
    "children-at-least": ("childrenCount", ">=", "integer"),
    "plugin-name-is": ("pluginName", "=", "string"),
    "category-is": ("category", "=", "string"),
}
QUERY_BUSINESS_KIND_PREDICATE = "kind-is"
QUERY_FIXED_KIND_TYPES: Mapping[str, str] = {
    "all-sounds": "Sound",
    "project": "Project",
    "saved-query": "Query",
}
QUERY_BUSINESS_KINDS = tuple(
    sorted({*SUPPORTED_BUSINESS_KINDS, *QUERY_FIXED_KIND_TYPES})
)
QUERY_BUSINESS_RELATIONSHIPS: Mapping[str, str] = {
    "descendants": "descendants",
    "ancestors": "ancestors",
    "references-to": "referencesTo",
    "children": "children",
    "parent": "parent",
}
QUERY_BUSINESS_OUTPUTS: Mapping[str, tuple[str, str]] = {
    "notes": ("notes", "notes"),
    "volume-db": ("@Volume", "volume_db"),
    "pitch-cents": ("@Pitch", "pitch_cents"),
    "output-bus": ("OutputBus", "output_bus"),
    "source-language": ("audioSource:language", "source_language"),
    "parent": ("parent", "parent"),
    "owner": ("owner", "owner"),
    "included": ("isIncluded", "included"),
    "playable": ("isPlayable", "playable"),
    "explicitly-muted": ("isExplicitMute", "explicitly_muted"),
    "explicitly-soloed": ("isExplicitSolo", "explicitly_soloed"),
    "child-count": ("childrenCount", "child_count"),
    "plugin-name": ("pluginName", "plugin_name"),
    "category": ("category", "category"),
    "file-path": ("filePath", "file_path"),
    "original-file-path": ("originalFilePath", "original_file_path"),
    "active-source": ("activeSource", "active_source"),
    "action-type": ("ActionType", "action_type"),
    "target": ("Target", "target"),
    "override-output": ("OverrideOutput", "override_output"),
    "work-unit": ("workunit", "work_unit"),
    "source-duration": ("audioSource:playbackDuration", "source_duration"),
    "max-radius": ("audioSource:maxRadiusAttenuation", "max_radius"),
}
MAX_QUERY_BUSINESS_OUTPUTS = 32
MAX_QUERY_CUSTOM_OUTPUTS = 16
MAX_QUERY_CUSTOM_FIELD_CHARS = 128
BUSINESS_QUERY_CONTRACT = "waapi-skill.object-query-business/v1"
BUSINESS_QUERY_SCHEMA_CONTRACT = "waapi-skill.object-query-business-schema/v1"
ADVANCED_QUERY_SCHEMA_CONTRACT = (
    "waapi-skill.advanced-object-query-business-schema/v1"
)
METADATA_CURVE_ROLES: Mapping[str, str] = {
    "volume-dry": "VolumeDryUsage",
    "game-defined-aux-send-volume": "VolumeAuxGameDef",
    "user-defined-aux-send-volume": "VolumeAuxUserDef",
    "low-pass-filter": "LowPassFilter",
    "high-pass-filter": "HighPassFilter",
    "spread": "Spread",
    "focus": "Focus",
}
PROFILER_PIPELINE_IDENTITY_RETURN_FIELDS = (
    "pipelineID",
    "gameObjectID",
    "objectGUID",
    "objectName",
    "gameObjectName",
)
MAX_PROFILER_PIPELINE_IDENTITY_ROWS = 4096
MEDIA_POOL_FLOAT_FILTER_FIELDS_BY_VERSION: Mapping[str, frozenset[str]] = {
    "2025.1": frozenset({"WAV/Duration"}),
}
ORIGINAL_FILE_REFERENCE_MATCH_VERSION = "2025.1"
ORIGINAL_FILE_REFERENCE_MATCH_TYPE = "AudioFileSource"
ORIGINAL_FILE_REFERENCE_RETURN_FIELDS = ("id", "path", "originalFilePath")
MAX_ORIGINAL_FILE_PATH_CANDIDATES = 64
MAX_ORIGINAL_FILE_PATH_BYTES = 1024
MAX_ORIGINAL_FILE_REFERENCE_PATH_BYTES = 512
MAX_BUSINESS_OBJECT_PATH_SEGMENTS = 64
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


def _add_business_draft_binding_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument("draft_id")
    parser.add_argument("--task-authority", required=True)
    parser.add_argument("--expected-revision", required=True, type=int)


def _add_business_declaration_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    _add_business_draft_binding_arguments(parser)
    parser.add_argument("--declaration-id", required=True)
    parser.add_argument(
        "--field",
        action="append",
        nargs=2,
        default=[],
        metavar=("FIELD", "VALUE"),
        help="Set one stable high-level field; repeat for additional fields",
    )
    parser.add_argument(
        "--field-value",
        action="append",
        nargs=2,
        default=[],
        metavar=("FIELD_HANDLE", "VALUE"),
        help="Set one live-bound custom property or reference by opaque handle",
    )
    parser.add_argument(
        "--switch-value",
        help=(
            "Assign this import declaration to one exact user-requested Switch "
            "value without encoding it as a generic field pair"
        ),
    )
    parser.add_argument("--event-parent-handle")
    parser.add_argument("--event-name")
    parser.add_argument(
        "--event-action",
        choices=("Play", "Stop", "Pause", "Resume", "Break", "Seek"),
    )

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
    subparsers.add_parser(
        "project-default-work-units",
        help="Report version-aware default project Work Units without fabricating unavailable fields",
    )

    profiler_game_objects = subparsers.add_parser(
        "profiler-game-objects",
        help="Return profiler game objects through a cross-version registration-time projection",
    )
    profiler_game_objects_capture = profiler_game_objects.add_mutually_exclusive_group(
        required=True
    )
    profiler_game_objects_capture.add_argument(
        "--capture",
        choices=("latest", "user-cursor"),
        help="Choose the latest capture or the user-positioned profiler cursor",
    )
    profiler_game_objects_capture.add_argument(
        "--capture-ms",
        help="Exact non-negative capture time in milliseconds",
    )
    profiler_game_objects.set_defaults(time=None)

    profiler_voice_contributions = subparsers.add_parser(
        "profiler-voice-contributions",
        help="Return one bounded voice contribution tree with version-aware DSF availability",
    )
    profiler_voice_capture = profiler_voice_contributions.add_mutually_exclusive_group(
        required=True
    )
    profiler_voice_capture.add_argument(
        "--capture",
        choices=("latest", "user-cursor"),
        help="Choose the latest capture or the user-positioned profiler cursor",
    )
    profiler_voice_capture.add_argument(
        "--capture-ms",
        help="Exact non-negative capture time in milliseconds",
    )
    profiler_voice_contributions.add_argument(
        "--voice-object-id",
        required=True,
        help="Exact canonical Wwise object GUID for the requested active voice",
    )
    profiler_voice_contributions.add_argument(
        "--game-object-id",
        help="Optional exact runtime game-object ID used only to disambiguate voices",
    )
    profiler_voice_contributions.add_argument(
        "--bus-object-id",
        action="append",
        default=[],
        help=(
            "Repeat exact canonical Wwise Bus GUIDs in the requested voice-path "
            "order; omit for the dry path"
        ),
    )
    profiler_voice_contributions.set_defaults(
        time=None,
        voice_pipeline_id=None,
        bus_pipeline_id=[],
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
        "--max-nodes",
        type=int,
        default=128,
        dest="max_nodes",
        metavar=f"1..{MAX_WAL_TREE_NODES}",
        help=(
            "Maximum WAL nodes returned after the complete bounded call; "
            f"defaults to 128 and is capped at {MAX_WAL_TREE_NODES}"
        ),
    )
    debug_validate_call = subparsers.add_parser(
        "debug-validate-call",
        help=(
            "Validate one exact reflected function and, optionally, a bounded "
            "user-owned call artifact without executing that function"
        ),
    )
    debug_validate_call.add_argument(
        "api",
        help="Exact reflected WAAPI function URI to validate",
    )
    debug_validate_call.add_argument(
        "--artifact-file",
        help=(
            "Absolute path to a user-owned strict JSON object containing only "
            "optional args, options, and result objects"
        ),
    )

    query_object = subparsers.add_parser(
        "query-object",
        help="Run a source-grounded read-only object query without composing WAAPI code",
    )
    query_source = query_object.add_mutually_exclusive_group()
    query_source.add_argument(
        "--path-segment",
        action="append",
        dest="path_segments",
        help=(
            "Repeat one user-visible hierarchy name per level; the Gateway "
            "constructs the exact Wwise path and separators"
        ),
    )
    query_object.set_defaults(
        path=None,
        object_id=None,
        object_type=None,
        search=None,
        query=None,
        where=None,
        select=None,
        take=None,
        all_results=False,
    )
    query_source.add_argument("--exact-id", dest="object_id")
    query_source.add_argument(
        "--kind",
        choices=QUERY_BUSINESS_KINDS,
        dest="semantic_kind",
        help=(
            "Stable Wwise business kind; the Gateway derives the native type "
            "and any required Sound SFX/Voice predicate"
        ),
    )
    query_source.add_argument(
        "--custom-kind",
        dest="custom_kind_meaning",
        help=(
            "User-facing custom object/plug-in kind meaning; the Gateway binds "
            "it to one exact live Wwise type before constructing WAQL"
        ),
    )
    query_source.add_argument("--search-text", dest="search")
    query_source.add_argument(
        "--query-id",
        dest="query_id",
        metavar="QUERY_GUID",
        help=(
            "Exact Query Editor object GUID; raw WAQL is not accepted"
        ),
    )
    query_source.add_argument(
        "--query-path-segment",
        action="append",
        dest="query_path_segments",
        help=(
            "Repeat one Query Editor folder/name below the Queries root; the "
            "Gateway constructs the exact path and separators"
        ),
    )
    query_source.add_argument(
        "--advanced-waql",
        dest="advanced_waql",
        metavar="BOUNDED_WAQL",
        help=(
            "One exact bounded read-only domain expression disclosed only by "
            "query-schema --advanced; the Gateway owns URI, projection, and cap"
        ),
    )
    query_object.add_argument("--max-results", type=int)
    query_object.add_argument(
        "--include",
        action="append",
        choices=tuple(QUERY_BUSINESS_OUTPUTS),
        default=[],
        dest="business_outputs",
        help=(
            "Repeat one business result field; the Gateway derives the native "
            "projection and returns a stable business key"
        ),
    )
    query_object.add_argument(
        "--include-field",
        action="append",
        default=[],
        dest="custom_field_meanings",
        help=(
            "Repeat one user-facing custom property/reference meaning; the Gateway "
            "discovers and binds the exact live field before object.get"
        ),
    )
    query_object.add_argument(
        "--predicate",
        nargs=2,
        action="append",
        default=[],
        metavar=("BUSINESS_CONDITION", "VALUE"),
        dest="business_predicates",
        help=(
            "Repeat one closed business condition and value; the Gateway "
            "derives the native accessor, operator, and wire type"
        ),
    )
    query_object.add_argument(
        "--match-original-file-path",
        action="append",
        dest="match_original_file_paths",
        metavar="ABSOLUTE_PATH",
        help=(
            "Repeat for 1..64 absolute Media Pool candidate paths; only the fixed "
            "2025.1 AudioFileSource max-1000 reference-match mode accepts this option"
        ),
    )
    query_object.add_argument(
        "--relationship",
        action="append",
        choices=tuple(QUERY_BUSINESS_RELATIONSHIPS),
        dest="relationships",
        help=(
            "Repeat one user-requested object relationship; the Gateway "
            "derives the exact WAQL select token and order"
        ),
    )
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
            "discover",
            "property-state",
            "attenuation",
        ),
    )
    metadata_scope = metadata.add_mutually_exclusive_group()
    metadata_scope.add_argument(
        "--path-segment",
        action="append",
        dest="metadata_path_segments",
        help=(
            "Repeat one user-visible object hierarchy name per level; the "
            "Gateway constructs the exact Wwise object scope"
        ),
    )
    metadata_scope.add_argument(
        "--kind",
        choices=QUERY_BUSINESS_KINDS,
        dest="metadata_semantic_kind",
        help=(
            "Closed business kind for class-scoped field discovery; the Gateway "
            "derives the exact versioned metadata type"
        ),
    )
    metadata_scope.add_argument(
        "--custom-kind",
        dest="metadata_custom_kind_meaning",
        help=(
            "User-facing custom object/plug-in kind meaning; the Gateway binds "
            "it to one exact live Wwise metadata type"
        ),
    )
    metadata_scope.add_argument(
        "--exact-id",
        dest="metadata_exact_id",
        help="Exact canonical object GUID returned by a prior bounded query",
    )
    metadata.add_argument(
        "--meaning",
        action="append",
        dest="metadata_meanings",
        metavar="USER_FACING_FIELD_MEANING",
        help=(
            "Repeat one user-facing property/reference meaning; the Gateway "
            "discovers the exact live field metadata"
        ),
    )
    metadata.add_argument("--platform")
    metadata.add_argument(
        "--curve-role",
        choices=(
            "volume-dry",
            "game-defined-aux-send-volume",
            "user-defined-aux-send-volume",
            "low-pass-filter",
            "high-pass-filter",
            "spread",
            "focus",
        ),
        dest="curve_role",
        help=(
            "User-facing attenuation curve role; the Gateway derives Wwise's "
            "exact curveType token"
        ),
    )
    metadata.set_defaults(
        object=None,
        class_id=None,
        object_type=None,
        property=None,
        curve_type=None,
        queries=None,
        limit=None,
        detail=False,
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

    draft_business_configure = subparsers.add_parser(
        "draft-business-configure",
        help="Set complete high-level audio import batch behavior offline",
    )
    _add_business_draft_binding_arguments(draft_business_configure)
    draft_business_configure.add_argument(
        "--mode", choices=("create", "reimport", "replace")
    )
    draft_business_configure.add_argument(
        "--name-conflict",
        choices=("fail", "rename", "merge", "replace"),
    )
    draft_business_configure.add_argument("--replace-owner-handle")
    draft_business_configure.add_argument("--platform")
    draft_business_configure.add_argument(
        "--list-behavior",
        choices=("append", "replace-all"),
    )
    source_control = draft_business_configure.add_mutually_exclusive_group()
    source_control.add_argument(
        "--add-to-source-control",
        dest="add_to_source_control",
        action="store_true",
    )
    source_control.add_argument(
        "--no-add-to-source-control",
        dest="add_to_source_control",
        action="store_false",
    )
    draft_business_configure.set_defaults(add_to_source_control=None)
    check_out = draft_business_configure.add_mutually_exclusive_group()
    check_out.add_argument(
        "--check-out-from-source-control",
        dest="check_out_from_source_control",
        action="store_true",
    )
    check_out.add_argument(
        "--no-check-out-from-source-control",
        dest="check_out_from_source_control",
        action="store_false",
    )
    draft_business_configure.set_defaults(check_out_from_source_control=None)
    draft_business_configure.add_argument(
        "--default",
        action="append",
        nargs=2,
        default=[],
        metavar=("FIELD", "VALUE"),
    )
    draft_business_configure.add_argument(
        "--default-field-value",
        action="append",
        nargs=2,
        default=[],
        metavar=("FIELD_HANDLE", "VALUE"),
    )
    draft_business_configure.add_argument("--default-event-parent-handle")
    draft_business_configure.add_argument("--default-event-name")
    draft_business_configure.add_argument(
        "--default-event-action",
        choices=("Play", "Stop", "Pause", "Resume", "Break", "Seek"),
    )

    draft_declare_import_batch = subparsers.add_parser(
        "draft-declare-import-batch",
        help=(
            "Atomically submit one complete high-level audio import batch "
            "without native WAAPI rows or JSON shell quoting"
        ),
    )
    _add_business_draft_binding_arguments(draft_declare_import_batch)
    draft_declare_import_batch.add_argument(
        "--expected-declaration-count",
        required=True,
        type=int,
    )
    draft_declare_import_batch.add_argument(
        "--expected-switch-assignment-count",
        required=True,
        type=int,
    )
    draft_declare_import_batch.add_argument(
        "--row-order",
        action="append",
        required=True,
        metavar="ID",
        help="Repeat once per row in the exact requested import order",
    )
    draft_declare_import_batch.add_argument(
        "--new-root-row",
        action="append",
        nargs=4,
        default=[],
        metavar=("ID", "PARENT_HANDLE", "NAME", "KIND"),
    )
    draft_declare_import_batch.add_argument(
        "--new-child-row",
        action="append",
        nargs=4,
        default=[],
        metavar=("ID", "PARENT_ID", "NAME", "KIND"),
    )
    draft_declare_import_batch.add_argument(
        "--new-row",
        action="append",
        nargs=4,
        default=[],
        metavar=("ID", "PARENT_HANDLE_OR_ID", "NAME", "KIND"),
    )
    draft_declare_import_batch.add_argument(
        "--existing-row",
        action="append",
        nargs=2,
        default=[],
        metavar=("ID", "OBJECT_HANDLE"),
    )
    draft_declare_import_batch.add_argument(
        "--field",
        action="append",
        nargs=3,
        default=[],
        metavar=("ID", "FIELD", "VALUE"),
    )
    draft_declare_import_batch.add_argument(
        "--field-value",
        action="append",
        nargs=3,
        default=[],
        metavar=("ID", "FIELD_HANDLE", "VALUE"),
    )
    draft_declare_import_batch.add_argument(
        "--media-directory",
        metavar="ABSOLUTE_DIRECTORY",
    )
    draft_declare_import_batch.add_argument(
        "--media-file",
        action="append",
        nargs=2,
        default=[],
        metavar=("ID", "FILE_NAME"),
    )
    draft_declare_import_batch.add_argument(
        "--switch-value",
        action="append",
        nargs=2,
        default=[],
        metavar=("ID", "VALUE"),
    )
    draft_declare_import_batch.add_argument(
        "--event",
        action="append",
        nargs=4,
        default=[],
        metavar=("ID", "PARENT_HANDLE", "NAME", "ACTION"),
    )

    draft_declare_object_change = subparsers.add_parser(
        "draft-declare-object-change",
        help=(
            "Declare one simple existing-object business outcome using only "
            "opaque handles and operation-specific scalar facts"
        ),
    )
    _add_business_draft_binding_arguments(draft_declare_object_change)
    draft_declare_object_change.add_argument("--object-handle", required=True)
    draft_declare_object_change.add_argument("--parent-handle")
    draft_declare_object_change.add_argument("--new-name")
    draft_declare_object_change.add_argument("--notes")
    draft_declare_object_change.add_argument(
        "--name-conflict",
        choices=("fail", "rename"),
    )
    add_source = draft_declare_object_change.add_mutually_exclusive_group()
    add_source.add_argument(
        "--add-to-source-control",
        dest="add_to_source_control",
        action="store_true",
    )
    add_source.add_argument(
        "--no-add-to-source-control",
        dest="add_to_source_control",
        action="store_false",
    )
    check_out_change = draft_declare_object_change.add_mutually_exclusive_group()
    check_out_change.add_argument(
        "--check-out-from-source-control",
        dest="check_out_from_source_control",
        action="store_true",
    )
    check_out_change.add_argument(
        "--no-check-out-from-source-control",
        dest="check_out_from_source_control",
        action="store_false",
    )
    draft_declare_object_change.set_defaults(
        add_to_source_control=None,
        check_out_from_source_control=None,
    )

    draft_declare_switch_assignment = subparsers.add_parser(
        "draft-declare-switch-assignment",
        help=(
            "Declare one Switch Container child and Switch/State value "
            "relationship using only live-bound object handles"
        ),
    )
    _add_business_draft_binding_arguments(
        draft_declare_switch_assignment
    )
    draft_declare_switch_assignment.add_argument(
        "--switch-container-handle",
        required=True,
    )
    draft_declare_switch_assignment.add_argument(
        "--child-handle",
        required=True,
    )
    draft_declare_switch_assignment.add_argument(
        "--state-or-switch-handle",
        required=True,
    )

    draft_declare_soundbank_plan = subparsers.add_parser(
        "draft-declare-soundbank-plan",
        help=(
            "Declare one complete high-level SoundBank plan using bound "
            "objects, stable business choices, and exact caller artifacts"
        ),
    )
    _add_business_draft_binding_arguments(draft_declare_soundbank_plan)
    add_soundbank_plan_arguments(draft_declare_soundbank_plan)

    draft_declare_artifact_plan = subparsers.add_parser(
        "draft-declare-artifact-plan",
        help=(
            "Declare one complete tabular or Lua artifact plan while the "
            "Gateway owns native loader fields and source authority"
        ),
    )
    _add_business_draft_binding_arguments(draft_declare_artifact_plan)
    add_exact_artifact_plan_arguments(draft_declare_artifact_plan)

    draft_declare_ui_plan = subparsers.add_parser(
        "draft-declare-ui-plan",
        help=(
            "Declare one closed Authoring UI capture, execute, register header, "
            "or unregister business plan"
        ),
    )
    _add_business_draft_binding_arguments(draft_declare_ui_plan)
    add_authoring_ui_plan_arguments(draft_declare_ui_plan)

    draft_add_ui_command = subparsers.add_parser(
        "draft-add-ui-command",
        help=(
            "Append the next complete high-level command descriptor to a "
            "count-bound Authoring UI registration plan"
        ),
    )
    _add_business_draft_binding_arguments(draft_add_ui_command)
    add_authoring_ui_command_arguments(draft_add_ui_command)

    draft_declare_debug_intent = subparsers.add_parser(
        "draft-declare-debug-intent",
        help=(
            "Declare one stable Debug mode outcome or one zero-value "
            "deliberate host-control intent"
        ),
    )
    _add_business_draft_binding_arguments(draft_declare_debug_intent)
    add_debug_intent_arguments(draft_declare_debug_intent)

    draft_declare_undo_plan = subparsers.add_parser(
        "draft-declare-undo-plan",
        help=(
            "Declare one display name and an ordered list of checked child "
            "Business Draft snapshots"
        ),
    )
    _add_business_draft_binding_arguments(draft_declare_undo_plan)
    draft_declare_undo_plan.add_argument("--display-name", required=True)
    draft_declare_undo_plan.add_argument(
        "--child-draft",
        action="append",
        nargs=2,
        required=True,
        metavar=("DRAFT_ID", "TASK_AUTHORITY"),
    )

    draft_declare_field_change = subparsers.add_parser(
        "draft-declare-field-change",
        help=(
            "Declare one bound property, reference, or platform-link business "
            "outcome without naming its native Wwise token"
        ),
    )
    _add_business_draft_binding_arguments(draft_declare_field_change)
    draft_declare_field_change.add_argument("--object-handle", required=True)
    draft_declare_field_change.add_argument("--field-handle", required=True)
    outcome = draft_declare_field_change.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--business-value")
    outcome.add_argument("--target-handle")
    outcome.add_argument("--clear-reference", action="store_true")
    outcome.add_argument("--link-state", choices=("linked", "unlinked"))

    draft_declare_rtpc = subparsers.add_parser(
        "draft-declare-rtpc",
        help=(
            "Declare one bound RTPC property, Control Input, and ordered "
            "business curve"
        ),
    )
    _add_business_draft_binding_arguments(draft_declare_rtpc)
    draft_declare_rtpc.add_argument("--object-handle", required=True)
    draft_declare_rtpc.add_argument("--field-handle", required=True)
    draft_declare_rtpc.add_argument("--control-input-handle", required=True)
    draft_declare_rtpc.add_argument(
        "--point",
        action="append",
        nargs=3,
        required=True,
        metavar=("X", "Y", "WWISE_SHAPE"),
    )
    draft_declare_rtpc.add_argument(
        "--mode",
        choices=("add-only", "add-or-update"),
        default="add-or-update",
    )
    draft_declare_rtpc.add_argument("--notes")

    draft_declare_new = subparsers.add_parser(
        "draft-declare-new",
        help="Declare one new Wwise descendant using only high-level business facts",
    )
    _add_business_declaration_arguments(draft_declare_new)
    draft_declare_new.add_argument("--parent-handle", required=True)
    draft_declare_new.add_argument("--name", required=True)
    draft_declare_new.add_argument("--kind", required=True)

    draft_declare_existing = subparsers.add_parser(
        "draft-declare-existing",
        help="Declare one change to an exact bound existing Wwise object",
    )
    _add_business_declaration_arguments(draft_declare_existing)
    draft_declare_existing.add_argument("--object-handle", required=True)

    draft_add_media = subparsers.add_parser(
        "draft-add-media",
        help=(
            "Append one exact media artifact to an existing high-level object.set "
            "declaration without accepting a native import fragment"
        ),
    )
    _add_business_draft_binding_arguments(draft_add_media)
    draft_add_media.add_argument("--declaration-id", required=True)
    media_source = draft_add_media.add_mutually_exclusive_group(required=True)
    media_source.add_argument("--media-file")
    media_source.add_argument("--inline-wav")
    draft_add_media.add_argument("--kind")
    draft_add_media.add_argument("--language")
    draft_add_media.add_argument("--originals-subfolder")

    draft_clear_object_list = subparsers.add_parser(
        "draft-clear-object-list",
        help=(
            "Declare one exact Wwise object-list clear through a bound owner "
            "without accepting an empty native list row"
        ),
    )
    _add_business_draft_binding_arguments(draft_clear_object_list)
    draft_clear_object_list.add_argument("--declaration-id", required=True)
    draft_clear_object_list.add_argument("--object-handle", required=True)
    draft_clear_object_list.add_argument("--list-name", required=True)

    draft_revise_declaration = subparsers.add_parser(
        "draft-revise-declaration",
        help="Replace the complete high-level field set of one declaration",
    )
    _add_business_declaration_arguments(draft_revise_declaration)

    draft_remove_declaration = subparsers.add_parser(
        "draft-remove-declaration",
        help="Remove one high-level declaration from an editable Draft",
    )
    _add_business_draft_binding_arguments(draft_remove_declaration)
    draft_remove_declaration.add_argument("--declaration-id", required=True)

    draft_bind_object = subparsers.add_parser(
        "draft-bind-object",
        help="Resolve one exact live Wwise object into a task-local opaque handle",
    )
    _add_business_draft_binding_arguments(draft_bind_object)
    object_selector = draft_bind_object.add_mutually_exclusive_group(required=True)
    object_selector.add_argument("--object-id")
    object_selector.add_argument("--object-path")
    object_selector.add_argument("--object-path-segment", action="append")
    object_selector.add_argument(
        "--exact-type-name",
        nargs=2,
        metavar=("TYPE", "NAME"),
    )
    draft_bind_object.add_argument("--role")

    draft_bind_field = subparsers.add_parser(
        "draft-bind-field",
        help="Bind one exact live property or reference into an opaque typed handle",
    )
    _add_business_draft_binding_arguments(draft_bind_field)
    field_scope = draft_bind_field.add_mutually_exclusive_group(required=True)
    field_scope.add_argument("--object-handle")
    field_scope.add_argument("--class-name")
    draft_bind_field.add_argument("--token", required=True)
    draft_bind_field.add_argument("--platform")

    draft_discover_fields = subparsers.add_parser(
        "draft-discover-fields",
        help=(
            "Resolve user-facing field meaning into bounded live candidate handles"
        ),
    )
    _add_business_draft_binding_arguments(draft_discover_fields)
    discovery_scope = draft_discover_fields.add_mutually_exclusive_group(
        required=True
    )
    discovery_scope.add_argument("--object-handle")
    discovery_scope.add_argument("--type-handle")
    discovery_scope.add_argument("--semantic-kind")
    draft_discover_fields.add_argument(
        "--meaning",
        action="append",
        dest="meanings",
        required=True,
        metavar="SEARCH_PHRASE",
    )
    draft_discover_fields.add_argument("--platform")

    draft_discover_types = subparsers.add_parser(
        "draft-discover-types",
        help=(
            "Resolve a user-facing object or plug-in kind into bounded live "
            "type handles"
        ),
    )
    _add_business_draft_binding_arguments(draft_discover_types)
    draft_discover_types.add_argument(
        "--meaning",
        action="append",
        dest="meanings",
        required=True,
        metavar="SEARCH_PHRASE",
    )
    draft_discover_types.add_argument(
        "--role",
        choices=("object", "source", "effect"),
        required=True,
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
        if args.command == "query-object":
            preflight_query_object_input(args, env=source_env)
        if args.command in {"wait-topic", "stream-topic"}:
            preflight_typed_topic_input(args, env=source_env)
        if args.command == "metadata":
            preflight_metadata_input(args, env=source_env)
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
        if args.command in {"debug-wal-tree", "debug-validate-call"}:
            preflight_debug_read_input(args, env=source_env)
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


def _typed_container_response_end() -> dict[str, Any]:
    """Return the final visible completeness sentinel for typed containers."""

    return {
        "contract": "waapi-skill.gateway-response-end/v1",
        "marker": "WAAPI_TYPED_CONTAINER_RESPONSE_END",
        "complete": True,
        "truncated": False,
        "agent_action": "continue_same_turn",
    }


def gateway_stdout_payload(value: Any) -> Any:
    """Return the compact public projection for one terminal stdout document."""

    if (
        not isinstance(value, Mapping)
        or value.get("contract") != "waapi-skill.typed-container-handle/v1"
    ):
        return value
    compact_recursive_object = value.get("uri") == "object.create"
    compact_recursive_audit_fields = (
        {"schema_digest", "parent_handle", "key", "shape"}
        if compact_recursive_object
        else set()
    )
    projected = {
        key: item
        for key, item in value.items()
        if key
        not in (
            {
                "business_value_scope",
                "schema_lineage_authority",
                "construction_state",
                "session_context",
                "child_contract",
                "continuation",
                "response_integrity",
            }
            | compact_recursive_audit_fields
        )
    }
    projected["response_integrity"] = {
        "complete": True,
        "truncated": False,
    }
    raw_child_contract = value.get("child_contract")
    projected_child_contract: dict[str, Any] | None = None
    if isinstance(raw_child_contract, Mapping):
        projected_child_contract = {
            key: item
            for key, item in raw_child_contract.items()
            if key not in {"fact_literal_policy", "fixed_container_members"}
            and item not in (None, False, [], {})
        }
        scalar_table = projected_child_contract.get(
            "fixed_scalar_member_fact_table"
        )
        if compact_recursive_object and isinstance(scalar_table, Mapping):
            columns = scalar_table.get("columns")
            rows = scalar_table.get("rows")
            kept_columns = (
                "key",
                "required",
                "accepted_types",
            )
            if (
                isinstance(columns, list)
                and all(name in columns for name in kept_columns)
                and isinstance(rows, list)
                and all(isinstance(row, list) for row in rows)
                and isinstance(value.get("handle"), str)
            ):
                kept_indexes = [columns.index(name) for name in kept_columns]
                if all(
                    all(index < len(row) for index in kept_indexes)
                    for row in rows
                ):
                    business_pointer_index = columns.index(
                        "business_value_pointer"
                    )
                    business_pointers = [
                        row[business_pointer_index] for row in rows
                    ]
                    business_object_pointers = {
                        pointer.rsplit("/", 1)[0]
                        for pointer in business_pointers
                        if isinstance(pointer, str) and "/" in pointer
                    }
                    if len(business_object_pointers) != 1:
                        raise GatewayInputError(
                            "Recursive object scalar rows do not share one "
                            "business object pointer."
                        )
                    compact_scalar_table: dict[str, Any] = {
                        "columns": list(kept_columns),
                        "business_object_pointer": next(
                            iter(business_object_pointers)
                        ),
                        "exact_type_tokens": {
                            "Actor Mixer": "ActorMixer",
                            "Random Container": "RandomSequenceContainer",
                            "随机容器": "RandomSequenceContainer",
                            "Blend Container": "BlendContainer",
                            "混合容器": "BlendContainer",
                            "Sound": "Sound",
                            "forbidden": ["RandomContainer"],
                        },
                    }
                    compact_scalar_table["row_policy"] = (
                        "all_present_rows_in_order_skip_absent_optional"
                    )
                    compact_scalar_table.update(
                        {
                            "rows": [
                                [row[index] for index in kept_indexes]
                                for row in rows
                            ],
                            "fact_command_assembly": {
                                "fixed_argv_prefix": [
                                    "--action",
                                    "add_typed_fact",
                                    "--fact-action",
                                    "map-put",
                                    "--field-handle",
                                    value["handle"],
                                ],
                                "append_for_each_business_present_row": [
                                    "--value-type",
                                    "<selected-accepted-type>",
                                    "--fact-value",
                                    "<business-value>",
                                "--key",
                                "<row-key>",
                            ],
                            },
                        }
                    )
                    projected_child_contract[
                        "fixed_scalar_member_fact_table"
                    ] = compact_scalar_table
    raw_continuation = value.get("continuation")
    if not isinstance(raw_continuation, Mapping):
        projected["response_end"] = _typed_container_response_end()
        return projected
    raw_decision = raw_continuation.get("next_command_decision")
    raw_root_anchor = raw_continuation.get("root_fact_queue_anchor")
    raw_deferred_fact = raw_continuation.get("deferred_fact")
    include_root_anchor = isinstance(raw_root_anchor, Mapping) and (
        raw_continuation.get("subcommand") != "draft-apply"
        or not isinstance(raw_deferred_fact, Mapping)
        or raw_root_anchor.get("first_fact_argv") == raw_deferred_fact.get("argv")
    )
    continuation: dict[str, Any] = {}
    candidate_keys: list[str] = []
    if include_root_anchor:
        candidate_keys.append("root_fact_queue_anchor")
    if isinstance(raw_decision, Mapping):
        if compact_recursive_object:
            boundary = raw_decision.get("preview_construction_boundary")
            decision = {
                **(
                    {
                        "construction_boundary": {
                            key: boundary[key]
                            for key in (
                                "complete",
                                "required_terminal",
                                "same_turn_requirement",
                            )
                            if key in boundary
                        }
                    }
                    if isinstance(boundary, Mapping)
                    else {}
                ),
                **{
                    key: raw_decision[key]
                    for key in (
                        "evaluate_in_order",
                        "first_true_candidate_is_the_only_next_action",
                        "draft_check_or_cancel_with_remaining_candidate_or_deferred_fact",
                    )
                    if key in raw_decision
                },
            }
        else:
            decision = {
                key: raw_decision[key]
                for key in (
                    "preview_construction_boundary",
                    "evaluate_in_order",
                    "first_true_candidate_is_the_only_next_action",
                    "draft_check_or_cancel_with_remaining_candidate_or_deferred_fact",
                )
                if key in raw_decision
            }
        evaluate = decision.get("evaluate_in_order")
        if isinstance(evaluate, list):
            if compact_recursive_object:
                command_key_by_candidate = {
                    "branch_disclosure": "branch_disclosure",
                    "deferred_fact_queue": "deferred_fact",
                    "nested_container_disclosures": (
                        "nested_container_disclosures"
                    ),
                    "next_item_disclosure": "next_item_disclosure",
                    "business_sibling_transition": (
                        "business_sibling_transition"
                    ),
                }
                compact_evaluate: list[dict[str, Any]] = []
                for row in evaluate:
                    if not isinstance(row, Mapping):
                        continue
                    candidate = row.get("candidate")
                    if not isinstance(candidate, str) or candidate not in (
                        command_key_by_candidate
                    ):
                        continue
                    compact_row: dict[str, Any] = {
                        "candidate": candidate,
                        "command_key": command_key_by_candidate[candidate],
                    }
                    if "after_success" in row:
                        compact_row["after_success"] = (
                            "re_evaluate_same_response"
                        )
                    compact_evaluate.append(compact_row)
                decision["evaluate_in_order"] = compact_evaluate
            else:
                decision["evaluate_in_order"] = list(evaluate)
            candidate_key_by_name = {
                "branch_disclosure": "branch_disclosure",
                "nested_container_disclosures": "nested_container_disclosures",
                "next_item_disclosure": "next_item_disclosure",
                "business_sibling_transition": "business_sibling_transition",
                "deferred_fact_queue": "deferred_fact",
            }
            for row in decision["evaluate_in_order"]:
                if not isinstance(row, Mapping):
                    continue
                name = row.get("candidate")
                if not isinstance(name, str) or name not in candidate_key_by_name:
                    continue
                if row.get("first_command_pointer") == (
                    "/continuation/root_fact_queue_anchor/first_fact_argv"
                ):
                    candidate_keys.append("root_fact_queue_anchor")
                candidate_keys.append(candidate_key_by_name[name])
        continuation["next_command_decision"] = decision
    for key in candidate_keys:
        if key in raw_continuation and key not in continuation:
            item = raw_continuation[key]
            if (
                key == "deferred_fact"
                and raw_continuation.get("subcommand") == "draft-apply"
                and not include_root_anchor
                and isinstance(item, Mapping)
            ):
                item = {
                    **item,
                    "complete_command_assembly": {
                        "fixed_argv_prefix_source": (
                            "latest_draft_response.next_action_binding."
                            "fixed_argv_prefix"
                        ),
                        "append_this_fact_argv_exactly": True,
                    },
                }
            if compact_recursive_object and key == "deferred_fact" and isinstance(
                item, Mapping
            ):
                item = {
                    candidate: item[candidate]
                    for candidate in (
                        "argv",
                        "complete_command_assembly",
                        "must_precede",
                        "consume_once",
                    )
                    if candidate in item
                }
            if (
                compact_recursive_object
                and key == "business_sibling_transition"
                and isinstance(item, Mapping)
            ):
                compact_candidates = (
                    ("copy_command_by_shape",)
                    if "copy_command_by_shape" in item
                    else ("argv_by_shape",)
                )
                item = {
                    candidate: item[candidate]
                    for candidate in compact_candidates
                    if candidate in item
                }
                if isinstance(
                    raw_continuation[key].get("when_absent"), Mapping
                ):
                    item["when_absent"] = "nearest_ancestor_business_sibling"
            if (
                compact_recursive_object
                and key == "nested_container_disclosures"
                and isinstance(item, list)
                and item
                and all(isinstance(row, Mapping) for row in item)
            ):
                argv_rows = [row.get("argv") for row in item]
                if (
                    all(
                        isinstance(argv, list)
                        and len(argv) >= 10
                        and all(isinstance(token, str) for token in argv)
                        for argv in argv_rows
                    )
                    and all(argv[:4] == argv_rows[0][:4] for argv in argv_rows)
                    and all(argv[-2:] == argv_rows[0][-2:] for argv in argv_rows)
                    and all(
                        argv[4:-2]
                        == [
                            "--key",
                            row.get("key"),
                            "--shape",
                            row.get("shape"),
                        ]
                        for row, argv in zip(item, argv_rows, strict=True)
                    )
                ):
                    nested_object_pointers = {
                        str(row.get("business_value_pointer")).rsplit("/", 1)[0]
                        for row in item
                        if isinstance(row.get("business_value_pointer"), str)
                        and "/" in str(row.get("business_value_pointer"))
                    }
                    if len(nested_object_pointers) != 1:
                        raise GatewayInputError(
                            "Recursive object container rows do not share one "
                            "business object pointer."
                        )
                    item = {
                        "business_object_pointer": next(
                            iter(nested_object_pointers)
                        ),
                        "selection": (
                            "first_row_with_present_business_value_pointer_"
                            "in_queue_order"
                        ),
                        "absent_business_values": (
                            "skip_without_gateway_command"
                        ),
                        "allowed_members": [row.get("key") for row in item],
                        "shape": "array",
                        "argv_template": [
                            *argv_rows[0][:4],
                            "--key",
                            "<selected-business-member>",
                            "--shape",
                            "array",
                            *argv_rows[0][-2:],
                        ],
                        "replace_only": ["<selected-business-member>"],
                    }
            continuation[key] = item
    for key, item in raw_continuation.items():
        if key in {
            "draft_fact_execution",
            "nested_container_order",
            "next_business_present_nested_disclosure",
            "next_command_decision",
            "request_wide_order",
        } or key in continuation or (
            key == "root_fact_queue_anchor" and not include_root_anchor
        ):
            continue
        continuation[key] = item
    # Recursive-object compaction intentionally rewrites several verbose
    # continuation rows.  Re-derive the exact model-facing command only after
    # that rewrite so a concrete public argv can never lose its copy authority.
    projected["continuation"] = _dynamic_disclosure_copy_commands(continuation)
    if projected_child_contract is not None:
        projected["child_contract"] = projected_child_contract
    projected["response_end"] = _typed_container_response_end()
    return projected


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

    if isinstance(exc, BusinessDeclarationError):
        return {
            "error_code": exc.error_code,
            "message": exc.error_code,
            "details": {"repair": dict(exc.repair)},
        }
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


def command_line_host_required_payload(
    *,
    command: str,
    live_info: Mapping[str, Any],
    common: Mapping[str, Any] | None = None,
    operation: str,
) -> dict[str, Any]:
    """Return the closed boundary for Console-only operations."""

    payload: dict[str, Any] = {
        "contract": GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "command_line_host_required",
        "command": command,
        "error_code": "COMMAND_LINE_HOST_REQUIRED",
        "message": (
            "This operation requires WwiseConsole; Wwise Authoring cannot "
            "preview or execute it."
        ),
        "details": {
            "is_command_line": live_info.get("isCommandLine"),
            "required_host": "wwise-console",
        },
        "operation": operation,
        "executed": False,
        "verified": False,
    }
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
    if operation == "lua.executeCliFile" and live_info.get("isCommandLine") is not True:
        return command_line_host_required_payload(
            command=command,
            live_info=live_info,
            common=common,
            operation=operation,
        )
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
    capability = CapabilityCatalog().describe(versions[0], args.api)
    if (
        capability.preferred_route == "fixed_command"
        and "typed-call" not in capability.fixed_commands
    ):
        raise GatewayInputError(
            f"{args.api} uses its Gateway-owned fixed command: "
            f"{', '.join(capability.fixed_commands)}"
        )
    contract = request_contract(versions[0], args.api)
    if contract.as_gateway_payload()["input_shape"] == "draft":
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
            f"{dedicated_zero} and its Gateway-owned business Draft as its single entry."
        )
    if contract.schema_digest != args.schema_digest:
        raise GatewayInputError("Typed request schema digest is stale")
    if contract.fields:
        raise GatewayInputError("typed-zero-call is available only for zero-input schemas")
    execution = {
        "effect": contract.effect,
        "route": contract.route,
    }
    if contract.route == "fixed_command":
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


def _query_kind_predicates(
    name: str,
    *,
    version: str,
) -> tuple[tuple[str, str, str, str], ...]:
    """Compile one closed query kind into exact native type discriminators."""

    fixed_type = QUERY_FIXED_KIND_TYPES.get(name)
    if fixed_type is not None:
        return (("type", "=", "string", fixed_type),)
    kind = resolve_semantic_kind(name, version=version)
    native_type = (
        "Sound" if name in {"sound-sfx", "sound-voice"} else kind.native_object_type
    )
    predicates: list[tuple[str, str, str, str]] = [
        ("type", "=", "string", native_type)
    ]
    if name in {"sound-sfx", "sound-voice"}:
        predicates.append(
            (
                "@IsVoice",
                "=",
                "boolean",
                "true" if name == "sound-voice" else "false",
            )
        )
    return tuple(predicates)


def preflight_query_object_input(args: argparse.Namespace, *, env: Mapping[str, str]) -> None:
    """Reject closed query input errors before opening a WAAPI transport."""

    _compile_query_business_projection(args)
    args.where = []
    args.select = [
        QUERY_BUSINESS_RELATIONSHIPS[value]
        for value in getattr(args, "relationships", ()) or ()
    ]
    if getattr(args, "path_segments", None):
        args.path = _business_object_path_from_segments(args.path_segments)
    if getattr(args, "query_id", None):
        args.query = args.query_id
    if getattr(args, "query_path_segments", None):
        args.query = _business_object_path_from_segments(
            ["Queries", *args.query_path_segments]
        )
    if getattr(args, "semantic_kind", None):
        (kind_version,) = resolve_catalog_versions(args, env=env)
        kind_predicates = _query_kind_predicates(
            args.semantic_kind,
            version=kind_version,
        )
        args.object_type = kind_predicates[0][3]
        args.where.extend(kind_predicates[1:])
    custom_kind_meaning = getattr(args, "custom_kind_meaning", None)
    if custom_kind_meaning is not None and (
        not isinstance(custom_kind_meaning, str)
        or not custom_kind_meaning
        or custom_kind_meaning != custom_kind_meaning.strip()
        or len(custom_kind_meaning) > MAX_METADATA_DISCOVERY_NAME_CHARS
    ):
        raise GatewayInputError(
            "--custom-kind must be one bounded, trimmed user-facing type meaning"
        )
    for intent, value in getattr(args, "business_predicates", ()):
        if intent == QUERY_BUSINESS_KIND_PREDICATE:
            (kind_version,) = resolve_catalog_versions(args, env=env)
            if value not in QUERY_BUSINESS_KINDS:
                raise GatewayInputError(
                    "--predicate kind-is must use one disclosed business kind"
                )
            args.where.extend(_query_kind_predicates(value, version=kind_version))
            continue
        native = QUERY_BUSINESS_PREDICATES.get(intent)
        if native is None:
            raise GatewayInputError(
                "--predicate BUSINESS_CONDITION must be one of: "
                + ", ".join(sorted(QUERY_BUSINESS_PREDICATES))
            )
        field, operator, value_type = native
        args.where.append((field, operator, value_type, value))
    if getattr(args, "advanced_waql", None) is not None:
        if args.custom_field_meanings:
            raise GatewayInputError(
                "--advanced-waql does not accept --include-field because an exact "
                "live metadata scope cannot be derived; use a scoped business query"
            )
        if args.business_predicates or args.relationships:
            raise GatewayInputError(
                "--advanced-waql cannot be combined with --predicate or "
                "--relationship"
            )
        if args.max_results is None:
            raise GatewayInputError(
                "--advanced-waql requires --max-results"
            )
        (advanced_version,) = resolve_catalog_versions(args, env=env)
        args.advanced_query_preview = build_advanced_object_get_query(
            {
                "contract": ADVANCED_QUERY_CONTRACT,
                "waql": args.advanced_waql,
                "return": list(args.query_return_fields),
                "max_results": args.max_results,
            },
            version=advanced_version,
        )
        return

    if args.query_custom_field_meanings:
        exact_object_scope = args.path is not None or args.object_id is not None
        type_scope = (
            args.object_type is not None or custom_kind_meaning is not None
        )
        if args.select:
            raise GatewayInputError(
                "--include-field cannot be combined with --relationship because "
                "the post-traversal result type is not one exact metadata scope; "
                "use a closed --include business field"
            )
        if not (type_scope or exact_object_scope):
            raise GatewayInputError(
                "--include-field requires a --kind/--custom-kind source or one exact "
                "path/GUID source so the Gateway can "
                "bind one live metadata scope"
            )

    args.take = args.max_results
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
            custom_kind_meaning is not None,
        )
    ):
        raise GatewayInputError(
            "query-object requires one business source or --advanced-waql"
        )

    if custom_kind_meaning is None:
        where = typed_query_predicates(args)
        return_fields = args.query_return_fields
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


def _compile_query_business_projection(args: argparse.Namespace) -> None:
    """Compile stable business output names into exact object.get accessors."""

    requested = list(getattr(args, "business_outputs", ()) or ())
    custom_meanings = list(getattr(args, "custom_field_meanings", ()) or ())
    if len(requested) > MAX_QUERY_BUSINESS_OUTPUTS:
        raise GatewayInputError(
            f"query-object accepts at most {MAX_QUERY_BUSINESS_OUTPUTS} --include values"
        )
    if len(custom_meanings) > MAX_QUERY_CUSTOM_OUTPUTS:
        raise GatewayInputError(
            "query-object accepts at most "
            f"{MAX_QUERY_CUSTOM_OUTPUTS} custom field meanings"
        )
    if len(set(requested)) != len(requested):
        raise GatewayInputError("query-object --include values must be unique")

    bindings: list[tuple[str, str, str]] = []
    for name in requested:
        native, output = QUERY_BUSINESS_OUTPUTS[name]
        bindings.append(("business", native, output))

    def bounded_custom_meaning(value: Any) -> str:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > MAX_QUERY_CUSTOM_FIELD_CHARS
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or any(character in value for character in ('"', "'", "\\", ";"))
        ):
            raise GatewayInputError(
                "--include-field must be one bounded user-facing field meaning"
            )
        return value

    normalized_meanings = [bounded_custom_meaning(value) for value in custom_meanings]
    if len({" ".join(value.split()).casefold() for value in normalized_meanings}) != len(
        normalized_meanings
    ):
        raise GatewayInputError("query-object --include-field meanings must be unique")
    args.query_custom_field_meanings = tuple(normalized_meanings)

    native_fields = [binding[1] for binding in bindings]
    if len(set(native_fields)) != len(native_fields):
        raise GatewayInputError(
            "query-object requested the same native result field more than once"
        )
    args.query_output_bindings = tuple(bindings)
    args.query_return_fields = (
        *SELECTED_REQUIRED_RETURN_FIELDS,
        *native_fields,
    )


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
    if any(
        (
            args.path is not None,
            args.object_id is not None,
            args.object_type is not None,
            getattr(args, "custom_kind_meaning", None) is not None,
            args.search is not None,
            args.query is not None,
        )
    ):
        raise GatewayInputError(
            "--match-original-file-path owns its Audio File Source query and "
            "cannot be combined with another query source"
        )
    if args.where:
        raise GatewayInputError(
            "--match-original-file-path cannot be combined with --where"
        )
    if args.select:
        raise GatewayInputError(
            "--match-original-file-path cannot be combined with --relationship"
        )
    if args.all_results:
        raise GatewayInputError(
            "--match-original-file-path cannot be combined with --all-results"
        )
    if args.max_results != MAX_QUERY_TAKE:
        raise GatewayInputError(
            "--match-original-file-path requires exactly "
            f"--max-results {MAX_QUERY_TAKE}"
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


def preflight_metadata_input(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> None:
    """Compile business metadata scope and meaning into fixed live reads."""

    path_segments = getattr(args, "metadata_path_segments", None)
    semantic_kind = getattr(args, "metadata_semantic_kind", None)
    custom_kind_meaning = getattr(args, "metadata_custom_kind_meaning", None)
    exact_id = getattr(args, "metadata_exact_id", None)
    meanings = list(getattr(args, "metadata_meanings", None) or ())
    if path_segments:
        args.object = _business_object_path_from_segments(path_segments)
    if semantic_kind is not None:
        (version,) = resolve_catalog_versions(args, env=env)
        if semantic_kind in QUERY_FIXED_KIND_TYPES:
            args.object_type = QUERY_FIXED_KIND_TYPES[semantic_kind]
        else:
            args.object_type = resolve_semantic_kind(
                semantic_kind,
                version=version,
            ).metadata_object_type
    if custom_kind_meaning is not None and (
        not isinstance(custom_kind_meaning, str)
        or not custom_kind_meaning
        or custom_kind_meaning != custom_kind_meaning.strip()
        or len(custom_kind_meaning) > MAX_METADATA_DISCOVERY_NAME_CHARS
    ):
        raise GatewayInputError(
            "metadata --custom-kind must be one bounded, trimmed user-facing meaning"
        )
    if exact_id is not None:
        if not _canonical_guid(exact_id):
            raise GatewayInputError("metadata --exact-id must be a canonical GUID")
        args.object = exact_id
    args.queries = meanings or None
    args.limit = DEFAULT_METADATA_DISCOVERY_LIMIT
    args.detail = False

    if args.operation == "types":
        if (
            path_segments
            or semantic_kind is not None
            or custom_kind_meaning is not None
            or exact_id is not None
            or meanings
            or args.platform
            or args.curve_role
        ):
            raise GatewayInputError("metadata types accepts no business input")
        return

    if args.operation in {"discover", "property-state"}:
        if not 1 <= len(meanings) <= MAX_METADATA_DISCOVERY_QUERIES:
            raise GatewayInputError(
                f"metadata {args.operation} requires 1.."
                f"{MAX_METADATA_DISCOVERY_QUERIES} --meaning values"
            )
        total_chars = 0
        seen: set[str] = set()
        for meaning in meanings:
            if (
                not isinstance(meaning, str)
                or not meaning.strip()
                or meaning != meaning.strip()
                or len(meaning) > MAX_METADATA_DISCOVERY_QUERY_CHARS
            ):
                raise GatewayInputError(
                    "each metadata --meaning must be non-empty, trimmed, and "
                    f"contain at most {MAX_METADATA_DISCOVERY_QUERY_CHARS} characters"
                )
            total_chars += len(meaning)
            folded = " ".join(meaning.split()).casefold()
            if folded in seen:
                raise GatewayInputError("metadata --meaning values must be distinct")
            seen.add(folded)
        if total_chars > MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS:
            raise GatewayInputError(
                "metadata meaning text exceeds the combined "
                f"{MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS}-character limit"
            )

    if args.operation == "discover":
        if sum(
            value is not None
            for value in (path_segments, semantic_kind, custom_kind_meaning, exact_id)
        ) != 1:
            raise GatewayInputError(
                "metadata discover requires exactly one --path-segment, --kind, "
                "--custom-kind, or --exact-id scope"
            )
        if args.platform is not None or args.curve_role is not None:
            raise GatewayInputError(
                "metadata discover does not accept --platform or --curve-role"
            )
        return

    if args.operation == "property-state":
        if (
            (path_segments is None) == (exact_id is None)
            or semantic_kind is not None
            or custom_kind_meaning is not None
        ):
            raise GatewayInputError(
                "metadata property-state requires one object --path-segment or "
                "--exact-id scope"
            )
        if len(meanings) != 1:
            raise GatewayInputError(
                "metadata property-state requires exactly one --meaning"
            )
        if not isinstance(args.platform, str) or not args.platform.strip():
            raise GatewayInputError(
                "metadata property-state requires one non-empty --platform name"
            )
        if args.curve_role is not None:
            raise GatewayInputError(
                "metadata property-state does not accept --curve-role"
            )
        return

    if args.operation == "attenuation":
        if (
            (path_segments is None) == (exact_id is None)
            or semantic_kind is not None
            or custom_kind_meaning is not None
        ):
            raise GatewayInputError(
                "metadata attenuation requires one object --path-segment or "
                "--exact-id scope"
            )
        if meanings:
            raise GatewayInputError("metadata attenuation does not accept --meaning")
        if args.curve_role not in METADATA_CURVE_ROLES:
            raise GatewayInputError(
                "metadata attenuation requires one disclosed --curve-role"
            )
        args.curve_type = METADATA_CURVE_ROLES[args.curve_role]
        return

    raise GatewayInputError(f"unsupported metadata operation: {args.operation}")


def preflight_stable_read_input(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> None:
    """Compile profiler capture and object intent before opening WAAPI."""

    (version,) = resolve_catalog_versions(args, env=env)
    capture = getattr(args, "capture", None)
    capture_ms = getattr(args, "capture_ms", None)
    args.time = (
        "capture"
        if capture == "latest"
        else "user"
        if capture == "user-cursor"
        else capture_ms
    )
    if args.command == "profiler-game-objects":
        build_profiler_game_objects_request(
            version=version,
            time=args.time,
        )
        return
    if not _canonical_guid(args.voice_object_id):
        raise GatewayInputError(
            "profiler-voice-contributions --voice-object-id must be a canonical GUID"
        )
    bus_object_ids = tuple(args.bus_object_id)
    if len(bus_object_ids) > MAX_BUS_PIPELINE_IDS:
        raise GatewayInputError(
            "profiler-voice-contributions accepts at most "
            f"{MAX_BUS_PIPELINE_IDS} --bus-object-id values"
        )
    if (
        any(not _canonical_guid(value) for value in bus_object_ids)
        or len({value.casefold() for value in bus_object_ids}) != len(bus_object_ids)
    ):
        raise GatewayInputError(
            "profiler-voice-contributions --bus-object-id values must be unique "
            "canonical GUIDs"
        )
    if args.game_object_id is not None:
        if re.fullmatch(r"[0-9]+", args.game_object_id) is None:
            raise GatewayInputError(
                "profiler-voice-contributions --game-object-id must be an "
                "unsigned 64-bit integer"
            )
        game_object_id = int(args.game_object_id)
        if not 0 <= game_object_id <= (1 << 64) - 1:
            raise GatewayInputError(
                "profiler-voice-contributions --game-object-id must be an "
                "unsigned 64-bit integer"
            )
        args.game_object_id = game_object_id
    # Validate the shared capture value now; pipeline IDs are derived from the
    # bounded getVoices/getBusses reads after connection.
    args.time = normalize_profiler_time(args.time)


def preflight_debug_read_input(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> None:
    """Reject fixed debug-read scalar boundaries before opening WAAPI."""

    if args.command == "debug-wal-tree":
        if (
            isinstance(args.max_nodes, bool)
            or not isinstance(args.max_nodes, int)
            or not 1 <= args.max_nodes <= MAX_WAL_TREE_NODES
        ):
            raise GatewayInputError(
                "debug-wal-tree --max-nodes must be between 1 and "
                f"{MAX_WAL_TREE_NODES}"
            )
        return
    if args.command != "debug-validate-call":
        raise GatewayInputError(f"unsupported debug-read command: {args.command}")

    (version,) = resolve_catalog_versions(args, env=env)
    try:
        target = CapabilityCatalog().describe(version, args.api)
    except CapabilityNotFoundError as exc:
        raise GatewayInputError(
            f"debug-validate-call target is not reflected in Wwise {version}: {args.api}"
        ) from exc
    if target.item_type != "function":
        raise GatewayInputError("debug-validate-call target must be a WAAPI function")

    call_args: dict[str, Any] = {"id": target.uri}
    if args.artifact_file is not None:
        artifact = Path(args.artifact_file).expanduser()
        if not artifact.is_absolute():
            raise GatewayInputError(
                "debug-validate-call --artifact-file must be an absolute path"
            )
        try:
            artifact_stat = artifact.lstat()
        except OSError as exc:
            raise GatewayInputError(
                "debug-validate-call --artifact-file must exist"
            ) from exc
        if stat.S_ISLNK(artifact_stat.st_mode) or not stat.S_ISREG(artifact_stat.st_mode):
            raise GatewayInputError(
                "debug-validate-call --artifact-file must be a regular non-symlink file"
            )
        if artifact_stat.st_size > MAX_GATEWAY_JSON_INPUT_BYTES:
            raise GatewayInputError(
                "debug-validate-call --artifact-file exceeds the "
                f"{MAX_GATEWAY_JSON_INPUT_BYTES}-byte input limit"
            )
        try:
            text = artifact.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise GatewayInputError(
                "debug-validate-call --artifact-file must be readable UTF-8"
            ) from exc
        envelope = parse_json_object(text, "--artifact-file")
        unknown = sorted(set(envelope) - {"args", "options", "result"})
        if unknown:
            raise GatewayInputError(
                "debug-validate-call --artifact-file accepts only args, options, "
                f"and result objects; unknown keys: {', '.join(unknown)}"
            )
        for section, value in envelope.items():
            if not isinstance(value, dict):
                raise GatewayInputError(
                    f"debug-validate-call artifact {section} must be a JSON object"
                )
            call_args[section] = value
        args.artifact_digest = canonical_sha256(envelope)
        args.artifact_file = str(artifact)
    else:
        args.artifact_digest = None
    args.debug_validation_args = call_args


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
        # The authorized Draft binding decides the operation-local typed
        # Composer grammar. Dispatch performs that state-bound decision before
        # parsing any action facts.
        return


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
    modes = (
        {operation_input_mode(spec.name, version)}
        if version is not None and version in spec.supported_versions
        else {
            operation_input_mode(spec.name, supported_version)
            for supported_version in spec.supported_versions
        }
    )
    if modes != {BUSINESS_DECLARATION_INPUT_MODE}:
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
    if isinstance(start_preconditions, Mapping):
        exact_preconditions = dict(start_preconditions)
        if exact_preconditions.get("dynamic_metadata_before_draft_start") is True:
            exact_preconditions["next_step_decision"] = (
                "metadata discover when required; otherwise draft-start"
            )
            contract = {**contract, "start_preconditions": exact_preconditions}
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
            exact_preconditions = dict(contract["start_preconditions"])
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
                    "<derived-from-query-count>",
                ],
                "replace_only": ["<requested-field-name>"],
                "query_policy": {
                    "include_only_requested_dynamic_property_or_reference_tokens": True,
                    "known_target_fields_are_not_queries": [
                        "name",
                        "notes",
                        "platform",
                        "list_mode",
                        "on_name_conflict",
                    ],
                },
                "limit_by_query_count": metadata_candidate_limit_contract(),
            }
            contract = {**contract, "start_preconditions": exact_preconditions}
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
        **{
            operation_name: generic_typed_action_argv
            for operation_name in DRAFT_TYPED_OPERATIONS
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
            else {}
        ),
        "scalar_types": ["string", "number", "integer", "boolean"],
        **(
            {
                "scalar_type_discipline": {
                    "cli_type_source": "scalar_types",
                    "metadata_type_tokens_as_cli_types": "invalid",
                    "metadata_examples": {"Real64": "number", "int16": "integer"},
                }
            }
            if operation in {"audio.import", "object.set"}
            else {}
        ),
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
            "batch_fill": {
                "mode": "greedy_schema_order",
                "rule": (
                    "append the next complete handle-independent action while it "
                    "fits; execute a shorter batch only when the next action "
                    "depends on a returned handle or no action remains"
                ),
                "split_one_complete_action": "forbidden",
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
    public_contract = {
        key: value
        for key, value in contract.items()
        if key != "start_preconditions"
    }
    has_start_preconditions = "start_preconditions" in contract
    lock_draft_start = has_start_preconditions and operation in {
        "audio.import",
        "object.set",
    }
    start: dict[str, Any] = {}
    if has_start_preconditions:
        start["preconditions"] = dict(contract["start_preconditions"])
    subcommand_key = (
        "subcommand_after_preconditions" if lock_draft_start else "subcommand"
    )
    gateway_argv_key = (
        "gateway_argv_after_preconditions" if lock_draft_start else "gateway_argv"
    )
    start[subcommand_key] = "draft-start"
    start[gateway_argv_key] = ["draft-start", operation]
    if not has_start_preconditions:
        start["copy_instruction"] = {
            "contract": OPERATION_DRAFT_COMMAND_COPY_INSTRUCTION_CONTRACT,
            "source_field": "gateway_argv",
            "action": "append_to_packaged_gateway_prefix_and_execute_verbatim",
            "forbidden_transformations": [
                "reconstruct",
                "shorten",
                "normalize",
                "substitute_path_segments",
                "select_another_field",
            ],
        }
        start["precondition_discipline"] = {
            "metadata_discover_allowed_only_when": (
                "preconditions is present and selects metadata"
            ),
            "when_preconditions_absent": "execute_gateway_argv_now",
            "infer_metadata_from_operation_constraints": False,
        }
    return {
        "start": start,
        **public_contract,
        "dynamic_container_commands": {
            "map_value": "request-map-container",
            "array_item": "request-array-item",
            "schema_digest": contract.get("typed_request_schema_digest"),
            **typed_container_command_contract(
                operation,
                str(contract.get("typed_request_schema_digest")),
            ),
            "draft_binding": False,
            "scalar_map_entry_action": (
                "use draft-apply add_typed_fact with fact-action map-put directly; "
                "request-map-container is only for an object or array value"
            ),
            "sequence": (
                "root argv is only for top-level handles; returned children use the "
                "matching nested argv unchanged; then append/map-put that child; "
                "disclosure never consumes or changes the Draft revision; never "
                "mix schema digest with parent lineage; add --member-key only when "
                "branch_disclosure returns it"
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

    if api.startswith(TOPIC_OPTIONS_OPERATION_PREFIX):
        return topic_options_contract(
            version, api.removeprefix(TOPIC_OPTIONS_OPERATION_PREFIX)
        )
    if api.startswith(TOPIC_MATCH_OPERATION_PREFIX):
        return topic_match_contract(
            version, api.removeprefix(TOPIC_MATCH_OPERATION_PREFIX)
        )
    if api in DRAFT_TYPED_OPERATIONS:
        return draft_operation_request_contract(api, version)
    return request_contract(version, api)


def fixed_command_route_payload(capability: CapabilityRecord) -> dict[str, Any]:
    """Describe one deep fixed route without exposing its native request schema."""

    def command_requires_business_values(command: str) -> bool:
        return (
            command.split()[0]
            in {
            "query-object",
            "metadata",
            "profiler-game-objects",
            "profiler-voice-contributions",
            "debug-validate-call",
            }
            and command != "metadata types"
        )

    commands = [
        {
            "subcommand": command.split()[0],
            "arguments": command.split()[1:],
            "business_values_required": command_requires_business_values(command),
        }
        for command in capability.fixed_commands
    ]
    return {
        "contract": "waapi-skill.fixed-command-route/v1",
        "ok": True,
        "status": "ok",
        "command": "request-schema",
        "version": capability.version,
        "uri": capability.uri,
        "input_shape": "fixed_business_command",
        "native_request_fields_disclosed": False,
        "commands": commands,
        "continuation": (
            commands[0]
            if len(commands) == 1
            else {
                "choose_by_business_intent": commands,
                "business_values_required": "depends_on_command",
            }
        ),
    }


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
    dynamic_commands: dict[str, str] = {}
    for field in contract.fields:
        fact_construction = field.as_dict().get("fact_construction", {})
        if not isinstance(fact_construction, Mapping):
            continue
        if fact_construction.get("complex_member_disclosure") == (
            "request-map-container"
        ):
            dynamic_commands["map_value"] = "request-map-container"
        if fact_construction.get("complex_item_disclosure") == "request-array-item":
            dynamic_commands["array_item"] = "request-array-item"
    payload["continuation"] = {
        **(
            {"dynamic_container_commands": dynamic_commands}
            if dynamic_commands
            else {}
        ),
        "request_key": contract.uri,
    }
    return payload


def _topic_top_level_fact_table(
    contract: TypedRequestContract,
    *,
    prefix: str,
) -> dict[str, Any]:
    """Expose copy-ready top-level Topic facts before the large field tables."""

    fields_by_handle = {
        field.handle: field.as_dict()
        for field in contract.fields
    }
    rows: list[list[Any]] = []
    for handle, _name, phase, action, pointer in contract.top_level_fact_plan()[
        "rows"
    ]:
        if phase != "fact" or not isinstance(handle, str):
            continue
        field = fields_by_handle.get(handle, {})
        accepted_types = field.get("accepted_types", [])
        value_type = (
            accepted_types[0]
            if isinstance(accepted_types, list) and len(accepted_types) == 1
            else "<type>"
        )
        if action == "set":
            nonempty = [
                f"--{prefix}-set", handle, value_type, "<business-value>",
            ]
            empty = None
        elif action == "append":
            nonempty = [
                f"--{prefix}-append", handle, value_type, "<business-value>",
            ]
            empty = [f"--{prefix}-present", handle]
        elif action == "map-put":
            nonempty = [
                f"--{prefix}-map-put", handle, "<business-map-member-key>",
                "<type-of-business-map-member-value>",
                "<business-map-member-value>",
            ]
            empty = [f"--{prefix}-present", handle]
        elif action == "choose":
            nonempty = [f"--{prefix}-choose", handle, "<choice-handle>"]
            empty = None
        else:
            continue
        identity_facts = (
            {
                "id": [
                    f"--{prefix}-map-put", handle, "id", "string",
                    "<exact-guid>",
                ],
                "name": [
                    f"--{prefix}-map-put", handle, "name", "string",
                    "<exact-name>",
                ],
            }
            if prefix == "match"
            and action == "map-put"
            and field.get("name") in {"language", "platform"}
            else None
        )
        rows.append([pointer, nonempty, empty, identity_facts])
    return {
        "columns": [
            "business_pointer",
            "nonempty_fact_argv",
            "empty_argv",
            "object_identity_match_argv",
        ],
        "rows": rows,
    }


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
        "scope": "current_disclosed_node",
        "root_boundary": (
            "current_node_parent_and_member_facts_before_descendant_or_sibling_disclosure"
        ),
        "drain_after": "current_container_disclosure",
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
    if not isinstance(rows, list) or not rows:
        return
    child_contract["branch_fact_group_policy"] = {
        "actions": ["choose_dynamic_argv", "map_put_argv"],
        "group_size": 2,
        "split_across_apply_batches": "forbidden",
        "insufficient_remaining_slots": "start_group_in_next_batch",
        "greedy_batching": {
            "parent_fact_action_count": 1,
            "maximum_groups_with_parent_fact": 2,
            "maximum_groups_without_parent_fact": 3,
            "exact_group_count": (
                "with the parent fact use min(2,business-present queued groups); "
                "without it use min(3,remaining business-present queued groups)"
            ),
            "early_execute_with_a_business_present_group_unpacked": "invalid",
            "rule": (
                "start with the deferred parent fact, append exactly the next up "
                "to two business-present complete branch groups, execute, read the "
                "new revision, then pack exactly the next up to three remaining "
                "business-present complete groups per later batch"
            ),
        },
    }
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
        if draft_shape and not query_shape and topic_prefix is None:
            action_prefix = [
                "--action",
                "add_typed_fact",
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


def _bind_dynamic_scalar_array_facts(
    child_contract: dict[str, Any],
    *,
    child_handle: str,
    draft_shape: bool,
    query_shape: bool,
    topic_prefix: str | None,
) -> None:
    """Attach exact append facts for business-present scalar array items."""

    item_contract = child_contract.pop("scalar_array_item_contract", None)
    if not isinstance(item_contract, Mapping):
        return
    accepted_types = item_contract.get("accepted_types")
    if not isinstance(accepted_types, list) or not all(
        isinstance(value_type, str) for value_type in accepted_types
    ):
        return
    argv_by_type: dict[str, list[str]] = {}
    for value_type in accepted_types:
        deferred = _deferred_dynamic_fact_payload(
            ["--append", child_handle, value_type, "<business-value>"],
            draft_shape=draft_shape,
            query_shape=query_shape,
            topic_prefix=topic_prefix,
        ).get("deferred_fact")
        if isinstance(deferred, Mapping) and isinstance(deferred.get("argv"), list):
            argv_by_type[value_type] = list(deferred["argv"])
    if not argv_by_type:
        return
    scalar_array_item_facts = {
        **dict(item_contract),
        "fact_argv_by_type": argv_by_type,
    }
    enum_values = item_contract.get("enum")
    if (
        len(accepted_types) == 1
        and isinstance(enum_values, list)
        and 0 < len(enum_values) <= MAX_TYPED_ACTIONS_PER_APPLY
        and all(isinstance(value, str) for value in enum_values)
        and len(set(enum_values)) == len(enum_values)
    ):
        template = argv_by_type[accepted_types[0]]
        scalar_array_item_facts.update(
            {
                "fact_argv_by_enum_value": {
                    value: [
                        value if token == "<business-value>" else token
                        for token in template
                    ]
                    for value in enum_values
                },
                "enum_fact_selection": (
                    "copy_exact_argv_for_each_business_item_in_order"
                ),
            }
        )
    scalar_array_item_facts.update(
        {
            "repeat_for_each_business_item_in_order": True,
            "execute_after": "deferred_parent_fact",
            "queue_phase": "child_contract",
            "queue_order_ref": (
                "/continuation/request_wide_order/deferred_fact_queue"
            ),
            "consume_each_item_once": True,
            "replay_allowed": False,
        }
    )
    child_contract["scalar_array_item_facts"] = scalar_array_item_facts


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
    query_shape: bool,
    topic_prefix: str | None,
) -> dict[str, Any]:
    """Describe one returned-handle fact without presenting it as the next command."""

    if draft_shape and not query_shape and topic_prefix is None:
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
            "execute_after": "current_container_disclosure",
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


def _selected_parent_branch_fact_payload(
    args: argparse.Namespace,
    *,
    parent_handle: str,
    draft_shape: bool,
    query_shape: bool,
    topic_prefix: str | None,
) -> dict[str, Any]:
    """Preserve the exact selected branch fact on its disclosed child response."""

    choice_handle = getattr(args, "choice_handle", None)
    if (
        args.command != "request-map-container"
        or not isinstance(choice_handle, str)
    ):
        return {}
    if draft_shape and not query_shape and topic_prefix is None:
        argv = [
            "--action", "add_typed_fact",
            "--fact-action", "choose-dynamic",
            "--field-handle", parent_handle,
            "--fact-value", choice_handle,
            "--key", args.key,
        ]
    elif query_shape:
        argv = [
            "--typed-choose-dynamic", parent_handle, args.key, choice_handle,
        ]
    elif topic_prefix is not None:
        argv = [
            f"--{topic_prefix}-choose-dynamic",
            parent_handle,
            args.key,
            choice_handle,
        ]
    else:
        argv = ["--choose-dynamic", parent_handle, args.key, choice_handle]
    return {
        "selected_parent_branch_fact": {
            "argv": argv,
            "execute_after": (
                "all_pending_ancestor_facts_in_response_tree_preorder"
            ),
            "must_precede": "deferred_fact",
            "queue_phase": "selected_parent_branch",
            "queue_order_ref": (
                "/continuation/request_wide_order/deferred_fact_queue"
            ),
            "is_next_command": False,
            "consume_once": True,
            "replay_allowed": False,
        }
    }


def _root_fact_queue_anchor(
    *,
    contract: TypedRequestContract,
    child_handle: str,
    lineage_token: str,
    outermost_disclosed_root_pointer: str | None,
    draft_shape: bool,
    query_shape: bool,
    topic_prefix: str | None,
) -> dict[str, Any]:
    """Repeat the exact first fact on every descendant response.

    The response-local child tables remain authoritative for later facts.  The
    anchor removes the only cross-response inference: which ancestor fact must
    begin the first batch for this disclosed root.
    """

    if outermost_disclosed_root_pointer is None:
        return {}
    try:
        action, parent_handle, key, shape, root_child_handle = (
            typed_schema_lineage_root_fact(
                contract,
                child_handle=child_handle,
                token=lineage_token,
            )
        )
    except TypedRequestError:
        return {}
    fact = (
        ["--append", parent_handle, shape, root_child_handle]
        if action == "append"
        else ["--map-put", parent_handle, key, shape, root_child_handle]
    )
    payload = _deferred_dynamic_fact_payload(
        fact,
        draft_shape=draft_shape,
        query_shape=query_shape,
        topic_prefix=topic_prefix,
    ).get("deferred_fact")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("argv"), list):
        return {}
    return {
        "root_fact_queue_anchor": {
            "outermost_disclosed_root_pointer": outermost_disclosed_root_pointer,
            "first_fact_argv": list(payload["argv"]),
            "first_batch_must_start_with_first_fact": True,
            "batch_limit": MAX_TYPED_ACTIONS_PER_APPLY,
        }
    }


def _next_array_item_disclosure(
    args: argparse.Namespace,
    *,
    contract: TypedRequestContract,
    child_handle: str,
    lineage_token: str,
) -> dict[str, Any]:
    """Expose the sole nested-array continuation after its parent fact."""

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
            "after_current_node_fact_apply_success": True,
            "is_next_command": False,
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
    nested_sibling = args.parent_schema_token is not None
    transition: dict[str, Any] = {
        "condition": "current_business_request_contains_next_complex_item",
        "business_value_pointer": (
            f"{current_business_value_pointer.rsplit('/', 1)[0]}/{next_index}"
        ),
        "index": next_index,
        **(
            {
                "first_when_current_business_object_is_leaf": True,
                "leaf_nested_container_disclosures": "forbidden",
                "otherwise_after": (
                    "current_node_fact_apply_success_then_all_business_present_"
                    "current_item_descendant_nodes_if_any"
                ),
                "after_current_node_facts": True,
                "when_absent": {
                    "next_action": (
                        "finish_current_node_then_use_nearest_ancestor_business_"
                        "sibling_exact_argv"
                    )
                },
            }
            if nested_sibling
            else {"after": "current_root_fact_apply_success"}
        ),
        "absent_or_scalar_next_item_forbidden": True,
        "is_next_command": False,
        "argv_by_shape": argv_by_shape,
    }
    return {"business_sibling_transition": transition}


def _next_map_sibling_disclosure(
    args: argparse.Namespace,
    *,
    contract: TypedRequestContract,
    parent_schema: Mapping[str, Any] | None,
    parent_section: str | None,
    current_business_value_pointer: str | None,
) -> dict[str, Any]:
    """Expose the next schema-ordered complex member after one map branch."""

    if (
        args.command != "request-map-container"
        or args.parent_schema_token is None
        or parent_schema is None
        or parent_section is None
        or current_business_value_pointer is None
    ):
        return {}
    members = dynamic_fixed_container_members(
        contract,
        parent_schema=parent_schema,
        parent_section=parent_section,
    )
    current_indexes = tuple(
        index
        for index, row in enumerate(members)
        if row.get("key") == args.key and row.get("shape") == args.shape
    )
    if len(current_indexes) != 1:
        return {}
    for row in members[current_indexes[0] + 1 :]:
        key = row.get("key")
        shape = row.get("shape")
        if not isinstance(key, str) or shape not in {"object", "array"}:
            continue
        if not dynamic_map_container_choices(
            contract,
            map_handle=args.map_handle,
            key=key,
            shape=shape,
            parent_schema=parent_schema,
            parent_section=parent_section,
        ):
            continue
        argv_by_shape = {
            shape: [
                "request-map-container",
                args.api,
                "--map-handle",
                args.map_handle,
                "--key",
                key,
                "--shape",
                shape,
                "--parent-schema-token",
                args.parent_schema_token,
            ]
        }
        return {
            "business_sibling_transition": {
                "condition": "current_business_request_contains_next_complex_member",
                "business_value_pointer": (
                    f"{current_business_value_pointer.rsplit('/', 1)[0]}/"
                    f"{key.replace('~', '~0').replace('/', '~1')}"
                ),
                "key": key,
                "after": "current_branch_descendant_disclosures",
                "after_current_node_facts": True,
                "absent_member_forbidden": True,
                "is_next_command": False,
                "argv_by_shape": argv_by_shape,
            }
        }
    return {}


def _root_dynamic_disclosure_commands(
    contract: TypedRequestContract,
) -> dict[str, Any]:
    """Return exact copy-ready commands for every complex root array."""

    rows: list[dict[str, Any]] = []
    for field in contract.fields:
        if field.parent_handle is not None or field.shape != "array":
            continue
        argv_by_shape: dict[str, list[str]] = {}
        for shape in ("object", "array"):
            if not dynamic_array_item_choices(
                contract,
                array_handle=field.handle,
                index=0,
                shape=shape,
            ):
                continue
            argv_by_shape[shape] = [
                "request-array-item",
                contract.uri,
                "--schema-digest",
                contract.schema_digest,
                "--array-handle",
                field.handle,
                "--index",
                "0",
                "--shape",
                shape,
            ]
        if not argv_by_shape:
            continue
        rows.append(
            {
                "name": field.name,
                "field_handle": field.handle,
                "business_value_pointer": (
                    f"/{field.section}/" + "/".join(field.path)
                ),
                "argv_by_shape": argv_by_shape,
            }
        )
    projected = _dynamic_disclosure_copy_commands({
        "selection": "first unsubmitted business-present root in schema order",
        "activation_gate": {
            "source": "/draft/next_action_binding/next_phase_decision",
            "required_selected_candidate": "dynamic_disclosure",
            "while_remaining_top_level_fact_batch_is_selected": (
                "do_not_execute_any_row"
            ),
        },
        "rows": rows,
        "copy_selected_argv_exactly": True,
        "copy_selected_command_exactly": True,
        "reconstruct_schema_digest_or_handle": "invalid",
    })
    for row in projected["rows"]:
        copy_by_shape = row.get("copy_command_by_shape")
        if isinstance(copy_by_shape, Mapping) and len(copy_by_shape) == 1:
            selected_shape = next(iter(copy_by_shape))
            row["copy_instruction"] = {
                "contract": OPERATION_DRAFT_COMMAND_COPY_INSTRUCTION_CONTRACT,
                "source_field": f"copy_command_by_shape.{selected_shape}",
                "action": "execute_verbatim_as_one_shell_tool_call",
                "forbidden_transformations": [
                    "reconstruct",
                    "shorten",
                    "normalize",
                    "substitute_path_segments",
                    "select_another_field",
                ],
            }
    return projected


def _dynamic_disclosure_copy_commands(value: Any) -> Any:
    """Add host-native copy commands only to concrete container disclosures."""

    if isinstance(value, list):
        return [_dynamic_disclosure_copy_commands(item) for item in value]
    if not isinstance(value, Mapping):
        return value
    projected = {
        key: _dynamic_disclosure_copy_commands(item)
        for key, item in value.items()
    }

    def concrete_disclosure_argv(candidate: Any) -> list[str] | None:
        if (
            not isinstance(candidate, list)
            or not candidate
            or candidate[0] not in {"request-map-container", "request-array-item"}
            or any(not isinstance(token, str) or "<" in token for token in candidate)
        ):
            return None
        return candidate

    argv_by_shape = value.get("argv_by_shape")
    if isinstance(argv_by_shape, Mapping):
        copy_by_shape: dict[str, str] = {}
        for shape, candidate in argv_by_shape.items():
            argv = concrete_disclosure_argv(candidate)
            if not isinstance(shape, str) or argv is None:
                continue
            copy_by_shape[shape] = operation_draft_copy_command(
                ["python", str(GATEWAY_RUNNER_PATH), "gateway.py", *argv]
            )
        if copy_by_shape:
            projected["copy_command_by_shape"] = copy_by_shape

    argv = concrete_disclosure_argv(value.get("argv"))
    if argv is not None:
        projected["copy_command"] = operation_draft_copy_command(
            ["python", str(GATEWAY_RUNNER_PATH), "gateway.py", *argv]
        )
    return projected


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
                "follow_business_sibling_transition_then_drain_deferred_fact_queue"
                if next_sibling_disclosure.get(
                    "business_sibling_transition", {}
                ).get("is_next_command") is True
                else (
                    "drain_deferred_fact_queue_then_follow_"
                    "business_sibling_transition"
                )
            ),
            "is_next_command": False,
            "becomes_next_command_only_after_exact_business_pointer_match": True,
            "absent_business_pointer": "forbidden",
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
    selected_parent_branch_fact: Mapping[str, Any],
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
    sibling = next_sibling_disclosure.get("business_sibling_transition", {})
    nested_sibling = (
        isinstance(sibling, Mapping) and sibling.get("is_next_command") is True
    )
    sibling_candidate = (
        {
            "candidate": "business_sibling_transition",
            "condition": (
                "explicit_leaf_or_no_business_nested_member_and_sibling_present"
            ),
            "business_value_pointer": sibling.get("business_value_pointer"),
            "command_pointer": (
                "/continuation/business_sibling_transition/argv_by_shape/"
                "<exact-business-shape>"
            ),
            "explicit_leaf_rule": {
                "user_says_no_properties_references_children": (
                    "copy_exact_command_now"
                ),
                "nested_disclosures": "forbidden",
            },
        }
        if isinstance(sibling, Mapping) and sibling
        else None
    )
    deferred_candidate = (
        {
            "candidate": "deferred_fact_queue",
            "condition": "current_disclosed_node_has_unapplied_business_facts",
            "action": (
                "apply_pending_ancestor_facts_then_selected_parent_branch_fact_"
                "then_current_node_parent_fact_then_business_present_child_"
                "contract_facts_in_schema_order"
                if selected_parent_branch_fact
                and outermost_disclosed_root_pointer is not None
                else "apply_selected_parent_branch_fact_then_current_node_parent_"
                "fact_then_business_present_child_contract_facts_in_schema_order"
                if selected_parent_branch_fact
                else "apply_current_node_parent_fact_then_business_present_"
                "child_contract_facts_in_schema_order"
            ),
            "start_at": "current_disclosed_node_response",
            "batch_facts": (
                "current_disclosed_node_only_up_to_"
                f"{MAX_TYPED_ACTIONS_PER_APPLY}_facts_in_queue_order"
            ),
            "stop_before": "first_descendant_or_sibling_parent_fact",
            "after_success": "re_evaluate_remaining_candidates_from_this_response",
            "first_fact_only": "valid_only_when_current_node_has_no_other_business_facts",
            "first_command_pointer": (
                "/continuation/root_fact_queue_anchor/first_fact_argv"
                if selected_parent_branch_fact
                and outermost_disclosed_root_pointer is not None
                else "/continuation/selected_parent_branch_fact/argv"
                if selected_parent_branch_fact
                else "/continuation/deferred_fact/argv"
            ),
        }
        if deferred_fact
        else None
    )
    if draft_shape and deferred_candidate is not None:
        candidates.append(deferred_candidate)
    if not draft_shape and nested_sibling and sibling_candidate is not None:
        candidates.append(sibling_candidate)
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

    if not draft_shape and deferred_candidate is not None:
        candidates.append(deferred_candidate)
    if sibling_candidate is not None and (draft_shape or not nested_sibling):
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
                        "ask_user_to_continue_before_preview": "invalid",
                        "same_turn_requirement": (
                            "continue_until_preview_or_structured_gateway_error"
                        ),
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


def query_business_schema_payload(
    version: str,
    *,
    advanced: bool,
) -> dict[str, Any]:
    """Describe the one deep direct-read continuation for an object query."""

    if advanced:
        advanced_schema = advanced_query_schema(version=version)
        waql_schema = advanced_schema["properties"]["waql"]
        return {
            "contract": ADVANCED_QUERY_SCHEMA_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "query-schema",
            "version": version,
            "query_layer": "advanced-native-waql",
            "query_contract": ADVANCED_QUERY_CONTRACT,
            "input_shape": "business_declaration",
            "identity_projection": list(SELECTED_REQUIRED_RETURN_FIELDS),
            "business_outputs": list(QUERY_BUSINESS_OUTPUTS),
            "custom_outputs": {
                "available": False,
                "reason": "advanced WAQL has no Gateway-provable live metadata scope",
            },
            "continuation": {
                "subcommand": "query-object",
                "query_layer": "advanced-native-waql",
                "exact_expression": (
                    "--advanced-waql <one bounded exact WAQL expression>"
                ),
                "exact_expression_limits": {
                    "max_utf8_bytes": waql_schema["x-maxUtf8Bytes"],
                    "framing": dict(waql_schema["x-framing"]),
                    "description": waql_schema["description"],
                },
                "result_bound": f"--max-results <1..{MAX_QUERY_TAKE}>",
                "business_output": "--include <business-field> (repeat)",
            },
            "boundary": {
                "fixed_api": OBJECT_GET_URI,
                "read_only": True,
                "gateway_appends_final_take": True,
                "all_results_available": False,
                "return_projection": "gateway_compiled_business_projection",
                "arbitrary_uri_args_or_options_accepted": False,
                "fallback_or_retry_on_invalid_query": False,
            },
        }
    return {
        "contract": BUSINESS_QUERY_SCHEMA_CONTRACT,
        "ok": True,
        "status": "ok",
        "command": "query-schema",
        "version": version,
        "query_layer": "business-declaration",
        "query_contract": BUSINESS_QUERY_CONTRACT,
        "input_shape": "business_declaration",
        "identity_projection": list(SELECTED_REQUIRED_RETURN_FIELDS),
        "business_outputs": list(QUERY_BUSINESS_OUTPUTS),
        "custom_outputs": {
            "field_meaning": "--include-field <user-facing property/reference meaning>",
            "authority": "live WAAPI metadata bound by the Gateway before object.get",
            "repair": "refine the meaning when live discovery is not unique",
        },
        "sources": {
            "object_path": "--path-segment <one literal name> (repeat)",
            "exact_object_id": "--exact-id <canonical GUID>",
            "common_kind": "--kind <closed business kind>",
            "custom_kind": "--custom-kind <user-facing type meaning>",
            "search": "--search-text <literal text>",
            "query_id": "--query-id <canonical GUID>",
            "query_path": "--query-path-segment <one literal name> (repeat)",
        },
        "kind_semantics": {
            "all-sounds": "every Wwise Sound, including SFX and Voice",
            "sound-sfx": "only Sound objects whose source language is SFX",
            "sound-voice": "only Sound objects whose source language is not SFX",
        },
        "source_rules": {
            "exactly_one_source": True,
            "common_kind_is_a_source": (
                "--kind is valid only when no path, id, search, or Query Editor "
                "source is present"
            ),
            "kind_filter_after_another_source": (
                "--predicate kind-is <business-kind>"
            ),
        },
        "predicates": {
            name: {"value_type": value_type}
            for name, (_field, _operator, value_type) in sorted(
                QUERY_BUSINESS_PREDICATES.items()
            )
        }
        | {
            QUERY_BUSINESS_KIND_PREDICATE: {
                "value_type": "business-kind",
                "choices": list(QUERY_BUSINESS_KINDS),
            }
        },
        "relationships": list(QUERY_BUSINESS_RELATIONSHIPS),
        "continuation": {
            "subcommand": "query-object",
            "predicate": "--predicate <business-condition> <value>",
            "relationship": "--relationship <business-relationship>",
            "result_bound": f"--max-results <1..{MAX_QUERY_TAKE}>",
            "business_output": "--include <business-field> (repeat)",
        },
        "presentation_boundary": {
            "sort_or_group_complete_result": "agent-owned presentation",
            "advanced_required_only_when": (
                "server-side ordering, skip, distinct, regex, or another native "
                "construct changes which rows enter the bounded result"
            ),
        },
        "advanced_fallback": {
            "available": True,
            "disclose_with": "query-schema --advanced",
            "use_only_when": (
                "server-side query semantics require a read-only WAQL construct "
                "that the business declaration cannot express; final answer sorting "
                "or grouping does not qualify"
            ),
        },
    }


def dispatch_offline_command(args: argparse.Namespace, *, env: Mapping[str, str]) -> dict[str, Any]:
    """Run catalog commands without requiring a WAAPI port or live Wwise."""

    if args.command == "topic-schema":
        (version,) = resolve_catalog_versions(args, env=env)
        options = topic_options_contract(version, args.api)
        match = topic_match_contract(version, args.api)
        options_payload = typed_topic_contract_payload(options)
        match_payload = typed_topic_contract_payload(match)
        match_fields = match_payload.get("fields")
        duplicate_name_fact_routes = (
            match_fields.get("duplicate_name_fact_routes")
            if isinstance(match_fields, Mapping)
            else None
        )
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
                    **(
                        {"qualified_duplicate_fact_routes": duplicate_name_fact_routes}
                        if isinstance(duplicate_name_fact_routes, Mapping)
                        and duplicate_name_fact_routes.get("rows")
                        else {}
                    ),
                    "top_level_fact_tables": {
                        "options": _topic_top_level_fact_table(
                            options,
                            prefix="option",
                        ),
                        "match": _topic_top_level_fact_table(
                            match,
                            prefix="match",
                        ),
                    },
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
            "options": options_payload,
            "event_match": match_payload,
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
                    fields.pop("duplicate_name_fact_routes", None)
            continuation = payload.get("continuation")
            fact_argv = (
                continuation.get("fact_argv")
                if isinstance(continuation, Mapping)
                else None
            )
            if isinstance(fact_argv, dict):
                fact_argv.pop("qualified_duplicate_fact_routes", None)
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
            # Copy-ready top-level facts prevent opaque-handle transcription
            # on schemas with room for the redundant table. Large Topics keep
            # the same exact handles in their lossless field tables.
            continuation = payload.get("continuation")
            fact_argv = (
                continuation.get("fact_argv")
                if isinstance(continuation, Mapping)
                else None
            )
            if isinstance(fact_argv, dict):
                fact_argv.pop("top_level_fact_tables", None)
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
        if args.api in {
            STRUCTURED_TYPED_QUERY_OPERATION,
            ADVANCED_TYPED_QUERY_OPERATION,
        }:
            raise GatewayInputError(
                "Object queries use query-schema and its business continuation; "
                "archived typed query pseudo-operations are not public routes."
            )
        if args.command == "request-schema" and args.api.startswith(
            (TOPIC_OPTIONS_OPERATION_PREFIX, TOPIC_MATCH_OPERATION_PREFIX)
        ):
            raise GatewayInputError(
                "Typed Topics use topic-schema <topic-uri> as their single schema entry."
            )
        capability: CapabilityRecord | None = None
        if args.api.startswith("ak."):
            try:
                catalog = CapabilityCatalog()
                capability = (
                    catalog.authoring_ui_describe(versions[0], args.api)
                    if args.api in AUTHORING_UI_COMMAND_URIS
                    else catalog.describe(versions[0], args.api)
                )
            except CapabilityNotFoundError:
                capability = None
        if (
            args.command == "request-schema"
            and capability is not None
            and capability.preferred_route == "fixed_command"
        ):
            return fixed_command_route_payload(capability)
        if args.command != "request-schema" and args.api.startswith("ak."):
            if (
                capability is not None
                and capability.preferred_route == "fixed_command"
                and args.command not in capability.fixed_commands
            ):
                raise GatewayInputError(
                    f"{args.api} uses its Gateway-owned fixed command: "
                    f"{', '.join(capability.fixed_commands)}"
                )
        contract = public_typed_contract(versions[0], args.api)
        if args.command == "request-schema":
            dedicated_zero = {
                "ak.wwise.debug.restartWaapiServers": "debug.restartWaapiServers",
                "ak.wwise.debug.testAssert": "debug.testAssert",
                "ak.wwise.debug.testCrash": "debug.testCrash",
            }.get(args.api)
            if dedicated_zero is not None:
                raise GatewayInputError(
                    "This dangerous host control uses operation-schema "
                    f"{dedicated_zero} as its single business entry."
                )
        if args.command == "request-schema":
            return contract.as_gateway_payload()
        draft_shape = contract.as_gateway_payload()["input_shape"] == "draft"
        query_shape = False
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
            query_shape=query_shape,
            topic_prefix=topic_prefix,
        )
        _bind_dynamic_scalar_array_facts(
            child_contract,
            child_handle=child_handle,
            draft_shape=draft_shape,
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
            scalar_array_item_facts = child_contract.get(
                "scalar_array_item_facts"
            )
            if isinstance(scalar_array_item_facts, dict):
                scalar_array_item_facts["business_values_pointer"] = (
                    current_business_value_pointer
                )
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
            branch_choices = child_contract.get("branch_choices")
            if isinstance(branch_choices, list):
                for row in branch_choices:
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
        if branch_continuation:
            # A branch response owns the sole next container command. Direct
            # schema siblings are disclosed by the selected branch response,
            # after the Gateway has revalidated that exact parent lineage.
            nested_container_disclosures = []
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
        if not next_sibling_disclosure:
            next_sibling_disclosure = _next_map_sibling_disclosure(
                args,
                contract=contract,
                parent_schema=parent_schema,
                parent_section=parent_section,
                current_business_value_pointer=current_business_value_pointer,
            )
        deferred_fact = _deferred_dynamic_fact_payload(
            fact,
            draft_shape=draft_shape,
            query_shape=query_shape,
            topic_prefix=topic_prefix,
        )
        selected_parent_branch_fact = _selected_parent_branch_fact_payload(
            args,
            parent_handle=parent_handle,
            draft_shape=draft_shape,
            query_shape=query_shape,
            topic_prefix=topic_prefix,
        )
        if "deferred_fact" in deferred_fact:
            blocked_by: list[str] = []
            if branch_continuation:
                blocked_by.append("branch_disclosure")
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
                                "current_node_fact_apply_success_then_all_"
                                "business_present_current_item_descendant_nodes_if_any"
                                if args.parent_schema_token is not None
                                else "current_root_fact_apply_success"
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
                **next_sibling_disclosure,
                # Copy-ready nested commands are the current response's
                # actionable continuation. Keep the complete schema-ordered
                # list before repeated queue and request-wide guidance so
                # every exact candidate remains visible in a bounded
                # shell-tool prefix.
                **(
                    {
                        "nested_container_disclosures": (
                            nested_container_disclosures
                        ),
                        "nested_container_order": (
                            "branch_then_current_node_facts_then_schema_members_"
                            "then_descendants"
                            if branch_continuation
                            else "current_node_facts_then_schema_members_then_descendants"
                        ),
                    }
                    if nested_container_disclosures
                    else {}
                ),
                **_root_fact_queue_anchor(
                    contract=contract,
                    child_handle=child_handle,
                    lineage_token=lineage_token,
                    outermost_disclosed_root_pointer=(
                        outermost_disclosed_root_pointer
                    ),
                    draft_shape=draft_shape,
                    query_shape=query_shape,
                    topic_prefix=topic_prefix,
                ),
                **selected_parent_branch_fact,
                **_dynamic_next_command_decision(
                    draft_shape=(
                        draft_shape and not query_shape and topic_prefix is None
                    ),
                    outermost_disclosed_root_pointer=(
                        outermost_disclosed_root_pointer
                    ),
                    branch_continuation=branch_continuation,
                    nested_container_disclosures=nested_container_disclosures,
                    next_item_disclosure=next_item_disclosure,
                    next_sibling_disclosure=next_sibling_disclosure,
                    deferred_fact=deferred_fact,
                    selected_parent_branch_fact=selected_parent_branch_fact,
                ),
                "request_wide_order": {
                    "phase": "node_local_disclosure_then_facts",
                    "root_boundary": (
                        "finish_current_root_nodes_before_next_root"
                    ),
                    "traversal": "response_tree_preorder",
                    "nested_member_order": "schema_property_order",
                    "child_fact_order": "child_contract_schema_order",
                    "deferred_fact_queue": {
                        "traversal": "response_tree_preorder",
                        "node_steps": [
                            *(
                                ["selected_parent_branch_fact"]
                                if selected_parent_branch_fact
                                else []
                            ),
                            "deferred_parent_fact",
                            "child_contract_facts",
                            "then_descendant_response_nodes",
                        ],
                        "forbidden": [
                            "descendant_fact_before_current_node_parent_or_child_facts",
                            "next_outer_sibling_disclosure_before_current_root_facts",
                            "one_fact_apply_batch_spanning_disclosed_nodes",
                        ],
                    },
                    "this_handle_is_not_a_complete_request": True,
                },
                "subcommand": (
                    "query-object"
                    if query_shape
                    else "topic-input-fact" if topic_prefix is not None
                    else "draft-apply" if draft_shape else "typed-call"
                ),
                **(
                    {
                        "draft_fact_execution": {
                            "prefix_source": (
                                "latest_draft_response.next_action_binding."
                                "fixed_argv_prefix"
                            ),
                            "complete_command_formula": [
                                "copy_every_prefix_argv_from_prefix_source",
                                (
                                    "append_current_node_deferred_parent_fact_"
                                    "when_present"
                                ),
                                (
                                    "append_every_business_present_child_contract_"
                                    "fact_in_schema_order"
                                ),
                                "execute_once_as_one_shell_tool_call",
                            ],
                            "runner_only_or_prefix_only_command": "invalid",
                            "batch_scope": "current_disclosed_node_only",
                            "complete_action_groups_in_queue_order": True,
                            "maximum_actions": MAX_TYPED_ACTIONS_PER_APPLY,
                            "count_each_literal_action_flag": True,
                            "seventh_action": (
                                "stop_before_it_execute_first_six_then_read_response"
                            ),
                            "copy_returned_handles_exactly": True,
                        }
                    }
                    if draft_shape
                    and not query_shape
                    and topic_prefix is None
                    else {}
                ),
                **next_item_disclosure,
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
        if draft_shape:
            read_only_draft = (
                args.api.startswith("ak.")
                and contract.effect == "read"
            )
            response["construction_state"] = {
                "complete": False,
                "disclosure_replay_allowed": False,
                "next_phase": (
                    "apply_current_node_facts_then_continue_dynamic_disclosures"
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
        response["continuation"] = _dynamic_disclosure_copy_commands(
            response["continuation"]
        )
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
        payload = operation_draft_payload(
            args.command,
            started.record,
            task_authority=started.task_authority,
        )
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
        if operation_uses_business_declaration(
            inspected.operation,
            inspected.version,
        ):
            raise GatewayInputError(
                f"{inspected.operation} no longer accepts shallow draft-apply actions; "
                "use the Gateway-owned business declaration commands from draft-start"
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
    if args.command in {
        "draft-add-media",
        "draft-business-configure",
        "draft-clear-object-list",
        "draft-declare-field-change",
        "draft-declare-import-batch",
        "draft-declare-object-change",
        "draft-declare-switch-assignment",
        "draft-declare-rtpc",
        "draft-declare-existing",
        "draft-declare-new",
        "draft-remove-declaration",
        "draft-revise-declaration",
    }:
        return dispatch_offline_business_draft_update(args, env=env)
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
                **query_business_schema_payload(
                    versions[0], advanced=args.advanced
                ),
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
                "advanced-native-waql" if args.advanced else "business-declaration"
            ),
            "query_contract": (
                ADVANCED_QUERY_CONTRACT if args.advanced else BUSINESS_QUERY_CONTRACT
            ),
            "versions": list(versions),
            "contracts": {
                version: query_business_schema_payload(
                    version,
                    advanced=args.advanced,
                )
                for version in versions
            },
        }
    if args.command == "operations":
        operations: list[dict[str, Any]] = []
        for spec in list_operation_specs():
            if spec.name == "waapi.call":
                continue
            modes = {
                version: operation_input_mode(spec.name, version)
                for version in spec.supported_versions
            }
            if not args.detail:
                projection = spec.as_compact_dict()
                if set(modes.values()) == {BUSINESS_DECLARATION_INPUT_MODE}:
                    projection.pop("required_arguments", None)
                    projection.pop("optional_arguments", None)
                    projection["input_mode"] = BUSINESS_DECLARATION_INPUT_MODE
                    projection["next_command"] = ["operation-schema", spec.name]
                operations.append(projection)
                continue
            if BUSINESS_DECLARATION_INPUT_MODE in modes.values():
                projection = composer_operation_projection(spec, version=None)
                projection["input_modes_by_version"] = modes
                projection["business_contracts_by_version"] = {
                    version: operation_business_contract(spec.name, version)
                    for version, mode in modes.items()
                    if mode == BUSINESS_DECLARATION_INPUT_MODE
                }
                operations.append(projection)
                continue
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
        normal_business = input_mode == BUSINESS_DECLARATION_INPUT_MODE
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
                if normal_composer or normal_business or normal_inline
                else spec.as_dict(version=request_version)
            )
        payload = {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok" if spec.implemented else "unsupported_boundary",
            "command": args.command,
            "offline": True,
        }
        if normal_composer and request_version is not None:
            payload["composer"] = operation_composer_input_contract(
                spec.name,
                request_version,
            )
        if normal_business and request_version is not None:
            business_contract = operation_business_contract(
                spec.name,
                request_version
            )
            start = dict(business_contract["start"])
            gateway_argv = start.pop("gateway_argv", None)
            if gateway_argv is not None:
                start.pop("copy_instruction", None)
                start["next_command"] = transaction_next_command(
                    "draft-start",
                    gateway_argv,
                )
            business_contract["start"] = start
            payload["business_adapter"] = business_contract
        payload["operation"] = operation_projection
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


def resolve_profiler_voice_path(
    args: argparse.Namespace,
    *,
    connection: GatewayConnection,
    detected_version: str,
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> tuple[int, tuple[int, ...]] | dict[str, Any]:
    """Resolve semantic voice/Bus identities to one live pipeline path."""

    def read_rows(api: str) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
        request_args = {"time": args.time}
        request_options = {
            "return": list(PROFILER_PIPELINE_IDENTITY_RETURN_FIELDS)
        }
        validation = validate_semantic_payload(
            api,
            request_args,
            request_options,
            version=detected_version,
        )
        result = dispatch(
            dispatcher,
            api,
            connection=connection,
            version=detected_version,
            args=request_args,
            options=request_options,
            # These are read-only implementation dependencies of the closed
            # voice-contribution Adapter. Their separate public routes remain
            # transaction-gated until #87 migrates them.
            allow_destructive=True,
            result_limit_bytes=STABLE_READ_RESULT_LIMIT_BYTES,
        )
        if not result.get("ok"):
            return [], {
                "ok": False,
                "status": "error",
                **dict(common),
                "api_attempted": api,
                "schema_validation": {
                    "request": validation.as_dict(),
                    "result": None,
                },
                "call": dispatch_call_summary(result),
            }
        payload = result.get("result")
        rows = payload.get("return") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list) or len(rows) > MAX_PROFILER_PIPELINE_IDENTITY_ROWS:
            raise GatewayResultShapeError(
                "Profiler identity lookup returned an invalid bounded row array.",
                details={
                    "api": api,
                    "maximum_rows": MAX_PROFILER_PIPELINE_IDENTITY_ROWS,
                },
                error_code="INVALID_STABLE_READ_RESULT",
            )
        required = set(PROFILER_PIPELINE_IDENTITY_RETURN_FIELDS)
        normalized: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or not required <= set(row):
                raise GatewayResultShapeError(
                    "Profiler identity lookup returned a malformed row.",
                    details={"api": api, "row_index": index},
                    error_code="INVALID_STABLE_READ_RESULT",
                )
            pipeline_id = row.get("pipelineID")
            game_object_id = row.get("gameObjectID")
            object_guid = row.get("objectGUID")
            if (
                isinstance(pipeline_id, bool)
                or not isinstance(pipeline_id, int)
                or not 0 <= pipeline_id <= 0xFFFFFFFF
                or isinstance(game_object_id, bool)
                or not isinstance(game_object_id, int)
                or not 0 <= game_object_id <= (1 << 64) - 1
                or not _canonical_guid(object_guid)
            ):
                raise GatewayResultShapeError(
                    "Profiler identity lookup returned invalid identity values.",
                    details={"api": api, "row_index": index},
                    error_code="INVALID_STABLE_READ_RESULT",
                )
            normalized.append(dict(row))
        return normalized, result

    voices_or_rows = read_rows("ak.wwise.core.profiler.getVoices")
    voices, voice_result = voices_or_rows
    if not voice_result.get("ok", True):
        return dict(voice_result)
    voice_matches = [
        row
        for row in voices
        if str(row["objectGUID"]).casefold() == args.voice_object_id.casefold()
        and (
            args.game_object_id is None
            or row["gameObjectID"] == args.game_object_id
        )
    ]
    if len(voice_matches) != 1:
        return {
            "ok": True,
            "status": "needs_clarification",
            **dict(common),
            "operation": "profiler-voice-contributions",
            "agent_result": {
                "requested_voice_object_id": args.voice_object_id,
                "matching_voice_count": len(voice_matches),
                "candidates": [
                    {
                        "object_name": row["objectName"],
                        "game_object_id": row["gameObjectID"],
                        "game_object_name": row["gameObjectName"],
                    }
                    for row in voice_matches
                ],
                "repair": (
                    "provide --game-object-id when more than one active voice matches"
                ),
            },
        }
    voice = voice_matches[0]
    bus_pipeline_ids: list[int] = []
    if args.bus_object_id:
        busses, bus_result = read_rows("ak.wwise.core.profiler.getBusses")
        if not bus_result.get("ok", True):
            return dict(bus_result)
        for requested in args.bus_object_id:
            matches = [
                row
                for row in busses
                if str(row["objectGUID"]).casefold() == requested.casefold()
                and row["gameObjectID"] == voice["gameObjectID"]
            ]
            if len(matches) != 1:
                return {
                    "ok": True,
                    "status": "needs_clarification",
                    **dict(common),
                    "operation": "profiler-voice-contributions",
                    "agent_result": {
                        "requested_bus_object_id": requested,
                        "matching_bus_count": len(matches),
                        "repair": (
                            "choose one Bus identity active for the selected game object"
                        ),
                    },
                }
            bus_pipeline_ids.append(int(matches[0]["pipelineID"]))
    return int(voice["pipelineID"]), tuple(bus_pipeline_ids)


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


def dispatch_debug_validation(
    call_args: Mapping[str, Any],
    *,
    connection: GatewayConnection,
    detected_version: str,
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one Gateway-owned exact Debug call envelope."""

    api = TYPED_REQUEST_COMPLEX_TRACER_URI
    capability = CapabilityCatalog().describe(detected_version, api)
    normalized_args = dict(call_args)
    supplied_sections = [
        name for name in ("args", "options", "result") if name in normalized_args
    ]
    request_validation = validate_semantic_payload(
        api, normalized_args, {}, version=detected_version
    )
    result = dispatch(
        dispatcher,
        api,
        connection=connection,
        version=detected_version,
        args=normalized_args,
        options={},
        result_limit_bytes=int(capability.execution_contract["result_limit_bytes"]),
        operation_timeout=float(capability.execution_contract["timeout_seconds"]),
    )
    if result.get("waapi_error_uri") == "ak.wwise.invalid_procedure_uri":
        return {
            "ok": True,
            "status": "unsupported_boundary",
            **dict(common),
            "api_attempted": api,
            "validated_api": normalized_args["id"],
            "supplied_sections": supplied_sections,
            "error_code": "DEBUG_BUILD_REQUIRED",
            "message": (
                "The running Wwise build does not register this Debug read; "
                "use a matching Debug-capable Authoring build for live execution proof."
            ),
            "executed": False,
            "call": dispatch_call_summary(result),
            "agent_result": None,
        }
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
        "validated_api": normalized_args["id"],
        "supplied_sections": supplied_sections,
        "call": dispatch_call_summary(result),
        "schema_validation": {
            "request": request_validation.as_dict(),
            "result": result_validation.as_dict() if result_validation else None,
        },
        "agent_result": (
            {
                "validated_api": normalized_args["id"],
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
    if args.command == "draft-bind-object":
        return dispatch_business_object_binding(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command == "draft-declare-soundbank-plan":
        return dispatch_business_soundbank_plan(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command == "draft-declare-artifact-plan":
        return dispatch_business_exact_artifact_plan(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command in {"draft-declare-ui-plan", "draft-add-ui-command"}:
        return dispatch_business_authoring_ui_update(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command == "draft-declare-debug-intent":
        return dispatch_business_debug_intent(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command == "draft-declare-undo-plan":
        return dispatch_business_compound_undo_plan(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command == "draft-bind-field":
        return dispatch_business_field_binding(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command == "draft-discover-fields":
        return dispatch_business_field_discovery(
            args,
            env=env,
            connection=connection,
            detected_version=detected_version,
            live_info=live_info,
            dispatcher=dispatcher,
            common=common,
        )
    if args.command == "draft-discover-types":
        return dispatch_business_type_discovery(
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
        resolved = resolve_profiler_voice_path(
            args,
            connection=connection,
            detected_version=detected_version,
            dispatcher=dispatcher,
            common=common,
        )
        if isinstance(resolved, dict):
            return resolved
        voice_pipeline_id, bus_pipeline_ids = resolved
        request = build_profiler_voice_contributions_request(
            version=detected_version,
            time=args.time,
            voice_pipeline_id=voice_pipeline_id,
            bus_pipeline_ids=bus_pipeline_ids,
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
        if result.get("waapi_error_uri") == "ak.wwise.invalid_procedure_uri":
            return {
                "ok": True,
                "status": "unsupported_boundary",
                **common,
                "api_attempted": api,
                "error_code": "DEBUG_BUILD_REQUIRED",
                "message": (
                    "The running Wwise build does not register this Debug read; "
                    "use a matching Debug-capable Authoring build for live execution proof."
                ),
                "executed": False,
                "call": dispatch_call_summary(result),
                "schema_validation": {
                    "request": request_validation.as_dict(),
                    "result": None,
                },
                "agent_result": None,
            }
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
                take=args.max_nodes,
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
    if args.command == "debug-validate-call":
        api = TYPED_REQUEST_COMPLEX_TRACER_URI
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
        artifact = (
            {
                "path": args.artifact_file,
                "digest": args.artifact_digest,
                "authority": "user_owned_exact_artifact",
            }
            if args.artifact_file is not None
            else None
        )
        return dispatch_debug_validation(
            args.debug_validation_args,
            connection=connection,
            detected_version=detected_version,
            dispatcher=dispatcher,
            common={**common, "artifact": artifact},
        )
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
            "agent_result": rows if result.get("ok") else None,
        }
    if args.command == "selected":
        return_fields = SELECTED_REQUIRED_RETURN_FIELDS
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
            "agent_result": rows if result.get("ok") else None,
        }
    if args.command == "query-object":
        advanced_preview = getattr(args, "advanced_query_preview", None)
        if advanced_preview is not None:
            envelope = advanced_preview.envelope
            maximum_rows = int(
                advanced_preview.envelope.metadata["query_bound"]["value"]
            )
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
                    command="query-object --advanced-waql",
                    maximum_rows=maximum_rows,
                )
                if result.get("ok")
                else []
            )
            business_rows = (
                _project_query_business_rows(args, rows) if result.get("ok") else []
            )
            return {
                "ok": bool(result.get("ok")),
                "status": "ok" if result.get("ok") else "error",
                **common,
                "query_layer": "advanced-native-waql",
                "query_contract": ADVANCED_QUERY_CONTRACT,
                "semantic_preview": advanced_preview.as_dict(),
                "query_bound": {
                    "mode": "gateway-appended-take",
                    "value": maximum_rows,
                },
                "call": dispatch_call_summary(result),
                "count": len(rows) if result.get("ok") else None,
                "limit_reached": (
                    len(rows) == maximum_rows if result.get("ok") else None
                ),
                "objects": business_rows if result.get("ok") else None,
                "agent_result": business_rows if result.get("ok") else None,
            }
        if original_file_reference_match_requested(args):
            return dispatch_original_file_reference_match(
                args,
                connection=connection,
                detected_version=detected_version,
                dispatcher=dispatcher,
                common=common,
            )
        custom_kind_clarification = _bind_custom_kind_from_live_types(
            args,
            connection=connection,
            detected_version=detected_version,
            dispatcher=dispatcher,
        )
        if custom_kind_clarification is not None:
            return {
                "ok": True,
                "status": "needs_clarification",
                **common,
                "query_layer": "business-declaration",
                "agent_result": custom_kind_clarification,
            }
        custom_field_clarification = _bind_query_custom_fields_from_live_metadata(
            args,
            connection=connection,
            detected_version=detected_version,
            dispatcher=dispatcher,
        )
        if custom_field_clarification is not None:
            return {
                "ok": True,
                "status": "needs_clarification",
                **common,
                "query_layer": "business-declaration",
                "agent_result": custom_field_clarification,
            }
        where = typed_query_predicates(args)
        return_fields = args.query_return_fields
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
        business_rows = (
            _project_query_business_rows(args, rows) if result.get("ok") else []
        )
        return {
            "ok": bool(result.get("ok")),
            "status": "ok" if result.get("ok") else "error",
            **common,
            "semantic_preview": preview.as_dict(),
            "query_bound": _query_bound_summary(args),
            "call": dispatch_call_summary(result),
            "count": len(rows) if result.get("ok") else None,
            "objects": business_rows if result.get("ok") else None,
            "agent_result": business_rows if result.get("ok") else None,
        }
    if args.command == "metadata":
        if args.operation in {"discover", "property-state"}:
            custom_kind_clarification = _bind_custom_kind_from_live_types(
                args,
                connection=connection,
                detected_version=detected_version,
                dispatcher=dispatcher,
            )
            if custom_kind_clarification is not None:
                return {
                    "ok": True,
                    "status": "needs_clarification",
                    **common,
                    "operation": args.operation,
                    "metadata_authority": "live-waapi",
                    "agent_result": custom_kind_clarification,
                }
            metadata_calls: list[dict[str, Any]] = []
            read_call = transaction_read_call(
                dispatcher,
                connection=connection,
                version=detected_version,
                call_sink=metadata_calls,
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
            if args.operation == "discover":
                payload = {
                    "ok": True,
                    "status": "ok",
                    **common,
                    "operation": args.operation,
                    "metadata_authority": "live-waapi",
                    **metadata_call_evidence_projection(metadata_calls),
                }
                payload["agent_result"] = discovery.as_dict(detail=False)
                return payload
            candidates = tuple(discovery.candidates)
            if len(candidates) != 1:
                return {
                    "ok": True,
                    "status": "needs_clarification",
                    **common,
                    "operation": args.operation,
                    "metadata_authority": "live-waapi",
                    **metadata_call_evidence_projection(metadata_calls),
                    "agent_result": {
                        "meaning": args.queries[0],
                        "candidate_count": len(candidates),
                        "candidates": [
                            {
                                "field": candidate.get("name"),
                                "display_name": (
                                    candidate.get("metadata", {})
                                    .get("display", {})
                                    .get("name")
                                    if isinstance(candidate.get("metadata"), Mapping)
                                    else None
                                ),
                            }
                            for candidate in candidates
                        ],
                        "repair": (
                            "refine --meaning until exactly one live field matches"
                        ),
                    },
                }
            field_name = candidates[0].get("name")
            field_kind = candidates[0].get("kind")
            if not isinstance(field_name, str) or not field_name:
                raise GatewayResultShapeError(
                    "metadata property-state discovery returned an invalid field.",
                    details={"operation": args.operation},
                    error_code="INVALID_METADATA_RESULT",
                )
            if field_kind != "property":
                return {
                    "ok": True,
                    "status": "needs_clarification",
                    **common,
                    "operation": args.operation,
                    "metadata_authority": "live-waapi",
                    **metadata_call_evidence_projection(metadata_calls),
                    "agent_result": {
                        "meaning": args.queries[0],
                        "candidate_count": 1,
                        "candidates": [
                            {
                                "field": field_name,
                                "kind": field_kind,
                            }
                        ],
                        "repair": (
                            "request a property meaning; references do not have "
                            "an enabled-state query"
                        ),
                    },
                }
            preview = MetadataBuilder(version=detected_version).is_property_enabled(
                object=args.object,
                property=field_name,
                platform=args.platform,
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
            normalized = (
                parse_is_property_enabled_result(result.get("result")).as_dict()
                if result.get("ok")
                else None
            )
            return {
                "ok": bool(result.get("ok")),
                "status": "ok" if result.get("ok") else "error",
                **common,
                "operation": args.operation,
                "metadata_authority": "live-waapi",
                **metadata_call_evidence_projection(metadata_calls),
                "semantic_preview": preview.as_dict(),
                "call": dispatch_call_summary(result),
                "agent_result": (
                    {
                        "meaning": args.queries[0],
                        "platform": args.platform,
                        "enabled": normalized["enabled"],
                    }
                    if normalized is not None
                    else None
                ),
            }
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
        if args.operation == "attenuation":
            payload["agent_result"] = (
                {
                    "curve_role": args.curve_role,
                    "use": normalized["use"],
                    "points": normalized["points"],
                }
                if normalized is not None
                else None
            )
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
    compiled_business = None
    raw_business_session = (
        materialized.record.composition.get("business_session")
        if materialized.record.composition is not None
        else None
    )
    if raw_business_session is not None and operation_uses_business_declaration(
        canonical_request.operation,
        canonical_request.version,
    ):
        adapter = business_adapter(canonical_request.operation)
        business_session = BusinessDeclarationSession.from_dict(raw_business_session)
        bound_objects = tuple(
            business_session.handles.resolve_object(row["handle"])
            for row in business_session.handles.as_dict()["objects"]
        )
        revalidate_live_objects(
            business_session.handles,
            bound_objects,
            read_call=read_call,
        )
        if adapter.supports_field_binding or adapter.supports_field_discovery:
            for row in business_session.handles.as_dict()["fields"]:
                bound_field = business_session.handles.bound_field(row["handle"])
                revalidate_live_field(
                    business_session.handles,
                    bound_field,
                    read_call=read_call,
                )
        if adapter.supports_type_discovery:
            bound_types = tuple(
                business_session.handles.resolve_type(row["handle"])
                for row in business_session.handles.as_dict()["types"]
            )
            revalidate_live_types(
                business_session.handles,
                bound_types,
                read_call=read_call,
            )

        def build_business_continuation(
            _request: Mapping[str, Any],
            _request_digest: str,
            deadline: Any,
        ) -> Mapping[str, Any]:
            deadline.checkpoint()
            return transaction_next_command(
                "preview-from-draft",
                [
                    "preview-from-draft",
                    materialized.record.draft_id,
                    "--task-authority",
                    args.task_authority,
                    "--expected-revision",
                    str(materialized.record.revision + 1),
                ],
            )

        compiled_business = adapter.compile_preview(
            business_session,
            build_continuation=build_business_continuation,
        )
        if compiled_business is not None:
            if (
                compiled_business.request != materialized.request
                or compiled_business.request_digest != materialized.request_digest
            ):
                raise OperationDraftBindingDrift(
                    "Compiled business Preview differs from the Draft canonical request."
                )
    if canonical_request.operation == "object.set":
        read_call = prepare_object_set_batch_check(
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
        business_preview=(
            None if compiled_business is None else compiled_business.preview
        ),
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
    preview_arguments = [
        "preview-from-draft",
        record.draft_id,
        "--task-authority",
        args.task_authority,
        "--expected-revision",
        str(record.revision),
    ]
    if not (
        operation_uses_business_declaration(
            canonical_request.operation,
            canonical_request.version,
        )
        and business_adapter(canonical_request.operation).auto_apply_preview
    ):
        preview_arguments.append("--apply")
    payload["next_command"] = transaction_next_command(
        "preview-from-draft",
        preview_arguments,
    )
    return payload


def _parse_business_value(value_type: str, raw: str, *, field: str) -> Any:
    if value_type in {"string", "reference"}:
        return raw
    if value_type == "boolean":
        if raw not in {"true", "false"}:
            raise GatewayInputError(f"{field} requires true or false")
        return raw == "true"
    if value_type == "integer":
        try:
            value = int(raw)
        except ValueError as exc:
            raise GatewayInputError(f"{field} requires an integer") from exc
        if str(value) != raw and not (value == 0 and raw == "-0"):
            raise GatewayInputError(f"{field} requires a canonical integer")
        return value
    if value_type == "number":
        try:
            value = float(raw)
        except ValueError as exc:
            raise GatewayInputError(f"{field} requires a number") from exc
        if not math.isfinite(value):
            raise GatewayInputError(f"{field} requires a finite number")
        return value
    raise GatewayInputError(f"{field} has an unsupported business value type")


def _parse_audio_import_business_fields(
    session: BusinessDeclarationSession,
    pairs: Sequence[Sequence[str]],
    *,
    switch_value: str | None = None,
    allow_switch_value_pair: bool = True,
    field_value_pairs: Sequence[Sequence[str]] = (),
    event_parent_handle: str | None = None,
    event_name: str | None = None,
    event_action: str | None = None,
) -> dict[str, Any]:
    raw_field_types = audio_import_business_contract(
        session.context.wwise_version
    )["field_value_types"]
    if not isinstance(raw_field_types, Mapping):  # pragma: no cover - Registry invariant
        raise GatewayInputError("audio import business field contract is invalid")
    field_types = dict(raw_field_types)
    fields: dict[str, Any] = {}
    literal_pairs = [*pairs]
    if switch_value is not None:
        literal_pairs.append(("switch_value", switch_value))
    generic_pair_count = len(pairs)
    for index, pair in enumerate(literal_pairs):
        if len(pair) != 2:
            raise GatewayInputError("business --field requires FIELD VALUE")
        name, raw = pair
        if (
            name == "switch_value"
            and not allow_switch_value_pair
            and index < generic_pair_count
        ):
            raise GatewayInputError(
                "Per-declaration switch_value requires the dedicated "
                "--switch-value business argument"
            )
        value_type = field_types.get(name)
        if value_type is None:
            raise GatewayInputError(
                f"Unknown audio import business field {name!r}; use a disclosed stable field"
            )
        if name in fields:
            raise GatewayInputError(f"Business field {name!r} was supplied twice")
        fields[name] = _parse_business_value(value_type, raw, field=name)
    if field_value_pairs:
        dynamic: dict[str, Any] = {}
        for pair in field_value_pairs:
            if len(pair) != 2:
                raise GatewayInputError(
                    "business --field-value requires FIELD_HANDLE VALUE"
                )
            handle, raw = pair
            if handle in dynamic:
                raise GatewayInputError("One Field Handle was supplied twice")
            bound = session.handles.bound_field(handle)
            dynamic[handle] = _parse_business_value(
                bound.value_type,
                raw,
                field=bound.token,
            )
        fields["field_values"] = dynamic
    event_parts = (event_parent_handle, event_name, event_action)
    if any(value is not None for value in event_parts):
        if event_parent_handle is None or event_name is None:
            raise GatewayInputError(
                "Event creation requires --event-parent-handle and --event-name together"
            )
        fields["event"] = {
            "parent_handle": event_parent_handle,
            "name": event_name,
            "action": event_action or "Play",
        }
    return fields


def _parse_object_graph_business_fields(
    session: BusinessDeclarationSession,
    operation: str,
    pairs: Sequence[Sequence[str]],
    *,
    field_value_pairs: Sequence[Sequence[str]] = (),
) -> dict[str, Any]:
    declaration = operation_business_contract(operation, session.context.wwise_version)[
        "declaration"
    ]
    raw_field_types = declaration.get("field_value_types")
    if not isinstance(raw_field_types, Mapping):
        raise GatewayInputError("object graph business field contract is invalid")
    fields: dict[str, Any] = {}
    for pair in pairs:
        if len(pair) != 2:
            raise GatewayInputError("business --field requires FIELD VALUE")
        name, raw = pair
        value_type = raw_field_types.get(name)
        if not isinstance(value_type, str):
            raise GatewayInputError(
                f"Unknown object graph business field {name!r}; use a disclosed stable field"
            )
        if name in fields:
            raise GatewayInputError(f"Business field {name!r} was supplied twice")
        fields[name] = _parse_business_value(value_type, raw, field=name)
    if field_value_pairs:
        dynamic: dict[str, Any] = {}
        for pair in field_value_pairs:
            if len(pair) != 2:
                raise GatewayInputError(
                    "business --field-value requires FIELD_HANDLE VALUE"
                )
            handle, raw = pair
            if handle in dynamic:
                raise GatewayInputError("One Field Handle was supplied twice")
            bound = session.handles.bound_field(handle)
            dynamic[handle] = _parse_business_value(
                bound.value_type,
                raw,
                field="bound business field",
            )
        fields["field_values"] = dynamic
    return fields


def dispatch_offline_business_draft_update(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
) -> dict[str, Any]:
    store = OperationDraftStore(resolve_transaction_state_directory(args, env=env))
    inspected = store.inspect(
        args.draft_id,
        task_authority=args.task_authority,
    )
    if not operation_uses_business_declaration(
        inspected.operation,
        inspected.version,
    ):
        raise GatewayInputError("This Draft has no Business Declaration Adapter")
    adapter = business_adapter(inspected.operation)
    if not adapter.accepts_update_command(args.command):
        raise GatewayInputError(
            f"{inspected.operation} does not expose {args.command}"
        )
    if (
        getattr(args, "switch_value", None) is not None
        and adapter.family != "audio-import"
    ):
        raise GatewayInputError(
            "--switch-value is available only for audio.import business declarations"
        )
    raw_session = (
        inspected.composition.get("business_session")
        if inspected.composition is not None
        else None
    )
    if raw_session is None:
        raise GatewayInputError(
            "Bind one exact live project object before adding business declarations"
        )
    session = BusinessDeclarationSession.from_dict(raw_session)
    role_declaration = adapter.role_declaration
    if args.command == "draft-declare-import-batch":
        if adapter.family != "audio-import":
            raise GatewayInputError(
                "draft-declare-import-batch is available only for audio.import"
            )
        if args.expected_declaration_count < 1:
            raise GatewayInputError(
                "Expected declaration count must be at least one"
            )
        if args.expected_switch_assignment_count < 0:
            raise GatewayInputError(
                "Expected Switch assignment count cannot be negative"
            )

        row_specs: dict[str, tuple[str, tuple[str, ...]]] = {}

        def add_row(
            declaration_id: str,
            form: str,
            values: tuple[str, ...],
        ) -> None:
            if declaration_id in row_specs:
                raise GatewayInputError(
                    f"Import batch declaration id {declaration_id!r} was supplied twice"
                )
            row_specs[declaration_id] = (form, values)

        for declaration_id, parent_handle, name, kind in args.new_root_row:
            add_row(
                declaration_id,
                "new-root",
                (parent_handle, name, kind),
            )
        for declaration_id, parent_id, name, kind in args.new_child_row:
            add_row(
                declaration_id,
                "new-child",
                (parent_id, name, kind),
            )
        for declaration_id, parent_reference, name, kind in args.new_row:
            add_row(
                declaration_id,
                "new-auto",
                (parent_reference, name, kind),
            )
        for declaration_id, object_handle in args.existing_row:
            add_row(declaration_id, "existing", (object_handle,))

        row_order = list(args.row_order)
        if (
            len(row_order) != len(set(row_order))
            or set(row_order) != set(row_specs)
        ):
            raise GatewayInputError(
                "Import batch row order must name every supplied declaration exactly once"
            )
        if args.expected_declaration_count != len(row_order):
            raise GatewayInputError(
                "Expected declaration count does not match the complete import batch"
            )
        for declaration_id, (form, values) in tuple(row_specs.items()):
            if form != "new-auto":
                continue
            parent_reference, name, kind = values
            row_specs[declaration_id] = (
                (
                    "new-child"
                    if parent_reference in row_specs
                    else "new-root"
                ),
                (parent_reference, name, kind),
            )

        fields_by_id: dict[str, list[tuple[str, str]]] = {}
        field_values_by_id: dict[str, list[tuple[str, str]]] = {}
        switch_values: dict[str, str] = {}
        events: dict[str, tuple[str, str, str]] = {}
        for declaration_id, field_name, value in args.field:
            fields_by_id.setdefault(declaration_id, []).append(
                (field_name, value)
            )
        if args.media_file and args.media_directory is None:
            raise GatewayInputError(
                "Import batch media files require one absolute media directory"
            )
        if args.media_directory is not None and not args.media_file:
            raise GatewayInputError(
                "Import batch media directory requires at least one media file"
            )
        media_file_ids: set[str] = set()
        if args.media_directory is not None:
            media_directory = Path(args.media_directory)
            if (
                not media_directory.is_absolute()
                or ".." in media_directory.parts
                or not media_directory.is_dir()
            ):
                raise GatewayInputError(
                    "Import batch media directory must be one existing absolute directory without traversal"
                )
            for declaration_id, file_name in args.media_file:
                if (
                    not file_name
                    or file_name in {".", ".."}
                    or "/" in file_name
                    or "\\" in file_name
                    or "\x00" in file_name
                ):
                    raise GatewayInputError(
                        "Import batch media file name must be one leaf name without separators or traversal"
                    )
                if declaration_id in media_file_ids:
                    raise GatewayInputError(
                        f"Import batch media file for {declaration_id!r} was supplied twice"
                    )
                if any(
                    field_name == "media_file"
                    for field_name, _value in fields_by_id.get(
                        declaration_id,
                        [],
                    )
                ):
                    raise GatewayInputError(
                        f"Import batch media file for {declaration_id!r} has two transports"
                    )
                media_file_ids.add(declaration_id)
                fields_by_id.setdefault(declaration_id, []).append(
                    ("media_file", str(media_directory / file_name))
                )
        for declaration_id, field_handle, value in args.field_value:
            field_values_by_id.setdefault(declaration_id, []).append(
                (field_handle, value)
            )
        for declaration_id, value in args.switch_value:
            if declaration_id in switch_values:
                raise GatewayInputError(
                    f"Import batch Switch value for {declaration_id!r} was supplied twice"
                )
            switch_values[declaration_id] = value
        for declaration_id, parent_handle, name, action in args.event:
            if declaration_id in events:
                raise GatewayInputError(
                    f"Import batch Event for {declaration_id!r} was supplied twice"
                )
            if action not in {"Play", "Stop", "Pause", "Resume", "Break", "Seek"}:
                raise GatewayInputError(
                    f"Import batch Event action {action!r} is not supported"
                )
            events[declaration_id] = (parent_handle, name, action)

        supplied_fact_ids = (
            set(fields_by_id)
            | set(field_values_by_id)
            | set(switch_values)
            | set(events)
        )
        unknown_fact_ids = supplied_fact_ids - set(row_specs)
        if unknown_fact_ids:
            raise GatewayInputError(
                "Import batch fields reference an unknown declaration id"
            )
        if args.expected_switch_assignment_count != len(switch_values):
            raise GatewayInputError(
                "Expected Switch assignment count does not match the complete import batch"
            )

        def update(
            current: BusinessDeclarationSession,
        ) -> BusinessDeclarationSession:
            candidate = current
            for declaration_id in row_order:
                form, values = row_specs[declaration_id]
                event = events.get(declaration_id)
                fields = _parse_audio_import_business_fields(
                    candidate,
                    fields_by_id.get(declaration_id, []),
                    switch_value=switch_values.get(declaration_id),
                    allow_switch_value_pair=False,
                    field_value_pairs=field_values_by_id.get(
                        declaration_id,
                        [],
                    ),
                    event_parent_handle=None if event is None else event[0],
                    event_name=None if event is None else event[1],
                    event_action=None if event is None else event[2],
                )
                if form == "new-root":
                    parent_handle, name, kind = values
                    target = NewDescendantTarget(
                        parent_handle=parent_handle,
                        name=name,
                        kind=kind,
                    )
                    candidate = candidate.with_new_declaration(
                        declaration_id=declaration_id,
                        target=target,
                        fields=fields,
                    )
                elif form == "new-child":
                    parent_id, name, kind = values
                    parent_matches = [
                        row
                        for row in candidate.declarations
                        if row.declaration_id == parent_id
                    ]
                    if len(parent_matches) != 1:
                        raise business_repair(
                            "BATCH_PARENT_NOT_AVAILABLE",
                            field="parent_declaration_id",
                            draft_revision=current.revision,
                            action=(
                                "put each parent before its children in --row-order"
                            ),
                        )
                    candidate = candidate.with_new_declaration(
                        declaration_id=declaration_id,
                        target=NewDescendantTarget(
                            parent_handle=parent_matches[0].result_handle,
                            name=name,
                            kind=kind,
                        ),
                        fields=fields,
                    )
                else:
                    (object_handle,) = values
                    candidate = candidate.with_existing_declaration(
                        declaration_id=declaration_id,
                        target=ExistingObjectTarget(object_handle),
                        fields=fields,
                    )
            adapter.materialize(candidate)
            return candidate

        event_type = "declaration.batch-added"
    elif args.command == "draft-add-media":
        media_row = {
            name: value
            for name, value in (
                ("media_file", args.media_file),
                ("inline_wav", args.inline_wav),
                ("kind", args.kind),
                ("language", args.language),
                ("originals_subfolder", args.originals_subfolder),
            )
            if value is not None
        }

        def update(
            current: BusinessDeclarationSession,
        ) -> BusinessDeclarationSession:
            matches = [
                row
                for row in current.declarations
                if row.declaration_id == args.declaration_id
            ]
            if len(matches) != 1:
                raise business_repair(
                    "DECLARATION_NOT_AVAILABLE",
                    field="declaration_id",
                    draft_revision=current.revision,
                    action="use one declaration id from the current task",
                )
            fields = dict(matches[0].fields)
            raw_media = fields.get("media_files", [])
            if not isinstance(raw_media, list):  # pragma: no cover - state invariant
                raise RuntimeError("business media_files state must be a list")
            fields["media_files"] = [*raw_media, media_row]
            candidate = current.revise_declaration(
                declaration_id=args.declaration_id,
                fields=fields,
            )
            adapter.materialize(candidate)
            return candidate

        event_type = "declaration.revised"
    elif args.command == "draft-clear-object-list":
        existing = [
            row
            for row in session.declarations
            if row.declaration_id == args.declaration_id
        ]
        if len(existing) > 1:  # pragma: no cover - session invariant
            raise RuntimeError("business declaration id is not unique")

        def update(
            current: BusinessDeclarationSession,
        ) -> BusinessDeclarationSession:
            matches = [
                row
                for row in current.declarations
                if row.declaration_id == args.declaration_id
            ]
            if not matches:
                candidate = current.with_existing_declaration(
                    declaration_id=args.declaration_id,
                    target=ExistingObjectTarget(args.object_handle),
                    fields={
                        "clear_object_lists": [args.list_name],
                        "list_behavior": "replace-all",
                    },
                )
            else:
                row = matches[0]
                if (
                    not isinstance(row.target, ExistingObjectTarget)
                    or row.target.object_handle != args.object_handle
                ):
                    raise business_repair(
                        "DECLARATION_TARGET_MISMATCH",
                        field="object_handle",
                        draft_revision=current.revision,
                        action="reuse this declaration id only for its exact bound owner",
                    )
                fields = dict(row.fields)
                raw_names = fields.get("clear_object_lists", [])
                if not isinstance(raw_names, list):  # pragma: no cover
                    raise RuntimeError("clear_object_lists state must be a list")
                fields["clear_object_lists"] = [*raw_names, args.list_name]
                fields["list_behavior"] = "replace-all"
                candidate = current.revise_declaration(
                    declaration_id=args.declaration_id,
                    fields=fields,
                )
            adapter.materialize(candidate)
            return candidate

        event_type = "declaration.revised" if existing else "declaration.added"
    elif args.command == "draft-declare-field-change":
        bound_field = session.handles.bound_field(args.field_handle)
        fields: dict[str, Any] = {"field_handle": args.field_handle}
        if args.business_value is not None:
            fields["business_value"] = _parse_business_value(
                bound_field.value_type,
                args.business_value,
                field="business_value",
            )
        elif args.target_handle is not None:
            fields["reference_outcome"] = args.target_handle
        elif args.clear_reference:
            fields["reference_outcome"] = "clear"
        elif args.link_state is not None:
            fields["link_state"] = args.link_state
        else:  # pragma: no cover - argparse requires one outcome
            raise GatewayInputError("Field change requires one business outcome")

        def update(
            current: BusinessDeclarationSession,
        ) -> BusinessDeclarationSession:
            candidate = current.with_existing_declaration(
                declaration_id="change",
                target=ExistingObjectTarget(args.object_handle),
                fields=fields,
            )
            adapter.materialize(candidate)
            return candidate

        event_type = "declaration.added"
    elif args.command == "draft-declare-rtpc":
        points: list[dict[str, Any]] = []
        for index, (raw_x, raw_y, shape) in enumerate(args.point):
            try:
                x = float(raw_x)
                y = float(raw_y)
            except ValueError as exc:
                raise GatewayInputError(
                    f"RTPC point {index} requires finite numeric X and Y values"
                ) from exc
            if not math.isfinite(x) or not math.isfinite(y):
                raise GatewayInputError(
                    f"RTPC point {index} requires finite numeric X and Y values"
                )
            points.append(
                {
                    "x": int(x) if x.is_integer() else x,
                    "y": int(y) if y.is_integer() else y,
                    "shape": shape,
                }
            )
        fields = {
            "control_input_handle": args.control_input_handle,
            "curve_points": points,
            "field_handle": args.field_handle,
            "mode": args.mode,
            **({} if args.notes is None else {"notes": args.notes}),
        }

        def update(
            current: BusinessDeclarationSession,
        ) -> BusinessDeclarationSession:
            candidate = current.with_existing_declaration(
                declaration_id="rtpc",
                target=ExistingObjectTarget(args.object_handle),
                fields=fields,
            )
            adapter.materialize(candidate)
            return candidate

        event_type = "declaration.added"
    elif args.command == "draft-declare-object-change":
        fields = {
            name: value
            for name, value in (
                ("parent_handle", args.parent_handle),
                ("new_name", args.new_name),
                ("notes", args.notes),
                ("name_conflict", args.name_conflict),
                ("add_to_source_control", args.add_to_source_control),
                (
                    "check_out_from_source_control",
                    args.check_out_from_source_control,
                ),
            )
            if value is not None
        }

        def update(
            current: BusinessDeclarationSession,
        ) -> BusinessDeclarationSession:
            candidate = current.with_existing_declaration(
                declaration_id="change",
                target=ExistingObjectTarget(args.object_handle),
                fields=fields,
            )
            adapter.materialize(candidate)
            return candidate

        event_type = "declaration.added"
    elif (
        role_declaration is not None
        and args.command == role_declaration.command
    ):
        values = {
            name: getattr(args, name)
            for name in role_declaration.required_fields
        }

        def update(
            current: BusinessDeclarationSession,
        ) -> BusinessDeclarationSession:
            candidate = role_declaration.update(current, values)
            adapter.materialize(candidate)
            return candidate

        event_type = "declaration.added"
    elif args.command == "draft-business-configure":
        settings: dict[str, Any] = {}
        if adapter.family == "object-creation-graph":
            names = (
                (
                    "add_to_source_control",
                    "list_behavior",
                    "name_conflict",
                )
                if inspected.operation == "object.set"
                else (
                    "add_to_source_control",
                    "name_conflict",
                    "platform",
                    "replace_owner_handle",
                )
            )
            for name in names:
                value = getattr(args, name)
                if value is not None:
                    settings[name] = value
        else:
            defaults = _parse_audio_import_business_fields(
                session,
                args.default,
                field_value_pairs=args.default_field_value,
                event_parent_handle=args.default_event_parent_handle,
                event_name=args.default_event_name,
                event_action=args.default_event_action,
            )
            if args.mode is not None:
                settings["mode"] = args.mode
            if args.add_to_source_control is not None:
                settings["add_to_source_control"] = args.add_to_source_control
            if args.check_out_from_source_control is not None:
                settings["check_out_from_source_control"] = (
                    args.check_out_from_source_control
                )
            if defaults:
                settings["defaults"] = defaults
        if not settings:
            raise GatewayInputError(
                "Business configuration requires at least one explicit batch setting"
            )
        def update(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
            candidate = current.with_settings(settings)
            if adapter.family == "object-creation-graph" and candidate.declarations:
                adapter.materialize(candidate)
            return candidate

        event_type = "settings.revised"
    elif args.command == "draft-remove-declaration":
        def update(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
            candidate = current.remove_declaration(args.declaration_id)
            if adapter.family == "object-creation-graph":
                adapter.materialize(candidate)
            return candidate

        event_type = "declaration.removed"
    else:
        fields = (
            _parse_object_graph_business_fields(
                session,
                inspected.operation,
                args.field,
                field_value_pairs=args.field_value,
            )
            if adapter.family == "object-creation-graph"
            else _parse_audio_import_business_fields(
                session,
                args.field,
                switch_value=args.switch_value,
                allow_switch_value_pair=False,
                field_value_pairs=args.field_value,
                event_parent_handle=args.event_parent_handle,
                event_name=args.event_name,
                event_action=args.event_action,
            )
        )
        if args.command == "draft-declare-new":
            def update(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
                candidate = current.with_new_declaration(
                    declaration_id=args.declaration_id,
                    target=NewDescendantTarget(
                        parent_handle=args.parent_handle,
                        name=args.name,
                        kind=args.kind,
                    ),
                    fields=fields,
                )
                if adapter.family == "object-creation-graph":
                    adapter.materialize(candidate)
                return candidate

            event_type = "declaration.added"
        elif args.command == "draft-declare-existing":
            def update(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
                candidate = current.with_existing_declaration(
                    declaration_id=args.declaration_id,
                    target=ExistingObjectTarget(args.object_handle),
                    fields=fields,
                )
                if adapter.family == "object-creation-graph":
                    adapter.materialize(candidate)
                return candidate

            event_type = "declaration.added"
        else:
            def update(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
                candidate = current.revise_declaration(
                    declaration_id=args.declaration_id,
                    fields=fields,
                )
                if adapter.family == "object-creation-graph":
                    adapter.materialize(candidate)
                return candidate

            event_type = "declaration.revised"
    schema_digest = operation_draft_schema_digest(
        inspected.operation,
        inspected.version,
    )
    composer_digest = operation_composer_digest(
        inspected.operation,
        inspected.version,
    )
    record = store.apply_business_update(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        context=session.context,
        update=update,
        event_type=event_type,
    )
    return operation_draft_payload(
        args.command,
        record,
        task_authority=args.task_authority,
    )


def dispatch_business_soundbank_plan(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind and validate one complete SoundBank plan without dispatching it."""

    binding = _open_business_binding(
        args,
        env=env,
        connection=connection,
        detected_version=detected_version,
        live_info=live_info,
        dispatcher=dispatcher,
    )
    adapter = business_adapter(binding.record.operation)
    if not adapter.accepts_update_command(args.command):
        raise GatewayInputError(
            f"{binding.record.operation} does not expose {args.command}"
        )
    raw_session = (
        binding.record.composition.get("business_session")
        if binding.record.composition is not None
        else None
    )
    session = (
        BusinessDeclarationSession.create(binding.context)
        if raw_session is None
        else BusinessDeclarationSession.from_dict(raw_session)
    )
    if session.context != binding.context:
        raise OperationDraftBindingDrift(
            "Live project or Wwise build differs from the SoundBank plan binding."
        )
    try:
        plan = soundbank_plan_from_namespace(
            args,
            operation=binding.record.operation,
        )
    except SoundBankBusinessCliError as exc:
        raise GatewayInputError(str(exc)) from exc

    def update(
        current: BusinessDeclarationSession,
    ) -> BusinessDeclarationSession:
        candidate = current.with_settings({"soundbank_plan": plan})
        adapter.materialize(candidate)
        return candidate

    record = binding.store.apply_business_update(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=operation_draft_schema_digest(
            binding.record.operation,
            detected_version,
        ),
        composer_digest=operation_composer_digest(
            binding.record.operation,
            detected_version,
        ),
        context=binding.context,
        update=update,
        event_type="settings.revised",
    )
    payload = operation_draft_payload(
        args.command,
        record,
        offline=False,
        task_authority=args.task_authority,
    )
    payload.update(
        {
            "endpoint": dict(common["endpoint"]),
            "detected_version": detected_version,
            "project_call": dispatch_call_summary(binding.project_call),
        }
    )
    return payload


def dispatch_business_exact_artifact_plan(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind one exact artifact plan without exposing its native loader."""

    state_dir = resolve_transaction_state_directory(args, env=env)
    pending = OperationDraftStore(state_dir).inspect(
        args.draft_id,
        task_authority=args.task_authority,
    )
    if (
        pending.operation == "lua.executeCliFile"
        and live_info.get("isCommandLine") is not True
    ):
        return command_line_host_required_payload(
            command=args.command,
            live_info=live_info,
            common=common,
            operation=pending.operation,
        )

    binding = _open_business_binding(
        args,
        env=env,
        connection=connection,
        detected_version=detected_version,
        live_info=live_info,
        dispatcher=dispatcher,
    )
    adapter = business_adapter(binding.record.operation)
    if not adapter.accepts_update_command(args.command):
        raise GatewayInputError(
            f"{binding.record.operation} does not expose {args.command}"
        )
    raw_session = (
        binding.record.composition.get("business_session")
        if binding.record.composition is not None
        else None
    )
    session = (
        BusinessDeclarationSession.create(binding.context)
        if raw_session is None
        else BusinessDeclarationSession.from_dict(raw_session)
    )
    if session.context != binding.context:
        raise OperationDraftBindingDrift(
            "Live project or Wwise build differs from the artifact plan binding."
        )
    try:
        plan = exact_artifact_plan_from_namespace(
            args,
            operation=binding.record.operation,
        )
    except ExactArtifactBusinessCliError as exc:
        raise GatewayInputError(str(exc)) from exc

    def update(
        current: BusinessDeclarationSession,
    ) -> BusinessDeclarationSession:
        provisional = current.with_settings({"artifact_plan": plan})
        request = adapter.materialize(provisional)
        settings: dict[str, Any] = {"artifact_plan": plan}
        evidence = exact_artifact_evidence_from_request(
            binding.record.operation,
            request,
        )
        if evidence is not None:
            settings["artifact_evidence"] = evidence
        candidate = current.with_settings(settings)
        adapter.materialize(candidate)
        return candidate

    record = binding.store.apply_business_update(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=operation_draft_schema_digest(
            binding.record.operation,
            detected_version,
        ),
        composer_digest=operation_composer_digest(
            binding.record.operation,
            detected_version,
        ),
        context=binding.context,
        update=update,
        event_type="settings.revised",
    )
    payload = operation_draft_payload(
        args.command,
        record,
        offline=False,
        task_authority=args.task_authority,
    )
    payload.update(
        {
            "endpoint": dict(common["endpoint"]),
            "detected_version": detected_version,
            "project_call": dispatch_call_summary(binding.project_call),
        }
    )
    return payload


def dispatch_business_authoring_ui_update(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Record one closed Authoring UI plan stage on an Authoring host."""

    state_dir = resolve_transaction_state_directory(args, env=env)
    pending = OperationDraftStore(state_dir).inspect(
        args.draft_id,
        task_authority=args.task_authority,
    )
    if live_info.get("isCommandLine") is not False:
        return authoring_host_required_payload(
            api=None,
            command=args.command,
            live_info=live_info,
            common=common,
            operation=pending.operation,
        )
    binding = _open_business_binding(
        args,
        env=env,
        connection=connection,
        detected_version=detected_version,
        live_info=live_info,
        dispatcher=dispatcher,
    )
    adapter = business_adapter(binding.record.operation)
    if adapter.family != "authoring-ui-business" or not adapter.accepts_update_command(
        args.command
    ):
        raise GatewayInputError(
            f"{binding.record.operation} does not expose {args.command}"
        )
    raw_session = (
        binding.record.composition.get("business_session")
        if binding.record.composition is not None
        else None
    )
    session = (
        BusinessDeclarationSession.create(binding.context)
        if raw_session is None
        else BusinessDeclarationSession.from_dict(raw_session)
    )
    if session.context != binding.context:
        raise OperationDraftBindingDrift(
            "Live project or Wwise build differs from the Authoring UI plan binding."
        )
    try:
        if args.command == "draft-declare-ui-plan":
            plan = authoring_ui_plan_from_namespace(
                args,
                operation=binding.record.operation,
            )

            def update(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
                candidate = current.with_settings({"ui_plan": plan})
                validate_authoring_ui_business_session(
                    binding.record.operation,
                    candidate,
                )
                if adapter.is_complete(candidate):
                    parse_operation_request(
                        adapter.materialize(candidate),
                        expected_version=detected_version,
                    )
                return candidate

        else:
            if binding.record.operation != "ui.commands.register":
                raise GatewayInputError(
                    "draft-add-ui-command is available only for ui.commands.register"
                )
            command = authoring_ui_command_from_namespace(args)

            def update(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
                candidate = append_authoring_ui_command(current, command)
                validate_authoring_ui_business_session(
                    binding.record.operation,
                    candidate,
                )
                if adapter.is_complete(candidate):
                    parse_operation_request(
                        adapter.materialize(candidate),
                        expected_version=detected_version,
                    )
                return candidate

    except AuthoringUiBusinessCliError as exc:
        raise GatewayInputError(str(exc)) from exc
    record = binding.store.apply_business_update(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=operation_draft_schema_digest(
            binding.record.operation,
            detected_version,
        ),
        composer_digest=operation_composer_digest(
            binding.record.operation,
            detected_version,
        ),
        context=binding.context,
        update=update,
        event_type="settings.revised",
    )
    payload = operation_draft_payload(
        args.command,
        record,
        offline=False,
        task_authority=args.task_authority,
    )
    payload.update(
        {
            "endpoint": dict(common["endpoint"]),
            "detected_version": detected_version,
            "project_call": dispatch_call_summary(binding.project_call),
        }
    )
    return payload


def dispatch_business_debug_intent(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Record one closed Debug business intent without native request fields."""

    binding = _open_business_binding(
        args,
        env=env,
        connection=connection,
        detected_version=detected_version,
        live_info=live_info,
        dispatcher=dispatcher,
    )
    adapter = business_adapter(binding.record.operation)
    if adapter.family != "debug-host-control" or not adapter.accepts_update_command(
        args.command
    ):
        raise GatewayInputError(
            f"{binding.record.operation} does not expose {args.command}"
        )
    raw_session = (
        binding.record.composition.get("business_session")
        if binding.record.composition is not None
        else None
    )
    session = (
        BusinessDeclarationSession.create(binding.context)
        if raw_session is None
        else BusinessDeclarationSession.from_dict(raw_session)
    )
    if session.context != binding.context:
        raise OperationDraftBindingDrift(
            "Live project or Wwise build differs from the Debug intent binding."
        )
    try:
        intent = debug_intent_from_namespace(
            args,
            operation=binding.record.operation,
        )
    except DebugBusinessCliError as exc:
        raise GatewayInputError(str(exc)) from exc

    def update(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
        candidate = current.with_settings({"debug_intent": intent})
        parse_operation_request(
            adapter.materialize(candidate),
            expected_version=detected_version,
        )
        return candidate

    record = binding.store.apply_business_update(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=operation_draft_schema_digest(
            binding.record.operation,
            detected_version,
        ),
        composer_digest=operation_composer_digest(
            binding.record.operation,
            detected_version,
        ),
        context=binding.context,
        update=update,
        event_type="settings.revised",
    )
    payload = operation_draft_payload(
        args.command,
        record,
        offline=False,
        task_authority=args.task_authority,
    )
    payload.update(
        {
            "endpoint": dict(common["endpoint"]),
            "detected_version": detected_version,
            "project_call": dispatch_call_summary(binding.project_call),
        }
    )
    return payload


def dispatch_business_compound_undo_plan(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Snapshot one ordered list of already checked child Business Drafts."""

    binding = _open_business_binding(
        args,
        env=env,
        connection=connection,
        detected_version=detected_version,
        live_info=live_info,
        dispatcher=dispatcher,
    )
    adapter = business_adapter(binding.record.operation)
    if adapter.family != "compound-undo-business" or not adapter.accepts_update_command(
        args.command
    ):
        raise GatewayInputError(
            f"{binding.record.operation} does not expose {args.command}"
        )
    child_bindings = args.child_draft
    if (
        not isinstance(child_bindings, list)
        or not 1 <= len(child_bindings) <= UNDO_GROUP_MAX_CALLS
    ):
        raise GatewayInputError(
            "Compound Undo requires between 1 and "
            f"{UNDO_GROUP_MAX_CALLS} checked child Drafts"
        )
    current_project_guard = build_project_guard(
        endpoint=common["endpoint"],
        version=detected_version,
        live_info=live_info,
        project=binding.project,
    )
    try:
        checked_child_bindings = tuple(
            CheckedChildDraftBinding.from_cli_pair(pair, index=index)
            for index, pair in enumerate(child_bindings)
        )
    except ValueError as exc:
        raise GatewayInputError(str(exc)) from exc
    try:
        snapshots = snapshot_checked_compound_undo_children(
            CompoundUndoSnapshotScope(
                store=binding.store,
                parent_draft_id=binding.record.draft_id,
                parent_context=binding.context,
                project_guard=current_project_guard,
                version=detected_version,
                schema_digest_for=operation_draft_schema_digest,
                composer_digest_for=operation_composer_digest,
            ),
            checked_child_bindings,
        )
    except ValueError as exc:
        raise GatewayInputError(str(exc)) from exc

    def update(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
        candidate = current.with_settings(
            {
                "undo_plan": {
                    "display_name": args.display_name,
                    "children": snapshots,
                }
            }
        )
        parse_operation_request(
            adapter.materialize(candidate),
            expected_version=detected_version,
        )
        return candidate

    record = binding.store.apply_business_update(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=operation_draft_schema_digest(
            binding.record.operation,
            detected_version,
        ),
        composer_digest=operation_composer_digest(
            binding.record.operation,
            detected_version,
        ),
        context=binding.context,
        update=update,
        event_type="settings.revised",
    )
    payload = operation_draft_payload(
        args.command,
        record,
        offline=False,
        task_authority=args.task_authority,
    )
    payload.update(
        {
            "endpoint": dict(common["endpoint"]),
            "detected_version": detected_version,
            "project_call": dispatch_call_summary(binding.project_call),
        }
    )
    return payload


def _business_context_from_live(
    *,
    task_authority: str,
    project: Mapping[str, Any],
    detected_version: str,
    live_info: Mapping[str, Any],
) -> BusinessContext:
    version = live_info.get("version")
    display_name = version.get("displayName") if isinstance(version, Mapping) else None
    if not isinstance(display_name, str) or not display_name:
        raise GatewayResultShapeError(
            "Live Wwise build identity is unavailable for business handle binding.",
            details={"required_field": "version.displayName"},
            error_code="INVALID_STATUS_RESULT",
        )
    return BusinessContext.create(
        task_authority=task_authority,
        project_id=str(project["id"]),
        project_path=str(project["path"]),
        wwise_version=detected_version,
        wwise_build=display_name,
    )


def _business_object_path_from_segments(values: Any) -> str:
    if (
        not isinstance(values, list)
        or not 1 <= len(values) <= MAX_BUSINESS_OBJECT_PATH_SEGMENTS
    ):
        raise GatewayInputError(
            "Business object path requires 1.."
            f"{MAX_BUSINESS_OBJECT_PATH_SEGMENTS} ordered path segments."
        )
    segments: list[str] = []
    for value in values:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value.encode("utf-8")) > MAX_BUSINESS_NAME_BYTES
            or "\\" in value
            or "/" in value
            or '"' in value
            or any(
                ord(character) < 32
                or ord(character) == 127
                or character in {"\u2028", "\u2029"}
                for character in value
            )
        ):
            raise GatewayInputError(
                "Each business object path segment must be one bounded literal name "
                "without a path separator."
            )
        segments.append(value)
    path = "\\" + "\\".join(segments)
    if len(path.encode("utf-8")) > MAX_BUSINESS_PATH_BYTES:
        raise GatewayInputError(
            "Business object path segments exceed the fixed path byte limit."
        )
    return path


@dataclass(frozen=True, slots=True)
class _BusinessBinding:
    state_dir: Path
    store: OperationDraftStore
    record: OperationDraftRecord
    project: Mapping[str, Any]
    project_call: Any
    context: BusinessContext
    read_call: Callable[[str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]


def _open_business_binding(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
) -> _BusinessBinding:
    state_dir = resolve_transaction_state_directory(args, env=env)
    store = OperationDraftStore(state_dir)
    record = store.inspect(args.draft_id, task_authority=args.task_authority)
    if not operation_uses_business_declaration(
        record.operation,
        record.version,
    ):
        raise GatewayInputError("This Draft has no Business Declaration Adapter")
    if record.version != detected_version:
        raise OperationDraftBindingDrift(
            "Operation Draft version does not match the connected Wwise version."
        )
    project, project_call = current_project(
        dispatcher,
        connection=connection,
        version=detected_version,
    )
    assert project is not None
    context = _business_context_from_live(
        task_authority=args.task_authority,
        project=project,
        detected_version=detected_version,
        live_info=live_info,
    )
    return _BusinessBinding(
        state_dir=state_dir,
        store=store,
        record=record,
        project=project,
        project_call=project_call,
        context=context,
        read_call=transaction_read_call(
            dispatcher,
            connection=connection,
            version=detected_version,
        ),
    )


def dispatch_business_object_binding(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    binding = _open_business_binding(
        args,
        env=env,
        connection=connection,
        detected_version=detected_version,
        live_info=live_info,
        dispatcher=dispatcher,
    )
    adapter = business_adapter(binding.record.operation)
    role_declaration = adapter.role_declaration
    if role_declaration is None:
        business_contract = adapter.contract(detected_version)
        contract_binding = business_contract.get("binding")
        contract_roles = (
            tuple(contract_binding.get("roles", ()))
            if isinstance(contract_binding, Mapping)
            else ()
        )
        role_required = (
            contract_binding.get("role_required") is True
            if isinstance(contract_binding, Mapping)
            else False
        )
        if (
            isinstance(contract_binding, Mapping)
            and contract_binding.get("available") is False
        ):
            raise GatewayInputError(
                f"Business object roles are unavailable for {binding.record.operation}"
            )
        if args.role is not None and not contract_roles:
            raise GatewayInputError(
                f"Business object roles are unavailable for {binding.record.operation}"
            )
        if args.role is not None and args.role not in contract_roles:
            raise GatewayInputError(
                "Business object binding requires one disclosed role: "
                + ", ".join(contract_roles)
            )
        if role_required and args.role is None:
            raise GatewayInputError(
                "Business object binding requires one disclosed role: "
                + ", ".join(contract_roles)
            )
    else:
        raw_session = (
            binding.record.composition.get("business_session")
            if binding.record.composition is not None
            else None
        )
        bound_count = (
            0
            if raw_session is None
            else len(
                BusinessDeclarationSession.from_dict(raw_session).handles.as_dict()[
                    "objects"
                ]
            )
        )
        if bound_count >= len(role_declaration.roles):
            raise GatewayInputError(
                "Every business object role is already bound; submit the declaration"
            )
        expected_role = role_declaration.roles[bound_count]
        if args.role != expected_role:
            raise GatewayInputError(
                f"The next business object binding requires --role {expected_role}"
            )
    object_path = args.object_path
    if args.object_path_segment is not None:
        object_path = _business_object_path_from_segments(args.object_path_segment)
    exact_type_name: tuple[str, str] | None = None
    if args.exact_type_name is not None:
        try:
            identity = normalize_object_identity(
                {
                    "kind": "exact-type-name",
                    "type": args.exact_type_name[0],
                    "name": args.exact_type_name[1],
                },
                path="draft-bind-object.exact-type-name",
            )
        except ObjectOperationContractError as exc:
            raise GatewayInputError(str(exc)) from exc
        assert identity.type is not None and identity.name is not None
        exact_type_name = (identity.type, identity.name)
    if args.object_id is not None:
        selector = {"from": {"id": [args.object_id]}}
    elif object_path is not None:
        selector = {"from": {"path": [object_path]}}
    elif exact_type_name is not None:
        object_type, object_name = exact_type_name
        selector = {
            "waql": (
                f"from type {object_type} where name = "
                f"{quote_waql_literal(object_name)} take 2"
            )
        }
    else:
        raise GatewayInputError(
            "Business object binding requires an exact GUID, path, or typed name"
        )
    raw = binding.read_call(
        OBJECT_GET_URI,
        selector,
        {"return": ["id", "name", "type", "path"]},
    )
    rows = raw.get("return")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        candidates = [
            {
                field: row[field]
                for field in ("id", "name", "type", "path")
                if field in row
            }
            for row in (rows[:2] if isinstance(rows, list) else [])
            if isinstance(row, Mapping)
        ]
        raise GatewayResultShapeError(
            "Exact business object binding requires one live Wwise object row.",
            details={
                "actual_count": len(rows) if isinstance(rows, list) else None,
                "candidates": candidates,
            },
            error_code="BUSINESS_OBJECT_NOT_UNIQUE",
        )
    row = dict(rows[0])
    if (
        not _canonical_guid(row.get("id"))
        or not all(
            isinstance(row.get(field), str) and bool(str(row.get(field)).strip())
            for field in ("name", "type", "path")
        )
        or (args.object_id is not None and str(row["id"]).upper() != args.object_id.upper())
        or (object_path is not None and row["path"] != object_path)
        or (
            exact_type_name is not None
            and (row["type"], row["name"]) != exact_type_name
        )
    ):
        raise GatewayResultShapeError(
            "Live business object row does not match its exact selector.",
            details={"required_fields": ["id", "name", "type", "path"]},
            error_code="BUSINESS_OBJECT_BINDING_MISMATCH",
        )
    semantic_kind: str | None = None
    if adapter.requires_sound_subtype and str(row["type"]).casefold() == "sound":
        subtype_raw = binding.read_call(
            OBJECT_GET_URI,
            {"from": {"id": [str(row["id"])]}},
            {"return": ["id", "@IsVoice"]},
        )
        subtype_rows = subtype_raw.get("return")
        if (
            not isinstance(subtype_rows, list)
            or len(subtype_rows) != 1
            or not isinstance(subtype_rows[0], Mapping)
            or str(subtype_rows[0].get("id", "")).upper()
            != str(row["id"]).upper()
            or type(subtype_rows[0].get("@IsVoice")) is not bool
        ):
            raise GatewayResultShapeError(
                "Live Sound binding requires one exact IsVoice readback.",
                details={"required_fields": ["id", "@IsVoice"]},
                error_code="BUSINESS_OBJECT_SUBTYPE_UNRESOLVED",
            )
        semantic_kind = (
            "sound-voice" if subtype_rows[0]["@IsVoice"] else "sound-sfx"
        )
    captured: list[Any] = []

    def bind(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
        handles = BusinessHandleRegistry.from_dict(current.handles.as_dict())
        bound = handles.bind_object(
            object_id=str(row["id"]),
            name=str(row["name"]),
            object_type=str(row["type"]),
            path=str(row["path"]),
            semantic_kind=semantic_kind,
            role=args.role,
        )
        captured.append(bound)
        return current.with_handle_registry(handles)

    schema_digest = operation_draft_schema_digest(
        binding.record.operation,
        detected_version,
    )
    composer_digest = operation_composer_digest(
        binding.record.operation,
        detected_version,
    )
    record = binding.store.apply_business_update(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        context=binding.context,
        update=bind,
        event_type="handles.bound",
    )
    bound = captured[0]
    payload = operation_draft_payload(
        args.command,
        record,
        offline=False,
        task_authority=args.task_authority,
    )
    payload.update(
        {
            "endpoint": dict(common["endpoint"]),
            "detected_version": detected_version,
            "project_call": dispatch_call_summary(binding.project_call),
            "bound_object": {
                "handle": bound.handle,
                "name": bound.name,
                "type": bound.object_type,
                "semantic_kind": bound.semantic_kind,
                **({} if bound.role is None else {"role": bound.role}),
            },
        }
    )
    return payload


def dispatch_business_field_binding(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    binding = _open_business_binding(
        args,
        env=env,
        connection=connection,
        detected_version=detected_version,
        live_info=live_info,
        dispatcher=dispatcher,
    )
    adapter = business_adapter(binding.record.operation)
    if not adapter.supports_field_binding:
        raise GatewayInputError(
            f"Custom field binding is unavailable for {binding.record.operation}"
        )
    raw_session = (
        binding.record.composition.get("business_session")
        if binding.record.composition is not None
        else None
    )
    if raw_session is None:
        raise GatewayInputError("Bind one exact object before binding custom fields")
    session = BusinessDeclarationSession.from_dict(raw_session)
    if binding.context != session.context:
        raise OperationDraftBindingDrift(
            "Live project or Wwise build differs from the business declaration binding."
        )
    if args.object_handle is not None:
        scope_kind = "object"
        scope_value: str | int = session.handles.resolve_object(
            args.object_handle
        ).object_id
    else:
        scope_kind = "class"
        scope_value = args.class_name
    read_call = metadata_cached_read_call(
        binding.read_call,
        connection=connection,
        version=detected_version,
        live_info=live_info,
        project=binding.project,
        state_dir=binding.state_dir,
    )
    captured: list[Any] = []

    def bind(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
        handles = BusinessHandleRegistry.from_dict(current.handles.as_dict())
        bound = bind_live_field(
            handles,
            read_call=read_call,
            scope_kind=scope_kind,
            scope_value=scope_value,
            token=args.token,
            platform=args.platform,
        )
        captured.append(bound)
        return current.with_handle_registry(handles)

    schema_digest = operation_draft_schema_digest(
        binding.record.operation,
        detected_version,
    )
    composer_digest = operation_composer_digest(
        binding.record.operation,
        detected_version,
    )
    record = binding.store.apply_business_update(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        context=binding.context,
        update=bind,
        event_type="handles.bound",
    )
    bound = captured[0]
    payload = operation_draft_payload(
        args.command,
        record,
        offline=False,
        task_authority=args.task_authority,
    )
    payload.update(
        {
            "endpoint": dict(common["endpoint"]),
            "detected_version": detected_version,
            "project_call": dispatch_call_summary(binding.project_call),
            "bound_field": {
                "handle": bound.handle,
                "token": bound.token,
                "field_kind": bound.field_kind,
                "value_type": bound.value_type,
                "platform": bound.platform,
                "restrictions": dict(bound.restrictions),
            },
        }
    )
    return payload


def dispatch_business_field_discovery(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind bounded live candidates without accepting a model-authored token."""

    binding = _open_business_binding(
        args,
        env=env,
        connection=connection,
        detected_version=detected_version,
        live_info=live_info,
        dispatcher=dispatcher,
    )
    adapter = business_adapter(binding.record.operation)
    if not adapter.supports_field_discovery:
        raise GatewayInputError(
            f"Business field discovery is unavailable for {binding.record.operation}"
        )
    raw_session = (
        binding.record.composition.get("business_session")
        if binding.record.composition is not None
        else None
    )
    if raw_session is None:
        raise GatewayInputError("Bind the exact target object before field discovery")
    session = BusinessDeclarationSession.from_dict(raw_session)
    if binding.context != session.context:
        raise OperationDraftBindingDrift(
            "Live project or Wwise build differs from the business declaration binding."
        )
    source = None
    if args.object_handle is not None:
        source = session.handles.resolve_object(args.object_handle)
        scope_kind = "object"
        scope_value: str | int = source.object_id
        discovery_scope = {"object": source.object_id}
    elif args.type_handle is not None:
        bound_type = session.handles.resolve_type(args.type_handle)
        scope_kind = "class"
        scope_value = bound_type.class_id
        discovery_scope = {"class_id": bound_type.class_id}
    else:
        kind = resolve_semantic_kind(
            args.semantic_kind,
            version=detected_version,
        )
        scope_kind = "class"
        scope_value = kind.metadata_object_type
        discovery_scope = {"object_type": kind.metadata_object_type}
    if (
        binding.record.operation
        in {"object.setLinked", "object.setProperty", "object.setReference", "object.setRTPC"}
        and source is None
    ):
        raise GatewayInputError(
            f"{binding.record.operation} field discovery requires its exact bound object"
        )
    if binding.record.operation == "object.setLinked" and args.platform is None:
        raise GatewayInputError(
            "object.setLinked field discovery requires one explicit platform"
        )
    read_call = metadata_cached_read_call(
        binding.read_call,
        connection=connection,
        version=detected_version,
        live_info=live_info,
        project=binding.project,
        state_dir=binding.state_dir,
    )
    discovery = discover_metadata(
        read_call=read_call,
        queries=tuple(args.meanings),
        **discovery_scope,
        limit=MAX_METADATA_DISCOVERY_LIMIT,
    )
    eligible: list[Mapping[str, Any]] = []
    for candidate in discovery.candidates:
        kind = candidate.get("kind")
        metadata = candidate.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        value_type = metadata_typed_value_type(str(metadata.get("type", "")))
        if binding.record.operation == "object.setProperty":
            accepted = kind == "property" and value_type is not None
        elif binding.record.operation == "object.setReference":
            accepted = kind == "reference"
        elif binding.record.operation == "object.setRTPC":
            supports = metadata.get("supports")
            rtpc = supports.get("rtpc") if isinstance(supports, Mapping) else None
            accepted = (
                kind == "property"
                and value_type in {"number", "integer"}
                and rtpc not in {None, False, "", "None", "none"}
            )
        elif binding.record.operation == "object.set":
            accepted = (
                (kind == "property" and value_type is not None)
                or kind == "reference"
            )
        elif binding.record.operation == "object.createPlugin":
            accepted = kind == "property" and value_type is not None
        elif binding.record.operation == "object.create":
            accepted = (
                (kind == "property" and value_type is not None)
                or kind == "reference"
            )
        else:
            supports = metadata.get("supports")
            accepted = (
                kind in {"property", "reference"}
                and (kind == "reference" or value_type is not None)
                and isinstance(supports, Mapping)
                and supports.get("unlink") is True
            )
        if accepted:
            eligible.append(candidate)
    if not eligible:
        raise GatewayInputError(
            "Live field discovery found no candidate compatible with this operation"
        )

    captured: list[Any] = []
    rejected: list[Mapping[str, Any]] = []
    rejected_errors: list[BusinessDeclarationError] = []

    def bind(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
        handles = BusinessHandleRegistry.from_dict(current.handles.as_dict())
        for candidate in eligible:
            try:
                captured.append(
                    bind_live_field(
                        handles,
                        read_call=read_call,
                        scope_kind=scope_kind,
                        scope_value=scope_value,
                        token=str(candidate["name"]),
                        platform=args.platform,
                    )
                )
            except BusinessDeclarationError as exc:
                rejected_errors.append(exc)
                rejected.append(
                    {
                        "error_code": exc.error_code,
                        "field_kind": candidate.get("kind"),
                    }
                )
        if not captured:
            raise rejected_errors[0]
        return current.with_handle_registry(handles)

    schema_digest = operation_draft_schema_digest(
        binding.record.operation,
        detected_version,
    )
    composer_digest = operation_composer_digest(
        binding.record.operation,
        detected_version,
    )
    record = binding.store.apply_business_update(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        context=binding.context,
        update=bind,
        event_type="handles.bound",
    )
    metadata_by_name = {
        str(candidate["name"]): candidate
        for candidate in eligible
    }
    field_candidates: list[dict[str, Any]] = []
    for bound in captured:
        candidate = metadata_by_name[bound.token]
        metadata = candidate.get("metadata")
        display = metadata.get("display") if isinstance(metadata, Mapping) else None
        label = (
            display.get("name")
            if isinstance(display, Mapping)
            and isinstance(display.get("name"), str)
            and display["name"].strip()
            else bound.token
        )
        field_candidates.append(
            {
                "handle": bound.handle,
                "label": label,
                "field_kind": bound.field_kind,
                "value_type": bound.value_type,
                "platform": bound.platform,
                "restrictions": dict(bound.restrictions),
                "matched_meanings": list(candidate.get("matched_queries", [])),
            }
        )
    payload = operation_draft_payload(
        args.command,
        record,
        offline=False,
        task_authority=args.task_authority,
    )
    payload.update(
        {
            "endpoint": dict(common["endpoint"]),
            "detected_version": detected_version,
            "project_call": dispatch_call_summary(binding.project_call),
            "field_candidates": field_candidates,
            "candidate_count": len(field_candidates),
            "rejected_candidate_count": len(rejected),
            "selection_required": True,
            "selection_rule": "copy_one_returned_field_candidate.handle",
        }
    )
    return payload


def dispatch_business_type_discovery(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str],
    connection: GatewayConnection,
    detected_version: str,
    live_info: Mapping[str, Any],
    dispatcher: WwiseDispatcher,
    common: Mapping[str, Any],
) -> dict[str, Any]:
    """Issue opaque handles for bounded live object or plug-in type matches."""

    binding = _open_business_binding(
        args,
        env=env,
        connection=connection,
        detected_version=detected_version,
        live_info=live_info,
        dispatcher=dispatcher,
    )
    adapter = business_adapter(binding.record.operation)
    if not adapter.supports_type_discovery:
        raise GatewayInputError(
            f"Business type discovery is unavailable for {binding.record.operation}"
        )
    raw_session = (
        binding.record.composition.get("business_session")
        if binding.record.composition is not None
        else None
    )
    if raw_session is None:
        raise GatewayInputError(
            "Bind the exact object or parent before type discovery"
        )
    session = BusinessDeclarationSession.from_dict(raw_session)
    if binding.context != session.context:
        raise OperationDraftBindingDrift(
            "Live project or Wwise build differs from the business declaration binding."
        )
    meanings = tuple(args.meanings)
    if (
        not 1 <= len(meanings) <= MAX_METADATA_DISCOVERY_QUERIES
        or any(
            not isinstance(value, str)
            or not value.strip()
            or len(value) > MAX_METADATA_DISCOVERY_QUERY_CHARS
            for value in meanings
        )
        or sum(len(value) for value in meanings)
        > MAX_METADATA_DISCOVERY_TOTAL_QUERY_CHARS
    ):
        raise GatewayInputError("Business type meanings exceed their fixed bounds")
    read_call = metadata_cached_read_call(
        binding.read_call,
        connection=connection,
        version=detected_version,
        live_info=live_info,
        project=binding.project,
        state_dir=binding.state_dir,
    )
    try:
        rows = parse_get_types_result(read_call(CACHE_GET_TYPES_URI, {}, {}))
    except (TypeError, ValueError) as exc:
        raise GatewayResultShapeError(
            "Live object type discovery returned an invalid catalog.",
            error_code="INVALID_METADATA_RESULT",
        ) from exc
    role = str(args.role)

    def role_matches(type_category: str) -> bool:
        category = type_category.casefold()
        if role == "source":
            return category == "source"
        if role == "effect":
            return category == "effect"
        return category not in {"source", "effect"}

    def score(meaning: str, *, name: str, category: str) -> int:
        query = meaning.strip().casefold()
        candidate = name.casefold()
        if query == candidate:
            return 1_000
        if query in candidate:
            return 700 + len(query)
        tokens = tuple(
            token
            for token in "".join(
                character if character.isalnum() else " "
                for character in query
            ).split()
            if token
        )
        searchable = f"{candidate} {category.casefold()}"
        matched = sum(token in searchable for token in tokens)
        return 100 * matched if matched and matched == len(tokens) else 0

    ranked: list[tuple[Any, list[str], int]] = []
    for row in rows:
        if not role_matches(row.type):
            continue
        scores = {
            meaning: score(meaning, name=row.name, category=row.type)
            for meaning in meanings
        }
        matched = [meaning for meaning in meanings if scores[meaning] > 0]
        if matched:
            ranked.append((row, matched, sum(scores.values())))
    ranked.sort(
        key=lambda item: (-item[2], item[0].name.casefold(), item[0].class_id)
    )
    selected = ranked[:MAX_METADATA_DISCOVERY_LIMIT]
    if not selected:
        raise GatewayInputError(
            "Live type discovery found no candidate compatible with this role"
        )
    catalog_digest = canonical_sha256(
        {"return": [row.as_dict() for row in rows]}
    )
    captured: list[Any] = []

    def bind(current: BusinessDeclarationSession) -> BusinessDeclarationSession:
        handles = BusinessHandleRegistry.from_dict(current.handles.as_dict())
        for row, _matched, _score in selected:
            captured.append(
                handles.bind_type(
                    class_id=row.class_id,
                    name=row.name,
                    type_category=row.type,
                    catalog_digest=catalog_digest,
                )
            )
        return current.with_handle_registry(handles)

    schema_digest = operation_draft_schema_digest(
        binding.record.operation,
        detected_version,
    )
    composer_digest = operation_composer_digest(
        binding.record.operation,
        detected_version,
    )
    record = binding.store.apply_business_update(
        args.draft_id,
        task_authority=args.task_authority,
        expected_revision=args.expected_revision,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        context=binding.context,
        update=bind,
        event_type="handles.bound",
    )
    candidates = [
        {
            "handle": bound.handle,
            "label": bound.name,
            "role": role,
            "matched_meanings": list(selected[index][1]),
        }
        for index, bound in enumerate(captured)
    ]
    payload = operation_draft_payload(
        args.command,
        record,
        offline=False,
        task_authority=args.task_authority,
    )
    payload.update(
        {
            "endpoint": dict(common["endpoint"]),
            "detected_version": detected_version,
            "project_call": dispatch_call_summary(binding.project_call),
            "type_candidates": candidates,
            "candidate_count": len(candidates),
            "selection_required": True,
            "selection_rule": "copy_one_returned_type_candidate.handle",
        }
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
    # Some checked Business Drafts are themselves closed requests to preview a
    # project change.  Do not make the caller restate that fact with the easily
    # misread generic ``--apply`` transport flag.
    inspected_adapter = (
        business_adapter(inspected.operation)
        if operation_uses_business_declaration(
            inspected.operation,
            inspected.version,
        )
        else None
    )
    if inspected_adapter is not None and inspected_adapter.auto_apply_preview:
        args.apply = True
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
            execute_payload["agent_control"] = {
                "terminal": False,
                "required_outcome_before_reply": (
                    "verified_or_structured_verification_failure"
                ),
                "next": (
                    "execute next_command.copy_instruction.source_field in same turn"
                ),
                "reply_before_next_command": "invalid",
            }
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
    normalized_exception = (
        result is not None and result.get("failure_origin") == "exception"
    )
    explicit_dispatch_failure = (
        result is not None
        and not dispatch_accepted
        and not (expected_disconnect and normalized_exception)
    )
    if dispatch_accepted:
        delivery = "waapi_result_returned"
        disconnect_observation = "not_observed_before_result"
        terminal_classification = "dispatch_accepted_effect_unverified"
    elif result is not None:
        delivery = "indeterminate_after_dispatch_attempt"
        disconnect_observation = (
            "call_failed_or_connection_loss_observed"
            if expected_disconnect
            else "unexpected_call_failure_observed"
        )
        terminal_classification = (
            "dispatch_failed"
            if explicit_dispatch_failure
            else "expected_disconnect_delivery_indeterminate"
        )
    else:
        delivery = "exception_after_dispatch_started"
        disconnect_observation = (
            "exception_compatible_with_expected_disconnect"
            if expected_disconnect
            else "unexpected_exception_observed"
        )
        terminal_classification = (
            "expected_disconnect_delivery_indeterminate"
            if expected_disconnect
            else "dispatch_failed"
        )
    lifecycle = {
        "expected": process_expectation,
        "observed": "not_observed_by_gateway",
        "gateway_process_action": "none",
        "reconnect_attempted": False,
    }
    durable_state = (
        TransactionState.EXECUTION_FAILED
        if explicit_dispatch_failure
        else TransactionState.INDETERMINATE
    )
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
        "terminal_journal": {
            "classification": terminal_classification,
            "effect_verified": False,
            "durable_state": durable_state.value,
            "retry_allowed": False,
        },
    }
    terminal_record = (
        store.mark_execution_failed(transaction_id, details=durable_details)
        if explicit_dispatch_failure
        else store.mark_execution_indeterminate(
            transaction_id,
            details=durable_details,
        )
    )
    return {
        "ok": False,
        "status": (
            "host_control_dispatch_failed"
            if explicit_dispatch_failure
            else "expected_disconnect_indeterminate"
            if expected_disconnect
            else "host_control_effect_indeterminate"
        ),
        **common,
        "transaction_id": transaction_id,
        "state": terminal_record.state.value,
        "artifact_hash": artifact_hash,
        "host_control": call_uri,
        "expected_disconnect": expected_disconnect,
        "disconnect_observation": disconnect_observation,
        "dispatch_delivery": delivery,
        "dispatch_accepted": dispatch_accepted,
        "terminal_journal": durable_details["terminal_journal"],
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
    if getattr(args, "return_fields", None):
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
        (bool(getattr(args, "return_fields", None)), "--return-field"),
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
    broad_source = (
        args.object_type is not None
        or getattr(args, "custom_kind_meaning", None) is not None
        or args.search is not None
        or args.query is not None
    )
    transformed = bool(args.select)
    if (broad_source or transformed) and args.take is None:
        raise GatewayInputError(
            "Broad query-object sources and --relationship traversal require an "
            "explicit --max-results bound."
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
    return {"mode": "exact-object"}


def _project_query_business_rows(
    args: argparse.Namespace,
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rename Gateway-compiled native accessors into stable business fields."""

    bindings = tuple(getattr(args, "query_output_bindings", ()) or ())
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        item = {field: row[field] for field in SELECTED_REQUIRED_RETURN_FIELDS}
        properties: dict[str, Any] = {}
        references: dict[str, Any] = {}
        for kind, native, output in bindings:
            if native not in row:
                raise GatewayResultShapeError(
                    "Object query omitted a requested business result field.",
                    details={
                        "row_index": index,
                        "business_field": output,
                    },
                    error_code="INVALID_QUERY_RESULT",
                )
            if kind == "property":
                properties[output] = row[native]
            elif kind == "reference":
                references[output] = row[native]
            else:
                item[output] = row[native]
        if properties:
            item["properties"] = properties
        if references:
            item["references"] = references
        projected.append(item)
    return projected


def _bind_custom_kind_from_live_types(
    args: argparse.Namespace,
    *,
    connection: GatewayConnection,
    detected_version: str,
    dispatcher: WwiseDispatcher,
) -> dict[str, Any] | None:
    """Resolve one user-facing custom kind against the live type inventory."""

    meaning = getattr(args, "custom_kind_meaning", None) or getattr(
        args,
        "metadata_custom_kind_meaning",
        None,
    )
    if meaning is None:
        return None
    read = transaction_read_call(
        dispatcher,
        connection=connection,
        version=detected_version,
    )
    records = parse_get_types_result(read(CACHE_GET_TYPES_URI, {}, {}))

    def lexical(value: str) -> str:
        return "".join(character.casefold() for character in value if character.isalnum())

    needle = lexical(meaning)
    exact = [record for record in records if lexical(record.name) == needle]
    matches = exact or [
        record
        for record in records
        if needle and (needle in lexical(record.name) or lexical(record.name) in needle)
    ]
    if len(matches) != 1:
        return {
            "metadata_authority": "live-waapi",
            "meaning": meaning,
            "candidate_count": len(matches),
            "candidates": [record.as_dict() for record in matches[:8]],
            "repair": "refine --custom-kind until one live Wwise type matches",
        }
    args.object_type = matches[0].name
    return None


def _bind_query_custom_fields_from_live_metadata(
    args: argparse.Namespace,
    *,
    connection: GatewayConnection,
    detected_version: str,
    dispatcher: WwiseDispatcher,
) -> dict[str, Any] | None:
    """Bind business field meanings to exact live query projection accessors.

    Returns a structured clarification payload when any meaning is ambiguous;
    otherwise mutates only the current invocation's compiled projection facts.
    """

    meanings = tuple(getattr(args, "query_custom_field_meanings", ()) or ())
    if not meanings:
        return None
    discovery = discover_metadata(
        read_call=transaction_read_call(
            dispatcher,
            connection=connection,
            version=detected_version,
        ),
        queries=meanings,
        object_type=args.object_type,
        object=args.path if args.path is not None else args.object_id,
        limit=DEFAULT_METADATA_DISCOVERY_LIMIT,
    )
    candidates = {
        candidate.get("name"): candidate
        for candidate in discovery.candidates
        if isinstance(candidate.get("name"), str)
    }
    bindings = list(getattr(args, "query_output_bindings", ()) or ())
    unresolved: list[dict[str, Any]] = []
    for query_result in discovery.query_results:
        meaning = query_result.get("query")
        names = query_result.get("candidate_names")
        if not isinstance(meaning, str) or not isinstance(names, list):
            unresolved.append(
                {
                    "meaning": meaning,
                    "candidate_names": names if isinstance(names, list) else [],
                }
            )
            continue
        exact_names: list[str] = []
        for name in names:
            candidate = candidates.get(name)
            metadata = candidate.get("metadata") if isinstance(candidate, Mapping) else None
            display = metadata.get("display") if isinstance(metadata, Mapping) else None
            display_name = display.get("name") if isinstance(display, Mapping) else None
            if (
                isinstance(name, str)
                and name.casefold() == meaning.casefold()
            ) or (
                isinstance(display_name, str)
                and display_name.casefold() == meaning.casefold()
            ):
                exact_names.append(name)
        selected_names = exact_names if len(exact_names) == 1 else names
        if len(selected_names) != 1:
            unresolved.append({"meaning": meaning, "candidate_names": names})
            continue
        candidate = candidates.get(selected_names[0])
        kind = candidate.get("kind") if isinstance(candidate, Mapping) else None
        token = candidate.get("name") if isinstance(candidate, Mapping) else None
        if kind not in {"property", "reference"} or not isinstance(token, str):
            unresolved.append({"meaning": meaning, "candidate_names": names})
            continue
        native = f"@{token}" if kind == "property" else token
        bindings.append((kind, native, token))
    if unresolved:
        return {
            "metadata_authority": "live-waapi",
            "unresolved": unresolved,
            "repair": "refine each --include-field meaning until one live field matches",
        }
    native_fields = [binding[1] for binding in bindings]
    if len(set(native_fields)) != len(native_fields):
        raise GatewayInputError(
            "query-object live field discovery resolved duplicate result fields"
        )
    args.query_output_bindings = tuple(bindings)
    args.query_return_fields = (*SELECTED_REQUIRED_RETURN_FIELDS, *native_fields)
    return None


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


def metadata_call_evidence_projection(
    calls: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Keep metadata stdout bounded while pointing to complete dispatcher evidence."""

    return {
        "metadata_call_count": len(calls),
        "calls": [dict(calls[-1])] if calls else [],
        "metadata_evidence_scope": "all calls retained in dispatcher evidence directory",
    }


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
        "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
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


def operation_draft_copy_command(
    full_argv: Sequence[str],
    *,
    platform_name: str | None = None,
) -> str:
    """Render one exact compact Draft continuation for the active shell host."""

    active_platform = os.name if platform_name is None else platform_name
    normalized = [str(value) for value in full_argv]
    if active_platform == "nt":
        try:
            return encode_windows_model_argv(normalized)
        except PlatformCommandError:
            return encode_windows_powershell_argv(normalized)
    return shlex.join(normalized)


def operation_draft_prefix_copy_binding(
    full_argv: Sequence[str],
    *,
    append_action: str = "copy_verbatim_then_append_complete_typed_action_groups",
) -> dict[str, Any]:
    """Return one copy-ready Draft prefix plus its closed append policy."""

    normalized = [str(value) for value in full_argv]
    return {
        "fixed_argv_prefix": normalized,
        "fixed_argv_prefix_copy": operation_draft_copy_command(normalized),
        "fixed_argv_prefix_copy_instruction": {
            "contract": OPERATION_DRAFT_COMMAND_COPY_INSTRUCTION_CONTRACT,
            "source_field": "fixed_argv_prefix_copy",
            "action": append_action,
            "forbidden_transformations": [
                "reconstruct",
                "shorten",
                "normalize",
                "substitute_path_segments",
                "select_another_field",
            ],
            "opaque_token_guard": {
                "task_authority": {
                    "prefix": "da1-",
                    "hex_characters_after_prefix": 40,
                    "truncate_to_32_hex_characters": "invalid",
                }
            },
        },
    }


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


def _business_next_action_binding(
    record: OperationDraftRecord,
    *,
    task_authority: str | None,
) -> dict[str, Any]:
    authority = task_authority or "<task-authority-from-draft-start>"
    base = [
        "python",
        str(GATEWAY_RUNNER_PATH),
        "gateway.py",
    ]
    binding = [
        record.draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(record.revision),
    ]
    raw_session = (
        record.composition.get("business_session")
        if record.composition is not None
        else None
    )
    session = (
        None
        if raw_session is None
        else BusinessDeclarationSession.from_dict(raw_session)
    )
    adapter = business_adapter(record.operation)
    if record.check is not None:
        preview = [*base, "preview-from-draft", *binding]
        if not adapter.auto_apply_preview:
            preview.append("--apply")
        return {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "required_next_phase": "preview_from_checked_business_draft",
            "fixed_full_argv": preview,
            "copy_command": operation_draft_copy_command(preview),
            "copy_exactly": True,
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
        }
    object_bind_prefix = [*base, "draft-bind-object", *binding]
    field_bind_prefix = [*base, "draft-bind-field", *binding]
    field_discover_prefix = [*base, "draft-discover-fields", *binding]
    configure_prefix = [*base, "draft-business-configure", *binding]
    declare_new_prefix = [*base, "draft-declare-new", *binding]
    declare_existing_prefix = [*base, "draft-declare-existing", *binding]
    declare_import_batch_prefix = [
        *base,
        "draft-declare-import-batch",
        *binding,
    ]
    add_media_prefix = [*base, "draft-add-media", *binding]
    clear_object_list_prefix = [
        *base,
        "draft-clear-object-list",
        *binding,
    ]
    declare_object_change_prefix = [
        *base,
        "draft-declare-object-change",
        *binding,
    ]
    declare_field_change_prefix = [
        *base,
        "draft-declare-field-change",
        *binding,
    ]
    declare_rtpc_prefix = [*base, "draft-declare-rtpc", *binding]
    declare_soundbank_plan_prefix = [
        *base,
        "draft-declare-soundbank-plan",
        *binding,
    ]
    declare_artifact_plan_prefix = [
        *base,
        "draft-declare-artifact-plan",
        *binding,
    ]
    declare_ui_plan_prefix = [*base, "draft-declare-ui-plan", *binding]
    add_ui_command_prefix = [*base, "draft-add-ui-command", *binding]
    declare_debug_intent_prefix = [
        *base,
        "draft-declare-debug-intent",
        *binding,
    ]
    declare_undo_plan_prefix = [
        *base,
        "draft-declare-undo-plan",
        *binding,
    ]
    revise_prefix = [*base, "draft-revise-declaration", *binding]
    remove_prefix = [*base, "draft-remove-declaration", *binding]
    check = [*base, "draft-check", *binding]
    by_id = operation_draft_prefix_copy_binding(object_bind_prefix)
    by_id["append"] = ["--object-id", "<exact-guid>"]
    by_path_segments = operation_draft_prefix_copy_binding(object_bind_prefix)
    by_path_segments["append_repeated"] = [
        "--object-path-segment",
        "<one-exact-user-path-segment-without-separators>",
    ]
    by_path_segments["segment_order"] = "root_to_leaf"
    object_binding = {
        "by_id": by_id,
        "by_path_segments": by_path_segments,
        "selection_rule": (
            "user_supplied_complete_path_requires_by_path_segments; "
            "user_supplied_name_without_a_path_requires_query_then_by_id; "
            "user_selected_guid_uses_by_id"
        ),
        "path_rule": (
            "copy_each_nonempty_user_path_segment_root_to_leaf; gateway_inserts_"
            "every_wwise_separator"
        ),
        "name_rule": "unscoped_name_is_not_a_mutation_identity",
        "result": "copy_the_returned_bound_object.handle",
        "result_validation_rule": (
            "before_declaration_compare_returned_name_type_path_to_the_user_"
            "target; bind_again_or_stop_if_they_differ"
        ),
        "use_only_for": [
            "existing_target",
            "new_target_parent",
            "output_bus",
            "event_parent",
            "custom_reference_value",
        ],
    }
    role_declaration = adapter.role_declaration

    def role_object_binding(next_role: str) -> dict[str, Any]:
        role_bind_prefix = [*object_bind_prefix, "--role", next_role]
        role_by_id = operation_draft_prefix_copy_binding(role_bind_prefix)
        role_by_id["append"] = ["--object-id", "<exact-guid>"]
        role_by_path_segments = operation_draft_prefix_copy_binding(
            role_bind_prefix
        )
        role_by_path_segments["append_repeated"] = [
            "--object-path-segment",
            "<one-exact-user-path-segment-without-separators>",
        ]
        role_by_path_segments["segment_order"] = "root_to_leaf"
        return {
            **object_binding,
            "by_id": role_by_id,
            "by_path_segments": role_by_path_segments,
            "next_role": next_role,
            "use_only_for": [next_role],
            "role_assignment": (
                "copy this Gateway-owned role prefix exactly, then copy "
                "the returned handle into the same named declaration field"
            ),
        }

    forbidden_inputs = [
        "native_request",
        "model_invented_object_path",
        "object_type",
        "metadata_scope",
        "waapi_args",
        "waapi_options",
    ]
    business_contract = operation_business_contract(
        record.operation,
        record.version,
    )
    if not (adapter.supports_field_binding or adapter.supports_field_discovery):
        object_binding = {
            **object_binding,
            "use_only_for": business_contract["binding"]["roles"],
            "role_assignment": (
                "bind_each_required_role_then_copy_its_returned_handle_into_"
                "the_same_named_declaration_field"
            ),
        }
    if adapter.family == "compound-undo-business":
        shared = {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "responsibility_split": business_contract["responsibility_split"],
            "business_contract": business_contract,
            "forbidden_inputs": [
                *forbidden_inputs,
                "child_call_handle",
                "child_schema_digest",
                "child_native_request",
                "action_ordering_grammar",
                "begin_group_call",
                "end_group_call",
                "cancel_group_call",
                "revision_arithmetic",
            ],
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
        }
        if session is not None and adapter.is_complete(session):
            return {
                **shared,
                "required_next_phase": "check_complete_compound_undo_plan",
                "check": {
                    **operation_draft_prefix_copy_binding(check),
                    "append": [],
                },
            }
        return {
            **shared,
            "required_next_phase": "declare_ordered_checked_child_business_drafts",
            "declaration": {
                **operation_draft_prefix_copy_binding(
                    declare_undo_plan_prefix,
                    append_action=(
                        "copy_verbatim_then_append_display_name_and_each_checked_"
                        "child_draft_in_user_requested_order"
                    ),
                ),
                "append": [
                    "--display-name <user-facing-Wwise-Undo-step-name>",
                    "--child-draft <checked-child-draft-id> <its-task-authority> [--child-draft ...]",
                ],
                "order_rule": "repeat_child_draft_in_exact_user_requested_execution_order",
                "order_ownership": {
                    "business_sequence": "caller_owned_stable_business_value",
                    "native_phase_dependencies": (
                        "gateway_owned_begin_then_business_sequence_then_end_"
                        "with_cancel_on_failure"
                    ),
                    "dependency_edges_input": "forbidden",
                },
                "child_prerequisite": (
                    "each_child_is_a_current_revision_draft-check-passed_closed_"
                    "business_draft_for_this_project_and_version_with_a_supported_"
                    "business_outcome_verifier; generic_typed_children_are_"
                    "prohibited_until_their_separate_interface_depth_migration"
                ),
                "submit_once": True,
                "native_request_input": "forbidden",
            },
        }
    if adapter.family == "debug-host-control":
        shared = {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "responsibility_split": business_contract["responsibility_split"],
            "business_contract": business_contract,
            "forbidden_inputs": [
                *forbidden_inputs,
                "acknowledgement_literal",
                "native_uri",
                "native_request",
                "waapi_args",
                "waapi_options",
                "disconnect_classification",
                "retry_or_reconnect_plan",
            ],
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
        }
        if session is not None and adapter.is_complete(session):
            return {
                **shared,
                "required_next_phase": "check_complete_debug_business_intent",
                "check": {
                    **operation_draft_prefix_copy_binding(check),
                    "append": [],
                },
            }
        append = (
            ["exactly one of --enable or --disable"]
            if record.operation
            in {"debug.setAsserts", "debug.setAutomationMode"}
            else []
        )
        return {
            **shared,
            "required_next_phase": "declare_debug_business_intent",
            "declaration": {
                **operation_draft_prefix_copy_binding(
                    declare_debug_intent_prefix,
                    append_action=(
                        "copy_verbatim_then_append_the_stable_boolean_outcome"
                        if append
                        else "copy_and_execute_verbatim_once"
                    ),
                ),
                "append": append,
                "submit_once": True,
                "native_request_input": "forbidden",
            },
        }
    if adapter.family == "authoring-ui-business":
        shared = {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "responsibility_split": operation_business_contract(
                record.operation,
                record.version,
            )["responsibility_split"],
            "business_contract": operation_business_contract(
                record.operation,
                record.version,
            ),
            "forbidden_inputs": [
                *forbidden_inputs,
                "native_command_id_for_registration",
                "source_authority",
                "host_platform",
                "acknowledgement_literal",
                "native_request",
                "revision_arithmetic",
                "request_fragment",
            ],
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
        }
        if record.operation in {
            "ui.commands.execute",
            "ui.commands.register",
            "ui.commands.unregister",
        }:
            shared["fresh_command_inventory"] = {
                "owner": "gateway",
                "agent_action": (
                    "declare_the_user_requested_business_choice_without_an_"
                    "extra_getCommands_or_request_schema_call"
                ),
                "validation_timing": "immediately_before_dispatch",
            }
        if session is not None and adapter.is_complete(session):
            return {
                **shared,
                "required_next_phase": "check_complete_authoring_ui_plan",
                "check": {
                    **operation_draft_prefix_copy_binding(check),
                    "append": [],
                },
            }
        if record.operation == "ui.commands.register" and session is not None:
            raw_plan = session.settings.get("ui_plan")
            commands = raw_plan.get("commands") if isinstance(raw_plan, Mapping) else None
            expected = raw_plan.get("command_count") if isinstance(raw_plan, Mapping) else None
            next_index = len(commands) if isinstance(commands, list) else 0
            handler_kinds = ["notification", "program"]
            if record.version in {"2023.1", "2024.1", "2025.1"}:
                handler_kinds.append("lua_script")
            return {
                **shared,
                "required_next_phase": "add_next_complete_ui_command",
                "command_index": next_index,
                "expected_command_count": expected,
                "declaration": {
                    **operation_draft_prefix_copy_binding(
                        add_ui_command_prefix,
                        append_action="copy_verbatim_then_append_one_complete_ui_command",
                    ),
                    "append": [
                        "--key <stable-business-command-key>",
                        "--display-name <user-facing-name>",
                        f"--handler-kind {'|'.join(handler_kinds)}",
                        "[--handler-path <exact-user-supplied-existing-path>]",
                        "[--argument-token <one-exact-token>]... (lua_script only)",
                        "[--working-directory <exact-existing-directory>]",
                        "[--start-mode SingleSelectionSingleProcess|MultipleSelectionSingleProcessSpaceSeparated|MultipleSelectionMultipleProcesses]",
                        "[--redirect-outputs] (program/Windows only)",
                        "[--lua-module-directory <exact-existing-directory>]...",
                        "[--lua-selected-return <field>]...",
                        "[--default-shortcut <shortcut>]",
                        "[--context-menu-segment <Wwise-menu-segment>]...",
                        "[--context-visible-for <Wwise-object-type>]...",
                        "[--context-enabled-for <Wwise-object-type>]...",
                        "[--main-menu-segment <Wwise-menu-segment>]...",
                    ],
                    "submit_once": True,
                },
            }
        shapes = {
            "ui.captureScreen": [
                "[--view-name <exact-Wwise-view-name>]",
                "[--view-channel 1|2|3|4]",
                "[--rect <x> <y> <width> <height>]",
            ],
            "ui.commands.execute": [
                "--command-id <exact-user-requested-command-choice>",
                "[--command-object <exact-object-guid-or-command-operand>]...",
                "[--command-platform <exact-project-platform>]...",
                "[--value string|boolean|integer|number|null <exact-value>]",
                "[--command-file <exact-user-supplied-file>]... (2025.1 only)",
            ],
            "ui.commands.register": [
                "--command-count <number-of-user-requested-commands-1-to-32>",
            ],
            "ui.commands.unregister": [
                "either --registered-command-key <Gateway-derived-registration-key> [...]",
                "or --existing-command-id <exact-id-from-fresh-getCommands-choice> [...] --confirm-unknown-ownership",
            ],
        }
        return {
            **shared,
            "required_next_phase": "declare_authoring_ui_business_plan",
            "declaration": {
                **operation_draft_prefix_copy_binding(
                    declare_ui_plan_prefix,
                    append_action="copy_verbatim_then_append_one_complete_ui_business_plan",
                ),
                "append": shapes[record.operation],
                "submit_once": True,
            },
        }
    if adapter.family == "exact-artifact-code":
        shared = {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "responsibility_split": {
                "agent": (
                    "select_the_operation_and_copy_exact_user_artifacts_plus_"
                    "closed_business_values"
                ),
                "gateway": (
                    "derive_source_authority_io_root_native_loader_fields_"
                    "request_order_and_serialization"
                ),
            },
            "business_contract": business_contract,
            "forbidden_inputs": [
                *forbidden_inputs,
                "source_authority",
                "native_loader_field",
                "luaScript",
                "luaString",
                "doFiles",
                "luaPaths",
                "requires",
                "request_fragment",
                "serialized_native_payload",
            ],
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
        }
        if session is not None and session.settings:
            return {
                **shared,
                "required_next_phase": "check_complete_business_declaration",
                "check": {
                    **operation_draft_prefix_copy_binding(check),
                    "append": [],
                },
            }
        binding_roles = business_contract["binding"]["roles"]
        bound_roles = (
            set()
            if session is None
            else {
                row.get("role")
                for row in session.handles.as_dict()["objects"]
                if isinstance(row, Mapping)
            }
        )
        missing_roles = [role for role in binding_roles if role not in bound_roles]
        if missing_roles:
            next_role = missing_roles[0]
            return {
                **shared,
                "required_next_phase": "bind_exact_artifact_business_role",
                "object_binding": role_object_binding(next_role),
            }
        declaration_shapes = {
            "audio.importTabDelimited": [
                "--table-file <exact-user-supplied-tsv-file>",
                "--location-handle <bound-import-location-handle>",
                "--language <exact-project-language>",
                "[--mode create|reimport|replace]",
                "[--add-to-source-control|--no-add-to-source-control]",
                "[--check-out-from-source-control|--no-check-out-from-source-control] (2023.1+)",
            ],
            "lua.executeCliFile": [
                "--script-file <exact-user-supplied-lua-file>",
                "[--argument <key> string|boolean|integer|number|json|null <exact-value>]...",
                "[--watchdog-seconds <non-negative-integer>] (2024.1+)",
            ],
            "lua.executeCoreFile": [
                "--script-file <exact-user-supplied-lua-file>",
                "[--argument <key> string|boolean|integer|number|json|null <exact-value>]...",
            ],
            "lua.executeCoreInline": [
                "--lua-source <exact-user-supplied-utf8-source>",
                "--io-root <exact-isolated-transaction-root>",
                "[--argument <key> string|boolean|integer|number|json|null <exact-value>]...",
            ],
        }
        return {
            **shared,
            "required_next_phase": "declare_complete_exact_artifact_plan",
            "declaration": {
                **operation_draft_prefix_copy_binding(
                    declare_artifact_plan_prefix,
                    append_action=(
                        "copy_verbatim_then_append_one_complete_exact_artifact_plan"
                    ),
                ),
                "append": declaration_shapes[record.operation],
                "submit_once": True,
                "native_request_input": "forbidden",
            },
        }
    if adapter.family == "soundbank-planning":
        def soundbank_role_route(role: str) -> dict[str, Any]:
            role_prefix = [*object_bind_prefix, "--role", role]
            role_by_id = operation_draft_prefix_copy_binding(role_prefix)
            role_by_id["append"] = ["--object-id", "<exact-guid>"]
            role_by_path_segments = operation_draft_prefix_copy_binding(
                role_prefix
            )
            role_by_path_segments["append_repeated"] = [
                "--object-path-segment",
                "<one-exact-user-path-segment-without-separators>",
            ]
            role_by_path_segments["segment_order"] = "root_to_leaf"
            route: dict[str, Any] = {
                "fixed_role": role,
                "by_id": role_by_id,
                "by_path_segments": role_by_path_segments,
                "result": "copy_the_returned_bound_object.handle",
            }
            if role == "soundbank":
                role_exact_name = operation_draft_prefix_copy_binding(
                    [*role_prefix, "--exact-type-name", "SoundBank"]
                )
                role_exact_name["append"] = ["<exact-object-name>"]
                route["by_exact_name"] = role_exact_name
            return route

        soundbank_object_binding = {
            "direct_query_before_binding": "forbidden",
            "route_by_user_fact": {
                "complete_object_path": "role_routes.<role>.by_path_segments",
                "exact_soundbank_name": (
                    "role_routes.soundbank.by_exact_name"
                ),
                "selected_guid": "role_routes.<role>.by_id",
            },
            "role_routes": {
                role: soundbank_role_route(role)
                for role in business_contract["binding"]["roles"]
            },
            "selection_rule": (
                "choose_the_business_role_first_then_copy_its_disclosed_identity_route"
            ),
            "name_rule": (
                "an_unscoped_soundbank_name_uses_the_soundbank_exact_name_route"
            ),
            "result_validation_rule": (
                "compare_returned_name_type_path_to_the_user_target_before_using_"
                "the_handle"
            ),
        }
        shared = {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "responsibility_split": {
                "agent": "natural_language_to_closed_high_level_business_facts",
                "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
            },
            "business_contract": business_contract,
            "forbidden_inputs": [
                *(
                    item
                    for item in forbidden_inputs
                    if item != "object_type"
                ),
                "native_object_type_field",
                "native_soundbank_row",
                "identity_selector",
                "skip_languages",
                "write_to_disk",
                "request_fragment",
                "batch_layout",
            ],
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
        }
        if session is not None and session.settings:
            return {
                **shared,
                "required_next_phase": "check_complete_business_declaration",
                "check": {
                    **operation_draft_prefix_copy_binding(check),
                    "append": [],
                },
            }
        declaration_shapes = {
            "soundbank.setInclusions": [
                "--mode add|remove|replace",
                "--soundbank-handle <bound-soundbank-handle>",
                "[--inclusion <bound-object-handle> <one-or-more-unique-events|structures|media-filters>]...",
            ],
            "soundbank.generate": [
                "--soundbank <bound-soundbank-handle> nonlocalized|localized|mixed",
                "[--event <bound-soundbank-handle> <bound-event-handle>]...",
                "[--aux-bus <bound-soundbank-handle> <bound-aux-bus-handle>]...",
                "[--generation-inclusion <bound-soundbank-handle> <one-or-more-unique-events|structures|media-filters>]...",
                "[--rebuild-soundbank <bound-soundbank-handle>|--no-rebuild-soundbank <bound-soundbank-handle>]...",
                "--platform <project-platform-name> [--platform ...]",
                "[--language <localized-project-language>]...",
                "[--rebuild-soundbanks|--no-rebuild-soundbanks]",
                "[--clear-audio-file-cache|--no-clear-audio-file-cache]",
                "[--rebuild-init-bank|--no-rebuild-init-bank]",
                "--io-root <exact-isolated-output-root>",
            ],
            "soundbank.convertExternalSources": [
                "--source <exact-wsources-file> <project-platform-name> <exact-output-root>",
                "[--source ...]...",
                "--io-root <exact-isolated-root>",
            ],
            "soundbank.processDefinitionFiles": [
                "--definition-file <exact-definition-file> [--definition-file ...]",
                "--io-root <exact-isolated-root>",
            ],
        }
        binding_roles = business_contract["binding"]["roles"]
        result = {
            **shared,
            "required_next_phase": (
                "bind_remaining_plan_objects_or_declare_complete_soundbank_plan"
                if binding_roles
                else "declare_complete_soundbank_plan"
            ),
        }
        if binding_roles:
            result["object_binding"] = {
                **soundbank_object_binding,
                "use_only_for": binding_roles,
                "repeat_until": "every_object_named_by_the_business_plan_is_bound",
            }
        result["declaration"] = {
            **operation_draft_prefix_copy_binding(
                declare_soundbank_plan_prefix,
                append_action=(
                    "copy_verbatim_then_append_one_complete_soundbank_business_plan"
                ),
            ),
            "append": declaration_shapes[record.operation],
            "submit_once": True,
            "native_request_input": "forbidden",
        }
        return result
    if session is None:
        if role_declaration is not None:
            next_role = role_declaration.roles[0]
            return {
                "contract": "waapi-skill.business-draft-next-action/v1",
                "required_next_phase": "bind_remaining_switch_assignment_roles",
                "responsibility_split": {
                    "agent": "natural_language_to_closed_high_level_business_facts",
                    "gateway": (
                        "business_facts_to_exact_waapi_request_and_execution_plan"
                    ),
                },
                "business_contract": business_contract,
                "object_binding": role_object_binding(next_role),
                "forbidden_inputs": [
                    *forbidden_inputs,
                    *role_declaration.forbidden_inputs,
                ],
                "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
                "then_read_next_response": True,
                "precompute_or_increment_revision": False,
            }
        return {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "required_next_phase": "bind_existing_business_object",
            "responsibility_split": {
                "agent": "natural_language_to_closed_high_level_business_facts",
                "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
            },
            "business_contract": business_contract,
            "object_binding": object_binding,
            "forbidden_inputs": forbidden_inputs,
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
        }
    if role_declaration is not None:
        bound_count = len(session.handles.as_dict()["objects"])
        shared = {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "responsibility_split": {
                "agent": "natural_language_to_closed_high_level_business_facts",
                "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
            },
            "business_contract": business_contract,
            "forbidden_inputs": [
                *forbidden_inputs,
                *role_declaration.forbidden_inputs,
            ],
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
        }
        if session.declarations:
            return {
                **shared,
                "required_next_phase": "check_complete_business_declaration",
                "check": {
                    **operation_draft_prefix_copy_binding(check),
                    "append": [],
                },
        }
        if bound_count < len(role_declaration.roles):
            next_role = role_declaration.roles[bound_count]
            return {
                **shared,
                "required_next_phase": "bind_remaining_switch_assignment_roles",
                "object_binding": role_object_binding(next_role),
            }
        return {
            **shared,
            "required_next_phase": "declare_complete_switch_assignment",
            "declaration": {
                **operation_draft_prefix_copy_binding(
                    [*base, role_declaration.command, *binding]
                ),
                "append": list(role_declaration.continuation_argv),
                "submit_once": True,
            },
        }
    if adapter.supports_type_discovery:
        type_discover_prefix = [*base, "draft-discover-types", *binding]
        declaration_prefix = [*base, "draft-declare-new", *binding]
        if record.operation == "object.createPlugin":
            shared = {
                "contract": "waapi-skill.business-draft-next-action/v1",
                "responsibility_split": {
                    "agent": "natural_language_to_closed_high_level_business_facts",
                    "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
                },
                "business_contract": business_contract,
                "object_binding": object_binding,
                "forbidden_inputs": [
                    *forbidden_inputs,
                    "plugin_class_id",
                    "plugin_property_token",
                    "native_plugin_topology",
                ],
                "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
                "then_read_next_response": True,
                "precompute_or_increment_revision": False,
            }
            if session.declarations:
                return {
                    **shared,
                    "required_next_phase": "check_complete_business_declaration",
                    "check": {
                        **operation_draft_prefix_copy_binding(check),
                        "append": [],
                    },
                }
            type_discovery = {
                **operation_draft_prefix_copy_binding(type_discover_prefix),
                "role_decision": {
                    "source": [
                        "--meaning",
                        "<user-facing-plugin-name>",
                        "--role",
                        "source",
                    ],
                    "effect": [
                        "--meaning",
                        "<user-facing-plugin-name>",
                        "--role",
                        "effect",
                    ],
                },
                "result": "copy_one_returned_type_candidate.handle",
            }
            field_discovery = {
                **operation_draft_prefix_copy_binding(field_discover_prefix),
                "append": [
                    "--type-handle",
                    "<selected-plugin-type-handle>",
                    "--meaning",
                    "<user-facing-plugin-property-meaning>",
                ],
                "use_only_when": "the_user_requested_plugin_properties",
                "token_input": "forbidden",
            }
            declaration = {
                **operation_draft_prefix_copy_binding(declare_existing_prefix),
                "append": [
                    "--declaration-id",
                    "plugin",
                    "--object-handle",
                    "<bound-plugin-owner-handle>",
                    "--field",
                    "plugin_role",
                    "<source-or-effect>",
                    "--field",
                    "plugin_name",
                    "<requested-plugin-object-name>",
                    "--field",
                    "plugin_type_handle",
                    "<selected-plugin-type-handle>",
                    "[--field notes <exact-user-notes>]",
                    "[--field platform <exact-user-platform>]",
                    "[--field language <exact-source-language>]",
                    "[--field-value <bound-property-handle> <business-value>]...",
                ],
            }
            return {
                **shared,
                "required_next_phase": (
                    "declare_plugin_or_discover_requested_properties"
                    if session.handles.as_dict()["types"]
                    else "discover_plugin_type"
                ),
                "type_discovery": type_discovery,
                "field_discovery": field_discovery,
                "declaration": declaration,
            }
        if record.operation == "object.set":
            shared = {
                "contract": "waapi-skill.business-draft-next-action/v1",
                "responsibility_split": {
                    "agent": "natural_language_to_closed_high_level_business_facts",
                    "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
                },
                "business_contract": business_contract,
                "object_binding": object_binding,
                "forbidden_inputs": [
                    *forbidden_inputs,
                    "property_token",
                    "reference_token",
                    "target_row",
                    "batch_layout",
                    "recursive_request_fragment",
                ],
                "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
                "then_read_next_response": True,
                "precompute_or_increment_revision": False,
            }
            return {
                **shared,
                "required_next_phase": (
                    "declare_remaining_object_outcomes_or_check_complete_batch"
                    if session.declarations
                    else "declare_existing_or_new_object_outcome"
                ),
                "field_discovery": {
                    **operation_draft_prefix_copy_binding(field_discover_prefix),
                    "scope_decision": {
                        "existing_object": [
                            "--object-handle",
                            "<bound-existing-target-handle>",
                        ],
                        "stable_new_kind": [
                            "--semantic-kind",
                            "<disclosed-stable-semantic-kind>",
                        ],
                        "discovered_new_type": [
                            "--type-handle",
                            "<selected-type-handle>",
                        ],
                    },
                    "append": [
                        "--meaning",
                        "<user-facing-field-meaning>",
                    ],
                    "token_input": "forbidden",
                },
                "type_discovery": {
                    **operation_draft_prefix_copy_binding(type_discover_prefix),
                    "append": [
                        "--meaning",
                        "<user-facing-long-tail-child-kind>",
                        "--role",
                        "object",
                    ],
                    "use_when": "new_kind_is_not_one_disclosed_stable_semantic_kind",
                },
                "declare_existing": {
                    **operation_draft_prefix_copy_binding(declare_existing_prefix),
                    "append": [
                        "--declaration-id",
                        "<task-local-id>",
                        "--object-handle",
                        "<bound-existing-target-handle>",
                        "[--field <stable-business-field> <business-value>]...",
                        "[--field-value <bound-field-handle> <business-value>]...",
                    ],
                },
                "declare_new": {
                    **operation_draft_prefix_copy_binding(declare_new_prefix),
                    "append": [
                        "--declaration-id",
                        "<task-local-id>",
                        "--parent-handle",
                        "<bound-or-planned-parent-handle>",
                        "--name",
                        "<requested-child-name>",
                        "--kind",
                        "<stable-semantic-kind-or-selected-type-handle>",
                        "[--field <stable-business-field> <business-value>]...",
                        "[--field-value <bound-field-handle> <business-value>]...",
                    ],
                },
                "configure": {
                    **operation_draft_prefix_copy_binding(configure_prefix),
                    "append": [
                        "[--name-conflict fail|rename|merge]",
                        "[--list-behavior append|replace-all]",
                        "[--add-to-source-control|--no-add-to-source-control]",
                    ],
                },
                "clear_object_list": {
                    **operation_draft_prefix_copy_binding(
                        clear_object_list_prefix
                    ),
                    "append": [
                        "--declaration-id",
                        "<task-local-existing-target-id>",
                        "--object-handle",
                        "<bound-existing-target-handle>",
                        "--list-name",
                        "<exact-user-owned-wwise-object-list-name>",
                    ],
                    "list_name_input": (
                        "exact_user_owned_wwise_object_list_name_without_at_prefix"
                    ),
                    "effect": "replace_all_with_empty_list",
                },
                **(
                    {
                        "add_media": {
                            **operation_draft_prefix_copy_binding(add_media_prefix),
                            "append": [
                                "--declaration-id",
                                "<existing-task-local-declaration-id>",
                                "--media-file",
                                "<exact-user-media-path>",
                                "or",
                                "--inline-wav",
                                "<exact-user-inline-wav>",
                                "[--kind <stable-semantic-kind-or-selected-type-handle>]",
                                "[--language <exact-project-language>]",
                                "[--originals-subfolder <exact-relative-subfolder>]",
                            ],
                            "supported_versions": ["2023.1", "2024.1", "2025.1"],
                            "native_import_fragment_input": "forbidden",
                            "repeat_for_each_media_artifact": True,
                        }
                    }
                    if record.version in {"2023.1", "2024.1", "2025.1"}
                    else {}
                ),
                "completion_candidate": {
                    "condition": "all_user_requested_object_outcomes_are_declared",
                    "fixed_full_argv": check,
                    "copy_command": operation_draft_copy_command(check),
                    "is_next_command_when_condition_true": bool(session.declarations),
                },
            }
        shared = {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "responsibility_split": {
                "agent": "natural_language_to_closed_high_level_business_facts",
                "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
            },
            "business_contract": business_contract,
            "object_binding": object_binding,
            "forbidden_inputs": [
                *forbidden_inputs,
                "native_object_type",
                "plugin_class_id",
                "recursive_request_fragment",
            ],
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
        }
        type_discovery = {
            **operation_draft_prefix_copy_binding(type_discover_prefix),
            "append": [
                "--meaning",
                "<user-facing-object-kind>",
                "--role",
                "object",
            ],
            "use_when": "requested_kind_is_not_one_disclosed_stable_semantic_kind",
            "result": "copy_one_returned_type_candidate.handle",
            "native_type_input": "forbidden",
            "class_id_input": "forbidden",
        }
        declare = {
            **operation_draft_prefix_copy_binding(declaration_prefix),
            "append": [
                "--declaration-id",
                "<task-local-id>",
                "--parent-handle",
                "<bound-or-planned-parent-handle>",
                "--name",
                "<requested-object-name>",
                "--kind",
                "<stable-semantic-kind-or-selected-type-handle>",
                "[--field <stable-business-field> <business-value>]...",
            ],
            "task_local_id": "bounded_unique_not_business_data",
            "planned_child_result": "copy_returned_declaration.result_handle",
        }
        field_discovery = {
            **operation_draft_prefix_copy_binding(field_discover_prefix),
            "scope_decision": {
                "stable_semantic_kind": [
                    "--semantic-kind",
                    "<disclosed-stable-semantic-kind>",
                ],
                "discovered_type": [
                    "--type-handle",
                    "<selected-type-handle>",
                ],
            },
            "append": [
                "--meaning",
                "<user-facing-field-meaning>",
            ],
            "use_only_when": "the_user_requested_custom_properties_or_references",
            "token_input": "forbidden",
        }
        configure = {
            **operation_draft_prefix_copy_binding(configure_prefix),
            "append": [
                "[--name-conflict fail|rename|merge|replace]",
                "[--replace-owner-handle <bound-existing-owner-handle>]",
                "[--platform <exact-user-platform>]",
                "[--add-to-source-control|--no-add-to-source-control]",
            ],
        }
        return {
            **shared,
            "required_next_phase": (
                "declare_remaining_named_objects_or_check_complete_graph"
                if session.declarations
                else "declare_named_object_or_discover_long_tail_kind"
            ),
            "type_discovery": type_discovery,
            "field_discovery": field_discovery,
            "configure": configure,
            "declaration": declare,
            "completion_candidate": {
                "condition": "all_user_requested_named_objects_are_declared",
                "fixed_full_argv": check,
                "copy_command": operation_draft_copy_command(check),
                "is_next_command_when_condition_true": bool(session.declarations),
            },
        }
    if not (adapter.supports_field_binding or adapter.supports_field_discovery):
        if session.declarations:
            return {
                "contract": "waapi-skill.business-draft-next-action/v1",
                "required_next_phase": "check_complete_business_declaration",
                "business_contract": business_contract,
                "check": {
                    **operation_draft_prefix_copy_binding(check),
                    "append": [],
                },
                "forbidden_inputs": forbidden_inputs,
                "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
                "then_read_next_response": True,
                "precompute_or_increment_revision": False,
            }
        return {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "required_next_phase": (
                "bind_remaining_business_objects_then_declare_complete_object_change"
                if len(session.handles.as_dict()["objects"])
                < len(business_contract["binding"]["roles"])
                else "declare_complete_object_change"
            ),
            "responsibility_split": {
                "agent": "natural_language_to_closed_high_level_business_facts",
                "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
            },
            "business_contract": business_contract,
            "object_binding": object_binding,
            "declaration": {
                **operation_draft_prefix_copy_binding(
                    declare_object_change_prefix
                ),
                "append_fields": business_contract["declaration"],
                "submit_once": True,
            },
            "forbidden_inputs": forbidden_inputs,
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
        }
    if adapter.supports_field_discovery:
        if record.operation == "object.setRTPC":
            handle_state = session.handles.as_dict()
            bound_objects = handle_state["objects"]
            bound_fields = handle_state["fields"]
            shared = {
                "contract": "waapi-skill.business-draft-next-action/v1",
                "responsibility_split": {
                    "agent": "natural_language_to_closed_high_level_business_facts",
                    "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
                },
                "business_contract": business_contract,
                "forbidden_inputs": [
                    *forbidden_inputs,
                    "property_token",
                    "rtpc_list_row",
                    "native_curve_fragment",
                ],
                "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
                "then_read_next_response": True,
                "precompute_or_increment_revision": False,
            }
            if session.declarations:
                return {
                    **shared,
                    "required_next_phase": "check_complete_business_declaration",
                    "check": {
                        **operation_draft_prefix_copy_binding(check),
                        "append": [],
                    },
                }
            if not bound_fields:
                discovery = {
                    **operation_draft_prefix_copy_binding(field_discover_prefix),
                    "append": [
                        "--object-handle",
                        "<bound-rtpc-owner-handle>",
                        "--meaning",
                        "<user-facing-rtpc-property-meaning>",
                    ],
                    "result": "copy_one_returned_property_candidate.handle",
                    "token_input": "forbidden",
                }
                return {
                    **shared,
                    "required_next_phase": "discover_rtpc_property_for_bound_object",
                    "field_discovery": discovery,
                    "object_binding": object_binding,
                }
            if len(bound_objects) < 2:
                return {
                    **shared,
                    "required_next_phase": "bind_rtpc_control_input",
                    "object_binding": {
                        **object_binding,
                        "use_only_for": ["control_input"],
                    },
                }
            return {
                **shared,
                "required_next_phase": "declare_complete_rtpc_curve",
                "declaration": {
                    **operation_draft_prefix_copy_binding(declare_rtpc_prefix),
                    "append": [
                        "--object-handle",
                        "<bound-rtpc-owner-handle>",
                        "--field-handle",
                        "<selected-property-handle>",
                        "--control-input-handle",
                        "<bound-control-input-handle>",
                        "--point",
                        "<x>",
                        "<y>",
                        "<Wwise-shape>",
                        "[--point <x> <y> <Wwise-shape>]...",
                        "[--mode add-only|add-or-update]",
                        "[--notes <exact-user-notes>]",
                    ],
                    "submit_once": True,
                },
            }
        if session.declarations:
            return {
                "contract": "waapi-skill.business-draft-next-action/v1",
                "required_next_phase": "check_complete_business_declaration",
                "business_contract": business_contract,
                "check": {
                    **operation_draft_prefix_copy_binding(check),
                    "append": [],
                },
                "forbidden_inputs": forbidden_inputs,
                "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
                "then_read_next_response": True,
                "precompute_or_increment_revision": False,
            }
        handle_state = session.handles.as_dict()
        bound_objects = handle_state["objects"]
        bound_fields = handle_state["fields"]
        field_discovery = {
            **operation_draft_prefix_copy_binding(field_discover_prefix),
            "append": [
                "--object-handle",
                "<bound-target-object-handle>",
                "--meaning",
                "<user-facing-field-meaning>",
                "[--platform <exact-user-requested-platform>]",
            ],
            "result": "copy_one_returned_field_candidate.handle",
            "token_input": "forbidden",
            "refine_only_when": "returned_candidates_do_not_identify_user_intent",
        }
        declaration_prefix = {
            **operation_draft_prefix_copy_binding(
                declare_field_change_prefix
            ),
            "submit_once": True,
        }
        shared = {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "responsibility_split": {
                "agent": "natural_language_to_closed_high_level_business_facts",
                "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
            },
            "business_contract": business_contract,
            "forbidden_inputs": [
                *forbidden_inputs,
                "property_token",
                "reference_token",
                "field_scope",
                "field_wire_type",
            ],
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
        }
        if not bound_fields:
            return {
                **shared,
                "required_next_phase": "discover_field_for_bound_object",
                "field_discovery": field_discovery,
            }
        if record.operation == "object.setReference" and len(bound_objects) < 2:
            clear_declaration = {
                **declaration_prefix,
                "append": [
                    "--object-handle",
                    "<bound-source-object-handle>",
                    "--field-handle",
                    "<selected-field-handle>",
                    "--clear-reference",
                ],
            }
            return {
                **shared,
                "required_next_phase": "choose_clear_or_bind_reference_target",
                "decision": {
                    "clear": clear_declaration,
                    "set_target": "bind_the_exact_reference_target_then_read_next_response",
                },
                "object_binding": {
                    **object_binding,
                    "use_only_for": ["reference_target"],
                },
            }
        if record.operation == "object.setProperty":
            declaration_append = [
                "--object-handle",
                "<bound-source-object-handle>",
                "--field-handle",
                "<selected-field-handle>",
                "--business-value",
                "<user-requested-business-value>",
            ]
        elif record.operation == "object.setReference":
            declaration_append = [
                "--object-handle",
                "<bound-source-object-handle>",
                "--field-handle",
                "<selected-field-handle>",
                "--target-handle",
                "<bound-reference-target-handle>",
            ]
        else:
            declaration_append = [
                "--object-handle",
                "<bound-source-object-handle>",
                "--field-handle",
                "<selected-field-handle>",
                "--link-state",
                "<linked-or-unlinked>",
            ]
        return {
            **shared,
            "required_next_phase": "declare_complete_field_change",
            "declaration": {
                **declaration_prefix,
                "append": declaration_append,
            },
        }
    if adapter.family == "audio-import":
        audio_object_binding = {
            **object_binding,
            "use_only_for": [
                "existing_import_row_target",
                "new_import_row_parent",
                "output_bus_reference",
                "new_event_parent",
                "custom_reference_value",
            ],
            "forbidden_for": [
                "switch_group",
                "switch_value",
                "preservation_only_object",
            ],
        }
        return {
            "contract": "waapi-skill.business-draft-next-action/v1",
            "required_next_phase": (
                "bind_only_additional_handle_typed_business_values_then_submit_"
                "one_complete_import_batch"
            ),
            "object_binding": audio_object_binding,
            "field_binding": {
                "object_scope": {
                    **operation_draft_prefix_copy_binding(field_bind_prefix),
                    "append": [
                        "--object-handle",
                        "<bound-object-handle>",
                        "--token",
                        "<exact-live-field-token>",
                    ],
                },
                "class_scope": {
                    **operation_draft_prefix_copy_binding(field_bind_prefix),
                    "append": [
                        "--class-name",
                        "<exact-live-class-name>",
                        "--token",
                        "<exact-live-field-token>",
                    ],
                },
                "use_only_for": "custom_property_or_reference_field_values",
            },
            "configure": {
                **operation_draft_prefix_copy_binding(configure_prefix),
                "append": [
                    "[--mode replace]",
                    "[--add-to-source-control|--no-add-to-source-control]",
                    "[--check-out-from-source-control|--no-check-out-from-source-control]",
                    "[--default <stable-field> <business-value>]...",
                    "[--default-field-value <bound-field-handle> <business-value>]...",
                ],
                "use_only_when": (
                    "the_user_explicitly_requests_batch_settings_or_defaults"
                ),
            },
            "declare_import_batch": {
                **operation_draft_prefix_copy_binding(
                    declare_import_batch_prefix
                ),
                "closure": [
                    "--expected-declaration-count",
                    "<count-of-all-user-requested-import-rows>",
                    "--expected-switch-assignment-count",
                    "<count-of-all-user-requested-switch-assignments>",
                ],
                "row_order": [
                    "--row-order",
                    "<declaration-id>",
                    "repeat_once_per_row_in_exact_import_order",
                ],
                "row_forms": {
                    "new": [
                        "--new-row",
                        "<id>",
                        "<bound-parent-handle-or-earlier-parent-id>",
                        "<name>",
                        "<semantic-kind>",
                    ],
                    "existing": [
                        "--existing-row",
                        "<id>",
                        "<bound-existing-object-handle>",
                    ],
                },
                "row_fields": {
                    "stable": [
                        "--field",
                        "<id>",
                        "<stable-field-except-switch_value>",
                        "<business-value>",
                    ],
                    "custom": [
                        "--field-value",
                        "<id>",
                        "<bound-field-handle>",
                        "<business-value>",
                    ],
                    "switch_assignment": [
                        "--switch-value",
                        "<id>",
                        "<exact-user-requested-switch-value>",
                    ],
                    "event": [
                        "--event",
                        "<id>",
                        "<bound-event-parent-handle>",
                        "<event-name>",
                        "<Play|Stop|Pause|Resume|Break|Seek>",
                    ],
                },
                "media_source": {
                    "directory": [
                        "--media-directory",
                        "<one-absolute-source-directory>",
                    ],
                    "file": [
                        "--media-file",
                        "<id>",
                        "<one-file-name-without-separators>",
                    ],
                    "rule": (
                        "when two or more requested media files share a directory, "
                        "copy that directory once and submit one leaf file name per row"
                    ),
                },
                "complete_on_first_submission": True,
                "submit_once": True,
            },
            "forbidden_inputs": forbidden_inputs,
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
            "then_read_next_response": True,
            "precompute_or_increment_revision": False,
        }
    return {
        "contract": "waapi-skill.business-draft-next-action/v1",
        "required_next_phase": (
            "bind_only_handle_typed_business_objects_then_configure_and_declare"
            if session is None
            else "complete_business_declarations_then_check"
        ),
        "responsibility_split": {
            "agent": "natural_language_to_closed_high_level_business_facts",
            "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
        },
        "business_contract": business_contract,
        "object_binding": object_binding,
        "field_binding": {
            "object_scope": {
                **operation_draft_prefix_copy_binding(field_bind_prefix),
                "append": [
                    "--object-handle",
                    "<bound-object-handle>",
                    "--token",
                    "<exact-live-field-token>",
                ],
            },
            "class_scope": {
                **operation_draft_prefix_copy_binding(field_bind_prefix),
                "append": [
                    "--class-name",
                    "<exact-live-class-name>",
                    "--token",
                    "<exact-live-field-token>",
                ],
            },
            "result": "copy_the_returned_bound_field.handle_and_restrictions",
            "use_only_for": "custom_property_or_reference_field_values",
        },
        "binding_decision": {
            "bound_object_handle_fields": [
                "output_bus",
                "event_parent",
                "custom_reference_value",
            ],
            "literal_never_bind": [
                "audio_source_notes",
                "dialogue_event_directive",
                "inline_wav",
                "language",
                "loop",
                "max_instances",
                "media_file",
                "notes",
                "originals_subfolder",
                "override_parent_instance_limit",
                "switch_value",
                "volume_db",
            ],
            "rule": "bind_only_when_the_disclosed_value_type_requires_a_handle",
        },
        "configure": {
            **operation_draft_prefix_copy_binding(configure_prefix),
            "append": [
                "[--mode replace] only_for_explicit_replacement; "
                "create_and_reimport_derive_from_target_form",
                "[--add-to-source-control|--no-add-to-source-control]",
                "[--check-out-from-source-control|--no-check-out-from-source-control]",
            ],
        },
        "explicit_global_defaults": {
            **operation_draft_prefix_copy_binding(configure_prefix),
            "append": [
                "[--default <stable-field> <business-value>]...",
                "[--default-field-value <bound-field-handle> <business-value>]...",
            ],
            "use_only_when": (
                "user_explicitly_requests_a_Wwise_global_batch_default"
            ),
            "scope": "every_declaration_in_the_batch_after_expansion",
            "reference_default_rule": (
                "copy_one_bound_object_handle_never_a_path_or_name"
            ),
            "default_use_rule": (
                "use_only_when_the_user_explicitly_requests_one_value_for_every_"
                "declaration_and_the_field_is_valid_for_every_target_kind; otherwise_"
                "put_the_field_on_each_applicable_declaration"
            ),
        },
        "declare_new": {
            **operation_draft_prefix_copy_binding(declare_new_prefix),
            "append": [
                "--declaration-id",
                "<task-local-id>",
                "--parent-handle",
                "<bound-or-planned-object-handle>",
                "--name",
                "<child-name>",
                "--kind",
                "<semantic-kind>",
                "--switch-value <exact-user-requested-switch-value> "
                "required_when_user_requests_this_declaration_be_assigned_to_a_"
                "switch_value; omission_is_incomplete",
                "[--field <stable-field-except-switch_value> <business-value>]...",
                "[--field-value <bound-field-handle> <business-value>]...",
            ],
            "task_local_id": "bounded_unique_not_business_data",
            "known_user_fields": "complete_on_first_submission",
            "conditional_required_user_fields": {
                "switch_assignment": {
                    "argument": "--switch-value",
                    "value": "exact_user_requested_switch_value",
                    "required_when": (
                        "user_requests_this_declaration_be_assigned_to_a_switch_value"
                    ),
                    "omission": "incomplete_declaration",
                }
            },
        },
        "declare_existing": {
            **operation_draft_prefix_copy_binding(declare_existing_prefix),
            "append": [
                "--declaration-id",
                "<task-local-id>",
                "--object-handle",
                "<bound-object-handle>",
                "--switch-value <exact-user-requested-switch-value> "
                "required_when_user_requests_this_declaration_be_assigned_to_a_"
                "switch_value; omission_is_incomplete",
                "[--field <stable-field-except-switch_value> <business-value>]...",
                "[--field-value <bound-field-handle> <business-value>]...",
            ],
            "task_local_id": "bounded_unique_not_business_data",
            "known_user_fields": "complete_on_first_submission",
            "conditional_required_user_fields": {
                "switch_assignment": {
                    "argument": "--switch-value",
                    "value": "exact_user_requested_switch_value",
                    "required_when": (
                        "user_requests_this_declaration_be_assigned_to_a_switch_value"
                    ),
                    "omission": "incomplete_declaration",
                }
            },
        },
        "revise": {
            **operation_draft_prefix_copy_binding(revise_prefix),
            "append": [
                "--declaration-id",
                "<existing-task-local-id>",
                "[--switch-value <corrected-exact-user-requested-switch-value>]",
                "[--field <stable-field-except-switch_value> <corrected-business-value>]...",
                "[--field-value <bound-field-handle> <corrected-business-value>]...",
            ],
            "use_only_for": "correction_or_late_discovered_fact",
        },
        "remove": {
            **operation_draft_prefix_copy_binding(remove_prefix),
        },
        "completion_candidate": {
            "condition": "all_user_requested_business_declarations_are_complete",
            "fixed_full_argv": check,
            "copy_command": operation_draft_copy_command(check),
            "is_next_command_when_condition_true": bool(
                session is not None and session.declarations
            ),
        },
        "forbidden_inputs": forbidden_inputs,
        "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
        "then_read_next_response": True,
        "precompute_or_increment_revision": False,
    }


def _operation_draft_node_batch_continuation(
    actions: Sequence[Mapping[str, Any]],
    *,
    operation: str,
    version: str,
) -> dict[str, Any] | None:
    """Resume the disclosed child after one atomic parent-plus-node batch."""

    if len(actions) < 2:
        return None
    parent_fact = actions[0]
    response_handle = parent_fact.get("value")
    if (
        parent_fact.get("action") != "add_typed_fact"
        or parent_fact.get("fact_action") not in {"append", "map-put", "set"}
        or not isinstance(response_handle, str)
        or not response_handle.startswith("trm1-")
    ):
        return None
    reachable_handles = {response_handle}
    for row in actions[1:]:
        if (
            row.get("action") != "add_typed_fact"
            or row.get("field_handle") not in reachable_handles
        ):
            return None
        nested_handle = row.get("value")
        if (
            row.get("fact_action") in {"append", "map-put", "set"}
            and isinstance(nested_handle, str)
            and nested_handle.startswith("trm1-")
        ):
            reachable_handles.add(nested_handle)
    return {
        "source": "most_recent_typed_container_handle_response",
        "response_was_complete_not_truncated": True,
        "current_handle": response_handle,
        "completed_fact_action": "batch",
        "next_rule": (
            "resume_previous_container_response_after_current_node_fact_batch"
        ),
        "stop_cancel_or_claim_truncation_before_current_root_is_complete": (
            "invalid"
        ),
        "resume_previous_container_response": (
            _operation_draft_resume_previous_container_payload(
                response_handle=response_handle,
                completed_candidate="current_node_fact_batch",
                operation=operation,
                version=version,
                actions=actions,
            )
        ),
    }


def _operation_draft_root_array_next_item_disclosure(
    *,
    operation: str,
    version: str,
    actions: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Carry the exact next direct-root array command across child receipts."""

    if not actions:
        return None
    parent_fact = actions[0]
    candidate_handles = {
        value
        for value in (parent_fact.get("field_handle"), parent_fact.get("value"))
        if isinstance(value, str) and value.startswith("trm1-")
    }
    if not candidate_handles:
        return None
    contract = draft_operation_request_contract(operation, version)
    for field in contract.fields:
        if field.parent_handle is not None or field.shape != "array":
            continue
        for index in range(MAX_TYPED_ARRAY_ITEMS):
            matched = False
            for shape in ("object", "array"):
                choices = dynamic_array_item_choices(
                    contract,
                    array_handle=field.handle,
                    index=index,
                    shape=shape,
                )
                if len(choices) != 1:
                    continue
                current_handle = dynamic_array_item_handle(
                    contract,
                    array_handle=field.handle,
                    index=index,
                    shape=shape,
                )
                if current_handle in candidate_handles:
                    matched = True
                    break
            if not matched:
                continue
            next_index = index + 1
            if next_index >= MAX_TYPED_ARRAY_ITEMS:
                return None
            copy_command_by_shape: dict[str, str] = {}
            for shape in ("object", "array"):
                choices = dynamic_array_item_choices(
                    contract,
                    array_handle=field.handle,
                    index=next_index,
                    shape=shape,
                )
                if len(choices) != 1:
                    continue
                copy_command_by_shape[shape] = operation_draft_copy_command(
                    [
                        "python",
                        str(GATEWAY_RUNNER_PATH),
                        "gateway.py",
                        "request-array-item",
                        operation,
                        "--schema-digest",
                        contract.schema_digest,
                        "--array-handle",
                        field.handle,
                        "--index",
                        str(next_index),
                        "--shape",
                        shape,
                    ]
                )
            if not copy_command_by_shape:
                return None
            return {
                "condition": "current_business_request_contains_next_complex_item",
                "business_cardinality_authority": "current_business_request",
                "index": next_index,
                "copy_command_by_shape": copy_command_by_shape,
            }
    return None


def _operation_draft_current_item_business_sibling(
    *,
    operation: str,
    version: str,
    actions: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Reissue the exact schema sibling after one connected branch subtree."""

    if not actions:
        return None
    parent_fact = actions[0]
    candidate_handles = {
        value
        for value in (parent_fact.get("field_handle"), parent_fact.get("value"))
        if isinstance(value, str) and value.startswith("trm1-")
    }
    if not candidate_handles:
        return None
    contract = draft_operation_request_contract(operation, version)
    for field in contract.fields:
        if field.parent_handle is not None or field.shape != "array":
            continue
        for index in range(MAX_TYPED_ARRAY_ITEMS):
            for item_shape in ("object", "array"):
                choices = dynamic_array_item_choices(
                    contract,
                    array_handle=field.handle,
                    index=index,
                    shape=item_shape,
                )
                if len(choices) != 1:
                    continue
                item_handle = dynamic_array_item_handle(
                    contract,
                    array_handle=field.handle,
                    index=index,
                    shape=item_shape,
                )
                if item_handle not in candidate_handles:
                    continue
                item_disclosure = dynamic_container_disclosure(
                    contract,
                    parent_handle=field.handle,
                    key=str(index),
                    shape=item_shape,
                    child_handle=item_handle,
                )
                item_schema = item_disclosure.get("schema_lineage")
                if not isinstance(item_schema, Mapping):
                    return None
                item_lineage_token = typed_schema_lineage_token(
                    contract,
                    child_handle=item_handle,
                    parent_token=None,
                    parent_handle=field.handle,
                    key=str(index),
                    shape=item_shape,
                    choice_handle=None,
                )
                for branch in actions[1:]:
                    branch_key = branch.get("key")
                    branch_choice = branch.get("value")
                    if (
                        branch.get("action") != "add_typed_fact"
                        or branch.get("fact_action") != "choose-dynamic"
                        or branch.get("field_handle") != item_handle
                        or not isinstance(branch_key, str)
                        or not isinstance(branch_choice, str)
                    ):
                        continue
                    children = tuple(
                        row
                        for row in actions[1:]
                        if row.get("action") == "add_typed_fact"
                        and row.get("fact_action") == "map-put"
                        and row.get("field_handle") == item_handle
                        and row.get("key") == branch_key
                        and row.get("value_type") in {"object", "array"}
                        and isinstance(row.get("value"), str)
                    )
                    if len(children) != 1:
                        return None
                    child = children[0]
                    child_shape = str(child["value_type"])
                    child_handle = str(child["value"])
                    choice_rows = dynamic_map_container_choices(
                        contract,
                        map_handle=item_handle,
                        key=branch_key,
                        shape=child_shape,
                        parent_schema=item_schema,
                        parent_section=field.section,
                    )
                    if not any(
                        choice_handle == branch_choice
                        for choice_handle, _choice_index, _variant in choice_rows
                    ):
                        return None
                    expected_child_handle = dynamic_map_entry_handle(
                        contract,
                        map_handle=item_handle,
                        key=branch_key,
                        shape=child_shape,
                        choice_handle=branch_choice,
                        parent_schema=item_schema,
                        parent_section=field.section,
                    )
                    if child_handle != expected_child_handle:
                        return None
                    child_lineage_token = typed_schema_lineage_token(
                        contract,
                        child_handle=child_handle,
                        parent_token=item_lineage_token,
                        parent_handle=item_handle,
                        key=branch_key,
                        shape=child_shape,
                        choice_handle=branch_choice,
                    )
                    try:
                        business_pointer = typed_schema_lineage_business_pointer(
                            contract,
                            child_handle=child_handle,
                            token=child_lineage_token,
                        )
                    except TypedRequestError:
                        return None
                    sibling = _next_map_sibling_disclosure(
                        argparse.Namespace(
                            command="request-map-container",
                            parent_schema_token=item_lineage_token,
                            key=branch_key,
                            shape=child_shape,
                            map_handle=item_handle,
                            api=operation,
                        ),
                        contract=contract,
                        parent_schema=item_schema,
                        parent_section=field.section,
                        current_business_value_pointer=business_pointer,
                    )
                    projected = _dynamic_disclosure_copy_commands(sibling)
                    transition = projected.get("business_sibling_transition")
                    return dict(transition) if isinstance(transition, Mapping) else None
                return None
    return None


def _operation_draft_resume_previous_container_payload(
    *,
    response_handle: str,
    completed_candidate: str,
    operation: str,
    version: str,
    actions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": "waapi-skill.typed-container-handle/v1",
        "response_handle": response_handle,
        "completed_candidate": completed_candidate,
        "decision_pointer": "/continuation/next_command_decision/evaluate_in_order",
        "selection": "first_remaining_business_present_candidate_in_order",
        "continue_in_same_turn": True,
        "after_exhausted": "resume_ancestor_response_stack",
        "ancestor_resume_gate": (
            "current_response_and_all_descendant_business_candidates_exhausted"
        ),
        "ancestor_next_item_source": "next_item_disclosure.copy_command_by_shape",
        "retype_schema_digest": "invalid",
    }
    business_sibling = _operation_draft_current_item_business_sibling(
        operation=operation,
        version=version,
        actions=actions,
    )
    if business_sibling is not None:
        payload["decision_pointer"] = "/business_sibling_transition"
        payload["selection"] = "business_present_sibling_before_ancestor_item"
        payload["business_sibling_transition"] = business_sibling
    disclosure = _operation_draft_root_array_next_item_disclosure(
        operation=operation,
        version=version,
        actions=actions,
    )
    if disclosure is not None:
        payload["ancestor_next_item_source"] = (
            "ancestor_next_item_disclosure.copy_command_by_shape"
        )
        payload["ancestor_next_item_disclosure"] = disclosure
    return payload


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
        if fact_action == "map-put" and dynamic_value is not None:
            continuation["next_rule"] = (
                "resume_previous_container_response_after_deferred_fact_queue"
            )
            continuation["resume_previous_container_response"] = (
                _operation_draft_resume_previous_container_payload(
                    response_handle=dynamic_value,
                    completed_candidate="deferred_fact_queue",
                    operation=record.operation,
                    version=record.version,
                    actions=actions,
                )
            )
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
            if command == "draft-check" and not operation_uses_business_declaration(
                record.operation,
                record.version,
            ):
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
                batch_continuation = _operation_draft_node_batch_continuation(
                    compact_actions,
                    operation=record.operation,
                    version=record.version,
                )
                if batch_continuation is None:
                    action_result.pop("construction_continuation", None)
                else:
                    action_result["construction_continuation"] = batch_continuation
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
    projection = operation_draft_public_projection(projection)
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
    if (
        record.state is OperationDraftState.EDITABLE
        and operation_uses_business_declaration(
            record.operation,
            record.version,
        )
    ):
        next_action_binding = _business_next_action_binding(
            record,
            task_authority=task_authority,
        )
        adapter = business_adapter(record.operation)
        if (
            command == "draft-bind-object"
            and adapter.role_declaration is not None
            and record.check is None
        ):
            next_action_binding = {
                key: next_action_binding[key]
                for key in (
                    "contract",
                    "required_next_phase",
                    "object_binding",
                    "declaration",
                    "check",
                    "shell_tool_timeout_ms",
                    "then_read_next_response",
                    "precompute_or_increment_revision",
                )
                if key in next_action_binding
            }
            draft = {
                key: draft[key]
                for key in (
                    "contract",
                    "draft_id",
                    "lifecycle_state",
                    "revision",
                    "binding",
                    "business_revision",
                )
                if key in draft
            }
            draft["response_integrity"] = {
                "complete": True,
                "truncated": False,
                "projection": "bound_role_and_singular_continuation",
                "compact_projection_is_not_truncation": True,
            }
        if (
            record.operation == "audio.import"
            and record.check is None
            and command == "draft-declare-import-batch"
        ):
            declarations = draft.get("declarations")
            if not isinstance(declarations, list) or not declarations:
                raise GatewayInputError(
                    "Audio import batch receipt is unavailable."
                )
            check_argv = [
                "python",
                str(GATEWAY_RUNNER_PATH),
                "gateway.py",
                "draft-check",
                record.draft_id,
                "--task-authority",
                task_authority or "<task-authority-from-draft-start>",
                "--expected-revision",
                str(record.revision),
            ]
            next_action_binding = {
                "contract": "waapi-skill.business-draft-next-action/v1",
                "required_next_phase": "check_complete_business_declaration",
                "check": {
                    **operation_draft_prefix_copy_binding(check_argv),
                    "append": [],
                },
                "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
                "then_read_next_response": True,
                "precompute_or_increment_revision": False,
            }
            draft = {
                key: draft[key]
                for key in (
                    "contract",
                    "draft_id",
                    "lifecycle_state",
                    "revision",
                    "binding",
                    "business_revision",
                )
                if key in draft
            }
            declaration_ids = [
                row.get("declaration_id")
                for row in declarations
                if isinstance(row, Mapping)
            ]
            if (
                len(declaration_ids) != len(declarations)
                or not all(isinstance(value, str) for value in declaration_ids)
            ):
                raise GatewayInputError(
                    "Audio import batch receipt has invalid declaration identities."
                )
            switch_assignment_count = sum(
                1
                for row in declarations
                if isinstance(row, Mapping)
                and isinstance(row.get("fields"), Mapping)
                and "switch_value" in row["fields"]
            )
            draft["batch_receipt"] = {
                "contract": (
                    "waapi-skill.business-declaration-batch-receipt/v1"
                ),
                "declaration_count": len(declarations),
                "switch_assignment_count": switch_assignment_count,
                "declaration_ids": declaration_ids,
            }
            draft["declarations_summary"] = {
                "count": len(declarations),
                "canonical_sha256": canonical_sha256(declarations),
            }
            draft["response_integrity"] = {
                "complete": True,
                "truncated": False,
                "projection": "business_declaration_batch_receipt_and_check",
                "compact_projection_is_not_truncation": True,
            }
            draft["next_command"] = transaction_next_command(
                "draft-check",
                check_argv[3:],
            )
        elif (
            record.operation == "audio.import"
            and record.check is None
            and command in {"draft-declare-new", "draft-declare-existing"}
        ):
            declarations = draft.get("declarations")
            if not isinstance(declarations, list) or not declarations:
                raise GatewayInputError(
                    "Audio import declaration receipt is unavailable."
                )
            check_argv = [
                "python",
                str(GATEWAY_RUNNER_PATH),
                "gateway.py",
                "draft-check",
                record.draft_id,
                "--task-authority",
                task_authority or "<task-authority-from-draft-start>",
                "--expected-revision",
                str(record.revision),
            ]
            next_action_binding = {
                "contract": "waapi-skill.business-draft-next-action/v1",
                "required_next_phase": "check_complete_business_declaration",
                "check": {
                    **operation_draft_prefix_copy_binding(check_argv),
                    "append": [],
                },
                "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
                "then_read_next_response": True,
                "precompute_or_increment_revision": False,
            }
            draft = {
                key: draft[key]
                for key in (
                    "contract",
                    "draft_id",
                    "lifecycle_state",
                    "revision",
                    "binding",
                    "business_revision",
                )
                if key in draft
            }
            draft["declaration_receipt"] = declarations[-1]
            draft["declarations_summary"] = {
                "count": len(declarations),
                "canonical_sha256": canonical_sha256(declarations),
            }
            draft["response_integrity"] = {
                "complete": True,
                "truncated": False,
                "projection": "business_declaration_receipt_and_continuation",
                "compact_projection_is_not_truncation": True,
            }
        draft["next_action_binding"] = next_action_binding
        draft["agent_control"] = {
            "terminal": False,
            "required_outcome_before_reply": "preview_or_structured_refusal",
            "next": "follow_next_action_binding",
            "reply_or_claim_preview_now": "invalid",
        }
        return {
            "contract": GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": record.state.value,
            "command": command,
            "offline": offline,
            "draft": draft,
        }
    if record.state is OperationDraftState.EDITABLE:
        generic_typed_draft = record.operation.startswith("ak.") or (
            record.operation in DRAFT_TYPED_OPERATIONS
            and record.operation != "waapi.undoGroup"
        )
        next_action_binding: dict[str, Any] = {
            "contract": "waapi-skill.operation-draft-next-action/v1",
            "shell_tool_timeout_ms": GATEWAY_SHELL_TOOL_TIMEOUT_MS,
        }
        if (
            command == "draft-start"
            and compact_actions is None
            and record.check is None
            and not generic_typed_draft
        ):
            composer_input = operation_composer_input_contract(
                record.operation,
                record.version,
            )
            apply_contract = require_mapping(
                composer_input.get("apply"),
                "operation Composer apply contract",
            )
            action_argv = require_mapping(
                apply_contract.get("action_argv"),
                "operation Composer action argv",
            )
            allowed_actions = draft.get("allowed_actions")
            if not isinstance(allowed_actions, list):
                raise GatewayInputError(
                    "Editable operation Draft lacks its allowed actions."
                )
            allowed_action_argv = {
                action: list(action_argv[action])
                for action in allowed_actions
                if isinstance(action, str) and action in action_argv
            }
            if allowed_action_argv:
                next_action_binding["allowed_action_argv"] = allowed_action_argv
                next_action_binding["action_argv_discipline"] = {
                    "source": "allowed_action_argv[action-name]",
                    "copy_placeholder_positions_exactly": True,
                    "insert_type_only_where_template_contains_TYPE": True,
                }
            if (
                operation_uses_business_declaration(
                    record.operation,
                    record.version,
                )
                and business_adapter(
                    record.operation
                ).requires_wwise_path_discipline
            ):
                next_action_binding["wwise_path_discipline"] = {
                    "parent_source": "exact_user_supplied_business_path",
                    "append_descendant": (
                        "one_literal_backslash_before_each_child_name"
                    ),
                    "remove_or_normalize_existing_separators": "invalid",
                }
        if generic_typed_draft:
            typed_draft_contract = (
                request_contract(record.version, record.operation)
                if record.operation.startswith("ak.")
                else draft_operation_request_contract(
                    record.operation,
                    record.version,
                )
            )
            next_action_binding["typed_fact_batch_discipline"] = {
                "batch_size": "6 until fewer than 6 facts remain",
                "final_batch": (
                    "include every remaining complete action; never split"
                ),
                "top_level_facts_before_dynamic_disclosure": True,
                "branch_choice_requires_selected_branch_facts": True,
                "schema_candidates_without_business_values": "skip",
            }
            next_action_binding["selected_branch_fact_completion"] = {
                "choose_only": "invalid",
                "same_batch_before_next_top_level_fact": True,
                "path_selector_exact_sequence": [
                    "choose branch handle with the path choice handle",
                    "set selected path choice kind handle to string path",
                    "set selected path choice value handle to the exact business path",
                ],
                "exact_type_name_selector_exact_sequence": [
                    "choose branch handle with the exact-type-name choice handle",
                    "set selected choice kind handle to string exact-type-name",
                    "set selected choice type handle to the exact business object type",
                    "set selected choice name handle to the exact business object name",
                ],
                "copy_handles_from_operation_schema_exactly": True,
            }
            root_disclosures = _root_dynamic_disclosure_commands(
                typed_draft_contract
            )
            if root_disclosures["rows"]:
                next_action_binding["root_dynamic_disclosure_commands"] = (
                    root_disclosures
                )
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
        if generic_typed_draft:
            next_action_binding["prompt_fact_completion_guard"] = {
                "schema_optional_is_not_evidence_of_prompt_absence": True,
                "account_for_every_prompt_present_scalar_array_item_and_map_entry": True,
                "copy_boolean_values_exactly": True,
                "infer_or_replace_prompt_values": "invalid",
            }
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
            draft_apply_prefix = [
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
            ]
            if compact_actions is None:
                next_action_binding.update(
                    operation_draft_prefix_copy_binding(draft_apply_prefix)
                )
            else:
                next_action_binding["fixed_argv_prefix"] = draft_apply_prefix
            next_action_binding.update(
                {
                    "append_every_next_complete_handle_ready_typed_action_until_limit_or_new_handle_dependency": [
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
            resume_previous = (
                construction_continuation.get(
                    "resume_previous_container_response"
                )
                if isinstance(construction_continuation, Mapping)
                else None
            )
            if isinstance(resume_previous, Mapping):
                for stale_key in (
                    "typed_fact_batch_discipline",
                    "selected_branch_fact_completion",
                    "root_dynamic_disclosure_commands",
                    "next_phase_decision",
                ):
                    next_action_binding.pop(stale_key, None)
                next_action_binding["resume_previous_container_response"] = dict(
                    resume_previous
                )
            if (
                compact_actions is not None
                and draft.get("schema_required_fields_status") == "complete"
            ):
                completion_argv = [
                    "python",
                    str(GATEWAY_RUNNER_PATH),
                    "gateway.py",
                    "draft-check",
                    record.draft_id,
                    "--task-authority",
                    task_authority or "<task-authority-from-draft-start>",
                    "--expected-revision",
                    str(record.revision),
                ]
                completion_candidate = {
                    "condition": (
                        "all_current_business_request_facts_and_disclosures_submitted"
                    ),
                    "business_completion_check": {
                        "source": "current_user_business_request",
                        "schema_required_fields_complete_is_insufficient": True,
                        "all_user_present_optional_map_and_constant_facts_required": True,
                        "exact_values_and_object_types_required": True,
                    },
                    "is_next_command_when_condition_true": True,
                    "fixed_argv_prefix": completion_argv,
                    "copy_exactly": True,
                    "copy_instruction": {
                        "contract": (
                            OPERATION_DRAFT_COMMAND_COPY_INSTRUCTION_CONTRACT
                        ),
                        "source_field": "copy_command",
                        "action": "execute_verbatim_as_one_shell_tool_call",
                        "forbidden_transformations": [
                            "reconstruct",
                            "shorten",
                            "normalize",
                            "substitute_path_segments",
                            "select_another_field",
                        ],
                    },
                    "copy_command": operation_draft_copy_command(
                        completion_argv
                    ),
                    "allowed_suffix_source": (
                        "request_schema_terminal_arguments_only"
                    ),
                    "draft_apply_action_check": "invalid",
                    "when_condition_false": (
                        "continue_with_one_atomic_typed_action_batch_or_dynamic_disclosure"
                    ),
                }
                if generic_typed_draft:
                    terminal_arguments = typed_draft_contract.as_gateway_payload().get(
                        "result_filter"
                    )
                    if isinstance(terminal_arguments, Mapping):
                        completion_candidate[
                            "request_schema_terminal_arguments"
                        ] = {
                            "source_pointer": "/request-schema/result_filter",
                            "append_before_execute": True,
                            "contract": dict(terminal_arguments),
                        }
                next_action_binding["completion_candidate"] = completion_candidate
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
        if compact_actions is not None and "completion_candidate" in next_action_binding:
            # A long generic composition can repeat several exact root
            # disclosure commands after every atomic fact batch.  Put the
            # terminal decision first so a caller that has finished every
            # business-present fact sees the complete draft-check command in
            # the bounded stdout prefix instead of mistaking the receipt for a
            # truncated continuation.
            contract_name = next_action_binding.pop("contract")
            completion_candidate = next_action_binding.pop(
                "completion_candidate"
            )
            next_action_binding = {
                "contract": contract_name,
                "completion_candidate": completion_candidate,
                **next_action_binding,
            }
        if not (command == "draft-check" and record.check is not None):
            priority_keys = (
                "contract",
                "required_next_phase",
                "fixed_argv_prefix_copy",
                "fixed_argv_prefix_copy_instruction",
                "next_phase_decision",
            )
            next_action_binding = {
                **{
                    key: next_action_binding[key]
                    for key in priority_keys
                    if key in next_action_binding
                },
                **{
                    key: value
                    for key, value in next_action_binding.items()
                    if key not in priority_keys
                },
            }
            draft["next_action_binding"] = next_action_binding
        if command in {"draft-start", "draft-apply"}:
            agent_control = {
                "terminal": False,
                "required_outcome_before_reply": (
                    "preview_or_structured_refusal"
                ),
                "next": "follow_next_action_binding",
                "reply_or_claim_preview_now": "invalid",
            }
            draft = {
                **{
                    key: draft[key]
                    for key in (
                        "contract",
                        "draft_id",
                        "lifecycle_state",
                        "revision",
                        "binding",
                    )
                },
                "agent_control": agent_control,
                **(
                    {"next_action_binding": draft["next_action_binding"]}
                    if "next_action_binding" in draft
                    else {}
                ),
                **{
                    key: value
                    for key, value in draft.items()
                    if key
                    not in {
                        "contract",
                        "draft_id",
                        "lifecycle_state",
                        "revision",
                        "binding",
                        "next_action_binding",
                    }
                },
            }
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
        TransactionState.EXECUTION_FAILED.value: "indeterminate",
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
    call_sink: list[dict[str, Any]] | None = None,
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
        if call_sink is not None:
            call_sink.append(dispatch_call_summary(result))
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
    if args.operation in {"attenuation", "attenuation-curve"}:
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
    if operation in {"attenuation", "attenuation-curve"}:
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
        stdout_payload = gateway_stdout_payload(payload)
        print(gateway_stdout_json_encoder(stdout_payload).encode(stdout_payload))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
