---
name: waapi-skill
description: Use for every Wwise/WAAPI setup, read, topic, or change. Read only the injected SKILL.md locator first; never search for or infer it. Choose by command host, not Wwise/Codex version or path spelling. POSIX uses `cat '<literal-locator>'` or exact `sed -n '1,$p' '<literal-locator>'`; a whitespace-free POSIX locator uses unquoted `cat <literal-locator>`. native Windows uses exact `Get-Content -Raw -Encoding UTF8 '<literal-locator>'` in PowerShell Core. Never cross-use/wrap these forms or combine the read with unrelated action.
---

# Wwise WAAPI Skill

Automate Wwise through the packaged gateway. Use no inline Python or direct `WaapiClient`.

Read the injected `SKILL.md` exactly once as the sole first shell action in a fresh task. A successful read is complete; a second `SKILL.md` read is forbidden. Never combine it with `pwd`, `git`, `rg`, `ls`, `find`, `printf` or another action.

Versions: `2021.1`, `2022.1`, `2023.1`, `2024.1`, and `2025.1`.

## One-time conversation introduction

When the visible conversation lacks an introduction, wait for the task's first
required Gateway result. The very next Agent message states
`session_context.one_time_introduction.facts` together in natural prose: Skill
loaded, current WAAPI address, adapter version, policy, and three modes. The
same introduction must name them exactly: `read_only`, `ask_before_changes`,
and `allow_changes`. A Skill/reference read is not a Gateway result; never
announce early, split facts, use memory, or format a status table. Say
“当前连接的” only for a proved live connection; otherwise “当前使用的/配置的”.

Use the task's first required Gateway command. For a pure explanation, use one
offline `config-show`; never open a live connection only for the introduction.
Repeat only on request or changed facts; keep exact machine answers in a
separate progress update.

## Entry rules

1. Route the user's request into **setup**, **query**, or **operate**.
2. Bootstrap only from the injected `SKILL.md` locator. Never guess a repository-relative `skills/waapi-skill` path or probe with `pwd`, `git status`, `ls`, `find`, or `rg`, including for Wwise CLI and project-migration requests.
3. For common reads below, resolve the locator to the absolute Skill directory without probing and run its absolute `scripts/run.py` before `ls`, `find`, `rg`, research, or implementation reads.
4. Connection precedence is explicit flags, `WWISE_WAAPI_HOST` / `WWISE_WAAPI_PORT` / `WWISE_VERSION`, then config. Put version after `gateway.py`: `python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 operation-schema object.copy`. `--wwise-version` is the compatibility/config field. Never hand-edit config or scan unrelated ports/processes.
5. Treat gateway JSON as authoritative. Every gateway command must leave its complete JSON visible before the next command: never suppress or redirect its output, request a zero/short tool-output budget, or continue from the shell exit code alone. Copy returned `shell_tool_timeout_ms` to the outer shell tool call; never add it to the command argv. If no complete JSON is visible, stop. A structured error is final. On native Windows, only `CreateProcessAsUserW failed: 267` before PowerShell starts permits you to repeat that identical complete shell command once. This is process-launch recovery, not a Gateway retry. A second 267 or any other shell failure stops.
6. Read only the current-turn lane; never preload. Read-only work cannot read `waapi-operate.md` before a change request.
7. Read each later named lane reference exactly once in its own shell call. POSIX uses `cat <absolute-reference>`. Native Windows always copies the short task-local form `Get-Content -Raw -Encoding UTF8 '.agents\skills\waapi-skill\references\<file>.md'` exactly instead of reconstructing a scenario-root absolute path. Exactly once spans the visible task, not each turn; never reread an already-visible file. Do not probe with `wc -l`, `ls`, `rg`, `find`, `stat`, or `test`, and never split a reference. For `WAAPI_QUERY_REFERENCE_END` and `WAAPI_OPERATE_REFERENCE_END`, proceed only when the matching sentinel is the final visible line. Each Gateway call is separate. Only POSIX may bootstrap the initial complete `SKILL.md` against the same literal file with exact `wc -l <SKILL.md> && sed -n '1,<enough-lines>p' <SKILL.md>`; this is the only combined read allowed. Never combine any other command.

## Fixed gateway commands

Use the injected absolute `scripts/run.py`.

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
python scripts/run.py gateway.py request-schema <exact-user-supplied-reflected-function-uri>
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

Register a runtime Game Object with `request-schema ak.soundengine.registerGameObj`; unregister via its schema, never `object.create`.

`status` is the sole Gateway-owned `getInfo` route for connection/version/project. Do not use `request-schema` or `typed-zero-call` instead. It needs only this `SKILL.md`; do not read the setup or query reference. Treat the named `getInfo` result's `processId` as the requested live process identity; finish from that Gateway evidence without a system process lookup.

