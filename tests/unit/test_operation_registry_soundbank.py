from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.platform_filesystem import create_symlink_or_skip

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    OperationContractError,
    _localize_waapi_file_path,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
    verify_prepared_operation,
)


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
PLATFORM_ID = "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"
LANGUAGE_ID = "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"
CONVERSION_ID = "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}"
EVENT_ID = "{11111111-1111-1111-1111-111111111111}"
DEBUG_EVENT_ID = "{11111111-1111-1111-1111-222222222222}"
CONTROL_BANK_ID = "{22222222-2222-2222-2222-222222222222}"
TARGET_BANK_ID = "{33333333-3333-3333-3333-333333333333}"
WWISE_2021_PROJECT_ID = "{16164796-C6E6-491A-8799-C42A33110A84}"
WWISE_2021_PROJECT = Path(__file__).resolve().parents[1] / "_org" / "2021.1" / "SampleProject.wproj"


def _copy_2021_project(tmp_path: Path) -> tuple[Path, Path]:
    io_root = tmp_path / "sandbox"
    project_root = io_root / "SampleProject"
    project_root.mkdir(parents=True)
    project_file = project_root / "SampleProject.wproj"
    shutil.copy2(WWISE_2021_PROJECT, project_file)
    return io_root, project_file


class Generate2021Reader:
    def __init__(self, project_file: Path) -> None:
        self.project_file = project_file
        self.dirty = False
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def __call__(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((uri, dict(args), dict(options)))
        if uri != "ak.wwise.core.object.get":
            raise AssertionError((uri, args, options))
        row = _row(WWISE_2021_PROJECT_ID, "SampleProject", "Project", "\\")
        row.update(
            {
                "filePath": str(self.project_file),
                "workunitIsDirty": self.dirty,
            }
        )
        return {"return": [row]}


def test_waapi_virtual_home_path_uses_host_account_not_disposable_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name == "nt":
        assert Path(_localize_waapi_file_path(r"C:\Projects\SampleProject.wproj")).is_absolute()
        return
    import pwd

    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    monkeypatch.setenv("HOME", str(tmp_path / "disposable-home"))

    assert _localize_waapi_file_path(r"Y:\Projects\SampleProject.wproj") == str(
        account_home / "Projects" / "SampleProject.wproj"
    )
    assert _localize_waapi_file_path(r"Z:\Volumes\Projects\SampleProject.wproj") == (
        "/Volumes/Projects/SampleProject.wproj"
    )


def test_waapi_posix_file_path_keeps_a_literal_backslash() -> None:
    if os.name == "nt":
        pytest.skip("a backslash is a native separator on Windows")

    value = r"/srv/projects/name\with-backslash/SampleProject.wproj"
    assert _localize_waapi_file_path(value) == value


@pytest.mark.parametrize(
    "value",
    (
        "relative/SampleProject.wproj",
        r"C:\Projects\SampleProject.wproj",
        r"\\server\share\SampleProject.wproj",
        r"Y:\Projects\..\SampleProject.wproj",
    ),
)
def test_waapi_posix_file_path_fails_closed_when_namespace_is_not_local(
    value: str,
) -> None:
    if os.name == "nt":
        pytest.skip("this test covers POSIX and Wine localization")

    with pytest.raises(OperationContractError) as caught:
        _localize_waapi_file_path(value)

    assert caught.value.error_code == "INVALID_PROJECT_CONTEXT"


def _project(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    io_root = tmp_path / "sandbox"
    project_root = io_root / "SampleProject"
    project_root.mkdir(parents=True)
    project_file = project_root / "SampleProject.wproj"
    project_file.write_text("<Project/>\n", encoding="utf-8")
    return io_root, {
        "name": "SampleProject",
        "displayTitle": "SampleProject - Wwise",
        "path": str(project_file),
        "id": PROJECT_ID,
        "isDirty": False,
        "currentLanguageId": LANGUAGE_ID,
        "referenceLanguageId": LANGUAGE_ID,
        "languages": [{"id": LANGUAGE_ID, "name": "English(US)", "shortId": 1}],
        "currentPlatformId": PLATFORM_ID,
        "platforms": [
            {
                "id": PLATFORM_ID,
                "name": "Mac",
                "baseName": "Mac",
                "baseDisplayName": "Mac",
                "soundBankPath": str(project_root / "GeneratedSoundBanks" / "Mac"),
                "copiedMediaPath": str(project_root / "GeneratedSoundBanks" / "Mac" / "Media"),
            }
        ],
        "defaultConversion": {"id": CONVERSION_ID, "name": "PCM"},
        "directories": {
            "root": str(project_root),
            "cache": str(project_root / ".cache"),
            "originals": str(project_root / "Originals"),
            "soundBankOutputRoot": str(project_root / "GeneratedSoundBanks"),
            "commands": str(project_root / "Commands"),
            "properties": str(project_root),
        },
    }


def _request(operation: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": operation,
        "arguments": dict(arguments),
    }


def _row(
    object_id: str,
    name: str,
    object_type: str,
    path: str,
    parent: str = PROJECT_ID,
) -> dict[str, Any]:
    return {
        "id": object_id,
        "name": name,
        "type": object_type,
        "path": path,
        "parent": {"id": parent},
        "notes": "",
    }


class GenerateReader:
    def __init__(self, project: Mapping[str, Any]) -> None:
        self.project = dict(project)
        self.event = _row(EVENT_ID, "Play_Gameplay", "Event", r"\Events\Default Work Unit\Play_Gameplay")

    def __call__(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        if uri == "ak.wwise.core.getProjectInfo":
            return dict(self.project)
        if uri == "ak.wwise.core.object.get":
            ids = args.get("from", {}).get("id", []) if isinstance(args.get("from"), Mapping) else []
            return {"return": [self.event] if ids == [EVENT_ID] else []}
        raise AssertionError((uri, args, options))


def _minimal_generate_request(io_root: Path) -> dict[str, Any]:
    return _request(
        "soundbank.generate",
        {
            "soundbanks": [
                {
                    "name": "Gameplay_Main",
                    "artifact_expectation": "nonlocalized",
                }
            ],
            "platforms": ["Mac"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": str(io_root),
        },
    )


@pytest.mark.parametrize(
    "version",
    ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"],
)
def test_generate_parser_accepts_batch_wide_language_modes(
    tmp_path: Path,
    version: str,
) -> None:
    base = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": "soundbank.generate",
    }
    nonlocalized = {
        **base,
        "arguments": {
            "soundbanks": [
                {
                    "name": "Gameplay_Main",
                    "artifact_expectation": "nonlocalized",
                }
            ],
            "platforms": ["Mac"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": str(tmp_path),
        },
    }
    mixed_batch = {
        **base,
        "arguments": {
            "soundbanks": [
                {
                    "name": "Gameplay_Main",
                    "artifact_expectation": "nonlocalized",
                },
                {
                    "name": "Dialogue_Main",
                    "artifact_expectation": "localized",
                },
            ],
            "platforms": ["Mac"],
            "languages": ["English(US)"],
            "skip_languages": False,
            "write_to_disk": True,
            "io_root": str(tmp_path),
        },
    }

    assert parse_operation_request(nonlocalized).arguments["skip_languages"] is True
    parsed_mixed = parse_operation_request(mixed_batch)
    assert parsed_mixed.arguments["languages"] == ["English(US)"]


@pytest.mark.parametrize(
    "version",
    ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"],
)
@pytest.mark.parametrize(
    "soundbanks,skip_languages,languages",
    [
        (
            [{"name": "Dialogue_Main", "artifact_expectation": "localized"}],
            True,
            None,
        ),
        (
            [{"name": "Dialogue_Main", "artifact_expectation": "mixed"}],
            False,
            ["SFX"],
        ),
    ],
)
def test_generate_parser_rejects_inconsistent_batch_language_modes(
    tmp_path: Path,
    version: str,
    soundbanks: list[dict[str, Any]],
    skip_languages: bool,
    languages: list[str] | None,
) -> None:
    arguments: dict[str, Any] = {
        "soundbanks": soundbanks,
        "platforms": ["Mac"],
        "skip_languages": skip_languages,
        "write_to_disk": True,
        "io_root": str(tmp_path),
    }
    if languages is not None:
        arguments["languages"] = languages

    with pytest.raises(OperationContractError) as rejected:
        parse_operation_request(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": version,
                "operation": "soundbank.generate",
                "arguments": arguments,
            }
        )

    assert rejected.value.error_code == "INVALID_SCOPE"


def test_generate_binds_relative_project_directories_to_live_project_file(
    tmp_path: Path,
) -> None:
    io_root, project = _project(tmp_path)
    project_root = Path(project["path"]).parent
    project["directories"].update(
        {
            "root": ".",
            "cache": ".cache",
            "originals": "Originals",
            "soundBankOutputRoot": "GeneratedSoundBanks",
            "commands": "Commands",
            "properties": ".",
        }
    )
    project["platforms"][0].update(
        {
            "soundBankPath": "GeneratedSoundBanks/Mac",
            "copiedMediaPath": "GeneratedSoundBanks/Mac/Media",
        }
    )

    reader = GenerateReader(project)
    prepared = prepare_operation(
        parse_operation_request(_minimal_generate_request(io_root)),
        read_call=reader,
    ).as_dict()

    plan = prepared["verification_plan"]["plan"]
    assert plan["project_context"]["path"] == str(Path(project["path"]).resolve())
    assert plan["project_context"]["directories"]["root"] == str(project_root.resolve())
    assert prepared["dispatch"]["uri"] == "ak.wwise.core.soundbank.generate"
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is True


def test_generate_allows_project_relative_sibling_paths_inside_io_root_and_replays_guard(
    tmp_path: Path,
) -> None:
    io_root, project = _project(tmp_path)
    project["directories"].update(
        {
            "root": ".",
            "cache": "../SharedCache/SampleProject",
            "soundBankOutputRoot": "../Build/GeneratedSoundBanks",
        }
    )
    project["platforms"][0].update(
        {
            "soundBankPath": "../Build/GeneratedSoundBanks/Mac",
            "copiedMediaPath": "../Build/GeneratedSoundBanks/Mac/Media",
        }
    )

    reader = GenerateReader(project)
    prepared = prepare_operation(
        parse_operation_request(_minimal_generate_request(io_root)),
        read_call=reader,
    ).as_dict()

    artifact_plan = prepared["verification_plan"]["plan"]["artifact_plan"]
    assert artifact_plan["cache_root"] == str(
        (io_root / "SharedCache" / "SampleProject").resolve()
    )
    assert artifact_plan["metadata_root"] == str(
        (io_root / "Build" / "GeneratedSoundBanks").resolve()
    )
    assert artifact_plan["platforms"][0]["soundBankPath"] == str(
        (io_root / "Build" / "GeneratedSoundBanks" / "Mac").resolve()
    )
    assert artifact_plan["platforms"][0]["copiedMediaPath"] == str(
        (io_root / "Build" / "GeneratedSoundBanks" / "Mac" / "Media").resolve()
    )
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is True


@pytest.mark.parametrize(
    ("field", "unsafe_path"),
    [
        ("cache", "../../outside-cache"),
        ("soundBankOutputRoot", "../Build//GeneratedSoundBanks"),
        ("soundBankOutputRoot", "../Build/./GeneratedSoundBanks"),
        ("soundBankOutputRoot", "../Build/C:/GeneratedSoundBanks"),
    ],
)
def test_generate_rejects_unsafe_project_relative_sibling_paths(
    tmp_path: Path,
    field: str,
    unsafe_path: str,
) -> None:
    io_root, project = _project(tmp_path)
    project["directories"][field] = unsafe_path

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(_minimal_generate_request(io_root)),
            read_call=GenerateReader(project),
        )

    assert rejected.value.error_code == "INVALID_PROJECT_CONTEXT"


def test_generate_rejects_project_relative_sibling_symlink_escape(
    tmp_path: Path,
) -> None:
    io_root, project = _project(tmp_path)
    outside = tmp_path / "outside-cache"
    outside.mkdir()
    create_symlink_or_skip(
        io_root / "linked-cache",
        outside,
        target_is_directory=True,
    )
    project["directories"]["cache"] = "../linked-cache/SampleProject"

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(_minimal_generate_request(io_root)),
            read_call=GenerateReader(project),
        )

    assert rejected.value.error_code == "INVALID_PROJECT_CONTEXT"


def test_generate_guard_replay_rejects_new_sibling_symlink_escape(
    tmp_path: Path,
) -> None:
    io_root, project = _project(tmp_path)
    project["directories"]["cache"] = "../late-cache/SampleProject"
    reader = GenerateReader(project)
    prepared = prepare_operation(
        parse_operation_request(_minimal_generate_request(io_root)),
        read_call=reader,
    ).as_dict()

    outside = tmp_path / "outside-cache"
    outside.mkdir()
    create_symlink_or_skip(
        io_root / "late-cache",
        outside,
        target_is_directory=True,
    )
    validation = validate_prepared_roles(prepared, read_call=reader)

    assert validation["ok"] is False
    assert validation["status"] == "repreview_required"
    replay = next(
        assertion
        for assertion in validation["assertions"]
        if assertion["name"]
        == "closed SoundBank inputs and project context can be replayed unchanged"
    )
    assert replay["passed"] is False
    assert replay["evidence"]["error_code"] == "INVALID_PROJECT_CONTEXT"


@pytest.mark.skipif(os.name == "nt", reason="Wine virtual drives are POSIX-host behavior")
@pytest.mark.parametrize("drive", ["Y", "Z"])
def test_generate_localizes_wine_project_directories_and_platform_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drive: str,
) -> None:
    io_root, project = _project(tmp_path)
    if drive == "Y":
        import pwd

        monkeypatch.setattr(
            pwd,
            "getpwuid",
            lambda _uid: SimpleNamespace(pw_dir=str(tmp_path)),
        )

    def wine_path(raw: str) -> str:
        path = Path(raw).resolve()
        if drive == "Y":
            parts = path.relative_to(tmp_path.resolve()).parts
        else:
            parts = path.parts[1:]
        return drive + ":\\" + "\\".join(parts)

    expected_project_path = str(Path(project["path"]).resolve())
    project["path"] = wine_path(project["path"])
    project["directories"] = {
        key: wine_path(value)
        for key, value in project["directories"].items()
    }
    # The sealed 2022.1 campaign evidence reports the project root with a
    # trailing Wine separator (``Y:\\...\\``).
    project["directories"]["root"] += "\\"
    project["platforms"] = [
        {
            **row,
            "soundBankPath": wine_path(row["soundBankPath"]),
            "copiedMediaPath": wine_path(row["copiedMediaPath"]),
        }
        for row in project["platforms"]
    ]

    reader = GenerateReader(project)
    prepared = prepare_operation(
        parse_operation_request(_minimal_generate_request(io_root)),
        read_call=reader,
    ).as_dict()

    plan = prepared["verification_plan"]["plan"]
    assert plan["project_context"]["path"] == expected_project_path
    assert plan["project_context"]["directories"]["root"] == str(
        Path(expected_project_path).parent
    )
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is True


