from __future__ import annotations

import base64
from collections import deque
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    OperationContractError,
    _is_rtpc_control_input,
    parse_operation_request,
    prepare_operation,
    verify_prepared_operation,
)


OBJECT_ID = "{11111111-1111-1111-1111-111111111111}"
CONTROL_ID = "{22222222-2222-2222-2222-222222222222}"
RTPC_ID = "{33333333-3333-3333-3333-333333333333}"
CURVE_ID = "{44444444-4444-4444-4444-444444444444}"


class ScriptedReader:
    def __init__(self, responses: Mapping[str, list[Mapping[str, Any]]]) -> None:
        self.responses = {uri: deque(rows) for uri, rows in responses.items()}
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def __call__(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls.append((uri, dict(args), dict(options)))
        return self.responses[uri].popleft()


def _request(
    operation: str,
    arguments: Mapping[str, Any],
    *,
    version: str = "2023.1",
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": dict(arguments),
    }


def _object_row(
    object_id: str = OBJECT_ID,
    *,
    name: str = "Sound",
    object_type: str = "Sound",
    **fields: Any,
) -> dict[str, Any]:
    return {
        "id": object_id,
        "name": name,
        "type": object_type,
        "path": rf"\Actor-Mixer Hierarchy\Default Work Unit\{name}",
        "parent": {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"},
        "notes": "",
        **fields,
    }


def _rtpc_row(
    *,
    rtpc_id: str = RTPC_ID,
    points: list[dict[str, Any]] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "id": rtpc_id,
        "name": "",
        "type": "RTPC",
        "path": rf"\Actor-Mixer Hierarchy\Default Work Unit\Sound\[RTPC: Voice Volume, Distance]",
        "notes": notes,
        "@PropertyName": "Volume",
        "@ControlInput": {"id": CONTROL_ID, "name": "Distance"},
        "@Curve": {
            "id": CURVE_ID,
            "points": points
            or [
                {"x": 0.0, "y": -20.0, "shape": "Linear"},
                {"x": 100.0, "y": 0.0, "shape": "Linear"},
            ],
        },
    }


def _nonmatching_rtpc_rows(count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(count):
        row = _rtpc_row(
            rtpc_id=f"{{90000000-0000-0000-0000-{index:012X}}}",
        )
        row["@PropertyName"] = "Pitch"
        rows.append(row)
    return rows


@pytest.mark.parametrize(
    "object_type",
    (
        "GameParameter",
        "ModulatorLFO",
        "ModulatorEnvelope",
        "ModulatorTime",
        "MIDIParameter",
        "midi_parameter",
    ),
)
def test_rtpc_control_input_type_uses_exact_normalized_allowlist(
    object_type: str,
) -> None:
    assert _is_rtpc_control_input(object_type)


@pytest.mark.parametrize(
    "object_type",
    (
        "MidiFile",
        "ModulatorWhatever",
        "MIDI",
        "Modulator",
        "GameParameterProxy",
        None,
    ),
)
def test_rtpc_control_input_type_rejects_prefix_lookalikes(
    object_type: Any,
) -> None:
    assert not _is_rtpc_control_input(object_type)


def test_platform_property_is_preflighted_dispatched_and_verified_with_same_platform() -> None:
    request = parse_operation_request(
        _request(
            "object.setProperty",
            {
                "object": {"kind": "id", "value": OBJECT_ID},
                "property": "Volume",
                "value": -6.0,
                "platform": "Mac",
            },
        )
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [_object_row()]},
                {"return": [{"id": OBJECT_ID, "path": _object_row()["path"], "Volume": -3.0}]},
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "supports": {"randomizer": True, "rtpc": "Additive", "unlink": True},
                }
            ],
            "ak.wwise.core.object.isPropertyEnabled": [{"return": True}],
        }
    )

    prepared = prepare_operation(request, read_call=reader).as_dict()

    assert prepared["dispatch"]["args"] == {
        "object": OBJECT_ID,
        "property": "Volume",
        "value": -6.0,
        "platform": "Mac",
    }
    assert prepared["pre_state"]["field_before"]["platform"] == "Mac"
    field_read = next(call for call in reader.calls if call[2].get("return") == ["id", "path", "Volume"])
    assert field_read[2]["platform"] == "Mac"

    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [{"id": OBJECT_ID, "path": _object_row()["path"], "Volume": -6.0}]}
                ]
            }
        ),
    )
    assert verified.ok


def test_set_linked_uses_is_linked_for_prestate_and_postcondition() -> None:
    parsed = parse_operation_request(
        _request(
            "object.setLinked",
            {
                "object": {"kind": "id", "value": OBJECT_ID},
                "property": "Volume",
                "platform": "Mac",
                "linked": False,
            },
        )
    )
    prepared = prepare_operation(
        parsed,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [{"return": [_object_row()]}],
                "ak.wwise.core.object.getPropertyInfo": [
                    {
                        "name": "Volume",
                        "type": "Real32",
                        "supports": {"randomizer": True, "rtpc": "Additive", "unlink": True},
                    }
                ],
                "ak.wwise.core.object.isLinked": [{"linked": True}],
            }
        ),
    ).as_dict()

    assert prepared["dispatch"] == {
        "uri": "ak.wwise.core.object.setLinked",
        "args": {
            "object": OBJECT_ID,
            "property": "Volume",
            "platform": "Mac",
            "linked": False,
        },
        "options": {},
    }
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=ScriptedReader(
            {"ak.wwise.core.object.isLinked": [{"linked": False}]}
        ),
    )
    assert verified.ok


