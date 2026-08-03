from __future__ import annotations

from collections import deque
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    OperationContractError,
    list_operation_specs,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
    verify_prepared_operation,
)


PARENT_ID = "{10000000-0000-0000-0000-000000000001}"
OWNED_ROOT_ID = "{10000000-0000-0000-0000-000000000002}"
OLD_ROOT_ID = "{10000000-0000-0000-0000-000000000003}"
OLD_GROUP_ID = "{10000000-0000-0000-0000-000000000004}"
OLD_SOUND_ID = "{10000000-0000-0000-0000-000000000005}"
SIBLING_ID = "{10000000-0000-0000-0000-000000000006}"
NEW_ROOT_ID = "{20000000-0000-0000-0000-000000000001}"
NEW_GROUP_ID = "{20000000-0000-0000-0000-000000000002}"
NEW_SOUND_ID = "{20000000-0000-0000-0000-000000000003}"

OWNED_ROOT_PATH = r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticCases"
PARENT_PATH = OWNED_ROOT_PATH + r"\Generated"
COLLISION_PATH = PARENT_PATH + r"\Prototype_Footsteps"
OLD_GROUP_PATH = COLLISION_PATH + r"\Legacy"
OLD_SOUND_PATH = OLD_GROUP_PATH + r"\Old_Step"
NEW_GROUP_PATH = COLLISION_PATH + r"\Boots"
NEW_SOUND_PATH = NEW_GROUP_PATH + r"\Boot_01"


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


def _parent_row(*, path: str = PARENT_PATH) -> dict[str, Any]:
    return _row(PARENT_ID, "Generated", "ActorMixer", path, OWNED_ROOT_ID)


def _owned_root_row(*, path: str = OWNED_ROOT_PATH) -> dict[str, Any]:
    return _row(
        OWNED_ROOT_ID,
        path.rsplit("\\", 1)[-1],
        "ActorMixer",
        path,
        "{default-work-unit}",
    )


def _old_root_row(*, path: str = COLLISION_PATH) -> dict[str, Any]:
    return _row(OLD_ROOT_ID, "Prototype_Footsteps", "ActorMixer", path, PARENT_ID)


def _old_descendants() -> list[dict[str, Any]]:
    return [
        {"id": OLD_GROUP_ID, "path": OLD_GROUP_PATH},
        {"id": OLD_SOUND_ID, "path": OLD_SOUND_PATH},
    ]


def _parent_children() -> list[dict[str, Any]]:
    return [
        _old_root_row(),
        _row(SIBLING_ID, "Keep_Me", "Sound", PARENT_PATH + r"\Keep_Me", PARENT_ID),
    ]


def _arguments() -> dict[str, Any]:
    return {
        "parent": {"kind": "id", "value": PARENT_ID},
        "type": "ActorMixer",
        "name": "Prototype_Footsteps",
        "notes": "new disposable prototype",
        "children": [
            {
                "type": "RandomSequenceContainer",
                "name": "Boots",
                "children": [{"type": "Sound", "name": "Boot_01"}],
            }
        ],
        "on_name_conflict": "replace",
        "replace_owned_root": {"kind": "id", "value": OWNED_ROOT_ID},
    }


def _request(
    arguments: Mapping[str, Any],
    *,
    version: str = "2022.1",
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "object.create",
        "arguments": dict(arguments),
    }


def _prepare_replace() -> dict[str, Any]:
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [_parent_row()]},
                {"return": [_owned_root_row()]},
                {"return": [_old_root_row()]},
                {"return": _old_descendants()},
                {"return": _parent_children()},
            ],
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {"classId": 1, "name": "ActorMixer", "type": "WObject"},
                        {
                            "classId": 2,
                            "name": "RandomSequenceContainer",
                            "type": "WObject",
                        },
                        {"classId": 3, "name": "Sound", "type": "WObject"},
                    ]
                }
            ],
        }
    )
    prepared = prepare_operation(
        parse_operation_request(_request(_arguments())),
        read_call=reader,
    ).as_dict()
    assert reader.calls[4] == (
        "ak.wwise.core.object.get",
        {
            "from": {"id": [OLD_ROOT_ID]},
            "transform": [{"select": ["descendants"]}],
        },
        {"return": ["id", "path"]},
    )
    return prepared


