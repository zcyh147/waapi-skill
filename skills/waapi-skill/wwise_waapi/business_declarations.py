"""Closed business-declaration primitives for Gateway-owned WAAPI planning.

The types in this module are deliberately below any operation-specific CLI.
They let an Adapter accept stable business meaning while keeping exact Wwise
types, paths, metadata tokens, and live binding checks inside the Gateway.
No function in this module calls WAAPI or persists mutable state.
"""

from __future__ import annotations

import hmac
import math
import re
import secrets
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .builders.metadata import (
    GET_PROPERTY_AND_REFERENCE_NAMES_URI,
    GET_PROPERTY_INFO_URI,
    GET_TYPES_URI,
    IS_PROPERTY_ENABLED_URI,
    parse_get_property_info_result,
    parse_get_types_result,
    parse_is_property_enabled_result,
    parse_property_and_reference_names_result,
)
from .canonical import canonical_json_bytes, canonical_sha256, sha256_hex
from .metadata_discovery import metadata_typed_value_type
from .identity_limits import MULTI_IDENTITY_READ_MAX_IDS
from .metadata_restrictions import (
    MetadataRestrictionError,
    reference_allowed_types,
    reference_type_token,
)


BUSINESS_REPAIR_CONTRACT = "waapi-skill.business-repair/v1"
BUSINESS_KIND_CONTRACT = "waapi-skill.semantic-kind/v1"
BUSINESS_CONTEXT_CONTRACT = "waapi-skill.business-context/v1"
OPERATION_DRAFT_AUTHORITY_CONTRACT = "waapi-skill.operation-draft-authority/v1"
BOUND_OBJECT_HANDLE_CONTRACT = "waapi-skill.bound-object-handle/v1"
BOUND_FIELD_HANDLE_CONTRACT = "waapi-skill.bound-field-handle/v1"
BOUND_TYPE_HANDLE_CONTRACT = "waapi-skill.bound-type-handle/v1"
BUSINESS_HANDLE_REGISTRY_CONTRACT = "waapi-skill.business-handle-registry/v2"
_LEGACY_BUSINESS_HANDLE_REGISTRY_CONTRACT = (
    "waapi-skill.business-handle-registry/v1"
)

SUPPORTED_WWISE_VERSIONS = (
    "2021.1",
    "2022.1",
    "2023.1",
    "2024.1",
    "2025.1",
)
SUPPORTED_BUSINESS_KINDS = (
    "actor-mixer",
    "blend-container",
    "music-playlist-container",
    "music-segment",
    "music-switch-container",
    "music-track",
    "random-container",
    "sequence-container",
    "sound-sfx",
    "sound-voice",
    "switch-container",
    "virtual-folder",
)

MAX_BUSINESS_REPAIR_BYTES = 16 * 1024
MAX_BUSINESS_REPAIR_ITEMS = 32
MAX_BUSINESS_REPAIR_TEXT_BYTES = 512
MAX_BUSINESS_NAME_BYTES = 512
MAX_BUSINESS_PATH_BYTES = 8 * 1024
MAX_FIELD_TOKEN_BYTES = 256
MAX_FIELD_STRING_BYTES = 16 * 1024
MAX_FIELD_ENUM_CHOICES = 64
MAX_REFERENCE_TARGET_TYPES = 64
COMMON_BUSINESS_FIELDS = (
    "delay_ms",
    "fade_time_ms",
    "loop",
    "max_instances",
    "output_bus",
    "volume_db",
)

_TASK_AUTHORITY = re.compile(r"^da1-[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OBJECT_HANDLE = re.compile(r"^boh1-[0-9a-f]{32}$")
_FIELD_HANDLE = re.compile(r"^bfh1-[0-9a-f]{32}$")
_TYPE_HANDLE = re.compile(r"^bth1-[0-9a-f]{32}$")
_CANONICAL_GUID = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)
_FIELD_TOKEN = re.compile(r"^[:_a-zA-Z0-9]+$")

TokenBytes = Callable[[int], bytes]
ReadCall = Callable[
    [str, Mapping[str, Any], Mapping[str, Any]],
    Mapping[str, Any],
]


class BusinessDeclarationError(ValueError):
    """One declaration cannot be accepted without guessing or stale reuse."""

    def __init__(self, repair: Mapping[str, Any]) -> None:
        self.repair = dict(repair)
        self.details = dict(repair)
        super().__init__(str(self.repair.get("error_code", "BUSINESS_DECLARATION_ERROR")))

    @property
    def error_code(self) -> str:
        return str(self.repair["error_code"])

    def as_dict(self) -> dict[str, Any]:
        return dict(self.repair)


@dataclass(frozen=True, slots=True)
class BusinessContext:
    """Live facts that every opaque business handle is scoped to."""

    task_authority_digest: str
    project_id: str
    project_path: str
    wwise_version: str
    wwise_build: str

    @classmethod
    def create(
        cls,
        *,
        task_authority: str,
        project_id: str,
        project_path: str,
        wwise_version: str,
        wwise_build: str,
    ) -> "BusinessContext":
        if not isinstance(task_authority, str) or not _TASK_AUTHORITY.fullmatch(
            task_authority
        ):
            raise ValueError("task_authority must be a current Draft capability")
        if wwise_version not in SUPPORTED_WWISE_VERSIONS:
            raise ValueError("wwise_version is not supported")
        return cls(
            task_authority_digest=canonical_sha256(
                {
                    "contract": OPERATION_DRAFT_AUTHORITY_CONTRACT,
                    "task_authority": task_authority,
                }
            ),
            project_id=_required_text(project_id, field="project_id"),
            project_path=_required_text(project_path, field="project_path"),
            wwise_version=wwise_version,
            wwise_build=_required_text(wwise_build, field="wwise_build"),
        )

    def as_binding_dict(self) -> dict[str, str]:
        return {
            "contract": BUSINESS_CONTEXT_CONTRACT,
            "task_authority_digest": self.task_authority_digest,
            "project_id": self.project_id,
            "project_path": self.project_path,
            "wwise_version": self.wwise_version,
            "wwise_build": self.wwise_build,
        }

    @classmethod
    def from_binding_dict(cls, payload: Mapping[str, Any]) -> "BusinessContext":
        if not isinstance(payload, Mapping) or set(payload) != {
            "contract",
            "task_authority_digest",
            "project_id",
            "project_path",
            "wwise_version",
            "wwise_build",
        }:
            raise ValueError("business context fields are invalid")
        if payload.get("contract") != BUSINESS_CONTEXT_CONTRACT:
            raise ValueError("business context contract is invalid")
        digest = payload.get("task_authority_digest")
        version = payload.get("wwise_version")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("business context authority digest is invalid")
        if version not in SUPPORTED_WWISE_VERSIONS:
            raise ValueError("business context Wwise version is invalid")
        return cls(
            task_authority_digest=digest,
            project_id=_required_text(payload.get("project_id"), field="project_id"),
            project_path=_required_text(
                payload.get("project_path"), field="project_path"
            ),
            wwise_version=str(version),
            wwise_build=_required_text(
                payload.get("wwise_build"), field="wwise_build"
            ),
        )


@dataclass(frozen=True, slots=True)
class SemanticKind:
    name: str
    version: str
    path_segment_type: str
    native_object_type: str
    metadata_object_type: str
    verifier_object_types: tuple[str, ...]
    binding_digest: str


@dataclass(frozen=True, slots=True)
class BoundObjectHandle:
    handle: str
    context: BusinessContext
    object_id: str
    name: str
    object_type: str
    path: str
    semantic_kind: str | None
    role: str | None
    binding_digest: str


@dataclass(frozen=True, slots=True)
class BoundFieldHandle:
    handle: str
    context: BusinessContext
    scope_kind: str
    scope_value: str | int
    token: str
    field_kind: str
    value_type: str
    platform: str | int | None
    restrictions: Mapping[str, Any]
    metadata_digest: str
    binding_digest: str


@dataclass(frozen=True, slots=True)
class BoundTypeHandle:
    handle: str
    context: BusinessContext
    class_id: int
    name: str
    type_category: str
    catalog_digest: str
    binding_digest: str


@dataclass(frozen=True, slots=True)
class NewDescendantTarget:
    parent_handle: str
    name: str
    kind: str


@dataclass(frozen=True, slots=True)
class ExistingObjectTarget:
    object_handle: str


