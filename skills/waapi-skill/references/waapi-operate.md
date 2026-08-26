# WAAPI operate lane

Read this file once with one complete standalone `cat`. It is complete only when the unique terminal sentinel required by `SKILL.md` is the final visible line and no truncation or omission marker appears. Otherwise report an incomplete host read; do not reread a range or invoke the Gateway.

## Core boundaries

- The only normal change path is the packaged transaction CLI through absolute `scripts/run.py` from the injected `SKILL.md` locator.
- Do not import builders or planners from inline Python, write a helper, call `WaapiClient`, construct raw WAAPI mutations, edit Wwise XML, or bypass a dedicated operation with generic `call`. Do not write code to bypass an unsupported boundary. That boundary does not authorize code generation.
- POSIX: single-quote Wwise path values to preserve backslashes; one read/Gateway call per shell call, never joined.
- Read each Gateway JSON before continuing; exit `0` proves nothing. Stop on empty, non-JSON, or host-truncated output. A typed-container response is complete only when final `WAAPI_TYPED_CONTAINER_RESPONSE_END` says `complete:true` and `truncated:false`; then continue from that response.
- A rejected or nonzero Gateway invocation is also a hard stop for that turn. Do not advance to the next schema, preview, or transaction phase and do not repair or retry the command. The sole metadata-discovery retry below starts only from a successful complete JSON result whose `fallback_detail_scan.status` is `partial`.
- Except for the migration below, one complete terminal `verify` result ends the transaction; append no query, filesystem inspection, or other proof.

## Choose the phase and first Gateway command

An existing transaction continuation always outranks operation selection.

### Existing transaction

Use the transaction id from conversation or a prior Gateway result; an artifact hash is not a lookup key. If absent, report unavailable preview context and offer a fresh preview; do not ask for an internal id, inspect state, or reread visible Skill files. The visible Preview's `next_command` is authoritative: execute its selected field verbatim. The template below never authorizes reconstruction with another runner path.

