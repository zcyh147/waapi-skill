from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"


def test_skill_declares_fixed_gateway_before_discovery_and_no_code_fallback() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    for command in (
        "python scripts/run.py gateway.py status",
        "python scripts/run.py gateway.py config-show",
        "python scripts/run.py gateway.py config-set --wwise-version 2022.1 --waapi-host 127.0.0.1 --waapi-port 8080 --project-modification-policy preview_then_confirm",
        "python scripts/run.py gateway.py config-set --reset",
        "python scripts/run.py gateway.py buses",
        "python scripts/run.py gateway.py selected",
        "python scripts/run.py gateway.py capabilities --all-versions --summary-only",
        "python scripts/run.py gateway.py capabilities --all-versions --query object.get --limit 20",
        "python scripts/run.py gateway.py describe <uri> --all-versions",
        "python scripts/run.py gateway.py --version <supported-version> call ak.wwise.waapi.getFunctions --args-json '{}' --options-json '{}'",
        "python scripts/run.py gateway.py --version <supported-version> call ak.wwise.waapi.getTopics --args-json '{}' --options-json '{}'",
        "python scripts/run.py gateway.py query-object --path '<exact-object-path>' --return-field id --return-field name --return-field type --return-field path",
        "python scripts/run.py gateway.py query-object --type Event --take 100",
        "python scripts/run.py gateway.py metadata types --summary-only",
        "python scripts/run.py gateway.py --timeout 10 wait-topic <topic-uri>",
        "python scripts/run.py gateway.py operations",
        "python scripts/run.py gateway.py operation-schema object.create",
        "python scripts/run.py gateway.py operation-schema waapi.call",
        "python scripts/run.py gateway.py operation-schema waapi.undoGroup",
        "python scripts/run.py gateway.py --version 2022.1 operation-schema object.copy",
    ):
        assert command in skill
    assert "before `ls`, `find`, `rg`" in skill
    assert "inline Python" in skill
    assert "unsupported_by_skill_interface" in skill
    assert "A fail-closed execution registry assigns all 814 reflected version/API rows" in skill
    assert "769 executable rows and 45 explicit exclusions" in skill
    assert "each `transaction_operation` row requires immutable preview/confirmation through its declared closed operation" in skill
    assert "`waapi.undoGroup` for the three Undo members, `waapi.call` otherwise" in skill
    assert "FIXED_COMMAND_REQUIRED" in skill
    assert "WAIT_TOPIC_REQUIRED" in skill
    assert "--dry-run" in skill
    assert "describe <uri> --full-schema" in skill
    assert "The list defaults to at most 50 compact rows" in skill
    assert "operations --detail" in skill
    assert "do not read the query reference before or after it" in skill
    assert "do not retry a rejected or failed gateway invocation" in skill
    assert "Do not run `describe` or `capabilities` first" in skill
    assert "run exactly one matching `call` command" in skill
    assert "replacing `<supported-version>` with the exact requested or connected Wwise version" in skill
    assert "except for an explicit exact reflection call covered by the fast route above" in skill
    assert "read any later named lane reference exactly once with `cat /absolute/path/to/waapi-skill/references/<file>.md`" in skill
    assert "Never run `wc -l`, `ls`, `rg`, `find`, `stat`, `test`" in skill
    assert "never split one reference across multiple reads" in skill
    assert (
        "python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version "
        "2022.1 operation-schema object.copy"
    ) in skill
    assert "This rule applies to fixed reads as well as transactions" in skill
    assert "do not run another command after receiving it" in skill


