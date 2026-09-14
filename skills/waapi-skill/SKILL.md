---
name: waapi-skill
description: >-
  Query, edit, and monitor Wwise projects through a local, version-aware
  WAAPI Gateway. Use to configure WAAPI connections and Wwise versions;
  inspect, create, edit, copy, move, or delete objects; update properties
  and references; import or reimport audio; generate SoundBanks; use
  supported playback and UI controls; or subscribe to Wwise events
  and monitor changes.
---

# WAAPI Skill

Use the packaged Gateway to operate Wwise. The Agent selects the requested
outcome and supplies business values; the Gateway owns version-specific
parameters, validation, execution, and verification.

Versions: `2021.1`, `2022.1`, `2023.1`, `2024.1`, and `2025.1`.

## Loading and paths

Use the complete Skill instructions supplied by the agent environment.
If they are not already loaded, read `SKILL.md` from the supplied location
before running a Gateway command. If that location or complete content is
unavailable, stop instead of searching for another installation.

The Skill root is the directory containing that `SKILL.md`. Resolve `scripts/`
and `references/` relative to this root, not the working directory or an assumed
installation path. Use the absolute path to `scripts/run.py` for Gateway calls.

Read only the reference needed for the current task, once, completely and as
UTF-8 text. Reuse complete instructions already visible in the conversation.
Use the environment's file-reading tool or a compatible shell. Shell reads
are standalone: POSIX may use `cat '<absolute-file>'`; native Windows uses
PowerShell Core with `Get-Content -Raw -Encoding UTF8 '<absolute-file>'`.
Choose by the actual execution environment, not the connected Wwise version
or the spelling of a path. A missing or truncated read stops the workflow.
For query/operate references, the matching `WAAPI_QUERY_REFERENCE_END` or
`WAAPI_OPERATE_REFERENCE_END` sentinel must be the final visible line.

Keep Gateway calls separate. Copy each returned continuation exactly as
instructed; do not reconstruct its command or change its shell syntax.

## One-time conversation introduction

When the visible conversation lacks an introduction:

- Only `/waapi-skill` or a Skill link: run one offline
  `config-show` before asking what to do.
- With a request, reuse its first required Gateway result; no extra call.
- Pure explanation: one offline `config-show`.

The next reply states `session_context.one_time_introduction.facts` together
in the user's language, in two short paragraphs: Skill loaded, WAAPI port (not URL),
Wwise 适配版本 (localize); then policy and modes. Keep mode names exact: `read_only`,
`ask_before_changes`, and `allow_changes`. Never announce before Gateway,
split facts, use memory, or a status table. Say
configured, not connected unless proved live. Closing questions are free prose,
in a new paragraph.
Never connect solely for welcome. Repeat only on request or changed
facts, not later Skill invocations. Send machine answers separately.

## Entry rules

1. Route the user's request into **setup**, **query**, or **operate**.
2. Use the supplied Skill root and the loading rules above, including for Wwise CLI and project-migration requests. Do not probe the repository or working directory to locate the Skill.
3. For common reads below, run the absolute `scripts/run.py` before `ls`, `find`, `rg`, research, or implementation reads.
4. Connection precedence is explicit flags, `WWISE_WAAPI_HOST` / `WWISE_WAAPI_PORT` / `WWISE_VERSION`, then config. Put version after `gateway.py`: `python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 operation-schema object.copy`. `--wwise-version` is the compatibility/config field. Never hand-edit config or scan unrelated ports/processes.
5. Treat gateway JSON as authoritative. Every gateway command must leave its complete JSON visible before the next command: never suppress or redirect its output, request a zero/short tool-output budget, or continue from the shell exit code alone. Copy returned `shell_tool_timeout_ms` to the outer shell tool call; never add it to the command argv. If no complete JSON is visible, stop. A structured error or shell failure stops the workflow; do not retry the Gateway command.
6. Read only the current-turn lane; never preload. Read-only work cannot read `waapi-operate.md` before a change request.

## Fixed gateway commands

Examples below are relative to the supplied Skill root; use its absolute `scripts/run.py` when executing them.

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
Tell the user the effective policy naturally: ordinary omitted-duration default
is 10 seconds; SoundBank-generated uses `--timeout 120`. Preserve a positive finite
duration, converting units to seconds without rounding, in global `--timeout`
before `wait-topic`. An explicit no-time-limit bounded-wait request selects
`--no-timeout`: until 1–64 requested matches or cancellation, not an unlimited
output stream. Never combine those flags. Default: “这次使用默认的 10 秒等待时间”.

Select `stream-topic` for a requested event count (such as “监控十次”) or
per-event/persistent output; do not add the vague-request 10-second total timeout.
It keeps one subscription, flushes matched events, and requires an
`--event-count <1..64>` ceiling. Announce `topic-schema.monitoring_policy`:
default idle cutoff is 300 seconds; explicit total durations have no implicit
idle cutoff. User overrides: `--idle-timeout <seconds>` / `--no-idle-timeout`.
Before every wait/stream,
run `topic-schema` and copy its digest and opaque `tvc1-*` handles. For
`choice_on_disclosure`, run `field_disclosure` first and use only typed `*-as`;
never guess untyped. Event size, count, cumulative bytes, and buffering are bounded; the
terminal record includes the completion and unsubscribe result.

For `ak.wwise.waapi.getFunctions`/`getTopics`, run `request-schema` and follow its sole typed continuation. Do not run `describe` or `capabilities` first.

For five-version totals, read coverage then use its host-scoped summary command. The default capability profile is Console; `--profile wwise-authoring-ui` inspects the packaged Console-plus-Authoring union, not a complete live Authoring inventory. Row filters omit `--summary-only`. The list defaults to at most 50 compact rows; `--limit 0` requests all and `--detail` is diagnostic. A user-literal function URI uses `request-schema`. For another natural-language request not covered by a fixed route, run one `operations` lookup and copy its `next_command`/guidance; never synthesize a route or choose from memory/examples. This offline directory includes named operations, business reads, and zero-input routes for the configured version. Live host checks still apply. Use `operations --detail` only for an explicit all-version catalog audit.

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
After that preflight, use `operation-schema` and its sole continuation. Business declarations start the Draft first, bind the exact owner or new-object kind, and use returned discovery commands for requested dynamic fields. Common fields use disclosed business parameters; dynamic fields use copied Field Handles. The operate reference owns this sequence for creation, edits, and imports; never infer a native token or scope.

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
