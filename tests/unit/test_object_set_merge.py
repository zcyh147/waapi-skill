from __future__ import annotations

from collections import deque
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    PREPARED_OPERATION_CONTRACT,
    OperationContractError,
    list_operation_specs,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
    verify_prepared_operation,
)


TARGET_ID = "{30000000-0000-0000-0000-000000000001}"
ROOT_COLLISION_ID = "{30000000-0000-0000-0000-000000000002}"
NESTED_COLLISION_ID = "{30000000-0000-0000-0000-000000000003}"
DRIFTED_NESTED_ID = "{30000000-0000-0000-0000-000000000004}"
SECOND_TARGET_ID = "{30000000-0000-0000-0000-000000000005}"
NEW_CHILD_ID = "{30000000-0000-0000-0000-000000000006}"
UNKNOWN_TARGET_ID = "{30000000-0000-0000-0000-000000000007}"
EXTRA_CHILD_ID = "{30000000-0000-0000-0000-000000000008}"
TARGET_PATH = r"\Actor-Mixer Hierarchy\Default Work Unit\SetTarget"
SECOND_TARGET_PATH = r"\Actor-Mixer Hierarchy\Default Work Unit\SecondTarget"
NEW_CHILD_PATH = SECOND_TARGET_PATH + r"\NewChild"
ROOT_COLLISION_PATH = TARGET_PATH + r"\ExistingGroup"
NESTED_COLLISION_PATH = ROOT_COLLISION_PATH + r"\ExistingSound"


class ScriptedReader:
    def __init__(self, responses: Mapping[str, list[Mapping[str, Any]]]) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def __call__(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((uri, dict(args), dict(options)))
        return self.responses[uri].popleft()


def _row(
    object_id: str,
    name: str,
    object_type: str,
    path: str,
    parent: str,
    *,
    notes: str = "before",
) -> dict[str, Any]:
    return {
        "id": object_id,
        "name": name,
        "type": object_type,
        "path": path,
        "parent": {"id": parent},
        "notes": notes,
    }


def _target_row(*, object_type: str = "ActorMixer", path: str = TARGET_PATH) -> dict[str, Any]:
    return _row(
        TARGET_ID,
        path.rsplit("\\", 1)[-1] or "Project",
        object_type,
        path,
        "{default-work-unit}",
    )


def _root_collision_row() -> dict[str, Any]:
    return _row(
        ROOT_COLLISION_ID,
        "ExistingGroup",
        "ActorMixer",
        ROOT_COLLISION_PATH,
        TARGET_ID,
    )


def _nested_collision_row(
    *,
    object_id: str = NESTED_COLLISION_ID,
    object_type: str = "Sound",
) -> dict[str, Any]:
    return _row(
        object_id,
        "ExistingSound",
        object_type,
        NESTED_COLLISION_PATH,
        ROOT_COLLISION_ID,
    )


def _type_catalog() -> dict[str, Any]:
    return {
        "return": [
            {"classId": 1, "name": "ActorMixer", "type": "ActorMixer"},
            {"classId": 2, "name": "Sound", "type": "Sound"},
        ]
    }


def _request(*, target_id: str = TARGET_ID) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "id", "value": target_id},
                    "children": [
                        {
                            "type": "ActorMixer",
                            "name": "ExistingGroup",
                            "children": [
                                {
                                    "type": "Sound",
                                    "name": "ExistingSound",
                                }
                            ],
                        }
                    ],
                }
            ],
            "on_name_conflict": "merge",
        },
    }


def _prepare_merge(*, nested_row: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], ScriptedReader]:
    nested = dict(nested_row) if nested_row is not None else _nested_collision_row()
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [_type_catalog()],
            "ak.wwise.core.object.get": [
                {"return": [_target_row()]},
                {"return": [_root_collision_row()]},
                {"return": [nested]},
                {"return": [nested]},
                {"return": []},
                {"return": [_target_row()]},
                {"return": [_root_collision_row()]},
            ],
        }
    )
    prepared = prepare_operation(
        parse_operation_request(_request()),
        read_call=reader,
    ).as_dict()
    return prepared, reader


