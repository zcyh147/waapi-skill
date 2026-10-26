from __future__ import annotations

import copy
import os
from typing import Any

import pytest

from tests.destructive.support.workflow_evidence import (
    WorkflowEvidenceError,
    validate_audio_import_business_evidence,
    validate_soundbank_inclusions_business_evidence,
    validate_switch_assignment_business_evidence,
)


TARGET_ID = "{11111111-1111-1111-1111-111111111111}"
SOURCE_ID = "{22222222-2222-2222-2222-222222222222}"
BANK_ID = "{33333333-3333-3333-3333-333333333333}"
INCLUDED_ID = "{44444444-4444-4444-4444-444444444444}"
CONTAINER_ID = "{55555555-5555-5555-5555-555555555555}"
GROUP_ID = "{66666666-6666-6666-6666-666666666666}"
CHILD_ID = "{77777777-7777-7777-7777-777777777777}"
SWITCH_ID = "{88888888-8888-8888-8888-888888888888}"
OTHER_ID = "{99999999-9999-9999-9999-999999999999}"
TARGET_PATH = r"\Actor-Mixer Hierarchy\Default Work Unit\Imported"
SOURCE_PATH = TARGET_PATH + r"\source"
NOTES = "closed import notes"


def _verification(operation: str, readbacks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "operation": operation,
        "ok": True,
        "status": "verified",
        "business_state_verified": True,
        # Deliberately omit assertion names: the business oracle must consume
        # structured execution/readback evidence rather than display wording.
        "assertions": [{"passed": True, "evidence": {"structured": True}}],
        "readbacks": readbacks,
    }


def _audio_case(version: str = "2025.1") -> tuple[dict[str, Any], dict[str, Any]]:
    target = {
        "id": TARGET_ID,
        "name": "Imported",
        "type": "Sound",
        "path": TARGET_PATH,
        "notes": NOTES,
        "activeSource": {"id": SOURCE_ID},
    }
    source = {
        "id": SOURCE_ID,
        "name": "source",
        "type": "AudioFileSource",
        "path": SOURCE_PATH,
        "originalFilePath": r"C:\Project\Originals\SFX\source.wav",
    }
    result: dict[str, Any] = {"objects": [dict(target), dict(source)]}
    if version in {"2023.1", "2024.1", "2025.1"}:
        result = {
            "log": [],
            "files": [r"C:\Project\Originals\SFX\source.wav"],
            **result,
        }
    execution = {"dispatch_result": {"result": result}}
    verification = _verification(
        "audio.import",
        [
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"path": [TARGET_PATH]}},
                "options": {},
                "result": {"return": [target]},
            },
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"id": [SOURCE_ID]}},
                "options": {},
                "result": {"return": [source]},
            },
        ],
    )
    return execution, verification


@pytest.mark.parametrize(
    ("version", "source_file"),
    [("2022.1", "/fixtures/source.wav"), ("2025.1", r"C:\fixtures\source.wav")],
)
def test_audio_import_business_evidence_accepts_versioned_structural_proof(
    version: str,
    source_file: str,
) -> None:
    execution, verification = _audio_case(version)

    validate_audio_import_business_evidence(
        execution=execution,
        verification=verification,
        version=version,
        expected_target_path=TARGET_PATH,
        expected_target_id=TARGET_ID,
        expected_notes=NOTES,
        source_file=source_file,
    )


