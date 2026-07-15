"""Closed JSON operations backed by semantic builders and live readbacks.

This module is the bridge between a model-facing JSON request and the existing
Python semantic builders.  It deliberately exposes no arbitrary URI, args,
options, Python kwargs, identity rows, or property metadata.  Every object role
is resolved live to exactly one canonical GUID before a mutating preview is
built, and every implemented operation has an operation-specific verifier.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .canonical import canonical_json_bytes
from .builders.imports import ImportBuilder
from .builders.identity import ObjectIdentity, ResolvedObject, plan_object_resolution
from .builders.metadata import (
    GET_PROPERTY_INFO_URI,
    PropertyInfoMetadataRecord,
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
from .transaction_cleanup import build_transaction_cleanup_spec
from .versions import SUPPORTED_WWISE_VERSION_KEYS


OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
PREPARED_OPERATION_CONTRACT = "waapi-skill.prepared-operation/v1"
VERIFICATION_RESULT_CONTRACT = "waapi-skill.operation-verification/v1"
ROLE_VALIDATION_CONTRACT = "waapi-skill.role-validation/v1"
OBJECT_GET_URI = "ak.wwise.core.object.get"
SOUNDBANK_GET_INCLUSIONS_URI = "ak.wwise.core.soundbank.getInclusions"
SWITCHCONTAINER_GET_ASSIGNMENTS_URI = "ak.wwise.core.switchContainer.getAssignments"
REMOTE_GET_CONNECTION_STATUS_URI = "ak.wwise.core.remote.getConnectionStatus"
REMOTE_CONNECT_URI = "ak.wwise.core.remote.connect"
REMOTE_DISCONNECT_URI = "ak.wwise.core.remote.disconnect"
TRANSPORT_CREATE_URI = "ak.wwise.core.transport.create"
TRANSPORT_DESTROY_URI = "ak.wwise.core.transport.destroy"
TRANSPORT_GET_LIST_URI = "ak.wwise.core.transport.getList"
TRANSPORT_GET_STATE_URI = "ak.wwise.core.transport.getState"
PACKAGED_TRANSACTION_READBACK_URIS = frozenset(
    {
        OBJECT_GET_URI,
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
IMPORT_ROOTS_BY_VERSION: Mapping[str, frozenset[str]] = {
    "2021.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2022.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2023.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2024.1": frozenset({"Actor-Mixer Hierarchy", "Interactive Music Hierarchy"}),
    "2025.1": frozenset({"Containers", "Interactive Music Hierarchy"}),
}
IMPORT_ITEM_REQUIRED_FIELDS = ("object_path", "audio_file")
IMPORT_ITEM_OPTIONAL_FIELDS = ("object_type", "notes")
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
                "api": {"type": "string", "pattern": r"^ak\."},
                "args": {"type": "object"},
                "options": {"type": "object"},
                "io_root": {"type": "string", "minLength": 1},
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
        "Import absolute regular audio files with createNew and verify every returned object GUID/path.",
        ("imports",),
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
                            "notes": {"type": "string"},
                        },
                        optional=IMPORT_ITEM_OPTIONAL_FIELDS,
                    ),
                }
            },
        ),
    ),
    "audio.importTabDelimited": OperationSpec(
        "audio.importTabDelimited",
        "ak.wwise.core.audio.importTabDelimited",
        "import",
        "Import audio from a tab-delimited definition file.",
        ("import_file", "import_location", "import_language"),
        argument_contract=_object_contract(
            ("import_file", "import_location", "import_language"),
            {
                "import_file": {"type": "string", "absoluteRegularFile": True},
                "import_location": IDENTITY_ARGUMENT_SCHEMA,
                "import_language": {"type": "string", "minLength": 1},
            },
        ),
        identity_arguments=("import_location",),
        implemented=False,
        boundary="Materialized-file provenance, row-level partial failure, and created-object cleanup are not yet closed.",
    ),
    "object.create": OperationSpec(
        "object.create",
        "ak.wwise.core.object.create",
        "object-mutation",
        "Create one named object under one live-resolved parent; conflict policy is fixed to fail.",
        ("parent", "type", "name"),
        ("notes",),
        argument_contract=_object_contract(
            ("parent", "type", "name"),
            {
                "parent": IDENTITY_ARGUMENT_SCHEMA,
                "type": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
                "notes": {"type": "string"},
            },
            optional=("notes",),
        ),
        identity_arguments=("parent",),
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
        "Batch object mutation.",
        ("objects",),
        argument_contract=_object_contract(("objects",), {"objects": {"type": "array", "minItems": 1}}),
        implemented=False,
        boundary="Batch partial-success semantics and per-field readback are not yet closed; 2021.1 also lacks the URI.",
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
        "Generate SoundBanks and filesystem artifacts.",
        (),
        argument_contract=_object_contract((), {}),
        implemented=False,
        boundary="Generation logs and topics do not prove complete artifacts; output-root and artifact cleanup remain unclosed.",
    ),
    "soundbank.convertExternalSources": OperationSpec(
        "soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.convertExternalSources",
        "soundbank",
        "Convert external audio sources into platform artifacts.",
        ("sources",),
        argument_contract=_object_contract(("sources",), {"sources": {"type": "array", "minItems": 1}}),
        implemented=False,
        boundary="Output-path containment, overwrite behavior, and artifact cleanup remain unclosed.",
        supported_versions=("2022.1", "2023.1", "2024.1", "2025.1"),
    ),
    "soundbank.processDefinitionFiles": OperationSpec(
        "soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "soundbank",
        "Process SoundBank definition files.",
        ("files",),
        argument_contract=_object_contract(("files",), {"files": {"type": "array", "minItems": 1}}),
        implemented=False,
        boundary="WAAPI call success is not proof of generated SoundBank objects or artifacts; deterministic cleanup remains unclosed.",
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
    _validate_nested_request_shape(operation, arguments)
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
        parent = _resolve_identity(arguments["parent"], role="parent", read=read)
        roles["parent"] = parent
        object_type = _non_empty_string(arguments["type"], field="type")
        name = _non_empty_string(arguments["name"], field="name")
        notes = arguments.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise OperationContractError("INVALID_ARGUMENT", "notes must be a string when supplied.")
        preview = ObjectMutationBuilder(version=request.version).create(
            parent=parent,
            type=object_type,
            name=name,
            notes=notes,
            on_name_conflict="fail",
            auto_add_to_source_control=False,
        )
        verification = {
            "kind": "created-guid-present",
            "result_id_required": True,
            "expected": {"name": name, "requested_type": object_type, "parent_id": parent.object, "notes": notes},
        }
        cleanup = {"kind": "delete-created-guid", "source": "execution_result.id"}
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
    if not raw_imports:
        raise OperationContractError("INVALID_ARGUMENT", "audio.import requires at least one import item.")
    roles: dict[str, ResolvedObject] = {}
    import_rows: list[dict[str, Any]] = []
    file_proofs: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for index, item in enumerate(raw_imports):
        _require_exact_keys(
            item,
            required=IMPORT_ITEM_REQUIRED_FIELDS,
            optional=IMPORT_ITEM_OPTIONAL_FIELDS,
            context=f"audio.import imports[{index}]",
        )
        object_path = _non_empty_string(item.get("object_path"), field=f"imports[{index}].object_path")
        target_path, parent_path = _canonical_import_target_paths(object_path, version=request.version)
        target_key = target_path.casefold()
        if target_key in seen_targets:
            raise OperationContractError(
                "INVALID_ARGUMENT",
                "audio.import target paths must be unique.",
                details={"duplicate_target_path": target_path},
            )
        seen_targets.add(target_key)
        parent = _resolve_identity(
            {"kind": "path", "value": parent_path},
            role=f"imports[{index}].parent",
            read=read,
        )
        _require_import_parent(parent, index=index)
        roles[f"imports[{index}].parent"] = parent
        target_result = read(
            OBJECT_GET_URI,
            {"from": {"path": [target_path]}},
            {"return": list(IDENTITY_RETURN_FIELDS)},
        )
        target_rows = _rows(target_result)
        if target_rows:
            raise OperationContractError(
                "TARGET_EXISTS",
                "audio.import is fixed to createNew, so every canonical target path must be absent at preview.",
                details={"index": index, "target_path": target_path, "rows": target_rows},
            )
        file_proof = _regular_file_proof(item.get("audio_file"), field=f"imports[{index}].audio_file")
        file_proofs.append({"index": index, **file_proof})
        normalized: dict[str, Any] = {
            "objectPath": object_path,
            "audioFile": file_proof["path"],
        }
        for source_name, target_name in (("object_type", "objectType"),):
            if source_name in item:
                normalized[target_name] = _non_empty_string(item.get(source_name), field=f"imports[{index}].{source_name}")
        if "notes" in item:
            notes = item.get("notes")
            if not isinstance(notes, str):
                raise OperationContractError("INVALID_ARGUMENT", f"imports[{index}].notes must be a string.")
            normalized["notes"] = notes
        import_rows.append(normalized)
        targets.append(
            {
                "index": index,
                "object_path": object_path,
                "canonical_target_path": target_path,
                "parent_path": parent_path,
                "parent_id": parent.object,
                "requested_type": normalized.get("objectType"),
                "notes_supplied": "notes" in normalized,
                "requested_notes": normalized.get("notes"),
            }
        )
    preview = ImportBuilder(version=request.version).audio_import(
        import_rows,
        import_operation="createNew",
        auto_add_to_source_control=False,
        auto_check_out_to_source_control=False if request.version in {"2023.1", "2024.1", "2025.1"} else None,
    )
    verification = {
        "kind": "audio-import-created-objects",
        "version": request.version,
        "targets": targets,
        "error_log_is_failure": True,
    }
    cleanup = {
        "kind": "delete-returned-import-guids-and-discard-sandbox-originals",
        "description": "Manual cleanup must delete every GUID returned for the requested target paths and discard copied Originals only with sandbox containment proof.",
        "automatic": False,
        "automatic_retry": False,
        "source": "execution_result.result.objects",
    }
    state = {
        "audio_import_files": file_proofs,
        "audio_import_targets": targets,
        "audio_import_policy": {
            "import_operation": "createNew",
            "auto_add_to_source_control": False,
            "auto_check_out_to_source_control": False if request.version in {"2023.1", "2024.1", "2025.1"} else "not-in-schema",
        },
    }
    return preview, roles, state, verification, cleanup


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

    def read_object(*, object_id: Any = None, path: str | None = None, fields: Sequence[str]) -> list[dict[str, Any]]:
        args = {"from": {"id": [object_id]}} if object_id is not None else {"from": {"path": [path]}}
        options = {"return": list(fields)}
        result = read_call(OBJECT_GET_URI, args, options)
        if not isinstance(result, Mapping):
            raise OperationContractError("INVALID_READBACK", "object.get verification result must be an object.")
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


def _validate_nested_request_shape(operation: str, arguments: Mapping[str, Any]) -> None:
    if operation == "audio.import":
        for index, item in enumerate(_mapping_sequence(arguments.get("imports"), field="imports")):
            _require_exact_keys(
                item,
                required=IMPORT_ITEM_REQUIRED_FIELDS,
                optional=IMPORT_ITEM_OPTIONAL_FIELDS,
                context=f"audio.import imports[{index}]",
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
    recognized = {"normal", "message", "error", "fatal", "fatal error"}
    return (
        isinstance(severity, str)
        and severity.casefold() in recognized
        and isinstance(message, str)
        and (index is None or (not isinstance(index, bool) and isinstance(index, (int, float))))
    )


def _require_reference_target_allowed(
    metadata: PropertyInfoMetadataRecord,
    target: ResolvedObject,
) -> None:
    restrictions = metadata.restriction.get("restrictions")
    if restrictions is None:
        return
    if not isinstance(restrictions, list) or not all(isinstance(item, Mapping) for item in restrictions):
        raise OperationContractError(
            "INVALID_METADATA",
            "Reference restriction metadata must be an array of objects when present.",
            details={"reference": metadata.name, "restriction": dict(metadata.restriction)},
        )
    allowed_types: set[str] = set()
    for item in restrictions:
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
