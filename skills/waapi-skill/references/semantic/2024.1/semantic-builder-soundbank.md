# Semantic builder source note: soundbank, Wwise 2024.1

- family: `soundbank`
- status: `grounded`
- notebook id: `wwise-2024.1-docs`
- version target: `2024.1`
- gate evidence path: `references/semantic/2024.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_soundbank_getinclusions.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_soundbank_setinclusions.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_soundbank_generate.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_soundbank_convertexternalsources.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_soundbank_processdefinitionfiles.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_soundbank_generated.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_soundbank_generationdone.html

## Endpoint inventory

- `ak.wwise.core.soundbank.getInclusions`
- `ak.wwise.core.soundbank.setInclusions`
- `ak.wwise.core.soundbank.generate`
- `ak.wwise.core.soundbank.convertExternalSources`
- `ak.wwise.core.soundbank.processDefinitionFiles`
- `ak.wwise.core.soundbank.generated`
- `ak.wwise.core.soundbank.generationDone`

## Required fields

- `ak.wwise.core.soundbank.getInclusions: soundbank`
- `ak.wwise.core.soundbank.setInclusions: soundbank, operation, inclusions`
- `ak.wwise.core.soundbank.generate: no required fields when generating all, otherwise identify supplied soundbanks`
- `ak.wwise.core.soundbank.convertExternalSources: sources array with source input path and platform`
- `ak.wwise.core.soundbank.processDefinitionFiles: files array`
- `ak.wwise.core.soundbank.generated: topic payload only`
- `ak.wwise.core.soundbank.generationDone: topic payload only`

## Optional fields

- `platforms`
- `languages`
- `skipLanguages`
- `soundbanks`
- `rebuildSoundBanks`
- `clearAudioFileCache`
- `writeToDisk`
- `rebuildInitBank`
- `base64 bankData, infoFile, or pluginInfo in generated topic options`

## Return shape

getInclusions returns an inclusions array. setInclusions, convertExternalSources, and processDefinitionFiles return empty JSON objects. generate returns logs. generated publishes soundbank and platform details, with optional embedded bankData, infoFile, or pluginInfo. generationDone publishes logs.

## Destructive behavior

Mutating. setInclusions with replace semantics can clear existing inclusion lists. clearAudioFileCache removes generated audio cache data. Generation can overwrite on-disk bank files.

## Ambiguity constraints

If soundbanks is omitted or empty during generation, Wwise generates all user-defined SoundBanks. Topic notifications alone do not prove generation success, so logs still need review.

## Unsupported cases

Do not include profiler, transport, soundengine, UI, CLI, remote, or debug APIs. Auto-defined SoundBanks cannot be manually specified in the soundbanks array.

## Cited required fields

- `ak.wwise.core.soundbank.getInclusions: soundbank`
- `ak.wwise.core.soundbank.setInclusions: soundbank, operation, inclusions`
- `ak.wwise.core.soundbank.generate: no required fields when generating all, otherwise identify supplied soundbanks`
- `ak.wwise.core.soundbank.convertExternalSources: sources array with source input path and platform`
- `ak.wwise.core.soundbank.processDefinitionFiles: files array`
- `ak.wwise.core.soundbank.generated: topic payload only`
- `ak.wwise.core.soundbank.generationDone: topic payload only`

## Evidence caveat

NotebookLM returned source-grounded required-field details for this family from the Wwise 2024.1 notebook, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