def test_2021_audio_import_uses_result_bound_source_when_accessor_is_absent() -> None:
    execution, verification = _audio_case("2021.1")
    execution["dispatch_result"]["result"]["objects"][0].pop("activeSource")
    verification["readbacks"][0]["result"]["return"][0].pop("activeSource")
    execution["dispatch_result"]["result"]["objects"][1]["parent"] = {
        "id": TARGET_ID
    }

    validate_audio_import_business_evidence(
        execution=execution,
        verification=verification,
        version="2021.1",
        expected_target_path=TARGET_PATH,
        expected_target_id=TARGET_ID,
        expected_notes=NOTES,
        source_file="/fixtures/source.wav",
    )


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        ("path", "path"),
        ("guid", "GUID"),
        ("type", "type"),
        ("log", "log"),
        ("active-source", "activeSource"),
    ],
)
def test_audio_import_business_evidence_rejects_targeted_tampering(
    tamper: str,
    message: str,
) -> None:
    execution, verification = _audio_case("2025.1")
    execution = copy.deepcopy(execution)
    verification = copy.deepcopy(verification)
    if tamper == "path":
        execution["dispatch_result"]["result"]["objects"][0]["path"] += "_drift"
    elif tamper == "guid":
        execution["dispatch_result"]["result"]["objects"][0]["id"] = OTHER_ID
    elif tamper == "type":
        verification["readbacks"][0]["result"]["return"][0]["type"] = "ActorMixer"
    elif tamper == "log":
        execution["dispatch_result"]["result"]["log"] = [
            {"severity": "Error", "message": "rejected", "index": 0}
        ]
    else:
        verification["readbacks"][0]["result"]["return"][0]["activeSource"] = {
            "id": OTHER_ID
        }

    with pytest.raises(WorkflowEvidenceError, match=message):
        validate_audio_import_business_evidence(
            execution=execution,
            verification=verification,
            version="2025.1",
            expected_target_path=TARGET_PATH,
            expected_target_id=TARGET_ID,
            expected_notes=NOTES,
            source_file=r"C:\fixtures\source.wav",
        )


def _soundbank_verification(filters: list[str]) -> dict[str, Any]:
    return _verification(
        "soundbank.setInclusions",
        [
            {
                "uri": "ak.wwise.core.soundbank.getInclusions",
                "args": {"soundbank": BANK_ID},
                "options": {},
                "result": {
                    "inclusions": [
                        {"object": {"id": INCLUDED_ID}, "filter": filters}
                    ]
                },
            }
        ],
    )


def test_soundbank_business_evidence_accepts_exact_object_filter_state() -> None:
    validate_soundbank_inclusions_business_evidence(
        _soundbank_verification(["structures", "media"]),
        soundbank_id=BANK_ID,
        expected=[
            {"object": INCLUDED_ID.casefold(), "filters": ["media", "structures"]}
        ],
    )


@pytest.mark.parametrize(
    ("tamper", "message"),
    [("filter", "filter"), ("object", "object")],
)
def test_soundbank_business_evidence_rejects_tampering(
    tamper: str,
    message: str,
) -> None:
    verification = _soundbank_verification(
        ["events"] if tamper == "filter" else ["structures", "media"]
    )
    if tamper == "object":
        verification["readbacks"][0]["result"]["inclusions"][0]["object"] = {
            "id": OTHER_ID
        }
    with pytest.raises(WorkflowEvidenceError, match=message):
        validate_soundbank_inclusions_business_evidence(
            verification,
            soundbank_id=BANK_ID,
            expected=[
                {
                    "object": INCLUDED_ID.casefold(),
                    "filters": ["media", "structures"],
                }
            ],
        )


def _switch_verification(*, should_exist: bool) -> dict[str, Any]:
    pairs = (
        [{"child": {"id": CHILD_ID}, "stateOrSwitch": {"id": SWITCH_ID}}]
        if should_exist
        else []
    )
    return _verification(
        (
            "switchContainer.addAssignment"
            if should_exist
            else "switchContainer.removeAssignment"
        ),
        [
            {
                "uri": "ak.wwise.core.switchContainer.getAssignments",
                "args": {"id": CONTAINER_ID},
                "options": {},
                "result": {"return": pairs},
            },
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"id": [CONTAINER_ID]}},
                "options": {},
                "result": {
                    "return": [
                        {
                            "id": CONTAINER_ID,
                            "type": "SwitchContainer",
                            "SwitchGroupOrStateGroup": {"id": GROUP_ID},
                        }
                    ]
                },
            },
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"id": [CHILD_ID]}},
                "options": {},
                "result": {
                    "return": [{"id": CHILD_ID, "type": "Sound", "parent": CONTAINER_ID}]
                },
            },
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"id": [GROUP_ID]}},
                "options": {},
                "result": {"return": [{"id": GROUP_ID, "type": "SwitchGroup"}]},
            },
            {
                "uri": "ak.wwise.core.object.get",
                "args": {"from": {"id": [SWITCH_ID]}},
                "options": {},
                "result": {
                    "return": [{"id": SWITCH_ID, "type": "Switch", "parent": GROUP_ID}]
                },
            },
        ],
    )


