# Semantic builder source note: import, Wwise 2021.1

- family: `import`
- status: `grounded`
- notebook id: `wwise-2021.1.14-docs`
- version target: `2021.1`
- gate evidence path: `references/semantic/2021.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_audio_import.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_audio_importtabdelimited.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_audio_imported.html
- https://www.audiokinetic.com/library/edge/?source=Help&id=importing_media_files_from_tab_delimited_text_file

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
- `audioFileBase64`
- `options.return`
- `per-import objectType and @PropertyName values`

## Return shape

Import and importTabDelimited return an optional objects array. imported publishes the required objects array for the completed import operation.

## Destructive behavior

Mutating. replaceExisting, ReplaceFile, and ReplaceObject can overwrite or destroy existing objects and assets that share imported names.

## Ambiguity constraints

Per-import properties take precedence over fallback parameters. Base64 audio inputs need a vertical bar separator between the target relative file path and the encoded WAV payload.

## Unsupported cases

Do not use import builders for profiler, transport, soundengine, UI, CLI, remote, or debug APIs. Do not set constraint-based Switch Container associations through import when ordering cannot be proven.

## Cited required fields

- `ak.wwise.core.audio.import: imports array`
- `ak.wwise.core.audio.import: objectPath and audioFile or audioFileBase64 for media import items`
- `ak.wwise.core.audio.importTabDelimited: importLanguage, importOperation, importFile`
- `ak.wwise.core.audio.imported: topic payload only`

## Evidence caveat

NotebookLM returned source-grounded 2021.1 details for this family from notebook `wwise-2021.1.14-docs`. Exact full URLs were not directly surfaced in the browser answer, so the URLs above are versioned public-library candidates and exact page ids; they should be treated as source evidence, not behavioral proof.
