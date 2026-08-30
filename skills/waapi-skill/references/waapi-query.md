# WAAPI query lane

Use this for read-only Wwise queries and bounded Topic waits/streams.

Require the unique terminal sentinel required by `SKILL.md` and no truncation or omission marker; do not reread a range or invoke the Gateway.

## Boundaries and routing

- Use only the Skill-local Gateway; return its structured evidence or blocker.
- Invoke the fixed routes named below directly. Object queries use the business
  declaration returned by `query-schema`; advanced queries add only an exact
  bounded WAQL expression. Non-fixed reflected functions use `request-schema`; Topic facts use
  `topic-schema`. Topic observation never authorizes its publishing change.
- For a broad catalog question start with
  `gateway.py capabilities --all-versions --summary-only`, then narrow with
  `--query`, `--category`, `--item-type`, `--family`, or `--route`.
  `capabilities` returns at most 50 compact rows by default. Use `--limit 0` only when
  every match is explicitly needed; use `--detail` only for nested
  interface, schema-summary, policy, or evidence auditing.
- For a known URI's route, version, schema, or boundary use
  `gateway.py describe <uri>`. Add `--full-schema` only when the complete
  reflected args/options/result schema is required.
- For a fixed function URI, `request-schema` returns only its business command,
  never native request fields. For remaining non-fixed reflected functions,
  follow the one returned construction continuation.
- Fixed functions return `FIXED_COMMAND_REQUIRED`;
  `ak.wwise.core.object.get` returns `QUERY_OBJECT_REQUIRED`; Topics return
  `WAIT_TOPIC_REQUIRED`; broader reads return `TRANSACTION_REQUIRED` rather than being inferred safe from a `get`-shaped name.
  `API_NOT_FOUND`, `MANIFEST_NOT_FOUND`, catalog route
  `unsupported_by_skill_interface`, `UNSUPPORTED_BY_SKILL_INTERFACE`, connection
  errors, and invalid responses are boundaries: report them and stop.
- The configured exact Wwise version selects every schema. Typed values and
  Gateway-issued handles remain bounded by that schema; a rejected continuation
  is a boundary, not permission to try another input language.
- Live Skill work must not copy `--version` from an example. The runner-owned
  session already selects the connected exact version; an explicit selector is
  only for an offline request that the user actually asked to inspect.

## Wwise 2025.1 Media Pool

`ak.wwise.core.mediaPool.getFields` and `.get` form one closed two-call read.
Use `request-schema` for each URI and follow only its typed continuation. Bind
field names solely from the first live result; the `.get` contract owns its
nested typed facts and optional closed result filter.

1. Exact standard bindings are name/file -> `Filename`, duration ->
   `WAV/Duration`, sample rate -> `WAV/Sample Rate`, bit depth ->
   `WAV/Bit Depth`, and channels -> `WAV/Channels`. `Filename` omits the
   extension; use `Path` when an extension or full path matters and never append
   `.wav` to a `Filename` regex. For IXML Scene/Take, select the unique returned
   `BWFXML/` field whose final component matches case-insensitively and preserve
   its spelling; stop on missing or ambiguous binding.
2. Args contain only `databases`, `filters`, and `maxResults`. Preserve database
   and predicate order; put a range's lower bound before its upper. Each filter is
   `{"type":"field","field":<bound field>,"operator":<operator>,"value":<value>}`
   with no `weight`. Operators are `equals`, `notEquals`, `contains`,
   `startsWith`, `endsWith`, `matchesRegex`, `lessThan`, `greaterThan`,
   `lessThanOrEqual`, and `greaterThanOrEqual`. “Between/from A to B” is
   inclusive. `contains` takes literal text, never regex syntax or inline modifiers.
   Convert kHz to integer Hz, mono/stereo to `1`/`2`, bit depth to an
   integer, and seconds to JSON numbers (`8.0` when whole). Do not add
   search, paging, sort, description, or similarity args.
3. Use the user's maximum, else `100`; range is 1–200, with at most 16 filters
   and 8 databases. For the case-sensitive `Filename` exception, use the
   `result_filter` fields disclosed by `request-schema`; the Gateway returns the
   filtered terminal `agent_result`. A saturated candidate set fails with
   `MEDIA_POOL_POST_FILTER_INCOMPLETE`.
