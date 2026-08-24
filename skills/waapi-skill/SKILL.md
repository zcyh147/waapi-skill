---
name: waapi-skill
description: Use this Skill for any Wwise/WAAPI version, project, query, object/property, import, SoundBank, switch, topic, setup, or change—even without “WAAPI”. Use only its Python runtime, versioned resources/builders, bounded subscriptions, and safe dispatcher. Read only the injected SKILL.md locator first; never search for or infer it. Choose by command host, not Wwise/Codex version or path spelling. POSIX uses `cat '<literal-locator>'` or exact `sed -n '1,$p' '<literal-locator>'`; a whitespace-free POSIX locator uses unquoted `cat <literal-locator>` to avoid an incomplete quote; native Windows uses exact `Get-Content -Raw -Encoding UTF8 '<literal-locator>'` in PowerShell Core. Never cross-use/wrap these forms or combine the read with unrelated action.
---

# Wwise WAAPI Skill

Automate Wwise only through the packaged, version-aware gateway. Do not replace it with temporary scripts, inline Python, direct `WaapiClient` calls, or repository archaeology.

Read the injected `SKILL.md` exactly once as the sole first shell action in a fresh task. A successful read is complete; a second `SKILL.md` read is forbidden. Never combine it with `pwd`, `git`, `rg`, `ls`, `find`, `printf`, a user-file read, or a gateway command; finish before the next command.

Supported Wwise versions are `2021.1`, `2022.1`, `2023.1`, `2024.1`, and `2025.1`.

## One-time conversation introduction

The first time this Skill is used in a conversation, do not announce that it is loaded before the first gateway result. When the visible conversation has no prior introduction, the first Agent message after that result must express the returned `session_context.one_time_introduction.facts` together as one short, atomic introduction: say naturally that `waapi-skill` is loaded, report the current WAAPI address, WAAPI adapter version, and project modification policy, and offer the three available modes. The same introduction must name them exactly: `read_only`, `ask_before_changes`, and `allow_changes`. Do not split those facts across an earlier message and a gateway-backed message. Match the user's language and write ordinary prose, not a status bar, table, field list, or rigid template.

A Skill or lane-reference file read is not a Gateway result. Before the first complete Gateway result, do not emit a placeholder introduction, claim the Skill is loaded, or say its facts will be confirmed later. After it, the very next Agent message must state every actual returned fact together, even if an earlier message mentioned part.

Natural Chinese may say “若有需要，可按需切换模式” after the evidence-backed facts. Say “当前连接的” only with a proved live connection; otherwise say “当前使用的/配置的”. Report unavailable facts plainly and never guess.

Use the first gateway command already required by the user's task. For a pure explanation needing no gateway, run exactly one offline `config-show` to obtain the introduction facts; never run `status` or open a live WAAPI connection only for the introduction. An offline task stays offline. Show it only when the visible conversation does not already contain this introduction; do not use memory to make that decision. Repeat it only when asked or a reported value changes. For an exact machine-readable answer, use a separate normal progress update and keep the result body exact.

## Entry rules

