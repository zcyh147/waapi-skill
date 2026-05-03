# Semantic builder source note: query, Wwise 2023.1

- family: `query`
- status: `grounded`
- notebook id: `wwise-2023.1-docs`
- version target: `2023.1`
- gate evidence path: `references/semantic/2023.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://blog.audiokinetic.com/waapi-for-wwise-2023.1/
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waql_reference.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_get.html

## Endpoint inventory

- `ak.wwise.core.object.get`

## Required fields

- `ak.wwise.core.object.get`: `waql` text query, or deprecated legacy query fields such as `from`.

## Optional fields

- `options.return`
- `options.platform`
- `options.language`

## Return shape

Object with a `return` array. Each returned item contains the fields requested by `options.return`, such as `id`, `name`, or property accessors.

## Destructive behavior

Read-only. Query builders must not mutate Wwise state or dispatch automatically.

## Ambiguity constraints

Prefer WAQL because it has better error handling than legacy JSON query syntax. Return accessors can use WAQL aliases, but fields that do not apply to a matched object can be omitted by Wwise.

## Unsupported cases

Do not mix WAQL with the deprecated JSON `from` and transform query format in one source note. Profiler, transport, soundengine, UI, CLI, remote, debug, and mutating operations are outside this family.

## Cited required fields

- `ak.wwise.core.object.get: waql text query or deprecated from statement`

## Evidence caveat

NotebookLM returned a source-grounded answer for this family, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
