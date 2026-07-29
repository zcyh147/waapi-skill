# WAAPI operate lane

Read this file once with one complete `cat`. A complete output ends with the exact `WAAPI_OPERATE_REFERENCE_END` sentinel. If that sentinel is visible, the reference is complete: do not run `sed`, `head`, `tail`, `rg`, or another `cat` for any part of it. If the sentinel is absent, stop and report an incomplete host read instead of attempting a partial reread or invoking the gateway.

Use this reference for project-changing work. The only normal execution path is the packaged transaction CLI. Do not import builders or planners from inline Python, create a helper script, construct a raw WAAPI mutation, or use the direct `call` command for live mutation. The closed `waapi.call` operation can execute a manifest-registered transaction route only through an immutable preview and the configured modification-policy authority. The three Undo Group member URIs are the exception: they can run only inside the closed `waapi.undoGroup` same-connection composite, never as independent calls. Run each reference read and each gateway command as its own shell tool call; never combine a read and gateway invocation with `&&`, `;`, pipes, command substitution, or another multi-command shell string. After one complete terminal `verify` result, stop all tool use for that transaction—do not inspect the filesystem or repository for extra business proof. An original request containing multiple closed transactions applies the current policy independently to each ordered item. For `ak.wwise.cli.migrate`, its one complete `execute` result is the terminal boundary instead.

## Choose the transaction phase first

An existing transaction continuation outranks the named-operation rule because its immutable preview already seals the request schema, target, value, endpoint, and artifact hash.

- **Existing transaction:** the user confirms, checks, rejects, executes, or verifies an already previewed transaction, and its transaction id is available from the message, conversation, or prior gateway result. A transaction id is required: an artifact hash alone is not a lookup key and is insufficient for continuation. If the id is unavailable internally, say that the saved preview context is unavailable and offer a fresh preview; do not ask a normal user to provide an internal transaction id, search transaction files, or inspect state directories. If `SKILL.md` and this reference are already visible from the preview turn in the same conversation/task, do not reread either file on the continuation turn. With the id, proceed directly. The first gateway command is `transaction-show <transaction-id> --summary-only`. Do not call `operations`, `operation-schema`, or `preview` first. This show is a safety gate, not a best-effort read: if its complete JSON is empty, truncated, non-JSON, or otherwise not visible—even with exit code `0` or a previously known id/hash—stop without any later transaction command and do not retry the show in that turn.
- **New change request:** no transaction exists yet. Use `operation-schema <semantic-name>` when `describe` lists a dedicated operation; `waapi.call` is a hard-rejected bypass for that URI. Otherwise use `describe <uri>`, except for the reviewed direct `waapi.call` fast routes below. Only a row reporting `transaction_operation` may use the exact operation named in its `transaction_operations`. The Undo member rows require `operation-schema waapi.undoGroup`; a row may use `operation-schema waapi.call` only when the catalog explicitly lists that fallback. Construct that closed request and use `preview --apply` for an actual change or plain `preview` for a design-only review. Do not call `operations` first: that command is only for broad capability-inventory questions and returns a compact inventory by default.

## Choose by business outcome, not native API overlap

A native WAAPI function being technically capable of encoding a request does
not make it the right Skill route. Select the operation whose business
postcondition and verifier most directly match the user's request. Prefer the
smallest operation that covers the complete authorized outcome in one
transaction, and never invent an intermediate file or decompose a higher-level
outcome merely to reach another API. A successful `operation-schema` exposes
the same rule in `operation.selection_guidance`.

Use these precedence rules before the first Gateway call:

| User intent | Select | Do not substitute |
|---|---|---|
| Import one or many media rows described directly in the request | `audio.import` | `audio.importTabDelimited` merely because the batch is large |
| Process an existing caller-supplied TSV, replay an externally maintained import manifest, or explicitly use Wwise's table workflow | `audio.importTabDelimited` | An Agent-generated TSV that only re-encodes natural-language parameters |
| Create a pure new object hierarchy with no media | `object.create` | A structure-only `audio.import` unless that row belongs to an actual import manifest |
| Mutate existing roots, several existing objects, or an explicitly existing nested container | `object.set` | `object.create` |
| In Wwise `2023.1`–`2025.1`, import media as one subordinate part of a broader atomic existing-object mutation | `object.set` with its closed `import` field | A separate `audio.import` transaction |
| Make one isolated rename, notes, scalar-property, or reference change | `object.setName`, `object.setNotes`, `object.setProperty`, or `object.setReference` | The broader `object.set` batch |
| Change platform link state, create a plug-in, edit an RTPC curve, or change a Switch Container assignment | The dedicated `object.setLinked`, `object.createPlugin`, `object.setRTPC`, or `switchContainer.*Assignment` operation | A generic property, reference, or list mutation |
| Change a native Authoring concept such as a Game Parameter range, Randomizer, Attenuation Curve, State structure, Conversion Plug-in, Active Source, or Blend assignment | Its exact specialized API returned by `describe` | `object.setProperty`, `object.setReference`, `object.set`, or a UI command |
| Combine heterogeneous allowlisted mutations into one explicitly requested Wwise Undo step | `waapi.undoGroup` | A compound wrapper when one dedicated batch operation already owns the whole outcome |
| Directly edit one SoundBank's inclusion rows | `soundbank.setInclusions` | A generated Definition TSV |
| Process existing caller-supplied SoundBank Definition TSV files | `soundbank.processDefinitionFiles` | Reconstructing the files as direct inclusion calls |
| Generate SoundBank artifacts, including one generation-only Event/AuxBus definition | `soundbank.generate` | Treating generation input as a persistent edit to the Bank's saved inclusions |
| Capture a Wwise UI image | `ui.captureScreen` | A generic UI command |
| Execute a known installed GUI command with no matching semantic operation | `ui.commands.execute` | A shortcut around a dedicated operation or a closed boundary |

Batch size alone never establishes table-file intent: `audio.import` is already
batch-capable. If a table workflow is explicit but no existing TSV path was
supplied, ask for that artifact instead of creating it. Conversely, do not ask
the user to choose a WAAPI function when their business intent already selects
one row above.

Keep execution domains distinct. Durable edits to saved Wwise project objects,
properties, curves, references, and relationships use the matching
`ak.wwise.core.*` route or dedicated semantic operation. Current SoundEngine
playback, Game Object, listener, spatial, Bank, RTPC, Switch, State, Trigger,
Event, and related runtime state uses `ak.soundengine.*`; auditioning an
Authoring object uses
`ak.wwise.core.transport.*`; an explicitly requested menu or GUI command uses
`ui.commands.execute`. For example, `object.setRTPC` authors a curve while
`ak.soundengine.setRTPCValue` changes a runtime value, and
`switchContainer.*Assignment` edits project relationships while
`ak.soundengine.setSwitch` changes a runtime Switch. Do not cross these domains
merely because their names are similar, and do not assume every
`ak.wwise.core.*` route persists project data: transport, Profiler, remote,
debug, and other session/tool families retain their own domains. The
URI-specific `describe` result exposes `interface.selection_guidance`; every
SoundEngine route receives a runtime-domain fallback and high-ambiguity routes
add more specific alternatives. Within the Profiler domain, `setCursorTime` is
absolute positioning and `moveCursor` is relative movement; do not infer one
from the other.

When an import request also asks that same import create its Event or Switch
Assignation side effect, keep it inside the single `audio.import` transaction.
Use the dedicated Event/object or Switch Container operation only for an
independent change to existing project objects. Likewise, use an operation's
`auto_add_to_source_control` or `auto_check_out_to_source_control` field when
source control is subordinate to that mutation; choose a standalone
`sourceControl.*` route only for an independent source-control workflow.

`soundbank.generate` does not persistently replace
`soundbank.setInclusions`: generation definitions describe the requested
artifact run, while `setInclusions` changes the Bank's saved inclusion state.
If the user explicitly wants both outcomes, use two ordered transactions under
the configured modification policy instead of treating either one as an
implicit implementation detail.

For an object-tree change, choose the named operation before making the first
Gateway call; do not probe one semantic operation and switch after rejection.
Evaluate the `object.set` exclusions first:

- Use `operation-schema object.set` only when the request changes fields or
  references on existing roots, targets multiple existing roots, or appends
  children below a nested container explicitly identified as already existing.
  Any one of these conditions locks `object.set` for the request and excludes
  `object.create`.
- Only after all three `object.set` exclusions are absent may an existing-root
  merge use `object.create`. If exactly one same-name root already exists, the
  root itself must remain unchanged, and the request only recursively merges a
  descendant tree beneath it—a pure descendant-tree merge—begin with
  `operation-schema object.create`.
  Set `parent` to the existing root's parent, repeat the root's exact `type` and
  `name`, and set `on_name_conflict: "merge"` in the closed request. The root's
  existence alone never selects `object.set`.
- A wholly new recursive root also begins with
  `operation-schema object.create`.

## Resolve properties and references from live metadata

When the user's requested change describes a property or reference by meaning,
resolve its exact live Wwise name before constructing the closed operation
request. The user should keep speaking naturally; never ask them to provide an
internal property/reference name.