def test_object_set_real_property_rejects_integer_outside_finite_waapi_range() -> None:
    property_request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "id", "value": TARGET_ID},
                    "properties": [{"name": "Volume", "value": 2**1024}],
                }
            ],
            "on_name_conflict": "fail",
        },
    }
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [_type_catalog()],
            "ak.wwise.core.object.get": [{"return": [_target_row()]}],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "supports": {"randomizer": True, "rtpc": "Additive"},
                }
            ],
        }
    )

    with pytest.raises(OperationContractError) as invalid:
        prepare_operation(
            parse_operation_request(property_request),
            read_call=reader,
        )

    assert invalid.value.error_code == "INVALID_PROPERTY_VALUE"
    assert [call[0] for call in reader.calls] == [
        "ak.wwise.core.object.getTypes",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.getPropertyInfo",
    ]


def _confirmation_responses(
    *,
    nested_row: Mapping[str, Any] | None = None,
) -> dict[str, list[Mapping[str, Any]]]:
    nested = dict(nested_row) if nested_row is not None else _nested_collision_row()
    return {
        "ak.wwise.core.object.get": [
            {"return": [_target_row()]},
            {"return": [_target_row()]},
            {"return": [_root_collision_row()]},
            {"return": [nested]},
            {"return": []},
            {"return": [_root_collision_row()]},
            {"return": [nested]},
        ]
    }


