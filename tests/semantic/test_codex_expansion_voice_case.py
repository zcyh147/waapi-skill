from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError
from tests.semantic.support.codex_expansion_voice_case import (
    C01_ASSERTIONS, _create_english_event_voice, _voice_snapshot,
    approve_c01_preview, prepare_c01, verify_c01,
)


SOUND_PATH = r"\Containers\Default Work Unit\Voice"
REPLACEMENT = Path("/fixture/replacement/C01_line.wav")


def _artifact():
    return {"request": {"version": "2025.1", "operation": "audio.import", "arguments": {
        "import_operation": "useExisting", "imports": [{
            "object_path": SOUND_PATH, "object_type": "Sound Voice", "import_language": "Japanese",
            "audio_file": str(REPLACEMENT),
        }],
    }}, "prepared_operation": {"verification_plan": {"kind": "closed-audio-import",
           "targets": [{"preexisting_id": "sound"}], "native_directive_boundaries": []}}}


def _approved(artifact):
    return approve_c01_preview(artifact, version="2025.1", sound_id="sound", sound_path=SOUND_PATH, replacement=REPLACEMENT)


def test_voice_preview_accepts_closed_equivalent_defaults() -> None:
    artifact = _artifact()
    assert _approved(artifact)
    args = artifact["request"]["arguments"]
    args["defaults"] = {"import_language": args["imports"][0].pop("import_language"),
                        "properties": [], "references": []}
    args["auto_add_to_source_control"] = False
    assert _approved(artifact)


@pytest.mark.parametrize("key,value", (
    ("object_path", SOUND_PATH + "_Backup"), ("import_language", "English(US)"),
    ("audio_file", "/fixture/wrong.wav"), ("notes", "unexpected edit"),
    ("properties", [{"name": "Volume", "value": 0}]),
    ("references", [{"name": "OutputBus", "target": "another"}]),
    ("event", {"path": "unrequested"}), ("object_type", "Sound SFX"),
))
def test_voice_preview_rejects_wrong_effect_or_scope(key, value) -> None:
    artifact = _artifact()
    artifact["request"]["arguments"]["imports"][0][key] = value
    assert not _approved(artifact)


def test_voice_preview_rejects_replacement_and_extra_target() -> None:
    artifact = _artifact()
    artifact["request"]["arguments"]["import_operation"] = "replaceExisting"
    assert not _approved(artifact)
    artifact = _artifact()
    artifact["request"]["arguments"]["imports"] *= 2
    assert not _approved(artifact)
    artifact = _artifact()
    artifact["prepared_operation"]["verification_plan"]["targets"][0]["preexisting_id"] = "other-at-same-path"
    assert not _approved(artifact)


def _before():
    def source(language, identity, digest):
        return {"object": {"id": identity, "name": "line", "path": "/line", "type": "AudioFileSource",
                           "parent": {"id": "sound"}, "source_language": {"name": language}},
                "media": {"path": f"/{language}/line.wav", "sha256": digest}, "volume_offset_db": 0}
    return {"sound": {"id": "sound", "volume_db": -3, "output_bus": {"id": "bus"}},
            "sources": {"Japanese": source("Japanese", "jp", "old"),
                        "English(US)": source("English(US)", "en", "english")},
            "event": {"id": "event"}, "actions": [{"id": "action", "target": {"id": "sound"}}],
            "distractor": {"id": "decoy", "volume_db": -9}, "members": ["sound", "decoy"]}


def test_voice_independent_oracle_requires_media_and_preservation() -> None:
    before = _before()
    after = deepcopy(before)
    after["sources"]["Japanese"]["media"]["sha256"] = "replacement"
    assertions = verify_c01(before, after, replacement_sha256="replacement")
    assert set(assertions) == C01_ASSERTIONS
    assert all(assertions.values())
    after["sources"]["Japanese"]["volume_offset_db"] = 2
    assert not verify_c01(before, after, replacement_sha256="replacement")["source_gain_unchanged"]
    after["sources"]["Japanese"]["volume_offset_db"] = 0
    after["sources"]["Japanese"]["object"]["id"] = "recreated-source"
    assert not verify_c01(before, after, replacement_sha256="replacement")["requested_language_source_identity_preserved"]
    after["sources"]["English(US)"]["media"]["sha256"] = "replacement"
    assert not verify_c01(before, after, replacement_sha256="replacement")["other_language_unchanged"]
    after["sound"]["volume_db"] = 0
    assert not verify_c01(before, after, replacement_sha256="replacement")["sound_identity_and_configuration_unchanged"]
    after["actions"][0]["target"] = {"id": "decoy"}
    assert not verify_c01(before, after, replacement_sha256="replacement")["event_and_action_unchanged"]


