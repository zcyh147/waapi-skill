from __future__ import annotations

import math
from pathlib import Path

import pytest

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import BusinessContext, BusinessDeclarationError
from wwise_waapi.project_setting_business import (
    materialize_project_setting_business_request,
)
from wwise_waapi.operation_registry import (
    parse_operation_request,
    prepare_operation,
    verify_prepared_operation,
)
from wwise_waapi.project_setting_business_contracts import (
    GAME_PARAMETER_SET_RANGE_URI,
    SOUND_SET_ACTIVE_SOURCE_URI,
    project_setting_business_contract_data,
    project_setting_business_operations,
    project_setting_business_versions,
)
from wwise_waapi.source_control_business_contracts import (
    SOURCE_CONTROL_COMMIT_URI,
    SOURCE_CONTROL_GET_SOURCE_FILES_URI,
    SOURCE_CONTROL_GET_STATUS_URI,
    SOURCE_CONTROL_MOVE_URI,
    SOURCE_CONTROL_SET_PROVIDER_URI,
    source_control_business_contract_data,
    source_control_business_operations,
    source_control_business_versions,
)
from wwise_waapi.source_control_business import (
    materialize_source_control_business_request,
    normalize_source_control_result,
)


SOUND_ID = "{11111111-1111-1111-1111-111111111111}"
SOURCE_ID = "{22222222-2222-2222-2222-222222222222}"
GAME_PARAMETER_ID = "{33333333-3333-3333-3333-333333333333}"


def test_issue_86_contracts_partition_all_forty_three_exact_rows() -> None:
    project_rows = {
        (operation, version)
        for operation in project_setting_business_operations()
        for version in project_setting_business_versions(operation)
    }
    source_control_rows = {
        (operation, version)
        for operation in source_control_business_operations()
        for version in source_control_business_versions(operation)
    }

    assert project_rows == {
        (SOUND_SET_ACTIVE_SOURCE_URI, "2022.1"),
        (SOUND_SET_ACTIVE_SOURCE_URI, "2023.1"),
        (SOUND_SET_ACTIVE_SOURCE_URI, "2024.1"),
        (SOUND_SET_ACTIVE_SOURCE_URI, "2025.1"),
        (GAME_PARAMETER_SET_RANGE_URI, "2024.1"),
        (GAME_PARAMETER_SET_RANGE_URI, "2025.1"),
    }
    assert len(source_control_rows) == 27
    assert len(project_rows) + len(source_control_rows) + 10 == 43


def _session(version: str = "2025.1") -> tuple[BusinessDeclarationSession, dict[str, str]]:
    context = BusinessContext.create(
        task_authority="da1-" + "8" * 40,
        project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        project_path="/fixtures/SampleProject.wproj",
        wwise_version=version,
        wwise_build=f"{version}.fixture",
    )
    session = BusinessDeclarationSession.create(context)
    sound = session.handles.bind_object(
        object_id=SOUND_ID,
        name="Weather_Loop",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather_Loop",
        role="sound",
    )
    source = session.handles.bind_object(
        object_id=SOURCE_ID,
        name="Weather_Loop_Alt",
        object_type="AudioFileSource",
        path=(
            r"\Actor-Mixer Hierarchy\Default Work Unit\Weather_Loop"
            r"\Weather_Loop_Alt"
        ),
        role="source",
    )
    game_parameter = session.handles.bind_object(
        object_id=GAME_PARAMETER_ID,
        name="WeatherIntensity",
        object_type="GameParameter",
        path=r"\Game Parameters\Default Work Unit\WeatherIntensity",
        role="game_parameter",
    )
    return session, {
        "sound": sound.handle,
        "source": source.handle,
        "game_parameter": game_parameter.handle,
    }


