from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.canonical import canonical_sha256  # pyright: ignore[reportMissingImports]
from wwise_waapi.operation_soundbank import (  # pyright: ignore[reportMissingImports]
    ARTIFACT_TREE_CONTRACT,
    DEFINITION_FILE_CONTRACT,
    DEFINITION_PLAN_CONTRACT,
    EXTERNAL_SOURCES_FILE_CONTRACT,
    EXTERNAL_SOURCES_PLAN_CONTRACT,
    GENERATE_PLAN_CONTRACT,
    SoundBankContractError,
    build_external_sources_operation_plan,
    build_generate_operation_plan,
    build_process_definition_operation_plan,
    capture_artifact_tree,
    compare_artifact_trees,
    parse_external_sources_file,
    parse_soundbank_definition_file,
    parse_wwise_2021_language_inventory,
    parse_wwise_2021_project_file,
    prove_artifact_path,
    verify_file_proof,
)


WWISE_2021_PROJECT = Path(__file__).resolve().parents[1] / "_org" / "2021.1" / "SampleProject.wproj"
WWISE_2021_PROJECT_ID = "{16164796-C6E6-491A-8799-C42A33110A84}"


def _copy_2021_project(tmp_path: Path) -> tuple[Path, Path]:
    io_root = tmp_path / "sandbox"
    project_root = io_root / "SampleProject"
    project_root.mkdir(parents=True)
    project_file = project_root / "SampleProject.wproj"
    shutil.copy2(WWISE_2021_PROJECT, project_file)
    return io_root, project_file


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
MAC_ID = "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"
WINDOWS_ID = "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"
ENGLISH_ID = "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}"
FRENCH_ID = "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}"
EVENT_ID = "{11111111-1111-1111-1111-111111111111}"
AUX_ID = "{22222222-2222-2222-2222-222222222222}"


def _project(tmp_path: Path, *, dirty: bool = False) -> tuple[Path, dict[str, Any]]:
    io_root = tmp_path / "sandbox"
    project_root = io_root / "SampleProject"
    project_root.mkdir(parents=True)
    project_file = project_root / "SampleProject.wproj"
    project_file.write_text("<Project/>\n", encoding="utf-8")
    info: dict[str, Any] = {
        "id": PROJECT_ID,
        "name": "SampleProject",
        "path": str(project_file),
        "isDirty": dirty,
        "directories": {
            "root": str(project_root),
            "cache": str(project_root / ".cache"),
            "soundBankOutputRoot": str(project_root / "GeneratedSoundBanks"),
        },
        "platforms": [
            {
                "id": MAC_ID,
                "name": "Mac",
                "baseName": "Mac",
                "soundBankPath": str(project_root / "GeneratedSoundBanks" / "Mac"),
                "copiedMediaPath": str(project_root / "GeneratedSoundBanks" / "Mac" / "Media"),
            },
            {
                "id": WINDOWS_ID,
                "name": "Windows",
                "baseName": "Windows",
                "soundBankPath": str(project_root / "GeneratedSoundBanks" / "Windows"),
                "copiedMediaPath": str(project_root / "GeneratedSoundBanks" / "Windows" / "Media"),
            },
        ],
        "languages": [
            {"id": ENGLISH_ID, "name": "English(US)"},
            {"id": FRENCH_ID, "name": "French(Canada)"},
        ],
        "defaultConversion": {"id": "{FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF}", "name": "Default"},
    }
    return io_root, info


def _generate_arguments() -> dict[str, Any]:
    return {
        "soundbanks": [
            {
                "name": "Gameplay_Main",
                "artifactExpectation": "mixed",
                "events": [EVENT_ID, "Play_Ambience"],
                "auxBusses": [AUX_ID],
                "inclusions": ["media", "event", "structure"],
                "rebuild": True,
            },
            {"name": "Music_Main", "artifactExpectation": "localized"},
        ],
        "platforms": ["Mac"],
        "languages": ["English(US)", FRENCH_ID],
        "skipLanguages": False,
        "rebuildSoundBanks": False,
        "clearAudioFileCache": True,
        "writeToDisk": True,
        "rebuildInitBank": True,
    }


def _write_wsources(path: Path, root: str, body: str) -> Path:
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<ExternalSourcesList SchemaVersion="1" Root="{root}">\n'
        f"{body}\n"
        "</ExternalSourcesList>\n",
        encoding="utf-8",
    )
    return path


