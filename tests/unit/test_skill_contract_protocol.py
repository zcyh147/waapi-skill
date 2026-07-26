from __future__ import annotations

import json
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
SKILL = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
QUERY = (SKILL_ROOT / "references" / "waapi-query.md").read_text(encoding="utf-8")
SETUP = (SKILL_ROOT / "references" / "waapi-setup.md").read_text(encoding="utf-8")
OPERATE = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(encoding="utf-8")
COVERAGE = (SKILL_ROOT / "references" / "waapi-coverage.md").read_text(encoding="utf-8")


def test_common_reads_use_closed_gateway_before_optional_references() -> None:
    assert SKILL.index("## Fixed gateway commands") < SKILL.index("## Routing")
    assert "Treat gateway JSON as authoritative" in SKILL
    assert "Every gateway command must leave its complete JSON visible" in SKILL
    assert "never suppress or redirect its output" in SKILL
    assert "request a zero/short tool-output budget" in SKILL
    assert "continue from the shell exit code alone" in SKILL
    assert "If no complete JSON is visible, stop" in SKILL
    assert "Read one lane reference only when the fixed command table does not fully answer" in SKILL
    assert "There is no raw-client fallback" in QUERY


def test_machine_readable_agent_result_is_terminal_for_fixed_reads_and_transactions() -> None:
    assert "any successful gateway payload contains `agent_result`" in SKILL
    assert "This rule applies to fixed reads as well as transactions" in SKILL
    assert "Do not reconstruct its fields from the prompt, `normalized`" in SKILL
    assert "do not run another command after receiving it" in SKILL
    assert "metadata types --summary-only" in QUERY
    assert "compact-serialize that object exactly" in QUERY


def test_media_pool_reference_classification_uses_one_closed_versioned_query() -> None:
    section = QUERY.split("#### Closed original-file reference classification", 1)[1].split(
        "## Query examples", 1
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
    assert "Do not add `--where-json`, `--select`, `--all-results`, or `--return-field`" in section_flat
    assert "fixed `id,path,originalFilePath` projection" in section_flat
    assert "emits no raw AudioFileSource inventory" in section_flat
    assert "never perform this join in model-authored code" in QUERY


def test_media_pool_reference_classification_documents_terminal_result_and_boundaries() -> None:
    section = QUERY.split("#### Closed original-file reference classification", 1)[1].split(
        "## Query examples", 1
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
    assert "make the first shell action only the injected `SKILL.md` read" in SKILL
    assert "Do not prepend or append `pwd`, `git`, `rg`, `ls`, `find`, `printf`" in SKILL
    assert "Before any other shell action, read only the injected absolute SKILL.md locator" in SKILL
    assert "After this entry file has been loaded" in SKILL
    assert "scoped to the whole visible conversation/task, not to each user turn" in SKILL
    assert "do not read it again on a confirmation or other transaction-continuation turn" in SKILL
    assert "same absolute file" in SKILL
    assert "this is the only combined read allowed" in SKILL
    assert "Never combine a reference read, gateway invocation, or any other commands" in SKILL


def test_exact_identity_query_is_complete_in_entry_file() -> None:
    command = (
        "query-object --path '<exact-object-path>' --return-field id "
        "--return-field name --return-field type --return-field path"
    )
    assert command in SKILL
    assert "Keep all four return fields explicit" in SKILL
    assert "do not read the query reference before or after it" in SKILL
    assert "Conditional read for a query not fully covered" in SKILL
    assert "keep those four fields explicit for an exact path/GUID identity lookup" in QUERY


def test_complex_query_guidance_preserves_tokens_pushdown_and_user_bounds() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        "Volume -> `@Volume`",
        "Output Bus -> `OutputBus` (never `@OutputBus`)",
        "Source language -> `audioSource:language`",
        "direct child count -> `childrenCount`",
        "exactly one returned `AudioFileSource` has `parent.id` exactly equal to that Sound's `id`",
        "Do not report the language as missing when this exact child-source evidence exists",
        "do not associate by row position, similar names, or path prefixes",
        "A predicate array means AND only",
        "For `A and (B or C)`, push the common `A`",
        "copy that exact number to `--take`",
        "ask for a limit instead of inventing one",
    ):
        assert phrase in query_flat
    assert "--where-json '{\"field\":\"type\",\"operator\":\"=\",\"value\":\"Sound\"}' --take 24" in query_flat
    assert "--return-field @Volume --return-field notes --return-field OutputBus" in query_flat


def test_pure_and_query_pushes_every_supported_conjunct_in_canonical_order() -> None:
    query_flat = " ".join(QUERY.split())
    for phrase in (
        'Words such as "simultaneously", "all of the following conditions", or “同时满足” introduce a pure AND',
        "Put every supported conjunct into one `--where-json` array",
        "preserving the user's condition order",
        "Do not submit only the type predicate",
        "report, grouping, or sorting in their first-mention order",
        "additional filter-only fields",
        "`isIncluded` is appended last because it is filter-only",
    ):
        assert phrase in query_flat
    assert (
        "--where-json '[{\"field\":\"type\",\"operator\":\"=\",\"value\":\"Sound\"},"
        "{\"field\":\"@Volume\",\"operator\":\"<=\",\"value\":-6.0},"
        "{\"field\":\"notes\",\"operator\":\":\",\"value\":\"mix-review\"},"
        "{\"field\":\"isIncluded\",\"operator\":\"=\",\"value\":true}]' --take 12"
    ) in query_flat
    assert (
        "--return-field @Volume --return-field notes "
        "--return-field audioSource:language --return-field OutputBus "
        "--return-field isIncluded"
    ) in query_flat


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
        "query-object --type Sound --select parent --where-json "
        "'[{\"field\":\"path\",\"operator\":\":\",\"value\":\"\\\\Actor-Mixer Hierarchy\\\\Default Work Unit\\\\ParentReview\"},"
        "{\"field\":\"type\",\"operator\":\"=\",\"value\":\"RandomSequenceContainer\"},"
        "{\"field\":\"childrenCount\",\"operator\":\">=\",\"value\":3},"
        "{\"field\":\"notes\",\"operator\":\":\",\"value\":\"parent-review\"}]' --take 10"
    ) in query_flat
    assert (
        "--return-field childrenCount --return-field notes "
        "--return-field OutputBus"
    ) in query_flat


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
        "--select ancestors --where-json "
        "'{\"field\":\"type\",\"operator\":\"!=\",\"value\":\"Project\"}' --take 8"
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
    command = (
        "--timeout 120 wait-topic ak.wwise.core.soundbank.generated "
        "--options-json"
    )
    assert command in QUERY
    assert "--timeout 10 wait-topic ak.wwise.core.soundbank.generated" not in QUERY
    assert "gateway itself keeps the ordinary 10-second omitted-duration default" in QUERY
    assert "explicitly pass gateway-global `--timeout 120`" in QUERY
    assert "an explicit Skill-selected timeout, not a different gateway default" in QUERY
    assert "tell the user that this subscription will use 120 seconds" in QUERY
    assert "user-supplied positive finite duration or explicit no-time-limit request still takes precedence" in QUERY


