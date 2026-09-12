from __future__ import annotations

from collections import deque
from typing import Any, Mapping

import pytest

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    OperationContractError,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
    verify_prepared_operation,
)


TARGET_ID = "{11111111-1111-1111-1111-111111111111}"
TARGET_PARENT_ID = "{22222222-2222-2222-2222-222222222222}"
SLOT_ID = "{33333333-3333-3333-3333-333333333333}"
PLUGIN_ID = "{44444444-4444-4444-4444-444444444444}"
OLD_SLOT_ID = "{55555555-5555-5555-5555-555555555555}"
OLD_PLUGIN_ID = "{66666666-6666-6666-6666-666666666666}"


class ScriptedReader:
    def __init__(self, responses: Mapping[str, list[Mapping[str, Any]]]) -> None:
        self.responses = {
            uri: deque(values)
            for uri, values in responses.items()
        }
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
        values = self.responses.get(uri)
        if values is None or not values:
            raise AssertionError(
                f"Unexpected or exhausted read: {uri} args={args!r} options={options!r}"
            )
        return values.popleft()


def target_row(*, object_type: str = "Sound") -> dict[str, Any]:
    return {
        "id": TARGET_ID,
        "name": "Target",
        "type": object_type,
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Target",
        "parent": {"id": TARGET_PARENT_ID},
        "notes": "",
    }


def request(
    *,
    version: str,
    kind: str,
    properties: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    plugin: dict[str, Any] = {
        "kind": kind,
        "name": "Generated Tone" if kind == "source" else "Room",
        "class_id": 123_456 if kind == "source" else 7_733_251,
    }
    if properties is not None:
        plugin["properties"] = properties
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "object.createPlugin",
        "arguments": {
            "target": {"kind": "id", "value": TARGET_ID},
            "plugin": plugin,
        },
    }


def source_row(
    *,
    plugin_id: str = PLUGIN_ID,
    name: str = "Generated Tone",
) -> dict[str, Any]:
    return {
        "id": plugin_id,
        "name": name,
        "type": "Source",
        "classId": 123_456,
        "parent": {"id": TARGET_ID},
        "owner": {"id": TARGET_ID},
    }


def effect_row(
    *,
    parent_id: str,
    plugin_id: str = PLUGIN_ID,
) -> dict[str, Any]:
    return {
        "id": plugin_id,
        "name": "Room",
        "type": "Effect",
        "classId": 7_733_251,
        "parent": {"id": parent_id},
        "owner": {"id": TARGET_ID},
    }


def effect_slot_row(
    *,
    slot_id: str = SLOT_ID,
    plugin_id: str | None = PLUGIN_ID,
) -> dict[str, Any]:
    return {
        "id": slot_id,
        "name": "",
        "type": "EffectSlot",
        "parent": {"id": TARGET_ID},
        "owner": {"id": TARGET_ID},
        "@Effect": (
            None
            if plugin_id is None
            else {"id": plugin_id}
        ),
    }