def test_set_active_source_compiles_two_typed_roles_and_optional_platform() -> None:
    session, handles = _session()
    session = session.with_settings(
        {
            "project_setting_plan": {
                "sound_handle": handles["sound"],
                "source_handle": handles["source"],
                "platform_name": "Windows",
            }
        }
    )

    request = materialize_project_setting_business_request(
        SOUND_SET_ACTIVE_SOURCE_URI,
        session,
    )

    assert request["operation"] == "waapi.call"
    assert request["arguments"] == {
        "api": SOUND_SET_ACTIVE_SOURCE_URI,
        "args": {
            "sound": SOUND_ID,
            "source": SOURCE_ID,
            "platform": "Windows",
        },
        "options": {},
    }
    prepared = prepare_operation(
        parse_operation_request(request),
        read_call=lambda *_args, **_kwargs: pytest.fail(
            "active-source preparation performed a read"
        ),
    ).as_dict()
    assert prepared["verification_plan"] == {
        "kind": "project-setting-state",
        "uri": SOUND_SET_ACTIVE_SOURCE_URI,
        "version": "2025.1",
        "strategy": "operation_specific_readback",
        "base_result_strategy": "result_schema",
        "object_id": SOUND_ID,
        "expected_active_source_id": SOURCE_ID,
        "platform": "Windows",
    }
    verification = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=lambda uri, args, options: {
            "return": [
                {
                    "id": SOUND_ID,
                    "name": "Weather_Loop",
                    "type": "Sound",
                    "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather_Loop",
                    "activeSource": {"id": SOURCE_ID},
                }
            ]
        },
    )
    assert verification.ok is True
    assert verification.business_state_verified is True


@pytest.mark.parametrize(
    ("curve_outcome", "native"),
    (("stretch", "stretch"), ("preserve-x", "preserveX")),
)
def test_set_game_parameter_range_compiles_business_outcome(
    curve_outcome: str,
    native: str,
) -> None:
    session, handles = _session()
    session = session.with_settings(
        {
            "project_setting_plan": {
                "game_parameter_handle": handles["game_parameter"],
                "minimum": -10.0,
                "maximum": 100.0,
                "curve_update_outcome": curve_outcome,
            }
        }
    )

    request = materialize_project_setting_business_request(
        GAME_PARAMETER_SET_RANGE_URI,
        session,
    )

    assert request["arguments"] == {
        "api": GAME_PARAMETER_SET_RANGE_URI,
        "args": {
            "object": GAME_PARAMETER_ID,
            "min": -10.0,
            "max": 100.0,
            "onCurveUpdate": native,
        },
        "options": {},
    }
    prepared = prepare_operation(
        parse_operation_request(request),
        read_call=lambda *_args, **_kwargs: pytest.fail(
            "range preparation performed a read"
        ),
    ).as_dict()
    assert prepared["verification_plan"] == {
        "kind": "project-setting-state",
        "uri": GAME_PARAMETER_SET_RANGE_URI,
        "version": "2025.1",
        "strategy": "operation_specific_readback",
        "base_result_strategy": "result_schema",
        "object_id": GAME_PARAMETER_ID,
        "expected_minimum": -10.0,
        "expected_maximum": 100.0,
    }
    verification = verify_prepared_operation(
        prepared,
        execution_result={"result": {}},
        read_call=lambda uri, args, options: {
            "return": [
                {
                    "id": GAME_PARAMETER_ID,
                    "name": "WeatherIntensity",
                    "type": "GameParameter",
                    "path": r"\Game Parameters\Default Work Unit\WeatherIntensity",
                    "@Min": -10.0,
                    "@Max": 100.0,
                }
            ]
        },
    )
    assert verification.ok is True
    assert verification.business_state_verified is True


@pytest.mark.parametrize(
    "minimum,maximum",
    ((1.0, 1.0), (2.0, 1.0), (math.nan, 1.0), (0.0, math.inf)),
)
def test_set_game_parameter_range_rejects_empty_or_hostile_ranges(
    minimum: float,
    maximum: float,
) -> None:
    session, handles = _session()
    with pytest.raises(BusinessDeclarationError):
        session = session.with_settings(
            {
                "project_setting_plan": {
                    "game_parameter_handle": handles["game_parameter"],
                    "minimum": minimum,
                    "maximum": maximum,
                    "curve_update_outcome": "stretch",
                }
            }
        )
        materialize_project_setting_business_request(
            GAME_PARAMETER_SET_RANGE_URI,
            session,
        )


