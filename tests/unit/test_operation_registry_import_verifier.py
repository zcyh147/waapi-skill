from __future__ import annotations

import base64
from collections import deque
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_import import (  # pyright: ignore[reportMissingImports]
    expected_audio_file_source_result_path,
    regular_file_proof,
)
from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
    PREPARED_OPERATION_CONTRACT,
    OperationContractError,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
    verify_prepared_operation,
)
from wwise_waapi.platform_paths import (  # pyright: ignore[reportMissingImports]
    WWISE_WIRE_PATH_INPUT_AUDIT_CONTRACT,
)


OLD_GUID = "{11111111-1111-1111-1111-111111111111}"
NEW_GUID = "{22222222-2222-2222-2222-222222222222}"
SECOND_GUID = "{33333333-3333-3333-3333-333333333333}"
SOURCE_GUID = "{44444444-4444-4444-4444-444444444444}"
EVENT_GUID = "{55555555-5555-5555-5555-555555555555}"
PARENT_GUID = "{66666666-6666-6666-6666-666666666666}"
OLD_ROOT = r"\Actor-Mixer Hierarchy\Default Work Unit"
NEW_ROOT = r"\Containers\Default Work Unit"
WWISE_2021_PROJECT_ID = "{16164796-C6E6-491A-8799-C42A33110A84}"
WWISE_2021_PROJECT = Path(__file__).resolve().parents[1] / "_org" / "2021.1" / "SampleProject.wproj"
LIVE_SOUND_TYPES = {
    "return": [
        {
            "classId": 65552,
            "name": "Sound",
            "type": "WObject",
        }
    ]
}


class ScriptedReader:
    def __init__(
        self,
        responses: list[Mapping[str, Any]],
        *,
        project_languages: list[Mapping[str, Any]] | None = None,
        project_root: Path | None = None,
        originals_root: Path | None = None,
    ) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
        self.project_languages = [
            dict(row)
            for row in (
                project_languages
                if project_languages is not None
                else [
                    {
                        "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                        "name": "SFX",
                        "shortId": 1,
                    }
                ]
            )
        ]
        self.project_root = (
            project_root or Path(__file__).resolve().parent
        ).resolve()
        self.originals_root = (
            originals_root or self.project_root
        ).resolve()

    def __call__(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((uri, dict(args), dict(options)))
        if uri == "ak.wwise.core.object.getTypes":
            return LIVE_SOUND_TYPES
        if uri == "ak.wwise.core.getProjectInfo":
            return {
                "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "name": "SampleProject",
                "displayTitle": "SampleProject",
                "path": str(self.project_root / "SampleProject.wproj"),
                "isDirty": False,
                "currentLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "referenceLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "currentPlatformId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "directories": {
                    "root": str(self.project_root),
                    "cache": str(self.project_root / ".cache"),
                    "originals": str(self.originals_root),
                    "soundBankOutputRoot": str(self.project_root / "GeneratedSoundBanks"),
                    "commands": str(self.project_root / "Commands"),
                    "properties": str(self.project_root / "Properties"),
                },
                "platforms": [
                    {
                        "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                        "name": "Mac",
                        "baseName": "Mac",
                        "baseDisplayName": "Mac",
                        "soundBankPath": str(self.project_root / "GeneratedSoundBanks/Mac"),
                        "copiedMediaPath": str(self.project_root / "GeneratedSoundBanks/Mac/Media"),
                    }
                ],
                "languages": self.project_languages,
                "defaultConversion": {
                    "id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}",
                    "name": "Default",
                },
            }
        assert uri == "ak.wwise.core.object.get"
        if args.get("waql") == "from type Project take 2":
            return {
                "return": [
                    {
                        "id": WWISE_2021_PROJECT_ID,
                        "name": "SampleProject",
                        "type": "Project",
                        "path": "\\",
                        "filePath": str(WWISE_2021_PROJECT),
                        "workunitIsDirty": False,
                    }
                ]
            }
        return self.responses.popleft()


