from __future__ import annotations

import os
from pathlib import Path

import pytest

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
)
from wwise_waapi.core_business import materialize_core_business_request
from wwise_waapi.core_business_contracts import (
    core_business_contract_data,
    core_business_operations,
)


SOURCE_ID = "{11111111-1111-1111-1111-111111111111}"
TARGET_ID = "{22222222-2222-2222-2222-222222222222}"

VERSIONS_BY_OPERATION = {
    "ak.wwise.core.object.setAttenuationCurve": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.object.setRandomizer": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.switchContainer.getAssignments": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.object.diff": ("2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.object.pasteProperties": ("2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.audio.mute": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.audio.solo": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.object.isLinked": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.object.setStateGroups": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.object.setStateProperties": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.project.save": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.core.audio.convert": ("2024.1", "2025.1"),
    "ak.wwise.core.audio.setConversionPlugin": ("2024.1", "2025.1"),
    "ak.wwise.core.blendContainer.addAssignment": ("2024.1", "2025.1"),
    "ak.wwise.core.blendContainer.addTrack": ("2024.1", "2025.1"),
    "ak.wwise.core.blendContainer.getAssignments": ("2024.1", "2025.1"),
    "ak.wwise.core.blendContainer.removeAssignment": ("2024.1", "2025.1"),
    "ak.wwise.core.workUnit.load": ("2025.1",),
    "ak.wwise.core.workUnit.unload": ("2025.1",),
}


def test_exact_issue_84_version_surface_has_one_core_business_contract_per_lane() -> None:
    assert core_business_operations() == frozenset(VERSIONS_BY_OPERATION)
    observed = {
        (operation, version)
        for operation, versions in VERSIONS_BY_OPERATION.items()
        for version in versions
        if core_business_contract_data(operation, version)
    }
    assert len(observed) == 55
    for operation, version in observed:
        contract = core_business_contract_data(operation, version)
        assert contract["legacy_typed_call_public"] is False
        assert contract["execution_shape"] in {"bounded_read", "draft_mutation"}
        assert contract["declaration"]["field_types"]


def _session(version: str = "2025.1") -> tuple[BusinessDeclarationSession, str, str]:
    context = BusinessContext.create(
        task_authority="da1-" + "1" * 40,
        project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        project_path="/fixtures/SampleProject.wproj",
        wwise_version=version,
        wwise_build=f"{version}.fixture",
    )
    session = BusinessDeclarationSession.create(context)
    source = session.handles.bind_object(
        object_id=SOURCE_ID,
        name="Source",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Source",
        role="source",
    )
    target = session.handles.bind_object(
        object_id=TARGET_ID,
        name="Target",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Target",
        role="target",
    )
    return session, source.handle, target.handle


def _role_session(
    roles: tuple[str, ...],
    *,
    version: str = "2025.1",
) -> tuple[BusinessDeclarationSession, list[str], list[str]]:
    context = BusinessContext.create(
        task_authority="da1-" + "2" * 40,
        project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        project_path="/fixtures/SampleProject.wproj",
        wwise_version=version,
        wwise_build=f"{version}.fixture",
    )
    session = BusinessDeclarationSession.create(context)
    handles: list[str] = []
    ids: list[str] = []
    for index, role in enumerate(roles, start=1):
        object_id = f"{{00000000-0000-0000-0000-{index:012d}}}"
        bound = session.handles.bind_object(
            object_id=object_id,
            name=f"Object_{index}",
            object_type=("StateGroup" if role == "state_group" else "Sound"),
            path=rf"\Actor-Mixer Hierarchy\Default Work Unit\Object_{index}",
            role=role,
        )
        handles.append(bound.handle)
        ids.append(object_id)
    return session, handles, ids


def test_object_diff_business_interface_compiles_two_roles_without_typed_fields() -> None:
    operation = "ak.wwise.core.object.diff"
    session, source, target = _session()
    session = session.with_settings(
        {
            "core_plan": {
                "source_handle": source,
                "target_handle": target,
            }
        }
    )

    request = materialize_core_business_request(operation, session)

    assert request == {
        "contract": "waapi-skill.core-business-call/v1",
        "version": "2025.1",
        "api": operation,
        "args": {
            "source": SOURCE_ID,
            "target": TARGET_ID,
        },
        "options": {},
    }


