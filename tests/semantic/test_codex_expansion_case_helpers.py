from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
from tests.semantic.support import codex_expansion_case_helpers as expansion_helpers
from tests.semantic.support.codex_expansion_case_helpers import (
    BusinessDraft, CaseBoundaryError, file_evidence, make_public_gateway,
    read_object, rows, wav_assets,
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


def test_assets_reuse_distinct_owned_media_and_generate_only_the_shortfall(tmp_path: Path) -> None:
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
    selected = wav_assets(ctx, 3)
    assert len({path.read_bytes() for path in selected}) == 3
    generated = [path for path in selected if path.parent != originals]
    assert len(generated) == 1
    import wave
    with wave.open(str(generated[0]), "rb") as audio:
        assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
        assert audio.getnframes() == 800
    assert first.read_bytes() == b"RIFF-a" and second.read_bytes() == b"RIFF-b"
    outside = tmp_path.parent / "outside.wav"
    with pytest.raises(CaseBoundaryError, match="escapes"):
        file_evidence(ctx, str(outside))


def test_public_gateway_uses_the_packaged_runner_and_owned_live_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    state = tmp_path / "state"
    receipts = []
    expected = {"ok": True, "endpoint": {"host": "127.0.0.1", "port": 8090},
                "detected_version": "2025.1", "objects": []}

    def run(command, **kwargs):
        assert command[1] == str(expansion_helpers._GATEWAY_RUNNER)
        assert command[2] == "gateway.py"
        assert command[command.index("--host") + 1] == "127.0.0.1"
        assert command[command.index("--port") + 1] == "8090"
        assert command[command.index("--version") + 1] == "2025.1"
        assert command[command.index("--state-dir") + 1] == str(state)
        assert kwargs["cwd"] == expansion_helpers._GATEWAY_CWD
        assert kwargs["env"]["WAAPI_SKILL_CONFIG_PATH"] == str(config)
        assert kwargs["env"]["WAAPI_SKILL_STATE_DIR"] == str(state)
        assert kwargs["timeout"] == 60
        return expansion_helpers.subprocess.CompletedProcess(
            command, 0, json.dumps(expected).encode("utf-8"), b"",
        )

    monkeypatch.setattr(expansion_helpers.subprocess, "run", run)
    gateway = make_public_gateway(
        host="127.0.0.1", port=8090, version="2025.1", config_path=config,
        state_dir=state, environment={}, receipts=receipts,
        live_commands=frozenset({"query-object"}),
    )
    assert gateway(["query-object", "--max-results", "2"]) == expected
    assert receipts[0]["payload"] == expected
    assert receipts[0]["returncode"] == 0


def test_public_gateway_preserves_structured_failure_and_bounds_process_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    receipts = []
    failure = {"ok": False, "status": "failed", "error": {"code": "HOST_TIMEOUT"}}
    monkeypatch.setattr(
        expansion_helpers.subprocess, "run",
        lambda command, **kwargs: expansion_helpers.subprocess.CompletedProcess(
            command, 2, json.dumps(failure).encode(), b"bounded stderr",
        ),
    )
    gateway = make_public_gateway(
        host="127.0.0.1", port=8090, version="2022.1", config_path=config,
        state_dir=tmp_path / "state", environment={}, receipts=receipts,
        live_commands=frozenset({"query-object"}),
    )
    with pytest.raises(CaseBoundaryError, match="HOST_TIMEOUT"):
        gateway(["query-object", "--exact-id", GUID])
    assert receipts[0]["payload"] == failure
    assert receipts[0]["stderr_excerpt"] == "bounded stderr"


def test_public_gateway_retains_failed_assertion_names_in_oversize_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    receipts = []
    failure = {
        "ok": False,
        "status": "verification_failed",
        "error": {"code": "VERIFY_FAILED", "message": "business verification failed"},
        "verification": {
            "status": "verification_failed",
            "business_state_verified": False,
            "assertions": [
                {"name": "Event exact path resolves once", "passed": False,
                 "evidence": {"diagnostic": "x" * 40_000}},
            ],
        },
        "padding": "x" * 40_000,
    }
    monkeypatch.setattr(
        expansion_helpers.subprocess, "run",
        lambda command, **kwargs: expansion_helpers.subprocess.CompletedProcess(
            command, 2, json.dumps(failure).encode(), b"",
        ),
    )
    gateway = make_public_gateway(
        host="127.0.0.1", port=8090, version="2025.1", config_path=config,
        state_dir=tmp_path / "state", environment={}, receipts=receipts,
        live_commands=frozenset(),
    )
    with pytest.raises(CaseBoundaryError):
        gateway(["verify", "tx1-test"])
    receipt = receipts[0]
    assert receipt["payload_bytes"] > expansion_helpers._GATEWAY_RECEIPT_PAYLOAD_LIMIT_BYTES
    assert receipt["payload_summary"]["verification"]["failed_assertions"] == [
        "Event exact path resolves once",
    ]
    assert len(json.dumps(receipt["payload_summary"]).encode()) <= 4096


def test_public_gateway_timeout_is_retained_as_a_bounded_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    receipts = []

    def run(command, **kwargs):
        raise expansion_helpers.subprocess.TimeoutExpired(
            command, kwargs["timeout"], output=b"partial output", stderr=b"still running",
        )

    monkeypatch.setattr(expansion_helpers.subprocess, "run", run)
    gateway = make_public_gateway(
        host="127.0.0.1", port=8090, version="2025.1", config_path=config,
        state_dir=tmp_path / "state", environment={}, receipts=receipts,
        live_commands=frozenset(),
    )
    with pytest.raises(CaseBoundaryError, match="60 seconds"):
        gateway(["draft-start", "object.create"])
    assert receipts[0]["error"] == "subprocess_timeout"
    assert receipts[0]["stdout_excerpt"] == "partial output"
    assert receipts[0]["stderr_excerpt"] == "still running"
