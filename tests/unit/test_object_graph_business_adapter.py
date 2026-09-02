from __future__ import annotations

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    NewDescendantTarget,
    ExistingObjectTarget,
    revalidate_live_types,
)
import pytest


PARENT_ID = "{11111111-1111-1111-1111-111111111111}"
BUS_ID = "{22222222-2222-2222-2222-222222222222}"


def _session(version: str = "2022.1") -> tuple[BusinessDeclarationSession, str]:
    context = BusinessContext.create(
        task_authority="da1-" + "1" * 40,
        project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        project_path="/fixtures/SampleProject.wproj",
        wwise_version=version,
        wwise_build=f"{version}.fixture",
    )
    session = BusinessDeclarationSession.create(context)
    parent = session.handles.bind_object(
        object_id=PARENT_ID,
        name="Default Work Unit",
        object_type="WorkUnit",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit",
    )
    return session, parent.handle


@pytest.mark.parametrize(
    "version",
    ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
)
def test_object_create_compiles_named_hierarchy_without_native_types_or_paths(
    version: str,
) -> None:
    session, parent_handle = _session(version)
    session = session.with_new_declaration(
        declaration_id="weather",
        target=NewDescendantTarget(
            parent_handle=parent_handle,
            name="Weather",
            kind="actor-mixer",
        ),
        fields={},
    )
    weather_handle = session.declarations[0].result_handle
    session = session.with_new_declaration(
        declaration_id="rain",
        target=NewDescendantTarget(
            parent_handle=weather_handle,
            name="Rain",
            kind="sound-sfx",
        ),
        fields={"loop": "infinite", "volume_db": -4},
    )

    request = business_adapter("object.create").materialize(session)

    assert request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "object.create",
        "arguments": {
            "parent": {"kind": "id", "value": PARENT_ID},
            "type": "ActorMixer",
            "name": "Weather",
            "children": [
                {
                    "type": "Sound",
                    "name": "Rain",
                    "properties": [
                        {"name": "IsLoopingEnabled", "value": True},
                        {"name": "IsLoopingInfinite", "value": True},
                        {"name": "Volume", "value": -4.0},
                    ],
                }
            ],
        },
    }


def test_object_create_accepts_one_gateway_bound_long_tail_kind_handle() -> None:
    session, parent_handle = _session("2025.1")
    bound_kind = session.handles.bind_type(
        class_id=3_276_960,
        name="Event",
        type_category="WObject",
        catalog_digest="a" * 64,
    )
    session = session.with_new_declaration(
        declaration_id="weather-event",
        target=NewDescendantTarget(
            parent_handle=parent_handle,
            name="Play_Weather",
            kind=bound_kind.handle,
        ),
        fields={},
    )

    request = business_adapter("object.create").materialize(session)

    assert request["arguments"] == {
        "parent": {"kind": "id", "value": PARENT_ID},
        "type": "Event",
        "name": "Play_Weather",
    }


