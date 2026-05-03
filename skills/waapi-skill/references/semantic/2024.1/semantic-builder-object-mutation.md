# Semantic builder source note: object-mutation, Wwise 2024.1

- family: `object-mutation`
- status: `grounded`
- notebook id: `wwise-2024.1-docs`
- version target: `2024.1`
- gate evidence path: `references/semantic/2024.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_create.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_set.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_delete.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_copy.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_move.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_diff.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_pasteproperties.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_undo_begingroup.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_undo_endgroup.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_undo_undo.html

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

- `ak.wwise.core.object.create: parent, type, name`
- `ak.wwise.core.object.set: objects array`
- `ak.wwise.core.object.delete: object`
- `ak.wwise.core.object.copy: object, parent`
- `ak.wwise.core.object.move: object, parent`
- `ak.wwise.core.object.diff: source, target`
- `ak.wwise.core.object.pasteProperties: source, targets array`
- `ak.wwise.core.undo.beginGroup: no required fields`
- `ak.wwise.core.undo.endGroup: displayName`
- `ak.wwise.core.undo.undo: no required fields`

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

Create and set return objects arrays with created or modified object data. Copy and move return object identity fields such as id, name, type, shortId, filePath, and workunit. object.diff returns properties and lists arrays. pasteProperties and undo actions return empty JSON objects.

## Destructive behavior

Mutating. Delete removes objects, and deleting a Work Unit can save the project and cannot be undone. onNameConflict replace can remove an existing child before replacement. pasteMode replaceEntire can clear list entries not present in the source.

## Ambiguity constraints

Name collisions must be resolved explicitly with onNameConflict modes such as rename, replace, merge, or fail. String object identifiers need enough scope to avoid matching the wrong object.

## Unsupported cases

Do not create Query objects or plug-in Source, Effect, or Metadata objects through generic mutation builders. Do not set constraint-based Switch Container assignments through generic object mutation because ordering cannot be proven.

## Cited required fields

- `ak.wwise.core.object.create: parent, type, name`
- `ak.wwise.core.object.set: objects array`
- `ak.wwise.core.object.delete: object`
- `ak.wwise.core.object.copy: object, parent`
- `ak.wwise.core.object.move: object, parent`
- `ak.wwise.core.object.diff: source, target`
- `ak.wwise.core.object.pasteProperties: source, targets array`
- `ak.wwise.core.undo.beginGroup: no required fields`
- `ak.wwise.core.undo.endGroup: displayName`
- `ak.wwise.core.undo.undo: no required fields`

## Evidence caveat

NotebookLM returned source-grounded required-field details for this family from the Wwise 2024.1 notebook, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
