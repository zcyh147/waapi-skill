from __future__ import annotations

from pathlib import Path

import pytest

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
)
from wwise_waapi.exact_artifact_business import (
    materialize_exact_artifact_business_request,
)
from wwise_waapi.exact_artifact_business_contracts import (
    EXACT_ARTIFACT_BUSINESS_OPERATIONS,
    exact_artifact_business_contract_data,
)
from wwise_waapi.exact_artifact_business_cli import (
    _typed_value,
)
from wwise_waapi.operation_registry import (
    BUSINESS_DECLARATION_INPUT_MODE,
    operation_input_mode,
    parse_operation_request,
)


LANES = {
    "audio.importTabDelimited": (
        "2021.1",
        "2022.1",
        "2023.1",
        "2024.1",
        "2025.1",
    ),
    "lua.executeCliFile": ("2023.1", "2024.1", "2025.1"),
    "lua.executeCoreFile": ("2023.1", "2024.1", "2025.1"),
    "lua.executeCoreInline": ("2025.1",),
}


def _session(version: str) -> BusinessDeclarationSession:
    return BusinessDeclarationSession.create(
        BusinessContext.create(
            task_authority="da1-" + "1" * 40,
            project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            project_path="/fixtures/SampleProject.wproj",
            wwise_version=version,
            wwise_build=f"{version}.fixture",
        )
    )


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation, versions in LANES.items()
        for version in versions
    ],
)
def test_every_exact_artifact_lane_uses_one_complete_business_plan(
    operation: str,
    version: str,
) -> None:
    contract = exact_artifact_business_contract_data(operation, version)

    assert set(EXACT_ARTIFACT_BUSINESS_OPERATIONS) == set(LANES)
    assert operation_input_mode(operation, version) == (
        BUSINESS_DECLARATION_INPUT_MODE
    )
    assert contract["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert contract["declaration"]["subcommand"] == (
        "draft-declare-artifact-plan"
    )
    assert contract["legacy_composer_public"] is False
    assert contract["legacy_inline_typed_public"] is False
    assert "source_authority" not in contract["declaration"]["public_fields"]
    adapter = business_adapter(operation)
    assert adapter.family == "exact-artifact-code"
    assert adapter.accepts_update_command("draft-declare-artifact-plan")