@pytest.mark.parametrize("should_exist", [True, False])
def test_switch_assignment_business_evidence_accepts_exact_pair_state(
    should_exist: bool,
) -> None:
    validate_switch_assignment_business_evidence(
        _switch_verification(should_exist=should_exist),
        switch_container_id=CONTAINER_ID,
        switch_group_id=GROUP_ID,
        child_id=CHILD_ID,
        state_or_switch_id=SWITCH_ID,
        should_exist=should_exist,
    )


def test_switch_assignment_business_evidence_rejects_pair_tampering() -> None:
    verification = _switch_verification(should_exist=True)
    verification["readbacks"][0]["result"]["return"][0]["stateOrSwitch"] = {
        "id": OTHER_ID
    }

    with pytest.raises(WorkflowEvidenceError, match="pair"):
        validate_switch_assignment_business_evidence(
            verification,
            switch_container_id=CONTAINER_ID,
            switch_group_id=GROUP_ID,
            child_id=CHILD_ID,
            state_or_switch_id=SWITCH_ID,
            should_exist=True,
        )


def test_switch_assignment_business_evidence_rejects_relationship_tampering() -> None:
    verification = _switch_verification(should_exist=True)
    verification["readbacks"][2]["result"]["return"][0]["parent"] = OTHER_ID

    with pytest.raises(WorkflowEvidenceError, match="relationship"):
        validate_switch_assignment_business_evidence(
            verification,
            switch_container_id=CONTAINER_ID,
            switch_group_id=GROUP_ID,
            child_id=CHILD_ID,
            state_or_switch_id=SWITCH_ID,
            should_exist=True,
        )


@pytest.mark.parametrize("fault", (None, "notes-on-source", "partial-post-read", "indeterminate"))
def test_localized_tsv_native_witness_reaches_persisted_final_writer(tmp_path, monkeypatch, fault):
    _assert_localized_native_witness_final_writer(tmp_path, monkeypatch, fault=fault, witness_kind="notes-columns")


@pytest.mark.parametrize("witness_kind", ("ordinary-owner-source", "explicit-source-tsv"))
@pytest.mark.parametrize("fault", (None, "missing-field", "wrong-identity", "indeterminate"))
def test_owner_source_native_witnesses_reach_persisted_final_writer(tmp_path, monkeypatch, fault, witness_kind):
    _assert_localized_native_witness_final_writer(tmp_path, monkeypatch, fault=fault, witness_kind=witness_kind)


@pytest.mark.parametrize("fault", ("missing-bus", "wrong-bus-parent"))
def test_ordinary_owner_source_native_witness_rejects_invalid_selected_bus(tmp_path, monkeypatch, fault):
    _assert_localized_native_witness_final_writer(tmp_path, monkeypatch, fault=fault, witness_kind="ordinary-owner-source")


