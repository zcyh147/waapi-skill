---
name: waapi-skill
description: Use this skill for Wwise and WAAPI work through the existing skill-local Python runtime, versioned manifests, semantic builders, bounded subscriptions, and safe dispatcher calls. Always use this skill when the user asks about the current Wwise project or version, current selection, object lookup, hierarchy browsing, properties, imports, soundbanks, switch assignments, topic waits, WAAPI connection/setup, or Wwise project changes, even if they do not explicitly say “WAAPI”.
---

# Wwise WAAPI Skill

Use this skill to automate Wwise through its packaged, version-aware WAAPI runtime. The executable gateway is the interface. Do not replace it with temporary scripts, inline Python, direct `WaapiClient` calls, or repository archaeology.

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

## Entry rules

1. Route the request into **setup**, **query**, or **operate** from the user's words.
2. For the common live reads below, run the matching gateway command immediately. Derive the absolute Skill directory from the injected absolute `SKILL.md` locator and invoke its absolute `scripts/run.py` path; do not rely on an unrecorded shell working directory. Do this before `ls`, `find`, `rg`, documentation research, or reading implementation files.
3. Use connection settings in this order: explicit gateway flags, `WWISE_WAAPI_HOST` / `WWISE_WAAPI_PORT` / `WWISE_VERSION`, then the external saved config reported by `config-show`. Put the runtime version selector after `gateway.py` and before its subcommand. The exact full shape is `python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 operation-schema object.copy`; `--wwise-version` is accepted in that gateway-global position as a compatibility alias and is also the saved-config field after `config-set`. Do not inspect or hand-edit config files. Do not scan unrelated ports or processes.
4. Treat gateway JSON as authoritative. On a structured error or boundary, report it; do not improvise another WAAPI client or write a helper.
5. Read one lane reference only when the fixed command table does not fully answer the request.
6. After this entry file has been loaded, read any later named lane reference exactly once with `cat /absolute/path/to/waapi-skill/references/<file>.md` as its own shell tool call. Never run `wc -l`, `ls`, `rg`, `find`, `stat`, `test`, or another length, existence, or path probe before a reference read, and never split one reference across multiple reads. Make every gateway invocation its own later shell tool call. A host may bootstrap the initial complete `SKILL.md` load with exactly `wc -l <SKILL.md> && sed -n '1,<enough-lines>p' <SKILL.md>` against that same absolute file; this is the only combined read allowed. Never combine a reference read, gateway invocation, or any other commands with `&&`, `;`, a pipe, command substitution, or a multi-command shell string because those actions are not independently auditable.

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
python scripts/run.py gateway.py operations
python scripts/run.py gateway.py operation-schema object.create
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
| wait for one topic event | `wait-topic` | bounded subscription, optional JSON payload match, guaranteed unsubscribe |
| inspect project-changing operation support | `operations` / `operation-schema` | offline closed request schema and explicit executable boundary |

Each command prints one JSON document. Summarize its actual values in the user's language. Do not paste the whole JSON unless asked.

Exact reflection-call fast route: when the user explicitly asks to call `ak.wwise.waapi.getFunctions` or `ak.wwise.waapi.getTopics` with empty args and options, run exactly one matching `call` command from the table, replacing `<supported-version>` with the exact requested or connected Wwise version. Do not run `describe` or `capabilities` first, and do not read the query reference before or after the call. The reviewed route is already fixed by this Skill. If that one gateway invocation is rejected or fails, stop and report the result; never retry it with another command.

For capability discovery, start with `capabilities --all-versions --summary-only`, then add `--query`, `--category`, `--item-type`, `--family`, or `--route` and request only the needed rows. The list defaults to at most 50 compact rows; `--limit 0` is an explicit all-row opt-in, and `--detail` is only for nested interface, schema-summary, policy, or evidence auditing. When a URI is already known, use `describe <uri>` instead of listing the matrix, except for an explicit exact reflection call covered by the fast route above. A known row with `preferred_route: manifest_dispatch` may use `call`. For `transaction_operation`, obey the returned `transaction_operations`: the three Undo Group member URIs require `waapi.undoGroup`; all other such rows use `waapi.call`. For operations, use the compact `operations` inventory only for a genuinely broad inventory question; use `operation-schema <name>` directly for any named operation, and reserve `operations --detail` for an explicit full-catalog contract audit.

When the user explicitly asks for the five-version coverage numbers, exclusions, or what the program matrix proves, read `references/waapi-coverage.md` once and combine it with the current offline catalog. Do not claim that program-tested coverage is live-Wwise verification.

Broad `query-object` sources and every `--select` require `--take N` with `0 <= N <= 1000`; use `--all-results` only when the user explicitly asks for an unbounded result. The fixed `buses` command is bounded to 1000 rows and reports that bound plus whether truncation is possible. Never route `ak.wwise.core.object.get` through the generic `call` command: the gateway returns `QUERY_OBJECT_REQUIRED` so all object discovery stays inside `query-object`. Other fixed-command URIs return `FIXED_COMMAND_REQUIRED`, and topic URIs return `WAIT_TOPIC_REQUIRED`; use the command named by that boundary instead of retrying `call`.

When the requested answer is machine-readable and any successful gateway payload contains `agent_result`, compact-serialize exactly that object as the result body and stop. This rule applies to fixed reads as well as transactions. Do not reconstruct its fields from the prompt, `normalized`, summaries, or verification evidence; do not alter JSON escaping or add/remove keys; and do not run another command after receiving it. If the required envelope is `WAAPI_RESULT_JSON=<json>`, append the compact serialization of `agent_result` directly after the prefix. Failed, deferred, indeterminate, or boundary payloads intentionally have no successful `agent_result`; report their actual state instead of inventing one. For a normal natural-language answer, use the complete gateway evidence rather than only the compact projection.

