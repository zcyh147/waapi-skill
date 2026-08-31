---
name: waapi-skill
description: Use for every Wwise/WAAPI setup, read, topic, or change. Read only the injected SKILL.md locator first; never search for or infer it. Choose by command host, not Wwise/Codex version or path spelling. POSIX uses `cat '<literal-locator>'` or exact `sed -n '1,$p' '<literal-locator>'`; a whitespace-free POSIX locator uses unquoted `cat <literal-locator>`. native Windows uses exact `Get-Content -Raw -Encoding UTF8 '<literal-locator>'` in PowerShell Core. Never cross-use/wrap these forms or combine the read with unrelated action.
---

# Wwise WAAPI Skill

Automate Wwise through the packaged gateway. Use no inline Python or direct `WaapiClient`.

Read the injected `SKILL.md` exactly once as the sole first shell action in a fresh task. A successful read is complete; a second `SKILL.md` read is forbidden. Never combine it with `pwd`, `git`, `rg`, `ls`, `find`, `printf`, a user-file read, or a gateway command; finish before the next command.

Supported Wwise versions are `2021.1`, `2022.1`, `2023.1`, `2024.1`, and `2025.1`.

## One-time conversation introduction

The first time this Skill is used in a conversation, do not announce that it is loaded before the first gateway result. When the visible conversation lacks an introduction, the first Agent message after that result must express `session_context.one_time_introduction.facts` as one short, atomic introduction: say naturally that `waapi-skill` is loaded, report the current WAAPI address, WAAPI adapter version, and project modification policy, and offer the three available modes. The same introduction must name them exactly: `read_only`, `ask_before_changes`, and `allow_changes`. Do not split those facts across an earlier message and a gateway-backed message. Match the user's language and use ordinary prose, not a status bar, table, field list, or rigid template.

A Skill or lane-reference file read is not a Gateway result. Before a complete result, do not emit a placeholder introduction. After it, the very next Agent message must state every actual returned fact together, even if an earlier message mentioned part. Natural Chinese may say “若有需要，可按需切换模式”. Say “当前连接的” only for a proved live connection; otherwise say “当前使用的/配置的”.

Use the first gateway command already required by the user's task. For a pure explanation, run exactly one offline `config-show` to obtain the introduction facts; never run `status` or open a live WAAPI connection only for the introduction. An offline task stays offline. Show it only when the visible conversation does not already contain this introduction; do not use memory to make that decision. Repeat only on request or changed facts. Keep an exact answer in a separate normal progress update.

## Entry rules

1. Route the request into **setup**, **query**, or **operate** from the user's words.
2. Bootstrap only from the injected `SKILL.md` locator. Never guess a repository-relative `skills/waapi-skill` path or probe with `pwd`, `git status`, `ls`, `find`, or `rg`, including for Wwise CLI and project-migration requests.
3. For common reads below, run the matching gateway command immediately: resolve that locator to the absolute Skill directory without probing and invoke its absolute `scripts/run.py` before `ls`, `find`, `rg`, research, or implementation reads.
4. Connection order is explicit gateway flags, `WWISE_WAAPI_HOST` / `WWISE_WAAPI_PORT` / `WWISE_VERSION`, then `config-show`. Put version after `gateway.py`: `python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 operation-schema object.copy`. `--wwise-version` is its compatibility alias and the `config-set` field. Never hand-edit config. Do not scan unrelated ports or processes.
5. Treat gateway JSON as authoritative. Every gateway command must leave its complete JSON visible to the conversation before the next command: never suppress or redirect its output, request a zero/short tool-output budget, or continue from the shell exit code alone. When a successful response supplies `shell_tool_timeout_ms`, set that exact value on the outer shell tool call that executes its next Gateway command. This is transport wait metadata: never add it to the command argv or change the Gateway's own timeout. If no complete JSON is visible, stop and report that missing result instead of assuming success. On native Windows only, if the outer shell reports `CreateProcessAsUserW failed: 267` before PowerShell starts, repeat that identical complete shell command once. This is process-launch recovery, not a Gateway retry. A second 267 or any other shell failure stops. On a structured Gateway error or boundary, report it; do not improvise another WAAPI client or write a helper.
6. Read only the current-turn lane; never preload. Read-only work cannot read `waapi-operate.md` before a change request.
7. Read each later named lane reference exactly once in its own shell call. POSIX uses `cat <absolute-reference>`. Native Windows always copies the short task-local form `Get-Content -Raw -Encoding UTF8 '.agents\skills\waapi-skill\references\<file>.md'` exactly instead of reconstructing a scenario-root absolute path. Exactly once spans the visible task, not each turn; never reread an already-visible file. Do not probe with `wc -l`, `ls`, `rg`, `find`, `stat`, or `test`, and never split a reference. `waapi-query.md` and `waapi-operate.md` use `WAAPI_QUERY_REFERENCE_END` and `WAAPI_OPERATE_REFERENCE_END`; proceed only when the matching sentinel is the final visible line, otherwise report an incomplete read and stop. Do not check with another reader. Each later gateway invocation gets its own shell call. Only POSIX may bootstrap the initial complete `SKILL.md` against the same literal file with exact `wc -l <SKILL.md> && sed -n '1,<enough-lines>p' <SKILL.md>`; this is the only combined read allowed. Never combine any other command.

