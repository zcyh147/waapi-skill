from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"


def test_skill_declares_fixed_gateway_before_discovery_and_no_code_fallback() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    coverage = (SKILL_ROOT / "references" / "waapi-coverage.md").read_text(
        encoding="utf-8"
    )

    for command in (
        "python scripts/run.py gateway.py status",
        "python scripts/run.py gateway.py config-show",
        "python scripts/run.py gateway.py config-set --wwise-version 2022.1 --waapi-host 127.0.0.1 --waapi-port 8080 --project-modification-policy ask_before_changes",
        "python scripts/run.py gateway.py config-set --reset",
        "python scripts/run.py gateway.py buses",
        "python scripts/run.py gateway.py selected",
        "python scripts/run.py gateway.py capabilities --all-versions --summary-only",
        "python scripts/run.py gateway.py capabilities --all-versions --query object.get --limit 20",
        "python scripts/run.py gateway.py describe <uri> --all-versions",
        "python scripts/run.py gateway.py request-schema ak.wwise.waapi.getFunctions",
        "python scripts/run.py gateway.py request-schema ak.wwise.waapi.getTopics",
        "python scripts/run.py gateway.py query-object --path '<exact-object-path>' --return-field id --return-field name --return-field type --return-field path",
        "python scripts/run.py gateway.py query-object --type Event --take 100",
        "python scripts/run.py gateway.py --version <supported-version> query-schema [--advanced]",
        "python scripts/run.py gateway.py --version <supported-version> query-object (--typed-structured <typed-facts-from-query-schema> | --typed-advanced --waql '<bounded-single-line-waql>' <typed-fields-from-query-schema>)",
        "python scripts/run.py gateway.py metadata types --summary-only",
        "python scripts/run.py gateway.py wait-topic <topic-uri>",
        "python scripts/run.py gateway.py topic-schema <topic-uri>",
        "python scripts/run.py gateway.py --timeout <positive-finite-seconds> wait-topic <topic-uri>",
        "python scripts/run.py gateway.py wait-topic <topic-uri> --no-timeout",
        "python scripts/run.py gateway.py stream-topic <topic-uri>",
        "python scripts/run.py gateway.py --timeout <positive-finite-seconds> stream-topic <topic-uri>",
        "python scripts/run.py gateway.py operations",
        "python scripts/run.py gateway.py operation-schema object.create",
        "python scripts/run.py gateway.py operation-schema object.set",
        "python scripts/run.py gateway.py operation-schema waapi.undoGroup",
        "python scripts/run.py gateway.py --version 2022.1 operation-schema object.copy",
    ):
        assert command in skill
    assert "before `ls`, `find`, `rg`" in skill
    assert "inline Python" in skill
    assert "unsupported_by_skill_interface" in skill
    assert "814" in coverage
    assert "808 packaged route rows" in coverage
    assert "require a live Authoring host" in coverage
    assert "824" in coverage
    assert "Mutations always require immutable Preview plus confirmation or policy authorization" in skill
    assert "Closed transaction operations include `waapi.undoGroup`" in skill
    assert "FIXED_COMMAND_REQUIRED" in skill
    assert "WAIT_TOPIC_REQUIRED" in skill
    assert "describe <uri> --full-schema" in skill
    assert "The list defaults to at most 50 compact rows" in skill
    assert "operations --detail" in skill
    assert "do not read the query reference before or after it" in skill
    assert "do not retry a rejected or failed gateway invocation" in skill
    assert "Do not run `describe` or `capabilities` first" in skill
    assert "run `request-schema` and follow its sole typed continuation" in skill
    assert "The configured exact Wwise version selects every schema" in (SKILL_ROOT / "references" / "waapi-query.md").read_text(encoding="utf-8")
    assert "Read each later named lane reference exactly once in its own shell call" in skill
    assert "native Windows uses `Get-Content -Raw -Encoding UTF8 '<reference>'`" in skill
    assert ".agents\\skills\\waapi-skill\\references\\<file>.md" in skill
    assert "Do not probe with `wc -l`, `ls`, `rg`, `find`, `stat`, or `test`" in skill
    assert "never split a reference" in skill
    assert (
        "python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version "
        "2022.1 operation-schema object.copy"
    ) in skill
    assert "This rule applies to fixed reads as well as transactions" in skill
    assert "do not run another command after receiving it" in skill


