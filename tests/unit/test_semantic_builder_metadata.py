from __future__ import annotations

from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticErrorCode,
    SemanticValidationError,
    SourceNoteCheck,
)
from wwise_waapi.builders.metadata import (  # pyright: ignore[reportMissingImports]
    GET_ATTENUATION_CURVE_URI,
    GET_PROPERTY_AND_REFERENCE_NAMES_URI,
    GET_PROPERTY_INFO_URI,
    GET_TYPES_URI,
    IS_PROPERTY_ENABLED_URI,
    MetadataBuilder,
    MetadataOperation,
    build_metadata_preview,
    parse_get_attenuation_curve_result,
    parse_get_property_info_result,
    parse_get_types_result,
    parse_is_property_enabled_result,
    parse_property_and_reference_names_result,
)


class FakeSourceNoteChecker:
    def __init__(self, status: SourceNoteCheck | None = None) -> None:
        self.status = status or SourceNoteCheck(True, BuilderFamily.PROPERTY_REFERENCE.value, cited_fields=("metadata",))
        self.calls: list[tuple[str, str]] = []

    def check(self, family: str, version: str = "2022.1") -> SourceNoteCheck:
        self.calls.append((family, version))
        return self.status


def builder(checker: FakeSourceNoteChecker | None = None) -> MetadataBuilder:
    return MetadataBuilder(source_note_checker=checker or FakeSourceNoteChecker())


def assert_preview(preview: Any, uri: str, args: dict[str, Any], parser: str) -> None:
    assert preview.source_note_family == BuilderFamily.PROPERTY_REFERENCE.value
    assert preview.requires_destructive_gate is False
    assert preview.raw_dispatch_allowed is False
    assert preview.dispatch_payload() == {"uri": uri, "args": args, "options": {}}
    assert preview.to_dispatcher_request().dry_run is True
    assert preview.readback_plan[0].uri == uri
    assert preview.readback_plan[0].args == args
    assert preview.envelope.metadata["builder_family"] == BuilderFamily.PROPERTY_REFERENCE.value
    assert preview.envelope.metadata["read_only"] is True
    assert preview.envelope.metadata["return_expectation"]["parser"] == parser
    assert preview.envelope.metadata["schema_validation"]["uri"] == uri


def test_get_types_envelope() -> None:
    checker = FakeSourceNoteChecker()

    preview = MetadataBuilder(source_note_checker=checker).get_types()

    assert_preview(preview, GET_TYPES_URI, {}, "parse_get_types_result")
    assert checker.calls == [(BuilderFamily.PROPERTY_REFERENCE.value, "2022.1")]


def test_property_and_reference_names_envelope() -> None:
    preview = builder().get_property_and_reference_names(class_id=123)

    assert_preview(preview, GET_PROPERTY_AND_REFERENCE_NAMES_URI, {"classId": 123}, "parse_property_and_reference_names_result")


def test_property_and_reference_names_object_scope_envelope() -> None:
    preview = builder().get_property_and_reference_names(object="{sound}")

    assert_preview(preview, GET_PROPERTY_AND_REFERENCE_NAMES_URI, {"object": "{sound}"}, "parse_property_and_reference_names_result")

    with pytest.raises(SemanticValidationError) as both:
        builder().get_property_and_reference_names(object="{sound}", class_id=123)
    assert both.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_get_property_info_envelope() -> None:
    preview = builder().get_property_info(class_id=123, property="Volume")

    assert_preview(preview, GET_PROPERTY_INFO_URI, {"classId": 123, "property": "Volume"}, "parse_get_property_info_result")
    assert preview.envelope.metadata["return_expectation"]["required_fields"] == ["name", "type"]


def test_get_property_info_object_scope_envelope() -> None:
    preview = builder().get_property_info(object="{11111111-1111-1111-1111-111111111111}", property="Volume")

    assert_preview(
        preview,
        GET_PROPERTY_INFO_URI,
        {"object": "{11111111-1111-1111-1111-111111111111}", "property": "Volume"},
        "parse_get_property_info_result",
    )


