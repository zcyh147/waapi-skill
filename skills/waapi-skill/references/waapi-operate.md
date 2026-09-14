# WAAPI operate lane

Read this reference using the loading rules in `SKILL.md`. It is complete only when the unique terminal sentinel is final and no truncation or omission marker appears; otherwise do not reread a range or invoke the Gateway.

## Core boundaries

- The only normal change path is the packaged transaction CLI: `scripts/run.py gateway.py`. Do not import builders or planners from inline Python, call `WaapiClient`, or use raw WAAPI/XML/generic call. Do not write code to bypass an unsupported boundary. That boundary does not authorize code generation.
- POSIX: single-quote Wwise path values to preserve backslashes. One read/Gateway invocation per shell call.
- Read complete JSON; exit 0 proves nothing. `WAAPI_TYPED_CONTAINER_RESPONSE_END` must say complete/not truncated; then continue from that response.
- A rejected or nonzero Gateway invocation is also a hard stop. Only a successful result whose `fallback_detail_scan.status` is `partial` permits the one metadata retry below.
- The one complete terminal `verify` result ends the transaction; no extra proof query/filesystem call.

## Choose the phase and first Gateway command

An existing transaction continuation always outranks operation selection.

### Existing transaction

Use its transaction id; an artifact hash is not a lookup key. The visible Preview's `next_command` is authoritative and any other field never authorizes reconstruction. Run:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py transaction-show <transaction-id> --summary-only
```

Do not call `operations`, `operation-schema`, or `request-schema` first. Without complete JSON, stop.

### New transaction

For a prior-query subset, finish the selected-subset identity gate first: exact-ID read back every selected GUID and match name/type/path. These bounded read-only checks precede the transaction contract and never replace schema/metadata.

A prior exact diagnostic identity is not a selected subset: reuse its GUID; do not query it again. Gateway binding revalidates it.

A new natural-language change starts with one compact `operations` lookup; only its returned route selects the first transaction contract. An exact user operation/URI skips it.

| Request | First transaction-contract sequence |
|---|---|
| `object.create` | Preflight: explicit pre-Preview same-name-root type/path only; not parent/sibling or later verification. Then `operation-schema`, business Draft, returned binding/discovery. |
| `object.set` | Named schema and `business_declaration`; bind roles, discover dynamic fields through returned Draft commands, and submit only disclosed high-level fields. |
| `audio.import` | `operation-schema audio.import`, then returned `business_declaration`; bind live objects/custom fields and submit one complete import outcome. |
| copy/delete/move/rename/notes | Named schema, returned business Draft, role bindings, one complete change. |
| Any other operation with a requested dynamic property/reference | its schema, then the returned discovery sequence; Business Drafts own field discovery |
| A named operation using only closed schema fields and side effects | its named `operation-schema` directly |
| An exact user-supplied native URI without a named route | `request-schema <uri>` and its sole continuation; never infer a URI from natural-language intent |

Follow the schema's sole `input_mode`. No schema-to-preview shortcut. The business Adapter owns object paths, native types, metadata scopes, enums, order, batching, and Preview change intent. Complete paths use `by_path_segments`; GUIDs use `by_id`; for an exact reflected URI with a complete caller path, keep it as one `path` selector.

For `composer`, run only its returned start and action argv. For `business_declaration`, run `draft-start` when returned. Bind exact owners, parents, and references. Supply stable facts such as `volume_db=-4`; Gateway owns native construction. Configure defaults only when requested.

Table imports start `operation-schema audio.importTabDelimited`; dynamic columns stay metadata-first. Continue preserving `--expected-revision` and `--apply` until Preview/refusal. Returned Field Handles are copied exactly; never infer or type a property/reference token. `draft-check` revalidates them.

`construction_state.complete:false` and compact action receipts are complete JSON. Follow `next_command_decision`; only an exact `business_value_pointer` authorizes it. A business Draft instead follows its returned required phase and completion candidate. Copy handles into the same named role. Corrections reuse the draft; never `draft-apply --action check`.

Public mutation identities are closed to `id`, `path`, `exact-type-name`, `direct-child`, and `scoped-name`. After an exact relationship/path read returns canonical `id`/`name`/`type`/`path`, reuse its GUID as an `id` selector for a later object/target; never switch to path/name or retype its Wwise path. Gateway revalidates it. Use returned version-stable `business_kind`; stated ambiguity stops. Zero/multiple/truncated results do not identify a target. Raw WAQL never becomes mutation identity.

## Choose by business outcome

Select the operation whose postcondition and verifier match the request; `operation.selection_guidance` and `interface.selection_guidance` govern. **Media gate:** a request that names Sound/SFX nodes but supplies no media artifact or import intent is a pure object hierarchy and selects `object.create`.

An exact CamelCase Wwise Authoring command ID such as `SaveProject` is not a native URI. It directly selects `operation-schema ui.commands.execute`; screen capture directly selects `operation-schema ui.captureScreen`. Both skip `operations`, and command-ID routing overrides generic connected-project save intent. If a larger request already required the catalog, `operations.routing_precedence` preserves the same choice.

Ordinary save wording such as `save the current project` or `保存当前工程` selects `request-schema ak.wwise.core.project.save`; never infer or translate that wording into `SaveProject`. Only the user's exact literal CamelCase command ID selects the UI-command route.

When media import is primary, use one `audio.import` to replace media on existing Sounds or create a Sound in the same batch; `object.set` is never a preliminary schema for that outcome. New target-container hierarchy and same-row Event/Switch outcomes remain in that transaction; never probe `object.create` or a separate assignment first. From 2023.1, `object.set` may carry media only when import is subordinate to broader existing-target work.

Existing-root status alone does not select `object.set`. One existing object's single rename, notes, scalar-property, or reference edit uses its dedicated operation; these fixed single-edit routes skip `operations`. Broad `object.set` is only for one larger atomic outcome: several fields/properties/references on one root, an ordinary closed object-list change, multiple roots, a root edit plus a new subtree, or insertion into a named existing descendant. After any required selected-subset identity gate, that batch starts with `operation-schema object.set`. For a batch, bind every target first. Use disclosed fixed fields directly; discover other fields for each exact target and copy the selected handles into `declare_existing_batch`. Plug-in, RTPC, and platform-link changes keep their dedicated operations. An insertion target is not the request root; give each one an `objects[]` row containing only genuinely new direct descendants. Single-edit, plug-in, RTPC, and platform-link operations take precedence; `object.create` owns new structure when those `object.set` conditions are absent.

If root type is unproven, first exact-query the unchanged root. Then open `operation-schema object.create` and follow its sole continuation directly into the Draft; do not query the parent already determined by that verified path. When that exact preflight proves an existing same-name root and the user requests merge, bind its direct parent, declare the root name once, and configure merge; never bind the existing root as its own new parent. For the default container Work Unit, use that preflight query for an `object.create`. `object.set` instead binds the exact target and uses returned field/type discovery plus business-Draft validation. Do not insert `project-default-work-units`. If a supplied parent is not a valid direct writable parent, do not silently retarget the mutation; ask the user to confirm the intended writable child container.

| User outcome | Select | Do not substitute |
|---|---|---|
| Directly described media rows whose primary outcome is import, one or many | `audio.import` | `object.create`, separate same-row assignment, or Agent-generated TSV |
| Existing caller-owned import TSV or explicit Wwise table workflow | `audio.importTabDelimited` | direct import because the table is large |
| Wholly new structure-only object hierarchy whose requested root does not already exist and has no media or import-manifest intent | `object.create` | `audio.import` |
| One existing object's single rename, notes, scalar-property, or reference edit | `object.setName`, `object.setNotes`, `object.setProperty`, or `object.setReference` | broad `object.set` |
| Larger atomic existing-target batch: several fields/properties/references on one root; an ordinary closed object-list change; multiple roots; a root edit plus a new subtree; or insertion into a named existing descendant | `object.set` | `object.create` or a dedicated operation |
| Platform link, plug-in, or RTPC curve | dedicated operation | generic mutation |
| Add/remove an independent Switch assignment between existing objects | `switchContainer.addAssignment` / `switchContainer.removeAssignment`; copy the exact operation, never an invented alias | generic mutation or same-row import side effect |
| Direct saved SoundBank inclusions | `soundbank.setInclusions` | Definition TSV |
| Existing caller-owned SoundBank Definition TSV | `soundbank.processDefinitionFiles` | reconstructed direct rows |
| Generate Bank artifacts | `soundbank.generate` | persistent inclusions |
| Heterogeneous allowlisted Undo step | `waapi.undoGroup` | wrapping one batch operation |
| Known installed GUI command without semantic route | `ui.commands.execute` | dedicated-route shortcut |

For `waapi.undoGroup`, follow its parent-owned `start_child` continuation. Complete each returned child through `draft-check`; never Preview a Compound Undo child independently. Copy every `checked_child_argument`, then start the next child or finish the parent with all arguments in requested order.

For one Bank's complete desired final inclusion set, use one `soundbank.setInclusions` `replace` transaction. Omitted rows are removed without being named individually; every other Bank remains outside that transaction. Do not split that final-state request into `add` and `remove` transactions.

Batch size never establishes file-workflow intent. If explicit table workflow lacks a caller-owned TSV, ask for it. Saved inclusions plus generation are two ordered transactions.

Keep domains distinct: durable Authoring project edits use `ak.wwise.core.*`; runtime actions use `ak.soundengine.*`; register a runtime Game Object with `request-schema ak.soundengine.registerGameObj`, never `object.create`; Authoring transport uses `ak.wwise.core.transport.*`; GUI actions use `ui.commands.execute`.

## Live metadata and business values

Users never supply internal tokens. Prompt/schema text, cached schemas, and Wwise knowledge are never exact live metadata evidence.

For `object.setProperty`, `object.setReference`, and `object.setLinked`, read the schema, start, bind the target, then run returned `draft-discover-fields`. Bind the exact existing owner first; that fixes the metadata scope inside the Draft. Copy one handle; never a token, scope, or type. No match stops; ambiguity needs one behavior question.

For `object.create`, `object.set`, and direct `audio.import`, start the business Draft, bind exact object/type scope, then use only returned discovery/binding commands. The returned type, restrictions, and opaque handle are the only value authority. A remaining Composer lane's returned start preconditions may require metadata first. For every `business_declaration` lane, start the Draft first and use its returned live binding or discovery command.

1. Bind the exact existing owner or the disclosed new-object type first.
2. Run the returned discovery once with short English Wwise UI/technical meanings; separate distinct meanings.
3. Copy one returned opaque handle per requested field; stop/clarify on no-match/ambiguity.
4. Submit business values against those handles. Copy returned enum labels or explicitly select a disclosed value; duplicate labels require a distinct choice. Gateway validates restrictions and activates proven dependencies.
5. `draft-check` revalidates scope, token, dependencies, and value; do not rediscover just to obtain a token.

For business declarations, bind only user-requested custom properties/references; common outcomes such as volume, infinite looping, output bus, maximum instances, parent instance-limit override, notes, Event, Dialogue Event, and Switch value use stable business fields. For table imports, discover only dynamic `Property[...]`, `Reference[...]`, or `@...` columns.

Omit every optional business field the user did not explicitly supply; defaults, examples, expected results, and verifier facts are not inputs. For user Lua files use `lua.executeCoreFile` or explicit CLI `lua.executeCliFile`; there is no `lua.executeFile` operation.

### Import/value rules

- For an ordinary `audio.importTabDelimited` import, do not `cat` or otherwise read the caller's TSV; pass its absolute path through the typed continuation.
- `SFX` is the built-in nonlocalized import token; never query language inventory for it.
- Batch `mode` is `create`, `reimport`, or `replace`; omit unrequested source-control settings.
- Bind the exact existing parent/target once. New objects declare parent handle, name, and semantic kind; existing objects declare their handle. Gateway constructs Wwise paths and type prefixes.
- For new hierarchy, declare each requested container once as a structure-only descendant; children may use its planned handle.
- Use `originals_subfolder` only when the user explicitly supplies it; never infer it.
- `media_directory` and `audio_file` are opaque caller paths; never derive either from campaign/workspace cwd. `audio_file`: supplied absolute path only; no relative/traversal or relocation.
- For an import Event, bind its exact parent, then provide Event name and business Action in the same Preview.
- Wwise Pitch is cents: `1 semitone = 100 cents`.

## CLI, host, and conversion routes

Only explicit WwiseConsole, CLI, command-line, or 命令行 wording selects `ak.wwise.cli.*`; a path alone does not establish CLI intent. CLI SoundBank generation runs compact `operations` and copies `routing_precedence.explicit_cli_soundbank_generation.choose` (`request-schema ak.wwise.cli.generateSoundbank`).

Every reflected `ak.wwise.cli.*` route plus `ak.wwise.console.project.create` and `ak.wwise.console.project.open` starts from catalog/user-supplied `request-schema <exact-uri>`, then `draft-start` and one `draft-declare-cli-console-plan`. Use `--value` per scalar, `--item` per member, `--mapping` per platform/value pair, and `--toggle <field> enable|disable`. Never type native CLI option names. The Gateway owns versions, serialization, I/O, and ordering; model-supplied global/pre-build/post-build hooks are prohibited. Wwise 2022 external-source partial success: disconnect or continued reachability never authorizes replay; result-schema-only evidence is not a reopened-project business oracle.

`ak.wwise.waapi.getSchema` uses `waapi-schema`. Test-tone and UI-project routes
use the returned `draft-declare-host-plan` contract. Every UI-project phase
requires Authoring.

Project open/close preserves the save prompt by default. Discard requires
explicit user intent. Let the user resolve save prompts; never repeat execution.
Follow Gateway verification/status, not GUI assumptions. Timeout is indeterminate.

### Authoring audio conversion

For `ak.wwise.core.audio.convert` in `2024.1`/`2025.1`, use `request-schema ak.wwise.core.audio.convert`, then its `core-business/v1` Draft. Bind exact object identities, platforms, languages, and the user's exact absolute `io_root`; the Gateway constructs the native request. Never return to typed-call.

## Preview, policy, and continuation

Unknown fields fail; there is no caller-authored request document. Never ask for confirmation while typed composition or Preview creation is still incomplete. A rejected or incomplete preview is a hard same-turn boundary. A changed target/value needs a new Preview.

Unless a trusted caller supplied an override, omit `--state-dir`; the Gateway owns the external runtime state root. File-backed routes require loopback; On `LOCAL_WAAPI_HOST_REQUIRED`, report and stop.

- `read_only`: block executable Preview.
- `ask_before_changes`: present expected result/risk, say unchanged, and ask.
- `allow_changes`: after Preview, announce the concrete impending change and continue.

Normal prose covers only objects, changes, results, risks, and whether anything changed. Hide API/operation names, Draft/transaction internals, ids, hashes, tokens, states, and commands. Keep exact `agent_result` machine-readable.

## Continue only from Gateway-owned commands

For every later phase, execute only the field named by `next_command.copy_instruction.source_field`, copying the complete string verbatim once. Windows normally selects `model_command`; encoded `shell_command` is audit/fallback unless explicitly selected. Do not render diagnostic `full_argv`. Truncated/incomplete instructions stop without inferred fallback.

- a status/check request stops after `transaction-show`;
- a clear confirmation follows returned confirm, execute, verify;
- confirmed/policy-authorized follows execute then verify;
- executed-unverified runs verify only;
- a verify-only request never executes.

`execution_in_progress`: no state change. Report busy; retry only in a later turn.

The confirmation token binds the exact stored Preview. Never reconstruct/substitute it or run `confirm --help`. For ordered multi-transaction work, after the prior item reaches terminal verification, a successful `verify` immediately starts the next already-requested transaction in the same turn and stops only when its executable Preview is visible. Never infer, add, combine, reorder, or turn later items design-only.

## Terminal states

- `verified`: report actual readback and stop.
- `result_schema_checked`: report only schema proof.
- `verification_deferred`: later verification is safe; never re-execute.
- `verification_failed`, `repreview_required`, `execution_cancelled`: report without retry.
- `execution_succeeded_persistence_failed`: preserve uncertainty; never replay.
- `indeterminate`: Do not verify, retry, call another Gateway route, or use another tool. A later diagnosis needs a new user request.

`ak.wwise.cli.migrate` ends at complete `execute`; run no later Agent tools/reads. Only the caller-owned harness outside the Skill sequence may reopen/prove it. Managed openers may leave cleanup uncertain; never synthesize code. Work Unit reversal and same-connection Undo stay explicit.

For an exact machine-readable answer, serialize the successful Gateway `agent_result` verbatim. Never fabricate a success projection from failed/deferred/indeterminate evidence.

<!-- WAAPI_OPERATE_REFERENCE_END -->
