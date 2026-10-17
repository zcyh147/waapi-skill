"""Exact field/class eligibility and evidence for Gateway-owned inline curves."""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from .builders.metadata import (
    ObjectTypeMetadataRecord, PropertyInfoMetadataRecord, bind_get_property_info_result,
    parse_get_types_result, parse_property_and_reference_names_result,
)
from .metadata_restrictions import reference_allowed_types, reference_type_token
from .operation_object import ObjectCurveDescriptor


Read = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]


class InlineCurveError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = code


def _curve_class(types: Sequence[ObjectTypeMetadataRecord]) -> dict[str, Any]:
    matches = [row for row in types if row.name == "Curve"]
    if len(matches) != 1 or not isinstance(matches[0].class_id, int) or isinstance(matches[0].class_id, bool):
        raise InlineCurveError("INLINE_CURVE_CLASS_UNAVAILABLE", "One exact live Curve class is required.")
    row = matches[0]
    return {"classId": row.class_id, "name": row.name, "type": row.type}


def require_inline_curve_field(restriction: Mapping[str, Any]) -> None:
    allowed = reference_allowed_types(restriction)
    if "curve" not in {reference_type_token(value) for value in allowed}:
        raise InlineCurveError("INLINE_CURVE_APPLICABILITY_UNPROVEN",
                               "Exact field metadata must explicitly allow the Curve class; generic reference kind is insufficient.")
    for row in restriction.get("restrictions", []):
        if row == "notNull":
            continue
        if not isinstance(row, Mapping) or "type" not in row or set(row) - {"type", "sharedOnlyTypes"}:
            raise InlineCurveError("INLINE_CURVE_CLASSIFIER_UNPROVEN",
                                   "This inline field requires additional target-classifier evidence.")
        shared = row.get("sharedOnlyTypes", [])
        if (not isinstance(shared, list) or not all(isinstance(value, str) and value for value in shared)
                or not {reference_type_token(value) for value in shared} <= {reference_type_token(value) for value in row["type"]}):
            raise InlineCurveError("INVALID_METADATA", "Shared-only Curve metadata must be an exact subset of its allowed class types.")
        if "curve" in {reference_type_token(value) for value in shared}:
            raise InlineCurveError("INLINE_CURVE_SHARED_ONLY", "The field requires a shared Curve and cannot accept an in-place custom curve.")


def prepare_inline_curve(curve: ObjectCurveDescriptor, *, token: str,
                         metadata: PropertyInfoMetadataRecord, scope: Mapping[str, Any],
                         types: Sequence[ObjectTypeMetadataRecord]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require an explicit Curve class alternative; never infer it from Reference."""
    require_inline_curve_field(metadata.restriction)
    proof = {"scope": dict(scope), "token": token, "metadata": metadata.as_dict(include_raw=True),
             "curve_class": _curve_class(types)}
    return curve.native_value(), proof


def observe_inline_curve_proof(proof: Mapping[str, Any], *, read: Read) -> dict[str, Any]:
    scope, token = proof["scope"], proof["token"]
    names = parse_property_and_reference_names_result(read("ak.wwise.core.object.getPropertyAndReferenceNames", scope, {}))
    metadata = bind_get_property_info_result(read("ak.wwise.core.object.getPropertyInfo", {**scope, "property": token}, {}),
        field_token=token, available_names=tuple(row.name for row in names))
    types = parse_get_types_result(read("ak.wwise.core.object.getTypes", {}, {}))
    return {"scope": dict(scope), "token": token, "metadata": metadata.as_dict(include_raw=True),
            "curve_class": _curve_class(types)}
