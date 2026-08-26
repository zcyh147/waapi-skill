"""Closed, pure request structures for ``object.create`` and ``object.set``.

This module deliberately knows nothing about a live Wwise connection.  It
normalizes the small public object-tree DSL, rejects native WAAPI escape
hatches, and supplies deterministic request/result topology helpers.  The
operation registry remains responsible for resolving identities, consulting
live type/property metadata, taking pre-state snapshots, dispatching exactly
once, and verifying the resulting Wwise state.

Callers must never pass raw ``children`` objects or caller-authored ``@Field``
keys directly to WAAPI.  ``materialize_waapi_node`` is the sole conversion
helper: it creates those dynamic keys from already-normalized descriptors and
already-resolved reference identities.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from .canonical import canonical_json_bytes


JsonScalar = str | int | float | bool
ObjectId = str | int

DEFAULT_MAX_DEPTH = 8
DEFAULT_MAX_NODES = 128
DEFAULT_MAX_CHILDREN_PER_NODE = 32
DEFAULT_MAX_FIELDS_PER_NODE = 32
DEFAULT_MAX_REQUEST_BYTES = 256 * 1024
DEFAULT_MAX_NAME_LENGTH = 255
DEFAULT_MAX_TYPE_LENGTH = 128
DEFAULT_MAX_IDENTITY_PARENT_LITERAL_LENGTH = 4096
DEFAULT_MAX_FIELD_NAME_LENGTH = 128
DEFAULT_MAX_NOTES_LENGTH = 64 * 1024
DEFAULT_MAX_RTPCS = 32
DEFAULT_MAX_RTPC_POINTS = 256
DEFAULT_MAX_IMPORT_FILES = 16

NODE_FIELDS = frozenset({"type", "name", "notes", "properties", "references", "children"})
OBJECT_SET_NODE_FIELDS = NODE_FIELDS | {"platform", "language", "import"}
LIST_FIELDS = frozenset({"name", "objects"})
PROPERTY_FIELDS = frozenset({"name", "value"})
REFERENCE_FIELDS = frozenset({"name", "target"})
IMPORT_FIELDS = frozenset({"files"})
IMPORT_OPTIONAL_FIELDS = frozenset({"auto_add_to_source_control"})
IMPORT_FILE_OPTIONAL_FIELDS = frozenset(
    {
        "audio_file",
        "audio_file_base64",
        "originals_subfolder",
        "language",
        "object_type",
    }
)
RTPC_FIELDS = frozenset({"property", "control_input", "points"})
RTPC_OPTIONAL_FIELDS = frozenset({"notes"})
RTPC_POINT_FIELDS = frozenset({"x", "y", "shape"})
RTPC_POINT_SHAPES = frozenset(
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
IDENTITY_KINDS = frozenset(
    {"id", "path", "exact-type-name", "direct-child", "scoped-name"}
)
_DYNAMIC_FIELD_NAME = re.compile(r"^[:_a-zA-Z0-9]+$")
_EXACT_TYPE_NAME_TYPE_TOKEN = re.compile(r"^[A-Za-z0-9_.]+$")


class ObjectOperationContractError(ValueError):
    """A public object-operation document is not closed or safely bounded."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "details": dict(self.details),
        }


class ObjectConflictPolicy(str, Enum):
    FAIL = "fail"
    RENAME = "rename"
    MERGE = "merge"
    REPLACE = "replace"


@dataclass(frozen=True, slots=True)
class ObjectTreeLimits:
    """Resource ceilings for one normalized object-tree request."""

    max_depth: int = DEFAULT_MAX_DEPTH
    max_nodes: int = DEFAULT_MAX_NODES
    max_children_per_node: int = DEFAULT_MAX_CHILDREN_PER_NODE
    max_fields_per_node: int = DEFAULT_MAX_FIELDS_PER_NODE
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    max_name_length: int = DEFAULT_MAX_NAME_LENGTH
    max_type_length: int = DEFAULT_MAX_TYPE_LENGTH
    max_field_name_length: int = DEFAULT_MAX_FIELD_NAME_LENGTH
    max_notes_length: int = DEFAULT_MAX_NOTES_LENGTH

    def __post_init__(self) -> None:
        for field_name in (
            "max_depth",
            "max_nodes",
            "max_children_per_node",
            "max_fields_per_node",
            "max_request_bytes",
            "max_name_length",
            "max_type_length",
            "max_field_name_length",
            "max_notes_length",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"ObjectTreeLimits.{field_name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class ConflictPolicyRequirements:
    policy: str
    requires_absence_guard: bool
    requires_collision_snapshot: bool
    requires_owned_collision: bool
    can_delete_preexisting_objects: bool
    cleanup_boundary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "requires_absence_guard": self.requires_absence_guard,
            "requires_collision_snapshot": self.requires_collision_snapshot,
            "requires_owned_collision": self.requires_owned_collision,
            "can_delete_preexisting_objects": self.can_delete_preexisting_objects,
            "cleanup_boundary": self.cleanup_boundary,
        }


@dataclass(frozen=True, slots=True)
class ObjectIdentityDescriptor:
    """Unresolved public identity; live code must still prove one exact row."""

    kind: str
    value: ObjectId | None = None
    name: str | None = None
    type: str | None = None
    parent: ObjectIdentityDescriptor | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.kind == "exact-type-name":
            assert self.name is not None and self.type is not None
            return {
                "kind": self.kind,
                "type": self.type,
                "name": self.name,
            }
        if self.kind == "direct-child":
            assert self.type is not None and self.parent is not None
            return {
                "kind": self.kind,
                "parent": self.parent.as_dict(),
                "type": self.type,
            }
        if self.kind == "scoped-name":
            assert self.name is not None and self.type is not None and self.parent is not None
            return {
                "kind": self.kind,
                "name": self.name,
                "type": self.type,
                "parent": self.parent.as_dict(),
            }
        return {"kind": self.kind, "value": self.value}


@dataclass(frozen=True, slots=True)
class ObjectPropertyDescriptor:
    request_path: str
    name: str
    value: JsonScalar

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True, slots=True)
class ObjectReferenceDescriptor:
    request_path: str
    name: str
    target: ObjectIdentityDescriptor

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "target": self.target.as_dict()}


@dataclass(frozen=True, slots=True)
class ObjectImportFileDescriptor:
    """One closed native ``object.set`` import file before filesystem proof."""

    request_path: str
    audio_file: str | None
    audio_file_base64: str | None
    originals_subfolder: str | None
    language: str | None
    object_type: str | None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.audio_file is not None:
            result["audio_file"] = self.audio_file
        if self.audio_file_base64 is not None:
            result["audio_file_base64"] = self.audio_file_base64
        if self.originals_subfolder is not None:
            result["originals_subfolder"] = self.originals_subfolder
        if self.language is not None:
            result["language"] = self.language
        if self.object_type is not None:
            result["object_type"] = self.object_type
        return result


@dataclass(frozen=True, slots=True)
class ObjectImportDescriptor:
    """Closed ``importArg`` subset supported by Wwise 2023.1 and newer."""

    request_path: str
    files: tuple[ObjectImportFileDescriptor, ...]
    auto_add_to_source_control: bool | None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "files": [item.as_dict() for item in self.files]
        }
        if self.auto_add_to_source_control is not None:
            result["auto_add_to_source_control"] = self.auto_add_to_source_control
        return result


@dataclass(frozen=True, slots=True)
class RtpcCurvePoint:
    x: int | float
    y: int | float
    shape: str

    def as_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "shape": self.shape}


