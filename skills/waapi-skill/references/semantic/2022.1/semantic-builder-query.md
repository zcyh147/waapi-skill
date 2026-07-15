# Semantic builder source note: query

- family: `query`
- status: `grounded`
- notebook id: `wwise-2022.1-docs`
- version target: `2022.1`

## NotebookLM gate evidence

- Evidence path: `references/semantic-builder-notebooklm-gate.md`
- Unlock rule: this note unlocks only when `NotebookLMGate` opens that persisted evidence file for notebook id `wwise-2022.1-docs`.

## Official/source URLs

- https://www.audiokinetic.com/library/2025.1.3_9037/?id=waql_reference.html
- https://www.audiokinetic.com/en/library/edge/?id=ak_wwise_core_object_get.html
- `resources/waql/2022.1/object-get-examples.json`
- NotebookLM notebook `wwise-2022.1-docs`, cited answer for WAQL and `ak.wwise.core.object.get`.

## Endpoint list

- `ak.wwise.core.object.get`

## Required fields

- `ak.wwise.core.object.get`: `waql` or legacy query expression.

## Optional fields

- `options.return`
- `options.platform`
- `options.language`

## Return shape

Object with a `return` array; each returned object contains key-value pairs requested by `options.return`, defaulting to `id` and `name` when no return list is supplied.

## Destructive behavior

Read-only. Query builders must not mutate Wwise state or dispatch automatically.

## Ambiguity constraints

Return fields that do not apply to a matched object can be omitted by Wwise. Legacy JSON queries have poorer error handling than WAQL and should not be preferred.

## Unsupported cases

Profiler, transport, soundengine, UI, CLI, remote, debug, and mutating WAQL-like operations are outside this family.

## Cited required fields

- `ak.wwise.core.object.get: waql or legacy query expression`
