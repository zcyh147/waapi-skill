from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SEMANTIC_README = REPO_ROOT / "tests" / "semantic" / "README.md"
TEST_INVENTORY = REPO_ROOT / "tests" / "TEST_INVENTORY.md"

REQUIRED_2022_COMMAND = (
    "python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test "
    "--scenario-set phase3-required --wwise-version 2022.1 --archive-root "
    ".sisyphus/evidence/waapi-opencode-semantic-runs --require-live"
)
SMOKE_ALL_COMMAND = (
    "python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test "
    "--scenario-set phase3-smoke --wwise-version all --archive-root "
    ".sisyphus/evidence/waapi-opencode-semantic-runs --prefer-live"
)
CAPABILITY_REQUIRED_COMMAND = (
    "python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test "
    "--scenario-set semantic-capability-required --wwise-version 2022.1 --archive-root "
    ".sisyphus/evidence/waapi-opencode-semantic-runs --require-live"
)
CAPABILITY_ALL_COMMAND = (
    "python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test "
    "--scenario-set semantic-capability-all --wwise-version all --archive-root "
    ".sisyphus/evidence/waapi-opencode-semantic-runs --require-live"
)
CAPABILITY_BOUNDARY_COMMAND = (
    "python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test "
    "--scenario-set semantic-capability-boundary --wwise-version all --archive-root "
    ".sisyphus/evidence/waapi-opencode-semantic-runs --require-live"
)


def test_phase3_required_commands_stay_documented() -> None:
    readme = SEMANTIC_README.read_text(encoding="utf-8")
    inventory = TEST_INVENTORY.read_text(encoding="utf-8")

    for command in (REQUIRED_2022_COMMAND, SMOKE_ALL_COMMAND):
        assert command in readme
        assert command in inventory


def test_semantic_capability_commands_are_documented() -> None:
    readme = SEMANTIC_README.read_text(encoding="utf-8")
    inventory = TEST_INVENTORY.read_text(encoding="utf-8")

    for command in (CAPABILITY_REQUIRED_COMMAND, CAPABILITY_ALL_COMMAND, CAPABILITY_BOUNDARY_COMMAND):
        assert command in readme
        assert command in inventory

    for phrase in (
        "product semantic capability validation",
        "testing evidence",
        "does not prove product capability by itself",
    ):
        assert phrase in readme


def test_inventory_count_matches_latest_nonlive_result_without_collect_only_overclaim() -> None:
    inventory = TEST_INVENTORY.read_text(encoding="utf-8")

    assert "807 pytest items" not in inventory
    assert "807 tests collected" not in inventory
    assert "837 passed, 76 skipped, 24 deselected" in inventory
    assert "not a fresh full `--collect-only` recount" in inventory


def test_semantic_docs_keep_environment_archive_and_verdict_semantics() -> None:
    readme = SEMANTIC_README.read_text(encoding="utf-8")

    required_phrases = [
        "/Users/xiye/Documents/Git/waapi_skill_test",
        ".agents/skills/waapi-skill",
        "must be a symlink",
        "WwiseConsole.sh",
        "tests/_org/<version>/SampleProject.wproj",
        ".sisyphus/evidence/waapi-opencode-semantic-runs",
        "local and untracked by default",
        "pass",
        "fail",
        "skip",
        "blocked",
    ]

    for phrase in required_phrases:
        assert phrase in readme


def test_semantic_docs_guard_against_dry_run_overclaiming_and_phase3_scope_drift() -> None:
    readme = SEMANTIC_README.read_text(encoding="utf-8")

    required_phrases = [
        "mocked pytest is CI-safe",
        "not a replacement for real WwiseConsole semantic validation",
        "required 2022.1 semantic batch passes",
        "`pass: 6`, `fail: 0`, `blocked: 0`, and `skip: 0`",
        "all-version smoke evidence is also accounted for",
        "`pass: 10`, `fail: 0`, `blocked: 0`, and `skip: 0`",
        "full executor rewrite",
        "schema stuffing",
        "profiler overbuild",
        "broad docs churn",
        "silent retargeting",
    ]

    for phrase in required_phrases:
        assert phrase in readme

    stale_blocked_phrases = [
        "Current local live Task 10 evidence is blocked, not passed",
        "connection-refused WAAPI output",
        "did not return a session id",
    ]

    for phrase in stale_blocked_phrases:
        assert phrase not in readme
