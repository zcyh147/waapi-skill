# Semantic builder source note: object-mutation, Wwise 2023.1

- family: `object-mutation`
- status: `grounded`
- notebook id: `wwise-2023.1-docs`
- version target: `2023.1`
- gate evidence path: `references/semantic/2023.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_create.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_set.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_delete.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_copy.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_move.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_diff.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_object_pasteproperties.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_undo_begingroup.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_undo_endgroup.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_undo_undo.html

## Endpoint inventory

- `ak.wwise.core.object.create`
- `ak.wwise.core.object.set`
- `ak.wwise.core.object.delete`
- `ak.wwise.core.object.copy`
- `ak.wwise.core.object.move`
- `ak.wwise.core.object.diff`
- `ak.wwise.core.object.pasteProperties`
- `ak.wwise.core.undo.beginGroup`
- `ak.wwise.core.undo.endGroup`
- `ak.wwise.core.undo.undo`

## Required fields

- `object.create`: `parent`, `type`, `name`.
- `object.set`: `objects` array.
- `object.delete`: `object`.
- `object.copy`: `object`, `parent`.
- `object.move`: `object`, `parent`.
- `object.diff`: `object`, `other`.
- `object.pasteProperties`: `source`, `target` or `targets` as documented by the endpoint.
- `undo.beginGroup`: no required fields.
- `undo.endGroup`: `displayName`.
- `undo.undo`: no required fields.

## Optional fields

- `onNameConflict`
- `platform`
- `autoAddToSourceControl`
- `notes`
- `children`
- `pasteMode`
- `inclusion`
- `exclusion`
- `options.return`

## Return shape

Mutation endpoints return created or modified object data when requested, often in `objects` or `return` arrays. `object.diff` returns property and list differences. Undo actions return empty JSON objects.

## Destructive behavior

Mutating. Delete operations remove objects. Copying or deleting Work Units can force project save behavior. `onNameConflict=replace` can remove an existing child before replacement. List replacement can clear existing list items.

## Ambiguity constraints

Name conflicts must be handled explicitly with `onNameConflict`. String object identifiers need enough scope to avoid matching the wrong object.

## Unsupported cases

Do not create Query objects or plug-in Source, Effect, or Metadata objects through generic mutation builders. Do not set constraint-based Switch Container assignments through generic object mutation because ordering cannot be proven.

## Cited required fields

- `ak.wwise.core.object.create: parent, type, name`
- `ak.wwise.core.object.set: objects array`
- `ak.wwise.core.object.delete: object`
- `ak.wwise.core.object.copy: object, parent`
- `ak.wwise.core.object.move: object, parent`
- `ak.wwise.core.object.diff: object, other`
- `ak.wwise.core.object.pasteProperties: source and target or targets`
- `ak.wwise.core.undo.beginGroup: no required fields`
- `ak.wwise.core.undo.endGroup: displayName`
- `ak.wwise.core.undo.undo: no required fields`

## Evidence caveat

NotebookLM returned source-grounded required-field details for this family, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
