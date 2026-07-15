# Semantic builder source note: query, Wwise 2021.1

- family: `query`
- status: `grounded`
- notebook id: `wwise-2021.1.14-docs`
- version target: `2021.1`
- gate evidence path: `references/semantic/2021.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waql_reference.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_get.html

## Endpoint inventory

- `ak.wwise.core.object.get`

## Required fields

- `ak.wwise.core.object.get: waql or deprecated from/where query`

## Optional fields

- `options.return`
- `options.platform`
- `options.language`

## Return shape

Object with a return array; each returned item contains fields requested by options.return, such as id, name, and property accessors.

## Destructive behavior

Read-only. Query builders must not mutate Wwise state or dispatch automatically.

## Ambiguity constraints

Prefer WAQL because the legacy JSON from and where query format is deprecated in 2021.1. If platform or language options are omitted, Wwise uses the current platform and current language.

## Unsupported cases

Do not mix WAQL with deprecated JSON query bodies in one source note. Profiler, transport, soundengine, UI, CLI, remote, debug, and mutating operations are outside this family.

## Cited required fields

- `ak.wwise.core.object.get: waql or deprecated from/where query`

## Evidence caveat

NotebookLM returned source-grounded 2021.1 details for this family from notebook `wwise-2021.1.14-docs`. Exact full URLs were not directly surfaced in the browser answer, so the URLs above are versioned public-library candidates and exact page ids; they should be treated as source evidence, not behavioral proof.