## Fixed gateway commands

Below, `scripts/run.py` is shorthand; automated calls replace it with the injected absolute path, for example `python /absolute/path/to/waapi-skill/scripts/run.py gateway.py status`.

```bash
python scripts/run.py gateway.py status
python scripts/run.py gateway.py config-show
python scripts/run.py gateway.py config-set --wwise-version 2022.1 --waapi-host 127.0.0.1 --waapi-port 8080 --project-modification-policy ask_before_changes
python scripts/run.py gateway.py config-set --reset
python scripts/run.py gateway.py buses
python scripts/run.py gateway.py selected
python scripts/run.py gateway.py capabilities --all-versions --summary-only
python scripts/run.py gateway.py capabilities --all-versions --query object.get --limit 20
python scripts/run.py gateway.py describe <uri> --all-versions
python scripts/run.py gateway.py request-schema ak.wwise.waapi.getFunctions
python scripts/run.py gateway.py request-schema ak.wwise.waapi.getTopics
python scripts/run.py gateway.py request-schema <reflected-function-uri>
python scripts/run.py gateway.py query-object --path-segment '<root>' --path-segment '<child>'
python scripts/run.py gateway.py query-object --kind sound-sfx --include volume-db --max-results 100
python scripts/run.py gateway.py --version <supported-version> query-schema [--advanced]
python scripts/run.py gateway.py --version <supported-version> query-object --advanced-waql '<bounded-single-line-waql>' --include <business-field> --max-results <1..1000>
python scripts/run.py gateway.py metadata types
python scripts/run.py gateway.py topic-schema <topic-uri>
python scripts/run.py gateway.py wait-topic <topic-uri> <binding-and-facts-from-topic-schema>
python scripts/run.py gateway.py --timeout <positive-finite-seconds> wait-topic <topic-uri> --event-count <1..64> <binding-and-facts-from-topic-schema>
python scripts/run.py gateway.py wait-topic <topic-uri> --no-timeout <binding-from-topic-schema>
python scripts/run.py gateway.py stream-topic <topic-uri> --event-count <1..64> <binding-and-facts-from-topic-schema>
python scripts/run.py gateway.py --timeout <positive-finite-seconds> stream-topic <topic-uri> --event-count <1..64> <binding-and-facts-from-topic-schema>
python scripts/run.py gateway.py operations
python scripts/run.py gateway.py operation-schema object.create
python scripts/run.py gateway.py operation-schema object.set
python scripts/run.py gateway.py operation-schema waapi.undoGroup
python scripts/run.py gateway.py --version 2022.1 operation-schema object.copy
```

Register a runtime Game Object with `request-schema ak.soundengine.registerGameObj`; unregister through its matching schema; never `object.create`.

`status` is the sole Gateway-owned `getInfo` route for connection/version/project. Do not use `request-schema` or `typed-zero-call` instead. It needs only this `SKILL.md`; do not read the setup or query reference. Treat the named `getInfo` result's `processId` as the requested live process identity; finish from that Gateway evidence without a system process lookup.