- If an exact name has not already been returned by live metadata in the
  visible conversation, run one `metadata discover` command with repeated
  `--query '<ordinary search phrase>'` values and an optional bounded
  `--limit`. Use exactly one scope: `--object-type` for a new or imported
  object's known type, `--class-id` for an already proven live class ID, or
  `--object` for an existing object or plug-in object.
- Copy into `properties` or `references` only exact names returned by that live
  discovery. Do not guess from memory, translation, UI labels, or an
  object-specific preset. This rule applies across import, create, set, plug-in,
  and isolated property/reference operations.
- Keep related intent phrases in the same discovery invocation. The route is a
  bounded read; class/type and canonical-object-GUID evidence is shared with
  transaction preview, while mutable path scope is revalidated. A cache miss
  merely performs the live metadata reads. Do not expose or inspect cache paths
  as part of an ordinary Wwise task.
- If internal names do not match the phrases, discovery performs a bounded scan
  of live display/UI details. Treat `fallback_detail_scan.status: "partial"` as
  incomplete retrieval: retry once with broader related technical phrases, and
  never turn a partial `no_match` into a guessed field name.
- When several candidates remain, choose only when the returned metadata and
  user intent clearly distinguish the behavior. Otherwise ask one natural
  behavior question without showing the user a list of internal names.
- Honor live dependency metadata. If the selected setting requires another
  same-object property to enable or override it, include that enabling value in
  the same request when the user clearly asked for that behavior. Ask before
  preview when the dependency's intended value is unclear.

An exact live-proven name already visible in the conversation does not require
another discovery call. The later immutable preview remains authoritative and
validates the final property/reference request before any mutation.

The user's current intent authorizes actions; the returned transaction state only constrains which actions are legal and never authorizes an action by itself. Read the complete JSON returned by each transaction command before issuing the next one. Never suppress or redirect gateway output, request a zero/short tool-output budget, or infer a successful state transition from exit code `0`; if the complete JSON is not visible, stop and report that missing result:

- A status or check request stops after `transaction-show`; report the returned state without calling `confirm`, `execute`, `verify`, or `reject`.
- An explicit rejection may call `reject` after the show and then stops.
- A clear confirmation may continue from `awaiting_confirmation` through `confirm`, `execute`, and `verify`; from `confirmed` through `execute` and `verify`; or from `executed_unverified` through `verify` only. A current `allow_changes` request may continue from `policy_authorized` directly through `execute` and `verify` after the required notice. Risks and verifier limits already disclosed by a successful immutable preview are decision information, not a second Agent veto: after the user clearly confirms that same request, continue and report those limits with the terminal result. A confirmation that merely calls the already connected project a copy or isolated project does not change scope unless it identifies another project/path or asks to switch or open one; a genuine project or request change instead requires a new preview. Continue from `execute` to `verify` only when its complete result is successful and reports `executed_unverified`. Apply the same policy independently to each item in an explicitly ordered multi-transaction request; do not invent another batch or change its order. A complete execute result with `status` and `state` both `indeterminate` is terminal for that turn: report it and stop immediately without `verify`, retry, `transaction-show`, another gateway call, filesystem inspection, or any other follow-up command. A later diagnosis requires a new user request and must use a packaged read-only Skill route; caller-owned test oracles remain outside the Skill command sequence. `ak.wwise.cli.migrate` is the narrow exception: its one `execute` is the terminal gateway invocation. Once that complete execute JSON is visible, stop all gateway activity immediately and run no more Agent tools at all: no generic `verify`, `status`, `query-object`, or `call`, and no `sed`, `rg`, `cat`, `find`, `ls`, `head`, or `tail`. Do not run another gateway command to reopen or inspect the migrated project. The Agent must not read the project, `.wproj`/`.wwu` files, broker evidence, lifecycle evidence, logs, `business-oracle-plan`, or any other evidence/oracle artifact. The caller-owned reopened-project oracle runs outside the Skill command sequence. Only the caller-owned harness—not the Agent—may close Wwise, reopen the migrated project, and read those artifacts for final business verification.
- An explicit verify-only request may call `verify` only from an applicable executed state; it never calls `execute`.
- Terminal states are reported without another mutation.

Use `operations --detail` only for an explicit audit of every nested request contract. An implemented named semantic operation owns its underlying URI and removes the generic `waapi.call` route, even when its request shape is intentionally narrower than native WAAPI. Treat that narrower contract as the interface boundary; never infer or probe a raw fallback from the operation name.

### Deterministic Wwise `2022.1` `ak.wwise.cli` request mapping

The four packaged CLI transaction rows below use raw `waapi.call`, but their request is still closed and reconstructible from ordinary user language. These four CLI no-`describe` fast routes apply only to Wwise `2022.1`: after reading the Skill from its injected absolute `SKILL.md` locator and reading this reference exactly once, run `operation-schema waapi.call` as the first gateway command; do not run `describe` or `capabilities` first. When the version was not visible before that call, inspect only the returned `session_context`; apply the mapping below only if it reports `2022.1`. If it reports another version, do not preview and use `describe <uri>` next. If it still provides no version, report the missing version or ask the user instead of guessing. For any other already-known configured/runtime Wwise version, do not reuse these field rules; begin with the ordinary `describe <uri>` route and obey that version's reflected schema and declared transaction operation. Do not invent a case root, hidden cache, default boolean, or custom hook. Include a boolean only when the user explicitly requests its true behavior; omit false/default fields. `options` is always `{}`.

Both offline routes now expose the packaged field contract instead of requiring
the Agent to infer it from prose. A version-pinned `operation-schema waapi.call`
returns `cli_request_templates` for all four CLI APIs; `describe <exact-cli-uri>`
returns that URI's `request_template` in every requested version row. These are
constraints-only records, not executable sample payloads: they contain no
placeholder values. The compact operation-schema index names required, blocked,
and version-delta fields and points to `describe`; the detailed describe record
lists every exact reflected and accepted field, keeps `options` fixed to `{}`,
and requires an absolute sibling `io_root`. Gather the real user values first,
then materialize them only inside the `request_envelope` returned by
`operation-schema`.

The packaged manifests prove these field changes:

- `generateSoundbank` adds `no-source-control`, `root-output-path`, and
  `use-user-overrides` in `2022.1`; the reflected name is
  `use-user-overrides`, never the invented `use-user-settings`.
- `generateSoundbank` adds `license-file` in `2023.1`.
- `no-wwise-dat` exists for `generateSoundbank` and `convertExternalSource`
  through `2023.1`, then is absent in `2024.1` and `2025.1`.
- `tabDelimitedImport` and `migrate` add `no-source-control` in `2023.1`.

Choose between the CLI and connected-Authoring families before selecting an operation:

- Only explicit WwiseConsole, CLI, command-line, or 命令行 wording selects an `ak.wwise.cli.*` row and `operation-schema waapi.call`. The selected CLI row then requires its case-owned `.wproj`, but a `.wproj` path, a JSON `project` field, a project-copy description, or output/cache paths alone never establish CLI intent.
- Without that explicit CLI wording, work through the already connected Authoring project using the dedicated `ak.wwise.core.*` operation when one exists. Connected bank generation uses `soundbank.generate`, External Sources `.wsources` conversion uses `soundbank.convertExternalSources`, Definition `.tsv` processing uses `soundbank.processDefinitionFiles`, and a connected tab-delimited audio import uses `audio.importTabDelimited`.
- For each of those three connected SoundBank workflows, the first gateway command after this reference read is the matching named `operation-schema`; in particular, generation begins with exactly `operation-schema soundbank.generate`. Do not run `describe`, `query-object`, or `operation-schema waapi.call` first. Do not inspect a supplied `.wsources` or `.tsv` with `cat`, `sed`, or another shell command, and do not split identity prechecks into a separate query: the named operation's `preview` owns strict file parsing, input proofs, and required live identity resolution. After a successful `execute` reports `executed_unverified`, run its returned `verify` before answering.
- The similar names are not interchangeable. `ak.wwise.cli.convertExternalSource` (singular) is not `ak.wwise.core.soundbank.convertExternalSources` (plural); `ak.wwise.cli.generateSoundbank` is not `ak.wwise.core.soundbank.generate`; and `ak.wwise.cli.tabDelimitedImport` is not `ak.wwise.core.audio.importTabDelimited`.
- Once the user's explicit CLI wording establishes one of the four 2022.1 CLI rows and its required `.wproj` is present, do not probe a same-named dedicated operation first. Conversely, do not choose `waapi.call` for an already-connected Authoring request merely because it includes a project path/field, output/cache paths, or rebuilding.

Use these JSON cardinality shapes for every applicable CLI route; they are field contracts, not case-specific examples:

- `bank`: one Bank name or one absolute Bank-list file is a JSON string (`"Dialogue_Chapter01"`); multiple Bank names are a JSON array (`["Dialogue_Chapter01","Music"]`).
- `platform`: always a JSON array, including one platform (`["Windows"]`).
- `language` and `import-definition-file`: one value is a JSON string (`"value"`); multiple values are a JSON array (`["value-1","value-2"]`). For Wwise `2022.1` `convertExternalSource`, `source-file` is exactly one `.wsources` string. Do not use its reflected array shape: real 2022.1 runs process only the first member.
- `project`, `io_root`, `cache`, and `root-output-path`: always scalar JSON strings. The tab-delimited route likewise uses scalar strings for `project`, `tab-delimited-import-file`, `tab-delimited-operation`, and `import-language`; the migrate route's `project` is also a scalar string. Never wrap one of these fields in a single-item array.
- `convertExternalSource` `output`: always bind each platform to its final physical output directory. One platform uses a flat pair (`["Windows","/absolute/windows-output"]`); multiple platforms use the pair array below. Do not use scalar `"/absolute/output"` for a platform-specific final directory: Wwise treats that scalar as a shared parent and appends a platform subdirectory.
- Platform/value mappings such as `source-by-platform`, `output`, and `soundbank-path`: one pair is a flat two-string array (`["Windows","/absolute/path"]`); multiple pairs are an array of two-string arrays (`[["Windows","/windows"],["Mac","/mac"]]`). Do not add an outer array around a single pair. In Wwise `2022.1` `convertExternalSource`, each platform may occur only once in `source-by-platform`: real runs process only the last entry for a repeated platform.

- `ak.wwise.cli.convertExternalSource`: map the stated `.wproj`, platform names, one `.wsources` file shared by all platforms or one unique platform/file pair per platform, and each platform's final output directory directly to `project`, `platform`, `source-file` or `source-by-platform`, and platform-bound `output`. With one output pair, `io_root` is that pair's absolute directory. With several output pairs, use their deepest common absolute ancestor. For example, outputs `/case/cli-io/windows` and `/case/cli-io/mac` require the exact `io_root` `/case/cli-io`, never the broader `/case`. If that deepest ancestor is only the filesystem root, stop and ask for one narrower common output root. If a user supplies multiple manifests for the same platform, do not preview a partial request or create a merged file: ask for one caller-prepared union `.wsources`, or offer separately previewed transactions.
- `ak.wwise.cli.generateSoundbank`: map the requested non-Init Bank names (or the stated absolute UTF-8 Bank-list file), platforms, and explicit languages to `bank`, `platform`, and optional `language`. Init is generated automatically and is not added to `bank`. An explicit non-localized-only request adds `skip-languages:true`; an explicit cache clear adds `clear-audio-file-cache:true`; an explicit `Wwise_IDs.h` request adds `header-file:true`; explicit definition files map to `import-definition-file`. For one platform, `soundbank-path` is `[PLATFORM, OUTPUT_ROOT]`; for several, it is `[[PLATFORM, OUTPUT_ROOT/PLATFORM], ...]`. Use a user-stated dedicated cache/root-output path when present; otherwise set `cache` to `OUTPUT_ROOT/.waapi-skill-cache` and `root-output-path` to `OUTPUT_ROOT`. Derive `io_root` from exactly the resolved path values in `soundbank-path`, `cache`, and `root-output-path`: use their deepest common absolute ancestor, never include `project`, the `.wproj` directory, or any other path in that calculation, and reject a filesystem-root-only result. Omit `save`, `continue-on-error`, `use-stable-guid`, and every other false/default flag unless the user explicitly requested an available true behavior. Its sealed execution contract keeps the normal invariant project guard before execution, but `verify` does not issue a post-execution project probe because WwiseConsole may have already torn down that context. It instead revalidates the exact endpoint/getInfo process identity and packaged runtime against the preview, checks the sealed result schema, and can report only `result_schema_checked` with `verified:false`—never business-state verification.
- `ak.wwise.cli.tabDelimitedImport`: map the stated `.wproj`, TSV, Wwise language, and explicit `createNew`, `useExisting`, or `replaceExisting` intent to `project`, `tab-delimited-import-file`, `import-language`, and `tab-delimited-operation`. `io_root` is the absolute directory containing the case-owned `.wproj`. Omit `audio-source-from-original` and `continue-on-error` unless explicitly requested true.
- `ak.wwise.cli.migrate`: map only the stated case-owned `.wproj` to `project`; `io_root` is its containing directory. Add `abort-on-load-issues:true` only when the user explicitly asks to abort on load issues. Do not infer `verbose` merely because the user asks for a warning summary. The separate control WAAPI server may remain reachable or disconnect after its one `execute`; neither outcome changes the no-retry rule, and only caller-owned lifecycle evidence may classify an actual natural exit. An exact non-retryable `indeterminate` execute result must not be replayed. After the complete execute JSON, stop instead of opening or querying the migrated project through the gateway. Final success still requires the caller-owned reopened-project oracle outside this command sequence; the generic gateway alone does not claim that readback.

For a two-platform `convertExternalSource` preview with one shared manifest,
preserve this complete JSON nesting and replace only the angle-bracket values.
In particular, `output` closes both the second pair and its outer array before
`args` closes; the final two braces close `arguments` and the request root. Do
not reconstruct a shorter or differently nested envelope from memory:

```json
{"contract":"waapi-skill.operation-request/v1","version":"2022.1","operation":"waapi.call","arguments":{"api":"ak.wwise.cli.convertExternalSource","args":{"project":"<absolute-project.wproj>","platform":["Windows","Mac"],"source-file":"<absolute-source.wsources>","output":[["Windows","<absolute-windows-output>"],["Mac","<absolute-mac-output>"]]},"options":{},"io_root":"<deepest-common-output-directory>"}}
```

When each platform has its own manifest, use this complete
`source-by-platform` shape:

```json
{"contract":"waapi-skill.operation-request/v1","version":"2022.1","operation":"waapi.call","arguments":{"api":"ak.wwise.cli.convertExternalSource","args":{"project":"<absolute-project.wproj>","platform":["Windows","Mac"],"source-by-platform":[["Windows","<absolute-windows-source.wsources>"],["Mac","<absolute-mac-source.wsources>"]],"output":[["Windows","<absolute-windows-output>"],["Mac","<absolute-mac-output>"]]},"options":{},"io_root":"<deepest-common-output-directory>"}}
```

Multiple `.wsources` files for one platform are a structured Wwise `2022.1`
boundary, not another cardinality spelling. A `source-file` array processes only
its first member, while repeated `source-by-platform` pairs process only the
last member for that platform. The gateway rejects both partial-success shapes.

For a two-platform `generateSoundbank` request that explicitly asks for
non-localized generation, cache clearing, and `Wwise_IDs.h`, preserve this
compact complete JSON shape. The `io_root` placeholder is computed from only
the two `soundbank-path` values, `cache`, and `root-output-path`; the `project`
path does not participate:

```json
{"contract":"waapi-skill.operation-request/v1","version":"2022.1","operation":"waapi.call","arguments":{"api":"ak.wwise.cli.generateSoundbank","args":{"project":"<absolute-project.wproj>","bank":["<bank-1>","<bank-2>"],"platform":["Windows","Mac"],"skip-languages":true,"clear-audio-file-cache":true,"header-file":true,"soundbank-path":[["Windows","<absolute-windows-output>"],["Mac","<absolute-mac-output>"]],"cache":"<absolute-cache>","root-output-path":"<absolute-root-output>"},"options":{},"io_root":"<deepest-common-ancestor-of-soundbank-path-cache-root-output>"}}
```

These Wwise 2022.1 derivations are product rules, not eval-only shortcuts. If the natural request omits a platform, language policy, import mode, or output relationship needed to choose one exact mapping, ask the user rather than guessing.

### Deterministic Wwise `2024.1` / `2025.1` Authoring audio conversion request mapping

The reviewed raw Authoring conversion route is a no-hidden-argument and no-`describe` fast route:

- `ak.wwise.core.audio.convert` (`2024.1` / `2025.1`): after the exact absolute Skill and complete operate-reference reads, use `operation-schema waapi.call` as the first gateway command without `describe` or `capabilities`. If the version was initially unknown, apply this fixed mapping only after that result's `session_context` reports either `2024.1` or `2025.1`; on another version, do not preview and use its ordinary `describe` route next. The reflected `args` object requires all three keys: `args.objects`, `args.platforms`, and `args.languages`. Each value is a non-empty ordered JSON array of strings, including for one item; never use object wrappers such as `{"object":"..."}`, `{"path":"..."}`, or `{"name":"..."}`. Map the exact Wwise object paths and platform names in the user's stated order. When the user gives one absolute parent path plus named direct children, form each object path by joining that parent with each child in the stated order; do not search recursively or include unnamed descendants. Any natural phrase that calls the conversion targets SFX maps to `languages:["SFX"]` unless the user explicitly names localized languages; explicit localized languages replace that default and stay in the user's stated order. Use `options:{}` and the user's stated absolute allowed conversion root exactly as `io_root`. Do not add or remove a target, platform, language, or root based on project discovery. If any of those four inputs is missing or ambiguous after applying the SFX rule, ask before previewing.

Copy the complete version-specific envelope returned by
`direct_fast_route_contract.canonical_request_template`, replacing only its
listed values and extending the three arrays in their stated order. The two
reviewed versions differ only in the exact version bound into that returned
envelope. This canonical request contract applies only to
`ak.wwise.core.audio.convert`, never to another `waapi.call` URI:

