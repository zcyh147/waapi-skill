"""Closed JSON operations backed by semantic builders and live readbacks.

This module is the bridge between a model-facing JSON request and the existing
Python semantic builders.  It deliberately exposes no arbitrary URI, args,
options, Python kwargs, identity rows, or property metadata.  Every object role
is resolved live to exactly one canonical GUID before a mutating preview is
built, and every implemented operation has an operation-specific verifier.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from xml.etree import ElementTree as ET

from .canonical import canonical_json_bytes
from .builders.imports import ImportBuilder
from .builders.identity import ObjectIdentity, ResolvedObject, plan_object_resolution
from .builders.metadata import (
    GET_PROPERTY_INFO_URI,
    ObjectTypeMetadataRecord,
    PropertyInfoMetadataRecord,
    parse_get_types_result,
    parse_get_property_info_result,
)
from .builders.object_mutation import ObjectMutationBuilder
from .builders.properties import PropertyReferenceBuilder
from .builders.common import SemanticEnvelope, SemanticPreview, SemanticValidationError
from .builders.schema import validate_semantic_payload, validate_semantic_result
from .builders.soundbank import SoundBankBuilder
from .builders.switchcontainer import SwitchContainerAssignmentBuilder
from .execution_contracts import ExecutionContractError, ExecutionContractRegistry
from .io_policy import IOPolicyError, validate_isolated_io
from .operation_import import (
    ImportContractError,
    build_audio_import_plan,
    expected_audio_file_source_result_path,
    language_requires_live_project_validation,
    parse_tab_delimited_import_file,
    regular_file_proof as import_regular_file_proof,
    unsupported_localized_existing_fields,
    verify_regular_file_proof as verify_import_file_proof,
)
from .operation_object import (
    DEFAULT_MAX_NODES,
    ObjectNodeDescriptor,
    ObjectOperationContractError,
    ObjectResultNode,
    bind_request_result_topology,
    flatten_create_result,
    flatten_request_nodes,
    flatten_set_result,
    materialize_waapi_node,
    normalize_object_forest,
    normalize_property_descriptors,
    normalize_reference_descriptors,
    normalize_object_tree,
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
from .transaction_cleanup import build_transaction_cleanup_spec
from .versions import SUPPORTED_WWISE_VERSION_KEYS


OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
PREPARED_OPERATION_CONTRACT = "waapi-skill.prepared-operation/v1"
VERIFICATION_RESULT_CONTRACT = "waapi-skill.operation-verification/v1"
ROLE_VALIDATION_CONTRACT = "waapi-skill.role-validation/v1"
OBJECT_GET_URI = "ak.wwise.core.object.get"
OBJECT_GET_TYPES_URI = "ak.wwise.core.object.getTypes"
GET_PROJECT_INFO_URI = "ak.wwise.core.getProjectInfo"
SOUNDBANK_GET_INCLUSIONS_URI = "ak.wwise.core.soundbank.getInclusions"
SWITCHCONTAINER_GET_ASSIGNMENTS_URI = "ak.wwise.core.switchContainer.getAssignments"
REMOTE_GET_CONNECTION_STATUS_URI = "ak.wwise.core.remote.getConnectionStatus"
REMOTE_CONNECT_URI = "ak.wwise.core.remote.connect"
REMOTE_DISCONNECT_URI = "ak.wwise.core.remote.disconnect"
TRANSPORT_CREATE_URI = "ak.wwise.core.transport.create"
TRANSPORT_DESTROY_URI = "ak.wwise.core.transport.destroy"
TRANSPORT_GET_LIST_URI = "ak.wwise.core.transport.getList"
TRANSPORT_GET_STATE_URI = "ak.wwise.core.transport.getState"
CLI_CONVERT_EXTERNAL_SOURCE_URI = "ak.wwise.cli.convertExternalSource"
AUTHORING_AUDIO_CONVERT_URI = "ak.wwise.core.audio.convert"
PACKAGED_TRANSACTION_READBACK_URIS = frozenset(
    {
        OBJECT_GET_URI,
        OBJECT_GET_TYPES_URI,
        GET_PROJECT_INFO_URI,
        GET_PROPERTY_INFO_URI,
        SOUNDBANK_GET_INCLUSIONS_URI,
        SWITCHCONTAINER_GET_ASSIGNMENTS_URI,
        REMOTE_GET_CONNECTION_STATUS_URI,
        TRANSPORT_GET_LIST_URI,
        TRANSPORT_GET_STATE_URI,
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
_REFERENCE_ACTIVATION_DEPENDENCY_FIELDS = frozenset(
    {"action", "context", "property", "type"}
)
_REFERENCE_ACTIVATION_FIELD_NAME = re.compile(r"^[:_a-zA-Z0-9]+$")
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
IMPORT_ROOTS_BY_VERSION: Mapping[str, frozenset[str]] = {
    "2021.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2022.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2023.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2024.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2025.1": frozenset({"Containers", "Interactive Music Hierarchy"}),
}
IMPORT_ITEM_REQUIRED_FIELDS = ("object_path", "audio_file")
IMPORT_ITEM_OPTIONAL_FIELDS = (
    "object_type",
    "import_language",
    "originals_subfolder",
    "notes",
    "audio_source_notes",
    "event",
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
_WAQL_IDENTITY_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["kind", "value"],
    "additionalProperties": False,
    "properties": {"kind": {"const": "waql"}, "value": {"type": "string", "minLength": 1}},
}
IDENTITY_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "oneOf": [
        _ID_IDENTITY_SCHEMA,
        _PATH_IDENTITY_SCHEMA,
        _WAQL_IDENTITY_SCHEMA,
        {
            "type": "object",
            "required": ["kind", "name", "type", "parent"],
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "scoped-name"},
                "name": {"type": "string", "minLength": 1},
                "type": {"type": "string", "minLength": 1},
                "parent": {
                    "description": "Closed id or path identity; live-resolved before preview.",
                    "oneOf": [_ID_IDENTITY_SCHEMA, _PATH_IDENTITY_SCHEMA],
                },
            },
        },
    ]
}

_OBJECT_PROPERTY_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["name", "value"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "value": {"description": "Finite JSON scalar validated against live getPropertyInfo metadata."},
    },
}
_OBJECT_REFERENCE_ARGUMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["name", "target"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "target": IDENTITY_ARGUMENT_SCHEMA,
    },
}
_OBJECT_CREATE_TYPE_TOKEN_DESCRIPTION = (
    "Exact Wwise metadata token. Natural mappings: Actor Mixer -> ActorMixer; "
    "Random Container / 随机容器 -> RandomSequenceContainer (never RandomContainer); "
    "Blend Container / 混合容器 -> BlendContainer; Sound -> Sound."
)
_OBJECT_CREATE_TYPE_TOKEN_SCHEMA: Mapping[str, Any] = {
    "type": "string",
    "minLength": 1,
    "description": _OBJECT_CREATE_TYPE_TOKEN_DESCRIPTION,
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
            "description": "Recursive closed object-node DSL with the same six fields; depth 8 and 128 total nodes.",
        },
    },
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
        },
        "events": {"type": "array", "minItems": 1, "items": IDENTITY_ARGUMENT_SCHEMA},
        "aux_busses": {"type": "array", "minItems": 1, "items": IDENTITY_ARGUMENT_SCHEMA},
        "inclusions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "uniqueItems": True,
            "items": {"type": "string", "enum": ["event", "structure", "media"]},
        },
        "rebuild": {"type": "boolean"},
    },
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

    def as_dict(self) -> dict[str, Any]:
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
            "argument_contract": _json_mapping(self.argument_contract),
            "constraints": list(self.constraints),
        }
        if self.identity_arguments:
            result["identity_contract"] = {
                "one_of": ["id", "path", "waql", "scoped-name"],
                "argument_fields": list(self.identity_arguments),
                "runtime_live_resolution_required": True,
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
                        ("api", "args"),
                        {
                            "api": {"type": "string", "pattern": r"^ak\.wwise\.core\."},
                            "args": {"type": "object"},
                            "options": {"type": "object"},
                        },
                        optional=("options",),
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
            "execution is bound to immutable preview confirmation",
        ),
    ),
    "audio.import": OperationSpec(
        "audio.import",
        "ak.wwise.core.audio.import",
        "import",
        "Import absolute regular audio files with a closed createNew/useExisting/replaceExisting policy and verify every requested target and copied source file.",
        ("imports",),
        ("import_operation",),
        argument_contract=_object_contract(
            ("imports",),
            {
                "imports": {
                    "type": "array",
                    "minItems": 1,
                    "items": _object_contract(
                        IMPORT_ITEM_REQUIRED_FIELDS,
                        {
                            "object_path": {"type": "string", "pattern": r"^\\"},
                            "object_type": {"type": "string", "minLength": 1},
                            "audio_file": {"type": "string", "absoluteRegularFile": True},
                            "import_language": {"type": "string", "minLength": 1},
                            "originals_subfolder": {"type": "string"},
                            "notes": {"type": "string"},
                            "audio_source_notes": {"type": "string"},
                            "event": _object_contract(
                                ("path",),
                                {
                                    "path": {"type": "string", "pattern": r"^\\Events\\"},
                                    "action": {
                                        "type": "string",
                                        "enum": ["Play", "Stop", "Pause", "Resume", "Break", "Seek"],
                                    },
                                },
                                optional=("action",),
                            ),
                        },
                        optional=IMPORT_ITEM_OPTIONAL_FIELDS,
                    ),
                },
                "import_operation": {
                    "type": "string",
                    "enum": ["createNew", "useExisting", "replaceExisting"],
                },
            },
            optional=("import_operation",),
        ),
        constraints=(
            "all source files and targets are preflighted before the single dispatch",
            "useExisting preserves an existing target GUID; replaceExisting requires the old GUID to disappear",
            "a live non-SFX localized useExisting row dispatches only audioFile/objectPath/importLanguage; objectType is consumed by live type preflight and other requested row fields are rejected",
            "replaceExisting is irreversible and must be exercised only in a disposable project copy during tests",
        ),
    ),
    "audio.importTabDelimited": OperationSpec(
        "audio.importTabDelimited",
        "ak.wwise.core.audio.importTabDelimited",
        "import",
        "Import a bounded strict-UTF-8 tab-delimited file whose targets and source-file proofs are derived by the packaged parser.",
        ("import_file", "import_location", "import_language"),
        ("import_operation",),
        argument_contract=_object_contract(
            ("import_file", "import_location", "import_language"),
            {
                "import_file": {"type": "string", "absoluteRegularFile": True},
                "import_location": IDENTITY_ARGUMENT_SCHEMA,
                "import_language": {"type": "string", "minLength": 1},
                "import_operation": {
                    "type": "string",
                    "enum": ["createNew", "useExisting", "replaceExisting"],
                },
            },
            optional=("import_operation",),
        ),
        identity_arguments=("import_location",),
        constraints=(
            "accepted columns are version-pinned and importLanguage is a call argument, never a TSV column",
            "the parser hashes the TSV and every referenced absolute regular media file before preview",
            "a missing or invalid row rejects the whole request before dispatch",
        ),
    ),
    "object.create": OperationSpec(
        "object.create",
        "ak.wwise.core.object.create",
        "object-mutation",
        "Create or merge one bounded recursive object tree under a live-resolved parent, including a guarded replace confined to one explicitly authorized root.",
        ("parent", "type", "name"),
        ("notes", "properties", "references", "children", "on_name_conflict", "replace_owned_root"),
        argument_contract=_object_contract(
            ("parent", "type", "name"),
            {
                "parent": IDENTITY_ARGUMENT_SCHEMA,
                "type": _OBJECT_CREATE_TYPE_TOKEN_SCHEMA,
                "name": {"type": "string", "minLength": 1},
                "notes": {"type": "string"},
                "properties": {"type": "array", "items": _OBJECT_PROPERTY_ARGUMENT_SCHEMA},
                "references": {"type": "array", "items": _OBJECT_REFERENCE_ARGUMENT_SCHEMA},
                "children": {
                    "type": "array",
                    "items": _OBJECT_NODE_ARGUMENT_SCHEMA,
                    "description": (
                        "Recursive closed node DSL; raw @ keys, lists, plug-ins, and RTPCs are rejected. "
                        "For an existing named request root, keep its existing parent as parent, repeat "
                        "the root type/name, and use on_name_conflict=merge."
                    ),
                },
                "on_name_conflict": {
                    "type": "string",
                    "enum": ["fail", "rename", "merge", "replace"],
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
                "on_name_conflict",
                "replace_owned_root",
            ),
        ),
        identity_arguments=("parent", "replace_owned_root"),
        constraints=(
            "maximum depth 8, 128 nodes, and 32 children per parent",
            "one existing named root that only receives a recursive descendant merge remains an object.create request: identify its existing parent, repeat the root type/name, and use on_name_conflict=merge",
            "parent must live-resolve below a management root to one reviewed writable WorkUnit, Folder, Actor-Mixer container, or Interactive-Music container type",
            "replace_owned_root is an explicit reviewed authorization boundary, not independently proven ownership; replace requires the collision strictly below that non-protected live root and a complete pre-state snapshot of at most 128 old subtree GUID/path rows",
            "fail, rename, and merge reject replace_owned_root; raw @ fields, classId, plug-ins, lists, RTPCs, Clips, Sequences, and Stingers are not exposed",
            "the complete returned GUID topology and every requested field are read back after execution",
        ),
    ),
    "object.delete": OperationSpec(
        "object.delete",
        "ak.wwise.core.object.delete",
        "object-mutation",
        "Delete one live-resolved non-protected object and verify GUID absence.",
        ("object",),
        argument_contract=_object_contract(("object",), {"object": IDENTITY_ARGUMENT_SCHEMA}),
        identity_arguments=("object",),
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
    ),
    "object.setProperty": OperationSpec(
        "object.setProperty",
        "ak.wwise.core.object.setProperty",
        "property-reference",
        "Set one non-platform-specific property using live property metadata and typed readback.",
        ("object", "property", "value"),
        argument_contract=_object_contract(
            ("object", "property", "value"),
            {
                "object": IDENTITY_ARGUMENT_SCHEMA,
                "property": {"type": "string", "minLength": 1},
                "value": {"description": "JSON scalar accepted only after live property metadata validation."},
            },
        ),
        identity_arguments=("object",),
    ),
    "object.setReference": OperationSpec(
        "object.setReference",
        "ak.wwise.core.object.setReference",
        "property-reference",
        "Set one non-platform-specific reference after resolving source and target GUIDs.",
        ("object", "reference", "target"),
        argument_contract=_object_contract(
            ("object", "reference", "target"),
            {
                "object": IDENTITY_ARGUMENT_SCHEMA,
                "reference": {"type": "string", "minLength": 1},
                "target": IDENTITY_ARGUMENT_SCHEMA,
            },
        ),
        identity_arguments=("object", "target"),
    ),
    "object.set": OperationSpec(
        "object.set",
        "ak.wwise.core.object.set",
        "object-mutation",
        "Batch fields and genuinely new recursive children against one or more existing live-resolved targets.",
        ("objects",),
        ("on_name_conflict",),
        argument_contract=_object_contract(
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
                            "notes": {"type": "string"},
                            "properties": {"type": "array", "items": _OBJECT_PROPERTY_ARGUMENT_SCHEMA},
                            "references": {"type": "array", "items": _OBJECT_REFERENCE_ARGUMENT_SCHEMA},
                            "children": {
                                "type": "array",
                                "items": _OBJECT_NODE_ARGUMENT_SCHEMA,
                                "description": (
                                    "Only genuinely new direct children belong here. Never redeclare an "
                                    "existing nested container as a child; give it a separate objects[] "
                                    "row and put only its new descendants there."
                                ),
                            },
                        },
                        optional=("notes", "properties", "references", "children"),
                    ),
                },
                "on_name_conflict": {
                    "type": "string",
                    "enum": ["fail", "rename", "merge"],
                    "description": (
                        "Applies only to genuinely new children, never to existing objects[] "
                        "targets. Use fail for children requested as new or absent; use merge "
                        "only when the user explicitly requests collision merging for a new "
                        "child name."
                    ),
                },
            },
            optional=("on_name_conflict",),
        ),
        identity_arguments=("objects[].object",),
        constraints=(
            "every target and field pre-state is captured before the one non-retryable batch dispatch",
            "every existing nested container that receives descendants is a separate objects[] target; children contain only genuinely new direct descendants",
            "on_name_conflict applies only to new children; existing objects[] targets do not imply merge, and children requested as new or absent use fail",
            "children are append/merge only; listMode, replaceAll, raw @ keys, plug-ins, platform link state, and RTPCs are rejected",
            "a partial result or any per-target readback mismatch fails verification",
        ),
        supported_versions=("2022.1", "2023.1", "2024.1", "2025.1"),
    ),
    "object.copy": OperationSpec(
        "object.copy",
        "ak.wwise.core.object.copy",
        "object-mutation",
        "Copy one object under one parent.",
        ("object", "parent"),
        argument_contract=_object_contract(
            ("object", "parent"),
            {"object": IDENTITY_ARGUMENT_SCHEMA, "parent": IDENTITY_ARGUMENT_SCHEMA},
        ),
        identity_arguments=("object", "parent"),
        implemented=False,
        boundary="The current builder reads back the source instead of the returned copy GUID.",
    ),
    "object.move": OperationSpec(
        "object.move",
        "ak.wwise.core.object.move",
        "object-mutation",
        "Move one object under one parent.",
        ("object", "parent"),
        argument_contract=_object_contract(
            ("object", "parent"),
            {"object": IDENTITY_ARGUMENT_SCHEMA, "parent": IDENTITY_ARGUMENT_SCHEMA},
        ),
        identity_arguments=("object", "parent"),
        implemented=False,
        boundary="The current builder does not assert the new parent/path or preserve a rollback snapshot.",
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
            "replace sets the complete normalized inclusion list and may use an empty list",
            "add upserts the complete filter row for each requested object while preserving other objects",
            "remove requires an exact live filter-row match and removes the requested object inclusion",
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
                "platforms": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                "languages": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                "skip_languages": {"type": "boolean"},
                "write_to_disk": {"const": True},
                "rebuild_soundbanks": {"type": "boolean"},
                "clear_audio_file_cache": {"type": "boolean"},
                "rebuild_init_bank": {"type": "boolean"},
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
            "Event and AuxBus descriptors resolve live to one GUID before preview",
            "Wwise 2021.1 derives project paths from the live Project filePath plus a hashed strict WPROJ parse; later versions use live core.getProjectInfo",
            "confirmation replays project/file/artifact guards; verification requires each requested Bank artifact to be created or changed and non-empty",
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
            "confirmation rejects input, project, or output-tree drift; verification requires every exact WEM output and rejects partial success",
        ),
        supported_versions=("2022.1", "2023.1", "2024.1", "2025.1"),
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
            "confirmation replays file/project and SoundBank inclusion snapshots; verification checks exact target inclusions and one unrelated control Bank",
        ),
        supported_versions=("2022.1", "2023.1", "2024.1", "2025.1"),
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
            "the exact child and state_or_switch pair must already exist",
        ),
    ),
}


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
    for index, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, Mapping):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                f"waapi.undoGroup calls[{index}] must be a JSON object.",
            )
        _require_exact_keys(
            raw_call,
            required=("api", "args"),
            optional=("options",),
            context=f"waapi.undoGroup calls[{index}]",
        )
        api = raw_call.get("api")
        args = raw_call.get("args")
        options = raw_call.get("options", {})
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
        if not isinstance(args, Mapping) or not isinstance(options, Mapping):
            raise OperationContractError(
                "INVALID_ARGUMENT",
                f"waapi.undoGroup calls[{index}] args/options must be JSON objects.",
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
        validation = validate_semantic_payload(api, args, options, version=version)
        calls.append(
            {
                "api": api,
                "args": dict(args),
                "options": dict(options),
                "request_validation": validation.as_dict(),
                "request_validation_strength": (
                    "partial_reflected_schema"
                    if validation.unresolved_refs
                    else "complete_reflected_schema"
                ),
            }
        )
    cancel_args = {} if version in {"2021.1", "2022.1"} else {"undo": True}
    plan = {
        "kind": "same_connection_undo_group",
        "version": version,
        "begin": {"uri": UNDO_BEGIN_GROUP_URI, "args": {}, "options": {}},
        "calls": calls,
        "end": {
            "uri": UNDO_END_GROUP_URI,
            "args": {"displayName": display_name},
            "options": {},
        },
        "cancel": {
            "uri": UNDO_CANCEL_GROUP_URI,
            "args": cancel_args,
            "options": {},
        },
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
    parent = _resolve_identity(arguments.get("parent"), role="parent", read=read)
    _require_object_create_writable_parent(parent)
    roles: dict[str, ResolvedObject] = {"parent": parent}
    replace_owned_root: ResolvedObject | None = None
    if requested_conflict == "replace":
        replace_owned_root = _resolve_identity(
            arguments.get("replace_owned_root"),
            role="replace_owned_root",
            read=read,
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
    type_catalog = _read_object_type_catalog(read)
    canonical_types: dict[str, str] = {}
    resolved_references: dict[str, Any] = {}
    derived_properties: dict[str, dict[str, Any]] = {}
    node_specs = _prepare_object_node_specs(
        normalized.nodes,
        type_catalog=type_catalog,
        read=read,
        roles=roles,
        canonical_types=canonical_types,
        resolved_references=resolved_references,
        derived_properties=derived_properties,
    )
    root_path = _child_path(parent.row.get("path"), normalized.root.name, field="parent.path")
    conflict = normalized.on_name_conflict
    path_snapshots: list[dict[str, Any]] = []
    replace_subtree_snapshots: list[dict[str, Any]] = []
    if conflict == "fail":
        rows = _read_object_path_rows(root_path, fields=IDENTITY_RETURN_FIELDS, read=read)
        if rows:
            raise OperationContractError(
                "TARGET_EXISTS",
                "object.create with on_name_conflict=fail requires the exact root path to be absent at preview.",
                details={"path": root_path, "rows": rows},
            )
        path_snapshots.append({"path": root_path, "fields": list(IDENTITY_RETURN_FIELDS), "rows": []})
    elif conflict == "merge":
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

    parent_children = _read_direct_children(parent.object, fields=IDENTITY_RETURN_FIELDS, read=read)
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
        "autoAddToSourceControl": False,
    }
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
        "children_snapshots": [
            {
                "object_id": parent.object,
                "fields": list(IDENTITY_RETURN_FIELDS),
                "rows": parent_children,
            }
        ],
        "field_snapshots": [],
        "subtree_snapshots": replace_subtree_snapshots,
    }
    verification = {
        "kind": "object-create-graph",
        "version": request.version,
        "parent_id": parent.object,
        "on_name_conflict": conflict,
        "nodes": node_specs,
        "preexisting_root_rows": path_snapshots[0]["rows"] if path_snapshots else [],
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


def _prepare_object_set(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw_objects = _mapping_sequence(arguments.get("objects"), field="objects")
    conflict = str(arguments.get("on_name_conflict", "fail"))
    type_catalog = _read_object_type_catalog(read)
    roles: dict[str, ResolvedObject] = {}
    dispatch_objects: list[dict[str, Any]] = []
    node_specs: list[dict[str, Any]] = []
    field_snapshots: list[dict[str, Any]] = []
    children_snapshots: list[dict[str, Any]] = []
    path_snapshots: list[dict[str, Any]] = []
    resolved_target_ids: dict[str, int] = {}
    for index, item in enumerate(raw_objects):
        merge_child_snapshots: list[dict[str, Any]] = []
        target = _resolve_identity(item.get("object"), role=f"objects[{index}].object", read=read)
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
            on_name_conflict=conflict,
            base_path=f"$.objects[{index}].children",
        )
        if children.roots:
            _require_object_create_writable_parent(target)
        target_spec: dict[str, Any] = {
            "request_path": f"$.objects[{index}]",
            "parent_request_path": None,
            "existing_target": True,
            "target_id": target.object,
            "requested_name": target.row.get("name"),
            "requested_type": target.row.get("type"),
            "canonical_type": target.row.get("type"),
            "notes_supplied": "notes" in item,
            "requested_notes": item.get("notes"),
            "properties": [],
            "references": [],
        }
        trusted: dict[str, Any] = {"object": target.object}
        property_info_by_name: dict[str, PropertyInfoMetadataRecord] = {}
        derived_target_properties: dict[str, Any] = {}
        if "notes" in item:
            notes = item.get("notes")
            if not isinstance(notes, str):
                raise OperationContractError("INVALID_ARGUMENT", f"object.set objects[{index}].notes must be a string.")
            trusted["notes"] = notes
        for descriptor in properties:
            info = _read_property_info(read, object_id=target.object, name=descriptor.name)
            _require_object_property_value(info, descriptor.value)
            property_info_by_name[descriptor.name.casefold()] = info
            trusted[f"@{descriptor.name}"] = descriptor.value
            target_spec["properties"].append(
                {"name": descriptor.name, "value": descriptor.value, "metadata_type": info.type}
            )
        for descriptor in references:
            info = _read_property_info(read, object_id=target.object, name=descriptor.name)
            _require_object_reference_metadata(info)
            activation_properties = _apply_reference_activation_dependencies(
                info,
                read=read,
                object_id=target.object,
                property_specs=target_spec["properties"],
                property_info_by_name=property_info_by_name,
                derived_properties=derived_target_properties,
                request_path=descriptor.request_path,
            )
            resolved = _resolve_identity(
                descriptor.target.as_dict(),
                role=descriptor.request_path,
                read=read,
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
            type_catalog=type_catalog,
            read=read,
            roles=roles,
            canonical_types=canonical_types,
            resolved_references=resolved_references,
            derived_properties=derived_child_properties,
        )
        if children.roots:
            trusted["children"] = [
                _materialize_canonical_object_node(
                    root,
                    canonical_types=canonical_types,
                    resolved_references=resolved_references,
                    derived_properties=derived_child_properties,
                )
                for root in children.roots
            ]
        target_path = target.row.get("path")
        for child_spec in child_specs:
            child_spec["target_index"] = index
            child_spec["parent_request_path"] = (
                target_spec["request_path"]
                if child_spec["parent_request_path"] is None
                else child_spec["parent_request_path"]
            )
            expected_path = _request_node_expected_path(
                target_path,
                child_spec,
                child_specs,
                root_request_path=target_spec["request_path"],
            )
            if conflict == "merge":
                fields = _object_spec_return_fields(child_spec)
                rows = _read_object_path_rows(expected_path, fields=fields, read=read)
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
                path_snapshots.append({"path": expected_path, "fields": fields, "rows": rows})
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
            elif conflict == "fail" and child_spec["parent_request_path"] == target_spec["request_path"]:
                fields = _object_spec_return_fields(child_spec)
                rows = _read_object_path_rows(expected_path, fields=fields, read=read)
                if rows:
                    raise OperationContractError(
                        "TARGET_EXISTS",
                        "object.set append-only child creation with fail requires each root child path to be absent.",
                        details={"path": expected_path, "rows": rows},
                    )
                path_snapshots.append({"path": expected_path, "fields": fields, "rows": rows})
                child_spec["expected_path"] = expected_path

        snapshot_fields = _dedupe_fields(
            [
                *IDENTITY_RETURN_FIELDS,
                *(row["name"] for row in target_spec["properties"]),
                *(row["name"] for row in target_spec["references"]),
            ]
        )
        snapshot_rows = _read_object_id_rows(target.object, fields=snapshot_fields, read=read)
        if len(snapshot_rows) != 1:
            raise OperationContractError("INVALID_READBACK", "object.set pre-state target must resolve exactly once.")
        field_snapshots.append({"object_id": target.object, "fields": snapshot_fields, "rows": snapshot_rows})
        target_spec["pre_state"] = snapshot_rows[0]
        child_rows = _read_direct_children(target.object, fields=IDENTITY_RETURN_FIELDS, read=read)
        children_snapshots.append(
            {"object_id": target.object, "fields": list(IDENTITY_RETURN_FIELDS), "rows": child_rows}
        )
        children_snapshots.extend(merge_child_snapshots)
        target_spec["preexisting_children"] = child_rows
        target_spec["children_request_paths"] = [row["request_path"] for row in child_specs]
        node_specs.append(target_spec)
        node_specs.extend(child_specs)
        if len(node_specs) > DEFAULT_MAX_NODES:
            raise OperationContractError(
                "NODE_LIMIT_EXCEEDED",
                "object.set target and child nodes exceed the single bounded result budget.",
                details={"count": len(node_specs), "limit": DEFAULT_MAX_NODES},
            )
        dispatch_objects.append(trusted)

    dispatch_args = {
        "objects": dispatch_objects,
        "onNameConflict": conflict,
        "listMode": "append",
        "autoAddToSourceControl": False,
    }
    preview = _closed_operation_preview(
        uri="ak.wwise.core.object.set",
        args=dispatch_args,
        options={"return": list(IDENTITY_RETURN_FIELDS)},
        version=request.version,
        family="object-mutation",
        metadata={
            "closed_object_batch": True,
            "target_count": len(raw_objects),
            "node_count": len(node_specs),
            "partial_success_is_failure": True,
        },
    )
    graph_guard = {
        "kind": "object-set-batch",
        "path_snapshots": path_snapshots,
        "children_snapshots": children_snapshots,
        "field_snapshots": field_snapshots,
    }
    verification = {
        "kind": "object-set-batch",
        "version": request.version,
        "on_name_conflict": conflict,
        "nodes": node_specs,
    }
    cleanup = {
        "kind": "discard-owned-sandbox-or-restore-captured-fields",
        "automatic": False,
        "automatic_retry": False,
        "partial_success_possible": len(raw_objects) > 1,
    }
    return preview, roles, {"object_graph_guard": graph_guard, "object_set_nodes": node_specs}, verification, cleanup


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


def _prepare_object_node_specs(
    nodes: Sequence[ObjectNodeDescriptor],
    *,
    type_catalog: Sequence[ObjectTypeMetadataRecord],
    read: ReadCall,
    roles: dict[str, ResolvedObject],
    canonical_types: dict[str, str],
    resolved_references: dict[str, Any],
    derived_properties: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for node in nodes:
        type_info = _resolve_object_type(node.type, catalog=type_catalog)
        # ``object.getTypes`` reports a broad base class in ``type`` (for
        # example, 2022.1 reports ``WObject`` for Sound, ActorMixer, and
        # RandomSequenceContainer).  ``object.create`` instead requires the
        # concrete creation token in the uniquely resolved metadata ``name``.
        canonical_types[node.request_path] = type_info.name
        spec: dict[str, Any] = {
            "request_path": node.request_path,
            "parent_request_path": node.parent_request_path,
            "existing_target": False,
            "requested_name": node.name,
            "requested_type": node.type,
            "canonical_type": type_info.name,
            "class_id": type_info.class_id,
            "notes_supplied": node.notes is not None,
            "requested_notes": node.notes,
            "properties": [],
            "references": [],
        }
        property_info_by_name: dict[str, PropertyInfoMetadataRecord] = {}
        node_derived_properties: dict[str, Any] = {}
        for descriptor in node.properties:
            info = _read_property_info(read, class_id=type_info.class_id, name=descriptor.name)
            _require_object_property_value(info, descriptor.value)
            property_info_by_name[descriptor.name.casefold()] = info
            spec["properties"].append(
                {"name": descriptor.name, "value": descriptor.value, "metadata_type": info.type}
            )
        for descriptor in node.references:
            info = _read_property_info(read, class_id=type_info.class_id, name=descriptor.name)
            _require_object_reference_metadata(info)
            activation_properties = _apply_reference_activation_dependencies(
                info,
                read=read,
                class_id=type_info.class_id,
                property_specs=spec["properties"],
                property_info_by_name=property_info_by_name,
                derived_properties=node_derived_properties,
                request_path=descriptor.request_path,
            )
            resolved = _resolve_identity(
                descriptor.target.as_dict(),
                role=descriptor.request_path,
                read=read,
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


def _require_object_property_value(metadata: PropertyInfoMetadataRecord, value: Any) -> None:
    property_type = metadata.type.casefold()
    if property_type in {"real32", "real64", "float", "double"}:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))
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
            property_info = _read_property_info(
                read,
                name=property_name,
                object_id=object_id,
                class_id=class_id,
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
) -> dict[str, Any]:
    try:
        payload = materialize_waapi_node(node, resolved_references=resolved_references)
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
) -> dict[str, Any]:
    options: dict[str, Any] = {"return": list(fields)}
    if language is not None:
        options["language"] = language
    return options


def _read_object_path_rows(
    path: str,
    *,
    fields: Sequence[str],
    read: ReadCall,
    language: str | None = None,
) -> list[dict[str, Any]]:
    return _rows(
        read(
            OBJECT_GET_URI,
            {"from": {"path": [path]}},
            _import_object_get_options(fields, language=language),
        )
    )


def _read_object_id_rows(object_id: Any, *, fields: Sequence[str], read: ReadCall) -> list[dict[str, Any]]:
    return _rows(read(OBJECT_GET_URI, {"from": {"id": [object_id]}}, {"return": list(fields)}))


def _read_direct_children(object_id: Any, *, fields: Sequence[str], read: ReadCall) -> list[dict[str, Any]]:
    return _rows(
        read(
            OBJECT_GET_URI,
            {"from": {"id": [object_id]}, "transform": [{"select": ["children"]}]},
            {"return": list(fields)},
        )
    )


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
            *(row.get("name") for row in spec.get("properties", []) if isinstance(row, Mapping)),
            *(row.get("name") for row in spec.get("references", []) if isinstance(row, Mapping)),
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
    elif request.operation == "object.create":
        preview, workflow_roles, workflow_state, verification, cleanup = _prepare_object_create(
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
    elif request.operation == "object.delete":
        target = _resolve_identity(arguments["object"], role="object", read=read)
        _reject_protected_delete(target)
        roles["object"] = target
        preview = ObjectMutationBuilder(version=request.version).delete(object=target)
        verification = {"kind": "guid-absent", "object_id": target.object}
        cleanup = {"kind": "none-after-delete", "irreversible": True}
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
        info_payload = read(
            GET_PROPERTY_INFO_URI,
            {"object": source.object, "property": field_value},
            {},
        )
        info = parse_get_property_info_result(info_payload)
        metadata["field_info"] = info.as_dict()
        field_before_result = read(
            OBJECT_GET_URI,
            {"from": {"id": [source.object]}},
            {"return": ["id", "path", field_value]},
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
            "row": field_before_rows[0],
        }
        if request.operation == "object.setProperty":
            preview = PropertyReferenceBuilder(version=request.version).set_property(
                object=source,
                property=field_value,
                value=arguments["value"],
                property_info=info,
                property_enabled=None,
            )
            verification = {
                "kind": "same-guid-property",
                "object_id": source.object,
                "field": field_value,
                "expected_value": arguments["value"],
                "metadata_type": info.type,
            }
        else:
            target = _resolve_identity(arguments["target"], role="target", read=read)
            roles["target"] = target
            _require_reference_target_allowed(info, target)
            preview = PropertyReferenceBuilder(version=request.version).set_reference(
                object=source,
                reference=field_value,
                target=target,
                reference_info=info,
            )
            verification = {
                "kind": "same-guid-reference",
                "object_id": source.object,
                "field": field_value,
                "expected_target_id": target.object,
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


def _prepare_audio_import(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw_imports = _mapping_sequence(arguments.get("imports"), field="imports")
    operation = arguments.get("import_operation", "createNew")
    try:
        plan = build_audio_import_plan(
            raw_imports,
            version=request.version,
            import_operation=str(operation),
        )
    except ImportContractError as exc:
        raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
    return _prepare_closed_import_plan(
        request,
        source_operation="audio.import",
        plan=plan,
        read=read,
    )


def _prepare_audio_import_tab_delimited(
    request: OperationRequest,
    *,
    arguments: Mapping[str, Any],
    read: ReadCall,
) -> tuple[SemanticPreview, dict[str, ResolvedObject], dict[str, Any], dict[str, Any], dict[str, Any]]:
    location = _resolve_identity(arguments.get("import_location"), role="import_location", read=read)
    _require_import_parent(location, index=0)
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
    portable = value.replace("\\", "/")
    if Path(portable).is_absolute() or re.fullmatch(r"[A-Za-z]:/.*", portable):
        candidate = Path(_localize_waapi_file_path(value, field=field))
    elif portable == ".":
        candidate = base
    else:
        parts = portable.split("/")
        if any(part in {"", ".", ".."} or ":" in part for part in parts):
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                f"{field} contains an unsafe relative path segment.",
                details={field: value},
            )
        candidate = base.joinpath(*parts)
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
        if stat.S_ISLNK(path_stat.st_mode):
            raise OperationContractError(
                "UNSAFE_ORIGINALS_PATH",
                f"{field} must not contain symbolic links.",
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
    raw_targets = oracle.get("targets")
    if not isinstance(raw_targets, list) or not all(isinstance(row, Mapping) for row in raw_targets):
        raise OperationContractError("INVALID_PREVIEW", "Closed import target oracle is malformed.")
    import_operation = policy.get("import_operation")
    roles: dict[str, ResolvedObject] = {}
    targets: list[dict[str, Any]] = []
    path_snapshots: list[dict[str, Any]] = []
    event_paths: set[str] = set()
    allowed_result_paths: set[str] = set()
    for index, raw_target in enumerate(raw_targets):
        target = dict(raw_target)
        target_path = target.get("canonical_target_path")
        if not isinstance(target_path, str):
            raise OperationContractError("INVALID_PREVIEW", "Import target lacks a canonical path.")
        anchor, empty_ancestor_snapshots = _resolve_import_anchor(
            target_path,
            role=f"targets[{index}].anchor",
            read=read,
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
        source_file_path = (
            source_file.get("path") if isinstance(source_file, Mapping) else None
        )
        if not isinstance(source_file_path, str):
            raise OperationContractError(
                "INVALID_PREVIEW",
                "The closed import target lacks a proven source file path.",
                details={"target_path": target_path},
            )
        try:
            derived_source_path = expected_audio_file_source_result_path(
                target_path,
                source_file_path,
            )
        except ImportContractError as exc:
            raise OperationContractError(
                "INVALID_PREVIEW",
                "The closed import AudioFileSource result path cannot be derived safely.",
                details=exc.as_dict(),
            ) from exc
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
        event = target.get("requested_event")
        if isinstance(event, Mapping):
            _require_exact_keys(
                event,
                required=("path", "action"),
                context=f"targets[{index}].requested_event",
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
            target["event_pre_state_rows"] = event_rows
            path_snapshots.append({"path": event_path, "fields": list(IDENTITY_RETURN_FIELDS), "rows": event_rows})
        targets.append(target)

    if import_operation == "useExisting":
        unsupported_existing_rows: list[dict[str, Any]] = []
        for index, target in enumerate(targets):
            if not target.get("pre_state_rows"):
                continue
            unsupported = unsupported_localized_existing_fields(
                import_language=target.get("requested_language"),
                originals_subfolder_supplied=(
                    "requested_originals_subfolder" in target
                ),
                notes_supplied="requested_notes" in target,
                audio_source_notes_supplied=(
                    "requested_audio_source_notes" in target
                ),
                event_supplied="requested_event" in target,
            )
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
    originals_context: Mapping[str, Any] = _read_import_originals_context(
        request.version,
        read=read,
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
        options={"return": _import_target_return_fields({}, version=request.version)},
        version=request.version,
        family="import",
        metadata={
            "closed_import_plan": plan.get("contract"),
            "import_operation": import_operation,
            "target_count": len(targets),
            "caller_expected_rows_accepted": False,
            "preflight_consumed_fields": preflight_consumed_fields,
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
    guard = {
        "source_operation": source_operation,
        "file_proofs": file_proofs,
        "path_snapshots": path_snapshots,
        "language_inventory": _json_mapping(language_inventory) if language_inventory is not None else None,
    }
    guard["originals_context"] = _json_mapping(originals_context)
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
    }
    verification["originals_context"] = _json_mapping(originals_context)
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
        _require_import_parent(resolved, index=0)
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
    fields = [
        *IDENTITY_RETURN_FIELDS,
        "activeSource",
        "originalFilePath",
        "sound:originalWavFilePath",
        "audioSource:language",
    ]
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
        "originalFilePath",
        "audioSource:language",
    ]
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
    portable = value.replace("\\", "/")
    if Path(portable).is_absolute() or re.fullmatch(r"[A-Za-z]:/.*", portable):
        candidate = Path(_localize_waapi_file_path(value, field=field))
    elif portable == ".":
        candidate = project_root
    else:
        parts = portable.split("/")
        if any(
            part in {"", "."}
            or ":" in part
            or (part == ".." and not allow_parent_segments)
            for part in parts
        ):
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                f"{field} contains an unsafe relative path segment.",
                details={field: value},
            )
        candidate = project_root.joinpath(*parts)
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
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{field} must be a non-empty path string.",
            details={field: value},
        )
    if os.name == "nt":
        path = Path(value)
        if not path.is_absolute():
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                f"{field} must be absolute.",
                details={field: value},
            )
        return str(path)
    normalized = value.replace("\\", "/")
    virtual_drive = re.fullmatch(r"([A-Za-z]):/(.*)", normalized)
    if virtual_drive is not None:
        drive = virtual_drive.group(1).upper()
        suffix = virtual_drive.group(2)
        if drive == "Z":
            path = Path("/") / suffix
        elif drive == "Y":
            # WAAPI's Y: is the login account home, while agent harnesses may
            # deliberately replace HOME for the model process.
            try:
                import pwd

                account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
            except (ImportError, KeyError, OSError) as exc:
                raise OperationContractError(
                    "INVALID_PROJECT_CONTEXT",
                    "The WAAPI Y: virtual drive could not be mapped to the host account home.",
                    details={field: value, "error": str(exc)},
                ) from exc
            path = account_home / suffix
        else:
            raise OperationContractError(
                "INVALID_PROJECT_CONTEXT",
                f"{field} uses an unmappable WAAPI virtual drive.",
                details={field: value, "drive": drive},
            )
    else:
        path = Path(normalized)
    if not path.is_absolute():
        raise OperationContractError(
            "INVALID_PROJECT_CONTEXT",
            f"{field} must be absolute after WAAPI path localization.",
            details={field: value, "localized": str(path)},
        )
    return str(path)


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
        expected_plan = build_undo_group_execution_plan(version, arguments)
        expected_dispatch = expected_plan["begin"]
        actual_plan = pre_state.get("execution_plan")
        passed = actual_plan == expected_plan and dict(dispatch_payload) == expected_dispatch
        assertions.append(
            {
                "name": "waapi.undoGroup execution plan still matches the immutable reviewed composite",
                "passed": passed,
                "evidence": {
                    "expected_plan": expected_plan,
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
            "assertions": [_json_mapping(item) for item in assertions],
            "readbacks": [],
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
    for role, snapshot_value in roles.items():
        if not isinstance(snapshot_value, Mapping):
            raise OperationContractError("INVALID_PREVIEW", f"Resolved role {role!r} is malformed.")
        object_id = snapshot_value.get("object")
        expected_row = snapshot_value.get("row")
        if object_id is None or not isinstance(expected_row, Mapping):
            raise OperationContractError("INVALID_PREVIEW", f"Resolved role {role!r} lacks object/row evidence.")
        args = {"from": {"id": [object_id]}}
        options = {"return": list(IDENTITY_RETURN_FIELDS)}
        result = read_call(OBJECT_GET_URI, args, options)
        if not isinstance(result, Mapping):
            raise OperationContractError("INVALID_READBACK", f"Role {role!r} readback must be an object.")
        rows = _rows(result)
        readbacks.append({"role": role, "uri": OBJECT_GET_URI, "args": args, "options": options, "result": dict(result)})
        assertions.append({"name": f"{role} resolves exactly once", "passed": len(rows) == 1, "evidence": rows})
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
    rows are then matched inside that sealed parent topology, with every new
    node required exactly once and every unreviewed returned node rejected.
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
        if on_name_conflict == "rename":
            return node.name == requested_name or node.name.startswith(requested_name)
        return node.name == requested_name

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
            sealed_matches = [
                candidate
                for candidate in available
                if candidate.get("preexisting_id") is not None
                and _same_identity(child.object, candidate.get("preexisting_id"))
            ]
            matches = sealed_matches or [
                candidate
                for candidate in available
                if name_matches(child, candidate)
            ]
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
    ) -> list[dict[str, Any]]:
        args = {"from": {"id": [object_id]}} if object_id is not None else {"from": {"path": [path]}}
        options = _import_object_get_options(fields, language=language)
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
    if kind == "undo-group-result-schemas":
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
        payload = _execution_payload(execution_result)
        result_nodes: tuple[ObjectResultNode, ...] = ()
        result_by_path: dict[str, ObjectResultNode] = {}
        try:
            if kind == "object-create-graph":
                result_nodes = flatten_create_result(payload)
                result_by_path = {row.request_path: row for row in result_nodes}
            else:
                result_nodes = flatten_set_result(payload)
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
            rows = read_object(object_id=object_id, fields=fields)
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
            if plan.get("on_name_conflict") == "rename" and spec.get("existing_target") is not True:
                name_ok = (
                    result_node is not None
                    and isinstance(row.get("name"), str)
                    and bool(row.get("name"))
                    and row.get("name") == returned_name
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
                expected_parent_id = None
            if expected_parent_id is not None:
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
                parent_path = child_spec.get("parent_request_path")
                if isinstance(parent_path, str):
                    direct_specs_by_parent.setdefault(parent_path, []).append(child_spec)
            closure_specs = [
                row
                for row in specs
                if row.get("existing_target") is True
                or row.get("preexisting_id") is not None
                or direct_specs_by_parent.get(str(row.get("request_path")))
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
        rows = read_object(object_id=plan.get("object_id"), fields=("id", "path", field_name))
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
        rows = read_object(object_id=plan.get("object_id"), fields=("id", "path", field_name))
        check("reference source resolves exactly once", len(rows) == 1, rows)
        if len(rows) == 1:
            actual = _reference_identity(_field_value(rows[0], field_name))
            expected = plan.get("expected_target_id")
            if actual is None:
                return VerificationResult(
                    operation,
                    "indeterminate",
                    tuple(assertions),
                    tuple(readbacks),
                    "Wwise did not expose a canonical target identity for the reference readback.",
                )
            check("reference target matches", _same_identity(actual, expected), {"actual": actual, "expected": expected})
    elif kind == "closed-audio-import":
        source_operation = plan.get("source_operation")
        version = plan.get("version")
        uri = plan.get("uri")
        import_operation = plan.get("import_operation")
        result_contract = plan.get("result_contract")
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
        originals_root = _import_originals_root_from_context(
            originals_context,
            version=version,
        )
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
            pre_state_rows = target.get("pre_state_rows")
            expected_source_path = target.get(
                "expected_audio_file_source_result_path"
            )
            notes_destination = target.get("requested_notes_destination")
            if (
                not isinstance(target_path, str)
                or not target_path.startswith("\\")
                or not isinstance(source_proof, Mapping)
                or not isinstance(source_proof.get("path"), str)
                or not isinstance(source_proof.get("sha256"), str)
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
                    )
                )
                or notes_destination not in {"target_object", "audio_file_source"}
                or (
                    "requested_event" in target
                    and not isinstance(target.get("requested_event"), Mapping)
                )
            ):
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A closed audio import target oracle is malformed.",
                    details={"target": target},
                )
            try:
                derived_source_path = expected_audio_file_source_result_path(
                    target_path,
                    str(source_proof["path"]),
                )
            except ImportContractError as exc:
                raise OperationContractError(
                    "INVALID_PREVIEW",
                    "A closed audio import target has an unsafe AudioFileSource result path.",
                    details=exc.as_dict(),
                ) from exc
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
            event = target.get("requested_event")
            if isinstance(event, Mapping):
                event_path = event.get("path")
                event_action = event.get("action")
                event_pre_state_rows = target.get("event_pre_state_rows")
                if (
                    set(event) != {"path", "action"}
                    or not isinstance(event_path, str)
                    or not event_path.startswith("\\")
                    or not isinstance(event_action, str)
                    or event_action not in event_action_types
                    or event_pre_state_rows != []
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
            source_proof = target["source_file"]
            read_language = _localized_import_read_language(
                target.get("requested_language")
            )
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

                active_source_id = _reference_identity(_field_value(live_row, "activeSource"))
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

                copied_path = _field_value(source_state, "originalFilePath")
                if copied_path is None and source_state is not live_row:
                    copied_path = _field_value(live_row, "originalFilePath")
                if copied_path is None:
                    copied_path = _field_value(live_row, "sound:originalWavFilePath")
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
                        check(f"{label} copied original WAV is readable and regular", False, exc.as_dict())
                    else:
                        check(
                            f"{label} copied original WAV hash matches the source",
                            copied_proof.get("sha256") == source_proof.get("sha256"),
                            {
                                "source_path": source_proof.get("path"),
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
                                ) == _import_file_path_key(copied_proof.get("path")):
                                    file_matches.append(item)
                            check(
                                f"{label} copied original WAV is reported exactly once",
                                len(file_matches) == 1,
                                {"copied_path": copied_proof.get("path"), "matches": file_matches},
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

            event = target.get("requested_event")
            if isinstance(event, Mapping):
                event_path = event.get("path")
                if not isinstance(event_path, str) or not event_path.startswith("\\"):
                    raise OperationContractError(
                        "INVALID_PREVIEW",
                        "A closed audio import Event oracle lacks an absolute path.",
                        details={"target_path": target_path, "event": dict(event)},
                    )
                event_rows = read_object(path=event_path, fields=IDENTITY_RETURN_FIELDS)
                check(f"{label} Event exact path resolves once", len(event_rows) == 1, event_rows)
                if len(event_rows) == 1:
                    event_row = event_rows[0]
                    event_id = event_row.get("id")
                    check(
                        f"{label} Event path matches exactly",
                        event_row.get("path") == event_path,
                        {"expected": event_path, "actual": event_row.get("path")},
                    )
                    check(
                        f"{label} Event type is Event",
                        _object_type_token(event_row.get("type")) == "event",
                        event_row.get("type"),
                    )
                    check(f"{label} Event GUID is canonical", _valid_object_id(event_id), event_id)
                    if _valid_object_id(event_id):
                        action_rows = read_direct_children(
                            object_id=event_id,
                            fields=event_action_fields,
                        )
                        check(
                            f"{label} Event contains exactly one direct Action",
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
                                f"{label} Event child type is Action",
                                _object_type_token(action_row.get("type")) == "action",
                                action_row.get("type"),
                            )
                            check(
                                f"{label} Event Action GUID is canonical",
                                _valid_object_id(action_id),
                                action_id,
                            )
                            check(
                                f"{label} Event Action parent is the exact Event",
                                _same_identity(_reference_identity(action_row.get("parent")), event_id),
                                {
                                    "expected_event_id": event_id,
                                    "actual_parent": action_row.get("parent"),
                                },
                            )
                            check(
                                f"{label} Event Action type matches exactly",
                                actual_action_type == expected_action_type,
                                {
                                    "requested_action": expected_action,
                                    "expected_action_type": expected_action_type,
                                    "actual_action_type": actual_action_type,
                                    "raw": _field_value(action_row, "ActionType"),
                                },
                            )
                            check(
                                f"{label} Event Action target is the imported object",
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


def _resolve_identity(payload: Any, *, role: str, read: ReadCall) -> ResolvedObject:
    if not isinstance(payload, Mapping):
        raise OperationContractError("INVALID_IDENTITY", f"{role} identity must be a JSON object.")
    kind = payload.get("kind")
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
    elif kind == "waql":
        _require_exact_keys(payload, required=("kind", "value"), context=f"{role} identity")
        value = payload.get("value")
        if not isinstance(value, str) or not value.strip():
            raise OperationContractError("INVALID_IDENTITY", f"{role} WAQL must be a non-empty string.")
        identity = ObjectIdentity(waql=value)
        args = {"waql": value}
    elif kind == "scoped-name":
        _require_exact_keys(payload, required=("kind", "name", "type", "parent"), context=f"{role} identity")
        parent_payload = payload.get("parent")
        if not isinstance(parent_payload, Mapping) or parent_payload.get("kind") not in {"id", "path"}:
            raise OperationContractError("INVALID_IDENTITY", f"{role} scoped-name parent must be an id or path identity.")
        parent = _resolve_identity(parent_payload, role=f"{role}.parent", read=read)
        name = _non_empty_string(payload.get("name"), field=f"{role}.name")
        object_type = _non_empty_string(payload.get("type"), field=f"{role}.type")
        identity = ObjectIdentity(name=name, type=object_type, parent=str(parent.object))
        planned = plan_object_resolution(identity, destructive_use=True)
        args = dict(planned.readback_plan.args)  # type: ignore[union-attr]
    else:
        raise OperationContractError(
            "INVALID_IDENTITY",
            f"{role} identity kind must be id, path, waql, or scoped-name.",
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
    return ResolvedObject(identity=identity, object=object_id, resolution=f"live-{kind}", row=row)


def _mapping_sequence(value: Any, *, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise OperationContractError("INVALID_ARGUMENT", f"{field} must be a JSON array.")
    if not all(isinstance(item, Mapping) for item in value):
        raise OperationContractError("INVALID_ARGUMENT", f"Every {field} item must be a JSON object.")
    return [dict(item) for item in value]


def _validate_nested_request_shape(
    operation: str,
    arguments: Mapping[str, Any],
    *,
    version: str,
) -> None:
    if operation == "audio.import":
        for index, item in enumerate(_mapping_sequence(arguments.get("imports"), field="imports")):
            _require_exact_keys(
                item,
                required=IMPORT_ITEM_REQUIRED_FIELDS,
                optional=IMPORT_ITEM_OPTIONAL_FIELDS,
                context=f"audio.import imports[{index}]",
            )
            event = item.get("event")
            if event is not None:
                if not isinstance(event, Mapping):
                    raise OperationContractError(
                        "INVALID_ARGUMENT",
                        f"audio.import imports[{index}].event must be a structured JSON object.",
                    )
                _require_exact_keys(
                    event,
                    required=("path",),
                    optional=("action",),
                    context=f"audio.import imports[{index}].event",
                )
        return
    if operation == "audio.importTabDelimited":
        _validate_identity_payload_shape(arguments.get("import_location"), role="import_location")
        return
    if operation == "object.create":
        _validate_identity_payload_shape(arguments.get("parent"), role="parent")
        conflict = arguments.get("on_name_conflict", "fail")
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
        descriptor_keys: set[bytes] = set()
        total_nodes = len(raw_objects)
        for index, item in enumerate(raw_objects):
            _require_exact_keys(
                item,
                required=("object",),
                optional=("notes", "properties", "references", "children"),
                context=f"object.set objects[{index}]",
            )
            _validate_identity_payload_shape(item.get("object"), role=f"objects[{index}].object")
            descriptor_key = canonical_json_bytes(item.get("object"))
            if descriptor_key in descriptor_keys:
                raise OperationContractError(
                    "DUPLICATE_TARGET",
                    "object.set target identity descriptors must be unique.",
                    details={"index": index, "identity": item.get("object")},
                )
            descriptor_keys.add(descriptor_key)
            if not any(field in item for field in ("notes", "properties", "references", "children")):
                raise OperationContractError(
                    "NO_OP",
                    f"object.set objects[{index}] must request at least one field or child change.",
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
                forest = normalize_object_forest(
                    item.get("children", []),
                    on_name_conflict=conflict,
                    base_path=f"$.objects[{index}].children",
                )
                total_nodes += len(forest.nodes)
            except ObjectOperationContractError as exc:
                raise OperationContractError(exc.error_code, str(exc), details=exc.details) from exc
        if total_nodes > DEFAULT_MAX_NODES:
            raise OperationContractError(
                "NODE_LIMIT_EXCEEDED",
                "object.set target and child nodes exceed the single bounded result budget.",
                details={"count": total_nodes, "limit": DEFAULT_MAX_NODES},
            )
        return
    if operation == "soundbank.generate":
        soundbanks = _mapping_sequence(arguments.get("soundbanks"), field="soundbanks")
        for bank_index, bank in enumerate(soundbanks):
            _require_exact_keys(
                bank,
                required=("name", "artifact_expectation"),
                optional=("events", "aux_busses", "inclusions", "rebuild"),
                context=f"soundbank.generate soundbanks[{bank_index}]",
            )
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
    if kind in {"id", "path", "waql"}:
        _require_exact_keys(payload, required=("kind", "value"), context=f"{role} identity")
        return
    if kind == "scoped-name":
        _require_exact_keys(payload, required=("kind", "name", "type", "parent"), context=f"{role} identity")
        parent = payload.get("parent")
        if not isinstance(parent, Mapping) or parent.get("kind") not in {"id", "path"}:
            raise OperationContractError("INVALID_IDENTITY", f"{role} scoped-name parent must be an id or path identity.")
        _validate_identity_payload_shape(parent, role=f"{role}.parent")
        return
    raise OperationContractError(
        "INVALID_IDENTITY",
        f"{role} identity kind must be id, path, waql, or scoped-name.",
        details={"kind": kind},
    )


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
    allowed_roots = IMPORT_ROOTS_BY_VERSION.get(version, frozenset())
    if canonical_segments[0] not in allowed_roots:
        raise OperationContractError(
            "INVALID_TARGET",
            f"The closed audio.import operation does not allow {canonical_segments[0]!r} in Wwise {version}.",
            details={"version": version, "management_root": canonical_segments[0], "allowed_roots": sorted(allowed_roots)},
        )
    target_path = "\\" + "\\".join(canonical_segments)
    parent_path = "\\" + "\\".join(canonical_segments[:-1])
    return target_path, parent_path


def _require_import_parent(parent: ResolvedObject, *, index: int) -> None:
    parent_type = parent.row.get("type")
    parent_path = parent.row.get("path")
    if parent_type not in IMPORT_WRITABLE_PARENT_TYPES or not isinstance(parent_path, str):
        raise OperationContractError(
            "INVALID_TARGET_TYPE",
            "audio.import requires a live writable audio hierarchy parent container.",
            details={"index": index, "allowed_types": sorted(IMPORT_WRITABLE_PARENT_TYPES), "parent": parent.as_dict()},
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
    return [segment.casefold() for segment in re.split(r"[\\/]+", value) if segment]


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


def _import_file_path_key(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return os.path.normpath(value.replace("\\", "/")).casefold()


def _require_reference_target_allowed(
    metadata: PropertyInfoMetadataRecord,
    target: ResolvedObject,
) -> None:
    restrictions = metadata.restriction.get("restrictions")
    if restrictions is None:
        return
    if not isinstance(restrictions, list):
        raise OperationContractError(
            "INVALID_METADATA",
            "Reference restriction metadata must be an array when present.",
            details={"reference": metadata.name, "restriction": dict(metadata.restriction)},
        )
    allowed_types: set[str] = set()
    for item in restrictions:
        if isinstance(item, str):
            if item == "notNull":
                # The closed identity resolver has already proved one concrete,
                # non-null target before this metadata check.
                continue
            if item == "playable":
                raise OperationContractError(
                    "CONSTRAINED_REFERENCE_BOUNDARY",
                    "Playable reference restrictions require a dedicated live target classifier.",
                    details={
                        "reference": metadata.name,
                        "restriction": dict(metadata.restriction),
                    },
                )
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
                details={"reference": metadata.name, "restriction": dict(metadata.restriction)},
            )
        values = item.get("type")
        if values is None:
            continue
        if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
            raise OperationContractError(
                "INVALID_METADATA",
                "Reference restriction type entries must be non-empty string arrays.",
                details={"reference": metadata.name, "restriction": dict(metadata.restriction)},
            )
        allowed_types.update(values)
    if not allowed_types:
        return
    target_type = target.row.get("type")
    if not isinstance(target_type, str) or not target_type:
        raise OperationContractError(
            "INVALID_READBACK",
            "Reference target readback must expose a type when live restrictions are present.",
            details={"reference": metadata.name, "target": target.as_dict()},
        )
    target_token = _reference_type_token(target_type)
    allowed_tokens = {_reference_type_token(value) for value in allowed_types}
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


def _reference_type_token(value: str) -> str:
    token = "".join(character for character in value.casefold() if character.isalnum())
    aliases = {
        "audiobus": "bus",
        "auxiliarybus": "auxbus",
        "auxbus": "auxbus",
    }
    return aliases.get(token, token)


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


def _require_object_create_writable_parent(parent: ResolvedObject) -> None:
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
    if object_type not in OBJECT_CREATE_WRITABLE_PARENT_TYPES:
        raise OperationContractError(
            "INVALID_CREATE_PARENT_TYPE",
            "object.create parent is not one of the reviewed writable object types.",
            details={
                "actual_type": object_type,
                "allowed_types": sorted(OBJECT_CREATE_WRITABLE_PARENT_TYPES),
                "parent": parent.as_dict(),
            },
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


__all__ = [
    "OPERATION_REQUEST_CONTRACT",
    "PREPARED_OPERATION_CONTRACT",
    "VERIFICATION_RESULT_CONTRACT",
    "ROLE_VALIDATION_CONTRACT",
    "OperationContractError",
    "OperationRequest",
    "OperationSpec",
    "PreparedOperation",
    "VerificationResult",
    "describe_operation",
    "list_operation_specs",
    "parse_operation_request",
    "prepare_operation",
    "validate_prepared_roles",
    "verify_prepared_operation",
]