def _assert_localized_native_witness_final_writer(tmp_path, monkeypatch, *, fault, witness_kind):
    """Real public Gateway/collector/finalizer; only native Wwise is substituted."""
    import importlib
    import hashlib
    import json
    import re
    import uuid
    from pathlib import Path
    from types import SimpleNamespace
    from tests.unit.test_audio_import_business_gateway import ImportFieldsClient, _env, waapi_gateway
    from tests.unit.test_profiler_input_native_fixture import _finish
    from tests.destructive.support import sandbox_fixture

    monkeypatch.setenv("WWISE_LIVE", "1"); monkeypatch.setenv("WWISE_DESTRUCTIVE", "1")
    workflow = importlib.import_module("tests.destructive.test_gateway_workflow_transaction_matrix")
    collector = importlib.import_module("tests.destructive.support.audio_import_acceptance")

    class Client(ImportFieldsClient):
        def __init__(self):
            super().__init__(tmp_path, "2025.1")
            self.parent = {"id": PARENT_ID, "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
                "path": r"\Containers\Default Work Unit", "notes": "keep placement", "parent": None}
            self.objects = {PARENT_ID: self.parent}
            self.tab_count = self.import_count = 0
            self.bus_work_unit = {"id": "{A74EEB4A-0805-4AFA-969C-53DCB862B550}", "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
                "path": r"\Busses\Default Work Unit", "notes": "", "parent": None}
            self.objects[self.bus_work_unit["id"]] = self.bus_work_unit
            self.bus = {"id": "{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}", "name": "Main Audio Bus", "type": "Bus", "classId": 524304,
                "path": r"\Busses\Default Work Unit\Main Audio Bus", "notes": "keep bus", "parent": {"id": self.bus_work_unit["id"]}}
            # The retained r2 public children reply and committed baseline
            # contain all four Buses. Put the selected Main Bus last so taking
            # the first valid Bus cannot pass this public-flow control.
            for identity, name in (
                ("{D2E0BC7E-7B3F-4FFE-A670-FAE02761B631}", "Secondary Bus"),
                ("{8DD26D7F-389D-4487-B09F-5C675BF2E8D9}", "WAAPI_V2_Weapons"),
                ("{EF9E9851-4728-4F6C-9939-2C84CF0367A3}", "WAAPI_V2_Footsteps"),
            ):
                self.objects[identity] = {**self.bus, "id": identity, "name": name,
                    "path": "\\Busses\\Default Work Unit\\" + name}
            if fault != "missing-bus":
                self.objects[self.bus["id"]] = self.bus
            if fault == "wrong-bus-parent":
                self.bus["parent"] = {"id": PARENT_ID}
        def projected(self, rows, options):
            result = []
            for raw in rows:
                if raw["type"] == "AudioFileSource" and options.get("language") and raw["audioSource:language"]["name"] != options["language"]:
                    continue
                row = copy.deepcopy(raw)
                if row["type"] == "Sound":
                    children = [source for source in self.objects.values() if (source.get("parent") or {}).get("id") == row["id"]
                        and source.get("audioSource:language", {}).get("name") == options.get("language", "English(US)" if row.get("@IsVoice") else "SFX")]
                    if children:
                        row.update(activeSource={"id": children[0]["id"]}, originalFilePath=children[0]["originalFilePath"],
                            **{"sound:originalWavFilePath": children[0]["originalFilePath"], "audioSource:language": children[0]["audioSource:language"]})
                result.append({key: row.get(key, row.get("@" + key)) for key in options["return"] if key in row or "@" + key in row})
            return result
        def ingest(self, row, language):
            explicit_source = "<AudioFileSource>" in row["objectPath"]
            path = re.sub(r"<[^>]+>", "", row["objectPath"])
            source_name = path.rsplit("\\", 1)[-1] if explicit_source else None
            if explicit_source: path = path.rsplit("\\", 1)[0]
            owner = next((item for item in self.objects.values() if item["path"] == path and item["type"] != "AudioFileSource"), None)
            if owner is None:
                parent_path, _, name = path.rpartition("\\")
                parent = next(item for item in self.objects.values() if item["path"] == parent_path)
                kind = row.get("objectType", "")
                sound = "sound" in kind.casefold()
                owner = {"id": "{" + str(uuid.uuid4()).upper() + "}", "name": name,
                    "type": "Sound" if sound else "PropertyContainer", "classId": 65552 if sound else 1,
                    "path": path, "parent": {"id": parent["id"]}, "notes": ""}
                if sound: owner["@IsVoice"] = "voice" in kind.casefold()
                self.objects[owner["id"]] = owner
            for name in ("Volume", "OutputBus", "OverrideOutput"):
                if "@" + name in row:
                    owner["@" + name] = {"id": row["@" + name]} if name == "OutputBus" else row["@" + name]
            if owner["type"] == "Sound":
                owner.setdefault("@Volume", 0.0); owner.setdefault("@OutputBus", None); owner.setdefault("@OverrideOutput", False)
            if "notes" in row and not explicit_source and "audioFile" not in row and "audioFileBase64" not in row:
                owner["notes"] = row["notes"]
            returned = [owner]
            if "audioFile" in row or "audioFileBase64" in row:
                import base64
                relative, _, encoded = row.get("audioFileBase64", "").partition("|")
                media = Path(row["audioFile"]) if "audioFile" in row else Path(relative.replace("\\", "/"))
                data = media.read_bytes() if "audioFile" in row else base64.b64decode(encoded)
                source_name = source_name or media.stem
                source = next((item for item in self.objects.values() if (item.get("parent") or {}).get("id") == owner["id"]
                    and item["type"] == "AudioFileSource" and item["name"] == source_name
                    and item["audioSource:language"]["name"] == language), None)
                copied = tmp_path / "project/Originals" / ("SFX" if language == "SFX" else "Voices/" + language)
                copied = (copied / row.get("originalsSubFolder", "") / media.name if "audioFile" in row
                    else tmp_path / "project/Originals" / media)
                copied.parent.mkdir(parents=True, exist_ok=True); copied.write_bytes(data)
                if source is None:
                    source = {"id": "{" + str(uuid.uuid4()).upper() + "}", "name": source_name,
                        "type": "AudioFileSource", "classId": 16, "path": path + "\\" + source_name,
                        "notes": "", "parent": {"id": owner["id"]},
                        "audioSource:language": {"id": ENGLISH if language == "English(US)" else JAPANESE if language == "Japanese" else SFX, "name": language}}
                    self.objects[source["id"]] = source
                source["originalFilePath"] = str(copied)
                if explicit_source and "notes" in row: source["notes"] = row["notes"]
                returned.append(source)
            return returned
        def call(self, uri, args=None, options=None):
            args, options = args or {}, options or {}
            if uri.endswith("getInfo"):
                info = super().call(uri, args, options)
                info["version"].update(minor=7, build=9143, displayName="v2025.1.7.9143")
                if witness_kind == "explicit-source-tsv" and os.name == "posix":
                    info.update(processPath=r"C:\Wwise\WwiseConsole.exe", platform="x64")
                return info
            if uri.endswith("getTypes"):
                return {"return": [{"classId": n, "name": name, "type": "WObject"} for n, name in (
                    (1, "PropertyContainer"), (65552, "Sound"), (16, "AudioFileSource"), (1638416, "WorkUnit"), (524304, "Bus"))]}
            if uri.endswith("getPropertyAndReferenceNames"): return {"return": ["IsVoice", "Volume", "OutputBus", "OverrideOutput"]}
            if uri.endswith("getPropertyInfo"):
                if args["property"] == "Volume":
                    return {"name": "Volume", "type": "Real64", "restriction": {"type": "range", "min": -200, "max": 200}}
                dependency = {"type": "override", "action": "Enable", "context": "Self", "property": "OverrideOutput"}
                if args["property"] == "OutputBus":
                    return {"name": "OutputBus", "type": "", "restriction": {"type": "reference", "restrictions": [{"type": ["Audio Bus"], "sharedOnlyTypes": []}, "notNull"]},
                        "dependencies": [dependency]}
                if args["property"] == "OverrideOutput":
                    return {"name": "OverrideOutput", "type": "bool", "default": False, "dependencies": [dependency]}
                return {"name": "IsVoice", "type": "bool", "default": False, "dependencies": []}
            if uri.endswith("getProjectInfo"):
                info = super().call(uri, args, options)
                if witness_kind == "explicit-source-tsv" and os.name == "posix":
                    from tests.unit.test_transaction_gateway import z_wire_path
                    info["path"] = z_wire_path(tmp_path / "project/SampleProject.wproj")
                info["languages"].extend([{"id": ENGLISH, "name": "English(US)", "shortId": 2}, {"id": JAPANESE, "name": "Japanese", "shortId": 3}])
                return info
            if uri.endswith("object.get") and not args.get("waql", "").startswith("from type Project"):
                rows = []
                if "waql" in args:
                    match = re.match(r'from object ("(?:[^"\\]|\\.)*")(.*)', args["waql"])
                    assert match, args
                    identity, tail = match[1][1:-1], match[2]
                    rows = [item for item in self.objects.values() if item["id"] == identity or item["path"] == identity]
                    if "select children" in tail:
                        owners = {item["id"] for item in rows}
                        rows = [item for item in self.objects.values() if isinstance(item.get("parent"), dict) and item["parent"].get("id") in owners]
                    if fault == "partial-post-read" and self.tab_count and rows and rows[0]["name"] == "VoiceSource" and "select children" not in tail:
                        rows = []
                elif "from" in args:
                    identities = args["from"]
                    rows = [item for item in self.objects.values() if item["id"] in identities.get("id", []) or item["path"] in identities.get("path", [])]
                    if args.get("transform"):
                        owners = {item["id"] for item in rows}
                        rows = [item for item in self.objects.values() if isinstance(item.get("parent"), dict) and item["parent"].get("id") in owners]
                self.calls.append((uri, copy.deepcopy(args), copy.deepcopy(options)))
                projected = self.projected(rows, options)
                if fault == "missing-field" and (self.tab_count or self.import_count == 3) and "waql" in args:
                    target = "VoiceSource" if witness_kind == "ordinary-owner-source" else "VoiceNotes"
                    for row in projected:
                        if row.get("type") == "Sound" and row.get("name") == target: row.pop("notes", None)
                return {"return": projected}
            if uri == "ak.wwise.core.audio.import":
                self.calls.append((uri, copy.deepcopy(args), copy.deepcopy(options)))
                self.import_count += 1
                if witness_kind == "ordinary-owner-source" and self.import_count == 3 and fault == "indeterminate":
                    raise RuntimeError("fake native transport lost after dispatch")
                returned = []
                for row in args["imports"]: returned.extend(self.ingest(row, row.get("importLanguage", "SFX")))
                returned = list({row["id"]: row for row in returned}.values())
                if witness_kind == "ordinary-owner-source" and self.import_count == 3 and fault == "wrong-identity":
                    source = next(row for row in returned if row["type"] == "AudioFileSource")
                    source["parent"] = {"id": PARENT_ID}
                return {"objects": self.projected(returned, options), "log": [],
                    "files": [item["originalFilePath"] for item in returned if item["type"] == "AudioFileSource"]}
            if uri == "ak.wwise.core.audio.importTabDelimited":
                import csv
                self.calls.append((uri, copy.deepcopy(args), copy.deepcopy(options))); self.tab_count += 1
                if fault == "indeterminate": raise RuntimeError("fake native transport lost after dispatch")
                from wwise_waapi.host_paths import localize_waapi_host_path
                with Path(localize_waapi_host_path(args["importFile"])).open(encoding="utf-8", newline="") as source:
                    rows = list(csv.DictReader(source, delimiter="\t"))
                returned = []
                for row in rows:
                    object_path = row["Object Path"]
                    if not object_path.startswith("\\"):
                        object_path = self.objects[args["importLocation"]]["path"] + "\\" + object_path
                    native = {"objectPath": object_path, "notes": row.get("Notes", "")}
                    if row.get("Audio File"):
                        if witness_kind == "explicit-source-tsv":
                            assert not row["Audio File"].startswith("/"), "Wine cannot consume a POSIX absolute media cell"
                        native["audioFile"] = localize_waapi_host_path(row["Audio File"])
                    if row.get("OriginalsSubFolder"): native["originalsSubFolder"] = row["OriginalsSubFolder"]
                    objects = self.ingest(native, "English(US)")
                    owner = objects[0]; source = objects[-1] if len(objects) > 1 else None
                    if row.get("Notes") and source is not None and "<AudioFileSource>" not in object_path:
                        (source if fault == "notes-on-source" else owner)["notes"] = row["Notes"]
                    if row.get("Audio Source Notes") and source is not None: source["notes"] = row["Audio Source Notes"]
                    if fault == "wrong-identity" and source is not None:
                        self.objects.pop(source["id"]); source["id"] = "{" + str(uuid.uuid4()).upper() + "}"; self.objects[source["id"]] = source
                    returned.extend(objects)
                returned = list({row["id"]: row for row in returned}.values())
                return {"objects": self.projected(returned, options)}
            if uri.startswith("ak.wwise.core.undo."): return {}
            return super().call(uri, args, options)

    PARENT_ID = "{11111111-1111-1111-1111-111111111111}"
    ENGLISH = "{88888888-8888-8888-8888-888888888888}"
    JAPANESE = "{99999999-9999-9999-9999-999999999999}"
    SFX = "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"
    client = Client()
    state = tmp_path / "state"
    env = {**_env(tmp_path)}
    config = Path(env["WAAPI_SKILL_CONFIG_PATH"])
    settings = json.loads(config.read_text()); settings["wwise_version"] = "2025.1"; config.write_text(json.dumps(settings))
    raw = lambda argv: waapi_gateway.execute_gateway(["--state-dir", str(state), *argv], env=env, client_factory=lambda _: client)
    source_root = tmp_path / "immutable-source"; source_root.mkdir()
    source_file = source_root / "SampleProject.wproj"; source_file.write_text("immutable source")
    proof = sandbox_fixture.hash_project(source_root)
    metadata = sandbox_fixture.SandboxMetadata(str(source_file), str(source_root), str(tmp_path / "project"),
        str(tmp_path / "project/SampleProject.wproj"), "2025.1", 0, proof, sandbox_fixture.hash_project(tmp_path / "project"),
        source_file.stat().st_mtime, process_cleanup_result="cleaned", process_cleanup_details={"residual_processes": []})
    metadata.get_info_version = {"year": 2025, "major": 1, "minor": 7, "build": 9143}
    sandbox = sandbox_fixture.SandboxProject(source_file, source_root, tmp_path, tmp_path / "project", tmp_path / "project/SampleProject.wproj", metadata)
    runtime = SimpleNamespace(version="2025.1", candidate=workflow.exact_git_candidate(workflow.REPO_ROOT), sandbox=sandbox,
        state_dir=state, env=env, category_results=[], raw_gateway=raw,
        lifecycle=SimpleNamespace(host="127.0.0.1", waapi_url="ws://127.0.0.1:31337/waapi"), port=31337)
    lock = sandbox_fixture.LiveSandboxLock(tmp_path / "locks"); lock.__enter__()
    node = {"notes-columns": "test_audio_import_localized_exact_tsv_independent_notes",
        "ordinary-owner-source": "test_audio_import_new_localized_source_owner_fields",
        "explicit-source-tsv": "test_audio_import_exact_tsv_owner_notes_existing_source_media"}[witness_kind]
    error = None
    try: getattr(workflow, node)(runtime)
    except AssertionError as exc: error = exc
    assert (error is None) == (fault is None), error
    category, = runtime.category_results
    body = Path(category["observation_path"]).read_bytes(); report = json.loads(body)
    final = _finish((workflow, runtime, client, lock, proof), tmp_path, monkeypatch, [(node, error)])[-1]
    assert final["categories"][0]["observation_sha256"] == hashlib.sha256(body).hexdigest()
    assert final["invocation"]["outcome"] == ("PASS" if fault is None else "FAIL")
    assert report["business_effect_verified"] is (fault is None)
    assert report["transaction_budget"] == {"setup": 2, "witness": 1, "maximum_total": 3}
    if witness_kind == "ordinary-owner-source":
        assert all("Master-Mixer Hierarchy" not in json.dumps(call) and "Master Audio Bus" not in json.dumps(call)
            for call in report["calls"])
        assert any(call["argv"][:3] == ["query-object", "--path-segment", "Busses"] for call in report["calls"])
        if fault in {"missing-bus", "wrong-bus-parent"}:
            assert len(final["transactions"]) == client.import_count == 2
            assert all(phase["verify"]["state"] == "verified" for phase in report["setup"])
            assert not report["witness"] and not report["observations"].get("after")
            assert final["residual_state"]["sandbox"] == "quarantined"
            return
        assert report["bus_before"]["id"] == client.bus["id"]
        assert any(call["argv"][0] == "draft-bind-object" and "--object-id" in call["argv"]
            and client.bus["id"] in call["argv"] for call in report["calls"])
    if witness_kind != "notes-columns":
        assert len(final["transactions"]) == 3
        assert final["residual_state"]["sandbox"] == ("deleted" if fault is None else "quarantined")
        witness = report["witness"]
        if fault == "indeterminate":
            assert witness["execute"]["state"] == "indeterminate"
            assert report["calls"][-1]["argv"] == ["execute", witness["transaction_id"]]
            assert not report["observations"].get("after")
        else:
            assert len(witness["actual_verifications"]) == 1 and witness["actual_verifications"][0]["readbacks"]
            assert report["observations"]["after"]["Spare"] == report["observations"]["before"]["Spare"]
            if fault == "missing-field":
                assert report["observation_errors"]
            if fault == "wrong-identity":
                assert witness["verify_exit_code"] == 2
        if witness_kind == "ordinary-owner-source":
            assert client.import_count == 3 and client.tab_count == 0
            assert "table" not in report
        else:
            assert client.import_count == 2 and client.tab_count == 1
            assert "Audio Source Notes" not in report["table"]["utf8"]
            cells = [line.split("\t") for line in report["table"]["utf8"].splitlines()]
            assert cells[1][0] == "" and cells[1][2] == "TSV requested object Notes"
            assert cells[2][1].endswith("<AudioFileSource>LineNotes") and cells[2][2] == "TSV requested source Notes"
            if fault != "indeterminate": assert report["table_after"]["sha256"] == report["table"]["sha256"]
        return
    table_bytes = report["table"]["utf8"].encode("utf-8")
    assert hashlib.sha256(table_bytes).hexdigest() == report["table"]["sha256"]
    cells = [line.split("\t") for line in report["table"]["utf8"].splitlines()]
    assert cells[1][2:4] == ["TSV requested object Notes", ""]
    assert cells[2][2:4] == ["", "TSV requested source Notes"]
    assert client.tab_count == 1
    assert len(final["transactions"]) == 3
    witness = report["witness"]
    if fault == "indeterminate":
        assert witness["execute"]["state"] == "indeterminate"
        assert not report["observations"].get("after")
        index = next(i for i, row in enumerate(report["calls"]) if row["argv"] == ["execute", witness["transaction_id"]])
        assert index == len(report["calls"]) - 1
    else:
        assert {row["name"] for row in report["rows"]} == {"VoiceNotes", "VoiceSource"}
        after = report["observations"]["after"]
        assert report["table_after"]["sha256"] == report["table"]["sha256"]
        if fault == "partial-post-read":
            assert report["observation_errors"] and "owner" not in after["VoiceSource"]
            assert after["VoiceSource"]["sources"]
            assert after["VoiceNotes"]["owner"] and after["VoiceNotes"]["sources"]
        else:
            assert all("owner" in row and "sources" in row for row in after.values())
        assert len(witness["actual_verifications"]) == 1 and witness["actual_verifications"][0]["readbacks"]
        if fault == "notes-on-source":
            actual = report["observations"]["after"]["VoiceNotes"]
            assert actual["owner"]["notes"] == ""
            assert next(item["object"]["notes"] for item in actual["sources"] if item["object"]["source_language"]["name"] == "English(US)") == "TSV requested object Notes"
            assert witness["verify_exit_code"] == 2
