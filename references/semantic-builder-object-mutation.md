# Semantic builder source note: object-mutation

- family: `object-mutation`
- status: `grounded`
- notebook id: `wwise-2022.1-docs`
- version target: `2022.1`

## NotebookLM gate evidence

- Evidence path: `references/semantic-builder-notebooklm-gate.md`
- Unlock rule: this note unlocks only when `NotebookLMGate` opens that persisted evidence file for notebook id `wwise-2022.1-docs`.

## Official/source URLs

- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_object_set.html
- `resources/manifest/2022.1/schemas.json`
- NotebookLM notebook `wwise-2022.1-docs`, cited answer for `ak.wwise.core.object.set`.

## Endpoint list

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
- `objects` array.
- Object identifier by id, name, or path.
- `object.delete`: `object`.
- `object.copy`: `object`, `parent`.
- `object.move`: `object`, `parent`.
- `object.diff`: `object`, `other`.
- `object.pasteProperties`: `source`, `target`.
- `undo.beginGroup`: no required fields.
- `undo.endGroup`: `displayName`.
- `undo.undo`: no required fields.

## Optional fields

- `platform`
- `onNameConflict`
- `listMode`
- `autoAddToSourceControl`
- properties and references expressed with `@` fields
- `options.return`

## Return shape

Object containing an `objects` array for modified or created objects, with fields controlled by `options.return`.

## Destructive behavior

Mutating. `onNameConflict=replace` deletes the matched object and children before creation; `listMode=replaceAll` clears existing list items.

## Ambiguity constraints

Name identifiers must be globally unique and use `type:name` or `Global:shortId` where string identity would otherwise be ambiguous.

## Unsupported cases

Do not create Query objects or Source, Effect, or Metadata plug-ins here; do not populate Metadata, Clips, Sequences, or Stingers lists; do not rely on WAAPI creation order for constrained references.

## Cited required fields

- `ak.wwise.core.object.create: parent, type, name`
- `ak.wwise.core.object.set: objects array`
- `ak.wwise.core.object.set: object identifier by id, name, or path`
- `ak.wwise.core.object.delete: object`
- `ak.wwise.core.object.copy: object, parent`
- `ak.wwise.core.object.move: object, parent`
- `ak.wwise.core.object.diff: object, other`
- `ak.wwise.core.object.pasteProperties: source, target`
- `ak.wwise.core.undo.beginGroup: no required fields`
- `ak.wwise.core.undo.endGroup: displayName`
- `ak.wwise.core.undo.undo: no required fields`
