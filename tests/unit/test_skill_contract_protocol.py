from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
SKILL = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
QUERY = (SKILL_ROOT / "references" / "waapi-query.md").read_text(encoding="utf-8")
SETUP = (SKILL_ROOT / "references" / "waapi-setup.md").read_text(encoding="utf-8")
OPERATE = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(encoding="utf-8")
COVERAGE = (SKILL_ROOT / "references" / "waapi-coverage.md").read_text(encoding="utf-8")
DOMAIN_CONTEXT = (REPO_ROOT / "CONTEXT.md").read_text(encoding="utf-8")
COMPOSER_ADR = (
    REPO_ROOT / "docs" / "adr" / "0001-gateway-owned-operation-composition.md"
).read_text(encoding="utf-8")
TYPED_INPUT_ADR = (
    REPO_ROOT / "docs" / "adr" / "0002-single-model-facing-typed-input.md"
).read_text(encoding="utf-8")


def test_composer_domain_terms_and_architecture_decision_are_frozen() -> None:
    for term in (
        "Business Orchestration",
        "Operation Composer",
        "Operation Draft",
        "Canonical OperationRequest",
        "Change Preview",
    ):
        assert term in DOMAIN_CONTEXT
        assert term in COMPOSER_ADR
    for term in (
        "Gateway-Owned Request Construction",
        "Typed Request Construction Core",
        "Historical OperationRequest Record",
    ):
        assert term in DOMAIN_CONTEXT
    assert "Legacy JSON Adapter" not in DOMAIN_CONTEXT
    assert "Legacy JSON Adapter" in COMPOSER_ADR
    assert "Status: Superseded in part" in COMPOSER_ADR
    assert "a Legacy lane cannot start a new Operation Draft" in COMPOSER_ADR
    assert "no planner model is embedded" in COMPOSER_ADR
    assert "Normal user-facing prose describes objects" in COMPOSER_ADR
    assert "Status: Accepted" in TYPED_INPUT_ADR
    assert "one model-facing typed input system" in TYPED_INPUT_ADR


def test_common_reads_use_closed_gateway_before_optional_references() -> None:
    assert SKILL.index("## Fixed gateway commands") < SKILL.index("## Routing")
    assert "Treat gateway JSON as authoritative" in SKILL
    assert "Every gateway command must leave its complete JSON visible" in SKILL
    assert "never suppress or redirect its output" in SKILL
    assert "request a zero/short tool-output budget" in SKILL
    assert "continue from the shell exit code alone" in SKILL
    assert "If no complete JSON is visible, stop" in SKILL
    assert "`shell_tool_timeout_ms`" in SKILL
    assert "outer shell tool call" in SKILL
    assert "never add it to the command argv" in SKILL
    assert "Read one lane reference only when fixed commands are insufficient" in SKILL
    assert "There is no raw-client fallback" in QUERY


def test_dynamic_draft_guidance_distinguishes_complete_json_from_incomplete_construction() -> None:
    compact = " ".join(OPERATE.split())
    assert (
        "`construction_state.complete:false` and compact action receipts are "
        "complete JSON"
    ) in compact
    assert "Follow `next_command_decision`" in compact
    assert "only an exact `business_value_pointer` authorizes it" in compact
    assert "schema alone never does" in compact
    assert "never reuse handles" in compact
    assert "return to the outermost response; parent fact before children" in compact
    assert "`completion_candidate`" in compact
    assert "never `draft-apply --action check`" in compact


def test_machine_readable_agent_result_is_terminal_for_fixed_reads_and_transactions() -> None:
    assert "any successful gateway payload contains `agent_result`" in SKILL
    assert "This rule applies to fixed reads as well as transactions" in SKILL
    assert "Do not reconstruct its fields from the prompt, `normalized`" in SKILL
    assert "do not run another command after receiving it" in SKILL
    assert "metadata types --summary-only" in QUERY
    assert "compact-serialize that object exactly" in QUERY


def test_media_pool_reference_classification_uses_one_closed_versioned_query() -> None:
    section = QUERY.split("### Closed original-file reference classification", 1)[1].split(
        "## Object queries", 1
    )[0]
    section_flat = " ".join(section.split())
    command = (
        "gateway.py --version 2025.1 query-object --type AudioFileSource "
        "--take 1000 --match-original-file-path "
        "'<first-complete-returned-Path>' --match-original-file-path "
        "'<second-complete-returned-Path>'"
    )

    assert "Wwise `2025.1`-only" in section
    assert command in section_flat
    assert "between 1 and 64 candidate rows" in section_flat
    assert "With zero candidates" in section_flat
    assert "With more than 64" in section_flat
    assert "do not silently truncate, split the candidates across repeated scans" in section_flat
    assert "sort those strings lexicographically" in section_flat
    assert "drive-absolute" in section_flat
    assert "ordinary UNC path" in section_flat
    assert "POSIX-absolute" in section_flat
    assert "Do not pre-normalize or de-duplicate" in section_flat
    assert "normalizes slash spelling and drive/UNC case" in section_flat
    assert "keeps POSIX case significant" in section_flat
    assert "Do not add `--where`, `--select`, `--all-results`, or `--return-field`" in section_flat
    assert "fixed `id,path,originalFilePath` projection" in section_flat
    assert "emits no raw AudioFileSource inventory" in section_flat
    assert "never perform this join in model-authored code" in QUERY


def test_media_pool_reference_classification_documents_terminal_result_and_boundaries() -> None:
    section = QUERY.split("### Closed original-file reference classification", 1)[1].split(
        "## Object queries", 1
    )[0]
    section_flat = " ".join(section.split())

    for phrase in (
        "`agent_result` as its final top-level field",
        "`waapi-skill.original-file-reference-match/v1`",
        "`scan_complete: true`",
        "`scanned_audio_source_count`",
        "`scan_limit: 1000`",
        "one `candidates` entry for every input path in the same order",
        "exact full-scan `reference_count`",
        "at most four `{id,path}` details",
        "sorted by path case-insensitively and then id case-insensitively",
        "`references_truncated: true` means only that detail list was shortened",
        "An unreferenced entry has count `0`",
        "`ORIGINAL_FILE_REFERENCE_SCAN_INCOMPLETE` with no `agent_result`",
        "normalized candidate collisions",
        "proves no unreferenced claim",
    ):
        assert phrase in section_flat
    assert "Classify only when the outer command succeeds" in section_flat
    assert "terminal result says `scan_complete: true`" in section_flat
    assert "Stop instead of retrying with a broader query, another batch" in section_flat
    assert "direct `WaapiClient`, inline Python, or a helper file" in section_flat