Every command except `stream-topic` prints one JSON document; streaming emits bounded NDJSON plus one terminal record.

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
subscription, flushes matched events, requires an `--event-count <1..64>` ceiling, and
may have a gateway-global timeout. Before every wait/stream,
run `topic-schema` and copy its digest and opaque `tvc1-*` handles. For
`choice_on_disclosure`, run `field_disclosure` first and use only typed `*-as`;
never guess untyped. Event size, count, cumulative bytes, and buffering are bounded; the
terminal record includes the completion and unsubscribe result.

For `ak.wwise.waapi.getFunctions`/`getTopics`, run `request-schema` and follow its sole typed continuation. Do not run `describe` or `capabilities` first.

For five-version totals, read coverage then run exactly `capabilities --all-versions --summary-only`; it includes every route count. Row filters omit `--summary-only`. The list defaults to at most 50 compact rows; `--limit 0` requests all and `--detail` is diagnostic. A user-literal URI uses `request-schema`. For another natural-language change/Preview without an exact Gateway operation or URI, run one `operations` lookup and copy its route/guidance; never synthesize one or choose from memory/examples. Then use `operation-schema` for a name or `request-schema` for a URI. Use `operations --detail` only for an explicit full-catalog audit.

For totals, coverage, exclusions, or matrix proof, read `references/waapi-coverage.md` once after `SKILL.md` and before the summary. Program tests are not live-Wwise verification.

Object discovery starts with closed `query-schema`; use its bounded advanced
contract only when needed. An advanced one-row response never certifies uniqueness.
Before mutation, show candidates and exact-ID verify the chosen GUID/name/type/path.
The same applies to a mutation subset selected from multiple business-declaration or advanced results; relationship-GUID read hops are exempt.
For `mutation_selection`, run nothing now. If the user later selects candidates to mutate, copy each selected command before reading operate or choosing an operation.
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

Use setup for connection/config. `status` covers current status/version/project/process identity: after `SKILL.md`, run `status` directly and do not read `waapi-setup.md`. Read setup only for saved changes.

Read: `references/waapi-setup.md`

### Query lane

Use query for selection, object/hierarchy/property/project reads, discovery, and topics.

Classify the requested action, not background wording. A request to listen for, wait for, or report a SoundBank generation notification is query-only. It never authorizes `soundbank.generate`, an operation-schema lookup, or mutation.

A diagnosis-only turn reads only `waapi-query.md`; it must not preload `waapi-operate.md`.

Classify the complete read-only task before its first hop. If it needs multiple or relationship hops, fully read `references/waapi-query.md` before any Gateway command; an exact path/GUID first hop does not make the whole task a complete fast route.

For a complete single-hop exact path/GUID existence or identity lookup, run exactly `query-object` with one literal `--path-segment` per hierarchy level, or `--exact-id '<exact-guid>'`. The Gateway constructs path separators and always returns the four identity fields. Exact `not_found` stays Gateway-owned in compact output; use `--detail` only for explicit compile/dispatch diagnostics. This route is complete: do not read the query reference before or after it; do not retry a rejected or failed gateway invocation.

Conditional read for a query not fully covered by the fixed commands, exact-identity fast route, or exact reflection-call fast route: `references/waapi-query.md`

### Operate lane

Use operate for project-changing work: create, move, copy, delete, property/reference edits, imports, soundbanks, switch assignments, and design previews. An exact path/GUID identity preflight inside a change request is part of the operate lane; read only `references/waapi-operate.md` for that task.

Finish any required selected-subset exact-ID readback first. Finish any user-requested exact path/type preflight before `operation-schema object.create`. Only an explicit before-preview type/path check of the same-name request root triggers it; a parent path, preserved sibling, or post-execution verification does not.
After that preflight, `object.create` runs `operation-schema`, one `metadata discover` for its 1–8 dynamic fields, then `draft-start`. `object.set` batches and revalidates its dynamic fields. Import, lifecycle, scalar property/reference, and platform-link operations use `business_declaration`. For the last three, bind the target, pass its English field meaning and optional platform to `draft-discover-fields`, and copy one handle—never a token. Import alone uses token custom-field binding. For other
operations, only an explicit unknown dynamic property/reference token needs
metadata in the operate-reference order; never infer a token or scope.
For `object.create`, finish every prompt-present metadata-disclosed field before `children`.

Apply the latest `session_context` policy and copy the returned Preview exactly. For Business Drafts, copy the returned `preview-from-draft` continuation exactly; it is executable without the flag. Never append `--apply` to `preview-from-draft`.

