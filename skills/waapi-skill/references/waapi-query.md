# WAAPI query lane

Use this reference for read-only project facts, object and hierarchy inspection,
metadata discovery, bounded Topic waits, and persistent Topic streams.

Read this file once with one complete standalone `cat`. The read is complete
only when the unique terminal sentinel required by `SKILL.md` is the final
visible line and the tool output has no truncation or omission marker.
Otherwise stop and report an incomplete host read; do not reread a range or
invoke the Gateway.

## Boundaries and routing

- Use only the Skill-local Gateway. Return its structured evidence or a clear
  blocker; never use direct `WaapiClient`, inline Python, or a generated helper.
- Use the entry file's fixed `status`, `buses`, `selected`, `query-schema`,
  `query-object`, `object-types`, `metadata`, `wait-topic`, and `stream-topic`
  commands directly. Public command shapes include offline
  `gateway.py query-schema`, simple `gateway.py query-object` flags, structured
  `gateway.py query-object --request-json`,
  `gateway.py wait-topic`, and `gateway.py stream-topic`.
  Observing a Topic is read-only and never authorizes the change that publishes it.
- For a broad catalog question start with
  `gateway.py capabilities --all-versions --summary-only`, then narrow with
  `--query`, `--category`, `--item-type`, `--family`, or `--route`.
  `capabilities` returns at most 50 compact rows by default. Use `--limit 0` only when
  every match is explicitly needed; use `--detail` only for nested
  interface, schema-summary, policy, or evidence auditing.
- For a known URI's route, version, schema, or boundary use
  `gateway.py describe <uri>`. Add `--full-schema` only when the complete
  reflected args/options/result schema is required.
- The generic shape is
  `gateway.py call <uri> --args-json '<object>' --options-json '<object>'`.
  It is not an open raw-call surface: only the current version's
  `preferred_route: manifest_dispatch` rows dispatch, with recursive schema,
  time, and size validation. An explicit empty-args/options request for
  `ak.wwise.waapi.getFunctions` or `ak.wwise.waapi.getTopics` is a reviewed
  fast route: run that one `call` directly without `describe` or `capabilities`.
  Other known bounded reads may use `call` after `describe` proves the route.
- Fixed functions return `FIXED_COMMAND_REQUIRED`;
  `ak.wwise.core.object.get` returns `QUERY_OBJECT_REQUIRED`; Topics return
  `WAIT_TOPIC_REQUIRED`; broader reads return `TRANSACTION_REQUIRED` rather than being inferred safe from a `get`-shaped name.
  `API_NOT_FOUND`, `MANIFEST_NOT_FOUND`, catalog route
  `unsupported_by_skill_interface`, `UNSUPPORTED_BY_SKILL_INTERFACE`, connection
  errors, and invalid responses are boundaries: report them and stop.
- Global `--version`, `--timeout`, and `--evidence-dir` precede `call`;
  `--args-json`, `--options-json`, `--dry-run`, and compatibility-only
  `--allow-destructive` follow the URI. Neither those flags nor
  `WWISE_DESTRUCTIVE=1` can broaden the route. JSON inputs reject duplicate
  keys, non-finite numbers, invalid Unicode, and excessive size, depth, or nodes.

## Wwise 2025.1 Media Pool

`ak.wwise.core.mediaPool.getFields` and `.get` form one closed two-call read.
Do not run `describe` or `capabilities`: call `getFields` with empty
args/options, bind only its returned strings, then issue exactly one
`gateway.py --version 2025.1 call ak.wwise.core.mediaPool.get`. There is no
`mediaPool.get` subcommand, and the user need not know internal field names.

1. Exact standard bindings are name/file -> `Filename`, duration ->
   `WAV/Duration`, sample rate -> `WAV/Sample Rate`, bit depth ->
   `WAV/Bit Depth`, and channels -> `WAV/Channels`. `Filename` omits the
   extension; use `Path` when an extension or full path matters and never append
   `.wav` to a `Filename` regex. For IXML Scene/Take, select the unique returned
   `BWFXML/` field whose final component matches case-insensitively and preserve
   its spelling; stop on missing or ambiguous binding.
