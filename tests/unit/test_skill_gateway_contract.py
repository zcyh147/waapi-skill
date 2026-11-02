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

    for command in ("status", "config-show", "buses", "selected", "operations"):
        assert f"python scripts/run.py gateway.py {command}" in skill
    assert "before `ls`, `find`, `rg`" in skill
    assert "inline Python" in skill
    assert "never synthesize a route" in skill
    assert "Mutations always require immutable Preview plus confirmation or policy authorization" in skill
    assert "run one `operations` lookup" in skill
    assert "run `request-schema` and follow its sole typed continuation" in skill
    assert "typed continuations still require exact copying" in skill
    assert "A missing or truncated read stops the workflow" in " ".join(skill.split())
    assert "Never reconstruct fields or run another command" in skill


def test_loading_uses_supplied_skill_root_and_allows_complete_host_injection() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    compact = " ".join(skill.split())
    assert "Read the supplied `SKILL.md` completely before Gateway use unless already loaded" in compact
    assert "The directory containing `SKILL.md` is the Skill root" in compact
    assert "Resolve `scripts/` and `references/` there" in compact
    assert "Missing location or incomplete content stops; never search another installation" in compact
    assert "environment's file-reading tool or a compatible shell" in compact
    assert "Get-Content -Raw -Encoding UTF8 '<absolute-file>'" in skill
    assert "Reuse complete instructions already visible in the conversation" in compact
    assert "including for Wwise CLI and project-migration requests" in skill


def test_public_skill_distinguishes_structured_recovery_from_incomplete_launch_failure() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "A shell failure without complete JSON remains a stop" in skill
    assert "read_only_continuation_allowed" in skill
    assert "without another permission question" in skill
    assert "never replay the original write" in skill
    assert "Unresolved cleanup" in skill
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
    query = (SKILL_ROOT / "references" / "waapi-query.md").read_text(encoding="utf-8")
    compact = " ".join(query.split())

    for boundary in ("There is no raw-client fallback", "do not write Python",
                     "TRANSACTION_REQUIRED", "FIXED_COMMAND_REQUIRED", "WAIT_TOPIC_REQUIRED"):
        assert boundary in query
    assert "request-schema <uri>" in query
    assert "query-schema --advanced" in query
    assert "Raw WAQL itself is never a mutation identity" in compact
    assert "The exact-ID readback must match" in compact
    assert "`query-object --exact-id`" in compact
    assert "no unbounded mode" in compact
    assert "--max-results <1..1000>" in query


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
        "python /absolute/path/to/waapi-skill/scripts/run.py gateway.py "
        "query-object --max-results 1000 "
        "--match-original-file-path '<first-complete-returned-Path>' "
        "--match-original-file-path '<second-complete-returned-Path>'"
    )

    assert command in query_flat
    assert "repeating the candidate option" in query_flat
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
    assert "an artifact hash alone is not a transaction lookup key" in skill
    assert "transaction-show <transaction-id> --summary-only" in operate
    assert "Existing transactions outrank operation selection" in operate
    assert "Copy only the visible Preview's authoritative `next_command`" in operate
    assert "execute only the field named by `next_command.copy_instruction.source_field`" in operate
    assert "copying the complete string verbatim once" in operate
    assert "encoded `shell_command` is audit/fallback unless explicitly selected" in operate
    assert "Truncated/incomplete instructions stop without inferred fallback" in operate


def test_metadata_order_follows_the_disclosed_input_mode() -> None:
    operate = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(encoding="utf-8")

    assert "never exact live metadata evidence" in operate
    assert "Business Draft precedes binding/discovery" in operate
    assert "Composer stays metadata-first" in operate
    assert operate.index("1. Bind the exact existing owner") < operate.index("2. Run the returned discovery once")
    assert "Submit business values against those handles" in operate
    assert "For business declarations, bind only user-requested custom properties/references" in operate


def test_media_gate_routes_pure_sound_hierarchies_to_object_create() -> None:
    operate = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(
        encoding="utf-8"
    )

    assert "**Media gate:**" in operate
    assert "names Sound/SFX nodes but supplies no media artifact" in operate
    assert "is a pure object hierarchy and selects `object.create`" in operate


def test_operate_lane_reuses_exact_diagnostics_and_preserves_media_paths() -> None:
    operate = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(encoding="utf-8")

    assert "reuse its GUID as an `id` selector" in operate
    assert "Gateway revalidates it" in operate
    assert "`media_directory`/`audio_file` are opaque caller paths, never cwd-derived" in operate
    assert "For a batch, bind every target first" in operate
    assert "discover other fields for each exact target" in operate
    assert "copy the selected handles into `declare_existing_batch`" in operate


def test_normal_change_prose_stays_business_facing() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    operate = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(encoding="utf-8")

    assert "In prose, describe objects, changes, results, and risks." in skill
    assert "Hide API names, Draft/transaction internals, ids, hashes, tokens, states, and commands" in skill
    assert "preserve machine `agent_result`" in skill
    assert "serialize the successful Gateway `agent_result` verbatim" in operate


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
        for internal_detail in (
            "WwiseDispatcher",
            "waapi_client",
            "SemanticPlanner",
            "draft-start object.setNotes",
            "--advanced-waql",
            "--path-segment",
        ):
            assert internal_detail not in readme

    assert "Control Wwise Authoring with natural language" in english
    assert "用自然语言操作 Wwise Authoring" in chinese


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
