from __future__ import annotations

import base64
from collections import deque
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    OPERATION_SPECS,
    OperationContractError,
    _is_rtpc_control_input,
    _read_rtpc_rows_with_evidence,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
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


def _rtpc_owner_result(*rows: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "return": [
            {
                "id": OBJECT_ID,
                "@RTPC": [{"id": row["id"]} for row in rows],
            }
        ]
    }


def _missing_rtpc_owner_result() -> dict[str, Any]:
    return {"return": [{"id": OBJECT_ID}]}


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


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_rtpc_add_materializes_only_the_closed_append_shape_and_verifies_full_list(
    version: str,
) -> None:
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
            version=version,
        )
    )
    prepare_reader = ScriptedReader(
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
                _rtpc_owner_result(),
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "supports": {"randomizer": True, "rtpc": "Additive", "unlink": True},
                }
            ],
        }
    )
    prepared = prepare_operation(parsed, read_call=prepare_reader).as_dict()

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
    assert prepare_reader.calls[-1] == (
        "ak.wwise.core.object.get",
        {"from": {"id": [OBJECT_ID]}},
        {"return": ["id", "@RTPC"]},
    )

    guard = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {
                        "return": [
                            _object_row(),
                            _object_row(
                                CONTROL_ID,
                                name="Distance",
                                object_type="GameParameter",
                            )
                        ]
                    },
                    _rtpc_owner_result(),
                ]
            }
        ),
    )
    assert guard["status"] == "valid"
    assert guard["ok"] is True

    actual = _rtpc_row(points=points, notes="Distance curve")
    verify_reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                _rtpc_owner_result(actual),
                {"return": [actual]},
            ]
        }
    )
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=verify_reader,
    )
    assert verified.ok
    assert verify_reader.calls == [
        (
            "ak.wwise.core.object.get",
            {"from": {"id": [OBJECT_ID]}},
            {"return": ["id", "@RTPC"]},
        ),
        (
            "ak.wwise.core.object.get",
            {"from": {"id": [RTPC_ID]}},
            {
                "return": [
                    "id",
                    "name",
                    "type",
                    "path",
                    "notes",
                    "@PropertyName",
                    "@ControlInput",
                    "@Curve",
                ]
            },
        ),
    ]


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_version_proven_missing_empty_rtpc_field_is_normalized_through_prepare_guard_and_verify(
    version: str,
) -> None:
    parsed = parse_operation_request(
        _request(
            "object.setRTPC",
            {
                "object": {"kind": "id", "value": OBJECT_ID},
                "property": "Volume",
                "control_input": {"kind": "id", "value": CONTROL_ID},
                "points": [{"x": 0, "y": -12, "shape": "Linear"}],
            },
            version=version,
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
                    _missing_rtpc_owner_result(),
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
        ),
    ).as_dict()

    normalization = {
        "kind": "missing-empty-object-list",
        "version": version,
        "field": "@RTPC",
        "observed_row_keys": ["id"],
        "normalized_value": [],
    }
    assert prepared["pre_state"]["rtpc_snapshot"]["rows"] == []
    assert prepared["pre_state"]["rtpc_snapshot"]["readback_compatibility"] == [
        normalization
    ]
    assert prepared["preflight_reads"][-1]["result"] == _missing_rtpc_owner_result()

    guard = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {
                        "return": [
                            _object_row(),
                            _object_row(
                                CONTROL_ID,
                                name="Distance",
                                object_type="GameParameter",
                            )
                        ]
                    },
                    _missing_rtpc_owner_result(),
                ]
            }
        ),
    )
    assert guard["ok"] is True
    guard_owner = next(
        row for row in guard["readbacks"] if row.get("role") == "object-rtpc-owner"
    )
    assert guard_owner["result"] == _missing_rtpc_owner_result()
    assert guard_owner["compatibility_normalization"] == normalization

    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=ScriptedReader(
            {"ak.wwise.core.object.get": [_missing_rtpc_owner_result()]}
        ),
    )
    assert verified.ok is False
    assert verified.status == "verification_failed"
    assert verified.readbacks[0]["result"] == _missing_rtpc_owner_result()
    assert verified.readbacks[0]["compatibility_normalization"] == normalization


