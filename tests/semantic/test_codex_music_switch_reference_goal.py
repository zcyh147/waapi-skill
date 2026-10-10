from copy import deepcopy

import pytest

from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError
from tests.semantic.support.codex_music_switch_reference_goal import (
    ENTRY, FIGHT, approve_music_switch_reference_preview, music_switch_reference_snapshot, run_music_switch_reference_goal,
    append_bounded_goal_receipt, verify_music_switch_reference_goal,
)


def test_preview_approves_only_the_exact_existing_reference_change():
    artifact = {"request": {"operation": "object.setReference", "version": "2025.1",
        "arguments": {"object": {"kind": "id", "value": ENTRY}, "reference": "AudioNode",
                      "target": {"kind": "id", "value": FIGHT}}}}
    assert approve_music_switch_reference_preview(artifact)
    for key, value in (("reference", "OutputBus"), ("extra", True),
                       ("object", {"kind": "path", "value": "display"})):
        wrong = deepcopy(artifact)
        wrong["request"]["arguments"][key] = value
        assert not approve_music_switch_reference_preview(wrong)


def _snapshots():
    from pathlib import Path
    from tests.semantic.support.codex_music_oracle_probes import xml_music_witness
    root = Path(__file__).resolve().parents[2]
    witness = xml_music_witness(root / "tests/_org/2025.1/Containers/Music/Music.wwu", "2025.1")
    switch = witness["music_switch"]
    before = {"owner": {"id": switch["owner"]}, "argument_slots": switch["argument_slots"],
        "entry_ids": [row["entry_id"] for row in switch["mappings"]], "entries": {},
        "arguments": dict(zip(switch["argument_slots"], switch["groups"])),
        "paths": {}, "conditions": {}, "protected_contents": [{"id": "protected"}],
        "media": {"audio.wav": {"sha256": "a" * 64}}, "wwu_sha256": witness["wwu_sha256"]}
    for row in switch["mappings"]:
        before["entries"][row["entry_id"]] = {"id": row["entry_id"], "type": "MultiSwitchEntry",
            "properties": {"Probability": 100, "Weight": 50},
            "references": {"AudioNode": {"id": row["target"]}}}
        before["paths"][row["entry_id"]] = row["slots"]
        before["conditions"].update(dict(zip(row["slots"], row["conditions"])))
    after = deepcopy(before)
    after["entries"][ENTRY]["references"]["AudioNode"] = {"id": FIGHT}
    return witness, before, after


def test_reference_effect_and_full_preservation_are_checked_without_order_authority_claim():
    witness, before, after = _snapshots()
    checks = verify_music_switch_reference_goal(before, after, witness)
    assert checks and all(value is True for value in checks.values())


@pytest.mark.parametrize("damage", ("condition", "weight", "sibling", "media", "contents", "missing", "duplicate", "wrong", "argument_position", "condition_position"))
def test_independent_oracle_rejects_unrequested_changes(damage):
    witness, before, after = _snapshots()
    if damage == "condition":
        after["conditions"][next(iter(after["conditions"]))] = FIGHT
    elif damage == "weight":
        after["entries"][ENTRY]["properties"]["Weight"] = 10
    elif damage == "sibling":
        sibling = witness["music_switch"]["mappings"][0]["entry_id"]
        after["entries"][sibling]["references"]["AudioNode"] = {"id": FIGHT}
    elif damage == "media":
        after["media"]["audio.wav"]["sha256"] = "b" * 64
    elif damage == "contents":
        after["protected_contents"] = []
    elif damage == "missing":
        after["entry_ids"].pop()
    elif damage == "duplicate":
        after["entry_ids"][-1] = after["entry_ids"][0]
    elif damage == "wrong":
        after["entry_ids"][-1] = FIGHT
    elif damage == "argument_position":
        after["argument_slots"].reverse()
    else:
        after["paths"][ENTRY].reverse()
    assert not all(verify_music_switch_reference_goal(before, after, witness).values())


