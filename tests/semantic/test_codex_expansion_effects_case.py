from copy import deepcopy

import pytest
from pathlib import Path

from tests.semantic.support.codex_expansion_effects_case import (
    C09_ASSERTIONS, approve_c09_preview, prepare_c09, verify_c09,
)
from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError
from tests.unit.test_object_graph_business_gateway import gateway as public_gateway


OWNER = "{11111111-1111-1111-1111-111111111111}"


def _entry(slot, effect, name):
    return {"slot": slot, "slot_state": {"id": slot, "type": "EffectSlot", "owner": {"id": OWNER}, "@Effect": {"id": effect}},
            "effect": {"id": effect, "type": "Effect", "classId": 123,
                       "name": name, "notes": "preserved", "owner": {"id": slot}}}


def _baseline():
    return {"owner": {"id": OWNER, "@Volume": -3}, "slot_order": ["slot-a", "slot-b"], "entries": [
        _entry("slot-a", "effect-a", "Old A"), _entry("slot-b", "effect-b", "Old B"),
    ]}


def test_effect_append_oracle_accepts_equivalent_read_order_but_not_swapped_bindings():
    before = _baseline()
    after = deepcopy(before)
    added = _entry("slot-c", "effect-c", "New Gain")
    added["effect"]["notes"] = "requested"
    after["entries"] = [after["entries"][1], added, after["entries"][0]]
    after["slot_order"].append("slot-c")
    result = verify_c09(before, after, version="2025.1", expected_class_id=123, expected_name="New Gain", expected_notes="requested")
    assert set(result) == C09_ASSERTIONS
    assert all(result.values())
    after["entries"][0]["effect"]["id"] = "effect-a"
    assert not all(verify_c09(before, after, version="2025.1", expected_class_id=123,
                              expected_name="New Gain", expected_notes="requested").values())


@pytest.mark.parametrize("damage", ("extra", "missing", "old_notes", "new_class", "new_owner", "owner_volume"))
def test_effect_append_rejects_collateral_and_extra_changes(damage):
    before = _baseline()
    after = deepcopy(before)
    added = _entry("slot-c", "effect-c", "New Gain")
    added["effect"]["notes"] = "requested"
    after["entries"].append(added)
    after["slot_order"].append(added["slot"])
    if damage == "extra":
        after["entries"].append(_entry("slot-d", "effect-d", "Extra"))
    elif damage == "missing":
        del after["entries"][0]
    elif damage == "old_notes":
        after["entries"][0]["effect"]["notes"] = "changed"
    elif damage == "new_class":
        added["effect"]["classId"] = 999
    elif damage == "new_owner":
        added["effect"]["owner"]["id"] = "another-owner"
    else:
        after["owner"]["@Volume"] = -12
    assert not all(verify_c09(before, after, version="2025.1", expected_class_id=123,
                              expected_name="New Gain", expected_notes="requested").values())


def test_effect_preview_allows_only_the_owned_named_plugin_append():
    artifact = {"request": {"operation": "object.createPlugin", "version": "2025.1", "arguments": {
        "target": {"kind": "id", "value": OWNER},
        "plugin": {"kind": "effect", "name": "New Gain", "class_id": 123, "notes": "requested"},
    }}}
    kwargs = {"version": "2025.1", "owner_id": OWNER, "class_id": 123,
              "name": "New Gain", "notes": "requested"}
    assert approve_c09_preview(artifact, **kwargs)
    for key, value in (("properties", [{"name": "Gain", "value": -9}]),
                       ("platform", "Windows"), ("kind", "source"), ("class_id", 999)):
        changed = deepcopy(artifact)
        changed["request"]["arguments"]["plugin"][key] = value
        assert not approve_c09_preview(changed, **kwargs)