@pytest.mark.parametrize(
    ("reported_root", "error_code"),
    [
        ("../outside", "INVALID_PROJECT_CONTEXT"),
        ("different-project", "PROJECT_PATH_MISMATCH"),
        (r"X:\outside", "INVALID_PROJECT_CONTEXT"),
    ],
)
def test_generate_rejects_escaping_mismatched_or_unmappable_project_root(
    tmp_path: Path,
    reported_root: str,
    error_code: str,
) -> None:
    io_root, project = _project(tmp_path)
    project["directories"]["root"] = reported_root

    with pytest.raises(OperationContractError) as rejected:
        prepare_operation(
            parse_operation_request(_minimal_generate_request(io_root)),
            read_call=GenerateReader(project),
        )

    assert rejected.value.error_code == error_code


def test_generate_named_route_replays_guards_and_verifies_nonempty_bank(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)
    reader = GenerateReader(project)
    parsed = parse_operation_request(
        _request(
            "soundbank.generate",
            {
                "soundbanks": [
                    {
                        "name": "Gameplay_Main",
                        "artifact_expectation": "nonlocalized",
                        "events": [{"kind": "id", "value": EVENT_ID}],
                        "inclusions": ["event", "structure", "media"],
                        "rebuild": True,
                    }
                ],
                "platforms": ["Mac"],
                "skip_languages": True,
                "write_to_disk": True,
                "io_root": str(io_root),
            },
        )
    )
    prepared = prepare_operation(parsed, read_call=reader).as_dict()

    assert prepared["dispatch"]["uri"] == "ak.wwise.core.soundbank.generate"
    assert prepared["dispatch"]["args"]["soundbanks"][0]["events"] == [EVENT_ID]
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is True

    bank = Path(project["platforms"][0]["soundBankPath"]) / "Gameplay_Main.bnk"
    bank.parent.mkdir(parents=True)
    bank.write_bytes(b"BKHD\x00\x01")
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {"logs": []}},
        read_call=reader,
    )

    assert verified.ok is True
    assert all(assertion["passed"] for assertion in verified.assertions)

    failed_log = verify_prepared_operation(
        prepared,
        execution_result={"result": {"logs": [{"severity": "Error", "message": "generation failed"}]}},
        read_call=reader,
    )
    assert failed_log.ok is False


