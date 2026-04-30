"""Object identity contracts and resolution plans for semantic builders."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .common import SemanticErrorCode, SemanticReadbackPlan, SemanticValidationError

OBJECT_GET_URI = "ak.wwise.core.object.get"
DEFAULT_IDENTITY_RETURN_FIELDS = ("id", "name", "type", "path", "parent")


class ObjectIdentityKind(str, Enum):
    """Supported semantic object identity shapes."""

    EXACT_ID = "exact-id"
    EXACT_PATH = "exact-path"
    WAQL = "waql"
    SCOPED_NAME = "scoped-name"


@dataclass(slots=True, frozen=True)
class ObjectIdentity:
    """Caller-supplied object identity before any live or fake readback."""

    id: str | int | None = None
    path: str | None = None
    waql: str | None = None
    name: str | None = None
    type: str | None = None
    parent: str | None = None

    @property
    def kind(self) -> ObjectIdentityKind:
        shapes = self._shapes()
        if len(shapes) == 1:
            return shapes[0]
        raise IdentityAmbiguityError(
            "Object identity must specify exactly one shape: explicit id/GUID, exact path, WAQL, or name scoped by type and parent.",
            details={"identity": self.as_dict(), "shapes": [shape.value for shape in shapes]},
        )

    def _shapes(self) -> tuple[ObjectIdentityKind, ...]:
        shapes: list[ObjectIdentityKind] = []
        if _valid_id(self.id):
            shapes.append(ObjectIdentityKind.EXACT_ID)
        if _non_empty(self.path):
            shapes.append(ObjectIdentityKind.EXACT_PATH)
        if _non_empty(self.waql):
            shapes.append(ObjectIdentityKind.WAQL)
        if _non_empty(self.name) and _non_empty(self.type) and _non_empty(self.parent):
            shapes.append(ObjectIdentityKind.SCOPED_NAME)
        return tuple(shapes)

    @property
    def is_exact(self) -> bool:
        return self.kind in {ObjectIdentityKind.EXACT_ID, ObjectIdentityKind.EXACT_PATH}

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "path": self.path, "waql": self.waql, "name": self.name, "type": self.type, "parent": self.parent}


@dataclass(slots=True, frozen=True)
class ResolvedObject:
    """Object identity proven exact by input contract or one-row readback."""

    identity: ObjectIdentity
    object: str | int
    resolution: str
    row: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_exact(self) -> bool:
        return True

    def as_dict(self) -> dict[str, Any]:
        return {"identity": self.identity.as_dict(), "object": self.object, "resolution": self.resolution, "row": dict(self.row)}


@dataclass(slots=True, frozen=True)
class ResolutionPlan:
    """Planned object.get lookup that a caller can execute with a fake or live client."""

    identity: ObjectIdentity
    readback_plan: SemanticReadbackPlan
    destructive_use: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"identity": self.identity.as_dict(), "readback_plan": self.readback_plan.as_dict(), "destructive_use": self.destructive_use}


class IdentityAmbiguityError(SemanticValidationError):
    """Raised when an object identity cannot be proven to one target."""

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY, message, details=details)


def plan_object_resolution(identity: ObjectIdentity, *, destructive_use: bool = False) -> ResolutionPlan | ResolvedObject:
    """Accept exact identities immediately or return an object.get readback plan."""

    kind = identity.kind
    if kind == ObjectIdentityKind.EXACT_ID:
        assert identity.id is not None
        return ResolvedObject(identity=identity, object=identity.id, resolution=kind.value, row={"id": identity.id})
    if kind == ObjectIdentityKind.EXACT_PATH:
        assert identity.path is not None
        return ResolvedObject(identity=identity, object=identity.path, resolution=kind.value, row={"path": identity.path})
    return ResolutionPlan(identity=identity, readback_plan=_readback_plan(identity), destructive_use=destructive_use)


def resolve_object_identity(
    identity: ObjectIdentity,
    rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    *,
    destructive_use: bool = False,
) -> ResolvedObject | ResolutionPlan:
    """Resolve an identity from supplied object.get rows, failing closed for ambiguity."""

    planned = plan_object_resolution(identity, destructive_use=destructive_use)
    if isinstance(planned, ResolvedObject):
        return planned
    if rows is None:
        if destructive_use:
            raise IdentityAmbiguityError(
                "Destructive use requires object.get resolution to exactly one row before envelope generation.",
                details={"identity": identity.as_dict(), "plan": planned.as_dict(), "row_count": None},
            )
        return planned
    return resolve_resolution_plan(planned, rows)


def resolve_resolution_plan(plan: ResolutionPlan, rows: Sequence[Mapping[str, Any]] | Mapping[str, Any]) -> ResolvedObject:
    """Convert an object.get readback result into one resolved object or a typed ambiguity error."""

    normalized = _rows(rows)
    matching = tuple(row for row in normalized if _row_matches(plan.identity, row))
    if len(normalized) != 1 or len(matching) != 1:
        raise IdentityAmbiguityError(
            "Object identity resolution readback must return exactly one row and that row must match the identity.",
            details={
                "identity": plan.identity.as_dict(),
                "row_count": len(normalized),
                "matching_row_count": len(matching),
                "rows": [dict(row) for row in normalized],
            },
        )
    row = matching[0]
    object_value = row.get("id") or row.get("path")
    if object_value is None:
        raise IdentityAmbiguityError(
            "Resolved object row must contain id or path.",
            details={"identity": plan.identity.as_dict(), "row": dict(row)},
        )
    return ResolvedObject(identity=plan.identity, object=object_value, resolution=plan.identity.kind.value, row=dict(row))


def _readback_plan(identity: ObjectIdentity) -> SemanticReadbackPlan:
    if identity.kind == ObjectIdentityKind.WAQL:
        args = {"waql": identity.waql}
    else:
        args = {"waql": _scoped_name_waql(identity)}
    return SemanticReadbackPlan(
        OBJECT_GET_URI,
        args=args,
        options={"return": list(DEFAULT_IDENTITY_RETURN_FIELDS)},
        description="resolve semantic object identity to exactly one row",
    )


def _scoped_name_waql(identity: ObjectIdentity) -> str:
    assert identity.name is not None
    assert identity.type is not None
    assert identity.parent is not None
    return (
        f'from object {_quote(identity.parent)} '
        f'transform select children '
        f'where type = {_quote(identity.type)} and name = {_quote(identity.name)}'
    )


def _row_matches(identity: ObjectIdentity, row: Mapping[str, Any]) -> bool:
    kind = identity.kind
    if kind == ObjectIdentityKind.WAQL:
        return True
    if kind == ObjectIdentityKind.SCOPED_NAME:
        parent = row.get("parent")
        parent_match = parent == identity.parent
        if isinstance(parent, Mapping):
            parent_match = parent.get("id") == identity.parent or parent.get("path") == identity.parent or parent.get("name") == identity.parent
        return row.get("name") == identity.name and row.get("type") == identity.type and parent_match
    return True


def _rows(rows: Sequence[Mapping[str, Any]] | Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    if isinstance(rows, Mapping):
        value = rows.get("return")
        if isinstance(value, list):
            return tuple(row for row in value if isinstance(row, Mapping))
        return ()
    return tuple(row for row in rows if isinstance(row, Mapping))


def _valid_id(value: str | int | None) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, int):
        return True
    return _non_empty(value)


def _non_empty(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('\"', '\\"') + '"'