def test_bound_kind_handle_fails_closed_when_live_type_row_drifts() -> None:
    session, _parent_handle = _session("2025.1")
    row = {"classId": 3_276_960, "name": "Event", "type": "WObject"}
    bound = session.handles.bind_type(
        class_id=row["classId"],
        name=row["name"],
        type_category=row["type"],
        catalog_digest="a" * 64,
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        revalidate_live_types(
            session.handles,
            (bound,),
            read_call=lambda _uri, _args, _options: {
                "return": [{**row, "classId": row["classId"] + 1}]
            },
        )

    assert captured.value.error_code == "TYPE_HANDLE_STALE"
    assert captured.value.repair["field"] == "kind_handle"


def test_object_create_compiles_common_and_bound_fields_without_tokens() -> None:
    session, parent_handle = _session("2025.1")
    bus = session.handles.bind_object(
        object_id=BUS_ID,
        name="Weather Bus",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Weather Bus",
    )
    custom = session.handles.bind_field(
        scope_kind="class",
        scope_value="Sound",
        token="CustomGain",
        field_kind="property",
        value_type="number",
        platform="Windows",
        restrictions={"minimum": 0.0, "maximum": 1.0},
        metadata_digest="b" * 64,
    )
    session = session.with_settings(
        {
            "add_to_source_control": True,
            "name_conflict": "fail",
            "platform": "Windows",
        }
    )
    session = session.with_new_declaration(
        declaration_id="rain",
        target=NewDescendantTarget(
            parent_handle=parent_handle,
            name="Rain",
            kind="sound-sfx",
        ),
        fields={
            "field_values": {custom.handle: 0.5},
            "loop": "infinite",
            "max_instances": 4,
            "output_bus": bus.handle,
            "ignore_parent_instance_limit": True,
            "volume_db": -4,
        },
    )

    request = business_adapter("object.create").materialize(session)

    assert request["arguments"] == {
        "parent": {"kind": "id", "value": PARENT_ID},
        "type": "Sound",
        "name": "Rain",
        "platform": "Windows",
        "properties": [
            {"name": "IsLoopingEnabled", "value": True},
            {"name": "IsLoopingInfinite", "value": True},
            {"name": "Volume", "value": -4.0},
            {"name": "UseMaxSoundPerInstance", "value": True},
            {"name": "MaxSoundPerInstance", "value": 4},
            {"name": "IgnoreParentMaxSoundInstance", "value": True},
            {"name": "CustomGain", "value": 0.5},
        ],
        "references": [
            {
                "name": "OutputBus",
                "target": {"kind": "id", "value": BUS_ID},
            }
        ],
        "auto_add_to_source_control": True,
    }


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_create_plugin_compiles_role_type_and_properties_from_handles(
    version: str,
) -> None:
    session, _parent_handle = _session(version)
    target = session.handles.bind_object(
        object_id="{33333333-3333-3333-3333-333333333333}",
        name="Rain",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
        semantic_kind="sound-voice",
    )
    plugin_type = session.handles.bind_type(
        class_id=123_456,
        name="Ak Tone Generator",
        type_category="Source",
        catalog_digest="c" * 64,
    )
    frequency = session.handles.bind_field(
        scope_kind="class",
        scope_value=123_456,
        token="Frequency",
        field_kind="property",
        value_type="number",
        restrictions={"minimum": 20.0, "maximum": 20_000.0},
        metadata_digest="d" * 64,
    )
    session = session.with_existing_declaration(
        declaration_id="source",
        target=ExistingObjectTarget(target.handle),
        fields={
            "field_values": {frequency.handle: 440},
            "language": "English(US)",
            "notes": "Weather tone",
            "platform": "Windows",
            "plugin_name": "Rain Tone",
            "plugin_role": "source",
            "plugin_type_handle": plugin_type.handle,
        },
    )

    request = business_adapter("object.createPlugin").materialize(session)

    assert request["arguments"] == {
        "target": {
            "kind": "id",
            "value": "{33333333-3333-3333-3333-333333333333}",
        },
        "plugin": {
            "kind": "source",
            "name": "Rain Tone",
            "class_id": 123_456,
            "notes": "Weather tone",
            "platform": "Windows",
            "language": "English(US)",
            "properties": [{"name": "Frequency", "value": 440.0}],
        },
    }


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_set_rtpc_compiles_bound_property_control_and_business_curve(
    version: str,
) -> None:
    session, _parent_handle = _session(version)
    target = session.handles.bind_object(
        object_id="{44444444-4444-4444-4444-444444444444}",
        name="Rain",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
    )
    control = session.handles.bind_object(
        object_id="{55555555-5555-5555-5555-555555555555}",
        name="Weather Intensity",
        object_type="GameParameter",
        path=r"\Game Parameters\Default Work Unit\Weather Intensity",
    )
    volume = session.handles.bind_field(
        scope_kind="object",
        scope_value=target.object_id,
        token="Volume",
        field_kind="property",
        value_type="number",
        restrictions={"minimum": -200.0, "maximum": 200.0},
        metadata_digest="e" * 64,
    )
    session = session.with_existing_declaration(
        declaration_id="rain-volume-rtpc",
        target=ExistingObjectTarget(target.handle),
        fields={
            "control_input_handle": control.handle,
            "curve_points": [
                {"x": 0, "y": -12, "shape": "Linear"},
                {"x": 100, "y": 0, "shape": "SCurve"},
            ],
            "field_handle": volume.handle,
            "mode": "add-or-update",
            "notes": "Weather intensity curve",
        },
    )

    request = business_adapter("object.setRTPC").materialize(session)

    assert request["arguments"] == {
        "object": {
            "kind": "id",
            "value": "{44444444-4444-4444-4444-444444444444}",
        },
        "property": "Volume",
        "control_input": {
            "kind": "id",
            "value": "{55555555-5555-5555-5555-555555555555}",
        },
        "points": [
            {"x": 0, "y": -12, "shape": "Linear"},
            {"x": 100, "y": 0, "shape": "Linear"},
        ],
        "notes": "Weather intensity curve",
        "mode": "add_or_replace",
    }


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_object_set_compiles_multi_object_changes_and_new_descendants(
    version: str,
) -> None:
    session, _parent_handle = _session(version)
    rain = session.handles.bind_object(
        object_id="{66666666-6666-6666-6666-666666666666}",
        name="Rain",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\Rain",
    )
    wind = session.handles.bind_object(
        object_id="{77777777-7777-7777-7777-777777777777}",
        name="Wind",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\Wind",
    )
    weather = session.handles.bind_object(
        object_id="{88888888-8888-8888-8888-888888888888}",
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )
    bus = session.handles.bind_object(
        object_id=BUS_ID,
        name="Weather Bus",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Weather Bus",
    )
    rain_volume = session.handles.bind_field(
        scope_kind="object",
        scope_value=rain.object_id,
        token="Volume",
        field_kind="property",
        value_type="number",
        restrictions={"minimum": -200.0, "maximum": 200.0},
        metadata_digest="1" * 64,
    )
    rain_bus = session.handles.bind_field(
        scope_kind="object",
        scope_value=rain.object_id,
        token="OutputBus",
        field_kind="reference",
        value_type="reference",
        restrictions={"allowed_target_types": ["Bus", "AuxBus"]},
        metadata_digest="2" * 64,
    )
    session = session.with_existing_declaration(
        declaration_id="rain",
        target=ExistingObjectTarget(rain.handle),
        fields={
            "field_values": {
                rain_volume.handle: -4,
                rain_bus.handle: bus.handle,
            }
        },
    )
    session = session.with_existing_declaration(
        declaration_id="wind",
        target=ExistingObjectTarget(wind.handle),
        fields={"notes": "Wind bed"},
    )
    session = session.with_new_declaration(
        declaration_id="gust",
        target=NewDescendantTarget(
            parent_handle=weather.handle,
            name="Gust",
            kind="sound-sfx",
        ),
        fields={"volume_db": -6},
    )

    request = business_adapter("object.set").materialize(session)

    assert request["arguments"] == {
        "objects": [
            {
                "object": {"kind": "id", "value": rain.object_id},
                "properties": [{"name": "Volume", "value": -4.0}],
                "references": [
                    {
                        "name": "OutputBus",
                        "target": {"kind": "id", "value": BUS_ID},
                    }
                ],
            },
            {
                "object": {"kind": "id", "value": wind.object_id},
                "notes": "Wind bed",
            },
            {
                "object": {"kind": "id", "value": weather.object_id},
                "children": [
                    {
                        "type": "Sound",
                        "name": "Gust",
                        "properties": [{"name": "Volume", "value": -6.0}],
                    }
                ],
            },
        ]
    }


def test_set_rtpc_rejects_curve_value_outside_bound_property_range() -> None:
    session, _parent_handle = _session("2025.1")
    target = session.handles.bind_object(
        object_id="{44444444-4444-4444-4444-444444444444}",
        name="Rain",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
    )
    control = session.handles.bind_object(
        object_id="{55555555-5555-5555-5555-555555555555}",
        name="Weather Intensity",
        object_type="GameParameter",
        path=r"\Game Parameters\Default Work Unit\Weather Intensity",
    )
    volume = session.handles.bind_field(
        scope_kind="object",
        scope_value=target.object_id,
        token="Volume",
        field_kind="property",
        value_type="number",
        restrictions={"minimum": -10.0, "maximum": 10.0},
        metadata_digest="e" * 64,
    )
    session = session.with_existing_declaration(
        declaration_id="rain-volume-rtpc",
        target=ExistingObjectTarget(target.handle),
        fields={
            "control_input_handle": control.handle,
            "curve_points": [{"x": 0, "y": -12, "shape": "Linear"}],
            "field_handle": volume.handle,
        },
    )

    with pytest.raises(BusinessDeclarationError) as rejected:
        business_adapter("object.setRTPC").materialize(session)

    assert rejected.value.repair["error_code"] == "FIELD_VALUE_OUT_OF_RANGE"


def test_set_rtpc_rejects_more_than_256_business_points() -> None:
    session, _parent_handle = _session("2025.1")
    target = session.handles.bind_object(
        object_id="{44444444-4444-4444-4444-444444444444}",
        name="Rain",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
    )
    control = session.handles.bind_object(
        object_id="{55555555-5555-5555-5555-555555555555}",
        name="Weather Intensity",
        object_type="GameParameter",
        path=r"\Game Parameters\Default Work Unit\Weather Intensity",
    )
    volume = session.handles.bind_field(
        scope_kind="object",
        scope_value=target.object_id,
        token="Volume",
        field_kind="property",
        value_type="number",
        restrictions={"minimum": -200.0, "maximum": 200.0},
        metadata_digest="e" * 64,
    )
    session = session.with_existing_declaration(
        declaration_id="rain-volume-rtpc",
        target=ExistingObjectTarget(target.handle),
        fields={
            "control_input_handle": control.handle,
            "curve_points": [
                {"x": index, "y": 0, "shape": "Linear"}
                for index in range(257)
            ],
            "field_handle": volume.handle,
        },
    )

    with pytest.raises(BusinessDeclarationError) as rejected:
        business_adapter("object.setRTPC").materialize(session)

    assert rejected.value.repair["error_code"] == "RTPC_POINT_LIMIT_INVALID"


@pytest.mark.parametrize(
    ("operation", "shape", "error_code"),
    (
        ("object.create", "depth", "OBJECT_GRAPH_DEPTH_LIMIT_EXCEEDED"),
        ("object.create", "children", "OBJECT_GRAPH_CHILD_LIMIT_EXCEEDED"),
        ("object.set", "nodes", "OBJECT_GRAPH_NODE_LIMIT_EXCEEDED"),
    ),
)
def test_object_graph_limits_return_business_repairs(
    operation: str,
    shape: str,
    error_code: str,
) -> None:
    session, parent_handle = _session("2025.1")
    if shape == "depth":
        current_parent = parent_handle
        for index in range(9):
            session = session.with_new_declaration(
                declaration_id=f"depth-{index}",
                target=NewDescendantTarget(
                    parent_handle=current_parent,
                    name=f"Depth {index}",
                    kind="actor-mixer",
                ),
                fields={},
            )
            current_parent = session.declarations[-1].result_handle
    elif shape == "children":
        session = session.with_new_declaration(
            declaration_id="root",
            target=NewDescendantTarget(
                parent_handle=parent_handle,
                name="Root",
                kind="actor-mixer",
            ),
            fields={},
        )
        root_handle = session.declarations[-1].result_handle
        for index in range(33):
            session = session.with_new_declaration(
                declaration_id=f"child-{index}",
                target=NewDescendantTarget(
                    parent_handle=root_handle,
                    name=f"Child {index}",
                    kind="sound-sfx",
                ),
                fields={},
            )
    else:
        for index in range(129):
            session = session.with_new_declaration(
                declaration_id=f"node-{index}",
                target=NewDescendantTarget(
                    parent_handle=parent_handle,
                    name=f"Node {index}",
                    kind="sound-sfx",
                ),
                fields={},
            )

    with pytest.raises(BusinessDeclarationError) as captured:
        business_adapter(operation).materialize(session)

    assert captured.value.error_code == error_code
    assert captured.value.repair["draft_revision"] == session.revision
    assert "limit" in captured.value.repair


def test_object_graph_field_limit_counts_compiled_properties_and_references() -> None:
    session, parent_handle = _session("2025.1")
    fields: dict[str, float] = {}
    for index in range(33):
        bound = session.handles.bind_field(
            scope_kind="class",
            scope_value="Sound",
            token=f"Custom{index}",
            field_kind="property",
            value_type="number",
            restrictions={},
            metadata_digest=f"{index + 1:064x}",
        )
        fields[bound.handle] = float(index)
    session = session.with_new_declaration(
        declaration_id="too-many-fields",
        target=NewDescendantTarget(
            parent_handle=parent_handle,
            name="Rain",
            kind="sound-sfx",
        ),
        fields={"field_values": fields},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        business_adapter("object.create").materialize(session)

    assert captured.value.error_code == "OBJECT_GRAPH_FIELD_LIMIT_EXCEEDED"
    assert captured.value.repair["limit"] == 32


@pytest.mark.parametrize(
    ("parent_type", "child_kind", "expected_list"),
    (
        ("StateGroup", "state", "States"),
        ("SwitchGroup", "switch", "Switches"),
    ),
)
def test_object_create_derives_game_sync_list_from_bound_parent(
    parent_type: str,
    child_kind: str,
    expected_list: str,
) -> None:
    session, _parent_handle = _session("2025.1")
    parent = session.handles.bind_object(
        object_id="{99999999-9999-9999-9999-999999999999}",
        name="Weather Mode",
        object_type=parent_type,
        path=rf"\Game Parameters\Default Work Unit\Weather Mode",
    )
    child_type = session.handles.bind_type(
        class_id=77 if child_kind == "state" else 88,
        name=child_kind.title(),
        type_category="WObject",
        catalog_digest="a" * 64,
    )
    session = session.with_new_declaration(
        declaration_id="value",
        target=NewDescendantTarget(
            parent_handle=parent.handle,
            name="Storm",
            kind=child_type.handle,
        ),
        fields={},
    )

    request = business_adapter("object.create").materialize(session)

    assert request["arguments"]["list"] == expected_list


def test_object_set_compiles_voice_language_platform_and_subordinate_media() -> None:
    session, parent_handle = _session("2025.1")
    session = session.with_new_declaration(
        declaration_id="voice",
        target=NewDescendantTarget(
            parent_handle=parent_handle,
            name="Storm Warning",
            kind="sound-voice",
        ),
        fields={
            "language": "English(US)",
            "media_files": [
                {
                    "inline_wav": "StormWarning.wav|UklGRgAAAAAA",
                    "kind": "sound-voice",
                    "language": "English(US)",
                    "originals_subfolder": "Weather/Warnings",
                }
            ],
            "platform": "Windows",
            "volume_db": -3,
        },
    )

    request = business_adapter("object.set").materialize(session)

    assert request["arguments"]["objects"] == [
        {
            "object": {"kind": "id", "value": PARENT_ID},
            "children": [
                {
                    "type": "Sound",
                    "name": "Storm Warning",
                    "language": "English(US)",
                    "platform": "Windows",
                    "properties": [{"name": "Volume", "value": -3.0}],
                    "import": {
                        "files": [
                            {
                                "audio_file_base64": "StormWarning.wav|UklGRgAAAAAA",
                                "originals_subfolder": "Weather/Warnings",
                                "language": "English(US)",
                                "object_type": "Sound",
                            }
                        ]
                    },
                }
            ],
        }
    ]


def test_object_set_subordinate_media_is_version_repaired_before_native_parse() -> None:
    session, parent_handle = _session("2022.1")
    session = session.with_new_declaration(
        declaration_id="rain",
        target=NewDescendantTarget(
            parent_handle=parent_handle,
            name="Rain",
            kind="sound-sfx",
        ),
        fields={
            "media_files": [
                {"inline_wav": "Rain.wav|UklGRgAAAAAAAA"},
            ]
        },
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        business_adapter("object.set").materialize(session)

    assert captured.value.error_code == "OBJECT_SET_IMPORT_UNAVAILABLE"
    assert captured.value.repair["choices"] == ["2023.1", "2024.1", "2025.1"]


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_object_set_compiles_named_object_list_with_per_target_replace(
    version: str,
) -> None:
    session, parent_handle = _session(version)
    session = session.with_new_declaration(
        declaration_id="custom-list-member",
        target=NewDescendantTarget(
            parent_handle=parent_handle,
            name="Rain Layer",
            kind="sound-sfx",
        ),
        fields={
            "list_behavior": "replace-all",
            "object_list": "CustomList",
            "volume_db": -4,
        },
    )

    request = business_adapter("object.set").materialize(session)

    assert request["arguments"] == {
        "objects": [
            {
                "object": {"kind": "id", "value": PARENT_ID},
                "list_mode": "replaceAll",
                "lists": [
                    {
                        "name": "CustomList",
                        "objects": [
                            {
                                "type": "Sound",
                                "name": "Rain Layer",
                                "properties": [{"name": "Volume", "value": -4.0}],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_object_set_compiles_explicit_empty_list_clear() -> None:
    session, parent_handle = _session("2025.1")
    session = session.with_existing_declaration(
        declaration_id="clear-custom-list",
        target=ExistingObjectTarget(parent_handle),
        fields={
            "clear_object_lists": ["CustomList"],
            "list_behavior": "replace-all",
        },
    )

    request = business_adapter("object.set").materialize(session)

    assert request["arguments"]["objects"] == [
        {
            "object": {"kind": "id", "value": PARENT_ID},
            "list_mode": "replaceAll",
            "lists": [{"name": "CustomList", "objects": []}],
        }
    ]


def test_object_set_rejects_empty_list_clear_without_replace_all() -> None:
    session, parent_handle = _session("2025.1")
    session = session.with_existing_declaration(
        declaration_id="invalid-clear",
        target=ExistingObjectTarget(parent_handle),
        fields={
            "clear_object_lists": ["CustomList"],
            "list_behavior": "append",
        },
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        business_adapter("object.set").materialize(session)

    assert captured.value.error_code == "OBJECT_SET_EMPTY_LIST_REQUIRES_REPLACE"


def test_object_create_rejects_voice_outcome_that_native_route_cannot_express() -> None:
    session, parent_handle = _session("2025.1")
    session = session.with_new_declaration(
        declaration_id="voice",
        target=NewDescendantTarget(
            parent_handle=parent_handle,
            name="Storm Warning",
            kind="sound-voice",
        ),
        fields={},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        business_adapter("object.create").materialize(session)

    assert captured.value.error_code == "OBJECT_CREATE_VOICE_UNAVAILABLE"
    assert captured.value.repair["choices"] == ["audio.import", "object.set"]


def test_create_plugin_rejects_type_handle_from_the_wrong_role() -> None:
    session, _parent_handle = _session("2025.1")
    target = session.handles.bind_object(
        object_id="{33333333-3333-3333-3333-333333333333}",
        name="Rain",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
    )
    source_type = session.handles.bind_type(
        class_id=123_456,
        name="Ak Tone Generator",
        type_category="Source",
        catalog_digest="c" * 64,
    )
    session = session.with_existing_declaration(
        declaration_id="effect",
        target=ExistingObjectTarget(target.handle),
        fields={
            "plugin_name": "Rain Effect",
            "plugin_role": "effect",
            "plugin_type_handle": source_type.handle,
        },
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        business_adapter("object.createPlugin").materialize(session)

    assert captured.value.error_code == "TYPE_HANDLE_ROLE_MISMATCH"
    assert captured.value.repair["expected_role"] == "effect"


def test_create_plugin_rejects_language_for_sound_sfx_before_preview() -> None:
    session, _parent_handle = _session("2025.1")
    target = session.handles.bind_object(
        object_id="{33333333-3333-3333-3333-333333333333}",
        name="Rain",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
        semantic_kind="sound-sfx",
    )
    plugin_type = session.handles.bind_type(
        class_id=123_456,
        name="Wwise Tone Generator",
        type_category="Source",
        catalog_digest="c" * 64,
    )
    session = session.with_existing_declaration(
        declaration_id="source",
        target=ExistingObjectTarget(target.handle),
        fields={
            "language": "SFX",
            "plugin_name": "Rain Tone",
            "plugin_role": "source",
            "plugin_type_handle": plugin_type.handle,
        },
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        business_adapter("object.createPlugin").materialize(session)

    assert captured.value.error_code == "PLUGIN_LANGUAGE_UNAVAILABLE"
    assert captured.value.repair["action"] == (
        "omit language for a Source on a Sound SFX"
    )


def test_create_plugin_preserves_hostile_notes_but_rejects_reserved_name() -> None:
    session, _parent_handle = _session("2025.1")
    target = session.handles.bind_object(
        object_id="{33333333-3333-3333-3333-333333333333}",
        name="Rain",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
    )
    plugin_type = session.handles.bind_type(
        class_id=123_456,
        name="Ak Tone Generator",
        type_category="Source",
        catalog_digest="c" * 64,
    )
    hostile_notes = "line one\n'\";$()\\路径"
    session = session.with_existing_declaration(
        declaration_id="source",
        target=ExistingObjectTarget(target.handle),
        fields={
            "notes": hostile_notes,
            "plugin_name": "Rain Tone",
            "plugin_role": "source",
            "plugin_type_handle": plugin_type.handle,
        },
    )
    request = business_adapter("object.createPlugin").materialize(session)
    assert request["arguments"]["plugin"]["notes"] == hostile_notes

    invalid = session.revise_declaration(
        declaration_id="source",
        fields={
            "plugin_name": "Rain/Tone",
            "plugin_role": "source",
            "plugin_type_handle": plugin_type.handle,
        },
    )
    with pytest.raises(BusinessDeclarationError) as captured:
        business_adapter("object.createPlugin").materialize(invalid)
    assert captured.value.error_code == "PLUGIN_NAME_INVALID"