def _assert_seal(payload: dict[str, Any], field: str) -> None:
    body = {key: value for key, value in payload.items() if key != field}
    assert payload[field] == canonical_sha256(body)
    json.dumps(payload, allow_nan=False)


def test_generate_plan_closes_scope_resolves_project_rows_and_proves_outputs(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)

    plan = build_generate_operation_plan(
        _generate_arguments(),
        version="2022.1",
        project_info=project,
        io_root=io_root,
    )

    assert plan["contract"] == GENERATE_PLAN_CONTRACT
    assert plan["dispatch_args"] == {
        "soundbanks": [
            {
                "name": "Gameplay_Main",
                "events": [EVENT_ID, "Play_Ambience"],
                "auxBusses": [AUX_ID],
                "inclusions": ["event", "structure", "media"],
                "rebuild": True,
            },
            {"name": "Music_Main", "rebuild": False},
        ],
        "platforms": [MAC_ID],
        "languages": [ENGLISH_ID, FRENCH_ID],
        "skipLanguages": False,
        "rebuildSoundBanks": False,
        "clearAudioFileCache": True,
        "writeToDisk": True,
        "rebuildInitBank": True,
    }
    assert plan["project_context"]["authority"] == "waapi_getProjectInfo"
    assert plan["scope"]["empty_soundbank_list_allowed"] is False
    assert plan["scope"]["implicit_all_platforms_allowed"] is False
    assert plan["scope"]["implicit_all_languages_allowed"] is False
    assert plan["artifact_plan"]["automatic_byproducts"] == ["Init.bnk"]
    artifacts = plan["artifact_plan"]["platforms"][0]["expected_user_soundbanks"][0]["expected_artifacts"]
    assert any(row["path"].endswith("/Mac/Gameplay_Main.bnk") for row in artifacts)
    assert any(row["path"].endswith("/Mac/English(US)/Gameplay_Main.bnk") for row in artifacts)
    assert all(proof["within_io_root"] for proof in plan["artifact_plan"]["path_proofs"])
    _assert_seal(plan, "plan_sha256")


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (lambda value: value.update(soundbanks=[]), "INVALID_SCOPE"),
        (lambda value: value.pop("platforms"), "INVALID_ARGUMENT"),
        (lambda value: value.update(platforms=[]), "INVALID_SCOPE"),
        (lambda value: value.pop("languages"), "INVALID_ARGUMENT"),
        (lambda value: value.update(skipLanguages=True), "INVALID_SCOPE"),
        (lambda value: value.update(writeToDisk=False), "UNSUPPORTED_BOUNDARY"),
        (lambda value: value["soundbanks"].append({"name": "Init", "artifactExpectation": "nonlocalized"}), "INVALID_SCOPE"),
        (lambda value: value["soundbanks"].append({"name": "Bad Bank", "artifactExpectation": "nonlocalized"}), "INVALID_SOUNDBANK_NAME"),
    ],
)
def test_generate_plan_rejects_implicit_or_ambiguous_scope(
    tmp_path: Path,
    mutation: Any,
    error_code: str,
) -> None:
    io_root, project = _project(tmp_path)
    arguments = _generate_arguments()
    mutation(arguments)

    with pytest.raises(SoundBankContractError) as exc:
        build_generate_operation_plan(
            arguments,
            version="2022.1",
            project_info=project,
            io_root=io_root,
        )

    assert exc.value.error_code == error_code


