from __future__ import annotations

from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticErrorCode,
    SemanticValidationError,
    SourceNoteCheck,
)
from wwise_waapi.builders.identity import ObjectIdentity, ResolvedObject  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.metadata import PropertyInfoMetadataRecord  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.properties import (  # pyright: ignore[reportMissingImports]
    SET_ATTENUATION_CURVE_URI,
    SET_NAME_URI,
    SET_NOTES_URI,
    SET_PROPERTY_URI,
    SET_RANDOMIZER_URI,
    SET_REFERENCE_URI,
    CurvePoint,
    PropertyReferenceBuilder,
    property_changed_topic_expectation,
)


class FakeSourceNoteChecker:
    def __init__(self, status: SourceNoteCheck | None = None) -> None:
        self.status = status or SourceNoteCheck(True, BuilderFamily.PROPERTY_REFERENCE.value, cited_fields=("setters",))
        self.calls: list[tuple[str, str]] = []

    def check(self, family: str, version: str = "2022.1") -> SourceNoteCheck:
        self.calls.append((family, version))
        return self.status


def builder(checker: FakeSourceNoteChecker | None = None) -> PropertyReferenceBuilder:
    return PropertyReferenceBuilder(source_note_checker=checker or FakeSourceNoteChecker())


def exact_sound() -> ObjectIdentity:
    return ObjectIdentity(id="{11111111-1111-1111-1111-111111111111}")


def exact_bus() -> ObjectIdentity:
    return ObjectIdentity(id="{22222222-2222-2222-2222-222222222222}")


def volume_info(**overrides: Any) -> PropertyInfoMetadataRecord:
    values = {"name": "Volume", "type": "Real32", "supports": {"randomizer": True}}
    values.update(overrides)
    return PropertyInfoMetadataRecord(**values)


def output_bus_info(**overrides: Any) -> PropertyInfoMetadataRecord:
    values = {"name": "OutputBus", "type": "Reference", "supports": {"reference": True}}
    values.update(overrides)
    return PropertyInfoMetadataRecord(**values)


def assert_mutating_preview(preview: Any, uri: str, args: dict[str, Any]) -> None:
    assert preview.source_note_family == BuilderFamily.PROPERTY_REFERENCE.value
    assert preview.requires_destructive_gate is True
    assert preview.raw_dispatch_allowed is False
    assert preview.dispatch_payload() == {"uri": uri, "args": args, "options": {}}
    assert preview.to_dispatcher_request().dry_run is True
    assert preview.envelope.metadata["builder_family"] == BuilderFamily.PROPERTY_REFERENCE.value
    assert preview.envelope.metadata["read_only"] is False
    assert preview.envelope.metadata["schema_validation"]["uri"] == uri
    assert preview.evidence_plan[0]["kind"] == "source-note"
    assert preview.evidence_plan[1]["kind"] == "schema"


def test_set_name_and_notes_return_preview_with_readback_and_topic_evidence() -> None:
    name_preview = builder().set_name(object=exact_sound(), value="Renamed")
    assert_mutating_preview(name_preview, SET_NAME_URI, {"object": exact_sound().id, "value": "Renamed"})
    assert name_preview.readback_plan[0].uri == "ak.wwise.core.object.get"
    assert name_preview.readback_plan[0].options == {"return": ["id", "name", "path", "type"]}
    assert name_preview.evidence_plan[2]["topic"] == "ak.wwise.core.object.nameChanged"
    assert name_preview.evidence_plan[2]["live_subscription"] is False

    notes_preview = builder().set_notes(object=exact_sound(), value="hello")
    assert_mutating_preview(notes_preview, SET_NOTES_URI, {"object": exact_sound().id, "value": "hello"})
    assert notes_preview.readback_plan[0].options == {"return": ["id", "notes", "path", "type"]}
    assert notes_preview.evidence_plan[2]["topic"] == "ak.wwise.core.object.notesChanged"


def test_set_property_requires_metadata_match() -> None:
    with pytest.raises(SemanticValidationError) as name_mismatch:
        builder().set_property(object=exact_sound(), property="Pitch", value=-3.0, property_info=volume_info())
    assert name_mismatch.value.error_code == SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED
    assert name_mismatch.value.details["metadata_name"] == "Volume"

    with pytest.raises(SemanticValidationError) as type_mismatch:
        builder().set_property(object=exact_sound(), property="Volume", value="loud", property_info=volume_info())
    assert type_mismatch.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert type_mismatch.value.details["expected_value_kind"] == "number"

    with pytest.raises(SemanticValidationError) as disabled:
        builder().set_property(object=exact_sound(), property="Volume", value=-6.0, property_info=volume_info(), property_enabled=False)
    assert disabled.value.error_code == SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED


def test_set_property_preview_records_metadata_platform_and_topic_plan() -> None:
    preview = builder().set_property(
        object=exact_sound(),
        property="Volume",
        value=-6.0,
        property_info=volume_info(),
        property_enabled=True,
        platform="Windows",
    )

    assert_mutating_preview(
        preview,
        SET_PROPERTY_URI,
        {"object": exact_sound().id, "property": "Volume", "value": -6.0, "platform": "Windows"},
    )
    assert preview.readback_plan[0].options == {"return": ["id", "path", "Volume"]}
    assert preview.envelope.metadata["applicability"]["property_info"]["name"] == "Volume"
    assert preview.envelope.metadata["applicability"]["property_enabled"] is True
    assert preview.evidence_plan[2]["topic"] == "ak.wwise.core.object.propertyChanged"
    assert preview.evidence_plan[3]["kind"] == "metadata-applicability"