def test_source_prepare_replays_class_id_metadata_and_complete_child_guard() -> None:
    operation_request = parse_operation_request(
        request(
            version="2025.1",
            kind="source",
            properties=[{"name": "Frequency", "value": 440.0}],
        )
    )
    preview_reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [target_row()]},
                {"return": []},
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {"name": "Frequency", "type": "Real32"},
            ],
        }
    )

    prepared = prepare_operation(
        operation_request,
        read_call=preview_reader,
    ).as_dict()

    assert prepared["dispatch"] == {
        "uri": "ak.wwise.core.object.set",
        "args": {
            "objects": [
                {
                    "object": TARGET_ID,
                    "onNameConflict": "fail",
                    "children": [
                        {
                            "type": "Source",
                            "name": "Generated Tone",
                            "classId": 123_456,
                            "@Frequency": 440.0,
                        }
                    ],
                }
            ],
            "autoAddToSourceControl": False,
        },
        "options": {},
    }
    guard = prepared["pre_state"]["plugin_creation_guard"]
    assert guard["snapshot"]["kind"] == "source_children"
    assert guard["snapshot"]["rows"] == []
    assert guard["property_metadata"][0]["name"] == "Frequency"
    assert guard["property_metadata"][0]["type"] == "Real32"
    verification_plan = prepared["verification_plan"]
    assert verification_plan["kind"] == "object-plugin-created"
    assert verification_plan["property_validation"] == [
        {
            "name": "Frequency",
            "value": 440.0,
            "metadata_type": "Real32",
        }
    ]
    assert verification_plan["readback_fields"] == [
        "id",
        "name",
        "type",
        "classId",
        "parent",
        "owner",
        "@Frequency",
    ]
    assert verification_plan["readback_view"] == {
        "language": None,
        "platform": None,
    }

    replay_reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [target_row()]},
                {"return": []},
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {"name": "Frequency", "type": "Real32"},
            ],
        }
    )
    validation = validate_prepared_roles(
        prepared,
        read_call=replay_reader,
    )

    assert validation["ok"] is True
    assert any(
        row["name"] == "closed plug-in dispatch still matches the replayed plan"
        and row["passed"] is True
        for row in validation["assertions"]
    )
    property_calls = [
        call
        for call in replay_reader.calls
        if call[0] == "ak.wwise.core.object.getPropertyInfo"
    ]
    assert property_calls == [
        (
            "ak.wwise.core.object.getPropertyInfo",
            {"property": "Frequency", "classId": 123_456},
            {},
        )
    ]


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_public_source_language_contract_dispatches_in_every_supported_version(
    version: str,
) -> None:
    payload = request(version=version, kind="source")
    payload["arguments"]["plugin"]["language"] = "SFX"

    prepared = prepare_operation(
        parse_operation_request(payload),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [target_row()]},
                    {"return": []},
                ]
            }
        ),
    ).as_dict()

    source = prepared["dispatch"]["args"]["objects"][0]["children"][0]
    assert source["language"] == "SFX"
    assert prepared["pre_state"]["plugin_creation_guard"]["descriptor"][
        "language"
    ] == "SFX"
    assert prepared["verification_plan"]["readback_fields"][-1] == (
        "audioSource:language"
    )
    assert prepared["verification_plan"]["readback_view"] == {
        "language": "SFX",
        "platform": None,
    }


def test_source_preexisting_child_drift_requires_a_new_preview() -> None:
    operation_request = parse_operation_request(
        request(version="2025.1", kind="source")
    )
    prepared = prepare_operation(
        operation_request,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [target_row()]},
                    {"return": []},
                ]
            }
        ),
    ).as_dict()

    validation = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [target_row()]},
                    {
                        "return": [
                            {
                                "id": OLD_PLUGIN_ID,
                                "name": "Added After Preview",
                                "type": "Source",
                                "parent": {"id": TARGET_ID},
                            }
                        ]
                    },
                ]
            }
        ),
    )

    assert validation["ok"] is False
    assert validation["status"] == "repreview_required"
    assert any(
        row["name"] == "complete plug-in placement pre-state is unchanged"
        and row["passed"] is False
        for row in validation["assertions"]
    )


def test_source_verifier_uses_sealed_dynamic_view_and_requested_state() -> None:
    payload = request(
        version="2025.1",
        kind="source",
        properties=[{"name": "Frequency", "value": 440.0}],
    )
    payload["arguments"]["plugin"].update(
        {
            "notes": "Generated for verification",
            "language": "English(US)",
            "platform": "Windows",
        }
    )
    prepared = prepare_operation(
        parse_operation_request(payload),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [target_row()]},
                    {"return": []},
                ],
                "ak.wwise.core.object.getPropertyInfo": [
                    {"name": "Frequency", "type": "Real32"},
                ],
            }
        ),
    ).as_dict()

    verifier_reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            **source_row(),
                            "notes": "Generated for verification",
                            "audioSource:language": {
                                "name": "English(US)",
                            },
                            "@Frequency": 440.00003,
                        }
                    ]
                }
            ]
        }
    )
    verification = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "objects": [
                    {
                        "id": TARGET_ID,
                        "children": [
                            {
                                "id": PLUGIN_ID,
                                "name": "Generated Tone",
                                "type": "Source",
                            }
                        ],
                    }
                ]
            }
        },
        read_call=verifier_reader,
    )

    assert verification.status == "verified"
    assert verifier_reader.calls == [
        (
            "ak.wwise.core.object.get",
            {"from": {"id": [PLUGIN_ID]}},
            {
                "return": [
                    "id",
                    "name",
                    "type",
                    "classId",
                    "parent",
                    "owner",
                    "notes",
                    "audioSource:language",
                    "@Frequency",
                ],
                "language": "English(US)",
                "platform": "Windows",
            },
        )
    ]
    assert verification.assertions[-1]["evidence"]["requested_state"] == {
        "language": {"requested": True, "value": "English(US)"},
        "notes": {
            "requested": True,
            "value": "Generated for verification",
        },
        "platform": "Windows",
        "properties": [
            {
                "field": "@Frequency",
                "metadata_type": "Real32",
                "value": 440.00003,
            }
        ],
    }


