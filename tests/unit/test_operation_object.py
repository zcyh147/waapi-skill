from __future__ import annotations

import math

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_object import (  # pyright: ignore[reportMissingImports]
    ObjectOperationContractError,
    ObjectTreeLimits,
    bind_request_result_topology,
    describe_conflict_policy,
    flatten_create_result,
    flatten_set_result,
    materialize_waapi_node,
    materialize_waapi_rtpc,
    normalize_conflict_policy,
    normalize_object_forest,
    normalize_object_lists,
    normalize_object_tree,
    normalize_property_descriptors,
    normalize_reference_descriptors,
    normalize_rtpc_descriptors,
    request_topology_edges,
)


def _node(name: str, *, children: list[dict[str, object]] | None = None) -> dict[str, object]:
    result: dict[str, object] = {"type": "ActorMixer", "name": name}
    if children is not None:
        result["children"] = children
    return result


def test_recursive_tree_is_normalized_materialized_and_bound_by_topology() -> None:
    tree = normalize_object_tree(
        {
            "type": "ActorMixer",
            "name": "Player_Foley",
            "notes": "角色脚步统一入口",
            "properties": [{"name": "Volume", "value": -2.0}],
            "references": [
                {
                    "name": "OutputBus",
                    "target": {"kind": "path", "value": "\\Master-Mixer Hierarchy\\Default Work Unit\\Master Audio Bus"},
                }
            ],
            "children": [
                {
                    "type": "RandomSequenceContainer",
                    "name": "Footsteps",
                    "children": [
                        {"type": "Sound", "name": "Footstep_A"},
                        {"type": "Sound", "name": "Footstep_B"},
                    ],
                },
                {"type": "BlendContainer", "name": "Cloth"},
            ],
        },
        on_name_conflict="merge",
    )

    assert tree.on_name_conflict == "merge"
    assert [node.request_path for node in tree.nodes] == [
        "$",
        "$.children[0]",
        "$.children[0].children[0]",
        "$.children[0].children[1]",
        "$.children[1]",
    ]
    assert [(edge.parent_request_path, edge.child_request_path) for edge in request_topology_edges(tree.nodes)] == [
        ("$", "$.children[0]"),
        ("$.children[0]", "$.children[0].children[0]"),
        ("$.children[0]", "$.children[0].children[1]"),
        ("$", "$.children[1]"),
    ]

    payload = materialize_waapi_node(
        tree.root,
        resolved_references={"$.references[0]": "{MASTER-BUS}"},
    )
    assert payload["@Volume"] == -2.0
    assert payload["@OutputBus"] == "{MASTER-BUS}"
    assert payload["children"][0]["children"][1] == {"type": "Sound", "name": "Footstep_B"}
    assert "properties" not in payload
    assert "references" not in payload

    result_nodes = flatten_create_result(
        {
            "id": "{ROOT}",
            "name": "Player_Foley",
            "children": [
                {
                    "id": "{FOOTSTEPS}",
                    "name": "Footsteps",
                    "children": [
                        {"id": "{A}", "name": "Footstep_A"},
                        {"id": "{B}", "name": "Footstep_B"},
                    ],
                },
                {"id": "{CLOTH}", "name": "Cloth"},
            ],
        }
    )
    bindings = bind_request_result_topology(tree.nodes, result_nodes)
    assert [binding.object for binding in bindings] == ["{ROOT}", "{FOOTSTEPS}", "{A}", "{B}", "{CLOTH}"]


def test_object_set_result_allows_omitted_optional_objects_array() -> None:
    assert flatten_set_result({}) == ()
    assert flatten_set_result({"objects": []}) == ()


@pytest.mark.parametrize("objects", (None, {}, "invalid", 1, True))
def test_object_set_result_rejects_non_array_objects_when_present(objects: object) -> None:
    with pytest.raises(ObjectOperationContractError) as rejected:
        flatten_set_result({"objects": objects})

    assert rejected.value.error_code == "INVALID_RESULT_SHAPE"
    assert rejected.value.details["path"] == "$result.objects"