def test_object_diff_contract_exposes_business_roles_and_no_typed_fallback() -> None:
    operation = "ak.wwise.core.object.diff"

    contract = core_business_contract_data(operation, "2025.1")

    assert contract["input_mode"] == "business_declaration"
    assert contract["binding"] == {
        "roles": ["source", "target"],
        "role_fields": [
            {"role": "source", "field": "source_id", "cardinality": "exactly_one"},
            {"role": "target", "field": "target_id", "cardinality": "exactly_one"},
        ],
        "role_required": True,
        "identity": "gateway_evidence_object_id",
        "validation": "exact_guid_name_type_path",
    }
    assert contract["declaration"] == {
        "subcommand": "core-call",
        "required_fields": ["source_id", "target_id"],
        "optional_fields": [],
        "field_types": {
            "source_id": "gateway_evidence_object_id",
            "target_id": "gateway_evidence_object_id",
        },
        "input_forms": {
            "source_id": {"flag": "--source-id", "repeatable": False},
            "target_id": {"flag": "--target-id", "repeatable": False},
        },
    }
    assert contract["legacy_typed_call_public"] is False
    assert contract["execution_shape"] == "bounded_read"
    assert "native_request" in contract["gateway_derivations"]


def test_project_save_business_interface_derives_zero_or_one_stable_setting() -> None:
    operation = "ak.wwise.core.project.save"
    session, _source, _target = _session("2025.1")
    session = session.with_settings(
        {"core_plan": {"auto_check_out": True}}
    )

    request = materialize_core_business_request(operation, session)

    assert request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "waapi.call",
        "arguments": {
            "api": operation,
            "args": {"autoCheckOutToSourceControl": True},
            "options": {},
        },
    }
    adapter = business_adapter(operation)
    assert adapter.family == "core-project-object"
    assert adapter.accepts_update_command("draft-declare-core-plan") is True


@pytest.mark.parametrize(
    ("operation", "roles", "plan_factory", "native_factory", "read_shape"),
    [
        (
            "ak.wwise.core.switchContainer.getAssignments",
            ("switch_container",),
            lambda h: {"switch_container_handle": h[0]},
            lambda ids: {"id": ids[0]},
            True,
        ),
        (
            "ak.wwise.core.audio.mute",
            ("object", "object"),
            lambda h: {"object_handles": h, "muted": True},
            lambda ids: {"objects": ids, "value": True},
            False,
        ),
        (
            "ak.wwise.core.audio.solo",
            ("object", "object"),
            lambda h: {"object_handles": h, "soloed": False},
            lambda ids: {"objects": ids, "value": False},
            False,
        ),
        (
            "ak.wwise.core.object.setStateGroups",
            ("object", "state_group"),
            lambda h: {"object_handle": h[0], "state_group_handles": [h[1]]},
            lambda ids: {"object": ids[0], "stateGroups": [ids[1]]},
            False,
        ),
        (
            "ak.wwise.core.blendContainer.getAssignments",
            ("blend_track",),
            lambda h: {"blend_track_handle": h[0]},
            lambda ids: {"object": ids[0]},
            True,
        ),
        (
            "ak.wwise.core.workUnit.load",
            ("work_unit",),
            lambda h: {"work_unit_handle": h[0]},
            lambda ids: {"object": ids[0]},
            False,
        ),
        (
            "ak.wwise.core.workUnit.unload",
            ("work_unit",),
            lambda h: {"work_unit_handle": h[0]},
            lambda ids: {"object": ids[0]},
            False,
        ),
    ],
)
def test_simple_core_business_outcomes_compile_only_bound_roles(
    operation: str,
    roles: tuple[str, ...],
    plan_factory: object,
    native_factory: object,
    read_shape: bool,
) -> None:
    session, handles, ids = _role_session(roles)
    plan = plan_factory(handles)  # type: ignore[operator]
    session = session.with_settings({"core_plan": plan})

    request = materialize_core_business_request(operation, session)

    expected_args = native_factory(ids)  # type: ignore[operator]
    if read_shape:
        assert request["contract"] == "waapi-skill.core-business-call/v1"
        assert request["args"] == expected_args
    else:
        assert request["operation"] == "waapi.call"
        assert request["arguments"] == {
            "api": operation,
            "args": expected_args,
            "options": {},
        }


