from __future__ import annotations

import copy
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
            self.tab_count = 0
        def projected(self, rows, options):
            result = []
            for raw in rows:
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
            path = re.sub(r"<[^>]+>", "", row["objectPath"])
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
            returned = [owner]
            if "audioFile" in row:
                media = Path(row["audioFile"])
                source = next((item for item in self.objects.values() if (item.get("parent") or {}).get("id") == owner["id"]
                    and item["type"] == "AudioFileSource" and item["name"] == media.stem
                    and item["audioSource:language"]["name"] == language), None)
                copied = tmp_path / "project/Originals" / ("SFX" if language == "SFX" else "Voices/" + language)
                copied = copied / row.get("originalsSubFolder", "") / media.name
                copied.parent.mkdir(parents=True, exist_ok=True); copied.write_bytes(media.read_bytes())
                if source is None:
                    source = {"id": "{" + str(uuid.uuid4()).upper() + "}", "name": media.stem,
                        "type": "AudioFileSource", "classId": 16, "path": path + "\\" + media.stem,
                        "notes": "", "parent": {"id": owner["id"]},
                        "audioSource:language": {"id": ENGLISH if language == "English(US)" else JAPANESE if language == "Japanese" else SFX, "name": language}}
                    self.objects[source["id"]] = source
                source["originalFilePath"] = str(copied)
                returned.append(source)
            return returned
        def call(self, uri, args=None, options=None):
            args, options = args or {}, options or {}
            if uri.endswith("getInfo"):
                info = super().call(uri, args, options)
                info["version"].update(minor=7, build=9143, displayName="v2025.1.7.9143")
                return info
            if uri.endswith("getTypes"):
                return {"return": [{"classId": n, "name": name, "type": "WObject"} for n, name in (
                    (1, "PropertyContainer"), (65552, "Sound"), (16, "AudioFileSource"), (1638416, "WorkUnit"))]}
            if uri.endswith("getPropertyAndReferenceNames"): return {"return": ["IsVoice"]}
            if uri.endswith("getPropertyInfo"): return {"name": "IsVoice", "type": "bool", "default": False, "dependencies": []}
            if uri.endswith("getProjectInfo"):
                info = super().call(uri, args, options)
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
                return {"return": self.projected(rows, options)}
            if uri == "ak.wwise.core.audio.import":
                self.calls.append((uri, copy.deepcopy(args), copy.deepcopy(options)))
                returned = []
                for row in args["imports"]: returned.extend(self.ingest(row, row.get("importLanguage", "SFX")))
                return {"objects": self.projected(returned, options), "log": [],
                    "files": [item["originalFilePath"] for item in returned if item["type"] == "AudioFileSource"]}
            if uri == "ak.wwise.core.audio.importTabDelimited":
                import csv
                self.calls.append((uri, copy.deepcopy(args), copy.deepcopy(options))); self.tab_count += 1
                if fault == "indeterminate": raise RuntimeError("fake native transport lost after dispatch")
                with Path(args["importFile"]).open(encoding="utf-8", newline="") as source:
                    rows = list(csv.DictReader(source, delimiter="\t"))
                returned = []
                for row in rows:
                    object_path = row["Object Path"]
                    if not object_path.startswith("\\"):
                        object_path = self.objects[args["importLocation"]]["path"] + "\\" + object_path
                    owner, source = self.ingest({"objectPath": object_path, "audioFile": row["Audio File"],
                        "originalsSubFolder": row["OriginalsSubFolder"]}, "English(US)")
                    if row["Notes"]: (source if fault == "notes-on-source" else owner)["notes"] = row["Notes"]
                    if row["Audio Source Notes"]: source["notes"] = row["Audio Source Notes"]
                    returned.extend([owner, source])
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
    node = "test_audio_import_localized_exact_tsv_independent_notes"
    error = None
    try: collector.collect_localized_tsv_import_acceptance(runtime)
    except AssertionError as exc: error = exc
    assert (error is None) == (fault is None), error
    category, = runtime.category_results
    body = Path(category["observation_path"]).read_bytes(); report = json.loads(body)
    final = _finish((workflow, runtime, client, lock, proof), tmp_path, monkeypatch, [(node, error)])[-1]
    assert final["categories"][0]["observation_sha256"] == hashlib.sha256(body).hexdigest()
    assert final["invocation"]["outcome"] == ("PASS" if fault is None else "FAIL")
    assert report["business_effect_verified"] is (fault is None)
    assert report["transaction_budget"] == {"setup": 2, "witness": 1, "maximum_total": 3}
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
