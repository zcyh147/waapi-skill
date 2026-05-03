# Semantic builder source note: object-mutation, Wwise 2025.1

- family: `object-mutation`
- status: `grounded`
- notebook id: `wwise-2025.1-docs`
- version target: `2025.1`
- gate evidence path: `references/semantic/2025.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_create.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_set.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_delete.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_copy.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_move.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_diff.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_pasteproperties.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_undo_begingroup.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_undo_endgroup.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_undo_undo.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_object_structurechanged.html

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
- `autoCheckOutToSourceControl`
- `notes`
- `children`
- `listMode`
- `pasteMode`
- `inclusion`
- `exclusion`
- `options.return`

## Return shape

Create and set return objects arrays with created or modified object data. Copy and move return object identity fields such as id, name, type, path, and shortId. object.diff returns properties and lists arrays. pasteProperties and undo actions return empty JSON objects.

## Destructive behavior

Mutating. Deleting a Work Unit cannot be undone and automatically saves the project. onNameConflict replace in object.set deletes the destination object and children. listMode replaceAll removes existing objects in that list. pasteMode replaceEntire removes target list elements not present in the source. undo reverts the last operation in the undo stack.

## Ambiguity constraints

Name collisions must be resolved explicitly with onNameConflict modes. For object.create, replace is not supported. object.set list data must be slot-wrapped in 2025.1, such as ArgumentsSlot, MusicArgumentsSlot, EntryPathSlot, MetadataSlot, or PlaylistSlot. Use object.structureChanged for hierarchy updates because it batches object hierarchy changes per undo event.

## Unsupported cases

Do not create Source, Effect, or Metadata plug-ins through object.create; use object.set where supported. Do not create objects in Sequences or Stingers lists through generic set builders when AudioSourceRef or Segment constraints cannot be proven. Do not use deprecated granular topics such as object.created, preDeleted, postDeleted, childAdded, or childRemoved as the primary 2025.1 hierarchy proof when object.structureChanged is available.

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

NotebookLM returned source-grounded required-field details for this family from notebook `wwise-2025.1-docs`, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