def test_tab_import_plan_derives_native_fields_from_bound_location(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Import 表.tsv"
    source.write_bytes(
        b"Audio File\tObject Path\nvoice.wav\t\\Actor-Mixer Hierarchy\\Voice\n"
    )
    session = _session("2025.1")
    location = session.handles.bind_object(
        object_id="{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        name="Default Work Unit",
        object_type="WorkUnit",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit",
        role="import_location",
    )
    session = session.with_settings(
        {
            "artifact_plan": {
                "table_file": str(source),
                "location_handle": location.handle,
                "language": "English(US)",
                "mode": "replace",
                "add_to_source_control": True,
                "check_out_from_source_control": False,
            }
        }
    )

    request = materialize_exact_artifact_business_request(
        "audio.importTabDelimited",
        session,
    )

    assert request["arguments"] == {
        "import_file": str(source),
        "import_location": {
            "kind": "id",
            "value": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        },
        "import_language": "English(US)",
        "import_operation": "replaceExisting",
        "auto_add_to_source_control": True,
        "auto_check_out_to_source_control": False,
    }
    parse_operation_request(request, expected_version="2025.1")


@pytest.mark.parametrize(
    "operation",
    ("lua.executeCliFile", "lua.executeCoreFile"),
)
def test_lua_file_plan_derives_root_authority_and_loader(
    tmp_path: Path,
    operation: str,
) -> None:
    script = tmp_path / "用户 script.lua"
    script.write_bytes(b"return wa_args.request_id\n")
    plan = {
        "script_file": str(script),
        "arguments": {"request_id": "alpha", "nested": {"x": 1}},
    }
    if operation == "lua.executeCliFile":
        plan["watchdog_seconds"] = 15
    session = _session("2025.1").with_settings({"artifact_plan": plan})

    request = materialize_exact_artifact_business_request(operation, session)

    expected = {
        "script_file": str(script),
        "io_root": str(tmp_path),
        "source_authority": "user_supplied_verbatim",
        "wa_args": {"request_id": "alpha", "nested": {"x": 1}},
    }
    if operation == "lua.executeCliFile":
        expected["watchdog_seconds"] = 15
    assert request["arguments"] == expected
    parse_operation_request(request, expected_version="2025.1")


def test_inline_lua_plan_preserves_exact_source_and_derives_authority(
    tmp_path: Path,
) -> None:
    source = "local 名称 = wa_args.name\nreturn 名称 .. '\\n'\n"
    session = _session("2025.1").with_settings(
        {
            "artifact_plan": {
                "lua_source": source,
                "io_root": str(tmp_path),
                "arguments": {"name": "天气"},
            }
        }
    )

    request = materialize_exact_artifact_business_request(
        "lua.executeCoreInline",
        session,
    )

    assert request["arguments"] == {
        "lua_code": source,
        "io_root": str(tmp_path),
        "source_authority": "user_supplied_verbatim",
        "wa_args": {"name": "天气"},
    }
    parse_operation_request(request, expected_version="2025.1")


def test_lua_business_cli_preserves_every_strict_json_value_kind() -> None:
    assert _typed_value("string", "null") == "null"
    assert _typed_value("boolean", "false") is False
    assert _typed_value("integer", "4") == 4
    assert _typed_value("number", "-1.25") == -1.25
    assert _typed_value("json", '{"nested":[1,true,null]}') == {
        "nested": [1, True, None]
    }
    assert _typed_value("null", "null") is None

    with pytest.raises(ValueError, match="null argument"):
        _typed_value("null", '"null"')


def test_lua_contract_discloses_recursive_strict_json_values() -> None:
    contract = exact_artifact_business_contract_data(
        "lua.executeCoreInline",
        "2025.1",
    )
    schema = contract["declaration"]["schema"]

    assert schema["properties"]["arguments"]["additionalProperties"] == {
        "$ref": "#/$defs/strictJsonValue"
    }
    value_schema = schema["$defs"]["strictJsonValue"]
    assert {row["type"] for row in value_schema["anyOf"]} == {
        "array",
        "boolean",
        "integer",
        "null",
        "number",
        "object",
        "string",
    }
    array = next(row for row in value_schema["anyOf"] if row["type"] == "array")
    object_value = next(
        row for row in value_schema["anyOf"] if row["type"] == "object"
    )
    assert array["items"] == {"$ref": "#/$defs/strictJsonValue"}
    assert object_value["additionalProperties"] == {
        "$ref": "#/$defs/strictJsonValue"
    }


@pytest.mark.parametrize(
    ("script_file", "sealed_io_root"),
    (
        ("/owned/sub/../script.lua", "/owned"),
        (r"C:\owned\script.lua", r"C:\owned"),
        (r"\\server\share\owned\script.lua", r"\\server\share\owned"),
    ),
)
def test_cleaned_file_replay_uses_persisted_canonical_root_without_host_parsing(
    script_file: str,
    sealed_io_root: str,
) -> None:
    session = _session("2025.1").with_settings(
        {
            "artifact_plan": {"script_file": script_file},
            "artifact_evidence": {
                "contract": "waapi-skill.exact-artifact-evidence/v1",
                "io_root": sealed_io_root,
            },
        }
    )

    request = materialize_exact_artifact_business_request(
        "lua.executeCoreFile",
        session,
        allow_cleaned_file_evidence=True,
    )

    assert request["arguments"]["script_file"] == script_file
    assert request["arguments"]["io_root"] == sealed_io_root


def test_cleaned_file_replay_requires_persisted_canonical_root() -> None:
    session = _session("2025.1").with_settings(
        {"artifact_plan": {"script_file": "/owned/script.lua"}}
    )

    with pytest.raises(BusinessDeclarationError) as exc_info:
        materialize_exact_artifact_business_request(
            "lua.executeCoreFile",
            session,
            allow_cleaned_file_evidence=True,
        )
    assert exc_info.value.repair["error_code"] == "ARCHIVE_EVIDENCE_REQUIRED"


@pytest.mark.parametrize("reserved", ("luaScript", "doFiles", "requires"))
def test_lua_business_plan_rejects_reserved_loader_fields(
    tmp_path: Path,
    reserved: str,
) -> None:
    session = _session("2025.1").with_settings(
        {
            "artifact_plan": {
                "lua_source": "return true\n",
                "io_root": str(tmp_path),
                "arguments": {reserved: "blocked"},
            }
        }
    )

    with pytest.raises(BusinessDeclarationError) as exc_info:
        materialize_exact_artifact_business_request(
            "lua.executeCoreInline",
            session,
        )
    assert exc_info.value.repair["error_code"] == "RESERVED_ARGUMENT"
