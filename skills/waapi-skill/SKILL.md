---
name: waapi-skill
description: Use this skill for Wwise and WAAPI work through the existing skill-local Python runtime, versioned manifests, semantic builders, bounded subscriptions, and safe dispatcher calls. Always use this skill when the user asks about the current Wwise project or version, current selection, object lookup, hierarchy browsing, properties, imports, soundbanks, switch assignments, topic waits, WAAPI connection/setup, or Wwise project changes, even if they do not explicitly say “WAAPI”. For every Skill-backed Wwise task, begin with the injected absolute SKILL.md locator; never search the current workspace or infer a repository-relative Skill path. Before any other shell action, read only the injected absolute SKILL.md locator in one command; that first command must not also run pwd, git, rg, ls, find, inspect a user file, or invoke the gateway. This is especially important for Wwise CLI, project migration, and the reviewed 2024.1 audio conversion route.
---

# Wwise WAAPI Skill

Use this skill to automate Wwise through its packaged, version-aware WAAPI runtime. The executable gateway is the interface. Do not replace it with temporary scripts, inline Python, direct `WaapiClient` calls, or repository archaeology.

In a fresh task, make the first shell action only the injected `SKILL.md` read. Do not prepend or append `pwd`, `git`, `rg`, `ls`, `find`, `printf`, a user-file read, a gateway command, or any other workspace action to that initial read. Finish that one read before deciding the next command.

Supported Wwise versions are `2021.1`, `2022.1`, `2023.1`, `2024.1`, and `2025.1`.

## When this skill should trigger

Use this skill whenever the user is trying to do Wwise work such as:

- checking which Wwise project or version is currently open
- checking the current selection or browsing hierarchy
- finding events, busses, sounds, work units, properties, references, or object paths
- importing audio or tab-delimited data
- previewing or changing Wwise objects, properties, soundbanks, or switch assignments
- waiting on bounded WAAPI topics or object/topic events
- diagnosing WAAPI host, port, version, or connection state
- asking whether a Wwise authoring operation is supported

Technical trigger words still count: `Wwise`, `WAAPI`, `Audiokinetic`, `topic subscription`, `manifest`, `semantic builder`, `dispatcher`, and version-specific WAAPI behavior.

## One-time conversation introduction

The first time this Skill is used in a conversation, do not announce that it is loaded before the first gateway result. When the visible conversation has no prior introduction, the first Agent message after that result must express the returned `session_context.one_time_introduction.facts` together as one short, atomic introduction: say naturally that `waapi-skill` is loaded, report the current WAAPI address, WAAPI adapter version, and project modification policy, and offer the three available modes. Do not split those facts across an earlier message and a gateway-backed message. Match the user's language and write ordinary prose, not a status bar, table, field list, or rigid template. Do not add a separate “current operation” field.

For example, natural Chinese wording is: “我已经加载了 `waapi-skill`。当前使用的 WAAPI 地址是 `ws://127.0.0.1:8080/waapi`，适配层版本为 `2022.1`，工程修改策略是 `preview_then_confirm`。若有需要，可按需切换模式：`never`、`preview_then_confirm` 或 `allow_with_notice`。” Adapt the values and wording to the gateway evidence instead of copying the example blindly. Say “当前连接的” only when the task's gateway result proves a live connection; otherwise say “当前使用的” or “当前配置的” without adding engineering-style verification boilerplate. If `session_context.available` is false or a required value is null, say simply which setting is not configured or unavailable; report the remaining facts and never guess a missing value.

Use the first gateway command already required by the user's task. If the first task is a pure explanation that otherwise needs no gateway command, run exactly one offline `config-show` to obtain the introduction facts; never run `status` or open a live WAAPI connection only for the introduction, and never inspect a config file directly. An offline task stays offline. Complete the introduction once per conversation, including when the first task is read-only or offline. Show it only when the visible conversation does not already contain this introduction; do not use memory to make that decision. Do not repeat it unless the user asks about these settings or one of the reported values changes. If the final answer must be exact machine-readable output, put the introduction in a separate normal progress update and keep the required result body exact.

## Entry rules