class Import2021Reader:
    def __init__(self, project_file: Path, responses: list[Mapping[str, Any]]) -> None:
        self.project_file = project_file
        self.responses = deque(responses)

    def __call__(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        if uri == "ak.wwise.core.object.getTypes":
            return LIVE_SOUND_TYPES
        if uri != "ak.wwise.core.object.get":
            raise AssertionError((uri, args, options))
        if args.get("waql") == "from type Project take 2":
            return {
                "return": [
                    {
                        "id": WWISE_2021_PROJECT_ID,
                        "name": "SampleProject",
                        "type": "Project",
                        "path": "\\",
                        "filePath": str(self.project_file),
                        "workunitIsDirty": False,
                    }
                ]
            }
        return self.responses.popleft()


def _media(root: Path, name: str, content: bytes = b"RIFF-closed-import-WAVE") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _target(
    source: Path,
    path: str,
    *,
    index: int = 0,
    pre_state_rows: list[Mapping[str, Any]] | None = None,
    **values: Any,
) -> dict[str, Any]:
    row = {
        "index": index,
        "canonical_target_path": path,
        "canonical_parent_path": path.rsplit("\\", 1)[0],
        "source_file": regular_file_proof(source, field=f"target[{index}].source"),
        "expected_audio_file_source_result_path": (
            expected_audio_file_source_result_path(path, str(source.resolve()))
        ),
        "pre_state_required": True,
        "pre_state_rows": [dict(item) for item in (pre_state_rows or [])],
        **values,
    }
    if row["pre_state_rows"]:
        row["preexisting_id"] = row["pre_state_rows"][0]["id"]
    return row


def _prepared(
    *,
    version: str,
    targets: list[Mapping[str, Any]],
    source_operation: str = "audio.import",
    import_operation: str = "createNew",
    result_contract: str | None = None,
    originals_root: Path | None = None,
) -> dict[str, Any]:
    uri = (
        "ak.wwise.core.audio.import"
        if source_operation == "audio.import"
        else "ak.wwise.core.audio.importTabDelimited"
    )
    if result_contract is None:
        result_contract = (
            "required_log_files_objects"
            if source_operation == "audio.import" and version in {"2023.1", "2024.1", "2025.1"}
            else "objects_only"
        )
    prepared_targets: list[dict[str, Any]] = []
    for target in targets:
        prepared_target = dict(target)
        prepared_target.setdefault(
            "requested_notes_destination",
            (
                "audio_file_source"
                if import_operation == "useExisting"
                and bool(prepared_target.get("pre_state_rows"))
                else "target_object"
            ),
        )
        prepared_targets.append(prepared_target)
    verification_plan: dict[str, Any] = {
        "kind": "closed-audio-import",
        "source_operation": source_operation,
        "uri": uri,
        "version": version,
        "import_operation": import_operation,
        "targets": prepared_targets,
        "allowed_result_paths": sorted(
            {
                path.casefold()
                for target in prepared_targets
                for path in (
                    str(target["canonical_target_path"]),
                    *(
                        [str(target["expected_audio_file_source_result_path"])]
                        if isinstance(
                            target.get("expected_audio_file_source_result_path"),
                            str,
                        )
                        else []
                    ),
                )
            }
        ),
        "result_contract": result_contract,
        "error_log_is_failure": True,
    }
    if originals_root is None:
        first_source = Path(str(prepared_targets[0]["source_file"]["path"]))
        originals_root = first_source.parent / "Originals"
    absolute_root = originals_root.absolute()
    project_root = absolute_root.parent
    verification_plan["originals_context"] = {
        "authority": (
            "waapi_object_get_filePath_plus_hashed_wproj"
            if version == "2021.1"
            else "waapi_getProjectInfo"
        ),
        "version": version,
        "project": {
            "id": WWISE_2021_PROJECT_ID if version == "2021.1" else "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            "name": "SampleProject",
            "path": str(project_root / "SampleProject.wproj"),
        },
        "project_root": str(project_root),
        "originals_root": str(absolute_root),
        "source_proof_sha256": "a" * 64 if version == "2021.1" else None,
    }
    return {
        "contract": PREPARED_OPERATION_CONTRACT,
        "operation": source_operation,
        "verification_plan": verification_plan,
    }


def _object_row(
    path: str,
    original_file: Path,
    *,
    object_id: str = NEW_GUID,
    notes: str = "",
    object_type: str = "Sound",
    relative_path: str = "SFX/Closed/original.wav",
    **values: Any,
) -> dict[str, Any]:
    return {
        "id": object_id,
        "name": path.rsplit("\\", 1)[-1],
        "type": object_type,
        "path": path,
        "parent": {"id": PARENT_GUID},
        "notes": notes,
        "originalFilePath": str(original_file.resolve()),
        "originalRelativeFilePath": relative_path,
        **values,
    }


def _result(
    version: str,
    rows: list[Mapping[str, Any]],
    files: list[Path],
    *,
    source_operation: str = "audio.import",
    log: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"objects": [dict(row) for row in rows]}
    if source_operation == "audio.import" and version in {"2023.1", "2024.1", "2025.1"}:
        payload = {
            "log": [dict(row) for row in (log or [])],
            "files": [str(path.resolve()) for path in files],
            "objects": [dict(row) for row in rows],
        }
    return {"result": payload}


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_closed_audio_import_enforces_each_reflected_version_shape(
    version: str,
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, f"source-{version}.wav")
    copied = _media(tmp_path, f"Originals/copied-{version}.wav")
    root = NEW_ROOT if version == "2025.1" else OLD_ROOT
    path = root + rf"\Imported_{version}"
    target = _target(source, path, requested_object_type="Sound SFX")
    live = _object_row(path, copied)
    log = [{"severity": "Warning", "message": "non-fatal normalization", "index": 0}]

    verified = verify_prepared_operation(
        _prepared(version=version, targets=[target]),
        execution_result=_result(version, [live], [copied], log=log),
        read_call=ScriptedReader([{"return": [live]}]),
    )

    assert verified.status == "verified"
    reflected = next(
        assertion
        for assertion in verified.assertions
        if assertion["name"] == "WAAPI result matches the packaged reflected schema"
    )
    assert reflected["passed"] is True


def test_create_new_accepts_bound_sound_and_audio_file_source_rows(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "created-source.wav", b"RIFF-created-WAVE")
    copied = _media(
        tmp_path,
        "Originals/SFX/Created/created-source.wav",
        b"RIFF-created-WAVE",
    )
    path = OLD_ROOT + r"\Created"
    target = _target(source, path, requested_object_type="Sound SFX")
    live = _object_row(
        path,
        copied,
        activeSource={"id": SOURCE_GUID},
    )
    audio_source = {
        "id": SOURCE_GUID,
        "name": "created-source",
        "type": "AudioFileSource",
        "path": path + r"\created-source",
        "parent": {"id": NEW_GUID, "name": "Created"},
        "notes": "",
        "originalFilePath": str(copied.resolve()),
    }

    verified = verify_prepared_operation(
        _prepared(version="2022.1", targets=[target]),
        execution_result=_result("2022.1", [audio_source, live], [copied]),
        read_call=ScriptedReader(
            [{"return": [live]}, {"return": [audio_source]}]
        ),
    )

    assert verified.status == "verified"
    passed = {item["name"] for item in verified.assertions if item["passed"]}
    assert passed >= {
        "import target 0 is returned exactly once",
        "import target 0 AudioFileSource result is optional but unique",
        "import target 0 returned AudioFileSource parent is the live target",
        "import target 0 returned AudioFileSource is the active source",
    }


@pytest.mark.parametrize(
    ("post_source_id", "expected_status", "expected_preserved"),
    [
        (SOURCE_GUID, "verified", True),
        (SECOND_GUID, "verification_failed", False),
    ],
)
def test_use_existing_binds_explicit_audio_file_source_identity(
    tmp_path: Path,
    post_source_id: str,
    expected_status: str,
    expected_preserved: bool,
) -> None:
    source = _media(tmp_path, "existing-source.wav", b"RIFF-existing-WAVE")
    copied = _media(
        tmp_path,
        "Originals/SFX/Existing/existing-source.wav",
        b"RIFF-existing-WAVE",
    )
    path = OLD_ROOT + r"\Existing"
    expected_source_path = path + r"\existing-source"
    target = _target(
        source,
        path,
        pre_state_rows=[
            {
                "id": OLD_GUID,
                "name": "Existing",
                "type": "Sound",
                "path": path,
                "notes": "before",
            }
        ],
        requested_object_type="Sound SFX",
        validated_properties=[
            {
                "name": "Volume",
                "value": -6.0,
                "metadata_type": "Real32",
                "source": "request",
            }
        ],
        explicit_audio_file_source_pre_state_rows=[
            {
                "id": SOURCE_GUID,
                "name": "existing-source",
                "type": "AudioFileSource",
                "path": expected_source_path,
                "notes": "before source",
            }
        ],
    )
    live = _object_row(
        path,
        copied,
        object_id=OLD_GUID,
        notes="before",
        activeSource={"id": post_source_id},
        **{"@Volume": -6.0},
    )
    audio_source = {
        "id": post_source_id,
        "name": "existing-source",
        "type": "AudioFileSource",
        "path": expected_source_path,
        "parent": {"id": OLD_GUID, "name": "Existing"},
        "notes": "",
        "originalFilePath": str(copied.resolve()),
    }

    verified = verify_prepared_operation(
        _prepared(
            version="2022.1",
            targets=[target],
            import_operation="useExisting",
        ),
        execution_result=_result(
            "2022.1",
            [audio_source, live],
            [copied],
        ),
        read_call=ScriptedReader(
            [{"return": [live]}, {"return": [audio_source]}]
        ),
    )

    assertion = next(
        item
        for item in verified.assertions
        if item["name"]
        == "import target 0 useExisting preserved the explicit AudioFileSource GUID"
    )
    assert verified.status == expected_status
    assert assertion["passed"] is expected_preserved


def test_closed_audio_import_rejects_unsealed_audio_file_source_result(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "expected-source.wav")
    copied = _media(tmp_path, "Originals/SFX/expected-source.wav")
    path = OLD_ROOT + r"\ExpectedSource"
    target = _target(source, path)
    live = _object_row(path, copied)
    unrelated_source = {
        "id": SOURCE_GUID,
        "name": "unrelated",
        "type": "AudioFileSource",
        "path": path + r"\unrelated",
        "parent": {"id": NEW_GUID, "name": "ExpectedSource"},
        "notes": "",
        "originalFilePath": str(copied.resolve()),
    }

    verified = verify_prepared_operation(
        _prepared(version="2022.1", targets=[target]),
        execution_result=_result(
            "2022.1",
            [live, unrelated_source],
            [copied],
        ),
        read_call=ScriptedReader([{"return": [live]}]),
    )

    boundary = next(
        item
        for item in verified.assertions
        if item["name"]
        == "closed import result contains only sealed targets, AudioFileSources, or missing ancestors"
    )
    assert verified.status == "verification_failed"
    assert boundary["passed"] is False
    assert boundary["evidence"]["unexpected_rows"] == [unrelated_source]


def test_closed_audio_import_rejects_audio_file_source_parent_mismatch(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "parent-source.wav")
    copied = _media(tmp_path, "Originals/SFX/parent-source.wav")
    path = OLD_ROOT + r"\ParentMismatch"
    target = _target(source, path)
    live = _object_row(
        path,
        copied,
        activeSource={"id": SOURCE_GUID},
    )
    audio_source = {
        "id": SOURCE_GUID,
        "name": "parent-source",
        "type": "AudioFileSource",
        "path": path + r"\parent-source",
        "parent": {"id": SECOND_GUID, "name": "WrongParent"},
        "notes": "",
        "originalFilePath": str(copied.resolve()),
    }

    verified = verify_prepared_operation(
        _prepared(version="2022.1", targets=[target]),
        execution_result=_result("2022.1", [live, audio_source], [copied]),
        read_call=ScriptedReader(
            [{"return": [live]}, {"return": [audio_source]}]
        ),
    )

    parent = next(
        item
        for item in verified.assertions
        if item["name"]
        == "import target 0 returned AudioFileSource parent is the live target"
    )
    assert verified.status == "verification_failed"
    assert parent["passed"] is False


@pytest.mark.skipif(os.name == "nt", reason="Wine virtual drives are POSIX-only")
def test_copied_media_hash_localizes_wine_y_path_without_subfolder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pwd

    account_home = tmp_path / "account-home"
    originals_root = account_home / "Project" / "Originals"
    source = _media(tmp_path, "wine-source.wav", b"RIFF-wine-WAVE")
    copied = _media(
        originals_root,
        "SFX/wine-source.wav",
        b"RIFF-wine-WAVE",
    )
    monkeypatch.setattr(
        pwd,
        "getpwuid",
        lambda _uid: SimpleNamespace(pw_dir=str(account_home)),
    )
    path = OLD_ROOT + r"\WinePath"
    target = _target(source, path)
    wire_path = r"Y:\Project\Originals\SFX\wine-source.wav"
    live = _object_row(
        path,
        copied,
        originalFilePath=wire_path,
        **{"sound:originalWavFilePath": wire_path},
    )

    verified = verify_prepared_operation(
        _prepared(
            version="2022.1",
            targets=[target],
            originals_root=originals_root,
        ),
        execution_result=_result("2022.1", [live], [copied]),
        read_call=ScriptedReader([{"return": [live]}]),
    )

    assert verified.status == "verified"
    mapped = next(
        item
        for item in verified.assertions
        if item["name"]
        == "import target 0 copied original WAV is inside the sealed Project Originals root"
    )
    assert mapped["passed"] is True
    assert mapped["evidence"]["copied_path"] == str(copied.resolve())


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_tab_delimited_import_remains_objects_only_in_every_version(
    version: str,
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, f"tab-source-{version}.wav")
    copied = _media(tmp_path, f"Originals/tab-copied-{version}.wav")
    root = NEW_ROOT if version == "2025.1" else OLD_ROOT
    path = root + rf"\Tab_{version}"
    target = _target(source, path, requested_language="SFX")
    live = _object_row(path, copied, **{"audioSource:language": {"name": "SFX"}})

    verified = verify_prepared_operation(
        _prepared(
            version=version,
            targets=[target],
            source_operation="audio.importTabDelimited",
        ),
        execution_result=_result(
            version,
            [live],
            [copied],
            source_operation="audio.importTabDelimited",
        ),
        read_call=ScriptedReader([{"return": [live]}]),
    )

    assert verified.status == "verified"
    shape = next(
        assertion
        for assertion in verified.assertions
        if assertion["name"] == "closed import result has the exact versioned shape"
    )
    assert shape["evidence"]["actual_keys"] == ["objects"]


@pytest.mark.parametrize(
    ("version", "auto_check_out_to_source_control"),
    [("2022.1", None), ("2023.1", True)],
)
def test_tab_delimited_prepare_and_verify_share_the_closed_oracle(
    version: str,
    auto_check_out_to_source_control: bool | None,
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "tab-e2e-source.wav")
    copied = _media(tmp_path, "Originals/SFX/Batch/tab-e2e.wav")
    import_file = tmp_path / "batch.tsv"
    import_file.write_text(
        f"Audio File\tObject Path\tOriginalsSubFolder\n{source}\tBatch\\TabE2E\tBatch\n",
        encoding="utf-8",
    )
    location = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": "{77777777-7777-7777-7777-777777777777}"},
        "notes": "",
    }
    arguments: dict[str, Any] = {
        "import_file": str(import_file),
        "import_location": {"kind": "path", "value": OLD_ROOT},
        "import_language": "SFX",
    }
    if auto_check_out_to_source_control is not None:
        arguments["auto_check_out_to_source_control"] = (
            auto_check_out_to_source_control
        )
    parsed = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": version,
            "operation": "audio.importTabDelimited",
            "arguments": arguments,
        }
    )
    prepared = prepare_operation(
        parsed,
        read_call=ScriptedReader(
            [
                {"return": [location]},
                {"return": []},
                {"return": [location]},
                {"return": []},
            ],
            project_root=tmp_path,
        ),
    ).as_dict()
    target_path = OLD_ROOT + r"\Batch\TabE2E"
    live = _object_row(
        target_path,
        copied,
        relative_path="SFX/Batch/tab-e2e.wav",
        **{"audioSource:language": {"name": "SFX"}},
    )

    verified = verify_prepared_operation(
        prepared,
        execution_result=_result(
            version,
            [live],
            [copied],
            source_operation="audio.importTabDelimited",
        ),
        read_call=ScriptedReader([{"return": [live]}]),
    )

    assert prepared["verification_plan"]["kind"] == "closed-audio-import"
    assert prepared["verification_plan"]["result_contract"] == "objects_only"
    assert prepared["dispatch"]["args"]["importLocation"] == PARENT_GUID
    assert prepared["pre_state"]["import_guard"]["wire_path_input_audit"] == {
        "contract": WWISE_WIRE_PATH_INPUT_AUDIT_CONTRACT,
        "uri": "ak.wwise.core.audio.importTabDelimited",
        "scope": "transient_dispatch_read_paths_only",
        "paths": [
            {
                "section": "args",
                "json_path": "$.args.importFile",
                "field": "importFile",
                "role": "read",
                "raw_path": str(import_file.resolve()),
                "resolved_path": str(import_file.resolve()),
            }
        ],
    }
    assert [
        row["field"]
        for row in prepared["pre_state"]["import_guard"]["file_proofs"]
    ] == ["import_file", "source_file_proofs[1]"]
    assert "io_root" not in prepared["request"]["arguments"]
    auto_check_out_supported = version == "2023.1"
    assert (
        "autoCheckOutToSourceControl" in prepared["dispatch"]["args"]
    ) is auto_check_out_supported
    assert prepared["semantic_preview"]["envelope"]["metadata"][
        "source_control_policy"
    ] == {
        "auto_add_to_source_control": False,
        "auto_check_out_to_source_control": bool(
            auto_check_out_to_source_control
        ),
        "auto_check_out_to_source_control_supported": auto_check_out_supported,
        "auto_check_out_to_source_control_dispatched": auto_check_out_supported,
    }
    ancestor_snapshot = next(
        snapshot
        for snapshot in prepared["pre_state"]["import_guard"]["path_snapshots"]
        if snapshot["path"] == OLD_ROOT + r"\Batch"
    )
    assert ancestor_snapshot == {
        "path": OLD_ROOT + r"\Batch",
        "fields": ["id", "name", "type", "path", "parent", "notes"],
        "rows": [],
    }
    assert verified.status == "verified"


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_import_object_get_projection_never_uses_unproven_relative_accessor(
    version: str,
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, f"projection-{version}.wav")
    root = NEW_ROOT if version == "2025.1" else OLD_ROOT
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": root,
        "parent": {"id": OLD_GUID},
        "notes": "",
    }
    parsed = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": version,
            "operation": "audio.import",
            "arguments": {
                "imports": [
                    {
                        "object_path": root + r"\Projection",
                        "audio_file": str(source),
                    }
                ]
            },
        }
    )
    reader = ScriptedReader([{"return": [anchor]}, {"return": []}])

    prepared = prepare_operation(parsed, read_call=reader).as_dict()

    assert "originalRelativeFilePath" not in prepared["dispatch"]["options"]["return"]
    assert all(
        "originalRelativeFilePath" not in options.get("return", [])
        for uri, _args, options in reader.calls
        if uri == "ak.wwise.core.object.get"
    )