4. `options.return` starts, unchanged and in order, with `Path`, `FileId`, `Db`,
   `Filename`, `WAV/Duration`, `WAV/Sample Rate`, `WAV/Bit Depth`,
   `WAV/Channels`:
   `{"return":["Path","FileId","Db","Filename","WAV/Duration","WAV/Sample Rate","WAV/Bit Depth","WAV/Channels"]}`.
   Append only non-standard bound fields needed by explicit filtering,
   grouping, sorting, or reporting, in first-mention order, without duplicates;
   the complete projection has at most 32 fields.
5. Start with `request-schema ak.wwise.core.mediaPool.getFields`, follow its
   sole continuation, and bind the exact returned field names. Only then run
   `request-schema ak.wwise.core.mediaPool.get` and follow every returned
   handle/continuation exactly. Do not request the `.get` schema first or use
   `.getFields` as a schema for `.get`. Preserve each returned `Db` and
   complete `Path`; never shorten a path or guess a host translation; never run
   the old unfiltered 1000-row AudioFileSource projection; never perform this join in model-authored code.

### Closed original-file reference classification

This is a Wwise `2025.1`-only follow-up to a successful Media Pool read.

- Run it only for between 1 and 64 candidate rows. With zero candidates report
  the empty result. With more than 64 report the candidate-limit boundary; do
  not silently truncate, split the candidates across repeated scans, or choose
  a subset.
- Take each exact returned `Path`, sort those strings lexicographically, and
  pass each once. Each path is limited to 1024 UTF-8 bytes and must be
  drive-absolute (`Y:\...`), ordinary UNC path (`\\server\share\...` with
  nonempty server/share/file), or POSIX-absolute. Reject basenames, relative/traversal
  paths, device paths, and guessed translations. Do not pre-normalize or
  de-duplicate: the Gateway normalizes slash spelling and drive/UNC case, keeps
  POSIX case significant, and rejects normalized candidate collisions.
- Invoke exactly one command, repeating only the final candidate option:

  ```bash
  python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2025.1 query-object --max-results 1000 --match-original-file-path '<first-complete-returned-Path>' --match-original-file-path '<second-complete-returned-Path>'
  ```

  Do not add predicates, relationships, or extra business outputs.
  The Gateway owns the fixed `id,path,originalFilePath` projection, validates
  rows and duplicate ids, performs the complete normalized join, and emits no
  raw AudioFileSource inventory.
- Success keeps `agent_result` as its final top-level field with contract
  `waapi-skill.original-file-reference-match/v1`, `scan_complete: true`,
  `scanned_audio_source_count`, `scan_limit: 1000`, and one `candidates` entry
  for every input path in the same order. Each has its exact
  `originalFilePath`, `classification`, exact full-scan `reference_count`,
  `references`, and `references_truncated`. `references` contains at most four
  `{id,path}` details sorted by path case-insensitively and then id
  case-insensitively; `references_truncated: true` means only that detail list
  was shortened. An unreferenced entry has count `0`, empty references, and
  `references_truncated: false`.
- Classify only when the outer command succeeds and the terminal result says
  `scan_complete: true`. A 1000-row scan returns
  `ORIGINAL_FILE_REFERENCE_SCAN_INCOMPLETE` with no `agent_result`. Malformed or
  oversized paths/rows, duplicate ids, normalized candidate collisions, WAAPI
  failure, or any other boundary proves no unreferenced claim. Stop instead of
  retrying with a broader query, another batch, direct `WaapiClient`, inline
  Python, or a helper file.

## Object queries

Object reads use one Gateway-owned business declaration. Choose exactly one
source: repeated `--path-segment`, `--exact-id`, a closed `--kind`, a
live-resolved `--custom-kind`, `--search-text`,
`--query-id`, or repeated `--query-path-segment`. Never reconstruct a Wwise
path separator, native type discriminator, predicate accessor, or relationship
token. The Gateway constructs the exact Wwise path and separators from the
literal hierarchy names.

When a custom kind meaning matches zero or multiple live types, use the
structured candidate list to refine `--custom-kind` to one exact returned type
name, then continue the original bounded read. Do not invent a type token or
skip the requested query after the repair probe.

Use repeated `--predicate BUSINESS_CONDITION VALUE` for flat AND conditions and
repeated `--relationship` for `descendants`, `ancestors`, `references-to`,
`children`, or `parent`. A broad or expanding source requires the user's
`--max-results`; exact path/GUID identity may omit it. There is no unbounded
mode.

