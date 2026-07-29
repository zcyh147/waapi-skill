# WAAPI operate lane

Read this file once with one complete standalone `cat`. The read is complete only when the unique terminal sentinel required by `SKILL.md` is the final visible line and the tool output contains no truncation or omission marker. Otherwise stop and report an incomplete host read; do not reread a range or invoke the Gateway.

## Core boundaries

- The only normal change path is the packaged transaction CLI through the absolute `scripts/run.py` derived from the injected `SKILL.md` locator.
- Do not import builders or planners from inline Python, write a helper, call `WaapiClient`, construct raw WAAPI mutations, edit Wwise XML, or bypass a dedicated operation with generic `call`. Do not write code to bypass an unsupported boundary. That boundary does not authorize code generation.
- Each reference read and Gateway invocation is one shell tool call. Never join commands with `&&`, `;`, a pipe, command substitution, or a multi-command shell string.
- Read every Gateway JSON completely before the next command. Never suppress or redirect it, choose a short output budget, or infer success from exit code `0`. Empty, truncated, non-JSON, or otherwise incomplete visible output is a hard stop for that turn.
- Except for the migration exception below, one complete terminal `verify` result ends the transaction. Do not append a query, filesystem inspection, or another proof.

## Choose the phase and first Gateway command

An existing transaction continuation always outranks operation selection.

### Existing transaction

A continuation requires the transaction id retained from the visible conversation or prior Gateway result; an artifact hash is not a lookup key. If the id is unavailable, say that the saved preview context is unavailable and offer a fresh preview. Do not ask a normal user for an internal id or inspect a state directory. Do not reread `SKILL.md` or this reference on a continuation turn when they are already visible.

