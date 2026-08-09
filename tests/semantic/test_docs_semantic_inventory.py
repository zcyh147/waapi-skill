from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_AGENTS = REPO_ROOT / "AGENTS.md"
TESTS_AGENTS = REPO_ROOT / "tests" / "AGENTS.md"
SEMANTIC_README = REPO_ROOT / "tests" / "semantic" / "README.md"
TEST_INVENTORY = REPO_ROOT / "tests" / "TEST_INVENTORY.md"

PUBLIC_INTEGRATION_CANDIDATE = "7f54506783a131695bafb97b89103488cb73d96c"
PUBLIC_INTEGRATION_MAC_ROOTS = (
    "imac-int-7f54506-r1",
    "imac-int-7f54506-r2-retry5",
    "imac-int-7f54506-r3-rifle",
)
PUBLIC_INTEGRATION_WINDOWS_ROOTS = (
    "iwin-int-7f54506-r1",
    "iwin-int-7f54506-r2-retry3",
)

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
        "Memory-off",
        "disposable `HOME` and `CODEX_HOME`",
        "`screening` | 40",
        "`formal_98` | 98",
        "`full_cross_version_168` | 168",
    ):
        assert phrase in readme


def test_retired_agent_evaluation_lanes_are_not_documented() -> None:
    readme = SEMANTIC_README.read_text(encoding="utf-8")
    inventory = TEST_INVENTORY.read_text(encoding="utf-8")

    for stale_name in (
        "run_opencode_semantic_batch.py",
        "run_codex_skill_evals.py",
        "tests/support/evals.json",
        "skills/waapi-skill/evals/evals.json",
        "Legacy OpenCode comparison",
    ):
        assert stale_name not in readme
        assert stale_name not in inventory


def test_inventory_count_matches_latest_nonlive_result_without_collect_only_overclaim() -> None:
    inventory = TEST_INVENTORY.read_text(encoding="utf-8")

    assert "807 pytest items" not in inventory
    assert "807 tests collected" not in inventory
    recorded_results = re.findall(
        r"(\d+ passed, \d+ skipped, \d+ deselected)",
        inventory,
    )
    assert len(recorded_results) >= 2
    assert len(set(recorded_results)) == 1
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


def test_public_integration_candidate_evidence_is_exact_and_host_scoped() -> None:
    documents = tuple(
        path.read_text(encoding="utf-8")
        for path in (ROOT_AGENTS, TESTS_AGENTS, SEMANTIC_README, TEST_INVENTORY)
    )

    for document in documents:
        assert PUBLIC_INTEGRATION_CANDIDATE in document
        for root in (*PUBLIC_INTEGRATION_MAC_ROOTS, *PUBLIC_INTEGRATION_WINDOWS_ROOTS):
            assert root in document
        for phrase in (
            "passed 7\nunits and failed 5",
            "passed 4 and failed 1",
            "passed its one fresh Rifle unit and its identical",
            "All 12 unique public-profile units therefore\nhave macOS passing evidence",
            "but no root passed 12/12",
            "passed 9 units and failed 3",
            "passed Weather and failed both Weapons\nunits",
            "10 of 12 unique public-profile units with native-Windows passing\nevidence",
            "authenticated Broker rejected malformed preview JSON",
            "not complete\nnative-Windows `integration` acceptance",
            "must not be reported as Windows\n12/12",
            "All four roots containing semantic FAILs were frozen without\nverify-only replay",
            "test_native_windows_powershell_shim_preserves_hostile_json",
            "2 passed, exit 0",
            "without granting any semantic PASS\ncredit",
            "full hash and mtime remained\nunchanged",
            "no scoped residual process remained",
        ):
            assert phrase in document

    inventory = documents[-1]
    assert "`ci\\test.bat --mode program -- -q -ra`" in inventory
    assert "2609 passed, 34 skipped in 167.50s; exit 0" in inventory
    assert "The batch launcher delegated repository development tests to Poetry" in inventory
    assert "started neither Codex nor Wwise" in inventory


def test_public_integration_candidate_docs_forbid_false_windows_completion() -> None:
    documents = tuple(
        path.read_text(encoding="utf-8")
        for path in (ROOT_AGENTS, TESTS_AGENTS, SEMANTIC_README, TEST_INVENTORY)
    )

    for document in documents:
        for false_claim in (
            f"candidate `{PUBLIC_INTEGRATION_CANDIDATE}` passed Windows 12/12",
            "`iwin-int-7f54506-r1` passed all 12",
            "`iwin-int-7f54506-r2-retry3` passed both Weapons",
            "complete native-Windows `integration` acceptance for candidate",
            "single-root 12/12 at `imac-int-7f54506-r1`",
        ):
            assert false_claim not in document