def test_topic_wait_duration_policy_is_explicit_and_output_remains_bounded() -> None:
    skill_flat = " ".join(SKILL.split())
    query_flat = " ".join(QUERY.split())

    for phrase in (
        "tell the user the effective waiting policy in one natural sentence",
        "ordinary 10-second default",
        "converting units to seconds without rounding",
        "`--timeout <positive-finite-seconds>` position before `wait-topic`",
        "`wait-topic` subcommand flag `--no-timeout`",
        "until the requested 1–64 matching events have been collected or the user cancels it",
        "it is not an unlimited output stream",
        "Never combine `--timeout` with `--no-timeout`",
    ):
        assert phrase in skill_flat

    for phrase in (
        "An ordinary omitted duration uses 10 seconds",
        "convert its units to seconds without rounding",
        "Do not silently clamp it",
        "is its default or recommendation, not a maximum",
        "add the subcommand flag `--no-timeout`",
        "the command still returns one terminal JSON document",
        "after success, timeout, or user cancellation",
        "event count, result size, and terminal JSON output remain bounded",
    ):
        assert phrase in query_flat

    assert "gateway.py wait-topic <topic-uri>" in SKILL
    assert (
        "gateway.py --timeout <positive-finite-seconds> wait-topic <topic-uri>"
        in SKILL
    )
    assert "gateway.py wait-topic <topic-uri> --no-timeout" in SKILL
    assert "这次使用默认的 10 秒等待时间" in SKILL
    assert "直到收齐 `<N>` 个匹配事件或你让我停止" in SKILL


def test_ordinary_wwise_work_forbids_agent_authored_code() -> None:
    for phrase in ("inline Python", "new `.py`/`.js`/`.sh` helper", "direct client construction"):
        assert phrase in SKILL
    assert "Skill development, testing, or debugging" in SKILL
    assert "Do not import builders or planners from inline Python" in OPERATE
    assert "That boundary does not authorize code generation" in OPERATE
    assert "Do not write code to bypass it" in OPERATE


def test_operate_lane_uses_real_transaction_cli_in_order() -> None:
    new_transaction_sequence = (
        "gateway.py operation-schema <operation-name>",
        "preview --request-json",
    )
    continuation_sequence = (
        "transaction-show <transaction-id>",
        "confirm <transaction-id> --confirmation-token <gateway-token>",
        "execute <transaction-id>",
        "verify <transaction-id>",
    )
    new_positions = [OPERATE.index(item) for item in new_transaction_sequence]
    continuation_positions = [OPERATE.index(item) for item in continuation_sequence]
    assert new_positions == sorted(new_positions)
    assert continuation_positions == sorted(continuation_positions)
    assert "`operations` first: that command is only for broad capability-inventory questions" in OPERATE
    assert "Do not call `operations`, `operation-schema`, or `preview` first" in OPERATE
    assert "Only after a later user message clearly confirms" in OPERATE
    assert "Never run `confirm` merely because the original request used an imperative verb" in OPERATE
    for document in (SKILL, OPERATE):
        assert "`next_command.full_argv`" in document
        assert "`next_command.shell_command`" in document
        assert "returned string verbatim as one shell tool call" in document
        assert "`shell_family`" in document
        assert "absolute `scripts/run.py`" in document
        assert "never reconstruct, shorten, or normalize" in document.lower()
        assert "`confirm --help`" in document
        assert "--confirmation-token" in document
        assert "fall back to the displayed artifact hash" in document.lower()
        assert "`--artifact-hash`" not in document
    assert "do not translate `full_argv` into a command yourself" in SKILL
    assert "do not render `full_argv`, re-quote it, or rebuild" in OPERATE
    assert "short opaque `confirmation.token`" in SKILL
    assert "Gateway-owned short token" in OPERATE
    assert "Do not generate, shorten, validate from spelling, reconstruct, or substitute the token" in OPERATE
    assert "contract `waapi-skill.confirmation-binding/v1`" in OPERATE


def test_operation_schema_owns_the_complete_versioned_request_envelope() -> None:
    for document in (SKILL, OPERATE):
        flattened = " ".join(document.split())
        assert "`request_envelope_policy.status` is `ready`" in flattened
        assert "copy `request_envelope` exactly" in flattened
        assert "replace only" in flattened
        assert "never omit" in flattened
        assert "`version`" in flattened


def test_operation_schema_owns_exact_argument_paths_and_waapi_call_siblings() -> None:
    flattened = " ".join(OPERATE.split())
    assert "`request_envelope_policy.argument_paths`" in flattened
    assert "`api`, `args`, `options`, and `io_root` are siblings" in flattened
    assert "`io_root` is never nested inside the reflected API's `args`" in flattened