1. Route the request into **setup**, **query**, or **operate** from the user's words.
2. Bootstrap only from the injected absolute `SKILL.md` locator. Never guess a repository-relative `skills/waapi-skill` path or run `pwd`, `git status`, `ls`, `find`, `rg`, or another working-directory/repository probe to locate the Skill, including for Wwise CLI and project-migration requests.
3. For the common live reads below, run the matching gateway command immediately. Derive the absolute Skill directory from the injected absolute `SKILL.md` locator and invoke its absolute `scripts/run.py` path; do not rely on an unrecorded shell working directory. Do this before `ls`, `find`, `rg`, documentation research, or reading implementation files.
4. Use connection settings in this order: explicit gateway flags, `WWISE_WAAPI_HOST` / `WWISE_WAAPI_PORT` / `WWISE_VERSION`, then the external saved config reported by `config-show`. Put the runtime version selector after `gateway.py` and before its subcommand. The exact full shape is `python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 operation-schema object.copy`; `--wwise-version` is accepted in that gateway-global position as a compatibility alias and is also the saved-config field after `config-set`. Do not inspect or hand-edit config files. Do not scan unrelated ports or processes.
5. Treat gateway JSON as authoritative. Every gateway command must leave its complete JSON visible to the conversation before the next command: never suppress or redirect its output, request a zero/short tool-output budget, or continue from the shell exit code alone. If no complete JSON is visible, stop and report that missing result instead of assuming success. On a structured error or boundary, report it; do not improvise another WAAPI client or write a helper.
6. Read one lane reference only when the fixed command table does not fully answer the request.
7. After this entry file has been loaded, read any later named lane reference exactly once with `cat /absolute/path/to/waapi-skill/references/<file>.md` as its own shell tool call. “Exactly once” is scoped to the whole visible conversation/task, not to each user turn. If this `SKILL.md` or a lane reference is already present in the visible conversation from an earlier turn, do not read it again on a confirmation or other transaction-continuation turn; use the visible content and proceed with the required gateway command. Never run `wc -l`, `ls`, `rg`, `find`, `stat`, `test`, or another length, existence, or path probe before a reference read, and never split one reference across multiple reads. A complete `waapi-operate.md` read ends with the exact `WAAPI_OPERATE_REFERENCE_END` sentinel. When it is visible, proceed without any `sed`, `head`, `tail`, `rg`, or second `cat`; when it is absent, stop and report an incomplete host read instead of trying a partial reread or invoking the gateway. Make every gateway invocation its own later shell tool call. A host may bootstrap the initial complete `SKILL.md` load with exactly `wc -l <SKILL.md> && sed -n '1,<enough-lines>p' <SKILL.md>` against that same absolute file; this is the only combined read allowed. Never combine a reference read, gateway invocation, or any other commands with `&&`, `;`, a pipe, command substitution, or a multi-command shell string because those actions are not independently auditable.

## Fixed gateway commands

The snippets below use `scripts/run.py` as readable shorthand. In the actual tool call, replace it with the absolute path derived from this injected `SKILL.md` locator, for example `python /absolute/path/to/waapi-skill/scripts/run.py gateway.py status`. Never execute the relative `scripts/run.py` spelling in an automated agent run.

```bash
python scripts/run.py gateway.py status
python scripts/run.py gateway.py config-show
python scripts/run.py gateway.py config-set --wwise-version 2022.1 --waapi-host 127.0.0.1 --waapi-port 8080 --project-modification-policy preview_then_confirm
python scripts/run.py gateway.py config-set --reset
python scripts/run.py gateway.py buses
python scripts/run.py gateway.py selected
python scripts/run.py gateway.py capabilities --all-versions --summary-only
python scripts/run.py gateway.py capabilities --all-versions --query object.get --limit 20
python scripts/run.py gateway.py describe <uri> --all-versions
python scripts/run.py gateway.py --version <supported-version> call ak.wwise.waapi.getFunctions --args-json '{}' --options-json '{}'
python scripts/run.py gateway.py --version <supported-version> call ak.wwise.waapi.getTopics --args-json '{}' --options-json '{}'
python scripts/run.py gateway.py --version <supported-version> call <bounded-read-uri> --args-json '<object>' --options-json '<object>'
python scripts/run.py gateway.py query-object --path '<exact-object-path>' --return-field id --return-field name --return-field type --return-field path
python scripts/run.py gateway.py query-object --type Event --take 100
python scripts/run.py gateway.py metadata types --summary-only
python scripts/run.py gateway.py --timeout 10 wait-topic <topic-uri>
python scripts/run.py gateway.py --timeout 10 wait-topic <topic-uri> --event-count <1..64> --match-json '<object>'
python scripts/run.py gateway.py operations
python scripts/run.py gateway.py operation-schema object.create
python scripts/run.py gateway.py operation-schema object.set
python scripts/run.py gateway.py operation-schema waapi.call
python scripts/run.py gateway.py operation-schema waapi.undoGroup
python scripts/run.py gateway.py operation-schema audio.import
python scripts/run.py gateway.py --version 2022.1 operation-schema object.copy
```

