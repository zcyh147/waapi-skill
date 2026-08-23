from __future__ import annotations

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    parse_operation_request,
)
from wwise_waapi.typed_operations import (  # pyright: ignore[reportMissingImports]
    MAX_INLINE_OPERATION_VALUE_BYTES,
    TypedOperationInputError,
    inline_operation_cli_argument_variants,
    inline_operation_contract,
    materialize_inline_operation_request,
)


VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
OBJECT = ("id-string", "{11111111-1111-1111-1111-111111111111}")
TARGET = ("path", r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus")


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize(
    ("operation", "values", "expected"),
    [
        ("object.setName", {"object": OBJECT, "text": "Renamed"}, {"value": "Renamed"}),
        ("object.setNotes", {"object": OBJECT, "text": ""}, {"value": ""}),
        (
            "object.setProperty",
            {
                "object": OBJECT,
                "property": "Volume",
                "value_type": "number",
                "value": "-3.0",
                "platform": "Windows",
            },
            {"property": "Volume", "value": -3.0, "platform": "Windows"},
        ),
        (
            "object.setReference",
            {"object": OBJECT, "reference": "OutputBus", "target": TARGET},
            {
                "reference": "OutputBus",
                "target": {"kind": "path", "value": TARGET[1]},
            },
        ),
        (
            "object.setReference",
            {"object": OBJECT, "reference": "OutputBus", "clear": True},
            {"reference": "OutputBus", "target": None},
        ),
    ],
)
def test_inline_operations_materialize_exact_registry_requests(
    version: str,
    operation: str,
    values: dict[str, object],
    expected: dict[str, object],
) -> None:
    request = materialize_inline_operation_request(operation, version, values)

    assert request == {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": {
            "object": {"kind": "id", "value": OBJECT[1]},
            **expected,
        },
    }
    assert parse_operation_request(request, expected_version=version).operation == operation


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("linked", ("true", "false"))
def test_set_linked_keeps_explicit_boolean_distinct(version: str, linked: str) -> None:
    request = materialize_inline_operation_request(
        "object.setLinked",
        version,
        {
            "object": OBJECT,
            "property": "Volume",
            "platform": "Windows",
            "linked": linked,
        },
    )

    assert request["arguments"]["linked"] is (linked == "true")
    parse_operation_request(request, expected_version=version)


@pytest.mark.parametrize("value_type,value", [("string", "x"), ("integer", "2"), ("number", "2.5"), ("boolean", "false")])
def test_set_property_accepts_only_typed_json_scalars(value_type: str, value: str) -> None:
    request = materialize_inline_operation_request(
        "object.setProperty",
        "2025.1",
        {
            "object": OBJECT,
            "property": "Volume",
            "value_type": value_type,
            "value": value,
        },
    )
    parse_operation_request(request, expected_version="2025.1")


def test_reference_clear_and_target_are_mutually_exclusive() -> None:
    with pytest.raises(TypedOperationInputError, match="exactly one"):
        materialize_inline_operation_request(
            "object.setReference",
            "2025.1",
            {
                "object": OBJECT,
                "reference": "OutputBus",
                "target": TARGET,
                "clear": True,
            },
        )


def test_reference_cli_variants_preserve_exact_groups_in_any_parser_order() -> None:
    request = materialize_inline_operation_request(
        "object.setReference",
        "2022.1",
        {"object": OBJECT, "reference": "OutputBus", "target": TARGET},
    )

    variants = inline_operation_cli_argument_variants(request)

    assert len(variants) == 6
    assert variants[0][4:9] == (
        "--object",
        *OBJECT,
        "--reference",
        "OutputBus",
    )
    assert (
        *variants[0][:4],
        "--target",
        *TARGET,
        "--object",
        *OBJECT,
        "--reference",
        "OutputBus",
    ) in variants


