from __future__ import annotations

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    ManifestSchemaLoader,
    SemanticErrorCode,
    SemanticValidationError,
)
from wwise_waapi.builders.schema import (  # pyright: ignore[reportMissingImports]
    SemanticSchemaValidator,
    validate_semantic_payload,
)
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]


def fake_manifest_loader() -> ManifestSchemaLoader:
    store = ManifestStore()
    store.record(
        "2022.1",
        {
            "schemas": [
                {
                    "uri": "ak.wwise.core.object.delete",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "properties": {"object": {"type": "string"}},
                            "required": ["object"],
                            "type": "object",
                        },
                        "optionsSchema": {"additionalProperties": False, "properties": {}, "type": "object"},
                    },
                },
                {
                    "uri": "ak.wwise.core.object.getPropertyInfo",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "oneOf": [{"required": ["object"]}, {"required": ["classId"]}],
                            "properties": {
                                "object": {"type": "string"},
                                "classId": {"type": "integer"},
                            },
                            "type": "object",
                        },
                        "optionsSchema": {"additionalProperties": False, "properties": {}, "type": "object"},
                    },
                },
                {
                    "uri": "ak.soundengine.seekOnEvent",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "oneOf": [
                                {"required": ["event", "gameObject", "position"]},
                                {"required": ["event", "gameObject", "percent"]},
                            ],
                            "properties": {
                                "event": {"type": "string"},
                                "gameObject": {"type": "integer"},
                                "position": {"type": "integer"},
                                "percent": {"type": "number"},
                            },
                            "type": "object",
                        },
                        "optionsSchema": {"additionalProperties": False, "properties": {}, "type": "object"},
                    },
                },
                {
                    "uri": "ak.test.discriminatedOneOf",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "oneOf": [
                                {
                                    "properties": {"mode": {"const": "first"}},
                                    "required": ["mode"],
                                },
                                {
                                    "properties": {"mode": {"const": "second"}},
                                    "required": ["mode"],
                                },
                            ],
                            "properties": {"mode": {"type": "string"}},
                            "type": "object",
                        },
                        "optionsSchema": {"additionalProperties": False, "properties": {}, "type": "object"},
                    },
                },
                {
                    "uri": "ak.test.patternProperties",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "patternProperties": {
                                "^@[:_a-zA-Z0-9]+$": {"type": "number"}
                            },
                            "properties": {"name": {"type": "string"}},
                            "type": "object",
                        },
                        "optionsSchema": {"additionalProperties": False, "properties": {}, "type": "object"},
                    },
                },
                {
                    "uri": "ak.test.invalidPatternProperties",
                    "status": "ok",
                    "schema": {
                        "argsSchema": {
                            "additionalProperties": False,
                            "patternProperties": {"[": {"type": "number"}},
                            "properties": {},
                            "type": "object",
                        },
                        "optionsSchema": {"additionalProperties": False, "properties": {}, "type": "object"},
                    },
                },
            ]
        },
    )
    return ManifestSchemaLoader(store)


def test_schema_validator_loads_supported_uri_from_manifest_resources() -> None:
    result = validate_semantic_payload(
        "ak.wwise.core.object.get",
        {"waql": "from type Sound"},
        {"return": ["id", "name"]},
    )

    assert result.uri == "ak.wwise.core.object.get"
    assert result.version == "2022.1"


@pytest.mark.parametrize(
    "version",
    ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
)
def test_versioned_object_create_schema_accepts_reflected_dynamic_property(
    version: str,
) -> None:
    result = validate_semantic_payload(
        "ak.wwise.core.object.create",
        {
            "parent": "{11111111-1111-1111-1111-111111111111}",
            "type": "ActorMixer",
            "name": "Root",
            "@Volume": -2.0,
            "children": [
                {"type": "Sound", "name": "Child", "@Volume": -3.0}
            ],
            "onNameConflict": "fail",
            "autoAddToSourceControl": False,
        },
        {},
        version=version,
    )

    assert result.version == version
    assert result.required_fields == ("type", "name", "parent")
    assert any(
        reference.endswith("#/definitions/propertyValue")
        for reference in result.unresolved_refs
    )


def test_unsupported_version_rejected() -> None:
    with pytest.raises(SemanticValidationError) as exc:
        validate_semantic_payload("ak.wwise.core.object.get", version="2024")

    assert exc.value.error_code == SemanticErrorCode.UNSUPPORTED_WWISE_VERSION
    assert exc.value.details["version"] == "2024"