def test_cli_bootstrap_uses_only_the_literal_injected_skill_locator() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = skill.split("---", 2)[1]

    assert "Read only the injected SKILL.md locator first" in frontmatter
    assert "never search for or infer it" in frontmatter
    assert "Choose by command host, not Wwise/Codex version or path spelling" in frontmatter
    assert "POSIX uses `cat '<literal-locator>'` or exact `sed -n '1,$p'" in frontmatter
    assert "Get-Content -Raw -Encoding UTF8 '<literal-locator>'" in frontmatter
    assert "Never cross-use/wrap these forms" in frontmatter
    assert "combine the read with unrelated action" in frontmatter
    assert "Bootstrap only from the injected `SKILL.md` locator" in skill
    assert "Never guess a repository-relative `skills/waapi-skill` path" in skill
    for forbidden_probe in ("`pwd`", "`git status`", "`ls`", "`find`", "`rg`"):
        assert forbidden_probe in skill
    assert "including for Wwise CLI and project-migration requests" in skill


def test_query_reference_has_no_raw_client_fallback() -> None:
    query_reference = (SKILL_ROOT / "references" / "waapi-query.md").read_text(encoding="utf-8")
    query_flat = " ".join(query_reference.split())

    assert "There is no raw-client fallback" in query_reference
    assert "request-schema <uri>" in query_reference
    assert "TRANSACTION_REQUIRED" in query_reference
    assert "FIXED_COMMAND_REQUIRED" in query_reference
    assert "WAIT_TOPIC_REQUIRED" in query_reference
    assert "UNSUPPORTED_BY_SKILL_INTERFACE" in query_reference
    assert "gateway.py query-object" in query_reference
    assert "`--query` means an existing Wwise Query Editor object" in query_reference
    assert "query-schema --advanced" in query_reference
    assert "query-object --typed-advanced" in query_reference
    assert "do not write Python" in query_reference
    assert "Raw WAQL itself is never a mutation identity" in query_flat
    assert "never alias another advanced expression onto" in query_flat
    assert "The exact-ID readback must match" in query_flat
    assert "`--all-results`" in query_reference
    assert "between `0` and `1000`" in query_reference
    assert "`QUERY_OBJECT_REQUIRED`" in query_reference
    assert "gateway.py --version <supported-version> query-schema" in query_reference
    assert "typed-structured continuation" in query_reference
    assert "Add `--full-schema` only when" in query_reference
    assert "at most 50 compact rows by default" in query_reference
    assert "Use `--limit 0` only when" in query_reference
    assert "--path '\\Events\\Default Work Unit'" in query_reference
    assert "--path '\\\\Events\\\\Default Work Unit'" not in query_reference
    assert "--search 'ExactName' --where name = string ExactName --take 1" in query_reference
    assert "`=` is exact equality" in query_reference
    assert "`:` is" in query_reference and "a contains/match predicate" in query_reference
    assert "Use `request-schema` for each URI and follow only its typed continuation" in query_reference
    assert "metadata types --summary-only" in query_reference
    assert "compact-serialize that object exactly" in query_reference