@pytest.mark.parametrize("different_after", (False, True))
def test_unordered_entry_read_permutations_preserve_keyed_mapping_proof(different_after):
    witness, before, after = _snapshots()
    before["entry_ids"].reverse()
    after["entry_ids"] = (before["entry_ids"][3:] + before["entry_ids"][:3]
                          if different_after else list(before["entry_ids"]))
    assert all(verify_music_switch_reference_goal(before, after, witness).values())


@pytest.mark.parametrize("existing_receipts", (0, 2))
def test_receipt_overflow_retains_only_bounded_descriptor_in_failure_evidence(existing_receipts):
    import json
    receipts = []
    category = {"category": "reference-goal", "status": "FAIL", "gateway_receipts": receipts}
    for _ in range(existing_receipts):
        append_bounded_goal_receipt(receipts, ["query-schema"], 0, {"text": "x" * 140}, max_total_bytes=1024)
    payload = {"ok": True, "text": "x" * 2000}
    with pytest.raises(CaseBoundaryError, match="ceiling"):
        append_bounded_goal_receipt(receipts, ["query-schema"], 0, payload, max_total_bytes=1024)
    assert len(json.dumps(category).encode()) <= 1024
    assert receipts[-1]["error"] == "goal_receipt_overflow"
    assert receipts[-1]["payload_sha256"] and receipts[-1]["payload_bytes"] >= 2000
    assert "payload" not in receipts[-1] and "text" not in json.dumps(receipts[-1])


@pytest.mark.parametrize("aggregate_overflow", (False, True))
def test_actual_receipt_ceilings_leave_serializable_bounded_failure_evidence(aggregate_overflow):
    import json
    receipts = []
    category = {"category": "reference-goal", "status": "FAIL", "gateway_receipts": receipts}
    if aggregate_overflow:
        payload = {"text": "x" * (1_048_576 - 4096)}
        for _ in range(8):
            append_bounded_goal_receipt(receipts, ["query-object"], 0, payload)
    else:
        payload = {"text": "x" * 1_048_576}
    with pytest.raises(CaseBoundaryError, match="ceiling"):
        append_bounded_goal_receipt(receipts, ["query-object"], 0, payload)
    assert len(json.dumps([category], ensure_ascii=False).encode("utf-8")) <= 8 * 1_048_576
    assert receipts[-1]["error"] == "goal_receipt_overflow"
    assert "payload" not in receipts[-1]