def test_depth_and_total_node_limits_fail_closed() -> None:
    depth_two = _node("Root", children=[_node("Child")])
    assert len(normalize_object_tree(depth_two, limits=ObjectTreeLimits(max_depth=2)).nodes) == 2

    too_deep = _node("Root", children=[_node("Child", children=[_node("Grandchild")])])
    with pytest.raises(ObjectOperationContractError) as depth_error:
        normalize_object_tree(too_deep, limits=ObjectTreeLimits(max_depth=2))
    assert depth_error.value.error_code == "DEPTH_LIMIT_EXCEEDED"
    assert depth_error.value.details["path"] == "$.children[0].children[0]"

    with pytest.raises(ObjectOperationContractError) as node_error:
        normalize_object_forest(
            [_node("One"), _node("Two"), _node("Three")],
            limits=ObjectTreeLimits(max_nodes=2),
        )
    assert node_error.value.error_code == "NODE_LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    ("payload", "path"),
    [
        ({"type": "ActorMixer", "name": "Root", "@Volume": -2}, "$"),
        ({"type": "ActorMixer", "name": "Root", "id": "{CALLER-ID}"}, "$"),
        ({"type": "ActorMixer", "name": "Root", "classId": 123}, "$"),
        ({"type": "ActorMixer", "name": "Root", "platform": "Windows"}, "$"),
        (
            {
                "type": "ActorMixer",
                "name": "Root",
                "properties": [{"name": "Volume", "value": -2, "raw": True}],
            },
            "$.properties[0]",
        ),
        (
            {
                "type": "ActorMixer",
                "name": "Root",
                "references": [{"name": "OutputBus", "target": {"kind": "id", "value": "{BUS}"}, "value": "{BYPASS}"}],
            },
            "$.references[0]",
        ),
    ],
)
def test_unknown_or_native_escape_fields_are_rejected(payload: dict[str, object], path: str) -> None:
    with pytest.raises(ObjectOperationContractError) as exc:
        normalize_object_tree(payload)
    assert exc.value.error_code == "INVALID_FIELDS"
    assert exc.value.details["path"] == path


def test_conflict_policies_expose_guards_and_replace_requires_ownership() -> None:
    assert [normalize_conflict_policy(value) for value in ("fail", "rename", "merge")] == [
        "fail",
        "rename",
        "merge",
    ]
    with pytest.raises(ObjectOperationContractError) as unsafe_replace:
        normalize_conflict_policy("replace")
    assert unsafe_replace.value.error_code == "REPLACE_OWNERSHIP_REQUIRED"
    assert normalize_conflict_policy("replace", replace_owned=True) == "replace"

    replace = describe_conflict_policy("replace")
    assert replace.requires_owned_collision is True
    assert replace.can_delete_preexisting_objects is True
    assert "cannot be restored" in replace.cleanup_boundary
    assert describe_conflict_policy("fail").requires_absence_guard is True
    assert describe_conflict_policy("merge").requires_collision_snapshot is True

    with pytest.raises(ObjectOperationContractError) as unknown:
        normalize_conflict_policy("overwrite")
    assert unknown.value.error_code == "INVALID_CONFLICT_POLICY"


def test_property_and_reference_descriptors_are_closed_and_typed() -> None:
    properties = normalize_property_descriptors(
        [
            {"name": "Volume", "value": -3},
            {"name": "IsStreamingEnabled", "value": True},
            {"name": "NotesTag", "value": "combat"},
        ]
    )
    assert [(item.name, item.value) for item in properties] == [
        ("Volume", -3),
        ("IsStreamingEnabled", True),
        ("NotesTag", "combat"),
    ]

    references = normalize_reference_descriptors(
        [
            {"name": "OutputBus", "target": {"kind": "id", "value": "{BUS}"}},
            {
                "name": "Attenuation",
                "target": {
                    "kind": "scoped-name",
                    "name": "Outdoor",
                    "type": "Attenuation",
                    "parent": {"kind": "path", "value": "\\Attenuations\\Default Work Unit"},
                },
            },
            {
                "name": "Target",
                "target": {
                    "kind": "direct-child",
                    "parent": {
                        "kind": "path",
                        "value": "\\Events\\Default Work Unit\\Play_Weather",
                    },
                    "type": "Action",
                },
            },
        ]
    )
    assert references[0].target.as_dict() == {"kind": "id", "value": "{BUS}"}
    assert references[1].target.parent is not None
    assert references[1].target.parent.kind == "path"
    assert references[2].target.as_dict() == {
        "kind": "direct-child",
        "parent": {
            "kind": "path",
            "value": "\\Events\\Default Work Unit\\Play_Weather",
        },
        "type": "Action",
    }

    for invalid_value in (None, [1, 2], {"value": 1}, math.nan, math.inf):
        with pytest.raises(ObjectOperationContractError) as invalid:
            normalize_property_descriptors([{"name": "Volume", "value": invalid_value}])
        assert invalid.value.error_code == "INVALID_PROPERTY_VALUE"

    with pytest.raises(ObjectOperationContractError) as raw_name:
        normalize_property_descriptors([{"name": "@Volume", "value": -2}])
    assert raw_name.value.error_code == "INVALID_FIELD_NAME"

    with pytest.raises(ObjectOperationContractError) as missing_target:
        normalize_reference_descriptors([{"name": "OutputBus", "target": None}])
    assert missing_target.value.error_code == "INVALID_OBJECT"


