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


def test_skill_entry_stays_within_one_complete_agent_tool_read() -> None:
    assert len(SKILL.encode("utf-8")) <= 20_000
    assert len(SKILL.encode("utf-8")) + SKILL.count("\n") <= 20_000


def test_first_gateway_backed_introduction_names_all_three_policy_modes() -> None:
    introduction = SKILL.split("## Setup", 1)[0]

    assert "Keep mode names exact" in introduction
    for policy in ("`read_only`", "`ask_before_changes`", "`allow_changes`"):
        assert policy in introduction


def test_lane_references_stay_within_one_complete_agent_tool_read() -> None:
    for name, content in {
        "waapi-query.md": QUERY,
        "waapi-setup.md": SETUP,
        "waapi-operate.md": OPERATE,
        "waapi-coverage.md": COVERAGE,
    }.items():
        assert len(content.encode("utf-8")) <= 30 * 1024, name


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
    assert "Read only the current-turn lane; never preload" in SKILL


def test_lane_reads_follow_only_the_current_user_turn() -> None:
    assert "Read only the current-turn lane; never preload" in SKILL
    assert (
        "Read-only work cannot read `waapi-operate.md` before a change request"
        in SKILL
    )
    assert "There is no raw-client fallback" in QUERY


def test_dynamic_draft_guidance_distinguishes_complete_json_from_incomplete_construction() -> None:
    compact = " ".join(OPERATE.split())
    assert (
        "`construction_state.complete:false` and compact action receipts are "
        "complete JSON"
    ) in compact
    assert "Follow `next_command_decision`" in compact
    assert "only an exact `business_value_pointer` authorizes it" in compact
    assert "A business Draft instead follows its returned required phase" in compact
    assert "completion candidate" in compact
    assert "Copy handles into the same named role" in compact
    assert "Corrections reuse the draft" in compact
    assert "never `draft-apply --action check`" in compact


def test_machine_readable_agent_result_is_terminal_for_fixed_reads_and_transactions() -> None:
    assert "any successful gateway payload contains `agent_result`" in SKILL
    assert "This rule applies to fixed reads as well as transactions" in SKILL
    assert "Do not reconstruct its fields from the prompt, `normalized`" in SKILL
    assert "do not run another command after receiving it" in SKILL
    assert "Use live `metadata types`" in QUERY
    assert "projection and bound are fixed" in QUERY