```json
{"contract":"waapi-skill.operation-request/v1","version":"2024.1","operation":"waapi.call","arguments":{"api":"ak.wwise.core.audio.convert","args":{"objects":["<exact-wwise-object-path>"],"platforms":["<platform>"],"languages":["SFX"]},"options":{},"io_root":"<absolute-allowed-conversion-root>"}}
```

```json
{"contract":"waapi-skill.operation-request/v1","version":"2025.1","operation":"waapi.call","arguments":{"api":"ak.wwise.core.audio.convert","args":{"objects":["<exact-wwise-object-path>"],"platforms":["<platform>"],"languages":["SFX"]},"options":{},"io_root":"<absolute-allowed-conversion-root>"}}
```

After the one complete read of this reference, do not reread any line range with `sed`, `head`, `tail`, `rg`, or another partial-file command; proceed directly to the one gateway command above.

## Closed transaction flow

Derive the absolute Skill directory from the injected absolute `SKILL.md` locator and invoke its absolute `scripts/run.py` path in every actual tool call. The snippets below retain `scripts/run.py` only as readable shorthand; never execute that relative spelling in an automated agent run.

In ordinary agent use, omit `--state-dir` on every gateway command: the Gateway owns a deterministic external transaction-store default. Never run `env`, `printenv`, shell expansion, or another environment-inspection command to discover `WAAPI_SKILL_STATE_DIR`; do not read, guess, or search for its value, and never ask a normal user to provide this implementation path. Pass `--state-dir` only when the user or trusted caller explicitly supplied a trusted absolute override, then reuse that exact path unchanged. Explicit caller flags retain priority over the Gateway-owned default.

For an actual, unambiguous change request:

```bash
python scripts/run.py gateway.py operation-schema <operation-name>
python scripts/run.py gateway.py preview --apply --request-json '<request-v1-json>'
```

The preview envelope alone permits a 393216-byte JSON document and a
262144-byte string so one reviewed inline-WAV value can reach the operation
validator. Other JSON gateway arguments retain the smaller general limits.
The selected operation schema remains authoritative for its tighter request,
aggregate Base64, and canonical-normalization ceilings.

For a request that asks only to preview, plan, or explain a possible change,
omit `--apply`. A preview without `--apply` never carries policy authority to
execute.

The successful `operation-schema` result owns the request's outer envelope.
When `request_envelope_policy.status` is `ready`, copy `request_envelope`
exactly and replace only its empty `arguments` object with the fields required
by that same schema. Its four top-level keys are always `contract`, `version`,
`operation`, and `arguments`; never omit `version`, even when the gateway is
already configured for that version. If the envelope is not ready, resolve the
reported version or implementation boundary before previewing instead of
inventing a value. Place every operation argument at the exact location in
`request_envelope_policy.argument_paths`. In particular, the four `waapi.call`
arguments `api`, `args`, `options`, and `io_root` are siblings inside
`$.arguments`; `io_root` is never nested inside the reflected API's `args`.

Use the canonical `project_modification_policy` returned in the latest gateway
`session_context`:

- `read_only` blocks an actual change. Explain the current mode and stop after
  `operation-schema`; do not run `preview --apply`. The Gateway also rejects
  that spelling before opening WAAPI if it is attempted. A design-only preview
  without `--apply` remains available.
- `ask_before_changes` makes `preview --apply` return
  `awaiting_confirmation`. Name the concrete root and major child targets, then
  summarize every requested target/value, expected result, conflict behavior,
  irreversible effect, verifier limit, cleanup obligation, or other fact that
  could change the user's decision. Say clearly that nothing changed, ask as a
  natural direct question whether to proceed, and end the turn. Keep transaction
  ids, artifact hashes, confirmation tokens, internal state labels, and returned
  commands out of ordinary user prose; retain them only for exact continuation.
  Reveal them only when the user explicitly requests raw, machine-readable, or
  diagnostic transaction data.
- `allow_changes` makes `preview --apply` return `policy_authorized` for normal
  project changes. Name the concrete root and major child targets from the
  preview, summarize what is about to change, and tell the user that the current
  mode permits it. Put that notice in an Agent message after the preview
  completes and before `execute`; an earlier introduction does not count, and a
  generic object count is not enough. Then, in the same user turn, copy the returned
  `execute` command exactly once and follow a successful
  `executed_unverified` result with its exact `verify` command. Do not report
  success until verification has finished.

`debug.restartWaapiServers`, `debug.testAssert`, and `debug.testCrash` are
confirmation-only host controls: even under `allow_changes`, their preview
returns `awaiting_confirmation` and must wait for a later explicit user
confirmation. The Gateway records ordinary direct authority as
`policy_authorized`; it never mislabels policy authority as user confirmation.
It re-reads the policy before dispatch, and a downgrade prevents the mutation.

`read_only` does not block catalog-classified reads. Some reflected read
functions deliberately use `waapi.call` transactions for bounded schema
validation and result verification. For a row whose packaged execution
contract says `effect: read`, omit `--apply`; its immutable preview accepts
explicit confirmation only and remains executable under `read_only`. Never
infer this classification from the user prompt or from the API name.

On a successful preview, `agent_result` is the compact machine-result projection bound directly to the immutable artifact request. If the user requires a machine-readable result, serialize that object exactly; do not retype or rebuild its request, transaction id, hash, state, or flags.

For `ask_before_changes` or a confirmation-only host control, stop after the
preview. Only after a later user message clearly confirms that preview, start
the continuation by showing the stored transaction:

```bash
python scripts/run.py gateway.py transaction-show <transaction-id> --summary-only
python scripts/run.py gateway.py confirm <transaction-id> --confirmation-token <gateway-token>
python scripts/run.py gateway.py execute <transaction-id>
python scripts/run.py gateway.py verify <transaction-id>
```

Treat these as separately gated commands, never as a batch. Inspect one
complete JSON result before issuing the next command. Every successful
non-terminal phase exposes its state-valid continuation as
`next_command.full_argv`, including the canonical `python`, absolute
`scripts/run.py`, and `gateway.py` prefix. An `awaiting_confirmation` preview's
continuation is `transaction-show ... --summary-only` and must wait for a later
user message. On that later turn, copy the entire returned command exactly. The
show result contains a top-level confirmation object with contract `waapi-skill.confirmation-binding/v1`
and a token bound to the stored transaction id, full artifact hash, current state,
event sequence, and last event hash. Never reconstruct, shorten, or normalize the returned launcher
prefix from memory. Only when the current user message explicitly confirms that
preview may the returned confirm command be run. If `confirm` does not return
complete visible JSON, stop before `execute` or `verify`, even when its shell
exit code is `0`. Do not generate, shorten, validate from spelling, reconstruct, or substitute the token;
do not fall back to the displayed artifact hash or run `confirm --help`.

If `confirm` returns empty, truncated, non-JSON, or otherwise incomplete visible
output, stop before `execute` and `verify` even when the shell reports exit code `0`;
do not infer confirmation from the exit code or previously known transaction values.

A `policy_authorized` preview has no confirmation token and returns `execute`
directly. Its durable authorization names `allow_changes`,
`explicit_confirmation:false`, and the caller-asserted current change request.
Issue a natural-language notice before that execution tool call. If a later
continuation first uses `transaction-show`, execute only when the show result
still returns the exact `execute` next command; a policy downgrade instead
reports that a new preview is required.

The Gateway keeps `next_command` after `session_context` as the final actionable top-level field. A preview additionally mirrors that same object as the final field of its terminal `agent_result`; use the exact returned `next_command.shell_command` from that structured tail and never rebuild its path.

Use `next_command.shell_command` as the executable representation. Once the user has authorized that state transition, pass the returned string verbatim as one shell tool call; do not render `full_argv`, re-quote it, or rebuild any launcher path segment yourself. `shell_family` states which host spelling the gateway supplied.

When the original request itself contains a closed ordered sequence of
independent transactions, apply the configured policy independently to each
item after the prior item reaches its terminal verification result. Never infer,
add, or reorder an item.

The final `verify` command in this generic sequence does not apply to `ak.wwise.cli.migrate`. For that route, stop after the one complete `execute` JSON even when its durable transaction state is named `executed_unverified`; that label records the gateway's deliberately weaker evidence and does not authorize a generic verification call.

`transaction-show --summary-only` always preserves the exact immutable `request`,
full artifact hash, guard fingerprints, event chain, and complete cleanup spec. Its
`summary_contract` and `detail_level` explain whether prepared dispatch, role,
pre-state, and verification evidence is shown directly or as deterministic
counts and SHA-256 digests. A digest projection is an intentional bounded review
form, not missing output; review the exact request, complete SHA-256, and cleanup
obligation, then use only the Gateway-owned short token already embedded in the
returned `next_command.shell_command` for confirmation. Never reconstruct omitted
prepared internals, derive a token from the hash, or replace either with
model-authored code.

Never run `confirm` merely because the original request used an imperative verb.
Under `ask_before_changes`, preview and explicit confirmation are separate
turns. Under `allow_changes`, the original request must itself be an
unambiguous actual-change request before `--apply` is used; a design preview or
ambiguous target never receives policy authority. If the user changes the
target or requested value, reject or abandon the old transaction and create a
fresh preview.

## Request v1

`preview` accepts one JSON object and no arbitrary Python kwargs:

```json
{
  "contract": "waapi-skill.operation-request/v1",
  "version": "2024.1",
  "operation": "object.create",
  "arguments": {
    "parent": {"kind": "path", "value": "\\Actor-Mixer Hierarchy\\Default Work Unit\\WAAPI Sandbox"},
    "type": "ActorMixer",
    "name": "New Actor Mixer",
    "notes": "Created through the WAAPI Skill transaction gateway"
  }
}
```

A rejected or incomplete `preview` result is a hard same-turn boundary. If the
shell rejects the command, JSON parsing fails, a broker rejects it, or the
complete gateway JSON is not visible, stop that turn immediately.
Do not repair a bracket, reformat the payload, or retry `preview` in the same
turn; a later attempt needs a fresh transaction context.

All request levels are closed: unknown fields fail. Identity shapes are exactly:

- `{"kind":"id","value":"{GUID}"}`
- `{"kind":"path","value":"\\Exact\\Wwise\\Path"}`
- `{"kind":"waql","value":"from ..."}`
- `{"kind":"scoped-name","name":"Name","type":"Sound","parent":{"kind":"id","value":"{GUID}"}}`

For dedicated semantic operations, never supply identity rows, `property_info`, `reference_info`, schema objects, dispatcher args/options, or a WAAPI URI. The runtime obtains those from live read-only preflight and versioned packaged resources.
Once an exact property/reference token is known, do not run a separate
`metadata property-info` command merely to validate it before `preview`:
`object.create`, `object.set`, and both import operations perform that live,
typed validation internally and deduplicate repeated metadata reads in the same
transaction. Use the offline `object-types` catalog instead of live
`metadata types` for ordinary class-ID/type discovery.

### Exact `object.create` type tokens

`object.create` `type` values are exact Wwise metadata tokens, not translated or shortened labels. Apply these deterministic mappings for natural Wwise terms in the request, at both the root and child levels:

- Actor Mixer / ActorMixer / Actor Mixer 对象 → `ActorMixer`
- Random Container / 随机容器 → `RandomSequenceContainer` (never `RandomContainer`)
- Blend Container / 混合容器 → `BlendContainer`
- Sound / 声音对象 → `Sound`

For another type, use an exact Wwise token explicitly supplied by the user; if they provide only an ambiguous natural label, ask rather than inventing a token.

When `object.create` merges descendants into an existing named root, keep that
existing object as the request root: set `parent` to its existing parent and
repeat the root's exact `type` and `name`; use `on_name_conflict: "merge"`, and
include every requested new branch in the one closed child tree. Do not retarget
`parent` to the existing root or promote one requested child to become the
request root.

For `object.set`, every `objects[]` row names an existing object to update. If
one call updates existing roots and also appends children to existing nested
containers, give each such nested container its own `objects[]` row using the
exact path derivable from the user's stated hierarchy; keep only genuinely new
descendants under that row's `children`. Do not replace that exact path with a
`scoped-name` identity when the stated hierarchy already determines the path.

For guarded `object.create` replacement, `replace_owned_root` names the reviewed
authorization boundary, not the object being replaced. The collision must be
strictly below it. If the request creates `name=X` under `parent=P` and replaces
the existing `P\\X`, normally set both `parent` and `replace_owned_root` to `P`;
never set `replace_owned_root` to `P\\X`. The requested name confines the actual
replacement to `P\\X`, so a sibling such as `P\\Keep_Me` remains outside the
mutation.

The generic packaged transaction has one intentionally different shape:

```json
{
  "contract": "waapi-skill.operation-request/v1",
  "version": "2024.1",
  "operation": "waapi.call",
  "arguments": {
    "api": "ak.wwise.core.project.save",
    "args": {},
    "options": {}
  }
}
```

The exact URI must be reflected in that version and assigned to `transaction`, `managed_transaction`, or `isolated_transaction`; fixed/direct/topic/excluded rows are rejected. `args` and `options` are recursively checked against the packaged reflected schema. For an isolated route, add `"io_root":"/absolute/trusted/root"` when the I/O audit requires it. Read paths must be absolute and are recorded; every explicit write path must resolve inside that root, including through existing symlinks. Wwise-managed implicit outputs are disclosed as `implicit_write_confinement_proven:false` rather than falsely claimed to be physically confined. Custom CLI command fields such as `custom-pre-gen-cmd` and `custom-post-gen-cmd` are never accepted.

Undo Group members use a compound request instead of `waapi.call`:

```json
{
  "contract": "waapi-skill.operation-request/v1",
  "version": "2024.1",
  "operation": "waapi.undoGroup",
  "arguments": {
    "display_name": "Batch property update",
    "calls": [{
      "api": "ak.wwise.core.object.setNotes",
      "args": {"object": "{OBJECT-GUID}", "value": "Reviewed note"},
      "options": {}
    }]
  }
}
```

Obtain the current version's inner-call allowlist from `operation-schema waapi.undoGroup`; never guess it. The runtime validates the complete request and immutable execution plan before confirmation. If an inner call fails, it attempts `cancelGroup` on the same connection. `execution_cancelled` means that cancel returned successfully but rollback was not independently verified. Any uncertain begin/end/cancel outcome is terminal `indeterminate`, and no phase is automatically retried. Phase evidence has a 256 KiB aggregate ceiling and appears once, under `dispatch_result.result.phases`; an oversized inner result is reduced to a bounded failure record before same-connection cancellation.

If the requested target is not a valid direct writable parent for that object type, do not silently retarget the mutation. Report the structured container-suitability evidence and ask the user to confirm the intended writable child container before creating a new preview.

## Currently executable closed operations