- `read_only`: keep the project unchanged; stop after schema or a design-only non-executable Preview.
- `ask_before_changes`: create the executable Preview without asking first, summarize it, state nothing changed, ask to proceed, and end the turn. Even when the same request names later independent changes, run no more Gateway commands in that turn.
- `allow_changes`: an unambiguous actual change may return `policy_authorized`; name its root/major children, execute once from `next_command.copy_instruction.source_field`, then verify. Preview/plan/explain requests stop at the non-executable Preview.

Normal prose covers only objects, changes, results, risks, and whether anything changed. Hide API/operation names, Draft/transaction internals, ids, hashes, tokens, states, and commands. Keep exact `agent_result` machine-readable.

`read_only` still permits reads. A packaged `effect: read` function may use the transaction lane for bounded schema/result validation without `--apply`; never reclassify a mutation from wording. The original user message supplies authority and the Gateway decides whether `--apply` is present. Ambiguity stops. Never auto-authorize `debug.restartWaapiServers`, `debug.testAssert`, or `debug.testCrash`.

Choose the transaction phase before choosing a command. An existing transaction continuation takes precedence over the named-operation rule; it requires the transaction id, and an artifact hash alone is not a transaction lookup key. For a confirmation, check, or continuation, reuse the already-visible Skill/reference and run `transaction-show <transaction-id> --summary-only` first; skip schema discovery and start with `transaction-show`. Follow only its complete returned continuation and selected `copy_instruction.source_field`; diagnostic `full_argv` is not executable. An incomplete result stops the turn. `awaiting_confirmation` also requires current user authorization and its opaque token; `policy_authorized` has no token. A status or check request stops after `transaction-show`.

For a new change, use its named operation or exact-URI `request-schema` and follow one continuation. For `core-business/v1`, the exact returned continuation owns the read shape. Bind returned object/Field Handles and submit one complete Core plan; never type native tokens, enums, GUID arrays, curve/edge objects, or request fragments. Execute once; `verify` is terminal authority. Rejection, incompleteness, or `indeterminate` stops. `ak.wwise.cli.migrate` stops after execute. Never invoke internal planners/builders or construct raw requests.

For user-ordered independent transactions, preserve order and scope. In ordinary agent use, omit `--state-dir`: the Gateway owns a deterministic external runtime-state default. Never probe `WAAPI_SKILL_STATE_DIR`; pass `--state-dir` only when a trusted absolute override was explicitly supplied, and reuse it unchanged.

Fast route from this entry file:

- Closed transaction operations include `waapi.undoGroup`, all `object.*`, `audio.*`, `soundbank.*`, `switchContainer.*`, `ui.*`, `lua.*`, and `debug.*` operations returned by `operation-schema`; other reviewed mutations use exact-URI `request-schema`. New work reads `references/waapi-operate.md`; an existing transaction skips schema discovery and starts with `transaction-show`.
- For structure-only changes, one existing object's single rename/notes/property/reference edit uses its dedicated operation. `object.set` is for broader atomic existing-target work; `object.create` is for a new root or descendants below one unchanged same-name root.
- Primary media import uses one `audio.import`; business declarations own hierarchy and Event/Switch outcomes. Never probe `object.create` or a separate assignment first. On Wwise 2023.1+, use `object.set` when import is subordinate to a broader existing-target mutation. Caller tables use `audio.importTabDelimited`.
- The operate reference owns version-specific typed request mappings and all remaining operation rules. Follow that reference literally after its one complete read.

Conditional read for a closed transaction: `references/waapi-operate.md`

## Runner and packaged runtime

Loads versioned manifest, semantic, WAQL, and deferred resources. Use `describe <uri> --full-schema` only when needed. `waapi-coverage.md` owns counts/evidence, never live proof.

## Boundaries

- Never invent API maps or disposable logic: no heredoc, inline Python, new `.py`/`.js`/`.sh` helper, direct client construction, alternate runner, or temporary script.
- Use only packaged commands or returned `request-schema` / `operation-schema` continuations. Mutations always require immutable Preview plus confirmation or policy authorization; `typed-call` cannot bypass routing.
- Lua uses only exact user source/path. Debug controls execute once. Raw UI hooks/model CLI stay blocked; writes stay below `io_root`.
- Do not search the repository to recover from a gateway error. Return structured failure or `unsupported_by_skill_interface` unless the user requested Skill development/debugging.
- Editing is allowed only for Skill development, testing, or debugging—not to complete ordinary Wwise work.

## Detailed references

- In `references/`: `waapi-setup.md` config, `waapi-query.md` reads/topics, `waapi-operate.md` changes, `waapi-coverage.md` counts/evidence.