@pytest.mark.parametrize("version", ("2023.1", "2024.1"))
def test_missing_rtpc_owner_field_remains_invalid_without_live_version_evidence(
    version: str,
) -> None:
    reader = ScriptedReader(
        {"ak.wwise.core.object.get": [_missing_rtpc_owner_result()]}
    )

    with pytest.raises(OperationContractError) as exc_info:
        _read_rtpc_rows_with_evidence(
            OBJECT_ID,
            version=version,
            read=reader,
        )

    assert exc_info.value.error_code == "INVALID_READBACK"


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_explicit_empty_rtpc_owner_array_remains_valid(version: str) -> None:
    reader = ScriptedReader(
        {"ak.wwise.core.object.get": [_rtpc_owner_result()]}
    )

    rows, readbacks = _read_rtpc_rows_with_evidence(
        OBJECT_ID,
        version=version,
        read=reader,
    )

    assert rows == []
    assert readbacks == [
        {
            "role": "object-rtpc-owner",
            "uri": "ak.wwise.core.object.get",
            "args": {"from": {"id": [OBJECT_ID]}},
            "options": {"return": ["id", "@RTPC"]},
            "result": _rtpc_owner_result(),
        }
    ]


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
@pytest.mark.parametrize(
    "owner_result",
    (
        {"return": []},
        {"return": [{}]},
        {"return": [{"id": CONTROL_ID}]},
        {"return": [{"id": OBJECT_ID}, {"id": OBJECT_ID}]},
    ),
)
def test_compatibility_version_still_requires_one_canonical_owner_row(
    version: str,
    owner_result: Mapping[str, Any],
) -> None:
    reader = ScriptedReader(
        {"ak.wwise.core.object.get": [owner_result]}
    )

    with pytest.raises(OperationContractError) as exc_info:
        _read_rtpc_rows_with_evidence(
            OBJECT_ID,
            version=version,
            read=reader,
        )

    assert exc_info.value.error_code == "INVALID_READBACK"


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_compatibility_version_missing_rtpc_field_with_an_extra_key_remains_invalid(
    version: str,
) -> None:
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [{"id": OBJECT_ID, "name": "Sound"}]}
            ]
        }
    )

    with pytest.raises(OperationContractError) as exc_info:
        _read_rtpc_rows_with_evidence(
            OBJECT_ID,
            version=version,
            read=reader,
        )

    assert exc_info.value.error_code == "INVALID_READBACK"


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
@pytest.mark.parametrize("malformed", (None, {}, "not-a-list", 0))
def test_present_rtpc_owner_field_must_remain_an_array_in_compatibility_versions(
    version: str,
    malformed: Any,
) -> None:
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [{"id": OBJECT_ID, "@RTPC": malformed}]}
            ]
        }
    )

    with pytest.raises(OperationContractError) as exc_info:
        _read_rtpc_rows_with_evidence(
            OBJECT_ID,
            version=version,
            read=reader,
        )

    assert exc_info.value.error_code == "INVALID_READBACK"


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
                    _rtpc_owner_result(before),
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
            {
                "ak.wwise.core.object.get": [
                    _rtpc_owner_result(_rtpc_row(points=points)),
                    {"return": [_rtpc_row(points=points)]},
                ]
            }
        ),
    )
    assert verified.ok


def test_rtpc_mode_schema_maps_replace_or_add_business_wording() -> None:
    spec = OPERATION_SPECS["object.setRTPC"]
    mode = spec.argument_contract["properties"]["mode"]

    assert mode["x-discloseDescription"] is True
    assert mode["description"] == (
        "Use add_or_replace when the user asks to replace the matching RTPC if "
        "present and add it if absent; use add only when an existing exact "
        "property and ControlInput match must fail."
    )


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
                _rtpc_owner_result(*_nonmatching_rtpc_rows(128)),
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


def test_rtpc_owner_list_over_snapshot_limit_fails_before_detail_read() -> None:
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
    rows = _nonmatching_rtpc_rows(129)
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
                _rtpc_owner_result(*rows),
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
    assert exc_info.value.details == {"count": 129, "limit": 128}
    assert reader.calls[-1] == (
        "ak.wwise.core.object.get",
        {"from": {"id": [OBJECT_ID]}},
        {"return": ["id", "@RTPC"]},
    )


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
                _rtpc_owner_result(
                    *_nonmatching_rtpc_rows(127),
                    _rtpc_row(),
                ),
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
    assert verified.status == "result_schema_checked"
    assert verified.verification_strength == "result_schema_only"
    assert verified.business_state_verified is False


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
