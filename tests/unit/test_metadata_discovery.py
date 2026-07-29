from __future__ import annotations

from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.metadata import (  # pyright: ignore[reportMissingImports]
    GET_PROPERTY_AND_REFERENCE_NAMES_URI,
    GET_PROPERTY_INFO_URI,
    GET_TYPES_URI,
)
from wwise_waapi.metadata_discovery import (  # pyright: ignore[reportMissingImports]
    DEFAULT_METADATA_DISCOVERY_LIMIT,
    MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN,
    MAX_METADATA_DISCOVERY_LIMIT,
    MAX_METADATA_DISCOVERY_NAMES,
    MAX_METADATA_DISCOVERY_QUERY_CHARS,
    MAX_METADATA_DISCOVERY_QUERIES,
    METADATA_DISCOVERY_CONTRACT,
    MetadataDiscoveryError,
    discover_metadata,
)


class MetadataReader:
    def __init__(
        self,
        *,
        types: list[Mapping[str, Any]] | None = None,
        names: list[str] | None = None,
        info: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.types = list(
            types
            or [
                {"classId": 65552, "name": "Sound", "type": "WObject"},
                {
                    "classId": 589840,
                    "name": "RandomSequenceContainer",
                    "type": "WObject",
                },
            ]
        )
        self.names = list(names or [])
        self.info = {name: dict(value) for name, value in (info or {}).items()}
        self.calls: list[
            tuple[str, Mapping[str, Any], Mapping[str, Any]]
        ] = []

    def __call__(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls.append((uri, dict(args), dict(options)))
        if uri == GET_TYPES_URI:
            return {"return": list(self.types)}
        if uri == GET_PROPERTY_AND_REFERENCE_NAMES_URI:
            return {"return": list(self.names)}
        if uri == GET_PROPERTY_INFO_URI:
            return dict(self.info[str(args["property"])])
        raise AssertionError(f"unapproved metadata URI: {uri}")


def _property_info(
    name: str,
    *,
    property_type: str = "Boolean",
    display_name: str | None = None,
    dependencies: list[Mapping[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": property_type,
        "default": False if property_type.casefold() in {"bool", "boolean"} else None,
        "display": {"name": display_name or name},
        "dependencies": [dict(item) for item in (dependencies or [])],
        **extra,
    }


def _self_dependency(name: str) -> dict[str, Any]:
    return {
        "type": "override",
        "action": "Enable",
        "context": "Self",
        "property": name,
    }


def test_object_type_discovery_resolves_live_name_and_returns_rich_candidates() -> None:
    names = [
        "IgnoreParentMaxSoundInstance",
        "IsLoopingEnabled",
        "MaxSoundPerInstance",
        "UseMaxSoundPerInstance",
        "Volume",
    ]
    reader = MetadataReader(
        names=names,
        info={name: _property_info(name) for name in names},
    )

    result = discover_metadata(
        read_call=reader,
        object_type="sound",
        queries=["looping enabled", "max sound instance"],
    ).as_dict()

    assert result["contract"] == METADATA_DISCOVERY_CONTRACT
    assert result["authority"] == "live-waapi"
    assert result["scope"] == {
        "kind": "object_type",
        "requested": "sound",
        "resolved": {"classId": 65552, "name": "Sound", "type": "WObject"},
    }
    assert result["available_name_count"] == len(names)
    assert result["candidate_count"] <= DEFAULT_METADATA_DISCOVERY_LIMIT
    assert {row["name"] for row in result["candidates"]} >= {
        "IsLoopingEnabled",
        "MaxSoundPerInstance",
    }
    looping = next(
        row for row in result["candidates"] if row["name"] == "IsLoopingEnabled"
    )
    assert looping["kind"] == "property"
    assert looping["metadata"]["type"] == "Boolean"
    assert looping["match_evidence"][0]["sources"][0] == {
        "field": "name",
        "value": "IsLoopingEnabled",
    }
    assert result["selection_required"] is True
    assert result["exact_live_name_required_for_mutation"] is True

    assert reader.calls[0] == (GET_TYPES_URI, {}, {})
    assert reader.calls[1] == (
        GET_PROPERTY_AND_REFERENCE_NAMES_URI,
        {"classId": 65552},
        {},
    )
    assert {call[0] for call in reader.calls} <= {
        GET_TYPES_URI,
        GET_PROPERTY_AND_REFERENCE_NAMES_URI,
        GET_PROPERTY_INFO_URI,
    }
    assert all(
        call[1].get("classId") == 65552
        for call in reader.calls[1:]
    )


def test_display_metadata_can_match_a_second_query_without_static_aliases() -> None:
    reader = MetadataReader(
        names=["OutputBus", "OutputRouting"],
        info={
            "OutputBus": _property_info(
                "OutputBus",
                property_type="Reference",
                display_name="Master Routing",
                restriction={"type": "reference"},
            ),
            "OutputRouting": _property_info(
                "OutputRouting",
                property_type="Reference",
                display_name="Secondary Output",
                restriction={"type": "reference"},
            ),
        },
    )

    result = discover_metadata(
        read_call=reader,
        class_id=65552,
        queries=["output", "master"],
    ).as_dict()

    second = result["query_results"][1]
    assert second == {
        "query": "master",
        "status": "single_candidate",
        "candidate_names": ["OutputBus"],
    }
    output_bus = next(
        row for row in result["candidates"] if row["name"] == "OutputBus"
    )
    evidence = next(
        row
        for row in output_bus["match_evidence"]
        if row["query"] == "master"
    )
    assert {"field": "live_metadata", "value": "Master Routing"} in evidence[
        "sources"
    ]
    assert result["fallback_detail_scan"]["status"] == "complete"


def test_display_only_query_triggers_bounded_live_detail_fallback() -> None:
    reader = MetadataReader(
        names=["OutputBus", "Volume"],
        info={
            "OutputBus": _property_info(
                "OutputBus",
                property_type="Reference",
                display_name="Master Routing",
                restriction={"type": "reference"},
            ),
            "Volume": _property_info("Volume"),
        },
    )

    result = discover_metadata(
        read_call=reader,
        class_id=65552,
        queries=["master routing"],
    ).as_dict()

    assert result["query_results"] == [
        {
            "query": "master routing",
            "status": "single_candidate",
            "candidate_names": ["OutputBus"],
        }
    ]
    assert result["fallback_detail_scan"] == {
        "status": "complete",
        "trigger_queries": ["master routing"],
        "live_name_count": 2,
        "inspected_name_count": 2,
        "inspection_limit": 256,
    }
    assert [
        call[1]["property"]
        for call in reader.calls
        if call[0] == GET_PROPERTY_INFO_URI
    ] == ["OutputBus", "Volume"]


def test_query_status_distinguishes_exact_single_multiple_and_no_match() -> None:
    reader = MetadataReader(
        names=["OutputBus", "OutputDevice", "Volume"],
        info={
            "OutputBus": _property_info("OutputBus"),
            "OutputDevice": _property_info("OutputDevice"),
            "Volume": _property_info("Volume"),
        },
    )

    result = discover_metadata(
        read_call=reader,
        class_id=65552,
        queries=["OutputBus", "device", "output", "playback ceiling"],
    ).as_dict()

    assert [row["status"] for row in result["query_results"]] == [
        "exact_live_name",
        "single_candidate",
        "multiple_candidates",
        "no_match",
    ]
    assert result["query_results"][3]["candidate_names"] == []
    assert "name_hints" not in result
    assert {call[1].get("property") for call in reader.calls[1:]} == {
        "OutputBus",
        "OutputDevice",
        "Volume",
    }


def test_no_lexical_match_is_reported_only_after_complete_live_detail_scan() -> None:
    reader = MetadataReader(
        names=["OutputBus", "Volume"],
        info={
            "OutputBus": _property_info("OutputBus"),
            "Volume": _property_info("Volume"),
        },
    )

    result = discover_metadata(
        read_call=reader,
        object="{10000000-0000-0000-0000-000000000001}",
        queries=["playback ceiling"],
    ).as_dict()

    assert result["candidates"] == []
    assert result["query_results"] == [
        {
            "query": "playback ceiling",
            "status": "no_match",
            "candidate_names": [],
        }
    ]
    assert result["fallback_detail_scan"]["status"] == "complete"
    assert [call[0] for call in reader.calls] == [
        GET_PROPERTY_AND_REFERENCE_NAMES_URI,
        GET_PROPERTY_INFO_URI,
        GET_PROPERTY_INFO_URI,
    ]
    assert reader.calls[0][1] == {
        "object": "{10000000-0000-0000-0000-000000000001}"
    }


def test_same_object_dependency_closure_is_live_bounded_and_cycle_safe() -> None:
    reader = MetadataReader(
        names=["EnableRouting", "OutputBus", "OverrideOutput"],
        info={
            "OutputBus": _property_info(
                "OutputBus",
                property_type="Reference",
                restriction={"type": "reference"},
                dependencies=[_self_dependency("OverrideOutput")],
            ),
            "OverrideOutput": _property_info(
                "OverrideOutput",
                dependencies=[_self_dependency("EnableRouting")],
            ),
            "EnableRouting": _property_info(
                "EnableRouting",
                dependencies=[_self_dependency("OutputBus")],
            ),
        },
    )

    result = discover_metadata(
        read_call=reader,
        class_id=65552,
        queries=["OutputBus"],
        limit=1,
    ).as_dict()

    assert result["dependency_closure_complete"] is True
    assert result["unresolved_dependencies"] == []
    candidate = result["candidates"][0]
    assert candidate["kind"] == "reference"
    assert candidate["same_object_dependencies"] == [
        "EnableRouting",
        "OverrideOutput",
    ]
    assert [row["name"] for row in result["dependency_candidates"]] == [
        "EnableRouting",
        "OverrideOutput",
    ]
    assert {
        call[1]["property"]
        for call in reader.calls
        if call[0] == GET_PROPERTY_INFO_URI
    } == {"EnableRouting", "OutputBus", "OverrideOutput"}


def test_dependency_cycle_below_root_does_not_repeat_reads_or_exhaust_depth() -> None:
    reader = MetadataReader(
        names=["FirstGate", "OutputBus", "SecondGate"],
        info={
            "OutputBus": _property_info(
                "OutputBus",
                dependencies=[_self_dependency("FirstGate")],
            ),
            "FirstGate": _property_info(
                "FirstGate",
                dependencies=[_self_dependency("SecondGate")],
            ),
            "SecondGate": _property_info(
                "SecondGate",
                dependencies=[_self_dependency("FirstGate")],
            ),
        },
    )

    result = discover_metadata(
        read_call=reader,
        class_id=65552,
        queries=["OutputBus"],
        limit=1,
    ).as_dict()

    assert result["dependency_closure_complete"] is True
    assert result["candidates"][0]["same_object_dependencies"] == [
        "FirstGate",
        "SecondGate",
    ]
    assert [
        call[1]["property"]
        for call in reader.calls
        if call[0] == GET_PROPERTY_INFO_URI
    ] == ["OutputBus", "FirstGate", "SecondGate"]


def test_non_self_or_unresolvable_dependencies_are_reported_not_guessed() -> None:
    reader = MetadataReader(
        names=["OutputBus"],
        info={
            "OutputBus": _property_info(
                "OutputBus",
                dependencies=[
                    {
                        "action": "Enable",
                        "context": "Parent",
                        "property": "OverrideOutput",
                    },
                    {
                        "action": "Enable",
                        "context": "Self",
                        "property": "MissingProperty",
                    },
                ],
            )
        },
    )

    result = discover_metadata(
        read_call=reader,
        class_id=65552,
        queries=["output bus"],
    ).as_dict()

    assert result["dependency_closure_complete"] is False
    assert [row["reason"] for row in result["unresolved_dependencies"]] == [
        "not-a-resolvable-same-object-property",
        "dependency-name-not-in-live-inventory",
    ]
    assert [
        call[1]["property"]
        for call in reader.calls
        if call[0] == GET_PROPERTY_INFO_URI
    ] == ["OutputBus"]


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    [
        (
            {
                "class_id": 1,
                "object": "{10000000-0000-0000-0000-000000000001}",
                "queries": ["volume"],
            },
            "INVALID_DISCOVERY_SCOPE",
        ),
        ({"queries": ["volume"]}, "INVALID_DISCOVERY_SCOPE"),
        ({"class_id": True, "queries": ["volume"]}, "INVALID_CLASS_ID"),
        (
            {"class_id": 1, "queries": []},
            "INVALID_DISCOVERY_QUERY",
        ),
        (
            {
                "class_id": 1,
                "queries": ["x"] * (MAX_METADATA_DISCOVERY_QUERIES + 1),
            },
            "INVALID_DISCOVERY_QUERY",
        ),
        (
            {
                "class_id": 1,
                "queries": ["x" * (MAX_METADATA_DISCOVERY_QUERY_CHARS + 1)],
            },
            "INVALID_DISCOVERY_ARGUMENT",
        ),
        (
            {
                "class_id": 1,
                "queries": ["volume"],
                "limit": MAX_METADATA_DISCOVERY_LIMIT + 1,
            },
            "INVALID_DISCOVERY_LIMIT",
        ),
    ],
)
def test_invalid_requests_fail_before_any_live_call(
    kwargs: Mapping[str, Any],
    error_code: str,
) -> None:
    reader = MetadataReader()

    with pytest.raises(MetadataDiscoveryError) as caught:
        discover_metadata(read_call=reader, **kwargs)

    assert caught.value.error_code == error_code
    assert caught.value.as_dict()["error_code"] == error_code
    assert reader.calls == []


def test_object_type_matches_only_exact_live_name_not_broad_type_field() -> None:
    reader = MetadataReader(names=["Volume"], info={"Volume": _property_info("Volume")})

    with pytest.raises(MetadataDiscoveryError) as caught:
        discover_metadata(
            read_call=reader,
            object_type="WObject",
            queries=["volume"],
        )

    assert caught.value.error_code == "OBJECT_TYPE_NOT_UNIQUE"
    assert [call[0] for call in reader.calls] == [GET_TYPES_URI]


def test_live_name_and_property_info_mismatch_fail_closed() -> None:
    reader = MetadataReader(
        names=["Volume"],
        info={"Volume": _property_info("Pitch")},
    )

    with pytest.raises(MetadataDiscoveryError) as caught:
        discover_metadata(
            read_call=reader,
            class_id=65552,
            queries=["volume"],
        )

    assert caught.value.error_code == "LIVE_METADATA_NAME_MISMATCH"
    assert caught.value.details == {"requested": "Volume", "actual": "Pitch"}


def test_live_inventory_count_and_error_details_remain_bounded() -> None:
    reader = MetadataReader(
        names=[f"Property{index}" for index in range(MAX_METADATA_DISCOVERY_NAMES + 1)]
    )

    with pytest.raises(MetadataDiscoveryError) as caught:
        discover_metadata(
            read_call=reader,
            class_id=65552,
            queries=["property"],
        )

    assert caught.value.error_code == "LIVE_METADATA_LIMIT_EXCEEDED"
    oversized = MetadataDiscoveryError(
        "TEST",
        "bounded",
        details={"value": "x" * 20_000},
    )
    assert oversized.details == {
        "details_omitted": True,
        "reason": "error details exceeded the public JSON bound",
    }


def test_fallback_detail_scan_is_explicitly_partial_above_its_live_read_bound() -> None:
    names = [
        f"Property{index}"
        for index in range(MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN + 1)
    ]
    reader = MetadataReader(
        names=names,
        info={name: _property_info(name) for name in names},
    )

    result = discover_metadata(
        read_call=reader,
        class_id=65552,
        queries=["display phrase with no internal overlap"],
    ).as_dict()

    assert result["candidates"] == []
    assert result["fallback_detail_scan"] == {
        "status": "partial",
        "trigger_queries": ["display phrase with no internal overlap"],
        "live_name_count": MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN + 1,
        "inspected_name_count": MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN,
        "inspection_limit": MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN,
    }
    assert sum(
        call[0] == GET_PROPERTY_INFO_URI for call in reader.calls
    ) == MAX_METADATA_DISCOVERY_FALLBACK_DETAIL_SCAN


def test_read_failures_are_structured_and_do_not_leak_unbounded_text() -> None:
    def failing_reader(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del uri, args, options
        raise RuntimeError("x" * 5_000)

    with pytest.raises(MetadataDiscoveryError) as caught:
        discover_metadata(
            read_call=failing_reader,
            class_id=65552,
            queries=["volume"],
        )

    assert caught.value.error_code == "LIVE_METADATA_READ_FAILED"
    assert len(caught.value.details["cause"]) <= 512