def test_duplicate_fields_and_sibling_names_are_rejected_case_insensitively() -> None:
    with pytest.raises(ObjectOperationContractError) as fields:
        normalize_object_tree(
            {
                "type": "ActorMixer",
                "name": "Root",
                "properties": [{"name": "Volume", "value": -1}],
                "references": [{"name": "volume", "target": {"kind": "id", "value": "{X}"}}],
            }
        )
    assert fields.value.error_code == "DUPLICATE_FIELD"

    with pytest.raises(ObjectOperationContractError) as siblings:
        normalize_object_tree(
            _node("Root", children=[{"type": "Sound", "name": "Hit"}, {"type": "Sound", "name": "hit"}])
        )
    assert siblings.value.error_code == "DUPLICATE_SIBLING_NAME"

    with pytest.raises(ObjectOperationContractError) as field_limit:
        normalize_object_tree(
            {
                "type": "ActorMixer",
                "name": "Root",
                "properties": [{"name": "Volume", "value": -1}],
                "references": [{"name": "OutputBus", "target": {"kind": "id", "value": "{X}"}}],
            },
            limits=ObjectTreeLimits(max_fields_per_node=1),
        )
    assert field_limit.value.error_code == "FIELD_LIMIT_EXCEEDED"


def test_reference_materialization_requires_exact_live_bindings() -> None:
    tree = normalize_object_tree(
        {
            "type": "Sound",
            "name": "Hit",
            "references": [{"name": "OutputBus", "target": {"kind": "id", "value": "{REQUESTED}"}}],
        }
    )
    with pytest.raises(ObjectOperationContractError) as missing:
        materialize_waapi_node(tree.root)
    assert missing.value.error_code == "REFERENCE_BINDING_MISMATCH"

    with pytest.raises(ObjectOperationContractError) as extra:
        materialize_waapi_node(
            tree.root,
            resolved_references={"$.references[0]": "{RESOLVED}", "$.references[1]": "{EXTRA}"},
        )
    assert extra.value.error_code == "REFERENCE_BINDING_MISMATCH"


def test_result_topology_mismatch_never_binds_ids_by_guessing_names() -> None:
    tree = normalize_object_tree(_node("Root", children=[{"type": "Sound", "name": "A"}]))
    returned = flatten_create_result({"id": "{ROOT}", "name": "Root"})
    with pytest.raises(ObjectOperationContractError) as exc:
        bind_request_result_topology(tree.nodes, returned)
    assert exc.value.error_code == "TOPOLOGY_MISMATCH"
    assert exc.value.details["missing"] == ["$.children[0]"]