@dataclass(frozen=True, slots=True)
class RtpcDescriptor:
    """One closed RTPC request before live ControlInput resolution."""

    request_path: str
    property: str
    control_input: ObjectIdentityDescriptor
    points: tuple[RtpcCurvePoint, ...]
    notes: str | None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "property": self.property,
            "control_input": self.control_input.as_dict(),
            "points": [point.as_dict() for point in self.points],
        }
        if self.notes is not None:
            result["notes"] = self.notes
        return result


@dataclass(frozen=True, slots=True)
class ObjectNodeDescriptor:
    """One normalized node in a request-relative recursive object tree."""

    request_path: str
    parent_request_path: str | None
    type: str
    name: str
    notes: str | None
    platform: str | None
    language: str | None
    import_arg: ObjectImportDescriptor | None
    properties: tuple[ObjectPropertyDescriptor, ...]
    references: tuple[ObjectReferenceDescriptor, ...]
    children: tuple[ObjectNodeDescriptor, ...]

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type, "name": self.name}
        if self.notes is not None:
            result["notes"] = self.notes
        if self.platform is not None:
            result["platform"] = self.platform
        if self.language is not None:
            result["language"] = self.language
        if self.import_arg is not None:
            result["import"] = self.import_arg.as_dict()
        if self.properties:
            result["properties"] = [item.as_dict() for item in self.properties]
        if self.references:
            result["references"] = [item.as_dict() for item in self.references]
        if self.children:
            result["children"] = [item.as_dict() for item in self.children]
        return result


@dataclass(frozen=True, slots=True)
class ObjectListDescriptor:
    """One closed native object-list assignment for an existing owner."""

    request_path: str
    name: str
    objects: tuple[ObjectNodeDescriptor, ...]
    nodes: tuple[ObjectNodeDescriptor, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "objects": [item.as_dict() for item in self.objects],
        }


@dataclass(frozen=True, slots=True)
class NormalizedObjectTree:
    root: ObjectNodeDescriptor
    nodes: tuple[ObjectNodeDescriptor, ...]
    on_name_conflict: str
    request_size_bytes: int


@dataclass(frozen=True, slots=True)
class NormalizedObjectForest:
    roots: tuple[ObjectNodeDescriptor, ...]
    nodes: tuple[ObjectNodeDescriptor, ...]
    on_name_conflict: str
    request_size_bytes: int


@dataclass(frozen=True, slots=True)
class ObjectTopologyEdge:
    parent_request_path: str
    child_request_path: str


@dataclass(frozen=True, slots=True)
class ObjectResultNode:
    request_path: str
    parent_request_path: str | None
    object: ObjectId
    name: str
    child_count: int
    collection: str | None = None


@dataclass(frozen=True, slots=True)
class ObjectResultBinding:
    request_path: str
    requested_type: str
    requested_name: str
    object: ObjectId
    actual_name: str


def normalize_conflict_policy(
    value: str | ObjectConflictPolicy,
    *,
    replace_owned: bool = False,
) -> str:
    """Normalize a conflict policy and fail closed for unowned ``replace``."""

    raw = value.value if isinstance(value, ObjectConflictPolicy) else value
    if not isinstance(raw, str) or raw not in {item.value for item in ObjectConflictPolicy}:
        raise ObjectOperationContractError(
            "INVALID_CONFLICT_POLICY",
            "on_name_conflict must be fail, rename, merge, or replace.",
            details={"actual": raw, "allowed": [item.value for item in ObjectConflictPolicy]},
        )
    if raw == ObjectConflictPolicy.REPLACE.value and not replace_owned:
        raise ObjectOperationContractError(
            "REPLACE_OWNERSHIP_REQUIRED",
            "replace is allowed only after the operation layer proves the collided subtree is disposable and request-owned.",
            details={"policy": raw, "replace_owned": False},
        )
    return raw


def describe_conflict_policy(value: str | ObjectConflictPolicy) -> ConflictPolicyRequirements:
    """Return the live guards and cleanup boundary required by a policy."""

    raw = value.value if isinstance(value, ObjectConflictPolicy) else value
    if raw == ObjectConflictPolicy.REPLACE.value:
        normalized = normalize_conflict_policy(raw, replace_owned=True)
    else:
        normalized = normalize_conflict_policy(raw)
    if normalized == ObjectConflictPolicy.FAIL.value:
        return ConflictPolicyRequirements(
            normalized,
            requires_absence_guard=True,
            requires_collision_snapshot=False,
            requires_owned_collision=False,
            can_delete_preexisting_objects=False,
            cleanup_boundary="delete only the GUID returned by object.create when one was created",
        )
    if normalized == ObjectConflictPolicy.RENAME.value:
        return ConflictPolicyRequirements(
            normalized,
            requires_absence_guard=False,
            requires_collision_snapshot=True,
            requires_owned_collision=False,
            can_delete_preexisting_objects=False,
            cleanup_boundary="delete only the returned renamed GUID; preserve the collided object",
        )
    if normalized == ObjectConflictPolicy.MERGE.value:
        return ConflictPolicyRequirements(
            normalized,
            requires_absence_guard=False,
            requires_collision_snapshot=True,
            requires_owned_collision=False,
            can_delete_preexisting_objects=False,
            cleanup_boundary="merged preexisting state has no automatic rollback; use an owned sandbox root",
        )
    return ConflictPolicyRequirements(
        normalized,
        requires_absence_guard=False,
        requires_collision_snapshot=True,
        requires_owned_collision=True,
        can_delete_preexisting_objects=True,
        cleanup_boundary="deleted GUIDs cannot be restored; discard the sandbox or restore a project backup",
    )


def normalize_object_tree(
    payload: Mapping[str, Any],
    *,
    on_name_conflict: str | ObjectConflictPolicy = ObjectConflictPolicy.FAIL,
    replace_owned: bool = False,
    limits: ObjectTreeLimits = ObjectTreeLimits(),
    base_path: str = "$",
    allow_platform: bool = False,
    allow_language: bool = False,
    allow_import: bool = False,
) -> NormalizedObjectTree:
    """Normalize one root and return its deterministic request-relative list."""

    request_size = _request_size(payload, limits=limits, path=base_path)
    state = _NormalizationState(
        limits,
        allow_platform=allow_platform,
        allow_language=allow_language,
        allow_import=allow_import,
    )
    root = state.node(payload, request_path=base_path, parent_path=None, depth=1)
    return NormalizedObjectTree(
        root=root,
        nodes=flatten_request_nodes((root,)),
        on_name_conflict=normalize_conflict_policy(on_name_conflict, replace_owned=replace_owned),
        request_size_bytes=request_size,
    )


def normalize_object_node(
    payload: Mapping[str, Any],
    *,
    limits: ObjectTreeLimits = ObjectTreeLimits(),
    base_path: str = "$",
    allow_platform: bool = False,
    allow_language: bool = False,
    allow_import: bool = False,
) -> ObjectNodeDescriptor:
    """Normalize one node when conflict policy is owned by a surrounding call."""

    return normalize_object_tree(
        payload,
        limits=limits,
        base_path=base_path,
        allow_platform=allow_platform,
        allow_language=allow_language,
        allow_import=allow_import,
    ).root


