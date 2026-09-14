from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"


def test_description_exposes_user_tasks_without_host_loading_instructions() -> None:
    frontmatter = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
    description = frontmatter.split("description:", 1)[1].strip()
    for task in ("query", "edit", "monitor", "subscribe", "import", "soundbank"):
        assert task in description.casefold()
    for host_detail in ("codex", "claude", "powershell", "literal-locator", "Get-Content", "`cat"):
        assert host_detail.casefold() not in description.casefold()


def test_public_loading_contract_has_no_fixed_install_path_or_launcher_retry() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    operate = (SKILL_ROOT / "references/waapi-operate.md").read_text(encoding="utf-8")
    assert ".agents\\skills\\waapi-skill" not in skill
    assert "CreateProcessAsUserW" not in skill
    assert "standalone `cat`" not in operate
    assert "UTF-8" in skill
    assert "copy_instruction.source_field" in skill
    assert "Mutations always require immutable Preview plus confirmation or policy authorization" in skill


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
        "python scripts/run.py gateway.py query-object --path-segment '<root>' --path-segment '<child>'",
        "python scripts/run.py gateway.py query-object --kind sound-sfx --include volume-db --max-results 100",
        "python scripts/run.py gateway.py --version <supported-version> query-schema [--advanced]",
        "python scripts/run.py gateway.py --version <supported-version> query-object --advanced-waql '<bounded-single-line-waql>' --include <business-field> --max-results <1..1000>",
        "python scripts/run.py gateway.py metadata types",
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
    assert "849" in coverage
    assert "Mutations always require immutable Preview plus confirmation or policy authorization" in skill
    assert "Closed transaction operations include `waapi.undoGroup`" in skill
    assert "FIXED_COMMAND_REQUIRED" in skill
    assert "WAIT_TOPIC_REQUIRED" in skill
    assert "describe <uri> --full-schema" in skill
    assert "The list defaults to at most 50 compact rows" in skill
    assert "operations --detail" in skill
    assert "never synthesize a route" in skill
    assert "run one `operations` lookup and copy its `next_command`" in skill
    assert "do not read the query reference before or after it" in skill
    assert "do not retry a rejected or failed gateway invocation" in skill
    assert "Do not run `describe` or `capabilities` first" in skill
    assert "run `request-schema` and follow its sole typed continuation" in skill
    assert "The configured exact Wwise version selects every schema" in (SKILL_ROOT / "references" / "waapi-query.md").read_text(encoding="utf-8")
    compact = " ".join(skill.split())
    assert "Read only the reference needed for the current task, once, completely and as UTF-8 text" in compact
    assert "A missing or truncated read stops the workflow" in compact
    assert "sentinel must be the final visible line" in compact
    assert (
        "python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version "
        "2022.1 operation-schema object.copy"
    ) in skill
    assert "This rule applies to fixed reads as well as transactions" in skill
    assert "do not run another command after receiving it" in skill


def test_loading_uses_supplied_skill_root_and_allows_complete_host_injection() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    compact = " ".join(skill.split())
    assert "If they are not already loaded, read `SKILL.md` from the supplied location before running a Gateway command" in compact
    assert "The Skill root is the directory containing that `SKILL.md`" in compact
    assert "not the working directory or an assumed installation path" in compact
    assert "stop instead of searching for another installation" in compact
    assert "environment's file-reading tool or a compatible shell" in compact
    assert "Get-Content -Raw -Encoding UTF8 '<absolute-file>'" in skill
    assert "Reuse complete instructions already visible in the conversation" in compact
    assert "including for Wwise CLI and project-migration requests" in skill


def test_public_skill_stops_on_launch_failure_without_harness_retry_permission() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "A structured error or shell failure stops the workflow" in skill
    assert "do not retry the Gateway command" in skill
    assert "CreateProcessAsUserW" not in skill