Use exactly one command for the corresponding intent:

| User intent | Command | Live WAAPI evidence |
| --- | --- | --- |
| current Wwise version, endpoint, or project | `status` | `getInfo` plus `getProjectInfo` (2022.1+) or manifest-backed `object.get` (2021.1) |
| inspect or save connection/version/policy config | `config-show` / `config-set` | offline external config contract; no Wwise connection |
| list current project Buses | `buses` | `ak.wwise.core.object.get` |
| current UI selection | `selected` | `ak.wwise.ui.getSelectedObjects` |
| inspect packaged API support, schema, route, or boundary | `capabilities` / `describe` | offline versioned resources; no Wwise connection |
| call a capability whose catalog route is `manifest_dispatch` | `call` with reflected args/options | recursively validated bounded live result |
| object lookup by path, id, type, search, or query object | `query-object` | semantic query builder plus `ak.wwise.core.object.get` |
| object type/property/reference metadata | `metadata` | fixed metadata builder and typed result parser |
| wait for one or a fixed bounded count of topic events | `wait-topic` | 1–64 matching events, one total timeout, optional JSON payload match, guaranteed unsubscribe |
| inspect project-changing operation support | `operations` / `operation-schema` | offline closed request schema and explicit executable boundary |

Each command prints one JSON document. Summarize its actual values in the user's language. Do not paste the whole JSON unless asked. Every result includes a bounded `session_context`; use it for the one-time conversation introduction above and do not reconstruct those settings from prose, configuration files, or assumptions.

Exact reflection-call fast route: when the user explicitly asks to call `ak.wwise.waapi.getFunctions` or `ak.wwise.waapi.getTopics` with empty args and options, run exactly one matching `call` command from the table, replacing `<supported-version>` with the exact requested or connected Wwise version. Do not run `describe` or `capabilities` first, and do not read the query reference before or after the call. The reviewed route is already fixed by this Skill. If that one gateway invocation is rejected or fails, stop and report the result; never retry it with another command.

For capability discovery, start with `capabilities --all-versions --summary-only`, then add `--query`, `--category`, `--item-type`, `--family`, or `--route` and request only the needed rows. The list defaults to at most 50 compact rows; `--limit 0` is an explicit all-row opt-in, and `--detail` is only for nested interface, schema-summary, policy, or evidence auditing. When a URI is already known, use `describe <uri>` instead of listing the matrix, except for an explicit exact reflection call or a reviewed direct `waapi.call` fast route named in the operate lane below. A known row with `preferred_route: manifest_dispatch` may use `call`. For `transaction_operation`, obey the returned `transaction_operations`: prefer a listed dedicated semantic operation, use `waapi.undoGroup` for its three member URIs, and use `waapi.call` only when no dedicated operation applies. For operations, use the compact `operations` inventory only for a genuinely broad inventory question; use `operation-schema <name>` directly for any named operation, and reserve `operations --detail` for an explicit full-catalog contract audit.

When the user explicitly asks for the five-version coverage numbers, exclusions, or what the program matrix proves, read `references/waapi-coverage.md` once and combine it with the current offline catalog. Do not claim that program-tested coverage is live-Wwise verification.

Broad `query-object` sources and every `--select` require `--take N` with `0 <= N <= 1000`; use `--all-results` only when the user explicitly asks for an unbounded result. The fixed `buses` command is bounded to 1000 rows and reports that bound plus whether truncation is possible. Never route `ak.wwise.core.object.get` through the generic `call` command: the gateway returns `QUERY_OBJECT_REQUIRED` so all object discovery stays inside `query-object`. Other fixed-command URIs return `FIXED_COMMAND_REQUIRED`, and topic URIs return `WAIT_TOPIC_REQUIRED`; use the command named by that boundary instead of retrying `call`.