def test_use_existing_rejects_only_live_localized_rows_with_non_audio_fields(
    tmp_path: Path,
) -> None:
    existing_source = _media(tmp_path, "existing-localized.wav")
    absent_source = _media(tmp_path, "absent-localized.wav")
    existing_path = OLD_ROOT + r"\ExistingVoice"
    absent_path = OLD_ROOT + r"\NewVoice"
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": OLD_GUID},
        "notes": "",
    }
    existing = {
        "id": OLD_GUID,
        "name": "ExistingVoice",
        "type": "Sound",
        "path": existing_path,
        "parent": {"id": PARENT_GUID},
        "notes": "legacy",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "import_operation": "useExisting",
                "imports": [
                    {
                        "object_path": existing_path,
                        "audio_file": str(existing_source),
                        "import_language": "Japanese",
                        "originals_subfolder": "Dialogue/Japanese",
                        "notes": "must be a separate object mutation",
                    },
                    {
                        "object_path": absent_path,
                        "audio_file": str(absent_source),
                        "import_language": "Japanese",
                        "notes": "safe while the target is created",
                    },
                ],
            },
        }
    )

    with pytest.raises(OperationContractError) as caught:
        prepare_operation(
            request,
            read_call=ScriptedReader(
                [
                    {"return": [anchor]},
                    {"return": [existing]},
                    {"return": [anchor]},
                    {"return": []},
                ]
            ),
        )

    assert caught.value.error_code == "LOCALIZED_EXISTING_IMPORT_FIELDS"
    assert caught.value.details["call_wide_rejection"] is True
    assert caught.value.details["rows"] == [
        {
            "index": 0,
            "target_path": existing_path,
            "import_language": "Japanese",
            "unsupported_fields": ["originals_subfolder", "notes"],
        }
    ]


def test_use_existing_live_sfx_preserves_inline_base64_and_native_directives(
    tmp_path: Path,
) -> None:
    target_path = OLD_ROOT + r"\ExistingSfx"
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": SECOND_GUID},
        "notes": "",
    }
    existing = {
        "id": OLD_GUID,
        "name": "ExistingSfx",
        "type": "Sound",
        "path": target_path,
        "parent": {"id": PARENT_GUID},
        "notes": "preserved",
    }
    inline_wav = b"RIFF\x04\x00\x00\x00WAVE"
    inline_source = (
        "SFX/existing.wav|" + base64.b64encode(inline_wav).decode("ascii")
    )
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "import_operation": "useExisting",
                "imports": [
                    {
                        "object_path": target_path,
                        "audio_file_base64": inline_source,
                        "import_language": "SFX",
                        "dialogue_event": r"\Dialogue Events\Existing",
                        "switch_assignment": r"\Switches\Footwear\Boots",
                    }
                ],
            },
        }
    )

    prepared = prepare_operation(
        request,
        read_call=ScriptedReader(
            [{"return": [anchor]}, {"return": [existing]}],
            project_root=tmp_path,
        ),
    ).as_dict()

    assert prepared["dispatch"]["args"]["imports"] == [
        {
            "objectPath": target_path,
            "audioFileBase64": (
                "SFX\\existing.wav|"
                + base64.b64encode(inline_wav).decode("ascii")
            ),
            "importLanguage": "SFX",
            "dialogueEvent": r"\Dialogue Events\Existing",
            "switchAssignation": r"\Switches\Footwear\Boots",
        }
    ]