def test_rtpc_add_materializes_only_the_closed_append_shape_and_verifies_full_list() -> None:
    points = [
        {"x": 0, "y": -20.0, "shape": "Linear"},
        {"x": 100, "y": 0.0, "shape": "SCurve"},
    ]
    parsed = parse_operation_request(
        _request(
            "object.setRTPC",
            {
                "object": {"kind": "id", "value": OBJECT_ID},
                "property": "Volume",
                "control_input": {"kind": "id", "value": CONTROL_ID},
                "points": points,
                "notes": "Distance curve",
            },
            version="2022.1",
        )
    )
    prepared = prepare_operation(
        parsed,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [_object_row()]},
                    {
                        "return": [
                            _object_row(
                                CONTROL_ID,
                                name="Distance",
                                object_type="GameParameter",
                            )
                        ]
                    },
                    {"return": []},
                ],
                "ak.wwise.core.object.getPropertyInfo": [
                    {
                        "name": "Volume",
                        "type": "Real32",
                        "supports": {"randomizer": True, "rtpc": "Additive", "unlink": True},
                    }
                ],
            }
        ),
    ).as_dict()

    assert prepared["dispatch"]["args"]["listMode"] == "append"
    assert prepared["dispatch"]["args"]["autoAddToSourceControl"] is False
    assert prepared["dispatch"]["args"]["objects"] == [
        {
            "object": OBJECT_ID,
            "@RTPC": [
                {
                    "type": "RTPC",
                    "name": "",
                    "@Curve": {"type": "Curve", "points": points},
                    "@PropertyName": "Volume",
                    "@ControlInput": CONTROL_ID,
                    "notes": "Distance curve",
                }
            ],
        }
    ]
    assert prepared["semantic_preview"]["envelope"]["metadata"]["raw_replace_all_allowed"] is False

    actual = _rtpc_row(points=points, notes="Distance curve")
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=ScriptedReader(
            {"ak.wwise.core.object.get": [{"return": [actual]}]}
        ),
    )
    assert verified.ok


def test_rtpc_update_targets_existing_rtpc_without_replace_all() -> None:
    before = _rtpc_row()
    points = [
        {"x": 0, "y": -12, "shape": "Linear"},
        {"x": 100, "y": 3, "shape": "Exp1"},
    ]
    parsed = parse_operation_request(
        _request(
            "object.setRTPC",
            {
                "object": {"kind": "id", "value": OBJECT_ID},
                "property": "Volume",
                "control_input": {"kind": "id", "value": CONTROL_ID},
                "points": points,
                "mode": "add_or_replace",
            },
        )
    )
    prepared = prepare_operation(
        parsed,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [_object_row()]},
                    {
                        "return": [
                            _object_row(
                                CONTROL_ID,
                                name="Distance",
                                object_type="GameParameter",
                            )
                        ]
                    },
                    {"return": [before]},
                ],
                "ak.wwise.core.object.getPropertyInfo": [
                    {
                        "name": "Volume",
                        "type": "Real32",
                        "supports": {"randomizer": True, "rtpc": "Additive", "unlink": True},
                    }
                ],
            }
        ),
    ).as_dict()

    assert prepared["dispatch"]["args"]["listMode"] == "append"
    assert prepared["dispatch"]["args"]["objects"] == [
        {
            "object": RTPC_ID,
            "@Curve": {"type": "Curve", "points": points},
        }
    ]
    assert "@RTPC" not in prepared["dispatch"]["args"]["objects"][0]

    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=ScriptedReader(
            {"ak.wwise.core.object.get": [{"return": [_rtpc_row(points=points)]}]}
        ),
    )
    assert verified.ok


def test_rtpc_add_fails_before_dispatch_when_complete_list_is_at_capacity() -> None:
    parsed = parse_operation_request(
        _request(
            "object.setRTPC",
            {
                "object": {"kind": "id", "value": OBJECT_ID},
                "property": "Volume",
                "control_input": {"kind": "id", "value": CONTROL_ID},
                "points": [{"x": 0, "y": 0, "shape": "Linear"}],
            },
        )
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [_object_row()]},
                {
                    "return": [
                        _object_row(
                            CONTROL_ID,
                            name="Distance",
                            object_type="GameParameter",
                        )
                    ]
                },
                {"return": _nonmatching_rtpc_rows(128)},
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "supports": {
                        "randomizer": True,
                        "rtpc": "Additive",
                        "unlink": True,
                    },
                }
            ],
        }
    )

    with pytest.raises(OperationContractError) as exc_info:
        prepare_operation(parsed, read_call=reader)

    assert exc_info.value.error_code == "RTPC_LIST_LIMIT_EXCEEDED"
    assert exc_info.value.details == {
        "count": 128,
        "limit": 128,
        "requested_action": "add",
    }