def test_source_verifier_rejects_tampered_property_validation_before_reads() -> None:
    prepared = prepare_operation(
        parse_operation_request(
            request(
                version="2025.1",
                kind="source",
                properties=[{"name": "Frequency", "value": 440.0}],
            )
        ),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [target_row()]},
                    {"return": []},
                ],
                "ak.wwise.core.object.getPropertyInfo": [
                    {"name": "Frequency", "type": "Real32"},
                ],
            }
        ),
    ).as_dict()
    prepared["verification_plan"]["property_validation"][0][
        "metadata_type"
    ] = "String"

    reader = ScriptedReader({})
    with pytest.raises(OperationContractError) as caught:
        verify_prepared_operation(
            prepared,
            execution_result={"result": {}},
            read_call=reader,
        )

    assert caught.value.error_code == "INVALID_PREVIEW"
    assert reader.calls == []


def test_2022_effect_prepare_uses_complete_fixed_slot_snapshot_and_verifies_plugin() -> None:
    fixed_snapshot = {
        "id": TARGET_ID,
        "@Effect0": {"id": OLD_PLUGIN_ID},
        "@Effect1": None,
        "@Effect2": None,
        "@Effect3": None,
    }
    prepared = prepare_operation(
        parse_operation_request(request(version="2022.1", kind="effect")),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [target_row(object_type="ActorMixer")]},
                    {"return": [fixed_snapshot]},
                ]
            }
        ),
    ).as_dict()

    dispatch_object = prepared["dispatch"]["args"]["objects"][0]
    assert dispatch_object == {
        "object": TARGET_ID,
        "@Effect1": {
            "type": "Effect",
            "name": "Room",
            "classId": 7_733_251,
        },
    }
    assert prepared["pre_state"]["plugin_creation_guard"]["snapshot"][
        "fixed_effects"
    ] == {
        "@Effect0": OLD_PLUGIN_ID,
        "@Effect1": None,
        "@Effect2": None,
        "@Effect3": None,
    }
    assert prepared["verification_plan"]["pre_effect_references"] == {
        "@Effect0": OLD_PLUGIN_ID,
        "@Effect1": None,
        "@Effect2": None,
        "@Effect3": None,
    }

    post_snapshot = {
        "id": TARGET_ID,
        "@Effect0": {"id": OLD_PLUGIN_ID},
        "@Effect1": {"id": PLUGIN_ID},
        "@Effect2": None,
        "@Effect3": None,
    }
    verifier_reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [post_snapshot]},
                {"return": [effect_row(parent_id=TARGET_ID)]},
            ]
        }
    )
    verification = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "objects": [
                    {
                        "id": TARGET_ID,
                        "@Effect1": {
                            "id": PLUGIN_ID,
                            "name": "Room",
                            "type": "Effect",
                        },
                    }
                ]
            }
        },
        read_call=verifier_reader,
    )

    assert verification.status == "verified"
    assert verification.business_state_verified is True
    assert verification.readbacks[-1]["result"]["return"][0]["id"] == PLUGIN_ID
    assert [call[2]["return"] for call in verifier_reader.calls] == [
        ["id", "@Effect0", "@Effect1", "@Effect2", "@Effect3"],
        ["id", "name", "type", "classId", "parent", "owner"],
    ]
    assert verification.assertions[-1]["evidence"]["placement"] == {
        "kind": "fixed_effect_reference",
        "selected_effect_field": "@Effect1",
        "target_id": TARGET_ID,
        "target_post_references": {
            "@Effect0": OLD_PLUGIN_ID,
            "@Effect1": PLUGIN_ID,
            "@Effect2": None,
            "@Effect3": None,
        },
    }


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_effect_verifier_resolves_effect_slot_to_effect_guid_before_plugin_read(
    version: str,
) -> None:
    payload = request(version=version, kind="effect")
    payload["arguments"]["plugin"]["platform"] = "Windows"
    prepared = prepare_operation(
        parse_operation_request(payload),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [target_row(object_type="ActorMixer")]},
                    {
                        "return": [
                            {
                                "id": TARGET_ID,
                                "@Effects": [{"id": OLD_SLOT_ID}],
                            }
                        ]
                    },
                    {
                        "return": [
                            effect_slot_row(
                                slot_id=OLD_SLOT_ID,
                                plugin_id=OLD_PLUGIN_ID,
                            )
                        ]
                    },
                ]
            }
        ),
    ).as_dict()
    dispatch_object = prepared["dispatch"]["args"]["objects"][0]
    assert dispatch_object["listMode"] == "append"
    assert dispatch_object["@Effects"][0]["type"] == "EffectSlot"
    assert dispatch_object["@Effects"][0]["@Effect"]["type"] == "Effect"
    assert prepared["verification_plan"]["preexisting_effect_slot_ids"] == [
        OLD_SLOT_ID
    ]
    preview_snapshot = prepared["pre_state"]["plugin_creation_guard"][
        "snapshot"
    ]
    assert preview_snapshot["args"] == {"from": {"id": [TARGET_ID]}}
    assert preview_snapshot["options"] == {
        "return": ["id", "@Effects"],
        "platform": "Windows",
    }
    preview_readbacks = prepared["preflight_reads"]
    effect_reads = [
        row
        for row in preview_readbacks
        if row["uri"] == "ak.wwise.core.object.get"
        and row["options"].get("platform") == "Windows"
    ]
    assert [row["options"]["return"] for row in effect_reads] == [
        ["id", "@Effects"],
        ["id", "name", "type", "parent", "owner", "@Effect"],
    ]

    verifier_reader = ScriptedReader(
        {
            "ak.wwise.core.object.get": [
                {"return": [effect_slot_row()]},
                {"return": [effect_row(parent_id=SLOT_ID)]},
            ]
        }
    )
    verification = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "objects": [
                    {
                        "id": TARGET_ID,
                        "@Effects": [
                            {
                                "id": SLOT_ID,
                                "name": "",
                                "type": "EffectSlot",
                            }
                        ],
                    }
                ]
            }
        },
        read_call=verifier_reader,
    )

    assert verification.status == "verified"
    object_get_ids = [
        call[1]["from"]["id"][0]
        for call in verifier_reader.calls
        if call[0] == "ak.wwise.core.object.get"
    ]
    assert object_get_ids == [SLOT_ID, PLUGIN_ID]
    assert any(
        row["name"] == "created EffectSlot exposes one canonical @Effect binding"
        and row["passed"] is True
        for row in verification.assertions
    )
    assert verification.assertions[-1]["evidence"] == {
        "id": PLUGIN_ID,
        "name": "Room",
        "type": "Effect",
        "classId": 7_733_251,
        "parent": SLOT_ID,
        "owner": TARGET_ID,
        "readback_view": {
            "fields": [
                "id",
                "name",
                "type",
                "classId",
                "parent",
                "owner",
            ],
            "language": None,
            "platform": "Windows",
        },
        "requested_state": {
            "language": {"requested": False, "value": None},
            "notes": {"requested": False, "value": None},
            "platform": "Windows",
            "properties": [],
        },
        "placement": {
            "kind": "effect_slot_append",
            "effect_slot_id": SLOT_ID,
            "preexisting_effect_slot_ids": [OLD_SLOT_ID],
            "target_id": TARGET_ID,
        },
    }


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("proof", ({}, {"return": None}, {"return": {}}, {"return": [None]}, {"return": [{"id": SLOT_ID}]}, {"return": []}))
def test_effect_prepare_requires_independent_empty_list_proof(
    version: str, proof: Mapping[str, Any],
) -> None:
    reader = ScriptedReader({
        "ak.wwise.core.object.get": [
            {"return": [target_row(object_type="ActorMixer")]},
            {"return": [{"id": TARGET_ID}]},
            proof,
        ],
    })
    parsed = parse_operation_request(request(version=version, kind="effect"))
    if proof == {"return": []}:
        prepared = prepare_operation(parsed, read_call=reader).as_dict()
        assert prepared["dispatch"]["args"]["objects"][0]["listMode"] == "append"
        assert prepared["preflight_reads"][-1]["result"] == proof
    else:
        with pytest.raises(OperationContractError, match="independently empty"):
            prepare_operation(parsed, read_call=reader)
    assert reader.calls[-1] == (
        "ak.wwise.core.object.get",
        {"waql": f'from object "{TARGET_ID}" select @Effects take 1'},
        {"return": ["id"]},
    )


