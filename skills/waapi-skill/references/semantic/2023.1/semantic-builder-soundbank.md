# Semantic builder source note: soundbank, Wwise 2023.1

- family: `soundbank`
- status: `grounded`
- notebook id: `wwise-2023.1-docs`
- version target: `2023.1`
- gate evidence path: `references/semantic/2023.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_soundbank_getinclusions.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_soundbank_setinclusions.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_soundbank_generate.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_soundbank_convertexternalsources.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_soundbank_processdefinitionfiles.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=ak_wwise_core_soundbank_generated.html

## Endpoint inventory

- `ak.wwise.core.soundbank.getInclusions`
- `ak.wwise.core.soundbank.setInclusions`
- `ak.wwise.core.soundbank.generate`
- `ak.wwise.core.soundbank.convertExternalSources`
- `ak.wwise.core.soundbank.processDefinitionFiles`
- `ak.wwise.core.soundbank.generated`
- `ak.wwise.core.soundbank.generationDone`

## Required fields

- `getInclusions`: `soundbank`.
- `setInclusions`: `soundbank`, `operation`, `inclusions`.
- `generate`: no required fields when generating all user-defined SoundBanks, otherwise supplied SoundBank entries must identify the target banks.
- `convertExternalSources`: `sources` array, with each source carrying required input details.
- `processDefinitionFiles`: `files` array.
- `generated`: topic payload only.
- `generationDone`: topic payload only and retained here as a guarded compatibility topic.

## Optional fields

- `platforms`
- `languages`
- `skipLanguages`
- `soundbanks`
- `rebuildSoundBanks`
- `clearAudioFileCache`
- `writeToDisk`
- `rebuildInitBank`
- generated topic payload options such as bank data or info file flags

## Return shape

`getInclusions` returns inclusion arrays. `setInclusions` returns an empty JSON object. `generate` and generation topics return logs or generated bank payload details depending on options.

## Destructive behavior

Mutating. `setInclusions` with replace semantics clears existing inclusion lists. `clearAudioFileCache` removes generated audio cache data.

## Ambiguity constraints

If `soundbanks` is omitted or empty during generation, Wwise can generate all user-defined SoundBanks. Topic notifications are not enough by themselves to prove generation success without checking logs or returned payloads.

## Unsupported cases

Do not include profiler, transport, soundengine, UI, CLI, remote, or debug APIs. Do not treat auto-defined SoundBanks as manually specified SoundBanks for WAAPI generation.

## Cited required fields

- `ak.wwise.core.soundbank.getInclusions: soundbank`
- `ak.wwise.core.soundbank.setInclusions: soundbank, operation, inclusions`
- `ak.wwise.core.soundbank.generate: no required fields when generating all, otherwise identify supplied soundbanks`
- `ak.wwise.core.soundbank.convertExternalSources: sources array with source input details`
- `ak.wwise.core.soundbank.processDefinitionFiles: files array`
- `ak.wwise.core.soundbank.generated: topic payload only`
- `ak.wwise.core.soundbank.generationDone: topic payload only`

## Evidence caveat

NotebookLM said `generationDone` was not listed in the provided 2023.1 sources while existing builders track it as a guarded topic. This note keeps the endpoint in inventory for compatibility and marks the detail for later manifest confirmation.
