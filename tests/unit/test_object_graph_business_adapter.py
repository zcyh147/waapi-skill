from __future__ import annotations

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    NewDescendantTarget,
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
