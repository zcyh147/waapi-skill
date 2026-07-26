from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.schema import validate_semantic_payload  # pyright: ignore[reportMissingImports]
from wwise_waapi.operation_soundbank import (  # pyright: ignore[reportMissingImports]
    build_external_sources_operation_plan,
    build_generate_operation_plan,
    build_process_definition_operation_plan,
    parse_wwise_2021_project_file,
)


WWISE_2021_PROJECT = Path(__file__).resolve().parents[1] / "_org" / "2021.1" / "SampleProject.wproj"
WWISE_2021_PROJECT_ID = "{16164796-C6E6-491A-8799-C42A33110A84}"


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_definition_event_short_id_selector_matches_each_reflected_request_schema(
    version: str,
) -> None:
    validation = validate_semantic_payload(
        "ak.wwise.core.object.get",
        {"from": {"id": [{"shortId": 123, "type": 10}]}},
        {"return": ["id", "name", "type", "path", "parent", "notes", "shortId"]},
        version=version,
    )

    assert validation.section == "request"


def _project(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    io_root = tmp_path / "sandbox"
    project_root = io_root / "SampleProject"
    project_root.mkdir(parents=True)
    project_file = project_root / "SampleProject.wproj"
    project_file.write_text("<Project/>\n", encoding="utf-8")
    return io_root, {
        "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        "name": "SampleProject",
        "path": str(project_file),
        "isDirty": False,
        "directories": {
            "root": str(project_root),
            "cache": str(project_root / ".cache"),
            "soundBankOutputRoot": str(project_root / "GeneratedSoundBanks"),
        },
        "platforms": [
            {
                "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "name": "Mac",
                "baseName": "Mac",
                "soundBankPath": str(project_root / "GeneratedSoundBanks" / "Mac"),
                "copiedMediaPath": str(project_root / "GeneratedSoundBanks" / "Mac" / "Media"),
            }
        ],
        "languages": [{"id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}", "name": "English(US)"}],
        "defaultConversion": {"id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}", "name": "PCM"},
    }


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
def test_generate_closed_plan_matches_each_reflected_request_schema(tmp_path: Path, version: str) -> None:
    io_root, project = _project(tmp_path / version)
    plan = build_generate_operation_plan(
        {
            "soundbanks": [{"name": "Gameplay_Main", "artifactExpectation": "nonlocalized", "rebuild": True}],
            "platforms": ["Mac"],
            "skipLanguages": True,
            "writeToDisk": True,
        },
        version=version,
        project_info=project,
        io_root=io_root,
        project_context_authority="waapi_getProjectInfo",
    )

    validation = validate_semantic_payload(
        "ak.wwise.core.soundbank.generate",
        plan["dispatch_args"],
        {},
        version=version,
    )

    assert validation.section == "request"


def test_generate_2021_closed_plan_uses_hashed_live_project_file_and_matches_schema(tmp_path: Path) -> None:
    io_root = tmp_path / "sandbox"
    project_root = io_root / "SampleProject"
    project_root.mkdir(parents=True)
    project_file = project_root / "SampleProject.wproj"
    shutil.copy2(WWISE_2021_PROJECT, project_file)
    project = parse_wwise_2021_project_file(
        project_file,
        io_root=io_root,
        live_project_id=WWISE_2021_PROJECT_ID,
        live_project_name="SampleProject",
        workunit_is_dirty=False,
    )
    plan = build_generate_operation_plan(
        {
            "soundbanks": [{"name": "Gameplay_Main", "artifactExpectation": "nonlocalized", "rebuild": True}],
            "platforms": ["Mac"],
            "skipLanguages": True,
            "writeToDisk": True,
        },
        version="2021.1",
        project_info=project,
        io_root=io_root,
        project_context_authority="waapi_object_get_filePath_plus_hashed_wproj",
    )

    validation = validate_semantic_payload(
        "ak.wwise.core.soundbank.generate",
        plan["dispatch_args"],
        {},
        version="2021.1",
    )

    assert validation.section == "request"
    assert plan["project_context"]["wproj_source"]["context_sha256"]


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
def test_external_sources_closed_plan_matches_each_reflected_request_schema(tmp_path: Path, version: str) -> None:
    io_root, project = _project(tmp_path / version)
    project_root = Path(project["directories"]["root"])
    wav = project_root / "external.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 32)
    source_list = project_root / "external.wsources"
    source_list.write_text(
        '<ExternalSourcesList SchemaVersion="1" Root=".">\n'
        '  <Source Path="external.wav" Destination="weapons/external.wav" />\n'
        '</ExternalSourcesList>\n',
        encoding="utf-8",
    )
    plan = build_external_sources_operation_plan(
        {
            "sources": [
                {
                    "input": str(source_list),
                    "platform": "Mac",
                    "output": str(io_root / "outputs" / "Mac"),
                }
            ]
        },
        version=version,
        project_info=project,
        io_root=io_root,
    )

    validation = validate_semantic_payload(
        "ak.wwise.core.soundbank.convertExternalSources",
        plan["dispatch_args"],
        {},
        version=version,
    )

    assert validation.section == "request"


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
def test_definition_closed_plan_matches_each_reflected_request_schema(tmp_path: Path, version: str) -> None:
    io_root, project = _project(tmp_path / version)
    definition = Path(project["directories"]["root"]) / "banks.tsv"
    definition.write_text(
        'Gameplay_Main\t"Play_Test"\tEvent\tStructure\tMedia\n',
        encoding="utf-8",
    )
    plan = build_process_definition_operation_plan(
        {"files": [str(definition)]},
        version=version,
        project_info=project,
        io_root=io_root,
    )

    validation = validate_semantic_payload(
        "ak.wwise.core.soundbank.processDefinitionFiles",
        plan["dispatch_args"],
        {},
        version=version,
    )

    assert validation.section == "request"
