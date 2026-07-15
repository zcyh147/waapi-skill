# Semantic builder source note: query, Wwise 2025.1

- family: `query`
- status: `grounded`
- notebook id: `wwise-2025.1-docs`
- version target: `2025.1`
- gate evidence path: `references/semantic/2025.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waql_reference.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_get.html

## Endpoint inventory

- `ak.wwise.core.object.get`

## Required fields

- `ak.wwise.core.object.get: waql text query or deprecated from statement`

## Optional fields

- `options.return`
- `options.platform`
- `options.language`
- `transform for deprecated JSON query bodies`

## Return shape

Object with a return array; each returned item contains fields requested by options.return, such as id, name, type, property accessors, or parent accessors.

## Destructive behavior

Read-only. Query builders must not mutate Wwise state or dispatch automatically.

## Ambiguity constraints

Prefer WAQL because the legacy JSON from and transform query format is deprecated in 2025.1. If platform or language options are omitted, Wwise uses the current platform and current language.

## Unsupported cases

Do not mix WAQL with deprecated JSON query bodies in one source note. Profiler, transport, soundengine, ui, cli, remote, debug, and mutating operations are outside this family.

## Cited required fields

- `ak.wwise.core.object.get: waql text query or deprecated from statement`

## Evidence caveat

NotebookLM returned source-grounded required-field details for this family from notebook `wwise-2025.1-docs`, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
