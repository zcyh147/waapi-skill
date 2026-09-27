from copy import deepcopy
from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, ExpectedCapabilityBoundary
from tests.semantic.support.codex_expansion_stinger_case import (
    STINGER, TARGET, approve_m05_preview, prepare_m05, verify_m05,
)


def test_stinger_verification_requires_exact_trigger_and_preserves_segment_and_other_rules():
    before = {"stinger": {"id": "s", "@Trigger": {"id": "old"}, "@Segment": {"id": "segment"}},
              "target": {"id": "new"}, "segment": {"id": "segment"},
              "siblings": [{"id": "s"}, {"id": "other"}],
              "protected": {"stinger": {"id": "protected", "@PlaySegmentAt": 3}}}
    after = deepcopy(before)
    after["stinger"]["@Trigger"] = {"id": "new"}
    before["stinger"].update(name="old display", path="[Old trigger]")
    after["stinger"].update(name="new display", path="[New trigger]")
    after["siblings"].reverse()
    assert all(verify_m05(before, after, target_id="new").values())
    after["stinger"]["@Segment"] = {"id": "wrong"}
    assert not verify_m05(before, after, target_id="new")["segment_reference_preserved"]
    after["siblings"].pop()
    assert not verify_m05(before, after, target_id="new")["other_stingers_preserved"]


def test_stinger_rejects_unrequested_timing_change():
    before = {"stinger": {"id": "s", "@Trigger": {"id": "old"},
                           "@Segment": {"id": "segment"}, "@PlaySegmentAt": 3}, "siblings": []}
    after = deepcopy(before)
    after["stinger"]["@Trigger"] = {"id": "new"}
    after["stinger"]["@PlaySegmentAt"] = 4
    assert not verify_m05(before, after, target_id="new")["stinger_identity_and_other_configuration_preserved"]


def test_stinger_requires_real_protected_witness():
    before = {"stinger": {"id": "s", "@Segment": {"id": "segment"}}, "siblings": []}
    after = deepcopy(before)
    after["stinger"]["@Trigger"] = {"id": "new"}
    assert not verify_m05(before, after, target_id="new")["other_stingers_preserved"]


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