def test_use_existing_live_localized_row_has_exact_three_field_wire_shape(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "localized-media-only.wav")
    target_path = OLD_ROOT + r"\ExistingVoice"
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": OLD_GUID},
        "notes": "",
    }
    existing = {
        "id": OLD_GUID,
        "name": "ExistingVoice",
        "type": "Sound",
        "path": target_path,
        "parent": {"id": PARENT_GUID},
        "notes": "preserved",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "import_operation": "useExisting",
                "imports": [
                    {
                        "object_path": target_path,
                        "audio_file": str(source),
                        "object_type": "Sound Voice",
                        "import_language": "Japanese",
                    }
                ],
            },
        }
    )
    reader = ScriptedReader(
        [{"return": [anchor]}, {"return": [existing]}],
        project_languages=[
            {"id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}", "name": "Japanese", "shortId": 2}
        ],
        project_root=tmp_path,
    )

    prepared = prepare_operation(request, read_call=reader).as_dict()

    row = prepared["dispatch"]["args"]["imports"][0]
    wire_path = OLD_ROOT + r"\<Sound Voice>ExistingVoice"
    assert row == {
        "audioFile": str(source.resolve()),
        "objectPath": wire_path,
        "importLanguage": "Japanese",
    }
    assert prepared["verification_plan"]["targets"][0]["preexisting_id"] == OLD_GUID
    assert prepared["semantic_preview"]["envelope"]["metadata"][
        "preflight_consumed_fields"
    ] == [
        {
            "index": 0,
            "target_path": target_path,
            "fields": ["object_type"],
            "proof": "live target type matched before dispatch",
        }
    ]
    assert prepared["semantic_preview"]["envelope"]["metadata"][
        "localized_existing_wire_normalizations"
    ] == [
        {
            "index": 0,
            "input_object_path": target_path,
            "logical_target_path": target_path,
            "wire_object_path": wire_path,
            "wire_object_type": "Sound Voice",
            "basis": {
                "import_operation": "useExisting",
                "preexisting_id": OLD_GUID,
                "reflected_type": "Sound",
                "requested_language": "Japanese",
            },
        }
    ]
    target_snapshot = next(
        snapshot
        for snapshot in prepared["pre_state"]["import_guard"]["path_snapshots"]
        if snapshot["path"] == target_path
    )
    expected_options = {
        "return": target_snapshot["fields"],
        "language": "Japanese",
    }
    assert target_snapshot["options"] == expected_options
    preview_target_calls = [
        call
        for call in reader.calls
        if call[0] == "ak.wwise.core.object.get"
        and call[1] == {"from": {"path": [target_path]}}
    ]
    assert preview_target_calls == [
        (
            "ak.wwise.core.object.get",
            {"from": {"path": [target_path]}},
            expected_options,
        )
    ]

    confirmation_reader = ScriptedReader(
        [
            {"return": [anchor]},
            {"return": [existing]},
            {"return": [existing]},
        ],
        project_languages=[
            {"id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}", "name": "Japanese", "shortId": 2}
        ],
        project_root=tmp_path,
    )
    confirmation = validate_prepared_roles(
        prepared,
        read_call=confirmation_reader,
    )

    assert confirmation["status"] == "valid"
    confirmation_target_calls = [
        call
        for call in confirmation_reader.calls
        if call[0] == "ak.wwise.core.object.get"
        and call[1] == {"from": {"path": [target_path]}}
    ]
    assert confirmation_target_calls == [
        (
            "ak.wwise.core.object.get",
            {"from": {"path": [target_path]}},
            expected_options,
        )
    ]


def test_use_existing_live_localized_typed_input_normalizes_from_canonical_parent(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "typed-localized-media-only.wav")
    dialogue_path = OLD_ROOT + r"\Dialogue"
    target_path = dialogue_path + r"\ExistingVoice"
    requested_path = OLD_ROOT + r"\<Virtual Folder>Dialogue\<Sound>ExistingVoice"
    wire_path = dialogue_path + r"\<Sound Voice>ExistingVoice"
    anchor = {
        "id": PARENT_GUID,
        "name": "Dialogue",
        "type": "Folder",
        "path": dialogue_path,
        "parent": {"id": SECOND_GUID},
        "notes": "",
    }
    existing = {
        "id": OLD_GUID,
        "name": "ExistingVoice",
        "type": "Sound",
        "path": target_path,
        "parent": {"id": PARENT_GUID},
        "notes": "preserved",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "import_operation": "useExisting",
                "imports": [
                    {
                        "object_path": requested_path,
                        "audio_file": str(source),
                        "import_language": "Japanese",
                    }
                ],
            },
        }
    )
    reader = ScriptedReader(
        [{"return": [anchor]}, {"return": [existing]}],
        project_languages=[
            {
                "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "name": "Japanese",
                "shortId": 2,
            }
        ],
        project_root=tmp_path,
    )

    prepared = prepare_operation(request, read_call=reader).as_dict()

    assert prepared["dispatch"]["args"]["imports"][0] == {
        "audioFile": str(source.resolve()),
        "objectPath": wire_path,
        "importLanguage": "Japanese",
    }
    evidence = prepared["semantic_preview"]["envelope"]["metadata"][
        "localized_existing_wire_normalizations"
    ]
    assert evidence[0]["input_object_path"] == requested_path
    assert evidence[0]["logical_target_path"] == target_path
    assert evidence[0]["wire_object_path"] == wire_path
    target_reads = [
        call
        for call in reader.calls
        if call[0] == "ak.wwise.core.object.get"
        and call[1] == {"from": {"path": [target_path]}}
    ]
    assert len(target_reads) == 1
    assert target_reads[0][2]["language"] == "Japanese"


def test_use_existing_live_localized_rejects_explicit_sfx_type_before_dispatch(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "localized-conflicting-type.wav")
    target_path = OLD_ROOT + r"\ExistingVoice"
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": SECOND_GUID},
        "notes": "",
    }
    existing = {
        "id": OLD_GUID,
        "name": "ExistingVoice",
        "type": "Sound",
        "path": target_path,
        "parent": {"id": PARENT_GUID},
        "notes": "preserved",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "import_operation": "useExisting",
                "imports": [
                    {
                        "object_path": target_path,
                        "audio_file": str(source),
                        "object_type": "Sound SFX",
                        "import_language": "Japanese",
                    }
                ],
            },
        }
    )
    reader = ScriptedReader(
        [{"return": [anchor]}, {"return": [existing]}],
        project_languages=[
            {
                "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "name": "Japanese",
                "shortId": 2,
            }
        ],
        project_root=tmp_path,
    )

    with pytest.raises(OperationContractError) as caught:
        prepare_operation(request, read_call=reader)

    assert caught.value.error_code == "INVALID_TARGET_TYPE"
    assert caught.value.details == {
        "index": 0,
        "target_path": target_path,
        "requested_type": "Sound SFX",
        "required_type": "Sound Voice",
    }


@pytest.mark.parametrize("import_operation", ["useExisting", "createNew"])
def test_localized_absent_target_wire_path_is_not_rewritten(
    import_operation: str,
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, f"{import_operation}-absent-localized.wav")
    target_path = OLD_ROOT + rf"\{import_operation}AbsentVoice"
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": SECOND_GUID},
        "notes": "",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "import_operation": import_operation,
                "imports": [
                    {
                        "object_path": target_path,
                        "audio_file": str(source),
                        "object_type": "Sound Voice",
                        "import_language": "Japanese",
                    }
                ],
            },
        }
    )
    reader = ScriptedReader(
        [{"return": [anchor]}, {"return": []}],
        project_languages=[
            {
                "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "name": "Japanese",
                "shortId": 2,
            }
        ],
        project_root=tmp_path,
    )

    prepared = prepare_operation(request, read_call=reader).as_dict()

    assert prepared["dispatch"]["args"]["imports"][0] == {
        "audioFile": str(source.resolve()),
        "objectPath": target_path,
        "objectType": "Sound Voice",
        "importLanguage": "Japanese",
    }
    assert "localized_existing_wire_normalizations" not in prepared[
        "semantic_preview"
    ]["envelope"]["metadata"]


def test_use_existing_sfx_row_may_update_notes_on_an_existing_target(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "existing-sfx.wav")
    target_path = OLD_ROOT + r"\ExistingSfx"
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": OLD_GUID},
        "notes": "",
    }
    existing = {
        "id": OLD_GUID,
        "name": "ExistingSfx",
        "type": "Sound",
        "path": target_path,
        "parent": {"id": PARENT_GUID},
        "notes": "before",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "import_operation": "useExisting",
                "imports": [
                    {
                        "object_path": target_path,
                        "audio_file": str(source),
                        "import_language": "SFX",
                        "notes": "after",
                    }
                ],
            },
        }
    )
    reader = ScriptedReader(
        [{"return": [anchor]}, {"return": [existing]}],
        project_languages=[
            {"id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}", "name": "SFX", "shortId": 1}
        ],
    )

    prepared = prepare_operation(request, read_call=reader).as_dict()

    assert prepared["dispatch"]["args"]["imports"][0]["notes"] == "after"
    assert prepared["verification_plan"]["targets"][0][
        "requested_notes_destination"
    ] == "audio_file_source"
    target_snapshot = next(
        snapshot
        for snapshot in prepared["pre_state"]["import_guard"]["path_snapshots"]
        if snapshot["path"] == target_path
    )
    assert "options" not in target_snapshot
    target_call = next(
        call
        for call in reader.calls
        if call[0] == "ak.wwise.core.object.get"
        and call[1] == {"from": {"path": [target_path]}}
    )
    assert target_call[2] == {"return": target_snapshot["fields"]}


def test_use_existing_rejects_two_competing_audio_source_notes_fields(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "ambiguous-existing-sfx.wav")
    target_path = OLD_ROOT + r"\AmbiguousExistingSfx"
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": SECOND_GUID},
        "notes": "",
    }
    existing = {
        "id": OLD_GUID,
        "name": "AmbiguousExistingSfx",
        "type": "Sound",
        "path": target_path,
        "parent": {"id": PARENT_GUID},
        "notes": "before",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "import_operation": "useExisting",
                "imports": [
                    {
                        "object_path": target_path,
                        "audio_file": str(source),
                        "import_language": "SFX",
                        "notes": "from Notes",
                        "audio_source_notes": "from Audio Source Notes",
                    }
                ],
            },
        }
    )

    with pytest.raises(OperationContractError) as caught:
        prepare_operation(
            request,
            read_call=ScriptedReader(
                [{"return": [anchor]}, {"return": [existing]}]
            ),
        )

    assert caught.value.error_code == "AMBIGUOUS_EXISTING_AUDIO_SOURCE_NOTES"