def test_set_reference_requires_explicit_target_identity() -> None:
    with pytest.raises(SemanticValidationError) as name_only_target:
        builder().set_reference(
            object=exact_sound(),
            reference="OutputBus",
            target=ObjectIdentity(name="Master Audio Bus"),
            reference_info=output_bus_info(),
        )
    assert name_only_target.value.error_code == SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY

    with pytest.raises(SemanticValidationError) as not_reference:
        builder().set_reference(object=exact_sound(), reference="OutputBus", target=exact_bus(), reference_info=volume_info(name="OutputBus"))
    assert not_reference.value.error_code == SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED

    with pytest.raises(SemanticValidationError) as constrained:
        builder().set_reference(
            object=exact_sound(),
            reference="OutputBus",
            target=exact_bus(),
            reference_info=output_bus_info(supports={"reference": True, "constrained": True}),
        )
    assert constrained.value.error_code == SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED


def test_set_reference_preview_uses_target_object_value_and_evidence_plan() -> None:
    preview = builder().set_reference(object=exact_sound(), reference="OutputBus", target=exact_bus(), reference_info=output_bus_info())

    assert_mutating_preview(
        preview,
        SET_REFERENCE_URI,
        {"object": exact_sound().id, "reference": "OutputBus", "value": exact_bus().id},
    )
    assert preview.envelope.metadata["applicability"]["target_identity"]["object"] == exact_bus().id
    assert preview.evidence_plan[2]["topic"] == "ak.wwise.core.object.referenceChanged"


def test_set_randomizer_requires_support_and_one_randomizer_field() -> None:
    with pytest.raises(SemanticValidationError) as unsupported:
        builder().set_randomizer(object=exact_sound(), property="Volume", property_info=volume_info(supports={}))
    assert unsupported.value.error_code == SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED

    with pytest.raises(SemanticValidationError) as missing_value:
        builder().set_randomizer(object=exact_sound(), property="Volume", property_info=volume_info())
    assert missing_value.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH

    preview = builder().set_randomizer(object=exact_sound(), property="Volume", property_info=volume_info(), enabled=True, min=-3.0, max=3.0)
    assert_mutating_preview(
        preview,
        SET_RANDOMIZER_URI,
        {"object": exact_sound().id, "property": "Volume", "enabled": True, "min": -3.0, "max": 3.0},
    )


def test_set_attenuation_curve_requires_explicit_points_shape_fields() -> None:
    with pytest.raises(SemanticValidationError) as empty_points:
        builder().set_attenuation_curve(object=exact_sound(), curve_type="VolumeDryUsage", use="Custom", points=[])
    assert empty_points.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH

    with pytest.raises(SemanticValidationError) as missing_shape:
        builder().set_attenuation_curve(object=exact_sound(), curve_type="VolumeDryUsage", use="Custom", points=[{"x": 0, "y": 0}])
    assert missing_shape.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert missing_shape.value.details["missing_fields"] == ["shape"]

    preview = builder().set_attenuation_curve(
        object=exact_sound(),
        curve_type="VolumeDryUsage",
        use="Custom",
        points=[CurvePoint(x=0.0, y=0.0, shape="Linear"), {"x": 100.0, "y": -96.0, "shape": "Constant"}],
    )
    assert_mutating_preview(
        preview,
        SET_ATTENUATION_CURVE_URI,
        {
            "object": exact_sound().id,
            "curveType": "VolumeDryUsage",
            "use": "Custom",
            "points": [{"x": 0.0, "y": 0.0, "shape": "Linear"}, {"x": 100.0, "y": -96.0, "shape": "Constant"}],
        },
    )
    assert preview.readback_plan[0].uri == "ak.wwise.core.object.getAttenuationCurve"
    assert preview.evidence_plan[2]["topic"] == "ak.wwise.core.object.attenuationCurveChanged"


def test_source_note_must_unlock_before_property_preview() -> None:
    checker = FakeSourceNoteChecker(
        SourceNoteCheck(False, BuilderFamily.PROPERTY_REFERENCE.value, missing_fields=("return_shape",), reason="incomplete")
    )

    with pytest.raises(SemanticValidationError) as exc:
        PropertyReferenceBuilder(source_note_checker=checker).set_property(
            object=exact_sound(), property="Volume", value=-6.0, property_info=volume_info()
        )

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
    assert checker.calls == [(BuilderFamily.PROPERTY_REFERENCE.value, "2022.1")]


def test_topic_expectation_helper_is_evidence_plan_only() -> None:
    object = ResolvedObject(identity=exact_sound(), object=str(exact_sound().id), resolution="exact-id", row={"id": exact_sound().id})
    plan = property_changed_topic_expectation(object, "Volume", -3.0).as_dict()

    assert plan["kind"] == "topic-expectation"
    assert plan["topic"] == "ak.wwise.core.object.propertyChanged"
    assert plan["live_subscription"] is False
    assert plan["required_payload_fields"] == ["id", "path", "property", "old", "new"]