def test_media_pool_reference_classification_uses_one_closed_versioned_query() -> None:
    section = QUERY.split("### Closed original-file reference classification", 1)[1].split(
        "## Object queries", 1
    )[0]
    section_flat = " ".join(section.split())
    command = (
        "gateway.py --version 2025.1 query-object "
        "--max-results 1000 --match-original-file-path "
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
    assert "Do not add predicates, relationships, or extra business outputs" in section_flat
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

    assert "Read the injected `SKILL.md` exactly once as the sole first shell action" in SKILL
    assert "Never combine it with `pwd`, `git`, `rg`, `ls`, `find`, `printf`" in SKILL
    assert "Choose by command host, not Wwise/Codex version or path spelling" in frontmatter
    assert "POSIX uses `cat '<literal-locator>'` or exact `sed -n '1,$p'" in frontmatter
    assert "whitespace-free POSIX locator uses unquoted `cat <literal-locator>`" in frontmatter
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
    # Real native-Windows Fresh Agent runs have clipped the middle of larger
    # PowerShell output despite preserving both ends.  Keep material margin
    # below that variable transport window instead of merely fitting 32 KiB.
    assert len(SKILL.encode("utf-8")) <= 20_000
    assert len(SKILL.replace("\n", "\r\n").encode("utf-8")) <= 20_000


def test_exact_identity_query_is_complete_in_entry_file() -> None:
    assert "one literal `--path-segment` per hierarchy level" in SKILL
    assert "`--exact-id '<exact-guid>'`" in SKILL
    assert "always returns the four identity fields" in SKILL
    assert "Exact `not_found` stays Gateway-owned in compact output" in SKILL
    assert "use `--detail` only for explicit compile/dispatch diagnostics" in SKILL
    assert "do not read the query reference before or after it" in SKILL
    assert "Conditional read for a query not fully covered" in SKILL
    assert "The fixed identity projection is always present" in QUERY


def test_multihop_query_reads_reference_before_a_fast_looking_first_hop() -> None:
    first_hop_rule = "Classify the complete read-only task before its first hop"
    single_hop_rule = "For a complete single-hop exact path/GUID"

    assert first_hop_rule in SKILL
    assert "If it needs multiple or relationship hops" in SKILL
    assert "fully read `references/waapi-query.md` before any Gateway command" in SKILL
    assert (
        "an exact path/GUID first hop does not make the whole task a complete fast route"
        in SKILL
    )
    assert SKILL.index(first_hop_rule) < SKILL.index(single_hop_rule)


def test_operate_identity_preflight_stays_in_the_operate_reference_lane() -> None:
    operate_section = SKILL.split("### Operate lane", 1)[1].split(
        "## Runner and packaged runtime", 1
    )[0]
    operate_compact = " ".join(operate_section.split())

    assert (
        "An exact path/GUID identity preflight inside a change request is part "
        "of the operate lane"
    ) in operate_compact
    assert (
        "read only `references/waapi-operate.md` for that task"
        in operate_compact
    )
    assert (
        "Finish any user-requested exact path/type preflight before "
        "`operation-schema object.create`"
    ) in operate_compact
    assert "before-preview type/path check" in operate_compact
    assert "preserved sibling" in operate_compact
    assert "post-execution verification does not" in operate_compact
    assert (
        "After that preflight, `object.create` runs `operation-schema`, one "
        "`metadata discover` for its 1–8 dynamic fields, then `draft-start`"
    ) in operate_compact
    assert operate_compact.index(
        "Finish any user-requested exact path/type preflight"
    ) < operate_compact.index("`operation-schema object.create`")


def test_exact_hop_playback_diagnosis_does_not_repeat_the_action_lookup() -> None:
    section = QUERY.split("## Exact-hop playback diagnosis", 1)[1].split(
        "## Topics and Authoring-only reads", 1
    )[0]
    section_flat = " ".join(section.split())

    assert "Resolve the exact Event once" in section_flat
    assert "copy-ready `event-actions` continuation" in section_flat
    assert "Gateway owns the child hop" in section_flat
    assert "copy-ready `--view sound-routing-diagnostics`" in section_flat
    assert "do not re-query the Action" in section_flat


def test_exact_hop_bus_comparison_uses_symmetric_volume_projections() -> None:
    section = QUERY.split("## Exact-hop playback diagnosis", 1)[1].split(
        "## Topics and Authoring-only reads", 1
    )[0]
    section_flat = " ".join(section.split())

    assert "request `volume-db` only on the exact Bus identities" in section_flat
    assert "first the returned `output_bus` id" in section_flat
    assert "then the requested comparison Bus path or id" in section_flat
    assert "Never omit it from the comparison Bus" in section_flat


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

    assert "broad ordinary or advanced query returns multiple candidates" in section_flat
    assert "selects some to change" in section_flat
    assert "`query-object --exact-id` on each selected GUID" in section_flat
    assert "`id`, `name`, `type`, and `path`" in section_flat
    assert "Never reread unselected rows" in section_flat
    assert "relationship read hops are exempt" in section_flat
    assert "mutation subset selected from multiple business-declaration or advanced results" in SKILL
    assert "`mutation_selection`" in SKILL
    assert "relationship-GUID read hops are exempt" in SKILL


def test_query_only_diagnosis_never_preloads_the_future_operate_lane() -> None:
    assert "A diagnosis-only turn reads only `waapi-query.md`" in SKILL
    assert "must not preload `waapi-operate.md`" in SKILL


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


def test_topic_terminal_agent_result_is_authoritative_for_natural_answers() -> None:
    query_flat = " ".join(QUERY.split())

    assert "terminal `agent_result` is the sole event-result authority" in query_flat
    assert "never report no events when its `event_count` is positive" in query_flat
    assert "`topic-schema <topic-uri> --catalog`" in query_flat


def test_small_complete_audit_uses_simple_inventory_before_report_rules() -> None:
    query_flat = " ".join(QUERY.split())

    assert "Plan one bounded request" in query_flat
    assert "apply presentation logic only to its complete result" in query_flat
    assert "Use the business declaration for one source" in query_flat
    assert "Use advanced only for a native read-only construct absent from that schema" in query_flat
    assert "descendants, flat predicates, and business includes do not justify `--advanced`" in query_flat


def test_user_supplied_absolute_wwise_paths_keep_their_exact_versioned_root() -> None:
    query_flat = " ".join(QUERY.split())

    assert "repeated `--path-segment`" in query_flat
    assert "Never reconstruct a Wwise path separator" in query_flat
    assert "Gateway constructs the exact Wwise path and separators" in query_flat


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
        "simple `query-object --exact-id` route",
        "workflow stops for a new choice",
    ):
        assert phrase in section_flat
    assert "identity handoff" not in section.casefold()
    assert "one-row response never certifies uniqueness" in SKILL


