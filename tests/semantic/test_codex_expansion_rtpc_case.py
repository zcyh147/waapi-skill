from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError
from tests.semantic.support.codex_expansion_rtpc_case import (
    C06_ASSERTIONS, TARGET_POINTS, _rtpc_snapshot, approve_c06_preview, prepare_c06, verify_c06,
)


OWNER = "{11111111-1111-1111-1111-111111111111}"
CONTROL = "{22222222-2222-2222-2222-222222222222}"
TARGET = "{33333333-3333-3333-3333-333333333333}"
SIBLING = "{44444444-4444-4444-4444-444444444444}"
SOURCE = "{55555555-5555-5555-5555-555555555555}"
SECOND_CONTROL = "{66666666-6666-6666-6666-666666666666}"


def _artifact():
    return {"request": {"operation": "object.setRTPC", "version": "2025.1", "arguments": {
        "object": {"kind": "id", "value": OWNER}, "control_input": {"kind": "id", "value": CONTROL},
        "property": "Volume", "points": list(TARGET_POINTS), "mode": "add_or_replace",
    }}, "prepared_operation": {"verification_plan": {
        "kind": "object-rtpc-state", "action": "update", "existing_rtpc_id": TARGET,
        "object_id": OWNER, "control_input_id": CONTROL,
    }}}


def _approved(artifact):
    return approve_c06_preview(artifact, version="2025.1", owner_id=OWNER,
                               control_id=CONTROL, target_id=TARGET, expected_notes="keep")


@pytest.mark.parametrize("key,value", (
    ("object", {"kind": "id", "value": SOURCE}),
    ("control_input", {"kind": "id", "value": SECOND_CONTROL}),
    ("property", "Pitch"), ("mode", "add"), ("notes", "changed"),
    ("points", [{"x": 0, "y": -20, "shape": "Linear"}]),
))
def test_rtpc_preview_rejects_wrong_target_values_and_add_only(key, value) -> None:
    artifact = _artifact()
    assert _approved(artifact)
    artifact["request"]["arguments"][key] = value
    assert not _approved(artifact)


def test_rtpc_preview_accepts_unchanged_explicit_notes_but_requires_existing_update() -> None:
    artifact = _artifact()
    artifact["request"]["arguments"]["notes"] = "keep"
    assert _approved(artifact)
    artifact["prepared_operation"]["verification_plan"]["action"] = "add"
    assert not _approved(artifact)
    artifact["prepared_operation"]["verification_plan"]["action"] = "update"
    artifact["prepared_operation"]["verification_plan"]["existing_rtpc_id"] = SIBLING
    assert not _approved(artifact)
    artifact = deepcopy(_artifact())
    artifact["request"]["arguments"]["points"][0]["x"] = False
    assert not _approved(artifact)


def _before():
    target = {"id": TARGET, "type": "RTPC", "name": "", "path": "[RTPC: Volume]", "notes": "keep",
              "@PropertyName": "Volume", "@ControlInput": {"id": CONTROL},
              "@Curve": {"points": [{"x": 0, "y": -12, "shape": "Linear"}]}}
    sibling = {**deepcopy(target), "id": SIBLING, "@PropertyName": "Pitch",
               "@ControlInput": {"id": SECOND_CONTROL}}
    return {"owner": {"id": OWNER, "name": "Bed", "type": "Sound", "path": "/Bed",
                      "parent": {"id": SOURCE}, "notes": "", "@Volume": -3, "@OutputBus": None},
            "rtpcs": {TARGET: target, SIBLING: sibling},
            "media": {"sha256": "unchanged"}, "controls": [{"id": CONTROL}, {"id": SECOND_CONTROL}]}