def _execution_result(*, nested_id: str = NESTED_COLLISION_ID) -> dict[str, Any]:
    return {
        "result": {
            "objects": [
                {
                    "id": TARGET_ID,
                    "name": "SetTarget",
                    "children": [
                        {
                            "id": ROOT_COLLISION_ID,
                            "name": "ExistingGroup",
                            "children": [
                                {
                                    "id": nested_id,
                                    "name": "ExistingSound",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }


def _postverify_responses(*, nested_id: str = NESTED_COLLISION_ID) -> dict[str, list[Mapping[str, Any]]]:
    return {
        "ak.wwise.core.object.get": [
            {"return": [_target_row()]},
            {"return": [_root_collision_row()]},
            {"return": [_nested_collision_row(object_id=nested_id)]},
            {"return": [_root_collision_row()]},
            {"return": [_nested_collision_row(object_id=nested_id)]},
            {"return": []},
        ]
    }


def _sparse_set_prepared(*, include_child: bool) -> dict[str, Any]:
    first_target = {
        "request_path": "$.objects[0]",
        "parent_request_path": None,
        "existing_target": True,
        "target_id": TARGET_ID,
        "requested_name": "SetTarget",
        "requested_type": "ActorMixer",
        "canonical_type": "ActorMixer",
        "notes_supplied": True,
        "requested_notes": "after first",
        "properties": [],
        "references": [],
        "preexisting_children": [],
        "children_request_paths": [],
    }
    second_target = {
        "request_path": "$.objects[1]",
        "parent_request_path": None,
        "existing_target": True,
        "target_id": SECOND_TARGET_ID,
        "requested_name": "SecondTarget",
        "requested_type": "ActorMixer",
        "canonical_type": "ActorMixer",
        "notes_supplied": True,
        "requested_notes": "after second",
        "properties": [],
        "references": [],
        "preexisting_children": [],
        "children_request_paths": ["$.objects[1].children[0]"] if include_child else [],
    }
    nodes = [first_target, second_target]
    if include_child:
        nodes.append(
            {
                "request_path": "$.objects[1].children[0]",
                "parent_request_path": "$.objects[1]",
                "existing_target": False,
                "requested_name": "NewChild",
                "requested_type": "Sound",
                "canonical_type": "Sound",
                "notes_supplied": False,
                "requested_notes": None,
                "properties": [],
                "references": [],
                "expected_path": NEW_CHILD_PATH,
            }
        )
    return {
        "contract": PREPARED_OPERATION_CONTRACT,
        "operation": "object.set",
        "verification_plan": {
            "kind": "object-set-batch",
            "version": "2022.1",
            "on_name_conflict": "fail",
            "nodes": nodes,
        },
    }


def _sparse_target_rows() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        _row(
            TARGET_ID,
            "SetTarget",
            "ActorMixer",
            TARGET_PATH,
            "{default-work-unit}",
            notes="after first",
        ),
        _row(
            SECOND_TARGET_ID,
            "SecondTarget",
            "ActorMixer",
            SECOND_TARGET_PATH,
            "{default-work-unit}",
            notes="after second",
        ),
    )


def _new_child_row(*, object_id: str = NEW_CHILD_ID, name: str = "NewChild") -> dict[str, Any]:
    return _row(
        object_id,
        name,
        "Sound",
        SECOND_TARGET_PATH + "\\" + name,
        SECOND_TARGET_ID,
    )


def _sparse_set_execution_result() -> dict[str, Any]:
    return {
        "result": {
            "objects": [
                {
                    "id": SECOND_TARGET_ID,
                    "name": "SecondTarget",
                    "children": [{"id": NEW_CHILD_ID, "name": "NewChild"}],
                }
            ]
        }
    }


def _sparse_readback_responses(
    *,
    include_child: bool,
    second_target_children: list[Mapping[str, Any]] | None = None,
) -> dict[str, list[Mapping[str, Any]]]:
    first, second = _sparse_target_rows()
    responses: list[Mapping[str, Any]] = [{"return": [first]}, {"return": [second]}]
    if include_child:
        responses.append({"return": [_new_child_row()]})
    responses.extend(
        [
            {"return": []},
            {
                "return": list(
                    second_target_children
                    if second_target_children is not None
                    else ([_new_child_row()] if include_child else [])
                )
            },
        ]
    )
    return {"ak.wwise.core.object.get": responses}


def test_set_field_only_result_may_omit_objects_and_reads_every_sealed_target() -> None:
    reader = ScriptedReader(_sparse_readback_responses(include_child=False))

    verification = verify_prepared_operation(
        _sparse_set_prepared(include_child=False),
        execution_result={"result": {}},
        read_call=reader,
    )

    assert verification.status == "verified"
    assert all(item["passed"] for item in verification.assertions)
    assert [call[1]["from"]["id"][0] for call in reader.calls[:2]] == [
        TARGET_ID,
        SECOND_TARGET_ID,
    ]


def test_set_sparse_result_binds_association_by_sealed_parent_guid_not_response_index() -> None:
    reader = ScriptedReader(_sparse_readback_responses(include_child=True))

    verification = verify_prepared_operation(
        _sparse_set_prepared(include_child=True),
        execution_result=_sparse_set_execution_result(),
        read_call=reader,
    )

    assert verification.status == "verified"
    assert all(item["passed"] for item in verification.assertions)
    assert [call[1]["from"]["id"][0] for call in reader.calls[:3]] == [
        TARGET_ID,
        SECOND_TARGET_ID,
        NEW_CHILD_ID,
    ]
    binding = next(
        item
        for item in verification.assertions
        if item["name"]
        == "sparse object.set result associations bind exactly to the sealed request graph"
    )
    assert binding["evidence"]["bound_request_paths"] == [
        "$.objects[1]",
        "$.objects[1].children[0]",
    ]


@pytest.mark.parametrize(
    ("result", "error_code"),
    [
        (
            {
                "result": {
                    "objects": [
                        {"id": UNKNOWN_TARGET_ID, "name": "UnknownTarget"},
                    ]
                }
            },
            "UNKNOWN_RESULT_ASSOCIATION",
        ),
        (
            {
                "result": {
                    "objects": [
                        {
                            "id": SECOND_TARGET_ID,
                            "name": "SecondTarget",
                            "children": [{"id": NEW_CHILD_ID, "name": "NewChild"}],
                        },
                        {"id": SECOND_TARGET_ID, "name": "SecondTarget"},
                    ]
                }
            },
            "DUPLICATE_RESULT_NODE",
        ),
        ({"result": {}}, "MISSING_RESULT_NODES"),
        (
            {
                "result": {
                    "objects": [
                        {
                            "id": SECOND_TARGET_ID,
                            "name": "SecondTarget",
                            "children": [
                                {"id": NEW_CHILD_ID, "name": "NewChild"},
                                {"id": EXTRA_CHILD_ID, "name": "UnreviewedChild"},
                            ],
                        }
                    ]
                }
            },
            "UNEXPECTED_RESULT_NODE",
        ),
    ],
    ids=["unknown-parent", "duplicate-association", "missing-new-child", "extra-result-child"],
)
def test_set_sparse_result_rejects_unknown_duplicate_missing_and_extra_nodes(
    result: Mapping[str, Any],
    error_code: str,
) -> None:
    verification = verify_prepared_operation(
        _sparse_set_prepared(include_child=True),
        execution_result=result,
        read_call=ScriptedReader(
            _sparse_readback_responses(
                include_child=False,
                second_target_children=[_new_child_row()],
            )
        ),
    )

    assert verification.status == "verification_failed"
    binding = next(
        item
        for item in verification.assertions
        if item["name"]
        == "sparse object.set result associations bind exactly to the sealed request graph"
    )
    assert binding["passed"] is False
    assert binding["evidence"]["error_code"] == error_code


def test_set_postverify_rejects_an_extra_live_child_outside_the_reviewed_closure() -> None:
    verification = verify_prepared_operation(
        _sparse_set_prepared(include_child=True),
        execution_result=_sparse_set_execution_result(),
        read_call=ScriptedReader(
            _sparse_readback_responses(
                include_child=True,
                second_target_children=[
                    _new_child_row(),
                    _new_child_row(object_id=EXTRA_CHILD_ID, name="UnreviewedChild"),
                ],
            )
        ),
    )

    assert verification.status == "verification_failed"
    closure = next(
        item
        for item in verification.assertions
        if item["name"]
        == "$.objects[1] direct child GUID set equals sealed pre-state plus reviewed children"
    )
    assert closure["passed"] is False
    assert closure["evidence"]["actual"] == sorted([NEW_CHILD_ID.casefold(), EXTRA_CHILD_ID.casefold()])


@pytest.mark.parametrize(
    ("target", "error_code"),
    [
        (
            _row(
                TARGET_ID,
                "SampleProject",
                "Project",
                "\\",
                TARGET_ID,
            ),
            "PROTECTED_CREATE_PARENT",
        ),
        (
            _row(
                TARGET_ID,
                "Actor-Mixer Hierarchy",
                "Folder",
                r"\Actor-Mixer Hierarchy",
                "{project}",
            ),
            "PROTECTED_CREATE_PARENT",
        ),
        (
            _row(
                TARGET_ID,
                "LeafSound",
                "Sound",
                r"\Actor-Mixer Hierarchy\Default Work Unit\LeafSound",
                "{default-work-unit}",
            ),
            "INVALID_CREATE_PARENT_TYPE",
        ),
    ],
)
def test_set_rejects_children_under_project_management_or_leaf_targets(
    target: Mapping[str, Any],
    error_code: str,
) -> None:
    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(_request()),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.getTypes": [_type_catalog()],
                    "ak.wwise.core.object.get": [{"return": [target]}],
                }
            ),
        )

    assert rejected.value.error_code == error_code


def test_set_accepts_2025_property_container_target_for_new_sound_child() -> None:
    target_path = r"\Containers\Default Work Unit\SemanticLab\UI\Error"
    target = _target_row(
        object_type="PropertyContainer",
        path=target_path,
    )
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2025.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "id", "value": TARGET_ID},
                    "children": [{"type": "Sound", "name": "Error_Layer"}],
                }
            ],
            "on_name_conflict": "fail",
        },
    }
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {
                            "classId": 524304,
                            "name": "PropertyContainer",
                            "type": "WObject",
                        },
                        {"classId": 65552, "name": "Sound", "type": "WObject"},
                    ]
                }
            ],
            "ak.wwise.core.object.get": [
                {"return": [target]},
                {"return": []},
                {"return": [target]},
                {"return": []},
            ],
        }
    )

    prepared = prepare_operation(
        parse_operation_request(request),
        read_call=reader,
    ).as_dict()

    assert prepared["resolved_roles"]["objects[0].object"]["row"]["type"] == (
        "PropertyContainer"
    )
    child_dispatch = prepared["dispatch"]["args"]["objects"][0]["children"][0]
    assert child_dispatch == {"type": "Sound", "name": "Error_Layer"}
    child_plan = prepared["verification_plan"]["nodes"][1]
    assert child_plan["requested_type"] == "Sound"
    assert child_plan["canonical_type"] == "Sound"


