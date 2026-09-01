"""Wwise object identity capabilities shared by every public Gateway seam.

Object ``name`` is not uniform across the Authoring object graph. Most rows
own an intrinsic non-empty name, Actions expose an empty stored name and a
derived display path, and EffectSlots are anonymous owned-list entries. Keep
that distinction here so handles, collision proofs, and mutation operations do
not independently guess from one observed row.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ObjectIdentitySemantics:
    name_mode: str
    empty_name_allowed: bool
    mutable_intrinsic_name: bool
    display_identity_source: str


_DEFAULT = ObjectIdentitySemantics(
    name_mode="intrinsic",
    empty_name_allowed=False,
    mutable_intrinsic_name=True,
    display_identity_source="name_and_path",
)

_BY_OBJECT_TYPE = {
    "Action": ObjectIdentitySemantics(
        name_mode="derived",
        empty_name_allowed=True,
        mutable_intrinsic_name=False,
        display_identity_source="action_and_target_path",
    ),
    "EffectSlot": ObjectIdentitySemantics(
        name_mode="anonymous_slot",
        empty_name_allowed=True,
        mutable_intrinsic_name=False,
        display_identity_source="owner_and_collection_position",
    ),
}

NON_INTRINSIC_NAME_OBJECT_TYPES = frozenset(_BY_OBJECT_TYPE)


def object_identity_semantics(object_type: str) -> ObjectIdentitySemantics:
    """Return reviewed identity behavior for one exact reflected object type."""

    return _BY_OBJECT_TYPE.get(object_type, _DEFAULT)


__all__ = [
    "NON_INTRINSIC_NAME_OBJECT_TYPES",
    "ObjectIdentitySemantics",
    "object_identity_semantics",
]
