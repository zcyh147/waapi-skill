# WAAPI query lane

Use this for read-only Wwise queries and bounded Topic waits/streams. Require the unique terminal sentinel required by `SKILL.md` as the final visible line and no truncation or omission marker; otherwise do not reread a range or invoke the Gateway.

## Routing and boundaries

- Use only the packaged Gateway. There is no raw-client fallback and do not write Python.
- Use fixed routes directly: object reads use the business declaration from `query-schema`; Topic facts use `topic-schema`; non-fixed reflected functions use `request-schema <uri>` and its sole continuation. Topic observation never authorizes its publisher.
- Broad catalog: `capabilities --all-versions --summary-only`, then narrow with filters. It returns at most 50 compact rows by default. Use `--limit 0` only when every row is explicitly needed and `--detail` only for audits.
- Known URI: `describe <uri>`. Add `--full-schema` only when the complete reflected schema is required.
- `API_NOT_FOUND`, `MANIFEST_NOT_FOUND`, `FIXED_COMMAND_REQUIRED`, `QUERY_OBJECT_REQUIRED`, `WAIT_TOPIC_REQUIRED`, `TRANSACTION_REQUIRED`, and `UNSUPPORTED_BY_SKILL_INTERFACE` (`unsupported_by_skill_interface`) are boundaries; connection errors, invalid responses, and rejected continuations also stop the workflow.
- The configured exact Wwise version selects every schema. Live work never copies an example `--version`; use it only for a requested offline inspection.

## Wwise 2025.1 Media Pool

`ak.wwise.core.mediaPool.getFields` and `.get` are one closed two-call read. Use `request-schema` for each URI and follow only its typed continuation. Run `request-schema ak.wwise.core.mediaPool.getFields` before `request-schema ak.wwise.core.mediaPool.get`; Do not request the `.get` schema first.

Exact standard bindings are name/file -> `Filename`, duration -> `WAV/Duration`, sample rate -> `WAV/Sample Rate`, bit depth -> `WAV/Bit Depth`, and channels -> `WAV/Channels`. `Filename` omits extension; use `Path` when it matters. Bind custom fields only from the live field result and stop on missing/ambiguous binding.

Args contain only `databases`, `filters`, and `maxResults`. Preserve database and predicate order. Each filter is `{"type":"field","field":<bound field>,"operator":<operator>,"value":<value>}`. `contains` takes literal text, never regex syntax or inline modifiers. Convert Between/from A to B into two ordered bounds. Use the user's maximum, else 100; range is 1–200. For a case-sensitive requirement, use the `result_filter` fields disclosed by `request-schema`; the Gateway returns `MEDIA_POOL_POST_FILTER_INCOMPLETE` when a saturated candidate set cannot prove completeness.

The return list starts with `Path`, `FileId`, `Db`, `Filename`, `WAV/Duration`, `WAV/Sample Rate`, `WAV/Bit Depth`, `WAV/Channels`; append only explicitly needed live fields, without duplicates. Preserve returned `Db` and complete `Path`; never run the old unfiltered 1000-row AudioFileSource projection and never perform this join in model-authored code.

### Closed original-file reference classification

This is Wwise `2025.1`-only and follows a successful Media Pool read. Run only for between 1 and 64 candidate rows. With zero candidates report empty. With more than 64 report the candidate-limit boundary; do not silently truncate, split the candidates across repeated scans, or choose a subset.

Take each exact returned `Path`, sort those strings lexicographically, and pass each once. Each path is limited to 1024 UTF-8 bytes and must be drive-absolute, an ordinary UNC path, or POSIX-absolute. Reject relative/traversal/device paths. Do not pre-normalize or de-duplicate: the Gateway normalizes slash spelling and drive/UNC case, keeps POSIX case significant, and rejects normalized candidate collisions.

