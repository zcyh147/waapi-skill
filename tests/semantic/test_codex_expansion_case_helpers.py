from __future__ import annotations

from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
from tests.semantic.support.codex_expansion_case_helpers import (
    BusinessDraft, CaseBoundaryError, file_evidence, read_object, rows, wav_assets,
)


GUID = "{11111111-1111-1111-1111-111111111111}"
OTHER = "{22222222-2222-2222-2222-222222222222}"


def _payload(items, limit=2):
    return {"ok": True, "count": len(items), "objects": items,
            "query_bound": {"mode": "take", "value": limit}}


def test_public_query_completeness_uses_real_bound_without_draft_integrity() -> None:
    value = _payload([{"id": GUID}])
    assert rows(value) == [{"id": GUID}]
    assert rows({**value, "query_bound": {"mode": "exact-object"}}) == [{"id": GUID}]


@pytest.mark.parametrize("change", (
    {"count": 0}, {"query_bound": {"mode": "take", "value": 1}},
    {"query_bound": {"mode": "all"}}, {"limit_reached": True},
    {"response_integrity": {"complete": False, "truncated": True}},
))
def test_public_query_fails_closed_on_incomplete_receipts(change) -> None:
    with pytest.raises(CaseBoundaryError):
        rows({**_payload([{"id": GUID}]), **change})


def test_public_query_rejects_duplicate_and_misbound_identities(tmp_path: Path) -> None:
    with pytest.raises(CaseBoundaryError):
        rows(_payload([{"id": GUID}, {"id": GUID}], 3))
    ctx = ExpansionCaseContext("2025.1", "C01", tmp_path / "Sample.wproj", tmp_path / "assets",
                               lambda argv: _payload([{"id": OTHER}]))
    with pytest.raises(CaseBoundaryError, match="GUID"):
        read_object(ctx, GUID)


def test_setup_uses_closed_roles_discovery_and_one_confirmed_execution(tmp_path: Path) -> None:
    calls = []
    revision = 1

    def gateway(argv):
        nonlocal revision
        calls.append(tuple(argv))
        command = argv[0]
        if command == "draft-start":
            return {"draft": {"draft_id": "od1-fixture", "revision": revision}, "task_authority": "authority"}
        if command.startswith("draft-") or command == "preview-from-draft":
            assert argv[argv.index("--expected-revision") + 1] == str(revision)
            revision += 1
            result = {"draft": {"revision": revision}}
            if command == "draft-bind-object":
                assert "--object-path-segment" in argv and "--path-segment" not in argv
                assert argv[-2:] == ["--role", "parent"]
                result["bound_object"] = {"handle": "boh1-fixture"}
            if command == "draft-discover-types":
                result["type_candidates"] = [{"handle": "bth1-fixture"}]
            if command == "preview-from-draft":
                result["transaction_id"] = "tx1-fixture"
            return result
        if command == "transaction-show":
            return {"state": "awaiting_confirmation", "confirmation": {"token": "ct1-fixture"}}
        if command == "confirm":
            assert argv == ["confirm", "tx1-fixture", "--confirmation-token", "ct1-fixture"]
            return {"state": "confirmed"}
        if command == "execute":
            return {"state": "executed_unverified"}
        if command == "verify":
            return {"state": "verified", "verification": {"business_state_verified": True}}
        raise AssertionError(argv)

    ctx = ExpansionCaseContext("2025.1", "C01", tmp_path / "Sample.wproj", tmp_path / "assets", gateway)
    draft = BusinessDraft(ctx, "object.create")
    assert draft.bind(segments=("Events", "Default Work Unit"), role="parent") == "boh1-fixture"
    assert draft.discover_type("Event") == "bth1-fixture"
    assert draft.finish()["verify"]["state"] == "verified"
    assert [row[0] for row in calls[-5:]] == ["preview-from-draft", "transaction-show", "confirm", "execute", "verify"]


def test_setup_does_not_execute_when_authorization_is_missing(tmp_path: Path) -> None:
    calls = []
    def gateway(argv):
        calls.append(argv[0])
        if argv[0] == "draft-start":
            return {"draft": {"draft_id": "od1-test", "revision": 1}, "task_authority": "a"}
        if argv[0] == "preview-from-draft":
            return {"transaction_id": "tx1-test"}
        return {"state": "awaiting_confirmation"}
    ctx = ExpansionCaseContext("2025.1", "C01", tmp_path / "Sample.wproj", tmp_path / "assets", gateway)
    with pytest.raises(CaseBoundaryError, match="authorization"):
        BusinessDraft(ctx, "audio.import").finish()
    assert "execute" not in calls


def test_assets_are_distinct_owned_media_and_missing_assets_block(tmp_path: Path) -> None:
    originals = tmp_path / "Originals"
    originals.mkdir()
    first = originals / "first.wav"
    first.write_bytes(b"RIFF-a")
    (originals / "duplicate.wav").write_bytes(b"RIFF-a")
    second = originals / "second.wav"
    second.write_bytes(b"RIFF-b")
    ctx = ExpansionCaseContext("2025.1", "C01", tmp_path / "Sample.wproj", tmp_path / "assets", lambda _: {})
    selected = wav_assets(ctx, 2)
    assert len({path.read_bytes() for path in selected}) == 2
    assert file_evidence(ctx, str(first))["path"] == str(first)
    with pytest.raises(CaseBoundaryError, match="3 distinct"):
        wav_assets(ctx, 3)
    outside = tmp_path.parent / "outside.wav"
    with pytest.raises(CaseBoundaryError, match="escapes"):
        file_evidence(ctx, str(outside))