1. Route the request into **setup**, **query**, or **operate** from the user's words.
2. Bootstrap only from the injected `SKILL.md` locator. Never guess a repository-relative `skills/waapi-skill` path or run `pwd`, `git status`, `ls`, `find`, `rg`, or another workspace probe to locate the Skill, including for Wwise CLI and project-migration requests.
3. For the common live reads below, run the matching gateway command immediately. Resolve the injected locator to the absolute Skill directory without probing, then invoke its absolute `scripts/run.py` path; do not rely on an unrecorded shell working directory. Do this before `ls`, `find`, `rg`, documentation research, or reading implementation files.
4. Use connection settings in this order: explicit gateway flags, `WWISE_WAAPI_HOST` / `WWISE_WAAPI_PORT` / `WWISE_VERSION`, then the external saved config reported by `config-show`. Put the runtime version selector after `gateway.py` and before its subcommand. The exact full shape is `python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 operation-schema object.copy`; `--wwise-version` is accepted in that gateway-global position as a compatibility alias and is also the saved-config field after `config-set`. Do not inspect or hand-edit config files. Do not scan unrelated ports or processes.
5. Treat gateway JSON as authoritative. Every gateway command must leave its complete JSON visible to the conversation before the next command: never suppress or redirect its output, request a zero/short tool-output budget, or continue from the shell exit code alone. When a successful response supplies `shell_tool_timeout_ms`, set that exact value on the outer shell tool call that executes its next Gateway command. This is transport wait metadata: never add it to the command argv or change the Gateway's own timeout. If no complete JSON is visible, stop and report that missing result instead of assuming success. On a structured error or boundary, report it; do not improvise another WAAPI client or write a helper.
6. Read only the current-turn lane; never preload. Read-only work cannot read `waapi-operate.md` before a change request.
7. Read each later named lane reference exactly once in its own shell call. POSIX uses `cat <absolute-reference>`. Native Windows always copies the short task-local form `Get-Content -Raw -Encoding UTF8 '.agents\skills\waapi-skill\references\<file>.md'` exactly; keep that workspace-relative locator instead of reconstructing a scenario-root absolute path. “Exactly once” spans the visible task, not each turn; never reread an already-visible file. Do not probe with `wc -l`, `ls`, `rg`, `find`, `stat`, or `test`, and never split a reference. Complete `waapi-query.md` and `waapi-operate.md` reads end with the exact `WAAPI_QUERY_REFERENCE_END` and `WAAPI_OPERATE_REFERENCE_END` sentinels. Proceed only when the matching sentinel is the final visible line with no truncation or omission marker; otherwise report an incomplete read and stop without a partial reread or gateway call. Do not use `sed`, `head`, `tail`, `rg`, or a second reader to check. Give each gateway invocation its own later shell call. Only POSIX may bootstrap the initial complete `SKILL.md` with exactly `wc -l <SKILL.md> && sed -n '1,<enough-lines>p' <SKILL.md>` against that same literal file; this is the only combined read allowed. Never combine any other command with `&&`, `;`, a pipe, command substitution, or a multi-command shell string; those forms are not independently auditable.

## Fixed gateway commands

The snippets below use `scripts/run.py` as readable shorthand. In the actual tool call, replace it with the absolute path derived from this injected `SKILL.md` locator, for example `python /absolute/path/to/waapi-skill/scripts/run.py gateway.py status`. Never execute the relative `scripts/run.py` spelling in an automated agent run.

```bash
python scripts/run.py gateway.py status
python scripts/run.py gateway.py config-show
python scripts/run.py gateway.py config-set --wwise-version 2022.1 --waapi-host 127.0.0.1 --waapi-port 8080 --project-modification-policy ask_before_changes
python scripts/run.py gateway.py config-set --reset
python scripts/run.py gateway.py buses
python scripts/run.py gateway.py selected
python scripts/run.py gateway.py project-default-work-units
python scripts/run.py gateway.py profiler-game-objects --time capture
python scripts/run.py gateway.py profiler-voice-contributions --time capture --voice-pipeline-id <uint32> --bus-pipeline-id <uint32>
python scripts/run.py gateway.py request-schema <migrated-api-uri>
python scripts/run.py gateway.py debug-wal-tree --take 128
python scripts/run.py gateway.py capabilities --all-versions --summary-only
python scripts/run.py gateway.py capabilities --all-versions --query object.get --limit 20
python scripts/run.py gateway.py describe <uri> --all-versions
python scripts/run.py gateway.py request-schema ak.wwise.waapi.getFunctions
python scripts/run.py gateway.py request-schema ak.wwise.waapi.getTopics
python scripts/run.py gateway.py request-schema <reflected-function-uri>
python scripts/run.py gateway.py query-object --path '<exact-object-path>' --return-field id --return-field name --return-field type --return-field path
python scripts/run.py gateway.py query-object --type Event --take 100
python scripts/run.py gateway.py --version <supported-version> query-schema [--advanced]
python scripts/run.py gateway.py --version <supported-version> query-object (--typed-structured <typed-facts-from-query-schema> | --typed-advanced --waql '<bounded-single-line-waql>' <typed-fields-from-query-schema>)
python scripts/run.py gateway.py --version <supported-version> object-types --query '<type keywords>' --limit 20
python scripts/run.py gateway.py metadata types --summary-only
python scripts/run.py gateway.py wait-topic <topic-uri>
python scripts/run.py gateway.py topic-schema <topic-uri>
python scripts/run.py gateway.py --timeout <positive-finite-seconds> wait-topic <topic-uri> --event-count <1..64> <typed-topic-facts-from-topic-schema>
python scripts/run.py gateway.py wait-topic <topic-uri> --no-timeout
python scripts/run.py gateway.py stream-topic <topic-uri> <typed-topic-facts-from-topic-schema>
python scripts/run.py gateway.py --timeout <positive-finite-seconds> stream-topic <topic-uri> <typed-topic-facts-from-topic-schema>
python scripts/run.py gateway.py operations
python scripts/run.py gateway.py operation-schema object.create
python scripts/run.py gateway.py operation-schema object.set
python scripts/run.py gateway.py operation-schema waapi.undoGroup
python scripts/run.py gateway.py --version 2022.1 operation-schema object.copy
```