_BASE_KIND_ROWS: Mapping[str, tuple[str, str, str, tuple[str, ...]]] = {
    "actor-mixer": (
        "Actor-Mixer",
        "ActorMixer",
        "ActorMixer",
        ("ActorMixer",),
    ),
    "blend-container": (
        "Blend Container",
        "BlendContainer",
        "BlendContainer",
        ("BlendContainer",),
    ),
    "music-playlist-container": (
        "Music Playlist Container",
        "MusicRanSeqCntr",
        "MusicRanSeqCntr",
        ("MusicRanSeqCntr", "Music Playlist Container"),
    ),
    "music-segment": (
        "Music Segment",
        "MusicSegment",
        "MusicSegment",
        ("MusicSegment",),
    ),
    "music-switch-container": (
        "Music Switch Container",
        "MusicSwitchContainer",
        "MusicSwitchContainer",
        ("MusicSwitchContainer",),
    ),
    "music-track": (
        "Music Track",
        "MusicTrack",
        "MusicTrack",
        ("MusicTrack",),
    ),
    "random-container": (
        "Random Container",
        "RandomSequenceContainer",
        "RandomSequenceContainer",
        ("RandomSequenceContainer", "Random Container"),
    ),
    "sequence-container": (
        "Sequence Container",
        "RandomSequenceContainer",
        "RandomSequenceContainer",
        ("RandomSequenceContainer", "Sequence Container"),
    ),
    "sound-sfx": (
        "Sound SFX",
        "Sound SFX",
        "Sound",
        ("Sound", "Sound SFX"),
    ),
    "sound-voice": (
        "Sound Voice",
        "Sound Voice",
        "Sound",
        ("Sound", "Sound Voice"),
    ),
    "switch-container": (
        "Switch Container",
        "SwitchContainer",
        "SwitchContainer",
        ("SwitchContainer",),
    ),
    "virtual-folder": (
        "Virtual Folder",
        "Folder",
        "Folder",
        ("Folder",),
    ),
}

_DISPLAY_KIND_ALIASES = {
    row[0]: stable_name for stable_name, row in _BASE_KIND_ROWS.items()
}


def resolve_semantic_kind(name: str, *, version: str) -> SemanticKind:
    """Resolve one stable kind or its unambiguous Wwise display spelling."""

    if version not in SUPPORTED_WWISE_VERSIONS:
        raise _error(
            "WWISE_VERSION_UNSUPPORTED",
            field="version",
            choices=SUPPORTED_WWISE_VERSIONS,
            action="choose one supported Wwise version",
        )
    canonical_name = (
        _DISPLAY_KIND_ALIASES.get(name, name) if isinstance(name, str) else name
    )
    if not isinstance(canonical_name, str) or canonical_name not in _BASE_KIND_ROWS:
        raise _error(
            "BUSINESS_KIND_UNAVAILABLE",
            field="kind",
            choices=SUPPORTED_BUSINESS_KINDS,
            action="choose one disclosed semantic kind",
        )
    path_type, native_type, metadata_type, verifier_types = _BASE_KIND_ROWS[
        canonical_name
    ]
    if canonical_name == "actor-mixer" and version == "2025.1":
        metadata_type = "PropertyContainer"
        verifier_types = ("ActorMixer", "PropertyContainer")
    material = {
        "contract": BUSINESS_KIND_CONTRACT,
        "name": canonical_name,
        "version": version,
        "path_segment_type": path_type,
        "native_object_type": native_type,
        "metadata_object_type": metadata_type,
        "verifier_object_types": list(verifier_types),
    }
    return SemanticKind(
        name=canonical_name,
        version=version,
        path_segment_type=path_type,
        native_object_type=native_type,
        metadata_object_type=metadata_type,
        verifier_object_types=verifier_types,
        binding_digest=canonical_sha256(material),
    )


def business_repair(
    error_code: str,
    *,
    field: str,
    action: str,
    draft_revision: int | None = None,
    **details: Any,
) -> BusinessDeclarationError:
    """Build one bounded structured repair without reflecting unbounded input."""

    return _error(
        error_code,
        field=field,
        action=action,
        draft_revision=draft_revision,
        **details,
    )


def repair_at_draft_revision(
    error: BusinessDeclarationError,
    *,
    draft_revision: int,
) -> BusinessDeclarationError:
    """Attach the current revision to a nested bounded repair exactly once."""

    if not isinstance(error, BusinessDeclarationError):
        raise TypeError("error must be BusinessDeclarationError")
    if (
        isinstance(draft_revision, bool)
        or not isinstance(draft_revision, int)
        or draft_revision < 0
    ):
        raise ValueError("draft_revision must be a non-negative integer")
    if error.repair.get("draft_revision") == draft_revision:
        return error
    payload = dict(error.repair)
    payload["draft_revision"] = draft_revision
    if len(canonical_json_bytes(payload)) <= MAX_BUSINESS_REPAIR_BYTES:
        return BusinessDeclarationError(payload)
    return _error(
        str(payload.get("error_code", "BUSINESS_DECLARATION_ERROR")),
        field=str(payload.get("field", "declaration")),
        draft_revision=draft_revision,
        action="refresh the bounded declaration evidence and retry",
    )