def test_inline_contract_discloses_one_operation_specific_continuation() -> None:
    contract = inline_operation_contract("object.setReference", "2025.1")

    assert contract["operation"] == "object.setReference"
    assert contract["input_shape"] == "inline"
    assert contract["continuation"]["subcommand"] == "typed-operation"
    assert contract["continuation"]["target_choice"] == ["--target SELECTOR", "--clear"]
    assert contract["continuation"]["selector_argv"] == {
        "object_id_string": ["--object", "id-string", "<guid>"],
        "target_id_string": ["--target", "id-string", "<guid>"],
        "one_array_element_per_argv": True,
        "joined_kind_and_value_string": "invalid",
    }
    assert "request-json" not in str(contract).lower()


@pytest.mark.parametrize(
    "selector",
    [
        ("id-string", "{11111111-1111-1111-1111-111111111111}"),
        ("id-integer", "42"),
        ("path", r"\Actor-Mixer Hierarchy\Default Work Unit\Sound"),
        ("exact-type-name", "Sound", "Sound"),
        ("direct-child", "Action", "path", r"\Events\Default Work Unit\Event"),
        (
            "scoped-name",
            "Sound",
            "Sound",
            "id-string",
            "{11111111-1111-1111-1111-111111111111}",
        ),
    ],
)
def test_inline_operation_accepts_all_five_closed_selector_kinds(
    selector: tuple[str, ...],
) -> None:
    request = materialize_inline_operation_request(
        "object.setNotes",
        "2025.1",
        {"object": selector, "text": "ok"},
    )
    parse_operation_request(request, expected_version="2025.1")


def test_nested_parent_selector_is_rejected_before_canonical_materialization() -> None:
    with pytest.raises(TypedOperationInputError, match="parent selector must be"):
        materialize_inline_operation_request(
            "object.setNotes",
            "2025.1",
            {
                "object": (
                    "scoped-name",
                    "Sound",
                    "Child",
                    "exact-type-name",
                    "WorkUnit",
                    "Default Work Unit",
                ),
                "text": "ok",
            },
        )


def test_inline_text_limit_rejects_oversize_before_preview() -> None:
    with pytest.raises(TypedOperationInputError, match="UTF-8 limit"):
        materialize_inline_operation_request(
            "object.setNotes",
            "2025.1",
            {"object": OBJECT, "text": "x" * (MAX_INLINE_OPERATION_VALUE_BYTES + 1)},
        )


@pytest.mark.parametrize(
    ("operation", "extra"),
    [
        (
            "object.setProperty",
            {"property": "Volume", "value_type": "string", "value": "x" * (MAX_INLINE_OPERATION_VALUE_BYTES + 1)},
        ),
        (
            "object.setReference",
            {"reference": "OutputBus", "target": TARGET, "platform": "x" * (MAX_INLINE_OPERATION_VALUE_BYTES + 1)},
        ),
    ],
)
def test_all_disclosed_inline_string_values_share_the_utf8_limit(
    operation: str,
    extra: dict[str, object],
) -> None:
    with pytest.raises(TypedOperationInputError, match="UTF-8 limit"):
        materialize_inline_operation_request(
            operation,
            "2025.1",
            {"object": OBJECT, **extra},
        )


def test_selector_tokens_share_the_disclosed_utf8_limit() -> None:
    with pytest.raises(TypedOperationInputError, match="UTF-8 limit"):
        materialize_inline_operation_request(
            "object.setNotes",
            "2025.1",
            {"object": ("path", "\\" + "x" * MAX_INLINE_OPERATION_VALUE_BYTES), "text": ""},
        )


def test_metadata_backed_contract_discloses_token_source_and_scalar_types() -> None:
    contract = inline_operation_contract("object.setProperty", "2025.1")

    assert contract["metadata_dependency"] == {
        "token": "property",
        "source": "successful live metadata discover for this object/class scope",
        "never_infer": True,
        "preview_revalidates": True,
        "accepted_value_types": ["string", "integer", "number", "boolean"],
    }
    assert contract["bounds"]["value_utf8_bytes"] == MAX_INLINE_OPERATION_VALUE_BYTES
