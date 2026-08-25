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


def test_object_create_compiles_named_hierarchy_without_native_types_or_paths() -> None:
    session, parent_handle = _session()
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
        "version": "2022.1",
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
            "override_parent_instance_limit": True,
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
            "language": "SFX",
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
            "language": "SFX",
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
            {"x": 100, "y": 0, "shape": "SCurve"},
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