def _role_guard_responses(*, descendants: list[dict[str, Any]] | None = None) -> dict[str, list[Mapping[str, Any]]]:
    return {
        "ak.wwise.core.object.get": [
            {"return": [_parent_row(), _owned_root_row(), _old_root_row()]},
            {"return": _parent_children()},
            {"return": [_old_root_row()]},
            {"return": [{"id": OLD_ROOT_ID, "path": COLLISION_PATH}]},
            {"return": _old_descendants() if descendants is None else descendants},
        ]
    }


def _new_rows() -> list[dict[str, Any]]:
    return [
        _row(
            NEW_ROOT_ID,
            "Prototype_Footsteps",
            "ActorMixer",
            COLLISION_PATH,
            PARENT_ID,
            notes="new disposable prototype",
        ),
        _row(
            NEW_GROUP_ID,
            "Boots",
            "RandomSequenceContainer",
            NEW_GROUP_PATH,
            NEW_ROOT_ID,
        ),
        _row(NEW_SOUND_ID, "Boot_01", "Sound", NEW_SOUND_PATH, NEW_GROUP_ID),
    ]


def _execution_result() -> dict[str, Any]:
    return {
        "result": {
            "id": NEW_ROOT_ID,
            "name": "Prototype_Footsteps",
            "children": [
                {
                    "id": NEW_GROUP_ID,
                    "name": "Boots",
                    "children": [{"id": NEW_SOUND_ID, "name": "Boot_01"}],
                }
            ],
        }
    }


def test_public_replace_contract_is_conditional_and_closed() -> None:
    spec = {item.name: item.as_dict() for item in list_operation_specs()}["object.create"]
    assert spec["argument_contract"]["properties"]["on_name_conflict"]["enum"] == [
        "fail",
        "rename",
        "merge",
        "replace",
    ]
    assert spec["identity_contract"]["argument_fields"] == ["parent", "replace_owned_root"]
    replace_description = spec["argument_contract"]["properties"]["replace_owned_root"]["description"]
    assert "strict ancestor" in replace_description
    assert "not the object being replaced" in replace_description
    assert "parent and replace_owned_root are normally both P" in replace_description

    missing_owner = _arguments()
    missing_owner.pop("replace_owned_root")
    with pytest.raises(OperationContractError) as missing:
        parse_operation_request(_request(missing_owner))
    assert missing.value.error_code == "REPLACE_OWNERSHIP_REQUIRED"

    unexpected_owner = _arguments()
    unexpected_owner["on_name_conflict"] = "fail"
    with pytest.raises(OperationContractError) as unexpected:
        parse_operation_request(_request(unexpected_owner))
    assert unexpected.value.error_code == "REPLACE_OWNERSHIP_NOT_ALLOWED"

    parsed = parse_operation_request(_request(_arguments()))
    assert parsed.arguments["replace_owned_root"] == {"kind": "id", "value": OWNED_ROOT_ID}


def test_public_create_schema_exposes_merge_query_and_2025_type_alias() -> None:
    spec = {item.name: item.as_dict() for item in list_operation_specs()}[
        "object.create"
    ]
    type_description = spec["argument_contract"]["properties"]["type"][
        "description"
    ]
    constraints = " ".join(spec["constraints"])

    assert "Wwise 2025.1 reflects an Actor Mixer as PropertyContainer" in (
        type_description
    )
    assert "object.create request token remains ActorMixer" in type_description
    assert "operation-schema must be followed by one exact-path query-object" in (
        constraints
    )
    assert "returning id, name, type, and path before preview" in constraints
    assert (
        "Wwise 2025.1 PropertyContainer readback maps to the ActorMixer request token"
        in constraints
    )