## Routing

### Setup lane

Use setup when the task is about connection state, version detection, host/port issues, saved config, first-run onboarding, or “what Wwise instance is this talking to?”.

Examples:
- “Which Wwise version is open?”
- “What project is currently open?”
- “WAAPI isn’t connecting.”
- “What endpoint are you using?”

Read: `references/waapi-setup.md`

### Query lane

Use query for read-only inspection: selection, object lookup, hierarchy browsing, property reads, WAQL-shaped discovery, project facts, bounded topic waits, and other non-mutating inspection.

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

Use operate for project-changing work: create, move, copy, delete, property/reference edits, imports, soundbanks, switch assignments, design previews, or guarded fallbacks such as XML editing.

Examples:
- “Create a new Event under this Work Unit.”
- “Import these files.”
- “Generate or update this soundbank setup.”
- “Assign this object to the Switch Container.”

Choose the transaction phase before choosing a command. An existing transaction continuation takes precedence over the named-operation rule, but it requires the transaction id; an artifact hash alone is not a transaction lookup key. When the user confirms, checks, or continues an already previewed transaction and its transaction id is available from the message or conversation, read the operate reference and run `transaction-show <transaction-id> --summary-only` first. Do not call `operations`, `operation-schema`, or `preview` before that show call; the immutable preview already contains the closed request and schema. A status or check request stops after `transaction-show`. User intent authorizes every later action; the returned state only constrains which actions are legal and never authorizes `confirm`, `execute`, `verify`, or `reject` by itself.

For a new change request with no existing transaction, prefer a named semantic operation when one exists because it has richer identity resolution and readback. Otherwise use `describe <uri>`; if it reports `transaction_operation`, use the exact operation named in `transaction_operations`. The three Undo Group member URIs require `operation-schema waapi.undoGroup`; every other row uses `operation-schema waapi.call` with that exact manifest URI plus reflected `args` and `options`. Do not run `operations` first. Then use `preview`, wait for a later explicit confirmation, bind it with `confirm`, execute the immutable transaction once, and run `verify`. Generic verification proves the returned reflected result schema; do not describe it as an operation-specific Wwise state readback. Never invoke planner/builder classes, construct a raw mutation, or write code.

`verify` is the terminal authority for the selected contract: dedicated operations return their live readback, while generic `waapi.call` returns reflected result-schema evidence. After `verify` returns `verified` or another terminal verification state, stop the gateway sequence and report exactly that evidence. Do not add `query-object`, `call`, or another gateway command to double-check the same mutation.

In ordinary agent use, omit `--state-dir` and let the caller or broker inject the transaction store implicitly. Never run `env`, `printenv`, shell expansion, or another environment-inspection command to discover `WAAPI_SKILL_STATE_DIR`, and never guess or search for a state directory. Pass `--state-dir` only when the user or trusted caller explicitly supplied a trusted absolute path. If the gateway returns a structured state-directory error or boundary, report it and stop instead of probing the environment or filesystem.

Fast route from this entry file:

- Closed transaction operations are `waapi.call`, `waapi.undoGroup`, `object.create`, `object.delete`, `object.setName`, `object.setNotes`, `object.setProperty`, `object.setReference`, `audio.import`, `soundbank.setInclusions`, `switchContainer.addAssignment`, and `switchContainer.removeAssignment`. For a new request, read `references/waapi-operate.md` in its own tool call, then run the named `operation-schema` and transaction commands as separate tool calls. For an existing transaction continuation, read the same reference but skip `operation-schema` and `preview`; start with `transaction-show`.
- `waapi.call` is the packaged fallback for catalog rows routed to `transaction_operation` except the three Undo Group member URIs, which are executable only through the same-connection `waapi.undoGroup` operation. Neither operation accepts an invented URI or code. `isolated_transaction` requests may require an absolute `io_root`; custom CLI command hooks are always rejected. Read the operate reference before constructing either request.

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
- The generic `call` path accepts only catalog rows whose preferred route is `manifest_dispatch`. Fixed functions require their packaged command, reviewed topics require `wait-topic`, and each `transaction_operation` row requires immutable preview/confirmation through its declared closed operation: `waapi.undoGroup` for the three Undo members, `waapi.call` otherwise. `--dry-run`, `--allow-destructive`, and `WWISE_DESTRUCTIVE=1` do not bypass those route decisions.
- Arbitrary Lua, unsafe/private debug APIs, unrestricted UI command registration/execution, and model-supplied CLI custom command hooks remain blocked. UI command add-ons can launch external programs, while unrestricted built-in command IDs can bypass reviewed project-transition guards. Isolated transactions audit absolute inputs and confine every explicit write path below `io_root`; any implicit Wwise-managed write is disclosed as unproven, never misreported as confined.
- Do not search the repository to recover from a gateway error. A structured failure is the result unless the user explicitly asked to develop or debug this Skill itself.
- If a capability has no packaged executable path, return a clear `unsupported_by_skill_interface` boundary instead of synthesizing code.
- Do not treat XML editing as a normal first-line path. It is a guarded fallback inside the operate lane.
- Editing this Skill's implementation is allowed only when the user's task is Skill development, testing, or debugging—not as a way to complete an ordinary Wwise request.

## Detailed references

- `references/waapi-setup.md` — connection, version, config, status, and first-run behavior
- `references/waapi-query.md` — read-only inspection, selection/object lookup, bounded topic waits, and no-code failure rules
- `references/waapi-operate.md` — closed operation JSON, durable preview/confirm/execute/verify, retry rules, and explicit boundaries
- `references/waapi-coverage.md` — exact five-version counts, exclusions, route meanings, and program-test scope
