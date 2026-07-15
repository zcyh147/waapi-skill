# WAAPI query lane

Use this reference for read-only inspection: current project facts, current selection, hierarchy browsing, object lookup, property reads, WAQL-shaped discovery, and bounded topic waits.

## Query defaults

- Use only the skill-local executable gateway for user queries.
- Return a structured result or a clear blocker, not just “I called WAAPI”.
- Never use direct `WaapiClient`, inline Python, or a generated helper file.

## Standard query flow

1. Map current project/version to `gateway.py status`, Bus listing to `gateway.py buses`, and selection to `gateway.py selected`.
2. Run that command before any repository discovery.
3. Map object discovery to `gateway.py query-object`, metadata discovery to `gateway.py metadata`, and one bounded subscription to `gateway.py wait-topic`.
4. Use offline `gateway.py capabilities --all-versions --summary-only` first for a broad support overview, then narrow a list with `--query`, `--category`, `--item-type`, `--family`, or `--route`. If a URI is already known and the user is asking about its route, schema, availability, or boundary, skip the list and use `gateway.py describe <uri>` directly. This discovery rule does not apply when the user explicitly asks to call one of the two reviewed reflection inventories in the next step.
5. The generic form is `gateway.py call <uri> --args-json '<object>' --options-json '<object>'`, but its executable surface is intentionally limited to the two zero-input reflection inventories `ak.wwise.waapi.getFunctions` and `ak.wwise.waapi.getTopics`, whose packaged route is already fixed as `preferred_route: manifest_dispatch`. When the user explicitly asks to invoke either exact URI with empty args and options, run that `call` directly as the first and only gateway command: do not run `describe` or `capabilities` first. Their results are validated as bounded URI arrays and compared with the packaged manifest. Every other read needs a dedicated fixed/bounded command before it can become executable; reflection or a `get`-shaped name is not enough. Fixed functions return `FIXED_COMMAND_REQUIRED`, `ak.wwise.core.object.get` retains the narrower `QUERY_OBJECT_REQUIRED`, and topic URIs return `WAIT_TOPIC_REQUIRED`.
6. Report the gateway result. On `API_NOT_FOUND`, `MANIFEST_NOT_FOUND`, `FIXED_COMMAND_REQUIRED`, `WAIT_TOPIC_REQUIRED`, `TRANSACTION_REQUIRED`, `UNSUPPORTED_BY_SKILL_INTERFACE`, connection failure, or another structured error, stop and report the boundary.

## Query examples

- current Wwise version / current project
- current selection
- object lookup by name, path, id, GUID, or semantic family
- hierarchy browsing under a parent path
- read-only property inspection
- bounded topic waits such as a single `object.created` wait

Topic waits belong here by default when they are bounded inspection behavior rather than a project-changing workflow.

## Fixed query commands

Run from the Skill directory:

```bash
python scripts/run.py gateway.py query-object --path '\Events\Default Work Unit' --return-field id --return-field name --return-field type --return-field path
python scripts/run.py gateway.py query-object --type Event --where-json '{"field":"name","operator":":","value":"Play"}' --take 100
python scripts/run.py gateway.py query-object --search 'ExactName' --where-json '{"field":"name","operator":"=","value":"ExactName"}' --take 1 --return-field id --return-field name --return-field type --return-field path
python scripts/run.py gateway.py metadata types --summary-only
python scripts/run.py gateway.py metadata property-info --object '{GUID}' --property Volume
python scripts/run.py gateway.py --timeout 10 wait-topic ak.wwise.core.object.created --match-json '{"object":{"id":"{GUID}"}}'
python scripts/run.py gateway.py capabilities --all-versions --query object.get --limit 20
python scripts/run.py gateway.py describe ak.wwise.core.object.get --all-versions
python scripts/run.py gateway.py --version <supported-version> call ak.wwise.waapi.getFunctions --args-json '{}' --options-json '{}'
python scripts/run.py gateway.py --version <supported-version> call ak.wwise.waapi.getTopics --args-json '{}' --options-json '{}'
```

`capabilities` returns at most 50 compact rows by default, including each row's public route and transaction boundary. Use `--limit 0` only when every matching row is explicitly needed, and add `--detail` only for nested interface, schema-summary, policy, and evidence auditing. `describe` intentionally returns only the compact schema summary. Add `--full-schema` only when the task requires the complete reflected args/options/result schema; do not pay that context cost for ordinary route or availability checks.

For a machine-readable object-type summary, use the fixed `metadata types --summary-only` route. Its successful payload exposes the bounded projection as `agent_result`; compact-serialize that object exactly into the requested result envelope and stop. Do not derive a replacement from `normalized`, alter its keys or values, or repeat the metadata command after success. This fixed-read projection follows the same terminal `agent_result` rule as a successful transaction payload.