The first Gateway command is:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py transaction-show <transaction-id> --summary-only
```

This is a mandatory safety gate. Do not call `operations`, `operation-schema`, or `request-schema` first. If its complete JSON is not visible, stop without a later transaction command, even with exit code `0` or a previously known id/hash.

### New transaction

When this change uses a subset that the user selected from a previous multi-result ordinary, structured, or advanced object query, finish the query lane's selected-subset identity gate first: exact-ID read back every selected GUID and require its unaliased name, type, and path to match the candidate that the user chose. A failed, missing, changed, or ambiguous row stops the change. These bounded read-only checks precede the transaction contract; they do not replace its schema or metadata steps.

After a selected-subset gate, choose one first transaction-contract branch:

| Request | First transaction-contract sequence |
|---|---|
| `object.create` | Preflight: explicit pre-Preview same-name-root type/path only; not parent/sibling or later verification. Then `operation-schema`; metadata. |
| `object.set` | its named `operation-schema`, then its `business_declaration` start. Bind exact owners, parents, and references; discover dynamic fields through returned Draft commands; declare only high-level target, subtree, media, and object-list outcomes. |
| `audio.import` | `operation-schema audio.import`, then its `business_declaration` start. Bind exact live objects and any custom fields through the returned business Draft commands; declare only high-level outcomes. |
| copy/delete/move/rename/notes | named `operation-schema`, then returned `business_declaration`; bind each role and submit one complete high-level change. |
| Any other operation with an explicitly requested unknown dynamic property/reference token | one metadata discovery first, then its named `operation-schema` |
| A named operation using only closed schema fields and side effects | its named `operation-schema` directly |
| A known native URI without a named route | `request-schema <uri>` and follow its sole typed continuation |

For business operations, the business Adapter owns object paths, native types, metadata scopes, object-list rows, Event/Switch construction, order and batching. Complete paths use `by_path_segments`; GUIDs use `by_id`; follow only the binding variants disclosed for the selected operation. SoundBank planning exposes `by_exact_type_name` for an exact unscoped name paired with its exact Wwise type; that one bounded Gateway call resolves at most two rows and binds only one exact name/type/path match. Returned Field Handles are copied exactly; `draft-check` revalidates them. Returned Object Handles are copied exactly and revalidated too; never infer or type a property/reference token. Table imports start `operation-schema audio.importTabDelimited`; dynamic columns stay metadata-first.

Follow the schema's sole `input_mode`. No schema-to-preview shortcut; never infer a token. For `inline_typed`, run its continuation. For `composer`, run only its returned start and action argv. For `business_declaration`, run `draft-start` from the returned start, then copy each `fixed_argv_prefix_copy`, append one complete disclosed group, and read its response. Copy handles into the same named role; submit only disclosed high-level fields. The Gateway derives Wwise paths, types, metadata scopes, native fields, object-list rows, order, batching, and Preview change intent. For audio, new/existing targets derive create/reimport; configure `--mode replace` only for explicit replacement. Supply stable facts such as `volume_db=-4`; references use handles and `sound-sfx` derives `SFX`. Put every known audio field in its first declaration. Corrections reuse the draft. For audio, configure a default only when the user requested it for every target kind; otherwise repeat it where applicable. Continue to Preview/refusal in the same turn. Exact reflected URIs use `request-schema`.

Copy argv, preserving `--expected-revision` and `--apply`. Only when the returned input mode is `composer`, fill six-fact batches then a last partial batch and add required branch facts after `choose`. Business declarations instead submit one complete returned high-level command at a time.

For a Composer lane, `construction_state.complete:false` and compact action receipts are complete JSON. Follow `next_command_decision`; only an exact `business_value_pointer` authorizes it. A business Draft instead follows its returned required phase and completion candidate. Both lanes finish through the returned check/Preview continuation, never `draft-apply --action check`.

Public mutation identities are closed to `id`, `path`, `exact-type-name`, `direct-child`, and `scoped-name` outside `business_declaration`. Use a schema-fitting selector directly in preview; do not query only to translate it or use raw WAQL. After exact relationship/path read returns canonical `id`/`name`/`type`/`path`, reuse its GUID as an `id` selector for later object/target; never switch to path/name or retype its Wwise path. Gateway revalidates it. When the user already supplied a complete Wwise path, keep it as one `path` selector; do not decompose it into `scoped-name` plus a parent path.

For an exact SoundBank name that is intended to be globally unique by type, use
`{"kind":"exact-type-name","type":"SoundBank","name":"<exact name>"}`. For an
exact existing Event path whose requested target is its one direct Action, use
`{"kind":"direct-child","parent":{"kind":"path","value":"<absolute Event path>"},"type":"Action"}`.
The Gateway owns quoting, the two-row ambiguity ceiling, exact type validation,
and the applicable parent or name checks.

If the target can be described only by a complex filter, first follow the query
lane's offline `query-schema` plus its returned typed structured-query flow. Proceed
to a mutation only when that read returns exactly one verified GUID, then use
`{"kind":"id","value":"<returned GUID>"}`. Zero, multiple, truncated, or
otherwise incomplete query results do not identify a mutation target.

## Choose by business outcome

Select the operation whose postcondition and verifier match the user's complete authorized outcome. A native API overlap or large batch does not override this rule. `operation.selection_guidance` and `interface.selection_guidance` govern. **Media gate:** a request that names Sound/SFX nodes but supplies no media artifact or import intent is a pure object hierarchy and selects `object.create`. When media import is primary, use one `audio.import` for requests that replace media on existing Sounds or create a Sound in the same batch; `object.set` is never a preliminary schema for that outcome. From 2023.1, `object.set` may carry media only when import is subordinate to a broader atomic mutation of existing targets. New target-container hierarchy and same-row Event/Switch outcomes stay in the selected business transaction; never probe `object.create` or a separate assignment first.

Existing-root status alone does not select `object.set`. One object's single rename, notes, scalar-property, or reference edit uses `object.setName`, `object.setNotes`, `object.setProperty`, or `object.setReference`. Broad `object.set` is only for one larger atomic outcome: several fields/properties/references on one root, an ordinary closed object-list change, multiple roots, a root edit plus a new subtree, or insertion into a named existing descendant. Plug-in, RTPC, and platform-link changes keep their dedicated operations. After any required selected-subset identity gate, that batch starts with `operation-schema object.set`.

| User outcome | Select | Do not substitute |
|---|---|---|
| Directly described media rows whose primary outcome is import, one or many | `audio.import` | `object.create`, a separate same-row Event/Switch assignment, or an Agent-generated TSV |
| Existing caller-owned import TSV or explicit Wwise table workflow | `audio.importTabDelimited` | direct import merely because the table is large |
| Wholly new structure-only object hierarchy whose requested root does not already exist and has no media or import-manifest intent | `object.create` | `audio.import` |
| One existing object's single rename, notes, scalar-property, or reference edit | `object.setName`, `object.setNotes`, `object.setProperty`, or `object.setReference` | broad `object.set` |
| Larger atomic existing-target batch: several fields/properties/references on one root; an ordinary closed object-list change; multiple roots; a root edit plus a new subtree; or insertion into a named existing descendant (not the request root) | `object.set` | `object.create` or any dedicated operation |
| Platform link, plug-in, or RTPC curve | its dedicated operation | generic object mutation |
| Add an independent Switch assignment between existing objects | `switchContainer.addAssignment` | an invented alias, generic object mutation, or a same-row import side effect |
| Remove an independent Switch assignment between existing objects | `switchContainer.removeAssignment` | an invented alias, generic object mutation, or a same-row import side effect |
| Direct saved SoundBank inclusions | `soundbank.setInclusions` | Definition TSV |
| Existing caller-owned SoundBank Definition TSV | `soundbank.processDefinitionFiles` | reconstructed direct rows |
| Generate Bank artifacts | `soundbank.generate` | persistent inclusion editing |
| One Wwise Undo step containing heterogeneous allowlisted calls | `waapi.undoGroup` | wrapping work already owned by one batch operation |
| Known installed GUI command with no semantic operation | `ui.commands.execute` | a shortcut around a dedicated route |

When the user gives one Bank's complete desired final inclusion set, use one `soundbank.setInclusions` `replace` transaction: omitted existing rows such as Debug rows are removed without being named individually, and every other Bank remains outside that transaction. Do not split that final-state request into `add` and `remove` transactions.

When saved inclusions precede generation, the verified Bank is the input; generation repeats only Bank/artifact expectation and preserves platforms/languages. Its `io_root` is the supplied trusted absolute ancestor of project, cache, and every platform Bank/media destination—not merely an output folder. Reuse it unchanged or ask for one.

Batch size never establishes file-workflow intent. If a table workflow is explicit but no caller-owned TSV exists, ask for it instead of creating one. Keep an import's requested Event or Switch side effect inside that same `audio.import` transaction. If saved inclusions and artifact generation are both requested, use two ordered transactions under the current policy.

Keep execution domains distinct:

- durable Authoring project edits use the matching `ak.wwise.core.*` route or semantic operation;
- live playback/Game Object/Bank/RTPC/Switch/State values use `ak.soundengine.*`;
- Authoring audition transport uses `ak.wwise.core.transport.*`;
- an explicitly requested menu/GUI action uses `ui.commands.execute`.

For example, `object.setRTPC` authors a curve while `ak.soundengine.setRTPCValue` changes a runtime value. Do not cross domains because names are similar.

### `object.create` versus `object.set`

- `object.set` covers several fields/properties/references on one root, an ordinary closed object-list change, multiple roots, a root plus descendants, or insertion into a named descendant. Single-edit, plug-in, RTPC, and platform-link operations take precedence. An insertion target is not the request root; give each one an `objects[]` row containing only genuinely new direct descendants.
- `object.create` owns a wholly new recursive root, or—only when those `object.set` conditions are absent—descendants below one unchanged same-name root. Repeat that root's exact type/name, use its parent, and set `on_name_conflict:"merge"`.
- If exact type is unproven, first exact-query the unchanged root and require one type/name/path match. Then open `operation-schema object.create` and follow its sole continuation directly into the Draft; do not query the parent already determined by that verified path.
- For the current-version default container Work Unit, use that preflight query for an `object.create` same-name-root merge; `object.set` instead binds the exact target and uses returned field/type discovery plus business-Draft validation. Do not insert `project-default-work-units`.
- Existing `objects[]` never implies child-name merge; obey returned `fail`, `merge`, or guarded-replace guidance.
- If not a valid direct writable parent, do not silently retarget the mutation; ask the user to confirm the intended writable child container.

## Resolve properties and references from live metadata

Users speak naturally; never ask them for internal property/reference names. When an exact token is not already visible from live metadata:

For `object.setProperty`, `object.setReference`, and `object.setLinked`, read the schema, start, bind the target, then run returned `draft-discover-fields` with a short English meaning and an explicit platform only when requested or required. Copy one handle; never a token, scope, or type. No match stops; ambiguity needs one behavior question.

For `object.create`, `object.set`, and direct `audio.import`, read the named schema, start the business Draft, bind the exact object/type scope, then use only its returned field discovery or binding command for requested dynamic properties and references. The returned type, restrictions, and opaque handle are the only value authority; `draft-check` revalidates scope, token, dependencies, and value.

Prompt/schema text, cached schemas, and Wwise knowledge are never exact live metadata evidence. When a remaining Composer lane's returned start preconditions contain `metadata_gate`, complete that exact successful discovery before `draft-start`. For every `business_declaration` lane, start the Draft first and use only its returned live binding or discovery command.

1. Bind the exact existing owner or the disclosed new-object type first; this fixes the metadata scope inside the Draft.
2. Run the returned discovery once with short English Wwise UI/technical meanings for every requested dynamic field. Search distinct meanings separately; do not turn localized prose into guessed Wwise tokens.
3. Copy one returned opaque handle per requested field. A complete no-match stops; ambiguity requires one natural behavior question.
4. Submit only business values against those handles. Gateway validates restrictions and activates proven dependencies; do not add unrequested fields or treat candidates/defaults as a preset.
5. Let `draft-check` perform exact live revalidation. Do not run a second discovery merely to obtain a token or reconstruct an object type.

Preview remains authoritative; never inspect metadata-cache files.

For business declarations, bind only user-requested custom properties/references; common outcomes such as volume, infinite looping, output bus, maximum instances, parent instance-limit override, notes, Event, Dialogue Event, and Switch value use stable business fields. For table imports, discover only dynamic `Property[...]`, `Reference[...]`, or `@...` columns.

For user Lua files use `lua.executeCoreFile` in Authoring, or `lua.executeCliFile` only for explicit CLI; there is no `lua.executeFile` operation.

### Compact import and value rules

- For an ordinary `audio.importTabDelimited` import, do not `cat` or otherwise read the caller's TSV. Pass its supplied absolute path unchanged through the typed continuation returned by `operation-schema`; the resulting Preview owns bounded TSV parsing and hashing, inline base64 and media validation, and exact-path conflict checks. A user request to view the file is a separate read-only task, never an import prerequisite.
- `SFX` is the built-in nonlocalized import token. Preserve it literally and do not query the Project language inventory for it; validate only explicit non-SFX languages.
- Batch `mode` is `create`, `reimport`, or `replace`; omit source-control settings unless the user explicitly requests them. The Adapter maps mode and version-specific native fields.
- Bind the exact existing parent/target once. For a new object, declare `parent_handle`, child `name`, and one disclosed semantic `kind`; for an existing object, declare its bound object handle. The Adapter constructs the complete path and exact native type.
- When one request includes a new container hierarchy, declare each requested container once as a structure-only descendant. Later declarations may use its returned planned handle as parent. Keep Sound-only media/language/field facts on the Sound declaration.
- Use `originals_subfolder` only when the user explicitly supplies its exact relative destination; otherwise omit it—never infer one from a source directory, media category, object path, or example. It is relative to Wwise's normal destination for that language; preserve an explicit value and never silently add or remove an `SFX/` prefix.
- `audio_file`: supplied absolute path only; append each named file to the exact supplied directory; no relative/traversal; never workspace-relative or `..` traversal.
- Every requested import Event belongs in the matching declaration: bind its exact parent, then provide Event name and business Action. The Adapter constructs the Event/Action path and keeps it in that same Preview.
- Wwise `Pitch` values are cents. Convert requested semitones before preview (`1 semitone = 100 cents`); do not pass the semitone number as the property value.

## CLI versus connected Authoring

Only explicit WwiseConsole, CLI, command-line, or 命令行 wording selects an `ak.wwise.cli.*` route. A `.wproj` path, JSON `project` field, project-copy description, or output/cache path alone does not establish CLI intent.

Without explicit CLI wording, use the connected Authoring operations: `soundbank.generate`, `soundbank.convertExternalSources`, `soundbank.processDefinitionFiles`, and `audio.importTabDelimited`. When the earlier metadata-bound branch does not apply, their first Gateway command is the named `operation-schema`; otherwise complete that branch's one discovery first and then read the same schema. Do not probe a same-named CLI API first. The singular CLI `convertExternalSource`, CLI `generateSoundbank`, and CLI `tabDelimitedImport` are not their connected `ak.wwise.core.*` counterparts.

### Reviewed CLI typed routes

For these four exact CLI APIs, use `request-schema <exact-uri>` and follow its sole typed continuation:

- `ak.wwise.cli.convertExternalSource`
- `ak.wwise.cli.generateSoundbank`
- `ak.wwise.cli.tabDelimitedImport`
- `ak.wwise.cli.migrate`

Apply the 2022-specific reminders below only when the configured schema version is `2022.1`; never reuse them for another lane. `request-schema` owns accepted and blocked fields, reflected types, version deltas, typed handles, and `io_root` policy. Never invent a hidden flag or default Boolean; include a true Boolean only for behavior explicitly requested by the user.

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

### Authoring audio conversion

For exact `ak.wwise.core.audio.convert` in `2024.1`/`2025.1`, run `request-schema ak.wwise.core.audio.convert` and follow its typed continuation. Append non-empty ordered object identities, platforms, and languages through the returned handles, and pass the user's exact absolute `io_root`. Explicit SFX targets use `SFX`; explicit localized languages replace it. Ask when a required input remains ambiguous.

## Closed input, preview, and policy

Unknown fields fail. Use only the returned continuation; there is no caller-authored request document. Never ask for confirmation while typed composition or Preview creation is still incomplete. Under `ask_before_changes`, `--apply` previews without execution; design work omits it. The Gateway owns the external runtime state root: omit `--state-dir` unless a trusted caller supplied an absolute override.

A rejected or incomplete preview is a hard same-turn boundary. Do not repair JSON, change an operation, or retry preview in that turn. A changed target/value requires a new preview.

Filesystem proofs are local to the Gateway host. File-backed imports, SoundBank I/O, Lua, file-bearing UI commands, recursive object imports, and isolated exact-URI typed routes require a loopback WAAPI endpoint as reported by their schema/boundary. On `LOCAL_WAAPI_HOST_REQUIRED`, report and stop; never treat a local file proof as evidence about a remote host.

Policy behavior:

| Policy | Behavior |
|---|---|
| `read_only` | block executable preview; a design-only preview remains possible |
| `ask_before_changes` | preview returns `awaiting_confirmation`; present the concrete expected result and decision-relevant risk/cleanup/verifier limit, say nothing changed, ask whether to proceed, and end the turn |
| `allow_changes` | preview may return `policy_authorized`; after preview and before execution, tell the user the concrete impending change and that current mode permits it, then continue in the same turn |

Dangerous debug host controls take no business facts: follow their zero-value typed continuation. The Gateway owns the fixed acknowledgement internally, and the resulting Preview remains confirmation-only even under `allow_changes`.
Normal prose covers only objects, changes, results, risks, and whether anything changed. Hide API/operation names, Draft/transaction internals, ids, hashes, tokens, states, and commands. Keep exact `agent_result` machine-readable.

## Continue only from Gateway-owned commands

User intent authorizes; transaction state only constrains legality. For every later phase, execute only the field named by `next_command.copy_instruction.source_field`, copying the complete string verbatim once. Windows normally selects `model_command`; encoded `shell_command` is audit/fallback unless explicitly selected. Do not render diagnostic `full_argv` or rebuild any segment. Truncated/incomplete instructions stop without inferred fallback.

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
Each later intended change still creates its own executable preview; completing one does not turn the next one into a design-only preview.

## Terminal states and reporting

- `verified`: report the completed business outcome and actual readback, then stop without an extra query.
- `result_schema_checked`: report explicitly that only the reflected result shape was proved; do not claim business-state verification.
- `verification_deferred`: a later user-requested verify is safe; never re-execute.
- `verification_failed`, `repreview_required`, `execution_cancelled`, or a structured boundary: report the actual failure/next decision without claiming completion or retrying mutation.
- `execution_succeeded_persistence_failed`: WAAPI reported execution but the journal failed; preserve the uncertainty and never replay automatically.
- `indeterminate`: execution may have reached Wwise. Do not verify, retry, call another Gateway route, or use another tool. A later diagnosis needs a new user request and a packaged read-only route.

`ak.wwise.cli.migrate` ends at complete `execute`, even when `executed_unverified`; run no later Agent tools/reads. Only the caller-owned harness outside the Skill sequence may reopen and prove it.

Managed openers may leave cleanup uncertain. Report it and use only a later authorized packaged transaction; never synthesize code. Work Unit reversal and same-connection Undo cleanup stay explicit.

For ordinary prose, hide internal ids, hashes, tokens, raw commands, and state labels unless the user requests diagnostics. For an exact machine-readable answer, serialize the successful Gateway `agent_result` verbatim; do not rebuild it from summaries. Failed/deferred/indeterminate payloads have no successful projection and must not be fabricated.
<!-- WAAPI_OPERATE_REFERENCE_END -->