@pytest.mark.parametrize("wrong_preview", (False, True))
@pytest.mark.parametrize("permuted_reads", (False, True))
def test_public_draft_goal_approves_before_one_execute_or_stops_on_wrong_preview(wrong_preview, permuted_reads):
    from pathlib import Path
    from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
    from tests.semantic.support.codex_expansion_policy import canonical_digest

    witness, before, after = _snapshots()
    calls = []
    revision = 1
    bindings = 0
    artifact = {"request": {"operation": "object.setReference", "version": "2025.1",
        "arguments": {"object": {"kind": "id", "value": ENTRY}, "reference": "Wrong" if wrong_preview else "AudioNode",
                      "target": {"kind": "id", "value": FIGHT}}}}
    def gateway(argv):
        nonlocal revision, bindings
        calls.append(tuple(argv))
        command = argv[0]
        if command == "operation-schema":
            return {"ok": True}
        if command == "draft-start":
            return {"draft": {"draft_id": "od1-goal", "revision": revision}, "task_authority": "authority"}
        if command.startswith("draft-") or command == "preview-from-draft":
            revision += 1
            payload = {"draft": {"revision": revision}}
            if command == "draft-bind-object":
                bindings += 1
                payload["bound_object"] = {"handle": f"boh1-{bindings}"}
            elif command == "draft-discover-fields":
                assert argv[argv.index("--meaning") + 1] == "AudioNode"
                payload["meaning_results"] = [{"candidates": [{"handle": "bf1-audio-node"}]}]
            elif command == "preview-from-draft":
                payload["transaction_id"] = "tx1-goal"
            return payload
        if command == "transaction-show":
            return {"transaction_id": "tx1-goal", "artifact": artifact, "artifact_hash": canonical_digest(artifact),
                    "state": "awaiting_confirmation", "confirmation": {"token": "ct1-goal"}}
        if command == "confirm":
            return {"state": "confirmed"}
        if command == "execute":
            return {"state": "executed_unverified", "transaction_id": "tx1-goal", "artifact_hash": canonical_digest(artifact)}
        if command == "verify":
            return {"state": "verified", "transaction_id": "tx1-goal", "artifact_hash": canonical_digest(artifact),
                    "verification": {"business_state_verified": True}}
        pytest.fail(f"unexpected command: {argv}")
    preview_baseline = deepcopy(before)
    if permuted_reads:
        preview_baseline["entry_ids"].reverse()
        after["entry_ids"] = after["entry_ids"][3:] + after["entry_ids"][:3]
    snapshots = iter((before, preview_baseline, after))
    ctx = ExpansionCaseContext("2025.1", "MUSIC_REFERENCE_GOAL", Path("/fixture/Sample.wproj"), Path("/fixture/assets"), gateway)
    if wrong_preview:
        with pytest.raises(CaseBoundaryError, match="Preview"):
            run_music_switch_reference_goal(ctx, witness, lambda: next(snapshots))
        assert not any(argv[0] in {"confirm", "execute", "verify"} for argv in calls)
    else:
        result = run_music_switch_reference_goal(ctx, witness, lambda: next(snapshots))
        assert sum(argv[0] == "execute" for argv in calls) == 1
        assert result["selected_reference_effect_verified"] is True
        assert result["complete_workflow_verified"] is False and result["business_effect_verified"] is False
        assert result["agent_pass"] is False and result["order_is_authoritative"] is False
        declaration = next(argv for argv in calls if argv[0] == "draft-declare-field-change")
        assert declaration[-6:] == ("--object-handle", "boh1-1", "--field-handle", "bf1-audio-node", "--target-handle", "boh1-2")


def test_public_snapshot_reads_complete_wrappers_and_hashes_only_owned_media(tmp_path):
    from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
    from tests.semantic.support.codex_music_oracle_probes import SWITCH

    witness, baseline, _ = _snapshots()
    media = tmp_path / "protected.wav"
    media.write_bytes(b"owned-source-media")
    source_id = "{FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF}"
    calls = []
    def gateway(argv):
        calls.append(tuple(argv))
        if argv[0] == "query-schema":
            return {"ok": True}
        if "--advanced-waql" in argv:
            expression = argv[argv.index("--advanced-waql") + 1]
            if expression.endswith("@Arguments"):
                identifiers = baseline["argument_slots"]
            elif expression.endswith("@Entries"):
                identifiers = baseline["entry_ids"]
            else:
                identifier = expression.split('"')[1]
                identifiers = baseline["paths"][identifier]
            rows = [{"id": value} for value in identifiers]
            bound = {"mode": "gateway-appended-take", "value": int(argv[-1])}
        elif "--relationship" in argv:
            rows = [{"id": source_id, "name": "protected", "type": "AudioFileSource",
                     "path": r"\Protected", "original_file_path": str(media)}]
            bound = {"mode": "take", "value": 1000}
        else:
            identifier = argv[argv.index("--exact-id") + 1]
            if identifier in baseline["entries"]:
                row = baseline["entries"][identifier]
            elif identifier in baseline["arguments"]:
                row = {"id": identifier, "references": {"Argument": {"id": baseline["arguments"][identifier]}}}
            elif identifier in baseline["conditions"]:
                row = {"id": identifier, "references": {"EntryPathObject": {"id": baseline["conditions"][identifier]}}}
            else:
                assert identifier in {SWITCH, FIGHT}
                row = {"id": identifier}
            rows = [row]
            bound = {"mode": "exact-object"}
        return {"ok": True, "status": "ok", "count": len(rows), "objects": rows, "query_bound": bound}
    ctx = ExpansionCaseContext("2025.1", "REFERENCE", tmp_path / "Sample.wproj", tmp_path / "assets", gateway)
    result = music_switch_reference_snapshot(ctx, witness, lambda: witness)
    assert len(result["entries"]) == 9 and len(result["conditions"]) == 18 and len(result["arguments"]) == 2
    assert result["media"][str(media)]["sha256"]
    assert all(argv[0] in {"query-schema", "query-object"} for argv in calls)


