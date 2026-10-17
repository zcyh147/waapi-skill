# WAAPI query lane

Read-only queries and bounded Topic monitoring. Require the final sentinel and complete read per `SKILL.md`; otherwise stop.

## Routing and boundaries

- Use only the packaged Gateway. There is no raw-client fallback and do not write Python.
- Use fixed routes directly: object reads use the business declaration from `query-schema`; Topic facts use `topic-schema`; non-fixed reflected functions use `request-schema <uri>` and its sole continuation. Topic observation never authorizes its publisher.
- Otherwise copy the route from `operations`.
- Saved configuration selects live schemas. Catalogs default to Console; offline `--profile wwise-authoring-ui` adds Authoring. Neither proves live availability. Use coverage's host-scoped summary, then filters. `describe` is for offline schema audits. `--limit 0` requires every row.
- `API_NOT_FOUND`, `MANIFEST_NOT_FOUND`, `FIXED_COMMAND_REQUIRED`, `QUERY_OBJECT_REQUIRED`, `WAIT_TOPIC_REQUIRED`, `TRANSACTION_REQUIRED`, and `UNSUPPORTED_BY_SKILL_INTERFACE` (`unsupported_by_skill_interface`) are boundaries; other complete structured failures follow the Skill Recovery rule and their receipt.

## Wwise 2025.1 Media Pool

Run `request-schema ak.wwise.core.mediaPool.getFields` before `request-schema ak.wwise.core.mediaPool.get` and follow each typed continuation. Do not request the `.get` schema first.

Supply disclosed database, field, condition, output, and limit values. Gateway owns
native bindings, filters, and projection. Missing live fields permit scoped discovery refinement; unresolved ambiguity needs an exact choice.
For case-sensitive matching use the disclosed post-filter; a saturated candidate
set that cannot prove completeness returns `MEDIA_POOL_POST_FILTER_INCOMPLETE`.
At the candidate limit, follow `next_command` for a larger prefix reread, with no
native offset. Gateway verifies the exact preceding prefix and query/config/project/session.
Append ordinary later rows; `replace_previous_prefix` replaces the prior sorted/filtered
view. Long queries use an opaque `--media-query` read-plan handle. At 200 rows,
`complete=false` remains a resource boundary, never proof that the collection ends.
Preserve returned `Db` and complete `Path` for a later original-file reference
check; never perform this join in model-authored code.
`contains` takes literal text, never regex syntax or inline modifiers.

### Closed original-file reference classification

Wwise `2025.1`-only, after a successful Media Pool read. Require between 1 and 64 candidate rows. With zero candidates report empty. With more than 64 report the candidate-limit boundary; do not silently truncate, split the candidates across repeated scans, or choose a subset.

Take each exact returned `Path`, sort those strings lexicographically, and pass each once. Each path is limited to 1024 UTF-8 bytes and must be drive-absolute, an ordinary UNC path, or POSIX-absolute. Reject relative/traversal/device paths. Do not pre-normalize or de-duplicate: the Gateway normalizes slash spelling and drive/UNC case, keeps POSIX case significant, and rejects normalized candidate collisions.