def test_2021_subfolder_prepare_binds_hashed_wproj_originals_setting(tmp_path: Path) -> None:
    source = _media(tmp_path, "projection-2021-subfolder.wav")
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": OLD_GUID},
        "notes": "",
    }
    parsed = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2021.1",
            "operation": "audio.import",
            "arguments": {
                "imports": [
                    {
                        "object_path": OLD_ROOT + r"\ProjectionSubfolder",
                        "audio_file": str(source),
                        "originals_subfolder": "Dialog",
                    }
                ]
            },
        }
    )

    prepared = prepare_operation(
        parsed,
        read_call=Import2021Reader(
            WWISE_2021_PROJECT,
            [{"return": [anchor]}, {"return": []}],
        ),
    ).as_dict()

    context = prepared["verification_plan"]["originals_context"]
    assert context["authority"] == "waapi_object_get_filePath_plus_hashed_wproj"
    assert context["originals_root"] == str(WWISE_2021_PROJECT.parent / "Originals")
    assert len(context["source_proof_sha256"]) == 64
    assert prepared["pre_state"]["import_guard"]["originals_context"] == context


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_originals_subfolder_is_derived_without_legacy_relative_field(
    version: str,
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, f"derived-source-{version}.wav")
    originals_root = tmp_path / f"Originals-{version}"
    copied = _media(originals_root, "SFX/Dialogue/Chapter06/line.wav")
    root = NEW_ROOT if version == "2025.1" else OLD_ROOT
    path = root + r"\DerivedSubfolder"
    target = _target(
        source,
        path,
        requested_originals_subfolder=r"Dialogue\Chapter06",
    )
    live = _object_row(path, copied)
    live.pop("originalRelativeFilePath")

    verified = verify_prepared_operation(
        _prepared(
            version=version,
            targets=[target],
            originals_root=originals_root,
        ),
        execution_result=_result(version, [live], [copied]),
        read_call=ScriptedReader([{"return": [live]}]),
    )

    assert verified.status == "verified"
    subfolder = next(
        item
        for item in verified.assertions
        if item["name"] == "import target 0 Originals subfolder matches"
    )
    assert subfolder["passed"] is True
    assert subfolder["evidence"]["derived_relative_path"] == "SFX/Dialogue/Chapter06/line.wav"


def test_originals_root_project_context_drift_blocks_confirmation(tmp_path: Path) -> None:
    source = _media(tmp_path, "guard-source.wav")
    original_root = tmp_path / "Originals"
    changed_root = tmp_path / "OtherOriginals"
    original_root.mkdir()
    changed_root.mkdir()
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": OLD_GUID},
        "notes": "",
    }
    parsed = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "imports": [
                    {
                        "object_path": OLD_ROOT + r"\GuardedSubfolder",
                        "audio_file": str(source),
                        "originals_subfolder": "Dialog",
                    }
                ]
            },
        }
    )
    prepared = prepare_operation(
        parsed,
        read_call=ScriptedReader(
            [{"return": [anchor]}, {"return": []}],
            project_root=tmp_path,
            originals_root=original_root,
        ),
    ).as_dict()

    guard = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            [{"return": [anchor]}, {"return": []}],
            project_root=tmp_path,
            originals_root=changed_root,
        ),
    )

    assert guard["status"] == "repreview_required"
    root_guard = next(
        item
        for item in guard["assertions"]
        if item["name"] == "live Project Originals root is unchanged since preview"
    )
    assert root_guard["passed"] is False
    assert root_guard["evidence"]["expected"]["originals_root"] == str(original_root)
    assert root_guard["evidence"]["actual"]["originals_root"] == str(changed_root)


def test_originals_subfolder_rejects_copied_path_escape_even_with_injected_legacy_field(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "escape-source.wav")
    originals_root = tmp_path / "Originals"
    originals_root.mkdir()
    copied = _media(tmp_path, "Outside/Dialog/escape.wav")
    path = OLD_ROOT + r"\Escape"
    target = _target(source, path, requested_originals_subfolder="Dialog")
    live = _object_row(path, copied, relative_path="Dialog/escape.wav")

    verified = verify_prepared_operation(
        _prepared(
            version="2022.1",
            targets=[target],
            originals_root=originals_root,
        ),
        execution_result=_result("2022.1", [live], [copied]),
        read_call=ScriptedReader([{"return": [live]}]),
    )

    subfolder = next(
        item
        for item in verified.assertions
        if item["name"] == "import target 0 Originals subfolder matches"
    )
    assert verified.status == "verification_failed"
    assert subfolder["passed"] is False
    assert subfolder["evidence"]["error"]["error_code"] == "ORIGINALS_PATH_ESCAPE"


@pytest.mark.parametrize("symlink_kind", ["root", "component", "file"])
def test_originals_subfolder_rejects_symlink_root_or_path_components(
    symlink_kind: str,
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, f"symlink-source-{symlink_kind}.wav")
    originals_root = tmp_path / "Originals"
    if symlink_kind == "root":
        real_root = tmp_path / "RealOriginals"
        copied = _media(real_root, "Dialog/symlink.wav")
        originals_root.symlink_to(real_root, target_is_directory=True)
        reported_copied = originals_root / "Dialog/symlink.wav"
    elif symlink_kind == "component":
        originals_root.mkdir()
        real_dialog = tmp_path / "RealDialog"
        copied = _media(real_dialog, "symlink.wav")
        (originals_root / "Dialog").symlink_to(real_dialog, target_is_directory=True)
        reported_copied = originals_root / "Dialog/symlink.wav"
    else:
        (originals_root / "Dialog").mkdir(parents=True)
        copied = _media(tmp_path, "real-symlink.wav")
        reported_copied = originals_root / "Dialog/symlink.wav"
        reported_copied.symlink_to(copied)
    path = OLD_ROOT + rf"\Symlink_{symlink_kind}"
    target = _target(source, path, requested_originals_subfolder="Dialog")
    live = _object_row(path, copied, relative_path="Dialog/symlink.wav")
    live["originalFilePath"] = str(reported_copied.absolute())

    verified = verify_prepared_operation(
        _prepared(
            version="2022.1",
            targets=[target],
            originals_root=originals_root,
        ),
        execution_result=_result("2022.1", [live], [copied]),
        read_call=ScriptedReader([{"return": [live]}]),
    )

    subfolder = next(
        item
        for item in verified.assertions
        if item["name"] == "import target 0 Originals subfolder matches"
    )
    assert verified.status == "verification_failed"
    assert subfolder["passed"] is False
    assert subfolder["evidence"]["error"]["error_code"] == "UNSAFE_ORIGINALS_PATH"


def test_import_anchor_query_rejects_a_row_from_the_wrong_path(tmp_path: Path) -> None:
    source = _media(tmp_path, "wrong-anchor-source.wav")
    wrong_anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": OLD_GUID},
        "notes": "",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "imports": [
                    {
                        "object_path": OLD_ROOT + r"\Batch\WrongAnchor",
                        "audio_file": str(source),
                    }
                ]
            },
        }
    )

    with pytest.raises(OperationContractError) as caught:
        prepare_operation(
            request,
            read_call=ScriptedReader([{"return": [wrong_anchor]}]),
        )

    assert caught.value.error_code == "IDENTITY_MISMATCH"
    assert caught.value.details["requested_path"] == OLD_ROOT + r"\Batch"
    assert caught.value.details["actual_row"]["path"] == OLD_ROOT


@pytest.mark.parametrize("drift_kind", ["ancestor-appeared", "wrong-path-row"])
def test_missing_import_ancestor_drift_blocks_confirmation(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    source = _media(tmp_path, f"ancestor-drift-{drift_kind}.wav")
    ancestor_path = OLD_ROOT + r"\Batch"
    target_path = ancestor_path + r"\DriftTarget"
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": OLD_GUID},
        "notes": "",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "imports": [
                    {
                        "object_path": target_path,
                        "audio_file": str(source),
                    }
                ]
            },
        }
    )
    prepared = prepare_operation(
        request,
        read_call=ScriptedReader(
            [
                {"return": []},
                {"return": [anchor]},
                {"return": []},
            ]
        ),
    ).as_dict()
    unchanged = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            [
                {"return": [anchor]},
                {"return": []},
                {"return": []},
            ]
        ),
    )
    assert unchanged["status"] == "valid"

    appeared = {
        "id": SECOND_GUID,
        "name": "Batch",
        "type": "RandomSequenceContainer",
        "path": ancestor_path,
        "parent": {"id": PARENT_GUID},
        "notes": "",
    }
    if drift_kind == "wrong-path-row":
        appeared = {**appeared, "name": "Unrelated", "path": OLD_ROOT + r"\Unrelated"}

    confirmation = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            [
                {"return": [anchor]},
                {"return": [appeared]},
                {"return": []},
            ]
        ),
    )

    assert confirmation["status"] == "repreview_required"
    drift = next(
        assertion
        for assertion in confirmation["assertions"]
        if assertion["name"] == "import path snapshot 0 unchanged"
    )
    assert drift["passed"] is False
    assert drift["evidence"]["path"] == ancestor_path
    assert drift["evidence"]["expected"] == []
    assert drift["evidence"]["actual"] == [appeared]