`all-sounds` means every Wwise `Sound`, including SFX and Voice; `sound` is the
same business meaning and the Gateway canonicalizes it. Use
`sound-sfx` only when the user explicitly limits the request to SFX, and
`sound-voice` only for Voice. `--kind` is itself one exclusive source. When a
path, ID, search, or Query Editor source is already present, apply a type limit
only as `--predicate kind-is <business-kind>`. Sorting or grouping a complete
bounded result for the final answer is presentation and stays outside the
query. Disclose advanced WAQL only when server-side ordering, skip, distinct,
regex, or another native construct changes which rows enter the bounded result.

The Gateway always returns `id,name,type,path`. Add requested report data with
repeated `--include <business-field>`; `query-schema` lists the closed names.
For a custom plug-in field, use `--include-field` with the user's short field
meaning. The Gateway performs live metadata discovery in the query's exact
object/class scope, binds the result as a property or reference, and returns
custom values under `properties` or `references`. If discovery is not unique,
refine the meaning from the structured repair; never supply a native metadata
token.

The offline version-aware schema command describes this same business entry:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version <supported-version> query-schema
```

Use it to choose source, predicate, relationship, result bound, and business
outputs. Do not copy internal accessors or synthesize another construction
layer. Nested boolean, ordering, distinct, skip, regular-expression, or other
native constructs move to the bounded advanced lane below.

Over-bound or multiple exact-lookup rows are drift; a fixed
`buses` response above 1000 is protocol drift. Success rows are objects in the array; only an explicit empty array
is empty. An invalid response shape is a structured error, never an empty result.

The fixed identity projection is always present and identity mismatch is
rejected:

```bash
python scripts/run.py gateway.py query-object --path-segment 'Events' --path-segment 'Default Work Unit'
python scripts/run.py gateway.py query-object --search-text 'ExactName' --predicate name-is ExactName --max-results 1
```

Ordinary `query-object` success defaults to compact business fields, sufficient for
normal answers. Use `--detail` only for explicit user requests or compile/dispatch
diagnosis; never rerun solely for detail. Failures skip
compact projection but obey global limits. Keep terminal `agent_result` exact and final.

### Relationship-guided next hops

`Target`, `activeSource`, `OutputBus`, and `parent` are relationship objects.
Only `Target.id`, `activeSource.id`, `OutputBus.id`, or `parent.id` is the next-hop
identity. Require a canonical braced GUID; stop if missing or
malformed. Query that GUID directly; do not reread the current row or search by name
or path. Gateway target/role revalidation still runs during preview/execute/verify.
Preserve first-returned order, de-duplicate the GUIDs, and query each distinct
GUID exactly once in a separate `query-object --exact-id`; never merge IDs in one command.

A relationship display `name`, including `OutputBus.name`, never proves an
absolute path. If a rule gives an absolute Bus path,
exact-ID query every distinct `OutputBus` GUID for `id`, `name`, `type`, and
`path`; compare returned `path`, never `name` with its final segment.

If a broad ordinary or advanced query returns multiple
candidates and the user selects some to change, before preview use
`query-object --exact-id` on each selected GUID with unaliased `id`, `name`,
`type`, and `path`; all must match. Never reread unselected rows; relationship
read hops are exempt. An advanced-WAQL candidate needs an exact choice and the
simple exact-id readback.

### Advanced native WAQL fallback

If the business declaration returned by `query-schema` lacks a required read-only
construct—such as `skip`, `orderby`, `distinct`, a regular-expression literal,
a WAQL list function, or an advanced return expression—do not reject the user
request and do not write Python. Disclose only the bounded advanced fallback:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version <supported-version> query-schema --advanced
```

