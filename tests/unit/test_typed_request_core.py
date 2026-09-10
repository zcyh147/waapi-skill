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
    typed_request_construction_for_values,
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


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_inverse_encoder_round_trips_scalar_branch_and_array_values(
    version: str,
) -> None:
    contract = request_contract(version, TYPED_REQUEST_TRACER_URI)
    args = {
        "time": 1200,
        "voicePipelineID": 17,
        "bussesPipelineID": [3, 5],
    }

    construction = typed_request_construction_for_values(
        contract,
        args=args,
        options={},
    )
    materialized = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=construction.facts,
    )

    assert materialized.args == args
    assert materialized.options == {}
    assert construction.disclosures == ()


def test_inverse_encoder_round_trips_nested_dynamic_containers_and_open_map() -> None:
    schema = {
        "argsSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "payload"],
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kind", "value"],
                        "properties": {
                            "kind": {"const": "id", "type": "string"},
                            "value": {
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "integer"},
                                ]
                            },
                        },
                    },
                },
                "payload": {
                    "type": "object",
                    "additionalProperties": {
                        "oneOf": [
                            {"type": "null"},
                            {"type": "boolean"},
                            {"type": "number"},
                            {"type": "string"},
                        ]
                    },
                },
            },
        },
        "optionsSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "return": {"type": "array", "items": {"type": "string"}}
            },
        },
    }
    contract = compile_typed_request_contract(
        version="2025.1",
        uri="ak.example.inverse-complex",
        schema=schema,
        graph=load_definition_graph("2025.1"),
    )
    args = {
        "rows": [{"kind": "id", "value": 42}],
        "payload": {"empty": None, "enabled": True, "gain": -1.5, "name": "x"},
    }
    options = {"return": []}

    construction = typed_request_construction_for_values(
        contract,
        args=args,
        options=options,
    )
    materialized = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=construction.facts,
    )

    assert materialized.args == args
    assert materialized.options == options
    assert construction.disclosures
    disclosed_handles = {item.child_handle for item in construction.disclosures}
    assert all(
        fact.value in disclosed_handles
        for fact in construction.facts
        if fact.value_type in {"object", "array"}
    )


def test_inverse_encoder_round_trips_open_map_overlay_inside_fixed_object() -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri="ak.example.inverse-overlay",
        schema={
            "argsSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["wa_args"],
                "properties": {
                    "wa_args": {
                        "type": "object",
                        "maxProperties": 4,
                        "maximumBytes": 1024,
                    }
                },
            },
            "optionsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
        graph=load_definition_graph("2025.1"),
    )

    construction = typed_request_construction_for_values(
        contract,
        args={"wa_args": {"count": 3, "enabled": True}},
        options={},
    )
    materialized = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=construction.facts,
    )

    assert materialized.args == {"wa_args": {"count": 3, "enabled": True}}


def test_inverse_encoder_fact_order_is_independent_of_mapping_insertion() -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri="ak.example.inverse-order",
        schema={
            "argsSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["mode", "payload"],
                "properties": {
                    "mode": {"type": "string"},
                    "payload": {
                        "type": "object",
                        "additionalProperties": {
                            "oneOf": [
                                {"type": "integer"},
                                {"type": "string"},
                            ]
                        },
                    },
                },
            },
            "optionsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
        graph=load_definition_graph("2025.1"),
    )
    forward = typed_request_construction_for_values(
        contract,
        args={"mode": "replace", "payload": {"z": 1, "a": "x"}},
        options={},
    )
    reversed_order = typed_request_construction_for_values(
        contract,
        args={"payload": {"a": "x", "z": 1}, "mode": "replace"},
        options={},
    )

    assert reversed_order == forward


def test_inverse_encoder_does_not_use_map_overlay_to_bypass_fixed_member_schema() -> None:
    contract = compile_typed_request_contract(
        version="2025.1",
        uri="ak.example.inverse-fixed-overlay",
        schema={
            "argsSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["payload"],
                "properties": {
                    "payload": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {"known": {"type": "string"}},
                    }
                },
            },
            "optionsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
        graph=load_definition_graph("2025.1"),
    )

    with pytest.raises(TypedRequestError):
        typed_request_construction_for_values(
            contract,
            args={"payload": {"known": 7}},
            options={},
        )


def test_inverse_encoder_rejects_unknown_and_ambiguous_values() -> None:
    contract = request_contract("2025.1", TYPED_REQUEST_TRACER_URI)
    with pytest.raises(TypedRequestError, match="outside the disclosed contract"):
        typed_request_construction_for_values(
            contract,
            args={"time": 1, "voicePipelineID": 2, "invented": True},
            options={},
        )

    ambiguous = compile_typed_request_contract(
        version="2025.1",
        uri="ak.example.inverse-ambiguous",
        schema={
            "argsSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["value"],
                "properties": {
                    "value": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "string", "minLength": 1},
                        ]
                    }
                },
            },
            "optionsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
        graph=load_definition_graph("2025.1"),
    )
    with pytest.raises(TypedRequestError):
        typed_request_construction_for_values(
            ambiguous,
            args={"value": "x"},
            options={},
        )
