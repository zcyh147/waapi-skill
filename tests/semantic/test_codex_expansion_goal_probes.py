from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext, PreparedExpansionCase
from tests.semantic.support.codex_expansion_case_helpers import BusinessDraft, CaseBoundaryError
from tests.semantic.support.codex_expansion_goal_probes import (
    build_goal_draft,
    review_approve_execute_verify,
    run_goal_probe,
)


PARENT = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
OWNER = "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"
CONTROL = "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"
TARGET = "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}"
SIBLING = "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}"


def _draft_gateway():
    calls = []
    revisions = {}

    def gateway(argv):
        call = tuple(argv)
        calls.append(call)
        command = argv[0]
        if command == "draft-start":
            revisions["od1-probe"] = 1
            return {"draft": {"draft_id": "od1-probe", "revision": 1},
                    "task_authority": "authority"}
        draft_id = argv[1]
        if command == "draft-bind-object":
            revisions[draft_id] += 1
            return {"draft": {"revision": revisions[draft_id]},
                    "bound_object": {"handle": "boh1-parent"}}
        if command == "draft-discover-fields":
            revisions[draft_id] += 1
            return {"draft": {"revision": revisions[draft_id]},
                    "meaning_results": [{"candidates": [{"handle": "bf1-volume"}]}]}
        if command.startswith("draft-"):
            revisions[draft_id] += 1
            return {"draft": {"revision": revisions[draft_id]}}
        raise AssertionError(call)

    return gateway, calls


def test_m01_goal_is_one_closed_import_batch_with_only_quiet_track_volume(
    tmp_path: Path,
) -> None:
    project = tmp_path / "Sample.wproj"
    project.write_text("<Project/>", encoding="utf-8")
    media_dir = tmp_path / "ExpansionAssets" / "music"
    media_dir.mkdir(parents=True)
    quiet, full = media_dir / "Quiet.wav", media_dir / "Full.wav"
    quiet.write_bytes(b"RIFF-quiet")
    full.write_bytes(b"RIFF-full")
    media = {"Quiet": quiet, "Full": full}
    parent_path = r"\Containers\Default Work Unit\Owned"
    gateway, calls = _draft_gateway()
    ctx = ExpansionCaseContext("2025.1", "M01", project, tmp_path / "assets", gateway)
    prepared = PreparedExpansionCase(
        prompt="goal", operation="audio.import", policy="allow_changes",
        before={"parent": {"id": PARENT, "path": parent_path}},
        read_object_ids=frozenset({PARENT}), relationship_sources=frozenset(),
        read_includes=frozenset(), required_assertions=frozenset({"goal"}),
        approve_preview=lambda _artifact: True, snapshot=lambda: {},
        verify=lambda _before, _after: {"goal": True},
        archive_oracle_parameters={"expected_hashes": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in media.items()
        }},
        archive_preview_parameters={"version": "2025.1", "parent_path": parent_path,
                                    "segment_name": "Imported",
                                    "media": {name: str(path) for name, path in media.items()}},
    )

    build_goal_draft(ctx, "M01", prepared)

    declarations = [call for call in calls if call[0] == "draft-declare-import-batch"]
    assert len(declarations) == 1
    call = declarations[0]
    args = list(call[call.index("--expected-revision") + 2:])
    assert args == [
        "--row-order", "segment", "quiet", "full",
        "--new-row", "segment", "boh1-parent", "Imported", "music-segment",
        "--new-row", "quiet", "segment", "Quiet", "music-track",
        "--new-row", "full", "segment", "Full", "music-track",
        "--media-directory", str(media_dir),
        "--media-file", "quiet", "Quiet.wav",
        "--media-file", "full", "Full.wav",
        "--field", "quiet", "volume_db", "-6",
    ]