@pytest.mark.parametrize(
    "version",
    ["2022.1", "2023.1", "2024.1", "2025.1"],
)
@pytest.mark.parametrize(
    ("parent_type", "child_type", "hierarchy"),
    [
        ("SwitchGroup", "Switch", "Switches"),
        ("StateGroup", "State", "States"),
    ],
)
def test_set_accepts_closed_game_sync_children_across_supported_versions(
    version: str,
    parent_type: str,
    child_type: str,
    hierarchy: str,
) -> None:
    target_path = rf"\{hierarchy}\Default Work Unit\Reviewed{parent_type}"
    target = _target_row(object_type=parent_type, path=target_path)
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "id", "value": TARGET_ID},
                    "children": [
                        {"type": child_type, "name": f"Reviewed{child_type}"}
                    ],
                }
            ],
            "on_name_conflict": "fail",
        },
    }
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {"classId": 1, "name": child_type, "type": "WObject"}
                    ]
                }
            ],
            "ak.wwise.core.object.get": [
                {"return": [target]},
                {"return": []},
                {"return": [target]},
                {"return": []},
            ],
        }
    )

    prepared = prepare_operation(
        parse_operation_request(request),
        read_call=reader,
    ).as_dict()

    assert prepared["resolved_roles"]["objects[0].object"]["row"]["type"] == (
        parent_type
    )
    child_dispatch = prepared["dispatch"]["args"]["objects"][0]["children"][0]
    assert child_dispatch == {
        "type": child_type,
        "name": f"Reviewed{child_type}",
    }


