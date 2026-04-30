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
        "Unit coverage and packet verification",
        "Live smoke prerequisites",
        "Live sandbox read-only workflows",
        "Destructive sandbox workflows",
        "Phase 2.1 status meanings",
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
        "tests/unit/test_phase2_coverage_summary.py tests/unit/test_live_runbook_constraints.py -q",
        "tests/destructive/test_project_mutation_sandbox.py",
        "/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject",
        "immutable source-to-copy fixture path",
        "is not committed or vendored",
        "The committed `tests/_org/2022.1` tree is immutable fixture source",
        "normal tests must never mutate either source fixture tree",
        "Destructive tests must only mutate copied sandboxes under `WWISE_SANDBOX_ROOT`",
        "Never point `WWISE_FIXTURE_PROJECT` at a source project, production project, user project",
        "Do not commit preserved sandboxes, generated banks, generated audio, runtime logs, caches, `.venv`, or auth/session state",
        "Committed fixture `.wav` inputs under `tests/_org/2022.1` are handled through Git LFS",
        "Generated `.wav` files, converted audio, SoundBank output, profiler captures, runtime sandboxes, caches, auth state, and session state are runtime artifacts and must not be committed",
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
    assert "returned IDs, empty mappings, capture start/stop, or no exceptions are context only" in text



def test_runbook_documents_semantic_builder_refresh_and_execution_tiers() -> None:
    text = read_reference(RUNBOOK)

    for phrase in (
        "Semantic builder and source-note refresh workflow",
        "Default development remains Wwise-free",
        "They do not execute live WAAPI calls by default",
        "Query NotebookLM notebook `wwise-2022.1-docs`",
        "references/semantic-builder-notebooklm-gate.md",
        "resources/semantic/2022.1/source_notes.json",
        "tests/unit/test_semantic_builder_source_notes.py tests/unit/test_semantic_builder_audit.py -q",
        "profiler, transport, soundengine, UI, CLI, remote, or debug APIs",
        "WWISE_LIVE=1 python -m pytest tests/live/test_waql_live_matrix.py -q",
        "WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes",
        "Live and destructive tests skip unless the matching environment variables are explicitly set",
        "Never treat a skipped live/destructive suite as proof of live execution",
    ):
        assert phrase in text

def test_runbook_documents_phase21_status_meanings_without_overclaiming() -> None:
    text = read_reference(RUNBOOK)

    for phrase in (
        "`fake-route-tested`: Phase 1 fake-route behavior remains accepted",
        "`sandbox-mutating-tested`: copied-sandbox behavior evidence exists",
        "`skipped-approved`: user-approved inventory-only exclusion",
        "`wrapper-only`: wrapper diagnostics or route coverage only",
        "`conformance-only-skip`: user-approved reflected schema and route conformance only",
        "`still-deferred-with-evidence`: blocker evidence and future review trigger exist",
        "not behavioral or live behavioral coverage",
    ):
        assert phrase in text


def test_live_opt_in_prerequisite_failures_fail_fast_without_fake_fallback() -> None:
    text = read_reference(RUNBOOK)

    assert "with `WWISE_LIVE=1` set, missing Wwise or SampleProject prerequisites must fail fast" in text
    assert "clear prerequisite error before any live or destructive workflow continues" in text
    assert "Do not silently skip, fall back to fake routes, or treat the live opt-in failure as substitute coverage" in text
    assert "fail fast or skip" not in text


def test_phase21_review_packet() -> None:
    text = read_reference(REVIEW_PACKET)

    for phrase in (
        "Original deferred before Phase 2 | 117",
        "Original deferred after Phase 2 | 63",
        "Original deferred promoted to behavioral coverage | 13",
        "Original deferred policy-approved as inventory only | 41",
        "Live behavioral covered count | 13",
        "Behavioral covered count including fake-route coverage | 38",
        "`fake-route-tested` | 25",
        "`sandbox-mutating-tested` | 13",
        "`skipped-approved` | 21",
        "`wrapper-only` | 11",
        "`conformance-only-skip` | 11",
        "`still-deferred-with-evidence` | 63",
        "13 promoted behavioral, 41 policy-approved inventory-only, and 63 still deferred with evidence",
        "includes 21 skipped-approved APIs, 11 wrapper-only APIs, and 11 conformance-only-skip APIs",
        "Do not claim that all 117 original deferred APIs are fully behavior-tested",
    ):
        assert phrase in text

    for uri in (
        "ak.wwise.core.project.loaded",
        "ak.wwise.core.project.postClosed",
        "ak.wwise.core.project.preClosed",
        "ak.wwise.core.project.save",
        "ak.wwise.core.project.saved",
        "ak.wwise.core.transport.create",
        "ak.wwise.core.transport.destroy",
        "ak.wwise.core.transport.executeAction",
        "ak.wwise.core.transport.prepare",
        "ak.wwise.core.transport.stateChanged",
        "ak.wwise.core.undo.cancelGroup",
    ):
        assert f"`{uri}`" in text


def test_review_packet_documents_blockers_without_overclaiming() -> None:
    text = read_reference(REVIEW_PACKET)

    for phrase in (
        "Project lifecycle and transport lifecycle APIs in the conformance-only set remain policy-approved inventory coverage",
        "`ak.wwise.core.undo.redo` is absent locally",
        "`ak.wwise.core.undo.cancelGroup` is conformance-only under current policy",
        "`ak.wwise.core.soundbank.processDefinitionFiles` remains blocked",
        "WAQL generation fail-closed",
        "malformed-WAQL error payload shapes",
        "timeout, memory, recursion, and performance limits",
        "did not observe a transport state transition",
        "profiler capture-log payload for `postMsgMonitor`",
        "profiler game-object payloads",
        "Returned ids, empty mappings, capture start/stop, no exceptions, or accepted calls are not enough to count as coverage",
        "`conformance-only-skip`, `wrapper-only`, and `skipped-approved` are inventory, conformance, or route-policy results, not live behavior",
        "Windows validation remains pending",
        "not Windows-host evidence",
    ):
        assert phrase in text


def test_review_packet_includes_explicit_user_approval_gate() -> None:
    text = read_reference(REVIEW_PACKET)

    assert "Use this exact approval gate before F1-F4 are marked complete" in text
    assert "Please review the Phase 2.1 live sandbox coverage packet" in text
    assert "F1-F4 must not be marked complete until you explicitly approve this packet" in text
    assert "the 11 conformance-only-skip entries" in text
    assert ".sisyphus/evidence/task-12-approval-stop.md" in text
