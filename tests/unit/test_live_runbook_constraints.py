from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "references" / "long-run-runbook.md"
REVIEW_PACKET = ROOT / "references" / "phase2-user-review-packet.md"


def read_reference(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_runbook_documents_live_sandbox_workflows_and_env_vars() -> None:
    text = read_reference(RUNBOOK)

    for heading in (
        "Default Wwise-free verification",
        "Live smoke prerequisites",
        "Live sandbox read-only workflows",
        "Destructive sandbox workflows",
        "Keep-on-failure evidence workflow",
        "Prerequisite failure workflow",
        "Windows-pending workflow",
    ):
        assert heading in text

    for env_var in (
        "WWISE_SAMPLE_PROJECT_PATH",
        "WWISE_FIXTURE_PROJECT",
        "WWISE_SANDBOX_ROOT",
        "WWISE_SANDBOX_KEEP_ON_FAILURE",
        "WWISE_LIVE",
        "WWISE_DESTRUCTIVE",
    ):
        assert env_var in text


def test_runbook_keeps_live_and_destructive_commands_safe() -> None:
    text = read_reference(RUNBOOK)

    required_phrases = (
        "python -m pytest -q",
        "WWISE_LIVE=1",
        "WWISE_DESTRUCTIVE=1",
        "tests/live/test_live_prerequisites.py -q",
        "tests/destructive/test_project_mutation_sandbox.py",
        "/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject",
        "immutable source-to-copy fixture path",
        "is not committed or vendored",
        "Destructive tests must only mutate copied sandboxes under `WWISE_SANDBOX_ROOT`",
        "Never point `WWISE_FIXTURE_PROJECT` at a source project, production project, user project",
        "Do not commit preserved sandboxes, generated banks, generated audio, runtime logs, caches, `.venv`, or auth/session state",
        "macOS-generated `GeneratedSoundBanks/Windows` artifacts are sandbox output only, not Windows validation",
    )
    for phrase in required_phrases:
        assert phrase in text


def test_runbook_explains_evidence_inspection_and_category_reruns() -> None:
    text = read_reference(RUNBOOK)

    assert ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/" in text
    assert "Compare copied `.wproj`, `.wwu`, generated bank, audio, and log artifacts" in text
    assert "Rerun only the failed category after the prerequisite smoke test passes" in text
    assert "tests/live/test_waql_live_matrix.py -q" in text
    assert "tests/live/test_profiler_transport_soundengine.py -q" in text
    assert "tests/destructive/test_soundbank_audio_sandbox.py -q" in text
    assert "Accepted WAAPI calls alone are not coverage" in text


def test_live_opt_in_prerequisite_failures_fail_fast_without_fake_fallback() -> None:
    text = read_reference(RUNBOOK)

    assert "with `WWISE_LIVE=1` set, missing Wwise or SampleProject prerequisites must fail fast" in text
    assert "clear prerequisite error before any live or destructive workflow continues" in text
    assert "Do not silently skip, fall back to fake routes, or treat the live opt-in failure as substitute coverage" in text
    assert "fail fast or skip" not in text


def test_review_packet_contains_corrected_counts_and_statuses() -> None:
    text = read_reference(REVIEW_PACKET)

    for phrase in (
        "Original deferred before Phase 2 | 117",
        "Original deferred after Phase 2 | 74",
        "`fake-route-tested` | 25",
        "`sandbox-mutating-tested` | 13",
        "`skipped-approved` | 21",
        "`wrapper-only` | 11",
        "`still-deferred-with-evidence` | 74",
        "13 promoted behavioral, 30 policy-approved inventory-only, and 74 still deferred with evidence",
        "Do not claim that all 117 original deferred APIs are fully behavior-tested",
    ):
        assert phrase in text


def test_review_packet_documents_blockers_without_overclaiming() -> None:
    text = read_reference(REVIEW_PACKET)

    for phrase in (
        "`ak.wwise.core.project.saved` is reflected, but WwiseConsole reports the topic as unavailable",
        "`ak.wwise.core.soundbank.processDefinitionFiles` remains blocked",
        "WAQL generation fail-closed",
        "malformed-WAQL error payload shapes",
        "timeout, memory, recursion, and performance limits",
        "did not observe a transport state transition",
        "profiler capture-log payload for `postMsgMonitor`",
        "profiler game-object payloads",
        "accepted calls are not enough to count as coverage",
        "Windows validation remains pending",
        "not Windows-host evidence",
    ):
        assert phrase in text


def test_review_packet_includes_explicit_user_approval_gate() -> None:
    text = read_reference(REVIEW_PACKET)

    assert "Use this exact approval gate before F1-F4 are marked complete" in text
    assert "Please review the Phase 2 live sandbox coverage packet" in text
    assert "F1-F4 must not be marked complete until you explicitly approve this packet" in text
    assert ".sisyphus/evidence/task-12-approval-stop.md" in text