The first Gateway command is:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py transaction-show <transaction-id> --summary-only
```

This is a mandatory safety gate. Do not call `operations`, `operation-schema`, or `preview` first. If its complete JSON is not visible, stop without a later transaction command, even with exit code `0` or a previously known id/hash.

### New transaction

Choose exactly one of these first-command branches:

| Request | First Gateway sequence |
|---|---|
| `object.create` or `object.set` | `operation-schema <name>` first. If the request describes dynamic properties/references by meaning, run one metadata discovery next; do not repeat the schema. |
| Any other metadata-bound operation with unknown property/reference tokens, including both import operations | one metadata discovery first, then its named `operation-schema` |
| A named operation with no metadata lookup | its named `operation-schema` directly |
| A known native URI without a named route | `describe <uri>` and obey only the returned `transaction_operations`, except for the reviewed fast routes below |

Use `operations` only for a broad inventory question, never as preparation for a named change. An implemented dedicated operation owns its URI; `waapi.call` is a hard-rejected bypass unless the catalog explicitly lists it as that URI's transaction operation. The three Undo Group member URIs use only `waapi.undoGroup`.

After the required discovery/schema sequence, construct only the closed request returned by the schema and preview it. There is deliberately no unconditional schema-to-preview shortcut: missing metadata, version, identity, file, or user input must be resolved by the branch that owns it.

## Choose by business outcome

Select the operation whose postcondition and verifier match the user's complete authorized outcome. A native API overlap or large batch does not override this rule. `operation.selection_guidance` and, for native URIs, `interface.selection_guidance` are authoritative.

A named root that already exists and receives any notes, property, reference, or list change locks the whole batch to `object.set`, even when the same request also adds a wholly new subtree below it. Its first Gateway command is `operation-schema object.set`.

| User outcome | Select | Do not substitute |
|---|---|---|
| Directly described media rows, one or many | `audio.import` | an Agent-generated TSV |
| Existing caller-owned import TSV or explicit Wwise table workflow | `audio.importTabDelimited` | direct import merely because the table is large |
| Wholly new object hierarchy whose requested root does not already exist | `object.create` | structure-only import |
| Change fields, references, or lists on existing roots; target multiple existing roots; or append directly to an existing descendant below the named request root that the user explicitly identifies as the direct insertion target—the request root itself does not count | `object.set` | `object.create` |
| One isolated rename, notes, property, or reference edit | `object.setName`, `object.setNotes`, `object.setProperty`, or `object.setReference` | broad `object.set` |
| Platform link, plug-in, RTPC curve, or Switch assignment | its dedicated operation | generic object mutation |
| Direct saved SoundBank inclusions | `soundbank.setInclusions` | Definition TSV |
| Existing caller-owned SoundBank Definition TSV | `soundbank.processDefinitionFiles` | reconstructed direct rows |
| Generate Bank artifacts | `soundbank.generate` | persistent inclusion editing |
| One Wwise Undo step containing heterogeneous allowlisted calls | `waapi.undoGroup` | wrapping work already owned by one batch operation |
| Known installed GUI command with no semantic operation | `ui.commands.execute` | a shortcut around a dedicated route |

Batch size alone never establishes file-workflow intent. If a table workflow is explicit but no caller-owned TSV exists, ask for it instead of creating one. Keep an import's requested Event or Switch side effect inside that same `audio.import` transaction. If saved inclusions and artifact generation are both requested, use two ordered transactions under the current policy.

Keep execution domains distinct:

- durable Authoring project edits use the matching `ak.wwise.core.*` route or semantic operation;
- live playback/Game Object/Bank/RTPC/Switch/State values use `ak.soundengine.*`;
- Authoring audition transport uses `ak.wwise.core.transport.*`;
- an explicitly requested menu/GUI action uses `ui.commands.execute`.

For example, `object.setRTPC` authors a curve while `ak.soundengine.setRTPCValue` changes a runtime value. Do not cross domains because names are similar.

### `object.create` versus `object.set`

- `object.set` is locked when the request changes fields/references on an existing root, targets several existing roots, or appends to an existing descendant container below the named request root that the user explicitly identifies as the direct insertion target; the named request root itself does not count. Each existing insertion target gets its own `objects[]` row; its `children` contain only genuinely new direct descendants.
- `object.create` owns a wholly new recursive root. It may also merge only descendants below exactly one unchanged same-name existing root, after all three `object.set` conditions above are absent. Keep that existing object as the request root, repeat its exact type/name, use its parent as `parent`, and use `on_name_conflict:"merge"`.
- When the request is relative to the current-version default container Work Unit, follow the selected operation's returned versioned target contract: an `object.create` same-name-root merge goes directly to its exact `query-object`, while `object.set` uses its returned target base and dynamic metadata scope. Do not insert `project-default-work-units`.
- Existing `objects[]` targets never imply a child-name merge. Follow the returned schema/selection guidance for `fail`, `merge`, and guarded replace.
- If a requested target is not a valid direct writable parent for that object type, do not silently retarget the mutation; report the structured suitability evidence and ask the user to confirm the intended writable child container before a new preview.

## Resolve properties and references from live metadata

Users speak naturally; never ask them for internal property/reference names. When an exact token is not already visible from live metadata:

1. Run one `metadata discover` with one repeated `--query '<ordinary phrase>'` per requested setting and `--limit 8`. Translate localized user wording into short English Wwise UI or technical behavior phrases for this search; do not copy CJK wording into the live lexical matcher. Keep independent enable switches and numeric values as separate queries.
2. Use exactly one scope: `--object-type` for a known new/imported type or several existing targets of one proven type, `--class-id` for a proven class id, or `--object` for one existing object.
3. For Sound SFX imports use `--object-type Sound`. For Actor Mixer roots use `ActorMixer` in `2021.1`–`2024.1` and reflected `PropertyContainer` in `2025.1`; the operation request token remains `ActorMixer`.
4. Copy only exact returned names and only settings the user requested, plus dependencies whose returned `required_values` prove an exact enabling value. Do not treat candidates/defaults as a preset.
5. Retry once only when `fallback_detail_scan.status` is `partial`, using broader related English technical phrases. A `complete` scan with no match is terminal for that phrase; do not run a second metadata discovery. If candidates remain ambiguous, ask one natural behavior question.

The operation preview performs final live typed validation and remains authoritative. Do not add a separate property-info check for a token already proved in the visible conversation, and never inspect metadata-cache files.

For import tables, discover only dynamic property/reference behavior. `Notes` and `Audio Source Notes` are fixed import columns owned by the import schema/parser, not Sound metadata queries. Useful search concepts include `looping`, `ignore parent playback limit`, `sound instance limit enabled`, `maximum sound instances`, and `output bus`; these are search phrases, never permission to guess the returned internal token.

### Compact import and value rules

- For an ordinary `audio.importTabDelimited` import, do not `cat` or otherwise read the caller's TSV. Pass its supplied absolute path unchanged to `preview`; that preview owns bounded TSV parsing and hashing, inline base64 and media validation, and exact-path conflict checks. A user request to view the file is a separate read-only task, never an import prerequisite.
- `SFX` is the built-in nonlocalized import token. Preserve it literally and do not query the Project language inventory for it; validate only explicit non-SFX languages.
- `arguments.import_operation` is the explicit batch-level mode: write `createNew`, `useExisting`, or `replaceExisting` when the user asks for that behavior; omission means `createNew`, and the field never belongs inside an `imports[]` row. Under `useExisting`, behavior is still resolved per row: an existing localized non-SFX target keeps only `audio_file`, `object_path`, `import_language`, and the live-preflighted `object_type`; omit notes, source notes, Originals subfolder, and Event. Existing SFX rows retain every user-supplied optional field, and missing targets retain creation fields.
- `originals_subfolder` is relative to Wwise's normal destination for that language. For SFX, `Foley/Footsteps` means `Originals/SFX/Foley/Footsteps`; never silently add or remove an `SFX/` prefix.
- Every requested import Event uses an absolute path below `\Events`, is absent before preview, and is unique across rows. Do not append an Action to an existing Event.
- Wwise `Pitch` values are cents. Convert requested semitones before preview (`1 semitone = 100 cents`); do not pass the semitone number as the property value.

## CLI versus connected Authoring

Only explicit WwiseConsole, CLI, command-line, or 命令行 wording selects an `ak.wwise.cli.*` route. A `.wproj` path, JSON `project` field, project-copy description, or output/cache path alone does not establish CLI intent.

Without explicit CLI wording, use the connected Authoring operations: `soundbank.generate`, `soundbank.convertExternalSources`, `soundbank.processDefinitionFiles`, and `audio.importTabDelimited`. When the earlier metadata-bound branch does not apply, their first Gateway command is the named `operation-schema`; otherwise complete that branch's one discovery first and then read the same schema. Do not probe `waapi.call`, `describe`, or a same-named CLI API first. The singular CLI `convertExternalSource`, CLI `generateSoundbank`, and CLI `tabDelimitedImport` are not their connected `ak.wwise.core.*` counterparts.

### Reviewed CLI fast routes

For these four exact CLI APIs in Wwise `2022.1`, use `operation-schema waapi.call` as the first Gateway command without `describe`/`capabilities`:

- `ak.wwise.cli.convertExternalSource`
- `ak.wwise.cli.generateSoundbank`
- `ak.wwise.cli.tabDelimitedImport`
- `ak.wwise.cli.migrate`

If the version was initially unknown, apply the rules below only when that schema result's `session_context` reports `2022.1`; on another version do not preview and use `describe <exact-uri>`. For any other already-known version, begin with `describe` and do not reuse 2022-only materialization rules. `operation-schema`/`describe` own the accepted/blocked fields, reflected types, version deltas, request envelope, and `io_root` policy. Never invent a hidden flag or default Boolean; include a true Boolean only for behavior explicitly requested by the user. `options` is `{}`.

Version-delta reminders that must agree with the returned schema:

| API | Field delta |
|---|---|
| `generateSoundbank` | `no-source-control`, `root-output-path`, and `use-user-overrides` appear in 2022.1; `license-file` appears in 2023.1; `no-wwise-dat` ends after 2023.1 |
| `tabDelimitedImport`, `migrate` | `no-source-control` appears in 2023.1 |
| `convertExternalSource` | `no-wwise-dat` ends after 2023.1 |

Compact 2022 materialization rules not yet represented structurally:

- `platform` is always an array. `bank`, `language`, and `import-definition-file` are a string for one value and an array for several. `project`, `io_root`, `cache`, `root-output-path`, the tab-import file/mode/language, and migrate project are scalar strings.
- A platform/value mapping (`source-by-platform`, `output`, `soundbank-path`) is a flat two-string pair for one platform and an array of pairs for several; never wrap one pair in an extra array.
- `convertExternalSource` accepts exactly one `source-file` string shared by platforms or one unique `source-by-platform` pair per platform. In 2022.1 an array processes only its first source and a repeated platform mapping processes only its last entry, so both shapes are rejected; multiple manifests for one platform require a caller-prepared union file or separate transactions. Bind each `output` pair to that platform's final directory. `io_root` is the deepest common absolute ancestor of those outputs and may not be only the filesystem root.
- `generateSoundbank` maps non-Init Banks, platform arrays, and explicit languages. Init is automatic. Explicit nonlocalized-only, cache-clear, or header requests map to their returned true flags; omit false/default flags. One `soundbank-path` is a flat pair; several use per-platform pairs. Use stated cache/root-output paths or default them below the requested output root as returned by the reviewed mapping. Derive `io_root` only from resolved write paths, never the project path, and reject a filesystem-root-only result. Its verifier is result-schema-only because WwiseConsole may already have torn down the project context.
- `tabDelimitedImport` uses the stated project, caller TSV, Wwise language, and explicit `createNew`/`useExisting`/`replaceExisting`; `io_root` is the case-owned project directory. Optional true flags are never inferred.
- `migrate` maps only the case-owned project and its containing `io_root`. `abort-on-load-issues` is included only when explicitly requested; warning summaries do not imply `verbose`. A normal control-server disconnect or continued reachability does not authorize replay; never replay execution, and defer success to the caller-owned reopened-project oracle.

### Reviewed Authoring audio-convert fast route

For exact `ak.wwise.core.audio.convert` in `2024.1`/`2025.1`, use `operation-schema waapi.call` first without `describe`/`capabilities`. Apply it only after the result proves one of those versions. Copy `direct_fast_route_contract.canonical_request_template` and replace only its listed values: non-empty ordered string arrays for exact object paths, platforms, and languages, plus the user's stated absolute `io_root` unchanged. An exact object path may be formed only from an explicitly supplied parent plus named direct children, in user order; never search recursively or add unnamed descendants. Explicit SFX targets use `languages:["SFX"]`; explicit localized languages replace it. Ask when a required input remains ambiguous.

## Closed request, preview, and policy

The successful named schema is the sole authority for request fields, identities, constraints, version support, and argument paths. When `request_envelope_policy.status` is `ready`, copy `request_envelope` exactly and replace only its empty `arguments` with fields allowed by that same schema. Unknown fields fail. Runtime-owned identity evidence, metadata records, dispatcher args/options, and raw `@Property` members are never model inputs to a dedicated operation.

For an unambiguous actual change use one standalone:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py preview --apply --request-json '<closed-request-json>'
```