def normalize_object_forest(
    payload: Sequence[Mapping[str, Any]],
    *,
    on_name_conflict: str | ObjectConflictPolicy = ObjectConflictPolicy.FAIL,
    replace_owned: bool = False,
    limits: ObjectTreeLimits = ObjectTreeLimits(),
    base_path: str = "$",
    allow_platform: bool = False,
    allow_language: bool = False,
    allow_import: bool = False,
) -> NormalizedObjectForest:
    """Normalize sibling roots under one shared node/size budget."""

    if isinstance(payload, (str, bytes, bytearray)) or not isinstance(payload, Sequence):
        raise ObjectOperationContractError(
            "INVALID_FOREST",
            f"{base_path} must be an array of object nodes.",
            details={"path": base_path, "actual_type": type(payload).__name__},
        )
    request_size = _request_size(payload, limits=limits, path=base_path)
    if len(payload) > limits.max_children_per_node:
        raise ObjectOperationContractError(
            "CHILD_LIMIT_EXCEEDED",
            f"{base_path} exceeds the per-parent child limit.",
            details={"path": base_path, "count": len(payload), "limit": limits.max_children_per_node},
        )
    state = _NormalizationState(
        limits,
        allow_platform=allow_platform,
        allow_language=allow_language,
        allow_import=allow_import,
    )
    roots = tuple(
        state.node(
            item,
            request_path=f"{base_path}[{index}]",
            parent_path=None,
            depth=1,
        )
        for index, item in enumerate(payload)
    )
    _reject_duplicate_sibling_names(roots, path=base_path)
    return NormalizedObjectForest(
        roots=roots,
        nodes=flatten_request_nodes(roots),
        on_name_conflict=normalize_conflict_policy(on_name_conflict, replace_owned=replace_owned),
        request_size_bytes=request_size,
    )


def normalize_object_list_name(
    value: Any,
    *,
    request_path: str = "$.list",
    limits: ObjectTreeLimits = ObjectTreeLimits(),
) -> str:
    """Normalize one native object-list token without accepting a raw ``@`` key."""

    return _field_name(value, path=request_path, limits=limits)


def normalize_object_lists(
    payload: Any,
    *,
    request_path: str = "$.lists",
    limits: ObjectTreeLimits = ObjectTreeLimits(),
    allow_platform: bool = False,
    allow_language: bool = False,
    allow_import: bool = False,
) -> tuple[ObjectListDescriptor, ...]:
    """Normalize the closed ``[{name, objects}]`` object-list DSL.

    An empty ``objects`` array is retained so a surrounding, explicitly sealed
    ``replaceAll`` operation can clear a list.  ``append`` callers must reject
    that no-op at the operation layer.
    """

    _request_size(payload, limits=limits, path=request_path)
    rows = _descriptor_rows(
        payload,
        request_path=request_path,
        limit=limits.max_children_per_node,
    )
    result: list[ObjectListDescriptor] = []
    total_nodes = 0
    for index, item in enumerate(rows):
        path = f"{request_path}[{index}]"
        _exact_fields(item, required=LIST_FIELDS, optional=frozenset(), path=path)
        name = normalize_object_list_name(
            item.get("name"),
            request_path=f"{path}.name",
            limits=limits,
        )
        forest = normalize_object_forest(
            item.get("objects"),
            limits=limits,
            base_path=f"{path}.objects",
            allow_platform=allow_platform,
            allow_language=allow_language,
            allow_import=allow_import,
        )
        total_nodes += len(forest.nodes)
        if total_nodes > limits.max_nodes:
            raise ObjectOperationContractError(
                "NODE_LIMIT_EXCEEDED",
                "The object lists exceed the shared total node limit.",
                details={
                    "path": request_path,
                    "count": total_nodes,
                    "limit": limits.max_nodes,
                },
            )
        result.append(
            ObjectListDescriptor(
                request_path=path,
                name=name,
                objects=forest.roots,
                nodes=forest.nodes,
            )
        )
    names = [item.name.casefold() for item in result]
    if len(names) != len(set(names)):
        raise ObjectOperationContractError(
            "DUPLICATE_LIST",
            "One object.set target must not assign the same object list more than once.",
            details={"path": request_path},
        )
    return tuple(result)


def normalize_object_import(
    payload: Any,
    *,
    request_path: str = "$.import",
    max_files: int = DEFAULT_MAX_IMPORT_FILES,
) -> ObjectImportDescriptor:
    """Normalize the reviewed ``importArg`` subset without touching files.

    The operation registry subsequently proves every regular file, canonicalizes
    bounded inline WAV data, and binds those immutable values to the preview.
    This pure layer accepts no other native import fields.
    """

    mapping = _mapping(payload, path=request_path)
    _exact_fields(
        mapping,
        required=IMPORT_FIELDS,
        optional=IMPORT_OPTIONAL_FIELDS,
        path=request_path,
    )
    raw_files = mapping.get("files")
    if not isinstance(raw_files, list):
        raise ObjectOperationContractError(
            "INVALID_IMPORT_FILES",
            f"{request_path}.files must be an array.",
            details={
                "path": f"{request_path}.files",
                "actual_type": type(raw_files).__name__,
            },
        )
    limit = _positive_limit(max_files, field="max_files")
    if not raw_files or len(raw_files) > limit:
        raise ObjectOperationContractError(
            "IMPORT_FILE_LIMIT",
            f"{request_path}.files must contain between 1 and {limit} entries.",
            details={"path": f"{request_path}.files", "count": len(raw_files), "limit": limit},
        )
    files: list[ObjectImportFileDescriptor] = []
    for index, raw in enumerate(raw_files):
        path = f"{request_path}.files[{index}]"
        row = _mapping(raw, path=path)
        _exact_fields(
            row,
            required=frozenset(),
            optional=IMPORT_FILE_OPTIONAL_FIELDS,
            path=path,
        )
        has_file = "audio_file" in row
        has_inline = "audio_file_base64" in row
        if has_file == has_inline:
            raise ObjectOperationContractError(
                "INVALID_IMPORT_SOURCE",
                f"{path} must provide exactly one of audio_file or audio_file_base64.",
                details={"path": path},
            )
        audio_file = (
            _bounded_import_text(
                row.get("audio_file"),
                path=f"{path}.audio_file",
                max_length=4096,
            )
            if has_file
            else None
        )
        audio_file_base64 = (
            _bounded_import_text(
                row.get("audio_file_base64"),
                path=f"{path}.audio_file_base64",
                max_length=256 * 1024,
            )
            if has_inline
            else None
        )
        originals_subfolder = (
            _bounded_import_text(
                row.get("originals_subfolder"),
                path=f"{path}.originals_subfolder",
                max_length=512,
            )
            if "originals_subfolder" in row
            else None
        )
        language = (
            _bounded_import_text(
                row.get("language"),
                path=f"{path}.language",
                max_length=128,
            )
            if "language" in row
            else None
        )
        object_type = (
            _bounded_import_text(
                row.get("object_type"),
                path=f"{path}.object_type",
                max_length=128,
            )
            if "object_type" in row
            else None
        )
        files.append(
            ObjectImportFileDescriptor(
                request_path=path,
                audio_file=audio_file,
                audio_file_base64=audio_file_base64,
                originals_subfolder=originals_subfolder,
                language=language,
                object_type=object_type,
            )
        )
    auto_add = mapping.get("auto_add_to_source_control")
    if auto_add is not None and type(auto_add) is not bool:
        raise ObjectOperationContractError(
            "INVALID_IMPORT_SOURCE_CONTROL",
            f"{request_path}.auto_add_to_source_control must be a JSON boolean.",
            details={"path": f"{request_path}.auto_add_to_source_control"},
        )
    return ObjectImportDescriptor(
        request_path=request_path,
        files=tuple(files),
        auto_add_to_source_control=auto_add,
    )


def normalize_property_descriptors(
    payload: Any,
    *,
    request_path: str = "$.properties",
    limits: ObjectTreeLimits = ObjectTreeLimits(),
) -> tuple[ObjectPropertyDescriptor, ...]:
    """Normalize closed scalar property descriptors for an existing target."""

    return _normalize_properties(payload, request_path=request_path, limits=limits)


def normalize_reference_descriptors(
    payload: Any,
    *,
    request_path: str = "$.references",
    limits: ObjectTreeLimits = ObjectTreeLimits(),
) -> tuple[ObjectReferenceDescriptor, ...]:
    """Normalize reference descriptors without resolving their target identities."""

    return _normalize_references(payload, request_path=request_path, limits=limits)