@pytest.mark.parametrize("language_choice", ["explicit", "omitted", "empty"])
def test_generate_localized_expectation_requires_every_requested_language_artifact(tmp_path: Path, language_choice: str) -> None:
    io_root, project = _project(tmp_path)
    project["languages"].append(
        {
            "id": "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}",
            "name": "French(Canada)",
            "shortId": 2,
        }
    )
    reader = GenerateReader(project)
    parsed = parse_operation_request(
        _request(
            "soundbank.generate",
            {
                "soundbanks": [
                    {
                        "name": "Gameplay_Main",
                        "artifact_expectation": "localized",
                    }
                ],
                "platforms": ["Mac"],
                "languages": ["English(US)", "French(Canada)"],
                "skip_languages": False,
                "write_to_disk": True,
                "io_root": str(io_root),
            },
        )
    )
    request = parsed.as_dict()
    if language_choice == "omitted":
        request["arguments"].pop("languages")
    elif language_choice == "empty":
        request["arguments"]["languages"] = []
    parsed = parse_operation_request(request)
    prepared = prepare_operation(parsed, read_call=reader).as_dict()

    native = prepared["dispatch"]["args"]
    assert ("languages" in native) is (language_choice != "omitted")
    if language_choice == "empty":
        assert native["languages"] == []
    english = Path(project["platforms"][0]["soundBankPath"]) / "English(US)" / "Gameplay_Main.bnk"
    english.parent.mkdir(parents=True)
    english.write_bytes(b"BKHD-English")
    verified = verify_prepared_operation(
        prepared,
        execution_result={"result": {"logs": []}},
        read_call=reader,
    )

    assert verified.ok is False
    french = next(
        assertion
        for assertion in verified.assertions
        if assertion["name"].endswith(":1 was created or modified and is non-empty")
    )
    assert french["passed"] is False
    assert french["evidence"]["artifact"]["language"] == "French(Canada)"
    french_path = english.parent.parent / "French(Canada)" / "Gameplay_Main.bnk"
    french_path.parent.mkdir(parents=True)
    french_path.write_bytes(b"BKHD-French")
    assert verify_prepared_operation(prepared, execution_result={"result": {"logs": []}}, read_call=reader).ok