`query-object` accepts exactly one source: `--path`, `--object-id`, `--type`, `--search`, or `--query`. Here `--query` means an existing Wwise Query Editor object identified by a canonical `{GUID}` or an absolute `\Queries\...` path with single backslash hierarchy separators. It never accepts raw WAQL such as `from type Sound`; use the other closed source and transform flags instead. Supported `--select` values are `descendants`, `ancestors`, `referencesTo`, `children`, and `parent`; `this` and `owner` remain outside the packaged boundary. In `--where-json`, `=` is exact equality and `:` is a contains/match predicate; when the user says a field must equal an exact value, use `=` even if the source is `--search`. Every broad source (`--type`, `--search`, `--query`) and every `--select` transform requires either `--take N`, where `N` is between `0` and `1000`, or the explicit `--all-results` opt-in. `--take` and `--all-results` cannot be combined. Use `--all-results` only when the user explicitly requests an unbounded result set. Exact path/GUID lookup without a transform remains one-object bounded and needs neither flag. A bounded success that exceeds its `take`, an untransformed exact lookup that returns more than one row, or a fixed `buses` result above 1000 rows is rejected as protocol drift; `--all-results` remains unbounded for genuinely broad queries. The fixed `buses` command uses `take 1000`, reports that bound in its JSON, and marks a 1000-row response as possibly truncated. The gateway defaults to `id,name,type,path`; supplying any `--return-field` replaces that default list, so repeat the flag for every field needed. An untransformed exact `--path` lookup must return `path`, and an exact `--object-id` lookup must return `id`; the gateway normalizes path separators/case or GUID case and rejects a mismatched returned identity. For exact identity inspection, keep those four fields explicit for an exact path/GUID identity lookup. Successful object queries must return a JSON object containing a `return` array of JSON object rows; an invalid response shape or bound is a structured error, never an empty-result substitute. A successful selection must likewise contain an explicit `objects` array whose every row is an object; only `objects: []` means a valid empty selection. `wait-topic` accepts only an exact URI in the reviewed topic allowlist; its JSON match is a recursive payload subset and it always unsubscribes on success or timeout. Its timeout is end-to-end, so the actual event wait reserves a small in-budget cleanup window. On success, `event` is the validated raw WAAPI publish payload, not the dispatcher's internal callback envelope. `object.created` fires before the final name is applied, so do not match it by the requested name. An ActorMixer create reports event type `ActorMixer` in Wwise 2021.1-2024.1 but `PropertyContainer` in Wwise 2025.1; use the version-specific type as a bounded predicate and correlate `event.object.id` with trusted publisher evidence when exact ownership matters. Unreviewed and future topics return `UNSUPPORTED_BY_SKILL_INTERFACE` before subscription.

An invalid response shape is a structured error. It must never be converted into an empty query, Bus list, project, or selection.

## Current selection boundary

For `ak.wwise.ui.getSelectedObjects`, prefer the live selected-object query first when the user asks what is currently selected.

- If the endpoint returns selected object rows, report them clearly.
- If the endpoint returns an empty selection, report that explicit empty selection.
- If the connected endpoint is a headless or command-line WwiseConsole instance where the UI selection API is unavailable, report that boundary clearly and stop. Do not drift into repo/docs research and do not invent a fallback selection result.

## Dispatcher rules

- Do not hard-code a fixed API map in the prompt if versioned manifests and deferred resources can resolve the capability.
- Keep return fields explicit when needed, but pass them as dispatcher `options`, not as raw positional WAAPI arguments.
- Keep timeouts finite; prefer roughly 5–10 seconds unless there is a real reason to wait longer.
- The generic read-only CLI contract contains exactly the two reflection-list rows with `preferred_route: manifest_dispatch`; an explicit request to call either exact row is a direct one-command fast route and never needs a preceding `describe`. Global `--version`, `--timeout`, and `--evidence-dir` precede `call`, while `--args-json`, `--options-json`, `--dry-run`, and the hidden compatibility-only `--allow-destructive` follow the URI. Reads awaiting URI-specific input/work/result validators are explicit unsupported boundaries, not speculative generic calls. Fixed functions, topics, transactions, and unsupported rows are rejected before business dispatch. `--dry-run`, `--allow-destructive`, and `WWISE_DESTRUCTIVE=1` cannot bypass that routing decision.
- Every JSON option is parsed before connecting and is strict and bounded: duplicate keys, non-finite numbers, invalid Unicode, oversized documents/strings, excessive nesting, and excessive node counts fail closed. Do not retry by moving the same payload into inline Python or a helper file.

## Failure rule

There is no raw-client fallback for an ordinary user query. If the packaged gateway cannot perform the request, say that the current Skill interface does not cover it. Only a separate, explicit Skill-development task may change the implementation.
