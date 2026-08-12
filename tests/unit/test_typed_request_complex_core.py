from __future__ import annotations

import pytest

from wwise_waapi.schema_inventory import load_definition_graph
from wwise_waapi.typed_requests import (
    MAX_TYPED_REQUEST_BYTES,
    MAX_TYPED_SCHEMA_DEPTH,
    MAX_TYPED_REQUEST_FACTS,
    MAX_TYPED_STRING_BYTES,
    TypedRequestError,
    TypedRequestFact,
    compile_typed_request_contract,
    dynamic_branch_choices,
    dynamic_array_item_handle,
    dynamic_map_entry_handle,
    materialize_typed_request,
)


def _compile(args_schema: dict[str, object]):
    return compile_typed_request_contract(
        version="2025.1",
        uri="ak.example.complex",
        schema={
            "argsSchema": args_schema,
            "optionsSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
        graph=load_definition_graph("2025.1"),
    )


def test_scalar_one_of_requires_explicit_version_bound_branch() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["identity"],
            "properties": {
                "identity": {
                    "oneOf": [{"type": "integer"}, {"type": "string"}]
                }
            },
        }
    )
    branch = next(field for field in contract.fields if field.name == "identity")
    integer = next(
        field
        for field in contract.fields
        if field.parent_handle == branch.handle and field.name == "integer"
    )

    request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact("choose", branch.handle, "branch", integer.handle),
            TypedRequestFact("set", integer.handle, "integer", "42"),
        ),
    )
    assert request.args == {"identity": 42}

    with pytest.raises(TypedRequestError, match="branch"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(TypedRequestFact("set", integer.handle, "integer", "42"),),
        )


def test_nested_any_of_object_branch_and_nullable_value() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["choice"],
            "properties": {
                "choice": {
                    "anyOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name"],
                            "properties": {"name": {"type": "string"}},
                        },
                        {"type": "null"},
                    ]
                }
            },
        }
    )
    branch = next(field for field in contract.fields if field.name == "choice")
    null_choice = next(
        field
        for field in contract.fields
        if field.parent_handle == branch.handle and field.name == "null"
    )
    request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact("choose", branch.handle, "branch", null_choice.handle),
            TypedRequestFact("set", null_choice.handle, "null", "null"),
        ),
    )
    assert request.args == {"choice": None}


def test_patterned_and_open_maps_support_atomic_put_correct_remove() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["patterned", "open"],
            "properties": {
                "patterned": {
                    "type": "object",
                    "additionalProperties": False,
                    "patternProperties": {"^x-[a-z]+$": {"type": "integer"}},
                },
                "open": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {},
                },
            },
        }
    )
    handles = {field.name: field.handle for field in contract.fields}
    request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact("map-put", handles["patterned"], "integer", "1", key="x-count"),
            TypedRequestFact("map-correct", handles["patterned"], "integer", "2", key="x-count"),
            TypedRequestFact("map-put", handles["open"], "string", "42", key="identity"),
            TypedRequestFact("map-put", handles["open"], "integer", "42", key="count"),
            TypedRequestFact("map-put", handles["open"], "null", "null", key="removed"),
            TypedRequestFact("map-remove", handles["open"], "null", "null", key="removed"),
        ),
    )
    assert request.args == {
        "patterned": {"x-count": 2},
        "open": {"identity": "42", "count": 42},
    }

    with pytest.raises(TypedRequestError, match="key"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(
                TypedRequestFact("map-put", handles["patterned"], "integer", "1", key="bad"),
            ),
        )


def test_empty_open_map_is_distinct_from_omission() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "open": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {},
                }
            },
        }
    )
    handle = next(field.handle for field in contract.fields if field.name == "open")
    request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(TypedRequestFact("present", handle, "null", "null"),),
    )
    assert request.args == {"open": {}}


def test_open_map_nested_object_and_array_are_built_one_fact_at_a_time() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["open"],
            "properties": {
                "open": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {},
                }
            },
        }
    )
    root = next(field.handle for field in contract.fields if field.name == "open")
    child = dynamic_map_entry_handle(
        contract, map_handle=root, key="child", shape="object"
    )
    items = dynamic_map_entry_handle(
        contract, map_handle=child, key="items", shape="array"
    )

    request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact("map-put", root, "object", child, key="child"),
            TypedRequestFact("map-put", child, "string", "sentinel", key="name"),
            TypedRequestFact("map-put", child, "array", items, key="items"),
            TypedRequestFact("append", items, "integer", "42"),
            TypedRequestFact("append", items, "null", "null"),
        ),
    )
    assert request.args == {
        "open": {"child": {"name": "sentinel", "items": [42, None]}}
    }


def test_dynamic_container_handles_bind_parent_key_shape_and_version() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "open": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {},
                }
            },
        }
    )
    root = next(field.handle for field in contract.fields if field.name == "open")
    child = dynamic_map_entry_handle(
        contract, map_handle=root, key="child", shape="object"
    )
    wrong_shape = dynamic_map_entry_handle(
        contract, map_handle=root, key="child", shape="array"
    )

    with pytest.raises(TypedRequestError, match="unknown or stale"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(
                TypedRequestFact(
                    "map-put", root, "object", wrong_shape, key="child"
                ),
            ),
        )
    assert child != wrong_shape