def _owned_music_fixture(tmp_path):
    from pathlib import Path
    import shutil
    from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
    source = Path(__file__).resolve().parents[2] / 'tests/_org/2025.1'
    owned = tmp_path / 'owned'
    shutil.copytree(source, owned)
    ctx = ExpansionCaseContext('2025.1', 'REFERENCE', owned / 'SampleProject.wproj', owned / 'assets',
                              lambda _: pytest.fail('media preparation cannot call Gateway'))
    return source, owned, ctx


def test_missing_legacy_music_is_seeded_before_actual_hash_preservation(tmp_path):
    import hashlib
    from tests.semantic.support.codex_expansion_case_helpers import file_evidence
    from tests.semantic.support.codex_music_switch_reference_goal import prepare_music_switch_reference_media
    source, owned, ctx = _owned_music_fixture(tmp_path)
    wwu = owned / 'Containers/Music/Music.wwu'
    before_xml = wwu.read_bytes()
    missing = owned / 'Originals/SFX/Music/Michael McCann and Tim Rideout/MenuMusic_Lp_01.wav'
    assert not missing.exists()
    with pytest.raises(CaseBoundaryError):
        file_evidence(ctx, str(missing))
    report = prepare_music_switch_reference_media(ctx, wwu, source / 'SampleProject.wproj')
    import json
    from tests.semantic.support.codex_music_switch_reference_goal import MEDIA_PREPARATION_REPORT_BYTES
    assert len(json.dumps(report, ensure_ascii=False).encode('utf-8')) <= MEDIA_PREPARATION_REPORT_BYTES
    assert report['source_object_count'] == 70
    assert len(report['files']) == report['created_count'] == 67
    assert len({row['path'] for row in report['files']}) == 67
    assert file_evidence(ctx, str(missing))['sha256'] == report['donor']['sha256']
    assert report['source_wwu_sha256'] == hashlib.sha256(before_xml).hexdigest()
    assert wwu.read_bytes() == (source / 'Containers/Music/Music.wwu').read_bytes() == before_xml
    assert not (source / 'Originals/SFX/Music').exists()
    missing.write_bytes(b'changed-after-independent-before')
    assert file_evidence(ctx, str(missing))['sha256'] != report['donor']['sha256']


def test_media_preparation_preserves_existing_input_without_overwrite(tmp_path):
    from tests.semantic.support.codex_music_switch_reference_goal import prepare_music_switch_reference_media
    source, owned, ctx = _owned_music_fixture(tmp_path)
    existing = owned / 'Originals/SFX/Music/Michael McCann and Tim Rideout/MenuMusic_Lp_01.wav'
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b'already-owned-input')
    report = prepare_music_switch_reference_media(ctx, owned / 'Containers/Music/Music.wwu', source / 'SampleProject.wproj')
    assert existing.read_bytes() == b'already-owned-input'
    assert report['created_count'] == 66
    assert sum(row['created'] is False for row in report['files']) == 1


@pytest.mark.parametrize('damage', ('traversal', 'absolute', 'duplicate_id', 'entity', 'too_many',
                                    'case_alias', 'symlink', 'reparse', 'donor_drift', 'source_root'))
