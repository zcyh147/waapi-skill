---
name: waapi-skill
description: Use this Skill for any Wwise/WAAPI version, project, query, object/property, import, SoundBank, switch, topic, setup, or change—even without “WAAPI”. Use only its Python runtime, versioned resources/builders, bounded subscriptions, and safe dispatcher. Read only the injected SKILL.md locator first; never search for or infer it. Choose by command host, not Wwise/Codex version or path spelling. POSIX uses `cat '<literal-locator>'` or exact `sed -n '1,$p' '<literal-locator>'`; native Windows uses exact `Get-Content -Raw -Encoding UTF8 '<literal-locator>'` in PowerShell Core. Never cross-use/wrap these forms or combine the read with unrelated action.
---

# Wwise WAAPI Skill

Automate Wwise only through the packaged, version-aware gateway. Do not replace it with temporary scripts, inline Python, direct `WaapiClient` calls, or repository archaeology.

In a fresh task, make that host-native injected `SKILL.md` read the sole first shell action. Never combine it with `pwd`, `git`, `rg`, `ls`, `find`, `printf`, a user-file read, or a gateway command; finish before the next command.

Supported Wwise versions are `2021.1`, `2022.1`, `2023.1`, `2024.1`, and `2025.1`.

## One-time conversation introduction

The first time this Skill is used in a conversation, do not announce that it is loaded before the first gateway result. When the visible conversation has no prior introduction, the first Agent message after that result must express the returned `session_context.one_time_introduction.facts` together as one short, atomic introduction: say naturally that `waapi-skill` is loaded, report the current WAAPI address, WAAPI adapter version, and project modification policy, and offer the three available modes. Do not split those facts across an earlier message and a gateway-backed message. Match the user's language and write ordinary prose, not a status bar, table, field list, or rigid template. Do not add a separate “current operation” field.

For example, natural Chinese wording is: “我已经加载了 `waapi-skill`。当前使用的 WAAPI 地址是 `ws://127.0.0.1:8080/waapi`，适配层版本为 `2022.1`，工程修改策略是 `ask_before_changes`。若有需要，可按需切换模式：`read_only`、`ask_before_changes` 或 `allow_changes`。” Adapt the values and wording to the gateway evidence instead of copying the example blindly. Say “当前连接的” only when the task's gateway result proves a live connection; otherwise say “当前使用的” or “当前配置的” without adding engineering-style verification boilerplate. If `session_context.available` is false or a required value is null, say simply which setting is not configured or unavailable; report the remaining facts and never guess a missing value.

Use the first gateway command already required by the user's task. If the first task is a pure explanation that otherwise needs no gateway command, run exactly one offline `config-show` to obtain the introduction facts; never run `status` or open a live WAAPI connection only for the introduction, and never inspect a config file directly. An offline task stays offline. Complete the introduction once per conversation, including when the first task is read-only or offline. Show it only when the visible conversation does not already contain this introduction; do not use memory to make that decision. Do not repeat it unless the user asks about these settings or one of the reported values changes. If the final answer must be exact machine-readable output, put the introduction in a separate normal progress update and keep the required result body exact.

## Entry rules

