"""Voice reimport must bind a language-specific source, not its ambiguous path."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
from typing import Any, Mapping
import xml.etree.ElementTree as ET

import pytest

from tests.unit.test_operation_registry_import_verifier import ScriptedReader
from wwise_waapi.operation_registry import (
    OPERATION_REQUEST_CONTRACT,
    OperationContractError,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
)


VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
OWNER = "{11111111-1111-1111-1111-111111111111}"
PARENT = "{22222222-2222-2222-2222-222222222222}"
EN_SOURCE = "{33333333-3333-3333-3333-333333333333}"
JP_SOURCE = "{44444444-4444-4444-4444-444444444444}"
OTHER_SOURCE = "{55555555-5555-5555-5555-555555555555}"
EN_LANGUAGE = "{273F02D0-F4F6-49D6-B2F2-B46585A2406B}"
JP_LANGUAGE = "{66666666-6666-6666-6666-666666666666}"


class VoiceReader(ScriptedReader):
    """Fake only WAAPI reads; compiler and preview guard remain production code."""

    def __init__(self, tmp_path: Path, version: str, children: list[dict[str, Any]]) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir(exist_ok=True)
        (project_root / "Originals").mkdir(exist_ok=True)
        project_file = project_root / "SampleProject.wproj"
        if not project_file.exists():
            original = Path(__file__).resolve().parents[1] / "_org/2021.1/SampleProject.wproj"
            shutil.copy2(original, project_file)
            document = ET.parse(project_file)
            languages = document.find(".//LanguageList")
            assert languages is not None
            ET.SubElement(languages, "Language", {"Name": "Japanese", "ID": JP_LANGUAGE})
            document.write(project_file, encoding="utf-8", xml_declaration=True)
        super().__init__(
            [], project_root=project_root, originals_root=project_root / "Originals",
            legacy_project_file=project_file,
            project_languages=[
                {"id": EN_LANGUAGE, "name": "English(US)", "shortId": 1},
                {"id": JP_LANGUAGE, "name": "Japanese", "shortId": 2},
            ],
        )
        self.root = r"\Containers\Default Work Unit" if version == "2025.1" else r"\Actor-Mixer Hierarchy\Default Work Unit"
        self.owner = {"id": OWNER, "type": "Sound", "name": "Voice", "path": self.root + r"\Voice",
                      "parent": {"id": PARENT}, "notes": "preserved"}
        self.anchor = {"id": PARENT, "type": "WorkUnit", "name": "Default Work Unit", "path": self.root,
                       "parent": {"id": OTHER_SOURCE}, "notes": ""}
        self.children = deepcopy(children)
        for child in self.children:
            child.setdefault("path", self.owner["path"] + r"\Line")

    def __call__(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
        if uri != "ak.wwise.core.object.get" or args.get("waql") == "from type Project take 2":
            return super().__call__(uri, args, options)
        self.calls.append((uri, dict(args), dict(options)))
        if args.get("waql") == f'from object "{OWNER}" select children take 129':
            return {"return": deepcopy(self.children)}
        identity = args.get("from", {})
        if "path" in identity:
            known = {self.root: self.anchor, self.owner["path"]: self.owner}
            return {"return": [deepcopy(known[path]) for path in identity["path"] if path in known]}
        if "id" in identity:
            known = {PARENT: self.anchor, OWNER: self.owner}
            return {"return": [deepcopy(known[guid]) for guid in identity["id"] if guid in known]}
        raise AssertionError((uri, args, options))


def source(guid: str, language: str) -> dict[str, Any]:
    return {"id": guid, "name": "Line", "type": "AudioFileSource", "parent": {"id": OWNER},
            "audioSource:language": {"id": EN_LANGUAGE if language == "English(US)" else JP_LANGUAGE,
                                     "name": language}}


def prepare(tmp_path: Path, version: str, children: list[dict[str, Any]],
            *, language: str = "English(US)", typed: bool = False) -> tuple[dict[str, Any], VoiceReader, Path]:
    media = tmp_path / "Line.wav"
    media.write_bytes(b"RIFF-localized-voice-program-fixture-WAVE")
    reader = VoiceReader(tmp_path, version, children)
    item = {"object_path": reader.root + (r"\<Sound Voice>Voice" if typed else r"\Voice"),
            "object_type": "Sound Voice", "audio_file": str(media), "import_language": language}
    parsed = parse_operation_request({
        "contract": OPERATION_REQUEST_CONTRACT, "version": version, "operation": "audio.import",
        "arguments": {"import_operation": "useExisting", "imports": [item]},
    })
    return prepare_operation(parsed, read_call=reader).as_dict(), reader, media


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("typed", [False, True])
def test_cross_family_voice_reimport_binds_exact_language_guid_without_active_source(
    tmp_path: Path, version: str, typed: bool,
) -> None:
    prepared, reader, media = prepare(tmp_path, version, [
        source(JP_SOURCE, "Japanese"), source(EN_SOURCE, "English(US)"),
    ], typed=typed)
    expected = {
        "audioFile": str(media.resolve()), "importLanguage": "English(US)",
        "objectPath": reader.root + r"\<Sound Voice>Voice",
    }
    if version == "2025.1":
        expected.update({"importLocation": EN_SOURCE, "objectPath": ""})
    assert prepared["dispatch"]["args"]["imports"] == [expected]
    target = prepared["verification_plan"]["targets"][0]
    assert target["preexisting_id"] == OWNER
    assert target["localized_audio_file_source_id"] == EN_SOURCE
    assert "activeSource" not in reader.owner
    assert {row["id"] for row in target["localized_source_snapshot"]["rows"]} == {EN_SOURCE, JP_SOURCE}


@pytest.mark.parametrize("version", VERSIONS)
def test_cross_family_voice_new_language_never_reuses_same_named_other_language_source(
    tmp_path: Path, version: str,
) -> None:
    prepared, reader, media = prepare(tmp_path, version, [source(EN_SOURCE, "English(US)")], language="Japanese")
    assert prepared["dispatch"]["args"]["imports"] == [{
        "audioFile": str(media.resolve()), "importLanguage": "Japanese",
        "objectPath": reader.root + r"\<Sound Voice>Voice",
    }]
    assert prepared["verification_plan"]["targets"][0]["localized_audio_file_source_id"] is None


@pytest.mark.parametrize("version", VERSIONS)
def test_cross_family_voice_duplicate_language_filename_is_rejected_before_dispatch(
    tmp_path: Path, version: str,
) -> None:
    with pytest.raises(OperationContractError) as rejected:
        prepare(tmp_path, version, [source(EN_SOURCE, "English(US)"), source(OTHER_SOURCE, "English(US)")])
    assert rejected.value.error_code == "AMBIGUOUS_LOCALIZED_SOURCE"


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("malformed", ["guid", "parent", "language", "duplicate-id", "limit"])
def test_cross_family_voice_source_discovery_rejects_malformed_unrelated_or_unbounded_rows(
    tmp_path: Path, version: str, malformed: str,
) -> None:
    rows = [source(EN_SOURCE, "English(US)")]
    if malformed == "guid":
        rows[0]["id"] = "not-a-guid"
    elif malformed == "parent":
        rows[0]["parent"] = {"id": OTHER_SOURCE}
    elif malformed == "language":
        del rows[0]["audioSource:language"]
    elif malformed == "duplicate-id":
        rows.append(deepcopy(rows[0]))
    else:
        rows *= 129
    with pytest.raises(OperationContractError) as rejected:
        prepare(tmp_path, version, rows)
    assert rejected.value.error_code == ("LOCALIZED_SOURCE_LIMIT_EXCEEDED" if malformed == "limit" else "INVALID_READBACK")


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("change", ["none", "reordered", "source-replaced", "other-language-removed"])
def test_cross_family_voice_execution_guard_detects_source_drift_but_not_result_order(
    tmp_path: Path, version: str, change: str,
) -> None:
    prepared, reader, _ = prepare(tmp_path, version, [source(EN_SOURCE, "English(US)"), source(JP_SOURCE, "Japanese")])
    if change == "reordered":
        reader.children.reverse()
    elif change == "source-replaced":
        reader.children[0]["id"] = OTHER_SOURCE
    elif change == "other-language-removed":
        reader.children.pop()
    guard = validate_prepared_roles(prepared, read_call=reader)
    assert guard["ok"] is (change in {"none", "reordered"}), guard
