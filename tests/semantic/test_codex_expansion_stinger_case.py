from copy import deepcopy
from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, ExpectedCapabilityBoundary
from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError
from tests.semantic.support.codex_expansion_stinger_case import (
    STINGER, TARGET, OWNER, BONUS, SEGMENT, PROTECTED_STINGER, PROTECTED_OWNER,
    approve_m05_preview, prepare_m05, verify_m05,
)


def test_stinger_verification_requires_exact_trigger_and_preserves_segment_and_other_rules():
    before = _live_shaped_snapshot()
    sibling = deepcopy(before["stinger"])
    sibling["id"] = "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}"
    before["siblings"].append(sibling)
    before["owner"]["@Stingers"].append({"id": sibling["id"]})
    after = deepcopy(before)
    after["stinger"].update({"@Trigger": {"id": TARGET}, "name": "new display", "path": "[New trigger]"})
    after["siblings"][0] = deepcopy(after["stinger"])
    after["siblings"].reverse()
    assert all(verify_m05(before, after, version="2025.1", target_id=TARGET).values())
    after["stinger"]["@Segment"] = {"id": TARGET}
    assert not verify_m05(before, after, version="2025.1", target_id=TARGET)["segment_reference_preserved"]
    after["siblings"].pop()
    assert not verify_m05(before, after, version="2025.1", target_id=TARGET)["other_stingers_preserved"]


def test_stinger_rejects_unrequested_timing_change():
    before = _live_shaped_snapshot()
    after = deepcopy(before)
    after["stinger"].update({"@Trigger": {"id": TARGET}, "@PlaySegmentAt": 4})
    after["siblings"] = [deepcopy(after["stinger"])]
    assert not verify_m05(before, after, version="2025.1", target_id=TARGET)["stinger_identity_and_other_configuration_preserved"]


def test_stinger_requires_real_protected_witness():
    before = _live_shaped_snapshot()
    after = deepcopy(before)
    after["stinger"]["@Trigger"] = {"id": TARGET}
    after["siblings"] = [deepcopy(after["stinger"])]
    before.pop("protected")
    assert not verify_m05(before, after, version="2025.1", target_id=TARGET)["other_stingers_preserved"]


def test_stinger_preview_rejects_other_targets_or_additional_changes():
    artifact = {"request": {"operation": "object.setReference", "version": "2025.1", "arguments": {
        "object": {"kind": "id", "value": STINGER}, "reference": "Trigger",
        "target": {"kind": "id", "value": TARGET},
    }}}
    assert approve_m05_preview(artifact, version="2025.1")
    changed = deepcopy(artifact)
    changed["request"]["arguments"]["reference"] = "Segment"
    assert not approve_m05_preview(changed, version="2025.1")
    changed = deepcopy(artifact)
    changed["request"]["arguments"]["target"]["value"] = STINGER
    assert not approve_m05_preview(changed, version="2025.1")
    changed = deepcopy(artifact)
    changed["request"]["arguments"]["notes"] = "unrequested"
    assert not approve_m05_preview(changed, version="2025.1")


def test_2022_stinger_boundary_is_positive_read_evidence_without_agent_or_mutation():
    calls = []
    identity = {"id": STINGER, "name": "", "type": "MusicStinger", "path": "[Stinger]"}
    def gateway(argv):
        calls.append(tuple(argv))
        assert argv[0] == "query-object"
        if "--include-field" in argv:
            return {"ok": True, "status": "needs_clarification", "agent_result": {"unresolved": [
                {"meaning": "Trigger", "candidate_names": []},
                {"meaning": "Segment", "candidate_names": ["PlaySegmentAt"]},
            ]}}
        return {"ok": True, "status": "ok", "count": 1, "query_bound": {"mode": "exact-object"},
                "objects": [identity]}
    ctx = ExpansionCaseContext("2022.1", "M05", Path("/owned/Fixture.wproj"), Path("/owned/assets"), gateway)
    with pytest.raises(ExpectedCapabilityBoundary) as caught:
        prepare_m05(ctx)
    assert caught.value.evidence["agent_executed"] is False
    assert caught.value.evidence["business_effect_verified"] is False
    assert len(calls) == 3


def _live_shaped_snapshot():
    def stinger(identifier):
        return {"id": identifier, "name": "", "type": "MusicStinger", "notes": "",
                "path": "[Stinger : Bonus,Stinger Bonus]", "@Trigger": {"id": BONUS, "name": "Bonus"},
                "@Segment": {"id": SEGMENT, "name": "Stinger Bonus"},
                "@NumSegmentAdvance": 1, "@PlaySegmentAt": 3}
    target = stinger(STINGER)
    return {"stinger": target, "siblings": [deepcopy(target)],
            "owner": {"id": OWNER, "type": "MusicPlaylistContainer", "@Stingers": [{"id": STINGER}]},
            "target": {"id": TARGET, "name": "Backup_Team_Arrives", "type": "Trigger"},
            "segment": {"id": SEGMENT, "type": "MusicSegment"},
            "protected": {"stinger": stinger(PROTECTED_STINGER), "owner": {
                "id": PROTECTED_OWNER, "type": "MusicPlaylistContainer", "@Stingers": [{"id": PROTECTED_STINGER}]}}}