def test_generate_plan_requires_clean_contained_project_and_parser_owned_2021_context(tmp_path: Path) -> None:
    io_root, dirty_project = _project(tmp_path / "dirty", dirty=True)
    with pytest.raises(SoundBankContractError) as dirty:
        build_generate_operation_plan(
            _generate_arguments(),
            version="2022.1",
            project_info=dirty_project,
            io_root=io_root,
        )
    assert dirty.value.error_code == "PROJECT_DIRTY"

    io_root, project = _project(tmp_path / "2021-untrusted")
    with pytest.raises(SoundBankContractError) as no_parser_evidence:
        build_generate_operation_plan(
            _generate_arguments(),
            version="2021.1",
            project_info=project,
            io_root=io_root,
        )
    assert no_parser_evidence.value.error_code == "INVALID_PROJECT_CONTEXT_AUTHORITY"

    io_root, project_file = _copy_2021_project(tmp_path / "2021-live")
    project = parse_wwise_2021_project_file(
        project_file,
        io_root=io_root,
        live_project_id=WWISE_2021_PROJECT_ID,
        live_project_name="SampleProject",
        workunit_is_dirty=False,
    )
    generate_arguments = _generate_arguments()
    generate_arguments["languages"] = ["English(US)"]
    plan = build_generate_operation_plan(
        generate_arguments,
        version="2021.1",
        project_info=project,
        io_root=io_root,
        project_context_authority="waapi_object_get_filePath_plus_hashed_wproj",
    )
    assert plan["project_context"]["authority"] == "waapi_object_get_filePath_plus_hashed_wproj"
    assert plan["project_context"]["wproj_source"]["hook_policy"].startswith("empty_pre")
    assert plan["oracle"]["logs_are_diagnostic_only"] is False

    io_root, contained_project = _project(tmp_path / "outside-base")
    outside = tmp_path / "outside"
    outside.mkdir()
    contained_project["platforms"][0]["soundBankPath"] = str(outside / "Mac")
    with pytest.raises(SoundBankContractError) as escaped:
        build_generate_operation_plan(
            _generate_arguments(),
            version="2022.1",
            project_info=contained_project,
            io_root=io_root,
        )
    assert escaped.value.error_code == "PATH_OUTSIDE_IO_ROOT"


def test_2021_project_file_parser_derives_live_hashed_context(tmp_path: Path) -> None:
    io_root, project_file = _copy_2021_project(tmp_path)

    project = parse_wwise_2021_project_file(
        project_file,
        io_root=io_root,
        live_project_id=WWISE_2021_PROJECT_ID.lower(),
        live_project_name="SampleProject",
        workunit_is_dirty=False,
    )

    assert project["id"] == WWISE_2021_PROJECT_ID
    assert project["path"] == str(project_file.resolve())
    assert project["isDirty"] is False
    assert project["directories"] == {
        "root": str(project_file.parent.resolve()),
        "cache": str((project_file.parent / ".cache").resolve()),
        "soundBankOutputRoot": str((project_file.parent / "GeneratedSoundBanks").resolve()),
    }
    assert {(row["name"], row["baseName"]) for row in project["platforms"]} == {
        ("Mac", "Mac"),
        ("Windows", "Windows"),
    }
    assert project["languages"] == [
        {"id": "{273F02D0-F4F6-49D6-B2F2-B46585A2406B}", "name": "English(US)"}
    ]
    assert all(row["soundBankPath"] == row["copiedMediaPath"] for row in project["platforms"])
    assert project["wwiseProjectFile"]["file_proof"]["sha256"]


def test_2021_language_inventory_is_hash_bound_and_rejects_dirty_disk_evidence(tmp_path: Path) -> None:
    _, project_file = _copy_2021_project(tmp_path)
    inventory = parse_wwise_2021_language_inventory(
        project_file,
        live_project_id=WWISE_2021_PROJECT_ID,
        live_project_name="SampleProject",
        workunit_is_dirty=False,
    )

    assert inventory["contract"] == "waapi-skill.wwise-2021-language-inventory/v1"
    assert inventory["file_proof"]["sha256"]
    assert any(row["name"] == "SFX" for row in inventory["languages"])
    assert inventory["inventory_sha256"]

    with pytest.raises(SoundBankContractError) as dirty:
        parse_wwise_2021_language_inventory(
            project_file,
            live_project_id=WWISE_2021_PROJECT_ID,
            live_project_name="SampleProject",
            workunit_is_dirty=True,
        )
    assert dirty.value.error_code == "PROJECT_DIRTY"

    linked = tmp_path / "linked-project.wproj"
    linked.symlink_to(project_file)
    with pytest.raises(SoundBankContractError) as symlink:
        parse_wwise_2021_language_inventory(
            linked,
            live_project_id=WWISE_2021_PROJECT_ID,
            live_project_name="SampleProject",
            workunit_is_dirty=False,
        )
    assert symlink.value.error_code == "SYMLINK_NOT_ALLOWED"