@pytest.mark.parametrize(
    ("parent_type", "parent_path", "parent_name"),
    [
        (
            "WorkUnit",
            r"\Actor-Mixer Hierarchy\Default Work Unit",
            "Default Work Unit",
        ),
        (
            "Folder",
            r"\Actor-Mixer Hierarchy\Default Work Unit\ReviewedFolder",
            "ReviewedFolder",
        ),
        ("ActorMixer", PARENT_PATH, "Generated"),
    ],
)
def test_create_accepts_only_reviewed_writable_parent_categories(
    parent_type: str,
    parent_path: str,
    parent_name: str,
) -> None:
    parent = _row(
        PARENT_ID,
        parent_name,
        parent_type,
        parent_path,
        "{reviewed-parent}",
    )
    arguments = {
        "parent": {"kind": "id", "value": PARENT_ID},
        "type": "ActorMixer",
        "name": "ClosedCreate",
    }
    prepared = prepare_operation(
        parse_operation_request(_request(arguments)),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [parent]},
                    {"return": []},
                    {"return": []},
                ],
                "ak.wwise.core.object.getTypes": [
                    {"return": [{"classId": 1, "name": "ActorMixer", "type": "ActorMixer"}]}
                ],
            }
        ),
    ).as_dict()

    assert prepared["resolved_roles"]["parent"]["row"]["type"] == parent_type
    assert prepared["dispatch"]["args"]["parent"] == PARENT_ID


def test_create_accepts_2025_property_container_parent_but_dispatches_actor_mixer() -> None:
    parent_path = r"\Containers\Default Work Unit\SemanticLab\Weapons"
    parent = _row(
        PARENT_ID,
        "Weapons",
        "PropertyContainer",
        parent_path,
        "{default-work-unit}",
    )
    arguments = {
        "parent": {"kind": "id", "value": PARENT_ID},
        "type": "ActorMixer",
        "name": "Impact_Library",
    }

    prepared = prepare_operation(
        parse_operation_request(_request(arguments, version="2025.1")),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [parent]},
                    {"return": []},
                    {"return": []},
                ],
                "ak.wwise.core.object.getTypes": [
                    {
                        "return": [
                            {
                                "classId": 524304,
                                "name": "PropertyContainer",
                                "type": "WObject",
                            }
                        ]
                    }
                ],
            }
        ),
    ).as_dict()

    assert prepared["resolved_roles"]["parent"]["row"]["type"] == (
        "PropertyContainer"
    )
    assert prepared["dispatch"]["args"]["type"] == "ActorMixer"
    assert prepared["verification_plan"]["nodes"][0]["requested_type"] == (
        "ActorMixer"
    )
    assert prepared["verification_plan"]["nodes"][0]["canonical_type"] == (
        "ActorMixer"
    )
    assert prepared["verification_plan"]["nodes"][0]["class_id"] == 524304


@pytest.mark.parametrize(
    ("version", "parent_type"),
    [
        ("2022.1", "PropertyContainer"),
        ("2025.1", "FutureContainer"),
    ],
)
def test_create_reflected_parent_alias_is_version_bound_and_unknown_types_fail(
    version: str,
    parent_type: str,
) -> None:
    parent_root = (
        r"\Containers"
        if version == "2025.1"
        else r"\Actor-Mixer Hierarchy"
    )
    parent = _row(
        PARENT_ID,
        "Parent",
        parent_type,
        parent_root + r"\Default Work Unit\Parent",
        "{default-work-unit}",
    )
    arguments = {
        "parent": {"kind": "id", "value": PARENT_ID},
        "type": "ActorMixer",
        "name": "ClosedCreate",
    }

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(_request(arguments, version=version)),
            read_call=ScriptedReader(
                {"ak.wwise.core.object.get": [{"return": [parent]}]}
            ),
        )

    assert rejected.value.error_code == "INVALID_CREATE_PARENT_TYPE"
    assert rejected.value.details["actual_type"] == parent_type
    assert rejected.value.details["version"] == version
    assert (
        "PropertyContainer" in rejected.value.details["allowed_types"]
    ) is (version == "2025.1")


@pytest.mark.parametrize(
    ("parent", "error_code"),
    [
        (
            _row(
                PARENT_ID,
                "Actor-Mixer Hierarchy",
                "Folder",
                r"\Actor-Mixer Hierarchy",
                "{project}",
            ),
            "PROTECTED_CREATE_PARENT",
        ),
        (
            _row(
                PARENT_ID,
                "LeafSound",
                "Sound",
                r"\Actor-Mixer Hierarchy\Default Work Unit\LeafSound",
                "{default-work-unit}",
            ),
            "INVALID_CREATE_PARENT_TYPE",
        ),
    ],
)
def test_create_rejects_protected_or_unreviewed_parent(
    parent: Mapping[str, Any],
    error_code: str,
) -> None:
    arguments = {
        "parent": {"kind": "id", "value": PARENT_ID},
        "type": "ActorMixer",
        "name": "ClosedCreate",
    }
    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(_request(arguments)),
            read_call=ScriptedReader({"ak.wwise.core.object.get": [{"return": [parent]}]}),
        )
    assert rejected.value.error_code == error_code