def test_transaction_continuation_is_the_final_structured_actionable_tail() -> None:
    for document in (SKILL, OPERATE):
        flattened = " ".join(document.split())
        assert "`next_command` after `session_context`" in flattened
        assert "final actionable top-level field" in flattened
        assert "mirrors that same object" in flattened
        assert "final field of its terminal `agent_result`" in flattened


def test_operate_reference_has_one_visible_completion_sentinel() -> None:
    assert OPERATE.count("WAAPI_OPERATE_REFERENCE_END") == 2
    assert OPERATE.rstrip().endswith("<!-- WAAPI_OPERATE_REFERENCE_END -->")
    for document in (SKILL, OPERATE):
        assert "If the sentinel is absent" in document or "when it is absent" in document
        assert "partial reread" in document


def test_complex_query_projection_documents_derived_field_first_mention_order() -> None:
    flattened = " ".join(QUERY.split())
    assert "scanning the user's requested output left to right" in flattened
    assert "`id`, `name`, `type`, `path`, `parent`, `audioSource:language`, `@Volume`," in QUERY
    assert "`notes`" in QUERY


def test_reviewed_raw_transaction_fast_routes_skip_catalog_discovery() -> None:
    assert "except for the reviewed direct `waapi.call` fast routes named below" in SKILL
    assert "or a reviewed direct `waapi.call` fast route named in the operate lane below" in SKILL
    assert "the four deterministic `ak.wwise.cli` transaction rows" in SKILL
    assert "route's first gateway command is `operation-schema waapi.call`" in SKILL
    assert "do not run `describe` or `capabilities` first" in SKILL
    assert "When the configured/runtime Wwise version is `2022.1`" in SKILL
    assert "If the version is not visible before that first gateway call" in SKILL
    assert "read its returned `session_context`" in SKILL
    assert "If it reports another version, do not preview" in SKILL
    assert "For every other known Wwise version" in SKILL
    assert "never reuse the 2022.1 field mapping" in SKILL

    assert "except for the reviewed direct `waapi.call` fast routes below" in OPERATE
    assert "Deterministic Wwise `2022.1` `ak.wwise.cli` request mapping" in OPERATE
    assert "These four CLI no-`describe` fast routes apply only to Wwise `2022.1`" in OPERATE
    assert "run `operation-schema waapi.call` as the first gateway command" in OPERATE
    assert "do not run `describe` or `capabilities` first" in OPERATE
    assert "For any other already-known configured/runtime Wwise version" in OPERATE
    assert "do not reuse these field rules" in OPERATE
    assert "When the version was not visible before that call" in OPERATE
    assert "apply the mapping below only if it reports `2022.1`" in OPERATE
    assert "If it reports another version, do not preview" in OPERATE
    for api in (
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.migrate",
        "ak.wwise.core.audio.convert",
    ):
        assert f"`{api}`" in OPERATE
    assert "The reviewed raw Authoring conversion route is a no-hidden-argument and no-`describe` fast route" in OPERATE
    assert "without `describe` or `capabilities`" in OPERATE
    assert "reports either `2024.1` or `2025.1`" in OPERATE
    assert "Outside the reviewed direct fast routes above" in OPERATE


def test_audio_convert_fast_route_is_early_and_unique() -> None:
    heading = "### Deterministic Wwise `2024.1` / `2025.1` Authoring audio conversion request mapping"
    marker = "`ak.wwise.core.audio.convert` (`2024.1` / `2025.1`)"

    assert OPERATE.count(heading) == 1
    assert OPERATE.count(marker) == 1
    assert (
        OPERATE.index("## Choose the transaction phase first")
        < OPERATE.index(heading)
        < OPERATE.index("## Closed transaction flow")
        < OPERATE.index("## Request v1")
    )


def test_audio_convert_fast_route_closes_prompt_mapping_and_rereads() -> None:
    section = OPERATE.split(
        "### Deterministic Wwise `2024.1` / `2025.1` Authoring audio conversion request mapping",
        1,
    )[1].split("## Closed transaction flow", 1)[0]

    for token in (
        "`args.objects`",
        "`args.platforms`",
        "`args.languages`",
        "`options:{}`",
        "requires all three keys",
        "non-empty ordered JSON array of strings",
        "never use object wrappers",
        '`{"object":"..."}`',
        'maps to `languages:["SFX"]`',
        "unless the user explicitly names localized languages",
        "exactly as `io_root`",
    ):
        assert token in section
    for version in ("2024.1", "2025.1"):
        assert (
            f'{{"contract":"waapi-skill.operation-request/v1","version":"{version}",'
            '"operation":"waapi.call","arguments":{"api":"ak.wwise.core.audio.convert",'
            '"args":{"objects":["<exact-wwise-object-path>"],"platforms":["<platform>"],'
            '"languages":["SFX"]},"options":{},"io_root":'
            '"<absolute-allowed-conversion-root>"}}'
        ) in section
    assert "do not search recursively or include unnamed descendants" in section
    assert "Do not add or remove a target, platform, language, or root" in section
    assert "After the one complete read of this reference" in section
    assert "do not reread any line range with `sed`, `head`, `tail`, `rg`" in section
    assert "proceed directly to the one gateway command above" in section


def test_audio_convert_uses_gateway_owned_schema_contract() -> None:
    flattened = " ".join(SKILL.split())

    assert (
        "returned Gateway-owned `direct_fast_route_contract.canonical_request_template`"
        in flattened
    )
    assert "never omit `args.languages`" in flattened
    assert 'literal `languages:["SFX"]`' in flattened
    assert "does not apply to any other `waapi.call` URI" in flattened