@pytest.mark.parametrize(
    ("parent_type", "child_type", "allowed_child_type"),
    [
        ("SwitchGroup", "State", "Switch"),
        ("StateGroup", "Switch", "State"),
    ],
)
def test_set_rejects_unreviewed_game_sync_children(
    parent_type: str,
    child_type: str,
    allowed_child_type: str,
) -> None:
    hierarchy = "Switches" if parent_type == "SwitchGroup" else "States"
    target = _target_row(
        object_type=parent_type,
        path=rf"\{hierarchy}\Default Work Unit\Reviewed{parent_type}",
    )
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "id", "value": TARGET_ID},
                    "children": [{"type": child_type, "name": "WrongValue"}],
                }
            ],
            "on_name_conflict": "fail",
        },
    }

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(request),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.getTypes": [_type_catalog()],
                    "ak.wwise.core.object.get": [{"return": [target]}],
                }
            ),
        )

    assert rejected.value.error_code == "INVALID_CREATE_CHILD_TYPE_FOR_PARENT"
    assert rejected.value.details["parent_type"] == parent_type
    assert rejected.value.details["invalid_child_types"] == [child_type]
    assert rejected.value.details["allowed_child_types"] == [allowed_child_type]


def test_object_set_schema_discloses_closed_bus_and_game_sync_child_pairs() -> None:
    spec = {item.name: item.as_dict() for item in list_operation_specs()}["object.set"]
    assert spec["parent_child_contract"] == {
        "AuxBus": ["AuxBus", "Bus"],
        "Bus": ["AuxBus", "Bus"],
        "StateGroup": ["State"],
        "SwitchGroup": ["Switch"],
    }


@pytest.mark.parametrize(
    ("child_type", "allowed_parent_type"),
    [("State", "StateGroup"), ("Switch", "SwitchGroup")],
)
def test_set_rejects_game_sync_value_under_general_target(
    child_type: str,
    allowed_parent_type: str,
) -> None:
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "id", "value": TARGET_ID},
                    "children": [{"type": child_type, "name": "MisplacedValue"}],
                }
            ],
            "on_name_conflict": "fail",
        },
    }

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(request),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.getTypes": [_type_catalog()],
                    "ak.wwise.core.object.get": [{"return": [_target_row()]}],
                }
            ),
        )

    assert rejected.value.error_code == "INVALID_CREATE_PARENT_TYPE_FOR_CHILD"
    assert rejected.value.details["actual_parent_type"] == "ActorMixer"
    assert rejected.value.details["child_type"] == child_type
    assert rejected.value.details["allowed_parent_types"] == [allowed_parent_type]


