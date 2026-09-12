"""Closed, version-aware structures for creating Source and Effect plug-ins.

This module is intentionally pure and is not itself a public gateway route.
The packaged ``object.createPlugin`` operation uses it after resolving one
exact target and reading live ``getPropertyInfo`` metadata.

The Wwise object model differs materially by version:

* Source plug-ins are new ``Source`` children of a Sound/Voice target.
* Wwise 2022.1 Effect plug-ins occupy the first proven-empty fixed
  ``@Effect0`` through ``@Effect3`` reference.
* Wwise 2023.1 and later append one ``EffectSlot`` to ``@Effects`` and create
  the new ``Effect`` behind that slot's ``@Effect`` reference.

The caller supplies the exact uint32 plug-in ``class_id``.  This module never
maps a display name to a class ID, never emits ``replaceAll``, and never
replaces an occupied fixed Effect reference.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


OBJECT_SET_URI = "ak.wwise.core.object.set"
GET_PROPERTY_INFO_URI = "ak.wwise.core.object.getPropertyInfo"
SUPPORTED_PLUGIN_VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")
UINT32_MAX = 4_294_967_295
MAX_PLUGIN_PROPERTIES = 32
MAX_PLUGIN_NAME_LENGTH = 255
MAX_PLUGIN_NOTES_LENGTH = 64 * 1024
MAX_PLUGIN_FIELD_NAME_LENGTH = 128
PLUGIN_KINDS = frozenset({"source", "effect"})
SOURCE_TARGET_TYPES = frozenset({"Sound", "Voice"})
WWISE_2022_EFFECT_FIELDS = ("@Effect0", "@Effect1", "@Effect2", "@Effect3")
PLUGIN_VERIFICATION_FIELDS = (
    "id",
    "name",
    "type",
    "classId",
    "parent",
    "owner",
)
PLUGIN_LANGUAGE_READBACK_FIELD = "audioSource:language"
PLUGIN_EFFECT_SLOT_READBACK_FIELDS = (
    "id",
    "name",
    "type",
    "parent",
    "owner",
    "@Effect",
)
PLUGIN_2022_EFFECT_TARGET_READBACK_FIELDS = (
    "id",
    *WWISE_2022_EFFECT_FIELDS,
)
PLUGIN_READBACK_VIEW_FIELDS = frozenset(
    {"fields", "language", "platform"}
)
PLUGIN_REAL32_REL_TOLERANCE = 1e-6
PLUGIN_REAL32_ABS_TOLERANCE = 1e-6
PLUGIN_REAL64_REL_TOLERANCE = 1e-12
PLUGIN_REAL64_ABS_TOLERANCE = 1e-12

_PLUGIN_REQUEST_FIELDS = frozenset(
    {
        "kind",
        "name",
        "class_id",
        "notes",
        "platform",
        "language",
        "properties",
    }
)
_PLUGIN_PROPERTY_FIELDS = frozenset({"name", "value"})
_SOURCE_PLACEMENT_EVIDENCE_FIELDS = frozenset({"kind"})
_FIXED_EFFECT_PLACEMENT_EVIDENCE_FIELDS = frozenset(
    {
        "kind",
        "pre_effect_references",
        "selected_effect_field",
        "target_post_readback",
    }
)
_APPENDED_EFFECT_PLACEMENT_EVIDENCE_FIELDS = frozenset(
    {
        "kind",
        "preexisting_effect_slot_ids",
        "created_effect_slot",
    }
)
_OBJECT_REFERENCE_FIELDS = frozenset({"id", "name", "path", "type"})
_FIELD_NAME = re.compile(r"^[:_a-zA-Z0-9]+$")
_GUID = re.compile(
    r"^\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}$"
)
_REAL32_PROPERTY_TYPES = frozenset({"real32", "float"})
_REAL64_PROPERTY_TYPES = frozenset({"real64", "double"})
_REAL_PROPERTY_TYPES = _REAL32_PROPERTY_TYPES | _REAL64_PROPERTY_TYPES
_INTEGER_PROPERTY_TYPES = frozenset(
    {
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "integer",
    }
)
_BOOLEAN_PROPERTY_TYPES = frozenset({"bool", "boolean"})
_STRING_PROPERTY_TYPES = frozenset({"string", "cstring"})


JsonScalar = str | int | float | bool


class PluginOperationContractError(ValueError):
    """The plug-in creation request or evidence is outside the closed contract."""

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


@dataclass(frozen=True, slots=True)
class PluginProperty:
    name: str
    value: JsonScalar

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True, slots=True)
class ValidatedPluginProperty:
    """One requested scalar bound to live ``getPropertyInfo`` name/type."""

    name: str
    value: JsonScalar
    metadata_type: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "metadata_type": self.metadata_type,
        }


@dataclass(frozen=True, slots=True)
class PluginCreationDescriptor:
    kind: str
    name: str
    class_id: int
    notes: str | None
    platform: str | None
    language: str | None
    properties: tuple[PluginProperty, ...]

    @property
    def object_type(self) -> str:
        return "Source" if self.kind == "source" else "Effect"

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind,
            "name": self.name,
            "class_id": self.class_id,
            "properties": [item.as_dict() for item in self.properties],
        }
        if self.notes is not None:
            result["notes"] = self.notes
        if self.platform is not None:
            result["platform"] = self.platform
        if self.language is not None:
            result["language"] = self.language
        return result


@dataclass(frozen=True, slots=True)
class PluginCreationPlan:
    """One dispatch-ready create/append-only object.set plan."""

    version: str
    target_id: str
    target_type: str
    descriptor: PluginCreationDescriptor
    validated_properties: tuple[ValidatedPluginProperty, ...]
    placement: Mapping[str, Any]
    dispatch_args: Mapping[str, Any]
    verification: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": "object.createPlugin",
            "version": self.version,
            "target": {"id": self.target_id, "type": self.target_type},
            "plugin": self.descriptor.as_dict(),
            "property_validation": [
                item.as_dict() for item in self.validated_properties
            ],
            "placement": dict(self.placement),
            "dispatch": {
                "uri": OBJECT_SET_URI,
                "args": _json_copy(self.dispatch_args),
                "options": {},
            },
            "verification": _json_copy(self.verification),
        }


@dataclass(frozen=True, slots=True)
class PluginVerificationEvidence:
    plugin_id: str
    name: str
    type: str
    class_id: int
    parent_id: str
    owner_id: str
    readback_view: Mapping[str, Any]
    requested_state: Mapping[str, Any]
    placement: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.plugin_id,
            "name": self.name,
            "type": self.type,
            "classId": self.class_id,
            "parent": self.parent_id,
            "owner": self.owner_id,
            "readback_view": _json_copy(self.readback_view),
            "requested_state": _json_copy(self.requested_state),
            "placement": _json_copy(self.placement),
        }


def normalize_plugin_creation(payload: Any) -> PluginCreationDescriptor:
    """Validate the closed public plug-in descriptor without guessing class ID."""

    if not isinstance(payload, Mapping):
        raise PluginOperationContractError(
            "INVALID_ARGUMENT",
            "Plug-in creation arguments must be an object.",
        )
    unknown = set(payload) - _PLUGIN_REQUEST_FIELDS
    missing = {"kind", "name", "class_id"} - set(payload)
    if unknown or missing:
        raise PluginOperationContractError(
            "INVALID_ARGUMENT",
            "Plug-in creation arguments contain unknown or missing fields.",
            details={"missing": sorted(missing), "unknown": sorted(unknown)},
        )

    kind = payload.get("kind")
    if kind not in PLUGIN_KINDS:
        raise PluginOperationContractError(
            "INVALID_ARGUMENT",
            "kind must be 'source' or 'effect'.",
        )
    name = _bounded_text(
        payload.get("name"),
        field="name",
        maximum=MAX_PLUGIN_NAME_LENGTH,
        allow_empty=False,
    )
    if any(character in name for character in "\\/:*?\"<>|"):
        raise PluginOperationContractError(
            "INVALID_ARGUMENT",
            "Plug-in name contains a path or reserved filename character.",
        )

    class_id = payload.get("class_id")
    if type(class_id) is not int or not 1 <= class_id <= UINT32_MAX:
        raise PluginOperationContractError(
            "INVALID_ARGUMENT",
            f"class_id must be an exact integer in [1, {UINT32_MAX}]; "
            "the Skill never guesses it from a plug-in name.",
        )

    notes_value = payload.get("notes")
    notes = (
        None
        if notes_value is None
        else _bounded_text(
            notes_value,
            field="notes",
            maximum=MAX_PLUGIN_NOTES_LENGTH,
            allow_empty=True,
        )
    )
    platform_value = payload.get("platform")
    platform = (
        None
        if platform_value is None
        else _bounded_text(
            platform_value,
            field="platform",
            maximum=255,
            allow_empty=False,
        )
    )
    language_value = payload.get("language")
    language = (
        None
        if language_value is None
        else _bounded_text(
            language_value,
            field="language",
            maximum=255,
            allow_empty=False,
        )
    )
    if kind == "effect" and language is not None:
        raise PluginOperationContractError(
            "INVALID_ARGUMENT",
            "language is accepted only for Source plug-in creation.",
        )
    properties = _normalize_properties(payload.get("properties", []))
    return PluginCreationDescriptor(
        kind=str(kind),
        name=name,
        class_id=class_id,
        notes=notes,
        platform=platform,
        language=language,
        properties=properties,
    )


def plugin_property_metadata_requests(
    descriptor: PluginCreationDescriptor,
) -> tuple[dict[str, Any], ...]:
    """Return the exact live reads required before any property is materialized."""

    return tuple(
        {
            "uri": GET_PROPERTY_INFO_URI,
            "args": {
                "classId": descriptor.class_id,
                "property": prop.name,
            },
            "options": {},
        }
        for prop in descriptor.properties
    )


def plugin_verification_fields(
    descriptor: PluginCreationDescriptor,
) -> tuple[str, ...]:
    """Return the exact object.get fields required for this descriptor."""

    fields = list(PLUGIN_VERIFICATION_FIELDS)
    if descriptor.notes is not None:
        fields.append("notes")
    if descriptor.language is not None:
        fields.append(PLUGIN_LANGUAGE_READBACK_FIELD)
    fields.extend(f"@{prop.name}" for prop in descriptor.properties)
    if len(set(fields)) != len(fields):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            "Plug-in verification fields contain a duplicate accessor.",
            details={"fields": fields},
        )
    return tuple(fields)


def validate_plugin_property_metadata(
    descriptor: PluginCreationDescriptor,
    metadata_rows: Sequence[Mapping[str, Any]] | None,
) -> tuple[ValidatedPluginProperty, ...]:
    """Bind every requested property to one exact live metadata name and type."""

    if not descriptor.properties:
        if metadata_rows not in (None, (), []):
            raise PluginOperationContractError(
                "UNEXPECTED_PROPERTY_METADATA",
                "Property metadata was supplied for a request with no properties.",
            )
        return ()
    if metadata_rows is None:
        raise PluginOperationContractError(
            "PROPERTY_METADATA_REQUIRED",
            "Every plug-in property requires a live getPropertyInfo result "
            "scoped by the exact classId.",
            details={
                "requests": [
                    item for item in plugin_property_metadata_requests(descriptor)
                ]
            },
        )
    if isinstance(metadata_rows, (str, bytes)) or not isinstance(
        metadata_rows, Sequence
    ):
        raise PluginOperationContractError(
            "INVALID_PROPERTY_METADATA",
            "Property metadata must be an ordered array of getPropertyInfo rows.",
        )
    if len(metadata_rows) != len(descriptor.properties):
        raise PluginOperationContractError(
            "INVALID_PROPERTY_METADATA",
            "Property metadata count does not match the requested property count.",
            details={
                "requested": len(descriptor.properties),
                "received": len(metadata_rows),
            },
        )

    validated: list[ValidatedPluginProperty] = []
    for index, (prop, row) in enumerate(zip(descriptor.properties, metadata_rows)):
        if not isinstance(row, Mapping):
            raise PluginOperationContractError(
                "INVALID_PROPERTY_METADATA",
                f"Property metadata row {index} must be an object.",
            )
        metadata_name = row.get("name")
        metadata_type = row.get("type")
        if metadata_name != prop.name or not isinstance(metadata_type, str):
            raise PluginOperationContractError(
                "INVALID_PROPERTY_METADATA",
                "getPropertyInfo returned a different property name or no type.",
                details={
                    "requested": prop.name,
                    "actual_name": metadata_name,
                    "actual_type": metadata_type,
                },
            )
        _require_metadata_value_type(
            name=prop.name,
            metadata_type=metadata_type,
            value=prop.value,
        )
        validated.append(
            ValidatedPluginProperty(
                name=prop.name,
                value=prop.value,
                metadata_type=metadata_type,
            )
        )
    return tuple(validated)


def build_plugin_creation_plan(
    *,
    version: str,
    target_id: str,
    target_type: str,
    request: Mapping[str, Any] | PluginCreationDescriptor,
    property_metadata: Sequence[Mapping[str, Any]] | None = None,
    effect_slots_2022: Mapping[str, Any] | None = None,
) -> PluginCreationPlan:
    """Build one version-correct object.set plan after live metadata validation."""

    if version not in SUPPORTED_PLUGIN_VERSIONS:
        raise PluginOperationContractError(
            "UNAVAILABLE_IN_VERSION",
            "object.createPlugin is packaged only for Wwise 2022.1-2025.1.",
            details={
                "version": version,
                "supported_versions": list(SUPPORTED_PLUGIN_VERSIONS),
            },
        )
    target_id = _require_guid(target_id, field="target_id")
    target_type = _bounded_text(
        target_type,
        field="target_type",
        maximum=128,
        allow_empty=False,
    )
    descriptor = (
        request
        if isinstance(request, PluginCreationDescriptor)
        else normalize_plugin_creation(request)
    )
    validated = validate_plugin_property_metadata(descriptor, property_metadata)
    plugin_object = _materialize_plugin_object(descriptor, validated)

    if descriptor.kind == "source":
        if target_type not in SOURCE_TARGET_TYPES:
            raise PluginOperationContractError(
                "INVALID_SOURCE_TARGET",
                "Source plug-ins may be created only as children of a live "
                "Sound or Voice target.",
                details={
                    "target_type": target_type,
                    "allowed": sorted(SOURCE_TARGET_TYPES),
                },
            )
        if effect_slots_2022 is not None:
            raise PluginOperationContractError(
                "UNEXPECTED_EFFECT_SLOT_SNAPSHOT",
                "Source creation does not accept Effect-slot evidence.",
            )
        object_spec = {
            "object": target_id,
            "onNameConflict": "fail",
            "children": [plugin_object],
        }
        placement: dict[str, Any] = {
            "kind": "source_child",
            "collection": "children",
            "create_only": True,
            "on_name_conflict": "fail",
            "raw_replace_all_allowed": False,
            "replace_existing_allowed": False,
        }
        expected_parent: dict[str, Any] = {"kind": "id", "value": target_id}
    elif version == "2022.1":
        selected_slot = select_free_2022_effect_field(effect_slots_2022)
        object_spec = {
            "object": target_id,
            selected_slot: plugin_object,
        }
        placement = {
            "kind": "fixed_effect_reference",
            "collection": selected_slot,
            "effect_slot": selected_slot,
            "create_only": True,
            "requires_proven_empty_slot": True,
            "raw_replace_all_allowed": False,
            "replace_existing_allowed": False,
        }
        expected_parent = {"kind": "id", "value": target_id}
    else:
        if effect_slots_2022 is not None:
            raise PluginOperationContractError(
                "UNEXPECTED_EFFECT_SLOT_SNAPSHOT",
                "Wwise 2023.1+ Effect creation appends @Effects and does not "
                "accept the Wwise 2022 fixed-slot snapshot.",
            )
        effect_slot = {
            "type": "EffectSlot",
            "name": "",
            "@Effect": plugin_object,
        }
        object_spec = {
            "object": target_id,
            "listMode": "append",
            "@Effects": [effect_slot],
        }
        placement = {
            "kind": "effect_slot_append",
            "collection": "@Effects",
            "list_mode": "append",
            "effect_slot_type": "EffectSlot",
            "create_only": True,
            "raw_replace_all_allowed": False,
            "replace_existing_allowed": False,
        }
        expected_parent = {"kind": "created_effect_slot"}

    dispatch_args = {
        "objects": [object_spec],
        "autoAddToSourceControl": False,
    }
    expected_plugin: dict[str, Any] = {
        "name": descriptor.name,
        "type": descriptor.object_type,
        "classId": descriptor.class_id,
        "parent": expected_parent,
        "owner": {"kind": "id", "value": target_id},
        "properties": [
            item.as_dict() for item in validated
        ],
    }
    if descriptor.notes is not None:
        expected_plugin["notes"] = descriptor.notes
    if descriptor.language is not None:
        expected_plugin["language"] = descriptor.language
    verification = {
        "readback_fields": list(plugin_verification_fields(descriptor)),
        "readback_view": {
            "language": descriptor.language,
            "platform": descriptor.platform,
        },
        "expected_plugin": expected_plugin,
        "require_new_plugin_id": True,
        "business_state_verified_only_by_readback": True,
    }
    return PluginCreationPlan(
        version=version,
        target_id=target_id,
        target_type=target_type,
        descriptor=descriptor,
        validated_properties=validated,
        placement=placement,
        dispatch_args=dispatch_args,
        verification=verification,
    )


def select_free_2022_effect_field(
    snapshot: Mapping[str, Any] | None,
) -> str:
    """Select the first fixed Effect field only from a complete null snapshot."""

    if not isinstance(snapshot, Mapping):
        raise PluginOperationContractError(
            "EFFECT_SLOT_SNAPSHOT_REQUIRED",
            "Wwise 2022.1 Effect creation requires all four fixed Effect fields.",
            details={"required_fields": list(WWISE_2022_EFFECT_FIELDS)},
        )
    missing = set(WWISE_2022_EFFECT_FIELDS) - set(snapshot)
    unknown = set(snapshot) - set(WWISE_2022_EFFECT_FIELDS)
    if missing or unknown:
        raise PluginOperationContractError(
            "INVALID_EFFECT_SLOT_SNAPSHOT",
            "The Wwise 2022.1 fixed Effect snapshot is incomplete or contains "
            "unreviewed fields.",
            details={"missing": sorted(missing), "unknown": sorted(unknown)},
        )
    for field in WWISE_2022_EFFECT_FIELDS:
        if snapshot[field] is None:
            return field
    raise PluginOperationContractError(
        "NO_FREE_EFFECT_SLOT",
        "All four Wwise 2022.1 fixed Effect slots are occupied; "
        "object.createPlugin never replaces an existing Effect.",
        details={"fields": list(WWISE_2022_EFFECT_FIELDS)},
    )


def verify_created_plugin_row(
    descriptor: PluginCreationDescriptor,
    row: Mapping[str, Any],
    *,
    version: str,
    expected_parent_id: str,
    expected_owner_id: str,
    validated_properties: Sequence[ValidatedPluginProperty],
    preexisting_plugin_ids: Sequence[str],
    readback_view: Mapping[str, Any],
    placement_evidence: Mapping[str, Any],
) -> PluginVerificationEvidence:
    """Validate the complete requested state and version-specific placement.

    ``readback_view`` binds the row to the exact object.get projection and its
    language/platform options. ``placement_evidence`` is a closed,
    lane-specific object:

    * Source: ``{"kind": "source_child"}``.
    * Wwise 2022.1 Effect: the selected fixed field, complete pre-state, and
      complete target post-read.
    * Wwise 2023.1+ Effect: the complete created EffectSlot row plus all
      pre-existing EffectSlot IDs.

    The caller must provide every argument, even when a sequence is empty or a
    view value is null. There is intentionally no compatibility path back to
    identity-only verification.
    """

    if version not in SUPPORTED_PLUGIN_VERSIONS:
        raise PluginOperationContractError(
            "UNAVAILABLE_IN_VERSION",
            "Plug-in verification is available only for Wwise "
            "2022.1-2025.1.",
            details={
                "version": version,
                "supported_versions": list(SUPPORTED_PLUGIN_VERSIONS),
            },
        )
    if not isinstance(row, Mapping):
        raise PluginOperationContractError(
            "INVALID_PLUGIN_READBACK",
            "Plug-in readback must be an object.",
        )
    normalized_properties = _validate_verification_properties(
        descriptor,
        validated_properties,
    )
    normalized_view = _validate_plugin_readback_view(
        descriptor,
        readback_view,
    )
    expected_fields = plugin_verification_fields(descriptor)
    actual_fields = tuple(row)
    effect_owner_only = descriptor.kind == "effect" and "parent" not in row
    allowed_missing_fields = (
        {"owner"} if descriptor.kind == "source" else {"parent"}
    )
    if (
        set(actual_fields) - set(expected_fields)
        or (set(expected_fields) - set(actual_fields)) - allowed_missing_fields
    ):
        raise PluginOperationContractError(
            "INVALID_PLUGIN_READBACK",
            "Plug-in readback fields do not match the closed descriptor "
            "projection.",
            details={
                "expected_fields": list(expected_fields),
                "missing": sorted(set(expected_fields) - set(actual_fields)),
                "unknown": sorted(set(actual_fields) - set(expected_fields)),
            },
        )

    plugin_id = _require_guid(row.get("id"), field="plugin.id")
    parent_id = _closed_object_reference_id(
        row.get("owner") if effect_owner_only else row.get("parent"),
        field="plugin.parent",
    )
    owner_id = _closed_object_reference_id(
        row.get("owner", row.get("parent")),
        field="plugin.owner",
    )
    expected_parent_id = _require_guid(
        expected_parent_id,
        field="expected_parent_id",
    )
    expected_owner_id = _require_guid(
        expected_owner_id,
        field="expected_owner_id",
    )
    normalized_preexisting = _normalize_guid_sequence(
        preexisting_plugin_ids,
        field="preexisting_plugin_ids",
    )
    if plugin_id.casefold() in normalized_preexisting:
        raise PluginOperationContractError(
            "PLUGIN_ID_NOT_NEW",
            "Plug-in readback reused a pre-existing plug-in ID; create-only "
            "verification failed.",
            details={"plugin_id": plugin_id},
        )

    placement = _verify_plugin_placement(
        descriptor=descriptor,
        version=version,
        plugin_id=plugin_id,
        expected_parent_id=expected_parent_id,
        expected_owner_id=expected_owner_id,
        placement_evidence=placement_evidence,
    )
    # Effects can be embedded values with an immediate owner, not hierarchy
    # children. Placement above independently proves slot -> target (or the
    # 2022 fixed target reference); the effect must point back to that slot.
    expected_plugin_owner = (
        expected_parent_id if effect_owner_only else expected_owner_id
    )
    if effect_owner_only:
        placement["ownership_readback"] = "immediate_owner_without_hierarchy_parent"
    expected = {
        "name": descriptor.name,
        "type": descriptor.object_type,
        "classId": descriptor.class_id,
        "parent": expected_parent_id,
        "owner": expected_plugin_owner,
    }
    native_type = row.get("type")
    normalized_type = (
        descriptor.object_type
        if native_type
        in {descriptor.object_type, f"{descriptor.object_type}Plugin"}
        else native_type
    )
    actual = {
        "name": row.get("name"),
        "type": normalized_type,
        "classId": row.get("classId"),
        "parent": parent_id,
        "owner": owner_id,
    }
    matches = (
        actual["name"] == expected["name"]
        and actual["type"] == expected["type"]
        and type(actual["classId"]) is int
        and actual["classId"] == expected["classId"]
        and _same_guid(parent_id, expected_parent_id)
        and _same_guid(owner_id, expected_plugin_owner)
    )
    if not matches:
        raise PluginOperationContractError(
            "PLUGIN_READBACK_MISMATCH",
            "Created plug-in name/type/classId/parent/owner did not match the "
            "immutable plan.",
            details={"expected": expected, "actual": actual},
        )

    requested_state = _verify_requested_plugin_state(
        descriptor=descriptor,
        row=row,
        validated_properties=normalized_properties,
    )
    return PluginVerificationEvidence(
        plugin_id=plugin_id,
        name=descriptor.name,
        type=descriptor.object_type,
        class_id=descriptor.class_id,
        parent_id=parent_id,
        owner_id=owner_id,
        readback_view=normalized_view,
        requested_state=requested_state,
        placement=placement,
    )


def _validate_verification_properties(
    descriptor: PluginCreationDescriptor,
    value: Sequence[ValidatedPluginProperty],
) -> tuple[ValidatedPluginProperty, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            "validated_properties must be an ordered array of "
            "ValidatedPluginProperty values.",
        )
    rows = tuple(value)
    if not all(isinstance(item, ValidatedPluginProperty) for item in rows):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            "validated_properties contains a value outside the closed "
            "ValidatedPluginProperty contract.",
        )
    requested = tuple(
        (item.name, item.value)
        for item in descriptor.properties
    )
    actual = tuple((item.name, item.value) for item in rows)
    if requested != actual:
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            "validated_properties does not match the immutable descriptor.",
            details={"requested": requested, "actual": actual},
        )
    for item in rows:
        _require_metadata_value_type(
            name=item.name,
            metadata_type=item.metadata_type,
            value=item.value,
        )
    return rows


def _validate_plugin_readback_view(
    descriptor: PluginCreationDescriptor,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            "readback_view must be an object.",
        )
    _require_exact_mapping_fields(
        value,
        PLUGIN_READBACK_VIEW_FIELDS,
        field="readback_view",
    )
    raw_fields = value.get("fields")
    if isinstance(raw_fields, (str, bytes)) or not isinstance(
        raw_fields,
        Sequence,
    ):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            "readback_view.fields must be an ordered array.",
        )
    fields = tuple(raw_fields)
    expected_fields = plugin_verification_fields(descriptor)
    if (
        not all(isinstance(item, str) for item in fields)
        or fields != expected_fields
    ):
        raise PluginOperationContractError(
            "PLUGIN_READBACK_VIEW_MISMATCH",
            "Plug-in readback fields do not match the immutable descriptor.",
            details={
                "expected": list(expected_fields),
                "actual": list(fields),
            },
        )
    platform = value.get("platform")
    language = value.get("language")
    if platform != descriptor.platform or language != descriptor.language:
        raise PluginOperationContractError(
            "PLUGIN_READBACK_VIEW_MISMATCH",
            "Plug-in readback language/platform view does not match the "
            "immutable descriptor.",
            details={
                "expected": {
                    "language": descriptor.language,
                    "platform": descriptor.platform,
                },
                "actual": {
                    "language": language,
                    "platform": platform,
                },
            },
        )
    return {
        "fields": list(fields),
        "language": language,
        "platform": platform,
    }


def _verify_requested_plugin_state(
    *,
    descriptor: PluginCreationDescriptor,
    row: Mapping[str, Any],
    validated_properties: Sequence[ValidatedPluginProperty],
) -> dict[str, Any]:
    requested_state: dict[str, Any] = {
        "language": {
            "requested": descriptor.language is not None,
            "value": descriptor.language,
        },
        "notes": {
            "requested": descriptor.notes is not None,
            "value": descriptor.notes,
        },
        "platform": descriptor.platform,
        "properties": [],
    }
    if descriptor.notes is not None:
        actual_notes = row.get("notes")
        if type(actual_notes) is not str or actual_notes != descriptor.notes:
            raise PluginOperationContractError(
                "PLUGIN_REQUESTED_STATE_MISMATCH",
                "Created plug-in notes do not match the immutable request.",
                details={
                    "field": "notes",
                    "expected": descriptor.notes,
                    "actual": actual_notes,
                },
            )
    if descriptor.language is not None:
        actual_language = _language_reference_name(
            row.get(PLUGIN_LANGUAGE_READBACK_FIELD),
            field=f"plugin.{PLUGIN_LANGUAGE_READBACK_FIELD}",
        )
        if actual_language != descriptor.language:
            raise PluginOperationContractError(
                "PLUGIN_REQUESTED_STATE_MISMATCH",
                "Created Source language does not match the immutable request.",
                details={
                    "field": PLUGIN_LANGUAGE_READBACK_FIELD,
                    "expected": descriptor.language,
                    "actual": actual_language,
                },
            )

    property_evidence: list[dict[str, Any]] = []
    for prop in validated_properties:
        field = f"@{prop.name}"
        actual = row.get(field)
        if not _verified_property_value_equal(
            actual,
            prop.value,
            metadata_type=prop.metadata_type,
        ):
            raise PluginOperationContractError(
                "PLUGIN_REQUESTED_STATE_MISMATCH",
                "Created plug-in property does not match the immutable "
                "typed request.",
                details={
                    "field": field,
                    "expected": prop.value,
                    "actual": actual,
                    "metadata_type": prop.metadata_type,
                },
            )
        property_evidence.append(
            {
                "field": field,
                "metadata_type": prop.metadata_type,
                "value": actual,
            }
        )
    requested_state["properties"] = property_evidence
    return requested_state


def _verify_plugin_placement(
    *,
    descriptor: PluginCreationDescriptor,
    version: str,
    plugin_id: str,
    expected_parent_id: str,
    expected_owner_id: str,
    placement_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(placement_evidence, Mapping):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            "placement_evidence must be an object.",
        )
    if descriptor.kind == "source":
        _require_exact_mapping_fields(
            placement_evidence,
            _SOURCE_PLACEMENT_EVIDENCE_FIELDS,
            field="placement_evidence",
        )
        if placement_evidence.get("kind") != "source_child":
            raise PluginOperationContractError(
                "PLUGIN_PLACEMENT_MISMATCH",
                "Source verification requires source_child placement evidence.",
            )
        if not _same_guid(expected_parent_id, expected_owner_id):
            raise PluginOperationContractError(
                "PLUGIN_PLACEMENT_MISMATCH",
                "Source plug-in parent and owner must both be the resolved "
                "Sound or Voice target.",
            )
        return {"kind": "source_child"}

    if version == "2022.1":
        return _verify_2022_effect_placement(
            plugin_id=plugin_id,
            expected_parent_id=expected_parent_id,
            expected_owner_id=expected_owner_id,
            placement_evidence=placement_evidence,
        )
    return _verify_appended_effect_slot_placement(
        plugin_id=plugin_id,
        expected_parent_id=expected_parent_id,
        expected_owner_id=expected_owner_id,
        placement_evidence=placement_evidence,
    )


def _verify_2022_effect_placement(
    *,
    plugin_id: str,
    expected_parent_id: str,
    expected_owner_id: str,
    placement_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    _require_exact_mapping_fields(
        placement_evidence,
        _FIXED_EFFECT_PLACEMENT_EVIDENCE_FIELDS,
        field="placement_evidence",
    )
    if placement_evidence.get("kind") != "fixed_effect_reference":
        raise PluginOperationContractError(
            "PLUGIN_PLACEMENT_MISMATCH",
            "Wwise 2022.1 Effect verification requires fixed-reference "
            "placement evidence.",
        )
    if not _same_guid(expected_parent_id, expected_owner_id):
        raise PluginOperationContractError(
            "PLUGIN_PLACEMENT_MISMATCH",
            "A Wwise 2022.1 Effect parent and owner must both be the resolved "
            "target.",
        )
    selected = placement_evidence.get("selected_effect_field")
    if selected not in WWISE_2022_EFFECT_FIELDS:
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            "selected_effect_field is not a reviewed Wwise 2022.1 Effect "
            "reference.",
            details={"field": selected},
        )
    before = _normalize_2022_effect_references(
        placement_evidence.get("pre_effect_references"),
        field="placement_evidence.pre_effect_references",
    )
    if before[selected] is not None:
        raise PluginOperationContractError(
            "PLUGIN_PLACEMENT_MISMATCH",
            "The selected Wwise 2022.1 Effect reference was not empty in the "
            "sealed pre-state.",
            details={"field": selected, "value": before[selected]},
        )
    post = _normalize_2022_effect_target_row(
        placement_evidence.get("target_post_readback"),
        expected_target_id=expected_owner_id,
    )
    expected_post = dict(before)
    expected_post[selected] = plugin_id
    if any(
        not _optional_guid_equal(post[field], expected_post[field])
        for field in WWISE_2022_EFFECT_FIELDS
    ):
        raise PluginOperationContractError(
            "EFFECT_REFERENCE_READBACK_MISMATCH",
            "The Wwise 2022.1 target Effect references do not equal the "
            "sealed pre-state plus the new plug-in binding.",
            details={
                "selected_effect_field": selected,
                "expected": expected_post,
                "actual": post,
            },
        )
    return {
        "kind": "fixed_effect_reference",
        "selected_effect_field": selected,
        "target_id": expected_owner_id,
        "target_post_references": post,
    }


def _verify_appended_effect_slot_placement(
    *,
    plugin_id: str,
    expected_parent_id: str,
    expected_owner_id: str,
    placement_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    _require_exact_mapping_fields(
        placement_evidence,
        _APPENDED_EFFECT_PLACEMENT_EVIDENCE_FIELDS,
        field="placement_evidence",
    )
    if placement_evidence.get("kind") != "effect_slot_append":
        raise PluginOperationContractError(
            "PLUGIN_PLACEMENT_MISMATCH",
            "Wwise 2023.1+ Effect verification requires appended EffectSlot "
            "placement evidence.",
        )
    preexisting_slots = _normalize_guid_sequence(
        placement_evidence.get("preexisting_effect_slot_ids"),
        field="placement_evidence.preexisting_effect_slot_ids",
    )
    slot = placement_evidence.get("created_effect_slot")
    if not isinstance(slot, Mapping):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            "created_effect_slot must be an object.",
        )
    _require_exact_mapping_fields(
        slot,
        frozenset(PLUGIN_EFFECT_SLOT_READBACK_FIELDS) - ({"parent"} if "parent" not in slot else set()),
        field="placement_evidence.created_effect_slot",
    )
    slot_id = _require_guid(
        slot.get("id"),
        field="placement_evidence.created_effect_slot.id",
    )
    if slot_id.casefold() in preexisting_slots:
        raise PluginOperationContractError(
            "EFFECT_SLOT_ID_NOT_NEW",
            "The created EffectSlot reused a pre-existing EffectSlot ID.",
            details={"effect_slot_id": slot_id},
        )
    slot_parent = _closed_object_reference_id(
        slot.get("parent", slot.get("owner")),
        field="placement_evidence.created_effect_slot.parent",
    )
    slot_owner = _closed_object_reference_id(
        slot.get("owner"),
        field="placement_evidence.created_effect_slot.owner",
    )
    slot_effect = _closed_object_reference_id(
        slot.get("@Effect"),
        field="placement_evidence.created_effect_slot.@Effect",
    )
    matches = (
        slot.get("name") == ""
        and slot.get("type") == "EffectSlot"
        and _same_guid(slot_id, expected_parent_id)
        and _same_guid(slot_parent, expected_owner_id)
        and _same_guid(slot_owner, expected_owner_id)
        and _same_guid(slot_effect, plugin_id)
    )
    if not matches:
        raise PluginOperationContractError(
            "EFFECT_SLOT_READBACK_MISMATCH",
            "The created EffectSlot identity, ownership, or @Effect binding "
            "does not match the immutable plan.",
            details={
                "expected": {
                    "id": expected_parent_id,
                    "name": "",
                    "type": "EffectSlot",
                    "parent": expected_owner_id,
                    "owner": expected_owner_id,
                    "@Effect": plugin_id,
                },
                "actual": {
                    "id": slot_id,
                    "name": slot.get("name"),
                    "type": slot.get("type"),
                    "parent": slot_parent,
                    "owner": slot_owner,
                    "@Effect": slot_effect,
                },
            },
        )
    return {
        "kind": "effect_slot_append",
        "effect_slot_id": slot_id,
        "preexisting_effect_slot_ids": sorted(preexisting_slots),
        "target_id": expected_owner_id,
    }


def _normalize_2022_effect_references(
    value: Any,
    *,
    field: str,
) -> dict[str, str | None]:
    if not isinstance(value, Mapping):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            f"{field} must be an object.",
        )
    _require_exact_mapping_fields(
        value,
        frozenset(WWISE_2022_EFFECT_FIELDS),
        field=field,
    )
    normalized = {
        name: _closed_object_reference_id(
            value.get(name),
            field=f"{field}.{name}",
            allow_none=True,
        )
        for name in WWISE_2022_EFFECT_FIELDS
    }
    occupied = [
        item for item in normalized.values() if item is not None
    ]
    if len({item.casefold() for item in occupied}) != len(occupied):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            f"{field} contains duplicate Effect plug-in IDs.",
        )
    return normalized


def _normalize_2022_effect_target_row(
    value: Any,
    *,
    expected_target_id: str,
) -> dict[str, str | None]:
    if not isinstance(value, Mapping):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            "target_post_readback must be an object.",
        )
    _require_exact_mapping_fields(
        value,
        frozenset(PLUGIN_2022_EFFECT_TARGET_READBACK_FIELDS),
        field="placement_evidence.target_post_readback",
    )
    target_id = _require_guid(
        value.get("id"),
        field="placement_evidence.target_post_readback.id",
    )
    if not _same_guid(target_id, expected_target_id):
        raise PluginOperationContractError(
            "EFFECT_REFERENCE_READBACK_MISMATCH",
            "The Wwise 2022.1 Effect post-read resolved a different target.",
            details={
                "expected": expected_target_id,
                "actual": target_id,
            },
        )
    return {
        name: _closed_object_reference_id(
            value.get(name),
            field=f"placement_evidence.target_post_readback.{name}",
            allow_none=True,
        )
        for name in WWISE_2022_EFFECT_FIELDS
    }


def _normalize_guid_sequence(
    value: Any,
    *,
    field: str,
) -> set[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            f"{field} must be an array of exact Wwise GUIDs.",
        )
    normalized = [
        _require_guid(item, field=f"{field}[]").casefold()
        for item in value
    ]
    if len(set(normalized)) != len(normalized):
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            f"{field} contains duplicate Wwise GUIDs.",
        )
    return set(normalized)


def _closed_object_reference_id(
    value: Any,
    *,
    field: str,
    allow_none: bool = False,
) -> str | None:
    if value is None and allow_none:
        return None
    if isinstance(value, Mapping):
        unknown = set(value) - _OBJECT_REFERENCE_FIELDS
        if unknown or "id" not in value:
            raise PluginOperationContractError(
                "INVALID_PLUGIN_READBACK",
                f"{field} is outside the closed object-reference shape.",
                details={"unknown": sorted(unknown)},
            )
        for optional_field in ("name", "path", "type"):
            if (
                optional_field in value
                and not isinstance(value.get(optional_field), str)
            ):
                raise PluginOperationContractError(
                    "INVALID_PLUGIN_READBACK",
                    f"{field}.{optional_field} must be a string.",
                )
        value = value.get("id")
    if allow_none and value == "{00000000-0000-0000-0000-000000000000}":
        return None
    return _require_guid(value, field=field)


def _language_reference_name(value: Any, *, field: str) -> str:
    if isinstance(value, str):
        return _bounded_text(
            value,
            field=field,
            maximum=255,
            allow_empty=False,
        )
    if not isinstance(value, Mapping):
        raise PluginOperationContractError(
            "INVALID_PLUGIN_READBACK",
            f"{field} must be a language name or closed object reference.",
        )
    unknown = set(value) - _OBJECT_REFERENCE_FIELDS
    if unknown or "name" not in value:
        raise PluginOperationContractError(
            "INVALID_PLUGIN_READBACK",
            f"{field} is outside the closed language-reference shape.",
            details={"unknown": sorted(unknown)},
        )
    if "id" in value:
        _require_guid(value.get("id"), field=f"{field}.id")
    for optional_field in ("path", "type"):
        if optional_field in value and not isinstance(
            value.get(optional_field),
            str,
        ):
            raise PluginOperationContractError(
                "INVALID_PLUGIN_READBACK",
                f"{field}.{optional_field} must be a string.",
            )
    return _bounded_text(
        value.get("name"),
        field=f"{field}.name",
        maximum=255,
        allow_empty=False,
    )


def _verified_property_value_equal(
    actual: Any,
    expected: JsonScalar,
    *,
    metadata_type: str,
) -> bool:
    normalized = metadata_type.casefold()
    if normalized in _REAL_PROPERTY_TYPES:
        if (
            isinstance(actual, bool)
            or not isinstance(actual, (int, float))
            or not math.isfinite(float(actual))
        ):
            return False
        if normalized in _REAL32_PROPERTY_TYPES:
            return math.isclose(
                float(actual),
                float(expected),
                rel_tol=PLUGIN_REAL32_REL_TOLERANCE,
                abs_tol=PLUGIN_REAL32_ABS_TOLERANCE,
            )
        return math.isclose(
            float(actual),
            float(expected),
            rel_tol=PLUGIN_REAL64_REL_TOLERANCE,
            abs_tol=PLUGIN_REAL64_ABS_TOLERANCE,
        )
    if normalized in _INTEGER_PROPERTY_TYPES:
        return type(actual) is int and actual == expected
    if normalized in _BOOLEAN_PROPERTY_TYPES:
        return type(actual) is bool and actual is expected
    if normalized in _STRING_PROPERTY_TYPES:
        return type(actual) is str and actual == expected
    return False


def _optional_guid_equal(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return left is right
    return _same_guid(left, right)


def _require_exact_mapping_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    *,
    field: str,
) -> None:
    missing = set(expected) - set(value)
    unknown = set(value) - set(expected)
    if missing or unknown:
        raise PluginOperationContractError(
            "INVALID_VERIFICATION_INPUT",
            f"{field} contains unknown or missing fields.",
            details={"missing": sorted(missing), "unknown": sorted(unknown)},
        )


def _materialize_plugin_object(
    descriptor: PluginCreationDescriptor,
    validated: tuple[ValidatedPluginProperty, ...],
) -> dict[str, Any]:
    requested = tuple(
        (item.name, item.value)
        for item in descriptor.properties
    )
    proven = tuple((item.name, item.value) for item in validated)
    if requested != proven:
        raise PluginOperationContractError(
            "PROPERTY_METADATA_REQUIRED",
            "Plug-in properties cannot be materialized before exact live "
            "getPropertyInfo name/type validation.",
        )
    result: dict[str, Any] = {
        "type": descriptor.object_type,
        "name": descriptor.name,
        "classId": descriptor.class_id,
    }
    if descriptor.notes is not None:
        result["notes"] = descriptor.notes
    if descriptor.platform is not None:
        result["platform"] = descriptor.platform
    if descriptor.language is not None:
        result["language"] = descriptor.language
    for prop in validated:
        result[f"@{prop.name}"] = prop.value
    return result


def _normalize_properties(payload: Any) -> tuple[PluginProperty, ...]:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise PluginOperationContractError(
            "INVALID_ARGUMENT",
            "properties must be an array.",
        )
    if len(payload) > MAX_PLUGIN_PROPERTIES:
        raise PluginOperationContractError(
            "LIMIT_EXCEEDED",
            f"properties exceeds the {MAX_PLUGIN_PROPERTIES} item ceiling.",
        )
    result: list[PluginProperty] = []
    seen: set[str] = set()
    for index, raw in enumerate(payload):
        if not isinstance(raw, Mapping):
            raise PluginOperationContractError(
                "INVALID_ARGUMENT",
                f"properties[{index}] must be an object.",
            )
        unknown = set(raw) - _PLUGIN_PROPERTY_FIELDS
        missing = _PLUGIN_PROPERTY_FIELDS - set(raw)
        if unknown or missing:
            raise PluginOperationContractError(
                "INVALID_ARGUMENT",
                f"properties[{index}] contains unknown or missing fields.",
                details={"missing": sorted(missing), "unknown": sorted(unknown)},
            )
        name = _bounded_text(
            raw.get("name"),
            field=f"properties[{index}].name",
            maximum=MAX_PLUGIN_FIELD_NAME_LENGTH,
            allow_empty=False,
        )
        if not _FIELD_NAME.fullmatch(name):
            raise PluginOperationContractError(
                "INVALID_ARGUMENT",
                f"properties[{index}].name is not a valid Wwise field name.",
            )
        folded = name.casefold()
        if folded in seen:
            raise PluginOperationContractError(
                "INVALID_ARGUMENT",
                f"properties contains duplicate field {name!r}.",
            )
        value = raw.get("value")
        if value is None or isinstance(value, (list, Mapping)):
            raise PluginOperationContractError(
                "INVALID_ARGUMENT",
                f"properties[{index}].value must be a JSON scalar.",
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise PluginOperationContractError(
                "INVALID_ARGUMENT",
                f"properties[{index}].value must be finite.",
            )
        if not isinstance(value, (str, int, float, bool)):
            raise PluginOperationContractError(
                "INVALID_ARGUMENT",
                f"properties[{index}].value must be a JSON scalar.",
            )
        result.append(PluginProperty(name=name, value=value))
        seen.add(folded)
    return tuple(result)


def _require_metadata_value_type(
    *,
    name: str,
    metadata_type: str,
    value: JsonScalar,
) -> None:
    normalized = metadata_type.casefold()
    if normalized in _REAL_PROPERTY_TYPES:
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
        )
    elif normalized in _INTEGER_PROPERTY_TYPES:
        valid = not isinstance(value, bool) and isinstance(value, int)
        if valid and normalized.startswith("uint"):
            valid = value >= 0
    elif normalized in _BOOLEAN_PROPERTY_TYPES:
        valid = isinstance(value, bool)
    elif normalized in _STRING_PROPERTY_TYPES:
        valid = isinstance(value, str)
    else:
        raise PluginOperationContractError(
            "UNSUPPORTED_PROPERTY_TYPE",
            "Plug-in property metadata type is outside the closed scalar "
            "property contract.",
            details={"property": name, "metadata_type": metadata_type},
        )
    if not valid:
        raise PluginOperationContractError(
            "INVALID_PROPERTY_VALUE",
            "Plug-in property value does not match live getPropertyInfo type.",
            details={
                "property": name,
                "metadata_type": metadata_type,
                "value_type": type(value).__name__,
            },
        )


def _require_guid(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _GUID.fullmatch(value):
        raise PluginOperationContractError(
            "INVALID_OBJECT_ID",
            f"{field} must be an exact Wwise GUID.",
            details={"field": field},
        )
    return value


def _same_guid(left: str, right: str) -> bool:
    return left.casefold() == right.casefold()


def _bounded_text(
    value: Any,
    *,
    field: str,
    maximum: int,
    allow_empty: bool,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise PluginOperationContractError(
            "INVALID_ARGUMENT",
            f"{field} must be {qualifier}.",
        )
    if len(value) > maximum:
        raise PluginOperationContractError(
            "LIMIT_EXCEEDED",
            f"{field} exceeds the {maximum} character ceiling.",
        )
    return value


def _json_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_copy(item) for item in value]
    if isinstance(value, list):
        return [_json_copy(item) for item in value]
    return value


__all__ = [
    "GET_PROPERTY_INFO_URI",
    "MAX_PLUGIN_PROPERTIES",
    "OBJECT_SET_URI",
    "PLUGIN_2022_EFFECT_TARGET_READBACK_FIELDS",
    "PLUGIN_EFFECT_SLOT_READBACK_FIELDS",
    "PLUGIN_KINDS",
    "PLUGIN_LANGUAGE_READBACK_FIELD",
    "PLUGIN_REAL32_ABS_TOLERANCE",
    "PLUGIN_REAL32_REL_TOLERANCE",
    "PLUGIN_REAL64_ABS_TOLERANCE",
    "PLUGIN_REAL64_REL_TOLERANCE",
    "PLUGIN_VERIFICATION_FIELDS",
    "PluginCreationDescriptor",
    "PluginCreationPlan",
    "PluginOperationContractError",
    "PluginProperty",
    "PluginVerificationEvidence",
    "SOURCE_TARGET_TYPES",
    "SUPPORTED_PLUGIN_VERSIONS",
    "UINT32_MAX",
    "ValidatedPluginProperty",
    "WWISE_2022_EFFECT_FIELDS",
    "build_plugin_creation_plan",
    "normalize_plugin_creation",
    "plugin_property_metadata_requests",
    "plugin_verification_fields",
    "select_free_2022_effect_field",
    "validate_plugin_property_metadata",
    "verify_created_plugin_row",
]
