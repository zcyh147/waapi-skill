# Semantic builder source note: import, Wwise 2023.1

- family: `import`
- status: `grounded`
- notebook id: `wwise-2023.1-docs`
- version target: `2023.1`
- gate evidence path: `references/semantic/2023.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_audio_import.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_audio_importtabdelimited.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_audio_imported.html

## Endpoint inventory

- `ak.wwise.core.audio.import`
- `ak.wwise.core.audio.importTabDelimited`
- `ak.wwise.core.audio.imported`

## Required fields

- `audio.import`: `importOperation` and `imports` array.
- `audio.import`: each import item needs `objectPath` and an audio source such as `audioFile` or `audioFileBase64` when importing media.
- `audio.importTabDelimited`: `importLanguage`, `importOperation`, `importFile`.
- `audio.imported`: topic payload only.

## Optional fields

- `default`
- `originalsSubFolder`
- `notes`
- `switchAssignation`
- `autoAddToSourceControl`
- `autoCheckOutToSourceControl`
- `options.return`
- per-import `objectType` and `@PropertyName` values

## Return shape

Import returns arrays of created or changed objects and imported files, plus log entries that must be checked for warnings or failures. The `imported` topic reports import event payloads.

## Destructive behavior

Mutating. `replaceExisting` permanently destroys existing objects with matching names before replacement.

## Ambiguity constraints

Base64 audio inputs need the documented filename separator before the data stream. Import logs must be parsed because import commands can report failure through log entries rather than hard errors.

## Unsupported cases

Do not use import builders for profiler, transport, soundengine, UI, CLI, remote, or debug APIs. Do not set constraint-based Switch Container associations through import because assignment order cannot be proven.

## Cited required fields

- `ak.wwise.core.audio.import: importOperation and imports array`
- `ak.wwise.core.audio.import: objectPath and audioFile or audioFileBase64 for media import items`
- `ak.wwise.core.audio.importTabDelimited: importLanguage, importOperation, importFile`
- `ak.wwise.core.audio.imported: topic payload only`

## Evidence caveat

NotebookLM returned source-grounded required-field details for this family, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