When the requested answer is machine-readable and any successful gateway payload contains `agent_result`, compact-serialize exactly that object as the result body and stop. This rule applies to fixed reads as well as transactions. Do not reconstruct its fields from the prompt, `normalized`, summaries, or verification evidence; do not alter JSON escaping or add/remove keys; and do not run another command after receiving it. If the required envelope is `WAAPI_RESULT_JSON=<json>`, append the compact serialization of `agent_result` directly after the prefix. Failed, deferred, indeterminate, or boundary payloads intentionally have no successful `agent_result`; report their actual state instead of inventing one. The one-time introduction belongs in a separate progress update when needed and never changes the exact machine-readable result body. For a normal natural-language answer, use the complete gateway evidence rather than only the compact projection.

## Routing

### Setup lane

Use setup when the task is about connection state, version detection, host/port issues, saved config, or “what Wwise instance is this talking to?”.

Examples:
- “Which Wwise version is open?”
- “What project is currently open?”
- “WAAPI isn’t connecting.”
- “What endpoint are you using?”

Read: `references/waapi-setup.md`

### Query lane

Use query for read-only inspection: selection, object lookup, hierarchy browsing, property reads, WAQL-shaped discovery, project facts, bounded topic waits, and other non-mutating inspection.

Classify the requested action, not background wording. A request to listen for, wait for, or report a SoundBank generation notification is a query-only topic task even when it says that a Bank is being generated or rebuilt and even when an old output file already exists. It never authorizes `soundbank.generate`, an operation-schema lookup, or another mutation.

Examples:
- “What object is selected right now?”
- “Find this Event.”
- “Show me the current project structure under this Work Unit.”
- “Wait for object.created once, then report it.”

Default result shape: return the resolved structured result, not just “I called WAAPI”.

Fast route from this entry file: when the user supplies one exact object path and asks whether that object exists or asks for its standard identity, run exactly one `query-object --path '<exact-object-path>' --return-field id --return-field name --return-field type --return-field path` command. For one exact GUID, use the same command with `--object-id '<exact-guid>'` in place of `--path`. Keep all four return fields explicit even though they are gateway defaults. This fixed route is complete: do not read the query reference before or after it, and do not retry a rejected or failed gateway invocation.

For current-selection questions, prefer the live selected-object query path first. If the connected endpoint is a headless or command-line Wwise instance where the UI selection API is unavailable, report that boundary clearly instead of drifting into repo/docs research or pretending a selection result exists.

For `query-object --where-json`, translate the user's comparison literally: `"operator":"="` means exact equality, while `"operator":":"` is a contains/match predicate. A request to search and then restrict `name` to the exact same value therefore uses `--search '<value>'` plus `--where-json '{"field":"name","operator":"=","value":"<value>"}'`; `:` does not satisfy an exact-name request.

Conditional read for a query not fully covered by the fixed commands, exact-identity fast route, or exact reflection-call fast route: `references/waapi-query.md`

### Operate lane

Use operate for project-changing work: create, move, copy, delete, property/reference edits, imports, soundbanks, switch assignments, and design previews.

Examples:
- “Create a new Event under this Work Unit.”
- “Import these files.”
- “Generate or update this soundbank setup.”
- “Assign this object to the Switch Container.”

