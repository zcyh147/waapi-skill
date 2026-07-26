from __future__ import annotations

from collections import deque
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    OperationContractError,
    parse_operation_request,
    prepare_operation,
)


PARENT_ID = "{41000000-0000-0000-0000-000000000001}"
TARGET_ID = "{41000000-0000-0000-0000-000000000002}"
BUS_ID = "{41000000-0000-0000-0000-000000000003}"
PARENT_PATH = r"\Actor-Mixer Hierarchy\Default Work Unit\SemanticLab\Characters"
TARGET_PATH = PARENT_PATH + r"\Existing"
BUS_PATH = r"\Master-Mixer Hierarchy\Default Work Unit\VO_Bus"


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
    **fields: Any,
) -> dict[str, Any]:
    return {
        "id": object_id,
        "name": name,
        "type": object_type,
        "path": path,
        "parent": {"id": parent},
        "notes": "before",
        **fields,
    }


def _parent_row() -> dict[str, Any]:
    return _row(PARENT_ID, "Characters", "ActorMixer", PARENT_PATH, "{default-work-unit}")


def _target_row(**fields: Any) -> dict[str, Any]:
    return _row(TARGET_ID, "Existing", "ActorMixer", TARGET_PATH, PARENT_ID, **fields)


def _bus_row() -> dict[str, Any]:
    return _row(BUS_ID, "VO_Bus", "Bus", BUS_PATH, "{master-work-unit}")


def _types() -> dict[str, Any]:
    return {
        "return": [
            {"classId": 1, "name": "ActorMixer", "type": "WObject"},
            {"classId": 2, "name": "Sound", "type": "WObject"},
        ]
    }


def _dependency(**changes: Any) -> dict[str, Any]:
    return {
        "type": "override",
        "action": "Enable",
        "context": "Self",
        "property": "OverrideOutput",
        **changes,
    }


def _reference_info(*, dependency: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": "OutputBus",
        "type": "Reference",
        "supports": {"reference": True},
        "dependencies": [dict(_dependency() if dependency is None else dependency)],
    }


def _activation_info(*, property_type: str = "Boolean") -> dict[str, Any]:
    return {"name": "OverrideOutput", "type": property_type}


def _request(operation: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": operation,
        "arguments": dict(arguments),
    }


def _reference() -> dict[str, Any]:
    return {
        "name": "OutputBus",
        "target": {"kind": "id", "value": BUS_ID},
    }


def _create_arguments(*, nested: bool = False, properties: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {
        "type": "ActorMixer",
        "name": "Created",
        "references": [_reference()],
    }
    if properties is not None:
        node["properties"] = properties
    if nested:
        node = {
            "type": "ActorMixer",
            "name": "Created",
            "children": [{"type": "Sound", "name": "Voice", "references": [_reference()]}],
        }
    return {"parent": {"kind": "id", "value": PARENT_ID}, **node}


def _create_reader(*, metadata: list[Mapping[str, Any]]) -> ScriptedReader:
    return ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [_types()],
            "ak.wwise.core.object.getPropertyInfo": list(metadata),
            "ak.wwise.core.object.get": [
                {"return": [_parent_row()]},
                {"return": [_bus_row()]},
                {"return": []},
                {"return": []},
            ],
        }
    )


def test_object_create_root_derives_activation_into_dispatch_and_verification() -> None:
    prepared = prepare_operation(
        parse_operation_request(_request("object.create", _create_arguments())),
        read_call=_create_reader(metadata=[_reference_info(), _activation_info()]),
    ).as_dict()

    dispatch = prepared["dispatch"]["args"]
    assert dispatch["@OutputBus"] == BUS_ID
    assert dispatch["@OverrideOutput"] is True
    spec = prepared["verification_plan"]["nodes"][0]
    assert spec["properties"] == [
        {
            "name": "OverrideOutput",
            "value": True,
            "metadata_type": "Boolean",
            "derived": True,
            "activates_references": ["OutputBus"],
        }
    ]
    assert spec["references"][0]["activation_properties"] == ["OverrideOutput"]


def test_object_create_nested_derives_activation_only_on_referencing_child() -> None:
    prepared = prepare_operation(
        parse_operation_request(_request("object.create", _create_arguments(nested=True))),
        read_call=_create_reader(metadata=[_reference_info(), _activation_info()]),
    ).as_dict()

    root = prepared["dispatch"]["args"]
    child = root["children"][0]
    assert "@OverrideOutput" not in root
    assert child["@OutputBus"] == BUS_ID
    assert child["@OverrideOutput"] is True
    assert prepared["verification_plan"]["nodes"][0]["properties"] == []
    assert prepared["verification_plan"]["nodes"][1]["properties"][0]["derived"] is True