Invoke one command, repeating only the final candidate option:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2025.1 query-object --max-results 1000 --match-original-file-path '<first-complete-returned-Path>' --match-original-file-path '<second-complete-returned-Path>'
```

Do not add predicates, relationships, or extra business outputs. The fixed `id,path,originalFilePath` projection performs the complete join and emits no raw AudioFileSource inventory.

Success keeps `agent_result` as its final top-level field with `waapi-skill.original-file-reference-match/v1`, `scan_complete: true`, `scanned_audio_source_count`, `scan_limit: 1000`, and one `candidates` entry for every input path in the same order. Each includes the exact full-scan `reference_count` and at most four `{id,path}` details, sorted by path case-insensitively and then id case-insensitively. `references_truncated: true` means only that detail list was shortened. An unreferenced entry has count `0`.

Classify only when the outer command succeeds and the terminal result says `scan_complete: true`. A 1000-row scan returns `ORIGINAL_FILE_REFERENCE_SCAN_INCOMPLETE` with no `agent_result`. Any malformed row/path, duplicate id, normalized candidate collision, or WAAPI boundary proves no unreferenced claim. Stop instead of retrying with a broader query, another batch, direct `WaapiClient`, inline Python, or a helper file.

## Object queries

One Gateway-owned business declaration chooses exactly one source: repeated `--path-segment`, `--exact-id`, closed `--kind`, live-resolved `--custom-kind`, `--search-text`, `--query-id`, or repeated `--query-path-segment`. Never reconstruct a Wwise path separator, type discriminator, accessor, or relationship token. The Gateway constructs the exact Wwise path and separators from literal hierarchy names. A custom-kind miss/ambiguity uses returned candidates; never invent a type.

Repeated `--predicate BUSINESS_CONDITION VALUE` means flat AND. Repeated `--relationship` selects `descendants`, `ancestors`, `references-to`, `children`, or `parent`. A broad/expanding source requires the user's `--max-results`; there is no unbounded mode. `all-sounds`/`sound` includes SFX and Voice; use `sound-sfx` or `sound-voice` only for that explicit scope. With another source, type is `--predicate kind-is`, not a second source.

The fixed identity projection is always present: `id,name,type,path`. Add report data through repeated `--include` values in caller order; custom live fields use `--include-field` and appear in custom `properties` and `references` maps. Missing/ambiguous metadata uses the structured repair, never a token guess.

The offline version-aware schema command is:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version <supported-version> query-schema
```

Success rows are objects in the array; only an explicit empty array is empty. Over-bound, malformed, or truncated results are not empty. Ordinary `query-object` success defaults to compact business fields, sufficient for normal answers. Use `--detail` only for explicit user requests or compile/dispatch diagnosis; never rerun solely for detail. Failures skip compact projection but obey global limits. Keep terminal `agent_result` exact and final.

```bash
python scripts/run.py gateway.py query-object --path-segment 'Events' --path-segment 'Default Work Unit'
python scripts/run.py gateway.py query-object --search-text 'ExactName' --predicate name-is ExactName --max-results 1
python scripts/run.py gateway.py query-object --path-segment 'Actor-Mixer Hierarchy' --path-segment 'Default Work Unit' --path-segment 'Combat' --relationship descendants --predicate kind-is all-sounds --max-results 24
```

Repeated `--predicate` values mean AND and preserve user condition order. A pure-AND mix query includes every supported conjunct before the bound; presentation sorting/grouping happens only after a complete result.

### Relationship-guided next hops

`Target`, `activeSource`, `OutputBus`, and `parent` are relationship objects. Only `Target.id`, `activeSource.id`, `OutputBus.id`, or `parent.id` is next-hop identity. Require a canonical braced GUID; stop if missing or malformed. Query that GUID directly; do not reread the current row or search by name or path. Gateway target/role revalidation still runs during preview/execute/verify. Preserve first-returned order, de-duplicate the GUIDs, and query each distinct GUID exactly once in a separate `query-object --exact-id`; never merge IDs.

A relationship display `name`, including `OutputBus.name`, never proves an absolute path. If a rule gives an absolute Bus path, exact-ID query every distinct `OutputBus` GUID for `id`, `name`, `type`, and `path`; compare returned `path`, never `name` with its final segment.

If a broad ordinary or advanced query returns multiple candidates and the user selects some to change, run `query-object --exact-id` on each selected GUID and match `id`, `name`, `type`, and `path`. Never reread unselected rows; relationship read hops are exempt. An advanced-WAQL candidate needs an exact choice and the simple exact-id readback. The exact-ID readback must match or stop. Raw WAQL itself is never a mutation identity.

### Advanced native WAQL fallback