def test_2022_cli_json_cardinality_shapes_match_the_runtime_compiler() -> None:
    mapping = OPERATE.split(
        "### Deterministic Wwise `2022.1` `ak.wwise.cli` request mapping", 1
    )[1].split(
        "### Deterministic Wwise `2024.1` / `2025.1` Authoring audio conversion request mapping",
        1,
    )[0]

    assert "for every applicable CLI route" in mapping
    assert "field contracts, not case-specific examples" in mapping
    assert (
        '`bank`: one Bank name or one absolute Bank-list file is a JSON string '
        '(`"Dialogue_Chapter01"`); multiple Bank names are a JSON array '
        '(`["Dialogue_Chapter01","Music"]`)'
    ) in mapping
    assert '`platform`: always a JSON array, including one platform (`["Windows"]`)' in mapping
    assert (
        '`language` and `import-definition-file`: one value is a JSON string '
        '(`"value"`); multiple values are a JSON array (`["value-1","value-2"]`)'
    ) in mapping
    assert (
        "`source-file` is exactly one `.wsources` string"
        in mapping
    )
    assert "real 2022.1 runs process only the first member" in mapping
    assert (
        "`project`, `io_root`, `cache`, and `root-output-path`: always scalar JSON strings"
    ) in mapping
    assert (
        "The tab-delimited route likewise uses scalar strings for `project`, "
        "`tab-delimited-import-file`, `tab-delimited-operation`, and `import-language`"
    ) in mapping
    assert "the migrate route's `project` is also a scalar string" in mapping
    assert "Never wrap one of these fields in a single-item array" in mapping
    assert (
        '`convertExternalSource` `output`: always bind each platform to its final physical '
        'output directory. One platform uses a flat pair '
        '(`["Windows","/absolute/windows-output"]`)'
    ) in mapping
    assert (
        "Do not use scalar `\"/absolute/output\"` for a platform-specific final directory"
    ) in mapping
    assert (
        "Platform/value mappings such as `source-by-platform`, `output`, "
        "and `soundbank-path`"
    ) in mapping
    assert 'one pair is a flat two-string array (`["Windows","/absolute/path"]`)' in mapping
    assert (
        'multiple pairs are an array of two-string arrays '
        '(`[["Windows","/windows"],["Mac","/mac"]]`)'
    ) in mapping
    assert "Do not add an outer array around a single pair" in mapping
    assert "each platform may occur only once in `source-by-platform`" in mapping
    assert "real runs process only the last entry for a repeated platform" in mapping
    assert "preserve this complete JSON" in mapping
    assert "replace only the angle-bracket values" in mapping
    assert '"operation":"waapi.call"' in mapping
    assert '"api":"ak.wwise.cli.convertExternalSource"' in mapping
    assert (
        '"output":[["Windows","<absolute-windows-output>"],'
        '["Mac","<absolute-mac-output>"]]' in mapping
    )
    assert '"io_root":"<deepest-common-output-directory>"}}' in mapping
    assert (
        "outputs `/case/cli-io/windows` and `/case/cli-io/mac` require the exact "
        "`io_root` `/case/cli-io`, never the broader `/case`"
    ) in " ".join(mapping.split())
    convert_templates = [
        line
        for line in mapping.splitlines()
        if line.startswith('{"contract":"waapi-skill.operation-request/v1"')
        and '"api":"ak.wwise.cli.convertExternalSource"' in line
    ]
    assert len(convert_templates) == 2
    convert_payloads = [json.loads(template) for template in convert_templates]
    shared_payload = next(
        payload
        for payload in convert_payloads
        if "source-file" in payload["arguments"]["args"]
    )
    assert shared_payload["arguments"]["args"]["source-file"] == (
        "<absolute-source.wsources>"
    )
    assert shared_payload["arguments"]["args"]["output"] == [
        ["Windows", "<absolute-windows-output>"],
        ["Mac", "<absolute-mac-output>"],
    ]
    source_by_platform_payloads = [
        payload
        for payload in convert_payloads
        if "source-by-platform" in payload["arguments"]["args"]
    ]
    assert len(source_by_platform_payloads) == 1
    platform_specific_payload = source_by_platform_payloads[0]
    assert platform_specific_payload["arguments"]["args"]["source-by-platform"] == [
        ["Windows", "<absolute-windows-source.wsources>"],
        ["Mac", "<absolute-mac-source.wsources>"],
    ]
    assert all(
        payload["arguments"]["io_root"] == "<deepest-common-output-directory>"
        for payload in convert_payloads
    )
    compact_mapping = " ".join(mapping.split())
    assert "Multiple `.wsources` files for one platform are a structured" in mapping
    assert "gateway rejects both partial-success shapes" in compact_mapping
    assert "one caller-prepared union `.wsources`" in compact_mapping
    assert "separately previewed transactions" in compact_mapping
    generate_template = next(
        line
        for line in mapping.splitlines()
        if line.startswith('{"contract":"waapi-skill.operation-request/v1"')
        and '"api":"ak.wwise.cli.generateSoundbank"' in line
    )
    generate_payload = json.loads(generate_template)
    generate_arguments = generate_payload["arguments"]
    assert generate_arguments == {
        "api": "ak.wwise.cli.generateSoundbank",
        "args": {
            "project": "<absolute-project.wproj>",
            "bank": ["<bank-1>", "<bank-2>"],
            "platform": ["Windows", "Mac"],
            "skip-languages": True,
            "clear-audio-file-cache": True,
            "header-file": True,
            "soundbank-path": [
                ["Windows", "<absolute-windows-output>"],
                ["Mac", "<absolute-mac-output>"],
            ],
            "cache": "<absolute-cache>",
            "root-output-path": "<absolute-root-output>",
        },
        "options": {},
        "io_root": "<deepest-common-ancestor-of-soundbank-path-cache-root-output>",
    }
    assert "Derive `io_root` from exactly the resolved path values" in mapping
    assert "never include `project`, the `.wproj` directory, or any other path" in mapping
    assert "The `io_root` placeholder is computed from only" in mapping
    assert "the `project` path does not participate" in " ".join(mapping.split())
    assert "O22-CLI-" not in mapping