Choose the transaction phase before choosing a command. An existing transaction continuation takes precedence over the named-operation rule, but it requires the transaction id; an artifact hash alone is not a transaction lookup key. When the user confirms, checks, or continues an already previewed transaction and its transaction id is available from the message or conversation, reuse the Skill and operate reference already visible from the preview turn: do not reread either file in the same visible conversation/task; run `transaction-show <transaction-id> --summary-only` first, proceeding directly from the already-visible instructions. Read the operate reference exactly once only when it is not already visible. Do not call `operations`, `operation-schema`, or `preview` before that show call; the immutable preview already contains the closed request and schema. A successful preview supplies that show command as `next_command.full_argv`; after the later user message, copy the entire array exactly, including its canonical absolute `scripts/run.py` path. Never reconstruct, shorten, or normalize that launcher prefix from memory. `transaction-show` is the continuation safety gate: its complete JSON must be visible. If that output is empty, truncated, non-JSON, or otherwise incomplete—even with exit code `0` or a transaction id/hash from the preceding turn—stop without calling `confirm`, `execute`, `verify`, or `reject`, and do not retry the show in that turn. When its state is `awaiting_confirmation`, the Gateway returns a short opaque `confirmation.token` bound to that stored transaction and supplies the exact `confirm <transaction-id> --confirmation-token <token>` continuation in `next_command`; only after the current user message clearly authorizes execution may its returned `shell_command` be copied verbatim and run. Never generate, shorten, validate from its spelling, reconstruct, or substitute that token, and never fall back to the displayed artifact hash. Never run `confirm --help` or assemble a confirmation command from memory. Every later continuation command is gated the same way: in particular, if `confirm` does not return complete visible JSON, stop before `execute` or `verify`, even when its shell exit code is `0`. A status or check request stops after `transaction-show`; this means after its complete JSON is visible. User intent authorizes every later action; the returned state only constrains which actions are legal and never authorizes `confirm`, `execute`, `verify`, or `reject` by itself.

`next_command.shell_command` is the directly executable form. When the user has authorized that state transition, pass this returned string verbatim as one shell tool call; do not translate `full_argv` into a command yourself. `shell_family` identifies the host spelling chosen by the gateway, which owns every launcher path segment.

The Gateway keeps `next_command` after `session_context` as the final actionable top-level field. A preview also mirrors that same object as the final field of its terminal `agent_result`; execute the structured tail's returned shell command without rebuilding it.

For a new change request with no existing transaction, use the named semantic operation whenever `describe` lists one; the generic route rejects that URI with `DEDICATED_OPERATION_REQUIRED`. Otherwise use `describe <uri>`, except for the reviewed direct `waapi.call` fast routes named below. For every other row reporting `transaction_operation`, use the exact declared operation: `waapi.undoGroup` for its three member URIs or `waapi.call` only for a row with no dedicated operation. Do not run `operations` first. A successful `operation-schema` owns the outer request: when its `request_envelope_policy.status` is `ready`, copy `request_envelope` exactly and replace only `arguments`; never omit its `version` even when the gateway is already configured. Then use `preview`, wait for a later explicit confirmation, bind it with `confirm`, execute the immutable transaction once, and run `verify` only when the complete execute result is successful and reports `executed_unverified`. A complete execute result with `status` and `state` both `indeterminate` is terminal for that turn: report it and stop immediately without `verify`, retry, `transaction-show`, another gateway call, filesystem inspection, or any other follow-up command. A later diagnosis requires a new user request and must use a packaged read-only Skill route; caller-owned test oracles remain outside the Skill command sequence. A rejected `preview`, invalid JSON/shell invocation, or any `preview` output that is not complete gateway JSON ends that turn immediately: do not fix and retry the command in the same turn. `ak.wwise.cli.migrate` is the narrow exception: after its one complete `execute` JSON, stop all gateway activity immediately—do not run generic `verify`, `status`, `query-object`, `call`, or another gateway command to reopen or inspect the migrated project. The caller-owned reopened-project oracle runs outside this Skill command sequence and is responsible for final business verification. Generic verification proves the returned reflected result schema; do not describe it as an operation-specific Wwise state readback. Never invoke planner/builder classes, construct a raw mutation, or write code.

Except for `ak.wwise.cli.migrate`'s terminal `execute`, `verify` is the terminal authority for the selected contract: dedicated operations return their live readback, while generic `waapi.call` returns reflected result-schema evidence. After `verify` returns `verified` or another terminal verification state, stop the gateway sequence and report exactly that evidence. Do not add `query-object`, `call`, or another gateway command to double-check the same mutation. The only narrow workflow exception is an original request that already closed and ordered multiple independent transactions: after a successful non-final `verify`, run only the next transaction's `operation-schema` and immutable `preview`, then stop for a later explicit confirmation; never execute that next preview in the same turn.

In ordinary agent use, omit `--state-dir` and let the caller or broker inject the transaction store implicitly. Never run `env`, `printenv`, shell expansion, or another environment-inspection command to discover `WAAPI_SKILL_STATE_DIR`, and never guess or search for a state directory. Pass `--state-dir` only when the user or trusted caller explicitly supplied a trusted absolute path. If the gateway returns a structured state-directory error or boundary, report it and stop instead of probing the environment or filesystem.