def test_project_setting_contracts_expose_only_business_fields() -> None:
    active = project_setting_business_contract_data(
        SOUND_SET_ACTIVE_SOURCE_URI,
        "2025.1",
    )
    range_contract = project_setting_business_contract_data(
        GAME_PARAMETER_SET_RANGE_URI,
        "2025.1",
    )

    assert active["declaration"]["field_types"] == {
        "sound_handle": "bound_sound_handle",
        "source_handle": "bound_audio_file_source_handle",
        "platform_name": "platform_name",
    }
    assert range_contract["declaration"]["field_types"] == {
        "game_parameter_handle": "bound_game_parameter_handle",
        "minimum": "finite_number",
        "maximum": "finite_number",
        "curve_update_outcome": "range_curve_update_outcome",
    }
    for contract in (active, range_contract):
        assert contract["input_mode"] == "business_declaration"
        assert contract["execution_shape"] == "draft_mutation"
        assert contract["legacy_typed_call_public"] is False
        assert contract["start"]["gateway_argv"] == [
            "draft-start",
            contract["operation"],
        ]


def test_source_control_contracts_close_provider_and_native_request_boundaries() -> None:
    for operation in source_control_business_operations():
        for version in source_control_business_versions(operation):
            contract = source_control_business_contract_data(operation, version)
            assert contract["legacy_typed_call_public"] is False
            assert contract["native_request_input"] == "forbidden"
            if operation == SOURCE_CONTROL_SET_PROVIDER_URI:
                assert contract["execution_shape"] == "prohibited_boundary"
                assert contract["boundary"]["error_code"] == (
                    "SOURCE_CONTROL_PROVIDER_CONFIGURATION_REQUIRED"
                )
                assert "start" not in contract
            else:
                assert contract["execution_shape"] in {
                    "isolated_draft_external",
                }
                argv = contract["start"].get(
                    "gateway_argv_prefix",
                    contract["start"].get("gateway_argv"),
                )
                assert argv[0] == "draft-start"


def test_every_executable_source_control_row_uses_one_business_adapter() -> None:
    for operation in source_control_business_operations() - {
        SOURCE_CONTROL_SET_PROVIDER_URI
    }:
        adapter = business_adapter(operation)
        assert adapter.family == "source-control-business"
        assert adapter.update_commands == frozenset(
            {"draft-declare-source-control-plan"}
        )


def _source_control_session(
    tmp_path: Path,
    plan: dict[str, object],
) -> BusinessDeclarationSession:
    project_root = tmp_path / "SampleProject"
    originals = project_root / "Originals"
    originals.mkdir(parents=True, exist_ok=True)
    project_file = project_root / "SampleProject.wproj"
    project_file.write_text("fixture", encoding="utf-8")
    context = BusinessContext.create(
        task_authority="da1-" + "7" * 40,
        project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        project_path=str(project_file),
        wwise_version="2025.1",
        wwise_build="2025.1.fixture",
    )
    return BusinessDeclarationSession.create(context).with_settings(
        {
            "source_control_roots": {
                "project": str(project_root),
                "originals": str(originals),
            },
            "source_control_plan": plan,
        }
    )