class BusinessHandleRegistry:
    """Current-task opaque handle table used by one operation Adapter.

    The table has no list/search/resume API.  The random token is only a lookup
    capability; every successful lookup also revalidates all live context facts.
    """

    def __init__(
        self,
        context: BusinessContext,
        *,
        token_bytes: TokenBytes = secrets.token_bytes,
    ) -> None:
        if not isinstance(context, BusinessContext):
            raise TypeError("context must be BusinessContext")
        self.context = context
        self._token_bytes = token_bytes
        self._objects: dict[str, BoundObjectHandle] = {}
        self._fields: dict[str, BoundFieldHandle] = {}
        self._types: dict[str, BoundTypeHandle] = {}

    def bind_object(
        self,
        *,
        object_id: str,
        name: str,
        object_type: str,
        path: str,
        semantic_kind: str | None = None,
        role: str | None = None,
    ) -> BoundObjectHandle:
        if not isinstance(object_id, str) or not _CANONICAL_GUID.fullmatch(object_id):
            raise ValueError("object_id must be a canonical Wwise GUID")
        normalized_name = _bounded_required_text(
            name, field="name", maximum_bytes=MAX_BUSINESS_NAME_BYTES
        )
        normalized_type = _bounded_required_text(
            object_type, field="object_type", maximum_bytes=MAX_FIELD_TOKEN_BYTES
        )
        normalized_path = _bounded_required_text(
            path, field="path", maximum_bytes=MAX_BUSINESS_PATH_BYTES
        ).rstrip("\\")
        if not normalized_path.startswith("\\"):
            raise ValueError("path must be an absolute Wwise path")
        if semantic_kind is not None:
            if semantic_kind not in {"sound-sfx", "sound-voice"}:
                raise ValueError("semantic_kind must be a closed Sound kind")
            if _type_token(normalized_type) != "sound":
                raise ValueError("semantic_kind is valid only for live Sound objects")
        normalized_role = (
            None
            if role is None
            else _bounded_required_text(
                role,
                field="role",
                maximum_bytes=MAX_FIELD_TOKEN_BYTES,
            )
        )
        material = {
            "contract": BOUND_OBJECT_HANDLE_CONTRACT,
            "context": self.context.as_binding_dict(),
            "object_id": object_id.upper(),
            "name": normalized_name,
            "object_type": normalized_type,
            "path": normalized_path,
            "semantic_kind": semantic_kind,
            **({} if normalized_role is None else {"role": normalized_role}),
        }
        digest = canonical_sha256(material)
        handle = self._new_handle("boh1", digest)
        bound = BoundObjectHandle(
            handle=handle,
            context=self.context,
            object_id=object_id.upper(),
            name=normalized_name,
            object_type=normalized_type,
            path=normalized_path,
            semantic_kind=semantic_kind,
            role=normalized_role,
            binding_digest=digest,
        )
        self._objects[handle] = bound
        return bound

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": BUSINESS_HANDLE_REGISTRY_CONTRACT,
            "context": self.context.as_binding_dict(),
            "objects": [
                {
                    "contract": BOUND_OBJECT_HANDLE_CONTRACT,
                    "handle": row.handle,
                    "object_id": row.object_id,
                    "name": row.name,
                    "object_type": row.object_type,
                    "path": row.path,
                    "semantic_kind": row.semantic_kind,
                    **({} if row.role is None else {"role": row.role}),
                    "binding_digest": row.binding_digest,
                }
                for row in sorted(self._objects.values(), key=lambda item: item.handle)
            ],
            "fields": [
                {
                    "contract": BOUND_FIELD_HANDLE_CONTRACT,
                    "handle": row.handle,
                    "scope_kind": row.scope_kind,
                    "scope_value": row.scope_value,
                    "token": row.token,
                    "field_kind": row.field_kind,
                    "value_type": row.value_type,
                    "platform": row.platform,
                    "restrictions": dict(row.restrictions),
                    "metadata_digest": row.metadata_digest,
                    "binding_digest": row.binding_digest,
                }
                for row in sorted(self._fields.values(), key=lambda item: item.handle)
            ],
            "types": [
                {
                    "contract": BOUND_TYPE_HANDLE_CONTRACT,
                    "handle": row.handle,
                    "class_id": row.class_id,
                    "name": row.name,
                    "type_category": row.type_category,
                    "catalog_digest": row.catalog_digest,
                    "binding_digest": row.binding_digest,
                }
                for row in sorted(self._types.values(), key=lambda item: item.handle)
            ],
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        token_bytes: TokenBytes = secrets.token_bytes,
    ) -> "BusinessHandleRegistry":
        if not isinstance(payload, Mapping):
            raise ValueError("business handle registry fields are invalid")
        contract = payload.get("contract")
        expected = {"contract", "context", "objects", "fields"}
        if contract == BUSINESS_HANDLE_REGISTRY_CONTRACT:
            expected.add("types")
        elif contract != _LEGACY_BUSINESS_HANDLE_REGISTRY_CONTRACT:
            raise ValueError("business handle registry contract is invalid")
        if set(payload) != expected:
            raise ValueError("business handle registry fields are invalid")
        context = BusinessContext.from_binding_dict(payload.get("context"))
        registry = cls(context, token_bytes=token_bytes)
        raw_objects = payload.get("objects")
        raw_fields = payload.get("fields")
        raw_types = payload.get("types", [])
        if (
            not isinstance(raw_objects, list)
            or not isinstance(raw_fields, list)
            or not isinstance(raw_types, list)
        ):
            raise ValueError("business handle registry rows are invalid")
        for raw in raw_objects:
            bound = _bound_object_from_dict(raw, context=context)
            if bound.handle in registry._objects:
                raise ValueError("business object handles must be unique")
            registry._objects[bound.handle] = bound
        for raw in raw_fields:
            bound = _bound_field_from_dict(raw, context=context)
            if bound.handle in registry._fields:
                raise ValueError("business field handles must be unique")
            registry._fields[bound.handle] = bound
        for raw in raw_types:
            bound = _bound_type_from_dict(raw, context=context)
            if bound.handle in registry._types:
                raise ValueError("business type handles must be unique")
            registry._types[bound.handle] = bound
        return registry

    def bind_type(
        self,
        *,
        class_id: int,
        name: str,
        type_category: str,
        catalog_digest: str,
    ) -> BoundTypeHandle:
        if (
            isinstance(class_id, bool)
            or not isinstance(class_id, int)
            or not 0 <= class_id <= 0xFFFFFFFF
        ):
            raise ValueError("class_id must be uint32")
        normalized_name = _bounded_required_text(
            name,
            field="name",
            maximum_bytes=MAX_BUSINESS_NAME_BYTES,
        )
        normalized_category = _bounded_required_text(
            type_category,
            field="type_category",
            maximum_bytes=MAX_FIELD_TOKEN_BYTES,
        )
        if not isinstance(catalog_digest, str) or not _SHA256.fullmatch(
            catalog_digest
        ):
            raise ValueError("catalog_digest must be a lowercase SHA-256")
        material = {
            "contract": BOUND_TYPE_HANDLE_CONTRACT,
            "context": self.context.as_binding_dict(),
            "class_id": class_id,
            "name": normalized_name,
            "type_category": normalized_category,
            "catalog_digest": catalog_digest,
        }
        digest = canonical_sha256(material)
        handle = self._new_handle("bth1", digest)
        bound = BoundTypeHandle(
            handle=handle,
            context=self.context,
            class_id=class_id,
            name=normalized_name,
            type_category=normalized_category,
            catalog_digest=catalog_digest,
            binding_digest=digest,
        )
        self._types[handle] = bound
        return bound

    def resolve_type(
        self,
        handle: str,
        *,
        context: BusinessContext | None = None,
    ) -> BoundTypeHandle:
        if not isinstance(handle, str) or not _TYPE_HANDLE.fullmatch(handle):
            raise _error(
                "TYPE_HANDLE_NOT_AVAILABLE",
                field="kind_handle",
                action="discover the type in this task and use its returned handle",
            )
        bound = self._types.get(handle)
        if bound is None:
            raise _error(
                "TYPE_HANDLE_NOT_AVAILABLE",
                field="kind_handle",
                rejected_handle=handle,
                action="discover the type in this task and use its returned handle",
            )
        self._require_context(bound.context, context or self.context, handle=handle)
        return bound

    def resolve_object(
        self,
        handle: str,
        *,
        context: BusinessContext | None = None,
    ) -> BoundObjectHandle:
        if not isinstance(handle, str) or not _OBJECT_HANDLE.fullmatch(handle):
            raise _error(
                "OBJECT_HANDLE_NOT_AVAILABLE",
                field="object_handle",
                action="resolve the object in this task and use its returned handle",
            )
        bound = self._objects.get(handle)
        if bound is None:
            raise _error(
                "OBJECT_HANDLE_NOT_AVAILABLE",
                field="object_handle",
                rejected_handle=handle,
                action="resolve the object in this task and use its returned handle",
            )
        self._require_context(bound.context, context or self.context, handle=handle)
        return bound

    def bind_field(
        self,
        *,
        scope_kind: str,
        scope_value: str | int,
        token: str,
        field_kind: str,
        value_type: str,
        platform: str | int | None = None,
        restrictions: Mapping[str, Any],
        metadata_digest: str,
    ) -> BoundFieldHandle:
        normalized_scope = _normalize_scope(scope_kind, scope_value)
        if not isinstance(token, str) or not _FIELD_TOKEN.fullmatch(token):
            raise ValueError("token must be an exact Wwise property/reference token")
        if len(token.encode("utf-8")) > MAX_FIELD_TOKEN_BYTES:
            raise ValueError("token exceeds its fixed byte limit")
        if field_kind not in {"property", "reference"}:
            raise ValueError("field_kind must be property or reference")
        if value_type not in {"number", "integer", "boolean", "string", "reference"}:
            raise ValueError("value_type is not supported")
        if (field_kind == "reference") != (value_type == "reference"):
            raise ValueError("reference fields require the reference value type")
        if not isinstance(metadata_digest, str) or not _SHA256.fullmatch(metadata_digest):
            raise ValueError("metadata_digest must be a lowercase SHA-256")
        normalized_restrictions = _normalize_restrictions(
            restrictions,
            field_kind=field_kind,
            value_type=value_type,
        )
        normalized_platform = _normalize_field_platform(platform)
        material = {
            "contract": BOUND_FIELD_HANDLE_CONTRACT,
            "context": self.context.as_binding_dict(),
            "scope_kind": scope_kind,
            "scope_value": normalized_scope,
            "token": token,
            "field_kind": field_kind,
            "value_type": value_type,
            "platform": normalized_platform,
            "restrictions": normalized_restrictions,
            "metadata_digest": metadata_digest,
        }
        digest = canonical_sha256(material)
        handle = self._new_handle("bfh1", digest)
        bound = BoundFieldHandle(
            handle=handle,
            context=self.context,
            scope_kind=scope_kind,
            scope_value=normalized_scope,
            token=token,
            field_kind=field_kind,
            value_type=value_type,
            platform=normalized_platform,
            restrictions=normalized_restrictions,
            metadata_digest=metadata_digest,
            binding_digest=digest,
        )
        self._fields[handle] = bound
        return bound

    def resolve_field(
        self,
        handle: str,
        *,
        context: BusinessContext | None = None,
        scope_kind: str,
        scope_value: str | int,
        metadata_digest: str,
    ) -> BoundFieldHandle:
        if not isinstance(handle, str) or not _FIELD_HANDLE.fullmatch(handle):
            raise _error(
                "FIELD_HANDLE_NOT_AVAILABLE",
                field="field_handle",
                action="discover the field in this task and use its returned handle",
            )
        bound = self._fields.get(handle)
        if bound is None:
            raise _error(
                "FIELD_HANDLE_NOT_AVAILABLE",
                field="field_handle",
                rejected_handle=handle,
                action="discover the field in this task and use its returned handle",
            )
        self._require_context(bound.context, context or self.context, handle=handle)
        normalized_scope = _normalize_scope(scope_kind, scope_value)
        if bound.scope_kind != scope_kind or bound.scope_value != normalized_scope:
            raise _error(
                "FIELD_HANDLE_SCOPE_MISMATCH",
                field="field_handle",
                rejected_handle=handle,
                action="discover the field for the current object or class scope",
            )
        if not hmac.compare_digest(bound.metadata_digest, metadata_digest):
            raise _error(
                "FIELD_HANDLE_STALE",
                field="field_handle",
                rejected_handle=handle,
                action="refresh live metadata and use the new field handle",
            )
        return bound

    def bound_field(self, handle: str) -> BoundFieldHandle:
        """Return one current-task field binding without weakening live revalidation."""

        if not isinstance(handle, str) or not _FIELD_HANDLE.fullmatch(handle):
            raise _error(
                "FIELD_HANDLE_NOT_AVAILABLE",
                field="field_handle",
                action="discover the field in this task and use its returned handle",
            )
        bound = self._fields.get(handle)
        if bound is None:
            raise _error(
                "FIELD_HANDLE_NOT_AVAILABLE",
                field="field_handle",
                rejected_handle=handle,
                action="discover the field in this task and use its returned handle",
            )
        self._require_context(bound.context, self.context, handle=handle)
        return bound

    def new_descendant(
        self,
        *,
        parent_handle: str,
        name: str,
        kind: str,
    ) -> NewDescendantTarget:
        self.resolve_object(parent_handle)
        normalized_name = _bounded_required_text(
            name, field="name", maximum_bytes=MAX_BUSINESS_NAME_BYTES
        )
        if any(character in normalized_name for character in ("\\", "<", ">")):
            raise _error(
                "INVALID_CHILD_NAME",
                field="name",
                action="provide one Wwise child name without path syntax",
            )
        resolved_kind = resolve_semantic_kind(kind, version=self.context.wwise_version)
        return NewDescendantTarget(
            parent_handle=parent_handle,
            name=normalized_name,
            kind=resolved_kind.name,
        )

    def existing_target(self, object_handle: str) -> ExistingObjectTarget:
        self.resolve_object(object_handle)
        return ExistingObjectTarget(object_handle=object_handle)

    def validate_field_value(self, field: BoundFieldHandle, value: Any) -> Any:
        if not isinstance(field, BoundFieldHandle) or self._fields.get(field.handle) != field:
            raise _error(
                "FIELD_HANDLE_NOT_AVAILABLE",
                field="field_handle",
                action="discover the field in this task and use its returned handle",
            )
        self._require_context(field.context, self.context, handle=field.handle)
        restrictions = field.restrictions
        if field.value_type == "reference":
            target = self.resolve_object(value) if isinstance(value, str) else None
            allowed = tuple(restrictions.get("allowed_target_types", ()))
            if target is None or (
                allowed
                and reference_type_token(target.object_type)
                not in {reference_type_token(item) for item in allowed}
            ):
                raise _error(
                    "REFERENCE_TARGET_TYPE_MISMATCH",
                    field=field.token,
                    rejected_handle=value if isinstance(value, str) and _OBJECT_HANDLE.fullmatch(value) else None,
                    allowed_target_types=sorted(allowed),
                    action="choose a bound object with one allowed live type",
                )
            return target.handle
        if field.value_type in {"number", "integer"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise _field_type_error(field)
            normalized = float(value)
            if not math.isfinite(normalized):
                raise _field_type_error(field)
            if field.value_type == "integer" and not normalized.is_integer():
                raise _field_type_error(field)
            minimum = restrictions.get("minimum")
            maximum = restrictions.get("maximum")
            if (minimum is not None and normalized < minimum) or (
                maximum is not None and normalized > maximum
            ):
                raise _error(
                    "FIELD_VALUE_OUT_OF_RANGE",
                    field=field.token,
                    valid_range={"minimum": minimum, "maximum": maximum},
                    action="provide a value inside the live metadata range",
                )
            normalized_value: Any = (
                int(normalized) if field.value_type == "integer" else normalized
            )
            _require_enum_choice(field, normalized_value)
            return normalized_value
        if field.value_type == "boolean":
            if type(value) is not bool:
                raise _field_type_error(field)
            _require_enum_choice(field, value)
            return value
        if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_FIELD_STRING_BYTES:
            raise _field_type_error(field)
        _require_enum_choice(field, value)
        return value

    def _new_handle(self, prefix: str, binding_digest: str) -> str:
        random_bytes = self._token_bytes(32)
        if not isinstance(random_bytes, bytes) or len(random_bytes) < 16:
            raise ValueError("token_bytes must return at least 16 random bytes")
        token = sha256_hex(random_bytes + bytes.fromhex(binding_digest))[:32]
        return f"{prefix}-{token}"

    @staticmethod
    def _require_context(
        expected: BusinessContext,
        actual: BusinessContext,
        *,
        handle: str,
    ) -> None:
        comparisons = (
            ("task_authority_digest", "HANDLE_TASK_MISMATCH"),
            ("project_id", "HANDLE_PROJECT_MISMATCH"),
            ("project_path", "HANDLE_PROJECT_MISMATCH"),
            ("wwise_version", "HANDLE_VERSION_MISMATCH"),
            ("wwise_build", "HANDLE_BUILD_MISMATCH"),
        )
        for field_name, error_code in comparisons:
            expected_value = str(getattr(expected, field_name))
            actual_value = str(getattr(actual, field_name))
            if not hmac.compare_digest(expected_value, actual_value):
                raise _error(
                    error_code,
                    field="handle",
                    rejected_handle=handle,
                    action="resolve a new handle in the current live task context",
                )


def bind_live_field(
    registry: BusinessHandleRegistry,
    *,
    read_call: ReadCall,
    scope_kind: str,
    scope_value: str | int,
    token: str,
    platform: str | int | None = None,
) -> BoundFieldHandle:
    """Issue one Field Handle from exact, bounded live metadata evidence.

    The Agent supplies the exact token selected from Gateway discovery.  This
    function proves that token in the requested scope, binds the complete
    metadata digest, and performs the dynamic enabled check whenever a
    dependency-bearing object field is bound for an explicit platform.
    """

    if not isinstance(registry, BusinessHandleRegistry):
        raise TypeError("registry must be BusinessHandleRegistry")
    if not callable(read_call):
        raise TypeError("read_call must be callable")
    normalized_scope = _normalize_scope(scope_kind, scope_value)
    if not isinstance(token, str) or not _FIELD_TOKEN.fullmatch(token):
        raise _error(
            "FIELD_TOKEN_INVALID",
            field="token",
            action="copy one exact token from live field discovery",
        )
    live_scope = _live_metadata_scope(
        read_call,
        scope_kind=scope_kind,
        scope_value=normalized_scope,
    )
    try:
        names = parse_property_and_reference_names_result(
            read_call(GET_PROPERTY_AND_REFERENCE_NAMES_URI, live_scope, {})
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            "METADATA_READBACK_INVALID",
            field="token",
            action="refresh live Wwise metadata before continuing",
        ) from exc
    exact_names = tuple(row.name for row in names)
    if token not in exact_names:
        raise _error(
            "FIELD_TOKEN_NOT_AVAILABLE",
            field="token",
            candidates=exact_names[:MAX_BUSINESS_REPAIR_ITEMS],
            action="choose one exact token returned for this live scope",
        )
    try:
        info = parse_get_property_info_result(
            read_call(
                GET_PROPERTY_INFO_URI,
                {**live_scope, "property": token},
                {},
            )
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            "METADATA_READBACK_INVALID",
            field="token",
            action="refresh live Wwise metadata before continuing",
        ) from exc
    if info.name != token:
        raise _error(
            "METADATA_READBACK_MISMATCH",
            field="token",
            candidates=(info.name,),
            action="refresh live Wwise metadata before continuing",
        )
    field_kind = (
        "reference"
        if info.type.casefold() in {"reference", "objectreference"}
        or info.restriction.get("type") == "reference"
        else "property"
    )
    value_type = (
        "reference" if field_kind == "reference" else metadata_typed_value_type(info.type)
    )
    if value_type is None:
        raise _error(
            "FIELD_TYPE_UNSUPPORTED",
            field=token,
            action="use a separately reviewed Adapter for this metadata type",
        )
    try:
        restrictions = _restrictions_from_live_metadata(
            info.restriction,
            field_kind=field_kind,
            value_type=value_type,
        )
    except MetadataRestrictionError as exc:
        raise _error(
            exc.error_code,
            field=token,
            action="use a separately reviewed Adapter for this live restriction",
        ) from exc
    dependency_fields = _dependency_field_tokens(info.dependencies)
    enabled_dependency_fields = (
        dependency_fields if field_kind == "property" else ()
    )
    if enabled_dependency_fields and scope_kind != "object":
        raise _error(
            "FIELD_OBJECT_SCOPE_REQUIRED",
            field=token,
            dependency_fields=enabled_dependency_fields,
            action="resolve the exact target object before checking this dependent field",
        )
    if enabled_dependency_fields:
        if platform is None:
            raise _error(
                "FIELD_PLATFORM_REQUIRED",
                field=token,
                dependency_fields=enabled_dependency_fields,
                action="provide the explicit platform for the dynamic enabled check",
            )
        try:
            enabled = parse_is_property_enabled_result(
                read_call(
                    IS_PROPERTY_ENABLED_URI,
                    {
                        "object": normalized_scope,
                        "property": token,
                        "platform": platform,
                    },
                    {},
                )
            ).enabled
        except (TypeError, ValueError) as exc:
            raise _error(
                "METADATA_READBACK_INVALID",
                field=token,
                action="refresh the live property-enabled state before continuing",
            ) from exc
        if not enabled:
            raise _error(
                "FIELD_DISABLED",
                field=token,
                dependency_fields=enabled_dependency_fields,
                action="satisfy the disclosed dependency state or omit this field",
            )
    metadata_digest = canonical_sha256(
        {
            "scope_kind": scope_kind,
            "scope_value": normalized_scope,
            "metadata": info.as_dict(),
        }
    )
    try:
        return registry.bind_field(
            scope_kind=scope_kind,
            scope_value=normalized_scope,
            token=token,
            field_kind=field_kind,
            value_type=value_type,
            platform=platform,
            restrictions=restrictions,
            metadata_digest=metadata_digest,
        )
    except ValueError as exc:
        raise _error(
            "INVALID_METADATA",
            field=token,
            action="refresh or repair the live Wwise metadata contract",
        ) from exc


def revalidate_live_field(
    registry: BusinessHandleRegistry,
    field: BoundFieldHandle,
    *,
    read_call: ReadCall,
    platform: str | int | None = None,
) -> BoundFieldHandle:
    """Re-read one bound field and fail closed on scope or metadata drift."""

    if not isinstance(field, BoundFieldHandle):
        raise TypeError("field must be BoundFieldHandle")
    normalized_platform = _normalize_field_platform(platform)
    if (
        normalized_platform is not None
        and field.platform is not None
        and normalized_platform != field.platform
    ):
        raise _error(
            "FIELD_HANDLE_PLATFORM_MISMATCH",
            field="field_handle",
            rejected_handle=field.handle,
            action="reuse the platform sealed into the current Field Handle",
        )
    effective_platform = (
        field.platform if normalized_platform is None else normalized_platform
    )
    live_scope = _live_metadata_scope(
        read_call,
        scope_kind=field.scope_kind,
        scope_value=field.scope_value,
    )
    try:
        names = parse_property_and_reference_names_result(
            read_call(GET_PROPERTY_AND_REFERENCE_NAMES_URI, live_scope, {})
        )
        if field.token not in {row.name for row in names}:
            raise business_repair(
                "FIELD_HANDLE_STALE",
                field="field_handle",
                rejected_handle=field.handle,
                action="refresh live metadata and use the new field handle",
            )
        info = parse_get_property_info_result(
            read_call(
                GET_PROPERTY_INFO_URI,
                {**live_scope, "property": field.token},
                {},
            )
        )
    except BusinessDeclarationError:
        raise
    except (TypeError, ValueError) as exc:
        raise _error(
            "METADATA_READBACK_INVALID",
            field="field_handle",
            action="refresh live Wwise metadata before Preview",
        ) from exc
    if info.name != field.token:
        raise _error(
            "FIELD_HANDLE_STALE",
            field="field_handle",
            rejected_handle=field.handle,
            action="refresh live metadata and use the new field handle",
        )
    dependency_fields = _dependency_field_tokens(info.dependencies)
    enabled_dependency_fields = (
        dependency_fields if field.field_kind == "property" else ()
    )
    if enabled_dependency_fields and field.scope_kind != "object":
        raise _error(
            "FIELD_OBJECT_SCOPE_REQUIRED",
            field=field.token,
            rejected_handle=field.handle,
            dependency_fields=enabled_dependency_fields,
            action="resolve an exact target object and issue a new field handle",
        )
    if enabled_dependency_fields:
        if effective_platform is None:
            raise _error(
                "FIELD_PLATFORM_REQUIRED",
                field=field.token,
                dependency_fields=enabled_dependency_fields,
                action="provide the explicit platform for Preview revalidation",
            )
        try:
            enabled = parse_is_property_enabled_result(
                read_call(
                    IS_PROPERTY_ENABLED_URI,
                    {
                        "object": field.scope_value,
                        "property": field.token,
                        "platform": effective_platform,
                    },
                    {},
                )
            ).enabled
        except (TypeError, ValueError) as exc:
            raise _error(
                "METADATA_READBACK_INVALID",
                field=field.token,
                action="refresh the live property-enabled state before Preview",
            ) from exc
        if not enabled:
            raise _error(
                "FIELD_DISABLED",
                field=field.token,
                dependency_fields=enabled_dependency_fields,
                action="satisfy the disclosed dependency state or omit this field",
            )
    metadata_digest = canonical_sha256(
        {
            "scope_kind": field.scope_kind,
            "scope_value": field.scope_value,
            "metadata": info.as_dict(),
        }
    )
    return registry.resolve_field(
        field.handle,
        scope_kind=field.scope_kind,
        scope_value=field.scope_value,
        metadata_digest=metadata_digest,
    )


def revalidate_live_object(
    registry: BusinessHandleRegistry,
    bound: BoundObjectHandle,
    *,
    read_call: ReadCall,
) -> BoundObjectHandle:
    """Re-read one bound object by GUID and require its exact sealed quartet."""

    return revalidate_live_objects(registry, (bound,), read_call=read_call)[0]


def bound_object_identity_for_handle(
    registry: BusinessHandleRegistry,
    handle: str,
    *,
    field: str,
    action: str,
) -> dict[str, str]:
    """Resolve one opaque object handle into the internal closed ID selector."""

    try:
        bound = registry.resolve_object(handle)
    except BusinessDeclarationError as exc:
        repair = dict(exc.repair)
        repair["field"] = field
        repair["action"] = action
        raise BusinessDeclarationError(repair) from exc
    except Exception as exc:
        raise business_repair(
            "OBJECT_HANDLE_NOT_AVAILABLE",
            field=field,
            action=action,
        ) from exc
    return {"kind": "id", "value": bound.object_id}


def revalidate_live_types(
    registry: BusinessHandleRegistry,
    bounds: Sequence[BoundTypeHandle],
    *,
    read_call: ReadCall,
) -> tuple[BoundTypeHandle, ...]:
    """Re-read one bounded type catalog and require every sealed row exactly."""

    if not isinstance(registry, BusinessHandleRegistry):
        raise TypeError("registry must be BusinessHandleRegistry")
    if (
        not isinstance(bounds, Sequence)
        or isinstance(bounds, (str, bytes))
        or any(not isinstance(bound, BoundTypeHandle) for bound in bounds)
    ):
        raise TypeError("bounds must be a sequence of BoundTypeHandle values")
    if not bounds:
        return ()
    try:
        rows = parse_get_types_result(read_call(GET_TYPES_URI, {}, {}))
    except (TypeError, ValueError) as exc:
        raise _error(
            "METADATA_READBACK_INVALID",
            field="kind_handle",
            action="refresh live Wwise type discovery before Preview",
        ) from exc
    live_digest = canonical_sha256(
        {"return": [row.as_dict() for row in rows]}
    )
    for bound in bounds:
        registry.resolve_type(bound.handle)
        matches = [
            row
            for row in rows
            if row.class_id == bound.class_id
            and row.name == bound.name
            and row.type == bound.type_category
        ]
        if (
            len(matches) != 1
            or not hmac.compare_digest(
                live_digest,
                bound.catalog_digest,
            )
        ):
            raise _error(
                "TYPE_HANDLE_STALE",
                field="kind_handle",
                rejected_handle=bound.handle,
                action="repeat live type discovery and use the new handle",
            )
    return tuple(bounds)


def revalidate_live_objects(
    registry: BusinessHandleRegistry,
    bounds: Sequence[BoundObjectHandle],
    *,
    read_call: ReadCall,
) -> tuple[BoundObjectHandle, ...]:
    """Re-read one deduplicated bounded GUID set and require every sealed row."""

    if not isinstance(registry, BusinessHandleRegistry):
        raise TypeError("registry must be BusinessHandleRegistry")
    if (
        not isinstance(bounds, Sequence)
        or isinstance(bounds, (str, bytes))
        or any(not isinstance(bound, BoundObjectHandle) for bound in bounds)
    ):
        raise TypeError("bounds must be a sequence of BoundObjectHandle values")
    if not bounds:
        return ()
    unique_ids = list(dict.fromkeys(bound.object_id for bound in bounds))
    if len(unique_ids) > MULTI_IDENTITY_READ_MAX_IDS:
        raise _error(
            "OBJECT_READ_LIMIT_EXCEEDED",
            field="object_handle",
            actual_count=len(unique_ids),
            limit=MULTI_IDENTITY_READ_MAX_IDS,
            action="reduce the exact bound object set before Preview",
        )
    try:
        return_fields = ["id", "name", "type", "path"]
        if any(bound.semantic_kind is not None for bound in bounds):
            return_fields.append("@IsVoice")
        payload = read_call(
            "ak.wwise.core.object.get",
            {"from": {"id": unique_ids}},
            {"return": return_fields},
        )
        if not isinstance(payload, Mapping):
            raise ValueError("object readback is not a JSON object")
        rows = payload.get("return")
        if not isinstance(rows, list) or len(rows) > MULTI_IDENTITY_READ_MAX_IDS:
            raise ValueError("object readback exceeds its bounded row contract")
        expected_ids = set(unique_ids)
        rows_by_id: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("object readback row is not an object")
            object_id = row.get("id")
            if not isinstance(object_id, str) or not _CANONICAL_GUID.fullmatch(object_id):
                raise ValueError("object readback row has no canonical GUID")
            canonical_id = object_id.upper()
            if (
                canonical_id not in expected_ids
                and len(unique_ids) == 1
                and len(rows) == 1
            ):
                raise _error(
                    "OBJECT_HANDLE_STALE",
                    field="object_handle",
                    rejected_handle=bounds[0].handle,
                    action="resolve the exact live object again before Preview",
                )
            if canonical_id not in expected_ids or canonical_id in rows_by_id:
                raise ValueError("object readback contains an extra or duplicate GUID")
            rows_by_id[canonical_id] = row
        if set(rows_by_id) != expected_ids:
            raise ValueError("object readback is missing one or more exact GUIDs")
    except BusinessDeclarationError:
        raise
    except (TypeError, ValueError) as exc:
        raise _error(
            "OBJECT_READBACK_INVALID",
            field="object_handle",
            action="resolve the exact live object again before Preview",
        ) from exc
    result: list[BoundObjectHandle] = []
    for bound in bounds:
        row = rows_by_id[bound.object_id]
        live = {
            "id": str(row.get("id", "")).upper(),
            "name": row.get("name"),
            "type": row.get("type"),
            "path": row.get("path"),
        }
        if bound.semantic_kind is not None:
            is_voice = row.get("@IsVoice")
            if type(is_voice) is not bool:
                raise _error(
                    "OBJECT_READBACK_INVALID",
                    field="object_handle",
                    rejected_handle=bound.handle,
                    action="resolve the exact live object again before Preview",
                )
            live["semantic_kind"] = "sound-voice" if is_voice else "sound-sfx"
        expected = {
            "id": bound.object_id,
            "name": bound.name,
            "type": bound.object_type,
            "path": bound.path,
        }
        if bound.semantic_kind is not None:
            expected["semantic_kind"] = bound.semantic_kind
        if live != expected:
            raise _error(
                "OBJECT_HANDLE_STALE",
                field="object_handle",
                rejected_handle=bound.handle,
                action="resolve the exact live object again before Preview",
            )
        result.append(registry.resolve_object(bound.handle))
    return tuple(result)


def normalize_common_business_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize stable unit-bearing fields while preserving exact omission."""

    if not isinstance(fields, Mapping):
        raise business_repair(
            "BUSINESS_FIELDS_INVALID",
            field="fields",
            action="provide one object of disclosed business fields",
        )
    unknown = sorted(
        name for name in fields if not isinstance(name, str) or name not in COMMON_BUSINESS_FIELDS
    )
    if unknown:
        raise business_repair(
            "BUSINESS_FIELD_UNAVAILABLE",
            field="fields",
            choices=COMMON_BUSINESS_FIELDS,
            action="use stable fields with explicit units or a live Field Handle",
        )
    normalized: dict[str, Any] = {}
    for name, value in fields.items():
        if name in {"volume_db", "fade_time_ms", "delay_ms"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise _common_field_type_error(name, "finite number")
            number = float(value)
            if not math.isfinite(number):
                raise _common_field_type_error(name, "finite number")
            if name == "volume_db" and not -200.0 <= number <= 200.0:
                raise _error(
                    "FIELD_VALUE_OUT_OF_RANGE",
                    field=name,
                    valid_range={"minimum": -200.0, "maximum": 200.0},
                    action="provide decibels inside the stable business range",
                )
            if name != "volume_db" and number < 0:
                raise _error(
                    "FIELD_VALUE_OUT_OF_RANGE",
                    field=name,
                    valid_range={"minimum": 0.0, "maximum": None},
                    action="provide a non-negative millisecond value",
                )
            normalized[name] = number
        elif name == "max_instances":
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= 1_000_000
            ):
                raise _error(
                    "FIELD_VALUE_OUT_OF_RANGE",
                    field=name,
                    valid_range={"minimum": 1, "maximum": 1_000_000},
                    action="provide a positive bounded instance count",
                )
            normalized[name] = value
        elif name == "loop":
            if value != "infinite":
                raise _error(
                    "FIELD_VALUE_UNAVAILABLE",
                    field=name,
                    choices=("infinite",),
                    action="choose the disclosed loop mode or omit the field",
                )
            normalized[name] = value
        else:
            if not isinstance(value, str) or not _OBJECT_HANDLE.fullmatch(value):
                raise _common_field_type_error(name, "bound object handle")
            normalized[name] = value
    return dict(sorted(normalized.items()))


def _common_field_type_error(
    field: str,
    expected: str,
) -> BusinessDeclarationError:
    return _error(
        "FIELD_VALUE_TYPE_MISMATCH",
        field=field,
        expected_type=expected,
        action="provide the disclosed business value type",
    )


def _live_metadata_scope(
    read_call: ReadCall,
    *,
    scope_kind: str,
    scope_value: str | int,
) -> dict[str, Any]:
    if scope_kind == "object":
        return {"object": scope_value}
    if isinstance(scope_value, int):
        return {"classId": scope_value}
    try:
        types = parse_get_types_result(read_call(GET_TYPES_URI, {}, {}))
    except (TypeError, ValueError) as exc:
        raise _error(
            "METADATA_READBACK_INVALID",
            field="scope",
            action="refresh live Wwise type metadata before continuing",
        ) from exc
    matches = tuple(
        row for row in types if scope_value in {row.name, row.type}
    )
    if len(matches) != 1:
        raise _error(
            "FIELD_SCOPE_NOT_AVAILABLE",
            field="scope",
            candidates=tuple(row.name for row in types[:MAX_BUSINESS_REPAIR_ITEMS]),
            action="choose one exact live metadata class",
        )
    return {"classId": matches[0].class_id}


def _restrictions_from_live_metadata(
    restriction: Mapping[str, Any],
    *,
    field_kind: str,
    value_type: str,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    if restriction.get("type") == "range":
        if "min" in restriction:
            normalized["minimum"] = restriction["min"]
        if "max" in restriction:
            normalized["maximum"] = restriction["max"]
    if restriction.get("type") == "enum":
        raw_values = restriction.get("values")
        if (
            not isinstance(raw_values, list)
            or not raw_values
            or any(not isinstance(row, Mapping) or "value" not in row for row in raw_values)
        ):
            raise MetadataRestrictionError(
                "INVALID_METADATA",
                "Enum restriction values must be a non-empty array of value rows.",
            )
        normalized["enum_choices"] = [row["value"] for row in raw_values]
    if field_kind == "reference":
        allowed = reference_allowed_types(restriction)
        if allowed:
            normalized["allowed_target_types"] = list(allowed)
    return normalized


def _dependency_field_tokens(
    dependencies: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    values = {
        value
        for dependency in dependencies
        for value in (dependency.get("property"), dependency.get("reference"))
        if isinstance(value, str) and value
    }
    return tuple(sorted(values))


def _normalize_scope(scope_kind: str, scope_value: str | int) -> str | int:
    if scope_kind not in {"object", "class"}:
        raise ValueError("scope_kind must be object or class")
    if scope_kind == "class":
        if isinstance(scope_value, bool) or not isinstance(scope_value, (str, int)):
            raise ValueError("class scope must be an exact type name or uint32 class id")
        if isinstance(scope_value, int):
            if not 0 <= scope_value <= 0xFFFFFFFF:
                raise ValueError("class scope id must be uint32")
            return scope_value
        return _bounded_required_text(
            scope_value, field="scope_value", maximum_bytes=MAX_FIELD_TOKEN_BYTES
        )
    if not isinstance(scope_value, str) or not (
        _CANONICAL_GUID.fullmatch(scope_value) or scope_value.startswith("\\")
    ):
        raise ValueError("object scope must be an exact GUID or absolute Wwise path")
    return scope_value.upper() if _CANONICAL_GUID.fullmatch(scope_value) else scope_value


def _normalize_field_platform(value: Any) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("field platform must be an exact name, id, or omission")
    if isinstance(value, int):
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("field platform id must be uint32")
        return value
    return _bounded_required_text(
        value,
        field="platform",
        maximum_bytes=MAX_FIELD_TOKEN_BYTES,
    )


def _bound_object_from_dict(
    payload: Any,
    *,
    context: BusinessContext,
) -> BoundObjectHandle:
    expected = {
        "contract",
        "handle",
        "object_id",
        "name",
        "object_type",
        "path",
        "semantic_kind",
        "binding_digest",
    }
    if (
        not isinstance(payload, Mapping)
        or set(payload) not in (expected, {*expected, "role"})
    ):
        raise ValueError("bound object handle fields are invalid")
    handle = payload.get("handle")
    object_id = payload.get("object_id")
    digest = payload.get("binding_digest")
    if payload.get("contract") != BOUND_OBJECT_HANDLE_CONTRACT:
        raise ValueError("bound object handle contract is invalid")
    if not isinstance(handle, str) or not _OBJECT_HANDLE.fullmatch(handle):
        raise ValueError("bound object handle token is invalid")
    if not isinstance(object_id, str) or not _CANONICAL_GUID.fullmatch(object_id):
        raise ValueError("bound object id is invalid")
    name = _bounded_required_text(
        payload.get("name"), field="name", maximum_bytes=MAX_BUSINESS_NAME_BYTES
    )
    object_type = _bounded_required_text(
        payload.get("object_type"),
        field="object_type",
        maximum_bytes=MAX_FIELD_TOKEN_BYTES,
    )
    semantic_kind = payload.get("semantic_kind")
    if semantic_kind is not None:
        if semantic_kind not in {"sound-sfx", "sound-voice"}:
            raise ValueError("bound object semantic kind is invalid")
        if _type_token(object_type) != "sound":
            raise ValueError("bound object semantic kind requires a Sound")
    role = payload.get("role")
    if role is not None:
        role = _bounded_required_text(
            role,
            field="role",
            maximum_bytes=MAX_FIELD_TOKEN_BYTES,
        )
    path = _bounded_required_text(
        payload.get("path"), field="path", maximum_bytes=MAX_BUSINESS_PATH_BYTES
    )
    if not path.startswith("\\") or path.endswith("\\"):
        raise ValueError("bound object path is invalid")
    material = {
        "contract": BOUND_OBJECT_HANDLE_CONTRACT,
        "context": context.as_binding_dict(),
        "object_id": object_id.upper(),
        "name": name,
        "object_type": object_type,
        "path": path,
        "semantic_kind": semantic_kind,
        **({} if role is None else {"role": role}),
    }
    expected_digest = canonical_sha256(material)
    if (
        not isinstance(digest, str)
        or not _SHA256.fullmatch(digest)
        or not hmac.compare_digest(digest, expected_digest)
    ):
        raise ValueError("bound object binding digest is invalid")
    return BoundObjectHandle(
        handle=handle,
        context=context,
        object_id=object_id.upper(),
        name=name,
        object_type=object_type,
        path=path,
        semantic_kind=semantic_kind,
        role=role,
        binding_digest=digest,
    )


def _bound_field_from_dict(
    payload: Any,
    *,
    context: BusinessContext,
) -> BoundFieldHandle:
    expected = {
        "contract",
        "handle",
        "scope_kind",
        "scope_value",
        "token",
        "field_kind",
        "value_type",
        "platform",
        "restrictions",
        "metadata_digest",
        "binding_digest",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("bound field handle fields are invalid")
    if payload.get("contract") != BOUND_FIELD_HANDLE_CONTRACT:
        raise ValueError("bound field handle contract is invalid")
    handle = payload.get("handle")
    if not isinstance(handle, str) or not _FIELD_HANDLE.fullmatch(handle):
        raise ValueError("bound field handle token is invalid")
    scope_kind = payload.get("scope_kind")
    if not isinstance(scope_kind, str):
        raise ValueError("bound field scope kind is invalid")
    scope_value = _normalize_scope(scope_kind, payload.get("scope_value"))
    token = payload.get("token")
    field_kind = payload.get("field_kind")
    value_type = payload.get("value_type")
    platform = _normalize_field_platform(payload.get("platform"))
    metadata_digest = payload.get("metadata_digest")
    if not isinstance(token, str) or not _FIELD_TOKEN.fullmatch(token):
        raise ValueError("bound field token is invalid")
    if field_kind not in {"property", "reference"} or value_type not in {
        "number",
        "integer",
        "boolean",
        "string",
        "reference",
    }:
        raise ValueError("bound field kind or value type is invalid")
    if (field_kind == "reference") != (value_type == "reference"):
        raise ValueError("bound field kind and value type disagree")
    if not isinstance(metadata_digest, str) or not _SHA256.fullmatch(metadata_digest):
        raise ValueError("bound field metadata digest is invalid")
    restrictions = _normalize_restrictions(
        payload.get("restrictions"),
        field_kind=str(field_kind),
        value_type=str(value_type),
    )
    material = {
        "contract": BOUND_FIELD_HANDLE_CONTRACT,
        "context": context.as_binding_dict(),
        "scope_kind": scope_kind,
        "scope_value": scope_value,
        "token": token,
        "field_kind": field_kind,
        "value_type": value_type,
        "platform": platform,
        "restrictions": restrictions,
        "metadata_digest": metadata_digest,
    }
    expected_digest = canonical_sha256(material)
    digest = payload.get("binding_digest")
    if (
        not isinstance(digest, str)
        or not _SHA256.fullmatch(digest)
        or not hmac.compare_digest(digest, expected_digest)
    ):
        raise ValueError("bound field binding digest is invalid")
    return BoundFieldHandle(
        handle=handle,
        context=context,
        scope_kind=scope_kind,
        scope_value=scope_value,
        token=token,
        field_kind=str(field_kind),
        value_type=str(value_type),
        platform=platform,
        restrictions=restrictions,
        metadata_digest=metadata_digest,
        binding_digest=digest,
    )


def _bound_type_from_dict(
    payload: Any,
    *,
    context: BusinessContext,
) -> BoundTypeHandle:
    expected = {
        "contract",
        "handle",
        "class_id",
        "name",
        "type_category",
        "catalog_digest",
        "binding_digest",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("bound type handle fields are invalid")
    if payload.get("contract") != BOUND_TYPE_HANDLE_CONTRACT:
        raise ValueError("bound type handle contract is invalid")
    handle = payload.get("handle")
    class_id = payload.get("class_id")
    catalog_digest = payload.get("catalog_digest")
    if not isinstance(handle, str) or not _TYPE_HANDLE.fullmatch(handle):
        raise ValueError("bound type handle token is invalid")
    if (
        isinstance(class_id, bool)
        or not isinstance(class_id, int)
        or not 0 <= class_id <= 0xFFFFFFFF
    ):
        raise ValueError("bound type class id is invalid")
    name = _bounded_required_text(
        payload.get("name"), field="name", maximum_bytes=MAX_BUSINESS_NAME_BYTES
    )
    type_category = _bounded_required_text(
        payload.get("type_category"),
        field="type_category",
        maximum_bytes=MAX_FIELD_TOKEN_BYTES,
    )
    if not isinstance(catalog_digest, str) or not _SHA256.fullmatch(
        catalog_digest
    ):
        raise ValueError("bound type catalog digest is invalid")
    material = {
        "contract": BOUND_TYPE_HANDLE_CONTRACT,
        "context": context.as_binding_dict(),
        "class_id": class_id,
        "name": name,
        "type_category": type_category,
        "catalog_digest": catalog_digest,
    }
    expected_digest = canonical_sha256(material)
    digest = payload.get("binding_digest")
    if (
        not isinstance(digest, str)
        or not _SHA256.fullmatch(digest)
        or not hmac.compare_digest(digest, expected_digest)
    ):
        raise ValueError("bound type binding digest is invalid")
    return BoundTypeHandle(
        handle=handle,
        context=context,
        class_id=class_id,
        name=name,
        type_category=type_category,
        catalog_digest=catalog_digest,
        binding_digest=digest,
    )


def _normalize_restrictions(
    restrictions: Mapping[str, Any],
    *,
    field_kind: str,
    value_type: str,
) -> dict[str, Any]:
    if not isinstance(restrictions, Mapping):
        raise ValueError("restrictions must be an object")
    allowed_keys = {"minimum", "maximum", "enum_choices", "allowed_target_types"}
    if set(restrictions) - allowed_keys:
        raise ValueError("restrictions contain unsupported fields")
    normalized: dict[str, Any] = {}
    for key in ("minimum", "maximum"):
        if key in restrictions:
            raw = restrictions[key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError(f"{key} must be a finite number")
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError(f"{key} must be a finite number")
            normalized[key] = value
    if (
        normalized.get("minimum") is not None
        and normalized.get("maximum") is not None
        and normalized["minimum"] > normalized["maximum"]
    ):
        raise ValueError("minimum cannot exceed maximum")
    if value_type not in {"number", "integer"} and {
        "minimum",
        "maximum",
    } & normalized.keys():
        raise ValueError("only numeric fields accept a range")
    if "enum_choices" in restrictions:
        choices = _normalized_enum_choices(
            restrictions["enum_choices"],
            value_type=value_type,
        )
        normalized["enum_choices"] = list(choices)
    if "allowed_target_types" in restrictions:
        target_types = _normalized_text_sequence(
            restrictions["allowed_target_types"],
            field="allowed_target_types",
            maximum_items=MAX_REFERENCE_TARGET_TYPES,
        )
        if field_kind != "reference":
            raise ValueError("allowed target types require a reference field")
        normalized["allowed_target_types"] = sorted(target_types)
    if field_kind == "property" and "allowed_target_types" in normalized:
        raise ValueError("property fields cannot bind reference target types")
    return dict(sorted(normalized.items()))


def _normalized_text_sequence(
    value: Any,
    *,
    field: str,
    maximum_items: int,
) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
        or len(value) > maximum_items
    ):
        raise ValueError(f"{field} must be a non-empty bounded array")
    rows = tuple(
        _bounded_required_text(item, field=field, maximum_bytes=MAX_FIELD_TOKEN_BYTES)
        for item in value
    )
    if len(set(rows)) != len(rows):
        raise ValueError(f"{field} must not contain duplicates")
    return rows


def _normalized_enum_choices(
    value: Any,
    *,
    value_type: str,
) -> tuple[Any, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
        or len(value) > MAX_FIELD_ENUM_CHOICES
    ):
        raise ValueError("enum_choices must be a non-empty bounded array")
    rows: list[Any] = []
    for item in value:
        if value_type == "string":
            normalized = _bounded_required_text(
                item,
                field="enum_choices",
                maximum_bytes=MAX_FIELD_TOKEN_BYTES,
            )
        elif value_type == "boolean":
            if type(item) is not bool:
                raise ValueError("boolean enum choices must be booleans")
            normalized = item
        elif value_type in {"number", "integer"}:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ValueError("numeric enum choices must be numbers")
            number = float(item)
            if not math.isfinite(number) or (
                value_type == "integer" and not number.is_integer()
            ):
                raise ValueError("numeric enum choices must match their field type")
            normalized = int(number) if value_type == "integer" else number
        else:
            raise ValueError("reference fields cannot use enum choices")
        rows.append(normalized)
    digests = tuple(canonical_sha256(item) for item in rows)
    if len(set(digests)) != len(digests):
        raise ValueError("enum choices must not contain duplicates")
    return tuple(rows)


def _require_enum_choice(field: BoundFieldHandle, value: Any) -> None:
    choices = field.restrictions.get("enum_choices")
    if choices is not None and value not in choices:
        raise _error(
            "FIELD_VALUE_UNAVAILABLE",
            field=field.token,
            choices=choices,
            action="choose one exact live metadata value",
        )


def _field_type_error(field: BoundFieldHandle) -> BusinessDeclarationError:
    return _error(
        "FIELD_VALUE_TYPE_MISMATCH",
        field=field.token,
        expected_type=field.value_type,
        action="provide a value with the live metadata type",
    )


def _error(
    error_code: str,
    *,
    field: str,
    action: str,
    draft_revision: int | None = None,
    **details: Any,
) -> BusinessDeclarationError:
    payload: dict[str, Any] = {
        "contract": BUSINESS_REPAIR_CONTRACT,
        "error_code": _bounded_required_text(
            error_code, field="error_code", maximum_bytes=128
        ),
        "field": _bounded_required_text(field, field="field", maximum_bytes=256),
    }
    if draft_revision is not None:
        if (
            isinstance(draft_revision, bool)
            or not isinstance(draft_revision, int)
            or draft_revision < 0
        ):
            raise ValueError("draft_revision must be a non-negative integer")
        payload["draft_revision"] = draft_revision
    payload["draft_changed"] = False
    payload.update(_bounded_repair_details(details))
    payload["action"] = _bounded_required_text(
        action, field="action", maximum_bytes=MAX_BUSINESS_REPAIR_TEXT_BYTES
    )
    if len(canonical_json_bytes(payload)) > MAX_BUSINESS_REPAIR_BYTES:
        payload = {
            "contract": BUSINESS_REPAIR_CONTRACT,
            "error_code": payload["error_code"],
            "field": payload["field"],
            "draft_changed": False,
            "action": payload["action"],
        }
    return BusinessDeclarationError(payload)


def _bounded_repair_details(details: Mapping[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key, value in details.items():
        if value is None:
            continue
        if isinstance(value, str):
            if len(value.encode("utf-8")) <= MAX_BUSINESS_REPAIR_TEXT_BYTES:
                bounded[key] = value
            continue
        if isinstance(value, (bool, int, float)):
            bounded[key] = value
            continue
        if isinstance(value, Mapping):
            row = _bounded_repair_details(value)
            if len(canonical_json_bytes(row)) <= MAX_BUSINESS_REPAIR_BYTES // 2:
                bounded[key] = row
            continue
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            rows: list[Any] = []
            for item in value[:MAX_BUSINESS_REPAIR_ITEMS]:
                if isinstance(item, str) and len(item.encode("utf-8")) <= MAX_BUSINESS_REPAIR_TEXT_BYTES:
                    rows.append(item)
                elif isinstance(item, (bool, int, float)):
                    rows.append(item)
            bounded[key] = rows
    return bounded


def _required_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be non-empty text without outer whitespace")
    return value


def _bounded_required_text(value: Any, *, field: str, maximum_bytes: int) -> str:
    normalized = _required_text(value, field=field)
    if len(normalized.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{field} exceeds its fixed byte limit")
    return normalized


def _type_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


__all__ = [
    "BOUND_FIELD_HANDLE_CONTRACT",
    "BOUND_OBJECT_HANDLE_CONTRACT",
    "BOUND_TYPE_HANDLE_CONTRACT",
    "BUSINESS_CONTEXT_CONTRACT",
    "BUSINESS_KIND_CONTRACT",
    "BUSINESS_REPAIR_CONTRACT",
    "COMMON_BUSINESS_FIELDS",
    "BoundFieldHandle",
    "BoundObjectHandle",
    "BoundTypeHandle",
    "BusinessContext",
    "BusinessDeclarationError",
    "BusinessHandleRegistry",
    "ExistingObjectTarget",
    "MAX_BUSINESS_REPAIR_BYTES",
    "NewDescendantTarget",
    "SUPPORTED_BUSINESS_KINDS",
    "SUPPORTED_WWISE_VERSIONS",
    "SemanticKind",
    "bind_live_field",
    "bound_object_identity_for_handle",
    "business_repair",
    "normalize_common_business_fields",
    "revalidate_live_field",
    "revalidate_live_object",
    "revalidate_live_objects",
    "revalidate_live_types",
    "repair_at_draft_revision",
    "resolve_semantic_kind",
]