def _bind_property(
    session: BusinessDeclarationSession,
    *,
    object_id: str,
    token: str,
    platform: str | None = None,
) -> str:
    return session.handles.bind_field(
        scope_kind="object",
        scope_value=object_id,
        token=token,
        field_kind="property",
        value_type="number",
        platform=platform,
        restrictions={},
        metadata_digest="a" * 64,
    ).handle


def test_metadata_core_business_fields_compile_bound_tokens_and_platform() -> None:
    session, handles, ids = _role_session(("object",))
    volume = _bind_property(
        session,
        object_id=ids[0],
        token="Volume",
        platform="Windows",
    )
    randomizer = session.with_settings(
        {
            "core_plan": {
                "object_handle": handles[0],
                "field_handle": volume,
                "enabled": True,
                "minimum_offset": -3.0,
                "maximum_offset": 5.0,
                "platform_name": "Windows",
            }
        }
    )
    linked = session.with_settings(
        {
            "core_plan": {
                "object_handle": handles[0],
                "field_handle": volume,
                "platform_name": "Windows",
            }
        }
    )
    pitch = _bind_property(session, object_id=ids[0], token="Pitch")
    states = session.with_settings(
        {
            "core_plan": {
                "object_handle": handles[0],
                "field_handles": [volume, pitch],
            }
        }
    )

    assert materialize_core_business_request(
        "ak.wwise.core.object.setRandomizer", randomizer
    )["arguments"]["args"] == {
        "object": ids[0],
        "property": "Volume",
        "enabled": True,
        "min": -3.0,
        "max": 5.0,
        "platform": "Windows",
    }
    assert materialize_core_business_request(
        "ak.wwise.core.object.isLinked", linked
    )["args"] == {
        "object": ids[0],
        "property": "Volume",
        "platform": "Windows",
    }
    assert materialize_core_business_request(
        "ak.wwise.core.object.setStateProperties", states
    )["arguments"]["args"] == {
        "object": ids[0],
        "stateProperties": ["Volume", "Pitch"],
    }


def test_paste_convert_and_conversion_plugin_compile_business_collections(
    tmp_path: Path,
) -> None:
    paste_session, paste_handles, paste_ids = _role_session(
        ("source", "target", "target")
    )
    volume = _bind_property(
        paste_session,
        object_id=paste_ids[0],
        token="Volume",
    )
    paste_session = paste_session.with_settings(
        {
            "core_plan": {
                "source_handle": paste_handles[0],
                "target_handles": paste_handles[1:],
                "include_field_handles": [volume],
                "list_mode": "merge-replace",
            }
        }
    )
    paste = materialize_core_business_request(
        "ak.wwise.core.object.pasteProperties",
        paste_session,
    )
    assert paste["arguments"]["args"] == {
        "source": paste_ids[0],
        "targets": paste_ids[1:],
        "inclusion": ["Volume"],
        "pasteMode": "addReplace",
    }

    convert_session, convert_handles, convert_ids = _role_session(
        ("audio_object", "audio_object")
    )
    convert_session = convert_session.with_settings(
        {
            "core_plan": {
                "audio_object_handles": convert_handles,
                "platform_names": ["Windows", "Mac"],
                "languages": ["SFX", "English(US)"],
                "io_root": str(tmp_path / "waapi-convert-output"),
            }
        }
    )
    convert = materialize_core_business_request(
        "ak.wwise.core.audio.convert",
        convert_session,
    )
    assert convert["arguments"]["args"] == {
        "objects": convert_ids,
        "platforms": ["Windows", "Mac"],
        "languages": ["SFX", "English(US)"],
    }

    plugin_session, plugin_handles, plugin_ids = _role_session(("conversion",))
    plugin_session = plugin_session.with_settings(
        {
            "core_plan": {
                "conversion_handle": plugin_handles[0],
                "platform_name": "Windows",
                "plugin_name": "Vorbis",
            }
        }
    )
    plugin = materialize_core_business_request(
        "ak.wwise.core.audio.setConversionPlugin",
        plugin_session,
    )
    assert plugin["arguments"]["args"] == {
        "conversion": plugin_ids[0],
        "platform": "Windows",
        "plugin": "Vorbis",
    }