def test_generate_2021_uses_live_file_path_and_hashed_wproj_without_caller_layout(tmp_path: Path) -> None:
    io_root, project_file = _copy_2021_project(tmp_path)
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2021.1",
        "operation": "soundbank.generate",
        "arguments": {
            "soundbanks": [{"name": "Gameplay_Main", "artifact_expectation": "nonlocalized"}],
            "platforms": ["Mac"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": str(io_root),
        },
    }
    reader = Generate2021Reader(project_file)
    prepared = prepare_operation(parse_operation_request(request), read_call=reader).as_dict()

    assert prepared["semantic_preview"]["envelope"]["metadata"]["project_context_authority"] == (
        "waapi_object_get_filePath_plus_hashed_wproj"
    )
    assert prepared["pre_state"]["soundbank_guard"]["plan_sha256"]
    assert any(
        call[1] == {"waql": "from type Project take 2"}
        and "filePath" in call[2]["return"]
        and "workunitIsDirty" in call[2]["return"]
        for call in reader.calls
    )
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is True

    request["arguments"]["attested_project_layout"] = {"id": WWISE_2021_PROJECT_ID}
    with pytest.raises(OperationContractError) as caller_layout:
        parse_operation_request(request)
    assert getattr(caller_layout.value, "error_code", None) == "INVALID_REQUEST"


