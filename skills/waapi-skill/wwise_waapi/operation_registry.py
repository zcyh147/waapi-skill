"""Closed JSON operations backed by semantic builders and live readbacks.

This module is the bridge between a model-facing JSON request and the existing
Python semantic builders.  It deliberately exposes no arbitrary URI, args,
options, Python kwargs, identity rows, or property metadata.  Every object role
is resolved live to exactly one canonical GUID before a mutating preview is
built, and every implemented operation has an operation-specific verifier.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, NoReturn, Sequence
from xml.etree import ElementTree as ET

from .canonical import canonical_json_bytes, canonical_sha256
from .business_adapters import business_adapter
from .builders.identity import ObjectIdentity, ResolvedObject, plan_object_resolution
from .builders.metadata import (
    GET_PROPERTY_AND_REFERENCE_NAMES_URI,
    GET_PROPERTY_INFO_URI,
    ObjectTypeMetadataRecord,
    PropertyInfoMetadataRecord,
    parse_get_types_result,
    parse_get_property_info_result,
)
from .builders.object_mutation import ObjectMutationBuilder
from .builders.properties import PropertyReferenceBuilder
from .builders.common import SemanticEnvelope, SemanticPreview, SemanticValidationError
from .builders.debug_lua import (
    CLI_LUA_RESERVED_FIELDS,
    CORE_LUA_RESERVED_FIELDS,
    DebugLuaContractError,
    LUA_SOURCE_AUTHORITY,
    MAX_LUA_SOURCE_BYTES,
    MAX_LUA_WA_ARGS_BYTES,
    MAX_LUA_WA_ARGS_KEYS,
    normalize_lua_wa_args,
    seal_inline_lua_source,
    seal_isolated_lua_file,
)
from .builders.schema import validate_semantic_payload, validate_semantic_result
from .builders.soundbank import SoundBankBuilder
from .builders.switchcontainer import SwitchContainerAssignmentBuilder
from .execution_contracts import ExecutionContractError, ExecutionContractRegistry
from .filesystem_security import path_is_link_or_reparse
from .host_paths import (
    HostPathError,
    HostPathKey,
    host_path_comparison_key,
    localize_waapi_host_path,
    parse_absolute_host_path,
    parse_relative_host_path,
)
from .io_policy import IOPolicyError, validate_isolated_io
from .identity_limits import MULTI_IDENTITY_READ_MAX_IDS
from .metadata_restrictions import (
    MetadataRestrictionError,
    reference_allowed_types,
    reference_type_token,
)
from .operation_import import (
    AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS,
    ImportContractError,
    MAX_AUDIO_IMPORT_BASE64_ENCODED_CHARS,
    MAX_IMPORT_ITEMS,
    MAX_NATIVE_AUDIO_IMPORT_ROWS,
    allowed_import_hierarchy_roots,
    build_audio_import_plan,
    expected_audio_file_source_result_path,
    language_requires_live_project_validation,
    normalize_auto_check_out_to_source_control,
    normalize_inline_audio_file,
    normalize_originals_subfolder,
    parse_tab_delimited_import_file,
    regular_file_proof as import_regular_file_proof,
    unsupported_localized_existing_fields,
    validate_import_media_extension,
    verify_regular_file_proof as verify_import_file_proof,
)
from .operation_object import (
    DEFAULT_MAX_CHILDREN_PER_NODE,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_FIELDS_PER_NODE,
    DEFAULT_MAX_IMPORT_FILES,
    DEFAULT_MAX_NODES,
    DEFAULT_MAX_REQUEST_BYTES,
    ObjectImportDescriptor,
    ObjectNodeDescriptor,
    ObjectOperationContractError,
    ObjectResultNode,
    RtpcDescriptor,
    bind_request_result_topology,
    flatten_create_result,
    flatten_request_nodes,
    flatten_set_result,
    materialize_waapi_node,
    materialize_waapi_rtpc,
    normalize_object_forest,
    normalize_object_import,
    normalize_object_node,
    normalize_object_list_name,
    normalize_object_lists,
    normalize_property_descriptors,
    normalize_reference_descriptors,
    normalize_rtpc_descriptors,
    normalize_object_tree,
)
from .operation_plugin import (
    PLUGIN_2022_EFFECT_TARGET_READBACK_FIELDS,
    PLUGIN_EFFECT_SLOT_READBACK_FIELDS,
    SUPPORTED_PLUGIN_VERSIONS,
    WWISE_2022_EFFECT_FIELDS,
    PluginCreationDescriptor,
    PluginOperationContractError,
    ValidatedPluginProperty,
    build_plugin_creation_plan,
    normalize_plugin_creation,
    plugin_property_metadata_requests,
    plugin_verification_fields,
    validate_plugin_property_metadata,
    verify_created_plugin_row,
)
from .operation_ui_commands import (
    EXECUTE_URI as UI_COMMAND_EXECUTE_URI,
    GET_COMMANDS_URI as UI_COMMAND_GET_COMMANDS_URI,
    LUA_COMMAND_VERSIONS as UI_COMMAND_LUA_VERSIONS,
    MAX_ARGUMENT_TOKEN_CHARS as UI_COMMAND_MAX_ARGUMENT_TOKEN_CHARS,
    MAX_ARGUMENT_TOKENS as UI_COMMAND_MAX_ARGUMENT_TOKENS,
    MAX_COMMAND_ID_CHARS as UI_COMMAND_MAX_ID_CHARS,
    MAX_COMMANDS_PER_PLAN as UI_COMMAND_MAX_COMMANDS,
    MAX_DEFAULT_SHORTCUT_CHARS as UI_COMMAND_MAX_DEFAULT_SHORTCUT_CHARS,
    MAX_DISPLAY_NAME_CHARS as UI_COMMAND_MAX_DISPLAY_NAME_CHARS,
    MAX_LUA_MODULE_DIRECTORIES as UI_COMMAND_MAX_LUA_MODULE_DIRECTORIES,
    MAX_LUA_SELECTED_RETURN_CHARS as UI_COMMAND_MAX_LUA_RETURN_CHARS,
    MAX_LUA_SELECTED_RETURN_FIELDS as UI_COMMAND_MAX_LUA_RETURN_FIELDS,
    MAX_MENU_SEGMENT_CHARS as UI_COMMAND_MAX_MENU_SEGMENT_CHARS,
    MAX_MENU_SEGMENTS as UI_COMMAND_MAX_MENU_SEGMENTS,
    MAX_OBJECT_TYPE_CHARS as UI_COMMAND_MAX_OBJECT_TYPE_CHARS,
    MAX_OBJECT_TYPES as UI_COMMAND_MAX_OBJECT_TYPES,
    MAX_PATH_CHARS as UI_COMMAND_MAX_PATH_CHARS,
    REGISTER_URI as UI_COMMAND_REGISTER_URI,
    START_MODES as UI_COMMAND_START_MODES,
    UNREGISTER_EXISTING_ACKNOWLEDGEMENT,
    UNREGISTER_URI as UI_COMMAND_UNREGISTER_URI,
    USER_SUPPLIED_SOURCE_AUTHORITY as UI_COMMAND_SOURCE_AUTHORITY,
    UiCommandContractError,
    build_ui_command_execute_plan,
    build_ui_commands_register_plan,
    build_ui_commands_unregister_descriptors_plan,
    build_ui_commands_unregister_existing_plan,
    validate_empty_ui_command_result,
    validate_ui_command_plan,
    validate_ui_command_runtime_preconditions,
    verify_ui_command_inventory_postcondition,
)
from .operation_soundbank import (
    SoundBankContractError,
    build_external_sources_operation_plan,
    build_generate_operation_plan,
    build_process_definition_operation_plan,
    capture_artifact_tree,
    compare_artifact_trees,
    parse_wwise_2021_project_file,
    parse_wwise_2021_language_inventory,
    verify_file_proof as verify_soundbank_file_proof,
)
from .platform_paths import WWISE_WIRE_PATH_INPUT_AUDIT_CONTRACT
from .transaction_cleanup import build_transaction_cleanup_spec
from .versions import SUPPORTED_WWISE_VERSION_KEYS
from .waql import quote_waql_literal


OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
PREPARED_OPERATION_CONTRACT = "waapi-skill.prepared-operation/v1"
VERIFICATION_RESULT_CONTRACT = "waapi-skill.operation-verification/v1"
ROLE_VALIDATION_CONTRACT = "waapi-skill.role-validation/v1"
INTERNAL_CANONICAL_INPUT_MODE = "internal_canonical"
COMPOSER_INPUT_MODE = "composer"
BUSINESS_DECLARATION_INPUT_MODE = "business_declaration"
INLINE_TYPED_INPUT_MODE = "inline_typed"
SUPPORTED_OPERATION_INPUT_MODES = frozenset(
    {
        INTERNAL_CANONICAL_INPUT_MODE,
        COMPOSER_INPUT_MODE,
        BUSINESS_DECLARATION_INPUT_MODE,
        INLINE_TYPED_INPUT_MODE,
    }
)
OBJECT_GET_URI = "ak.wwise.core.object.get"
OBJECT_GET_TYPES_URI = "ak.wwise.core.object.getTypes"
OBJECT_IS_LINKED_URI = "ak.wwise.core.object.isLinked"
OBJECT_IS_PROPERTY_ENABLED_URI = "ak.wwise.core.object.isPropertyEnabled"
OBJECT_SET_LINKED_URI = "ak.wwise.core.object.setLinked"
OBJECT_SET_URI = "ak.wwise.core.object.set"
GET_PROJECT_INFO_URI = "ak.wwise.core.getProjectInfo"
SOUNDBANK_GET_INCLUSIONS_URI = "ak.wwise.core.soundbank.getInclusions"
SWITCHCONTAINER_GET_ASSIGNMENTS_URI = "ak.wwise.core.switchContainer.getAssignments"
REMOTE_GET_CONNECTION_STATUS_URI = "ak.wwise.core.remote.getConnectionStatus"
REMOTE_CONNECT_URI = "ak.wwise.core.remote.connect"
OBJECT_SET_IMPORT_VERSIONS = frozenset(
    {"2023.1", "2024.1", "2025.1"}
)
OBJECT_SET_IMPORT_READBACK_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "parent",
    "activeSource",
    "audioSource:language",
    "originalFilePath",
    "sound:originalWavFilePath",
)
REMOTE_DISCONNECT_URI = "ak.wwise.core.remote.disconnect"
TRANSPORT_CREATE_URI = "ak.wwise.core.transport.create"
TRANSPORT_DESTROY_URI = "ak.wwise.core.transport.destroy"
TRANSPORT_GET_LIST_URI = "ak.wwise.core.transport.getList"
TRANSPORT_GET_STATE_URI = "ak.wwise.core.transport.getState"
CLI_CONVERT_EXTERNAL_SOURCE_URI = "ak.wwise.cli.convertExternalSource"
AUTHORING_AUDIO_CONVERT_URI = "ak.wwise.core.audio.convert"
CLI_EXECUTE_LUA_URI = "ak.wwise.cli.executeLuaScript"
CORE_EXECUTE_LUA_URI = "ak.wwise.core.executeLuaScript"
DEBUG_ENABLE_ASSERTS_URI = "ak.wwise.debug.enableAsserts"
DEBUG_ENABLE_AUTOMATION_MODE_URI = "ak.wwise.debug.enableAutomationMode"
DEBUG_RESTART_WAAPI_SERVERS_URI = "ak.wwise.debug.restartWaapiServers"
DEBUG_TEST_ASSERT_URI = "ak.wwise.debug.testAssert"
DEBUG_TEST_CRASH_URI = "ak.wwise.debug.testCrash"
GET_INFO_URI = "ak.wwise.core.getInfo"
UI_COMMAND_OPERATIONS = frozenset(
    {
        "ui.commands.execute",
        "ui.commands.register",
        "ui.commands.unregister",
    }
)
REPLAY_GUARD_OPERATIONS = frozenset(
    {
        "lua.executeCliFile",
        "lua.executeCoreFile",
        "lua.executeCoreInline",
        "debug.setAsserts",
        "debug.setAutomationMode",
        "debug.restartWaapiServers",
        "debug.testAssert",
        "debug.testCrash",
        "ui.captureScreen",
    }
)
PACKAGED_TRANSACTION_READBACK_URIS = frozenset(
    {
        OBJECT_GET_URI,
        OBJECT_GET_TYPES_URI,
        OBJECT_IS_LINKED_URI,
        OBJECT_IS_PROPERTY_ENABLED_URI,
        GET_INFO_URI,
        GET_PROJECT_INFO_URI,
        GET_PROPERTY_AND_REFERENCE_NAMES_URI,
        GET_PROPERTY_INFO_URI,
        SOUNDBANK_GET_INCLUSIONS_URI,
        SWITCHCONTAINER_GET_ASSIGNMENTS_URI,
        REMOTE_GET_CONNECTION_STATUS_URI,
        TRANSPORT_GET_LIST_URI,
        TRANSPORT_GET_STATE_URI,
        UI_COMMAND_GET_COMMANDS_URI,
    }
)
TRANSPORT_STATES = frozenset({"playing", "stopped", "paused"})
UNDO_BEGIN_GROUP_URI = "ak.wwise.core.undo.beginGroup"
UNDO_END_GROUP_URI = "ak.wwise.core.undo.endGroup"
UNDO_CANCEL_GROUP_URI = "ak.wwise.core.undo.cancelGroup"
UNDO_GROUP_MAX_CALLS = 32
UNDO_GROUP_MAX_DISPLAY_NAME_LENGTH = 256
UNDO_GROUP_MAX_REQUEST_BYTES = 128 * 1024
UNDO_GROUP_MAX_PLAN_BYTES = 256 * 1024
_UNDO_GROUP_2021_INNER_URIS = frozenset(
    {
        "ak.wwise.core.object.setAttenuationCurve",
        "ak.wwise.core.object.setName",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.object.setProperty",
        "ak.wwise.core.object.setRandomizer",
        "ak.wwise.core.object.setReference",
        "ak.wwise.core.soundbank.setInclusions",
        "ak.wwise.core.switchContainer.addAssignment",
        "ak.wwise.core.switchContainer.removeAssignment",
    }
)
_UNDO_GROUP_2022_INNER_URIS = _UNDO_GROUP_2021_INNER_URIS | {
    "ak.wwise.core.object.pasteProperties",
    "ak.wwise.core.sound.setActiveSource",
}
_UNDO_GROUP_2023_INNER_URIS = _UNDO_GROUP_2022_INNER_URIS | {
    "ak.wwise.core.object.setLinked",
    "ak.wwise.core.object.setStateGroups",
    "ak.wwise.core.object.setStateProperties",
}
_UNDO_GROUP_2024_INNER_URIS = _UNDO_GROUP_2023_INNER_URIS | {
    "ak.wwise.core.audio.setConversionPlugin",
    "ak.wwise.core.blendContainer.addAssignment",
    "ak.wwise.core.blendContainer.addTrack",
    "ak.wwise.core.blendContainer.removeAssignment",
    "ak.wwise.core.gameParameter.setRange",
}
UNDO_GROUP_INNER_URIS_BY_VERSION: Mapping[str, frozenset[str]] = {
    "2021.1": _UNDO_GROUP_2021_INNER_URIS,
    "2022.1": frozenset(_UNDO_GROUP_2022_INNER_URIS),
    "2023.1": frozenset(_UNDO_GROUP_2023_INNER_URIS),
    "2024.1": frozenset(_UNDO_GROUP_2024_INNER_URIS),
    "2025.1": frozenset(_UNDO_GROUP_2024_INNER_URIS),
}
SWITCH_GROUP_REFERENCE = "SwitchGroupOrStateGroup"
IDENTITY_RETURN_FIELDS = ("id", "name", "type", "path", "parent", "notes")
# ``ak.wwise.core.object.get`` does not accept a bare numeric Short ID.  Its
# ``from.id`` Short ID selector is a closed object whose numeric ``type`` is
# the WAAPI object-type code.  Only Definition directives with an official
# selector code are admitted here; notably, DialogueEvent has no such selector
# and must fail closed instead of borrowing Event's code.
DEFINITION_SHORT_ID_OBJECT_TYPE_CODES: Mapping[str, int] = {
    "Event": 10,
    "Effect": 17,  # EffectPlugin; Definition readback accepts Effect/EffectShareSet.
    "AuxBus": 20,
}
OBJECT_REPLACE_SNAPSHOT_FIELDS = ("id", "path")
OBJECT_REPLACE_MAX_SUBTREE_NODES = 128
OBJECT_LIST_SNAPSHOT_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "parent",
    "owner",
    "notes",
)
OBJECT_LIST_MAX_SUBTREE_NODES = 128
OBJECT_DEDICATED_LIST_NAMES = frozenset({"effects", "rtpc"})
RTPC_SNAPSHOT_FIELDS = (
    "id",
    "name",
    "type",
    "path",
    "notes",
    "@PropertyName",
    "@ControlInput",
    "@Curve",
)
RTPC_MAX_LIST_ROWS = 128
RTPC_EMPTY_OWNER_FIELD_OMISSION_VERSIONS = frozenset({"2022.1", "2025.1"})
RTPC_CONTROL_INPUT_TYPE_TOKENS = frozenset(
    {
        "gameparameter",
        "modulatorlfo",
        "modulatorenvelope",
        "modulatortime",
        "midiparameter",
    }
)
_REFERENCE_ACTIVATION_DEPENDENCY_FIELDS = frozenset(
    {"action", "context", "property", "type"}
)
_REFERENCE_ACTIVATION_FIELD_NAME = re.compile(r"^[:_a-zA-Z0-9]+$")
_PLUGIN_GUID = re.compile(
    r"^\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}$"
)
INCLUSION_FILTERS = frozenset({"events", "structures", "media"})
IMPORT_WRITABLE_PARENT_TYPES = frozenset(
    {
        "WorkUnit",
        "Folder",
        "ActorMixer",
        "RandomSequenceContainer",
        "SwitchContainer",
        "BlendContainer",
        "MusicSwitchContainer",
        "MusicRanSeqCntr",
        "MusicSegment",
    }
)
IMPORT_REFLECTED_WRITABLE_PARENT_TYPES_BY_VERSION: Mapping[
    str,
    frozenset[str],
] = {
    "2025.1": frozenset({"PropertyContainer"}),
}
OBJECT_CREATE_WRITABLE_PARENT_TYPES = frozenset(
    {
        "WorkUnit",
        "Folder",
        "ActorMixer",
        "RandomSequenceContainer",
        "SwitchContainer",
        "BlendContainer",
        "MusicSwitchContainer",
        "MusicRanSeqCntr",
        "MusicSegment",
    }
)
OBJECT_CREATE_SPECIALIZED_CHILD_TYPES_BY_PARENT: Mapping[
    str,
    frozenset[str],
] = {
    "StateGroup": frozenset({"State"}),
    "SwitchGroup": frozenset({"Switch"}),
}
OBJECT_CREATE_REFLECTED_PARENT_TYPES_BY_VERSION: Mapping[str, frozenset[str]] = {
    "2025.1": frozenset({"PropertyContainer"}),
}
IMPORT_ITEM_REQUIRED_FIELDS: tuple[str, ...] = ()
IMPORT_ITEM_OPTIONAL_FIELDS = (
    "object_path",
    "object_type",
    "audio_file",
    "audio_file_base64",
    "import_language",
    "import_location",
    "originals_subfolder",
    "notes",
    "audio_source_notes",
    "event",
    "dialogue_event",
    "switch_assignment",
    "properties",
    "references",
)
# ``audio.import`` exposes an Event string, but the useful postcondition is the
# Action object created below that Event.  Keep both the reflected return fields
# and enum values pinned by Wwise lane even though the reviewed five versions
# currently share the same Action object contract.
_IMPORT_EVENT_ACTION_FIELDS_BY_VERSION: Mapping[str, tuple[str, ...]] = {
    version: (*IDENTITY_RETURN_FIELDS, "ActionType", "Target")
    for version in SUPPORTED_WWISE_VERSION_KEYS
}
_IMPORT_EVENT_ACTION_TYPES_BY_VERSION: Mapping[str, Mapping[str, int]] = {
    version: {
        "Play": 1,
        "Stop": 2,
        "Pause": 7,
        "Resume": 9,
        "Break": 34,
        "Seek": 36,
    }
    for version in SUPPORTED_WWISE_VERSION_KEYS
}
_TYPED_PATH_SEGMENT = re.compile(r"^<[^<>]+>(.+)$")

FORBIDDEN_MODEL_AUTHORED_COMMAND_FIELDS: Mapping[str, frozenset[str]] = {
    "ak.wwise.cli.generateSoundbank": frozenset(
        {
            "custom-global-closing-cmd",
            "custom-global-opening-cmd",
            "custom-post-gen-cmd",
            "custom-pre-gen-cmd",
        }
    ),
    "ak.wwise.cli.tabDelimitedImport": frozenset(
        {
            "custom-global-closing-cmd",
            "custom-global-opening-cmd",
        }
    ),
}

DIRECT_CHILD_MAX_PARENT_LITERAL_LENGTH = 4096
DIRECT_CHILD_MAX_TYPE_LENGTH = 128
EXACT_TYPE_NAME_MAX_NAME_LENGTH = 255
_EXACT_TYPE_NAME_TYPE_TOKEN = re.compile(r"^[A-Za-z0-9_.]+$")


_ID_IDENTITY_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["kind", "value"],
    "additionalProperties": False,
    "properties": {"kind": {"const": "id"}, "value": {"type": ["string", "integer"]}},
}
_PATH_IDENTITY_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["kind", "value"],
    "additionalProperties": False,
    "properties": {"kind": {"const": "path"}, "value": {"type": "string", "pattern": r"^\\"}},
}
_EXACT_TYPE_NAME_IDENTITY_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["kind", "type", "name"],
    "additionalProperties": False,
    "properties": {
        "kind": {"const": "exact-type-name"},
        "type": {
            "type": "string",
            "minLength": 1,
            "maxLength": DIRECT_CHILD_MAX_TYPE_LENGTH,
            "pattern": _EXACT_TYPE_NAME_TYPE_TOKEN.pattern,
            "description": "Exact Wwise type token used in a Gateway-owned WAQL source.",
        },
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": EXACT_TYPE_NAME_MAX_NAME_LENGTH,
            "description": "Exact global object name; live resolution must return exactly one row.",
        },
    },
    "description": (
        "Resolve exactly one globally named object of one exact type. "
        "The Gateway constructs the bounded WAQL selector; caller-authored WAQL is not accepted."
    ),
}
_DIRECT_CHILD_PARENT_ID_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["kind", "value"],
    "additionalProperties": False,
    "properties": {
        "kind": {"const": "id"},
        "value": {
            "oneOf": [
                {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": DIRECT_CHILD_MAX_PARENT_LITERAL_LENGTH,
                },
                {"type": "integer"},
            ]
        },
    },
}
_DIRECT_CHILD_PARENT_PATH_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["kind", "value"],
    "additionalProperties": False,
    "properties": {
        "kind": {"const": "path"},
        "value": {
            "type": "string",
            "pattern": r"^\\",
            "maxLength": DIRECT_CHILD_MAX_PARENT_LITERAL_LENGTH,
        },
    },
}
_DIRECT_CHILD_IDENTITY_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["kind", "parent", "type"],
    "additionalProperties": False,
    "properties": {
        "kind": {"const": "direct-child"},
        "parent": {
            "description": (
                "Closed id or path identity. The Gateway resolves it live, "
                "then constructs the bounded direct-child selector."
            ),
            "oneOf": [
                _DIRECT_CHILD_PARENT_ID_SCHEMA,
                _DIRECT_CHILD_PARENT_PATH_SCHEMA,
            ],
        },
        "type": {
            "type": "string",
            "minLength": 1,
            "maxLength": DIRECT_CHILD_MAX_TYPE_LENGTH,
            "description": "Exact Wwise type token for the one required direct child.",
        },
    },
    "description": (
        "Resolve exactly one direct child of the closed parent by exact type. "
        "No caller-authored WAQL is accepted by this identity kind."
    ),
}
IDENTITY_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "oneOf": [
        _ID_IDENTITY_SCHEMA,
        _PATH_IDENTITY_SCHEMA,
        _EXACT_TYPE_NAME_IDENTITY_SCHEMA,
        _DIRECT_CHILD_IDENTITY_SCHEMA,
        {
            "type": "object",
            "required": ["kind", "name", "type", "parent"],
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "scoped-name"},
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": EXACT_TYPE_NAME_MAX_NAME_LENGTH,
                    "description": "Exact object name below the one closed parent.",
                },
                "type": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": DIRECT_CHILD_MAX_TYPE_LENGTH,
                    "pattern": _EXACT_TYPE_NAME_TYPE_TOKEN.pattern,
                    "description": "Exact Wwise type token below the one closed parent.",
                },
                "parent": {
                    "description": "Closed id or path identity; live-resolved before preview.",
                    "oneOf": [
                        _DIRECT_CHILD_PARENT_ID_SCHEMA,
                        _DIRECT_CHILD_PARENT_PATH_SCHEMA,
                    ],
                },
            },
            "description": (
                "Resolve exactly one direct child by exact type and name below one closed parent. "
                "The Gateway constructs the bounded selector; caller-authored WAQL is not accepted."
            ),
        },
    ]
}

_SWITCH_REMOVE_CHILD_IDENTITY_SCHEMA: Mapping[str, Any] = {
    **IDENTITY_ARGUMENT_SCHEMA,
    "description": (
        "Identity of the existing direct child whose assignment will be removed. "
        "Use an exact id or full path only when that identity was supplied or "
        "proved directly. When the available evidence is the closed Switch "
        "Container parent plus the child's exact name and type, use scoped-name "
        "with that parent; do not synthesize a full path."
    ),
}
_SWITCH_REMOVE_CONTAINER_IDENTITY_SCHEMA: Mapping[str, Any] = {
    **IDENTITY_ARGUMENT_SCHEMA,
    "description": (
        "Identity of the existing Switch Container. Prefer a canonical id "
        "already returned by the Gateway (for example an import result's "
        "parent.id); otherwise copy the complete Wwise path supplied or proved "
        "earlier verbatim. If neither is practical, use exact-type-name with "
        "type SwitchContainer and the exact display name so the Gateway can "
        "prove uniqueness live. Never shorten, infer, or reconstruct a path: "
        "a single display-name segment such as \\Player_Footsteps is not a "
        "complete Wwise path and must not be sent as kind path."
    ),
}
_SWITCH_REMOVE_VALUE_IDENTITY_SCHEMA: Mapping[str, Any] = {
    **IDENTITY_ARGUMENT_SCHEMA,
    "description": (
        "Identity of the existing direct Switch/State value whose assignment "
        "will be removed. Use an exact id or full path only when that identity "
        "was supplied or proved directly. When the available evidence is the "
        "closed Switch/State Group parent plus the value's exact name and type, "
        "use scoped-name with that parent. Business wording such as Group/Value "
        "describes the relationship; it does not add a Group display-name path "
        "segment between the known parent and value."
    ),
}

PLATFORM_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "string",
    "minLength": 1,
    "description": "Exact platform GUID or unique Wwise platform name.",
}

_OBJECT_PROPERTY_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["name", "value"],
    "additionalProperties": False,
    "properties": {
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": r"^[:_a-zA-Z0-9]+$",
            "description": (
                "Mutation token without @. If this conversation's successful "
                "live query returned exact accessor @Foo, submit Foo by removing "
                "exactly one leading @. Never infer it from other text."
            ),
            "live_query_accessor_mapping": {
                "source": "successful_live_query_in_this_conversation",
                "query": "@Foo",
                "mutation": "Foo",
                "transform": "remove_exactly_one_leading_at",
                "guessing": False,
            },
        },
        "value": {"description": "Finite JSON scalar validated against live getPropertyInfo metadata."},
    },
}

_PLUGIN_PROPERTY_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["name", "value"],
    "additionalProperties": False,
    "properties": {
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "description": (
                "Exact plug-in property name. The Skill validates it with a "
                "classId-scoped live getPropertyInfo read."
            ),
        },
        "value": {
            "oneOf": [
                {"type": "string"},
                {"type": "integer"},
                {"type": "number"},
                {"type": "boolean"},
            ],
            "description": (
                "Finite JSON scalar accepted only after live getPropertyInfo "
                "name/type validation."
            )
        },
    },
}

_PLUGIN_CREATION_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["kind", "name", "class_id"],
    "optional": ["notes", "platform", "language", "properties"],
    "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["source", "effect"]},
        "name": {"type": "string", "minLength": 1, "maxLength": 255},
        "class_id": {
            "type": "integer",
            "minimum": 1,
            "maximum": 4_294_967_295,
            "description": (
                "Exact uint32 Wwise plug-in classId. It is never inferred from "
                "a display name."
            ),
        },
        "notes": {
            "type": "string",
            "maxLength": 64 * 1024,
            "x-maxUtf8Bytes": 64 * 1024,
        },
        "platform": PLATFORM_ARGUMENT_SCHEMA,
        "language": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
            "description": (
                "Exact Wwise Source language, such as SFX; accepted only when "
                "kind is source."
            ),
        },
        "properties": {
            "type": "array",
            "maxItems": 32,
            "items": _PLUGIN_PROPERTY_ARGUMENT_SCHEMA,
        },
    },
}

_RTPC_POINT_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["x", "y", "shape"],
    "additionalProperties": False,
    "properties": {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "shape": {
            "type": "string",
            "enum": [
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
            ],
        },
    },
}
_OBJECT_REFERENCE_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["name", "target"],
    "additionalProperties": False,
    "properties": {
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": r"^[:_a-zA-Z0-9]+$",
            "description": (
                "Mutation token. Copy an exact reference accessor from this "
                "conversation's successful live query unchanged: OutputBus "
                "remains OutputBus. Never infer it from other text."
            ),
            "live_query_accessor_mapping": {
                "source": "successful_live_query_in_this_conversation",
                "query": "OutputBus",
                "mutation": "OutputBus",
                "transform": "copy_exactly",
                "guessing": False,
            },
        },
        "target": IDENTITY_ARGUMENT_SCHEMA,
    },
}
_OBJECT_CREATE_TYPE_TOKEN_DESCRIPTION = (
    "Exact Wwise request token. Natural mappings: Actor Mixer -> ActorMixer; "
    "Random Container / 随机容器 -> RandomSequenceContainer (never RandomContainer); "
    "Blend Container / 混合容器 -> BlendContainer; Sound -> Sound. "
    "Wwise 2025.1 reflects an Actor Mixer as PropertyContainer, but its "
    "object.create request token remains ActorMixer."
)
_OBJECT_CREATE_TYPE_TOKEN_SCHEMA: Mapping[str, Any] = {
    "type": "string",
    "minLength": 1,
    "description": _OBJECT_CREATE_TYPE_TOKEN_DESCRIPTION,
}
_AUDIO_FILE_BASE64_VERBATIM_CONTRACT: Mapping[str, Any] = {
    "contract": "waapi-skill.audio-file-base64-verbatim/v1",
    "opaque_segment": "characters_after_first_vertical_bar",
    "caller_provided_complete_value": "copy_character_for_character",
    "forbidden_transformations": [
        "reconstruct",
        "re-encode",
        "repair",
        "truncate",
        "splice",
    ],
    "on_unreliable_preservation": "stop_before_preview",
}
_SHELL_SINGLE_QUOTED_WWISE_PATH_CONTRACT: Mapping[str, Any] = {
    "contract": "waapi-skill.shell-single-quoted-wwise-path/v1",
    "source_value": "decoded_gateway_json_string",
    "shell_quoting": "single_quotes",
    "literal_backslashes_per_path_separator": 1,
    "json_serialized_backslashes_per_path_separator": 2,
    "copy_json_escape_backslashes_as_literal_characters": False,
}
_DEFAULT_CONTAINER_WORK_UNIT_PATH_BY_VERSION: Mapping[str, str] = {
    "2021.1": r"\Actor-Mixer Hierarchy\Default Work Unit",
    "2022.1": r"\Actor-Mixer Hierarchy\Default Work Unit",
    "2023.1": r"\Actor-Mixer Hierarchy\Default Work Unit",
    "2024.1": r"\Actor-Mixer Hierarchy\Default Work Unit",
    "2025.1": r"\Containers\Default Work Unit",
}
_ACTOR_MIXER_METADATA_TYPE_BY_VERSION: Mapping[str, str] = {
    "2021.1": "ActorMixer",
    "2022.1": "ActorMixer",
    "2023.1": "ActorMixer",
    "2024.1": "ActorMixer",
    "2025.1": "PropertyContainer",
}
_OBJECT_NODE_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["type", "name"],
    "additionalProperties": False,
    "properties": {
        "type": _OBJECT_CREATE_TYPE_TOKEN_SCHEMA,
        "name": {"type": "string", "minLength": 1},
        "notes": {"type": "string"},
        "properties": {"type": "array", "items": _OBJECT_PROPERTY_ARGUMENT_SCHEMA},
        "references": {"type": "array", "items": _OBJECT_REFERENCE_ARGUMENT_SCHEMA},
        "children": {
            "type": "array",
            "description": "Recursive closed object-node DSL; depth 8 and 128 total nodes.",
        },
    },
}
_OBJECT_SET_IMPORT_FILE_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": [],
    "optional": [
        "audio_file",
        "audio_file_base64",
        "originals_subfolder",
        "language",
        "object_type",
    ],
    "additionalProperties": False,
    "description": "Exactly one of audio_file or audio_file_base64 is required.",
    "properties": {
        "audio_file": {
            "type": "string",
            "absoluteRegularFile": True,
            "description": "Absolute WAV, AMB, MID, or MIDI source file proved before preview.",
        },
        "audio_file_base64": {
            "type": "string",
            "minLength": 17,
            "maxLength": 256 * 1024,
            "description": (
                "A relative .wav path below Project Originals, a vertical bar, "
                "and bounded canonical RIFF/WAVE base64 data. Treat caller-"
                "provided inline data as opaque: copy the complete value "
                "character-for-character and stop before preview if exact "
                "preservation is uncertain."
            ),
            "verbatim_contract": _AUDIO_FILE_BASE64_VERBATIM_CONTRACT,
        },
        "originals_subfolder": {
            "type": "string",
            "maxLength": 512,
            "description": "Reviewed relative subfolder below Wwise Originals.",
        },
        "language": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "description": (
                "SFX or an exact existing Project language name for this media file."
            ),
        },
        "object_type": {
            **_OBJECT_CREATE_TYPE_TOKEN_SCHEMA,
            "description": (
                "Exact live metadata token for the object created for this "
                "imported media file."
            ),
        },
    },
}
_OBJECT_SET_IMPORT_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["files"],
    "optional": ["auto_add_to_source_control"],
    "additionalProperties": False,
    "properties": {
        "files": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": _OBJECT_SET_IMPORT_FILE_ARGUMENT_SCHEMA,
        },
        "auto_add_to_source_control": {"type": "boolean"},
    },
}
_OBJECT_SET_NODE_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["type", "name"],
    "additionalProperties": False,
    "properties": {
        "type": _OBJECT_CREATE_TYPE_TOKEN_SCHEMA,
        "name": {"type": "string", "minLength": 1},
        "notes": {"type": "string"},
        "platform": {
            **PLATFORM_ARGUMENT_SCHEMA,
            "description": (
                "Per-node platform override available in Wwise 2022.1-2025.1."
            ),
        },
        "language": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "description": (
                "Exact existing Project language name for a newly created Sound Voice; "
                "available in Wwise 2022.1 and newer."
            ),
        },
        "import": {
            **_OBJECT_SET_IMPORT_ARGUMENT_SCHEMA,
            "supported_versions": ["2023.1", "2024.1", "2025.1"],
        },
        "properties": {"type": "array", "items": _OBJECT_PROPERTY_ARGUMENT_SCHEMA},
        "references": {"type": "array", "items": _OBJECT_REFERENCE_ARGUMENT_SCHEMA},
        "children": {
            "type": "array",
            "description": (
                "Recursive closed object.set node DSL with the same fields; "
                "depth 8 and 128 total nodes."
            ),
        },
    },
}
_OBJECT_LIST_NAME_SCHEMA: Mapping[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 128,
    "pattern": r"^[:_a-zA-Z0-9]+$",
    "description": (
        "Canonical Wwise object-list name without the native @ prefix. "
        "Source/Effect plug-ins and RTPCs remain dedicated operations."
    ),
}
_OBJECT_LIST_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["name", "objects"],
    "additionalProperties": False,
    "properties": {
        "name": _OBJECT_LIST_NAME_SCHEMA,
        "objects": {
            "type": "array",
            "maxItems": 32,
            "items": _OBJECT_SET_NODE_ARGUMENT_SCHEMA,
            "description": (
                "Closed recursive object-node DSL. An empty array is meaningful "
                "only with list_mode=replaceAll, where it clears the reviewed list."
            ),
        },
    },
}

_IMPORT_EVENT_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["path"],
    "optional": ["action"],
    "additionalProperties": False,
    "properties": {
        "path": {"type": "string", "pattern": r"^\\Events\\"},
        "action": {
            "type": "string",
            "enum": ["Play", "Stop", "Pause", "Resume", "Break", "Seek"],
        },
    },
}
_AUDIO_IMPORT_OBJECT_TYPE_TOKEN_DESCRIPTION = (
    "Exact Wwise audio.import objectType wire token. Natural mappings: "
    "Sound SFX / SFX 声音 -> Sound SFX (do not shorten an explicitly requested "
    "Sound SFX to Sound); Random Container / 随机容器 -> "
    "RandomSequenceContainer (never RandomContainer). These spellings are "
    "request-shape guidance; RandomContainer and SequenceContainer remain "
    "distinct and are not semantic aliases."
)
_AUDIO_IMPORT_OBJECT_TYPE_TOKEN_SCHEMA: Mapping[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 128,
    "description": _AUDIO_IMPORT_OBJECT_TYPE_TOKEN_DESCRIPTION,
}
_AUDIO_IMPORT_SWITCH_ASSIGNMENT_DESCRIPTION = (
    "One native Wwise Switch Assignation import directive, not an object "
    "identity or object-path field. When importing a direct child into an "
    "existing Switch Container whose Switch/State Group is already bound, "
    "use the exact Switch/State value name (for example, Snow); do not pass "
    "the value object's path in that common case."
)
_AUDIO_IMPORT_SWITCH_ASSIGNMENT_SCHEMA: Mapping[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 16 * 1024,
    "description": _AUDIO_IMPORT_SWITCH_ASSIGNMENT_DESCRIPTION,
}
_IMPORT_COMMON_ARGUMENT_PROPERTIES: Mapping[str, Any] = {
    "object_path": {"type": "string", "minLength": 1},
    "object_type": _AUDIO_IMPORT_OBJECT_TYPE_TOKEN_SCHEMA,
    "audio_file": {"type": "string", "absoluteRegularFile": True},
    "audio_file_base64": {
        "type": "string",
        "minLength": 17,
        "maxLength": 256 * 1024,
        "description": (
            "A relative .wav path below Project Originals, a vertical bar, and "
            "canonical RIFF/WAVE base64 data. Treat caller-provided inline data "
            "as opaque: copy the complete value character-for-character and "
            "stop before preview if exact preservation is uncertain."
        ),
        "verbatim_contract": _AUDIO_FILE_BASE64_VERBATIM_CONTRACT,
    },
    "import_language": {"type": "string", "minLength": 1},
    "import_location": IDENTITY_ARGUMENT_SCHEMA,
    "originals_subfolder": {
        "type": "string",
        "description": (
            "Optional relative Originals destination supplied explicitly by "
            "the user. Copy an exact requested value; otherwise omit this "
            "field. Never infer it from the source directory, media category, "
            "object path, or examples."
        ),
    },
    "notes": {"type": "string"},
    "audio_source_notes": {"type": "string"},
    "event": _IMPORT_EVENT_ARGUMENT_SCHEMA,
    "dialogue_event": {
        "type": "string",
        "minLength": 1,
        "maxLength": 16 * 1024,
        "description": "One native Wwise Dialogue Event import directive.",
    },
    "switch_assignment": _AUDIO_IMPORT_SWITCH_ASSIGNMENT_SCHEMA,
    "properties": {
        "type": "array",
        "maxItems": 64,
        "items": _OBJECT_PROPERTY_ARGUMENT_SCHEMA,
    },
    "references": {
        "type": "array",
        "maxItems": 64,
        "items": _OBJECT_REFERENCE_ARGUMENT_SCHEMA,
    },
}
_IMPORT_DEFAULT_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": [],
    "optional": list(_IMPORT_COMMON_ARGUMENT_PROPERTIES),
    "additionalProperties": False,
    "properties": dict(_IMPORT_COMMON_ARGUMENT_PROPERTIES),
    "description": (
        "For a multi-row batch, put each supported fixed field and each property/"
        "reference here once when the user explicitly states it as the batch/default/"
        "common baseline (including natural wording such as 默认/统一/共同), with "
        "exceptional rows carrying exact overrides, or when the same effective value "
        "applies to every row. A value merely repeated by a subset without baseline "
        "intent stays in those rows; keep imports[] to row-specific fields and exact "
        "overrides so the request stays compact."
    ),
}
_IMPORT_OPERATION_DESCRIPTION = (
    "Batch mode at $.arguments.import_operation. Map meaning rather than "
    "requiring literal tokens: createNew creates objects; useExisting must "
    "preserve the existing object's identity while updating its media and may "
    "also create missing rows. Use replaceExisting only when the user authorizes "
    "replacing the object, not merely its media. When mode is unstated, omission "
    "means createNew. Never place it inside an imports[] row or TSV."
)
_IMPORT_OPERATION_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "string",
    "enum": ["createNew", "useExisting", "replaceExisting"],
    "default": "createNew",
    "description": _IMPORT_OPERATION_DESCRIPTION,
}
_IMPORT_OPERATION_INTENT_CONTRACT: Mapping[str, Any] = {
    "contract": "waapi-skill.import-operation-intent/v1",
    "path": "$.arguments.import_operation",
    "matching": "semantic_user_intent_not_literal_token",
    "required_when_user_intent_is_explicit": True,
    "omission_value_when_user_intent_is_unstated": "createNew",
    "explicit_intent_values": [
        {
            "intent": "create_or_new",
            "semantic_examples": [
                "create",
                "new",
                "createNew",
                "新建",
                "创建",
            ],
            "value": "createNew",
        },
        {
            "intent": "reuse_existing",
            "semantic_examples": [
                "reuse",
                "use existing",
                "useExisting",
                "使用现有",
                "复用",
            ],
            "value": "useExisting",
        },
        {
            "intent": "replace_existing",
            "semantic_examples": [
                "replace",
                "replace existing",
                "replaceExisting",
                "替换",
                "覆盖现有",
            ],
            "value": "replaceExisting",
        },
    ],
}
_LIVE_METADATA_DEPENDENCY_CLOSURE_CONTRACT: Mapping[str, Any] = {
    "contract": "waapi-skill.live-metadata-dependency-closure/v1",
    "selection": {
        "source": "current_operation_request",
        "kinds": ["property", "reference"],
        "selected_fields_only": True,
    },
    "metadata_source": {
        "command": "metadata discover",
        "authority": "live-waapi",
        "same_result_required": True,
        "candidate_collections": [
            "$.agent_result.candidates",
            "$.agent_result.dependency_candidates",
        ],
        "requirements_field": "dependency_requirements",
        "unresolved_dependencies_path": (
            "$.agent_result.unresolved_dependencies"
        ),
    },
    "traversal": {
        "recursive": True,
        "dependency_identity": "exact_returned_property_name",
    },
    "materialization": {
        "ordinary_dependencies": {
            "owner": "request",
            "required_values_count": 1,
            "kind": "property",
            "copy_name_from": "dependency_requirements[].property",
            "copy_value_from": (
                "dependency_requirements[].required_values[0]"
            ),
            "scope": {
                "inherit_selected_owner_scope": True,
                "defaults": "$.arguments.defaults.properties",
                "row": (
                    "$.arguments.imports[owner_row_index].properties"
                ),
            },
        },
        "supported_reference_activation": {
            "owner": "gateway",
            "supported_shape": {
                "dependency_type": "override",
                "action": "Enable",
                "context": "Self",
                "property_type": ["bool", "boolean"],
                "required_value": True,
            },
            "request_forms": {
                "omitted": "accepted_and_derived_before_dispatch",
                "explicit_required_value": "accepted_and_deduplicated",
                "explicit_conflict": "rejected",
            },
            "scope": "same_object_as_reference",
        },
    },
    "failure_policy": {
        "phase": "before_preview",
        "action": "stop",
        "conditions": [
            "required_values_missing",
            "required_values_multiple",
            "dependency_candidate_missing",
            "dependency_unresolved",
        ],
        "guessing_allowed": False,
    },
}
_AUDIO_IMPORT_REQUEST_COMPOSITION_CONTRACT: Mapping[str, Any] = {
    "contract": "waapi-skill.audio-import-request-composition/v1",
    "shared_values": {
        "placement": "$.arguments.defaults",
        "occurrences": "once",
        "promotion_conditions": [
            {
                "kind": "explicit_batch_baseline",
                "source": "explicit_user_semantics",
                "matching": "semantic_intent_not_literal_token",
                "semantic_examples": [
                    "default",
                    "common",
                    "默认",
                    "统一",
                    "共同",
                ],
                "row_overrides": {
                    "allowed": True,
                    "fixed_fields_match": "field_name",
                    "properties_references_match": "exact_name",
                },
            },
            {
                "kind": "identical_effective_value",
                "coverage": "all_import_rows",
                "applies_identically_to_every_import_row": True,
                "row_overrides": {"allowed": False},
            },
        ],
        "subset_shared_without_explicit_baseline": (
            "keep_in_each_applicable_import_row"
        ),
        "defaults_scope": {
            "applies_to": "every_imports_row",
            "object_type_filtering": False,
            "mixed_structure_and_sound_rows": {
                "sound_only_fields": [
                    "import_language",
                    "properties",
                    "references",
                    "event",
                ],
                "placement": "keep_on_each_applicable_sound_row",
                "defaults_placement": "forbidden",
            },
            "rule": (
                "defaults has no object-type filter and affects every imports "
                "row; when structure-only and Sound rows are mixed, keep "
                "import_language, properties, references, and event on each "
                "applicable Sound row instead of defaults"
            ),
        },
        "fixed_fields": [
            name
            for name in _IMPORT_COMMON_ARGUMENT_PROPERTIES
            if name not in {"properties", "references"}
        ],
        "named_fields": ["properties", "references"],
        "imports_row_policy": "row_specific_fields_and_exact_overrides_only",
        "named_override_key": "name",
    },
    "metadata_dependency_closure": (
        _LIVE_METADATA_DEPENDENCY_CLOSURE_CONTRACT
    ),
    "import_operation": _IMPORT_OPERATION_INTENT_CONTRACT,
}

_SOUNDBANK_GENERATE_ITEM_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["name", "artifact_expectation"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "artifact_expectation": {
            "type": "string",
            "enum": ["nonlocalized", "localized", "mixed"],
            "description": (
                "Expected artifact layout for this SoundBank. nonlocalized means "
                "only the root non-localized/SFX Bank artifact; localized means "
                "per-language artifacts; mixed means both root and per-language "
                "artifacts. Language selection is a batch-level rule derived from "
                "all soundbanks[] rows."
            ),
        },
        "events": {"type": "array", "minItems": 1, "maxItems": 256, "items": IDENTITY_ARGUMENT_SCHEMA},
        "aux_busses": {"type": "array", "minItems": 1, "maxItems": 256, "items": IDENTITY_ARGUMENT_SCHEMA},
        "inclusions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "uniqueItems": True,
            "items": {"type": "string", "enum": ["event", "structure", "media"]},
        },
        "rebuild": {
            "type": "boolean",
            "default": False,
            "description": (
                "Per-SoundBank rebuild control. Preserve an explicitly supplied "
                "value on each row; rebuild_soundbanks is a separate batch-level "
                "control and never replaces this field."
            ),
        },
    },
}

_IMPORT_AUTO_CHECK_OUT_SCHEMA: Mapping[str, Any] = {
    "type": "boolean",
    "default": False,
    "supported_versions": list(AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS),
    "description": (
        "Ask Wwise to check out affected source-control files before import. "
        "Omission defaults to false; explicit use is accepted only in Wwise 2023.1-2025.1."
    ),
}

_DELETE_AUTO_CHECK_OUT_SCHEMA: Mapping[str, Any] = {
    "type": "boolean",
    "default": False,
    "supported_versions": list(AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS),
    "description": (
        "Ask Wwise to check out affected source-control files before deletion. "
        "Omission defaults to false; explicit use is accepted only in Wwise "
        "2023.1-2025.1."
    ),
}

_OBJECT_MUTATION_AUTO_CHECK_OUT_SCHEMA: Mapping[str, Any] = {
    "type": "boolean",
    "default": False,
    "supported_versions": list(AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS),
    "description": (
        "Ask Wwise to check out affected source-control files before the object "
        "mutation. Omission defaults to false; explicit use is accepted only "
        "in Wwise 2023.1-2025.1."
    ),
}

_COPY_AUTO_ADD_SCHEMA: Mapping[str, Any] = {
    "type": "boolean",
    "default": False,
    "supported_versions": list(AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS),
    "description": (
        "Ask Wwise to add affected work units to source control after copy. "
        "Omission defaults to false; explicit use is accepted only in Wwise "
        "2023.1-2025.1."
    ),
}

_LUA_SOURCE_AUTHORITY_SCHEMA: Mapping[str, Any] = {
    "const": LUA_SOURCE_AUTHORITY,
    "description": (
        "Caller assertion that the current user message supplied the exact file "
        "path or complete inline Lua verbatim; the runtime cannot independently "
        "prove provenance. Agents must not synthesize, repair, or wrap Lua and "
        "must not use this lane as a fallback."
    ),
}
_LUA_WA_ARGS_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "maxProperties": MAX_LUA_WA_ARGS_KEYS,
    "maximumBytes": MAX_LUA_WA_ARGS_BYTES,
    "x-keyMaximumBytes": 128,
    "description": (
        f"Strict JSON data passed to wa_args, capped at {MAX_LUA_WA_ARGS_BYTES} "
        "bytes. Packaged Lua source/loader fields are reserved."
    ),
}
_LUA_FILE_SCHEMA: Mapping[str, Any] = {
    "type": "string",
    "absoluteRegularFile": True,
    "pattern": r"(?i)\.lua$",
    "maximumBytes": MAX_LUA_SOURCE_BYTES,
}


def _object_contract(
    required: Sequence[str],
    properties: Mapping[str, Any],
    *,
    optional: Sequence[str] = (),
) -> Mapping[str, Any]:
    return {
        "type": "object",
        "required": list(required),
        "optional": list(optional),
        "additionalProperties": False,
        "properties": dict(properties),
    }


def _ui_command_descriptor_contract() -> Mapping[str, Any]:
    """Return the closed item shape shared by register and unregister."""

    start_mode = {
        "type": "string",
        "enum": sorted(UI_COMMAND_START_MODES),
    }
    token_array = {
        "type": "array",
        "maxItems": UI_COMMAND_MAX_ARGUMENT_TOKENS,
        "items": {
            "type": "string",
            "maxLength": UI_COMMAND_MAX_ARGUMENT_TOKEN_CHARS,
        },
    }
    menu_path = {
        "type": "array",
        "minItems": 1,
        "maxItems": UI_COMMAND_MAX_MENU_SEGMENTS,
        "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": UI_COMMAND_MAX_MENU_SEGMENT_CHARS,
            "pattern": r"^[^/\\]+$",
        },
    }
    object_types = {
        "type": "array",
        "maxItems": UI_COMMAND_MAX_OBJECT_TYPES,
        "uniqueItems": True,
        "caseInsensitiveUniqueItems": True,
        "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": UI_COMMAND_MAX_OBJECT_TYPE_CHARS,
            "pattern": r"^[^,]+$",
        },
    }
    handler = {
        "type": "object",
        "discriminator": {"propertyName": "kind"},
        "oneOf": [
            _object_contract(
                ("kind",),
                {"kind": {"const": "notification"}},
            ),
            _object_contract(
                ("kind", "program_path"),
                {
                    "kind": {"const": "program"},
                    "program_path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": UI_COMMAND_MAX_PATH_CHARS,
                        "absoluteRegularFile": True,
                        "executable": True,
                    },
                    "argument_tokens": {
                        **token_array,
                        "maxItems": 0,
                    },
                    "redirect_outputs": {"type": "boolean"},
                    "start_mode": start_mode,
                    "working_directory": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": UI_COMMAND_MAX_PATH_CHARS,
                        "absoluteDirectory": True,
                    },
                },
                optional=(
                    "argument_tokens",
                    "redirect_outputs",
                    "start_mode",
                    "working_directory",
                ),
            ),
            {
                **_object_contract(
                    ("kind", "lua_script_path"),
                    {
                        "kind": {"const": "lua_script"},
                        "lua_script_path": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": UI_COMMAND_MAX_PATH_CHARS,
                            "absoluteRegularFile": True,
                        },
                        "argument_tokens": token_array,
                        "lua_module_directories": {
                            "type": "array",
                            "maxItems": UI_COMMAND_MAX_LUA_MODULE_DIRECTORIES,
                            "uniqueItems": True,
                            "caseInsensitiveUniqueItems": True,
                            "items": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": UI_COMMAND_MAX_PATH_CHARS,
                                "absoluteDirectory": True,
                            },
                        },
                        "lua_selected_return": {
                            "type": "array",
                            "maxItems": UI_COMMAND_MAX_LUA_RETURN_FIELDS,
                            "uniqueItems": True,
                            "caseInsensitiveUniqueItems": True,
                            "items": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": UI_COMMAND_MAX_LUA_RETURN_CHARS,
                            },
                        },
                        "start_mode": start_mode,
                        "working_directory": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": UI_COMMAND_MAX_PATH_CHARS,
                            "absoluteDirectory": True,
                        },
                    },
                    optional=(
                        "argument_tokens",
                        "lua_module_directories",
                        "lua_selected_return",
                        "start_mode",
                        "working_directory",
                    ),
                ),
                "supported_versions": sorted(UI_COMMAND_LUA_VERSIONS),
            },
        ],
    }
    return _object_contract(
        ("id", "display_name", "handler"),
        {
            "id": {
                "type": "string",
                "minLength": 1,
                "maxLength": UI_COMMAND_MAX_ID_CHARS,
            },
            "display_name": {
                "type": "string",
                "minLength": 1,
                "maxLength": UI_COMMAND_MAX_DISPLAY_NAME_CHARS,
            },
            "handler": handler,
            "context_menu": _object_contract(
                (),
                {
                    "base_path": {**menu_path, "minItems": 0},
                    "enabled_for": object_types,
                    "visible_for": object_types,
                },
                optional=("base_path", "enabled_for", "visible_for"),
            ),
            "default_shortcut": {
                "type": "string",
                "maxLength": UI_COMMAND_MAX_DEFAULT_SHORTCUT_CHARS,
            },
            "main_menu": _object_contract(
                ("base_path",),
                {"base_path": menu_path},
            ),
        },
        optional=("context_menu", "default_shortcut", "main_menu"),
    )


def _ui_command_source_authority_condition() -> Mapping[str, Any]:
    """Require the fixed assertion when any descriptor names a local path."""

    return {
        "if": {
            "properties": {
                "commands": {
                    "contains": {
                        "properties": {
                            "handler": {
                                "properties": {
                                    "kind": {
                                        "enum": ["program", "lua_script"]
                                    }
                                },
                                "required": ["kind"],
                            }
                        },
                        "required": ["handler"],
                    }
                }
            },
            "required": ["commands"],
        },
        "then": {"required": ["source_authority"]},
    }


class OperationContractError(ValueError):
    """A closed operation request cannot be accepted safely."""

    def __init__(self, error_code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {"error_code": self.error_code, "message": str(self), "details": dict(self.details)}


@dataclass(frozen=True, slots=True)
class OperationRequest:
    contract: str
    version: str
    operation: str
    arguments: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "version": self.version,
            "operation": self.operation,
            "arguments": dict(self.arguments),
        }


@dataclass(frozen=True, slots=True)
class OperationInputModeLane:
    """One explicit normal model-input choice for an operation/version lane.

    Lanes intentionally remain a sequence until validation.  A mapping would
    silently discard duplicate operation/version declarations before the
    Registry could reject them.
    """

    operation: str
    version: str
    input_mode: str


@dataclass(frozen=True, slots=True)
class OperationSpec:
    name: str
    uri: str
    family: str
    summary: str
    required_arguments: tuple[str, ...]
    optional_arguments: tuple[str, ...] = ()
    argument_contract: Mapping[str, Any] = field(default_factory=dict)
    identity_arguments: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    implemented: bool = True
    boundary: str | None = None
    supported_versions: tuple[str, ...] = SUPPORTED_WWISE_VERSION_KEYS
    selection_guidance: Mapping[str, Any] = field(default_factory=dict)
    parent_child_contract: Mapping[str, frozenset[str]] = field(
        default_factory=dict
    )
    file_read_policy: str | None = None
    next_step: str | None = None
    preview_owns: tuple[str, ...] = ()

    def as_compact_dict(self) -> dict[str, Any]:
        """Return the stable public inventory row without nested schemas."""

        return {
            "name": self.name,
            "uri": self.uri,
            "family": self.family,
            "summary": self.summary,
            "implemented": self.implemented,
            "boundary": self.boundary,
            "supported_versions": list(self.supported_versions),
            "required_arguments": list(self.required_arguments),
            "optional_arguments": list(self.optional_arguments),
        }

    def as_dict(self, *, version: str | None = None) -> dict[str, Any]:
        result = {
            "name": self.name,
            "uri": self.uri,
            "family": self.family,
            "summary": self.summary,
            "request_contract": OPERATION_REQUEST_CONTRACT,
            "required_arguments": list(self.required_arguments),
            "optional_arguments": list(self.optional_arguments),
            "additional_properties": False,
            "implemented": self.implemented,
            "boundary": self.boundary,
            "supported_versions": list(self.supported_versions),
            "argument_contract": _operation_argument_contract(
                self.name,
                self.argument_contract,
                version=version,
            ),
            "constraints": list(self.constraints),
        }
        if version is not None and version in self.supported_versions:
            result["input_mode"] = operation_input_mode(self.name, version)
        elif version is None:
            result["input_modes_by_version"] = operation_input_modes_by_version(
                self.name
            )
        if self.file_read_policy is not None:
            result["file_read_policy"] = self.file_read_policy
        if self.next_step is not None:
            result["next_step"] = self.next_step
        if self.preview_owns:
            result["preview_owns"] = list(self.preview_owns)
        if self.selection_guidance:
            result["selection_guidance"] = _json_mapping(self.selection_guidance)
        if self.parent_child_contract:
            result["parent_child_contract"] = {
                parent_type: sorted(child_types)
                for parent_type, child_types in sorted(
                    self.parent_child_contract.items()
                )
            }
        if self.identity_arguments:
            result["identity_contract"] = {
                "one_of": [
                    "id",
                    "path",
                    "exact-type-name",
                    "direct-child",
                    "scoped-name",
                ],
                "argument_fields": list(self.identity_arguments),
                "runtime_live_resolution_required": True,
                "exact_selector_goes_directly_to_preview": True,
                "separate_query_object_required": False,
                "separate_query_object_rule": (
                    "Do not query merely to translate an already exact id, "
                    "complete path, exact-type-name, direct-child, or "
                    "scoped-name selector; preview performs live resolution, "
                    "uniqueness, type, and parent checks. Query first only "
                    "when the user's target cannot yet be expressed by one "
                    "closed selector."
                ),
                "caller_rows_allowed": False,
            }
        return result


@dataclass(frozen=True, slots=True)
class PreparedOperation:
    request: OperationRequest
    semantic_preview: SemanticPreview
    resolved_roles: Mapping[str, Any]
    preflight_reads: tuple[Mapping[str, Any], ...]
    pre_state: Mapping[str, Any]
    verification_plan: Mapping[str, Any]
    cleanup: Mapping[str, Any]
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": PREPARED_OPERATION_CONTRACT,
            "request": self.request.as_dict(),
            "operation": self.request.operation,
            "version": self.request.version,
            "dispatch": self.semantic_preview.dispatch_payload(),
            "semantic_preview": self.semantic_preview.as_dict(),
            "resolved_roles": {key: _json_mapping(value) for key, value in self.resolved_roles.items()},
            "preflight_reads": [_json_mapping(item) for item in self.preflight_reads],
            "pre_state": _json_mapping(self.pre_state),
            "verification_plan": _json_mapping(self.verification_plan),
            "cleanup": _json_mapping(self.cleanup),
            "warnings": list(self.warnings),
            "raw_dispatch_allowed": False,
        }


@dataclass(frozen=True, slots=True)
class VerificationResult:
    operation: str
    status: str
    assertions: tuple[Mapping[str, Any], ...]
    readbacks: tuple[Mapping[str, Any], ...] = ()
    message: str = ""
    verification_strength: str = "operation_specific_readback"
    business_state_verified: bool = True

    @property
    def ok(self) -> bool:
        return self.status in {"verified", "result_schema_checked"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": VERIFICATION_RESULT_CONTRACT,
            "operation": self.operation,
            "status": self.status,
            "ok": self.ok,
            "assertions": [_json_mapping(item) for item in self.assertions],
            "readbacks": [_json_mapping(item) for item in self.readbacks],
            "message": self.message,
            "verification_strength": self.verification_strength,
            "business_state_verified": self.business_state_verified,
        }


ReadCall = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]

MAX_OBJECT_SET_BATCH_CHECK_READS = 512
MAX_OBJECT_SET_BATCH_CHECK_MESSAGE_CHARS = 1024

# Positive contract for dedicated operations whose adapters bind paths on the
# gateway machine. Generic ``waapi.call`` locality is derived separately from
# its versioned ``isolated_transaction`` execution route. Conditional UI
# descriptor paths and ``object.set`` import branches remain request-shaped and
# are classified by the locality module.
LOCAL_FILESYSTEM_OPERATION_ROLES: Mapping[str, tuple[str, ...]] = {
    "audio.import": (
        "arguments.imports[].audio_file",
        "live_project_files",
    ),
    "audio.importTabDelimited": (
        "arguments.import_file",
        "tab_file_audio_sources",
        "live_project_files",
    ),
    "lua.executeCliFile": (
        "arguments.io_root",
        "arguments.script_file",
    ),
    "lua.executeCoreFile": (
        "arguments.io_root",
        "arguments.script_file",
    ),
    "lua.executeCoreInline": ("arguments.io_root",),
    "soundbank.convertExternalSources": (
        "arguments.io_root",
        "arguments.sources[].input",
        "arguments.sources[].output",
    ),
    "soundbank.generate": (
        "arguments.io_root",
        "generated_artifacts",
        "live_project_path",
    ),
    "soundbank.processDefinitionFiles": (
        "arguments.files[]",
        "arguments.io_root",
        "live_project_path",
    ),
}
CONDITIONAL_LOCAL_FILESYSTEM_OPERATIONS = frozenset(
    {
        "object.set",
        "ui.commands.execute",
        "ui.commands.register",
        "ui.commands.unregister",
    }
)
DYNAMIC_LOCAL_FILESYSTEM_OPERATIONS = frozenset({"waapi.call"})
NO_LOCAL_FILESYSTEM_OPERATIONS = frozenset(
    {
        "debug.restartWaapiServers",
        "debug.setAsserts",
        "debug.setAutomationMode",
        "debug.testAssert",
        "debug.testCrash",
        "object.copy",
        "object.create",
        "object.createPlugin",
        "object.delete",
        "object.move",
        "object.setLinked",
        "object.setName",
        "object.setNotes",
        "object.setProperty",
        "object.setRTPC",
        "object.setReference",
        "soundbank.setInclusions",
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
        "ui.captureScreen",
        "waapi.undoGroup",
    }
)


def _selection_guidance(
    *,
    use_when: Sequence[str],
    avoid_when: Sequence[str] = (),
    preferred_over: Sequence[tuple[str, str]] = (),
    choose_instead: Sequence[tuple[str, str]] = (),
) -> Mapping[str, Any]:
    """Describe business-intent routing without changing execution authority."""

    return {
        "principle": (
            "Choose from the user's intended business outcome, not merely from "
            "whether this native API can encode the request."
        ),
        "use_when": tuple(use_when),
        "avoid_when": tuple(avoid_when),
        "preferred_over": tuple(
            {"target": target, "when": condition}
            for target, condition in preferred_over
        ),
        "choose_instead": tuple(
            {"target": target, "when": condition}
            for target, condition in choose_instead
        ),
    }


OPERATION_SPECS: Mapping[str, OperationSpec] = {
    "waapi.undoGroup": OperationSpec(
        "waapi.undoGroup",
        UNDO_BEGIN_GROUP_URI,
        "same-connection-compound",
        "Execute 1-32 reviewed project mutations inside one same-session Wwise Undo Group.",
        ("display_name", "calls"),
        argument_contract=_object_contract(
            ("display_name", "calls"),
            {
                "display_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": UNDO_GROUP_MAX_DISPLAY_NAME_LENGTH,
                },
                "calls": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": UNDO_GROUP_MAX_CALLS,
                    "items": _object_contract(
                        ("schema_digest", "request"),
                        {
                            "schema_digest": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
                            "request": {"type": "object"},
                        },
                    ),
                },
            },
        ),
        constraints=(
            "beginGroup, every inner mutation, and endGroup execute on one existing WAAPI client",
            "inner calls are selected from an immutable version-specific project-mutation allowlist",
            "inner failure triggers same-connection cancelGroup; cancellation is not rollback verification",
            "begin/end/cancel uncertainty is terminal and never retried automatically",
        ),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user explicitly wants several heterogeneous allowlisted mutations to appear as one Wwise Undo step.",
            ),
            avoid_when=(
                "One dedicated semantic operation already covers the complete batch and provides stronger operation-specific verification.",
                "The Agent is grouping unrelated changes without an explicit one-Undo-step intent.",
            ),
            choose_instead=(
                (
                    "the matching dedicated batch operation",
                    "one operation owns the complete requested outcome",
                ),
                (
                    "separate ordered transactions",
                    "the user requests several outcomes but not one Wwise Undo step",
                ),
            ),
        ),
    ),
    "waapi.call": OperationSpec(
        "waapi.call",
        "manifest://waapi.call",
        "public-execution-contract",
        "Execute one manifest-registered guarded function without model-authored code.",
        ("api",),
        ("args", "options", "io_root"),
        argument_contract=_object_contract(
            ("api",),
            {
                "api": {
                    "type": "string",
                    "pattern": r"^ak\.",
                    "description": (
                        "Reflected WAAPI URI at $.arguments.api; sibling of args, "
                        "options, and io_root."
                    ),
                },
                "args": {
                    "type": "object",
                    "description": (
                        "Only the reflected API arguments at $.arguments.args; "
                        "never place io_root or operation-envelope fields here."
                    ),
                },
                "options": {
                    "type": "object",
                    "description": (
                        "Reflected API options at $.arguments.options; use an empty "
                        "object when the request needs no options."
                    ),
                },
                "io_root": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Absolute isolated I/O root at $.arguments.io_root; it is a "
                        "sibling of api, args, and options and must never be nested "
                        "inside args."
                    ),
                },
            },
            optional=("args", "options", "io_root"),
        ),
        constraints=(
            "api must be reflected by the requested Wwise version",
            "api must resolve to transaction, managed_transaction, or isolated_transaction",
            "args/options must pass the packaged reflected schema",
            "isolated transactions audit absolute paths and confine explicit writes under io_root",
            "execution is bound to immutable preview authorization",
        ),
    ),
    "audio.import": OperationSpec(
        "audio.import",
        "ak.wwise.core.audio.import",
        "import",
        "Import media or object structure with validated properties/references and a closed createNew/useExisting/replaceExisting policy.",
        ("imports",),
        (
            "defaults",
            "import_operation",
            "auto_add_to_source_control",
            "auto_check_out_to_source_control",
        ),
        argument_contract={
            **_object_contract(
                ("imports",),
                {
                    "imports": {
                        "type": "array",
                        "minItems": 1,
                        "items": _object_contract(
                            IMPORT_ITEM_REQUIRED_FIELDS,
                            {
                                **_IMPORT_COMMON_ARGUMENT_PROPERTIES,
                            },
                            optional=IMPORT_ITEM_OPTIONAL_FIELDS,
                        ),
                    },
                    "defaults": _IMPORT_DEFAULT_ARGUMENT_SCHEMA,
                    "import_operation": _IMPORT_OPERATION_ARGUMENT_SCHEMA,
                    "auto_add_to_source_control": {"type": "boolean", "default": False},
                    "auto_check_out_to_source_control": _IMPORT_AUTO_CHECK_OUT_SCHEMA,
                },
                optional=(
                    "defaults",
                    "import_operation",
                    "auto_add_to_source_control",
                    "auto_check_out_to_source_control",
                ),
            ),
            "maximumEffectiveAudioFileBase64EncodedCharacters": (
                MAX_AUDIO_IMPORT_BASE64_ENCODED_CHARS
            ),
            "request_composition_contract": (
                _AUDIO_IMPORT_REQUEST_COMPOSITION_CONTRACT
            ),
        },
        constraints=(
            "all source files and targets are preflighted before the single dispatch",
            "defaults are expanded into sealed per-row values; row properties/references override defaults by exact token",
            "after defaults expansion, the sum of canonical audio_file_base64 strings is limited to 262144 encoded characters",
            "dynamic @ fields are produced only after live object-type and getPropertyInfo validation",
            "each row accepts one regular audio_file, one bounded RIFF/WAVE audio_file_base64, or a typed structure-only import",
            "useExisting preserves an existing target GUID; replaceExisting requires the old GUID to disappear",
            "a live non-SFX localized useExisting row dispatches only audioFile/objectPath/importLanguage; objectType is consumed by live type preflight and other requested row fields are rejected",
            "replaceExisting is irreversible and must be exercised only in a disposable project copy during tests",
            "auto_add_to_source_control is explicit and defaults to false",
            "auto_check_out_to_source_control defaults to false and is accepted only in Wwise 2023.1-2025.1; explicit use on 2021.1/2022.1 fails before connection",
        ),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user describes media, object paths, properties, references, Events, or import defaults directly, for one row or a batch.",
                "Media import is the primary business outcome, including create, reuse, or replace of target objects.",
                "Structure-only rows are part of the same explicit import manifest.",
                "Event or Switch Assignation creation is an explicit side effect of those same imported rows.",
            ),
            avoid_when=(
                "The user already supplied a tab-delimited file or explicitly requested that existing table workflow.",
                "The request is only a new object hierarchy with no media or import-manifest intent.",
                "In Wwise 2023.1 or later, media import is only one subordinate part of a broader atomic mutation of existing objects.",
            ),
            preferred_over=(
                (
                    "audio.importTabDelimited",
                    "the Agent would otherwise have to invent an intermediate TSV, or batch size is the only reason to choose a table",
                ),
                (
                    "object.create",
                    "media import is the primary requested outcome",
                ),
                (
                    "object.set",
                    "the request is only an import rather than a broader existing-object mutation",
                ),
                (
                    "switchContainer.addAssignment",
                    "the Switch Assignation is part of the same media import rather than an independent edit to existing objects",
                ),
            ),
            choose_instead=(
                (
                    "audio.importTabDelimited",
                    "the caller owns an existing TSV or explicitly requests that file-based workflow",
                ),
                (
                    "object.create",
                    "the request is a pure new object tree with no media",
                ),
                (
                    "object.set",
                    "Wwise is 2023.1 or later and the import belongs inside a broader atomic mutation of existing targets",
                ),
            ),
        ),
    ),
    "audio.importTabDelimited": OperationSpec(
        "audio.importTabDelimited",
        "ak.wwise.core.audio.importTabDelimited",
        "import",
        "Import a bounded strict-UTF-8 tab-delimited file with native property/reference, base64, Event, Dialogue Event, and Switch Assignation columns.",
        ("import_file", "import_location", "import_language"),
        (
            "import_operation",
            "auto_add_to_source_control",
            "auto_check_out_to_source_control",
        ),
        argument_contract={
            **_object_contract(
                ("import_file", "import_location", "import_language"),
                {
                    "import_file": {
                        "type": "string",
                        "absoluteRegularFile": True,
                    },
                    "import_location": IDENTITY_ARGUMENT_SCHEMA,
                    "import_language": {"type": "string", "minLength": 1},
                    "import_operation": _IMPORT_OPERATION_ARGUMENT_SCHEMA,
                    "auto_add_to_source_control": {
                        "type": "boolean",
                        "default": False,
                    },
                    "auto_check_out_to_source_control": (
                        _IMPORT_AUTO_CHECK_OUT_SCHEMA
                    ),
                },
                optional=(
                    "import_operation",
                    "auto_add_to_source_control",
                    "auto_check_out_to_source_control",
                ),
            ),
            "import_operation_contract": _IMPORT_OPERATION_INTENT_CONTRACT,
        },
        identity_arguments=("import_location",),
        constraints=(
            "fixed and dynamic native headers are parsed under bounded grammar; importLanguage remains a call argument",
            "the parser hashes the TSV, regular media, and decoded inline base64 before preview",
            "a missing or invalid row rejects the whole request before dispatch",
            "auto_add_to_source_control is explicit and defaults to false",
            "auto_check_out_to_source_control defaults to false and is accepted only in Wwise 2023.1-2025.1; explicit use on 2021.1/2022.1 fails before connection",
        ),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user supplies an existing absolute TSV and asks Wwise Authoring to process it.",
                "The user explicitly requests the native tab-delimited import workflow, replay, or externally maintained import manifest.",
            ),
            avoid_when=(
                "The Agent would need to create a TSV solely to translate natural-language parameters.",
                "The only reason for choosing this operation is that the import contains many rows.",
            ),
            choose_instead=(
                (
                    "audio.import",
                    "the import rows are expressed directly by the user or can be represented directly in the closed request",
                ),
                (
                    "waapi.call",
                    "the user explicitly requests WwiseConsole or CLI tab-delimited import rather than the connected Authoring project",
                ),
            ),
        ),
        file_read_policy="pass_path_without_reading",
        next_step="preview",
        preview_owns=(
            "tsv_parsing",
            "tsv_hash_validation",
            "inline_base64_validation",
            "media_validation",
            "exact_path_conflict_validation",
        ),
    ),
    "object.create": OperationSpec(
        "object.create",
        "ak.wwise.core.object.create",
        "object-mutation",
        "Create or merge one bounded recursive object tree under a live-resolved parent, including a guarded replace confined to one explicitly authorized root.",
        ("parent", "type", "name"),
        (
            "notes",
            "properties",
            "references",
            "children",
            "platform",
            "list",
            "auto_add_to_source_control",
            "on_name_conflict",
            "replace_owned_root",
        ),
        argument_contract=_object_contract(
            ("parent", "type", "name"),
            {
                "parent": IDENTITY_ARGUMENT_SCHEMA,
                "type": _OBJECT_CREATE_TYPE_TOKEN_SCHEMA,
                "name": {"type": "string", "minLength": 1},
                "on_name_conflict": {
                    "type": "string",
                    "enum": ["fail", "rename", "merge", "replace"],
                },
                "notes": {"type": "string"},
                "properties": {"type": "array", "items": _OBJECT_PROPERTY_ARGUMENT_SCHEMA},
                "references": {"type": "array", "items": _OBJECT_REFERENCE_ARGUMENT_SCHEMA},
                "platform": PLATFORM_ARGUMENT_SCHEMA,
                "list": _OBJECT_LIST_NAME_SCHEMA,
                "auto_add_to_source_control": {"type": "boolean", "default": False},
                "children": {
                    "type": "array",
                    "items": _OBJECT_NODE_ARGUMENT_SCHEMA,
                    "description": (
                        "Recursive closed node DSL; raw @ keys, lists, plug-ins, and RTPCs are rejected. "
                        "For an existing named request root, keep its existing parent as parent, repeat "
                        "the root type/name, and use on_name_conflict=merge."
                    ),
                },
                "replace_owned_root": {
                    **IDENTITY_ARGUMENT_SCHEMA,
                    "description": (
                        "The reviewed non-protected authorization boundary that must be a "
                        "strict ancestor of the exact collision; it is not the object being "
                        "replaced. When creating name X under parent P and replacing P\\X, "
                        "parent and replace_owned_root are normally both P. The name still "
                        "limits deletion to P\\X, so siblings below P are not replaced."
                    ),
                },
            },
            optional=(
                "notes",
                "properties",
                "references",
                "children",
                "platform",
                "list",
                "auto_add_to_source_control",
                "on_name_conflict",
                "replace_owned_root",
            ),
        ),
        identity_arguments=("parent", "replace_owned_root"),
        constraints=(
            "maximum depth 8, 128 nodes, and 32 children per parent",
            "one existing named root that only receives a recursive descendant merge remains an object.create request: identify its existing parent, repeat the root type/name, and use on_name_conflict=merge",
            "when that existing merge root's exact type was not stated or already proven, perform one exact-path query-object returning id, name, type, and path before operation-schema so its sole continuation remains uninterrupted; Wwise 2025.1 PropertyContainer readback maps to the ActorMixer request token",
            "ordinary child creation requires one reviewed writable hierarchy parent; list creation requires a non-protected live owner and a canonical list token",
            "Game Sync hierarchy creation is closed to StateGroup -> State and SwitchGroup -> Switch, whether the live parent is a group or the group appears inside the recursive tree",
            "replace_owned_root is an explicit reviewed authorization boundary, not independently proven ownership; replace requires the collision strictly below that non-protected live root and a complete pre-state snapshot of at most 128 old subtree GUID/path rows",
            "list insertion supports fail, rename, and merge but not replace; raw @ fields, classId, plug-ins, and RTPC rows are not exposed",
            "platform applies to validated properties/references and is verified through the same platform view",
            "auto_add_to_source_control is explicit and defaults to false",
            "the complete returned GUID topology and every requested field are read back after execution",
        ),
        parent_child_contract=OBJECT_CREATE_SPECIALIZED_CHILD_TYPES_BY_PARENT,
        selection_guidance=_selection_guidance(
            use_when=(
                "The request creates one wholly new recursive root.",
                "Exactly one same-name existing root remains unchanged while only a descendant tree is merged below it.",
                "The request replaces one exact same-name subtree through the guarded on_name_conflict=replace contract.",
            ),
            avoid_when=(
                "The request changes fields or references on an existing root, targets multiple existing roots, or appends children directly to an explicitly existing descendant container below the named request root; the named request root itself is not that descendant insertion target.",
                "Media import is the primary requested outcome.",
                "The Agent would otherwise emulate copy, move, or delete-plus-create behavior.",
            ),
            preferred_over=(
                (
                    "audio.import",
                    "the request is a pure object hierarchy with no media and no import-manifest intent",
                ),
                (
                    "object.delete",
                    "the requested outcome is one guarded same-name subtree replacement rather than deletion alone",
                ),
            ),
            choose_instead=(
                (
                    "object.set",
                    "an existing root changes fields or references, several existing roots change atomically, or an explicitly existing descendant below the named request root is the direct insertion target",
                ),
                (
                    "audio.import",
                    "media import is the primary requested outcome",
                ),
                (
                    "object.copy or object.move",
                    "the user explicitly requests copy or move; report their packaged boundary rather than emulate them",
                ),
            ),
        ),
    ),
    "object.delete": OperationSpec(
        "object.delete",
        "ak.wwise.core.object.delete",
        "object-mutation",
        "Delete one live-resolved non-protected object and verify GUID absence.",
        ("object",),
        ("auto_check_out_to_source_control",),
        argument_contract=_object_contract(
            ("object",),
            {
                "object": IDENTITY_ARGUMENT_SCHEMA,
                "auto_check_out_to_source_control": _DELETE_AUTO_CHECK_OUT_SCHEMA,
            },
            optional=("auto_check_out_to_source_control",),
        ),
        identity_arguments=("object",),
        constraints=(
            "auto_check_out_to_source_control defaults to false and is accepted only in Wwise 2023.1-2025.1; explicit use on 2021.1/2022.1 fails before connection",
        ),
        selection_guidance=_selection_guidance(
            use_when=("The intended outcome is deletion of one existing object and nothing replaces it.",),
            avoid_when=(
                "Deletion is only an implementation step toward replace, move, or another higher-level outcome.",
            ),
            choose_instead=(
                (
                    "object.create",
                    "one exact same-name subtree replacement fits its guarded replace contract",
                ),
                (
                    "object.move",
                    "the intended outcome is moving an object; report the packaged boundary rather than synthesize delete/create",
                ),
            ),
        ),
    ),
    "object.setName": OperationSpec(
        "object.setName",
        "ak.wwise.core.object.setName",
        "property-reference",
        "Rename one live-resolved object and verify the same GUID at its new path.",
        ("object", "value"),
        argument_contract=_object_contract(
            ("object", "value"),
            {"object": IDENTITY_ARGUMENT_SCHEMA, "value": {"type": "string", "minLength": 1}},
        ),
        identity_arguments=("object",),
        selection_guidance=_selection_guidance(
            use_when=("Exactly one existing object receives only a rename.",),
            avoid_when=("The rename is one part of a multi-field or multi-object atomic change.",),
            preferred_over=(("object.set", "the request is only one isolated rename"),),
            choose_instead=(("object.set", "several changes must remain in one batch"),),
        ),
    ),
    "object.setNotes": OperationSpec(
        "object.setNotes",
        "ak.wwise.core.object.setNotes",
        "property-reference",
        "Set notes on one live-resolved object and verify exact text.",
        ("object", "value"),
        argument_contract=_object_contract(
            ("object", "value"),
            {"object": IDENTITY_ARGUMENT_SCHEMA, "value": {"type": "string"}},
        ),
        identity_arguments=("object",),
        selection_guidance=_selection_guidance(
            use_when=("Exactly one existing object receives only a notes change.",),
            avoid_when=("The notes edit is one part of a multi-field or multi-object atomic change.",),
            preferred_over=(("object.set", "the request is only one isolated notes edit"),),
            choose_instead=(("object.set", "several changes must remain in one batch"),),
        ),
    ),
    "object.setProperty": OperationSpec(
        "object.setProperty",
        "ak.wwise.core.object.setProperty",
        "property-reference",
        "Set one property for the current or an explicit platform using live property metadata and typed readback.",
        ("object", "property", "value"),
        ("platform",),
        argument_contract=_object_contract(
            ("object", "property", "value"),
            {
                "object": IDENTITY_ARGUMENT_SCHEMA,
                "property": {"type": "string", "minLength": 1},
                "value": {"description": "JSON scalar accepted only after live property metadata validation."},
                "platform": PLATFORM_ARGUMENT_SCHEMA,
            },
            optional=("platform",),
        ),
        identity_arguments=("object",),
        selection_guidance=_selection_guidance(
            use_when=("Exactly one existing object receives one scalar property value.",),
            avoid_when=(
                "Several properties, references, objects, children, or imports must change atomically.",
                "The requested concept is platform link state or an RTPC curve rather than a scalar value.",
            ),
            preferred_over=(("object.set", "the request is one isolated scalar property edit"),),
            choose_instead=(
                ("object.set", "several ordinary changes must remain in one batch"),
                ("object.setLinked", "the user asks to link or unlink a platform value"),
                ("object.setRTPC", "the user asks for an RTPC curve"),
            ),
        ),
    ),
    "object.setReference": OperationSpec(
        "object.setReference",
        "ak.wwise.core.object.setReference",
        "property-reference",
        "Set or clear one reference for the current or an explicit platform after resolving every non-null identity.",
        ("object", "reference", "target"),
        ("platform",),
        argument_contract=_object_contract(
            ("object", "reference", "target"),
            {
                "object": IDENTITY_ARGUMENT_SCHEMA,
                "reference": {"type": "string", "minLength": 1},
                "target": {
                    "oneOf": [
                        IDENTITY_ARGUMENT_SCHEMA,
                        {
                            "type": "null",
                            "description": (
                                "Explicitly clear the reference; omitted target is "
                                "never interpreted as a clear request."
                            ),
                        },
                    ]
                },
                "platform": PLATFORM_ARGUMENT_SCHEMA,
            },
            optional=("platform",),
        ),
        identity_arguments=("object", "target"),
        constraints=(
            "target=null is an explicit closed clear operation and is rejected when live metadata contains a notNull restriction",
            "a non-null target is live-resolved and checked against live reference type restrictions",
            "when a prior successful Gateway read returned an exact id for object or target, copy that id exactly; do not retype its path or name",
        ),
        selection_guidance=_selection_guidance(
            use_when=("Exactly one existing object receives one reference set or clear.",),
            avoid_when=(
                "Several references, fields, objects, or children must change atomically.",
                "The request changes platform link state instead of the reference target.",
            ),
            preferred_over=(("object.set", "the request is one isolated reference edit"),),
            choose_instead=(
                ("object.set", "several ordinary changes must remain in one batch"),
                ("object.setLinked", "the user asks to link or unlink the reference for a platform"),
            ),
        ),
    ),
    "object.setLinked": OperationSpec(
        "object.setLinked",
        OBJECT_SET_LINKED_URI,
        "property-reference",
        "Link or unlink one property, reference, or object list for one explicit platform.",
        ("object", "property", "platform", "linked"),
        argument_contract=_object_contract(
            ("object", "property", "platform", "linked"),
            {
                "object": IDENTITY_ARGUMENT_SCHEMA,
                "property": {"type": "string", "minLength": 1},
                "platform": PLATFORM_ARGUMENT_SCHEMA,
                "linked": {"type": "boolean"},
            },
        ),
        identity_arguments=("object",),
        constraints=(
            "pre-state and post-state are read with ak.wwise.core.object.isLinked",
            "the platform is explicit and the linked value must be a JSON boolean",
            "the same object/property/platform tuple is rebound before execution",
        ),
        supported_versions=("2023.1", "2024.1", "2025.1"),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user explicitly asks to link or unlink one property, reference, or object list for a platform.",
            ),
            avoid_when=("The user wants to change the field value rather than its platform link state.",),
            preferred_over=(
                ("object.setProperty", "the requested outcome is link state, not a scalar property value"),
                ("object.setReference", "the requested outcome is link state, not a reference target"),
                ("object.set", "the requested outcome is link state, which object.set intentionally does not own"),
            ),
        ),
    ),
    "object.createPlugin": OperationSpec(
        "object.createPlugin",
        OBJECT_SET_URI,
        "object-mutation",
        (
            "Create one Source or Effect plug-in from an exact classId through "
            "the version-correct Wwise object topology."
        ),
        ("target", "plugin"),
        argument_contract=_object_contract(
            ("target", "plugin"),
            {
                "target": IDENTITY_ARGUMENT_SCHEMA,
                "plugin": _PLUGIN_CREATION_ARGUMENT_SCHEMA,
            },
        ),
        identity_arguments=("target",),
        constraints=(
            "target resolves live to exactly one canonical object before preview",
            "class_id is an exact caller-supplied uint32 and is never guessed from a plug-in display name",
            "every requested property is validated by classId-scoped live getPropertyInfo metadata",
            "Source plug-ins are create-only children of Sound or Voice targets",
            "Wwise 2022.1 Effects use the first proven-empty @Effect0 through @Effect3 reference",
            "Wwise 2023.1 and later Effects append one EffectSlot and verify its @Effect reference",
            "pre-existing plug-in identities are sealed before dispatch; replacement, raw replaceAll, and caller-authored object.set payloads are rejected",
            "the returned association and post-read id/name/type/classId/parent/owner must bind uniquely to the immutable plan",
        ),
        supported_versions=("2022.1", "2023.1", "2024.1", "2025.1"),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user asks to create one Source or Effect plug-in from an exact supplied classId.",
            ),
            avoid_when=(
                "The request is ordinary object creation with no plug-in semantics.",
                "The Agent would have to guess a classId from a display name.",
            ),
            preferred_over=(
                ("object.create", "the requested object is a Source or Effect plug-in"),
                ("object.set", "the requested list mutation is plug-in creation"),
            ),
        ),
    ),
    "object.setRTPC": OperationSpec(
        "object.setRTPC",
        OBJECT_SET_URI,
        "object-mutation",
        "Add or update one RTPC curve through a closed property, ControlInput, and point contract.",
        ("object", "property", "control_input", "points"),
        ("notes", "mode"),
        argument_contract=_object_contract(
            ("object", "property", "control_input", "points"),
            {
                "object": IDENTITY_ARGUMENT_SCHEMA,
                "property": {"type": "string", "minLength": 1},
                "control_input": IDENTITY_ARGUMENT_SCHEMA,
                "points": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 256,
                    "items": _RTPC_POINT_ARGUMENT_SCHEMA,
                },
                "notes": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["add", "add_or_replace"],
                    "default": "add_or_replace",
                    "x-discloseDescription": True,
                    "description": (
                        "Use add_or_replace when the user asks to replace the "
                        "matching RTPC if present and add it if absent; use add "
                        "only when an existing exact property and ControlInput "
                        "match must fail."
                    ),
                },
            },
            optional=("notes", "mode"),
        ),
        identity_arguments=("object", "control_input"),
        constraints=(
            "live getPropertyInfo must report RTPC support for the requested property",
            "the ControlInput resolves to exactly one existing GameParameter, MIDI, or Modulator object",
            "add appends one typed @RTPC row; add_or_replace updates one exact property/ControlInput match in place",
            "raw @RTPC rows and caller-authored listMode/replaceAll are never accepted",
            "the complete RTPC list is sealed before execution and read back after execution",
        ),
        supported_versions=("2022.1", "2023.1", "2024.1", "2025.1"),
        selection_guidance=_selection_guidance(
            use_when=("The user asks to add or update one RTPC curve.",),
            avoid_when=("The request is only a scalar property value with no ControlInput curve.",),
            preferred_over=(
                ("object.setProperty", "the requested outcome is an RTPC curve"),
                ("object.set", "the requested list mutation is an RTPC curve"),
            ),
        ),
    ),
    "object.set": OperationSpec(
        "object.set",
        "ak.wwise.core.object.set",
        "object-mutation",
        "Batch fields, renames, recursive children, and closed object-list creation against live-resolved targets.",
        ("objects",),
        (
            "platform",
            "list_mode",
            "on_name_conflict",
            "auto_add_to_source_control",
        ),
        argument_contract={
            **_object_contract(
                ("objects",),
                {
                    "objects": {
                        "type": "array",
                        "minItems": 1,
                        "description": (
                            "Each existing object that receives fields or new direct children is its own "
                            "target row, including an existing nested container."
                        ),
                        "items": _object_contract(
                            ("object",),
                            {
                                "object": IDENTITY_ARGUMENT_SCHEMA,
                                "name": {"type": "string", "minLength": 1},
                                "notes": {"type": "string"},
                                "platform": PLATFORM_ARGUMENT_SCHEMA,
                                "list_mode": {
                                    "type": "string",
                                    "enum": ["append", "replaceAll"],
                                },
                                "on_name_conflict": {
                                    "type": "string",
                                    "enum": ["fail", "rename", "merge"],
                                },
                                "properties": {"type": "array", "items": _OBJECT_PROPERTY_ARGUMENT_SCHEMA},
                                "references": {"type": "array", "items": _OBJECT_REFERENCE_ARGUMENT_SCHEMA},
                                "import": {
                                    **_OBJECT_SET_IMPORT_ARGUMENT_SCHEMA,
                                    "supported_versions": ["2023.1", "2024.1", "2025.1"],
                                    "description": (
                                        "Import media into the existing live-resolved target. "
                                        "Only reviewed importable object types are accepted."
                                    ),
                                },
                                "children": {
                                    "type": "array",
                                    "items": _OBJECT_SET_NODE_ARGUMENT_SCHEMA,
                                    "description": (
                                        "Only genuinely new direct children belong here. Never redeclare an "
                                        "existing nested container as a child; give it a separate objects[] "
                                        "row and put only its new descendants there."
                                    ),
                                },
                                "lists": {
                                    "type": "array",
                                    "maxItems": 32,
                                    "items": _OBJECT_LIST_ARGUMENT_SCHEMA,
                                    "description": (
                                        "Closed native object-list assignments. Plug-in and RTPC "
                                        "lists remain routed through object.createPlugin and object.setRTPC."
                                    ),
                                },
                            },
                            optional=(
                                "name",
                                "notes",
                                "platform",
                                "list_mode",
                                "on_name_conflict",
                                "properties",
                                "references",
                                "import",
                                "children",
                                "lists",
                            ),
                        ),
                    },
                    "platform": PLATFORM_ARGUMENT_SCHEMA,
                    "list_mode": {
                        "type": "string",
                        "enum": ["append", "replaceAll"],
                        "default": "append",
                    },
                    "on_name_conflict": {
                        "type": "string",
                        "enum": ["fail", "rename", "merge"],
                        "default": "fail",
                        "description": (
                            "Applies only to genuinely new children, never to existing objects[] "
                            "targets. Omission defaults to fail. Use fail for children requested "
                            "as new or absent; use merge only when the user explicitly requests "
                            "collision merging for a new child name."
                        ),
                    },
                    "auto_add_to_source_control": {"type": "boolean", "default": False},
                },
                optional=(
                    "platform",
                    "list_mode",
                    "on_name_conflict",
                    "auto_add_to_source_control",
                ),
            ),
            "maximumCanonicalRequestBytes": DEFAULT_MAX_REQUEST_BYTES,
        },
        identity_arguments=("objects[].object",),
        constraints=(
            "seal every target and field pre-state before one non-retryable batch dispatch",
            "nested containers receiving descendants are separate objects[] targets; children are new direct descendants",
            "existing objects[] targets do not imply merge; on_name_conflict applies only to new child/list-member names",
            "top-level platform, list_mode, and on_name_conflict may be overridden by one closed target row",
            "a requested name keeps the same GUID and parent; fail/rename collisions are sealed before dispatch",
            "each target row may set properties/references for one effective platform; link state remains the dedicated object.setLinked operation",
            "closed object lists are emitted only from [{name, objects}] descriptors; plug-ins and RTPCs remain dedicated operations",
            "replaceAll seals every current direct list member and every descendant GUID, rechecks the complete snapshot before execution, and verifies exact replacement afterward",
            "canonical request limit: 262144 bytes including inline Base64 audio",
            "auto_add_to_source_control is explicit and defaults to false",
            "partial results or per-target readback mismatches fail verification",
        ),
        supported_versions=("2022.1", "2023.1", "2024.1", "2025.1"),
        parent_child_contract=OBJECT_CREATE_SPECIALIZED_CHILD_TYPES_BY_PARENT,
        selection_guidance=_selection_guidance(
            use_when=(
                "One atomic request changes fields, references, or lists on existing targets.",
                "The request targets multiple existing objects.",
                "Children are appended directly to an explicitly existing descendant container below the named request root; the named request root itself is not that descendant insertion target.",
                "In Wwise 2023.1 or later, media import is subordinate to a broader mutation of existing targets.",
            ),
            avoid_when=(
                "The request is only one isolated rename, notes edit, scalar property edit, or reference edit.",
                "The request is a wholly new recursive root or a pure descendant-tree merge below one unchanged same-name root.",
                "Media import alone is the primary requested outcome.",
                "The requested concept is plug-in creation, RTPC editing, or platform link state.",
            ),
            preferred_over=(
                ("object.setName", "rename is only one part of a larger atomic batch"),
                ("object.setNotes", "notes are only one part of a larger atomic batch"),
                ("object.setProperty", "properties are only part of a larger atomic batch"),
                ("object.setReference", "references are only part of a larger atomic batch"),
                ("audio.import", "Wwise is 2023.1 or later and import is subordinate to the same broader existing-object mutation"),
            ),
            choose_instead=(
                (
                    "object.create",
                    "the request is a new root or only merges descendants below one unchanged same-name existing request root",
                ),
                ("audio.import", "the request is primarily media import"),
                ("object.createPlugin", "the request creates a Source or Effect plug-in"),
                ("object.setRTPC", "the request adds or updates an RTPC curve"),
                ("object.setLinked", "the request changes platform link state"),
            ),
        ),
    ),
    "lua.executeCliFile": OperationSpec(
        "lua.executeCliFile",
        CLI_EXECUTE_LUA_URI,
        "explicit-user-code",
        "Execute one existing user-supplied Lua file through the Wwise CLI endpoint.",
        ("script_file", "io_root", "source_authority"),
        ("wa_args", "watchdog_seconds"),
        argument_contract=_object_contract(
            ("script_file", "io_root", "source_authority"),
            {
                "script_file": _LUA_FILE_SCHEMA,
                "io_root": {
                    "type": "string",
                    "absoluteExistingDirectory": True,
                },
                "source_authority": _LUA_SOURCE_AUTHORITY_SCHEMA,
                "wa_args": _LUA_WA_ARGS_SCHEMA,
                "watchdog_seconds": {
                    "type": "integer",
                    "minimum": 0,
                    "supported_versions": ["2024.1", "2025.1"],
                },
            },
            optional=("wa_args", "watchdog_seconds"),
        ),
        constraints=(
            "script_file must be an existing non-symlink .lua file canonically contained by io_root",
            "the complete file size and SHA-256 are sealed at preview and rechecked before execution",
            "source_authority is a caller assertion, not runtime provenance proof, and may be set only for a path supplied verbatim in the current user message",
            "do-file, lua-path, require, migration, project, and arbitrary loader switches are not exposed",
            "watchdog_seconds is accepted only in Wwise 2024.1-2025.1",
            "Lua side effects are not inferred, confined, rolled back, or retried",
        ),
        supported_versions=("2023.1", "2024.1", "2025.1"),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user explicitly asks for WwiseConsole or CLI execution of an existing Lua file and supplies its exact path.",
            ),
            avoid_when=(
                "The request is for the already connected Authoring project.",
                "The Agent would have to author, repair, wrap, or synthesize Lua.",
            ),
            choose_instead=(
                ("lua.executeCoreFile", "the user wants the existing file executed in connected Authoring"),
                ("lua.executeCoreInline", "Wwise is 2025.1 and the user supplied exact inline Lua rather than a file"),
            ),
        ),
    ),
    "lua.executeCoreFile": OperationSpec(
        "lua.executeCoreFile",
        CORE_EXECUTE_LUA_URI,
        "explicit-user-code",
        "Execute one existing user-supplied Lua file in connected Wwise Authoring.",
        ("script_file", "io_root", "source_authority"),
        ("wa_args",),
        argument_contract=_object_contract(
            ("script_file", "io_root", "source_authority"),
            {
                "script_file": _LUA_FILE_SCHEMA,
                "io_root": {
                    "type": "string",
                    "absoluteExistingDirectory": True,
                },
                "source_authority": _LUA_SOURCE_AUTHORITY_SCHEMA,
                "wa_args": _LUA_WA_ARGS_SCHEMA,
            },
            optional=("wa_args",),
        ),
        constraints=(
            "script_file must be an existing non-symlink .lua file canonically contained by io_root",
            "the complete file size and SHA-256 are sealed at preview and rechecked before execution",
            "source_authority is a caller assertion, not runtime provenance proof, and may be set only for a path supplied verbatim in the current user message",
            "doFiles, luaPaths, requires, and hidden helper source are not exposed",
            "Lua side effects are not inferred, confined, rolled back, or retried",
        ),
        supported_versions=("2023.1", "2024.1", "2025.1"),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user supplies an existing Lua file and wants it executed in the connected Authoring process.",
            ),
            avoid_when=(
                "The user explicitly asks for WwiseConsole or CLI execution.",
                "The Agent would have to author, repair, wrap, or synthesize Lua.",
            ),
            choose_instead=(
                ("lua.executeCliFile", "the user explicitly requests the CLI host"),
                ("lua.executeCoreInline", "Wwise is 2025.1 and the user supplied exact inline Lua rather than a file"),
            ),
        ),
    ),
    "lua.executeCoreInline": OperationSpec(
        "lua.executeCoreInline",
        CORE_EXECUTE_LUA_URI,
        "explicit-user-code",
        "Execute one exact user-supplied inline Lua string in Wwise 2025.1.",
        ("lua_code", "io_root", "source_authority"),
        ("wa_args",),
        argument_contract=_object_contract(
            ("lua_code", "io_root", "source_authority"),
            {
                "lua_code": {
                    "type": "string",
                    "minLength": 1,
                    "maximumBytes": MAX_LUA_SOURCE_BYTES,
                },
                "io_root": {
                    "type": "string",
                    "absoluteExistingDirectory": True,
                },
                "source_authority": _LUA_SOURCE_AUTHORITY_SCHEMA,
                "wa_args": _LUA_WA_ARGS_SCHEMA,
            },
            optional=("wa_args",),
        ),
        constraints=(
            "source_authority is a caller assertion, not runtime provenance proof; lua_code must be copied byte-for-byte from the current user message and is sealed by size and SHA-256",
            "io_root is an explicit isolated transaction context; Lua's implicit side effects are still not claimed confined",
            "the Skill never generates, repairs, wraps, or augments the Lua string",
            "luaScript, doFiles, luaPaths, requires, and hidden helper source are not exposed",
            "Lua side effects are not inferred, confined, rolled back, or retried",
        ),
        supported_versions=("2025.1",),
        selection_guidance=_selection_guidance(
            use_when=(
                "Wwise is 2025.1 and the current user message supplies the exact inline Lua to execute in connected Authoring.",
            ),
            avoid_when=(
                "The user supplied a Lua file path rather than complete inline source.",
                "The Agent would have to author, repair, wrap, or augment the Lua.",
            ),
            choose_instead=(
                ("lua.executeCoreFile", "the user supplied an existing file for connected Authoring"),
                ("lua.executeCliFile", "the user explicitly requests CLI execution of an existing file"),
            ),
        ),
    ),
    "debug.setAsserts": OperationSpec(
        "debug.setAsserts",
        DEBUG_ENABLE_ASSERTS_URI,
        "debug-runtime",
        "Apply one policy-gated process-wide debug-assert ref-count change.",
        ("enable",),
        argument_contract=_object_contract(
            ("enable",),
            {"enable": {"type": "boolean"}},
        ),
        constraints=(
            "the endpoint has no state getter; verification proves only the reflected result schema",
            "Wwise implements a process-wide ref-count, so this operation is never retried or described as idempotent",
        ),
    ),
    "debug.setAutomationMode": OperationSpec(
        "debug.setAutomationMode",
        DEBUG_ENABLE_AUTOMATION_MODE_URI,
        "debug-runtime",
        "Enable or disable Wwise automation mode through an immutable policy-gated preview.",
        ("enable",),
        argument_contract=_object_contract(
            ("enable",),
            {"enable": {"type": "boolean"}},
        ),
        constraints=(
            "automation mode affects process-wide dialog and popup handling",
            "the endpoint has no state getter; verification proves only the reflected result schema",
            "the operation is never retried automatically",
        ),
    ),
    "debug.restartWaapiServers": OperationSpec(
        "debug.restartWaapiServers",
        DEBUG_RESTART_WAAPI_SERVERS_URI,
        "dangerous-host-control",
        "Request a WAAPI server restart and terminate the transaction without reconnecting.",
        ("acknowledge",),
        argument_contract=_object_contract(
            ("acknowledge",),
            {"acknowledge": {"const": "restart_waapi_servers"}},
        ),
        constraints=(
            "the immutable acknowledgement distinguishes this from an ordinary WAAPI call",
            "disconnect is expected; delivery and server restart completion may remain indeterminate",
            "the Wwise process is expected to remain running, but this gateway does not claim lifecycle observation",
            "there is no automatic retry, reconnect, or generic verify phase",
        ),
        supported_versions=("2023.1", "2024.1", "2025.1"),
    ),
    "debug.testAssert": OperationSpec(
        "debug.testAssert",
        DEBUG_TEST_ASSERT_URI,
        "dangerous-host-control",
        "Deliberately trigger Wwise's private test assertion after explicit confirmation.",
        ("acknowledge",),
        argument_contract=_object_contract(
            ("acknowledge",),
            {"acknowledge": {"const": "trigger_debug_assert"}},
        ),
        constraints=(
            "the immutable acknowledgement distinguishes this deliberate failure from an ordinary call",
            "an assertion dialog, assertFailed event, disconnect, or continued process are host-build dependent",
            "there is no automatic retry, cleanup promise, or business-state verification",
        ),
    ),
    "debug.testCrash": OperationSpec(
        "debug.testCrash",
        DEBUG_TEST_CRASH_URI,
        "dangerous-host-control",
        "Deliberately request Wwise process termination after explicit confirmation.",
        ("acknowledge",),
        argument_contract=_object_contract(
            ("acknowledge",),
            {"acknowledge": {"const": "crash_wwise_process"}},
        ),
        constraints=(
            "the immutable acknowledgement distinguishes this deliberate crash from an ordinary call",
            "disconnect and process termination are expected, but delivery and lifecycle completion may remain indeterminate",
            "there is no automatic retry, reconnect, cleanup promise, or generic verify phase",
        ),
    ),
    "ui.commands.execute": OperationSpec(
        "ui.commands.execute",
        UI_COMMAND_EXECUTE_URI,
        "authoring-ui-command",
        "Execute one installed Wwise Authoring UI command after a fresh live command-inventory check.",
        ("command",),
        ("objects", "platforms", "value", "files"),
        argument_contract=_object_contract(
            ("command",),
            {
                "command": {"type": "string", "minLength": 1, "maxLength": 512},
                "objects": {
                    "type": "array",
                    "maxItems": 64,
                    "items": {"type": "string", "maxLength": 1024},
                },
                "platforms": {
                    "type": "array",
                    "maxItems": 16,
                    "items": {"type": "string", "maxLength": 256},
                },
                "value": {
                    "description": "Optional finite JSON scalar forwarded as the command value.",
                },
                "files": {
                    "type": "array",
                    "maxItems": 64,
                    "items": {"type": "string", "absoluteRegularFile": True},
                    "supported_versions": ["2025.1"],
                },
            },
            optional=("objects", "platforms", "value", "files"),
        ),
        constraints=(
            "available only when live getInfo.isCommandLine is false",
            "the command ID must be present in a fresh getCommands result immediately before dispatch",
            "files is available only in Wwise 2025.1 and every file identity/content proof is replayed before dispatch",
            "generic command effects have no business-state readback and are never retried automatically",
        ),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user explicitly asks to execute an installed Wwise UI command or perform GUI command automation.",
                "No dedicated semantic operation owns the requested business outcome.",
            ),
            avoid_when=(
                "A dedicated operation can express and verify the requested project change.",
                "The command is being chosen only as a shortcut around a closed semantic boundary.",
            ),
            choose_instead=(
                (
                    "the matching dedicated operation",
                    "the request names a supported import, object, SoundBank, Switch Container, debug, Lua, or capture outcome",
                ),
            ),
        ),
    ),
    "ui.commands.register": OperationSpec(
        "ui.commands.register",
        UI_COMMAND_REGISTER_URI,
        "authoring-ui-command",
        "Register bounded Wwise Authoring UI commands from closed descriptors and verify their IDs appear.",
        ("commands",),
        ("source_authority",),
        argument_contract={
            **_object_contract(
                ("commands",),
                {
                    "commands": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": UI_COMMAND_MAX_COMMANDS,
                        "caseInsensitiveUniqueBy": "$.id",
                        "items": _ui_command_descriptor_contract(),
                    },
                    "source_authority": {
                        "const": UI_COMMAND_SOURCE_AUTHORITY,
                        "description": (
                            "Required only for exact existing program or Lua paths supplied "
                            "verbatim by the user."
                        ),
                    },
                },
                optional=("source_authority",),
            ),
            "allOf": [_ui_command_source_authority_condition()],
        },
        constraints=(
            "available only when live getInfo.isCommandLine is false",
            "host platform is derived only from live getInfo.platform; callers cannot supply it",
            "x64 and win32 map to Windows, macosx maps to macOS, and every other platform fails closed",
            "all command IDs must be absent immediately before dispatch and present after dispatch",
            "external program/Lua paths are immutable proven local paths; the Skill never authors source code",
            "generic Program descriptors name one final proved executable and require empty argument_tokens",
        ),
    ),
    "ui.commands.unregister": OperationSpec(
        "ui.commands.unregister",
        UI_COMMAND_UNREGISTER_URI,
        "authoring-ui-command",
        "Unregister command IDs from closed descriptor evidence or an explicitly acknowledged ID list; both standalone forms have unknown ownership and no inferred inverse.",
        (),
        ("commands", "source_authority", "command_ids", "acknowledgement"),
        argument_contract={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "commands": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": UI_COMMAND_MAX_COMMANDS,
                    "caseInsensitiveUniqueBy": "$.id",
                    "items": _ui_command_descriptor_contract(),
                },
                "source_authority": {"const": UI_COMMAND_SOURCE_AUTHORITY},
                "command_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": UI_COMMAND_MAX_COMMANDS,
                    "uniqueItems": True,
                    "caseInsensitiveUniqueItems": True,
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": UI_COMMAND_MAX_ID_CHARS,
                    },
                },
                "acknowledgement": {
                    "const": UNREGISTER_EXISTING_ACKNOWLEDGEMENT,
                },
            },
            "oneOf": [
                {
                    "required": ["commands"],
                    "forbidden": ["command_ids", "acknowledgement"],
                },
                {
                    "required": ["command_ids", "acknowledgement"],
                    "forbidden": ["commands", "source_authority"],
                },
            ],
            "allOf": [_ui_command_source_authority_condition()],
        },
        constraints=(
            "available only when live getInfo.isCommandLine is false",
            "descriptor-backed mode uses a live-derived host platform and sealed definitions only to derive the requested IDs; it proves neither ownership nor a matching live definition",
            "existing-ID mode requires an exact irreversibility acknowledgement because getCommands exposes no definitions or ownership",
            "all command IDs must be present immediately before dispatch and absent after dispatch",
            "neither standalone mode carries inverse registration cleanup; reversible cleanup is bound to a previously successful register transaction",
        ),
    ),
    "ui.captureScreen": OperationSpec(
        "ui.captureScreen",
        "ak.wwise.ui.captureScreen",
        "ui",
        "Capture the whole Wwise UI or one named view through a stable five-version request.",
        (),
        ("view_name", "view_channel", "rect"),
        argument_contract=_object_contract(
            (),
            {
                "view_name": {"type": "string", "minLength": 1},
                "view_channel": {"type": "integer", "minimum": 1, "maximum": 4},
                "rect": _object_contract(
                    ("x", "y", "width", "height"),
                    {
                        "x": {"type": "integer", "minimum": 0},
                        "y": {"type": "integer", "minimum": 0},
                        "width": {"type": "integer", "minimum": 1},
                        "height": {"type": "integer", "minimum": 1},
                    },
                ),
            },
            optional=("view_name", "view_channel", "rect"),
        ),
        constraints=(
            "view_channel maps to viewSyncGroup in 2021.1 and viewSelectionChannel in 2022.1-2025.1",
            "rect is always a complete x/y/width/height object even though 2021.1 reflection did not mark its members required",
            "the returned image must have a declared image content type and valid bounded base64",
        ),
        selection_guidance=_selection_guidance(
            use_when=("The requested outcome is a Wwise UI or named-view image.",),
            avoid_when=("A generic UI command is being used to approximate the same screenshot outcome.",),
            preferred_over=(
                ("ui.commands.execute", "the requested business result is a screenshot"),
            ),
        ),
    ),
    "object.copy": OperationSpec(
        "object.copy",
        "ak.wwise.core.object.copy",
        "object-mutation",
        "Copy one object under one parent.",
        ("object", "parent"),
        ("on_name_conflict", "auto_add_to_source_control", "auto_check_out_to_source_control"),
        argument_contract=_object_contract(
            ("object", "parent"),
            {
                "object": IDENTITY_ARGUMENT_SCHEMA,
                "parent": IDENTITY_ARGUMENT_SCHEMA,
                "on_name_conflict": {"type": "string", "enum": ["fail", "rename"]},
                "auto_add_to_source_control": _COPY_AUTO_ADD_SCHEMA,
                "auto_check_out_to_source_control": _OBJECT_MUTATION_AUTO_CHECK_OUT_SCHEMA,
            },
            optional=("on_name_conflict", "auto_add_to_source_control", "auto_check_out_to_source_control"),
        ),
        identity_arguments=("object", "parent"),
        constraints=("the returned copy GUID is captured and verified under the requested parent",),
    ),
    "object.move": OperationSpec(
        "object.move",
        "ak.wwise.core.object.move",
        "object-mutation",
        "Move one object under one parent.",
        ("object", "parent"),
        ("on_name_conflict", "auto_check_out_to_source_control"),
        argument_contract=_object_contract(
            ("object", "parent"),
            {
                "object": IDENTITY_ARGUMENT_SCHEMA,
                "parent": IDENTITY_ARGUMENT_SCHEMA,
                "on_name_conflict": {"type": "string", "enum": ["fail", "rename"]},
                "auto_check_out_to_source_control": _OBJECT_MUTATION_AUTO_CHECK_OUT_SCHEMA,
            },
            optional=("on_name_conflict", "auto_check_out_to_source_control"),
        ),
        identity_arguments=("object", "parent"),
        constraints=("the source GUID is preserved and its new parent/path are verified",),
    ),
    "soundbank.setInclusions": OperationSpec(
        "soundbank.setInclusions",
        "ak.wwise.core.soundbank.setInclusions",
        "soundbank",
        "Add, remove, or replace normalized SoundBank inclusions against a live pre-state snapshot.",
        ("soundbank", "mode", "inclusions"),
        argument_contract=_object_contract(
            ("soundbank", "mode", "inclusions"),
            {
                "soundbank": IDENTITY_ARGUMENT_SCHEMA,
                "mode": {"type": "string", "enum": ["add", "remove", "replace"]},
                "inclusions": {
                    "type": "array",
                    "maxItems": 128,
                    "empty_allowed_when": {"mode": "replace"},
                    "items": _object_contract(
                        ("object", "filters"),
                        {
                            "object": IDENTITY_ARGUMENT_SCHEMA,
                            "filters": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"type": "string", "enum": ["events", "structures", "media"]},
                            },
                        },
                    ),
                },
            },
        ),
        identity_arguments=("soundbank", "inclusions[].object"),
        constraints=(
            "replace is one transaction scoped only to the selected SoundBank: "
            "submit its complete desired post-state; omitted existing rows are "
            "removed without naming them, every other SoundBank is unaffected, "
            "and the list may be empty",
            "add upserts the complete filter row for each requested object while preserving other objects",
            "remove requires an exact live filter-row match and removes the requested object inclusion",
        ),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user directly describes additions, removals, replacement, or clearing of one live SoundBank's inclusion rows.",
                "The user gives one SoundBank's complete desired final inclusion "
                "set and asks to remove Debug or any other omitted rows; use one "
                "replace transaction and never split that final-state request "
                "into add and remove transactions.",
            ),
            avoid_when=(
                "The user supplies SoundBank Definition TSV files and asks Wwise to process those files.",
                "The Agent would need to invent a Definition TSV only to encode direct inclusion parameters.",
            ),
            preferred_over=(
                (
                    "soundbank.processDefinitionFiles",
                    "the inclusion changes are expressed directly rather than through caller-owned Definition files",
                ),
            ),
            choose_instead=(
                (
                    "soundbank.processDefinitionFiles",
                    "existing caller-owned Definition TSV files are the requested source of truth",
                ),
            ),
        ),
    ),
    "soundbank.generate": OperationSpec(
        "soundbank.generate",
        "ak.wwise.core.soundbank.generate",
        "soundbank",
        "Generate an explicit bounded SoundBank/platform/language scope and verify requested non-empty artifacts inside one isolated I/O root.",
        ("soundbanks", "platforms", "skip_languages", "write_to_disk", "io_root"),
        (
            "languages",
            "rebuild_soundbanks",
            "clear_audio_file_cache",
            "rebuild_init_bank",
        ),
        argument_contract=_object_contract(
            ("soundbanks", "platforms", "skip_languages", "write_to_disk", "io_root"),
            {
                "soundbanks": {"type": "array", "minItems": 1, "maxItems": 64, "items": _SOUNDBANK_GENERATE_ITEM_SCHEMA},
                "platforms": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "string", "minLength": 1}},
                "languages": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": {"type": "string", "minLength": 1},
                    "description": (
                        "Batch language selection. Omit when every SoundBank has "
                        "artifact_expectation=nonlocalized. When any SoundBank is "
                        "localized or mixed, supply one or more real localized "
                        "project language names; SFX is not a localized language "
                        "and is forbidden here."
                    ),
                },
                "skip_languages": {
                    "type": "boolean",
                    "x-discloseDescription": True,
                    "description": (
                        "Batch switch derived from the complete soundbanks[] list: "
                        "true exactly when every SoundBank is nonlocalized, and "
                        "false when any SoundBank is localized or mixed."
                    ),
                },
                "write_to_disk": {"const": True},
                "rebuild_soundbanks": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Batch-level native rebuildSoundBanks control. It is "
                        "independent from soundbanks[].rebuild and never "
                        "substitutes for an explicitly supplied per-Bank value."
                    ),
                },
                "clear_audio_file_cache": {
                    "type": "boolean",
                    "default": False,
                },
                "rebuild_init_bank": {
                    "type": "boolean",
                    "default": False,
                },
                "io_root": {"type": "string", "minLength": 1},
            },
            optional=(
                "languages",
                "rebuild_soundbanks",
                "clear_audio_file_cache",
                "rebuild_init_bank",
            ),
        ),
        identity_arguments=("soundbanks[].events[]", "soundbanks[].aux_busses[]"),
        constraints=(
            "the user SoundBank, platform, and language scope is explicit; Init is an automatic by-product and cannot be requested",
            "language selection is batch-wide: all-nonlocalized soundbanks require skip_languages=true and languages omitted; any localized or mixed soundbank requires skip_languages=false plus non-empty live project languages, never SFX; one batch may combine nonlocalized with localized or mixed rows",
            "batch-level rebuild_soundbanks and per-Bank soundbanks[].rebuild are independent; preserve every explicitly supplied value at its original level",
            "Event and AuxBus descriptors resolve live to one GUID before preview",
            "Wwise 2021.1 derives project paths from the live Project filePath plus a hashed strict WPROJ parse; later versions use live core.getProjectInfo",
            "execution replays project/file/artifact guards; verification requires each requested Bank artifact to be created or changed and non-empty",
        ),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user wants to generate SoundBanks in the already connected Authoring project.",
                "Event or AuxBus descriptors are generation-only inputs for the requested artifact run.",
            ),
            avoid_when=(
                "The user explicitly requests WwiseConsole, CLI, or command-line generation.",
                "The user only asks to wait for or stream SoundBank generation notifications.",
                "The user asks to persistently change the SoundBank's saved inclusion rows.",
            ),
            choose_instead=(
                ("waapi.call", "explicit CLI generation intent selects the versioned ak.wwise.cli.generateSoundbank route"),
                ("wait-topic or stream-topic", "the request is observation-only"),
                ("soundbank.setInclusions", "the requested outcome is a persistent inclusion edit"),
            ),
        ),
    ),
    "soundbank.convertExternalSources": OperationSpec(
        "soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.convertExternalSources",
        "soundbank",
        "Convert strict proven .wsources inputs into exact non-empty WEM artifacts under isolated per-platform output roots.",
        ("sources", "io_root"),
        argument_contract=_object_contract(
            ("sources", "io_root"),
            {
                "sources": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 32,
                    "items": _object_contract(
                        ("input", "platform", "output"),
                        {
                            "input": {"type": "string", "absoluteRegularFile": True},
                            "platform": {"type": "string", "minLength": 1},
                            "output": {"type": "string", "minLength": 1},
                        },
                    ),
                },
                "io_root": {"type": "string", "minLength": 1},
            },
        ),
        constraints=(
            "every .wsources document and WAV source is parsed and hashed before preview",
            "different platforms cannot share an output root and every derived .wem remains inside io_root",
            "execution rejects input, project, or output-tree drift; verification requires every exact WEM output and rejects partial success",
        ),
        supported_versions=("2022.1", "2023.1", "2024.1", "2025.1"),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user wants the connected Authoring project to convert existing .wsources manifests.",
            ),
            avoid_when=("The user explicitly requests WwiseConsole or CLI conversion.",),
            choose_instead=(
                ("waapi.call", "explicit CLI intent selects the versioned ak.wwise.cli.convertExternalSource route"),
            ),
        ),
    ),
    "soundbank.processDefinitionFiles": OperationSpec(
        "soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "soundbank",
        "Process strict proven SoundBank Definition TSV files after resolving every derived object, then verify exact SoundBank GUID/inclusion state.",
        ("files", "io_root"),
        argument_contract=_object_contract(
            ("files", "io_root"),
            {
                "files": {"type": "array", "minItems": 1, "maxItems": 32, "items": {"type": "string", "absoluteRegularFile": True}},
                "io_root": {"type": "string", "minLength": 1},
            },
        ),
        constraints=(
            "SoundBank names and inclusion rows are derived only from hashed UTF-8 tab-delimited files",
            "unsupported directives, duplicate rows, unknown objects, and ambiguous names fail before dispatch",
            "execution replays file/project and SoundBank inclusion snapshots; verification checks exact target inclusions and one unrelated control Bank",
        ),
        supported_versions=("2022.1", "2023.1", "2024.1", "2025.1"),
        selection_guidance=_selection_guidance(
            use_when=(
                "The user supplies existing SoundBank Definition TSV files and asks connected Authoring to process them.",
            ),
            avoid_when=(
                "The user directly describes inclusion rows and the Agent would need to invent a TSV.",
            ),
            choose_instead=(
                ("soundbank.setInclusions", "the requested inclusion changes are expressed directly"),
                ("waapi.call", "explicit WwiseConsole or CLI Definition-file processing intent selects the versioned CLI route"),
            ),
        ),
    ),
    "switchContainer.addAssignment": OperationSpec(
        "switchContainer.addAssignment",
        "ak.wwise.core.switchContainer.addAssignment",
        "switchcontainer",
        "Add one validated child/state-or-switch assignment and verify the exact pair appears.",
        ("switch_container", "child", "state_or_switch"),
        argument_contract=_object_contract(
            ("switch_container", "child", "state_or_switch"),
            {
                "switch_container": IDENTITY_ARGUMENT_SCHEMA,
                "child": IDENTITY_ARGUMENT_SCHEMA,
                "state_or_switch": IDENTITY_ARGUMENT_SCHEMA,
            },
        ),
        identity_arguments=("switch_container", "child", "state_or_switch"),
        constraints=(
            "switch_container must be a SwitchContainer",
            "child must be a direct child of switch_container",
            "state_or_switch must be a direct child of the group referenced by SwitchGroupOrStateGroup",
            "the closed add policy rejects a child that already has any assignment",
        ),
        selection_guidance=_selection_guidance(
            use_when=("The user asks to add one Switch Container child assignment.",),
            avoid_when=("The Agent would otherwise express the assignment as a generic object list/reference edit.",),
            preferred_over=(
                ("object.set", "the requested outcome is a Switch Container assignment"),
                ("object.setReference", "the requested outcome is a Switch Container assignment"),
            ),
        ),
    ),
    "switchContainer.removeAssignment": OperationSpec(
        "switchContainer.removeAssignment",
        "ak.wwise.core.switchContainer.removeAssignment",
        "switchcontainer",
        "Remove one validated child/state-or-switch assignment and verify the exact pair disappears.",
        ("switch_container", "child", "state_or_switch"),
        argument_contract=_object_contract(
            ("switch_container", "child", "state_or_switch"),
            {
                "switch_container": _SWITCH_REMOVE_CONTAINER_IDENTITY_SCHEMA,
                "child": _SWITCH_REMOVE_CHILD_IDENTITY_SCHEMA,
                "state_or_switch": _SWITCH_REMOVE_VALUE_IDENTITY_SCHEMA,
            },
        ),
        identity_arguments=("switch_container", "child", "state_or_switch"),
        constraints=(
            "switch_container must be a SwitchContainer",
            "child must be a direct child of switch_container",
            "state_or_switch must be a direct child of the group referenced by SwitchGroupOrStateGroup",
            "the exact child and state_or_switch pair must already exist",
            "an exact child name plus a closed parent requires scoped-name; direct-child is only for one unnamed exactly-one child by type",
            "an exact Switch or State value name plus its closed group parent requires scoped-name",
        ),
        selection_guidance=_selection_guidance(
            use_when=("The user asks to remove one existing Switch Container child assignment.",),
            avoid_when=("The Agent would otherwise express the removal as a generic object list/reference edit.",),
            preferred_over=(
                ("object.set", "the requested outcome is removal of a Switch Container assignment"),
                ("object.setReference", "the requested outcome is removal of a Switch Container assignment"),
            ),
        ),
    ),
}


_OPERATION_INPUT_MODE_DECLARATIONS: tuple[
    tuple[str, tuple[str, ...], str], ...
] = (
    ("audio.import", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("audio.importTabDelimited", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), INLINE_TYPED_INPUT_MODE),
    ("debug.restartWaapiServers", ("2023.1", "2024.1", "2025.1"), INLINE_TYPED_INPUT_MODE),
    ("debug.setAsserts", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), INLINE_TYPED_INPUT_MODE),
    ("debug.setAutomationMode", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), INLINE_TYPED_INPUT_MODE),
    ("debug.testAssert", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), INLINE_TYPED_INPUT_MODE),
    ("debug.testCrash", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), INLINE_TYPED_INPUT_MODE),
    ("lua.executeCliFile", ("2023.1", "2024.1", "2025.1"), COMPOSER_INPUT_MODE),
    ("lua.executeCoreFile", ("2023.1", "2024.1", "2025.1"), COMPOSER_INPUT_MODE),
    ("lua.executeCoreInline", ("2025.1",), COMPOSER_INPUT_MODE),
    ("object.copy", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("object.create", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("object.createPlugin", ("2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("object.delete", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("object.move", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("object.set", ("2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("object.setLinked", ("2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("object.setName", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("object.setNotes", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("object.setProperty", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("object.setRTPC", ("2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("object.setReference", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("soundbank.convertExternalSources", ("2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("soundbank.generate", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("soundbank.processDefinitionFiles", ("2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("soundbank.setInclusions", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("switchContainer.addAssignment", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("switchContainer.removeAssignment", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), BUSINESS_DECLARATION_INPUT_MODE),
    ("ui.captureScreen", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), INLINE_TYPED_INPUT_MODE),
    ("ui.commands.execute", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), INLINE_TYPED_INPUT_MODE),
    ("ui.commands.register", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), COMPOSER_INPUT_MODE),
    ("ui.commands.unregister", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), COMPOSER_INPUT_MODE),
    ("waapi.call", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), INTERNAL_CANONICAL_INPUT_MODE),
    ("waapi.undoGroup", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), COMPOSER_INPUT_MODE),
)

OPERATION_INPUT_MODE_LANES: tuple[OperationInputModeLane, ...] = tuple(
    OperationInputModeLane(
        operation=operation,
        version=version,
        input_mode=input_mode,
    )
    for operation, versions, input_mode in _OPERATION_INPUT_MODE_DECLARATIONS
    for version in versions
)


def validate_operation_input_mode_lanes(
    lanes: Sequence[OperationInputModeLane],
) -> None:
    """Require exactly one reviewed normal input mode for every Registry lane."""

    expected = {
        (spec.name, version)
        for spec in OPERATION_SPECS.values()
        for version in spec.supported_versions
    }
    observed: set[tuple[str, str]] = set()
    for lane in lanes:
        if not isinstance(lane, OperationInputModeLane):
            raise OperationContractError(
                "INVALID_INPUT_MODE_REGISTRY",
                "operation input mode lanes must use OperationInputModeLane records.",
            )
        spec = OPERATION_SPECS.get(lane.operation)
        if spec is None:
            raise OperationContractError(
                "INVALID_INPUT_MODE_REGISTRY",
                f"operation input mode lane names unknown operation {lane.operation!r}.",
            )
        if lane.version not in spec.supported_versions:
            raise OperationContractError(
                "INVALID_INPUT_MODE_REGISTRY",
                "operation input mode registry contains an unsupported version lane: "
                f"{lane.operation!r} {lane.version!r}.",
            )
        if lane.input_mode not in SUPPORTED_OPERATION_INPUT_MODES:
            raise OperationContractError(
                "INVALID_INPUT_MODE_REGISTRY",
                f"operation input mode registry contains unknown input mode {lane.input_mode!r}.",
            )
        key = (lane.operation, lane.version)
        if key in observed:
            raise OperationContractError(
                "INVALID_INPUT_MODE_REGISTRY",
                "operation input mode registry contains a duplicate lane: "
                f"{lane.operation!r} {lane.version!r}.",
            )
        observed.add(key)
    missing = sorted(expected - observed)
    if missing:
        raise OperationContractError(
            "INVALID_INPUT_MODE_REGISTRY",
            "operation input mode registry has missing supported lanes.",
            details={"missing": [list(item) for item in missing]},
        )


def _operation_input_mode_index(
    lanes: Sequence[OperationInputModeLane],
) -> dict[tuple[str, str], str]:
    validate_operation_input_mode_lanes(lanes)
    return {
        (lane.operation, lane.version): lane.input_mode
        for lane in lanes
    }


def operation_input_mode(name: str, version: str) -> str:
    """Return the sole normal input mode for one exact operation/version key."""

    spec = describe_operation(name)
    if version not in spec.supported_versions:
        raise OperationContractError(
            "UNAVAILABLE_IN_VERSION",
            f"{name} is not reflected for Wwise {version}.",
            details={
                "operation": name,
                "version": version,
                "supported_versions": list(spec.supported_versions),
            },
        )
    return _operation_input_mode_index(OPERATION_INPUT_MODE_LANES)[(name, version)]


def operation_uses_business_declaration(name: str, version: str) -> bool:
    """Return false for native URI Drafts outside the named-operation Registry."""

    spec = OPERATION_SPECS.get(name)
    if spec is None or version not in spec.supported_versions:
        return False
    uses_business_declaration = (
        operation_input_mode(name, version) == BUSINESS_DECLARATION_INPUT_MODE
    )
    if uses_business_declaration:
        try:
            business_adapter(name)
        except KeyError as exc:  # pragma: no cover - Registry validation invariant
            raise OperationContractError(
                "BUSINESS_ADAPTER_UNAVAILABLE",
                f"{name} has no reviewed Business Declaration Adapter.",
            ) from exc
    return uses_business_declaration


def audio_import_business_contract(version: str) -> dict[str, Any]:
    """Publish Registry-owned audio.import business shape and safety metadata."""

    if operation_input_mode("audio.import", version) != BUSINESS_DECLARATION_INPUT_MODE:
        raise OperationContractError(
            "OPERATION_INPUT_MODE_INVALID",
            "audio.import does not expose the business declaration input mode.",
        )
    return business_adapter("audio.import").contract(version)


def operation_business_contract(name: str, version: str) -> dict[str, Any]:
    """Publish the Adapter-owned business contract for one exact lane."""

    if operation_input_mode(name, version) != BUSINESS_DECLARATION_INPUT_MODE:
        raise OperationContractError(
            "OPERATION_INPUT_MODE_INVALID",
            f"{name} does not expose the business declaration input mode.",
        )
    try:
        return business_adapter(name).contract(version)
    except KeyError as exc:  # pragma: no cover - input-mode Registry invariant
        raise OperationContractError(
            "BUSINESS_ADAPTER_UNAVAILABLE",
            f"{name} has no reviewed Business Declaration Adapter.",
        ) from exc


def operation_input_modes_by_version(name: str) -> dict[str, str]:
    """Project one operation's unique normal lane for every supported version."""

    spec = describe_operation(name)
    index = _operation_input_mode_index(OPERATION_INPUT_MODE_LANES)
    return {
        version: index[(name, version)]
        for version in spec.supported_versions
    }


validate_operation_input_mode_lanes(OPERATION_INPUT_MODE_LANES)


def list_operation_specs() -> tuple[OperationSpec, ...]:
    return tuple(OPERATION_SPECS[name] for name in sorted(OPERATION_SPECS))


def describe_operation(name: str) -> OperationSpec:
    try:
        return OPERATION_SPECS[name]
    except KeyError as exc:
        raise OperationContractError(
            "UNKNOWN_OPERATION",
            f"Unknown closed operation {name!r}.",
            details={"operation": name, "supported": sorted(OPERATION_SPECS)},
        ) from exc


def operation_request_machine_contract(name: str, version: str) -> dict[str, Any]:
    """Return the versioned machine contract that governs request validity.

    Human summaries and routing guidance are deliberately excluded: editing
    prose must not invalidate an otherwise unchanged Operation Draft.  Fields
    that affect accepted request values, identities, file policy, or Preview
    ownership remain bound into the contract.
    """

    spec = describe_operation(name)
    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise OperationContractError(
            "UNSUPPORTED_VERSION",
            f"Unsupported Wwise version {version!r}.",
            details={"supported_versions": list(SUPPORTED_WWISE_VERSION_KEYS)},
        )
    if version not in spec.supported_versions:
        raise OperationContractError(
            "UNAVAILABLE_IN_VERSION",
            f"{name} is not reflected for Wwise {version}.",
            details={
                "operation": name,
                "version": version,
                "supported_versions": list(spec.supported_versions),
            },
        )
    if not spec.implemented:
        raise OperationContractError(
            "OPERATION_BOUNDARY",
            f"{name} does not yet have a closed executable verifier.",
            details={"operation": name, "boundary": spec.boundary},
        )
    return {
        "additional_properties": False,
        "argument_contract": _operation_argument_contract(
            spec.name,
            spec.argument_contract,
            version=version,
        ),
        "constraints": list(spec.constraints),
        "contract": "waapi-skill.operation-request-schema/v1",
        "file_read_policy": spec.file_read_policy,
        "identity_arguments": list(spec.identity_arguments),
        "operation": spec.name,
        "optional_arguments": list(spec.optional_arguments),
        "parent_child_contract": {
            parent_type: sorted(child_types)
            for parent_type, child_types in sorted(spec.parent_child_contract.items())
        },
        "preview_owns": list(spec.preview_owns),
        "request_contract": OPERATION_REQUEST_CONTRACT,
        "required_arguments": list(spec.required_arguments),
        "version": version,
    }


def operation_request_schema_digest(name: str, version: str) -> str:
    """Bind one Draft to the exact Registry-owned request machine contract."""

    return canonical_sha256(operation_request_machine_contract(name, version))



def validate_operation_identity_fragment(
    operation: str,
    version: str,
    *,
    role: str,
    payload: Any,
) -> dict[str, Any]:
    """Validate one typed identity through an exact Registry operation lane."""

    machine = operation_request_machine_contract(operation, version)
    if role not in machine["identity_arguments"]:
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role!r} is not an identity argument for {operation!r}.",
        )
    try:
        descriptors = normalize_reference_descriptors(
            [{"name": role, "target": payload}],
            request_path=f"$.arguments.{role}",
        )
    except ObjectOperationContractError as exc:
        raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
    if len(descriptors) != 1:  # pragma: no cover - normalizer invariant
        raise RuntimeError("one operation identity fragment did not normalize once")
    return descriptors[0].target.as_dict()




def parse_operation_request(payload: Mapping[str, Any], *, expected_version: str | None = None) -> OperationRequest:
    if not isinstance(payload, Mapping):
        raise OperationContractError("INVALID_REQUEST", "Operation request must be a JSON object.")
    _require_exact_keys(payload, required=("contract", "version", "operation", "arguments"), context="request")
    if payload.get("contract") != OPERATION_REQUEST_CONTRACT:
        raise OperationContractError(
            "INVALID_CONTRACT",
            f"contract must be {OPERATION_REQUEST_CONTRACT!r}.",
            details={"actual": payload.get("contract")},
        )
    version = payload.get("version")
    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise OperationContractError(
            "UNSUPPORTED_VERSION",
            f"Unsupported Wwise version {version!r}.",
            details={"supported_versions": list(SUPPORTED_WWISE_VERSION_KEYS)},
        )
    if expected_version is not None and version != expected_version:
        raise OperationContractError(
            "VERSION_MISMATCH",
            f"Operation request is for {version}, but live Wwise is {expected_version}.",
            details={"request_version": version, "live_version": expected_version},
        )
    operation = payload.get("operation")
    if not isinstance(operation, str):
        raise OperationContractError("INVALID_REQUEST", "operation must be a string.")
    spec = describe_operation(operation)
    if version not in spec.supported_versions:
        raise OperationContractError(
            "UNAVAILABLE_IN_VERSION",
            f"{operation} is not reflected for Wwise {version}.",
            details={"operation": operation, "version": version, "supported_versions": list(spec.supported_versions)},
        )
    if not spec.implemented:
        raise OperationContractError(
            "OPERATION_BOUNDARY",
            f"{operation} does not yet have a closed executable verifier.",
            details={"operation": operation, "boundary": spec.boundary},
        )
    arguments = payload.get("arguments")
    if not isinstance(arguments, Mapping):
        raise OperationContractError("INVALID_REQUEST", "arguments must be a JSON object.")
    _require_exact_keys(arguments, required=spec.required_arguments, optional=spec.optional_arguments, context=operation)
    _validate_nested_request_shape(operation, arguments, version=str(version))
    if operation == "waapi.call":
        _public_call_arguments(str(version), arguments)
    elif operation == "waapi.undoGroup":
        build_undo_group_execution_plan(str(version), arguments)
    return OperationRequest(OPERATION_REQUEST_CONTRACT, str(version), operation, dict(arguments))


def build_undo_group_execution_plan(
    version: str,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the exact immutable same-connection Undo Group call plan."""

    display_name = arguments.get("display_name")
    try:
        request_size = len(canonical_json_bytes(dict(arguments)))
    except (TypeError, ValueError) as exc:
        raise OperationContractError(
            "INVALID_ARGUMENT",
            "waapi.undoGroup arguments must be a strict JSON document.",
        ) from exc
    if request_size > UNDO_GROUP_MAX_REQUEST_BYTES:
        raise OperationContractError(
            "UNDO_GROUP_REQUEST_TOO_LARGE",
            "waapi.undoGroup arguments exceed the packaged compound-request byte limit.",
            details={"size_bytes": request_size, "limit_bytes": UNDO_GROUP_MAX_REQUEST_BYTES},
        )
    if not isinstance(display_name, str) or not display_name.strip():
        raise OperationContractError(
            "INVALID_ARGUMENT",
            "waapi.undoGroup display_name must be a non-empty string.",
        )
    if len(display_name) > UNDO_GROUP_MAX_DISPLAY_NAME_LENGTH:
        raise OperationContractError(
            "INVALID_ARGUMENT",
            f"waapi.undoGroup display_name must be at most {UNDO_GROUP_MAX_DISPLAY_NAME_LENGTH} characters.",
            details={"length": len(display_name)},
        )
    raw_calls = arguments.get("calls")
    if not isinstance(raw_calls, list) or not 1 <= len(raw_calls) <= UNDO_GROUP_MAX_CALLS:
        raise OperationContractError(
            "INVALID_ARGUMENT",
            f"waapi.undoGroup calls must contain between 1 and {UNDO_GROUP_MAX_CALLS} items.",
            details={"count": len(raw_calls) if isinstance(raw_calls, list) else None},
        )
    allowed = UNDO_GROUP_INNER_URIS_BY_VERSION.get(version)
    if allowed is None:
        raise OperationContractError(
            "UNSUPPORTED_VERSION",
            f"Unsupported Wwise version {version!r}.",
        )
    registry = ExecutionContractRegistry()
    calls: list[dict[str, Any]] = []
    for index, raw_child_binding in enumerate(raw_calls):
        if not isinstance(raw_child_binding, Mapping):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                f"waapi.undoGroup calls[{index}] must be a JSON object.",
            )
        _require_exact_keys(
            raw_child_binding,
            required=("schema_digest", "request"),
            context=f"waapi.undoGroup calls[{index}]",
        )
        child_payload = raw_child_binding.get("request")
        if not isinstance(child_payload, Mapping):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                f"waapi.undoGroup calls[{index}].request must be an object.",
            )
        child = parse_operation_request(child_payload, expected_version=version)
        if child.operation == "waapi.undoGroup":
            raise OperationContractError(
                "UNDO_GROUP_INNER_NOT_ALLOWED",
                "Nested Undo Group child calls are not allowed.",
                details={"index": index},
            )
        if child.operation == "waapi.call":
            api_value = child.arguments.get("api")
            if not isinstance(api_value, str):
                raise OperationContractError(
                    "INVALID_ARGUMENT", "Undo Group waapi.call child lacks its API."
                )
            from .typed_requests import request_contract

            expected_child_schema_digest = request_contract(
                version, api_value
            ).schema_digest
            api, args, options, _execution_contract = _public_call_arguments(
                version, child.arguments
            )
            validation = validate_semantic_payload(
                api, args, options, version=version
            )
        else:
            child_spec = describe_operation(child.operation)
            api = child_spec.uri
            from .typed_operations import compound_child_request_contract

            expected_child_schema_digest = compound_child_request_contract(
                child.operation, version
            ).schema_digest
            # Dedicated children retain their closed semantic arguments here;
            # live preparation below resolves them to the exact native call.
            args = {}
            options = {}
        if raw_child_binding.get("schema_digest") != expected_child_schema_digest:
            raise OperationContractError(
                "UNDO_GROUP_CHILD_SCHEMA_MISMATCH",
                "Undo Group child schema digest is stale or belongs to another contract.",
                details={"index": index, "operation": child.operation},
            )
        if not isinstance(api, str) or api not in allowed:
            raise OperationContractError(
                "UNDO_GROUP_INNER_NOT_ALLOWED",
                f"{api!r} is not an allowed waapi.undoGroup inner mutation for Wwise {version}.",
                details={
                    "index": index,
                    "api": api,
                    "version": version,
                    "allowed": sorted(allowed),
                },
            )
        contract = registry.describe(version, api)
        if contract.route != "transaction" or contract.effect != "project_mutation":
            raise OperationContractError(
                "UNDO_GROUP_INNER_ROUTE_MISMATCH",
                "Undo Group inner calls must remain ordinary packaged project-mutation transactions.",
                details={
                    "index": index,
                    "api": api,
                    "route": contract.route,
                    "effect": contract.effect,
                },
            )
        calls.append(
            {
                "child_operation": child.operation,
                "child_request": child.as_dict(),
                "child_schema_digest": expected_child_schema_digest,
                "api": api,
                "args": dict(args),
                "options": dict(options),
                "timeout_seconds": contract.timeout_seconds,
                "result_limit_bytes": contract.result_limit_bytes,
                **(
                    {
                        "request_validation": validation.as_dict(),
                        "request_validation_strength": (
                            "partial_reflected_schema"
                            if validation.unresolved_refs
                            else "complete_reflected_schema"
                        ),
                    }
                    if child.operation == "waapi.call"
                    else {"request_validation_strength": "dedicated_operation_preparation"}
                ),
            }
        )
    cancel_args = {} if version in {"2021.1", "2022.1"} else {"undo": True}
    def phase(uri: str, args: Mapping[str, Any]) -> dict[str, Any]:
        phase_contract = registry.describe(version, uri)
        return {
            "uri": uri,
            "args": dict(args),
            "options": {},
            "timeout_seconds": phase_contract.timeout_seconds,
            "result_limit_bytes": phase_contract.result_limit_bytes,
        }

    plan = {
        "kind": "same_connection_undo_group",
        "version": version,
        "begin": phase(UNDO_BEGIN_GROUP_URI, {}),
        "calls": calls,
        "end": phase(UNDO_END_GROUP_URI, {"displayName": display_name}),
        "cancel": phase(UNDO_CANCEL_GROUP_URI, cancel_args),
        "same_connection_required": True,
        "automatic_retry": False,
    }
    plan_size = len(canonical_json_bytes(plan))
    if plan_size > UNDO_GROUP_MAX_PLAN_BYTES:
        raise OperationContractError(
            "UNDO_GROUP_PLAN_TOO_LARGE",
            "waapi.undoGroup immutable execution plan exceeds the packaged byte limit.",
            details={"size_bytes": plan_size, "limit_bytes": UNDO_GROUP_MAX_PLAN_BYTES},
        )
    return plan


def _public_call_arguments(
    version: str,
    arguments: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    api = arguments.get("api")
    if not isinstance(api, str) or not api.startswith("ak."):
        raise OperationContractError("INVALID_ARGUMENT", "waapi.call api must be a reflected ak.* URI.")
    raw_args = arguments.get("args", {})
    raw_options = arguments.get("options", {})
    if not isinstance(raw_args, Mapping) or not isinstance(raw_options, Mapping):
        raise OperationContractError("INVALID_ARGUMENT", "waapi.call args and options must be JSON objects.")
    try:
        contract = ExecutionContractRegistry().describe(version, api)
    except ExecutionContractError as exc:
        raise OperationContractError(
            "UNAVAILABLE_IN_VERSION",
            str(exc),
            details={"api": api, "version": version},
        ) from exc
    if contract.route == "compound_transaction_member":
        raise OperationContractError(
            "UNDO_GROUP_COMPOSITE_REQUIRED",
            f"{api!r} is session-scoped and cannot execute as an independent waapi.call transaction; use waapi.undoGroup.",
            details={
                "api": api,
                "version": version,
                "required_operation": "waapi.undoGroup",
                "route": contract.route,
            },
        )
    dedicated_operations = sorted(
        spec.name
        for spec in OPERATION_SPECS.values()
        if spec.name not in {"waapi.call", "waapi.undoGroup"}
        and spec.implemented
        and spec.uri == api
        and version in spec.supported_versions
    )
    if dedicated_operations:
        raise OperationContractError(
            "DEDICATED_OPERATION_REQUIRED",
            f"{api!r} has a packaged dedicated operation and cannot be called through waapi.call.",
            details={
                "api": api,
                "version": version,
                "required_operations": dedicated_operations,
            },
        )
    allowed_routes = {"transaction", "managed_transaction", "isolated_transaction"}
    if contract.route not in allowed_routes:
        raise OperationContractError(
            "PUBLIC_ROUTE_MISMATCH",
            f"waapi.call transaction cannot execute {api!r} through route {contract.route!r}.",
            details={
                "api": api,
                "version": version,
                "route": contract.route,
                "gateway_commands": list(contract.gateway_commands),
            },
        )
    forbidden_fields = FORBIDDEN_MODEL_AUTHORED_COMMAND_FIELDS.get(api, frozenset())
    supplied_forbidden = tuple(sorted(field for field in forbidden_fields if field in raw_args))
    if supplied_forbidden:
        raise OperationContractError(
            "MODEL_AUTHORED_COMMAND_BLOCKED",
            "Packaged waapi.call does not accept custom command-line hooks.",
            details={"api": api, "fields": list(supplied_forbidden)},
        )
    validation = validate_semantic_payload(api, raw_args, raw_options, version=version)
    _enforce_versioned_public_call_boundaries(
        version=version,
        api=api,
        args=raw_args,
    )
    if api == TRANSPORT_DESTROY_URI and not _valid_transport_id(raw_args.get("transport")):
        raise OperationContractError(
            "INVALID_ARGUMENT",
            "ak.wwise.core.transport.destroy requires a non-zero uint32 transport ID.",
            details={"api": api, "transport": raw_args.get("transport")},
        )
    io_root = arguments.get("io_root")
    if io_root is not None and not isinstance(io_root, str):
        raise OperationContractError("INVALID_ARGUMENT", "waapi.call io_root must be an absolute path string.")
    io_audit: Mapping[str, Any] | None = None
    if contract.route == "isolated_transaction":
        try:
            io_audit = validate_isolated_io(
                version=version,
                uri=api,
                args=raw_args,
                options=raw_options,
                io_root=io_root,
            ).as_dict()
        except IOPolicyError as exc:
            raise OperationContractError(
                exc.error_code,
                str(exc),
                details={"io_policy": exc.as_dict()},
            ) from exc
    elif io_root is not None:
        raise OperationContractError(
            "IO_ROOT_NOT_APPLICABLE",
            "waapi.call io_root is accepted only for isolated_transaction routes.",
            details={"api": api, "version": version, "route": contract.route},
        )
    return api, dict(raw_args), dict(raw_options), {
        **contract.as_dict(),
        "request_validation": validation.as_dict(),
        "request_validation_strength": (
            "partial_reflected_schema"
            if validation.unresolved_refs
            else "complete_reflected_schema"
        ),
        "io_audit": dict(io_audit) if io_audit is not None else None,
    }


def _enforce_versioned_public_call_boundaries(
    *,
    version: str,
    api: str,
    args: Mapping[str, Any],
) -> None:
    """Reject reflected request shapes that are partial in a proven Wwise lane."""

    if version in {"2024.1", "2025.1"} and api == AUTHORING_AUDIO_CONVERT_URI:
        required_shape = "non-empty ordered array of non-empty strings"
        for field in ("objects", "platforms", "languages"):
            value = args.get(field)
            if not isinstance(value, list) or not value:
                raise OperationContractError(
                    "VERSION_BEHAVIOR_BOUNDARY",
                    f"Wwise {version} audio.convert {field} must be a {required_shape}.",
                    details={
                        "api": api,
                        "version": version,
                        "field": field,
                        "required_shape": required_shape,
                        "received_type": type(value).__name__,
                    },
                )
            invalid_index = next(
                (
                    index
                    for index, item in enumerate(value)
                    if not isinstance(item, str) or not item.strip()
                ),
                None,
            )
            if invalid_index is not None:
                raise OperationContractError(
                    "VERSION_BEHAVIOR_BOUNDARY",
                    f"Wwise {version} audio.convert {field} must be a {required_shape}.",
                    details={
                        "api": api,
                        "version": version,
                        "field": field,
                        "required_shape": required_shape,
                        "invalid_index": invalid_index,
                        "received_type": type(value[invalid_index]).__name__,
                    },
                )
        return

    if version != "2022.1" or api != CLI_CONVERT_EXTERNAL_SOURCE_URI:
        return

    source_files = args.get("source-file")
    if isinstance(source_files, list) and len(source_files) > 1:
        raise OperationContractError(
            "VERSION_BEHAVIOR_BOUNDARY",
            "Wwise 2022.1 convertExternalSource processes only the first "
            "source-file when several .wsources files are supplied; the "
            "packaged interface rejects that partial-success shape.",
            details={
                "api": api,
                "version": version,
                "field": "source-file",
                "supplied_count": len(source_files),
                "supported_shape": "one .wsources file per platform per transaction",
                "next_step": (
                    "Supply one caller-prepared union .wsources file or use "
                    "separately previewed transactions."
                ),
            },
        )

    source_by_platform = args.get("source-by-platform")
    if not isinstance(source_by_platform, list):
        return
    if len(source_by_platform) == 2 and all(
        isinstance(item, str) for item in source_by_platform
    ):
        pairs = (source_by_platform,)
    else:
        pairs = tuple(
            row
            for row in source_by_platform
            if isinstance(row, list)
            and len(row) == 2
            and all(isinstance(item, str) for item in row)
        )
    platforms = [str(row[0]).casefold() for row in pairs]
    duplicates = sorted(
        {
            platform
            for platform in platforms
            if platforms.count(platform) > 1
        }
    )
    if duplicates:
        raise OperationContractError(
            "VERSION_BEHAVIOR_BOUNDARY",
            "Wwise 2022.1 convertExternalSource processes only the last "
            "source-by-platform entry for a repeated platform; the packaged "
            "interface rejects that partial-success shape.",
            details={
                "api": api,
                "version": version,
                "field": "source-by-platform",
                "duplicate_platforms": duplicates,
                "supported_shape": "one .wsources file per platform per transaction",
                "next_step": (
                    "Supply one caller-prepared union .wsources file per "
                    "platform or use separately previewed transactions."
                ),
            },
        )


def _public_call_verification_plan(
    *,
    api: str,
    version: str,
    args: Mapping[str, Any],
    strategy: str,
) -> dict[str, Any]:
    common = {"uri": api, "version": version}
    if api in {REMOTE_CONNECT_URI, REMOTE_DISCONNECT_URI}:
        return {
            "kind": "remote-connection-state",
            **common,
            "strategy": "operation_specific_readback",
            "base_result_strategy": strategy,
            "expected_connected": api == REMOTE_CONNECT_URI,
        }
    if api == TRANSPORT_CREATE_URI:
        return {
            "kind": "transport-created",
            **common,
            "strategy": "operation_specific_readback",
            "base_result_strategy": strategy,
        }
    if api == TRANSPORT_DESTROY_URI:
        transport_id = args.get("transport")
        if not _valid_transport_id(transport_id):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                "ak.wwise.core.transport.destroy requires a non-zero uint32 transport ID.",
                details={"api": api, "transport": transport_id},
            )
        return {
            "kind": "transport-destroyed",
            **common,
            "strategy": "operation_specific_readback",
            "base_result_strategy": strategy,
            "transport_id": transport_id,
        }
    return {"kind": "result-schema", **common, "strategy": strategy}


def _closed_operation_preview(
    *,
    uri: str,
    args: Mapping[str, Any],
    options: Mapping[str, Any],
    version: str,
    family: str,
    metadata: Mapping[str, Any],
) -> SemanticPreview:
    """Build a reviewed registry-owned preview and validate its exact dispatch."""

    validation = validate_semantic_payload(uri, args, options, version=version)
    return SemanticPreview(
        envelope=SemanticEnvelope(
            uri=uri,
            args=dict(args),
            options=dict(options),
            metadata={
                "schema_validation": validation.as_dict(),
                "request_validation_strength": (
                    "partial_reflected_schema"
                    if validation.unresolved_refs
                    else "complete_reflected_schema"
                ),
                "model_authored_code": False,
                **dict(metadata),
            },
        ),
        source_note_family=family,
        version=version,
        requires_destructive_gate=True,
        raw_dispatch_allowed=False,
    )


def _prepare_object_create(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    requested_conflict = arguments.get("on_name_conflict", "fail")
    platform = (
        _non_empty_string(arguments.get("platform"), field="platform")
        if "platform" in arguments
        else None
    )
    list_name = (
        normalize_object_list_name(
            arguments.get("list"),
            request_path="$.arguments.list",
        )
        if "list" in arguments
        else None
    )
    auto_add_to_source_control = arguments.get(
        "auto_add_to_source_control",
        False,
    )
    if not isinstance(auto_add_to_source_control, bool):
        raise OperationContractError(
            "INVALID_ARGUMENT",
            "object.create auto_add_to_source_control must be a JSON boolean.",
        )
    replace_owned_root_supplied = "replace_owned_root" in arguments
    if requested_conflict == "replace" and not replace_owned_root_supplied:
        raise OperationContractError(
            "REPLACE_OWNERSHIP_REQUIRED",
            "object.create with on_name_conflict=replace requires replace_owned_root.",
        )
    if requested_conflict != "replace" and replace_owned_root_supplied:
        raise OperationContractError(
            "REPLACE_OWNERSHIP_NOT_ALLOWED",
            "replace_owned_root is accepted only when object.create uses on_name_conflict=replace.",
            details={"on_name_conflict": requested_conflict},
        )
    identity_cache: dict[bytes, ResolvedObject] = {}
    property_info_cache: dict[
        tuple[str, str, str],
        PropertyInfoMetadataRecord,
    ] = {}
    parent = _resolve_identity(
        arguments.get("parent"),
        role="parent",
        read=read,
        identity_cache=identity_cache,
    )
    if list_name is None:
        _require_object_create_writable_parent(
            parent,
            version=request.version,
            child_types=(str(arguments["type"]),),
        )
    else:
        _require_object_list_owner(parent)
        if requested_conflict == "replace":
            raise OperationContractError(
                "LIST_REPLACE_REQUIRES_OBJECT_SET",
                "object.create list insertion does not expose destructive replace; use object.set with list_mode=replaceAll.",
            )
    roles: dict[str, ResolvedObject] = {"parent": parent}
    replace_owned_root: ResolvedObject | None = None
    if requested_conflict == "replace":
        replace_owned_root = _resolve_identity(
            arguments.get("replace_owned_root"),
            role="replace_owned_root",
            read=read,
            identity_cache=identity_cache,
        )
        _reject_protected_replace_boundary(replace_owned_root)
        roles["replace_owned_root"] = replace_owned_root
    node_payload = {
        key: arguments[key]
        for key in ("type", "name", "notes", "properties", "references", "children")
        if key in arguments
    }
    try:
        normalized = normalize_object_tree(
            node_payload,
            on_name_conflict=requested_conflict,
            replace_owned=replace_owned_root_supplied,
        )
    except ObjectOperationContractError as exc:
        raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
    _require_specialized_object_tree_relationships(normalized.nodes)
    type_catalog = _read_object_type_catalog(read)
    canonical_types: dict[str, str] = {}
    resolved_references: dict[str, Any] = {}
    derived_properties: dict[str, dict[str, Any]] = {}
    node_specs = _prepare_object_node_specs(
        normalized.nodes,
        version=request.version,
        type_catalog=type_catalog,
        read=read,
        roles=roles,
        canonical_types=canonical_types,
        resolved_references=resolved_references,
        derived_properties=derived_properties,
        identity_cache=identity_cache,
        property_info_cache=property_info_cache,
    )
    for index, spec in enumerate(node_specs):
        spec["platform"] = platform
        spec["collection"] = (
            list_name if index == 0 and list_name is not None else "children"
        )
    root_path = (
        _child_path(parent.row.get("path"), normalized.root.name, field="parent.path")
        if list_name is None
        else None
    )
    conflict = normalized.on_name_conflict
    path_snapshots: list[dict[str, Any]] = []
    list_snapshots: list[dict[str, Any]] = []
    merge_field_snapshots: list[dict[str, Any]] = []
    replace_subtree_snapshots: list[dict[str, Any]] = []
    list_before: list[dict[str, Any]] = []
    if list_name is not None:
        list_before = _normalize_object_list_snapshot(
            _read_object_list(
                parent.object,
                list_name,
                fields=OBJECT_LIST_SNAPSHOT_FIELDS,
                read=read,
                platform=platform,
            ),
            owner_id=parent.object,
            list_name=list_name,
        )
        list_snapshots.append(
            {
                "object_id": parent.object,
                "list": list_name,
                "fields": list(OBJECT_LIST_SNAPSHOT_FIELDS),
                "platform": platform,
                "rows": list_before,
            }
        )
        collisions = [
            row
            for row in list_before
            if isinstance(row.get("name"), str)
            and row["name"].casefold() == normalized.root.name.casefold()
        ]
        if len(collisions) > 1:
            raise OperationContractError(
                "AMBIGUOUS_IDENTITY",
                "The requested object-list name collides with more than one live member.",
                details={"list": list_name, "name": normalized.root.name, "rows": collisions},
            )
        if conflict == "fail" and collisions:
            raise OperationContractError(
                "TARGET_EXISTS",
                "object.create list insertion with fail requires the requested member name to be absent.",
                details={"list": list_name, "name": normalized.root.name, "rows": collisions},
            )
        if conflict == "merge" and collisions:
            if not _object_type_matches(collisions[0].get("type"), node_specs[0]):
                raise OperationContractError(
                    "INVALID_TARGET_TYPE",
                    "object.create list merge collision has a different live object type.",
                    details={
                        "list": list_name,
                        "expected": node_specs[0]["canonical_type"],
                        "actual": collisions[0].get("type"),
                    },
                )
            node_specs[0]["preexisting_id"] = collisions[0].get("id")
            if normalized.root.children:
                raise OperationContractError(
                    "LIST_MERGE_CHILDREN_UNSUPPORTED",
                    "A pre-existing object.create list member with requested descendants requires a dedicated list operation.",
                    details={"list": list_name, "name": normalized.root.name},
                )
            merge_fields = _object_spec_return_fields(node_specs[0])
            merge_options: dict[str, Any] = {"return": merge_fields}
            if platform is not None:
                merge_options["platform"] = platform
            merge_rows = _rows(
                read(
                    OBJECT_GET_URI,
                    {"from": {"id": [collisions[0].get("id")]}},
                    merge_options,
                )
            )
            if len(merge_rows) != 1:
                raise OperationContractError(
                    "INVALID_READBACK",
                    "The merged object.create list member must resolve exactly once.",
                )
            merge_field_snapshots.append(
                {
                    "object_id": collisions[0].get("id"),
                    "fields": merge_fields,
                    "platform": platform,
                    "rows": merge_rows,
                }
            )
        if conflict == "rename":
            node_specs[0]["rename_collision_rows"] = collisions
    elif conflict == "fail":
        assert isinstance(root_path, str)
        rows = _read_object_path_rows(root_path, fields=IDENTITY_RETURN_FIELDS, read=read)
        if rows:
            raise OperationContractError(
                "TARGET_EXISTS",
                "object.create with on_name_conflict=fail requires the exact root path to be absent at preview.",
                details={"path": root_path, "rows": rows},
            )
        path_snapshots.append({"path": root_path, "fields": list(IDENTITY_RETURN_FIELDS), "rows": []})
    elif conflict == "merge":
        assert isinstance(root_path, str)
        for spec in node_specs:
            expected_path = _request_node_expected_path(parent.row.get("path"), spec, node_specs)
            fields = _object_spec_return_fields(spec)
            rows = _read_object_path_rows(expected_path, fields=fields, read=read)
            if len(rows) > 1:
                raise OperationContractError(
                    "AMBIGUOUS_IDENTITY",
                    "object.create merge path must resolve to at most one object.",
                    details={"path": expected_path, "rows": rows},
                )
            if rows and not _object_type_matches(rows[0].get("type"), spec):
                raise OperationContractError(
                    "INVALID_TARGET_TYPE",
                    "object.create merge collision has a different live object type.",
                    details={"path": expected_path, "expected": spec["canonical_type"], "actual": rows[0].get("type")},
                )
            path_snapshots.append({"path": expected_path, "fields": fields, "rows": rows})
            spec["expected_path"] = expected_path
            if rows:
                spec["preexisting_id"] = rows[0].get("id")
    elif conflict == "rename":
        assert isinstance(root_path, str)
        rows = _read_object_path_rows(root_path, fields=IDENTITY_RETURN_FIELDS, read=read)
        if len(rows) > 1:
            raise OperationContractError(
                "AMBIGUOUS_IDENTITY",
                "object.create rename collision path must resolve to at most one object.",
                details={"path": root_path, "rows": rows},
            )
        path_snapshots.append({"path": root_path, "fields": list(IDENTITY_RETURN_FIELDS), "rows": rows})
        if not rows:
            node_specs[0]["expected_path"] = root_path
    else:  # replace
        assert isinstance(root_path, str)
        if replace_owned_root is None:  # pragma: no cover - guarded above and by request parsing.
            raise OperationContractError(
                "REPLACE_OWNERSHIP_REQUIRED",
                "object.create replace lacks its live-resolved owned root.",
            )
        owned_root_path = _absolute_live_object_path(
            replace_owned_root.row.get("path"),
            field="replace_owned_root.path",
        )
        if not _is_strict_descendant_object_path(root_path, owned_root_path):
            raise OperationContractError(
                "REPLACE_TARGET_OUTSIDE_OWNED_ROOT",
                "The exact object.create collision must be strictly below replace_owned_root.",
                details={"collision_path": root_path, "replace_owned_root_path": owned_root_path},
            )
        rows = _read_object_path_rows(root_path, fields=IDENTITY_RETURN_FIELDS, read=read)
        if len(rows) != 1:
            raise OperationContractError(
                "REPLACE_TARGET_REQUIRED" if not rows else "AMBIGUOUS_IDENTITY",
                "object.create replace requires the exact root path to resolve to one existing object.",
                details={"path": root_path, "row_count": len(rows), "rows": rows},
            )
        collision_row = rows[0]
        if collision_row.get("path") != root_path:
            raise OperationContractError(
                "IDENTITY_MISMATCH",
                "The live replace collision row does not match the exact requested root path.",
                details={"expected_path": root_path, "row": collision_row},
            )
        collision_id = collision_row.get("id")
        if not _valid_object_id(collision_id):
            raise OperationContractError(
                "INVALID_READBACK",
                "The live replace collision row lacks a canonical GUID.",
                details={"row": collision_row},
            )
        collision = ResolvedObject(
            identity=ObjectIdentity(path=root_path),
            object=collision_id,
            resolution="live-exact-create-root-collision",
            row=collision_row,
        )
        _reject_protected_replace_boundary(collision)
        if _same_identity(collision.object, replace_owned_root.object):
            raise OperationContractError(
                "REPLACE_TARGET_OUTSIDE_OWNED_ROOT",
                "The replace collision cannot be replace_owned_root itself.",
                details={"collision": collision.as_dict(), "replace_owned_root": replace_owned_root.as_dict()},
            )
        roles["replace_collision"] = collision
        subtree_rows = _capture_replace_subtree_snapshot(
            collision,
            read=read,
        )
        path_snapshots.append(
            {"path": root_path, "fields": list(IDENTITY_RETURN_FIELDS), "rows": rows}
        )
        replace_subtree_snapshots.append(
            {
                "root_id": collision.object,
                "root_path": root_path,
                "fields": list(OBJECT_REPLACE_SNAPSHOT_FIELDS),
                "rows": subtree_rows,
            }
        )
        for spec in node_specs:
            spec["expected_path"] = _request_node_expected_path(
                parent.row.get("path"),
                spec,
                node_specs,
            )

    parent_children = (
        _read_direct_children(
            parent.object,
            fields=IDENTITY_RETURN_FIELDS,
            read=read,
        )
        if list_name is None
        else []
    )
    trusted_root = _materialize_canonical_object_node(
        normalized.root,
        canonical_types=canonical_types,
        resolved_references=resolved_references,
        derived_properties=derived_properties,
    )
    dispatch_args = {
        "parent": parent.object,
        **trusted_root,
        "onNameConflict": conflict,
        "autoAddToSourceControl": auto_add_to_source_control,
    }
    if platform is not None:
        dispatch_args["platform"] = platform
    if list_name is not None:
        dispatch_args["list"] = list_name
    preview = _closed_operation_preview(
        uri="ak.wwise.core.object.create",
        args=dispatch_args,
        options={},
        version=request.version,
        family="object-mutation",
        metadata={
            "closed_object_tree": True,
            "node_count": len(node_specs),
            "on_name_conflict": conflict,
            "platform": platform,
            "list": list_name,
            "auto_add_to_source_control": auto_add_to_source_control,
            "replaced_subtree_node_count": (
                len(replace_subtree_snapshots[0]["rows"])
                if replace_subtree_snapshots
                else 0
            ),
        },
    )
    graph_guard = {
        "kind": "object-create-graph",
        "path_snapshots": path_snapshots,
        "children_snapshots": (
            [
                {
                    "object_id": parent.object,
                    "fields": list(IDENTITY_RETURN_FIELDS),
                    "rows": parent_children,
                }
            ]
            if list_name is None
            else []
        ),
        "list_snapshots": list_snapshots,
        "field_snapshots": merge_field_snapshots,
        "subtree_snapshots": replace_subtree_snapshots,
    }
    verification = {
        "kind": "object-create-graph",
        "version": request.version,
        "parent_id": parent.object,
        "on_name_conflict": conflict,
        "list": list_name,
        "list_before": list_before,
        "nodes": node_specs,
        "preexisting_root_rows": (
            path_snapshots[0]["rows"]
            if path_snapshots
            else node_specs[0].get("rename_collision_rows", [])
        ),
        "replaced_subtree_rows": (
            replace_subtree_snapshots[0]["rows"]
            if replace_subtree_snapshots
            else []
        ),
    }
    if conflict == "replace":
        cleanup = {
            "kind": "discard-case-owned-project-copy-after-replace",
            "description": "The replaced subtree is not reconstructed; discard the case-owned project copy after collecting evidence.",
            "automatic": False,
            "automatic_retry": False,
            "replace_owned_root_id": replace_owned_root.object if replace_owned_root is not None else None,
            "irreversible_preexisting_changes": True,
        }
    else:
        cleanup = {
            "kind": "delete-returned-root-guid" if conflict in {"fail", "rename"} else "discard-owned-sandbox-after-merge",
            "automatic": False,
            "automatic_retry": False,
            "source": "execution_result.id",
            "irreversible_preexisting_changes": conflict == "merge",
        }
    return preview, roles, {"object_graph_guard": graph_guard, "object_create_nodes": node_specs}, verification, cleanup


def _raise_plugin_operation_error(exc: PluginOperationContractError) -> NoReturn:
    raise OperationContractError(
        exc.error_code,
        str(exc),
        details=exc.details,
    ) from exc


def _plugin_guid(value: Any, *, field: str, allow_none: bool = False) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("id")
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not _PLUGIN_GUID.fullmatch(value):
        raise OperationContractError(
            "INVALID_READBACK",
            f"{field} must expose one canonical Wwise GUID.",
            details={"field": field, "value": value},
        )
    return value


def _sealed_plugin_property_validation(
    value: Any,
    *,
    descriptor: PluginCreationDescriptor,
) -> tuple[ValidatedPluginProperty, ...]:
    """Rehydrate the immutable property/type bindings without trusting JSON."""

    if not isinstance(value, list):
        raise OperationContractError(
            "INVALID_PREVIEW",
            "object.createPlugin property validation must be an ordered array.",
        )
    if len(value) != len(descriptor.properties):
        raise OperationContractError(
            "INVALID_PREVIEW",
            "object.createPlugin property validation count does not match the "
            "immutable descriptor.",
            details={
                "expected": len(descriptor.properties),
                "actual": len(value),
            },
        )

    validated: list[ValidatedPluginProperty] = []
    for index, (raw_row, requested) in enumerate(
        zip(value, descriptor.properties)
    ):
        if (
            not isinstance(raw_row, Mapping)
            or set(raw_row) != {"name", "value", "metadata_type"}
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "object.createPlugin property validation row is malformed.",
                details={"index": index, "row": raw_row},
            )
        name = raw_row.get("name")
        metadata_type = raw_row.get("metadata_type")
        raw_value = raw_row.get("value")
        if (
            name != requested.name
            or type(raw_value) is not type(requested.value)
            or raw_value != requested.value
            or not isinstance(metadata_type, str)
            or not metadata_type
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "object.createPlugin property validation does not match the "
                "immutable descriptor.",
                details={
                    "index": index,
                    "expected": requested.as_dict(),
                    "actual": dict(raw_row),
                },
            )
        validated.append(
            ValidatedPluginProperty(
                name=requested.name,
                value=requested.value,
                metadata_type=metadata_type,
            )
        )

    try:
        canonical = validate_plugin_property_metadata(
            descriptor,
            (
                [
                    {"name": item.name, "type": item.metadata_type}
                    for item in validated
                ]
                if validated
                else None
            ),
        )
    except PluginOperationContractError as exc:
        raise OperationContractError(
            "INVALID_PREVIEW",
            "object.createPlugin property validation is not a valid sealed "
            "classId-scoped binding.",
            details=exc.as_dict(),
        ) from exc
    if tuple(validated) != canonical:
        raise OperationContractError(
            "INVALID_PREVIEW",
            "object.createPlugin property validation is not canonical.",
        )
    return canonical


def _normalize_plugin_source_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    target_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    for index, row_value in enumerate(rows):
        row = dict(row_value)
        object_type = row.get("type")
        if not isinstance(object_type, str) or not object_type:
            raise OperationContractError(
                "INVALID_READBACK",
                "Every direct child row must expose a type while Source plug-in pre-state is captured.",
                details={"index": index, "row": row},
            )
        if object_type != "Source":
            continue
        object_id = _plugin_guid(row.get("id"), field=f"source_children[{index}].id")
        name = row.get("name")
        if not isinstance(name, str):
            raise OperationContractError(
                "INVALID_READBACK",
                "Every Source plug-in pre-state row must expose a name.",
                details={"index": index, "row": row},
            )
        parent = _plugin_guid(
            row.get("parent"),
            field=f"source_children[{index}].parent",
        )
        if not _same_identity(parent, target_id):
            raise OperationContractError(
                "INVALID_READBACK",
                "A direct Source child readback reported a different parent.",
                details={
                    "index": index,
                    "expected_parent": target_id,
                    "actual_parent": parent,
                    "row": row,
                },
            )
        normalized.append(
            {
                "id": object_id,
                "name": name,
                "type": object_type,
                "parent": parent,
            }
        )
    normalized.sort(key=lambda row: str(row["id"]).casefold())
    ids = [str(row["id"]) for row in normalized]
    if len({value.casefold() for value in ids}) != len(ids):
        raise OperationContractError(
            "INVALID_READBACK",
            "Source plug-in pre-state contains duplicate GUIDs.",
            details={"rows": normalized},
        )
    return normalized, ids


def _read_plugin_prestate(
    *,
    version: str,
    target_id: str,
    descriptor: PluginCreationDescriptor,
    read: ReadCall,
) -> dict[str, Any]:
    if descriptor.kind == "source":
        fields = ("id", "name", "type", "parent")
        args = {
            "from": {"id": [target_id]},
            "transform": [{"select": ["children"]}],
        }
        options = {"return": list(fields)}
        result = read(OBJECT_GET_URI, args, options)
        rows = _rows(result)
        normalized_rows, ids = _normalize_plugin_source_rows(
            rows,
            target_id=target_id,
        )
        return {
            "kind": "source_children",
            "uri": OBJECT_GET_URI,
            "args": args,
            "options": options,
            "rows": normalized_rows,
            "preexisting_plugin_ids": ids,
        }

    if version == "2022.1":
        fields = ("id", *WWISE_2022_EFFECT_FIELDS)
        args = {"from": {"id": [target_id]}}
        options = {"return": list(fields)}
        result = read(OBJECT_GET_URI, args, options)
        rows = _rows(result)
        if len(rows) != 1 or not _same_identity(rows[0].get("id"), target_id):
            raise OperationContractError(
                "INVALID_READBACK",
                "Wwise 2022.1 fixed Effect pre-state must return the target exactly once.",
                details={"target_id": target_id, "rows": rows},
            )
        fixed_effects: dict[str, str | None] = {}
        for field_name in WWISE_2022_EFFECT_FIELDS:
            if field_name not in rows[0]:
                raise OperationContractError(
                    "INVALID_READBACK",
                    "Wwise 2022.1 fixed Effect pre-state omitted a requested slot.",
                    details={
                        "field": field_name,
                        "required_fields": list(WWISE_2022_EFFECT_FIELDS),
                        "row": rows[0],
                    },
                )
            fixed_effects[field_name] = _plugin_guid(
                rows[0].get(field_name),
                field=f"fixed_effects.{field_name}",
                allow_none=True,
            )
        ids = [
            value
            for value in fixed_effects.values()
            if isinstance(value, str)
        ]
        if len({value.casefold() for value in ids}) != len(ids):
            raise OperationContractError(
                "INVALID_READBACK",
                "Wwise 2022.1 fixed Effect pre-state contains duplicate plug-in GUIDs.",
                details={"fixed_effects": fixed_effects},
            )
        return {
            "kind": "fixed_effect_references",
            "uri": OBJECT_GET_URI,
            "args": args,
            "options": options,
            "fixed_effects": fixed_effects,
            "preexisting_plugin_ids": ids,
        }

    fields = PLUGIN_EFFECT_SLOT_READBACK_FIELDS
    rows, effect_readbacks = _read_object_list_rows_with_evidence(
        target_id,
        "Effects",
        fields=fields,
        read=read,
        platform=descriptor.platform,
        context="plugin-effect-slots",
        # Wwise can omit an empty, requested object-list accessor.  This is a
        # fixed, operation-owned list token rather than caller-authored input.
        allow_missing_empty=True,
    )
    owner_readback = effect_readbacks[0]
    normalized_slots: list[dict[str, Any]] = []
    plugin_ids: list[str] = []
    for index, row_value in enumerate(rows):
        row = dict(row_value)
        if row.get("type") != "EffectSlot":
            raise OperationContractError(
                "INVALID_READBACK",
                "The @Effects pre-state must contain only EffectSlot rows.",
                details={"index": index, "row": row},
            )
        slot_id = _plugin_guid(row.get("id"), field=f"effect_slots[{index}].id")
        parent_id = _plugin_guid(
            row.get("parent"),
            field=f"effect_slots[{index}].parent",
        )
        owner_id = _plugin_guid(
            row.get("owner"),
            field=f"effect_slots[{index}].owner",
        )
        if not _same_identity(parent_id, target_id) or not _same_identity(
            owner_id,
            target_id,
        ):
            raise OperationContractError(
                "INVALID_READBACK",
                "An EffectSlot pre-state row is not owned by the resolved target.",
                details={
                    "index": index,
                    "target_id": target_id,
                    "parent": parent_id,
                    "owner": owner_id,
                    "row": row,
                },
            )
        effect_id = _plugin_guid(
            row.get("@Effect"),
            field=f"effect_slots[{index}].@Effect",
            allow_none=True,
        )
        if effect_id is not None:
            plugin_ids.append(effect_id)
        normalized_slots.append(
            {
                "id": slot_id,
                "name": row.get("name"),
                "type": "EffectSlot",
                "parent": parent_id,
                "owner": owner_id,
                "@Effect": effect_id,
            }
        )
    normalized_slots.sort(key=lambda row: str(row["id"]).casefold())
    slot_ids = [str(row["id"]) for row in normalized_slots]
    if (
        len({value.casefold() for value in slot_ids}) != len(slot_ids)
        or len({value.casefold() for value in plugin_ids}) != len(plugin_ids)
    ):
        raise OperationContractError(
            "INVALID_READBACK",
            "The @Effects pre-state contains duplicate slot or plug-in GUIDs.",
            details={"effect_slots": normalized_slots},
        )
    return {
        "kind": "effect_slots",
        "uri": OBJECT_GET_URI,
        "args": owner_readback["args"],
        "options": owner_readback["options"],
        "effect_slots": normalized_slots,
        "preexisting_plugin_ids": sorted(plugin_ids, key=str.casefold),
    }


def _prepare_object_create_plugin(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[
    SemanticPreview,
    dict[str, ResolvedObject],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    try:
        descriptor = normalize_plugin_creation(arguments.get("plugin"))
    except PluginOperationContractError as exc:
        _raise_plugin_operation_error(exc)

    target = _resolve_identity(arguments.get("target"), role="target", read=read)
    if not isinstance(target.object, str) or not _PLUGIN_GUID.fullmatch(target.object):
        raise OperationContractError(
            "INVALID_READBACK",
            "object.createPlugin target must resolve to a canonical Wwise GUID.",
            details={"target": target.as_dict()},
        )
    target_type = target.row.get("type")
    if not isinstance(target_type, str) or not target_type:
        raise OperationContractError(
            "INVALID_READBACK",
            "object.createPlugin target readback must expose a type.",
            details={"target": target.as_dict()},
        )

    property_metadata: list[dict[str, Any]] = []
    for metadata_request in plugin_property_metadata_requests(descriptor):
        raw_args = metadata_request["args"]
        info = _read_property_info(
            read,
            class_id=descriptor.class_id,
            name=str(raw_args["property"]),
        )
        property_metadata.append(info.as_dict())

    plugin_prestate = _read_plugin_prestate(
        version=request.version,
        target_id=target.object,
        descriptor=descriptor,
        read=read,
    )
    fixed_effects = (
        plugin_prestate.get("fixed_effects")
        if plugin_prestate.get("kind") == "fixed_effect_references"
        else None
    )
    try:
        plugin_plan = build_plugin_creation_plan(
            version=request.version,
            target_id=target.object,
            target_type=target_type,
            request=descriptor,
            property_metadata=property_metadata or None,
            effect_slots_2022=(
                fixed_effects
                if isinstance(fixed_effects, Mapping)
                else None
            ),
        )
    except PluginOperationContractError as exc:
        _raise_plugin_operation_error(exc)

    plan_payload = plugin_plan.as_dict()
    preview = _closed_operation_preview(
        uri=OBJECT_SET_URI,
        args=plugin_plan.dispatch_args,
        options={},
        version=request.version,
        family="object-mutation",
        metadata={
            "closed_plugin_creation": True,
            "plugin_kind": descriptor.kind,
            "plugin_class_id": descriptor.class_id,
            "placement": dict(plugin_plan.placement),
            "create_only": True,
            "raw_replace_all_allowed": False,
        },
    )
    preexisting_ids = plugin_prestate["preexisting_plugin_ids"]
    guard = {
        "version": request.version,
        "target_id": target.object,
        "target_type": target_type,
        "descriptor": descriptor.as_dict(),
        "plan": plan_payload,
        "snapshot": plugin_prestate,
        "property_metadata": property_metadata,
    }
    verification: dict[str, Any] = {
        "kind": "object-plugin-created",
        "version": request.version,
        "target_id": target.object,
        "target_type": target_type,
        "descriptor": descriptor.as_dict(),
        "placement": dict(plugin_plan.placement),
        "preexisting_plugin_ids": list(preexisting_ids),
        "property_validation": [
            item.as_dict() for item in plugin_plan.validated_properties
        ],
        "readback_fields": list(plugin_verification_fields(descriptor)),
        "readback_view": {
            "language": descriptor.language,
            "platform": descriptor.platform,
        },
    }
    if plugin_prestate["kind"] == "fixed_effect_references":
        verification["pre_effect_references"] = dict(
            plugin_prestate["fixed_effects"]
        )
    elif plugin_prestate["kind"] == "effect_slots":
        verification["preexisting_effect_slot_ids"] = [
            str(row["id"])
            for row in plugin_prestate["effect_slots"]
        ]
    cleanup = {
        "kind": "delete-created-plugin-after-fresh-preview",
        "description": (
            "Cleanup may delete only the verified returned plug-in GUID after "
            "a separate fresh destructive preview."
        ),
        "automatic": False,
        "automatic_retry": False,
        "source": "verification_result.plugin.id",
    }
    return (
        preview,
        {"target": target},
        {"plugin_creation_guard": guard},
        verification,
        cleanup,
    )


def _prepare_object_set(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw_objects = _mapping_sequence(arguments.get("objects"), field="objects")
    conflict = str(arguments.get("on_name_conflict", "fail"))
    global_platform = (
        _non_empty_string(arguments.get("platform"), field="platform")
        if "platform" in arguments
        else None
    )
    global_list_mode = str(arguments.get("list_mode", "append"))
    auto_add_to_source_control = arguments.get(
        "auto_add_to_source_control",
        False,
    )
    if not isinstance(auto_add_to_source_control, bool):
        raise OperationContractError(
            "INVALID_ARGUMENT",
            "object.set auto_add_to_source_control must be a JSON boolean.",
        )
    type_catalog = _read_object_type_catalog(read)
    roles: dict[str, ResolvedObject] = {}
    dispatch_objects: list[dict[str, Any]] = []
    node_specs: list[dict[str, Any]] = []
    field_snapshots: list[dict[str, Any]] = []
    children_snapshots: list[dict[str, Any]] = []
    list_snapshots: list[dict[str, Any]] = []
    list_subtree_snapshots: list[dict[str, Any]] = []
    path_snapshots: list[dict[str, Any]] = []
    object_set_file_proofs: list[dict[str, Any]] = []
    requested_languages: set[str] = set()
    materialized_imports: dict[str, dict[str, Any]] = {}
    project_info_cache: dict[str, Mapping[str, Any]] = {}
    identity_cache: dict[bytes, ResolvedObject] = {}
    property_info_cache: dict[
        tuple[str, str, str],
        PropertyInfoMetadataRecord,
    ] = {}

    def import_context_read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if uri == GET_PROJECT_INFO_URI and not args and not options:
            cached = project_info_cache.get(uri)
            if cached is not None:
                return cached
            result = read(uri, args, options)
            project_info_cache[uri] = result
            return result
        return read(uri, args, options)

    resolved_target_ids: dict[str, int] = {}
    for index, item in enumerate(raw_objects):
        merge_child_snapshots: list[dict[str, Any]] = []
        target = _resolve_identity(
            item.get("object"),
            role=f"objects[{index}].object",
            read=read,
            identity_cache=identity_cache,
        )
        platform = (
            _non_empty_string(item.get("platform"), field=f"objects[{index}].platform")
            if "platform" in item
            else global_platform
        )
        row_conflict = str(item.get("on_name_conflict", conflict))
        row_list_mode = str(item.get("list_mode", global_list_mode))
        target_key = _identity_key(target.object)
        previous_index = resolved_target_ids.get(target_key)
        if previous_index is not None:
            raise OperationContractError(
                "DUPLICATE_TARGET",
                "object.set identities must resolve to distinct live object GUIDs.",
                details={
                    "index": index,
                    "previous_index": previous_index,
                    "object_id": target.object,
                },
            )
        resolved_target_ids[target_key] = index
        roles[f"objects[{index}].object"] = target
        properties = normalize_property_descriptors(
            item.get("properties", []),
            request_path=f"$.objects[{index}].properties",
        )
        references = normalize_reference_descriptors(
            item.get("references", []),
            request_path=f"$.objects[{index}].references",
        )
        children = normalize_object_forest(
            item.get("children", []),
            on_name_conflict=row_conflict,
            base_path=f"$.objects[{index}].children",
            allow_platform=True,
            allow_language=True,
            allow_import=request.version in OBJECT_SET_IMPORT_VERSIONS,
        )
        lists = normalize_object_lists(
            item.get("lists", []),
            request_path=f"$.objects[{index}].lists",
            allow_platform=True,
            allow_language=True,
            allow_import=request.version in OBJECT_SET_IMPORT_VERSIONS,
        )
        if children.roots:
            _require_object_create_writable_parent(
                target,
                version=request.version,
                child_types=tuple(root.type for root in children.roots),
            )
            _require_specialized_object_tree_relationships(children.nodes)
        if lists:
            _require_object_list_owner(target)
        target_spec: dict[str, Any] = {
            "request_path": f"$.objects[{index}]",
            "parent_request_path": None,
            "existing_target": True,
            "target_id": target.object,
            "requested_name": item.get("name", target.row.get("name")),
            "original_name": target.row.get("name"),
            "requested_type": target.row.get("type"),
            "canonical_type": target.row.get("type"),
            "collection": None,
            "on_name_conflict": row_conflict,
            "list_mode": row_list_mode,
            "notes_supplied": "notes" in item,
            "requested_notes": item.get("notes"),
            "platform": platform,
            "properties": [],
            "references": [],
        }
        trusted: dict[str, Any] = {"object": target.object}
        if "import" in item:
            if request.version not in OBJECT_SET_IMPORT_VERSIONS:
                raise OperationContractError(
                    "VERSION_BEHAVIOR_BOUNDARY",
                    "object.set import is available only in Wwise 2023.1-2025.1.",
                    details={"version": request.version},
                )
            try:
                row_import = normalize_object_import(
                    item.get("import"),
                    request_path=f"$.objects[{index}].import",
                )
            except ObjectOperationContractError as exc:
                raise OperationContractError(
                    exc.error_code,
                    str(exc),
                    details=exc.details,
                ) from exc
            trusted_import, import_spec = _prepare_object_set_import(
                row_import,
                canonical_type=target.row.get("type"),
                type_catalog=type_catalog,
                file_proofs=object_set_file_proofs,
                default_auto_add_to_source_control=auto_add_to_source_control,
            )
            trusted["import"] = trusted_import
            target_spec["import"] = import_spec
        if "platform" in item:
            trusted["platform"] = platform
        if "on_name_conflict" in item:
            trusted["onNameConflict"] = row_conflict
        if "list_mode" in item:
            trusted["listMode"] = row_list_mode
        property_info_by_name: dict[str, PropertyInfoMetadataRecord] = {}
        derived_target_properties: dict[str, Any] = {}
        if "notes" in item:
            notes = item.get("notes")
            if not isinstance(notes, str):
                raise OperationContractError("INVALID_ARGUMENT", f"object.set objects[{index}].notes must be a string.")
            trusted["notes"] = notes
        if "name" in item:
            requested_name = item.get("name")
            if not isinstance(requested_name, str) or not requested_name.strip():
                raise OperationContractError(
                    "INVALID_ARGUMENT",
                    f"object.set objects[{index}].name must be a non-empty string.",
                )
            if requested_name == target.row.get("name"):
                raise OperationContractError(
                    "NO_OP",
                    f"object.set objects[{index}].name already matches the live target.",
                )
            if row_conflict == "merge":
                raise OperationContractError(
                    "INVALID_CONFLICT_POLICY",
                    "Renaming an existing object does not support on_name_conflict=merge.",
                    details={"index": index},
                )
            trusted["name"] = requested_name
        for descriptor in properties:
            info = _read_property_info_cached(
                read,
                cache=property_info_cache,
                object_id=target.object,
                name=descriptor.name,
            )
            _require_object_property_value(info, descriptor.value)
            if platform is not None:
                _require_platform_field_enabled(
                    read,
                    object_id=target.object,
                    field_name=descriptor.name,
                    platform=platform,
                )
            property_info_by_name[descriptor.name.casefold()] = info
            trusted[f"@{descriptor.name}"] = descriptor.value
            target_spec["properties"].append(
                {"name": descriptor.name, "value": descriptor.value, "metadata_type": info.type}
            )
        for descriptor in references:
            info = _read_property_info_cached(
                read,
                cache=property_info_cache,
                object_id=target.object,
                name=descriptor.name,
            )
            _require_object_reference_metadata(info)
            if platform is not None:
                _require_platform_field_enabled(
                    read,
                    object_id=target.object,
                    field_name=descriptor.name,
                    platform=platform,
                )
            activation_properties = _apply_reference_activation_dependencies(
                info,
                read=read,
                object_id=target.object,
                property_specs=target_spec["properties"],
                property_info_by_name=property_info_by_name,
                derived_properties=derived_target_properties,
                request_path=descriptor.request_path,
                property_info_cache=property_info_cache,
            )
            resolved = _resolve_identity(
                descriptor.target.as_dict(),
                role=descriptor.request_path,
                read=read,
                identity_cache=identity_cache,
            )
            _require_reference_target_allowed(info, resolved)
            roles[descriptor.request_path] = resolved
            trusted[f"@{descriptor.name}"] = resolved.object
            reference_spec = {"name": descriptor.name, "target_id": resolved.object}
            if activation_properties:
                reference_spec["activation_properties"] = list(activation_properties)
            target_spec["references"].append(reference_spec)
        for property_name, value in derived_target_properties.items():
            trusted[f"@{property_name}"] = value

        canonical_types: dict[str, str] = {}
        resolved_references: dict[str, Any] = {}
        derived_child_properties: dict[str, dict[str, Any]] = {}
        child_specs = _prepare_object_node_specs(
            children.nodes,
            version=request.version,
            type_catalog=type_catalog,
            read=read,
            roles=roles,
            canonical_types=canonical_types,
            resolved_references=resolved_references,
            derived_properties=derived_child_properties,
            identity_cache=identity_cache,
            property_info_cache=property_info_cache,
        )
        child_spec_by_path = {
            str(spec["request_path"]): spec for spec in child_specs
        }
        for node in children.nodes:
            if node.language is not None:
                requested_languages.add(node.language)
            if node.import_arg is not None:
                trusted_import, import_spec = _prepare_object_set_import(
                    node.import_arg,
                    canonical_type=canonical_types[node.request_path],
                    type_catalog=type_catalog,
                    file_proofs=object_set_file_proofs,
                    default_auto_add_to_source_control=auto_add_to_source_control,
                )
                materialized_imports[node.request_path] = trusted_import
                child_spec_by_path[node.request_path]["import"] = import_spec
        for child_spec in child_specs:
            child_spec.setdefault("platform", platform)
            child_spec["collection"] = "children"
            child_spec["on_name_conflict"] = row_conflict
        if children.roots:
            trusted["children"] = [
                _materialize_canonical_object_node(
                    root,
                    canonical_types=canonical_types,
                    resolved_references=resolved_references,
                    derived_properties=derived_child_properties,
                    materialized_imports=materialized_imports,
                )
                for root in children.roots
            ]
        target_path = _absolute_live_object_path(
            target.row.get("path"),
            field=f"objects[{index}].path",
        )
        target_spec["old_path"] = target_path
        future_target_path = target_path
        if "name" in item:
            parent_path = target_path.rsplit("\\", 1)[0]
            future_target_path = _child_path(
                parent_path,
                item.get("name"),
                field=f"objects[{index}].parent_path",
            )
            rename_rows = _read_object_path_rows(
                future_target_path,
                fields=IDENTITY_RETURN_FIELDS,
                read=read,
            )
            rename_rows = [
                row
                for row in rename_rows
                if not _same_identity(row.get("id"), target.object)
            ]
            if len(rename_rows) > 1:
                raise OperationContractError(
                    "AMBIGUOUS_IDENTITY",
                    "object.set rename collision path resolved more than once.",
                    details={"path": future_target_path, "rows": rename_rows},
                )
            if row_conflict == "fail" and rename_rows:
                raise OperationContractError(
                    "TARGET_EXISTS",
                    "object.set rename with fail requires the exact requested path to be absent.",
                    details={"path": future_target_path, "rows": rename_rows},
                )
            path_snapshots.append(
                {
                    "path": future_target_path,
                    "fields": list(IDENTITY_RETURN_FIELDS),
                    "rows": rename_rows,
                }
            )
            target_spec["rename_collision_rows"] = rename_rows
            if row_conflict == "fail":
                target_spec["expected_path"] = future_target_path
        for child_spec in child_specs:
            child_spec["target_index"] = index
            child_spec["parent_request_path"] = (
                target_spec["request_path"]
                if child_spec["parent_request_path"] is None
                else child_spec["parent_request_path"]
            )
            expected_path = (
                _request_node_expected_path(
                    future_target_path,
                    child_spec,
                    child_specs,
                    root_request_path=target_spec["request_path"],
                )
                if row_conflict in {"fail", "merge"}
                else None
            )
            if row_conflict == "merge":
                assert isinstance(expected_path, str)
                fields = _object_spec_return_fields(child_spec)
                snapshot_platform = child_spec.get("platform")
                snapshot_language = _localized_import_read_language(
                    child_spec.get("requested_language")
                )
                rows = _read_object_path_rows(
                    expected_path,
                    fields=fields,
                    read=read,
                    platform=snapshot_platform,
                    language=snapshot_language,
                )
                if len(rows) > 1:
                    raise OperationContractError(
                        "AMBIGUOUS_IDENTITY",
                        "object.set merge path must resolve to at most one object.",
                        details={"path": expected_path, "rows": rows},
                    )
                if rows and not _object_type_matches(rows[0].get("type"), child_spec):
                    raise OperationContractError(
                        "INVALID_TARGET_TYPE",
                        "object.set merge collision has a different live object type.",
                        details={"path": expected_path, "expected": child_spec["canonical_type"], "actual": rows[0].get("type")},
                    )
                path_snapshots.append(
                    {
                        "path": expected_path,
                        "fields": fields,
                        "platform": snapshot_platform,
                        "language": snapshot_language,
                        "rows": rows,
                    }
                )
                child_spec["expected_path"] = expected_path
                if rows:
                    child_spec["preexisting_id"] = rows[0].get("id")
                    preexisting_children = _read_direct_children(
                        rows[0].get("id"),
                        fields=IDENTITY_RETURN_FIELDS,
                        read=read,
                    )
                    child_spec["preexisting_children"] = preexisting_children
                    merge_child_snapshots.append(
                        {
                            "object_id": rows[0].get("id"),
                            "fields": list(IDENTITY_RETURN_FIELDS),
                            "rows": preexisting_children,
                        }
                    )
            elif (
                row_conflict == "fail"
                and child_spec["parent_request_path"] == target_spec["request_path"]
            ):
                assert isinstance(expected_path, str)
                fields = _object_spec_return_fields(child_spec)
                snapshot_platform = child_spec.get("platform")
                snapshot_language = _localized_import_read_language(
                    child_spec.get("requested_language")
                )
                rows = _read_object_path_rows(
                    expected_path,
                    fields=fields,
                    read=read,
                    platform=snapshot_platform,
                    language=snapshot_language,
                )
                if rows:
                    raise OperationContractError(
                        "TARGET_EXISTS",
                        "object.set append-only child creation with fail requires each root child path to be absent.",
                        details={"path": expected_path, "rows": rows},
                    )
                path_snapshots.append(
                    {
                        "path": expected_path,
                        "fields": fields,
                        "platform": snapshot_platform,
                        "language": snapshot_language,
                        "rows": rows,
                    }
                )
                child_spec["expected_path"] = expected_path

        list_specs: list[dict[str, Any]] = []
        target_list_snapshots: list[dict[str, Any]] = []
        for list_index, descriptor in enumerate(lists):
            if descriptor.name.casefold() in OBJECT_DEDICATED_LIST_NAMES:
                raise OperationContractError(
                    "DEDICATED_OPERATION_REQUIRED",
                    "Effect and RTPC object lists must use object.createPlugin or object.setRTPC.",
                    details={
                        "index": index,
                        "list_index": list_index,
                        "list": descriptor.name,
                    },
                )
            before_rows = _normalize_object_list_snapshot(
                _read_object_list(
                    target.object,
                    descriptor.name,
                    fields=OBJECT_LIST_SNAPSHOT_FIELDS,
                    read=read,
                    platform=platform,
                ),
                owner_id=target.object,
                list_name=descriptor.name,
            )
            list_snapshot = {
                "object_id": target.object,
                "list": descriptor.name,
                "fields": list(OBJECT_LIST_SNAPSHOT_FIELDS),
                "platform": platform,
                "rows": before_rows,
            }
            list_snapshots.append(list_snapshot)
            target_list_snapshots.append(list_snapshot)
            if row_list_mode == "replaceAll":
                replacement_subtrees = _capture_object_list_replace_subtrees(
                    before_rows,
                    read=read,
                )
                for subtree in replacement_subtrees:
                    subtree["object_id"] = target.object
                    subtree["list"] = descriptor.name
                list_subtree_snapshots.extend(replacement_subtrees)

            prepared_specs = _prepare_object_node_specs(
                descriptor.nodes,
                version=request.version,
                type_catalog=type_catalog,
                read=read,
                roles=roles,
                canonical_types=canonical_types,
                resolved_references=resolved_references,
                derived_properties=derived_child_properties,
                identity_cache=identity_cache,
                property_info_cache=property_info_cache,
            )
            prepared_spec_by_path = {
                str(spec["request_path"]): spec for spec in prepared_specs
            }
            for node in descriptor.nodes:
                if node.language is not None:
                    requested_languages.add(node.language)
                if node.import_arg is not None:
                    trusted_import, import_spec = _prepare_object_set_import(
                        node.import_arg,
                        canonical_type=canonical_types[node.request_path],
                        type_catalog=type_catalog,
                        file_proofs=object_set_file_proofs,
                        default_auto_add_to_source_control=auto_add_to_source_control,
                    )
                    materialized_imports[node.request_path] = trusted_import
                    prepared_spec_by_path[node.request_path]["import"] = (
                        import_spec
                    )
            root_paths = {root.request_path for root in descriptor.objects}
            root_specs = [
                spec
                for spec in prepared_specs
                if spec.get("request_path") in root_paths
            ]
            if len(root_specs) != len(descriptor.objects):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Closed object-list roots could not be bound to their normalized descriptors.",
                )
            for list_spec in prepared_specs:
                is_root = list_spec.get("request_path") in root_paths
                list_spec["target_index"] = index
                list_spec.setdefault("platform", platform)
                list_spec["collection"] = descriptor.name if is_root else "children"
                list_spec["list_owner_id"] = target.object
                list_spec["list_name"] = descriptor.name
                list_spec["list_mode"] = row_list_mode
                list_spec["on_name_conflict"] = row_conflict
                if is_root:
                    list_spec["parent_request_path"] = target_spec["request_path"]
            collisions_by_name: dict[str, list[dict[str, Any]]] = {}
            for root_spec in root_specs:
                requested_name = root_spec.get("requested_name")
                collisions = [
                    row
                    for row in before_rows
                    if isinstance(row.get("name"), str)
                    and isinstance(requested_name, str)
                    and row["name"].casefold() == requested_name.casefold()
                ]
                collisions_by_name[str(requested_name)] = collisions
                if len(collisions) > 1:
                    raise OperationContractError(
                        "AMBIGUOUS_IDENTITY",
                        "A requested object-list member name resolves more than once.",
                        details={
                            "list": descriptor.name,
                            "name": requested_name,
                            "rows": collisions,
                        },
                    )
                if row_list_mode == "append" and row_conflict == "fail" and collisions:
                    raise OperationContractError(
                        "TARGET_EXISTS",
                        "Appending an object-list member with fail requires its name to be absent.",
                        details={
                            "list": descriptor.name,
                            "name": requested_name,
                            "rows": collisions,
                        },
                    )
                if row_list_mode == "append" and row_conflict == "merge" and collisions:
                    if not _object_type_matches(collisions[0].get("type"), root_spec):
                        raise OperationContractError(
                            "INVALID_TARGET_TYPE",
                            "An object-list merge collision has a different live type.",
                            details={
                                "list": descriptor.name,
                                "name": requested_name,
                                "expected": root_spec.get("canonical_type"),
                                "actual": collisions[0].get("type"),
                            },
                        )
                    direct_requested_children = [
                        spec
                        for spec in prepared_specs
                        if spec.get("parent_request_path") == root_spec.get("request_path")
                    ]
                    if direct_requested_children:
                        raise OperationContractError(
                            "LIST_MERGE_CHILDREN_UNSUPPORTED",
                            "A pre-existing object-list member with requested descendants requires a dedicated list operation.",
                            details={
                                "list": descriptor.name,
                                "name": requested_name,
                            },
                        )
                    root_spec["preexisting_id"] = collisions[0].get("id")
                    existing_fields = _object_spec_return_fields(root_spec)
                    snapshot_platform = root_spec.get("platform")
                    snapshot_language = _localized_import_read_language(
                        root_spec.get("requested_language")
                    )
                    existing_options: dict[str, Any] = {
                        "return": existing_fields,
                    }
                    if snapshot_platform is not None:
                        existing_options["platform"] = snapshot_platform
                    if snapshot_language is not None:
                        existing_options["language"] = snapshot_language
                    existing_rows = _rows(
                        read(
                            OBJECT_GET_URI,
                            {"from": {"id": [collisions[0].get("id")]}},
                            existing_options,
                        )
                    )
                    if len(existing_rows) != 1:
                        raise OperationContractError(
                            "INVALID_READBACK",
                            "A merged object-list member must resolve exactly once.",
                        )
                    field_snapshots.append(
                        {
                            "object_id": collisions[0].get("id"),
                            "fields": existing_fields,
                            "platform": snapshot_platform,
                            "language": snapshot_language,
                            "rows": existing_rows,
                        }
                    )
            trusted[f"@{descriptor.name}"] = [
                _materialize_canonical_object_node(
                    root,
                    canonical_types=canonical_types,
                    resolved_references=resolved_references,
                    derived_properties=derived_child_properties,
                    materialized_imports=materialized_imports,
                )
                for root in descriptor.objects
            ]
            list_specs.extend(prepared_specs)

        snapshot_fields = _dedupe_fields(
            [
                *IDENTITY_RETURN_FIELDS,
                *(row["name"] for row in target_spec["properties"]),
                *(row["name"] for row in target_spec["references"]),
            ]
        )
        snapshot_args = {"from": {"id": [target.object]}}
        snapshot_options: dict[str, Any] = {"return": list(snapshot_fields)}
        if platform is not None:
            snapshot_options["platform"] = platform
        snapshot_result = read(OBJECT_GET_URI, snapshot_args, snapshot_options)
        snapshot_rows = _rows(snapshot_result)
        if len(snapshot_rows) != 1:
            raise OperationContractError("INVALID_READBACK", "object.set pre-state target must resolve exactly once.")
        field_snapshots.append(
            {
                "object_id": target.object,
                "fields": snapshot_fields,
                "platform": platform,
                "rows": snapshot_rows,
            }
        )
        target_spec["pre_state"] = snapshot_rows[0]
        target_spec["expected_parent_id"] = _parent_value(
            snapshot_rows[0].get("parent")
        )
        child_rows = _read_direct_children(target.object, fields=IDENTITY_RETURN_FIELDS, read=read)
        children_snapshots.append(
            {"object_id": target.object, "fields": list(IDENTITY_RETURN_FIELDS), "rows": child_rows}
        )
        children_snapshots.extend(merge_child_snapshots)
        target_spec["preexisting_children"] = child_rows
        target_spec["children_request_paths"] = [row["request_path"] for row in child_specs]
        target_spec["list_snapshots"] = target_list_snapshots
        target_spec["list_request_paths"] = [
            row["request_path"] for row in list_specs
        ]
        node_specs.append(target_spec)
        node_specs.extend(child_specs)
        node_specs.extend(list_specs)
        if len(node_specs) > DEFAULT_MAX_NODES:
            raise OperationContractError(
                "NODE_LIMIT_EXCEEDED",
                "object.set target and child nodes exceed the single bounded result budget.",
                details={"count": len(node_specs), "limit": DEFAULT_MAX_NODES},
            )
        dispatch_objects.append(trusted)

    has_imports = any(
        isinstance(spec.get("import"), Mapping) for spec in node_specs
    )
    for spec in node_specs:
        import_spec = spec.get("import")
        if not isinstance(import_spec, Mapping):
            continue
        for source in import_spec.get("sources", []):
            if not isinstance(source, Mapping):
                continue
            language = source.get("requested_language")
            if language_requires_live_project_validation(language):
                requested_languages.add(str(language))

    language_inventory: Mapping[str, Any] | None = None
    if requested_languages:
        language_inventory = _read_import_language_inventory(
            request.version,
            read=import_context_read,
        )
        available_languages = {
            str(row["name"])
            for row in language_inventory.get("languages", [])
            if isinstance(row, Mapping) and isinstance(row.get("name"), str)
        }
        unavailable = sorted(requested_languages - available_languages)
        if unavailable:
            raise OperationContractError(
                "UNKNOWN_PROJECT_LANGUAGE",
                "Every object.set Sound Voice language must exactly match the live Project language inventory.",
                details={
                    "requested": sorted(requested_languages),
                    "unavailable": unavailable,
                    "available": sorted(available_languages),
                },
            )
    originals_context: Mapping[str, Any] | None = None
    if has_imports:
        originals_context = _read_import_originals_context(
            request.version,
            read=import_context_read,
        )

    dispatch_args = {
        "objects": dispatch_objects,
        "onNameConflict": conflict,
        "listMode": global_list_mode,
        "autoAddToSourceControl": auto_add_to_source_control,
    }
    if global_platform is not None:
        dispatch_args["platform"] = global_platform
    preview = _closed_operation_preview(
        uri="ak.wwise.core.object.set",
        args=dispatch_args,
        options={"return": [*IDENTITY_RETURN_FIELDS, "owner"]},
        version=request.version,
        family="object-mutation",
        metadata={
            "closed_object_batch": True,
            "target_count": len(raw_objects),
            "node_count": len(node_specs),
            "platform": global_platform,
            "list_mode": global_list_mode,
            "auto_add_to_source_control": auto_add_to_source_control,
            "partial_success_is_failure": True,
        },
    )
    graph_guard = {
        "kind": "object-set-batch",
        "path_snapshots": path_snapshots,
        "children_snapshots": children_snapshots,
        "list_snapshots": list_snapshots,
        "list_subtree_snapshots": list_subtree_snapshots,
        "field_snapshots": field_snapshots,
    }
    import_guard = {
        "file_proofs": object_set_file_proofs,
        "originals_context": (
            dict(originals_context)
            if isinstance(originals_context, Mapping)
            else None
        ),
        "language_inventory": (
            dict(language_inventory)
            if isinstance(language_inventory, Mapping)
            else None
        ),
    }
    verification = {
        "kind": "object-set-batch",
        "version": request.version,
        "on_name_conflict": conflict,
        "list_names": sorted(
            {
                str(row.get("list_name"))
                for row in node_specs
                if isinstance(row.get("list_name"), str)
            }
        ),
        "replaced_list_subtree_rows": [
            dict(row)
            for snapshot in list_subtree_snapshots
            for row in snapshot.get("rows", [])
            if isinstance(row, Mapping)
        ],
        "nodes": node_specs,
    }
    cleanup = {
        "kind": "discard-owned-sandbox-or-restore-captured-fields",
        "automatic": False,
        "automatic_retry": False,
        "partial_success_possible": len(raw_objects) > 1,
    }
    state: dict[str, Any] = {
        "object_graph_guard": graph_guard,
        "object_set_nodes": node_specs,
    }
    if has_imports or requested_languages:
        state["import_guard"] = import_guard
    return preview, roles, state, verification, cleanup


def _prepare_object_set_linked(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    target = _resolve_identity(arguments.get("object"), role="object", read=read)
    field_name = _non_empty_string(arguments.get("property"), field="property")
    platform = _non_empty_string(arguments.get("platform"), field="platform")
    linked = arguments.get("linked")
    if not isinstance(linked, bool):
        raise OperationContractError("INVALID_ARGUMENT", "object.setLinked linked must be a JSON boolean.")
    info = _read_property_info(read, object_id=target.object, name=field_name)
    if info.supports.get("unlink") is not True:
        raise OperationContractError(
            "LINK_UNSUPPORTED",
            "Live property metadata does not support platform link/unlink for this field.",
            details={"field": field_name, "supports": dict(info.supports)},
        )
    before_result = read(
        OBJECT_IS_LINKED_URI,
        {"object": target.object, "property": field_name, "platform": platform},
        {},
    )
    before = before_result.get("linked") if isinstance(before_result, Mapping) else None
    if not isinstance(before, bool):
        raise OperationContractError(
            "INVALID_READBACK",
            "object.isLinked must return one linked boolean.",
            details={"result": before_result},
        )
    if before is linked:
        raise OperationContractError(
            "NO_OP",
            "object.setLinked already matches the requested link state.",
            details={"field": field_name, "platform": platform, "linked": linked},
        )
    dispatch_args = {
        "object": target.object,
        "property": field_name,
        "platform": platform,
        "linked": linked,
    }
    preview = _closed_operation_preview(
        uri=OBJECT_SET_LINKED_URI,
        args=dispatch_args,
        options={},
        version=request.version,
        family="property-reference",
        metadata={
            "closed_platform_link": True,
            "field_info": info.as_dict(),
            "linked_before": before,
        },
    )
    pre_state = {
        "linked_before": {
            "object_id": target.object,
            "property": field_name,
            "platform": platform,
            "linked": before,
        }
    }
    verification = {
        "kind": "object-linked-state",
        "version": request.version,
        "object_id": target.object,
        "property": field_name,
        "platform": platform,
        "expected_linked": linked,
    }
    cleanup = {
        "kind": "restore-platform-link-state",
        "automatic": False,
        "automatic_retry": False,
        "snapshot": dict(pre_state["linked_before"]),
    }
    return preview, {"object": target}, pre_state, verification, cleanup


def _prepare_object_set_rtpc(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    target = _resolve_identity(arguments.get("object"), role="object", read=read)
    control = _resolve_identity(arguments.get("control_input"), role="control_input", read=read)
    if not _is_rtpc_control_input(control.row.get("type")):
        raise OperationContractError(
            "INVALID_CONTROL_INPUT_TYPE",
            "RTPC ControlInput must resolve to a GameParameter, MIDI parameter, or Modulator object.",
            details={"control_input": control.as_dict()},
        )
    descriptor_payload = {
        "property": arguments.get("property"),
        "control_input": arguments.get("control_input"),
        "points": arguments.get("points"),
        **({"notes": arguments.get("notes")} if "notes" in arguments else {}),
    }
    try:
        descriptors = normalize_rtpc_descriptors(
            [descriptor_payload],
            request_path="$.arguments.rtpcs",
            max_rtpcs=1,
        )
    except ObjectOperationContractError as exc:
        raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
    descriptor = descriptors[0]
    info = _read_property_info(read, object_id=target.object, name=descriptor.property)
    rtpc_support = info.supports.get("rtpc")
    if not isinstance(rtpc_support, str) or rtpc_support.casefold() == "none":
        raise OperationContractError(
            "RTPC_UNSUPPORTED",
            "Live property metadata does not support an RTPC for this field.",
            details={"property": descriptor.property, "supports": dict(info.supports)},
        )
    mode = str(arguments.get("mode", "add_or_replace"))
    if mode not in {"add", "add_or_replace"}:
        raise OperationContractError(
            "INVALID_ARGUMENT",
            "object.setRTPC mode must be add or add_or_replace.",
            details={"mode": mode},
        )
    before_rows, rtpc_readbacks = _read_rtpc_rows_with_evidence(
        target.object,
        version=request.version,
        read=read,
    )
    matches = [
        row
        for row in before_rows
        if row.get("@PropertyName") == descriptor.property
        and _same_identity(
            _reference_identity(row.get("@ControlInput")),
            control.object,
        )
    ]
    if len(matches) > 1:
        raise OperationContractError(
            "AMBIGUOUS_RTPC",
            "More than one RTPC matches the requested property and ControlInput.",
            details={
                "property": descriptor.property,
                "control_input": control.object,
                "matches": matches,
            },
        )
    if mode == "add" and matches:
        raise OperationContractError(
            "TARGET_EXISTS",
            "object.setRTPC add requires the property/ControlInput pair to be absent.",
            details={"property": descriptor.property, "control_input": control.object},
        )

    action = "update" if matches else "add"
    if action == "add":
        if len(before_rows) >= RTPC_MAX_LIST_ROWS:
            raise OperationContractError(
                "RTPC_LIST_LIMIT_EXCEEDED",
                "Adding an RTPC would exceed the reviewed complete-list limit.",
                details={
                    "count": len(before_rows),
                    "limit": RTPC_MAX_LIST_ROWS,
                    "requested_action": action,
                },
            )
        dispatch_row = {
            "object": target.object,
            "@RTPC": [
                materialize_waapi_rtpc(
                    descriptor,
                    resolved_control_input=control.object,
                )
            ],
        }
    else:
        existing_id = matches[0].get("id")
        if not _valid_object_id(existing_id):
            raise OperationContractError(
                "INVALID_READBACK",
                "The matching RTPC row lacks a canonical GUID.",
                details={"row": matches[0]},
            )
        dispatch_row = {
            "object": existing_id,
            "@Curve": {
                "type": "Curve",
                "points": [point.as_dict() for point in descriptor.points],
            },
        }
        if descriptor.notes is not None:
            dispatch_row["notes"] = descriptor.notes

    dispatch_args = {
        "objects": [dispatch_row],
        "onNameConflict": "fail",
        "listMode": "append",
        "autoAddToSourceControl": False,
    }
    preview = _closed_operation_preview(
        uri=OBJECT_SET_URI,
        args=dispatch_args,
        options={"return": ["id", "name", "type", "path", "@RTPC", "@Curve"]},
        version=request.version,
        family="object-mutation",
        metadata={
            "closed_rtpc_operation": True,
            "action": action,
            "mode": mode,
            "property_info": info.as_dict(),
            "rtpc_support": rtpc_support,
            "raw_replace_all_allowed": False,
        },
    )
    rtpc_snapshot = {
        "object_id": target.object,
        "fields": list(RTPC_SNAPSHOT_FIELDS),
        "rows": before_rows,
        "readback_compatibility": [
            dict(item["compatibility_normalization"])
            for item in rtpc_readbacks
            if isinstance(item.get("compatibility_normalization"), Mapping)
        ],
    }
    verification = {
        "kind": "object-rtpc-state",
        "version": request.version,
        "object_id": target.object,
        "action": action,
        "existing_rtpc_id": matches[0].get("id") if matches else None,
        "property": descriptor.property,
        "control_input_id": control.object,
        "points": [point.as_dict() for point in descriptor.points],
        "notes_supplied": descriptor.notes is not None,
        "expected_notes": descriptor.notes,
        "before_rows": before_rows,
    }
    cleanup = {
        "kind": "restore-rtpc-snapshot-or-discard-owned-sandbox",
        "automatic": False,
        "automatic_retry": False,
        "action": action,
        "snapshot": rtpc_snapshot,
    }
    return (
        preview,
        {"object": target, "control_input": control},
        {"rtpc_snapshot": rtpc_snapshot},
        verification,
        cleanup,
    )


def _read_rtpc_rows_with_evidence(
    object_id: Any,
    *,
    version: str,
    read: ReadCall,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read one complete RTPC list through schema-valid object accessors.

    ``transform.select`` accepts hierarchy relationships, not object-list
    accessors.  Read the owner's ``@RTPC`` accessor first, then resolve the
    returned bounded GUID set in one ordinary ``from.id`` query.
    """

    owner_args = {"from": {"id": [object_id]}}
    owner_options = {"return": ["id", "@RTPC"]}
    owner_result = read(OBJECT_GET_URI, owner_args, owner_options)
    if not isinstance(owner_result, Mapping):
        raise OperationContractError(
            "INVALID_READBACK",
            "The RTPC owner readback must be an object.",
        )
    owner_rows = _rows(owner_result)
    if (
        len(owner_rows) != 1
        or not _same_identity(owner_rows[0].get("id"), object_id)
    ):
        raise OperationContractError(
            "INVALID_READBACK",
            "The RTPC owner must resolve exactly once by canonical ID.",
            details={"object_id": object_id, "rows": owner_rows},
        )
    owner_row = owner_rows[0]
    compatibility_normalization: dict[str, Any] | None = None
    if "@RTPC" not in owner_row:
        if (
            version in RTPC_EMPTY_OWNER_FIELD_OMISSION_VERSIONS
            and set(owner_row) == {"id"}
        ):
            raw_references: Any = []
            compatibility_normalization = {
                "kind": "missing-empty-object-list",
                "version": version,
                "field": "@RTPC",
                "observed_row_keys": ["id"],
                "normalized_value": [],
            }
        else:
            raise OperationContractError(
                "INVALID_READBACK",
                "The RTPC owner readback must contain an @RTPC array.",
                details={
                    "object_id": object_id,
                    "version": version,
                    "row": owner_row,
                },
            )
    else:
        raw_references = owner_row["@RTPC"]
    if not isinstance(raw_references, list):
        raise OperationContractError(
            "INVALID_READBACK",
            "The RTPC owner readback must contain an @RTPC array.",
            details={
                "object_id": object_id,
                "version": version,
                "row": owner_row,
            },
        )
    if len(raw_references) > RTPC_MAX_LIST_ROWS:
        raise OperationContractError(
            "RTPC_LIST_LIMIT_EXCEEDED",
            "The target RTPC list exceeds the reviewed snapshot limit.",
            details={
                "count": len(raw_references),
                "limit": RTPC_MAX_LIST_ROWS,
            },
        )
    reference_ids: list[Any] = []
    reference_keys: set[str] = set()
    for index, reference in enumerate(raw_references):
        reference_id = (
            reference.get("id")
            if isinstance(reference, Mapping)
            else None
        )
        if (
            not isinstance(reference_id, str)
            or not _PLUGIN_GUID.fullmatch(reference_id)
        ):
            raise OperationContractError(
                "INVALID_READBACK",
                "Every @RTPC list entry must expose a canonical GUID.",
                details={"index": index, "entry": reference},
            )
        key = _identity_key(reference_id)
        if key in reference_keys:
            raise OperationContractError(
                "INVALID_READBACK",
                "The @RTPC list contains a duplicate GUID.",
                details={"index": index, "id": reference_id},
            )
        reference_keys.add(key)
        reference_ids.append(reference_id)

    owner_readback = {
        "role": "object-rtpc-owner",
        "uri": OBJECT_GET_URI,
        "args": owner_args,
        "options": owner_options,
        "result": dict(owner_result),
    }
    if compatibility_normalization is not None:
        owner_readback["compatibility_normalization"] = (
            compatibility_normalization
        )
    readbacks = [owner_readback]
    if not reference_ids:
        return [], readbacks

    entries_args = {"from": {"id": reference_ids}}
    entries_options = {"return": list(RTPC_SNAPSHOT_FIELDS)}
    entries_result = read(OBJECT_GET_URI, entries_args, entries_options)
    if not isinstance(entries_result, Mapping):
        raise OperationContractError(
            "INVALID_READBACK",
            "The RTPC entry readback must be an object.",
        )
    unordered_rows = _rows(entries_result)
    rows_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(unordered_rows):
        row_id = row.get("id")
        if not isinstance(row_id, str) or not _PLUGIN_GUID.fullmatch(row_id):
            raise OperationContractError(
                "INVALID_READBACK",
                "Every RTPC detail row must expose a canonical GUID.",
                details={"index": index, "row": row},
            )
        key = _identity_key(row_id)
        if key in rows_by_id:
            raise OperationContractError(
                "INVALID_READBACK",
                "The RTPC detail readback contains a duplicate GUID.",
                details={"index": index, "id": row_id},
            )
        rows_by_id[key] = row
    if set(rows_by_id) != reference_keys:
        raise OperationContractError(
            "INVALID_READBACK",
            "The RTPC detail readback does not match the owner's complete @RTPC GUID list.",
            details={
                "owner_ids": reference_ids,
                "detail_ids": [row.get("id") for row in unordered_rows],
            },
        )
    rows = [rows_by_id[_identity_key(reference_id)] for reference_id in reference_ids]
    if not all(
        _valid_object_id(row.get("id"))
        and row.get("type") == "RTPC"
        and isinstance(row.get("@PropertyName"), str)
        and _valid_object_id(_reference_identity(row.get("@ControlInput")))
        and isinstance(row.get("@Curve"), Mapping)
        and isinstance(row["@Curve"].get("points"), list)
        for row in rows
    ):
        raise OperationContractError(
            "INVALID_READBACK",
            "The complete RTPC list snapshot contains an unrecognized row.",
            details={"rows": rows},
        )
    readbacks.append(
        {
            "role": "object-rtpc-entries",
            "uri": OBJECT_GET_URI,
            "args": entries_args,
            "options": entries_options,
            "result": dict(entries_result),
        }
    )
    return rows, readbacks


def _is_rtpc_control_input(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    token = re.sub(r"[^a-z0-9]", "", value.casefold())
    return token in RTPC_CONTROL_INPUT_TYPE_TOKENS


def _read_object_type_catalog(read: ReadCall) -> tuple[ObjectTypeMetadataRecord, ...]:
    result = read(OBJECT_GET_TYPES_URI, {}, {})
    try:
        records = parse_get_types_result(result)
    except SemanticValidationError as exc:
        raise OperationContractError("INVALID_READBACK", str(exc), details=exc.as_dict()) from exc
    if not records:
        raise OperationContractError("INVALID_READBACK", "object.getTypes returned no object types.")
    return records


def _resolve_object_type(
    requested: str,
    *,
    catalog: Sequence[ObjectTypeMetadataRecord],
) -> ObjectTypeMetadataRecord:
    token = _object_type_token(requested)
    matches = [row for row in catalog if token in {_object_type_token(row.name), _object_type_token(row.type)}]
    if len(matches) != 1:
        raise OperationContractError(
            "INVALID_OBJECT_TYPE",
            "Object type must resolve to exactly one live getTypes row.",
            details={"requested": requested, "matches": [row.as_dict() for row in matches]},
        )
    row = matches[0]
    forbidden = {
        "workunit",
        "effect",
        "source",
        "audiodevice",
        "metadata",
        "musicclip",
        "musicsequence",
        "stinger",
    }
    if _object_type_token(row.type) in forbidden or _object_type_token(row.name) in forbidden:
        raise OperationContractError(
            "UNSUPPORTED_OBJECT_TYPE",
            "The closed object-tree DSL does not create Work Units, plug-ins, Metadata, Clips, Sequences, or Stingers.",
            details={"requested": requested, "resolved": row.as_dict()},
        )
    return row


def _resolve_object_set_import_type(
    requested: str,
    *,
    catalog: Sequence[ObjectTypeMetadataRecord],
) -> ObjectTypeMetadataRecord:
    """Resolve one native import ``objectType`` without opening raw type input."""

    token = _object_type_token(requested)
    matches = [
        row
        for row in catalog
        if token == _object_type_token(row.name)
    ]
    if len(matches) != 1:
        raise OperationContractError(
            "INVALID_IMPORT_OBJECT_TYPE",
            "object.set import object_type must resolve to exactly one live metadata name.",
            details={
                "requested": requested,
                "matches": [row.as_dict() for row in matches],
            },
        )
    row = matches[0]
    return row


def _prepare_object_node_specs(
    nodes: Sequence[ObjectNodeDescriptor],
    *,
    version: str,
    type_catalog: Sequence[ObjectTypeMetadataRecord],
    read: ReadCall,
    roles: dict[str, ResolvedObject],
    canonical_types: dict[str, str],
    resolved_references: dict[str, Any],
    derived_properties: dict[str, dict[str, Any]],
    identity_cache: dict[bytes, ResolvedObject],
    property_info_cache: dict[
        tuple[str, str, str],
        PropertyInfoMetadataRecord,
    ],
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for node in nodes:
        requested_type_token = _object_type_token(node.type)
        uses_2025_actor_mixer_alias = (
            version == "2025.1" and requested_type_token == "actormixer"
        )
        metadata_type = (
            "PropertyContainer"
            if uses_2025_actor_mixer_alias
            else node.type
        )
        type_info = _resolve_object_type(metadata_type, catalog=type_catalog)
        if (
            uses_2025_actor_mixer_alias
            and _object_type_token(type_info.name) != "propertycontainer"
        ):
            raise OperationContractError(
                "INVALID_OBJECT_TYPE",
                "Wwise 2025.1 ActorMixer must resolve through the live PropertyContainer metadata row.",
                details={
                    "requested": node.type,
                    "resolved": type_info.as_dict(),
                },
            )
        # ``object.getTypes`` reports a broad base class in ``type`` (for
        # example, 2022.1 reports ``WObject`` for Sound, ActorMixer, and
        # RandomSequenceContainer).  ``object.create`` instead requires the
        # concrete creation token in the uniquely resolved metadata ``name``.
        canonical_type = (
            "ActorMixer"
            if uses_2025_actor_mixer_alias
            else type_info.name
        )
        canonical_types[node.request_path] = canonical_type
        spec: dict[str, Any] = {
            "request_path": node.request_path,
            "parent_request_path": node.parent_request_path,
            "existing_target": False,
            "requested_name": node.name,
            "requested_type": node.type,
            "canonical_type": canonical_type,
            "class_id": type_info.class_id,
            "notes_supplied": node.notes is not None,
            "requested_notes": node.notes,
            "properties": [],
            "references": [],
        }
        if node.language is not None:
            if _object_type_token(type_info.name) != "sound":
                raise OperationContractError(
                    "INVALID_LANGUAGE_TARGET",
                    "object.set language is meaningful only for a newly created Sound Voice.",
                    details={
                        "request_path": node.request_path,
                        "canonical_type": type_info.name,
                    },
                )
            spec["requested_language"] = node.language
        if node.platform is not None:
            spec["platform"] = node.platform
        if node.import_arg is not None:
            spec["import_requested"] = True
        property_info_by_name: dict[str, PropertyInfoMetadataRecord] = {}
        node_derived_properties: dict[str, Any] = {}
        for descriptor in node.properties:
            info = _read_property_info_cached(
                read,
                cache=property_info_cache,
                class_id=type_info.class_id,
                name=descriptor.name,
            )
            _require_object_property_value(info, descriptor.value)
            property_info_by_name[descriptor.name.casefold()] = info
            spec["properties"].append(
                {"name": descriptor.name, "value": descriptor.value, "metadata_type": info.type}
            )
        for descriptor in node.references:
            info = _read_property_info_cached(
                read,
                cache=property_info_cache,
                class_id=type_info.class_id,
                name=descriptor.name,
            )
            _require_object_reference_metadata(info)
            activation_properties = _apply_reference_activation_dependencies(
                info,
                read=read,
                class_id=type_info.class_id,
                property_specs=spec["properties"],
                property_info_by_name=property_info_by_name,
                derived_properties=node_derived_properties,
                request_path=descriptor.request_path,
                property_info_cache=property_info_cache,
            )
            resolved = _resolve_identity(
                descriptor.target.as_dict(),
                role=descriptor.request_path,
                read=read,
                identity_cache=identity_cache,
            )
            _require_reference_target_allowed(info, resolved)
            roles[descriptor.request_path] = resolved
            resolved_references[descriptor.request_path] = resolved.object
            reference_spec = {"name": descriptor.name, "target_id": resolved.object}
            if activation_properties:
                reference_spec["activation_properties"] = list(activation_properties)
            spec["references"].append(reference_spec)
        if node_derived_properties:
            derived_properties[node.request_path] = node_derived_properties
        specs.append(spec)
    return specs


def _prepare_object_set_import(
    descriptor: ObjectImportDescriptor,
    *,
    canonical_type: Any,
    type_catalog: Sequence[ObjectTypeMetadataRecord],
    file_proofs: list[dict[str, Any]],
    default_auto_add_to_source_control: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind one reviewed native ``importArg`` to immutable source proofs."""

    if not isinstance(canonical_type, str) or not canonical_type:
        raise OperationContractError(
            "UNSUPPORTED_IMPORT_TARGET",
            "object.set import target type must come from the live-resolved object or node.",
            details={
                "request_path": descriptor.request_path,
                "canonical_type": canonical_type,
            },
        )
    dispatch_files: list[dict[str, Any]] = []
    source_specs: list[dict[str, Any]] = []
    source_keys: set[tuple[tuple[str, ...], str, str, str]] = set()
    for index, item in enumerate(descriptor.files):
        field = item.request_path
        dispatch_row: dict[str, Any] = {}
        if item.audio_file is not None:
            try:
                proof = import_regular_file_proof(
                    item.audio_file,
                    field=f"{field}.audio_file",
                )
                validate_import_media_extension(
                    str(proof["path"]),
                    field=f"{field}.audio_file",
                )
            except ImportContractError as exc:
                raise OperationContractError(
                    exc.error_code,
                    str(exc),
                    details=exc.details,
                ) from exc
            source_identity = (
                "file",
                *host_path_comparison_key(proof["path"]),
            )
            dispatch_row["audioFile"] = proof["path"]
            source = {
                "index": index,
                "kind": "regular_file",
                **proof,
            }
            expected_filename = _import_path_leaf_name(proof["path"])
            file_proofs.append(
                {
                    "field": f"{field}.audio_file",
                    "proof": dict(proof),
                }
            )
        else:
            try:
                encoded, inline_proof = normalize_inline_audio_file(
                    item.audio_file_base64,
                    field=f"{field}.audio_file_base64",
                )
            except ImportContractError as exc:
                raise OperationContractError(
                    exc.error_code,
                    str(exc),
                    details=exc.details,
                ) from exc
            source_identity = (
                "inline",
                str(inline_proof["relative_path"]).casefold(),
                str(inline_proof["sha256"]),
            )
            dispatch_row["audioFileBase64"] = encoded
            source = {
                "index": index,
                **inline_proof,
            }
            expected_filename = _import_path_leaf_name(
                inline_proof["relative_path"]
            )
        if not expected_filename:
            raise OperationContractError(
                "INVALID_IMPORT_SOURCE",
                "object.set import source must have a sealed file name.",
                details={"request_path": field},
            )
        source["expected_original_filename"] = expected_filename
        source["expected_object_name"] = Path(expected_filename).stem
        if item.originals_subfolder is not None:
            try:
                subfolder = normalize_originals_subfolder(
                    item.originals_subfolder,
                    field=f"{field}.originals_subfolder",
                )
            except ImportContractError as exc:
                raise OperationContractError(
                    exc.error_code,
                    str(exc),
                    details=exc.details,
                ) from exc
            dispatch_row["originalsSubFolder"] = subfolder
            source["requested_originals_subfolder"] = subfolder
        if item.language is not None:
            dispatch_row["language"] = item.language
            source["requested_language"] = item.language
        if item.object_type is not None:
            type_info = _resolve_object_set_import_type(
                item.object_type,
                catalog=type_catalog,
            )
            dispatch_row["objectType"] = type_info.name
            source["requested_object_type"] = type_info.name
            source["requested_object_type_class_id"] = type_info.class_id
        source_key = (
            source_identity,
            str(dispatch_row.get("language", "")).casefold(),
            str(dispatch_row.get("objectType", "")).casefold(),
            str(dispatch_row.get("originalsSubFolder", "")).casefold(),
        )
        if source_key in source_keys:
            raise OperationContractError(
                "DUPLICATE_IMPORT_SOURCE",
                "One object.set import must not repeat the same media source and destination semantics.",
                details={"request_path": descriptor.request_path, "index": index},
            )
        source_keys.add(source_key)
        dispatch_files.append(dispatch_row)
        source_specs.append(source)

    effective_auto_add = (
        descriptor.auto_add_to_source_control
        if descriptor.auto_add_to_source_control is not None
        else default_auto_add_to_source_control
    )
    dispatch: dict[str, Any] = {
        "files": dispatch_files,
        "autoAddToSourceControl": effective_auto_add,
    }
    return dispatch, {
        "sources": source_specs,
        "canonical_type": canonical_type,
        "readback_contract": (
            "copied Originals paths are located from the imported target and "
            "its descendants, then each copied file is hashed against its "
            "immutable source proof"
        ),
    }


def _read_property_info(
    read: ReadCall,
    *,
    name: str,
    object_id: Any | None = None,
    class_id: int | None = None,
) -> PropertyInfoMetadataRecord:
    args: dict[str, Any] = {"property": name}
    if object_id is not None:
        args["object"] = object_id
    elif class_id is not None:
        args["classId"] = class_id
    else:  # pragma: no cover - internal invariant
        raise AssertionError("object_id or class_id is required")
    try:
        info = parse_get_property_info_result(read(GET_PROPERTY_INFO_URI, args, {}))
    except SemanticValidationError as exc:
        raise OperationContractError("INVALID_METADATA", str(exc), details=exc.as_dict()) from exc
    if info.name != name:
        raise OperationContractError(
            "INVALID_METADATA",
            "getPropertyInfo returned metadata for a different field.",
            details={"requested": name, "actual": info.name},
        )
    return info


def _read_property_info_cached(
    read: ReadCall,
    *,
    cache: dict[tuple[str, str, str], PropertyInfoMetadataRecord],
    name: str,
    object_id: Any | None = None,
    class_id: int | None = None,
) -> PropertyInfoMetadataRecord:
    """Read property metadata once per exact prepare-local object/class scope."""

    if (object_id is None) == (class_id is None):  # pragma: no cover - internal invariant.
        raise AssertionError("object_id or class_id must be supplied exclusively")
    if object_id is not None:
        scope_kind = "object"
        scope_value = _identity_key(object_id)
    else:
        if isinstance(class_id, bool) or not isinstance(class_id, int):
            raise OperationContractError(
                "INVALID_METADATA",
                "A class-scoped property metadata cache key requires one integer classId.",
                details={"class_id": class_id, "property": name},
            )
        scope_kind = "class"
        scope_value = str(class_id)
    cache_key = (scope_kind, scope_value, name.casefold())
    cached = cache.get(cache_key)
    if cached is not None:
        if cached.name != name:
            raise OperationContractError(
                "INVALID_METADATA",
                "Cached property metadata does not match the exact requested field token.",
                details={"requested": name, "actual": cached.name},
            )
        return cached
    info = _read_property_info(
        read,
        name=name,
        object_id=object_id,
        class_id=class_id,
    )
    cache[cache_key] = info
    return info


def _require_platform_field_enabled(
    read: ReadCall,
    *,
    object_id: Any,
    field_name: str,
    platform: str,
) -> None:
    result = read(
        OBJECT_IS_PROPERTY_ENABLED_URI,
        {"object": object_id, "property": field_name, "platform": platform},
        {},
    )
    enabled = result.get("return") if isinstance(result, Mapping) else None
    if not isinstance(enabled, bool):
        raise OperationContractError(
            "INVALID_READBACK",
            "isPropertyEnabled must return one boolean for an explicit platform.",
            details={"field": field_name, "platform": platform, "result": result},
        )
    if not enabled:
        raise OperationContractError(
            "PROPERTY_DISABLED_FOR_PLATFORM",
            "The requested property or reference is disabled for the explicit platform.",
            details={"field": field_name, "platform": platform},
        )


def _require_object_property_value(metadata: PropertyInfoMetadataRecord, value: Any) -> None:
    property_type = metadata.type.casefold()
    if property_type in {"real32", "real64", "float", "double"}:
        valid = _is_finite_waapi_number(value)
    elif property_type in {"int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "integer"}:
        valid = not isinstance(value, bool) and isinstance(value, int)
    elif property_type in {"bool", "boolean"}:
        valid = isinstance(value, bool)
    elif property_type in {"string", "cstring"}:
        valid = isinstance(value, str)
    else:
        valid = False
    if not valid:
        raise OperationContractError(
            "INVALID_PROPERTY_VALUE",
            "Property value does not match live getPropertyInfo metadata.",
            details={"property": metadata.name, "metadata_type": metadata.type, "value": value},
        )
    restriction_type = metadata.restriction.get("type")
    if restriction_type == "range" and isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = metadata.restriction.get("min")
        maximum = metadata.restriction.get("max")
        if isinstance(minimum, (int, float)) and value < minimum or isinstance(maximum, (int, float)) and value > maximum:
            raise OperationContractError(
                "PROPERTY_VALUE_OUT_OF_RANGE",
                "Property value is outside the live metadata range.",
                details={"property": metadata.name, "value": value, "restriction": dict(metadata.restriction)},
            )
    if restriction_type == "enum":
        rows = metadata.restriction.get("values")
        allowed = [row.get("value") for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
        if allowed and value not in allowed:
            raise OperationContractError(
                "PROPERTY_VALUE_NOT_ALLOWED",
                "Property value is not one of the live metadata enum values.",
                details={"property": metadata.name, "value": value, "allowed": allowed},
            )


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


def _require_object_reference_metadata(metadata: PropertyInfoMetadataRecord) -> None:
    restriction_type = metadata.restriction.get("type")
    reference = metadata.type.casefold() in {"reference", "objectreference"} or restriction_type == "reference"
    if not reference:
        raise OperationContractError(
            "INVALID_REFERENCE",
            "Requested reference name does not expose reference metadata.",
            details={"reference": metadata.name, "metadata_type": metadata.type},
        )
    restrictions = metadata.restriction.get("restrictions")
    if isinstance(restrictions, list) and any(
        isinstance(row, Mapping) and row.get("childOfReference") is not None for row in restrictions
    ):
        raise OperationContractError(
            "CONSTRAINED_REFERENCE_BOUNDARY",
            "References constrained by another reference require a dedicated ordered operation.",
            details={"reference": metadata.name, "restriction": dict(metadata.restriction)},
        )


def _apply_reference_activation_dependencies(
    metadata: PropertyInfoMetadataRecord,
    *,
    read: ReadCall,
    property_specs: list[dict[str, Any]],
    property_info_by_name: dict[str, PropertyInfoMetadataRecord],
    derived_properties: dict[str, Any],
    request_path: str,
    object_id: Any | None = None,
    class_id: int | None = None,
    property_info_cache: dict[
        tuple[str, str, str],
        PropertyInfoMetadataRecord,
    ] | None = None,
) -> tuple[str, ...]:
    """Materialize the one closed live-metadata dependency shape we support.

    Wwise references such as ``OutputBus`` can be accepted syntactically while
    remaining inherited unless a same-object Boolean override is enabled.  The
    dependency is therefore part of the reviewed dispatch, field snapshot, and
    operation-specific verification rather than a hidden follow-up call.
    """

    if (object_id is None) == (class_id is None):  # pragma: no cover - internal invariant.
        raise AssertionError("object_id or class_id must be supplied exclusively")

    activation_names: list[str] = []
    seen_dependencies: set[str] = set()
    for index, dependency in enumerate(metadata.dependencies):
        fields = set(dependency)
        if fields != _REFERENCE_ACTIVATION_DEPENDENCY_FIELDS:
            raise OperationContractError(
                "INVALID_METADATA",
                "Reference dependency metadata does not match the closed activation shape.",
                details={
                    "reference": metadata.name,
                    "request_path": request_path,
                    "dependency_index": index,
                    "fields": sorted(str(field) for field in fields),
                    "expected_fields": sorted(_REFERENCE_ACTIVATION_DEPENDENCY_FIELDS),
                },
            )

        action = dependency.get("action")
        context = dependency.get("context")
        property_name = dependency.get("property")
        dependency_type = dependency.get("type")
        if not all(
            isinstance(value, str)
            for value in (action, context, property_name, dependency_type)
        ):
            raise OperationContractError(
                "INVALID_METADATA",
                "Reference dependency metadata fields must all be strings.",
                details={
                    "reference": metadata.name,
                    "request_path": request_path,
                    "dependency_index": index,
                },
            )
        if (
            not property_name
            or property_name.startswith("@")
            or _REFERENCE_ACTIVATION_FIELD_NAME.fullmatch(property_name) is None
            or property_name.casefold() == metadata.name.casefold()
        ):
            raise OperationContractError(
                "INVALID_METADATA",
                "Reference dependency metadata names an invalid activation property.",
                details={
                    "reference": metadata.name,
                    "request_path": request_path,
                    "dependency_index": index,
                    "property": property_name,
                },
            )
        if not (
            dependency_type == "override"
            and action == "Enable"
            and context == "Self"
        ):
            raise OperationContractError(
                "CONSTRAINED_REFERENCE_BOUNDARY",
                "Only a same-object Boolean override that enables the reference is supported.",
                details={
                    "reference": metadata.name,
                    "request_path": request_path,
                    "dependency_index": index,
                    "dependency": {
                        "type": dependency_type,
                        "action": action,
                        "context": context,
                        "property": property_name,
                    },
                },
            )

        property_key = property_name.casefold()
        if property_key in seen_dependencies:
            raise OperationContractError(
                "INVALID_METADATA",
                "Reference dependency metadata repeats an activation property.",
                details={
                    "reference": metadata.name,
                    "request_path": request_path,
                    "property": property_name,
                },
            )
        seen_dependencies.add(property_key)

        property_info = property_info_by_name.get(property_key)
        if property_info is None:
            property_info = (
                _read_property_info_cached(
                    read,
                    cache=property_info_cache,
                    name=property_name,
                    object_id=object_id,
                    class_id=class_id,
                )
                if property_info_cache is not None
                else _read_property_info(
                    read,
                    name=property_name,
                    object_id=object_id,
                    class_id=class_id,
                )
            )
            property_info_by_name[property_key] = property_info
        if (
            property_info.name != property_name
            or property_info.type.casefold() not in {"bool", "boolean"}
        ):
            raise OperationContractError(
                "INVALID_METADATA",
                "A reference activation dependency must resolve to the exact Boolean property.",
                details={
                    "reference": metadata.name,
                    "request_path": request_path,
                    "property": property_name,
                    "metadata_name": property_info.name,
                    "metadata_type": property_info.type,
                },
            )
        _require_object_property_value(property_info, True)

        matching_specs = [
            spec
            for spec in property_specs
            if isinstance(spec.get("name"), str)
            and str(spec["name"]).casefold() == property_key
        ]
        if len(matching_specs) > 1:  # pragma: no cover - normalized descriptors are unique.
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Reference activation property specifications are not unique.",
                details={"request_path": request_path, "property": property_name},
            )
        if matching_specs:
            property_spec = matching_specs[0]
            if property_spec.get("value") is not True:
                raise OperationContractError(
                    "REFERENCE_DEPENDENCY_CONFLICT",
                    "An explicitly disabled override conflicts with the requested reference.",
                    details={
                        "reference": metadata.name,
                        "request_path": request_path,
                        "property": property_name,
                        "value": property_spec.get("value"),
                    },
                )
        else:
            property_spec = {
                "name": property_info.name,
                "value": True,
                "metadata_type": property_info.type,
                "derived": True,
            }
            property_specs.append(property_spec)
            derived_properties[property_info.name] = True

        activators = property_spec.setdefault("activates_references", [])
        if not isinstance(activators, list):  # pragma: no cover - internal invariant.
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Reference activation provenance is malformed.",
                details={"request_path": request_path, "property": property_name},
            )
        if metadata.name not in activators:
            activators.append(metadata.name)
        activation_names.append(property_info.name)

    return tuple(activation_names)


def _materialize_canonical_object_node(
    node: ObjectNodeDescriptor,
    *,
    canonical_types: Mapping[str, str],
    resolved_references: Mapping[str, Any],
    derived_properties: Mapping[str, Mapping[str, Any]],
    materialized_imports: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        subtree_import_paths = {
            item.request_path
            for item in flatten_request_nodes((node,))
            if item.import_arg is not None
        }
        import_bindings = {
            path: dict(value)
            for path, value in dict(materialized_imports or {}).items()
            if path in subtree_import_paths
        }
        payload = materialize_waapi_node(
            node,
            resolved_references=resolved_references,
            materialized_imports=import_bindings,
        )
    except ObjectOperationContractError as exc:
        raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc

    def apply(current: ObjectNodeDescriptor, row: dict[str, Any]) -> None:
        row["type"] = canonical_types[current.request_path]
        for property_name, value in derived_properties.get(current.request_path, {}).items():
            if (
                not isinstance(property_name, str)
                or _REFERENCE_ACTIVATION_FIELD_NAME.fullmatch(property_name) is None
                or value is not True
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Derived reference activation properties are malformed.",
                    details={"request_path": current.request_path},
                )
            key = f"@{property_name}"
            if key in row and row[key] is not True:
                raise OperationContractError(
                    "REFERENCE_DEPENDENCY_CONFLICT",
                    "A derived reference activation conflicts with an explicit property.",
                    details={
                        "request_path": current.request_path,
                        "property": property_name,
                        "value": row[key],
                    },
                )
            row[key] = True
        for child, child_row in zip(current.children, row.get("children", []), strict=True):
            apply(child, child_row)

    apply(node, payload)
    return payload


def _object_type_token(value: Any) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _object_type_matches(actual: Any, spec: Mapping[str, Any]) -> bool:
    token = _object_type_token(actual)
    return token in {
        _object_type_token(spec.get("requested_type")),
        _object_type_token(spec.get("canonical_type")),
        "propertycontainer" if _object_type_token(spec.get("canonical_type")) == "actormixer" else "",
    }


def _child_path(parent_path: Any, name: Any, *, field: str) -> str:
    if not isinstance(parent_path, str) or not parent_path.startswith("\\"):
        raise OperationContractError("INVALID_READBACK", f"{field} must be an absolute Wwise object path.")
    if not isinstance(name, str) or not name:
        raise OperationContractError("INVALID_ARGUMENT", "Object node name must be non-empty.")
    return parent_path.rstrip("\\") + "\\" + name


def _absolute_live_object_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("\\"):
        raise OperationContractError(
            "INVALID_READBACK",
            f"{field} must be an absolute Wwise object path.",
            details={"field": field, "actual": value},
        )
    return value


def _is_strict_descendant_object_path(path: str, owned_root_path: str) -> bool:
    root = owned_root_path.rstrip("\\")
    if not root:
        return path != "\\" and path.startswith("\\")
    return path != root and path.startswith(root + "\\")


def _request_node_expected_path(
    base_parent_path: Any,
    spec: Mapping[str, Any],
    all_specs: Sequence[Mapping[str, Any]],
    *,
    root_request_path: str | None = None,
) -> str:
    # ``root_request_path`` binds object.set child roots to a synthetic
    # bind child roots to a synthetic existing-target request path.
    by_path = {row.get("request_path"): row for row in all_specs}
    names: list[str] = [str(spec.get("requested_name"))]
    parent_request = spec.get("parent_request_path")
    while parent_request is not None and parent_request in by_path:
        parent = by_path[parent_request]
        names.append(str(parent.get("requested_name")))
        parent_request = parent.get("parent_request_path")
    if parent_request is not None and root_request_path is not None and parent_request != root_request_path:
        raise OperationContractError("INVALID_PREVIEW", "Object node request topology has an unknown parent path.")
    if not isinstance(base_parent_path, str):
        raise OperationContractError("INVALID_READBACK", "Object parent path must be a string.")
    return base_parent_path.rstrip("\\") + "\\" + "\\".join(reversed(names))


def _localized_import_read_language(value: Any) -> str | None:
    """Return the explicit non-SFX language that selects localized accessors."""

    if isinstance(value, str) and value.casefold() != "sfx":
        return value
    return None


def _import_object_get_options(
    fields: Sequence[str],
    *,
    language: str | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    options: dict[str, Any] = {"return": list(fields)}
    if language is not None:
        options["language"] = language
    if platform is not None:
        options["platform"] = platform
    return options


def _read_object_path_rows(
    path: str,
    *,
    fields: Sequence[str],
    read: ReadCall,
    language: str | None = None,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    return _rows(
        read(
            OBJECT_GET_URI,
            {"from": {"path": [path]}},
            _import_object_get_options(
                fields,
                language=language,
                platform=platform,
            ),
        )
    )


def _read_object_id_rows(object_id: Any, *, fields: Sequence[str], read: ReadCall) -> list[dict[str, Any]]:
    return _rows(read(OBJECT_GET_URI, {"from": {"id": [object_id]}}, {"return": list(fields)}))


def _bounded_multi_identity_read(
    object_ids: Sequence[Any],
    *,
    fields: Sequence[str],
    read: ReadCall,
    context: str,
    platform: str | None = None,
) -> dict[str, Any]:
    """Read one unique bounded GUID set and classify every returned row."""

    unique_ids: list[Any] = []
    expected_by_key: dict[str, Any] = {}
    for object_id in object_ids:
        key = _identity_key(object_id)
        if key not in expected_by_key:
            expected_by_key[key] = object_id
            unique_ids.append(object_id)
    if not unique_ids:
        return {
            "args": {"from": {"id": []}},
            "options": _import_object_get_options(
                _dedupe_fields(["id", *fields]),
                platform=platform,
            ),
            "result": {"return": []},
            "rows_by_key": {},
            "missing_ids": [],
            "duplicate_ids": [],
            "extra_rows": [],
            "malformed_rows": [],
            "exact": True,
        }
    if len(unique_ids) > MULTI_IDENTITY_READ_MAX_IDS:
        raise OperationContractError(
            "IDENTITY_READ_LIMIT_EXCEEDED",
            f"{context} exceeds the bounded multi-identity read limit.",
            details={
                "count": len(unique_ids),
                "limit": MULTI_IDENTITY_READ_MAX_IDS,
            },
        )

    args = {"from": {"id": unique_ids}}
    options = _import_object_get_options(
        _dedupe_fields(["id", *fields]),
        platform=platform,
    )
    result = read(OBJECT_GET_URI, args, options)
    if not isinstance(result, Mapping):
        raise OperationContractError(
            "INVALID_READBACK",
            f"{context} readback must be a JSON object.",
            details={"actual_type": type(result).__name__},
        )
    rows = _rows(result)
    if len(rows) > MULTI_IDENTITY_READ_MAX_IDS:
        raise OperationContractError(
            "INVALID_READBACK",
            f"{context} returned more rows than the bounded identity-read limit.",
            details={
                "count": len(rows),
                "limit": MULTI_IDENTITY_READ_MAX_IDS,
            },
        )

    rows_by_key: dict[str, list[dict[str, Any]]] = {}
    malformed_rows: list[dict[str, Any]] = []
    extra_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        object_id = row.get("id")
        if not _valid_object_id(object_id):
            malformed_rows.append({"index": index, "row": row})
            continue
        key = _identity_key(object_id)
        rows_by_key.setdefault(key, []).append(row)
        if key not in expected_by_key:
            extra_rows.append({"index": index, "row": row})

    missing_ids = [
        object_id
        for key, object_id in expected_by_key.items()
        if key not in rows_by_key
    ]
    duplicate_ids = [
        expected_by_key.get(key, values[0].get("id"))
        for key, values in rows_by_key.items()
        if len(values) != 1
    ]
    exact = not (missing_ids or duplicate_ids or extra_rows or malformed_rows)
    return {
        "args": args,
        "options": options,
        "result": dict(result),
        "rows_by_key": rows_by_key,
        "missing_ids": missing_ids,
        "duplicate_ids": duplicate_ids,
        "extra_rows": extra_rows,
        "malformed_rows": malformed_rows,
        "exact": exact,
    }


def _read_object_list_rows_with_evidence(
    object_id: Any,
    list_name: str,
    *,
    fields: Sequence[str],
    read: ReadCall,
    platform: str | None = None,
    context: str,
    allow_missing_empty: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve one object list without using an invalid transform selector.

    Legacy ``object.get.transform.select`` supports hierarchy relationships,
    not dynamic object-list accessors.  Read the owner's ``@List`` accessor,
    validate its complete bounded GUID set, then resolve those GUIDs in one
    ordinary multi-ID read.
    """

    try:
        canonical_name = normalize_object_list_name(
            list_name,
            request_path="object_list.name",
        )
    except ObjectOperationContractError as exc:
        raise OperationContractError(
            exc.error_code,
            str(exc),
            details=exc.details,
        ) from exc

    list_field = f"@{canonical_name}"
    owner_args = {"from": {"id": [object_id]}}
    owner_options = _import_object_get_options(
        ("id", list_field),
        platform=platform,
    )
    owner_result = read(OBJECT_GET_URI, owner_args, owner_options)
    if not isinstance(owner_result, Mapping):
        raise OperationContractError(
            "INVALID_READBACK",
            f"{context} owner readback must be a JSON object.",
        )
    owner_rows = _rows(owner_result)
    if (
        len(owner_rows) != 1
        or not _same_identity(owner_rows[0].get("id"), object_id)
    ):
        raise OperationContractError(
            "INVALID_READBACK",
            f"{context} owner must resolve exactly once by canonical ID.",
            details={"object_id": object_id, "rows": owner_rows},
        )
    owner_row = owner_rows[0]
    compatibility_normalization: dict[str, Any] | None = None
    if list_field not in owner_row:
        if allow_missing_empty and set(owner_row) == {"id"}:
            raw_references: Any = []
            compatibility_normalization = {
                "kind": "missing-empty-object-list",
                "field": list_field,
                "observed_row_keys": ["id"],
                "normalized_value": [],
            }
        else:
            raise OperationContractError(
                "INVALID_READBACK",
                f"{context} owner readback must contain a {list_field} array.",
                details={"object_id": object_id, "row": owner_row},
            )
    else:
        raw_references = owner_row[list_field]
    if not isinstance(raw_references, list):
        raise OperationContractError(
            "INVALID_READBACK",
            f"{context} owner readback must contain a {list_field} array.",
            details={"object_id": object_id, "row": owner_row},
        )
    if len(raw_references) > OBJECT_LIST_MAX_SUBTREE_NODES:
        raise OperationContractError(
            "LIST_SNAPSHOT_LIMIT_EXCEEDED",
            f"{context} exceeds the complete object-list snapshot limit.",
            details={
                "list": canonical_name,
                "count": len(raw_references),
                "limit": OBJECT_LIST_MAX_SUBTREE_NODES,
            },
        )

    reference_ids: list[str] = []
    reference_keys: set[str] = set()
    for index, reference in enumerate(raw_references):
        reference_id = (
            reference.get("id") if isinstance(reference, Mapping) else None
        )
        if (
            not isinstance(reference_id, str)
            or not _PLUGIN_GUID.fullmatch(reference_id)
        ):
            raise OperationContractError(
                "INVALID_READBACK",
                f"Every {list_field} member must expose a canonical Wwise GUID.",
                details={"index": index, "entry": reference},
            )
        key = _identity_key(reference_id)
        if key in reference_keys:
            raise OperationContractError(
                "INVALID_READBACK",
                f"{context} contains a duplicate member GUID.",
                details={"list": canonical_name, "index": index, "id": reference_id},
            )
        reference_keys.add(key)
        reference_ids.append(reference_id)

    owner_readback: dict[str, Any] = {
        "role": f"{context}-owner",
        "uri": OBJECT_GET_URI,
        "args": owner_args,
        "options": owner_options,
        "result": dict(owner_result),
    }
    if compatibility_normalization is not None:
        owner_readback["compatibility_normalization"] = (
            compatibility_normalization
        )
    readbacks = [owner_readback]
    if not reference_ids:
        return [], readbacks

    detail_read = _bounded_multi_identity_read(
        reference_ids,
        fields=fields,
        read=read,
        context=f"{context} detail",
        platform=platform,
    )
    readbacks.append(
        {
            "role": f"{context}-members",
            "uri": OBJECT_GET_URI,
            "args": detail_read["args"],
            "options": detail_read["options"],
            "result": detail_read["result"],
        }
    )
    if not detail_read["exact"]:
        raise OperationContractError(
            "INVALID_READBACK",
            f"{context} detail readback does not exactly match the owner's complete GUID list.",
            details={
                "list": canonical_name,
                "owner_ids": reference_ids,
                "missing_ids": detail_read["missing_ids"],
                "duplicate_ids": detail_read["duplicate_ids"],
                "extra_rows": detail_read["extra_rows"],
                "malformed_rows": detail_read["malformed_rows"],
            },
        )
    rows_by_key = detail_read["rows_by_key"]
    rows = [
        rows_by_key[_identity_key(reference_id)][0]
        for reference_id in reference_ids
    ]
    if not all(
        isinstance(row.get("id"), str)
        and _PLUGIN_GUID.fullmatch(row["id"])
        for row in rows
    ):
        raise OperationContractError(
            "INVALID_READBACK",
            f"Every {list_field} detail row must expose a canonical Wwise GUID.",
            details={"rows": rows},
        )
    return rows, readbacks


def _read_direct_children(object_id: Any, *, fields: Sequence[str], read: ReadCall) -> list[dict[str, Any]]:
    return _rows(
        read(
            OBJECT_GET_URI,
            {"from": {"id": [object_id]}, "transform": [{"select": ["children"]}]},
            {"return": list(fields)},
        )
    )


def _read_object_list(
    object_id: Any,
    list_name: str,
    *,
    fields: Sequence[str],
    read: ReadCall,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    rows, _readbacks = _read_object_list_rows_with_evidence(
        object_id,
        list_name,
        fields=fields,
        read=read,
        platform=platform,
        context="object-list snapshot",
    )
    return rows


def _normalize_object_list_snapshot(
    rows: Sequence[Mapping[str, Any]],
    *,
    owner_id: Any,
    list_name: str,
) -> list[dict[str, Any]]:
    if len(rows) > OBJECT_LIST_MAX_SUBTREE_NODES:
        raise OperationContractError(
            "LIST_SNAPSHOT_LIMIT_EXCEEDED",
            "The existing object list exceeds the complete snapshot limit.",
            details={
                "list": list_name,
                "count": len(rows),
                "limit": OBJECT_LIST_MAX_SUBTREE_NODES,
            },
        )
    normalized: list[dict[str, Any]] = []
    identity_keys: set[str] = set()
    for index, raw_row in enumerate(rows):
        row = dict(raw_row)
        object_id = row.get("id")
        object_type = row.get("type")
        name = row.get("name")
        if (
            not _valid_object_id(object_id)
            or not isinstance(object_type, str)
            or not object_type
            or not isinstance(name, str)
        ):
            raise OperationContractError(
                "INVALID_READBACK",
                "Every object-list snapshot row must expose canonical id/name/type fields.",
                details={"list": list_name, "index": index, "row": row},
            )
        owner = _reference_identity(row.get("owner"))
        parent = _parent_value(row.get("parent"))
        if not (
            _same_identity(owner, owner_id)
            or _same_identity(parent, owner_id)
        ):
            raise OperationContractError(
                "LIST_OWNER_MISMATCH",
                "An object-list snapshot row is not owned by the reviewed target.",
                details={
                    "list": list_name,
                    "index": index,
                    "expected_owner": owner_id,
                    "owner": owner,
                    "parent": parent,
                    "row": row,
                },
            )
        identity_key = _identity_key(object_id)
        if identity_key in identity_keys:
            raise OperationContractError(
                "INVALID_READBACK",
                "An object-list snapshot contains duplicate GUIDs.",
                details={"list": list_name, "object_id": object_id},
            )
        identity_keys.add(identity_key)
        normalized.append(row)
    return sorted(normalized, key=lambda row: _identity_key(row["id"]))


def _normalize_object_identity_subtree(
    root_rows: Sequence[Mapping[str, Any]],
    descendant_rows: Sequence[Mapping[str, Any]],
    *,
    expected_root_id: Any,
) -> list[dict[str, Any]]:
    if (
        len(root_rows) != 1
        or not _same_identity(root_rows[0].get("id"), expected_root_id)
    ):
        raise OperationContractError(
            "IDENTITY_MISMATCH",
            "The object-list replacement subtree root changed during snapshot capture.",
            details={
                "expected_root_id": expected_root_id,
                "root_rows": [dict(row) for row in root_rows],
            },
        )
    rows = [dict(root_rows[0]), *(dict(row) for row in descendant_rows)]
    if len(rows) > OBJECT_LIST_MAX_SUBTREE_NODES:
        raise OperationContractError(
            "LIST_SUBTREE_LIMIT_EXCEEDED",
            "An existing object-list member subtree exceeds the complete GUID snapshot limit.",
            details={
                "root_id": expected_root_id,
                "count": len(rows),
                "limit": OBJECT_LIST_MAX_SUBTREE_NODES,
            },
        )
    identity_keys: list[str] = []
    for index, row in enumerate(rows):
        object_id = row.get("id")
        if not _valid_object_id(object_id):
            raise OperationContractError(
                "INVALID_READBACK",
                "Every object-list replacement subtree row must expose a canonical GUID.",
                details={"root_id": expected_root_id, "index": index, "row": row},
            )
        identity_keys.append(_identity_key(object_id))
    if len(identity_keys) != len(set(identity_keys)):
        raise OperationContractError(
            "INVALID_READBACK",
            "An object-list replacement subtree snapshot contains duplicate GUIDs.",
            details={"root_id": expected_root_id, "rows": rows},
        )
    return [rows[0], *sorted(rows[1:], key=lambda row: _identity_key(row["id"]))]


def _capture_object_list_replace_subtrees(
    rows: Sequence[Mapping[str, Any]],
    *,
    read: ReadCall,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    total_nodes = 0
    for index, row in enumerate(rows):
        root_id = row.get("id")
        root_result = read(
            OBJECT_GET_URI,
            {"from": {"id": [root_id]}},
            {"return": list(OBJECT_LIST_SNAPSHOT_FIELDS)},
        )
        descendants_result = read(
            OBJECT_GET_URI,
            {
                "from": {"id": [root_id]},
                "transform": [{"select": ["descendants"]}],
            },
            {"return": list(OBJECT_LIST_SNAPSHOT_FIELDS)},
        )
        subtree = _normalize_object_identity_subtree(
            _rows(root_result),
            _rows(descendants_result),
            expected_root_id=root_id,
        )
        total_nodes += len(subtree)
        if total_nodes > OBJECT_LIST_MAX_SUBTREE_NODES:
            raise OperationContractError(
                "LIST_SUBTREE_LIMIT_EXCEEDED",
                "The combined object-list replacement forest exceeds the complete GUID snapshot limit.",
                details={
                    "member_index": index,
                    "count": total_nodes,
                    "limit": OBJECT_LIST_MAX_SUBTREE_NODES,
                },
            )
        snapshots.append(
            {
                "root_id": root_id,
                "fields": list(OBJECT_LIST_SNAPSHOT_FIELDS),
                "rows": subtree,
            }
        )
    return snapshots


def _capture_replace_subtree_snapshot(
    collision: ResolvedObject,
    *,
    read: ReadCall,
) -> list[dict[str, Any]]:
    result = read(
        OBJECT_GET_URI,
        {"from": {"id": [collision.object]}, "transform": [{"select": ["descendants"]}]},
        {"return": list(OBJECT_REPLACE_SNAPSHOT_FIELDS)},
    )
    descendants = _rows(result)
    return _normalize_replace_subtree_snapshot(
        [collision.row],
        descendants,
        expected_root_id=collision.object,
        expected_root_path=collision.row.get("path"),
    )


def _normalize_replace_subtree_snapshot(
    root_rows: Sequence[Mapping[str, Any]],
    descendant_rows: Sequence[Mapping[str, Any]],
    *,
    expected_root_id: Any,
    expected_root_path: Any,
) -> list[dict[str, Any]]:
    if len(root_rows) != 1:
        raise OperationContractError(
            "INVALID_READBACK",
            "The replace subtree root must resolve exactly once.",
            details={"root_rows": [dict(row) for row in root_rows]},
        )
    root_path = _absolute_live_object_path(expected_root_path, field="replace collision path")
    root_row = root_rows[0]
    if not _same_identity(root_row.get("id"), expected_root_id) or root_row.get("path") != root_path:
        raise OperationContractError(
            "IDENTITY_MISMATCH",
            "The replace subtree root changed identity while its snapshot was being captured.",
            details={
                "expected": {"id": expected_root_id, "path": root_path},
                "actual": {"id": root_row.get("id"), "path": root_row.get("path")},
            },
        )
    if len(descendant_rows) + 1 > OBJECT_REPLACE_MAX_SUBTREE_NODES:
        raise OperationContractError(
            "REPLACE_SNAPSHOT_LIMIT_EXCEEDED",
            "The existing replace subtree exceeds the complete GUID/path snapshot limit.",
            details={
                "count": len(descendant_rows) + 1,
                "limit": OBJECT_REPLACE_MAX_SUBTREE_NODES,
                "root_path": root_path,
            },
        )
    normalized = [{"id": expected_root_id, "path": root_path}]
    for index, row in enumerate(descendant_rows):
        object_id = row.get("id")
        path = row.get("path")
        if not _valid_object_id(object_id) or not isinstance(path, str):
            raise OperationContractError(
                "INVALID_READBACK",
                "Every replace subtree descendant must contain a canonical GUID and path.",
                details={"index": index, "row": dict(row)},
            )
        _absolute_live_object_path(path, field=f"replace descendant[{index}].path")
        if not _is_strict_descendant_object_path(path, root_path):
            raise OperationContractError(
                "INVALID_READBACK",
                "A replace subtree descendant was returned outside the collided root.",
                details={"index": index, "root_path": root_path, "row": dict(row)},
            )
        normalized.append({"id": object_id, "path": path})
    identity_keys = [_identity_key(row["id"]) for row in normalized]
    paths = [row["path"] for row in normalized]
    if len(identity_keys) != len(set(identity_keys)) or len(paths) != len(set(paths)):
        raise OperationContractError(
            "INVALID_READBACK",
            "The replace subtree snapshot contains duplicate GUIDs or paths.",
            details={"rows": normalized},
        )
    return [normalized[0], *sorted(normalized[1:], key=lambda row: (str(row["path"]), _identity_key(row["id"])))]


def _object_spec_return_fields(spec: Mapping[str, Any]) -> list[str]:
    return _dedupe_fields(
        [
            *IDENTITY_RETURN_FIELDS,
            *(
                ("owner",)
                if spec.get("collection") not in {None, "children"}
                else ()
            ),
            *(row.get("name") for row in spec.get("properties", []) if isinstance(row, Mapping)),
            *(row.get("name") for row in spec.get("references", []) if isinstance(row, Mapping)),
            *(
                OBJECT_SET_IMPORT_READBACK_FIELDS
                if isinstance(spec.get("import"), Mapping)
                or isinstance(spec.get("requested_language"), str)
                else ()
            ),
        ]
    )


def _dedupe_fields(fields: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for field_name in fields:
        if isinstance(field_name, str) and field_name and field_name not in result:
            result.append(field_name)
    return result


def prepare_operation(request: OperationRequest, *, read_call: ReadCall) -> PreparedOperation:
    """Resolve live identities/metadata and build one immutable semantic preview."""

    spec = describe_operation(request.operation)
    reads: list[Mapping[str, Any]] = []

    def read(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        result = read_call(uri, args, options)
        if not isinstance(result, Mapping):
            raise OperationContractError(
                "INVALID_READBACK",
                f"Readback for {uri} must be a JSON object.",
                details={"uri": uri, "actual_type": type(result).__name__},
            )
        normalized = dict(result)
        reads.append({"uri": uri, "args": dict(args), "options": dict(options), "result": normalized})
        return normalized

    arguments = dict(request.arguments)
    roles: dict[str, ResolvedObject] = {}
    metadata: dict[str, Any] = {}
    warnings: list[str] = []

    if request.operation == "waapi.undoGroup":
        execution_plan = build_undo_group_execution_plan(request.version, arguments)
        prepared_children: list[Mapping[str, Any]] = []
        for index, child_plan in enumerate(execution_plan["calls"]):
            child_request = parse_operation_request(
                child_plan["child_request"],
                expected_version=request.version,
            )
            if child_request.operation == "waapi.call":
                prepared_children.append(dict(child_plan))
                continue
            child_prepared = prepare_operation(child_request, read_call=read)
            child_dispatch = child_prepared.semantic_preview.dispatch_payload()
            if child_dispatch.get("uri") != child_plan["api"]:
                raise OperationContractError(
                    "UNDO_GROUP_INNER_ROUTE_MISMATCH",
                    "Dedicated Undo child preparation changed its exact native URI.",
                    details={"index": index, "operation": child_request.operation},
                )
            prepared_children.append(
                {
                    **dict(child_plan),
                    "args": dict(child_dispatch.get("args", {})),
                    "options": dict(child_dispatch.get("options", {})),
                    "prepared_operation": child_prepared.as_dict(),
                    "request_validation_strength": "dedicated_operation_preparation",
                }
            )
        execution_plan = {
            **execution_plan,
            "calls": prepared_children,
        }
        prepared_plan_size = len(canonical_json_bytes(execution_plan))
        if prepared_plan_size > UNDO_GROUP_MAX_PLAN_BYTES:
            raise OperationContractError(
                "UNDO_GROUP_PLAN_TOO_LARGE",
                "waapi.undoGroup prepared execution plan exceeds the packaged byte limit.",
                details={
                    "size_bytes": prepared_plan_size,
                    "limit_bytes": UNDO_GROUP_MAX_PLAN_BYTES,
                },
            )
        begin = execution_plan["begin"]
        preview = SemanticPreview(
            envelope=SemanticEnvelope(
                uri=str(begin["uri"]),
                args=dict(begin["args"]),
                options=dict(begin["options"]),
                metadata={
                    "compound_operation": "waapi.undoGroup",
                    "execution_plan": execution_plan,
                    "model_authored_code": False,
                },
            ),
            source_note_family="same-connection-undo-group",
            version=request.version,
            requires_destructive_gate=True,
            raw_dispatch_allowed=False,
        )
        verification = {
            "kind": "undo-group-result-schemas",
            "version": request.version,
            "execution_plan": execution_plan,
            "business_state_verified": False,
        }
        cleanup = {
            "kind": "same_connection_cancel_on_inner_failure",
            "cancel": dict(execution_plan["cancel"]),
            "automatic_cleanup": "only_while_group_is_open_after_an_inner_failure",
            "automatic_retry": False,
            "rollback_verified": False,
        }
        metadata["execution_plan"] = execution_plan
    elif request.operation == "waapi.call":
        api, call_args, call_options, execution_contract = _public_call_arguments(
            request.version,
            arguments,
        )
        preview = SemanticPreview(
            envelope=SemanticEnvelope(
                uri=api,
                args=call_args,
                options=call_options,
                metadata={
                    "execution_contract": execution_contract,
                    "model_authored_code": False,
                },
            ),
            source_note_family="public-execution-contract",
            version=request.version,
            requires_destructive_gate=True,
            raw_dispatch_allowed=False,
        )
        verification = _public_call_verification_plan(
            api=api,
            version=request.version,
            args=call_args,
            strategy=str(execution_contract["verification_strategy"]),
        )
        cleanup = build_transaction_cleanup_spec(
            api,
            call_args,
            execution_contract,
        )
        metadata["execution_contract"] = execution_contract
    elif request.operation in {
        "lua.executeCliFile",
        "lua.executeCoreFile",
        "lua.executeCoreInline",
    }:
        preview, workflow_state, verification, cleanup = _prepare_lua_execution(
            request,
            arguments=arguments,
        )
        metadata.update(workflow_state)
    elif request.operation in {"debug.setAsserts", "debug.setAutomationMode"}:
        preview, workflow_state, verification, cleanup = _prepare_debug_mode_change(
            request,
            arguments=arguments,
        )
        metadata.update(workflow_state)
    elif request.operation in {
        "debug.restartWaapiServers",
        "debug.testAssert",
        "debug.testCrash",
    }:
        preview, workflow_state, verification, cleanup = _prepare_debug_host_control(
            request,
            arguments=arguments,
        )
        metadata.update(workflow_state)
    elif request.operation == "object.create":
        preview, workflow_roles, workflow_state, verification, cleanup = _prepare_object_create(
            request,
            arguments=arguments,
            read=read,
        )
        roles.update(workflow_roles)
        metadata.update(workflow_state)
    elif request.operation == "object.createPlugin":
        (
            preview,
            workflow_roles,
            workflow_state,
            verification,
            cleanup,
        ) = _prepare_object_create_plugin(
            request,
            arguments=arguments,
            read=read,
        )
        roles.update(workflow_roles)
        metadata.update(workflow_state)
    elif request.operation == "object.set":
        preview, workflow_roles, workflow_state, verification, cleanup = _prepare_object_set(
            request,
            arguments=arguments,
            read=read,
        )
        roles.update(workflow_roles)
        metadata.update(workflow_state)
    elif request.operation == "object.setLinked":
        preview, workflow_roles, workflow_state, verification, cleanup = _prepare_object_set_linked(
            request,
            arguments=arguments,
            read=read,
        )
        roles.update(workflow_roles)
        metadata.update(workflow_state)
    elif request.operation == "object.setRTPC":
        preview, workflow_roles, workflow_state, verification, cleanup = _prepare_object_set_rtpc(
            request,
            arguments=arguments,
            read=read,
        )
        roles.update(workflow_roles)
        metadata.update(workflow_state)
    elif request.operation in UI_COMMAND_OPERATIONS:
        preview, workflow_state, verification, cleanup = (
            _prepare_ui_command_operation(
                request,
                arguments=arguments,
                read=read,
            )
        )
        metadata.update(workflow_state)
    elif request.operation == "ui.captureScreen":
        preview, verification, cleanup = _prepare_ui_capture_screen(
            request,
            arguments=arguments,
        )
    elif request.operation == "object.delete":
        target = _resolve_identity(arguments["object"], role="object", read=read)
        _reject_protected_delete(target)
        roles["object"] = target
        try:
            auto_check_out = normalize_auto_check_out_to_source_control(
                arguments.get("auto_check_out_to_source_control"),
                version=request.version,
                supplied="auto_check_out_to_source_control" in arguments,
            )
        except ImportContractError as exc:
            raise OperationContractError(
                exc.error_code,
                str(exc),
                details=exc.details,
            ) from exc
        preview = ObjectMutationBuilder(version=request.version).delete(
            object=target,
            auto_check_out_to_source_control=auto_check_out,
        )
        metadata["source_control_policy"] = {
            "auto_check_out_to_source_control": auto_check_out,
            "supported": (
                request.version in AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS
            ),
            "dispatched": (
                "autoCheckOutToSourceControl"
                in preview.envelope.args
            ),
        }
        verification = {"kind": "guid-absent", "object_id": target.object}
        cleanup = {"kind": "none-after-delete", "irreversible": True}
    elif request.operation in {"object.copy", "object.move"}:
        source = _resolve_identity(arguments["object"], role="object", read=read)
        parent = _resolve_identity(arguments["parent"], role="parent", read=read)
        if _same_identity(source.object, parent.object):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                "object and parent must identify different live objects.",
            )
        _reject_protected_delete(source)
        roles.update({"object": source, "parent": parent})
        conflict = str(arguments.get("on_name_conflict", "fail"))
        if conflict == "replace":
            raise OperationContractError(
                "UNSUPPORTED_DESTRUCTIVE_COLLISION_POLICY",
                "object.copy and object.move do not expose native replace because it can delete an unreviewed destination subtree.",
            )
        source_name = source.row.get("name")
        parent_path = parent.row.get("path")
        if not isinstance(source_name, str) or not source_name or not isinstance(parent_path, str):
            raise OperationContractError(
                "INVALID_READBACK",
                "copy/move collision review requires live source name and parent path evidence.",
            )
        collision_path = parent_path.rstrip("\\") + "\\" + source_name
        collision_rows = _read_object_path_rows(
            collision_path,
            fields=IDENTITY_RETURN_FIELDS,
            read=read,
        )
        if len(collision_rows) > 1:
            raise OperationContractError(
                "AMBIGUOUS_COLLISION",
                "copy/move destination path must resolve to at most one object.",
                details={"path": collision_path, "rows": collision_rows},
            )
        if conflict == "fail" and collision_rows:
            raise OperationContractError(
                "NAME_COLLISION",
                "copy/move destination already contains the source name; choose rename or another parent.",
                details={"path": collision_path, "rows": collision_rows},
            )
        metadata["copy_move_collision_guard"] = {
            "path": collision_path,
            "rows": collision_rows,
        }
        try:
            auto_check_out = normalize_auto_check_out_to_source_control(
                arguments.get("auto_check_out_to_source_control"),
                version=request.version,
                supplied="auto_check_out_to_source_control" in arguments,
            )
            auto_add = (
                normalize_auto_check_out_to_source_control(
                    arguments.get("auto_add_to_source_control"),
                    version=request.version,
                    supplied="auto_add_to_source_control" in arguments,
                )
                if request.operation == "object.copy"
                else None
            )
        except ImportContractError as exc:
            raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
        builder = ObjectMutationBuilder(version=request.version)
        preview = (
            builder.copy(object=source, parent=parent, on_name_conflict=conflict, auto_add_to_source_control=auto_add, auto_check_out_to_source_control=auto_check_out)
            if request.operation == "object.copy"
            else builder.move(object=source, parent=parent, on_name_conflict=conflict, auto_check_out_to_source_control=auto_check_out)
        )
        verification = {
            "kind": "copied-guid-under-parent" if request.operation == "object.copy" else "moved-guid-under-parent",
            "source_id": source.object,
            "source_name": source.row.get("name"),
            "old_path": source.row.get("path"),
            "old_parent": _parent_value(source.row.get("parent")),
            "expected_parent_id": parent.object,
            "expected_parent_path": parent.row.get("path"),
            "on_name_conflict": conflict,
        }
        cleanup = {
            "kind": "delete-created-copy" if request.operation == "object.copy" else "move-back-to-original-parent",
            "source_snapshot": dict(source.row),
        }
    elif request.operation in {"object.setName", "object.setNotes"}:
        target = _resolve_identity(arguments["object"], role="object", read=read)
        roles["object"] = target
        value = arguments["value"]
        if not isinstance(value, str) or (request.operation == "object.setName" and not value.strip()):
            raise OperationContractError("INVALID_ARGUMENT", "value must be a non-empty string for setName and a string for setNotes.")
        if request.operation == "object.setName":
            if target.row.get("name") == value:
                raise OperationContractError("NO_OP", "setName value already matches the live object name.")
            preview = PropertyReferenceBuilder(version=request.version).set_name(object=target, value=value)
            verification = {
                "kind": "same-guid-renamed",
                "object_id": target.object,
                "expected_name": value,
                "old_path": target.row.get("path"),
                "old_parent": _parent_value(target.row.get("parent")),
            }
        else:
            preview = PropertyReferenceBuilder(version=request.version).set_notes(object=target, value=value)
            verification = {"kind": "same-guid-notes", "object_id": target.object, "expected_notes": value}
        cleanup = {"kind": "restore-pre-state", "snapshot": dict(target.row)}
    elif request.operation in {"object.setProperty", "object.setReference"}:
        source = _resolve_identity(arguments["object"], role="object", read=read)
        roles["object"] = source
        field_name = "property" if request.operation == "object.setProperty" else "reference"
        field_value = _non_empty_string(arguments[field_name], field=field_name)
        platform = (
            _non_empty_string(arguments.get("platform"), field="platform")
            if "platform" in arguments
            else None
        )
        info_payload = read(
            GET_PROPERTY_INFO_URI,
            {"object": source.object, "property": field_value},
            {},
        )
        info = parse_get_property_info_result(info_payload)
        metadata["field_info"] = info.as_dict()
        if platform is not None and request.operation == "object.setProperty":
            _require_platform_field_enabled(
                read,
                object_id=source.object,
                field_name=field_value,
                platform=platform,
            )
        field_before_result = read(
            OBJECT_GET_URI,
            {"from": {"id": [source.object]}},
            {
                "return": ["id", "path", field_value],
                **({"platform": platform} if platform is not None else {}),
            },
        )
        field_before_rows = _rows(field_before_result)
        if len(field_before_rows) != 1:
            raise OperationContractError(
                "INVALID_READBACK",
                "Property/reference pre-state must resolve to exactly one source row.",
                details={"field": field_value, "rows": field_before_rows},
            )
        metadata["field_before"] = {
            "field": field_value,
            "value": _field_value(field_before_rows[0], field_value),
            "platform": platform,
            "row": field_before_rows[0],
        }
        if request.operation == "object.setProperty":
            preview = PropertyReferenceBuilder(version=request.version).set_property(
                object=source,
                property=field_value,
                value=arguments["value"],
                property_info=info,
                property_enabled=None,
                platform=platform,
            )
            verification = {
                "kind": "same-guid-property",
                "object_id": source.object,
                "field": field_value,
                "expected_value": arguments["value"],
                "metadata_type": info.type,
                "platform": platform,
            }
        else:
            target_payload = arguments["target"]
            target = (
                _resolve_identity(target_payload, role="target", read=read)
                if target_payload is not None
                else None
            )
            if target is None:
                _require_reference_clear_allowed(info)
            else:
                roles["target"] = target
                _require_reference_target_allowed(info, target)
            preview = PropertyReferenceBuilder(version=request.version).set_reference(
                object=source,
                reference=field_value,
                target=target,
                reference_info=info,
                platform=platform,
            )
            verification = {
                "kind": "same-guid-reference",
                "object_id": source.object,
                "field": field_value,
                "expected_target_id": (
                    target.object if target is not None else None
                ),
                "expected_clear": target is None,
                "platform": platform,
            }
        cleanup = {"kind": "restore-pre-state", "snapshot": dict(source.row), "field_metadata": info.as_dict()}
    elif request.operation == "audio.import":
        preview, workflow_roles, workflow_state, verification, cleanup = _prepare_audio_import(
            request,
            arguments=arguments,
            read=read,
        )
        roles.update(workflow_roles)
        metadata.update(workflow_state)
    elif request.operation == "audio.importTabDelimited":
        preview, workflow_roles, workflow_state, verification, cleanup = _prepare_audio_import_tab_delimited(
            request,
            arguments=arguments,
            read=read,
        )
        roles.update(workflow_roles)
        metadata.update(workflow_state)
    elif request.operation in {
        "soundbank.generate",
        "soundbank.convertExternalSources",
        "soundbank.processDefinitionFiles",
    }:
        preview, workflow_roles, workflow_state, verification, cleanup = _prepare_closed_soundbank_operation(
            request,
            arguments=arguments,
            read=read,
        )
        roles.update(workflow_roles)
        metadata.update(workflow_state)
    elif request.operation == "soundbank.setInclusions":
        preview, workflow_roles, workflow_state, verification, cleanup = _prepare_soundbank_inclusions(
            request,
            arguments=arguments,
            read=read,
        )
        roles.update(workflow_roles)
        metadata.update(workflow_state)
    elif request.operation in {"switchContainer.addAssignment", "switchContainer.removeAssignment"}:
        preview, workflow_roles, workflow_state, verification, cleanup = _prepare_switch_assignment(
            request,
            arguments=arguments,
            read=read,
        )
        roles.update(workflow_roles)
        metadata.update(workflow_state)
    else:  # pragma: no cover - parse_operation_request closes this branch.
        raise OperationContractError("OPERATION_BOUNDARY", f"No preparer exists for {request.operation}.")

    return PreparedOperation(
        request=request,
        semantic_preview=preview,
        resolved_roles={name: value.as_dict() for name, value in roles.items()},
        preflight_reads=tuple(reads),
        pre_state={name: dict(value.row) for name, value in roles.items()} | metadata,
        verification_plan=verification,
        cleanup=cleanup,
        warnings=tuple(warnings),
    )


def prepare_object_set_batch_check(
    request: OperationRequest,
    *,
    read_call: ReadCall,
) -> ReadCall:
    """Check every object.set row and return the same bounded read snapshot."""

    if request.operation != "object.set":
        raise OperationContractError(
            "INVALID_REQUEST",
            "The multi-row batch check is available only for object.set.",
        )
    raw_objects = _mapping_sequence(request.arguments.get("objects"), field="objects")
    cache: dict[bytes, Mapping[str, Any]] = {}

    def cached_read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        key = canonical_json_bytes(
            {"uri": uri, "args": dict(args), "options": dict(options)}
        )
        existing = cache.get(key)
        if existing is not None:
            return dict(existing)
        if len(cache) >= MAX_OBJECT_SET_BATCH_CHECK_READS:
            raise OperationContractError(
                "OPERATION_DRAFT_CHECK_LIMIT_EXCEEDED",
                "Operation Draft live check exceeded its fixed read ceiling.",
                details={"limit": MAX_OBJECT_SET_BATCH_CHECK_READS},
            )
        result = read_call(uri, args, options)
        if not isinstance(result, Mapping):
            raise OperationContractError(
                "INVALID_READBACK",
                f"Readback for {uri} must be a JSON object.",
                details={"uri": uri, "actual_type": type(result).__name__},
            )
        normalized = dict(result)
        cache[key] = normalized
        return dict(normalized)

    common_arguments = {
        key: value
        for key, value in request.arguments.items()
        if key != "objects"
    }
    issues: list[dict[str, Any]] = []
    for row_index, row in enumerate(raw_objects):
        row_request = OperationRequest(
            contract=request.contract,
            version=request.version,
            operation=request.operation,
            arguments={**common_arguments, "objects": [dict(row)]},
        )
        try:
            prepare_operation(row_request, read_call=cached_read)
        except OperationContractError as exc:
            issues.append(
                {
                    "row_index": row_index,
                    "error_code": exc.error_code,
                    "message": str(exc)[:MAX_OBJECT_SET_BATCH_CHECK_MESSAGE_CHARS],
                }
            )
    if issues:
        raise OperationContractError(
            "OPERATION_DRAFT_CHECK_FAILED",
            "Operation Draft live check found invalid object.set rows.",
            details={"issues": issues},
        )
    return cached_read


def _prepare_ui_command_operation(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, Any], dict[str, Any], dict[str, Any]]:
    host_platform: str | None = None
    live_host_info: dict[str, Any] | None = None
    if request.operation == "ui.commands.register" or (
        request.operation == "ui.commands.unregister"
        and "commands" in arguments
    ):
        live_host_info = dict(read(GET_INFO_URI, {}, {}))
        host_platform = _ui_command_host_platform(live_host_info)
    plan = _build_ui_command_operation_plan(
        request,
        arguments=arguments,
        host_platform=host_platform,
    )
    dispatch = plan["dispatch"]
    preview = SemanticPreview(
        envelope=SemanticEnvelope(
            uri=str(dispatch["uri"]),
            args=dict(dispatch["arguments"]),
            options=dict(dispatch["options"]),
            metadata={
                "authoring_host_required": True,
                "host_platform_source": (
                    "live ak.wwise.core.getInfo.platform"
                    if host_platform is not None
                    else None
                ),
                "model_authored_code": False,
                "ui_command_plan_sha256": plan["plan_sha256"],
            },
        ),
        source_note_family="authoring-ui-command",
        version=request.version,
        requires_destructive_gate=True,
        raw_dispatch_allowed=False,
    )
    state: dict[str, Any] = {"ui_command_plan": plan}
    if live_host_info is not None:
        state["ui_command_live_host"] = {
            "isCommandLine": live_host_info.get("isCommandLine"),
            "platform": live_host_info.get("platform"),
            "mapped_host_platform": host_platform,
        }
    verification = {
        "kind": "ui-command-plan",
        "plan": plan,
        "version": request.version,
        "business_state_verified": request.operation
        in {"ui.commands.register", "ui.commands.unregister"},
    }
    return preview, state, verification, dict(plan["cleanup"])


def _build_ui_command_operation_plan(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    host_platform: str | None = None,
) -> dict[str, Any]:
    try:
        if request.operation == "ui.commands.execute":
            optional: dict[str, Any] = {}
            for field_name in ("objects", "platforms", "value", "files"):
                if field_name in arguments:
                    optional[field_name] = arguments[field_name]
            plan = build_ui_command_execute_plan(
                version=request.version,
                command=arguments.get("command"),
                **optional,
            )
        elif request.operation == "ui.commands.register":
            if host_platform is None:
                raise OperationContractError(
                    "HOST_PLATFORM_UNAVAILABLE",
                    "ui.commands.register requires a platform derived from live getInfo.",
                )
            plan = build_ui_commands_register_plan(
                version=request.version,
                host_platform=host_platform,
                commands=arguments.get("commands"),
                source_authority=arguments.get("source_authority"),
            )
        elif request.operation == "ui.commands.unregister":
            if "commands" in arguments:
                if host_platform is None:
                    raise OperationContractError(
                        "HOST_PLATFORM_UNAVAILABLE",
                        "Descriptor-backed ui.commands.unregister requires a platform derived from live getInfo.",
                    )
                plan = build_ui_commands_unregister_descriptors_plan(
                    version=request.version,
                    host_platform=host_platform,
                    commands=arguments.get("commands"),
                    source_authority=arguments.get("source_authority"),
                )
            else:
                plan = build_ui_commands_unregister_existing_plan(
                    version=request.version,
                    command_ids=arguments.get("command_ids"),
                    acknowledgement=arguments.get("acknowledgement"),
                )
        else:  # pragma: no cover - the public operation registry is closed.
            raise OperationContractError(
                "UNKNOWN_OPERATION",
                f"Unknown UI-command operation {request.operation!r}.",
            )
    except UiCommandContractError as exc:
        raise OperationContractError(
            exc.error_code,
            str(exc),
            details=exc.details,
        ) from exc
    return validate_ui_command_plan(plan)


def _ui_command_host_platform(live_info: Mapping[str, Any]) -> str:
    if live_info.get("isCommandLine") is not False:
        raise OperationContractError(
            "AUTHORING_HOST_REQUIRED",
            "Wwise Authoring UI commands require a live Authoring host, not WwiseConsole.",
            details={
                "is_command_line": live_info.get("isCommandLine"),
                "required_host": "wwise-authoring",
            },
        )
    platform = live_info.get("platform")
    if not isinstance(platform, str):
        raise OperationContractError(
            "HOST_PLATFORM_UNAVAILABLE",
            "Wwise Authoring getInfo did not return a usable platform.",
            details={"platform": platform, "supported": ["x64", "win32", "macosx"]},
        )
    normalized = platform.strip().casefold()
    mapped = {
        "x64": "windows",
        "win32": "windows",
        "macosx": "macos",
    }.get(normalized)
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


def _prepare_lua_execution(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
) -> tuple[SemanticPreview, dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        if request.operation in {"lua.executeCliFile", "lua.executeCoreFile"}:
            source_proof = seal_isolated_lua_file(
                arguments.get("script_file"),
                io_root=arguments.get("io_root"),
                source_authority=arguments.get("source_authority"),
            )
            reserved = (
                CLI_LUA_RESERVED_FIELDS
                if request.operation == "lua.executeCliFile"
                else CORE_LUA_RESERVED_FIELDS
            )
            wa_args = normalize_lua_wa_args(
                arguments.get("wa_args"),
                reserved_fields=reserved,
            )
            dispatch_args: dict[str, Any] = dict(wa_args)
            dispatch_args[
                "lua-script"
                if request.operation == "lua.executeCliFile"
                else "luaScript"
            ] = source_proof["file"]["path"]
            if "watchdog_seconds" in arguments:
                watchdog = arguments.get("watchdog_seconds")
                if (
                    request.operation != "lua.executeCliFile"
                    or request.version not in {"2024.1", "2025.1"}
                    or isinstance(watchdog, bool)
                    or not isinstance(watchdog, int)
                    or watchdog < 0
                ):
                    raise DebugLuaContractError(
                        "UNAVAILABLE_IN_VERSION",
                        "watchdog_seconds is accepted only as a non-negative integer in Wwise 2024.1-2025.1.",
                        details={"version": request.version},
                    )
                dispatch_args["watchdog-timeout"] = watchdog
        else:
            source_proof = seal_inline_lua_source(
                arguments.get("lua_code"),
                io_root=arguments.get("io_root"),
                source_authority=arguments.get("source_authority"),
            )
            wa_args = normalize_lua_wa_args(
                arguments.get("wa_args"),
                reserved_fields=CORE_LUA_RESERVED_FIELDS,
            )
            dispatch_args = {**wa_args, "luaString": arguments["lua_code"]}
    except DebugLuaContractError as exc:
        raise OperationContractError(
            exc.error_code,
            str(exc),
            details=exc.details,
        ) from exc

    uri = (
        CLI_EXECUTE_LUA_URI
        if request.operation == "lua.executeCliFile"
        else CORE_EXECUTE_LUA_URI
    )
    try:
        io_audit = validate_isolated_io(
            version=request.version,
            uri=uri,
            args=dispatch_args,
            options={},
            io_root=source_proof["io_root"],
        ).as_dict()
    except IOPolicyError as exc:
        raise OperationContractError(
            exc.error_code,
            str(exc),
            details={"io_policy": exc.as_dict()},
        ) from exc
    preview = _closed_operation_preview(
        uri=uri,
        args=dispatch_args,
        options={},
        version=request.version,
        family="explicit-user-code",
        metadata={
            "explicit_user_lua": True,
            "source_authority": LUA_SOURCE_AUTHORITY,
            "source_kind": source_proof["kind"],
            "source_sha256": (
                source_proof["file"]["sha256"]
                if source_proof["kind"] == "file"
                else source_proof["sha256"]
            ),
            "io_audit": io_audit,
            "automatic_retry": False,
        },
    )
    state = {
        "lua_source_proof": source_proof,
        "lua_wa_args": wa_args,
        "lua_io_audit": io_audit,
        "implicit_side_effect_confinement": "not_proven",
    }
    verification = {
        "kind": "result-schema",
        "uri": uri,
        "version": request.version,
        "strategy": "explicit-user-lua-result-schema",
        "business_state_verified": False,
    }
    cleanup = {
        "kind": "none",
        "automatic": False,
        "automatic_retry": False,
        "side_effects_reversible": False,
        "note": (
            "Lua may mutate project, runtime, UI, or filesystem state. The "
            "gateway seals source provenance but cannot infer or roll back its effects."
        ),
    }
    return preview, state, verification, cleanup


def _prepare_debug_mode_change(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
) -> tuple[SemanticPreview, dict[str, Any], dict[str, Any], dict[str, Any]]:
    enable = arguments.get("enable")
    if not isinstance(enable, bool):
        raise OperationContractError(
            "INVALID_ARGUMENT",
            f"{request.operation} enable must be a JSON boolean.",
        )
    uri = (
        DEBUG_ENABLE_ASSERTS_URI
        if request.operation == "debug.setAsserts"
        else DEBUG_ENABLE_AUTOMATION_MODE_URI
    )
    preview = _closed_operation_preview(
        uri=uri,
        args={"enable": enable},
        options={},
        version=request.version,
        family="debug-runtime",
        metadata={
            "process_wide_mode_change": True,
            "state_readback_available": False,
            "automatic_retry": False,
        },
    )
    state = {
        "debug_mode_request": {
            "uri": uri,
            "enable": enable,
            "pre_state": "unavailable",
        }
    }
    verification = {
        "kind": "result-schema",
        "uri": uri,
        "version": request.version,
        "strategy": "debug-mode-result-schema-only",
        "business_state_verified": False,
    }
    cleanup = {
        "kind": "manual-only",
        "automatic": False,
        "automatic_retry": False,
        "inverse_call_promised": False,
        "note": (
            "The endpoint exposes no state getter. enableAsserts is ref-counted, "
            "so an inverse call is not treated as verified rollback."
        ),
    }
    return preview, state, verification, cleanup


def _prepare_debug_host_control(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
) -> tuple[SemanticPreview, dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = {
        "debug.restartWaapiServers": {
            "uri": DEBUG_RESTART_WAAPI_SERVERS_URI,
            "acknowledge": "restart_waapi_servers",
            "expected_disconnect": True,
            "process_expectation": "wwise_process_remains_running_waapi_servers_restart",
        },
        "debug.testAssert": {
            "uri": DEBUG_TEST_ASSERT_URI,
            "acknowledge": "trigger_debug_assert",
            "expected_disconnect": False,
            "process_expectation": "assert_handler_or_dialog_is_host_build_dependent",
        },
        "debug.testCrash": {
            "uri": DEBUG_TEST_CRASH_URI,
            "acknowledge": "crash_wwise_process",
            "expected_disconnect": True,
            "process_expectation": "wwise_process_termination",
        },
    }[request.operation]
    if arguments.get("acknowledge") != contract["acknowledge"]:
        raise OperationContractError(
            "DANGEROUS_HOST_CONTROL_ACKNOWLEDGEMENT_REQUIRED",
            f"{request.operation} requires its exact immutable acknowledgement.",
            details={
                "expected": contract["acknowledge"],
                "actual": arguments.get("acknowledge"),
            },
        )
    preview = _closed_operation_preview(
        uri=str(contract["uri"]),
        args={},
        options={},
        version=request.version,
        family="dangerous-host-control",
        metadata={
            "dangerous_host_control": True,
            "acknowledgement": contract["acknowledge"],
            "expected_disconnect": contract["expected_disconnect"],
            "process_expectation": contract["process_expectation"],
            "automatic_retry": False,
        },
    )
    state = {
        "host_control": {
            "operation": request.operation,
            **contract,
            "process_observation": "not_performed_by_gateway",
        }
    }
    verification = {
        "kind": "host-control-terminal",
        "uri": contract["uri"],
        "version": request.version,
        "expected_disconnect": contract["expected_disconnect"],
        "process_expectation": contract["process_expectation"],
        "generic_verify_allowed": False,
        "business_state_verified": False,
    }
    cleanup = {
        "kind": "none",
        "automatic": False,
        "automatic_retry": False,
        "reconnect": False,
        "process_cleanup": False,
    }
    return preview, state, verification, cleanup


def _prepare_ui_capture_screen(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
) -> tuple[SemanticPreview, dict[str, Any], dict[str, Any]]:
    dispatch_args: dict[str, Any] = {}
    if "view_name" in arguments:
        dispatch_args["viewName"] = _non_empty_string(
            arguments.get("view_name"),
            field="view_name",
        )
    if "view_channel" in arguments:
        channel = arguments.get("view_channel")
        if isinstance(channel, bool) or not isinstance(channel, int) or not 1 <= channel <= 4:
            raise OperationContractError(
                "INVALID_ARGUMENT",
                "ui.captureScreen view_channel must be an integer from 1 through 4.",
            )
        dispatch_args[
            "viewSyncGroup"
            if request.version == "2021.1"
            else "viewSelectionChannel"
        ] = channel
    if "rect" in arguments:
        rect = arguments.get("rect")
        if not isinstance(rect, Mapping):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                "ui.captureScreen rect must be a JSON object.",
            )
        dispatch_args["rect"] = dict(rect)
    preview = _closed_operation_preview(
        uri="ak.wwise.ui.captureScreen",
        args=dispatch_args,
        options={},
        version=request.version,
        family="ui",
        metadata={
            "stable_request_adapter": True,
            "view_channel_wire_field": (
                "viewSyncGroup"
                if request.version == "2021.1"
                else "viewSelectionChannel"
            ),
        },
    )
    verification = {
        "kind": "ui-capture-screen-result",
        "version": request.version,
        "max_base64_chars": 1024 * 1024,
    }
    cleanup = {
        "kind": "none",
        "automatic": False,
        "automatic_retry": False,
    }
    return preview, verification, cleanup


def _prepare_audio_import(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw_imports = _mapping_sequence(arguments.get("imports"), field="imports")
    raw_defaults = arguments.get("defaults")
    if raw_defaults is not None and not isinstance(raw_defaults, Mapping):
        raise OperationContractError("INVALID_ARGUMENT", "defaults must be a JSON object.")
    resolved_imports = [dict(row) for row in raw_imports]
    resolved_defaults = dict(raw_defaults) if isinstance(raw_defaults, Mapping) else None
    location_roles: dict[str, ResolvedObject] = {}

    def resolve_location(scope: dict[str, Any], *, role: str) -> None:
        if "import_location" not in scope:
            return
        resolved = _resolve_identity(
            scope.get("import_location"),
            role=role,
            read=read,
        )
        _require_import_parent(
            resolved,
            index=0,
            version=request.version,
        )
        path = resolved.row.get("path")
        if not isinstance(path, str) or not path.startswith("\\"):
            raise OperationContractError(
                "INVALID_READBACK",
                f"{role} must expose an absolute Wwise path.",
            )
        scope["import_location"] = path
        location_roles[role] = resolved

    if resolved_defaults is not None:
        resolve_location(resolved_defaults, role="defaults.import_location")
    for index, row in enumerate(resolved_imports):
        resolve_location(row, role=f"imports[{index}].import_location")

    operation = arguments.get("import_operation", "createNew")
    try:
        plan = build_audio_import_plan(
            resolved_imports,
            version=request.version,
            import_operation=str(operation),
            defaults=resolved_defaults,
            auto_add_to_source_control=arguments.get(
                "auto_add_to_source_control",
                False,
            ),
            auto_check_out_to_source_control=arguments.get(
                "auto_check_out_to_source_control"
            ),
        )
    except ImportContractError as exc:
        raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
    preview, roles, state, verification, cleanup = _prepare_closed_import_plan(
        request,
        source_operation="audio.import",
        plan=plan,
        read=read,
    )
    return (
        preview,
        {**location_roles, **roles},
        state,
        verification,
        cleanup,
    )


def _prepare_audio_import_tab_delimited(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    location = _resolve_identity(arguments.get("import_location"), role="import_location", read=read)
    _require_import_parent(
        location,
        index=0,
        version=request.version,
    )
    location_path = location.row.get("path")
    if not isinstance(location_path, str):
        raise OperationContractError("INVALID_READBACK", "import_location must expose an absolute path.")
    try:
        plan = parse_tab_delimited_import_file(
            arguments.get("import_file"),
            version=request.version,
            import_location=location_path,
            import_language=str(arguments.get("import_language")),
            import_operation=str(arguments.get("import_operation", "createNew")),
            auto_add_to_source_control=arguments.get(
                "auto_add_to_source_control",
                False,
            ),
            auto_check_out_to_source_control=arguments.get(
                "auto_check_out_to_source_control"
            ),
        )
    except ImportContractError as exc:
        raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
    dispatch_args = dict(plan["dispatch_args"])
    dispatch_args["importLocation"] = location.object
    plan = {**plan, "dispatch_args": dispatch_args}
    prepared = _prepare_closed_import_plan(
        request,
        source_operation="audio.importTabDelimited",
        plan=plan,
        read=read,
    )
    preview, roles, state, verification, cleanup = prepared
    roles = {"import_location": location, **roles}
    return preview, roles, state, verification, cleanup


def _normalize_import_language_rows(value: Any, *, authority: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value or len(value) > 64:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "The live Project language inventory must be a non-empty bounded array.",
            details={"authority": authority, "count": len(value) if isinstance(value, list) else None},
        )
    rows: list[dict[str, str]] = []
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                "Every live Project language row must be an object.",
                details={"authority": authority, "index": index},
            )
        name = raw.get("name")
        language_id = raw.get("id")
        if (
            not isinstance(name, str)
            or not name
            or name != name.strip()
            or not isinstance(language_id, str)
            or not language_id
        ):
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                "Every live Project language row requires an exact non-empty name and ID.",
                details={"authority": authority, "index": index, "row": dict(raw)},
            )
        name_key = name.casefold()
        id_key = language_id.casefold()
        if name_key in seen_names or id_key in seen_ids:
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                "Live Project language names and IDs must be unique.",
                details={"authority": authority, "index": index, "row": dict(raw)},
            )
        seen_names.add(name_key)
        seen_ids.add(id_key)
        rows.append({"id": language_id, "name": name})
    return sorted(rows, key=lambda row: (row["name"].casefold(), row["id"].casefold()))


def _read_import_language_inventory(version: str, *, read: ReadCall) -> dict[str, Any]:
    if version == "2021.1":
        query = "from type Project take 2"
        options = {"return": ["id", "name", "type", "path", "filePath", "workunitIsDirty"]}
        result = read(OBJECT_GET_URI, {"waql": query}, options)
        rows = _rows(result)
        if len(rows) != 1 or rows[0].get("type") != "Project" or rows[0].get("path") != "\\":
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                "Wwise 2021.1 import language validation requires the unique live Project root.",
                details={"query": query, "rows": rows},
            )
        row = rows[0]
        project_file = _localize_waapi_file_path(row.get("filePath"))
        try:
            inventory = parse_wwise_2021_language_inventory(
                project_file,
                live_project_id=row.get("id"),
                live_project_name=row.get("name"),
                workunit_is_dirty=row.get("workunitIsDirty"),
            )
        except SoundBankContractError as exc:
            raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
        languages = _normalize_import_language_rows(
            inventory.get("languages"),
            authority="waapi_object_get_filePath_plus_hashed_wproj_language_list",
        )
        return {
            "authority": "waapi_object_get_filePath_plus_hashed_wproj_language_list",
            "project": {"id": row.get("id"), "name": row.get("name"), "path": row.get("path")},
            "languages": languages,
            "wproj_inventory": _json_mapping(inventory),
        }

    result = read(GET_PROJECT_INFO_URI, {}, {})
    try:
        validate_semantic_result(GET_PROJECT_INFO_URI, result, version=version)
    except SemanticValidationError as exc:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "core.getProjectInfo did not match the packaged versioned result schema.",
            details=exc.as_dict(),
        ) from exc
    languages = _normalize_import_language_rows(result.get("languages"), authority="waapi_getProjectInfo")
    project = {
        key: result.get(key)
        for key in ("id", "name", "path")
        if result.get(key) is not None
    }
    return {
        "authority": "waapi_getProjectInfo",
        "project": project,
        "languages": languages,
    }


def _import_project_directory_candidate(
    value: Any,
    *,
    field: str,
    base: Path,
) -> Path:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{field} must be a non-empty path string.",
            details={field: value},
        )
    try:
        parse_absolute_host_path(value, allow_trailing_separator=True)
    except HostPathError:
        try:
            relative = parse_relative_host_path(
                value,
                allow_current_directory=True,
            )
        except HostPathError as exc:
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                f"{field} contains an unsafe relative path.",
                details={field: value, "path_error": str(exc)},
            ) from exc
        candidate = base.joinpath(*relative.components)
    else:
        candidate = Path(_localize_waapi_file_path(value, field=field))
    if not candidate.is_absolute():
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{field} did not resolve to an absolute path.",
            details={field: value, "candidate": str(candidate)},
        )
    return candidate


def _secure_import_filesystem_path(
    path: Path,
    *,
    field: str,
    require_directory: bool,
) -> Path:
    """Resolve one import proof path without accepting symlink components."""

    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise OperationContractError(
            "UNSAFE_ORIGINALS_PATH",
            f"{field} must be an absolute path without dot segments.",
            details={field: str(path)},
        )
    current = Path(path.anchor)
    components = path.parts[1:]
    if not components:
        raise OperationContractError(
            "UNSAFE_ORIGINALS_PATH",
            f"{field} must not identify a filesystem anchor.",
            details={field: str(path)},
        )
    for index, component in enumerate(components):
        current = current / component
        try:
            path_stat = current.lstat()
        except OSError as exc:
            raise OperationContractError(
                "UNSAFE_ORIGINALS_PATH",
                f"{field} contains an inaccessible path component.",
                details={field: str(path), "component": str(current), "error": str(exc)},
            ) from exc
        if path_is_link_or_reparse(current, metadata=path_stat):
            raise OperationContractError(
                "UNSAFE_ORIGINALS_PATH",
                f"{field} must not contain links, junctions, or reparse points.",
                details={field: str(path), "component": str(current)},
            )
        is_final = index == len(components) - 1
        if not is_final and not stat.S_ISDIR(path_stat.st_mode):
            raise OperationContractError(
                "UNSAFE_ORIGINALS_PATH",
                f"{field} contains a non-directory parent component.",
                details={field: str(path), "component": str(current)},
            )
        if is_final:
            expected_mode = stat.S_ISDIR if require_directory else stat.S_ISREG
            if not expected_mode(path_stat.st_mode):
                expected = "directory" if require_directory else "regular file"
                raise OperationContractError(
                    "UNSAFE_ORIGINALS_PATH",
                    f"{field} must identify a {expected}.",
                    details={field: str(path), "component": str(current)},
                )
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise OperationContractError(
            "UNSAFE_ORIGINALS_PATH",
            f"{field} could not be resolved safely.",
            details={field: str(path), "error": str(exc)},
        ) from exc
    return resolved


def _wwise_2021_originals_setting(
    project_file: Path,
    *,
    expected_sha256: str,
) -> str:
    try:
        data = project_file.read_bytes()
    except OSError as exc:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "The Wwise 2021.1 Project file could not be read for its Originals setting.",
            details={"path": str(project_file), "error": str(exc)},
        ) from exc
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        raise OperationContractError(
            "FILE_CHANGED",
            "The Wwise 2021.1 Project file changed while its Originals setting was read.",
            details={
                "path": str(project_file),
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
            },
        )
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "The Wwise 2021.1 Project file must be UTF-8.",
            details={"path": str(project_file), "start": exc.start},
        ) from exc
    upper = text.upper()
    if "\x00" in text or "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "The Wwise 2021.1 Project file contains unsafe XML constructs.",
            details={"path": str(project_file)},
        )
    try:
        document = ET.fromstring(text)
    except ET.ParseError as exc:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "The Wwise 2021.1 Project file is not well-formed XML.",
            details={"path": str(project_file), "error": str(exc)},
        ) from exc
    project_infos = [child for child in document if child.tag == "ProjectInfo"]
    projects = (
        [child for child in project_infos[0] if child.tag == "Project"]
        if len(project_infos) == 1
        else []
    )
    misc_settings = (
        [child for child in projects[0] if child.tag == "MiscSettings"]
        if len(projects) == 1
        else []
    )
    originals = (
        [
            child
            for child in misc_settings[0]
            if child.tag == "MiscSettingEntry" and child.attrib.get("Name") == "Originals"
        ]
        if len(misc_settings) == 1
        else []
    )
    if len(originals) != 1 or set(originals[0].attrib) != {"Name"}:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "The Wwise 2021.1 Project must declare exactly one closed Originals setting.",
            details={"path": str(project_file), "count": len(originals)},
        )
    setting = originals[0].text
    if not isinstance(setting, str) or not setting or setting != setting.strip():
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "The Wwise 2021.1 Originals setting must be a non-empty path.",
            details={"path": str(project_file), "value": setting},
        )
    return setting


def _read_import_originals_context(version: str, *, read: ReadCall) -> dict[str, Any]:
    if version == "2021.1":
        query = "from type Project take 2"
        options = {
            "return": [
                "id",
                "name",
                "type",
                "path",
                "filePath",
                "workunitIsDirty",
            ]
        }
        result = read(OBJECT_GET_URI, {"waql": query}, options)
        rows = _rows(result)
        if len(rows) != 1 or rows[0].get("type") != "Project" or rows[0].get("path") != "\\":
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                "Wwise 2021.1 import Originals validation requires the unique live Project root.",
                details={"query": query, "rows": rows},
            )
        row = rows[0]
        project_file = Path(_localize_waapi_file_path(row.get("filePath")))
        try:
            inventory = parse_wwise_2021_language_inventory(
                project_file,
                live_project_id=row.get("id"),
                live_project_name=row.get("name"),
                workunit_is_dirty=row.get("workunitIsDirty"),
            )
        except SoundBankContractError as exc:
            raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
        file_proof = inventory.get("file_proof")
        expected_sha256 = file_proof.get("sha256") if isinstance(file_proof, Mapping) else None
        if not isinstance(expected_sha256, str):
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                "The Wwise 2021.1 Project inventory lacks a file digest.",
            )
        secure_project_file = _secure_import_filesystem_path(
            project_file,
            field="live Project filePath",
            require_directory=False,
        )
        project_root = _secure_import_filesystem_path(
            secure_project_file.parent,
            field="live Project root",
            require_directory=True,
        )
        originals_setting = _wwise_2021_originals_setting(
            secure_project_file,
            expected_sha256=expected_sha256,
        )
        originals_root = _secure_import_filesystem_path(
            _import_project_directory_candidate(
                originals_setting,
                field="Project.MiscSettings.Originals",
                base=project_root,
            ),
            field="Project.MiscSettings.Originals",
            require_directory=True,
        )
        return {
            "authority": "waapi_object_get_filePath_plus_hashed_wproj",
            "version": version,
            "project": {
                "id": row.get("id"),
                "name": row.get("name"),
                "path": str(secure_project_file),
            },
            "project_root": str(project_root),
            "originals_root": str(originals_root),
            "source_proof_sha256": inventory.get("inventory_sha256"),
        }
    if version not in {"2022.1", "2023.1", "2024.1", "2025.1"}:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "The derived Originals-root import oracle lacks a supported Wwise lane.",
            details={"version": version},
        )
    result = read(GET_PROJECT_INFO_URI, {}, {})
    try:
        validate_semantic_result(GET_PROJECT_INFO_URI, result, version=version)
    except SemanticValidationError as exc:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "core.getProjectInfo did not match the packaged versioned result schema.",
            details=exc.as_dict(),
        ) from exc
    project_file = Path(
        _localize_waapi_file_path(
            result.get("path"),
            field="project_info.path",
        )
    )
    raw_directories = result.get("directories")
    if not isinstance(raw_directories, Mapping):
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "project_info.directories must be a JSON object.",
        )
    project_root = _secure_import_filesystem_path(
        _import_project_directory_candidate(
            raw_directories.get("root"),
            field="project_info.directories.root",
            base=project_file.parent,
        ),
        field="project_info.directories.root",
        require_directory=True,
    )
    project_parent = _secure_import_filesystem_path(
        project_file.parent,
        field="project_info.path parent",
        require_directory=True,
    )
    if project_root != project_parent:
        raise OperationContractError(
            "PROJECT_PATH_MISMATCH",
            "project_info.directories.root does not identify the directory containing the active project file.",
            details={
                "project_info.path": str(project_file),
                "project_root": str(project_root),
                "project_parent": str(project_parent),
            },
        )
    originals_root = _secure_import_filesystem_path(
        _import_project_directory_candidate(
            raw_directories.get("originals"),
            field="project_info.directories.originals",
            base=project_root,
        ),
        field="project_info.directories.originals",
        require_directory=True,
    )
    return {
        "authority": "waapi_getProjectInfo",
        "version": version,
        "project": {
            "id": result.get("id"),
            "name": result.get("name"),
            "path": str(project_file),
        },
        "project_root": str(project_root),
        "originals_root": str(originals_root),
        "source_proof_sha256": None,
    }


def _import_originals_root_from_context(value: Any, *, version: str) -> str:
    expected_authority = (
        "waapi_object_get_filePath_plus_hashed_wproj"
        if version == "2021.1"
        else "waapi_getProjectInfo"
    )
    project = value.get("project") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "authority",
            "version",
            "project",
            "project_root",
            "originals_root",
            "source_proof_sha256",
        }
        or value.get("authority") != expected_authority
        or value.get("version") != version
        or version not in SUPPORTED_WWISE_VERSION_KEYS
        or not isinstance(project, Mapping)
        or set(project) != {"id", "name", "path"}
        or not all(isinstance(project.get(key), str) and project.get(key) for key in ("id", "name", "path"))
        or not Path(str(project.get("path"))).is_absolute()
        or not isinstance(value.get("project_root"), str)
        or not isinstance(value.get("originals_root"), str)
        or not Path(str(value.get("project_root"))).is_absolute()
        or not Path(str(value.get("originals_root"))).is_absolute()
        or (
            version == "2021.1"
            and not isinstance(value.get("source_proof_sha256"), str)
        )
        or (
            version != "2021.1"
            and value.get("source_proof_sha256") is not None
        )
    ):
        raise OperationContractError(
            "INVALID_PREVIEW",
            "The import Originals-root Project context is malformed.",
            details={"version": version, "context": value},
        )
    return str(value["originals_root"])


def _prepare_import_dynamic_fields(
    request: OperationRequest,
    *,
    source_operation: str,
    raw_targets: Sequence[Mapping[str, Any]],
    dispatch_args: Mapping[str, Any],
    read: ReadCall,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, ResolvedObject]]:
    """Validate and materialize native ``@Property`` import fields.

    The public request never contains a raw ``@`` key.  Property/reference
    tokens are checked against live class-scoped metadata, references are
    resolved to canonical IDs, and only then are the trusted WAAPI keys added
    to ``audio.import`` rows.  Tab-delimited files already contain their wire
    columns, so this path validates and seals their typed readback oracle
    without rewriting the proven input file.
    """

    if source_operation not in {"audio.import", "audio.importTabDelimited"}:
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Unknown closed import operation for dynamic-field validation.",
        )
    targets = [dict(row) for row in raw_targets]
    # The packaged catalog is discovery evidence, not mutation authority.
    # Resolve the class id from the connected Wwise instance.  The gateway
    # wraps this exact read with the session-bound metadata cache, so repeated
    # previews avoid another WAAPI round trip without accepting stale
    # cross-build or plug-in-specific type metadata.
    type_catalog = _read_object_type_catalog(read)
    property_info_cache: dict[
        tuple[str, str, str],
        PropertyInfoMetadataRecord,
    ] = {}
    identity_cache: dict[bytes, ResolvedObject] = {}
    roles: dict[str, ResolvedObject] = {}

    raw_dispatch_rows = dispatch_args.get("imports")
    if source_operation == "audio.import":
        if (
            not isinstance(raw_dispatch_rows, list)
            or len(raw_dispatch_rows) != len(targets)
            or not all(isinstance(row, Mapping) for row in raw_dispatch_rows)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "audio.import dynamic fields require one dispatch row per target.",
            )
        dispatch_rows = [dict(row) for row in raw_dispatch_rows]
    else:
        dispatch_rows = []

    def property_info(class_id: int, name: str) -> PropertyInfoMetadataRecord:
        return _read_property_info_cached(
            read,
            cache=property_info_cache,
            class_id=class_id,
            name=name,
        )

    def resolve_reference(identity: Mapping[str, Any], *, role: str) -> ResolvedObject:
        try:
            cache_key = canonical_json_bytes(dict(identity))
        except (TypeError, ValueError) as exc:
            raise OperationContractError(
                "INVALID_IDENTITY",
                f"{role} identity is not canonical JSON.",
            ) from exc
        cached = identity_cache.get(cache_key)
        if cached is None:
            cached = _resolve_identity(
                identity,
                role=role,
                read=read,
                identity_cache=identity_cache,
            )
            identity_cache[cache_key] = cached
        roles[role] = cached
        return cached

    for index, target in enumerate(targets):
        requested_type = target.get("requested_object_type", "Sound")
        if not isinstance(requested_type, str):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "An import target has a malformed requested object type.",
                details={"index": index, "requested_type": requested_type},
            )
        metadata_type = _import_metadata_object_type(
            requested_type,
            version=request.version,
        )
        type_info = _resolve_object_type(metadata_type, catalog=type_catalog)
        if (
            request.version == "2025.1"
            and _object_type_token(requested_type) == "actormixer"
            and _object_type_token(type_info.name) != "propertycontainer"
        ):
            raise OperationContractError(
                "INVALID_OBJECT_TYPE",
                "Wwise 2025.1 ActorMixer imports must resolve through the live PropertyContainer metadata row.",
                details={
                    "requested": requested_type,
                    "resolved": type_info.as_dict(),
                },
            )
        target["metadata_object_type"] = type_info.name
        target["metadata_class_id"] = type_info.class_id

        raw_properties = target.get("requested_properties", [])
        raw_references = target.get("requested_references", [])
        raw_dynamic = target.get("requested_dynamic_fields", [])
        if not isinstance(raw_properties, list) or not all(
            isinstance(item, Mapping) for item in raw_properties
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Import property descriptors are malformed.",
                details={"index": index},
            )
        if not isinstance(raw_references, list) or not all(
            isinstance(item, Mapping) for item in raw_references
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Import reference descriptors are malformed.",
                details={"index": index},
            )
        if not isinstance(raw_dynamic, list) or not all(
            isinstance(item, Mapping) for item in raw_dynamic
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Tab-delimited dynamic-field descriptors are malformed.",
                details={"index": index},
            )

        property_requests: list[dict[str, Any]] = [
            {"name": item.get("name"), "value": item.get("value"), "source": "request"}
            for item in raw_properties
        ]
        reference_requests: list[dict[str, Any]] = [
            {"name": item.get("name"), "target": item.get("target"), "source": "request"}
            for item in raw_references
        ]
        for dynamic_index, item in enumerate(raw_dynamic):
            name = item.get("name")
            kind = item.get("kind")
            value = item.get("value")
            if (
                not isinstance(name, str)
                or kind not in {"property", "reference", "auto"}
                or not isinstance(value, str)
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A tab-delimited dynamic field lacks a closed name, kind, or value.",
                    details={"index": index, "dynamic_index": dynamic_index},
                )
            info = property_info(type_info.class_id, name)
            is_reference = _metadata_is_reference(info)
            if kind == "property" and is_reference:
                raise OperationContractError(
                    "INVALID_PROPERTY",
                    "A Property[...] column resolves to live reference metadata.",
                    details={"index": index, "name": name},
                )
            if kind == "reference" and not is_reference:
                raise OperationContractError(
                    "INVALID_REFERENCE",
                    "A Reference[...] column resolves to live property metadata.",
                    details={"index": index, "name": name},
                )
            if is_reference:
                reference_requests.append(
                    {
                        "name": name,
                        "target": _tab_import_reference_identity(
                            value,
                            field=f"targets[{index}].dynamic[{dynamic_index}]",
                        ),
                        "source": "tab",
                    }
                )
            else:
                property_requests.append(
                    {
                        "name": name,
                        "value": _coerce_tab_import_property_value(
                            info,
                            value,
                            field=f"targets[{index}].dynamic[{dynamic_index}]",
                        ),
                        "source": "tab",
                    }
                )

        property_specs: list[dict[str, Any]] = []
        property_info_by_name: dict[str, PropertyInfoMetadataRecord] = {}
        seen_fields: set[str] = set()
        for property_index, descriptor in enumerate(property_requests):
            name = descriptor.get("name")
            if not isinstance(name, str) or not name:
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "An import property descriptor lacks a name.",
                    details={"index": index, "property_index": property_index},
                )
            key = name.casefold()
            if key in seen_fields:
                raise OperationContractError(
                    "DUPLICATE_FIELD",
                    "An import target assigns one property/reference more than once.",
                    details={"index": index, "name": name},
                )
            seen_fields.add(key)
            info = property_info(type_info.class_id, name)
            _require_object_property_value(info, descriptor.get("value"))
            property_info_by_name[key] = info
            property_specs.append(
                {
                    "name": info.name,
                    "value": descriptor.get("value"),
                    "metadata_type": info.type,
                    "source": descriptor.get("source"),
                }
            )

        reference_specs: list[dict[str, Any]] = []
        derived_properties: dict[str, Any] = {}
        for reference_index, descriptor in enumerate(reference_requests):
            name = descriptor.get("name")
            identity = descriptor.get("target")
            if not isinstance(name, str) or not name or not isinstance(identity, Mapping):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "An import reference descriptor lacks a name or closed identity.",
                    details={"index": index, "reference_index": reference_index},
                )
            key = name.casefold()
            if key in seen_fields:
                raise OperationContractError(
                    "DUPLICATE_FIELD",
                    "An import target assigns one property/reference more than once.",
                    details={"index": index, "name": name},
                )
            seen_fields.add(key)
            info = property_info(type_info.class_id, name)
            _require_object_reference_metadata(info)
            activation_properties = _apply_reference_activation_dependencies(
                info,
                read=read,
                class_id=type_info.class_id,
                property_specs=property_specs,
                property_info_by_name=property_info_by_name,
                derived_properties=derived_properties,
                request_path=f"targets[{index}].references[{reference_index}]",
                property_info_cache=property_info_cache,
            )
            resolved = resolve_reference(
                identity,
                role=f"targets[{index}].references[{reference_index}].target",
            )
            _require_reference_target_allowed(info, resolved)
            reference_spec: dict[str, Any] = {
                "name": info.name,
                "target_id": resolved.object,
                "source": descriptor.get("source"),
            }
            if activation_properties:
                reference_spec["activation_properties"] = list(
                    activation_properties
                )
            reference_specs.append(reference_spec)

        if source_operation == "audio.importTabDelimited":
            explicitly_supplied = {
                str(item.get("name")).casefold()
                for item in property_requests
                if isinstance(item.get("name"), str)
            }
            missing_activation_columns = sorted(
                name
                for name in derived_properties
                if name.casefold() not in explicitly_supplied
            )
            if missing_activation_columns:
                raise OperationContractError(
                    "TAB_REFERENCE_DEPENDENCY_REQUIRES_COLUMN",
                    "A tab-delimited reference requires explicit Boolean activation property columns.",
                    details={
                        "index": index,
                        "missing_properties": missing_activation_columns,
                    },
                )

        if property_specs:
            target["validated_properties"] = property_specs
        if reference_specs:
            target["validated_references"] = reference_specs
        targets[index] = target

    trusted_dispatch = dict(dispatch_args)
    if source_operation == "audio.import":
        trusted_dispatch["imports"] = dispatch_rows
    return targets, trusted_dispatch, roles


def _materialize_audio_import_dynamic_rows(
    *,
    dispatch_args: Mapping[str, Any],
    targets: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Materialize validated dynamic Sound fields onto their native owner.

    A native import row whose final object is an implicitly created
    ``AudioFileSource`` applies ``@Property`` and ``@Reference`` fields to that
    source, not to the requested Sound.  The public contract remains one
    logical row per Sound.  Internally, a media row with dynamic Sound fields
    is therefore expanded into an ordered structure row followed by an
    explicit ``AudioFileSource`` media row, while the WAAPI call count remains
    exactly one.
    """

    raw_rows = dispatch_args.get("imports")
    if (
        not isinstance(raw_rows, list)
        or len(raw_rows) != len(targets)
        or not all(isinstance(row, Mapping) for row in raw_rows)
    ):
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Closed audio.import rows must remain bound one-to-one to logical targets before native materialization.",
        )

    target_paths = {
        str(target.get("canonical_target_path")).casefold()
        for target in targets
        if isinstance(target.get("canonical_target_path"), str)
    }
    claimed_source_paths: set[str] = set()
    native_rows: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []

    for index, (raw_row, raw_target) in enumerate(
        zip(raw_rows, targets, strict=True)
    ):
        row = dict(raw_row)
        target = dict(raw_target)
        properties = target.get("validated_properties", [])
        references = target.get("validated_references", [])
        if not isinstance(properties, list) or not all(
            isinstance(item, Mapping) for item in properties
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Validated audio.import properties are malformed.",
                details={"index": index},
            )
        if not isinstance(references, list) or not all(
            isinstance(item, Mapping) for item in references
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Validated audio.import references are malformed.",
                details={"index": index},
            )

        dynamic_fields: dict[str, Any] = {}
        for spec in properties:
            name = spec.get("name")
            if not isinstance(name, str) or not name:
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A validated audio.import property lacks its canonical name.",
                    details={"index": index, "property": dict(spec)},
                )
            dynamic_fields[f"@{name}"] = spec.get("value")
        for spec in references:
            name = spec.get("name")
            target_id = spec.get("target_id")
            if (
                not isinstance(name, str)
                or not name
                or not _valid_object_id(target_id)
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A validated audio.import reference lacks its canonical name or target GUID.",
                    details={"index": index, "reference": dict(spec)},
                )
            dynamic_fields[f"@{name}"] = target_id

        media_expected = target.get("media_expected")
        if type(media_expected) is not bool:
            raise OperationContractError(
                "INVALID_PREVIEW",
                "An audio.import target lacks its explicit media expectation.",
                details={"index": index},
            )
        if not dynamic_fields or not media_expected:
            row.update(dynamic_fields)
            native_index = len(native_rows)
            native_rows.append(row)
            mapping.append(
                {
                    "logical_index": index,
                    "native_rows": [
                        {
                            "native_index": native_index,
                            "kind": "single",
                            "object_path": row.get("objectPath"),
                        }
                    ],
                }
            )
            continue

        metadata_type = target.get("metadata_object_type")
        expected_source_path = target.get(
            "expected_audio_file_source_result_path"
        )
        if _object_type_token(metadata_type) != "sound":
            raise OperationContractError(
                "IMPORT_DYNAMIC_MEDIA_TOPOLOGY_UNSUPPORTED",
                "Dynamic fields with media are currently materialized only for a live-validated Sound target.",
                details={
                    "index": index,
                    "metadata_object_type": metadata_type,
                },
            )
        if not isinstance(expected_source_path, str):
            raise OperationContractError(
                "IMPORT_DYNAMIC_MEDIA_TOPOLOGY_UNSUPPORTED",
                "This media type has no sealed AudioFileSource topology for dynamic Sound fields.",
                details={"index": index, "target": target.get("canonical_target_path")},
            )
        source_key = expected_source_path.casefold()
        if source_key in target_paths or source_key in claimed_source_paths:
            raise OperationContractError(
                "DUPLICATE_TARGET",
                "An expanded AudioFileSource path collides with another logical import target.",
                details={"index": index, "source_path": expected_source_path},
            )
        claimed_source_paths.add(source_key)

        object_path = row.get("objectPath")
        source_name = expected_source_path.rpartition("\\")[2]
        if (
            not isinstance(object_path, str)
            or not object_path
            or object_path.endswith("\\")
            or not source_name
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "The logical import row cannot derive one explicit AudioFileSource wire path.",
                details={
                    "index": index,
                    "object_path": object_path,
                    "expected_source_path": expected_source_path,
                },
            )

        supported_fields = {
            "objectPath",
            "importLocation",
            "objectType",
            "audioFile",
            "audioFileBase64",
            "importLanguage",
            "originalsSubFolder",
            "notes",
            "audioSourceNotes",
            "event",
            "dialogueEvent",
            "switchAssignation",
        }
        unexpected_fields = sorted(str(key) for key in set(row) - supported_fields)
        if unexpected_fields:
            raise OperationContractError(
                "INVALID_PREVIEW",
                "The logical audio.import row contains fields without a reviewed native owner.",
                details={"index": index, "fields": unexpected_fields},
            )

        structure_row: dict[str, Any] = {
            key: row[key]
            for key in (
                "objectPath",
                "importLocation",
                "objectType",
                "event",
                "dialogueEvent",
                "switchAssignation",
            )
            if key in row
        }
        if target.get("requested_notes_destination") == "target_object" and "notes" in row:
            structure_row["notes"] = row["notes"]
        structure_row.update(dynamic_fields)

        media_row: dict[str, Any] = {
            "objectPath": f"{object_path}\\<AudioFileSource>{source_name}",
        }
        for key in (
            "importLocation",
            "audioFile",
            "audioFileBase64",
            "importLanguage",
            "originalsSubFolder",
        ):
            if key in row:
                media_row[key] = row[key]
        if "audioSourceNotes" in row:
            media_row["notes"] = row["audioSourceNotes"]
        elif (
            target.get("requested_notes_destination") == "audio_file_source"
            and "notes" in row
        ):
            media_row["notes"] = row["notes"]
        if ("audioFile" in media_row) == ("audioFileBase64" in media_row):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "An expanded AudioFileSource row requires exactly one sealed media input.",
                details={"index": index, "fields": sorted(media_row)},
            )

        structure_index = len(native_rows)
        native_rows.append(structure_row)
        media_index = len(native_rows)
        native_rows.append(media_row)
        mapping.append(
            {
                "logical_index": index,
                "native_rows": [
                    {
                        "native_index": structure_index,
                        "kind": "sound_structure",
                        "object_path": structure_row["objectPath"],
                    },
                    {
                        "native_index": media_index,
                        "kind": "audio_file_source_media",
                        "object_path": media_row["objectPath"],
                        "canonical_result_path": expected_source_path,
                    },
                ],
            }
        )

    if len(native_rows) > MAX_NATIVE_AUDIO_IMPORT_ROWS:
        raise OperationContractError(
            "LIMIT_EXCEEDED",
            "audio.import native row expansion exceeds the closed internal limit.",
            details={
                "logical_rows": len(targets),
                "native_rows": len(native_rows),
                "limit": MAX_NATIVE_AUDIO_IMPORT_ROWS,
            },
        )
    return {**dict(dispatch_args), "imports": native_rows}, mapping


def _metadata_is_reference(info: PropertyInfoMetadataRecord) -> bool:
    return (
        info.type.casefold() in {"reference", "objectreference"}
        or info.restriction.get("type") == "reference"
    )


def _import_metadata_object_type(value: str, *, version: str) -> str:
    token = _object_type_token(value)
    if version == "2025.1" and token == "actormixer":
        # Wwise 2025.1 reflects Actor Mixers as PropertyContainer metadata,
        # while audio.import still accepts the stable native ActorMixer token.
        return "PropertyContainer"
    aliases = {
        "soundsfx": "Sound",
        "soundvoice": "Sound",
        "randomcontainer": "RandomSequenceContainer",
        "sequencecontainer": "RandomSequenceContainer",
        "randomsequencecontainer": "RandomSequenceContainer",
        "actormixer": "ActorMixer",
        "blendcontainer": "BlendContainer",
        "switchcontainer": "SwitchContainer",
        "musicplaylistcontainer": "MusicRanSeqCntr",
        "musicswitchcontainer": "MusicSwitchContainer",
        "musicsegment": "MusicSegment",
        "musictrack": "MusicTrack",
        "virtualfolder": "Folder",
        "propertycontainer": "Folder",
    }
    return aliases.get(token, value)


def _tab_import_reference_identity(value: str, *, field: str) -> Mapping[str, Any]:
    if value.startswith("\\"):
        return {"kind": "path", "value": value}
    if re.fullmatch(r"\{[0-9A-Fa-f-]{36}\}", value):
        return {"kind": "id", "value": value}
    raise OperationContractError(
        "INVALID_IDENTITY",
        f"{field} reference values must be an absolute Wwise path or canonical GUID.",
        details={"value": value},
    )


def _coerce_tab_import_property_value(
    info: PropertyInfoMetadataRecord,
    value: str,
    *,
    field: str,
) -> Any:
    property_type = info.type.casefold()
    try:
        if property_type in {"bool", "boolean"}:
            normalized = value.casefold()
            if normalized not in {"true", "false"}:
                raise ValueError
            result: Any = normalized == "true"
        elif property_type in {
            "int8",
            "int16",
            "int32",
            "int64",
            "uint8",
            "uint16",
            "uint32",
            "uint64",
            "integer",
        }:
            if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value) is None:
                raise ValueError
            result = int(value, 10)
        elif property_type in {"real32", "real64", "float", "double"}:
            result = float(value)
        elif property_type in {"string", "cstring"}:
            result = value
        else:
            raise ValueError
    except (OverflowError, ValueError) as exc:
        raise OperationContractError(
            "INVALID_PROPERTY_VALUE",
            f"{field} cannot be converted using live property metadata.",
            details={
                "property": info.name,
                "metadata_type": info.type,
                "value": value,
            },
        ) from exc
    _require_object_property_value(info, result)
    return result


def _prepare_closed_import_plan(
    request: OperationRequest,
    *,
    source_operation: str,
    plan: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    oracle = plan.get("oracle")
    policy = plan.get("operation_policy")
    dispatch_args = plan.get("dispatch_args")
    if not isinstance(oracle, Mapping) or not isinstance(policy, Mapping) or not isinstance(dispatch_args, Mapping):
        raise OperationContractError("INVALID_PREVIEW", "Closed import plan is malformed.")
    auto_check_out_supported = (
        request.version in AUTO_CHECK_OUT_TO_SOURCE_CONTROL_VERSIONS
    )
    auto_check_out_dispatched = "autoCheckOutToSourceControl" in dispatch_args
    if auto_check_out_dispatched != auto_check_out_supported:
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Closed import auto-check-out dispatch does not match the Wwise version boundary.",
            details={
                "version": request.version,
                "field_dispatched": auto_check_out_dispatched,
                "supported": auto_check_out_supported,
            },
        )
    if auto_check_out_dispatched and type(
        dispatch_args.get("autoCheckOutToSourceControl")
    ) is not bool:
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Closed import autoCheckOutToSourceControl must be a JSON boolean.",
        )
    source_control_policy = {
        "auto_add_to_source_control": dispatch_args.get(
            "autoAddToSourceControl",
            False,
        ),
        "auto_check_out_to_source_control": dispatch_args.get(
            "autoCheckOutToSourceControl",
            False,
        ),
        "auto_check_out_to_source_control_supported": auto_check_out_supported,
        "auto_check_out_to_source_control_dispatched": auto_check_out_dispatched,
    }
    raw_targets = oracle.get("targets")
    if not isinstance(raw_targets, list) or not all(isinstance(row, Mapping) for row in raw_targets):
        raise OperationContractError("INVALID_PREVIEW", "Closed import target oracle is malformed.")
    if type(dispatch_args.get("autoAddToSourceControl")) is not bool:
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Closed import autoAddToSourceControl must be a JSON boolean.",
        )
    import_operation = policy.get("import_operation")
    roles: dict[str, ResolvedObject] = {}
    targets, dispatch_args, dynamic_roles = _prepare_import_dynamic_fields(
        request,
        source_operation=source_operation,
        raw_targets=raw_targets,
        dispatch_args=dispatch_args,
        read=read,
    )
    roles.update(dynamic_roles)
    path_snapshots: list[dict[str, Any]] = []
    event_paths: set[str] = set()
    allowed_result_paths: set[str] = set()
    for index, raw_target in enumerate(targets):
        target = dict(raw_target)
        target_path = target.get("canonical_target_path")
        if not isinstance(target_path, str):
            raise OperationContractError("INVALID_PREVIEW", "Import target lacks a canonical path.")
        anchor, empty_ancestor_snapshots = _resolve_import_anchor(
            target_path,
            role=f"targets[{index}].anchor",
            read=read,
            version=request.version,
        )
        roles[f"targets[{index}].anchor"] = anchor
        fields = _import_target_return_fields(target, version=request.version)
        read_language = _localized_import_read_language(
            target.get("requested_language")
        )
        read_options = _import_object_get_options(
            fields,
            language=read_language,
        )
        rows = _read_object_path_rows(
            target_path,
            fields=fields,
            read=read,
            language=read_language,
        )
        if len(rows) > 1:
            raise OperationContractError(
                "AMBIGUOUS_IDENTITY",
                "Import target path must resolve to at most one object.",
                details={"path": target_path, "rows": rows},
            )
        if import_operation == "createNew" and rows:
            raise OperationContractError(
                "TARGET_EXISTS",
                "The closed createNew import requires every exact target path to be absent.",
                details={"path": target_path, "rows": rows},
            )
        target["pre_state_rows"] = rows
        target["anchor_id"] = anchor.object
        anchor_path = anchor.row.get("path")
        if not isinstance(anchor_path, str):
            raise OperationContractError("INVALID_READBACK", "Import anchor must expose an absolute path.")
        derived_paths = _import_result_paths_from_anchor(anchor_path, target_path)
        missing_ancestor_paths = derived_paths[:-1]
        ordered_empty_ancestor_snapshots = list(reversed(empty_ancestor_snapshots))
        if [snapshot["path"] for snapshot in ordered_empty_ancestor_snapshots] != missing_ancestor_paths:
            raise OperationContractError(
                "INVALID_READBACK",
                "Import anchor discovery did not prove every derived missing ancestor absent.",
                details={
                    "target_path": target_path,
                    "derived_missing_ancestors": missing_ancestor_paths,
                    "empty_query_paths": [
                        snapshot["path"] for snapshot in ordered_empty_ancestor_snapshots
                    ],
                },
            )
        target["missing_ancestor_paths"] = missing_ancestor_paths
        path_snapshots.extend(ordered_empty_ancestor_snapshots)
        allowed_result_paths.update(path.casefold() for path in derived_paths)
        expected_source_path = target.get(
            "expected_audio_file_source_result_path"
        )
        source_file = target.get("source_file")
        media_expected = target.get("media_expected")
        if not isinstance(media_expected, bool):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "The closed import target lacks an explicit media expectation.",
                details={"target_path": target_path},
            )
        if media_expected:
            if not isinstance(source_file, Mapping):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A media import target lacks a sealed source proof.",
                    details={"target_path": target_path},
                )
            source_kind = source_file.get("kind")
            source_name_path = (
                source_file.get("path")
                if source_kind == "regular_file"
                else source_file.get("relative_path")
                if source_kind == "inline_base64"
                else None
            )
            if (
                not isinstance(source_name_path, str)
                or not isinstance(source_file.get("sha256"), str)
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "The closed import source proof has an unsupported kind or filename.",
                    details={"target_path": target_path, "source_file": source_file},
                )
            try:
                derived_source_path = expected_audio_file_source_result_path(
                    target_path,
                    source_name_path,
                )
            except ImportContractError as exc:
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "The closed import AudioFileSource result path cannot be derived safely.",
                    details=exc.as_dict(),
                ) from exc
        else:
            if source_file is not None or expected_source_path is not None:
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A structure-only import target must not claim media proof or an AudioFileSource.",
                    details={"target_path": target_path},
                )
            derived_source_path = None
        if expected_source_path != derived_source_path:
            raise OperationContractError(
                "INVALID_PREVIEW",
                "The closed import AudioFileSource result path is not bound to the proven source filename.",
                details={
                    "target_path": target_path,
                    "expected": derived_source_path,
                    "actual": expected_source_path,
                },
            )
        if isinstance(expected_source_path, str):
            allowed_result_paths.add(expected_source_path.casefold())
        if rows:
            existing_id = rows[0].get("id")
            if not _valid_object_id(existing_id):
                raise OperationContractError("INVALID_READBACK", "Existing import target lacks a canonical GUID.")
            requested_type = target.get("requested_object_type")
            if isinstance(requested_type, str) and not _import_object_type_matches(
                rows[0].get("type"), requested_type
            ):
                raise OperationContractError(
                    "INVALID_TARGET_TYPE",
                    "An existing import target does not match the requested object type.",
                    details={
                        "path": target_path,
                        "requested_type": requested_type,
                        "actual_type": rows[0].get("type"),
                    },
                )
            target["preexisting_id"] = existing_id
            roles[f"targets[{index}].existing"] = ResolvedObject(
                identity=ObjectIdentity(path=target_path),
                object=existing_id,
                resolution="live-path",
                row=rows[0],
            )
        notes_destination = (
            "audio_file_source"
            if import_operation == "useExisting" and bool(rows)
            else "target_object"
        )
        if (
            notes_destination == "audio_file_source"
            and "requested_notes" in target
            and "requested_audio_source_notes" in target
        ):
            raise OperationContractError(
                "AMBIGUOUS_EXISTING_AUDIO_SOURCE_NOTES",
                "An existing useExisting target cannot seal both Notes and Audio Source Notes "
                "onto the same newly imported AudioFileSource.",
                details={
                    "index": index,
                    "target_path": target_path,
                    "requested_fields": ["notes", "audio_source_notes"],
                },
            )
        target["requested_notes_destination"] = notes_destination
        target_snapshot: dict[str, Any] = {
            "path": target_path,
            "fields": fields,
            "rows": rows,
        }
        if read_language is not None:
            # Confirmation must replay the exact language-scoped accessor read
            # that established this localized row's immutable pre-state.
            target_snapshot["options"] = read_options
        path_snapshots.append(target_snapshot)
        raw_events = target.get("requested_events")
        events = (
            [dict(event) for event in raw_events if isinstance(event, Mapping)]
            if isinstance(raw_events, list)
            else (
                [dict(target["requested_event"])]
                if isinstance(target.get("requested_event"), Mapping)
                else []
            )
        )
        event_pre_state: list[dict[str, Any]] = []
        for event_index, event in enumerate(events):
            _require_exact_keys(
                event,
                required=("path", "action"),
                context=f"targets[{index}].events[{event_index}]",
            )
            event_path = event.get("path")
            event_action = event.get("action")
            action_types = _IMPORT_EVENT_ACTION_TYPES_BY_VERSION.get(request.version)
            if (
                not isinstance(event_path, str)
                or not event_path.startswith("\\")
                or not isinstance(event_action, str)
                or not isinstance(action_types, Mapping)
                or event_action not in action_types
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Requested Event path or action is outside the closed versioned import contract.",
                    details={"version": request.version, "event": dict(event)},
                )
            event_key = event_path.casefold()
            if event_key in event_paths:
                raise OperationContractError(
                    "AMBIGUOUS_EVENT_MAPPING",
                    "Each closed import row must own a distinct new Event path.",
                    details={"event_path": event_path},
                )
            event_paths.add(event_key)
            event_rows = _read_object_path_rows(event_path, fields=IDENTITY_RETURN_FIELDS, read=read)
            if len(event_rows) > 1:
                raise OperationContractError("AMBIGUOUS_IDENTITY", "Requested Event path is ambiguous.")
            if event_rows:
                raise OperationContractError(
                    "EVENT_TARGET_EXISTS",
                    "The closed import Event field only supports a new, case-owned Event path.",
                    details={"event_path": event_path, "rows": event_rows},
                )
            event_pre_state.append({"path": event_path, "rows": event_rows})
            path_snapshots.append({"path": event_path, "fields": list(IDENTITY_RETURN_FIELDS), "rows": event_rows})
        if events:
            target["validated_events"] = events
            target["event_pre_state"] = event_pre_state
            if len(events) == 1:
                target["event_pre_state_rows"] = event_pre_state[0]["rows"]
        targets[index] = target

    if import_operation == "useExisting":
        unsupported_existing_rows: list[dict[str, Any]] = []
        for index, target in enumerate(targets):
            if not target.get("pre_state_rows"):
                continue
            language = target.get("requested_language")
            localized_existing = (
                isinstance(language, str) and language.casefold() != "sfx"
            )
            if not localized_existing:
                continue
            unsupported = unsupported_localized_existing_fields(
                import_language=language,
                originals_subfolder_supplied=(
                    "requested_originals_subfolder" in target
                ),
                notes_supplied="requested_notes" in target,
                audio_source_notes_supplied=(
                    "requested_audio_source_notes" in target
                ),
                event_supplied=(
                    "requested_event" in target
                    or bool(target.get("requested_events"))
                ),
            )
            additional_unsupported = [
                field_name
                for field_name, present in (
                    ("audio_file_base64", (
                        isinstance(target.get("source_file"), Mapping)
                        and target["source_file"].get("kind") == "inline_base64"
                    )),
                    ("import_location", "requested_import_location" in target),
                    ("dialogue_event", (
                        "requested_dialogue_event" in target
                        or bool(target.get("requested_dialogue_events"))
                    )),
                    ("switch_assignment", (
                        "requested_switch_assignment" in target
                        or bool(target.get("requested_switch_assignments"))
                    )),
                    ("properties", bool(target.get("validated_properties"))),
                    ("references", bool(target.get("validated_references"))),
                    ("dynamic_fields", bool(target.get("requested_dynamic_fields"))),
                )
                if present
            ]
            unsupported = (*unsupported, *additional_unsupported)
            if (
                source_operation == "audio.importTabDelimited"
                and "requested_object_type" in target
            ):
                unsupported = ("object_type", *unsupported)
            if unsupported:
                unsupported_existing_rows.append(
                    {
                        "index": index,
                        "target_path": target.get("canonical_target_path"),
                        "import_language": target.get("requested_language"),
                        "unsupported_fields": list(unsupported),
                    }
                )
        if unsupported_existing_rows:
            raise OperationContractError(
                "LOCALIZED_EXISTING_IMPORT_FIELDS",
                "A localized useExisting row that resolves to a live target may "
                "dispatch only audioFile, objectPath, and importLanguage. Remove "
                "creation/placement fields or submit their semantics through a "
                "separately previewed operation.",
                details={
                    "import_operation": import_operation,
                    "call_wide_rejection": True,
                    "rows": unsupported_existing_rows,
                },
            )

    if source_operation == "audio.import":
        logical_target_paths = {
            str(target.get("canonical_target_path")).casefold()
            for target in targets
            if isinstance(target.get("canonical_target_path"), str)
        }
        seen_explicit_source_paths: set[str] = set()
        for index, raw_target in enumerate(targets):
            target = dict(raw_target)
            dynamic_fields_present = bool(
                target.get("validated_properties")
                or target.get("validated_references")
            )
            if not dynamic_fields_present or target.get("media_expected") is not True:
                continue
            metadata_type = target.get("metadata_object_type")
            expected_source_path = target.get(
                "expected_audio_file_source_result_path"
            )
            if _object_type_token(metadata_type) != "sound":
                raise OperationContractError(
                    "IMPORT_DYNAMIC_MEDIA_TOPOLOGY_UNSUPPORTED",
                    "Dynamic fields with media require a live-validated Sound target.",
                    details={
                        "index": index,
                        "metadata_object_type": metadata_type,
                    },
                )
            if not isinstance(expected_source_path, str):
                raise OperationContractError(
                    "IMPORT_DYNAMIC_MEDIA_TOPOLOGY_UNSUPPORTED",
                    "This media type has no sealed AudioFileSource topology for dynamic Sound fields.",
                    details={
                        "index": index,
                        "target_path": target.get("canonical_target_path"),
                    },
                )
            source_key = expected_source_path.casefold()
            if (
                source_key in logical_target_paths
                or source_key in seen_explicit_source_paths
            ):
                raise OperationContractError(
                    "DUPLICATE_TARGET",
                    "An explicit AudioFileSource path collides with another logical import target.",
                    details={
                        "index": index,
                        "source_path": expected_source_path,
                    },
                )
            seen_explicit_source_paths.add(source_key)
            read_language = _localized_import_read_language(
                target.get("requested_language")
            )
            source_fields = _import_audio_source_return_fields(
                version=request.version
            )
            source_rows = _read_object_path_rows(
                expected_source_path,
                fields=source_fields,
                read=read,
                language=read_language,
            )
            if len(source_rows) > 1:
                raise OperationContractError(
                    "AMBIGUOUS_IDENTITY",
                    "The explicit AudioFileSource path is ambiguous.",
                    details={
                        "index": index,
                        "path": expected_source_path,
                        "rows": source_rows,
                    },
                )
            if source_rows:
                source_row = source_rows[0]
                if (
                    not _valid_object_id(source_row.get("id"))
                    or source_row.get("path") != expected_source_path
                    or _object_type_token(source_row.get("type"))
                    != "audiofilesource"
                ):
                    raise OperationContractError(
                        "INVALID_READBACK",
                        "The sealed media path did not return one exact canonical AudioFileSource identity.",
                        details={
                            "index": index,
                            "path": expected_source_path,
                            "row": source_row,
                        },
                    )
            target["explicit_audio_file_source_pre_state_rows"] = source_rows
            source_snapshot: dict[str, Any] = {
                "path": expected_source_path,
                "fields": source_fields,
                "rows": source_rows,
            }
            if read_language is not None:
                source_snapshot["options"] = _import_object_get_options(
                    source_fields,
                    language=read_language,
                )
            path_snapshots.append(source_snapshot)
            targets[index] = target

    preflight_consumed_fields: list[dict[str, Any]] = []
    localized_existing_wire_normalizations: list[dict[str, Any]] = []
    if source_operation == "audio.import" and import_operation == "useExisting":
        raw_dispatch_rows = dispatch_args.get("imports")
        if (
            not isinstance(raw_dispatch_rows, list)
            or len(raw_dispatch_rows) != len(targets)
            or not all(isinstance(row, Mapping) for row in raw_dispatch_rows)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Closed audio.import dispatch rows are not bound one-to-one to targets.",
            )
        trusted_dispatch_rows: list[dict[str, Any]] = []
        for index, (raw_row, target) in enumerate(
            zip(raw_dispatch_rows, targets, strict=True)
        ):
            row = dict(raw_row)
            language = target.get("requested_language")
            localized_existing = (
                bool(target.get("pre_state_rows"))
                and isinstance(language, str)
                and language.casefold() != "sfx"
            )
            if localized_existing:
                target_path = target.get("canonical_target_path")
                canonical_parent = target.get("canonical_parent_path")
                pre_state_rows = target.get("pre_state_rows")
                requested_type = target.get("requested_object_type")
                if (
                    not isinstance(target_path, str)
                    or not isinstance(canonical_parent, str)
                    or not isinstance(pre_state_rows, list)
                    or len(pre_state_rows) != 1
                    or not isinstance(pre_state_rows[0], Mapping)
                ):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A localized existing audio.import target lacks its exact canonical live pre-state.",
                        details={"index": index, "target": target},
                    )
                parent, separator, leaf = target_path.rpartition("\\")
                if (
                    not separator
                    or not parent
                    or not leaf
                    or canonical_parent != parent
                    or "<" in target_path
                    or ">" in target_path
                ):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A localized existing audio.import target has a malformed canonical logical path.",
                        details={
                            "index": index,
                            "target_path": target_path,
                            "canonical_parent_path": canonical_parent,
                        },
                    )
                live_type = pre_state_rows[0].get("type")
                if not _import_object_type_matches(live_type, "Sound Voice"):
                    raise OperationContractError(
                        "INVALID_TARGET_TYPE",
                        "A localized existing audio.import target must resolve to a Sound Voice-compatible object.",
                        details={
                            "index": index,
                            "target_path": target_path,
                            "required_type": "Sound Voice",
                            "actual_type": live_type,
                        },
                    )
                if (
                    isinstance(requested_type, str)
                    and _object_type_token(requested_type) not in {"sound", "soundvoice"}
                ):
                    raise OperationContractError(
                        "INVALID_TARGET_TYPE",
                        "An explicit object_type conflicts with the localized Sound Voice wire target.",
                        details={
                            "index": index,
                            "target_path": target_path,
                            "requested_type": requested_type,
                            "required_type": "Sound Voice",
                        },
                    )
                input_object_path = row.get("objectPath")
                if not isinstance(input_object_path, str):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A localized existing audio.import row lacks its requested objectPath.",
                        details={"index": index, "objectPath": input_object_path},
                    )
                wire_object_path = f"{canonical_parent}\\<Sound Voice>{leaf}"
                row["objectPath"] = wire_object_path
                consumed: list[str] = []
                if "objectType" in row:
                    row.pop("objectType")
                    consumed.append("object_type")
                expected_wire_fields = {"audioFile", "objectPath", "importLanguage"}
                if set(row) != expected_wire_fields:
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A localized existing audio.import row did not reduce to the "
                        "closed three-field wire contract.",
                        details={
                            "index": index,
                            "target_path": target.get("canonical_target_path"),
                            "actual_fields": sorted(str(key) for key in row),
                            "expected_fields": sorted(expected_wire_fields),
                        },
                    )
                localized_existing_wire_normalizations.append(
                    {
                        "index": index,
                        "input_object_path": input_object_path,
                        "logical_target_path": target_path,
                        "wire_object_path": wire_object_path,
                        "wire_object_type": "Sound Voice",
                        "basis": {
                            "import_operation": "useExisting",
                            "preexisting_id": target.get("preexisting_id"),
                            "reflected_type": live_type,
                            "requested_language": language,
                        },
                    }
                )
                if consumed:
                    preflight_consumed_fields.append(
                        {
                            "index": index,
                            "target_path": target.get("canonical_target_path"),
                            "fields": consumed,
                            "proof": "live target type matched before dispatch",
                        }
                    )
            trusted_dispatch_rows.append(row)
        dispatch_args = {**dict(dispatch_args), "imports": trusted_dispatch_rows}
        plan = {**dict(plan), "dispatch_args": dispatch_args}

    native_row_mapping: list[dict[str, Any]] = []
    if source_operation == "audio.import":
        dispatch_args, native_row_mapping = _materialize_audio_import_dynamic_rows(
            dispatch_args=dispatch_args,
            targets=targets,
        )
        plan = {**dict(plan), "dispatch_args": dispatch_args}

    requested_languages = sorted(
        {
            str(target["requested_language"])
            for target in targets
            if language_requires_live_project_validation(
                target.get("requested_language")
            )
        }
    )
    language_validation_flag = oracle.get(
        "language_requires_live_project_validation"
    )
    if (
        not isinstance(language_validation_flag, bool)
        or language_validation_flag != bool(requested_languages)
    ):
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Closed import language-validation policy is malformed.",
            details={
                "declared": language_validation_flag,
                "localized_languages": requested_languages,
            },
        )
    # Every copied-media hash proof is bound to the live Project Originals
    # root.  This also gives Wine ``Y:\``/``Z:\`` result paths one sealed,
    # exact wire-to-host mapping and prevents verification against an
    # unrelated host file with matching bytes.
    media_present = any(target.get("media_expected") is True for target in targets)
    originals_context: Mapping[str, Any] | None = (
        _read_import_originals_context(
            request.version,
            read=read,
        )
        if media_present
        else None
    )
    language_inventory: Mapping[str, Any] | None = None
    if requested_languages:
        language_inventory = _read_import_language_inventory(request.version, read=read)
        available_names = {
            str(row["name"])
            for row in language_inventory.get("languages", [])
            if isinstance(row, Mapping) and isinstance(row.get("name"), str)
        }
        unavailable = [name for name in requested_languages if name not in available_names]
        if unavailable:
            raise OperationContractError(
                "IMPORT_LANGUAGE_UNAVAILABLE",
                "Every import language must exactly match the live Project language inventory.",
                details={
                    "requested": requested_languages,
                    "unavailable": unavailable,
                    "available": sorted(available_names),
                },
            )

    uri = (
        "ak.wwise.core.audio.import"
        if source_operation == "audio.import"
        else "ak.wwise.core.audio.importTabDelimited"
    )
    preview = _closed_operation_preview(
        uri=uri,
        args=dispatch_args,
        options={
            "return": _dedupe_fields(
                field
                for target in targets
                for field in _import_target_return_fields(
                    target,
                    version=request.version,
                )
            )
        },
        version=request.version,
        family="import",
        metadata={
            "closed_import_plan": plan.get("contract"),
            "import_operation": import_operation,
            "target_count": len(targets),
            "native_row_count": (
                len(dispatch_args.get("imports", []))
                if source_operation == "audio.import"
                and isinstance(dispatch_args.get("imports"), list)
                else 1
            ),
            "caller_expected_rows_accepted": False,
            "source_control_policy": source_control_policy,
            "preflight_consumed_fields": preflight_consumed_fields,
            **(
                {"native_row_mapping": native_row_mapping}
                if native_row_mapping
                else {}
            ),
            **(
                {
                    "localized_existing_wire_normalizations": localized_existing_wire_normalizations,
                }
                if localized_existing_wire_normalizations
                else {}
            ),
        },
    )
    file_proofs: list[dict[str, Any]] = []
    if isinstance(plan.get("import_file_proof"), Mapping):
        file_proofs.append({"field": "import_file", "proof": dict(plan["import_file_proof"])})
    for proof_key in ("file_proofs", "source_file_proofs"):
        raw_proofs = plan.get(proof_key)
        if isinstance(raw_proofs, list):
            for proof in raw_proofs:
                if isinstance(proof, Mapping):
                    label = f"{proof_key}[{len(file_proofs)}]"
                    file_proofs.append({"field": label, "proof": dict(proof)})
    wire_path_input_audit: dict[str, Any] | None = None
    if source_operation == "audio.importTabDelimited":
        import_file_proof = plan.get("import_file_proof")
        import_file_path = dispatch_args.get("importFile")
        proven_path = (
            import_file_proof.get("path")
            if isinstance(import_file_proof, Mapping)
            else None
        )
        if (
            not isinstance(import_file_path, str)
            or not isinstance(proven_path, str)
            or not Path(proven_path).is_absolute()
            or import_file_path != proven_path
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Tab-delimited import wire-path input is not bound to its canonical file proof.",
            )
        wire_path_input_audit = {
            "contract": WWISE_WIRE_PATH_INPUT_AUDIT_CONTRACT,
            "uri": uri,
            "scope": "transient_dispatch_read_paths_only",
            "paths": [
                {
                    "section": "args",
                    "json_path": "$.args.importFile",
                    "field": "importFile",
                    "role": "read",
                    "raw_path": import_file_path,
                    "resolved_path": proven_path,
                }
            ],
        }
    guard = {
        "source_operation": source_operation,
        "file_proofs": file_proofs,
        "path_snapshots": path_snapshots,
        "language_inventory": _json_mapping(language_inventory) if language_inventory is not None else None,
    }
    if wire_path_input_audit is not None:
        guard["wire_path_input_audit"] = wire_path_input_audit
    guard["originals_context"] = (
        _json_mapping(originals_context)
        if originals_context is not None
        else None
    )
    verification = {
        "kind": "closed-audio-import",
        "source_operation": source_operation,
        "uri": uri,
        "version": request.version,
        "import_operation": import_operation,
        "targets": targets,
        "allowed_result_paths": sorted(allowed_result_paths),
        "result_contract": oracle.get("result_contract"),
        "error_log_is_failure": True,
        "native_directive_boundaries": sorted(
            {
                boundary
                for target in targets
                for boundary, present in (
                    (
                        "dialogue_event_result_and_target_verified_side_effect_not_fully_reconstructed",
                        "requested_dialogue_event" in target
                        or bool(target.get("requested_dialogue_events")),
                    ),
                    (
                        "switch_assignment_result_and_target_verified_side_effect_not_fully_reconstructed",
                        "requested_switch_assignment" in target
                        or bool(target.get("requested_switch_assignments")),
                    ),
                )
                if present
            }
        ),
    }
    verification["originals_context"] = (
        _json_mapping(originals_context)
        if originals_context is not None
        else None
    )
    cleanup = {
        "kind": "discard-case-owned-project-copy",
        "automatic": False,
        "automatic_retry": False,
        "irreversible": import_operation == "replaceExisting",
        "created_guid_source": "execution_result.result.objects",
    }
    state = {"closed_import_plan": _json_mapping(plan), "import_guard": guard}
    return preview, roles, state, verification, cleanup


def _resolve_import_anchor(
    target_path: str,
    *,
    role: str,
    read: ReadCall,
    version: str,
) -> tuple[ResolvedObject, list[dict[str, Any]]]:
    segments = target_path[1:].split("\\") if target_path.startswith("\\") else []
    if len(segments) < 3:
        raise OperationContractError("INVALID_TARGET", "Import target path is too shallow.")
    empty_snapshots: list[dict[str, Any]] = []
    for end in range(len(segments) - 1, 1, -1):
        candidate = "\\" + "\\".join(segments[:end])
        rows = _read_object_path_rows(candidate, fields=IDENTITY_RETURN_FIELDS, read=read)
        if not rows:
            empty_snapshots.append(
                {
                    "path": candidate,
                    "fields": list(IDENTITY_RETURN_FIELDS),
                    "rows": [],
                }
            )
            continue
        if len(rows) != 1:
            raise OperationContractError("AMBIGUOUS_IDENTITY", "Import anchor path is ambiguous.", details={"path": candidate})
        row = rows[0]
        if row.get("path") != candidate:
            raise OperationContractError(
                "IDENTITY_MISMATCH",
                "Import anchor query returned an object at a different path.",
                details={"requested_path": candidate, "actual_row": row},
            )
        object_id = row.get("id")
        if not _valid_object_id(object_id):
            raise OperationContractError("INVALID_READBACK", "Import anchor lacks a canonical GUID.")
        resolved = ResolvedObject(
            identity=ObjectIdentity(path=candidate),
            object=object_id,
            resolution="live-path",
            row=row,
        )
        _require_import_parent(
            resolved,
            index=0,
            version=version,
        )
        return resolved, empty_snapshots
    raise OperationContractError(
        "IMPORT_ANCHOR_NOT_FOUND",
        "No writable existing ancestor was found for the import target.",
        details={"target_path": target_path, "role": role},
    )


def _import_result_paths_from_anchor(anchor_path: str, target_path: str) -> list[str]:
    """Return the only result paths one import row may legitimately create.

    The anchor is the deepest live ancestor found during preflight, so every
    intermediate path below it was absent before dispatch.  This derives a
    closed allowlist without accepting arbitrary extra result objects.
    """

    if not anchor_path.startswith("\\") or not target_path.startswith("\\"):
        raise OperationContractError(
            "INVALID_READBACK",
            "Import anchor and target paths must be absolute Wwise paths.",
        )
    anchor = anchor_path.rstrip("\\")
    if not target_path.casefold().startswith((anchor + "\\").casefold()):
        raise OperationContractError(
            "IDENTITY_MISMATCH",
            "Import target is not a strict descendant of its live anchor.",
            details={"anchor_path": anchor_path, "target_path": target_path},
        )
    suffix = target_path[len(anchor) + 1 :]
    segments = suffix.split("\\")
    if not segments or any(not segment for segment in segments):
        raise OperationContractError(
            "INVALID_TARGET",
            "Import target contains an invalid path segment below its anchor.",
            details={"anchor_path": anchor_path, "target_path": target_path},
        )
    paths: list[str] = []
    current = anchor
    for segment in segments:
        current += "\\" + segment
        paths.append(current)
    return paths


def _import_target_return_fields(
    target: Mapping[str, Any],
    *,
    version: str,
) -> list[str]:
    fields = [*IDENTITY_RETURN_FIELDS]
    # Wwise 2021.1 rejects the otherwise useful ``activeSource`` and
    # ``originalFilePath`` accessors on the imported Sound object.  Its import
    # result still returns the created AudioFileSource, so the verifier binds
    # that child directly and uses the older Sound accessors for language/path.
    fields.extend(
        (
            ("sound:originalWavFilePath", "audioSource:language")
            if version == "2021.1"
            else (
                "activeSource",
                "originalFilePath",
                "sound:originalWavFilePath",
                "audioSource:language",
            )
        )
    )
    for key in ("validated_properties", "validated_references"):
        descriptors = target.get(key)
        if not isinstance(descriptors, list):
            continue
        for descriptor in descriptors:
            name = descriptor.get("name") if isinstance(descriptor, Mapping) else None
            if isinstance(name, str) and name:
                fields.append(f"@{name}")
    # Wwise 2022.1 rejects ``originalRelativeFilePath``, and the manifests do
    # not establish dynamic object.get accessor support in the other lanes.
    # Every lane therefore derives the relative path from an authoritative
    # Project Originals root plus the absolute copied-file accessor.
    return _dedupe_fields(fields)


def _import_audio_source_return_fields(*, version: str) -> list[str]:
    fields = [
        "id",
        "name",
        "type",
        "path",
        "notes",
        "audioSource:language",
    ]
    if version != "2021.1":
        fields.insert(-1, "originalFilePath")
    return fields


def _normalize_import_event_action_type(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _import_event_action_target_matches(
    value: Any,
    *,
    expected_id: Any,
    expected_path: str,
) -> bool:
    if not _valid_object_id(expected_id) or not expected_path.startswith("\\"):
        return False
    if isinstance(value, Mapping):
        compared = False
        if "id" in value:
            compared = True
            if not _same_identity(value.get("id"), expected_id):
                return False
        if "path" in value:
            compared = True
            if not _same_identity(value.get("path"), expected_path):
                return False
        if "object" in value:
            compared = True
            if not _import_event_action_target_matches(
                value.get("object"),
                expected_id=expected_id,
                expected_path=expected_path,
            ):
                return False
        return compared
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return _same_identity(value, expected_id) or _same_identity(value, expected_path)
    return False


def _prepare_closed_soundbank_operation(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    roles: dict[str, ResolvedObject] = {}
    io_root = _non_empty_string(arguments.get("io_root"), field="io_root")
    project_info, project_authority, project_validation = _soundbank_project_info(
        request.version,
        io_root=io_root,
        roles=roles,
        read=read,
    )
    if request.operation == "soundbank.generate":
        plan_arguments = _normalize_generate_arguments(arguments, roles=roles, read=read)
        plan = _build_soundbank_plan(
            request.operation,
            plan_arguments,
            version=request.version,
            project_info=project_info,
            io_root=io_root,
            project_context_authority=project_authority,
        )
    elif request.operation == "soundbank.convertExternalSources":
        plan_arguments = {"sources": [dict(row) for row in _mapping_sequence(arguments.get("sources"), field="sources")]}
        plan = _build_soundbank_plan(
            request.operation,
            plan_arguments,
            version=request.version,
            project_info=project_info,
            io_root=io_root,
            project_context_authority=project_authority,
        )
        _resolve_external_source_conversions(plan, roles=roles, read=read)
    else:
        files = arguments.get("files")
        if not isinstance(files, list):  # parse_operation_request closes this branch.
            raise OperationContractError("INVALID_ARGUMENT", "files must be an array.")
        plan_arguments = {"files": list(files)}
        plan = _build_soundbank_plan(
            request.operation,
            plan_arguments,
            version=request.version,
            project_info=project_info,
            io_root=io_root,
            project_context_authority=project_authority,
        )

    snapshots = _capture_soundbank_artifact_snapshots(plan, io_root=io_root)
    definition_oracle: Mapping[str, Any] | None = None
    if request.operation == "soundbank.processDefinitionFiles":
        definition_oracle = _prepare_definition_oracle(plan, roles=roles, read=read)

    uri = describe_operation(request.operation).uri
    dispatch_args = plan.get("dispatch_args")
    if not isinstance(dispatch_args, Mapping):
        raise OperationContractError("INVALID_PREVIEW", "Closed SoundBank plan lacks dispatch_args.")
    wire_path_io_audit: Mapping[str, Any] | None = None
    if request.operation in {
        "soundbank.convertExternalSources",
        "soundbank.processDefinitionFiles",
    }:
        try:
            wire_path_io_audit = validate_isolated_io(
                version=request.version,
                uri=uri,
                args=dispatch_args,
                options={},
                io_root=io_root,
            ).as_dict()
        except IOPolicyError as exc:
            raise OperationContractError(
                exc.error_code,
                str(exc),
                details={"io_policy": exc.as_dict()},
            ) from exc
    preview = _closed_operation_preview(
        uri=uri,
        args=dispatch_args,
        options={},
        version=request.version,
        family="closed-soundbank",
        metadata={
            "closed_soundbank_plan": plan.get("contract"),
            "plan_sha256": plan.get("plan_sha256"),
            "project_context_authority": project_authority,
            "project_info_validation": project_validation,
            "artifact_snapshot_count": len(snapshots),
            "caller_expected_rows_accepted": False,
        },
    )
    guard: dict[str, Any] = {
        "kind": request.operation,
        "version": request.version,
        "plan_arguments": _json_mapping(plan_arguments),
        "io_root": io_root,
        "project_context_authority": project_authority,
        "plan_sha256": plan.get("plan_sha256"),
        "artifact_snapshots": snapshots,
    }
    if wire_path_io_audit is not None:
        guard["io_audit"] = _json_mapping(wire_path_io_audit)
    if definition_oracle is not None:
        guard["definition_oracle"] = _json_mapping(definition_oracle)
    verification: dict[str, Any] = {
        "kind": (
            "soundbank-definition-exact"
            if request.operation == "soundbank.processDefinitionFiles"
            else "soundbank-artifact-exact"
        ),
        "source_operation": request.operation,
        "uri": uri,
        "version": request.version,
        "plan": _json_mapping(plan),
        "artifact_snapshots": snapshots,
    }
    if definition_oracle is not None:
        verification["definition_oracle"] = _json_mapping(definition_oracle)
    cleanup = {
        "kind": "discard-case-owned-project-copy-and-output-root",
        "automatic": False,
        "automatic_retry": False,
        "failure_policy": "seal_or_quarantine_failed_sandbox_and_never_reuse",
        "success_policy": "discard_the_complete_case_owned_sandbox",
        "io_root": io_root,
    }
    return preview, roles, {"soundbank_guard": guard}, verification, cleanup


def _soundbank_project_info(
    version: str,
    *,
    io_root: str,
    roles: dict[str, ResolvedObject],
    read: ReadCall,
) -> tuple[dict[str, Any], str, Mapping[str, Any]]:
    if version == "2021.1":
        query = "from type Project take 2"
        options = {
            "return": [
                "id",
                "name",
                "type",
                "path",
                "filePath",
                "workunitIsDirty",
            ]
        }
        result = read(OBJECT_GET_URI, {"waql": query}, options)
        rows = _rows(result)
        if len(rows) != 1:
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                "Wwise 2021.1 must expose exactly one live Project row with file evidence.",
                details={"query": query, "rows": rows},
            )
        row = rows[0]
        if row.get("type") != "Project" or row.get("path") != "\\":
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                "The Wwise 2021.1 Project query must return the unique Project root at path \\.",
                details={"row": row},
            )
        project_file = _localize_waapi_file_path(row.get("filePath"))
        try:
            project_info = parse_wwise_2021_project_file(
                project_file,
                io_root=io_root,
                live_project_id=row.get("id"),
                live_project_name=row.get("name"),
                workunit_is_dirty=row.get("workunitIsDirty"),
            )
        except SoundBankContractError as exc:
            raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
        roles["active_project"] = _resolved_waql_row(query, row)
        source = project_info.get("wwiseProjectFile")
        return project_info, "waapi_object_get_filePath_plus_hashed_wproj", {
            "strategy": "live_object_get_filePath_plus_hashed_strict_wproj",
            "query": query,
            "options": options,
            "active_project_id": row.get("id"),
            "file_proof_sha256": (
                source.get("file_proof", {}).get("proof_sha256")
                if isinstance(source, Mapping)
                and isinstance(source.get("file_proof"), Mapping)
                else None
            ),
        }

    result = read(GET_PROJECT_INFO_URI, {}, {})
    try:
        validation = validate_semantic_result(GET_PROJECT_INFO_URI, result, version=version)
    except SemanticValidationError as exc:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "core.getProjectInfo did not match the packaged versioned result schema.",
            details=exc.as_dict(),
        ) from exc
    localized = _localize_soundbank_project_info(result, io_root=io_root)
    return localized, "waapi_getProjectInfo", validation.as_dict()


def _localize_soundbank_project_info(
    value: Mapping[str, Any],
    *,
    io_root: str,
) -> dict[str, Any]:
    """Bind live ``getProjectInfo`` paths to one caller-owned sandbox.

    Wwise running through Wine reports absolute host paths with ``Y:``/``Z:``
    spellings.  Some builds also report project-setting directories relative to
    the project root.  Neither form may be interpreted relative to this
    process' current working directory: the live project file is the authority
    for the relative base, and every localized path must remain under the
    already explicit transaction ``io_root``.
    """

    normalized = dict(value)
    project_file = Path(
        _localize_waapi_file_path(
            value.get("path"),
            field="project_info.path",
        )
    )
    io_path = Path(
        _localize_waapi_file_path(
            io_root,
            field="io_root",
        )
    )
    project_file_resolved = project_file.resolve(strict=False)
    io_resolved = io_path.resolve(strict=False)
    if not _path_is_within(project_file_resolved, io_resolved):
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "The active project file is outside the explicit SoundBank I/O root.",
            details={
                "project_info.path": str(project_file),
                "localized_project_path": str(project_file_resolved),
                "io_root": str(io_resolved),
            },
        )
    project_root = project_file.parent

    raw_directories = value.get("directories")
    if not isinstance(raw_directories, Mapping):
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "project_info.directories must be a JSON object.",
        )
    directories = dict(raw_directories)
    localized_root = _localize_soundbank_project_directory(
        raw_directories.get("root"),
        field="project_info.directories.root",
        project_root=project_root,
        io_root=io_path,
        allow_parent_segments=False,
    )
    if localized_root.resolve(strict=False) != project_root.resolve(strict=False):
        raise OperationContractError(
            "PROJECT_PATH_MISMATCH",
            "project_info.directories.root does not identify the directory containing the active project file.",
            details={
                "project_info.path": str(project_file),
                "reported_root": raw_directories.get("root"),
                "localized_root": str(localized_root),
                "expected_root": str(project_root),
            },
        )
    directories["root"] = str(localized_root)
    for field_name in (
        "cache",
        "originals",
        "soundBankOutputRoot",
        "commands",
        "properties",
    ):
        if field_name not in raw_directories:
            continue
        directories[field_name] = str(
            _localize_soundbank_project_directory(
                raw_directories[field_name],
                field=f"project_info.directories.{field_name}",
                project_root=localized_root,
                io_root=io_path,
            )
        )

    raw_platforms = value.get("platforms")
    if not isinstance(raw_platforms, list):
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            "project_info.platforms must be a JSON array.",
        )
    platforms: list[dict[str, Any]] = []
    for index, raw_platform in enumerate(raw_platforms):
        if not isinstance(raw_platform, Mapping):
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                "project_info.platforms entries must be JSON objects.",
                details={"index": index},
            )
        platform = dict(raw_platform)
        for field_name in ("soundBankPath", "copiedMediaPath"):
            if field_name not in raw_platform:
                continue
            platform[field_name] = str(
                _localize_soundbank_project_directory(
                    raw_platform[field_name],
                    field=f"project_info.platforms[{index}].{field_name}",
                    project_root=localized_root,
                    io_root=io_path,
                )
            )
        platforms.append(platform)

    normalized["path"] = str(project_file)
    normalized["directories"] = directories
    normalized["platforms"] = platforms
    return normalized


def _localize_soundbank_project_directory(
    value: Any,
    *,
    field: str,
    project_root: Path,
    io_root: Path,
    allow_parent_segments: bool = True,
) -> Path:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{field} must be a non-empty path string.",
            details={field: value},
        )
    try:
        parse_absolute_host_path(value, allow_trailing_separator=True)
    except HostPathError:
        try:
            relative = parse_relative_host_path(
                value,
                allow_current_directory=True,
                allow_parent_segments=allow_parent_segments,
            )
        except HostPathError as exc:
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                f"{field} contains an unsafe relative path.",
                details={field: value, "path_error": str(exc)},
            ) from exc
        candidate = project_root.joinpath(*relative.components)
    else:
        candidate = Path(_localize_waapi_file_path(value, field=field))
    try:
        resolved = candidate.resolve(strict=False)
        io_resolved = io_root.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{field} could not be resolved safely.",
            details={field: value, "localized": str(candidate), "error": str(exc)},
        ) from exc
    if not _path_is_within(resolved, io_resolved):
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{field} resolves outside the explicit SoundBank I/O root.",
            details={
                field: value,
                "localized": str(candidate),
                "resolved": str(resolved),
                "io_root": str(io_resolved),
            },
        )
    return resolved


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _localize_waapi_file_path(
    value: Any,
    *,
    field: str = "live Project filePath",
) -> str:
    try:
        return localize_waapi_host_path(value)
    except HostPathError as exc:
        details: dict[str, Any] = {field: value, "reason": str(exc)}
        details.update(exc.details)
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{field} is not a safe local filesystem path: {exc}",
            details=details,
        ) from exc


def _normalize_generate_arguments(
    arguments: Mapping[str, Any],
    *,
    roles: dict[str, ResolvedObject],
    read: ReadCall,
) -> dict[str, Any]:
    normalized_banks: list[dict[str, Any]] = []
    for bank_index, bank in enumerate(_mapping_sequence(arguments.get("soundbanks"), field="soundbanks")):
        normalized: dict[str, Any] = {
            "name": bank.get("name"),
            "artifactExpectation": bank.get("artifact_expectation"),
        }
        for public_name, plan_name, expected_type in (
            ("events", "events", "Event"),
            ("aux_busses", "auxBusses", "AuxBus"),
        ):
            if public_name not in bank:
                continue
            values = bank.get(public_name)
            if not isinstance(values, list):
                raise OperationContractError("INVALID_ARGUMENT", f"soundbanks[{bank_index}].{public_name} must be an array.")
            ids: list[Any] = []
            for value_index, value in enumerate(values):
                role = f"soundbanks[{bank_index}].{public_name}[{value_index}]"
                resolved = _resolve_identity(value, role=role, read=read)
                if resolved.row.get("type") != expected_type:
                    raise OperationContractError(
                        "INVALID_TARGET_TYPE",
                        f"{role} must resolve to {expected_type}.",
                        details={"actual_type": resolved.row.get("type"), "row": dict(resolved.row)},
                    )
                roles[role] = resolved
                ids.append(resolved.object)
            normalized[plan_name] = ids
        for name in ("inclusions", "rebuild"):
            if name in bank:
                normalized[name] = bank[name]
        normalized_banks.append(normalized)
    result: dict[str, Any] = {
        "soundbanks": normalized_banks,
        "platforms": list(arguments.get("platforms", [])),
        "skipLanguages": arguments.get("skip_languages"),
        "writeToDisk": arguments.get("write_to_disk"),
    }
    optional_map = {
        "languages": "languages",
        "rebuild_soundbanks": "rebuildSoundBanks",
        "clear_audio_file_cache": "clearAudioFileCache",
        "rebuild_init_bank": "rebuildInitBank",
    }
    for public_name, plan_name in optional_map.items():
        if public_name in arguments:
            result[plan_name] = arguments[public_name]
    return result


def _build_soundbank_plan(
    operation: str,
    arguments: Mapping[str, Any],
    *,
    version: str,
    project_info: Mapping[str, Any],
    io_root: str,
    project_context_authority: str,
) -> dict[str, Any]:
    try:
        if operation == "soundbank.generate":
            return build_generate_operation_plan(
                arguments,
                version=version,
                project_info=project_info,
                io_root=io_root,
                project_context_authority=project_context_authority,
            )
        if operation == "soundbank.convertExternalSources":
            return build_external_sources_operation_plan(
                arguments,
                version=version,
                project_info=project_info,
                io_root=io_root,
                project_context_authority=project_context_authority,
            )
        if operation == "soundbank.processDefinitionFiles":
            return build_process_definition_operation_plan(
                arguments,
                version=version,
                project_info=project_info,
                io_root=io_root,
                project_context_authority=project_context_authority,
            )
    except SoundBankContractError as exc:
        raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
    raise OperationContractError("INVALID_PREVIEW", f"Unsupported closed SoundBank operation {operation!r}.")


def _capture_soundbank_artifact_snapshots(
    plan: Mapping[str, Any],
    *,
    io_root: str,
) -> list[dict[str, Any]]:
    artifact_plan = plan.get("artifact_plan")
    if not isinstance(artifact_plan, Mapping):
        return []
    roots = artifact_plan.get("snapshot_roots")
    if not isinstance(roots, list):
        return []
    snapshots: list[dict[str, Any]] = []
    try:
        for root in roots:
            if not isinstance(root, str):
                raise SoundBankContractError("INVALID_EVIDENCE", "SoundBank snapshot root must be a string.")
            snapshots.append(capture_artifact_tree(root, io_root=io_root))
    except SoundBankContractError as exc:
        raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
    return snapshots


def _resolve_external_source_conversions(
    plan: Mapping[str, Any],
    *,
    roles: dict[str, ResolvedObject],
    read: ReadCall,
) -> None:
    oracle = plan.get("oracle")
    names = oracle.get("explicit_conversion_names_require_live_resolution") if isinstance(oracle, Mapping) else None
    if not isinstance(names, list):
        return
    for index, name in enumerate(names):
        if not isinstance(name, str):
            raise OperationContractError("INVALID_PREVIEW", "External Source conversion name must be a string.")
        query, rows = _read_named_type_rows("Conversion", name, read=read, take=2)
        if len(rows) != 1:
            raise OperationContractError(
                "AMBIGUOUS_IDENTITY",
                "Every explicit External Sources Conversion setting must resolve live to exactly one object.",
                details={"name": name, "rows": rows},
            )
        roles[f"conversion[{index}]"] = _resolved_waql_row(query, rows[0])


def _prepare_definition_oracle(
    plan: Mapping[str, Any],
    *,
    roles: dict[str, ResolvedObject],
    read: ReadCall,
) -> dict[str, Any]:
    raw_banks = plan.get("soundbanks")
    if not isinstance(raw_banks, list) or not all(isinstance(row, Mapping) for row in raw_banks):
        raise OperationContractError("INVALID_PREVIEW", "Definition plan lacks derived SoundBank rows.")
    target_names = {str(bank.get("name")).casefold() for bank in raw_banks}
    banks: list[dict[str, Any]] = []
    for bank_index, raw_bank in enumerate(raw_banks):
        name = _non_empty_string(raw_bank.get("name"), field=f"definition.soundbanks[{bank_index}].name")
        query, rows = _read_named_type_rows("SoundBank", name, read=read, take=2)
        if len(rows) > 1:
            raise OperationContractError(
                "AMBIGUOUS_IDENTITY",
                "A Definition target SoundBank name resolves to more than one object.",
                details={"name": name, "rows": rows},
            )
        preexisting_id: Any = None
        before_inclusions: list[dict[str, Any]] = []
        before_map: dict[str, dict[str, Any]] = {}
        if rows:
            resolved_bank = _resolved_waql_row(query, rows[0])
            preexisting_id = resolved_bank.object
            roles[f"definition.bank[{bank_index}]"] = resolved_bank
            before_result = read(SOUNDBANK_GET_INCLUSIONS_URI, {"soundbank": preexisting_id}, {})
            before_map = _inclusion_map(before_result)
            before_inclusions = _inclusion_rows(before_map)

        expected_map: dict[str, dict[str, Any]] = {}
        raw_inclusions = raw_bank.get("expected_inclusions")
        if not isinstance(raw_inclusions, list) or not raw_inclusions:
            raise OperationContractError("INVALID_PREVIEW", "A Definition target lacks expected inclusions.")
        for inclusion_index, raw_inclusion in enumerate(raw_inclusions):
            if not isinstance(raw_inclusion, Mapping):
                raise OperationContractError("INVALID_PREVIEW", "A Definition inclusion is malformed.")
            expected_type = _non_empty_string(
                raw_inclusion.get("object_type"),
                field=f"definition.soundbanks[{bank_index}].inclusions[{inclusion_index}].object_type",
            )
            identity = raw_inclusion.get("identity")
            resolved = _resolve_definition_identity(
                identity,
                expected_type=expected_type,
                role=f"definition.bank[{bank_index}].inclusion[{inclusion_index}]",
                read=read,
            )
            roles[f"definition.bank[{bank_index}].inclusion[{inclusion_index}]"] = resolved
            key = _identity_key(resolved.object)
            if key in expected_map:
                raise OperationContractError(
                    "DUPLICATE_DEFINITION_INCLUSION",
                    "Definition rows resolve to the same live object more than once.",
                    details={"soundbank": name, "object_id": resolved.object},
                )
            filters = raw_inclusion.get("filters")
            expected_map[key] = {
                "object": resolved.object,
                "filters": set(_closed_inclusion_filters(filters, field="definition.filters")),
            }
        definition_inclusions = _inclusion_rows(expected_map)
        expected_after = _inclusion_rows(
            _apply_inclusion_mode(before_map, expected_map, mode="add")
        )
        banks.append(
            {
                "name": name,
                "query": query,
                "pre_state_rows": rows,
                "preexisting_id": preexisting_id,
                "before_inclusions": before_inclusions,
                "definition_inclusions": definition_inclusions,
                "expected_inclusions": expected_after,
            }
        )

    all_query = "from type SoundBank take 257"
    all_result = read(OBJECT_GET_URI, {"waql": all_query}, {"return": list(IDENTITY_RETURN_FIELDS)})
    all_rows = _rows(all_result)
    if len(all_rows) >= 257:
        raise OperationContractError(
            "RESULT_LIMIT_EXCEEDED",
            "The closed Definition route cannot select a bounded unrelated control SoundBank.",
            details={"limit": 256, "returned": len(all_rows)},
        )
    controls = sorted(
        (row for row in all_rows if str(row.get("name", "")).casefold() not in target_names),
        key=lambda row: (str(row.get("path", "")), str(row.get("id", ""))),
    )
    control: dict[str, Any] | None = None
    if controls:
        row = controls[0]
        control_id = row.get("id")
        if not _valid_object_id(control_id):
            raise OperationContractError("INVALID_READBACK", "Control SoundBank lacks a canonical GUID.")
        roles["definition.control_bank"] = _resolved_waql_row(all_query, row)
        before_result = read(SOUNDBANK_GET_INCLUSIONS_URI, {"soundbank": control_id}, {})
        control = {
            "id": control_id,
            "name": row.get("name"),
            "row": row,
            "inclusions": _inclusion_rows(_inclusion_map(before_result)),
        }
    return {"banks": banks, "control": control, "all_soundbanks_query": all_query}


def _resolve_definition_identity(
    identity: Any,
    *,
    expected_type: str,
    role: str,
    read: ReadCall,
) -> ResolvedObject:
    if not isinstance(identity, Mapping):
        raise OperationContractError("INVALID_PREVIEW", f"{role} identity is malformed.")
    kind = identity.get("kind")
    if kind == "guid":
        resolved = _resolve_identity({"kind": "id", "value": identity.get("value")}, role=role, read=read)
    elif kind == "short_id":
        value = identity.get("value")
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
            raise OperationContractError(
                "INVALID_PREVIEW",
                f"{role} short ID is not a uint32.",
            )
        object_type_code = DEFINITION_SHORT_ID_OBJECT_TYPE_CODES.get(expected_type)
        if object_type_code is None:
            raise OperationContractError(
                "UNSUPPORTED_DEFINITION_SHORT_ID_TYPE",
                "This Definition object type has no official object.get Short ID selector code.",
                details={
                    "role": role,
                    "expected_type": expected_type,
                    "supported_types": sorted(DEFINITION_SHORT_ID_OBJECT_TYPE_CODES),
                },
            )
        # ``Global:<shortId>`` is a string-identity spelling accepted by
        # selected mutation arguments, not an ``object.get`` qualified name.
        # Real 2022.1 Authoring requires the reflected ``{shortId, type}``
        # selector object and rejects a bare uint32 in ``from.id``.
        options = {"return": [*IDENTITY_RETURN_FIELDS, "shortId"]}
        result = read(
            OBJECT_GET_URI,
            {"from": {"id": [{"shortId": value, "type": object_type_code}]}},
            options,
        )
        rows = _rows(result)
        if len(rows) != 1:
            raise OperationContractError(
                "AMBIGUOUS_IDENTITY",
                "Every Definition Short ID must resolve live to exactly one object before dispatch.",
                details={
                    "role": role,
                    "expected_type": expected_type,
                    "short_id": value,
                    "rows": rows,
                },
            )
        row = rows[0]
        live_short_id = row.get("shortId")
        if isinstance(live_short_id, str) and live_short_id.isdecimal():
            live_short_id = int(live_short_id, 10)
        object_id = row.get("id")
        if live_short_id != value or not _valid_object_id(object_id):
            raise OperationContractError(
                "IDENTITY_MISMATCH",
                "A Definition Short ID readback did not preserve the requested numeric identity.",
                details={"short_id": value, "row": row},
            )
        resolved = ResolvedObject(
            identity=ObjectIdentity(id=object_id),
            object=object_id,
            resolution="live-short-id",
            row=dict(row),
        )
    elif kind == "name":
        name = _non_empty_string(identity.get("value"), field=f"{role}.name")
        query, rows = _read_named_type_rows(expected_type, name, read=read, take=2)
        if len(rows) != 1:
            raise OperationContractError(
                "AMBIGUOUS_IDENTITY",
                "Every Definition name must resolve live to exactly one typed object before dispatch.",
                details={"role": role, "expected_type": expected_type, "name": name, "rows": rows},
            )
        resolved = _resolved_waql_row(query, rows[0])
    else:
        raise OperationContractError("INVALID_PREVIEW", f"{role} uses an unsupported derived identity kind.")
    allowed_types = {
        "Event": {"Event"},
        "DialogueEvent": {"DialogueEvent"},
        "AuxBus": {"AuxBus"},
        "Effect": {"Effect", "EffectShareSet"},
    }.get(expected_type, {expected_type})
    if resolved.row.get("type") not in allowed_types:
        raise OperationContractError(
            "INVALID_TARGET_TYPE",
            f"{role} does not match the Definition directive object type.",
            details={"expected": sorted(allowed_types), "actual": resolved.row.get("type"), "row": dict(resolved.row)},
        )
    return resolved


def _read_named_type_rows(
    object_type: str,
    name: str,
    *,
    read: ReadCall,
    take: int,
) -> tuple[str, list[dict[str, Any]]]:
    allowed_types = {"Project", "SoundBank", "Conversion", "Event", "DialogueEvent", "AuxBus", "Effect"}
    if object_type not in allowed_types or not isinstance(take, int) or take < 1 or take > 257:
        raise OperationContractError("INVALID_PREVIEW", "Closed typed-name query parameters are invalid.")
    encoded_name = json.dumps(name, ensure_ascii=False)
    query = f"from type {object_type} where name = {encoded_name} take {take}"
    result = read(OBJECT_GET_URI, {"waql": query}, {"return": list(IDENTITY_RETURN_FIELDS)})
    return query, _rows(result)


def _resolved_waql_row(query: str, row: Mapping[str, Any]) -> ResolvedObject:
    object_id = row.get("id")
    if not _valid_object_id(object_id):
        raise OperationContractError("INVALID_READBACK", "A typed-name readback row lacks a canonical GUID.")
    return ResolvedObject(
        identity=ObjectIdentity(waql=query),
        object=object_id,
        resolution="live-waql",
        row=dict(row),
    )


def _prepare_soundbank_inclusions(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    roles: dict[str, ResolvedObject] = {}
    soundbank = _resolve_identity(arguments.get("soundbank"), role="soundbank", read=read)
    if soundbank.row.get("type") != "SoundBank":
        raise OperationContractError(
            "INVALID_TARGET_TYPE",
            "soundbank.setInclusions requires a live SoundBank object.",
            details={"actual_type": soundbank.row.get("type"), "soundbank": soundbank.as_dict()},
        )
    roles["soundbank"] = soundbank
    mode = _non_empty_string(arguments.get("mode"), field="mode")
    if mode not in {"add", "remove", "replace"}:
        raise OperationContractError(
            "INVALID_ARGUMENT",
            "soundbank.setInclusions mode must be add, remove, or replace.",
            details={"mode": mode},
        )
    requested_rows = _mapping_sequence(arguments.get("inclusions"), field="inclusions")
    if not requested_rows and mode != "replace":
        raise OperationContractError(
            "INVALID_ARGUMENT",
            "Empty soundbank.setInclusions rows are allowed only with replace, where they clear the captured inclusion state.",
        )
    requested: dict[str, dict[str, Any]] = {}
    builder_rows: list[dict[str, Any]] = []
    for index, row in enumerate(requested_rows):
        _require_exact_keys(row, required=("object", "filters"), context=f"inclusions[{index}]")
        resolved = _resolve_identity(row.get("object"), role=f"inclusions[{index}].object", read=read)
        roles[f"inclusions[{index}].object"] = resolved
        key = _identity_key(resolved.object)
        if key in requested:
            raise OperationContractError(
                "INVALID_ARGUMENT",
                "soundbank.setInclusions inclusion objects must be unique.",
                details={"duplicate_object": resolved.object},
            )
        filters = _closed_inclusion_filters(row.get("filters"), field=f"inclusions[{index}].filters")
        requested[key] = {"object": resolved.object, "filters": set(filters)}
        builder_rows.append({"object": resolved.object, "filter": filters})
    before_result = read(SOUNDBANK_GET_INCLUSIONS_URI, {"soundbank": soundbank.object}, {})
    before = _inclusion_map(before_result)
    if mode == "remove":
        missing = sorted(key for key in requested if key not in before)
        mismatched = [
            {
                "object": key,
                "expected_live_filters": sorted(str(item) for item in before[key].get("filters", ())),
                "requested_filters": sorted(str(item) for item in requested[key].get("filters", ())),
            }
            for key in requested
            if key in before and set(before[key].get("filters", ())) != set(requested[key].get("filters", ()))
        ]
        if missing or mismatched:
            raise OperationContractError(
                "REMOVE_PRECONDITION_MISMATCH",
                "soundbank.setInclusions remove requires each requested object and its complete filter row to match live state exactly.",
                details={"missing_objects": missing, "filter_mismatches": mismatched},
            )
    expected = _apply_inclusion_mode(before, requested, mode=mode)
    before_rows = _inclusion_rows(before)
    expected_rows = _inclusion_rows(expected)
    if before_rows == expected_rows:
        raise OperationContractError(
            "NO_OP",
            "soundbank.setInclusions would not change the normalized live inclusion state.",
            details={"mode": mode, "pre_state": before_rows, "requested": _inclusion_rows(requested)},
        )
    preview = SoundBankBuilder(version=request.version).set_inclusions(
        soundbank=soundbank.object,
        operation=mode,
        inclusions=builder_rows,
    )
    verification = {
        "kind": "soundbank-inclusions-exact",
        "soundbank_id": soundbank.object,
        "mode": mode,
        "expected": expected_rows,
    }
    cleanup = {
        "kind": "restore-soundbank-inclusions-from-prestate",
        "description": "Manual cleanup may replace inclusions with the captured normalized pre-state after a new preview; no automatic rollback is attempted.",
        "automatic": False,
        "automatic_retry": False,
        "pre_state": before_rows,
    }
    state = {
        "soundbank_inclusions": {
            "soundbank_id": soundbank.object,
            "mode": mode,
            "before": before_rows,
            "requested": _inclusion_rows(requested),
            "expected": expected_rows,
        }
    }
    return preview, roles, state, verification, cleanup


def _prepare_switch_assignment(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    roles = {
        "switch_container": _resolve_identity(arguments.get("switch_container"), role="switch_container", read=read),
        "child": _resolve_identity(arguments.get("child"), role="child", read=read),
        "state_or_switch": _resolve_identity(arguments.get("state_or_switch"), role="state_or_switch", read=read),
    }
    container = roles["switch_container"]
    child = roles["child"]
    state = roles["state_or_switch"]
    if container.row.get("type") != "SwitchContainer":
        raise OperationContractError(
            "INVALID_TARGET_TYPE",
            "switch_container must resolve to a SwitchContainer.",
            details={"actual_type": container.row.get("type")},
        )
    if not _same_identity(_parent_value(child.row.get("parent")), container.object):
        raise OperationContractError(
            "INVALID_RELATIONSHIP",
            "child must be a direct child of switch_container.",
            details={"child_parent": _parent_value(child.row.get("parent")), "container_id": container.object},
        )
    if state.row.get("type") not in {"Switch", "State"}:
        raise OperationContractError(
            "INVALID_TARGET_TYPE",
            "state_or_switch must resolve to a Switch or State.",
            details={"actual_type": state.row.get("type")},
        )
    reference_result = read(
        OBJECT_GET_URI,
        {"from": {"id": [container.object]}},
        {"return": ["id", "path", SWITCH_GROUP_REFERENCE]},
    )
    reference_rows = _rows(reference_result)
    reference_id = _reference_identity(_field_value(reference_rows[0], SWITCH_GROUP_REFERENCE)) if len(reference_rows) == 1 else None
    if reference_id is None:
        raise OperationContractError(
            "INVALID_RELATIONSHIP",
            "SwitchContainer must expose one canonical SwitchGroupOrStateGroup reference before assignment mutation.",
            details={"rows": reference_rows},
        )
    group_identity_kind = "path" if isinstance(reference_id, str) and reference_id.startswith("\\") else "id"
    group = _resolve_identity(
        {"kind": group_identity_kind, "value": reference_id},
        role="switch_group_or_state_group",
        read=read,
    )
    if group.row.get("type") not in {"SwitchGroup", "StateGroup"}:
        raise OperationContractError(
            "INVALID_TARGET_TYPE",
            "SwitchGroupOrStateGroup must resolve to a SwitchGroup or StateGroup.",
            details={"actual_type": group.row.get("type")},
        )
    roles["switch_group_or_state_group"] = group
    if not _same_identity(_parent_value(state.row.get("parent")), group.object):
        raise OperationContractError(
            "INVALID_RELATIONSHIP",
            "state_or_switch must be a direct child of the group referenced by the SwitchContainer.",
            details={"state_parent": _parent_value(state.row.get("parent")), "reference_id": group.object},
        )
    assignments_result = read(SWITCHCONTAINER_GET_ASSIGNMENTS_URI, {"id": container.object}, {})
    assignments = _assignment_pairs(assignments_result)
    child_key = _identity_key(child.object)
    state_key = _identity_key(state.object)
    exact = [row for row in assignments if row["child_key"] == child_key and row["state_key"] == state_key]
    same_child = [row for row in assignments if row["child_key"] == child_key]
    is_add = request.operation == "switchContainer.addAssignment"
    if is_add and exact:
        raise OperationContractError("NO_OP", "The exact Switch Container assignment already exists.", details={"assignment": exact})
    if is_add and same_child:
        raise OperationContractError(
            "RELATIONSHIP_CONFLICT",
            "The child already has an assignment to a different state or switch.",
            details={"existing": same_child},
        )
    if not is_add and not exact:
        raise OperationContractError(
            "NO_OP",
            "The exact Switch Container assignment does not exist and cannot be removed.",
            details={"assignments": _public_assignment_pairs(assignments)},
        )
    expected_assignments = [dict(row) for row in assignments]
    if is_add:
        expected_assignments.append(
            {
                "child": child.object,
                "stateOrSwitch": state.object,
                "child_key": child_key,
                "state_key": state_key,
            }
        )
    else:
        expected_assignments = [
            row
            for row in expected_assignments
            if not (row["child_key"] == child_key and row["state_key"] == state_key)
        ]
    builder = SwitchContainerAssignmentBuilder(version=request.version)
    build_kwargs = {
        "switch_container": container.object,
        "child": child.object,
        "state_or_switch": state.object,
        "existing_assignments": assignments_result,
    }
    preview = builder.add_assignment(**build_kwargs) if is_add else builder.remove_assignment(**build_kwargs)
    verification = {
        "kind": "switch-assignment-pair",
        "switch_container_id": container.object,
        "child_id": child.object,
        "state_or_switch_id": state.object,
        "should_exist": is_add,
        "reference_id": group.object,
        "group_type": group.row.get("type"),
        "state_or_switch_type": state.row.get("type"),
        "expected_assignments": _public_assignment_pairs(expected_assignments),
    }
    cleanup = {
        "kind": "remove-added-assignment" if is_add else "restore-removed-assignment",
        "description": (
            "Manual cleanup may remove the exact added pair after a fresh relationship preview."
            if is_add
            else "Manual cleanup may re-add the exact removed pair after a fresh relationship preview."
        ),
        "automatic": False,
        "automatic_retry": False,
        "pair": {"child": child.object, "stateOrSwitch": state.object},
    }
    state = {
        "switch_assignment": {
            "switch_container_id": container.object,
            "reference_id": group.object,
            "selectors": {
                role: _json_mapping(arguments[role])
                for role in ("switch_container", "child", "state_or_switch")
            },
            "assignments": _public_assignment_pairs(assignments),
            "target_pair": {"child": child.object, "stateOrSwitch": state.object},
        }
    }
    return preview, roles, state, verification, cleanup


def validate_prepared_roles(prepared: Mapping[str, Any], *, read_call: ReadCall) -> Mapping[str, Any]:
    """Re-read every canonical role and prove it still matches the preview snapshot."""

    if prepared.get("contract") != PREPARED_OPERATION_CONTRACT:
        raise OperationContractError("INVALID_PREVIEW", "Prepared operation contract is missing or unsupported.")
    operation = prepared.get("operation")
    roles = prepared.get("resolved_roles")
    if not isinstance(operation, str) or not isinstance(roles, Mapping):
        raise OperationContractError("INVALID_PREVIEW", "Prepared operation lacks operation or resolved_roles.")
    assertions: list[Mapping[str, Any]] = []
    readbacks: list[Mapping[str, Any]] = []
    if operation == "waapi.undoGroup":
        request_payload = prepared.get("request")
        dispatch_payload = prepared.get("dispatch")
        pre_state = prepared.get("pre_state")
        if (
            not isinstance(request_payload, Mapping)
            or not isinstance(dispatch_payload, Mapping)
            or not isinstance(pre_state, Mapping)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "waapi.undoGroup preview lacks request, dispatch, or execution plan data.",
            )
        version = request_payload.get("version")
        arguments = request_payload.get("arguments")
        if not isinstance(version, str) or not isinstance(arguments, Mapping):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "waapi.undoGroup preview lacks versioned arguments.",
            )
        actual_plan = pre_state.get("execution_plan")
        base_plan = build_undo_group_execution_plan(version, arguments)
        expected_dispatch = {
            key: base_plan["begin"][key] for key in ("uri", "args", "options")
        }
        passed = isinstance(actual_plan, Mapping)
        child_assertions: list[Mapping[str, Any]] = []
        child_readbacks: list[Mapping[str, Any]] = []
        if passed:
            actual_calls = actual_plan.get("calls")
            base_calls = base_plan.get("calls")
            passed = (
                isinstance(actual_calls, list)
                and isinstance(base_calls, list)
                and len(actual_calls) == len(base_calls)
                and actual_plan.get("begin") == base_plan.get("begin")
                and actual_plan.get("end") == base_plan.get("end")
                and actual_plan.get("cancel") == base_plan.get("cancel")
                and dict(dispatch_payload) == expected_dispatch
            )
            if passed:
                for index, (actual_child, base_child) in enumerate(
                    zip(actual_calls, base_calls, strict=True)
                ):
                    if not isinstance(actual_child, Mapping):
                        passed = False
                        break
                    binding_keys = (
                        "child_operation",
                        "child_request",
                        "child_schema_digest",
                        "api",
                        "timeout_seconds",
                        "result_limit_bytes",
                    )
                    binding_ok = all(
                        actual_child.get(key) == base_child.get(key)
                        for key in binding_keys
                    )
                    prepared_child = actual_child.get("prepared_operation")
                    if isinstance(prepared_child, Mapping):
                        child_validation = validate_prepared_roles(
                            prepared_child, read_call=read_call
                        )
                        binding_ok = binding_ok and child_validation.get("ok") is True
                        child_assertions.extend(
                            {
                                **dict(item),
                                "name": f"child[{index}] {item.get('name', 'role validation')}",
                            }
                            for item in child_validation.get("assertions", [])
                            if isinstance(item, Mapping)
                        )
                        child_readbacks.extend(
                            item
                            for item in child_validation.get("readbacks", [])
                            if isinstance(item, Mapping)
                        )
                    else:
                        binding_ok = binding_ok and all(
                            actual_child.get(key) == base_child.get(key)
                            for key in ("args", "options", "request_validation")
                        )
                    passed = passed and binding_ok
        assertions.append(
            {
                "name": "waapi.undoGroup execution plan still matches the immutable reviewed composite",
                "passed": passed,
                "evidence": {
                    "expected_plan": base_plan,
                    "actual_plan": actual_plan,
                    "expected_dispatch": expected_dispatch,
                    "actual_dispatch": dict(dispatch_payload),
                },
            }
        )
        return {
            "contract": ROLE_VALIDATION_CONTRACT,
            "operation": operation,
            "ok": passed,
            "status": "valid" if passed else "repreview_required",
            "assertions": [
                _json_mapping(item) for item in (*assertions, *child_assertions)
            ],
            "readbacks": [_json_mapping(item) for item in child_readbacks],
        }
    if operation == "waapi.call":
        request_payload = prepared.get("request")
        dispatch_payload = prepared.get("dispatch")
        if not isinstance(request_payload, Mapping) or not isinstance(dispatch_payload, Mapping):
            raise OperationContractError("INVALID_PREVIEW", "waapi.call preview lacks request or dispatch data.")
        version = request_payload.get("version")
        arguments = request_payload.get("arguments")
        if not isinstance(version, str) or not isinstance(arguments, Mapping):
            raise OperationContractError("INVALID_PREVIEW", "waapi.call preview lacks versioned arguments.")
        api, call_args, call_options, execution_contract = _public_call_arguments(version, arguments)
        expected = {"uri": api, "args": dict(call_args), "options": dict(call_options)}
        actual = {
            "uri": dispatch_payload.get("uri"),
            "args": dispatch_payload.get("args"),
            "options": dispatch_payload.get("options"),
        }
        passed = actual == expected
        assertions.append(
            {
                "name": "waapi.call dispatch still matches the reviewed versioned contract",
                "passed": passed,
                "evidence": {
                    "expected": expected,
                    "actual": actual,
                    "route": execution_contract["route"],
                },
            }
        )
        return {
            "contract": ROLE_VALIDATION_CONTRACT,
            "operation": operation,
            "ok": passed,
            "status": "valid" if passed else "repreview_required",
            "assertions": [_json_mapping(item) for item in assertions],
            "readbacks": [],
        }
    if operation in UI_COMMAND_OPERATIONS:
        request_payload = prepared.get("request")
        dispatch_payload = prepared.get("dispatch")
        pre_state = prepared.get("pre_state")
        if (
            not isinstance(request_payload, Mapping)
            or not isinstance(dispatch_payload, Mapping)
            or not isinstance(pre_state, Mapping)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                f"{operation} preview lacks request, dispatch, or UI-command plan evidence.",
            )
        stored_plan = pre_state.get("ui_command_plan")
        if not isinstance(stored_plan, Mapping):
            raise OperationContractError(
                "INVALID_PREVIEW",
                f"{operation} preview lacks its sealed UI-command plan.",
            )
        replay_request = parse_operation_request(request_payload)
        host_platform: str | None = None
        if operation == "ui.commands.register" or (
            operation == "ui.commands.unregister"
            and "commands" in replay_request.arguments
        ):
            host_result = read_call(GET_INFO_URI, {}, {})
            if not isinstance(host_result, Mapping):
                raise OperationContractError(
                    "INVALID_READBACK",
                    "ui.commands.register getInfo execution guard must return an object.",
                )
            host_platform = _ui_command_host_platform(host_result)
            readbacks.append(
                {
                    "role": "authoring-host",
                    "uri": GET_INFO_URI,
                    "args": {},
                    "options": {},
                    "result": dict(host_result),
                }
            )
        replayed_plan = _build_ui_command_operation_plan(
            replay_request,
            arguments=replay_request.arguments,
            host_platform=host_platform,
        )
        stored_valid = validate_ui_command_plan(stored_plan)
        expected_dispatch = {
            "uri": replayed_plan["dispatch"]["uri"],
            "args": dict(replayed_plan["dispatch"]["arguments"]),
            "options": dict(replayed_plan["dispatch"]["options"]),
        }
        assertions.extend(
            [
                {
                    "name": f"{operation} plan still matches the immutable closed request",
                    "passed": replayed_plan == stored_valid,
                    "evidence": {
                        "expected_plan_sha256": replayed_plan["plan_sha256"],
                        "actual_plan_sha256": stored_valid["plan_sha256"],
                    },
                },
                {
                    "name": f"{operation} dispatch still matches its sealed UI-command plan",
                    "passed": dict(dispatch_payload) == expected_dispatch,
                    "evidence": {
                        "expected": expected_dispatch,
                        "actual": dict(dispatch_payload),
                    },
                },
            ]
        )
        inventory = read_call(UI_COMMAND_GET_COMMANDS_URI, {}, {})
        if not isinstance(inventory, Mapping):
            raise OperationContractError(
                "INVALID_READBACK",
                "ui.commands.getCommands execution guard must return an object.",
            )
        readbacks.append(
            {
                "role": "ui-command-inventory",
                "uri": UI_COMMAND_GET_COMMANDS_URI,
                "args": {},
                "options": {},
                "result": dict(inventory),
            }
        )
        try:
            runtime_evidence = validate_ui_command_runtime_preconditions(
                stored_valid,
                inventory,
            )
        except UiCommandContractError as exc:
            assertions.append(
                {
                    "name": f"{operation} live inventory and file proofs still satisfy the sealed preconditions",
                    "passed": False,
                    "evidence": exc.as_dict(),
                }
            )
        else:
            assertions.append(
                {
                    "name": f"{operation} live inventory and file proofs still satisfy the sealed preconditions",
                    "passed": True,
                    "evidence": runtime_evidence,
                }
            )
        ok = bool(assertions) and all(
            item.get("passed") is True for item in assertions
        )
        return {
            "contract": ROLE_VALIDATION_CONTRACT,
            "operation": operation,
            "ok": ok,
            "status": "valid" if ok else "repreview_required",
            "assertions": [_json_mapping(item) for item in assertions],
            "readbacks": [_json_mapping(item) for item in readbacks],
        }
    if operation in REPLAY_GUARD_OPERATIONS:
        request_payload = prepared.get("request")
        dispatch_payload = prepared.get("dispatch")
        pre_state = prepared.get("pre_state")
        if (
            not isinstance(request_payload, Mapping)
            or not isinstance(dispatch_payload, Mapping)
            or not isinstance(pre_state, Mapping)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                f"{operation} preview lacks request, dispatch, or pre-state evidence.",
            )
        replay_request = parse_operation_request(request_payload)

        def reject_read(
            uri: str,
            args: Mapping[str, Any],
            options: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            raise OperationContractError(
                "INVALID_PREVIEW",
                f"{operation} unexpectedly requested a live read during immutable replay.",
                details={"uri": uri, "args": dict(args), "options": dict(options)},
            )

        replayed = prepare_operation(replay_request, read_call=reject_read).as_dict()
        expected_dispatch = replayed.get("dispatch")
        expected_pre_state = replayed.get("pre_state")
        dispatch_matches = (
            isinstance(expected_dispatch, Mapping)
            and dict(dispatch_payload) == dict(expected_dispatch)
        )
        pre_state_matches = (
            isinstance(expected_pre_state, Mapping)
            and dict(pre_state) == dict(expected_pre_state)
        )
        assertions.extend(
            [
                {
                    "name": f"{operation} dispatch still matches the immutable closed request",
                    "passed": dispatch_matches,
                    "evidence": {
                        "expected_uri": (
                            expected_dispatch.get("uri")
                            if isinstance(expected_dispatch, Mapping)
                            else None
                        ),
                        "actual_uri": dispatch_payload.get("uri"),
                        "expected_sha256": (
                            hashlib.sha256(canonical_json_bytes(expected_dispatch)).hexdigest()
                            if isinstance(expected_dispatch, Mapping)
                            else None
                        ),
                        "actual_sha256": hashlib.sha256(
                            canonical_json_bytes(dispatch_payload)
                        ).hexdigest(),
                    },
                },
                {
                    "name": f"{operation} sealed source/mode/host-control evidence is unchanged",
                    "passed": pre_state_matches,
                    "evidence": {
                        "expected_sha256": (
                            hashlib.sha256(canonical_json_bytes(expected_pre_state)).hexdigest()
                            if isinstance(expected_pre_state, Mapping)
                            else None
                        ),
                        "actual_sha256": hashlib.sha256(
                            canonical_json_bytes(pre_state)
                        ).hexdigest(),
                    },
                },
            ]
        )
    role_snapshots: list[tuple[str, Any, Mapping[str, Any]]] = []
    for role, snapshot_value in roles.items():
        if not isinstance(snapshot_value, Mapping):
            raise OperationContractError("INVALID_PREVIEW", f"Resolved role {role!r} is malformed.")
        object_id = snapshot_value.get("object")
        expected_row = snapshot_value.get("row")
        if object_id is None or not isinstance(expected_row, Mapping):
            raise OperationContractError("INVALID_PREVIEW", f"Resolved role {role!r} lacks object/row evidence.")
        _identity_key(object_id)
        role_snapshots.append((str(role), object_id, expected_row))

    role_batch: dict[str, Any] | None = None
    if role_snapshots:
        role_batch = _bounded_multi_identity_read(
            [object_id for _, object_id, _ in role_snapshots],
            fields=IDENTITY_RETURN_FIELDS,
            read=read_call,
            context="Prepared role validation",
        )
        readbacks.append(
            {
                "role": "resolved-roles",
                "roles": [role for role, _, _ in role_snapshots],
                "uri": OBJECT_GET_URI,
                "args": role_batch["args"],
                "options": role_batch["options"],
                "result": role_batch["result"],
            }
        )
        assertions.append(
            {
                "name": "resolved role GUID batch is exact",
                "passed": role_batch["exact"],
                "evidence": {
                    "requested_unique_ids": role_batch["args"]["from"]["id"],
                    "missing_ids": role_batch["missing_ids"],
                    "duplicate_ids": role_batch["duplicate_ids"],
                    "extra_rows": role_batch["extra_rows"],
                    "malformed_rows": role_batch["malformed_rows"],
                },
            }
        )

    for role, object_id, expected_row in role_snapshots:
        assert role_batch is not None  # role_snapshots is non-empty in this loop.
        rows = role_batch["rows_by_key"].get(_identity_key(object_id), [])
        assertions.append(
            {
                "name": f"{role} resolves exactly once",
                "passed": len(rows) == 1,
                "evidence": rows,
            }
        )
        if len(rows) != 1:
            continue
        actual = rows[0]
        for field_name in ("id", "name", "type", "path", "parent", "notes"):
            if field_name not in expected_row:
                continue
            expected = _parent_value(expected_row.get(field_name)) if field_name == "parent" else expected_row.get(field_name)
            observed = _parent_value(actual.get(field_name)) if field_name == "parent" else actual.get(field_name)
            assertions.append(
                {
                    "name": f"{role}.{field_name} unchanged",
                    "passed": _same_identity(observed, expected) if field_name in {"id", "parent"} else observed == expected,
                    "evidence": {"expected": expected, "actual": observed},
                }
            )

    pre_state = prepared.get("pre_state")
    field_before = pre_state.get("field_before") if isinstance(pre_state, Mapping) else None
    source = roles.get("object") if isinstance(roles, Mapping) else None
    if isinstance(field_before, Mapping) and isinstance(source, Mapping):
        field_name = field_before.get("field")
        object_id = source.get("object")
        if isinstance(field_name, str) and object_id is not None:
            args = {"from": {"id": [object_id]}}
            options = {"return": ["id", "path", field_name]}
            platform = field_before.get("platform")
            if platform is not None:
                if not isinstance(platform, str) or not platform:
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "Field precondition platform is malformed.",
                    )
                options["platform"] = platform
            result = read_call(OBJECT_GET_URI, args, options)
            if not isinstance(result, Mapping):
                raise OperationContractError("INVALID_READBACK", "Field precondition readback must be an object.")
            rows = _rows(result)
            readbacks.append({"role": "object-field", "uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)})
            actual = _field_value(rows[0], field_name) if len(rows) == 1 else None
            assertions.append(
                {
                    "name": f"object.{field_name} pre-state unchanged",
                    "passed": len(rows) == 1 and actual == field_before.get("value"),
                    "evidence": {"expected": field_before.get("value"), "actual": actual, "rows": rows},
                }
            )

    copy_move_collision_guard = (
        pre_state.get("copy_move_collision_guard")
        if isinstance(pre_state, Mapping)
        else None
    )
    if isinstance(copy_move_collision_guard, Mapping):
        path = copy_move_collision_guard.get("path")
        expected_rows = copy_move_collision_guard.get("rows")
        if not isinstance(path, str) or not isinstance(expected_rows, list):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "copy/move collision guard is malformed.",
            )
        result = read_call(
            OBJECT_GET_URI,
            {"from": {"path": [path]}},
            {"return": list(IDENTITY_RETURN_FIELDS)},
        )
        if not isinstance(result, Mapping):
            raise OperationContractError(
                "INVALID_READBACK",
                "copy/move collision guard readback must be an object.",
            )
        actual_rows = _rows(result)
        readbacks.append(
            {
                "role": "copy-move-collision",
                "uri": OBJECT_GET_URI,
                "args": {"from": {"path": [path]}},
                "options": {"return": list(IDENTITY_RETURN_FIELDS)},
                "result": dict(result),
            }
        )
        assertions.append(
            {
                "name": "copy/move destination collision state is unchanged",
                "passed": actual_rows == expected_rows,
                "evidence": {"path": path, "expected": expected_rows, "actual": actual_rows},
            }
        )

    linked_before = pre_state.get("linked_before") if isinstance(pre_state, Mapping) else None
    if isinstance(linked_before, Mapping):
        object_id = linked_before.get("object_id")
        field_name = linked_before.get("property")
        platform = linked_before.get("platform")
        expected_linked = linked_before.get("linked")
        if (
            not _valid_object_id(object_id)
            or not isinstance(field_name, str)
            or not field_name
            or not isinstance(platform, str)
            or not platform
            or not isinstance(expected_linked, bool)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Platform-link precondition snapshot is malformed.",
            )
        args = {"object": object_id, "property": field_name, "platform": platform}
        result = read_call(OBJECT_IS_LINKED_URI, args, {})
        if not isinstance(result, Mapping):
            raise OperationContractError(
                "INVALID_READBACK",
                "object.isLinked precondition readback must be an object.",
            )
        actual_linked = result.get("linked")
        readbacks.append(
            {
                "role": "object-linked-state",
                "uri": OBJECT_IS_LINKED_URI,
                "args": args,
                "options": {},
                "result": dict(result),
            }
        )
        assertions.append(
            {
                "name": "object platform link pre-state unchanged",
                "passed": actual_linked is expected_linked,
                "evidence": {"expected": expected_linked, "actual": actual_linked},
            }
        )

    rtpc_snapshot = pre_state.get("rtpc_snapshot") if isinstance(pre_state, Mapping) else None
    if isinstance(rtpc_snapshot, Mapping):
        request_payload = prepared.get("request")
        version = (
            request_payload.get("version")
            if isinstance(request_payload, Mapping)
            else None
        )
        object_id = rtpc_snapshot.get("object_id")
        fields = rtpc_snapshot.get("fields")
        expected = rtpc_snapshot.get("rows")
        if (
            not isinstance(version, str)
            or not _valid_object_id(object_id)
            or fields != list(RTPC_SNAPSHOT_FIELDS)
            or not isinstance(expected, list)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "RTPC precondition snapshot is malformed.",
            )
        actual, rtpc_readbacks = _read_rtpc_rows_with_evidence(
            object_id,
            version=version,
            read=read_call,
        )
        readbacks.extend(rtpc_readbacks)
        assertions.append(
            {
                "name": "complete RTPC list pre-state unchanged",
                "passed": actual == expected,
                "evidence": {"expected": expected, "actual": actual},
            }
        )

    plugin_guard = (
        pre_state.get("plugin_creation_guard")
        if isinstance(pre_state, Mapping)
        else None
    )
    if isinstance(plugin_guard, Mapping):
        request_payload = prepared.get("request")
        version = (
            request_payload.get("version")
            if isinstance(request_payload, Mapping)
            else None
        )
        target_id = plugin_guard.get("target_id")
        target_type = plugin_guard.get("target_type")
        raw_descriptor = plugin_guard.get("descriptor")
        expected_snapshot = plugin_guard.get("snapshot")
        expected_metadata = plugin_guard.get("property_metadata")
        expected_plan = plugin_guard.get("plan")
        if (
            operation != "object.createPlugin"
            or not isinstance(version, str)
            or not isinstance(target_id, str)
            or not _PLUGIN_GUID.fullmatch(target_id)
            or not isinstance(target_type, str)
            or not isinstance(raw_descriptor, Mapping)
            or not isinstance(expected_snapshot, Mapping)
            or not isinstance(expected_metadata, list)
            or not isinstance(expected_plan, Mapping)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "object.createPlugin execution guard is malformed.",
            )
        try:
            descriptor = normalize_plugin_creation(raw_descriptor)
        except PluginOperationContractError as exc:
            raise OperationContractError(
                "INVALID_PREVIEW",
                "object.createPlugin descriptor in the immutable preview is malformed.",
                details=exc.as_dict(),
            ) from exc

        def plugin_guard_read(
            uri: str,
            args: Mapping[str, Any],
            options: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            result = read_call(uri, args, options)
            if not isinstance(result, Mapping):
                raise OperationContractError(
                    "INVALID_READBACK",
                    f"{uri} plug-in execution guard readback must be an object.",
                )
            normalized = dict(result)
            readbacks.append(
                {
                    "role": "plugin-creation-guard",
                    "uri": uri,
                    "args": dict(args),
                    "options": dict(options),
                    "result": normalized,
                }
            )
            return normalized

        actual_metadata: list[dict[str, Any]] = []
        for metadata_request in plugin_property_metadata_requests(descriptor):
            info = _read_property_info(
                plugin_guard_read,
                class_id=descriptor.class_id,
                name=str(metadata_request["args"]["property"]),
            )
            actual_metadata.append(info.as_dict())
        actual_snapshot = _read_plugin_prestate(
            version=version,
            target_id=target_id,
            descriptor=descriptor,
            read=plugin_guard_read,
        )
        assertions.extend(
            [
                {
                    "name": "plug-in classId-scoped property metadata is unchanged",
                    "passed": actual_metadata == expected_metadata,
                    "evidence": {
                        "expected": expected_metadata,
                        "actual": actual_metadata,
                    },
                },
                {
                    "name": "complete plug-in placement pre-state is unchanged",
                    "passed": actual_snapshot == expected_snapshot,
                    "evidence": {
                        "expected": expected_snapshot,
                        "actual": actual_snapshot,
                    },
                },
            ]
        )
        fixed_effects = (
            actual_snapshot.get("fixed_effects")
            if actual_snapshot.get("kind") == "fixed_effect_references"
            else None
        )
        try:
            actual_plan = build_plugin_creation_plan(
                version=version,
                target_id=target_id,
                target_type=target_type,
                request=descriptor,
                property_metadata=actual_metadata or None,
                effect_slots_2022=(
                    fixed_effects
                    if isinstance(fixed_effects, Mapping)
                    else None
                ),
            ).as_dict()
        except PluginOperationContractError as exc:
            assertions.append(
                {
                    "name": "closed plug-in creation plan can be replayed",
                    "passed": False,
                    "evidence": exc.as_dict(),
                }
            )
        else:
            prepared_dispatch = prepared.get("dispatch")
            expected_dispatch = actual_plan.get("dispatch")
            assertions.extend(
                [
                    {
                        "name": "closed plug-in creation plan is unchanged",
                        "passed": actual_plan == expected_plan,
                        "evidence": {
                            "expected": expected_plan,
                            "actual": actual_plan,
                        },
                    },
                    {
                        "name": "closed plug-in dispatch still matches the replayed plan",
                        "passed": (
                            isinstance(prepared_dispatch, Mapping)
                            and isinstance(expected_dispatch, Mapping)
                            and dict(prepared_dispatch) == dict(expected_dispatch)
                        ),
                        "evidence": {
                            "expected": expected_dispatch,
                            "actual": prepared_dispatch,
                        },
                    },
                ]
            )

    graph_guard = pre_state.get("object_graph_guard") if isinstance(pre_state, Mapping) else None
    if isinstance(graph_guard, Mapping):
        for index, snapshot in enumerate(graph_guard.get("field_snapshots", [])):
            if not isinstance(snapshot, Mapping):
                raise OperationContractError("INVALID_PREVIEW", "Object graph field snapshot is malformed.")
            object_id = snapshot.get("object_id")
            fields = snapshot.get("fields")
            expected = snapshot.get("rows")
            if not isinstance(fields, list) or not isinstance(expected, list):
                raise OperationContractError("INVALID_PREVIEW", "Object graph field snapshot lacks fields/rows.")
            args = {"from": {"id": [object_id]}}
            options = {"return": fields}
            platform = snapshot.get("platform")
            if platform is not None:
                if not isinstance(platform, str) or not platform:
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "Object graph field snapshot platform is malformed.",
                    )
                options["platform"] = platform
            language = snapshot.get("language")
            if language is not None:
                if not isinstance(language, str) or not language:
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "Object graph field snapshot language is malformed.",
                    )
                options["language"] = language
            result = read_call(OBJECT_GET_URI, args, options)
            if not isinstance(result, Mapping):
                raise OperationContractError("INVALID_READBACK", "Object graph field guard must return an object.")
            actual = _rows(result)
            readbacks.append({"role": f"object-graph-field[{index}]", "uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)})
            assertions.append(
                {
                    "name": f"object graph field snapshot {index} unchanged",
                    "passed": actual == expected,
                    "evidence": {"expected": expected, "actual": actual},
                }
            )
        for index, snapshot in enumerate(graph_guard.get("children_snapshots", [])):
            if not isinstance(snapshot, Mapping):
                raise OperationContractError("INVALID_PREVIEW", "Object graph children snapshot is malformed.")
            object_id = snapshot.get("object_id")
            fields = snapshot.get("fields")
            expected = snapshot.get("rows")
            if not isinstance(fields, list) or not isinstance(expected, list):
                raise OperationContractError("INVALID_PREVIEW", "Object graph children snapshot lacks fields/rows.")
            args = {"from": {"id": [object_id]}, "transform": [{"select": ["children"]}]}
            options = {"return": fields}
            result = read_call(OBJECT_GET_URI, args, options)
            if not isinstance(result, Mapping):
                raise OperationContractError("INVALID_READBACK", "Object graph children guard must return an object.")
            actual = _rows(result)
            readbacks.append({"role": f"object-graph-children[{index}]", "uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)})
            assertions.append(
                {
                    "name": f"object graph child snapshot {index} unchanged",
                    "passed": actual == expected,
                    "evidence": {"expected": expected, "actual": actual},
                }
            )
        for index, snapshot in enumerate(graph_guard.get("list_snapshots", [])):
            if not isinstance(snapshot, Mapping):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Object graph list snapshot is malformed.",
                )
            object_id = snapshot.get("object_id")
            list_name = snapshot.get("list")
            fields = snapshot.get("fields")
            expected = snapshot.get("rows")
            if (
                not _valid_object_id(object_id)
                or not isinstance(list_name, str)
                or fields != list(OBJECT_LIST_SNAPSHOT_FIELDS)
                or not isinstance(expected, list)
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Object graph list snapshot lacks its owner, list, fields, or rows.",
                )
            platform = snapshot.get("platform")
            if platform is not None:
                if not isinstance(platform, str) or not platform:
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "Object graph list snapshot platform is malformed.",
                    )
            list_rows, list_readbacks = _read_object_list_rows_with_evidence(
                object_id,
                list_name,
                fields=OBJECT_LIST_SNAPSHOT_FIELDS,
                read=read_call,
                platform=platform,
                context=f"object-graph-list[{index}]",
            )
            actual = _normalize_object_list_snapshot(
                list_rows,
                owner_id=object_id,
                list_name=list_name,
            )
            readbacks.extend(list_readbacks)
            assertions.append(
                {
                    "name": f"object graph list snapshot {index} unchanged",
                    "passed": actual == expected,
                    "evidence": {"expected": expected, "actual": actual},
                }
            )
        for index, snapshot in enumerate(
            graph_guard.get("list_subtree_snapshots", [])
        ):
            if not isinstance(snapshot, Mapping):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Object graph list subtree snapshot is malformed.",
                )
            root_id = snapshot.get("root_id")
            fields = snapshot.get("fields")
            expected = snapshot.get("rows")
            if (
                not _valid_object_id(root_id)
                or fields != list(OBJECT_LIST_SNAPSHOT_FIELDS)
                or not isinstance(expected, list)
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Object graph list subtree snapshot lacks its root, fields, or rows.",
                )
            root_args = {"from": {"id": [root_id]}}
            descendants_args = {
                "from": {"id": [root_id]},
                "transform": [{"select": ["descendants"]}],
            }
            options = {"return": list(OBJECT_LIST_SNAPSHOT_FIELDS)}
            root_result = read_call(OBJECT_GET_URI, root_args, options)
            descendants_result = read_call(
                OBJECT_GET_URI,
                descendants_args,
                options,
            )
            if not isinstance(root_result, Mapping) or not isinstance(
                descendants_result,
                Mapping,
            ):
                raise OperationContractError(
                    "INVALID_READBACK",
                    "Object graph list subtree guard reads must return objects.",
                )
            actual = _normalize_object_identity_subtree(
                _rows(root_result),
                _rows(descendants_result),
                expected_root_id=root_id,
            )
            readbacks.extend(
                [
                    {
                        "role": f"object-graph-list-subtree-root[{index}]",
                        "uri": OBJECT_GET_URI,
                        "args": root_args,
                        "options": options,
                        "result": dict(root_result),
                    },
                    {
                        "role": f"object-graph-list-subtree-descendants[{index}]",
                        "uri": OBJECT_GET_URI,
                        "args": descendants_args,
                        "options": options,
                        "result": dict(descendants_result),
                    },
                ]
            )
            assertions.append(
                {
                    "name": f"object graph list subtree snapshot {index} unchanged",
                    "passed": actual == expected,
                    "evidence": {"expected": expected, "actual": actual},
                }
            )
        for index, snapshot in enumerate(graph_guard.get("path_snapshots", [])):
            if not isinstance(snapshot, Mapping):
                raise OperationContractError("INVALID_PREVIEW", "Object graph path snapshot is malformed.")
            path = snapshot.get("path")
            fields = snapshot.get("fields")
            expected = snapshot.get("rows")
            if not isinstance(path, str) or not isinstance(fields, list) or not isinstance(expected, list):
                raise OperationContractError("INVALID_PREVIEW", "Object graph path snapshot lacks path/fields/rows.")
            args = {"from": {"path": [path]}}
            options = {"return": fields}
            platform = snapshot.get("platform")
            if platform is not None:
                if not isinstance(platform, str) or not platform:
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "Object graph path snapshot platform is malformed.",
                    )
                options["platform"] = platform
            language = snapshot.get("language")
            if language is not None:
                if not isinstance(language, str) or not language:
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "Object graph path snapshot language is malformed.",
                    )
                options["language"] = language
            result = read_call(OBJECT_GET_URI, args, options)
            if not isinstance(result, Mapping):
                raise OperationContractError("INVALID_READBACK", "Object graph path guard must return an object.")
            actual = _rows(result)
            readbacks.append({"role": f"object-graph-path[{index}]", "uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)})
            assertions.append(
                {
                    "name": f"object graph path snapshot {index} unchanged",
                    "passed": actual == expected,
                    "evidence": {"path": path, "expected": expected, "actual": actual},
                }
            )
        for index, snapshot in enumerate(graph_guard.get("subtree_snapshots", [])):
            if not isinstance(snapshot, Mapping):
                raise OperationContractError("INVALID_PREVIEW", "Object graph subtree snapshot is malformed.")
            root_id = snapshot.get("root_id")
            root_path = snapshot.get("root_path")
            fields = snapshot.get("fields")
            expected = snapshot.get("rows")
            if (
                not _valid_object_id(root_id)
                or not isinstance(root_path, str)
                or fields != list(OBJECT_REPLACE_SNAPSHOT_FIELDS)
                or not isinstance(expected, list)
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Object graph subtree snapshot lacks its closed root, fields, or rows.",
                )
            root_args = {"from": {"id": [root_id]}}
            root_options = {"return": list(OBJECT_REPLACE_SNAPSHOT_FIELDS)}
            root_result = read_call(OBJECT_GET_URI, root_args, root_options)
            descendants_args = {
                "from": {"id": [root_id]},
                "transform": [{"select": ["descendants"]}],
            }
            descendants_options = {"return": list(OBJECT_REPLACE_SNAPSHOT_FIELDS)}
            descendants_result = read_call(OBJECT_GET_URI, descendants_args, descendants_options)
            if not isinstance(root_result, Mapping) or not isinstance(descendants_result, Mapping):
                raise OperationContractError(
                    "INVALID_READBACK",
                    "Object graph subtree guard reads must return objects.",
                )
            root_rows = _rows(root_result)
            descendant_rows = _rows(descendants_result)
            readbacks.extend(
                [
                    {
                        "role": f"object-graph-subtree-root[{index}]",
                        "uri": OBJECT_GET_URI,
                        "args": root_args,
                        "options": root_options,
                        "result": dict(root_result),
                    },
                    {
                        "role": f"object-graph-subtree-descendants[{index}]",
                        "uri": OBJECT_GET_URI,
                        "args": descendants_args,
                        "options": descendants_options,
                        "result": dict(descendants_result),
                    },
                ]
            )
            try:
                actual = _normalize_replace_subtree_snapshot(
                    root_rows,
                    descendant_rows,
                    expected_root_id=root_id,
                    expected_root_path=root_path,
                )
            except OperationContractError as exc:
                actual = []
                evidence: Any = {"expected": expected, "error": exc.as_dict()}
                passed = False
            else:
                evidence = {"expected": expected, "actual": actual}
                passed = actual == expected
            assertions.append(
                {
                    "name": f"object replace subtree GUID/path snapshot {index} unchanged",
                    "passed": passed,
                    "evidence": evidence,
                }
            )

    import_guard = pre_state.get("import_guard") if isinstance(pre_state, Mapping) else None
    if isinstance(import_guard, Mapping):
        for index, item in enumerate(import_guard.get("file_proofs", [])):
            if not isinstance(item, Mapping) or not isinstance(item.get("proof"), Mapping):
                raise OperationContractError("INVALID_PREVIEW", "Import file proof guard is malformed.")
            field = str(item.get("field", f"file[{index}]"))
            try:
                actual = verify_import_file_proof(item["proof"], field=field)
            except ImportContractError as exc:
                passed = False
                evidence: Any = {"expected": dict(item["proof"]), "error": exc.as_dict()}
            else:
                passed = True
                evidence = {"expected": dict(item["proof"]), "actual": actual}
            assertions.append({"name": f"{field} unchanged since preview", "passed": passed, "evidence": evidence})
        expected_originals_context = import_guard.get("originals_context")
        if expected_originals_context is not None:
            if not isinstance(expected_originals_context, Mapping):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Import Originals-root execution guard is malformed.",
                )
            prepared_request = prepared.get("request")
            prepared_version = (
                prepared_request.get("version")
                if isinstance(prepared_request, Mapping)
                else None
            )
            if not isinstance(prepared_version, str):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Import Originals-root execution guard lacks the prepared Wwise version.",
                )
            _import_originals_root_from_context(
                expected_originals_context,
                version=prepared_version,
            )

            def import_originals_context_read(
                uri: str,
                args: Mapping[str, Any],
                options: Mapping[str, Any],
            ) -> Mapping[str, Any]:
                result = read_call(uri, args, options)
                if not isinstance(result, Mapping):
                    raise OperationContractError(
                        "INVALID_READBACK",
                        f"{uri} import Originals-root guard readback must be an object.",
                    )
                normalized = dict(result)
                readbacks.append(
                    {
                        "role": "import-originals-context",
                        "uri": uri,
                        "args": dict(args),
                        "options": dict(options),
                        "result": normalized,
                    }
                )
                return normalized

            try:
                actual_originals_context = _read_import_originals_context(
                    prepared_version,
                    read=import_originals_context_read,
                )
            except OperationContractError as exc:
                passed = False
                evidence = {
                    "expected": dict(expected_originals_context),
                    "error": exc.as_dict(),
                }
            else:
                passed = actual_originals_context == dict(expected_originals_context)
                evidence = {
                    "expected": dict(expected_originals_context),
                    "actual": actual_originals_context,
                }
            assertions.append(
                {
                    "name": "live Project Originals root is unchanged since preview",
                    "passed": passed,
                    "evidence": evidence,
                }
            )
        expected_language_inventory = import_guard.get("language_inventory")
        if expected_language_inventory is not None:
            if not isinstance(expected_language_inventory, Mapping):
                raise OperationContractError("INVALID_PREVIEW", "Import language inventory guard is malformed.")

            def import_language_read(
                uri: str,
                args: Mapping[str, Any],
                options: Mapping[str, Any],
            ) -> Mapping[str, Any]:
                result = read_call(uri, args, options)
                if not isinstance(result, Mapping):
                    raise OperationContractError(
                        "INVALID_READBACK",
                        f"{uri} import language guard readback must be an object.",
                    )
                normalized = dict(result)
                readbacks.append(
                    {
                        "role": "import-language-inventory",
                        "uri": uri,
                        "args": dict(args),
                        "options": dict(options),
                        "result": normalized,
                    }
                )
                return normalized

            try:
                prepared_request = prepared.get("request")
                prepared_version = (
                    prepared_request.get("version")
                    if isinstance(prepared_request, Mapping)
                    else None
                )
                if not isinstance(prepared_version, str):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "Import language inventory guard lacks the prepared Wwise version.",
                    )
                actual_language_inventory = _read_import_language_inventory(
                    prepared_version,
                    read=import_language_read,
                )
            except OperationContractError as exc:
                passed = False
                evidence = {"expected": dict(expected_language_inventory), "error": exc.as_dict()}
            else:
                passed = actual_language_inventory == dict(expected_language_inventory)
                evidence = {
                    "expected": dict(expected_language_inventory),
                    "actual": actual_language_inventory,
                }
            assertions.append(
                {
                    "name": "live Project language inventory is unchanged since preview",
                    "passed": passed,
                    "evidence": evidence,
                }
            )
        for index, snapshot in enumerate(import_guard.get("path_snapshots", [])):
            if not isinstance(snapshot, Mapping):
                raise OperationContractError("INVALID_PREVIEW", "Import path snapshot is malformed.")
            path = snapshot.get("path")
            fields = snapshot.get("fields")
            expected = snapshot.get("rows")
            if not isinstance(path, str) or not isinstance(fields, list) or not isinstance(expected, list):
                raise OperationContractError("INVALID_PREVIEW", "Import path snapshot lacks path/fields/rows.")
            args = {"from": {"path": [path]}}
            stored_options = snapshot.get("options")
            if stored_options is None:
                options = _import_object_get_options(fields)
            else:
                if (
                    not isinstance(stored_options, Mapping)
                    or set(stored_options) != {"return", "language"}
                    or stored_options.get("return") != fields
                    or _localized_import_read_language(
                        stored_options.get("language")
                    )
                    != stored_options.get("language")
                ):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "Localized import path snapshot options are malformed.",
                    )
                # Replay the immutable preview options exactly; do not rebuild
                # the language from ambient Authoring state at confirmation.
                options = dict(stored_options)
            result = read_call(OBJECT_GET_URI, args, options)
            if not isinstance(result, Mapping):
                raise OperationContractError("INVALID_READBACK", "Import path guard must return an object.")
            actual = _rows(result)
            readbacks.append({"role": f"import-path[{index}]", "uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)})
            assertions.append(
                {
                    "name": f"import path snapshot {index} unchanged",
                    "passed": actual == expected,
                    "evidence": {
                        "path": path,
                        "options": options,
                        "expected": expected,
                        "actual": actual,
                    },
                }
            )

    soundbank_guard = pre_state.get("soundbank_guard") if isinstance(pre_state, Mapping) else None
    if isinstance(soundbank_guard, Mapping):
        guard_operation = soundbank_guard.get("kind")
        version = soundbank_guard.get("version")
        plan_arguments = soundbank_guard.get("plan_arguments")
        io_root = soundbank_guard.get("io_root")
        authority = soundbank_guard.get("project_context_authority")
        if (
            guard_operation not in {
                "soundbank.generate",
                "soundbank.convertExternalSources",
                "soundbank.processDefinitionFiles",
            }
            or guard_operation != operation
            or not isinstance(version, str)
            or not isinstance(plan_arguments, Mapping)
            or not isinstance(io_root, str)
            or not isinstance(authority, str)
        ):
            raise OperationContractError("INVALID_PREVIEW", "Closed SoundBank execution guard is malformed.")

        def soundbank_read(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
            result = read_call(uri, args, options)
            if not isinstance(result, Mapping):
                raise OperationContractError("INVALID_READBACK", f"{uri} SoundBank guard readback must be an object.")
            normalized = dict(result)
            readbacks.append({"role": "soundbank-guard", "uri": uri, "args": dict(args), "options": dict(options), "result": normalized})
            return normalized

        try:
            project_info, fresh_authority, project_validation = _soundbank_project_info(
                version,
                io_root=io_root,
                roles={},
                read=soundbank_read,
            )
            if fresh_authority != authority:
                raise OperationContractError(
                    "PROJECT_CONTEXT_AUTHORITY_CHANGED",
                    "The live SoundBank project-context authority changed after preview.",
                    details={"expected": authority, "actual": fresh_authority},
                )
            fresh_plan = _build_soundbank_plan(
                str(guard_operation),
                plan_arguments,
                version=version,
                project_info=project_info,
                io_root=io_root,
                project_context_authority=fresh_authority,
            )
        except OperationContractError as exc:
            assertions.append(
                {
                    "name": "closed SoundBank inputs and project context can be replayed unchanged",
                    "passed": False,
                    "evidence": exc.as_dict(),
                }
            )
            fresh_plan = None
        else:
            assertions.append(
                {
                    "name": "live SoundBank project evidence still matches its closed versioned authority",
                    "passed": True,
                    "evidence": dict(project_validation),
                }
            )
        if isinstance(fresh_plan, Mapping):
            expected_sha = soundbank_guard.get("plan_sha256")
            actual_sha = fresh_plan.get("plan_sha256")
            assertions.append(
                {
                    "name": "closed SoundBank plan hash is unchanged since preview",
                    "passed": isinstance(expected_sha, str) and actual_sha == expected_sha,
                    "evidence": {"expected": expected_sha, "actual": actual_sha},
                }
            )
            prepared_dispatch = prepared.get("dispatch")
            expected_dispatch = {
                "uri": describe_operation(str(guard_operation)).uri,
                "args": fresh_plan.get("dispatch_args"),
                "options": {},
            }
            assertions.append(
                {
                    "name": "closed SoundBank dispatch still matches the replayed plan",
                    "passed": isinstance(prepared_dispatch, Mapping) and dict(prepared_dispatch) == expected_dispatch,
                    "evidence": {"expected": expected_dispatch, "actual": prepared_dispatch},
                }
            )

        expected_snapshots = soundbank_guard.get("artifact_snapshots")
        if not isinstance(expected_snapshots, list):
            raise OperationContractError("INVALID_PREVIEW", "SoundBank artifact snapshot guard is malformed.")
        for index, expected in enumerate(expected_snapshots):
            if not isinstance(expected, Mapping) or not isinstance(expected.get("root"), str):
                raise OperationContractError("INVALID_PREVIEW", "A SoundBank artifact snapshot is malformed.")
            try:
                actual = capture_artifact_tree(expected["root"], io_root=io_root)
            except SoundBankContractError as exc:
                passed = False
                evidence: Any = {"expected": dict(expected), "error": exc.as_dict()}
            else:
                passed = actual.get("snapshot_sha256") == expected.get("snapshot_sha256")
                evidence = {
                    "root": expected.get("root"),
                    "expected_snapshot_sha256": expected.get("snapshot_sha256"),
                    "actual_snapshot_sha256": actual.get("snapshot_sha256"),
                }
            assertions.append(
                {
                    "name": f"SoundBank artifact tree {index} is unchanged since preview",
                    "passed": passed,
                    "evidence": evidence,
                }
            )

        definition_oracle = soundbank_guard.get("definition_oracle")
        if isinstance(definition_oracle, Mapping):
            raw_banks = definition_oracle.get("banks")
            if not isinstance(raw_banks, list):
                raise OperationContractError("INVALID_PREVIEW", "Definition guard bank rows are malformed.")
            for index, raw_bank in enumerate(raw_banks):
                if not isinstance(raw_bank, Mapping):
                    raise OperationContractError("INVALID_PREVIEW", "Definition guard bank row is malformed.")
                name = raw_bank.get("name")
                expected_rows = raw_bank.get("pre_state_rows")
                if not isinstance(name, str) or not isinstance(expected_rows, list):
                    raise OperationContractError("INVALID_PREVIEW", "Definition guard bank identity is malformed.")
                _, actual_rows = _read_named_type_rows("SoundBank", name, read=soundbank_read, take=2)
                assertions.append(
                    {
                        "name": f"Definition target SoundBank {index} identity pre-state is unchanged",
                        "passed": actual_rows == expected_rows,
                        "evidence": {"name": name, "expected": expected_rows, "actual": actual_rows},
                    }
                )
                existing_id = raw_bank.get("preexisting_id")
                if existing_id is not None:
                    inclusion_result = soundbank_read(
                        SOUNDBANK_GET_INCLUSIONS_URI,
                        {"soundbank": existing_id},
                        {},
                    )
                    actual_inclusions = _inclusion_rows(_inclusion_map(inclusion_result))
                    expected_inclusions = raw_bank.get("before_inclusions")
                    assertions.append(
                        {
                            "name": f"Definition target SoundBank {index} inclusions are unchanged",
                            "passed": actual_inclusions == expected_inclusions,
                            "evidence": {"expected": expected_inclusions, "actual": actual_inclusions},
                        }
                    )
            control = definition_oracle.get("control")
            if isinstance(control, Mapping):
                result = soundbank_read(
                    SOUNDBANK_GET_INCLUSIONS_URI,
                    {"soundbank": control.get("id")},
                    {},
                )
                actual = _inclusion_rows(_inclusion_map(result))
                expected = control.get("inclusions")
                assertions.append(
                    {
                        "name": "unrelated control SoundBank inclusions are unchanged before dispatch",
                        "passed": actual == expected,
                        "evidence": {"expected": expected, "actual": actual},
                    }
                )

    if isinstance(pre_state, Mapping) and operation == "audio.import":
        file_proofs = pre_state.get("audio_import_files")
        if isinstance(file_proofs, list):
            for proof in file_proofs:
                if not isinstance(proof, Mapping):
                    raise OperationContractError("INVALID_PREVIEW", "audio.import file proof is malformed.")
                try:
                    actual_proof = _regular_file_proof(proof.get("path"), field=f"imports[{proof.get('index')}].audio_file")
                    passed = actual_proof.get("size") == proof.get("size") and actual_proof.get("sha256") == proof.get("sha256")
                    evidence: Any = {"expected": dict(proof), "actual": actual_proof}
                except OperationContractError as exc:
                    passed = False
                    evidence = {"expected": dict(proof), "error": exc.as_dict()}
                assertions.append({"name": f"imports[{proof.get('index')}].audio_file unchanged", "passed": passed, "evidence": evidence})
        target_specs = pre_state.get("audio_import_targets")
        if isinstance(target_specs, list):
            for target in target_specs:
                if not isinstance(target, Mapping) or not isinstance(target.get("canonical_target_path"), str):
                    raise OperationContractError("INVALID_PREVIEW", "audio.import target proof is malformed.")
                args = {"from": {"path": [target["canonical_target_path"]]}}
                options = {"return": list(IDENTITY_RETURN_FIELDS)}
                result = read_call(OBJECT_GET_URI, args, options)
                if not isinstance(result, Mapping):
                    raise OperationContractError("INVALID_READBACK", "audio.import target readback must be an object.")
                rows = _rows(result)
                readbacks.append({"role": f"imports[{target.get('index')}].target", "uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)})
                assertions.append(
                    {
                        "name": f"imports[{target.get('index')}].target remains absent",
                        "passed": len(rows) == 0,
                        "evidence": {"target_path": target["canonical_target_path"], "rows": rows},
                    }
                )

    if isinstance(pre_state, Mapping) and operation == "soundbank.setInclusions":
        inclusion_state = pre_state.get("soundbank_inclusions")
        if isinstance(inclusion_state, Mapping):
            soundbank_id = inclusion_state.get("soundbank_id")
            args = {"soundbank": soundbank_id}
            result = read_call(SOUNDBANK_GET_INCLUSIONS_URI, args, {})
            if not isinstance(result, Mapping):
                raise OperationContractError("INVALID_READBACK", "getInclusions execution guard must return an object.")
            actual = _inclusion_rows(_inclusion_map(result))
            expected = inclusion_state.get("before")
            readbacks.append({"role": "soundbank-inclusions", "uri": SOUNDBANK_GET_INCLUSIONS_URI, "args": args, "options": {}, "result": dict(result)})
            assertions.append(
                {
                    "name": "soundbank inclusions pre-state unchanged",
                    "passed": actual == expected,
                    "evidence": {"expected": expected, "actual": actual},
                }
            )

    if isinstance(pre_state, Mapping) and operation in {"switchContainer.addAssignment", "switchContainer.removeAssignment"}:
        assignment_state = pre_state.get("switch_assignment")
        if isinstance(assignment_state, Mapping):
            container_id = assignment_state.get("switch_container_id")
            selectors = assignment_state.get("selectors")
            if not isinstance(selectors, Mapping):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Switch Container assignment selector evidence is missing.",
                )
            for role in ("switch_container", "child", "state_or_switch"):
                selector = selectors.get(role)
                expected_role = roles.get(role)
                if not isinstance(selector, Mapping) or not isinstance(expected_role, Mapping):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        f"Switch Container assignment {role} selector evidence is malformed.",
                    )
                # Exact IDs are already covered by the bounded role GUID batch.
                # Every other selector must still resolve uniquely to that same
                # GUID, including its recursively resolved parent selector.
                if selector.get("kind") == "id":
                    continue
                try:
                    resolved = _resolve_identity(
                        selector,
                        role=f"{role}.execution_selector",
                        read=read_call,
                    )
                    passed = _same_identity(
                        resolved.object, expected_role.get("object")
                    )
                    evidence: Any = {
                        "selector": dict(selector),
                        "expected_object": expected_role.get("object"),
                        "actual_object": resolved.object,
                    }
                except OperationContractError as exc:
                    passed = False
                    evidence = {
                        "selector": dict(selector),
                        "expected_object": expected_role.get("object"),
                        "error": exc.as_dict(),
                    }
                assertions.append(
                    {
                        "name": f"{role} original selector remains unique and unchanged",
                        "passed": passed,
                        "evidence": evidence,
                    }
                )
            reference_args = {"from": {"id": [container_id]}}
            reference_options = {"return": ["id", "path", SWITCH_GROUP_REFERENCE]}
            reference_result = read_call(OBJECT_GET_URI, reference_args, reference_options)
            if not isinstance(reference_result, Mapping):
                raise OperationContractError("INVALID_READBACK", "SwitchContainer reference execution guard must return an object.")
            reference_rows = _rows(reference_result)
            actual_reference = _reference_identity(_field_value(reference_rows[0], SWITCH_GROUP_REFERENCE)) if len(reference_rows) == 1 else None
            readbacks.append({"role": "switch-container-reference", "uri": OBJECT_GET_URI, "args": reference_args, "options": reference_options, "result": dict(reference_result)})
            assertions.append(
                {
                    "name": "SwitchGroupOrStateGroup reference unchanged",
                    "passed": _same_identity(actual_reference, assignment_state.get("reference_id")),
                    "evidence": {"expected": assignment_state.get("reference_id"), "actual": actual_reference},
                }
            )
            assignment_args = {"id": container_id}
            assignment_result = read_call(SWITCHCONTAINER_GET_ASSIGNMENTS_URI, assignment_args, {})
            if not isinstance(assignment_result, Mapping):
                raise OperationContractError("INVALID_READBACK", "getAssignments execution guard must return an object.")
            actual_assignments = _public_assignment_pairs(_assignment_pairs(assignment_result))
            readbacks.append({"role": "switch-assignments", "uri": SWITCHCONTAINER_GET_ASSIGNMENTS_URI, "args": assignment_args, "options": {}, "result": dict(assignment_result)})
            assertions.append(
                {
                    "name": "Switch Container assignments pre-state unchanged",
                    "passed": actual_assignments == assignment_state.get("assignments"),
                    "evidence": {"expected": assignment_state.get("assignments"), "actual": actual_assignments},
                }
            )

    ok = bool(assertions) and all(item.get("passed") is True for item in assertions)
    return {
        "contract": ROLE_VALIDATION_CONTRACT,
        "operation": operation,
        "ok": ok,
        "status": "valid" if ok else "repreview_required",
        "assertions": [_json_mapping(item) for item in assertions],
        "readbacks": [_json_mapping(item) for item in readbacks],
    }


def _bind_object_set_result_nodes(
    result_nodes: Sequence[ObjectResultNode],
    specs: Sequence[Mapping[str, Any]],
    *,
    on_name_conflict: str,
) -> dict[str, ObjectResultNode]:
    """Bind sparse ``object.set`` associations to the sealed request graph.

    Wwise returns only parent associations that own created child/list objects;
    field-only targets may be absent and association order is not the request
    order.  Parent GUIDs are therefore the only trusted root binding.  Child
    rows are then matched inside that sealed parent topology.  Every explicitly
    requested new node is required exactly once.  Native ``importArg`` may also
    report object children that were created implicitly from the sealed media
    sources; those result-only subtrees are consumed here and proved later by
    the import hash/type/topology verifier.
    """

    spec_by_path: dict[str, Mapping[str, Any]] = {}
    children_by_parent: dict[str, list[Mapping[str, Any]]] = {}
    target_by_id: dict[str, Mapping[str, Any]] = {}
    for spec in specs:
        request_path = spec.get("request_path")
        if not isinstance(request_path, str) or request_path in spec_by_path:
            raise ObjectOperationContractError(
                "INVALID_RESULT_BINDING",
                "object.set verification contains a missing or duplicate request path.",
                details={"request_path": request_path},
            )
        spec_by_path[request_path] = spec
        parent_path = spec.get("parent_request_path")
        if isinstance(parent_path, str):
            children_by_parent.setdefault(parent_path, []).append(spec)
        if spec.get("existing_target") is True:
            target_id = spec.get("target_id")
            try:
                target_key = _identity_key(target_id)
            except OperationContractError as exc:
                raise ObjectOperationContractError(
                    "INVALID_RESULT_BINDING",
                    "object.set verification target lacks a sealed canonical identity.",
                    details={"request_path": request_path, "target_id": target_id},
                ) from exc
            if target_key in target_by_id:
                raise ObjectOperationContractError(
                    "INVALID_RESULT_BINDING",
                    "object.set verification contains duplicate sealed target identities.",
                    details={"target_id": target_id},
                )
            target_by_id[target_key] = spec

    returned_children: dict[str, list[ObjectResultNode]] = {}
    roots: list[ObjectResultNode] = []
    for node in result_nodes:
        if node.parent_request_path is None:
            roots.append(node)
        else:
            returned_children.setdefault(node.parent_request_path, []).append(node)

    bound: dict[str, ObjectResultNode] = {}
    seen_result_ids: dict[str, str] = {}

    def name_matches(node: ObjectResultNode, spec: Mapping[str, Any]) -> bool:
        requested_name = spec.get("requested_name")
        if not isinstance(requested_name, str):
            return False
        if spec.get("preexisting_id") is not None:
            return node.name == requested_name
        effective_conflict = spec.get("on_name_conflict", on_name_conflict)
        if effective_conflict == "rename":
            return node.name == requested_name or node.name.startswith(requested_name)
        return node.name == requested_name

    def consume_import_result_subtree(
        node: ObjectResultNode,
        *,
        import_parent_path: str,
    ) -> None:
        result_id_key = _identity_key(node.object)
        previous_path = seen_result_ids.get(result_id_key)
        if previous_path is not None:
            raise ObjectOperationContractError(
                "DUPLICATE_RESULT_IDENTITY",
                "object.set returned one object identity for multiple result nodes.",
                details={
                    "object_id": node.object,
                    "first_path": previous_path,
                    "request_path": node.request_path,
                },
            )
        seen_result_ids[result_id_key] = (
            f"{import_parent_path}.import-result:{node.request_path}"
        )
        for child in returned_children.get(node.request_path, ()):
            if child.collection != "children":
                raise ObjectOperationContractError(
                    "UNEXPECTED_RESULT_NODE",
                    "object.set import returned an unreviewed object-list association.",
                    details={
                        "import_parent_request_path": import_parent_path,
                        "object_id": child.object,
                        "collection": child.collection,
                    },
                )
            consume_import_result_subtree(
                child,
                import_parent_path=import_parent_path,
            )

    def bind_node(node: ObjectResultNode, spec: Mapping[str, Any]) -> None:
        request_path = str(spec.get("request_path"))
        if request_path in bound:
            raise ObjectOperationContractError(
                "DUPLICATE_RESULT_NODE",
                "object.set returned the same reviewed request node more than once.",
                details={"request_path": request_path},
            )
        result_id_key = _identity_key(node.object)
        previous_path = seen_result_ids.get(result_id_key)
        if previous_path is not None:
            raise ObjectOperationContractError(
                "DUPLICATE_RESULT_IDENTITY",
                "object.set returned one object identity for multiple result nodes.",
                details={"object_id": node.object, "first_path": previous_path, "request_path": request_path},
            )
        sealed_id = spec.get("target_id") if spec.get("existing_target") is True else spec.get("preexisting_id")
        if sealed_id is not None and not _same_identity(node.object, sealed_id):
            raise ObjectOperationContractError(
                "RESULT_IDENTITY_MISMATCH",
                "object.set returned a different identity for a sealed existing node.",
                details={"request_path": request_path, "expected": sealed_id, "actual": node.object},
            )
        bound[request_path] = node
        seen_result_ids[result_id_key] = request_path

        available = list(children_by_parent.get(request_path, ()))
        for child in returned_children.get(node.request_path, ()):  # result-relative parent path
            collection_matches = [
                candidate
                for candidate in available
                if child.collection
                == candidate.get("collection", "children")
            ]
            sealed_matches = [
                candidate
                for candidate in collection_matches
                if candidate.get("preexisting_id") is not None
                and _same_identity(child.object, candidate.get("preexisting_id"))
            ]
            matches = sealed_matches or [
                candidate
                for candidate in collection_matches
                if name_matches(child, candidate)
            ]
            if (
                not matches
                and child.collection == "children"
                and isinstance(spec.get("import"), Mapping)
            ):
                consume_import_result_subtree(
                    child,
                    import_parent_path=request_path,
                )
                continue
            if len(matches) != 1:
                raise ObjectOperationContractError(
                    "UNEXPECTED_RESULT_NODE",
                    "object.set returned a child that cannot be bound uniquely inside the sealed request topology.",
                    details={
                        "parent_request_path": request_path,
                        "object_id": child.object,
                        "name": child.name,
                        "candidate_paths": [candidate.get("request_path") for candidate in matches],
                    },
                )
            matched = matches[0]
            available.remove(matched)
            bind_node(child, matched)

    for root in roots:
        target = target_by_id.get(_identity_key(root.object))
        if target is None:
            raise ObjectOperationContractError(
                "UNKNOWN_RESULT_ASSOCIATION",
                "object.set returned an association for an unsealed parent identity.",
                details={"object_id": root.object, "name": root.name},
            )
        bind_node(root, target)

    required_new_paths = {
        str(spec.get("request_path"))
        for spec in specs
        if spec.get("existing_target") is not True and spec.get("preexisting_id") is None
    }
    missing = sorted(required_new_paths - set(bound))
    if missing:
        raise ObjectOperationContractError(
            "MISSING_RESULT_NODES",
            "object.set omitted one or more newly requested child nodes from its sparse result associations.",
            details={"missing": missing},
        )
    return bound


def _single_plugin_result_object(
    value: Any,
    *,
    collection: str,
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        rows = [dict(value)]
    elif isinstance(value, list) and all(isinstance(row, Mapping) for row in value):
        rows = [dict(row) for row in value]
    else:
        raise OperationContractError(
            "INVALID_PLUGIN_RESULT",
            "object.set plug-in result collection must be one object or an array of objects.",
            details={"collection": collection, "value": value},
        )
    if len(rows) != 1:
        raise OperationContractError(
            "AMBIGUOUS_PLUGIN_RESULT",
            "object.set plug-in result must contain exactly one created object.",
            details={"collection": collection, "rows": rows},
        )
    _plugin_guid(rows[0].get("id"), field=f"result.{collection}.id")
    return rows[0]


def _extract_plugin_result_binding(
    payload: Mapping[str, Any],
    *,
    target_id: str,
    descriptor: PluginCreationDescriptor,
    placement: Mapping[str, Any],
) -> dict[str, Any]:
    raw_associations = payload.get("objects")
    if not isinstance(raw_associations, list) or not all(
        isinstance(row, Mapping) for row in raw_associations
    ):
        raise OperationContractError(
            "INVALID_PLUGIN_RESULT",
            "object.set result must contain an objects array of parent associations.",
            details={"result": dict(payload)},
        )
    associations = [
        dict(row)
        for row in raw_associations
        if _same_identity(row.get("id"), target_id)
    ]
    if len(associations) != 1 or len(raw_associations) != 1:
        raise OperationContractError(
            "AMBIGUOUS_PLUGIN_RESULT",
            "object.set result must bind exactly one association to the sealed target.",
            details={
                "target_id": target_id,
                "association_count": len(raw_associations),
                "matching_associations": associations,
            },
        )
    association = associations[0]
    collection = placement.get("collection")
    if not isinstance(collection, str) or not collection:
        raise OperationContractError(
            "INVALID_PREVIEW",
            "Plug-in verification placement lacks a result collection.",
        )
    if collection not in association:
        raise OperationContractError(
            "MISSING_PLUGIN_RESULT",
            "object.set result omitted the reviewed plug-in result collection.",
            details={
                "collection": collection,
                "association": association,
            },
        )
    created = _single_plugin_result_object(
        association[collection],
        collection=collection,
    )
    expected_type = (
        "EffectSlot"
        if placement.get("kind") == "effect_slot_append"
        else descriptor.object_type
    )
    result_type = created.get("type")
    if result_type is not None and result_type != expected_type:
        raise OperationContractError(
            "PLUGIN_RESULT_TYPE_MISMATCH",
            "object.set returned a different created object type.",
            details={
                "expected": expected_type,
                "actual": result_type,
                "created": created,
            },
        )
    expected_name = "" if expected_type == "EffectSlot" else descriptor.name
    result_name = created.get("name")
    if result_name is not None and result_name != expected_name:
        raise OperationContractError(
            "PLUGIN_RESULT_NAME_MISMATCH",
            "object.set returned a different created object name.",
            details={
                "expected": expected_name,
                "actual": result_name,
                "created": created,
            },
        )
    return {
        "association": association,
        "created": created,
        "created_id": created["id"],
        "expected_type": expected_type,
    }


def verify_prepared_operation(
    prepared: Mapping[str, Any],
    *,
    execution_result: Mapping[str, Any],
    read_call: ReadCall,
) -> VerificationResult:
    """Run the closed postcondition for one persisted prepared operation."""

    if prepared.get("contract") != PREPARED_OPERATION_CONTRACT:
        raise OperationContractError("INVALID_PREVIEW", "Prepared operation contract is missing or unsupported.")
    operation = prepared.get("operation")
    if not isinstance(operation, str):
        raise OperationContractError("INVALID_PREVIEW", "Prepared operation lacks an operation name.")
    plan = prepared.get("verification_plan")
    if not isinstance(plan, Mapping):
        raise OperationContractError("INVALID_PREVIEW", "Prepared operation lacks a verification plan.")
    readbacks: list[Mapping[str, Any]] = []
    assertions: list[Mapping[str, Any]] = []
    success_status = "verified"
    verification_strength = "operation_specific_readback"
    business_state_verified = True

    def read_object(
        *,
        object_id: Any = None,
        path: str | None = None,
        fields: Sequence[str],
        language: str | None = None,
        platform: str | None = None,
    ) -> list[dict[str, Any]]:
        args = {"from": {"id": [object_id]}} if object_id is not None else {"from": {"path": [path]}}
        options = _import_object_get_options(fields, language=language)
        if platform is not None:
            options["platform"] = platform
        result = read_call(OBJECT_GET_URI, args, options)
        if not isinstance(result, Mapping):
            raise OperationContractError("INVALID_READBACK", "object.get verification result must be an object.")
        readbacks.append({"uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)})
        return _rows(result)

    def read_direct_children(*, object_id: Any, fields: Sequence[str]) -> list[dict[str, Any]]:
        args = {"from": {"id": [object_id]}, "transform": [{"select": ["children"]}]}
        options = {"return": list(fields)}
        result = read_call(OBJECT_GET_URI, args, options)
        if not isinstance(result, Mapping):
            raise OperationContractError(
                "INVALID_READBACK",
                "object.get child verification result must be an object.",
            )
        readbacks.append({"uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)})
        return _rows(result)

    def check(name: str, passed: bool, evidence: Any) -> None:
        assertions.append({"name": name, "passed": bool(passed), "evidence": evidence})

    def check_result_schema(uri: str, version: str) -> None:
        try:
            validation = validate_semantic_result(
                uri,
                execution_result.get("result"),
                version=version,
            )
        except SemanticValidationError as exc:
            check("WAAPI result matches the packaged reflected schema", False, exc.as_dict())
        else:
            check("WAAPI result matches the packaged reflected schema", True, validation.as_dict())

    def verified_readback(
        uri: str,
        args: Mapping[str, Any],
        *,
        version: str,
    ) -> Mapping[str, Any]:
        result = read_call(uri, args, {})
        if not isinstance(result, Mapping):
            raise OperationContractError(
                "INVALID_READBACK",
                f"{uri} verification result must be an object.",
                details={"actual_type": type(result).__name__},
            )
        normalized = dict(result)
        readbacks.append({"uri": uri, "args": dict(args), "options": {}, "result": normalized})
        try:
            validation = validate_semantic_result(uri, normalized, version=version)
        except SemanticValidationError as exc:
            check(f"{uri} readback matches the packaged reflected schema", False, exc.as_dict())
        else:
            check(
                f"{uri} readback matches the packaged reflected schema",
                True,
                validation.as_dict(),
            )
        return normalized

    kind = plan.get("kind")
    if kind == "ui-command-plan":
        raw_ui_plan = plan.get("plan")
        version = plan.get("version")
        if not isinstance(raw_ui_plan, Mapping) or not isinstance(version, str):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "UI-command verification lacks its sealed plan or version.",
            )
        try:
            ui_plan = validate_ui_command_plan(raw_ui_plan)
        except UiCommandContractError as exc:
            raise OperationContractError(
                "INVALID_PREVIEW",
                "UI-command verification plan failed its immutable seal.",
                details=exc.as_dict(),
            ) from exc
        try:
            result_evidence = validate_empty_ui_command_result(
                ui_plan,
                execution_result.get("result"),
            )
        except UiCommandContractError as exc:
            check(
                "UI-command result matches the closed empty-result contract",
                False,
                exc.as_dict(),
            )
        else:
            check(
                "UI-command result matches the closed empty-result contract",
                True,
                result_evidence,
            )
        try:
            reflected = validate_semantic_result(
                str(ui_plan["dispatch"]["uri"]),
                execution_result.get("result"),
                version=version,
                authoring_ui_profile=True,
            )
        except SemanticValidationError as exc:
            check(
                "UI-command result matches the Authoring-profile reflected schema",
                False,
                exc.as_dict(),
            )
        else:
            check(
                "UI-command result matches the Authoring-profile reflected schema",
                True,
                reflected.as_dict(),
            )
        ui_operation = ui_plan.get("operation")
        if ui_operation == "execute":
            success_status = "result_schema_checked"
            verification_strength = "result_schema_only"
            business_state_verified = False
        elif ui_operation in {"register", "unregister"}:
            inventory = read_call(UI_COMMAND_GET_COMMANDS_URI, {}, {})
            if not isinstance(inventory, Mapping):
                raise OperationContractError(
                    "INVALID_READBACK",
                    "ui.commands.getCommands postcondition readback must return an object.",
                )
            readbacks.append(
                {
                    "uri": UI_COMMAND_GET_COMMANDS_URI,
                    "args": {},
                    "options": {},
                    "result": dict(inventory),
                }
            )
            try:
                inventory_evidence = verify_ui_command_inventory_postcondition(
                    raw_ui_plan,
                    inventory,
                )
            except UiCommandContractError as exc:
                check(
                    f"UI-command {ui_operation} inventory postcondition holds",
                    False,
                    exc.as_dict(),
                )
            else:
                check(
                    f"UI-command {ui_operation} inventory postcondition holds",
                    True,
                    inventory_evidence,
                )
            verification_strength = "operation_specific_readback"
            business_state_verified = True
        else:
            raise OperationContractError(
                "INVALID_PREVIEW",
                "UI-command verification plan names an unsupported operation.",
                details={"operation": ui_operation},
            )
    elif kind == "undo-group-result-schemas":
        success_status = "result_schema_checked"
        business_state_verified = False
        version = plan.get("version")
        execution_plan = plan.get("execution_plan")
        compound_payload = execution_result.get("result")
        if (
            not isinstance(version, str)
            or not isinstance(execution_plan, Mapping)
            or not isinstance(compound_payload, Mapping)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Undo Group verification lacks a versioned execution plan or recorded compound result.",
            )
        raw_phases = compound_payload.get("phases")
        phases = raw_phases if isinstance(raw_phases, list) else []
        inner_plan = execution_plan.get("calls")
        if not isinstance(inner_plan, list):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Undo Group execution plan lacks its inner call list.",
            )
        expected_uris = [UNDO_BEGIN_GROUP_URI]
        expected_uris.extend(
            item.get("api") for item in inner_plan if isinstance(item, Mapping)
        )
        expected_uris.append(UNDO_END_GROUP_URI)
        actual_uris = [
            phase.get("uri") if isinstance(phase, Mapping) else None
            for phase in phases
        ]
        check(
            "Undo Group recorded the exact immutable phase order",
            actual_uris == expected_uris,
            {"expected": expected_uris, "actual": actual_uris},
        )
        partial_schema = False
        if actual_uris == expected_uris:
            for index, phase in enumerate(phases):
                if not isinstance(phase, Mapping):
                    check(f"Undo Group phase {index} is structured", False, phase)
                    continue
                dispatch_result = phase.get("dispatch_result")
                uri = phase.get("uri")
                if not isinstance(dispatch_result, Mapping) or not isinstance(uri, str):
                    check(
                        f"Undo Group phase {index} recorded a structured dispatch result",
                        False,
                        dict(phase),
                    )
                    continue
                check(
                    f"Undo Group phase {index} dispatch succeeded",
                    dispatch_result.get("ok") is True,
                    {"uri": uri, "error_code": dispatch_result.get("error_code")},
                )
                try:
                    validation = validate_semantic_result(
                        uri,
                        dispatch_result.get("result"),
                        version=version,
                    )
                except SemanticValidationError as exc:
                    check(
                        f"Undo Group phase {index} result matches the packaged reflected schema",
                        False,
                        exc.as_dict(),
                    )
                else:
                    partial_schema = partial_schema or bool(validation.unresolved_refs)
                    check(
                        f"Undo Group phase {index} result matches the packaged reflected schema",
                        True,
                        validation.as_dict(),
                    )
        verification_strength = (
            "partial_reflected_schema" if partial_schema else "complete_reflected_schema"
        )
    elif kind == "result-schema":
        success_status = "result_schema_checked"
        business_state_verified = False
        uri = plan.get("uri")
        version = plan.get("version")
        if not isinstance(uri, str) or not isinstance(version, str):
            raise OperationContractError("INVALID_PREVIEW", "result-schema verification lacks uri/version.")
        try:
            validation = validate_semantic_result(
                uri,
                execution_result.get("result"),
                version=version,
            )
        except SemanticValidationError as exc:
            check(
                "WAAPI result matches the packaged reflected schema",
                False,
                exc.as_dict(),
            )
        else:
            verification_strength = (
                "partial_reflected_schema"
                if validation.unresolved_refs
                else "complete_reflected_schema"
            )
            check(
                "WAAPI result matches the packaged reflected schema",
                True,
                validation.as_dict(),
            )
    elif kind == "remote-connection-state":
        uri = plan.get("uri")
        version = plan.get("version")
        expected_connected = plan.get("expected_connected")
        if (
            uri not in {REMOTE_CONNECT_URI, REMOTE_DISCONNECT_URI}
            or not isinstance(version, str)
            or not isinstance(expected_connected, bool)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Remote connection verification lacks a valid uri/version/postcondition.",
            )
        check_result_schema(str(uri), version)
        status = verified_readback(REMOTE_GET_CONNECTION_STATUS_URI, {}, version=version)
        actual_connected = status.get("isConnected")
        check(
            "remote connection state matches the requested postcondition",
            isinstance(actual_connected, bool) and actual_connected is expected_connected,
            {"expected": expected_connected, "actual": actual_connected, "status": status.get("status")},
        )
    elif kind == "transport-created":
        uri = plan.get("uri")
        version = plan.get("version")
        if uri != TRANSPORT_CREATE_URI or not isinstance(version, str):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Transport creation verification lacks a valid uri/version.",
            )
        check_result_schema(uri, version)
        transport_id = _execution_payload(execution_result).get("transport")
        valid_transport_id = _valid_transport_id(transport_id)
        check(
            "transport.create returned a non-zero uint32 transport ID",
            valid_transport_id,
            {"transport": transport_id},
        )
        if valid_transport_id:
            transport_list = verified_readback(TRANSPORT_GET_LIST_URI, {}, version=version)
            rows, list_shape_ok = _transport_list_rows(transport_list)
            check(
                "transport.getList returned transport rows with valid IDs",
                list_shape_ok,
                {"list": transport_list.get("list")},
            )
            matches = [row for row in rows if row.get("transport") == transport_id]
            check(
                "created transport ID appears exactly once in transport.getList",
                list_shape_ok and len(matches) == 1,
                {"transport": transport_id, "matches": matches},
            )
            transport_state = verified_readback(
                TRANSPORT_GET_STATE_URI,
                {"transport": transport_id},
                version=version,
            )
            state = transport_state.get("state")
            check(
                "created transport ID resolves through transport.getState",
                isinstance(state, str) and state in TRANSPORT_STATES,
                {"transport": transport_id, "state": state},
            )
    elif kind == "transport-destroyed":
        uri = plan.get("uri")
        version = plan.get("version")
        transport_id = plan.get("transport_id")
        if (
            uri != TRANSPORT_DESTROY_URI
            or not isinstance(version, str)
            or not _valid_transport_id(transport_id)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Transport destruction verification lacks a valid uri/version/transport ID.",
            )
        check_result_schema(uri, version)
        transport_list = verified_readback(TRANSPORT_GET_LIST_URI, {}, version=version)
        rows, list_shape_ok = _transport_list_rows(transport_list)
        check(
            "transport.getList returned transport rows with valid IDs",
            list_shape_ok,
            {"list": transport_list.get("list")},
        )
        matches = [row for row in rows if row.get("transport") == transport_id]
        check(
            "destroyed transport ID is absent from transport.getList",
            list_shape_ok and not matches,
            {"transport": transport_id, "matches": matches},
        )
    elif kind == "soundbank-artifact-exact":
        source_operation = plan.get("source_operation")
        version = plan.get("version")
        uri = plan.get("uri")
        closed_plan = plan.get("plan")
        before_snapshots = plan.get("artifact_snapshots")
        expected_uri = {
            "soundbank.generate": "ak.wwise.core.soundbank.generate",
            "soundbank.convertExternalSources": "ak.wwise.core.soundbank.convertExternalSources",
        }.get(source_operation)
        if (
            source_operation not in {"soundbank.generate", "soundbank.convertExternalSources"}
            or source_operation != operation
            or uri != expected_uri
            or version not in SUPPORTED_WWISE_VERSION_KEYS
            or not isinstance(closed_plan, Mapping)
            or not isinstance(before_snapshots, list)
            or not all(isinstance(item, Mapping) for item in before_snapshots)
        ):
            raise OperationContractError("INVALID_PREVIEW", "Closed SoundBank artifact verification plan is malformed.")
        check_result_schema(str(uri), str(version))
        payload = _execution_payload(execution_result)
        for proof_index, proof in enumerate(_soundbank_input_file_proofs(closed_plan, include_project=True)):
            try:
                actual_proof = verify_soundbank_file_proof(proof, field=f"soundbank.input_proof[{proof_index}]")
            except SoundBankContractError as exc:
                check(f"SoundBank input file proof {proof_index} is unchanged after execution", False, exc.as_dict())
            else:
                check(
                    f"SoundBank input file proof {proof_index} is unchanged after execution",
                    True,
                    {"expected": dict(proof), "actual": actual_proof},
                )
        if source_operation == "soundbank.generate":
            logs = payload.get("logs", [])
            log_rows = [dict(row) for row in logs if isinstance(row, Mapping)] if isinstance(logs, list) else []
            check(
                "SoundBank generation logs have a structured array shape when present",
                isinstance(logs, list) and len(log_rows) == len(logs),
                logs,
            )
            error_logs = [row for row in log_rows if _log_entry_is_error(row)]
            check("SoundBank generation log contains no error", not error_logs, error_logs)
            error_text = payload.get("error")
            check(
                "SoundBank generation first-error field is absent or empty",
                error_text is None or error_text == "",
                {"error": error_text},
            )

        after_snapshots: list[dict[str, Any]] = []
        for index, before in enumerate(before_snapshots):
            root = before.get("root")
            io_root = before.get("io_root")
            if not isinstance(root, str) or not isinstance(io_root, str):
                raise OperationContractError("INVALID_PREVIEW", "SoundBank artifact snapshot lacks root/io_root.")
            try:
                after = capture_artifact_tree(root, io_root=io_root)
            except SoundBankContractError as exc:
                check(f"SoundBank artifact tree {index} can be captured after execution", False, exc.as_dict())
                after_snapshots.append(
                    {
                        "root": root,
                        "resolved_root": before.get("resolved_root", root),
                        "io_root": io_root,
                        "files": [],
                        "capture_error": exc.as_dict(),
                    }
                )
                continue
            after_snapshots.append(after)
            try:
                delta = compare_artifact_trees(before, after, require_expected_change=False)
            except SoundBankContractError as exc:
                check(f"SoundBank artifact tree {index} delta is valid", False, exc.as_dict())
            else:
                check(
                    f"SoundBank artifact tree {index} changed or remained structurally valid",
                    bool(delta.get("verified")),
                    delta,
                )
        check(
            "every reviewed SoundBank artifact root was captured after execution",
            len(after_snapshots) == len(before_snapshots)
            and all("capture_error" not in item for item in after_snapshots),
            {
                "expected": len(before_snapshots),
                "actual": len(after_snapshots),
                "capture_errors": [item.get("capture_error") for item in after_snapshots if "capture_error" in item],
            },
        )

        if source_operation == "soundbank.generate":
            artifact_plan = closed_plan.get("artifact_plan")
            platforms = artifact_plan.get("platforms") if isinstance(artifact_plan, Mapping) else None
            if not isinstance(platforms, list):
                raise OperationContractError("INVALID_PREVIEW", "SoundBank generation artifact oracle is malformed.")
            for platform_index, platform in enumerate(platforms):
                if not isinstance(platform, Mapping):
                    raise OperationContractError("INVALID_PREVIEW", "SoundBank generation platform oracle is malformed.")
                banks = platform.get("expected_user_soundbanks")
                if not isinstance(banks, list):
                    raise OperationContractError("INVALID_PREVIEW", "SoundBank generation Bank oracle is malformed.")
                for bank_index, bank in enumerate(banks):
                    expected_artifacts = bank.get("expected_artifacts") if isinstance(bank, Mapping) else None
                    if (
                        not isinstance(bank, Mapping)
                        or bank.get("artifact_expectation") not in {"nonlocalized", "localized", "mixed"}
                        or not isinstance(expected_artifacts, list)
                        or not expected_artifacts
                    ):
                        raise OperationContractError("INVALID_PREVIEW", "SoundBank generation exact artifact oracle is malformed.")
                    for artifact_index, artifact in enumerate(expected_artifacts):
                        if (
                            not isinstance(artifact, Mapping)
                            or artifact.get("kind") not in {"nonlocalized", "localized"}
                            or not isinstance(artifact.get("path"), str)
                            or (
                                artifact.get("kind") == "localized"
                                and not isinstance(artifact.get("language"), str)
                            )
                            or (
                                artifact.get("kind") == "nonlocalized"
                                and artifact.get("language") is not None
                            )
                        ):
                            raise OperationContractError(
                                "INVALID_PREVIEW",
                                "A SoundBank generation exact artifact row is malformed.",
                            )
                        evidence = _artifact_candidate_evidence(
                            artifact["path"],
                            before_snapshots,
                            after_snapshots,
                        )
                        check(
                            f"requested SoundBank artifact {platform_index}:{bank_index}:{artifact_index} was created or modified and is non-empty",
                            evidence.get("after_nonempty") is True
                            and evidence.get("created_or_modified") is True,
                            {
                                "bank": bank.get("name"),
                                "platform": platform.get("name"),
                                "expectation": bank.get("artifact_expectation"),
                                "artifact": dict(artifact),
                                "evidence": evidence,
                            },
                        )
        else:
            raw_requests = closed_plan.get("requests")
            if not isinstance(raw_requests, list):
                raise OperationContractError("INVALID_PREVIEW", "External Sources output oracle is malformed.")
            allowed_by_root: dict[str, set[str]] = {}
            for request_index, raw_request in enumerate(raw_requests):
                if not isinstance(raw_request, Mapping):
                    raise OperationContractError("INVALID_PREVIEW", "External Sources request oracle is malformed.")
                output_root = raw_request.get("output_root")
                outputs = raw_request.get("expected_outputs")
                if not isinstance(output_root, str) or not isinstance(outputs, list):
                    raise OperationContractError("INVALID_PREVIEW", "External Sources output rows are malformed.")
                allowed = allowed_by_root.setdefault(str(Path(output_root).resolve(strict=False)), {"Wwise.dat"})
                for output_index, raw_output in enumerate(outputs):
                    if not isinstance(raw_output, Mapping):
                        raise OperationContractError("INVALID_PREVIEW", "External Sources expected output is malformed.")
                    absolute_path = raw_output.get("absolute_path")
                    relative_path = raw_output.get("relative_path")
                    evidence = _artifact_candidate_evidence(absolute_path, before_snapshots, after_snapshots)
                    check(
                        f"External Sources output {request_index}:{output_index} was created or modified and is non-empty",
                        evidence.get("after_nonempty") is True and evidence.get("created_or_modified") is True,
                        evidence,
                    )
                    if isinstance(relative_path, str):
                        allowed.add(relative_path)
            for before, after in zip(before_snapshots, after_snapshots, strict=False):
                root = str(Path(str(before.get("root"))).resolve(strict=False))
                allowed = sorted(allowed_by_root.get(root, {"Wwise.dat"}))
                try:
                    delta = compare_artifact_trees(
                        before,
                        after,
                        allowed_relative_paths=allowed,
                        require_expected_change=False,
                        enforce_no_unexpected_changes=True,
                    )
                except SoundBankContractError as exc:
                    check(f"External Sources output tree {root} delta is closed", False, exc.as_dict())
                else:
                    check(
                        f"External Sources output tree {root} changed only at reviewed paths",
                        bool(delta.get("verified")),
                        delta,
                    )
    elif kind == "soundbank-definition-exact":
        source_operation = plan.get("source_operation")
        version = plan.get("version")
        uri = plan.get("uri")
        oracle = plan.get("definition_oracle")
        closed_plan = plan.get("plan")
        if (
            source_operation != "soundbank.processDefinitionFiles"
            or operation != source_operation
            or uri != "ak.wwise.core.soundbank.processDefinitionFiles"
            or version not in {"2022.1", "2023.1", "2024.1", "2025.1"}
            or not isinstance(oracle, Mapping)
            or not isinstance(closed_plan, Mapping)
        ):
            raise OperationContractError("INVALID_PREVIEW", "Closed Definition verification plan is malformed.")
        check_result_schema(str(uri), str(version))
        for proof_index, proof in enumerate(_soundbank_input_file_proofs(closed_plan, include_project=False)):
            try:
                actual_proof = verify_soundbank_file_proof(proof, field=f"definition.input_proof[{proof_index}]")
            except SoundBankContractError as exc:
                check(f"Definition input file proof {proof_index} is unchanged after execution", False, exc.as_dict())
            else:
                check(
                    f"Definition input file proof {proof_index} is unchanged after execution",
                    True,
                    {"expected": dict(proof), "actual": actual_proof},
                )
        raw_banks = oracle.get("banks")
        if not isinstance(raw_banks, list) or not raw_banks:
            raise OperationContractError("INVALID_PREVIEW", "Closed Definition verification lacks target banks.")
        for index, raw_bank in enumerate(raw_banks):
            if not isinstance(raw_bank, Mapping) or not isinstance(raw_bank.get("name"), str):
                raise OperationContractError("INVALID_PREVIEW", "Closed Definition target Bank is malformed.")
            name = str(raw_bank["name"])
            query = f"from type SoundBank where name = {json.dumps(name, ensure_ascii=False)} take 2"
            args = {"waql": query}
            options = {"return": list(IDENTITY_RETURN_FIELDS)}
            result = read_call(OBJECT_GET_URI, args, options)
            if not isinstance(result, Mapping):
                raise OperationContractError("INVALID_READBACK", "Definition target SoundBank readback must be an object.")
            rows = _rows(result)
            readbacks.append({"uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)})
            check(f"Definition target SoundBank {index} resolves exactly once", len(rows) == 1, {"name": name, "rows": rows})
            if len(rows) != 1:
                continue
            bank_id = rows[0].get("id")
            check(f"Definition target SoundBank {index} returned a canonical GUID", _valid_object_id(bank_id), bank_id)
            preexisting_id = raw_bank.get("preexisting_id")
            if preexisting_id is not None:
                check(
                    f"Definition target SoundBank {index} preserved its existing GUID",
                    _same_identity(bank_id, preexisting_id),
                    {"expected": preexisting_id, "actual": bank_id},
                )
            if not _valid_object_id(bank_id):
                continue
            inclusion_result = read_call(SOUNDBANK_GET_INCLUSIONS_URI, {"soundbank": bank_id}, {})
            if not isinstance(inclusion_result, Mapping):
                raise OperationContractError("INVALID_READBACK", "Definition getInclusions readback must be an object.")
            readbacks.append(
                {
                    "uri": SOUNDBANK_GET_INCLUSIONS_URI,
                    "args": {"soundbank": bank_id},
                    "options": {},
                    "result": dict(inclusion_result),
                }
            )
            actual = _inclusion_rows(_inclusion_map(inclusion_result))
            expected = raw_bank.get("expected_inclusions")
            check(
                f"Definition target SoundBank {index} has the exact additive inclusion set",
                actual == expected,
                {"expected": expected, "actual": actual},
            )
        control = oracle.get("control")
        if isinstance(control, Mapping):
            control_id = control.get("id")
            result = read_call(SOUNDBANK_GET_INCLUSIONS_URI, {"soundbank": control_id}, {})
            if not isinstance(result, Mapping):
                raise OperationContractError("INVALID_READBACK", "Control SoundBank getInclusions readback must be an object.")
            readbacks.append(
                {
                    "uri": SOUNDBANK_GET_INCLUSIONS_URI,
                    "args": {"soundbank": control_id},
                    "options": {},
                    "result": dict(result),
                }
            )
            actual = _inclusion_rows(_inclusion_map(result))
            expected = control.get("inclusions")
            check("unrelated control SoundBank inclusions are unchanged", actual == expected, {"expected": expected, "actual": actual})
    elif kind == "object-plugin-created":
        version = plan.get("version")
        target_id = plan.get("target_id")
        target_type = plan.get("target_type")
        raw_descriptor = plan.get("descriptor")
        placement = plan.get("placement")
        preexisting_ids = plan.get("preexisting_plugin_ids")
        raw_property_validation = plan.get("property_validation")
        raw_readback_fields = plan.get("readback_fields")
        raw_readback_view = plan.get("readback_view")
        if (
            version not in SUPPORTED_PLUGIN_VERSIONS
            or not isinstance(target_id, str)
            or not _PLUGIN_GUID.fullmatch(target_id)
            or not isinstance(target_type, str)
            or not target_type
            or not isinstance(raw_descriptor, Mapping)
            or not isinstance(placement, Mapping)
            or not isinstance(preexisting_ids, list)
            or not all(
                isinstance(value, str) and _PLUGIN_GUID.fullmatch(value)
                for value in preexisting_ids
            )
            or len({value.casefold() for value in preexisting_ids})
            != len(preexisting_ids)
            or not isinstance(raw_readback_fields, list)
            or not isinstance(raw_readback_view, Mapping)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "object.createPlugin verification plan is malformed.",
            )
        try:
            descriptor = normalize_plugin_creation(raw_descriptor)
        except PluginOperationContractError as exc:
            raise OperationContractError(
                "INVALID_PREVIEW",
                "object.createPlugin verification descriptor is malformed.",
                details=exc.as_dict(),
            ) from exc

        expected_readback_fields = list(plugin_verification_fields(descriptor))
        if raw_readback_fields != expected_readback_fields:
            raise OperationContractError(
                "INVALID_PREVIEW",
                "object.createPlugin verification fields do not match the "
                "immutable descriptor.",
                details={
                    "expected": expected_readback_fields,
                    "actual": raw_readback_fields,
                },
            )
        if (
            set(raw_readback_view) != {"language", "platform"}
            or raw_readback_view.get("language") != descriptor.language
            or raw_readback_view.get("platform") != descriptor.platform
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "object.createPlugin verification language/platform view does "
                "not match the immutable descriptor.",
                details={
                    "expected": {
                        "language": descriptor.language,
                        "platform": descriptor.platform,
                    },
                    "actual": dict(raw_readback_view),
                },
            )
        validated_properties = _sealed_plugin_property_validation(
            raw_property_validation,
            descriptor=descriptor,
        )

        base_plan_fields = {
            "kind",
            "version",
            "target_id",
            "target_type",
            "descriptor",
            "placement",
            "preexisting_plugin_ids",
            "property_validation",
            "readback_fields",
            "readback_view",
        }
        if descriptor.kind == "source":
            expected_plan_fields = base_plan_fields
            expected_placement_kind = "source_child"
            placement_shape_matches = (
                placement.get("collection") == "children"
            )
        elif version == "2022.1":
            expected_plan_fields = base_plan_fields | {
                "pre_effect_references"
            }
            expected_placement_kind = "fixed_effect_reference"
            selected_effect_field = placement.get("effect_slot")
            placement_shape_matches = (
                selected_effect_field in WWISE_2022_EFFECT_FIELDS
                and placement.get("collection") == selected_effect_field
            )
        else:
            expected_plan_fields = base_plan_fields | {
                "preexisting_effect_slot_ids"
            }
            expected_placement_kind = "effect_slot_append"
            placement_shape_matches = (
                placement.get("collection") == "@Effects"
            )
        if (
            set(plan) != expected_plan_fields
            or placement.get("kind") != expected_placement_kind
            or not placement_shape_matches
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "object.createPlugin verification placement is malformed for "
                "the immutable version and plug-in kind.",
                details={
                    "version": version,
                    "plugin_kind": descriptor.kind,
                    "placement": dict(placement),
                    "missing_plan_fields": sorted(
                        expected_plan_fields - set(plan)
                    ),
                    "unknown_plan_fields": sorted(
                        set(plan) - expected_plan_fields
                    ),
                },
            )

        pre_effect_references: Mapping[str, Any] | None = None
        preexisting_effect_slot_ids: list[str] | None = None
        if expected_placement_kind == "fixed_effect_reference":
            raw_pre_effect_references = plan.get("pre_effect_references")
            if (
                not isinstance(raw_pre_effect_references, Mapping)
                or set(raw_pre_effect_references)
                != set(WWISE_2022_EFFECT_FIELDS)
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "object.createPlugin fixed Effect pre-state is malformed.",
                )
            pre_effect_references = dict(raw_pre_effect_references)
        elif expected_placement_kind == "effect_slot_append":
            raw_preexisting_slot_ids = plan.get(
                "preexisting_effect_slot_ids"
            )
            if (
                not isinstance(raw_preexisting_slot_ids, list)
                or not all(
                    isinstance(value, str)
                    and _PLUGIN_GUID.fullmatch(value)
                    for value in raw_preexisting_slot_ids
                )
                or len(
                    {
                        value.casefold()
                        for value in raw_preexisting_slot_ids
                    }
                )
                != len(raw_preexisting_slot_ids)
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "object.createPlugin EffectSlot pre-state is malformed.",
                )
            preexisting_effect_slot_ids = list(
                raw_preexisting_slot_ids
            )

        readback_view = {
            "fields": list(raw_readback_fields),
            "language": raw_readback_view.get("language"),
            "platform": raw_readback_view.get("platform"),
        }
        check_result_schema(OBJECT_SET_URI, version)
        try:
            result_binding = _extract_plugin_result_binding(
                _execution_payload(execution_result),
                target_id=target_id,
                descriptor=descriptor,
                placement=placement,
            )
        except OperationContractError as exc:
            check(
                "object.set returned exactly one plug-in placement binding",
                False,
                exc.as_dict(),
            )
            return _verification(operation, assertions, readbacks)
        check(
            "object.set returned exactly one plug-in placement binding",
            True,
            result_binding,
        )

        created_id = result_binding["created_id"]
        expected_parent_id = target_id
        if expected_placement_kind == "source_child":
            plugin_id = created_id
            placement_evidence: dict[str, Any] = {
                "kind": "source_child"
            }
        elif expected_placement_kind == "fixed_effect_reference":
            target_rows = read_object(
                object_id=target_id,
                fields=PLUGIN_2022_EFFECT_TARGET_READBACK_FIELDS,
            )
            check(
                "Wwise 2022.1 Effect target GUID resolves exactly once",
                len(target_rows) == 1,
                target_rows,
            )
            if len(target_rows) != 1:
                return _verification(
                    operation,
                    assertions,
                    readbacks,
                )
            plugin_id = created_id
            placement_evidence = {
                "kind": "fixed_effect_reference",
                "selected_effect_field": placement["effect_slot"],
                "pre_effect_references": dict(
                    pre_effect_references or {}
                ),
                "target_post_readback": target_rows[0],
            }
        else:
            slot_id = created_id
            slot_rows = read_object(
                object_id=slot_id,
                fields=PLUGIN_EFFECT_SLOT_READBACK_FIELDS,
            )
            check(
                "created EffectSlot GUID resolves exactly once",
                len(slot_rows) == 1,
                slot_rows,
            )
            if len(slot_rows) != 1:
                return _verification(operation, assertions, readbacks)
            slot = slot_rows[0]
            try:
                plugin_id = _plugin_guid(
                    slot.get("@Effect"),
                    field="created_effect_slot.@Effect",
                )
            except OperationContractError as exc:
                check(
                    "created EffectSlot exposes one canonical @Effect binding",
                    False,
                    exc.as_dict(),
                )
                return _verification(operation, assertions, readbacks)
            check(
                "created EffectSlot exposes one canonical @Effect binding",
                True,
                {"effect_slot_id": slot_id, "plugin_id": plugin_id},
            )
            expected_parent_id = slot_id
            placement_evidence = {
                "kind": "effect_slot_append",
                "preexisting_effect_slot_ids": list(
                    preexisting_effect_slot_ids or []
                ),
                "created_effect_slot": slot,
            }

        plugin_rows = read_object(
            object_id=plugin_id,
            fields=raw_readback_fields,
            language=descriptor.language,
            platform=descriptor.platform,
        )
        check(
            "created plug-in GUID resolves exactly once",
            len(plugin_rows) == 1,
            plugin_rows,
        )
        if len(plugin_rows) != 1:
            return _verification(operation, assertions, readbacks)
        try:
            evidence = verify_created_plugin_row(
                descriptor,
                plugin_rows[0],
                version=version,
                expected_parent_id=expected_parent_id,
                expected_owner_id=target_id,
                validated_properties=validated_properties,
                preexisting_plugin_ids=preexisting_ids,
                readback_view=readback_view,
                placement_evidence=placement_evidence,
            )
        except PluginOperationContractError as exc:
            check(
                "created plug-in requested state and placement match the immutable plan",
                False,
                exc.as_dict(),
            )
        else:
            check(
                "created plug-in requested state and placement match the immutable plan",
                True,
                evidence.as_dict(),
            )
    elif kind in {"object-create-graph", "object-set-batch"}:
        version = plan.get("version")
        if not isinstance(version, str):
            raise OperationContractError("INVALID_PREVIEW", "Object graph verification lacks a version.")
        uri = "ak.wwise.core.object.create" if kind == "object-create-graph" else "ak.wwise.core.object.set"
        check_result_schema(uri, version)
        raw_specs = plan.get("nodes")
        if not isinstance(raw_specs, list) or not all(isinstance(row, Mapping) for row in raw_specs):
            raise OperationContractError("INVALID_PREVIEW", "Object graph verification nodes are malformed.")
        specs = [dict(row) for row in raw_specs]
        verified_import_direct_child_ids: dict[str, set[str]] = {}
        object_set_originals_root: str | None = None
        if kind == "object-set-batch" and any(
            isinstance(spec.get("import"), Mapping) for spec in specs
        ):
            raw_pre_state = prepared.get("pre_state")
            raw_import_guard = (
                raw_pre_state.get("import_guard")
                if isinstance(raw_pre_state, Mapping)
                else None
            )
            raw_originals_context = (
                raw_import_guard.get("originals_context")
                if isinstance(raw_import_guard, Mapping)
                else None
            )
            object_set_originals_root = _import_originals_root_from_context(
                raw_originals_context,
                version=version,
            )
        payload = _execution_payload(execution_result)
        result_nodes: tuple[ObjectResultNode, ...] = ()
        result_by_path: dict[str, ObjectResultNode] = {}
        try:
            if kind == "object-create-graph":
                result_nodes = flatten_create_result(payload)
                result_by_path = {row.request_path: row for row in result_nodes}
            else:
                raw_list_names = plan.get("list_names", [])
                if not isinstance(raw_list_names, list) or not all(
                    isinstance(item, str) for item in raw_list_names
                ):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "Object-set list-name verification scope is malformed.",
                    )
                result_nodes = flatten_set_result(
                    payload,
                    allowed_lists=raw_list_names,
                )
                result_by_path = _bind_object_set_result_nodes(
                    result_nodes,
                    specs,
                    on_name_conflict=str(plan.get("on_name_conflict")),
                )
        except ObjectOperationContractError as exc:
            assertion_name = (
                "returned object topology is structurally valid"
                if kind == "object-create-graph"
                else "sparse object.set result associations bind exactly to the sealed request graph"
            )
            check(assertion_name, False, exc.as_dict())
            if kind == "object-create-graph":
                return _verification(operation, assertions, readbacks)
        else:
            if kind == "object-create-graph":
                expected_paths = [row.get("request_path") for row in specs]
                actual_paths = [row.request_path for row in result_nodes]
                check(
                    "returned object topology contains every requested node exactly once",
                    len(expected_paths) == len(set(expected_paths)) and actual_paths == expected_paths,
                    {"expected": expected_paths, "actual": actual_paths},
                )
            else:
                check(
                    "sparse object.set result associations bind exactly to the sealed request graph",
                    True,
                    {
                        "returned_association_count": sum(
                            row.parent_request_path is None for row in result_nodes
                        ),
                        "returned_node_count": len(result_nodes),
                        "bound_request_paths": sorted(result_by_path),
                    },
                )
        spec_by_path = {str(row.get("request_path")): row for row in specs}
        resolved_id_by_path: dict[str, Any] = {}
        for spec in specs:
            request_path = str(spec.get("request_path"))
            result_node = result_by_path.get(request_path)
            if kind == "object-set-batch" and spec.get("existing_target") is True:
                object_id = spec.get("target_id")
            elif kind == "object-set-batch" and spec.get("preexisting_id") is not None:
                object_id = spec.get("preexisting_id")
            elif result_node is not None:
                object_id = result_node.object
            else:
                continue
            resolved_id_by_path[request_path] = object_id
            check(
                f"{request_path} has a canonical verification GUID",
                _valid_object_id(object_id),
                {
                    "id": object_id,
                    "returned": result_node is not None,
                    "returned_name": result_node.name if result_node is not None else None,
                },
            )
            if not _valid_object_id(object_id):
                continue
            if spec.get("existing_target") is True and result_node is not None:
                check(
                    f"{request_path} returned association retained its sealed target GUID",
                    _same_identity(result_node.object, spec.get("target_id")),
                    {"expected": spec.get("target_id"), "actual": result_node.object},
                )
            preexisting_id = spec.get("preexisting_id")
            if preexisting_id is not None and result_node is not None:
                check(
                    f"{request_path} merge retained the pre-existing GUID",
                    _same_identity(result_node.object, preexisting_id),
                    {"expected": preexisting_id, "actual": result_node.object},
                )
            fields = _object_spec_return_fields(spec)
            platform = spec.get("platform")
            if platform is not None and (not isinstance(platform, str) or not platform):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Object graph verification platform is malformed.",
                )
            requested_language = spec.get("requested_language")
            if requested_language is not None and (
                not isinstance(requested_language, str)
                or not requested_language
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Object graph verification language is malformed.",
                )
            rows = read_object(
                object_id=object_id,
                fields=fields,
                language=_localized_import_read_language(requested_language),
                platform=platform,
            )
            check(f"{request_path} GUID resolves exactly once", len(rows) == 1, rows)
            if len(rows) != 1:
                continue
            row = rows[0]
            check(
                f"{request_path} readback GUID matches the result",
                _same_identity(row.get("id"), object_id),
                {"expected": object_id, "actual": row.get("id")},
            )
            check(
                f"{request_path} reflected type matches the live-resolved request type",
                _object_type_matches(row.get("type"), spec),
                {"requested": spec.get("requested_type"), "canonical": spec.get("canonical_type"), "actual": row.get("type")},
            )
            returned_name = result_node.name if result_node is not None else None
            effective_conflict = spec.get(
                "on_name_conflict",
                plan.get("on_name_conflict"),
            )
            if effective_conflict == "rename" and (
                spec.get("existing_target") is not True
                or spec.get("original_name") != spec.get("requested_name")
            ):
                actual_name = row.get("name")
                requested_name = spec.get("requested_name")
                name_ok = (
                    isinstance(actual_name, str)
                    and isinstance(requested_name, str)
                    and (
                        actual_name == requested_name
                        or actual_name.startswith(requested_name)
                    )
                    and (
                        result_node is None
                        or actual_name == returned_name
                    )
                )
            else:
                name_ok = row.get("name") == spec.get("requested_name") and (
                    result_node is None or row.get("name") == returned_name
                )
            check(
                f"{request_path} name follows the reviewed conflict policy",
                name_ok,
                {"requested": spec.get("requested_name"), "result": returned_name, "actual": row.get("name")},
            )
            parent_request_path = spec.get("parent_request_path")
            if kind == "object-create-graph" and parent_request_path is None:
                expected_parent_id = plan.get("parent_id")
            elif isinstance(parent_request_path, str):
                parent_result = result_by_path.get(parent_request_path)
                parent_spec = spec_by_path.get(parent_request_path)
                expected_parent_id = (
                    resolved_id_by_path.get(parent_request_path)
                    or (parent_result.object if parent_result is not None else None)
                    or (
                        parent_spec.get("target_id")
                        if isinstance(parent_spec, Mapping)
                        else None
                    )
                )
            else:
                expected_parent_id = spec.get("expected_parent_id")
            if expected_parent_id is not None:
                collection = spec.get("collection")
                if collection not in {None, "children"}:
                    actual_owner = _reference_identity(row.get("owner"))
                    check(
                        f"{request_path} list owner matches the requested topology",
                        _same_identity(actual_owner, expected_parent_id),
                        {"expected": expected_parent_id, "actual": actual_owner},
                    )
                else:
                    check(
                        f"{request_path} parent edge matches the requested topology",
                        _same_identity(_parent_value(row.get("parent")), expected_parent_id),
                        {"expected": expected_parent_id, "actual": _parent_value(row.get("parent"))},
                    )
            expected_path = spec.get("expected_path")
            if isinstance(expected_path, str):
                check(
                    f"{request_path} exact path matches",
                    row.get("path") == expected_path,
                    {"expected": expected_path, "actual": row.get("path")},
                )
            if spec.get("notes_supplied") is True:
                check(
                    f"{request_path} notes match",
                    row.get("notes") == spec.get("requested_notes"),
                    {"expected": spec.get("requested_notes"), "actual": row.get("notes")},
                )
            elif spec.get("existing_target") is True and isinstance(spec.get("pre_state"), Mapping):
                check(
                    f"{request_path} untouched notes remain unchanged",
                    row.get("notes") == spec["pre_state"].get("notes"),
                    {"expected": spec["pre_state"].get("notes"), "actual": row.get("notes")},
                )
            for field_spec in spec.get("properties", []):
                if not isinstance(field_spec, Mapping):
                    continue
                field_name = field_spec.get("name")
                actual = _field_value(row, str(field_name))
                expected = field_spec.get("value")
                check(
                    f"{request_path}.{field_name} matches typed metadata",
                    _typed_value_equal(actual, expected, str(field_spec.get("metadata_type", ""))),
                    {"expected": expected, "actual": actual, "metadata_type": field_spec.get("metadata_type")},
                )
            for field_spec in spec.get("references", []):
                if not isinstance(field_spec, Mapping):
                    continue
                field_name = field_spec.get("name")
                actual = _reference_identity(_field_value(row, str(field_name)))
                check(
                    f"{request_path}.{field_name} reference matches",
                    _same_identity(actual, field_spec.get("target_id")),
                    {"expected": field_spec.get("target_id"), "actual": actual},
                )
            import_spec = spec.get("import")
            if isinstance(import_spec, Mapping) or isinstance(
                requested_language,
                str,
            ):
                raw_sources: list[Mapping[str, Any]] = []
                if isinstance(import_spec, Mapping):
                    raw_import_sources = import_spec.get("sources")
                    if (
                        not isinstance(raw_import_sources, list)
                        or not raw_import_sources
                        or not all(
                            isinstance(source, Mapping)
                            for source in raw_import_sources
                        )
                        or not isinstance(object_set_originals_root, str)
                    ):
                        raise OperationContractError(
                            "INVALID_PREVIEW",
                            "object.set import verification lacks sources or the sealed Originals root.",
                        )
                    raw_sources = list(raw_import_sources)

                base_read_language = _localized_import_read_language(
                    requested_language
                )
                read_languages: list[str | None] = [base_read_language]
                for raw_source in raw_sources:
                    source_language = raw_source.get("requested_language")
                    if source_language is not None and (
                        not isinstance(source_language, str)
                        or not source_language
                    ):
                        raise OperationContractError(
                            "INVALID_PREVIEW",
                            "object.set import source language is malformed.",
                        )
                    source_type = raw_source.get("requested_object_type")
                    if source_type is not None and (
                        not isinstance(source_type, str)
                        or not source_type
                    ):
                        raise OperationContractError(
                            "INVALID_PREVIEW",
                            "object.set import source object type is malformed.",
                        )
                    if source_language is not None:
                        read_language = _localized_import_read_language(
                            source_language
                        )
                        if read_language not in read_languages:
                            read_languages.append(read_language)

                grouped_candidates: dict[str | None, list[dict[str, Any]]] = {}
                for read_language in read_languages:
                    target_rows = (
                        [row]
                        if read_language == base_read_language
                        else read_object(
                            object_id=object_id,
                            fields=OBJECT_SET_IMPORT_READBACK_FIELDS,
                            language=read_language,
                            platform=platform,
                        )
                    )
                    language_rows = list(target_rows)
                    for target_row in target_rows:
                        active_source_id = _reference_identity(
                            _field_value(target_row, "activeSource")
                        )
                        if (
                            _valid_object_id(active_source_id)
                            and not _same_identity(active_source_id, object_id)
                        ):
                            language_rows.extend(
                                read_object(
                                    object_id=active_source_id,
                                    fields=OBJECT_SET_IMPORT_READBACK_FIELDS,
                                    language=read_language,
                                    platform=platform,
                                )
                            )
                    if isinstance(import_spec, Mapping):
                        descendant_args = {
                            "from": {"id": [object_id]},
                            "transform": [{"select": ["descendants"]}],
                        }
                        descendant_options = {
                            "return": list(OBJECT_SET_IMPORT_READBACK_FIELDS)
                        }
                        if read_language is not None:
                            descendant_options["language"] = read_language
                        if platform is not None:
                            descendant_options["platform"] = platform
                        descendant_result = read_call(
                            OBJECT_GET_URI,
                            descendant_args,
                            descendant_options,
                        )
                        if not isinstance(descendant_result, Mapping):
                            raise OperationContractError(
                                "INVALID_READBACK",
                                "object.set import descendant verification must return an object.",
                            )
                        readbacks.append(
                            {
                                "role": (
                                    f"{request_path}.import-descendants"
                                    f"[{read_language or 'default'}]"
                                ),
                                "uri": OBJECT_GET_URI,
                                "args": descendant_args,
                                "options": descendant_options,
                                "result": dict(descendant_result),
                            }
                        )
                        language_rows.extend(_rows(descendant_result))
                    grouped_candidates[read_language] = language_rows

                candidate_rows: list[dict[str, Any]] = []
                seen_candidate_keys: set[str] = set()
                for read_language, language_rows in grouped_candidates.items():
                    for candidate in language_rows:
                        candidate_id = candidate.get("id")
                        candidate_path = candidate.get("path")
                        reported_language = _import_language_name(
                            _field_value(candidate, "audioSource:language")
                        )
                        reported_original = _field_value(
                            candidate,
                            "originalFilePath",
                        ) or _field_value(
                            candidate,
                            "sound:originalWavFilePath",
                        )
                        candidate_key = ":".join(
                            (
                                (
                                    f"id:{_identity_key(candidate_id)}"
                                    if _valid_object_id(candidate_id)
                                    else f"path:{candidate_path}"
                                ),
                                str(
                                    reported_language
                                    or read_language
                                    or ""
                                ).casefold(),
                                str(reported_original or "").casefold(),
                            )
                        )
                        if candidate_key in seen_candidate_keys:
                            continue
                        seen_candidate_keys.add(candidate_key)
                        candidate_rows.append(candidate)

                if isinstance(requested_language, str):
                    reported_languages = [
                        name
                        for name in (
                            _import_language_name(
                                _field_value(candidate, "audioSource:language")
                            )
                            for candidate in grouped_candidates.get(
                                base_read_language,
                                [],
                            )
                        )
                        if isinstance(name, str)
                    ]
                    check(
                        f"{request_path} Sound Voice language matches exactly",
                        bool(reported_languages)
                        and set(reported_languages) == {requested_language},
                        {
                            "expected": requested_language,
                            "reported": reported_languages,
                        },
                    )

                if isinstance(import_spec, Mapping):
                    copied_candidates: list[dict[str, Any]] = []
                    for candidate_index, candidate in enumerate(candidate_rows):
                        copied_path = _field_value(
                            candidate,
                            "originalFilePath",
                        )
                        if copied_path is None:
                            copied_path = _field_value(
                                candidate,
                                "sound:originalWavFilePath",
                            )
                        if copied_path is None:
                            continue
                        try:
                            relative = _import_relative_original_path(
                                copied_path,
                                originals_root=object_set_originals_root,
                            )
                            copied_proof = import_regular_file_proof(
                                relative["copied_path"],
                                field=(
                                    f"{request_path}.import copied source "
                                    f"{candidate_index}"
                                ),
                            )
                        except (OperationContractError, ImportContractError) as exc:
                            copied_candidates.append(
                                {
                                    "candidate": candidate,
                                    "reported_path": copied_path,
                                    "error": (
                                        exc.as_dict()
                                        if hasattr(exc, "as_dict")
                                        else str(exc)
                                    ),
                                }
                            )
                            continue
                        copied_candidates.append(
                            {
                                "candidate": candidate,
                                **relative,
                                "proof": copied_proof,
                            }
                        )

                    matched_candidate_keys: set[str] = set()
                    for source_index, raw_source in enumerate(raw_sources):
                        if not isinstance(raw_source, Mapping):
                            raise OperationContractError(
                                "INVALID_PREVIEW",
                                "object.set import source proof is malformed.",
                            )
                        requested_hash = raw_source.get("sha256")
                        requested_subfolder = raw_source.get(
                            "requested_originals_subfolder"
                        )
                        requested_source_language = raw_source.get(
                            "requested_language"
                        )
                        requested_source_type = raw_source.get(
                            "requested_object_type"
                        )
                        expected_filename = raw_source.get(
                            "expected_original_filename"
                        )
                        expected_object_name = raw_source.get(
                            "expected_object_name"
                        )
                        if (
                            not isinstance(expected_filename, str)
                            or not expected_filename
                            or not isinstance(expected_object_name, str)
                            or not expected_object_name
                        ):
                            raise OperationContractError(
                                "INVALID_PREVIEW",
                                "object.set import source lacks its sealed file and object names.",
                                details={
                                    "request_path": request_path,
                                    "source_index": source_index,
                                },
                            )
                        matches = [
                            candidate
                            for candidate in copied_candidates
                            if isinstance(candidate.get("proof"), Mapping)
                            and candidate["proof"].get("sha256")
                            == requested_hash
                            and _import_path_leaf_name(
                                candidate.get("relative_path")
                            ).casefold()
                            == expected_filename.casefold()
                            and (
                                requested_subfolder is None
                                or _import_originals_subfolder_matches(
                                    candidate.get("relative_path"),
                                    requested_subfolder,
                                )
                            )
                            and (
                                requested_source_language is None
                                or _import_language_name(
                                    _field_value(
                                        candidate.get("candidate", {}),
                                        "audioSource:language",
                                    )
                                )
                                == requested_source_language
                            )
                        ]
                        matches_by_key = {
                            ":".join(
                                (
                                    (
                                        _identity_key(
                                            candidate.get(
                                                "candidate",
                                                {},
                                            ).get("id")
                                        )
                                        if isinstance(
                                            candidate.get("candidate"),
                                            Mapping,
                                        )
                                        and _valid_object_id(
                                            candidate.get(
                                                "candidate",
                                                {},
                                            ).get("id")
                                        )
                                        else ""
                                    ),
                                    str(candidate.get("copied_path")),
                                    str(
                                        _import_language_name(
                                            _field_value(
                                                candidate.get(
                                                    "candidate",
                                                    {},
                                                ),
                                                "audioSource:language",
                                            )
                                        )
                                        or ""
                                    ),
                                )
                            ): candidate
                            for candidate in matches
                            if isinstance(candidate.get("copied_path"), str)
                        }
                        unique_match_keys = set(matches_by_key)
                        media_match_ok = (
                            len(unique_match_keys) == 1
                            and not bool(
                                unique_match_keys & matched_candidate_keys
                            )
                        )
                        check(
                            (
                                f"{request_path}.import source {source_index} "
                                "was copied once with the exact hash"
                            ),
                            media_match_ok,
                            {
                                "expected_sha256": requested_hash,
                                "expected_original_filename": expected_filename,
                                "requested_originals_subfolder": requested_subfolder,
                                "requested_language": requested_source_language,
                                "requested_object_type": requested_source_type,
                                "matches": matches,
                                "all_candidates": copied_candidates,
                            },
                        )
                        matched_candidate_keys.update(unique_match_keys)
                        if not media_match_ok:
                            continue
                        matched_media = next(iter(matches_by_key.values()))
                        matched_row = matched_media.get("candidate")
                        if not isinstance(matched_row, Mapping):
                            continue
                        ancestor_chain = _import_candidate_ancestor_chain(
                            matched_row,
                            candidate_rows,
                            target_id=object_id,
                        )
                        topology_ok = ancestor_chain is not None
                        check(
                            (
                                f"{request_path}.import source {source_index} "
                                "belongs to the sealed target topology"
                            ),
                            topology_ok,
                            {
                                "target_id": object_id,
                                "matched_candidate": matched_row,
                                "ancestor_chain": ancestor_chain,
                            },
                        )
                        if ancestor_chain is None:
                            continue

                        type_ok = True
                        type_matches: list[Mapping[str, Any]] = []
                        if requested_source_type is not None:
                            type_matches = [
                                candidate
                                for candidate in ancestor_chain
                                if _object_type_token(candidate.get("type"))
                                == _object_type_token(requested_source_type)
                                and _import_created_name_matches(
                                    candidate.get("name"),
                                    expected_object_name,
                                    on_name_conflict=spec.get(
                                        "on_name_conflict",
                                        plan.get("on_name_conflict"),
                                    ),
                                )
                            ]
                            unique_type_ids = {
                                _identity_key(candidate.get("id"))
                                for candidate in type_matches
                                if _valid_object_id(candidate.get("id"))
                            }
                            type_ok = len(unique_type_ids) == 1
                            check(
                                (
                                    f"{request_path}.import source "
                                    f"{source_index} created the requested "
                                    "object type"
                                ),
                                type_ok,
                                {
                                    "requested_object_type": requested_source_type,
                                    "expected_object_name": expected_object_name,
                                    "matches": type_matches,
                                    "ancestor_chain": ancestor_chain,
                                },
                            )
                        if type_ok and ancestor_chain:
                            direct_child_id = ancestor_chain[-1].get("id")
                            if _valid_object_id(direct_child_id):
                                verified_import_direct_child_ids.setdefault(
                                    request_path,
                                    set(),
                                ).add(_identity_key(direct_child_id))

        if kind == "object-create-graph" and plan.get("on_name_conflict") == "replace":
            replaced_rows = plan.get("replaced_subtree_rows")
            if (
                not isinstance(replaced_rows, list)
                or not replaced_rows
                or not all(
                    isinstance(row, Mapping)
                    and _valid_object_id(row.get("id"))
                    and isinstance(row.get("path"), str)
                    for row in replaced_rows
                )
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "object.create replace verification lacks the complete old subtree GUID/path snapshot.",
                )
            old_ids = [row.get("id") for row in replaced_rows]
            old_identity_keys = {_identity_key(value) for value in old_ids}
            root_result = result_by_path.get(str(specs[0].get("request_path"))) if specs else None
            check(
                "replace returned a new root GUID outside the deleted subtree",
                root_result is not None and _identity_key(root_result.object) not in old_identity_keys,
                {
                    "old_ids": old_ids,
                    "new_root_id": root_result.object if root_result is not None else None,
                },
            )
            for spec in specs:
                request_path = str(spec.get("request_path"))
                result_node = result_by_path.get(request_path)
                if result_node is None or not _valid_object_id(result_node.object):
                    continue
                child_specs = [
                    row
                    for row in specs
                    if row.get("parent_request_path") == request_path
                ]
                child_results = [
                    result_by_path.get(str(row.get("request_path")))
                    for row in child_specs
                ]
                complete_expected = all(
                    row is not None and _valid_object_id(row.object)
                    for row in child_results
                )
                expected_ids = {
                    _identity_key(row.object)
                    for row in child_results
                    if row is not None and _valid_object_id(row.object)
                }
                args = {
                    "from": {"id": [result_node.object]},
                    "transform": [{"select": ["children"]}],
                }
                options = {"return": list(OBJECT_REPLACE_SNAPSHOT_FIELDS)}
                result = read_call(OBJECT_GET_URI, args, options)
                if not isinstance(result, Mapping):
                    raise OperationContractError(
                        "INVALID_READBACK",
                        "object.create replace child-set verification must return an object.",
                    )
                actual_children = _rows(result)
                readbacks.append(
                    {"uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)}
                )
                actual_ids = [
                    _identity_key(row.get("id"))
                    for row in actual_children
                    if _valid_object_id(row.get("id"))
                ]
                actual_is_closed = (
                    len(actual_ids) == len(actual_children)
                    and len(actual_ids) == len(set(actual_ids))
                )
                check(
                    f"{request_path} direct child GUID set is exactly the new reviewed topology",
                    complete_expected and actual_is_closed and set(actual_ids) == expected_ids,
                    {
                        "expected": sorted(expected_ids),
                        "actual": sorted(actual_ids),
                        "rows": actual_children,
                    },
                )
            old_options = {"return": list(OBJECT_REPLACE_SNAPSHOT_FIELDS)}
            remaining_old_rows: list[dict[str, Any]] = []
            for index, old_row in enumerate(replaced_rows):
                old_id = old_row["id"]
                old_args = {"from": {"id": [old_id]}}
                old_result = read_call(OBJECT_GET_URI, old_args, old_options)
                if not isinstance(old_result, Mapping):
                    raise OperationContractError(
                        "INVALID_READBACK",
                        "object.create replace old-subtree verification must return an object.",
                    )
                rows = _rows(old_result)
                remaining_old_rows.extend(rows)
                readbacks.append(
                    {
                        "role": f"object-create-replaced-guid-absence[{index}]",
                        "uri": OBJECT_GET_URI,
                        "args": old_args,
                        "options": old_options,
                        "expected_absent": dict(old_row),
                        "result": dict(old_result),
                    }
                )
                check(
                    f"replaced subtree GUID {index} is absent after object.create",
                    not rows,
                    {"old_row": dict(old_row), "remaining_rows": rows},
                )
            check(
                "every replaced subtree GUID is absent after object.create",
                not remaining_old_rows,
                {"old_rows": replaced_rows, "remaining_rows": remaining_old_rows},
            )
        if kind == "object-create-graph" and plan.get("on_name_conflict") == "rename":
            before_rows = plan.get("preexisting_root_rows")
            if isinstance(before_rows, list) and before_rows:
                collided_id = before_rows[0].get("id") if isinstance(before_rows[0], Mapping) else None
                root_result = result_by_path.get(str(specs[0].get("request_path"))) if specs else None
                check(
                    "rename created a different root GUID and preserved the collided object",
                    root_result is not None and not _same_identity(root_result.object, collided_id),
                    {"collided_id": collided_id, "created_id": root_result.object if root_result else None},
                )
                if collided_id is not None:
                    collided_rows = read_object(object_id=collided_id, fields=IDENTITY_RETURN_FIELDS)
                    expected_collision = dict(before_rows[0])
                    unchanged = len(collided_rows) == 1 and all(
                        (
                            _same_identity(
                                _parent_value(collided_rows[0].get(field_name)),
                                _parent_value(expected_collision.get(field_name)),
                            )
                            if field_name in {"id", "parent"}
                            else collided_rows[0].get(field_name) == expected_collision.get(field_name)
                        )
                        for field_name in IDENTITY_RETURN_FIELDS
                    )
                    check(
                        "rename collision full identity snapshot is unchanged",
                        unchanged,
                        {"expected": expected_collision, "actual": collided_rows},
                    )
        if kind == "object-set-batch":
            direct_specs_by_parent: dict[str, list[Mapping[str, Any]]] = {}
            for child_spec in specs:
                if child_spec.get("collection") not in {None, "children"}:
                    continue
                parent_path = child_spec.get("parent_request_path")
                if isinstance(parent_path, str):
                    direct_specs_by_parent.setdefault(parent_path, []).append(child_spec)
            closure_specs = [
                row
                for row in specs
                if row.get("existing_target") is True
                or row.get("preexisting_id") is not None
                or direct_specs_by_parent.get(str(row.get("request_path")))
                or isinstance(row.get("import"), Mapping)
            ]
            for parent_spec in closure_specs:
                parent_path = str(parent_spec.get("request_path"))
                parent_id = resolved_id_by_path.get(parent_path)
                if not _valid_object_id(parent_id):
                    check(
                        f"{parent_path} direct child GUID set is closed",
                        False,
                        {"error": "parent verification identity is unavailable"},
                    )
                    continue
                args = {"from": {"id": [parent_id]}, "transform": [{"select": ["children"]}]}
                options = {"return": list(IDENTITY_RETURN_FIELDS)}
                result = read_call(OBJECT_GET_URI, args, options)
                if not isinstance(result, Mapping):
                    raise OperationContractError("INVALID_READBACK", "object.set child-set verification must return an object.")
                actual_children = _rows(result)
                readbacks.append({"uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)})
                expected_ids = {
                    _identity_key(row.get("id"))
                    for row in parent_spec.get("preexisting_children", [])
                    if isinstance(row, Mapping) and _valid_object_id(row.get("id"))
                }
                complete_expected = True
                for child_spec in direct_specs_by_parent.get(parent_path, ()):
                    child_id = resolved_id_by_path.get(str(child_spec.get("request_path")))
                    if not _valid_object_id(child_id):
                        complete_expected = False
                        continue
                    expected_ids.add(_identity_key(child_id))
                expected_ids.update(
                    verified_import_direct_child_ids.get(parent_path, set())
                )
                actual_identity_keys = [
                    _identity_key(row.get("id"))
                    for row in actual_children
                    if _valid_object_id(row.get("id"))
                ]
                actual_is_closed = (
                    len(actual_identity_keys) == len(actual_children)
                    and len(actual_identity_keys) == len(set(actual_identity_keys))
                )
                actual_ids = set(actual_identity_keys)
                check(
                    f"{parent_path} direct child GUID set equals sealed pre-state plus reviewed children",
                    complete_expected and actual_is_closed and actual_ids == expected_ids,
                    {
                        "expected": sorted(expected_ids),
                        "actual": sorted(actual_ids),
                        "complete_expected": complete_expected,
                        "actual_is_closed": actual_is_closed,
                        "rows": actual_children,
                    },
                )
        list_roots_by_owner: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for list_spec in specs:
            collection = list_spec.get("collection")
            parent_path = list_spec.get("parent_request_path")
            if (
                isinstance(collection, str)
                and collection != "children"
            ):
                if kind == "object-create-graph" and parent_path is None:
                    parent_path = "$create-parent"
                if not isinstance(parent_path, str):
                    continue
                list_roots_by_owner.setdefault(
                    (parent_path, collection),
                    [],
                ).append(list_spec)
        if kind == "object-set-batch":
            for owner_spec in specs:
                if owner_spec.get("existing_target") is not True:
                    continue
                owner_path = owner_spec.get("request_path")
                snapshots = owner_spec.get("list_snapshots", [])
                if not isinstance(owner_path, str) or not isinstance(
                    snapshots,
                    list,
                ):
                    continue
                for snapshot in snapshots:
                    list_name = (
                        snapshot.get("list")
                        if isinstance(snapshot, Mapping)
                        else None
                    )
                    if isinstance(list_name, str):
                        list_roots_by_owner.setdefault(
                            (owner_path, list_name),
                            [],
                        )
        for (owner_path, list_name), list_root_specs in list_roots_by_owner.items():
            owner_id = (
                plan.get("parent_id")
                if owner_path == "$create-parent"
                else resolved_id_by_path.get(owner_path)
            )
            if not _valid_object_id(owner_id):
                check(
                    f"{owner_path}.@{list_name} has a canonical owner GUID",
                    False,
                    {"owner_id": owner_id},
                )
                continue
            owner_spec = spec_by_path.get(owner_path, {})
            if kind == "object-create-graph":
                before_rows = plan.get("list_before", [])
                list_mode = "append"
            else:
                raw_snapshots = owner_spec.get("list_snapshots", [])
                matching = [
                    row
                    for row in raw_snapshots
                    if isinstance(row, Mapping) and row.get("list") == list_name
                ] if isinstance(raw_snapshots, list) else []
                if len(matching) != 1:
                    check(
                        f"{owner_path}.@{list_name} has one sealed pre-state snapshot",
                        False,
                        {"snapshots": raw_snapshots},
                    )
                    continue
                before_rows = matching[0].get("rows", [])
                list_mode = owner_spec.get("list_mode", "append")
            if not isinstance(before_rows, list):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Object-list verification pre-state is malformed.",
                )
            expected_ids = (
                set()
                if list_mode == "replaceAll"
                else {
                    _identity_key(row.get("id"))
                    for row in before_rows
                    if isinstance(row, Mapping) and _valid_object_id(row.get("id"))
                }
            )
            complete_expected = True
            for list_root_spec in list_root_specs:
                object_id = resolved_id_by_path.get(
                    str(list_root_spec.get("request_path"))
                )
                if not _valid_object_id(object_id):
                    complete_expected = False
                    continue
                expected_ids.add(_identity_key(object_id))
            list_platform = (
                list_root_specs[0].get("platform")
                if list_root_specs
                else owner_spec.get("platform")
            )
            effective_platform = (
                list_platform
                if isinstance(list_platform, str) and list_platform
                else None
            )
            list_rows, list_readbacks = _read_object_list_rows_with_evidence(
                owner_id,
                list_name,
                fields=OBJECT_LIST_SNAPSHOT_FIELDS,
                read=read_call,
                platform=effective_platform,
                context=f"object-list-verification[{owner_path}].{list_name}",
            )
            actual_rows = _normalize_object_list_snapshot(
                list_rows,
                owner_id=owner_id,
                list_name=list_name,
            )
            readbacks.extend(list_readbacks)
            actual_ids = {_identity_key(row["id"]) for row in actual_rows}
            check(
                f"{owner_path}.@{list_name} GUID set matches the reviewed {list_mode} operation",
                complete_expected and actual_ids == expected_ids,
                {
                    "expected": sorted(expected_ids),
                    "actual": sorted(actual_ids),
                    "complete_expected": complete_expected,
                    "rows": actual_rows,
                },
            )
        if kind == "object-set-batch":
            replaced_rows = plan.get("replaced_list_subtree_rows", [])
            if not isinstance(replaced_rows, list):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Object-list replaceAll old-subtree verification is malformed.",
                )
            seen_old_ids: set[str] = set()
            for index, old_row in enumerate(replaced_rows):
                if not isinstance(old_row, Mapping) or not _valid_object_id(
                    old_row.get("id")
                ):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "Object-list replaceAll old-subtree row is malformed.",
                    )
                old_id = old_row.get("id")
                old_key = _identity_key(old_id)
                if old_key in seen_old_ids:
                    continue
                seen_old_ids.add(old_key)
                old_rows = read_object(
                    object_id=old_id,
                    fields=OBJECT_LIST_SNAPSHOT_FIELDS,
                )
                check(
                    f"replaced object-list subtree GUID {index} is absent",
                    not old_rows,
                    {"old_row": dict(old_row), "remaining_rows": old_rows},
                )
    # Compatibility for already-persisted legacy previews only. Current public
    # object.create producers emit object-create-graph.
    elif kind == "created-guid-present":
        created_id = _execution_result_id(execution_result)
        if created_id is None:
            check("execution returned created GUID", False, dict(execution_result))
            return _verification(operation, assertions, readbacks)
        rows = read_object(object_id=created_id, fields=("id", "name", "type", "path", "parent", "notes"))
        check("created GUID resolves exactly once", len(rows) == 1, rows)
        if len(rows) == 1:
            row = rows[0]
            expected = plan.get("expected", {})
            check("created GUID is stable", _same_identity(row.get("id"), created_id), {"actual": row.get("id"), "expected": created_id})
            check("created name matches", row.get("name") == expected.get("name"), {"actual": row.get("name"), "expected": expected.get("name")})
            check(
                "created parent matches",
                _same_identity(_parent_value(row.get("parent")), expected.get("parent_id")),
                {"actual": _parent_value(row.get("parent")), "expected": expected.get("parent_id")},
            )
            path = row.get("path")
            check("created path ends with name", isinstance(path, str) and path.rstrip("\\").endswith("\\" + str(expected.get("name"))), path)
            if expected.get("notes") is not None:
                check("created notes match", row.get("notes") == expected.get("notes"), {"actual": row.get("notes"), "expected": expected.get("notes")})
            assertions.append(
                {
                    "name": "created type is captured",
                    "passed": True,
                    "evidence": {
                        "requested_type": expected.get("requested_type"),
                        "reflected_type": row.get("type"),
                        "boundary": "Wwise reflection may expose a canonical base type such as PropertyContainer.",
                    },
                }
            )
    elif kind == "guid-absent":
        rows = read_object(object_id=plan.get("object_id"), fields=("id", "name", "type", "path"))
        check("deleted GUID is absent", len(rows) == 0, rows)
    elif kind in {"copied-guid-under-parent", "moved-guid-under-parent"}:
        is_copy = kind == "copied-guid-under-parent"
        object_id = _execution_result_id(execution_result)
        check(
            "execution returned copied GUID" if is_copy else "moved source GUID is known",
            object_id is not None,
            dict(execution_result),
        )
        if object_id is None:
            return _verification(operation, assertions, readbacks)
        rows = read_object(object_id=object_id, fields=("id", "name", "type", "path", "parent"))
        check("result GUID resolves exactly once", len(rows) == 1, rows)
        if len(rows) == 1:
            row = rows[0]
            check("result GUID is stable", _same_identity(row.get("id"), object_id), row.get("id"))
            if is_copy:
                check("copy GUID differs from source", not _same_identity(object_id, plan.get("source_id")), object_id)
            else:
                check("move preserves source GUID", _same_identity(object_id, plan.get("source_id")), object_id)
            result_name = row.get("name")
            conflict_policy = plan.get("on_name_conflict", "fail")
            name_matches = (
                isinstance(result_name, str) and bool(result_name)
                if conflict_policy == "rename"
                else result_name == plan.get("source_name")
            )
            check("result name satisfies conflict policy", name_matches, result_name)
            parent_matches = _same_identity(
                _parent_value(row.get("parent")), plan.get("expected_parent_id")
            )
            check("result parent matches requested parent", parent_matches, row.get("parent"))
            path = row.get("path")
            expected_parent_path = plan.get("expected_parent_path")
            path_matches = (
                isinstance(path, str)
                and isinstance(expected_parent_path, str)
                and path.startswith(expected_parent_path.rstrip("\\") + "\\")
                and isinstance(result_name, str)
                and path.rstrip("\\").endswith("\\" + result_name)
            )
            check("result path is below requested parent", path_matches, path)
        if not is_copy:
            old_path = plan.get("old_path")
            if isinstance(old_path, str) and old_path:
                old_rows = read_object(path=old_path, fields=("id", "path"))
                check(
                    "old path no longer resolves to moved GUID",
                    not any(_same_identity(row.get("id"), plan.get("source_id")) for row in old_rows),
                    old_rows,
                )
    elif kind == "same-guid-renamed":
        object_id = plan.get("object_id")
        rows = read_object(object_id=object_id, fields=("id", "name", "type", "path", "parent"))
        check("renamed GUID resolves exactly once", len(rows) == 1, rows)
        if len(rows) == 1:
            row = rows[0]
            check("renamed object keeps GUID", _same_identity(row.get("id"), object_id), row.get("id"))
            check("new name matches", row.get("name") == plan.get("expected_name"), row.get("name"))
            path = row.get("path")
            check("new path ends with name", isinstance(path, str) and path.rstrip("\\").endswith("\\" + str(plan.get("expected_name"))), path)
            check(
                "parent is unchanged",
                _same_identity(_parent_value(row.get("parent")), plan.get("old_parent")),
                {"actual": _parent_value(row.get("parent")), "expected": plan.get("old_parent")},
            )
        old_path = plan.get("old_path")
        if isinstance(old_path, str) and old_path:
            old_rows = read_object(path=old_path, fields=("id", "path"))
            check("old path no longer resolves to GUID", not any(_same_identity(row.get("id"), object_id) for row in old_rows), old_rows)
    elif kind == "same-guid-notes":
        rows = read_object(object_id=plan.get("object_id"), fields=("id", "notes", "path", "type"))
        check("notes target resolves exactly once", len(rows) == 1, rows)
        if len(rows) == 1:
            check("notes target keeps GUID", _same_identity(rows[0].get("id"), plan.get("object_id")), rows[0].get("id"))
            check("notes match exactly", rows[0].get("notes") == plan.get("expected_notes"), rows[0].get("notes"))
    elif kind == "same-guid-property":
        field_name = str(plan.get("field"))
        platform = plan.get("platform")
        rows = read_object(
            object_id=plan.get("object_id"),
            fields=("id", "path", field_name),
            platform=platform if isinstance(platform, str) else None,
        )
        check("property target resolves exactly once", len(rows) == 1, rows)
        if len(rows) == 1:
            actual = _field_value(rows[0], field_name)
            expected = plan.get("expected_value")
            check(
                "property value matches metadata type",
                _typed_value_equal(actual, expected, str(plan.get("metadata_type", ""))),
                {"actual": actual, "expected": expected, "metadata_type": plan.get("metadata_type")},
            )
    elif kind == "same-guid-reference":
        field_name = str(plan.get("field"))
        platform = plan.get("platform")
        rows = read_object(
            object_id=plan.get("object_id"),
            fields=("id", "path", field_name),
            platform=platform if isinstance(platform, str) else None,
        )
        check("reference source resolves exactly once", len(rows) == 1, rows)
        if len(rows) == 1:
            raw_actual = _field_value(rows[0], field_name)
            actual = _reference_identity(raw_actual)
            expected = plan.get("expected_target_id")
            expected_clear = plan.get("expected_clear") is True
            if expected_clear:
                check(
                    "reference is cleared",
                    _reference_value_is_null(raw_actual),
                    {"actual": raw_actual, "expected": None},
                )
            elif actual is None:
                return VerificationResult(
                    operation,
                    "indeterminate",
                    tuple(assertions),
                    tuple(readbacks),
                    "Wwise did not expose a canonical target identity for the reference readback.",
                )
            else:
                check(
                    "reference target matches",
                    _same_identity(actual, expected),
                    {"actual": actual, "expected": expected},
                )
    elif kind == "ui-capture-screen-result":
        success_status = "result_schema_checked"
        verification_strength = "result_schema_only"
        business_state_verified = False
        version = plan.get("version")
        max_chars = plan.get("max_base64_chars")
        if (
            not isinstance(version, str)
            or isinstance(max_chars, bool)
            or not isinstance(max_chars, int)
            or max_chars < 1
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "UI capture verification plan is malformed.",
            )
        check_result_schema("ak.wwise.ui.captureScreen", version)
        payload = _execution_payload(execution_result)
        content_type = payload.get("contentType")
        encoded = payload.get("contentBase64")
        check(
            "screen capture reports an image content type",
            isinstance(content_type, str) and content_type.startswith("image/"),
            {"content_type": content_type},
        )
        encoded_is_bounded = (
            isinstance(encoded, str)
            and bool(encoded)
            and len(encoded) <= max_chars
        )
        check(
            "screen capture base64 is present and bounded",
            encoded_is_bounded,
            {
                "encoded_length": len(encoded) if isinstance(encoded, str) else None,
                "limit": max_chars,
            },
        )
        decoded_length: int | None = None
        valid_base64 = False
        if encoded_is_bounded:
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                pass
            else:
                decoded_length = len(decoded)
                valid_base64 = decoded_length > 0
        check(
            "screen capture content is valid non-empty base64",
            valid_base64,
            {"decoded_length": decoded_length},
        )
    elif kind == "object-linked-state":
        version = plan.get("version")
        object_id = plan.get("object_id")
        field_name = plan.get("property")
        platform = plan.get("platform")
        expected = plan.get("expected_linked")
        if (
            not isinstance(version, str)
            or not _valid_object_id(object_id)
            or not isinstance(field_name, str)
            or not field_name
            or not isinstance(platform, str)
            or not platform
            or not isinstance(expected, bool)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Platform-link verification plan is malformed.",
            )
        check_result_schema(OBJECT_SET_LINKED_URI, version)
        result = verified_readback(
            OBJECT_IS_LINKED_URI,
            {"object": object_id, "property": field_name, "platform": platform},
            version=version,
        )
        check(
            "platform link state matches",
            result.get("linked") is expected,
            {"expected": expected, "actual": result.get("linked")},
        )
    elif kind == "object-rtpc-state":
        version = plan.get("version")
        object_id = plan.get("object_id")
        action = plan.get("action")
        property_name = plan.get("property")
        control_input_id = plan.get("control_input_id")
        expected_points = plan.get("points")
        before_rows = plan.get("before_rows")
        if (
            not isinstance(version, str)
            or not _valid_object_id(object_id)
            or action not in {"add", "update"}
            or not isinstance(property_name, str)
            or not _valid_object_id(control_input_id)
            or not isinstance(expected_points, list)
            or not isinstance(before_rows, list)
            or not all(isinstance(row, Mapping) for row in before_rows)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "RTPC verification plan is malformed.",
            )
        check_result_schema(OBJECT_SET_URI, version)
        actual_rows, rtpc_readbacks = _read_rtpc_rows_with_evidence(
            object_id,
            version=version,
            read=read_call,
        )
        readbacks.extend(rtpc_readbacks)
        before_by_id = {
            _identity_key(row.get("id")): dict(row)
            for row in before_rows
            if _valid_object_id(row.get("id"))
        }
        actual_by_id = {
            _identity_key(row.get("id")): dict(row)
            for row in actual_rows
            if _valid_object_id(row.get("id"))
        }
        check(
            "RTPC readback has unique canonical GUIDs",
            len(actual_by_id) == len(actual_rows),
            actual_rows,
        )
        matches = [
            row
            for row in actual_rows
            if row.get("@PropertyName") == property_name
            and _same_identity(
                _reference_identity(row.get("@ControlInput")),
                control_input_id,
            )
        ]
        check(
            "exactly one RTPC matches the requested property and ControlInput",
            len(matches) == 1,
            matches,
        )
        if action == "add":
            check(
                "RTPC add preserved every prior row and added exactly one GUID",
                len(actual_by_id) == len(before_by_id) + 1
                and all(actual_by_id.get(key) == row for key, row in before_by_id.items()),
                {
                    "before_ids": sorted(before_by_id),
                    "actual_ids": sorted(actual_by_id),
                },
            )
        else:
            existing_id = plan.get("existing_rtpc_id")
            existing_key = _identity_key(existing_id) if _valid_object_id(existing_id) else None
            check(
                "RTPC update retained the complete GUID set",
                existing_key is not None and set(actual_by_id) == set(before_by_id),
                {
                    "before_ids": sorted(before_by_id),
                    "actual_ids": sorted(actual_by_id),
                    "existing_id": existing_id,
                },
            )
            untouched = {
                key: row
                for key, row in before_by_id.items()
                if key != existing_key
            }
            check(
                "RTPC update left every other list row unchanged",
                all(actual_by_id.get(key) == row for key, row in untouched.items()),
                {
                    "untouched_ids": sorted(untouched),
                    "changed_ids": sorted(
                        key
                        for key, row in untouched.items()
                        if actual_by_id.get(key) != row
                    ),
                },
            )
            if len(matches) == 1:
                check(
                    "RTPC update retained the matched RTPC GUID",
                    _same_identity(matches[0].get("id"), existing_id),
                    {"expected": existing_id, "actual": matches[0].get("id")},
                )
        if len(matches) == 1:
            curve = matches[0].get("@Curve")
            actual_points = curve.get("points") if isinstance(curve, Mapping) else None
            check(
                "RTPC curve points match exactly",
                actual_points == expected_points,
                {"expected": expected_points, "actual": actual_points},
            )
            if plan.get("notes_supplied") is True:
                check(
                    "RTPC notes match exactly",
                    matches[0].get("notes") == plan.get("expected_notes"),
                    {
                        "expected": plan.get("expected_notes"),
                        "actual": matches[0].get("notes"),
                    },
                )
    elif kind == "closed-audio-import":
        source_operation = plan.get("source_operation")
        version = plan.get("version")
        uri = plan.get("uri")
        import_operation = plan.get("import_operation")
        result_contract = plan.get("result_contract")
        native_directive_boundaries = plan.get("native_directive_boundaries", [])
        expected_uri = (
            {
                "audio.import": "ak.wwise.core.audio.import",
                "audio.importTabDelimited": "ak.wwise.core.audio.importTabDelimited",
            }.get(source_operation)
            if isinstance(source_operation, str)
            else None
        )
        if (
            not isinstance(source_operation, str)
            or source_operation not in {"audio.import", "audio.importTabDelimited"}
            or operation != source_operation
            or uri != expected_uri
            or not isinstance(version, str)
            or version not in SUPPORTED_WWISE_VERSION_KEYS
            or not isinstance(import_operation, str)
            or import_operation not in {"createNew", "useExisting", "replaceExisting"}
            or plan.get("error_log_is_failure") is not True
            or not isinstance(native_directive_boundaries, list)
            or not all(
                boundary
                in {
                    "dialogue_event_result_and_target_verified_side_effect_not_fully_reconstructed",
                    "switch_assignment_result_and_target_verified_side_effect_not_fully_reconstructed",
                }
                for boundary in native_directive_boundaries
            )
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Closed audio import verification metadata is malformed or inconsistent.",
            )
        expected_result_contract = (
            "required_log_files_objects"
            if source_operation == "audio.import" and version in {"2023.1", "2024.1", "2025.1"}
            else "objects_only"
        )
        if result_contract != expected_result_contract:
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Closed audio import result contract does not match its URI and version.",
                details={
                    "source_operation": source_operation,
                    "version": version,
                    "expected": expected_result_contract,
                    "actual": result_contract,
                },
                )
        if native_directive_boundaries:
            success_status = "result_schema_checked"
            verification_strength = "operation_specific_readback_with_explicit_native_directive_boundary"
            business_state_verified = False

        check_result_schema(str(uri), str(version))
        payload = _execution_payload(execution_result)
        expected_result_keys = (
            {"log", "files", "objects"}
            if expected_result_contract == "required_log_files_objects"
            else {"objects"}
        )
        objects_value = payload.get("objects")
        object_rows = (
            [dict(row) for row in objects_value if isinstance(row, Mapping)]
            if isinstance(objects_value, list)
            else []
        )
        shape_ok = (
            set(payload) == expected_result_keys
            and isinstance(objects_value, list)
            and len(object_rows) == len(objects_value)
        )
        log_rows: list[dict[str, Any]] = []
        result_files: list[str] = []
        if expected_result_contract == "required_log_files_objects":
            log_value = payload.get("log")
            files_value = payload.get("files")
            log_rows = (
                [dict(row) for row in log_value if isinstance(row, Mapping)]
                if isinstance(log_value, list)
                else []
            )
            result_files = [item for item in files_value if isinstance(item, str)] if isinstance(files_value, list) else []
            shape_ok = (
                shape_ok
                and isinstance(log_value, list)
                and len(log_rows) == len(log_value)
                and isinstance(files_value, list)
                and len(result_files) == len(files_value)
            )
        check(
            "closed import result has the exact versioned shape",
            shape_ok,
            {
                "source_operation": source_operation,
                "version": version,
                "expected_keys": sorted(expected_result_keys),
                "actual_keys": sorted(str(key) for key in payload),
            },
        )
        if expected_result_contract == "required_log_files_objects":
            well_formed_logs = all(_audio_import_log_entry_is_well_formed(row) for row in log_rows)
            check("closed import log entries are well formed", well_formed_logs, log_rows)
            error_logs = [row for row in log_rows if _log_entry_is_error(row)]
            check("closed import log contains no error", not error_logs, error_logs)

        raw_targets = plan.get("targets")
        if (
            not isinstance(raw_targets, list)
            or not raw_targets
            or not all(isinstance(row, Mapping) for row in raw_targets)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Closed audio import verification targets are malformed or empty.",
            )
        targets = [dict(row) for row in raw_targets]
        originals_context = plan.get("originals_context")
        media_present = any(
            target.get("media_expected") is True
            or (
                target.get("media_expected") is None
                and isinstance(target.get("source_file"), Mapping)
            )
            for target in targets
        )
        if media_present:
            originals_root: str | None = _import_originals_root_from_context(
                originals_context,
                version=version,
            )
        else:
            if originals_context is not None:
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A structure-only import must not bind an Originals filesystem context.",
                )
            originals_root = None
        raw_allowed_result_paths = plan.get("allowed_result_paths")
        if (
            not isinstance(raw_allowed_result_paths, list)
            or not raw_allowed_result_paths
            or not all(isinstance(path, str) and path.startswith("\\") for path in raw_allowed_result_paths)
        ):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Closed audio import result-path allowlist is malformed or empty.",
            )
        allowed_result_paths = {path.casefold() for path in raw_allowed_result_paths}
        target_paths: list[str] = []
        expected_source_paths: list[str] = []
        expected_target_types: dict[str, str] = {}
        event_paths: list[str] = []
        event_action_fields = _IMPORT_EVENT_ACTION_FIELDS_BY_VERSION.get(version)
        event_action_types = _IMPORT_EVENT_ACTION_TYPES_BY_VERSION.get(version)
        if not isinstance(event_action_fields, tuple) or not isinstance(event_action_types, Mapping):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Closed audio import Event verification lacks a versioned readback contract.",
                details={"version": version},
            )
        for target in targets:
            target_path = target.get("canonical_target_path")
            source_proof = target.get("source_file")
            media_expected = target.get("media_expected")
            if media_expected is None:
                # Backward-compatible interpretation for sealed v1 previews
                # produced before structure-only rows were introduced.
                media_expected = isinstance(source_proof, Mapping)
            source_kind = (
                source_proof.get("kind", "regular_file")
                if isinstance(source_proof, Mapping)
                else None
            )
            pre_state_rows = target.get("pre_state_rows")
            expected_source_path = target.get(
                "expected_audio_file_source_result_path"
            )
            notes_destination = target.get("requested_notes_destination")
            if (
                not isinstance(target_path, str)
                or not target_path.startswith("\\")
                or not isinstance(media_expected, bool)
                or (
                    media_expected
                    and (
                        not isinstance(source_proof, Mapping)
                        or source_kind not in {"regular_file", "inline_base64"}
                        or not isinstance(source_proof.get("sha256"), str)
                    )
                )
                or (not media_expected and source_proof is not None)
                or not isinstance(pre_state_rows, list)
                or len(pre_state_rows) > 1
                or not all(isinstance(row, Mapping) for row in pre_state_rows)
                or any(
                    field_name in target and not isinstance(target.get(field_name), str)
                    for field_name in (
                        "requested_object_type",
                        "requested_language",
                        "requested_originals_subfolder",
                        "requested_notes",
                        "requested_audio_source_notes",
                        "requested_dialogue_event",
                        "requested_switch_assignment",
                    )
                )
                or notes_destination not in {"target_object", "audio_file_source"}
                or (
                    "requested_event" in target
                    and not isinstance(target.get("requested_event"), Mapping)
                )
                or (
                    "validated_properties" in target
                    and (
                        not isinstance(target.get("validated_properties"), list)
                        or not all(
                            isinstance(item, Mapping)
                            and isinstance(item.get("name"), str)
                            and isinstance(item.get("metadata_type"), str)
                            for item in target.get("validated_properties", [])
                        )
                    )
                )
                or (
                    "validated_references" in target
                    and (
                        not isinstance(target.get("validated_references"), list)
                        or not all(
                            isinstance(item, Mapping)
                            and isinstance(item.get("name"), str)
                            and _valid_object_id(item.get("target_id"))
                            for item in target.get("validated_references", [])
                        )
                    )
                )
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A closed audio import target oracle is malformed.",
                    details={"target": target},
                )
            if media_expected:
                source_name_path = (
                    source_proof.get("path")
                    if source_kind == "regular_file"
                    else source_proof.get("relative_path")
                )
                if not isinstance(source_name_path, str):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A closed audio import source proof lacks its filename.",
                        details={"target_path": target_path, "source_proof": source_proof},
                    )
                try:
                    derived_source_path = expected_audio_file_source_result_path(
                        target_path,
                        source_name_path,
                    )
                except ImportContractError as exc:
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A closed audio import target has an unsafe AudioFileSource result path.",
                        details=exc.as_dict(),
                    ) from exc
            else:
                derived_source_path = None
            if expected_source_path != derived_source_path:
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A closed audio import target has a drifted AudioFileSource result path.",
                    details={
                        "target_path": target_path,
                        "expected": derived_source_path,
                        "actual": expected_source_path,
                    },
                )
            explicit_source_pre_state = target.get(
                "explicit_audio_file_source_pre_state_rows"
            )
            requires_explicit_source_pre_state = (
                source_operation == "audio.import"
                and media_expected
                and bool(
                    target.get("validated_properties")
                    or target.get("validated_references")
                )
            )
            if requires_explicit_source_pre_state != (
                explicit_source_pre_state is not None
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Explicit AudioFileSource pre-state evidence does not match the dynamic media topology.",
                    details={
                        "target_path": target_path,
                        "required": requires_explicit_source_pre_state,
                        "present": explicit_source_pre_state is not None,
                    },
                )
            if explicit_source_pre_state is not None:
                if (
                    not isinstance(explicit_source_pre_state, list)
                    or len(explicit_source_pre_state) > 1
                    or not all(
                        isinstance(row, Mapping)
                        for row in explicit_source_pre_state
                    )
                ):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "An explicit AudioFileSource pre-state is not bound to one dynamic media target.",
                        details={"target_path": target_path},
                    )
                if explicit_source_pre_state:
                    explicit_source_row = explicit_source_pre_state[0]
                    if (
                        not _valid_object_id(explicit_source_row.get("id"))
                        or explicit_source_row.get("path") != expected_source_path
                        or _object_type_token(explicit_source_row.get("type"))
                        != "audiofilesource"
                    ):
                        raise OperationContractError(
                            "INVALID_PREVIEW",
                            "An explicit AudioFileSource pre-state lacks its exact path, type, or GUID.",
                            details={
                                "target_path": target_path,
                                "source_path": expected_source_path,
                                "source_pre_state": explicit_source_row,
                            },
                        )
                    if import_operation == "createNew":
                        raise OperationContractError(
                            "INVALID_PREVIEW",
                            "A closed createNew import cannot claim an existing explicit AudioFileSource.",
                            details={
                                "target_path": target_path,
                                "source_path": expected_source_path,
                            },
                        )
            target_paths.append(target_path.casefold())
            expected_target_types[target_path.casefold()] = str(
                target.get("requested_object_type", "Sound")
            )
            if isinstance(expected_source_path, str):
                expected_source_paths.append(expected_source_path.casefold())
            preexisting_id = target.get("preexisting_id")
            if pre_state_rows:
                pre_state_id = pre_state_rows[0].get("id")
                if (
                    not _valid_object_id(pre_state_id)
                    or not _valid_object_id(preexisting_id)
                    or not _same_identity(pre_state_id, preexisting_id)
                ):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A closed audio import target has inconsistent pre-state identity evidence.",
                        details={"target_path": target_path},
                    )
            elif preexisting_id is not None:
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A closed audio import target claims a pre-existing GUID without a pre-state row.",
                    details={"target_path": target_path},
                )
            if import_operation == "createNew" and pre_state_rows:
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A closed createNew import target must have been absent at preview time.",
                    details={"target_path": target_path},
                )
            expected_notes_destination = (
                "audio_file_source"
                if import_operation == "useExisting" and bool(pre_state_rows)
                else "target_object"
            )
            if notes_destination != expected_notes_destination:
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A closed audio import target has a drifted Notes destination.",
                    details={
                        "target_path": target_path,
                        "expected": expected_notes_destination,
                        "actual": notes_destination,
                    },
                )
            if (
                notes_destination == "audio_file_source"
                and "requested_notes" in target
                and "requested_audio_source_notes" in target
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "An existing useExisting target cannot bind both Notes fields to one AudioFileSource.",
                    details={"target_path": target_path},
                )
            validated_events = target.get("validated_events")
            events = (
                validated_events
                if isinstance(validated_events, list)
                else (
                    [target["requested_event"]]
                    if isinstance(target.get("requested_event"), Mapping)
                    else []
                )
            )
            event_pre_state = target.get("event_pre_state")
            if events and not isinstance(event_pre_state, list):
                event_pre_state = [
                    {
                        "path": events[0].get("path"),
                        "rows": target.get("event_pre_state_rows"),
                    }
                ]
            if not isinstance(event_pre_state, list):
                event_pre_state = []
            if len(events) != len(event_pre_state):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "Closed import Event pre-state does not match the sealed Event list.",
                    details={"target_path": target_path},
                )
            for event, pre_state in zip(events, event_pre_state, strict=True):
                if not isinstance(event, Mapping) or not isinstance(pre_state, Mapping):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A closed import Event entry is malformed.",
                    )
                event_path = event.get("path")
                event_action = event.get("action")
                event_pre_state_rows = pre_state.get("rows")
                if (
                    set(event) != {"path", "action"}
                    or not isinstance(event_path, str)
                    or not event_path.startswith("\\")
                    or not isinstance(event_action, str)
                    or event_action not in event_action_types
                    or event_pre_state_rows != []
                    or pre_state.get("path") != event_path
                ):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A closed audio import Event oracle must bind one supported action to a distinct absent Event path.",
                        details={
                            "version": version,
                            "target_path": target_path,
                            "event": dict(event),
                            "event_pre_state_rows": event_pre_state_rows,
                        },
                    )
                event_paths.append(event_path.casefold())
        if len(target_paths) != len(set(target_paths)):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Closed audio import verification target paths must be unique.",
            )
        if len(expected_source_paths) != len(set(expected_source_paths)):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Closed audio import AudioFileSource result paths must be unique.",
            )
        if any(path not in allowed_result_paths for path in expected_source_paths):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Closed audio import result-path allowlist omits a sealed AudioFileSource path.",
            )
        if len(event_paths) != len(set(event_paths)):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "Closed audio import Event paths must be unique per import row.",
            )
        returned_paths = [row.get("path") for row in object_rows]
        expected_source_path_set = set(expected_source_paths)
        unexpected_result_rows: list[dict[str, Any]] = []
        for row in object_rows:
            result_path = row.get("path")
            result_key = result_path.casefold() if isinstance(result_path, str) else None
            expected_target_type = (
                expected_target_types.get(result_key)
                if isinstance(result_key, str)
                else None
            )
            if (
                result_key is None
                or result_key not in allowed_result_paths
                or (
                    result_key in expected_source_path_set
                    and _object_type_token(row.get("type")) != "audiofilesource"
                )
                or (
                    expected_target_type is not None
                    and not _import_object_type_matches(
                        row.get("type"),
                        expected_target_type,
                    )
                )
            ):
                unexpected_result_rows.append(row)
        normalized_returned_paths = [path.casefold() for path in returned_paths if isinstance(path, str)]
        check(
            "closed import result contains only sealed targets, AudioFileSources, or missing ancestors",
            not unexpected_result_rows
            and len(normalized_returned_paths) == len(returned_paths)
            and len(normalized_returned_paths) == len(set(normalized_returned_paths)),
            {
                "allowed_paths": sorted(allowed_result_paths),
                "returned_paths": returned_paths,
                "unexpected_rows": unexpected_result_rows,
            },
        )

        for ordinal, target in enumerate(targets):
            target_path = str(target["canonical_target_path"])
            target_number = target.get("index", target.get("row_number", ordinal))
            label = f"import target {target_number}"
            source_proof = target.get("source_file")
            media_expected = target.get("media_expected")
            if media_expected is None:
                media_expected = isinstance(source_proof, Mapping)
            source_kind = (
                source_proof.get("kind", "regular_file")
                if isinstance(source_proof, Mapping)
                else None
            )
            read_language = _localized_import_read_language(
                target.get("requested_language")
            )
            if source_kind == "regular_file" and isinstance(source_proof, Mapping):
                try:
                    current_source_proof = verify_import_file_proof(
                        source_proof,
                        field=f"{label} source_file",
                    )
                except ImportContractError as exc:
                    check(f"{label} source WAV still matches its preview proof", False, exc.as_dict())
                else:
                    check(
                        f"{label} source WAV still matches its preview proof",
                        current_source_proof.get("sha256") == source_proof.get("sha256"),
                        {
                            "path": current_source_proof.get("path"),
                            "sha256": current_source_proof.get("sha256"),
                        },
                    )
            elif source_kind == "inline_base64" and isinstance(source_proof, Mapping):
                check(
                    f"{label} inline WAV proof is sealed",
                    isinstance(source_proof.get("relative_path"), str)
                    and isinstance(source_proof.get("size"), int)
                    and source_proof.get("size", 0) > 0
                    and isinstance(source_proof.get("sha256"), str)
                    and len(str(source_proof.get("sha256"))) == 64,
                    {
                        "relative_path": source_proof.get("relative_path"),
                        "size": source_proof.get("size"),
                        "sha256": source_proof.get("sha256"),
                    },
                )
            elif media_expected:
                check(
                    f"{label} has one supported source proof",
                    False,
                    {"source_proof": source_proof},
                )

            returned_matches = [
                row for row in object_rows if _same_identity(row.get("path"), target_path)
            ]
            existing_use_existing = (
                import_operation == "useExisting"
                and bool(target["pre_state_rows"])
            )
            check(
                (
                    f"{label} target result is optional but unique"
                    if existing_use_existing
                    else f"{label} is returned exactly once"
                ),
                (
                    len(returned_matches) <= 1
                    if existing_use_existing
                    else len(returned_matches) == 1
                ),
                {"target_path": target_path, "matches": returned_matches},
            )
            returned_id = returned_matches[0].get("id") if len(returned_matches) == 1 else None
            if len(returned_matches) == 1:
                check(
                    f"{label} returned path is exact",
                    returned_matches[0].get("path") == target_path,
                    {"expected": target_path, "actual": returned_matches[0].get("path")},
                )
                check(
                    f"{label} returned a canonical GUID",
                    _valid_object_id(returned_id),
                    returned_matches[0],
                )

            expected_source_path = target.get(
                "expected_audio_file_source_result_path"
            )
            explicit_source_pre_state = target.get(
                "explicit_audio_file_source_pre_state_rows"
            )
            explicit_source_preexisting_id = (
                explicit_source_pre_state[0].get("id")
                if isinstance(explicit_source_pre_state, list)
                and len(explicit_source_pre_state) == 1
                and isinstance(explicit_source_pre_state[0], Mapping)
                else None
            )
            returned_source_matches = (
                [
                    row
                    for row in object_rows
                    if _same_identity(row.get("path"), expected_source_path)
                ]
                if isinstance(expected_source_path, str)
                else []
            )
            if isinstance(expected_source_path, str):
                check(
                    (
                        f"{label} AudioFileSource is returned exactly once"
                        if existing_use_existing
                        else f"{label} AudioFileSource result is optional but unique"
                    ),
                    (
                        len(returned_source_matches) == 1
                        if existing_use_existing
                        else len(returned_source_matches) <= 1
                    ),
                    {
                        "expected_path": expected_source_path,
                        "matches": returned_source_matches,
                    },
                )
            returned_source_id = (
                returned_source_matches[0].get("id")
                if len(returned_source_matches) == 1
                else None
            )
            if len(returned_source_matches) == 1:
                returned_source = returned_source_matches[0]
                check(
                    f"{label} AudioFileSource returned path is exact",
                    returned_source.get("path") == expected_source_path,
                    {
                        "expected": expected_source_path,
                        "actual": returned_source.get("path"),
                    },
                )
                check(
                    f"{label} AudioFileSource returned a canonical GUID",
                    _valid_object_id(returned_source_id),
                    returned_source,
                )
                check(
                    f"{label} AudioFileSource returned the exact object type",
                    _object_type_token(returned_source.get("type"))
                    == "audiofilesource",
                    returned_source,
                )

            target_rows = read_object(
                path=target_path,
                fields=_import_target_return_fields(target, version=version),
                language=read_language,
            )
            check(f"{label} exact path resolves once", len(target_rows) == 1, target_rows)
            live_id: Any = None
            live_row: Mapping[str, Any] | None = target_rows[0] if len(target_rows) == 1 else None
            audio_source_row: Mapping[str, Any] | None = None
            if live_row is not None:
                live_id = live_row.get("id")
                check(f"{label} live GUID is canonical", _valid_object_id(live_id), live_row)
                check(
                    f"{label} exact live path matches",
                    live_row.get("path") == target_path,
                    {"expected": target_path, "actual": live_row.get("path")},
                )
                if returned_id is not None:
                    check(
                        f"{label} result and readback GUIDs match",
                        _same_identity(returned_id, live_id),
                        {"result": returned_id, "readback": live_id},
                    )
                expected_type = target.get("requested_object_type", "Sound")
                check(
                    f"{label} reflected type matches the request",
                    _import_object_type_matches(live_row.get("type"), expected_type),
                    {"expected": expected_type, "actual": live_row.get("type")},
                )
                for property_spec in target.get("validated_properties", []):
                    property_name = property_spec.get("name")
                    expected_value = property_spec.get("value")
                    actual_value = _field_value(live_row, f"@{property_name}")
                    check(
                        f"{label} property {property_name} matches exactly",
                        _typed_value_equal(
                            actual_value,
                            expected_value,
                            str(property_spec.get("metadata_type", "")),
                        ),
                        {
                            "property": property_name,
                            "expected": expected_value,
                            "actual": actual_value,
                            "metadata_type": property_spec.get("metadata_type"),
                        },
                    )
                for reference_spec in target.get("validated_references", []):
                    reference_name = reference_spec.get("name")
                    expected_reference = reference_spec.get("target_id")
                    actual_reference = _reference_identity(
                        _field_value(live_row, f"@{reference_name}")
                    )
                    check(
                        f"{label} reference {reference_name} matches exactly",
                        _same_identity(actual_reference, expected_reference),
                        {
                            "reference": reference_name,
                            "expected": expected_reference,
                            "actual": actual_reference,
                        },
                    )
                notes_destination = target["requested_notes_destination"]
                if (
                    "requested_notes" in target
                    and notes_destination == "target_object"
                ):
                    check(
                        f"{label} notes match exactly",
                        live_row.get("notes") == target.get("requested_notes"),
                        {"expected": target.get("requested_notes"), "actual": live_row.get("notes")},
                    )
                elif target["pre_state_rows"]:
                    before_notes = target["pre_state_rows"][0].get("notes")
                    check(
                        f"{label} untouched notes remain unchanged",
                        live_row.get("notes") == before_notes,
                        {"expected": before_notes, "actual": live_row.get("notes")},
                    )

                active_source_id = _reference_identity(
                    _field_value(live_row, "activeSource")
                )
                if version == "2021.1" and active_source_id is None:
                    active_source_id = returned_source_id
                if len(returned_source_matches) == 1:
                    returned_source = returned_source_matches[0]
                    returned_parent_id = _reference_identity(
                        returned_source.get("parent")
                    )
                    check(
                        f"{label} returned AudioFileSource parent is the live target",
                        _same_identity(returned_parent_id, live_id),
                        {
                            "expected": live_id,
                            "actual": returned_parent_id,
                            "parent": returned_source.get("parent"),
                        },
                    )
                    check(
                        f"{label} returned AudioFileSource is the active source",
                        _same_identity(returned_source_id, active_source_id),
                        {
                            "result": returned_source_id,
                            "activeSource": active_source_id,
                        },
                    )
                if active_source_id is not None:
                    source_rows = read_object(
                        object_id=active_source_id,
                        fields=_import_audio_source_return_fields(version=version),
                        language=read_language,
                    )
                    check(f"{label} active Audio Source resolves once", len(source_rows) == 1, source_rows)
                    if len(source_rows) == 1:
                        audio_source_row = source_rows[0]
                        check(
                            f"{label} active Audio Source GUID is stable",
                            _same_identity(audio_source_row.get("id"), active_source_id),
                            {"expected": active_source_id, "actual": audio_source_row.get("id")},
                        )
                        if isinstance(expected_source_path, str):
                            check(
                                f"{label} active Audio Source path matches the sealed result path",
                                audio_source_row.get("path") == expected_source_path,
                                {
                                    "expected": expected_source_path,
                                    "actual": audio_source_row.get("path"),
                                },
                            )
                elif (
                    "requested_audio_source_notes" in target
                    or (
                        "requested_notes" in target
                        and notes_destination == "audio_file_source"
                    )
                    or len(returned_source_matches) == 1
                ):
                    check(
                        f"{label} exposes an active Audio Source for notes verification",
                        False,
                        {"activeSource": _field_value(live_row, "activeSource")},
                    )

                if explicit_source_preexisting_id is not None:
                    live_source_id = (
                        audio_source_row.get("id")
                        if isinstance(audio_source_row, Mapping)
                        else None
                    )
                    if import_operation == "useExisting":
                        check(
                            f"{label} useExisting preserved the explicit AudioFileSource GUID",
                            _same_identity(
                                live_source_id,
                                explicit_source_preexisting_id,
                            )
                            and (
                                returned_source_id is None
                                or _same_identity(
                                    returned_source_id,
                                    explicit_source_preexisting_id,
                                )
                            ),
                            {
                                "expected": explicit_source_preexisting_id,
                                "readback": live_source_id,
                                "result": returned_source_id,
                            },
                        )
                    elif import_operation == "replaceExisting":
                        check(
                            f"{label} replaceExisting returned a distinct AudioFileSource GUID",
                            _valid_object_id(live_source_id)
                            and not _same_identity(
                                live_source_id,
                                explicit_source_preexisting_id,
                            ),
                            {
                                "old": explicit_source_preexisting_id,
                                "new": live_source_id,
                            },
                        )
                        old_source_rows = read_object(
                            object_id=explicit_source_preexisting_id,
                            fields=IDENTITY_RETURN_FIELDS,
                        )
                        check(
                            f"{label} replaceExisting removed the old AudioFileSource GUID",
                            len(old_source_rows) == 0,
                            old_source_rows,
                        )

                expected_audio_source_notes: Any = None
                verify_audio_source_notes = False
                if "requested_audio_source_notes" in target:
                    expected_audio_source_notes = target.get(
                        "requested_audio_source_notes"
                    )
                    verify_audio_source_notes = True
                elif (
                    "requested_notes" in target
                    and notes_destination == "audio_file_source"
                ):
                    expected_audio_source_notes = target.get("requested_notes")
                    verify_audio_source_notes = True
                if verify_audio_source_notes and audio_source_row is not None:
                    check(
                        f"{label} Audio Source notes match exactly",
                        audio_source_row.get("notes")
                        == expected_audio_source_notes,
                        {
                            "expected": expected_audio_source_notes,
                            "actual": audio_source_row.get("notes"),
                            "source_field": (
                                "audio_source_notes"
                                if "requested_audio_source_notes" in target
                                else "notes"
                            ),
                        },
                    )

                source_state = audio_source_row if audio_source_row is not None else live_row
                if "requested_language" in target:
                    language_value = _field_value(source_state, "audioSource:language")
                    if language_value is None and source_state is not live_row:
                        language_value = _field_value(live_row, "audioSource:language")
                    actual_language = _import_language_name(language_value)
                    check(
                        f"{label} language matches exactly",
                        actual_language == target.get("requested_language"),
                        {"expected": target.get("requested_language"), "actual": actual_language},
                    )

                if media_expected:
                    copied_path = _field_value(source_state, "originalFilePath")
                    if copied_path is None and source_state is not live_row:
                        copied_path = _field_value(live_row, "originalFilePath")
                    if copied_path is None:
                        copied_path = _field_value(
                            live_row,
                            "sound:originalWavFilePath",
                        )
                    derived_original: dict[str, str] | None = None
                    try:
                        derived_original = _import_relative_original_path(
                            copied_path,
                            originals_root=originals_root,
                        )
                    except OperationContractError as exc:
                        check(
                            f"{label} copied original WAV is inside the sealed Project Originals root",
                            False,
                            {
                                "reported_path": copied_path,
                                "originals_root": originals_root,
                                "error": exc.as_dict(),
                            },
                        )
                        if "requested_originals_subfolder" in target:
                            check(
                                f"{label} Originals subfolder matches",
                                False,
                                {
                                    "requested": target.get("requested_originals_subfolder"),
                                    "error": exc.as_dict(),
                                },
                            )
                        copied_path = None
                    else:
                        copied_path = derived_original["copied_path"]
                        check(
                            f"{label} copied original WAV is inside the sealed Project Originals root",
                            True,
                            derived_original,
                        )
                        if "requested_originals_subfolder" in target:
                            check(
                                f"{label} Originals subfolder matches",
                                _import_originals_subfolder_matches(
                                    derived_original["relative_path"],
                                    target.get("requested_originals_subfolder"),
                                ),
                                {
                                    "requested": target.get("requested_originals_subfolder"),
                                    "originals_root": derived_original["originals_root"],
                                    "copied_path": derived_original["copied_path"],
                                    "derived_relative_path": derived_original["relative_path"],
                                },
                            )
                    if copied_path is not None:
                        try:
                            copied_proof = import_regular_file_proof(
                                copied_path,
                                field=f"{label} original WAV",
                            )
                        except ImportContractError as exc:
                            check(
                                f"{label} copied original WAV is readable and regular",
                                False,
                                exc.as_dict(),
                            )
                        else:
                            check(
                                f"{label} copied original WAV hash matches the source",
                                copied_proof.get("sha256")
                                == source_proof.get("sha256"),
                                {
                                    "source_path": source_proof.get(
                                        "path",
                                        source_proof.get("relative_path"),
                                    ),
                                    "source_sha256": source_proof.get("sha256"),
                                    "copied_path": copied_proof.get("path"),
                                    "copied_sha256": copied_proof.get("sha256"),
                                },
                            )
                            if expected_result_contract == "required_log_files_objects":
                                file_matches: list[str] = []
                                for item in result_files:
                                    try:
                                        result_file = _import_relative_original_path(
                                            item,
                                            originals_root=originals_root,
                                        )
                                    except OperationContractError:
                                        continue
                                    if _import_file_path_key(
                                        result_file["copied_path"]
                                    ) == _import_file_path_key(
                                        copied_proof.get("path")
                                    ):
                                        file_matches.append(item)
                                check(
                                    f"{label} copied original WAV is reported exactly once",
                                    len(file_matches) == 1,
                                    {
                                        "copied_path": copied_proof.get("path"),
                                        "matches": file_matches,
                                    },
                                )

            preexisting_id = target.get("preexisting_id")
            if import_operation == "createNew":
                check(
                    f"{label} createNew produced a new GUID",
                    not target["pre_state_rows"] and _valid_object_id(live_id),
                    {"pre_state_rows": target["pre_state_rows"], "live_id": live_id},
                )
            elif import_operation == "useExisting":
                if preexisting_id is not None:
                    check(
                        f"{label} useExisting preserved the GUID",
                        _same_identity(live_id, preexisting_id),
                        {"expected": preexisting_id, "actual": live_id},
                    )
                else:
                    check(
                        f"{label} useExisting created a GUID for an absent target",
                        _valid_object_id(live_id),
                        {"live_id": live_id},
                    )
            elif preexisting_id is not None:
                check(
                    f"{label} replaceExisting returned a distinct GUID",
                    _valid_object_id(live_id) and not _same_identity(live_id, preexisting_id),
                    {"old": preexisting_id, "new": live_id},
                )
                old_rows = read_object(object_id=preexisting_id, fields=IDENTITY_RETURN_FIELDS)
                check(f"{label} replaceExisting removed the old GUID", len(old_rows) == 0, old_rows)
            else:
                check(
                    f"{label} replaceExisting created a GUID for an absent target",
                    _valid_object_id(live_id),
                    {"live_id": live_id},
                )

            events = target.get("validated_events")
            if not isinstance(events, list):
                events = (
                    [target["requested_event"]]
                    if isinstance(target.get("requested_event"), Mapping)
                    else []
                )
            for event_index, event in enumerate(events):
                if not isinstance(event, Mapping):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A closed audio import Event oracle entry is malformed.",
                    )
                event_path = event.get("path")
                if not isinstance(event_path, str) or not event_path.startswith("\\"):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A closed audio import Event oracle lacks an absolute path.",
                        details={"target_path": target_path, "event": dict(event)},
                    )
                event_rows = read_object(path=event_path, fields=IDENTITY_RETURN_FIELDS)
                event_label = (
                    f"{label} Event"
                    if len(events) == 1
                    else f"{label} Event {event_index}"
                )
                check(f"{event_label} exact path resolves once", len(event_rows) == 1, event_rows)
                if len(event_rows) == 1:
                    event_row = event_rows[0]
                    event_id = event_row.get("id")
                    check(
                        f"{event_label} path matches exactly",
                        event_row.get("path") == event_path,
                        {"expected": event_path, "actual": event_row.get("path")},
                    )
                    check(
                        f"{event_label} type is Event",
                        _object_type_token(event_row.get("type")) == "event",
                        event_row.get("type"),
                    )
                    check(f"{event_label} GUID is canonical", _valid_object_id(event_id), event_id)
                    if _valid_object_id(event_id):
                        action_rows = read_direct_children(
                            object_id=event_id,
                            fields=event_action_fields,
                        )
                        check(
                            f"{event_label} contains exactly one direct Action",
                            len(action_rows) == 1,
                            action_rows,
                        )
                        if len(action_rows) == 1:
                            action_row = action_rows[0]
                            action_id = action_row.get("id")
                            expected_action = event.get("action")
                            expected_action_type = event_action_types.get(expected_action)
                            actual_action_type = _normalize_import_event_action_type(
                                _field_value(action_row, "ActionType")
                            )
                            actual_target = _field_value(action_row, "Target")
                            check(
                                f"{event_label} child type is Action",
                                _object_type_token(action_row.get("type")) == "action",
                                action_row.get("type"),
                            )
                            check(
                                f"{event_label} Action GUID is canonical",
                                _valid_object_id(action_id),
                                action_id,
                            )
                            check(
                                f"{event_label} Action parent is the exact Event",
                                _same_identity(_reference_identity(action_row.get("parent")), event_id),
                                {
                                    "expected_event_id": event_id,
                                    "actual_parent": action_row.get("parent"),
                                },
                            )
                            check(
                                f"{event_label} Action type matches exactly",
                                actual_action_type == expected_action_type,
                                {
                                    "requested_action": expected_action,
                                    "expected_action_type": expected_action_type,
                                    "actual_action_type": actual_action_type,
                                    "raw": _field_value(action_row, "ActionType"),
                                },
                            )
                            check(
                                f"{event_label} Action target is the imported object",
                                _import_event_action_target_matches(
                                    actual_target,
                                    expected_id=live_id,
                                    expected_path=target_path,
                                ),
                                {
                                    "expected_id": live_id,
                                    "expected_path": target_path,
                                    "actual_target": actual_target,
                                },
                            )
    # Compatibility for already-persisted legacy previews only. Current public
    # audio.import and audio.importTabDelimited producers emit closed-audio-import.
    elif kind == "audio-import-created-objects":
        payload = _execution_payload(execution_result)
        objects_value = payload.get("objects")
        object_rows = [dict(row) for row in objects_value if isinstance(row, Mapping)] if isinstance(objects_value, list) else []
        version = plan.get("version")
        if version in {"2023.1", "2024.1", "2025.1"}:
            log_value = payload.get("log")
            files_value = payload.get("files")
            log_rows = [dict(row) for row in log_value if isinstance(row, Mapping)] if isinstance(log_value, list) else []
            well_formed_log_rows = all(_audio_import_log_entry_is_well_formed(row) for row in log_rows)
            shape_ok = (
                isinstance(log_value, list)
                and len(log_rows) == len(log_value)
                and all(
                    isinstance(row.get("severity"), str)
                    and isinstance(row.get("message"), str)
                    and (
                        "index" not in row
                        or (not isinstance(row.get("index"), bool) and isinstance(row.get("index"), (int, float)))
                    )
                    for row in log_rows
                )
                and isinstance(files_value, list)
                and all(isinstance(item, str) for item in files_value)
                and isinstance(objects_value, list)
                and len(object_rows) == len(objects_value)
            )
            check(
                "import result shape matches version",
                shape_ok,
                {"version": version, "keys": sorted(payload), "log": log_value, "files": files_value},
            )
            check("audio import log entries are well formed", well_formed_log_rows, log_rows)
            error_logs = [row for row in log_rows if _log_entry_is_error(row)]
            check("audio import log has no errors", not error_logs, error_logs)
        else:
            check(
                "import result shape matches version",
                isinstance(objects_value, list) and len(object_rows) == len(objects_value),
                {"version": version, "keys": sorted(payload)},
            )
        targets = plan.get("targets")
        if not isinstance(targets, list):
            raise OperationContractError("INVALID_PREVIEW", "audio.import verification targets are malformed.")
        for target in targets:
            if not isinstance(target, Mapping):
                raise OperationContractError("INVALID_PREVIEW", "audio.import verification target is malformed.")
            target_path = target.get("canonical_target_path")
            matches = [row for row in object_rows if _same_identity(row.get("path"), target_path)]
            check(
                "import target returned exactly once",
                len(matches) == 1,
                {"index": target.get("index"), "target_path": target_path, "matches": matches},
            )
            if len(matches) != 1:
                continue
            returned = matches[0]
            object_id = returned.get("id")
            check("import target returned canonical GUID", _valid_object_id(object_id), returned)
            if not _valid_object_id(object_id):
                continue
            rows = read_object(object_id=object_id, fields=("id", "name", "type", "path", "parent", "notes"))
            check("imported GUID resolves exactly once", len(rows) == 1, {"id": object_id, "rows": rows})
            if len(rows) == 1:
                row = rows[0]
                check("imported GUID remains stable", _same_identity(row.get("id"), object_id), {"expected": object_id, "actual": row.get("id")})
                check(
                    "imported path matches returned target",
                    _same_identity(row.get("path"), target_path),
                    {"expected": target_path, "actual": row.get("path")},
                )
                if target.get("requested_type") is not None:
                    check(
                        "imported type matches request",
                        row.get("type") == target.get("requested_type"),
                        {"expected": target.get("requested_type"), "actual": row.get("type")},
                    )
                if target.get("notes_supplied") is True:
                    check(
                        "imported notes match request",
                        row.get("notes") == target.get("requested_notes"),
                        {"expected": target.get("requested_notes"), "actual": row.get("notes")},
                    )
    elif kind == "soundbank-inclusions-exact":
        soundbank_id = plan.get("soundbank_id")
        args = {"soundbank": soundbank_id}
        result = read_call(SOUNDBANK_GET_INCLUSIONS_URI, args, {})
        if not isinstance(result, Mapping):
            raise OperationContractError("INVALID_READBACK", "SoundBank inclusion verification must return an object.")
        actual = _inclusion_rows(_inclusion_map(result))
        readbacks.append({"uri": SOUNDBANK_GET_INCLUSIONS_URI, "args": args, "options": {}, "result": dict(result)})
        check(
            "SoundBank inclusions match computed post-state",
            actual == plan.get("expected"),
            {"mode": plan.get("mode"), "expected": plan.get("expected"), "actual": actual},
        )
    elif kind == "switch-assignment-pair":
        container_id = plan.get("switch_container_id")
        args = {"id": container_id}
        result = read_call(SWITCHCONTAINER_GET_ASSIGNMENTS_URI, args, {})
        if not isinstance(result, Mapping):
            raise OperationContractError("INVALID_READBACK", "Switch Container assignment verification must return an object.")
        pairs = _assignment_pairs(result)
        public_pairs = _public_assignment_pairs(pairs)
        readbacks.append({"uri": SWITCHCONTAINER_GET_ASSIGNMENTS_URI, "args": args, "options": {}, "result": dict(result)})
        present = any(
            row["child_key"] == _identity_key(plan.get("child_id"))
            and row["state_key"] == _identity_key(plan.get("state_or_switch_id"))
            for row in pairs
        )
        should_exist = plan.get("should_exist") is True
        check(
            "assignment pair is present" if should_exist else "assignment pair is absent",
            present is should_exist,
            {
                "pair": {"child": plan.get("child_id"), "stateOrSwitch": plan.get("state_or_switch_id")},
                "assignments": public_pairs,
            },
        )
        check(
            "complete Switch Container assignment state matches expected post-state",
            public_pairs == plan.get("expected_assignments"),
            {"expected": plan.get("expected_assignments"), "actual": public_pairs},
        )

        container_rows = read_object(
            object_id=container_id,
            fields=("id", "type", "path", SWITCH_GROUP_REFERENCE),
        )
        check("Switch Container resolves exactly once after assignment", len(container_rows) == 1, container_rows)
        if len(container_rows) == 1:
            container_row = container_rows[0]
            actual_reference = _reference_identity(_field_value(container_row, SWITCH_GROUP_REFERENCE))
            check("Switch Container type remains valid", container_row.get("type") == "SwitchContainer", container_row.get("type"))
            check(
                "SwitchGroupOrStateGroup reference remains unchanged",
                _same_identity(actual_reference, plan.get("reference_id")),
                {"expected": plan.get("reference_id"), "actual": actual_reference},
            )

        child_rows = read_object(
            object_id=plan.get("child_id"),
            fields=("id", "type", "path", "parent"),
        )
        check("assignment child resolves exactly once after assignment", len(child_rows) == 1, child_rows)
        if len(child_rows) == 1:
            check(
                "assignment child remains directly under Switch Container",
                _same_identity(_parent_value(child_rows[0].get("parent")), container_id),
                {"expected": container_id, "actual": _parent_value(child_rows[0].get("parent"))},
            )

        group_rows = read_object(
            object_id=plan.get("reference_id"),
            fields=("id", "type", "path", "parent"),
        )
        check("Switch/State Group resolves exactly once after assignment", len(group_rows) == 1, group_rows)
        if len(group_rows) == 1:
            check(
                "Switch/State Group type remains valid",
                group_rows[0].get("type") == plan.get("group_type"),
                {"expected": plan.get("group_type"), "actual": group_rows[0].get("type")},
            )

        state_rows = read_object(
            object_id=plan.get("state_or_switch_id"),
            fields=("id", "type", "path", "parent"),
        )
        check("State/Switch resolves exactly once after assignment", len(state_rows) == 1, state_rows)
        if len(state_rows) == 1:
            check(
                "State/Switch type remains valid",
                state_rows[0].get("type") == plan.get("state_or_switch_type"),
                {"expected": plan.get("state_or_switch_type"), "actual": state_rows[0].get("type")},
            )
            check(
                "State/Switch remains directly under referenced group",
                _same_identity(_parent_value(state_rows[0].get("parent")), plan.get("reference_id")),
                {"expected": plan.get("reference_id"), "actual": _parent_value(state_rows[0].get("parent"))},
            )
    else:
        raise OperationContractError("INVALID_PREVIEW", f"Unknown verification plan kind {kind!r}.")
    return _verification(
        operation,
        assertions,
        readbacks,
        success_status=success_status,
        verification_strength=verification_strength,
        business_state_verified=business_state_verified,
    )


def _soundbank_input_file_proofs(
    plan: Mapping[str, Any],
    *,
    include_project: bool,
) -> list[Mapping[str, Any]]:
    project_context = plan.get("project_context")
    project_proof = project_context.get("project_file_proof") if isinstance(project_context, Mapping) else None
    project_seal = project_proof.get("proof_sha256") if isinstance(project_proof, Mapping) else None
    found: list[Mapping[str, Any]] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            if value.get("contract") == "waapi-skill.regular-file-proof/v1":
                seal = value.get("proof_sha256")
                if not isinstance(seal, str):
                    raise OperationContractError("INVALID_PREVIEW", "A SoundBank file proof lacks its SHA-256 seal.")
                if seal not in seen and (include_project or seal != project_seal):
                    seen.add(seal)
                    found.append(value)
                return
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(plan)
    return found


def _artifact_candidate_evidence(
    value: Any,
    before_snapshots: Sequence[Mapping[str, Any]],
    after_snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(value, str):
        return {"path": value, "after_nonempty": False, "created_or_modified": False, "error": "candidate path is not a string"}
    candidate = Path(value).resolve(strict=False)
    matches: list[tuple[int, Path, Mapping[str, Any], Mapping[str, Any]]] = []
    for index, before in enumerate(before_snapshots):
        if index >= len(after_snapshots):
            continue
        after = after_snapshots[index]
        if not isinstance(after, Mapping):
            continue
        root_value = before.get("resolved_root", before.get("root"))
        if not isinstance(root_value, str):
            continue
        root = Path(root_value).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        matches.append((len(root.parts), root, before, after))
    if not matches:
        return {
            "path": str(candidate),
            "after_nonempty": False,
            "created_or_modified": False,
            "error": "candidate is not represented by a reviewed artifact snapshot",
        }
    _, root, before, after = max(matches, key=lambda item: item[0])
    relative = candidate.relative_to(root).as_posix()

    def row(snapshot: Mapping[str, Any]) -> Mapping[str, Any] | None:
        files = snapshot.get("files")
        if not isinstance(files, list):
            return None
        for item in files:
            if isinstance(item, Mapping) and item.get("path") == relative:
                return item
        return None

    before_row = row(before)
    after_row = row(after)
    nonempty = bool(after_row and isinstance(after_row.get("size"), int) and after_row["size"] > 0)
    changed = bool(
        after_row
        and (
            before_row is None
            or before_row.get("size") != after_row.get("size")
            or before_row.get("sha256") != after_row.get("sha256")
        )
    )
    return {
        "path": str(candidate),
        "snapshot_root": str(root),
        "relative_path": relative,
        "before": None if before_row is None else dict(before_row),
        "after": None if after_row is None else dict(after_row),
        "after_nonempty": nonempty,
        "created_or_modified": changed,
    }


def _verification(
    operation: str,
    assertions: Sequence[Mapping[str, Any]],
    readbacks: Sequence[Mapping[str, Any]],
    *,
    success_status: str = "verified",
    verification_strength: str = "operation_specific_readback",
    business_state_verified: bool = True,
) -> VerificationResult:
    passed = bool(assertions) and all(item.get("passed") is True for item in assertions)
    status = success_status if passed else "verification_failed"
    if operation == "waapi.call" and business_state_verified and readbacks:
        message = (
            "The WAAPI result schema and operation-specific business-state readbacks passed."
            if passed
            else "The WAAPI result schema or an operation-specific business-state readback failed."
        )
    elif operation in {"waapi.call", "waapi.undoGroup"} and not business_state_verified:
        message = (
            "The returned WAAPI payload matches the packaged reflected result schema."
            if passed
            else "The returned WAAPI payload does not match the packaged reflected result schema."
        )
    elif readbacks:
        message = (
            "All operation-specific readbacks passed."
            if passed
            else "One or more operation-specific readbacks failed."
        )
    else:
        message = (
            "All operation-specific verification assertions passed."
            if passed
            else "One or more operation-specific verification assertions failed."
        )
    return VerificationResult(
        operation,
        status,
        tuple(assertions),
        tuple(readbacks),
        message,
        verification_strength,
        business_state_verified,
    )


def _resolve_identity(
    payload: Any,
    *,
    role: str,
    read: ReadCall,
    identity_cache: dict[bytes, ResolvedObject] | None = None,
) -> ResolvedObject:
    if not isinstance(payload, Mapping):
        raise OperationContractError("INVALID_IDENTITY", f"{role} identity must be a JSON object.")
    cache_key: bytes | None = None
    if identity_cache is not None:
        try:
            cache_key = canonical_json_bytes(dict(payload))
        except (TypeError, ValueError) as exc:
            raise OperationContractError(
                "INVALID_IDENTITY",
                f"{role} identity is not canonical JSON.",
            ) from exc
        cached = identity_cache.get(cache_key)
        if cached is not None:
            return cached
    kind = payload.get("kind")
    direct_child_parent: ResolvedObject | None = None
    direct_child_type: str | None = None
    scoped_name_parent: ResolvedObject | None = None
    if kind == "id":
        _require_exact_keys(payload, required=("kind", "value"), context=f"{role} identity")
        value = payload.get("value")
        if isinstance(value, bool) or not isinstance(value, (str, int)) or (isinstance(value, str) and not value.strip()):
            raise OperationContractError("INVALID_IDENTITY", f"{role} id value must be a non-empty string or integer.")
        identity = ObjectIdentity(id=value)
        args = {"from": {"id": [value]}}
    elif kind == "path":
        _require_exact_keys(payload, required=("kind", "value"), context=f"{role} identity")
        value = payload.get("value")
        if not isinstance(value, str) or not value.startswith("\\"):
            raise OperationContractError("INVALID_IDENTITY", f"{role} path must start with a backslash.")
        identity = ObjectIdentity(path=value)
        args = {"from": {"path": [value]}}
    elif kind == "exact-type-name":
        _validate_exact_type_name_identity_payload(payload, role=role)
        object_type = str(payload["type"])
        name = str(payload["name"])
        query = (
            f"from type {object_type} where name = "
            f"{quote_waql_literal(name)} take 2"
        )
        identity = ObjectIdentity(waql=query)
        args = {"waql": query}
    elif kind == "direct-child":
        _validate_direct_child_identity_payload(payload, role=role)
        parent_payload = payload["parent"]
        assert isinstance(parent_payload, Mapping)
        direct_child_parent = _resolve_identity(
            parent_payload,
            role=f"{role}.parent",
            read=read,
            identity_cache=identity_cache,
        )
        direct_child_type = str(payload["type"])
        parent_literal = str(parent_payload["value"])
        try:
            query = (
                f"from object {quote_waql_literal(parent_literal)} "
                f"select children where type = "
                f"{quote_waql_literal(direct_child_type)} take 2"
            )
        except ValueError as exc:
            raise OperationContractError(
                "INVALID_IDENTITY",
                f"{role} direct-child identity contains an unsupported WAQL literal.",
                details={
                    "role": role,
                    "boundary": "packaged-waql-literal-evidence",
                },
            ) from exc
        identity = ObjectIdentity(waql=query)
        args = {"waql": query}
    elif kind == "scoped-name":
        _validate_scoped_name_identity_payload(payload, role=role)
        parent_payload = payload["parent"]
        assert isinstance(parent_payload, Mapping)
        scoped_name_parent = _resolve_identity(
            parent_payload,
            role=f"{role}.parent",
            read=read,
            identity_cache=identity_cache,
        )
        name = str(payload["name"])
        object_type = str(payload["type"])
        identity = ObjectIdentity(
            name=name,
            type=object_type,
            parent=str(scoped_name_parent.object),
        )
        planned = plan_object_resolution(identity, destructive_use=True)
        args = dict(planned.readback_plan.args)  # type: ignore[union-attr]
        scoped_query = args.get("waql")
        if not isinstance(scoped_query, str) or not scoped_query:
            raise OperationContractError(
                "INVALID_IDENTITY",
                f"{role} scoped-name identity did not produce a bounded selector.",
            )
        args["waql"] = f"{scoped_query} take 2"
    else:
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} identity kind must be id, path, exact-type-name, direct-child, or scoped-name.",
            details={"kind": kind},
        )
    result = read(OBJECT_GET_URI, args, {"return": list(IDENTITY_RETURN_FIELDS)})
    rows = _rows(result)
    if len(rows) != 1:
        raise OperationContractError(
            "AMBIGUOUS_IDENTITY",
            f"{role} identity must resolve live to exactly one object.",
            details={"role": role, "identity": dict(payload), "row_count": len(rows), "rows": rows},
        )
    row = rows[0]
    object_id = row.get("id")
    if isinstance(object_id, bool) or not isinstance(object_id, (str, int)):
        raise OperationContractError("INVALID_READBACK", f"{role} live row must contain a canonical id.", details={"row": row})
    if kind == "id" and not _same_identity(object_id, payload.get("value")):
        raise OperationContractError("IDENTITY_MISMATCH", f"{role} live GUID does not match the request.", details={"row": row})
    if kind == "path" and row.get("path") != payload.get("value"):
        raise OperationContractError("IDENTITY_MISMATCH", f"{role} live path does not match the request.", details={"row": row})
    if kind == "exact-type-name" and (
        row.get("name") != payload.get("name")
        or row.get("type") != payload.get("type")
    ):
        raise OperationContractError(
            "IDENTITY_MISMATCH",
            f"{role} live name/type does not exactly match the request.",
            details={
                "expected_name": payload.get("name"),
                "expected_type": payload.get("type"),
                "actual_name": row.get("name"),
                "actual_type": row.get("type"),
                "row": row,
            },
        )
    if kind == "scoped-name":
        assert scoped_name_parent is not None
        if (
            row.get("name") != payload.get("name")
            or row.get("type") != payload.get("type")
        ):
            raise OperationContractError(
                "IDENTITY_MISMATCH",
                f"{role} live scoped name/type does not exactly match the request.",
                details={
                    "expected_name": payload.get("name"),
                    "expected_type": payload.get("type"),
                    "actual_name": row.get("name"),
                    "actual_type": row.get("type"),
                    "row": row,
                },
            )
        parent_match = _direct_child_parent_relationship_matches(
            row,
            scoped_name_parent,
        )
        if parent_match is not True:
            raise OperationContractError(
                "IDENTITY_MISMATCH",
                f"{role} live scoped object is not proven to be a direct child of the resolved parent.",
                details={
                    "expected_parent": scoped_name_parent.as_dict(),
                    "actual_parent": row.get("parent"),
                    "row": row,
                },
            )
    if kind == "direct-child":
        assert direct_child_type is not None and direct_child_parent is not None
        if row.get("type") != direct_child_type:
            raise OperationContractError(
                "IDENTITY_MISMATCH",
                f"{role} live direct child type does not exactly match the request.",
                details={
                    "expected_type": direct_child_type,
                    "actual_type": row.get("type"),
                    "row": row,
                },
            )
        parent_match = _direct_child_parent_relationship_matches(
            row,
            direct_child_parent,
        )
        if parent_match is False:
            raise OperationContractError(
                "IDENTITY_MISMATCH",
                f"{role} live object is not a direct child of the resolved parent.",
                details={
                    "expected_parent": direct_child_parent.as_dict(),
                    "actual_parent": row.get("parent"),
                    "row": row,
                },
            )
    resolved = ResolvedObject(
        identity=identity,
        object=object_id,
        resolution=f"live-{kind}",
        row=row,
    )
    if identity_cache is not None and cache_key is not None:
        identity_cache[cache_key] = resolved
    return resolved


def _mapping_sequence(value: Any, *, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise OperationContractError("INVALID_ARGUMENT", f"{field} must be a JSON array.")
    if not all(isinstance(item, Mapping) for item in value):
        raise OperationContractError("INVALID_ARGUMENT", f"Every {field} item must be a JSON object.")
    return [dict(item) for item in value]


def _validate_import_source_control_option(
    arguments: Mapping[str, Any],
    *,
    version: str,
) -> None:
    try:
        normalize_auto_check_out_to_source_control(
            arguments.get("auto_check_out_to_source_control"),
            version=version,
            supplied="auto_check_out_to_source_control" in arguments,
        )
    except ImportContractError as exc:
        raise OperationContractError(
            exc.error_code,
            str(exc),
            details=exc.details,
        ) from exc


def _validate_nested_request_shape(
    operation: str,
    arguments: Mapping[str, Any],
    *,
    version: str,
) -> None:
    if operation == "ui.commands.execute":
        request = OperationRequest(
            OPERATION_REQUEST_CONTRACT,
            version,
            operation,
            dict(arguments),
        )
        _build_ui_command_operation_plan(request, arguments=arguments)
        return
    if operation == "ui.commands.unregister":
        owned_mode = "commands" in arguments
        existing_mode = (
            "command_ids" in arguments or "acknowledgement" in arguments
        )
        if owned_mode == existing_mode:
            raise OperationContractError(
                "INVALID_ARGUMENT",
                "ui.commands.unregister requires exactly one request mode: "
                "closed command descriptors, or command_ids plus acknowledgement.",
            )
        if existing_mode:
            if set(arguments) != {"command_ids", "acknowledgement"}:
                raise OperationContractError(
                    "INVALID_ARGUMENT",
                    "Existing-ID ui.commands.unregister accepts only command_ids and acknowledgement.",
                )
            request = OperationRequest(
                OPERATION_REQUEST_CONTRACT,
                version,
                operation,
                dict(arguments),
            )
            _build_ui_command_operation_plan(request, arguments=arguments)
            return
        if set(arguments) - {"commands", "source_authority"}:
            raise OperationContractError(
                "INVALID_ARGUMENT",
                    "Descriptor-backed ui.commands.unregister accepts only commands and source_authority.",
            )
    if operation in {"ui.commands.register", "ui.commands.unregister"}:
        context_operation = operation
        raw_commands = arguments.get("commands")
        if (
            not isinstance(raw_commands, list)
            or not 1 <= len(raw_commands) <= UI_COMMAND_MAX_COMMANDS
            or not all(isinstance(item, Mapping) for item in raw_commands)
        ):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                f"{context_operation} commands must contain 1-"
                f"{UI_COMMAND_MAX_COMMANDS} JSON objects.",
            )
        for index, raw_command in enumerate(raw_commands):
            command = dict(raw_command)
            _require_exact_keys(
                command,
                required=("id", "display_name", "handler"),
                optional=(
                    "context_menu",
                    "default_shortcut",
                    "main_menu",
                ),
                context=f"{context_operation} commands[{index}]",
            )
            handler = command.get("handler")
            if not isinstance(handler, Mapping):
                raise OperationContractError(
                    "INVALID_ARGUMENT",
                    f"{context_operation} commands[{index}].handler must be a JSON object.",
                )
            kind = handler.get("kind")
            optional_by_kind = {
                "notification": (),
                "program": (
                    "argument_tokens",
                    "program_path",
                    "redirect_outputs",
                    "start_mode",
                    "working_directory",
                ),
                "lua_script": (
                    "argument_tokens",
                    "lua_module_directories",
                    "lua_script_path",
                    "lua_selected_return",
                    "start_mode",
                    "working_directory",
                ),
            }
            if kind not in optional_by_kind:
                raise OperationContractError(
                    "INVALID_ARGUMENT",
                    f"{context_operation} commands[{index}].handler.kind is unsupported.",
                    details={"kind": kind},
                )
            if kind == "lua_script" and version not in UI_COMMAND_LUA_VERSIONS:
                raise OperationContractError(
                    "UNAVAILABLE_IN_VERSION",
                    f"{context_operation} lua_script handlers are not available in Wwise {version}.",
                    details={
                        "version": version,
                        "supported_versions": sorted(UI_COMMAND_LUA_VERSIONS),
                    },
                )
            required = (
                ("kind", "program_path")
                if kind == "program"
                else (
                    ("kind", "lua_script_path")
                    if kind == "lua_script"
                    else ("kind",)
                )
            )
            _require_exact_keys(
                handler,
                required=required,
                optional=tuple(
                    field_name
                    for field_name in optional_by_kind[str(kind)]
                    if field_name not in required
                ),
                context=f"{context_operation} commands[{index}].handler",
            )
            for field_name, required, optional in (
                (
                    "context_menu",
                    (),
                    ("base_path", "enabled_for", "visible_for"),
                ),
                ("main_menu", ("base_path",), ()),
            ):
                value = command.get(field_name)
                if value is None:
                    continue
                if not isinstance(value, Mapping):
                    raise OperationContractError(
                        "INVALID_ARGUMENT",
                        f"{context_operation} commands[{index}].{field_name} must be a JSON object.",
                    )
                _require_exact_keys(
                    value,
                    required=required,
                    optional=optional,
                    context=(
                        f"{context_operation} commands[{index}].{field_name}"
                    ),
                )
        requires_source_authority = any(
            isinstance(command.get("handler"), Mapping)
            and command["handler"].get("kind") in {"program", "lua_script"}
            for command in raw_commands
        )
        authority = arguments.get("source_authority")
        if requires_source_authority and authority is None:
            raise OperationContractError(
                "SOURCE_AUTHORITY_REQUIRED",
                f"{context_operation} requires source_authority for Program or Lua handlers.",
                details={"expected": UI_COMMAND_SOURCE_AUTHORITY},
            )
        if authority is not None and authority != UI_COMMAND_SOURCE_AUTHORITY:
            raise OperationContractError(
                "INVALID_SOURCE_AUTHORITY",
                f"{context_operation} source_authority uses an unknown assertion.",
                details={"expected": UI_COMMAND_SOURCE_AUTHORITY},
            )
        return
    if operation in {"lua.executeCliFile", "lua.executeCoreFile"}:
        try:
            seal_isolated_lua_file(
                arguments.get("script_file"),
                io_root=arguments.get("io_root"),
                source_authority=arguments.get("source_authority"),
            )
            normalize_lua_wa_args(
                arguments.get("wa_args"),
                reserved_fields=(
                    CLI_LUA_RESERVED_FIELDS
                    if operation == "lua.executeCliFile"
                    else CORE_LUA_RESERVED_FIELDS
                ),
            )
        except DebugLuaContractError as exc:
            raise OperationContractError(
                exc.error_code,
                str(exc),
                details=exc.details,
            ) from exc
        if "watchdog_seconds" in arguments:
            watchdog = arguments.get("watchdog_seconds")
            if (
                operation != "lua.executeCliFile"
                or version not in {"2024.1", "2025.1"}
            ):
                raise OperationContractError(
                    "UNAVAILABLE_IN_VERSION",
                    "watchdog_seconds is available only for lua.executeCliFile in Wwise 2024.1-2025.1.",
                    details={"operation": operation, "version": version},
                )
            if isinstance(watchdog, bool) or not isinstance(watchdog, int) or watchdog < 0:
                raise OperationContractError(
                    "INVALID_ARGUMENT",
                    "watchdog_seconds must be a non-negative integer.",
                )
        return
    if operation == "lua.executeCoreInline":
        try:
            seal_inline_lua_source(
                arguments.get("lua_code"),
                io_root=arguments.get("io_root"),
                source_authority=arguments.get("source_authority"),
            )
            normalize_lua_wa_args(
                arguments.get("wa_args"),
                reserved_fields=CORE_LUA_RESERVED_FIELDS,
            )
        except DebugLuaContractError as exc:
            raise OperationContractError(
                exc.error_code,
                str(exc),
                details=exc.details,
            ) from exc
        return
    if operation in {"debug.setAsserts", "debug.setAutomationMode"}:
        if not isinstance(arguments.get("enable"), bool):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                f"{operation} enable must be a JSON boolean.",
            )
        return
    if operation in {
        "debug.restartWaapiServers",
        "debug.testAssert",
        "debug.testCrash",
    }:
        expected = {
            "debug.restartWaapiServers": "restart_waapi_servers",
            "debug.testAssert": "trigger_debug_assert",
            "debug.testCrash": "crash_wwise_process",
        }[operation]
        if arguments.get("acknowledge") != expected:
            raise OperationContractError(
                "DANGEROUS_HOST_CONTROL_ACKNOWLEDGEMENT_REQUIRED",
                f"{operation} requires its exact immutable acknowledgement.",
                details={"expected": expected, "actual": arguments.get("acknowledge")},
            )
        return
    if operation == "audio.import":
        import_items = _mapping_sequence(arguments.get("imports"), field="imports")
        scopes: list[tuple[str, Mapping[str, Any]]] = []
        defaults = arguments.get("defaults")
        if defaults is not None:
            if not isinstance(defaults, Mapping):
                raise OperationContractError(
                    "INVALID_ARGUMENT",
                    "audio.import defaults must be a JSON object.",
                )
            _require_exact_keys(
                defaults,
                required=(),
                optional=IMPORT_ITEM_OPTIONAL_FIELDS,
                context="audio.import defaults",
            )
            scopes.append(("audio.import defaults", defaults))
        for index, item in enumerate(import_items):
            _require_exact_keys(
                item,
                required=IMPORT_ITEM_REQUIRED_FIELDS,
                optional=IMPORT_ITEM_OPTIONAL_FIELDS,
                context=f"audio.import imports[{index}]",
            )
            scopes.append((f"audio.import imports[{index}]", item))
        for scope_name, item in scopes:
            event = item.get("event")
            if event is not None:
                if not isinstance(event, Mapping):
                    raise OperationContractError(
                        "INVALID_ARGUMENT",
                        f"{scope_name}.event must be a structured JSON object.",
                    )
                _require_exact_keys(
                    event,
                    required=("path",),
                    optional=("action",),
                    context=f"{scope_name}.event",
                )
            if "import_location" in item:
                _validate_identity_payload_shape(
                    item.get("import_location"),
                    role=f"{scope_name}.import_location",
                )
            references = item.get("references", [])
            if references is not None:
                if not isinstance(references, list):
                    raise OperationContractError(
                        "INVALID_ARGUMENT",
                        f"{scope_name}.references must be a JSON array.",
                    )
                for reference_index, reference in enumerate(references):
                    if not isinstance(reference, Mapping):
                        raise OperationContractError(
                            "INVALID_ARGUMENT",
                            f"{scope_name}.references[{reference_index}] must be a JSON object.",
                        )
                    _validate_identity_payload_shape(
                        reference.get("target"),
                        role=f"{scope_name}.references[{reference_index}].target",
                    )
        _validate_import_source_control_option(arguments, version=version)
        return
    if operation == "audio.importTabDelimited":
        _validate_identity_payload_shape(arguments.get("import_location"), role="import_location")
        _validate_import_source_control_option(arguments, version=version)
        return
    if operation == "ui.captureScreen":
        if "view_name" in arguments:
            _non_empty_string(arguments.get("view_name"), field="view_name")
        if "view_channel" in arguments:
            channel = arguments.get("view_channel")
            if isinstance(channel, bool) or not isinstance(channel, int) or not 1 <= channel <= 4:
                raise OperationContractError(
                    "INVALID_ARGUMENT",
                    "ui.captureScreen view_channel must be an integer from 1 through 4.",
                )
        if "rect" in arguments:
            rect = arguments.get("rect")
            if not isinstance(rect, Mapping):
                raise OperationContractError(
                    "INVALID_ARGUMENT",
                    "ui.captureScreen rect must be a JSON object.",
                )
            _require_exact_keys(
                rect,
                required=("x", "y", "width", "height"),
                context="ui.captureScreen rect",
            )
            for field_name in ("x", "y", "width", "height"):
                value = rect.get(field_name)
                minimum = 1 if field_name in {"width", "height"} else 0
                if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                    raise OperationContractError(
                        "INVALID_ARGUMENT",
                        f"ui.captureScreen rect.{field_name} must be an integer >= {minimum}.",
                    )
        return
    if operation == "object.createPlugin":
        _validate_identity_payload_shape(arguments.get("target"), role="target")
        try:
            normalize_plugin_creation(arguments.get("plugin"))
        except PluginOperationContractError as exc:
            _raise_plugin_operation_error(exc)
        return
    if operation == "object.create":
        _validate_identity_payload_shape(arguments.get("parent"), role="parent")
        conflict = arguments.get("on_name_conflict", "fail")
        if "platform" in arguments:
            _non_empty_string(arguments.get("platform"), field="platform")
        if "list" in arguments:
            try:
                normalize_object_list_name(
                    arguments.get("list"),
                    request_path="$.arguments.list",
                )
            except ObjectOperationContractError as exc:
                raise OperationContractError(
                    exc.error_code,
                    str(exc),
                    details=exc.details,
                ) from exc
            if conflict == "replace":
                raise OperationContractError(
                    "LIST_REPLACE_REQUIRES_OBJECT_SET",
                    "object.create list insertion does not expose destructive replace; use a closed object.set list with list_mode=replaceAll.",
                )
        replace_owned_root_supplied = "replace_owned_root" in arguments
        if conflict == "replace":
            if not replace_owned_root_supplied:
                raise OperationContractError(
                    "REPLACE_OWNERSHIP_REQUIRED",
                    "object.create with on_name_conflict=replace requires replace_owned_root.",
                )
            _validate_identity_payload_shape(
                arguments.get("replace_owned_root"),
                role="replace_owned_root",
            )
        elif replace_owned_root_supplied:
            raise OperationContractError(
                "REPLACE_OWNERSHIP_NOT_ALLOWED",
                "replace_owned_root is accepted only when object.create uses on_name_conflict=replace.",
                details={"on_name_conflict": conflict},
            )
        node = {
            key: arguments[key]
            for key in ("type", "name", "notes", "properties", "references", "children")
            if key in arguments
        }
        try:
            normalize_object_tree(
                node,
                on_name_conflict=conflict,
                replace_owned=replace_owned_root_supplied,
            )
        except ObjectOperationContractError as exc:
            raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
        return
    if operation == "object.delete":
        _validate_identity_payload_shape(arguments.get("object"), role="object")
        try:
            normalize_auto_check_out_to_source_control(
                arguments.get("auto_check_out_to_source_control"),
                version=version,
                supplied="auto_check_out_to_source_control" in arguments,
            )
        except ImportContractError as exc:
            raise OperationContractError(
                exc.error_code,
                str(exc),
                details=exc.details,
            ) from exc
        return
    if operation in {"object.setName", "object.setNotes"}:
        _validate_identity_payload_shape(arguments.get("object"), role="object")
        return
    if operation in {"object.setProperty", "object.setReference"}:
        _validate_identity_payload_shape(arguments.get("object"), role="object")
        if (
            operation == "object.setReference"
            and arguments.get("target") is not None
        ):
            _validate_identity_payload_shape(arguments.get("target"), role="target")
        if "platform" in arguments:
            _non_empty_string(arguments.get("platform"), field="platform")
        return
    if operation == "object.setLinked":
        _validate_identity_payload_shape(arguments.get("object"), role="object")
        _non_empty_string(arguments.get("property"), field="property")
        _non_empty_string(arguments.get("platform"), field="platform")
        if not isinstance(arguments.get("linked"), bool):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                "object.setLinked linked must be a JSON boolean.",
            )
        return
    if operation == "object.setRTPC":
        _validate_identity_payload_shape(arguments.get("object"), role="object")
        _validate_identity_payload_shape(arguments.get("control_input"), role="control_input")
        mode = arguments.get("mode", "add_or_replace")
        if mode not in {"add", "add_or_replace"}:
            raise OperationContractError(
                "INVALID_ARGUMENT",
                "object.setRTPC mode must be add or add_or_replace.",
                details={"mode": mode},
            )
        descriptor_payload = {
            "property": arguments.get("property"),
            "control_input": arguments.get("control_input"),
            "points": arguments.get("points"),
            **({"notes": arguments.get("notes")} if "notes" in arguments else {}),
        }
        try:
            normalize_rtpc_descriptors(
                [descriptor_payload],
                request_path="$.arguments.rtpcs",
                max_rtpcs=1,
            )
        except ObjectOperationContractError as exc:
            raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
        return
    if operation == "object.set":
        raw_objects = _mapping_sequence(arguments.get("objects"), field="objects")
        if not raw_objects:
            raise OperationContractError(
                "INVALID_SCOPE",
                "object.set requires at least one existing target object.",
            )
        if len(raw_objects) > 32:
            raise OperationContractError(
                "LIMIT_EXCEEDED",
                "object.set supports at most 32 existing target objects per request.",
                details={"count": len(raw_objects), "limit": 32},
            )
        conflict = arguments.get("on_name_conflict", "fail")
        list_mode = arguments.get("list_mode", "append")
        if "platform" in arguments:
            _non_empty_string(arguments.get("platform"), field="platform")
        descriptor_keys: set[bytes] = set()
        total_nodes = len(raw_objects)
        saw_list_assignment = False
        for index, item in enumerate(raw_objects):
            _require_exact_keys(
                item,
                required=("object",),
                optional=(
                    "name",
                    "notes",
                    "platform",
                    "list_mode",
                    "on_name_conflict",
                    "properties",
                    "references",
                    "import",
                    "children",
                    "lists",
                ),
                context=f"object.set objects[{index}]",
            )
            _validate_identity_payload_shape(item.get("object"), role=f"objects[{index}].object")
            if "platform" in item:
                _non_empty_string(item.get("platform"), field=f"objects[{index}].platform")
            row_conflict = item.get("on_name_conflict", conflict)
            row_list_mode = item.get("list_mode", list_mode)
            descriptor_key = canonical_json_bytes(item.get("object"))
            if descriptor_key in descriptor_keys:
                raise OperationContractError(
                    "DUPLICATE_TARGET",
                    "object.set target identity descriptors must be unique.",
                    details={"index": index, "identity": item.get("object")},
                )
            descriptor_keys.add(descriptor_key)
            if not any(
                field in item
                for field in (
                    "name",
                    "notes",
                    "properties",
                    "references",
                    "import",
                    "children",
                    "lists",
                )
            ):
                raise OperationContractError(
                    "NO_OP",
                    f"object.set objects[{index}] must request at least one field, child, or list change.",
                )
            try:
                normalize_property_descriptors(
                    item.get("properties", []),
                    request_path=f"$.objects[{index}].properties",
                )
                normalize_reference_descriptors(
                    item.get("references", []),
                    request_path=f"$.objects[{index}].references",
                )
                if "import" in item:
                    if version not in OBJECT_SET_IMPORT_VERSIONS:
                        raise OperationContractError(
                            "VERSION_BEHAVIOR_BOUNDARY",
                            "object.set import is available only in Wwise 2023.1-2025.1.",
                            details={"version": version},
                        )
                    normalize_object_import(
                        item.get("import"),
                        request_path=f"$.objects[{index}].import",
                    )
                forest = normalize_object_forest(
                    item.get("children", []),
                    on_name_conflict=row_conflict,
                    base_path=f"$.objects[{index}].children",
                    allow_platform=True,
                    allow_language=True,
                    allow_import=version in OBJECT_SET_IMPORT_VERSIONS,
                )
                total_nodes += len(forest.nodes)
                lists = normalize_object_lists(
                    item.get("lists", []),
                    request_path=f"$.objects[{index}].lists",
                    allow_platform=True,
                    allow_language=True,
                    allow_import=version in OBJECT_SET_IMPORT_VERSIONS,
                )
                saw_list_assignment = saw_list_assignment or bool(lists)
                list_nodes = sum(len(descriptor.nodes) for descriptor in lists)
                total_nodes += list_nodes
                if row_list_mode == "append" and any(
                    not descriptor.objects for descriptor in lists
                ):
                    raise OperationContractError(
                        "NO_OP",
                        f"object.set objects[{index}] append lists must contain at least one object.",
                    )
                if (
                    item.get("list_mode") == "replaceAll"
                    and not lists
                ):
                    raise OperationContractError(
                        "NO_OP",
                        f"object.set objects[{index}] list_mode=replaceAll requires one closed lists[] assignment.",
                    )
            except ObjectOperationContractError as exc:
                raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
        if list_mode == "replaceAll" and not saw_list_assignment:
            raise OperationContractError(
                "NO_OP",
                "object.set list_mode=replaceAll requires at least one closed lists[] assignment.",
            )
        if total_nodes > DEFAULT_MAX_NODES:
            raise OperationContractError(
                "NODE_LIMIT_EXCEEDED",
                "object.set target and child nodes exceed the single bounded result budget.",
                details={"count": total_nodes, "limit": DEFAULT_MAX_NODES},
            )
        return
    if operation == "soundbank.generate":
        soundbanks = _mapping_sequence(arguments.get("soundbanks"), field="soundbanks")
        artifact_expectations: list[str] = []
        for bank_index, bank in enumerate(soundbanks):
            _require_exact_keys(
                bank,
                required=("name", "artifact_expectation"),
                optional=("events", "aux_busses", "inclusions", "rebuild"),
                context=f"soundbank.generate soundbanks[{bank_index}]",
            )
            artifact_expectation = bank.get("artifact_expectation")
            if artifact_expectation not in {
                "nonlocalized",
                "localized",
                "mixed",
            }:
                raise OperationContractError(
                    "INVALID_ARGUMENT",
                    "soundbank.generate soundbanks[] artifact_expectation must "
                    "be nonlocalized, localized, or mixed.",
                    details={
                        "index": bank_index,
                        "actual": artifact_expectation,
                    },
                )
            artifact_expectations.append(str(artifact_expectation))
            for field_name in ("events", "aux_busses"):
                if field_name not in bank:
                    continue
                values = bank.get(field_name)
                if not isinstance(values, list) or not values:
                    raise OperationContractError(
                        "INVALID_ARGUMENT",
                        f"soundbanks[{bank_index}].{field_name} must be a non-empty JSON array.",
                    )
                for value_index, value in enumerate(values):
                    _validate_identity_payload_shape(
                        value,
                        role=f"soundbanks[{bank_index}].{field_name}[{value_index}]",
                    )
        skip_languages = arguments.get("skip_languages")
        if not isinstance(skip_languages, bool):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                "soundbank.generate skip_languages must be a boolean.",
            )
        language_dependent = any(
            expectation in {"localized", "mixed"}
            for expectation in artifact_expectations
        )
        if not language_dependent:
            if skip_languages is not True or "languages" in arguments:
                raise OperationContractError(
                    "INVALID_SCOPE",
                    "An all-nonlocalized SoundBank batch requires "
                    "skip_languages=true and languages omitted.",
                )
            return
        if skip_languages is not False:
            raise OperationContractError(
                "INVALID_SCOPE",
                "A SoundBank batch containing any localized or mixed row "
                "requires skip_languages=false.",
            )
        languages = arguments.get("languages")
        if (
            not isinstance(languages, list)
            or not languages
            or not all(
                isinstance(language, str) and bool(language.strip())
                for language in languages
            )
        ):
            raise OperationContractError(
                "INVALID_SCOPE",
                "A SoundBank batch containing any localized or mixed row "
                "requires a non-empty languages array of localized project "
                "language names.",
            )
        if any(language.strip().casefold() == "sfx" for language in languages):
            raise OperationContractError(
                "INVALID_SCOPE",
                "SFX is not a localized project language and cannot appear in "
                "soundbank.generate languages.",
            )
        return
    if operation == "soundbank.convertExternalSources":
        for index, row in enumerate(_mapping_sequence(arguments.get("sources"), field="sources")):
            _require_exact_keys(
                row,
                required=("input", "platform", "output"),
                context=f"soundbank.convertExternalSources sources[{index}]",
            )
        return
    if operation == "soundbank.processDefinitionFiles":
        files = arguments.get("files")
        if not isinstance(files, list) or not files or not all(isinstance(item, str) for item in files):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                "soundbank.processDefinitionFiles files must be a non-empty JSON string array.",
            )
        return
    if operation == "soundbank.setInclusions":
        _validate_identity_payload_shape(arguments.get("soundbank"), role="soundbank")
        for index, item in enumerate(_mapping_sequence(arguments.get("inclusions"), field="inclusions")):
            _require_exact_keys(item, required=("object", "filters"), context=f"inclusions[{index}]")
            _validate_identity_payload_shape(item.get("object"), role=f"inclusions[{index}].object")
        return
    if operation in {"switchContainer.addAssignment", "switchContainer.removeAssignment"}:
        for field_name in ("switch_container", "child", "state_or_switch"):
            _validate_identity_payload_shape(arguments.get(field_name), role=field_name)
        return


def _validate_identity_payload_shape(payload: Any, *, role: str) -> None:
    if not isinstance(payload, Mapping):
        raise OperationContractError("INVALID_IDENTITY", f"{role} identity must be a JSON object.")
    kind = payload.get("kind")
    if kind in {"id", "path"}:
        _require_exact_keys(payload, required=("kind", "value"), context=f"{role} identity")
        return
    if kind == "exact-type-name":
        _validate_exact_type_name_identity_payload(payload, role=role)
        return
    if kind == "direct-child":
        _validate_direct_child_identity_payload(payload, role=role)
        return
    if kind == "scoped-name":
        _validate_scoped_name_identity_payload(payload, role=role)
        return
    raise OperationContractError(
        "INVALID_IDENTITY",
        f"{role} identity kind must be id, path, exact-type-name, direct-child, or scoped-name.",
        details={"kind": kind},
    )


def _validate_exact_type_name_identity_payload(
    payload: Mapping[str, Any],
    *,
    role: str,
) -> None:
    _require_exact_keys(
        payload,
        required=("kind", "type", "name"),
        context=f"{role} identity",
    )
    object_type = payload.get("type")
    if (
        not isinstance(object_type, str)
        or not object_type
        or object_type != object_type.strip()
        or len(object_type) > DIRECT_CHILD_MAX_TYPE_LENGTH
        or _EXACT_TYPE_NAME_TYPE_TOKEN.fullmatch(object_type) is None
    ):
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} exact-type-name type must be one bounded Wwise type token.",
            details={
                "role": role,
                "limit": DIRECT_CHILD_MAX_TYPE_LENGTH,
                "accepted": _EXACT_TYPE_NAME_TYPE_TOKEN.pattern,
            },
        )
    name = payload.get("name")
    if (
        not isinstance(name, str)
        or not name
        or name != name.strip()
        or len(name) > EXACT_TYPE_NAME_MAX_NAME_LENGTH
        or "\\" in name
    ):
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} exact-type-name name must be one bounded exact object name.",
            details={
                "role": role,
                "limit": EXACT_TYPE_NAME_MAX_NAME_LENGTH,
            },
        )
    try:
        quote_waql_literal(name)
    except ValueError as exc:
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} exact-type-name name is outside the packaged WAQL literal boundary.",
            details={
                "role": role,
                "boundary": "packaged-waql-literal-evidence",
            },
        ) from exc


def _validate_scoped_name_identity_payload(
    payload: Mapping[str, Any],
    *,
    role: str,
) -> None:
    _require_exact_keys(
        payload,
        required=("kind", "name", "type", "parent"),
        context=f"{role} identity",
    )
    object_type = payload.get("type")
    if (
        not isinstance(object_type, str)
        or not object_type
        or object_type != object_type.strip()
        or len(object_type) > DIRECT_CHILD_MAX_TYPE_LENGTH
        or _EXACT_TYPE_NAME_TYPE_TOKEN.fullmatch(object_type) is None
    ):
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} scoped-name type must be one bounded Wwise type token.",
            details={
                "role": role,
                "limit": DIRECT_CHILD_MAX_TYPE_LENGTH,
                "accepted": _EXACT_TYPE_NAME_TYPE_TOKEN.pattern,
            },
        )
    name = payload.get("name")
    if (
        not isinstance(name, str)
        or not name
        or name != name.strip()
        or len(name) > EXACT_TYPE_NAME_MAX_NAME_LENGTH
        or "\\" in name
    ):
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} scoped-name name must be one bounded exact object name.",
            details={
                "role": role,
                "limit": EXACT_TYPE_NAME_MAX_NAME_LENGTH,
            },
        )
    parent = payload.get("parent")
    if not isinstance(parent, Mapping) or parent.get("kind") not in {"id", "path"}:
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} scoped-name parent must be an id or path identity.",
        )
    _require_exact_keys(
        parent,
        required=("kind", "value"),
        context=f"{role}.parent identity",
    )
    parent_value = parent.get("value")
    if parent.get("kind") == "id":
        if (
            isinstance(parent_value, bool)
            or not isinstance(parent_value, (str, int))
            or (
                isinstance(parent_value, str)
                and (
                    not parent_value.strip()
                    or len(parent_value) > DIRECT_CHILD_MAX_PARENT_LITERAL_LENGTH
                )
            )
        ):
            raise OperationContractError(
                "INVALID_IDENTITY",
                f"{role} scoped-name parent id must be a bounded non-empty string or integer.",
                details={"limit": DIRECT_CHILD_MAX_PARENT_LITERAL_LENGTH},
            )
    elif (
        not isinstance(parent_value, str)
        or not parent_value.startswith("\\")
        or len(parent_value) > DIRECT_CHILD_MAX_PARENT_LITERAL_LENGTH
    ):
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} scoped-name parent path must be a bounded absolute Wwise path.",
            details={"limit": DIRECT_CHILD_MAX_PARENT_LITERAL_LENGTH},
        )
    try:
        quote_waql_literal(name)
        quote_waql_literal(str(parent_value))
    except ValueError as exc:
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} scoped-name identity contains an unsupported WAQL literal.",
            details={
                "role": role,
                "boundary": "packaged-waql-literal-evidence",
            },
        ) from exc


def _validate_direct_child_identity_payload(
    payload: Mapping[str, Any],
    *,
    role: str,
) -> None:
    _require_exact_keys(
        payload,
        required=("kind", "parent", "type"),
        context=f"{role} identity",
    )
    parent = payload.get("parent")
    if not isinstance(parent, Mapping) or parent.get("kind") not in {"id", "path"}:
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} direct-child parent must be an id or path identity.",
        )
    _require_exact_keys(
        parent,
        required=("kind", "value"),
        context=f"{role}.parent identity",
    )
    parent_value = parent.get("value")
    if parent.get("kind") == "id":
        if (
            isinstance(parent_value, bool)
            or not isinstance(parent_value, (str, int))
            or (
                isinstance(parent_value, str)
                and (
                    not parent_value.strip()
                    or len(parent_value) > DIRECT_CHILD_MAX_PARENT_LITERAL_LENGTH
                )
            )
        ):
            raise OperationContractError(
                "INVALID_IDENTITY",
                f"{role} direct-child parent id must be a bounded non-empty string or integer.",
                details={
                    "limit": DIRECT_CHILD_MAX_PARENT_LITERAL_LENGTH,
                },
            )
    else:
        if (
            not isinstance(parent_value, str)
            or not parent_value.startswith("\\")
            or len(parent_value) > DIRECT_CHILD_MAX_PARENT_LITERAL_LENGTH
        ):
            raise OperationContractError(
                "INVALID_IDENTITY",
                f"{role} direct-child parent path must be a bounded absolute Wwise path.",
                details={
                    "limit": DIRECT_CHILD_MAX_PARENT_LITERAL_LENGTH,
                },
            )
    object_type = payload.get("type")
    if (
        not isinstance(object_type, str)
        or not object_type
        or object_type != object_type.strip()
        or len(object_type) > DIRECT_CHILD_MAX_TYPE_LENGTH
    ):
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} direct-child type must be one bounded exact Wwise type token.",
            details={"limit": DIRECT_CHILD_MAX_TYPE_LENGTH},
        )
    try:
        quote_waql_literal(str(parent_value))
        quote_waql_literal(object_type)
    except ValueError as exc:
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} direct-child identity contains an unsupported WAQL literal.",
            details={
                "role": role,
                "boundary": "packaged-waql-literal-evidence",
            },
        ) from exc


def _canonical_import_target_paths(object_path: str, *, version: str) -> tuple[str, str]:
    if not object_path.startswith("\\") or object_path.endswith("\\"):
        raise OperationContractError(
            "INVALID_ARGUMENT",
            "audio.import object_path must be an absolute Wwise object path with a final object name.",
            details={"object_path": object_path},
        )
    raw_segments = object_path[1:].split("\\")
    if len(raw_segments) < 3 or any(not segment or segment in {".", ".."} for segment in raw_segments):
        raise OperationContractError(
            "INVALID_ARGUMENT",
            "audio.import object_path must name a direct target below a live writable parent.",
            details={"object_path": object_path},
        )
    canonical_segments: list[str] = []
    for segment in raw_segments:
        if segment.startswith("<"):
            match = _TYPED_PATH_SEGMENT.fullmatch(segment)
            if match is None or not match.group(1).strip():
                raise OperationContractError(
                    "INVALID_ARGUMENT",
                    "Typed Wwise path segments must use <Type>Name.",
                    details={"object_path": object_path, "segment": segment},
                )
            canonical_segments.append(match.group(1))
        else:
            canonical_segments.append(segment)
    if any(not segment or segment in {".", ".."} for segment in canonical_segments):
        raise OperationContractError(
            "INVALID_ARGUMENT",
            "Typed Wwise path segments must not normalize to empty, dot, or dot-dot names.",
            details={"object_path": object_path, "canonical_segments": canonical_segments},
        )
    try:
        allowed_roots = allowed_import_hierarchy_roots(version)
    except ImportContractError as exc:
        raise OperationContractError(
            exc.error_code,
            str(exc),
            details=exc.details,
        ) from exc
    if canonical_segments[0] not in allowed_roots:
        raise OperationContractError(
            "INVALID_TARGET",
            f"The closed audio.import operation does not allow {canonical_segments[0]!r} in Wwise {version}.",
            details={
                "version": version,
                "management_root": canonical_segments[0],
                "allowed_roots": list(allowed_roots),
            },
        )
    target_path = "\\" + "\\".join(canonical_segments)
    parent_path = "\\" + "\\".join(canonical_segments[:-1])
    return target_path, parent_path


def _require_import_parent(
    parent: ResolvedObject,
    *,
    index: int,
    version: str,
) -> None:
    parent_type = parent.row.get("type")
    parent_path = parent.row.get("path")
    allowed_types = (
        IMPORT_WRITABLE_PARENT_TYPES
        | IMPORT_REFLECTED_WRITABLE_PARENT_TYPES_BY_VERSION.get(
            version,
            frozenset(),
        )
    )
    if parent_type not in allowed_types or not isinstance(parent_path, str):
        raise OperationContractError(
            "INVALID_TARGET_TYPE",
            "audio.import requires a live writable audio hierarchy parent container.",
            details={
                "index": index,
                "version": version,
                "allowed_types": sorted(allowed_types),
                "parent": parent.as_dict(),
            },
        )


def _regular_file_proof(value: Any, *, field: str) -> dict[str, Any]:
    path_text = _non_empty_string(value, field=field)
    path = Path(path_text)
    if not path.is_absolute():
        raise OperationContractError("INVALID_FILE", f"{field} must be an absolute path.", details={"path": path_text})
    try:
        path_lstat = path.lstat()
    except OSError as exc:
        raise OperationContractError("INVALID_FILE", f"{field} is not accessible.", details={"path": path_text, "error": str(exc)}) from exc
    if not stat.S_ISREG(path_lstat.st_mode):
        raise OperationContractError(
            "INVALID_FILE",
            f"{field} must identify a regular file, not a directory, device, or symbolic link.",
            details={"path": path_text},
        )
    try:
        canonical = path.resolve(strict=True)
    except OSError as exc:
        raise OperationContractError("INVALID_FILE", f"{field} could not be resolved.", details={"path": path_text, "error": str(exc)}) from exc
    digest = hashlib.sha256()
    try:
        with canonical.open("rb") as handle:
            before = stat_result = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise OperationContractError("INVALID_FILE", f"{field} must identify a regular file.", details={"path": str(canonical)})
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    except OperationContractError:
        raise
    except OSError as exc:
        raise OperationContractError("INVALID_FILE", f"{field} could not be hashed.", details={"path": str(canonical), "error": str(exc)}) from exc
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise OperationContractError("FILE_CHANGED", f"{field} changed while its preview proof was being captured.", details={"path": str(canonical)})
    return {"path": str(canonical), "size": stat_result.st_size, "sha256": digest.hexdigest()}


def _closed_inclusion_filters(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise OperationContractError("INVALID_ARGUMENT", f"{field} must be a non-empty JSON array.")
    if not all(isinstance(item, str) and item in INCLUSION_FILTERS for item in value):
        raise OperationContractError(
            "INVALID_ARGUMENT",
            f"{field} accepts only events, structures, and media.",
            details={"filters": value, "supported": sorted(INCLUSION_FILTERS)},
        )
    if len(set(value)) != len(value):
        raise OperationContractError("INVALID_ARGUMENT", f"{field} must not contain duplicates.", details={"filters": value})
    return sorted(value)


def _identity_key(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or value == "":
        raise OperationContractError("INVALID_READBACK", "A canonical object identity is required.", details={"value": value})
    return str(value).casefold()


def _inclusion_map(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values = result.get("inclusions")
    if not isinstance(values, list) or not all(isinstance(item, Mapping) for item in values):
        raise OperationContractError(
            "INVALID_READBACK",
            "getInclusions result must contain an inclusions array of objects.",
            details={"result": dict(result)},
        )
    normalized: dict[str, dict[str, Any]] = {}
    for index, row_value in enumerate(values):
        row = dict(row_value)
        object_id = _reference_identity(row.get("object"))
        key = _identity_key(object_id)
        filters = _closed_inclusion_filters(row.get("filter"), field=f"getInclusions.inclusions[{index}].filter")
        entry = normalized.setdefault(key, {"object": object_id, "filters": set()})
        entry["filters"].update(filters)
    return normalized


def _apply_inclusion_mode(
    before: Mapping[str, Mapping[str, Any]],
    requested: Mapping[str, Mapping[str, Any]],
    *,
    mode: str,
) -> dict[str, dict[str, Any]]:
    if mode == "replace":
        return {
            key: {"object": value.get("object"), "filters": set(value.get("filters", ()))}
            for key, value in requested.items()
        }
    result = {
        key: {"object": value.get("object"), "filters": set(value.get("filters", ()))}
        for key, value in before.items()
    }
    for key, value in requested.items():
        filters = set(value.get("filters", ()))
        if mode == "add":
            result[key] = {"object": value.get("object"), "filters": filters}
        else:
            result.pop(key, None)
    return result


def _inclusion_rows(values: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"object": key, "filters": sorted(str(item) for item in value.get("filters", ()))}
        for key, value in sorted(values.items())
    ]


def _assignment_pairs(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = result.get("return")
    if not isinstance(values, list) or not all(isinstance(item, Mapping) for item in values):
        raise OperationContractError(
            "INVALID_READBACK",
            "getAssignments runtime result must contain a return array of assignment rows.",
            details={"result": dict(result)},
        )
    pairs: list[dict[str, Any]] = []
    for index, row_value in enumerate(values):
        row = dict(row_value)
        child = _reference_identity(row.get("child"))
        state_or_switch = _reference_identity(row.get("stateOrSwitch"))
        if child is None or state_or_switch is None:
            raise OperationContractError(
                "INVALID_READBACK",
                "getAssignments rows must expose canonical child and stateOrSwitch identities.",
                details={"index": index, "row": row},
            )
        pairs.append(
            {
                "child": child,
                "stateOrSwitch": state_or_switch,
                "child_key": _identity_key(child),
                "state_key": _identity_key(state_or_switch),
            }
        )
    return pairs


def _public_assignment_pairs(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {"child": str(value.get("child_key")), "stateOrSwitch": str(value.get("state_key"))}
        for value in values
    ]
    return sorted(rows, key=lambda row: (row["child"], row["stateOrSwitch"]))


def _execution_payload(result: Mapping[str, Any]) -> Mapping[str, Any]:
    current: Mapping[str, Any] = result
    for _ in range(3):
        nested = current.get("result")
        if isinstance(nested, Mapping):
            current = nested
            continue
        break
    return current


def _log_entry_is_error(row: Mapping[str, Any]) -> bool:
    severity = row.get("severity")
    return isinstance(severity, str) and ("error" in severity.casefold() or "fatal" in severity.casefold())


def _audio_import_log_entry_is_well_formed(row: Mapping[str, Any]) -> bool:
    severity = row.get("severity")
    message = row.get("message")
    index = row.get("index")
    recognized = {"normal", "message", "warning", "error", "fatal", "fatal error"}
    return (
        isinstance(severity, str)
        and severity.casefold() in recognized
        and isinstance(message, str)
        and (index is None or (not isinstance(index, bool) and isinstance(index, (int, float))))
    )


def _import_object_type_matches(actual: Any, requested: Any) -> bool:
    actual_token = _object_type_token(actual)
    requested_token = _object_type_token(requested)
    aliases: Mapping[str, frozenset[str]] = {
        "actormixer": frozenset({"actormixer", "propertycontainer"}),
        "propertycontainer": frozenset({"actormixer", "propertycontainer"}),
        "blendcontainer": frozenset({"blendcontainer"}),
        "folder": frozenset({"folder"}),
        "musicplaylistcontainer": frozenset({"musicranseqcntr", "musicplaylistcontainer"}),
        "musicranseqcntr": frozenset({"musicranseqcntr", "musicplaylistcontainer"}),
        "musicsegment": frozenset({"musicsegment"}),
        "musicswitchcontainer": frozenset({"musicswitchcontainer"}),
        "musictrack": frozenset({"musictrack"}),
        "randomcontainer": frozenset({"randomsequencecontainer"}),
        "sequencecontainer": frozenset({"randomsequencecontainer"}),
        "randomsequencecontainer": frozenset({"randomsequencecontainer"}),
        "sound": frozenset({"sound"}),
        "soundsfx": frozenset({"sound"}),
        "soundvoice": frozenset({"sound"}),
        "switchcontainer": frozenset({"switchcontainer"}),
        "virtualfolder": frozenset({"folder", "virtualfolder"}),
    }
    return actual_token in aliases.get(requested_token, frozenset({requested_token}))


def _import_language_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("name", "displayName", "shortName"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
    return None


def _import_path_segments(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    try:
        relative = parse_relative_host_path(value)
    except HostPathError:
        return []
    return [segment.casefold() for segment in relative.components]


def _import_path_leaf_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        absolute = parse_absolute_host_path(value)
    except HostPathError:
        try:
            relative = parse_relative_host_path(value)
        except HostPathError:
            return ""
        return relative.pure_path.name
    return absolute.pure_path.name


def _import_candidate_ancestor_chain(
    candidate: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    target_id: Any,
) -> list[Mapping[str, Any]] | None:
    """Return the source-to-direct-child chain below one import target.

    ``[]`` means the copied-media evidence is the target object itself.  ``None``
    means the reflected parent graph is incomplete, cyclic, or escapes the
    sealed import target.
    """

    candidate_id = candidate.get("id")
    if not _valid_object_id(candidate_id) or not _valid_object_id(target_id):
        return None
    if _same_identity(candidate_id, target_id):
        return []
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in candidates:
        row_id = row.get("id")
        if _valid_object_id(row_id):
            by_id.setdefault(_identity_key(row_id), row)
    chain: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    current: Mapping[str, Any] = candidate
    while True:
        current_id = current.get("id")
        if not _valid_object_id(current_id):
            return None
        current_key = _identity_key(current_id)
        if current_key in seen:
            return None
        seen.add(current_key)
        chain.append(current)
        parent_id = _parent_value(current.get("parent"))
        if _same_identity(parent_id, target_id):
            return chain
        if not _valid_object_id(parent_id):
            return None
        parent = by_id.get(_identity_key(parent_id))
        if parent is None:
            return None
        current = parent


def _import_created_name_matches(
    actual: Any,
    expected: Any,
    *,
    on_name_conflict: Any,
) -> bool:
    if not isinstance(actual, str) or not isinstance(expected, str):
        return False
    if on_name_conflict == "rename":
        return actual == expected or actual.startswith(expected)
    return actual == expected


def _import_originals_subfolder_matches(relative_path: Any, requested: Any) -> bool:
    actual_segments = _import_path_segments(relative_path)
    requested_segments = _import_path_segments(requested)
    if not actual_segments or not requested_segments:
        return False
    parent_segments = actual_segments[:-1]
    width = len(requested_segments)
    return len(parent_segments) >= width and parent_segments[-width:] == requested_segments


def _import_relative_original_path(
    copied_path: Any,
    *,
    originals_root: str,
) -> dict[str, str]:
    try:
        localized_copied = Path(
            _localize_waapi_file_path(
                copied_path,
                field="copied original WAV path",
            )
        )
    except OperationContractError as exc:
        raise OperationContractError(
            "UNSAFE_ORIGINALS_PATH",
            "The copied original WAV path is not an authoritative absolute path.",
            details=exc.as_dict(),
        ) from exc
    root = _secure_import_filesystem_path(
        Path(originals_root),
        field="prepared Originals root",
        require_directory=True,
    )
    copied = _secure_import_filesystem_path(
        localized_copied,
        field="copied original WAV path",
        require_directory=False,
    )
    if not _path_is_within(copied, root) or copied == root:
        raise OperationContractError(
            "ORIGINALS_PATH_ESCAPE",
            "The copied original WAV is outside the authoritative live Project Originals root.",
            details={"originals_root": str(root), "copied_path": str(copied)},
        )
    relative = copied.relative_to(root)
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise OperationContractError(
            "UNSAFE_ORIGINALS_PATH",
            "The copied original WAV did not produce a safe relative Originals path.",
            details={"originals_root": str(root), "copied_path": str(copied)},
        )
    return {
        "originals_root": str(root),
        "copied_path": str(copied),
        "relative_path": "/".join(relative.parts),
    }


def _import_file_path_key(value: Any) -> HostPathKey | None:
    try:
        return host_path_comparison_key(value)
    except HostPathError:
        return None


def _require_reference_target_allowed(
    metadata: PropertyInfoMetadataRecord,
    target: ResolvedObject,
) -> None:
    try:
        allowed_types = set(reference_allowed_types(metadata.restriction))
    except MetadataRestrictionError as exc:
        raise OperationContractError(
            exc.error_code,
            str(exc),
            details={"reference": metadata.name, "restriction": dict(metadata.restriction)},
        ) from exc
    if not allowed_types:
        return
    target_type = target.row.get("type")
    if not isinstance(target_type, str) or not target_type:
        raise OperationContractError(
            "INVALID_READBACK",
            "Reference target readback must expose a type when live restrictions are present.",
            details={"reference": metadata.name, "target": target.as_dict()},
        )
    target_token = reference_type_token(target_type)
    allowed_tokens = {reference_type_token(value) for value in allowed_types}
    if target_token not in allowed_tokens:
        raise OperationContractError(
            "INVALID_REFERENCE_TARGET",
            "Reference target type is not allowed by live getPropertyInfo restrictions.",
            details={
                "reference": metadata.name,
                "target_type": target_type,
                "allowed_types": sorted(allowed_types),
            },
        )


def _require_reference_clear_allowed(
    metadata: PropertyInfoMetadataRecord,
) -> None:
    """Reject an explicit clear when live metadata proves the reference non-null."""

    restrictions = metadata.restriction.get("restrictions")
    if restrictions is None:
        return
    if not isinstance(restrictions, list):
        raise OperationContractError(
            "INVALID_METADATA",
            "Reference restriction metadata must be an array when present.",
            details={
                "reference": metadata.name,
                "restriction": dict(metadata.restriction),
            },
        )
    for item in restrictions:
        if isinstance(item, str):
            if item == "notNull":
                raise OperationContractError(
                    "REFERENCE_NOT_CLEARABLE",
                    "Live getPropertyInfo metadata marks this reference as non-null.",
                    details={
                        "reference": metadata.name,
                        "restriction": dict(metadata.restriction),
                    },
                )
            if item == "playable":
                # A target classifier is unnecessary when no target remains.
                continue
            raise OperationContractError(
                "INVALID_METADATA",
                "Reference restriction metadata contains an unknown string flag.",
                details={
                    "reference": metadata.name,
                    "restriction": dict(metadata.restriction),
                    "flag": item,
                },
            )
        if not isinstance(item, Mapping):
            raise OperationContractError(
                "INVALID_METADATA",
                "Reference restriction entries must be objects or supported string flags.",
                details={
                    "reference": metadata.name,
                    "restriction": dict(metadata.restriction),
                },
            )


def _valid_object_id(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (str, int)) and value != ""


def _valid_transport_id(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and 1 <= value <= 0xFFFFFFFF


def _transport_list_rows(result: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    value = result.get("list")
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        return [], False
    rows = [dict(item) for item in value]
    return rows, all(_valid_transport_id(row.get("transport")) for row in rows)


def _reject_protected_delete(target: ResolvedObject) -> None:
    row = target.row
    path = row.get("path")
    name = row.get("name")
    object_type = row.get("type")
    protected = object_type == "Project" or path in {"\\", ""} or (
        name == "Default Work Unit" and isinstance(path, str) and path.count("\\") <= 2
    )
    if protected:
        raise OperationContractError(
            "PROTECTED_TARGET",
            "Project roots and default work units cannot be deleted through the stable transaction interface.",
            details={"target": target.as_dict()},
        )


def _require_object_create_writable_parent(
    parent: ResolvedObject,
    *,
    version: str,
    child_types: Sequence[str],
) -> None:
    row = parent.row
    path = row.get("path")
    object_type = row.get("type")
    if (
        object_type == "Project"
        or path in {"\\", ""}
        or (isinstance(path, str) and path.count("\\") <= 1)
    ):
        raise OperationContractError(
            "PROTECTED_CREATE_PARENT",
            "Project and management roots cannot be object.create parents through the closed interface.",
            details={"parent": parent.as_dict()},
        )
    if not isinstance(path, str) or not path.startswith("\\"):
        raise OperationContractError(
            "INVALID_READBACK",
            "object.create parent must expose an absolute live Wwise path.",
            details={"parent": parent.as_dict()},
        )
    allowed_types = (
        OBJECT_CREATE_WRITABLE_PARENT_TYPES
        | frozenset(OBJECT_CREATE_SPECIALIZED_CHILD_TYPES_BY_PARENT)
        | OBJECT_CREATE_REFLECTED_PARENT_TYPES_BY_VERSION.get(
            version,
            frozenset(),
        )
    )
    if object_type not in allowed_types:
        raise OperationContractError(
            "INVALID_CREATE_PARENT_TYPE",
            "object.create parent is not one of the reviewed writable object types.",
            details={
                "actual_type": object_type,
                "allowed_types": sorted(allowed_types),
                "version": version,
                "parent": parent.as_dict(),
            },
        )
    _require_specialized_object_child_types(
        parent_type=object_type,
        child_types=child_types,
        details={"parent": parent.as_dict(), "version": version},
    )


def _require_specialized_object_tree_relationships(
    nodes: Sequence[ObjectNodeDescriptor],
) -> None:
    for node in nodes:
        if not node.children:
            continue
        _require_specialized_object_child_types(
            parent_type=node.type,
            child_types=tuple(child.type for child in node.children),
            details={"request_path": node.request_path},
        )


def _require_specialized_object_child_types(
    *,
    parent_type: Any,
    child_types: Sequence[str],
    details: Mapping[str, Any],
) -> None:
    parent_token = _object_type_token(parent_type)
    specialized = next(
        (
            (name, allowed)
            for name, allowed in OBJECT_CREATE_SPECIALIZED_CHILD_TYPES_BY_PARENT.items()
            if _object_type_token(name) == parent_token
        ),
        None,
    )
    if specialized is not None:
        canonical_parent, allowed_child_types = specialized
        allowed_tokens = {
            _object_type_token(child_type) for child_type in allowed_child_types
        }
        invalid_child_types = sorted(
            {
                str(child_type)
                for child_type in child_types
                if _object_type_token(child_type) not in allowed_tokens
            },
            key=str.casefold,
        )
        if invalid_child_types:
            raise OperationContractError(
                "INVALID_CREATE_CHILD_TYPE_FOR_PARENT",
                f"{canonical_parent} accepts only its reviewed Game Sync child type.",
                details={
                    **dict(details),
                    "parent_type": canonical_parent,
                    "invalid_child_types": invalid_child_types,
                    "allowed_child_types": sorted(allowed_child_types),
                },
            )

    for child_type in child_types:
        allowed_parent_types = sorted(
            parent_name
            for parent_name, allowed_children in (
                OBJECT_CREATE_SPECIALIZED_CHILD_TYPES_BY_PARENT.items()
            )
            if _object_type_token(child_type)
            in {_object_type_token(item) for item in allowed_children}
        )
        if allowed_parent_types and parent_token not in {
            _object_type_token(item) for item in allowed_parent_types
        }:
            raise OperationContractError(
                "INVALID_CREATE_PARENT_TYPE_FOR_CHILD",
                f"{child_type} can be created only under its reviewed Game Sync group type.",
                details={
                    **dict(details),
                    "actual_parent_type": parent_type,
                    "child_type": child_type,
                    "allowed_parent_types": allowed_parent_types,
                },
            )


def _require_object_list_owner(owner: ResolvedObject) -> None:
    row = owner.row
    path = row.get("path")
    object_type = row.get("type")
    if (
        object_type == "Project"
        or path in {"\\", ""}
        or not isinstance(path, str)
        or not path.startswith("\\")
        or path.count("\\") <= 1
    ):
        raise OperationContractError(
            "PROTECTED_LIST_OWNER",
            "Project and management roots cannot own object-list mutations through the closed interface.",
            details={"owner": owner.as_dict()},
        )


def _reject_protected_replace_boundary(target: ResolvedObject) -> None:
    row = target.row
    path = row.get("path")
    name = row.get("name")
    object_type = row.get("type")
    protected = object_type == "Project" or path in {"\\", ""} or (
        isinstance(path, str) and path.count("\\") <= 1
    ) or (
        name == "Default Work Unit" and isinstance(path, str) and path.count("\\") <= 2
    )
    if protected:
        raise OperationContractError(
            "PROTECTED_REPLACE_ROOT",
            "Project, management, and default-work-unit roots cannot bound or be removed by object.create replace.",
            details={"target": target.as_dict()},
        )


def _execution_result_id(result: Mapping[str, Any]) -> Any:
    current: Any = result
    for _ in range(3):
        if isinstance(current, Mapping) and current.get("id") is not None:
            return current.get("id")
        if isinstance(current, Mapping) and isinstance(current.get("return"), list):
            rows = current["return"]
            if len(rows) == 1 and isinstance(rows[0], Mapping):
                return rows[0].get("id")
            return None
        if isinstance(current, Mapping) and isinstance(current.get("result"), Mapping):
            current = current["result"]
            continue
        break
    return None


def _rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = result.get("return")
    if not isinstance(values, list):
        raise OperationContractError(
            "INVALID_READBACK",
            "object.get result must contain a return array.",
            details={"result": dict(result)},
        )
    if not all(isinstance(row, Mapping) for row in values):
        raise OperationContractError(
            "INVALID_READBACK",
            "object.get return must contain only object rows.",
            details={"result": dict(result)},
        )
    return [dict(row) for row in values]


def _require_exact_keys(
    payload: Mapping[str, Any],
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
    context: str,
) -> None:
    actual = set(payload)
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - actual)
    unknown = sorted(actual - allowed)
    if missing or unknown:
        raise OperationContractError(
            "INVALID_REQUEST",
            f"{context} fields do not match the closed JSON contract.",
            details={"missing_fields": missing, "unknown_fields": unknown, "allowed_fields": sorted(allowed)},
        )


def _non_empty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OperationContractError("INVALID_ARGUMENT", f"{field} must be a non-empty string.")
    return value


def _parent_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get("id") or value.get("path") or value.get("name")
    return value


def _direct_child_parent_relationship_matches(
    child_row: Mapping[str, Any],
    parent: ResolvedObject,
) -> bool | None:
    """Prove a direct-child row's parent when canonical readback permits it."""

    actual = child_row.get("parent")
    if isinstance(actual, Mapping):
        checked = False
        for field_name, expected in (
            ("id", parent.object),
            ("path", parent.row.get("path")),
        ):
            value = actual.get(field_name)
            if value is None or expected is None:
                continue
            checked = True
            if not _same_identity(value, expected):
                return False
        if checked:
            return True
    elif isinstance(actual, (str, int)) and not isinstance(actual, bool):
        expected_values = (
            parent.object,
            parent.row.get("id"),
            parent.row.get("path"),
        )
        return any(
            expected is not None and _same_identity(actual, expected)
            for expected in expected_values
        )

    child_path = child_row.get("path")
    parent_path = parent.row.get("path")
    if isinstance(child_path, str) and isinstance(parent_path, str):
        separator = "" if parent_path.endswith("\\") else "\\"
        relative = child_path.removeprefix(f"{parent_path}{separator}")
        if relative != child_path:
            return bool(relative) and "\\" not in relative
    return None


def _field_value(row: Mapping[str, Any], field_name: str) -> Any:
    for key in (field_name, f"@{field_name}", f"@@{field_name}"):
        if key in row:
            return row[key]
    return None


def _reference_identity(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get("id") or value.get("object") or value.get("path")
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return value
    return None


def _reference_value_is_null(value: Any) -> bool:
    if value is None:
        return True
    identity = _reference_identity(value)
    return (
        isinstance(identity, str)
        and identity.casefold()
        == "{00000000-0000-0000-0000-000000000000}"
    )


def _typed_value_equal(actual: Any, expected: Any, metadata_type: str) -> bool:
    if metadata_type.lower() in {"real32", "real64", "float", "double"}:
        if isinstance(actual, bool) or isinstance(expected, bool):
            return False
        if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
            return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-5)
    return actual == expected


def _same_identity(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    return str(left).casefold() == str(right).casefold()


def _json_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_mapping(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_mapping(item) for item in value]
    if isinstance(value, list):
        return [_json_mapping(item) for item in value]
    return value


_UNAVAILABLE_VERSION_SCHEMA = object()


def _project_supported_version_contract(value: Any, *, version: str) -> Any:
    """Remove Registry schema nodes that do not belong to one exact lane."""

    if isinstance(value, Mapping):
        supported = value.get("supported_versions")
        if supported is not None:
            if not isinstance(supported, list) or not all(
                isinstance(item, str) for item in supported
            ):
                raise RuntimeError("Registry supported_versions must be a string array")
            if version not in supported:
                return _UNAVAILABLE_VERSION_SCHEMA
        projected: dict[str, Any] = {}
        for key, item in value.items():
            child = _project_supported_version_contract(item, version=version)
            if child is not _UNAVAILABLE_VERSION_SCHEMA:
                projected[str(key)] = child
        properties = projected.get("properties")
        if isinstance(properties, Mapping):
            allowed = set(properties)
            for keyword in ("required", "optional"):
                names = projected.get(keyword)
                if isinstance(names, list):
                    projected[keyword] = [name for name in names if name in allowed]
        return projected
    if isinstance(value, list):
        projected_items = []
        for item in value:
            child = _project_supported_version_contract(item, version=version)
            if child is not _UNAVAILABLE_VERSION_SCHEMA:
                projected_items.append(child)
        return projected_items
    return value


def _operation_argument_contract(
    operation: str,
    value: Mapping[str, Any],
    *,
    version: str | None,
) -> dict[str, Any]:
    contract = _json_mapping(value)
    if version is not None and operation in {
        "audio.importTabDelimited",
        "lua.executeCliFile",
        "lua.executeCoreFile",
        "lua.executeCoreInline",
        "ui.commands.register",
        "ui.commands.unregister",
    }:
        projected = _project_supported_version_contract(contract, version=version)
        if not isinstance(projected, dict):  # pragma: no cover - root invariant
            raise RuntimeError("Operation argument contract is unavailable in its own version lane")
        contract = projected
    if operation == "waapi.undoGroup":
        # The normal Composer owns child-operation discovery and typed facts.
        # The canonical Registry records only Gateway-generated bound requests;
        # it never exposes native URI/args/options as a public child grammar.
        return contract
    if operation == "object.create":
        contract["default_container_parent_contract"] = (
            _object_create_default_container_parent_contract(version=version)
        )
        contract["same_name_merge_path_contract"] = (
            _object_create_same_name_merge_path_contract(version=version)
        )
        return contract
    if operation == "object.set":
        contract["default_container_target_contract"] = (
            _object_set_default_container_target_contract(version=version)
        )
        return contract
    if operation != "audio.import":
        return contract

    path_contract = _audio_import_object_path_contract(version=version)
    try:
        properties = contract["properties"]
        item_properties = properties["imports"]["items"]["properties"]
        default_properties = properties["defaults"]["properties"]
        item_properties["object_path"]["path_contract"] = _json_mapping(
            path_contract
        )
        default_properties["object_path"]["path_contract"] = _json_mapping(
            path_contract
        )
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            "audio.import operation schema no longer exposes both object_path fields"
        ) from exc
    return contract


def _object_create_same_name_merge_path_contract(
    *,
    version: str | None,
) -> dict[str, Any]:
    return {
        "contract": "waapi-skill.object-create-same-name-merge-path/v1",
        "applies_when": (
            "Exactly one unchanged same-name existing request root below the "
            "current-version default container Work Unit receives only a "
            "recursive descendant merge."
        ),
        "resolved_target": _default_container_work_unit_target(version=version),
        "exact_path": {
            "base_path_source": "resolved_target",
            "separator": "\\",
            "append_user_stated_descendant_segments": True,
            "terminal_segment": "same_name_request_root",
        },
        "identity_query": {
            "route": "query-object",
            "must_follow_operation_schema_directly": True,
            "path_mode": "exact",
            "return_fields": ["id", "name", "type", "path"],
            "path_argument_contract": (
                _SHELL_SINGLE_QUOTED_WWISE_PATH_CONTRACT
            ),
        },
        "forbidden_intermediate_routes": ["project-default-work-units"],
    }


def _object_create_default_container_parent_contract(
    *,
    version: str | None,
) -> dict[str, Any]:
    return {
        "contract": "waapi-skill.object-create-default-container-parent/v1",
        "applies_when": (
            "The user anchors a new object.create parent relative to the "
            "current-version default container Work Unit."
        ),
        "resolved_target": _default_container_work_unit_target(version=version),
        "parent_path": {
            "base_path_source": "resolved_target",
            "separator": "\\",
            "append_user_stated_parent_segments": True,
        },
        "dynamic_actor_mixer_metadata_scope": (
            _actor_mixer_metadata_scope(version=version)
        ),
        "required_sequence": [
            "operation-schema object.create",
            "one metadata discover when a dynamic field token is unknown",
            "preview",
        ],
        "forbidden_intermediate_routes": ["project-default-work-units"],
    }


def _object_set_default_container_target_contract(
    *,
    version: str | None,
) -> dict[str, Any]:
    return {
        "contract": "waapi-skill.object-set-default-container-target/v1",
        "applies_when": (
            "The user names one or more existing targets relative to the "
            "current-version default container Work Unit."
        ),
        "resolved_target": _default_container_work_unit_target(version=version),
        "exact_path": {
            "base_path_source": "resolved_target",
            "separator": "\\",
            "append_user_stated_descendant_segments": True,
        },
        "dynamic_actor_mixer_metadata_scope": (
            _actor_mixer_metadata_scope(version=version)
        ),
        "required_sequence": [
            "operation-schema object.set",
            "one metadata discover when a dynamic field token is unknown",
            "preview",
        ],
        "forbidden_intermediate_routes": ["project-default-work-units"],
    }


def _actor_mixer_metadata_scope(
    *,
    version: str | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "object_type",
        "one_discovery_for_same_type_targets": True,
        "object_scope_is_for_one_existing_target_only": True,
    }
    if version is None:
        result["actor_mixer_object_type_by_version"] = dict(
            _ACTOR_MIXER_METADATA_TYPE_BY_VERSION
        )
    else:
        result["wwise_version"] = version
        result["actor_mixer_object_type"] = (
            _ACTOR_MIXER_METADATA_TYPE_BY_VERSION[version]
        )
    return result


def _default_container_work_unit_target(
    *,
    version: str | None,
) -> dict[str, Any]:
    if version is None:
        return {
            "default_container_work_unit_path_by_version": dict(
                _DEFAULT_CONTAINER_WORK_UNIT_PATH_BY_VERSION
            )
        }
    return {
        "wwise_version": version,
        "default_container_work_unit_path": (
            _DEFAULT_CONTAINER_WORK_UNIT_PATH_BY_VERSION[version]
        ),
    }


def _audio_import_object_path_contract(
    *,
    version: str | None,
) -> dict[str, Any]:
    resolved_target: dict[str, Any] = {
        "minimum_segments": 3,
        "hierarchy_root_case_sensitive": True,
    }
    if version is None:
        resolved_target["allowed_hierarchy_roots_by_version"] = {
            lane: list(allowed_import_hierarchy_roots(lane))
            for lane in SUPPORTED_WWISE_VERSION_KEYS
        }
    else:
        resolved_target["wwise_version"] = version
        resolved_target["allowed_hierarchy_roots"] = list(
            allowed_import_hierarchy_roots(version)
        )
    return {
        "contract": "waapi-skill.audio-import-object-path/v1",
        "resolved_target": resolved_target,
        "absolute_form": True,
        "import_location_selection": {
            "wire_significant": True,
            "absolute_object_path": {
                "ordinary_action": "omit",
                "infer_from_common_parent": False,
                "include_only_when_user_explicitly_requests_native_field": True,
            },
            "relative_object_path": {
                "requires_effective_import_location": True,
                "effective_sources": [
                    "$.arguments.imports[].import_location",
                    "$.arguments.defaults.import_location",
                ],
            },
        },
        "relative_form": {
            "allowed": True,
            "requires_effective_import_location": True,
        },
    }


__all__ = [
    "COMPOSER_INPUT_MODE",
    "BUSINESS_DECLARATION_INPUT_MODE",
    "audio_import_business_contract",
    "INLINE_TYPED_INPUT_MODE",
    "CONDITIONAL_LOCAL_FILESYSTEM_OPERATIONS",
    "DYNAMIC_LOCAL_FILESYSTEM_OPERATIONS",
    "LOCAL_FILESYSTEM_OPERATION_ROLES",
    "NO_LOCAL_FILESYSTEM_OPERATIONS",
    "INTERNAL_CANONICAL_INPUT_MODE",
    "OPERATION_INPUT_MODE_LANES",
    "OPERATION_REQUEST_CONTRACT",
    "PREPARED_OPERATION_CONTRACT",
    "VERIFICATION_RESULT_CONTRACT",
    "ROLE_VALIDATION_CONTRACT",
    "SUPPORTED_OPERATION_INPUT_MODES",
    "OperationContractError",
    "OperationInputModeLane",
    "OperationRequest",
    "OperationSpec",
    "PreparedOperation",
    "VerificationResult",
    "describe_operation",
    "list_operation_specs",
    "operation_input_mode",
    "operation_input_modes_by_version",
    "operation_uses_business_declaration",
    "operation_business_contract",
    "operation_request_machine_contract",
    "operation_request_schema_digest",
    "parse_operation_request",
    "prepare_object_set_batch_check",
    "prepare_operation",
    "validate_operation_input_mode_lanes",
    "validate_operation_identity_fragment",
    "validate_prepared_roles",
    "verify_prepared_operation",
]