def test_topic_wait_policy_is_consistent_across_skill_reference_and_readmes() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    query = (SKILL_ROOT / "references" / "waapi-query.md").read_text(
        encoding="utf-8"
    )
    english = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    skill_flat = " ".join(skill.split())
    query_flat = " ".join(query.split())

    assert "ordinary omitted-duration default is 10 seconds" in skill_flat
    assert "tell the user the effective policy naturally" in skill_flat
    assert "positive finite duration" in skill_flat
    assert "explicit no-time-limit bounded-wait request selects" in skill_flat
    assert "not an unlimited output stream" in skill_flat

    assert "An ordinary omitted duration uses 10 seconds" in query_flat
    assert "A user-supplied positive finite duration is authoritative" in query_flat
    assert "Do not silently clamp it" in query_flat
    assert "Do not combine the two flags" in query_flat
    assert "collection still stops at 1–64 matching events" in query_flat
    assert "the command still returns one terminal JSON document" in query_flat
    assert "gateway itself keeps the ordinary 10-second omitted-duration default" in query_flat
    assert "explicitly pass gateway-global `--timeout 120`" in query_flat
    assert "tell the user that this subscription will use 120 seconds" in query_flat
    assert "ordinary vague requests to subscribe, listen, monitor" in query_flat
    assert "only when the user explicitly asks for a stream" in query_flat
    assert "one persistent subscription" in query_flat
    assert "one compact flushed NDJSON record" in query_flat
    assert (
        "by default continues until the user cancels it or a bounded "
        "low-frequency health check detects"
    ) in query_flat
    assert "overflow fails closed instead of silently dropping an event" in query_flat
    assert "always attempts to unsubscribe" in query_flat
    assert "one terminal NDJSON record" in query_flat
    assert "Every command except `stream-topic` prints one JSON document" in skill_flat
    for intent in (
        "stream",
        "continuous",
        "persistent",
        "实时逐条",
        "流式",
        "持续",
        "一直监听",
        "不要收到后退出",
    ):
        assert intent in query

    for readme in (english, chinese):
        assert "--timeout" in readme
        assert "--no-timeout" in readme
        assert "256 KiB" in readme
    assert "gateway default for every Topic wait is 10 seconds" in english
    assert "not an unlimited output stream" in english
    assert "explicitly invokes the same gateway with `--timeout 120`" in english
    assert "120 seconds is a Skill policy, not a second gateway default" in english
    assert "所有 Topic wait 的 gateway 默认值都是 10 秒" in chinese
    assert "并不是无限输出流" in chinese
    assert "显式给同一个 gateway 传入 `--timeout 120`" in chinese
    assert "这是 Skill 的选择，不是另一套 gateway 默认值" in chinese


def test_query_reference_exposes_only_the_closed_original_file_match_surface() -> None:
    query_reference = (SKILL_ROOT / "references" / "waapi-query.md").read_text(
        encoding="utf-8"
    )
    query_flat = " ".join(query_reference.split())
    command = (
        "python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version "
        "2025.1 query-object --type AudioFileSource --take 1000 "
        "--match-original-file-path '<first-complete-returned-Path>' "
        "--match-original-file-path '<second-complete-returned-Path>'"
    )

    assert command in query_flat
    assert "repeating only the final candidate option" in query_flat
    assert "Each path is limited to 1024 UTF-8 bytes" in query_flat
    assert "candidate-limit boundary" in query_flat
    assert "do not silently truncate" in query_flat
    assert "Do not add `--where`, `--select`, `--all-results`, or `--return-field`" in query_flat
    assert "never run the old unfiltered 1000-row AudioFileSource projection" in query_flat
    assert "--return-field originalFilePath" not in query_reference
    assert "A 1000-row scan returns `ORIGINAL_FILE_REFERENCE_SCAN_INCOMPLETE`" in query_flat
    assert "with no `agent_result`" in query_flat


def test_existing_transaction_continuation_precedes_named_operation_schema() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    operate = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(encoding="utf-8")

    assert "An existing transaction continuation takes precedence over the named-operation rule" in skill
    assert "it requires the transaction id" in skill
    assert "an artifact hash alone is not a transaction lookup key" in skill
    assert "run `transaction-show <transaction-id> --summary-only` first" in skill
    assert "skip schema discovery and start with `transaction-show`" in skill
    assert "An existing transaction continuation always outranks operation selection" in operate
    assert "an artifact hash is not a lookup key" in operate
    assert "transaction-show <transaction-id> --summary-only" in operate
    assert "Do not call `operations`, `operation-schema`, or `request-schema` first" in operate
    assert "execute only the field named by `next_command.copy_instruction.source_field`" in operate
    assert "copy that entire string verbatim as one shell tool call" in operate
    assert "normally selects the short `model_command`" in operate
    assert "encoded `shell_command` remains an audit/fallback representation" in operate
    assert "never infer fallback from the visible field" in operate
    assert operate.index("## Choose the phase and first Gateway command") < operate.index(
        "## Continue only from Gateway-owned commands"
    )