@pytest.mark.parametrize(
    ("version", "payload", "failed_assertion"),
    [
        (
            "2022.1",
            {"objects": "ROWS", "log": [], "files": "FILES"},
            "closed import result has the exact versioned shape",
        ),
        (
            "2025.1",
            {"objects": "ROWS", "log": []},
            "closed import result has the exact versioned shape",
        ),
        (
            "2025.1",
            {"objects": "ROWS", "log": [], "files": []},
            "import target 0 copied original WAV is reported exactly once",
        ),
        (
            "2025.1",
            {
                "objects": "ROWS",
                "files": "FILES",
                "log": [{"severity": "Error", "message": "one row failed", "index": 0}],
            },
            "closed import log contains no error",
        ),
    ],
)
def test_closed_audio_import_fails_wrong_shape_missing_fields_and_error_logs(
    version: str,
    payload: Mapping[str, Any],
    failed_assertion: str,
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, f"bad-source-{version}.wav")
    copied = _media(tmp_path, f"Originals/bad-copied-{version}.wav")
    root = NEW_ROOT if version == "2025.1" else OLD_ROOT
    path = root + "\\BadResult"
    target = _target(source, path)
    live = _object_row(path, copied)
    resolved_payload = {
        key: [dict(live)] if value == "ROWS" else [str(copied.resolve())] if value == "FILES" else value
        for key, value in payload.items()
    }

    verified = verify_prepared_operation(
        _prepared(version=version, targets=[target]),
        execution_result={"result": resolved_payload},
        read_call=ScriptedReader([{"return": [live]}]),
    )

    assert verified.status == "verification_failed"
    assertion = next(item for item in verified.assertions if item["name"] == failed_assertion)
    assert assertion["passed"] is False


def test_use_existing_verifies_guid_fields_audio_source_and_original_hash(tmp_path: Path) -> None:
    source = _media(tmp_path, "dialogue-source.wav", b"RIFF-dialogue-WAVE")
    copied = _media(tmp_path, "Originals/SFX/Dialogue/Chapter06/dialogue-source.wav", b"RIFF-dialogue-WAVE")
    path = OLD_ROOT + r"\Dialogue\Line_01"
    before = _object_row(path, copied, object_id=OLD_GUID, notes="before")
    target = _target(
        source,
        path,
        pre_state_rows=[before],
        requested_object_type="Sound SFX",
        requested_notes="localized line",
        requested_language="SFX",
        requested_originals_subfolder=r"Dialogue\Chapter06",
    )
    live = _object_row(
        path,
        copied,
        object_id=OLD_GUID,
        notes="before",
        relative_path=r"SFX\Dialogue\Chapter06\dialogue-source.wav",
        activeSource={"id": SOURCE_GUID},
        **{"audioSource:language": {"name": "SFX"}},
    )
    live.pop("originalRelativeFilePath")
    audio_source = {
        "id": SOURCE_GUID,
        "name": "dialogue-source",
        "type": "AudioFileSource",
        "path": path + "\\dialogue-source",
        "parent": {"id": OLD_GUID, "name": "Line_01"},
        "notes": "localized line",
        "originalFilePath": str(copied.resolve()),
        "audioSource:language": {"name": "SFX"},
    }

    verified = verify_prepared_operation(
        _prepared(
            version="2022.1",
            targets=[target],
            import_operation="useExisting",
            originals_root=tmp_path / "Originals",
        ),
        execution_result=_result("2022.1", [audio_source], [copied]),
        read_call=ScriptedReader([{"return": [live]}, {"return": [audio_source]}]),
    )

    assert verified.status == "verified"
    passed_names = {item["name"] for item in verified.assertions if item["passed"]}
    assert passed_names >= {
        "import target 0 useExisting preserved the GUID",
        "import target 0 reflected type matches the request",
        "import target 0 target result is optional but unique",
        "import target 0 AudioFileSource is returned exactly once",
        "import target 0 untouched notes remain unchanged",
        "import target 0 Audio Source notes match exactly",
        "import target 0 language matches exactly",
        "import target 0 Originals subfolder matches",
        "import target 0 copied original WAV hash matches the source",
    }


