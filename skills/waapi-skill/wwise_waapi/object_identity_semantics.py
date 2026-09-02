"""Wwise object identity capabilities shared by every public Gateway seam.

Object ``name`` is not uniform across the Authoring object graph. Most rows
own an intrinsic non-empty name, while derived, embedded, and owned-list rows
may expose an empty or fixed implementation name. Keep that distinction here
so handles, collision proofs, and mutation operations do not independently
guess from one observed row.

The reviewed exceptions are checked against the five committed reflected
object-type catalogs and SampleProject work units. A newly observed empty-name
``WObject`` therefore fails the program gate until it is classified here.
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

_EMBEDDED_VALUE = ObjectIdentitySemantics(
    name_mode="embedded_value",
    empty_name_allowed=True,
    mutable_intrinsic_name=False,
    display_identity_source="owner_and_embedded_role",
)

_OWNED_COLLECTION_ENTRY = ObjectIdentitySemantics(
    name_mode="owned_collection_entry",
    empty_name_allowed=True,
    mutable_intrinsic_name=False,
    display_identity_source="owner_and_collection_role",
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
    # Property graphs and spatial configuration rows are implementation-owned
    # values. Their XML/WAAPI names are empty or fixed property labels, not
    # caller-controlled object identities.
    "Curve": _EMBEDDED_VALUE,
    "Modifier": _EMBEDDED_VALUE,
    "Panner": _EMBEDDED_VALUE,
    "Position": _EMBEDDED_VALUE,
    "RTPC": _EMBEDDED_VALUE,
    # Music, state, and switch subgraphs expose list entries as WObjects, but
    # identify them through their owner, role, target, or collection position.
    "CustomState": _OWNED_COLLECTION_ENTRY,
    "MultiSwitchEntry": _OWNED_COLLECTION_ENTRY,
    "MusicPlaylistItem": _OWNED_COLLECTION_ENTRY,
    "MusicStinger": _OWNED_COLLECTION_ENTRY,
    "MusicTrackSequence": _OWNED_COLLECTION_ENTRY,
    "StateGroupInfo": _OWNED_COLLECTION_ENTRY,
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