1. Route the request into **setup**, **query**, or **operate** from the user's words.
2. Bootstrap only from the injected `SKILL.md` locator. Never guess a repository-relative `skills/waapi-skill` path or run `pwd`, `git status`, `ls`, `find`, `rg`, or another workspace probe to locate the Skill, including for Wwise CLI and project-migration requests.
3. For the common live reads below, run the matching gateway command immediately. Resolve the injected locator to the absolute Skill directory without probing, then invoke its absolute `scripts/run.py` path; do not rely on an unrecorded shell working directory. Do this before `ls`, `find`, `rg`, documentation research, or reading implementation files.
4. Use connection settings in this order: explicit gateway flags, `WWISE_WAAPI_HOST` / `WWISE_WAAPI_PORT` / `WWISE_VERSION`, then the external saved config reported by `config-show`. Put the runtime version selector after `gateway.py` and before its subcommand. The exact full shape is `python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 operation-schema object.copy`; `--wwise-version` is accepted in that gateway-global position as a compatibility alias and is also the saved-config field after `config-set`. Do not inspect or hand-edit config files. Do not scan unrelated ports or processes.
5. Treat gateway JSON as authoritative. Every gateway command must leave its complete JSON visible to the conversation before the next command: never suppress or redirect its output, request a zero/short tool-output budget, or continue from the shell exit code alone. If no complete JSON is visible, stop and report that missing result instead of assuming success. On a structured error or boundary, report it; do not improvise another WAAPI client or write a helper.
6. Read one lane reference only when fixed commands are insufficient; five-version totals, coverage, and program-matrix requests are the exception below.
7. Read each later named lane reference exactly once in its own shell call. POSIX uses `cat <absolute-reference>`; native Windows uses `Get-Content -Raw -Encoding UTF8 '<reference>'` with an absolute path or exact injected `.agents\skills\waapi-skill\references\<file>.md`. Do not derive or normalize it. “Exactly once” spans the visible task, not each turn; never reread an already-visible file. Do not probe with `wc -l`, `ls`, `rg`, `find`, `stat`, or `test`, and never split a reference. Complete `waapi-query.md` and `waapi-operate.md` reads end with the exact `WAAPI_QUERY_REFERENCE_END` and `WAAPI_OPERATE_REFERENCE_END` sentinels. Proceed only when the matching sentinel is the final visible line with no truncation or omission marker; otherwise report an incomplete read and stop without a partial reread or gateway call. Do not use `sed`, `head`, `tail`, `rg`, or a second reader to check. Give each gateway invocation its own later shell call. Only POSIX may bootstrap the initial complete `SKILL.md` with exactly `wc -l <SKILL.md> && sed -n '1,<enough-lines>p' <SKILL.md>` against that same literal file; this is the only combined read allowed. Never combine any other command with `&&`, `;`, a pipe, command substitution, or a multi-command shell string; those forms are not independently auditable.

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
python scripts/run.py gateway.py debug-wal-tree --take 128
python scripts/run.py gateway.py debug-validate-call <exact-function-uri> --args-json '{}'
python scripts/run.py gateway.py capabilities --all-versions --summary-only
python scripts/run.py gateway.py capabilities --all-versions --query object.get --limit 20
python scripts/run.py gateway.py describe <uri> --all-versions
python scripts/run.py gateway.py --version <supported-version> call ak.wwise.waapi.getFunctions --args-json '{}' --options-json '{}'
python scripts/run.py gateway.py --version <supported-version> call ak.wwise.waapi.getTopics --args-json '{}' --options-json '{}'
python scripts/run.py gateway.py --version <supported-version> call <bounded-read-uri> --args-json '<object>' --options-json '<object>'
python scripts/run.py gateway.py query-object --path '<exact-object-path>' --return-field id --return-field name --return-field type --return-field path
python scripts/run.py gateway.py query-object --type Event --take 100
python scripts/run.py gateway.py --version <supported-version> query-schema [--advanced]
python scripts/run.py gateway.py --version <supported-version> query-object (--request-json '<object-query-v1-json>' | --advanced-request-json '<advanced-object-query-v1-json>')
python scripts/run.py gateway.py --version <supported-version> object-types --query '<type keywords>' --limit 20
python scripts/run.py gateway.py metadata types --summary-only
python scripts/run.py gateway.py wait-topic <topic-uri>
python scripts/run.py gateway.py --timeout <positive-finite-seconds> wait-topic <topic-uri> --event-count <1..64> --match-json '<object>'
python scripts/run.py gateway.py wait-topic <topic-uri> --no-timeout
python scripts/run.py gateway.py stream-topic <topic-uri> --options-json '<object>' --match-json '<object>'
python scripts/run.py gateway.py --timeout <positive-finite-seconds> stream-topic <topic-uri> --match-json '<object>'
python scripts/run.py gateway.py operations
python scripts/run.py gateway.py operation-schema object.create
python scripts/run.py gateway.py operation-schema object.set
python scripts/run.py gateway.py operation-schema waapi.call
python scripts/run.py gateway.py operation-schema waapi.undoGroup
python scripts/run.py gateway.py --version 2022.1 operation-schema object.copy
```

Use exactly one command for the corresponding intent:

| User intent | Command |
| --- | --- |
| current Wwise version, endpoint, or project | `status` |
| inspect or save connection/version/policy config | `config-show` / `config-set` |
| list current project Buses | `buses` |
| current UI selection | `selected` |
| inspect project default Work Units | `project-default-work-units` |
| list profiler game objects at a time/cursor | `profiler-game-objects` |
| inspect one voice-path contribution tree | `profiler-voice-contributions` |
| inspect the private WAL tree | `debug-wal-tree` |
| ask a Debug Wwise build to validate one reflected call shape without executing it | `debug-validate-call` |
| inspect packaged API support, schema, route, or boundary | `capabilities` / `describe` |
| call a capability whose catalog route is `manifest_dispatch` | `call` with reflected args/options |
| object lookup | progressively disclose `query-object` flags, structured schema, then advanced schema |
| packaged object-type discovery without Wwise | `object-types` |
| live object type/property/reference metadata | `metadata` |
| wait for one or a fixed bounded count of topic events | `wait-topic` |
| explicitly stream topic events continuously | `stream-topic` |
| inspect project-changing operation support | `operations` / `operation-schema` |

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
finite duration. Pass reviewed `--options-json` and recursive `--match-json`
when needed. Each event is publish-schema and size validated; a bounded buffer
fails closed on overflow, cleanup always attempts unsubscribe, and a terminal
record reports why the stream ended.

Exact reflection-call fast route: when the user explicitly asks to call `ak.wwise.waapi.getFunctions` or `ak.wwise.waapi.getTopics` with empty args and options, run exactly one matching `call` command from the table, replacing `<supported-version>` with the exact requested or connected Wwise version. Do not run `describe` or `capabilities` first, and do not read the query reference before or after the call. The reviewed route is already fixed by this Skill. If that one gateway invocation is rejected or fails, stop and report the result; never retry it with another command.

For five-version totals, first read coverage as directed below, then run exactly `capabilities --all-versions --summary-only`; it includes every route count. Row filters omit `--summary-only`. The list defaults to at most 50 compact rows; `--limit 0` is an explicit all-row opt-in, and `--detail` is only for nested interface, schema-summary, policy, or evidence auditing. When a URI is already known, use `describe <uri>` instead of listing the matrix, except for an explicit exact reflection call or a reviewed direct `waapi.call` fast route named in the operate lane below. A known row with `preferred_route: manifest_dispatch` may use `call`. For `transaction_operation`, obey the returned `transaction_operations`: prefer a listed dedicated semantic operation, use `waapi.undoGroup` for its three member URIs, and use `waapi.call` only when no dedicated operation applies. For operations, use the compact `operations` inventory only for a genuinely broad inventory question; use `operation-schema <name>` directly for a named operation unless the operate metadata flow requires discovery first, and reserve `operations --detail` for an explicit full-catalog contract audit.

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

Classify the complete task before its first hop. If it needs multiple or relationship hops, fully read `references/waapi-query.md` before any Gateway command; an exact path/GUID first hop does not make the whole task a complete fast route.

For a complete single-hop exact path/GUID existence or identity lookup, run exactly `query-object --path '<exact-object-path>' --return-field id --return-field name --return-field type --return-field path`; substitute `--object-id '<exact-guid>'`. Keep all four return fields explicit. Exact `not_found` stays Gateway-owned in compact output; use `--detail` only for explicit compile/dispatch diagnostics. This route is complete: do not read the query reference before or after it; do not retry a rejected or failed gateway invocation.

For current-selection questions, use the live selected-object query first. On a headless/command-line Wwise host, report the UI boundary; do not research or pretend a selection exists.

For `query-object --where-json`, `=` is exact and `:` is contains/match; an exact-name restriction uses `=`.

Conditional read for a query not fully covered by the fixed commands, exact-identity fast route, or exact reflection-call fast route: `references/waapi-query.md`

### Operate lane

Use operate for project-changing work: create, move, copy, delete, property/reference edits, imports, soundbanks, switch assignments, and design previews.

For `object.create`/`object.set`, finish any required selected-subset exact-ID
readback, then run schema before metadata; its adapter version selects scope.
Otherwise, only an explicit unknown dynamic property/reference token needs
metadata; the operate reference says whether it precedes or commutes with
schema. Closed fields and side effects are not metadata; without that token,
start with the named schema. Never infer a token or scope.

Apply the canonical policy from the latest gateway `session_context`:

- `read_only`: do not carry out a project change. For an actual change request, explain that the current mode blocks changes, state that this request left the project unchanged, and stop after the required schema exposes that policy; do not create an executable preview. A design-only preview remains read-only and omits `--apply`.
- `ask_before_changes`: immediately create the schema-selected executable preview with `--apply`; it asks permission, so do not ask first. Summarize targets, values, result, and risks; state nothing changed, ask naturally whether to proceed, and end the turn.
- `allow_changes`: for an actual, unambiguous change request, create the schema-selected executable preview with `--apply`. When it returns `policy_authorized`, name the concrete root and major child targets, say what is about to change and that the mode permits it, then execute exactly once the field named by `next_command.copy_instruction.source_field` and run its `verify` continuation. A generic count is insufficient. Claim success only after verification. Preview/plan/explain requests omit `--apply` and stop after preview.

Normal prose covers only objects, changes, results, risks, and whether anything changed. Hide API/operation names, Draft/transaction internals, ids, hashes, tokens, states, and commands. Keep exact `agent_result` machine-readable.

`read_only` still permits reads. A reflected function whose packaged execution contract has `effect: read` may use the transaction lane only for bounded schema validation and result verification: omit `--apply`, preserve its explicit-confirmation-only authority, and never reclassify a mutation from prompt wording.

The original user message is the authority for `--apply`; imperative tone alone is insufficient when the target, value, scope, or requested action is ambiguous. The Gateway records `allow_changes` as `policy_authorized`, not as explicit user confirmation, and re-reads the policy before dispatch. `debug.restartWaapiServers`, `debug.testAssert`, and `debug.testCrash` always remain in the later-confirmation path even under `allow_changes`.

Choose the transaction phase before choosing a command. An existing transaction continuation takes precedence over the named-operation rule, but it requires the transaction id; an artifact hash alone is not a transaction lookup key. When the user confirms, checks, or continues an already previewed transaction and its transaction id is available from the message or conversation, reuse the Skill and operate reference already visible from the preview turn: do not reread either file in the same visible conversation/task; run `transaction-show <transaction-id> --summary-only` first, proceeding directly from the already-visible instructions. Read the operate reference exactly once only when it is not already visible. Do not call `operations`, `operation-schema`, or `preview` before that show call; the immutable preview already contains the closed request and schema. `full_argv` and fields not named by `copy_instruction.source_field` are diagnostic. Require the complete instruction and named field; execute only it verbatim. Windows v2 normally names short `model_command`; use encoded `shell_command` only when explicitly selected. Never retype, reconstruct, shorten, normalize, or choose another field. `transaction-show` is the continuation safety gate: its complete JSON must be visible. If that output or selected command is empty, truncated, non-JSON, or otherwise incomplete—even with exit code `0` or a transaction id/hash from the preceding turn—stop without calling `confirm`, `execute`, `verify`, or `reject`, and do not retry the show in that turn.

When `transaction-show` reports `awaiting_confirmation`, it returns a short opaque `confirmation.token` bound to that stored transaction and the exact `confirm <transaction-id> --confirmation-token <gateway-token>` continuation. Run it only when the current user message clearly authorizes that preview. Never generate, shorten, validate from its spelling, reconstruct, or substitute that token, and never fall back to the displayed artifact hash. Never run `confirm --help`. If `confirm` does not return complete visible JSON, stop before `execute` or `verify`, even when its shell exit code is `0`. When `transaction-show` reports `policy_authorized`, it returns an `execute` continuation only while the current policy is still `allow_changes`; no confirmation token exists. A status or check request stops after `transaction-show`. User intent authorizes actions; the returned state only constrains which actions are legal and never invents intent by itself.

The field named by `copy_instruction.source_field` is the sole executable form; never choose a representation yourself or translate `full_argv`. The Gateway owns every launcher path segment.

The Gateway keeps `next_command` after `session_context` as the final actionable top-level field. A preview also mirrors that same object as the final field of its terminal `agent_result`; execute the structured tail's selected command without rebuilding it.

For a new change request with no existing transaction, use the named semantic operation whenever `describe` lists one; the generic route rejects that URI with `DEDICATED_OPERATION_REQUIRED`. Otherwise use `describe <uri>`, except for the reviewed direct `waapi.call` fast routes named below. For every other row reporting `transaction_operation`, use the exact declared operation: `waapi.undoGroup` for its three member URIs or `waapi.call` only for a row with no dedicated operation. Do not run `operations` first. Follow the successful schema's single `input_mode` and exact returned instructions; never choose a competing normal input. Composer mode starts from its Gateway argv and builds only through returned typed actions and Gateway-generated handles; Legacy mode copies its envelope and replaces only `arguments`. Follow the policy above, execute the immutable transaction at most once, and verify only after complete `executed_unverified`. An execute result with `status` and `state` both `indeterminate` ends the turn: report it without any follow-up. Later diagnosis needs a new user request and packaged read-only route. A rejected preview, invalid Legacy JSON/shell invocation, or incomplete gateway JSON ends the turn without repair/retry. `ak.wwise.cli.migrate` is the exception: after its complete `execute`, stop all gateway activity; its caller-owned reopened-project oracle performs final verification. Generic verification proves only the reflected result schema. Never invoke planner/builder classes, construct a raw mutation, or write code.

Except for `ak.wwise.cli.migrate`'s terminal `execute`, `verify` is the terminal authority for the selected contract: dedicated operations return their live readback, while generic `waapi.call` returns reflected result-schema evidence. After `verify` returns `verified` or another terminal verification state, stop the gateway sequence and report exactly that evidence. Do not add `query-object`, `call`, or another gateway command to double-check the same mutation. For an original request that already closed and ordered multiple independent transactions, apply the same configured policy independently to each item; never infer, reorder, or add a transaction.

In ordinary agent use, omit `--state-dir`: the Gateway owns a deterministic external transaction-store default. Never run `env`, `printenv`, shell expansion, or another probe to discover `WAAPI_SKILL_STATE_DIR`; never ask a normal user for this implementation path. Pass `--state-dir` only when the user or trusted caller explicitly supplied a trusted absolute override, and reuse it unchanged.

Fast route from this entry file:

- Closed transaction operations are `waapi.call`, `waapi.undoGroup`, `object.create`, `object.createPlugin`, `object.set`, `object.setLinked`, `object.setRTPC`, `object.delete`, `object.setName`, `object.setNotes`, `object.setProperty`, `object.setReference`, `audio.import`, `audio.importTabDelimited`, `soundbank.setInclusions`, `soundbank.generate`, `soundbank.convertExternalSources`, `soundbank.processDefinitionFiles`, `switchContainer.addAssignment`, `switchContainer.removeAssignment`, `ui.captureScreen`, `ui.commands.execute`, `ui.commands.register`, `ui.commands.unregister`, `lua.executeCliFile`, `lua.executeCoreFile`, `lua.executeCoreInline`, `debug.setAsserts`, `debug.setAutomationMode`, `debug.restartWaapiServers`, `debug.testAssert`, and `debug.testCrash`. For a new request, read `references/waapi-operate.md` in its own tool call and follow its closed operation flow. For an existing transaction continuation, do not reread an already-visible Skill or operate reference; skip `operation-schema` and `preview`; start with `transaction-show`.
- For structure-only changes, one existing object's single rename/notes/property/reference edit uses its dedicated operation. `object.set` is for broader atomic existing-target work; `object.create` handles a new root or descendants below one unchanged same-name root.
- Choose overlaps by the complete outcome and returned selection guidance. When media import is primary, one `audio.import` owns its media-row target hierarchy as typed structure-only rows and same-row Event/Switch Assignation; never probe `object.create` or a separate assignment first. On Wwise 2023.1+, use `object.set` instead when import is subordinate to a broader atomic mutation of existing targets. Caller-supplied TSV/table workflows use `audio.importTabDelimited`; keep execution domains distinct.
- The operate reference owns version-specific direct `waapi.call` fast routes and request mappings plus all remaining operation rules. Follow that reference literally after its one complete read.

Conditional read for a closed transaction: `references/waapi-operate.md`

## Runner and packaged runtime

The runtime loads `resources/manifest/<version>/`, `resources/semantic/<version>/`, `resources/waql/<version>/`, and `resources/deferred/<version>.json` through the packaged gateway. Use `describe <uri> --full-schema` only when a complete reflected schema is necessary. For exact registry counts, profile meanings, exclusions, and evidence scope, read `references/waapi-coverage.md` once as directed above; evidence status never substitutes for live behavioral proof.

## Boundaries

- Do not invent fixed API maps in the prompt when the runtime resources can resolve the correct URI.
- Never write disposable business logic for a user Wwise task. No heredoc script, inline Python, new `.py`/`.js`/`.sh` helper, or direct client construction.
- `scripts/run.py` and the environment helper accept only their immutable packaged script allowlist. Never attempt another runner target or temporary script path.
- The generic `call` path accepts only catalog rows whose preferred route is `manifest_dispatch`. Fixed functions require their packaged command, reviewed topics require `wait-topic` or `stream-topic`, and each `transaction_operation` row requires immutable preview plus confirmation or policy authorization through exactly one declared closed lane: a dedicated named operation when present, `waapi.undoGroup` for the three Undo members, and `waapi.call` only when the catalog explicitly lists it. `--dry-run`, `--allow-destructive`, and `WWISE_DESTRUCTIVE=1` do not bypass those route decisions.
- Lua is available only through its dedicated policy-gated operations: an existing non-symlink `.lua` file canonically inside `io_root`, or an exact inline string explicitly supplied by the user in Wwise 2025.1. `source_authority` is a caller assertion in the request protocol, not provenance the runtime can independently prove; set it only when the current user message actually supplies the complete code or exact file path. Never generate, repair, wrap, augment, or hide Lua for the user. Loader paths/modules and CLI project/migration switches remain closed, source size/hash is rebound before execution, side effects are not inferred or rolled back, and no Lua operation is retried.
- Private debug reads use only `debug-wal-tree`, `debug-validate-call`, or bounded `wait-topic ak.wwise.debug.assertFailed`. Process-wide mode changes require their dedicated policy-gated operations. `debug.restartWaapiServers`, `debug.testAssert`, and `debug.testCrash` require exact dangerous-action acknowledgement plus later confirmation even under `allow_changes`; execution is once-only and terminal indeterminate with explicit disconnect/process expectations, no retry, reconnect, or generic verification.
- Raw or unrestricted UI-command registration/execution and model-supplied CLI custom command hooks remain blocked. Only the closed Authoring-host routes above are available. A current live `getCommands` result—not the packaged observed inventory—is the command-ID authority. Program/Lua registration paths and content are rebound, but the `user_supplied_verbatim` value remains a caller assertion that the runtime cannot independently prove. Isolated transactions audit absolute inputs and confine every explicit write path below `io_root`; any implicit Wwise-managed write is disclosed as unproven, never misreported as confined.
- Do not search the repository to recover from a gateway error. A structured failure is the result unless the user explicitly asked to develop or debug this Skill itself.
- If a capability has no packaged executable path, return a clear `unsupported_by_skill_interface` boundary instead of synthesizing code.
- Editing this Skill's implementation is allowed only when the user's task is Skill development, testing, or debugging—not as a way to complete an ordinary Wwise request.

## Detailed references

- `references/waapi-setup.md` — connection, version, config, and status troubleshooting
- `references/waapi-query.md` — read-only inspection, selection/object lookup, topic waits/streams, and no-code failure rules
- `references/waapi-operate.md` — closed operation JSON, durable policy-aware preview/authorize/execute/verify flow, retry rules, and explicit boundaries
- `references/waapi-coverage.md` — exact five-version counts, exclusions, route meanings, and program-test scope