- `waapi.call`: one exact version-reflected API plus reflected `args`/`options`; accepted only when the catalog transaction row explicitly lists `waapi.call` and no implemented dedicated operation owns that URI. It provides immutable policy-aware authorization, bounded dispatch, result-schema verification, isolated path auditing where applicable, and no model-authored code. It does not invent URI-specific business readbacks.
- `waapi.undoGroup`: one display name plus 1–32 version-allowlisted project-mutation calls. It keeps `beginGroup`, every inner call, and `endGroup`/`cancelGroup` on the same dispatcher and WAAPI client. It never retries, and successful verification proves reflected result shapes only—not that a rollback or final business state was read back.
- `lua.executeCliFile` (Wwise `2023.1`–`2025.1`) and `lua.executeCoreFile` (Wwise `2023.1`–`2025.1`) accept one absolute existing non-symlink `.lua` file canonically inside an existing `io_root`. `lua.executeCoreInline` exists only in Wwise `2025.1` and accepts one exact inline `lua_code` plus an existing `io_root`. `source_authority` is only a caller assertion in the request protocol; hashing can bind source bytes but cannot independently prove who authored or supplied them. Use `source_authority: "user_supplied_verbatim"` only when the current user message actually provides the complete source text or exact file path. Never generate, repair, wrap, augment, or hide Lua and then assert that authority. Optional `wa_args` is strict bounded JSON and cannot replace source/loader fields. CLI `watchdog_seconds` exists only in Wwise `2024.1`–`2025.1`. File size and SHA-256 are sealed and rebound before execution. Because `io_root` and source proofs describe the gateway filesystem, all three operations require an explicit loopback WAAPI host at preview and execution; a remote host returns `LOCAL_WAAPI_HOST_REQUIRED` before project or source-path access. These operations prove reflected result shape only; Lua effects are not inferred, confined, rolled back, or retried.
- `debug.setAsserts` and `debug.setAutomationMode` accept one explicit boolean in all five versions. Both alter process-wide behavior and follow the configured modification policy after immutable preview. Wwise exposes no state getter, and assert enablement is ref-counted, so verification proves only the reflected result schema and never claims a verified inverse or rollback.
- `debug.restartWaapiServers` (Wwise `2023.1`–`2025.1`), `debug.testAssert` (all five versions), and `debug.testCrash` (all five versions) are dedicated dangerous host-control transactions. Their exact acknowledgements are, respectively, `restart_waapi_servers`, `trigger_debug_assert`, and `crash_wwise_process`; an ordinary “yes” is rejected. After preview, wait for a later explicit user confirmation. Execution dispatches once and then records a terminal indeterminate state because neither a returned result nor a dropped connection proves delivery and lifecycle completion. Never retry, reconnect, run generic `verify`, or append a diagnostic command in that turn.
- `object.create`: one live-resolved writable `parent` plus a bounded recursive tree of `type`, `name`, optional `notes`, typed properties, live-resolved references, and children. An optional exact `platform` applies to the validated fields; an optional native `list` inserts below one proven list owner; `auto_add_to_source_control` is explicit and defaults to false. Conflict mode is `fail`, `rename`, `merge`, or guarded `replace`; `replace` requires a separate live `replace_owned_root`, an exact collision strictly below it, and a complete bounded old-subtree snapshot. `replace_owned_root` is the user's explicit reviewed authorization boundary; the Skill does not claim to have independently proved ownership of that root. Use the typed property/reference arrays instead of raw `@` keys. Plug-ins and RTPCs use their dedicated operations; caller-assigned internal GUIDs, Clips, Sequences, and Stingers are not exposed.
- `object.createPlugin` (`2022.1`–`2025.1`): one live-resolved `target` plus one closed `plugin` descriptor with `kind` (`source` or `effect`), exact `name`, and exact uint32 `class_id`; optional scalar properties are validated with classId-scoped live metadata. Source plug-ins are create-only children of a Sound or Voice and may include an exact non-empty `language` such as `SFX`. Effects reject `language`: Wwise `2022.1` uses the first proven-empty `@Effect0`–`@Effect3`, while `2023.1` and later append one `EffectSlot`. Never infer classId, replace an occupied Effect, add `replaceAll`, or express this work through raw `object.set`.
- `object.set` (`2022.1`–`2025.1`): one bounded batch of live objects with optional rename, notes, typed properties, live-resolved references, child trees, and closed `lists:[{"name":...,"objects":[...]}]` descriptors. Global `platform`, `list_mode`, and `on_name_conflict` defaults may be overridden per row; recursive child/list nodes may also carry their own `platform`, and new Sound Voice nodes may use an exact live Project `language`. In `2023.1`–`2025.1`, existing rows and recursive nodes may use a closed `import` with proved regular media or bounded inline WAV files, reviewed Originals subfolders, per-file `SFX`/live Project language, and an exact live-resolved object type. Imported Originals are hashed again and their requested language/type is read back. The complete canonical normalized request, including inline Base64 strings, is limited to 262144 bytes; this limit is exposed by `operation-schema object.set`. `list_mode` accepts `append` or guarded `replaceAll`, and `auto_add_to_source_control` is explicit. `replaceAll` seals the complete current list and every old member descendant, rechecks it before dispatch, then verifies the exact replacement and disappearance of the old GUID tree. Platform link state remains `object.setLinked`; plug-ins and RTPCs remain `object.createPlugin` / `object.setRTPC`. Caller-assigned internal GUIDs, raw dynamic members, and unverifiable merge-into-an-existing-list-member topology stay closed.
- `object.setLinked` (`2023.1`–`2025.1`): one live object, exact property/reference/list name, explicit platform, and Boolean link state. It requires live metadata support, reads the current link state before preview, and verifies the requested state through `object.isLinked`.
- `object.setRTPC` (`2022.1`–`2025.1`): one live object, exact property, one live ControlInput of an exact Game Parameter, MIDI Parameter, or supported Modulator type, and a bounded typed curve. It adds or updates exactly one matching RTPC without raw `replaceAll`, seals the complete RTPC list, and verifies the complete post-state.
- Evaluate the `object.set` exclusions before considering an existing-root `object.create` merge. Choose `object.set` when the request changes fields or references on existing roots, targets multiple existing objects, or appends below a nested container explicitly identified as already existing; any one condition locks that operation. Choose `object.create` for a new recursive root and also for one existing named root—but for the existing-root case, only after all three exclusions are absent and exactly one same-name root remains unchanged while the request only merges a recursive descendant tree. Keep the existing parent as `parent`, repeat the root's exact `type` and `name`, and use `on_name_conflict: "merge"`. For `object.set`, every existing target—including each nested container receiving descendants—gets its own `objects[]` row, and that row's `children` contains only genuinely new direct children. For one isolated rename, notes edit, property edit, or reference edit, prefer the narrower `object.setName`, `object.setNotes`, `object.setProperty`, or `object.setReference` operation.
- For `object.set`, `on_name_conflict` governs only genuinely new child names. Existing `objects[]` targets never imply `merge`; use `fail` when those requested children are new or absent, and use `merge` only when the user explicitly asks to merge a same-name collision for a new child.
- For `Pitch`, Wwise WAAPI property values are cents. Translate a user's semitone value deterministically before preview (`1 semitone = 100 cents`, so `-2 semitones = -200`); never pass the semitone number itself as the raw property value. Keep other units exactly as returned by live property metadata.
- `object.delete`: one non-protected `object`; Project roots and default work units are rejected. `auto_check_out_to_source_control` is an optional Boolean in Wwise `2023.1`–`2025.1` and otherwise fails before connection; omission deterministically dispatches `false` in supported lanes.
- `object.setName`: one `object` and non-empty `value`.
- `object.setNotes`: one `object` and string `value`.
- `object.setProperty`: one `object`, `property`, and `value`; property metadata is queried live. An optional explicit `platform` is accepted only after `isPropertyEnabled` and is used for both pre-state and typed verification.
- `object.setReference`: one source `object`, `reference`, and explicit `target`; a non-null target is live-resolved and checked against live reference restrictions, while `target: null` requests a closed reference clear and is rejected when live metadata marks the reference `notNull`. An optional explicit `platform` is used for the enablement check, pre-state, dispatch, and verification. Clearing is verified only when readback exposes null (or the canonical null GUID), never from an unidentifiable non-null value.
- `ui.captureScreen`: a version-stable screenshot operation for all five lanes. The closed request maps `view_channel` to Wwise `2021.1`'s `viewSyncGroup` or later versions' `viewSelectionChannel`, and verifies the returned bounded image content instead of accepting an arbitrary UI payload.
- For `ak.wwise.ui.commands`, do not begin a modifying request with the default Console-profile `describe`. Begin directly with `operation-schema ui.commands.execute`, `ui.commands.register`, or `ui.commands.unregister`; an inventory request uses the bounded live `call ak.wwise.ui.commands.getCommands`, and an executed-command observation uses bounded `wait-topic ak.wwise.ui.commands.executed`. The gateway derives the host profile from live `getInfo.isCommandLine` and accepts no caller-controlled Authoring override; WwiseConsole returns `AUTHORING_HOST_REQUIRED` before business dispatch.
- `ui.commands.execute`: Authoring-only command execution for all five versions. It accepts one bounded command ID plus reviewed objects/platforms/value fields; Wwise `2025.1` alone also accepts up to 64 existing, non-symlink regular files whose path, metadata, and SHA-256 are rebound immediately before dispatch. The `files` form requires a loopback WAAPI endpoint at preview and execution because local proofs cannot establish remote-host file identity. A fresh live `getCommands` read must contain the ID. The generic command effect has no universal inverse or business readback, so verification proves only the reflected empty result schema and never claims the GUI/project effect succeeded.
- `ui.commands.register`: Authoring-only registration of up to 32 closed notification, program, or version-allowed Lua descriptors. Program/Lua descriptors use immutable executable/script/directory proofs; they require `source_authority: "user_supplied_verbatim"`, which is a caller assertion rather than runtime provenance proof, and require a loopback WAAPI endpoint at preview and execution. A Program descriptor must name its final proved executable directly. Shells, `/usr/bin/env`, generic interpreters, launchers, loaders, and command prefixes are rejected, and its `argument_tokens` must be empty. Any parameterized Program execution must wait for a dedicated closed adapter; the generic descriptor cannot delegate an unproved script, subcommand, database expression, remote command, or other payload through arguments. Never create a wrapper to evade this boundary. The platform comes only from live `getInfo.platform`: `x64`/`win32` map to `windows`, `macosx` maps to `macos`, and any other or missing value fails closed. The registered IDs must be absent immediately before dispatch and present in a fresh live `getCommands` result afterward. Its sealed unregister cleanup companion becomes actionable only after that exact register transaction executes and verifies successfully.
- `ui.commands.unregister`: Authoring-only removal with exactly one of two request forms. Descriptor-backed mode supplies `commands` plus `source_authority` only when a Program/Lua descriptor requires it; existing-ID mode supplies `command_ids` plus the exact `acknowledgement: "unregister_existing_commands_without_definition"`. Mixing those forms is rejected. A descriptor-backed request containing local Program/Lua paths requires the same loopback endpoint boundary as registration; the existing-ID form contains no local path proof. Both standalone forms record ownership as unknown and have no inverse registration cleanup. Descriptor-backed mode uses the same live platform mapping and seals the supplied descriptors and path proofs only as the requested deletion definition; `getCommands` proves ID membership but neither the live definition nor who registered it. Never turn a descriptor set or sealed register preview into a reversible unregister. Reversibility is available only through the journal-bound cleanup companion of a successfully executed and verified earlier register transaction.

### Local WAAPI endpoint boundary