For design/preview-only intent omit `--apply`; it never authorizes execution. In ordinary use omit `--state-dir`: the Gateway owns the external transaction store. Pass it only when a trusted caller explicitly supplied an absolute override, then reuse that path unchanged.

A rejected or incomplete preview is a hard same-turn boundary. Do not repair JSON, change an operation, or retry preview in that turn. A changed target/value requires a new preview.

Filesystem proofs are local to the Gateway host. File-backed imports, SoundBank I/O, Lua, file-bearing UI commands, recursive object imports, and isolated `waapi.call` require a loopback WAAPI endpoint as reported by their schema/boundary. On `LOCAL_WAAPI_HOST_REQUIRED`, report and stop; never treat a local file proof as evidence about a remote host.

Policy behavior:

| Policy | Behavior |
|---|---|
| `read_only` | block `preview --apply`; a design-only preview remains possible |
| `ask_before_changes` | preview returns `awaiting_confirmation`; present the concrete expected result and decision-relevant risk/cleanup/verifier limit, say nothing changed, ask whether to proceed, and end the turn |
| `allow_changes` | preview may return `policy_authorized`; after preview and before execution, tell the user the concrete impending change and that current mode permits it, then continue in the same turn |

Dangerous debug host controls remain confirmation-only even under `allow_changes`; obey their schema acknowledgement and never infer ordinary "yes" as the required value.