def test_generate_2021_generic_reflected_waapi_call_route_requires_dedicated_operation(tmp_path: Path) -> None:
    io_root = tmp_path / "isolated-output"
    io_root.mkdir()
    with pytest.raises(OperationContractError) as blocked:
        parse_operation_request(
            {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2021.1",
            "operation": "waapi.call",
            "arguments": {
                "api": "ak.wwise.core.soundbank.generate",
                "args": {
                    "soundbanks": [{"name": "Gameplay_Main"}],
                    "platforms": ["{9C6217D5-DD11-4795-87C1-6CE02853C541}"],
                    "skipLanguages": True,
                    "writeToDisk": True,
                },
                "options": {},
                "io_root": str(io_root),
            },
            }
        )

    assert blocked.value.error_code == "DEDICATED_OPERATION_REQUIRED"
    assert blocked.value.details["required_operations"] == ["soundbank.generate"]


@pytest.mark.parametrize("drift", ["dirty", "escape", "symlink", "proof", "identity", "path", "hook"])
def test_generate_2021_confirmation_rejects_live_project_or_wproj_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    io_root, project_file = _copy_2021_project(tmp_path)
    reader = Generate2021Reader(project_file)
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2021.1",
        "operation": "soundbank.generate",
        "arguments": {
            "soundbanks": [{"name": "Gameplay_Main", "artifact_expectation": "nonlocalized"}],
            "platforms": ["Mac"],
            "skip_languages": True,
            "write_to_disk": True,
            "io_root": str(io_root),
        },
    }
    prepared = prepare_operation(parse_operation_request(request), read_call=reader).as_dict()

    if drift == "dirty":
        reader.dirty = True
    elif drift == "escape":
        reader.project_file = WWISE_2021_PROJECT.resolve()
    elif drift == "symlink":
        link = project_file.parent / "Linked.wproj"
        create_symlink_or_skip(link, project_file)
        reader.project_file = link
    else:
        text = project_file.read_text(encoding="utf-8")
        replacements = {
            "proof": ('WwiseBuild="7485"', 'WwiseBuild="7486"'),
            "identity": ('<Project Name="SampleProject"', '<Project Name="OtherProject"'),
            "path": (
                "<Value Platform=\"Mac\">GeneratedSoundBanks\\Mac\\</Value>",
                "<Value Platform=\"Mac\">..\\..\\..\\Outside</Value>",
            ),
            "hook": (
                '"$(WwiseExePath)\\CopyStreamedFiles.exe" -info "$(InfoFilePath)"',
                '"python" -info "$(InfoFilePath)"',
            ),
        }
        old, new = replacements[drift]
        assert old in text
        project_file.write_text(text.replace(old, new, 1), encoding="utf-8")

    validation = validate_prepared_roles(prepared, read_call=reader)

    assert validation["ok"] is False
    assert validation["status"] == "repreview_required"
    assert any(
        assertion["name"]
        in {
            "closed SoundBank inputs and project context can be replayed unchanged",
            "closed SoundBank plan hash is unchanged since preview",
        }
        and assertion["passed"] is False
        for assertion in validation["assertions"]
    )


class ProjectOnlyReader:
    def __init__(self, project: Mapping[str, Any]) -> None:
        self.project = dict(project)

    def __call__(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        if uri == "ak.wwise.core.getProjectInfo":
            return dict(self.project)
        raise AssertionError((uri, args, options))


def test_convert_external_sources_verifies_exact_outputs_and_no_unreviewed_files(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)
    project_root = Path(project["directories"]["root"])
    source = project_root / "external.wav"
    source.write_bytes(b"RIFF" + b"\x00" * 64)
    source_list = project_root / "external.wsources"
    source_list.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ExternalSourcesList SchemaVersion="1" Root=".">\n'
        '  <Source Path="external.wav" Destination="dialog/external.wav" />\n'
        '</ExternalSourcesList>\n',
        encoding="utf-8",
    )
    output = io_root / "external-output" / "Mac"
    reader = ProjectOnlyReader(project)
    parsed = parse_operation_request(
        _request(
            "soundbank.convertExternalSources",
            {
                "sources": [{"input": str(source_list), "platform": "Mac", "output": str(output)}],
                "io_root": str(io_root),
            },
        )
    )
    prepared = prepare_operation(parsed, read_call=reader).as_dict()

    io_audit = prepared["pre_state"]["soundbank_guard"]["io_audit"]
    assert io_audit["uri"] == "ak.wwise.core.soundbank.convertExternalSources"
    assert {
        (row["json_path"], row["role"], row["raw_path"])
        for row in io_audit["paths"]
    } == {
        ("$.args.sources[0].input", "read", str(source_list)),
        ("$.args.sources[0].output", "write", str(output)),
    }

    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is True
    expected = output / "dialog" / "external.wem"
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"WEM!" + b"\x01" * 32)
    (output / "Wwise.dat").write_bytes(b"DATA")
    verified = verify_prepared_operation(prepared, execution_result={"result": {}}, read_call=reader)

    assert verified.ok is True
    assert all(assertion["passed"] for assertion in verified.assertions)

    (output / "unreviewed.tmp").write_bytes(b"unexpected")
    unexpected = verify_prepared_operation(prepared, execution_result={"result": {}}, read_call=reader)
    assert unexpected.ok is False