@pytest.mark.parametrize(
    ("group_type", "child_type", "hierarchy"),
    [
        ("SwitchGroup", "Switch", "Switches"),
        ("StateGroup", "State", "States"),
    ],
)
def test_set_accepts_closed_game_sync_pairs_inside_recursive_children(
    group_type: str,
    child_type: str,
    hierarchy: str,
) -> None:
    target_path = rf"\{hierarchy}\Default Work Unit"
    target = _target_row(object_type="WorkUnit", path=target_path)
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": {"kind": "id", "value": TARGET_ID},
                    "children": [
                        {
                            "type": group_type,
                            "name": f"Reviewed{group_type}",
                            "children": [
                                {
                                    "type": child_type,
                                    "name": f"Reviewed{child_type}",
                                }
                            ],
                        }
                    ],
                }
            ],
            "on_name_conflict": "fail",
        },
    }
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {"classId": 1, "name": group_type, "type": "WObject"},
                        {"classId": 2, "name": child_type, "type": "WObject"},
                    ]
                }
            ],
            "ak.wwise.core.object.get": [
                {"return": [target]},
                {"return": []},
                {"return": [target]},
                {"return": []},
            ],
        }
    )

    prepared = prepare_operation(
        parse_operation_request(request),
        read_call=reader,
    ).as_dict()

    assert prepared["dispatch"]["args"]["objects"][0]["children"] == [
        {
            "type": group_type,
            "name": f"Reviewed{group_type}",
            "children": [
                {"type": child_type, "name": f"Reviewed{child_type}"}
            ],
        }
    ]


def test_set_merge_snapshots_every_nested_collision_and_verifies_the_confirmed_result() -> None:
    prepared, preview_reader = _prepare_merge()

    path_snapshots = prepared["pre_state"]["object_graph_guard"]["path_snapshots"]
    assert [row["path"] for row in path_snapshots] == [
        ROOT_COLLISION_PATH,
        NESTED_COLLISION_PATH,
    ]
    assert [row["rows"][0]["id"] for row in path_snapshots] == [
        ROOT_COLLISION_ID,
        NESTED_COLLISION_ID,
    ]
    child_specs = prepared["verification_plan"]["nodes"][1:]
    assert [row["expected_path"] for row in child_specs] == [
        ROOT_COLLISION_PATH,
        NESTED_COLLISION_PATH,
    ]
    assert [row["preexisting_id"] for row in child_specs] == [
        ROOT_COLLISION_ID,
        NESTED_COLLISION_ID,
    ]
    preview_path_reads = [
        call[1]["from"]["path"][0]
        for call in preview_reader.calls
        if call[0] == "ak.wwise.core.object.get" and "path" in call[1].get("from", {})
    ]
    assert preview_path_reads == [ROOT_COLLISION_PATH, NESTED_COLLISION_PATH]

    confirmation = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(_confirmation_responses()),
    )
    assert confirmation["status"] == "valid"
    assert all(item["passed"] for item in confirmation["assertions"])

    verified = verify_prepared_operation(
        prepared,
        execution_result=_execution_result(),
        read_call=ScriptedReader(_postverify_responses()),
    )
    assert verified.status == "verified"
    assert all(item["passed"] for item in verified.assertions)
    assert {
        item["name"]
        for item in verified.assertions
        if "merge retained the pre-existing GUID" in item["name"]
    } == {
        "$.objects[0].children[0] merge retained the pre-existing GUID",
        "$.objects[0].children[0].children[0] merge retained the pre-existing GUID",
    }