## Continue only from Gateway-owned commands

The user's current intent authorizes an action; transaction state only constrains which actions are legal. After `transaction-show`, use `next_command.shell_command` as the sole executable representation for every later phase. Its `copy_instruction` names the action. Copy the entire string verbatim as one shell tool call, including `python`, the absolute launcher path, `gateway.py`, id, and token. Do not render diagnostic `full_argv`, re-quote, shorten, normalize, or rebuild any path/token segment.

Treat every phase as separately gated and inspect its complete JSON before the next:

- a status/check request stops after `transaction-show`;
- an explicit rejection may run only the returned reject command, then stops;
- a clear confirmation may continue from `awaiting_confirmation` through the returned confirm, execute, and verify commands;
- `confirmed` continues through returned execute then verify;
- `policy_authorized` continues through returned execute then verify after its notice;
- `executed_unverified` runs the returned verify only;
- a verify-only request never executes.

The show result's confirmation token binds the stored id, full artifact hash, state, and event chain. Never reconstruct or substitute it, use the artifact hash as a token, or run `confirm --help`. If confirm output is incomplete, stop before execute/verify. Risks already disclosed by the immutable preview are decision information, not a second Agent veto after the user clearly confirms that same request. A changed project/path/scope requires a fresh preview.

For an original ordered multi-transaction request, apply the current policy to each item independently after the prior item reaches terminal verification. Never infer, add, combine, or reorder an item.

