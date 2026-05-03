# Semantic builder source note: import, Wwise 2025.1

- family: `import`
- status: `grounded`
- notebook id: `wwise-2025.1-docs`
- version target: `2025.1`
- gate evidence path: `references/semantic/2025.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_audio_import.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_audio_importtabdelimited.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_audio_imported.html

## Endpoint inventory

- `ak.wwise.core.audio.import`
- `ak.wwise.core.audio.importTabDelimited`
- `ak.wwise.core.audio.imported`

## Required fields

- `ak.wwise.core.audio.import: imports array`
- `ak.wwise.core.audio.import: objectPath and audioFile or audioFileBase64 for media import items`
- `ak.wwise.core.audio.importTabDelimited: importLanguage, importOperation, importFile`
- `ak.wwise.core.audio.imported: topic payload only`

## Optional fields

- `importOperation`
- `default`
- `importLocation`
- `originalsSubFolder`
- `notes`
- `switchAssignation`
- `autoAddToSourceControl`
- `autoCheckOutToSourceControl`
- `audioFileBase64`
- `options.return`
- `per-import objectType and @PropertyName values`

## Return shape

audio.import returns log, files, and objects arrays. importTabDelimited returns an objects array containing created or modified objects. The imported topic publishes operation, objects, and files.

## Destructive behavior

Mutating. replaceExisting, ReplaceFile, and ReplaceObject can overwrite or destroy existing objects and assets that share imported names.

## Ambiguity constraints

importOperation controls name collisions: createNew makes unique names, useExisting updates matching objects, and replaceExisting overwrites matching objects. Import logs must be parsed because import can report failures through log entries instead of a standard WAAPI error. If useExisting finds a different WAV file name, Wwise can import a new inactive source version.

## Unsupported cases

Do not use import builders for profiler, transport, soundengine, UI, CLI, remote, or debug APIs. Do not set constrained Switch Container assignments through import when ordering cannot be proven. Tab-delimited voice import ignores concurrent operations such as volume adjustments.

## Cited required fields

- `ak.wwise.core.audio.import: imports array`
- `ak.wwise.core.audio.import: objectPath and audioFile or audioFileBase64 for media import items`
- `ak.wwise.core.audio.importTabDelimited: importLanguage, importOperation, importFile`
- `ak.wwise.core.audio.imported: topic payload only`

## Evidence caveat

NotebookLM returned source-grounded required-field details for this family from notebook `wwise-2025.1-docs`, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
