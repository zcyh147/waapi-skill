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
from typing import Any, Mapping, NoReturn, Sequence

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
DEFAULT_MAX_FIELD_NAME_LENGTH = 128
DEFAULT_MAX_NOTES_LENGTH = 64 * 1024

NODE_FIELDS = frozenset({"type", "name", "notes", "properties", "references", "children"})
PROPERTY_FIELDS = frozenset({"name", "value"})
REFERENCE_FIELDS = frozenset({"name", "target"})
IDENTITY_KINDS = frozenset({"id", "path", "waql", "scoped-name"})
_DYNAMIC_FIELD_NAME = re.compile(r"^[:_a-zA-Z0-9]+$")

RTPC_UNSUPPORTED_BOUNDARY = (
    "object.set RTPC editing is not exposed by the initial closed object operation: "
    "curve/list replacement, ControlInput resolution, versioned point-shape validation, "
    "full-list readback, and rollback semantics require a dedicated reviewed contract."
)


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
class ObjectNodeDescriptor:
    """One normalized node in a request-relative recursive object tree."""

    request_path: str
    parent_request_path: str | None
    type: str
    name: str
    notes: str | None
    properties: tuple[ObjectPropertyDescriptor, ...]
    references: tuple[ObjectReferenceDescriptor, ...]
    children: tuple[ObjectNodeDescriptor, ...]

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type, "name": self.name}
        if self.notes is not None:
            result["notes"] = self.notes
        if self.properties:
            result["properties"] = [item.as_dict() for item in self.properties]
        if self.references:
            result["references"] = [item.as_dict() for item in self.references]
        if self.children:
            result["children"] = [item.as_dict() for item in self.children]
        return result


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
) -> NormalizedObjectTree:
    """Normalize one root and return its deterministic request-relative list."""

    request_size = _request_size(payload, limits=limits, path=base_path)
    state = _NormalizationState(limits)
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
) -> ObjectNodeDescriptor:
    """Normalize one node when conflict policy is owned by a surrounding call."""

    return normalize_object_tree(payload, limits=limits, base_path=base_path).root


def normalize_object_forest(
    payload: Sequence[Mapping[str, Any]],
    *,
    on_name_conflict: str | ObjectConflictPolicy = ObjectConflictPolicy.FAIL,
    replace_owned: bool = False,
    limits: ObjectTreeLimits = ObjectTreeLimits(),
    base_path: str = "$",
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
    state = _NormalizationState(limits)
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


def normalize_rtpc_descriptors(payload: Any, *, request_path: str = "$.rtpcs") -> NoReturn:
    """Return the explicit first-release boundary for object.set RTPC lists."""

    raise ObjectOperationContractError(
        "RTPC_NOT_IMPLEMENTED",
        RTPC_UNSUPPORTED_BOUNDARY,
        details={"path": request_path, "supplied": payload is not None},
    )


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
) -> dict[str, Any]:
    """Build one trusted native WAAPI child object from normalized descriptors.

    ``resolved_references`` is keyed by each descriptor's request path (for
    example ``$.references[0]``).  Values must be canonical IDs produced by the
    live operation layer, never copied from model-authored dynamic fields.
    """

    resolved = dict(resolved_references or {})
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

    def build(current: ObjectNodeDescriptor) -> dict[str, Any]:
        result: dict[str, Any] = {"type": current.type, "name": current.name}
        if current.notes is not None:
            result["notes"] = current.notes
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
) -> tuple[ObjectResultNode, ...]:
    """Flatten an ``object.set`` result body, including each target association."""

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
    counter = [0]
    result: list[ObjectResultNode] = []
    for index, item in enumerate(objects):
        result.extend(
            _flatten_result_node(
                item,
                request_path=f"{base_path}[{index}]",
                parent_path=None,
                max_nodes=limit,
                counter=counter,
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
    def __init__(self, limits: ObjectTreeLimits) -> None:
        self.limits = limits
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
        _exact_fields(mapping, required={"type", "name"}, optional=NODE_FIELDS - {"type", "name"}, path=request_path)
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
            f"{path}.kind must be id, path, waql, or scoped-name.",
            details={"path": path, "kind": kind},
        )
    if kind in {"id", "path", "waql"}:
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
    parent = _normalize_identity(mapping.get("parent"), path=f"{path}.parent", limits=limits)
    if parent.kind not in {"id", "path"}:
        raise ObjectOperationContractError(
            "INVALID_IDENTITY",
            "A scoped-name identity parent must use a closed id or path identity.",
            details={"path": f"{path}.parent", "kind": parent.kind},
        )
    return ObjectIdentityDescriptor(kind=kind, name=name, type=object_type, parent=parent)


def _flatten_result_node(
    payload: Any,
    *,
    request_path: str,
    parent_path: str | None,
    max_nodes: int,
    counter: list[int],
) -> list[ObjectResultNode]:
    counter[0] += 1
    if counter[0] > max_nodes:
        raise ObjectOperationContractError(
            "RESULT_NODE_LIMIT_EXCEEDED",
            "The reflected object result exceeds the node limit.",
            details={"path": request_path, "count": counter[0], "limit": max_nodes},
        )
    mapping = _mapping(payload, path=request_path)
    object_id = mapping.get("id")
    _require_object_id(object_id, path=f"{request_path}.id")
    name = mapping.get("name")
    if not isinstance(name, str):
        raise ObjectOperationContractError(
            "INVALID_RESULT_SHAPE",
            f"{request_path}.name must be a string.",
            details={"path": f"{request_path}.name", "actual_type": type(name).__name__},
        )
    children = mapping.get("children", [])
    if not isinstance(children, list):
        raise ObjectOperationContractError(
            "INVALID_RESULT_SHAPE",
            f"{request_path}.children must be an array when present.",
            details={"path": f"{request_path}.children", "actual_type": type(children).__name__},
        )
    result = [ObjectResultNode(request_path, parent_path, object_id, name, len(children))]
    for index, child in enumerate(children):
        result.extend(
            _flatten_result_node(
                child,
                request_path=f"{request_path}.children[{index}]",
                parent_path=request_path,
                max_nodes=max_nodes,
                counter=counter,
            )
        )
    return result


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
    "ObjectNodeDescriptor",
    "ObjectOperationContractError",
    "ObjectPropertyDescriptor",
    "ObjectReferenceDescriptor",
    "ObjectResultBinding",
    "ObjectResultNode",
    "ObjectTopologyEdge",
    "ObjectTreeLimits",
    "RTPC_UNSUPPORTED_BOUNDARY",
    "bind_request_result_topology",
    "describe_conflict_policy",
    "flatten_create_result",
    "flatten_request_nodes",
    "flatten_set_result",
    "materialize_waapi_node",
    "normalize_conflict_policy",
    "normalize_object_forest",
    "normalize_object_node",
    "normalize_object_tree",
    "normalize_property_descriptors",
    "normalize_reference_descriptors",
    "normalize_rtpc_descriptors",
    "request_topology_edges",
]