def test_localized_verifier_scopes_sound_and_active_source_reads_to_row_language(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "localized-source.wav", b"RIFF-japanese-WAVE")
    japanese_copy = _media(
        tmp_path,
        "Originals/Voices/Japanese/localized-source.wav",
        b"RIFF-japanese-WAVE",
    )
    default_copy = _media(
        tmp_path,
        "Originals/Voices/English(US)/localized-source.wav",
        b"RIFF-default-english-WAVE",
    )
    path = OLD_ROOT + r"\LocalizedReadback"
    before = _object_row(path, default_copy, object_id=OLD_GUID, notes="before")
    target = _target(
        source,
        path,
        pre_state_rows=[before],
        requested_object_type="Sound Voice",
        requested_language="Japanese",
    )
    japanese_sound = _object_row(
        path,
        japanese_copy,
        object_id=OLD_GUID,
        notes="before",
        activeSource={"id": SOURCE_GUID},
        **{"audioSource:language": {"name": "Japanese"}},
    )
    japanese_source = {
        "id": SOURCE_GUID,
        "name": "localized-source",
        "type": "AudioFileSource",
        "path": path + r"\localized-source",
        "parent": {"id": OLD_GUID, "name": "LocalizedReadback"},
        "notes": "",
        "originalFilePath": str(japanese_copy.resolve()),
        "audioSource:language": {"name": "Japanese"},
    }
    default_sound = _object_row(
        path,
        default_copy,
        object_id=OLD_GUID,
        notes="before",
        activeSource={"id": SECOND_GUID},
        **{"audioSource:language": {"name": "English(US)"}},
    )
    default_source = {
        "id": SECOND_GUID,
        "name": "localized-source",
        "type": "AudioFileSource",
        "path": path + r"\localized-source",
        "parent": {"id": OLD_GUID, "name": "LocalizedReadback"},
        "notes": "",
        "originalFilePath": str(default_copy.resolve()),
        "audioSource:language": {"name": "English(US)"},
    }

    class LanguageDependentReader:
        def __init__(self, *, honor_language: bool) -> None:
            self.honor_language = honor_language
            self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

        def __call__(
            self,
            uri: str,
            args: Mapping[str, Any],
            options: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            self.calls.append((uri, dict(args), dict(options)))
            assert uri == "ak.wwise.core.object.get"
            localized = self.honor_language and options.get("language") == "Japanese"
            selector = args["from"]
            if "path" in selector:
                return {"return": [japanese_sound if localized else default_sound]}
            requested_id = selector["id"][0]
            if localized and requested_id == SOURCE_GUID:
                return {"return": [japanese_source]}
            if not localized and requested_id == SECOND_GUID:
                return {"return": [default_source]}
            return {"return": []}

    prepared = _prepared(
        version="2022.1",
        targets=[target],
        import_operation="useExisting",
    )
    language_aware_reader = LanguageDependentReader(honor_language=True)
    verified = verify_prepared_operation(
        prepared,
        execution_result=_result("2022.1", [japanese_source], [japanese_copy]),
        read_call=language_aware_reader,
    )

    assert verified.status == "verified"
    assert [call[2]["language"] for call in language_aware_reader.calls] == [
        "Japanese",
        "Japanese",
    ]
    assert all(set(call[2]) == {"return", "language"} for call in language_aware_reader.calls)

    default_only_reader = LanguageDependentReader(honor_language=False)
    wrong_default = verify_prepared_operation(
        prepared,
        execution_result=_result("2022.1", [japanese_source], [japanese_copy]),
        read_call=default_only_reader,
    )

    assert wrong_default.status == "verification_failed"
    failed_names = {item["name"] for item in wrong_default.assertions if not item["passed"]}
    assert failed_names >= {
        "import target 0 language matches exactly",
        "import target 0 copied original WAV hash matches the source",
    }


@pytest.mark.parametrize(
    ("live_id", "old_readback", "expected_status"),
    [
        (NEW_GUID, [], "verified"),
        (OLD_GUID, ["LIVE"], "verification_failed"),
    ],
)
def test_replace_existing_requires_distinct_new_guid_and_absent_old_guid(
    live_id: str,
    old_readback: list[str],
    expected_status: str,
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "replace-source.wav")
    copied = _media(tmp_path, "Originals/replace.wav")
    path = OLD_ROOT + r"\ReplaceMe"
    before = _object_row(path, copied, object_id=OLD_GUID, notes="unchanged")
    target = _target(source, path, pre_state_rows=[before])
    live = _object_row(path, copied, object_id=live_id, notes="unchanged")
    old_rows = [live] if old_readback else []

    verified = verify_prepared_operation(
        _prepared(
            version="2022.1",
            targets=[target],
            import_operation="replaceExisting",
        ),
        execution_result=_result("2022.1", [live], [copied]),
        read_call=ScriptedReader([{"return": [live]}, {"return": old_rows}]),
    )

    assert verified.status == expected_status
    distinct = next(
        item
        for item in verified.assertions
        if item["name"] == "import target 0 replaceExisting returned a distinct GUID"
    )
    assert distinct["passed"] is (expected_status == "verified")


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize(
    ("requested_action", "action_type"),
    [("Play", 1), ("Stop", 2), ("Pause", 7), ("Resume", 9), ("Break", 34), ("Seek", 36)],
)
def test_closed_audio_import_verifies_exact_event_action_and_target_in_every_version(
    version: str,
    requested_action: str,
    action_type: int,
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, f"event-source-{version}-{requested_action}.wav")
    copied = _media(tmp_path, f"Originals/event-{version}-{requested_action}.wav")
    root = NEW_ROOT if version == "2025.1" else OLD_ROOT
    path = root + rf"\EventSound_{requested_action}"
    event_path = rf"\Events\Default Work Unit\Import Tests\{requested_action}_EventSound"
    target = _target(
        source,
        path,
        requested_event={"path": event_path, "action": requested_action},
        event_pre_state_rows=[],
    )
    live = _object_row(path, copied)
    event = {
        "id": EVENT_GUID,
        "name": "Play_EventSound",
        "type": "Event",
        "path": event_path,
        "parent": {"id": PARENT_GUID},
        "notes": "",
    }
    action = {
        "id": SECOND_GUID,
        "name": "",
        "type": "Action",
        "path": event_path + r"\<Action>",
        "parent": {"id": EVENT_GUID},
        "notes": "",
        "ActionType": action_type,
        "Target": {"id": NEW_GUID, "path": path},
    }
    reader = ScriptedReader(
        [{"return": [live]}, {"return": [event]}, {"return": [action]}]
    )

    verified = verify_prepared_operation(
        _prepared(version=version, targets=[target]),
        execution_result=_result(version, [live], [copied]),
        read_call=reader,
    )

    assert verified.status == "verified"
    assert reader.calls[-1][1] == {
        "from": {"id": [EVENT_GUID]},
        "transform": [{"select": ["children"]}],
    }
    assert reader.calls[-1][2]["return"][-2:] == ["ActionType", "Target"]
    passed = {row["name"] for row in verified.assertions if row["passed"]}
    assert passed >= {
        "import target 0 Event contains exactly one direct Action",
        "import target 0 Event Action type matches exactly",
        "import target 0 Event Action target is the imported object",
    }


@pytest.mark.parametrize(
    ("version", "failure_mode", "failed_assertion"),
    [
        ("2021.1", "missing_action", "import target 0 Event contains exactly one direct Action"),
        ("2022.1", "wrong_action", "import target 0 Event Action type matches exactly"),
        ("2023.1", "wrong_target", "import target 0 Event Action target is the imported object"),
        ("2024.1", "extra_action", "import target 0 Event contains exactly one direct Action"),
        ("2025.1", "missing_target", "import target 0 Event Action target is the imported object"),
    ],
)
def test_closed_audio_import_rejects_missing_wrong_or_ambiguous_event_actions_in_every_version(
    version: str,
    failure_mode: str,
    failed_assertion: str,
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, f"bad-event-source-{version}.wav")
    copied = _media(tmp_path, f"Originals/bad-event-{version}.wav")
    root = NEW_ROOT if version == "2025.1" else OLD_ROOT
    path = root + r"\EventSound"
    event_path = r"\Events\Default Work Unit\Import Tests\Play_EventSound"
    target = _target(
        source,
        path,
        requested_event={"path": event_path, "action": "Play"},
        event_pre_state_rows=[],
    )
    live = _object_row(path, copied)
    event = {
        "id": EVENT_GUID,
        "name": "Play_EventSound",
        "type": "Event",
        "path": event_path,
        "parent": {"id": PARENT_GUID},
        "notes": "",
    }
    action: dict[str, Any] = {
        "id": SECOND_GUID,
        "name": "",
        "type": "Action",
        "path": event_path + r"\<Action>",
        "parent": {"id": EVENT_GUID},
        "notes": "",
        "ActionType": 1,
        "Target": {"id": NEW_GUID, "path": path},
    }
    action_rows: list[Mapping[str, Any]] = [action]
    if failure_mode == "missing_action":
        action_rows = []
    elif failure_mode == "wrong_action":
        action["ActionType"] = 2
    elif failure_mode == "wrong_target":
        action["Target"] = {"id": SOURCE_GUID}
    elif failure_mode == "extra_action":
        action_rows.append({**action, "id": PARENT_GUID})
    elif failure_mode == "missing_target":
        del action["Target"]

    verified = verify_prepared_operation(
        _prepared(version=version, targets=[target]),
        execution_result=_result(version, [live], [copied]),
        read_call=ScriptedReader(
            [{"return": [live]}, {"return": [event]}, {"return": action_rows}]
        ),
    )

    assert verified.status == "verification_failed"
    assertion = next(row for row in verified.assertions if row["name"] == failed_assertion)
    assert assertion["passed"] is False


def test_closed_audio_import_event_oracle_rejects_missing_event_readback(tmp_path: Path) -> None:
    source = _media(tmp_path, "missing-event-source.wav")
    copied = _media(tmp_path, "Originals/missing-event.wav")
    path = OLD_ROOT + r"\MissingEventSound"
    event_path = r"\Events\Default Work Unit\Import Tests\Play_MissingEventSound"
    target = _target(
        source,
        path,
        requested_event={"path": event_path, "action": "Play"},
        event_pre_state_rows=[],
    )
    live = _object_row(path, copied)

    verified = verify_prepared_operation(
        _prepared(version="2022.1", targets=[target]),
        execution_result=_result("2022.1", [live], [copied]),
        read_call=ScriptedReader([{"return": [live]}, {"return": []}]),
    )

    assert verified.status == "verification_failed"
    assertion = next(
        row
        for row in verified.assertions
        if row["name"] == "import target 0 Event exact path resolves once"
    )
    assert assertion["passed"] is False


def test_audio_import_prepare_rejects_a_preexisting_event_path(tmp_path: Path) -> None:
    source = _media(tmp_path, "preexisting-event-source.wav")
    target_path = OLD_ROOT + r"\PreexistingEventSound"
    event_path = r"\Events\Default Work Unit\Import Tests\Play_PreexistingEventSound"
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": OLD_GUID},
        "notes": "",
    }
    event = {
        "id": EVENT_GUID,
        "name": "Play_PreexistingEventSound",
        "type": "Event",
        "path": event_path,
        "parent": {"id": OLD_GUID},
        "notes": "",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "import_operation": "createNew",
                "imports": [
                    {
                        "object_path": target_path,
                        "audio_file": str(source),
                        "event": {"path": event_path, "action": "Play"},
                    }
                ],
            },
        }
    )

    with pytest.raises(OperationContractError) as caught:
        prepare_operation(
            request,
            read_call=ScriptedReader(
                [{"return": [anchor]}, {"return": []}, {"return": [event]}]
            ),
        )

    assert caught.value.error_code == "EVENT_TARGET_EXISTS"


def test_audio_import_prepare_rejects_two_rows_sharing_one_event_path(tmp_path: Path) -> None:
    first_source = _media(tmp_path, "duplicate-event-first.wav")
    second_source = _media(tmp_path, "duplicate-event-second.wav", b"RIFF-second-WAVE")
    event_path = r"\Events\Default Work Unit\Import Tests\Play_Shared"
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": OLD_GUID},
        "notes": "",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "import_operation": "createNew",
                "imports": [
                    {
                        "object_path": OLD_ROOT + r"\SharedEventFirst",
                        "audio_file": str(first_source),
                        "event": {"path": event_path, "action": "Play"},
                    },
                    {
                        "object_path": OLD_ROOT + r"\SharedEventSecond",
                        "audio_file": str(second_source),
                        "event": {"path": event_path, "action": "Play"},
                    },
                ],
            },
        }
    )

    with pytest.raises(OperationContractError) as caught:
        prepare_operation(
            request,
            read_call=ScriptedReader(
                [
                    {"return": [anchor]},
                    {"return": []},
                    {"return": []},
                    {"return": [anchor]},
                    {"return": []},
                ]
            ),
        )

    assert caught.value.error_code == "AMBIGUOUS_EVENT_MAPPING"


def test_closed_audio_import_rejects_partial_target_results(tmp_path: Path) -> None:
    source = _media(tmp_path, "partial-source.wav")
    copied = _media(tmp_path, "Originals/partial.wav")
    first_path = OLD_ROOT + r"\First"
    second_path = OLD_ROOT + r"\Second"
    first = _object_row(first_path, copied, object_id=NEW_GUID)
    second = _object_row(second_path, copied, object_id=SECOND_GUID)
    targets = [
        _target(source, first_path, index=0),
        _target(source, second_path, index=1),
    ]

    verified = verify_prepared_operation(
        _prepared(version="2022.1", targets=targets),
        execution_result=_result("2022.1", [first], [copied]),
        read_call=ScriptedReader([{"return": [first]}, {"return": [second]}]),
    )

    assert verified.status == "verification_failed"
    missing = next(
        item
        for item in verified.assertions
        if item["name"] == "import target 1 is returned exactly once"
    )
    assert missing["passed"] is False


def test_closed_audio_import_rejects_copied_wav_hash_mismatch(tmp_path: Path) -> None:
    source = _media(tmp_path, "hash-source.wav", b"RIFF-source-WAVE")
    copied = _media(tmp_path, "Originals/hash-copy.wav", b"RIFF-different-WAVE")
    path = OLD_ROOT + r"\HashMismatch"
    target = _target(source, path)
    live = _object_row(path, copied)

    verified = verify_prepared_operation(
        _prepared(version="2022.1", targets=[target]),
        execution_result=_result("2022.1", [live], [copied]),
        read_call=ScriptedReader([{"return": [live]}]),
    )

    assert verified.status == "verification_failed"
    mismatch = next(
        item
        for item in verified.assertions
        if item["name"] == "import target 0 copied original WAV hash matches the source"
    )
    assert mismatch["passed"] is False