Filesystem proofs and artifact snapshots are made by the gateway process. Therefore `audio.import`, `audio.importTabDelimited`, `soundbank.generate`, `soundbank.convertExternalSources`, `soundbank.processDefinitionFiles`, all three `lua.execute*` operations, `object.set` when any recursive node imports audio, `ui.commands.execute` when `files` is present, and Program/Lua register or descriptor-unregister requests require a loopback WAAPI endpoint. Every generic `waapi.call` assigned to the versioned `isolated_transaction` route is conservatively local-only as well, even when a particular request has no explicit path field. The boundary runs before project reads or local path proof during preview and before proof replay or business dispatch during continuation. Only `localhost` or a literal loopback IP address is accepted; no DNS alias is treated as proof of locality. The named `ui.captureScreen` adapter holds bounded image data in memory and remains remote-capable.
On `LOCAL_WAAPI_HOST_REQUIRED`, report the boundary and stop. Never reinterpret a local hash, directory proof, or isolated-I/O policy as evidence about a remote Wwise host.
- `audio.import`: one or more closed rows with `object_path` plus exactly one of an absolute regular `audio_file`, bounded `audio_file_base64`, or an explicit object type for structure-only creation. Rows may supply a live-resolved `import_location`, object type, language, Originals subfolder, object/source notes, structured Event, native Dialogue Event/Switch Assignation directives, and typed property/reference arrays. A closed call-wide `defaults` object is merged into rows before sealing; after that expansion, all canonical `audio_file_base64` strings together are limited to 262144 encoded characters. This request-wide bound is exposed by `operation-schema audio.import`, keeps one maximum-size inline WAV available, and rejects an oversized aggregate before dispatch. `auto_add_to_source_control` is explicit. Property/reference names and values are validated against live metadata, materialized as trusted native `@` members, and read back. A structured Event must use one absolute, previously absent, row-unique path below `\Events`; relative Event paths and appending an Action to an existing Event remain closed. References whose live metadata contains `childOfReference` also remain closed because they require an ordered operation. The call-wide mode is `createNew`, `useExisting`, or `replaceExisting`. Preview hashes every source and captures every target; verification checks exact topology, requested fields, GUID preservation/replacement semantics, copied media hashes, Event structure, and the version-specific result/log shape. Dialogue/Switch directives retain an explicit weaker side-effect-verification boundary when Wwise exposes no complete reconstruction.
- `audio.importTabDelimited`: one absolute UTF-8 tab-delimited file, one live import location, one call-wide language, and `createNew`, `useExisting`, or `replaceExisting`. In addition to ordinary object/media fields, the parser accepts bounded `Audio File Base64`, repeated Event, Dialogue Event, Switch Assignation, `@Property`, `Property[...]`, and `Reference[...]` column families, including structure-only typed rows. Property/reference columns use canonical metadata tokens; display-name aliases such as `Reference[Output Bus]` are not accepted as equivalent native headers, and references constrained by `childOfReference` remain closed. Every row requires a non-empty `Object Path`; native blank-path inference from the media filename is not exposed. A regular `Audio File` cell must be an absolute proved path rather than a path relative to the TSV. Every Event column uses the same absolute, previously absent, row-unique Event boundary as direct import. Dynamic fields are validated against live metadata before dispatch, every referenced regular media file is hashed, and the whole table is rejected on any invalid row. Each cell must be one physical field: literal tab, CR, or LF separators are not allowed inside cell content, and CSV-style quoting does not escape those Wwise separators; preview fails closed before dispatch. `auto_add_to_source_control` is explicit. Verification covers every resulting object, media source, typed property/reference, and Event; Dialogue/Switch directives use the same explicit weaker side-effect boundary as direct import. It is available in all five supported versions.
- A request that calls a table or batch an SFX import supplies the exact language already: map it directly to `import_language: "SFX"`. Do not ask the user to repeat that language and do not query the Project language inventory for it.
- For both import operations, `SFX` is Wwise's built-in non-localized import token, not a row in the Project language inventory. Preserve the literal `SFX` dispatch value without requiring it from `ak.wwise.core.getProjectInfo`; validate only explicit non-SFX language names. A mixed batch containing `SFX` and localized rows validates only the localized names.
- `useExisting` is decided per row even though it dispatches once. For a non-SFX localized row whose exact target already exists, send only `audio_file`, `object_path`, `import_language`, and the live-preflighted `object_type`; omit `notes`, `audio_source_notes`, `originals_subfolder`, and `event` for that row. This omission rule never applies to `SFX`: even when an SFX target already exists, preserve every optional field the user supplied for that row. A missing target in the same batch is a creation row: preserve every such optional field from its reviewed manifest instead of deleting those fields from the whole batch.
- `originals_subfolder` is relative to the normal destination Wwise selects for that import language. For an SFX row, `Foley/Footsteps` therefore produces `Originals/SFX/Foley/Footsteps`; do not prepend `SFX/` merely to name the language. A caller's literal `SFX/Foley/Footsteps` would instead request the distinct nested path `Originals/SFX/SFX/Foley/Footsteps`, so never silently strip that prefix.
- `soundbank.generate`: an explicit bounded list of SoundBanks, platforms, language policy, and an isolated `io_root`. Every Bank must declare `artifact_expectation` as `nonlocalized`, `localized`, or `mixed`; verification then requires, respectively, the platform-root artifact, every explicitly selected language artifact, or both sets. Event/AuxBus descriptors resolve live; confirmation rechecks project and output-tree guards; verification requires every expected artifact to be newly created or modified and non-empty, and rejects error/fatal results. On Wwise `2021.1`, the gateway reads the live Project object's `filePath` and `workunitIsDirty`, requires the localized `.wproj` to stay inside `io_root`, hashes and strictly parses its project identity, platforms, languages, output/cache paths, and default conversion, and rejects unknown or non-default generation hooks. It repeats that live read and file proof at confirmation. Do not supply a project layout. Later versions bind live `core.getProjectInfo` evidence.
- `soundbank.convertExternalSources` (`2022.1`–`2025.1`): strict hashed `.wsources` documents, explicit platforms, and distinct output roots inside one `io_root`. Derive `io_root` as the deepest common absolute ancestor of every stated `.wsources` input path and output directory; if that ancestor is only the filesystem root, stop and ask for one narrower common root. Every source WAV and derived WEM path is proven before preview; verification requires every exact non-empty output and rejects partial or unexpected output.
- `soundbank.processDefinitionFiles` (`2022.1`–`2025.1`): strict hashed UTF-8 SoundBank Definition TSV files. Use the user's stated absolute allowed file root exactly as `io_root`; never synthesize a broader root from the definition-file paths. Every referenced object and target bank is resolved before preview; processing is additive for an existing Bank, so verification checks its preserved GUID and the exact additive post-state formed from pre-existing and file-derived inclusions, plus an unrelated control Bank.
- `soundbank.setInclusions`: one live `soundbank`, `mode` (`add`, `remove`, or `replace`), and inclusion rows containing one live `object` and unique `filters` from `events`, `structures`, and `media`. `add` upserts the requested object's complete filter row while preserving other objects; it does not union filters with an existing row. `remove` is accepted only when the requested filter row exactly matches live state, then removes that object inclusion. `replace` sets the complete list and may use an empty list for an exact clear. Preview captures the complete normalized state; execution and verification require exact full-state transitions.
- `switchContainer.addAssignment` and `switchContainer.removeAssignment`: one live `switch_container`, direct `child`, and `state_or_switch`. Preview proves the container type, direct-child relation, bound Switch/State Group, group membership, and complete assignment pre-state; verification proves the exact complete assignment post-state, unchanged group reference, and unchanged object relationships. The closed add policy rejects a child that already has any assignment instead of guessing whether reassignment was intended.

Run `operation-schema <name>` directly for a named operation instead of relying on this list. Use compact `operations` only when the user asks for the broad operation inventory; use `operations --detail` only when the entire nested catalog is itself the requested artifact. Semantic names such as `object.copy` and `object.move` may still report that their richer operation-specific verifier is incomplete. That boundary does not authorize code generation. Outside the reviewed direct fast routes above, use an underlying URI only when `describe <underlying-uri>` reports a packaged `transaction_operation`, and then use its exact declared transaction operation. This is `waapi.call` only for rows with no implemented dedicated operation; the three Undo Group members declare only `waapi.undoGroup`. Disclose result-schema-only verification whenever no operation-specific readback exists.

### Closed workflow request shapes

Obtain the exact machine-readable nested fields from `operation-schema`; these examples show the intended level of input, not an invitation to add raw WAAPI fields.

```json
{
  "contract": "waapi-skill.operation-request/v1",
  "version": "2024.1",
  "operation": "audio.import",
  "arguments": {
    "imports": [{
      "object_path": "\\Actor-Mixer Hierarchy\\Default Work Unit\\<Sound>Footstep",
      "audio_file": "/absolute/path/Footstep.wav",
      "object_type": "Sound",
      "notes": "Imported through the WAAPI Skill transaction gateway"
    }]
  }
}
```

For Wwise `2025.1`, authored audio lives below `\\Containers`; for `2021.1` through `2024.1`, use `\\Actor-Mixer Hierarchy`. `\\Interactive Music Hierarchy` remains a separate authored-music root. Do not translate one root into another silently.

```json
{
  "contract": "waapi-skill.operation-request/v1",
  "version": "2024.1",
  "operation": "soundbank.setInclusions",
  "arguments": {
    "soundbank": {"kind": "path", "value": "\\SoundBanks\\Default Work Unit\\Main"},
    "mode": "replace",
    "inclusions": [{
      "object": {"kind": "id", "value": "{OBJECT-GUID}"},
      "filters": ["structures", "media"]
    }]
  }
}
```

```json
{
  "contract": "waapi-skill.operation-request/v1",
  "version": "2024.1",
  "operation": "switchContainer.addAssignment",
  "arguments": {
    "switch_container": {"kind": "id", "value": "{CONTAINER-GUID}"},
    "child": {"kind": "id", "value": "{CHILD-GUID}"},
    "state_or_switch": {"kind": "id", "value": "{SWITCH-GUID}"}
  }
}
```

## Invariants enforced by the runtime

