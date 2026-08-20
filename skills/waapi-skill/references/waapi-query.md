# WAAPI query lane

Use this reference for read-only project facts, hierarchy inspection, metadata
discovery, bounded Topic waits, and persistent streams.

Require the unique terminal sentinel required by `SKILL.md` and no truncation or omission marker; do not reread a range or invoke the Gateway.

## Boundaries and routing

- Use only the Skill-local Gateway; return its structured evidence or blocker.
- Use fixed `status`, `buses`, `selected`, `query-schema`, `query-object`,
  `object-types`, `metadata`, `request-schema`, `topic-schema`, `wait-topic`,
  and `stream-topic` directly. Simple queries use concise typed flags;
  structured and advanced queries use the sole continuation returned by
  `query-schema`; reflected functions use `request-schema`; Topic facts use
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
- For any reflected function URI, run `gateway.py request-schema <uri>` and
  follow its sole typed continuation. Zero-input reads dispatch without facts;
  inline and Draft shapes are selected by the Gateway, never by the Agent.
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
  python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2025.1 query-object --type AudioFileSource --take 1000 --match-original-file-path '<first-complete-returned-Path>' --match-original-file-path '<second-complete-returned-Path>'
  ```

  Do not add `--where`, `--select`, `--all-results`, or `--return-field`.
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

Object reads progress from simple flags to the closed structured Builder, then
bounded native WAQL fallback; use the earliest expressive layer.

Simple one-source/flat flags: `--path`, `--object-id`, `--type`, `--search`, and
`--query`; `--query` means an existing Wwise Query Editor object
identified by GUID or absolute `\Queries\...` path. Selects are
`descendants`, `ancestors`, `referencesTo`, `children`, and `parent`; `this` and
`owner` remain outside the packaged boundary. `=` is exact equality and `:` is
a contains/match predicate.

Copy user-supplied absolute Wwise paths character-for-character; never add or
change their roots. In 2025, never rewrite `\Containers\...` or `\Busses\...`
under legacy roots.

Choose the query layer by live retrieval, not report-rule count. For every
object in one explicit small subtree, fetch needed fields with one complete
simple inventory, then apply the user's `OR`, `NOT`, comparison, or naming rules
directly to those rows, without code. Do not call `query-schema` merely because
a report has several rules. Use structured only when live row selection itself
requires it.

For a complex query, first run the offline, version-aware schema command:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version <supported-version> query-schema
```

Follow its typed structured-query continuation, using only Gateway-disclosed
field, branch, and dynamic-container handles. The contract defines one
structured `source`, ordered `transforms`, and explicit `return`; it alone defines the closed
sources; `select`, `where`, and `take`; and `compare`, `truthy`, nested
`all`/`any`, or `not`. Do not add `waql`, `raw`, `expression`, or another escape
field, or infer absent grammar.

Every broad structured source/select ends with one `take` between `0` and `1000`;
only one exact non-expanding object may omit it. The simple route keeps
its existing `--take N` or explicit user-requested `--all-results` rule.
Over-bound or multiple exact-lookup rows are drift; a fixed
`buses` response above 1000 is protocol drift. Success rows are objects in the array; only an explicit empty array
is empty. An invalid response shape is a structured error, never an empty result.

Explicit `--return-field` on the simple route and `return` in the structured
request replace defaults, so include every needed field. An exact path lookup
must return `path`, an exact id lookup must return `id`, and identity mismatch
is rejected; keep those four fields explicit for an exact path/GUID identity lookup:

```bash
python scripts/run.py gateway.py query-object --path '\Events\Default Work Unit' --return-field id --return-field name --return-field type --return-field path
python scripts/run.py gateway.py query-object --search 'ExactName' --where name = string ExactName --take 1 --return-field id --return-field name --return-field type --return-field path
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
Preserve first-returned order,
de-duplicate the GUIDs, and query each distinct GUID exactly once.

A relationship display `name`, including `OutputBus.name`, never proves an
absolute path. If a rule gives an absolute Bus path,
exact-ID query every distinct `OutputBus` GUID for `id`, `name`, `type`, and
`path`; compare returned `path`, never `name` with its final segment.

If a broad ordinary/structured query returns multiple
candidates and the user selects some to change, before preview use
`query-object --object-id` on each selected GUID with unaliased `id`, `name`,
`type`, and `path`; all must match. Never reread unselected rows; relationship
read hops are exempt. An advanced-WAQL candidate needs an exact choice and the
simple exact-id readback.

### Advanced native WAQL fallback

If the schema returned by ordinary `query-schema` lacks a required read-only
construct—such as `skip`, `orderby`, `distinct`, a regular-expression literal,
a WAQL list function, or an advanced return expression—do not reject the user
request and do not write Python. Disclose only the third-layer contract:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version <supported-version> query-schema --advanced
```