Invoke its one business envelope:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py query-object --advanced-waql '<bounded-single-line-waql>' --include <business-field> --max-results <1..1000>
```

The exact WAQL expression and result bound cannot choose URI, args/options,
projection syntax, timeout, byte limit, or an all-results mode. The Gateway
fixes read-only `ak.wwise.core.object.get`, compiles the same business outputs,
rejects multi-query framing, appends final `take <max_results>`, and rejects
excess rows.

The schema gives exact native-input limits. WAQL uses UTF-8 bytes (not character
counts) and must be trimmed and single-line.
Omit Query Editor `$`; add no comments or statement separators; reject an
unclosed double-quoted string or slash-regex literal. Ordinary names such as
“delete” remain harmless text. On Wwise rejection, report the structured error;
never alter WAQL, guess-retry, use generic `call`, or create a helper script.
Final `take` bounds returned rows, not internal `orderby`, `distinct`, or other
scans; Gateway timeout and byte ceilings remain separate.

For read-only work, choose the smallest honest `max_results` matching the user's
bound. Advanced limiting, ordering, list, alias, or projection means even a
one-row result does not prove target uniqueness. Never feed an advanced result
directly into a mutation. For a later change, present candidates, obtain their
exact choice, then verify its GUID through the simple
`query-object --exact-id` route before the closed mutation. Candidate displays
keep `id`, `name`, `type`, and `path` unaliased; never alias another advanced
expression onto those reserved keys. The exact-ID readback must match the chosen
name/type/path or the workflow stops for a new choice. Raw WAQL itself is never
a mutation identity.

### Bounded inventories

Use the business declaration for one source, relationships, flat AND, and
semantic outputs. Use advanced only for a native read-only construct absent
from that schema. Plan one bounded request and apply presentation logic only to
its complete result.

- The Agent names `volume-db`, `pitch-cents`, `output-bus`, `source-language`,
  `parent`, `included`, `child-count`, and other business fields. The Gateway
  owns case-sensitive Wwise accessors and shell quoting.
- Output order is fixed identity first, then repeated `--include` values in
  caller order, followed by custom `properties` and `references` maps.
- Repeated `--predicate` values mean AND and preserve the user's condition
  order. Do not submit only a type condition when volume, notes, inclusion, or
  child count is also required. When live selection needs nested boolean logic,
  use the advanced exact-WAQL lane; do not recreate native tuples in ordinary
  flags.
- “Shared” applies to the complete final row set. For parent containers together
  with their direct child Sounds, omit a `type=Sound` or container-only
  predicate, fetch one bounded mixed-type descendant set, add `--include parent`, and
  separate both returned branches; a type predicate would erase one required
  side of the relationship.
- A Sound's language may live on its child source. Associate it only when
  exactly one returned `AudioFileSource` has `parent.id` exactly equal to that
  Sound's `id`; use its `audioSource:language`. Do not report the language as
  missing when this exact child-source evidence exists, and do not associate by
  row position, similar names, or path prefixes. Missing or disagreeing exact
  sources mean unresolved.
- For "from the Sounds, find their direct parents", use
  `--kind all-sounds --relationship parent`.
  Predicates then describe the selected parent rows; include a returned-parent
  `path` predicate before type, child-count, and notes. Do not replace this with
  a descendant inventory.
  The result contains one returned parent row for each matching source object:
  Count those rows before deduplicating. Treat `childrenCount` only as the
  number of all direct child objects; never relabel its value or a sum of it as
  a source count. At the take bound, report that confirmed source count and say
  the result may be incomplete, including derived parent lists/counts.
- For an ownership chain from one exact object, use `--relationship ancestors`.
  If excluding Project cannot be expressed by the closed predicates, use one
  bounded advanced query; do not assume the relationship removes Project.
  Return nearest parent to farthest ancestor without mixing same-name objects
  from other branches.
- For relative depth, derive depth from each returned `path`, counting the
  root's direct children as relative depth 1; do not add `parent` solely to
  calculate relative depth. Request `parent` only when the user needs a parent
  identity or a direct parent-child relationship.
- When the user supplies a numeric maximum, copy that exact number to
  `--max-results`. When a broad or expanding query has no bound, ask for a limit
  instead of inventing one; even explicit exhaustive wording has no unbounded
  mode.
  Reaching the bound makes the rows and every derived count/group/list
  potentially incomplete.

For example, a bounded descendant inventory of Sound candidates remains a
simple flag query:

```bash
python scripts/run.py gateway.py query-object --path-segment 'Actor-Mixer Hierarchy' --path-segment 'Default Work Unit' --path-segment 'Combat' --relationship descendants --predicate kind-is all-sounds --max-results 24
```

Pure AND; `isIncluded` is appended last because it is filter-only:

```bash
python scripts/run.py gateway.py query-object --path-segment 'Actor-Mixer Hierarchy' --path-segment 'Default Work Unit' --path-segment 'CombatMix' --relationship descendants --predicate kind-is all-sounds --predicate volume-db-at-most -6.0 --predicate notes-contain mix-review --predicate included-is true --max-results 12
```

Direct parents:

```bash
python scripts/run.py gateway.py query-object --kind all-sounds --relationship parent --predicate kind-is random-container --predicate children-at-least 3 --predicate notes-contain parent-review --max-results 10
```

Eight-level non-Project ownership:

```bash
python scripts/run.py gateway.py query-object --path-segment 'Actor-Mixer Hierarchy' --path-segment 'Default Work Unit' --path-segment 'Player' --path-segment 'Movement' --path-segment 'Footstep_Run' --relationship ancestors --max-results 8
```

When live selection contains nested OR/NOT, ordering, distinct, skip, or another
construct absent from the business predicates, disclose the advanced boundary:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py query-schema --advanced
# Use one bounded --advanced-waql plus business --include fields.
```