def test_2021_project_file_parser_rejects_dirty_escape_and_symlink(tmp_path: Path) -> None:
    io_root, project_file = _copy_2021_project(tmp_path / "dirty")
    with pytest.raises(SoundBankContractError) as dirty:
        parse_wwise_2021_project_file(
            project_file,
            io_root=io_root,
            live_project_id=WWISE_2021_PROJECT_ID,
            live_project_name="SampleProject",
            workunit_is_dirty=True,
        )
    assert dirty.value.error_code == "PROJECT_DIRTY"

    outside_root, outside_project = _copy_2021_project(tmp_path / "outside")
    contained_root = tmp_path / "contained"
    contained_root.mkdir()
    with pytest.raises(SoundBankContractError) as escaped:
        parse_wwise_2021_project_file(
            outside_project,
            io_root=contained_root,
            live_project_id=WWISE_2021_PROJECT_ID,
            live_project_name="SampleProject",
            workunit_is_dirty=False,
        )
    assert escaped.value.error_code == "PATH_OUTSIDE_IO_ROOT"
    assert outside_root != contained_root

    link = outside_project.parent / "Linked.wproj"
    link.symlink_to(outside_project)
    with pytest.raises(SoundBankContractError) as symlink:
        parse_wwise_2021_project_file(
            link,
            io_root=outside_root,
            live_project_id=WWISE_2021_PROJECT_ID,
            live_project_name="SampleProject",
            workunit_is_dirty=False,
        )
    assert symlink.value.error_code == "SYMLINK_NOT_ALLOWED"


def test_2021_project_file_parser_allows_contained_parent_relative_platform_output(tmp_path: Path) -> None:
    io_root, project_file = _copy_2021_project(tmp_path)
    text = project_file.read_text(encoding="utf-8")
    old = "<Value Platform=\"Mac\">GeneratedSoundBanks\\Mac\\</Value>"
    new = "<Value Platform=\"Mac\">..\\Android\\assets\\GeneratedSoundBanks\\Android\\</Value>"
    assert old in text
    project_file.write_text(text.replace(old, new, 1), encoding="utf-8")

    project = parse_wwise_2021_project_file(
        project_file,
        io_root=io_root,
        live_project_id=WWISE_2021_PROJECT_ID,
        live_project_name="SampleProject",
        workunit_is_dirty=False,
    )

    mac = next(row for row in project["platforms"] if row["name"] == "Mac")
    assert mac["soundBankPath"] == str(
        (io_root / "Android" / "assets" / "GeneratedSoundBanks" / "Android").resolve()
    )