def test_2022_cli_mapping_is_single_and_precedes_the_audio_convert_fast_route() -> None:
    heading = "### Deterministic Wwise `2022.1` `ak.wwise.cli` request mapping"
    audio_heading = (
        "### Deterministic Wwise `2024.1` / `2025.1` Authoring audio conversion request mapping"
    )

    assert OPERATE.count(heading) == 1
    assert (
        OPERATE.index("## Choose the transaction phase first")
        < OPERATE.index(heading)
        < OPERATE.index(audio_heading)
        < OPERATE.index("## Closed transaction flow")
    )
    assert "After one complete terminal `verify` result, stop all tool use" in OPERATE[:2_000]
    assert (
        "For `ak.wwise.cli.migrate`, its one complete `execute` result is that "
        "terminal boundary instead"
    ) in OPERATE[:2_000]
    assert "do not inspect the filesystem or repository for extra business proof" in OPERATE[:2_000]


def test_operate_state_directory_is_caller_owned_and_never_probed() -> None:
    for document in (SKILL, OPERATE):
        assert "omit `--state-dir`" in document
        assert "Never run `env`, `printenv`" in document
        assert "discover `WAAPI_SKILL_STATE_DIR`" in document
        assert "trusted absolute path" in document
        assert "structured state-directory error or boundary" in document

    assert "gateway.py --state-dir /absolute/state/dir" not in OPERATE
    for command in (
        "gateway.py preview --request-json",
        "gateway.py transaction-show <transaction-id> --summary-only",
        "gateway.py confirm <transaction-id> --confirmation-token <gateway-token>",
        "gateway.py execute <transaction-id>",
        "gateway.py verify <transaction-id>",
    ):
        assert command in OPERATE


def test_transaction_state_never_grants_authority_and_hash_alone_is_insufficient() -> None:
    assert "A status or check request stops after `transaction-show`" in SKILL
    assert "the returned state only constrains which actions are legal" in SKILL
    assert "an artifact hash alone is not a transaction lookup key" in SKILL

    assert "A transaction id is required: an artifact hash alone is not a lookup key" in OPERATE
    assert "A status or check request stops after `transaction-show`" in OPERATE
    assert "state only constrains which actions are legal and never authorizes an action by itself" in OPERATE
    assert "An explicit verify-only request" in OPERATE


def test_confirmed_preview_risks_are_reported_but_do_not_become_a_second_veto() -> None:
    assert (
        "Risks and verifier limits already disclosed by a successful immutable preview "
        "are decision information, not a second Agent veto"
    ) in OPERATE
    assert "after the user clearly confirms that same request, continue" in OPERATE
    assert (
        "merely calls the already connected project a copy or isolated project "
        "does not change scope"
    ) in OPERATE
    assert "identifies another project/path or asks to switch or open one" in OPERATE
    assert "a genuine project or request change instead requires a new preview" in OPERATE


def test_transaction_show_is_a_visible_json_safety_gate() -> None:
    assert "do not reread either file in the same visible conversation/task" in SKILL
    assert "proceeding directly from the already-visible instructions" in SKILL
    assert "if `confirm` does not return complete visible JSON" in SKILL
    assert "stop before `execute` or `verify`" in SKILL
    assert "`transaction-show` is the continuation safety gate" in SKILL
    assert "even with exit code `0` or a transaction id/hash" in SKILL
    assert "do not retry the show in that turn" in SKILL

    assert "This show is a safety gate, not a best-effort read" in OPERATE
    assert "do not reread either file on the continuation turn" in OPERATE
    assert "With the id, proceed directly. The first gateway command is" in OPERATE
    assert "Treat these as separately gated commands, never as a batch" in OPERATE
    assert "if `confirm` returns empty, truncated, non-json" in OPERATE.lower()
    assert "stop before `execute` and `verify` even when the shell reports exit code `0`" in OPERATE
    assert "even with exit code `0` or a previously known id/hash" in OPERATE
    assert "stop without any later transaction command" in OPERATE


def test_preview_rejection_is_a_same_turn_stop_and_replace_boundary_is_unambiguous() -> None:
    assert "A rejected `preview`, invalid JSON/shell invocation" in SKILL
    assert "do not fix and retry the command in the same turn" in SKILL
    assert "A `preview` result is also a hard same-turn boundary" in OPERATE
    assert "Do not repair a bracket" in OPERATE
    assert "authorization boundary, not the object being replaced" in OPERATE
    assert "normally set both `parent` and `replace_owned_root` to `P`" in OPERATE
    assert "never set `replace_owned_root` to `P\\\\X`" in OPERATE


def test_indeterminate_execute_stops_without_verify_or_ad_hoc_readback() -> None:
    assert "reports `executed_unverified`" in SKILL
    assert "`status` and `state` both `indeterminate` is terminal for that turn" in SKILL
    assert "without `verify`, retry, `transaction-show`, another gateway call, filesystem inspection" in SKILL
    assert "requires a new user request and must use a packaged read-only Skill route" in SKILL

    assert "Continue from `execute` to `verify` only when" in OPERATE
    assert "`status` and `state` both `indeterminate` is terminal for that turn" in OPERATE
    assert "do not call `verify`, retry, run another gateway command, inspect files" in OPERATE
    assert "Any later diagnosis requires a new user request" in OPERATE


def test_verify_payload_is_terminal_and_must_not_be_double_checked() -> None:
    assert "Except for `ak.wwise.cli.migrate`'s terminal `execute`" in SKILL
    assert "dedicated operations return their live readback" in SKILL
    assert "generic `waapi.call` returns reflected result-schema evidence" in SKILL
    assert "Do not add `query-object`, `call`, or another gateway command" in SKILL
    assert "Except for migration's terminal `execute`, the `verify` payload is the terminal authority" in OPERATE
    assert "Never append `query-object`, direct `call`, or another gateway command" in OPERATE
    assert "then stop without an extra query" in OPERATE