def test_open_map_depth_and_total_request_bytes_are_bounded() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["open"],
            "properties": {
                "open": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {},
                }
            },
        }
    )
    root = next(field.handle for field in contract.fields if field.name == "open")
    facts: list[TypedRequestFact] = []
    parent = root
    for index in range(MAX_TYPED_SCHEMA_DEPTH + 1):
        child = dynamic_map_entry_handle(
            contract, map_handle=parent, key=f"level-{index}", shape="object"
        )
        facts.append(TypedRequestFact("map-put", parent, "object", child, key=f"level-{index}"))
        parent = child
    with pytest.raises(TypedRequestError, match="depth"):
        materialize_typed_request(
            contract, schema_digest=contract.schema_digest, facts=facts
        )

    large_facts = tuple(
        TypedRequestFact(
            "map-put",
            root,
            "string",
            "x" * (MAX_TYPED_REQUEST_BYTES // 8),
            key=f"value-{index}",
        )
        for index in range(9)
    )
    with pytest.raises(TypedRequestError, match="byte limit"):
        materialize_typed_request(
            contract, schema_digest=contract.schema_digest, facts=large_facts
        )


def test_nested_dynamic_map_enforces_its_schema_byte_limit() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["open"],
            "properties": {
                "open": {
                    "type": "object",
                    "additionalProperties": False,
                    "patternProperties": {
                        "^child$": {
                            "type": "object",
                            "additionalProperties": True,
                            "maximumBytes": 9,
                        }
                    },
                }
            },
        }
    )
    root = next(field for field in contract.fields if field.shape == "map")
    child = dynamic_map_entry_handle(
        contract, map_handle=root.handle, key="child", shape="object"
    )

    with pytest.raises(TypedRequestError, match="9-byte limit"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(
                TypedRequestFact(
                    "map-put", root.handle, "object", child, key="child"
                ),
                TypedRequestFact("map-put", child, "string", "1", key="a"),
                TypedRequestFact("map-put", child, "string", "2", key="b"),
            ),
        )


def test_dynamic_child_removal_and_scalar_correction_do_not_resurrect_it() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["open"],
            "properties": {
                "open": {"type": "object", "additionalProperties": True, "properties": {}}
            },
        }
    )
    root = next(field.handle for field in contract.fields if field.name == "open")
    child = dynamic_map_entry_handle(contract, map_handle=root, key="child", shape="object")
    prefix = (
        TypedRequestFact("map-put", root, "object", child, key="child"),
        TypedRequestFact("map-put", child, "integer", "1", key="x"),
    )
    removed = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(*prefix, TypedRequestFact("map-remove", root, "null", "null", key="child")),
    )
    corrected = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(*prefix, TypedRequestFact("map-correct", root, "string", "done", key="child")),
    )
    assert removed.args == {"open": {}}
    assert corrected.args == {"open": {"child": "done"}}


def test_fixed_and_patterned_object_members_materialize_together() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["mixed"],
            "properties": {
                "mixed": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["fixed"],
                    "properties": {"fixed": {"type": "string"}},
                    "patternProperties": {"x-": {"type": "integer"}},
                }
            },
        }
    )
    fixed = next(field for field in contract.fields if field.name == "fixed")
    patterned = next(field for field in contract.fields if field.overlay)
    request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact("set", fixed.handle, "string", "value"),
            TypedRequestFact("map-put", patterned.handle, "integer", "2", key="prefix-x-suffix"),
        ),
    )
    assert request.args == {"mixed": {"fixed": "value", "prefix-x-suffix": 2}}


def test_schema_node_ceiling_counts_scalar_fields() -> None:
    from wwise_waapi.typed_requests import MAX_TYPED_SCHEMA_NODES

    properties = {
        f"field-{index}": {"type": "string"}
        for index in range(MAX_TYPED_SCHEMA_NODES + 1)
    }
    with pytest.raises(TypedRequestError, match="structure limits"):
        _compile(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": properties,
            }
        )


def test_patterned_map_accepts_array_container_when_its_schema_does() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["patterned"],
            "properties": {
                "patterned": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                    "patternProperties": {"^list-": {"type": "array", "items": {"type": "string"}}},
                }
            },
        }
    )
    root = next(field for field in contract.fields if field.shape == "map")
    child = dynamic_map_entry_handle(contract, map_handle=root.handle, key="list-items", shape="array")
    request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact("map-put", root.handle, "array", child, key="list-items"),
            TypedRequestFact("append", child, "string", "one"),
        ),
    )
    assert request.args == {"patterned": {"list-items": ["one"]}}


