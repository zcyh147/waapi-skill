from __future__ import annotations

from dataclasses import replace

import pytest

from wwise_waapi.schema_inventory import load_definition_graph
from wwise_waapi.typed_requests import (
    MAX_TYPED_ARRAY_ITEMS,
    TYPED_REQUEST_TRACER_URI,
    TypedRequestError,
    TypedRequestFact,
    compile_typed_request_contract,
    materialize_typed_request,
    request_contract,
)
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_tracer_contract_is_schema_derived_for_every_supported_version(
    version: str,
) -> None:
    contract = request_contract(version, TYPED_REQUEST_TRACER_URI)

    assert contract.version == version
    assert {field.name for field in contract.fields if field.parent_handle is None} == {
        "time",
        "voicePipelineID",
        "bussesPipelineID",
    }
    assert len({field.handle for field in contract.fields}) == len(contract.fields)
    assert all(field.handle.startswith("trh1-") for field in contract.fields)


def test_nested_objects_and_scalar_arrays_materialize_from_gateway_handles() -> None:
    schema = {
        "argsSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["label", "nested"],
            "properties": {
                "label": {"type": "string"},
                "flags": {
                    "type": "array",
                    "items": {"type": "boolean"},
                    "maxItems": 4,
                },
                "nested": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["count"],
                    "properties": {
                        "count": {"type": "integer", "minimum": 0}
                    },
                },
            },
        },
        "optionsSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
    }
    contract = compile_typed_request_contract(
        version="2025.1",
        uri="ak.example.synthetic",
        schema=schema,
        graph=load_definition_graph("2025.1"),
    )
    handles = {field.name: field.handle for field in contract.fields}

    request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact("set", handles["label"], "string", "sentinel"),
            TypedRequestFact("append", handles["flags"], "boolean", "true"),
            TypedRequestFact("append", handles["flags"], "boolean", "false"),
            TypedRequestFact("set", handles["count"], "integer", "3"),
        ),
    )

    assert request.args == {
        "label": "sentinel",
        "flags": [True, False],
        "nested": {"count": 3},
    }
    assert request.options == {}


def test_container_handles_preserve_empty_presence_and_conditional_requirements() -> None:
    schema = {
        "argsSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["requiredEmpty"],
            "properties": {
                "requiredEmpty": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                },
                "optionalItems": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "optionalObject": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["child"],
                    "properties": {"child": {"type": "string"}},
                },
            },
        },
        "optionsSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
    }
    contract = compile_typed_request_contract(
        version="2025.1",
        uri="ak.example.containers",
        schema=schema,
        graph=load_definition_graph("2025.1"),
    )
    handles = {field.name: field.handle for field in contract.fields}

    request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact(
                "present", handles["optionalItems"], "null", "null"
            ),
        ),
    )
    assert request.args == {"requiredEmpty": {}, "optionalItems": []}

    with pytest.raises(TypedRequestError, match="child.*missing"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(
                TypedRequestFact(
                    "present", handles["optionalObject"], "null", "null"
                ),
            ),
        )