def test_closed_multi_transaction_workflow_previews_only_the_next_item() -> None:
    assert "original request that already closed and ordered multiple independent transactions" in SKILL
    assert "run only the next transaction's `operation-schema` and immutable `preview`" in SKILL
    assert "never execute that next preview in the same turn" in SKILL

    assert "original user request that already closed and ordered multiple independent transactions" in OPERATE
    assert "successful non-final `verify` may be followed only by the next transaction's `operation-schema`" in OPERATE
    assert "It never authorizes the next `confirm` or `execute`" in OPERATE
    assert "The final transaction's `verify` remains the terminal command" in OPERATE
    assert "This exception never permits same-turn preview plus execution" in OPERATE


def test_migration_execute_is_terminal_and_defers_to_the_reopened_oracle() -> None:
    assert "`ak.wwise.cli.migrate` is the narrow exception" in SKILL
    assert "after its one complete `execute` JSON, stop all gateway activity immediately" in SKILL
    assert "do not run generic `verify`, `status`, `query-object`, `call`" in SKILL
    assert "caller-owned reopened-project oracle" in SKILL
    assert "`ak.wwise.cli.migrate` is the narrow exception" in OPERATE
    assert "its one `execute` is the terminal gateway invocation" in OPERATE
    assert "Read the complete JSON returned by each transaction command" in OPERATE
    assert "Never suppress or redirect gateway output" in OPERATE
    assert "infer a successful state transition from exit code `0`" in OPERATE
    assert "Once that complete execute JSON is visible, stop all gateway activity immediately" in OPERATE
    assert "another gateway command to reopen or inspect the migrated project" in OPERATE
    assert "oracle runs outside the Skill command sequence" in OPERATE
    assert "run no more Agent tools at all" in OPERATE
    assert "no `sed`, `rg`, `cat`, `find`, `ls`, `head`, or `tail`" in OPERATE
    assert "The Agent must not read the project, `.wproj`/`.wwu` files" in OPERATE
    assert "broker evidence, lifecycle evidence, logs, `business-oracle-plan`" in OPERATE
    assert "Only the caller-owned harness—not the Agent—may close Wwise" in OPERATE
    assert "does not apply to `ak.wwise.cli.migrate`" in OPERATE
    assert "even when its durable transaction state is named `executed_unverified`" in OPERATE
    invariants = OPERATE.split("## Invariants enforced by the runtime", 1)[1].split(
        "## Result handling", 1
    )[0]
    assert "Except for `ak.wwise.cli.migrate`" in invariants
    assert "do not run `verify` even when execute reports `executed_unverified`" in invariants
    assert "the complete execute payload is the terminal authority" in invariants
    result_handling = OPERATE.split("## Result handling", 1)[1]
    assert "If the immutable request targets `ak.wwise.cli.migrate`" in result_handling
    assert "do not add a gateway inspection" in result_handling


def test_operate_examples_are_generic_and_preserve_requested_import_notes() -> None:
    assert "gateway.py operation-schema <operation-name>" in OPERATE
    assert "gateway.py operation-schema object.create" not in OPERATE
    assert '"notes": "Imported through the WAAPI Skill transaction gateway"' in OPERATE


def test_object_create_natural_type_labels_have_exact_wwise_tokens() -> None:
    expected_mappings = {
        "Actor Mixer / ActorMixer / Actor Mixer 对象": "ActorMixer",
        "Random Container / 随机容器": "RandomSequenceContainer",
        "Blend Container / 混合容器": "BlendContainer",
        "Sound / 声音对象": "Sound",
    }
    for natural_label, exact_token in expected_mappings.items():
        assert f"{natural_label} → `{exact_token}`" in OPERATE
    assert "never `RandomContainer`" in OPERATE


def test_operation_request_is_closed_and_runtime_owned_metadata_cannot_be_injected() -> None:
    assert '"contract": "waapi-skill.operation-request/v1"' in OPERATE
    for kind in ('"kind":"id"', '"kind":"path"', '"kind":"waql"', '"kind":"scoped-name"'):
        assert kind in OPERATE
    for forbidden_input in ("identity rows", "`property_info`", "`reference_info`", "dispatcher args/options", "WAAPI URI"):
        assert forbidden_input in OPERATE
    assert "unknown fields fail" in OPERATE


def test_dedicated_operations_and_generic_transaction_fallback_are_truthful() -> None:
    for operation in (
        "object.create",
        "object.set",
        "object.setLinked",
        "object.setRTPC",
        "object.delete",
        "object.setName",
        "object.setNotes",
        "object.setProperty",
        "object.setReference",
        "audio.import",
        "audio.importTabDelimited",
        "soundbank.setInclusions",
        "soundbank.generate",
        "soundbank.convertExternalSources",
        "soundbank.processDefinitionFiles",
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
        "ui.captureScreen",
        "ui.commands.execute",
        "ui.commands.register",
        "ui.commands.unregister",
    ):
        assert f"`{operation}`" in OPERATE
    assert "`waapi.call`: one exact version-reflected API" in OPERATE
    assert "`waapi.undoGroup`: one display name plus 1–32 version-allowlisted" in OPERATE
    assert "accepted only when the catalog transaction row explicitly lists `waapi.call`" in OPERATE
    assert "`waapi.call` is a hard-rejected bypass for that URI" in OPERATE
    assert "result-schema verification" in OPERATE
    for older_semantic_boundary in ("object.copy", "object.move"):
        assert older_semantic_boundary in OPERATE
    assert "their richer operation-specific verifier is incomplete" in OPERATE
    incomplete_sentence = OPERATE[OPERATE.index("Semantic names such as"):]
    assert "audio.importTabDelimited" not in incomplete_sentence.split(". That boundary", 1)[0]
    assert "soundbank.generate" not in incomplete_sentence.split(". That boundary", 1)[0]
    assert "the three Undo Group members declare only `waapi.undoGroup`" in OPERATE
    assert "An optional explicit `platform` is accepted only after `isPropertyEnabled`" in OPERATE
    assert "An optional explicit `platform` is used for the enablement check" in OPERATE