Program tests prove the advanced route's fixed URI, framing, projection
compilation, cap, and result checks, not real-Wwise acceptance of every native
construct. Let the connected version decide, with no generated-code fallback.

## Object types, live metadata, and fixed reads

Use offline, version-pinned `object-types` first; it returns at most 20 rows per
version by default. Narrow with `--query`, `--object-type`, or `--limit`;
`--summary-only` describes the complete catalog and cannot combine with them.
Use live `metadata types` only to reflect the running instance again; its
projection and bound are fixed.

`metadata discover` resolves user-facing meanings to authoritative live names.
Choose exactly one scope: repeated `--path-segment`, closed `--kind`,
live-resolved `--custom-kind`, or `--exact-id`; repeat `--meaning` for one to
eight short English phrases. The
Gateway owns detail level, search bounds, projection, metadata tokens, and
cache scope. `metadata property-state` takes one meaning plus `--platform` and
first resolves exactly one property. `metadata attenuation` takes one semantic
`--curve-role`; never supply native curve tokens.

The Gateway searches at most 256 live details. Complete `no_match` is a bounded miss;
on `partial`, retry once with broader technical phrases, then ask one behavior
question. Never guess. Only exact current live names enter closed
`properties`/`references`; labels are hints. Honor dependencies when authorized,
otherwise clarify. Preview revalidates.

Use fixed reads rather than reflected payloads:

- `profiler-game-objects`: `--capture latest|user-cursor` or non-negative
  `--capture-ms`;
  2022.1–2025.1; 2022 `registrationTime` normalizes to `register_time`.
- `profiler-voice-contributions`: all five versions; the same capture declaration,
  one exact Voice object GUID, optional game-object ID for ambiguity repair, and
  up to 64 Bus object GUIDs. The Gateway resolves volatile pipeline IDs; DSF
  `feature_available`, `reported`, and `value` stay distinct.
- `project-default-work-units`: distinct availability/reporting/value for
  2025 `defaultWorkUnits` and `defaultImportWorkUnit`.

Each exposes its stable terminal `agent_result`; do not rebuild it.

For a remaining non-fixed reflected read not covered by the business routes
above, run `request-schema <uri>` with the configured version, then its sole
continuation with the returned handles, digest, and typed values. On stale/schema
errors, rerun discovery.

## Exact-hop playback diagnosis

For cross-reference diagnosis from an exact path, resolve
`id,name,type,path`, then follow returned relationship ids by exact-id lookup.
For Event use `--relationship children --max-results 100`, not descendants or
same-name search. Request business hop fields: Action ->
`--include action-type --include target`; Sound ->
`--include override-output --include active-source --include output-bus`. The Event
children result is already the Action hop. With its `ActionType,Target`, do not
query the Action id again; use the returned `Target.id` directly for the next
exact-id Sound lookup.

That Sound projection ends at `output_bus`; do not add `volume-db` to the Sound
hop unless the user asks for the Sound's own volume. For source file/language,
request `original-file-path,source-language` on the exact returned
`active_source` id. To distinguish routing from Bus mute, request `volume-db` only
on the exact Bus identities: first the returned `output_bus` id, then the
requested comparison Bus path or id. Search only for discovery/disambiguation,
never exact-identity translation. Both exact Bus reads must use the same
fixed identity plus `volume_db`; never omit `--include volume-db` from the
comparison Bus.

## Topics and Authoring-only reads

`wait-topic` accepts one reviewed URI and 1–64 matches. An ordinary omitted
duration uses 10 seconds; tell the user and allow another duration. A
user-supplied positive finite duration is authoritative: convert its units to
seconds without rounding and put global `--timeout` before `wait-topic`. Do not
silently clamp it. For an explicit no-limit but fixed-count wait, omit global
timeout and add the subcommand flag `--no-timeout`. Do not combine the two flags.