def test_initial_skill_bootstrap_is_the_only_combined_read_exception() -> None:
    frontmatter = SKILL.split("---", 2)[1]

    assert (
        "make that host-native injected `SKILL.md` read the sole first shell action"
        in SKILL
    )
    assert "Never combine it with `pwd`, `git`, `rg`, `ls`, `find`, `printf`" in SKILL
    assert "Choose by command host, not Wwise/Codex version or path spelling" in frontmatter
    assert "POSIX uses `cat '<literal-locator>'` or exact `sed -n '1,$p'" in frontmatter
    assert (
        "native Windows uses exact "
        "`Get-Content -Raw -Encoding UTF8 '<literal-locator>'`" in frontmatter
    )
    assert "Never cross-use/wrap these forms" in frontmatter
    assert "combine the read with unrelated action" in frontmatter
    assert "Read each later named lane reference exactly once" in SKILL
    assert "spans the visible task, not each turn" in SKILL
    assert "never reread an already-visible file" in SKILL
    assert "same literal file" in SKILL
    assert "Only POSIX may bootstrap the initial complete `SKILL.md`" in SKILL
    assert "this is the only combined read allowed" in SKILL
    assert "Never combine any other command" in SKILL


def test_skill_frontmatter_uses_the_closed_plain_scalar_shape() -> None:
    frontmatter = SKILL.split("---", 2)[1].strip().splitlines()

    assert len(frontmatter) == 2
    assert frontmatter[0] == "name: waapi-skill"
    assert frontmatter[1].startswith("description: ")
    description = frontmatter[1].removeprefix("description: ")
    assert description
    # This Skill deliberately uses one unquoted plain YAML scalar.  A colon
    # followed by whitespace would start a nested mapping and make the Skill
    # unloadable, so keep that syntax outside the value.
    assert ": " not in description
    assert "\t" not in description


def test_skill_entry_fits_the_fresh_codex_bootstrap_window() -> None:
    assert len(SKILL.splitlines()) <= 230
    assert len(SKILL.encode("utf-8")) <= 35_000
    assert len(SKILL.replace("\n", "\r\n").encode("utf-8")) <= 35_000


def test_exact_identity_query_is_complete_in_entry_file() -> None:
    command = (
        "query-object --path '<exact-object-path>' --return-field id "
        "--return-field name --return-field type --return-field path"
    )
    assert command in SKILL
    assert "Keep all four return fields explicit" in SKILL
    assert "Exact `not_found` stays Gateway-owned in compact output" in SKILL
    assert "use `--detail` only for explicit compile/dispatch diagnostics" in SKILL
    assert "do not read the query reference before or after it" in SKILL
    assert "Conditional read for a query not fully covered" in SKILL
    assert "keep those four fields explicit for an exact path/GUID identity lookup" in QUERY


def test_multihop_query_reads_reference_before_a_fast_looking_first_hop() -> None:
    first_hop_rule = "Classify the complete task before its first hop"
    single_hop_rule = "For a complete single-hop exact path/GUID"

    assert first_hop_rule in SKILL
    assert "If it needs multiple or relationship hops" in SKILL
    assert "fully read `references/waapi-query.md` before any Gateway command" in SKILL
    assert (
        "an exact path/GUID first hop does not make the whole task a complete fast route"
        in SKILL
    )
    assert SKILL.index(first_hop_rule) < SKILL.index(single_hop_rule)


def test_exact_hop_playback_diagnosis_does_not_repeat_the_action_lookup() -> None:
    section = QUERY.split("## Exact-hop playback diagnosis", 1)[1].split(
        "## Topics and Authoring-only reads", 1
    )[0]
    section_flat = " ".join(section.split())

    assert "The Event children result is already the Action hop" in section_flat
    assert "do not query the Action id again" in section_flat
    assert "use the returned `Target.id` directly" in section_flat
    assert "for the next exact-id Sound lookup" in section_flat


def test_exact_hop_bus_comparison_uses_symmetric_volume_projections() -> None:
    section = QUERY.split("## Exact-hop playback diagnosis", 1)[1].split(
        "## Topics and Authoring-only reads", 1
    )[0]
    section_flat = " ".join(section.split())

    assert "Both exact Bus reads must use the same" in section_flat
    assert "`id,name,type,path,@Volume` projection" in section_flat
    assert "never omit `@Volume` from comparison Bus" in section_flat


def test_query_relationship_hops_reuse_returned_guids_without_weakening_guards() -> None:
    section = QUERY.split("### Relationship-guided next hops", 1)[1].split(
        "### Advanced native WAQL fallback", 1
    )[0]
    section_flat = " ".join(section.split())

    for relationship in ("`Target`", "`activeSource`", "`OutputBus`", "`parent`"):
        assert relationship in section_flat
    for relationship_id in (
        "`Target.id`",
        "`activeSource.id`",
        "`OutputBus.id`",
        "`parent.id`",
    ):
        assert relationship_id in section_flat
    assert "are relationship objects" in section_flat
    assert "canonical braced GUID" in section_flat
    assert "stop if missing or malformed" in section_flat
    assert "Query that GUID directly" in section_flat
    assert "do not reread the current row or search by name or path" in section_flat
    assert "Gateway target/role revalidation still runs during preview/execute/verify" in section_flat
    assert "Preserve first-returned order" in section_flat
    assert "de-duplicate the GUIDs" in section_flat
    assert "query each distinct GUID exactly once" in section_flat
    assert "advanced-WAQL candidate" in section_flat
    assert "simple exact-id readback" in section_flat


def test_operate_reuses_completed_exact_read_guids_for_later_selectors() -> None:
    section = OPERATE.split("Public mutation identities are closed", 1)[1].split(
        "## Choose by business outcome", 1
    )[0]
    section_flat = " ".join(section.split())

    assert "exact relationship/path read" in section_flat
    assert "returns canonical `id`/`name`/`type`/`path`" in section_flat
    assert "reuse its GUID as an `id` selector" in section_flat
    assert "later object/target" in section_flat
    assert "never switch to path/name" in section_flat
    assert "retype its Wwise path" in section_flat
    assert "Gateway revalidates it" in section_flat


