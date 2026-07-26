# Semantic builder source note: object-mutation, Wwise 2021.1

- family: `object-mutation`
- status: `grounded`
- notebook id: `wwise-2021.1.14-docs`
- version target: `2021.1`
- gate evidence path: `references/semantic/2021.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_create.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_delete.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_copy.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_object_move.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_undo_begingroup.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_undo_endgroup.html

## Endpoint inventory

- `ak.wwise.core.object.create`
- `ak.wwise.core.object.delete`
- `ak.wwise.core.object.copy`
- `ak.wwise.core.object.move`
- `ak.wwise.core.undo.beginGroup`
- `ak.wwise.core.undo.endGroup`

## Required fields

- `ak.wwise.core.object.create: parent, type, name`
- `ak.wwise.core.object.delete: object`
- `ak.wwise.core.object.copy: object, parent`
- `ak.wwise.core.object.move: object, parent`
- `ak.wwise.core.undo.beginGroup: no required fields`
- `ak.wwise.core.undo.endGroup: displayName`

## Optional fields

- `onNameConflict`
- `platform`
- `autoAddToSourceControl`
- `notes`
- `children`
- `options.return`

## Return shape

Create, copy, and move return object data; delete and undo group calls return empty JSON objects.

## Destructive behavior

Mutating. delete removes objects permanently, and onNameConflict=replace can delete existing destination objects before creation.

## Ambiguity constraints

Name collisions must be resolved explicitly with onNameConflict. String identifiers need enough scope to avoid matching the wrong object.

## Unsupported cases

Do not create Query objects or plug-in Source, Effect, or Metadata objects through generic mutation builders. Do not set constraint-based Switch Container assignments through generic object mutation when ordering cannot be proven.

## Cited required fields

- `ak.wwise.core.object.create: parent, type, name`
- `ak.wwise.core.object.delete: object`
- `ak.wwise.core.object.copy: object, parent`
- `ak.wwise.core.object.move: object, parent`
- `ak.wwise.core.undo.beginGroup: no required fields`
- `ak.wwise.core.undo.endGroup: displayName`

## Evidence caveat

NotebookLM returned source-grounded 2021.1 details for this family from notebook `wwise-2021.1.14-docs`. Exact full URLs were not directly surfaced in the browser answer, so the URLs above are versioned public-library candidates and exact page ids; they should be treated as source evidence, not behavioral proof.
