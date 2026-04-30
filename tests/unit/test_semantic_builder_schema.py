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


def test_unsupported_version_rejected() -> None:
    with pytest.raises(SemanticValidationError) as exc:
        validate_semantic_payload("ak.wwise.core.object.get", version="2023.1")

    assert exc.value.error_code == SemanticErrorCode.UNSUPPORTED_WWISE_VERSION
    assert exc.value.details["version"] == "2023.1"


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
    assert result.required_families == (("object", "classId"),)

    with pytest.raises(SemanticValidationError) as exc:
        validator.validate("ak.wwise.core.object.getPropertyInfo", {})

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["missing_arg_families"] == [["object", "classId"]]


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
