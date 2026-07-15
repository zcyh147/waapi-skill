# Semantic builder source note: import, Wwise 2024.1

- family: `import`
- status: `grounded`
- notebook id: `wwise-2024.1-docs`
- version target: `2024.1`
- gate evidence path: `references/semantic/2024.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_audio_import.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_audio_importtabdelimited.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_audio_imported.html

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
- `originalsSubFolder`
- `notes`
- `switchAssignation`
- `autoAddToSourceControl`
- `autoCheckOutToSourceControl`
- `audioFileBase64`
- `options.return`
- `per-import objectType and @PropertyName values`

## Return shape

Import and importTabDelimited return log, files, and objects arrays. The imported topic publishes objects, files, and the applied operation string.

## Destructive behavior

Mutating. replaceExisting destroys existing Wwise objects that share names with new imports.

## Ambiguity constraints

Per-import properties take precedence over fallback parameters in default. Base64 audio inputs need a vertical bar separator between the target relative file path and the encoded WAV payload. Import logs must be parsed because commands can report failures through log entries.

## Unsupported cases

Do not use import builders for profiler, transport, soundengine, UI, CLI, remote, or debug APIs. Do not set constraint-based Switch Container associations through generic JSON imports when ordering cannot be proven.

## Cited required fields

- `ak.wwise.core.audio.import: imports array`
- `ak.wwise.core.audio.import: objectPath and audioFile or audioFileBase64 for media import items`
- `ak.wwise.core.audio.importTabDelimited: importLanguage, importOperation, importFile`
- `ak.wwise.core.audio.imported: topic payload only`

## Evidence caveat

NotebookLM returned source-grounded required-field details for this family from the Wwise 2024.1 notebook, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