def test_closed_audio_import_rejects_tampered_result_contract_before_readback(tmp_path: Path) -> None:
    source = _media(tmp_path, "tampered-source.wav")
    path = OLD_ROOT + r"\Tampered"
    prepared = _prepared(
        version="2025.1",
        targets=[_target(source, path)],
        result_contract="objects_only",
    )

    with pytest.raises(OperationContractError) as caught:
        verify_prepared_operation(
            prepared,
            execution_result={"result": {"objects": []}},
            read_call=ScriptedReader([]),
        )

    assert caught.value.error_code == "INVALID_PREVIEW"


def test_closed_audio_import_rejects_extra_result_objects_outside_derived_ancestors(tmp_path: Path) -> None:
    source = _media(tmp_path, "extra-source.wav")
    copied = _media(tmp_path, "Originals/extra-copy.wav")
    path = OLD_ROOT + r"\Expected"
    target = _target(source, path)
    live = _object_row(path, copied)
    extra = {
        **live,
        "id": SECOND_GUID,
        "name": "Unrelated",
        "path": OLD_ROOT + r"\Unrelated",
    }

    verified = verify_prepared_operation(
        _prepared(version="2022.1", targets=[target]),
        execution_result=_result("2022.1", [live, extra], [copied]),
        read_call=ScriptedReader([{"return": [live]}]),
    )

    assert verified.status == "verification_failed"
    boundary = next(
        item
        for item in verified.assertions
        if item["name"] == "closed import result contains only sealed targets, AudioFileSources, or missing ancestors"
    )
    assert boundary["passed"] is False
    assert boundary["evidence"]["unexpected_rows"][0]["path"].endswith(r"\Unrelated")


def test_originals_subfolder_requires_the_exact_parent_suffix(tmp_path: Path) -> None:
    source = _media(tmp_path, "subfolder-source.wav")
    copied = _media(tmp_path, "Originals/Dialog/Extra/subfolder-copy.wav")
    path = OLD_ROOT + r"\Subfolder"
    target = _target(source, path, requested_originals_subfolder="Dialog")
    live = _object_row(
        path,
        copied,
        # This legacy field would pass the old suffix oracle.  The verifier
        # must ignore it and derive Dialog/Extra/subfolder-copy.wav instead.
        relative_path="Dialog/subfolder-copy.wav",
    )

    verified = verify_prepared_operation(
        _prepared(
            version="2022.1",
            targets=[target],
            originals_root=tmp_path / "Originals",
        ),
        execution_result=_result("2022.1", [live], [copied]),
        read_call=ScriptedReader([{"return": [live]}]),
    )

    mismatch = next(
        item
        for item in verified.assertions
        if item["name"] == "import target 0 Originals subfolder matches"
    )
    assert mismatch["passed"] is False
    assert verified.status == "verification_failed"


def _language_import_request(source: Path, language: str) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": OLD_ROOT + r"\LanguageTarget",
                    "audio_file": str(source),
                    "import_language": language,
                }
            ]
        },
    }


def test_localized_import_language_must_exist_and_drift_blocks_confirmation(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "language-source.wav")
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": "{77777777-7777-7777-7777-777777777777}"},
        "notes": "",
    }

    with pytest.raises(OperationContractError) as unavailable:
        prepare_operation(
            parse_operation_request(_language_import_request(source, "Japanese")),
            read_call=ScriptedReader([{"return": [anchor]}, {"return": []}]),
        )
    assert unavailable.value.error_code == "IMPORT_LANGUAGE_UNAVAILABLE"

    prepared = prepare_operation(
        parse_operation_request(_language_import_request(source, "Japanese")),
        read_call=ScriptedReader(
            [{"return": [anchor]}, {"return": []}],
            project_languages=[
                {
                    "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                    "name": "Japanese",
                    "shortId": 2,
                }
            ],
        ),
    ).as_dict()
    confirmation = validate_prepared_roles(
        prepared,
        read_call=ScriptedReader(
            [{"return": [anchor]}, {"return": []}],
            project_languages=[
                {
                    "id": "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}",
                    "name": "English(US)",
                    "shortId": 2,
                }
            ],
        ),
    )

    assert confirmation["status"] == "repreview_required"
    drift = next(
        item
        for item in confirmation["assertions"]
        if item["name"] == "live Project language inventory is unchanged since preview"
    )
    assert drift["passed"] is False


def test_sfx_import_skips_live_project_language_inventory(
    tmp_path: Path,
) -> None:
    source = _media(tmp_path, "sfx-language-source.wav")
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": "{77777777-7777-7777-7777-777777777777}"},
        "notes": "",
    }
    preview_reader = ScriptedReader(
        [{"return": [anchor]}, {"return": []}],
        project_languages=[
            {
                "id": "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}",
                "name": "Japanese",
                "shortId": 2,
            }
        ],
    )

    prepared = prepare_operation(
        parse_operation_request(_language_import_request(source, "sfx")),
        read_call=preview_reader,
    ).as_dict()

    assert prepared["dispatch"]["args"]["imports"][0]["importLanguage"] == "SFX"
    assert prepared["pre_state"]["import_guard"]["language_inventory"] is None
    # One Project-info read now seals the Originals root for copied-media
    # verification; SFX still adds no second read for language inventory.
    assert sum(
        call[0] == "ak.wwise.core.getProjectInfo"
        for call in preview_reader.calls
    ) == 1

    confirmation_reader = ScriptedReader(
        [{"return": [anchor]}, {"return": []}],
        project_languages=[],
    )
    confirmation = validate_prepared_roles(
        prepared,
        read_call=confirmation_reader,
    )

    assert confirmation["status"] == "valid"
    assert sum(
        call[0] == "ak.wwise.core.getProjectInfo"
        for call in confirmation_reader.calls
    ) == 1


def test_mixed_sfx_and_localized_import_validates_only_localized_languages(
    tmp_path: Path,
) -> None:
    sfx_source = _media(tmp_path, "mixed-sfx.wav")
    localized_source = _media(tmp_path, "mixed-japanese.wav")
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": "{77777777-7777-7777-7777-777777777777}"},
        "notes": "",
    }
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "audio.import",
            "arguments": {
                "imports": [
                    {
                        "object_path": OLD_ROOT + r"\MixedSfx",
                        "audio_file": str(sfx_source),
                        "import_language": "SFX",
                    },
                    {
                        "object_path": OLD_ROOT + r"\MixedJapanese",
                        "audio_file": str(localized_source),
                        "import_language": "Japanese",
                    },
                ]
            },
        }
    )
    reader = ScriptedReader(
        [
            {"return": [anchor]},
            {"return": []},
            {"return": [anchor]},
            {"return": []},
        ],
        project_languages=[
            {
                "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "name": "Japanese",
                "shortId": 2,
            }
        ],
    )

    prepared = prepare_operation(request, read_call=reader).as_dict()

    assert [
        row["importLanguage"]
        for row in prepared["dispatch"]["args"]["imports"]
    ] == ["SFX", "Japanese"]
    project_info_calls = [
        call for call in reader.calls if call[0] == "ak.wwise.core.getProjectInfo"
    ]
    # One read seals Originals and one validates the localized language.
    assert len(project_info_calls) == 2
    assert [
        row["name"]
        for row in prepared["pre_state"]["import_guard"]["language_inventory"][
            "languages"
        ]
    ] == ["Japanese"]


@pytest.mark.parametrize("drift_kind", ["hash", "language-list"])
def test_2021_import_language_wproj_drift_blocks_confirmation(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    project_root = tmp_path / "SampleProject"
    project_root.mkdir()
    (project_root / "Originals").mkdir()
    project_file = project_root / "SampleProject.wproj"
    shutil.copy2(WWISE_2021_PROJECT, project_file)
    source = _media(tmp_path, "language-2021.wav")
    anchor = {
        "id": PARENT_GUID,
        "name": "Default Work Unit",
        "type": "WorkUnit",
        "path": OLD_ROOT,
        "parent": {"id": "{77777777-7777-7777-7777-777777777777}"},
        "notes": "",
    }
    request = {
        **_language_import_request(source, "English(US)"),
        "version": "2021.1",
    }
    prepared = prepare_operation(
        parse_operation_request(request),
        read_call=Import2021Reader(project_file, [{"return": [anchor]}, {"return": []}]),
    ).as_dict()

    text = project_file.read_text(encoding="utf-8")
    if drift_kind == "hash":
        project_file.write_text(text + "\n", encoding="utf-8")
    else:
        assert "English(US)" in text
        project_file.write_text(text.replace("English(US)", "Japanese", 1), encoding="utf-8")

    confirmation = validate_prepared_roles(
        prepared,
        read_call=Import2021Reader(project_file, [{"return": [anchor]}, {"return": []}]),
    )

    assert confirmation["status"] == "repreview_required"
    drift = next(
        item
        for item in confirmation["assertions"]
        if item["name"] == "live Project language inventory is unchanged since preview"
    )
    assert drift["passed"] is False