Fast route from this entry file:

- Closed transaction operations are `waapi.call`, `waapi.undoGroup`, `object.create`, `object.set`, `object.delete`, `object.setName`, `object.setNotes`, `object.setProperty`, `object.setReference`, `audio.import`, `audio.importTabDelimited`, `soundbank.setInclusions`, `soundbank.generate`, `soundbank.convertExternalSources`, `soundbank.processDefinitionFiles`, `switchContainer.addAssignment`, and `switchContainer.removeAssignment`. For a new request, read `references/waapi-operate.md` in its own tool call, then run the named `operation-schema` and transaction commands as separate tool calls. For an existing transaction continuation, do not reread an already-visible Skill or operate reference; skip `operation-schema` and `preview`; start with `transaction-show`.
- For an object-tree request, evaluate the `object.set` lock before considering an existing-root `object.create` merge. Any requested field or reference change on an existing root, more than one existing root, or an append under a nested container explicitly identified as existing selects `object.set` and excludes `object.create`. Only after all three exclusions are absent may `object.create` merge into exactly one same-name existing root, and then only when that root stays unchanged and the request is a pure descendant-tree merge. A wholly new recursive root also uses `object.create`.
- Route the three reviewed connected-Authoring SoundBank workflows directly: connected-Authoring bank generation uses `soundbank.generate`, connected-Authoring External Sources `.wsources` conversion uses `soundbank.convertExternalSources`, and connected-Authoring Definition `.tsv` processing uses `soundbank.processDefinitionFiles`. These are the `ak.wwise.core.soundbank.*` routes. Only a request that explicitly asks for WwiseConsole, CLI, command-line, or 命令行 execution selects the distinct 2022.1 `ak.wwise.cli.*` `waapi.call` family; a `.wproj` path, JSON `project` field, project-copy description, output/cache path, `.wsources`, Bank list, or TSV alone is input data, not CLI intent. For a new connected-Authoring request—including SoundBank generation without that explicit CLI wording—the first gateway command after the operate-reference read is the matching named `operation-schema`, so generation begins with exactly `operation-schema soundbank.generate`; do not run `describe`, `query-object`, or `operation-schema waapi.call` first. Do not inspect a supplied `.wsources` or `.tsv` with `cat`, `sed`, or another shell command, and do not split identity prechecks into a separate query: the named operation's `preview` owns strict file parsing, input proofs, and required live identity resolution. After its successful `execute` reports `executed_unverified`, run `verify` before answering.
- When the configured/runtime Wwise version is `2022.1`, the four deterministic `ak.wwise.cli` transaction rows are direct `waapi.call` fast routes. The reflected-identical Wwise `2024.1` and `2025.1` `ak.wwise.core.audio.convert` routes share a separate direct fast route. After the exact absolute Skill and operate-reference reads, the matching version-scoped route's first gateway command is `operation-schema waapi.call`; do not run `describe` or `capabilities` first. If the version is not visible before that first gateway call, use the same safe offline `operation-schema waapi.call` first and read its returned `session_context`: continue with the fixed mapping only when it reports one of the route's exact reviewed versions. If it reports another version, do not preview; use that version's ordinary `describe <uri>` path next. If the version remains unavailable, report that boundary or ask for the target version without guessing. For every other known Wwise version, the CLI rows use the ordinary versioned `describe` path above; never reuse the 2022.1 field mapping against another version's schema.
- For an exact Wwise `2024.1` or `2025.1` `ak.wwise.core.audio.convert` intent, construct the preview request from the returned Gateway-owned `direct_fast_route_contract.canonical_request_template` and its rules. Copy that version-bound closed shape, replace only the listed values, and never omit `args.languages`; natural SFX targets keep the literal `languages:["SFX"]` unless the user explicitly states localized languages. This contract does not apply to any other `waapi.call` URI.
- For Wwise `2021.1`, `soundbank.generate` obtains project paths only from the live Project `filePath` plus a contained, hashed `.wproj`; never ask the user to provide or reconstruct a project layout.
- `waapi.call` is the packaged fallback only for catalog transaction rows whose `transaction_operations` contain `waapi.call` and no implemented dedicated operation. Dedicated URIs reject it with `DEDICATED_OPERATION_REQUIRED`; the three Undo Group member URIs are executable only through the same-connection `waapi.undoGroup` operation. Neither operation accepts an invented URI or code. `isolated_transaction` requests may require an absolute `io_root`; custom CLI command hooks are always rejected. Read the operate reference before constructing either request.