def test_optional_object_leaf_materializes_parent_and_enforces_required_sibling() -> None:
    schema = {
        "argsSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "branch": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["requiredLeaf"],
                    "properties": {
                        "requiredLeaf": {"type": "string"},
                        "optionalLeaf": {"type": "string"},
                    },
                }
            },
        },
        "optionsSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
    }
    contract = compile_typed_request_contract(
        version="2025.1",
        uri="ak.example.conditional-object",
        schema=schema,
        graph=load_definition_graph("2025.1"),
    )
    handles = {field.name: field.handle for field in contract.fields}

    with pytest.raises(TypedRequestError, match="requiredLeaf.*missing"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(
                TypedRequestFact(
                    "set", handles["optionalLeaf"], "string", "sentinel"
                ),
            ),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "wrong_digest",
        "foreign_handle",
        "wrong_action",
        "wrong_type",
        "duplicate",
        "missing_required",
        "oversized_array",
    ),
)
def test_invalid_fact_sets_fail_atomically_without_a_partial_request(
    mutation: str,
) -> None:
    contract = request_contract("2025.1", TYPED_REQUEST_TRACER_URI)
    handles = {field.name: field.handle for field in contract.fields}
    facts = [
        *_tracer_fact(
            contract, field_name="time", value_type="integer", value="1200"
        ),
        TypedRequestFact("set", handles["voicePipelineID"], "integer", "17"),
    ]
    digest = contract.schema_digest
    if mutation == "wrong_digest":
        digest = "0" * 64
    elif mutation == "foreign_handle":
        facts.append(TypedRequestFact("set", "trh1-foreign", "integer", "1"))
    elif mutation == "wrong_action":
        facts.append(TypedRequestFact("append", handles["voicePipelineID"], "integer", "1"))
    elif mutation == "wrong_type":
        facts[1] = TypedRequestFact(
            "set", handles["voicePipelineID"], "string", "17"
        )
    elif mutation == "duplicate":
        facts.extend(
            _tracer_fact(
                contract, field_name="time", value_type="integer", value="1"
            )
        )
    elif mutation == "missing_required":
        facts.pop()
    elif mutation == "oversized_array":
        facts.extend(
            TypedRequestFact(
                "append", handles["bussesPipelineID"], "integer", str(index)
            )
            for index in range(MAX_TYPED_ARRAY_ITEMS + 1)
        )

    with pytest.raises(TypedRequestError):
        materialize_typed_request(contract, schema_digest=digest, facts=facts)

    valid = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            *_tracer_fact(
                contract, field_name="time", value_type="integer", value="1200"
            ),
            TypedRequestFact("set", handles["voicePipelineID"], "integer", "17"),
        ),
    )
    assert valid.args == {"time": 1200, "voicePipelineID": 17}


def test_handles_and_digest_are_version_bound() -> None:
    current = request_contract("2025.1", TYPED_REQUEST_TRACER_URI)
    prior = request_contract("2024.1", TYPED_REQUEST_TRACER_URI)
    current_handles = {field.name: field.handle for field in current.fields}
    prior_handles = {field.name: field.handle for field in prior.fields}

    assert current.schema_digest != prior.schema_digest
    assert current_handles != prior_handles
    with pytest.raises(TypedRequestError, match="unknown or stale"):
        materialize_typed_request(
            current,
            schema_digest=current.schema_digest,
            facts=(
                TypedRequestFact("set", prior_handles["time"], "integer", "1"),
                TypedRequestFact(
                    "set", current_handles["voicePipelineID"], "integer", "1"
                ),
            ),
        )


def _tracer_fact(
    contract,
    *,
    field_name: str,
    value_type: str,
    value: str,
) -> tuple[TypedRequestFact, ...]:
    field = next(
        item
        for item in contract.fields
        if item.name == field_name and item.parent_handle is None
    )
    if field.shape != "branch":
        return (TypedRequestFact("set", field.handle, value_type, value),)
    choice = next(
        item
        for item in contract.fields
        if item.parent_handle == field.handle and item.name == value_type
    )
    return (
        TypedRequestFact("choose", field.handle, "branch", choice.handle),
        TypedRequestFact("set", choice.handle, value_type, value),
    )


def test_materialization_rejects_contract_tampering() -> None:
    contract = request_contract("2025.1", TYPED_REQUEST_TRACER_URI)
    tampered = replace(contract, schema_digest="f" * 64)
    handles = {field.name: field.handle for field in contract.fields}

    with pytest.raises(TypedRequestError, match="corrupt or stale"):
        materialize_typed_request(
            tampered,
            schema_digest=tampered.schema_digest,
            facts=(
                TypedRequestFact("set", handles["time"], "integer", "1"),
                TypedRequestFact(
                    "set", handles["voicePipelineID"], "integer", "1"
                ),
            ),
        )