Run once, repeating the candidate option:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py query-object --max-results 1000 --match-original-file-path '<first-complete-returned-Path>' --match-original-file-path '<second-complete-returned-Path>'
```

Do not add predicates, relationships, or extra business outputs. The fixed `id,path,originalFilePath` projection performs the complete join and emits no raw AudioFileSource inventory.

Success keeps `agent_result` as its final top-level field with `waapi-skill.original-file-reference-match/v1`, `scan_complete: true`, `scanned_audio_source_count`, `scan_limit: 1000`, and one `candidates` entry for every input path in the same order. Each has exact full-scan `reference_count` and at most four `{id,path}` details, sorted by path case-insensitively and then id case-insensitively. `references_truncated: true` means only that detail list was shortened. An unreferenced entry has count `0`.

Classify only when the outer command succeeds and the terminal result says `scan_complete: true`. A 1000-row scan returns `ORIGINAL_FILE_REFERENCE_SCAN_INCOMPLETE` with no `agent_result`. Any malformed row/path, duplicate id, normalized candidate collision, or WAAPI boundary proves no unreferenced claim. Stop instead of retrying with a broader query, another batch, direct `WaapiClient`, inline Python, or a helper file.

## Object queries

Choose exactly one business source: repeated `--path-segment`, `--exact-id`, `--short-id` with the closed `--short-id-kind` and explicit `--max-results`, closed `--kind`, live-resolved `--custom-kind`, `--search-text`, `--query-id`, or repeated `--query-path-segment`. `query-schema` discloses the Short ID kinds and version-aware lookup. Short ID collisions remain candidates requiring canonical GUID selection and exact-ID readback before changes. Never reconstruct a Wwise path separator. Gateway constructs the exact Wwise path and separators from literal hierarchy names. Custom-kind miss/ambiguity uses returned candidates, never an invented type.

Repeated `--predicate BUSINESS_CONDITION VALUE` means flat AND. `--relationship` selects `descendants`, `ancestors`, `references-to`, `children`, or `parent`. A broad/expanding source requires the user's `--max-results`; there is no unbounded mode. `all-sounds`/`sound` includes SFX and Voice; use `sound-sfx` or `sound-voice` only for that explicit scope. With another source, type is `--predicate kind-is`, not a second source.

Identity projections always request `id,name,type,path`. Absent outputs appear in `unavailable_fields`; explicit null stays null. Missing identity facts produce `identity_completeness.complete=false` and bounded `native_observation`, with no mutation authority. Add repeated `--include` values in caller order; `--include-field` adds live fields to custom `properties` and `references` maps. Follow structured metadata repair for missing/ambiguous fields.

Offline schema: `query-schema` lists versioned outputs; `query-schema --output NAME` gives meaning, applicability, shape and versions.

Optional `--platform`/`--language` take one exact name or GUID, trimmed and bounded to 512 UTF-8 bytes. Omission keeps the current platform/native language default. Generated continuations retain both.

Success rows are objects in the array; only an explicit empty array is empty. Over-bound, malformed, or truncated results are not empty. Ordinary `query-object` success defaults to compact business fields, sufficient for normal answers. Use `--detail` only for explicit user requests or compile/dispatch diagnosis; never rerun solely for detail. Failures skip compact projection but obey global limits. Keep terminal `agent_result` exact and final.

Apply every AND conjunct before the bound.

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

The Gateway fixes read-only `ak.wwise.core.object.get`, projection, final take, timeout, bytes, and grammar. Limits are UTF-8 bytes (not character counts); WAQL is trimmed and single-line, without Query Editor `$`, comments or statement separators, or an unclosed double-quoted string or slash-regex literal. On rejection, report the reason and use the recovery receipt to refine the intended read through the disclosed schema. There is no generated-code fallback.

Final take bounds returned rows, not internal scans; even a one-row result does not prove uniqueness. Never feed an advanced result directly into a mutation. Present candidates, obtain their exact choice, then use the simple `query-object --exact-id` route. A mismatch means the workflow stops for a new choice. Candidate displays keep unaliased identity fields; never alias another advanced expression onto them.

### Bounded inventories

Use the business declaration for one source and flat AND. Use advanced only for a native read-only construct absent from that schema; descendants, flat predicates, and business includes do not justify `--advanced`. Plan one bounded request and apply presentation logic only to its complete result.

- The Agent names `volume-db`, `pitch-cents`, `output-bus`, `source-language`, and other business fields. The Gateway owns case-sensitive Wwise accessors and shell quoting. Output order is fixed identity first, then repeated includes, then custom maps.
- Repeated `--predicate` values mean AND; preserve the user's condition order. Do not submit only a type condition. With nested boolean logic, use the advanced exact-WAQL lane. `isIncluded` is appended last because it is filter-only.
- “Shared” applies to the complete final row set. For parent containers together with their direct child Sounds, omit a `type=Sound` or container-only predicate; fetch one bounded mixed-type descendant set with `--include parent`, or it would erase one required side of the relationship.
- Sound language is proven when exactly one returned `AudioFileSource` has `parent.id` exactly equal to that Sound's `id`. Do not report the language as missing when this exact child-source evidence exists; do not associate by row position, similar names, or path prefixes.
- For "from the Sounds, find their direct parents", use `--kind all-sounds --relationship parent`. Predicates then describe the selected parent rows; Do not replace this with a descendant inventory. The result has one returned parent row for each matching source object. Count those rows before deduplicating. Treat `childrenCount` only as the number of all direct child objects; never relabel its value or a sum of it. At the bound, report that confirmed source count and say the result may be incomplete.
- For an ownership chain from one exact object, use `--relationship ancestors`; do not assume the relationship removes Project. Return nearest parent to farthest ancestor without mixing same-name objects from other branches.
- For relative depth, derive depth from each returned `path`, counting the root's direct children as relative depth 1; do not add `parent` solely to calculate relative depth. Request `parent` only when the user needs a parent identity or a direct parent-child relationship.
- When the user supplies a maximum, copy that exact number to `--max-results`. Otherwise ask for a limit instead of inventing one.

Literal path and exact-name search:

```bash
python scripts/run.py gateway.py query-object --path-segment 'Events' --path-segment 'Default Work Unit'
python scripts/run.py gateway.py query-object --search-text 'ExactName' --predicate name-is ExactName --max-results 1
```

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

Start with offline `object-types`. Live `metadata types` pages the running type inventory; optional `--meaning` filters name/type substrings. Follow generated `next_command` until `complete`.

`metadata list` pages one scope's fields. Copy a returned `selection` to same-scope `metadata detail --selection`; for a full inventory, follow `next_command` until `complete`. Details preserve type/default/restrictions/dependencies/supports/UI units, absence/null; unknown units stay unknown. Large fields retain useful `field` facts with typed choice/dependency and lossless raw-detail continuations. Follow generated commands; field selection needs no JSON-pointer reconstruction or giant descriptions. Expired/changed-scope selections require a new list and never authorize changes.

`metadata discover` is auxiliary lexical search. It chooses one scope and repeat `--meaning` for one to eight short English phrases. Gateway owns detail level, search bounds, projection, metadata tokens, and cache scope. Complete `no_match` is a bounded miss: refine the meaning or use scoped list/detail discovery within the task. A `partial` result permits one broader technical attempt, then clarify unresolved choices. Honor dependencies when authorized, otherwise clarify.

Use fixed reads rather than reflected payloads:

- `profiler-game-objects`: bounded capture; 2022.1–2025.1.
- `profiler-voice-contributions`: all versions; one Voice object GUID and optional game-object/Bus object GUIDs. Gateway resolves volatile pipeline IDs.
- `project-default-work-units`: bounded default Work Unit facts.

Other reflected reads use `request-schema <uri>` and its exact continuation.

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

`wait-topic`: one reviewed URI, 1–64 matching events, one terminal JSON document.
An ordinary omitted duration uses 10 seconds. Explicit durations are authoritative:
convert units to seconds without rounding into global `--timeout`, never clamp.
Contract timeouts are defaults, not maxima. Explicit no-limit waits use
`--no-timeout`, never combined with `--timeout`. Announce the effective policy.

Before every wait/stream, run `topic-schema`, copy its complete contract digest and opaque value handles, and stop on missing/stale data. Recursive business match facts from `topic-schema` are applied per event; the Gateway derives publish-schema paths, nested containers, wire types, and matching structure. It unsubscribes after success, timeout, or user cancellation. The complete dispatcher collection still shares the topic execution contract's 256 KiB JSON result ceiling.

For `ak.wwise.core.soundbank.generated`, the default `topic-schema` is the compact shortcut view. It omits the long-tail row and exact-entry catalogs; request those only when the shortcut fields cannot express the user's need, using `topic-schema <topic-uri> --catalog` before the relevant field disclosure. After a successful stream, terminal `agent_result` is the sole event-result authority for both natural-language and machine-readable answers. Report its exact events, and never report no events when its `event_count` is positive.

Route ordinary vague requests to subscribe, listen, monitor through `wait-topic`;
a requested event count or per-event/persistent output selects `stream-topic`.
It emits one compact flushed NDJSON record per match from one persistent subscription and
requires an explicit maximum `--event-count <1..64>` (a Skill limit, not WAAPI).
Total: global `--timeout`; idle: `--idle-timeout` after `stream-topic`.
Announce both and the count. Without a
total duration, Gateway defaults to 300 idle seconds, reset only by matching
events. Explicit total duration disables that default; explicit idle duration
overrides it (30 minutes = 1800 seconds); `--no-idle-timeout` disables it.
Clarify ambiguous timeout wording. Options are start-time, not live-adjustable.
The stream ends at count/time limits, user cancellation, or a bounded low-frequency
health check detects host loss. Every streamed event and the cumulative NDJSON
bytes are bounded and validated; overflow fails closed instead of silently
dropping an event. Every exit always attempts to unsubscribe and emits one
terminal NDJSON record. Use `monitoring_outcome.target_completed` as completion
authority. Duration or idle termination before the count reports `stopped`;
report observed/target counts and the stop reason without automatically restarting.
Subscription acknowledgement proves setup only. Every delivered event is checked
against its pinned publish schema and reachable definitions before matching;
malformed events and overflow fail monitoring with separate cleanup evidence.
For `ui.signal.click/toggle`, copy `topic-schema`'s `--signal-model` and
`--signal-widget` continuation. Select an active owned frontend model and its
exact widget key; the Gateway derives subscription and callback identity filters.
Observation does not authorize `signal.emit` or establish its delivery.

For a vague `ak.wwise.core.soundbank.generated` wait, explicitly pass gateway-global
`--timeout 120` and announce 120 seconds. This is Skill-selected; Gateway still
defaults to 10 seconds. Explicit user timing/count intent takes precedence.
Prefer its `topic-schema` shortcuts: `--include-object-identity` returns
`id,name,type,path`; `--match-platform-name <exact-name>` and
`--match-soundbank-name <exact-name>` bind names without handles. Omit unrequested
matches; never substitute GUIDs. Disclosed Topic facts cover other fields.

Use `ak.wwise.core.soundbank.generated` for per-Bank × platform × language result events. Use `ak.wwise.core.soundbank.generationDone` only for the overall generation-cycle notice; `generationDone` is not proof that every Bank succeeded, so use the generating operation's terminal verification. `interface.selection_guidance` repeats this distinction.

UI reads require the auto-detected Authoring profile and fresh `getCommands`; snapshots are not allowlists. `debug-wal-tree` and `debug-validate-call` remain bounded Debug-build routes and never authorize synthesis of an artifact.

## Selection and result boundary

For current selection use live `selected`; report rows or explicit empty. The Gateway deduplicates and bounds it. Preserve terminal `agent_result` exactly. Malformed responses never become empty objects/Buses/projects/selections.

Selected files: Wwise 2025.1 Authoring only. Find `getSelectedFiles` through
`operations` and follow its zero-input continuation. File selection is distinct; empty files say nothing about selected objects.

Report unsupported Gateway queries as boundaries; only explicit Skill development changes implementation.

<!-- WAAPI_QUERY_REFERENCE_END -->