def test_schema_invalid_uri_rejected_with_typed_code() -> None:
    validator = SemanticSchemaValidator(manifest_loader=fake_manifest_loader())

    with pytest.raises(SemanticValidationError) as exc:
        validator.validate("ak.wwise.core.object.missing", {})

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["uri"] == "ak.wwise.core.object.missing"


def test_schema_required_fields_rejected_with_typed_code() -> None:
    validator = SemanticSchemaValidator(manifest_loader=fake_manifest_loader())

    with pytest.raises(SemanticValidationError) as exc:
        validator.validate("ak.wwise.core.object.delete", {})

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["missing_args"] == ["object"]


def test_schema_required_arg_family_is_conservative() -> None:
    validator = SemanticSchemaValidator(manifest_loader=fake_manifest_loader())

    result = validator.validate("ak.wwise.core.object.getPropertyInfo", {"classId": 1})
    assert result.required_families == (("object",), ("classId",))

    with pytest.raises(SemanticValidationError) as exc:
        validator.validate("ak.wwise.core.object.getPropertyInfo", {})

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["required_alternatives"] == [["object"], ["classId"]]


def test_schema_unknown_or_wrong_type_fields_rejected() -> None:
    validator = SemanticSchemaValidator(manifest_loader=fake_manifest_loader())

    with pytest.raises(SemanticValidationError) as unknown:
        validator.validate("ak.wwise.core.object.delete", {"object": "{id}", "extra": True})
    assert unknown.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert unknown.value.details["unknown_fields"] == ["extra"]

    with pytest.raises(SemanticValidationError) as wrong_type:
        validator.validate("ak.wwise.core.object.delete", {"object": 123})
    assert wrong_type.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert wrong_type.value.details["expected_type"] == "string"


def test_schema_top_level_pattern_properties_are_known_and_value_validated() -> None:
    validator = SemanticSchemaValidator(manifest_loader=fake_manifest_loader())

    result = validator.validate(
        "ak.test.patternProperties",
        {"name": "Root", "@Volume": -2.0},
    )

    assert result.validated_nodes >= 3
    with pytest.raises(SemanticValidationError) as wrong_type:
        validator.validate(
            "ak.test.patternProperties",
            {"name": "Root", "@Volume": "loud"},
        )
    assert wrong_type.value.details["actual_type"] == "str"
    with pytest.raises(SemanticValidationError) as unknown:
        validator.validate(
            "ak.test.patternProperties",
            {"name": "Root", "notAProperty": -2.0},
        )
    assert unknown.value.details["unknown_fields"] == ["notAProperty"]


def test_schema_top_level_invalid_pattern_fails_closed() -> None:
    validator = SemanticSchemaValidator(manifest_loader=fake_manifest_loader())

    with pytest.raises(SemanticValidationError, match="invalid packaged schema pattern"):
        validator.validate("ak.test.invalidPatternProperties", {"@Volume": -2.0})


def test_schema_oneof_requires_exactly_one_complete_branch() -> None:
    validator = SemanticSchemaValidator(manifest_loader=fake_manifest_loader())

    validator.validate("ak.soundengine.seekOnEvent", {"event": "Play", "gameObject": 1, "position": 100})

    with pytest.raises(SemanticValidationError) as incomplete:
        validator.validate("ak.soundengine.seekOnEvent", {"event": "Play"})
    assert incomplete.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert incomplete.value.details["matched_alternatives"] == []

    with pytest.raises(SemanticValidationError) as overlapping:
        validator.validate(
            "ak.soundengine.seekOnEvent",
            {"event": "Play", "gameObject": 1, "position": 100, "percent": 50.0},
        )
    assert overlapping.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert overlapping.value.details["required_policy"] == "exactly one"


def test_schema_oneof_validates_complete_branches_not_only_required_fields() -> None:
    validator = SemanticSchemaValidator(manifest_loader=fake_manifest_loader())

    validator.validate("ak.test.discriminatedOneOf", {"mode": "first"})

    with pytest.raises(SemanticValidationError) as invalid:
        validator.validate("ak.test.discriminatedOneOf", {"mode": "other"})

    assert invalid.value.details["required_policy"] == "exactly one"
    assert invalid.value.details["required_alternatives"] == [["mode"], ["mode"]]
    assert invalid.value.details["matched_alternatives"] == []