def test_curve_and_blend_business_values_compile_native_enums_and_shapes() -> None:
    curve_session, curve_handles, curve_ids = _role_session(("attenuation",))
    curve_session = curve_session.with_settings(
        {
            "core_plan": {
                "attenuation_handle": curve_handles[0],
                "curve_kind": "volume-dry",
                "curve_source": "custom",
                "platform_name": "Windows",
                "points": [
                    {"x": 0.0, "y": 0.0, "shape": "linear"},
                    {"x": 100.0, "y": -96.0, "shape": "constant"},
                ],
            }
        }
    )
    curve = materialize_core_business_request(
        "ak.wwise.core.object.setAttenuationCurve",
        curve_session,
    )
    assert curve["arguments"]["args"] == {
        "object": curve_ids[0],
        "curveType": "VolumeDryUsage",
        "use": "Custom",
        "platform": "Windows",
        "points": [
            {"x": 0.0, "y": 0.0, "shape": "Linear"},
            {"x": 100.0, "y": -96.0, "shape": "Constant"},
        ],
    }

    assignment_session, assignment_handles, assignment_ids = _role_session(
        ("blend_track", "child")
    )
    assignment_session = assignment_session.with_settings(
        {
            "core_plan": {
                "blend_track_handle": assignment_handles[0],
                "child_handle": assignment_handles[1],
                "insertion_index": 1,
                "edges": [
                    {
                        "edge_position": 0.0,
                        "fade_mode": "manual",
                        "fade_position": 10.0,
                        "shape": "linear",
                    },
                    {
                        "edge_position": 100.0,
                        "fade_mode": "automatic",
                        "shape": "s-curve",
                    },
                ],
            }
        }
    )
    assignment = materialize_core_business_request(
        "ak.wwise.core.blendContainer.addAssignment",
        assignment_session,
    )
    assert assignment["arguments"]["args"] == {
        "object": assignment_ids[0],
        "child": assignment_ids[1],
        "index": 1,
        "edges": [
            {
                "edgePosition": 0.0,
                "fadeMode": "Manual",
                "fadePosition": 10.0,
                "fadeShape": "Linear",
            },
            {
                "edgePosition": 100.0,
                "fadeMode": "Automatic",
                "fadeShape": "SCurve",
            },
        ],
    }

    track_session, track_handles, track_ids = _role_session(("blend_container",))
    track_session = track_session.with_settings(
        {
            "core_plan": {
                "blend_container_handle": track_handles[0],
                "track_name": "Weather Blend",
            }
        }
    )
    assert materialize_core_business_request(
        "ak.wwise.core.blendContainer.addTrack", track_session
    )["arguments"]["args"] == {
        "object": track_ids[0],
        "name": "Weather Blend",
    }

    remove_session, remove_handles, remove_ids = _role_session(
        ("blend_track", "child")
    )
    remove_session = remove_session.with_settings(
        {
            "core_plan": {
                "blend_track_handle": remove_handles[0],
                "child_handle": remove_handles[1],
            }
        }
    )
    assert materialize_core_business_request(
        "ak.wwise.core.blendContainer.removeAssignment", remove_session
    )["arguments"]["args"] == {
        "object": remove_ids[0],
        "child": remove_ids[1],
    }