def test_rtpc_descriptors_are_closed_normalized_and_materialized() -> None:
    descriptors = normalize_rtpc_descriptors(
        [
            {
                "property": "OutputBusVolume",
                "control_input": {"kind": "path", "value": "\\Game Parameters\\Default Work Unit\\Distance"},
                "points": [
                    {"x": 0, "y": -20.0, "shape": "Linear"},
                    {"x": 100, "y": 0, "shape": "SCurve"},
                ],
                "notes": "Distance curve",
            }
        ]
    )
    assert [item.as_dict() for item in descriptors] == [
        {
            "property": "OutputBusVolume",
            "control_input": {"kind": "path", "value": "\\Game Parameters\\Default Work Unit\\Distance"},
            "points": [
                {"x": 0, "y": -20.0, "shape": "Linear"},
                {"x": 100, "y": 0, "shape": "SCurve"},
            ],
            "notes": "Distance curve",
        }
    ]
    assert materialize_waapi_rtpc(descriptors[0], resolved_control_input="{CONTROL}") == {
        "type": "RTPC",
        "name": "",
        "@Curve": {
            "type": "Curve",
            "points": [
                {"x": 0, "y": -20.0, "shape": "Linear"},
                {"x": 100, "y": 0, "shape": "SCurve"},
            ],
        },
        "@PropertyName": "OutputBusVolume",
        "@ControlInput": "{CONTROL}",
        "notes": "Distance curve",
    }


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ([], "EMPTY_RTPC_LIST"),
        (
            [
                {
                    "property": "Volume",
                    "control_input": {"kind": "id", "value": "{CONTROL}"},
                    "points": [],
                }
            ],
            "RTPC_POINT_LIMIT",
        ),
        (
            [
                {
                    "property": "Volume",
                    "control_input": {"kind": "id", "value": "{CONTROL}"},
                    "points": [
                        {"x": 1, "y": 0, "shape": "Linear"},
                        {"x": 0, "y": 1, "shape": "Linear"},
                    ],
                }
            ],
            "INVALID_RTPC_POINT_ORDER",
        ),
        (
            [
                {
                    "property": "Volume",
                    "control_input": {"kind": "id", "value": "{CONTROL}"},
                    "points": [{"x": 0, "y": 0, "shape": "Bezier"}],
                }
            ],
            "INVALID_RTPC_POINT_SHAPE",
        ),
        (
            [
                {
                    "property": "Volume",
                    "control_input": {"kind": "id", "value": "{CONTROL}"},
                    "points": [{"x": 0, "y": 0, "shape": "Linear"}],
                    "listMode": "replaceAll",
                }
            ],
            "INVALID_FIELDS",
        ),
    ],
)
def test_rtpc_descriptors_fail_closed(payload: object, error_code: str) -> None:
    with pytest.raises(ObjectOperationContractError) as exc:
        normalize_rtpc_descriptors(payload)
    assert exc.value.error_code == error_code


def test_closed_object_lists_normalize_empty_clear_and_recursive_nodes() -> None:
    lists = normalize_object_lists(
        [
            {"name": "Clips", "objects": []},
            {
                "name": "Sequences",
                "objects": [
                    {
                        "type": "MusicSegment",
                        "name": "Intro",
                        "children": [{"type": "MusicTrack", "name": "Track"}],
                    }
                ],
            },
        ]
    )

    assert [item.name for item in lists] == ["Clips", "Sequences"]
    assert lists[0].objects == ()
    assert [node.request_path for node in lists[1].nodes] == [
        "$.lists[1].objects[0]",
        "$.lists[1].objects[0].children[0]",
    ]


def test_closed_object_lists_reject_duplicate_or_raw_list_names() -> None:
    with pytest.raises(ObjectOperationContractError) as duplicate:
        normalize_object_lists(
            [
                {"name": "Clips", "objects": []},
                {"name": "clips", "objects": []},
            ]
        )
    assert duplicate.value.error_code == "DUPLICATE_LIST"

    with pytest.raises(ObjectOperationContractError) as raw:
        normalize_object_lists([{"name": "@Clips", "objects": []}])
    assert raw.value.error_code == "INVALID_FIELD_NAME"


def test_object_set_result_binds_only_reviewed_dynamic_list_associations() -> None:
    rows = flatten_set_result(
        {
            "objects": [
                {
                    "id": "{OWNER}",
                    "name": "Owner",
                    "@Clips": [
                        {
                            "id": "{CLIP}",
                            "name": "Clip",
                            "children": [{"id": "{CHILD}", "name": "Child"}],
                        }
                    ],
                }
            ]
        },
        allowed_lists=["Clips"],
    )

    assert [(row.name, row.collection) for row in rows] == [
        ("Owner", None),
        ("Clip", "Clips"),
        ("Child", "children"),
    ]

    with pytest.raises(ObjectOperationContractError) as unexpected:
        flatten_set_result(
            {
                "objects": [
                    {
                        "id": "{OWNER}",
                        "name": "Owner",
                        "@Effects": [{"id": "{EFFECT}", "name": "Effect"}],
                    }
                ]
            },
            allowed_lists=["Clips"],
        )
    assert unexpected.value.error_code == "INVALID_RESULT_SHAPE"