Use the listed route for the corresponding intent:

| User intent | Command |
| --- | --- |
| current Wwise version, endpoint, or project | `status` |
| inspect or save connection/version/policy config | `config-show` / `config-set` |
| list current project Buses | `buses` |
| current UI selection | `selected` |
| inspect project default Work Units | `project-default-work-units` |
| list profiler game objects at a time/cursor | `profiler-game-objects` |
| inspect one voice-path contribution tree | `profiler-voice-contributions` |
| build a migrated API request from typed values | run `request-schema`; execute its sole continuation |
| inspect the private WAL tree | `debug-wal-tree` |
| ask a Debug Wwise build to validate one reflected call shape without executing it | `request-schema ak.wwise.debug.validateCall` and its typed continuation |
| inspect packaged API support, schema, route, or boundary | `capabilities` / `describe` |
| run a reviewed reflected capability | `request-schema <exact-uri>` and its typed continuation |
| object lookup | progressively disclose `query-object` flags, structured schema, then advanced schema |
| packaged object-type discovery without Wwise | `object-types` |
| live object type/property/reference metadata | `metadata` |
| wait for one or a fixed bounded count of topic events | `wait-topic` |
| explicitly stream topic events continuously | `stream-topic` |
| inspect project-changing operation support | `operations` / `operation-schema` |

`status` completes a connection/version/project request. When the user instead asks for the independent live result of a named API, including `getInfo`, use `status` only as the required host/project preflight, then run `request-schema <exact-uri>` and its sole typed continuation. The result embedded in `status` does not replace that independently requested API call. This complete named-`getInfo` route needs only this `SKILL.md`; do not read the setup or query reference for it.
Treat the named `getInfo` result's `processId` as the requested live process identity; finish from that Gateway evidence without a system process lookup.

Every command except `stream-topic` prints one JSON document; streaming prints compact flushed NDJSON event records and one terminal record. Summarize actual values; show full JSON only if asked. Every result includes bounded `session_context`; use it for the one-time introduction and never reconstruct it.

Route ordinary vague “subscribe”, “listen”, or “monitor” wording to
`wait-topic`, not streaming. Before invoking it, tell the user the effective
policy naturally. Its ordinary omitted-duration default is 10 seconds; the
Skill exception for `ak.wwise.core.soundbank.generated` explicitly passes and
reports `--timeout 120`. Preserve a user-supplied positive finite duration
exactly (converting units to seconds without rounding) in the gateway-global
`--timeout <positive-finite-seconds>` position before `wait-topic`. Only an
explicit no-time-limit bounded-wait request selects the `wait-topic` subcommand
flag `--no-timeout`; it waits until 1–64 requested matches or cancellation but
is not an unlimited output stream. Never combine those flags.
By default say “这次使用默认的 10 秒等待时间”.

Select `stream-topic` only for explicit streaming or persistent intent such as
“stream”, “continuous”, “persistent”, “实时逐条”, “流式”, “持续”, “一直监听”,
or “不要收到后退出”. It creates one persistent subscription, emits each matched
event immediately as a compact flushed JSON record, and by default runs until
cancellation; a gateway-global `--timeout <positive-finite-seconds>` gives it a
finite duration. When options or matching are needed, run `topic-schema` once
and use its typed continuation for the already-selected wait or stream lifecycle. Each event is publish-schema and size validated; a bounded buffer
fails closed on overflow, cleanup always attempts unsubscribe, and a terminal
record reports why the stream ended.

Exact reflection-call fast route: for `ak.wwise.waapi.getFunctions` or `ak.wwise.waapi.getTopics`, run `request-schema` and follow its sole typed continuation. Do not run `describe` or `capabilities` first. If that continuation is rejected or fails, stop and report the result.