2. Args contain only `databases`, `filters`, and `maxResults`. Preserve database
   and predicate order; expand a range lower bound before its upper bound.
   Every filter is
   `{"type":"field","field":<bound field>,"operator":<operator>,"value":<value>}`
   with no `weight`. Operators are `equals`, `notEquals`, `contains`,
   `startsWith`, `endsWith`, `matchesRegex`, `lessThan`, `greaterThan`,
   `lessThanOrEqual`, and `greaterThanOrEqual`. “Between/from A to B” is
   inclusive. Convert kHz to integer Hz, mono/stereo to `1`/`2`, bit depth to
   integer, and seconds to JSON numbers (`8.0` for whole seconds). Do not add
   search, paging, sort, description, or similarity args.
3. Use the user's `maxResults`, else `100`; range is 1–200, with at most 16
   filters and 8 databases. Case-sensitive `Filename` substring matching is the
   sole exception: use a matching `contains` candidate, raw `maxResults:200`,
   and add `--post-filter-json` exactly as
   `{"field":<bound field>,"operator":"containsCaseSensitive","value":<same literal>,"limit":<user maximum or 100>}`.
   The Gateway returns the filtered terminal `agent_result`; do not filter it
   yourself. A saturated candidate set fails with
   `MEDIA_POOL_POST_FILTER_INCOMPLETE`.
4. `options.return` starts, unchanged and in order, with `Path`, `FileId`, `Db`,
   `Filename`, `WAV/Duration`, `WAV/Sample Rate`, `WAV/Bit Depth`,
   `WAV/Channels`:
   `{"return":["Path","FileId","Db","Filename","WAV/Duration","WAV/Sample Rate","WAV/Bit Depth","WAV/Channels"]}`.
   Append only non-standard bound fields needed by explicit filtering,
   grouping, sorting, or reporting, in first-mention order, without duplicates;
   the complete projection has at most 32 fields.
5. Invoke:

   ```bash
   python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2025.1 call ak.wwise.core.mediaPool.get --args-json '<args>' --options-json '<options>'
   ```

   Add `--post-filter-json` only for rule 3. Preserve each returned `Db` and
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

  Do not add `--where-json`, `--select`, `--all-results`, or `--return-field`.
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

Public object discovery has two closed forms. Neither accepts caller- or
model-authored raw WAQL.

Use the existing flags for a simple lookup with one source and the flat
conditions/transforms those flags expose: `--path`, `--object-id`, `--type`,
`--search`, or `--query`; `--query` means an existing Wwise Query Editor object
identified by canonical GUID or absolute `\Queries\...` path. Selects are
`descendants`, `ancestors`, `referencesTo`, `children`, and `parent`; `this` and
`owner` remain outside the packaged boundary. `=` is exact equality and `:` is
a contains/match predicate.

For a complex query, first run the offline, version-aware schema command:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version <supported-version> query-schema
```

Use its `waapi-skill.object-query/v1` JSON Schema to construct only the
structured fields it exposes, and then invoke:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version <supported-version> query-object --request-json '<waapi-skill.object-query/v1-json>'
```

The strict request contains `contract`, one structured `source`, ordered
`transforms`, and an explicit `return` projection. Sources cover the schema's
closed `all`, `project`, `type`, exact `object`, `search`, and Query Editor
`query` shapes. Transforms cover only structured `select`, `where`, and `take`.
A predicate is a closed `compare`, `truthy`, nested `all`/`any`, or `not`
object. Do not add `waql`, `raw`, `expression`, or another escape field, and do
not infer grammar that is absent from the returned schema.