Every command except `stream-topic` prints one JSON document; streaming emits bounded NDJSON plus one terminal record. Every `session_context` is authoritative.

Route ordinary vague “subscribe”, “listen”, or “monitor” wording to `wait-topic`.
Before invoking it, tell the user the effective policy naturally. Its ordinary
omitted-duration default is 10 seconds; SoundBank-generated explicitly uses and
reports `--timeout 120`. Preserve a user-supplied positive finite duration
exactly (converting units to seconds without rounding) in the gateway-global
`--timeout <positive-finite-seconds>` position before `wait-topic`. Only an
explicit no-time-limit bounded-wait request selects the `wait-topic` subcommand
flag `--no-timeout`; it waits until 1–64 requested matches or cancellation and
is not an unlimited output stream. Never combine those flags. By
default say “这次使用默认的 10 秒等待时间”.

Select `stream-topic` only for explicit persistent intent: stream, continuous,
persistent, 实时逐条, 流式, 持续, 一直监听, or 不要收到后退出. It keeps one
subscription, flushes matched events, requires an `--event-count <1..64>`
ceiling, and may have a finite gateway-global timeout. Before every wait/stream,
run `topic-schema` and copy its digest and opaque `tvc1-*` handles. For
`choice_on_disclosure`, run `field_disclosure` first and use only typed `*-as`;
never guess untyped. Event size, count, cumulative bytes, and buffering are bounded; the
terminal record includes the completion and unsubscribe result.

For `ak.wwise.waapi.getFunctions`/`getTopics`, run `request-schema` and follow its sole typed continuation. Do not run `describe` or `capabilities` first. Any failure stops.

For five-version totals, first read coverage as directed below, then run exactly `capabilities --all-versions --summary-only`; it includes every route count. Row filters omit `--summary-only`. The list defaults to at most 50 compact rows;
`--limit 0` requests all, and `--detail` is diagnostic. A known URI
uses `request-schema`. Business intent uses an exact supplied operation name or
one compact `operations` lookup, then `operation-schema`; never invent names.
Reserve `operations --detail` for an explicit full-catalog audit.

For five-version totals, coverage, exclusions, or matrix proof, read `references/waapi-coverage.md` once after `SKILL.md` and before the summary; combine both. Program tests are not live-Wwise verification.

Object discovery starts with closed `query-schema`; use its bounded advanced
contract only when needed. An advanced one-row response never certifies uniqueness.
Before mutation, show candidates and exact-ID verify the chosen GUID/name/type/path.
The same applies to a mutation subset selected from multiple business-declaration or advanced results; relationship-GUID read hops are exempt.
Generic `call` is forbidden; obey `QUERY_OBJECT_REQUIRED`,
`FIXED_COMMAND_REQUIRED`, and `WAIT_TOPIC_REQUIRED`.

When any successful gateway payload contains `agent_result` and the user wants
a machine-readable answer, compact-serialize exactly that object and stop;
Do not reconstruct its fields from the prompt, `normalized`, summaries, or evidence; do not run another command after receiving it. Add `WAAPI_RESULT_JSON=` when requested.
This rule applies to fixed reads as well as transactions. Normal
query answers use default business fields. Keep the introduction separate. Use
`query-object --detail` only for explicit user requests or compile/dispatch diagnosis;
never rerun solely for detail.

## Routing

### Setup lane

Use setup for connection, version, host/port, saved config, or instance identity.
`status` covers current status/version/project/process identity: after `SKILL.md`, run `status` directly and do not read `waapi-setup.md`. Read setup only for saved connection/config changes.

Read: `references/waapi-setup.md`

### Query lane

Use query for selection, object/hierarchy/property/project reads, discovery, and topics.

Classify the requested action, not background wording. A request to listen for, wait for, or report a SoundBank generation notification is query-only. It never authorizes `soundbank.generate`, an operation-schema lookup, or mutation.

Classify the complete read-only task before its first hop. If it needs multiple or relationship hops, fully read `references/waapi-query.md` before any Gateway command; an exact path/GUID first hop does not make the whole task a complete fast route.