def _valid_lane_session(
    operation: str,
    version: str,
) -> BusinessDeclarationSession:
    role_map = {
        "ak.wwise.core.object.setAttenuationCurve": ("attenuation",),
        "ak.wwise.core.object.setRandomizer": ("object",),
        "ak.wwise.core.switchContainer.getAssignments": ("switch_container",),
        "ak.wwise.core.object.diff": ("source", "target"),
        "ak.wwise.core.object.pasteProperties": ("source", "target"),
        "ak.wwise.core.audio.mute": ("object",),
        "ak.wwise.core.audio.solo": ("object",),
        "ak.wwise.core.object.isLinked": ("object",),
        "ak.wwise.core.object.setStateGroups": ("object", "state_group"),
        "ak.wwise.core.object.setStateProperties": ("object",),
        "ak.wwise.core.project.save": (),
        "ak.wwise.core.audio.convert": ("audio_object",),
        "ak.wwise.core.audio.setConversionPlugin": ("conversion",),
        "ak.wwise.core.blendContainer.addAssignment": ("blend_track", "child"),
        "ak.wwise.core.blendContainer.addTrack": ("blend_container",),
        "ak.wwise.core.blendContainer.getAssignments": ("blend_track",),
        "ak.wwise.core.blendContainer.removeAssignment": ("blend_track", "child"),
        "ak.wwise.core.workUnit.load": ("work_unit",),
        "ak.wwise.core.workUnit.unload": ("work_unit",),
    }
    session, handles, ids = _role_session(role_map[operation], version=version)
    if operation == "ak.wwise.core.object.setAttenuationCurve":
        plan = {
            "attenuation_handle": handles[0],
            "curve_kind": "volume-dry",
            "curve_source": "custom",
            "points": [{"x": 0, "y": 0, "shape": "linear"}],
        }
    elif operation == "ak.wwise.core.object.setRandomizer":
        field = _bind_property(session, object_id=ids[0], token="Volume")
        plan = {
            "object_handle": handles[0],
            "field_handle": field,
            "enabled": True,
        }
    elif operation == "ak.wwise.core.switchContainer.getAssignments":
        plan = {"switch_container_handle": handles[0]}
    elif operation == "ak.wwise.core.object.diff":
        plan = {"source_handle": handles[0], "target_handle": handles[1]}
    elif operation == "ak.wwise.core.object.pasteProperties":
        plan = {"source_handle": handles[0], "target_handles": [handles[1]]}
    elif operation == "ak.wwise.core.audio.mute":
        plan = {"object_handles": handles, "muted": True}
    elif operation == "ak.wwise.core.audio.solo":
        plan = {"object_handles": handles, "soloed": True}
    elif operation == "ak.wwise.core.object.isLinked":
        field = _bind_property(session, object_id=ids[0], token="Volume")
        plan = {
            "object_handle": handles[0],
            "field_handle": field,
            "platform_name": "Windows",
        }
    elif operation == "ak.wwise.core.object.setStateGroups":
        plan = {"object_handle": handles[0], "state_group_handles": [handles[1]]}
    elif operation == "ak.wwise.core.object.setStateProperties":
        field = _bind_property(session, object_id=ids[0], token="Volume")
        plan = {"object_handle": handles[0], "field_handles": [field]}
    elif operation == "ak.wwise.core.project.save":
        plan = {}
    elif operation == "ak.wwise.core.audio.convert":
        plan = {
            "audio_object_handles": handles,
            "platform_names": ["Windows"],
            "languages": ["SFX"],
            "io_root": (
                r"C:\Temp\waapi-convert-output"
                if os.name == "nt"
                else "/tmp/waapi-convert-output"
            ),
        }
    elif operation == "ak.wwise.core.audio.setConversionPlugin":
        plan = {
            "conversion_handle": handles[0],
            "platform_name": "Windows",
            "plugin_name": "Vorbis",
        }
    elif operation == "ak.wwise.core.blendContainer.addAssignment":
        plan = {"blend_track_handle": handles[0], "child_handle": handles[1]}
    elif operation == "ak.wwise.core.blendContainer.addTrack":
        plan = {"blend_container_handle": handles[0], "track_name": "Track"}
    elif operation == "ak.wwise.core.blendContainer.getAssignments":
        plan = {"blend_track_handle": handles[0]}
    elif operation == "ak.wwise.core.blendContainer.removeAssignment":
        plan = {"blend_track_handle": handles[0], "child_handle": handles[1]}
    else:
        plan = {"work_unit_handle": handles[0]}
    return session.with_settings({"core_plan": plan})


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation, versions in VERSIONS_BY_OPERATION.items()
        for version in versions
    ],
)
def test_every_issue_84_version_lane_materializes_one_closed_request(
    operation: str,
    version: str,
) -> None:
    request = materialize_core_business_request(
        operation,
        _valid_lane_session(operation, version),
    )

    assert request["version"] == version
    if core_business_contract_data(operation, version)["execution_shape"] == "bounded_read":
        assert request["contract"] == "waapi-skill.core-business-call/v1"
        assert request["api"] == operation
    else:
        assert request["contract"] == "waapi-skill.operation-request/v1"
        assert request["operation"] == "waapi.call"
        assert request["arguments"]["api"] == operation