def test_complex_query_guidance_preserves_tokens_pushdown_and_user_bounds() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        "The Agent names `volume-db`, `pitch-cents`, `output-bus`, `source-language`",
        "The Gateway owns case-sensitive Wwise accessors and shell quoting",
        "exactly one returned `AudioFileSource` has `parent.id` exactly equal to that Sound's `id`",
        "Do not report the language as missing when this exact child-source evidence exists",
        "do not associate by row position, similar names, or path prefixes",
        "Repeated `--predicate` values mean AND",
        "nested boolean logic, use the advanced exact-WAQL lane",
        "copy that exact number to `--max-results`",
        "ask for a limit instead of inventing one",
    ):
        assert phrase in query_flat
    assert "--predicate kind-is all-sounds --max-results 24" in query_flat
    assert "--include volume-db" in query_flat


def test_pure_and_query_pushes_every_supported_conjunct_in_canonical_order() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        "Repeated `--predicate` values mean AND",
        "preserve the user's condition order",
        "Do not submit only a type condition",
        "Output order is fixed identity first",
        "`isIncluded` is appended last because it is filter-only",
    ):
        assert phrase in query_flat
    assert (
        "--predicate kind-is all-sounds --predicate volume-db-at-most -6.0 "
        "--predicate notes-contain mix-review --predicate included-is true --max-results 12"
    ) in query_flat
    assert "--where" not in query_flat


def test_query_shell_examples_never_expose_bare_at_prefixed_argv_values() -> None:
    executable_snippets = "\n".join(
        re.findall(r"```bash\n(.*?)\n```", QUERY, flags=re.DOTALL)
    )

    assert executable_snippets
    assert "--return-field" not in executable_snippets


def test_nested_boolean_query_uses_the_bounded_advanced_contract() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        "offline version-aware schema command",
        "Advanced native WAQL fallback",
        "--advanced-waql",
        "Gateway fixes read-only `ak.wwise.core.object.get`",
        "no generated-code fallback",
    ):
        assert phrase in query_flat
    assert "typed-structured" not in QUERY


def test_reverse_direct_parent_query_uses_the_parent_transform() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        '"from the Sounds, find their direct parents"',
        "`--kind all-sounds --relationship parent`",
        "Predicates then describe the selected parent rows",
        "Do not replace this with a descendant inventory",
    ):
        assert phrase in query_flat
    assert (
        "query-object --kind all-sounds --relationship parent "
        "--predicate kind-is random-container"
    ) in query_flat
    assert (
        "--predicate children-at-least 3 --predicate notes-contain parent-review"
    ) in query_flat