## Terminal states and reporting

- `verified`: report the completed business outcome and actual readback, then
  stop without an extra query.
- `result_schema_checked`: report explicitly that only the reflected result
  shape was proved; do not claim business-state verification.
- `verification_deferred`: a later user-requested verify is safe; never
  re-execute.
- `verification_failed`, `repreview_required`, `execution_cancelled`, or a
  structured boundary: report the actual failure/next decision without claiming
  completion or retrying mutation.
- `execution_succeeded_persistence_failed`: WAAPI reported execution but the
  journal failed; preserve the uncertainty and never replay automatically.
- `indeterminate`: execution may have reached Wwise. Stop immediately after the
  complete execute JSON. Do not verify, retry, call another Gateway route,
  inspect files/evidence, or perform any follow-up tool action. A later
  diagnosis needs a new user request and a packaged read-only route.

`ak.wwise.cli.migrate` is the narrow exception to normal verify flow. Its one
complete `execute` JSON is the terminal Skill boundary even when state says
`executed_unverified`. Run no more Agent tools: do not reopen/query the project
or inspect `.wproj`, `.wwu`, broker/lifecycle/log/oracle artifacts. Only the
caller-owned harness outside the Skill sequence may close Wwise, reopen the
migrated project, and establish final business proof.

Managed openers may return a pending or unknown cleanup companion (for example
Bank load, Game Object registration, Profiler capture, meter/remote/transport,
or UI command registration). Do not hide that obligation or uncertainty.
Explain the business cleanup naturally and use only a later packaged
transaction when the user authorizes it. Never synthesize cleanup code.
Work Unit load/unload is an available reversal, not automatic cleanup; Undo
Group cleanup remains inside its same-connection composite.

For ordinary prose, hide internal ids, hashes, tokens, raw commands, and state
labels unless the user requests diagnostics. For an exact machine-readable
answer, serialize the successful Gateway `agent_result` verbatim; do not rebuild
it from summaries. Failed/deferred/indeterminate payloads have no successful
projection and must not be fabricated.

<!-- WAAPI_OPERATE_REFERENCE_END -->
