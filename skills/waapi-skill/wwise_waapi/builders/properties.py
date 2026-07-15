"""Mutating property/reference semantic previews that never dispatch WAAPI calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION  # pyright: ignore[reportMissingImports]
from wwise_waapi.waql import quote_waql_literal  # pyright: ignore[reportMissingImports]

from .common import (  # pyright: ignore[reportMissingImports]
    BuilderContext,
    BuilderFamily,
    ManifestSchemaLoader,
    SemanticEnvelope,
    SemanticErrorCode,
    SemanticPreview,
    SemanticReadbackPlan,
    SemanticValidationError,
    SourceNoteChecker,
)
from .identity import ObjectIdentity, ResolvedObject, resolve_object_identity  # pyright: ignore[reportMissingImports]
from .metadata import PropertyInfoMetadataRecord  # pyright: ignore[reportMissingImports]
from .schema import SemanticSchemaValidator, SchemaValidationResult  # pyright: ignore[reportMissingImports]
from .source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]


OBJECT_GET_URI = "ak.wwise.core.object.get"
SET_NAME_URI = "ak.wwise.core.object.setName"
SET_NOTES_URI = "ak.wwise.core.object.setNotes"
SET_PROPERTY_URI = "ak.wwise.core.object.setProperty"
SET_REFERENCE_URI = "ak.wwise.core.object.setReference"
SET_RANDOMIZER_URI = "ak.wwise.core.object.setRandomizer"
SET_ATTENUATION_CURVE_URI = "ak.wwise.core.object.setAttenuationCurve"
GET_ATTENUATION_CURVE_URI = "ak.wwise.core.object.getAttenuationCurve"


class PropertyReferenceOperation(str, Enum):
    """Supported mutating property/reference operations."""

    SET_NAME = "setName"
    SET_NOTES = "setNotes"
    SET_PROPERTY = "setProperty"
    SET_REFERENCE = "setReference"
    SET_RANDOMIZER = "setRandomizer"
    SET_ATTENUATION_CURVE = "setAttenuationCurve"


SUPPORTED_PROPERTY_REFERENCE_URIS: Mapping[PropertyReferenceOperation, str] = {
    PropertyReferenceOperation.SET_NAME: SET_NAME_URI,
    PropertyReferenceOperation.SET_NOTES: SET_NOTES_URI,
    PropertyReferenceOperation.SET_PROPERTY: SET_PROPERTY_URI,
    PropertyReferenceOperation.SET_REFERENCE: SET_REFERENCE_URI,
    PropertyReferenceOperation.SET_RANDOMIZER: SET_RANDOMIZER_URI,
    PropertyReferenceOperation.SET_ATTENUATION_CURVE: SET_ATTENUATION_CURVE_URI,
}


@dataclass(slots=True, frozen=True)
class TopicExpectationPlan:
    """Evidence-only plan for a future topic assertion; it never subscribes."""

    topic: str
    expected_identity: Mapping[str, Any]
    required_payload_fields: tuple[str, ...]
    description: str
    old_new_required: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "topic-expectation",
            "topic": self.topic,
            "expected_identity": dict(self.expected_identity),
            "required_payload_fields": list(self.required_payload_fields),
            "old_new_required": self.old_new_required,
            "description": self.description,
            "live_subscription": False,
        }


@dataclass(slots=True, frozen=True)
class CurvePoint:
    """Explicit attenuation-curve point accepted by the semantic builder."""

    x: int | float
    y: int | float
    shape: str

    def as_dict(self) -> dict[str, Any]:
        _require_number("x", self.x)
        _require_number("y", self.y)
        _require_non_empty_string("shape", self.shape)
        return {"x": self.x, "y": self.y, "shape": self.shape}


@dataclass(slots=True, frozen=True)
class PropertyReferenceBuilder:
    """Build setter previews after explicit metadata and identity validation."""

    version: str = DEFAULT_WWISE_VERSION
    source_note_checker: SourceNoteChecker | None = None
    manifest_loader: ManifestSchemaLoader = field(default_factory=ManifestSchemaLoader)

    def set_name(self, *, object: ObjectIdentity | ResolvedObject, value: str) -> SemanticPreview:
        source = _resolved_exact_object("object", object)
        _require_non_empty_string("value", value)
        args = {"object": source.object, "value": value}
        return self._build_preview(
            PropertyReferenceOperation.SET_NAME,
            args,
            readback_plan=_object_value_readback(source, ("id", "name", "path", "type"), "read back renamed object by exact identity"),
            evidence_items=(name_changed_topic_expectation(source, value).as_dict(),),
            operation_metadata={"value_kind": "name"},
        )

    def set_notes(self, *, object: ObjectIdentity | ResolvedObject, value: str) -> SemanticPreview:
        source = _resolved_exact_object("object", object)
        if not isinstance(value, str):
            raise _type_error("value", "string", value)
        args = {"object": source.object, "value": value}
        return self._build_preview(
            PropertyReferenceOperation.SET_NOTES,
            args,
            readback_plan=_object_value_readback(source, ("id", "notes", "path", "type"), "read back notes by exact identity"),
            evidence_items=(notes_changed_topic_expectation(source, value).as_dict(),),
            operation_metadata={"value_kind": "notes"},
        )

    def set_property(
        self,
        *,
        object: ObjectIdentity | ResolvedObject,
        property: str,
        value: Any,
        property_info: PropertyInfoMetadataRecord,
        property_enabled: bool | None = None,
        platform: str | int | None = None,
    ) -> SemanticPreview:
        source = _resolved_exact_object("object", object)
        _require_metadata_match(property, property_info)
        _require_property_value(property_info, value)
        args: dict[str, Any] = {"object": source.object, "property": property, "value": value}
        if platform is not None:
            _require_object_arg("platform", platform)
            args["platform"] = platform
        if property_enabled is False:
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
                f"Property {property!r} is not enabled for the supplied object/platform metadata.",
                details={"property": property, "property_enabled": False},
            )
        return self._build_preview(
            PropertyReferenceOperation.SET_PROPERTY,
            args,
            readback_plan=_object_value_readback(source, ("id", "path", property), "read back changed property by exact identity"),
            evidence_items=(property_changed_topic_expectation(source, property, value).as_dict(), _property_metadata_evidence(property_info, property_enabled, platform)),
            operation_metadata={"property_info": property_info.as_dict(), "property_enabled": property_enabled, "platform": platform},
        )

    def set_reference(
        self,
        *,
        object: ObjectIdentity | ResolvedObject,
        reference: str,
        target: ObjectIdentity | ResolvedObject,
        reference_info: PropertyInfoMetadataRecord,
        platform: str | int | None = None,
    ) -> SemanticPreview:
        source = _resolved_exact_object("object", object)
        target_object = _resolved_exact_object("target", target)
        _require_metadata_match(reference, reference_info)
        _require_reference_metadata(reference_info)
        args: dict[str, Any] = {"object": source.object, "reference": reference, "value": target_object.object}
        if platform is not None:
            _require_object_arg("platform", platform)
            args["platform"] = platform
        return self._build_preview(
            PropertyReferenceOperation.SET_REFERENCE,
            args,
            readback_plan=_object_value_readback(source, ("id", "path", reference), "read back changed reference by exact identity when WAAPI exposes it"),
            evidence_items=(reference_changed_topic_expectation(source, reference, target_object).as_dict(), _property_metadata_evidence(reference_info, None, platform)),
            operation_metadata={"reference_info": reference_info.as_dict(), "target_identity": target_object.as_dict(), "platform": platform},
        )

    def set_randomizer(
        self,
        *,
        object: ObjectIdentity | ResolvedObject,
        property: str,
        property_info: PropertyInfoMetadataRecord,
        enabled: bool | None = None,
        min: int | float | None = None,
        max: int | float | None = None,
        platform: str | int | None = None,
    ) -> SemanticPreview:
        source = _resolved_exact_object("object", object)
        _require_metadata_match(property, property_info)
        if property_info.supports.get("randomizer") is not True:
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
                f"Property {property!r} metadata does not support randomizer edits.",
                details={"property": property, "supports": dict(property_info.supports)},
            )
        args: dict[str, Any] = {"object": source.object, "property": property}
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise _type_error("enabled", "boolean", enabled)
            args["enabled"] = enabled
        if min is not None:
            _require_number("min", min)
            args["min"] = min
        if max is not None:
            _require_number("max", max)
            args["max"] = max
        if not any(key in args for key in ("enabled", "min", "max")):
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
                "setRandomizer requires at least one of enabled, min, or max.",
                details={"required_alternatives": [["enabled"], ["min"], ["max"]]},
            )
        if platform is not None:
            _require_object_arg("platform", platform)
            args["platform"] = platform
        return self._build_preview(
            PropertyReferenceOperation.SET_RANDOMIZER,
            args,
            readback_plan=_object_value_readback(source, ("id", "path", property), "read back property after randomizer edit; randomizer-specific readback remains external evidence"),
            evidence_items=(_property_metadata_evidence(property_info, None, platform),),
            operation_metadata={"property_info": property_info.as_dict(), "platform": platform},
        )

    def set_attenuation_curve(
        self,
        *,
        object: ObjectIdentity | ResolvedObject,
        curve_type: str,
        use: str,
        points: Sequence[CurvePoint | Mapping[str, Any]],
        platform: str | int | None = None,
    ) -> SemanticPreview:
        source = _resolved_exact_object("object", object)
        _require_non_empty_string("curve_type", curve_type)
        _require_non_empty_string("use", use)
        normalized_points = [_curve_point(point) for point in points]
        if not normalized_points:
            raise SemanticValidationError(
                SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
                "setAttenuationCurve requires explicit curve points with x, y, and shape.",
                details={"required_fields": ["points[].x", "points[].y", "points[].shape"]},
            )
        args: dict[str, Any] = {"object": source.object, "curveType": curve_type, "use": use, "points": normalized_points}
        if platform is not None:
            _require_object_arg("platform", platform)
            args["platform"] = platform
        return self._build_preview(
            PropertyReferenceOperation.SET_ATTENUATION_CURVE,
            args,
            readback_plan=(
                SemanticReadbackPlan(
                    GET_ATTENUATION_CURVE_URI,
                    args={"object": source.object, "curveType": curve_type, **({"platform": platform} if platform is not None else {})},
                    options={},
                    description="read back attenuation curve after mutation with documented empty-response policy handled by parser",
                ),
            ),
            evidence_items=(attenuation_curve_changed_topic_expectation(source, curve_type).as_dict(),),
            operation_metadata={"curve_type": curve_type, "use": use, "platform": platform},
        )

    def _build_preview(
        self,
        operation: PropertyReferenceOperation,
        args: Mapping[str, Any],
        *,
        readback_plan: tuple[SemanticReadbackPlan, ...],
        evidence_items: tuple[Mapping[str, Any], ...],
        operation_metadata: Mapping[str, Any],
    ) -> SemanticPreview:
        uri = SUPPORTED_PROPERTY_REFERENCE_URIS[operation]
        context = BuilderContext(
            BuilderFamily.PROPERTY_REFERENCE,
            version=self.version,
            source_note_checker=self.source_note_checker or SemanticSourceNoteChecker(),
            manifest_loader=self.manifest_loader,
        )
        context.require_supported_family()
        source_note = context.require_source_note()
        validation = SemanticSchemaValidator(manifest_loader=context.manifest_loader, version=context.version).validate(uri, args, {})
        envelope = SemanticEnvelope(
            uri,
            args=dict(args),
            options={},
            metadata=_preview_metadata(operation, validation, source_note.as_dict(), operation_metadata),
        )
        return SemanticPreview(
            envelope=envelope,
            source_note_family=BuilderFamily.PROPERTY_REFERENCE.value,
            version=self.version,
            readback_plan=readback_plan,
            evidence_plan=(
                {"kind": "source-note", "family": BuilderFamily.PROPERTY_REFERENCE.value, "status": source_note.as_dict()},
                {"kind": "schema", "validation": validation.as_dict()},
                *tuple(dict(item) for item in evidence_items),
            ),
            requires_destructive_gate=True,
            raw_dispatch_allowed=False,
        )


def build_set_name_preview(**kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).set_name(**kwargs)


def build_set_notes_preview(**kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).set_notes(**kwargs)


def build_set_property_preview(**kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).set_property(**kwargs)


def build_set_reference_preview(**kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).set_reference(**kwargs)


def build_set_randomizer_preview(**kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).set_randomizer(**kwargs)


def build_set_attenuation_curve_preview(**kwargs: Any) -> SemanticPreview:
    return _builder_from_kwargs(kwargs).set_attenuation_curve(**kwargs)


def _builder_from_kwargs(kwargs: dict[str, Any]) -> PropertyReferenceBuilder:
    return PropertyReferenceBuilder(
        version=kwargs.pop("version", DEFAULT_WWISE_VERSION),
        source_note_checker=kwargs.pop("source_note_checker", None),
    )


def name_changed_topic_expectation(object: ResolvedObject, value: str) -> TopicExpectationPlan:
    return TopicExpectationPlan("ak.wwise.core.object.nameChanged", object.as_dict(), ("id", "path", "name"), f"expect nameChanged payload for value {value!r}")


def notes_changed_topic_expectation(object: ResolvedObject, value: str) -> TopicExpectationPlan:
    return TopicExpectationPlan("ak.wwise.core.object.notesChanged", object.as_dict(), ("id", "path", "notes"), f"expect notesChanged payload for value length {len(value)}")


def property_changed_topic_expectation(object: ResolvedObject, property: str, value: Any) -> TopicExpectationPlan:
    return TopicExpectationPlan("ak.wwise.core.object.propertyChanged", object.as_dict(), ("id", "path", "property", "old", "new"), f"expect propertyChanged payload for {property!r} value {value!r}")


def reference_changed_topic_expectation(object: ResolvedObject, reference: str, target: ResolvedObject) -> TopicExpectationPlan:
    return TopicExpectationPlan("ak.wwise.core.object.referenceChanged", {"source": object.as_dict(), "target": target.as_dict()}, ("id", "path", "reference", "old", "new"), f"expect referenceChanged payload for {reference!r}")


def attenuation_curve_changed_topic_expectation(object: ResolvedObject, curve_type: str) -> TopicExpectationPlan:
    return TopicExpectationPlan("ak.wwise.core.object.attenuationCurveChanged", object.as_dict(), ("id", "path", "curveType", "old", "new"), f"expect attenuationCurveChanged payload for {curve_type!r}")


def curve_changed_topic_expectation(object: ResolvedObject, curve_type: str) -> TopicExpectationPlan:
    return TopicExpectationPlan("ak.wwise.core.object.curveChanged", object.as_dict(), ("id", "path", "curveType", "old", "new"), f"expect curveChanged payload for {curve_type!r}")


def _preview_metadata(
    operation: PropertyReferenceOperation,
    schema_validation: SchemaValidationResult,
    source_note: Mapping[str, Any],
    operation_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "builder_family": BuilderFamily.PROPERTY_REFERENCE.value,
        "operation": operation.value,
        "uri": SUPPORTED_PROPERTY_REFERENCE_URIS[operation],
        "read_only": False,
        "destructive_gate": {"required": True, "reason": "property/reference setter previews must be reviewed before dispatch"},
        "source_note": dict(source_note),
        "schema_validation": schema_validation.as_dict(),
        "applicability": dict(operation_metadata),
    }


def _resolved_exact_object(name: str, identity: ObjectIdentity | ResolvedObject) -> ResolvedObject:
    if isinstance(identity, ResolvedObject):
        return identity
    if not isinstance(identity, ObjectIdentity):
        raise _type_error(name, "ObjectIdentity or ResolvedObject", identity)
    resolved = resolve_object_identity(identity, destructive_use=True)
    if not isinstance(resolved, ResolvedObject):
        raise SemanticValidationError(
            SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY,
            f"{name} must resolve to an exact object before preview generation.",
            details={"identity": identity.as_dict()},
        )
    return resolved


def _object_value_readback(object: ResolvedObject, return_fields: tuple[str, ...], description: str) -> tuple[SemanticReadbackPlan, ...]:
    try:
        object_literal = quote_waql_literal(str(object.object))
    except ValueError as exc:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            str(exc),
            details={"object": object.object, "boundary": "packaged-waql-literal-evidence"},
        ) from exc
    return (
        SemanticReadbackPlan(
            OBJECT_GET_URI,
            args={"waql": f"from object {object_literal}"},
            options={"return": list(return_fields)},
            description=description,
        ),
    )


def _require_metadata_match(name: str, metadata: PropertyInfoMetadataRecord) -> None:
    _require_non_empty_string("name", name)
    if metadata.name != name:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
            "Property/reference metadata name must match the requested setter name.",
            details={"requested": name, "metadata_name": metadata.name},
        )


def _require_property_value(metadata: PropertyInfoMetadataRecord, value: Any) -> None:
    expected = _value_kind(metadata.type)
    if expected == "number" and _is_number(value):
        return
    if expected == "integer" and isinstance(value, int) and not isinstance(value, bool):
        return
    if expected == "boolean" and isinstance(value, bool):
        return
    if expected == "string" and isinstance(value, str):
        return
    if expected == "any":
        return
    raise SemanticValidationError(
        SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
        f"Value for property {metadata.name!r} does not match metadata type {metadata.type!r}.",
        details={"property": metadata.name, "metadata_type": metadata.type, "expected_value_kind": expected, "actual_type": type(value).__name__},
    )


def _require_reference_metadata(metadata: PropertyInfoMetadataRecord) -> None:
    restriction_type = metadata.restriction.get("type")
    supports_reference = (
        metadata.supports.get("reference") is True
        or metadata.type.lower() in {"reference", "objectreference"}
        or (isinstance(restriction_type, str) and restriction_type.casefold() == "reference")
    )
    constrained = metadata.supports.get("constrained") is True or bool(metadata.restriction.get("constraints")) or bool(metadata.restriction.get("ordering"))
    if not supports_reference:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
            f"Metadata for {metadata.name!r} does not describe a settable reference.",
            details={"reference": metadata.name, "metadata_type": metadata.type, "supports": dict(metadata.supports)},
        )
    if constrained:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
            "Constrained references are not set by this builder without explicit source-note ordering constraints.",
            details={"reference": metadata.name, "restriction": dict(metadata.restriction), "supports": dict(metadata.supports)},
        )


def _property_metadata_evidence(metadata: PropertyInfoMetadataRecord, property_enabled: bool | None, platform: str | int | None) -> dict[str, Any]:
    return {
        "kind": "metadata-applicability",
        "property_info": metadata.as_dict(),
        "property_enabled": property_enabled,
        "platform": platform,
    }


def _curve_point(point: CurvePoint | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(point, CurvePoint):
        return point.as_dict()
    if not isinstance(point, Mapping):
        raise _type_error("points[]", "mapping or CurvePoint", point)
    missing = tuple(field for field in ("x", "y", "shape") if field not in point)
    if missing:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "Curve points require explicit x, y, and shape fields.",
            details={"missing_fields": list(missing)},
        )
    _require_number("x", point["x"])
    _require_number("y", point["y"])
    _require_non_empty_string("shape", point["shape"])
    return {"x": point["x"], "y": point["y"], "shape": point["shape"]}


def _value_kind(value: str) -> str:
    normalized = value.lower()
    if normalized in {"real32", "real64", "double", "float", "number"}:
        return "number"
    if normalized in {"int16", "int32", "int64", "uint16", "uint32", "uint64", "integer"}:
        return "integer"
    if normalized in {"bool", "boolean"}:
        return "boolean"
    if normalized in {"string", "text"}:
        return "string"
    return "any"


def _require_non_empty_string(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise _type_error(name, "non-empty string", value)


def _require_number(name: str, value: Any) -> None:
    if not _is_number(value):
        raise _type_error(name, "number", value)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _require_object_arg(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, str | int) or (isinstance(value, str) and not value.strip()):
        raise _type_error(name, "non-empty WAAPI object/platform identifier", value)


def _type_error(field: str, expected: str, value: Any) -> SemanticValidationError:
    return SemanticValidationError(
        SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
        f"Property/reference argument {field!r} must be {expected}.",
        details={"field": field, "expected_type": expected, "actual_type": type(value).__name__},
    )