def test_c06_goal_uses_discovered_volume_field_and_updates_existing_rtpc() -> None:
    gateway, calls = _draft_gateway()
    ctx = ExpansionCaseContext("2025.1", "C06", Path("/fixture/Sample.wproj"),
                               Path("/fixture/assets"), gateway)
    target = {"id": TARGET, "@PropertyName": "Volume",
              "@ControlInput": {"id": CONTROL}, "notes": "keep target notes"}
    sibling = {"id": SIBLING, "@PropertyName": "Pitch",
               "@ControlInput": {"id": CONTROL}, "notes": "keep sibling"}
    prepared = PreparedExpansionCase(
        prompt="goal", operation="object.setRTPC", policy="allow_changes",
        before={"rtpcs": {TARGET: target, SIBLING: sibling}},
        read_object_ids=frozenset({OWNER, CONTROL, TARGET, SIBLING}),
        relationship_sources=frozenset({OWNER}), read_includes=frozenset(),
        required_assertions=frozenset({"goal"}),
        approve_preview=lambda _artifact: True, snapshot=lambda: {},
        verify=lambda _before, _after: {"goal": True},
        archive_preview_parameters={"version": "2025.1", "owner_id": OWNER,
                                    "control_id": CONTROL, "target_id": TARGET,
                                    "expected_notes": "keep target notes"},
    )

    build_goal_draft(ctx, "C06", prepared)

    bound = [call for call in calls if call[0] == "draft-bind-object"]
    assert [call[call.index("--object-id") + 1] for call in bound] == [OWNER, CONTROL]
    discovery = next(call for call in calls if call[0] == "draft-discover-fields")
    assert discovery[discovery.index("--meaning") + 1] == "volume"
    declaration = next(call for call in calls if call[0] == "draft-declare-rtpc")
    args = list(declaration[declaration.index("--expected-revision") + 2:])
    assert args == [
        "--object-handle", "boh1-parent", "--field-handle", "bf1-volume",
        "--control-input-handle", "boh1-parent", "--mode", "add-or-update",
        "--notes", "keep target notes",
        "--point", "0", "-48", "Linear",
        "--point", "50", "-6", "Linear",
        "--point", "100", "0", "Linear",
    ]


def test_rejected_goal_preview_stops_before_confirmation_or_execution() -> None:
    calls = []
    revision = 1
    artifact = {"request": {"operation": "audio.import"}, "artifact_hash": "h"}

    def gateway(argv):
        nonlocal revision
        calls.append(tuple(argv))
        command = argv[0]
        if command == "draft-start":
            return {"draft": {"draft_id": "od1-review", "revision": revision},
                    "task_authority": "authority"}
        if command in {"draft-check", "preview-from-draft"}:
            revision += 1
            result = {"draft": {"revision": revision}}
            if command == "preview-from-draft":
                result["transaction_id"] = "tx1-review"
            return result
        if command == "transaction-show":
            return {"state": "awaiting_confirmation", "transaction_id": "tx1-review",
                    "artifact_hash": "review-hash", "artifact": artifact,
                    "confirmation": {"token": "ct1-review"}}
        raise AssertionError(argv)

    ctx = ExpansionCaseContext("2025.1", "M01", Path("/fixture/Sample.wproj"),
                               Path("/fixture/assets"), gateway)
    draft = BusinessDraft(ctx, "audio.import")
    approvals = []
    prepared = PreparedExpansionCase(
        prompt="goal", operation="audio.import", policy="allow_changes", before={},
        read_object_ids=frozenset({PARENT}), relationship_sources=frozenset(),
        read_includes=frozenset(), required_assertions=frozenset({"goal"}),
        approve_preview=lambda received: approvals.append(received) or False,
        snapshot=lambda: {}, verify=lambda _before, _after: {"goal": False},
    )

    with pytest.raises(CaseBoundaryError, match="did not approve"):
        review_approve_execute_verify(draft, prepared)

    assert approvals == [artifact]
    assert [call[0] for call in calls] == [
        "draft-start", "draft-check", "preview-from-draft", "transaction-show",
    ]
    assert not any(call[0] in {"confirm", "execute", "verify"} for call in calls)


def test_approved_goal_preview_confirms_executes_once_and_verifies() -> None:
    order = []
    revision = 1
    artifact = {"request": {"operation": "object.setRTPC"}, "artifact_hash": "hash"}

    def gateway(argv):
        nonlocal revision
        command = argv[0]
        order.append(command)
        if command == "draft-start":
            return {"draft": {"draft_id": "od1-approved", "revision": revision},
                    "task_authority": "authority"}
        if command in {"draft-check", "preview-from-draft"}:
            revision += 1
            result = {"draft": {"revision": revision}}
            if command == "preview-from-draft":
                result["transaction_id"] = "tx1-approved"
            return result
        if command == "transaction-show":
            return {"state": "awaiting_confirmation", "transaction_id": "tx1-approved",
                    "artifact": artifact,
                    "artifact_hash": "hash", "confirmation": {"token": "ct1-approved"}}
        if command == "confirm":
            return {"state": "confirmed"}
        if command == "execute":
            return {"state": "executed_unverified"}
        if command == "verify":
            return {"state": "verified", "verification": {"business_state_verified": True}}
        raise AssertionError(argv)

    ctx = ExpansionCaseContext("2025.1", "C06", Path("/fixture/Sample.wproj"),
                               Path("/fixture/assets"), gateway)
    draft = BusinessDraft(ctx, "object.setRTPC")

    def approve(received):
        assert received is artifact
        order.append("adapter-approved")
        return True

    prepared = PreparedExpansionCase(
        prompt="goal", operation="object.setRTPC", policy="allow_changes", before={},
        read_object_ids=frozenset({OWNER}), relationship_sources=frozenset(),
        read_includes=frozenset(), required_assertions=frozenset({"goal"}),
        approve_preview=approve, snapshot=lambda: {},
        verify=lambda _before, _after: {"goal": True},
    )

    result = review_approve_execute_verify(draft, prepared)

    assert order == [
        "draft-start", "draft-check", "preview-from-draft", "transaction-show",
        "adapter-approved", "confirm", "execute", "verify",
    ]
    assert result == {
        "transaction_id": "tx1-approved", "artifact_hash": "hash",
        "gateway_verification_state": "verified", "business_state_verified": True,
    }