def test_tab_delimited_import_documents_wwise_physical_separator_boundary() -> None:
    tab_import = OPERATE.split("`audio.importTabDelimited`:", 1)[1].split(
        "\n- ",
        1,
    )[0]
    assert "Each cell must be one physical field" in tab_import
    assert "literal tab, CR, or LF separators are not allowed inside cell content" in tab_import
    assert "CSV-style quoting does not escape those Wwise separators" in tab_import
    assert "preview fails closed before dispatch" in tab_import


def test_soundbank_workflows_have_direct_named_routes_and_closed_preflight() -> None:
    section = SKILL.split("Fast route from this entry file:", 1)[1].split(
        "Conditional read for a closed transaction:", 1
    )[0]
    section_flat = " ".join(section.split())

    for workflow, operation in (
        ("bank generation", "soundbank.generate"),
        ("External Sources `.wsources` conversion", "soundbank.convertExternalSources"),
        ("Definition `.tsv` processing", "soundbank.processDefinitionFiles"),
    ):
        assert f"{workflow} uses `{operation}`" in section_flat
    assert "the first gateway command after the operate-reference read is the matching named `operation-schema`" in section_flat
    assert "do not run `describe`, `query-object`, or `operation-schema waapi.call` first" in section_flat
    assert "Do not inspect a supplied `.wsources` or `.tsv` with `cat`, `sed`" in section_flat
    assert "the named operation's `preview` owns strict file parsing, input proofs" in section_flat
    assert "After its successful `execute` reports `executed_unverified`, run `verify` before answering" in section_flat
    assert "These are the `ak.wwise.core.soundbank.*` routes" in section_flat
    assert "Only a request that explicitly asks for WwiseConsole, CLI, command-line, or 命令行 execution" in section_flat
    assert "a `.wproj` path, JSON `project` field, project-copy description" in section_flat
    assert "input data, not CLI intent" in section_flat
    assert "generation begins with exactly `operation-schema soundbank.generate`" in section_flat


def test_cli_and_connected_authoring_names_are_not_interchangeable() -> None:
    assert "Choose between the CLI and connected-Authoring families" in OPERATE
    assert "Only explicit WwiseConsole, CLI, command-line, or 命令行 wording" in OPERATE
    assert "a `.wproj` path, a JSON `project` field, a project-copy description" in OPERATE
    assert "alone never establish CLI intent" in OPERATE
    assert "Without that explicit CLI wording" in OPERATE
    assert "connected SoundBank generation must begin with `operation-schema soundbank.generate`" in OPERATE
    assert "never `operation-schema waapi.call`" in OPERATE
    for distinction in (
        "`ak.wwise.cli.convertExternalSource` (singular) is not `ak.wwise.core.soundbank.convertExternalSources` (plural)",
        "`ak.wwise.cli.generateSoundbank` is not `ak.wwise.core.soundbank.generate`",
        "`ak.wwise.cli.tabDelimitedImport` is not `ak.wwise.core.audio.importTabDelimited`",
    ):
        assert distinction in OPERATE
    assert "do not probe a same-named dedicated operation first" in OPERATE
    assert "do not choose `waapi.call` for an already-connected Authoring request" in OPERATE


def test_soundbank_generation_notifications_remain_query_only() -> None:
    assert "Classify the requested action, not background wording" in SKILL
    assert "listen for, wait for, or report a SoundBank generation notification" in SKILL
    assert "It never authorizes `soundbank.generate`" in SKILL


def test_object_create_merge_and_object_set_existing_target_routing_are_disjoint() -> None:
    first_choice = OPERATE.split("- **New change request:**", 1)[1].split(
        "\n\nThe user's current intent",
        1,
    )[0]
    first_choice_flat = " ".join(first_choice.split())

    assert "choose the named operation before making the first Gateway call" in first_choice_flat
    assert "do not probe one semantic operation and switch after rejection" in first_choice_flat
    assert "Evaluate the `object.set` exclusions first" in first_choice_flat
    assert "Use `operation-schema object.set` only when the request changes fields or references on existing roots" in first_choice_flat
    assert "targets multiple existing roots" in first_choice_flat
    assert "nested container explicitly identified as already existing" in first_choice_flat
    assert "Any one of these conditions locks `object.set`" in first_choice_flat
    assert (
        first_choice_flat.index("Use `operation-schema object.set` only when")
        < first_choice_flat.index("Only after all three `object.set` exclusions are absent")
        < first_choice_flat.index("If exactly one same-name root already exists")
    )
    assert "If exactly one same-name root already exists, the root itself must remain unchanged" in first_choice_flat
    assert "only recursively merges a descendant tree beneath it" in first_choice_flat
    assert "begin with `operation-schema object.create`" in first_choice_flat
    assert "repeat the root's exact `type` and `name`" in first_choice_flat
    assert '`on_name_conflict: "merge"`' in first_choice_flat
    assert "The root's existence alone never selects `object.set`" in first_choice_flat
    assert "A wholly new recursive root also begins with" in first_choice_flat

    fixed_commands = SKILL.split("## Fixed gateway commands", 1)[1].split(
        "Use exactly one command",
        1,
    )[0]
    assert (
        "gateway.py operation-schema object.create\n"
        "python scripts/run.py gateway.py operation-schema object.set"
    ) in fixed_commands
    assert "evaluate the `object.set` lock before considering" in SKILL
    assert "Only after all three exclusions are absent" in SKILL
    assert "exactly one same-name existing root" in SKILL
    assert "Choose `object.create` for a new recursive root and also for one existing named root" in OPERATE
    assert "only merges a recursive descendant tree" in OPERATE
    assert "Evaluate the `object.set` exclusions before considering" in OPERATE
    assert "Choose `object.set` when the request changes fields or references on existing roots" in OPERATE
    assert "nested container explicitly identified as already existing" in OPERATE
    assert "any one condition locks that operation" in OPERATE
    assert "only after all three exclusions are absent" in OPERATE
    assert "exactly one same-name root remains unchanged" in OPERATE
    assert "each nested container receiving descendants—gets its own `objects[]` row" in OPERATE
    assert "contains only genuinely new direct children" in OPERATE
    assert "Existing `objects[]` targets never imply `merge`" in OPERATE
    assert "use `fail` when those requested children are new or absent" in OPERATE
    assert "prefer the narrower `object.setName`, `object.setNotes`, `object.setProperty`, or `object.setReference`" in OPERATE
    assert "Choose `object.create` only when the requested top-level object itself is new" not in OPERATE


