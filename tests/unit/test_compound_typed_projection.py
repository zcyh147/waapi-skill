"""Compound child contracts retain independent schemas after projection."""
from copy import deepcopy

from wwise_waapi.typed_operations import compound_child_request_contract


def test_compound_child_schema_keeps_scalar_choices_annotations_and_output_isolation():
    first = compound_child_request_contract("object.create", "2025.1")
    expected = deepcopy(first.schema_roots["args"])
    properties = first.schema_roots["args"]["properties"]
    assert properties["on_name_conflict"]["enum"] == ["fail", "rename", "merge", "replace"]
    fields = properties["properties"]["items"]["properties"]
    assert fields["value"]["oneOf"] == [
        {"type": "string"}, {"type": "integer"}, {"type": "number"},
        {"type": "boolean"}, {"type": "null"},
    ]
    assert fields["name"]["live_query_accessor_mapping"] == {
        "source": "successful_live_query_in_this_conversation", "query": "@Foo",
        "mutation": "Foo", "transform": "remove_exactly_one_leading_at", "guessing": False,
    }
    properties["on_name_conflict"]["enum"].clear()
    fields["value"]["oneOf"].clear()
    fields["name"]["live_query_accessor_mapping"]["guessing"] = True
    second = compound_child_request_contract("object.create", "2025.1")
    assert second.schema_roots["args"] == expected
    assert second.schema_digest == first.schema_digest