def test_replace_preview_binds_owned_scope_full_old_subtree_and_discard_only_cleanup() -> None:
    prepared = _prepare_replace()

    # Wwise 2022.1 getTypes reports WObject as the shared base type for these
    # concrete classes.  The create payload must retain their metadata names.
    dispatch = prepared["dispatch"]["args"]
    assert dispatch["type"] == "ActorMixer"
    assert dispatch["children"][0]["type"] == "RandomSequenceContainer"
    assert dispatch["children"][0]["children"][0]["type"] == "Sound"
    assert prepared["dispatch"]["args"]["onNameConflict"] == "replace"
    assert "replace_owned_root" not in prepared["dispatch"]["args"]
    assert prepared["resolved_roles"]["replace_owned_root"]["object"] == OWNED_ROOT_ID
    assert prepared["resolved_roles"]["replace_collision"]["object"] == OLD_ROOT_ID
    snapshot = prepared["pre_state"]["object_graph_guard"]["subtree_snapshots"][0]
    assert snapshot == {
        "root_id": OLD_ROOT_ID,
        "root_path": COLLISION_PATH,
        "fields": ["id", "path"],
        "rows": [
            {"id": OLD_ROOT_ID, "path": COLLISION_PATH},
            {"id": OLD_GROUP_ID, "path": OLD_GROUP_PATH},
            {"id": OLD_SOUND_ID, "path": OLD_SOUND_PATH},
        ],
    }
    assert [row["expected_path"] for row in prepared["verification_plan"]["nodes"]] == [
        COLLISION_PATH,
        NEW_GROUP_PATH,
        NEW_SOUND_PATH,
    ]
    assert prepared["cleanup"] == {
        "kind": "discard-case-owned-project-copy-after-replace",
        "description": "The replaced subtree is not reconstructed; discard the case-owned project copy after collecting evidence.",
        "automatic": False,
        "automatic_retry": False,
        "replace_owned_root_id": OWNED_ROOT_ID,
        "irreversible_preexisting_changes": True,
    }


def test_replace_materializes_the_campaign_nested_tree_with_concrete_get_types_names() -> None:
    """Keep the 2022.1 WObject-base-class payload that exposed OBJ22-F-CREATE-05."""

    arguments = _arguments()
    arguments["children"] = [
        {
            "type": "RandomSequenceContainer",
            "name": category,
            "children": [
                {"type": "Sound", "name": "Walk"},
                {"type": "Sound", "name": "Run"},
            ],
        }
        for category in ("Sneakers", "Boots", "Barefoot")
    ]
    prepared = prepare_operation(
        parse_operation_request(_request(arguments)),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [_parent_row()]},
                    {"return": [_owned_root_row()]},
                    {"return": [_old_root_row()]},
                    {"return": _old_descendants()},
                    {"return": _parent_children()},
                ],
                "ak.wwise.core.object.getTypes": [
                    {
                        "return": [
                            {"classId": 1, "name": "ActorMixer", "type": "WObject"},
                            {
                                "classId": 2,
                                "name": "RandomSequenceContainer",
                                "type": "WObject",
                            },
                            {"classId": 3, "name": "Sound", "type": "WObject"},
                        ]
                    }
                ],
            }
        ),
    ).as_dict()

    dispatch = prepared["dispatch"]["args"]
    assert dispatch["type"] == "ActorMixer"
    assert dispatch["children"] == [
        {
            "type": "RandomSequenceContainer",
            "name": category,
            "children": [
                {"type": "Sound", "name": "Walk"},
                {"type": "Sound", "name": "Run"},
            ],
        }
        for category in ("Sneakers", "Boots", "Barefoot")
    ]
    assert all(node["canonical_type"] != "WObject" for node in prepared["verification_plan"]["nodes"])


