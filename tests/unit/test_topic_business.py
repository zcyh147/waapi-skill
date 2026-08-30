from __future__ import annotations

import json

import pytest

from wwise_waapi.capabilities import CapabilityCatalog
from wwise_waapi.execution_contracts import AUTHORING_UI_EXECUTION_PROFILE
from wwise_waapi.topic_business import (
    TopicBusinessError,
    TopicBusinessEntryFact,
    TopicBusinessEntryEmptyFact,
    TopicBusinessEntryObjectFact,
    TopicBusinessEntryRowFact,
    TopicBusinessFact,
    TopicBusinessEmptyFact,
    TopicBusinessEmptyRowFact,
    TopicBusinessRowFact,
    materialize_topic_business_inputs,
    topic_business_contract,
)
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


PROJECT_GUID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"


def test_all_154_topic_lanes_compile_one_handle_free_business_contract() -> None:
    lane_count = 0

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for capability in CapabilityCatalog().entries_for_profile(
            version,
            profile=AUTHORING_UI_EXECUTION_PROFILE,
        ):
            if capability.item_type != "topic":
                continue
            contract = topic_business_contract(version, capability.uri)
            payload = contract.as_dict()
            encoded = json.dumps(payload, sort_keys=True)

            assert payload["version"] == version
            assert payload["topic"] == capability.uri
            assert len(contract.option_fields) == len(
                {field.token for field in contract.option_fields}
            )
            assert len(contract.match_fields) == len(
                {field.token for field in contract.match_fields}
            )
            assert "trh1-" not in encoded
            assert "field_handle" not in encoded
            assert "schema_digest" not in encoded
            assert "wire_type" not in encoded
            assert "json_path" not in encoded
            assert contract.transitional_boundaries == ()
            assert all(row.fields for row in contract.row_fields)
            lane_count += 1

    assert lane_count == 154


def test_object_created_business_values_compile_exact_options_and_match() -> None:
    materialized = materialize_topic_business_inputs(
        version="2022.1",
        topic="ak.wwise.core.object.created",
        option_facts=(
            TopicBusinessFact("platform", PROJECT_GUID),
            TopicBusinessFact("include", "id"),
            TopicBusinessFact("include", "name"),
        ),
        match_facts=(
            TopicBusinessFact("object-name", "Footstep_Run"),
            TopicBusinessFact("object-type", "Sound"),
        ),
    )

    assert materialized.options == {
        "platform": PROJECT_GUID,
        "return": ["id", "name"],
    }
    assert materialized.match == {
        "object": {"name": "Footstep_Run", "type": "Sound"}
    }


def test_property_changed_business_value_selects_branch_from_value() -> None:
    materialized = materialize_topic_business_inputs(
        version="2022.1",
        topic="ak.wwise.core.object.propertyChanged",
        option_facts=(
            TopicBusinessFact("object", PROJECT_GUID),
            TopicBusinessFact("property", "Volume"),
        ),
        match_facts=(
            TopicBusinessFact("new", "-4"),
            TopicBusinessFact("object-name", "Weather_Rain"),
        ),
    )

    assert materialized.options == {
        "object": PROJECT_GUID,
        "property": "Volume",
    }
    assert materialized.match == {
        "new": -4,
        "object": {"name": "Weather_Rain"},
    }


def test_business_topic_rejects_unknown_or_ambiguous_values_without_native_repair() -> None:
    with pytest.raises(TopicBusinessError, match="Unknown event match field"):
        materialize_topic_business_inputs(
            version="2022.1",
            topic="ak.wwise.core.object.created",
            option_facts=(),
            match_facts=(TopicBusinessFact("native-json-pointer", "x"),),
        )


def test_hostile_business_scalar_remains_data_and_never_becomes_native_syntax() -> None:
    hostile = '$(touch /tmp/not-run) `whoami` "quoted" ü\nnext'

    materialized = materialize_topic_business_inputs(
        version="2025.1",
        topic="ak.wwise.core.object.created",
        option_facts=(),
        match_facts=(TopicBusinessFact("object-name", hostile, kind="text"),),
    )

    assert materialized.match == {"object": {"name": hostile}}

    with pytest.raises(TopicBusinessError, match="does not accept"):
        materialize_topic_business_inputs(
            version="2022.1",
            topic="ak.wwise.core.object.created",
            option_facts=(),
            match_facts=(TopicBusinessFact("object-is-playable", "not-a-toggle"),),
        )


def test_complex_event_collections_have_no_legacy_boundary_after_business_parity() -> None:
    contract = topic_business_contract(
        "2022.1",
        "ak.wwise.core.audio.imported",
    )

    assert contract.match_fields == ()
    assert {row.token for row in contract.row_fields} >= {"objects"}
    assert contract.transitional_boundaries == ()


def test_audio_imported_business_rows_compile_exact_object_array_match() -> None:
    contract = topic_business_contract(
        "2022.1",
        "ak.wwise.core.audio.imported",
    )
    objects = next(row for row in contract.row_fields if row.token == "objects")

    assert objects.index_depth == 1
    assert {field.token for field in objects.fields} >= {
        "id",
        "name",
        "type",
        "owner-name",
    }

    materialized = materialize_topic_business_inputs(
        version="2022.1",
        topic="ak.wwise.core.audio.imported",
        option_facts=(),
        match_facts=(),
        row_facts=(
            TopicBusinessRowFact("objects", (0,), "name", "Footstep_Run"),
            TopicBusinessRowFact("objects", (0,), "type", "Sound"),
        ),
    )

    assert materialized.match == {
        "objects": [{"name": "Footstep_Run", "type": "Sound"}]
    }


def test_exact_accessor_entries_compile_scalar_object_and_object_list_values() -> None:
    materialized = materialize_topic_business_inputs(
        version="2025.1",
        topic="ak.wwise.core.audio.imported",
        option_facts=(),
        match_facts=(),
        entry_facts=(
            TopicBusinessEntryFact("objects", (0,), "@Volume", "-4"),
        ),
        entry_object_facts=(
            TopicBusinessEntryObjectFact(
                "objects",
                (0,),
                "OutputBus",
                "name",
                "Master Audio Bus",
            ),
        ),
        entry_row_facts=(
            TopicBusinessEntryRowFact(
                "objects",
                (0,),
                "Children",
                0,
                "name",
                "Footstep_Run",
            ),
        ),
    )

    assert materialized.match == {
        "objects": [
            {
                "@Volume": -4,
                "OutputBus": {"name": "Master Audio Bus"},
                "Children": [{"name": "Footstep_Run"}],
            }
        ]
    }


def test_empty_business_containers_preserve_legacy_present_semantics() -> None:
    empty_root = materialize_topic_business_inputs(
        version="2025.1",
        topic="ak.wwise.core.audio.imported",
        option_facts=(),
        match_facts=(),
        match_empty_facts=(TopicBusinessEmptyFact("objects"),),
    )
    assert empty_root.match == {"objects": []}

    empty_nested = materialize_topic_business_inputs(
        version="2025.1",
        topic="ak.wwise.core.audio.imported",
        option_facts=(),
        match_facts=(),
        empty_row_facts=(
            TopicBusinessEmptyRowFact("objects-points", (0,)),
        ),
        entry_empty_facts=(
            TopicBusinessEntryEmptyFact(
                "objects",
                (0,),
                "Children",
                "list",
            ),
        ),
    )
    assert empty_nested.match == {
        "objects": [{"points": [], "Children": []}]
    }