- A preview artifact is write-once; its full SHA-256 remains in the structured Gateway result for integrity checks and explicit diagnostics, not ordinary confirmation prose. `ask_before_changes` binds it into the Gateway-owned confirmation token, while `allow_changes` binds a distinct durable policy-authorization event.
- Normal confirmation accepts a transaction id and the exact short token returned by `transaction-show`; the token binds the stored artifact and transaction state, and confirmation does not accept replacement JSON.
- Execution reloads the immutable dispatch, checks preview expiry, verifies the live Wwise version/project/endpoint, verifies the packaged implementation digest, and re-reads every canonical GUID role before mutation.
- A target, project, runtime, or pre-state drift becomes `repreview_required` before any mutation.
- The public generic `call` route cannot execute a mutation, even with `--allow-destructive` or `WWISE_DESTRUCTIVE=1`.
- Once state reaches `executing`, the mutation is never automatically retried. A lost/ambiguous result becomes terminal `indeterminate`.
- Except for `ak.wwise.cli.migrate`, successful dispatch normally becomes `executed_unverified`; it is not terminal until `verify` reaches `verified`, `result_schema_checked`, or an explicit failure/indeterminate state. Migration instead treats its one complete `execute` JSON as terminal Skill evidence because only the caller-owned reopened-project oracle can prove the migrated project. If WAAPI succeeds but the local completion journal cannot be written, the response is `execution_succeeded_persistence_failed`, preserves `executed: true`, the dispatch and cleanup evidence, and `automatic_retry: false`; never replay that mutation.
- Dedicated semantic operations use operation-specific readback. Generic `waapi.call` normally verifies the returned value against the packaged reflected result schema and must not be described as live business-state proof. The migration route is excluded from that generic verification step: do not run `verify` even when execute reports `executed_unverified`. For other routes, a transient read-only verification error returns `verification_deferred`, keeps `executed_unverified`, and permits a later manual `verify`; it never re-executes the mutation.
- Except for migration's terminal `execute`, the `verify` payload is the terminal authority for the selected contract: dedicated operations contain live readbacks, while generic `waapi.call` and `waapi.undoGroup` contain reflected result-schema assertions. After any terminal verification response, stop that transaction. In a previously closed multi-transaction workflow, apply the current policy to the next item only after the prior item terminates. Never append `query-object`, direct `call`, or another gateway command to double-check the same result. For migration, the complete execute payload is the terminal authority inside the Skill command sequence and must not be followed by any gateway command.
- Successful preview and successful terminal `verified` or `result_schema_checked` responses expose `agent_result`. For a machine-readable answer, serialize only that exact object without reconstruction or an extra command. A terminal migration execute may intentionally have no successful `agent_result`; report its complete actual state and caller-owned verification boundary instead of running `verify` or fabricating a projection. Failure, `verification_deferred`, `verification_failed`, `execution_cancelled`, `execution_succeeded_persistence_failed`, `repreview_required`, and `indeterminate` responses do not expose a successful projection; never fabricate one. Natural-language reporting still uses the complete gateway payload and its evidence rather than discarding readback, assertions, risks, or cleanup details.

For `object.create`, verification binds every returned GUID to the requested recursive topology and reads back all requested notes, typed properties, and references. Guarded replace also proves every captured old-subtree GUID absent and never claims an in-place rollback; tests discard the case-owned project copy. `object.createPlugin` seals the complete relevant plug-in placement pre-state before dispatch. It rejects a reused `2023.1`+ EffectSlot, proves the selected Wwise `2022.1` `@EffectN` reference or later slot `@Effect` binding, and reads back the plug-in's exact identity, owner/parent topology, requested notes/language, and typed properties using the sealed platform/language view. Any missing, ambiguous, pre-existing, or mismatched evidence fails verification. `object.set` captures every target and field pre-state, reads every updated target back independently, and requires every appended or merged child returned by Wwise to match the reviewed topology exactly. Delete proves GUID absence. Rename proves the same GUID, new name/path, unchanged parent, and old-path absence. Notes are exact. Numeric properties use typed tolerance. References must normalize to the target identity or return an explicit indeterminate boundary.

For both import operations, every input file is bound by absolute canonical path, size, and SHA-256 at preview and re-hashed before execution. `createNew` requires exact target absence, `useExisting` preserves each existing GUID while allowing missing targets to be created, and `replaceExisting` proves every old GUID absent and each replacement GUID different. Error/fatal logs, missing rows, wrong copied-media hashes, or unexpected target state fail verification. SoundBank generation/conversion binds source and output artifact trees; Definition processing requires the exact additive post-state, while SoundBank inclusion operations require their exact requested set algebra. Switch assignment operations re-read their complete normalized pre-state immediately before dispatch and require exact post-state evidence.

Some managed calls open resources that need a later packaged companion: bank load/unload, Game Object register/unregister, Profiler capture start/stop, meter register/unregister, Remote connect/disconnect, Transport create/destroy, and Authoring UI command register/unregister. Their immutable cleanup spec is preserved in preview, execute, verify, `transaction-show`, and `agent_result`: opener preview is `not_started`, successful execution/verification is `pending`, and an ambiguous execution is `unknown`. Transport destroy binds only to the validated ID returned by create. A successful closed UI registration retains its exact unregister cleanup companion. Both standalone UI unregister forms have unknown ownership and no inverse; neither descriptors nor an arbitrary existing-ID list can recreate one. A closer has `not_required` for any further cleanup. Work Unit load/unload is reported separately as `available_reversal`, never required or automatic cleanup, because either action clears Undo history and unload can fail with unsaved changes. Undo Group cleanup occurs only inside its same-connection composite. Do not hide the cleanup obligation or uncertainty, but explain it in natural language without raw state labels unless the user requested diagnostic data. Never replace a companion with code; use a separate packaged transaction under the configured policy when the user's workflow reaches an actual cleanup obligation.

## Result handling

The labels below are internal routing, not normal user-facing copy. In ordinary prose, translate them into the business outcome, uncertainty, or next decision; expose exact labels and transaction metadata only for an explicitly requested raw, machine-readable, or diagnostic result.

- `awaiting_confirmation`: show a concise human preview with every requested target/value, expected result, and decision-relevant conflict, risk, verifier limit, or cleanup obligation. State explicitly that execution has not happened, omit the internal identifiers and continuation data named above, and then wait. On a later explicit confirmation, obtain a fresh `transaction-show` result and copy its token-bearing `next_command.shell_command` exactly.
- `policy_authorized`: the immutable preview is authorized by the current `allow_changes` policy, not by an explicit confirmation. Tell the user what is about to change, then use the exact returned `execute` command while that policy remains current.
- `confirmed`: confirmation was token-bound to the immutable artifact and current transaction state; execution has not happened.
- `executed_unverified`: normally run `verify`, not `execute` again. If the immutable request targets `ak.wwise.cli.migrate`, this state is terminal for the Skill: stop after the complete execute payload, do not add a gateway inspection, and defer final proof to the caller-owned reopened-project oracle.
- `verified`: report the completed business change, every requested target/value, and the actual readback evidence from this payload, then stop without an extra query. Keep internal identifiers and state labels out of ordinary prose. In an original closed multi-transaction workflow, apply the configured policy to the next item only after this terminal result. Never let a negated or failed execution/verification message sound like completion.
- `result_schema_checked`: the reflected return shape passed, but business state was not independently verified. Report that weaker evidence and stop without an extra query.
- `execution_cancelled`: same-connection `cancelGroup` returned successfully after an Undo inner failure; rollback remains unverified, and the transaction must not be retried.
- `execution_succeeded_persistence_failed`: WAAPI returned success but the local completion journal did not. Preserve the returned execution and cleanup evidence, never retry automatically, and repair or inspect the transaction store before any later manual decision.
- `verification_failed`: report which assertion failed; do not claim completion or retry mutation.
- `verification_deferred`: a read-only verification attempt failed; a later manual `verify` is safe.
- `repreview_required`: live state changed before execution; create a new preview.
- `indeterminate`: execution may have reached Wwise. Stop the current turn immediately after the complete execute JSON; do not call `verify`, retry, run another gateway command, inspect files, or perform any other follow-up check. Explain that the action may have reached Wwise and its outcome cannot currently be confirmed, then ask the user how to proceed. Any later diagnosis requires a new user request and a packaged read-only Skill route. For migration, only the caller-owned lifecycle and reopened-project oracle may inspect the result outside the Skill sequence.
- `unsupported_boundary` / `OPERATION_BOUNDARY`: report the packaged interface gap. Do not write code to bypass it.

For a requested `WAAPI_RESULT_JSON=<json>` answer, when the successful preview or verified payload contains `agent_result`, the `<json>` portion is the compact serialization of that object verbatim in structure and values. Do not copy fields manually; this preserves backslashes, quotes, Unicode, numeric types, and the immutable request binding.

Only the explicit catalog exclusions and route-specific input policies are interface boundaries. Model-authored or hidden Lua, unrestricted Lua loaders, unrestricted UI command registration/execution, custom external command hooks, and cross-app MCP federation are never substituted for a packaged route. Explicit user Lua and private debug APIs use only the closed routes described above.

<!-- WAAPI_OPERATE_REFERENCE_END -->