Construct exactly the returned `waapi-skill.advanced-object-query/v1` shape and
invoke:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py query-object --typed-advanced --schema-digest <digest> --waql '<bounded-single-line-waql>' --advanced-return '<expression>' --max-results <1..1000>
```

That document has `contract`, native `waql`, native `return`, and `max_results`
(1–1000). It cannot choose URI, args/options, timeout, byte limit, or all-results
mode. The Gateway fixes read-only `ak.wwise.core.object.get`, rejects multi-query
framing, appends final `take <max_results>`, and rejects excess rows. Wwise
version-checks native return syntax; the Gateway bounds it.

The schema gives exact native-input limits. `waql` and every `return` expression
use UTF-8 bytes (not character counts) and must be trimmed and single-line.
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
`query-object --object-id` route before the closed mutation. Candidate displays
keep `id`, `name`, `type`, and `path` unaliased; never alias another advanced
expression onto those reserved keys. The exact-ID readback must match the chosen
name/type/path or the workflow stops for a new choice. Raw WAQL itself is never
a mutation identity.

### Bounded inventories

Use simple flags for one source, fixed selects, and flat AND; structured form
for nested predicates or ordered transforms; advanced only for a native
construct absent from the structured schema. Plan one bounded request and
apply presentation logic only to its complete result.

- Case-sensitive: Volume -> `@Volume`, Pitch -> `@Pitch`, notes -> `notes`,
  Output Bus -> `OutputBus` (never `@OutputBus`), Source language ->
  `audioSource:language`, parent -> `parent`, inclusion -> `isIncluded`, direct
  child count -> `childrenCount`. Copy tokens exactly; never recase or
  add/remove `@`. ASCII-single-quote every standalone argv value beginning with
  `@` on every platform: `--return-field '@Volume'`.
- Projection order is `id,name,type,path`, then fields needed for report,
  grouping, or sorting in their first-mention order, then additional filter-only
  fields. Determine it by scanning the user's requested output left to right;
  derived fields stay at first mention. “Parent path, then Sound path, language,
  Volume, notes” is exactly
  `id`, `name`, `type`, `path`, `parent`, `audioSource:language`, `@Volume`,
  `notes`.
- Repeated `--where FIELD OPERATOR TYPE VALUE` facts mean AND on the simple route. Words such as
  "simultaneously", "all of the following conditions", or “同时满足” introduce
  a pure AND. Repeat `--where` for every supported conjunct, preserving the
  user's condition order. Do not submit only the type predicate
  when Volume, notes, inclusion, child-count, or path is also a requested
  server-side condition. When the live result selection itself requires
  `A and (B or C)` or another nested boolean, switch to the structured route:
  use one `where` transform with `all`, `any`, and `not` only in the shapes
  returned by `query-schema`. Boolean rules applied after a complete small
  inventory do not trigger that switch.
- “Shared” applies to the complete final row set. For parent containers together
  with their direct child Sounds, omit a `type=Sound` or container-only
  predicate, fetch one bounded mixed-type descendant set, request `parent`, and
  separate both returned branches; a type predicate would erase one required
  side of the relationship.
- A Sound's language may live on its child source. Associate it only when
  exactly one returned `AudioFileSource` has `parent.id` exactly equal to that
  Sound's `id`; use its `audioSource:language`. Do not report the language as
  missing when this exact child-source evidence exists, and do not associate by
  row position, similar names, or path prefixes. Missing or disagreeing exact
  sources mean unresolved.
- For "from the Sounds, find their direct parents", use
  `--type Sound --select parent`.
  Predicates then describe the selected parent rows; include a returned-parent
  `path` predicate before type, child-count, and notes. Do not replace this with
  a descendant inventory.
  The result contains one returned parent row for each matching source object:
  Count those rows before deduplicating. Treat `childrenCount` only as the
  number of all direct child objects; never relabel its value or a sum of it as
  a source count. At the take bound, report that confirmed source count and say
  the result may be incomplete, including derived parent lists/counts.
- For an ownership chain from one exact object, use `--select ancestors`.
  When Project is excluded, add `type != Project`; do not assume the ancestor
  transform removes Project by itself. Return nearest parent to farthest
  ancestor without mixing same-name objects from other branches.
- For relative depth, derive depth from each returned `path`, counting the
  root's direct children as relative depth 1; do not add `parent` solely to
  calculate relative depth. Request `parent` only when the user needs a parent
  identity or a direct parent-child relationship.
- When the user supplies a numeric maximum, copy that exact number to `--take`
  on the simple route or to the terminal structured `take` transform. Use
  simple `--all-results` for explicit exhaustive wording: `all`, `全部`, or
  `都列出来`. When a broad or
  expanding query has no bound, ask for a limit instead of inventing one.
  Reaching the bound makes the rows and every derived count/group/list
  potentially incomplete.

For example, a bounded descendant inventory of Sound candidates remains a
simple flag query:

```bash
python scripts/run.py gateway.py query-object --path '\Actor-Mixer Hierarchy\Default Work Unit\Combat' --select descendants --where type = string Sound --take 24 --return-field id --return-field name --return-field type --return-field path --return-field '@Volume' --return-field notes --return-field OutputBus
```

Pure AND; `isIncluded` is appended last because it is filter-only:

```bash
python scripts/run.py gateway.py query-object --path '\Actor-Mixer Hierarchy\Default Work Unit\CombatMix' --select descendants --where type = string Sound --where '@Volume' '<=' number -6.0 --where notes : string mix-review --where isIncluded = boolean true --take 12 --return-field id --return-field name --return-field type --return-field path --return-field '@Volume' --return-field notes --return-field OutputBus --return-field isIncluded
```

Direct parents:

```bash
python scripts/run.py gateway.py query-object --type Sound --select parent --where path : string '\Actor-Mixer Hierarchy\Default Work Unit\ParentReview' --where type = string RandomSequenceContainer --where childrenCount '>=' integer 3 --where notes : string parent-review --take 10 --return-field id --return-field name --return-field type --return-field path --return-field childrenCount --return-field notes --return-field OutputBus
```

Eight-level non-Project ownership:

```bash
python scripts/run.py gateway.py query-object --path '\Actor-Mixer Hierarchy\Default Work Unit\Player\Movement\Footstep_Run' --select ancestors --where type '!=' string Project --take 8 --return-field id --return-field name --return-field type --return-field path --return-field childrenCount --return-field notes
```

When the live result selection itself, rather than a report over a complete
small inventory, contains nested OR/NOT logic, run the offline schema call and
use the structured request:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py query-schema
# Follow the returned typed-structured continuation and Gateway-issued handles.
```