def test_goal_probe_requires_stable_before_and_all_independent_after_assertions() -> None:
    points = [{"x": 0, "y": -48, "shape": "Linear"},
              {"x": 50, "y": -6, "shape": "Linear"},
              {"x": 100, "y": 0, "shape": "Linear"}]
    before = {"rtpcs": {
        TARGET: {"id": TARGET, "@PropertyName": "Volume", "@ControlInput": {"id": CONTROL},
                 "notes": "target", "@Curve": {"points": [{"x": 0, "y": -12, "shape": "Linear"}]}},
        SIBLING: {"id": SIBLING, "@PropertyName": "Pitch", "@ControlInput": {"id": CONTROL},
                  "notes": "sibling", "@Curve": {"points": [{"x": 0, "y": 0, "shape": "Linear"}]}},
    }}
    after = {"rtpcs": {
        TARGET: {**before["rtpcs"][TARGET], "@Curve": {"points": points}},
        SIBLING: before["rtpcs"][SIBLING],
    }}
    calls = []
    receipts = []
    revision = 1

    def gateway(argv):
        nonlocal revision
        call = tuple(argv)
        calls.append(call)
        receipts.append({"argv": list(argv)})
        command = argv[0]
        if command == "query-object":
            return {"ok": True}
        if command == "draft-start":
            return {"draft": {"draft_id": "od1-run", "revision": revision},
                    "task_authority": "authority"}
        if command == "draft-bind-object":
            revision += 1
            return {"draft": {"revision": revision}, "bound_object": {"handle": "boh1-bound"}}
        if command == "draft-discover-fields":
            revision += 1
            return {"draft": {"revision": revision},
                    "meaning_results": [{"candidates": [{"handle": "bf1-volume"}]}]}
        if command.startswith("draft-"):
            revision += 1
            return {"draft": {"revision": revision}}
        if command == "preview-from-draft":
            revision += 1
            return {"draft": {"revision": revision}, "transaction_id": "tx1-run"}
        if command == "transaction-show":
            return {"state": "awaiting_confirmation", "transaction_id": "tx1-run",
                    "artifact": {"prepared": True},
                    "artifact_hash": "hash", "confirmation": {"token": "token"}}
        if command == "confirm":
            return {"state": "confirmed"}
        if command == "execute":
            return {"state": "executed_unverified"}
        if command == "verify":
            return {"state": "verified", "verification": {"business_state_verified": True}}
        raise AssertionError(call)

    ctx = ExpansionCaseContext("2025.1", "C06", Path("/fixture/Sample.wproj"),
                               Path("/fixture/assets"), gateway)
    snapshot_count = 0

    def snapshot():
        nonlocal snapshot_count
        snapshot_count += 1
        ctx.gateway(["query-object", "--exact-id", OWNER, "--max-results", "2"])
        return before if snapshot_count < 3 else after

    required = frozenset({"target_curve_matches", "sibling_curves_unchanged"})
    prepared = PreparedExpansionCase(
        prompt="goal", operation="object.setRTPC", policy="allow_changes", before=before,
        read_object_ids=frozenset({OWNER, CONTROL, TARGET, SIBLING}),
        relationship_sources=frozenset({OWNER}), read_includes=frozenset(),
        required_assertions=required, approve_preview=lambda _artifact: True,
        snapshot=snapshot,
        verify=lambda old, new: {
            "target_curve_matches": new["rtpcs"][TARGET]["@Curve"]["points"] == points,
            "sibling_curves_unchanged": new["rtpcs"][SIBLING] == old["rtpcs"][SIBLING],
        },
        archive_preview_parameters={"version": "2025.1", "owner_id": OWNER,
                                    "control_id": CONTROL, "target_id": TARGET,
                                    "expected_notes": "target"},
    )

    result = run_goal_probe(ctx, "C06", prepared, receipts)

    assert result["assertions"] == {name: True for name in required}
    assert result["business_state_verified"] is True and result["agent_pass"] is False
    assert [call[0] for call in calls].count("execute") == 1