@pytest.mark.parametrize(
    ("parent_path", "owned_path"),
    [
        (
            r"\Actor-Mixer Hierarchy\Default Work Unit\OtherCase\Generated",
            OWNED_ROOT_PATH,
        ),
        (
            r"\Actor-Mixer Hierarchy\Default Work Unit",
            r"\Actor-Mixer Hierarchy\Default Work Unit\Prototype_Footsteps",
        ),
    ],
)
def test_replace_rejects_collision_outside_or_equal_to_owned_root(
    parent_path: str,
    owned_path: str,
) -> None:
    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(_request(_arguments())),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.get": [
                        {"return": [_parent_row(path=parent_path)]},
                        {"return": [_owned_root_row(path=owned_path)]},
                    ],
                    "ak.wwise.core.object.getTypes": [
                        {
                            "return": [
                                {"classId": 1, "name": "ActorMixer", "type": "ActorMixer"},
                                {
                                    "classId": 2,
                                    "name": "RandomSequenceContainer",
                                    "type": "RandomSequenceContainer",
                                },
                                {"classId": 3, "name": "Sound", "type": "Sound"},
                            ]
                        }
                    ],
                }
            ),
        )
    assert rejected.value.error_code == "REPLACE_TARGET_OUTSIDE_OWNED_ROOT"


def test_replace_rejects_protected_owned_root_before_collision_reads() -> None:
    protected = _row(
        OWNED_ROOT_ID,
        "Default Work Unit",
        "WorkUnit",
        r"\Actor-Mixer Hierarchy\Default Work Unit",
        "{actor-mixer-root}",
    )
    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(_request(_arguments())),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.get": [
                        {"return": [_parent_row()]},
                        {"return": [protected]},
                    ]
                }
            ),
        )
    assert rejected.value.error_code == "PROTECTED_REPLACE_ROOT"


@pytest.mark.parametrize(
    ("collision_rows", "error_code"),
    [
        ([], "REPLACE_TARGET_REQUIRED"),
        ([_old_root_row(), _old_root_row()], "AMBIGUOUS_IDENTITY"),
    ],
)
def test_replace_requires_one_exact_existing_collision(
    collision_rows: list[dict[str, Any]],
    error_code: str,
) -> None:
    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(_request(_arguments())),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.get": [
                        {"return": [_parent_row()]},
                        {"return": [_owned_root_row()]},
                        {"return": collision_rows},
                    ],
                    "ak.wwise.core.object.getTypes": [
                        {
                            "return": [
                                {"classId": 1, "name": "ActorMixer", "type": "ActorMixer"},
                                {
                                    "classId": 2,
                                    "name": "RandomSequenceContainer",
                                    "type": "RandomSequenceContainer",
                                },
                                {"classId": 3, "name": "Sound", "type": "Sound"},
                            ]
                        }
                    ],
                }
            ),
        )
    assert rejected.value.error_code == error_code


def test_replace_rejects_an_old_subtree_too_large_to_snapshot_completely() -> None:
    descendants = [
        {"id": f"old-node-{index}", "path": COLLISION_PATH + f"\\Old_{index:03d}"}
        for index in range(128)
    ]
    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(_request(_arguments())),
            read_call=ScriptedReader(
                {
                    "ak.wwise.core.object.get": [
                        {"return": [_parent_row()]},
                        {"return": [_owned_root_row()]},
                        {"return": [_old_root_row()]},
                        {"return": descendants},
                    ],
                    "ak.wwise.core.object.getTypes": [
                        {
                            "return": [
                                {"classId": 1, "name": "ActorMixer", "type": "ActorMixer"},
                                {
                                    "classId": 2,
                                    "name": "RandomSequenceContainer",
                                    "type": "RandomSequenceContainer",
                                },
                                {"classId": 3, "name": "Sound", "type": "Sound"},
                            ]
                        }
                    ],
                }
            ),
        )
    assert rejected.value.error_code == "REPLACE_SNAPSHOT_LIMIT_EXCEEDED"
    assert rejected.value.details == {
        "count": 129,
        "limit": 128,
        "root_path": COLLISION_PATH,
    }