def test_media_preparation_fails_closed_before_any_seed(damage, tmp_path, monkeypatch):
    import shutil
    from pathlib import Path
    from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
    from tests.semantic.support import codex_music_switch_reference_goal as goal
    fixed = Path(__file__).resolve().parents[2] / 'tests/_org/2025.1'
    source, owned = tmp_path / 'source', tmp_path / 'owned'
    shutil.copytree(fixed, source)
    wwu = source / 'Containers/Music/Music.wwu'
    raw = wwu.read_bytes()
    original = b'Music\\Michael McCann and Tim Rideout\\MenuMusic_Lp_01.wav'
    if damage in {'traversal', 'absolute'}:
        raw = raw.replace(original, b'..\\escape.wav' if damage == 'traversal' else b'/escape.wav')
    elif damage in {'duplicate_id', 'case_alias', 'too_many'}:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(raw)
        switch = next(node for node in root.iter('MusicSwitchContainer') if node.get('ID') == goal.SWITCH)
        nodes = list(switch.iter('AudioFileSource'))
        if damage == 'duplicate_id':
            nodes[1].set('ID', nodes[0].get('ID'))
        elif damage == 'case_alias':
            nodes[1].find('AudioFile').text = nodes[0].findtext('AudioFile').lower()
        else:
            from copy import deepcopy
            for _ in range(60):
                switch.append(deepcopy(nodes[0]))
        raw = ET.tostring(root)
    elif damage == 'entity':
        raw = b'<!DOCTYPE WwiseDocument [<!ENTITY external SYSTEM "file:///forbidden">]>' + raw
    wwu.write_bytes(raw)
    shutil.copytree(source, owned)
    ctx = ExpansionCaseContext('2025.1', 'REFERENCE', owned / 'SampleProject.wproj', owned / 'assets',
                              lambda _: pytest.fail('preparation cannot call Gateway'))
    music = owned / 'Originals/SFX/Music'
    if damage == 'symlink':
        music.symlink_to(tmp_path, target_is_directory=True)
    elif damage == 'reparse':
        original_check = goal.path_is_link_or_reparse
        monkeypatch.setattr(goal, 'path_is_link_or_reparse',
            lambda path: True if path == music else original_check(path))
    elif damage == 'donor_drift':
        (owned / goal.MEDIA_DONOR).write_bytes(b'drifted')
    elif damage == 'source_root':
        ctx = ExpansionCaseContext('2025.1', 'REFERENCE', source / 'SampleProject.wproj', source / 'assets', ctx.gateway)
    with pytest.raises(CaseBoundaryError):
        goal.prepare_music_switch_reference_media(ctx, ctx.project_path.parent / 'Containers/Music/Music.wwu',
                                                 source / 'SampleProject.wproj')
    if damage == 'symlink':
        assert music.is_symlink()
    else:
        assert not list(owned.glob('Originals/SFX/Music/**/*.wav'))


def test_partial_fixture_copy_evidence_survives_later_failure(tmp_path, monkeypatch):
    from tests.semantic.support import codex_music_switch_reference_goal as goal
    source, owned, ctx = _owned_music_fixture(tmp_path)
    original = goal.read_bounded_exclusive_regular_file
    evidence = {}
    def fail_second_created_read(path, **kwargs):
        if path.name == 'Stealth_Ambient_AmbientMelody1_Seg1_01.wav' and path.exists():
            raise CaseBoundaryError('injected fixture read failure')
        return original(path, **kwargs)
    monkeypatch.setattr(goal, 'read_bounded_exclusive_regular_file', fail_second_created_read)
    with pytest.raises(CaseBoundaryError, match='injected'):
        goal.prepare_music_switch_reference_media(ctx, owned / 'Containers/Music/Music.wwu',
                                                 source / 'SampleProject.wproj', evidence=evidence)
    assert evidence['donor']['sha256'] == goal.MEDIA_DONOR_SHA256
    assert evidence['created_count'] == 2
    assert len(evidence['files']) == 2 and evidence['files'][0]['verified'] is True
    assert evidence['files'][1]['created'] is True and evidence['files'][1]['verified'] is False
    assert evidence['files'][1]['sha256'] is None