For five-version totals, first read coverage as directed below, then run exactly `capabilities --all-versions --summary-only`; it includes every route count. Row filters omit `--summary-only`. The list defaults to at most 50 compact rows; `--limit 0` is an explicit all-row opt-in, and `--detail` is only for nested interface, schema-summary, policy, or evidence auditing. When a URI is already known, use `request-schema <uri>` instead of listing the matrix. For operations, use the compact `operations` inventory only for a genuinely broad inventory question; use `operation-schema <name>` directly for a named operation unless the operate metadata flow requires discovery first, and reserve `operations --detail` for an explicit full-catalog contract audit.

For five-version totals, coverage, exclusions, or matrix proof, read `references/waapi-coverage.md` once after `SKILL.md` and before the summary; combine both. Program tests are not live-Wwise verification.

Object discovery progresses from simple flags to the structured Builder, using the exact advanced contract only when required. Do not skip a sufficient layer. Advanced WAQL is fixed read-only `object.get`, Gateway-bounded, and its schema states UTF-8/framing limits. Never rewrite a rejection or mutate from its result: a one-row response never certifies uniqueness. Before a later change, show candidates and exact-ID verify the chosen GUID/name/type/path. Do likewise for a mutation subset selected from multiple ordinary/structured results; relationship-GUID read hops are exempt. Generic `call` remains forbidden; obey `QUERY_OBJECT_REQUIRED`, `FIXED_COMMAND_REQUIRED`, and `WAIT_TOPIC_REQUIRED`.

When a machine-readable answer is requested and any successful gateway payload contains `agent_result`, compact-serialize exactly that object as the result body and stop. This rule applies to fixed reads as well as transactions. Do not reconstruct its fields from the prompt, `normalized`, summaries, or verification evidence; do not alter JSON escaping or keys; and do not run another command after receiving it. For `WAAPI_RESULT_JSON=<json>`, append compact `agent_result` directly after the prefix. Failed, deferred, indeterminate, or boundary payloads have no successful `agent_result`; report their actual state. Put the one-time introduction in a separate progress update; it never changes the exact machine-readable body. Normal query answers use default business fields. Use `query-object --detail` only for explicit user requests or compile/dispatch diagnosis; never rerun solely for detail.

## Routing

### Setup lane

Use setup when the task is about connection state, version detection, host/port issues, saved config, or “what Wwise instance is this talking to?”.

Read: `references/waapi-setup.md`

### Query lane

Use query for read-only inspection: selection, object lookup, hierarchy browsing, property reads, structured object discovery, project facts, topic waits/streams, and other non-mutating inspection.

Classify the requested action, not background wording. A request to listen for, wait for, or report a SoundBank generation notification is query-only even if a Bank is rebuilt or output exists. It never authorizes `soundbank.generate`, an operation-schema lookup, or mutation.

Default result shape: return the resolved structured result, not just “I called WAAPI”.

Classify the complete read-only task before its first hop. If it needs multiple or relationship hops, fully read `references/waapi-query.md` before any Gateway command; an exact path/GUID first hop does not make the whole task a complete fast route.

For a complete single-hop exact path/GUID existence or identity lookup, run exactly `query-object --path '<exact-object-path>' --return-field id --return-field name --return-field type --return-field path`; substitute `--object-id '<exact-guid>'`. Keep all four return fields explicit. Exact `not_found` stays Gateway-owned in compact output; use `--detail` only for explicit compile/dispatch diagnostics. This route is complete: do not read the query reference before or after it; do not retry a rejected or failed gateway invocation.

For current-selection questions, use the live selected-object query first. On a headless/command-line Wwise host, report the UI boundary; do not research or pretend a selection exists.

For repeated `query-object --where FIELD OPERATOR TYPE VALUE`, `=` is exact and `:` is contains/match; an exact-name restriction uses `=`.

Conditional read for a query not fully covered by the fixed commands, exact-identity fast route, or exact reflection-call fast route: `references/waapi-query.md`

### Operate lane

Use operate for project-changing work: create, move, copy, delete, property/reference edits, imports, soundbanks, switch assignments, and design previews. An exact path/GUID identity preflight inside a change request is part of the operate lane; read only `references/waapi-operate.md` for that task.