def test_2023_effect_verifier_fails_closed_when_slot_has_no_effect_reference() -> None:
    prepared = prepare_operation(
        parse_operation_request(request(version="2023.1", kind="effect")),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [target_row(object_type="ActorMixer")]},
                    {"return": [{"id": TARGET_ID, "@Effects": []}]},
                ]
            }
        ),
    ).as_dict()

    verification = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "objects": [
                    {
                        "id": TARGET_ID,
                        "@Effects": [{"id": SLOT_ID, "name": "", "type": "EffectSlot"}],
                    }
                ]
            }
        },
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [effect_slot_row(plugin_id=None)]}
                ]
            }
        ),
    )

    assert verification.status == "verification_failed"
    assert verification.ok is False
    assert any(
        row["name"] == "created EffectSlot exposes one canonical @Effect binding"
        and row["passed"] is False
        for row in verification.assertions
    )


def test_2023_effect_verifier_rejects_a_reused_preexisting_slot_id() -> None:
    prepared = prepare_operation(
        parse_operation_request(request(version="2023.1", kind="effect")),
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {"return": [target_row(object_type="ActorMixer")]},
                    {
                        "return": [
                            {
                                "id": TARGET_ID,
                                "@Effects": [{"id": OLD_SLOT_ID}],
                            }
                        ]
                    },
                    {
                        "return": [
                            effect_slot_row(
                                slot_id=OLD_SLOT_ID,
                                plugin_id=OLD_PLUGIN_ID,
                            )
                        ]
                    },
                ]
            }
        ),
    ).as_dict()

    verification = verify_prepared_operation(
        prepared,
        execution_result={
            "result": {
                "objects": [
                    {
                        "id": TARGET_ID,
                        "@Effects": [
                            {
                                "id": OLD_SLOT_ID,
                                "name": "",
                                "type": "EffectSlot",
                            }
                        ],
                    }
                ]
            }
        },
        read_call=ScriptedReader(
            {
                "ak.wwise.core.object.get": [
                    {
                        "return": [
                            effect_slot_row(
                                slot_id=OLD_SLOT_ID,
                                plugin_id=PLUGIN_ID,
                            )
                        ]
                    },
                    {
                        "return": [
                            effect_row(
                                parent_id=OLD_SLOT_ID,
                            )
                        ]
                    },
                ]
            }
        ),
    )

    assert verification.status == "verification_failed"
    assert verification.assertions[-1]["passed"] is False
    assert verification.assertions[-1]["evidence"]["error_code"] == (
        "EFFECT_SLOT_ID_NOT_NEW"
    )


def test_generic_object_set_call_lists_create_plugin_as_a_required_dedicated_route() -> None:
    try:
        parse_operation_request(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": "2025.1",
                "operation": "waapi.call",
                "arguments": {
                    "api": "ak.wwise.core.object.set",
                    "args": {},
                    "options": {},
                },
            }
        )
    except OperationContractError as exc:
        assert exc.error_code == "DEDICATED_OPERATION_REQUIRED"
        assert exc.details["required_operations"] == [
            "object.createPlugin",
            "object.set",
            "object.setRTPC",
        ]
    else:  # pragma: no cover - failure message is clearer than pytest.raises here.
        raise AssertionError("generic object.set unexpectedly bypassed dedicated routes")