def test_normal_change_prose_stays_business_facing() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    operate = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(
        encoding="utf-8"
    )

    for document in (skill, operate):
        assert (
            "Normal prose covers only objects, changes, results, risks, and whether "
            "anything changed."
            in document
        )
        assert (
            "Hide API/operation names, Draft/transaction internals, ids, hashes, tokens, "
            "states, and commands."
            in document
        )
        assert "Keep exact `agent_result` machine-readable" in document


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
            "python scripts/run.py gateway.py typed-operation object.setNotes --apply",
            "python scripts/run.py gateway.py transaction-show <transaction-id> --summary-only",
            "python scripts/run.py gateway.py confirm <transaction-id> --confirmation-token <confirmation-token>",
            "python scripts/run.py gateway.py execute <transaction-id>",
            "python scripts/run.py gateway.py verify <transaction-id>",
        ):
            assert command in readme
        assert "state-bound confirmation token" in readme or "与当前状态绑定的确认 token" in readme
        assert readme.index("python scripts/run.py gateway.py typed-operation object.setNotes --apply") < readme.index(
            "python scripts/run.py gateway.py transaction-show <transaction-id> --summary-only"
        )
        assert readme.index(
            "python scripts/run.py gateway.py transaction-show <transaction-id> --summary-only"
        ) < readme.index(
            "python scripts/run.py gateway.py confirm <transaction-id> --confirmation-token <confirmation-token>"
        )
        assert readme.count(
            "python scripts/run.py gateway.py confirm <transaction-id> --artifact-hash"
        ) == 0
        for internal_route in ("WwiseDispatcher", "waapi_client", "SemanticPlanner", "semantic planner path"):
            assert internal_route not in readme
        assert "inline Python" in readme
        assert "helper script" in readme

    assert "Manifest reflection is discovery, not permission" in readmes[0]
    assert "request-schema` exposes only reviewed exact-version typed routes" in readmes[0]
    assert "Manifest 反射只用于发现能力，不等于授权执行" in readmes[1]
    assert "request-schema` 只开放经过审核、精确版本绑定且结果有界的 typed route" in readmes[1]


def test_public_readmes_publish_exact_five_version_api_coverage() -> None:
    english = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    coverage_contract = (SKILL_ROOT / "references" / "waapi-coverage.md").read_text(encoding="utf-8")

    expected_rows = (
        "| `2021.1` | 126 | 124 | 97 | 27 | 2 |",
        "| `2022.1` | 144 | 142 | 110 | 32 | 2 |",
        "| `2023.1` | 181 | 179 | 147 | 32 | 2 |",
        "| `2024.1` | 178 | 178 | 148 | 30 | 0 |",
        "| `2025.1` | 185 | 185 | 154 | 31 | 0 |",
    )
    for readme in (english, chinese):
        for row in expected_rows:
            assert row in readme
        assert "**814**" in readme
        assert "**808**" in readme
        assert "**656**" in readme
        assert "**152**" in readme
        assert "**6**" in readme
        assert "3368" in readme
        assert "./skills/waapi-skill/references/waapi-coverage.md" in readme

    assert "198 unique routed WAAPI URIs" in english
    assert "198 个唯一已封装 WAAPI URI" in chinese
    assert "still require a live Authoring host" in " ".join(english.split())
    assert "仍要求实时宿主为 Authoring" in " ".join(chinese.split())
    assert "not a claim that all 808 rows have been exercised against a real Wwise process" in english
    assert "不等于已经在真实 Wwise 进程中逐一运行了全部 808 行" in chinese
    assert "currently contains 3368 passing tests" in coverage_contract