Conditional read for a closed transaction: `references/waapi-operate.md`

## Runner and packaged runtime

Use the skill-local wrapper so dependencies and paths stay consistent:

```bash
python scripts/run.py --help
python scripts/run.py gateway.py --help
```

Key runtime pieces:

1. `scripts/run.py`: skill-local script runner.
2. `wwise_waapi/dispatcher.py`: validated WAAPI function and topic dispatch.
3. `wwise_waapi/builders/`: semantic builders and preview objects.
4. `wwise_waapi/manifest.py`: versioned manifest loading and reflection helpers.
5. `resources/manifest/<version>/`, `resources/semantic/<version>/`, `resources/waql/<version>/`, and `resources/deferred/<version>.json`: packaged runtime resources loaded on demand.
6. `wwise_waapi/operation_registry.py`, `transaction_runtime.py`, and `transactions.py`: closed operation requests, live preflight/verifiers, immutable artifacts, and the durable state machine.

The catalog commands are offline and distinguish manifest availability, executable route, safety gate, runtime profile, recursive reflected-schema validation, and evidence status. `capabilities` and `operations` return compact inventories by default while retaining safety and transaction boundaries. Use their `--detail` flags only for an explicit whole-row audit. `describe` returns a compact request/result/event schema summary by default; use `describe <uri> --full-schema` only when the complete reflected schema is necessary. Evidence status never substitutes for live behavioral proof. A fail-closed execution registry assigns all 814 reflected version/API rows to exactly one route: 769 executable rows and 45 explicit exclusions. The direct `call` set is data-driven and limited to catalog rows with `manifest_dispatch`; other included functions use fixed commands, confirmed `waapi.call` transactions, or the closed same-connection `waapi.undoGroup` composite. Reviewed topics use bounded waits with publish-schema validation. A future URI or same-count inventory substitution fails its per-version digest instead of being inferred safe from its spelling.

## Boundaries

- Do not invent fixed API maps in the prompt when the runtime resources can resolve the correct URI.
- Never write disposable business logic for a user Wwise task. No heredoc script, inline Python, new `.py`/`.js`/`.sh` helper, or direct client construction.
- `scripts/run.py` and the environment helper accept only their immutable packaged script allowlist. Never attempt another runner target or temporary script path.
- The generic `call` path accepts only catalog rows whose preferred route is `manifest_dispatch`. Fixed functions require their packaged command, reviewed topics require `wait-topic`, and each `transaction_operation` row requires immutable preview/confirmation through exactly one declared closed lane: a dedicated named operation when present, `waapi.undoGroup` for the three Undo members, and `waapi.call` only when the catalog explicitly lists it. `--dry-run`, `--allow-destructive`, and `WWISE_DESTRUCTIVE=1` do not bypass those route decisions.
- Arbitrary Lua, unsafe/private debug APIs, unrestricted UI command registration/execution, and model-supplied CLI custom command hooks remain blocked. UI command add-ons can launch external programs, while unrestricted built-in command IDs can bypass reviewed project-transition guards. Isolated transactions audit absolute inputs and confine every explicit write path below `io_root`; any implicit Wwise-managed write is disclosed as unproven, never misreported as confined.
- Do not search the repository to recover from a gateway error. A structured failure is the result unless the user explicitly asked to develop or debug this Skill itself.
- If a capability has no packaged executable path, return a clear `unsupported_by_skill_interface` boundary instead of synthesizing code.
- Editing this Skill's implementation is allowed only when the user's task is Skill development, testing, or debugging—not as a way to complete an ordinary Wwise request.

## Detailed references

- `references/waapi-setup.md` — connection, version, config, and status troubleshooting
- `references/waapi-query.md` — read-only inspection, selection/object lookup, bounded topic waits, and no-code failure rules
- `references/waapi-operate.md` — closed operation JSON, durable preview/confirm/execute/verify, retry rules, and explicit boundaries
- `references/waapi-coverage.md` — exact five-version counts, exclusions, route meanings, and program-test scope
