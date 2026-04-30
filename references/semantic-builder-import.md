# Semantic builder source note: import

- family: `import`
- status: `grounded`
- notebook id: `wwise-2022.1-docs`
- version target: `2022.1`

## NotebookLM gate evidence

- Evidence path: `references/semantic-builder-notebooklm-gate.md`
- Unlock rule: this note unlocks only when `NotebookLMGate` opens that persisted evidence file for notebook id `wwise-2022.1-docs`.

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2024.1.4_8780/?id=ak_wwise_core_audio_import.html
- https://www.audiokinetic.com/library/edge/?source=Help&id=importing_media_files_from_tab_delimited_text_file
- `resources/manifest/2022.1/schemas.json`
- NotebookLM notebook `wwise-2022.1-docs`, cited answer for audio import endpoints.

## Endpoint list

- `ak.wwise.core.audio.import`
- `ak.wwise.core.audio.importTabDelimited`
- `ak.wwise.core.audio.imported`

## Required fields

- `audio.import`: `imports` array.
- `audio.import`: each import item `objectPath`.
- `audio.importTabDelimited`: `importLocation`, `importLanguage`, `importOperation`, `importFile`.
- `audio.imported`: topic payload only.

## Optional fields

- `importOperation`
- `default`
- `autoAddToSourceControl`
- `options.return`
- `options.platform`
- `options.language`
- per-import `audioFile`, `audioFileBase64`, `objectType`, `notes`, `@PropertyName`

## Return shape

Object with an `objects` array describing created or replaced objects according to `options.return`.

## Destructive behavior

Mutating. `replaceExisting` permanently destroys existing objects with the same name before import replacement.

## Ambiguity constraints

String object names must use `type:name` or `Global:shortId`; missing absolute media paths fail import; constrained references should not rely on sequential resolution during import.

## Unsupported cases

Do not use this family for profiler, transport, soundengine, UI, CLI, remote, or debug APIs; do not set Switch Container state constraints through import builders.

## Cited required fields

- `ak.wwise.core.audio.import: imports array`
- `ak.wwise.core.audio.import: each import item objectPath`
- `ak.wwise.core.audio.importTabDelimited: importLocation, importLanguage, importOperation, importFile`
- `ak.wwise.core.audio.imported: topic payload only`
