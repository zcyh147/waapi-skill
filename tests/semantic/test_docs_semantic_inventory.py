from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SEMANTIC_README = REPO_ROOT / "tests" / "semantic" / "README.md"
TEST_INVENTORY = REPO_ROOT / "tests" / "TEST_INVENTORY.md"

CODEX_PROFILE_COMMANDS = (
    "skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py "
    "--profile screening --campaign-root "
    "skills/waapi-skill-workspace/campaign-screening",
    "skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py "
    "--profile formal_98 --campaign-root "
    "skills/waapi-skill-workspace/campaign-formal-98",
    "skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py "
    "--profile full_cross_version_168 --campaign-root "
    "skills/waapi-skill-workspace/campaign-full-cross-version-168",
)
LEGACY_OPENCODE_COMMANDS = (
    "python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test "
    "--scenario-set phase3-required --wwise-version 2022.1 --archive-root "
    ".sisyphus/evidence/waapi-opencode-semantic-runs --require-live",
    "python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test "
    "--scenario-set phase3-smoke --wwise-version all --archive-root "
    ".sisyphus/evidence/waapi-opencode-semantic-runs --prefer-live",
    "python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test "
    "--scenario-set semantic-capability-required --wwise-version 2022.1 --archive-root "
    ".sisyphus/evidence/waapi-opencode-semantic-runs --require-live",
    "python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test "
    "--scenario-set semantic-capability-all --wwise-version all --archive-root "
    ".sisyphus/evidence/waapi-opencode-semantic-runs --require-live",
    "python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test "
    "--scenario-set semantic-capability-boundary --wwise-version all --archive-root "
    ".sisyphus/evidence/waapi-opencode-semantic-runs --require-live",
)


def test_fresh_codex_profiles_are_the_formal_documented_workflow() -> None:
    readme = SEMANTIC_README.read_text(encoding="utf-8")
    inventory = TEST_INVENTORY.read_text(encoding="utf-8")

    for command in CODEX_PROFILE_COMMANDS:
        assert command in readme
        assert command in inventory
    for phrase in (
        "Fresh Codex semantic validation",
        "formal agent-behavior gate",
        "append-only",
        "--resume --verify-only",
        "memory-off",
        "disposable `HOME` and `CODEX_HOME`",
        "`screening` | 40",
        "`formal_98` | 98",
        "`full_cross_version_168` | 168",
    ):
        assert phrase in readme


def test_opencode_commands_are_retained_only_as_legacy_comparison() -> None:
    readme = SEMANTIC_README.read_text(encoding="utf-8")
    inventory = TEST_INVENTORY.read_text(encoding="utf-8")

    for command in LEGACY_OPENCODE_COMMANDS:
        assert command in readme
        assert command in inventory
    assert "Legacy OpenCode comparison" in readme
    assert "Legacy OpenCode comparison" in inventory
    assert "not the formal memory-off v2 gate" in readme
    assert "# Semantic OpenCode validation" not in readme


def test_inventory_count_matches_latest_nonlive_result_without_collect_only_overclaim() -> None:
    inventory = TEST_INVENTORY.read_text(encoding="utf-8")

    assert "807 pytest items" not in inventory
    assert "807 tests collected" not in inventory
    assert "2938 passed, 77 skipped, 27 deselected" in inventory
    assert "not a fresh full `--collect-only` recount" in inventory


def test_fresh_codex_docs_keep_isolation_broker_and_infrastructure_semantics() -> None:
    readme = SEMANTIC_README.read_text(encoding="utf-8")

    for phrase in (
        "links only the selected\n`auth.json`",
        "exactly one target Skill",
        "phase-local broker",
        "reconciled with the Codex JSON event trace",
        "Quota/rate-limit",
        "Codex infrastructure failure",
        "does not count as a Skill pass or a Skill failure",
        "the profile remains\nincomplete",
        "Once the agent has acted",
        "partial or quota-blocked artifacts must be reported as incomplete",
        "No campaign cleanup uses a global Wwise kill",
        "mocked/offline tests does not prove live semantic capability",
        "`live-preflight.json`",
        "before starting a\nCodex phase or WwiseConsole",
        "Pure offline selections skip this live dependency\ncheck",
        "never runs `pip` or changes the global environment",
    ):
        assert phrase in readme


def test_docs_do_not_overclaim_formal_or_full_completion() -> None:
    readme = SEMANTIC_README.read_text(encoding="utf-8")

    assert "Profile names and expected session totals are test definitions, not proof" in readme
    assert "Do not claim `formal_98` or `full_cross_version_168` completed" in readme
    for stale_claim in (
        "Current formal_98 evidence passes",
        "Current full_cross_version_168 evidence passes",
        "formal_98 completed successfully",
        "full_cross_version_168 completed successfully",
    ):
        assert stale_claim not in readme