def test_query_reference_has_no_raw_client_fallback() -> None:
    query_reference = (SKILL_ROOT / "references" / "waapi-query.md").read_text(encoding="utf-8")

    assert "There is no raw-client fallback" in query_reference
    assert "gateway.py call <uri>" in query_reference
    assert "TRANSACTION_REQUIRED" in query_reference
    assert "FIXED_COMMAND_REQUIRED" in query_reference
    assert "WAIT_TOPIC_REQUIRED" in query_reference
    assert "UNSUPPORTED_BY_SKILL_INTERFACE" in query_reference
    assert "preferred_route: manifest_dispatch" in query_reference
    assert "broader reads return `TRANSACTION_REQUIRED` rather than being inferred safe from a `get`-shaped name" in query_reference
    assert "not an open raw-call surface" in query_reference
    assert "gateway.py query-object" in query_reference
    assert "gateway.py wait-topic" in query_reference
    assert "`--query` means an existing Wwise Query Editor object" in query_reference
    assert "It never accepts raw WAQL" in query_reference
    assert "`this` and `owner` remain outside the packaged boundary" in query_reference
    assert "requires either `--take N`" in query_reference
    assert "`--all-results`" in query_reference
    assert "between `0` and `1000`" in query_reference
    assert "`QUERY_OBJECT_REQUIRED`" in query_reference
    assert "fixed `buses` command uses `take 1000`" in query_reference
    assert "invalid response shape is a structured error" in query_reference
    assert "Add `--full-schema` only when" in query_reference
    assert "at most 50 compact rows by default" in query_reference
    assert "Use `--limit 0` only when" in query_reference
    assert "--path '\\Events\\Default Work Unit'" in query_reference
    assert "--path '\\\\Events\\\\Default Work Unit'" not in query_reference
    assert "--search 'ExactName' --where-json '{\"field\":\"name\",\"operator\":\"=\",\"value\":\"ExactName\"}' --take 1" in query_reference
    assert "`=` is exact equality and `:` is a contains/match predicate" in query_reference
    assert "run that one `call` directly without `describe` or `capabilities`" in query_reference
    assert "only when `describe` reports" not in query_reference
    assert "metadata types --summary-only" in query_reference
    assert "compact-serialize that object exactly" in query_reference
    assert "repeat the metadata command after success" in query_reference


def test_existing_transaction_continuation_precedes_named_operation_schema() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    operate = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(encoding="utf-8")

    assert "An existing transaction continuation takes precedence over the named-operation rule" in skill
    assert "it requires the transaction id" in skill
    assert "an artifact hash alone is not a transaction lookup key" in skill
    assert "run `transaction-show <transaction-id> --summary-only` first" in skill
    assert "skip `operation-schema` and `preview`; start with `transaction-show`" in skill
    assert "An existing transaction continuation outranks the named-operation rule" in operate
    assert "A transaction id is required: an artifact hash alone is not a lookup key" in operate
    assert "The first gateway command is `transaction-show <transaction-id> --summary-only`" in operate
    assert "Do not call `operations`, `operation-schema`, or `preview` first" in operate
    assert operate.index("## Choose the transaction phase first") < operate.index("## Closed transaction flow")


def test_public_readmes_route_users_only_through_the_packaged_gateway() -> None:
    readmes = (
        (REPO_ROOT / "README.md").read_text(encoding="utf-8"),
        (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8"),
    )

    for readme in readmes:
        for command in (
            "python scripts/run.py gateway.py status",
            "python scripts/run.py gateway.py query-object",
            "python scripts/run.py gateway.py operation-schema object.setNotes",
            "python scripts/run.py gateway.py preview",
            "python scripts/run.py gateway.py confirm <transaction-id> --artifact-hash <artifact-hash>",
            "python scripts/run.py gateway.py execute <transaction-id>",
            "python scripts/run.py gateway.py verify <transaction-id>",
        ):
            assert command in readme
        for internal_route in ("WwiseDispatcher", "waapi_client", "SemanticPlanner", "semantic planner path"):
            assert internal_route not in readme
        assert "inline Python" in readme
        assert "helper script" in readme
        assert "--dry-run" in readme

    assert "Manifest reflection is discovery, not permission" in readmes[0]
    assert "immutable reviewed allowlists" in readmes[0]
    assert "Manifest 反射只用于发现能力，不等于授权执行" in readmes[1]
    assert "immutable reviewed allowlist" in readmes[1]


def test_public_readmes_publish_exact_five_version_api_coverage() -> None:
    english = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    coverage_contract = (SKILL_ROOT / "references" / "waapi-coverage.md").read_text(encoding="utf-8")

    expected_rows = (
        "| `2021.1` | 126 | 119 | 93 | 26 | 7 |",
        "| `2022.1` | 144 | 137 | 106 | 31 | 7 |",
        "| `2023.1` | 181 | 170 | 139 | 31 | 11 |",
        "| `2024.1` | 178 | 168 | 139 | 29 | 10 |",
        "| `2025.1` | 185 | 175 | 145 | 30 | 10 |",
    )
    for readme in (english, chinese):
        for row in expected_rows:
            assert row in readme
        assert "**814**" in readme
        assert "**769**" in readme
        assert "**622**" in readme
        assert "**147**" in readme
        assert "**45**" in readme
        assert "957" in readme
        assert "./skills/waapi-skill/references/waapi-coverage.md" in readme

    assert "188 unique executable WAAPI URIs" in english
    assert "188 个唯一可执行 WAAPI URI" in chinese
    assert "not a claim that all 769 rows have been exercised against a real Wwise process" in english
    assert "不等于已经在真实 Wwise 进程中逐一运行了全部 769 行" in chinese
    assert "currently contains 957 passing tests" in coverage_contract