def test_runtime_game_object_registration_never_routes_to_object_create() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    operate = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(
        encoding="utf-8"
    )

    for document in (skill, operate):
        compact = " ".join(document.split())
        assert "runtime Game Object" in compact
        assert "`request-schema ak.soundengine.registerGameObj`" in compact
        assert "never `object.create`" in compact


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
    assert "`--query-id`" in query_reference
    assert "`--query-path-segment`" in query_reference
    assert "query-schema --advanced" in query_reference
    assert "query-object --advanced-waql" in query_reference
    assert "do not write Python" in query_reference
    assert "Raw WAQL itself is never a mutation identity" in query_flat
    assert "never alias another advanced expression onto" in query_flat
    assert "The exact-ID readback must match" in query_flat
    assert "query each distinct GUID exactly once in a separate" in query_flat
    assert "`query-object --exact-id`" in query_flat
    assert "never merge IDs" in query_flat
    assert "no unbounded mode" in query_flat
    assert "--max-results <1..1000>" in query_reference
    assert "`QUERY_OBJECT_REQUIRED`" in query_reference
    assert "gateway.py --version <supported-version> query-schema" in query_reference
    assert "business declaration" in query_reference
    assert "`describe` is for an explicit capability/schema audit" in query_reference
    assert "offline `--profile wwise-authoring-ui`" in query_reference
    assert "Use `--limit 0` only when" in query_reference
    assert "--path-segment 'Events' --path-segment 'Default Work Unit'" in query_reference
    assert "--search-text 'ExactName' --predicate name-is ExactName --max-results 1" in query_reference
    assert "Repeated `--predicate` values mean AND" in query_reference
    assert "Use `request-schema` for each URI and follow only its typed continuation" in query_reference
    assert "Use live `metadata types`" in query_reference
    assert "projection and bound are fixed" in query_reference


def test_topic_wait_policy_is_consistent_across_skill_and_query_reference() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    query = (SKILL_ROOT / "references" / "waapi-query.md").read_text(
        encoding="utf-8"
    )
    skill_flat = " ".join(skill.split())
    query_flat = " ".join(query.split())

    assert "ordinary omitted-duration default is 10 seconds" in skill_flat
    assert "Tell the user the effective policy naturally" in skill_flat
    assert "positive finite duration" in skill_flat
    assert "explicit no-time-limit bounded-wait request selects" in skill_flat
    assert "not an unlimited output stream" in skill_flat

    assert "An ordinary omitted duration uses 10 seconds" in query_flat
    assert "Explicit durations are authoritative" in query_flat
    assert "never clamp" in query_flat
    assert "`--no-timeout`, never combined with `--timeout`" in query_flat
    assert "1–64 matching events, one terminal JSON document" in query_flat
    assert "Gateway still defaults to 10 seconds" in query_flat
    assert "explicitly pass gateway-global `--timeout 120`" in query_flat
    assert "announce 120 seconds" in query_flat
    assert "ordinary vague requests to subscribe, listen, monitor" in query_flat
    assert "a requested event count or per-event/persistent output selects `stream-topic`" in query_flat
    assert "one persistent subscription" in query_flat
    assert "one compact flushed NDJSON record" in query_flat
    assert "requires an explicit maximum `--event-count <1..64>`" in query_flat
    assert "user cancellation, or a bounded low-frequency health check" in query_flat
    assert "cumulative NDJSON bytes are bounded" in query_flat
    assert "overflow fails closed instead of silently dropping an event" in query_flat
    assert "always attempts to unsubscribe" in query_flat
    assert "one terminal NDJSON record" in query_flat
    assert "Every command except `stream-topic` prints one JSON document" in skill_flat
    for intent in ("requested event count", "per-event/persistent"):
        assert intent in query


def test_query_reference_exposes_only_the_closed_original_file_match_surface() -> None:
    query_reference = (SKILL_ROOT / "references" / "waapi-query.md").read_text(
        encoding="utf-8"
    )
    query_flat = " ".join(query_reference.split())
    command = (
        "python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version "
        "2025.1 query-object --max-results 1000 "
        "--match-original-file-path '<first-complete-returned-Path>' "
        "--match-original-file-path '<second-complete-returned-Path>'"
    )

    assert command in query_flat
    assert "repeating only the final candidate option" in query_flat
    assert "Each path is limited to 1024 UTF-8 bytes" in query_flat
    assert "candidate-limit boundary" in query_flat
    assert "do not silently truncate" in query_flat
    assert "Do not add predicates, relationships, or extra business outputs" in query_flat
    assert "The fixed `id,path,originalFilePath` projection performs the complete join" in query_flat
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
    assert "The visible Preview's `next_command` is authoritative" in operate
    assert "never authorizes reconstruction" in operate
    assert "Do not call `operations`, `operation-schema`, or `request-schema` first" in operate
    assert "execute only the field named by `next_command.copy_instruction.source_field`" in operate
    assert "copying the complete string verbatim once" in operate
    assert "Windows normally selects `model_command`" in operate
    assert "encoded `shell_command` is audit/fallback unless explicitly selected" in operate
    assert "Truncated/incomplete instructions stop without inferred fallback" in operate
    assert operate.index("## Choose the phase and first Gateway command") < operate.index(
        "## Continue only from Gateway-owned commands"
    )