def test_relationship_display_name_never_substitutes_for_absolute_bus_path() -> None:
    section = QUERY.split("### Relationship-guided next hops", 1)[1].split(
        "### Advanced native WAQL fallback", 1
    )[0]
    section_flat = " ".join(section.split())

    assert "A relationship display `name`, including `OutputBus.name`, never proves an absolute path" in section_flat
    assert "rule gives an absolute Bus path" in section_flat
    assert "exact-ID query every distinct `OutputBus` GUID" in section_flat
    assert "for `id`, `name`, `type`, and `path`" in section_flat
    assert "compare returned `path`, never `name` with its final segment" in section_flat


def test_broad_query_subset_mutations_require_exact_id_readback() -> None:
    section = QUERY.split("### Relationship-guided next hops", 1)[1].split(
        "### Advanced native WAQL fallback", 1
    )[0]
    section_flat = " ".join(section.split())

    assert "broad ordinary/structured query returns multiple candidates" in section_flat
    assert "selects some to change" in section_flat
    assert "`query-object --object-id` on each selected GUID" in section_flat
    assert "`id`, `name`, `type`, and `path`" in section_flat
    assert "Never reread unselected rows" in section_flat
    assert "relationship read hops are exempt" in section_flat
    assert "mutation subset selected from multiple ordinary/structured results" in SKILL
    assert "relationship-GUID read hops are exempt" in SKILL


def test_query_reference_discloses_compact_success_and_explicit_detail() -> None:
    section = QUERY.split("Ordinary `query-object` success", 1)[1].split(
        "### Relationship-guided next hops", 1
    )[0]
    section_flat = " ".join(section.split())

    assert "defaults to compact business fields" in section_flat
    assert "sufficient for normal answers" in section_flat
    assert "Use `--detail` only for explicit user requests" in section_flat
    assert "compile/dispatch diagnosis" in section_flat
    assert "never rerun solely for detail" in section_flat
    assert "Failures skip compact projection but obey global limits" in section_flat
    assert "Keep terminal `agent_result` exact and final" in section_flat

    skill_flat = " ".join(SKILL.split())
    assert "Normal query answers use default business fields" in skill_flat
    assert "only for explicit user requests or compile/dispatch diagnosis" in skill_flat
    assert "never rerun solely for detail" in skill_flat


def test_small_complete_audit_uses_simple_inventory_before_report_rules() -> None:
    query_flat = " ".join(QUERY.split())

    assert "Choose the query layer by live retrieval, not report-rule count" in query_flat
    assert "every object in one explicit small subtree" in query_flat
    assert "apply the user's `OR`, `NOT`, comparison, or naming rules directly to those rows, without code" in query_flat
    assert "Do not call `query-schema` merely because a report has several rules" in query_flat
    assert "Boolean rules applied after a complete small inventory do not trigger that switch" in query_flat


def test_user_supplied_absolute_wwise_paths_keep_their_exact_versioned_root() -> None:
    query_flat = " ".join(QUERY.split())

    assert "Copy user-supplied absolute Wwise paths character-for-character" in query_flat
    assert "never add or change their roots" in query_flat
    assert "In 2025, never rewrite `\\Containers\\...` or `\\Busses\\...` under legacy roots" in query_flat


def test_advanced_query_docs_forbid_identity_handoff_and_disclose_framing() -> None:
    section = QUERY.split("### Advanced native WAQL fallback", 1)[1].split(
        "### Bounded inventories", 1
    )[0]
    section_flat = " ".join(section.split())

    for phrase in (
        "UTF-8 bytes (not character counts)",
        "trimmed and single-line",
        "comments or statement separators",
        "unclosed double-quoted string or slash-regex literal",
        "even a one-row result does not prove",
        "Never feed an advanced result directly into a mutation",
        "obtain their exact choice",
        "simple `query-object --object-id` route",
        "workflow stops for a new choice",
    ):
        assert phrase in section_flat
    assert "identity handoff" not in section.casefold()
    assert "one-row response never certifies uniqueness" in SKILL


def test_complex_query_guidance_preserves_tokens_pushdown_and_user_bounds() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        "Volume -> `@Volume`",
        "Output Bus -> `OutputBus` (never `@OutputBus`)",
        "Source language -> `audioSource:language`",
        "direct child count -> `childrenCount`",
        "ASCII-single-quote every standalone argv value beginning with `@`",
        "exactly one returned `AudioFileSource` has `parent.id` exactly equal to that Sound's `id`",
        "Do not report the language as missing when this exact child-source evidence exists",
        "do not associate by row position, similar names, or path prefixes",
        "Repeated `--where FIELD OPERATOR TYPE VALUE` facts mean AND",
        "When the live result selection itself requires `A and (B or C)` or another nested boolean, switch to the structured route",
        "copy that exact number to `--take`",
        "ask for a limit instead of inventing one",
    ):
        assert phrase in query_flat
    assert "--where type = string Sound --take 24" in query_flat
    assert "--return-field '@Volume' --return-field notes --return-field OutputBus" in query_flat


def test_pure_and_query_pushes_every_supported_conjunct_in_canonical_order() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        'Words such as "simultaneously", "all of the following conditions", or “同时满足” introduce a pure AND',
        "Repeat `--where` for every supported conjunct",
        "preserving the user's condition order",
        "Do not submit only the type predicate",
        "report, grouping, or sorting in their first-mention order",
        "additional filter-only fields",
        "`isIncluded` is appended last because it is filter-only",
    ):
        assert phrase in query_flat
    assert (
        "--where type = string Sound --where '@Volume' '<=' number -6.0 "
        "--where notes : string mix-review --where isIncluded = boolean true --take 12"
    ) in query_flat
    assert (
        "--return-field '@Volume' --return-field notes "
        "--return-field OutputBus "
        "--return-field isIncluded"
    ) in query_flat
    assert (
        "--return-field notes --return-field audioSource:language "
        "--return-field OutputBus"
    ) not in query_flat


def test_query_shell_examples_never_expose_bare_at_prefixed_argv_values() -> None:
    executable_snippets = "\n".join(
        re.findall(r"```bash\n(.*?)\n```", QUERY, flags=re.DOTALL)
    )

    assert executable_snippets
    assert re.search(
        r"(?:^|\s)--return-field\s+@[A-Za-z_][A-Za-z0-9_:]*",
        executable_snippets,
    ) is None