def test_rtpc_update_remains_available_when_complete_list_is_at_capacity() -> None:
    parsed = parse_operation_request(
        _request(
            "object.setRTPC",
            {
                "object": {"kind": "id", "value": OBJECT_ID},
                "property": "Volume",
                "control_input": {"kind": "id", "value": CONTROL_ID},
                "points": [{"x": 0, "y": -6, "shape": "Linear"}],
            },
        )
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [_object_row()]},
                {
                    "return": [
                        _object_row(
                            CONTROL_ID,
                            name="Distance",
                            object_type="GameParameter",
                        )
                    ]
                },
                {"return": [*_nonmatching_rtpc_rows(127), _rtpc_row()]},
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "supports": {
                        "randomizer": True,
                        "rtpc": "Additive",
                        "unlink": True,
                    },
                }
            ],
        }
    )

    prepared = prepare_operation(parsed, read_call=reader).as_dict()

    assert prepared["verification_plan"]["action"] == "update"
    assert prepared["dispatch"]["args"]["objects"][0]["object"] == RTPC_ID


def test_rtpc_and_link_boundaries_fail_before_live_reads() -> None:
    with pytest.raises(OperationContractError) as unavailable:
        parse_operation_request(
            _request(
                "object.setRTPC",
                {
                    "object": {"kind": "id", "value": OBJECT_ID},
                    "property": "Volume",
                    "control_input": {"kind": "id", "value": CONTROL_ID},
                    "points": [{"x": 0, "y": 0, "shape": "Linear"}],
                },
                version="2021.1",
            )
        )
    assert unavailable.value.error_code == "UNAVAILABLE_IN_VERSION"

    with pytest.raises(OperationContractError) as raw:
        parse_operation_request(
            _request(
                "object.setRTPC",
                {
                    "object": {"kind": "id", "value": OBJECT_ID},
                    "property": "Volume",
                    "control_input": {"kind": "id", "value": CONTROL_ID},
                    "points": [{"x": 0, "y": 0, "shape": "Linear"}],
                    "listMode": "replaceAll",
                },
            )
        )
    assert raw.value.error_code == "INVALID_REQUEST"

    with pytest.raises(OperationContractError) as linked_type:
        parse_operation_request(
            _request(
                "object.setLinked",
                {
                    "object": {"kind": "id", "value": OBJECT_ID},
                    "property": "Volume",
                    "platform": "Mac",
                    "linked": 0,
                },
            )
        )
    assert linked_type.value.error_code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    ("version", "wire_field"),
    [
        ("2021.1", "viewSyncGroup"),
        ("2022.1", "viewSelectionChannel"),
        ("2025.1", "viewSelectionChannel"),
    ],
)
def test_capture_screen_maps_the_stable_view_channel_and_verifies_image(
    version: str,
    wire_field: str,
) -> None:
    parsed = parse_operation_request(
        _request(
            "ui.captureScreen",
            {
                "view_name": "Project Explorer",
                "view_channel": 2,
                "rect": {"x": 0, "y": 1, "width": 640, "height": 360},
            },
            version=version,
        )
    )
    prepared = prepare_operation(parsed, read_call=lambda *_: {}).as_dict()
    assert prepared["dispatch"] == {
        "uri": "ak.wwise.ui.captureScreen",
        "args": {
            "viewName": "Project Explorer",
            wire_field: 2,
            "rect": {"x": 0, "y": 1, "width": 640, "height": 360},
        },
        "options": {},
    }
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nimage").decode("ascii")
    verified = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "contentType": "image/png",
                "contentBase64": encoded,
            }
        },
        read_call=lambda *_: {},
    )
    assert verified.ok
    assert verified.business_state_verified is True


@pytest.mark.parametrize(
    "arguments",
    [
        {"view_channel": 0},
        {"view_channel": True},
        {"rect": {"x": 0, "y": 0, "width": 1}},
        {"rect": {"x": -1, "y": 0, "width": 1, "height": 1}},
        {"rect": {"x": 0, "y": 0, "width": 0, "height": 1}},
    ],
)
def test_capture_screen_stable_request_fails_closed(arguments: Mapping[str, Any]) -> None:
    with pytest.raises(OperationContractError):
        parse_operation_request(_request("ui.captureScreen", arguments))


def test_capture_screen_rejects_invalid_base64_result() -> None:
    prepared = prepare_operation(
        parse_operation_request(_request("ui.captureScreen", {})),
        read_call=lambda *_: {},
    ).as_dict()
    verified = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "contentType": "image/png",
                "contentBase64": "not-base64!",
            }
        },
        read_call=lambda *_: {},
    )
    assert not verified.ok
    assert any(
        item["name"] == "screen capture content is valid non-empty base64"
        and item["passed"] is False
        for item in verified.assertions
    )