def test_branch_array_and_array_object_items_use_explicit_handles() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["choice", "rows"],
            "properties": {
                "choice": {
                    "oneOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "null"},
                    ]
                },
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name"],
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
        }
    )
    branch = next(field for field in contract.fields if field.name == "choice")
    array_choice = next(
        field
        for field in contract.fields
        if field.parent_handle == branch.handle and field.shape == "array"
    )
    rows = next(field for field in contract.fields if field.name == "rows")
    row = dynamic_array_item_handle(
        contract, array_handle=rows.handle, index=0, shape="object"
    )
    request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact("choose", branch.handle, "branch", array_choice.handle),
            TypedRequestFact("append", array_choice.handle, "string", "selected"),
            TypedRequestFact("append", rows.handle, "object", row),
            TypedRequestFact("map-put", row, "string", "sentinel", key="name"),
        ),
    )
    assert request.args == {
        "choice": ["selected"],
        "rows": [{"name": "sentinel"}],
    }


def test_required_dynamic_object_member_is_enforced() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["rows"],
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name"],
                        "properties": {"name": {"type": "string"}},
                    },
                }
            },
        }
    )
    rows = next(field for field in contract.fields if field.name == "rows")
    row = dynamic_array_item_handle(
        contract, array_handle=rows.handle, index=0, shape="object"
    )
    with pytest.raises(TypedRequestError, match="required keys"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(TypedRequestFact("append", rows.handle, "object", row),),
        )


def test_multiple_matching_patterns_are_conjunctive() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["values"],
            "properties": {
                "values": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                    "patternProperties": {
                        "x": {"type": "integer", "minimum": 0},
                        "^x$": {"type": "integer", "maximum": 10},
                    },
                }
            },
        }
    )
    field = next(item for item in contract.fields if item.shape == "map")
    with pytest.raises(TypedRequestError, match="matching reflected"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(TypedRequestFact("map-put", field.handle, "integer", "20", key="x"),),
        )


def test_map_overlay_cannot_override_fixed_property() -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["mixed"],
            "properties": {
                "mixed": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {"known": {"type": "string"}},
                }
            },
        }
    )
    overlay = next(field for field in contract.fields if field.overlay)
    with pytest.raises(TypedRequestError, match="fixed reflected"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(TypedRequestFact("map-put", overlay.handle, "integer", "7", key="known"),),
        )


def test_nested_schema_node_ceiling_and_dynamic_branch_refs_are_enforced() -> None:
    from wwise_waapi.typed_requests import MAX_TYPED_SCHEMA_NODES

    with pytest.raises(TypedRequestError, match="structure limits"):
        _compile(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "rows": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                f"f-{index}": {"type": "string"}
                                for index in range(MAX_TYPED_SCHEMA_NODES + 1)
                            },
                        },
                    }
                },
            }
        )

    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["rows"],
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["value"],
                        "properties": {
                            "value": {
                                "oneOf": [{"type": "integer"}, {"type": "string"}]
                            }
                        },
                    },
                }
            },
        }
    )
    rows = next(field for field in contract.fields if field.name == "rows")
    row = dynamic_array_item_handle(
        contract, array_handle=rows.handle, index=0, shape="object"
    )
    choice = dynamic_branch_choices(
        contract,
        object_handle=row,
        key="value",
        value_schema={"oneOf": [{"type": "integer"}, {"type": "string"}]},
    )[0][0]
    request = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact("append", rows.handle, "object", row),
            TypedRequestFact("choose-dynamic", row, "choice", choice, key="value"),
            TypedRequestFact("map-put", row, "integer", "7", key="value"),
        ),
    )
    assert request.args == {"rows": [{"value": 7}]}


@pytest.mark.parametrize(
    "case",
    ("duplicate_put", "correct_missing", "remove_missing", "oversized_key", "too_many_facts"),
)
def test_open_map_invalid_corrections_and_bounds_are_atomic(case: str) -> None:
    contract = _compile(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["open"],
            "properties": {
                "open": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {},
                }
            },
        }
    )
    handle = next(field.handle for field in contract.fields if field.name == "open")
    put = TypedRequestFact("map-put", handle, "integer", "1", key="count")
    facts = [put]
    if case == "duplicate_put":
        facts.append(put)
    elif case == "correct_missing":
        facts = [TypedRequestFact("map-correct", handle, "integer", "1", key="missing")]
    elif case == "remove_missing":
        facts = [TypedRequestFact("map-remove", handle, "null", "null", key="missing")]
    elif case == "oversized_key":
        facts = [
            TypedRequestFact("map-put", handle, "integer", "1", key="x" * (MAX_TYPED_STRING_BYTES + 1))
        ]
    elif case == "too_many_facts":
        facts = [
            TypedRequestFact("map-put", handle, "integer", str(index), key=f"k{index}")
            for index in range(MAX_TYPED_REQUEST_FACTS + 1)
        ]

    with pytest.raises(TypedRequestError):
        materialize_typed_request(
            contract, schema_digest=contract.schema_digest, facts=facts
        )

    valid = materialize_typed_request(
        contract, schema_digest=contract.schema_digest, facts=(put,)
    )
    assert valid.args == {"open": {"count": 1}}
