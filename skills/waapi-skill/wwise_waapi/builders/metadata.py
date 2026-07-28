"""Read-only property/reference metadata builders and parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from wwise_waapi.dispatcher import DEFAULT_WWISE_VERSION

from .common import (
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
from .schema import SemanticSchemaValidator, SchemaValidationResult  # pyright: ignore[reportMissingImports]
from .source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]


GET_TYPES_URI = "ak.wwise.core.object.getTypes"
GET_PROPERTY_AND_REFERENCE_NAMES_URI = "ak.wwise.core.object.getPropertyAndReferenceNames"
GET_PROPERTY_INFO_URI = "ak.wwise.core.object.getPropertyInfo"
IS_PROPERTY_ENABLED_URI = "ak.wwise.core.object.isPropertyEnabled"
GET_ATTENUATION_CURVE_URI = "ak.wwise.core.object.getAttenuationCurve"


class MetadataOperation(str, Enum):
    """Supported read-only metadata discovery operations."""

    GET_TYPES = "getTypes"
    GET_PROPERTY_AND_REFERENCE_NAMES = "getPropertyAndReferenceNames"
    GET_PROPERTY_INFO = "getPropertyInfo"
    IS_PROPERTY_ENABLED = "isPropertyEnabled"
    GET_ATTENUATION_CURVE = "getAttenuationCurve"


SUPPORTED_METADATA_URIS: Mapping[MetadataOperation, str] = {
    MetadataOperation.GET_TYPES: GET_TYPES_URI,
    MetadataOperation.GET_PROPERTY_AND_REFERENCE_NAMES: GET_PROPERTY_AND_REFERENCE_NAMES_URI,
    MetadataOperation.GET_PROPERTY_INFO: GET_PROPERTY_INFO_URI,
    MetadataOperation.IS_PROPERTY_ENABLED: IS_PROPERTY_ENABLED_URI,
    MetadataOperation.GET_ATTENUATION_CURVE: GET_ATTENUATION_CURVE_URI,
}


@dataclass(slots=True, frozen=True)
class MetadataReturnExpectation:
    """Normalized downstream parser expectation for one metadata URI."""

    parser: str
    shape: str
    required_fields: tuple[str, ...] = ()
    allow_documented_empty: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "parser": self.parser,
            "shape": self.shape,
            "required_fields": list(self.required_fields),
            "allow_documented_empty": self.allow_documented_empty,
        }


@dataclass(slots=True, frozen=True)
class ObjectTypeMetadataRecord:
    """One row from ``ak.wwise.core.object.getTypes``."""

    class_id: int
    name: str
    type: str
    raw: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        payload = {
            "classId": self.class_id,
            "name": self.name,
            "type": self.type,
        }
        if include_raw:
            payload["raw"] = dict(self.raw)
        return payload


@dataclass(slots=True, frozen=True)
class PropertyReferenceNameRecord:
    """One property/reference name returned for an object class."""

    name: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name}


@dataclass(slots=True, frozen=True)
class PropertyInfoMetadataRecord:
    """Selected required and optional metadata from ``getPropertyInfo``."""

    name: str
    type: str
    default: Any = None
    supports: Mapping[str, Any] = field(default_factory=dict)
    display: Mapping[str, Any] = field(default_factory=dict)
    restriction: Mapping[str, Any] = field(default_factory=dict)
    dependencies: tuple[Mapping[str, Any], ...] = ()
    ui: Mapping[str, Any] = field(default_factory=dict)
    audio_engine_id: int | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "supports": dict(self.supports),
            "display": dict(self.display),
            "restriction": dict(self.restriction),
            "dependencies": [dict(item) for item in self.dependencies],
            "ui": dict(self.ui),
            "audioEngineId": self.audio_engine_id,
        }
        if include_raw:
            payload["raw"] = dict(self.raw)
        return payload


@dataclass(slots=True, frozen=True)
class PropertyEnabledMetadataRecord:
    """Parsed boolean result from ``isPropertyEnabled``."""

    enabled: bool

    def as_dict(self) -> dict[str, bool]:
        return {"enabled": self.enabled}


@dataclass(slots=True, frozen=True)
class AttenuationCurveMetadataRecord:
    """Metadata returned for one attenuation curve when Wwise provides it."""

    curve_type: str
    use: str
    points: tuple[Mapping[str, Any], ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        payload = {
            "curveType": self.curve_type,
            "use": self.use,
            "points": [dict(point) for point in self.points],
        }
        if include_raw:
            payload["raw"] = dict(self.raw)
        return payload


@dataclass(slots=True, frozen=True)
class MetadataBuilder:
    """Build source-grounded metadata discovery previews without dispatching."""

    version: str = DEFAULT_WWISE_VERSION
    source_note_checker: SourceNoteChecker | None = None
    manifest_loader: ManifestSchemaLoader = field(default_factory=ManifestSchemaLoader)

    def get_types(self) -> SemanticPreview:
        return self._build_preview(
            MetadataOperation.GET_TYPES,
            {},
            MetadataReturnExpectation(
                parser="parse_get_types_result",
                shape="object-with-return-array",
                required_fields=("return[].classId", "return[].name", "return[].type"),
            ),
        )

    def get_property_and_reference_names(self, *, object: str | int | None = None, class_id: int | None = None) -> SemanticPreview:
        args = _exactly_one_scope(object=object, class_id=class_id)
        return self._build_preview(
            MetadataOperation.GET_PROPERTY_AND_REFERENCE_NAMES,
            args,
            MetadataReturnExpectation(
                parser="parse_property_and_reference_names_result",
                shape="object-with-return-string-array",
                required_fields=("return",),
            ),
        )

    def get_property_info(self, *, property: str, object: str | int | None = None, class_id: int | None = None) -> SemanticPreview:
        _require_non_empty_string("property", property)
        args: dict[str, Any] = {"property": property}
        args.update(_exactly_one_scope(object=object, class_id=class_id))
        return self._build_preview(
            MetadataOperation.GET_PROPERTY_INFO,
            args,
            MetadataReturnExpectation(
                parser="parse_get_property_info_result",
                shape="object",
                required_fields=("name", "type"),
            ),
        )

    def is_property_enabled(self, *, object: str | int, property: str, platform: str | int) -> SemanticPreview:
        _require_object_arg("object", object)
        _require_non_empty_string("property", property)
        _require_object_arg("platform", platform)
        return self._build_preview(
            MetadataOperation.IS_PROPERTY_ENABLED,
            {"object": object, "property": property, "platform": platform},
            MetadataReturnExpectation(parser="parse_is_property_enabled_result", shape="object-with-return-boolean", required_fields=("return",)),
        )

    def get_attenuation_curve(self, *, object: str | int, curve_type: str, platform: str | int | None = None) -> SemanticPreview:
        _require_object_arg("object", object)
        _require_non_empty_string("curve_type", curve_type)
        args: dict[str, Any] = {"object": object, "curveType": curve_type}
        if platform is not None:
            _require_object_arg("platform", platform)
            args["platform"] = platform
        return self._build_preview(
            MetadataOperation.GET_ATTENUATION_CURVE,
            args,
            MetadataReturnExpectation(
                parser="parse_get_attenuation_curve_result",
                shape="object-or-documented-empty-object",
                required_fields=("curveType", "use"),
                allow_documented_empty=True,
            ),
        )

    def preview(self, operation: MetadataOperation | str, **kwargs: Any) -> SemanticPreview:
        """Build a preview by operation name or URI, rejecting unsupported metadata work."""

        normalized = _coerce_operation(operation)
        if normalized == MetadataOperation.GET_TYPES:
            _reject_kwargs(normalized, kwargs)
            return self.get_types()
        if normalized == MetadataOperation.GET_PROPERTY_AND_REFERENCE_NAMES:
            return self.get_property_and_reference_names(object=kwargs.get("object"), class_id=kwargs.get("class_id"))
        if normalized == MetadataOperation.GET_PROPERTY_INFO:
            return self.get_property_info(
                property=_required_kw(normalized, kwargs, "property"),
                object=kwargs.get("object"),
                class_id=kwargs.get("class_id"),
            )
        if normalized == MetadataOperation.IS_PROPERTY_ENABLED:
            return self.is_property_enabled(
                object=_required_kw(normalized, kwargs, "object"),
                property=_required_kw(normalized, kwargs, "property"),
                platform=_required_kw(normalized, kwargs, "platform"),
            )
        if normalized == MetadataOperation.GET_ATTENUATION_CURVE:
            return self.get_attenuation_curve(
                object=_required_kw(normalized, kwargs, "object"),
                curve_type=_required_kw(normalized, kwargs, "curve_type"),
                platform=kwargs.get("platform"),
            )
        raise _unsupported_metadata_error(str(operation))

    def _build_preview(
        self,
        operation: MetadataOperation,
        args: Mapping[str, Any],
        expectation: MetadataReturnExpectation,
    ) -> SemanticPreview:
        uri = SUPPORTED_METADATA_URIS[operation]
        context = BuilderContext(
            BuilderFamily.PROPERTY_REFERENCE,
            version=self.version,
            source_note_checker=self.source_note_checker or SemanticSourceNoteChecker(),
            manifest_loader=self.manifest_loader,
        )
        context.require_supported_family()
        source_note = context.require_source_note()
        schema_validation = SemanticSchemaValidator(manifest_loader=context.manifest_loader, version=context.version).validate(uri, args, {})
        envelope = SemanticEnvelope(
            uri,
            args=dict(args),
            options={},
            metadata=_preview_metadata(operation, expectation, schema_validation, source_note.as_dict()),
        )
        return SemanticPreview(
            envelope=envelope,
            source_note_family=BuilderFamily.PROPERTY_REFERENCE.value,
            version=self.version,
            readback_plan=(
                SemanticReadbackPlan(
                    uri,
                    args=dict(args),
                    options={},
                    description=f"parse metadata result with {expectation.parser}",
                ),
            ),
            evidence_plan=(
                {"kind": "source-note", "family": BuilderFamily.PROPERTY_REFERENCE.value, "status": source_note.as_dict()},
                {"kind": "schema", "validation": schema_validation.as_dict()},
            ),
        )


def build_metadata_preview(operation: MetadataOperation | str, **kwargs: Any) -> SemanticPreview:
    """Convenience wrapper around :class:`MetadataBuilder`."""

    return MetadataBuilder().preview(operation, **kwargs)


def parse_get_types_result(result: Mapping[str, Any]) -> tuple[ObjectTypeMetadataRecord, ...]:
    rows = _return_list(GET_TYPES_URI, result)
    records: list[ObjectTypeMetadataRecord] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise _result_error(GET_TYPES_URI, "getTypes return rows must be objects.", row_index=index, actual_type=type(row).__name__)
        _require_result_fields(GET_TYPES_URI, row, ("classId", "name", "type"), row_index=index)
        if not _is_uint32(row["classId"]):
            raise _result_error(GET_TYPES_URI, "getTypes classId must be an integer.", row_index=index, field="classId")
        if not isinstance(row["name"], str) or not isinstance(row["type"], str):
            raise _result_error(GET_TYPES_URI, "getTypes name and type must be strings.", row_index=index)
        records.append(ObjectTypeMetadataRecord(class_id=row["classId"], name=row["name"], type=row["type"], raw=dict(row)))
    return tuple(records)


def parse_property_and_reference_names_result(result: Mapping[str, Any]) -> tuple[PropertyReferenceNameRecord, ...]:
    values = _return_list(GET_PROPERTY_AND_REFERENCE_NAMES_URI, result)
    records: list[PropertyReferenceNameRecord] = []
    for index, value in enumerate(values):
        if not isinstance(value, str):
            raise _result_error(
                GET_PROPERTY_AND_REFERENCE_NAMES_URI,
                "Property/reference names must be strings.",
                row_index=index,
                actual_type=type(value).__name__,
            )
        records.append(PropertyReferenceNameRecord(name=value))
    return tuple(records)


def parse_get_property_info_result(result: Mapping[str, Any]) -> PropertyInfoMetadataRecord:
    _require_result_mapping(GET_PROPERTY_INFO_URI, result)
    _require_result_fields(GET_PROPERTY_INFO_URI, result, ("name", "type"))
    if not isinstance(result["name"], str) or not isinstance(result["type"], str):
        raise _result_error(GET_PROPERTY_INFO_URI, "Property info name and type must be strings.")
    dependencies = result.get("dependencies", ())
    if dependencies is None:
        dependencies = ()
    if not isinstance(dependencies, list | tuple) or not all(isinstance(item, Mapping) for item in dependencies):
        raise _result_error(GET_PROPERTY_INFO_URI, "Property info dependencies must be an array of objects when present.")
    audio_engine_id = result.get("audioEngineId")
    if audio_engine_id is not None and not _is_uint32(audio_engine_id):
        raise _result_error(GET_PROPERTY_INFO_URI, "Property info audioEngineId must be a non-negative integer when present.")
    return PropertyInfoMetadataRecord(
        name=result["name"],
        type=result["type"],
        default=result.get("default"),
        supports=_mapping_or_empty(result.get("supports")),
        display=_mapping_or_empty(result.get("display")),
        restriction=_mapping_or_empty(result.get("restriction")),
        dependencies=tuple(dict(item) for item in dependencies),
        ui=_mapping_or_empty(result.get("ui")),
        audio_engine_id=audio_engine_id,
        raw=dict(result),
    )


def parse_is_property_enabled_result(result: Mapping[str, Any]) -> PropertyEnabledMetadataRecord:
    _require_result_mapping(IS_PROPERTY_ENABLED_URI, result)
    _require_result_fields(IS_PROPERTY_ENABLED_URI, result, ("return",))
    if not isinstance(result["return"], bool):
        raise _result_error(IS_PROPERTY_ENABLED_URI, "isPropertyEnabled return must be a boolean.")
    return PropertyEnabledMetadataRecord(enabled=result["return"])


def parse_get_attenuation_curve_result(
    result: Mapping[str, Any],
    *,
    allow_documented_empty: bool = False,
) -> AttenuationCurveMetadataRecord | None:
    _require_result_mapping(GET_ATTENUATION_CURVE_URI, result)
    if not result and allow_documented_empty:
        return None
    _require_result_fields(GET_ATTENUATION_CURVE_URI, result, ("curveType", "use"))
    if not isinstance(result["curveType"], str) or not isinstance(result["use"], str):
        raise _result_error(GET_ATTENUATION_CURVE_URI, "Attenuation curve curveType and use must be strings.")
    points = result.get("points", ())
    if points is None:
        points = ()
    if not isinstance(points, list | tuple) or not all(isinstance(point, Mapping) for point in points):
        raise _result_error(GET_ATTENUATION_CURVE_URI, "Attenuation curve points must be an array of objects when present.")
    return AttenuationCurveMetadataRecord(
        curve_type=result["curveType"],
        use=result["use"],
        points=tuple(dict(point) for point in points),
        raw=dict(result),
    )


def _preview_metadata(
    operation: MetadataOperation,
    expectation: MetadataReturnExpectation,
    schema_validation: SchemaValidationResult,
    source_note: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "builder_family": BuilderFamily.PROPERTY_REFERENCE.value,
        "operation": operation.value,
        "uri": SUPPORTED_METADATA_URIS[operation],
        "read_only": True,
        "return_expectation": expectation.as_dict(),
        "schema_validation": schema_validation.as_dict(),
        "source_note": dict(source_note),
    }


def _coerce_operation(operation: MetadataOperation | str) -> MetadataOperation:
    if isinstance(operation, MetadataOperation):
        return operation
    for candidate, uri in SUPPORTED_METADATA_URIS.items():
        if operation in {candidate.value, uri}:
            return candidate
    raise _unsupported_metadata_error(str(operation))


def _unsupported_metadata_error(operation: str) -> SemanticValidationError:
    return SemanticValidationError(
        SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED,
        f"Unsupported property/reference metadata operation: {operation}",
        details={"operation": operation, "supported": [operation.value for operation in MetadataOperation]},
    )


def _required_kw(operation: MetadataOperation, kwargs: Mapping[str, Any], key: str) -> Any:
    if key not in kwargs:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"Metadata operation {operation.value} requires {key!r}.",
            details={"operation": operation.value, "missing_args": [key]},
        )
    return kwargs[key]


def _reject_kwargs(operation: MetadataOperation, kwargs: Mapping[str, Any]) -> None:
    if kwargs:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"Metadata operation {operation.value} does not accept arguments.",
            details={"operation": operation.value, "unknown_fields": sorted(kwargs)},
        )


def _exactly_one_scope(*, object: str | int | None, class_id: int | None) -> dict[str, Any]:
    has_object = object is not None
    has_class = class_id is not None
    if has_object == has_class:
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            "getPropertyInfo requires exactly one identity scope: object or class_id.",
            details={"missing_arg_families": [["object"], ["class_id"]], "object_supplied": has_object, "class_id_supplied": has_class},
        )
    if has_class:
        assert class_id is not None
        _require_uint32("class_id", class_id)
        return {"classId": class_id}
    assert object is not None
    _require_object_arg("object", object)
    return {"object": object}


def _require_non_empty_string(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"Metadata argument {name!r} must be a non-empty string.",
            details={"field": name, "expected_type": "non-empty string", "actual_type": type(value).__name__},
        )


def _require_uint32(name: str, value: Any) -> None:
    if not _is_uint32(value):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"Metadata argument {name!r} must be a non-negative integer class id.",
            details={"field": name, "expected_type": "uint32", "actual_type": type(value).__name__},
        )


def _is_uint32(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0xFFFFFFFF


def _require_object_arg(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, str | int) or (isinstance(value, str) and not value.strip()):
        raise SemanticValidationError(
            SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
            f"Metadata argument {name!r} must be a non-empty WAAPI object/platform identifier.",
            details={"field": name, "expected_type": "objectArg", "actual_type": type(value).__name__},
        )


def _return_list(uri: str, result: Mapping[str, Any]) -> list[Any]:
    _require_result_mapping(uri, result)
    _require_result_fields(uri, result, ("return",))
    values = result["return"]
    if not isinstance(values, list):
        raise _result_error(uri, "Metadata result return field must be an array.", field="return", actual_type=type(values).__name__)
    return values


def _require_result_mapping(uri: str, result: Mapping[str, Any]) -> None:
    if not isinstance(result, Mapping):
        raise _result_error(uri, "Metadata result must be a JSON object.", actual_type=type(result).__name__)


def _require_result_fields(uri: str, result: Mapping[str, Any], fields: tuple[str, ...], **details: Any) -> None:
    missing = tuple(field for field in fields if field not in result)
    if missing:
        raise _result_error(uri, "Metadata result is missing required fields.", missing_fields=missing, **details)


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _result_error(uri: str, message: str, **details: Any) -> SemanticValidationError:
    normalized = {key: list(value) if isinstance(value, tuple) else value for key, value in details.items()}
    return SemanticValidationError(
        SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH,
        message,
        details={"uri": uri, **normalized},
    )