def test_nested_boolean_query_uses_the_closed_structured_contract() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        "offline, version-aware schema command",
        "typed structured-query continuation",
        "nested `all`/`any`, or `not`",
        "Do not add `waql`, `raw`, `expression`",
        "structured route: use one `where` transform with `all`, `any`, and `not`",
    ):
        assert phrase in query_flat
    assert "Follow the returned typed-structured continuation" in QUERY


def test_reverse_direct_parent_query_uses_the_parent_transform() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        '"from the Sounds, find their direct parents"',
        "`--type Sound --select parent`",
        "Predicates then describe the selected parent rows",
        "returned-parent `path` predicate",
        "Do not replace this with a descendant inventory",
    ):
        assert phrase in query_flat
    assert (
        "query-object --type Sound --select parent --where path : string "
        "'\\Actor-Mixer Hierarchy\\Default Work Unit\\ParentReview' "
        "--where type = string RandomSequenceContainer"
    ) in query_flat
    assert (
        "--return-field childrenCount --return-field notes "
        "--return-field OutputBus"
    ) in query_flat


def test_reverse_direct_parent_example_contains_exact_typed_path() -> None:
    example = QUERY.split("Direct parents:", 1)[1].split("```bash", 1)[1].split(
        "```", 1
    )[0]
    assert (
        "--where path : string "
        r"'\Actor-Mixer Hierarchy\Default Work Unit\ParentReview'"
    ) in example


def test_reverse_parent_coverage_counts_raw_source_rows_not_children_count() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        "one returned parent row for each matching source object",
        "Count those rows before deduplicating",
        "`childrenCount` only as the number of all direct child objects",
        "never relabel its value or a sum of it",
        "report that confirmed source count",
        "result may be incomplete",
    ):
        assert phrase in query_flat


def test_ancestor_ownership_query_keeps_the_explicit_project_exclusion() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        "ownership chain from one exact object",
        "`--select ancestors`",
        "do not assume the ancestor transform removes Project by itself",
        "nearest parent to farthest ancestor",
        "without mixing same-name objects from other branches",
    ):
        assert phrase in query_flat
    assert (
        "--select ancestors --where type '!=' string Project --take 8"
    ) in query_flat
    assert (
        "--return-field childrenCount --return-field notes"
    ) in query_flat


def test_relative_depth_uses_path_without_an_unrequested_parent_projection() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        "derive depth from each returned `path`",
        "counting the root's direct children as relative depth 1",
        "do not add `parent` solely to calculate relative depth",
        "Request `parent` only when the user needs a parent identity or a direct parent-child relationship",
    ):
        assert phrase in query_flat

    example = QUERY.split(
        "For example, a bounded descendant inventory of Sound candidates", 1
    )[1].split("```bash", 1)[1].split("```", 1)[0]
    assert "--return-field path" in example
    assert "--return-field parent" not in example


def test_mixed_parent_child_query_keeps_both_required_types_in_candidate_set() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        "complete final row set",
        "parent containers together with their direct child Sounds",
        "omit a `type=Sound` or container-only predicate",
        "bounded mixed-type descendant set",
        "request `parent`",
        "erase one required side of the relationship",
    ):
        assert phrase in query_flat


def test_soundbank_generated_uses_an_explicit_skill_selected_timeout() -> None:
    assert "For `ak.wwise.core.soundbank.generated`" in QUERY
    assert "Run `topic-schema`" in QUERY
    assert "exact typed option handles" in QUERY
    assert "--timeout 10 wait-topic ak.wwise.core.soundbank.generated" not in QUERY
    assert "gateway itself keeps the ordinary 10-second omitted-duration default" in QUERY
    assert "explicitly pass gateway-global `--timeout 120`" in QUERY
    assert "an explicit Skill-selected timeout, not a different gateway default" in QUERY
    assert "tell the user that this subscription will use 120 seconds" in QUERY
    assert "user-supplied positive finite duration or explicit no-time-limit bounded wait still takes precedence" in QUERY


def test_topic_wait_duration_policy_is_explicit_and_output_remains_bounded() -> None:
    skill_flat = " ".join(SKILL.split())
    query_flat = " ".join(QUERY.split())

    for phrase in (
        "tell the user the effective policy naturally",
        "ordinary omitted-duration default is 10 seconds",
        "converting units to seconds without rounding",
        "`--timeout <positive-finite-seconds>` position before `wait-topic`",
        "`wait-topic` subcommand flag `--no-timeout`",
        "until 1–64 requested matches or cancellation",
        "is not an unlimited output stream",
        "Never combine those flags",
    ):
        assert phrase in skill_flat

    for phrase in (
        "An ordinary omitted duration uses 10 seconds",
        "convert its units to seconds without rounding",
        "Do not silently clamp it",
        "is its default or recommendation, not a maximum",
        "add the subcommand flag `--no-timeout`",
        "the command still returns one terminal JSON document",
        "Typed match facts from `topic-schema` are applied per event",
        "after success, timeout, or user cancellation",
        "complete dispatcher collection still shares the topic execution contract's 256 KiB JSON result ceiling",
    ):
        assert phrase in query_flat

    assert "gateway.py wait-topic <topic-uri>" in SKILL
    assert "gateway.py topic-schema <topic-uri>" in SKILL
    assert (
        "gateway.py --timeout <positive-finite-seconds> wait-topic <topic-uri>"
        in SKILL
    )
    assert "gateway.py wait-topic <topic-uri> --no-timeout" in SKILL
    assert "这次使用默认的 10 秒等待时间" in SKILL