def test_voice_missing_prelaunch_language_blocks_before_any_gateway_mutation(tmp_path: Path) -> None:
    project = tmp_path / "Sample.wproj"
    project.write_text('<Project><LanguageList><Language Name="English(US)"/></LanguageList></Project>')
    calls = []
    ctx = ExpansionCaseContext("2025.1", "C01", project, tmp_path / "assets", lambda argv: calls.append(argv))
    with pytest.raises(CaseBoundaryError, match="before launch"):
        prepare_c01(ctx)
    assert calls == []


def test_english_event_import_and_volume_use_separate_verified_gateway_transactions(
    tmp_path: Path,
) -> None:
    parent_id = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    sound_id = "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"
    sound = {"id": sound_id, "type": "Sound", "name": "Line_01",
             "path": r"\Containers\Default Work Unit\Voices\Line_01",
             "parent": {"id": parent_id}, "notes": "", "volume_db": 0.0,
             "output_bus": None}
    calls: list[tuple[str, ...]] = []
    operations: dict[str, str] = {}
    revisions: dict[str, int] = {}

    def gateway(argv):
        call = tuple(argv)
        calls.append(call)
        command = argv[0]
        if command == "draft-start":
            draft_id = f"draft-{len(operations) + 1}"
            operations[draft_id] = argv[1]
            revisions[draft_id] = 1
            return {"draft": {"draft_id": draft_id, "revision": 1},
                    "task_authority": "task-authority"}
        if command == "draft-bind-object":
            result = {"draft": {"revision": revisions[argv[1]] + 1}}
            revisions[argv[1]] += 1
            if "--object-id" in argv:
                result["bound_object"] = {"handle": "boh-parent"}
            else:
                result["bound_object"] = {"handle": "boh-events"}
            return result
        if command == "draft-discover-fields":
            revisions[argv[1]] += 1
            return {"draft": {"revision": revisions[argv[1]]},
                    "meaning_results": [{"candidates": [{"handle": "bf-volume"}]}]}
        if command.startswith("draft-") or command == "preview-from-draft":
            draft_id = argv[1]
            revisions[draft_id] += 1
            result = {"draft": {"revision": revisions[draft_id]}}
            if command == "preview-from-draft":
                result["transaction_id"] = f"tx-{draft_id}"
            if command == "draft-declare-field-change":
                assert operations[draft_id] == "object.setProperty"
                assert argv[argv.index("--field-handle") + 1] == "bf-volume"
                assert argv[argv.index("--business-value") + 1] == "-3"
                sound["volume_db"] = -3.0
            return result
        if command == "transaction-show":
            return {"state": "awaiting_confirmation", "confirmation": {"token": "confirm"}}
        if command == "confirm":
            return {"state": "confirmed"}
        if command == "execute":
            return {"state": "executed_unverified"}
        if command == "verify":
            return {"state": "verified", "verification": {"business_state_verified": True}}
        if command == "query-object":
            if "--exact-id" in argv:
                assert argv[argv.index("--exact-id") + 1] == sound_id
            else:
                assert [argv[i + 1] for i, value in enumerate(argv[:-1])
                        if value == "--path-segment"] == [
                            "Containers", "Default Work Unit", "Voices", "Line_01",
                        ]
            return {"ok": True, "count": 1, "objects": [dict(sound)],
                    "query_bound": {"mode": "take", "value": 2}}
        raise AssertionError(call)

    media = tmp_path / "english" / "C01_line.wav"
    media.parent.mkdir()
    media.write_bytes(b"RIFF-english")
    ctx = ExpansionCaseContext("2025.1", "C01", tmp_path / "Sample.wproj",
                               tmp_path / "assets", gateway)
    prepared_sound = _create_english_event_voice(
        ctx, parent={"id": parent_id, "path": r"\Containers\Default Work Unit\Voices"},
        parent_segments=("Containers", "Default Work Unit", "Voices"),
        sound_name="Line_01", event_name="Expansion_C01_Play_Line_01", media=media,
    )

    import_calls = [call for call in calls if call[0] == "draft-declare-import-batch"]
    assert len(import_calls) == 1
    assert operations[import_calls[0][1]] == "audio.import"
    event_index = import_calls[0].index("--event")
    assert import_calls[0][event_index + 1:event_index + 5] == (
        "voice", "boh-events", "Expansion_C01_Play_Line_01", "Play",
    )
    import_fields = [import_calls[0][index + 1:index + 3]
                     for index, value in enumerate(import_calls[0][:-2]) if value == "--field"]
    assert ("voice", "language") in import_fields
    assert ("voice", "volume_db") not in import_fields
    field_change = next(call for call in calls if call[0] == "draft-declare-field-change")
    assert operations[field_change[1]] == "object.setProperty"
    discovery = next(call for call in calls if call[0] == "draft-discover-fields")
    assert discovery[discovery.index("--meaning") + 1] == "Volume"
    assert prepared_sound["volume_db"] == -3.0
    assert any(call[0] == "verify" and call[1] == f"tx-{field_change[1]}" for call in calls)
    exact_read = next(call for call in calls if call[0] == "query-object" and "--exact-id" in call)
    assert "--include" in exact_read and "volume-db" in exact_read