@pytest.mark.parametrize(
    "nested_drift",
    [
        _nested_collision_row(object_id=DRIFTED_NESTED_ID),
        _nested_collision_row(object_type="ActorMixer"),
    ],
    ids=["guid-drift", "type-drift"],
)
def test_set_merge_confirmation_replays_nested_collision_guid_and_type(
    nested_drift: Mapping[str, Any],
) -> None:
    prepared, _ = _prepare_merge()

    confirmation = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(_confirmation_responses(nested_row=nested_drift)),
    )

    assert confirmation["status"] == "repreview_required"
    nested_assertion = next(
        item
        for item in confirmation["assertions"]
        if item["name"] == "object graph path snapshot 1 unchanged"
    )
    assert nested_assertion["passed"] is False
    assert nested_assertion["evidence"]["path"] == NESTED_COLLISION_PATH


def test_set_merge_rejects_a_nested_collision_with_the_wrong_type_during_preview() -> None:
    with pytest.raises(OperationContractError) as rejected:
        _prepare_merge(nested_row=_nested_collision_row(object_type="ActorMixer"))

    assert rejected.value.error_code == "INVALID_TARGET_TYPE"
    assert rejected.value.details["path"] == NESTED_COLLISION_PATH


def test_set_merge_postverify_fails_if_nested_merge_returns_a_different_guid() -> None:
    prepared, _ = _prepare_merge()
    confirmation = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(_confirmation_responses()),
    )
    assert confirmation["status"] == "valid"

    verification = verify_prepared_operation(
        prepared,
        execution_result=_execution_result(nested_id=DRIFTED_NESTED_ID),
        read_call=ScriptedReader(_postverify_responses(nested_id=DRIFTED_NESTED_ID)),
    )

    assert verification.status == "verification_failed"
    binding = next(
        item
        for item in verification.assertions
        if item["name"]
        == "sparse object.set result associations bind exactly to the sealed request graph"
    )
    assert binding["passed"] is False
    assert binding["evidence"]["error_code"] == "RESULT_IDENTITY_MISMATCH"


def test_set_rejects_empty_duplicate_descriptors_and_a_129_node_batch() -> None:
    empty = _request()
    empty["arguments"]["objects"] = []
    with pytest.raises(OperationContractError) as empty_error:
        parse_operation_request(empty)
    assert empty_error.value.error_code == "INVALID_SCOPE"

    duplicate = _request()
    duplicate["arguments"] = {
        "objects": [
            {"object": {"kind": "id", "value": TARGET_ID}, "notes": "first"},
            {"object": {"kind": "id", "value": TARGET_ID}, "notes": "second"},
        ]
    }
    with pytest.raises(OperationContractError) as duplicate_error:
        parse_operation_request(duplicate)
    assert duplicate_error.value.error_code == "DUPLICATE_TARGET"

    oversized = _request()
    oversized["arguments"] = {
        "objects": [
            {
                "object": {"kind": "id", "value": f"{{30000000-0000-0000-0000-{target_index + 10:012d}}}"},
                "children": [
                    {"type": "Sound", "name": f"Child_{target_index}_{index}"}
                    for index in range(32 if target_index == 0 else 31)
                ],
            }
            for target_index in range(4)
        ]
    }
    with pytest.raises(OperationContractError) as oversized_error:
        parse_operation_request(oversized)
    assert oversized_error.value.error_code == "NODE_LIMIT_EXCEEDED"
    assert oversized_error.value.details == {"count": 129, "limit": 128}


def test_set_rejects_distinct_descriptors_that_resolve_to_the_same_live_guid() -> None:
    request = _request()
    request["arguments"] = {
        "objects": [
            {"object": {"kind": "id", "value": TARGET_ID}, "notes": "first"},
            {"object": {"kind": "path", "value": TARGET_PATH}, "notes": "second"},
        ]
    }
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [_type_catalog()],
            "ak.wwise.core.object.get": [
                {"return": [_target_row()]},
                {"return": [_target_row()]},
                {"return": []},
                {"return": [_target_row()]},
            ],
        }
    )

    with pytest.raises(OperationContractError) as duplicate:
        prepare_operation(parse_operation_request(request), read_call=reader)

    assert duplicate.value.error_code == "DUPLICATE_TARGET"
    assert duplicate.value.details["previous_index"] == 0