One timeout covers setup and collection. A Topic contract timeout is its default
or recommendation, not a maximum. With `--no-timeout`, collection still stops at
1–64 matching events, and the command still returns one terminal JSON document. Recursive
business match facts from `topic-schema` are applied per event; the Gateway derives
publish-schema paths, nested containers, wire types, and exact matching structure.
Nonmatches do not consume count. The route
unsubscribes after success, timeout, or user cancellation. Every payload is
publish-schema validated, and the complete dispatcher collection still shares
the topic execution contract's 256 KiB JSON result ceiling. Reaching N matches
does not prove no N+1 event exists.

Route ordinary vague requests to subscribe, listen, monitor through
`wait-topic`. Select `stream-topic` only when the user explicitly asks for a
stream, continuous, persistent, event-by-event, “实时逐条”, “流式”, “持续”,
“一直监听”, or “不要收到后退出” intent. It uses one persistent subscription and
emits one compact flushed NDJSON record per match,
and by default continues until the user cancels it or a bounded low-frequency
health check detects host loss/replacement. A finite global timeout ends it
normally. Every streamed event is validated; overflow fails closed instead of
silently dropping an event. Every exit always attempts to unsubscribe and emits
one terminal NDJSON record. Relay events immediately; do not restart between
events or wait for the terminal record.

For `ak.wwise.core.soundbank.generated`, the gateway itself keeps the ordinary 10-second omitted-duration default. The Skill must explicitly pass gateway-global `--timeout 120` and tell the user that this subscription will use 120 seconds. This is an explicit Skill-selected timeout, not a different gateway default; a user-supplied positive finite duration or explicit no-time-limit bounded wait still takes precedence. Run `topic-schema`; repeat `--topic-option include <id|name|type|path>`, set event count to Bank × platform × language cells, and use `--event-match soundbank-name <name>` only when one explicit Bank name covers every cell. When every requested cell shares one platform, add `--event-entry platform - name <platform-name>`. Otherwise omit that predicate; never inject a GUID.

Use `ak.wwise.core.soundbank.generated` for per-Bank × platform × language
result events. Use `ak.wwise.core.soundbank.generationDone` only for the overall
generation-cycle/log notice. `generationDone` is not proof that every Bank
succeeded or artifacts exist; use the generating operation's terminal
verification. `describe` repeats this under `interface.selection_guidance`.

For `object.created`, do not match the requested name because publication
precedes final naming. ActorMixer event type is `ActorMixer` in
2021.1–2024.1 and `PropertyContainer` in 2025.1; use the version type and
trusted publisher evidence for id correlation. `ak.wwise.debug.assertFailed`
is diagnostic, not recovery proof.

The five `ak.wwise.ui.commands.*` reads require the auto-detected Authoring profile. Call
live `getCommands` without Console `describe`; only offline schema audits use
`describe ak.wwise.ui.commands.getCommands --profile wwise-authoring-ui`.
Observe execution via bounded `wait-topic ak.wwise.ui.commands.executed`.
WwiseConsole returns `AUTHORING_HOST_REQUIRED`. Packaged command-id snapshots
(317/451/475/594/623 across 2021.1–2025.1) are environment evidence, never
runtime allowlists; mutations require fresh live `getCommands`.

`debug-wal-tree` is the sole `ak.wwise.debug.getWalTree` route (2023.1–2025.1):
`--max-nodes` takes 1–256; the Gateway validates/sorts nodes and returns bounded
`agent_result`. `debug-validate-call` (2024.1–2025.1) takes an exact reflected
function URI and optionally an absolute user-owned `--artifact-file` containing
only `args`, `options`, and `result` objects. Never synthesize that artifact for
the user or use typed facts to reconstruct it. The target function is not
executed. Both debug routes may be unavailable in non-Debug builds.

## Selection and result boundary

For current selection use live `selected` first; report rows or explicit empty
selection. Its projection is fixed to `id,name,type,path`; the Gateway
deduplicates and bounds it. On a headless host report the UI boundary; do not
invent a fallback.

Preserve terminal
`agent_result` exactly for machine-readable output. Never convert malformed
responses into empty objects, Buses, projects, or selections.

There is no raw-client fallback for an ordinary user query. If the packaged
Gateway cannot perform it, report that the current Skill interface does not
cover it. Only an explicit Skill-development task may change the implementation.

<!-- WAAPI_QUERY_REFERENCE_END -->
