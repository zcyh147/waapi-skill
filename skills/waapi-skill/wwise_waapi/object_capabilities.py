"""Shared Wwise object identity and hierarchy capabilities.

The public Gateway must not infer universal object behavior from ordinary
named containers.  This module is the single in-process seam for two facts
that vary by reflected Wwise type: whether an object owns a mutable intrinsic
name, and whether it may own a requested child type in one supported version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ObjectIdentitySemantics:
    name_mode: str
    empty_name_allowed: bool
    mutable_intrinsic_name: bool
    display_identity_source: str
    relative_display_paths: tuple[str, ...] = ()
    opaque_display_path: bool = False


@dataclass(frozen=True, slots=True)
class ObjectChildCapability:
    parent_type: str
    writable_parent: bool
    invalid_child_types: tuple[str, ...]
    allowed_parent_types: tuple[str, ...]
    allowed_child_types: tuple[str, ...]
    required_parent_types_by_child: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def allowed(self) -> bool:
        return self.writable_parent and not self.invalid_child_types

    def required_parent_types_for(self, child_type: str) -> tuple[str, ...]:
        child_token = _object_type_token(child_type)
        return next(
            (
                parents
                for candidate, parents in self.required_parent_types_by_child
                if _object_type_token(candidate) == child_token
            ),
            (),
        )


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
    "Curve": _EMBEDDED_VALUE,
    "Modifier": _EMBEDDED_VALUE,
    "Panner": _EMBEDDED_VALUE,
    "Position": _EMBEDDED_VALUE,
    "RTPC": _EMBEDDED_VALUE,
    # Codec GUIDs are owned, anonymous objects, not hierarchy nodes. Retained
    # native packets return opaque display text rather than a hierarchy path.
    "ConversionPlugin": ObjectIdentitySemantics(
        name_mode="embedded_value", empty_name_allowed=True, mutable_intrinsic_name=False,
        display_identity_source="owner_and_embedded_role", opaque_display_path=True,
    ),
    "CustomState": _OWNED_COLLECTION_ENTRY,
    "MultiSwitchEntry": _OWNED_COLLECTION_ENTRY,
    "MusicPlaylistItem": _OWNED_COLLECTION_ENTRY,
    "MusicStinger": _OWNED_COLLECTION_ENTRY,
    "MusicTrackSequence": _OWNED_COLLECTION_ENTRY,
    # Live exact-GUID reads on 2022.1/2025.1 return this internal display path.
    # It is an identity comparison value, never a hierarchy selector.
    "MusicTransition": ObjectIdentitySemantics(
        name_mode="owned_collection_entry",
        empty_name_allowed=True,
        mutable_intrinsic_name=False,
        display_identity_source="owner_and_collection_role",
        relative_display_paths=(r"Root\Transition",),
    ),
    "StateGroupInfo": _OWNED_COLLECTION_ENTRY,
    # Native 2025.1 exact context-GUID readback exposes an unnamed association.
    # That observation establishes identity acceptance, not rename immutability.
    "ObjectSettingAssociation": ObjectIdentitySemantics(
        name_mode="intrinsic",
        empty_name_allowed=True,
        mutable_intrinsic_name=True,
        display_identity_source="name_and_path",
    ),
}

NON_INTRINSIC_NAME_OBJECT_TYPES = frozenset(
    name for name, semantics in _BY_OBJECT_TYPE.items() if not semantics.mutable_intrinsic_name
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
        "MusicPlaylistContainer",
        "MusicSegment",
    }
)
OBJECT_CREATE_SPECIALIZED_CHILD_TYPES_BY_PARENT = {
    "ControlSurfaceSession": frozenset({"ControlSurfaceBindingGroup"}),
    "ControlSurfaceBindingGroup": frozenset({"ControlSurfaceBindingGroup", "ControlSurfaceBinding"}),
    "Query": frozenset({"SearchCriteria"}),
    "Event": frozenset({"Action"}),
    "Bus": frozenset({"Bus", "AuxBus"}),
    "AuxBus": frozenset({"Bus", "AuxBus"}),
    "StateGroup": frozenset({"State"}),
    "SwitchGroup": frozenset({"Switch"}),
}
# A parent's child allowlist is not the inverse of a child's required parent:
# Bus/AuxBus may also be created under a WorkUnit. Inverse child placement
# requirements remain independent from each specialized parent's allowlist.
_OBJECT_CREATE_REQUIRED_PARENT_TYPES_BY_CHILD = {
    "WorkUnit": frozenset({"WorkUnit", "Folder"}),
    "Query": frozenset({"WorkUnit", "Folder"}),
    "SearchCriteria": frozenset({"Query"}),
    "ControlSurfaceBindingGroup": frozenset({"ControlSurfaceSession", "ControlSurfaceBindingGroup"}),
    "ControlSurfaceBinding": frozenset({"ControlSurfaceBindingGroup"}),
    "Action": frozenset({"Event"}),
    "State": frozenset({"StateGroup"}),
    "Switch": frozenset({"SwitchGroup"}),
}
OBJECT_CREATE_REFLECTED_PARENT_TYPES_BY_VERSION = {
    "2025.1": frozenset({"PropertyContainer"}),
}


def _object_type_token(value: object) -> str:
    return "".join(
        character
        for character in str(value).casefold()
        if character.isalnum()
    )


def object_identity_semantics(object_type: str) -> ObjectIdentitySemantics:
    """Return reviewed identity behavior for one exact reflected object type."""

    return _BY_OBJECT_TYPE.get(object_type, _DEFAULT)


def reviewed_existing_display_identity(*, version: str | None, object_type: str,
                                      name: object, path: object) -> bool:
    """Recognize reviewed exact-GUID display facts, never selector/name authority.

    The #195 owned-role survey observed these shapes on 2025.1.7.9143.
    Language, UserProjectSettings and MidiParameter have matching class/type
    definitions in all five lanes; MediaPoolQuery is introduced in 2025. These
    rules accept a matching live shape, without claiming it was seen on every
    version or treating its text as a hierarchy path.
    This comparison-only admission neither constructs nor renames an object.
    """
    if (version not in {"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"}
            or not isinstance(name, str) or not isinstance(path, str)):
        return False
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in name + path):
        return False
    if object_type == "UserProjectSettings":
        return name == "" and path == "<Unnamed Default Object Values>"
    if not name or name != name.strip() or any(character in name for character in "\\/"):
        return False
    if object_type == "Language" or (version == "2025.1" and object_type == "MediaPoolQuery"):
        return path == name
    if object_type == "MidiParameter":
        parts = path.split("\\")
        return (len(parts) >= 2 and parts[0] == "MIDI" and parts[-1] == name
                and all(part and part not in {".", ".."} and "/" not in part for part in parts))
    return False


def object_child_capability(
    *,
    version: str,
    parent_type: object,
    child_types: Sequence[object],
) -> ObjectChildCapability:
    """Return one closed parent/child decision shared by every mutation seam."""

    parent_text = str(parent_type)
    parent_token = _object_type_token(parent_text)
    allowed_parent_types = tuple(
        sorted(
            OBJECT_CREATE_WRITABLE_PARENT_TYPES
            | frozenset(OBJECT_CREATE_SPECIALIZED_CHILD_TYPES_BY_PARENT)
            | OBJECT_CREATE_REFLECTED_PARENT_TYPES_BY_VERSION.get(
                version,
                frozenset(),
            ),
            key=str.casefold,
        )
    )
    writable_parent = parent_token in {
        _object_type_token(item) for item in allowed_parent_types
    }
    specialized_parent = next(
        (
            (name, allowed)
            for name, allowed in OBJECT_CREATE_SPECIALIZED_CHILD_TYPES_BY_PARENT.items()
            if _object_type_token(name) == parent_token
        ),
        None,
    )
    allowed_child_types = tuple(
        sorted(specialized_parent[1], key=str.casefold)
    ) if specialized_parent is not None else ()
    allowed_child_tokens = {
        _object_type_token(item) for item in allowed_child_types
    }
    requirements = tuple(
        sorted(
            (
                child,
                tuple(sorted(parents)),
            )
            for child, parents in _OBJECT_CREATE_REQUIRED_PARENT_TYPES_BY_CHILD.items()
        )
    )
    invalid: set[str] = set()
    for child_type in child_types:
        child_text = str(child_type)
        child_token = _object_type_token(child_text)
        if specialized_parent is not None and child_token not in allowed_child_tokens:
            invalid.add(child_text)
            continue
        required_parents = next(
            (
                parents
                for child, parents in requirements
                if _object_type_token(child) == child_token
            ),
            (),
        )
        if required_parents and parent_token not in {
            _object_type_token(item) for item in required_parents
        }:
            invalid.add(child_text)
    return ObjectChildCapability(
        parent_type=parent_text,
        writable_parent=writable_parent,
        invalid_child_types=tuple(sorted(invalid, key=str.casefold)),
        allowed_parent_types=allowed_parent_types,
        allowed_child_types=allowed_child_types,
        required_parent_types_by_child=requirements,
    )


def object_transfer_parent_compatible(*, version: str, parent_type: object, child_type: object) -> bool:
    """Transfer admission is distinct from creating an object of this class."""
    if parent_type in {"ControlSurfaceSession", "ControlSurfaceBindingGroup"}:
        # Constructor role admission does not grant copy/move authority on
        # reserved or user groups; those operations need their own role proof.
        return False
    if child_type in {"Source", "SourcePlugin", "AudioFileSource"}:
        # Existing Source identity carries the plugin/file class. The public
        # preparation seam separately certifies that class and the Sound owner.
        return parent_type == "Sound"
    return object_child_capability(version=version, parent_type=parent_type, child_types=(child_type,)).allowed


__all__ = [
    "NON_INTRINSIC_NAME_OBJECT_TYPES",
    "OBJECT_CREATE_REFLECTED_PARENT_TYPES_BY_VERSION",
    "OBJECT_CREATE_SPECIALIZED_CHILD_TYPES_BY_PARENT",
    "OBJECT_CREATE_WRITABLE_PARENT_TYPES",
    "ObjectChildCapability",
    "ObjectIdentitySemantics",
    "object_child_capability",
    "object_identity_semantics",
]