def test_explicit_persistent_topic_intent_uses_one_streaming_subscription() -> None:
    skill_flat = " ".join(SKILL.split())
    query_flat = " ".join(QUERY.split())

    for phrase in (
        "Route ordinary vague “subscribe”, “listen”, or “monitor” wording to `wait-topic`",
        "Select `stream-topic` only for explicit streaming or persistent intent",
        "one persistent subscription",
        "compact flushed JSON record",
        "by default runs until cancellation",
        "bounded buffer fails closed on overflow",
        "cleanup always attempts unsubscribe",
        "a terminal record reports why the stream ended",
    ):
        assert phrase in skill_flat
    for phrase in (
        "one compact flushed NDJSON record",
        "by default continues until the user cancels it or a bounded low-frequency health check detects",
        "overflow fails closed instead of silently dropping an event",
        "always attempts to unsubscribe",
        "one terminal NDJSON record",
        "Every streamed event is validated",
    ):
        assert phrase in query_flat
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
        assert intent in SKILL
        assert intent in QUERY

    assert "gateway.py stream-topic <topic-uri>" in SKILL
    assert (
        "gateway.py --timeout <positive-finite-seconds> stream-topic <topic-uri>"
        in SKILL
    )
    assert "Every command except `stream-topic` prints one JSON document" in skill_flat


def test_ordinary_wwise_work_forbids_agent_authored_code() -> None:
    for phrase in ("inline Python", "new `.py`/`.js`/`.sh` helper", "direct client construction"):
        assert phrase in SKILL
    assert "Skill development, testing, or debugging" in SKILL
    for phrase in (
        "Do not import builders or planners from inline Python",
        "call `WaapiClient`",
        "Do not write code to bypass an unsupported boundary",
        "That boundary does not authorize code generation",
    ):
        assert phrase in OPERATE


def test_all_agent_cat_references_fit_the_single_read_window() -> None:
    references = {
        "waapi-setup.md": SETUP,
        "waapi-query.md": QUERY,
        "waapi-operate.md": OPERATE,
        "waapi-coverage.md": COVERAGE,
    }

    for name, reference in references.items():
        lf_bytes = len(reference.encode("utf-8"))
        assert lf_bytes <= 32_768, name
        assert lf_bytes + reference.count("\n") <= 32_768, f"{name} CRLF checkout"


def test_media_pool_contains_value_is_disclosed_as_literal_text() -> None:
    assert (
        "`contains` takes literal text, never regex syntax or inline modifiers"
        in QUERY
    )


def test_operate_reference_is_a_bounded_single_read_control_plane() -> None:
    marker = "<!-- WAAPI_OPERATE_REFERENCE_END -->"
    assert len(OPERATE.encode("utf-8")) <= 32_768
    assert len(OPERATE.splitlines()) <= 240
    assert OPERATE.count("WAAPI_OPERATE_REFERENCE_END") == 1
    assert OPERATE.rstrip().endswith(marker)
    assert marker not in OPERATE[: OPERATE.rfind(marker)]
    assert "unique terminal sentinel required by `SKILL.md`" in OPERATE
    assert "no truncation or omission marker" in OPERATE
    assert "do not reread a range or invoke the Gateway" in OPERATE


def test_query_reference_has_a_deterministic_end_and_separate_alarm_hops() -> None:
    marker = "<!-- WAAPI_QUERY_REFERENCE_END -->"
    query_flat = " ".join(QUERY.split())

    assert len(QUERY.encode("utf-8")) <= 32_768
    assert len(QUERY.encode("utf-8")) + QUERY.count("\n") <= 32_768
    assert QUERY.count("WAAPI_QUERY_REFERENCE_END") == 1
    assert QUERY.rstrip().endswith(marker)
    assert marker not in QUERY[: QUERY.rfind(marker)]
    assert "unique terminal sentinel required by `SKILL.md`" in query_flat
    assert "no truncation or omission marker" in query_flat
    assert "do not reread a range or invoke the Gateway" in query_flat
    assert "`WAAPI_QUERY_REFERENCE_END` and `WAAPI_OPERATE_REFERENCE_END`" in SKILL
    assert "matching sentinel is the final visible line" in SKILL
    assert "That Sound projection ends at `OutputBus`" in query_flat
    assert "do not add `@Volume` to the Sound hop" in query_flat
    assert "query `@Volume` only on the exact Bus identities" in query_flat
    assert "first the returned `OutputBus` id" in query_flat
    assert "then the requested comparison Bus path or id" in query_flat
    assert "count only repeated `--query` flags" in query_flat
    assert "1–2 use 8, 3–4 use 3, and 5–8 use 2" in query_flat
    for phrase in (
        "Exact standard bindings",
        "Success rows are objects in the array",
        "Complete `no_match` is a bounded miss",
        "Honor dependencies when authorized, otherwise clarify",
        "Use fixed reads rather than reflected payloads",
        "voice pipeline id",
        "bus pipeline ids",
        "auto-detected Authoring profile",
        "bounds the projection",
    ):
        assert phrase in query_flat


def test_operate_first_command_branches_are_disjoint_and_schema_owned() -> None:
    compact = " ".join(OPERATE.split())
    assert "An existing transaction continuation always outranks operation selection" in OPERATE
    assert "transaction-show <transaction-id> --summary-only" in OPERATE
    assert "Do not call `operations`, `operation-schema`, or `request-schema` first" in OPERATE
    assert "`object.set` or `audio.import`" in OPERATE
    assert "run one metadata discovery next, then Composer actions" in OPERATE
    assert "`operation-schema object.create` first" in OPERATE
    assert "selected-subset identity gate" in OPERATE
    assert "exact-ID read back every selected" in OPERATE
    assert "These bounded read-only checks precede the transaction contract" in OPERATE
    assert "first transaction-contract branches" in OPERATE
    assert "explicitly requested unknown dynamic property/reference token" in OPERATE
    assert "one metadata discovery first, then its named `operation-schema`" in OPERATE
    assert "A named operation using only closed schema fields and side effects" in OPERATE
    assert "its named `operation-schema` directly" in OPERATE
    assert "including both import operations" not in OPERATE
    assert "schema owns fixed fields and Event/Switch Assignation" in OPERATE
    assert "metadata selects dynamic tokens and `draft-check` revalidates them" in OPERATE
    assert "Table imports start `operation-schema audio.importTabDelimited`" in OPERATE
    assert "dynamic columns stay metadata-first" in OPERATE
    skill_compact = " ".join(SKILL.split())
    assert "Composer `draft-check` revalidates them and dependencies" in skill_compact
    assert "only an explicit unknown dynamic property/reference token needs" in skill_compact
    assert "A known native URI without a named route" in OPERATE
    assert "`request-schema <uri>`" in OPERATE
    assert "No schema-to-preview shortcut" in compact
    assert "gateway.py operation-schema <operation-name>" not in OPERATE
    assert "Follow the schema's sole `input_mode`" in OPERATE
    assert "For `composer`, run `composer.start.gateway_argv`" in OPERATE
    assert "then only the selected `action_argv`" in OPERATE
    assert "Start `object.set` rows with `add_target --target ...`" in OPERATE
    assert "Start every `audio.import` row with one `add_import_row`" in OPERATE
    assert "include `--assignment none`" in OPERATE
    assert "`--assignment switch VALUE` only when requested" in OPERATE
    assert "run its `preview-from-draft` unchanged" in OPERATE
    assert "preserving `--expected-revision` and `--apply`" in OPERATE
    assert "there is no `lua.executeFile` operation" in OPERATE
    assert "keep it as one `path` selector" in OPERATE
    assert "`--apply` marks a preview, not execution" in OPERATE
    assert "Exact reflected URIs use `request-schema`" in OPERATE
    assert "follow its sole typed continuation" in OPERATE
    assert "Unknown fields fail" in OPERATE
    assert "there is no caller-authored request document" in OPERATE
    assert "Public mutation identities are closed" in OPERATE
    assert "`exact-type-name`" in OPERATE
    assert (
        "Each later intended change still creates its own executable preview"
        in OPERATE
    )
    assert (
        "does not turn the next one into a design-only preview"
        in OPERATE
    )