def test_get_property_info_requires_exactly_one_scope() -> None:
    with pytest.raises(SemanticValidationError) as missing:
        builder().get_property_info(property="Volume")
    assert missing.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH

    with pytest.raises(SemanticValidationError) as both:
        builder().get_property_info(object="\\Actor-Mixer Hierarchy\\Default Work Unit\\Sound", class_id=123, property="Volume")
    assert both.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_is_property_enabled_envelope_requires_manifest_platform() -> None:
    preview = builder().is_property_enabled(object="{sound}", property="Volume", platform="Windows")

    assert_preview(
        preview,
        IS_PROPERTY_ENABLED_URI,
        {"object": "{sound}", "property": "Volume", "platform": "Windows"},
        "parse_is_property_enabled_result",
    )

    with pytest.raises(SemanticValidationError) as exc:
        build_metadata_preview(MetadataOperation.IS_PROPERTY_ENABLED, object="{sound}", property="Volume")
    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["missing_args"] == ["platform"]


def test_get_attenuation_curve_envelope() -> None:
    preview = builder().get_attenuation_curve(object="{attenuation}", curve_type="VolumeDryUsage")

    assert_preview(
        preview,
        GET_ATTENUATION_CURVE_URI,
        {"object": "{attenuation}", "curveType": "VolumeDryUsage"},
        "parse_get_attenuation_curve_result",
    )
    assert preview.envelope.metadata["return_expectation"]["allow_documented_empty"] is True


def test_unsupported_metadata_operation_rejected_with_typed_error() -> None:
    with pytest.raises(SemanticValidationError) as exc:
        build_metadata_preview("ak.wwise.core.object.setProperty", object="{sound}", property="Volume", value=0)

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED
    assert exc.value.details["operation"] == "ak.wwise.core.object.setProperty"


def test_source_note_must_unlock_before_preview() -> None:
    checker = FakeSourceNoteChecker(
        SourceNoteCheck(
            False,
            BuilderFamily.PROPERTY_REFERENCE.value,
            missing_fields=("return_shape",),
            reason="incomplete source note",
        )
    )

    with pytest.raises(SemanticValidationError) as exc:
        MetadataBuilder(source_note_checker=checker).get_types()

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
    assert checker.calls == [(BuilderFamily.PROPERTY_REFERENCE.value, "2022.1")]


def test_get_types_parser_returns_records_and_rejects_missing_required_fields() -> None:
    records = parse_get_types_result({"return": [{"classId": 1, "name": "Sound", "type": "Sound"}]})

    assert records[0].class_id == 1
    assert records[0].as_dict()["name"] == "Sound"

    with pytest.raises(SemanticValidationError) as exc:
        parse_get_types_result({"return": [{"name": "Sound", "type": "Sound"}]})
    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["missing_fields"] == ["classId"]

    with pytest.raises(SemanticValidationError) as negative:
        parse_get_types_result({"return": [{"classId": -1, "name": "Sound", "type": "Sound"}]})
    assert negative.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_property_and_reference_names_parser_requires_return_string_array() -> None:
    records = parse_property_and_reference_names_result({"return": ["Volume", "OutputBus"]})

    assert [record.name for record in records] == ["Volume", "OutputBus"]

    with pytest.raises(SemanticValidationError) as exc:
        parse_property_and_reference_names_result({"return": ["Volume", 1]})
    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_property_info_parser_rejects_missing_required_fields() -> None:
    record = parse_get_property_info_result({"name": "Volume", "type": "Real32", "supports": {"randomizer": True}})

    assert record.name == "Volume"
    assert record.supports == {"randomizer": True}

    with pytest.raises(SemanticValidationError) as exc:
        parse_get_property_info_result({"name": "Volume"})
    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["missing_fields"] == ["type"]

    with pytest.raises(SemanticValidationError) as negative:
        parse_get_property_info_result({"name": "Volume", "type": "Real32", "audioEngineId": -1})
    assert negative.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_property_enabled_parser_rejects_non_boolean_return() -> None:
    assert parse_is_property_enabled_result({"return": False}).enabled is False

    with pytest.raises(SemanticValidationError) as exc:
        parse_is_property_enabled_result({"return": "false"})
    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_attenuation_curve_empty_response_policy() -> None:
    assert parse_get_attenuation_curve_result({}, allow_documented_empty=True) is None

    record = parse_get_attenuation_curve_result({"curveType": "VolumeDryUsage", "use": "Custom", "points": []})
    assert record is not None
    assert record.curve_type == "VolumeDryUsage"

    with pytest.raises(SemanticValidationError) as exc:
        parse_get_attenuation_curve_result({}, allow_documented_empty=False)
    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["missing_fields"] == ["curveType", "use"]