def test_replace_confirmation_rechecks_the_complete_old_subtree_without_drift() -> None:
    prepared = _prepare_replace()
    valid = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(_role_guard_responses()),
    )
    assert valid["status"] == "valid"

    drifted_descendants = [
        *_old_descendants(),
        {"id": "{10000000-0000-0000-0000-000000000099}", "path": COLLISION_PATH + r"\Late_Addition"},
    ]
    drifted = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(_role_guard_responses(descendants=drifted_descendants)),
    )
    assert drifted["status"] == "repreview_required"
    assertion = next(
        item
        for item in drifted["assertions"]
        if item["name"] == "object replace subtree GUID/path snapshot 0 unchanged"
    )
    assert assertion["passed"] is False


def test_replace_verifier_requires_exact_new_topology_and_every_old_guid_absent() -> None:
    prepared = _prepare_replace()
    root, group, sound = _new_rows()
    verified = verify_prepared_operation(
        prepared,
        execution_result=_execution_result(),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [root]},
                    {"return": [group]},
                    {"return": [sound]},
                    {"return": [{"id": NEW_GROUP_ID, "path": NEW_GROUP_PATH}]},
                    {"return": [{"id": NEW_SOUND_ID, "path": NEW_SOUND_PATH}]},
                    {"return": []},
                    {"return": []},
                    {"return": []},
                    {"return": []},
                ]
            }
        ),
    )

    assert verified.status == "verified"
    assert next(
        item for item in verified.assertions if item["name"] == "every replaced subtree GUID is absent after object.create"
    )["passed"] is True
    old_guid_readbacks = [
        item
        for item in verified.readbacks
        if str(item.get("role", "")).startswith("object-create-replaced-guid-absence[")
    ]
    assert [item["args"] for item in old_guid_readbacks] == [
        {"from": {"id": [OLD_ROOT_ID]}},
        {"from": {"id": [OLD_GROUP_ID]}},
        {"from": {"id": [OLD_SOUND_ID]}},
    ]
    assert [item["expected_absent"] for item in old_guid_readbacks] == [
        {"id": OLD_ROOT_ID, "path": COLLISION_PATH},
        {"id": OLD_GROUP_ID, "path": OLD_GROUP_PATH},
        {"id": OLD_SOUND_ID, "path": OLD_SOUND_PATH},
    ]
    old_guid_assertions = [
        item
        for item in verified.assertions
        if item["name"].startswith("replaced subtree GUID ")
    ]
    assert len(old_guid_assertions) == 3
    assert all(item["passed"] for item in old_guid_assertions)
    topology_assertions = [
        item
        for item in verified.assertions
        if item["name"].endswith("direct child GUID set is exactly the new reviewed topology")
    ]
    assert len(topology_assertions) == 3
    assert all(item["passed"] for item in topology_assertions)


def test_replace_verifier_fails_for_surviving_old_guid_or_extra_new_child() -> None:
    prepared = _prepare_replace()
    root, group, sound = _new_rows()
    extra_id = "{20000000-0000-0000-0000-000000000099}"
    failed = verify_prepared_operation(
        prepared,
        execution_result=_execution_result(),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [root]},
                    {"return": [group]},
                    {"return": [sound]},
                    {
                        "return": [
                            {"id": NEW_GROUP_ID, "path": NEW_GROUP_PATH},
                            {"id": extra_id, "path": COLLISION_PATH + r"\Unexpected"},
                        ]
                    },
                    {"return": [{"id": NEW_SOUND_ID, "path": NEW_SOUND_PATH}]},
                    {"return": []},
                    {"return": []},
                    {"return": []},
                    {"return": [{"id": OLD_SOUND_ID, "path": OLD_SOUND_PATH}]},
                ]
            }
        ),
    )

    assert failed.status == "verification_failed"
    assert next(
        item for item in failed.assertions if item["name"] == "$ direct child GUID set is exactly the new reviewed topology"
    )["passed"] is False
    assert next(
        item for item in failed.assertions if item["name"] == "every replaced subtree GUID is absent after object.create"
    )["passed"] is False
    old_guid_assertions = [
        item
        for item in failed.assertions
        if item["name"].startswith("replaced subtree GUID ")
    ]
    assert [item["passed"] for item in old_guid_assertions] == [True, True, False]
    assert old_guid_assertions[-1]["evidence"] == {
        "old_row": {"id": OLD_SOUND_ID, "path": OLD_SOUND_PATH},
        "remaining_rows": [{"id": OLD_SOUND_ID, "path": OLD_SOUND_PATH}],
    }