Every broad structured source and every structured select must end with exactly
one `take` transform between `0` and `1000`. Only a single exact object source
without an expanding select may omit it. The simple flag route keeps its
existing `--take N` or explicit user-requested `--all-results` rule. A bounded
response above its take, an exact lookup returning multiple rows, or a fixed
`buses` response above 1000 is protocol drift. Successful rows must be objects
in the documented array; only an explicit empty array is empty. An invalid
response shape is a structured error, never an empty result.

Explicit `--return-field` on the simple route and `return` in the structured
request replace defaults, so include every needed field. An exact path lookup
must return `path`, an exact id lookup must return `id`, and identity mismatch
is rejected; keep those four fields explicit for an exact path/GUID identity lookup:

```bash
python scripts/run.py gateway.py query-object --path '\Events\Default Work Unit' --return-field id --return-field name --return-field type --return-field path
python scripts/run.py gateway.py query-object --search 'ExactName' --where-json '{"field":"name","operator":"=","value":"ExactName"}' --take 1 --return-field id --return-field name --return-field type --return-field path
```

### Bounded inventories

Use the simple flags when one source, their fixed selects, and a flat AND cover
the request. Use the schema-driven structured form only when the query needs a
nested boolean predicate or ordered transform combination that those flags
cannot express. Plan one bounded request and apply unsupported presentation
logic only to that complete result.

- Field tokens are case-sensitive. Mappings include Volume -> `@Volume`, Pitch
  -> `@Pitch`, notes -> `notes`, Output Bus -> `OutputBus` (never `@OutputBus`),
  Source language -> `audioSource:language`, parent -> `parent`, inclusion ->
  `isIncluded`, and direct child count -> `childrenCount`. Never translate,
  recase, or add/remove `@`.
- Projection order is `id,name,type,path`, then fields needed for report,
  grouping, or sorting in their first-mention order, then additional filter-only
  fields. Determine it by scanning the user's requested output left to right;
  derived fields stay at first mention. “Parent path, then Sound path, language,
  Volume, notes” is exactly
  `id`, `name`, `type`, `path`, `parent`, `audioSource:language`, `@Volume`,
  `notes`.
- A predicate array means AND only on the simple route. Words such as
  "simultaneously", "all of the following conditions", or “同时满足” introduce
  a pure AND. Put every supported conjunct into one `--where-json` array,
  preserving the user's condition order. Do not submit only the type predicate
  when Volume, notes, inclusion, child-count, or path is also a requested
  condition. For `A and (B or C)` or another nested boolean, switch to the
  structured route: use one `where` transform with `all`, `any`, and `not` only
  in the shapes returned by `query-schema`.
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
  simple `--all-results` only when explicitly requested. When a broad or
  expanding query has no bound, ask for a limit instead of inventing one.
  Reaching the bound makes the rows and every derived count/group/list
  potentially incomplete.

For example, a bounded descendant inventory of Sound candidates remains a
simple flag query:

```bash
python scripts/run.py gateway.py query-object --path '\Actor-Mixer Hierarchy\Default Work Unit\Combat' --select descendants --where-json '{"field":"type","operator":"=","value":"Sound"}' --take 24 --return-field id --return-field name --return-field type --return-field path --return-field @Volume --return-field notes --return-field OutputBus
```

Pure AND; `isIncluded` is appended last because it is filter-only:

```bash
python scripts/run.py gateway.py query-object --path '\Actor-Mixer Hierarchy\Default Work Unit\CombatMix' --select descendants --where-json '[{"field":"type","operator":"=","value":"Sound"},{"field":"@Volume","operator":"<=","value":-6.0},{"field":"notes","operator":":","value":"mix-review"},{"field":"isIncluded","operator":"=","value":true}]' --take 12 --return-field id --return-field name --return-field type --return-field path --return-field @Volume --return-field notes --return-field audioSource:language --return-field OutputBus --return-field isIncluded
```

Direct parents:

```bash
python scripts/run.py gateway.py query-object --type Sound --select parent --where-json '[{"field":"path","operator":":","value":"\\Actor-Mixer Hierarchy\\Default Work Unit\\ParentReview"},{"field":"type","operator":"=","value":"RandomSequenceContainer"},{"field":"childrenCount","operator":">=","value":3},{"field":"notes","operator":":","value":"parent-review"}]' --take 10 --return-field id --return-field name --return-field type --return-field path --return-field childrenCount --return-field notes --return-field OutputBus
```

Eight-level non-Project ownership:

```bash
python scripts/run.py gateway.py query-object --path '\Actor-Mixer Hierarchy\Default Work Unit\Player\Movement\Footstep_Run' --select ancestors --where-json '{"field":"type","operator":"!=","value":"Project"}' --take 8 --return-field id --return-field name --return-field type --return-field path --return-field childrenCount --return-field notes
```

When the request instead contains nested OR/NOT logic, run the offline schema
call and use the structured request:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 query-object --request-json '{"contract":"waapi-skill.object-query/v1","source":{"kind":"object","objects":[{"kind":"path","value":"\\Actor-Mixer Hierarchy\\Default Work Unit\\CombatMix"}]},"transforms":[{"kind":"select","expressions":[["descendants"]]},{"kind":"where","predicate":{"kind":"all","operands":[{"kind":"compare","path":["type"],"operator":"=","value":"Sound"},{"kind":"compare","path":["@Volume"],"operator":"<=","value":-6.0},{"kind":"any","operands":[{"kind":"compare","path":["notes"],"operator":":","value":"mix-review"},{"kind":"not","operand":{"kind":"truthy","path":["isIncluded"]}}]}]}},{"kind":"take","value":12}],"return":["id","name","type","path","@Volume","notes","audioSource:language","OutputBus","isIncluded"]}'
```

This is a versioned core subset, not a complete WAQL implementation. Python
program tests can prove that a valid request compiles deterministically and an
invalid request fails before transport; they do not prove that a newly added
construct has run successfully in real Wwise. Sort, aggregation, regex, or
another construct absent from `query-schema` remains unsupported rather than a
reason to write raw WAQL.

## Object types, live metadata, and fixed reads

Use `object-types` first for type discovery: it is version-pinned, offline, and
returns at most 20 rows per version by default. Narrow with `--query`,
`--object-type`, or `--limit`. `--summary-only` describes the complete catalog
and cannot combine with those filters. Use live `metadata types` only when the
running instance must be reflected again. For a machine-readable live summary,
`metadata types --summary-only` returns terminal `agent_result`;
compact-serialize that object exactly and stop. Do not rebuild it from
`normalized` or repeat the metadata command after success.

Use `metadata discover` when the user describes a property/reference by meaning
but no exact live name is already visible. Convert their intent to short natural
search phrases in repeated `--query`; do not ask for internal names. Select
exactly one scope: `--object-type` for a known new/imported type, `--class-id`
for a proven class id, or `--object` for an existing GUID/path or concrete
plug-in. Per-phrase `--limit` defaults to 5 and maxes at 8. For mutation
planning use 8 candidates for 1–2 phrases, 3 for 3–4, and 2 for 5–8. Keep
related phrases in one bounded invocation; if its dependency/byte ceiling is
reached, split groups without repeating already-proven phrases.

The Gateway searches live names and details, reports cache use, and may scan at
most 256 details when names lack lexical overlap. A complete `no_match` is a
bounded miss; for `partial`, retry once with broader technical phrases, then ask
one natural behavior question. Never guess. Only exact names from current live
discovery may enter closed `properties`/`references`; memory, translations, UI
labels, and presets are hints only. Honor returned dependencies in the same
request when clearly authorized, otherwise clarify. Preview revalidates.

Use fixed reads rather than reflected payloads:

- `profiler-game-objects` accepts non-negative milliseconds or exact
  `user`/`capture`, supports 2022.1–2025.1, and normalizes 2022
  `registrationTime` to `register_time`.
- `profiler-voice-contributions` supports all five versions, takes one uint32
  voice pipeline id and up to 64 ordered bus pipeline ids (omit them for dry
  path), and keeps DSF `feature_available`, `reported`, and `value` distinct.
- `project-default-work-units` keeps availability/reporting/value distinct for
  2025's `defaultWorkUnits` and `defaultImportWorkUnit`.

Each exposes its stable terminal `agent_result`; do not rebuild it.

## Exact-hop playback diagnosis

For a cross-reference diagnosis starting at one exact path, first resolve
`id,name,type,path`. Follow only returned relationship ids, one hop at a time,
with exact-id lookups. For an Event use bounded direct
`--select children --take 100`, not broad descendants or same-name search.
Request identity plus only fields needed at that hop: Action ->
`ActionType,Target`; Sound -> `OverrideOutput,activeSource,OutputBus`.

That Sound projection ends at `OutputBus`; do not add `@Volume` to the Sound
hop unless the user asks for the Sound's own volume. For source file/language,
query `originalFilePath,audioSource:language` on the exact returned
`activeSource` id. To distinguish routing from Bus mute, query `@Volume` only
on the exact Bus identities: first the returned `OutputBus` id, then the
requested comparison Bus path or id. Search is only for genuine discovery or
disambiguation, never to translate an already exact identity.

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
`--match-json` is applied per event; nonmatches do not consume count. The route
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

For `ak.wwise.core.soundbank.generated`, the gateway itself keeps the ordinary 10-second omitted-duration default. The Skill must explicitly pass gateway-global `--timeout 120` and tell the user that this subscription will use 120 seconds. This is an explicit Skill-selected timeout, not a different gateway default; a user-supplied positive finite duration or explicit no-time-limit bounded wait still takes precedence. Use exactly
`{"return":["id","name","type","path"]}` and set event count to requested
Bank × platform × language cells. Include `soundbank.name` or
`platform.name` in `--match-json` only when one explicit name is common to all
cells; otherwise omit `--match-json` instead of passing an empty object. Never
discover or inject a GUID for this predicate.

```bash
python scripts/run.py gateway.py --timeout 120 wait-topic ak.wwise.core.soundbank.generated --options-json '{"return":["id","name","type","path"]}' --event-count 2 --match-json '{"soundbank":{"name":"Weapons_Core"}}'
```

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

The five `ak.wwise.ui.commands.*` reads require the automatically detected
Authoring profile. Call live `getCommands` directly without default Console
`describe`; for offline schema audit only, use
`describe ak.wwise.ui.commands.getCommands --profile wwise-authoring-ui`.
Observe execution via bounded `wait-topic ak.wwise.ui.commands.executed`.
WwiseConsole returns `AUTHORING_HOST_REQUIRED`. Packaged command-id snapshots
(317/451/475/594/623 across 2021.1–2025.1) are environment evidence, not
runtime allowlists; mutations use fresh live `getCommands`.

`debug-wal-tree` is the only `ak.wwise.debug.getWalTree` route (2023.1–2025.1),
takes 1–256, validates/sorts nodes, and returns bounded `agent_result`.
`debug-validate-call` (2024.1–2025.1) validates but does not execute one
reflected request. Both private APIs may be unavailable in non-Debug builds.

## Selection and result boundary

For current selection, use live `selected` first. Report rows or explicit empty
selection. Add repeatable needed accessors; the Gateway retains
`id,name,type,path`, deduplicates, and bounds the projection. On a headless host
report the UI boundary; do not invent a fallback.

Keep return fields explicit as Gateway options. Preserve terminal
`agent_result` exactly for machine-readable output. Never convert malformed
responses into empty objects, Buses, projects, or selections.

There is no raw-client fallback for an ordinary user query. If the packaged
Gateway cannot perform it, report that the current Skill interface does not
cover it. Only an explicit Skill-development task may change the implementation.

<!-- WAAPI_QUERY_REFERENCE_END -->