For a complete single-hop exact path/GUID existence or identity lookup, run exactly `query-object` with one literal `--path-segment` per hierarchy level, or `--exact-id '<exact-guid>'`. The Gateway constructs path separators and always returns the four identity fields. Exact `not_found` stays Gateway-owned in compact output; use `--detail` only for explicit compile/dispatch diagnostics. This route is complete: do not read the query reference before or after it; do not retry a rejected or failed gateway invocation.

For current-selection questions, use the live selected-object query first. On a headless/command-line Wwise host, report the UI boundary; do not research or pretend a selection exists.

Repeated `query-object --predicate BUSINESS_CONDITION VALUE` declarations mean AND; the Gateway owns native fields, operators, and value types.

Conditional read for a query not fully covered by the fixed commands, exact-identity fast route, or exact reflection-call fast route: `references/waapi-query.md`

### Operate lane

Use operate for project-changing work: create, move, copy, delete, property/reference edits, imports, soundbanks, switch assignments, and design previews. An exact path/GUID identity preflight inside a change request is part of the operate lane; read only `references/waapi-operate.md` for that task.

Finish any required selected-subset exact-ID readback first. Finish any user-requested exact path/type preflight before `operation-schema object.create`. Only an explicit before-preview type/path check of the same-name request root triggers it; a parent path, preserved sibling, or post-execution verification does not.
After that preflight, `object.create` runs `operation-schema`, one `metadata discover` for its 1–8 dynamic fields, then `draft-start`. `object.set` batches and revalidates its dynamic fields. Import, lifecycle, scalar property/reference, and platform-link operations use `business_declaration`. For the last three, bind the target, pass its English field meaning and optional platform to `draft-discover-fields`, and copy one handle—never a token. Import alone uses token custom-field binding. For other
operations, only an explicit unknown dynamic property/reference token needs
metadata in the order stated by the operate reference. Never infer a token or
scope.
For `object.create`, metadata proves the matching top-level `properties` or `references` pointer present; after scalar facts, follow every prompt-present disclosure row in schema-table order and finish both before `children`. Never jump to the child tree while a requested metadata-proven field remains undisclosed.

Apply the canonical policy from the latest gateway `session_context`:

Copy the returned Preview exactly; use `--apply` only if present. For Business Drafts, copy the returned `preview-from-draft` continuation exactly; it is executable without the flag. Never append `--apply` to `preview-from-draft`.

- `read_only`: do not change the project. Explain the mode block, state the project is unchanged, and stop after its schema; do not create an executable Preview. Design-only Preview remains read-only and omits `--apply`.
- `ask_before_changes`: immediately create the executable Preview; it asks permission, so do not ask first. Summarize targets, values, result, and risks; state nothing changed, ask naturally whether to proceed, and end the turn. Even when the same request names later independent changes, run no more Gateway commands in that turn.
- `allow_changes`: for an actual unambiguous change, create the executable Preview. If it returns `policy_authorized`, name the root and major children, state the impending permitted change, execute exactly once from `next_command.copy_instruction.source_field`, then verify. Counts alone are insufficient. Preview/plan/explain requests stop after the returned non-executable Preview.

Normal prose covers only objects, changes, results, risks, and whether anything changed. Hide API/operation names, Draft/transaction internals, ids, hashes, tokens, states, and commands. Keep exact `agent_result` machine-readable.

`read_only` still permits reads. A reflected function whose packaged execution contract has `effect: read` may use the transaction lane only for bounded schema validation and result verification: omit `--apply`, preserve its explicit-confirmation-only authority, and never reclassify a mutation from prompt wording.

The original user message supplies authority; the Gateway-owned command decides whether `--apply` is present. Imperative tone is insufficient when target, value, scope, or action is ambiguous. `allow_changes` records `policy_authorized`, re-reads policy before dispatch, and never auto-authorizes `debug.restartWaapiServers`, `debug.testAssert`, or `debug.testCrash`.

Choose the transaction phase before choosing a command. An existing transaction continuation takes precedence over the named-operation rule; it requires the transaction id, and an artifact hash alone is not a transaction lookup key. For a confirmation, check, or continuation, reuse the already-visible Skill/reference and run `transaction-show <transaction-id> --summary-only` first; skip schema discovery and start with `transaction-show`. Follow only its complete returned continuation and selected `copy_instruction.source_field`; diagnostic `full_argv` is not executable. An incomplete result stops the turn. `awaiting_confirmation` also requires current user authorization and its opaque token; `policy_authorized` has no token. A status or check request stops after `transaction-show`.