def normalize_rtpc_descriptors(
    payload: Any,
    *,
    request_path: str = "$.rtpcs",
    limits: ObjectTreeLimits = ObjectTreeLimits(),
    max_rtpcs: int = DEFAULT_MAX_RTPCS,
    max_points_per_curve: int = DEFAULT_MAX_RTPC_POINTS,
) -> tuple[RtpcDescriptor, ...]:
    """Normalize the closed public RTPC DSL without accepting raw object lists."""

    _request_size(payload, limits=limits, path=request_path)
    rows = _descriptor_rows(
        payload,
        request_path=request_path,
        limit=_positive_limit(max_rtpcs, field="max_rtpcs"),
    )
    if not rows:
        raise ObjectOperationContractError(
            "EMPTY_RTPC_LIST",
            f"{request_path} must contain at least one RTPC descriptor.",
            details={"path": request_path},
        )

    point_limit = _positive_limit(max_points_per_curve, field="max_points_per_curve")
    normalized: list[RtpcDescriptor] = []
    for index, item in enumerate(rows):
        path = f"{request_path}[{index}]"
        _exact_fields(item, required=RTPC_FIELDS, optional=RTPC_OPTIONAL_FIELDS, path=path)
        property_name = _field_name(item.get("property"), path=f"{path}.property", limits=limits)
        control_input = _normalize_identity(
            item.get("control_input"),
            path=f"{path}.control_input",
            limits=limits,
        )
        points_payload = item.get("points")
        if not isinstance(points_payload, list):
            raise ObjectOperationContractError(
                "INVALID_RTPC_POINTS",
                f"{path}.points must be an array.",
                details={"path": f"{path}.points", "actual_type": type(points_payload).__name__},
            )
        if not points_payload or len(points_payload) > point_limit:
            raise ObjectOperationContractError(
                "RTPC_POINT_LIMIT",
                f"{path}.points must contain between 1 and {point_limit} points.",
                details={"path": f"{path}.points", "count": len(points_payload), "limit": point_limit},
            )

        points: list[RtpcCurvePoint] = []
        previous_x: int | float | None = None
        for point_index, raw_point in enumerate(points_payload):
            point_path = f"{path}.points[{point_index}]"
            point = _mapping(raw_point, path=point_path)
            _exact_fields(point, required=RTPC_POINT_FIELDS, optional=frozenset(), path=point_path)
            x = _finite_number(point.get("x"), path=f"{point_path}.x")
            y = _finite_number(point.get("y"), path=f"{point_path}.y")
            shape = point.get("shape")
            if shape not in RTPC_POINT_SHAPES:
                raise ObjectOperationContractError(
                    "INVALID_RTPC_POINT_SHAPE",
                    f"{point_path}.shape is not a supported Wwise curve shape.",
                    details={
                        "path": f"{point_path}.shape",
                        "actual": shape,
                        "allowed": sorted(RTPC_POINT_SHAPES),
                    },
                )
            if previous_x is not None and x <= previous_x:
                raise ObjectOperationContractError(
                    "INVALID_RTPC_POINT_ORDER",
                    f"{path}.points x coordinates must be strictly increasing.",
                    details={
                        "path": f"{point_path}.x",
                        "previous_x": previous_x,
                        "actual_x": x,
                    },
                )
            previous_x = x
            points.append(RtpcCurvePoint(x=x, y=y, shape=shape))

        notes = item.get("notes")
        if notes is not None:
            if not isinstance(notes, str):
                raise ObjectOperationContractError(
                    "INVALID_RTPC_NOTES",
                    f"{path}.notes must be a string when present.",
                    details={"path": f"{path}.notes", "actual_type": type(notes).__name__},
                )
            if len(notes) > limits.max_notes_length:
                raise ObjectOperationContractError(
                    "STRING_LIMIT_EXCEEDED",
                    f"{path}.notes exceeds the length limit.",
                    details={
                        "path": f"{path}.notes",
                        "length": len(notes),
                        "limit": limits.max_notes_length,
                    },
                )
            if any(ord(character) < 32 and character not in "\n\r\t" for character in notes):
                raise ObjectOperationContractError(
                    "INVALID_RTPC_NOTES",
                    f"{path}.notes must not contain control characters.",
                    details={"path": f"{path}.notes"},
                )
        normalized.append(
            RtpcDescriptor(
                request_path=path,
                property=property_name,
                control_input=control_input,
                points=tuple(points),
                notes=notes,
            )
        )
    return tuple(normalized)


def materialize_waapi_rtpc(
    descriptor: RtpcDescriptor,
    *,
    resolved_control_input: ObjectId,
) -> dict[str, Any]:
    """Build the native ``@RTPC`` row from reviewed data and one resolved identity."""

    _require_object_id(
        resolved_control_input,
        path=f"{descriptor.request_path}.control_input",
    )
    result: dict[str, Any] = {
        "type": "RTPC",
        "name": "",
        "@Curve": {
            "type": "Curve",
            "points": [point.as_dict() for point in descriptor.points],
        },
        "@PropertyName": descriptor.property,
        "@ControlInput": resolved_control_input,
    }
    if descriptor.notes is not None:
        result["notes"] = descriptor.notes
    return result


def flatten_request_nodes(roots: Sequence[ObjectNodeDescriptor]) -> tuple[ObjectNodeDescriptor, ...]:
    """Flatten normalized roots in deterministic pre-order."""

    result: list[ObjectNodeDescriptor] = []

    def visit(node: ObjectNodeDescriptor) -> None:
        result.append(node)
        for child in node.children:
            visit(child)

    for root in roots:
        visit(root)
    return tuple(result)


def request_topology_edges(nodes: Sequence[ObjectNodeDescriptor]) -> tuple[ObjectTopologyEdge, ...]:
    """Return every request-relative parent/child edge in node order."""

    return tuple(
        ObjectTopologyEdge(node.parent_request_path, node.request_path)
        for node in nodes
        if node.parent_request_path is not None
    )