def test_effect_oracle_is_required_before_any_fixture_change(tmp_path: Path):
    calls = []
    ctx = ExpansionCaseContext("2025.1", "C09", tmp_path / "Fixture.wproj", tmp_path / "assets",
                               lambda argv: calls.append(argv))
    with pytest.raises(CaseBoundaryError, match="before any setup"):
        prepare_c09(ctx)
    assert calls == []


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_effect_setup_cli_parses_and_snapshot_checks_independent_bindings(version, tmp_path):
    """Parse real CLI argv; fake replies exercise orchestration, not live setup."""
    calls = []
    starts = []
    parser = public_gateway.build_parser()
    plugins = ["{22222222-2222-2222-2222-222222222222}", "{33333333-3333-3333-3333-333333333333}"]
    slots = ["{44444444-4444-4444-4444-444444444444}", "{55555555-5555-5555-5555-555555555555}"]
    owner = {"id": OWNER, "name": "Owner", "type": "Sound", "path": r"\Owner",
             "parent": {"id": "{66666666-6666-6666-6666-666666666666}"}, "@Volume": -3, "notes": ""}
    plugin_rows = {
        plugin_id: {"id": plugin_id, "name": f"Protected_Gain_{index}", "type": "Effect", "path": rf"\Gain{index}",
                    "owner": {"id": OWNER if version == "2022.1" else slots[index]}, "classId": 123, "notes": f"protected effect {index}"}
        for index, plugin_id in enumerate(plugins)
    }
    def gateway(argv):
        parser.parse_args(argv)
        calls.append(tuple(argv))
        command = argv[0]
        if command == "draft-start":
            starts.append(argv[1])
            return {"draft": {"draft_id": str(len(starts)), "revision": 1}, "task_authority": "authority"}
        if command == "query-object":
            return {"ok": True, "status": "ok", "objects": [owner], "count": 1,
                    "query_bound": {"mode": "take", "value": 2}}
        if command == "draft-bind-object":
            return {"bound_object": {"handle": "bound-owner"}, "draft": {"revision": 2}}
        if command == "draft-discover-types":
            return {"type_candidates": [{"handle": "discovered-gain"}], "draft": {"revision": 3}}
        if command == "preview-from-draft":
            return {"transaction_id": "transaction"}
        if command == "transaction-show":
            return {"confirmation": {"token": "visible-confirmation"}}
        if command == "execute":
            return {"state": "executed_unverified"}
        if command == "verify":
            return {"state": "verified", "verification": {"business_state_verified": True}}
        assert command in {"draft-declare-new", "draft-declare-existing", "draft-check", "confirm"}, argv
        return {"draft": {"revision": 4}}
    reverse_reads = True
    def read(view, ids):
        if view == "effect_owner":
            if version == "2022.1":
                return [{**owner, **{f"@Effect{index}": {"id": plugins[index]} if index < 2 else None
                                     for index in range(4)}}]
            return [{**owner, "@Effects": [{"id": slot} for slot in slots]}]
        if view == "effect_slot":
            return [{"id": slot, "name": "", "type": "EffectSlot", "path": rf"\Slot{index}",
                     "owner": {"id": OWNER}, "@Effect": {"id": plugins[index]}}
                    for index, slot in (reversed(list(enumerate(slots))) if reverse_reads else enumerate(slots))]
        assert view == "effect_plugin"
        return [deepcopy(plugin_rows[identifier]) for identifier in reversed(ids)]
    ctx = ExpansionCaseContext(version, "C09", tmp_path / "Fixture.wproj", tmp_path / "assets", gateway, read)
    case = prepare_c09(ctx)
    assert starts == ["object.create", "object.createPlugin", "object.createPlugin"]
    assert case.policy == "allow_changes" and case.operation == "object.createPlugin"
    assert len(case.before["entries"]) == 2
    assert case.before["slot_order"] == (["0", "1"] if version == "2022.1" else slots)
    reverse_reads = False
    assert case.snapshot() == case.before
    declarations = [call for call in calls if call[0] == "draft-declare-existing"]
    assert all("discovered-gain" in call and "protected effect" in " ".join(call) for call in declarations)
    assert len([call for call in calls if call[0] == "confirm"]) == 3
    plugin_rows[plugins[0]].pop("owner")
    with pytest.raises(CaseBoundaryError, match="incomplete"):
        case.snapshot()


@pytest.mark.parametrize("damage", ("slot_owner", "slot_identity", "slot_effect", "plugin_owner"))
def test_effect_append_requires_the_exact_2025_three_link_ownership_chain(damage):
    before = _baseline()
    after = deepcopy(before)
    added = _entry("slot-c", "effect-c", "New Gain")
    added["effect"]["notes"] = "requested"
    after["entries"].append(added)
    after["slot_order"].append(added["slot"])
    if damage == "slot_owner":
        added["slot_state"]["owner"]["id"] = "other-sound"
    elif damage == "slot_identity":
        added["slot_state"]["id"] = "slot-d"
    elif damage == "slot_effect":
        added["slot_state"]["@Effect"]["id"] = "other-effect"
    else:
        added["effect"]["owner"]["id"] = OWNER
    result = verify_c09(before, after, version="2025.1", expected_class_id=123,
                        expected_name="New Gain", expected_notes="requested")
    assert not result["new_effect_owned_by_target"]


def test_effect_append_preserves_the_2022_direct_owner_layout():
    before = _baseline()
    for index, entry in enumerate(before["entries"]):
        entry.update(slot=str(index), slot_state=None)
        entry["effect"]["owner"]["id"] = OWNER
    before["slot_order"] = ["0", "1"]
    after = deepcopy(before)
    added = _entry("2", "effect-c", "New Gain")
    added["slot_state"] = None
    added["effect"].update(owner={"id": OWNER}, notes="requested")
    after["entries"].append(added)
    after["slot_order"].append(added["slot"])
    assert all(verify_c09(before, after, version="2022.1", expected_class_id=123,
                          expected_name="New Gain", expected_notes="requested").values())
    assert not all(verify_c09(before, after, version="2025.1", expected_class_id=123,
                              expected_name="New Gain", expected_notes="requested").values())


@pytest.mark.parametrize("slot_order", (["slot-b", "slot-c", "slot-a"],
                                        ["slot-c", "slot-a", "slot-b"]))
def test_effect_append_rejects_reordered_or_front_inserted_owner_chain(slot_order):
    before = _baseline()
    after = deepcopy(before)
    added = _entry("slot-c", "effect-c", "New Gain")
    added["effect"]["notes"] = "requested"
    after["entries"].append(added)
    after["slot_order"] = slot_order
    assert not all(verify_c09(before, after, version="2025.1", expected_class_id=123,
                              expected_name="New Gain", expected_notes="requested").values())
