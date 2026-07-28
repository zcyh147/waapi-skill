# WAAPI query lane

Use this reference for read-only inspection: current project facts, current selection, hierarchy browsing, object lookup, property reads, WAQL-shaped discovery, bounded topic waits, and persistent topic streams.

## Query defaults

- Use only the skill-local executable gateway for user queries.
- Return a structured result or a clear blocker, not just “I called WAAPI”.
- Never use direct `WaapiClient`, inline Python, or a generated helper file.

## Standard query flow

1. Map current project/version to `gateway.py status`, Bus listing to `gateway.py buses`, and selection to `gateway.py selected`.
2. Run that command before any repository discovery.
3. Map object discovery to `gateway.py query-object`, packaged object-type
   discovery to `gateway.py object-types`, and live property/reference metadata
   to `gateway.py metadata`. Ordinary subscribe/listen/monitor wording uses one
   bounded `gateway.py wait-topic`; only explicit streaming or persistent intent
   uses `gateway.py stream-topic`.
4. Use offline `gateway.py capabilities --all-versions --summary-only` first for a broad support overview, then narrow a list with `--query`, `--category`, `--item-type`, `--family`, or `--route`. If a URI is already known and the user is asking about its route, schema, availability, or boundary, skip the list and use `gateway.py describe <uri>` directly. This discovery rule does not apply when the user explicitly asks to call one of the two reviewed reflection inventories in the next step.
5. The generic form is `gateway.py call <uri> --args-json '<object>' --options-json '<object>'`. It accepts only catalog rows whose current version reports `preferred_route: manifest_dispatch`; the reflected request and returned result are recursively validated and size/time bounded. The two zero-input reflection inventories remain fast routes: when the user explicitly asks to invoke `ak.wwise.waapi.getFunctions` or `ak.wwise.waapi.getTopics` with empty args/options, run that one `call` directly without `describe` or `capabilities`. Other known bounded reads may use `call` after `describe` confirms the route. Fixed functions return `FIXED_COMMAND_REQUIRED`, `ak.wwise.core.object.get` retains `QUERY_OBJECT_REQUIRED`, topics return `WAIT_TOPIC_REQUIRED`, and broader reads return `TRANSACTION_REQUIRED` rather than being inferred safe from a `get`-shaped name.

### Wwise 2025.1 Media Pool request mapping

`ak.wwise.core.mediaPool.getFields` and `ak.wwise.core.mediaPool.get` are reviewed direct reads with a closed two-call mapping. For a Media Pool field query, do not run `describe` or `capabilities`: call `getFields` first with exact empty args/options, then construct one `get` call from the rules below. Both are generic `call` commands: the second command begins exactly `gateway.py --version 2025.1 call ak.wwise.core.mediaPool.get`. There is no `mediaPool.get` gateway subcommand; never omit `call` or shorten the URI. Do not ask the user to provide schema field names.