def test_operate_business_selection_and_execution_domains_remain_explicit() -> None:
    compact = " ".join(OPERATE.split())
    for phrase in (
        "Select the operation whose postcondition and verifier match",
        "`operation.selection_guidance`",
        "`interface.selection_guidance`",
        "Directly described media rows",
        "Existing caller-owned import TSV",
        "Agent-generated TSV",
        "Direct saved SoundBank inclusions",
        "Existing caller-owned SoundBank Definition TSV",
        "Generate Bank artifacts",
        "durable Authoring project edits",
        "`ak.soundengine.*`",
        "`ak.wwise.core.transport.*`",
        "`ui.commands.execute`",
    ):
        assert phrase in OPERATE
    assert "Batch size alone never establishes file-workflow intent" in compact
    assert "When media import is primary" in compact
    assert "replace media on existing Sounds" in compact
    assert "create a Sound in the same batch" in compact
    assert "`object.set` cannot author media import" in compact
    assert (
        "directly described rows include a new target-container hierarchy or "
        "a same-row Event/Switch Assignation"
    ) in compact
    assert "use one `audio.import`" in compact
    assert "typed structure-only row" in compact
    assert (
        "never probe `object.create` or a separate assignment first"
        in compact
    )
    assert (
        "keep `object.set` when import is subordinate to a broader atomic "
        "mutation of existing targets"
    ) in compact
    assert "independent Switch assignment between existing objects" in compact
    assert "same-row import side effect" in compact
    assert (
        "Wholly new structure-only object hierarchy whose requested root does "
        "not already exist and has no media or import-manifest intent"
    ) in compact
    skill_compact = " ".join(SKILL.split())
    assert "For structure-only changes" in skill_compact
    assert "When media import is primary" in skill_compact
    assert "media-row target hierarchy as typed structure-only rows" in skill_compact
    assert "never probe `object.create` or a separate assignment first" in skill_compact
    assert (
        "use `object.set` instead when import is subordinate to a broader "
        "atomic mutation of existing targets"
    ) in skill_compact
    assert "An insertion target is not the request root" in compact
    assert (
        "Broad `object.set` is only for one larger atomic outcome"
    ) in compact
    assert "a root edit plus a new subtree" in compact
    assert (
        "After any required selected-subset identity gate, that batch starts with "
        "`operation-schema object.set`"
    ) in compact
    assert "whose requested root does not already exist" in compact
    assert "insertion into a named existing descendant" in compact
    assert "is not the request root" in compact
    assert "give each one an `objects[]` row" in compact
    assert "only genuinely new direct descendants" in compact
    assert "use that preflight query for an `object.create`" in compact
    assert (
        "first exact-query the unchanged root"
        in compact
    )
    assert (
        "Then open `operation-schema object.create` and follow its sole continuation "
        "directly into the Draft"
        in compact
    )
    assert (
        "do not query the parent already determined by that verified path"
        in compact
    )
    assert compact.index("first exact-query the unchanged root") < compact.index(
        "Then open `operation-schema object.create`"
    )
    assert (
        "`object.set` instead uses its returned target base, live token discovery, "
        "and Composer validation"
    ) in compact
    assert "Do not insert `project-default-work-units`" in compact


def test_single_existing_object_edit_uses_its_dedicated_operation_before_object_set() -> None:
    compact = " ".join(OPERATE.split())
    skill_compact = " ".join(SKILL.split())
    dedicated_row = (
        "| One existing object's single rename, notes, scalar-property, or "
        "reference edit | `object.setName`, `object.setNotes`, "
        "`object.setProperty`, or `object.setReference` | broad `object.set` |"
    )
    broad_row = "| Larger atomic existing-target batch:"

    assert "Existing-root status alone does not select `object.set`" in compact
    assert dedicated_row in OPERATE
    assert OPERATE.index(dedicated_row) < OPERATE.index(broad_row)
    assert (
        "one existing object's single rename/notes/property/reference edit "
        "uses its dedicated operation"
    ) in skill_compact
    assert "`object.set` is for broader atomic existing-target work" in skill_compact
    for broad_case in (
        "several fields/properties/references on one root",
        "an ordinary closed object-list change",
        "multiple roots",
        "a root edit plus a new subtree",
        "insertion into a named existing descendant",
    ):
        assert broad_case in compact
    assert compact.count("several fields/properties/references on one root") == 3
    assert compact.count("an ordinary closed object-list change") == 3
    assert "Plug-in, RTPC, and platform-link changes keep their dedicated operations" in compact
    assert "Single-edit, plug-in, RTPC, and platform-link operations take precedence" in compact
    assert "when those `object.set` conditions are absent" in compact
    assert "all three `object.set` conditions" not in compact
    assert (
        "A named root that already exists and receives any notes, property, "
        "reference, or list change locks the whole batch to `object.set`"
    ) not in compact
    assert (
        "`object.set` is locked when the request changes fields/references on "
        "an existing root"
    ) not in compact