def _set_reader(*, nested: bool = False) -> ScriptedReader:
    object_reads: list[Mapping[str, Any]] = [
        {"return": [_target_row()]},
        {"return": [_bus_row()]},
    ]
    if nested:
        object_reads.append({"return": []})
    object_reads.extend(
        [
            {
                "return": [
                    _target_row(
                        OverrideOutput=False,
                        OutputBus={"id": "{master-bus}"},
                    )
                ]
            },
            {"return": []},
        ]
    )
    return ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [_types()],
            "ak.wwise.core.object.getPropertyInfo": [_reference_info(), _activation_info()],
            "ak.wwise.core.object.get": object_reads,
        }
    )


def test_object_set_root_derives_activation_and_snapshots_it() -> None:
    prepared = prepare_operation(
        parse_operation_request(
            _request(
                "object.set",
                {
                    "objects": [
                        {
                            "object": {"kind": "id", "value": TARGET_ID},
                            "references": [_reference()],
                        }
                    ]
                },
            )
        ),
        read_call=_set_reader(),
    ).as_dict()

    dispatch = prepared["dispatch"]["args"]["objects"][0]
    assert dispatch["@OutputBus"] == BUS_ID
    assert dispatch["@OverrideOutput"] is True
    fields = prepared["pre_state"]["object_graph_guard"]["field_snapshots"][0]["fields"]
    assert "OverrideOutput" in fields
    assert prepared["verification_plan"]["nodes"][0]["properties"][0]["derived"] is True


def test_object_set_nested_derives_activation_on_child_and_snapshots_child_path() -> None:
    prepared = prepare_operation(
        parse_operation_request(
            _request(
                "object.set",
                {
                    "objects": [
                        {
                            "object": {"kind": "id", "value": TARGET_ID},
                            "children": [
                                {"type": "Sound", "name": "Voice", "references": [_reference()]}
                            ],
                        }
                    ]
                },
            )
        ),
        read_call=_set_reader(nested=True),
    ).as_dict()

    target = prepared["dispatch"]["args"]["objects"][0]
    child = target["children"][0]
    assert "@OverrideOutput" not in target
    assert child["@OverrideOutput"] is True
    assert child["@OutputBus"] == BUS_ID
    child_spec = prepared["verification_plan"]["nodes"][1]
    assert child_spec["properties"][0]["name"] == "OverrideOutput"
    path_fields = prepared["pre_state"]["object_graph_guard"]["path_snapshots"][0]["fields"]
    assert "OverrideOutput" in path_fields


def test_explicit_true_activation_is_deduplicated() -> None:
    reader = _create_reader(metadata=[_activation_info(), _reference_info()])
    prepared = prepare_operation(
        parse_operation_request(
            _request(
                "object.create",
                _create_arguments(properties=[{"name": "OverrideOutput", "value": True}]),
            )
        ),
        read_call=reader,
    ).as_dict()

    spec = prepared["verification_plan"]["nodes"][0]
    assert prepared["dispatch"]["args"]["@OverrideOutput"] is True
    assert len([row for row in spec["properties"] if row["name"] == "OverrideOutput"]) == 1
    assert "derived" not in spec["properties"][0]
    assert spec["properties"][0]["activates_references"] == ["OutputBus"]
    assert len(reader.calls) == 7


def test_explicit_false_activation_is_rejected() -> None:
    reader = _create_reader(metadata=[_activation_info(), _reference_info()])
    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(
                _request(
                    "object.create",
                    _create_arguments(properties=[{"name": "OverrideOutput", "value": False}]),
                )
            ),
            read_call=reader,
        )

    assert rejected.value.error_code == "REFERENCE_DEPENDENCY_CONFLICT"


@pytest.mark.parametrize(
    ("dependency", "activation_type", "error_code"),
    [
        ({**_dependency(), "extra": True}, "Boolean", "INVALID_METADATA"),
        (_dependency(context="Parent"), "Boolean", "CONSTRAINED_REFERENCE_BOUNDARY"),
        (_dependency(), "Real64", "INVALID_METADATA"),
    ],
)
def test_unknown_malformed_or_non_boolean_dependencies_fail_closed(
    dependency: Mapping[str, Any],
    activation_type: str,
    error_code: str,
) -> None:
    reader = _create_reader(
        metadata=[_reference_info(dependency=dependency), _activation_info(property_type=activation_type)]
    )
    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(_request("object.create", _create_arguments())),
            read_call=reader,
        )

    assert rejected.value.error_code == error_code