def test_source_control_status_localizes_project_originals_and_exact_files(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "SampleProject" / "Actor-Mixer Hierarchy" / "A.wwu"
    original = tmp_path / "SampleProject" / "Originals" / "SFX" / "Rain.wav"
    external_root = tmp_path / "approved"
    external = external_root / "notes.txt"
    for path in (project_file, original, external):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    session = _source_control_session(
        tmp_path,
        {
            "files": [
                {"scope": "project", "path": "Actor-Mixer Hierarchy/A.wwu"},
                {"scope": "originals", "path": "SFX/Rain.wav"},
                {"scope": "exact", "path": str(external)},
            ],
            "io_root": str(external_root),
        },
    )

    request = materialize_source_control_business_request(
        SOURCE_CONTROL_GET_STATUS_URI,
        session,
    )

    assert request["arguments"]["args"] == {
        "files": [str(project_file), str(original), str(external)]
    }
    assert "io_root" not in request["arguments"]


def test_source_control_commit_keeps_message_exact_and_gateway_owns_io_root(
    tmp_path: Path,
) -> None:
    work_unit = tmp_path / "SampleProject" / "Events" / "Default Work Unit.wwu"
    work_unit.parent.mkdir(parents=True)
    work_unit.write_text("fixture", encoding="utf-8")
    message = 'Fix Weather: preserve "Rain"; no shell reconstruction'
    session = _source_control_session(
        tmp_path,
        {
            "files": [{"scope": "project", "path": "Events/Default Work Unit.wwu"}],
            "commit_message": message,
        },
    )

    request = materialize_source_control_business_request(
        SOURCE_CONTROL_COMMIT_URI,
        session,
    )

    assert request["arguments"] == {
        "api": SOURCE_CONTROL_COMMIT_URI,
        "args": {"files": [str(work_unit)], "message": message},
        "options": {},
        "io_root": str(tmp_path / "SampleProject"),
    }


def test_source_control_move_compiles_aligned_native_path_arrays(tmp_path: Path) -> None:
    source = tmp_path / "SampleProject" / "Events" / "Old.wwu"
    source.parent.mkdir(parents=True)
    source.write_text("fixture", encoding="utf-8")
    destination = tmp_path / "SampleProject" / "Events" / "New.wwu"
    session = _source_control_session(
        tmp_path,
        {
            "moves": [
                {
                    "source": {"scope": "project", "path": "Events/Old.wwu"},
                    "destination": {"scope": "project", "path": "Events/New.wwu"},
                }
            ]
        },
    )

    request = materialize_source_control_business_request(SOURCE_CONTROL_MOVE_URI, session)

    assert request["arguments"]["args"] == {
        "files": [str(source)],
        "newFiles": [str(destination)],
    }


def test_source_file_read_compiles_fixed_projection_and_bounded_result(
    tmp_path: Path,
) -> None:
    session = _source_control_session(
        tmp_path,
        {
            "usage_scope": "unused",
            "originals_folder": "SFX/Weather",
            "recursive": False,
            "include_usage_objects": True,
            "max_results": 2,
        },
    )

    request = materialize_source_control_business_request(
        SOURCE_CONTROL_GET_SOURCE_FILES_URI,
        session,
    )
    normalized = normalize_source_control_result(
        SOURCE_CONTROL_GET_SOURCE_FILES_URI,
        {"return": [{"file": "a.wav"}, {"file": "b.wav"}, {"file": "c.wav"}]},
        session,
    )

    assert request["arguments"] == {
        "api": SOURCE_CONTROL_GET_SOURCE_FILES_URI,
        "args": {"filter": "unused", "folder": str(Path("SFX") / "Weather"), "recursive": False},
        "options": {
            "return": ["file", "folder", "isUsed", "isMissing", "usage"],
            "objectReturn": ["id", "name", "type", "path"],
        },
        "result_projection": {
            "kind": "source-control-files",
            "max_results": 2,
        },
    }
    assert normalized == {
        "items": [{"file": "a.wav"}, {"file": "b.wav"}],
        "returned_count": 2,
        "total_count": 3,
        "truncated": True,
        "max_results": 2,
    }
    prepared = prepare_operation(
        parse_operation_request(request),
        read_call=lambda *_args, **_kwargs: pytest.fail(
            "source-file projection preparation performed a read"
        ),
    ).as_dict()
    assert prepared["verification_plan"]["result_projection"] == {
        "kind": "source-control-files",
        "max_results": 2,
    }


@pytest.mark.parametrize(
    "plan",
    (
        {"files": [{"scope": "project", "path": "../escape.wwu"}]},
        {"files": [{"scope": "exact", "path": "/tmp/unowned.wwu"}]},
        {"files": []},
    ),
)
def test_source_control_file_plans_fail_closed_on_hostile_or_unowned_paths(
    tmp_path: Path,
    plan: dict[str, object],
) -> None:
    session = _source_control_session(tmp_path, plan)
    with pytest.raises(BusinessDeclarationError):
        materialize_source_control_business_request(
            SOURCE_CONTROL_GET_STATUS_URI,
            session,
        )