@pytest.mark.parametrize("fault", (
    None, "wrong-parent", "duplicate-language", "missing-file",
    "sound:volume_db", "sound:output_bus", "sound:notes", "sound:parent",
    "sound:type", "sound:path", "distractor:volume_db", "event:notes",
    "action:action_type", "action:notes", "source:notes", "invalid-volume", "invalid-bus",
    "missing-source-gain", "invalid-source-gain", "no-trusted-oracle",
))
def test_voice_snapshot_binds_language_media_and_event_edges(tmp_path: Path, fault: str | None) -> None:
    def guid(value):
        return "{00000000-0000-0000-0000-%012d}" % value
    sound, event, decoy, parent, action = [guid(index) for index in range(1, 6)]
    source_rows = []
    for index, language in enumerate(("English(US)", "Japanese"), 6):
        media = tmp_path / "Originals" / language / "line.wav"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"RIFF" + bytes([index]))
        source_rows.append({"id": guid(index), "type": "AudioFileSource", "name": "line",
                            "path": f"/Voice/{language}", "parent": {"id": sound},
                            "source_language": {"name": language}, "original_file_path": str(media), "notes": ""})
    action_row = {"id": action, "type": "Action", "name": "", "path": "/Event/Action",
                  "target": {"id": sound}, "parent": {"id": event}, "action_type": 1, "notes": ""}
    exact_rows = {
        identity: {"id": identity, "type": kind, "name": kind, "path": f"/{kind}",
                   "parent": {"id": parent}, "notes": ""}
        for identity, kind in ((sound, "Sound"), (decoy, "Sound"), (event, "Event"))
    }
    for identity in (sound, decoy):
        exact_rows[identity].update(volume_db=-3, output_bus=None)
    if fault and ":" in fault:
        target, key = fault.split(":")
        selected = {"sound": exact_rows[sound], "distractor": exact_rows[decoy],
                    "event": exact_rows[event], "action": action_row, "source": source_rows[0]}[target]
        del selected[key]
    elif fault == "invalid-volume":
        exact_rows[sound]["volume_db"] = True
    elif fault == "invalid-bus":
        exact_rows[sound]["output_bus"] = {}
    if fault == "wrong-parent":
        source_rows[1]["parent"] = {"id": decoy}
    elif fault == "duplicate-language":
        source_rows[1]["source_language"] = {"name": "English(US)"}
    elif fault == "missing-file":
        Path(source_rows[1]["original_file_path"]).unlink()

    def gateway(argv):
        object_id = argv[argv.index("--exact-id") + 1]
        if "--relationship" in argv:
            found = (source_rows if object_id == sound else
                     [action_row]
                     if object_id == event else [{"id": sound}, {"id": decoy}])
        else:
            found = [exact_rows[object_id]]
        return {"ok": True, "count": len(found), "objects": found,
                "query_bound": {"mode": "take", "value": int(argv[argv.index("--max-results") + 1])}}

    def trusted(view, ids):
        assert view == "audio_source"
        result = [{"id": identity, "@VolumeOffset": 0} for identity in ids]
        if fault == "missing-source-gain":
            result[0].pop("@VolumeOffset")
        elif fault == "invalid-source-gain":
            result[0]["@VolumeOffset"] = True
        return result

    ctx = ExpansionCaseContext("2025.1", "C01", tmp_path / "Sample.wproj", tmp_path / "assets", gateway,
                               None if fault == "no-trusted-oracle" else trusted)
    if fault:
        with pytest.raises(CaseBoundaryError):
            _voice_snapshot(ctx, sound_id=sound, event_id=event, decoy_id=decoy, parent_id=parent)
    else:
        snapshot = _voice_snapshot(ctx, sound_id=sound, event_id=event, decoy_id=decoy, parent_id=parent)
        assert set(snapshot["sources"]) == {"English(US)", "Japanese"}
        assert len({row["media"]["sha256"] for row in snapshot["sources"].values()}) == 2
        assert snapshot["actions"][0]["target"] == {"id": sound}