def test_operate_uses_one_bank_scoped_replace_for_a_complete_inclusion_post_state() -> None:
    compact = " ".join(OPERATE.split())

    assert (
        "complete desired final inclusion set, use one "
        "`soundbank.setInclusions` `replace` transaction"
    ) in compact
    assert "removed without being named individually" in compact
    assert "every other Bank remains outside that transaction" in compact
    assert (
        "Do not split that final-state request into `add` and `remove` transactions"
        in compact
    )


def test_operate_metadata_and_import_prose_only_rules_are_preserved() -> None:
    compact = " ".join(OPERATE.split())
    for phrase in (
        "one repeated `--query '<ordinary phrase>'` per requested setting",
            "Use the deterministic candidate budget",
        "one or two flags require `--limit 8`",
        "three or four require `--limit 3`",
        "five through eight require `--limit 2`",
        "A rejected or nonzero Gateway invocation is also a hard stop",
        "Do not advance to the next schema, preview, or transaction phase",
        "several existing targets of one proven type",
        "`--object` for one existing object",
        "`--object-type Sound`",
        "`PropertyContainer` in `2025.1`",
            "Translate localized wording into short English Wwise UI",
        "do not copy CJK wording into the live lexical matcher",
            "independent switches and numeric values separately",
        "`fallback_detail_scan.status` is `partial`",
        "A `complete` scan with no match is terminal",
        "for table imports, only dynamic `Property[...]`, `Reference[...]`, or `@...` columns",
        "Fixed fields and side effects never trigger discovery",
        "Event, Dialogue Event, and Switch Assignation are schema-owned too",
        "`Notes` and `Audio Source Notes` are fixed import columns",
        "not Sound metadata queries",
        "ordinary `audio.importTabDelimited` import",
        "do not `cat` or otherwise read the caller's TSV",
        "supplied absolute path unchanged through the typed continuation",
        "resulting Preview owns bounded TSV parsing and hashing",
        "inline base64 and media validation",
        "exact-path conflict checks",
        "separate read-only task, never an import prerequisite",
        "`SFX` is the built-in nonlocalized import token",
        "do not query the Project language inventory",
        "`arguments.import_operation` is the explicit batch-level mode",
        "omission means `createNew`",
        "never belongs inside an `imports[]` row",
        "Under `useExisting`, behavior is still resolved per row",
        "Existing SFX rows retain every user-supplied optional field",
        "`import_location` is a wire-significant path-base selector",
        "absolute `object_path`, omit it from both the row and `defaults`",
        "never infer `defaults.import_location` from a shared absolute parent",
        "relative `object_path` requires one effective row/default `import_location`",
        "Use `originals_subfolder` only when the user explicitly supplies",
        "never infer one from a source directory, media category, object path, or example",
        "It is relative to Wwise's normal destination",
        "absolute path below `\\Events`",
        "absent before preview",
        "unique across rows",
        "`1 semitone = 100 cents`",
    ):
        assert phrase in compact
    assert "never silently add or remove an `SFX/` prefix" in compact


def test_operate_maps_only_live_query_accessors_to_mutation_tokens() -> None:
    compact = " ".join(OPERATE.split())

    assert "Reuse evidence-bound live property/reference accessors" in compact
    assert "`@Foo` becomes `Foo`" in compact
    assert "remove one leading `@`" in compact
    assert "`OutputBus` remains `OutputBus`" in compact
    assert "evidence-bound" in compact
    assert "never infer a token" in compact


def test_operate_cli_and_authoring_fast_routes_keep_unstructured_materialization_rules() -> None:
    compact = " ".join(OPERATE.split())
    assert "Only explicit WwiseConsole, CLI, command-line, or 命令行 wording" in compact
    assert "alone does not establish CLI intent" in compact
    for api in (
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.migrate",
    ):
        assert f"`{api}`" in OPERATE
    assert "`request-schema <exact-uri>`" in compact
    assert "never reuse them for another lane" in compact
    assert "not yet represented structurally" in OPERATE
    for phrase in (
        "`platform` is always an array",
        "flat two-string pair for one platform",
        "array of pairs for several",
        "array processes only its first source",
        "repeated platform mapping processes only its last entry",
        "both shapes are rejected",
        "final directory",
        "Init is automatic",
        "omit false/default flags",
        "result-schema-only",
        "normal control-server disconnect or continued reachability does not authorize replay",
        "caller-owned reopened-project oracle",
    ):
        assert phrase in compact
    assert "`request-schema ak.wwise.core.audio.convert`" in compact
    assert "user's exact absolute `io_root`" in compact


def test_operate_policy_and_gateway_owned_continuation_are_closed() -> None:
    compact = " ".join(OPERATE.split())
    skill_compact = " ".join(SKILL.split())
    for policy in ("`read_only`", "`ask_before_changes`", "`allow_changes`"):
        assert policy in OPERATE
    assert "omit `--state-dir`" in OPERATE
    assert "Gateway owns the external runtime state root" in OPERATE
    assert "Gateway owns a deterministic external runtime-state default" in SKILL
    assert "A rejected or incomplete preview is a hard same-turn boundary" in OPERATE
    assert (
        "Never ask for confirmation while typed composition or Preview creation "
        "is still incomplete"
    ) in compact
    assert "On `LOCAL_WAAPI_HOST_REQUIRED`, report and stop" in OPERATE
    assert "execute only the field named by `next_command.copy_instruction.source_field`" in compact
    assert "copy that entire string verbatim as one shell tool call" in compact
    assert "normally selects the short `model_command`" in compact
    assert "encoded `shell_command` remains an audit/fallback representation" in compact
    assert "Do not render diagnostic `full_argv`" in compact
    assert "never infer fallback from the visible field" in compact
    assert "run `confirm --help`" in compact
    assert "a status/check request stops after `transaction-show`" in compact
    assert "a verify-only request never executes" in compact
    assert "after the prior item reaches terminal verification" in compact
    assert "Never infer, add, combine, or reorder an item" in compact
    assert (
        "Even when the same request names later independent changes, run no more "
        "Gateway commands in that turn"
    ) in skill_compact