class DefinitionReader:
    def __init__(self, project: Mapping[str, Any], *, version: str = "2025.1") -> None:
        self.project = dict(project)
        self.version = version
        self.target_exists = False
        self.wrong_target_inclusions = False
        self.event = _row(EVENT_ID, "Play_Test", "Event", r"\Events\Default Work Unit\Play_Test")
        self.control = _row(CONTROL_BANK_ID, "Control_Bank", "SoundBank", r"\SoundBanks\Default Work Unit\Control_Bank")
        self.target = _row(TARGET_BANK_ID, "Gameplay_Main", "SoundBank", r"\SoundBanks\Default Work Unit\Gameplay_Main")
        self.event["shortId"] = 123
        self.target_inclusions = [
            {"object": {"id": EVENT_ID}, "filter": ["events", "structures", "media"]}
        ]
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def __call__(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((uri, dict(args), dict(options)))
        if uri == "ak.wwise.core.getProjectInfo":
            return dict(self.project)
        if uri == "ak.wwise.core.object.get":
            source = args.get("from")
            if isinstance(source, Mapping) and source.get("id") == [EVENT_ID]:
                return {"return": [self.event]}
            if isinstance(source, Mapping) and source.get("id") == [
                {"shortId": 123, "type": 10}
            ]:
                return {"return": [self.event]}
            if isinstance(source, Mapping) and source.get("id") == [CONTROL_BANK_ID]:
                return {"return": [self.control]}
            if isinstance(source, Mapping) and source.get("id") == [
                EVENT_ID,
                CONTROL_BANK_ID,
            ]:
                return {"return": [self.event, self.control]}
            query = args.get("waql")
            literal = f"{self.event['shortId']}.0" if self.version in {"2022.1", "2023.1"} else str(self.event["shortId"])
            if query == f"from type DialogueEvent where shortId = {literal} take 2":
                return {"return": [self.event]}
            if query == 'from type Event where name = "Play_Test" take 2':
                return {"return": [self.event]}
            if query == 'from type SoundBank where name = "Gameplay_Main" take 2':
                return {"return": [self.target] if self.target_exists else []}
            if query == "from type SoundBank take 257":
                return {"return": [self.control]}
            raise AssertionError((uri, args, options))
        if uri == "ak.wwise.core.soundbank.getInclusions":
            soundbank = args.get("soundbank")
            if soundbank == CONTROL_BANK_ID:
                return {"inclusions": []}
            if soundbank == TARGET_BANK_ID and self.target_exists:
                inclusions = [dict(row) for row in self.target_inclusions]
                if self.wrong_target_inclusions:
                    inclusions = [
                        {
                            **row,
                            "filter": ["events"]
                            if row.get("object") == {"id": EVENT_ID}
                            else row.get("filter"),
                        }
                        for row in inclusions
                    ]
                return {"inclusions": inclusions}
            raise AssertionError((uri, args, options))
        raise AssertionError((uri, args, options))


def test_process_definition_files_resolves_every_identity_and_checks_exact_inclusions(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)
    definition = Path(project["directories"]["root"]) / "banks.tsv"
    definition.write_text(
        f"Gameplay_Main\t{EVENT_ID}\tEvent\tStructure\tMedia\n",
        encoding="utf-8",
    )
    reader = DefinitionReader(project)
    parsed = parse_operation_request(
        _request(
            "soundbank.processDefinitionFiles",
            {"files": [str(definition)], "io_root": str(io_root)},
        )
    )
    prepared = prepare_operation(parsed, read_call=reader).as_dict()

    assert prepared["dispatch"] == {
        "uri": "ak.wwise.core.soundbank.processDefinitionFiles",
        "args": {"files": [str(definition.resolve())]},
        "options": {},
    }
    io_audit = prepared["pre_state"]["soundbank_guard"]["io_audit"]
    assert io_audit["uri"] == "ak.wwise.core.soundbank.processDefinitionFiles"
    assert [
        (row["json_path"], row["role"], row["raw_path"])
        for row in io_audit["paths"]
    ] == [("$.args.files[0]", "read", str(definition))]
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is True
    reader.target_exists = True
    verified = verify_prepared_operation(prepared, execution_result={"result": {}}, read_call=reader)

    assert verified.ok is True
    assert all(assertion["passed"] for assertion in verified.assertions)

    reader.wrong_target_inclusions = True
    mismatch = verify_prepared_operation(prepared, execution_result={"result": {}}, read_call=reader)
    assert mismatch.ok is False


def test_process_definition_files_nonempty_prestate_discloses_unverified_import_effects(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)
    definition = Path(project["directories"]["root"]) / "banks.tsv"
    definition.write_text(f"Gameplay_Main\t{EVENT_ID}\tEvent\tStructure\tMedia\n", encoding="utf-8")
    reader = DefinitionReader(project)
    reader.target_exists = True
    old = {"object": {"id": DEBUG_EVENT_ID}, "filter": ["events", "structures", "media"]}
    requested = {"object": {"id": EVENT_ID}, "filter": ["events", "structures", "media"]}
    reader.target_inclusions = [old]
    prepared = prepare_operation(parse_operation_request(_request("soundbank.processDefinitionFiles",
        {"files": [str(definition)], "io_root": str(io_root)})), read_call=reader).as_dict()
    bank = prepared["verification_plan"]["definition_oracle"]["banks"][0]
    assert bank["before_inclusions"] == [{"object": DEBUG_EVENT_ID.casefold(), "filters": ["events", "media", "structures"]}]
    assert bank["expected_inclusions"] is None
    assert bank["verification_boundary_reasons"] == ["nonempty_preexisting_inclusions"]
    assert prepared["verification_plan"]["verification_scope"]["mode"] == "result_schema_only"
    # Neither preservation nor removal is inferred from an empty native result.
    for actual in ([old, requested], [requested], []):
        reader.target_inclusions = actual
        result = verify_prepared_operation(prepared, execution_result={"result": {}}, read_call=reader)
        assert result.ok and result.status == "result_schema_checked"
        assert result.business_state_verified is False
        assert result.verification_scope["mode"] == "result_schema_only"


def test_process_definition_files_resolves_short_id_through_reflected_uint32_id(
    tmp_path: Path,
) -> None:
    io_root, project = _project(tmp_path)
    definition = Path(project["directories"]["root"]) / "short-id.tsv"
    definition.write_text(
        "Gameplay_Main\t123\tEvent\tStructure\tMedia\n",
        encoding="utf-8",
    )
    reader = DefinitionReader(project)
    parsed = parse_operation_request(
        _request(
            "soundbank.processDefinitionFiles",
            {"files": [str(definition)], "io_root": str(io_root)},
        )
    )

    prepared = prepare_operation(parsed, read_call=reader).as_dict()

    short_id_calls = [
        (args, options)
        for uri, args, options in reader.calls
        if uri == "ak.wwise.core.object.get"
        and args.get("from") == {"id": [{"shortId": 123, "type": 10}]}
    ]
    assert short_id_calls == [
        (
            {"from": {"id": [{"shortId": 123, "type": 10}]}, "transform": [{"range": [0, 2]}]},
            {
                "return": [
                    "id",
                    "name",
                    "type",
                    "path",
                    "parent",
                    "notes",
                    "shortId",
                ]
            },
        )
    ]
    role = prepared["resolved_roles"]["definition.bank[0].inclusion[0]"]
    assert role["object"] == EVENT_ID
    assert role["resolution"] == "live-short-id"
    assert role["row"]["shortId"] == 123


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("number", [1, 123, 3970659059, 4294967295])
def test_process_definition_files_resolves_dialogue_short_id_and_guards_guid_readback(
    tmp_path: Path,
    version: str,
    number: int,
) -> None:
    io_root, project = _project(tmp_path)
    definition = Path(project["directories"]["root"]) / "dialogue-short-id.tsv"
    definition.write_text(
        f"Gameplay_Main\t-DialogueEvent\t{number}\tEvent\tMedia\n",
        encoding="utf-8",
    )
    reader = DefinitionReader(project, version=version)
    reader.event["type"] = "DialogueEvent"
    reader.event["shortId"] = number
    request = _request("soundbank.processDefinitionFiles", {"files": [str(definition)], "io_root": str(io_root)})
    request["version"] = version
    parsed = parse_operation_request(
        request
    )
    prepared = prepare_operation(parsed, read_call=reader).as_dict()
    assert prepared["resolved_roles"]["definition.bank[0].inclusion[0]"]["object"] == EVENT_ID
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is True
    for changed in (number + 1, True, str(number), None):
        reader.event["shortId"] = changed
        guarded = validate_prepared_roles(prepared, read_call=reader)
        assert guarded["ok"] is False, guarded
    reader.event["shortId"] = number
    reader.event["type"] = "Event"
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is False
    reader.event["type"] = "DialogueEvent"
    for changed_id in (CONTROL_BANK_ID, "malformed"):
        reader.event["id"] = changed_id
        assert validate_prepared_roles(prepared, read_call=reader)["ok"] is False


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("write_choice", [None, False])
def test_generate_memory_preserves_native_defaults_and_honest_result_boundary(tmp_path: Path, version: str, write_choice: bool | None) -> None:
    if version == "2021.1":
        io_root, project_file = _copy_2021_project(tmp_path)
        reader = Generate2021Reader(project_file)
        platform = "Windows"
    else:
        io_root, project = _project(tmp_path)
        reader = GenerateReader(project)
        platform = "Mac"
    arguments = {"soundbanks": [{"name": "Temporary_Bank", "artifact_expectation": "nonlocalized"}],
        "platforms": [platform], "io_root": str(io_root)}
    if write_choice is not None:
        arguments["write_to_disk"] = write_choice
    request = _request("soundbank.generate", arguments)
    request["version"] = version
    prepared = prepare_operation(parse_operation_request(request), read_call=reader).as_dict()
    args = prepared["dispatch"]["args"]
    assert args["soundbanks"] == [{"name": "Temporary_Bank"}]
    assert ("writeToDisk" in args) is (write_choice is not None)
    if write_choice is not None:
        assert args["writeToDisk"] is False
    assert not ({"skipLanguages", "languages", "rebuildSoundBanks", "clearAudioFileCache", "rebuildInitBank"} & args.keys())
    from wwise_waapi.builders.schema import validate_semantic_payload
    validate_semantic_payload("ak.wwise.core.soundbank.generate", args, {}, version=version)
    assert prepared["verification_plan"]["plan"]["oracle"]["business_state_requires_artifacts"] is False
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is True
    verified = verify_prepared_operation(prepared, execution_result={"result": {}}, read_call=reader)
    assert verified.ok and verified.status == "result_schema_checked"
    assert verified.business_state_verified is False
    invalid = verify_prepared_operation(prepared, execution_result={"result": {"bankData": "invented"}}, read_call=reader)
    assert invalid.ok is False


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_generate_all_user_banks_keeps_empty_native_list_and_rejects_inventory_drift(tmp_path: Path, version: str) -> None:
    if version == "2021.1":
        io_root, project_file = _copy_2021_project(tmp_path)
        delegate, platform = Generate2021Reader(project_file), "Windows"
    else:
        io_root, project = _project(tmp_path)
        delegate, platform = GenerateReader(project), "Mac"
    bank_row = _row(TARGET_BANK_ID, "Gameplay_Main", "SoundBank", r"\SoundBanks\Default Work Unit\Gameplay_Main")
    class Reader:
        banks = [bank_row]
        def __call__(self, uri, args, options):
            if uri == "ak.wwise.core.object.get" and args.get("waql") == "from type SoundBank take 65":
                return {"return": self.banks}
            if uri == "ak.wwise.core.object.get" and args.get("from", {}).get("id") == [TARGET_BANK_ID]:
                return {"return": [bank_row]}
            return delegate(uri, args, options)
    reader = Reader()
    request = _minimal_generate_request(io_root)
    request["version"] = version
    request["arguments"]["platforms"] = [platform]
    request["arguments"]["soundbanks"] = []
    request["arguments"]["all_user_soundbanks"] = "nonlocalized"
    prepared = prepare_operation(parse_operation_request(request), read_call=reader).as_dict()
    assert prepared["dispatch"]["args"]["soundbanks"] == ([] if version in {"2023.1", "2024.1", "2025.1"} else [{"name": "Gameplay_Main"}])
    assert prepared["verification_plan"]["plan"]["scope"]["user_soundbanks"] == ["Gameplay_Main"]
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is True
    reader.banks = []
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is False
    reader.banks = [bank_row]
    missing = verify_prepared_operation(prepared, execution_result={"result": {}}, read_call=reader)
    assert missing.ok is False
    bank = Path(prepared["verification_plan"]["plan"]["artifact_plan"]["platforms"][0]["expected_user_soundbanks"][0]["expected_artifacts"][0]["path"])
    bank.parent.mkdir(parents=True)
    bank.write_bytes(b"BKHD\x00\x01")
    assert verify_prepared_operation(prepared, execution_result={"result": {}}, read_call=reader).ok


@pytest.mark.parametrize("failure", ["duplicate", "wrong-type", "missing-guid", "oversized"])
def test_generate_all_user_bank_inventory_fails_closed(tmp_path: Path, failure: str) -> None:
    io_root, project = _project(tmp_path)
    row = _row(TARGET_BANK_ID, "Gameplay_Main", "SoundBank", r"\SoundBanks\Default Work Unit\Gameplay_Main")
    rows = [row]
    if failure == "duplicate":
        rows.append(dict(row))
    elif failure == "wrong-type":
        row["type"] = "Event"
    elif failure == "missing-guid":
        row.pop("id")
    else:
        rows = [dict(row) for _ in range(65)]
    def reader(uri, args, options):
        if uri == "ak.wwise.core.object.get" and args.get("waql") == "from type SoundBank take 65":
            return {"return": rows}
        return GenerateReader(project)(uri, args, options)
    request = _minimal_generate_request(io_root)
    request["arguments"].update(soundbanks=[], all_user_soundbanks="nonlocalized")
    with pytest.raises(OperationContractError) as error:
        prepare_operation(parse_operation_request(request), read_call=reader)
    assert error.value.error_code == ("RESULT_LIMIT_EXCEEDED" if failure == "oversized" else "INVALID_READBACK")


def test_generate_temporary_name_collision_and_later_collision_are_blocked(tmp_path: Path) -> None:
    io_root, project = _project(tmp_path)
    rows = []
    def reader(uri, args, options):
        if uri == "ak.wwise.core.object.get" and "where name" in args.get("waql", ""):
            return {"return": rows}
        return GenerateReader(project)(uri, args, options)
    request = _minimal_generate_request(io_root)
    request["arguments"]["soundbanks"][0]["temporary"] = True
    prepared = prepare_operation(parse_operation_request(request), read_call=reader).as_dict()
    rows.append(_row(TARGET_BANK_ID, "Gameplay_Main", "SoundBank", r"\SoundBanks\Default Work Unit\Gameplay_Main"))
    assert validate_prepared_roles(prepared, read_call=reader)["ok"] is False
    with pytest.raises(OperationContractError) as error:
        prepare_operation(parse_operation_request(request), read_call=reader)
    assert error.value.error_code == "NAME_COLLISION"