def test_existing_root_merge_request_shapes_are_unambiguous() -> None:
    operate_flat = " ".join(OPERATE.split())
    assert "set `parent` to its existing parent" in operate_flat
    assert "repeat the root's exact `type` and `name`" in operate_flat
    assert 'use `on_name_conflict: "merge"`' in operate_flat
    assert "Do not retarget `parent` to the existing root" in operate_flat
    assert "give each such nested container its own `objects[]` row" in operate_flat
    assert "using the exact path derivable from the user's stated hierarchy" in operate_flat
    assert "Do not replace that exact path with a `scoped-name` identity" in operate_flat


def test_import_language_and_use_existing_mapping_are_row_sensitive() -> None:
    operate_flat = " ".join(OPERATE.split())
    assert "calls a table or batch an SFX import supplies the exact language already" in operate_flat
    assert 'map it directly to `import_language: "SFX"`' in operate_flat
    assert "Do not ask the user to repeat that language" in operate_flat
    assert "`useExisting` is decided per row even though it dispatches once" in operate_flat
    assert "For a non-SFX localized row whose exact target already exists" in operate_flat
    assert "This omission rule never applies to `SFX`" in operate_flat
    assert "even when an SFX target already exists, preserve every optional field" in operate_flat
    assert "A missing target in the same batch is a creation row" in operate_flat
    assert "preserve every such optional field from its reviewed manifest" in operate_flat


def test_five_version_coverage_reference_reports_executable_registry_not_boundaries() -> None:
    coverage_flat = " ".join(COVERAGE.split())
    assert "| Total version/API rows | 814 | 268 | 540 | 6 | 808 |" in COVERAGE
    assert "The 808 packaged route rows represent 198 unique public WAAPI route contracts" in COVERAGE
    assert "A hard boundary is never counted as routed coverage" in COVERAGE
    assert "still require a live Authoring host" in coverage_flat
    assert "`AUTHORING_HOST_REQUIRED` before business" in coverage_flat
    assert "manifest-registered `waapi.call` operation" in COVERAGE
    assert "Lua file operations are executable only from an existing `.lua` file" in COVERAGE
    assert (
        "Hidden/model-authored source and unrestricted loader fields remain closed"
        in coverage_flat
    )
    assert "program-tested packaged coverage" in COVERAGE
    assert "not individually" in COVERAGE
    assert "live-semantic-verified" in COVERAGE


def test_lua_source_authority_is_explicitly_a_caller_assertion_not_proof() -> None:
    skill_flat = " ".join(SKILL.split())
    operate_flat = " ".join(OPERATE.split())

    assert "`source_authority` is a caller assertion in the request protocol" in skill_flat
    assert "set it only when the current user message actually supplies" in skill_flat
    assert "`source_authority` is only a caller assertion in the request protocol" in operate_flat
    assert "cannot independently prove who authored or supplied them" in operate_flat
    assert "Never generate, repair, wrap, augment, or hide Lua" in operate_flat


def test_transaction_runtime_invariants_prevent_confirmation_target_and_retry_drift() -> None:
    for phrase in (
        "full SHA-256 remains visible for human review",
        "exact short token returned by `transaction-show`",
        "token binds the stored artifact and transaction state",
        "does not accept replacement JSON",
        "verifies the live Wwise version/project/endpoint",
        "verifies the packaged implementation digest",
        "re-reads every canonical GUID role",
        "repreview_required",
        "never automatically retried",
        "executed_unverified",
        "verification_deferred",
        "execution_cancelled",
        "result_schema_checked",
    ):
        assert phrase in OPERATE
    assert "even with `--allow-destructive` or `WWISE_DESTRUCTIVE=1`" in OPERATE


def test_lifecycle_cleanup_statuses_and_bindings_are_documented() -> None:
    for phrase in (
        "opener preview is `not_started`",
        "successful execution/verification is `pending`",
        "ambiguous execution is `unknown`",
        "Transport destroy binds only to the validated ID returned by create",
        "Work Unit load/unload is reported separately as `available_reversal`",
        "A successful closed UI registration retains its exact unregister cleanup companion",
        "Both standalone UI unregister forms have unknown ownership and no inverse",
    ):
        assert phrase in OPERATE


def test_operation_specific_verification_is_not_generic_mutation_replay() -> None:
    for phrase in (
        "binds every returned GUID",
        "every captured old-subtree GUID absent",
        "`object.set` captures every target and field pre-state",
        "Delete proves GUID absence",
        "same GUID, new name/path, unchanged parent, and old-path absence",
        "Numeric properties use typed tolerance",
        "`1 semitone = 100 cents`",
        "References must normalize to the target identity",
        "`useExisting` preserves each existing GUID",
        "Definition processing requires the exact additive post-state",
        "SoundBank inclusion operations require their exact requested set algebra",
    ):
        assert phrase in OPERATE
    assert "run `verify`, not `execute` again" in OPERATE


def test_removed_fallback_layers_are_not_advertised() -> None:
    assert "SemanticPlanner" not in OPERATE
    assert "XML editing" not in OPERATE
    assert "XML helper" not in OPERATE
    assert "only normal execution path is the packaged transaction CLI" in OPERATE


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