When ordinary business fields cannot express skip/order/distinct/regex/list/nested logic, run:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version <supported-version> query-schema --advanced
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py query-object --advanced-waql '<bounded-single-line-waql>' --include <business-field> --max-results <1..1000>
```

The Gateway fixes read-only `ak.wwise.core.object.get`, projection, final take, timeout, bytes, and grammar. Limits are UTF-8 bytes (not character counts); WAQL is trimmed and single-line, without Query Editor `$`, comments or statement separators, or an unclosed double-quoted string or slash-regex literal. On rejection, report it; never alter-and-retry. There is no generated-code fallback.

Final take bounds returned rows, not internal scans; even a one-row result does not prove uniqueness. Never feed an advanced result directly into a mutation. Present candidates, obtain their exact choice, then use the simple `query-object --exact-id` route. A mismatch means the workflow stops for a new choice. Candidate displays keep unaliased identity fields; never alias another advanced expression onto them.

### Bounded inventories

Use the business declaration for one source and flat AND. Use advanced only for a native read-only construct absent from that schema. Plan one bounded request and apply presentation logic only to its complete result.

- The Agent names `volume-db`, `pitch-cents`, `output-bus`, `source-language`, and other business fields. The Gateway owns case-sensitive Wwise accessors and shell quoting. Output order is fixed identity first, then repeated includes, then custom maps.
- Repeated `--predicate` values mean AND; preserve the user's condition order. Do not submit only a type condition. With nested boolean logic, use the advanced exact-WAQL lane. `isIncluded` is appended last because it is filter-only.
- “Shared” applies to the complete final row set. For parent containers together with their direct child Sounds, omit a `type=Sound` or container-only predicate; fetch one bounded mixed-type descendant set with `--include parent`, or it would erase one required side of the relationship.
- Sound language is proven when exactly one returned `AudioFileSource` has `parent.id` exactly equal to that Sound's `id`. Do not report the language as missing when this exact child-source evidence exists; do not associate by row position, similar names, or path prefixes.
- For "from the Sounds, find their direct parents", use `--kind all-sounds --relationship parent`. Predicates then describe the selected parent rows; Do not replace this with a descendant inventory. The result has one returned parent row for each matching source object. Count those rows before deduplicating. Treat `childrenCount` only as the number of all direct child objects; never relabel its value or a sum of it. At the bound, report that confirmed source count and say the result may be incomplete.
- For an ownership chain from one exact object, use `--relationship ancestors`; do not assume the relationship removes Project. Return nearest parent to farthest ancestor without mixing same-name objects from other branches.
- For relative depth, derive depth from each returned `path`, counting the root's direct children as relative depth 1; do not add `parent` solely to calculate relative depth. Request `parent` only when the user needs a parent identity or a direct parent-child relationship.
- When the user supplies a maximum, copy that exact number to `--max-results`. Otherwise ask for a limit instead of inventing one.

For example, a bounded descendant inventory of Sound candidates:

```bash
python scripts/run.py gateway.py query-object --path-segment 'Actor-Mixer Hierarchy' --path-segment 'Default Work Unit' --path-segment 'Combat' --relationship descendants --predicate kind-is all-sounds --max-results 24
```

Pure AND:

```bash
python scripts/run.py gateway.py query-object --predicate kind-is all-sounds --predicate volume-db-at-most -6.0 --predicate notes-contain mix-review --predicate included-is true --max-results 12 --include volume-db
```

Direct parents:

```bash
python scripts/run.py gateway.py query-object --kind all-sounds --relationship parent --predicate kind-is random-container --predicate children-at-least 3 --predicate notes-contain parent-review --max-results 10
```

Ownership:

```bash
python scripts/run.py gateway.py query-object --exact-id '{GUID}' --relationship ancestors --max-results 8
```

## Object types, metadata, and fixed reads

Use offline version-pinned `object-types` first; narrow its bounded result. Use live `metadata types` only to re-reflect the running instance; its projection and bound are fixed.

`metadata discover` chooses one scope and repeat `--meaning` for one to eight short English phrases. Gateway owns detail level, search bounds, projection, metadata tokens, and cache scope. Complete `no_match` is a bounded miss; one `partial` result permits one broader technical retry, then clarify. Honor dependencies when authorized, otherwise clarify.

Use fixed reads rather than reflected payloads:

- `profiler-game-objects`: bounded capture; 2022.1–2025.1.
- `profiler-voice-contributions`: all versions; one Voice object GUID and optional game-object/Bus object GUIDs. Gateway resolves volatile pipeline IDs.
- `project-default-work-units`: bounded default Work Unit facts.

Each returns its stable `agent_result`; do not rebuild it. Remaining reflected reads use `request-schema <uri>` and its exact continuation.

## Exact-hop playback diagnosis

Resolve the exact Event once, then execute its copy-ready `event-actions`
continuation; Gateway owns the child hop, bound, `action_type`, and `target`.
Execute its copy-ready `--view sound-routing-diagnostics` continuation exactly;
do not re-query the Action or hand-build Sound fields.

The view returns `override_output`, `active_source`, and ends at `output_bus`;
do not add `volume-db` to the Sound hop. Read file/language from the exact
`active_source`. For routing versus mute, request `volume-db` only on the exact
Bus identities: first the returned `output_bus` id, then the requested
comparison Bus path or id. Never omit it from the comparison Bus.

## Topics and Authoring-only reads

`wait-topic` accepts one reviewed URI and 1–64 matches. An ordinary omitted duration uses 10 seconds; tell the user. A user-supplied positive finite duration is authoritative: convert its units to seconds without rounding and place global `--timeout` before the command. Do not silently clamp it. A Topic contract timeout is its default or recommendation, not a maximum. Explicit no-limit bounded wait must add the subcommand flag `--no-timeout`; Do not combine the two flags. Even then collection still stops at 1–64 matching events and the command still returns one terminal JSON document.

Before every wait/stream, run `topic-schema`, copy its complete contract digest and opaque value handles, and stop on missing/stale data. Recursive business match facts from `topic-schema` are applied per event; the Gateway derives publish-schema paths, nested containers, wire types, and matching structure. It unsubscribes after success, timeout, or user cancellation. The complete dispatcher collection still shares the topic execution contract's 256 KiB JSON result ceiling.

For `ak.wwise.core.soundbank.generated`, the default `topic-schema` is the compact shortcut view. It omits the long-tail row and exact-entry catalogs; request those only when the shortcut fields cannot express the user's need, using `topic-schema <topic-uri> --catalog` before the relevant field disclosure. After a successful stream, terminal `agent_result` is the sole event-result authority for both natural-language and machine-readable answers. Report its exact events, and never report no events when its `event_count` is positive.

Route ordinary vague requests to subscribe, listen, monitor through `wait-topic`. Select `stream-topic` only when the user explicitly asks for a stream, continuous, persistent, event-by-event, 实时逐条, 流式, 持续, 一直监听, or 不要收到后退出 intent. It keeps one persistent subscription, emits one compact flushed NDJSON record per match, and requires an explicit maximum `--event-count <1..64>`. It ends at the count, timeout, user cancellation, or a bounded low-frequency health check detects host loss. Every streamed event and the cumulative NDJSON bytes are bounded and validated; overflow fails closed instead of silently dropping an event. Every exit always attempts to unsubscribe and emits one terminal NDJSON record.

For `ak.wwise.core.soundbank.generated`, the gateway itself keeps the ordinary 10-second omitted-duration default. The Skill must explicitly pass gateway-global `--timeout 120` and tell the user that this subscription will use 120 seconds. This is an explicit Skill-selected timeout, not a different gateway default; a user-supplied positive finite duration or explicit no-time-limit bounded wait still takes precedence. Run `topic-schema` and prefer its closed business shortcuts: `--include-object-identity` returns `id,name,type,path`; `--match-platform-name <exact-name>` binds the nested platform name without a handle; `--match-soundbank-name <exact-name>` binds a named Bank. Omit a match the user did not request and never inject a GUID in its place. The generic disclosed Topic facts remain available for other fields and topics.

Use `ak.wwise.core.soundbank.generated` for per-Bank × platform × language result events. Use `ak.wwise.core.soundbank.generationDone` only for the overall generation-cycle notice; `generationDone` is not proof that every Bank succeeded, so use the generating operation's terminal verification. `interface.selection_guidance` repeats this distinction.

UI-command reads require the auto-detected Authoring profile and fresh `getCommands`; snapshots are not allowlists. `debug-wal-tree` and `debug-validate-call` remain bounded Debug-build routes and never authorize synthesis of an artifact.

## Selection and result boundary

For current selection use live `selected`; report rows or explicit empty. The Gateway deduplicates and bounds it. Preserve terminal `agent_result` exactly. Malformed responses never become empty objects/Buses/projects/selections.

There is no raw-client fallback for an ordinary user query. If the packaged Gateway cannot perform it, report the interface boundary. Only an explicit Skill-development task may change the implementation.

<!-- WAAPI_QUERY_REFERENCE_END -->