The versioned structured Builder is a core subset. Program tests prove its
compiler and the advanced route's fixed URI, framing, cap, and result checks,
not real-Wwise acceptance of a native construct. When the structured schema
lacks one, use the advanced route and let the connected version decide, with no
generated-code fallback.

## Object types, live metadata, and fixed reads

Use offline, version-pinned `object-types` first; it returns at most 20 rows per
version by default. Narrow with `--query`, `--object-type`, or `--limit`;
`--summary-only` describes the complete catalog and cannot combine with them.
Use live `metadata types` only to reflect the running instance again. For a live
machine-readable summary,
`metadata types --summary-only` returns terminal `agent_result`;
compact-serialize that object exactly and stop. Do not rebuild it from
`normalized` or repeat the metadata command after success.

`metadata discover` resolves a known meaning to a live name. Translate intent
to short English phrases in repeated
`--query`; never ask for internal names. Choose one scope: `--object-type` for a
known new/imported type, `--class-id` for a proven class id, or `--object` for a
GUID/path or plug-in. `--limit` is per phrase (default 5, max 8).
For mutation count only repeated `--query` flags (not objects, rows, files, or
values): 1–2 use 8, 3–4 use 3, and 5–8 use 2. At a dependency/byte ceiling,
split without repeating proven phrases.