def test_metadata_order_follows_the_disclosed_input_mode() -> None:
    operate = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(
        encoding="utf-8"
    )

    assert "never exact live metadata evidence" in operate
    assert "remaining Composer lane's returned start preconditions" in operate
    assert "For every `business_declaration` lane, start the Draft first" in operate
    assert "returned live binding or discovery command" in operate
    assert "For `object.create`, `object.set`, and direct `audio.import`" in operate
    assert "opaque handle are the only value authority" in operate
    assert "For `object.setProperty`, `object.setReference`, and `object.setLinked`" in operate
    assert "read the schema, start, bind the target, then run returned `draft-discover-fields`" in operate
    assert "Copy one handle; never a token, scope, or type" in operate
    assert "No match stops; ambiguity needs one behavior question" in operate
    assert "For business declarations, bind only user-requested custom properties/references" in operate
    assert "common outcomes such as volume, infinite looping, output bus" in operate
    assert "use stable business fields" in operate
    assert "Bind the exact existing owner or the disclosed new-object type first" in operate
    assert "Submit business values against those handles" in operate


def test_media_gate_routes_pure_sound_hierarchies_to_object_create() -> None:
    operate = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(
        encoding="utf-8"
    )

    assert "**Media gate:**" in operate
    assert "names Sound/SFX nodes but supplies no media artifact" in operate
    assert "is a pure object hierarchy and selects `object.create`" in operate


def test_operate_lane_reuses_exact_diagnostics_and_preserves_media_paths() -> None:
    operate = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(
        encoding="utf-8"
    )

    assert "prior exact diagnostic identity is not a selected subset" in operate
    assert "reuse its GUID; do not query it again" in operate
    assert "`media_directory` and `audio_file` are opaque caller paths" in operate
    assert "never derive either from campaign/workspace cwd" in operate
    assert "For a batch, bind every target first" in operate
    assert "discover other fields for each exact target" in operate
    assert "copy the selected handles into `declare_existing_batch`" in operate
    assert "do not run field discovery" not in operate


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


def test_public_readmes_keep_setup_and_usage_user_facing() -> None:
    english = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    readmes = (english, chinese)

    for readme in readmes:
        assert "https://github.com/zcyh147/waapi-skill" in readme
        assert (
            "npx skills add zcyh147/waapi-skill --skill waapi-skill" in readme
        )
        assert "python skills/waapi-skill/scripts/run.py gateway.py config-set" in readme
        assert "python skills/waapi-skill/scripts/run.py gateway.py status" in readme
        assert "python skills/waapi-skill/scripts/run.py setup_environment.py" not in readme
        assert "read_only" in readme
        assert "ask_before_changes" in readme
        assert "allow_changes" in readme
        assert "./skills/waapi-skill/references/waapi-coverage.md" in readme
        assert "./tests/TEST_INVENTORY.md" in readme
        assert "./skills/waapi-skill/SKILL.md" in readme
        assert len(readme.splitlines()) < 220
        for internal_detail in (
            "WwiseDispatcher",
            "waapi_client",
            "SemanticPlanner",
            "draft-start object.setNotes",
            "--advanced-waql",
            "--path-segment",
            "4738",
            "4715",
            "4743",
            "4720",
        ):
            assert internal_detail not in readme

    assert "Control Wwise Authoring with natural language" in english
    assert "Agent-assisted installation" in english
    assert "Configure this Skill for Wwise 2025.1" in english
    assert "List the Events under the Default Work Unit" in english
    assert "用自然语言操作 Wwise Authoring" in chinese
    assert "由 Agent 安装" in chinese
    assert "为这个 Skill 配置 Wwise 2025.1" in chinese
    assert "列出 Default Work Unit 下的所有 Event" in chinese


def test_public_readmes_link_exact_coverage_instead_of_inlining_it() -> None:
    english = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    coverage_contract = (SKILL_ROOT / "references" / "waapi-coverage.md").read_text(encoding="utf-8")

    for readme in (english, chinese):
        for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"):
            assert f"| `{version}` |" in readme
        assert "./skills/waapi-skill/references/waapi-coverage.md" in readme
        assert "Reflected rows" not in readme
        assert "反射总行数" not in readme
        assert "4738" not in readme
        assert "4715" not in readme
        assert "4743" not in readme
        assert "4720" not in readme

    assert "Exact completed run counts and candidate commits" in coverage_contract
    assert "tests/TEST_INVENTORY.md" in coverage_contract