1. Bind field concepts only from the returned `getFields` strings. The standard bindings are exact: file/name is `Filename`, duration is `WAV/Duration`, sample rate is `WAV/Sample Rate`, bit depth is `WAV/Bit Depth`, and channel count is `WAV/Channels`. `Filename` values are the basename without the file extension; use `Path` when the extension or full path matters, and do not append `.wav` to a `Filename` regex. For an IXML concept such as Scene or Take, select the one returned field below `BWFXML/` whose final path component equals that concept case-insensitively, then preserve the returned spelling exactly. Stop on a missing or ambiguous binding.
2. Build `args` with keys `databases`, `filters`, and `maxResults` only. Preserve explicitly named database paths and their order. Preserve the user's predicate order; expand one range into its lower predicate followed by its upper predicate. Every predicate is exactly `{"type":"field","field":<bound field>,"operator":<operator>,"value":<value>}` with no `weight`. Use `equals` / `notEquals` for equality, `contains` for containment candidates, `startsWith` / `endsWith` for prefixes or suffixes, `matchesRegex` for a supplied regular expression, `lessThan` / `greaterThan` for exclusive limits, and `lessThanOrEqual` / `greaterThanOrEqual` for inclusive limits. “Between/from A to B” is inclusive at both ends. Convert kHz to integer Hz, mono/stereo to `1`/`2`, bit depth to its integer, and seconds to a JSON number; write whole-second duration values in decimal form such as `8.0`, not `8`. Do not add `searchText`, paging, sort, audio-description, or similarity arguments; sort or group the bounded returned rows when reporting.
3. Normally use the user's explicit maximum as `maxResults`; when it is omitted, use `100`. The accepted range is 1 through 200, with at most 16 filters and 8 databases. One exact exception applies when the user requires a case-sensitive literal substring or excludes case-only variants: supported Wwise 2025.1 builds can evaluate both `contains` and ordinary regular expressions case-insensitively, so use the literal in a `contains` candidate predicate, set raw `maxResults` to `200`, and add `--post-filter-json` with exactly `{"field":<bound field>,"operator":"containsCaseSensitive","value":<same literal>,"limit":<the user's maximum or 100>}` to the `mediaPool.get` call. The packaged Gateway compares the returned field values without case folding and returns only that filtered, limited array as terminal `agent_result`; do not filter or rewrite it yourself. This post-filter is valid only for `Filename`, requires the matching `contains` predicate and returned `Filename` field, and fails with `MEDIA_POOL_POST_FILTER_INCOMPLETE` instead of claiming completeness when the 200-row candidate ceiling is reached.
4. Build `options.return` with this fixed eight-field prefix, in this exact order: `Path`, `FileId`, `Db`, `Filename`, `WAV/Duration`, `WAV/Sample Rate`, `WAV/Bit Depth`, `WAV/Channels`. This prefix is mandatory: never omit, shorten, or reorder it even when the user asks to report only some of those fields. The exact JSON prefix is `{"return":["Path","FileId","Db","Filename","WAV/Duration","WAV/Sample Rate","WAV/Bit Depth","WAV/Channels"]}`. Append each non-standard bound field needed by an explicit filter, grouping, sorting, or report request in first-mention order, without duplicates. Do not add any other option key; the complete projection is limited to 32 unique fields.
5. Invoke `mediaPool.get` once with those exact args/options, using the exact CLI shape `python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2025.1 call ak.wwise.core.mediaPool.get --args-json '<args>' --options-json '<options>'` (plus the reviewed `--post-filter-json` only when rule 3 requires it). If the user asks which returned candidates are unreferenced, use the closed original-file reference classification below. Never replace a complete returned `Path` with a basename or a guessed host path, never run the old unfiltered 1000-row AudioFileSource projection, and never perform this join in model-authored code.
6. Report the gateway result using the fields the user requested. When the user asks to keep, list, or report each result's database or path, pair every row with its returned `Db` name and reproduce the complete returned `Path`; never replace path segments with `...` or a shortened display path. On `API_NOT_FOUND`, `MANIFEST_NOT_FOUND`, `FIXED_COMMAND_REQUIRED`, `WAIT_TOPIC_REQUIRED`, `TRANSACTION_REQUIRED`, `UNSUPPORTED_BY_SKILL_INTERFACE`, connection failure, or another structured error, stop and report the boundary.

#### Closed original-file reference classification

This is a Wwise `2025.1`-only follow-up to the reviewed Media Pool read, not a general object-query or cross-version recipe.

- Run the match only after one successful `mediaPool.get` returns between 1 and 64 candidate rows. With zero candidates, report that empty result without a match command. With more than 64, report the candidate-limit boundary; do not silently truncate, split the candidates across repeated scans, or select a convenient subset.
- Take each candidate's exact complete returned `Path`, sort those strings lexicographically, and pass each once in that order. Each path is limited to 1024 UTF-8 bytes and must be drive-absolute (`Y:\...`), an ordinary UNC path with nonempty server/share/file components (`\\server\share\...`), or POSIX-absolute (`/...`). Never pass a basename, relative path, traversal path, `\\?\`/`\\.\` device path, or locally guessed translation. Do not pre-normalize or de-duplicate the values: the Gateway normalizes slash spelling and drive/UNC case, keeps POSIX case significant, and rejects any normalized collision rather than hiding one candidate.
- Invoke exactly one command with this fixed shape, repeating only the final candidate option:

  ```bash
  python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2025.1 query-object --type AudioFileSource --take 1000 --match-original-file-path '<first-complete-returned-Path>' --match-original-file-path '<second-complete-returned-Path>'
  ```

  Do not add `--where-json`, `--select`, `--all-results`, or `--return-field`. The Gateway owns the fixed `id,path,originalFilePath` projection, validates every returned row and duplicate object id, performs the complete normalized join, and emits no raw AudioFileSource inventory for model-side filtering.
- A successful payload keeps `agent_result` as its final top-level field. That object has contract `waapi-skill.original-file-reference-match/v1`, `scan_complete: true`, `scanned_audio_source_count`, `scan_limit: 1000`, and one `candidates` entry for every input path in the same order. Every entry contains its exact input `originalFilePath`, `classification` (`referenced` or `unreferenced`), exact full-scan `reference_count`, `references`, and `references_truncated`. `references` contains at most four `{id,path}` details sorted by path case-insensitively and then id case-insensitively; `references_truncated: true` means only that detail list was shortened, not that the classification or count is uncertain. An unreferenced entry has count `0`, an empty detail list, and `references_truncated: false`.
- Classify only when the outer command succeeds and that terminal result says `scan_complete: true`. A 1000-row scan returns `ORIGINAL_FILE_REFERENCE_SCAN_INCOMPLETE` with no `agent_result`; malformed or oversized paths/rows, duplicate ids, normalized candidate collisions, WAAPI failure, or any other structured boundary likewise proves no unreferenced claim. Stop instead of retrying with a broader query, another batch, direct `WaapiClient`, inline Python, or a helper file.

## Query examples

- current Wwise version / current project
- current selection
- object lookup by name, path, id, GUID, or semantic family
- hierarchy browsing under a parent path
- read-only property inspection
- bounded topic waits such as a single `object.created` wait
- explicitly requested persistent, event-by-event topic streams

Topic waits and streams belong here because observing a Topic is read-only and never authorizes the project-changing action that might publish it.

## Fixed query commands

Run from the Skill directory:

```bash
python scripts/run.py gateway.py query-object --path '\Events\Default Work Unit' --return-field id --return-field name --return-field type --return-field path
python scripts/run.py gateway.py query-object --type Event --where-json '{"field":"name","operator":":","value":"Play"}' --take 100
python scripts/run.py gateway.py query-object --search 'ExactName' --where-json '{"field":"name","operator":"=","value":"ExactName"}' --take 1 --return-field id --return-field name --return-field type --return-field path
python scripts/run.py gateway.py --version 2025.1 query-object --type AudioFileSource --take 1000 --match-original-file-path '<first-complete-returned-Path>' --match-original-file-path '<second-complete-returned-Path>'
python scripts/run.py gateway.py --version 2022.1 object-types --query 'audio source' --object-type WObject --limit 20
python scripts/run.py gateway.py --version 2022.1 object-types --summary-only
python scripts/run.py gateway.py metadata types --summary-only
python scripts/run.py gateway.py metadata property-info --object '{GUID}' --property Volume
python scripts/run.py gateway.py project-default-work-units
python scripts/run.py gateway.py --version 2022.1 profiler-game-objects --time capture
python scripts/run.py gateway.py --version 2025.1 profiler-voice-contributions --time capture --voice-pipeline-id 17 --bus-pipeline-id 21 --bus-pipeline-id 22
python scripts/run.py gateway.py --version 2025.1 debug-wal-tree --take 128
python scripts/run.py gateway.py --version 2025.1 debug-validate-call ak.wwise.core.object.get --args-json '{"from":{"id":["{GUID}"]}}' --options-json '{"return":["id","name"]}'
python scripts/run.py gateway.py wait-topic ak.wwise.core.object.created --match-json '{"object":{"id":"{GUID}"}}'
python scripts/run.py gateway.py --timeout 45 wait-topic ak.wwise.core.object.created --match-json '{"object":{"id":"{GUID}"}}'
python scripts/run.py gateway.py wait-topic ak.wwise.core.object.created --no-timeout --match-json '{"object":{"id":"{GUID}"}}'
python scripts/run.py gateway.py stream-topic ak.wwise.core.object.created --options-json '{}' --match-json '{"object":{"id":"{GUID}"}}'
python scripts/run.py gateway.py --timeout 300 stream-topic ak.wwise.core.object.created --match-json '{"object":{"id":"{GUID}"}}'
python scripts/run.py gateway.py --timeout 120 wait-topic ak.wwise.core.soundbank.generated --options-json '{"return":["id","name","type","path"]}' --event-count 2 --match-json '{"soundbank":{"name":"Weapons_Core"}}'
python scripts/run.py gateway.py capabilities --all-versions --query object.get --limit 20
python scripts/run.py gateway.py describe ak.wwise.core.object.get --all-versions
python scripts/run.py gateway.py --version <supported-version> call ak.wwise.waapi.getFunctions --args-json '{}' --options-json '{}'
python scripts/run.py gateway.py --version <supported-version> call ak.wwise.waapi.getTopics --args-json '{}' --options-json '{}'
python scripts/run.py gateway.py --version 2022.1 call ak.soundengine.getState --args-json '{"stateGroup":"Gameplay"}' --options-json '{}'
```

### Complex object inventories

Plan one bounded query that safely narrows the candidate set, then finish any
unsupported relationship or presentation logic from that one complete result.

- Treat every `--return-field` token as case-sensitive syntax, not a display
  label. Common mappings are Volume -> `@Volume`, Pitch -> `@Pitch`, notes or
  remarks -> `notes`, and Output Bus -> `OutputBus` (never `@OutputBus`). Source language -> `audioSource:language`, parent -> `parent`, and inclusion ->
  `isIncluded`, and direct child count -> `childrenCount`. Never lowercase,
  translate, or add/remove `@`. Because explicit
  projections replace the defaults, list `id`, `name`, `type`, and `path` first,
  followed by every field needed for filtering, sorting, grouping, and reporting.
  After those four identity fields, keep fields explicitly requested for the
  report, grouping, or sorting in their first-mention order, then append any additional
  filter-only fields. This is the canonical projection order; do not reshuffle
  it based on implementation convenience. Determine that order by scanning the
  user's requested output left to right; a derived field such as
  `audioSource:language` stays where the user first mentioned language and is not
  moved because of how it is implemented. For example, “parent path, then each
  direct Sound's path, language, Volume, and notes” projects exactly
  `id`, `name`, `type`, `path`, `parent`, `audioSource:language`, `@Volume`,
  `notes`.
- Push every supported condition shared by all requested rows into
  `--where-json`. A predicate array means AND only. For `A and (B or C)`, push
  the common `A` and keep the OR for result-side filtering; for example, when
  every candidate must be a Sound and the final rule is Volume below a threshold
  OR notes containing a marker, push exactly
  `{"field":"type","operator":"=","value":"Sound"}`. Do not turn OR,
  relative depth, direct-child relationships, sorting, or aggregation into
  invented WAQL or a narrower predicate that could discard a valid branch.
- Words such as "simultaneously", "all of the following conditions", or
  “同时满足” introduce a pure AND.
  Put every supported conjunct into one `--where-json` array, preserving the
  user's condition order. Do not submit only the type predicate and leave a
  supported Volume, notes, inclusion, child-count, or path conjunct for final
  filtering. For example, Sound AND Volume at most -6 AND notes containing
  `mix-review` AND included is exactly
  `[{"field":"type","operator":"=","value":"Sound"},{"field":"@Volume","operator":"<=","value":-6.0},{"field":"notes","operator":":","value":"mix-review"},{"field":"isIncluded","operator":"=","value":true}]`.
- "Shared by all requested rows" applies to the complete final row set, not
  just one branch of a relationship request. If the user asks for parent
  containers together with their direct child Sounds, the requested rows have
  mixed types: omit a `type=Sound` or container-only predicate, fetch the one
  bounded mixed-type descendant set, request `parent`, and identify both
  branches from those returned rows. A type predicate in that case would erase
  one required side of the relationship before result-side filtering.
- A requested Sound language can be exposed on its directly owned
  `AudioFileSource` row rather than on the Sound row itself. Within the same
  complete bounded result, associate a language only when exactly one returned
  `AudioFileSource` has `parent.id` exactly equal to that Sound's `id`; use that
  source row's `audioSource:language` name (or its scalar value) for the Sound.
  Do not report the language as missing when this exact child-source evidence
  exists, and do not associate by row position, similar names, or path prefixes.
  If there is no exact source or the exact sources disagree, report the
  language as unresolved rather than guessing.
- For a reverse direct-parent request such as "from the Sounds, find their
  direct parents", use the child type as the broad source and the packaged
  parent transform: `--type Sound --select parent`. Predicates then describe
  the selected parent rows; include a returned-parent `path` predicate to keep
  them inside a named subtree, followed by the requested parent type,
  child-count, and notes predicates. Do not replace this with a descendant
  inventory plus a requested `parent` field when the user explicitly asks for
  direct-parent selection.
- A reverse-parent result contains one returned parent row for each matching
  source object, so repeated parent rows are the evidence for source-to-parent
  coverage. Count those rows before deduplicating the parent report. Treat
  `childrenCount` only as the number of all direct child objects; never relabel
  its value or a sum of it as a confirmed count of source-type objects such as
  Sounds. When the raw row count reaches `--take`, report that confirmed source
  count, say explicitly that the returned list and every summary derived from
  it may be incomplete, and keep any separately reported `childrenCount` total
  explicitly labeled as direct child objects. Do not narrow the disclosure to
  only the source rows: a bounded reverse-parent result also means that the
  deduplicated parent list and parent count may be incomplete.
- For an ownership chain from one exact object, use that exact object as the
  source and `--select ancestors`. If the user says to exclude Project, include
  the exact supported predicate
  `{"field":"type","operator":"!=","value":"Project"}`; do not assume the
  ancestor transform removes Project by itself. Copy the requested maximum
  depth to `--take`, request every ownership field needed for the report, and
  present the returned chain from nearest parent to farthest ancestor without
  mixing same-name objects from other branches.
- Apply the remaining relative-depth, direct-parent, OR, deduplication, sorting,
  and grouping rules only to the bounded rows returned by that one command. For
  a relative-depth limit below one exact root, derive depth from each returned
  `path`, counting the root's direct children as relative depth 1. The `path` is
  sufficient for that calculation; do not add `parent` solely to calculate
  relative depth. Request `parent` only when the user needs a parent identity or
  a direct parent-child relationship, then identify direct children by the
  returned `parent` identity. Do not issue a second query merely to redo this
  result-side processing.
- When the user supplies a numeric maximum, copy that exact number to `--take`;
  never replace it with 24, 100, or 1000. Use `--all-results` only for an explicit
  unbounded request. If a transform needs a bound but the request supplies no
  number and is not explicitly unbounded, ask for a limit instead of inventing
  one. If the returned row count reaches the bound, say that the result may be
  incomplete. Apply that disclosure to the returned set and every derived
  count, grouping, or deduplicated list, not only to the pre-transform source.

For example, a bounded descendant inventory of Sound candidates that will be
post-filtered by Volume, notes, and relative depth uses this shape:

```bash
python scripts/run.py gateway.py query-object --path '\Actor-Mixer Hierarchy\Default Work Unit\Combat' --select descendants --where-json '{"field":"type","operator":"=","value":"Sound"}' --take 24 --return-field id --return-field name --return-field type --return-field path --return-field @Volume --return-field notes --return-field OutputBus
```

A pure-AND review that also reports language and groups by Output Bus uses this
canonical shape; `isIncluded` is appended last because it is filter-only:

```bash
python scripts/run.py gateway.py query-object --path '\Actor-Mixer Hierarchy\Default Work Unit\CombatMix' --select descendants --where-json '[{"field":"type","operator":"=","value":"Sound"},{"field":"@Volume","operator":"<=","value":-6.0},{"field":"notes","operator":":","value":"mix-review"},{"field":"isIncluded","operator":"=","value":true}]' --take 12 --return-field id --return-field name --return-field type --return-field path --return-field @Volume --return-field notes --return-field audioSource:language --return-field OutputBus --return-field isIncluded
```

A bounded reverse-parent review uses the direct transform instead of rebuilding
the relation from descendants:

```bash
python scripts/run.py gateway.py query-object --type Sound --select parent --where-json '[{"field":"path","operator":":","value":"\\Actor-Mixer Hierarchy\\Default Work Unit\\ParentReview"},{"field":"type","operator":"=","value":"RandomSequenceContainer"},{"field":"childrenCount","operator":">=","value":3},{"field":"notes","operator":":","value":"parent-review"}]' --take 10 --return-field id --return-field name --return-field type --return-field path --return-field childrenCount --return-field notes --return-field OutputBus
```

An eight-level non-Project ownership chain from one exact Sound uses:

```bash
python scripts/run.py gateway.py query-object --path '\Actor-Mixer Hierarchy\Default Work Unit\Player\Movement\Footstep_Run' --select ancestors --where-json '{"field":"type","operator":"!=","value":"Project"}' --take 8 --return-field id --return-field name --return-field type --return-field path --return-field childrenCount --return-field notes
```

`capabilities` returns at most 50 compact rows by default, including each row's public route and transaction boundary. Use `--limit 0` only when every matching row is explicitly needed, and add `--detail` only for nested interface, schema-summary, policy, and evidence auditing. `describe` intentionally returns only the compact schema summary. Add `--full-schema` only when the task requires the complete reflected args/options/result schema; do not pay that context cost for ordinary route or availability checks.

Use `object-types` first for object-type discovery. It searches a compact,
version-pinned catalog without connecting to Wwise and returns at most 20 rows
per version by default. Add `--query`, `--object-type`, or a bounded `--limit`
instead of loading every type into context. Use live `metadata types` only when
the user explicitly needs the currently running Authoring instance reflected
again. `--summary-only` describes the complete packaged catalog and therefore
cannot be combined with `--query` or `--object-type`.

For a machine-readable live object-type summary, use the fixed
`metadata types --summary-only` route. Its successful payload exposes the
bounded projection as `agent_result`; compact-serialize that object exactly into
the requested result envelope and stop. Do not derive a replacement from
`normalized`, alter its keys or values, or repeat the metadata command after success.
This fixed-read projection follows the same terminal `agent_result`
rule as a successful transaction payload.

Use the three version-stable fixed reads instead of composing their reflected
payloads. `profiler-game-objects` accepts only a non-negative millisecond time
or the exact `user` / `capture` cursor and is available in Wwise 2022.1–2025.1;
it normalizes the 2022.1 `registrationTime` spelling to the same public
`register_time` shape used for later versions.
`profiler-voice-contributions` is available in all five versions, requires one
unsigned 32-bit voice pipeline ID, and accepts up to 64 repeated ordered bus
pipeline IDs; omit the bus flags for the explicit dry path. Its DSF projection
keeps `feature_available`, `reported`, and `value` separate, so older versions
never receive a fabricated zero. `project-default-work-units` likewise keeps
availability, reporting, and value separate for the `defaultWorkUnits` and
`defaultImportWorkUnit` fields introduced in Wwise 2025.1. Each successful
command exposes its stable projection as the terminal `agent_result`; do not
rebuild it from the raw version-specific fields.

`query-object` accepts exactly one source: `--path`, `--object-id`, `--type`, `--search`, or `--query`. Here `--query` means an existing Wwise Query Editor object identified by a canonical `{GUID}` or an absolute `\Queries\...` path with single backslash hierarchy separators. It never accepts raw WAQL such as `from type Sound`; use the other closed source and transform flags instead. Supported `--select` values are `descendants`, `ancestors`, `referencesTo`, `children`, and `parent`; `this` and `owner` remain outside the packaged boundary. In `--where-json`, `=` is exact equality and `:` is a contains/match predicate; when the user says a field must equal an exact value, use `=` even if the source is `--search`. Every broad source (`--type`, `--search`, `--query`) and every `--select` transform requires either `--take N`, where `N` is between `0` and `1000`, or the explicit `--all-results` opt-in. `--take` and `--all-results` cannot be combined. Use `--all-results` only when the user explicitly requests an unbounded result set. Exact path/GUID lookup without a transform remains one-object bounded and needs neither flag. A bounded success that exceeds its `take`, an untransformed exact lookup that returns more than one row, or a fixed `buses` result above 1000 rows is rejected as protocol drift; `--all-results` remains unbounded for genuinely broad queries. The fixed `buses` command uses `take 1000`, reports that bound in its JSON, and marks a 1000-row response as possibly truncated. The gateway defaults to `id,name,type,path`; supplying any `--return-field` replaces that default list, so repeat the flag for every field needed. An untransformed exact `--path` lookup must return `path`, and an exact `--object-id` lookup must return `id`; the gateway normalizes path separators/case or GUID case and rejects a mismatched returned identity. For exact identity inspection, keep those four fields explicit for an exact path/GUID identity lookup. Successful object queries must return a JSON object containing a `return` array of JSON object rows; an invalid response shape or bound is a structured error, never an empty-result substitute. A successful selection must likewise contain an explicit `objects` array whose every row is an object; only `objects: []` means a valid empty selection. `selected` always retains `id,name,type,path` and accepts repeatable `--return-field` flags for up to 32 unique manifest-validated accessors when the current-selection answer needs properties or related-object fields.

`wait-topic` accepts only an exact URI in the reviewed topic allowlist. Its `--event-count` defaults to `1` and is restricted to `1..64`. Route ordinary vague requests to subscribe, listen, monitor, or keep an eye on a Topic here. An ordinary omitted duration uses 10 seconds; before invoking the gateway, tell the user naturally that this invocation will use that default and that they may request another duration. A user-supplied positive finite duration is authoritative: convert its units to seconds without rounding and place the exact value in the gateway-global `--timeout <positive-finite-seconds>` position before `wait-topic`. Do not silently clamp it to the ordinary default or to a topic recommendation. When the user explicitly asks for no time limit but still requests a fixed event count, omit global `--timeout`, add the subcommand flag `--no-timeout`, and tell them that the wait continues until all requested matching events arrive or they cancel it. Do not combine the two flags, and do not infer `--no-timeout` from ordinary listening language.

One end-to-end finite timeout covers subscription setup and collection of the full requested count. A Topic row's packaged `execution_contract.timeout_seconds` is its default or recommendation, not a maximum; never reapply it as a cap after the user has selected another policy. `--no-timeout` removes that waiting deadline, but it does not create an unlimited output stream: collection still stops at 1–64 matching events, the command still returns one terminal JSON document, and the complete dispatcher collection still shares the topic execution contract's 256 KiB JSON result ceiling. `--match-json` is a recursive payload subset applied independently to every candidate event, and non-matching events do not consume the requested count. The route always unsubscribes after success, timeout, or user cancellation. Default single-event mode preserves the existing `event` result. Multi-event mode returns ordered `events`, `event_count`, and `requested_event_count`, with every payload validated against that version's reflected `publishSchema`. Collection stops after the requested number of matches, so it does not by itself prove that no later `(N+1)` event exists; an exact-cardinality test needs a runner-owned publisher/oracle for that assertion.

Select `stream-topic` only when the user explicitly asks for a stream, continuous or persistent monitoring, event-by-event real-time output, “实时逐条”, “流式”, “持续”, “一直监听”, or “不要收到后退出”. It establishes one persistent subscription rather than repeatedly opening bounded waits, emits each matching event immediately as one compact flushed NDJSON record, and by default continues until the user cancels it or a bounded low-frequency health check detects a lost or replaced WAAPI host. A user-supplied positive finite duration goes in the gateway-global `--timeout <positive-finite-seconds>` position and ends the stream normally when elapsed. It accepts reviewed `--options-json` and the same recursive `--match-json`; non-matching events are ignored without reopening the subscription.

Every streamed event is validated against that version's reflected `publishSchema` and its per-event size ceiling before emission. The internal event buffer is bounded and overflow fails closed instead of silently dropping an event. Success, finite-duration completion, cancellation, overflow, or error always attempts to unsubscribe the one live subscription and emits one terminal NDJSON record stating why the stream ended. The stream may be time-unbounded, but no individual event, buffer, or output record is unbounded. Relay event records as they appear; do not wait for the terminal record to summarize earlier events, restart the command between events, or present ordinary `wait-topic` as equivalent zero-gap streaming.

The five `ak.wwise.ui.commands.*` APIs use the automatically selected
Authoring host profile. For a command inventory, call
`ak.wwise.ui.commands.getCommands` directly through the live bounded `call`
route; do not first use the default Console-profile `describe`, because
Wwise 2024.1 and 2025.1 obtain these schemas from the Authoring supplement.
For an explicit offline schema audit, use
`gateway.py --version <version> describe ak.wwise.ui.commands.getCommands --profile wwise-authoring-ui`;
that option inspects the packaged catalog only and cannot override the live
profile.
Observe executed commands with bounded
`wait-topic ak.wwise.ui.commands.executed`. The gateway derives the profile
only from live `getInfo.isCommandLine`; WwiseConsole returns
`AUTHORING_HOST_REQUIRED` without dispatching the requested UI API.

The packaged observed command-ID snapshots contain 317 / 451 / 475 / 594 / 623
rows for Wwise 2021.1 through 2025.1. They reflect the project, installed
plug-ins, registered add-ons, and exact Wwise build present during collection.
They are not cross-machine allowlists. A modifying UI-command operation always
uses a fresh live `getCommands` result immediately before dispatch.

The gateway itself keeps the ordinary 10-second omitted-duration default for `ak.wwise.core.soundbank.generated` too. At the Skill layer, when the user omits a duration for this Topic, explicitly pass gateway-global `--timeout 120` because the matching generation may need to finish after the subscription is established. Before invoking the gateway, tell the user that this subscription will use 120 seconds. This is an explicit Skill-selected timeout, not a different gateway default. A user-supplied positive finite duration or explicit no-time-limit bounded wait still takes precedence exactly as described above; explicit persistent streaming instead uses `stream-topic` and its streaming duration policy. Use exactly `{"return":["id","name","type","path"]}` as the subscription options. Those four fields provide the bounded SoundBank identity needed for the user-facing result and are the closed route default; do not vary them from case wording. Set `--event-count` to the number of requested Bank × platform × language cells. Build `--match-json` only from names explicitly present in the user's request: include `soundbank.name` when one Bank name is common to every requested cell, and include `platform.name` when one platform name is common to every cell. If neither dimension has one common name, omit `--match-json` instead of passing an empty object. Never discover or inject a GUID only to construct the subscription predicate; exact GUID correlation belongs to the trusted post-return oracle, not to the model-authored command.

Choose the SoundBank Topic from the requested observation. Use
`ak.wwise.core.soundbank.generated` for per-Bank × platform × language result
events. Use `ak.wwise.core.soundbank.generationDone` only for the overall
generation-cycle or log notification. `generationDone` is not proof that every
Bank succeeded or that requested artifacts exist; when success or artifact
completion matters, use the generating operation's terminal verification
instead of upgrading that Topic event into business evidence. A `describe` of
either Topic returns the same distinction under
`interface.selection_guidance`.

`object.created` fires before the final name is applied, so do not match it by the requested name. An ActorMixer create reports event type `ActorMixer` in Wwise 2021.1-2024.1 but `PropertyContainer` in Wwise 2025.1; use the version-specific type as a bounded predicate and correlate `event.object.id` with trusted publisher evidence when exact ownership matters. `ak.wwise.debug.assertFailed` is available through the same bounded `wait-topic` route and its versioned publish schema; it is a diagnostic event, not proof that an assertion request was safely recovered. Any unreviewed future topic returns `UNSUPPORTED_BY_SKILL_INTERFACE` before subscription.

`debug-wal-tree` is the only route for `ak.wwise.debug.getWalTree` and is
available in Wwise 2023.1–2025.1. It takes `1..256`, validates every returned
node, sorts by the reflected node-map key, and returns only the bounded
projection under terminal `agent_result`. `debug-validate-call` is available
in Wwise 2024.1–2025.1 and asks Wwise to validate, not execute, one exact
reflected function request. Supply only the sections the user actually wants
validated; omitted args/options/result sections remain omitted. Both APIs are
private/debug-build surfaces and may still be rejected by a non-Debug Wwise
binary even when their versioned schema exists.

An invalid response shape is a structured error. It must never be converted into an empty query, Bus list, project, or selection.

## Current selection boundary

For `ak.wwise.ui.getSelectedObjects`, prefer the live selected-object query first when the user asks what is currently selected.

- If the endpoint returns selected object rows, report them clearly.
- If the endpoint returns an empty selection, report that explicit empty selection.
- When the user also asks for selected-object properties or related fields, add one `--return-field` per required accessor. The gateway always retains `id`, `name`, `type`, and `path`, deduplicates additions, and rejects an oversized or malformed projection before connecting.
- If the connected endpoint is a headless or command-line WwiseConsole instance where the UI selection API is unavailable, report that boundary clearly and stop. Do not drift into repo/docs research and do not invent a fallback selection result.

## Dispatcher rules

- Do not hard-code a fixed API map in the prompt if versioned manifests and deferred resources can resolve the capability.
- Keep return fields explicit when needed, but pass them as dispatcher `options`, not as raw positional WAAPI arguments.
- The gateway's omitted-duration default is 10 seconds for every ordinary `wait-topic`. For a SoundBank generation notification with no user-supplied duration, the Skill explicitly passes `--timeout 120` and reports that choice. Preserve a user-supplied finite duration exactly; use `--no-timeout` only for an explicit no-time-limit bounded wait. Use `stream-topic` only for explicit persistent/event-by-event intent; it defaults to cancellation and accepts global `--timeout` for a finite duration.
- The generic read-only CLI contract is the versioned `manifest_dispatch` set, not an open raw-call surface. The two reflection-list rows are direct one-command fast routes; other rows need their known URI and reflected args/options. Global `--version`, `--timeout`, and `--evidence-dir` precede `call`, while `--args-json`, `--options-json`, `--dry-run`, and the hidden compatibility-only `--allow-destructive` follow the URI. Fixed functions, topics, transactions, exclusions, and unreviewed rows are rejected before business dispatch. `--dry-run`, `--allow-destructive`, and `WWISE_DESTRUCTIVE=1` cannot bypass that routing decision.
- Every JSON option is parsed before connecting and is strict and bounded: duplicate keys, non-finite numbers, invalid Unicode, oversized documents/strings, excessive nesting, and excessive node counts fail closed. Do not retry by moving the same payload into inline Python or a helper file.

## Failure rule

There is no raw-client fallback for an ordinary user query. If the packaged gateway cannot perform the request, say that the current Skill interface does not cover it. Only a separate, explicit Skill-development task may change the implementation.