The Gateway searches at most 256 live details. Complete `no_match` is a bounded miss;
on `partial`, retry once with broader technical phrases, then ask one behavior
question. Never guess. Only exact current live names enter closed
`properties`/`references`; labels are hints. Honor dependencies when authorized,
otherwise clarify. Preview revalidates.

Use fixed reads rather than reflected payloads:

- `profiler-game-objects`: non-negative milliseconds or exact `user`/`capture`;
  2022.1–2025.1; 2022 `registrationTime` normalizes to `register_time`.
- `profiler-voice-contributions`: all five versions; one uint32 voice pipeline id
  and up to 64 ordered bus pipeline ids (omit for dry path); DSF `feature_available`, `reported`,
  and `value` stay distinct.
- `project-default-work-units`: distinct availability/reporting/value for
  2025 `defaultWorkUnits` and `defaultImportWorkUnit`.

Each exposes its stable terminal `agent_result`; do not rebuild it.

For a migrated reflected read, run `request-schema <uri>` with the configured version, then
its sole continuation with the returned handles, digest, and typed values. On
stale/schema errors, rerun discovery.

## Exact-hop playback diagnosis

For cross-reference diagnosis from an exact path, resolve
`id,name,type,path`, then follow returned relationship ids by exact-id lookup.
For Event use `--select children --take 100`, not descendants or same-name
search. Request identity and hop fields: Action ->
`ActionType,Target`; Sound -> `OverrideOutput,activeSource,OutputBus`. The Event
children result is already the Action hop. With its `ActionType,Target`, do not
query the Action id again; use the returned `Target.id` directly for the next
exact-id Sound lookup.

That Sound projection ends at `OutputBus`; do not add `@Volume` to the Sound
hop unless the user asks for the Sound's own volume. For source file/language,
query `originalFilePath,audioSource:language` on the exact returned
`activeSource` id. To distinguish routing from Bus mute, query `@Volume` only
on the exact Bus identities: first the returned `OutputBus` id, then the
requested comparison Bus path or id. Search only for discovery/disambiguation,
never exact-identity translation. Both exact Bus reads must use the same
`id,name,type,path,@Volume` projection; never omit `@Volume` from comparison Bus.

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
Typed match facts from `topic-schema` are applied per event; nonmatches do not consume count. The route
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

For `ak.wwise.core.soundbank.generated`, the gateway itself keeps the ordinary 10-second omitted-duration default. The Skill must explicitly pass gateway-global `--timeout 120` and tell the user that this subscription will use 120 seconds. This is an explicit Skill-selected timeout, not a different gateway default; a user-supplied positive finite duration or explicit no-time-limit bounded wait still takes precedence. Run `topic-schema` and use its exact typed option handles for the four return fields `id,name,type,path`; set event count to requested
Bank × platform × language cells. Add typed match facts for `soundbank.name` or
`platform.name` only when one explicit name is common to all
cells; otherwise submit no match facts. Never
discover or inject a GUID for this predicate.
Use the exact leaf scalar handle when `topic-schema` exposes one (for example
`soundbank.name`); do not replace that fact with `map-put` on its parent map.
Conversely, use `map-put` only where the schema exposes an open map without a
leaf scalar. If every requested cell shares one platform, that platform is a
common explicit name and its typed match fact is required even when the Bank
names differ.

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
it takes 1–256, validates/sorts nodes, and returns bounded `agent_result`.
Exact `ak.wwise.debug.validateCall` typed construction (2024.1–2025.1) validates
without executing one reflected request. Both debug routes may be unavailable in
non-Debug builds.

## Selection and result boundary

For current selection use live `selected` first; report rows or explicit empty
selection. Add needed repeatable accessors; the Gateway retains
`id,name,type,path`, deduplicates, and bounds the projection. On a headless host report the
UI boundary; do not invent a fallback.

Keep return fields explicit as Gateway options. Preserve terminal
`agent_result` exactly for machine-readable output. Never convert malformed
responses into empty objects, Buses, projects, or selections.

There is no raw-client fallback for an ordinary user query. If the packaged
Gateway cannot perform it, report that the current Skill interface does not
cover it. Only an explicit Skill-development task may change the implementation.

<!-- WAAPI_QUERY_REFERENCE_END -->