def test_reverse_direct_parent_example_contains_exact_typed_path() -> None:
    example = QUERY.split("Direct parents:", 1)[1].split("```bash", 1)[1].split(
        "```", 1
    )[0]
    assert "--relationship parent" in example
    assert "--where" not in example


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
        "`--relationship ancestors`",
        "do not assume the relationship removes Project",
        "nearest parent to farthest ancestor",
        "without mixing same-name objects from other branches",
    ):
        assert phrase in query_flat
    assert "--relationship ancestors --max-results 8" in query_flat


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
    assert "--path-segment" in example
    assert "--include parent" not in example


def test_mixed_parent_child_query_keeps_both_required_types_in_candidate_set() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        "complete final row set",
        "parent containers together with their direct child Sounds",
        "omit a `type=Sound` or container-only predicate",
        "bounded mixed-type descendant set",
        "`--include parent`",
        "erase one required side of the relationship",
    ):
        assert phrase in query_flat


def test_soundbank_generated_uses_an_explicit_skill_selected_timeout() -> None:
    assert "For `ak.wwise.core.soundbank.generated`" in QUERY
    assert "`topic-schema` shortcuts" in QUERY
    assert "--include-object-identity" in QUERY
    assert "--match-platform-name <exact-name>" in QUERY
    assert "--match-soundbank-name <exact-name>" in QUERY
    assert "--event-entry platform - name <platform-name>" not in QUERY
    assert "--timeout 10 wait-topic ak.wwise.core.soundbank.generated" not in QUERY
    assert "Gateway still\ndefaults to 10 seconds" in QUERY
    assert "explicitly pass gateway-global `--timeout 120`" in " ".join(QUERY.split())
    assert "This is Skill-selected" in QUERY
    assert "announce 120 seconds" in QUERY
    assert "Explicit user timing/count intent takes precedence" in QUERY


def test_topic_wait_duration_policy_is_explicit_and_output_remains_bounded() -> None:
    skill_flat = " ".join(SKILL.split())
    query_flat = " ".join(QUERY.split())

    for phrase in (
        "Tell the user the effective policy naturally",
        "ordinary omitted-duration default is 10 seconds",
        "converting units to seconds without rounding",
        "global `--timeout` before `wait-topic`",
        "request selects `--no-timeout`",
        "until 1–64 requested matches or cancellation",
        "not an unlimited output stream",
        "Never combine those flags",
        "`choice_on_disclosure`",
        "run `field_disclosure` first",
        "use only typed `*-as`",
        "never guess untyped",
    ):
        assert phrase in skill_flat

    for phrase in (
        "An ordinary omitted duration uses 10 seconds",
        "convert units to seconds without rounding",
        "never clamp",
        "Contract timeouts are defaults, not maxima",
        "Explicit no-limit waits use `--no-timeout`",
        "1–64 matching events, one terminal JSON document",
        "business match facts from `topic-schema` are applied per event",
        "Gateway derives publish-schema paths, nested containers, wire types",
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
        "Select `stream-topic` for a requested event count",
        "do not add the vague-request 10-second total timeout",
        "--idle-timeout <seconds>",
        "explicit total durations have no implicit idle cutoff",
        "It keeps one subscription",
        "flushes matched events",
        "requires an `--event-count <1..64>` ceiling",
        "Event size, count, cumulative bytes, and buffering are bounded",
        "terminal record includes the completion and unsubscribe result",
    ):
        assert phrase in skill_flat
    for phrase in (
        "one compact flushed NDJSON record",
        "requires an explicit maximum `--event-count <1..64>`",
        "user cancellation, or a bounded low-frequency health check detects",
        "cumulative NDJSON bytes are bounded",
        "overflow fails closed instead of silently dropping an event",
        "always attempts to unsubscribe",
        "one terminal NDJSON record",
        "Every streamed event and the cumulative NDJSON bytes are bounded and validated",
    ):
        assert phrase in query_flat
    for intent in ("requested event count", "per-event/persistent"):
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
    assert len(OPERATE.replace("\n", "\r\n").encode("utf-8")) <= 20_000
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

    assert len(QUERY.replace("\n", "\r\n").encode("utf-8")) <= 20_000
    assert QUERY.count("WAAPI_QUERY_REFERENCE_END") == 1
    assert QUERY.rstrip().endswith(marker)
    assert marker not in QUERY[: QUERY.rfind(marker)]
    assert "unique terminal sentinel required by `SKILL.md`" in query_flat
    assert "no truncation or omission marker" in query_flat
    assert "do not reread a range or invoke the Gateway" in query_flat
    assert "`WAAPI_QUERY_REFERENCE_END` and `WAAPI_OPERATE_REFERENCE_END`" in SKILL
    assert "matching sentinel is the final visible line" in SKILL
    assert "ends at `output_bus`" in query_flat
    assert "do not add `volume-db` to the Sound hop" in query_flat
    assert "request `volume-db` only on the exact Bus identities" in query_flat
    assert "first the returned `output_bus` id" in query_flat
    assert "then the requested comparison Bus path or id" in query_flat
    assert "repeat `--meaning` for one to eight" in query_flat
    assert "Gateway owns detail level, search bounds, projection" in query_flat
    for phrase in (
        "Exact standard bindings",
        "Success rows are objects in the array",
        "Complete `no_match` is a bounded miss",
        "Honor dependencies when authorized, otherwise clarify",
        "Use fixed reads rather than reflected payloads",
            "Voice object GUID",
            "Bus object GUIDs",
            "Gateway resolves volatile pipeline IDs",
        "auto-detected Authoring profile",
            "deduplicates and bounds it",
    ):
        assert phrase in query_flat


