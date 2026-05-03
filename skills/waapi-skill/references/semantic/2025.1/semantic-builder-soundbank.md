# Semantic builder source note: soundbank, Wwise 2025.1

- family: `soundbank`
- status: `grounded`
- notebook id: `wwise-2025.1-docs`
- version target: `2025.1`
- gate evidence path: `references/semantic/2025.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_soundbank_getinclusions.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_soundbank_setinclusions.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_soundbank_generate.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_soundbank_convertexternalsources.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_soundbank_processdefinitionfiles.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_soundbank_generated.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=ak_wwise_core_soundbank_generationdone.html

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
- `ak.wwise.core.soundbank.convertExternalSources: sources array with input path and platform`
- `ak.wwise.core.soundbank.processDefinitionFiles: files array`
- `ak.wwise.core.soundbank.generated: topic payload only`
- `ak.wwise.core.soundbank.generationDone: topic payload only`

## Optional fields

- `platforms`
- `languages`
- `skipLanguages`
- `soundbanks`
- `events, auxBusses, inclusions, and rebuild inside supplied soundbank entries`
- `rebuildSoundBanks`
- `clearAudioFileCache`
- `writeToDisk`
- `rebuildInitBank`
- `sources output path for convertExternalSources`
- `infoFile, bankData, pluginInfo, and return array for generated topic options`

## Return shape

getInclusions returns an inclusions array. setInclusions and convertExternalSources return empty JSON objects. processDefinitionFiles reports status through the WAAPI log. generate returns logs and error fields. generated publishes the soundbank object with optional infoFile, bankData, or pluginInfo. generationDone publishes logs and a deprecated error string.

## Destructive behavior

Mutating. setInclusions with replace and an empty list clears SoundBank inclusions. clearAudioFileCache deletes the entire Wwise audio file cache before conversion. Generation can overwrite on-disk bank and media files.

## Ambiguity constraints

If soundbanks is omitted or empty during generation, Wwise generates all user-defined SoundBanks. Auto-defined SoundBanks cannot be manually specified in the soundbanks array because they are always generated. generated can publish multiple times during one generation request. generationDone is not reliable proof that soundbank.generate has fully completed, and logs must be parsed instead of the deprecated error field.

## Unsupported cases

Do not include profiler, transport, soundengine, UI, CLI, remote, or debug APIs. Do not treat ak.soundengine.loadBank or unloadBank as 2025.1 authoring semantic-builder evidence. Do not assume object size fields such as totalSize, mediaSize, objectSize, or structureSize are accurate until SoundBanks have been generated.

## Cited required fields

- `ak.wwise.core.soundbank.getInclusions: soundbank`
- `ak.wwise.core.soundbank.setInclusions: soundbank, operation, inclusions`
- `ak.wwise.core.soundbank.generate: no required fields when generating all, otherwise identify supplied soundbanks`
- `ak.wwise.core.soundbank.convertExternalSources: sources array with input path and platform`
- `ak.wwise.core.soundbank.processDefinitionFiles: files array`
- `ak.wwise.core.soundbank.generated: topic payload only`
- `ak.wwise.core.soundbank.generationDone: topic payload only`

## Evidence caveat

NotebookLM returned source-grounded required-field details for this family from notebook `wwise-2025.1-docs`, but official URL pages are recorded as evidence candidates unless separately fetched and archived.