def test_core_business_repair_rejects_stale_handle_and_wrong_role() -> None:
    session, handles, _ids = _role_session(("source",))
    stale = session.with_settings(
        {"core_plan": {"work_unit_handle": "boh1-stale"}}
    )
    wrong_role = session.with_settings(
        {"core_plan": {"work_unit_handle": handles[0]}}
    )

    with pytest.raises(BusinessDeclarationError) as stale_error:
        materialize_core_business_request("ak.wwise.core.workUnit.load", stale)
    assert stale_error.value.error_code == "OBJECT_HANDLE_NOT_AVAILABLE"
    with pytest.raises(BusinessDeclarationError) as role_error:
        materialize_core_business_request("ak.wwise.core.workUnit.load", wrong_role)
    assert role_error.value.error_code == "BOUND_OBJECT_ROLE_MISMATCH"


def test_core_business_repair_rejects_native_enum_spelling_and_invalid_range() -> None:
    curve_session, curve_handles, _curve_ids = _role_session(("attenuation",))
    curve_session = curve_session.with_settings(
        {
            "core_plan": {
                "attenuation_handle": curve_handles[0],
                "curve_kind": "VolumeDryUsage",
                "curve_source": "Custom",
                "points": [{"x": 0, "y": 0, "shape": "Linear"}],
            }
        }
    )
    with pytest.raises(BusinessDeclarationError) as enum_error:
        materialize_core_business_request(
            "ak.wwise.core.object.setAttenuationCurve",
            curve_session,
        )
    assert enum_error.value.error_code == "BUSINESS_ENUM_INVALID"

    random_session, random_handles, random_ids = _role_session(("object",))
    field = _bind_property(random_session, object_id=random_ids[0], token="Volume")
    random_session = random_session.with_settings(
        {
            "core_plan": {
                "object_handle": random_handles[0],
                "field_handle": field,
                "minimum_offset": 1,
            }
        }
    )
    with pytest.raises(BusinessDeclarationError) as range_error:
        materialize_core_business_request(
            "ak.wwise.core.object.setRandomizer",
            random_session,
        )
    assert range_error.value.error_code == "BUSINESS_RANGE_INVALID"


def test_core_business_rejects_hostile_name_and_unavailable_version() -> None:
    session, handles, _ids = _role_session(("blend_container",))
    session = session.with_settings(
        {
            "core_plan": {
                "blend_container_handle": handles[0],
                "track_name": r"Track\<Injected>",
            }
        }
    )
    with pytest.raises(BusinessDeclarationError) as name_error:
        materialize_core_business_request(
            "ak.wwise.core.blendContainer.addTrack",
            session,
        )
    assert name_error.value.error_code == "BUSINESS_VALUE_INVALID"

    plugin_session, plugin_handles, _plugin_ids = _role_session(("conversion",))
    plugin_session = plugin_session.with_settings(
        {
            "core_plan": {
                "conversion_handle": plugin_handles[0],
                "platform_name": "Windows",
                "plugin_name": "x" * 257,
            }
        }
    )
    with pytest.raises(BusinessDeclarationError) as plugin_error:
        materialize_core_business_request(
            "ak.wwise.core.audio.setConversionPlugin",
            plugin_session,
        )
    assert plugin_error.value.error_code == "BUSINESS_VALUE_INVALID"

    unsupported, _handles, _ids = _role_session((), version="2022.1")
    unsupported = unsupported.with_settings({"core_plan": {}})
    with pytest.raises(ValueError, match="unavailable"):
        materialize_core_business_request(
            "ak.wwise.core.project.save",
            unsupported,
        )