@pytest.mark.parametrize(
    ("old", "new", "error_code"),
    [
        ('<Project Name="SampleProject"', '<Project Name="OtherProject"', "PROJECT_IDENTITY_MISMATCH"),
        (
            "<Value Platform=\"Mac\">GeneratedSoundBanks\\Mac\\</Value>",
            "<Value Platform=\"Mac\">..\\..\\..\\Outside</Value>",
            "PATH_OUTSIDE_IO_ROOT",
        ),
        (
            '"$(WwiseExePath)\\CopyStreamedFiles.exe" -info "$(InfoFilePath)"',
            '"python" -info "$(InfoFilePath)"',
            "UNSAFE_PROJECT_HOOK",
        ),
    ],
)
def test_2021_project_file_parser_rejects_identity_path_and_hook_drift(
    tmp_path: Path,
    old: str,
    new: str,
    error_code: str,
) -> None:
    io_root, project_file = _copy_2021_project(tmp_path)
    text = project_file.read_text(encoding="utf-8")
    assert old in text
    project_file.write_text(text.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(SoundBankContractError) as drifted:
        parse_wwise_2021_project_file(
            project_file,
            io_root=io_root,
            live_project_id=WWISE_2021_PROJECT_ID,
            live_project_name="SampleProject",
            workunit_is_dirty=False,
        )

    assert drifted.value.error_code == error_code


def test_artifact_snapshots_prove_created_modified_deleted_and_detect_tampering(tmp_path: Path) -> None:
    io_root = tmp_path / "sandbox"
    io_root.mkdir()
    output = io_root / "GeneratedSoundBanks" / "Mac"

    before = capture_artifact_tree(output, io_root=io_root)
    assert before["contract"] == ARTIFACT_TREE_CONTRACT
    assert before["exists"] is False
    output.mkdir(parents=True)
    (output / "Gameplay_Main.bnk").write_bytes(b"bank-one")
    (output / "Wwise.dat").write_bytes(b"ledger")
    after = capture_artifact_tree(output, io_root=io_root)
    delta = compare_artifact_trees(
        before,
        after,
        expected_relative_paths=["Gameplay_Main.bnk"],
        allowed_relative_paths=["Gameplay_Main.bnk", "Wwise.dat"],
        enforce_no_unexpected_changes=True,
    )
    assert delta["created"] == ["Gameplay_Main.bnk", "Wwise.dat"]
    assert delta["expected"] == [
        {
            "path": "Gameplay_Main.bnk",
            "status": "created",
            "nonempty": True,
            "satisfied": True,
        }
    ]
    assert delta["verified"] is True

    (output / "Gameplay_Main.bnk").write_bytes(b"bank-two")
    (output / "Wwise.dat").unlink()
    final = capture_artifact_tree(output, io_root=io_root)
    second_delta = compare_artifact_trees(after, final)
    assert second_delta["modified"] == ["Gameplay_Main.bnk"]
    assert second_delta["deleted"] == ["Wwise.dat"]

    tampered = dict(after)
    tampered["file_count"] = 99
    with pytest.raises(SoundBankContractError) as invalid:
        compare_artifact_trees(tampered, final)
    assert invalid.value.error_code == "EVIDENCE_TAMPERED"


def test_artifact_path_and_tree_reject_escape_symlink_and_limits(tmp_path: Path) -> None:
    io_root = tmp_path / "sandbox"
    io_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(SoundBankContractError) as escaped:
        prove_artifact_path(outside / "bank.bnk", io_root=io_root, field="output", expect_directory=False)
    assert escaped.value.error_code == "PATH_OUTSIDE_IO_ROOT"

    output = io_root / "out"
    output.mkdir()
    (output / "one.bnk").write_bytes(b"one")
    (output / "two.bnk").write_bytes(b"two")
    with pytest.raises(SoundBankContractError) as limited:
        capture_artifact_tree(output, io_root=io_root, max_files=1)
    assert limited.value.error_code == "LIMIT_EXCEEDED"

    link = output / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit symbolic links")
    with pytest.raises(SoundBankContractError) as symlinked:
        capture_artifact_tree(output, io_root=io_root)
    assert symlinked.value.error_code == "SYMLINK_NOT_ALLOWED"


def test_external_sources_parser_hashes_inputs_and_derives_destinations(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)
    project_root = Path(project["directories"]["root"])
    source_root = project_root / "ExternalSources"
    (source_root / "nested").mkdir(parents=True)
    first = source_root / "line_a.wav"
    second = source_root / "nested" / "line_b.wav"
    first.write_bytes(b"RIFF-a")
    second.write_bytes(b"RIFF-b")
    source_list = _write_wsources(
        project_root / "dialog.wsources",
        "ExternalSources",
        '  <Source Path="line_a.wav" Conversion="PCM" Destination="dialog/renamed.voice" />\n'
        '  <Source Path="nested/line_b.wav" AnalysisTypes="6" />',
    )

    parsed = parse_external_sources_file(source_list, project_root=project_root)

    assert parsed["contract"] == EXTERNAL_SOURCES_FILE_CONTRACT
    assert [entry["expected_destination"] for entry in parsed["entries"]] == [
        "dialog/renamed.wem",
        "nested/line_b.wem",
    ]
    assert parsed["entries"][0]["source"]["sha256"] != parsed["entries"][1]["source"]["sha256"]
    assert parsed["entries"][0]["uses_project_default_conversion"] is False
    assert parsed["entries"][1]["uses_project_default_conversion"] is True
    assert parsed["entries"][1]["analysis_types"] == 6
    _assert_seal(parsed, "document_sha256")

    output = io_root / "external-output" / "Mac"
    plan = build_external_sources_operation_plan(
        {"sources": [{"input": str(source_list), "platform": "Mac", "output": str(output)}]},
        version="2022.1",
        project_info=project,
        io_root=io_root,
    )
    assert plan["contract"] == EXTERNAL_SOURCES_PLAN_CONTRACT
    assert plan["dispatch_args"] == {
        "sources": [{"input": str(source_list.resolve()), "platform": MAC_ID, "output": str(output.resolve())}]
    }
    assert [row["relative_path"] for row in plan["requests"][0]["expected_outputs"]] == [
        "dialog/renamed.wem",
        "nested/line_b.wem",
    ]
    assert plan["requests"][0]["managed_side_effects"] == ["Wwise.dat"]
    assert plan["artifact_plan"]["all_outputs_explicit"] is True
    _assert_seal(plan, "plan_sha256")

    verify_file_proof(parsed["entries"][0]["source"], field="line_a")
    first.write_bytes(b"RIFF-a-changed")
    with pytest.raises(SoundBankContractError) as drift:
        verify_file_proof(parsed["entries"][0]["source"], field="line_a")
    assert drift.value.error_code in {"FILE_CHANGED", "LIMIT_EXCEEDED"}


@pytest.mark.parametrize(
    ("body", "error_code"),
    [
        ('  <Source Path="tone.wav" Cookie="42" />', "UNSUPPORTED_XML_ATTRIBUTE"),
        (
            '  <Source Path="tone.wav" Destination="same.wav" />\n'
            '  <Source Path="other.wav" Destination="same.aif" />',
            "DUPLICATE_DESTINATION",
        ),
        ('  <Source Path="tone.wav" Destination="../outside.wav" />', "INVALID_DESTINATION"),
        ('  <Source Path="tone.wav" AnalysisTypes="3" />', "INVALID_EXTERNAL_SOURCES_FILE"),
    ],
)
def test_external_sources_parser_rejects_unreviewed_or_colliding_shapes(
    tmp_path: Path,
    body: str,
    error_code: str,
) -> None:
    root = tmp_path / "project"
    sources = root / "sources"
    sources.mkdir(parents=True)
    (sources / "tone.wav").write_bytes(b"tone")
    (sources / "other.wav").write_bytes(b"other")
    source_list = _write_wsources(root / "invalid.wsources", "sources", body)

    with pytest.raises(SoundBankContractError) as exc:
        parse_external_sources_file(source_list, project_root=root)

    assert exc.value.error_code == error_code


def test_external_sources_parser_rejects_dtd_absolute_without_destination_and_output_escape(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)
    project_root = Path(project["directories"]["root"])
    sources = project_root / "sources"
    sources.mkdir()
    tone = sources / "tone.wav"
    tone.write_bytes(b"tone")
    dtd = project_root / "dtd.wsources"
    dtd.write_text(
        '<!DOCTYPE x [<!ENTITY y "z">]><ExternalSourcesList SchemaVersion="1"><Source Path="tone.wav"/></ExternalSourcesList>',
        encoding="utf-8",
    )
    with pytest.raises(SoundBankContractError) as unsafe:
        parse_external_sources_file(dtd, project_root=project_root)
    assert unsafe.value.error_code == "UNSAFE_XML"

    absolute = _write_wsources(
        project_root / "absolute.wsources",
        str(sources),
        f'  <Source Path="{tone}" Conversion="PCM" />',
    )
    with pytest.raises(SoundBankContractError) as no_destination:
        parse_external_sources_file(absolute, project_root=project_root)
    assert no_destination.value.error_code == "EXPLICIT_DESTINATION_REQUIRED"

    outside = tmp_path / "outside"
    with pytest.raises(SoundBankContractError) as escaped:
        build_external_sources_operation_plan(
            {"sources": [{"input": str(absolute), "platform": "Mac", "output": str(outside)}]},
            version="2022.1",
            project_info=project,
            io_root=io_root,
        )
    assert escaped.value.error_code == "PATH_OUTSIDE_IO_ROOT"

    with pytest.raises(SoundBankContractError) as old_version:
        build_external_sources_operation_plan(
            {"sources": [{"input": str(absolute), "platform": "Mac", "output": str(io_root / "out")}]},
            version="2021.1",
            project_info=project,
            io_root=io_root,
        )
    assert old_version.value.error_code == "UNSUPPORTED_VERSION"


def test_external_sources_plan_rejects_cross_platform_output_root(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)
    project_root = Path(project["directories"]["root"])
    sources = project_root / "sources"
    sources.mkdir()
    (sources / "tone.wav").write_bytes(b"tone")
    source_list = _write_wsources(
        project_root / "one.wsources",
        "sources",
        '  <Source Path="tone.wav" Destination="tone.wav" />',
    )
    output = io_root / "shared-output"

    with pytest.raises(SoundBankContractError) as collision:
        build_external_sources_operation_plan(
            {
                "sources": [
                    {"input": str(source_list), "platform": "Mac", "output": str(output)},
                    {"input": str(source_list), "platform": "Windows", "output": str(output)},
                ]
            },
            version="2022.1",
            project_info=project,
            io_root=io_root,
        )

    assert collision.value.error_code == "CROSS_PLATFORM_OUTPUT_COLLISION"


def test_definition_parser_supports_strong_event_aux_dialogue_and_effect_subset(tmp_path: Path) -> None:
    definition = tmp_path / "banks.tsv"
    definition.write_bytes(
        ("\ufeff"
         'Bank_A\t"Play_Test"\n'
         f"Bank_A\t-AuxBus\t{AUX_ID}\tStructure\tMedia\n"
         "Bank_B\t-DialogueEvent\t123\tEvent\tMedia\n"
         "Bank_B\t-EffectShareset\t0x1A\tStructure\n").encode("utf-8")
    )

    parsed = parse_soundbank_definition_file(definition)

    assert parsed["contract"] == DEFINITION_FILE_CONTRACT
    assert parsed["row_count"] == 4
    assert [bank["name"] for bank in parsed["soundbanks"]] == ["Bank_A", "Bank_B"]
    rows = parsed["rows"]
    assert rows[0]["object_type"] == "Event"
    assert rows[0]["identity"] == {"kind": "name", "value": "Play_Test"}
    assert rows[0]["filters"] == ["events", "structures", "media"]
    assert rows[1]["object_type"] == "AuxBus"
    assert rows[1]["identity"] == {"kind": "guid", "value": AUX_ID}
    assert rows[2]["object_type"] == "DialogueEvent"
    assert rows[2]["identity"] == {"kind": "short_id", "value": 123, "source_format": "decimal"}
    assert rows[2]["filters"] == ["events", "media"]
    assert rows[3]["object_type"] == "Effect"
    assert rows[3]["identity"] == {"kind": "short_id", "value": 26, "source_format": "hexadecimal"}
    assert parsed["unsupported_boundary"]["GameSyncExclusion"].startswith("rejected")
    _assert_seal(parsed, "document_sha256")


@pytest.mark.parametrize(
    ("contents", "expected_identity"),
    (
        ('Bank_A\t"Event_A"\tEvent\n', {"kind": "name", "value": "Event_A"}),
        (
            'Bank_A\t-EffectShareset\t"Effect_A"\tStructure\tMedia\n',
            {"kind": "name", "value": "Effect_A"},
        ),
        (f"Bank_A\t{AUX_ID}\tEvent\n", {"kind": "guid", "value": AUX_ID}),
        (
            "Bank_A\t123\tEvent\n",
            {"kind": "short_id", "value": 123, "source_format": "decimal"},
        ),
        (
            "Bank_A\t0x1A\tEvent\n",
            {"kind": "short_id", "value": 26, "source_format": "hexadecimal"},
        ),
    ),
)
def test_definition_parser_accepts_only_official_identity_quote_forms(
    tmp_path: Path,
    contents: str,
    expected_identity: Mapping[str, Any],
) -> None:
    definition = tmp_path / "official.tsv"
    definition.write_text(contents, encoding="utf-8")

    parsed = parse_soundbank_definition_file(definition)

    assert parsed["rows"][0]["identity"] == expected_identity


@pytest.mark.parametrize(
    ("contents", "error_code"),
    [
        ("<SoundBanksInfo/>\n", "INVALID_DEFINITION_FORMAT"),
        ("Bank_A\t-GameSyncExclusion\tState\tGroup\tValue\n", "UNSUPPORTED_DEFINITION_DIRECTIVE"),
        ("Bank_A\t-Unknown\tObject\n", "UNSUPPORTED_DEFINITION_DIRECTIVE"),
        ('Bank_A\t-EffectShareset\t"Effect_A"\tEvent\n', "UNSUPPORTED_DEFINITION_FILTER"),
        ('Bank_A\t"Event_A"\tUnknown\n', "UNSUPPORTED_DEFINITION_FILTER"),
        ('Bank_A\t"Event_A"\nBank_A\t"Event_A"\tMedia\n', "DUPLICATE_DEFINITION_INCLUSION"),
    ],
)
def test_definition_parser_rejects_xml_exclusions_unknowns_and_duplicates(
    tmp_path: Path,
    contents: str,
    error_code: str,
) -> None:
    definition = tmp_path / "invalid.txt"
    definition.write_text(contents, encoding="utf-8")

    with pytest.raises(SoundBankContractError) as exc:
        parse_soundbank_definition_file(definition)

    assert exc.value.error_code == error_code


@pytest.mark.parametrize(
    ("contents", "error_code"),
    (
        ("Bank_A\tEvent_A\tEvent\n", "INVALID_DEFINITION_IDENTITY"),
        (
            "Bank_A\t-EffectShareset\tEffect_A\tStructure\tMedia\n",
            "INVALID_DEFINITION_IDENTITY",
        ),
        ('Bank_A\t"123"\tEvent\n', "INVALID_DEFINITION_IDENTITY"),
        (f'Bank_A\t"{AUX_ID}"\tEvent\n', "INVALID_DEFINITION_IDENTITY"),
        ('Bank_A\t"Event_A""\tEvent\n', "INVALID_DEFINITION_FILE"),
        ('"Bank_A"\t"Event_A"\tEvent\n', "INVALID_DEFINITION_ROW"),
    ),
)
def test_definition_parser_rejects_nonofficial_or_ambiguous_identity_quoting(
    tmp_path: Path,
    contents: str,
    error_code: str,
) -> None:
    definition = tmp_path / "invalid-quoting.tsv"
    definition.write_text(contents, encoding="utf-8")

    with pytest.raises(SoundBankContractError) as exc:
        parse_soundbank_definition_file(definition)

    assert exc.value.error_code == error_code


def test_process_definition_plan_derives_names_and_readback_oracle_from_files(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)
    project_root = Path(project["directories"]["root"])
    definition = project_root / "banks.txt"
    definition.write_text(
        f'Gameplay_Main\t"Play_Test"\tEvent\tStructure\tMedia\n'
        f"Gameplay_Main\t-AuxBus\t{AUX_ID}\tStructure\tMedia\n",
        encoding="utf-8",
    )

    plan = build_process_definition_operation_plan(
        {"files": [str(definition)]},
        version="2022.1",
        project_info=project,
        io_root=io_root,
    )

    assert plan["contract"] == DEFINITION_PLAN_CONTRACT
    assert plan["dispatch_args"] == {"files": [str(definition.resolve())]}
    assert [bank["name"] for bank in plan["soundbanks"]] == ["Gameplay_Main"]
    assert len(plan["soundbanks"][0]["expected_inclusions"]) == 2
    assert plan["oracle"]["caller_expected_soundbank_names_accepted"] is False
    assert plan["oracle"]["resolve_every_identity_before_dispatch"] is True
    assert plan["cleanup"]["automatic_cleanup"] is False
    assert plan["cleanup"]["sandbox_teardown_preferred"] is True
    _assert_seal(plan, "plan_sha256")


def test_process_definition_plan_rejects_same_bank_across_files_and_2021(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)
    project_root = Path(project["directories"]["root"])
    first = project_root / "first.txt"
    second = project_root / "second.txt"
    first.write_text('Gameplay_Main\t"Event_A"\n', encoding="utf-8")
    second.write_text('Gameplay_Main\t"Event_B"\n', encoding="utf-8")

    with pytest.raises(SoundBankContractError) as collision:
        build_process_definition_operation_plan(
            {"files": [str(first), str(second)]},
            version="2022.1",
            project_info=project,
            io_root=io_root,
        )
    assert collision.value.error_code == "CROSS_FILE_SOUNDBANK_COLLISION"

    with pytest.raises(SoundBankContractError) as old_version:
        build_process_definition_operation_plan(
            {"files": [str(first)]},
            version="2021.1",
            project_info=project,
            io_root=io_root,
        )
    assert old_version.value.error_code == "UNSUPPORTED_VERSION"


def test_file_proof_rejects_symbolic_link_leaf(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text('Bank_A\t"Event_A"\n', encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Host does not permit symbolic links")

    with pytest.raises(SoundBankContractError) as exc:
        parse_soundbank_definition_file(link)

    assert exc.value.error_code == "SYMLINK_NOT_ALLOWED"


def test_json_contracts_do_not_leak_path_objects(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)
    plan = build_generate_operation_plan(
        {
            "soundbanks": [{"name": "One_Bank", "artifactExpectation": "nonlocalized"}],
            "platforms": [MAC_ID],
            "skipLanguages": True,
            "writeToDisk": True,
        },
        version="2025.1",
        project_info=project,
        io_root=io_root,
    )

    encoded = json.dumps(plan, sort_keys=True, allow_nan=False)

    assert "PosixPath" not in encoded
    assert plan["scope"]["auto_defined_soundbanks"].startswith("generated_by_wwise")
    assert plan["oracle"]["error_field_must_be_empty"] is True