For a new change, use its named operation or exact-URI `request-schema` and follow one continuation. For `core-business/v1`, the exact returned continuation owns the read shape: simple fixed reads may use `core-call`; complex bounded reads may use a Draft. Changes bind returned object/Field Handles, follow `binding.role_fields`, and submit one complete Core plan. Never type native tokens, enums, GUID arrays, curve/edge objects, or request fragments. Execute once; `verify` is terminal authority. Rejection, incompleteness, or `indeterminate` ends without repair, retry, or extra readback. `ak.wwise.cli.migrate` stops after execute; result-schema-only is not business-state verification. Never invoke internal planners/builders, construct raw requests, or write code.

For multiple independent transactions already ordered by the user, apply the same policy to each without inferring, reordering, or adding work.

In ordinary agent use, omit `--state-dir`: the Gateway owns a deterministic external runtime-state default. Never run `env`, `printenv`, shell expansion, or another probe to discover `WAAPI_SKILL_STATE_DIR`; never ask a normal user for this implementation path. Pass `--state-dir` only when the user or trusted caller explicitly supplied a trusted absolute override, and reuse it unchanged.

Fast route from this entry file:

- Closed transaction operations include `waapi.undoGroup`, all `object.*`, `audio.*`, `soundbank.*`, `switchContainer.*`, `ui.*`, `lua.*`, and `debug.*` operations returned by `operation-schema`; other reviewed mutations are discovered by exact URI through `request-schema`. For a new request, read `references/waapi-operate.md` in its own tool call and follow the returned typed or business flow. For an existing transaction continuation, do not reread an already-visible Skill or operate reference; skip schema discovery and start with `transaction-show`.
- For structure-only changes, one existing object's single rename/notes/property/reference edit uses its dedicated operation. `object.set` is for broader atomic existing-target work; `object.create` handles a new root or descendants below one unchanged same-name root.
- Choose overlaps by the complete outcome and selection guidance. Primary media import uses one `audio.import`; its business declarations own hierarchy and Event/Switch outcomes while Gateway derives native mechanics. Never probe `object.create` or a separate assignment first. On Wwise 2023.1+, use `object.set` when import is subordinate to a broader existing-target mutation. Caller-supplied tables use `audio.importTabDelimited`.
- The operate reference owns version-specific typed request mappings and all remaining operation rules. Follow that reference literally after its one complete read.

Conditional read for a closed transaction: `references/waapi-operate.md`

## Runner and packaged runtime

The gateway loads `resources/manifest/<version>/`, `resources/semantic/<version>/`, `resources/waql/<version>/`, and `resources/deferred/<version>.json`. Use `describe <uri> --full-schema` only when needed. `waapi-coverage.md` owns counts/evidence, never live proof.

## Boundaries

- Never invent API maps or disposable business logic. No heredoc, inline Python, new `.py`/`.js`/`.sh` helper, direct client construction, alternate runner target, or temporary script.
- Use only each packaged fixed command or returned `request-schema` / named `operation-schema` continuation. Mutations always require immutable Preview plus confirmation or policy authorization. `typed-call` and retired commands cannot bypass route decisions.
- Lua is limited to its policy-gated operations and exact user-supplied source/path; never generate or repair it. Debug process controls execute once and never retry after disconnect uncertainty. Raw UI hooks and model-supplied CLI commands stay blocked; closed Authoring routes use fresh live command IDs. Explicit writes stay below `io_root`.
- Do not search the repository to recover from a gateway error. A structured failure is the result unless the user explicitly asked to develop or debug this Skill itself.
- If a capability has no packaged executable path, return a clear `unsupported_by_skill_interface` boundary instead of synthesizing code.
- Editing this Skill's implementation is allowed only when the user's task is Skill development, testing, or debugging—not as a way to complete an ordinary Wwise request.

## Detailed references

- In `references/`: `waapi-setup.md` config, `waapi-query.md` reads/topics, `waapi-operate.md` changes, `waapi-coverage.md` counts/evidence.
