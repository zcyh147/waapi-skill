from __future__ import annotations

import json
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.metadata import (  # pyright: ignore[reportMissingImports]
    GET_PROPERTY_AND_REFERENCE_NAMES_URI,
    GET_PROPERTY_INFO_URI,
    GET_TYPES_URI,
)
from wwise_waapi.metadata_discovery import (  # pyright: ignore[reportMissingImports]
    DEFAULT_METADATA_DISCOVERY_LIMIT,
    MAX_METADATA_DISCOVERY_AGENT_RESULT_BYTES,
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


def test_object_type_discovery_resolves_live_name_and_returns_compact_candidates() -> None:
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

    discovery = discover_metadata(
        read_call=reader,
        object_type="sound",
        queries=["looping enabled", "max sound instance"],
    )
    result = discovery.as_dict()

    assert result["contract"] == METADATA_DISCOVERY_CONTRACT
    assert result["authority"] == "live-waapi"
    assert result["result_detail"] == "compact"
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
    assert "match_evidence" not in looping
    assert set(looping["metadata"]) == {
        "name",
        "type",
        "default",
        "display",
        "restriction",
        "typed_value_type",
    }
    assert looping["metadata"]["typed_value_type"] == "boolean"
    detailed = discovery.as_dict(detail=True)
    assert detailed["contract"] == "waapi-skill.metadata-discovery/v1"
    assert "result_detail" not in detailed
    assert set(detailed) == {
        "contract",
        "authority",
        "scope",
        "queries",
        "available_name_count",
        "candidate_count",
        "query_results",
        "candidates",
        "mutation_authoring_policy",
        "dependency_candidates",
        "dependency_closure_complete",
        "unresolved_dependencies",
        "fallback_detail_scan",
        "selection_required",
        "exact_live_name_required_for_mutation",
    }
    detailed_looping = next(
        row
        for row in detailed["candidates"]
        if row["name"] == "IsLoopingEnabled"
    )
    assert detailed_looping["match_evidence"][0]["sources"][0] == {
        "field": "name",
        "value": "IsLoopingEnabled",
    }
    assert {
        "supports",
        "ui",
        "audioEngineId",
        "dependencies",
    } <= set(detailed_looping["metadata"])
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
    assert output_bus["matched_queries"] == ["output", "master"]
    assert output_bus["metadata"]["display"] == {"name": "Master Routing"}
    assert "match_evidence" not in output_bus
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
    assert candidate["dependency_requirements"] == [
        {
            "type": "override",
            "action": "Enable",
            "context": "Self",
            "property": "OverrideOutput",
            "required_values": [True],
        }
    ]
    assert [row["name"] for row in result["dependency_candidates"]] == [
        "EnableRouting",
        "OverrideOutput",
    ]
    override = next(
        row
        for row in result["dependency_candidates"]
        if row["name"] == "OverrideOutput"
    )
    assert override["dependency_requirements"] == [
        {
            "type": "override",
            "action": "Enable",
            "context": "Self",
            "property": "EnableRouting",
            "required_values": [True],
        }
    ]
    assert override["matched_queries"] == ["OutputBus"]
    assert {
        call[1]["property"]
        for call in reader.calls
        if call[0] == GET_PROPERTY_INFO_URI
    } == {"EnableRouting", "OutputBus", "OverrideOutput"}


def test_dependency_candidate_preserves_overlap_with_an_explicit_enable_query() -> None:
    reader = MetadataReader(
        names=["MaxSoundPerInstance", "UseMaxSoundPerInstance"],
        info={
            "MaxSoundPerInstance": _property_info(
                "MaxSoundPerInstance",
                property_type="int16",
                display_name="Maximum playback instances",
                dependencies=[_self_dependency("UseMaxSoundPerInstance")],
            ),
            "UseMaxSoundPerInstance": _property_info(
                "UseMaxSoundPerInstance",
                display_name="Limit Sound Instances",
            ),
        },
    )

    result = discover_metadata(
        read_call=reader,
        object_type="Sound",
        queries=["maximum playback instances enabled"],
        limit=1,
    ).as_dict()

    assert [row["name"] for row in result["candidates"]] == [
        "MaxSoundPerInstance"
    ]
    assert result["dependency_candidates"] == [
        {
            "name": "UseMaxSoundPerInstance",
            "kind": "property",
            "matched_queries": ["maximum playback instances enabled"],
            "required_by": ["MaxSoundPerInstance"],
            "dependency_requirements": [],
            "metadata": {
                "name": "UseMaxSoundPerInstance",
                "type": "Boolean",
                "default": False,
                "display": {"name": "Limit Sound Instances"},
                "restriction": {},
                "typed_value_type": "boolean",
            },
        }
    ]


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


def test_compact_dependency_requirements_preserve_all_live_conditions() -> None:
    dependency = {
        "type": "property",
        "action": "Enable",
        "context": "Self",
        "property": "ActivationGate",
        "conditions": [
            {
                "restriction": {
                    "type": "enum",
                    "values": [{"displayName": "True", "value": True}],
                }
            },
            {
                "referenceIsSet": {
                    "reference": "OutputBus",
                    "value": True,
                }
            },
        ],
    }
    reader = MetadataReader(
        names=["ActivationGate", "TargetSetting"],
        info={
            "ActivationGate": _property_info("ActivationGate"),
            "TargetSetting": _property_info(
                "TargetSetting",
                dependencies=[dependency],
            ),
        },
    )

    result = discover_metadata(
        read_call=reader,
        class_id=65552,
        queries=["TargetSetting"],
        limit=1,
    ).as_dict()

    assert result["candidates"][0]["dependency_requirements"] == [
        {**dependency, "required_values": [True]}
    ]


def test_compact_five_query_agent_result_stays_below_terminal_visibility_bound() -> None:
    queries = ("loop", "limit", "output", "pitch", "stream")
    names: list[str] = []
    info: dict[str, Mapping[str, Any]] = {}
    gate_names: list[str] = []
    for query_index, query in enumerate(queries):
        gate = f"ActivationGate{query_index}"
        gate_names.append(gate)
        for candidate_index in range(4):
            name = f"{query.title()}Setting{candidate_index}"
            names.append(name)
            info[name] = _property_info(
                name,
                property_type="Real32",
                display_name=f"{query.title()} setting {candidate_index}",
                dependencies=(
                    [_self_dependency(gate)]
                    if candidate_index == 0
                    else []
                ),
                supports={
                    "unlink": True,
                    "rtpc": "Exclusive",
                    "randomizer": False,
                },
                restriction={"type": "range", "min": -200.0, "max": 200.0},
                ui={
                    "value": {
                        "min": -200.0,
                        "max": 200.0,
                        "decimals": 3,
                        "step": 0.1,
                        "fine": 0.01,
                        "infinity": 0.0,
                    },
                    "displayAs": {
                        "lrMix": False,
                        "musicNote": False,
                        "bitfield": False,
                    },
                    "dataMeaning": "None",
                    "autoUpdate": False,
                },
                audioEngineId=1000 + query_index * 10 + candidate_index,
            )
        info[gate] = _property_info(gate)
    names.extend(gate_names)
    reader = MetadataReader(names=names, info=info)

    discovery = discover_metadata(
        read_call=reader,
        object_type="Sound",
        queries=queries,
        limit=8,
    )
    compact = discovery.as_dict()
    detailed = discovery.as_dict(detail=True)
    compact_bytes = (
        len(
            json.dumps(
                compact,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
                allow_nan=False,
            ).encode("utf-8")
        )
        + 1
    )

    assert len(compact["query_results"]) == 5
    assert len(compact["candidates"]) == 20
    assert compact["candidate_count"] == len(compact["candidates"])
    assert [row["name"] for row in compact["candidates"]] == [
        row["name"] for row in detailed["candidates"]
    ]
    assert len(compact["dependency_candidates"]) == 5
    assert compact_bytes <= MAX_METADATA_DISCOVERY_AGENT_RESULT_BYTES
    assert len(json.dumps(detailed, ensure_ascii=False, indent=2)) > compact_bytes
    assert all(
        set(row["metadata"]).isdisjoint(
            {"supports", "ui", "audioEngineId", "dependencies"}
        )
        for row in (
            *compact["candidates"],
            *compact["dependency_candidates"],
        )
    )
    assert all(
        row["metadata"]["range"] == {"min": -200.0, "max": 200.0}
        for row in compact["candidates"]
    )
    first = compact["candidates"][0]
    assert first["dependency_requirements"][0]["required_values"] == [True]


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


def test_is_master_bus_visibility_predicate_is_terminal_not_a_property_edge() -> None:
    predicate = {
        "action": "Show",
        "context": "Self",
        "type": "isMasterBus",
        "value": False,
    }
    reader = MetadataReader(
        names=["IgnoreParentMaxSoundInstance"],
        info={
            "IgnoreParentMaxSoundInstance": _property_info(
                "IgnoreParentMaxSoundInstance",
                dependencies=[predicate],
            )
        },
    )

    result = discover_metadata(
        read_call=reader,
        class_id=65552,
        queries=["ignore parent playback limit"],
    ).as_dict()

    assert result["dependency_closure_complete"] is True
    assert result["unresolved_dependencies"] == []
    assert result["dependency_candidates"] == []
    assert result["candidates"][0]["same_object_dependencies"] == []
    assert result["candidates"][0]["dependency_requirements"] == []
    detailed = discover_metadata(
        read_call=MetadataReader(
            names=["IgnoreParentMaxSoundInstance"],
            info={
                "IgnoreParentMaxSoundInstance": _property_info(
                    "IgnoreParentMaxSoundInstance",
                    dependencies=[predicate],
                )
            },
        ),
        class_id=65552,
        queries=["ignore parent playback limit"],
    ).as_dict(detail=True)
    assert detailed["candidates"][0]["metadata"]["dependencies"] == [predicate]
    assert [
        call[1]["property"]
        for call in reader.calls
        if call[0] == GET_PROPERTY_INFO_URI
    ] == ["IgnoreParentMaxSoundInstance"]


@pytest.mark.parametrize(
    "predicate",
    [
        {
            "action": "Show",
            "context": "Parent",
            "type": "isMasterBus",
            "value": False,
        },
        {
            "action": "Show",
            "context": "Self",
            "type": "isMasterBus",
        },
        {
            "action": "Show",
            "context": "Self",
            "type": "futureStructuralPredicate",
            "value": False,
        },
    ],
)
def test_unreviewed_structural_dependencies_remain_unresolved(
    predicate: dict[str, object],
) -> None:
    reader = MetadataReader(
        names=["IgnoreParentMaxSoundInstance"],
        info={
            "IgnoreParentMaxSoundInstance": _property_info(
                "IgnoreParentMaxSoundInstance",
                dependencies=[predicate],
            )
        },
    )

    result = discover_metadata(
        read_call=reader,
        class_id=65552,
        queries=["ignore parent playback limit"],
    ).as_dict()

    assert result["dependency_closure_complete"] is False
    assert result["unresolved_dependencies"][0]["reason"] == (
        "not-a-resolvable-same-object-property"
    )


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