def _prepare_from_snapshot(snapshot):
    calls = []
    def read(view, ids):
        calls.append((view, tuple(ids)))
        rows = {STINGER: snapshot["stinger"], OWNER: snapshot["owner"], TARGET: snapshot["target"],
                SEGMENT: snapshot["segment"], PROTECTED_STINGER: snapshot["protected"]["stinger"],
                PROTECTED_OWNER: snapshot["protected"]["owner"]}
        if view == "music_stinger" and STINGER in ids:
            return deepcopy(snapshot["siblings"])
        return [deepcopy(rows[identifier]) for identifier in ids]
    ctx = ExpansionCaseContext("2025.1", "M05", Path("/owned/Fixture.wproj"), Path("/owned/assets"),
                               lambda _: pytest.fail("fixture needs no project writes"), read)
    return prepare_m05(ctx), calls


def test_stinger_setup_proves_owner_membership_without_inventing_parent():
    before = _live_shaped_snapshot()
    case, calls = _prepare_from_snapshot(before)
    assert case.before == before
    assert case.snapshot() == before
    assert "parent" not in case.before["stinger"]
    assert ("music_stinger_owner", (OWNER,)) in calls
    after = deepcopy(before)
    after["stinger"].update({"@Trigger": {"id": TARGET}, "path": "[New display]", "name": "new"})
    after["siblings"] = [deepcopy(after["stinger"])]
    assert all(case.verify(before, after).values())
    assert all(verify_m05(before, after, **case.archive_oracle_parameters).values())


@pytest.mark.parametrize("damage", ("missing_member", "duplicate_member", "other_owner", "extra_sibling", "wrong_sibling", "protected_owner", "protected_duplicate", "timing_bool", "notes_missing"))
def test_stinger_setup_rejects_unproven_membership_or_configuration(damage):
    before = _live_shaped_snapshot()
    if damage == "missing_member":
        before["owner"]["@Stingers"] = []
    elif damage == "duplicate_member":
        before["owner"]["@Stingers"].append({"id": STINGER})
    elif damage == "other_owner":
        before["owner"]["id"] = PROTECTED_OWNER
    elif damage == "extra_sibling":
        before["siblings"].append(deepcopy(before["protected"]["stinger"]))
    elif damage == "wrong_sibling":
        before["siblings"] = [deepcopy(before["protected"]["stinger"])]
    elif damage == "protected_owner":
        before["protected"]["owner"]["id"] = OWNER
    elif damage == "protected_duplicate":
        before["protected"]["owner"]["@Stingers"].append({"id": PROTECTED_STINGER})
    elif damage == "timing_bool":
        before["stinger"]["@PlaySegmentAt"] = True
        before["siblings"] = [deepcopy(before["stinger"])]
    else:
        before["stinger"].pop("notes")
        before["siblings"] = [deepcopy(before["stinger"])]
    with pytest.raises(CaseBoundaryError):
        _prepare_from_snapshot(before)


@pytest.mark.parametrize("damage", ("owner_member", "owner_identity", "slot_duplicate", "protected", "timing", "notes"))
def test_stinger_verifier_rejects_ownership_or_preservation_changes(damage):
    before = _live_shaped_snapshot()
    after = deepcopy(before)
    after["stinger"]["@Trigger"] = {"id": TARGET}
    after["siblings"] = [deepcopy(after["stinger"])]
    if damage == "owner_member":
        after["owner"]["@Stingers"] = [{"id": PROTECTED_STINGER}]
    elif damage == "owner_identity":
        after["owner"]["id"] = PROTECTED_OWNER
    elif damage == "slot_duplicate":
        after["owner"]["@Stingers"].append({"id": STINGER})
    elif damage == "protected":
        after["protected"]["stinger"]["@Trigger"] = {"id": TARGET}
    elif damage == "timing":
        after["stinger"]["@NumSegmentAdvance"] = 2
        after["siblings"] = [deepcopy(after["stinger"])]
    else:
        after["stinger"]["notes"] = "unrequested"
        after["siblings"] = [deepcopy(after["stinger"])]
    assert not all(verify_m05(before, after, version="2025.1", target_id=TARGET).values())


def test_stinger_accepts_reordered_protected_owner_membership_without_changing_fields():
    before = _live_shaped_snapshot()
    before["protected"]["owner"]["@Stingers"].append({"id": "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}"})
    before["protected"]["owner"]["notes"] = "preserved owner notes"
    after = deepcopy(before)
    after["stinger"]["@Trigger"] = {"id": TARGET}
    after["siblings"] = [deepcopy(after["stinger"])]
    after["protected"]["owner"]["@Stingers"].reverse()
    assert all(verify_m05(before, after, version="2025.1", target_id=TARGET).values())
    after["protected"]["owner"]["notes"] = "changed owner notes"
    assert not verify_m05(before, after, version="2025.1", target_id=TARGET)["other_stingers_preserved"]


@pytest.mark.parametrize("damage", ("missing", "extra", "duplicate"))
def test_stinger_rejects_changed_protected_owner_membership(damage):
    before = _live_shaped_snapshot()
    before["protected"]["owner"]["@Stingers"].append({"id": "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}"})
    after = deepcopy(before)
    after["stinger"]["@Trigger"] = {"id": TARGET}
    after["siblings"] = [deepcopy(after["stinger"])]
    members = after["protected"]["owner"]["@Stingers"]
    if damage == "missing":
        members.pop()
    elif damage == "extra":
        members.append({"id": "{FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF}"})
    else:
        members.append({"id": PROTECTED_STINGER})
    assert not verify_m05(before, after, version="2025.1", target_id=TARGET)["other_stingers_preserved"]