Finish any required selected-subset exact-ID readback first. Finish any user-requested exact path/type preflight before `operation-schema object.create`. Only an explicit before-preview type/path check of the same-name request root triggers it; a parent path, preserved sibling, or post-execution verification does not.
After that preflight, `object.create` runs `operation-schema`, then one `metadata discover` containing every same-scope prompt-present dynamic property/reference token (1–8; never split), then `draft-start`; with none, start directly. `object.set` batches its dynamic fields; Composer `draft-check` revalidates them. `audio.import` uses its `business_declaration` flow and binds exact objects/custom fields after start. For other
operations, only an explicit unknown dynamic property/reference token needs
metadata in the order stated by the operate reference. Never infer a token or
scope.
For `object.create`, metadata proves the matching top-level `properties` or `references` pointer present; after scalar facts, follow every prompt-present disclosure row in schema-table order and finish both before `children`. Never jump to the child tree while a requested metadata-proven field remains undisclosed.

Apply the canonical policy from the latest gateway `session_context`:

- `read_only`: do not carry out a project change. For an actual change request, explain that the current mode blocks changes, state that this request left the project unchanged, and stop after the required schema exposes that policy; do not create an executable preview. A design-only preview remains read-only and omits `--apply`.
- `ask_before_changes`: immediately create the schema-selected executable preview with `--apply`; it asks permission, so do not ask first. Summarize targets, values, result, and risks; state nothing changed, ask naturally whether to proceed, and end the turn. Even when the same request names later independent changes, run no more Gateway commands in that turn.
- `allow_changes`: for an actual, unambiguous change request, create the schema-selected executable preview with `--apply`. When it returns `policy_authorized`, name the concrete root and major child targets, say what is about to change and that the mode permits it, then execute exactly once the field named by `next_command.copy_instruction.source_field` and run its `verify` continuation. A generic count is insufficient. Claim success only after verification. Preview/plan/explain requests omit `--apply` and stop after preview.

Normal prose covers only objects, changes, results, risks, and whether anything changed. Hide API/operation names, Draft/transaction internals, ids, hashes, tokens, states, and commands. Keep exact `agent_result` machine-readable.

`read_only` still permits reads. A reflected function whose packaged execution contract has `effect: read` may use the transaction lane only for bounded schema validation and result verification: omit `--apply`, preserve its explicit-confirmation-only authority, and never reclassify a mutation from prompt wording.

The original user message is the authority for `--apply`; imperative tone alone is insufficient when the target, value, scope, or requested action is ambiguous. The Gateway records `allow_changes` as `policy_authorized`, not as explicit user confirmation, and re-reads the policy before dispatch. `debug.restartWaapiServers`, `debug.testAssert`, and `debug.testCrash` always remain in the later-confirmation path even under `allow_changes`.

Choose the transaction phase before choosing a command. An existing transaction continuation takes precedence over the named-operation rule; it requires the transaction id, and an artifact hash alone is not a transaction lookup key. For a confirmation, check, or continuation, reuse the already-visible Skill/reference and run `transaction-show <transaction-id> --summary-only` first; skip schema discovery and start with `transaction-show`. Follow only its complete returned continuation and selected `copy_instruction.source_field`; diagnostic `full_argv` is not executable. An incomplete result stops the turn. `awaiting_confirmation` also requires current user authorization and its opaque token; `policy_authorized` has no token. A status or check request stops after `transaction-show`.

For a new change request, use the named operation or `request-schema <exact-uri>` directly and follow its single `typed-zero-call`, `typed-call`, or typed Draft continuation with exact returned handles. Execute the immutable transaction at most once, then use `verify` as terminal authority. A rejected/incomplete step or `indeterminate` execute ends without repair, retry, or extra readback. `ak.wwise.cli.migrate` stops after execute for its caller-owned oracle; result-schema-only operations never become business-state verified. Never invoke internal planners/builders, construct a raw request, or write code.

For multiple independent transactions already ordered by the user, apply the same policy to each without inferring, reordering, or adding work.

In ordinary agent use, omit `--state-dir`: the Gateway owns a deterministic external runtime-state default. Never run `env`, `printenv`, shell expansion, or another probe to discover `WAAPI_SKILL_STATE_DIR`; never ask a normal user for this implementation path. Pass `--state-dir` only when the user or trusted caller explicitly supplied a trusted absolute override, and reuse it unchanged.

Fast route from this entry file:

- Closed transaction operations include `waapi.undoGroup`, all `object.*`, `audio.*`, `soundbank.*`, `switchContainer.*`, `ui.*`, `lua.*`, and `debug.*` operations returned by `operation-schema`; other reviewed mutations are discovered by exact URI through `request-schema`. For a new request, read `references/waapi-operate.md` in its own tool call and follow its typed operation flow. For an existing transaction continuation, do not reread an already-visible Skill or operate reference; skip schema discovery and start with `transaction-show`.
- For structure-only changes, one existing object's single rename/notes/property/reference edit uses its dedicated operation. `object.set` is for broader atomic existing-target work; `object.create` handles a new root or descendants below one unchanged same-name root.
- Choose overlaps by the complete outcome and selection guidance. Primary media import uses one `audio.import`; its business declarations own hierarchy and Event/Switch outcomes while Gateway derives native mechanics. Never probe `object.create` or a separate assignment first. On Wwise 2023.1+, use `object.set` when import is subordinate to a broader existing-target mutation. Caller-supplied tables use `audio.importTabDelimited`.
- The operate reference owns version-specific typed request mappings and all remaining operation rules. Follow that reference literally after its one complete read.

Conditional read for a closed transaction: `references/waapi-operate.md`

## Runner and packaged runtime

The runtime loads `resources/manifest/<version>/`, `resources/semantic/<version>/`, `resources/waql/<version>/`, and `resources/deferred/<version>.json` through the packaged gateway. Use `describe <uri> --full-schema` only when a complete reflected schema is necessary. For exact registry counts, profile meanings, exclusions, and evidence scope, read `references/waapi-coverage.md` once as directed above; evidence status never substitutes for live behavioral proof.

## Boundaries

- Do not invent fixed API maps in the prompt when the runtime resources can resolve the correct URI.
- Never write disposable business logic for a user Wwise task. No heredoc script, inline Python, new `.py`/`.js`/`.sh` helper, or direct client construction.
- `scripts/run.py` and the environment helper accept only their immutable packaged script allowlist. Never attempt another runner target or temporary script path.
- Fixed functions require their packaged command, reviewed Topics require `wait-topic` or `stream-topic`, and every other reviewed API follows only its `request-schema` or named `operation-schema` typed continuation. Mutations always require immutable Preview plus confirmation or policy authorization. Environment variables and retired flags do not bypass those route decisions.
- Lua is available only through its dedicated policy-gated operations: an existing non-symlink `.lua` file canonically inside `io_root`, or an exact inline string explicitly supplied by the user in Wwise 2025.1. `source_authority` is a caller assertion in the request protocol, not provenance the runtime can independently prove; set it only when the current user message actually supplies the complete code or exact file path. Never generate, repair, wrap, augment, or hide Lua for the user. Loader paths/modules and CLI project/migration switches remain closed, source size/hash is rebound before execution, side effects are not inferred or rolled back, and no Lua operation is retried.
- Private debug reads use only `debug-wal-tree`, the exact typed `ak.wwise.debug.validateCall` contract when supported, or bounded `wait-topic ak.wwise.debug.assertFailed`. Process-wide mode changes require their dedicated policy-gated operations. `debug.restartWaapiServers`, `debug.testAssert`, and `debug.testCrash` internalize fixed acknowledgements and still require later confirmation even under `allow_changes`; execution is once-only and terminal indeterminate with explicit disconnect/process expectations, no retry, reconnect, or generic verification.
- Raw or unrestricted UI-command registration/execution and model-supplied CLI custom command hooks remain blocked. Only the closed Authoring-host routes above are available. A current live `getCommands` result—not the packaged observed inventory—is the command-ID authority. Program/Lua registration paths and content are rebound, but the `user_supplied_verbatim` value remains a caller assertion that the runtime cannot independently prove. Isolated transactions audit absolute inputs and confine every explicit write path below `io_root`; any implicit Wwise-managed write is disclosed as unproven, never misreported as confined.
- Do not search the repository to recover from a gateway error. A structured failure is the result unless the user explicitly asked to develop or debug this Skill itself.
- If a capability has no packaged executable path, return a clear `unsupported_by_skill_interface` boundary instead of synthesizing code.
- Editing this Skill's implementation is allowed only when the user's task is Skill development, testing, or debugging—not as a way to complete an ordinary Wwise request.

## Detailed references

- `references/waapi-setup.md` — connection, version, config, and status troubleshooting
- `references/waapi-query.md` — read-only inspection, selection/object lookup, topic waits/streams, and no-code failure rules
- `references/waapi-operate.md` — closed operation JSON, durable policy-aware preview/authorize/execute/verify flow, retry rules, and explicit boundaries
- `references/waapi-coverage.md` — exact five-version counts, exclusions, route meanings, and program-test scope