def test_operate_terminal_states_migration_and_cleanup_are_fail_closed() -> None:
    compact = " ".join(OPERATE.split())
    for state in (
        "`verified`",
        "`result_schema_checked`",
        "`verification_deferred`",
        "`verification_failed`",
        "`repreview_required`",
        "`execution_cancelled`",
        "`execution_succeeded_persistence_failed`",
        "`indeterminate`",
    ):
        assert state in OPERATE
    assert "Do not verify, retry, call another Gateway route" in compact
    assert "A later diagnosis needs a new user request" in compact
    assert "`ak.wwise.cli.migrate` is the narrow exception" in compact
    assert "Run no more Agent tools" in compact
    assert "caller-owned harness outside the Skill sequence" in compact
    assert "Do not hide that obligation or uncertainty" in compact
    assert "Never synthesize cleanup code" in compact
    assert "Work Unit load/unload is an available reversal" in compact
    assert "serialize the successful Gateway `agent_result` verbatim" in compact


def test_complex_query_projection_documents_derived_field_first_mention_order() -> None:
    flattened = " ".join(QUERY.split())
    assert "scanning the user's requested output left to right" in flattened
    assert "`id`, `name`, `type`, `path`, `parent`, `audioSource:language`, `@Volume`," in QUERY
    assert "`notes`" in QUERY


def test_media_pool_reference_orders_field_discovery_before_the_bound_read() -> None:
    fields_schema = "`request-schema ak.wwise.core.mediaPool.getFields`"
    get_schema = "`request-schema ak.wwise.core.mediaPool.get`"

    assert fields_schema in QUERY
    assert get_schema in QUERY
    assert QUERY.index(fields_schema) < QUERY.index(get_schema)
    assert "Do not request the `.get` schema first" in QUERY


def test_soundbank_generation_notifications_remain_query_only() -> None:
    assert "Classify the requested action, not background wording" in SKILL
    assert "listen for, wait for, or report a SoundBank generation notification" in SKILL
    assert "It never authorizes `soundbank.generate`" in SKILL


def test_soundbank_topic_selection_distinguishes_per_result_from_cycle_notice() -> None:
    query_flat = " ".join(QUERY.split())
    assert "Use `ak.wwise.core.soundbank.generated` for per-Bank × platform × language result events" in query_flat
    assert "Use `ak.wwise.core.soundbank.generationDone` only for the overall generation-cycle" in query_flat
    assert "`generationDone` is not proof that every Bank succeeded" in query_flat
    assert "use the generating operation's terminal verification" in query_flat
    assert "`interface.selection_guidance`" in query_flat


def test_capability_summary_is_unfiltered_and_route_filters_are_row_only() -> None:
    summary_command = "capabilities --all-versions --summary-only"

    assert f"run exactly `{summary_command}`" in SKILL
    assert "For five-version totals, first read coverage as directed below" in SKILL
    assert "it includes every route count" in SKILL
    assert "Row filters omit `--summary-only`" in SKILL
    assert "are the exception below" in SKILL
    assert "read `references/waapi-coverage.md` once after `SKILL.md`" in SKILL
    assert "before the summary" in SKILL
    assert summary_command in COVERAGE
    assert "Do not combine `--summary-only` with row filters" in COVERAGE
    assert "For row-level inventories, omit `--summary-only`" in COVERAGE


def test_five_version_coverage_reference_reports_executable_registry_not_boundaries() -> None:
    coverage_flat = " ".join(COVERAGE.split())
    assert "| Total version/API rows | 814 | 268 | 540 | 6 | 808 |" in COVERAGE
    assert "The 808 packaged route rows represent 198 unique public WAAPI route contracts" in COVERAGE
    assert "A hard boundary is never counted as routed coverage" in COVERAGE
    assert "still require a live Authoring host" in coverage_flat
    assert "`AUTHORING_HOST_REQUIRED` before business" in coverage_flat
    assert "`operation-schema` or exact-URI `request-schema` typed route" in COVERAGE
    assert "representation is never a caller or model input" in COVERAGE
    assert "Lua file operations are executable only from an existing `.lua` file" in COVERAGE
    assert "Hidden/model-authored source and unrestricted loader fields remain closed" in coverage_flat
    assert "program-tested packaged coverage" in COVERAGE
    assert "not individually" in COVERAGE
    assert "live-semantic-verified" in COVERAGE


def test_public_config_surface_excludes_runtime_internals() -> None:
    for field in ("wwise_version", "waapi_host", "waapi_port", "project_modification_policy"):
        assert f"`{field}`" in SETUP
    assert "Do not describe timeout constants" in SETUP
    assert "environment wiring" in SETUP
    assert "default `WwiseConsole` paths" in SETUP
    assert "gateway.py config-show" in SETUP
    assert "gateway.py config-set" in SETUP
    assert "$XDG_CONFIG_HOME/waapi-skill/config.json" in SETUP
    assert "never writes the legacy file inside the Skill checkout" in SETUP


def test_one_time_onboarding_is_global_natural_and_does_not_add_a_gateway_call() -> None:
    for phrase in (
        "The first time this Skill is used in a conversation",
        "do not announce that it is loaded before the first gateway result",
        "`session_context.one_time_introduction.facts`",
        "the first Agent message after that result",
        "one short, atomic introduction",
        "Do not split those facts across an earlier message and a gateway-backed message",
        "`waapi-skill` is loaded",
        "current WAAPI address",
        "WAAPI adapter version",
        "project modification policy",
        "若有需要，可按需切换模式",
        "offer the three available modes",
        "ordinary prose, not a status bar, table, field list, or rigid template",
        "Use the first gateway command already required by the user's task",
        "An offline task stays offline",
        "visible conversation does not already contain this introduction",
        "do not use memory to make that decision",
        "separate normal progress update",
    ):
        assert phrase in SKILL
    assert "run exactly one offline `config-show` to obtain the introduction facts" in SKILL
    assert "never run `status` or open a live WAAPI connection only for the introduction" in SKILL
    assert "The entry file owns the one-time conversation introduction for every lane" in SETUP
    assert "emit the Gateway's structured `session_context.one_time_introduction` atomically" in SETUP
    assert "Do not add policy or implementation narration to a simple read-only result" not in SETUP
    assert "do not repeat policy narration in every simple read-only result" in SETUP
    assert "project modification policy" not in QUERY.lower()


def test_named_api_result_uses_status_only_as_preflight() -> None:
    assert "asks for the independent live result of a named API" in SKILL
    assert "status` only as the required host/project preflight" in SKILL
    assert "does not replace that independently requested API call" in SKILL
    assert "needs only this `SKILL.md`" in SKILL
    assert "do not read the setup or query reference" in SKILL