def test_rtpc_oracle_requires_real_update_and_unchanged_sibling() -> None:
    before = _before()
    after = deepcopy(before)
    after["rtpcs"][TARGET]["@Curve"]["points"] = list(TARGET_POINTS)
    assertions = verify_c06(before, after, target_id=TARGET)
    assert set(assertions) == C06_ASSERTIONS
    assert all(assertions.values())
    after["rtpcs"][SIBLING]["notes"] = "corrupted"
    assert not verify_c06(before, after, target_id=TARGET)["sibling_curves_unchanged"]
    after["rtpcs"][SOURCE] = after["rtpcs"].pop(TARGET)
    assert not verify_c06(before, after, target_id=TARGET)["rtpc_identity_set_unchanged"]
    assert not verify_c06(before, after, target_id=TARGET)["target_curve_matches"]


@pytest.mark.parametrize("fault", (
    None, "owner:@Volume", "owner:@OutputBus", "owner:notes", "owner:parent",
    "owner:type", "owner:name", "owner:path", "invalid-volume", "invalid-bus",
    "rtpc:notes", "rtpc:name", "control:notes", "control:parent", "control:type",
    "source:source_language", "source:original_file_path", "invalid-point",
))
def test_rtpc_snapshot_reads_full_list_through_fixed_runner_view(tmp_path: Path, fault: str | None) -> None:
    originals = tmp_path / "Originals"
    originals.mkdir()
    media = originals / "bed.wav"
    media.write_bytes(b"RIFF-fixed")
    state = _before()
    source = {"id": SOURCE, "type": "AudioFileSource", "name": "bed", "path": "/Bed/bed",
              "source_language": {"name": "SFX"}, "original_file_path": str(media), "parent": {"id": OWNER}}
    controls = {identity: {"id": identity, "type": "GameParameter", "name": "Rain", "path": "/Rain",
                          "notes": "", "parent": {"id": SOURCE}} for identity in (CONTROL, SECOND_CONTROL)}
    if fault and ":" in fault:
        target, key = fault.split(":")
        selected = {"owner": state["owner"], "rtpc": state["rtpcs"][TARGET],
                    "control": controls[CONTROL], "source": source}[target]
        del selected[key]
    elif fault == "invalid-volume":
        state["owner"]["@Volume"] = True
    elif fault == "invalid-bus":
        state["owner"]["@OutputBus"] = {}
    elif fault == "invalid-point":
        state["rtpcs"][TARGET]["@Curve"]["points"] = [{"x": False, "y": 0, "shape": "Linear"}]
    reads = []
    def trusted(view, ids):
        reads.append((view, tuple(ids)))
        if view == "rtpc_owner":
            return [{**state["owner"], "@RTPC": [{"id": TARGET}, {"id": SIBLING}]}]
        assert view == "rtpc"
        return [state["rtpcs"][item] for item in ids]
    def gateway(argv):
        object_id = argv[argv.index("--exact-id") + 1]
        row = source if "--relationship" in argv else controls[object_id]
        return {"ok": True, "count": 1, "objects": [row], "query_bound": {"mode": "take", "value": 8}}
    ctx = ExpansionCaseContext("2025.1", "C06", tmp_path / "Sample.wproj", tmp_path / "assets", gateway, trusted)
    if fault:
        with pytest.raises(CaseBoundaryError):
            _rtpc_snapshot(ctx, OWNER, (CONTROL, SECOND_CONTROL))
        return
    snapshot = _rtpc_snapshot(ctx, OWNER, (CONTROL, SECOND_CONTROL))
    assert set(snapshot["rtpcs"]) == {TARGET, SIBLING}
    assert reads == [("rtpc_owner", (OWNER,)), ("rtpc", (TARGET, SIBLING))]
    assert "@RTPC" not in snapshot["owner"]


def test_rtpc_case_blocks_before_setup_without_trusted_oracle(tmp_path: Path) -> None:
    calls = []
    ctx = ExpansionCaseContext("2025.1", "C06", tmp_path / "Sample.wproj", tmp_path / "assets", lambda argv: calls.append(argv))
    with pytest.raises(CaseBoundaryError, match="trusted oracle"):
        prepare_c06(ctx)
    assert calls == []