def materialize_waapi_node(
    node: ObjectNodeDescriptor,
    *,
    resolved_references: Mapping[str, ObjectId] | None = None,
    materialized_imports: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one trusted native WAAPI child object from normalized descriptors.

    ``resolved_references`` is keyed by each descriptor's request path (for
    example ``$.references[0]``).  Values must be canonical IDs produced by the
    live operation layer, never copied from model-authored dynamic fields.
    """

    resolved = dict(resolved_references or {})
    imports = {
        key: dict(value)
        for key, value in dict(materialized_imports or {}).items()
    }
    required_paths = {
        reference.request_path
        for request_node in flatten_request_nodes((node,))
        for reference in request_node.references
    }
    missing = sorted(required_paths - set(resolved))
    unexpected = sorted(set(resolved) - required_paths)
    if missing or unexpected:
        raise ObjectOperationContractError(
            "REFERENCE_BINDING_MISMATCH",
            "Resolved reference bindings must match the normalized reference descriptors exactly.",
            details={"missing": missing, "unexpected": unexpected},
        )
    required_import_paths = {
        request_node.request_path
        for request_node in flatten_request_nodes((node,))
        if request_node.import_arg is not None
    }
    missing_imports = sorted(required_import_paths - set(imports))
    unexpected_imports = sorted(set(imports) - required_import_paths)
    if missing_imports or unexpected_imports:
        raise ObjectOperationContractError(
            "IMPORT_BINDING_MISMATCH",
            "Trusted import bindings must match normalized import descriptors exactly.",
            details={
                "missing": missing_imports,
                "unexpected": unexpected_imports,
            },
        )

    def build(current: ObjectNodeDescriptor) -> dict[str, Any]:
        result: dict[str, Any] = {"type": current.type, "name": current.name}
        if current.notes is not None:
            result["notes"] = current.notes
        if current.platform is not None:
            result["platform"] = current.platform
        if current.language is not None:
            result["language"] = current.language
        if current.import_arg is not None:
            result["import"] = imports[current.request_path]
        for prop in current.properties:
            result[f"@{prop.name}"] = prop.value
        for reference in current.references:
            target = resolved[reference.request_path]
            _require_object_id(target, path=reference.request_path)
            result[f"@{reference.name}"] = target
        if current.children:
            result["children"] = [build(child) for child in current.children]
        return result

    return build(node)


def flatten_create_result(
    payload: Mapping[str, Any],
    *,
    base_path: str = "$",
    max_nodes: int = DEFAULT_MAX_NODES,
) -> tuple[ObjectResultNode, ...]:
    """Flatten an ``object.create`` result body using request-shaped paths."""

    counter = [0]
    return tuple(
        _flatten_result_node(
            payload,
            request_path=base_path,
            parent_path=None,
            max_nodes=_positive_limit(max_nodes, field="max_nodes"),
            counter=counter,
        )
    )


def flatten_set_result(
    payload: Mapping[str, Any],
    *,
    base_path: str = "$.objects",
    max_nodes: int = DEFAULT_MAX_NODES,
    allowed_lists: Sequence[str] = (),
) -> tuple[ObjectResultNode, ...]:
    """Flatten an ``object.set`` result body, including reviewed list fields."""

    mapping = _mapping(payload, path="$result")
    unknown_root = set(mapping) - {"objects"}
    if unknown_root:
        raise ObjectOperationContractError(
            "INVALID_RESULT_SHAPE",
            "object.set result contains unknown top-level fields.",
            details={"path": "$result", "unknown_fields": sorted(unknown_root)},
        )
    objects = mapping.get("objects", [])
    if not isinstance(objects, list):
        raise ObjectOperationContractError(
            "INVALID_RESULT_SHAPE",
            "object.set result.objects must be an array when present.",
            details={"path": "$result.objects", "actual_type": type(objects).__name__},
        )
    limit = _positive_limit(max_nodes, field="max_nodes")
    normalized_lists = {
        normalize_object_list_name(
            item,
            request_path=f"$allowed_lists[{index}]",
        )
        for index, item in enumerate(allowed_lists)
    }
    counter = [0]
    result: list[ObjectResultNode] = []
    for index, item in enumerate(objects):
        request_path = f"{base_path}[{index}]"
        row = _mapping(item, path=request_path)
        dynamic_fields = {
            key[1:]: key
            for key in row
            if key.startswith("@")
        }
        unexpected = sorted(set(dynamic_fields) - normalized_lists)
        if unexpected:
            raise ObjectOperationContractError(
                "INVALID_RESULT_SHAPE",
                "object.set result contains an unreviewed object-list association.",
                details={
                    "path": request_path,
                    "unexpected_lists": unexpected,
                    "allowed_lists": sorted(normalized_lists),
                },
            )
        object_id, name = _result_identity(row, request_path=request_path)
        children = _result_collection_rows(
            row.get("children", []),
            request_path=f"{request_path}.children",
        )
        list_rows = {
            list_name: _result_collection_rows(
                row.get(wire_name, []),
                request_path=f"{request_path}.{wire_name}",
                allow_single=True,
            )
            for list_name, wire_name in dynamic_fields.items()
        }
        counter[0] += 1
        if counter[0] > limit:
            raise ObjectOperationContractError(
                "RESULT_NODE_LIMIT_EXCEEDED",
                "The reflected object result exceeds the node limit.",
                details={"path": request_path, "count": counter[0], "limit": limit},
            )
        result.append(
            ObjectResultNode(
                request_path,
                None,
                object_id,
                name,
                len(children) + sum(len(rows) for rows in list_rows.values()),
                None,
            )
        )
        for child_index, child in enumerate(children):
            result.extend(
                _flatten_result_node(
                    child,
                    request_path=f"{request_path}.children[{child_index}]",
                    parent_path=request_path,
                    max_nodes=limit,
                    counter=counter,
                    collection="children",
                )
            )
        for list_name, rows in list_rows.items():
            for child_index, child in enumerate(rows):
                result.extend(
                    _flatten_result_node(
                        child,
                        request_path=f"{request_path}.@{list_name}[{child_index}]",
                        parent_path=request_path,
                        max_nodes=limit,
                        counter=counter,
                        collection=list_name,
                    )
                )
    return tuple(result)


def bind_request_result_topology(
    request_nodes: Sequence[ObjectNodeDescriptor],
    result_nodes: Sequence[ObjectResultNode],
) -> tuple[ObjectResultBinding, ...]:
    """Bind reflected IDs only when request-relative topology matches exactly."""

    requested = {node.request_path: node for node in request_nodes}
    returned = {node.request_path: node for node in result_nodes}
    if len(requested) != len(request_nodes) or len(returned) != len(result_nodes):
        raise ObjectOperationContractError(
            "TOPOLOGY_MISMATCH",
            "Request or result contains duplicate request-relative paths.",
        )
    missing = sorted(set(requested) - set(returned))
    unexpected = sorted(set(returned) - set(requested))
    if missing or unexpected:
        raise ObjectOperationContractError(
            "TOPOLOGY_MISMATCH",
            "The reflected result topology does not match the normalized request topology.",
            details={"missing": missing, "unexpected": unexpected},
        )
    bindings: list[ObjectResultBinding] = []
    for request_node in request_nodes:
        returned_node = returned[request_node.request_path]
        if request_node.parent_request_path != returned_node.parent_request_path:
            raise ObjectOperationContractError(
                "TOPOLOGY_MISMATCH",
                "The reflected result parent edge does not match the normalized request.",
                details={
                    "path": request_node.request_path,
                    "expected_parent": request_node.parent_request_path,
                    "actual_parent": returned_node.parent_request_path,
                },
            )
        bindings.append(
            ObjectResultBinding(
                request_path=request_node.request_path,
                requested_type=request_node.type,
                requested_name=request_node.name,
                object=returned_node.object,
                actual_name=returned_node.name,
            )
        )
    return tuple(bindings)


class _NormalizationState:
    def __init__(
        self,
        limits: ObjectTreeLimits,
        *,
        allow_platform: bool,
        allow_language: bool,
        allow_import: bool,
    ) -> None:
        self.limits = limits
        self.allow_platform = allow_platform
        self.allow_language = allow_language
        self.allow_import = allow_import
        self.node_count = 0

    def node(
        self,
        payload: Any,
        *,
        request_path: str,
        parent_path: str | None,
        depth: int,
    ) -> ObjectNodeDescriptor:
        if depth > self.limits.max_depth:
            raise ObjectOperationContractError(
                "DEPTH_LIMIT_EXCEEDED",
                f"{request_path} exceeds the recursive object depth limit.",
                details={"path": request_path, "depth": depth, "limit": self.limits.max_depth},
            )
        self.node_count += 1
        if self.node_count > self.limits.max_nodes:
            raise ObjectOperationContractError(
                "NODE_LIMIT_EXCEEDED",
                "The object tree exceeds the total node limit.",
                details={"path": request_path, "count": self.node_count, "limit": self.limits.max_nodes},
            )
        mapping = _mapping(payload, path=request_path)
        allowed_fields = (
            OBJECT_SET_NODE_FIELDS
            if self.allow_platform or self.allow_language or self.allow_import
            else NODE_FIELDS
        )
        if not self.allow_platform:
            allowed_fields = allowed_fields - {"platform"}
        if not self.allow_language:
            allowed_fields = allowed_fields - {"language"}
        if not self.allow_import:
            allowed_fields = allowed_fields - {"import"}
        _exact_fields(
            mapping,
            required={"type", "name"},
            optional=allowed_fields - {"type", "name"},
            path=request_path,
        )
        object_type = _bounded_token(
            mapping.get("type"),
            path=f"{request_path}.type",
            max_length=self.limits.max_type_length,
            disallow_path_separator=False,
        )
        name = _bounded_token(
            mapping.get("name"),
            path=f"{request_path}.name",
            max_length=self.limits.max_name_length,
            disallow_path_separator=True,
        )
        notes = mapping.get("notes")
        if notes is not None:
            if not isinstance(notes, str):
                raise ObjectOperationContractError(
                    "INVALID_NOTES",
                    f"{request_path}.notes must be a string.",
                    details={"path": f"{request_path}.notes", "actual_type": type(notes).__name__},
                )
            if len(notes) > self.limits.max_notes_length:
                raise ObjectOperationContractError(
                    "NOTES_LIMIT_EXCEEDED",
                    f"{request_path}.notes exceeds the length limit.",
                    details={"path": f"{request_path}.notes", "length": len(notes), "limit": self.limits.max_notes_length},
                )
        platform = (
            _bounded_import_text(
                mapping.get("platform"),
                path=f"{request_path}.platform",
                max_length=128,
            )
            if "platform" in mapping
            else None
        )
        language = (
            _bounded_import_text(
                mapping.get("language"),
                path=f"{request_path}.language",
                max_length=128,
            )
            if "language" in mapping
            else None
        )
        import_arg = (
            normalize_object_import(
                mapping.get("import"),
                request_path=f"{request_path}.import",
            )
            if "import" in mapping
            else None
        )
        properties = _normalize_properties(
            mapping.get("properties", []),
            request_path=f"{request_path}.properties",
            limits=self.limits,
        )
        references = _normalize_references(
            mapping.get("references", []),
            request_path=f"{request_path}.references",
            limits=self.limits,
        )
        if len(properties) + len(references) > self.limits.max_fields_per_node:
            raise ObjectOperationContractError(
                "FIELD_LIMIT_EXCEEDED",
                "The combined property/reference descriptor count exceeds the per-node field limit.",
                details={
                    "path": request_path,
                    "property_count": len(properties),
                    "reference_count": len(references),
                    "limit": self.limits.max_fields_per_node,
                },
            )
        field_names = [item.name.casefold() for item in (*properties, *references)]
        if len(field_names) != len(set(field_names)):
            raise ObjectOperationContractError(
                "DUPLICATE_FIELD",
                "A node must not set the same property/reference more than once.",
                details={"path": request_path},
            )
        raw_children = mapping.get("children", [])
        if not isinstance(raw_children, list):
            raise ObjectOperationContractError(
                "INVALID_CHILDREN",
                f"{request_path}.children must be an array.",
                details={"path": f"{request_path}.children", "actual_type": type(raw_children).__name__},
            )
        if len(raw_children) > self.limits.max_children_per_node:
            raise ObjectOperationContractError(
                "CHILD_LIMIT_EXCEEDED",
                f"{request_path}.children exceeds the per-parent child limit.",
                details={
                    "path": f"{request_path}.children",
                    "count": len(raw_children),
                    "limit": self.limits.max_children_per_node,
                },
            )
        children = tuple(
            self.node(
                child,
                request_path=f"{request_path}.children[{index}]",
                parent_path=request_path,
                depth=depth + 1,
            )
            for index, child in enumerate(raw_children)
        )
        _reject_duplicate_sibling_names(children, path=f"{request_path}.children")
        return ObjectNodeDescriptor(
            request_path=request_path,
            parent_request_path=parent_path,
            type=object_type,
            name=name,
            notes=notes,
            platform=platform,
            language=language,
            import_arg=import_arg,
            properties=properties,
            references=references,
            children=children,
        )


def _normalize_properties(
    payload: Any,
    *,
    request_path: str,
    limits: ObjectTreeLimits,
) -> tuple[ObjectPropertyDescriptor, ...]:
    rows = _descriptor_rows(payload, request_path=request_path, limit=limits.max_fields_per_node)
    result: list[ObjectPropertyDescriptor] = []
    for index, item in enumerate(rows):
        path = f"{request_path}[{index}]"
        _exact_fields(item, required=PROPERTY_FIELDS, optional=frozenset(), path=path)
        name = _field_name(item.get("name"), path=f"{path}.name", limits=limits)
        value = item.get("value")
        if not _is_json_scalar(value):
            raise ObjectOperationContractError(
                "INVALID_PROPERTY_VALUE",
                f"{path}.value must be a finite JSON string, number, or boolean.",
                details={"path": f"{path}.value", "actual_type": type(value).__name__},
            )
        result.append(ObjectPropertyDescriptor(path, name, value))
    _reject_duplicate_descriptor_names(result, path=request_path)
    return tuple(result)


def _normalize_references(
    payload: Any,
    *,
    request_path: str,
    limits: ObjectTreeLimits,
) -> tuple[ObjectReferenceDescriptor, ...]:
    rows = _descriptor_rows(payload, request_path=request_path, limit=limits.max_fields_per_node)
    result: list[ObjectReferenceDescriptor] = []
    for index, item in enumerate(rows):
        path = f"{request_path}[{index}]"
        _exact_fields(item, required=REFERENCE_FIELDS, optional=frozenset(), path=path)
        name = _field_name(item.get("name"), path=f"{path}.name", limits=limits)
        target = _normalize_identity(item.get("target"), path=f"{path}.target", limits=limits)
        result.append(ObjectReferenceDescriptor(path, name, target))
    _reject_duplicate_descriptor_names(result, path=request_path)
    return tuple(result)


def _normalize_identity(
    payload: Any,
    *,
    path: str,
    limits: ObjectTreeLimits,
) -> ObjectIdentityDescriptor:
    mapping = _mapping(payload, path=path)
    kind = mapping.get("kind")
    if kind not in IDENTITY_KINDS:
        raise ObjectOperationContractError(
            "INVALID_IDENTITY",
            f"{path}.kind must be id, path, exact-type-name, direct-child, or scoped-name.",
            details={"path": path, "kind": kind},
        )
    if kind in {"id", "path"}:
        _exact_fields(mapping, required={"kind", "value"}, optional=frozenset(), path=path)
        value = mapping.get("value")
        if kind == "id":
            _require_object_id(value, path=f"{path}.value")
        else:
            if not isinstance(value, str) or not value.strip():
                raise ObjectOperationContractError(
                    "INVALID_IDENTITY",
                    f"{path}.value must be a non-empty string.",
                    details={"path": f"{path}.value", "kind": kind},
                )
            if kind == "path" and not value.startswith("\\"):
                raise ObjectOperationContractError(
                    "INVALID_IDENTITY",
                    f"{path}.value must be an absolute Wwise path.",
                    details={"path": f"{path}.value", "kind": kind},
                )
        return ObjectIdentityDescriptor(kind=kind, value=value)
    if kind == "exact-type-name":
        _exact_fields(
            mapping,
            required={"kind", "type", "name"},
            optional=frozenset(),
            path=path,
        )
        object_type = _bounded_token(
            mapping.get("type"),
            path=f"{path}.type",
            max_length=limits.max_type_length,
            disallow_path_separator=True,
        )
        if _EXACT_TYPE_NAME_TYPE_TOKEN.fullmatch(object_type) is None:
            raise ObjectOperationContractError(
                "INVALID_IDENTITY",
                f"{path}.type must be one canonical Wwise type token.",
                details={
                    "path": f"{path}.type",
                    "accepted": _EXACT_TYPE_NAME_TYPE_TOKEN.pattern,
                },
            )
        name = _bounded_token(
            mapping.get("name"),
            path=f"{path}.name",
            max_length=limits.max_name_length,
            disallow_path_separator=True,
        )
        if (
            '"' in name
            or any(
                ord(character) == 127
                or character in {"\u2028", "\u2029"}
                for character in name
            )
        ):
            raise ObjectOperationContractError(
                "INVALID_IDENTITY",
                f"{path}.name is outside the packaged WAQL literal boundary.",
                details={
                    "path": f"{path}.name",
                    "boundary": "packaged-waql-literal-evidence",
                },
            )
        return ObjectIdentityDescriptor(
            kind=kind,
            name=name,
            type=object_type,
        )
    if kind == "direct-child":
        _exact_fields(
            mapping,
            required={"kind", "parent", "type"},
            optional=frozenset(),
            path=path,
        )
        object_type = _bounded_token(
            mapping.get("type"),
            path=f"{path}.type",
            max_length=limits.max_type_length,
            disallow_path_separator=False,
        )
        if '"' in object_type:
            raise ObjectOperationContractError(
                "INVALID_IDENTITY",
                f"{path}.type is outside the packaged WAQL literal boundary.",
                details={"path": f"{path}.type"},
            )
        parent = _normalize_identity(
            mapping.get("parent"),
            path=f"{path}.parent",
            limits=limits,
        )
        if parent.kind not in {"id", "path"}:
            raise ObjectOperationContractError(
                "INVALID_IDENTITY",
                "A direct-child identity parent must use a closed id or path identity.",
                details={"path": f"{path}.parent", "kind": parent.kind},
            )
        parent_value = parent.value
        if (
            isinstance(parent_value, str)
            and (
                len(parent_value) > DEFAULT_MAX_IDENTITY_PARENT_LITERAL_LENGTH
                or '"' in parent_value
                or any(
                    ord(character) < 32
                    or ord(character) == 127
                    or character in {"\u2028", "\u2029"}
                    for character in parent_value
                )
            )
        ):
            raise ObjectOperationContractError(
                "INVALID_IDENTITY",
                f"{path}.parent exceeds the packaged WAQL literal boundary.",
                details={
                    "path": f"{path}.parent",
                    "limit": DEFAULT_MAX_IDENTITY_PARENT_LITERAL_LENGTH,
                },
            )
        return ObjectIdentityDescriptor(
            kind=kind,
            type=object_type,
            parent=parent,
        )
    _exact_fields(mapping, required={"kind", "name", "type", "parent"}, optional=frozenset(), path=path)
    name = _bounded_token(
        mapping.get("name"),
        path=f"{path}.name",
        max_length=limits.max_name_length,
        disallow_path_separator=True,
    )
    object_type = _bounded_token(
        mapping.get("type"),
        path=f"{path}.type",
        max_length=limits.max_type_length,
        disallow_path_separator=False,
    )
    if _EXACT_TYPE_NAME_TYPE_TOKEN.fullmatch(object_type) is None:
        raise ObjectOperationContractError(
            "INVALID_IDENTITY",
            f"{path}.type must be one canonical Wwise type token.",
            details={
                "path": f"{path}.type",
                "accepted": _EXACT_TYPE_NAME_TYPE_TOKEN.pattern,
            },
        )
    if (
        '"' in name
        or any(
            ord(character) == 127
            or character in {"\u2028", "\u2029"}
            for character in name
        )
    ):
        raise ObjectOperationContractError(
            "INVALID_IDENTITY",
            f"{path}.name is outside the packaged WAQL literal boundary.",
            details={
                "path": f"{path}.name",
                "boundary": "packaged-waql-literal-evidence",
            },
        )
    parent = _normalize_identity(mapping.get("parent"), path=f"{path}.parent", limits=limits)
    if parent.kind not in {"id", "path"}:
        raise ObjectOperationContractError(
            "INVALID_IDENTITY",
            "A scoped-name identity parent must use a closed id or path identity.",
            details={"path": f"{path}.parent", "kind": parent.kind},
        )
    parent_value = parent.value
    if (
        isinstance(parent_value, str)
        and (
            len(parent_value) > DEFAULT_MAX_IDENTITY_PARENT_LITERAL_LENGTH
            or '"' in parent_value
            or any(
                ord(character) < 32
                or ord(character) == 127
                or character in {"\u2028", "\u2029"}
                for character in parent_value
            )
        )
    ):
        raise ObjectOperationContractError(
            "INVALID_IDENTITY",
            f"{path}.parent exceeds the packaged WAQL literal boundary.",
            details={
                "path": f"{path}.parent",
                "limit": DEFAULT_MAX_IDENTITY_PARENT_LITERAL_LENGTH,
            },
        )
    return ObjectIdentityDescriptor(kind=kind, name=name, type=object_type, parent=parent)


def normalize_object_identity(
    payload: Any,
    *,
    path: str = "identity",
    limits: ObjectTreeLimits | None = None,
) -> ObjectIdentityDescriptor:
    """Validate one public closed object identity without materializing WAAPI."""

    return _normalize_identity(
        payload,
        path=path,
        limits=ObjectTreeLimits() if limits is None else limits,
    )


def _flatten_result_node(
    payload: Any,
    *,
    request_path: str,
    parent_path: str | None,
    max_nodes: int,
    counter: list[int],
    collection: str = "children",
) -> list[ObjectResultNode]:
    counter[0] += 1
    if counter[0] > max_nodes:
        raise ObjectOperationContractError(
            "RESULT_NODE_LIMIT_EXCEEDED",
            "The reflected object result exceeds the node limit.",
            details={"path": request_path, "count": counter[0], "limit": max_nodes},
        )
    mapping = _mapping(payload, path=request_path)
    dynamic_fields = sorted(key for key in mapping if key.startswith("@"))
    if dynamic_fields:
        raise ObjectOperationContractError(
            "INVALID_RESULT_SHAPE",
            "Nested object results contain an unreviewed object-list association.",
            details={"path": request_path, "unexpected_fields": dynamic_fields},
        )
    object_id, name = _result_identity(mapping, request_path=request_path)
    children = _result_collection_rows(
        mapping.get("children", []),
        request_path=f"{request_path}.children",
    )
    result = [
        ObjectResultNode(
            request_path,
            parent_path,
            object_id,
            name,
            len(children),
            collection,
        )
    ]
    for index, child in enumerate(children):
        result.extend(
            _flatten_result_node(
                child,
                request_path=f"{request_path}.children[{index}]",
                parent_path=request_path,
                max_nodes=max_nodes,
                counter=counter,
                collection="children",
            )
        )
    return result


def _result_identity(mapping: Mapping[str, Any], *, request_path: str) -> tuple[ObjectId, str]:
    object_id = mapping.get("id")
    _require_object_id(object_id, path=f"{request_path}.id")
    name = mapping.get("name")
    if not isinstance(name, str):
        raise ObjectOperationContractError(
            "INVALID_RESULT_SHAPE",
            f"{request_path}.name must be a string.",
            details={
                "path": f"{request_path}.name",
                "actual_type": type(name).__name__,
            },
        )
    return object_id, name


def _result_collection_rows(
    value: Any,
    *,
    request_path: str,
    allow_single: bool = False,
) -> list[dict[str, Any]]:
    if allow_single and isinstance(value, Mapping):
        return [_mapping(value, path=request_path)]
    if not isinstance(value, list):
        raise ObjectOperationContractError(
            "INVALID_RESULT_SHAPE",
            f"{request_path} must be an array when present.",
            details={"path": request_path, "actual_type": type(value).__name__},
        )
    return [
        _mapping(item, path=f"{request_path}[{index}]")
        for index, item in enumerate(value)
    ]


def _request_size(payload: Any, *, limits: ObjectTreeLimits, path: str) -> int:
    try:
        size = len(canonical_json_bytes(payload))
    except (TypeError, ValueError) as exc:
        raise ObjectOperationContractError(
            "INVALID_JSON",
            f"{path} must contain strict JSON values.",
            details={"path": path},
        ) from exc
    if size > limits.max_request_bytes:
        raise ObjectOperationContractError(
            "REQUEST_LIMIT_EXCEEDED",
            "The object-tree request exceeds the byte limit.",
            details={"path": path, "size_bytes": size, "limit_bytes": limits.max_request_bytes},
        )
    return size


def _mapping(payload: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ObjectOperationContractError(
            "INVALID_OBJECT",
            f"{path} must be a JSON object.",
            details={"path": path, "actual_type": type(payload).__name__},
        )
    if not all(isinstance(key, str) for key in payload):
        raise ObjectOperationContractError(
            "INVALID_OBJECT",
            f"{path} object keys must be strings.",
            details={"path": path},
        )
    return dict(payload)


def _exact_fields(
    mapping: Mapping[str, Any],
    *,
    required: set[str] | frozenset[str],
    optional: set[str] | frozenset[str],
    path: str,
) -> None:
    actual = set(mapping)
    missing = sorted(set(required) - actual)
    unknown = sorted(actual - set(required) - set(optional))
    if missing or unknown:
        raise ObjectOperationContractError(
            "INVALID_FIELDS",
            f"{path} does not match the closed object-operation schema.",
            details={"path": path, "missing_fields": missing, "unknown_fields": unknown},
        )


def _descriptor_rows(payload: Any, *, request_path: str, limit: int) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ObjectOperationContractError(
            "INVALID_DESCRIPTOR_LIST",
            f"{request_path} must be an array.",
            details={"path": request_path, "actual_type": type(payload).__name__},
        )
    if len(payload) > limit:
        raise ObjectOperationContractError(
            "FIELD_LIMIT_EXCEEDED",
            f"{request_path} exceeds the per-node field limit.",
            details={"path": request_path, "count": len(payload), "limit": limit},
        )
    return [_mapping(item, path=f"{request_path}[{index}]") for index, item in enumerate(payload)]


def _field_name(value: Any, *, path: str, limits: ObjectTreeLimits) -> str:
    name = _bounded_token(
        value,
        path=path,
        max_length=limits.max_field_name_length,
        disallow_path_separator=True,
    )
    if name.startswith("@") or _DYNAMIC_FIELD_NAME.fullmatch(name) is None:
        raise ObjectOperationContractError(
            "INVALID_FIELD_NAME",
            f"{path} must be a canonical property/reference name without an @ prefix.",
            details={"path": path, "name": name},
        )
    return name


def _bounded_import_text(value: Any, *, path: str, max_length: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ObjectOperationContractError(
            "INVALID_STRING",
            f"{path} must be a non-empty string without leading or trailing whitespace.",
            details={"path": path, "actual_type": type(value).__name__},
        )
    if len(value) > max_length:
        raise ObjectOperationContractError(
            "STRING_LIMIT_EXCEEDED",
            f"{path} exceeds the length limit.",
            details={"path": path, "length": len(value), "limit": max_length},
        )
    if any(ord(character) < 32 for character in value):
        raise ObjectOperationContractError(
            "INVALID_STRING",
            f"{path} must not contain control characters.",
            details={"path": path},
        )
    return value


def _bounded_token(
    value: Any,
    *,
    path: str,
    max_length: int,
    disallow_path_separator: bool,
) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ObjectOperationContractError(
            "INVALID_STRING",
            f"{path} must be a non-empty string without leading or trailing whitespace.",
            details={"path": path, "actual_type": type(value).__name__},
        )
    if len(value) > max_length:
        raise ObjectOperationContractError(
            "STRING_LIMIT_EXCEEDED",
            f"{path} exceeds the length limit.",
            details={"path": path, "length": len(value), "limit": max_length},
        )
    if any(ord(character) < 32 for character in value):
        raise ObjectOperationContractError(
            "INVALID_STRING",
            f"{path} must not contain control characters.",
            details={"path": path},
        )
    if disallow_path_separator and "\\" in value:
        raise ObjectOperationContractError(
            "INVALID_STRING",
            f"{path} must not contain the Wwise path separator.",
            details={"path": path},
        )
    return value


def _is_json_scalar(value: Any) -> bool:
    if isinstance(value, bool | str):
        return True
    if isinstance(value, int) and not isinstance(value, bool):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _finite_number(value: Any, *, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ObjectOperationContractError(
            "INVALID_NUMBER",
            f"{path} must be a finite JSON number.",
            details={"path": path, "actual_type": type(value).__name__},
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise ObjectOperationContractError(
            "INVALID_NUMBER",
            f"{path} must be a finite JSON number.",
            details={"path": path, "actual": repr(value)},
        )
    return value


def _require_object_id(value: Any, *, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise ObjectOperationContractError(
            "INVALID_IDENTITY",
            f"{path} must be a non-empty string or integer object identity.",
            details={"path": path, "actual_type": type(value).__name__},
        )
    if isinstance(value, str) and not value.strip():
        raise ObjectOperationContractError(
            "INVALID_IDENTITY",
            f"{path} must be a non-empty string or integer object identity.",
            details={"path": path},
        )


def _reject_duplicate_sibling_names(nodes: Sequence[ObjectNodeDescriptor], *, path: str) -> None:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for node in nodes:
        key = node.name.casefold()
        if key in seen:
            duplicates.append(node.name)
        else:
            seen[key] = node.name
    if duplicates:
        raise ObjectOperationContractError(
            "DUPLICATE_SIBLING_NAME",
            "One request must not contain case-insensitive duplicate sibling names.",
            details={"path": path, "duplicates": duplicates},
        )


def _reject_duplicate_descriptor_names(
    descriptors: Sequence[ObjectPropertyDescriptor | ObjectReferenceDescriptor],
    *,
    path: str,
) -> None:
    names = [item.name.casefold() for item in descriptors]
    if len(names) != len(set(names)):
        raise ObjectOperationContractError(
            "DUPLICATE_FIELD",
            "A descriptor list must not contain duplicate field names.",
            details={"path": path},
        )


def _positive_limit(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


__all__ = [
    "ConflictPolicyRequirements",
    "NormalizedObjectForest",
    "NormalizedObjectTree",
    "ObjectConflictPolicy",
    "ObjectIdentityDescriptor",
    "ObjectImportDescriptor",
    "ObjectImportFileDescriptor",
    "ObjectListDescriptor",
    "ObjectNodeDescriptor",
    "ObjectOperationContractError",
    "ObjectPropertyDescriptor",
    "ObjectReferenceDescriptor",
    "ObjectResultBinding",
    "ObjectResultNode",
    "ObjectTopologyEdge",
    "ObjectTreeLimits",
    "RTPC_POINT_SHAPES",
    "RtpcCurvePoint",
    "RtpcDescriptor",
    "bind_request_result_topology",
    "describe_conflict_policy",
    "flatten_create_result",
    "flatten_request_nodes",
    "flatten_set_result",
    "materialize_waapi_node",
    "materialize_waapi_rtpc",
    "normalize_conflict_policy",
    "normalize_object_forest",
    "normalize_object_import",
    "normalize_object_identity",
    "normalize_object_list_name",
    "normalize_object_lists",
    "normalize_object_node",
    "normalize_object_tree",
    "normalize_property_descriptors",
    "normalize_reference_descriptors",
    "normalize_rtpc_descriptors",
    "request_topology_edges",
]