def test_operate_first_command_branches_are_disjoint_and_schema_owned() -> None:
    compact = " ".join(OPERATE.split())
    assert "An existing transaction continuation always outranks operation selection" in OPERATE
    assert "transaction-show <transaction-id> --summary-only" in OPERATE
    assert "Do not call `operations`, `operation-schema`, or `request-schema` first" in OPERATE
    assert "| `audio.import` | `operation-schema audio.import`" in OPERATE
    assert "discover dynamic fields through returned Draft commands" in OPERATE
    assert "submit only disclosed high-level fields" in OPERATE
    assert "Then `operation-schema`; metadata" in OPERATE
    assert "pre-Preview same-name-root type/path only" in OPERATE
    assert "not parent/sibling or later verification" in compact
    assert compact.index(
        "pre-Preview same-name-root type/path only"
    ) < compact.index("Then `operation-schema`; metadata")
    assert "selected-subset identity gate" in OPERATE
    assert "exact-ID read back every selected" in OPERATE
    assert "These bounded read-only checks precede the transaction contract" in OPERATE
    assert "first transaction contract" in OPERATE
    assert (
        "A new natural-language change starts with one compact `operations` "
        "lookup; only its returned route selects the first transaction contract"
        in compact
    )
    assert "explicitly requested unknown dynamic property/reference token" in OPERATE
    assert "one metadata discovery first, then its named `operation-schema`" in OPERATE
    assert "A named operation using only closed schema fields and side effects" in OPERATE
    assert "its named `operation-schema` directly" in OPERATE
    assert "including both import operations" not in OPERATE
    assert "business Adapter owns object paths, native types, metadata scopes" in OPERATE
    assert "`draft-check` revalidates them" in OPERATE
    assert "Run the returned discovery once" in OPERATE
    assert "Gateway validates restrictions and activates proven dependencies" in OPERATE
    assert "`WAAPI_TYPED_CONTAINER_RESPONSE_END`" in OPERATE
    assert "then continue from that response" in OPERATE
    assert "Table imports start `operation-schema audio.importTabDelimited`" in OPERATE
    assert "dynamic columns stay metadata-first" in OPERATE
    skill_compact = " ".join(SKILL.split())
    assert "`object.set` batches and revalidates its dynamic fields" in skill_compact
    assert "only an explicit unknown dynamic property/reference token needs" in skill_compact
    assert "An exact user-supplied native URI without a named route" in OPERATE
    assert "`request-schema <uri>`" in OPERATE
    assert "never infer a URI from natural-language intent" in OPERATE
    assert (
        "request-schema <exact-user-supplied-reflected-function-uri>"
        in SKILL
    )
    assert "No schema-to-preview shortcut" in compact
    assert "gateway.py operation-schema <operation-name>" not in OPERATE
    assert "Follow the schema's sole `input_mode`" in OPERATE
    assert "For `composer`, run only its returned start and action argv" in OPERATE
    assert "For `business_declaration`, run `draft-start`" in OPERATE
    assert "Bind exact owners, parents, and references" in OPERATE
    assert "Supply stable facts such as `volume_db=-4`" in OPERATE
    assert "The Gateway derives Wwise paths, types, metadata scopes" in OPERATE
    assert "Corrections reuse the draft" in OPERATE
    assert "preserving `--expected-revision` and `--apply`" in OPERATE
    assert "there is no `lua.executeFile` operation" in OPERATE
    assert "keep it as one `path` selector" in OPERATE
    assert "Preview change intent" in OPERATE
    assert "configure a default only when the user requested it" in OPERATE
    assert "Exact reflected URIs use `request-schema`" in OPERATE
    assert "Follow the schema's sole `input_mode`" in OPERATE
    assert "Unknown fields fail" in OPERATE
    assert "there is no caller-authored request document" in OPERATE
    assert "Public mutation identities are closed" in OPERATE
    assert "`exact-type-name`" in OPERATE
    assert "next already-requested transaction" in OPERATE
    assert "its executable Preview is visible" in OPERATE
    assert "turn later items design-only" in OPERATE


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
    assert "An exact CamelCase Wwise Authoring command ID" in OPERATE
    assert "`operations.routing_precedence`" in OPERATE
    assert "overrides generic connected-project save intent" in OPERATE
    assert (
        "Ordinary save wording such as `save the current project` or "
        "`保存当前工程` selects `request-schema "
        "ak.wwise.core.project.save`"
        in OPERATE
    )
    assert "never infer or translate that wording into `SaveProject`" in OPERATE
    assert "operation-schema ui.commands.execute" in OPERATE
    assert "operation-schema ui.captureScreen" in OPERATE
    assert "skip `operations`" in OPERATE
    assert "parent-owned `start_child` continuation" in OPERATE
    assert "never Preview a Compound Undo child independently" in OPERATE
    assert "`checked_child_argument`" in OPERATE
    assert "Batch size never establishes file-workflow intent" in compact
    assert "When media import is primary" in compact
    assert "replace media on existing Sounds" in compact
    assert "create a Sound in the same batch" in compact
    assert "`object.set` is never a preliminary schema for that outcome" in compact
    assert "New target-container hierarchy and same-row Event/Switch outcomes" in compact
    assert "use one `audio.import`" in compact
    assert "structure-only descendant" in compact
    assert (
        "never probe `object.create` or a separate assignment first"
        in compact
    )
    assert "`object.set` may carry media only when import is subordinate" in compact
    assert "independent Switch assignment between existing objects" in compact
    assert "same-row import side effect" in compact
    assert (
        "Wholly new structure-only object hierarchy whose requested root does "
        "not already exist and has no media or import-manifest intent"
    ) in compact
    skill_compact = " ".join(SKILL.split())
    assert "For structure-only changes" in skill_compact
    assert "Primary media import uses one `audio.import`" in skill_compact
    assert "business declarations own hierarchy and Event/Switch outcomes" in skill_compact
    assert "Never probe `object.create` or a separate assignment first" in skill_compact
    assert (
        "use `object.set` when import is subordinate to a broader existing-target mutation"
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
        "`object.set` instead binds the exact target and uses returned field/type "
        "discovery plus business-Draft validation"
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
    assert "fixed single-edit routes skip `operations`" in compact
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
    assert compact.count("several fields/properties/references on one root") == 2
    assert compact.count("an ordinary closed object-list change") == 2
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


def test_natural_language_cli_soundbank_generation_uses_gateway_route_catalog() -> None:
    compact = " ".join(OPERATE.split())

    assert "CLI SoundBank generation runs compact `operations`" in compact
    assert "routing_precedence.explicit_cli_soundbank_generation.choose" in compact
    assert "`request-schema ak.wwise.cli.generateSoundbank`" in compact


def test_operate_metadata_and_import_prose_only_rules_are_preserved() -> None:
    compact = " ".join(OPERATE.split())
    for phrase in (
        "A rejected or nonzero Gateway invocation is also a hard stop",
        "`fallback_detail_scan.status` is `partial`",
        "Run the returned discovery once with short English Wwise UI/technical meanings",
        "Copy one returned opaque handle per requested field",
        "bind only user-requested custom properties/references",
        "stable business fields",
        "For table imports, discover only dynamic",
        "ordinary `audio.importTabDelimited` import",
        "do not `cat` or otherwise read the caller's TSV",
        "`SFX` is the built-in nonlocalized import token",
        "Batch `mode` is `create`, `reimport`, or `replace`",
        "Bind the exact existing parent/target once",
        "declare each requested container once as a structure-only descendant",
        "Use `originals_subfolder` only when the user explicitly supplies",
        "bind its exact parent, then provide Event name and business Action",
        "`1 semitone = 100 cents`",
    ):
        assert phrase in compact


def test_operate_maps_only_live_query_accessors_to_mutation_tokens() -> None:
    compact = " ".join(OPERATE.split())

    assert "Returned Field Handles are copied exactly" in compact
    assert "never infer or type a property/reference token" in compact
    assert "Prompt/schema text, cached schemas, and Wwise knowledge" in compact
    assert "Copy one returned opaque handle per requested field" in compact
    assert "`draft-check` revalidates scope, token, dependencies, and value" in compact


def test_operate_cli_and_console_routes_use_only_the_deep_business_plan() -> None:
    compact = " ".join(OPERATE.split())
    assert "Only explicit WwiseConsole, CLI, command-line, or 命令行 wording" in compact
    assert "alone does not establish CLI intent" in compact
    assert "Every reflected `ak.wwise.cli.*` route" in OPERATE
    assert "`ak.wwise.console.project.create`" in OPERATE
    assert "`ak.wwise.console.project.open`" in OPERATE
    assert "`request-schema <exact-uri>`" in compact
    for phrase in (
        "`draft-declare-cli-console-plan`",
        "`--value` per scalar",
        "`--item` per member",
        "`--mapping` per platform/value pair",
        "`--toggle <field> enable|disable`",
        "Never type native CLI option names",
        "The Gateway owns versions",
        "model-supplied global/pre-build/post-build",
        "Wwise 2022 external-source partial success",
        "disconnect or continued reachability never authorizes replay",
        "result-schema-only evidence is not a reopened-project business oracle",
    ):
        assert phrase in compact
    for retired_prompt_mechanic in (
        "`platform` is always an array",
        "flat two-string pair for one platform",
        "omit false/default flags",
        "not yet represented structurally",
    ):
        assert retired_prompt_mechanic not in OPERATE
    assert "`request-schema ak.wwise.core.audio.convert`" in compact
    assert "user's exact absolute `io_root`" in compact


def test_operate_host_schema_tone_and_project_routes_hide_native_mechanics() -> None:
    compact = " ".join(OPERATE.split())

    for phrase in (
        "`ak.wwise.waapi.getSchema`",
        "`ak.wwise.debug.generateToneWAV`",
        "`ak.wwise.ui.project.*`",
        "continues directly through `waapi-schema`",
        "one complete `draft-declare-host-plan`",
        "zero-based `waveform_channels`",
        "derives waveform spelling and the native channel bitmask",
        "Every `ak.wwise.ui.project.*` phase requires Wwise Authoring",
    ):
        assert phrase in compact
    assert "waveformChannelMask" not in OPERATE
    assert "autoCheckOutToSourceControl" not in OPERATE
    assert "onMigrationRequired" not in OPERATE


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
    assert "copying the complete string verbatim once" in compact
    assert "Windows normally selects `model_command`" in compact
    assert "encoded `shell_command` is audit/fallback unless explicitly selected" in compact
    assert "Do not render diagnostic `full_argv`" in compact
    assert "Truncated/incomplete instructions stop without inferred fallback" in compact
    assert "run `confirm --help`" in compact
    assert "a status/check request stops after `transaction-show`" in compact
    assert "a verify-only request never executes" in compact
    assert "`execution_in_progress`: no state change" in compact
    assert "retry only in a later turn" in compact
    assert "after the prior item reaches terminal verification" in compact
    assert (
        "a successful `verify` immediately starts the next already-requested "
        "transaction in the same turn and stops only when its executable Preview "
        "is visible"
    ) in compact
    assert "Never infer, add, combine, reorder, or turn later items design-only" in compact
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
    assert "`ak.wwise.cli.migrate` ends at complete `execute`" in compact
    assert "run no later Agent tools/reads" in compact
    assert "caller-owned harness outside the Skill sequence" in compact
    assert "Managed openers may leave cleanup uncertain" in compact
    assert "never synthesize code" in compact
    assert "Work Unit reversal" in compact
    assert "serialize the successful Gateway `agent_result` verbatim" in compact


def test_complex_query_projection_documents_derived_field_first_mention_order() -> None:
    flattened = " ".join(QUERY.split())
    assert "repeated `--include` values in caller order" in flattened
    assert "custom `properties` and `references` maps" in flattened


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
    assert "For five-version totals, read coverage then run exactly" in SKILL
    assert "it includes every route count" in SKILL
    assert "Row filters omit `--summary-only`" in SKILL
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
    skill_compact = " ".join(SKILL.split())
    for phrase in (
        "When the visible conversation lacks an introduction",
        "Only `/waapi-skill` or a Skill link: run one offline `config-show`",
        "Read the injected `SKILL.md` exactly once",
        "A successful read is complete; a second `SKILL.md` read is forbidden",
        "The next reply",
        "`session_context.one_time_introduction.facts` together",
        "Skill loaded",
        "WAAPI address",
        "in the user's language, in two short paragraphs",
        "Wwise 适配版本 (localize); then policy and modes",
        "configured, not connected unless proved live",
        "Closing questions are free prose, in a new paragraph",
        "Never announce before Gateway, split facts, use memory",
        "status table",
        "With a request, reuse its first required Gateway result; no extra call",
        "Pure explanation: one offline `config-show`",
        "Never connect solely for welcome",
        "Repeat only on request or changed facts",
        "not later Skill invocations",
        "Send machine answers separately",
    ):
        assert phrase in skill_compact
    assert "The entry file owns the one-time conversation introduction for every lane" in SETUP
    assert "emit the Gateway's structured `session_context.one_time_introduction` atomically" in SETUP
    assert "Do not add policy or implementation narration to a simple read-only result" not in SETUP
    assert "do not repeat policy narration in every simple read-only result" in SETUP
    assert "project modification policy" not in QUERY.lower()


def test_named_get_info_uses_status_as_its_only_route() -> None:
    assert "`status` is the sole Gateway-owned `getInfo` route" in SKILL
    assert "Do not use `request-schema` or `typed-zero-call`" in SKILL
    assert "needs only this `SKILL.md`" in SKILL
    assert "do not read the setup or query reference" in SKILL
    assert "run `status` directly and do not read `waapi-setup.md`" in SKILL
    assert (
        "Treat the named `getInfo` result's `processId` as the requested live "
        "process identity" in SKILL
    )
    assert "finish from that Gateway evidence without a system process lookup" in SKILL


def test_business_declarations_omit_every_unrequested_optional_fact() -> None:
    assert (
        "Omit every optional business field the user did not explicitly supply"
        in OPERATE
    )
    assert "defaults, examples, expected results, and verifier facts are not inputs" in OPERATE
